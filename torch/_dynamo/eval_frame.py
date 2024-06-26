# mypy: disable-error-code="method-assign"

"""
Functions in this file are responsible for modifying the eval frame
handler at RUNTIME.  Therefore, all functions in this file are hot.
Functions that only execute at compile time should be placed
in torch._dynamo.convert_frame.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import logging
import os
import sys
import textwrap
import threading
import traceback
import types
import warnings
import weakref
from enum import Enum
from os.path import dirname, join
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set, Tuple, Union
from unittest.mock import patch

import torch
import torch.fx
import torch.utils._pytree as pytree
import torch.utils.checkpoint
from torch import _guards
from torch._subclasses import fake_tensor
from torch._utils_internal import log_export_usage
from torch.export import Constraint
from torch.export.dynamic_shapes import _process_dynamic_shapes
from torch.fx.experimental.proxy_tensor import make_fx, maybe_disable_fake_tensor_mode
from torch.fx.experimental.symbolic_shapes import (
    ConstraintViolationError,
    DimDynamic,
    StatelessSymbolicContext,
)
from torch.fx.graph import _PyTreeCodeGen, _PyTreeInfo

from ..fx import GraphModule
from .backends.registry import CompilerFn, lookup_backend

from .hooks import Hooks

# see discussion at https://github.com/pytorch/pytorch/issues/120699
reset_code = torch._C._dynamo.eval_frame.reset_code  # noqa: F401
set_eval_frame = torch._C._dynamo.eval_frame.set_eval_frame  # noqa: F401
set_guard_error_hook = torch._C._dynamo.eval_frame.set_guard_error_hook  # noqa: F401
skip_code = torch._C._dynamo.eval_frame.skip_code  # noqa: F401
unsupported = torch._C._dynamo.eval_frame.unsupported  # noqa: F401

from . import config, convert_frame, external_utils, trace_rules, utils
from .code_context import code_context
from .exc import CondOpArgsMismatchError, UserError, UserErrorType
from .mutation_guard import install_generation_tagging_init
from .types import CacheEntry, DynamoCallback
from .utils import common_constant_types, compile_times

log = logging.getLogger(__name__)

from torch._dispatch.python import enable_python_dispatcher

always_optimize_code_objects = utils.ExactWeakKeyDictionary()
null_context = contextlib.nullcontext


import sympy


# See https://github.com/python/typing/pull/240
class Unset(Enum):
    token = 0


unset = Unset.token

guarded_backend_cache = threading.local()
cached_backends: Dict[int, CompilerFn] = {}


def check_current_backend(backend_obj_id: int):
    """
    Called from guards to check if we need to recompile due to a backend change
    """
    # TODO(jansel): we should move guarded_backend_cache to C++
    try:
        if guarded_backend_cache.skip_backend_check_for_run_only_mode:
            return True
    except AttributeError:
        # Go slightly faster next time
        guarded_backend_cache.skip_backend_check_for_run_only_mode = False
    try:
        current_backend = guarded_backend_cache.current_backend
    except AttributeError:
        current_backend = None
    return (
        # Avoid the dict lookup in case of exact same object
        id(current_backend) == backend_obj_id
        or current_backend == cached_backends.get(backend_obj_id, None)
    )


def _reset_guarded_backend_cache():
    global cached_backends
    guarded_backend_cache.skip_backend_check_for_run_only_mode = False
    guarded_backend_cache.current_backend = None
    for backend in cached_backends.values():
        if hasattr(backend, "reset"):
            backend.reset()
    cached_backends.clear()


def backend_cache_manager(callback: DynamoCallback):
    # callback is False for RunOnlyContext. RunOnlyContext is used
    # as a way to re-use the previous compiled cache.
    # We therefore skip the check and re-use whatever code that's already cached.
    # Note: the cache that's actually used depends on the caching policy.
    if callback is False:

        def change():
            try:
                prev_skip = guarded_backend_cache.skip_backend_check_for_run_only_mode
            except AttributeError:
                prev_skip = False
            guarded_backend_cache.skip_backend_check_for_run_only_mode = True

            def revert():
                guarded_backend_cache.skip_backend_check_for_run_only_mode = prev_skip

            return revert

    else:
        backend = innermost_fn(callback)

        def change():
            cached_backends.setdefault(id(backend), backend)
            try:
                prev_backend = guarded_backend_cache.current_backend
            except AttributeError:
                prev_backend = None
            guarded_backend_cache.current_backend = backend

            def revert():
                guarded_backend_cache.current_backend = prev_backend

            return revert

    return change


DONT_WRAP_FILES = {
    # For tracing into fx modules
    inspect.getsourcefile(GraphModule),
    join(dirname(dirname(__file__)), "onnx/_internal/fx/dynamo_graph_extractor.py"),
}


def _debug_get_cache_entry_list(
    code: Union[types.CodeType, Callable[..., Any]]
) -> List[CacheEntry]:
    """
    Given a code object or a callable object, retrieve the cache entries
     stored in this code.
    """
    if callable(code):
        code = code.__code__
    return torch._C._dynamo.eval_frame._debug_get_cache_entry_list(code)


class OptimizedModule(torch.nn.Module):
    """
    Wraps the original nn.Module object and later patches its
    forward method to optimized self.forward method.
    """

    _torchdynamo_orig_callable: Callable[..., Any]
    get_compiler_config: Callable[[], Any]

    def __init__(self, mod: torch.nn.Module, dynamo_ctx):
        super().__init__()
        # Installs the params/buffer
        self._orig_mod = mod
        self.dynamo_ctx = dynamo_ctx
        self._initialize()

    def _initialize(self):
        # Do this stuff in constructor to lower overhead slightly
        if isinstance(self._orig_mod.forward, types.MethodType) and trace_rules.check(
            self._orig_mod.forward
        ):
            # This may be a torch.nn.* instance in trace_rules.py which
            # won't trigger a frame evaluation workaround to add an extra
            # frame we can capture
            self.forward = self.dynamo_ctx(external_utils.wrap_inline(self._orig_mod))
        else:
            # Invoke hooks outside of dynamo then pickup the inner frame
            self.forward = self.dynamo_ctx(self._orig_mod.__call__)

        if hasattr(self._orig_mod, "_initialize_hook"):
            self._forward = self.forward
            self.forward = self._call_lazy_check

    def __getstate__(self):
        state = dict(self.__dict__)
        state.pop("forward", None)
        state.pop("__call__", None)
        return state

    def __setstate__(self, state):
        self.__dict__ = state
        self._initialize()

    def __getattr__(self, name):
        if name == "_orig_mod":
            return self._modules["_orig_mod"]
        return getattr(self._orig_mod, name)

    def _call_lazy_check(self, *args, **kwargs):
        if hasattr(self._orig_mod, "_initialize_hook"):
            # In the case of a lazy module, we want to run
            # the pre-hooks which initialize it.
            # Afterwards, lazy module deletes its pre-hooks
            # to avoid treating it as lazy on subsequent recompile.
            self._orig_mod._infer_parameters(self._orig_mod, args, kwargs)
        return self._forward(*args, **kwargs)

    def __dir__(self):
        orig_mod_attrs = self._orig_mod.__dir__()
        return orig_mod_attrs + [
            attr for attr in super().__dir__() if attr not in orig_mod_attrs
        ]


def remove_from_cache(f):
    """
    Make sure f.__code__ is not cached to force a recompile
    """
    if isinstance(f, types.CodeType):
        reset_code(f)
    elif hasattr(f, "__code__"):
        reset_code(f.__code__)
    elif hasattr(getattr(f, "forward", None), "__code__"):
        reset_code(f.forward.__code__)
    else:
        from . import reset  # type: ignore[attr-defined]

        reset()
        log.warning("could not determine __code__ for %s", f)


def nothing():
    pass


def always_false():
    return False


def innermost_fn(fn):
    """
    In case of nesting of _TorchDynamoContext calls, find the innermost
    function. TorchDynamo caches on fn.__code__ object, so its necessary to find
    the innermost function to pass on the optimize, run, disable etc.
    """
    unaltered_fn = fn
    while hasattr(unaltered_fn, "_torchdynamo_orig_callable"):
        unaltered_fn = unaltered_fn._torchdynamo_orig_callable
        assert callable(unaltered_fn)
    return unaltered_fn


def make_set_enable_dynamic(enable: bool):
    assert isinstance(enable, bool)
    if enable:
        # Assume everything is dynamic by default
        return config._make_closure_patcher(assume_static_by_default=False)
    else:
        return config._make_closure_patcher(
            automatic_dynamic_shapes=False, assume_static_by_default=True
        )


class _TorchDynamoContext:
    def __init__(
        self,
        callback: DynamoCallback,
        on_enter=nothing,
        backend_ctx_ctor=null_context,
        patch_fn=nothing,
        first_ctx=False,
        *,
        export=False,
        dynamic=None,
        compiler_config=None,
    ):
        super().__init__()
        assert callable(callback) or callback is False or callback is None
        self.callback: DynamoCallback = callback
        self.prior: Union[Unset, DynamoCallback] = unset
        self.first_ctx = first_ctx
        self.export = export
        self.compiler_config = compiler_config
        self.cleanup_fns: List[Callable[[], Any]] = []
        self.enter_exit_hooks = [backend_cache_manager(self.callback)]
        patch_fn()

        if dynamic is not None:
            self.enter_exit_hooks.append(make_set_enable_dynamic(dynamic))

        if on_enter is not nothing:
            # this case is not common
            def call_on_enter():
                on_enter()
                return nothing

            self.enter_exit_hooks.append(call_on_enter)

        if backend_ctx_ctor is not contextlib.nullcontext:
            # this case is not common
            def call_backend_ctx():
                ctx = backend_ctx_ctor()
                ctx.__enter__()
                return functools.partial(ctx.__exit__, None, None, None)

            self.enter_exit_hooks.append(call_backend_ctx)

    def __enter__(self):
        if config.raise_on_ctx_manager_usage:
            raise RuntimeError(
                "torch._dynamo.optimize(...) is used with a context manager. "
                "Please refer to https://pytorch.org/tutorials/intermediate/torch_compile_tutorial.html "
                "to use torch._dynamo.optimize(...) as an annotation/decorator. "
            )
        self.cleanup_fns = [enter() for enter in self.enter_exit_hooks]
        self.prior = set_eval_frame(self.callback)

    def __exit__(self, exc_type, exc_val, exc_tb):
        assert self.prior is not unset
        set_eval_frame(self.prior)
        self.prior = unset
        for cleanup in self.cleanup_fns:
            cleanup()
        self.cleanup_fns.clear()

    def __call__(self, fn):
        # public api for compiler config/options
        def get_compiler_config():
            return self.compiler_config

        fn = innermost_fn(fn)

        # add context containing GraphModule to any GraphModule forward functions
        from torch.fx._lazy_graph_module import _LazyGraphModule

        if isinstance(fn, _LazyGraphModule) or (
            isinstance(getattr(fn, "__self__", None), _LazyGraphModule)
            and fn.__name__ == "_lazy_forward"
        ):
            # Since dynamo will run the forward method for the GraphModule shortly
            # anyways, it does not hurt to do the real recompilation here if
            # this is a _LazyGraphModule. This makes it easier for dynamo to
            # optimize a _LazyGraphModule.

            lazy_gm = fn if isinstance(fn, _LazyGraphModule) else fn.__self__

            _LazyGraphModule.force_recompile(lazy_gm)

            # Assume that the underlying node metadata of `fn`,
            # a GraphModule instance, accurately represents
            # all instances of type(fn).
            code_context.get_context(lazy_gm.forward.__code__)[
                "orig_graphmodule"
            ] = weakref.ref(lazy_gm)

            if not isinstance(fn, _LazyGraphModule):
                # replace fn with the real forward method
                fn = lazy_gm.forward
        elif isinstance(fn, GraphModule):
            code_context.get_context(fn.forward.__code__)[
                "orig_graphmodule"
            ] = weakref.ref(fn)

        # Optimize the forward method of torch.nn.Module object
        if isinstance(fn, torch.nn.Module):
            mod = fn
            new_mod = OptimizedModule(mod, self)
            # Save the function pointer to find the original callable while nesting
            # of decorators.
            new_mod._torchdynamo_orig_callable = mod.forward

            # when compiling torch.nn.Module,
            # provide public api OptimizedModule.get_compiler_config()
            assert not hasattr(new_mod, "get_compiler_config")
            new_mod.get_compiler_config = get_compiler_config

            return new_mod
        assert callable(fn)

        try:
            filename = inspect.getsourcefile(fn)
        except TypeError:
            filename = None
        if (
            (filename is None or trace_rules.check(fn))
            and (
                getattr(fn, "__name__", "") not in ["_call_impl", "_wrapped_call_impl"]
            )
            and filename not in DONT_WRAP_FILES
        ):
            # call to a builtin without a frame for us to capture
            fn = external_utils.wrap_inline(fn)

        callback = self.callback

        if isinstance(self, DisableContext):
            is_jit_tracing = always_false
            is_fx_tracing = always_false
        else:
            is_jit_tracing = torch._C._is_tracing
            is_fx_tracing = torch.fx._symbolic_trace.is_fx_tracing

        @functools.wraps(fn)
        def _fn(*args, **kwargs):
            if is_fx_tracing():
                if config.error_on_nested_fx_trace:
                    raise RuntimeError(
                        "Detected that you are using FX to symbolically trace "
                        "a dynamo-optimized function. This is not supported at the moment."
                    )
                else:
                    return fn(*args, **kwargs)

            if is_jit_tracing():
                if config.error_on_nested_jit_trace:
                    raise RuntimeError(
                        "Detected that you are using FX to torch.jit.trace "
                        "a dynamo-optimized function. This is not supported at the moment."
                    )
                else:
                    return fn(*args, **kwargs)

            cleanups = [enter() for enter in self.enter_exit_hooks]
            prior = set_eval_frame(callback)
            try:
                return fn(*args, **kwargs)
            finally:
                set_eval_frame(prior)
                for cleanup in cleanups:
                    cleanup()

        # hooks to properly handle inlining
        if isinstance(self, DisableContext):
            _fn._torchdynamo_disable = True  # type: ignore[attr-defined]
        else:
            _fn._torchdynamo_inline = fn  # type: ignore[attr-defined]

        # Save the function pointer to find the original callable while nesting
        # of decorators.
        _fn._torchdynamo_orig_callable = fn  # type: ignore[attr-defined]

        # when compiling user function instead of nn.Module
        # provide public api _fn.get_compiler_config()
        assert not hasattr(_fn, "get_compiler_config")
        _fn.get_compiler_config = get_compiler_config  # type: ignore[attr-defined]

        # If the function is called using torch._dynamo.optimize decorator, we
        # should prevent any type of skipping.
        if callback not in (None, False):
            if not hasattr(fn, "__code__"):
                raise RuntimeError(
                    textwrap.dedent(
                        """

                        torch._dynamo.optimize is called on a non function object.
                        If this is a callable class, please wrap the relevant code into a function and optimize the
                        wrapper function.

                        >> class CallableClass:
                        >>     def __init__(self):
                        >>         super().__init__()
                        >>         self.relu = torch.nn.ReLU()
                        >>
                        >>     def __call__(self, x):
                        >>         return self.relu(torch.sin(x))
                        >>
                        >>     def print_hello(self):
                        >>         print("Hello world")
                        >>
                        >> mod = CallableClass()

                        If you want to optimize the __call__ function and other code, wrap that up in a function

                        >> def wrapper_fn(x):
                        >>     y = mod(x)
                        >>     return y.sum()

                        and then optimize the wrapper_fn

                        >> opt_wrapper_fn = torch._dynamo.optimize(wrapper_fn)
                        """
                    )
                )
            always_optimize_code_objects[fn.__code__] = True

        return _fn


class OptimizeContext(_TorchDynamoContext):
    def __init__(
        self,
        callback,
        backend_ctx_ctor,
        first_ctx=False,
        *,
        export=False,
        dynamic=None,
        compiler_config=None,
    ):
        def on_enter():
            install_generation_tagging_init()

        super().__init__(
            callback=callback,
            on_enter=on_enter,
            backend_ctx_ctor=backend_ctx_ctor,
            patch_fn=TorchPatcher.patch,
            first_ctx=first_ctx,
            export=export,
            dynamic=dynamic,
            compiler_config=compiler_config,
        )


class RunOnlyContext(_TorchDynamoContext):
    def __init__(self):
        # cudagraph trees relies on generation increment
        def on_enter():
            torch._dynamo.mutation_guard.GenerationTracker.generation += 1

        super().__init__(callback=False, on_enter=on_enter)


class DisableContext(_TorchDynamoContext):
    def __init__(self):
        super().__init__(callback=None)


def _optimize_catch_errors(
    compile_fn,
    hooks: Hooks,
    backend_ctx_ctor=null_context,
    export=False,
    dynamic=None,
    compiler_config=None,
):
    return OptimizeContext(
        convert_frame.catch_errors_wrapper(compile_fn, hooks),
        backend_ctx_ctor=backend_ctx_ctor,
        first_ctx=True,
        export=export,
        dynamic=dynamic,
        compiler_config=compiler_config,
    )


def get_compiler_fn(compiler_fn):
    from .repro.after_dynamo import wrap_backend_debug

    if hasattr(compiler_fn, "compiler_name"):
        compiler_str = compiler_fn.compiler_name
    elif isinstance(compiler_fn, str):
        compiler_str = compiler_fn
    else:
        compiler_str = None
    compiler_fn = lookup_backend(compiler_fn)
    return wrap_backend_debug(compiler_fn, compiler_str)


class _NullDecorator(contextlib.nullcontext):  # type: ignore[type-arg]
    def __call__(self, fn):
        assert callable(fn)
        return fn


def check_if_dynamo_supported():
    if sys.version_info >= (3, 12):
        raise RuntimeError("Python 3.12+ not yet supported for torch.compile")


def is_dynamo_supported():
    try:
        check_if_dynamo_supported()
        return True
    except Exception:
        return False


def check_if_inductor_supported():
    check_if_dynamo_supported()

    if sys.platform == "win32":
        raise RuntimeError("Windows not yet supported for inductor")


def is_inductor_supported():
    try:
        check_if_inductor_supported()
        return True
    except Exception:
        return False


def optimize(
    backend="inductor",
    *,
    nopython=False,
    guard_export_fn=None,
    guard_fail_fn=None,
    disable=False,
    dynamic=None,
):
    """
    The main entrypoint of TorchDynamo.  Do graph capture and call
    backend() to optimize extracted graphs.

    Args:
        backend: One of the two things:
            - Either, a function/callable taking a torch.fx.GraphModule and
            example_inputs and returning a python callable that runs the
            graph faster.
            One can also provide additional context for the backend, like
            torch.jit.fuser("fuser2"), by setting the backend_ctx_ctor attribute.
            See AOTAutogradMemoryEfficientFusionWithContext for the usage.
            - Or, a string backend name in `torch._dynamo.list_backends()`
        nopython: If True, graph breaks will be errors and there will
            be a single whole-program graph.
        disable: If True, turn this decorator into a no-op
        dynamic: If True, upfront compile as dynamic a kernel as possible.  If False,
            disable all dynamic shapes support (always specialize).  If None, automatically
            detect when sizes vary and generate dynamic kernels upon recompile.

    Example Usage::

        @torch._dynamo.optimize()
        def toy_example(a, b):
            ...
    """
    check_if_dynamo_supported()
    # Note: The hooks object could be global instead of passed around, *however* that would make
    # for a confusing API usage and plumbing story wherein we nest multiple .optimize calls.
    # There is some prior art around this, w/r/t nesting backend calls are enforced to be the same
    # compiler, however, this feels onerous for callback and hooks, and it feels better to give our users an
    # easier to understand UX at the cost of a little more plumbing on our end.
    hooks = Hooks(guard_export_fn=guard_export_fn, guard_fail_fn=guard_fail_fn)
    torch._C._log_api_usage_once("torch._dynamo.optimize")
    if disable or os.environ.get("TORCHDYNAMO_DISABLE", "") == "1":
        return _NullDecorator()

    backend = get_compiler_fn(backend)

    # Find if backend has any extra context manager
    backend_ctx_ctor = getattr(backend, "backend_ctx_ctor", null_context)

    if nopython:
        return optimize_assert(
            backend,
            dynamic=dynamic,
            hooks=hooks,
        )
    return _optimize_catch_errors(
        convert_frame.convert_frame(backend, hooks=hooks),
        hooks,
        backend_ctx_ctor,
        dynamic=dynamic,
        compiler_config=backend.get_compiler_config()
        if hasattr(backend, "get_compiler_config")
        else None,
    )


# TODO(voz): Consider making "explain" output alongside a run / part of a run
@patch("torch._dynamo.symbolic_convert.explain", True)
def explain(f, *extra_args, **extra_kwargs):
    def inner(*args, **kwargs):
        # TODO(voz): Do we want a decorator for this?
        from . import reset  # type: ignore[attr-defined]

        reset()

        graphs: List[torch.fx.GraphModule] = []
        break_reasons: List[Any] = []
        op_count: int = 0
        ops_per_graph: List[torch.fx.Node] = []
        out_guards: List[_guards.Guard] = []

        def dynamo_graph_accumulating_compiler(
            gm: torch.fx.GraphModule, example_inputs
        ):
            from .backends.debugging import _explain_graph_detail

            nonlocal graphs
            nonlocal op_count
            nonlocal ops_per_graph
            nonlocal break_reasons

            gm, graphs, op_count, ops_per_graph, break_reasons = _explain_graph_detail(
                gm, graphs, op_count, ops_per_graph, break_reasons
            )

            return gm.forward

        def guard_export_print(guards):
            nonlocal out_guards
            out_guards.extend(guards)

        opt_f = optimize(
            dynamo_graph_accumulating_compiler,
            nopython=False,
            guard_export_fn=guard_export_print,
        )(f)
        # TODO(voz): We may have instances of `f` that mutate inputs, we should track sideeffects and reject.
        opt_f(*args, **kwargs)

        graph_count = len(graphs)

        # For the explanation summary, dedupe reasons by the innermost stack frame and dedupe by it.
        deduped_reasons = {}
        for reason in break_reasons:
            innermost_frame = reason.user_stack[-1]
            # __repr__ uniquely identifies a FrameSummary so we can use it for deduping
            deduped_reasons[repr(innermost_frame)] = reason

        formatted_list = ""
        for idx, break_reason in enumerate(deduped_reasons.values()):
            formatted_stack = "".join(traceback.format_list(break_reason.user_stack))
            msg = f"{idx + 1}. Reason: {break_reason.reason}\n   User Stack: {formatted_stack}\n"
            formatted_list += msg

        graph_break_count = graph_count - 1
        compile_time = compile_times(repr="str")

        # TODO(voz): Do we want a decorator for this?
        reset()
        from .backends.debugging import ExplainOutput

        return ExplainOutput(
            graphs,
            graph_count,
            graph_break_count,
            break_reasons,
            op_count,
            ops_per_graph,
            out_guards,
            compile_time,
        )

    if extra_args or extra_kwargs:
        warnings.warn(
            "explain(f, *args, **kwargs) is deprecated, use explain(f)(*args, **kwargs) instead.  "
            "If you don't migrate, we may break your explain call in the future if your user defined kwargs "
            "conflict with future kwargs added to explain(f)."
        )
        return inner(*extra_args, **extra_kwargs)
    else:
        return inner


class FlattenInputOutputSignature(torch.fx.interpreter.Transformer):
    def __init__(
        self,
        m: torch.fx.GraphModule,
        flat_args: Tuple[Any],
        matched_input_elements_positions: List[int],
        flat_results: List[Any],
        matched_output_elements_positions: List[int],
        example_fake_inputs: List[torch.Tensor],
        flat_args_dynamic_dims: List[Set[int]],
        fake_mode: Optional[fake_tensor.FakeTensorMode] = None,
    ):
        super().__init__(m)

        assert len(flat_args_dynamic_dims) == len(flat_args)
        matched_input_elements_to_fake = {
            val: example_fake_inputs[ix]
            for ix, val in enumerate(matched_input_elements_positions)
        }

        self.new_args = []
        for i in range(0, len(flat_args)):
            arg = super().placeholder(f"arg{i}", (), {})
            if i in matched_input_elements_to_fake:
                arg.node.meta["val"] = matched_input_elements_to_fake[i]
            else:
                # Fill node.mata["val"] with faketensor from the input,
                # if it's not found in matched_input_elements_positions
                if fake_mode is not None and isinstance(flat_args[i], torch.Tensor):
                    # TODO(zhxchen17) Also preserve all the user constraints here.
                    arg.node.meta["val"] = fake_mode.from_tensor(
                        flat_args[i],
                        symbolic_context=StatelessSymbolicContext(
                            dynamic_sizes=[
                                DimDynamic.DYNAMIC
                                if d in flat_args_dynamic_dims[i]
                                else DimDynamic.STATIC
                                for d in range(len(flat_args[i].shape))
                            ],
                            constraint_sizes=[None] * len(flat_args[i].shape),
                        ),
                    )
            self.new_args.append(arg)
        self.old_args_gen = (self.new_args[i] for i in matched_input_elements_positions)
        self.matched_output_elements_positions = matched_output_elements_positions
        self.flat_results = flat_results

    def placeholder(self, target, args, kwargs):
        arg = next(self.old_args_gen)
        if "val" in self.current_node.meta:
            arg.node.meta["val"] = self.current_node.meta["val"]
        if "tensor_dict" in self.current_node.meta:
            arg.node.meta["tensor_dict"] = self.current_node.meta["tensor_dict"]
        if "example_value" in self.current_node.meta:
            arg.node.meta["example_value"] = self.current_node.meta["example_value"]
        return arg

    def output(self, target, args, kwargs):
        dynamo_result_flat = args[0]
        lookup = [*dynamo_result_flat, *self.new_args]
        new_results_flat = []
        for i in range(len(self.flat_results)):
            if self.matched_output_elements_positions[i] is not None:
                new_results_flat.append(
                    lookup[self.matched_output_elements_positions[i]]
                )
            else:
                const_val = self.flat_results[i]
                assert isinstance(const_val, tuple(common_constant_types))
                new_results_flat.append(const_val)
        return super().output(target, (new_results_flat,), {})

    def run_node(self, n):
        self.current_node = n
        result_proxy = super().run_node(n)
        if "val" in self.current_node.meta:
            result_proxy.node.meta["val"] = self.current_node.meta["val"]
        if "example_value" in self.current_node.meta:
            result_proxy.node.meta["example_value"] = self.current_node.meta[
                "example_value"
            ]
        if self.current_node.op != "output":
            result_proxy.node._rename(
                getattr(self.current_node, "name", result_proxy.node.name)
            )
        return result_proxy

    def transform(self):
        result_gm = super().transform()
        if "dynamo_flat_name_to_original_fqn" in self.module.meta:
            result_gm.meta["dynamo_flat_name_to_original_fqn"] = self.module.meta[
                "dynamo_flat_name_to_original_fqn"
            ]
        return result_gm


class ExportResult(NamedTuple):
    graph_module: torch.fx.GraphModule
    guards: _guards.GuardsSet
    # NB: Do not add new fields without overriding __iter__; people are
    # destructuring so it is BC-breaking


def check_signature_rewritable(graph):
    input_errors = []
    for node in graph.graph.nodes:
        if node.op == "placeholder":
            assert hasattr(node, "_dynamo_source")
            source = node._dynamo_source
            user_stacks = graph._source_to_user_stacks.get(source)
            if user_stacks is None:
                continue
            assert len(user_stacks) > 0
            # In some cases we may not have a useful stack.  Look for a
            # useful stack
            stack = None
            for s in user_stacks:
                if len(s) == 0:
                    continue
                stack = s
                break
            if stack is None:
                msg = f"{source.name()}, a closed over free variable"
            else:
                tb = "".join(traceback.format_list(stack))
                extra = ""
                if len(user_stacks) > 1:
                    extra = f"(elided {len(user_stacks)-1} more accesses)"
                msg = f"{source.name()}, accessed at:\n{tb}{extra}"
            # TODO: option to print ALL of the stack traces at once
            input_errors.append(msg)

    if input_errors:
        raise UserError(
            UserErrorType.INVALID_INPUT,
            "Cannot export model which references tensors that are neither "
            "buffers/parameters/constants nor are direct inputs.  For each tensor, if you'd "
            "like this tensor to be an explicit input, add it as a dummy argument "
            "to the top-level model definition you are exporting; if you would "
            "like its value to be embedded as an exported constant, wrap its access "
            "in a function marked with @assume_constant_result.\n\n"
            + "\n\n".join(input_errors),
        )


def rewrite_signature(
    f_sig,
    graph,
    fake_mode,
    flat_args,
    in_spec,
    example_fake_inputs,
    graph_captured_input,
    graph_captured_output,
    dynamo_traced_result,
    flat_args_dynamic_dims,
):
    orig_args, orig_kwargs = pytree.tree_unflatten(flat_args, in_spec)

    def check_user_input_output(flat_values, error_type):
        supported_types = [
            torch.Tensor,
            torch.SymInt,
            torch.SymFloat,
            torch.SymBool,
            torch._C.ScriptObject,
        ] + list(common_constant_types)

        def is_supported_type(val):
            return isinstance(val, tuple(supported_types))

        value_type = "input" if error_type == UserErrorType.INVALID_INPUT else "output"
        # We only check that the outputs are not None. Inputs can be None.
        for v in flat_values:
            if not is_supported_type(v):
                if error_type == UserErrorType.INVALID_INPUT and v is None:
                    continue

                raise UserError(
                    error_type,
                    f"It looks like one of the {value_type}s with type `{type(v)}` "
                    "is not supported or pytree-flattenable. \n"
                    f"Exported graphs {value_type}s can only contain the "
                    f"following supported types: {supported_types}. \n"
                    "If you are using a custom class object, "
                    "please register a pytree_flatten/unflatten function "
                    "using `torch.utils._pytree.register_pytree_node` or "
                    "`torch.export.register_dataclass`.",
                )

    check_user_input_output(flat_args, UserErrorType.INVALID_INPUT)
    flat_results_traced, out_spec_traced = pytree.tree_flatten(dynamo_traced_result)
    check_user_input_output(flat_results_traced, UserErrorType.INVALID_OUTPUT)

    def produce_matching(debug_type, sources, candidates):
        matched_elements_positions: List[Optional[int]] = []
        dict_of_source_vals = {}
        for i, val in enumerate(sources):
            dict_of_source_vals[id(val)] = i

        for i, val in enumerate(candidates):
            if isinstance(val, tuple(common_constant_types)):
                matched_elements_positions.append(None)
            elif id(val) not in dict_of_source_vals:
                raise AssertionError(
                    f"Unexpectedly found a {type(val)} in the {debug_type}.\n"
                    'Please file an issue along with a paste of the logs from TORCH_LOGS="+export"'
                )
            else:
                matched_elements_positions.append(dict_of_source_vals[id(val)])

        return matched_elements_positions

    matched_input_elements_positions = produce_matching(
        "inputs", flat_args, graph_captured_input
    )

    assert graph_captured_output is not None
    matched_output_elements_positions = produce_matching(
        "outputs", list(graph_captured_output) + flat_args, flat_results_traced
    )

    new_graph = FlattenInputOutputSignature(
        graph,
        flat_args,
        matched_input_elements_positions,
        flat_results_traced,
        matched_output_elements_positions,
        example_fake_inputs,
        flat_args_dynamic_dims,
        fake_mode,
    ).transform()

    # Make dynamo graph to have same input/output spec as user code
    def argument_names(f_sig, args, kwargs) -> List[str]:
        def signature_to_fullargspec(sig: inspect.Signature):
            # Get a list of Parameter objects from the Signature object
            params = list(sig.parameters.values())
            # Separate positional arguments, keyword-only arguments and varargs/varkw
            args = [
                p.name
                for p in params
                if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
            ]
            kwonlyargs = [
                p.name for p in params if p.kind == inspect.Parameter.KEYWORD_ONLY
            ]
            varargs = next(
                (p.name for p in params if p.kind == inspect.Parameter.VAR_POSITIONAL),
                None,
            )
            varkw = next(
                (p.name for p in params if p.kind == inspect.Parameter.VAR_KEYWORD),
                None,
            )
            # Get default values for positional arguments and keyword-only arguments
            defaults = tuple(
                p.default
                for p in params
                if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
                and p.default is not inspect.Parameter.empty
            )
            kwonlydefaults = {
                p.name: p.default
                for p in params
                if p.kind == inspect.Parameter.KEYWORD_ONLY
                and p.default is not inspect.Parameter.empty
            }
            # Get annotations for parameters and return value
            annotations = {}
            if sig.return_annotation:
                annotations = {"return": sig.return_annotation}
            for parameter in params:
                annotations[parameter.name] = parameter.annotation
            # Return a FullArgSpec object with the extracted attributes
            return inspect.FullArgSpec(
                args, varargs, varkw, defaults, kwonlyargs, kwonlydefaults, annotations
            )

        fullargspec = signature_to_fullargspec(f_sig)

        # 1. Map `args` 1-to-1 to positional arguments in original signature.
        input_strs = fullargspec.args[: len(args)]

        if len(args) > len(fullargspec.args):
            # 2. If there are more arguments left in `args`, they map to varargs in original
            # signature. Assign names as {varargs}_0, {varargs}_1, ...
            assert fullargspec.varargs is not None, "More arguments than expected"
            input_strs += [
                f"{fullargspec.varargs}_{i}"
                for i in range(0, len(args) - len(input_strs))
            ]
        elif len(args) < len(fullargspec.args):
            # 3. If there are fewer arguments in `args` than `fullargspec.args`,
            # it implies these are arguments either with default values, or provided in
            # `kwargs`. The former can be safely ignored. Because Dynamo.export does not
            # export them as part of the function signature. The latter will be handled
            # in the next step.
            for unprovided_arg in fullargspec.args[
                len(args) : -len(fullargspec.defaults or [])
            ]:
                assert unprovided_arg in kwargs, f"Missing argument {unprovided_arg}"

        # 4. Keyword arguments provided in `kwargs`.
        input_strs += list(kwargs.keys())

        # 5. Keyword-only arguments with default values if not provided are not exported
        # as part of the function signature.
        for kwonly_arg in fullargspec.kwonlyargs:
            kwonlydefaults = fullargspec.kwonlydefaults or {}
            assert (
                kwonly_arg in kwargs or kwonly_arg in kwonlydefaults
            ), f"Missing keyword only argument {kwonly_arg}"

        return input_strs

    new_graph.graph._codegen = _PyTreeCodeGen(
        _PyTreeInfo(
            argument_names(f_sig, orig_args, orig_kwargs),
            in_spec,
            out_spec_traced,
        )
    )
    new_graph.recompile()
    return new_graph


def export(
    f: Callable[..., Any],
    *extra_args,
    aten_graph: bool = False,
    pre_dispatch: bool = False,
    decomposition_table: Optional[
        Dict[torch._ops.OpOverload, Callable[..., Any]]
    ] = None,
    tracing_mode: str = "symbolic",
    constraints: Optional[List[Constraint]] = None,
    dynamic_shapes: Optional[Union[Dict[str, Any], Tuple[Any], List[Any]]] = None,
    assume_static_by_default: bool = False,
    same_signature: bool = True,
    disable_constraint_solver: bool = False,
    _log_export_usage: bool = True,
    **extra_kwargs,
) -> Callable[..., ExportResult]:
    """
    Export an input function f to a format that can be executed outside of PyTorch using the FX graph.

    Args:
        f (callable): A PyTorch function to be exported.

        aten_graph (bool): If True, exports a graph with ATen operators.
        If False, exports a graph with Python operators. Default is False.

        pre_dispatch (bool): If True, exports a graph with ATen operators,
        but before any logic in the PyTorch dispatcher has run.
        This can be useful if you want to apply further transformations on a graph before running it
        through autograd, autocast, or any other functionalities that are integrated into the dispatcher.
        This flag is only valid if aten_graph=True is set.
        Default is False.

        decomposition_table (dict): A dictionary that maps operators to their decomposition functions.
        Required if aten_graph or tracing_mode is specified. Default is None.

        tracing_mode (str): If "symbolic", turn on dynamic shapes support. Default is "symbolic".

        constraints: [DEPRECATED: use ``dynamic_shapes`` instead, see below]
         An optional list of constraints on the dynamic arguments
         that specify their possible range of shapes. By default, shapes of
         input torch.Tensors are assumed to be static. If an input torch.Tensor
         is expected to have dynamic shapes, please use :func:`dynamic_dim`
         to define :class:`Constraint` objects that specify the dynamics and the possible
         range of shapes. See :func:`dynamic_dim` docstring for examples on
         how to use it.

        dynamic_shapes:
         An optional argument where the type should either be:
         1) a dict from argument names of ``f`` to their dynamic shape specifications,
         2) a tuple that specifies dynamic shape specifications for each input in original order.
         If you are specifying dynamism on keyword args, you will need to pass them in the order that
         is defined in the original function signature.

         The dynamic shape of a tensor argument can be specified as either
         (1) a dict from dynamic dimension indices to :func:`Dim` types, where it is
         not required to include static dimension indices in this dict, but when they are,
         they should be mapped to None; or (2) a tuple / list of :func:`Dim` types or None,
         where the :func:`Dim` types correspond to dynamic dimensions, and static dimensions
         are denoted by None. Arguments that are dicts or tuples / lists of tensors are
         recursively specified by using mappings or sequences of contained specifications.

        same_signature (bool): If True, rewrite the returned graph's signature to be the same as f.

        disable_constraint_solver (bool): Whether the dim constraint solver must be disabled.

    Returns:
        A function that given args and kwargs, returns a tuple of (graph, guards)
        Graph: An FX graph representing the execution of the input PyTorch function with the provided arguments and options.
        Guards: The guards we accumulated during tracing f above

    Raises:
        AssertionError: If decomposition_table is specified without setting aten_graph=True,
        or if graph breaks during tracing in export.

        AssertionError: If Dynamo input and output is not consistent with traced input/output.

    Note - this headerdoc was authored by ChatGPT, with slight modifications by the author.
    """
    if _log_export_usage:
        log_export_usage(event="export.private_api", flags={"_dynamo"})

    # Deal with "local variable referenced before assignment"
    _f = f
    _assume_static_by_default = assume_static_by_default

    def inner(*args, **kwargs):
        nonlocal constraints
        if constraints is not None:
            if _log_export_usage:
                warnings.warn(
                    "Using `constraints` to specify dynamic shapes for export is DEPRECATED "
                    "and will not be supported in the future. "
                    "Please use `dynamic_shapes` instead (see docs on `torch.export.export`).",
                    DeprecationWarning,
                    stacklevel=2,
                )
        else:
            constraints = _process_dynamic_shapes(_f, args, kwargs, dynamic_shapes)
        f = _f
        assume_static_by_default = _assume_static_by_default
        check_if_dynamo_supported()
        torch._C._log_api_usage_once("torch._dynamo.export")
        if decomposition_table is not None:
            assert (
                aten_graph
            ), "Specifying a decomposition_table table or tracing mode is illegal without setting aten_graph=True"
        if pre_dispatch:
            assert aten_graph, "pre_dispatch=True can only be used when aten_graph=True"
        f = innermost_fn(f)
        call_to_inspect = f.forward if isinstance(f, torch.nn.Module) else f
        original_signature = inspect.signature(call_to_inspect)
        graph = None
        out_guards = None
        graph_captured_input = None
        graph_captured_result: Optional[Tuple[torch.Tensor, ...]] = None
        fake_mode = None

        def guard_export_print(guards: _guards.GuardsSet):
            nonlocal out_guards
            assert (
                out_guards is None
            ), "whole graph export entails exactly one guard export"
            out_guards = guards

        example_inputs = []

        def dynamo_normalization_capturing_compiler(
            gm: torch.fx.GraphModule, inner_example_inputs
        ):
            nonlocal graph
            assert (
                graph is None
            ), "Tried to emit a second graph during export. Tracing through 'f' must produce a single graph."
            graph = gm

            nonlocal fake_mode, example_inputs
            # NB: do NOT pass inner_example_inputs here, we are detecting the
            # Dynamo allocated fake mode, which should be DISTINCT from a
            # potential outer ambient fake mode which the user provided.
            # example_inputs is always the user specified inputs, so they
            # would have the wrong fake mode attached to them
            fake_mode = _guards.detect_fake_mode()
            example_inputs = inner_example_inputs

            def result_capturing_wrapper(*graph_inputs):
                nonlocal graph_captured_result
                nonlocal graph_captured_input

                graph_captured_input = graph_inputs
                assert graph is not None

                named_parameters = dict(graph.named_parameters(remove_duplicate=False))
                named_buffers = dict(graph.named_buffers(remove_duplicate=False))

                ambient_fake_mode = (
                    _guards.detect_fake_mode(graph_inputs)
                    if _guards.detect_fake_mode(graph_inputs) is not None
                    else fake_mode
                )

                with ambient_fake_mode, enable_python_dispatcher():
                    params_and_buffers = {
                        **named_parameters,
                        **named_buffers,
                    }
                    fake_params_buffers = dict()

                    for name, value in params_and_buffers.items():
                        fake_params_buffers[name] = ambient_fake_mode.from_tensor(
                            value, static_shapes=True
                        )

                    fake_graph_inputs = pytree.tree_map(
                        ambient_fake_mode.from_tensor, graph_inputs
                    )
                    graph_captured_result = torch.func.functional_call(
                        graph, fake_params_buffers, fake_graph_inputs
                    )

                return graph_captured_result

            return result_capturing_wrapper

        # Note: This is needed by rewrite_signature. We need to put it before
        # optimize_assert since user program may mutate the inputs.
        flat_args, in_spec = pytree.tree_flatten((args, kwargs))

        remove_from_cache(f)
        constraint_violation_error = None
        if tracing_mode != "symbolic":
            assume_static_by_default = True
        with config.patch(
            specialize_int=True,
            assume_static_by_default=assume_static_by_default,
            automatic_dynamic_shapes=False,
            capture_dynamic_output_shape_ops=True,
            capture_scalar_outputs=True,
        ):
            opt_f = optimize_assert(
                dynamo_normalization_capturing_compiler,
                hooks=Hooks(
                    guard_export_fn=guard_export_print,
                    guard_fail_fn=None,
                ),
                export=True,
                export_constraints=constraints,
            )(f)
            # TODO(voz): We may have instances of `f` that mutate inputs, we should track sideeffects and reject.
            try:
                result_traced = opt_f(*args, **kwargs)
            except ConstraintViolationError as e:
                constraint_violation_error = e
        remove_from_cache(f)

        if (
            not disable_constraint_solver
            and (shape_env := getattr(fake_mode, "shape_env", None)) is not None
            and (dim_constraints := shape_env.dim_constraints) is not None
            and not isinstance(
                call_to_inspect, (torch._ops.OpOverloadPacket, torch._ops.OpOverload)
            )
            and not trace_rules.check(call_to_inspect)
        ):
            dim_constraints.solve()
            dim_constraints.remove_redundant_dynamic_results()
            forced_specializations = dim_constraints.forced_specializations()
            msg = dim_constraints.prettify_results(
                original_signature, constraint_violation_error, forced_specializations
            )
            if constraint_violation_error:
                constraint_violation_error.args = (
                    constraint_violation_error.args[0] + msg,
                )
            else:
                if forced_specializations:
                    constraint_violation_error = ConstraintViolationError(msg)
                else:
                    log.info(
                        "Summary of dimension constraints:%s",
                        msg,
                    )

            # Error if we have any constraints on static values
            for k in shape_env.var_to_range.keys():
                if isinstance(k, sympy.Integer):
                    constraint_violation_error = ConstraintViolationError(
                        f"{''.join(traceback.format_list(shape_env.var_to_stack[k]))}\n"
                        "It appears that you're trying to set a constraint on a "
                        f"value which we evaluated to have a static value of {k}. "
                        'Set TORCH_LOGS="+export" for more information.'
                    )
        if constraint_violation_error:
            raise constraint_violation_error

        assert (
            graph is not None
        ), "Failed to produce a graph during tracing as no tensor operations were found."
        assert hasattr(graph, "_source_to_user_stacks")
        assert out_guards is not None, "Failed to produce guards during tracing"
        assert fake_mode is not None

        log.info(
            "Dynamo captured graph:\n\n%s", graph.print_readable(print_output=False)
        )

        # This check need to happened before aten_graph
        # because placeholder's _source_node attribute is not preserved by make_fx
        if same_signature:
            check_signature_rewritable(graph)

        # NB: This is mostly hitting the cache; Dynamo already converted these
        example_fake_inputs = [fake_mode.from_tensor(t) for t in example_inputs]

        if aten_graph:
            # Running graph with interpreter is needed for propagating the stack_trace
            def graph_with_interpreter(*args):
                with torch.fx.traceback.preserve_node_meta():
                    return torch.fx.Interpreter(graph).run(*args)

            with maybe_disable_fake_tensor_mode(), enable_python_dispatcher(), (
                fake_mode
            ):
                try:
                    graph = make_fx(
                        graph_with_interpreter,
                        decomposition_table=decomposition_table,
                        tracing_mode="real",
                        _allow_non_fake_inputs=True,
                        pre_dispatch=pre_dispatch,
                        _allow_fake_constant=False,
                    )(*example_fake_inputs)
                except CondOpArgsMismatchError as e:
                    # Wrap the internal error to the user-facing error
                    raise UserError(  # noqa: TRY200
                        UserErrorType.DYNAMIC_CONTROL_FLOW,
                        str(e),
                        case_name="cond_operands",
                    )

            assert graph is not None
            for node in graph.graph.nodes:
                if node.op == "get_attr" and isinstance(
                    getattr(graph, node.target), torch.Tensor
                ):
                    node.meta["val"] = fake_mode.from_tensor(
                        getattr(graph, node.target), static_shapes=True
                    )

        if same_signature:
            flat_args_dynamic_dims = [
                {c.dim for c in (constraints or ()) if c.w_tensor() is x}
                for x in flat_args
            ]
            graph = rewrite_signature(
                original_signature,
                graph,
                fake_mode,
                flat_args,
                in_spec,
                example_fake_inputs,
                graph_captured_input,
                graph_captured_result,
                result_traced,  # type: ignore[possibly-undefined]
                flat_args_dynamic_dims,
            )
        # Store constraints and inputs as metadata for user passes, e.g. turn constraints to runtime check
        assert graph is not None
        graph.meta["input_shape_constraints"] = (
            [constraint.serializable_spec for constraint in constraints]
            if constraints
            else []
        )

        return ExportResult(graph, out_guards)

    if extra_args or extra_kwargs:
        warnings.warn(
            "export(f, *args, **kwargs) is deprecated, use export(f)(*args, **kwargs) instead.  "
            "If you don't migrate, we may break your export call in the future if your user defined kwargs "
            "conflict with future kwargs added to export(f)."
        )
        return inner(*extra_args, **extra_kwargs)
    else:
        return inner


def optimize_assert(
    backend,
    *,
    hooks=Hooks(None, None),
    export=False,
    export_constraints=None,
    dynamic=None,
):
    """
    The same as `torch._dynamo.optimize(backend, nopython=True)`
    """
    backend = get_compiler_fn(backend)

    # Find if backend has any extra context manager
    backend_ctx_ctor = getattr(backend, "backend_ctx_ctor", null_context)

    return _optimize_catch_errors(
        convert_frame.convert_frame_assert(
            backend, export=export, export_constraints=export_constraints
        ),
        hooks,
        backend_ctx_ctor,
        export=export,
        dynamic=dynamic,
    )


class TorchPatcher:
    @staticmethod
    @functools.lru_cache(None)
    def patch():
        # A better way to disable the following would be decorate the source
        # functions with @torch._disable_dynamo. However, this causes issues
        # with torch.deploy internally.
        from .decorators import disable

        torch.jit.trace = disable(torch.jit.trace)
        torch.jit.trace_module = disable(torch.jit.trace_module)
        torch.jit._get_trace_graph = disable(torch.jit._get_trace_graph)
        torch.fx._symbolic_trace.Tracer.trace = disable(
            torch.fx._symbolic_trace.Tracer.trace
        )
        torch.distributions.Distribution.set_default_validate_args(False)

        from ..optim import (
            adadelta,
            adagrad,
            adam,
            adamax,
            adamw,
            asgd,
            lbfgs,
            nadam,
            radam,
            rmsprop,
            rprop,
            sgd,
            sparse_adam,
        )

        optimizer_modules = {
            adadelta,
            adagrad,
            adam,
            adamax,
            adamw,
            asgd,
            lbfgs,
            nadam,
            radam,
            rmsprop,
            rprop,
            sgd,
            sparse_adam,
        }

        for opt_mod in optimizer_modules:
            opt_name = opt_mod.__name__.split(".")[-1]
            fused_fn_name = f"_fused_{opt_name}"
            single_tensor_fn_name = f"_single_tensor_{opt_name}"

            if hasattr(opt_mod, fused_fn_name):
                setattr(
                    opt_mod, fused_fn_name, disable(getattr(opt_mod, fused_fn_name))
                )

        optimizer_classes = [
            opt
            for opt in torch.optim.__dict__.values()
            if inspect.isclass(opt) and issubclass(opt, torch.optim.Optimizer)
        ]

        # Note: we don't support sparsity or tracing through backwards
        excluded_optimizer_classes = {
            torch.optim.SparseAdam,
            torch.optim.LBFGS,
        }

        for opt in optimizer_classes:
            if opt in excluded_optimizer_classes:
                opt.step = disable(opt.step)

            if hasattr(opt, "_init_group"):
                opt._init_group = disable(opt._init_group)

    @staticmethod
    def suppress_torch_distributed_warnings(fn):
        def inner_fn(*args, **kwargs):
            warnings.filterwarnings(
                "ignore", category=UserWarning, module="torch.distributed"
            )
            return fn(*args, **kwargs)

        return inner_fn
