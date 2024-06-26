"""This module converts objects into numpy array."""
import numpy as np
import torch


def make_np(x):
    """
    Convert an object into numpy array.

    Args:
      x: An instance of torch tensor or caffe blob name

    Returns:
        numpy.array: Numpy array
    """
    if isinstance(x, np.ndarray):
        return x
    if isinstance(x, str):  # Caffe2 will pass name of blob(s) to fetch
        return _prepare_caffe2(x)
    if np.isscalar(x):
        return np.array([x])
    if isinstance(x, torch.Tensor):
        return _prepare_pytorch(x)
    raise NotImplementedError(
        f"Got {type(x)}, but numpy array, torch tensor, or caffe2 blob name are expected."
    )


def _prepare_pytorch(x):
    if x.dtype == torch.bfloat16:
        x = x.to(torch.float16)
    x = x.detach().cpu().numpy()
    return x


def _prepare_caffe2(x):
    from caffe2.python import workspace

    x = workspace.FetchBlob(x)
    return x
