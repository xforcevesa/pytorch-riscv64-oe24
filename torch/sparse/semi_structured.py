import warnings
from collections import namedtuple
from typing import Any, Optional, Tuple, List, Callable, Dict

import torch
from torch.sparse._semi_structured_conversions import (
    sparse_semi_structured_from_dense_cutlass,
    sparse_semi_structured_to_dense_cutlass,
)
from torch.sparse._semi_structured_ops import (
    fallback_dispatcher,
    semi_sparse_values,
    semi_sparse_indices,
    semi_sparse_detach,
    semi_sparse_t,
    semi_sparse_view,
    semi_sparse_mm,
    semi_sparse_addmm,
    semi_sparse_linear,
)

__all__ = [
    "SparseSemiStructuredTensor",
    "SparseSemiStructuredTensorCUTLASS",
    "SparseSemiStructuredTensorCUSPARSELT",
    "to_sparse_semi_structured",
]

_SEMI_STRUCTURED_SPARSE_CONFIG = namedtuple(
    "_SEMI_STRUCTURED_SPARSE_CONFIG",
    "sparse_min_rows sparse_min_cols dense_min_rows dense_min_cols",
)


class SparseSemiStructuredTensor(torch.Tensor):
    """
    This class implementes semi-structured sparsity as a Tensor subclass.

    Semi-structured sparsity describes a sparsity pattern where n in every 2n elements are sparse,
    depending on the datatype. It is also referred to as 2:4 sparsity or fine-grained
    structured sparsity.

    There are two backends available for semi_structred sparsity, either cuSPARSELt or CUTLASS.
    This class is meant to serve as a base class for both implementations. SparseSemiStructuredCUTLASS
    and SparseSemiStructuredCUSPARSELT both inherit from this class and define three backend-specific items.
    Note that as such, this class cannot be insantiated directly.

    -`_DTYPE_SHAPE_CONSTRAINTS` - A dictionary holding backend specific dense/sparse min shape constraints
    - `def from_dense()` - backend specific compression routines
    - `def _mm()` - backend specifc mm op (either torch._cslt_sparse_mm or torch._sparse_semi_structured_linear)
    """

    _DEFAULT_ALG_ID: int = 0
    _DTYPE_SHAPE_CONSTRAINTS: Dict[torch.dtype, _SEMI_STRUCTURED_SPARSE_CONFIG]
    _FORCE_CUTLASS: bool = True
    _FUSE_TRANSPOSE: bool = False
    _PROTOTYPE_WARNING_SHOWN: bool = False

    SPARSE_DISPATCH: Dict[Callable, Callable]

    packed: Optional[torch.Tensor]
    meta: Optional[torch.Tensor]
    packed_t: Optional[torch.Tensor]
    meta_t: Optional[torch.Tensor]
    threads_masks: Optional[torch.Tensor]
    fuse_transpose_cusparselt: bool
    alg_id_cusparselt: int

    __slots__ = ["packed", "meta", "packed_t", "meta_t", "threads_masks"]

    @staticmethod
    def __new__(  # noqa: PYI034
        cls,
        shape: torch.Size,
        packed: Optional[torch.Tensor],
        meta: Optional[torch.Tensor],
        packed_t: Optional[torch.Tensor],
        meta_t: Optional[torch.Tensor],
        threads_masks: Optional[torch.Tensor],
        fuse_transpose_cusparselt: bool = False,
        alg_id_cusparselt: int = 0,
        requires_grad: bool = False,
    ):
        """
        Create a new instance of the tensor subclass from the compressed sparse representation.

        We have the option to create the subclass with the compressed representations of both X and X', for training.
        For inference, we only need a single representation (either X or X'), while the corresponding other set will be None.

        Depending on the backend selected, certain fields will be set to None. (CUSPARSELT vs CUTLASS)

        Args:
            shape: The shape of the original dense tensor
            packed: The compressed representation of the original dense tensor
            meta: The metadata of the original dense tensor, if it is stored separately
            packed_t: The compressed representation of the transposed original dense tensor
            meta_t: The metadata of the transposed original dense tensor, if it is stored separately
            threads_masks: The masks used by the CUTLASS backend to determine which threads should participate in the computation.
                           Used for pointwise ops.
            fuse_transpose_cusparselt: When running with cuSPARSELt, we have the option to fuse a transposition
                                       with a matmul, which is useful in the case of 2:4 sparse training.
            alg_id_cusparselt: The algorithm id to use when using cuSPARSELT, will have effect on performance

        Returns:
            torch.Tensor: A torch.Tensor wrapper subclass.

        Raises:
            ValueError: If all of the tensor arguments are None.
        """
        if not cls._PROTOTYPE_WARNING_SHOWN:
            warnings.warn(
                (
                    "The PyTorch API of SparseSemiStructuredTensor is in prototype stage "
                    "and will change in the near future. Please open a Github issue "
                    "for features requests and see our documentation on the torch.sparse "
                    "module for further information about the project."
                ),
                UserWarning,
            )
            cls._PROTOTYPE_WARNING_SHOWN = True

            # Because this only runs onces, we also load the dispatch table here as well.
            # We can't define the dispatch table explicitly because of torch.ops import errors, so we do this instead
            # But this is useful since it allows users to overload the dispatch table for debugging / testing.
            cls._load_dispatch_table()

        if packed is not None:
            previous_tensor = packed
        elif packed_t is not None:
            previous_tensor = packed_t
        else:
            raise ValueError("At least one of packed or packed_t must be provided")

        kwargs = {
            "device": previous_tensor.device,
            "dtype": previous_tensor.dtype,
            "layout": previous_tensor.layout,
            "requires_grad": requires_grad,
        }
        tensor = torch.Tensor._make_wrapper_subclass(cls, shape, **kwargs)  # type: ignore[attr-defined]

        tensor.packed = packed
        tensor.meta = meta
        tensor.packed_t = packed_t
        tensor.meta_t = meta_t
        tensor.threads_masks = threads_masks
        tensor.fuse_transpose_cusparselt = fuse_transpose_cusparselt
        tensor.alg_id_cusparselt = alg_id_cusparselt
        return tensor

    def __repr__(self) -> str:  # type: ignore[override]
        assert hasattr(self, "shape")
        return f"{self.__class__.__name__}(shape={self.shape})"

    def __tensor_flatten__(
        self,
    ) -> Tuple[List[str], Tuple[torch.Size, bool, int, bool]]:
        inner_tensors = list(
            filter(lambda x: getattr(self, x) is not None, self.__slots__)
        )
        tensor_meta = (
            self.shape,
            self.fuse_transpose_cusparselt,
            self.alg_id_cusparselt,
            self.requires_grad,
        )
        return inner_tensors, tensor_meta

    @classmethod
    def __tensor_unflatten__(
        cls,
        inner_tensors,
        tensor_meta : Tuple[torch.Size, bool, int, bool],
        outer_size,
        outer_stride,
    ) -> torch.Tensor:
        shape, fuse_transpose_cusparselt, alg_id_cusparselt, requires_grad = tensor_meta
        return cls(
            shape=shape,
            packed=inner_tensors.get("packed", None),
            meta=inner_tensors.get("meta", None),
            packed_t=inner_tensors.get("packed_t", None),
            meta_t=inner_tensors.get("meta_t", None),
            threads_masks=inner_tensors.get("threads_masks", None),
            fuse_transpose_cusparselt=fuse_transpose_cusparselt,
            alg_id_cusparselt=alg_id_cusparselt,
            requires_grad=requires_grad,
        )

    __torch_function__ = torch._C._disabled_torch_function_impl

    @classmethod
    def __torch_dispatch__(cls, func, types, args, kwargs) -> Any:
        if func._overloadpacket not in cls.SPARSE_DISPATCH:
            raise NotImplementedError(
                f"{cls.__name__} only supports a specific set of operations, "
                f"can't perform requested op ({func.__name__})"
            )
        return cls.SPARSE_DISPATCH[func._overloadpacket](func, types, args, kwargs)

    @classmethod
    def _load_dispatch_table(cls, custom_dispatch_table=None) -> None:
        """
        Loads the op overload sparse dispatch table for the current class.
        """
        if getattr(cls, "SPARSE_DISPATCH", None) is None:
            cls.SPARSE_DISPATCH = {
                torch.ops.aten.values: semi_sparse_values,
                torch.ops.aten.indices: semi_sparse_indices,
                torch.ops.aten.is_same_size: fallback_dispatcher,
                torch.ops.aten.detach_: fallback_dispatcher,
                torch.ops.aten.detach: semi_sparse_detach,
                torch.ops.aten.t: semi_sparse_t,
                torch.ops.aten.view: semi_sparse_view,
                torch.ops.aten.mm: semi_sparse_mm,
                torch.ops.aten.matmul: semi_sparse_mm,
                torch.ops.aten.addmm: semi_sparse_addmm,
                torch.ops.aten.linear: semi_sparse_linear,
            }
            if custom_dispatch_table is not None:
                cls.SPARSE_DISPATCH.update(custom_dispatch_table)

    @classmethod
    def _validate_device_dim_dtype_shape(cls, original_tensor : torch.Tensor) -> None:
        """
        Assert that the given tensor is valid for semi-structured sparse compression.
        """
        # check device
        if not original_tensor.is_cuda:
            raise RuntimeError(
                f"Error original_tensor.device= {original_tensor.device} is not supported! "
                "Only CUDA tensors are currently supported."
            )

        # check dim
        if original_tensor.dim() != 2:
            raise RuntimeError(
                f"Error original_tensor.dim = {original_tensor.dim()} is not supported! "
                "Only 2d tensors are currently supported."
            )

        # check contiguous
        if not original_tensor.is_contiguous():
            raise RuntimeError(
                "Error original_tensor is not contiguous!"
                "Only contiguous tensors are currently supported."
            )

        # check dtype
        if original_tensor.dtype not in cls._DTYPE_SHAPE_CONSTRAINTS:
            raise RuntimeError(
                f"Error original_tensor.dtype {original_tensor.dtype} is not a supported dtype! "
                "dtype must be one of: {cls._DTYPE_SHAPE_CONSTRAINTS}"
            )

        # check shape
        m, n = original_tensor.shape
        min_rows = cls._DTYPE_SHAPE_CONSTRAINTS[original_tensor.dtype].sparse_min_rows
        min_cols = cls._DTYPE_SHAPE_CONSTRAINTS[original_tensor.dtype].sparse_min_cols
        if m < min_rows or m % min_rows or n < min_cols or n % min_cols:
            # TODO in the future we can add in padding to support sparse dimensions that aren't perfect multiples
            raise RuntimeError(
                f"Error original_tensor.shape {original_tensor.shape} is not supported! "
                f"Both dimensions must be larger or equal than and a multiple of ({min_rows}, {min_cols})"
            )

    @classmethod
    def _pad_dense_input(cls, dense_input: torch.Tensor) -> torch.Tensor:
        """
        Calculates padding for dense tensor and pads tensor if necessary.
        If padding is not required, this function returns the original tensor.
        """
        # only 2d matmul
        assert dense_input.dim() == 2

        # check shape
        m, n = dense_input.shape
        min_rows = cls._DTYPE_SHAPE_CONSTRAINTS[dense_input.dtype].dense_min_rows
        min_cols = cls._DTYPE_SHAPE_CONSTRAINTS[dense_input.dtype].dense_min_cols

        # calculate padding
        to_pad_m = -m % min_rows if m < min_rows or m % min_rows else 0
        to_pad_n = -n % min_cols if n < min_cols or n % min_rows else 0
        if to_pad_m or to_pad_n:
            return torch.nn.functional.pad(dense_input, (0, to_pad_n, 0, to_pad_m))
        else:
            return dense_input

    def to_dense(self):
        col = self.shape[-1]
        return torch.mm(self, torch.eye(col, dtype=self.dtype, device=self.device))

    @classmethod
    def from_dense(cls, original_tensor : torch.Tensor) -> "SparseSemiStructuredTensor":
        raise NotImplementedError

    def _mm(
        self,
        B: torch.Tensor,
        *,
        bias: Optional[torch.Tensor] = None,
        **kwargs,
    ) -> torch.Tensor:
        raise NotImplementedError


def to_sparse_semi_structured(
    original_tensor: torch.Tensor,
    transposed: bool = False,
) -> SparseSemiStructuredTensor:
    """
    This function converts a dense tensor into a sparse semi-structured tensor.
    It will return a SparseSemiStructuredTensor, a subclass of torch.Tensor.

    This function will check to ensure the dense tensor has the right dtype, size, dims, and device.
    We currently only support semi-structured sparse tensors for 2d CUDA tensors.
    Additionally, your tensor must be a positive multiple of the mininum sparse block size, given in
    `_DTYPE_TO_SHAPE_CONSTRAINTS` for each dtype (float32, float16, bfloat16, int8).

    Args:
        original_tensor (Tensor): the dense tensor to convert
        transposed (bool, optional): deprecated arg to be removed in another release. Do not use.
    Returns:
        SparseSemiStructuredTensor: A sparse semi-structured tensor created from the given original_tensor
    Raises:
        None
    Example:
        >>> # xdoctest: +REQUIRES(env:TORCH_DOCTEST_CUDA)
        >>> A = torch.Tensor([0, 0, 1, 1]).tile((128, 32)).half().cuda()
        tensor([[0., 0., 1.,  ..., 0., 1., 1.],
                [0., 0., 1.,  ..., 0., 1., 1.],
                [0., 0., 1.,  ..., 0., 1., 1.],
                ...,
                [0., 0., 1.,  ..., 0., 1., 1.],
                [0., 0., 1.,  ..., 0., 1., 1.],
                [0., 0., 1.,  ..., 0., 1., 1.]], device='cuda:0', dtype=torch.float16)
        >>> A_sparse = to_sparse_semi_structured(A)
        SparseSemiStructuredTensor(shape=torch.Size([128, 128]))
        >>> A_sparse.values()
        tensor([[1., 1., 1.,  ..., 1., 1., 1.],
                [1., 1., 1.,  ..., 1., 1., 1.],
                [1., 1., 1.,  ..., 1., 1., 1.],
                ...,
                [1., 1., 1.,  ..., 1., 1., 1.],
                [1., 1., 1.,  ..., 1., 1., 1.],
                [1., 1., 1.,  ..., 1., 1., 1.]], device='cuda:0', dtype=torch.float16),
        >>> A_sparse.indices()
        tensor([[-4370, -4370, -4370,  ..., -4370, -4370, -4370],
                [-4370, -4370, -4370,  ..., -4370, -4370, -4370],
                [-4370, -4370, -4370,  ..., -4370, -4370, -4370],
                ...,
                [-4370, -4370, -4370,  ..., -4370, -4370, -4370],
                [-4370, -4370, -4370,  ..., -4370, -4370, -4370],
                [-4370, -4370, -4370,  ..., -4370, -4370, -4370]], device='cuda:0', dtype=torch.int16))
    """
    if transposed:
        raise DeprecationWarning(
            "Setting transpose from to_sparse_semi_structured is deprecated and will be removed in a future release."
            "SparseSemiStructuredTensor only support contiguous input tensors. "
        )

    sparse_subclass = (
        torch.sparse.SparseSemiStructuredTensorCUTLASS
        if SparseSemiStructuredTensor._FORCE_CUTLASS
        else torch.sparse.SparseSemiStructuredTensorCUSPARSELT
    )
    return sparse_subclass.from_dense(original_tensor)


class SparseSemiStructuredTensorCUTLASS(SparseSemiStructuredTensor):
    """
    This class implements semi-structured sparsity for the CUTLASS backend.

    In this implementation, the specified elements and metadata are stored seprately,
    in packed and meta respectively.

    When _FORCE_CUTLASS is set, or when cuSPARSELt is not available, this subclass calls into _sparse_semi_structured_linear
    and sparse_semi_structured_from_dense for conversion to the compressed format.
    """

    _DTYPE_SHAPE_CONSTRAINTS = {
        torch.int8: _SEMI_STRUCTURED_SPARSE_CONFIG(16, 128, 16, 16),
        torch.float16: _SEMI_STRUCTURED_SPARSE_CONFIG(32, 64, 8, 8),
        torch.bfloat16: _SEMI_STRUCTURED_SPARSE_CONFIG(32, 64, 8, 8),
        torch.float32: _SEMI_STRUCTURED_SPARSE_CONFIG(32, 32, 4, 4),
    }

    @classmethod
    def from_dense(
        cls, original_tensor: torch.Tensor
    ) -> "SparseSemiStructuredTensorCUTLASS":
        cls._validate_device_dim_dtype_shape(original_tensor)
        (
            sparse_tensor_cutlass,
            meta_tensor_cutlass,
        ) = sparse_semi_structured_from_dense_cutlass(original_tensor)
        return cls(
            original_tensor.shape,
            packed=sparse_tensor_cutlass,
            meta=meta_tensor_cutlass,
            packed_t=None,
            meta_t=None,
            threads_masks=None,
            requires_grad=original_tensor.requires_grad,
        )

    def to_dense(self):
        assert self.meta is not None and self.packed is not None
        return (
            sparse_semi_structured_to_dense_cutlass(
                self.packed,
                self.meta,
            )
            if self.meta.ndim == 2
            else super().to_dense()
        )

    def _mm(
        self,
        B: torch.Tensor,
        *,
        bias: Optional[torch.Tensor] = None,
        **kwargs
    ) -> torch.Tensor:
        if isinstance(B, SparseSemiStructuredTensor):
            raise ValueError(
                "`SparseSemiStructuredTensor @ SparseSemiStructuredTensor` is not supported by the hardware"
            )
        cls_name = self.__class__.__name__
        if self.ndim != 2 or B.ndim != 2:
            raise NotImplementedError(
                f"`{cls_name}` matmul: Broadcasting is not implemented"
            )
        if self.packed is None or self.meta is None:
            raise NotImplementedError(
                f"`{cls_name}` matmul: operation is not supported"
            )
        else:
            res = torch._sparse_semi_structured_linear(
                B.t(), self.packed, self.meta, bias=bias
            ).t()
            return res[: self.shape[0]]


class SparseSemiStructuredTensorCUSPARSELT(SparseSemiStructuredTensor):
    """
    The cuSPARSELt backend expects the specified elements and the metadata to be stored in a single tensor:
    packed = [ specified elements of original tensor | metadata ]
    For an original tensor of size (m, k) we expect the first m * k // 2 elements to be the kept elements
    The rest of the tensor is metadata. Since there is only one tensor, we only use the packed and packed_t
    attributes respectively.

    cuSPARSELt also supports transposition fusion, which is necessary for performant 2:4 sparse training, as well
    as specifying alg_id, a config that affects the performance of the matmul depending on matmul sizes.
    """

    _DTYPE_SHAPE_CONSTRAINTS = {
        torch.int8: _SEMI_STRUCTURED_SPARSE_CONFIG(32, 32, 16, 16),
        torch.float16: _SEMI_STRUCTURED_SPARSE_CONFIG(16, 16, 8, 8),
        torch.bfloat16: _SEMI_STRUCTURED_SPARSE_CONFIG(16, 16, 8, 8),
        torch.float32: _SEMI_STRUCTURED_SPARSE_CONFIG(8, 8, 4, 4),
    }

    @classmethod
    def from_dense(cls, original_tensor : torch.Tensor) -> "SparseSemiStructuredTensorCUSPARSELT":
        cls._validate_device_dim_dtype_shape(original_tensor)
        return cls(
            shape=original_tensor.shape,
            packed=torch._cslt_compress(original_tensor),
            meta=None,
            packed_t=None,
            meta_t=None,
            threads_masks=None,
            fuse_transpose_cusparselt=SparseSemiStructuredTensor._FUSE_TRANSPOSE,
            alg_id_cusparselt=SparseSemiStructuredTensor._DEFAULT_ALG_ID,
            requires_grad=original_tensor.requires_grad,
        )

    def _mm(
        self,
        B: torch.Tensor,
        *,
        bias: Optional[torch.Tensor] = None,
        **kwargs
    ) -> torch.Tensor:
        if isinstance(B, SparseSemiStructuredTensor):
            raise ValueError(
                "`SparseSemiStructuredTensor @ SparseSemiStructuredTensor` is not supported by the hardware"
            )
        if self.ndim != 2 or B.ndim != 2:
            raise NotImplementedError(
                f"`{self.__class__.__name__}` matmul: Broadcasting is not implemented"
            )
        if B.dtype != self.dtype:
            raise NotImplementedError(
                f"`{self.__class__.__name__}` matmul: trying to do `A={tuple(self.shape)} @ B={tuple(B.shape)}`, "
                f"with A.dtype={self.dtype} and B.dtype={B.dtype}. "
                "This operation is only supported when A and B have the same data type."
            )
        if bias is not None and bias.dtype != self.dtype:
            raise NotImplementedError(
                f"`{self.__class__.__name__}` matmul: trying to do `A={tuple(self.shape)} @ B={tuple(B.shape)} + C`, "
                "with A.dtype=B.dtype={self.dtype} and C.dtype={B.dtype}. "
                "This operation is only supported when A, B and C have the same data type."
            )
        if self.packed is None:
            raise NotImplementedError(
                f"`{self.__class__.__name__}` matmul: operation is not supported"
            )
        else:
            res = torch._cslt_sparse_mm(
                self.packed,
                B,
                bias=bias,
                transpose_result=self.fuse_transpose_cusparselt,
                alg_id=self.alg_id_cusparselt,
            )
            return res.t() if self.fuse_transpose_cusparselt else res
