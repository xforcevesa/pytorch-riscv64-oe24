import collections
import contextlib
import copy
import functools
import itertools
import logging
import operator
import re
import sys
import traceback
import weakref
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set, Tuple, Union

import sympy

import torch._guards

import torch._logging

import torch.nn
import torch.utils._pytree as pytree
from torch import fx
from torch._guards import (
    Checkpointable,
    GlobalContextCheckpointState,
    GuardsCheckpointState,
    Source,
    TracingContext,
)
from torch._utils_internal import signpost_event
from torch.fx._lazy_graph_module import _make_graph_module  # type: ignore[attr-defined]
from torch.fx.experimental._backward_state import BackwardState
from torch.fx.experimental.sym_node import SymNode
from torch.fx.experimental.symbolic_shapes import free_symbols, is_symbolic, ShapeEnv
from torch.utils._python_dispatch import is_traceable_wrapper_subclass
from torch.utils._sympy.interp import sympy_interp
from torch.utils._sympy.reference import PythonReferenceAnalysis
from torch.utils.weak import WeakTensorKeyDictionary

from . import config, logging as torchdynamo_logging, variables
from .backends.registry import CompiledFn, CompilerFn
from .bytecode_transformation import (
    create_call_function,
    create_instruction,
    Instruction,
    unique_id,
)
from .code_context import code_context
from .codegen import PyCodegen
from .current_scope_id import enter_new_scope
from .exc import (
    BackendCompilerFailed,
    exceptions_allowed_to_be_fallback,
    SkipFrame,
    unimplemented,
    unimplemented_with_warning,
)
from .guards import GuardBuilder, install_guard
from .mutation_guard import is_dynamic_nn_module
from .side_effects import SideEffects
from .source import (
    AttrSource,
    BackwardStateSource,
    ConstantSource,
    GlobalStateSource,
    is_constant_source,
    is_from_local_source,
    LocalSource,
    ParamBufferSource,
    ShapeEnvSource,
    TensorProperty,
    TensorPropertySource,
)
from .utils import (
    checkpoint_params,
    CleanupHook,
    clone_inputs,
    count_calls,
    counters,
    dynamo_timed,
    get_instruction_source_311,
    get_static_address_type,
    graph_break_reasons,
    increment_op_count,
    lazy_format_graph_code,
    lazy_format_graph_tabular,
    LazyString,
    same,
)
from .variables.base import VariableTracker
from .variables.builder import (
    BackwardStateGraphArg,
    GraphArg,
    TrackedFake,
    VariableBuilder,
    wrap_fx_proxy,
)
from .variables.nn_module import NNModuleVariable
from .variables.tensor import (
    NumpyNdarrayVariable,
    SymNodeVariable,
    TensorVariable,
    UnspecializedPythonVariable,
)

from .variables.torch_function import TensorWithTFOverrideVariable

log = logging.getLogger(__name__)
graph_tabular_log = torch._logging.getArtifactLogger(__name__, "graph")
graph_code_log = torch._logging.getArtifactLogger(__name__, "graph_code")
graph_sizes_log = torch._logging.getArtifactLogger(__name__, "graph_sizes")
trace_call_log = torch._logging.getArtifactLogger(__name__, "trace_call")


class OutputGraphState(NamedTuple):
    input_source_to_var: Dict[Source, VariableTracker]
    tracked_fakes: List[TrackedFake]
    guard_state: GuardsCheckpointState
    nn_modules: Optional[Dict[str, torch.nn.Module]]
    register_finalizer_fns: List[Callable[[fx.GraphModule], None]]
    global_state: Optional[Dict[str, bool]]
    param_name_to_source: Optional[Dict[str, Source]]
    side_effects: SideEffects
    timestamp: int
    non_compliant_ops: Set[torch._ops.OpOverload]
    compliant_custom_ops: Set[torch._ops.OpOverload]

    def diff(self, other: "OutputGraphState", *, prefix: str = "") -> Optional[str]:
        for k in self._fields:
            if k == "guard_state":
                r = self.guard_state.diff(other.guard_state)
                if r is not None:
                    return r
                continue
            elif k == "side_effects":
                r = self.side_effects.diff(other.side_effects)
                if r is not None:
                    return r
                continue

            sv = getattr(self, k)
            ov = getattr(other, k)
            if sv != ov:
                return f"{prefix}{k} mismatch: {sv} != {ov}"
        return None

    # Back compat .guards api
    @property
    def guards(self):
        return self.guard_state.dynamo_guards


@functools.lru_cache(None)
def _step_logger():
    return torchdynamo_logging.get_step_logger(log)


@dataclass
class GraphCompileReason:
    """Stores why a given output graph was compiled; i.e. what caused the graph break."""

    reason: str
    user_stack: List[traceback.FrameSummary]

    # Indicates if this was a graph compile reason due to graph break.
    graph_break: bool = True

    def __post_init__(self):
        if self.graph_break:
            graph_break_reasons.append(self)


def _get_gen_rand_values_fn(random_calls):
    def _gen_rand_values():
        return [fn(*args, **kwargs) for fn, args, kwargs in random_calls]

    return _gen_rand_values


class FakeRootModule(torch.nn.Module):
    """Trick the constructor of fx.GraphModule"""

    def __init__(self, nn_modules: Dict[str, torch.nn.Module]):
        super().__init__()
        for k, v in nn_modules.items():
            setattr(self, k, v)

    def __repr__(self):
        return "FakeRootModule(...)"


class WrapperBackend:
    def __init__(self, backend: CompilerFn):
        self.backend: CompilerFn = backend

    def __call__(self, gm: torch.fx.GraphModule, example_inputs: List[torch.Tensor]):
        self.restore = checkpoint_params(gm)
        self.gm = gm
        copy_gm = copy.deepcopy(self.gm)
        self.candidate = self.backend(copy_gm, example_inputs)

        if self.candidate is None or self.candidate is self.gm.forward:
            return self.gm.forward

        if not config.verify_correctness:
            return self.candidate

        # if verify_correctness=True
        try:
            correct = self.gm.forward(*clone_inputs(example_inputs))
            result = self.candidate(*clone_inputs(example_inputs))

            # TODO: replace `same` function with the one in testing
            if same(correct, result):
                return self.candidate

            raise RuntimeError(f"incorrect results of backend {self}")
            return self.gm.forward

        except Exception:
            log.exception("error in verify_correctness")
            raise
        finally:
            self.restore()


Scope = Dict[str, object]


class OutputGraph(Checkpointable[OutputGraphState]):
    """
    Wrapper class to hold outputs of InstructionTranslator.  Mainly the
    generated fx.Graph.

    OutputGraph is 1:1 with a frame being processed. Each frame is associated
    with some root InstructionTranslator. When user code calls a function,
    we construct a InliningInstructionTranslator that continues to write into
    the root InstructionTranslator's OutputGraph.
    """

    def __init__(
        self,
        code_options: Dict[str, Any],
        compiler_fn: Optional[CompilerFn],
        root_tx,
        export: bool,
        export_constraints,
        frame_state,
        local_scope: Scope,
        global_scope: Scope,
        f_code,
    ):
        super().__init__()
        self.tracers = [SubgraphTracer(self, export_root=export)]
        # Map from graph input's `Source` to its `VariableTracker` to
        # de-duplicate graph inputs by source and reuse the tracker
        self.input_source_to_var: Dict[Source, VariableTracker] = {}
        self.export = export
        self.export_constraints = export_constraints
        self.frame_state = frame_state
        self.tensor_weakref_to_sizes_strides = WeakTensorKeyDictionary()
        self.cleanup_hooks: List[Callable[[], Any]] = []
        # compile_id is an id number for the current torch.compile
        self.compile_id: int = next(_compile_id_counter)
        # Set of globals installed via install_global* APIs
        self.installed_globals: Set[str] = set()

        # TODO: maybe should just pass the entire f_code in here?  Not
        # sure...
        self.co_fields = {
            "co_name": f_code.co_name,
            "co_filename": f_code.co_filename,
            "co_firstlineno": f_code.co_firstlineno,
        }

        # tracked_fakes says where any tensor that was wrapped to fake came
        # from.  It is similar to GraphArg, in that all GraphArgs will get
        # will get added to TrackedFakes, but TrackedFakes also contains
        # GraphArgs that got pruned, and things like Tensor attributes which
        # aren't explicit graph inputs.  Used by shape guard
        self.tracked_fakes: List[TrackedFake] = []

        # List of symbols for which we have exact bindings in the arguments
        # already
        self.bound_symbols: Set[sympy.Symbol] = set()

        shape_env = ShapeEnv(
            # Reference Cycle!
            # Share a reference to the list of TrackedFake.
            #
            # ShapeEnv needs this in order to be able to reproduce the call
            # to produce_guards at an arbitrary time point. That is because
            # TrackedFake instances may have its metadata changed throughout
            # the program execution.
            tracked_fakes=self.tracked_fakes,
            allow_scalar_outputs=config.capture_scalar_outputs,
            allow_dynamic_output_shape_ops=config.capture_dynamic_output_shape_ops,
            co_fields=self.co_fields,
        )

        # In export mode, we force the shape_env to strictly disallow any constraining
        # of the user marked dynamic dims
        fake_mode = torch._subclasses.FakeTensorMode(
            shape_env=shape_env,
            # TODO (tmanlaibaatar) Remove this once we always lift params and buffers
            allow_non_fake_inputs=True if self.export else False,
        )
        self.tracing_context: TracingContext = TracingContext(fake_mode)
        self.init_ambient_guards()

        # Map each tensor id to a list of sources. This is necessary because
        # tensor ids cannot be recovered from tracked fakes (in general).
        # We use this map to interpret (i.e., check for violations of) constraints,
        # specifically equality constraints, which have shared tensor ids in them.
        # This map should also be generally useful, e.g., for (de)serialization.
        self.tracked_fakes_id_to_source: Dict[
            int, List[Source]
        ] = collections.defaultdict(list)
        # Stores the full fqn of a param or buffer to the relevant source.
        self.param_name_to_source: Optional[Dict[str, Source]] = dict()
        self.side_effects = SideEffects()
        self.code_options = dict(code_options)
        self.output_instructions: List[Instruction] = []
        # used to track nodes that are added between calls of copy_graphstate
        # and restore_graphstate
        self.timestamp = 0

        # A list of register_finalizer_fns to apply to the output graph module
        self.register_finalizer_fns: List[Callable[[fx.GraphModule], None]] = []

        # Not checkpointed
        self.compiler_fn: Optional[CompilerFn] = compiler_fn
        self.global_scope = global_scope
        self.local_scope = local_scope
        self.root_tx = root_tx
        from torch._dynamo.symbolic_convert import InstructionTranslatorBase

        # Given a source, what are the user stacks of all locations that
        # accessed it?
        #
        # For efficiency, we only populate this:
        #   - During export, and
        #   - If the source could potentially lead to a spurious export input
        #
        # Feel free to populate this more frequently if other use-cases arise,
        # but be aware that we have to generate full stacks for each
        # recording!
        self.source_to_user_stacks: Dict[Source, List[traceback.StackSummary]] = {}

        self._current_tx: List[InstructionTranslatorBase] = []
        self.cleanups: List[CleanupHook] = []
        self.should_exit = False
        self.unspec_variable_map: Dict[str, UnspecializedPythonVariable] = {}
        self.torch_function_enabled = torch._C._is_torch_function_enabled()
        # Tracks if the output graph has a user defined allowed function in the
        # graph. This is used later to determine if we should fallback to eager
        # for certain exceptions. THe idea is that if the user has applied
        # allow_in_graph, they would like to see the error instead of falling
        # back for backend errors.
        self.has_user_defined_allowed_in_graph = False

        # Tracks a list of called ops that were not tagged with "pt2_compliant_tag".
        # This information is useful for logging.
        self.non_compliant_ops: Set[torch._ops.OpOverload] = set({})

        # Tracks a list of called custom ops that were tagged with "pt2_compliant_tag".
        # This information is useful for logging.
        self.compliant_custom_ops: Set[torch._ops.OpOverload] = set({})

        # We save the global torch state here to be restored in case of graph
        # breaks. The relevant issue is seen here
        # https://github.com/pytorch/pytorch/pull/100570#issuecomment-1543427086
        # where inlining of a function changes the global state (because of the
        # presence of torch.no_grad) and there is a graph break.
        self.save_global_state()

        # Tracks the original FQNs of the constant tensors from the original graph,
        # i.e. buffers and parameters.
        self.dynamo_flat_name_to_original_fqn: Dict[str, str] = {}

        # All calls to random() are replaced with a single call to __gen_rand_values
        # functions that returns a tuple of random values for each original call.
        # random_calls tracks calls to random() and random_values_var stores the name of
        # the variable that stores __gen_rand_values results.
        self.random_calls: List[
            Tuple[Callable[..., object], Tuple[object, ...], Dict[str, object]]
        ] = []
        self.random_values_var = None

        # Bytecode to insert right before we call the graph
        self.pregraph_bytecode: List[Instruction] = []

        # Use to pass values to backward hooks when using compiled autograd
        self.backward_state: Dict[str, VariableTracker] = {}
        self.backward_state_proxy: Optional[torch.fx.Proxy] = None
        self.backward_state_var: Optional[str] = None

    def add_backward_state_hook(self, hook: VariableTracker):
        name = f"hook{len(self.backward_state)}"
        assert name not in self.backward_state
        self.backward_state[name] = hook
        return name, self.get_backward_state_proxy()

    def get_backward_state_proxy(self):
        if self.backward_state_proxy is None:
            if self.export:
                unimplemented("backward_state does not support export")
            self.backward_state_proxy = self.root_tracer.create_graph_input(
                "dynamo_backward_state", BackwardState, source=BackwardStateSource()
            )
            self.backward_state_proxy.node.meta["grapharg"] = BackwardStateGraphArg()
            self.backward_state_proxy.node.meta["example_value"] = BackwardState()
            self.backward_state_var = self.new_var()
        return self.backward_state_proxy

    # This gets its own helper function so guards DEBUG logs are more informative
    def init_ambient_guards(self):
        # Register a SHAPE_ENV guard to make sure we setup shape guards
        # that show up in ShapeEnv
        self.guards.add(ShapeEnvSource().make_guard(GuardBuilder.SHAPE_ENV))

        self.guards.add(
            GlobalStateSource().make_guard(GuardBuilder.DETERMINISTIC_ALGORITHMS)
        )

        self.guards.add(GlobalStateSource().make_guard(GuardBuilder.GRAD_MODE))

        self.guards.add(GlobalStateSource().make_guard(GuardBuilder.DEFAULT_DEVICE))

        self.guards.add(
            GlobalStateSource().make_guard(GuardBuilder.TORCH_FUNCTION_STATE)
        )

        self.guards.add(GlobalStateSource().make_guard(GuardBuilder.BACKEND_MATCH))

    def add_cleanup_hook(self, fn: Callable[[], Any]):
        self.cleanup_hooks.append(fn)

    def call_cleanup_hooks(self):
        for hook in reversed(self.cleanup_hooks):
            hook()
        self.cleanup_hooks.clear()

    @property
    def root_tracer(self):
        return self.tracers[0]

    @property
    def current_tracer(self):
        return self.tracers[-1]

    def is_root_tracer(self):
        # Helper to tell if we are inside the higher order operator tracing.
        return len(self.tracers) == 1

    @property
    def graph(self):
        return self.current_tracer.graph

    # TODO(rzou): can delete after we refactor speculate_subgraph to use nested GraphTracer.
    @graph.setter
    def graph(self, value):
        self.current_tracer.graph = value

    @property
    def input_name_to_proxy(self):
        return self.current_tracer.input_name_to_proxy

    @property
    def real_value_cache(self):
        return self.current_tracer.real_value_cache

    # If you are here, and you're looking for create_graph_input,
    # to avoid ambiguity, please call one of the following:
    # - self.current_tracer.create_graph_input
    # - self.root_tracer.create_graph_input
    # See NOTE [HigherOrderOperator tracing design] for more context.

    def create_proxy(self, *args, **kwargs):
        return self.current_tracer.create_proxy(*args, **kwargs)

    def create_node(self, *args, **kwargs):
        return self.current_tracer.create_node(*args, **kwargs)

    def remove_node(self, *args, **kwargs):
        return self.current_tracer.remove_node(*args, **kwargs)

    @contextlib.contextmanager
    def subtracer(self, source_target, prior_tracer):
        new_scope_ctx = enter_new_scope()
        try:
            if prior_tracer:
                # Lineage MUST stay preserved
                assert prior_tracer.parent is self.current_tracer
            new_scope_ctx.__enter__()
            tracer = (
                prior_tracer
                if prior_tracer
                else SubgraphTracer(
                    self, parent=self.current_tracer, source_target=source_target
                )
            )
            self.tracers.append(tracer)
            yield tracer
        finally:
            new_scope_ctx.__exit__(None, None, None)
            self.tracers.pop()

    @property
    def output(self):
        return self

    @property
    def fake_mode(self):
        return self.tracing_context.fake_mode

    @property
    def shape_env(self):
        return self.tracing_context.fake_mode.shape_env

    @property
    def guards(self) -> torch._guards.GuardsSet:
        return self.tracing_context.guards_context.dynamo_guards

    @property
    def nn_modules(self) -> Dict[str, Any]:
        return self.tracing_context.module_context.nn_modules

    def save_global_state(self, out=None):
        """
        Saves to out if it is provided. Else saves to the tracing context's global_state.
        """
        global_state = (
            out if out is not None else self.tracing_context.global_context.global_state
        )

        # TODO - Consider having a torch level API for torch_function_state. As
        # of now, we create a ref cycle by passing the
        # output.set_torch_function_state to
        # output.tracing_context.global_context.global_state. In the interim,
        # the problem can be solved by manually set
        # output.tracing_context.global_context.global_state to None at cleanup.
        global_state["torch_function_enabled"] = (
            self.set_torch_function_state,
            self.torch_function_enabled,
        )
        global_state["grad_enabled"] = (torch.set_grad_enabled, torch.is_grad_enabled())
        global_state["autocast_enabled"] = (
            torch.set_autocast_enabled,
            torch.is_autocast_enabled(),
        )
        global_state["autocast_cpu_enabled"] = (
            torch.set_autocast_cpu_enabled,
            torch.is_autocast_cpu_enabled(),
        )
        global_state["autocast_gpu_dtype"] = (
            torch.set_autocast_gpu_dtype,
            torch.get_autocast_gpu_dtype(),
        )
        global_state["autocast_cpu_dtype"] = (
            torch.set_autocast_cpu_dtype,
            torch.get_autocast_cpu_dtype(),
        )
        global_state["autocast_cache_enabled"] = (
            torch.set_autocast_cache_enabled,
            torch.is_autocast_cache_enabled(),
        )

    def push_tx(self, tx):
        self._current_tx.append(tx)

    def pop_tx(self):
        return self._current_tx.pop()

    @property
    def current_tx(self):
        return self.root_tx if not self._current_tx else self._current_tx[-1]

    def copy_graphstate(self) -> OutputGraphState:
        """Create a checkpoint of the current state by copying everything"""
        assert self.param_name_to_source is not None
        guards_graph_state = self.tracing_context.guards_context.copy_graphstate()
        module_state = self.tracing_context.module_context.copy_graphstate()
        global_state = self.tracing_context.global_context.copy_graphstate()
        state = OutputGraphState(
            dict(self.input_source_to_var),
            list(self.tracked_fakes),
            guards_graph_state,
            module_state,
            list(self.register_finalizer_fns),
            global_state,
            dict(self.param_name_to_source),
            self.side_effects.clone(),
            self.timestamp,
            set(self.non_compliant_ops),
            set(self.compliant_custom_ops),
        )
        self.timestamp += 1
        return state

    def restore_graphstate(self, state: OutputGraphState):
        """Restore a checkpoint created by self.copy_graphstate()"""
        (
            self.input_source_to_var,
            self.tracked_fakes,
            guards_state,
            module_state,
            self.register_finalizer_fns,
            global_state,
            self.param_name_to_source,
            self.side_effects,
            self.timestamp,
            self.non_compliant_ops,
            self.compliant_custom_ops,
        ) = state
        self.tracing_context.guards_context.restore_graphstate(guards_state)
        self.tracing_context.module_context.restore_graphstate(module_state)
        self.tracing_context.global_context.restore_graphstate(global_state)

        # FX deepcopy doesn't work for a partially created graph, so just remove new nodes
        removed_nodes = 0
        for node in reversed(list(self.graph.nodes)):
            if (
                node.meta["creation_timestamp"] > self.timestamp
                # placeholders here may have been lazily added by existing objects
                and node.op != "placeholder"
            ):
                # Erasing node alone does not remove the meta information
                # So, remove the help tensor explicitly
                if "example_value" in node.meta:
                    del node.meta["example_value"]
                self.remove_node(node)
                self.real_value_cache.pop(node, None)
                removed_nodes += 1
        log.debug("restore_graphstate: removed %s nodes", removed_nodes)

    def add_symbol_bindings(self, arg: GraphArg):
        # Insert implicit size vars as necessary.  With dynamic shapes, we
        # maintain the invariant that every sizevar gets a direct SymInt input
        # into the graph.  This means downstream graph transforms can assume
        # every size variable is explicitly bound and accessible, instead of
        # having to pull it out implicitly from tensors.

        if self.export:
            return

        assert arg.fake_tensor is not None

        def bind_symint(s, prop):
            if not (is_symbolic(s) and isinstance(s.node.expr, sympy.Symbol)):
                return
            s0 = s.node.expr
            if s0 in self.bound_symbols:
                return
            self.bound_symbols.add(s0)
            log.debug("bind_symint %s %s", s, prop.name())
            # TODO: don't readd symint if we already have it in graph
            # (this is harmless because we do remove the unused ones later)
            proxy = self.root_tracer.create_graph_input(
                str(s0),
                torch.SymInt,
                before=True,
                source=prop,
            )
            proxy.node.meta["example_value"] = s
            proxy.node.meta["grapharg"] = GraphArg(
                prop,
                s,
                is_unspecialized=False,
                fake_tensor=None,
                is_tensor=False,
            )

        def handle_tensor(t, src):
            for i, s in enumerate(t.size()):
                bind_symint(s, TensorPropertySource(src, TensorProperty.SIZE, i))
            for i, s in enumerate(t.stride()):
                bind_symint(s, TensorPropertySource(src, TensorProperty.STRIDE, i))
            bind_symint(
                t.storage_offset(),
                TensorPropertySource(src, TensorProperty.STORAGE_OFFSET),
            )
            if is_traceable_wrapper_subclass(t):
                attrs, ctx = t.__tensor_flatten__()
                for attr in attrs:
                    inner_t = getattr(t, attr)
                    handle_tensor(inner_t, AttrSource(src, attr))

        handle_tensor(arg.fake_tensor, arg.source)

    def count_calls(self):
        return count_calls(self.graph)

    def is_empty_graph(self):
        return len(list(self.graph.nodes)) == 0

    def get_submodule(self, keys):
        assert keys
        obj: Union[torch.nn.Module, Dict[str, torch.nn.Module]] = self.nn_modules
        for k in keys.split("."):
            if isinstance(obj, dict):
                obj = obj[k]
            else:
                obj = getattr(obj, k)
        return obj

    def new_var(self, name="tmp"):
        existing = set(self.code_options["co_varnames"])
        for i in itertools.count():
            var = f"{name}_{i}"
            if var not in existing:
                self.code_options["co_varnames"] += (var,)
                return var

    def update_co_names(self, name):
        """Ensure self.code_options.co_names contains name"""
        if name not in self.code_options["co_names"]:
            self.code_options["co_names"] += (name,)

    @staticmethod
    def module_key_name(*names):
        # create a new unique name
        name = "_".join(map(str, names))
        # Strip the guard lookup L/G access
        name = re.sub(r"^[GL]\['?(.*?)'?\]$", r"\1", name)
        # e.g. replace abc.xyz[123].qkv with abc.xyz_123.qkv
        name = re.sub(r"\[(\d+)\]", r"_\g<1>", name)
        # e.g. replace abc.xyz_123.qkv with abc_xyz_123_qkv
        name = re.sub(r"[^a-zA-Z0-9]", "_", name)

        if not name or not name[0].isalpha():
            name = "sub" + name

        return name

    def register_attr_or_module(
        self,
        target: Union[torch.nn.Module, torch.Tensor, Any],
        *names,
        **options,
    ):
        if is_dynamic_nn_module(target):
            return variables.UnspecializedNNModuleVariable(target, **options)

        options = dict(options)
        assert "source" in options
        source = options["source"]
        assert not isinstance(source, ParamBufferSource)

        if isinstance(target, torch.Tensor):
            tracer = self.current_tracer
            if not self.is_root_tracer():
                # For higher order ops, we don't want to insert the get_attr in
                # innermost graph. Instead, we want to raise the params/buffers
                # as inputs to the higher-order graph, and register them as
                # get_attrs in the root tracer.

                # Note that Dynamo will still call lift_tracked_freevar_to_input
                # when these inputs are encountered for the inner graph. The
                # only difference is what happens at the root tracer for
                # nn.Parameters vs free inputs. The free inputs are registered
                # as placeholders in the root graph, whereas the nn.Parameters
                # are registered as get_attr nodes in the root graph.
                tracer = self.root_tracer

            if not is_constant_source(source):
                install_guard(source.make_guard(GuardBuilder.TENSOR_MATCH))

            if get_static_address_type(target) == "guarded":
                install_guard(source.make_guard(GuardBuilder.DATA_PTR_MATCH))

            def wrap_name(module_key):
                assert self.param_name_to_source is not None
                self.param_name_to_source[module_key] = source

                return wrap_fx_proxy(
                    self.root_tx,
                    tracer.create_proxy("get_attr", module_key, tuple(), {}),
                    example_value=target,
                    **options,
                )

        elif isinstance(target, torch.nn.Module):
            assert isinstance(target, torch.nn.Module)

            install_guard(source.make_guard(GuardBuilder.NN_MODULE))

            def wrap_name(module_key):
                return NNModuleVariable(type(target), module_key, target, **options)

        elif isinstance(target, (torch.SymInt, torch.SymFloat)):
            # HACKY CODE REGION BEGIN
            # WE ARE PIGGYBACKING ON EXISTING INFRA TO REGISTER ATTRS
            # This ultimately gets written to self.nn_modules, which is unfortunate
            # Attrs that are tenors and symints and such need to be migrated to have their
            # own storage
            # alas, this is like this for now

            def wrap_name(module_key):
                return SymNodeVariable.create(
                    self,
                    self.create_proxy("get_attr", module_key, tuple(), {}),
                    sym_num=target,
                    **options,
                )

            # HACKY CODE REGION END
        else:

            def wrap_name(module_key):
                self.output.update_co_names(module_key)
                self.global_scope[module_key] = target
                return VariableBuilder(self, ConstantSource(source_name=module_key))(
                    target
                )

        for k, v in self.nn_modules.items():
            if v is target:
                # it already exists
                return wrap_name(k)

        name = OutputGraph.module_key_name(*names)

        base = name
        for i in itertools.count():
            if name not in self.nn_modules:
                self.nn_modules[name] = target
                if isinstance(target, torch.nn.Module):

                    def register_leaf_name(leaf_name):
                        assert self.param_name_to_source is not None
                        new_source = ParamBufferSource(source, leaf_name)
                        new_name = f"{name}.{leaf_name}"
                        self.param_name_to_source[new_name] = new_source
                        if isinstance(source, LocalSource):
                            self.dynamo_flat_name_to_original_fqn[
                                OutputGraph.module_key_name(new_source.name())
                            ] = leaf_name

                    # annoying, but there are cases when we do not have parameters
                    # see test_nn_moduledict_contains
                    if hasattr(target, "_parameters"):
                        for leaf_name, _ in target.named_parameters():
                            register_leaf_name(leaf_name)
                    if hasattr(target, "_buffers"):
                        for leaf_name, _ in target.named_buffers():
                            register_leaf_name(leaf_name)

                return wrap_name(name)
            name = f"{base}_{i}"

        raise AssertionError("unreachable")

    def compile_subgraph(
        self, tx, partial_convert=False, reason: Optional[GraphCompileReason] = None
    ):
        """
        Generate a subgraph to continue execution on user code.
        Automatically restore live variables.
        """
        assert reason is not None

        from .decorators import disable

        self.partial_convert = partial_convert
        self.compile_subgraph_reason = reason
        self.should_exit = True

        log.debug("COMPILING GRAPH due to %s", reason)

        if not all(block.can_restore() for block in tx.block_stack):
            unimplemented("compile_subgraph with block_depth != 0")

        prefix_insts: List[Instruction] = []
        if sys.version_info >= (3, 11):
            # prefix instructions (Python 3.11+)
            for inst in tx.prefix_insts:
                if inst.opname == "MAKE_CELL":
                    prefix_insts.append(
                        create_instruction("MAKE_CELL", argval=inst.argval)
                    )
                elif inst.opname == "COPY_FREE_VARS":
                    prefix_insts.append(
                        create_instruction(
                            "COPY_FREE_VARS", arg=len(tx.code_options["co_freevars"])
                        )
                    )
                else:
                    prefix_insts.append(copy.copy(inst))
        assert not (
            self.pregraph_bytecode and self.export
        ), "export does not support pregraph_bytecode"
        prefix_insts.extend(self.pregraph_bytecode)

        def append_prefix_insts():
            self.add_output_instructions(prefix_insts)
            prefix_insts.clear()

        for block in reversed(tx.block_stack):
            block.exit(tx)

        self.cleanup_graph()
        tx.prune_dead_locals()
        stack_values = list(tx.stack)
        root = FakeRootModule(self.nn_modules)
        # Add all the local vars to the "stack" so restore at the end
        restore_vars = []
        val_to_names: Dict[VariableTracker, List[str]] = {}
        if stack_values:
            val_to_names[stack_values[-1]] = list()
        # NB: Typically (i.e., for graph compile from RETURN_VALUE),
        # symbolic_locals will be empty at this point, as prune_dead_locals
        # will clear out all of symbolic_locals because RETURN_VALUE is the
        # last instruction and no more locals are used.  The fanciness here
        # is only needed for partial graphs.
        for k, v in tx.symbolic_locals.items():
            # Note! this explicitly uses .local_name for matching
            # Failure to do so will cause spurious registrations in val_to_names.
            # This will in turn result in spurious variables showing up in the graph.
            # This was very tricky to debug. For an example, dump the graph at call_user_compiler
            # while running test_subgraphs.py
            if isinstance(v.source, LocalSource) and v.source.local_name == k:
                continue  # no need to restore initial state
            if v not in val_to_names:
                val_to_names[v] = list()
            val_to_names[v].append(k)
        for v in val_to_names.keys():
            restore_vars.extend(val_to_names[v])
            stack_values.extend([v] * len(val_to_names[v]))

        # to handle random calls
        if len(self.random_calls) > 0:
            append_prefix_insts()
            random_calls_instructions = []
            self.random_values_var = self.new_var("random_values")
            rand_fn = disable(_get_gen_rand_values_fn(self.random_calls))
            rand_fn_name = self.install_global("__gen_rand_values", rand_fn)
            codegen = PyCodegen(tx, root)
            random_calls_instructions.extend(
                codegen.load_function_name(rand_fn_name, True)
            )
            random_calls_instructions.extend(create_call_function(0, False))
            random_calls_instructions.append(
                codegen.create_store(tx.output.random_values_var),
            )
            self.add_output_instructions(random_calls_instructions)

        if (
            stack_values
            and all(
                not isinstance(
                    v,
                    (
                        UnspecializedPythonVariable,
                        NumpyNdarrayVariable,
                        TensorWithTFOverrideVariable,
                    ),
                )
                for v in stack_values
            )
            and all(isinstance(x, TensorVariable) for x in stack_values)
            and len(set(stack_values)) == len(stack_values)
            and self.side_effects.is_empty()
            and not len(tx.debug_locals) != 0
            and not self.backward_state
        ):
            append_prefix_insts()
            # optimization to generate better code in a common case
            self.add_output_instructions(
                self.compile_and_call_fx_graph(tx, list(reversed(stack_values)), root)
                + [create_instruction("UNPACK_SEQUENCE", arg=len(stack_values))]
            )
        else:
            graph_output_var = self.new_var("graph_out")
            pass1 = PyCodegen(tx, root, graph_output_var)
            self.codegen_suffix(tx, stack_values, pass1)

            # one more time now that we have established tempvars
            pass2 = PyCodegen(
                tx,
                root,
                graph_output_var,
                tempvars={val: None for val, count in pass1.uses.items() if count > 1},
            )
            self.codegen_suffix(tx, stack_values, pass2)

            output = []
            if count_calls(self.graph) != 0 or len(pass2.graph_outputs) != 0:
                output.extend(
                    self.compile_and_call_fx_graph(tx, pass2.graph_output_vars(), root)
                )

                if len(pass2.graph_outputs) != 0:
                    output.append(pass2.create_store(graph_output_var))
                else:
                    output.append(create_instruction("POP_TOP"))
            append_prefix_insts()
            self.add_output_instructions(output + pass2.get_instructions())

        # restore all the live local vars
        self.add_output_instructions(
            [PyCodegen(tx).create_store(var) for var in reversed(restore_vars)]
        )

    def codegen_suffix(self, tx, stack_values, cg):
        if self.backward_state:
            assert not self.export
            for name, val in self.backward_state.items():
                cg(val)
                cg.append_output(cg.create_load(self.backward_state_var))
                cg.store_attr(name)
        self.side_effects.codegen_hooks(cg)
        self.side_effects.codegen_save_tempvars(cg)

        # Return variables used for logging at the end
        for debug_var, args in tx.debug_locals:
            cg(debug_var)
            for arg in args:
                cg(arg)
            cg.extend_output(create_call_function(len(args), True))

        cg.restore_stack(stack_values, value_from_source=not tx.export)
        self.side_effects.codegen_update_mutated(cg)

    def cleanup_graph(self):
        """
        Remove "creation_timestamp" from node meta

        Remove this pattern from the graph:
            torch._C._set_grad_enabled(False)
            torch._C._set_grad_enabled(True)
        """
        assert self.should_exit
        nodes = list(self.graph.nodes)
        for node in nodes:
            node.meta.pop("creation_timestamp", None)

        grad_enabled = torch.is_grad_enabled()
        for node1, node2 in zip(nodes, nodes[1:]):
            if (
                node1.target is torch._C._set_grad_enabled
                and tuple(node1.args) == (not grad_enabled,)
                and not node1._erased
            ):
                grad_enabled = node1.args[0]
                if (
                    node2.target is torch._C._set_grad_enabled
                    and tuple(node2.args) == (not grad_enabled,)
                    and not node2._erased
                ):
                    grad_enabled = node2.args[0]
                    self.graph.erase_node(node1)
                    self.graph.erase_node(node2)

    def get_graph_sizes_structured(self):
        ret = {}
        for node in self.graph.nodes:
            example_value = node.meta.get("example_value", None)
            if isinstance(example_value, torch._subclasses.FakeTensor):
                size = example_value.size()
                ret[node.name] = [s if isinstance(s, int) else repr(s) for s in size]
        return ret

    def get_graph_sizes(self, name: str):
        graph_sizes_str = "TRACED GRAPH TENSOR SIZES\n"
        graph_sizes_str += f"===== {name} =====\n"
        for node in self.graph.nodes:
            example_value = node.meta.get("example_value", None)
            if isinstance(example_value, torch._subclasses.FakeTensor):
                size = example_value.size()
                graph_sizes_str += f"{node.name}: {tuple(size)}\n"
                concrete_size = []
                has_symint = False
                for sz in size:
                    if isinstance(sz, int):
                        concrete_size.append(sz)
                    elif isinstance(sz, torch.SymInt):
                        has_symint = True
                        concrete_size.append(sz.node.hint)
                    else:
                        break
                else:
                    if has_symint:
                        graph_sizes_str += (
                            f"{node.name} (concrete): {tuple(concrete_size)}\n"
                        )
        return graph_sizes_str

    @contextlib.contextmanager
    def restore_global_state(self):
        """
        Momentarily restores the global state to what it was prior to tracing the current output
        """
        prior_global_state = self.tracing_context.global_context.copy_graphstate()
        current_global_state: Dict[str, Tuple[Any, bool]] = {}
        self.save_global_state(out=current_global_state)
        try:
            # Set to state prior to tracing the graph
            self.tracing_context.global_context.restore_graphstate(prior_global_state)
            yield
        finally:
            # Reset to state at the current time (e.g. before calling the user compiler)
            self.tracing_context.global_context.restore_graphstate(
                GlobalContextCheckpointState(current_global_state)
            )

    @torch._guards.TracingContext.clear_frame()
    def compile_and_call_fx_graph(self, tx, rv, root):
        """
        Generate code from self.graph and return the Instruction()s to
        call that generated code.
        """
        from .decorators import disable

        assert self.should_exit

        name = unique_id("__compiled_fn")

        assert isinstance(rv, list)
        assert isinstance(root, FakeRootModule)
        self.create_node(
            "output",
            "output",
            (self.current_tracer.create_arg(tuple(x.as_proxy() for x in rv)),),
            {},
        )
        self.insert_deferred_runtime_asserts(root, name)
        # NB: deferred runtime asserts can keep graphargs live, so make sure
        # those are inserted before pruning
        self.remove_unused_graphargs()
        ncalls = count_calls(self.graph)
        counters["stats"]["calls_captured"] += ncalls

        # free a bit of memory
        self.real_value_cache.clear()

        gm = _make_graph_module(root, self.graph)
        for register_finalizer in self.register_finalizer_fns:
            register_finalizer(gm)

        gm.compile_subgraph_reason = self.compile_subgraph_reason
        gm.meta[
            "dynamo_flat_name_to_original_fqn"
        ] = self.dynamo_flat_name_to_original_fqn.copy()

        graph_code_log.debug("%s", lazy_format_graph_code(name, gm))
        torch._logging.trace_structured(
            "dynamo_output_graph",
            lambda: {"sizes": self.get_graph_sizes_structured()},
            payload_fn=lambda: gm.print_readable(print_output=False),
        )
        graph_tabular_log.debug("%s", lazy_format_graph_tabular(name, gm))
        graph_sizes_log.debug("%s", LazyString(lambda: self.get_graph_sizes(name)))
        self.call_cleanup_hooks()
        old_fake_mode = self.tracing_context.fake_mode
        if not self.export:
            # TODO(voz): The way export uses gm, and fake tensors, is not supported with us resetting
            backend_fake_mode = torch._subclasses.FakeTensorMode(
                shape_env=old_fake_mode.shape_env,
            )
            # TODO(voz): Ostensibily, this should be scoped and
            # restore back to old_fake_mode, but doing so currently violates
            # a lot of fake_tensor ownership assumptions and runs afoul of detect_fake_mode
            self.tracing_context.fake_mode = backend_fake_mode

        with self.restore_global_state():
            compiled_fn = self.call_user_compiler(gm)
        compiled_fn = disable(compiled_fn)

        counters["stats"]["unique_graphs"] += 1
        # This is safe because we pre-process name to be unique
        self.install_global_unsafe(name, compiled_fn)

        cg = PyCodegen(tx)
        cg.make_call_generated_code(name)
        return cg.get_instructions()

    @property
    def placeholders(self) -> List[fx.Node]:
        r = []
        for node in self.graph.nodes:
            if node.op == "placeholder":
                r.append(node)
                continue
            break
        return r

    @property
    def graphargs(self) -> List[GraphArg]:
        return [node.meta["grapharg"] for node in self.placeholders]

    @dynamo_timed(phase_name="backend_compile")
    def call_user_compiler(self, gm: fx.GraphModule) -> CompiledFn:
        assert self.compiler_fn is not None
        tot = 0
        placeholders = []
        for node in gm.graph.nodes:
            if node.op in ("call_function", "call_method", "call_module"):
                tot += 1
            if node.op == "placeholder":
                placeholders.append(node)
        increment_op_count(tot)
        for pl in placeholders:
            arg = pl.meta["grapharg"]
            # TODO: Why isn't this stored in meta :think:
            pl._dynamo_source = arg.source

        gm._param_name_to_source = self.param_name_to_source  # type: ignore[assignment]
        gm._source_to_user_stacks = self.source_to_user_stacks  # type: ignore[assignment]

        try:
            name = (
                self.compiler_fn.__name__
                if hasattr(self.compiler_fn, "__name__")
                else ""
            )
            _step_logger()(logging.INFO, f"calling compiler function {name}")
            compiler_fn = self.compiler_fn
            if config.verify_correctness:
                compiler_fn = WrapperBackend(compiler_fn)
            compiled_fn = compiler_fn(gm, self.example_inputs())
            _step_logger()(logging.INFO, f"done compiler function {name}")
            assert callable(compiled_fn), "compiler_fn did not return callable"
        except exceptions_allowed_to_be_fallback as e:
            if self.has_user_defined_allowed_in_graph:
                raise BackendCompilerFailed(self.compiler_fn, e).with_traceback(
                    e.__traceback__
                ) from None
            msg = (
                "Backend compiler failed with a fake tensor exception at \n"
                f"{self.root_tx.format_frame_summary()}"
                "Adding a graph break."
            )
            unimplemented_with_warning(e, self.root_tx.f_code, msg)
        except SkipFrame as e:
            # The backend compiler has requested that we skip the frame, instead of
            # aborting execution.
            raise e
        except Exception as e:
            raise BackendCompilerFailed(self.compiler_fn, e).with_traceback(
                e.__traceback__
            ) from None

        signpost_event(
            "dynamo",
            "OutputGraph.call_user_compiler",
            {
                **self.co_fields,
                "op_count": tot,
                "node_count": len(gm.graph.nodes),
                "input_count": len(placeholders),
            },
        )

        return compiled_fn

    def example_inputs(self) -> List[torch.Tensor]:
        result = []
        for arg in self.graphargs:
            result.append(arg.example)
        return result

    def remove_unused_graphargs(self) -> None:
        assert self.should_exit
        # Miniature DCE pass, but only for obviously trivial operations
        for node in reversed(list(self.graph.nodes)):
            if len(list(node.users)) == 0:
                if node.op == "get_attr":
                    self.remove_node(node)
                elif node.op == "call_function" and node.target is operator.getitem:
                    self.remove_node(node)

        def placeholder_binds_symbol(node):
            arg = node.meta["grapharg"]
            example = arg.example
            if isinstance(example, torch.SymInt) and isinstance(
                example.node.expr, sympy.Symbol
            ):
                return example.node.expr
            return None

        def remove_unused(node):
            log.debug("REMOVE UNUSED GRAPHARG %s", node.meta["grapharg"].source.name())
            # I'm not really sure why you need to delete these from the
            # node since the node is going to get removed
            del node.meta["grapharg"]
            self.remove_node(node)
            self.real_value_cache.pop(node, None)

        used_symbols = set()
        recheck_placeholders = []
        for node in self.placeholders:
            binds_symbol = placeholder_binds_symbol(node) is not None
            # Don't delete symbol bindings yet
            if binds_symbol:
                if not node.users:
                    recheck_placeholders.append(node)
            else:
                if not node.users and not isinstance(
                    node.meta["grapharg"], BackwardStateGraphArg
                ):
                    remove_unused(node)
                else:
                    # Register the free symbols as uses
                    arg = node.meta["grapharg"]
                    if isinstance(arg, BackwardStateGraphArg):
                        continue
                    fake = (
                        arg.fake_tensor if arg.fake_tensor is not None else arg.example
                    )
                    used_symbols |= free_symbols(fake)

        # After removing unused graphargs, prune unused binds_symbol
        for node in recheck_placeholders:
            symbol = placeholder_binds_symbol(node)
            if symbol is not None:
                if symbol not in used_symbols:
                    remove_unused(node)
                else:
                    # Make sure we delete later occurrences of the same symbol
                    used_symbols.remove(symbol)

    # TODO: this is a generic pass that should live outside of Dynamo
    def insert_deferred_runtime_asserts(self, root, name) -> None:
        """
        During tracing, we may have discovered that some data-dependent values
        had runtime assert on them; e.g., torch.empty(x.item()) induces a runtime
        that x.item() >= 0.  This asserts can happen unpredictably during fake
        tensor propagation, so we cannot conveniently insert them into the FX graph
        when they occur.  Instead, we accumulate them in the ShapeEnv, and in this
        pass insert them into the graph as proper tests.
        """
        # TODO: Request simplification on runtime asserts before emitting them
        ras_by_symbol = self.shape_env.deferred_runtime_asserts.copy()

        if not any(ras for ras in ras_by_symbol.values()):
            return

        gm = fx.GraphModule(root, self.graph)
        graph_code_log.debug(
            "%s",
            lazy_format_graph_code(f"pre insert_deferred_runtime_asserts {name}", gm),
        )

        # We are going to mutate the dict
        symbol_to_proxy = {}
        placeholders = set()
        last_placeholder = None
        for node in self.graph.nodes:
            if node.op != "placeholder":
                last_placeholder = node
                break
            placeholders.add(node)
        assert last_placeholder is not None

        # Identify what symbols we need to reify.  This isn't strictly needed
        # but helps reduce churn on the graph
        needed_symbols: Set[sympy.Symbol] = set()
        for ras in ras_by_symbol.values():
            for ra in ras:
                needed_symbols.update(free_symbols(ra.expr))

        log.debug("needed_symbols = %s", needed_symbols)

        for node in self.graph.nodes:
            # Placeholders can match symbols, but when we destructure them
            # with size we have to make sure we insert the nodes after all
            # the placeholders
            with self.graph.inserting_before(
                node.next if node not in placeholders else last_placeholder.next
            ):
                if "example_value" not in node.meta:
                    continue

                defs = []

                # For every new unbacked symbol, we need an fx.Node representing
                # precisely this value.  There are a few places where the unbacked
                # symbol could have come from, and we will check them to setup
                # these nodes.
                #
                # For a case like item(), this is trivial (no new node is added.)
                #
                # For nonzero(), we need to add something like i0 = out.size(0)
                #
                # We could end up with duplicate nodes this way but it is not a
                # big deal.
                #
                # We also do this to setup backed SymInts, but those are all going
                # to be matched from placeholders
                def match_symbol(symint, cb):
                    if (
                        isinstance(symint, torch.SymInt)
                        and isinstance(symint.node, SymNode)
                        and isinstance(s := symint.node.expr, sympy.Symbol)
                        and s not in symbol_to_proxy
                        and s in needed_symbols
                    ):
                        symbol_to_proxy[s] = fx.Proxy(cb())
                        log.debug("symbol_to_proxy[%s] = %s", s, symbol_to_proxy[s])
                        defs.append(s)

                match_symbol(node.meta["example_value"], lambda: node)
                if isinstance(t := node.meta["example_value"], torch.Tensor):
                    for i, s in enumerate(t.size()):
                        match_symbol(
                            s, lambda: self.graph.call_method("size", (node, i))
                        )
                    for i, s in enumerate(t.stride()):
                        match_symbol(
                            s, lambda: self.graph.call_method("stride", (node, i))
                        )
                    match_symbol(
                        t.storage_offset(),
                        lambda: self.graph.call_method("storage_offset", (node,)),
                    )

                for i0 in defs:
                    ras = ras_by_symbol.pop(i0, [])
                    # Before we perform any asserts, first apply range
                    # refinement.  This is important, because if we are going
                    # to retrace the graph (and we typically are if we send
                    # the graph to AOTAutograd), we need to make sure we apply
                    # range refinement (ala _check_is_size) first, BEFORE we
                    # run any of the asserts.  Otherwise, we may decide to
                    # perform substitutions based on the asserts which we then
                    # can't back out, because value ranges can only be applied
                    # to asserts.)
                    #
                    # A perhaps better long term plan is to avoid this order
                    # dependence by making it possible to refine ranges on
                    # arbitrary expressions, not just symbols.  But it is not
                    # so easy to make use of this information, see
                    # https://twitter.com/ezyang/status/1745801370299482492
                    # We actually made an attempt at this in
                    # https://github.com/pytorch/pytorch/pull/119043
                    # which didn't work.
                    #
                    # Another ideas for how to do this:
                    # - Have bound_sympy be the source of truth of the ranges of any expression
                    # - Cache intermediate results for every subexpression of bound_sympy
                    # - This cache should be possible to edit to refine ranges
                    #
                    # One issue with this proposal is that if
                    # we have a bound on 2x, we are not going to be able to
                    # apply it for 4x.  Similarly, we may have bounds for an
                    # equivalent expression that we are not applying because
                    # it's not a perfect match (e.g. x < y vs y > x)".
                    #
                    # The first issue we already have it and it's impossible
                    # to solve in general, so any implementation on a best
                    # effort basis should do.
                    #
                    # The second issue is a preexisting one. It can be mitigated
                    # with a normalisation algorithm. In general, it may also
                    # be on a best effort basis, but since our grammar is not
                    # terribly difficult, chances are we could even fully
                    # normalise SymPy expressions... who knows.

                    if i0 in self.shape_env.size_like:
                        self.graph.call_function(
                            torch._check_is_size, (symbol_to_proxy[i0].node,)
                        )

                    vr = self.shape_env.var_to_range[i0]
                    if not self.shape_env._default_unspecified_value_range().issubset(
                        vr
                    ):
                        # The runtime range is constrained, so add a runtime
                        # assert and also explicitly refine the range
                        # (refinement should not be necessary once runtime
                        # asserts cause refinement, but that's NYI)
                        def convert(s):
                            try:
                                return int(s)
                            except TypeError:
                                return None

                        self.graph.call_function(
                            torch._constrain_as_value,
                            (
                                symbol_to_proxy[i0].node,
                                convert(vr.lower),
                                convert(vr.upper),
                            ),
                        )

                    for ra in ras:
                        log.debug("inserting runtime assert %s", ra.expr)
                        # Need to process ALL free symbols, not just unbacked ones
                        fvs = free_symbols(ra.expr)
                        missing = fvs - symbol_to_proxy.keys()
                        if missing:
                            i1 = sorted(missing)[0]
                            # TODO: Remove relaxing assert on unbacked_symint https://github.com/pytorch/pytorch/issues/119689
                            # assert self.shape_env.is_unbacked_symint(i1), i1
                            ras_by_symbol.setdefault(i1, []).append(ra)
                        else:
                            # Convert the sympy expression into a sequence of FX
                            # nodes
                            res = sympy_interp(
                                PythonReferenceAnalysis, symbol_to_proxy, ra.expr
                            ).node
                            self.graph.call_function(
                                torch.ops.aten._assert_scalar.default,
                                # TODO: use ra.msg here, but it's pretty
                                # useless right now
                                (
                                    res,
                                    f"Deferred runtime assertion failed {ra.expr}",
                                ),
                            )

    def add_output_instructions(self, prefix: List[Instruction]) -> None:
        """
        We call this on the creation of a new compiled subgraph that is inserted
        before user code.
        """
        self.output_instructions.extend(prefix)
        self.should_exit = True

    def install_global_unsafe(self, name, value) -> None:
        """
        WARNING: prefer the safer `install_global_by_id/install_global`.
        torch.compile instances should be independent of each other;
        one footgun is to have one instance depend on the existence of
        a global installed by another instance. This can happen if we mangle
        a global the same way across both instances.
        """
        assert name not in self.installed_globals
        self.installed_globals.add(name)
        self.cleanups.append(CleanupHook.create(self.global_scope, name, value))

    def install_global_by_id(self, prefix, value) -> str:
        """
        Installs a global if it hasn't been installed already.
        This is determined by (prefix, id(value)) pair.

        Returns the name of the newly installed global.
        """
        # NB: need self.compile_id to distinguish this global
        # from another global created in a different torch.compile instance
        name = f"{prefix}_{id(value)}_c{self.compile_id}"
        if name in self.installed_globals:
            return name
        self.install_global_unsafe(name, value)
        return name

    def install_global(self, prefix, value) -> str:
        """
        Installs a global, generating a unique name for it.

        Returns the name of the newly installed global.
        """
        # NB: unique_id is unique, even across torch.compile instances
        name = unique_id(prefix)
        self.install_global_unsafe(name, value)
        return name

    def cleanup(self) -> None:
        # There is a reference cycle between tracer and OutputGraph, causing
        # some of the tensor objects to be held alive for longer than necessary.
        self.root_tx = None
        self.nn_modules.clear()
        self.param_name_to_source = None

        for node in self.graph.nodes:
            if "grapharg" in node.meta:
                del node.meta["grapharg"]
        self.real_value_cache.clear()
        self.input_name_to_proxy.clear()
        self.side_effects.clear()
        self.register_finalizer_fns.clear()
        self.dynamo_flat_name_to_original_fqn.clear()
        self.tracing_context.clear()

    def set_torch_function_state(self, enabled: bool) -> None:
        self.torch_function_enabled = enabled

    def add_graph_finalizer(
        self, register_finalizer: Callable[[fx.GraphModule], None]
    ) -> None:
        self.register_finalizer_fns.append(register_finalizer)

    def example_value_from_input_node(self, node: torch.fx.Node):
        """Extract the non-fake example tensor"""
        if node.op == "placeholder":
            return node.meta["grapharg"].example
        assert node.op == "get_attr"
        return self.nn_modules[node.target]  # type: ignore[index]


err_epilogue = (
    "With the current config, we will graph break "
    "(and fall back to eager-mode PyTorch) on all ops "
    "that have do not have the 'pt2_compliant_tag'. "
    "Please see the following doc for how to mark this op as PT2 compliant "
    "https://docs.google.com/document/d/1W--T6wz8IY8fOI0Vm8BF44PdBgs283QvpelJZWieQWQ"
)


def check_pt2_compliant_op(output_graph, kind, target, args, kwargs):
    if kind != "call_function":
        return

    def encountered_compliant_op(target):
        if target.namespace in {"prim", "prims", "aten"}:
            return
        output_graph.compliant_custom_ops.add(target)

    def encountered_non_compliant_op(target, msg):
        output_graph.non_compliant_ops.add(target)
        if config.only_allow_pt2_compliant_ops:
            unimplemented(msg + " " + err_epilogue)

    if isinstance(target, torch._ops.OpOverload):
        if torch.Tag.pt2_compliant_tag in target.tags:
            encountered_compliant_op(target)
            return
        encountered_non_compliant_op(
            target,
            f"Encountered the torch.ops.OpOverload {target} "
            f"that is not PT2 compliant.",
        )
        return

    if isinstance(target, torch._ops.OpOverloadPacket):
        overloads = tuple(target.overloads())
        # Optimization: Overload resolution is expensive.
        # If there's only one overload, we know what it will resolve to.
        if len(overloads) == 1:
            op = getattr(target, overloads[0])
            if torch.Tag.pt2_compliant_tag in op.tags:
                encountered_compliant_op(op)
                return
            encountered_non_compliant_op(
                op,
                f"Encountered the non-overloaded "
                f"torch.ops.OpOverloadPacket {target} "
                f"that is not PT2 compliant. ",
            )
            return

        args, kwargs = torch._dynamo.utils.get_fake_values_from_nodes(
            output_graph.current_tx, (args, kwargs), False
        )
        try:
            overload = torch._C._jit_resolve_packet(
                target._qualified_op_name, *args, **kwargs
            )
        except RuntimeError as e:
            unimplemented(str(e))

        op = getattr(target, overload)
        if torch.Tag.pt2_compliant_tag in op.tags:
            encountered_compliant_op(op)
        else:
            encountered_non_compliant_op(
                op,
                f"Encountered the torch.ops.OpOverloadPacket {target} "
                f"which resolves to the overload ({overload}) that is "
                f"not PT2 compliant.",
            )


_compile_id_counter = itertools.count()


class SubgraphTracer(fx.Tracer):
    """
    Holds an FX graph that is being traced. OutputGraph owns a SubgraphTracer
    and the separation of responsibilities is that SubgraphTracer is
    responsible for building the graph while OutputGraph is responsible for
    compiling and executing the graph.
    """

    def __init__(
        self, output_graph, parent=None, export_root=False, source_target=None
    ):
        super().__init__()
        self.output_graph = weakref.proxy(output_graph)
        self.graph = torch.fx.Graph()

        # The export is only ever set for the ROOT tracer.  It controls
        # whether or not certain inputs are allowed to be added or not.
        # Look at call sites of create_graph_input to see how it is used.
        if export_root:
            assert parent is None
        self.export_root = export_root
        # Map from graph input name to its placeholder proxy object, where the
        # map's keys give all current placeholder node names and can be used to
        # create unique node names
        self.input_name_to_proxy: Dict[str, fx.Proxy] = {}
        # Node => computed real value (see utils.get_real_value)
        self.real_value_cache: Dict[fx.Node, torch.Tensor] = {}

        # SubgraphTracers can be nested. See NOTE [HigherOrderOperator tracing design]
        self.parent = parent
        # A dict mapping previously free variables (Proxy objects)
        # to new Proxy objects that wrap inputs to this subgraph.
        #
        # This dict serves two purposes:
        # - Proxies are associated with VariableTrackers. If we see
        # the same VariableTracker twice (and it is a free variable),
        # then we want to use the same Proxy in the current subgraph to
        # record the tracing.
        # - If we are tracing a HigherOrderOperator's body_fn, then we
        # need to keep track of what free variables were lifted so we can
        # rewrite the HigherOrderOperator call using the traced body_fn.
        # Dicts maintain the order of args for the HigherOrderOperator call.
        self.lifted_freevars = {}
        self.prev_inst = None

        self._cur_code = None
        self._orig_gm_meta = None
        self._orig_gm_lineno_map = None
        self._orig_gm_firstlineno = None
        # Each SubgraphTracer is associated with a source target, which indicates
        # which operator this subgraph is attached to. We compute a source_fn_stack
        # based on the source target. For the root tracer, it's set to [].
        # This is useful for debugging and transforming the exported graph.
        if self.parent is None:
            self.source_fn_stack = []
        else:
            self.source_fn_stack = self.parent.source_fn_stack + [
                (self.graph._target_to_str(source_target), source_target)
            ]

    def create_proxy(
        self,
        kind,
        target,
        args,
        kwargs,
        name=None,
        type_expr=None,
        proxy_factory_fn=None,
    ):
        # NOTE: [Nested SubgraphTracer and free_variable handling]
        # --------------------------------------------------------
        # Read NOTE [HigherOrderOperator tracing design] first.
        #
        # Let's say we're in the middle of introspecting the body of a possibly
        # nested HigherOrderOperator, and we see a free variable.
        #
        # There are two cases:
        # 1. We see a free variable that is already tracked by Dynamo.
        # 2. We see a free variable that has not been tracked by Dynamo
        #
        # In case 1, we call `maybe_lift_tracked_freevar_to_input` (below)
        # which will lift the freevar to be an input of this subgraph
        # and also recursively lift it to be an input on the parent(s).
        #
        # In case 2, before the call to `create_proxy`, the InstructionTranslator
        # will see the freevar when it gets loaded by Python bytecode.
        # E.g. for Python 3.11 the bytecodes that may do this are LOAD_DEREF or
        # LOAD_GLOBAL.
        # There, the InstructionTranslator asks Dynamo to begin tracking the
        # freevar by building a new Variable.
        # Building a new Variable automatically lifts the freevar to be an
        # input of the root SubgraphTracer.
        #
        # The implications for the code below are:
        # - We will always be in Case 1 when we get to this code.
        # - Any "free variable" we encounter here is guaranteed to already be
        #   bound, that is, it is either a graph input of the root graph, or
        #   some local variable of the root graph or a subgraph.
        # - The additional work we need to do here is *only* that we need to
        #   lift this free variable into inputs (recursively) of each nested
        #   higher-order-op subgraph until we hit the subgraph where the free
        #   variable is bound
        if self.parent is not None:
            flat_args, tree_spec = pytree.tree_flatten((args, kwargs))
            new_flat_args = []
            for arg in flat_args:
                maybe_new_arg = self.maybe_lift_tracked_freevar_to_input(arg)
                new_flat_args.append(maybe_new_arg)

            args, kwargs = pytree.tree_unflatten(new_flat_args, tree_spec)

        rv = super().create_proxy(
            kind, target, args, kwargs, name, type_expr, proxy_factory_fn
        )

        # append stack trace to fx node
        tx = self.output_graph.current_tx

        # log detailed location of line of code in 3.11
        if sys.version_info >= (3, 11) and kind in (
            "call_function",
            "call_method",
            "call_module",
        ):
            cur_inst = tx.current_instruction
            if (
                cur_inst is not self.prev_inst
                and cur_inst.positions is not None
                and cur_inst.positions.lineno is not None
            ):
                tx_code = tx.f_code
                header = tx.get_line_of_code_header(lineno=cur_inst.positions.lineno)

                def get_trace_call_log_str():
                    line = get_instruction_source_311(tx_code, cur_inst).rstrip()
                    return f"TRACE FX call {rv.node.name} from {header}\n{line}"

                trace_call_log.debug("%s", LazyString(get_trace_call_log_str))
                self.prev_inst = cur_inst

        # update reference to original meta if we're tracing a new code object
        is_retracing = False
        if tx.f_code is not self._cur_code:
            orig_graphmodule_maybe = code_context.get_context(tx.f_code).get(
                "orig_graphmodule", lambda: None
            )()
            if isinstance(orig_graphmodule_maybe, torch.fx.GraphModule):
                is_retracing = True
                self._orig_gm_meta = [
                    nd.meta for nd in orig_graphmodule_maybe.graph.nodes
                ]
                self._orig_gm_lineno_map = orig_graphmodule_maybe._lineno_map
                self._orig_gm_firstlineno = (
                    orig_graphmodule_maybe.forward.__code__.co_firstlineno
                )
            else:
                self._orig_gm_meta = None
                self._orig_gm_lineno_map = None
                self._orig_gm_firstlineno = None
        nn_module_stack = tx.nn_module_stack
        if nn_module_stack:
            rv.node.meta["nn_module_stack"] = nn_module_stack.copy()

        if kind in {"call_function", "call_method"}:
            rv.node.meta["source_fn_stack"] = self.source_fn_stack + [
                (rv.node.name, target)
            ]
        elif kind == "call_module":
            if self.parent is not None:
                unimplemented("Invoking an nn.Module inside HigherOrderOperator")
            # For modules we store the class
            rv.node.meta["source_fn_stack"] = self.source_fn_stack + [
                (
                    rv.node.name,
                    rv.node.meta["nn_module_stack"][target][1],
                )
            ]

        # preserve original meta if it is available
        if (
            self._orig_gm_meta
            and self._orig_gm_lineno_map
            and self._orig_gm_firstlineno
        ):
            lineno = tx.current_instruction.starts_line
            node_idx = None
            if lineno is not None:
                node_idx = self._orig_gm_lineno_map.get(
                    lineno - self._orig_gm_firstlineno, None
                )
            if node_idx is not None:
                meta = self._orig_gm_meta[node_idx]
                for field in fx.proxy._COPY_META_FIELDS:
                    if field in meta:
                        rv.node.meta[field] = meta[field]
                if "stack_trace" in meta:
                    rv.node.meta["stack_trace"] = meta["stack_trace"]

        if not is_retracing:
            if "nn_module_stack" not in rv.node.meta:
                nn_module_stack = tx.nn_module_stack
                if nn_module_stack:
                    rv.node.meta["nn_module_stack"] = nn_module_stack.copy()

            if "source_fn_stack" not in rv.node.meta:
                if kind in {"call_function", "call_method"}:
                    rv.node.meta["source_fn_stack"] = self.source_fn_stack + [
                        (rv.node.name, target)
                    ]
                elif kind == "call_module":
                    if self.parent is not None:
                        unimplemented(
                            "Invoking an nn.Module inside HigherOrderOperator"
                        )
                    # For modules we store the class
                    rv.node.meta["source_fn_stack"] = self.source_fn_stack + [
                        (
                            rv.node.name,
                            rv.node.meta["nn_module_stack"][target][1],
                        )
                    ]

        if "stack_trace" not in rv.node.meta:
            frame_summaries: List[traceback.FrameSummary] = []
            while tx:
                frame_summaries.append(tx.frame_summary())
                tx = getattr(tx, "parent", None)
            # Reverse the frame_summaries, such that the innermost frame is at the last
            frame_summaries.reverse()

            # official from_list stub doesn't have new-style type
            msgs = traceback.StackSummary.from_list(frame_summaries).format()
            rv.node.stack_trace = "".join(msgs)

        return rv

    def create_node(
        self, op, target, args=None, kwargs=None, name=None, type_expr=None
    ):
        check_pt2_compliant_op(self.output_graph, op, target, args, kwargs)
        if self.parent is not None:
            flat_args = pytree.arg_tree_leaves(*args, **kwargs)
            for arg in flat_args:
                if not isinstance(arg, torch.fx.Node):
                    continue
                assert (
                    arg.graph == self.graph
                ), "create_node using arg not from this SubgraphTracer"

        node = super().create_node(op, target, args, kwargs, name, type_expr)
        node.meta["creation_timestamp"] = self.output_graph.timestamp
        return node

    # Note: we did not override erase_node since
    # we call self.graph.erase_node elsewhere
    def remove_node(self, node):
        if len(node.users) > 0:
            user_graph_nodes: List[torch.fx.Node] = []
            for user in node.users.keys():
                # For the case where user.graph == self.graph, that is a real bug and will raise
                # properly.
                if user.graph != self.graph:
                    # This is a nested graph, which needs to be deleted.
                    # If we do not do this, we will raise on attempting to remove this.
                    # As we only get here during restoration cleanup, this is sound.
                    user_graph_nodes.extend(reversed(list(user.graph.nodes)))
            for other_graph_node in user_graph_nodes:
                other_graph_node.graph.erase_node(other_graph_node)
        self.graph.erase_node(node)
        self.input_name_to_proxy.pop(node.name, None)

    # when before=True, we will insert this input before the most recent
    # inserted proxy.  This is a hack to get around an ordering problem,
    # where we first insert a tensor argument, and then insert bindings
    # for SymInts that may occur in the tensor argument.
    # Remove this if https://github.com/pytorch/pytorch/issues/99007 gets
    # fixed.
    def create_graph_input(self, name, type_expr=None, before=False, source=None):
        log.debug(
            "create_graph_input %s %s",
            name,
            source.name() if source is not None else "(none)",
        )
        if source is None:
            assert (
                self.parent is not None
            ), "you are required to provide a source for inputs on the root tracer"

        # In eager, we are generally OK with adding graph inputs whenever we
        # want, because we take care of writing the bytecode that knows how
        # to source all the inputs.
        #
        # In export, this is bad, because you want a self-contained export
        # object which only depends on the inputs you explicitly passed to it.
        # So we are a bit more strict about what sources can become inputs
        # in export
        if self.export_root:
            if not is_from_local_source(source, allow_cell_or_freevar=False):
                self.output_graph.source_to_user_stacks.setdefault(source, []).append(
                    TracingContext.extract_stack()
                )

        # unique
        if name in self.input_name_to_proxy:
            for i in itertools.count():
                candidate_name = f"{name}_{i}"
                if candidate_name not in self.input_name_to_proxy:
                    name = candidate_name
                    break

        if self.input_name_to_proxy:
            prev_name = next(reversed(self.input_name_to_proxy))
            node = self.input_name_to_proxy[prev_name].node
            if before:
                ctx = self.graph.inserting_before(node)
            else:
                ctx = self.graph.inserting_after(node)
        else:
            ctx = self.graph.inserting_before(None)
        with ctx:
            proxy = self.create_proxy("placeholder", name, (), {}, type_expr=type_expr)
            if self.input_name_to_proxy and before:
                k, v = self.input_name_to_proxy.popitem()
                self.input_name_to_proxy[name] = proxy
                self.input_name_to_proxy[k] = v
            else:
                self.input_name_to_proxy[name] = proxy
            return proxy

    # See NOTE: [Nested SubgraphTracer and free_variable handling] for more details
    def lift_tracked_freevar_to_input(self, proxy):
        # You're doing something wrong if we are the root SubgraphTracer because
        # Dynamo adds tensors to graph inputs before creating a proxy for them.
        assert (
            self.parent is not None
        ), "lift_tracked_freevar_to_input should not be called on root SubgraphTracer"
        # Proxys are associated with VariableTracker.
        # It is possible that we've already lifted the Proxy to be an input.
        # If that is the case, just return the already lifted Proxy.
        if proxy in self.lifted_freevars:
            return self.lifted_freevars[proxy]
        new_proxy = self.create_graph_input(proxy.node.name)
        new_proxy.node.meta["example_value"] = proxy.node.meta["example_value"]
        self.lifted_freevars[proxy] = new_proxy
        if self.parent is not None and proxy.tracer != self.parent:
            self.parent.lift_tracked_freevar_to_input(proxy)
        return new_proxy

    def maybe_lift_tracked_freevar_to_input(self, arg):
        """
        If arg is a free variable, then lift it to be an input.
        Returns the new lifted arg (if arg was a freevar), else the
        original arg.
        """
        if not isinstance(arg, torch.fx.Proxy):
            return arg
        elif arg.tracer == self:
            return arg
        return self.lift_tracked_freevar_to_input(arg)


# NOTE: [HigherOrderOperator tracing design]
# Ignoring HigherOrderOperators for a moment,
# OutputGraph represents the graph being built by Dynamo that may be compiled
# and executed. It holds a root SubgraphTracer where the FX graph is built.
#
# HigherOrderOperators are operators that take functions as their arguments.
# When Dynamo encounters a HigherOrderOperator, then it attempts to introspect
# the function passed to it (call this the "body function"), capture it into a
# GraphModule, and rewrite the call to the HigherOrderOperator to use the
# GraphModule.
#
# The way we handle the capture of body functions is through having
# (possibly nested) SubgraphTracers, one per body function.
#
# Mechanically, we do the introspection by:
# - Creating a new SubgraphTracer via OutputGraph.subtracer
# - Executing the body function.
# This constructs the graph of the body function in the new SubgraphTracer
# while modifying the state of the OutputGraph. For example:
# - the OutputGraph can receive new GraphArgs (if we discover any new
#   untracked Tensors)
# - side effects from the body function get accumulated into
#   OutputGraph.side_effects
# - guards produced by the body function get accumulated into OutputGraph.guards
#
# The traced function has some special properties that make it easier for us
# to transform later down the line:
# - we lift all free variables to being inputs.
#
# If the introspection fails (due to the existence of graph breaks), then
# we roll back the current OutputGraph state and graph break on the
# HigherOrderOperator.
