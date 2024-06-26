import collections
import dataclasses
import re
import sys
import types
from typing import Counter, Dict, List, Optional

import torch.nn
from . import utils

from .bytecode_transformation import (
    create_call_function,
    create_dup_top,
    create_instruction,
    create_load_global,
    create_rot_n,
    Instruction,
)
from .exc import unimplemented
from .source import AttrSource, Source
from .utils import is_safe_constant, rot_n_helper
from .variables.base import VariableTracker
from .variables.nn_module import NNModuleVariable
from .variables.tensor import (
    NumpyNdarrayVariable,
    SymNodeVariable,
    TensorVariable,
    UnspecializedPythonVariable,
)
from .variables.torch_function import TensorWithTFOverrideVariable


@dataclasses.dataclass
class GraphOutputEntry:
    index: int
    variable: VariableTracker


class PyCodegen:
    """
    Helper class uses for constructing Python bytecode
    """

    def __init__(
        self,
        tx=None,
        root: Optional[torch.nn.Module] = None,
        graph_output_var: Optional[str] = None,
        tempvars=None,
    ):
        self.root = root
        self.top_of_stack: Optional[VariableTracker] = None
        self.uses: Counter[VariableTracker] = collections.Counter()
        self.graph_outputs: Dict[int, GraphOutputEntry] = {}
        self._output: List[Instruction] = []
        self.tempvars = tempvars or {}
        self.tx = tx
        self.graph_output_var = graph_output_var
        self.code_options = self.tx.output.code_options
        self.cell_and_freevars = self.tx.cell_and_freevars
        self.new_var = self.tx.output.new_var
        self.mutable_side_effects_from_source = False
        self.value_from_source: bool = True

    def restore_stack(self, stack_values, *, value_from_source=True):
        prior = self.mutable_side_effects_from_source
        self.mutable_side_effects_from_source = True
        prev = self.value_from_source
        self.value_from_source &= value_from_source
        try:
            self.foreach(stack_values)
        finally:
            self.mutable_side_effects_from_source = prior
            self.value_from_source = prev

    def graph_output_vars(self):
        return [x.variable for x in self.graph_outputs.values()]

    def call_reconstruct(self, value):
        res = value.reconstruct(self)
        assert res is None, f"reconstruct!=None {value}"

    def __call__(self, value, allow_cache=True):
        """Generate code such that top-of-stack (TOS) is set to value"""
        if isinstance(value, Source):
            self.call_reconstruct(value)
            self.clear_tos()
            return

        assert isinstance(value, VariableTracker)
        output = self._output
        graph_outputs = self.graph_outputs

        if self.top_of_stack is value and allow_cache:
            output.append(create_dup_top())
            return

        if self.mutable_side_effects_from_source:
            # this is needed to get aliasing relationships right
            # value.mutable_local.source will get mutated to hold `value`
            # mutable_side_effects_from_source=False is used to codegen the mutation
            # mutable_side_effects_from_source=True is used to codegen a reference
            from .side_effects import MutableSideEffects

            if isinstance(value.mutable_local, MutableSideEffects):
                self(value.mutable_local.source)
                return

        if allow_cache:
            if value.mutable_local and value.mutable_local in self.tempvars:
                output.append(self.create_load(self.tempvars[value.mutable_local]))
                self.top_of_stack = value
                return
            if self.tempvars.get(value) is not None:
                output.append(self.create_load(self.tempvars[value]))
                self.top_of_stack = value
                return

        if value.source is not None and allow_cache and self.value_from_source:
            self.call_reconstruct(value.source)
        elif value.is_python_constant() and is_safe_constant(
            value.as_python_constant()
        ):
            output.append(self.create_load_const(value.as_python_constant()))
        elif isinstance(value, TensorWithTFOverrideVariable):
            graph_outputs_key = self.add_graph_output(value)

            self.load_import_from(utils.__name__, "to_subclass")
            self.load_graph_output(graph_outputs[graph_outputs_key].index)
            output.append(
                self.create_load_global(
                    value.global_mangled_class_name(self.tx), False, add=True
                )
            )
            output.extend(create_call_function(2, True))
        elif isinstance(
            value,
            (
                TensorVariable,
                SymNodeVariable,
                UnspecializedPythonVariable,
                NumpyNdarrayVariable,
            ),
        ):
            graph_outputs_key = self.add_graph_output(value)

            if isinstance(value, NumpyNdarrayVariable):
                self.load_import_from(utils.__name__, "to_numpy_helper")

            self.load_graph_output(graph_outputs[graph_outputs_key].index)

            if isinstance(value, NumpyNdarrayVariable):
                output.extend(create_call_function(1, True))
            elif isinstance(value, UnspecializedPythonVariable) and value.need_unwrap:
                output.extend(
                    [self.create_load_attr("item")] + create_call_function(0, True)
                )
        elif isinstance(value, NNModuleVariable):
            parts = value.module_key.split(".")
            if parts[0] in self.code_options["co_varnames"]:
                output.append(self.create_load(parts[0]))
                parts = parts[1:]
            else:
                assert self.root is not None
                output.append(self.create_load_output(self.root))
            for part in parts:
                output.append(self.create_load_attr(part))
        else:
            self.uses[value] += 1
            try:
                self.call_reconstruct(value)
            except NotImplementedError:
                unimplemented(f"reconstruct: {value}")
            if allow_cache and value in self.tempvars:
                self._output.append(create_dup_top())
                self.add_cache(value)

        self.top_of_stack = value

    def add_graph_output(self, value):
        graph_outputs_key = id(value.as_proxy())
        if graph_outputs_key not in self.graph_outputs:
            self.graph_outputs[graph_outputs_key] = GraphOutputEntry(
                len(self.graph_outputs), value
            )
        return graph_outputs_key

    def load_graph_output(self, index):
        output = self._output
        output.append(self.create_load(self.graph_output_var))
        output.append(self._create_load_const(index))
        output.append(create_instruction("BINARY_SUBSCR"))

    def add_cache(self, value):
        var = self.new_var()
        self.tempvars[value] = var
        if value.mutable_local:
            self.tempvars[value.mutable_local] = var
        self._output.append(self.create_store(var))

    def foreach(self, items):
        for i in items:
            self(i)

    def setup_globally_cached(self, name, value, push_null):
        """Store value in a new global"""
        name = re.sub(r"[^a-zA-Z0-9_]+", "_", name)
        f_globals = self.tx.f_globals
        if name in f_globals:
            assert id(f_globals[name]) == id(value)
        else:
            f_globals[name] = value
        return [self.create_load_global(name, push_null, add=True)]

    def clear_tos(self):
        self.top_of_stack = None

    def append_output(self, inst):
        assert isinstance(inst, Instruction)
        self._output.append(inst)
        self.clear_tos()

    def extend_output(self, insts):
        assert all(isinstance(x, Instruction) for x in insts)
        self._output.extend(insts)
        self.clear_tos()

    def get_instructions(self) -> List[Instruction]:
        return self._output

    def create_load(self, name) -> Instruction:
        if name in self.cell_and_freevars():
            return create_instruction("LOAD_DEREF", argval=name)
        assert name in self.code_options["co_varnames"], f"{name} missing"
        return create_instruction("LOAD_FAST", argval=name)

    def create_load_closure(self, name) -> Instruction:
        assert name in self.cell_and_freevars()
        return create_instruction("LOAD_CLOSURE", argval=name)

    def create_store(self, name) -> Instruction:
        if name in self.cell_and_freevars():
            return create_instruction("STORE_DEREF", argval=name)
        assert name in self.code_options["co_varnames"]
        return create_instruction("STORE_FAST", argval=name)

    def create_load_global(self, name, push_null, add=False) -> Instruction:
        if add:
            self.tx.output.update_co_names(name)
        assert name in self.code_options["co_names"], f"{name} not in co_names"
        return create_load_global(name, push_null)

    def create_load_const(self, value) -> Instruction:
        assert is_safe_constant(value), f"unsafe constant {value}"
        return self._create_load_const(value)

    def _create_load_const(self, value) -> Instruction:
        return create_instruction("LOAD_CONST", argval=value)

    create_load_output = _create_load_const

    def create_load_method(self, name):
        self.tx.output.update_co_names(name)
        return create_instruction("LOAD_METHOD", argval=name)

    def create_load_attr(self, name) -> Instruction:
        if name not in self.code_options["co_names"]:
            self.code_options["co_names"] += (name,)
        return create_instruction("LOAD_ATTR", argval=name)

    def load_attr(self, name):
        self.append_output(self.create_load_attr(name))

    def create_load_attrs(self, names):
        return [self.create_load_attr(name) for name in names.split(".")]

    def create_store_attr(self, name) -> Instruction:
        if name not in self.code_options["co_names"]:
            self.code_options["co_names"] += (name,)
        return create_instruction("STORE_ATTR", argval=name)

    def store_attr(self, name):
        self.append_output(self.create_store_attr(name))

    def load_function_name(self, fn_name, push_null, num_on_stack=0):
        """Load the global fn_name on the stack num_on_stack down"""
        output = []
        if push_null and sys.version_info >= (3, 11):
            output.extend(
                [create_instruction("PUSH_NULL"), *self.rot_n(num_on_stack + 1)]
            )
        output.extend(
            [
                self.create_load_global(fn_name, False, add=True),
                *self.rot_n(num_on_stack + 1),
            ]
        )
        return output

    def rot_n(self, n):
        try:
            return create_rot_n(n)
        except AttributeError:
            # desired rotate bytecode doesn't exist, generate equivalent bytecode
            return [
                create_instruction("BUILD_TUPLE", arg=n),
                self._create_load_const(rot_n_helper(n)),
                *create_rot_n(2),
                create_instruction("CALL_FUNCTION_EX", arg=0),
                create_instruction("UNPACK_SEQUENCE", arg=n),
            ]

    def pop_null(self):
        # POP_TOP doesn't work for null, so we pop nulls by pushing in a
        # nop function, calling it (which consumes the null), and popping the result.
        assert sys.version_info >= (3, 11)
        return [
            self._create_load_const(lambda: None),
            *create_call_function(0, False),
            create_instruction("POP_TOP"),
        ]

    def call_function(self, nargs: int, push_null: bool):
        self.extend_output(create_call_function(nargs, push_null=push_null))

    def dup_top(self):
        self.append_output(create_dup_top())

    def store(self, varname):
        self.append_output(self.create_store(varname))

    def make_function_with_closure(
        self, fn_name: str, code: types.CodeType, push_null: bool, num_on_stack=0
    ):
        freevars = code.co_freevars
        assert freevars
        output = self._output
        if sys.version_info >= (3, 11) and push_null:
            output.append(create_instruction("PUSH_NULL"))
            output.extend(self.rot_n(num_on_stack + 1))
        for var in freevars:
            assert var in self.cell_and_freevars()
            output.append(create_instruction("LOAD_CLOSURE", argval=var))
        output.append(create_instruction("BUILD_TUPLE", arg=len(freevars)))
        output.append(self.create_load_const(code))
        if sys.version_info < (3, 11):
            output.append(self.create_load_const(fn_name))
        output.append(create_instruction("MAKE_FUNCTION", arg=0x08))
        output.extend(self.rot_n(num_on_stack + 1))
        self.clear_tos()

    def create_load_python_module(self, mod, push_null) -> Instruction:
        """
        Generate a LOAD_GLOBAL instruction to fetch a given python module.
        """
        output = self.tx.output
        global_scope = output.global_scope
        name = re.sub(r"^.*[.]", "", mod.__name__)
        if global_scope.get(name, None) is mod:
            return self.create_load_global(name, push_null, add=True)
        prefix = f"___module_{name}"
        global_name = self.tx.output.install_global_by_id(prefix, mod)
        return self.create_load_global(global_name, push_null, add=True)

    def make_call_generated_code(self, fn_name: str) -> None:
        """Call the generated code function stored in fn_name"""
        self.extend_output(self.load_function_name(fn_name, True))

        graphargs = self.tx.output.graphargs
        for arg in graphargs:
            if arg.is_unspecialized:
                self.extend_output(
                    [
                        self.create_load_python_module(torch, True),
                        self.create_load_attr("as_tensor"),
                    ]
                )
                self.call_reconstruct(arg)
                self.extend_output(create_call_function(1, False))
            else:
                self.call_reconstruct(arg)

        self.extend_output(create_call_function(len(graphargs), False))

    def load_import_from(self, module_name, object_name) -> None:
        self(AttrSource(self.tx.import_source(module_name), object_name))

    def create_call_function_kw(self, nargs, kw_names, push_null) -> List[Instruction]:
        if sys.version_info >= (3, 11):
            output = create_call_function(nargs, push_null)
            assert output[-2].opname == "PRECALL"
            kw_names_inst = create_instruction("KW_NAMES", argval=kw_names)
            output.insert(-2, kw_names_inst)
            return output
        return [
            self.create_load_const(kw_names),
            create_instruction("CALL_FUNCTION_KW", arg=nargs),
        ]
