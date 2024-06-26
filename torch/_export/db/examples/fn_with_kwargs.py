import torch

from torch._export.db.case import export_case, ExportArgs, SupportLevel


@export_case(
    example_inputs=ExportArgs(
        torch.randn(4),
        (torch.randn(4), torch.randn(4)),
        *[torch.randn(4), torch.randn(4)],
        mykw0=torch.randn(4),
        input0=torch.randn(4), input1=torch.randn(4)
    ),
    tags={"python.data-structure"},
    support_level=SupportLevel.SUPPORTED,
)
class FnWithKwargs(torch.nn.Module):
    """
    Keyword arguments are not supported at the moment.
    """
    def __init__(self):
        super().__init__()

    def forward(self, pos0, tuple0, *myargs, mykw0, **mykwargs):
        out = pos0
        for arg in tuple0:
            out = out * arg
        for arg in myargs:
            out = out * arg
        out = out * mykw0
        out = out * mykwargs["input0"] * mykwargs["input1"]
        return out
