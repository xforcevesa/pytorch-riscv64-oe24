import torch

from torch._export.db.case import export_case, SupportLevel
from torch.utils import _pytree as pytree


@export_case(
    example_inputs=({1: torch.randn(3, 2), 2: torch.randn(3, 2)},),
    support_level=SupportLevel.SUPPORTED,
)
class PytreeFlatten(torch.nn.Module):
    """
    Pytree from PyTorch can be captured by TorchDynamo.
    """
    def __init__(self):
        super().__init__()

    def forward(self, x):
        y, spec = pytree.tree_flatten(x)
        return y[0] + 1
