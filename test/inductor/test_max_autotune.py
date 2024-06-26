# Owner(s): ["module: inductor"]
import os
import unittest

from typing import Callable, List, Optional

import torch
from torch import multiprocessing as mp
from torch._dynamo import reset
from torch._dynamo.test_case import run_tests, TestCase
from torch._dynamo.testing import reset_rng_state
from torch._dynamo.utils import counters
from torch._inductor import config
from torch._inductor.autotune_process import (
    BenchmarkRequest,
    CUDA_VISIBLE_DEVICES,
    TuningProcessPool,
)
from torch._inductor.graph import GraphLowering
from torch._inductor.ir import Buffer, FixedLayout
from torch._inductor.kernel.mm_plus_mm import aten_mm_plus_mm
from torch._inductor.select_algorithm import (
    AlgorithmSelectorCache,
    ChoiceCaller,
    TritonTemplateCaller,
)

from torch._inductor.utils import run_and_get_code
from torch._inductor.virtualized import V
from torch.fx.experimental.proxy_tensor import make_fx
from torch.testing import FileCheck
from torch.testing._internal.common_cuda import SM75OrLater, SM90OrLater
from torch.testing._internal.common_utils import (
    instantiate_parametrized_tests,
    parametrize,
    skipIfRocm,
)

from torch.testing._internal.inductor_utils import HAS_CPU, HAS_CUDA

torch.set_float32_matmul_precision("high")
if HAS_CUDA:
    torch.cuda.memory._set_allocator_settings("expandable_segments:False")

_CUTLASS_DIR = os.path.join(os.path.dirname(__file__), "../../third_party/cutlass/")


def _get_path_without_sccache() -> str:
    """
    Get the PATH environment variable without sccache.
    """
    path_envs = os.environ.get("PATH", "").split(":")
    path_envs = [env for env in path_envs if "/opt/cache/bin" not in env]
    return ":".join(path_envs)


def benchmark_choice(choice, args, out, expected_out, timings):
    result = choice.benchmark(*args, out=out)
    if expected_out is not None:
        torch.testing.assert_close(out, expected_out)

    timings.copy_(torch.tensor(result))


class FailChoiceCaller(ChoiceCaller):
    def benchmark(self, *args, out):
        raise RuntimeError("This choice caller will always throw")


@instantiate_parametrized_tests
class TestMaxAutotune(TestCase):
    def _create_buffer(self, name, shape):
        return Buffer(name, FixedLayout(torch.device("cuda:0"), torch.float32, shape))

    def test_benchmark_choice_in_subproc(self):
        gm = make_fx(
            lambda: torch.zeros(2, 3)
        )()  # a dummy graph to construct the GraphLowering
        graph = GraphLowering(gm)

        # the graph handler is neede to create benchmark example value below
        with V.set_graph_handler(graph):
            buf1 = self._create_buffer("mat1", (2, 3))
            buf2 = self._create_buffer("mat2", (3, 2))
            buf3 = self._create_buffer("mat3", (2, 3))
            buf4 = self._create_buffer("mat4", (3, 2))

            layout = FixedLayout(torch.device("cuda:0"), torch.float32, (2, 2))

            mat1 = AlgorithmSelectorCache.benchmark_example_value(buf1)
            mat2 = AlgorithmSelectorCache.benchmark_example_value(buf2)
            mat3 = AlgorithmSelectorCache.benchmark_example_value(buf3)
            mat4 = AlgorithmSelectorCache.benchmark_example_value(buf4)

            out = AlgorithmSelectorCache.benchmark_example_value(layout)
            # expected_out = (mat1 @ mat2) + (mat3 @ mat4)
            expected_out = None

            choice = aten_mm_plus_mm.bind((buf1, buf2, buf3, buf4), layout)
            # use a tensor since the mutation to a python list in a sub process
            # is not synced back to the parent process
            timings = torch.zeros(3, dtype=torch.float32)
            ctx = mp.get_context("spawn")
            child = ctx.Process(
                target=benchmark_choice,
                args=(choice, (mat1, mat2, mat3, mat4), out, expected_out, timings),
            )
            child.start()
            child.join()
            self.assertEqual(0, child.exitcode)
            print(f"timings is {timings}, out {out}, expected_out {expected_out}")

    def test_benchmark_choice_fail_in_subproc(self):
        gm = make_fx(
            lambda: torch.zeros(2, 3)
        )()  # a dummy graph to construct the GraphLowering
        graph = GraphLowering(gm)

        # the graph handler is neede to create benchmark example value below
        with V.set_graph_handler(graph):
            buf1 = self._create_buffer("mat1", (2, 3))
            buf2 = self._create_buffer("mat2", (3, 2))
            buf3 = self._create_buffer("mat3", (2, 3))
            buf4 = self._create_buffer("mat4", (3, 2))

            layout = FixedLayout(torch.device("cuda:0"), torch.float32, (2, 2))

            mat1 = AlgorithmSelectorCache.benchmark_example_value(buf1)
            mat2 = AlgorithmSelectorCache.benchmark_example_value(buf2)
            mat3 = AlgorithmSelectorCache.benchmark_example_value(buf3)
            mat4 = AlgorithmSelectorCache.benchmark_example_value(buf4)

            out = AlgorithmSelectorCache.benchmark_example_value(layout)
            expected_out = (mat1 @ mat2) + (mat3 @ mat4)

            choice = FailChoiceCaller("fail_choice_caller", [], None)

            # use a tensor since python list is not synced back
            timings = torch.zeros(3, dtype=torch.float32)
            ctx = mp.get_context("spawn")
            child = ctx.Process(
                target=benchmark_choice,
                args=(choice, (mat1, mat2, mat3, mat4), out, expected_out, timings),
            )
            child.start()
            child.join()
            self.assertNotEqual(0, child.exitcode)

    @parametrize("autotune_in_subproc", (True, False))
    @parametrize("autotune_multi_device", (True, False))
    def test_max_autotune_mm_plus_mm(self, autotune_in_subproc, autotune_multi_device):
        """
        This crash previously due to a triton issue: https://github.com/openai/triton/issues/1298 .
        With autotuning in subprocess, we don't crash anymore.
        """
        m, n, k = 2048, 1536, 64

        def mm_plus_mm(a, b, c, d):
            return a @ b + c @ d

        a = torch.randn(m, k).cuda()
        b = torch.randn(k, n).cuda()
        c = torch.randn(m, k).cuda()
        d = torch.randn(k, n).cuda()

        with config.patch(
            {
                "max_autotune": True,
                "autotune_in_subproc": autotune_in_subproc,
                "autotune_multi_device": autotune_multi_device,
            }
        ):
            torch.compile(mm_plus_mm)(a, b, c, d)

    @parametrize("dynamic", (False, True))
    def test_max_autotune_mm_plus_mm_zero_size_input(self, dynamic):
        """
        Make sure autotuning mm_plus_mm with zero-size input works without crashes.
        """
        m, n, k = 0, 1536, 64

        def mm_plus_mm(a, b, c, d):
            return a @ b + c @ d

        a = torch.randn(m, k).cuda()
        b = torch.randn(k, n).cuda()
        c = torch.randn(m, k).cuda()
        d = torch.randn(k, n).cuda()

        with config.patch({"max_autotune": True}):
            torch.compile(mm_plus_mm, dynamic=dynamic)(a, b, c, d)

    @parametrize("dynamic", (False, True))
    def test_max_autotune_regular_mm(self, dynamic: bool):
        """
        Make sure autotuning mm in sub processes work without crashes.
        """

        def mm(a, b):
            a = torch.sin(a)
            return a @ b

        a = torch.randn(100, 10).cuda()
        b = torch.randn(10, 100).cuda()

        with config.patch({"max_autotune": True, "autotune_in_subproc": True}):
            torch.compile(mm, dynamic=dynamic)(a, b)

    @parametrize("dynamic", (False, True))
    def test_max_autotune_regular_mm_zero_size_input(self, dynamic: bool):
        """
        Make sure autotuning mm with zero-size input works without crashes.
        """

        def mm(a, b):
            a = torch.sin(a)
            return a @ b

        a = torch.randn(0, 10).cuda()
        b = torch.randn(10, 100).cuda()

        with config.patch({"max_autotune": True}):
            torch.compile(mm, dynamic=dynamic)(a, b)

    @skipIfRocm
    @parametrize("dynamic", (False, True))
    def test_max_autotune_remote_caching(self, dynamic: bool):
        from unittest.mock import patch

        def mm(a, b):
            a = torch.sin(a)
            return a @ b

        a = torch.randn(100, 10).cuda()
        b = torch.randn(10, 100).cuda()

        class Model(torch.nn.Module):
            def forward(self, x, y):
                return x + y

        def f(x, y):
            return Model()(x, y)

        x = torch.randn(100, 100).cuda()
        y = torch.randn(100, 100).cuda()

        cache = {}
        num_get = 0
        num_put = 0

        class MyCache:
            def __init__(self, key, is_autotune=False):
                pass

            def get(self, filenames):
                nonlocal cache
                nonlocal num_get
                ret = {file: cache[file] for file in filenames if file in cache}
                num_get += len(ret)
                return ret

            def put(self, filename, data):
                nonlocal cache
                nonlocal num_put
                cache[filename] = data
                num_put += 1

        cache_module = (
            "triton.runtime.fb_memcache.FbMemcacheRemoteCacheBackend"
            if config.is_fbcode()
            else "triton.runtime.cache.RedisRemoteCacheBackend"
        )

        with config.patch(
            {
                "use_autotune_local_cache": False,
                "use_autotune_remote_cache": True,
            }
        ), patch.dict(os.environ), patch(cache_module, MyCache, create=True):
            os.environ.pop("TRITON_CACHE_MANAGER", None)
            with config.patch({"max_autotune": True}):
                for _ in range(4):
                    torch.compile(mm, dynamic=dynamic)(a, b)
                    reset()
                    torch._inductor.codecache.PyCodeCache.clear()
                self.assertEqual(num_get, 3)
                self.assertEqual(num_put, 1)
            num_get = 0
            num_put = 0
            for _ in range(4):
                torch.compile(f, dynamic=dynamic)(x, y)
                reset()
                torch._inductor.codecache.PyCodeCache.clear()
            self.assertEqual(num_get, 3)
            self.assertEqual(num_put, 1)

    def test_precompilation_threads(self):
        import threading
        from typing import Any, Dict
        from unittest.mock import Mock, patch

        class FakeChoiceCaller(ChoiceCaller):
            def __init__(self):
                super().__init__("none", [], Mock())
                self.thread_id = None

            def precompile(self):
                self.thread_id = threading.get_ident()

            def call_name(self) -> str:
                return None

            def to_callable(self):
                return None

            def hash_key(self) -> str:
                return None

            def output_node(self) -> "TensorBox":  # noqa: F821
                return None

        fake_choices = [FakeChoiceCaller() for i in range(10)]
        fake_lookup_result = {choice: 0.123 for choice in fake_choices}

        def no_lookup(
            choices: List[ChoiceCaller],
            op: str,
            inputs: str,
            benchmark: Callable[[Any], Dict[ChoiceCaller, float]],
        ) -> Dict[ChoiceCaller, float]:
            return benchmark(choices)

        asc = AlgorithmSelectorCache()

        def fake_benchmark_fn(*args, **kwargs):
            return fake_lookup_result

        main_thread_id = threading.get_ident()
        mock_debug_handler = Mock()
        old_debug_handler = V.debug
        try:
            V.set_debug_handler(mock_debug_handler)
            with patch.object(asc, "lookup", new=no_lookup):
                with patch.object(
                    asc, "make_benchmark_fn", return_value=fake_benchmark_fn
                ):
                    with config.patch(
                        {
                            "autotune_in_subproc": False,
                            "compile_threads": len(fake_choices),
                        }
                    ):
                        asc("test_call", fake_choices, [], Mock())
            for fake_choice in fake_choices:
                assert (
                    fake_choice.thread_id is not None
                ), "Expected all ChoiceCaller's precompile method to have been called"
                assert (
                    fake_choice.thread_id != main_thread_id
                ), "Expected all ChoiceCaller's precompile method to have been called on separate thread"
        finally:
            V.set_debug_handler(old_debug_handler)

    @unittest.skipIf(not SM75OrLater, "need sm_75")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    @unittest.mock.patch.dict(os.environ, {"PATH": _get_path_without_sccache()})
    def test_max_autotune_precompile(self):
        """
        Make sure autotuning mm in sub processes work without crashes.
        """

        if torch.version.hip:
            return

        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False

        def mm(a, b):
            return a @ b

        a = torch.randn(100, 10).cuda().half()
        b = torch.randn(10, 100).cuda().half()

        with config.patch(
            {
                "max_autotune": True,
                "autotune_in_subproc": True,
                "max_autotune_gemm_backends": "CUTLASS,Triton,ATen",
                "compile_threads": 4,
                "cuda.cutlass_dir": _CUTLASS_DIR,
                "cuda.cutlass_max_profiling_configs": 2,
            }
        ):
            Y_compiled = torch.compile(mm, dynamic=False)(a, b)
            Y = mm(a, b)
            torch.testing.assert_close(Y_compiled, Y)

    # TODO: Enable dynamic test cases when dynamic support is added.
    @unittest.skipIf(not SM75OrLater, "need sm_75")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    @parametrize("dynamic", (False,))
    @parametrize("max_autotune_gemm_backends", ("CUTLASS", "ATen,Triton,CUTLASS"))
    @unittest.mock.patch.dict(os.environ, {"PATH": _get_path_without_sccache()})
    def test_max_autotune_cutlass_backend_regular_mm(
        self, dynamic: bool, max_autotune_gemm_backends: str
    ):
        """
        Make sure autotuning mm in sub processes work without crashes.
        """

        if max_autotune_gemm_backends == "CUTLASS" and torch.version.hip:
            return

        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False

        def mm(a, b):
            return a @ b

        a = torch.randn(100, 10).cuda().half()
        b = torch.randn(10, 100).cuda().half()

        with config.patch(
            {
                "max_autotune": True,
                "autotune_in_subproc": False,
                "max_autotune_gemm_backends": max_autotune_gemm_backends,
                "cuda.cutlass_dir": _CUTLASS_DIR,
                "cuda.cutlass_max_profiling_configs": 2,
            }
        ):
            Y_compiled = torch.compile(mm, dynamic=dynamic)(a, b)
            Y = mm(a, b)
            torch.testing.assert_close(Y_compiled, Y)

    def _test_max_autotune_cutlass_backend_epilogue_fusion(
        self,
        dynamic: bool = False,
        max_autotune_gemm_backends: str = "CUTLASS",
        mixed_precision=False,
        fp16=True,
        expected_fuse_count=1,
        mm: Callable[[torch.Tensor, torch.Tensor], torch.Tensor] = None,
    ):
        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = (
            mixed_precision
        )

        # Note: The ops that are available
        # also depend on the alignment of the shapes
        # so if these shapes don't all align to at least 8 elements
        # it can happen that no Cutlass 3.x op is available
        # that allows fusions
        a = torch.randn(256, 32).cuda()
        b = torch.randn(32, 256).cuda()
        if fp16:
            a = a.half()
            b = b.half()

        with config.patch(
            {
                "max_autotune": True,
                "autotune_in_subproc": False,
                "max_autotune_gemm_backends": max_autotune_gemm_backends,
                "cuda.cutlass_dir": _CUTLASS_DIR,
                "cuda.cutlass_max_profiling_configs": 4,
                "cuda.cutlass_only_evt_capable_ops": True,
                "cuda.version": "12.2",  # required to enable the Kernels we need
            }
        ):
            counters["inductor"]["cuda_epilogue_fusion_counter"] = 0
            Y_compiled = torch.compile(mm, dynamic=dynamic)(a, b)
            Y = mm(a, b)
            actual_count = counters["inductor"]["cuda_epilogue_fusion_counter"]
            assert (
                actual_count == expected_fuse_count
            ), f"Expected fuse count of {expected_fuse_count} but got {actual_count}"
            torch.testing.assert_close(Y_compiled, Y, atol=1e-2, rtol=1e-2)

    @unittest.skipIf(not SM90OrLater, "need sm_90")
    @unittest.skipIf(torch.version.hip, "HIP not supported")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    def test_max_autotune_cutlass_backend_simple_fusion_fp16(self):
        def mm(a, b):
            return (a @ b) * 3.0

        #  The pointwise ops seem to be pre-fused into a single Pointwise
        self._test_max_autotune_cutlass_backend_epilogue_fusion(
            mixed_precision=False, fp16=True, expected_fuse_count=1, mm=mm
        )

    @unittest.skipIf(not SM90OrLater, "need sm_90")
    @unittest.skipIf(torch.version.hip, "HIP not supported")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    def test_max_autotune_cutlass_backend_simple_fusion_fp16_fp32acc(self):
        def mm(a, b):
            return (a @ b) * 3.0

        self._test_max_autotune_cutlass_backend_epilogue_fusion(
            mixed_precision=True, fp16=True, expected_fuse_count=1, mm=mm
        )

    @unittest.skipIf(not SM90OrLater, "need sm_90")
    @unittest.skipIf(torch.version.hip, "HIP not supported")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    def test_max_autotune_cutlass_backend_chained_fusion_fp16(self):
        def mm(a, b):
            return (a @ b) * 3.3 - 1.234

        #  The pointwise ops seem to be pre-fused into a single Pointwise
        self._test_max_autotune_cutlass_backend_epilogue_fusion(
            mixed_precision=False, fp16=True, expected_fuse_count=1, mm=mm
        )

    @unittest.skipIf(not SM90OrLater, "need sm_90")
    @unittest.skipIf(torch.version.hip, "HIP not supported")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    def test_max_autotune_cutlass_backend_chained_fusion_fp16_fp32acc(self):
        def mm(a, b):
            return (a @ b) * 3.3 - 1.234

        self._test_max_autotune_cutlass_backend_epilogue_fusion(
            mixed_precision=True, fp16=True, expected_fuse_count=1, mm=mm
        )

    @unittest.skipIf(not SM90OrLater, "need sm_90")
    @unittest.skipIf(torch.version.hip, "HIP not supported")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    def test_max_autotune_cutlass_backend_relu_fusion_fp16(self):
        def mm(a, b):
            return torch.nn.functional.relu((a @ b) * 3.3 - 1.234)

        self._test_max_autotune_cutlass_backend_epilogue_fusion(
            mixed_precision=False, fp16=True, expected_fuse_count=1, mm=mm
        )

    @unittest.skipIf(not SM90OrLater, "need sm_90")
    @unittest.skipIf(torch.version.hip, "HIP not supported")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    def test_max_autotune_cutlass_backend_relu_fusion_fp16_fp32acc(self):
        def mm(a, b):
            return torch.nn.functional.relu((a @ b) * 3.3 - 1.234)

        #  The pointwise ops seem to be pre-fused into a single Pointwise
        self._test_max_autotune_cutlass_backend_epilogue_fusion(
            mixed_precision=True, fp16=True, expected_fuse_count=1, mm=mm
        )

    @unittest.skipIf(not SM90OrLater, "need sm_90")
    @unittest.skipIf(torch.version.hip, "HIP not supported")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    def test_max_autotune_cutlass_backend_relu6_fusion_fp16_fp32acc(self):
        def mm(a, b):
            return torch.clamp(torch.nn.functional.relu(a @ b), max=6.0)

        #  The pointwise ops seem to be pre-fused into a single Pointwise
        self._test_max_autotune_cutlass_backend_epilogue_fusion(
            mixed_precision=True, fp16=True, expected_fuse_count=1, mm=mm
        )

    @unittest.skipIf(not SM90OrLater, "need sm_90")
    @unittest.skipIf(torch.version.hip, "HIP not supported")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    def test_max_autotune_cutlass_backend_no_fusion_dtype_mismatch(self):
        def mm(a, b):
            # this should not be fused, since the output dtype is different from the matmul dtype
            return (a @ b).to(torch.float32) * 0.00001

        self._test_max_autotune_cutlass_backend_epilogue_fusion(
            mixed_precision=True, fp16=True, expected_fuse_count=0, mm=mm
        )

    @unittest.skipIf(not SM90OrLater, "need sm_90")
    @unittest.skipIf(torch.version.hip, "HIP not supported")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    def test_max_autotune_cutlass_backend_shape_dependent_normalization_fusion(self):
        def mm(a, b):
            return (a @ b) / b.size(1)

        self._test_max_autotune_cutlass_backend_epilogue_fusion(
            mixed_precision=True, fp16=True, expected_fuse_count=1, mm=mm
        )

    # TODO: Enable dynamic test cases when dynamic support is added.
    @unittest.skipIf(not SM75OrLater, "need sm_75")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    @parametrize("dynamic", (False,))
    @parametrize("max_autotune_gemm_backends", ("CUTLASS", "ATen,Triton,CUTLASS"))
    @unittest.mock.patch.dict(os.environ, {"PATH": _get_path_without_sccache()})
    def test_max_autotune_cutlass_backend_mm_bias(
        self, dynamic: bool = False, max_autotune_gemm_backends: str = "CUTLASS"
    ):
        """
        Make sure autotuning mm in sub processes work without crashes.
        """

        if max_autotune_gemm_backends == "CUTLASS" and torch.version.hip:
            return

        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False

        def mm(a, b, bias):
            return torch.nn.functional.linear(a, b, bias)

        a = torch.randn(2048, 4096).cuda().half()
        bias = torch.randn(2048).cuda().half()

        with config.patch(
            {
                "max_autotune": True,
                "autotune_in_subproc": False,
                "max_autotune_gemm_backends": max_autotune_gemm_backends,
                "cuda.cutlass_dir": _CUTLASS_DIR,
                "cuda.cutlass_max_profiling_configs": 2,
            }
        ):
            Y = mm(a, a, bias)
            Y_compiled = torch.compile(mm, dynamic=dynamic)(a, a, bias)
            torch.testing.assert_close(Y_compiled, Y, atol=1e-1, rtol=1e-1)

    @parametrize("dynamic", (False, True))
    def test_max_autotune_addmm(self, dynamic=False):
        """
        Make sure autotuning addmm in sub processes work without crashes.
        """

        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False

        def addmm(x, a, b):
            return torch.addmm(x, a, b)

        x = torch.randn(100).cuda()
        a = torch.randn(100, 10).cuda()
        b = torch.randn(10, 100).cuda()
        with config.patch({"max_autotune": True, "autotune_in_subproc": True}):
            Y_compiled = torch.compile(addmm, dynamic=dynamic)(x, a, b)
            Y = addmm(x, a, b)
            torch.testing.assert_close(Y_compiled, Y, atol=1e-2, rtol=1e-2)

    @parametrize("dynamic", (False, True))
    def test_max_autotune_addmm_zero_size_input(self, dynamic):
        """
        Make sure autotuning addmm with zero-size input works without crashes.
        """

        def addmm(x, a, b):
            return torch.addmm(x, a, b)

        x = torch.randn(100).cuda()
        a = torch.randn(0, 10).cuda()
        b = torch.randn(10, 100).cuda()
        with config.patch({"max_autotune": True}):
            torch.compile(addmm, dynamic=dynamic)(x, a, b)

    # TODO: Enable dynamic test cases when dynamic support is added.
    @unittest.skipIf(not SM75OrLater, "need sm_75")
    @unittest.skipIf(config.is_fbcode(), "fbcode requires different CUTLASS path setup")
    @parametrize("dynamic", (False,))
    @parametrize("max_autotune_gemm_backends", ("CUTLASS", "ATen,Triton,CUTLASS"))
    @unittest.mock.patch.dict(os.environ, {"PATH": _get_path_without_sccache()})
    def test_max_autotune_cutlass_backend_addmm(
        self, dynamic, max_autotune_gemm_backends
    ):
        """
        Make sure autotuning addmm in sub processes work without crashes.
        """

        if max_autotune_gemm_backends == "CUTLASS" and torch.version.hip:
            return

        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False

        def addmm(x, a, b, alpha, beta):
            return torch.addmm(x, a, b, alpha=alpha, beta=beta)

        def compare_results(
            m: int, k: int, n: int, alpha: float, beta: float, x_shape: List[int]
        ) -> None:
            x = torch.randn(x_shape).cuda().half()
            a = torch.randn(m, k).cuda().half()
            b = torch.randn(k, n).cuda().half()
            y_expected = addmm(x, a, b, alpha, beta)

            compiled_fn = torch.compile(addmm, dynamic=dynamic)
            y = compiled_fn(x, a, b, alpha, beta)
            torch.testing.assert_close(y, y_expected)

        with config.patch(
            {
                "max_autotune": True,
                "autotune_in_subproc": False,
                "max_autotune_gemm_backends": max_autotune_gemm_backends,
                "cuda.cutlass_dir": _CUTLASS_DIR,
                "cuda.cutlass_max_profiling_configs": 2,
            }
        ):
            # No broadcast
            compare_results(4096, 25728, 2048, 2.0, 0.4, [4096, 2048])
            # Broadcast first dim.
            compare_results(4096, 25728, 2048, 2.0, 0.4, [2048])
            # Broadcast last dim.
            if not SM90OrLater and max_autotune_gemm_backends == "CUTLASS":
                with self.assertRaisesRegex(RuntimeError, "No choices to select"):
                    # CUTLASS2 doesn't support Bias last-dim broadcast.
                    compare_results(4096, 25728, 2048, 2.0, 0.4, [4096, 1])
            else:
                compare_results(4096, 25728, 2048, 2.0, 0.4, [4096, 1])

    @skipIfRocm
    def test_autotune_conv1x1(self):
        # Assuming input has 3 channels and we want to produce 16 channels as output
        conv1x1 = (
            torch.nn.Conv2d(in_channels=3, out_channels=16, kernel_size=1)
            .to(memory_format=torch.channels_last)
            .cuda()
        )

        # Example input tensor: batch size = 4, channels = 3, height = 32, width = 32
        # The memory format is set to `channels_last`
        input_tensor = (
            torch.randn(4, 3, 32, 32)
            .contiguous(memory_format=torch.channels_last)
            .cuda()
        )

        with config.patch(
            {"max_autotune": True, "max_autotune_gemm_backends": "TRITON"}
        ):

            @torch.compile()
            def foo(mod, x):
                return mod(x)

            with torch.no_grad():
                out, code = run_and_get_code(foo, conv1x1, input_tensor)

            FileCheck().check_not("extern_kernels.convolution").run(code[0])
            self.assertEqual(conv1x1(input_tensor), out, atol=1e-2, rtol=0)

    def test_cat_addmm(self):
        def fn(a: torch.Tensor, b: torch.Tensor, c: torch.Tensor):
            return torch.cat(
                [
                    torch.addmm(a, b, c),
                    torch.addmm(b, c, a),
                ],
                1,
            )

        args = [
            torch.randn(4, 4, device="cuda"),
            torch.randn(4, 4, device="cuda"),
            torch.randn(4, 4, device="cuda"),
        ]
        with config.patch(
            {
                "max_autotune": True,
                "max_autotune_gemm_backends": "Triton",
            }
        ):
            expected = fn(*args)
            actual = torch.compile(fn)(*args)
            torch.testing.assert_close(actual, expected, atol=1e-2, rtol=1e-2)

    def test_triton_template_with_epilogues_and_dynamic_shape(self):
        def fn(
            x: torch.Tensor, w: torch.Tensor, bias: torch.Tensor, mul: torch.Tensor
        ) -> torch.Tensor:
            return (
                torch.nn.functional.relu(
                    torch.matmul(torch.transpose(x, 0, 1), torch.transpose(w, 0, 1))
                    + bias
                )
                * mul
            )

        M0 = 5
        M1 = 8
        K = 4
        N = 3
        w = torch.rand(N, K).cuda().half()
        b = torch.rand(N).cuda().half()

        with config.patch(
            {
                "max_autotune": True,
                "autotune_in_subproc": True,
                "max_autotune_gemm_backends": "Triton",
            }
        ):
            compiled_fn = torch.compile(
                fn, fullgraph=True, dynamic=True, mode="max-autotune-no-cudagraphs"
            )

            x0 = torch.rand(K, M0).cuda().half()
            mul0 = torch.rand(M0, N).cuda().half()
            y0 = compiled_fn(x0, w, b, mul0)
            y0_expected = fn(x0, w, b, mul0)
            torch.testing.assert_close(y0, y0_expected)

            x1 = torch.rand(K, M1).cuda().half()
            mul1 = torch.rand(M1, N).cuda().half()
            y1 = compiled_fn(x1, w, b, mul1)
            y1_expected = fn(x1, w, b, mul1)
            torch.testing.assert_close(y1, y1_expected)

    @config.patch(
        benchmark_kernel=True,
        fallback_random=True,
        max_autotune_gemm=True,
    )
    @parametrize("device", ("cpu", "cuda"))
    def test_matmul_dropout(self, device):
        def fwd(a, b):
            x = a @ b
            x = torch.nn.functional.dropout(x, 0.1)
            return x

        def fn(a, b):
            x = fwd(a, b).sum()
            x.backward()
            return a.grad

        N = 128
        a = torch.randn(N, N, device=device, requires_grad=True)
        b = torch.randn(N, N, device=device)

        opt_fn = torch.compile(fn)
        reset_rng_state()
        ref = fn(a, b)
        reset_rng_state()
        act = opt_fn(a, b)

        if N <= 8:
            print(f"ref\n{ref}\nact\n{act}")
        torch.testing.assert_close(ref, act, atol=1e-1, rtol=1e-1)


class TestBenchmarkRequest(BenchmarkRequest):
    def __init__(
        self, value: float, multi_device: bool, parent_visible_devices: Optional[str]
    ) -> None:
        self.value = value
        self.multi_device = multi_device
        self.parent_visible_devices = parent_visible_devices

    def benchmark(
        self, *input_tensors: torch.Tensor, output_tensor: Optional[torch.Tensor] = None
    ) -> float:
        # Verify that the visible devices env var is set correctly. If multi-device
        # auto-tuning is disabled, the visible devices should be unmanipulated from
        # the parent process. If multi-device auto-tuning is enabled, the visible
        # devices should be a _single_ valid device number. Note that we can't perform
        # this validation directly from the test body because benchmarks execute in a
        # separate process. If the check fails, however, the test will detect the
        # failure by virtue of not receiving the expected result back.
        visible_devices = os.environ.get(CUDA_VISIBLE_DEVICES)
        if not self.multi_device:
            assert visible_devices == self.parent_visible_devices
        else:
            valid_devices = self.parent_visible_devices.split(",")
            assert visible_devices in valid_devices

        return self.value


class TestTritonTemplateCaller(TritonTemplateCaller):
    def __init__(self, bmreq: TestBenchmarkRequest):
        self.bmreq = bmreq

    def __str__(self) -> str:
        return "test"


class TestTuningProcess(TestCase):
    def test_tuning_pool_crash(self):
        # Use only one device/subprocess so we test the process restarts
        # and is usable after a "crash".
        with config.patch({"autotune_multi_device": False}):
            tuning_pool = TuningProcessPool()
            tuning_pool.initialize()

            # First force the tuning process to "crash" by setting a bogus
            # string for the expected visible devices.
            bmreq = TestBenchmarkRequest(3.14, False, "invalid")
            choice = TestTritonTemplateCaller(bmreq)

            timings = tuning_pool.benchmark([choice])
            self.assertTrue(choice in timings)
            self.assertEqual(timings[choice], float("inf"))

            # Then send another request and make sure the sub-process
            # has restarted and is operational. 'valid_devices' expected
            # to be None because autotune_multi_device is off.
            choice.bmreq.parent_visible_devices = os.environ.get(CUDA_VISIBLE_DEVICES)

            timings = tuning_pool.benchmark([choice])
            self.assertTrue(choice in timings)
            self.assertEqual(timings[choice], bmreq.value)

            tuning_pool.terminate()

    def test_tuning_pool_multiple_devices(self):
        with config.patch({"autotune_multi_device": True}):
            # Adapt the test to the available devices (and whether CUDA_VISIBLE_DEVICES
            # is already set in the environment); use a subset of the available devices
            # to ensure only the subset are visible to the sub-processes.
            if CUDA_VISIBLE_DEVICES in os.environ:
                visible_devices = os.environ[CUDA_VISIBLE_DEVICES].split(",")
            else:
                visible_devices = [str(d) for d in range(torch.cuda.device_count())]

            parent_visible_devices = ",".join(visible_devices[-2:])
            os.environ[CUDA_VISIBLE_DEVICES] = parent_visible_devices

            tuning_pool = TuningProcessPool()
            tuning_pool.initialize()

            choice1 = TestTritonTemplateCaller(
                TestBenchmarkRequest(3.14, True, parent_visible_devices),
            )
            choice2 = TestTritonTemplateCaller(
                TestBenchmarkRequest(2.718, True, parent_visible_devices),
            )

            timings = tuning_pool.benchmark([choice1, choice2])
            self.assertEqual(timings[choice1], choice1.bmreq.value)
            self.assertEqual(timings[choice2], choice2.bmreq.value)

            tuning_pool.terminate()


if __name__ == "__main__":
    from torch._inductor.utils import is_big_gpu

    # Set env to make it work in CI.
    if HAS_CUDA and HAS_CPU and is_big_gpu(0):
        run_tests()
