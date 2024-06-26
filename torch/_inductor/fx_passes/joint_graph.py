import logging
import typing
from collections import Counter
from typing import Dict, List, Set

import torch
import torch._guards
from torch._inductor.constant_folding import ConstantFolder
from torch.multiprocessing.reductions import StorageWeakRef

from .. import config
from ..pattern_matcher import (
    CallFunction,
    init_once_fakemode,
    KeywordArg,
    Match,
    PatternMatcherPass,
    register_graph_pattern,
    stable_topological_sort,
)
from .replace_random import replace_random_passes

log = logging.getLogger(__name__)
patterns = PatternMatcherPass()


@init_once_fakemode
def lazy_init():
    from .fuse_attention import _sfdp_init
    from .misc_patterns import _misc_patterns_init
    from .pad_mm import _pad_mm_init

    _pad_mm_init()
    _sfdp_init()
    _misc_patterns_init()


@torch.utils._python_dispatch._disable_current_modes()
def remove_no_ops(
    gm: torch.fx.GraphModule, zeros: Set[torch.fx.Node], ones: Set[torch.fx.Node]
):
    "Removes no-ops: (+ 0, - 0, * 1, / 1)"
    aten = torch.ops.aten
    graph = gm.graph

    def fake_tensors_eq(t1, t2, fields=("shape", "dtype", "device")):
        if any(not isinstance(t, torch.Tensor) for t in (t1, t2)):
            return False
        for field in fields:
            if getattr(t1, field) != getattr(t2, field):
                return False
        return True

    def replace_no_op(node, replace_input_index):
        replacement = node.args[replace_input_index]

        # https://github.com/pytorch/pytorch/issues/86128 causes
        # non-Tensor inputs even for ops with only Tensor inputs.
        # TODO - decompose/type promote to avoid this
        if not all(isinstance(arg, torch.fx.Node) for arg in node.args):
            return

        if not fake_tensors_eq(node.meta["val"], replacement.meta["val"]):
            if fake_tensors_eq(
                node.meta["val"],
                replacement.meta["val"],
                ("shape", "device"),
            ):
                with graph.inserting_after(node):
                    replacement = graph.call_function(
                        torch.ops.prims.convert_element_type.default,
                        args=(replacement, node.meta["val"].dtype),
                    )
            else:
                return

        node.replace_all_uses_with(replacement)
        replacement.meta.update(node.meta)
        graph.erase_node(node)

    for node in graph.nodes:
        if node.op != "call_function":
            continue

        # TODO handle Tensor-Scalar adds, it's a different schema
        if node.target == aten.add.Tensor and len(node.args) == 2:
            if (
                not any(e in zeros for e in node.args)
                or node.kwargs.get("alpha", 1) != 1
            ):
                continue

            replace_index = 1 if node.args[0] in zeros else 0
            replace_no_op(node, replace_index)

        elif node.target == aten.sub.Tensor and len(node.args) == 2:
            if node.args[1] not in zeros or node.kwargs.get("alpha", 1) != 1:
                continue

            replace_no_op(node, 0)

        elif node.target == aten.mul.Tensor and len(node.args) == 2:
            if not any(e in ones for e in node.args):
                continue

            replace_input_index = 1 if node.args[0] in ones else 0
            replace_no_op(node, replace_input_index)

        elif (
            node.target == aten.div.Tensor
            and len(node.args) == 2
            and node.args[1] in ones
        ):
            replace_no_op(node, 0)


@torch.utils._python_dispatch._disable_current_modes()
def remove_redundant_views(gm: torch.fx.GraphModule):
    """
    Removes redundant views by reusing existing ones.
    """

    # A dictionary mapping a tensor to all aliased views.
    views: Dict[torch.fx.Node, Dict[torch.dtype, torch.fx.Node]] = {}
    graph = gm.graph

    for node in graph.nodes:
        if node.op != "call_function":
            continue

        if node.target != torch.ops.aten.view.dtype:
            continue

        src = node.args[0]
        to_type = node.args[1]
        existing_views = views.get(src)
        is_needed = True

        if existing_views:
            # Replace the view with the an existing view if available.
            alias = existing_views.get(to_type)
            if alias:
                is_needed = False
                node.replace_all_uses_with(alias)
                alias.meta.update(node.meta)
                graph.erase_node(node)
        else:
            from_type = src.meta["val"].dtype
            existing_views = {from_type: src}
            views[src] = existing_views

        if is_needed:
            # Save the new alias but do not replace existing one.
            existing_views.setdefault(to_type, node)
            views[node] = existing_views

    # Clean up unused views.
    while True:
        unused_views = [alias for alias in views if not alias.users]
        if len(unused_views) == 0:
            break
        for unused in unused_views:
            views.pop(unused)
            graph.erase_node(unused)


class UniformValueConstantFolder(ConstantFolder):
    """
    Runs constant folding and replaces tensors that have a unifrom value
    with a tensor constructor call: aten.full([shape], value, ...)
    """

    def __init__(self, gm, skip_constructors=False):
        super().__init__(gm, skip_constructors)
        self.node_storages_ptrs: Dict[torch.fx.Node, int] = {}
        self.constant_data_ptrs: Dict[torch.fx.Node, StorageWeakRef] = {}
        # we may constant fold a tensor which in the graph has a sym size
        # see: [constant folding refining of symints]
        self.node_replacements_shapes: Dict[torch.fx.Node, List[int]] = {}

    def insertable_tensor_check(self, t: torch.Tensor) -> bool:
        # TODO - we could also Tensors which get replaced with arange here
        return (
            t.numel() != 0
            and bool((t == t.flatten()[0]).all())
            and torch._C._has_storage(t)
            and t.layout == torch.strided
        )

    def add_node_replacement(self, node: torch.fx.Node, tensor: torch.Tensor) -> None:
        self.node_replacements[node] = tensor.flatten()[0].item()
        self.constant_data_ptrs[node] = StorageWeakRef(tensor.untyped_storage())
        shape = list(tensor.shape)
        assert all(type(dim) is int for dim in shape)
        self.node_replacements_shapes[node] = shape


@torch.utils._python_dispatch._disable_current_modes()
def constant_fold_uniform_value(gm: torch.fx.GraphModule):
    "Runs constant folding and replaces constants which can be constructed with a single `full` call. Calls into remove_no_ops."
    aten = torch.ops.aten

    # Constant folding can leak memory, especially with repeated compilation, so we are only going to
    # remove constants which can be replaced with a constructor.
    cf = UniformValueConstantFolder(gm)
    cf.run()

    node_replacements = cf.node_replacements

    # note: [constant folding refining of symints]
    # constant folding will partially evaluate a graph such that values which have dependencies which
    # are entirely known at compile time may also become compile time constants. in some cases,
    # this will include symints which we had not yet previously deduced are guaranteed a
    # constant value and is then deduced in constant folding. an example is:
    # unbacked_symint_eq_11 = torch.full((), 11).item()
    # torch.full((unbacked_symint_eq_11,), 0)
    node_replacements_shapes = cf.node_replacements_shapes

    graph = gm.graph

    zeros = set()
    ones = set()

    # Got failures in `test_is_set_to_cuda` if we change aliasing on constants,
    # so just constant-ify if a Tensor is unaliased
    constant_data_ptr_count: typing.Counter[StorageWeakRef] = Counter()

    for node in cf.node_replacements:
        constant_data_ptr_count[cf.constant_data_ptrs[node]] += 1

    for node, value in node_replacements.items():
        # we dont have a functional way right now of instantiating a non-contiguous tensor with full/zeros/ones right now
        # hasn't shown up to be important yet
        fake_tensor = node.meta["val"]
        if not fake_tensor.is_contiguous(memory_format=torch.contiguous_format):
            continue

        if constant_data_ptr_count[cf.constant_data_ptrs[node]] > 1:
            continue

        with graph.inserting_after(node):
            # the conversion from tensor and back to value can be lossy, just use the original full ctor value
            if (
                node.op == "call_function"
                and node.target == aten.full.default
                and len(node.args) == 2
            ):
                value = node.args[1]

            # refines symints, see [constant folding refining of symints] above
            for runtime_size, compile_time_size in zip(
                node_replacements_shapes[node], fake_tensor.shape
            ):
                torch._check(runtime_size == compile_time_size)

            # zeros, and ones just get traced into full, so we insert those
            new_node = graph.call_function(
                aten.full.default,
                args=(node_replacements_shapes[node], value),
                kwargs={
                    "dtype": fake_tensor.dtype,
                    "layout": torch.strided,
                    "device": fake_tensor.device,
                    "pin_memory": False,
                },
            )

            new_node.meta.update(node.meta)
            node.replace_all_uses_with(new_node)
            graph.erase_node(node)

            if value == 0:
                zeros.add(new_node)
            elif value == 1:
                ones.add(new_node)

    remove_no_ops(gm, zeros, ones)
    remove_redundant_views(gm)


def joint_graph_passes(graph: torch.fx.GraphModule):
    """
    Run FX transformations on the joint forwards+backwards graph.
    """
    lazy_init()
    count = 0

    if config.joint_graph_constant_folding:
        constant_fold_uniform_value(graph)

    if config.pattern_matcher:
        count += patterns.apply(graph.graph)  # type: ignore[arg-type]

    if not config.fallback_random:
        count += replace_random_passes(graph)

    if count:
        stable_topological_sort(graph.graph)
        graph.graph.lint()
        graph.recompile()
    return graph


@register_graph_pattern(
    CallFunction(
        torch.ops.prims.convert_element_type.default,
        CallFunction(
            torch.ops.prims.convert_element_type.default,
            KeywordArg("arg"),
            KeywordArg("dtype1"),
        ),
        KeywordArg("dtype2"),
    ),
    pass_dict=patterns,
)
def pointless_convert(match: Match, arg, dtype1: torch.dtype, dtype2: torch.dtype):
    """Remove chain of dtype conversions often created by AMP"""
    graph = match.graph
    node = match.output_node()
    allowed = {torch.float16, torch.bfloat16, torch.float32, torch.float64}
    if dtype1 in allowed and dtype2 in allowed:
        repl = graph.call_function(
            torch.ops.prims.convert_element_type.default, (arg, dtype2)
        )
        repl.meta.update(node.meta)
        node.replace_all_uses_with(repl)
        match.erase_nodes(graph)


@register_graph_pattern(
    CallFunction(torch.ops.aten.view.default, KeywordArg("arg"), KeywordArg("size")),
    pass_dict=patterns,
)
def pointless_view(match: Match, arg, size):
    """Remove no-op view"""
    graph = match.graph
    node = match.output_node()
    arg_size = list(node.args[0].meta["val"].shape)  # type: ignore[union-attr]
    if size == arg_size:
        node.replace_all_uses_with(node.args[0])
        match.erase_nodes(graph)
