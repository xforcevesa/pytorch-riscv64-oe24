from typing import Any, Dict, List, Optional

import torch.fx
import torch.utils._pytree as pytree

__all__ = ["compile", "list_mode_options", "list_options", "cudagraph_mark_step_begin"]


def compile(
    gm: torch.fx.GraphModule,
    example_inputs: List[torch.Tensor],
    options: Optional[Dict[str, Any]] = None,
):
    """
    Compile a given FX graph with TorchInductor.  This allows compiling
    FX graphs captured without using TorchDynamo.

    Args:
        gm: The FX graph to compile.
        example_inputs:  List of tensor inputs.
        options:  Optional dict of config options.  See `torch._inductor.config`.

    Returns:
        Callable with same behavior as gm but faster.
    """
    from .compile_fx import compile_fx

    return compile_fx(gm, example_inputs, config_patches=options)


def aot_compile(
    gm: torch.fx.GraphModule,
    example_inputs: List[torch.Tensor],
    options: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Ahead-of-time compile a given FX graph with TorchInductor into a shared library.

    Args:
        gm: The FX graph to compile.
        example_inputs:  List of tensor inputs.
        options:  Optional dict of config options.  See `torch._inductor.config`.

    Returns:
        Path to the generated shared library
    """
    from .compile_fx import compile_fx_aot

    # We will serialize the pytree info into the .so as constant strings
    in_spec = None
    out_spec = None
    if isinstance(gm.graph._codegen, torch.fx.graph._PyTreeCodeGen):
        codegen = gm.graph._codegen
        gm.graph._codegen = torch.fx.graph.CodeGen()
        gm.recompile()

        if codegen.pytree_info.in_spec is not None:
            in_spec = codegen.pytree_info.in_spec
        if codegen.pytree_info.out_spec is not None:
            out_spec = codegen.pytree_info.out_spec

    else:
        if hasattr(gm, "_in_spec"):
            in_spec = gm._in_spec
        if hasattr(gm, "_out_spec"):
            out_spec = gm._out_spec

    serialized_in_spec = pytree.treespec_dumps(in_spec) if in_spec is not None else ""
    serialized_out_spec = (
        pytree.treespec_dumps(out_spec) if out_spec is not None else ""
    )

    options = (
        {
            "aot_inductor.serialized_in_spec": serialized_in_spec,
            "aot_inductor.serialized_out_spec": serialized_out_spec,
        }
        if options is None
        else {
            **options,
            "aot_inductor.serialized_in_spec": serialized_in_spec,
            "aot_inductor.serialized_out_spec": serialized_out_spec,
        }
    )

    return compile_fx_aot(
        gm,
        example_inputs,
        config_patches=options,
    )


def list_mode_options(
    mode: Optional[str] = None, dynamic: Optional[bool] = None
) -> Dict[str, Any]:
    r"""Returns a dictionary describing the optimizations that each of the available
    modes passed to `torch.compile()` performs.

    Args:
        mode (str, optional): The mode to return the optimizations for.
        If None, returns optimizations for all modes
        dynamic (bool, optional): Whether dynamic shape is enabled.

    Example::
        >>> torch._inductor.list_mode_options()
    """

    mode_options: Dict[str, Dict[str, bool]] = {
        "default": {},
        # enable cudagraphs
        "reduce-overhead": {
            "triton.cudagraphs": True,
        },
        # enable max-autotune
        "max-autotune-no-cudagraphs": {
            "max_autotune": True,
        },
        # enable max-autotune
        # enable cudagraphs
        "max-autotune": {
            "max_autotune": True,
            "triton.cudagraphs": True,
        },
    }
    return mode_options[mode] if mode else mode_options  # type: ignore[return-value]


def list_options() -> List[str]:
    r"""Returns a dictionary describing the optimizations and debug configurations
    that are available to `torch.compile()`.

    The options are documented in `torch._inductor.config`.

    Example::

        >>> torch._inductor.list_options()
    """

    from torch._inductor import config

    current_config: Dict[str, Any] = config.shallow_copy_dict()

    return list(current_config.keys())


def cudagraph_mark_step_begin():
    "Indicates that a new iteration of inference or training is about to begin."
    from .cudagraph_trees import mark_step_begin

    mark_step_begin()
