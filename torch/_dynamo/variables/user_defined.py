# mypy: ignore-errors

import collections
import contextlib
import functools
import importlib
import inspect
import itertools
import random
import sys
import threading
import types
from typing import Dict, List

from ..bytecode_transformation import create_call_function

try:
    import numpy as np
except ModuleNotFoundError:
    np = None

try:
    from torch.utils._cxx_pytree import PyTreeSpec
except ImportError:
    PyTreeSpec = type(None)

import torch._dynamo.config

import torch.nn
from torch._guards import TracingContext

from .. import variables
from ..exc import unimplemented
from ..guards import GuardBuilder, install_guard
from ..source import AttrSource, GetItemSource, ODictGetItemSource, RandomValueSource
from ..utils import (
    all_hook_names,
    build_checkpoint_variable,
    check_constant_args,
    get_custom_getattr,
    has_torch_function,
    is_namedtuple_cls,
    is_utils_checkpoint,
    istype,
    namedtuple_fields,
    object_has_getattribute,
    proxy_args_kwargs,
    tensortype_to_dtype,
)
from .base import MutableLocal, VariableTracker
from .ctx_manager import GenericContextWrappingVariable, NullContextVariable
from .dicts import DefaultDictVariable


class UserDefinedVariable(VariableTracker):
    pass


class UserDefinedClassVariable(UserDefinedVariable):
    def __init__(self, value, **kwargs):
        super().__init__(**kwargs)
        self.value = value

    def as_python_constant(self):
        return self.value

    def python_type(self):
        return type(self.value)

    def as_proxy(self):
        return self.value

    def __str__(self):
        return f"UserDefinedClassVariable({self.value})"

    @staticmethod
    @functools.lru_cache(None)
    def _constant_fold_classes():
        return {
            torch.device,
            torch.finfo,
            torch.iinfo,
            torch.Size,
        }

    @staticmethod
    @functools.lru_cache(None)
    def _in_graph_classes():
        return set(tensortype_to_dtype.keys()) | {
            torch.Tensor,
            torch.cuda.Stream,
            torch.cuda.Event,
        }

    def can_constant_fold_through(self):
        return self.value in self._constant_fold_classes()

    def var_getattr(self, tx, name: str) -> "VariableTracker":
        from .. import trace_rules
        from . import ConstantVariable
        from .builder import VariableBuilder

        if name == "__name__":
            return ConstantVariable.create(self.value.__name__)

        source = AttrSource(self.source, name) if self.source is not None else None
        try:
            obj = inspect.getattr_static(self.value, name)
        except AttributeError:
            obj = None

        if isinstance(obj, staticmethod):
            func = obj.__get__(self.value)
            if source is not None:
                return trace_rules.lookup(func).create_with_source(func, source=source)
            else:
                return trace_rules.lookup(func)(func)
        elif isinstance(obj, classmethod):
            return variables.UserMethodVariable(obj.__func__, self, source=source)
        elif source and inspect.ismemberdescriptor(obj):
            return VariableBuilder(tx, source)(obj.__get__(self.value))

        # Special handling of collections.OrderedDict.fromkeys()
        # Wrap it as GetAttrVariable(collections.OrderedDict, "fromkeys") to make it consistent with
        # collections.defaultdict, and both will be handled at UserDefinedClassVariable.call_method().
        # Otherwise, it would be wrapped as UserDefinedObjectVariable(collections.OrderedDict.fromkeys),
        # and we need duplicate code to handle both cases.
        if self.value is collections.OrderedDict and name == "fromkeys":
            return super().var_getattr(tx, name)

        if name in getattr(self.value, "__dict__", {}) or (
            self.value.__module__.startswith("torch.")
            or self.value.__module__ == "torch"
        ):
            if source:
                return VariableBuilder(tx, source)(obj)
        elif ConstantVariable.is_literal(obj):
            return ConstantVariable.create(obj)

        return super().var_getattr(tx, name)

    def _call_cross_entropy_loss(self, tx, args, kwargs):
        """
        functional: input, target, weight=None, size_average=None, ignore_index=- 100, reduce=None, reduction='mean',
        label_smoothing=0.0

        non functional ctor: weight=None, size_average=None, ignore_index=- 100, reduce=None, reduction='mean',
        label_smoothing=0.0

        non functional loss call: input, target, optional_output
        """
        from . import ConstantVariable

        def normalize_args(
            weight=ConstantVariable.create(None),
            size_average=ConstantVariable.create(None),
            ignore_index=ConstantVariable.create(-100),
            reduce=ConstantVariable.create(None),
            reduction=ConstantVariable.create("mean"),
            label_smoothing=ConstantVariable.create(0.0),
        ):
            return (
                weight,
                size_average,
                ignore_index,
                reduce,
                reduction,
                label_smoothing,
            )

        (
            weight,
            size_average,
            ignore_index,
            reduce_arg,
            reduction,
            label_smoothing,
        ) = normalize_args(*args, **kwargs)

        def fake_cross_entropy_loss(input, target):
            from .builder import wrap_fx_proxy

            return wrap_fx_proxy(
                tx=tx,
                proxy=tx.output.create_proxy(
                    "call_function",
                    torch.nn.functional.cross_entropy,
                    *proxy_args_kwargs(
                        [
                            input,
                            target,
                            weight,
                            size_average,
                            ignore_index,
                            reduce_arg,
                            reduction,
                            label_smoothing,
                        ],
                        {},
                    ),
                ),
            )

        return variables.LambdaVariable(fake_cross_entropy_loss)

    def call_method(
        self,
        tx,
        name,
        args: "List[VariableTracker]",
        kwargs: "Dict[str, VariableTracker]",
    ) -> "VariableTracker":
        if (
            name == "__subclasses__"
            and len(args) == 0
            and not kwargs
            and "__subclasses__" not in self.value.__dict__
        ):
            options = {"mutable_local": MutableLocal()}
            subs_as_vars: List[VariableTracker] = list()
            for sub in self.value.__subclasses__():
                source = AttrSource(tx.import_source(sub.__module__), sub.__name__)
                subs_as_vars.append(
                    variables.UserDefinedClassVariable(sub, source=source)
                )

            return variables.ListVariable(subs_as_vars, **options)
        elif (
            self.value in {collections.OrderedDict, collections.defaultdict}
            and name == "fromkeys"
        ):
            from .builtin import BuiltinVariable

            return BuiltinVariable.call_custom_dict_fromkeys(
                tx, self.value, *args, **kwargs
            )

        return super().call_method(tx, name, args, kwargs)

    def call_function(
        self, tx, args: "List[VariableTracker]", kwargs: "Dict[str, VariableTracker]"
    ) -> "VariableTracker":
        from ..side_effects import SideEffects
        from .builder import SourcelessBuilder, wrap_fx_proxy
        from .builtin import BuiltinVariable

        constant_args = check_constant_args(args, kwargs)

        if self.can_constant_fold_through() and constant_args:
            # constant fold
            return variables.ConstantVariable.create(
                self.as_python_constant()(
                    *[x.as_python_constant() for x in args],
                    **{k: v.as_python_constant() for k, v in kwargs.items()},
                ),
            )
        elif self.value is torch.nn.CrossEntropyLoss:
            return self._call_cross_entropy_loss(tx, args, kwargs)
        elif self.value is contextlib.nullcontext:
            return NullContextVariable()
        elif self.value is collections.OrderedDict:
            return BuiltinVariable.call_custom_dict(
                tx, collections.OrderedDict, *args, **kwargs
            )
        elif (
            self.value is collections.defaultdict
            and len(args) <= 1
            and DefaultDictVariable.is_supported_arg(args[0])
        ):
            return DefaultDictVariable(
                {},
                collections.defaultdict,
                args[0],
                mutable_local=MutableLocal(),
            )
        elif self.value is collections.deque and not kwargs:
            if len(args) == 0:
                items = []
            elif len(args) == 1 and args[0].has_unpack_var_sequence(tx):
                items = args[0].unpack_var_sequence(tx)
            else:
                unimplemented("deque() with more than 1 arg not supported")
            return variables.lists.DequeVariable(items, mutable_local=MutableLocal())
        elif self.value is functools.partial:
            if not args:
                unimplemented("functools.partial malformed")
            # The first arg, a callable (the ctor below will assert on types)
            fn = args[0]
            rest_args = args[1:]
            # guards for the produced FunctoolsPartialVariable are installed in FunctoolsPartialVariable ctor from the
            # args and keywords
            return variables.functions.FunctoolsPartialVariable(
                fn, args=rest_args, keywords=kwargs
            )
        elif (
            issubclass(type(self.value), type)
            and hasattr(
                self.value, "__enter__"
            )  # TODO(voz): These can invoke user code!
            and hasattr(
                self.value, "__exit__"
            )  # TODO(voz): These can invoke user code!
            and check_constant_args(args, kwargs)
            and self.value.__init__ == object.__init__
            and len(kwargs) == 0  # TODO(ybliang): support kwargs
        ):
            unwrapped_args = [x.as_python_constant() for x in args]
            return GenericContextWrappingVariable(
                unwrapped_args,
                cm_obj=self.value(*unwrapped_args),
            )

        elif is_namedtuple_cls(self.value):
            fields = namedtuple_fields(self.value)
            # check if this a quasi-namedtuple or a real one
            if self.value.__module__ == "torch.return_types":
                # create pseudo-defaults from values of the quasi-namedtuple
                field_defaults = dict(zip(fields, args[0].items))
            else:
                field_defaults = self.value._field_defaults

            items = list(args)
            items.extend([None] * (len(fields) - len(items)))

            var_tracker_kwargs = {}
            for field_name, var_tracker in zip(fields, items):
                if var_tracker is None:
                    if field_name in kwargs:
                        field_var = kwargs[field_name]
                    else:
                        assert field_name in field_defaults
                        field_var = SourcelessBuilder()(tx, field_defaults[field_name])
                    var_tracker_kwargs[field_name] = field_var

            for name, value in var_tracker_kwargs.items():
                assert name in fields
                items[fields.index(name)] = value

            assert all(x is not None for x in items)
            return variables.NamedTupleVariable(items, self.value)
        elif (
            inspect.getattr_static(self.value, "__new__", None) in (object.__new__,)
            and SideEffects.cls_supports_mutation_side_effects(self.value)
            and self.source
        ):
            var = tx.output.side_effects.track_object_new(
                self.source,
                self.value,
                variables.UnspecializedNNModuleVariable
                if issubclass(self.value, torch.nn.Module)
                else UserDefinedObjectVariable,
                {},
            )
            if (
                inspect.getattr_static(self.value, "__init__", None)
                is torch.nn.Module.__init__
            ):
                tx.output.side_effects.store_attr(
                    var,
                    "__call_nn_module_init",
                    variables.ConstantVariable.create(True),
                )
                return var
            else:
                var.call_method(tx, "__init__", args, kwargs)
                return var
        elif variables.CustomizedDictVariable.is_matching_cls(self.value):
            options = {"mutable_local": MutableLocal()}
            return variables.CustomizedDictVariable.create(
                self.value, args, kwargs, options
            )
        elif variables.DataClassVariable.is_matching_cls(self.value):
            options = {"mutable_local": MutableLocal()}
            return variables.DataClassVariable.create(self.value, args, kwargs, options)
        elif (
            variables.RestrictedListSubclassVariable.is_matching_cls(self.value)
            and self.source
        ):
            return variables.RestrictedListSubclassVariable(
                variables.BuiltinVariable(list).call_function(tx, args, kwargs).items,
                user_cls=self.value,
                user_cls_source=self.source,
                mutable_local=MutableLocal(),
            )
        elif self.value in self._in_graph_classes():
            # torch.LongTensor cannot accept a list of FakeTensors.
            # So we stack the list of FakeTensors instead.
            if (
                np
                and self.value in tensortype_to_dtype
                and len(args) == 1
                and isinstance(args[0], variables.ListVariable)
                and len(args[0].items) > 1
                and all(isinstance(x, variables.TensorVariable) for x in args[0].items)
            ):
                # Stack FakeTensor
                stacked = wrap_fx_proxy(
                    tx=tx,
                    proxy=tx.output.create_proxy(
                        "call_function",
                        torch.stack,
                        *proxy_args_kwargs(args, kwargs),
                    ),
                )
                args = [stacked]

            tensor_variable = wrap_fx_proxy(
                tx=tx,
                proxy=tx.output.create_proxy(
                    "call_function",
                    self.value,
                    *proxy_args_kwargs(args, kwargs),
                ),
            )

            return tensor_variable

        return super().call_function(tx, args, kwargs)

    def const_getattr(self, tx, name):
        if name == "__name__":
            return self.value.__name__
        return super().const_getattr(tx, name)


class UserDefinedObjectVariable(UserDefinedVariable):
    """
    Mostly objects of defined type.  Catch-all for something where we only know the type.
    """

    _nonvar_fields = {"value", "value_type", *UserDefinedVariable._nonvar_fields}

    def __init__(self, value, value_type=None, **kwargs):
        super().__init__(**kwargs)
        self.value = value
        self.value_type = value_type or type(value)
        assert type(value) is self.value_type

    def __str__(self):
        inner = self.value_type.__name__
        if inner in [
            "builtin_function_or_method",
            "getset_descriptor",
            "method_descriptor",
            "method",
        ]:
            inner = str(getattr(self.value, "__name__", None))
        return f"{self.__class__.__name__}({inner})"

    def python_type(self):
        return self.value_type

    def guard_as_python_constant(self):
        if self.source:
            install_guard(self.source.make_guard(GuardBuilder.ID_MATCH))
            return self.value
        return super().guard_as_python_constant()

    def torch_function_check(self):
        assert has_torch_function(
            self
        ), f"calling torch function on object without __torch_function__ {self}"

    def get_torch_fn(self, tx):
        self.torch_function_check()
        from .torch_function import build_torch_function_fn

        return build_torch_function_fn(tx, self.value, self.source)

    def call_torch_function(self, tx, fn, types, args, kwargs):
        self.torch_function_check()

        from .torch_function import _get_subclass_type_var, call_torch_function

        return call_torch_function(
            tx,
            _get_subclass_type_var(tx, self),
            self.get_torch_fn(tx),
            fn,
            types,
            args,
            kwargs,
        )

    @staticmethod
    @functools.lru_cache(None)
    def _supported_random_functions():
        fns = {
            random.random,
            random.randint,
            random.randrange,
            random.uniform,
        }
        return fns

    def _maybe_get_baseclass_method(self, name):
        if name not in getattr(self.value, "__dict__", {}):
            try:
                return inspect.getattr_static(type(self.value), name)
            except AttributeError:
                pass
        return None

    def call_method(
        self,
        tx,
        name,
        args: "List[VariableTracker]",
        kwargs: "Dict[str, VariableTracker]",
    ) -> "VariableTracker":
        from . import (
            BuiltinVariable,
            ConstantVariable,
            TupleVariable,
            UserMethodVariable,
        )

        method = self._maybe_get_baseclass_method(name)
        if method is not None:
            if method is object.__init__:
                return ConstantVariable.create(None)

            # [NOTE] OrderedDict, dict subtypes must always have source
            # We cannot instantiate such subtypes in-graph due to builtin __new__
            if method is collections.OrderedDict.keys:
                # subclass of OrderedDict
                assert not (args or kwargs)
                assert self.source  # OrderedDict, dict subtypes must always have source
                keys = list(self.value.keys())
                assert all(map(ConstantVariable.is_literal, keys))
                install_guard(self.source.make_guard(GuardBuilder.DICT_CONST_KEYS))
                return TupleVariable([ConstantVariable.create(k) for k in keys])

            if (
                method in (collections.OrderedDict.__contains__, dict.__contains__)
                and len(args) == 1
                and isinstance(args[0], (ConstantVariable, BuiltinVariable))
                and inspect.getattr_static(type(self.value), "keys")
                in (collections.OrderedDict.keys, dict.keys)
            ):
                assert not kwargs
                assert self.source  # OrderedDict, dict subtypes must always have source
                install_guard(self.source.make_guard(GuardBuilder.DICT_CONST_KEYS))
                return ConstantVariable.create(
                    args[0].as_python_constant() in self.value
                )

            if method is collections.OrderedDict.items and isinstance(
                self.value, collections.OrderedDict
            ):
                assert self.source  # OrderedDict, dict subtypes must always have source
                assert not (args or kwargs)
                items = []
                keys = self.call_method(tx, "keys", [], {})
                for key in keys.unpack_var_sequence(tx):
                    items.append(
                        TupleVariable(
                            [key, self.odict_getitem(tx, key)],
                        )
                    )
                return TupleVariable(items)

            if method is collections.OrderedDict.__getitem__ and len(args) == 1:
                assert not kwargs
                assert self.source  # OrderedDict, dict subtypes must always have source
                return self.odict_getitem(tx, args[0])

            # check for methods implemented in C++
            if isinstance(method, types.FunctionType):
                source = (
                    None
                    if self.source is None
                    else AttrSource(AttrSource(self.source, "__class__"), name)
                )
                # TODO(jansel): add a guard to check for monkey patching?
                return UserMethodVariable(method, self, source=source).call_function(
                    tx, args, kwargs
                )

            if method is list.__len__ and self.source and not (args or kwargs):
                install_guard(self.source.make_guard(GuardBuilder.SEQUENCE_LENGTH))
                return ConstantVariable(len(self.value))

        return super().call_method(tx, name, args, kwargs)

    def unpack_var_sequence(self, tx):
        if (
            self.source
            and self._maybe_get_baseclass_method("__iter__") is list.__iter__
            and self._maybe_get_baseclass_method("__len__") is list.__len__
            and self._maybe_get_baseclass_method("__getitem__") is list.__getitem__
        ):
            install_guard(self.source.make_guard(GuardBuilder.SEQUENCE_LENGTH))
            return [
                variables.LazyVariableTracker.create(
                    self.value[k],
                    source=GetItemSource(self.source, k),
                )
                for k in range(len(self.value))
            ]
        return super().unpack_var_sequence(tx)

    def is_supported_random(self):
        try:
            return self.value in self._supported_random_functions()
        except TypeError:
            # TypeError: unhashable type
            return False

    def call_function(
        self, tx, args: "List[VariableTracker]", kwargs: "Dict[str, VariableTracker]"
    ) -> "VariableTracker":
        from .. import trace_rules
        from .builder import VariableBuilder

        if (
            self.is_supported_random()
            and all(k.is_python_constant() for k in args)
            and all(v.is_python_constant() for v in kwargs.values())
        ):
            args = [x.as_python_constant() for x in args]
            kwargs = {k: v.as_python_constant() for k, v in kwargs.items()}
            random_call_index = len(tx.output.random_calls)
            example_value = self.value(*args, **kwargs)
            source = RandomValueSource(random_call_index)
            tx.output.random_calls.append((self.value, args, kwargs))
            return VariableBuilder(tx, source).wrap_unspecialized_primitive(
                example_value
            )
        elif istype(self.value, types.MethodType):
            func = self.value.__func__
            obj = self.value.__self__
            if (
                func is torch.utils._contextlib._DecoratorContextManager.clone
                and variables.TorchCtxManagerClassVariable.is_matching_cls(
                    obj.__class__
                )
                and not (args or kwargs)
            ):
                return variables.TorchCtxManagerClassVariable(
                    obj.__class__
                ).call_function(tx, args, kwargs)

            if (
                func is torch.autograd.grad_mode.inference_mode.clone
                and obj.__class__ is torch.autograd.grad_mode.inference_mode
            ):
                # simulate the inference_mode.clone implementation
                var = variables.ConstantVariable(obj.mode)
                return variables.TorchCtxManagerClassVariable(
                    obj.__class__
                ).call_function(tx, [var], kwargs)
        elif (
            istype(self.value, functools.partial)
            and trace_rules.lookup(self.value.func)
            == variables.TorchInGraphFunctionVariable
            and all(
                variables.ConstantVariable.is_literal(v)
                for v in itertools.chain(self.value.args, self.value.keywords.values())
            )
        ):
            if self.source:
                install_guard(
                    AttrSource(self.source, "func").make_guard(GuardBuilder.ID_MATCH),
                    AttrSource(self.source, "args").make_guard(
                        GuardBuilder.CONSTANT_MATCH
                    ),
                    AttrSource(self.source, "keywords").make_guard(
                        GuardBuilder.CONSTANT_MATCH
                    ),
                )

            partial_args = [
                variables.ConstantVariable.create(v) for v in self.value.args
            ]
            partial_args.extend(args)
            partial_kwargs = {
                k: variables.ConstantVariable.create(v)
                for k, v in self.value.keywords.items()
            }
            partial_kwargs.update(kwargs)
            if is_utils_checkpoint(self.value.func):
                return build_checkpoint_variable().call_function(
                    tx, partial_args, partial_kwargs
                )
            return variables.TorchInGraphFunctionVariable(
                self.value.func
            ).call_function(tx, partial_args, partial_kwargs)
        elif callable(self.value):
            if self.source:
                install_guard(self.source.make_guard(GuardBuilder.FUNCTION_MATCH))
            return self.call_method(tx, "__call__", args, kwargs)

        return super().call_function(tx, args, kwargs)

    def _check_for_getattribute(self):
        if object_has_getattribute(self.value):
            unimplemented("UserDefinedObjectVariable with custom __getattribute__")

    def _check_for_getattr(self):
        return get_custom_getattr(self.value)

    def _getattr_static(self, name):
        if (
            isinstance(self.value, (torch.nn.Module, PyTreeSpec))
            or "__slots__" in self.value.__class__.__dict__
            or type(self.value) == threading.local
        ):
            # getattr_static doesn't work on these
            subobj = getattr(self.value, name)
        else:
            subobj = inspect.getattr_static(self.value, name)
        return subobj

    def var_getattr(self, tx, name):
        from .. import trace_rules
        from . import ConstantVariable
        from .builder import VariableBuilder

        value = self.value
        source = AttrSource(self.source, name) if self.source else None
        self._check_for_getattribute()
        getattr_fn = self._check_for_getattr()

        class NO_SUCH_SUBOBJ:
            pass

        try:
            subobj = self._getattr_static(name)
        except AttributeError:
            subobj = NO_SUCH_SUBOBJ
            if isinstance(getattr_fn, types.FunctionType):
                return variables.UserMethodVariable(
                    getattr_fn, self, source=source
                ).call_function(tx, [ConstantVariable.create(name)], {})
            elif getattr_fn is not None:
                unimplemented("UserDefined with non-function __getattr__")

        if isinstance(subobj, property):
            # Rewrite the source being explicit about reading it statically.
            if self.source:
                source = AttrSource(self.source, name, get_static=True)
                source = AttrSource(source, "fget")
            return variables.UserMethodVariable(
                subobj.fget, self, source=source
            ).call_function(tx, [], {})
        elif isinstance(subobj, torch.distributions.utils.lazy_property):
            subobj_var = UserDefinedObjectVariable(subobj, source=source)
            return variables.UserMethodVariable(
                subobj.__get__.__func__, subobj_var, source=source
            ).call_function(tx, [self], {})
        elif isinstance(subobj, staticmethod):
            func = subobj.__get__(self.value)
            if source is not None:
                return trace_rules.lookup(func).create_with_source(func, source=source)
            else:
                return trace_rules.lookup(func)(func)
        elif isinstance(subobj, classmethod):
            return variables.UserMethodVariable(
                subobj.__func__, self.var_getattr(tx, "__class__"), source=source
            )
        elif isinstance(subobj, types.FunctionType) or (
            isinstance(subobj, types.MethodType)
            and isinstance(self.value, torch.nn.Module)
        ):
            # Since we get subobj via self._getattr_static, which may not trigger dynamic lookup.
            # Static lookup can't tell us it's a method or function correctly,
            # so we trigger dynamic lookup here to get the correct type.
            dynamic_subobj = getattr(self.value, name)

            while dynamic_subobj is subobj and hasattr(subobj, "_torchdynamo_inline"):
                subobj = subobj._torchdynamo_inline
                dynamic_subobj = subobj
                source = AttrSource(source, "_torchdynamo_inline") if source else None

            if isinstance(subobj, types.MethodType):
                if dynamic_subobj.__self__ is not self.value:
                    unimplemented("__self__ mismatch for bound method")
                func = subobj.__func__
            else:
                assert isinstance(subobj, types.FunctionType)
                func = subobj

            if inspect.ismethod(dynamic_subobj):
                return variables.UserMethodVariable(func, self, source=source)
            elif inspect.isfunction(dynamic_subobj):
                if is_utils_checkpoint(func):
                    return build_checkpoint_variable(source=source)
                elif source is not None:
                    return trace_rules.lookup(func).create_with_source(
                        func, source=source
                    )
                else:
                    return trace_rules.lookup(func)(func)

        if (
            name in getattr(value, "__dict__", {})
            or ConstantVariable.is_literal(subobj)
            or isinstance(
                subobj,
                (
                    torch.Tensor,
                    torch.nn.Module,
                ),
            )
        ):
            if source:
                return VariableBuilder(tx, source)(subobj)
            elif ConstantVariable.is_literal(subobj):
                return ConstantVariable.create(subobj)

        if (
            name not in getattr(value, "__dict__", {})
            and type(value).__module__.startswith("torch.")
            and "torch.optim" not in type(value).__module__
            and not callable(value)
            and not isinstance(subobj, types.MethodDescriptorType)
        ):
            if not source:
                assert getattr(
                    importlib.import_module(type(value).__module__),
                    type(value).__name__,
                ) is type(value)
                source = AttrSource(
                    AttrSource(
                        tx.import_source(type(value).__module__), type(value).__name__
                    ),
                    name,
                )

            return VariableBuilder(tx, source)(subobj)
        options = {"source": source}
        if isinstance(
            subobj,
            (
                torch.distributions.constraints._Interval,
                torch.distributions.constraints._Real,
                torch.distributions.constraints.Constraint,
            ),
        ):
            return UserDefinedObjectVariable(subobj, **options)
        elif isinstance(self.value, torch.nn.Module) and name in all_hook_names:
            assert isinstance(subobj, collections.OrderedDict)
            if not subobj:
                return variables.ConstDictVariable(
                    subobj, collections.OrderedDict, **options
                )

        if name == "__class__":
            return UserDefinedClassVariable(type(self.value), **options)

        return variables.GetAttrVariable(self, name, **options)

    def call_hasattr(self, tx, name: str) -> "VariableTracker":
        if tx.output.side_effects.is_attribute_mutation(self):
            try:
                result = tx.output.side_effects.load_attr(self, name, deleted_ok=True)
                return variables.ConstantVariable.create(
                    not isinstance(result, variables.DeletedVariable)
                )
            except KeyError:
                pass
        if self.source:
            install_guard(
                AttrSource(self.source, name).make_guard(GuardBuilder.HASATTR)
            )
        if self._check_for_getattribute() or self._check_for_getattr():
            unimplemented("hasattr with custom __getattr__")

        try:
            self._getattr_static(name)
            return variables.ConstantVariable.create(True)
        except AttributeError:
            return variables.ConstantVariable.create(False)

    def odict_getitem(self, tx, key):
        from .builder import VariableBuilder
        from .dicts import is_hashable

        # TODO this should probably be merged with the dict handling

        index = (
            key.source
            if is_hashable(key) and key.source is not None
            else key.as_python_constant()
        )

        return VariableBuilder(
            tx,
            ODictGetItemSource(self.source, index),
        )(collections.OrderedDict.__getitem__(self.value, key.as_python_constant()))


class KeyedJaggedTensorVariable(UserDefinedObjectVariable):
    @staticmethod
    def is_matching_object(obj):
        mod = sys.modules.get("torchrec.sparse.jagged_tensor")
        return mod is not None and type(obj) is mod.KeyedJaggedTensor

    def __init__(self, value, **kwargs):
        from torchrec.sparse.jagged_tensor import KeyedJaggedTensor

        assert type(value) is KeyedJaggedTensor
        super().__init__(value, **kwargs)

    def var_getattr(self, tx, name):
        if (
            torch._dynamo.config.force_unspec_int_unbacked_size_like_on_torchrec_kjt
            and self.source is not None
            and name in ("_length_per_key", "_offset_per_key")
        ):
            with TracingContext.patch(force_unspec_int_unbacked_size_like=True):
                return super().var_getattr(tx, name)
        return super().var_getattr(tx, name)


class RemovableHandleVariable(VariableTracker):
    REMOVED = -1

    def __init__(
        self,
        mutable_local=None,
        # index of the registration in the side_effects owned register_hook/handle list, used during removal.
        idx=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.mutable_local = mutable_local
        self.idx = idx

    def call_method(self, tx, method_name, args, kwargs):
        if method_name == "remove":
            if self.idx != self.REMOVED:
                tx.output.side_effects.remove_hook(self.idx)
                self.idx = self.REMOVED
            return variables.ConstantVariable.create(None)
        super().call_method(tx, method_name, args, kwargs)

    def reconstruct(self, codegen):
        if self.idx == self.REMOVED:
            # Hook has already been removed, return a dummy handle
            codegen.load_import_from("torch._dynamo.utils", "invalid_removeable_handle")
            codegen.extend_output(create_call_function(0, True))
            return
        # unreachable due to codegen.add_cache() when the hook is installed
        super().reconstruct(codegen)
