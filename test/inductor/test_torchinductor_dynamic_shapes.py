# Owner(s): ["module: inductor"]
import contextlib
import importlib
import math
import os
import sys
import unittest
from functools import partial

import torch
import torch._custom_ops as custom_ops
import torch.library
from torch._dynamo.testing import make_test_cls_with_patches
from torch.testing._internal.common_device_type import (
    instantiate_device_type_tests,
    onlyCPU,
    onlyCUDA,
)
from torch.testing._internal.common_utils import (
    IS_ARM64,
    IS_CI,
    IS_WINDOWS,
    parametrize,
    TEST_CUDA_MEM_LEAK_CHECK,
    TEST_WITH_ASAN,
    TEST_WITH_ROCM,
    TestCaseBase as TestCase,
)
from torch.testing._internal.inductor_utils import GPU_TYPE, HAS_CPU, HAS_GPU

if IS_WINDOWS and IS_CI:
    sys.stderr.write(
        "Windows CI does not have necessary dependencies for test_torchinductor_dynamic_shapes yet\n"
    )
    if __name__ == "__main__":
        sys.exit(0)
    raise unittest.SkipTest("requires sympy/functorch/filelock")

# Make the helper files in test/ importable
pytorch_test_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.append(pytorch_test_dir)
from inductor.test_torchinductor import (
    check_model,
    check_model_gpu,
    CommonTemplate,
    copy_tests,
    TestFailure,
)

importlib.import_module("filelock")

# xfail by default, set is_skip=True to skip
test_failures = {
    "test_kwargs_dynamic_shapes": TestFailure(("cpu",)),
    # calling div on only symint args
    "test_AllenaiLongformerBase_repro_dynamic_shapes": TestFailure(("cpu", "cuda")),
    "test_conv_inference_heuristics_dynamic_shapes": TestFailure("cuda"),
}

if TEST_WITH_ROCM:
    # Tensor-likes are not close
    test_failures["test_convolution1_dynamic_shapes"] = TestFailure(
        ("cpu", "cuda"), is_skip=True
    )
    test_failures["test_convolution3_dynamic_shapes"] = TestFailure(
        ("cuda"), is_skip=True
    )
    test_failures["test_expanded_reduction_dynamic_shapes"] = TestFailure(
        ("cuda"), is_skip=True
    )


def make_dynamic_cls(cls, xfail_prop="_expected_failure_dynamic"):
    return make_test_cls_with_patches(
        cls,
        "DynamicShapes",
        "_dynamic_shapes",
        (torch._dynamo.config, "assume_static_by_default", False),
        xfail_prop=xfail_prop,
    )


DynamicShapesCommonTemplate = make_dynamic_cls(CommonTemplate)


if HAS_CPU:

    class DynamicShapesCpuTests(TestCase):
        common = check_model
        device = "cpu"

    copy_tests(DynamicShapesCommonTemplate, DynamicShapesCpuTests, "cpu", test_failures)


if HAS_GPU and not TEST_WITH_ASAN:

    class DynamicShapesGPUTests(TestCase):
        common = check_model_gpu
        device = GPU_TYPE

    copy_tests(
        DynamicShapesCommonTemplate, DynamicShapesGPUTests, GPU_TYPE, test_failures
    )


class TestInductorDynamic(TestCase):
    compile_fn = partial(torch.compile, dynamic=True)

    def setUp(self):
        # HAS_CUDA also checks compute capability to skip tests
        # on older devices
        if not HAS_GPU:
            self.skipTest("Triton not available")
        torch._dynamo.reset()
        super(TestCase, self).setUp()
        # this should be in setUpClass, but device-generic tests
        # don't work with setUpClass well (non-deterministically the wrong setUpClass is resolved),
        # so put it in test setUp, it's cheap
        self._stack = contextlib.ExitStack()
        self._stack.enter_context(
            torch._inductor.config.patch(
                {
                    "debug": False,
                    "cpp.min_chunk_size": 1,
                    "triton.autotune_pointwise": False,  # too slow
                    "implicit_fallbacks": False,
                }
            )
        )

    def tearDown(self):
        self._stack.close()
        super(TestCase, self).tearDown()
        torch._dynamo.reset()

    def test_arange_dynamic(self, device):
        def fn(a):
            batch_size = a.numel()
            max_len = a.max()
            return ~(
                torch.arange(0, max_len, device=a.device)
                .type_as(a)
                .repeat(batch_size, 1)
                .lt(a.unsqueeze(1))
            )

        a = torch.randint(10, 30, (10,), device=device)
        a[0] = 29  # fix max_len
        opt = self.compile_fn(fn)
        res = opt(a)
        ref = fn(a)
        self.assertEqual(res, ref)

    def test_shape_as_constant_reciprocal_float_exp(self, device):
        def fn(x, a):
            return x, -1 / a**1.0

        x = torch.rand(10, 20, device=device)
        opt = self.compile_fn(fn)
        res = opt(x, x.size(0))
        ref = fn(x, x.size(0))
        self.assertEqual(res, ref)

    # not supported yet on cpu, https://github.com/pytorch/pytorch/issues/109897
    @torch._dynamo.config.patch(capture_dynamic_output_shape_ops=True)
    def test_bool_mask_nobreak(self, device):
        def f(x, b):
            return (x[b] * 2).sum()

        opt_f = torch.compile(f, fullgraph=True)
        x = torch.randn(5, device=device)
        b = torch.tensor([True, True, False, False, True], device=device)
        r = f(x, b)
        opt_r = opt_f(x, b)
        self.assertEqual(r, opt_r)

    def test_adaptive_max_pool3d_with_indices(self, device):
        x = 5
        y = torch.rand([9, 10, 9, 8, 6], dtype=torch.float32, device=device)

        def fn(x, y):
            return torch.nn.functional.adaptive_max_pool3d_with_indices(
                output_size=x, input=y, return_indices=True
            )

        opt_f = self.compile_fn(fn)
        r = fn(x, y)
        opt_r = opt_f(x, y)
        self.assertEqual(r, opt_r)

    @torch._dynamo.config.patch(capture_scalar_outputs=True)
    def test_unwrap_storage_didnt_work_repro(self, device):
        def f():
            full = torch.full((), 11)
            i0 = full.item()
            torch._check_is_size(i0)
            return torch.full((i0,), 0)

        opt_f = torch.compile(f, fullgraph=True)
        r = f()
        opt_r = opt_f()
        self.assertEqual(r, opt_r)

    @torch._dynamo.config.patch(capture_dynamic_output_shape_ops=True)
    def test_nonzero_size_factory_nobreak(self, device):
        def f(x, b):
            y = torch.nonzero(b)
            return x.new_zeros(y.size(0))

        opt_f = torch.compile(f, fullgraph=True)
        x = torch.randn(5, device=device)
        b = torch.tensor([True, True, False, False, True], device=device)
        r = f(x, b)
        opt_r = opt_f(x, b)
        self.assertEqual(r, opt_r)

    @torch._dynamo.config.patch(capture_scalar_outputs=True)
    def test_item_nobreak(self, device):
        @torch.compile(fullgraph=True)
        def f(x):
            y = x.item()
            return torch.empty(y)

        f(torch.tensor([3], device=device))

    @torch._dynamo.config.patch(capture_scalar_outputs=True)
    def test_item_bool_nobreak(self, device):
        @torch.compile(fullgraph=True)
        def f(x):
            return x.item()

        f(torch.tensor([True], device=device))

    @torch._dynamo.config.patch(capture_scalar_outputs=True)
    def test_item_zeros_nobreak(self, device):
        @torch.compile(fullgraph=True)
        def f(x):
            y = x.item()
            torch.empty(y)
            # This will avoid a NopSchedulerNode
            return x.new_zeros(y)

        f(torch.tensor([3], device=device))

    @torch._dynamo.config.patch(capture_scalar_outputs=True)
    def test_item_return(self, device):
        @torch.compile(fullgraph=True)
        def f(x):
            y = x.item()
            z = x.item()
            return y + z

        f(torch.tensor([3], device=device))

    @torch._dynamo.config.patch(
        capture_scalar_outputs=True, capture_dynamic_output_shape_ops=True
    )
    def test_float_item_inf(self, device):
        @torch.compile(fullgraph=True)
        def f(x):
            return x.item() == math.inf

        f(torch.tensor([3.0], device=device))

    @torch._dynamo.config.patch(
        capture_scalar_outputs=True, capture_dynamic_output_shape_ops=True
    )
    def test_float_item_neginf(self, device):
        @torch.compile(fullgraph=True)
        def f(x):
            return x.item() == -math.inf

        f(torch.tensor([3.0], device=device))

    @torch._dynamo.config.patch(capture_scalar_outputs=True)
    @torch._inductor.config.patch(implicit_fallbacks=True)
    def test_item_to_inputs_kernel_nobreak(self, device):
        with torch.library._scoped_library("test", "DEF") as lib:
            try:

                @custom_ops.custom_op("test::foo")
                def foo(x: torch.Tensor, y: int) -> torch.Tensor:
                    raise NotImplementedError()

                @custom_ops.impl("test::foo")
                def foo_impl(x: torch.Tensor, y: int) -> torch.Tensor:
                    return x.clone()

                @torch.library.impl_abstract("test::foo", lib=lib)
                def foo_meta(x: torch.Tensor, y: int) -> torch.Tensor:
                    return x.clone()

                @torch.compile(fullgraph=True)
                def f(x, r):
                    y = x.item()
                    return torch.ops.test.foo(r, y)

                f(torch.tensor([3], device=device), torch.randn(10, device=device))

            finally:
                custom_ops._destroy("test::foo")

    @torch._dynamo.config.patch(
        capture_scalar_outputs=True, capture_dynamic_output_shape_ops=True
    )
    def test_float_item_return(self, device):
        @torch.compile(fullgraph=True)
        def f(x):
            return x.item()

        f(torch.tensor([3.0], device=device))

    @unittest.skipIf(TEST_CUDA_MEM_LEAK_CHECK, "failing memory leak check")
    @torch._dynamo.config.patch(capture_scalar_outputs=True)
    def test_unbacked_index_select(self, device):
        # Tests if unbacked symbols captured by inner_fn are properly tracked
        def f(x):
            y = x.item()
            return torch.index_select(
                torch.ones(y, device=device), 0, torch.tensor([0, 2, 1], device=device)
            )

        cf = torch.compile(fullgraph=True)(f)
        arg = torch.tensor(5, device=device)
        self.assertEqual(f(arg), cf(arg))

    @torch._dynamo.config.patch(
        capture_scalar_outputs=True, capture_dynamic_output_shape_ops=True
    )
    def test_return_unbacked_view_split(self, device):
        def f(values, length_per_key):
            u0, u1 = length_per_key.tolist()
            torch._check_is_size(u0)
            torch._check_is_size(u1)
            v1, v2 = torch.functional.split(values, [u0, u1])
            return v1, v2

        cf = torch.compile(fullgraph=True)(f)
        args = (
            torch.randn(8, requires_grad=True, device=device),
            torch.tensor([3, 5], device=device),
        )
        self.assertEqual(f(*args), cf(*args))

    @torch._dynamo.config.patch(capture_scalar_outputs=True)
    def test_unbacked_matmul(self, device):
        def f(x):
            y = x.item()
            return torch.ones(1, y, device=device) @ torch.ones(y, 1, device=device)

        cf = torch.compile(fullgraph=True)(f)
        arg = torch.tensor(5, device=device)
        self.assertEqual(f(arg), cf(arg))

    @torch._dynamo.config.patch(capture_scalar_outputs=True)
    def test_unbacked_reduction(self, device):
        expect_fail = device == "cpu" and not IS_ARM64
        try:

            def f(x):
                y = x.item()
                return torch.ones(y, device=device).sum()

            cf = torch.compile(fullgraph=True)(f)
            arg = torch.tensor(5, device=device)
            self.assertEqual(f(arg), cf(arg))
        except Exception:
            if not expect_fail:
                raise
        else:
            if expect_fail:
                self.fail("expected to fail, but actually passed")

    @torch._dynamo.config.patch(
        capture_scalar_outputs=True, capture_dynamic_output_shape_ops=True
    )
    @torch._inductor.config.patch(implicit_fallbacks=True)
    def test_dynamic_stride_nobreak(self, device):
        with torch.library._scoped_library("test", "DEF") as lib:
            try:

                @custom_ops.custom_op("test::foo")
                def foo(x: torch.Tensor) -> torch.Tensor:
                    raise NotImplementedError()

                @custom_ops.impl("test::foo")
                def foo_impl(x: torch.Tensor) -> torch.Tensor:
                    stride = x.item()
                    return torch.empty_strided((1,), (stride,), device=x.device)

                @torch.library.impl_abstract("test::foo", lib=lib)
                def foo_meta(x: torch.Tensor) -> torch.Tensor:
                    ctx = torch.library.get_ctx()
                    stride = ctx.new_dynamic_size()
                    return torch.empty_strided((1,), (stride,), device=x.device)

                @torch.compile(fullgraph=True)
                def f(x):
                    r = torch.ops.test.foo(x)
                    y = r.stride(0)
                    return torch.empty(y, device=x.device)

                f(torch.tensor([3], device=device))

            finally:
                custom_ops._destroy("test::foo")

    @torch._inductor.config.patch(disable_cpp_codegen=True)
    def test_floor(self):
        # `int(n * 0.2)` will be generated as `floor(0.2*s0)` of torch.SymInt type.
        # If cpp codegen is disabled, we should generate `math.floor` using PythonPrinter.
        def fn(x):
            n = x.size(-1)
            y = x + int(n * 0.2) + 1
            return y

        opt = self.compile_fn(fn)
        # The first run doesn't trigger dynamic shapes.
        x0 = torch.rand(5)
        ref0 = fn(x0)
        res0 = opt(x0)
        self.assertEqual(ref0, res0)
        # The second run triggers dynamic shapes.
        x1 = torch.rand(8)
        ref1 = fn(x1)
        res1 = opt(x1)
        self.assertEqual(ref1, res1)

    # Need to comment: is xpu need this? if yes we may need to add onlyGPU
    @onlyCUDA
    def test_pad_dynamic(self, device):
        def get_same_padding(x: int, k: int, s: int, d: int):
            return max((math.ceil(x / s) - 1) * s + (k - 1) * d + 1 - x, 0)

        def pad_same(x, k, s, d=(1, 1), value=0):
            ih, iw = x.size()[-2:]
            pad_h, pad_w = get_same_padding(ih, k[0], s[0], d[0]), get_same_padding(
                iw, k[1], s[1], d[1]
            )
            if pad_h > 0 or pad_w > 0:
                x = torch.nn.functional.pad(
                    x,
                    [pad_w // 2, pad_w - pad_w // 2, pad_h // 2, pad_h - pad_h // 2],
                    value=value,
                )
            return x

        x = torch.randn(2, 24, 110, 110, device=device)
        opt = self.compile_fn(pad_same)
        res = opt(x, (5, 5), (2, 2))
        ref = pad_same(x, (5, 5), (2, 2))
        self.assertEqual(res, ref, atol=0, rtol=0)

    def test_slice_scatter(self, device):
        def fn(i):
            s3 = i.size(0)
            x = torch.ones(64, s3, device=device)
            y = torch.ones(64, s3 // 2, device=device)
            return torch.slice_scatter(x, y, 1, s3 // 2, 2 * (s3 // 2))

        a = torch.randn(16, device=device)
        cfn = self.compile_fn(fn)
        expect = fn(a)
        actual = cfn(a)
        self.assertEqual(expect, actual)

    def test_slice_index_changing_sign(self, device):
        def fn(x, y):
            y0, y1 = y.shape
            return x[: (y0 - y1)].clone()

        a = torch.randn(32, 32, device=device)
        cfn = self.compile_fn(fn)

        # y0 > y1 -> y0 - y1 is positive
        b = torch.randn(16, 2, device=device)
        expect = fn(a, b)
        actual = cfn(a, b)
        self.assertEqual(expect, actual)

        # y0 < y1 -> y0 - y1 is negative
        b = torch.randn(2, 16, device=device)
        expect = fn(a, b)
        actual = cfn(a, b)
        self.assertEqual(expect, actual)

    def test_sym_stride_lowering(self, device):
        def fn(x):
            s0 = (x + 1).stride(0)
            return x * s0

        a = torch.randn(32, 32, device=device)
        cfn = self.compile_fn(fn)
        self.assertEqual(fn(a), cfn(a))

    @torch._dynamo.config.patch(capture_scalar_outputs=True)
    def test_item_materialize(self, device):
        def fn(x):
            return x.sum(dim=0).view(4).tolist()

        cfn = torch.compile(fullgraph=True)(fn)

        a = torch.ones(3, 4, dtype=torch.int64, device=device)
        self.assertEqual(cfn(a), fn(a))

    def test_abs(self, device):
        def fn(x, y):
            y0, y1 = y.shape
            # Slicing checks abs in wrapper code,
            # multiplication tests abs in kernel code
            return x[: abs(y0 - y1)] * abs(y0 - y1)

        a = torch.randn(32, 32, device=device)
        cfn = self.compile_fn(fn)

        # y0 > y1 -> y0 - y1 is positive
        b = torch.randn(16, 2, device=device)
        expect = fn(a, b)
        actual = cfn(a, b)
        self.assertEqual(expect, actual)

        # y0 < y1 -> y0 - y1 is negative
        b = torch.randn(2, 16, device=device)
        expect = fn(a, b)
        actual = cfn(a, b)
        self.assertEqual(expect, actual)

    def test_float_is_integer(self, device):
        def fn(x, mul, dim=-1):
            size = x.size(dim)
            m = size / mul
            if m.is_integer():
                return m
            return size

        a = torch.randn((3, 6, 4, 2), device=device)
        cfn = self.compile_fn(fn)

        expect = fn(a, 2)
        actual = cfn(a, 2)
        self.assertEqual(expect, actual)

    @onlyCPU
    def test_arithmetic_constant_folding(self, device):
        def test(fn):
            cfn = self.compile_fn(fn)
            expect = fn(3)
            actual = cfn(3)
            self.assertEqual(expect, actual)

        def add(x):
            return x + torch.zeros(3)

        test(add)

        def mul(x):
            return x * torch.ones(3)

        test(mul)

        def div(x):
            return x / torch.ones(3)

        test(div)

    @onlyCPU
    def test_sub_constant_folding(self, device):
        def sub(x):
            return x - torch.zeros(3)

        cfn = self.compile_fn(sub)
        expect = sub(3)
        actual = cfn(3)
        self.assertEqual(expect, actual)

    def test_full(self, device):
        def fn(a):
            return torch.full((3,), a), torch.full((3,), torch.sym_float(a))

        cfn = self.compile_fn(fn)
        expect = fn(5)
        actual = cfn(5)
        self.assertEqual(expect, actual)

    @parametrize(
        "op",
        [
            math.sqrt,
            math.sin,
            math.cos,
            math.cosh,
            math.sin,
            math.sinh,
            math.tan,
            math.tanh,
            math.asin,
            math.acos,
            math.atan,
        ],
    )
    def test_math_ops(self, device, op):
        def func(x, fn, a):
            return x + fn(a)

        cfunc = self.compile_fn(func, fullgraph=True)
        x = torch.rand(10, device=device)
        a = -1 if op in (math.asin, math.acos) else 12
        expected = func(x, op, a)
        output = cfunc(x, op, a)
        self.assertEqual(output, expected)


instantiate_device_type_tests(TestInductorDynamic, globals())

if __name__ == "__main__":
    from torch._dynamo.test_case import run_tests

    # Slow on ASAN after https://github.com/pytorch/pytorch/pull/94068
    if (HAS_CPU or HAS_GPU) and not TEST_WITH_ASAN:
        run_tests(needs="filelock")
