"""This file implements the IndexPropagation ops handler, which wraps an
underlying handler to add a limited form of constant propagation, as well as
propagation of sympy expressions downstream of ops.index_expr calls.

For example, say we have the IR:

   tmp0 = ops.index_expr(x, torch.int32)
   tmp1 = ops.constant(2, torch.int32)
   tmp2 = ops.mul(tmp0, tmp1)
   tmp3 = ops.indirect_indexing(tmp2, x_size)
   tmp4 = ops.load("buf0", tmp3)

The underlying handler would just see:

   ops.load("buf0", x * 2)

This is limited by the set of operators handled in the sympy expression
printers. So simple operations like minimum and maximum cannot be translated to
SymPy expressions yet, despite sympy.Min and sympy.Max existing.

"""
import itertools
from dataclasses import dataclass
from typing import Any, Callable, Dict, Literal, Optional, overload, Tuple, Union

import sympy

from typing_extensions import TypeAlias

import torch
from torch._prims_common import is_boolean_dtype, is_integer_dtype
from torch.utils._sympy.functions import FloorDiv, ModularIndexing, Where


@dataclass
class TypedExpr:
    """A SymPy expression with associated type"""

    expr: sympy.Expr
    dtype: torch.dtype


class SymPyOps:
    """An ops handler where all IR values are SymPy expressions

    When a value cannot be represented as a SymPy expression, the method is
    either not defined, or returns NotImplemented

    """

    @staticmethod
    def identity(value: Any) -> Any:
        return value

    @staticmethod
    def constant(value: Union[int, float, bool], dtype: torch.dtype) -> TypedExpr:
        if is_boolean_dtype(dtype):
            expr = sympy.Integer(bool(value))
        elif is_integer_dtype(dtype):
            expr = sympy.Integer(int(value))
        else:
            expr = sympy.Float(float(value))
        return TypedExpr(expr, dtype)

    @staticmethod
    def index_expr(value: sympy.Expr, dtype: torch.dtype) -> Union[int, TypedExpr]:
        if isinstance(value, int):
            value = sympy.Integer(value)
        return TypedExpr(value, dtype)

    @staticmethod
    def to_dtype(
        value: Any, dtype: torch.dtype, src_dtype: Optional[torch.dtype] = None
    ) -> Union[int, TypedExpr]:
        if isinstance(value.expr, (sympy.Integer, sympy.Float)):
            return SymPyOps.constant(value.expr, dtype)
        elif is_integer_dtype(dtype) and is_integer_dtype(value.dtype):
            return SymPyOps.index_expr(value.expr, dtype)
        else:
            # TODO: Inductor doesn't handle floating point in sympy expressions well at the moment
            return NotImplemented

    @staticmethod
    def square(x: TypedExpr) -> TypedExpr:
        return TypedExpr(x.expr * x.expr, x.dtype)

    @staticmethod
    def add(x: TypedExpr, y: TypedExpr) -> TypedExpr:
        result_type = torch.promote_types(x.dtype, y.dtype)
        return TypedExpr(x.expr + y.expr, result_type)

    @staticmethod
    def sub(x: TypedExpr, y: TypedExpr) -> TypedExpr:
        result_type = torch.promote_types(x.dtype, y.dtype)
        return TypedExpr(x.expr - y.expr, result_type)

    @staticmethod
    def mul(x: TypedExpr, y: TypedExpr) -> TypedExpr:
        result_type = torch.promote_types(x.dtype, y.dtype)
        return TypedExpr(x.expr * y.expr, result_type)

    @staticmethod
    def neg(x: TypedExpr) -> TypedExpr:
        return TypedExpr(-x.expr, x.dtype)

    @staticmethod
    def floordiv(x: TypedExpr, y: TypedExpr) -> TypedExpr:
        result_type = torch.promote_types(x.dtype, y.dtype)
        if not is_integer_dtype(result_type):
            return NotImplemented

        return TypedExpr(FloorDiv(x.expr, y.expr), result_type)

    @staticmethod
    def mod(x: TypedExpr, y: TypedExpr) -> Optional[TypedExpr]:
        result_type = torch.promote_types(x.dtype, y.dtype)
        if not is_integer_dtype(result_type):
            return NotImplemented

        result_expr = ModularIndexing(x.expr, sympy.Integer(1), y.expr)
        return TypedExpr(result_expr, result_type)

    @staticmethod
    def remainder(x: TypedExpr, y: TypedExpr) -> Optional[TypedExpr]:
        result_type = torch.promote_types(x.dtype, y.dtype)
        if not is_integer_dtype(result_type):
            return NotImplemented
        # In these cases, remainder in Python == remainder in C++, so this transformation
        # is sound
        if (
            x.expr.is_nonnegative is not None
            and x.expr.is_nonnegative == y.expr.is_positive
        ):
            result_expr = ModularIndexing(x.expr, sympy.Integer(1), y.expr)
            return TypedExpr(result_expr, result_type)
        return NotImplemented

    @staticmethod
    def minimum(x: TypedExpr, y: TypedExpr) -> TypedExpr:
        result_type = torch.promote_types(x.dtype, y.dtype)
        return TypedExpr(sympy.Min(x.expr, y.expr), result_type)

    @staticmethod
    def maximum(x: TypedExpr, y: TypedExpr) -> TypedExpr:
        result_type = torch.promote_types(x.dtype, y.dtype)
        return TypedExpr(sympy.Max(x.expr, y.expr), result_type)


@dataclass
class IndexPropVar:
    value: Any  # Either an IR value, or TypedExpr if is_symbolic is true
    is_symbolic: bool = False

    @staticmethod
    def new_symbolic(expr: TypedExpr) -> "IndexPropVar":
        return IndexPropVar(expr, is_symbolic=True)

    def __post_init__(self):
        assert not self.is_symbolic or isinstance(
            self.value, TypedExpr
        ), "Symbolic IndexPropVar must contain a TypedExpr"


IndexPropResult: TypeAlias = Union[IndexPropVar, Tuple["IndexPropResult", ...]]


class IndexPropagation:
    """Ops wrapper that tries to propagate constant and index_expr values through the computation.

    This aims to maximize the compile time simplification possible, and convert
    indirect indexing from arange into normal static indexing.

    """

    def __init__(self, inner: Any):
        self._inner = inner

    def materialize_expr(self, expr: sympy.Expr, dtype: torch.dtype) -> Any:
        # Construct a new constant/index_expr from the SymPy expression
        if isinstance(expr, sympy.Integer):
            return self._inner.constant(int(expr), dtype)
        elif expr.is_number:
            return self._inner.constant(float(expr), dtype)
        return self._inner.index_expr(expr, dtype)

    def unwrap(self, a: Union[Any, IndexPropVar]) -> Any:
        if isinstance(a, (list, tuple)):
            return tuple(self.unwrap(v) for v in a)

        if not isinstance(a, IndexPropVar):
            return a

        # Prefer the sympy representation if possible
        if a.is_symbolic:
            return self.materialize_expr(a.value.expr, a.value.dtype)

        return a.value

    def wrap(self, a) -> IndexPropResult:
        if isinstance(a, (list, tuple)):
            return tuple(self.wrap(v) for v in a)
        return IndexPropVar(a)

    @overload
    def fallback(
        self,
        name: Literal["indirect_indexing"],
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
    ) -> IndexPropVar:
        ...

    @overload
    def fallback(
        self, name: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]
    ) -> IndexPropResult:
        ...

    def fallback(
        self, name: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]
    ) -> IndexPropResult:
        # Fallback to the wrapped handler
        new_args = [self.unwrap(a) for a in args]
        new_kwargs = {k: self.unwrap(v) for k, v in kwargs.items()}
        return self.wrap(getattr(self._inner, name)(*new_args, **new_kwargs))

    def propagate_sympy(
        self, name: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]
    ) -> IndexPropResult:
        # Build a new SymPy expression from this ops call
        def unwrap(a: Union[Any, IndexPropVar]) -> Any:
            if not isinstance(a, IndexPropVar):
                return a
            return a.value

        new_args = [unwrap(a) for a in args]
        new_kwargs = {k: unwrap(v) for k, v in kwargs.items()}
        new_expr = getattr(SymPyOps, name)(*new_args, **new_kwargs)
        is_valid_expr = new_expr is not NotImplemented and (
            # Inductor doesn't expect floating point in sympy expressions, but
            # allow floating point constants to be propagated
            isinstance(new_expr.expr, sympy.Number)
            or new_expr.expr.is_integer
        )
        if not is_valid_expr:
            return self.fallback(name, args, kwargs)
        return IndexPropVar.new_symbolic(new_expr)

    def __getattr__(self, name: str) -> Callable[..., IndexPropResult]:
        def inner(*args: Any, **kwargs: Any) -> IndexPropResult:
            if not hasattr(SymPyOps, name):
                return self.fallback(name, args, kwargs)

            var_arguments = [
                a
                for a in itertools.chain(args, kwargs.values())
                if isinstance(a, IndexPropVar)
            ]
            if not all(v.is_symbolic for v in var_arguments):
                return self.fallback(name, args, kwargs)

            return self.propagate_sympy(name, args, kwargs)

        return inner

    def indirect_indexing(
        self, index: Union[Any, IndexPropVar], size: Any, check: bool = True
    ) -> Any:
        # nb. We do index + Where(...) rather than Where(idx >= 0, idx, idx + sz) because we don't have CSE
        #     for SymPy expressions, so we don't want to repeat idx too much

        # indirect_indexing returns a sympy value, so no need to wrap in IndexPropVar here
        if isinstance(index, IndexPropVar) and index.is_symbolic:
            # If we are turning a indirect indexing into direct, we need to wrap it.
            index = index.value.expr
            return index + Where(index >= 0, 0, size)
        return self.fallback("indirect_indexing", (index, size, check), {}).value
