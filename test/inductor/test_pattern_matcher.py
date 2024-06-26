# Owner(s): ["module: inductor"]
import copy
import unittest

import torch
import torch._dynamo.config as dynamo_config
import torch._inductor.config as inductor_config
from torch._dynamo.test_case import run_tests, TestCase
from torch._dynamo.utils import count_calls, counters
from torch._higher_order_ops.out_dtype import out_dtype
from torch._inductor.fx_passes import joint_graph

from torch._inductor.fx_passes.serialized_patterns.central_index import (
    get_serialized_pattern,
)
from torch._inductor.pattern_matcher import (
    _TargetExpr,
    Arg,
    CallFunction,
    gen_pattern,
    KeywordArg,
    Match,
    PatternExpr,
    PatternMatcherPass,
    PatternPrettyPrinter,
    register_graph_pattern,
    stable_topological_sort,
)
from torch._inductor.utils import run_and_get_code
from torch._inductor.virtualized import V
from torch.testing import FileCheck
from torch.testing._internal.common_cuda import SM80OrLater
from torch.testing._internal.common_utils import IS_LINUX, skipIfRocm
from torch.testing._internal.inductor_utils import HAS_CUDA


class TestPatternMatcher(TestCase):
    def common(
        self,
        fn,
        args,
        expected_matches,
        expected_nodes,
        additional_check=lambda code: None,
    ):
        counters.clear()
        torch.manual_seed(42)
        expected = fn(*args)
        torch.manual_seed(42)
        actual, codes = run_and_get_code(torch.compile(fn), *args)
        if len(codes) == 1:
            codes = codes[0]
        torch.testing.assert_close(actual, expected)

        self.assertEqual(
            counters["inductor"]["pattern_matcher_count"], expected_matches
        )
        self.assertEqual(counters["inductor"]["pattern_matcher_nodes"], expected_nodes)
        additional_check(codes)
        counters.clear()

    def test_mm_plus_mm(self):
        def fn(a, b, c, d):
            return torch.add(torch.mm(a, b), torch.mm(c, d))

        # when m1 == n1 and m2 == n2, mm_plus_mm can be matched to fused op
        fusible_args_list = [
            (
                torch.randn(16, 16, device="cuda"),
                torch.randn(16, 16, device="cuda"),
                torch.randn(16, 16, device="cuda"),
                torch.randn(16, 16, device="cuda"),
            ),
            (
                torch.randn(1, 4, device="cuda"),
                torch.randn(4, 2, device="cuda"),
                torch.randn(1, 5, device="cuda"),
                torch.randn(5, 2, device="cuda"),
            ),
        ]
        for args in fusible_args_list:
            self.common(fn, args, 1, 3)

        # if not fusible, it can only match add(mm())
        unfusible_args_list = [
            # https://github.com/pytorch/pytorch/issues/100670.
            (
                torch.randn(1, 4, device="cuda"),
                torch.randn(4, 2, device="cuda"),
                torch.randn(1, 2, device="cuda"),
                torch.randn(2, 1, device="cuda"),
            ),
            (
                torch.randn(1, 2, device="cuda"),
                torch.randn(2, 1, device="cuda"),
                torch.randn(1, 4, device="cuda"),
                torch.randn(4, 2, device="cuda"),
            ),
        ]
        for args in unfusible_args_list:
            self.common(fn, args, 1, 2)

    def _test_fused_int_mm_mul_impl(self, fn, args, fused_int_mm_mul_expected=True):
        torch._dynamo.reset()
        counters.clear()
        ref = fn(*args)
        test, (code,) = run_and_get_code(torch.compile(fn, mode="max-autotune"), *args)
        self.assertEqual("fused_int_mm_mul" in code, fused_int_mm_mul_expected)
        if fused_int_mm_mul_expected:
            indices = ~ref.isinf()
            torch.testing.assert_close(
                ref[indices], test[indices]
            )  # also checks that dtype is correct

    @skipIfRocm
    @unittest.skipIf(not SM80OrLater, "need sm_80")
    @inductor_config.patch(force_fuse_int_mm_with_mul=True)
    def test_fused_int_mm_mul(self):
        def fn1(a, b, c):
            return out_dtype(torch.ops.aten.mm.default, torch.int32, a, b) * c

        def fn2(a, b, c):
            return (out_dtype(torch.ops.aten.mm.default, torch.int32, a, b) * c).to(
                torch.bfloat16
            )

        args_list = [
            (
                torch.randint(-128, 127, (32, 32), dtype=torch.int8, device="cuda"),
                torch.randint(-128, 127, (32, 8), dtype=torch.int8, device="cuda"),
                torch.randn((32, 1), dtype=torch.float16, device="cuda") * 0 + 0.5,
            ),
            (
                torch.randint(-128, 127, (32, 32), dtype=torch.int8, device="cuda"),
                torch.randint(-128, 127, (32, 8), dtype=torch.int8, device="cuda"),
                torch.randn((1, 8), dtype=torch.bfloat16, device="cuda"),
            ),
            (
                torch.randint(-128, 127, (32, 32), dtype=torch.int8, device="cuda"),
                torch.randint(-128, 127, (32, 8), dtype=torch.int8, device="cuda"),
                torch.randn((1, 8), dtype=torch.float32, device="cuda"),
            ),
        ]

        for args in args_list:
            self._test_fused_int_mm_mul_impl(fn1, args, True)
            self._test_fused_int_mm_mul_impl(fn2, args, True)

    @skipIfRocm
    @unittest.skipIf(not SM80OrLater, "need sm_80")
    @inductor_config.patch(force_fuse_int_mm_with_mul=True)
    def test_fused_int_mm_mul_gating(self):
        def fn1(a, b, c):
            return out_dtype(torch.ops.aten.mm.default, torch.int32, a, b) * c

        args1 = (
            torch.randint(-128, 127, (32, 32), dtype=torch.int8, device="cuda"),
            torch.randint(-128, 127, (32, 8), dtype=torch.int8, device="cuda"),
            torch.randn((8), dtype=torch.float32, device="cuda"),
        )

        args2 = (
            torch.randint(-128, 127, (32, 32), dtype=torch.int8, device="cuda"),
            torch.randint(-128, 127, (32, 8), dtype=torch.int8, device="cuda"),
            torch.randn((32, 1), dtype=torch.float16, device="cuda"),
        )
        self._test_fused_int_mm_mul_impl(fn1, args1, False)
        self._test_fused_int_mm_mul_impl(fn1, [arg.cpu() for arg in args2], False)
        inductor_config.force_fuse_int_mm_with_mul = False
        self._test_fused_int_mm_mul_impl(fn1, args2, False)

    def _test_mixed_impl(self, fn, args, mixed_mm_expected, fallback_mixed_mm_expected):
        torch._dynamo.reset()
        counters.clear()
        ref = fn(*args)
        test, (code,) = run_and_get_code(torch.compile(fn), *args)
        torch.testing.assert_close(ref, test)
        self.assertEqual("mixed_mm" in code, mixed_mm_expected)
        self.assertEqual("fallback_mixed_mm" in code, fallback_mixed_mm_expected)

    @unittest.skipIf(not SM80OrLater, "need sm_80")
    @inductor_config.patch(force_mixed_mm=True)
    def test_mixed_mm(self):
        def fn(a, b):
            return torch.mm(a, b.to(a.dtype))

        args_list = [
            (
                torch.randn(8, 8, device="cuda"),
                torch.randint(-128, 127, (8, 8), dtype=torch.int8, device="cuda"),
            ),
            (
                torch.randn(8, 2, device="cuda", dtype=torch.bfloat16),
                torch.randint(-128, 127, (2, 8), dtype=torch.int8, device="cuda"),
            ),
            (
                torch.randn(8, 5, device="cuda", dtype=torch.float16),
                torch.randint(0, 255, (5, 2), dtype=torch.uint8, device="cuda"),
            ),
            (
                torch.randn(8, 8, device="cuda", dtype=torch.float32),
                torch.randn(8, 8, device="cuda", dtype=torch.bfloat16),
            ),
        ]

        for args in args_list:
            self._test_mixed_impl(fn, args, True, False)

    @unittest.skipIf(not SM80OrLater, "need sm_80")
    @inductor_config.patch(force_mixed_mm=True)
    def test_mixed_mm_bad_cases(self):
        def fn(a, b):
            return torch.mm(a, b.to(a.dtype))

        args_list = [
            (
                torch.randn(8, 8, device="cuda", dtype=torch.float16),
                torch.randint(-128, 127, (2, 8), dtype=torch.int8, device="cuda").t(),
            ),
            (
                torch.randn(8, 8, device="cuda", dtype=torch.bfloat16),
                torch.randint(0, 255, (2, 8), dtype=torch.uint8, device="cuda").t(),
            ),
        ]

        for args in args_list:
            self._test_mixed_impl(fn, args, True, True)

    @unittest.skipIf(not SM80OrLater, "need sm_80")
    @inductor_config.patch(force_mixed_mm=True, max_autotune_gemm=True)
    def test_mixed_mm_epi_works(self):
        def fn(a, b, c, d):
            return torch.mm(a, b.to(a.dtype)) * c + d

        args_list = [
            (
                torch.randn(8, 8, device="cuda"),
                torch.randint(-128, 127, (8, 8), dtype=torch.int8, device="cuda"),
                torch.randn(8, device="cuda"),
                torch.randn(8, device="cuda"),
            ),
            (
                torch.randn(8, 2, device="cuda", dtype=torch.bfloat16),
                torch.randint(-128, 127, (2, 8), dtype=torch.int8, device="cuda"),
                torch.randn(8, device="cuda", dtype=torch.bfloat16),
                torch.randn(8, device="cuda", dtype=torch.bfloat16),
            ),
            (
                torch.randn(8, 5, device="cuda", dtype=torch.float16),
                torch.randint(0, 255, (5, 2), dtype=torch.uint8, device="cuda"),
                torch.randn(2, device="cuda", dtype=torch.float16),
                torch.randn(2, device="cuda", dtype=torch.float16),
            ),
        ]

        for args in args_list:
            self._test_mixed_impl(fn, args, True, False)

    @unittest.skipIf(not SM80OrLater, "need sm_80")
    def test_mixed_mm_gating(self):
        def fn(a, b):
            return torch.mm(a, b.to(a.dtype))

        args = (
            torch.randn(8, 8, device="cuda"),
            torch.randint(-128, 127, (8, 8), dtype=torch.int8, device="cuda"),
        )
        # will ignore the mixed_mm code (including fallback)
        with inductor_config.patch({"force_mixed_mm": False, "use_mixed_mm": False}):
            self._test_mixed_impl(fn, args, False, False)

        # will use fallback_mixed_mm kernel due to no gemm_autotune
        with inductor_config.patch({"force_mixed_mm": False, "use_mixed_mm": True}):
            self._test_mixed_impl(fn, args, True, True)

        # will use mixed_mm kernel
        with inductor_config.patch({"force_mixed_mm": True, "use_mixed_mm": False}):
            self._test_mixed_impl(fn, args, True, False)

        # shows that use_mixed_mm doesn't do anything if foce_mixed_mm is set
        with inductor_config.patch({"force_mixed_mm": True, "use_mixed_mm": True}):
            self._test_mixed_impl(fn, args, True, False)

    @inductor_config.patch(use_mixed_mm=True)
    def test_mixed_mm_cpu(self):
        def fn(a, b):
            return torch.mm(a, b.to(a.dtype))

        args = (
            torch.randn(8, 8),
            torch.randint(-128, 127, (8, 8), dtype=torch.int8),
        )
        self._test_mixed_impl(fn, args, False, False)

    @unittest.skipIf(not SM80OrLater, "need sm_80")
    @inductor_config.patch(use_mixed_mm=True)
    def test_uint4x2_mixed_mm(self):
        def fn(a, b):
            return torch.mm(
                a,
                torch.cat((b & 0xF, b >> 4), 1)
                .reshape(-1, b.shape[1])
                .to(a.dtype)
                .sub(8),
            )

        args_list = [
            (
                torch.randn(8, 8, device="cuda"),
                torch.randint(0, 255, (4, 8), dtype=torch.uint8, device="cuda"),
            ),
            (
                torch.randn(8, 8, device="cuda", dtype=torch.float16),
                torch.randint(0, 255, (4, 8), dtype=torch.uint8, device="cuda")
                .t()
                .contiguous()
                .t(),
            ),
            (
                torch.randn(8, 8, device="cuda"),
                torch.randint(0, 255, (4, 8), dtype=torch.int32, device="cuda"),
            ),
            (
                torch.randn(8, 8, device="cuda"),
                torch.randint(0, 255, (4, 8), dtype=torch.int64, device="cuda"),
            ),
        ]

        for args in args_list:
            torch._dynamo.reset()
            counters.clear()
            ref = fn(*args)
            test, (code,) = run_and_get_code(torch.compile(fn), *args)
            torch.testing.assert_close(ref, test)
            self.assertTrue("uint4x2_mixed_mm" in code)

    @unittest.skipIf(not SM80OrLater, "need sm_80")
    @inductor_config.patch(use_mixed_mm=True)
    def test_uint4x2_mixed_mm_epi(self):
        def fn(a, b, c, d):
            return (
                torch.mm(
                    a,
                    torch.cat((b & 0xF, b >> 4), 1)
                    .reshape(-1, b.shape[1])
                    .to(a.dtype)
                    .sub(8),
                )
                * c
                + d
            )

        args_list = [
            (
                torch.randn(8, 8, device="cuda"),
                torch.randint(0, 255, (4, 8), dtype=torch.uint8, device="cuda"),
                torch.randn(8, device="cuda"),
                torch.randn(8, device="cuda"),
            ),
        ]

        for args in args_list:
            torch._dynamo.reset()
            counters.clear()
            ref = fn(*args)
            test, (code,) = run_and_get_code(torch.compile(fn), *args)
            torch.testing.assert_close(ref, test)
            self.assertTrue("uint4x2_mixed_mm" in code)
            self.assertTrue("fused_add_mm_mul" in code)

    @inductor_config.patch(use_mixed_mm=True)
    def test_uint4x2_mixed_mm_fail_to_match(self):
        def fn(a, b):
            return torch.mm(
                a,
                torch.cat((b & 0xF, b >> 4), 1)
                .reshape(-1, b.shape[1])
                .to(a.dtype)
                .sub(8),
            )

        args_list = [
            (  # cpu
                torch.randn(8, 8),
                torch.randint(0, 255, (4, 8), dtype=torch.uint8),
            ),
            (  # int8
                torch.randn(8, 8, device="cuda"),
                torch.randint(-128, 127, (4, 8), dtype=torch.int8, device="cuda"),
            ),  # we don't match for int8 since numerics
        ]  # for int8 bitshifts don't match between triton and pytorch

        for args in args_list:
            torch._dynamo.reset()
            counters.clear()
            ref = fn(*args)
            test, (code,) = run_and_get_code(torch.compile(fn), *args)
            torch.testing.assert_close(ref, test)
            self.assertFalse("uint4x2_mixed_mm" in code)

    @inductor_config.patch(use_mixed_mm=False)
    def test_uint4x2_mixed_mm_gating_works(self):
        def fn(a, b):
            return torch.mm(
                a,
                torch.cat((b & 0xF, b >> 4), 1)
                .reshape(-1, b.shape[1])
                .to(a.dtype)
                .sub(8),
            )

        args_list = [
            (
                torch.randn(8, 8, device="cuda"),
                torch.randint(0, 255, (4, 8), dtype=torch.uint8, device="cuda"),
            ),
        ]

        for args in args_list:
            torch._dynamo.reset()
            counters.clear()
            ref = fn(*args)
            test, (code,) = run_and_get_code(torch.compile(fn), *args)
            torch.testing.assert_close(ref, test)
            self.assertFalse("uint4x2_mixed_mm" in code)

    def test_addmm(self):
        def fn(a, b, c):
            return torch.add(a, torch.mm(b, c)), torch.mm(b, c) + a

        args_list = [
            (
                torch.randn(16, 16, device="cuda"),
                torch.randn(16, 16, device="cuda"),
                torch.randn(16, 16, device="cuda"),
                True,
            ),
            (
                torch.randn(8, device="cuda"),
                torch.randn(16, 16, device="cuda"),
                torch.randn(16, 8, device="cuda"),
                True,
            ),
            (
                torch.randn(16, 16, device="cuda"),
                torch.randn(1, 16, device="cuda"),
                torch.randn(16, 16, device="cuda"),
                False,
            ),
            (
                torch.randn(1, 16, 16, device="cuda"),
                torch.randn(16, 16, device="cuda"),
                torch.randn(16, 16, device="cuda"),
                False,
            ),
            (
                4,
                torch.randn(16, 16, device="cuda"),
                torch.randn(16, 16, device="cuda"),
                False,
            ),
        ]
        for a, b, c, should_fuse in args_list:
            torch._dynamo.reset()
            counters.clear()
            args = (a, b, c)
            e1, e2 = fn(*args)
            a1, a2 = torch.compile(fn)(*args)
            torch.testing.assert_close(a1, e1)
            torch.testing.assert_close(a2, e2)
            count, nodes = (2, 4) if should_fuse else (0, 0)
            self.assertEqual(counters["inductor"]["pattern_matcher_count"], count)
            self.assertEqual(counters["inductor"]["pattern_matcher_nodes"], nodes)

    def test_addmm_symbolic_scalar(self):
        def fn(m1, m2):
            bias = m1.size(0)
            return torch.add(bias, torch.mm(m1, m2)), torch.mm(m1, m2) + bias

        m1 = torch.randn(16, 16, device="cuda")
        m2 = torch.randn(16, 16, device="cuda")

        counters.clear()
        expect = fn(m1, m2)
        actual = torch.compile(fn, dynamic=True)(m1, m2)
        self.assertEqual(expect, actual)
        self.assertEqual(counters["inductor"]["pattern_matcher_count"], 0)

    def test_addmm_broadcasting_bias(self):
        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.functional.linear
                self.linear_weight = torch.randn(4, 4).cuda()
                self.bias = torch.randn(1, 4).cuda()

            def forward(self, x):
                x = self.linear(x, self.linear_weight, self.bias)
                return x

        input_tensor = torch.randn(1, 3, 4).cuda()

        func = Model().cuda()

        res1 = func(input_tensor)
        jit_func = torch.compile(func)
        res2 = jit_func(input_tensor)

        self.assertEqual(res1, res2)

    def test_cat_mm(self):
        def fn(a, b, c):
            return torch.cat(
                [
                    torch.mm(a, b),
                    torch.mm(b, c),
                    torch.mm(a, c),
                ],
                1,
            )

        args = [
            torch.randn(16, 16, device="cuda"),
            torch.randn(16, 16, device="cuda"),
            torch.randn(16, 16, device="cuda"),
        ]
        self.common(fn, args, 2, 5)

    def test_cat_addmm(self):
        def fn(a, b, c):
            return torch.cat(
                [
                    torch.addmm(a, b, c),
                    torch.addmm(b, c, a),
                    torch.addmm(c, a, b),
                ],
                1,
            )

        args = [
            torch.randn(16, 16, device="cuda"),
            torch.randn(16, 16, device="cuda"),
            torch.randn(16, 16, device="cuda"),
        ]
        self.common(fn, args, 2, 5)

    def test_cat_slice_cat_cuda(self):
        def fn(a, b):
            cat_1 = torch.ops.aten.cat.default([a, b], 1)
            slice_1 = torch.ops.aten.slice.Tensor(cat_1, 0, 0, 9223372036854775807)
            slice_2 = torch.ops.aten.slice.Tensor(slice_1, 1, 0, 19)
            return torch.ops.aten.cat.default([cat_1, slice_2], 1)

        args = [
            torch.randn(2, 32, device="cuda"),
            torch.randn(2, 16, device="cuda"),
        ]
        self.common(fn, args, 1, 3)

        args = [
            torch.randn(2, 8, device="cuda"),
            torch.randn(2, 16, device="cuda"),
        ]
        counters.clear()
        expected = fn(*args)
        actual = torch.compile(fn)(*args)
        torch.testing.assert_close(actual, expected)
        # We don't recompile for dynamic-shape cases.
        if dynamo_config.assume_static_by_default:
            self.assertEqual(counters["inductor"]["pattern_matcher_count"], 1)
            self.assertEqual(counters["inductor"]["pattern_matcher_nodes"], 3)

        # Verify we fallback to non-optimal path for negative `end`.
        def fn(a, b):
            cat_1 = torch.ops.aten.cat.default([a, b], 1)
            slice_1 = torch.ops.aten.slice.Tensor(cat_1, 0, 0, 9223372036854775807)
            slice_2 = torch.ops.aten.slice.Tensor(slice_1, 1, 0, -1)
            return torch.ops.aten.cat.default([cat_1, slice_2], 1)

        args = [
            torch.randn(2, 8, device="cuda"),
            torch.randn(2, 16, device="cuda"),
        ]
        self.common(fn, args, 1, 3)

    def test_pointless_convert(self):
        def fn1(x):
            x = torch.ops.prims.convert_element_type.default(x, torch.float16)
            x = torch.ops.prims.convert_element_type.default(x, torch.float32)
            return x

        gm = torch.fx.symbolic_trace(fn1)
        self.assertEqual(count_calls(gm.graph), 2)
        joint_graph.joint_graph_passes(gm)
        self.assertEqual(count_calls(gm.graph), 1)

        def fn2(x):
            x = torch.ops.prims.convert_element_type.default(x, torch.int32)
            x = torch.ops.prims.convert_element_type.default(x, torch.float32)
            return x

        gm = torch.fx.symbolic_trace(fn2)
        self.assertEqual(count_calls(gm.graph), 2)
        joint_graph.joint_graph_passes(gm)
        self.assertEqual(count_calls(gm.graph), 2)

    # Constant folding was explicitly turned off due to issue #108388
    # Turn it back on for test
    @inductor_config.patch(joint_graph_constant_folding=True)
    def test_pointless_cumsum(self):
        def fn1():
            ones = torch.full(
                [1, 128], 1, layout=torch.strided, dtype=torch.float32
            ).to(torch.int64)
            return torch.cumsum(ones, 1) * ones

        def fn2():
            ones = torch.full(
                [55, 10], 1, layout=torch.strided, dtype=torch.float32
            ).to(torch.int64)
            return torch.cumsum(ones, 1)

        def fn3():
            twos = torch.full([5, 4, 3], 2, dtype=torch.int64)
            return torch.cumsum(twos, 0)

        def fn4():
            x = torch.full([100], 0.1, dtype=torch.float32)
            return torch.cumsum(x, 0)

        def fn5():
            t1 = torch.full([2, 4], 1)
            t2 = t1.to(dtype=torch.bool)
            return torch.cumsum(t2, 1)

        def fn6():
            x = torch.full([10, 10], True, dtype=torch.int32)
            return torch.cumsum(x, 1)

        for fn in (fn1, fn2, fn3, fn4, fn5, fn6):
            result, (code,) = run_and_get_code(torch.compile(fn, fullgraph=True))
            self.assertNotIn("aten.cumsum", code)
            self.assertEqual(result, fn())
            self.assertEqual(counters["inductor"]["pattern_matcher_count"], 1)
            counters.clear()

    def test_splitwithsizes_cat(self):
        # Good case
        def fn(a):
            split_with_sizes = torch.ops.aten.split_with_sizes.default(a, [8, 24], 1)
            getitem = split_with_sizes[0]
            getitem_1 = split_with_sizes[1]
            cat = torch.ops.aten.cat.default([getitem, getitem_1], 1)
            return cat**2

        args = [
            torch.randn(2, 32, device="cuda"),
        ]
        self.common(fn, args, 1, 4)

        # Not all getitems are passed to cat
        def fn(a):
            split_with_sizes = torch.ops.aten.split_with_sizes.default(a, [8, 8, 16], 1)
            getitem = split_with_sizes[0]
            getitem_1 = split_with_sizes[1]
            getitem_2 = split_with_sizes[2]
            cat = torch.ops.aten.cat.default([getitem, getitem_1], 1)
            return cat**2 + getitem_2

        args = [
            torch.randn(2, 32, device="cuda"),
        ]
        self.common(fn, args, 0, 0)

        # Different dimensions  (TODO this case should be handled by replacing with a reshape)
        def fn(a):
            split_with_sizes = torch.ops.aten.split_with_sizes.default(
                a, [8, 8, 8, 8], 1
            )
            cat = torch.ops.aten.cat.default(split_with_sizes, 0)
            return cat**2

        args = [
            torch.randn(2, 32, device="cuda"),
        ]
        self.common(fn, args, 0, 0)

        # https://github.com/pytorch/pytorch/issues/99686.
        def fn(a):
            x = torch.ops.aten.split_with_sizes.default(a, [3, 2, 3], dim=1)
            cat = torch.ops.aten.cat.default([x[1], x[0], x[2]], dim=1)
            return cat

        args = [
            torch.randn(1, 8, device="cuda"),
        ]
        self.common(fn, args, 0, 0)

    def test_cat_splitwithsizes(self):
        # good case
        def fn(a, b, c):
            cat = torch.ops.aten.cat.default([a, b, c], 1)
            split_with_sizes = torch.ops.aten.split_with_sizes.default(
                cat, [2, 3, 5], 1
            )
            return [s**2 for s in split_with_sizes]

        args = [
            torch.randn(2, 2, device="cuda"),
            torch.randn(2, 3, device="cuda"),
            torch.randn(2, 5, device="cuda"),
        ]
        self.common(fn, args, 1, 2)

        # cat node has other users
        def fn(a, b, c):
            cat = torch.ops.aten.cat.default([a, b, c], 1)
            split_with_sizes = torch.ops.aten.split_with_sizes.default(
                cat, [2, 3, 5], 1
            )
            return [s**2 for s in split_with_sizes] + [cat**3]

        args = [
            torch.randn(2, 2, device="cuda"),
            torch.randn(2, 3, device="cuda"),
            torch.randn(2, 5, device="cuda"),
        ]
        self.common(fn, args, 0, 0)

        # cat and split dims are different
        def fn(a, b, c):
            cat = torch.ops.aten.cat.default([a, b, c], 1)
            split_with_sizes = torch.ops.aten.split_with_sizes.default(
                cat, [2, 3, 5], 0
            )
            return [s**2 for s in split_with_sizes]

        args = [
            torch.randn(10, 2, device="cuda"),
            torch.randn(10, 3, device="cuda"),
            torch.randn(10, 5, device="cuda"),
        ]
        self.common(fn, args, 0, 0)

        # cat and split lenghts are different
        def fn(a, b, c):
            cat = torch.ops.aten.cat.default([a, b, c], 1)
            split_with_sizes = torch.ops.aten.split_with_sizes.default(cat, [5, 5], 1)
            return [s**2 for s in split_with_sizes]

        args = [
            torch.randn(2, 2, device="cuda"),
            torch.randn(2, 3, device="cuda"),
            torch.randn(2, 5, device="cuda"),
        ]
        self.common(fn, args, 0, 0)

        # cat input sizes and split sizes are different
        def fn(a, b, c):
            cat = torch.ops.aten.cat.default([a, b, c], 1)
            split_with_sizes = torch.ops.aten.split_with_sizes.default(
                cat, [2, 5, 3], 1
            )
            return [s**2 for s in split_with_sizes]

        args = [
            torch.randn(2, 2, device="cuda"),
            torch.randn(2, 3, device="cuda"),
            torch.randn(2, 5, device="cuda"),
        ]
        self.common(fn, args, 0, 0)

    def test_symint_pattern_matching(self):
        import torch._inductor.config as config
        from torch._inductor.pattern_matcher import (
            fwd_only,
            PatternMatcherPass,
            register_replacement,
        )

        saved_graph = None

        class _CustomPass(PatternMatcherPass):
            def __init__(self):
                super().__init__()

            def __call__(self, g: torch.fx.graph.Graph):
                self.apply(g)
                nonlocal saved_graph
                saved_graph = g

        with config.patch(
            # leave custom pass only in post_grad_passes()
            pattern_matcher=False,
            # define pattern match as custom post grad opt pass
            post_grad_custom_pre_pass=None,
            post_grad_custom_post_pass=_CustomPass(),
        ):

            def add(x, y):
                return x + y

            # testing that
            def sym_minus(x, y):
                return (x - (-y.size(0))) - (y * -1) - y.size(0)

            device = "cpu"
            my_args = [
                torch.empty([8, 1], device=device),
                torch.empty([10], device=device),
            ]

            invoked = False

            def extra_check(match):
                nonlocal invoked
                invoked = True
                return True

            register_replacement(
                add,
                sym_minus,
                my_args,
                fwd_only,
                [config.post_grad_custom_post_pass],
                extra_check=extra_check,
            )

            @torch.compile(dynamic=True)
            def foo(x, y):
                return x + y

            x = torch.rand([8, 1])
            y = torch.rand([10])

            self.assertEqual(foo(x, y), x + y)

            self.assertTrue(invoked)
            # we trace out the y.sym_size in replacement
            FileCheck().check("sym_size_int").check_same("num_users=2").check_same(
                "target=torch.ops.aten.sym_size"
            ).run(str(saved_graph))

    def test_match_with_mutation(self):
        counter = 0
        test_pass = PatternMatcherPass(prevent_match_across_mutations=True)

        @register_graph_pattern(
            CallFunction(
                torch.add, KeywordArg("x"), CallFunction(torch.sin, KeywordArg("x"))
            ),
            pass_dict=test_pass,
        )
        def _test(match, x):
            nonlocal counter
            counter += 1

        def fn0(x, y):
            a = torch.sin(x)
            b = torch.add(x, a)
            return b

        def fn1(x, y):
            a = torch.sin(x)
            x.copy_(y)
            b = torch.add(x, a)
            return b

        def fn2(x, y):
            a = torch.sin(x)
            with torch.no_grad():
                b = torch.add(x, a)
            return b

        def fn3(x, y):
            a = torch.sin(x)
            with torch.autocast("cuda"):
                b = torch.add(x, a)
            return b

        def fn4(x, y):
            a = torch.sin(x)
            torch.manual_seed(1234)
            b = torch.add(x, a)
            return b

        def fn5(x, y):
            a = torch.sin(x)
            torch.add(y, 1, out=x)
            b = torch.add(x, a)
            return b

        args = [
            torch.randn(5, 5, device="cuda"),
            torch.randn(5, 5, device="cuda"),
        ]

        with unittest.mock.patch(
            "torch._inductor.fx_passes.pre_grad.pattern_matcher_passes", [test_pass]
        ):
            for fn in (fn0, fn1, fn2, fn3, fn4, fn5):
                counter = 0
                expected = fn(*copy.deepcopy(args))
                actual = torch.compile(fn)(*copy.deepcopy(args))
                # should not match
                self.assertEqual(counter, int(fn is fn0))
                torch.testing.assert_close(actual, expected)

    def test_remove_pointless_clones(self):
        @torch.compile(fullgraph=True)
        def fn(a, b):
            return torch.mm(a, b).clone()

        result, (code) = run_and_get_code(fn, torch.randn(8, 8), torch.randn(8, 8))
        # clone would create a buf1
        self.assertIn("return (buf0, )", code[0])
        self.assertNotIn("async_compile.cpp", code[0])

    def test_unfuse_bias_addmm(self):
        args = [
            torch.randn(20, device="cuda"),
            torch.randn(10, 15, device="cuda"),
            torch.randn(15, 20, device="cuda"),
        ]

        @torch.compile()
        def fn(inp, a, b):
            return torch.ops.aten.addmm(inp, a, b)

        _, (code) = run_and_get_code(fn, args[0], args[1], args[2])
        FileCheck().check("extern_kernels.addmm(").run(code[0])

        @torch.compile()
        def fn2(inp, a, b):
            return torch.nn.functional.gelu(torch.ops.aten.addmm(inp, a, b))

        _, (code) = run_and_get_code(fn2, args[0], args[1], args[2])
        FileCheck().check_not("extern_kernels.addmm(").run(code[0])

        @torch.compile()
        def fn2(inp, a, b):
            return torch.nn.functional.gelu(
                torch.ops.aten.addmm(inp, a, b).unsqueeze(0)
            )

        # hit the view path
        _, (code) = run_and_get_code(fn2, args[0], args[1], args[2])
        FileCheck().check_not("extern_kernels.addmm(").run(code[0])

    def test_fuse_attention_roundtrip_pattern(self):
        # are we losing anything in serialization
        from torch._inductor.fx_passes.fuse_attention import _get_sfdp_patterns

        global_vals = {
            "aten": torch.ops.aten,
            "prims": torch.ops.prims,
            "torch": torch,
        }

        for name in dir(torch._inductor.pattern_matcher):
            attr = getattr(torch._inductor.pattern_matcher, name)
            if isinstance(attr, type) and issubclass(attr, (PatternExpr, _TargetExpr)):
                global_vals[name] = attr

        with torch._subclasses.FakeTensorMode():
            for _, kwargs in _get_sfdp_patterns():
                gen_kwargs = {
                    key: kwargs[key]
                    for key in (
                        "search_fn",
                        "example_inputs",
                        "trace_fn",
                        "scalar_workaround",
                    )
                }
                pattern = gen_pattern(**gen_kwargs)
                pattern_pp = PatternPrettyPrinter.run(pattern)
                env = global_vals.copy()
                exec(pattern_pp, env)
                pattern_2 = env["output"]
                self.assertEqual(pattern_pp, PatternPrettyPrinter.run(pattern_2))

    def test_fuse_attention_all_patterns_serialized(self):
        from torch._inductor.fx_passes.fuse_attention import _get_sfdp_patterns

        with torch._subclasses.FakeTensorMode():
            for key, kwargs in _get_sfdp_patterns():
                gen_kwargs = {
                    key: kwargs[key]
                    for key in (
                        "search_fn",
                        "example_inputs",
                        "trace_fn",
                        "scalar_workaround",
                    )
                }
                pattern = gen_pattern(**gen_kwargs)
                pattern_pp = PatternPrettyPrinter.run(pattern)

                search_fn_pattern = get_serialized_pattern(key)
                if search_fn_pattern is None:
                    continue

                self.assertEqual(
                    pattern_pp,
                    PatternPrettyPrinter.run(search_fn_pattern),
                    msg=f"Found mismatched pattern {key}. Run gen_attention_patterns.py",
                )

    def test_match_equivalent_function_invocations1(self):
        counter = 0
        test_pass = PatternMatcherPass(prevent_match_across_mutations=True)

        args = [
            torch.randn(20, device="cuda"),
            torch.randn(10, 15, device="cuda"),
            torch.randn(15, 20, device="cuda"),
        ]

        def f0(inp, a, b):
            return torch.ops.aten.addmm(inp, a, b)

        def f1(inp, a, b):
            return torch.ops.aten.addmm(inp, a, b, beta=1.0)

        def f2(inp, a, b):
            return torch.ops.aten.addmm(inp, a, b, beta=1.0, alpha=1.0)

        # This graph pattern should successfully match all of the above functions
        @register_graph_pattern(
            CallFunction(
                torch.ops.aten.addmm,
                Arg(),
                Arg(),
                Arg(),
                beta=KeywordArg("beta"),
                alpha=KeywordArg("alpha"),
            ),
            pass_dict=test_pass,
        )
        def addmm_replacement(match: Match, inp, mat1, mat2, beta, alpha):
            nonlocal counter
            counter += 1

            def repl(inp, x1, x2):
                return (x1 @ x2) * alpha + inp * beta

            with V.fake_mode:
                match.replace_by_example(repl, [inp, mat1, mat2])

        with unittest.mock.patch(
            "torch._inductor.fx_passes.post_grad.pass_patterns",
            torch._inductor.fx_passes.post_grad.pass_patterns + [test_pass],
        ):
            for fn in (f0, f1, f2):
                counter = 0
                expected = fn(*copy.deepcopy(args))
                opt_fn = torch.compile(fn)
                actual, (code) = run_and_get_code(opt_fn, args[0], args[1], args[2])
                # pattern should match
                self.assertEqual(counter, 1)
                torch.testing.assert_close(actual, expected)
                # addmm should be replaced
                FileCheck().check_not("extern_kernels.addmm(").run(code[0])

    def test_match_equivalent_function_invocations2(self):
        counter = 0
        test_pass = PatternMatcherPass(prevent_match_across_mutations=True)

        args = [
            torch.randn(20, device="cuda"),
            torch.randn(10, 15, device="cuda"),
            torch.randn(15, 20, device="cuda"),
        ]

        def f0(inp, a, b):
            return torch.ops.aten.addmm(inp, a, b)

        def f1(inp, a, b):
            return torch.ops.aten.addmm(inp, a, b, beta=1.0)

        def f2(inp, a, b):
            return torch.ops.aten.addmm(inp, a, b, beta=1.0, alpha=1.0)

        # This graph pattern should only match f0
        @register_graph_pattern(
            CallFunction(torch.ops.aten.addmm, Arg(), Arg(), Arg()),
            pass_dict=test_pass,
        )
        def addmm_replacement(match: Match, inp, mat1, mat2):
            nonlocal counter
            counter += 1

            def repl(inp, x1, x2):
                return x1 @ x2 + inp

            with V.fake_mode:
                match.replace_by_example(repl, [inp, mat1, mat2])

        with unittest.mock.patch(
            "torch._inductor.fx_passes.post_grad.pass_patterns",
            torch._inductor.fx_passes.post_grad.pass_patterns + [test_pass],
        ):
            for fn in (f0, f1, f2):
                counter = 0
                expected = fn(*copy.deepcopy(args))
                actual = torch.compile(fn)(*copy.deepcopy(args))
                self.assertEqual(counter, 1)
                torch.testing.assert_close(actual, expected)

    def test_match_equivalent_function_invocations3(self):
        counter = 0
        test_pass = PatternMatcherPass(prevent_match_across_mutations=True)

        args = [
            torch.randn(20, device="cuda"),
            torch.randn(10, 15, device="cuda"),
            torch.randn(15, 20, device="cuda"),
        ]

        def f0(inp, a, b):
            return torch.ops.aten.addmm(inp, a, b)

        def f1(inp, a, b):
            return torch.ops.aten.addmm(inp, a, b, beta=1.0)

        def f2(inp, a, b):
            return torch.ops.aten.addmm(inp, a, b, beta=1.0, alpha=1.0)

        # This graph pattern should only match f1
        @register_graph_pattern(
            CallFunction(
                torch.ops.aten.addmm, Arg(), Arg(), Arg(), beta=KeywordArg("beta")
            ),
            pass_dict=test_pass,
        )
        def addmm_replacement(match: Match, inp, mat1, mat2, beta):
            nonlocal counter
            counter += 1

            def repl(inp, x1, x2):
                return x1 @ x2 + inp

            with V.fake_mode:
                match.replace_by_example(repl, [inp, mat1, mat2])

        with unittest.mock.patch(
            "torch._inductor.fx_passes.post_grad.pass_patterns",
            torch._inductor.fx_passes.post_grad.pass_patterns + [test_pass],
        ):
            for fn in (f0, f1, f2):
                counter = 0
                expected = fn(*copy.deepcopy(args))
                actual = torch.compile(fn)(*copy.deepcopy(args))
                self.assertEqual(counter, 1)
                torch.testing.assert_close(actual, expected)

    def test_stable_topological_sort(self):
        def fn1(a, b):
            return a + b

        graph = torch.fx.Graph()
        a = graph.placeholder("x")
        b = graph.placeholder("y")
        c = graph.call_function(fn1, (a, b))
        stable_topological_sort(graph)
        self.assertEqual(list(graph.nodes), [a, b, c])

        graph = torch.fx.Graph()
        b = graph.placeholder("y")
        a = graph.placeholder("x")
        c = graph.call_function(fn1, (a, b))
        stable_topological_sort(graph)
        self.assertEqual(list(graph.nodes), [b, a, c])

        graph = torch.fx.Graph()
        a = graph.placeholder("x")
        b = graph.placeholder("y")
        c = graph.call_function(fn1, (b, a))
        c.append(a)
        stable_topological_sort(graph)
        self.assertEqual(list(graph.nodes), [b, a, c])


if __name__ == "__main__":
    if IS_LINUX and HAS_CUDA:
        run_tests()
