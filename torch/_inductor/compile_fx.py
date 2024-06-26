import contextlib
import functools
import logging
import os
import sys
import time
import warnings
from itertools import count

from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)
from unittest import mock

from functorch.compile import min_cut_rematerialization_partition

import torch.fx
import torch.utils._pytree as pytree
from torch._dynamo import (
    compiled_autograd,
    config as dynamo_config,
    logging as dynamo_logging,
    utils as dynamo_utils,
)
from torch._dynamo.utils import (
    counters,
    detect_fake_mode,
    lazy_format_graph_code,
    optimus_scuba_log,
)
from torch._functorch.aot_autograd import aot_export_module, make_boxed_func
from torch._inductor.codecache import code_hash, CompiledFxGraph, FxGraphCache
from torch._inductor.cudagraph_utils import BoxedDeviceIndex

from torch._inductor.debug import save_args_for_compile_fx_inner
from torch._inductor.utils import BoxedBool, count_tangents
from torch._logging import trace_structured
from torch._ops import OpOverload
from torch._subclasses.fake_tensor import FakeTensor
from torch._utils_internal import signpost_event
from torch.fx.passes.fake_tensor_prop import FakeTensorProp

from .._dynamo.backends.common import aot_autograd
from ..fx._lazy_graph_module import _use_lazy_graph_module  # type: ignore[attr-defined]
from ..fx.graph import _PyTreeCodeGen
from . import config, metrics
from .debug import DebugContext
from .decomposition import select_decomp_table
from .fx_passes.joint_graph import joint_graph_passes
from .fx_passes.post_grad import post_grad_passes, view_to_reshape
from .fx_passes.pre_grad import pre_grad_passes
from .graph import GraphLowering
from .ir import ExternKernelNode
from .utils import get_dtype_size, has_incompatible_cudagraph_ops, output_node
from .virtualized import V

if config.is_fbcode():
    from torch._inductor.fb.utils import time_and_log
else:
    # no-op decorator
    def time_and_log(attr: str, extra_loggings: Optional[Dict[str, str]] = None):
        return dynamo_utils.identity


log = logging.getLogger(__name__)
perf_hint_log = torch._logging.getArtifactLogger(__name__, "perf_hints")
post_grad_graphs_log = torch._logging.getArtifactLogger(__name__, "post_grad_graphs")
ALIGNMENT = 16


# copy_ fails when trying to write to tensors with memory overlap,
# for expanded dimensions (a dimension which used to have size 1 -> ?)
# we can select one element from that dimension and write to it
# to achieve writing to all values of that dimension of the input tensor
def get_expanded_dims(t):
    if not isinstance(t, torch.Tensor):
        return None
    return [i for i in range(t.ndim) if t.stride(i) == 0 and t.size(i) != 1]


def index_expanded_dims(t: torch.Tensor, expanded_dims: List[int]) -> torch.Tensor:
    for expanded_dim in expanded_dims:
        t = torch.ops.aten.slice(t, expanded_dim, 0, 1)
    return t


def complex_memory_overlap(t: torch.Tensor) -> bool:
    # if torch._debug_has_internal_overlap thinks this tensor potentially has
    # memory overlap internally, let's dig deeper to find out whether it's true.
    t = index_expanded_dims(t, get_expanded_dims(t))
    if torch._debug_has_internal_overlap(t) != 0:
        strides = t.stride()
        sizes = t.shape
        indices = list(range(len(strides)))
        indices = [x for _, x in sorted(zip(strides, indices))]
        for i in range(len(strides)):
            prev_stride = 1 if i == 0 else strides[indices[i - 1]]
            prev_size = 1 if i == 0 else sizes[indices[i - 1]]
            if strides[indices[i]] < prev_stride * prev_size:
                return True
    return False


@functools.lru_cache(None)
def _step_logger():
    return dynamo_logging.get_step_logger(log)


@functools.lru_cache(None)
def _warn_tf32_disabled():
    if (
        torch.cuda.is_available()
        and not torch.backends.cuda.matmul.allow_tf32
        and torch.cuda.get_device_capability() >= (8, 0)
    ):
        warnings.warn(
            "TensorFloat32 tensor cores for float32 matrix multiplication available but not enabled. "
            "Consider setting `torch.set_float32_matmul_precision('high')` for better performance."
        )


def _unlift_graph(mod, gm, graph_signature):
    from torch.export.unflatten import _assign_attr, _AttrKind

    state_dict = {}
    for name, param in mod.named_parameters(remove_duplicate=False):
        state_dict[name] = param
        _assign_attr(
            param,
            gm,
            name,
            attr_kind=_AttrKind.PARAMETER,
        )
    for name, buffer in mod.named_buffers(remove_duplicate=False):
        state_dict[name] = buffer
        _assign_attr(
            buffer,
            gm,
            name,
            attr_kind=_AttrKind.BUFFER,
        )

    placeholder_nodes = [node for node in gm.graph.nodes if node.op == "placeholder"]
    lifted_inputs = []
    for node in placeholder_nodes:
        node_name = node.name
        if node_name in graph_signature.inputs_to_parameters:
            lifted_inputs.append(graph_signature.inputs_to_parameters[node_name])
        elif node_name in graph_signature.inputs_to_buffers:
            lifted_inputs.append(graph_signature.inputs_to_buffers[node_name])
        else:
            assert node_name in graph_signature.user_inputs
            lifted_inputs.append(None)

    from torch.export._unlift import _unlift

    outputs = list(gm.graph.nodes)[-1].args[0]
    mutated_outputs = []
    for out in outputs:
        if out in graph_signature.buffers_to_mutate:
            mutated_outputs.append(graph_signature.buffers_to_mutate[out.name])
        else:
            mutated_outputs.append(None)

    unlifted_gm = _unlift(
        gm,
        lifted_inputs,
        mutated_outputs,
        pytree.LeafSpec(),
        None,
        state_dict,
        {},
    )
    return unlifted_gm


def _get_subgraph_names(gm):
    for node in gm.graph.nodes:
        if node.target == torch.ops.higher_order.cond:
            true_subgraph_name = node.args[1].name
            false_subgraph_name = node.args[2].name
            yield true_subgraph_name
            yield false_subgraph_name


def _recursive_pre_grad_passes(gm, example_inputs):
    for subgraph_name in _get_subgraph_names(gm):
        subgraph = getattr(gm, subgraph_name)
        # as we don't have recursive example inputs, passing None here
        new_subgraph = _recursive_pre_grad_passes(subgraph, example_inputs=None)
        setattr(gm, subgraph_name, new_subgraph)
    return pre_grad_passes(gm, example_inputs)


def _recursive_joint_graph_passes(gm):
    for subgraph_name in _get_subgraph_names(gm):
        subgraph = getattr(gm, subgraph_name)
        _recursive_joint_graph_passes(subgraph)
    joint_graph_passes(gm)


def _recursive_post_grad_passes(gm, is_inference: bool = False):
    for subgraph_name in _get_subgraph_names(gm):
        subgraph = getattr(gm, subgraph_name)
        _recursive_post_grad_passes(subgraph, is_inference)
    post_grad_passes(gm, is_inference)


def split_const_gm(
    gm: torch.fx.GraphModule,
) -> Tuple[torch.fx.GraphModule, Dict[str, int]]:
    """
    This function takes an GraphModule input "gm".
    The gm will be split into 2 components,
      1) const_gm, which consists the subgraph of gm that can be constant folded.
      2) gm (being inplace modified,) which returns the graph after constant folding.

    const_output_index is a mapping of corresponding node name from gm to the
    output index of const_gm.
    Returns (const_gm, const_output_index)
    """
    from torch._inductor.constant_folding import (
        CONST_MODULE_TAG,
        META_TAG,
        MODULE_TAG,
        replace_node_with_constant,
        run_and_get_constant_graph,
    )

    const_gm = run_and_get_constant_graph(gm)
    const_result = const_gm()

    const_outputs = {
        x.name: idx for idx, x in enumerate(tuple(const_gm.graph.nodes)[-1].args[0])
    }

    to_erase_node = []
    to_replace_node = []
    const_output_index = {}
    for node in gm.graph.nodes:
        if node.name in const_outputs:
            to_replace_node.append(node)
        elif node.meta[META_TAG] == CONST_MODULE_TAG:
            to_erase_node.append(node)

    for node in to_replace_node:
        new_const_name = "_FOLDED_CONST_" + node.name
        replace_node_with_constant(
            gm,
            node,
            const_result[const_outputs[node.name]],
            new_const_name,
        )
        const_output_index[new_const_name] = const_outputs[node.name]
    for node in to_erase_node[::-1]:
        if node.users:
            for n in node.users:
                assert n.meta[META_TAG] == MODULE_TAG, f"node: {node} user not empty."
        else:
            gm.graph.erase_node(node)
    gm.recompile()

    return const_gm, const_output_index


def is_tf32_warning_applicable(gm: torch.fx.GraphModule):
    aten = torch.ops.aten
    tf32_ops = {
        aten.mm.default,
        aten.addmm.default,
        aten.bmm.default,
        aten.baddbmm.default,
    }
    for node in gm.graph.nodes:
        if (
            node.op == "call_function"
            and node.target in tf32_ops
            and isinstance(node.meta.get("val", None), torch.Tensor)
            and node.meta["val"].dtype == torch.float32
            and node.meta["val"].device.type == "cuda"
        ):
            return True
    return False


@DebugContext.wrap
def count_bytes_inner(
    gm: torch.fx.GraphModule,
    example_inputs: List[torch.Tensor],
    num_fixed: int = 0,
    **kwargs,
):
    shape_env = _shape_env_from_inputs(example_inputs)
    fake_mode = fake_tensor_prop(gm, example_inputs)

    with V.set_fake_mode(fake_mode):
        _recursive_post_grad_passes(gm, False)

    graph = GraphLowering(gm, shape_env=shape_env, num_static_inputs=num_fixed)
    with V.set_graph_handler(graph), V.set_real_inputs(example_inputs):
        graph.run(*example_inputs)
        num_bytes, nodes_num_elem, node_runtimes = graph.count_bytes()
        metrics.num_bytes_accessed += num_bytes
        metrics.nodes_num_elem += nodes_num_elem
        metrics.node_runtimes += node_runtimes
    return make_boxed_func(gm.forward)


def fake_tensor_prop(
    gm: torch.fx.GraphModule,
    example_inputs: List[torch.Tensor],
    force_allow_non_fake_inputs: bool = False,
):
    """
    If we can not detect fake mode from the context of inputs, create one.

    The created fake mode will be returned.
    """
    fake_mode = detect_fake_mode(example_inputs)
    if not fake_mode:
        fake_mode = torch._subclasses.FakeTensorMode(allow_non_fake_inputs=True)
        FakeTensorProp(gm, mode=fake_mode).propagate(*example_inputs)
    else:
        ctx = (
            contextlib.nullcontext()
            if not force_allow_non_fake_inputs
            else mock.patch.object(fake_mode, "allow_non_fake_inputs", True)
        )
        with ctx:  # type: ignore[attr-defined]
            FakeTensorProp(gm, mode=fake_mode).propagate_dont_convert_inputs(
                *example_inputs
            )

    return fake_mode


# pass config dict back to user
def get_patched_config_dict(config_patches=None) -> Dict[str, Any]:
    with config.patch(config_patches):
        return config.get_config_copy()


@DebugContext.wrap
@torch.utils._python_dispatch._disable_current_modes()
@time_and_log(
    attr="compilation time (in seconds)",
    extra_loggings={"config_dict": str(get_patched_config_dict())},
)
# Need this decorator for compile_fx_inner even if we already have one for
# compile_fx. The reason is the compilation for backward graph may happen after
# compile_fx return and we may want to use the _LazyGraphModule for compiling
# the backward graph as well.
@_use_lazy_graph_module(dynamo_config.use_lazy_graph_module)
@dynamo_utils.dynamo_timed(phase_name="inductor_compile")
def compile_fx_inner(
    gm: torch.fx.GraphModule,
    example_inputs: List[torch.Tensor],
    cudagraphs: Optional[BoxedBool] = None,
    num_fixed: int = 0,
    is_backward: bool = False,
    graph_id: Optional[int] = None,
    cpp_wrapper: bool = False,
    aot_mode: bool = False,
    is_inference: bool = False,
    boxed_forward_device_index: Optional[BoxedDeviceIndex] = None,
    user_visible_outputs: FrozenSet[str] = frozenset(),
    layout_opt: Optional[bool] = None,
    extern_node_serializer: Optional[Callable[[List[ExternKernelNode]], Any]] = None,
) -> Union[CompiledFxGraph, str]:
    """
    Inductor API that compiles a single graph.

    If you change the argument list for this function, make sure you
    also update the call to save_args_for_compile_fx_inner below accordingly.
    """
    if dynamo_utils.count_calls(gm.graph) == 0 and not aot_mode:
        # trigger the real recompilation for _LazyGraphModule before returning
        # the forward method.
        from torch.fx._lazy_graph_module import _LazyGraphModule

        _LazyGraphModule.force_recompile(gm)
        return make_boxed_func(gm.forward)

    assert isinstance(
        next(iter(reversed(gm.graph.nodes))).args[0], (tuple, list)
    ), f"inductor can only compile FX graphs which return a tuple/list, but got {gm.graph}"

    if config.save_args:
        save_args_for_compile_fx_inner(
            gm,
            example_inputs,
            cudagraphs=cudagraphs,
            num_fixed=num_fixed,
            is_backward=is_backward,
            graph_id=graph_id,
            cpp_wrapper=cpp_wrapper,
            aot_mode=aot_mode,
            is_inference=is_inference,
            boxed_forward_device_index=boxed_forward_device_index,
            user_visible_outputs=user_visible_outputs,
            layout_opt=layout_opt,
        )

    if cudagraphs is None:
        cudagraphs = BoxedBool(config.triton.cudagraphs)

    # Inputs to fx_codegen_and_compile
    # Anything that affects codegen should go here, so if the signature
    # of fx_codegen_and_compile changes, the dict should be updated accordingly
    graph_kwargs = {
        "cudagraphs": cudagraphs,
        "num_fixed": num_fixed,
        "is_backward": is_backward,
        "graph_id": graph_id,
        "cpp_wrapper": cpp_wrapper,
        "aot_mode": aot_mode,
        "is_inference": is_inference,
        "user_visible_outputs": user_visible_outputs,
        "layout_opt": layout_opt,
        "extern_node_serializer": extern_node_serializer,
    }

    start = time.time()

    if config.fx_graph_cache and not aot_mode:
        compiled_graph = FxGraphCache.load(
            fx_codegen_and_compile, gm, example_inputs, graph_kwargs
        )
    else:
        compiled_graph = fx_codegen_and_compile(
            gm, example_inputs, **graph_kwargs  # type: ignore[arg-type]
        )

    log.debug("FX codegen and compilation took %.3fs", time.time() - start)

    # check cudagraph disabling reasons from inductor lowering
    if cudagraphs and compiled_graph.disabled_cudagraphs_reason:
        perf_hint_log.warning(
            "skipping cudagraphs due to %s", compiled_graph.disabled_cudagraphs_reason
        )
        BoxedBool.disable(cudagraphs)

    # Return the output strides to the caller via TracingContext
    context = torch._guards.TracingContext.try_get()
    if context is not None and context.output_strides is not None:
        assert len(context.output_strides) == 0
        context.output_strides.extend(compiled_graph.output_strides)

    if aot_mode:
        return compiled_graph

    if cudagraphs:
        # output args are tuple of first argument
        output = output_node(gm)
        assert len(output.args) == 1
        stack_traces = [
            (arg.stack_trace if isinstance(arg, torch.fx.node.Node) else None)
            for arg in output.args[0]
        ]

        complex_memory_overlap_inputs = any(
            complex_memory_overlap(t)
            for t in example_inputs
            if isinstance(t, torch.Tensor)
        )

        from torch._inductor.cudagraph_utils import check_for_mutation

        has_mutation_str = check_for_mutation(gm, compiled_graph, num_fixed)
        has_mutation = has_mutation_str is not None

        if has_mutation:
            compiled_graph.disabled_cudagraphs_reason = has_mutation_str

        cudagraph_tests = [
            (not has_mutation, "mutated inputs"),
            (not has_incompatible_cudagraph_ops(gm), "incompatible ops"),
            (not complex_memory_overlap_inputs, "complex memory overlap"),
            (
                all(
                    isinstance(t, (torch.Tensor, torch.SymInt)) for t in example_inputs
                ),
                "non-Tensor inputs",
            ),
        ]
        cudagraph_fail_reasons = [s for b, s in cudagraph_tests if not b]

        if not cudagraph_fail_reasons:
            if not config.triton.cudagraph_trees:
                # Force specialize all inputs so that CUDA graphs will work
                for t in example_inputs:
                    if isinstance(t, torch.SymInt):
                        int(t)  # guard

            if (
                boxed_forward_device_index is not None
                and not is_inference
                and not is_backward
            ):
                boxed_forward_device_index.set(next(iter(compiled_graph.device_idxs)))

            compiled_graph.current_callable = cudagraphify(
                compiled_graph.get_current_callable(),
                example_inputs,
                static_input_idxs=range(num_fixed),
                device_index=next(iter(compiled_graph.device_idxs)),
                stack_traces=stack_traces,
                is_backward=is_backward,
                is_inference=is_inference,
                constants=tuple(compiled_graph.constants.values()),
            )
        else:
            BoxedBool.disable(cudagraphs)

            # See [Backward Generation Handling]
            # if cudagraph'd the forward and set the device, we need to let the cudagraph manager
            # know we are we running the backward even if we will not run it in cudagraphs
            if is_backward and config.triton.cudagraph_trees:
                assert boxed_forward_device_index is not None
                assert boxed_forward_device_index.value is not None
                compiled_graph_callable = compiled_graph.get_current_callable()

                manager = torch._inductor.cudagraph_trees.get_manager(
                    boxed_forward_device_index.value, create_if_none_exists=False
                )
                # should already exist from forward
                assert manager is not None

                def compiled_artifact(new_inputs):
                    manager.set_to_running_backward()
                    return compiled_graph_callable(new_inputs)

                compiled_graph.current_callable = compiled_artifact

            if "cuda" in compiled_graph.device_types:
                # prefer better disable_cudagraphs_reason bc stack trace
                # TODO: migrate all disable reasons to stack trace, refactor
                if compiled_graph.disabled_cudagraphs_reason:
                    perf_hint_log.warning(compiled_graph.disabled_cudagraphs_reason)
                else:
                    perf_hint_log.warning(
                        "skipping cudagraphs due to %s", cudagraph_fail_reasons
                    )

    # cudagraphs does its own aligning of inputs
    if not cudagraphs:
        new_callable = align_inputs(
            compiled_graph.get_current_callable(), example_inputs, range(num_fixed)
        )
        if new_callable is not compiled_graph.get_current_callable():
            compiled_graph.current_callable = new_callable

    _step_logger()(
        logging.INFO,
        "torchinductor done compiling "
        f"{'BACKWARDS' if is_backward else 'FORWARDS'} "
        f"graph {graph_id}",
    )

    # aot autograd needs to know to pass in inputs as a list
    compiled_graph._boxed_call = True
    return compiled_graph


def fx_codegen_and_compile(
    gm: torch.fx.GraphModule,
    example_inputs: List[torch.Tensor],
    cudagraphs: Optional[BoxedBool] = None,
    num_fixed: int = 0,
    is_backward: bool = False,
    graph_id: Optional[int] = None,
    cpp_wrapper: bool = False,
    aot_mode: bool = False,
    is_inference: bool = False,
    user_visible_outputs: FrozenSet[str] = frozenset(),
    layout_opt: Optional[bool] = None,
    extern_node_serializer: Optional[Callable[[List[ExternKernelNode]], Any]] = None,
) -> Union[CompiledFxGraph, str]:
    if is_tf32_warning_applicable(gm):
        _warn_tf32_disabled()

    # lift the maximum depth of the Python interpreter stack
    # to adapt large/deep models
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 2000))

    _step_logger()(
        logging.INFO,
        "torchinductor compiling "
        f"{'BACKWARDS' if is_backward else 'FORWARDS'} "
        f"graph {graph_id}",
    )
    V.debug.fx_graph(gm, example_inputs)
    # TODO: Should we actually dump this?  It should be redundant with the aot
    # structured logs...
    # trace_structured("inductor_input_graph", payload_fn=lambda: gm.print_readable(print_output=False))

    shape_env = _shape_env_from_inputs(example_inputs)

    # Convert view to reshape in the graph. This is necessary primarily for
    # layout optimization. Do it unconditionally for uniformity.
    #
    # It's needed because when we do layout optimization, an contiguous tensor
    # in eager mode may becomes a channels last tensor. A view op previously
    # can be applied to the contiguous tensor may not be able to be applied
    # on the channels tensor any more. An error like
    #   RuntimeError: view size is not compatible with input tensor's size and stride
    #   (at least one dimension spans across two contiguous subspaces). Use .reshape(...) instead.
    # will be printed.
    #
    # Replace view op to reshape op in this case.
    # As an example, timm_resnest/botnet26t_256/convnext_base etc. will fail if we don't do this.
    #
    # Also this has to be done before FakeTensorProp below to avoid the failed
    # .view() call.
    view_to_reshape(gm)

    # It is safe to run FakeTensorProp under no_grad because by the time
    # we're in inductor, we assume that AOTAutograd has already "taken care"
    # of autograd, so there should be no more autograd-related API's in the
    # graph.
    with torch.no_grad():
        fake_mode = fake_tensor_prop(gm, example_inputs)

    # pattern matcher passes might not preserve striding information
    # on node.meta["val"]. if in the future we rely on these being
    # correct we will need to fix.

    with V.set_fake_mode(fake_mode):
        # has some issues with memory in training
        _recursive_post_grad_passes(gm, is_inference=is_inference)
        V.debug.fx_graph_transformed(gm, example_inputs)
        post_grad_graphs_log.debug("%s", lazy_format_graph_code("AFTER POST GRAD", gm))
        trace_structured(
            "inductor_post_grad_graph",
            payload_fn=lambda: gm.print_readable(print_output=False),
        )
        optimus_scuba_log["inductor_post_grad"] = counters["inductor"]
        signpost_event(
            "optimus",
            "compile_fx.post_grad_passes",
            optimus_scuba_log,
        )

    with V.set_fake_mode(fake_mode):
        const_output_index = None
        const_graph = None
        const_code = None

        if aot_mode and config.aot_inductor.use_runtime_constant_folding:
            const_gm, const_output_index = split_const_gm(gm)

            const_graph = GraphLowering(
                const_gm,
                example_inputs=[],
                shape_env=shape_env,
                num_static_inputs=num_fixed,
                graph_id=graph_id,
                cpp_wrapper=cpp_wrapper,
                aot_mode=aot_mode,
                user_visible_outputs=user_visible_outputs,
                extern_node_serializer=extern_node_serializer,
                is_inference=is_inference,
                is_const_graph=True,
            )
            with V.set_graph_handler(const_graph):
                assert cpp_wrapper, "AOT mode only supports C++ wrapper"
                const_graph.run()

                const_code, _ = const_graph.codegen_with_cpp_wrapper()

        graph = GraphLowering(
            gm,
            # example_inputs will be used by AOTInductor to dry-run the generated code for Triton kernel tuning.
            # For the forward pass, we have the real inputs to be used as example_inputs. For the backward pass,
            # we currently use fake tensors and defake them later.
            example_inputs=example_inputs,
            shape_env=shape_env,
            num_static_inputs=num_fixed,
            graph_id=graph_id,
            cpp_wrapper=cpp_wrapper,
            aot_mode=aot_mode,
            user_visible_outputs=user_visible_outputs,
            extern_node_serializer=extern_node_serializer,
            is_inference=is_inference,
            const_output_index=const_output_index,
            const_code=const_code,
            const_module=const_graph,
        )
        with V.set_graph_handler(graph):
            graph.run(*example_inputs)
            output_strides: List[Optional[Tuple[int, ...]]] = []
            if graph.graph_outputs is not None:
                # We'll put the output strides in the compiled graph so we
                # can later return them to the caller via TracingContext
                for out in graph.graph_outputs:
                    if hasattr(out, "layout"):
                        output_strides.append(
                            tuple(
                                V.graph.sizevars.size_hint(s) for s in out.layout.stride
                            )
                        )
                    else:
                        output_strides.append(None)

            metrics_helper = metrics.CachedMetricsHelper()
            compiled_fn = graph.compile_to_fn()

            if V.aot_compilation is True:
                return compiled_fn

            if cudagraphs and not V.graph.disable_cudagraphs_reason:
                from torch._inductor.cudagraph_utils import (
                    check_lowering_disable_cudagraph,
                )

                V.graph.disable_cudagraphs_reason = check_lowering_disable_cudagraph(
                    V.graph.device_node_mapping
                )

            compiled_graph = CompiledFxGraph(
                compiled_fn,
                graph,
                output_strides,
                V.graph.disable_cudagraphs_reason,
                metrics_helper.get_deltas(),
            )

    return compiled_graph


def clone_preserve_strides(x: torch.Tensor):
    needed_size = (
        sum((shape - 1) * stride for shape, stride in zip(x.size(), x.stride())) + 1
    )
    buffer = torch.as_strided(x, (needed_size,), (1,)).clone()
    return torch.as_strided(buffer, x.size(), x.stride())


def copy_misaligned_inputs(
    new_inputs: List[torch.Tensor], check_inputs_idxs: Sequence[int]
) -> None:
    for i in check_inputs_idxs:
        if new_inputs[i].data_ptr() % ALIGNMENT:
            new_inputs[i] = clone_preserve_strides(new_inputs[i])


def get_input_idxs_to_check(
    inputs: Union[List[torch.Tensor], Sequence[int]],
    static_input_idxs: Sequence[int],
) -> Sequence[int]:
    def is_aligned(storage_offset, dtype):
        return (storage_offset * get_dtype_size(dtype)) % ALIGNMENT == 0

    ids_to_check = []
    for i, input in enumerate(inputs):
        if (
            isinstance(input, torch.Tensor)
            and (
                i not in static_input_idxs
                or not is_aligned(input.storage_offset(), input.dtype)
            )
            and input.device.type == "cuda"
        ):
            ids_to_check.append(i)
    return ids_to_check


def align_inputs_from_check_idxs(
    model: Callable[[List[torch.Tensor]], Any], inputs_to_check: Sequence[int]
):
    if len(inputs_to_check) == 0:
        return model

    def run(new_inputs):
        copy_misaligned_inputs(new_inputs, inputs_to_check)
        return model(new_inputs)

    return run


def align_inputs(
    model: Callable[[List[torch.Tensor]], Any],
    inputs: List[torch.Tensor],
    static_input_idxs: Sequence[int] = (),
):
    inputs_to_check = get_input_idxs_to_check(inputs, static_input_idxs)
    return align_inputs_from_check_idxs(model, inputs_to_check)


@dynamo_utils.dynamo_timed
def cudagraphify(
    model: torch.fx.GraphModule,
    inputs: List[torch.Tensor],
    static_input_idxs: Sequence[int] = (),
    *,
    device_index: int,
    stack_traces: List[Optional[str]],
    is_backward: bool,
    is_inference: bool,
    constants: Tuple[torch.Tensor, ...] = (),
):
    from torch._inductor.cudagraph_trees import (
        cudagraphify_impl as new_cudagraphify_impl,
    )

    cudagraphify_fn: Callable[..., Any]
    if config.triton.cudagraph_trees:
        cudagraphify_fn = functools.partial(
            new_cudagraphify_impl,
            device_index=device_index,
            stack_traces=stack_traces,
            is_backward=is_backward,
            is_inference=is_inference,
            constants=constants,
        )
    else:
        cudagraphify_fn = cudagraphify_impl

    # if using fake tensors, defer cudagraphs until we get real inputs at runtime
    if not any(isinstance(inp, FakeTensor) for inp in inputs):
        return cudagraphify_fn(model, inputs, static_input_idxs)

    compiled_fn = None

    def run(new_inputs):
        nonlocal compiled_fn
        if compiled_fn is None:
            with dynamo_utils.preserve_rng_state():
                compiled_fn = cudagraphify_fn(model, new_inputs, static_input_idxs)
        return compiled_fn(new_inputs)

    return run


def remove_unaligned_input_idxs(
    inputs: Union[List[torch.Tensor], Sequence[int]],
    static_input_idxs: Sequence[int],
):
    """
    We require all inputs to be aligned, so introduce a copy for any
    that aren't.
    """
    aligned_static_input_idxs = []
    for idx, input in zip(static_input_idxs, inputs):
        if isinstance(input, torch.Tensor) and (input.data_ptr() % ALIGNMENT) == 0:
            aligned_static_input_idxs.append(idx)
    if len(aligned_static_input_idxs) != len(static_input_idxs):
        return aligned_static_input_idxs
    return static_input_idxs


def static_input(x: torch.Tensor):
    """
    Copy and input while preserving strides
    """
    # TODO(jansel): figure out why this version doesn't work:
    # return torch.empty_strided(x.size(), x.stride(), dtype=x.dtype, device=x.device)
    needed_size = (
        sum((shape - 1) * stride for shape, stride in zip(x.size(), x.stride())) + 1
    )
    buffer = torch.empty(needed_size, dtype=x.dtype, device=x.device)
    return torch.as_strided(buffer, x.size(), x.stride())


def index_expanded_dims_and_copy_(
    dst: torch.Tensor,
    src: torch.Tensor,
    expanded_dims: List[int],
):
    "Index into expanded dimensions of both dst and src then copy_"
    dst = index_expanded_dims(dst, expanded_dims)
    src = index_expanded_dims(src, expanded_dims)
    dst.copy_(src)


def cudagraphify_impl(
    model: torch.fx.GraphModule,
    inputs: List[torch.Tensor],
    static_input_idxs: Sequence[int] = (),
):
    """
    Assumes inputs[static_input_idxs[i]] are always the same memory address
    """
    check_input_idxs = get_input_idxs_to_check(inputs, static_input_idxs)
    static_input_idxs = remove_unaligned_input_idxs(inputs, static_input_idxs)
    copy_misaligned_inputs(inputs, check_input_idxs)

    assert isinstance(inputs, list)

    inps_expanded_dims = [
        get_expanded_dims(x) if idx not in static_input_idxs else []
        for idx, x in enumerate(inputs)
    ]

    # allocate static tensor inputs
    static_inputs = [
        x
        if not isinstance(x, torch.Tensor)
        else static_input(x)
        if idx not in static_input_idxs
        else x.detach()
        for idx, x in enumerate(inputs)
    ]

    # copy over input values for fresh allocations
    for idx, (x, expanded_dims) in enumerate(zip(inputs, inps_expanded_dims)):
        if isinstance(x, torch.Tensor) and idx not in static_input_idxs:
            index_expanded_dims_and_copy_(static_inputs[idx], x, expanded_dims)

    # warmup
    torch.cuda.synchronize()
    stream = torch.cuda.Stream()
    stream.wait_stream(torch.cuda.current_stream())
    # copy static_inputs because it will be cleared in model
    with torch.cuda.stream(stream):
        model(list(static_inputs))
    stream.synchronize()
    torch.cuda.current_stream().wait_stream(stream)
    torch.cuda.synchronize()

    # record
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph, stream=stream, capture_error_mode="thread_local"):
        static_outputs = model(list(static_inputs))
    if not isinstance(static_outputs, (list, tuple)):
        static_outputs = (static_outputs,)

    if config.size_asserts:

        def run(new_inputs):
            assert len(static_inputs) == len(new_inputs)
            for idx, (dst, src, expanded_dims) in enumerate(
                zip(static_inputs, new_inputs, inps_expanded_dims)
            ):
                if not isinstance(dst, torch.Tensor):
                    pass
                elif idx in static_input_idxs:
                    assert dst.data_ptr() == src.data_ptr()
                else:
                    # TODO - could make one single op of multiple slices
                    # and avoid dispatch.
                    # Could also pre-index the `dst` tensors
                    index_expanded_dims_and_copy_(dst, src, expanded_dims)
            new_inputs.clear()
            graph.replay()
            return static_outputs

    else:
        copy_indices = [
            idx for idx in range(len(static_inputs)) if idx not in static_input_idxs
        ]

        def run(new_inputs):
            for idx in copy_indices:
                expanded_dims = inps_expanded_dims[idx]
                index_expanded_dims_and_copy_(
                    static_inputs[idx], new_inputs[idx], expanded_dims
                )
            new_inputs.clear()
            graph.replay()
            return static_outputs

    return align_inputs_from_check_idxs(run, check_input_idxs)


def compile_fx_aot(
    model_: torch.fx.GraphModule,
    example_inputs_: List[torch.Tensor],
    inner_compile: Callable[..., Any] = compile_fx_inner,
    config_patches: Optional[Dict[str, Any]] = None,
):
    config_patches: Dict[str, Any] = (
        {"cpp_wrapper": True}
        if config_patches is None
        else {**config_patches, "cpp_wrapper": True}
    )
    if (
        "aot_inductor.output_path" not in config_patches
        and not config.aot_inductor.output_path
    ):
        config_patches = {
            **config_patches,
            "aot_inductor.output_path": code_hash(model_.code),
        }

    extern_node_serializer = config_patches.pop("extern_node_serializer", None)
    with V.set_aot_compilation(True):
        compiled_lib_path = compile_fx(
            model_,
            example_inputs_,
            inner_compile=functools.partial(
                inner_compile,
                aot_mode=True,
                extern_node_serializer=extern_node_serializer,
            ),
            config_patches=config_patches,
        )
        assert os.path.exists(
            compiled_lib_path
        ), f"AOTInductor compiled library does not exist at {compiled_lib_path}"
        return compiled_lib_path


_graph_counter = count(0)


def fw_compiler_freezing(
    aot_autograd_model: torch.fx.GraphModule,
    aot_example_inputs: List[torch.Tensor],
    dynamo_model: torch.fx.GraphModule,
    num_example_inputs: int,
    inner_compile: Callable[..., Any],
    cudagraphs: BoxedBool,
    graph_id: int,
    forward_device: BoxedDeviceIndex,
):
    from torch._inductor.freezing import convert_conv_weights_to_channels_last, freeze

    # partition_fn won't be called
    _recursive_joint_graph_passes(aot_autograd_model)

    layout_opt = GraphLowering.decide_layout_opt(aot_autograd_model, is_inference=True)
    if layout_opt:
        # make sure meta['val'] is properly setup
        fake_tensor_prop(aot_autograd_model, aot_example_inputs, True)
        convert_conv_weights_to_channels_last(aot_autograd_model)

    opt_model, preserved_arg_indices = freeze(
        dynamo_model,
        aot_autograd_model,
        aot_example_inputs,  # type: ignore[arg-type]
    )

    aot_example_inputs = [aot_example_inputs[ind] for ind in preserved_arg_indices]
    num_fixed = len(preserved_arg_indices) - num_example_inputs

    fake_mode = detect_fake_mode(aot_example_inputs)

    # for freezing, all graph outputs should be user visible
    *_, model_outputs_node = opt_model.graph.nodes
    model_outputs = model_outputs_node.args[0]
    user_visible_outputs = [
        n.name for n in model_outputs if isinstance(n, torch.fx.Node)
    ]

    # constant params will be real tensors, not fake
    tracing_context = torch._guards.TracingContext.try_get()
    if tracing_context is not None:
        params_flat = tracing_context.params_flat
        assert params_flat is not None
        for i in range(len(params_flat)):
            if i not in preserved_arg_indices:
                params_flat[i] = None

    with mock.patch.object(fake_mode, "allow_non_fake_inputs", True):
        optimized_function = inner_compile(
            opt_model,
            aot_example_inputs,
            num_fixed=num_fixed,
            cudagraphs=cudagraphs,
            graph_id=graph_id,
            is_inference=True,
            boxed_forward_device_index=forward_device,
            layout_opt=layout_opt,
            user_visible_outputs=user_visible_outputs,
        )

    # aot_inductor codegens a call that takes in just the inputs, so we don't return a wrapper
    # that drops constant-ified params
    if V.aot_compilation is True:
        return optimized_function

    def wrapper(args):
        args_new = [args[i] for i in preserved_arg_indices]
        args.clear()
        return optimized_function(args_new)

    wrapper._boxed_call = True  # type: ignore[attr-defined]

    return wrapper


@_use_lazy_graph_module(dynamo_config.use_lazy_graph_module)
def compile_fx(
    model_: torch.fx.GraphModule,
    example_inputs_: List[torch.Tensor],
    inner_compile: Callable[..., Any] = compile_fx_inner,
    config_patches: Optional[Dict[str, Any]] = None,
    decompositions: Optional[Dict[OpOverload, Callable[..., Any]]] = None,
):
    """Main entrypoint to a compile given FX graph"""
    if config_patches:
        with config.patch(config_patches):
            return compile_fx(
                model_,
                example_inputs_,
                # need extra layer of patching as backwards is compiled out of scope
                inner_compile=config.patch(config_patches)(inner_compile),
                decompositions=decompositions,
            )

    if config.cpp_wrapper:
        with config.patch(
            {
                "cpp_wrapper": False,
                "triton.autotune_cublasLt": False,
                "triton.cudagraphs": False,
                "triton.store_cubin": True,
            }
        ), V.set_real_inputs(example_inputs_):
            inputs_ = example_inputs_
            if isinstance(model_, torch.fx.GraphModule):
                fake_inputs = [
                    node.meta.get("val")
                    for node in model_.graph.nodes
                    if node.op == "placeholder"
                ]
                if all(v is not None for v in fake_inputs):
                    # Validate devices before switching to fake tensors.
                    for idx, fi, i in zip(count(), fake_inputs, inputs_):
                        if fi.device != i.device:
                            raise ValueError(
                                f"Device mismatch between fake input and example input at position #{idx}: "
                                f"{fi.device} vs {i.device}. If the model was exported via torch.export(), "
                                "make sure torch.export() and torch.aot_compile() run on the same device."
                            )
                    inputs_ = fake_inputs
            return compile_fx(
                model_,
                inputs_,
                inner_compile=functools.partial(inner_compile, cpp_wrapper=True),
                decompositions=decompositions,
            )

    recursive_compile_fx = functools.partial(
        compile_fx,
        inner_compile=inner_compile,
        decompositions=decompositions,
    )

    if not graph_returns_tuple(model_):
        return make_graph_return_tuple(
            model_,
            example_inputs_,
            recursive_compile_fx,
        )

    if isinstance(model_, torch.fx.GraphModule):
        if isinstance(model_.graph._codegen, _PyTreeCodeGen):
            # this graph is the result of dynamo.export()
            return handle_dynamo_export_graph(
                model_,
                example_inputs_,
                recursive_compile_fx,
            )

        model_ = _recursive_pre_grad_passes(model_, example_inputs_)
        optimus_scuba_log["inductor_pre_grad"] = counters["inductor"]
        signpost_event(
            "optimus",
            "compile_fx.pre_grad_passes",
            optimus_scuba_log,
        )

    if any(isinstance(x, (list, tuple, dict)) for x in example_inputs_):
        return flatten_graph_inputs(
            model_,
            example_inputs_,
            recursive_compile_fx,
        )

    assert not config._raise_error_for_testing
    num_example_inputs = len(example_inputs_)
    cudagraphs = BoxedBool(config.triton.cudagraphs)
    forward_device = BoxedDeviceIndex(None)

    graph_id = next(_graph_counter)

    decompositions = (
        decompositions if decompositions is not None else select_decomp_table()
    )

    @dynamo_utils.dynamo_timed
    def fw_compiler_base(
        model: torch.fx.GraphModule,
        example_inputs: List[torch.Tensor],
        is_inference: bool,
    ):
        if is_inference:
            # partition_fn won't be called
            _recursive_joint_graph_passes(model)

        fixed = torch._inductor.utils.num_fw_fixed_arguments(
            num_example_inputs, len(example_inputs)
        )
        user_visible_outputs = set()

        if config.keep_output_stride:
            *_, model_outputs_node = model.graph.nodes
            assert model_outputs_node.op == "output"
            model_outputs = pytree.arg_tree_leaves(*model_outputs_node.args)
            num_model_outputs = len(model_outputs)

            context = torch._guards.TracingContext.try_get()
            # See Note [User Outputs in the inductor graph]
            if context is not None and context.fw_metadata and not is_inference:
                original_output_start_index = (
                    context.fw_metadata.num_mutated_inp_runtime_indices
                )
            else:
                original_output_start_index = 0

            if isinstance(model_, torch.fx.GraphModule):
                *_, orig_model_outputs_node = model_.graph.nodes
                assert orig_model_outputs_node.op == "output"
                orig_model_outputs, _ = pytree.tree_flatten(
                    orig_model_outputs_node.args
                )
                num_orig_model_outputs = len(orig_model_outputs)
            else:
                num_orig_model_outputs = num_model_outputs

            assert num_orig_model_outputs <= num_model_outputs

            # Note [User Outputs in the inductor graph]
            # We makes the following assumption
            # For inference
            #   len(orig_model_outputs) == len(model_outputs)
            # For training
            #   len(orig_model_outputs) <= len(model_outputs)
            # During training, most of the time the model_outputs starts with
            # original module's outputs followed by saved activations.
            # But this can be not true if the model have inplace updated tensors.
            # AOTAutograd will make those tensors being returned before the original
            # module's output.
            # To make things safe, we'll use original_output_start_index field
            # set by AOTAutograd to decide where the original module outputs start.
            orig_output_end_idx = original_output_start_index + num_orig_model_outputs
            # Sanity chec: we are about to splice out the "user" outputs from the full set
            # of "graph" outputs. Make sure we're within bounds.
            assert orig_output_end_idx <= num_model_outputs

            user_visible_outputs = {
                n.name
                for n in model_outputs[original_output_start_index:orig_output_end_idx]
                if isinstance(n, torch.fx.Node)
            }

        return inner_compile(
            model,
            example_inputs,
            num_fixed=fixed,
            cudagraphs=cudagraphs,
            graph_id=graph_id,
            is_inference=is_inference,
            boxed_forward_device_index=forward_device,
            user_visible_outputs=user_visible_outputs,
        )

    fw_compiler = functools.partial(fw_compiler_base, is_inference=False)

    if config.freezing and not torch.is_grad_enabled():
        inference_compiler = functools.partial(
            fw_compiler_freezing,
            dynamo_model=model_,
            num_example_inputs=num_example_inputs,
            inner_compile=inner_compile,
            cudagraphs=cudagraphs,
            graph_id=graph_id,
            forward_device=forward_device,
        )
    else:
        inference_compiler = functools.partial(fw_compiler_base, is_inference=True)

    def partition_fn(graph, joint_inputs, **kwargs):
        _recursive_joint_graph_passes(graph)
        return min_cut_rematerialization_partition(
            graph, joint_inputs, **kwargs, compiler="inductor"
        )

    @dynamo_utils.dynamo_timed
    @dynamo_utils.maybe_cprofile
    def bw_compiler(model: torch.fx.GraphModule, example_inputs: List[torch.Tensor]):
        fixed = count_tangents(model)
        return inner_compile(
            model,
            example_inputs,
            num_fixed=fixed,
            cudagraphs=cudagraphs,
            is_backward=True,
            graph_id=graph_id,
            boxed_forward_device_index=forward_device,
        )

    # TODO: can add logging before/after the call to create_aot_dispatcher_function
    # in torch._functorch/aot_autograd.py::aot_module_simplified::aot_function_simplified::new_func
    # once torchdynamo is merged into pytorch

    fake_mode = detect_fake_mode(example_inputs_) or torch._subclasses.FakeTensorMode(
        allow_non_fake_inputs=True
    )
    tracing_context = (
        torch._guards.TracingContext.try_get()
        or torch._guards.TracingContext(fake_mode)
    )

    if V.aot_compilation is True:
        gm, graph_signature = aot_export_module(
            model_, example_inputs_, trace_joint=False, decompositions=decompositions
        )
        unlifted_gm = _unlift_graph(model_, gm, graph_signature)
        if "dynamo_flat_name_to_original_fqn" in model_.meta:
            unlifted_gm.meta["dynamo_flat_name_to_original_fqn"] = model_.meta[
                "dynamo_flat_name_to_original_fqn"
            ]
        with V.set_fake_mode(fake_mode), compiled_autograd.disable():
            return inference_compiler(unlifted_gm, example_inputs_)

    with V.set_fake_mode(fake_mode), torch._guards.tracing(
        tracing_context
    ), compiled_autograd.disable():
        return aot_autograd(
            fw_compiler=fw_compiler,
            bw_compiler=bw_compiler,
            inference_compiler=inference_compiler,
            decompositions=decompositions,
            partition_fn=partition_fn,
            keep_inference_input_mutations=True,
        )(model_, example_inputs_)


def _shape_env_from_inputs(inputs: List[torch.Tensor]):
    shape_env = None
    fake_mode = detect_fake_mode(inputs)

    # TODO(voz): It would be nice to enable this assert, but there are lots of tests that
    # pass in real inputs for now.
    # if len(inputs) > 0:
    # assert fake_mode is not None, breakpoint()

    if fake_mode is not None:
        return fake_mode.shape_env

    # When there are no tensor inputs, get shape_env from the first SymInt.
    for input in inputs:
        if isinstance(input, torch.SymInt):
            return input.node.shape_env

    # TODO(voz): Should we always have one anyway?
    return None


def graph_returns_tuple(gm: torch.fx.GraphModule):
    """True if a FX graph returns a tuple"""
    if not isinstance(gm, torch.fx.GraphModule):
        return True  # can't check this, assume true
    (rv,) = output_node(gm).args
    if isinstance(rv, (list, tuple)):
        return True
    if (
        isinstance(rv, torch.fx.node.Node)
        and hasattr(rv.target, "_schema")
        and len(rv.target._schema.returns) > 1
        and all(str(ret.type) == "Tensor" for ret in rv.target._schema.returns)
    ):
        # for graphs whose result is one node with multiple outputs
        return True
    return False


def make_graph_return_tuple(
    gm: torch.fx.GraphModule,
    inputs: List[torch.Tensor],
    compile_gm: Callable[..., Any],
):
    """
    Mutate gm so it returns a tuple.  This is only needed for graphs
    not created by torchdynamo that return non-tuples.
    """
    node = output_node(gm)
    (rv,) = node.args
    rv, spec = pytree.tree_flatten(rv)
    with gm.graph.inserting_before(node):
        gm.graph.output(rv)
    gm.graph.erase_node(node)
    assert graph_returns_tuple(gm)

    compiled_fn = compile_gm(gm, inputs)

    @functools.wraps(compiled_fn)
    def wrapper(*args, **kwargs):
        return pytree.tree_unflatten(compiled_fn(*args, **kwargs), spec)

    return wrapper


def flatten_graph_inputs(gm: torch.fx.GraphModule, inputs, compile_gm):
    """
    Mutate inputs so that they are flat and wrap gm such that it
    accepts those inputs.  This is only needed for graphs not created
    by torchdynamo that take bumpy inputs.
    """
    inputs, spec = pytree.tree_flatten(inputs)

    class GmWrapper(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.gm = gm

        def forward(self, *args):
            args: List[Any] = list(args)
            return self.gm(*pytree.tree_unflatten(args, spec))

    compiled_fn = compile_gm(GmWrapper(), inputs)

    @functools.wraps(compiled_fn)
    def wrapper(*args):
        # note this doesn't check the spec, assuming it is the same
        return compiled_fn(*pytree.arg_tree_leaves(*args))

    return wrapper


def handle_dynamo_export_graph(
    gm: torch.fx.GraphModule,
    inputs: List[torch.Tensor],
    compile_gm: Callable[..., Any],
):
    """
    `torch._dynamo.export` embeds pytrees in the FX graph codegen object,
    convert that to a normal FX graph so inductor can compile it.
    """
    codegen = gm.graph._codegen
    gm.graph._codegen = torch.fx.graph.CodeGen()
    gm.recompile()

    compiled_fn = compile_gm(gm, codegen.process_inputs(*inputs))

    @functools.wraps(compiled_fn)
    def wrapper(*args):
        return codegen.process_outputs(compiled_fn(*codegen.process_inputs(*args)))

    return wrapper
