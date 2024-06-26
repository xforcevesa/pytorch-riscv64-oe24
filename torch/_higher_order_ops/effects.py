from enum import Enum
from typing import Any, Dict, Optional, Tuple

import torch
import torch.utils._pytree as pytree
from torch._C import DispatchKey
from torch._ops import HigherOrderOperator
from torch._subclasses.fake_tensor import FakeTensorMode
from torch.fx.experimental.proxy_tensor import (
    disable_proxy_modes_tracing,
    ProxyTorchDispatchMode,
    track_tensor_tree,
)


class _EffectType(Enum):
    ORDERED = "Ordered"


SIDE_EFFECTS: Dict[torch._ops.OpOverload, _EffectType] = {
    torch.ops.aten._print.default: _EffectType.ORDERED,
}


class WithEffects(HigherOrderOperator):
    """
    with_effects(token, op, args, kwargs) -> (new_token, op_results)

    This HOP helps ensure ordering between side effectful ops like prints or ops
    using torchbind objects. This is needed to ensure a traced graph from
    AOTAutograd is functional so that future optimization passes do not reorder
    these operators. This is done through threading "effect tokens" through the
    graph to enforce data dependence between side effectful ops.

    The tokens are basically dummy values (torch.tensor([])). We create a token
    per "effect type", which are enumerated in the _EffectType enum.
    """

    def __init__(self):
        super().__init__("with_effects")

    def __call__(
        self,
        token,
        op: torch._ops.OpOverload,
        *args: Tuple[Any, ...],
        **kwargs: Dict[str, Any],
    ) -> Tuple[Any, ...]:
        assert isinstance(op, torch._ops.OpOverload)
        assert not has_aliasing(op), "Ops with aliasing is not supported"
        assert has_effects(op, args, kwargs)
        assert isinstance(kwargs, dict)
        return super().__call__(token, op, *args, **kwargs)


with_effects = WithEffects()


def has_aliasing(op: torch._ops.OpOverload):
    for arg in op._schema.arguments:
        if arg.alias_info is not None:
            return True
    for arg in op._schema.returns:
        if arg.alias_info is not None:
            return True
    return False


def has_effects(op, args, kwargs) -> bool:
    return (
        isinstance(op, torch._ops.OpOverload)
        and not has_aliasing(op)
        and get_effect_key(op, args, kwargs) is not None
    )


def get_effect_key(op, args, kwargs) -> Optional[_EffectType]:
    if op in SIDE_EFFECTS:
        return SIDE_EFFECTS[op]

    for arg in args:
        if isinstance(arg, torch.ScriptObject):
            return _EffectType.ORDERED

    return None


@with_effects.py_impl(DispatchKey.CompositeExplicitAutograd)
def with_effects_dense(
    token: torch.Tensor,
    op: torch._ops.OpOverload,
    *args: Tuple[Any, ...],
    **kwargs: Dict[str, Any],
) -> Tuple[torch.Tensor, ...]:
    out = op(*args, **kwargs)
    new_token = torch.tensor([])
    if isinstance(out, tuple):
        return (new_token, *out)
    return (new_token, out)


@with_effects.py_impl(FakeTensorMode)
def with_effects_fake(
    mode,
    token: torch.Tensor,
    op: torch._ops.OpOverload,
    *args: Tuple[Any, ...],
    **kwargs: Dict[str, Any],
) -> Tuple[torch.Tensor, ...]:
    with mode:
        result = with_effects_dense(token, op, *args, **kwargs)
        return result


@with_effects.py_impl(ProxyTorchDispatchMode)
def with_effects_proxy(
    mode,
    token: torch.Tensor,
    op: torch._ops.OpOverload,
    *args: Tuple[Any, ...],
    **kwargs: Dict[str, Any],
) -> Tuple[torch.Tensor, ...]:
    if not mode.enable_tracing:
        return with_effects(token, op, *args, **kwargs)

    with disable_proxy_modes_tracing():
        out = with_effects(token, op, *args, **kwargs)

    proxy_token = mode.tracer.unwrap_proxy(token)
    proxy_args = pytree.tree_map(mode.tracer.unwrap_proxy, args)
    proxy_kwargs = pytree.tree_map(mode.tracer.unwrap_proxy, kwargs)

    out_proxy = mode.tracer.create_proxy(
        "call_function",
        with_effects,
        (proxy_token, op, *proxy_args),
        proxy_kwargs,
    )
    result = track_tensor_tree(out, out_proxy, constant=None, tracer=mode.tracer)
    return result


with_effects.fallthrough(DispatchKey.AutogradCPU)
with_effects.fallthrough(DispatchKey.AutogradCUDA)


def handle_effects(
    allow_token_discovery: bool,
    tokens: Dict[_EffectType, torch.Tensor],
    op: torch._ops.OpOverload,
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
) -> Any:
    """
    Args:
        allow_token_discovery: Whether or not we are discovering tokens. If this
        is true, we will create a token for every side effect type seen that
        does not have a token assigned yet.  If this is false, the tokens
        should've all been created ahead of time, so we will error if there is
        no token mapping to every effect type.

        tokens: Map of effect type to tokens. This is to chain operators of the
        same effects together so that they do not get reordered in later
        optimization passes.
    """

    # Get a token. We can't do `tokens.get(op, torch.tensor([]))` because
    # this will create an empty tensor during proxy mode tracing if the token
    # doesn't exist. But the tokens should always exist during proxy mode tracing.
    key = get_effect_key(op, args, kwargs)
    assert key is not None
    if key not in tokens:
        assert allow_token_discovery, f"Could not find a token for effect {key}"
        tokens[key] = torch.tensor([])
    token = tokens[key]

    from torch._subclasses.functional_tensor import PythonFunctionalizeAPI

    ctx = PythonFunctionalizeAPI()

    unwrapped_token = ctx.unwrap_tensors([token])[0]  # type: ignore[arg-type]
    unwrapped_args = ctx.unwrap_tensors(args)  # type: ignore[arg-type]
    unwrapped_kwargs = ctx.unwrap_tensors(kwargs)  # type: ignore[arg-type]
    with ctx.redispatch_to_next():
        (new_token, *unwrapped_outs) = with_effects(
            unwrapped_token, op, *unwrapped_args, **unwrapped_kwargs  # type: ignore[arg-type]
        )

    if len(op._schema.returns) == 0:
        assert unwrapped_outs[0] is None
        unwrapped_outs = None  # type: ignore[assignment]
    elif len(op._schema.returns) == 1:
        assert len(unwrapped_outs) == 1
        unwrapped_outs = unwrapped_outs[0]
    else:
        assert len(unwrapped_outs) == len(op._schema.returns)

    # Add the newly created token into the tokens map for a following call to
    # use this token.
    wrapped_token = ctx.wrap_tensors(new_token)
    assert isinstance(wrapped_token, torch.Tensor)
    tokens[key] = wrapped_token

    return ctx.wrap_tensors(unwrapped_outs)  # type: ignore[arg-type]
