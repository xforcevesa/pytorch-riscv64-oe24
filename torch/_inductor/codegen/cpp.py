import contextlib
import dataclasses
import functools
import itertools
import logging
import math
import re
import sys
from copy import copy, deepcopy
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import sympy

import torch
import torch.fx
from torch._inductor import dependencies
from torch._inductor.ir import StorageBox, TensorBox
from torch._prims_common import is_float_dtype
from torch.utils import _pytree as pytree
from torch.utils._sympy.functions import FloorDiv, ModularIndexing
from torch.utils._sympy.value_ranges import bound_sympy, ValueRanges

from .. import codecache, config, ir, metrics
from ..codegen.wrapper import WrapperCodeGen
from ..optimize_indexing import range_expressable_in_32_bits
from ..scheduler import (
    BaseScheduling,
    ForeachKernelSchedulerNode,
    FusedSchedulerNode,
    SchedulerNode,
)
from ..utils import (
    cache_on_self,
    get_fused_kernel_name,
    is_welford_reduction,
    parallel_num_threads,
    sympy_index_symbol,
    sympy_product,
    sympy_subs,
)

from ..virtualized import ops, OpsValue, V
from .common import (
    BracesBuffer,
    CppWrapperKernelArgs,
    CSE,
    CSEVariable,
    DataTypePropagation,
    DeferredLine,
    DTYPE_TO_COMPUTATION_DTYPE,
    ExprPrinter,
    IndentedBuffer,
    Kernel,
    KernelArgs,
    OpOverrides,
    OptimizationContext,
)

schedule_log = torch._logging.getArtifactLogger(__name__, "schedule")

DTYPE_TO_CPP = {
    torch.float32: "float",
    torch.float64: "double",
    torch.float16: "half",
    torch.int64: "long",
    torch.int32: "int",
    torch.int16: "short",
    torch.int8: "signed char",
    torch.uint64: "unsigned long",
    torch.uint32: "unsigned int",
    torch.uint16: "unsigned short",
    torch.uint8: "unsigned char",
    torch.uint32: "unsigned int",
    torch.uint64: "unsigned long",
    torch.bool: "bool",
    torch.bfloat16: "bfloat16",
    torch.complex64: "complex64",
    torch.float8_e4m3fn: "float8_e4m3fn",
    torch.float8_e5m2: "float8_e5m2",
}

DTYPE_TO_ATEN = {
    torch.float32: "at::kFloat",
    torch.float64: "at::kDouble",
    torch.float16: "at::kHalf",
    torch.int64: "at::kLong",
    torch.int32: "at::kInt",
    torch.int16: "at::kShort",
    torch.int8: "at::kChar",
    torch.uint64: "at::kUInt64",
    torch.uint32: "at::kUInt32",
    torch.uint16: "at::kUInt16",
    torch.uint8: "at::kByte",
    torch.uint32: "at::kUInt32",
    torch.uint64: "at::kUInt64",
    torch.bool: "at::kBool",
    torch.bfloat16: "at::kBFloat16",
    torch.complex32: "at::kComplexHalf",
    torch.complex64: "at::kComplexFloat",
    torch.complex128: "at::kComplexDouble",
    torch.float8_e4m3fn: "at::kFloat8_e4m3fn",
    torch.float8_e5m2: "at::kFloat8_e5m2",
    torch.float8_e4m3fnuz: "at::kFloat8_e4m3fnuz",
    torch.float8_e5m2fnuz: "at::kFloat8_e5m2fnuz",
}

DEVICE_TO_ATEN = {
    "cpu": "at::kCPU",
    "cuda": "at::kCUDA",
}

INDEX_TYPE = "long"

NATIVE_OMP_RTYPES = {"+", "*", "^", "||", "min", "max"}
RTYPE_TO_CPP = {
    "sum": "+",
    "prod": "*",
    "xor_sum": "^",
    "min": "min",
    "max": "max",
    "argmin": "argmin",
    "argmax": "argmax",
    "any": "||",
    "welford_reduce": "welford",
    "welford_combine": "welford",
}
VECTORIZABLE_RTYPES = {
    "max",
    "min",
    "sum",
    "prod",
    "xor_sum",
    "welford_reduce",
    "welford_combine",
}

PYTHON_TO_CPP = {
    "Tensor": "at::Tensor",
    "int": "long",
    "float": "double",
    "bool": "bool",
    "str": "std::string",
    "ScalarType": "c10::ScalarType",
    "MemoryFormat": "at::MemoryFormat",
    "Layout": "at::Layout",
    "Device": "at::Device",
    "number": "at::Scalar",
}

CONTAINER_PYTHON_TO_CPP = {
    "List": "std::vector",
    "Optional": "c10::optional",
}

DTYPE_LOWP_FP = [
    torch.bfloat16,
    torch.float16,
]


def value_to_cpp(value, cpp_type):
    if value == float("-inf"):
        return f"-std::numeric_limits<{cpp_type}>::infinity()"
    elif value == float("inf"):
        return f"std::numeric_limits<{cpp_type}>::infinity()"
    elif isinstance(value, bool):
        return f"static_cast<{cpp_type}>({str(value).lower()})"
    elif math.isnan(value):
        return f"std::numeric_limits<{cpp_type}>::quiet_NaN()"
    else:
        return f"static_cast<{cpp_type}>({repr(value)})"


def reduction_init(reduction_type, dtype):
    if dtype in DTYPE_LOWP_FP:
        # Since load promotes all half-precision inputs to float, the initial
        # constant for reduction must be promoted as well
        dtype = torch.float32
    if reduction_type in ("xor_sum", "sum", "any"):
        return 0
    if reduction_type == "prod":
        return 1
    if reduction_type in {"max", "argmax"}:
        return (
            f"-std::numeric_limits<{DTYPE_TO_CPP[dtype]}>::infinity()"
            if is_float_dtype(dtype)
            else f"std::numeric_limits<{DTYPE_TO_CPP[dtype]}>::min()"
        )
    if reduction_type in {"min", "argmin"}:
        return (
            f"std::numeric_limits<{DTYPE_TO_CPP[dtype]}>::infinity()"
            if is_float_dtype(dtype)
            else f"std::numeric_limits<{DTYPE_TO_CPP[dtype]}>::max()"
        )
    if is_welford_reduction(reduction_type):
        return f"Welford<{DTYPE_TO_CPP[dtype]}>()"
    raise AssertionError(reduction_type)


def reduction_acc_type(reduction_type, dtype):
    assert reduction_type not in {"argmin", "argmax"}
    scalar_type = DTYPE_TO_CPP[DTYPE_TO_COMPUTATION_DTYPE[dtype]]
    if is_welford_reduction(reduction_type):
        return f"Welford<{scalar_type}>"

    return scalar_type


def reduction_combine(reduction_type, var, next_value):
    if reduction_type == "sum":
        return f"{var} + {next_value}"
    if reduction_type == "prod":
        return f"{var} * {next_value}"
    if reduction_type == "xor_sum":
        return f"{var} ^ {next_value}"
    if reduction_type == "any":
        return f"{var} || {next_value}"
    if reduction_type in ("min", "max"):
        return f"{reduction_type}_propagate_nan({var}, {next_value})"
    if reduction_type == "welford_reduce":
        return f"welford_combine({var}, {next_value})"
    if reduction_type == "welford_combine":
        if isinstance(next_value, tuple):
            mean, m2, weight = next_value
        else:
            mean, m2, weight = reduction_project(reduction_type, next_value)
        return f"welford_combine({var}, {{{mean}, {m2}, {weight}}})"
    raise AssertionError(reduction_type)


def reduction_project(reduction_type, acc):
    if is_welford_reduction(reduction_type):
        return f"{acc}.mean", f"{acc}.m2", f"{acc}.weight"
    elif reduction_type in {"argmin", "argmax"}:
        return f"{acc}.index"
    return acc


def is_to_lowp_dtype(expr):
    to_exprs = ["cvt_fp32_to_lowp_fp", "c10::convert"]
    if any(to_expr in expr for to_expr in to_exprs):
        if "half" in expr:
            return torch.half
        if "bfloat16" in expr:
            return torch.bfloat16
    return None


def get_lowp_to_fp32_expr(lowp_var, src_dtype, kernel):
    if isinstance(kernel, CppVecKernel):
        return f"cvt_lowp_fp_to_fp32<{DTYPE_TO_CPP[src_dtype]}>({lowp_var})"
    else:
        assert isinstance(kernel, CppKernel)
        return f"c10::convert<float>({lowp_var})"


index_value_name_counter = 1


def argmax_argmin_prefix(reduction_type, src_dtype, tmpvar):
    global index_value_name_counter
    struct_name = f"IndexValue_{index_value_name_counter}"
    index_value_name_counter += 1

    # A small annoyance, due to it being a little cumbersome to just throw {} into strings
    prefix = [
        f"struct {struct_name} {{size_t index; {DTYPE_TO_CPP[src_dtype]} value;}};",
        f"{struct_name} {tmpvar}{{0, {reduction_init(reduction_type, src_dtype)}}};",
    ]

    if reduction_type in ["argmax", "argmin"]:
        compare_op = "greater_or_nan" if reduction_type == "argmax" else "less_or_nan"
        prefix.extend(
            [
                "#if !defined(__clang_major__) || __clang_major__ > 9",
                f"#pragma omp declare reduction({reduction_type} : {struct_name} :\\",
                f"    omp_out = {compare_op}(omp_in.value, omp_out.value, omp_in.index, omp_out.index) ? omp_in : omp_out)\\",
                f"\tinitializer(omp_priv = {{0, {reduction_init(reduction_type, src_dtype)}}})",
                "#endif",
            ]
        )

    return prefix


@functools.lru_cache
def stride_at(index: sympy.Expr, var: sympy.Symbol):
    replacement = {var: var + 1}
    new_index = sympy_subs(index, replacement)  # type: ignore[arg-type]
    return sympy.simplify(new_index - index)


@functools.lru_cache
def simplify_index_in_vec_range(index: sympy.Expr, var: sympy.Expr, vec_length: int):
    """
    Simplifies the index expression within the range of a vectorized loop.
    Given a vectorized loop variable `var` in the range of a loop with `vec_length`,
    this function transforms the `index` into an equivalent form. It handles
    simplifications for cases where `var` can be expressed as `vec_length * a + b`,
    where `b` ranges from 0 to `vec_length - 1`. The function reduces occurrences
    of `FloorDiv` and `ModularIndexing` in the `index` with best-effort optimizations.

    NOTE:
    The simplified index expression is intended for analysis purposes only, not
    for code generation. It replaces `FloorDiv` and `ModularIndexing` with free variables
    which are not dependent on the loop variable `var` in the vectorized range. Check
    https://github.com/pytorch/pytorch/pull/117221#discussion_r1449746217 for more details.

    Examples:
    1. If `var` is `x3` and `vec_length` is 16, and `x3 = 16*a + b`, then
       `FloorDiv(x3, div)` or `ModularIndexing(x3, div, mod)` becomes a free variable
       when `div` is divisible by 16.
    2. `ModularIndexing(x3, 1, mod)` can be simplified to `x3 + c` where `c` is a free
       variable when `mod` is divisible by 16.
    """

    div_freevar_id = 0
    mod_freevar_id = 0

    def visit_indexing_div(divisor):
        nonlocal div_freevar_id
        result = FloorDiv(var, divisor)
        if sympy.gcd(divisor, vec_length) == vec_length:
            result = sympy.Symbol(f"{var}_div_c{div_freevar_id}")
            div_freevar_id += 1
        return result

    def visit_modular_indexing(divisor, modulus):
        nonlocal mod_freevar_id
        result = ModularIndexing(var, divisor, modulus)
        if sympy.gcd(divisor, vec_length) == vec_length:
            result = sympy.Symbol(f"{var}_mod_c{mod_freevar_id}")
            mod_freevar_id += 1
        elif divisor == 1 and sympy.gcd(modulus, vec_length) == vec_length:
            result = var + sympy.Symbol(f"{var}_mod_c{mod_freevar_id}")
            mod_freevar_id += 1
        return result

    original_index = index

    div = sympy.Wild("divisor")
    if index.has(FloorDiv):
        index = index.replace(FloorDiv(var, div), visit_indexing_div)

    mod = sympy.Wild("modulus")
    if index.has(ModularIndexing):
        index = index.replace(ModularIndexing(var, div, mod), visit_modular_indexing)

    index = sympy.simplify(index)
    if index != original_index:
        return simplify_index_in_vec_range(index, var, vec_length)

    return index


@functools.lru_cache
def stride_at_vec_range(index: sympy.Expr, var: sympy.Symbol, vec_length: int):
    index_vec_simplified = simplify_index_in_vec_range(index, var, vec_length)
    return stride_at(index_vec_simplified, var)


class CppPrinter(ExprPrinter):
    def _print_Integer(self, expr):
        return f"{int(expr)}L"

    def _print_Where(self, expr):
        c = self.paren(self.doprint(expr.args[0]))
        p = self.paren(self.doprint(expr.args[1]))
        q = self.paren(self.doprint(expr.args[2]))
        return f"{c} ? {p} : {q}"

    def _print_ModularIndexing(self, expr):
        x, div, mod = expr.args
        x = self.paren(self.doprint(x))
        if div != 1:
            div = self.paren(self.doprint(div))
            if expr.is_integer:
                x = f"c10::div_floor_integer({x}, {div})"
            else:
                x = f"c10::div_floor_floating(static_cast<double>({x}), static_cast<double>({div}))"
        mod = self.paren(self.doprint(mod))
        return f"static_cast<{INDEX_TYPE}>({x}) % static_cast<{INDEX_TYPE}>({mod})"

    def _print_FloorDiv(self, expr):
        x, div = expr.args
        x = self.paren(self.doprint(x))
        div = self.paren(self.doprint(div))
        if expr.is_integer:
            return f"c10::div_floor_integer({x}, {div})"
        return f"c10::div_floor_floating(static_cast<double>({x}), static_cast<double>({div}))"

    def _print_floor(self, expr):
        assert len(expr.args) == 1
        r = f"std::floor({self._print(expr.args[0])})"
        return f"static_cast<{INDEX_TYPE}>({r})" if expr.is_integer else r

    def _print_Pow(self, expr):
        # Uses float constants to perform FP div
        base, exp = expr.args
        base = self._print(base)

        if exp == 0.5 or exp == -0.5:
            return f"std::sqrt({base})" if exp == 0.5 else f"1.0/std::sqrt({base})"
        assert exp.is_integer
        exp = int(exp)
        if exp > 0:
            r = "*".join([self.paren(base)] * exp)
        elif exp < 0:
            r = "1.0/" + self.paren("*".join([self.paren(base)] * abs(exp)))
        else:  # exp == 0
            r = "1.0"

        return f"static_cast<{INDEX_TYPE}>({r})" if expr.is_integer else r

    def _print_Rational(self, expr):
        # Uses float constants to perform FP div
        if expr.q == 1:
            r = f"{expr.p}"
        else:
            r = f"{expr.p}.0/{expr.q}.0"
        return f"static_cast<{INDEX_TYPE}>({r})" if expr.is_integer else r

    def _print_ceiling(self, expr):
        assert len(expr.args) == 1
        r = f"std::ceil({self._print(expr.args[0])})"
        return f"static_cast<{INDEX_TYPE}>({r})" if expr.is_integer else r

    def _print_Min(self, expr):
        args = [self._print(a) for a in expr.args]
        if len(args) == 2:
            return f"std::min({args[0]}, {args[1]})"
        else:
            # Initializer list overload
            il = "{" + ", ".join(args) + "}"
            return f"std::min({il})"

    def _print_Max(self, expr):
        args = [self._print(a) for a in expr.args]
        if len(args) == 2:
            return f"std::max({args[0]}, {args[1]})"
        else:
            # Initializer list overload
            il = "{" + ", ".join(args) + "}"
            return f"std::max({il})"

    def _print_Abs(self, expr):
        assert len(expr.args) == 1
        return f"std::abs({self._print(expr.args[0])})"

    def _print_cos(self, expr):
        assert len(expr.args) == 1
        return f"std::cos({self._print(expr.args[0])})"

    def _print_cosh(self, expr):
        assert len(expr.args) == 1
        return f"std::cosh({self._print(expr.args[0])})"

    def _print_acos(self, expr):
        assert len(expr.args) == 1
        return f"std::acos({self._print(expr.args[0])})"

    def _print_sin(self, expr):
        assert len(expr.args) == 1
        return f"std::sin({self._print(expr.args[0])})"

    def _print_sinh(self, expr):
        assert len(expr.args) == 1
        return f"std::sinh({self._print(expr.args[0])})"

    def _print_asin(self, expr):
        assert len(expr.args) == 1
        return f"std::asin({self._print(expr.args[0])})"

    def _print_tan(self, expr):
        assert len(expr.args) == 1
        return f"std::tan({self._print(expr.args[0])})"

    def _print_tanh(self, expr):
        assert len(expr.args) == 1
        return f"std::tanh({self._print(expr.args[0])})"

    def _print_atan(self, expr):
        assert len(expr.args) == 1
        return f"std::atan({self._print(expr.args[0])})"

    def _print_Round(self, expr):
        assert len(expr.args) == 1
        return f"std::lrint({self._print(expr.args[0])})"

    def _print_RoundDecimal(self, expr):
        assert len(expr.args) == 2
        number, ndigits = expr.args
        if number.is_integer:
            # ndigits < 0 should have been filtered by the sympy function
            assert ndigits < 0
            raise ValueError(
                f"For integer inputs, only non-negative ndigits are currently supported, but got {ndigits}."
            )
        return f"static_cast<double>(std::nearbyint(1e{ndigits} * {self.paren(self._print(number))}) * 1e{-ndigits})"


# A function to print, useful for printing sympy symbols.
cexpr = CppPrinter().doprint


def cexpr_index(index):
    return f"static_cast<{INDEX_TYPE}>({cexpr(index)})"


class RecordOptimizationContext:
    def __init__(self, func_name: str = ""):
        self.func_name = func_name
        self.current_node: Optional[torch.fx.Node] = None
        self.opt_ctx: Optional[OptimizationContext] = None

    def __enter__(self):
        assert V.interpreter
        assert V.interpreter.current_node

        self.current_node = V.interpreter.current_node
        assert self.current_node is not None
        if OptimizationContext.key in self.current_node.meta:
            self.opt_ctx = self.current_node.meta[OptimizationContext.key]
        else:
            self.opt_ctx = OptimizationContext()
        assert self.opt_ctx is not None
        self.opt_ctx.ops_name = self.func_name
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        assert self.current_node
        assert self.opt_ctx
        self.current_node.meta[OptimizationContext.key] = self.opt_ctx

    def get_opt_ctx(self):
        return self.opt_ctx

    def get_fx_node(self):
        assert self.current_node
        return self.current_node


def get_opt_ctx(node: torch.fx.Node) -> OptimizationContext:
    return node.meta.get(OptimizationContext.key, None)


def get_current_node_opt_ctx() -> OptimizationContext:
    assert V.interpreter.current_node
    return get_opt_ctx(V.interpreter.current_node)


class CppVecUnsupportedError(Exception):
    pass


class CppCSEVariable(CSEVariable):
    def __init__(self, name, bounds: ValueRanges[Any]):
        super().__init__(name, bounds)
        self.is_vec = False
        self.dtype: Optional[torch.dtype] = None
        self.dependent_itervars: Set[sympy.Symbol] = set()

    def update_on_args(self, name, args, kwargs):
        if name == "load":
            # args[1] is index
            self._set_dependent_itervars(args[1])
        else:
            # propagate relevant itervars and is_vec from args
            self.dependent_itervars.update(
                *[
                    arg.dependent_itervars
                    for arg in args
                    if isinstance(arg, CppCSEVariable)
                ]
            )
            if name == "index_expr":
                self._set_dependent_itervars(args[0])
            if any(arg.is_vec for arg in args if isinstance(arg, CppCSEVariable)):
                self.is_vec = True
        # NOTE [dtype of CppCSEVariable]
        # Deciding dtype according to the current optimization context is not
        # always accurate since the dtypes are initialized during dtype propagation
        # at the beginning of the codegen. It is possible that some ops are invoked
        # during the codegen of the current op and take different dtypes from the
        # current op.
        # TODO(jgong5): A more accurate way of deciding the dtype of the variables is to
        # propagate the dtypes here inside `update_on_args`.
        if (
            hasattr(V.interpreter, "current_node")
            and get_current_node_opt_ctx() is not None
        ):
            self.dtype = get_current_node_opt_ctx().dtype

    def _set_dependent_itervars(self, index: sympy.Expr):
        """
        Set the relevant itervars for this variable based on the `index` expression.
        This includes the itervars directly used in the `index` as well as relevant itervars
        of other cse variables used in the `index`.
        """
        for s in index.free_symbols:
            if s in V.kernel.itervars:
                self.dependent_itervars.add(s)  # type: ignore[arg-type]
            elif s.name in V.kernel.cse.varname_map:  # type: ignore[attr-defined]
                self.dependent_itervars.update(
                    V.kernel.cse.varname_map[s.name].dependent_itervars  # type: ignore[attr-defined]
                )

    def depends_on(self, itervar: sympy.Symbol):
        return itervar in self.dependent_itervars


class CppOverrides(OpOverrides):
    """Map element-wise ops to C++"""

    @staticmethod
    def add(a, b):
        return f"decltype({a})({a} + {b})"

    @staticmethod
    def sub(a, b):
        return f"decltype({a})({a} - {b})"

    @staticmethod
    def mul(a, b):
        return f"decltype({a})({a} * {b})"

    @staticmethod
    def to_dtype(x, dtype, src_dtype=None):
        assert dtype in DTYPE_TO_CPP, f"{dtype} missing from {__name__}.DTYPE_TO_CPP"
        return f"c10::convert<{DTYPE_TO_CPP[dtype]}>({x})"

    @staticmethod
    def to_dtype_bitcast(x, dtype, src_dtype):
        assert dtype in DTYPE_TO_CPP, f"{dtype} missing from {__name__}.DTYPE_TO_CPP"
        if src_dtype in (torch.float16, torch.bfloat16):
            # c10::bit_cast requires the source and target have the bitwidth.
            # Because the input tensor's dtype could be promoted, e.g. from float16 to
            # float, we have to cast the tensor to its original source dtype before
            # invoking bit_cast. We also need to convert the bit-casted tensor
            # back to float to make sure we keep using higher precision values
            # for the rest of the computation.
            cast_x = f"c10::convert<{DTYPE_TO_CPP[src_dtype]}>({x})"
            cast_x = f"c10::bit_cast<{DTYPE_TO_CPP[dtype]}>({cast_x})"
            return f"c10::convert<{DTYPE_TO_CPP[torch.float32]}>({cast_x})"
        else:
            return f"c10::bit_cast<{DTYPE_TO_CPP[dtype]}>({x})"

    @staticmethod
    def abs(x):
        return f"std::abs({x})"

    @staticmethod
    def sin(x):
        return f"std::sin({x})"

    @staticmethod
    def cos(x):
        return f"std::cos({x})"

    @staticmethod
    def neg(x):
        return f"decltype({x})(-{x})"

    @staticmethod
    def exp(x):
        # return f"Sleef_expf_u10({x})"
        return f"std::exp({x})"

    @staticmethod
    def exp2(x):
        return f"std::exp2({x})"

    @staticmethod
    def expm1(x):
        return f"std::expm1({x})"

    @staticmethod
    def erf(x):
        return f"std::erf({x})"

    @staticmethod
    def erfc(x):
        return f"std::erfc({x})"

    @staticmethod
    def erfinv(x):
        return f"calc_erfinv({x})"

    @staticmethod
    def sqrt(x):
        return f"std::sqrt({x})"

    @staticmethod
    def rsqrt(x):
        return f"1 / std::sqrt({x})"

    @staticmethod
    def log1p(x):
        bug = config.cpp.inject_log1p_bug_TESTING_ONLY
        if bug == "accuracy":
            return f"{x} + decltype({x})(1)"
        elif bug is None:
            return f"std::log1p({x})"
        else:
            raise AssertionError(
                f"unrecognized config cpp.inject_log1p_bug_TESTING_ONLY = {bug!r}"
            )

    @staticmethod
    def tan(x):
        return f"std::tan({x})"

    @staticmethod
    def tanh(x):
        return f"std::tanh({x})"

    @staticmethod
    def signbit(x):
        return f"std::signbit({x})"

    @staticmethod
    def pow(a, b):
        return f"std::pow({a}, {b})"

    @staticmethod
    def log(x):
        return f"std::log({x})"

    @staticmethod
    def round(x):
        return f"std::nearbyint({x})"

    @staticmethod
    def floor(x):
        return f"std::floor({x})"

    @staticmethod
    def floordiv(a, b):
        # a and b are integer type
        quot = f"{a} / {b}"
        rem = f"{a} % {b}"
        return f"(({a} < 0) != ({b} < 0) ? ({rem} != 0 ? {quot} - 1 : {quot}) : {quot})"

    @staticmethod
    def ceil(x):
        return f"std::ceil({x})"

    @staticmethod
    def trunc(x):
        return f"std::trunc({x})"

    @staticmethod
    def truncdiv(a, b):
        # a and b are integer type
        return f"{a} / {b}"

    @staticmethod
    def fmod(a, b):
        return f"std::fmod({a}, {b})"

    @staticmethod
    def isinf(x):
        return f"std::isinf({x})"

    @staticmethod
    def isnan(x):
        return f"std::isnan({x})"

    @staticmethod
    def lgamma(x):
        return f"std::lgamma({x})"

    @staticmethod
    def acos(x):
        return f"std::acos({x})"

    @staticmethod
    def acosh(x):
        return f"std::acosh({x})"

    @staticmethod
    def cosh(x):
        return f"std::cosh({x})"

    @staticmethod
    def sinh(x):
        return f"std::sinh({x})"

    @staticmethod
    def asin(x):
        return f"std::asin({x})"

    @staticmethod
    def asinh(x):
        return f"std::asinh({x})"

    @staticmethod
    def atan2(x, y):
        return f"std::atan2({x}, {y})"

    @staticmethod
    def atan(x):
        return f"std::atan({x})"

    @staticmethod
    def atanh(x):
        return f"std::atanh({x})"

    @staticmethod
    def copysign(x, y):
        return f"std::copysign({x}, {y})"

    @staticmethod
    def frexp(x):
        cache_keys = f"frexp({x})[0]", f"frexp({x})[1]"
        if all(cache_key in V.kernel.cse.cache for cache_key in cache_keys):
            return tuple(V.kernel.cse.cache[cache_key] for cache_key in cache_keys)

        code = BracesBuffer()
        exponent = V.kernel.cse.newvar()
        mantissa = V.kernel.cse.newvar()
        code.writeline(f"int32_t {exponent};")
        code.writeline(f"auto {mantissa} = std::frexp({x}, &{exponent});")
        V.kernel.compute.splice(code)
        cse_vars = (mantissa, exponent)
        for cache_key, cse_var in zip(cache_keys, cse_vars):
            V.kernel.cse.cache[cache_key] = cse_var
        return mantissa, exponent

    @staticmethod
    def hypot(x, y):
        return f"std::hypot({x}, {y})"

    @staticmethod
    def log10(x):
        return f"std::log10({x})"

    @staticmethod
    def nextafter(x, y):
        return f"std::nextafter({x}, {y})"

    @staticmethod
    def relu(x):
        bug = config.cpp.inject_relu_bug_TESTING_ONLY
        if bug == "compile_error":
            return "compile error!"
        elif bug == "runtime_error":
            return f"{x}; throw 1"
        elif bug == "accuracy":
            return f"{x} + decltype({x})(1)"
        elif bug is None:
            return f"std::max({x}, decltype({x})(0))"
        else:
            raise AssertionError(
                f"unrecognized config cpp.inject_relu_bug_TESTING_ONLY = {bug!r}"
            )

    @staticmethod
    def minimum(a, b):
        return f"min_propagate_nan({a}, {b})"

    @staticmethod
    def maximum(a, b):
        return f"max_propagate_nan({a}, {b})"

    @staticmethod
    def where(a, b, c):
        return f"{a} ? {b} : {c}"

    @staticmethod
    def mod(a, b):
        return f"mod({a}, {b})"

    @staticmethod
    def constant(val, dtype):
        opt_ctx: OptimizationContext = get_current_node_opt_ctx()
        assert opt_ctx and opt_ctx.dtype is not None
        dtype = opt_ctx.dtype
        if dtype in DTYPE_LOWP_FP:
            # Since load promotes all half-precision inputs to float, constants
            # must be promoted as well
            dtype = torch.float32
        return value_to_cpp(val, DTYPE_TO_CPP[dtype])

    @staticmethod
    def index_expr(expr, dtype):
        opt_ctx: OptimizationContext = get_current_node_opt_ctx()
        assert opt_ctx and opt_ctx.dtype is not None
        dtype = opt_ctx.dtype
        return ops.to_dtype(cexpr(V.kernel.rename_indexing(expr)), dtype)

    @staticmethod
    def masked(mask, body, other):
        code = BracesBuffer()

        # Write masked operation into a lambda
        body_var = V.kernel.cse.newvar()
        code.writeline(f"auto {body_var} = [&]")
        with V.kernel.swap_buffers(code), code.indent():
            result = body()
            code.writeline(f"return {result};")
        code.writeline(";")
        V.kernel.compute.splice(code)

        # Use the lambda's return type as the type of other
        other_code = value_to_cpp(other, f"decltype({body_var}())")
        return f"{mask} ? {body_var}() : {other_code}"

    @staticmethod
    def logical_and(a, b):
        return f"{a} && {b}"

    @staticmethod
    def logical_not(a):
        return f"!{a}"

    @staticmethod
    def logical_or(a, b):
        return f"{a} || {b}"

    @staticmethod
    def logical_xor(a, b):
        return f"{a} != {b}"

    @staticmethod
    def bitwise_and(a, b):
        return f"decltype({a})({a} & {b})"

    @staticmethod
    def bitwise_not(a):
        return f"decltype({a})(~{a})"

    @staticmethod
    def bitwise_or(a, b):
        return f"decltype({a})({a} | {b})"

    @staticmethod
    def bitwise_xor(a, b):
        return f"decltype({a})({a} ^ {b})"

    @staticmethod
    def bitwise_left_shift(a, b):
        return f"decltype({a})({a} << {b})"

    @staticmethod
    def bitwise_right_shift(a, b):
        return f"decltype({a})({a} >> {b})"

    @staticmethod
    def rand(seed: sympy.Expr, offset: sympy.Expr):
        return f"normalized_rand_cpu({seed}, {offset})"

    @staticmethod
    def randn(seed: sympy.Expr, offset: sympy.Expr):
        return f"randn_cpu({seed}, {offset})"

    @staticmethod
    def randint64(seed: sympy.Expr, offset: sympy.Expr, low, high):
        return f"randint64_cpu({seed}, {offset}, {low}, {high})"

    @staticmethod
    def sigmoid(x):
        return f"decltype({x})(1) / (decltype({x})(1) + std::exp(-{x}))"

    @staticmethod
    def sign(x):
        code = BracesBuffer()
        scalar_zero = f"decltype({x})(0)"
        scalar_one = f"decltype({x})(1)"
        code.writeline("[&]()")
        with code.indent():
            code.writeline(f"auto left = {x} > 0 ? {scalar_one} : {scalar_zero};")
            code.writeline(f"auto right = {x} < 0 ? {scalar_one} : {scalar_zero};")
            code.writeline("return left - right;")
        code.writeline("()")
        return code


CppOverrides._initialize_pointwise_overrides("cpp")


class CppVecOverrides(CppOverrides):
    """Map element-wise ops to aten vectorization C++"""

    def __new__(cls, *args, **kargs):
        self = super().__new__(cls)

        def wrap(func):
            # `CppVecKernel` generates both scalar ops and vector ops according to
            # whether the inputs are scalars or vectors while all ops in `CppVecOverrides`
            # (except for some ops explained below) assume the inputs are vectors. We wrap the ops in
            # `CppVecOverrides` to broadcast scalar inputs to vectors if needed or fallback to
            # `CppOverrides` when all inputs are scalars.
            #
            # Notes on ops handled separately in their own functions:
            # `ops.masked`:
            #     needs recursive handling of masked body.
            # `ops.index_expr`:
            #     needs to further analyze the dependency of the index expression on
            #     the tiling itervar.
            def wrapper(*args, **kwargs):
                scalars = [
                    arg
                    for arg in args
                    if isinstance(arg, CppCSEVariable) and not arg.is_vec
                ]
                vectors = [
                    arg
                    for arg in args
                    if isinstance(arg, CppCSEVariable) and arg.is_vec
                ]
                new_args = list(args)
                if scalars and vectors:
                    # broadcast scalar args to vector if needed
                    new_args = []
                    vec_dtype = vectors[0].dtype
                    for arg in args:
                        if isinstance(arg, CppCSEVariable) and not arg.is_vec:
                            assert isinstance(V.kernel, CppVecKernel)
                            # align scalar data type to the vector for binary ops
                            if len(args) == 2 and arg.dtype != vec_dtype:
                                arg = ops.to_dtype(arg, vec_dtype)
                                arg = arg.value if isinstance(arg, OpsValue) else arg
                                # See NOTE [dtype of CppCSEVariable]: we have to fix arg.dtype since
                                # the dtype from optimization context could be wrong.
                                assert isinstance(arg, CppCSEVariable)
                                arg.dtype = vec_dtype
                            new_arg = V.kernel.broadcast(arg)
                            new_args.append(new_arg)
                        else:
                            new_args.append(arg)
                if vectors:
                    return func(*new_args, **kwargs)
                else:
                    # fallback to scalar ops
                    scalar_ops = super(CppVecOverrides, self)
                    scalar_func = getattr(
                        scalar_ops, func.__name__, scalar_ops.__getattr__(func.__name__)  # type: ignore[attr-defined]
                    )
                    assert scalar_func is not None
                    return scalar_func(*args, **kwargs)

            return wrapper

        for name, method in vars(CppVecOverrides).items():
            if getattr(method, "__class__", None) == staticmethod and name not in [
                "masked",
                "index_expr",
            ]:
                setattr(self, name, wrap(method.__func__))
        return self

    @staticmethod
    def add(a, b):
        return f"{a} + {b}"

    @staticmethod
    def sub(a, b):
        return f"{a} - {b}"

    @staticmethod
    def mul(a, b):
        return f"{a} * {b}"

    @staticmethod
    def truediv(a, b):
        return f"{a} / {b}"

    @staticmethod
    def abs(x):
        return f"{x}.abs()"

    @staticmethod
    def sin(x):
        return f"{x}.sin()"

    @staticmethod
    def cos(x):
        return f"{x}.cos()"

    @staticmethod
    def exp(x):
        return f"{x}.exp()"

    @staticmethod
    def exp2(x):
        return f"{x}.exp2()"

    @staticmethod
    def expm1(x):
        # decompose for a better performance
        vec_one = f"decltype({x})(1)"
        return f"{x}.exp() - {vec_one}"

    @staticmethod
    def erf(x):
        return f"{x}.erf()"

    @staticmethod
    def erfc(x):
        return f"{x}.erfc()"

    @staticmethod
    def erfinv(x):
        return f"{x}.erfinv()"

    @staticmethod
    def sqrt(x):
        return f"{x}.sqrt()"

    @staticmethod
    def eq(x, y):
        return f"to_float_mask({x} == {y})"

    @staticmethod
    def ne(x, y):
        return f"to_float_mask({x} != {y})"

    @staticmethod
    def lt(x, y):
        return f"to_float_mask({x} < {y})"

    @staticmethod
    def gt(x, y):
        return f"to_float_mask({x} > {y})"

    @staticmethod
    def le(x, y):
        return f"to_float_mask({x} <= {y})"

    @staticmethod
    def ge(x, y):
        return f"to_float_mask({x} >= {y})"

    @staticmethod
    def and_(x, y):
        return f"{x} & {y}"

    @staticmethod
    def rsqrt(x):
        return f"{x}.rsqrt()"

    @staticmethod
    def pow(a, b):
        return f"{a}.pow({b})"

    @staticmethod
    def log(x):
        return f"{x}.log()"

    @staticmethod
    def round(x):
        return f"{x}.round()"

    @staticmethod
    def floor(x):
        return f"{x}.floor()"

    @staticmethod
    def ceil(x):
        return f"{x}.ceil()"

    @staticmethod
    def trunc(x):
        return f"{x}.trunc()"

    @staticmethod
    def fmod(a, b):
        return f"{a}.fmod({b})"

    @staticmethod
    def lgamma(x):
        return f"{x}.lgamma()"

    @staticmethod
    def logical_and(a, b):
        return f"({a} != 0) & ({b} != 0)"

    @staticmethod
    def logical_not(a):
        return f"{a} == 0"

    @staticmethod
    def logical_or(a, b):
        return f"({a} != 0) | ({b} != 0)"

    @staticmethod
    def logical_xor(a, b):
        return f"({a} != 0) ^ ({b} != 0)"

    @staticmethod
    def tan(a):
        return f"{a}.tan()"

    @staticmethod
    def tanh(a):
        vec_one = f"decltype({a})(1)"
        vec_two = f"decltype({a})(2)"
        vec_minus_two = f"decltype({a})(-2)"
        return f"{vec_two} / ({vec_one} + ({vec_minus_two} * {a}).exp()) - {vec_one}"

    @staticmethod
    def reciprocal(a):
        return f"{a}.reciprocal()"

    @staticmethod
    def atan(x):
        return f"{x}.atan()"

    @staticmethod
    def acos(x):
        return f"{x}.acos()"

    @staticmethod
    def asin(x):
        return f"{x}.asin()"

    @staticmethod
    def cosh(x):
        return f"{x}.cosh()"

    @staticmethod
    def sinh(x):
        return f"{x}.sinh()"

    @staticmethod
    def log10(x):
        return f"{x}.log10()"

    @staticmethod
    def nextafter(x):
        return f"{x}.nextafter()"

    @staticmethod
    def copysign(a, b):
        return f"{a}.copysign({b})"

    @staticmethod
    def atan2(a, b):
        return f"{a}.atan2({b})"

    @staticmethod
    def hypot(a, b):
        return f"{a}.hypot({b})"

    @staticmethod
    def atanh(x):
        # For real x, atanh(x) = 1/2 * log((1+x)/(1-x))
        vec_one = f"decltype({x})(1)"
        vec_one_half = f"decltype({x})(0.5)"
        return f"{vec_one_half} * (({vec_one} + {x})/({vec_one} - {x})).log()"

    @staticmethod
    def asinh(x):
        # For real x, asinh(x) = log(x + sqrt(1 + x**2))
        vec_one = f"decltype({x})(1)"
        return f"({x} + ({vec_one} + {x}*{x}).sqrt()).log()"

    @staticmethod
    def acosh(x):
        return f"{x}.acosh()"

    @staticmethod
    def relu(x):
        bug = config.cpp.inject_relu_bug_TESTING_ONLY
        if bug == "compile_error":
            return "compile error!"
        elif bug == "runtime_error":
            return f"{x}; throw 1"
        elif bug == "accuracy":
            return f"{x} + decltype({x})(1)"
        elif bug is None:
            return f"at::vec::clamp_min({x}, decltype({x})(0))"
        else:
            raise AssertionError(
                f"unrecognized config cpp.inject_relu_bug_TESTING_ONLY = {bug!r}"
            )

    # TODO: this seems to be dead
    @staticmethod
    def sigmoid(x):
        return f"decltype({x})(1)/(decltype({x})(1) + {x}.neg().exp())"

    @staticmethod
    def neg(x):
        return f"{x}.neg()"

    @staticmethod
    def floordiv(a, b):
        # a and b are integer type
        _t = f"decltype({a})"
        quot = f"{a} / {b}"
        has_rem = f"({a} % {b} != {_t}(0))"
        is_neg = f"(({a} < {_t}(0)) != ({b} < {_t}(0)))"
        return f"{_t}::blendv({quot}, {quot} - {_t}(1), {has_rem} & {is_neg})"

    @staticmethod
    def truncdiv(a, b):
        # a and b are integer type
        return f"{a} / {b}"

    @staticmethod
    def minimum(a, b):
        return f"at::vec::minimum({a}, {b})"

    @staticmethod
    def maximum(a, b):
        return f"at::vec::maximum({a}, {b})"

    @staticmethod
    def square(a):
        return f"{a} * {a}"

    @staticmethod
    def where(a, b, c):
        assert isinstance(b, CppCSEVariable)
        if b.dtype != torch.float:
            raise CppVecUnsupportedError(
                "where with non-float tensor is not supported in vectorized codegen"
            )
        return f"decltype({b})::blendv({c}, {b}, {a})"

    @staticmethod
    def sign(x):
        code = BracesBuffer()
        vec_zero = f"decltype({x})(0)"
        vec_one = f"decltype({x})(1)"
        blendv_l = f"decltype({x})::blendv({vec_zero}, {vec_one}, {vec_zero} < {x})"
        blendv_r = f"decltype({x})::blendv({vec_zero}, {vec_one}, {x} < {vec_zero})"
        code.writeline("[&]()")
        with code.indent():
            code.writeline(f"auto left = {blendv_l};")
            code.writeline(f"auto right = {blendv_r};")
            code.writeline("return left - right;")
        code.writeline("()")
        return code

    @staticmethod
    def to_dtype(x, dtype, src_dtype=None):
        assert dtype in [
            torch.bool,
            torch.float,
            torch.bfloat16,
            torch.float16,
            torch.uint8,
            torch.int8,
            torch.int32,
            torch.int64,
        ], f"{__name__} does not support {dtype}"
        node: torch.fx.Node = V.interpreter.current_node
        assert node and isinstance(node, torch.fx.Node)
        opt_ctx_x = get_opt_ctx(node.args[1])
        assert opt_ctx_x
        if opt_ctx_x.dtype in (torch.float, torch.float32) and dtype == torch.bool:
            return f"vec_convert_to_mask({x})"
        if opt_ctx_x.dtype == torch.bool and dtype in (torch.float, torch.float32):
            return f"mask_convert_to_float({x})"
        if opt_ctx_x.dtype == torch.bool and dtype in DTYPE_LOWP_FP:
            return f"mask_convert_to_lowp<{DTYPE_TO_CPP[dtype]}>({x})"
        if opt_ctx_x.dtype == torch.bool and dtype == torch.int64:
            return f"mask_convert_to_int64({x})"
        if opt_ctx_x.dtype in (torch.float, torch.float32) and dtype in DTYPE_LOWP_FP:
            return f"cvt_fp32_to_lowp_fp<{DTYPE_TO_CPP[dtype]}>({x})"
        if opt_ctx_x.dtype in DTYPE_LOWP_FP and dtype in (torch.float, torch.float32):
            return f"cvt_lowp_fp_to_fp32<{DTYPE_TO_CPP[opt_ctx_x.dtype]}>({x})"
        if opt_ctx_x.dtype in (torch.uint8, torch.int8) and dtype in (
            torch.float,
            torch.float32,
        ):
            # Note: this function only convert inputs number of elements equal to at::vec::Vectorized<float>.size()
            return f"at::vec::convert_int8_to_float({x})"
        if opt_ctx_x.dtype in (torch.float, torch.float32) and dtype in (
            torch.uint8,
            torch.int8,
        ):
            # if we already handle the saturation previously.
            # * Pattern match of quantization op in the loop body.
            # * Skip the explicit saturation and clamp inside at::vec::convert_float_to_int8.
            return f"at::vec::convert_float_to_int8<{DTYPE_TO_CPP[dtype]}>({x})"
        if opt_ctx_x.dtype == torch.int32 and dtype == torch.float:
            return f"at::vec::convert_to_fp_of_same_size<float>({x})"
        if opt_ctx_x.dtype == torch.float and dtype == torch.int32:
            return f"at::vec::convert_to_int_of_same_size({x})"
        if opt_ctx_x.dtype == torch.int64 and dtype == torch.float:
            return f"cvt_int64_to_fp32({x})"
        if opt_ctx_x.dtype == torch.float and dtype == torch.int64:
            return f"cvt_fp32_to_int64({x})"
        if opt_ctx_x.dtype == torch.int32 and dtype == torch.int64:
            return f"cvt_int32_to_int64({x})"
        if opt_ctx_x.dtype == torch.int64 and dtype == torch.int32:
            return f"cvt_int64_to_int32({x})"
        # TODO(jgong5): support conversion for other types
        # currently we only allow load/store torch.uint8 and handle conversion there
        return f"({x})"

    @staticmethod
    def log1p(x):
        bug = config.cpp.inject_log1p_bug_TESTING_ONLY
        if bug == "accuracy":
            return f"{x} + decltype({x})(1)"
        elif bug is None:
            return f"{x}.log1p()"
        else:
            raise AssertionError(
                f"unrecognized config cpp.inject_log1p_bug_TESTING_ONLY = {bug!r}"
            )

    @staticmethod
    def masked(mask, body, other):
        assert isinstance(V.kernel, CppVecKernel)
        code = BracesBuffer()
        var = V.kernel.cse.newvar()
        with V.kernel.masked(mask) as new_mask:
            code.writeline(f"auto {var} = [&]")
            with V.kernel.swap_buffers(code), code.indent():
                result = body()
                code.writeline(f"return {result};")
        code.writeline(";")
        V.kernel.compute.splice(code)

        body_code = f"{var}()"
        body_code_vec = (
            body_code
            if result.is_vec
            else f"{V.kernel._get_vec_type(torch.float)}({body_code})"
        )
        other_code = value_to_cpp(other, "float")
        other_code_vec = f"{V.kernel._get_vec_type(torch.float)}({other_code})"
        assert isinstance(new_mask, CppCSEVariable), new_mask
        if new_mask.is_vec or result.is_vec:
            if result.dtype != torch.float:
                raise CppVecUnsupportedError(
                    "masked with non-float tensor is not supported in vectorized codegen"
                )
            type = f"decltype({body_code_vec})"
            float_mask = f"to_float_mask({new_mask})"
            code = BracesBuffer()
            code.writeline("[&]")
            with V.kernel.swap_buffers(code), code.indent():
                code.writeline(f"if (all_zero({float_mask}))")
                with code.indent():
                    code.writeline(f"return {other_code_vec};")
                code.writeline("else")
                with code.indent():
                    code.writeline(
                        f"return {type}::blendv({other_code_vec}, {body_code_vec}, {float_mask});"
                    )
            code.writeline("()")
            csevar = V.kernel.cse.generate(
                V.kernel.compute,
                code,
            )
        else:
            csevar = V.kernel.cse.generate(
                V.kernel.compute, f"{mask} ? {body_code} : {other_code}"
            )
        # `result` is explicitly added to the args for correct propagation
        # of relevant itervars and vectorization status.
        csevar.update_on_args("masked", (mask, body, other, result), {})
        return csevar

    @staticmethod
    def index_expr(expr, dtype):
        opt_ctx: OptimizationContext = get_current_node_opt_ctx()
        assert opt_ctx and opt_ctx.dtype is not None
        dtype = opt_ctx.dtype
        assert dtype == torch.int32
        assert isinstance(V.kernel, CppVecKernel)
        index = V.kernel.rename_indexing(expr)
        tiling_var = V.kernel.itervars[V.kernel.tiling_idx]
        stride = stride_at_vec_range(index, tiling_var, V.kernel.tiling_factor)
        if stride.is_number and not V.kernel.index_indirect_depends_on(
            index, tiling_var
        ):
            if stride == 0:
                return CppOverrides.index_expr(expr, dtype)
            value = ops.to_dtype(cexpr(index), dtype)
            if isinstance(value, OpsValue):
                value = value.value
            csevar = V.kernel.arange(value, stride)
        else:
            csevar = V.kernel.load_non_contiguous(None, index, dtype, V.kernel.compute)
        csevar.update_on_args("index_expr", (expr, dtype), {})
        return csevar


CppVecOverrides._initialize_pointwise_overrides("cppvec")


class CppTile2DOverrides(CppVecOverrides):
    @staticmethod
    def index_expr(expr, dtype):
        assert isinstance(V.kernel, CppTile2DKernel)
        expr = V.kernel.transform_indexing(expr)
        return CppVecOverrides.index_expr(expr, dtype)


class CppKernel(Kernel):
    overrides = CppOverrides  # type: ignore[assignment]
    sexpr = cexpr
    newvar_prefix = "auto "
    suffix = ";"

    def __init__(self, args, num_threads):
        super().__init__(args)
        self.call_ranges: Optional[Tuple[sympy.Expr, ...]] = None
        self.ranges: List[sympy.Expr] = []
        self.itervars: List[sympy.Symbol] = []
        self.reduction_depth = None
        self.reduction_prefix = IndentedBuffer()
        self.reduction_suffix = IndentedBuffer()
        self.reduction_var_map = {}
        self.reduction_cse = CSE(self.newvar_prefix, self.suffix, name_prefix="tmp_acc")
        self.preloads = IndentedBuffer()
        self.poststores = IndentedBuffer()
        self.num_threads = num_threads  # num_threads the kernel specialized for
        self.reduction_omp_dec: Dict[Tuple[str, str], str] = {}

    @contextlib.contextmanager
    def masked(self, mask):
        """Context manager to add an additional mask to loads and stores."""
        prior = self._load_mask
        if prior:
            mask = ops.and_(mask, prior)
            if isinstance(mask, OpsValue):
                mask = mask.value
                assert isinstance(mask, CppCSEVariable)
                # see NOTE [dtype of CppCSEVariable]
                # mask's dtype should be bool
                mask.dtype = torch.bool

        self._load_mask = mask
        try:
            yield mask
        finally:
            self._load_mask = prior

    def cache_fp32_cse_var_before_lowp_store(self, var_to_store):
        """
        https://github.com/pytorch/pytorch/issues/115260
        For FusedSchedulerNode[node1, node2], the node2 loads what node1 stores and the buffer is
        in low-precision floating point data type. When the output of node1 also serves as the output of the
        kernel, the result of nodes would be different from the case when output of node1 is not the output
        of the kernel (where we don't need to insert `to_dtype` for legalization). To address the problem, on
        storing the lowp node1 output, we also add the inverse dtype conversion to high precision data type
        to the cse cache.

        Example (pseudo code):
            node1_output = ...
            node1_output_lowp = to_dtype(node1_output, dtype=torch.bfloat16)
            store(buf, node1_output_lowp)
            node2_input_lowp = load(buf)
            node2_input = to_dtype(node2_input_lowp, dtype=torch.float)

        Without cse cache trick:
            node1_output = ...
            node1_output_lowp = to_dtype(node1_output, dtype=torch.bfloat16)
            store(buf, node1_output_lowp)
            node2_input_lowp = node_output_lowp # hit store cache
            node2_input = to_dtype(node2_input_lowp, dtype=torch.float)

        With cse cache trick:
            node1_output = ...
            node1_output_lowp = to_dtype(node1_output, dtype=torch.bfloat16)
            # also add `to_dtype(node1_input_lowp, dtype=torch.float)` -> `node1_output` to cse cache
            store(buf, node1_output_lowp)
            node2_input_lowp = node_output_lowp # hit store cache
            node2_input = node1_output # hit cse cache
        """

        if var_to_store.dtype not in DTYPE_LOWP_FP:
            # only need to cache fp32 cse var while var_to_store is lowp data
            return

        def find_fp32_var(var, cache):
            fp32_cse_var = None
            fp32_cse_var_name = None
            lowp_dtype = None
            for expr, cse_var in cache.items():
                if cse_var == var:
                    lowp_dtype = is_to_lowp_dtype(expr)
                    if lowp_dtype:
                        m = re.search(r"tmp\d+", expr)
                        assert m
                        fp32_cse_var_name = m.group()
            if fp32_cse_var_name:
                for cse_var in cache.values():
                    if cse_var.name == fp32_cse_var_name:
                        fp32_cse_var = cse_var
                        break
                assert fp32_cse_var is not None
            return fp32_cse_var, lowp_dtype

        fp32_var, lowp_dtype = find_fp32_var(var_to_store, self.cse.cache)
        if fp32_var:
            self.cse.cache[
                get_lowp_to_fp32_expr(var_to_store, lowp_dtype, self)
            ] = fp32_var

    def scale_index_with_offset(
        self, index: sympy.Expr, scale=1, itervar_idx=-1, offset=0
    ):
        var = self.itervars[itervar_idx]
        replacement = {var: var * scale + offset}
        new_index = sympy_subs(index, replacement)
        return new_index

    def index_to_str(self, index: sympy.Expr) -> str:
        """
        Convert an index expr to a string that can be used in cpp code.
        e.g. a sympy expression "s2" may actually appear as "ks1" in the cpp kernel.
        """
        return cexpr(self.rename_indexing(index))

    def index_indirect_depends_on(self, index: sympy.Expr, itervar: sympy.Symbol):
        """
        Check if an index has free symbol CppCSEVariable that depends on `itervar`.
        """
        return any(
            self.cse.varname_map[s.name].depends_on(itervar)  # type: ignore[attr-defined]
            for s in index.free_symbols
            if s.name in self.cse.varname_map  # type: ignore[attr-defined]
            and isinstance(self.cse.varname_map[s.name], CppCSEVariable)  # type: ignore[attr-defined]
        )

    def index_depends_on(self, index: sympy.Expr, itervar: sympy.Symbol):
        return itervar in index.free_symbols or self.index_indirect_depends_on(
            index, itervar
        )

    def load(self, name: str, index: sympy.Expr):
        var = self.args.input(name)
        index = self.rename_indexing(index)
        line = f"{var}[{cexpr_index(index)}]"
        if V.graph.get_dtype(name) in [torch.float16]:
            line = f"static_cast<float>({line})"
        csevar = self.cse.generate(self.loads, line)
        csevar.update_on_args("load", (name, index), {})
        return csevar

    def store(self, name, index, value, mode=None):
        assert "buf" in name
        var = self.args.output(name)
        self.cache_fp32_cse_var_before_lowp_store(value)
        index = self.rename_indexing(index)
        if mode is None:
            line = f"{var}[{cexpr_index(index)}] = {value};"
        elif mode == "atomic_add":
            if not config.cpp.dynamic_threads and self.num_threads == 1:
                line = f"{var}[{cexpr_index(index)}] += {value};"
            else:
                dtype = V.graph.get_dtype(name)
                # mirroring static_cast<float>(...) in load:
                value = f"static_cast<{DTYPE_TO_CPP[dtype]}>({value})"
                line = f"atomic_add(&{var}[{cexpr_index(index)}], {value});"
        else:
            raise NotImplementedError(f"store mode={mode}")
        self.stores.writeline(DeferredLine(name, line))

    def reduction(self, dtype, src_dtype, reduction_type, value):
        argmax_or_argmin = reduction_type in {"argmax", "argmin"}

        reduction_key = src_dtype, reduction_type, value
        if reduction_key in self.reduction_cse.reduction_cache:
            return self.reduction_cse.reduction_cache[reduction_key]

        acc = self.reduction_cse.generate(
            self.loads, f"reduction {reduction_key}", write=False
        )
        self.reduction_var_map[acc] = reduction_type
        if argmax_or_argmin:
            self.reduction_prefix.writelines(
                argmax_argmin_prefix(reduction_type, src_dtype, acc)
            )
            compare_op = (
                "greater_or_nan" if reduction_type == "argmax" else "less_or_nan"
            )
            assert self.reduction_depth is not None
            index = self.itervars[self.reduction_depth]
            for i in range(self.reduction_depth + 1, len(self.itervars)):
                index = index * self.ranges[i] + self.itervars[i]
            self.stores.writelines(
                [
                    f"if(!({compare_op}({acc}.value, {value}, {acc}.index, {cexpr_index(index)}))) {{",
                    f"    {acc}.index = {cexpr_index(index)}; {acc}.value = {value};",
                    "}",
                ],
            )
        else:
            acc_type = reduction_acc_type(reduction_type, dtype)

            if (reduction_type, acc_type) not in self.reduction_omp_dec:
                if RTYPE_TO_CPP[reduction_type] not in NATIVE_OMP_RTYPES:
                    # Scalar reduction for other reductions are declared by default
                    self.reduction_prefix.splice(
                        f"""\
    #pragma omp declare reduction(\
    {RTYPE_TO_CPP[reduction_type]}:{acc_type}:\
    omp_out = {reduction_combine(reduction_type, "omp_out", "omp_in")}) \
    initializer(omp_priv={{{reduction_init(reduction_type, dtype)}}})
                """
                    )
                self.reduction_omp_dec[reduction_type, acc_type] = RTYPE_TO_CPP[
                    reduction_type
                ]

            self.reduction_prefix.writeline(
                f"{acc_type} {acc} = {reduction_init(reduction_type, dtype)};"
            )
            self.stores.writeline(
                f"{acc} = {reduction_combine(reduction_type, acc, value)};"
            )

        result = reduction_project(reduction_type, acc)
        self.reduction_cse.reduction_cache[reduction_key] = result
        return result

    def store_reduction(self, name, index, value):
        index = self.rename_indexing(index)
        var = self.args.output(name)
        self.reduction_suffix.writeline(
            DeferredLine(name, f"{var}[{cexpr_index(index)}] = {value};")
        )

    def set_ranges(self, lengths, reduction_lengths):
        if self.call_ranges:
            assert self.call_ranges == tuple(lengths) + tuple(
                reduction_lengths
            ), f"{self.call_ranges} == {tuple(lengths)} + {tuple(reduction_lengths)}"
            assert self.reduction_depth == len(lengths)
        else:
            self.call_ranges = tuple(lengths) + tuple(reduction_lengths)
            self.ranges = [self.rename_indexing(x) for x in self.call_ranges]
            self.itervars = [
                sympy_index_symbol(f"x{n}") for n in range(len(self.ranges))
            ]
            self.reduction_depth = len(lengths)
        return (
            self.itervars[: self.reduction_depth],
            self.itervars[self.reduction_depth :],
        )

    def size_hint(self):
        return V.graph.sizevars.size_hint(
            sympy_product(self.call_ranges), fallback=8192
        )

    def codegen_loops_impl(self, loop_nest, code, worksharing):
        threads = parallel_num_threads()
        assert self.call_ranges is not None
        par_depth = self.decide_parallel_depth(
            self.call_ranges[: loop_nest.max_parallel_depth()], threads
        )
        with contextlib.ExitStack() as stack:
            if par_depth:
                if loop_nest.is_reduction_only():
                    # need to close the worksharing scope to define reduction vars outside it
                    worksharing.close()
                else:
                    worksharing.parallel(threads)
                loop_nest.mark_parallel(par_depth)
            elif threads > 1:
                if worksharing.single():
                    stack.enter_context(code.indent())

            def gen_kernel(kernel):
                with contextlib.ExitStack() as stack:
                    assert kernel
                    if hasattr(kernel, "codegen_inner_loops"):
                        code.splice(kernel.preloads)
                        kernel.codegen_inner_loops(code)
                        stack.enter_context(code.indent())
                    code.splice(kernel.loads)
                    code.splice(kernel.compute)
                    code.splice(kernel.stores)
                if hasattr(kernel, "codegen_inner_loops"):
                    code.splice(kernel.poststores)

            def get_reduction_code_buffer(loops, is_suffix=True):
                for loop in loops:
                    for kernel in loop.get_kernels():
                        if is_suffix:
                            return kernel.reduction_suffix
                        else:
                            return kernel.reduction_prefix
                return None

            def gen_loops(loops: List[LoopLevel], in_reduction=False):
                with contextlib.ExitStack() as stack_outer:
                    if loops:
                        loop = loops[0]
                        if loop.is_reduction() and not in_reduction:
                            reduction_prefix = get_reduction_code_buffer(
                                loops, is_suffix=False
                            )
                            if reduction_prefix:
                                stack_outer.enter_context(code.indent())
                            code.splice(reduction_prefix)
                        if loop_nest.is_reduction_only() and loop.parallel:
                            worksharing.parallel(threads)

                    for loop in loops:
                        gen_loop(loop, in_reduction)

                    if loops:
                        loop = loops[0]
                        if loop_nest.is_reduction_only() and loop.parallel:
                            worksharing.close()
                        if loop.is_reduction() and not in_reduction:
                            code.splice(
                                get_reduction_code_buffer(loops, is_suffix=True)
                            )

            def gen_loop(loop: LoopLevel, in_reduction=False):
                with contextlib.ExitStack() as stack:
                    loop_lines = loop.lines()
                    if loop_lines is None:
                        return
                    code.writelines(loop_lines)
                    stack.enter_context(code.indent())
                    # generate inner loops or loop body
                    if loop.inner:
                        gen_loops(loop.inner, loop.is_reduction())
                    else:
                        kernels = loop.get_kernels()
                        assert len(kernels) == 1
                        gen_kernel(kernels[0])

            stack.enter_context(code.indent())
            if loop_nest.root:
                gen_loops(loop_nest.root)
            else:
                gen_kernel(loop_nest.kernel)

    def codegen_loops(self, code, worksharing):
        loop_nest = LoopNestWithSplit.build(self)
        self.codegen_loops_impl(loop_nest, code, worksharing)

    @property
    def assert_function(self) -> str:
        if V.graph.aot_mode:
            return "AOTI_TORCH_CHECK"
        else:
            return "TORCH_CHECK"

    def decide_parallel_depth(self, ranges, threads):
        seq = self.size_hint()
        par = 1
        depth = 0
        for expr in ranges:
            hint = V.graph.sizevars.size_hint(expr, fallback=8192)
            if par >= 2 * threads or par == threads:
                break
            if seq // threads < config.cpp.min_chunk_size:
                # not enough work
                break
            depth += 1
            par *= hint
            seq /= hint
        # if we assume thread number is dynamic, make sure we
        # have at least one parallel scope and let OMP runtime
        # to manage the serial vs. parallel.
        if config.cpp.dynamic_threads and depth == 0 and len(ranges) > 0:
            depth = 1
        return depth

    @contextlib.contextmanager
    def write_to_suffix(self):
        prior = (self.loads, self.compute, self.stores, self.cse)
        self.loads = IndentedBuffer()
        self.compute = IndentedBuffer()
        self.stores = IndentedBuffer()
        self.cse = self.cse.clone()
        yield
        self.reduction_suffix.splice(self.loads)
        self.reduction_suffix.splice(self.compute)
        self.reduction_suffix.splice(self.stores)
        (self.loads, self.compute, self.stores, self.cse) = prior

    def create_cse_var(self, *args, **kwargs):
        return CppCSEVariable(*args, **kwargs)


class CppVecKernel(CppKernel):
    overrides = CppVecOverrides  # type: ignore[assignment]

    def __init__(
        self,
        args,
        num_threads,
        tiling_factor=0,
        tiling_idx=-1,
        tiling_dtype=torch.float,
    ):
        super().__init__(args, num_threads)
        self.vec_isa = codecache.pick_vec_isa()
        assert self.vec_isa
        if tiling_factor == 0:
            tiling_factor = self.vec_isa.nelements(dtype=tiling_dtype)
        self.tiling_factor = tiling_factor
        self.tiling_idx = tiling_idx

    def _get_num_vectors(self, dtype: torch.dtype) -> int:
        num_vectors = math.ceil(
            self.tiling_factor * dtype.itemsize * 8 / self.vec_isa.bit_width()
        )
        assert num_vectors >= 1
        return num_vectors

    def _get_vec_type(self, dtype: torch.dtype) -> str:
        num_vectors = self._get_num_vectors(dtype)
        if num_vectors == 1:
            return f"at::vec::Vectorized<{DTYPE_TO_CPP[dtype]}>"
        else:
            return f"at::vec::VectorizedN<{DTYPE_TO_CPP[dtype]},{num_vectors}>"

    def _get_vec_load_line(
        self,
        var: str,
        index: sympy.Expr,
        dtype: torch.dtype,
        load_mask: Optional[CppCSEVariable] = None,
    ):
        """
        Get a load line str that loads a vector from `var` at `index` of type `dtype`.
        If `load_mask` is not None, we do a masked load accordingly.
        Notes on the `dtype`:
        1. We always load `self.tiling_factor` number of elements regardless of the `dtype`.
           It means we load half of the vector lanes for 16-bit data types and quarter of the
           vector lanes for 8-bit data types.
        2. `torch.bool` and `torch.uint8` could mean masks and we load them as float mask vectors.
        """
        opt_ctx: OptimizationContext = get_current_node_opt_ctx()
        assert opt_ctx is not None
        load_mask_str = f"to_float_mask({load_mask})" if load_mask else None
        loadbuf = f"{var} + {cexpr_index(index)}" if index != 0 else var
        if dtype in (torch.uint8, torch.int8) and opt_ctx.is_load_int8_as_float:
            assert self._get_num_vectors(torch.uint8) == 1
            line = (
                f"masked_load({loadbuf}, {load_mask_str})"
                if load_mask_str
                else f"at::vec::Vectorized<{DTYPE_TO_CPP[dtype]}>::loadu_one_fourth({loadbuf})"
            )
        elif opt_ctx.is_load_as_mask:
            line = f"flag_to_float_vec({loadbuf})"
        elif dtype in DTYPE_LOWP_FP:
            line = (
                f"masked_load({loadbuf}, {load_mask_str})"
                if load_mask_str
                else f"{self._get_vec_type(dtype)}::loadu({loadbuf}, {self.tiling_factor})"
            )
        else:
            line = (
                f"masked_load({loadbuf}, {load_mask_str})"
                if load_mask_str
                else f"{self._get_vec_type(dtype)}::loadu({loadbuf})"
            )
        return line

    def load_non_contiguous(
        self,
        var: Optional[str],
        index: sympy.Expr,
        dtype: torch.dtype,
        buffer: Optional[IndentedBuffer] = None,
    ) -> CppCSEVariable:
        """
        Load a vector in a non-contiguous way. The vector is initialized from an array that is
        filled in an inner loop over the tiling factor.
        :param var: buffer to load from, i.e. `var[transformed(index)]`. If None, we load the index
                    as index expression, i.e. `transformed(index)`.
        :param index: index into the `var` or the index expression by its own if `var` is None.
                      The `index` could contain indirect indexing or the tiling itervar. When used in
                      the inner loop, the index is transformed as follows:
                      1. the index is linearized along the tiling dim.
                      2. the indirect indexing vector variables are transformed into arrays over the tiling dim.
        :param dtype: data type of `var` or `index` if `var` is None.
        :param buffer: the code buffer to write the generated code to. If None, we write to `self.loads`.
        :return: a CppCSEVariable that represents the loaded vector.
        """
        if buffer is None:
            buffer = self.loads

        def get_result_size(dtype: torch.dtype) -> int:
            if dtype.itemsize < 4:
                return self.tiling_factor * (4 // dtype.itemsize)
            else:
                return self.tiling_factor

        def vec_to_array(vec_var: CppCSEVariable) -> CppCSEVariable:
            assert vec_var.is_vec
            code = BracesBuffer()
            code.writeline("[&]")
            with self.swap_buffers(code), code.indent():
                vec_dtype = vec_var.dtype
                assert vec_dtype is not None
                if vec_dtype == torch.bool:
                    vec_dtype = torch.float
                result_size = get_result_size(vec_dtype)
                code.writeline(
                    f"__at_align__ std::array<{DTYPE_TO_CPP[vec_dtype]}, {result_size}> tmpbuf;"
                )
                line = f"{vec_var}.store(tmpbuf.data());"
                code.writeline(line)
                code.writeline("return tmpbuf;")
            code.writeline("()")
            csevar = self.cse.generate(buffer, code)
            assert isinstance(csevar, CppCSEVariable)
            return csevar

        opt_ctx: OptimizationContext = get_current_node_opt_ctx()
        assert opt_ctx is not None
        is_mask = opt_ctx.is_load_as_mask
        code = BracesBuffer()
        code.writeline("[&]")
        with self.swap_buffers(code), code.indent():
            result_type = "float" if is_mask else f"{DTYPE_TO_CPP[dtype]}"
            result_size = get_result_size(dtype)
            result_declare = (
                f"__at_align__ std::array<{result_type}, {result_size}> tmpbuf;"
            )
            code.writeline(result_declare)
            itervar_inner = sympy_index_symbol(
                f"{self.itervars[self.tiling_idx]}_inner"
            )
            replacements = {}
            for indirect_var in (
                self.cse.varname_map[s.name]  # type: ignore[attr-defined]
                for s in index.free_symbols
                if s.name.startswith("tmp")  # type: ignore[attr-defined]
            ):
                assert isinstance(indirect_var, CppCSEVariable)
                if indirect_var.is_vec:
                    array_var = vec_to_array(indirect_var)
                    replacements[indirect_var] = f"{array_var}[{itervar_inner}]"
            load_mask = None
            if self._load_mask is not None:
                assert isinstance(self._load_mask, CppCSEVariable), self._load_mask
                if self._load_mask.is_vec:
                    load_mask = (
                        f"vector_lane_mask_check({self._load_mask}, {itervar_inner})"
                    )
                else:
                    load_mask = f"{self._load_mask} != 0"
            index = sympy_subs(index, replacements)  # type: ignore[arg-type]
            index = self.scale_index_with_offset(
                index, itervar_idx=self.tiling_idx, offset=itervar_inner
            )
            if codecache.is_gcc():
                code.writeline(f"#pragma GCC unroll {self.tiling_factor}")
            else:
                code.writeline(f"#pragma unroll {self.tiling_factor}")
            code.writeline(
                f"for (long {itervar_inner} = 0; {itervar_inner} < {self.tiling_factor}; {itervar_inner}++)"
            )
            with code.indent(), contextlib.ExitStack() as stack:
                rhs = (
                    f"{var}[{cexpr_index(index)}]"
                    if var is not None
                    else f"{cexpr_index(index)}"
                )
                if is_mask:
                    rhs = f"flag_to_float_scalar({rhs})"
                if load_mask:
                    code.writeline(f"if ({load_mask})")
                    stack.enter_context(code.indent())
                code.writeline(f"tmpbuf[{itervar_inner}] = {rhs};")
            load_line = self._get_vec_load_line("tmpbuf.data()", 0, dtype)  # type: ignore[arg-type]
            code.writeline(f"return {load_line};")
        code.writeline("()")
        csevar = self.cse.generate(buffer, code)
        assert isinstance(csevar, CppCSEVariable)
        csevar.is_vec = True
        return csevar

    def load(self, name: str, index: sympy.Expr):
        opt_ctx: OptimizationContext = get_current_node_opt_ctx()
        var = self.args.input(name)
        index = self.rename_indexing(index)
        dtype = V.graph.get_dtype(name)
        tiling_var = self.itervars[self.tiling_idx]
        stride = stride_at_vec_range(index, tiling_var, self.tiling_factor)
        if stride == 0:
            # load scalar and lazily broadcast it on demand
            return super().load(name, index)
        non_contiguous = stride != 1 or self.index_indirect_depends_on(
            index, tiling_var
        )
        if non_contiguous:
            csevar = self.load_non_contiguous(var, index, dtype)
        else:
            line = self._get_vec_load_line(var, index, dtype, self._load_mask)
            csevar = self.cse.generate(self.loads, line)  # type: ignore[assignment]
        assert isinstance(csevar, CppCSEVariable)
        csevar.update_on_args("load", (name, index), {})
        csevar.is_vec = True
        return csevar

    def _get_vec_store_line(
        self,
        value: Union[str, CppCSEVariable],
        var: str,
        index: sympy.Expr,
        dtype: torch.dtype,
    ):
        """
        Get a store line str that stores `value` into `var` at `index` of `dtype`.
        :param value: Vectorized type templaterized on `dtype`.
        :param var: buffer to store into.
        :index: index into the `var`.
        """
        # when value's type is str (e.g., welford reduction), caller should make sure
        # it is a vector
        assert isinstance(value, str) or (
            isinstance(value, CppCSEVariable) and value.is_vec
        ), value
        tiling_var = self.itervars[self.tiling_idx]
        assert index.has(tiling_var), f"index: {index}, tiling_var: {tiling_var}"
        var_expr = f"{var} + {cexpr_index(index)}"
        stride = stride_at_vec_range(index, tiling_var, self.tiling_factor)
        non_contiguous = stride != 1 or self.index_indirect_depends_on(
            index, tiling_var
        )
        if non_contiguous:
            var_expr = "tmpbuf"
        if dtype == torch.float:
            line = f"{value}.store({var_expr});"
        else:
            line = f"{value}.store({var_expr}, {self.tiling_factor});"
        if non_contiguous:
            inner = sympy_index_symbol(f"{tiling_var}_inner")
            new_index = self.scale_index_with_offset(
                index, itervar_idx=self.tiling_idx, offset=inner
            )
            tmp_bufsize = (
                f"{self.tiling_factor}*sizeof(float)/sizeof({DTYPE_TO_CPP[dtype]})"
            )
            line = (
                f"{{ __at_align__ {DTYPE_TO_CPP[dtype]} tmpbuf[{tmp_bufsize}]; {line} "
                f"for (long {inner} = 0; {inner} < {self.tiling_factor}; {inner}++) "
                f"{var}[{cexpr_index(new_index)}] = tmpbuf[{inner}]; }}"
            )
        return line

    def store(self, name, index, value, mode=None):
        assert "buf" in name
        assert mode is None
        assert isinstance(value, CppCSEVariable), value
        if not value.is_vec:
            # this happens when we store a scalar into a vectorized buffer like "fill"
            value = self.broadcast(value)
        opt_ctx: OptimizationContext = get_current_node_opt_ctx()
        var = self.args.output(name)
        self.cache_fp32_cse_var_before_lowp_store(value)
        index = self.rename_indexing(index)
        self.stores.writeline(
            DeferredLine(
                name,
                self._get_vec_store_line(value, var, index, V.graph.get_dtype(name)),
            )
        )

    def reduction(self, dtype, src_dtype, reduction_type, value):
        assert reduction_type in {
            "max",
            "min",
            "sum",
            "prod",
            "xor_sum",
            "welford_reduce",
            "welford_combine",
        }
        assert dtype == src_dtype
        assert dtype in [torch.float, torch.int64]
        assert isinstance(value, CppCSEVariable), value

        if not value.is_vec:
            value = self.broadcast(value)

        acc_type = reduction_acc_type(reduction_type, dtype)
        acc_type_vec = self.reduction_acc_type_vec(reduction_type, dtype)

        if (reduction_type, acc_type) not in self.reduction_omp_dec:
            if RTYPE_TO_CPP[reduction_type] not in NATIVE_OMP_RTYPES:
                # Scalar reduction for other reductions are declared by default
                self.reduction_prefix.splice(
                    f"""\
#pragma omp declare reduction(\
{RTYPE_TO_CPP[reduction_type]}:{acc_type}:\
omp_out = {reduction_combine(reduction_type, "omp_out", "omp_in")}) \
initializer(omp_priv={{{reduction_init(reduction_type, dtype)}}})
            """
                )
            self.reduction_omp_dec[reduction_type, acc_type] = RTYPE_TO_CPP[
                reduction_type
            ]

        if (reduction_type, acc_type_vec) not in self.reduction_omp_dec:
            self.reduction_prefix.splice(
                f"""\
#pragma omp declare reduction(\
{RTYPE_TO_CPP[reduction_type]}:{acc_type_vec}:\
omp_out = {self.reduction_combine_vec(reduction_type, "omp_out", "omp_in")}) \
initializer(omp_priv={{{self.reduction_init_vec(reduction_type, dtype)}}})
            """
            )
            self.reduction_omp_dec[reduction_type, acc_type_vec] = RTYPE_TO_CPP[
                reduction_type
            ]

        reduction_key = src_dtype, reduction_type, value
        if reduction_key in self.reduction_cse.reduction_cache:
            return self.reduction_cse.reduction_cache[reduction_key]

        acc = self.reduction_cse.generate(
            self.loads, f"reduction {reduction_key}", write=False
        )
        acc_vec = f"{acc}_vec"

        self.reduction_var_map[acc_vec] = reduction_type
        self.reduction_prefix.writeline(
            f"{acc_type} {acc} = {reduction_init(reduction_type, dtype)};"
        )
        self.reduction_prefix.writeline(
            f"{acc_type_vec} {acc_vec} = {self.reduction_init_vec(reduction_type, dtype)};"
        )
        self.stores.writeline(
            f"{acc_vec} = {self.reduction_combine_vec(reduction_type, acc_vec, value)};"
        )

        tmpvar: Union[str, CSEVariable]
        if self.tiling_idx >= self.reduction_depth:
            # Horizontal reduction
            if is_welford_reduction(reduction_type):
                assert (
                    self._get_num_vectors(dtype) == 1
                ), "Welford reduction does not support VectorizedN (N>1)"
                next_value = f"welford_vec_reduce_all({acc_vec})"
            else:
                reduce_all_body = (
                    "{ return "
                    + self.reduction_combine_vec(reduction_type, "x", "y")
                    + "; }"
                )
                vec = f"at::vec::Vectorized<{DTYPE_TO_CPP[dtype]}>"
                vec_reduce_all_func = f"at::vec::vec_reduce_all<{DTYPE_TO_CPP[dtype]}>"
                next_value = f"{vec_reduce_all_func}([]({vec}& x, {vec}& y) {reduce_all_body}, {acc_vec})"

            self.reduction_suffix.writeline(
                f"{acc} = {reduction_combine(reduction_type, acc, next_value)};"
            )
            tmpvar = acc
        else:
            tmpvar = acc_vec

        result = reduction_project(reduction_type, tmpvar)
        self.reduction_cse.reduction_cache[reduction_key] = result
        return result

    def store_reduction(self, name, index, value):
        index = self.rename_indexing(index)
        var = self.args.output(name)
        out_dtype = V.graph.get_dtype(name)
        # Only float reductions are vectorized currently
        dtype = torch.float
        if self.tiling_idx >= self.reduction_depth:
            # Horizontal reduction
            self.reduction_suffix.writeline(
                DeferredLine(
                    name,
                    f"{var}[{cexpr_index(index)}] = static_cast<{DTYPE_TO_CPP[out_dtype]}>({value});",
                )
            )
        else:
            # Vertical reduction
            store_lines = []
            if out_dtype != dtype:
                if out_dtype in DTYPE_LOWP_FP and dtype == torch.float:
                    _lowp_fp_tmpvar_vec = f"{DTYPE_TO_CPP[out_dtype]}_{value}"
                    store_lines = [
                        DeferredLine(
                            name,
                            f"auto {_lowp_fp_tmpvar_vec} = cvt_fp32_to_lowp_fp<{DTYPE_TO_CPP[out_dtype]}>({value});",
                        )
                    ]
                    value = _lowp_fp_tmpvar_vec
                else:
                    raise AssertionError(
                        f"Unsupported reduction type from {dtype} to {out_dtype}"
                    )
            store_lines += [
                DeferredLine(
                    name,
                    self._get_vec_store_line(value, var, index, out_dtype),
                )
            ]
            self.reduction_suffix.writelines(store_lines)

    def broadcast(self, scalar_var: CppCSEVariable) -> CppCSEVariable:
        assert not scalar_var.is_vec
        if scalar_var.dtype == torch.bool:
            vec_var = self.cse.generate(
                self.compute, f"to_float_mask({scalar_var.name})"
            )
        else:
            assert scalar_var.dtype is not None
            vec_var = self.cse.generate(
                self.compute,
                f"{self._get_vec_type(scalar_var.dtype)}({scalar_var.name})",
            )
        assert isinstance(vec_var, CppCSEVariable)
        vec_var.dtype = scalar_var.dtype
        vec_var.dependent_itervars = scalar_var.dependent_itervars
        vec_var.is_vec = True
        return vec_var

    def arange(
        self, index: Union[sympy.Expr, CppCSEVariable], stride: sympy.Symbol
    ) -> CppCSEVariable:
        if isinstance(index, sympy.Expr):
            index = cexpr(index)
        else:
            assert isinstance(index, CppCSEVariable)
            assert not index.is_vec
        csevar = self.cse.generate(
            self.compute,
            f"{self._get_vec_type(torch.int32)}::arange({index}, {stride})",
        )
        assert isinstance(csevar, CppCSEVariable)
        csevar.dtype = torch.int32
        csevar.is_vec = True
        return csevar

    def reduction_init_vec(self, reduction_type, dtype):
        scalar_type = DTYPE_TO_COMPUTATION_DTYPE[dtype]
        vec_type = self._get_vec_type(scalar_type)

        if is_welford_reduction(reduction_type):
            return f"Welford<{vec_type}>()"

        scalar_init = reduction_init(reduction_type, dtype)
        return f"{vec_type}({scalar_init})"

    def reduction_acc_type_vec(self, reduction_type, dtype):
        assert reduction_type not in {"argmin", "argmax"}
        scalar_type = DTYPE_TO_COMPUTATION_DTYPE[dtype]
        vec_type = self._get_vec_type(scalar_type)
        if is_welford_reduction(reduction_type):
            return f"Welford<{vec_type}>"

        return vec_type

    def reduction_combine_vec(self, reduction_type, var, next_value):
        if reduction_type == "max":
            return f"at::vec::maximum({var}, {next_value})"
        elif reduction_type == "min":
            return f"at::vec::minimum({var}, {next_value})"
        elif reduction_type == "sum":
            return f"{var} + {next_value}"
        elif reduction_type == "prod":
            return f"{var} * {next_value}"
        elif reduction_type == "xor_sum":
            return f"{var} ^ {next_value}"
        elif reduction_type == "welford_reduce":
            return f"welford_combine({var}, {next_value})"
        elif reduction_type == "welford_combine":
            if isinstance(next_value, tuple):
                # When reading a value from Inductor IR we have a tuple of variable names
                mean, m2, weight = next_value
            else:
                # When combining intermediate accumulators we have a Welford<T> struct
                mean, m2, weight = reduction_project(reduction_type, next_value)
            return f"welford_combine({var}, {{{mean}, {m2}, {weight}}})"
        else:
            raise NotImplementedError()


class CppTile2DKernel(CppVecKernel):
    """
    A vector kernel that handles the 2d tiles with the tile size defined in `tiling_factor` on
    the inner-most loop level and one of the outer loop level (`outer_tiling_idx`). When the data
    tile is accessed in a contiguous way from the outer loop axis, a transposition is applied on the
    tile to make the access contiguous from the inner-most loop axis. Then, the same vectorization
    logic from its parent `CppVecKernel` is leveraged for load/store/compute. The transposed tile load
    and store are generated into kernel.preloads and kernel.poststores buffers.

    The loop structure looks like below:
    for ...
      for i_outer ...
        for ...
          for inner_most ...
            // generated by CppTile2DKernel
            float tmp0[16*16]; at::vec::transpose_mxn<...>(tmp0, in_ptr0 + ..., ...); // into kernel.preloads
            float tmp1[16*16]; // into kernel.preloads
            for i_inner ... { // the kernel inner loop
              vectorized loads/compute/stores (e.g., load tmp0, store tmp1) // into kernel.loads/compute/stores
            }
            at::vec::transpose_mxn(out_ptr0 + ..., tmp1, ...) // into kernel.poststores
          for inner_most ... (tail)
            // generated by CppVecKernel
            ...
      for i_outer ... (tail)
        for ...
          for ...
            // generated by CppKernel
            ...
    """

    overrides = CppTile2DOverrides  # type: ignore[assignment]

    def __init__(self, args, num_threads, tiling_factor, tiling_indices, tiling_dtype):
        super().__init__(
            args, num_threads, tiling_factor, tiling_indices[1], tiling_dtype
        )
        self.tiling_indices = tiling_indices

    def inner_itervar(self):
        return sympy_index_symbol(f"{self.itervars[self.outer_idx]}_inner")

    def need_vec_transpose(self, index):
        outer_var = self.itervars[self.outer_idx]
        inner_var = self.itervars[self.tiling_idx]
        outer_stride = stride_at_vec_range(index, outer_var, self.tiling_factor)
        inner_stride = stride_at_vec_range(index, inner_var, self.tiling_factor)
        return (
            self._load_mask is None  # TODO: support transposition with mask
            and outer_stride == 1
            and index.has(inner_var)
            and not inner_stride.has(inner_var)
            and not inner_stride.has(outer_var)
        )

    def gen_transposed_tile_load_store(self, name, var, index, is_store):
        # transposed tile load/store outside the kernel inner loop
        dtype = V.graph.get_dtype(name)
        factor = self.tiling_factor
        src = f"{var} + {cexpr_index(index)}"
        dst = "__place_holder__"
        ld_src = f"{cexpr_index(stride_at_vec_range(index, self.itervars[self.tiling_idx], self.tiling_factor))}"
        ld_dst = f"{factor}"
        if is_store:
            src, dst = dst, src
            ld_src, ld_dst = ld_dst, ld_src

        need_define = True
        load_or_store = f"at::vec::transpose_mxn<{DTYPE_TO_CPP[dtype]},{factor},{factor}>({src}, {ld_src}, {dst}, {ld_dst});"
        if is_store:
            tile_var = self.cse.newvar()
        elif load_or_store not in self.cse.cache:
            tile_var = self.cse.generate(self.preloads, load_or_store, write=False)
        else:
            need_define = False
            tile_var = self.cse.cache[load_or_store]

        if need_define:
            define_line = f"{DTYPE_TO_CPP[dtype]} {tile_var}[{factor}*{factor}] __attribute__ ((aligned ({factor})));"
            self.preloads.writeline(define_line)

        load_or_store = load_or_store.replace("__place_holder__", str(tile_var))
        if is_store:
            self.poststores.writeline(DeferredLine(name, load_or_store))
        else:
            self.preloads.writeline(load_or_store)

        return tile_var

    def load(self, name: str, index: sympy.Expr):
        opt_ctx: OptimizationContext = get_current_node_opt_ctx()
        var = self.args.input(name)
        index = self.rename_indexing(index)

        inner = self.inner_itervar()
        if self.need_vec_transpose(index):
            tile_var = self.gen_transposed_tile_load_store(
                name, var, index, is_store=False
            )
            # vector load inside the kernel inner loop
            loadbuf = f"{tile_var} + {cexpr_index(inner * self.tiling_factor)}"
            dtype = V.graph.get_dtype(name)
            line = self._get_vec_load_line(loadbuf, 0, dtype)  # type: ignore[arg-type]
            csevar = self.cse.generate(self.loads, line)
            csevar.update_on_args("load", (name, index), {})
            assert isinstance(csevar, CppCSEVariable)
            csevar.is_vec = True
            return csevar
        else:
            new_index = self.transform_indexing(index)
            return super().load(name, new_index)

    def store(self, name, index, value, mode=None):
        assert "buf" in name
        opt_ctx: OptimizationContext = get_current_node_opt_ctx()
        var = self.args.output(name)

        inner = self.inner_itervar()
        index = self.rename_indexing(index)
        assert mode is None
        if self.need_vec_transpose(index):
            tile_var = self.gen_transposed_tile_load_store(
                name, var, index, is_store=True
            )
            # vector store inside the kernel inner loop
            storebuf = f"{tile_var} + {cexpr_index(inner * self.tiling_factor)}"
            if V.graph.get_dtype(name) in DTYPE_LOWP_FP:
                line = f"{value}.store({storebuf}, {self.tiling_factor});"
            elif V.graph.get_dtype(name) in (torch.uint8, torch.int8):
                line = f"{value}.store({storebuf}, {self.tiling_factor});"
            else:
                line = f"{value}.store({storebuf});"
            self.stores.writeline(DeferredLine(name, line))
        else:
            new_index = self.transform_indexing(index)
            super().store(name, new_index, value, mode)

    def codegen_inner_loops(self, code):
        inner = self.inner_itervar()
        code.writeline(
            f"for (long {inner} = 0; {inner} < {self.tiling_factor}; {inner}++)"
        )

    def set_ranges(self, group, reduction_group):
        vars = super().set_ranges(group, reduction_group)
        # do vertical reduction as the tail loop
        self.outer_idx, self.tiling_idx = (
            self.tiling_indices
            if self.tiling_indices[1] < self.reduction_depth
            else reversed(self.tiling_indices)
        )
        return vars

    def transform_indexing(self, index: sympy.Expr) -> sympy.Expr:
        return self.scale_index_with_offset(
            index,
            itervar_idx=self.outer_idx,
            offset=self.inner_itervar(),
        )


class CppVecKernelChecker(CppVecKernel):
    def __init__(self, args, num_threads, tiling_factor, tiling_idx=-1):
        super().__init__(args, num_threads, tiling_factor, tiling_idx)

        # Since this kernel is only for checker but does not generate any
        # code, so we need to decrease the kernel count.
        metrics.generated_kernel_count -= 1

        # Used to record the graph wrapper code as the wrapper_code status could be
        # changed during graph run.
        self._orig_wrapper_code = None

        self.simd_vec = True

        self.fast_vec_list = []
        for k, v in CppVecOverrides.__dict__.items():
            if isinstance(v, staticmethod):
                self.fast_vec_list.append(k)
        self.exit_stack = contextlib.ExitStack()

        # Cache all the load result
        self.load_supported_dtypes: List[torch.dtype] = [
            torch.float,
            torch.bfloat16,
            torch.float16,
            torch.bool,
            torch.uint8,
            torch.int8,
            torch.int32,
            torch.int64,
        ]
        self.store_supported_dtypes: List[torch.dtype] = [
            torch.float,
            torch.bfloat16,
            torch.float16,
            torch.uint8,
            torch.int8,
            torch.int32,
            torch.int64,
        ]
        # Cache the dtypes of the store operation. If the store is mixing dtypes, the
        # vectorization would not support it as it is hard to determine the vec dtype
        self.store_dtypes: List[torch.dtype] = []
        # The dtype is used for vectorization
        self.vec_dtype: torch.dtype = torch.float32

    def disable_vec(self, msg=None):
        if schedule_log.isEnabledFor(logging.DEBUG):
            schedule_log.debug("Disabled vectorization: %s", msg)
        self.simd_vec = False

    def is_mask(self, name: str, users: Dict[torch.fx.Node, None]):
        load_type = V.graph.get_dtype(name)
        if load_type == torch.bool:
            return all(user.target in ("where", "masked") for user in users.keys())
        elif load_type in (torch.uint8, torch.int8):
            """
            If the load value is torch.uint8/int8, then we only support the loaded
            value is as the mask.
            """
            if not all(
                user.target == "to_dtype" and user.args[-1] == torch.bool
                for user in users.keys()
            ):
                return False

            for to_dtype_node in users.keys():
                assert to_dtype_node.target == "to_dtype"
                if not all(
                    user.target in ("where", "masked")
                    for user in to_dtype_node.users.keys()
                ):
                    return False
            return True
        else:
            return False

    def is_load_int8_as_float(self, name: str, users: Dict[torch.fx.Node, None]):
        """
        Check:
        1. load_type is torch.uint8 or torch.int8
        2. has 1 user node of target to_dtype
        3. dtype of to_dtype is torch.float
        """
        load_type = V.graph.get_dtype(name)
        if load_type not in (torch.uint8, torch.int8):
            return False
        if len(users) == 1:
            user = next(iter(users))
            if (user.target == "to_dtype") and (user.args[-1] == torch.float):
                return True
            return False
        return False

    def can_store_fp32_as_int8(self, store_var: str, value_node: torch.fx.Node):
        """
        Check:
        1. store_type is torch.uint8/torch.int8
        2. value_node is of target to_dtype
        3. dtype of to_dtype node is torch.uint8/torch.int8
        """
        store_type = V.graph.get_dtype(store_var)
        if store_type not in (torch.uint8, torch.int8):
            return False
        if value_node.target == "to_dtype" and value_node.args[-1] in (
            torch.uint8,
            torch.int8,
        ):
            return True

        return False

    def is_load_integer_scalar_tensor(self, name: str, index: sympy.Expr):
        load_dtype = V.graph.get_dtype(name)
        buffer = V.graph.get_buffer(name)
        return (
            load_dtype in [torch.int32, torch.int64]
            and isinstance(buffer, TensorBox)
            and isinstance(buffer.data, StorageBox)
            and (len(buffer.data.layout.size) == 0)
            and (index == 0)
        )

    def load(self, name: str, index: sympy.Expr):
        with RecordOptimizationContext(__name__) as node_ctx:
            load_dtype = V.graph.get_dtype(name)
            opt_ctx: OptimizationContext = node_ctx.get_opt_ctx()
            assert opt_ctx
            opt_ctx.dtype = load_dtype
            opt_ctx.is_load_as_mask = self.is_mask(name, node_ctx.get_fx_node().users)
            opt_ctx.is_load_int8_as_float = self.is_load_int8_as_float(
                name, node_ctx.get_fx_node().users
            )

            var = self.cse.newvar()

            if len(self.itervars) == 0:
                self.disable_vec("not a loop")
                return var

            if load_dtype in (torch.bool, torch.uint8, torch.int8) and not (
                opt_ctx.is_load_as_mask or opt_ctx.is_load_int8_as_float
            ):
                if not opt_ctx.is_load_as_mask:
                    self.disable_vec(f"{load_dtype} not loaded as mask")
                elif not opt_ctx.is_load_int8_as_float:
                    self.disable_vec(f"{load_dtype} not loaded as float")
                return var

            if (
                (load_dtype not in self.load_supported_dtypes)
                and not self.is_load_integer_scalar_tensor(name, index)
                and index.has(self.itervars[self.tiling_idx])
            ):
                self.disable_vec(f"{load_dtype} not supported by load")
                return var

            return var

    def store(self, name, index, value, mode=None):
        with RecordOptimizationContext(__name__) as node_ctx:
            if len(self.itervars) == 0:
                self.disable_vec("not a loop")
                return self.simd_vec

            store_dtype = V.graph.get_dtype(name)

            opt_ctx: OptimizationContext = node_ctx.get_opt_ctx()
            assert opt_ctx
            opt_ctx.dtype = store_dtype

            store_dtype = torch.float if store_dtype == torch.float32 else store_dtype
            self.store_dtypes.append(store_dtype)
            if store_dtype not in self.store_supported_dtypes:
                self.disable_vec(f"{store_dtype} not supported by store")
                return self.simd_vec

            if store_dtype in (torch.uint8, torch.int8):
                value_node = node_ctx.get_fx_node().all_input_nodes[-1]
                if not self.can_store_fp32_as_int8(name, value_node):
                    self.disable_vec("not support store float32 as uint8/int8")
                    return self.simd_vec

            assert "buf" in name
            index = self.rename_indexing(index)

            if mode:
                self.disable_vec(f"store mode: {mode}")
                return self.simd_vec

            if index.is_number:
                self.disable_vec(f"constant store index: {index}")
            return self.simd_vec

    def reduction(self, dtype, src_dtype, reduction_type, value):
        if (
            (dtype == torch.float and src_dtype == torch.float)
            or (dtype == torch.int64 and src_dtype == torch.int64)
            and reduction_type in VECTORIZABLE_RTYPES
        ):
            pass
        else:
            self.disable_vec(
                f"reduction: dtype {dtype}, src_dtype {src_dtype}, reduction_type {reduction_type}"
            )
        if is_welford_reduction(reduction_type):
            return tuple([self.simd_vec] * 3)
        return self.simd_vec

    def store_reduction(self, name, index, value):
        return self.simd_vec

    def is_supported_cmp(self, node: torch.fx.Node):
        def get_node_dtype(node):
            if type(node) == torch.fx.Node:
                opt_ctx: OptimizationContext = get_current_node_opt_ctx()
                return opt_ctx.dtype if opt_ctx else None
            else:
                return None

        def get_cmp_dtypes(node: torch.fx.Node):
            return get_node_dtype(node.args[-2]), get_node_dtype(node.args[-1])

        assert len(node.args) >= 2
        # cmp(x, y): y is a magic value like x >= 1
        if type(node.args[-1]) in [int, float]:
            return True
        # cmp(x, y): x is a magic value like 1 >= y
        if type(node.args[-2]) in [int, float]:
            return False

        left_dtype, right_dtype = get_cmp_dtypes(node)
        if left_dtype is None or right_dtype is None:
            # TODO(Eikan): To record, deduce and propagate the data type of every expression.
            return True
        else:
            return left_dtype == right_dtype

    def __exit__(self, exc_type, exc_val, exc_tb):
        assert self._orig_wrapper_code is not None
        # Restore the wrapper_code
        V.graph.wrapper_code = self._orig_wrapper_code
        self.exit_stack.__exit__(exc_type, exc_val, exc_tb)

    def __enter__(self):
        # Record the graph wrapper code. The wrapper_code status could be
        # changed during graph run. Regarding this checker, we also need to
        # run the graph but we don't expect to change any status that would
        # impact the code generation. Hence, we record the graph wrapper code
        # and replace it with a dummy wrapper_code and then restore to the
        # original one as long as the checker is finished.
        self._orig_wrapper_code = V.graph.wrapper_code
        V.graph.wrapper_code = WrapperCodeGen()

        parent_handler = V.MockHandler()

        class VecCheckerProxy:
            bin_cmp_ops = ["eq", "ne", "le", "ge", "lt", "gt"]

            @staticmethod
            def _bin_cmp_op(x, y):
                current_node: torch.fx.Node = V.interpreter.current_node
                if not self.is_supported_cmp(current_node):
                    self.disable_vec(f"binary comparison op: {current_node}")
                return self.simd_vec

            @staticmethod
            def __getattr__(name):  # type: ignore[misc]
                def inner(*args, **kwargs):
                    if name in VecCheckerProxy.bin_cmp_ops:
                        return VecCheckerProxy._bin_cmp_op(args, kwargs)

                    if name not in self.fast_vec_list:
                        self.disable_vec(f"op: {name}")

                    parent_val = getattr(parent_handler, name)(*args, **kwargs)
                    return pytree.tree_map(lambda _: self.simd_vec, parent_val)

                return inner

            @staticmethod
            def load(name: str, index: sympy.Expr):
                return self.load(name, index)

            @staticmethod
            def store(name, index, value, mode=None):
                return self.store(name, index, value, mode=mode)

            @staticmethod
            def reduction(dtype, src_dtype, reduction_type, value):
                return self.reduction(dtype, src_dtype, reduction_type, value)

            @staticmethod
            def store_reduction(name, index, value):
                return self.store_reduction(name, index, value)

            @staticmethod
            def constant(val, dtype):
                with RecordOptimizationContext(__name__) as node_ctx:
                    opt_ctx: OptimizationContext = node_ctx.get_opt_ctx()
                    assert opt_ctx
                    # VecKernel override dtype for constant
                    # Vectorization only support int32/fp32 now
                    # So if dtype = int64/fp64, we will cast it to int32/fp32 if possible
                    i32_iinfo = torch.iinfo(torch.int32)
                    if (
                        dtype == torch.int64
                        and val <= i32_iinfo.max
                        and val >= i32_iinfo.min
                    ):
                        opt_ctx.dtype = torch.int32

                    f32_iinfo = torch.finfo(torch.float32)
                    if dtype == torch.double:
                        if (
                            (val <= f32_iinfo.max and val >= f32_iinfo.min)
                            or (val == torch.inf)
                            or (val == -torch.inf)
                        ):
                            opt_ctx.dtype = torch.float32

                    supported_dtypes = [
                        torch.float32,
                        torch.int32,
                        torch.int64,
                        torch.bfloat16,
                        torch.float16,
                        torch.bool,
                    ]

                    if opt_ctx.dtype not in supported_dtypes or (
                        opt_ctx.dtype == torch.int32
                        and not all(
                            user.target in VecCheckerProxy.bin_cmp_ops
                            for user in node_ctx.current_node.users
                        )
                    ):
                        self.disable_vec(f"constant dtype: {opt_ctx.dtype}")
                    return val

            @staticmethod
            def index_expr(expr, dtype):
                assert len(self.ranges) == len(self.itervars)
                if not len(self.ranges) or not all(
                    not isinstance(range, sympy.Expr) or sympy.simplify(range).is_number
                    for range in self.ranges
                ):
                    # if the range value is sympy.Expr, we might could not deduce the accurate loop interval.
                    self.disable_vec(f"index_expr: {expr}, dtype {dtype}")
                    return self.cse.newvar()

                def can_use_int32():
                    free_symbols = list(expr.free_symbols)
                    sizes = {
                        k: v
                        for k, v in zip(self.itervars, self.ranges)
                        if k in free_symbols
                    }
                    # Trivial case: Range empty
                    if any(v == 0 for v in sizes.values()):
                        return True

                    vars_ranges = {k: ValueRanges(0, v - 1) for k, v in sizes.items()}
                    if not vars_ranges or len(vars_ranges) != len(free_symbols):
                        i32_iinfo = torch.iinfo(torch.int32)
                        return (
                            expr.is_number
                            and expr <= i32_iinfo.max
                            and expr >= i32_iinfo.min
                        )
                    expr_ranges = bound_sympy(expr, vars_ranges)
                    if math.isinf(expr_ranges.lower) or math.isinf(expr_ranges.upper):  # type: ignore[arg-type]
                        return False
                    # If something takes the values 0..7, we will compare in the loop
                    # x < 8. As such, for the loop not to overflow in the last iteration, we want
                    # to check that expr_ranges.upper + 1 is representable as well
                    return range_expressable_in_32_bits(
                        ValueRanges(
                            int(expr_ranges.lower), int(expr_ranges.upper) + 1  # type: ignore[arg-type]
                        )
                    )

                with RecordOptimizationContext(__name__) as node_ctx:
                    assert len(self.ranges) == len(self.itervars)
                    opt_ctx: OptimizationContext = node_ctx.get_opt_ctx()
                    assert opt_ctx
                    if (
                        dtype == torch.int64
                        and can_use_int32()
                        and all(
                            user.target in VecCheckerProxy.bin_cmp_ops
                            for user in node_ctx.current_node.users
                        )
                    ):
                        opt_ctx.dtype = torch.int32
                    else:
                        opt_ctx.dtype = dtype
                        self.disable_vec(f"index_expr: {expr}, dtype {dtype}")

                    tmp_var = self.cse.newvar()
                    return tmp_var

            @staticmethod
            def indirect_indexing(index_var, size, check=True):
                return sympy_index_symbol(str(index_var))

            @staticmethod
            def masked(mask, body, other):
                body()
                return self.cse.newvar()

            @staticmethod
            def to_dtype(x, dtype, src_dtype=None):
                with RecordOptimizationContext(__name__) as node_ctx:
                    opt_ctx: OptimizationContext = node_ctx.get_opt_ctx()
                    assert opt_ctx
                    opt_ctx.dtype = dtype

                    cur_node = node_ctx.get_fx_node()
                    input_value: torch.fx.Node = cur_node.all_input_nodes[1]
                    if dtype == torch.float:
                        if input_value.target in [
                            "load",
                        ]:
                            # Support masked_load for BF16/FP16. Because the legalization will
                            # insert to_dtype to convert the BF16/FP16 input to FP32.
                            dtype = (
                                V.graph.get_dtype(input_value.args[1])  # type: ignore[arg-type]
                                if input_value.target == "load"
                                else input_value.args[-1]
                            )
                            if dtype in [
                                torch.float16,
                                torch.bfloat16,
                                torch.float,
                                torch.float64,
                                torch.uint8,
                                torch.int8,
                                torch.int32,
                                torch.int64,
                            ]:
                                # Convert from dtype to torch.float
                                pass
                            else:
                                self.disable_vec(f"to_dtype: dtype {dtype}")
                    elif dtype in DTYPE_LOWP_FP:
                        if not all(usr.target == "store" for usr in cur_node.users):
                            self.disable_vec(
                                "to_dtype: bfloat16/float16 expecting users are all stores"
                            )
                            return x

                        store_names = [usr.args[1] for usr in cur_node.users]
                        if not all(
                            V.graph.get_dtype(name) in [dtype] for name in store_names
                        ):
                            self.disable_vec(
                                "to_dtype: expecting all stores into bfloat16 or float16"
                            )
                            return x
                    elif dtype == torch.bool:
                        pass
                    elif dtype in (torch.uint8, torch.int8):
                        # Only allow below 2 cases:
                        # Case 1: to_int8 and store which corresponding to the single quant node
                        # at last of fusion pattern.
                        is_to_int8_and_store = all(
                            usr.target in ["store"] for usr in cur_node.users
                        )
                        # Case 2: to_int8 and to_float which corresponding to pair of quant/dequant node
                        # at middle of fusion pattern.
                        is_to_int8_and_to_float = all(
                            (
                                usr.target in ["to_dtype"]
                                and usr.args[2] == torch.float32
                            )
                            for usr in cur_node.users
                        )
                        if not (is_to_int8_and_store or is_to_int8_and_to_float):
                            self.disable_vec(f"to_dtype: dtype {dtype}")
                    elif dtype in [torch.int64, torch.int32]:
                        pass
                    else:
                        self.disable_vec(f"to_dtype: dtype {dtype}")
                    return x

        self.exit_stack.enter_context(V.set_ops_handler(VecCheckerProxy()))
        self.exit_stack.enter_context(V.set_kernel_handler(self))
        return self


class CppKernelProxy(CppKernel):
    def __init__(self, kernel_group):
        super().__init__(kernel_group.args, kernel_group.ws.num_threads)
        self.kernel_group = kernel_group
        self.loop_nest = None
        self.call_ranges = None
        self.picked_vec_isa: codecache.VecISA = codecache.pick_vec_isa()

    def data_type_propagation(self, nodes):
        for _node in nodes:
            assert isinstance(_node, SchedulerNode)
            DataTypePropagation.propagate_scheduler_node(_node)

    # Check if all the nodes of a given fx graph can support BF16/FP16
    def is_lowp_fp_scheduler(self, scheduler_node: SchedulerNode):
        if not isinstance(scheduler_node._body, ir.LoopBody):
            return True

        _lowp_fp_type: Optional[torch.dtype] = None

        # Propagate the dtype to check if all the fx node is bf16/fp16
        DataTypePropagation.propagate_scheduler_node(scheduler_node)

        sub_blocks = [scheduler_node._body.root_block] + list(
            scheduler_node._body.subblocks.values()
        )
        for sub_block in sub_blocks:
            for _node in sub_block.graph.nodes:
                # TODO(Eikan): Regarding get_index and index_expr, we should conclude the
                # the data type as well.
                if _node.op == "placeholder" or _node.target in (
                    "get_index",
                    "index_expr",
                ):
                    continue

                # Fast path if all operations can support bf16/fp16 without converting to fp32
                if _node.target not in [
                    "load",
                    "store",
                    "abs",
                    "neg",
                    "output",
                ]:
                    return False

                if hasattr(_node, "meta") and _node.meta:
                    assert OptimizationContext.key in _node.meta
                    opt_ctx: OptimizationContext = _node.meta[OptimizationContext.key]
                    if not opt_ctx.dtype or opt_ctx.dtype not in DTYPE_LOWP_FP:
                        return False
                    if _lowp_fp_type:
                        assert (
                            _lowp_fp_type == opt_ctx.dtype
                        ), "scheduler node do not support bf16/fp16 mix"
                    else:
                        _lowp_fp_type = opt_ctx.dtype
                else:
                    return False

        scheduler_node._lowp_fp_type = _lowp_fp_type  # type: ignore[attr-defined]
        return True

    def legalize_lowp_fp_dtype(self, nodes):
        def add_to_dtype(sub_graph: torch.fx.Graph):
            def is_lowp_fp_load(node: torch.fx.Node):
                if node.target not in ["load"]:
                    return False
                assert len(node.args) == 3
                load_dtype = V.graph.get_dtype(node.args[1])  # type: ignore[arg-type]
                return load_dtype in DTYPE_LOWP_FP

            def is_lowp_fp_store(node: torch.fx.Node):
                if node.target != "store":
                    return False
                _, store_var, _, _, _ = node.args
                store_dtype = V.graph.get_dtype(store_var)  # type: ignore[arg-type]
                return store_dtype in DTYPE_LOWP_FP

            sub_graph_nodes = list(sub_graph.nodes)
            to_lowp_fp_legalized_nodes = []
            for _node in sub_graph_nodes:
                if is_lowp_fp_load(_node):
                    # No need to promote to float if all users are direct stores
                    if all(user.target == "store" for user in _node.users):
                        continue
                    ops = _node.args[0]
                    with sub_graph.inserting_after(_node):
                        to_type_node = sub_graph.call_method(
                            "to_dtype", args=(ops, _node, torch.float)
                        )
                        to_type_node_args = to_type_node.args
                        _node.replace_all_uses_with(to_type_node)
                        to_type_node.args = to_type_node_args
                        metrics.cpp_to_dtype_count += 1
                elif is_lowp_fp_store(_node):
                    ops, name, _, value_var, _ = _node.args
                    # No need to promote to float if it is a user of a load which are all directly stored
                    if value_var.target == "load" and all(
                        user.target == "store" for user in value_var.users
                    ):
                        continue
                    dtype = V.graph.get_dtype(name)
                    with sub_graph.inserting_before(_node):
                        to_type_node = sub_graph.call_method(
                            "to_dtype", args=(ops, value_var, dtype)
                        )
                        _node.replace_input_with(value_var, to_type_node)
                        metrics.cpp_to_dtype_count += 1
                elif _node.target == "reduction":
                    (
                        ops,
                        dtype,
                        src_dtype,
                        reduction_type,
                        value,
                    ) = _node.args
                    if src_dtype in DTYPE_LOWP_FP:
                        # Since we always convert the load/store value to float if the tensor is bfloat16/float16.
                        # Therefore, the reduction should never work with bfloat16/float16 value. Hence, we update
                        # the bfloat16/float16 reduction by
                        #     1) updating the src_dtype to float
                        # and 2) updating the dtype to float if it is bfloat16/float16.
                        assert dtype in [
                            torch.float,
                            torch.bfloat16,
                            torch.float16,
                            torch.int64,
                        ]
                        _node.args = (
                            ops,
                            torch.float if dtype in DTYPE_LOWP_FP else dtype,
                            torch.float,
                            reduction_type,
                            value,
                        )
                elif _node.target == "to_dtype" and _node.args[-1] in DTYPE_LOWP_FP:
                    (ops, x, _) = _node.args
                    # The legalization always loads the BF16/FP16 tensor as FP32 for computation
                    # and converts back to BF16/FP16 after the computation.
                    # Hence, there should be no computation w/ BF16/FP16.
                    # Therefore, we update the to_dtype by replacing the bf16/fp16 dtype with fp32.
                    # Save the legalized to_dtype node for the elimination(eliminate_to_dtype step):
                    #  1) Eliminate the redundant to_dtype node if we have a pattern as follows:
                    #     graph():
                    #       %lowp_fp_legalized = call_method[target=to_dtype](args = (%ops, %input, torch.float))
                    #       %to_dtype2 = call_method[target=to_dtype](args = (%ops, %lowp_fp_legalized, torch.bfloat16/float16))
                    # Regarding the first to_dtype, it is redundant because
                    # the second to_type also converts to the torch.bfloat16/torch.float16.
                    # Hence, we remove the first to_type.
                    to_lowp_fp_legalized_nodes.append(_node)
                    _node.args = (ops, x, torch.float)
                else:
                    pass

            def eliminate_to_dtype(sub_graph: torch.fx.Graph):
                def _eliminate_duplicate_to_node(sub_graph: torch.fx.Graph):
                    # Eliminate the redundant to_dtype node. Let's consider a pattern as follows:
                    #   graph():
                    #     %to_dtype1 = call_method[target=to_dtype](args = (%ops, %input, torch.float), kwargs = {})
                    #     %to_dtype2 = call_method[target=to_dtype](args = (%ops, %to_dtype1, torch.float), kwargs = {})
                    # Regarding the first to_dtype, it is redundant because the second to_type also converts to the
                    # torch.float. Hence, we remove the first to_type
                    def _used_by_to(to_node: torch.fx.Node):
                        return all(usr.target == "to_dtype" for usr in to_node.users)

                    all_to_nodes = [
                        node for node in sub_graph.nodes if node.target == "to_dtype"
                    ]
                    all_to_nodes_and_users = [
                        {node: node.users} for node in all_to_nodes if _used_by_to(node)
                    ]
                    for node_users in all_to_nodes_and_users:
                        for node, users in node_users.items():
                            if node in sub_graph.nodes and (
                                all(usr.args[-1] == node.args[-1] for usr in users)
                                or (
                                    node in to_lowp_fp_legalized_nodes
                                    and all(
                                        usr.args[-1] in DTYPE_LOWP_FP for usr in users
                                    )
                                )
                            ):
                                val_node = node.all_input_nodes[-1]
                                node.replace_all_uses_with(val_node)
                                sub_graph.erase_node(node)

                    # For debug mode, the graph of LoopBody will attach a new GraphModule as
                    # owning_module for debugging while the release mode will not. The lint will
                    # check whether the graph has owning_module to decide if it needs to check
                    # call_module. LoopBody might contain get_index as a module call. But it
                    # is just a function. Hence, it cannot pass the lint check for debug mode.
                    # We bypass the check if the owning_module is None. Eventually, we should call
                    # get_index via call_function but not call_module.
                    if sub_graph.owning_module is None:
                        sub_graph.lint()

                _eliminate_duplicate_to_node(sub_graph)

            eliminate_to_dtype(sub_graph)

        def _legalize_lowp_fp(loop_body: ir.LoopBody):
            sub_blocks = [loop_body.root_block] + list(loop_body.subblocks.values())
            for sub_block in sub_blocks:
                add_to_dtype(sub_block.graph)

        if all(
            isinstance(_node, SchedulerNode) and self.is_lowp_fp_scheduler(_node)
            for _node in nodes
        ):
            # Mark the load node to load bf16/fp16
            for _node in nodes:
                sub_blocks = [_node._body.root_block] + list(
                    _node._body.subblocks.values()
                )
                for sub_block in sub_blocks:
                    for fx_node in sub_block.graph.nodes:
                        if fx_node.target in ["load", "store"]:
                            assert fx_node.meta
                            assert OptimizationContext.key in fx_node.meta
                            opt_ctx: OptimizationContext = fx_node.meta[
                                OptimizationContext.key
                            ]
                            assert opt_ctx.dtype in DTYPE_LOWP_FP

            # Bypass the legalization as the kernel can run with bf16/fp16 directly
            return

        for _node in nodes:
            assert isinstance(_node, SchedulerNode)
            assert isinstance(_node._body, ir.LoopBody)
            node: SchedulerNode = _node

            def is_memory_copy_scheduler_node(node: SchedulerNode):
                op_counts = node.read_writes.op_counts
                return (
                    len(op_counts) == 2 and "load" in op_counts and "store" in op_counts
                )

            should_legalize = not is_memory_copy_scheduler_node(node)
            if should_legalize:
                body: ir.LoopBody = node._body
                _legalize_lowp_fp(body)

    def codegen_nodes(self, nodes: List[SchedulerNode]):
        # Legalize BF16 node by adding to_dtype explicitly
        self.legalize_lowp_fp_dtype(nodes)
        self.data_type_propagation(nodes)

        assert len(nodes) >= 1
        first_node = nodes[0]
        vec_dtype = (
            first_node._lowp_fp_type  # type: ignore[attr-defined]
            if all(
                hasattr(_node, "_lowp_fp_type")
                and _node._lowp_fp_type == first_node._lowp_fp_type  # type: ignore[attr-defined]
                for _node in nodes
            )
            else torch.float
        )

        kernel_group = self.kernel_group
        _, (group, reduction_group) = max(
            nodes, key=lambda x: int(x.is_reduction())
        ).group

        self.set_ranges(group, reduction_group)

        def codegen_kernel(cls, *args):
            with kernel_group.new_kernel(cls, *args) as kernel:
                # Ugly hack to maintain the metrics kernel count since
                # we only count in CppKernelProxy, not those contained in it
                metrics.generated_kernel_count -= 1

                run(kernel)
                return kernel

        def run(kernel):
            vars, reduction_vars = kernel.set_ranges(group, reduction_group)
            in_suffix = False
            for node in nodes:
                if node.group[1] in [
                    (group, reduction_group),
                    (group + reduction_group, ()),
                ]:
                    assert not in_suffix
                    node.run(vars, reduction_vars)
                else:
                    in_suffix = True
                    assert node.group[1] == (
                        group,
                        (),
                    ), f"unexpected group: {node.group[1]} != {group}, {reduction_group}"
                    # we can fuse in some extra pointwise into the suffix
                    with kernel.write_to_suffix():
                        node.run(vars, ())

        scalar_kernel = codegen_kernel(CppKernel)
        V.graph.removed_buffers |= scalar_kernel.removed_buffers
        V.graph.inplaced_to_remove |= scalar_kernel.inplaced_to_remove
        self.loop_nest = LoopNestWithSplit.build(scalar_kernel)

        if not self.picked_vec_isa:
            return

        def select_tiling_indices(tiling_factor):
            all_index = []
            for node in nodes:
                rw = dependencies.extract_read_writes(node._body, *node._sizes)
                all_index += [dep.index for dep in itertools.chain(rw.reads, rw.writes)]
            contig_vars = set()
            contig_vars_list = []
            non_contig_stride_const = set()
            non_contig_stride_other = set()
            for index in all_index:
                for var in index.free_symbols:
                    if not re.search(r"^d\d+$", var.name):
                        continue
                    stride = stride_at_vec_range(index, var, tiling_factor)
                    if stride == 0:
                        continue
                    elif stride == 1:
                        contig_vars.add(int(var.name[1:]))
                        contig_vars_list.append(int(var.name[1:]))
                    elif all(s.name.startswith("s") for s in stride.free_symbols):
                        non_contig_stride_const.add(int(var.name[1:]))
                    else:
                        non_contig_stride_other.add(int(var.name[1:]))
            contig_only = (
                contig_vars - non_contig_stride_const - non_contig_stride_other
            )
            if len(contig_vars) == 0:
                # no contiguous vars
                return [len(self.itervars) - 1]
            if contig_only:
                return sorted(contig_only)[-1:]
            contig_and_const_stride = (
                contig_vars & non_contig_stride_const
            ) - non_contig_stride_other
            contig_vars_sorted = sorted(contig_vars)
            if (
                len(contig_vars_sorted) == 2
                and contig_vars_sorted[-1] in contig_and_const_stride
                and contig_vars_sorted[-1] == len(self.itervars) - 1
            ):
                return contig_vars_sorted
            return sorted(contig_vars_sorted, key=contig_vars_list.count)[-1:]

        def select_tiling(dtype: torch.dtype = torch.float):
            # TODO(jgong5): support alternative tiling factors and data types
            tiling_factor = self.picked_vec_isa.nelements(dtype=dtype)
            tiling_indices = select_tiling_indices(tiling_factor)
            if tiling_indices:
                could_vec = True
                for tiling_indice in tiling_indices:
                    with CppVecKernelChecker(
                        deepcopy(self.kernel_group.args),
                        parallel_num_threads(),
                        tiling_factor,
                        tiling_indice,
                    ) as vec_checker:
                        run(vec_checker)
                        could_vec = could_vec and vec_checker.simd_vec
                        if not could_vec:
                            break
                if could_vec:
                    if len(tiling_indices) == 1:
                        return [tiling_factor], tiling_indices
                    if len(tiling_indices) == 2:
                        return [tiling_factor, tiling_factor], tiling_indices
            return [], []

        # Kernels share the same global contexts like V.graph.wrapper_code, V.kernel.args.
        # But the generated scalar kernel has updated these global contexts. Hence, the other kernels
        # should not do this again to avoid context conflict. By now, we only control the
        # config.inplace_buffers. In the future, we could maintain more contexts.
        with torch._inductor.config.patch(inplace_buffers=False):
            tiling_factors, tiling_indices = select_tiling(vec_dtype)
            assert len(tiling_factors) == len(tiling_indices)
            try:
                if len(tiling_indices) == 1:
                    vec_kernel = codegen_kernel(
                        CppVecKernel, tiling_factors[0], tiling_indices[0], vec_dtype
                    )
                    metrics.generated_cpp_vec_kernel_count += 1
                    main_loop, tail_loop = self.loop_nest.split_with_tiling(
                        tiling_indices[0], factor=tiling_factors[0]
                    )
                    main_loop.set_kernel(vec_kernel)
                    tail_loop.set_kernel(scalar_kernel)
                    main_loop.simd_vec = True
                    tail_loop.simd_omp = True
                    # We chop the loop into two cubes by the nelements - main loop and tail loop.
                    # Regarding the main loop, it is straightforward that it could be vectorized with
                    # nelements. But for the tail loop, it still could be vectorized. For example,
                    # if the nelements is 8(256bits), then the tail loop still could be vectorized
                    # as 4(128bits).
                    tail_loop.simd_nelements = tiling_factors[0] // 2
                elif len(tiling_indices) == 2:
                    assert (
                        tiling_indices[1] == len(self.itervars) - 1
                        and tiling_factors[0] == tiling_factors[1]
                    )
                    tile2d_kernel = codegen_kernel(
                        CppTile2DKernel, tiling_factors[0], tiling_indices, vec_dtype
                    )
                    vec_kernel = codegen_kernel(
                        CppVecKernel, tiling_factors[0], tiling_indices[0], vec_dtype
                    )
                    metrics.generated_cpp_vec_kernel_count += 2
                    outer_main_loop, outer_tail_loop = self.loop_nest.split_with_tiling(
                        tiling_indices[0], factor=tiling_factors[0]
                    )
                    outer_tail_loop.set_kernel(scalar_kernel)
                    (
                        inner_main_loop,
                        inner_tail_loop,
                    ) = outer_main_loop.split_with_tiling(
                        tiling_indices[1] - tiling_indices[0], factor=tiling_factors[0]
                    )
                    inner_main_loop.set_kernel(tile2d_kernel)
                    inner_tail_loop.set_kernel(vec_kernel)
            except CppVecUnsupportedError as e:
                if schedule_log.isEnabledFor(logging.DEBUG):
                    schedule_log.debug("Disabled vectorization: %s", e)

    def codegen_loops(self, code, worksharing):
        self.codegen_loops_impl(self.loop_nest, code, worksharing)


class ReasonFusedNodes(Enum):
    SAME_VARS_REDUCE = "same_vars_reduce"
    COMPATIBLE_REDUCTION = "compatible_reduction"
    COMPATIBLE_RANGES_NO_REDUCTION = "compatible_ranges_no_reduction"


class CppScheduling(BaseScheduling):
    # ctypes limits the number of args to 1024, refer to:
    # https://github.com/python/cpython/commit/a285af7e626d1b81cf09f8b2bf7656f100bc1237
    # We set a conservative threshold here.
    MAX_FUSED_KERNEL_ARGS_NUM = 500

    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.get_kernel_group()
        self._ready_to_flush = False

    def _set_flush_status(self, status: bool):
        self._ready_to_flush = status

    def group_fn(self, sizes):
        return tuple(tuple(map(V.graph.sizevars.simplify, s)) for s in sizes)

    def get_kernel_group(self):
        from .cpp_wrapper_cpu import CppWrapperCpu

        self.kernel_group: Union[CppWrapperKernelGroup, KernelGroup]
        if isinstance(V.graph.wrapper_code, CppWrapperCpu):
            self.kernel_group = CppWrapperKernelGroup()
        else:
            self.kernel_group = KernelGroup()

    def fuse(self, node1, node2):
        if node1.is_foreach() or node2.is_foreach():
            return ForeachKernelSchedulerNode.fuse(node1, node2)
        else:
            if (
                self._why_fuse_nodes(node1, node2)
                == ReasonFusedNodes.COMPATIBLE_RANGES_NO_REDUCTION
            ):
                assert isinstance(node1, (SchedulerNode, FusedSchedulerNode))
                assert isinstance(node2, (SchedulerNode, FusedSchedulerNode))

                _, (vars1, reduce1) = node1.group
                _, (vars2, reduce2) = node2.group
                assert reduce1 == () and reduce2 == (), (reduce1, reduce2)

                def get_indexing_ranges_exprs(node):
                    if isinstance(node, FusedSchedulerNode):
                        assert len(node.snodes) > 0
                        return get_indexing_ranges_exprs(node.snodes[0])
                    else:
                        assert isinstance(node, SchedulerNode)
                        comp_buffer = node.node
                        assert isinstance(comp_buffer, ir.ComputedBuffer)
                        _, body, _ = comp_buffer.get_default_sizes_body()
                        return body.var_ranges, list(body.indexing_exprs.values())

                node_to_recomp = node1 if len(vars1) < len(vars2) else node2
                assert isinstance(node_to_recomp, SchedulerNode)

                ref_node = node2 if len(vars1) < len(vars2) else node1

                extra_indexing_constraints = get_indexing_ranges_exprs(ref_node)

                node_to_recomp.recompute_size_and_body(
                    extra_indexing_constraints=extra_indexing_constraints
                )

                _, (vars1, _) = node1.group
                _, (vars2, _) = node2.group
                assert vars1 == vars2, (vars1, vars2)

            return FusedSchedulerNode.fuse(node1, node2)

    def _why_fuse_nodes(self, node1, node2) -> Optional[ReasonFusedNodes]:
        _, (vars1, reduce1) = node1.group
        _, (vars2, reduce2) = node2.group

        if vars1 == vars2 and reduce1 == reduce2:
            return ReasonFusedNodes.SAME_VARS_REDUCE
        if reduce1 == () and vars1 == vars2 + reduce2:
            return ReasonFusedNodes.COMPATIBLE_REDUCTION
        if self._can_fuse_nodes_with_compatible_ranges(node1, node2):
            return ReasonFusedNodes.COMPATIBLE_RANGES_NO_REDUCTION
        # TODO(jansel): allow fusion pointwise (vars1, ()) suffix?
        return None

    def _can_fuse_nodes_with_compatible_ranges(self, node1, node2):
        # Here we try to fuse SchedulerNode/FusedSchedulerNode with compatible ranges
        # e.g. (s0, s1, s2) and (s0 * s1 * s2)
        _, (vars1, reduce1) = node1.group
        _, (vars2, reduce2) = node2.group

        c1 = reduce1 == () and reduce2 == ()
        c2 = math.prod(vars1) == math.prod(vars2)
        c3 = len(vars1) == 1 or len(vars2) == 1
        if not (c1 and c2 and c3):
            return False

        node_to_recomp = node1 if len(vars1) < len(vars2) else node2
        ref_node = node2 if len(vars1) < len(vars2) else node1

        # We can not recompute sizes and body for nodes other than SchedulerNode
        # TODO: we can extend fusion support with compatible ranges for FusedSchedulerNode
        if isinstance(node_to_recomp, FusedSchedulerNode):
            return False

        def get_buffer(node):
            if isinstance(node, FusedSchedulerNode):
                assert len(node.snodes) > 0
                # use the last scheduler node from the list as it has the most
                # relevant indexing expressions
                return get_buffer(node.snodes[-1])
            else:
                assert isinstance(node, SchedulerNode)
                return node.node

        ref_node_buffer = get_buffer(ref_node)
        if isinstance(ref_node_buffer, ir.TemplateBuffer):
            return False

        assert isinstance(ref_node_buffer, ir.ComputedBuffer)

        # It may happen that node1 and node2 compatible number of elements
        # but different original ranges, for example:
        # {d0: s0, d1: s1, d2: s2} vs {d0: s0*s1*s2}
        # See https://github.com/pytorch/pytorch/pull/120077/files#r1500427848 for more details
        # TODO: we can fix if it allows us to CSE at least one of the variables
        var_ranges1 = ref_node_buffer.get_read_writes().var_ranges
        var_ranges2 = node_to_recomp.node.get_read_writes().var_ranges
        if var_ranges1 != var_ranges2:
            return False

        return True

    def _can_fuse_horizontal_impl(self, node1, node2):
        assert isinstance(node1, (FusedSchedulerNode, SchedulerNode))
        assert isinstance(node2, (FusedSchedulerNode, SchedulerNode))
        return self._why_fuse_nodes(node1, node2) is not None

    def can_fuse_horizontal(self, node1, node2):
        if (
            len(node1.get_nodes()) + len(node2.get_nodes())
            > config.cpp.max_horizontal_fusion_size
        ):
            return False

        return self._can_fuse_horizontal_impl(node1, node2)

    def can_fuse_vertical(self, node1, node2):
        return self._can_fuse_horizontal_impl(node1, node2) and not node1.is_reduction()

    def codegen_nodes(self, nodes: List[SchedulerNode]):
        """
        Turn an set of pre-fused nodes into a C++ kernel.
        """
        kernel_group = self.kernel_group

        cpp_kernel_proxy = CppKernelProxy(kernel_group)
        cpp_kernel_proxy.codegen_nodes(nodes)

        kernel_group.finalize_kernel(cpp_kernel_proxy, nodes)

        args_num = self._get_scheduled_num_args()
        if args_num > CppScheduling.MAX_FUSED_KERNEL_ARGS_NUM:
            self._set_flush_status(True)

    def _get_scheduled_num_args(self):
        return self.kernel_group.get_num_args()

    def ready_to_flush(self):
        return self._ready_to_flush

    def codegen_sync(self):
        pass

    def flush(self):
        self.kernel_group.codegen_define_and_call(V.graph.wrapper_code)
        self.get_kernel_group()
        self._set_flush_status(False)


class KernelGroup:
    def __init__(self):
        super().__init__()
        self.args = KernelArgs()
        self.loops_code = BracesBuffer()
        self.ws = WorkSharing(self.loops_code)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(self.ws)
        self.scheduled_nodes = []

    def new_kernel(self, cls, *args):
        return cls(self.args, parallel_num_threads(), *args)

    def finalize_kernel(self, new_kernel, nodes):
        self.scheduled_nodes += nodes
        code = self.loops_code
        ws = self.ws
        new_kernel.codegen_loops(code, ws)

    def get_num_args(self):
        arg_defs, call_args, arg_types = self.args.cpp_argdefs()
        args_num = len(arg_defs)
        return args_num

    def codegen_define_and_call(self, wrapper):
        self.stack.close()
        if not self.scheduled_nodes:
            return

        fused_name = (
            get_fused_kernel_name(self.scheduled_nodes, config.cpp.descriptive_names)
            if config.cpp.descriptive_names
            else ""
        )
        kernel_name = "_".join(["cpp", fused_name, wrapper.next_kernel_suffix()])
        arg_defs, call_args, arg_types = self.args.cpp_argdefs()
        arg_defs = ",\n".ljust(25).join(arg_defs)
        code = BracesBuffer()
        # TODO: support kernel profile on other platforms
        enable_kernel_profile = (
            config.cpp.enable_kernel_profile and sys.platform == "linux"
        )
        if enable_kernel_profile:
            code.writelines(["#include <ATen/record_function.h>"])
        kernel_decl_name = kernel_name if V.graph.cpp_wrapper else "kernel"
        code.writeline(codecache.cpp_prefix())

        code.writeline(f'extern "C" void {kernel_decl_name}({arg_defs})')
        with code.indent():
            if enable_kernel_profile:
                graph_id = V.graph.graph_id
                prefix = "graph_" + str(graph_id) + "_" if graph_id is not None else ""
                code.writelines(
                    [
                        f'RECORD_FUNCTION("{prefix + kernel_name}", c10::ArrayRef<c10::IValue>({{}}));'
                    ]
                )
            for old, new in self.args.aliases():
                code.writeline(f"auto {old} = {new};")
            code.splice(self.loops_code)

        codecache_def = IndentedBuffer()
        if not V.graph.cpp_wrapper:
            codecache_def.writeline(f"async_compile.cpp_pybinding({arg_types!r}, '''")
        codecache_def.splice(code)
        if not V.graph.cpp_wrapper:
            codecache_def.writeline("''')")

        codecache_str = codecache_def.getvalue()
        # TODO(voz): Ostensibly, we should not need this. But there are cases where C++ codegen does
        # not use BracesBuffer, so we have no good indicator of a C++ buffer atm.
        codecache_str = codecache_str.replace("#pragma CMT", "//")
        wrapper.define_kernel(kernel_name, codecache_str, cuda=False)
        # generate the code to call this
        wrapper.generate_kernel_call(
            kernel_name, call_args, cuda=False, arg_types=arg_types
        )


class CppWrapperKernelGroup(KernelGroup):
    def __init__(self):
        super().__init__()
        self.args = CppWrapperKernelArgs()


class WorkSharing:
    def __init__(self, code):
        self.code = code
        self.in_parallel = False
        self.num_threads = None
        self.stack = contextlib.ExitStack()

    def parallel(self, threads):
        if self.in_parallel and threads != self.num_threads:
            # wrong number of threads
            self.close()
        if not self.in_parallel:
            self.num_threads = threads
            self.in_parallel = True
            if config.cpp.dynamic_threads:
                self.code.writeline("#pragma omp parallel")
            else:
                self.code.writeline(f"#pragma omp parallel num_threads({threads})")
            self.stack.enter_context(self.code.indent())

    def single(self):
        if self.in_parallel:
            self.code.writeline("#pragma omp single")
        return self.in_parallel

    def close(self):
        self.stack.close()
        self.in_parallel = False

    def __enter__(self):
        self.stack.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stack.__exit__(exc_type, exc_val, exc_tb)


@dataclasses.dataclass
class LoopLevel:
    var: Optional[sympy.Expr] = None
    size: Optional[sympy.Expr] = None
    offset: sympy.Expr = sympy.Integer(0)
    steps: sympy.Expr = sympy.Integer(1)
    parallel: int = 0
    simd_omp: bool = False
    simd_vec: bool = False
    collapsed: bool = False
    reduction_var_map: Optional[Dict[str, str]] = None
    parent: Optional["LoopLevel"] = None
    # the next inner level of the loop, empty if it is inner-most
    # contains >1 LoopLevel if the inner level of loop is split
    inner: List["LoopLevel"] = dataclasses.field(default_factory=list)
    # kernel assigned to this loop level, only valid when it is a leaf
    kernel: Optional[CppKernel] = None

    def __post_init__(self):
        # Regarding the C++/OpenMP backend, `codecache.pick_vec_isa()` to check
        # vectorization ISA is a time-consuming and one-shot operation. It leads
        # to taking a longer time to import `codegen.cpp` package because the
        # `LoopLevel` of the package is decorated by `@dataclasses.dataclass` while
        # the decorator will invoke `codecache.pick_vec_isa()` to initialize the
        # `simd_nelements` of the `LoopLevel`. It might introduce additional compilation
        # overhead to the Triton backend. Therefore, we moved the `simd_nelements` to
        # `__post_init__`
        picked_vec_isa: codecache.VecISA = codecache.pick_vec_isa()
        self.simd_nelements: int = picked_vec_isa.nelements() if picked_vec_isa else 0

    def get_kernels(self) -> List[CppKernel]:
        """Get all kernel objects under this loop level"""
        if self.kernel:
            return [self.kernel]
        kernels = []
        for loop in self.inner:
            kernels += loop.get_kernels()
        return kernels

    def set_kernel(self, kernel: CppKernel):
        """
        Set the kernel under this loop level. No split is allowed under
        this loop level.
        """
        if not self.inner:
            self.kernel = kernel
            loop: Optional[LoopLevel] = self
            assert loop is not None
            if loop.is_reduction():
                loop.reduction_var_map = kernel.reduction_var_map.copy()
                loop = loop.parent
                while loop is not None and loop.is_reduction():
                    assert loop.reduction_var_map is not None
                    loop.reduction_var_map.update(kernel.reduction_var_map)
                    loop = loop.parent
            return
        assert len(self.inner) == 1
        self.inner[0].set_kernel(kernel)

    def get_loops_at(self, depth) -> List["LoopLevel"]:
        if depth == 0:
            return [self]
        else:
            loops = []
            for loop in self.inner:
                loops += loop.get_loops_at(depth - 1)
            return loops

    def is_reduction(self):
        return bool(self.reduction_var_map)

    def split_with_tiling(self, depth, factor):
        def clone_inner():
            inner = []
            if self.inner:
                for loop in self.inner:
                    inner.append(loop.clone())
            return inner

        def do_split_with_tiling():
            sympy_factor = sympy.Integer(factor)

            offset = FloorDiv(self.size, sympy_factor) * sympy_factor
            main_loop = LoopLevel(self.var, offset)
            main_loop.steps = sympy_factor
            main_loop.parallel = self.parallel
            main_loop.collapsed = False
            main_loop.reduction_var_map = self.reduction_var_map
            main_loop.inner = clone_inner()
            if main_loop.inner:
                for loop in main_loop.inner:
                    loop.parent = main_loop

            tail_loop = LoopLevel(self.var, self.size)
            tail_loop.offset = offset
            tail_loop.parallel = self.parallel
            tail_loop.collapsed = False
            tail_loop.reduction_var_map = self.reduction_var_map
            tail_loop.inner = clone_inner()
            if tail_loop.inner:
                for loop in tail_loop.inner:
                    loop.parent = tail_loop

            return main_loop, tail_loop

        if depth == 0:
            main_loop, tail_loop = do_split_with_tiling()
            parent = self.parent
            if parent:
                parent.inner = [main_loop, tail_loop]
                main_loop.parent = parent
                tail_loop.parent = parent
            return main_loop, tail_loop
        else:
            assert len(self.inner) == 1
            return self.inner[0].split_with_tiling(depth - 1, factor)

    def clone(self):
        loop = copy(self)
        loop.inner = []
        if self.inner:
            for inner_loop in self.inner:
                inner_loop_clone = inner_loop.clone()
                inner_loop_clone.parent = loop
                loop.inner.append(inner_loop_clone)
        loop.kernel = deepcopy(self.kernel)
        return loop

    def lines(self):
        offset_expr = cexpr_index(self.offset)
        size_expr = cexpr_index(self.size)
        if config.cpp.no_redundant_loops and offset_expr == size_expr:
            return None
        if self.reduction_var_map:
            reduction = " " + " ".join(
                f"reduction({RTYPE_TO_CPP[rtype]}:{var})"
                for var, rtype in self.reduction_var_map.items()
            )
        else:
            reduction = ""
        simd = (
            f"simd simdlen({self.simd_nelements}) "
            if self.simd_omp and self.simd_nelements > 1
            else ""
        )
        if self.parallel:
            # TODO(jansel): look into chunk size and other schedules
            line1 = f"#pragma omp for{reduction} "
            if self.parallel > 1:
                line1 += f" collapse({self.parallel})"
            if self.simd_omp:
                line1 = line1.replace(" for ", f" for {simd}")
        elif self.simd_vec:
            line1 = ""
        elif self.simd_omp:
            line1 = f"#pragma omp {simd}{reduction}"
        elif not self.reduction_var_map and codecache.is_gcc():
            line1 = "#pragma GCC ivdep"
        else:
            line1 = ""
        offset_str = f"{INDEX_TYPE} {self.var}={offset_expr}"
        size_str = f"{self.var}<{size_expr}"
        steps_str = f"{self.var}+={cexpr_index(self.steps)}"
        line2 = f"for({offset_str}; {size_str}; {steps_str})"
        if self.collapsed or not line1:
            return [line2]
        return [line1, line2]


@dataclasses.dataclass
class LoopNestWithSplit:
    """
    A loop-nest like structure but with some loop level split along
    the loop range into the main tiling loop and the tail. It is built
    with the `build` method as a loop nest and then split with
    `split_with_tiling` at some depth.

    A typical case is for vectorization where we typically split at the inner-most
    loop level. A more complicated case is 2D tiling where we split at
    both inner-most and outer levels.
    """

    root: Optional[List[LoopLevel]] = None
    kernel: Optional[CppKernel] = None

    @staticmethod
    def build(kernel: CppKernel):
        """Build a LoopNest with the given `kernel` as the leaf"""
        itervars = kernel.itervars
        ranges = kernel.ranges
        reduction_depth = kernel.reduction_depth
        assert reduction_depth is not None

        root: List[LoopLevel] = []
        levels: List[LoopLevel] = root
        loop: Optional[LoopLevel] = None
        for loop_idx, (var, size) in enumerate(zip(itervars, ranges)):
            loop = LoopLevel(var, size, parent=loop)
            if loop_idx >= reduction_depth:
                loop.reduction_var_map = kernel.reduction_var_map.copy()
            levels.append(loop)
            levels = loop.inner
        loop_nest = LoopNestWithSplit(root)
        if loop:
            loop.kernel = kernel
        else:
            loop_nest.kernel = kernel
        return loop_nest

    def __bool__(self):
        return bool(self.root)

    def get_loops_at(self, depth) -> List[LoopLevel]:
        """Get all the loop levels at the given `depth` (most outer loop has depth 0)"""
        loops: List[LoopLevel] = []
        assert self.root is not None
        for loop in self.root:
            loops += loop.get_loops_at(depth)
        return loops

    @cache_on_self
    def max_parallel_depth(self):
        """
        Maximal allowed depth for parallelism:
        1) Levels without splitting and
        2) All reduction or non-reduction levels
        When the loop is split at the top level, the max depth is 1.
        """
        max_depth = 0
        assert self.root is not None
        loops = self.root
        if len(loops) > 1:
            return 1
        is_reduction = loops[0].is_reduction() if loops else False
        while len(loops) == 1 and loops[0].is_reduction() == is_reduction:
            max_depth += 1
            loops = loops[0].inner
        return max_depth

    def is_reduction_only(self):
        """
        Whether all the loops are for reduction. Reduction loops
        are always the inner most ones.
        """
        return (
            self.root is not None and len(self.root) > 0 and self.root[0].is_reduction()
        )

    def mark_parallel(self, par_depth):
        assert (
            par_depth <= self.max_parallel_depth()
        ), "Parallel depth cannot exceed the maximal allowed parallel depth"
        assert self.root is not None
        loops = self.root
        for loop in loops:
            loop.parallel = par_depth
        for i in range(1, par_depth):
            loops = loops[0].inner
            loops[0].collapsed = True

    def split_with_tiling(self, depth, factor):
        """
        Split the loop into main and tail loops at given `depth` so that the range
        of the main loop has range `floor_div(range, factor) * factor` and
        the tail loop handles the remainder. The main loop is tiled
        according to the `factor`.
        """
        loops = self.get_loops_at(depth)
        assert len(loops) == 1
        split_loops = loops[0].split_with_tiling(0, factor)
        if depth == 0:
            self.root = split_loops
        return split_loops
