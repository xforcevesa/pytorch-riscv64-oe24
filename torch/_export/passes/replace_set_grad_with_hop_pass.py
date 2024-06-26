import torch
from torch._higher_order_ops.wrap import wrap_with_set_grad_enabled

from ..utils import (
    node_inline_,
    node_replace_,
    nodes_filter,
    nodes_first,
    nodes_map,
    sequential_split,
)


def _is_set_grad_enabled_node(node: torch.fx.Node):
    return (
        node
        and node.op == "call_function"
        and node.target == torch._C._set_grad_enabled
    )


def _is_set_grad_enabled_sub_mod(node: torch.fx.Node, omit_if_same_with_ambient=False):
    if node.op == "call_module":
        assert isinstance(node.target, str)
        subgm = getattr(node.graph.owning_module, node.target)
        first_non_ph = nodes_first(
            subgm.graph.nodes, lambda node: node.op != "placeholder"
        )
        if (
            first_non_ph
            and first_non_ph.op == "call_function"
            and first_non_ph.target == torch._C._set_grad_enabled
        ):
            return (
                first_non_ph.args[0] != torch.is_grad_enabled()
                if omit_if_same_with_ambient
                else True
            )
    return False


def _replace_with_hop(node: torch.fx.Node):
    assert node.op == "call_module"
    graph: torch.fx.Graph = node.graph
    gm: torch.fx.GraphModule = graph.owning_module
    assert isinstance(node.target, str)
    sub_gm = getattr(gm, node.target)
    sub_graph = sub_gm.graph
    set_grad_nodes = nodes_filter(sub_graph.nodes, _is_set_grad_enabled_node)
    if len(set_grad_nodes) > 0:
        assert len(set_grad_nodes) == 1
        set_grad_node = set_grad_nodes[0]
        enable_grad_val = set_grad_node.args[0]
        with graph.inserting_before(node):
            get_attr_node = graph.get_attr(node.target)
            output_node = next(iter(reversed(sub_gm.graph.nodes)), None)
            if output_node is not None:
                assert len(output_node.args) == 1
                output_args = output_node.args[0]
                if isinstance(output_args, (tuple, list)):
                    call_func_node = graph.call_function(
                        wrap_with_set_grad_enabled,
                        (enable_grad_val, get_attr_node, *node.args),
                        {},
                    )
                    # Create the metadata
                    call_func_node.meta["val"] = tuple(
                        arg.meta["val"] for arg in output_args
                    )
                    node_replace_(node, call_func_node, delete_old=True)

                    # Rename the name of getitem nodes to the actual name of its contents
                    # for passing verifier and better readability, also propagate metadata
                    for get_item_node in call_func_node.users.keys():
                        idx: int = get_item_node.args[1]
                        output_node = output_args[idx]
                        get_item_node._rename(output_node.name)
                        get_item_node.meta = output_node.meta
                        pass

                elif isinstance(output_args, torch.fx.Node):
                    call_func_node = graph.create_node(
                        "call_function",
                        wrap_with_set_grad_enabled,
                        (enable_grad_val, get_attr_node, *node.args),
                        {},
                        output_args.name,
                    )
                    call_func_node.meta = output_args.meta
                    node_replace_(node, call_func_node, delete_old=True)
                else:
                    raise NotImplementedError(
                        f"repalce_set_grad_with_hop_pass doesnt' support output type {type(output_args)}"
                    )
            else:
                raise NotImplementedError(
                    "Cannot replace a call_module with a hop if it has no output. This module will gets DCEed."
                )
        sub_graph.erase_node(set_grad_node)


def _remove_set_grad_and_inline(node: torch.fx.Node):
    assert node.op == "call_module"
    graph: torch.fx.Graph = node.graph
    gm: torch.fx.GraphModule = graph.owning_module
    assert isinstance(node.target, str)
    sub_gm = getattr(gm, node.target)
    sub_graph = sub_gm.graph
    nodes_map(
        sub_graph.nodes,
        lambda n: sub_graph.erase_node(n) if _is_set_grad_enabled_node(n) else n,
    )
    node_inline_(node)


def replace_set_grad_with_hop_pass(gm: torch.fx.GraphModule):
    # If there is no set_grad_enabled node, return the original graph module
    need_replacing = False
    for node in gm.graph.nodes:
        if _is_set_grad_enabled_node(node):
            need_replacing = True

    if not need_replacing:
        return gm

    new_gm = sequential_split(gm, _is_set_grad_enabled_node)

    def _maybe_inline_or_replace_with_hop(node: torch.fx.Node):
        if _is_set_grad_enabled_sub_mod(node, omit_if_same_with_ambient=True):
            _replace_with_hop(node)
        else:
            _remove_set_grad_and_inline(node)

    nodes_map(
        list(new_gm.graph.nodes),
        lambda node: _maybe_inline_or_replace_with_hop(node)
        if node.op == "call_module"
        else node,
    )
    new_gm.graph.lint()
    return new_gm
