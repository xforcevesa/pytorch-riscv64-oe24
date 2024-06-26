# Owner(s): ["module: inductor"]

import logging
import unittest

import torch
import torch._inductor
from torch._dynamo.test_case import run_tests, TestCase
from torch._dynamo.utils import counters

from torch.testing._internal.common_utils import (
    instantiate_parametrized_tests,
    parametrize,
)
from torch.testing._internal.inductor_utils import HAS_CUDA

requires_cuda = unittest.skipUnless(HAS_CUDA, "requires cuda")


class MyModule(torch.nn.Module):
    def __init__(
        self, n_input: int, n_output: int, has_bias: bool, device="cuda"
    ) -> None:
        super().__init__()
        self.linear = torch.nn.Linear(n_input, n_output, bias=has_bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.linear(x)


class MyModule2(torch.nn.Module):
    def __init__(self):
        super().__init__()

    def forward(self, input1, input2):
        output = torch.bmm(input1, input2)
        return output


class MyModule3(torch.nn.Module):
    def __init__(self):
        super().__init__()

    def forward(self, input1, input2):
        output = torch.mm(input1, input2)
        return output


@requires_cuda
@torch._inductor.config.patch(
    decompose_mem_bound_mm=True,
)
@instantiate_parametrized_tests
class TestDecomposeMemMM(TestCase):
    def compare_dict_tensors(self, ref_dict, res_dict, rtol=1e-3, atol=1e-3):
        if len(set(ref_dict.keys())) != len(set(res_dict.keys())):
            return False
        for key1 in ref_dict.keys():
            key2 = "_orig_mod." + key1
            assert key2 in res_dict, f"{key1} does not exist in traced module"
            if not torch.allclose(ref_dict[key1], res_dict[key2], rtol=rtol, atol=atol):
                return False
        return True

    def compare_pred(self, module, traced, input, rtol=1e-3, atol=1e-3):
        ref = module(*input)
        res = traced(*input)
        self.assertEqual(ref, res, rtol=rtol, atol=atol)

    def compare_parameters(self, module, traced, rtol=1e-3, atol=1e-3):
        ref_params = dict(module.named_parameters())
        res_params = dict(traced.named_parameters())
        self.assertTrue(self.compare_dict_tensors(ref_params, res_params, rtol, atol))

    def compare_gradients(self, module, traced, rtol=1e-3, atol=1e-3):
        ref_grad = {key: param.grad for key, param in module.named_parameters()}
        res_grad = {key: param.grad for key, param in traced.named_parameters()}
        self.assertTrue(
            self.compare_dict_tensors(ref_grad, res_grad, rtol=rtol, atol=atol)
        )

    @parametrize(
        "b,m,k,n,should_decompose",
        [(10240, 2, 2, 2, True), (10240, 2, 32, 32, False), (2000, 2, 2, 2, False)],
    )
    def test_decompose_bmm(self, b, m, n, k, should_decompose):
        torch._logging.set_logs(inductor=logging.DEBUG)
        mat1 = torch.randn(b, m, k, device="cuda").requires_grad_(True)
        mat2 = torch.randn(b, k, n, device="cuda").requires_grad_(True)

        counters.clear()

        module = MyModule2().to("cuda")
        traced = torch.compile(module)
        input = [mat1, mat2]
        ref = module(*input)
        res = traced(*input)

        self.compare_pred(module, traced, input)

        expected_val = 1 if should_decompose else 0
        self.assertEqual(
            counters["inductor"]["decompose_bmm"],
            expected_val,
        )

        ref.sum().backward()
        res.sum().backward()
        self.compare_parameters(module, traced)
        self.compare_gradients(module, traced)

        expected_val = 3 if should_decompose else 0
        self.assertEqual(
            counters["inductor"]["decompose_bmm"],
            expected_val,
        )
        counters.clear()

    @parametrize(
        "m,k,n, should_decompose",
        [(20480, 5, 2, True), (20480, 32, 2, False), (2048, 2, 2, False)],
    )
    @parametrize("has_bias", [True, False])
    def test_decompose_linear(self, m, n, k, has_bias, should_decompose):
        torch._logging.set_logs(inductor=logging.DEBUG)
        input = torch.randn(m, k, device="cuda").requires_grad_(True)

        counters.clear()

        module = MyModule(k, n, has_bias).to("cuda")
        traced = torch.compile(module)
        input = [input]
        ref = module(*input)
        res = traced(*input)

        self.compare_pred(module, traced, input)

        expected_val = 1 if should_decompose else 0
        if has_bias:
            self.assertEqual(
                counters["inductor"]["decompose_addmm"],
                expected_val,
            )
        else:
            self.assertEqual(
                counters["inductor"]["decompose_mm"],
                expected_val,
            )
        decompose_mm_fwd = counters["inductor"]["decompose_mm"]

        ref.sum().backward()
        res.sum().backward()

        self.compare_parameters(module, traced)
        self.compare_gradients(module, traced)

        self.assertEqual(
            counters["inductor"]["decompose_mm"] - decompose_mm_fwd,
            expected_val,
        )
        self.assertEqual(
            counters["inductor"]["decompose_mmt"],
            expected_val,
        )
        counters.clear()

    @parametrize(
        "m,k,n, should_decompose",
        [(20480, 5, 2, True), (20480, 32, 2, False), (2048, 2, 2, False)],
    )
    @parametrize("has_bias", [True, False])
    def test_decompose_mm(self, m, n, k, has_bias, should_decompose):
        torch._logging.set_logs(inductor=logging.DEBUG)
        mat1 = torch.randn(m, k, device="cuda").requires_grad_(True)
        mat2 = torch.randn(k, n, device="cuda").requires_grad_(True)

        counters.clear()

        module = MyModule3().to("cuda")
        traced = torch.compile(module)
        input = [mat1, mat2]
        ref = module(*input)
        res = traced(*input)

        self.compare_pred(module, traced, input)

        expected_val = 1 if should_decompose else 0
        self.assertEqual(
            counters["inductor"]["decompose_mm"],
            expected_val,
        )
        decompose_mm_fwd = counters["inductor"]["decompose_mm"]

        ref.sum().backward()
        res.sum().backward()
        self.compare_parameters(module, traced)
        self.compare_gradients(module, traced)

        expected_val = 1 if should_decompose else 0
        self.assertEqual(
            counters["inductor"]["decompose_mm"] - decompose_mm_fwd,
            expected_val,
        )
        self.assertEqual(
            counters["inductor"]["decompose_mm_large_k"],
            expected_val,
        )
        counters.clear()


if __name__ == "__main__":
    run_tests()
