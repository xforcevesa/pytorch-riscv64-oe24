# mypy: ignore-errors

import collections
import dataclasses
import functools
import inspect
import itertools
import sys
import types
from typing import Dict, List

import torch._C
import torch._numpy as tnp
import torch.utils._pytree as pytree
from .. import config, variables
from ..bytecode_transformation import create_call_function, create_instruction
from ..exc import unimplemented
from ..guards import GuardBuilder, install_guard
from ..source import AttrSource, GetItemSource, ODictGetItemSource, TypeSource
from ..utils import (
    check_constant_args,
    check_unspec_python_args,
    identity,
    is_tensor_base_attr_getter,
    proxy_args_kwargs,
)
from .base import VariableTracker
from .functions import NestedUserFunctionVariable, UserFunctionVariable
from .user_defined import UserDefinedObjectVariable


class SuperVariable(VariableTracker):
    def __init__(self, typevar, objvar=None, specialized=False, **kwargs):
        super().__init__(**kwargs)
        # typevar is the fist argument to super(). In the case where no argument
        # is provided to super(), it is the __class__ object where
        # the super() function is being called
        self.typevar = typevar
        # objvar here must be an instance or subtype of typevar.
        # In the case where super() is called without arguments, it is the first argument
        # to the current function where super() is called from (self for regular method,
        # cls for a classmethod)
        self.objvar = objvar
        self.specialized = specialized  # directly get attr from self.typevar if true

    def reconstruct(self, codegen):
        codegen(variables.BuiltinVariable(super))
        codegen(self.typevar)
        if self.objvar is not None:
            codegen(self.objvar)
            codegen.extend_output(create_call_function(2, True))
        else:
            codegen.extend_output(create_call_function(1, True))

    def _resolved_getattr_and_source(self, tx, name):
        assert self.objvar, "1-arg super not implemented"
        if self.specialized:
            return getattr(self.typevar.as_python_constant(), name)
        search_type = self.typevar.as_python_constant()

        # The rest of this function does two things:
        #   - Walk the mro to find where the attribute comes from to be
        #     able to provide accurate source
        #   - Call the getattr to get the object

        # Find the class object, where the function lives.
        # When objvar is "self", use type(self), when objvar is "cls", use it as-is
        type_to_use = self.objvar.python_type()
        type_to_use_source = (
            TypeSource(self.objvar.source) if self.objvar.source else None
        )
        if issubclass(type_to_use, type):
            type_to_use = self.objvar.value
            type_to_use_source = self.objvar.source

        source = None
        if self.objvar.source is not None:
            # Walk the mro tuple to find out the actual class where the
            # attribute resides.
            search_mro = type_to_use.__mro__
            start_index = search_mro.index(search_type) + 1
            for index in range(start_index, len(search_mro)):
                if hasattr(search_mro[index], name):
                    # Equivalent of something like type(L['self']).__mro__[1].attr_name
                    source = AttrSource(
                        GetItemSource(AttrSource(type_to_use_source, "__mro__"), index),
                        name,
                    )
                    break

        # TODO(jansel): there is a small chance this could trigger user code, prevent that
        return getattr(super(search_type, type_to_use), name), source

    def var_getattr(self, tx, name: str) -> "VariableTracker":
        # Check if getattr is a constant. If not, delay the actual work by
        # wrapping the result in GetAttrVariable. Mostly super is called with a
        # method, so most of the work is delayed to call_function.
        #
        # We could have just implemented a const_getattr. However, super is
        # special when it comes to finding sources. Compared to other VTs, super
        # requires the attr name to walk the mro and find the actual source (and
        # not just AttrSource).
        value, source = self._resolved_getattr_and_source(self, name)
        if not variables.ConstantVariable.is_literal(value):
            return GetAttrVariable(self, name)
        if source:
            install_guard(source.make_guard(GuardBuilder.CONSTANT_MATCH))
            return variables.ConstantVariable.create(value, source=source)
        return variables.ConstantVariable.create(value)

    def call_method(
        self,
        tx,
        name,
        args: "List[VariableTracker]",
        kwargs: "Dict[str, VariableTracker]",
    ) -> "VariableTracker":
        inner_fn, source = self._resolved_getattr_and_source(self, name)

        if inner_fn is object.__init__:
            return LambdaVariable(identity)
        elif inner_fn is torch.nn.Module.__init__:
            objvar = self.objvar
            from ..side_effects import AttributeMutationNew

            if (
                isinstance(objvar, variables.UserDefinedObjectVariable)
                and isinstance(objvar.mutable_local, AttributeMutationNew)
                and not (args or kwargs)
            ):
                tx.output.side_effects.store_attr(
                    objvar,
                    "__call_nn_module_init",
                    variables.ConstantVariable.create(True),
                )
                return variables.ConstantVariable.create(None)
            else:
                unimplemented("super() nn.Module.__init__")
        elif isinstance(inner_fn, types.FunctionType):
            return variables.UserFunctionVariable(
                inner_fn, source=source
            ).call_function(tx, [self.objvar] + args, kwargs)
        elif isinstance(inner_fn, types.MethodType):
            return variables.UserMethodVariable(
                inner_fn.__func__, self.objvar, source=source
            ).call_function(tx, args, kwargs)
        elif (
            inner_fn is collections.OrderedDict.__getitem__
            and isinstance(self.objvar, variables.UserDefinedObjectVariable)
            and self.objvar.source
            and len(args) == 1
            and len(kwargs) == 0
            and args[0].is_python_constant()
        ):
            from .builder import VariableBuilder

            key = args[0].as_python_constant()
            return VariableBuilder(tx, ODictGetItemSource(self.objvar.source, key))(
                collections.OrderedDict.__getitem__(self.objvar.value, key)
            )
        elif inner_fn in (
            collections.OrderedDict.__setitem__,
            object.__setattr__,
        ) and isinstance(self.objvar, variables.CustomizedDictVariable):
            assert not kwargs and len(args) == 2
            return super(variables.CustomizedDictVariable, self.objvar).call_method(
                tx, "__setitem__", args, kwargs
            )
        else:
            unimplemented(f"non-function or method super: {inner_fn}")


class UnknownVariable(VariableTracker):
    """
    It could be anything!
    """


class DelayGraphBreakVariable(UnknownVariable):
    """
    Used to insert a dummy variable in the stack to do the graph break at CALL_FUNCTION.
    """


class ComptimeVariable(VariableTracker):
    """
    This variable is special, it lets you execute arbitrary code at
    Dynamo compile time
    """

    def reconstruct(self, codegen):
        raise NotImplementedError("comptime is special form")

    def var_getattr(self, tx, name: str) -> "VariableTracker":
        from ..comptime import comptime

        # To support the comptime.print_graph convenience accessors
        from .functions import UserFunctionVariable

        return UserFunctionVariable(
            getattr(comptime, name), source=AttrSource(self.source, name)
        )

    def call_function(
        self, tx, args: "List[VariableTracker]", kwargs: "Dict[str, VariableTracker]"
    ) -> "VariableTracker":
        from ..comptime import ComptimeContext

        # TODO: support an expression form as well

        assert not kwargs
        assert len(args) == 1
        fn = args[0]
        if isinstance(fn, UserFunctionVariable):
            fn.get_function()(ComptimeContext(tx))
        elif isinstance(fn, NestedUserFunctionVariable):
            # We have to manually bind the freevars ourselves
            code = fn.get_code()
            assert not fn.closure, (
                "comptime function must not have free variables, "
                f"but these variables were free: {code.co_freevars}"
            )
            func = types.FunctionType(
                code,
                fn.f_globals,
                fn.fn_name.as_python_constant(),
                tuple(fn.defaults.items) if fn.defaults else None,
                # We could automatically promote free variables into
                # ComptimeVar but this is confusing if you access
                # a free variable that we actually DO have the runtime
                # value for
                # tuple(make_cell(ComptimeVar(i)) for i in fn.closure.items)
                tuple(),
            )
            func(ComptimeContext(tx))
        else:
            raise RuntimeError(f"unsupported argument to comptime: {type(fn)}")

        return variables.ConstantVariable.create(None)


class ClosureVariable(UnknownVariable):
    def __init__(self, name, **kwargs):
        super().__init__(**kwargs)
        self.name = name

    def reconstruct(self, codegen):
        codegen.append_output(codegen.create_load_closure(self.name))


# closure variable created by an inlined function
class InlinedClosureVariable(UnknownVariable):
    def __init__(self, name, **kwargs):
        super().__init__(**kwargs)
        self.name = name

    def reconstruct(self, codegen):
        codegen.append_output(codegen.create_load_closure(self.name))


class NewCellVariable(VariableTracker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class NewGlobalVariable(VariableTracker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class InspectSignatureVariable(VariableTracker):
    """represents inspect.signature(...)"""

    @staticmethod
    def create(callable, **kwargs):
        if kwargs:
            unimplemented(f"inspect.signature with {kwargs}")
        return InspectSignatureVariable(callable)

    def __init__(self, inspected: VariableTracker, **kwargs):
        super().__init__(**kwargs)
        self.inspected = inspected

    def var_getattr(self, tx, name: str) -> "VariableTracker":
        if name == "parameters":
            return variables.ConstDictVariable(
                {
                    variables.ConstantVariable.create(name): InspectParameterVariable()
                    for name in self.inspected.inspect_parameter_names()
                },
                user_cls=dict,
            )
        return super().var_getattr(tx, name)


class InspectParameterVariable(VariableTracker):
    """This is not implemented, if used will graph break."""

    pass


def produce_trampoline_autograd_apply(fn_cls):
    def trampoline_autograd_apply(*args, **kwargs):
        return fn_cls.apply(*args, **kwargs)

    trampoline_autograd_apply._origin = produce_trampoline_autograd_apply
    return trampoline_autograd_apply


class AutogradFunctionVariable(VariableTracker):
    """represents a torch.autograd.Function subclass"""

    def __init__(self, fn_cls, **kwargs):
        super().__init__(**kwargs)
        self.fn_cls = fn_cls

    def call_apply(self, tx, args, kwargs):
        requires_grad = False

        def visit(node):
            nonlocal requires_grad
            if isinstance(node, variables.TensorVariable):
                if node.requires_grad is not False:
                    requires_grad = True
            if isinstance(node, variables.NNModuleVariable):
                if node.is_training(tx):
                    requires_grad = True
            return node

        VariableTracker.apply(visit, (args, kwargs))

        if (
            requires_grad
            and torch.is_grad_enabled()
            and config.capture_autograd_function
        ):
            # Note - this is the same check used in autograd/function.py, except inverted.
            # If we want to support functorch transforms here, we will need to enable this.
            if (
                self.fn_cls.setup_context
                != torch.autograd.function._SingleLevelFunction.setup_context
            ):
                unimplemented(
                    "NYI - autograd.Function with custom setup_context method"
                )

            vjp_fn = self.fn_cls.vjp  # type: ignore[attr-defined]
            if vjp_fn is not torch.autograd.Function.vjp:
                unimplemented("NYI - User defind vjp")

            jvp_fn = self.fn_cls.jvp  # type: ignore[attr-defined]
            if jvp_fn is not torch.autograd.Function.jvp:
                unimplemented("NYI - User defind jvp")

            from .higher_order_ops import AutogradFunctionApplyVariable

            source = self.source
            if source is None:
                source = AttrSource(
                    tx.import_source(self.fn_cls.__module__), self.fn_cls.__name__
                )

            return AutogradFunctionApplyVariable(
                self.fn_cls.forward,
                self.fn_cls.backward,
                source,
                source=AttrSource(source, member="apply"),
            ).call_function(tx, args, kwargs)

        if self.source:
            source = AttrSource(self.source, "forward")
        else:
            source = None

        fn = self.fn_cls.forward
        ctx = AutogradFunctionContextVariable.create(tx)
        args = [ctx, *args]
        if isinstance(fn, types.FunctionType):
            return variables.UserFunctionVariable(fn, source=source).call_function(
                tx, args, kwargs
            )
        elif isinstance(fn, types.MethodType):
            return variables.UserMethodVariable(
                fn.__func__,
                variables.UserDefinedClassVariable(self.fn_cls),
                source=source,
            ).call_function(tx, args, kwargs)
        else:
            unimplemented(
                f"non-function or method in subclass of torch.autograd.Function: {fn}"
            )

    def call_function(self, tx, args, kwargs):
        return AutogradFunctionVariable(self.fn_cls)

    def call_method(
        self,
        tx,
        name,
        args: "List[VariableTracker]",
        kwargs: "Dict[str, VariableTracker]",
    ):
        from ..trace_rules import is_callable_allowed
        from .builder import wrap_fx_proxy

        if name == "apply":
            if is_callable_allowed(self.fn_cls):
                trampoline_autograd_apply = produce_trampoline_autograd_apply(
                    self.fn_cls
                )
                return wrap_fx_proxy(
                    tx=tx,
                    proxy=tx.output.create_proxy(
                        "call_function",
                        trampoline_autograd_apply,
                        *proxy_args_kwargs(args, kwargs),
                    ),
                )
            else:
                return self.call_apply(tx, args, kwargs)

        else:
            unimplemented(f"Unsupported method: {name}")


@dataclasses.dataclass
class SavedTensorBox:
    tensors: List[VariableTracker] = dataclasses.field(default_factory=list)


class AutogradFunctionContextVariable(UserDefinedObjectVariable):
    """
    Tracks an autograd.Function() context using mutation tracking in side_effects.py
    """

    _nonvar_fields = {
        "proxy",
        "inference",
        *UserDefinedObjectVariable._nonvar_fields,
    }

    def __init__(
        self,
        value,
        value_type=None,
        inference=False,
        proxy=None,
        saved_tensors=None,
        **kwargs,
    ):
        super().__init__(value=value, value_type=value_type, **kwargs)
        self.inference = inference
        self.proxy = proxy
        self.saved_tensors = saved_tensors

    @staticmethod
    def create(tx):
        proxy = tx.output.create_proxy(
            "call_function", torch.autograd.function.FunctionCtx, tuple(), {}
        )
        out = tx.output.side_effects.track_object_new(
            None,
            torch.autograd.function.FunctionCtx,
            functools.partial(
                AutogradFunctionContextVariable,
                inference=True,
                proxy=proxy,
                saved_tensors=SavedTensorBox(),
            ),
            {},
        )
        proxy.node.meta["example_value"] = out.value
        return out

    def as_proxy(self):
        if self.proxy is None:
            unimplemented("proxy not set")
        return self.proxy

    def call_method(
        self,
        tx,
        name,
        args: "List[VariableTracker]",
        kwargs: "Dict[str, VariableTracker]",
    ) -> "VariableTracker":
        if name != "save_for_backward":
            unimplemented(f"autograd.Function context method: {name}")
        if self.saved_tensors is None:
            unimplemented(
                "save_for_backward only supported on a newly constructed FunctionCtx"
            )

        if not self.inference:
            assert self.source and not kwargs
            tx.output.side_effects.track_save_for_backward(self, args)

        # In eager mode, multiple calls to .save_for_backward() will overwrite previous calls.
        if len(self.saved_tensors.tensors) > 0:
            self.saved_tensors.tensors = []
        for arg in args:
            self.saved_tensors.tensors.append(arg)
        return variables.ConstantVariable.create(None)

    def var_getattr(self, tx, name):
        if name == "save_for_backward":
            return LambdaVariable(
                lambda *args, **kwargs: self.call_method(tx, name, args, kwargs)
            )
        if name == "saved_tensors" and self.saved_tensors is not None:
            return variables.TupleVariable(list(self.saved_tensors.tensors))
        return super().var_getattr(tx, name)


class LambdaVariable(VariableTracker):
    def __init__(self, fn, **kwargs):
        super().__init__(**kwargs)
        self.fn = fn

    def call_function(
        self, tx, args: "List[VariableTracker]", kwargs: "Dict[str, VariableTracker]"
    ) -> "VariableTracker":
        return self.fn(*args, **kwargs)


class GetAttrVariable(VariableTracker):
    def __init__(self, obj, name, **kwargs):
        super().__init__(**kwargs)
        assert isinstance(obj, VariableTracker)
        assert isinstance(name, str)
        self.obj = obj
        self.name = name

    def __str__(self):
        return f"{self.__class__.__name__}({self.obj}, {self.name})"

    @staticmethod
    def create_getattr_proxy(base_proxy: torch.fx.Proxy, attr):
        return getattr(base_proxy, attr)

    def as_proxy(self):
        return GetAttrVariable.create_getattr_proxy(self.obj.as_proxy(), self.name)

    def const_getattr(self, tx, name):
        if not isinstance(self.obj, variables.NNModuleVariable):
            raise NotImplementedError()
        step1 = tx.output.get_submodule(self.obj.module_key)
        if self.name not in step1.__dict__:
            raise NotImplementedError()
        step2 = inspect.getattr_static(step1, self.name)
        if name not in step2.__dict__:
            raise NotImplementedError()
        return inspect.getattr_static(step2, name)

    def reconstruct(self, codegen):
        codegen(self.obj)
        codegen.extend_output(codegen.create_load_attrs(self.name))

    def call_function(
        self, tx, args: "List[VariableTracker]", kwargs: "Dict[str, VariableTracker]"
    ) -> "VariableTracker":
        return self.obj.call_method(tx, self.name, args, kwargs)


class MethodWrapperVariable(VariableTracker):
    def __init__(self, method_wrapper, **kwargs):
        super().__init__(**kwargs)
        self.method_wrapper = method_wrapper

    def call_function(
        self, tx, args: "List[VariableTracker]", kwargs: "Dict[str, VariableTracker]"
    ) -> "VariableTracker":
        if is_tensor_base_attr_getter(self.method_wrapper) and isinstance(
            args[0], variables.TensorVariable
        ):
            assert len(args) == 1 and len(kwargs) == 0

            return args[0].var_getattr(tx, self.method_wrapper.__self__.__name__)

        super().call_function(tx, args, kwargs)

    def is_python_constant(self):
        return True

    def as_python_constant(self):
        return self.method_wrapper


class GetSetDescriptorVariable(VariableTracker):
    def __init__(self, desc, **kwargs):
        super().__init__(**kwargs)
        self.desc = desc

    def var_getattr(self, tx, name):
        if name == "__get__" and self.source:
            from .builder import VariableBuilder

            return VariableBuilder(tx, AttrSource(self.source, "__get__"))(
                self.desc.__get__
            )
        else:
            return super().var_getattr(tx, name)

    def is_python_constant(self):
        return True

    def as_python_constant(self):
        return self.desc


class PythonModuleVariable(VariableTracker):
    def __init__(self, value: types.ModuleType, **kwargs):
        super().__init__(**kwargs)
        self.value = value
        self.is_torch = self.value is torch or self.value.__name__.startswith("torch.")

    def python_type(self):
        return types.ModuleType

    def as_python_constant(self):
        return self.value

    def __repr__(self):
        return f"PythonModuleVariable({self.value})"

    def call_hasattr(self, tx, name):
        if self.is_torch:
            result = hasattr(self.value, name)
            return variables.ConstantVariable.create(result)
        return super().call_hasattr(tx, name)


class TypingVariable(VariableTracker):
    def __init__(self, value, **kwargs):
        super().__init__(**kwargs)
        self.value = value

    def call_method(
        self,
        tx,
        name,
        args: "List[VariableTracker]",
        kwargs: "Dict[str, VariableTracker]",
    ) -> "VariableTracker":
        if name == "__getitem__" and len(args) == 1:
            return variables.ConstantVariable.create(
                self.value[args[0].as_python_constant()],
            )
        unimplemented("typing")

    def python_type(self):
        return type(self.value)

    def as_python_constant(self):
        return self.value


@functools.lru_cache(maxsize=1)
def get_np_to_tnp_map():
    from ..utils import NP_TO_TNP_MODULE

    np_fn_to_tnp_fn = {}

    for np_mod, tnp_mod in NP_TO_TNP_MODULE.items():
        for fn_name, tnp_fn in tnp_mod.__dict__.items():
            if callable(tnp_fn):
                # some internal details do leak from tnp
                # which are not part of numpy API.
                if np_fn := getattr(np_mod, fn_name, None):
                    np_fn_to_tnp_fn[np_fn] = tnp_fn

    return np_fn_to_tnp_fn


class NumpyVariable(VariableTracker):
    """
    Wrapper around `numpy.*`. Currently, is able to trace a small subset of numpy functions as well as numpy dtypes.
    """

    constant_fold_functions = (tnp.issubdtype,)

    def __init__(self, value, **kwargs):
        super().__init__(**kwargs)
        self.value = value

    @classmethod
    def can_constant_fold_through(cls, fn):
        mod = fn.__module__.split(".")
        assert len(mod) >= 2 and mod[:2] == ["torch", "_numpy"]
        return fn in cls.constant_fold_functions

    def call_function(
        self, tx, args: "List[VariableTracker]", kwargs: "Dict[str, VariableTracker]"
    ) -> "VariableTracker":
        if not config.trace_numpy:
            unimplemented(f"numpy.{self.value}()")

        from ..utils import numpy_to_tensor_wrapper

        from .tensor import NumpyNdarrayVariable

        # lookup method name in tnp. Things like np.dtype(float) are not supported yet.
        if self.value.__name__ == "dtype":
            unimplemented(
                f"numpy dtype function is not supported yet. Got type {type(self.value)}."
            )
        else:  # We are dealing with a callable.
            func = get_np_to_tnp_map().get(self.value)
            if func is None:
                unimplemented(
                    f"Can't find numpy function {self.value} in torch._numpy. "
                    " Please file an issue to request support for this function."
                )

            if (
                func.__module__ == "torch._numpy.random"
                and config.use_numpy_random_stream
            ):
                msg = f"delegate '{func.__qualname__}' to NumPy itself via "
                msg += f"confg.use_numpy_random_stream={config.use_numpy_random_stream}"
                unimplemented(msg)

            args, kwargs = NumpyNdarrayVariable.patch_args(func.__name__, args, kwargs)

            constant_args = check_constant_args(args, kwargs)
            unspec_python_args = check_unspec_python_args(args, kwargs)

            if self.can_constant_fold_through(func) and (
                constant_args or unspec_python_args
            ):
                # constant fold
                return variables.ConstantVariable.create(
                    self.as_python_constant()(
                        *[x.as_python_constant() for x in args],
                        **{k: v.as_python_constant() for k, v in kwargs.items()},
                    ),
                )

            # TODO Add all the functions that go from constants to constants to can_constant_fold_through
            proxy = tx.output.create_proxy(
                "call_function",
                numpy_to_tensor_wrapper(func),
                *proxy_args_kwargs(args, kwargs),
            )
            return NumpyNdarrayVariable.create(tx, proxy)

    def call_method(
        self,
        tx,
        name,
        args: "List[VariableTracker]",
        kwargs: "Dict[str, VariableTracker]",
    ) -> "VariableTracker":
        unimplemented("numpy")

    def python_type(self):
        return type(self.value)

    def as_python_constant(self):
        return self.value

    def as_proxy(self):
        if config.trace_numpy and isinstance(self.value, type):
            # This handles numpy dtype attributes such as np.float32
            # We return a string as we don't want to serialize non-PyTorch objects in the output FX graph
            # In torch/_numpy we normalize strings to their dtypes when the input is a dtype, as NumPy does
            return self.value.__name__

        return super().as_proxy()


# Used to keep track of NULLs pushed on the stack for Python 3.11 function calls
class NullVariable(VariableTracker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def __str__(self):
        return "NullVariable"

    def reconstruct(self, codegen):
        if sys.version_info < (3, 11):
            unimplemented("cannot reconstruct NullVariable in < Python 3.11")
        codegen.append_output(create_instruction("PUSH_NULL"))


class DeletedVariable(VariableTracker):
    """Marker used to implement delattr()"""


class StringFormatVariable(VariableTracker):
    """
    Represents a call to str.format(), we delay calling format until after the graph.
    """

    _nonvar_fields = {"format_string", *VariableTracker._nonvar_fields}

    @classmethod
    def create(cls, format_string, sym_args, sym_kwargs):
        if all(
            x.is_python_constant()
            for x in itertools.chain(sym_args, sym_kwargs.values())
        ):
            return variables.ConstantVariable.create(
                format_string.format(
                    *[v.as_python_constant() for v in sym_args],
                    **{k: v.as_python_constant() for k, v in sym_kwargs.items()},
                )
            )
        return cls(format_string, list(sym_args), dict(sym_kwargs))

    def __init__(self, format_string, sym_args, sym_kwargs, **kwargs):
        super().__init__(**kwargs)
        assert isinstance(format_string, str)
        self.format_string = format_string
        self.sym_args = sym_args
        self.sym_kwargs = sym_kwargs

    def __repr__(self):
        return f"{self.__class__.__name__}({self.format_string!r}, {self.sym_args!r}, {self.sym_kwargs!r})"

    def reconstruct(self, codegen):
        if sys.version_info >= (3, 11):
            codegen.append_output(create_instruction("PUSH_NULL"))
        codegen.append_output(codegen.create_load_const(self.format_string))
        codegen.append_output(codegen.create_load_attr("format"))
        codegen(variables.TupleVariable(self.sym_args))
        kwargs = {
            variables.ConstantVariable.create(k): v for k, v in self.sym_kwargs.items()
        }
        codegen(variables.ConstDictVariable(kwargs))
        codegen.append_output(create_instruction("CALL_FUNCTION_EX", arg=1))


class DebuggingVariable(VariableTracker):
    """
    Represents a call to a debugging function like print(), or something
    registered to config.reorderable_logging_functions.
    """

    def __init__(self, value, **kwargs):
        super().__init__(**kwargs)
        self.value = value

    @staticmethod
    def is_reorderable_logging_function(obj):
        return (
            callable(obj)
            and isinstance(obj, (types.FunctionType, types.BuiltinFunctionType))
            and obj in torch._dynamo.config.reorderable_logging_functions
        )

    def call_function(self, tx, args, kwargs):
        if tx.export:
            # For export cases, we can just make debugging functions no-ops
            return

        if not self.can_reorder_logs(self.value, args, kwargs):
            unimplemented(
                f"Reordering debugging function {self.value} "
                f"with inputs {args} {kwargs} is not yet implemented."
            )

        tx.debug_locals.append((self, list(args)))

    def reconstruct(self, codegen):
        return self.source.reconstruct(codegen)

    @staticmethod
    def can_reorder_logs(fn, args, kwargs) -> True:
        """
        Run some additional checks for what sort of function calls can we
        actually reorder.
        """

        allowed_input_types = (
            variables.TensorVariable,
            variables.ConstantVariable,
            StringFormatVariable,
        )

        flat_args = pytree.tree_leaves([args, kwargs])
        for arg in flat_args:
            if not isinstance(arg, allowed_input_types):
                return False

        return True
