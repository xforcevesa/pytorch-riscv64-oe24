# Owner(s): ["oncall: pt2"]

# Copyright (c) Facebook, Inc. and its affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from typing import Union, Callable, List, Any, Optional, Dict
from unittest.mock import patch
from torch.testing._internal.common_utils import (
    TestCase,
    run_tests,
    IS_ARM64,
    IS_MACOS,
    IS_WINDOWS,
    IS_X86,
    compare_equal_outs_and_grads,
    outs_and_grads,
    skipIfRocm,
)
from torch.testing._internal.two_tensor import TwoTensor, TwoTensorMode
import copy
import torch
import torch._dynamo as torchdynamo
import torch.nn as nn
import torch.utils._pytree as pytree
import unittest
import warnings
import itertools
from contextlib import nullcontext
from functools import partial
from torch.nn.utils.rnn import PackedSequence
from torch.testing._internal.common_device_type import instantiate_device_type_tests, toleranceOverride, tol
from torch.testing._internal.common_methods_invocations import op_db
from torch.testing._internal.common_modules import module_db, modules
from torch.testing._internal.common_utils import parametrize, instantiate_parametrized_tests
from torch.testing._internal.control_flow_opinfo_db import control_flow_opinfo_db
from torch.testing._internal.optests import _test_aot_autograd_forwards_backwards_helper, aot_autograd_check
from torch._higher_order_ops.out_dtype import out_dtype
from functorch import (
    grad, vjp, vmap, jacrev,
    make_fx
)
from torch._functorch.aot_autograd import aot_module_simplified, aot_export_module, aot_export_joint_simple
from functorch.compile import (
    nnc_jit, compiled_function, compiled_module,
    min_cut_rematerialization_partition, aot_function, aot_module,
    nop, default_partition, default_decompositions,
    memory_efficient_fusion, get_aot_compilation_context, make_boxed_compiler
)
from torch._decomp import decomposition_table

from torch.testing._internal.common_device_type import ops
from common_utils import (
    decorate,
    xfail,
    skip,
    skipOps,
    decorateForModules,
)
from torch._subclasses.fake_tensor import DynamicOutputShapeException, FakeTensorMode
from torch.fx.experimental.proxy_tensor import is_sym_node
from torch.fx.experimental.symbolic_shapes import ShapeEnv, GuardOnDataDependentSymNode

USE_TORCHVISION = False
try:
    import torchvision
    USE_TORCHVISION = True
except ImportError:
    warnings.warn("Couldn't import torchvision. Some of our tests use it, try "
                  "to install it with commands from pytorch.org, post-fixed with "
                  "`--no-deps` to avoid overwriting the pytorch installation",
                  UserWarning)

USE_NETWORKX = False
try:
    import networkx  # noqa: F401
    USE_NETWORKX = True
except ImportError:
    warnings.warn("Some tests use networkx but it was not installed",
                  UserWarning)

# NB: numpy is a testing dependency!

class AOTTestCase(TestCase):
    def setUp(self):
        super().setUp()

class TestPythonKey(AOTTestCase):
    def test_make_fx(self, device):
        def f(x):
            return torch.sin(x)
        inp = torch.randn(3)
        fx_f = make_fx(f)(inp)

        new_inp = torch.randn(3)
        self.assertEqual(fx_f(new_inp), f(new_inp))

    def test_make_fx_grad(self, device):
        def f(x):
            return torch.sin(x).sum()
        inp = torch.randn(3)
        f = grad(f)
        fx_f = make_fx(f)(inp)

        new_inp = torch.randn(3)
        self.assertEqual(fx_f(new_inp), f(new_inp))

    def test_scalar_device(self, device):
        def f(a, b):
            return a + b
        inps = [torch.randn(3, device=device), torch.tensor(5)]
        fx_f = make_fx(f)(*inps)
        self.assertEqual(fx_f(*inps), f(*inps))

    def test_make_fx_vmap(self, device):
        def f(x):
            return torch.sin(x)
        inp = torch.randn(5, 3)
        f = vmap(f)
        fx_f = make_fx(f)(inp)
        new_inp = torch.randn(5, 3)
        self.assertEqual(fx_f(new_inp), f(new_inp))

    def test_make_fx_jacrev(self, device):
        def f(x):
            return x.sin().sum()
        inp = torch.randn(3)
        f = jacrev(jacrev(f))
        fx_f = make_fx(f)(inp)
        new_inp = torch.randn(3)
        self.assertEqual(fx_f(new_inp), f(new_inp))

    def test_make_fx_vjp(self, device):
        def f(x):
            return torch.sin(x).sum()

        primals = torch.randn(3)
        _, vjp_fn = vjp(f, primals)
        cotangent = torch.randn(())
        fx_f = make_fx(vjp_fn)(cotangent, True, True)
        new_cotangent = torch.randn(())
        self.assertEqual(fx_f(new_cotangent, True, True), vjp_fn(new_cotangent))

    def test_make_fx_functionalize(self, device):
        from functorch.experimental import functionalize

        def fn(a):
            a = a * 2
            a.relu_()
            return a

        a = torch.randn(3, device=device)
        symbolic_gm = torch.fx.symbolic_trace(fn)
        includes_method_relu_ = any(
            str(n.target) == "relu_" for n in symbolic_gm.graph.nodes
        )
        self.assertTrue(includes_method_relu_)
        # Also verifies fix for https://github.com/pytorch/pytorch/issues/84570
        gm = make_fx(functionalize(symbolic_gm))(a)
        includes_aten_relu = any(
            n.target == torch.ops.aten.relu.default for n in gm.graph.nodes
        )
        self.assertTrue(includes_aten_relu)

    def test_make_fx_no_decompose(self, device):
        # FIXME
        return self.skipTest("error: maximum recursion reached")

        def f(x):
            return torch.tanh(x).sum()

        fx_f = make_fx(grad(f))(torch.randn(5))
        ops = {i.target for i in fx_f.graph.nodes}

        self.assertEqual(torch.ops.aten.tanh_backward in ops, True)

        fx_f = make_fx(grad(f), decomposition_table)(torch.randn(5))
        ops = {i.target for i in fx_f.graph.nodes}
        self.assertEqual(torch.ops.aten.tanh_backward in ops, False)

    def test_nnc_jit(self, device):
        def f(x):
            return torch.sin(x)

        jit_f = nnc_jit(f)

        inp = torch.randn(3)
        self.assertEqual(jit_f(inp), f(inp))

    def test_nnc_scalar(self, device):
        def f(x):
            return torch.sin(x)

        jit_f = nnc_jit(f)

        inp = torch.randn(())
        self.assertEqual(jit_f(inp), f(inp))

    def test_nnc_pytrees(self, device):
        def f(x):
            return [torch.sin(x[0])]

        jit_f = nnc_jit(f)

        inp = [torch.randn(3)]
        self.assertEqual(jit_f(inp), f(inp))

    def test_external_calls(self, device):
        def f(a, b):
            return torch.mv(a, b)
        jit_f = nnc_jit(f)
        inp = [torch.randn(3, 3), torch.randn(3)]
        self.assertEqual(jit_f(*inp), f(*inp))

    def test_nnc_passthrough(self, device):
        def f(x, y):
            return x + y, y
        inp = (torch.randn(3), torch.randn(3))
        jit_f = nnc_jit(f)
        self.assertEqual(jit_f(*inp), f(*inp))

        def f(x):
            x['a'] = x['a'] * 2
            return x
        inp = ({'a': torch.randn(3), 'b': torch.randn(3)},)
        jit_f = nnc_jit(f)
        self.assertEqual(jit_f(*inp), f(*inp))

    @unittest.skipIf(not USE_TORCHVISION, "test requires torchvision")
    def test_resnet18_backward_trace(self, device):
        mod = torchvision.models.resnet18()

        def f(x):
            out = mod(x)
            out.sum().backward()
            return [a.grad for a in mod.parameters()]

        inp = torch.randn(3, 3, 250, 250, requires_grad=True)
        grads = f(inp)

        mod.zero_grad()
        mod(inp).sum().backward()
        grads2 = [a.grad for a in mod.parameters()]
        self.assertEqual(grads, grads2)

def get_base(t):
    return t._base if t._is_view() else t

def is_in_base(t, maybe_tensors):
    t_base = get_base(t)
    for maybe_tensor in maybe_tensors:
        if isinstance(maybe_tensor, torch.Tensor):
            if t_base is get_base(maybe_tensor):
                return True
    return False

class TestAOTAutograd(AOTTestCase):
    # test_mutation will:
    # - Ensure that inputs are non-leaves, so our graphs can mutate them
    # - try to mutate outputs of the graph (to ensure that autograd meta is set properly on outputs)
    @patch("functorch.compile.config.debug_assert", True)
    def verify_aot_autograd(
        self,
        f,
        inp_: Union[Callable, List[Any]],
        *,
        test_mutation: bool = False,
        only_keep_inference_mutations: bool = False,
        decompositions: Optional[Dict] = None,
        dynamic: bool = False,
        # Only active when inp_ is Callable.
        # TODO: probably consolidate all tests to make inp a Callable.
        make_inputs_subclasses: bool = False,
    ):
        for keep_input_mutations in [True] if only_keep_inference_mutations else [True, False]:
            # Some tests pass in a callable for inp, to generate the inputs
            # (useful if we want to generate complicated aliasing inputs)
            if isinstance(inp_, Callable):
                inp_callable = inp_
                # The callable should return a tuple of f_inputs, f_graph_inputs
                # (The idea is that we might want to compile a function with the graph inputs,
                # but test autograd backprop all the way through the actual inputs)
                with TwoTensorMode() if make_inputs_subclasses else nullcontext():
                    inp_copy, graph_inps_copy = inp_callable()
                    inp, graph_inps = inp_callable()
            else:
                inp_copy = []
                inp = []
                # Our input clones need to mimic when inputs are duplicates of one another
                dupes_map = {}
                for i, x in enumerate(inp_):
                    if x in dupes_map:
                        x_dupe_idx = dupes_map[x]
                        inp_copy.append(inp_copy[x_dupe_idx])
                        inp.append(inp[x_dupe_idx])
                    else:
                        dupes_map[x] = i
                        if not isinstance(x, torch.Tensor):
                            x_copy = x
                            x_copy2 = x
                        else:
                            x_copy = x.clone().detach().requires_grad_(x.requires_grad)
                            x_copy2 = x.clone().detach().requires_grad_(x.requires_grad)
                            if x.requires_grad and not x.is_leaf:
                                x_copy = x_copy.clone()
                                x_copy2 = x_copy2.clone()
                        inp_copy.append(x_copy)
                        inp.append(x_copy2)

                if test_mutation:
                    # For graphs where we mutate inputs, need our test to make sure inputs aren't leaves
                    graph_inps = [x.add(1) for x in inp]
                    graph_inps_copy = [x.add(1) for x in inp_copy]
                else:
                    graph_inps = inp
                    graph_inps_copy = inp_copy
            fw_graph_cell = [None]
            if isinstance(f, nn.Module):
                compiled_f = aot_module(
                    f,
                    fw_compiler=make_boxed_compiler(partial(extract_graph, graph_cell=fw_graph_cell)),
                    bw_compiler=nop,
                    decompositions=decompositions,
                    keep_inference_input_mutations=keep_input_mutations,
                    dynamic=dynamic
                )
            else:
                compiled_f = aot_function(
                    f,
                    fw_compiler=make_boxed_compiler(partial(extract_graph, graph_cell=fw_graph_cell)),
                    bw_compiler=nop,
                    decompositions=decompositions,
                    keep_inference_input_mutations=keep_input_mutations,
                    dynamic=dynamic
                )
            ref_out, ref_grad = outs_and_grads(f, graph_inps, inp)
            test_out, test_grad = outs_and_grads(compiled_f, graph_inps_copy, inp_copy)
            self.assertEqual(ref_grad, test_grad)

            if isinstance(ref_out, torch.Tensor):
                self.assertTrue(isinstance(test_out, torch.Tensor))
                ref_out, test_out = [ref_out], [test_out]
            for ref_o, test_o in zip(ref_out, test_out):
                if isinstance(ref_o, torch.Tensor):
                    self.assertEqual(ref_o.requires_grad, test_o.requires_grad)
                    self.assertEqual(ref_o.is_leaf, test_o.is_leaf)
                    ref_is_view_of_non_interm = is_in_base(ref_o, graph_inps) or is_in_base(ref_o, ref_out)
                    test_is_view_of_non_interm = is_in_base(test_o, graph_inps_copy) or is_in_base(test_o, test_out)
                    self.assertEqual(ref_is_view_of_non_interm, test_is_view_of_non_interm)
                    self.assertEqual(ref_o, test_o)
                    if test_mutation:
                        # This tests that autograd meta is set properly on the output we can
                        # mutate it.
                        ref_o.mul_(2)
                        test_o.mul_(2)
                        self.assertEqual(ref_o, test_o)
            for ref_i, test_i in zip(inp, inp_copy):
                if isinstance(ref_i, torch.Tensor):
                    self.assertEqual(ref_i.requires_grad, test_i.requires_grad)
                self.assertEqual(ref_i, test_i)
        return fw_graph_cell[0]

    def test_non_tensor_and_none_inputs(self):
        # int, None, Tensor
        def f(a, b, c):
            return a * c
        inp = [2, None, torch.ones(3, 3, dtype=torch.float32, requires_grad=True)]
        self.verify_aot_autograd(f, inp)
        inp = [2, None, torch.ones(3, 3, dtype=torch.float32, requires_grad=False)]
        self.verify_aot_autograd(f, inp)

    def test_single_output(self):
        def f(a, b):
            return a + b
        inp = [torch.randn(3, 3, requires_grad=True), torch.randn(3, 3)]
        self.verify_aot_autograd(f, inp)
        inp = [torch.randn(3, 3, requires_grad=False), torch.randn(3, 3)]
        self.verify_aot_autograd(f, inp)

    def test_multi_output(self):
        def f(a, b):
            return a + b, a - b
        inp = [torch.randn(3, 3, requires_grad=True), torch.randn(3, 3)]
        self.verify_aot_autograd(f, inp)
        inp = [torch.randn(3, 3, requires_grad=False), torch.randn(3, 3)]
        self.verify_aot_autograd(f, inp)

    def test_multi_output_list(self):
        def f(a, b):
            return [a + b, a - b]
        inp = [torch.randn(3, 3, requires_grad=True), torch.randn(3, 3)]
        self.verify_aot_autograd(f, inp)
        inp = [torch.randn(3, 3, requires_grad=False), torch.randn(3, 3)]
        self.verify_aot_autograd(f, inp)

    # Test for bug occurring at the intersection of fake tensors & functionalization.
    def test_squeeze_mutation(self):
        def f(a):
            b = a.clone().squeeze(-1)
            b.add_(1.)
            return a + b

        inp = [torch.randn(3, 1, requires_grad=True)]
        self.verify_aot_autograd(f, inp, dynamic=True)
        inp = [torch.randn(3, 1, requires_grad=False)]
        self.verify_aot_autograd(f, inp, dynamic=True)

    def test_complex_linear(self):
        # https://github.com/pytorch/pytorch/issues/93424
        inp = [torch.randn(1, 10, 10, dtype=torch.complex64)]

        class F(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = nn.Linear(10, 10, dtype=torch.complex64)

            def forward(self, x):
                return self.linear(x).sum().abs()

        self.verify_aot_autograd(F(), inp)

    def test_embedding_bag_view_dynamic(self):
        # Backwards pass tries to wrap a sparse tensor in a FunctionalTensorWrapper;
        # test that this works even though the sparse tensor has no storage.

        class F(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.emb = torch.nn.EmbeddingBag(100, 8, sparse=True)

            def forward(self, x, y):
                return self.emb(x, y).view(-1)

        x = torch.arange(3)
        y = torch.arange(3)
        self.verify_aot_autograd(F(), [x, y], dynamic=False)
        self.verify_aot_autograd(F(), [x, y], dynamic=True)



    def test_input_mutation_simple(self):
        def f(a):
            a.mul_(2)
            return a * 3
        inp = [torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        # Things to note:
        # - the extra clone is because we need to pass the pre-mutated input to grad(),
        #   but autograd operates above functionalization so we need to manually clone.
        #   Hopefully backends can optimize this easily.
        # - The extra return arg is because the compiled forward returns (mutated inputs + outputs)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    mul = torch.ops.aten.mul.Tensor(clone, 2);  clone = None
    mul_1 = torch.ops.aten.mul.Tensor(mul, 3)
    return [mul, mul_1]""")

    def test_input_mutation_set__input_mutation(self):
        def f(a):
            b = torch.arange(9, dtype=a.dtype).reshape(3, 3)
            with torch.no_grad():
                a.set_(b)
            return a * b
        inp = [torch.ones(3, 3, requires_grad=True)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)

    def test_set__steals_view_chain(self):
        def f(a, b):
            a_ = a.mul(2)
            b_ = b.mul(2)
            b_slice = b_[1].view(3, 3)
            # a_clone should inherit the view chain from b_slice
            a_.set_(b_slice)
            # Also mutates b_,
            a_.view(-1).mul_(2)
            return a_ * b_slice
        inp = [torch.ones(3, 3, requires_grad=False), torch.zeros(3, 9, requires_grad=False)]
        self.verify_aot_autograd(f, inp)

    def test_set__and_data_mutation_good(self):
        def f(a, b):
            # The data mutation happens *after* the set_(). This is ok (see the graph below)
            with torch.no_grad():
                a.set_(b)
            b.mul_(2)
            return a + b
        inp = [torch.ones(3, 3, requires_grad=True), torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=False), torch.zeros(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        # Important things to note:
        # - "return a.set_(b)" desugars into "return b"
        # - Both a and b are recorded as experiencing mutations,
        #   which is why we see "b_updated" (output of the mul) twice in the graph outputs.
        #   a is recorded as both a data mutation and a metadata mutation (due to set_ swapping its storage).
        # - the runtime epilogue for a is "a.set_(mul)"
        # - the runtime epilogue for b is "b.copy_(mul)"
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2):
    clone = torch.ops.aten.clone.default(primals_2);  primals_2 = None
    mul = torch.ops.aten.mul.Tensor(clone, 2);  clone = None
    add = torch.ops.aten.add.Tensor(mul, mul)
    return [mul, mul, add]""")

    # This is a (hopefully) extremely rare case that is difficult to handle,
    # so we ban it.
    def test_set__and_data_mutation_bad(self):
        def f(a):
            a_view = a.view(-1)
            tmp = torch.ones(3, 3, requires_grad=True)
            # Now, any mutations on either tmp
            # will be tracked as graph input mutations.
            with torch.no_grad():
                a.set_(tmp)
            # BAD: a_view is now detached from every graph input,
            # so we won't recognize that this caused an input mutation!
            a_view.mul_(2)
            return a + tmp
        inp = [torch.ones(3, 3, requires_grad=True)]
        with self.assertRaisesRegex(RuntimeError, "cannot mutate tensors with frozen storage"):
            self.verify_aot_autograd(f, inp, test_mutation=True)

    def test_input_mutation_set__nop(self):
        def f(a):
            b = torch.arange(9, dtype=a.dtype)
            a_old = torch.ops.aten.alias.default(a)
            with torch.no_grad():
                a.set_(b)
                a.set_(a_old)
            return a + b.reshape(3, 3)
        inp = [torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        # Things to note:
        # - There are no set_() calls in the graph (we functionalize a.set_(b) into "b")
        # - There is only **1** graph output. We properly realized that the two set_() calls
        #   undo each other, and so effectively no inputs are mutated.
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    arange = torch.ops.aten.arange.default(9, dtype = torch.float32, device = device(type='cpu'), pin_memory = False)
    alias = torch.ops.aten.alias.default(primals_1);  primals_1 = None
    view = torch.ops.aten.view.default(arange, [3, 3]);  arange = None
    add = torch.ops.aten.add.Tensor(alias, view);  alias = view = None
    return [add]""")

    def test_input_mutation_simple_with_none_and_nontensor(self):
        # Tensor, None, int
        def f(a, b, c):
            return a * c
        f_compiled = aot_function(f, nop)
        for req_grad in [True, False]:
            inp = [torch.ones(3, 3, requires_grad=req_grad), None, 3]
            out_ref = f(*inp)
            out_test = f_compiled(*inp)
            self.assertEqual(out_ref, out_test)

    # https://github.com/pytorch/pytorch/issues/93363
    def test_mutates_input_noncontiguous(self):
        def f(a):
            a.add_(1)
            return ()

        f_compiled = aot_function(f, nop)
        ref = torch.ones(4, requires_grad=True) + 0
        ref_view = ref[0::2]

        test = torch.ones(4, requires_grad=True) + 0
        test_view = test[0::2]

        out_ref = f(ref_view)
        out_test = f_compiled(test_view)
        print(ref)
        print(test)
        self.assertEqual(ref, test)

    def test_input_mutation_modifies_autograd_meta_of_aliases(self):
        def f(a):
            a.mul_(2)
            out = a + 1
            return out.detach()

        x_ref = torch.ones(3, 3, requires_grad=True).clone()
        x_ref_view = x_ref.view(3, 3)

        x_test = torch.ones(3, 3, requires_grad=True).clone()
        x_test_view = x_test.view(3, 3)

        f_compiled = aot_function(f, nop, keep_inference_input_mutations=True)
        f(x_ref)
        f_compiled(x_test)
        # f will mutate aliases of the input, including its autograd metadata!
        # y.grad_fn is AsStridedBackward
        self.assertEqual(x_ref_view, x_test_view)
        self.assertEqual(x_ref_view._version, x_test_view._version)
        self.assertEqual(x_ref_view.grad_fn.__class__, x_test_view.grad_fn.__class__)
        # Test the actual gradients are correct
        (x_ref * x_ref_view).sum().backward()
        (x_test * x_test_view).sum().backward()
        self.assertEqual(x_ref.grad, x_test.grad)
        self.assertEqual(x_ref_view.grad, x_test_view.grad)


    def test_outputs_are_aliased(self):
        # Tensor, None, int
        def f(a):
            b = a.mul(2)
            c = b.view(-1)
            return b, c
        f_compiled = aot_function(f, nop)
        for req_grad in [True, False]:
            inp = torch.ones(3, requires_grad=req_grad)
            out_ref = f(inp)
            out_test = f_compiled(inp)
            self.assertEqual(out_ref[0], out_test[0])
            self.assertEqual(out_ref[1], out_test[1])
            # Try mutating one of the outputs, which is aliased.
            out_ref[0].mul_(3)
            out_test[0].mul_(3)
            # Assert that the aliasing relationship was preserved
            self.assertEqual(out_ref[0], out_test[0])
            self.assertEqual(out_ref[1], out_test[1])

    def test_input_mutation_is_output(self):
        def f(a):
            a.mul_(2)
            return a
        inp = [torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    mul = torch.ops.aten.mul.Tensor(clone, 2);  clone = None
    return [mul, mul]""")

    def test_input_mutation_multiple(self):
        def f(a, b, c):
            a.mul_(2)
            c.mul_(2)
            return a + b + c

        def create_inp(req_grad):
            return [
                torch.ones(3, 3, requires_grad=req_grad),
                torch.ones(3, 3, requires_grad=req_grad),
                torch.ones(3, 3, requires_grad=req_grad),
            ]

        self.verify_aot_autograd(f, create_inp(False), test_mutation=True)

        fw_graph = self.verify_aot_autograd(f, create_inp(True), test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2, primals_3):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    clone_1 = torch.ops.aten.clone.default(primals_3);  primals_3 = None
    mul = torch.ops.aten.mul.Tensor(clone, 2);  clone = None
    mul_1 = torch.ops.aten.mul.Tensor(clone_1, 2);  clone_1 = None
    add = torch.ops.aten.add.Tensor(mul, primals_2);  primals_2 = None
    add_1 = torch.ops.aten.add.Tensor(add, mul_1);  add = None
    return [mul, mul_1, add_1]""")

    def test_input_mutation_return(self):
        def f(a, b):
            return torch.sin(a, out=b)

        inp = [
            torch.randn(3, 3),
            torch.ones(3, 3)
        ]

        fw_graph = self.verify_aot_autograd(
            f, inp, test_mutation=True, only_keep_inference_mutations=True
        )
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, arg0_1, arg1_1):
    sin = torch.ops.aten.sin.default(arg0_1);  arg0_1 = None
    copy_ = torch.ops.aten.copy_.default(arg1_1, sin);  arg1_1 = sin = None
    return (copy_,)""")

    def test_input_mutation_metadata(self):
        def f(a, b):
            a.transpose_(1, 0)
            return a + b

        def create_inp(req_grad):
            return [
                torch.ones(3, 3, requires_grad=req_grad),
                torch.ones(3, 3, requires_grad=req_grad),
            ]

        self.verify_aot_autograd(f, create_inp(True), test_mutation=True)
        self.verify_aot_autograd(f, create_inp(False), test_mutation=True)

    def test_input_output_aliase_custom_autograd_function(self):

        class Foo(torch.autograd.Function):
            @staticmethod
            def forward(ctx, x):
                return x

            @staticmethod
            def backward(ctx, gx):
                return gx * 0.5

        def f(x):
            return Foo.apply(x)

        inp = [torch.ones(2, 2, requires_grad=True)]
        self.verify_aot_autograd(f, inp, test_mutation=False)

    def test_input_mutation_requires_grad_detach(self):
        # Here, "a" requires grad, and gets mutated, so we append a copy_() to the end of the graph.
        # Its mutation doesn't take part in autograd though, because we mutated a detach'd view.
        # Need to make sure that this copy_() doesn't error, and doesn't participate in autograd either.
        def f(a):
            a.detach().mul_(2)
            return a + 3
        inp = [torch.ones(4, requires_grad=True)]
        self.verify_aot_autograd(f, inp, test_mutation=False)
        inp = [torch.ones(4, requires_grad=True)]
        # test_mutation=True will first do some compute on inp, so it is no longer an autograd leaf
        # by the time it becomes a graph input. Good to test both cases.
        self.verify_aot_autograd(f, inp, test_mutation=True)

    def test_input_mutation_requires_grad_no_grad(self):
        def f(a):
            with torch.no_grad():
                a.mul_(2)
            return a + 3
        inp = [torch.ones(4, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True, only_keep_inference_mutations=True)
        # Even though the input requires_grad, we expect the keep the input mutation in the graph
        # (Even though this is a training graph!)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    mul = torch.ops.aten.mul.Tensor(primals_1, 2)
    add = torch.ops.aten.add.Tensor(mul, 3)
    copy_ = torch.ops.aten.copy_.default(primals_1, mul);  primals_1 = mul = None
    return [add]""")

    def test_input_mutation_requires_grad_no_grad_inference_graph(self):
        def f(a):
            with torch.no_grad():
                a.mul_(2)
                return a + 3
        inp = [torch.ones(4, requires_grad=True)]
        # Even though the input requires_grad, we expect the keep the input mutation in the graph
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True, only_keep_inference_mutations=True)

        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, arg0_1):
    mul = torch.ops.aten.mul.Tensor(arg0_1, 2)
    add = torch.ops.aten.add.Tensor(mul, 3)
    copy_ = torch.ops.aten.copy_.default(arg0_1, mul);  arg0_1 = mul = None
    return (add,)""")

    def test_input_mutation_requires_grad_no_grad_detach_mixed(self):
        # Perform a mix of mutations on a:
        # 1 normal, 1 in no_grad, 1 on a detach'd tensor.
        # Only the first should participate in gradient computation.
        def f(a):
            a.detach().mul_(2)
            a.mul_(3)
            with torch.no_grad():
                a.mul_(4)
            return a + 5
        inp = [torch.ones(4, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)

    def test_input_mutation_metadata2(self):
        def f(a):
            a.transpose_(1, 0)
            a.mul_(2)
            return a + 1
        inp = [torch.ones(3, 3, requires_grad=True)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)

    def test_input_mutation_batchnorm(self):
        def f(inpt, weight, bias, running_mean, running_var):
            # This is additionally a good test, because the input tensors that we mutate
            # are *also* saved for backwards.
            # This tests that what we save for the backward is actually cloned inputs,
            # and not the original inputs that got mutated.
            return torch._native_batch_norm_legit(inpt, weight, bias, running_mean, running_var, True, 0.5, 1e-5)

        def create_inp(req_grad):
            return [
                torch.ones(2, 5, 5, 5, requires_grad=req_grad),
                torch.ones(5, requires_grad=req_grad),
                torch.ones(5, requires_grad=req_grad),
                torch.ones(5),
                torch.ones(5),
            ]

        from torch._decomp import get_decompositions
        # This simulates what inductor does (running the fw + bw decompositions)
        decompositions = get_decompositions([
            torch.ops.aten._native_batch_norm_legit_functional,
            torch.ops.aten.native_batch_norm_backward,
        ])
        self.verify_aot_autograd(f, create_inp(True), test_mutation=True, decompositions=decompositions)
        self.verify_aot_autograd(f, create_inp(False), test_mutation=True, decompositions=decompositions)

    def test_batchnorm_inference(self):
        inp = [
            torch.ones(2, 5, 5, 5, requires_grad=True),
            torch.ones(5, requires_grad=True),
            torch.ones(5, requires_grad=True),
            torch.ones(5),
            torch.ones(5),
        ]

        m = torch.nn.BatchNorm2d(4, 4)
        m.eval()
        fw_graph_cell = [None]
        inp = torch.ones(4, 4, 4, 4)
        fw_graph_cell = [None]
        compiled_m = aot_module(
            m,
            fw_compiler=partial(extract_graph, graph_cell=fw_graph_cell),
            bw_compiler=nop,
            keep_inference_input_mutations=True,
        )
        inp = torch.ones(4, 4, 4, 4)
        with torch.no_grad():
            out = compiled_m(inp)
        # expectation: there are no copy_() calls in the decomposed batch norm when running under training=False (eval mode)
        code = fw_graph_cell[0].code.strip()
        self.assertTrue("copy_" not in str(code))

    def test_input_output_view_simple(self):
        def f(a):
            return a.view(-1)
        inp = [torch.ones(2, 2, requires_grad=False).add(1)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(2, 2, requires_grad=True).add(1)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        # Outputs that alias inputs are pulled out of the graph entirely, so we don't compile anything here
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    view = torch.ops.aten.view.default(primals_1, [-1]);  primals_1 = None
    return [view]""")

    def test_input_output_view_mutate_multiple(self):
        def f(a, b, c):
            a.mul_(2)
            c.mul_(3)
            return b.view(2, 2), c.view(2, 2)

        def create_inp(req_grad):
            return [
                torch.ones(2, 2, requires_grad=req_grad).add(1),
                torch.ones(2, 2, requires_grad=req_grad).add(1),
                torch.ones(2, 2, requires_grad=req_grad).add(1),
            ]

        self.verify_aot_autograd(f, create_inp(False), test_mutation=True)
        fw_graph = self.verify_aot_autograd(f, create_inp(True), test_mutation=True)
        # The original function returned two outputs, both of which aliased inputs.
        # We expect two outputs in the functional graph, a_updated and c_updated.
        # The actual aliased outputs themselves aren't in the compiled forward graph;
        # Instead, they're generated outside of  the graph.
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2, primals_3):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    clone_1 = torch.ops.aten.clone.default(primals_3);  primals_3 = None
    mul = torch.ops.aten.mul.Tensor(clone, 2);  clone = None
    mul_1 = torch.ops.aten.mul.Tensor(clone_1, 3);  clone_1 = None
    view = torch.ops.aten.view.default(primals_2, [2, 2]);  primals_2 = None
    view_2 = torch.ops.aten.view.default(mul_1, [2, 2])
    return [mul, mul_1, view, view_2]""")

    def test_input_output_view_metadata_mutate_multiple(self):
        def f(a, b, c):
            b.mul_(3)
            c.t_()
            return a.view(2, 2), b.view(2, 2), c.view(2, 2)

        def create_inp(req_grad):
            return [
                torch.ones(2, 2, requires_grad=req_grad).add(1),
                torch.ones(2, 2, requires_grad=req_grad).add(1),
                torch.ones(2, 2, requires_grad=req_grad).add(1),
            ]

        self.verify_aot_autograd(f, create_inp(False), test_mutation=True)
        fw_graph = self.verify_aot_autograd(f, create_inp(True), test_mutation=True)
        # Important thing to check here: of the three inputs:
        # Only the b.mul_(3) should show up in the graph (we functionalize it and return it).
        # Everything else that does not show up in the graph includes:
        # - The metadata mutation on c (we do it outside the graph)
        # - All 3 original fw outputs, which are aliases of inputs (we regenerate them outside of the graph)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2, primals_3):
    clone = torch.ops.aten.clone.default(primals_2);  primals_2 = None
    view = torch.ops.aten.view.default(primals_3, [2, 2]);  primals_3 = None
    mul = torch.ops.aten.mul.Tensor(clone, 3);  clone = None
    t = torch.ops.aten.t.default(view);  view = None
    view_1 = torch.ops.aten.view.default(primals_1, [2, 2]);  primals_1 = None
    view_3 = torch.ops.aten.view.default(t, [2, 2])
    view_4 = torch.ops.aten.view.default(mul, [2, 2])
    return [mul, t, view_1, view_4, view_3]""")

    def test_input_mutation_and_output_view(self):
        def f(a):
            a.add_(1)
            return a.view(-1)
        inp = [torch.ones(2, 2, requires_grad=False).add(1)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(2, 2, requires_grad=True).add(1)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        # Here, total # of outputs is 1 because:
        # - num_mutated_inps = 1 (a_updated)
        # - num_fw_outputs = 0 (the output is an alias of the input, so we move it outside the compiled fw)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    add = torch.ops.aten.add.Tensor(clone, 1);  clone = None
    view_1 = torch.ops.aten.view.default(add, [-1])
    return [add, view_1]""")


    def test_input_mutation_output_view_multiple(self):
        def f(a, b, c, d):
            b.transpose_(1, 0)
            c.add_(1)
            return d + 1, b.diagonal(), a + c

        def create_inp(req_grad):
            return [
                torch.arange(4, requires_grad=req_grad, dtype=torch.float32).view(2, 2).add(1),
                torch.arange(4, requires_grad=req_grad, dtype=torch.float32).view(2, 2).add(1),
                torch.ones(2, 2, requires_grad=req_grad).add(1),
                torch.ones(2, 2, requires_grad=req_grad).add(1),
            ]

        self.verify_aot_autograd(f, create_inp(False), test_mutation=True)
        fw_graph = self.verify_aot_autograd(f, create_inp(True), test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2, primals_3, primals_4):
    view = torch.ops.aten.view.default(primals_2, [2, 2]);  primals_2 = None
    clone = torch.ops.aten.clone.default(primals_3);  primals_3 = None
    transpose = torch.ops.aten.transpose.int(view, 1, 0);  view = None
    add = torch.ops.aten.add.Tensor(clone, 1);  clone = None
    add_1 = torch.ops.aten.add.Tensor(primals_4, 1);  primals_4 = None
    diagonal = torch.ops.aten.diagonal.default(transpose)
    add_2 = torch.ops.aten.add.Tensor(primals_1, add);  primals_1 = None
    return [transpose, add, add_1, diagonal, add_2]""")

    def test_output_aliases_intermediate_single(self):
        def f(a):
            out = torch.mul(a, 3)
            return out.view(-1)
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        # In AOTAutograd, we are obligated to make the compiled forward directly return `out`,
        # and reconstruct `out.view(-1)` as a fresh output.
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    mul = torch.ops.aten.mul.Tensor(primals_1, 3);  primals_1 = None
    view = torch.ops.aten.view.default(mul, [-1]);  mul = None
    return [view]""")

    def test_output_aliases_input_multi_output_view_should_raise_autograd_error(self):
        def f1(a):
            return list(a.unbind(0))

        f1_compiled = aot_function(f1, nop)

        inp1 = torch.ones(3, 3, requires_grad=True).clone()
        inp2 = torch.ones(3, 3, requires_grad=True).clone()
        inp3 = torch.ones(3, 3, requires_grad=True).clone()

        with self.assertRaisesRegex(RuntimeError, "Such functions do not allow the output views"):
            out_test1 = f1_compiled(inp1)
            # This raises a runtime error from autograd in eager mode
            out_test1[0].mul_(2)

        with self.assertRaisesRegex(RuntimeError, "Such functions do not allow the output views"):
            out_test2 = f1_compiled(inp2)
            inp2.mul_(2)
            # In eager mode, if we mutate a tensor, any multi-output-view aliases
            # get their grad_fn replaced with error nodes, so accessing grad_fn should error
            grad_fn = out_test2[0].grad_fn

        with self.assertRaisesRegex(RuntimeError, "Such functions do not allow the output views"):
            out_test3 = f1_compiled(inp3)
            out_test1[0].detach().mul_(2)
            # The above case also applies to detached aliases (they turn the multi-output-view
            # alias's grad_fns into error nodes)
            grad_fn = out_test2[0].grad_fn


    def test_output_aliases_input_multi_output_view(self):
        # All aliased outs are from multi-output views, so AOTAutograd will hide the aliasing from autograd.
        def f1(a):
            return list(a.unbind(0))

        inp = torch.ones(3, 3, requires_grad=True)
        inp_ref = torch.ones(3, 3, requires_grad=True)
        f1_compiled = aot_function(f1, nop)

        out_ref = f1(inp_ref)
        out_test = f1_compiled(inp)
        # Assert that we get CompiledFunctionBackward in the backward graph,
        # and not AsStridedBackward. No view-regeneration necessary for this mult-output view case.
        # See Note: [AOTAutograd: differentiable outputs that alias each other from a multi-output view call]
        self.assertTrue(all('CompiledFunctionBackward' in str(o.grad_fn) for o in out_test))

        sum(out_ref).sum().backward()
        sum(out_test).sum().backward()
        self.assertEqual(inp_ref.grad, inp.grad)

        # Several of the outputs are from multi-output views.
        # However: they are part of the same alias set as "a", and "a.view(out.shape)",
        # which are both user-visible.
        # AOTAutograd will not try to be smart here and hide the aliasing relationships from autograd.
        # Instead, it will perform its "output aliases input" logic, and regenerate all aliases.
        def f3(a):
            return *list(a.unbind(0)), a.view(a.shape)

        inp = torch.ones(3, 3, requires_grad=True)
        inp_ref = torch.ones(3, 3, requires_grad=True)
        f3_compiled = aot_function(f3, nop)

        inp_ref_clone = inp_ref.clone()
        inp_clone = inp.clone()
        out_ref = f3(inp_ref_clone)
        out_test = f3_compiled(inp_clone)
        self.assertTrue(all('UnbindBackward' in str(o.grad_fn) for o in out_test[:3]))

        # The last output is not from a multi-output view, so autograd will let us mutate it.
        out_ref[-1].mul_(2)
        out_test[-1].mul_(2)
        # Also mutate the input, which should affect the aliased output.
        inp_ref_clone.view(-1).mul_(3)
        inp_clone.view(-1).mul_(3)
        # Do backward
        (inp_ref + out_ref[-1]).sum().backward()
        (inp + out_test[-1]).sum().backward()
        self.assertEqual(inp_ref.grad, inp.grad)


    def test_output_aliases_intermediate_multi_output_view(self):
        # All aliased outs are from multi-output views, so AOTAutograd will hide the aliasing from autograd.
        def f1(a):
            out = torch.mul(a, 3)
            return list(out.unbind(0))

        inp = torch.ones(3, 3, requires_grad=True)
        inp_ref = torch.ones(3, 3, requires_grad=True)
        f1_compiled = aot_function(f1, nop)

        out_ref = f1(inp_ref)
        out_test = f1_compiled(inp)
        # Assert that we get CompiledFunctionBackward in the backward graph,
        # and not AsStridedBackward. No view-regeneration necessary for this mult-output view case.
        # See Note: [AOTAutograd: differentiable outputs that alias each other from a multi-output view call]
        self.assertTrue(all('CompiledFunctionBackward' in str(o.grad_fn) for o in out_test))

        sum(out_ref).sum().backward()
        sum(out_test).sum().backward()
        self.assertEqual(inp_ref.grad, inp.grad)

        # All aliased outs but one are from multi-output views, so AOTAutograd will hide the aliasing from autograd.
        def f2(a):
            out = torch.mul(a, 3)
            return *list(out.unbind(0)), out

        inp = torch.ones(3, 3, requires_grad=True)
        inp_ref = torch.ones(3, 3, requires_grad=True)
        f2_compiled = aot_function(f2, nop)

        out_ref = f2(inp_ref)
        out_test = f2_compiled(inp)
        # Assert that we get CompiledFunctionBackward in the backward graph,
        # and not AsStridedBackward. No view-regeneration necessary for this mult-output view case.
        # See Note: [AOTAutograd: differentiable outputs that alias each other from a multi-output view call]
        self.assertTrue(all('CompiledFunctionBackward' in str(o.grad_fn) for o in out_test))

        # The last output is not from a multi-output view, so autograd will let us mutate it.
        out_ref[-1].mul_(2)
        out_test[-1].mul_(2)
        out_ref[-1].sum().backward()
        out_test[-1].sum().backward()
        self.assertEqual(inp_ref.grad, inp.grad)

        # All aliased outs but one are from multi-output views, so AOTAutograd will hide the aliasing from autograd.
        def f3(a):
            out = torch.mul(a, 3)
            return *list(out.unbind(0)), out.view(out.shape)

        inp = torch.ones(3, 3, requires_grad=True)
        inp_ref = torch.ones(3, 3, requires_grad=True)
        f3_compiled = aot_function(f3, nop)

        out_ref = f3(inp_ref)
        out_test = f3_compiled(inp)
        # Assert that we get CompiledFunctionBackward in the backward graph,
        # and not AsStridedBackward. No view-regeneration necessary for this mult-output view case.
        # See Note: [AOTAutograd: differentiable outputs that alias each other from a multi-output view call]
        self.assertTrue(all('CompiledFunctionBackward' in str(o.grad_fn) for o in out_test))

        # The last output is not from a multi-output view, so autograd will let us mutate it.
        out_ref[-1].mul_(2)
        out_test[-1].mul_(2)
        out_ref[-1].sum().backward()
        out_test[-1].sum().backward()
        self.assertEqual(inp_ref.grad, inp.grad)

        # There are 5 outputs that all alias each other.
        # 3 of them come from multi-output views, but the other 3 are "ordinary" aliases.
        # Therefore, AOTAutograd will not attempt the multi-output-view optimization,
        # and apply the intermediate_base logic to all aliases.
        # (In theory we could probably get AOTAutograd to only apply the intermediate base
        # logic to the last 2 outputs and not the first 3. We should probably
        # just do the graph partitioning defined in this doc instead though).
        # https://docs.google.com/document/d/1DlfFq8TKbuAn2zyJxLfoW-X1qkkm5PLdHFtySo03QAk/edit
        def f4(a):
            out = torch.mul(a, 3)
            # also return the graph intermediate directly,
            # which will force AOTAutograd to do the "intermediate base" logic.
            # (Why? The user can mutate "out", which should change the autograd metadata
            #  of the other aliased outputs)
            return *list(out.unbind(0)), out, out.view(out.shape)

        inp = torch.ones(3, 3, requires_grad=True)
        inp_ref = torch.ones(3, 3, requires_grad=True)
        f4_compiled = aot_function(f4, nop)

        out_ref = f4(inp_ref)
        out_test = f4_compiled(inp)
        # Mutate the last output of f4 (autograd will allow this, since it is not a multi-output view,
        # as long as *only* the non-multi-output views participate in the backward)
        # Note: We could probably try to hide **only** the multi-output views from autograd here
        # and only do the intermediate base logic for the last two aliases.
        # Longer term solution of graph partitioning is probably cleaner though (see the note).
        out_ref[-1].mul_(2)
        out_test[-1].mul_(2)

        out_ref_sum = out_ref[-1] + out_ref[-2]
        out_test_sum = out_test[-1] + out_test[-2]
        out_ref_sum.sum().backward()
        out_test_sum.sum().backward()
        self.assertEqual(inp_ref.grad, inp.grad)


    def test_output_aliases_intermediate_mutation_linear(self):
        def f(x):
            return (x + 1).view(-1)

        inp = [torch.ones(3, 3, requires_grad=True)]
        # use inductor's decomps (which will e.g. turn _unsafe_view() into view())
        from torch._inductor.decomposition import decompositions
        f_compiled = aot_function(f, nop, decompositions=decompositions)

        out_ref = f(*inp)
        out_test = f_compiled(*inp)

        out_ref.mul_(2)
        out_test.mul_(2)
        self.assertEqual(out_ref, out_test)

    def test_output_aliases_intermediate_no_grad(self):
        def f(a, b):
            out = torch.mul(a, 3)
            # First output is an alias of an intermediate that doesn't require grad
            return out.view(-1), b.add(1)
        inp = [torch.ones(3, 3), torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3), torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        # important bit: we don't bother generating an intermediate base as an output in the graph,
        # because the intermediate base itself didn't require gradients.
        # (the only problematic case is when both the base and the aliasesed output require gradients).
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2):
    mul = torch.ops.aten.mul.Tensor(primals_1, 3);  primals_1 = None
    view = torch.ops.aten.view.default(mul, [-1]);  mul = None
    add = torch.ops.aten.add.Tensor(primals_2, 1);  primals_2 = None
    return [view, add]""")

    def test_output_aliases_intermediate_returned_multiple_times(self):
        def f(a):
            out = torch.mul(a, 3)
            out_view = out.view(-1)
            return out, out_view, out
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)

    def test_output_aliases_intermediate_multiple(self):
        def f(a):
            out = torch.mul(a, 3)
            # AOTAutograd should manually generate these two output views in the epilogue.
            return out.view(-1), out.view(-1)
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    mul = torch.ops.aten.mul.Tensor(primals_1, 3);  primals_1 = None
    view = torch.ops.aten.view.default(mul, [-1])
    view_1 = torch.ops.aten.view.default(mul, [-1])
    return [view, view_1, mul]""")

    def test_output_aliases_intermediate_and_returned(self):
        def f(a):
            out = torch.mul(a, 3)
            # AOTAutograd should manually generate the first output (a view of an intermediate)
            # but not the second (which is itself the intermediate for the first)
            return out.view(-1), out
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    mul = torch.ops.aten.mul.Tensor(primals_1, 3);  primals_1 = None
    view = torch.ops.aten.view.default(mul, [-1])
    return [view, mul]""")

    def test_output_aliases_intermediate_and_returned_flipped(self):
        def f(a):
            out = torch.mul(a, 3)
            # AOTAutograd should manually generate the first output (a view of an intermediate)
            # but not the second (which is itself the intermediate for the first)
            return out, out.view(-1)
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    mul = torch.ops.aten.mul.Tensor(primals_1, 3);  primals_1 = None
    view = torch.ops.aten.view.default(mul, [-1])
    return [mul, view]""")

    def test_output_aliases_intermediate_and_returned_different_grad(self):
        def f(a):
            out = torch.mul(a, 3)
            # AOTAutograd should manually generate the first output (a view of an intermediate)
            # but not the second (which is itself the intermediate for the first)
            return out.view(-1), out, out[0].detach()
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    mul = torch.ops.aten.mul.Tensor(primals_1, 3);  primals_1 = None
    view = torch.ops.aten.view.default(mul, [-1])
    select = torch.ops.aten.select.int(mul, 0, 0)
    detach = torch.ops.aten.detach.default(select);  select = None
    detach_1 = torch.ops.aten.detach.default(detach);  detach = None
    detach_2 = torch.ops.aten.detach.default(detach_1);  detach_1 = None
    return [view, mul, detach_2]""")

    def test_output_aliases_intermediate_inplace_view(self):
        def f(a):
            out = torch.mul(a, 3)
            out.t_()
            return out
        inp = [torch.ones(2, 4, requires_grad=True)]

        # TODO: fix this test.
        # See https://github.com/pytorch/pytorch/issues/90507
        # self.verify_aot_autograd(f, inp, test_mutation=True)

    def test_output_aliases_intermediate_inplace_view_with_detach(self):
        def f(a):
            out = torch.mul(a, 3)
            out.t_()
            out.detach_()
            # Thanks to the detach_() AOT Autograd doesn't need to do anything.
            # `out` will show up as having OutputType.non_alias,
            # and ._is_view() == False
            return out, a + 1
        inp = [torch.ones(2, 4, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(2, 4, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    mul = torch.ops.aten.mul.Tensor(primals_1, 3)
    t = torch.ops.aten.t.default(mul);  mul = None
    add = torch.ops.aten.add.Tensor(primals_1, 1);  primals_1 = None
    return [t, add]""")


    def test_output_aliases_intermediate_inplace_view_and_view(self):
        def f(a):
            out = torch.mul(a, 3)
            out_view = out.unsqueeze(0)
            out.t_()
            out_view2 = out.unsqueeze(0)
            return out_view, out, out_view2
        inp = [torch.ones(2, 4, requires_grad=True)]

        # TODO: fix this test.
        # See <github issue link>
        # self.verify_aot_autograd(f, inp, test_mutation=True)

    def test_output_aliases_intermediate_multiple_mixed(self):
        def f(a):
            out1 = torch.mul(a, 3)
            out2 = torch.mul(a, 4)
            # AOTAutograd should manually generate these two output views in the epilogue.
            return out1.view(-1), out2.transpose(1, 0), out1.transpose(1, 0)
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    mul = torch.ops.aten.mul.Tensor(primals_1, 3)
    mul_1 = torch.ops.aten.mul.Tensor(primals_1, 4);  primals_1 = None
    view = torch.ops.aten.view.default(mul, [-1])
    transpose = torch.ops.aten.transpose.int(mul_1, 1, 0);  mul_1 = None
    transpose_1 = torch.ops.aten.transpose.int(mul, 1, 0)
    return [view, transpose, transpose_1, mul]""")

    def test_output_all_alias_types(self):
        # There are 3 types of aliasing that require us to return metadata in the compiled fw:
        # (1) outputs that are views of inputs
        # (2) outputs that are views of intermediates
        # (3) inputs that get metadata mutations
        # test all 3 of them here
        def f(a):
            a.transpose_(1, 0)
            tmp = a.mul(2)
            return tmp.squeeze(), tmp.transpose(1, 0), a.unsqueeze(0)

        def inp_callable(req_grad):
            x = torch.ones(1, 2, 4, requires_grad=req_grad).clone()
            return [(x,), (x,)]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)
        fw_graph = self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        # TODO: make this test run with dynamic shapes so it is more meaningful
        # metadata output order: (a_updated_meta, out1_meta, out2_meta, out3_meta)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    view = torch.ops.aten.view.default(primals_1, [1, 2, 4]);  primals_1 = None
    transpose = torch.ops.aten.transpose.int(view, 1, 0);  view = None
    mul = torch.ops.aten.mul.Tensor(transpose, 2)
    squeeze = torch.ops.aten.squeeze.default(mul)
    transpose_1 = torch.ops.aten.transpose.int(mul, 1, 0)
    unsqueeze = torch.ops.aten.unsqueeze.default(transpose, 0)
    return [transpose, squeeze, transpose_1, unsqueeze, mul]""")

    @parametrize("req_grad", [False, True])
    def test_subclass_metadata_mutation(self, req_grad):
        def f(a):
            a.transpose_(1, 0)
            tmp = a.mul(2)
            return tmp.transpose(1, 0)

        def inp_callable(req_grad):
            x = torch.ones(1, 2, 4, requires_grad=req_grad).clone()
            return [(x,), (x,)]

        # See https://github.com/pytorch/pytorch/issues/114975
        with self.assertRaisesRegex(RuntimeError, "Metadata mutations are currently not allowed on tensor subclasses"):
            self.verify_aot_autograd(f, partial(inp_callable, req_grad=req_grad), test_mutation=True, make_inputs_subclasses=True)

    def test_input_data_and_metadata_mutation(self):
        def f(a):
            a.t_()
            a[0].mul_(2)
            return a.view(a.shape)
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=True)]
        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    t = torch.ops.aten.t.default(clone)
    select = torch.ops.aten.select.int(t, 0, 0);  t = None
    mul = torch.ops.aten.mul.Tensor(select, 2);  select = None
    t_1 = torch.ops.aten.t.default(clone);  clone = None
    select_scatter = torch.ops.aten.select_scatter.default(t_1, mul, 0, 0);  t_1 = mul = None
    t_2 = torch.ops.aten.t.default(select_scatter);  select_scatter = None
    t_4 = torch.ops.aten.t.default(t_2)
    t_6 = torch.ops.aten.t.default(t_2);  t_2 = None
    view_1 = torch.ops.aten.view.default(t_6, [3, 3]);  t_6 = None
    return [t_4, view_1]""")

    def test_view_and_inplace_view(self):
        def f(a, b):
            a.t_()
            return b.view(b.shape), a.view(a.shape)

        def create_inp(req_grad):
            return [
                torch.ones(3, 3, requires_grad=req_grad),
                torch.ones(3, 3, requires_grad=req_grad)
            ]

        self.verify_aot_autograd(f, create_inp(False), test_mutation=True)
        fw_graph = self.verify_aot_autograd(f, create_inp(True), test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2):
    view = torch.ops.aten.view.default(primals_1, [3, 3]);  primals_1 = None
    t = torch.ops.aten.t.default(view);  view = None
    view_1 = torch.ops.aten.view.default(primals_2, [3, 3]);  primals_2 = None
    view_2 = torch.ops.aten.view.default(t, [3, 3])
    return [t, view_1, view_2]""")

    def test_view_detach(self):
        def f(a):
            tmp = a.detach()
            a.mul_(2)
            return a, tmp
        inp = [torch.ones(3, 3, requires_grad=True)]
        self.verify_aot_autograd(f, inp, test_mutation=True)
        inp = [torch.ones(3, 3, requires_grad=False)]
        self.verify_aot_autograd(f, inp, test_mutation=True)

    def test_input_inplace_requires_grad_true(self):
        def f(a, b):
            a.requires_grad_(True)
            return a.mul(3), b.mul(4)
        inp = [
            # First inp doesnt require grad, but we switch it on
            torch.ones(3, 3, requires_grad=False),
            torch.ones(3, 3, requires_grad=True),
        ]

        fw_graph = self.verify_aot_autograd(f, inp, test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2):
    mul = torch.ops.aten.mul.Tensor(primals_1, 3);  primals_1 = None
    mul_1 = torch.ops.aten.mul.Tensor(primals_2, 4);  primals_2 = None
    return [mul, mul_1]""")

    # This is a torture test:
    # a and b get turned into a synthetic base in the compiled graph
    # One gets a data mutation, the other gets a metadata mutation.
    # We need to make sure that the metadata mutation gets propagated
    # back to the original input.
    def test_input_data_and_metadata_mutation_aliases_other_input(self):
        # a and b are aliased
        def f(a, b):
            a.mul_(2)
            b.t_()
            return a.mul(b)

        def inp_callable(req_grad):
            base = torch.ones(2, 2, requires_grad=req_grad)
            # Note: in our test, the add() is important because we need the graph inputs to be non-leaves so we can mutate them.
            x = base.add(1)
            inp1 = x[0]
            inp2 = x[0]
            return [base], [inp1, inp2]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)
        self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        with self.assertRaisesRegex(RuntimeError, "Encountered aliased inputs that are mutated in the graph, but"):
            self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True, make_inputs_subclasses=True)
        with self.assertRaisesRegex(RuntimeError, "Encountered aliased inputs that are mutated in the graph, but"):
            self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True, make_inputs_subclasses=True)

    # https://github.com/pytorch/pytorch/issues/106456
    def test_input_mutation_noncontiguous(self):
        def f(a):
            a.mul_(2)
            return a + 1

        def inp_callable(req_grad):
            base = torch.ones(2, 2, requires_grad=req_grad)
            x = base.add(1)
            # create a non-contiguous view to pass as an input to the compiler
            inp = x[:, 0]
            return [base], [inp]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)
        self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        with self.assertRaisesRegex(
            RuntimeError,
            "Mutations on non-contiguous inputs are currently not allowed on tensor subclasses"
        ):
            self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True, make_inputs_subclasses=True)
        with self.assertRaisesRegex(
            RuntimeError,
            "Mutations on non-contiguous inputs are currently not allowed on tensor subclasses"
        ):
            self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True, make_inputs_subclasses=True)

    # Mutations in the backward are allowed as long as the mutated object does not require grad
    def test_backward_mutation_data(self):
        class BwMutation(torch.autograd.Function):
            @staticmethod
            def forward(ctx, x):
                ctx.save_for_backward(x)
                return x.clone()

            @staticmethod
            def backward(ctx, grad_output):
                x, = ctx.saved_tensors
                # bw mutation
                x.mul_(2)
                return grad_output.clone()

        def f(a, b):
            out = BwMutation.apply(b)
            return a * out

        inp_no_grad = [
            torch.ones(3, 3, requires_grad=True),
            torch.ones(3, 3, requires_grad=False),
        ]

        # Mutation on buffer that does not require grad during the backward is allowed
        self.verify_aot_autograd(f, inp_no_grad, test_mutation=True)

        inp_grad = [
            torch.ones(3, 3, requires_grad=True),
            torch.ones(3, 3, requires_grad=True),
        ]
        with self.assertRaisesRegex(AssertionError, "input that requires_grad and was mutated in the backward"):
            self.verify_aot_autograd(f, inp_grad, test_mutation=True)

    def test_backward_mutation_metadata(self):
        class BwMutation(torch.autograd.Function):
            @staticmethod
            def forward(ctx, a, b):
                ctx.save_for_backward(b)
                return a.clone(), b.clone()

            @staticmethod
            def backward(ctx, grad_a, grad_b):
                b, = ctx.saved_tensors
                # bw metadata mutation
                b.transpose_(1, 0)
                return grad_a.clone(), grad_b.clone()

        def f(a, b):
            a_, b_ = BwMutation.apply(a, b)
            out = a_ * b_
            return out

        inp_no_grad = [
            torch.ones(3, 3, requires_grad=True),
            torch.ones(3, 3, requires_grad=False),
        ]

        with self.assertRaisesRegex(AssertionError, "input that had its metadata mutated in the backward"):
            self.verify_aot_autograd(f, inp_no_grad, test_mutation=True)

    def test_backward_mutation_on_grad_out(self):
        class BwMutation(torch.autograd.Function):
            @staticmethod
            def forward(ctx, x):
                return x.clone()

            @staticmethod
            def backward(ctx, grad_output):
                grad_output.mul_(2)
                return grad_output.clone()

        def f(a, b):
            tmp = a * b
            out = BwMutation.apply(tmp)
            return out

        inp_grad = [
            torch.ones(3, 3, requires_grad=True),
            torch.ones(3, 3, requires_grad=True),
        ]
        f_compiled = aot_function(f, nop)
        with self.assertRaisesRegex(AssertionError, "input to the backward that was mutated during the backward"):
            out = f_compiled(*inp_grad)

    # Partially addresses https://github.com/pytorch/pytorch/issues/106457
    def test_input_mutation_false_aliasing(self):
        def f(a, b):
            a.mul_(3)
            b.mul_(2)
            return a.clone().view(-1) + b.clone().view(-1)

        # No overlap, contiguous
        def inp_callable1(req_grad):
            base = torch.ones(4, 4, requires_grad=req_grad)
            x = base.add(1)
            # create two views that share storage, but are actually non-overlapping
            a = x[0:2]
            b = x[2:4]
            return [base], [a, b]

        fw_graph = self.verify_aot_autograd(f, partial(inp_callable1, req_grad=False), test_mutation=True)
        self.verify_aot_autograd(f, partial(inp_callable1, req_grad=True), test_mutation=True)
        self.verify_aot_autograd(f, partial(inp_callable1, req_grad=False), test_mutation=True, make_inputs_subclasses=True)
        # Input mutations on subclasses with training graphs fail backward guards today.
        with self.assertRaisesRegex(AssertionError, "attempted to compile the backward with incorrect subclass metadata"):
            self.verify_aot_autograd(f, partial(inp_callable1, req_grad=True), test_mutation=True, make_inputs_subclasses=True)

        # Important characteristic: the graph takes in 2 inputs!
        # That shows that we didn't try to run our complicated synthetic base logic,
        # because we successfully detected false aliasing across the two inputs.
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, arg0_1, arg1_1):
    mul = torch.ops.aten.mul.Tensor(arg0_1, 3);  arg0_1 = None
    mul_1 = torch.ops.aten.mul.Tensor(arg1_1, 2);  arg1_1 = None
    clone = torch.ops.aten.clone.default(mul)
    view = torch.ops.aten.view.default(clone, [-1]);  clone = None
    clone_1 = torch.ops.aten.clone.default(mul_1)
    view_1 = torch.ops.aten.view.default(clone_1, [-1]);  clone_1 = None
    add = torch.ops.aten.add.Tensor(view, view_1);  view = view_1 = None
    return (mul, mul_1, add)""")

        # No overlap, non-contiguous: first tensor ends before second tensor start
        def inp_callable2(req_grad):
            base = torch.ones(256, requires_grad=req_grad)
            x = base.add(1)
            a = x.as_strided((4, 4), (8, 1), storage_offset=0)
            b = x.as_strided((4, 4), (8, 1), storage_offset=28)
            return [base], [a, b]

        # No overlap, non-contiguous: tensors are perfectly interleaved
        def inp_callable3(req_grad):
            base = torch.ones(4, 4, requires_grad=req_grad)
            x = base.add(1)
            a = x[:, 0:2]
            b = x[:, 2:4]
            return [base], [a, b]

        # No overlap, non-contiguous
        def inp_callable4(req_grad):
            base = torch.ones(256, requires_grad=req_grad)
            x = base.add(1)
            a = x.as_strided((4, 4), (9, 1), storage_offset=0)
            b = x.as_strided((4, 4), (9, 1), storage_offset=22)
            return [base], [a, b]

        # No overlap, non-contiguous
        def inp_callable5(req_grad):
            base = torch.ones(256, requires_grad=req_grad)
            x = base.add(1)
            a = x.as_strided((4, 4), (9, 1), storage_offset=0)
            b = x.as_strided((4, 4), (9, 1), storage_offset=23)
            return [base], [a, b]

        # No overlap, non-contiguous
        def inp_callable6(req_grad):
            base = torch.ones(256, requires_grad=req_grad)
            x = base.add(1)
            # a's last element is at offset 195 (24 total elements)
            a = x.as_strided((2, 4, 3), (110, 24, 4), storage_offset=5)
            # b's first element is at offset 196: no overlap
            b = x[196:196 + a.numel()]
            return [base], [a, b]

        # overlap! non-contiguous
        def inp_callable_overlap1(req_grad):
            base = torch.ones(256, requires_grad=req_grad)
            x = base.add(1)
            a = x.as_strided((4, 4), (9, 1), storage_offset=0)
            b = x.as_strided((4, 4), (9, 1), storage_offset=24)
            return [base], [a, b]

        # overlap! non-contiguous
        def inp_callable_overlap2(req_grad):
            base = torch.ones(256, requires_grad=req_grad)
            x = base.add(1)
            a = x.as_strided((4, 4), (9, 1), storage_offset=0)
            b = x.as_strided((4, 4), (9, 1), storage_offset=25)
            return [base], [a, b]

        # overlap! non-contiguous
        def inp_callable_overlap3(req_grad):
            base = torch.ones(256, requires_grad=req_grad)
            x = base.add(1)
            # a's last element is at offset 195 (24 total elements)
            a = x.as_strided((2, 4, 3), (110, 24, 4), storage_offset=5)
            # b's first element is at offset 195: overlap!
            b = x[195:195 + a.numel()]
            return [base], [a, b]

        fw_graph2 = self.verify_aot_autograd(f, partial(inp_callable2, req_grad=False), test_mutation=True)
        fw_graph3 = self.verify_aot_autograd(f, partial(inp_callable3, req_grad=False), test_mutation=True)
        fw_graph4 = self.verify_aot_autograd(f, partial(inp_callable4, req_grad=False), test_mutation=True)
        fw_graph5 = self.verify_aot_autograd(f, partial(inp_callable5, req_grad=False), test_mutation=True)
        fw_graph6 = self.verify_aot_autograd(f, partial(inp_callable6, req_grad=False), test_mutation=True)

        fw_graph_overlap1 = self.verify_aot_autograd(f, partial(inp_callable_overlap2, req_grad=False), test_mutation=True)
        fw_graph_overlap2 = self.verify_aot_autograd(f, partial(inp_callable_overlap1, req_grad=False), test_mutation=True)

        # All non-overlap graphs should be the same since we detected false aliasing
        self.assertEqual(str(fw_graph.code), str(fw_graph2.code))
        self.assertEqual(str(fw_graph.code), str(fw_graph3.code))
        self.assertEqual(str(fw_graph.code), str(fw_graph4.code))
        self.assertEqual(str(fw_graph.code), str(fw_graph5.code))
        self.assertEqual(str(fw_graph.code), str(fw_graph6.code))

        # All overlap graphs should be the same since we detected real aliasing
        self.assertNotEqual(str(fw_graph.code), str(fw_graph_overlap1.code))
        self.assertNotEqual(str(fw_graph.code), str(fw_graph_overlap2.code))
        self.assertTrue('as_strided_scatter' in str(fw_graph_overlap1.code))
        self.assertTrue('as_strided_scatter' in str(fw_graph_overlap2.code))


    @unittest.skipIf(not torch.cuda.is_available(), "CUDA is unavailable")
    def test_mem_leak_from_save_for_bw(self):
        # See a full diagnosis at this issue: https://github.com/pytorch/pytorch/issues/94990
        # Note [Detaching saved tensors in AOTAutograd]
        # This program creates a ref-cycle. Long term, we should fix this ref cycle
        # (since it can arise, naturally albeit rarely, from uses of autograd.Function).
        # But AOTAutograd makes it more likely to show up from tracing user programs,
        # so we deal with it by manually detaching the tensors that we save for backward.
        # This is completely wrong and would give wrong results if we were to do double backward.
        # Fortunately today, double backward is explicitly banned in AOTAutograd.
        def f(a, b):
            add = a + a
            split = torch.functional.split(add, [4, 4], dim=1)
            getitem_2 = split[1]
            unsqueeze = getitem_2.unsqueeze(-1)
            mul = unsqueeze * b
            return (getitem_2, mul)

        f_compiled = aot_function(f, nop)
        inps = [
            torch.ones(8, 8, device='cuda', requires_grad=True),
            torch.ones(1, 4, 1, device='cuda', requires_grad=True),
        ]
        mem_before = torch.cuda.memory_allocated()
        f_compiled(*inps)
        mem_after = torch.cuda.memory_allocated()
        self.assertTrue(mem_after == mem_before)

    def test_output_aliases_multiple_inputs_get_correct_one(self):
        # a and b are aliased, but have different shapes
        # The first output should view off the first input, the 2nd output should view off the 2nd input
        def f(a, b):
            return a.view(a.shape), b.view(b.shape)

        def inp_callable(req_grad):
            base = torch.ones(2, 2, requires_grad=req_grad)
            # Note: in our test, the add() is important because we need the graph inputs to be non-leaves so we can mutate them.
            x = base.mul(2)
            inp1 = x.view(-1)
            inp2 = x[0]
            return [base], [inp1, inp2]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)
        self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True, make_inputs_subclasses=True)
        self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True, make_inputs_subclasses=True)

    def test_input_mutation_aliases_other_input(self):
        def f(a, b):
            a.add_(1)
            return a + b

        def inp_callable(req_grad):
            base = torch.ones(4, 2, requires_grad=req_grad)
            # Note: in our test, the add() is important because we need the graph inputs to be non-leaves so we can mutate them.
            x = base.add(1)
            inp1 = x[0]
            inp2 = x[0]
            return [base], [inp1, inp2]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)
        fw_graph = self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        # Important parts of the graph:
        # - the compiled graph takes in a base, and we generate a and b (the views) off of the base
        # - clone() is still in the graph, because we need to call grad() on the original (non-mutated) inputs
        # - We re-generate the views *after* the clone, to preserve view relationships.
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    as_strided = torch.ops.aten.as_strided.default(clone, [2], [1], 0)
    add = torch.ops.aten.add.Tensor(as_strided, 1);  as_strided = None
    as_strided_scatter = torch.ops.aten.as_strided_scatter.default(clone, add, [2], [1], 0);  clone = add = None
    as_strided_2 = torch.ops.aten.as_strided.default(as_strided_scatter, [2], [1], 0)
    as_strided_5 = torch.ops.aten.as_strided.default(as_strided_scatter, [2], [1], 0)
    add_1 = torch.ops.aten.add.Tensor(as_strided_2, as_strided_5);  as_strided_2 = as_strided_5 = None
    return [as_strided_scatter, add_1]""")  # noqa: B950

    def test_input_mutation_aliases_other_input2(self):
        def f(a, b):
            a.add_(1)
            return a + b

        def inp_callable(req_grad):
            base = torch.ones(2, 2, requires_grad=req_grad)
            x = base.add(1)
            inp1 = x[0]
            # Here, one of the aliased inputs is the base itself
            inp2 = x
            return [base], [inp1, inp2]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)
        fw_graph = self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    as_strided = torch.ops.aten.as_strided.default(clone, [2], [1], 0)
    add = torch.ops.aten.add.Tensor(as_strided, 1);  as_strided = None
    as_strided_scatter = torch.ops.aten.as_strided_scatter.default(clone, add, [2], [1], 0);  clone = add = None
    as_strided_2 = torch.ops.aten.as_strided.default(as_strided_scatter, [2], [1], 0)
    as_strided_5 = torch.ops.aten.as_strided.default(as_strided_scatter, [2, 2], [2, 1], 0)
    add_1 = torch.ops.aten.add.Tensor(as_strided_2, as_strided_5);  as_strided_2 = as_strided_5 = None
    return [as_strided_scatter, add_1]""")  # noqa: B950

    def test_input_mutation_aliases_and_output_alias(self):
        def f(a, b):
            # Here, we need to take care:that because and b are aliased
            # since a and b are aliased, we generate a view off of "updated b"
            a.add_(1)
            return b.view(b.shape)

        def inp_callable(req_grad):
            base = torch.ones(2, 2, requires_grad=req_grad)
            x = base.add(1)
            return [base], [x.view(-1), x.view(-1)]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)
        fw_graph = self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    as_strided = torch.ops.aten.as_strided.default(clone, [4], [1], 0)
    add = torch.ops.aten.add.Tensor(as_strided, 1);  as_strided = None
    as_strided_scatter = torch.ops.aten.as_strided_scatter.default(clone, add, [4], [1], 0);  clone = add = None
    as_strided_8 = torch.ops.aten.as_strided.default(as_strided_scatter, [4], [1], 0)
    view_1 = torch.ops.aten.view.default(as_strided_8, [4]);  as_strided_8 = None
    return [as_strided_scatter, view_1]""")  # noqa: B950

    def test_input_aliased_with_mutation_output_alias(self):
        def f(a, b, c):
            # a and c alias
            c.mul_(2)
            # The main thing we're testing here is that
            # (1) We need to reconstruct c.view(-1) from the 3rd input to the forward
            # (2) But we need to be careful to do this *before* converting aliased inputs into synthetic bases.
            #     The original fw takes in 3 args, but the compiled fw takes in only 2 args.
            return b.add(1), c.view(-1)

        def inp_callable(req_grad):
            base1 = torch.ones(2, 2, requires_grad=req_grad)
            base2 = torch.ones(2, 2, requires_grad=req_grad)
            x = base1.add(1)
            y = base2.add(1)
            return [base1, base2], [x.view(-1), y, x.view(-1)]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)
        fw_graph = self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    as_strided_1 = torch.ops.aten.as_strided.default(clone, [4], [1], 0)
    mul = torch.ops.aten.mul.Tensor(as_strided_1, 2);  as_strided_1 = None
    as_strided_scatter = torch.ops.aten.as_strided_scatter.default(clone, mul, [4], [1], 0);  clone = mul = None
    add = torch.ops.aten.add.Tensor(primals_2, 1);  primals_2 = None
    as_strided_7 = torch.ops.aten.as_strided.default(as_strided_scatter, [4], [1], 0)
    view_1 = torch.ops.aten.view.default(as_strided_7, [-1]);  as_strided_7 = None
    return [as_strided_scatter, add, view_1]""")  # noqa: B950

    def test_input_metadata_mutation_aliases(self):
        def f(a, b):
            # a and b alias, and we do a metadata mutation on a
            # Since we're not mutating data, then b isn't affected at all.
            # We expect aot autograd to not bother with constructing a synthetic base.
            a.t_()
            return a + b

        def inp_callable(req_grad):
            base = torch.ones(2, 2, requires_grad=req_grad)
            x = base.add(1)
            return [base], [x.view(-1), x.view(-1)]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)
        fw_graph = self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        # Expectation: fwd() takes in 2 args, and we don't construct a synthetic base.
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2):
    t = torch.ops.aten.t.default(primals_1);  primals_1 = None
    add = torch.ops.aten.add.Tensor(t, primals_2);  t = primals_2 = None
    return [add]""")

    def test_input_mutation_aliases_and_none_require_gradients(self):
        def f(a, b, c):
            # a and b alias, but neither require gradients (so they don't have a _base)
            # aot autograd should construct the synthetic base from `torch.Tensor(a.storage())`
            a.mul_(2)
            return b + 1, c + 1

        def inp_callable(req_grad):
            base = torch.ones(2, 2)
            c_arg = torch.ones(2, 2, requires_grad=req_grad)
            x = base.add(1)
            return [base, c_arg], [x.view(-1), x.view(-1), c_arg]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)

        with self.assertRaisesRegex(RuntimeError, "is a tensor subclass. This is not supported today"):
            self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True, make_inputs_subclasses=True)

        fw_graph = self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2):
    as_strided = torch.ops.aten.as_strided.default(primals_1, [4], [1], 0)
    mul = torch.ops.aten.mul.Tensor(as_strided, 2);  as_strided = None
    as_strided_scatter = torch.ops.aten.as_strided_scatter.default(primals_1, mul, [4], [1], 0);  primals_1 = mul = None
    as_strided_3 = torch.ops.aten.as_strided.default(as_strided_scatter, [4], [1], 0)
    add = torch.ops.aten.add.Tensor(as_strided_3, 1);  as_strided_3 = None
    add_1 = torch.ops.aten.add.Tensor(primals_2, 1);  primals_2 = None
    return [as_strided_scatter, add, add_1]""")  # noqa: B950

    def test_input_mutation_aliases_bases_out_of_order(self):
        # This tests our calling convention: if b and d are aliased, then the outer calling convention
        # that we send to the compiled forward becomes:
        # (b_d_base, a, c)
        # Importantly, even though a and c alias in our test, neither inputs are mutated,
        # So we don't need to do the base construction / deconstruction
        def f(a, b, c, d):
            b.add_(1)
            d.unsqueeze_(0)
            return a + c + d, b.view(-1)

        def inp_callable(req_grad):
            base1 = torch.ones(2, 2, requires_grad=req_grad)
            base2 = torch.ones(2, 2, requires_grad=req_grad)
            x1 = base1.add(1)
            x2 = base2.add(1)
            # a and c alias, b and d alias
            return [base1, base2], [x1.view(-1), x2.view(-1), x1.view(-1), x2.view(-1)]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)

        with self.assertRaisesRegex(RuntimeError, "Metadata mutations are currently not allowed on tensor subclasses"):
            self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True, make_inputs_subclasses=True)

        fw_graph = self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        # 3 graph inputs: (b_d_base, a, c)
        # 2 returns: (b_updated, a+c+d)
        # (there are 2 original fw outs, but one is a view of b so it's not part of the graph)
        # (there are also 2 input mutations, but one is a metadata-only mutation so the compiled forward doesn't return it)
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2, primals_3):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    as_strided = torch.ops.aten.as_strided.default(clone, [4], [1], 0)
    add = torch.ops.aten.add.Tensor(as_strided, 1);  as_strided = None
    as_strided_scatter = torch.ops.aten.as_strided_scatter.default(clone, add, [4], [1], 0);  clone = add = None
    add_1 = torch.ops.aten.add.Tensor(primals_2, primals_3);  primals_2 = primals_3 = None
    as_strided_5 = torch.ops.aten.as_strided.default(as_strided_scatter, [4], [1], 0)
    unsqueeze_1 = torch.ops.aten.unsqueeze.default(as_strided_5, 0);  as_strided_5 = None
    add_2 = torch.ops.aten.add.Tensor(add_1, unsqueeze_1);  add_1 = None
    as_strided_14 = torch.ops.aten.as_strided.default(as_strided_scatter, [4], [1], 0)
    view_2 = torch.ops.aten.view.default(as_strided_14, [-1]);  as_strided_14 = None
    return [as_strided_scatter, add_2, view_2, unsqueeze_1]""")  # noqa: B950

    @unittest.skipIf(not torch.cuda.is_available(), "CUDA is unavailable")
    def test_synthetic_base_base_attribute_is_none(self):
        def f(a, b):
            a.add_(1)
            return a + b

        def inp_callable():
            base = torch.ones(4, 4, device='cuda')
            # detach() so that none of the inputs have a ._base attribute.
            a = base[0].detach()
            b = base[1].detach()
            base2 = torch.ones(2, 2, requires_grad=True)
            return [base], [a, b]

        self.verify_aot_autograd(f, inp_callable, test_mutation=True)


    def test_input_mutation_alias_everything(self):
        # Mondo test that tests a combination of:
        # input is mutated, that aliases another input (so we make a synthetic base)
        # an output is an alias of another output
        # an output is an alias of an intermediate
        # a and c are aliased
        def f(a, b, c):
            c.mul_(2)  # mutates c
            b.t_()  # metadata mutate b
            tmp = a + c
            out1 = tmp.view(-1)
            out2 = b.t()
            out3 = out1.unsqueeze(0)
            # out1 and out3 are aliases of an intermediate, and alias each other!
            # out2 aliases an input, so we don't return it
            return out1, out2, out3

        def inp_callable(req_grad):
            base1 = torch.ones(2, 2, requires_grad=req_grad)
            base2 = torch.ones(2, 2, requires_grad=req_grad)
            # Note: in our test, the add() is important because we need the graph inputs to be non-leaves so we can mutate them.
            base1_ = base1.add(1)
            base2_ = base2.add(1)
            a = base1_.view(-1)
            b = base2_
            c = base1_.view(-1)
            return [base1, base2], [a, b, c]

        self.verify_aot_autograd(f, partial(inp_callable, req_grad=False), test_mutation=True)
        fw_graph = self.verify_aot_autograd(f, partial(inp_callable, req_grad=True), test_mutation=True)
        # Expected:
        # - 2 inputs in the forward: synthetic_base_a_c, b
        # - 1 output in the forward: "tmp"
        #   out2 is an alias of an input, and will be generated off of b outside of the compiled fn
        #   out1 and out3 are aliases of tmp, that we generate outside of the compiled function
        self.assertExpectedInline(fw_graph.code.strip(), """\
def forward(self, primals_1, primals_2):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    view = torch.ops.aten.view.default(primals_2, [2, 2]);  primals_2 = None
    as_strided_1 = torch.ops.aten.as_strided.default(clone, [4], [1], 0)
    mul = torch.ops.aten.mul.Tensor(as_strided_1, 2);  as_strided_1 = None
    as_strided_scatter = torch.ops.aten.as_strided_scatter.default(clone, mul, [4], [1], 0);  clone = mul = None
    as_strided_2 = torch.ops.aten.as_strided.default(as_strided_scatter, [4], [1], 0)
    t = torch.ops.aten.t.default(view);  view = None
    as_strided_5 = torch.ops.aten.as_strided.default(as_strided_scatter, [4], [1], 0)
    add = torch.ops.aten.add.Tensor(as_strided_5, as_strided_2);  as_strided_5 = as_strided_2 = None
    view_1 = torch.ops.aten.view.default(add, [-1])
    t_1 = torch.ops.aten.t.default(t)
    unsqueeze = torch.ops.aten.unsqueeze.default(view_1, 0)
    return [as_strided_scatter, t, view_1, t_1, unsqueeze, add]""")  # noqa: B950

    def test_dynamic_shape_output_not_in_bw_graph(self):
        def f(x):
            return [x + 1, x.shape[0]]
        inp = torch.ones(5, requires_grad=True)
        bw_graph_cell = [None]
        compiled_f = aot_function(
            f,
            fw_compiler=nop,
            bw_compiler=partial(extract_graph, graph_cell=bw_graph_cell),
            decompositions={},
            keep_inference_input_mutations=False,
            dynamic=True,
        )
        out = compiled_f(inp)
        out[0].sum().backward()
        # The important bit: the forward fn returns 2 outputs,
        # but one of them is a symint so we should only see
        # 1 grad_output as an input to the backward graph.
        # (Otherwise, autograd will plumb a None as the value of the grad_output,
        # which causes inductor to complain).
        self.assertExpectedInline(bw_graph_cell[0].code.strip(), """\
def forward(self, tangents_1):
    return [tangents_1]""")

    def test_no_grad_input_output(self):
        def f(a, b):
            return a.cos(), b.cos(), a * b

        inp_thunks = [lambda: torch.randn(5, requires_grad=True), lambda: torch.randn(5, requires_grad=False)]
        for inps in itertools.product(inp_thunks, repeat=2):
            inps = [i() for i in inps]
            self.verify_aot_autograd(f, inps)

    def test_some_output_requires_grad_input_doesnt(self):
        def f(a, b):
            a_view = a.view(-1)
            a_view.requires_grad_(True)
            return a_view
        inp = [torch.randn(3, 3), torch.randn(3, 3, requires_grad=True)]
        self.verify_aot_autograd(f, inp)

    def test_some_outputs_dont_require_grad_view(self):
        def f(a, b):
            return a.detach(), b
        inp = [torch.randn(3, 3, requires_grad=True), torch.randn(3, 3, requires_grad=True)]
        self.verify_aot_autograd(f, inp)

    def test_some_outputs_dont_require_grad_non_view(self):
        def f(a, b):
            return a.add(1).detach(), b
        inp = [torch.randn(3, 3, requires_grad=True), torch.randn(3, 3, requires_grad=True)]
        self.verify_aot_autograd(f, inp)

    def test_inner_grad(self):
        def foo(x):
            y = torch.exp(x)
            z = torch.autograd.grad(y, x)
            return z
        inps = [torch.randn((), requires_grad=True)]
        self.verify_aot_autograd(foo, inps)

    def test_grad_context(self):
        def foo(x):
            return x * 2
        inps = [torch.randn((), requires_grad=True)]
        graph_size = None

        def get_graph_size(fx_g, _):
            nonlocal graph_size
            graph_size = len(fx_g.graph.nodes)
            return fx_g

        f = aot_function(foo, nop, get_graph_size)
        with torch.set_grad_enabled(False):
            f(*inps)
        self.assertIsNone(graph_size)

        f = aot_function(foo, nop, get_graph_size)
        with torch.set_grad_enabled(True):
            out = f(*inps)
            self.assertIsNone(graph_size)
            out.sum().backward()
            self.assertTrue(graph_size > 2)

    def test_output_dict(self):
        def f(x):
            return {'a': x, 'b': x}
        inp = [torch.randn(3, 3, requires_grad=True)]
        self.verify_aot_autograd(f, inp)

        def f(x, y):
            return {'a': x, 'b': y + x}
        inp = [torch.randn(3, requires_grad=True), torch.randn(3)]
        self.verify_aot_autograd(f, inp)

        def f(x):
            new_d = {}
            for k in x:
                new_d[k] = x[k] * 2
            return new_d

        a = torch.randn(3, requires_grad=True)
        b = torch.randn(3, requires_grad=True)

        def inp_callable():
            inps = [{'a': a, 'b': b}]
            return inps, inps

        self.verify_aot_autograd(f, inp_callable)

    def test_module(self):
        mod = nn.Sequential(nn.Linear(32, 32), nn.ReLU())
        compiled_mod = compiled_module(mod, nop, nop)
        inp = torch.randn(32, 32)
        ref_out = mod(inp)
        ref_out.sum().backward()
        ref_grads = sorted([(name, p.grad) for name, p in mod.named_parameters()])
        out = compiled_mod(inp)
        out.sum().backward()
        grads = sorted([(name, p.grad) for name, p in mod.named_parameters()])
        self.assertEqual((out, grads), (ref_out, ref_grads))

    def test_batchnorm(self):
        mod = compiled_module(nn.BatchNorm2d(4), nop, nop)
        x = torch.ones(1, 4, 2, 2)
        mod(x).sum().backward()

    def test_list_codegen(self):
        def list_nop(f, _):
            def g(inps):
                return f(*inps)
            g._boxed_call = True
            return g

        def f(a, b, c):
            return a.sin() * b.cos() * c.sin()
        f = aot_function(f, list_nop)
        inp = [torch.randn(5, requires_grad=True) for _ in range(3)]
        f(*inp).sum().backward()

    @patch('torch._functorch.aot_autograd.AOT_COUNTER', new_callable=itertools.count)
    def test_compilation_context(self, counter):
        def f(x):
            return x.sin().sin()
        count = []

        def compiler(fx_g, _):
            context = get_aot_compilation_context()
            count.append((context[0], len(fx_g.graph.nodes)))
            return fx_g

        f = aot_function(f, compiler)
        out = f(torch.randn(5, requires_grad=True))
        f = aot_function(f, compiler)
        f(torch.randn(5))
        out.sum().backward()
        self.assertExpectedInline(str(count), """[(['0_forward'], 4), (['1_inference'], 4), (['0_backward'], 8)]""")

    def test_dupe_arg(self):
        def f(x, y):
            return x + y

        x = torch.randn(3, 3, requires_grad=True)
        self.verify_aot_autograd(f, [x, x])

    def test_dupe_arg_torture(self):
        def f(x, y):
            x.t_()
            y.unsqueeze_(0)
            return x + y

        x = torch.randn(3, 3, requires_grad=True).clone()
        self.verify_aot_autograd(f, [x, x])

    # See https://github.com/pytorch/pytorch/issues/100224
    def test_dupe_arg_returned_as_output(self):
        def f(a, b, a_):
            a[0].add_(1)
            return a_
        f_compiled = aot_function(f, nop)
        a = torch.ones(2)
        b = torch.ones(2)
        out_ref = f(a, b, a)

        a2 = torch.ones(2)
        b2 = torch.ones(2)
        out_test = f_compiled(a2, b2, a2)

        self.assertEqual(out_ref, out_test)
        self.assertEqual(a, a2)

    @patch('torch._functorch.aot_autograd.AOT_COUNTER', new_callable=itertools.count)
    @patch("torch._functorch.config.debug_assert", True)
    def test_invalid_dupe_left_bias(self, counter):
        # This test checks that, just because only the first
        # argument did a metadata mutation, we still correctly
        # switch to strategy 2 (deduplicate)
        # See: https://github.com/pytorch/pytorch/pull/89896#discussion_r1036224447
        class F(torch.nn.Module):
            def forward(self, x, y):
                x.t_()
                return (x + y,)

        x = torch.randn(3, 3, requires_grad=True).clone()
        y = torch.randn(3, 3, requires_grad=True)
        self.verify_aot_autograd(F(), [x, x])

        fxx = aot_module_simplified(F(), (x, x), nop)
        self.assertExpectedRaisesInline(
            AssertionError, lambda: fxx(x, y),
            """At compilation time, graph 2 was compiled under the assumption that input 1 would be a duplicate of input 0, but at runtime this was not the case.  This indicates a guard bug in AOTAutograd or Dynamo, please file a bug to PyTorch."""  # noqa: B950
        )


    @patch('torch._functorch.aot_autograd.AOT_COUNTER', new_callable=itertools.count)
    @patch("torch._functorch.config.debug_assert", True)
    def test_invalid_dupe(self, counter):
        self._test_invalid_dupe(counter, fake=False)

    # See Note: Dynamo recompilation guarding invalid grad for why this test exists
    @patch('torch._functorch.aot_autograd.AOT_COUNTER', new_callable=itertools.count)
    @patch("torch._functorch.config.debug_assert", True)
    def test_invalid_dupe_fake(self, counter):
        self._test_invalid_dupe(counter, fake=True)


    def _test_invalid_dupe(self, counter, fake):
        class F(torch.nn.Module):
            def forward(self, x, y):
                x.unsqueeze_(0)
                y.unsqueeze_(0)
                return (x + y,)

        x = torch.randn(3, 3, requires_grad=True).clone()
        y = torch.randn(3, 3, requires_grad=True).clone()

        if fake:
            shape_env = ShapeEnv()
            fake_mode = FakeTensorMode(shape_env=shape_env)

            fake_x = fake_mode.from_tensor(x)
            fake_y = fake_mode.from_tensor(y)

        if fake:
            fxy = aot_module_simplified(F(), (fake_x, fake_y), nop)
        else:
            fxy = aot_module_simplified(F(), (x, y), nop)

        fxy(x, y)
        x = torch.randn(3, 3, requires_grad=True).clone()
        y = torch.randn(3, 3, requires_grad=True).clone()
        fxy(x, x)  # is ok!

        if fake:
            fxx = aot_module_simplified(F(), (fake_x, fake_x), nop)
        else:
            fxx = aot_module_simplified(F(), (x, x), nop)

        x = torch.randn(3, 3, requires_grad=True).clone()
        y = torch.randn(3, 3, requires_grad=True).clone()
        fxx(x, x)
        # Note This should not raise! Once we have guards in place here,
        # we will have this working correctly, as it should recompile.
        x = torch.randn(3, 3, requires_grad=True).clone()
        y = torch.randn(3, 3, requires_grad=True).clone()
        self.assertExpectedRaisesInline(
            AssertionError, lambda: fxx(x, y),
            """At compilation time, graph 1 was compiled under the assumption that input 1 would be a duplicate of input 0, but at runtime this was not the case.  This indicates a guard bug in AOTAutograd or Dynamo, please file a bug to PyTorch."""  # noqa: B950
        )


    @patch('torch._functorch.aot_autograd.AOT_COUNTER', new_callable=itertools.count)
    @patch("torch._functorch.config.debug_assert", True)
    def test_invalid_requires_grad(self, counter):
        self._test_invalid_requires_grad(counter, fake=False)

    # See Note: Dynamo recompilation guarding invalid grad for why this test exists
    @patch('torch._functorch.aot_autograd.AOT_COUNTER', new_callable=itertools.count)
    @patch("torch._functorch.config.debug_assert", True)
    def test_invalid_requires_grad_fake(self, counter):
        self._test_invalid_requires_grad(counter, fake=True)

    def _test_invalid_requires_grad(self, counter, fake):
        class F(torch.nn.Module):
            def forward(self, x, y):
                return (x + y,)

        x = torch.randn(3, 3, requires_grad=True)
        y = torch.randn(3, 3, requires_grad=True)
        z = torch.randn(3, 3, requires_grad=False)

        if fake:
            shape_env = ShapeEnv()
            fake_mode = FakeTensorMode(shape_env=shape_env)

            fake_x = fake_mode.from_tensor(x)
            fake_y = fake_mode.from_tensor(y)
            fake_z = fake_mode.from_tensor(z)

        if fake:
            fxy = aot_module_simplified(F(), (fake_x, fake_y), nop)
        else:
            fxy = aot_module_simplified(F(), (x, y), nop)

        compare_equal_outs_and_grads(self, F(), fxy, (x, y))
        compare_equal_outs_and_grads(self, F(), fxy, (x, z))

        if fake:
            fxz = aot_module_simplified(F(), (fake_x, fake_z), nop)
        else:
            fxz = aot_module_simplified(F(), (x, z), nop)

        compare_equal_outs_and_grads(self, F(), fxz, (x, z))

        self.assertExpectedRaisesInline(
            AssertionError, lambda: fxz(x, y),
            """At compilation time, graph 1 was compiled under the assumption that input 1 would not require grad, but at runtime this was not the case.  This indicates a guard bug in AOTAutograd or Dynamo, please file a bug to PyTorch."""  # noqa: B950
        )

    def test_custom_autograd(self):
        class CustomFn(torch.autograd.Function):
            @staticmethod
            def forward(ctx, x):
                return x.clone()

            @staticmethod
            def backward(ctx, grad_output):
                return grad_output + 1

        def f(x):
            return CustomFn.apply(x)

        self.verify_aot_autograd(f, [torch.randn(3)])

    @unittest.skipIf(not torch.cuda.is_available(), "CUDA is unavailable")
    def test_autocast_disable_guard(self):
        with torch._C._DisableAutocast():
            x = torch.rand([4, 4]).cuda()
            y = x @ x
            self.assertEqual(y.dtype, torch.float32)

    @unittest.skipIf(not torch.cuda.is_available(), "CUDA is unavailable")
    def test_nonidempotent_amp(self):
        def f(self_s_emb, add_3):
            einsum_2 = torch.functional.einsum('ah,th->t', self_s_emb, add_3)
            log_softmax_2 = einsum_2.log_softmax(-1)
            return (log_softmax_2,)

        args = [torch.rand((1, 256), dtype=torch.float32, device='cuda'), torch.rand((30, 256), dtype=torch.float16, device='cuda')]
        with torch.cuda.amp.autocast(enabled=True):
            self.verify_aot_autograd(f, args)

        args = [e.requires_grad_(True) for e in args]
        with torch.cuda.amp.autocast(enabled=True):
            self.verify_aot_autograd(f, args)

    @unittest.skipIf(not torch.cuda.is_available(), "CUDA is unavailable")
    @unittest.skipIf(not torch.backends.cudnn.is_available(), "CUDNN is unavailable")
    @skipIfRocm  # https://github.com/pytorch/pytorch/issues/96560
    def test_batch_norm_amp(self):
        device = "cuda"
        input_dtype = torch.float16
        param_dtype = torch.float32
        weight, bias = (torch.ones(64, device=device, dtype=param_dtype, requires_grad=True) for _ in range(2))
        running_mean, running_var = (torch.ones(64, device=device, dtype=param_dtype) for _ in range(2))

        def bn(x):
            return torch.ops.aten.cudnn_batch_norm(
                x,
                weight,
                bias,
                running_mean,
                running_var,
                False,
                0.1,
                1e-05,
            )
        inp = torch.ones(torch.Size([16, 64, 112, 112]), dtype=input_dtype, device=device)

        ref = bn(inp)
        cudnn_batch_norm_decomp = torch._decomp.get_decompositions({torch.ops.aten.cudnn_batch_norm})
        aot_fn = make_fx(bn, decomposition_table=cudnn_batch_norm_decomp)(inp)
        res = aot_fn(inp)
        for a, b in zip(ref, res):
            assert torch.allclose(a, b)

    def test_output_op_depending_on_symint(self):
        """
        It won't be obvious from reading this test what it's testing for.  We should probably make it into a more
        focused unit test.

        An issue with the following program was the expand op would end up depending on a symint whose proxy was
        incorrectly associated with one of the grad tensors rather than input tensors.  It broke partitioner logic
        and the net result was aot_function failed to produce a function and threw an exception instead.
        """
        inp = torch.randn(5, requires_grad=True)

        def f(x):
            return x.expand(x.shape)

        # TODO(whc) make this work (test setup is wrong somehow)
        # joint_forward_backward = create_joint_forward_backward(f)
        # out = f(inp)
        # joint_inputs =  ([inp], [out.detach().contiguous()])
        # fx_g = make_fx(joint_forward_backward)(*joint_inputs)
        # TODO: assert outputs of fwd graph trace to correct symint

        # e2e test that fails without symint clone fix
        af = aot_function(f, nop, partition_fn=partial(min_cut_rematerialization_partition, compiler="inductor"), dynamic=True)
        out = af(inp)
        self.assertEqual(out, f(inp))

    def test_inference_mode(self):
        m = torch.nn.Linear(4, 4)
        inp = torch.randn(4, 4)

        aot_mod = aot_module(m, fw_compiler=nop)

        with torch.inference_mode():
            out_ref = m(inp)
            out_test = aot_mod(inp)
        self.assertEqual(out_ref, out_test)

    def test_default_partitioner_saves_symints_not_tensors_for_bw(self):
        """
        In this test, the important thing is that primals_1 is **only** needed in the backward
        in order to grab its sizes.
        We need to assert that what we save for the backward are the tensor's sizes, and not the tensor itself.

        The way this test is set up, it will actually fail if we try to save the input tensor for backward.
        Why?
        b.masked_fill_(c, 0) has a backward that requires knowing a's sizes
        b.masked_fill_(c, 0) **also** mutates a (because b and a are aliased)
        The autograd engine yells at us if we save "a" for backward, and then try to mutate it.
        """
        inp = torch.randn(2, 2, requires_grad=True)

        def f(a):
            b = a[0]
            c = torch.ones_like(b, dtype=torch.bool)
            d = b.masked_fill_(c, 0)
            return d

        compiled_f = aot_function(f, nop, dynamic=True)
        inp_ref = torch.ones(2, 2, requires_grad=True)
        inp_test = torch.ones(2, 2, requires_grad=True)

        out_ref = f(inp_ref.clone())
        out_test = compiled_f(inp_test.clone())

        self.assertEqual(out_ref, out_test)

        out_ref.sum().backward()
        out_test.sum().backward()

        self.assertEqual(inp_ref.grad, inp_test.grad)

    def test_buffer_copied_in_graph(self):
        class MyModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.register_buffer("buf", torch.zeros(1))
                self.w1 = torch.nn.Parameter(torch.zeros(1))
                self.w2 = torch.nn.Parameter(torch.zeros(1))

            def forward(self, x):
                self.buf.add_(1)
                return (self.w1 * x * self.w2).sum() + self.buf.sum()

        model_for_eager = MyModel()
        model_for_compile = copy.deepcopy(model_for_eager)

        fw_graph_cell = [None]
        compiled_f = aot_module(
            model_for_compile,
            fw_compiler=make_boxed_compiler(partial(extract_graph, graph_cell=fw_graph_cell)),
            bw_compiler=nop,
            keep_inference_input_mutations=True,
        )
        inp_ref = torch.ones(1, requires_grad=True)
        inp_test = torch.ones(1, requires_grad=True)

        out_ref = model_for_eager(inp_ref.clone())
        out_test = compiled_f(inp_test.clone())

        self.assertExpectedInline(fw_graph_cell[0].code.strip(), """\
def forward(self, primals_1, primals_2, primals_3, primals_4):
    add = torch.ops.aten.add.Tensor(primals_3, 1)
    mul = torch.ops.aten.mul.Tensor(primals_1, primals_4)
    mul_1 = torch.ops.aten.mul.Tensor(mul, primals_2)
    sum_1 = torch.ops.aten.sum.default(mul_1);  mul_1 = None
    sum_2 = torch.ops.aten.sum.default(add)
    add_1 = torch.ops.aten.add.Tensor(sum_1, sum_2);  sum_1 = sum_2 = None
    copy_ = torch.ops.aten.copy_.default(primals_3, add);  primals_3 = add = None
    return [add_1, primals_1, primals_2, primals_4, mul]""")

        self.assertEqual(out_ref, out_test)

        out_ref.sum().backward()
        out_test.sum().backward()

        eager_grads = [p.grad for _, p in model_for_eager.named_parameters()]
        compile_grads = [p.grad for _, p in model_for_compile.named_parameters()]

        self.assertEqual(eager_grads, compile_grads)
        self.assertEqual(inp_ref.grad, inp_test.grad)

    def test_buffer_copied_in_graph_with_different_shapes(self):
        class MyModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.register_buffer("buf", torch.ones(4, 4))
                self.w = torch.nn.Parameter(torch.Tensor([[4, 5], [1, 2], [6, 7], [8, 9]]))

            def forward(self, x):
                self.buf.add_(1)
                return (self.w @ x).sum() + self.buf.sum()

        model_for_eager = MyModel()
        model_for_compile = copy.deepcopy(model_for_eager)

        fw_graph_cell = [None]
        compiled_f = aot_module(
            model_for_compile,
            fw_compiler=make_boxed_compiler(partial(extract_graph, graph_cell=fw_graph_cell)),
            bw_compiler=nop,
            keep_inference_input_mutations=True,
        )
        inp_ref = torch.ones(2, 4, requires_grad=True)
        inp_test = torch.ones(2, 4, requires_grad=True)

        out_ref = model_for_eager(inp_ref.clone())
        out_test = compiled_f(inp_test.clone())

        self.assertExpectedInline(fw_graph_cell[0].code.strip(), """\
def forward(self, primals_1, primals_2, primals_3):
    add = torch.ops.aten.add.Tensor(primals_2, 1)
    mm = torch.ops.aten.mm.default(primals_1, primals_3)
    sum_1 = torch.ops.aten.sum.default(mm);  mm = None
    sum_2 = torch.ops.aten.sum.default(add)
    add_1 = torch.ops.aten.add.Tensor(sum_1, sum_2);  sum_1 = sum_2 = None
    copy_ = torch.ops.aten.copy_.default(primals_2, add);  primals_2 = add = None
    return [add_1, primals_1, primals_3]""")
        self.assertEqual(out_ref, out_test)

        out_ref.sum().backward()
        out_test.sum().backward()

        eager_grads = [p.grad for _, p in model_for_eager.named_parameters()]
        compile_grads = [p.grad for _, p in model_for_compile.named_parameters()]

        self.assertEqual(eager_grads, compile_grads)

        self.assertEqual(inp_ref.grad, inp_test.grad)

    def test_buffer_batch_norm(self):
        class MyModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.m = torch.nn.BatchNorm1d(100)

            def forward(self, x):
                return self.m(x)

        model_for_eager = MyModel()
        model_for_compile = copy.deepcopy(model_for_eager)

        fw_graph_cell = [None]
        bw_graph_cell = [None]
        compiled_f = aot_module(
            model_for_compile,
            fw_compiler=make_boxed_compiler(partial(extract_graph, graph_cell=fw_graph_cell)),
            bw_compiler=make_boxed_compiler(partial(extract_graph, graph_cell=bw_graph_cell)),
            keep_inference_input_mutations=True,
        )
        inp_ref = torch.ones(20, 100, requires_grad=True)
        inp_test = torch.ones(20, 100, requires_grad=True)

        out_ref = model_for_eager(inp_ref.clone())
        out_test = compiled_f(inp_test.clone())

        self.assertExpectedInline(fw_graph_cell[0].code.strip(), """\
def forward(self, primals_1, primals_2, primals_3, primals_4, primals_5, primals_6):
    add = torch.ops.aten.add.Tensor(primals_5, 1)
    _native_batch_norm_legit_functional = torch.ops.aten._native_batch_norm_legit_functional.default(primals_6, primals_1, primals_2, primals_3, primals_4, True, 0.1, 1e-05);  primals_2 = None
    getitem = _native_batch_norm_legit_functional[0]
    getitem_1 = _native_batch_norm_legit_functional[1]
    getitem_2 = _native_batch_norm_legit_functional[2]
    getitem_3 = _native_batch_norm_legit_functional[3]
    getitem_4 = _native_batch_norm_legit_functional[4];  _native_batch_norm_legit_functional = None
    copy_ = torch.ops.aten.copy_.default(primals_3, getitem_3);  primals_3 = None
    copy__1 = torch.ops.aten.copy_.default(primals_4, getitem_4);  primals_4 = None
    copy__2 = torch.ops.aten.copy_.default(primals_5, add);  primals_5 = add = None
    return [getitem, primals_1, primals_6, getitem_1, getitem_2, getitem_3, getitem_4]""")  # noqa: B950

        self.assertEqual(out_ref, out_test)

        out_ref.sum().backward()
        out_test.sum().backward()

        eager_grads = [p.grad for _, p in model_for_eager.named_parameters()]
        compile_grads = [p.grad for _, p in model_for_compile.named_parameters()]
        self.assertEqual(eager_grads, compile_grads)

        self.assertExpectedInline(bw_graph_cell[0].code.strip(), """\
def forward(self, primals_1, primals_6, getitem_1, getitem_2, getitem_3, getitem_4, tangents_1):
    native_batch_norm_backward = torch.ops.aten.native_batch_norm_backward.default(tangents_1, primals_6, primals_1, getitem_3, getitem_4, getitem_1, getitem_2, True, 1e-05, [True, True, True]);  tangents_1 = primals_6 = primals_1 = getitem_3 = getitem_4 = getitem_1 = getitem_2 = None
    getitem_5 = native_batch_norm_backward[0]
    getitem_6 = native_batch_norm_backward[1]
    getitem_7 = native_batch_norm_backward[2];  native_batch_norm_backward = None
    return [getitem_6, getitem_7, None, None, None, getitem_5]""")  # noqa: B950

        self.assertEqual(inp_ref.grad, inp_test.grad)

    def test_new_inp_requires_grad_now(self):
        def f(x, y):
            return x.add_(y)

        fw_graph_cell = [None]
        bw_graph_cell = [None]
        compiled_f = aot_function(
            f,
            fw_compiler=make_boxed_compiler(partial(extract_graph, graph_cell=fw_graph_cell)),
            bw_compiler=make_boxed_compiler(partial(extract_graph, graph_cell=bw_graph_cell)),
            keep_inference_input_mutations=True,
        )

        inp_ref = (torch.ones(20, 100, requires_grad=False), torch.ones(20, 100, requires_grad=True))
        inp_test = (torch.ones(20, 100, requires_grad=False), torch.ones(20, 100, requires_grad=True))

        out_ref = f(*inp_ref)
        out_test = compiled_f(*inp_test)

        # There is no copy_ method
        self.assertExpectedInline(fw_graph_cell[0].code.strip(), """\
def forward(self, primals_1, primals_2):
    clone = torch.ops.aten.clone.default(primals_1);  primals_1 = None
    add = torch.ops.aten.add.Tensor(clone, primals_2);  clone = primals_2 = None
    return [add, add]""")  # noqa: B950

        self.assertEqual(out_ref, out_test)

        out_ref.sum().backward()
        out_test.sum().backward()

        self.assertExpectedInline(bw_graph_cell[0].code.strip(), """\
def forward(self, tangents_1):
    return [None, tangents_1]""")  # noqa: B950

    def test_real_weights_in_symbolic_mode(self):
        from functorch.experimental import functionalize

        class M(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(5, 5)

            def forward(self, x):
                x = self.linear(x)
                return x

        m = M().eval()

        inp = torch.randn(2, 5)

        gm = make_fx(m, tracing_mode="symbolic", _allow_non_fake_inputs=True)(inp)
        self.assertEqual(gm(torch.ones(2, 5)), m(torch.ones(2, 5)))

        gm_functionalized = make_fx(functionalize(gm,), tracing_mode="symbolic", _allow_non_fake_inputs=True)(inp)
        self.assertEqual(gm_functionalized(torch.ones(2, 5)), m(torch.ones(2, 5)))

        inp_count = 0
        for node in gm.graph.nodes:
            if node.op == "placeholder":
                inp_count += 1

        # No more param lifting
        self.assertEqual(inp_count, 1)

        inp_count = 0
        for node in gm_functionalized.graph.nodes:
            if node.op == "placeholder":
                inp_count += 1

        # No more param lifting
        self.assertEqual(inp_count, 1)

        with self.assertRaisesRegex(Exception, "Please convert all Tensors to FakeTensors"):
            make_fx(m, tracing_mode="symbolic", _allow_non_fake_inputs=False)(torch.randn(2, 5))

    def test_real_weights_in_symbolic_mode_with_inplace_ops(self):

        class M(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.register_buffer("buffer", torch.ones(4, 5))

            def forward(self, x):
                y = self.buffer.add_(3)
                y.resize_([20])
                assert y.shape == self.buffer.shape
                return x.sum() + self.buffer.sum()

        m = M().eval()
        inp = torch.randn(2, 5)
        # inplace mutation on attr is not allowed
        with self.assertRaisesRegex(Exception, "Can't call metadata"):
            make_fx(m, tracing_mode="symbolic", _allow_non_fake_inputs=True)(inp)


def extract_graph(fx_g, _, graph_cell):
    graph_cell[0] = fx_g
    return fx_g


def get_ins_outs(fx_g):
    ins = []
    outs = []
    for n in fx_g.graph.nodes:
        if n.op == 'placeholder':
            ins.append(n)
        elif n.op == 'output':
            outs = tuple(n.args[0])
    return ins, outs


def get_num_ins_outs(fx_g):
    return tuple(len(i) for i in get_ins_outs(fx_g))


def get_fw_bw_graph(f, inps, partitioner=min_cut_rematerialization_partition, dynamic=False):
    fw_graph_cell = [None]
    bw_graph_cell = [None]
    aot_function(f,
                 fw_compiler=partial(extract_graph, graph_cell=fw_graph_cell),
                 bw_compiler=partial(extract_graph, graph_cell=bw_graph_cell),
                 partition_fn=partitioner,
                 decompositions=default_decompositions,
                 dynamic=dynamic)(*inps).sum().backward()
    return (fw_graph_cell[0], bw_graph_cell[0])

class TestMod(torch.nn.Module):
    def __init__(self, fn):
        super().__init__()
        self.p = torch.nn.Parameter(torch.ones(2, requires_grad=True))
        self.fn = fn

    def forward(self, *args):
        return self.fn(self.p, *args)

class TestAOTExport(AOTTestCase):

    def test_aot_export_ban_dropout_mut_pre_dispatch(self):
        def fn(p, x):
            y = torch.ops.aten.dropout.default(x, 0.1, train=False)
            y.add_(1)
            return (y,)

        mod = TestMod(fn)
        inp = torch.randn(2, 2)

        with self.assertRaisesRegex(RuntimeError, "cannot mutate tensors with frozen storage"):
            aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=True)

        gm, _ = aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=False)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1):
    clone = torch.ops.aten.clone.default(arg1_1);  arg1_1 = None
    add = torch.ops.aten.add.Tensor(clone, 1);  clone = None
    return (add,)""")

        fw_graph_cell = [None]
        bw_graph_cell = [None]

        compiled_outs = aot_function(
            fn,
            fw_compiler=partial(extract_graph, graph_cell=fw_graph_cell),
            bw_compiler=partial(extract_graph, graph_cell=bw_graph_cell),
            partition_fn=default_partition,
            decompositions=default_decompositions,
            dynamic=True)(*inp)
        fw_graph = fw_graph_cell[0]
        bw_graph = bw_graph_cell[0]

        self.assertExpectedInline(str(fw_graph.code).strip(), """\
def forward(self, arg0_1, arg1_1):
    clone = torch.ops.aten.clone.default(arg1_1);  arg1_1 = None
    add = torch.ops.aten.add.Tensor(clone, 1);  clone = None
    return (add,)""")


    def test_aot_export_predispatch_func_simple(self):
        def fn(p, x):
            y = x + 2
            with torch.no_grad():
                y.add_(2)
            return (x * 2 + y,)

        mod = TestMod(fn)
        inp = torch.randn(2, 2)

        gm, _ = aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1):
    add = torch.ops.aten.add.Tensor(arg1_1, 2)
    _set_grad_enabled = torch._C._set_grad_enabled(False)
    add_1 = torch.ops.aten.add.Tensor(add, 2);  add = None
    _set_grad_enabled_1 = torch._C._set_grad_enabled(False)
    mul = torch.ops.aten.mul.Tensor(arg1_1, 2);  arg1_1 = None
    add_2 = torch.ops.aten.add.Tensor(mul, add_1);  mul = add_1 = None
    return (add_2,)""")

    def test_aot_export_predispatch_func_composite_implicit(self):
        def fn(p, x):
            with torch.enable_grad():
                y = x @ x
            y.add_(2)
            return (x.sum() + y.sum(),)

        mod = TestMod(fn)
        inp = torch.randn(2, 2)

        gm, _ = aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1):
    _set_grad_enabled = torch._C._set_grad_enabled(True)
    matmul = torch.ops.aten.matmul.default(arg1_1, arg1_1)
    _set_grad_enabled_1 = torch._C._set_grad_enabled(False)
    add = torch.ops.aten.add.Tensor(matmul, 2);  matmul = None
    sum_1 = torch.ops.aten.sum.default(arg1_1);  arg1_1 = None
    sum_2 = torch.ops.aten.sum.default(add);  add = None
    add_1 = torch.ops.aten.add.Tensor(sum_1, sum_2);  sum_1 = sum_2 = None
    return (add_1,)""")

    def test_aot_export_predispatch_composite_implicit_inplace(self):
        def fn(x, p):
            return (torch.ops.aten.absolute_.default(x.clone()),)

        mod = TestMod(fn)
        inp = torch.randn(2, 2)

        gm, _ = aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1):
    clone = torch.ops.aten.clone.default(arg0_1);  arg0_1 = None
    abs_1 = torch.ops.aten.abs.default(clone);  clone = None
    return (abs_1,)""")

    def test_aot_export_predispatch_composite_implicit_linear(self):
        class MM(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(2, 2)

            def forward(self, x):
                return (self.linear(x),)

        mod = MM()
        inp = torch.randn(2, 2)

        gm, _ = aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1, arg2_1):
    linear = torch.ops.aten.linear.default(arg2_1, arg0_1, arg1_1);  arg2_1 = arg0_1 = arg1_1 = None
    return (linear,)""")

    @unittest.expectedFailure
    def test_aot_export_predispatch_outdtype(self):
        class M(torch.nn.Module):
            def __init__(self, weight):
                super().__init__()
                self.weight = weight

            def forward(self, x):
                y = x + 2
                y.add_(5)
                return (out_dtype(
                    torch.ops.aten.mm.default, torch.int32, y, self.weight
                ),)

        weight = torch.randint(-128, 127, (5, 5), dtype=torch.int8)
        mod = M(weight)
        inp = torch.randint(-128, 127, (5, 5), dtype=torch.int8)

        gm, _ = aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1):
    _set_grad_enabled = torch._C._set_grad_enabled(True)
    mm = torch.ops.aten.mm.default(arg1_1, arg1_1)
    _set_grad_enabled_1 = torch._C._set_grad_enabled(False)
    add = torch.ops.aten.add.Tensor(mm, 2);  mm = None
    sum_1 = torch.ops.aten.sum.default(arg1_1);  arg1_1 = None
    sum_2 = torch.ops.aten.sum.default(add);  add = None
    add_1 = torch.ops.aten.add.Tensor(sum_1, sum_2);  sum_1 = sum_2 = None
    return (add_1,)""")

    def test_aot_export_predispatch_func_view(self):
        def fn(p, x):
            y = x @ x
            y.add_(2)
            return (x.sum() + y.view(1, 4).sum(),)

        mod = TestMod(fn)
        inp = torch.randn(2, 2)

        gm, _ = aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1):
    matmul = torch.ops.aten.matmul.default(arg1_1, arg1_1)
    add = torch.ops.aten.add.Tensor(matmul, 2);  matmul = None
    sum_1 = torch.ops.aten.sum.default(arg1_1);  arg1_1 = None
    view_1 = torch.ops.aten.view.default(add, [1, 4]);  add = None
    sum_2 = torch.ops.aten.sum.default(view_1);  view_1 = None
    add_1 = torch.ops.aten.add.Tensor(sum_1, sum_2);  sum_1 = sum_2 = None
    return (add_1,)""")

    def test_aot_export_predispatch_buffer_mutation_metadata(self):
        class Foo(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.register_buffer('foo', torch.zeros(2, 2))

            def forward(self, x):
                self.foo.add_(4)
                return (x.sum() + self.foo.sum(),)

        inp = torch.randn(2, 2)

        gm, graph_sig = aot_export_module(Foo(), [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1):
    add = torch.ops.aten.add.Tensor(arg0_1, 4);  arg0_1 = None
    sum_1 = torch.ops.aten.sum.default(arg1_1);  arg1_1 = None
    sum_2 = torch.ops.aten.sum.default(add)
    add_1 = torch.ops.aten.add.Tensor(sum_1, sum_2);  sum_1 = sum_2 = None
    return (add, add_1)""")
        eager_mod = Foo()
        output_1, output_2 = gm(torch.zeros(2, 2), inp)
        eager_output = eager_mod(inp)
        self.assertTrue(torch.allclose(output_2, eager_output[0]))

        _, output_2 = gm(output_1, inp)
        eager_output = eager_mod(inp)
        self.assertTrue(torch.allclose(output_2, eager_output[0]))
        self.assertTrue("foo" in graph_sig.buffers)
        self.assertTrue(graph_sig.inputs_to_buffers["arg0_1"] == "foo")

    def test_aot_export_predispatch_with_autograd_op(self):
        def foo(p, x):
            with torch.enable_grad():
                y = x + 5
                y.add_(5)
                y.add_(7)
                return (x.cos() + y.sin(),)

        inp = torch.randn(2, 2)
        mod = TestMod(foo)

        gm, _ = aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1):
    _set_grad_enabled = torch._C._set_grad_enabled(True)
    add = torch.ops.aten.add.Tensor(arg1_1, 5)
    add_1 = torch.ops.aten.add.Tensor(add, 5);  add = None
    add_2 = torch.ops.aten.add.Tensor(add_1, 7);  add_1 = None
    cos = torch.ops.aten.cos.default(arg1_1);  arg1_1 = None
    sin = torch.ops.aten.sin.default(add_2);  add_2 = None
    add_3 = torch.ops.aten.add.Tensor(cos, sin);  cos = sin = None
    _set_grad_enabled_1 = torch._C._set_grad_enabled(False)
    return (add_3,)""")

    @unittest.skipIf(IS_WINDOWS, "Windows isn't supported for this case")
    @unittest.skipIf(not torchdynamo.is_dynamo_supported(), "TorchDynamo is not supported")
    def test_aot_export_predispatch_with_cond_nested(self):
        class M(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x):
                def true_fn(x):
                    y = x.sin()
                    y.add_(5)

                    def true_true_fn(x):
                        y = x.sin()
                        y.add_(7)
                        return y.sin()

                    def true_false_fn(x):
                        return x.cos()

                    return torch.cond(y.cos().shape[0] > 5, true_true_fn, true_false_fn, [y.cos()])

                def false_fn(x):
                    z = x.cos()
                    z.add_(6)
                    return z.sin()

                a = torch.cond(x.shape[0] > 4, true_fn, false_fn, [x])
                return (a + 3, a + 4)

        inp = torch.randn(2, 2)
        gm, _ = aot_export_module(M(), [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1):
    _set_grad_enabled = torch._C._set_grad_enabled(False)
    _set_grad_enabled_1 = torch._C._set_grad_enabled(False)
    _set_grad_enabled_2 = torch._C._set_grad_enabled(False)
    true_graph_0 = self.true_graph_0
    false_graph_0 = self.false_graph_0
    conditional = torch.ops.higher_order.cond(False, true_graph_0, false_graph_0, [arg0_1]);  true_graph_0 = false_graph_0 = arg0_1 = None
    getitem = conditional[0];  conditional = None
    add = torch.ops.aten.add.Tensor(getitem, 3)
    add_1 = torch.ops.aten.add.Tensor(getitem, 4);  getitem = None
    return (add, add_1)""")  # noqa: B950

        self.assertExpectedInline(str(gm.true_graph_0.code).strip(), """\
def forward(self, arg0_1):
    sin = torch.ops.aten.sin.default(arg0_1);  arg0_1 = None
    add = torch.ops.aten.add.Tensor(sin, 5);  sin = None
    cos = torch.ops.aten.cos.default(add)
    cos_1 = torch.ops.aten.cos.default(add);  add = None
    true_graph_0 = self.true_graph_0
    false_graph_0 = self.false_graph_0
    conditional = torch.ops.higher_order.cond(False, true_graph_0, false_graph_0, [cos_1]);  true_graph_0 = false_graph_0 = cos_1 = None
    getitem = conditional[0];  conditional = None
    return (getitem,)""")  # noqa: B950

        self.assertExpectedInline(str(gm.true_graph_0.true_graph_0.code).strip(), """\
def forward(self, arg0_1):
    sin = torch.ops.aten.sin.default(arg0_1);  arg0_1 = None
    add = torch.ops.aten.add.Tensor(sin, 7);  sin = None
    sin_1 = torch.ops.aten.sin.default(add);  add = None
    return (sin_1,)""")

    @unittest.skipIf(IS_WINDOWS, "Windows isn't supported for this case")
    @unittest.skipIf(not torchdynamo.is_dynamo_supported(), "TorchDynamo is not supported")
    def test_aot_export_predispatch_with_cond(self):
        class M(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x):
                def true_fn(x):
                    y = x.sin()
                    z = torch.ops.aten.linear.default(y, torch.randn(2, 2))
                    z.add_(5)
                    return z.cos()

                def false_fn(x):
                    z = x.cos()
                    z.add_(6)
                    return z.sin()

                a = torch.cond(x.shape[0] > 4, true_fn, false_fn, [x])
                return (a + 3, a + 4)

        inp = torch.randn(2, 2)
        gm, _ = aot_export_module(M(), [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1):
    _set_grad_enabled = torch._C._set_grad_enabled(False)
    _set_grad_enabled_1 = torch._C._set_grad_enabled(False)
    _set_grad_enabled_2 = torch._C._set_grad_enabled(False)
    true_graph_0 = self.true_graph_0
    false_graph_0 = self.false_graph_0
    conditional = torch.ops.higher_order.cond(False, true_graph_0, false_graph_0, [arg0_1]);  true_graph_0 = false_graph_0 = arg0_1 = None
    getitem = conditional[0];  conditional = None
    add = torch.ops.aten.add.Tensor(getitem, 3)
    add_1 = torch.ops.aten.add.Tensor(getitem, 4);  getitem = None
    return (add, add_1)""")  # noqa: B950
        self.assertExpectedInline(str(gm.true_graph_0.code).strip(), """\
def forward(self, arg0_1):
    sin = torch.ops.aten.sin.default(arg0_1);  arg0_1 = None
    randn = torch.ops.aten.randn.default([2, 2], device = device(type='cpu'), pin_memory = False)
    linear = torch.ops.aten.linear.default(sin, randn);  sin = randn = None
    add = torch.ops.aten.add.Tensor(linear, 5);  linear = None
    cos = torch.ops.aten.cos.default(add);  add = None
    return (cos,)""")

    def test_aot_export_predispatch_conv_and_bn(self):
        class ConvBatchnorm(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.conv = torch.nn.Conv2d(1, 3, 1, 1)
                self.bn = torch.nn.BatchNorm2d(3)

            def forward(self, x):
                x = self.conv(x)
                x = self.bn(x)
                return (x,)

        mod = ConvBatchnorm()
        mod.train()
        inp = torch.randn(1, 1, 3, 3)

        gm, _ = aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1, arg2_1, arg3_1, arg4_1, arg5_1, arg6_1, arg7_1):
    conv2d = torch.ops.aten.conv2d.default(arg7_1, arg0_1, arg1_1);  arg7_1 = arg0_1 = arg1_1 = None
    add = torch.ops.aten.add.Tensor(arg6_1, 1);  arg6_1 = None
    _native_batch_norm_legit_functional = torch.ops.aten._native_batch_norm_legit_functional.default(conv2d, arg2_1, arg3_1, arg4_1, arg5_1, True, 0.1, 1e-05);  conv2d = arg2_1 = arg3_1 = arg4_1 = arg5_1 = None
    getitem = _native_batch_norm_legit_functional[0]
    getitem_3 = _native_batch_norm_legit_functional[3]
    getitem_4 = _native_batch_norm_legit_functional[4];  _native_batch_norm_legit_functional = None
    return (getitem_3, getitem_4, add, getitem)""")  # noqa: B950

    def test_aot_export_predispatch_reshape(self):
        class Reshape(torch.nn.Module):
            def forward(self, x):
                y = x.reshape(4, 4)
                return (y.sum(),)

        mod = Reshape()
        inp = torch.randn(2, 8)

        gm, _ = aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1):
    view = torch.ops.aten.view.default(arg0_1, [4, 4]);  arg0_1 = None
    sum_1 = torch.ops.aten.sum.default(view);  view = None
    return (sum_1,)""")  # noqa: B950

    def test_aot_export_predispatch_contiguous(self):
        class Cont(torch.nn.Module):
            def forward(self, x):
                y = torch.ops.aten.contiguous.default(x)
                return (y.sum(),)

        mod = Cont()
        inp = torch.randn(2, 8)

        gm, _ = aot_export_module(mod, [inp], trace_joint=False, pre_dispatch=True)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1):
    sum_1 = torch.ops.aten.sum.default(arg0_1);  arg0_1 = None
    return (sum_1,)""")  # noqa: B950

    def test_aot_export_module_joint(self):
        class ConvBatchnormRelu(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.conv = torch.nn.Conv2d(1, 3, 1, 1)
                self.bn = torch.nn.BatchNorm2d(3)

            def forward(self, x):
                x = self.conv(x)
                x = self.bn(x)
                user_out = torch.nn.functional.relu(x)
                loss = user_out.sum()
                return loss, user_out.detach()

        mod = ConvBatchnormRelu()
        mod.train()
        inp = torch.randn(1, 1, 3, 3)
        o_ref = mod(inp)
        fx_g, signature = aot_export_module(mod, [inp], trace_joint=True, output_loss_index=0)
        # Some important characteristics of the exported graph below:
        # 8 arguments: 2 params from conv, 2 params from batchnorm, 2 buffers from 1 batchnorm, 1 user input
        # 9 outputs: 3 mutated buffers (from batchnorm), 2 user outputs and 4 gradients (since there were 4 parameters)
        self.assertExpectedInline(fx_g.print_readable(print_output=False), """\
class <lambda>(torch.nn.Module):
    def forward(self, arg0_1: "f32[3, 1, 1, 1]", arg1_1: "f32[3]", arg2_1: "f32[3]", arg3_1: "f32[3]", arg4_1: "f32[3]", arg5_1: "f32[3]", arg6_1: "i64[]", arg7_1: "f32[1, 1, 3, 3]"):
        # No stacktrace found for following nodes
        convolution: "f32[1, 3, 3, 3]" = torch.ops.aten.convolution.default(arg7_1, arg0_1, arg1_1, [1, 1], [0, 0], [1, 1], False, [0, 0], 1);  arg1_1 = None
        add: "i64[]" = torch.ops.aten.add.Tensor(arg6_1, 1);  arg6_1 = None
        _native_batch_norm_legit_functional = torch.ops.aten._native_batch_norm_legit_functional.default(convolution, arg2_1, arg3_1, arg4_1, arg5_1, True, 0.1, 1e-05);  arg3_1 = arg4_1 = arg5_1 = None
        getitem: "f32[1, 3, 3, 3]" = _native_batch_norm_legit_functional[0]
        getitem_1: "f32[3]" = _native_batch_norm_legit_functional[1]
        getitem_2: "f32[3]" = _native_batch_norm_legit_functional[2]
        getitem_3: "f32[3]" = _native_batch_norm_legit_functional[3]
        getitem_4: "f32[3]" = _native_batch_norm_legit_functional[4];  _native_batch_norm_legit_functional = None
        relu: "f32[1, 3, 3, 3]" = torch.ops.aten.relu.default(getitem);  getitem = None
        detach: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(relu)
        detach_1: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(relu)
        detach_2: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_1);  detach_1 = None
        detach_3: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_2);  detach_2 = None
        detach_4: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_3);  detach_3 = None
        sum_1: "f32[]" = torch.ops.aten.sum.default(relu)
        detach_5: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(relu);  relu = None
        detach_6: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_5);  detach_5 = None
        detach_7: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_6);  detach_6 = None
        detach_8: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_7);  detach_7 = None
        detach_9: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_8);  detach_8 = None
        detach_10: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_9);  detach_9 = None
        ones_like: "f32[]" = torch.ops.aten.ones_like.default(sum_1, pin_memory = False, memory_format = torch.preserve_format)
        expand: "f32[1, 3, 3, 3]" = torch.ops.aten.expand.default(ones_like, [1, 3, 3, 3]);  ones_like = None
        detach_11: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_4);  detach_4 = None
        detach_12: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_11);  detach_11 = None
        detach_13: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_12);  detach_12 = None
        detach_14: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_13);  detach_13 = None
        threshold_backward: "f32[1, 3, 3, 3]" = torch.ops.aten.threshold_backward.default(expand, detach_14, 0);  expand = detach_14 = None
        native_batch_norm_backward = torch.ops.aten.native_batch_norm_backward.default(threshold_backward, convolution, arg2_1, getitem_3, getitem_4, getitem_1, getitem_2, True, 1e-05, [True, True, True]);  threshold_backward = convolution = arg2_1 = getitem_1 = getitem_2 = None
        getitem_5: "f32[1, 3, 3, 3]" = native_batch_norm_backward[0]
        getitem_6: "f32[3]" = native_batch_norm_backward[1]
        getitem_7: "f32[3]" = native_batch_norm_backward[2];  native_batch_norm_backward = None
        convolution_backward = torch.ops.aten.convolution_backward.default(getitem_5, arg7_1, arg0_1, [3], [1, 1], [0, 0], [1, 1], False, [0, 0], 1, [False, True, True]);  getitem_5 = arg7_1 = arg0_1 = None
        getitem_8 = convolution_backward[0]
        getitem_9: "f32[3, 1, 1, 1]" = convolution_backward[1]
        getitem_10: "f32[3]" = convolution_backward[2];  convolution_backward = None
        return (getitem_3, getitem_4, add, sum_1, detach_10, getitem_9, getitem_10, getitem_6, getitem_7)
        """)  # noqa: B950


        self.assertExpectedInline(str(signature.parameters), """['conv.weight', 'conv.bias', 'bn.weight', 'bn.bias']""")
        self.assertExpectedInline(str(signature.buffers), """['bn.running_mean', 'bn.running_var', 'bn.num_batches_tracked']""")
        self.assertExpectedInline(str(signature.user_inputs), """['arg7_1']""")
        self.assertExpectedInline(str(signature.inputs_to_parameters), """{'arg0_1': 'conv.weight', 'arg1_1': 'conv.bias', 'arg2_1': 'bn.weight', 'arg3_1': 'bn.bias'}""")  # noqa: B950
        self.assertExpectedInline(str(signature.inputs_to_buffers), """{'arg4_1': 'bn.running_mean', 'arg5_1': 'bn.running_var', 'arg6_1': 'bn.num_batches_tracked'}""")  # noqa: B950
        self.assertExpectedInline(str(signature.buffers_to_mutate), """{'getitem_3': 'bn.running_mean', 'getitem_4': 'bn.running_var', 'add': 'bn.num_batches_tracked'}""")  # noqa: B950
        self.assertExpectedInline(str(signature.backward_signature.gradients_to_parameters), """{'getitem_9': 'conv.weight', 'getitem_10': 'conv.bias', 'getitem_6': 'bn.weight', 'getitem_7': 'bn.bias'}""")  # noqa: B950
        self.assertExpectedInline(str(signature.backward_signature.gradients_to_user_inputs), """{}""")
        self.assertExpectedInline(str(signature.backward_signature.loss_output), """getitem_3""")

        # Also check the inference graph
        # Main important thing here is that there are 5 total outputs: 3 total mutated buffers (from batchnorm), 2 user outputs.
        fx_g_inference, signature_inference = aot_export_module(mod, [inp], trace_joint=False)
        self.assertExpectedInline(fx_g_inference.print_readable(print_output=False), """\
class <lambda>(torch.nn.Module):
    def forward(self, arg0_1: "f32[3, 1, 1, 1]", arg1_1: "f32[3]", arg2_1: "f32[3]", arg3_1: "f32[3]", arg4_1: "f32[3]", arg5_1: "f32[3]", arg6_1: "i64[]", arg7_1: "f32[1, 1, 3, 3]"):
        # No stacktrace found for following nodes
        convolution: "f32[1, 3, 3, 3]" = torch.ops.aten.convolution.default(arg7_1, arg0_1, arg1_1, [1, 1], [0, 0], [1, 1], False, [0, 0], 1);  arg7_1 = arg0_1 = arg1_1 = None
        add: "i64[]" = torch.ops.aten.add.Tensor(arg6_1, 1);  arg6_1 = None
        _native_batch_norm_legit_functional = torch.ops.aten._native_batch_norm_legit_functional.default(convolution, arg2_1, arg3_1, arg4_1, arg5_1, True, 0.1, 1e-05);  convolution = arg2_1 = arg3_1 = arg4_1 = arg5_1 = None
        getitem: "f32[1, 3, 3, 3]" = _native_batch_norm_legit_functional[0]
        getitem_3: "f32[3]" = _native_batch_norm_legit_functional[3]
        getitem_4: "f32[3]" = _native_batch_norm_legit_functional[4];  _native_batch_norm_legit_functional = None
        relu: "f32[1, 3, 3, 3]" = torch.ops.aten.relu.default(getitem);  getitem = None
        sum_1: "f32[]" = torch.ops.aten.sum.default(relu)
        detach: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(relu);  relu = None
        detach_1: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach);  detach = None
        detach_2: "f32[1, 3, 3, 3]" = torch.ops.aten.detach.default(detach_1);  detach_1 = None
        return (getitem_3, getitem_4, add, sum_1, detach_2)
        """)  # noqa: B950
        # Some important characteristics of the exported graph below:
        # 8 arguments: 2 params from conv, 2 params from batchnorm, 2 buffers from 1 batchnorm, 1 user input
        # 9 outputs: 2 mutated buffers (from batchnorm), 2 user outputs and 4 gradients (since there were 4 parameters)

    def test_aot_export_simplified_basic(self):
        def f(x, y):
            return x * y, y * y.detach()

        x = torch.randn(2, requires_grad=True)
        y = torch.randn(2, requires_grad=True)

        f_graph_fw = aot_export_joint_simple(f, [x, y], trace_joint=False)
        out_ref = f(x, y)
        # No calling convention changes necessary to invoke the traced graph
        out_test = f_graph_fw(x, y)
        self.assertEqual(out_ref, out_test)

        # Now test the backward
        x = torch.randn(2, requires_grad=True)
        y = torch.randn(2, requires_grad=True)
        x2 = x.clone().detach().requires_grad_(True)
        y2 = y.clone().detach().requires_grad_(True)
        x3 = x.clone().detach().requires_grad_(True)
        y3 = y.clone().detach().requires_grad_(True)
        f_graph_joint = aot_export_joint_simple(f, [x, y], trace_joint=True)
        num_fw_outputs = 2
        fw_g, bw_g = default_partition(f_graph_joint, [x, y], num_fwd_outputs=num_fw_outputs)
        out_ref2 = f(x2, y2)
        fw_outs = fw_g(x3, y3)
        out_test2, activations = fw_outs[:num_fw_outputs], fw_outs[num_fw_outputs:]
        self.assertEqual(out_ref2, out_test2)

        # Test running the traced backward graph with a mocked-up grad_output
        grad_outs = [torch.ones_like(x) for x in out_ref2]
        grads_ref = torch.autograd.grad(out_ref2, [x2, y2], grad_outputs=grad_outs)
        grads_test = bw_g(*activations, *grad_outs)
        for g_ref, g_test in zip(grads_ref, grads_test):
            self.assertEqual(g_ref, g_test)

    def test_aot_export_metadata_mutation_banned(self):
        def fn(p, x):
            x.t_()
            return (x * 2,)
        mod = TestMod(fn)
        inp = torch.randn(2, 4)
        with self.assertRaisesRegex(
            RuntimeError, "Found an input that received a metadata mutation"
        ):
            aot_export_joint_simple(fn, [mod.p, inp], trace_joint=False)
            aot_export_joint_simple(fn, [mod.p, inp], trace_joint=True)
            aot_export_module(mod, [inp], trace_joint=False)

    def test_aot_export_forward_mutation_no_buffer_mut(self):
        class M(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.register_buffer("buffer1", torch.ones(6, 4))

            def forward(self, x):
                x.add_(4)
                return (x.cos().sum() + self.buffer1.sum(),)

        mod = M()
        inp = torch.ones(6, 4)
        gm, sig = aot_export_module(mod, [inp], trace_joint=False)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1):
    add = torch.ops.aten.add.Tensor(arg1_1, 4);  arg1_1 = None
    cos = torch.ops.aten.cos.default(add)
    sum_1 = torch.ops.aten.sum.default(cos);  cos = None
    sum_2 = torch.ops.aten.sum.default(arg0_1);  arg0_1 = None
    add_1 = torch.ops.aten.add.Tensor(sum_1, sum_2);  sum_1 = sum_2 = None
    return (add, add_1)""")  # noqa: B950
        self.assertEqual(sig.user_inputs_to_mutate, {"add": "arg1_1"})

    def test_aot_export_forward_mutation_multiple_mut(self):
        class M(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.register_buffer("buffer1", torch.ones(6, 4))

            def forward(self, x, y):
                y.add_(4)
                self.buffer1.add_(5)
                return (x.cos().sum() + y.sin().sum(), self.buffer1.sum(),)

        mod = M()
        inp = [torch.ones(6, 4), torch.zeros(6, 4)]
        gm, sig = aot_export_module(mod, inp, trace_joint=False)
        self.assertExpectedInline(str(gm.code).strip(), """\
def forward(self, arg0_1, arg1_1, arg2_1):
    add = torch.ops.aten.add.Tensor(arg2_1, 4);  arg2_1 = None
    add_1 = torch.ops.aten.add.Tensor(arg0_1, 5);  arg0_1 = None
    cos = torch.ops.aten.cos.default(arg1_1);  arg1_1 = None
    sum_1 = torch.ops.aten.sum.default(cos);  cos = None
    sin = torch.ops.aten.sin.default(add)
    sum_2 = torch.ops.aten.sum.default(sin);  sin = None
    add_2 = torch.ops.aten.add.Tensor(sum_1, sum_2);  sum_1 = sum_2 = None
    sum_3 = torch.ops.aten.sum.default(add_1)
    return (add_1, add, add_2, sum_3)""")  # noqa: B950
        self.assertEqual(sig.user_inputs_to_mutate, {"add": "arg2_1"})
        self.assertEqual(sig.buffers_to_mutate, {"add_1": "buffer1"})

    def test_aot_export_input_mutation_on_input_requiring_grad_banned(self):
        class M(torch.nn.Module):
            def forward(self, x):
                x.add_(4)
                return (x,)

        mod = M()
        inp = torch.randn(2, requires_grad=True)
        with self.assertRaisesRegex(
            RuntimeError, "Found a graph input that requires gradients, and received a mutation"
        ):
            aot_export_module(mod, [inp], trace_joint=False)

    def test_aot_export_input_mutation_on_parameter_banned(self):
        def fn(p, x):
            p.mul_(2)
            return (p + x,)
        mod = TestMod(fn)
        inp = torch.randn(2)
        with self.assertRaisesRegex(
            RuntimeError, "Found a graph input that requires gradients, and received a mutation"
        ):
            aot_export_joint_simple(fn, [mod.p, inp], trace_joint=False)
            aot_export_joint_simple(fn, [mod.p, inp], trace_joint=True)
            aot_export_module(mod, [inp], trace_joint=False)

    def test_aot_export_synthetic_bases_banned(self):
        def fn(p, x, y):
            x.mul_(2)
            return (x + y,)
        mod = TestMod(fn)
        inp = torch.randn(2)
        inp2 = inp.view(-1)
        with self.assertRaisesRegex(
            RuntimeError, "Encountered aliased inputs that are mutated"
        ):
            aot_export_joint_simple(fn, [mod.p, inp, inp2], trace_joint=False)
            aot_export_joint_simple(fn, [mod.p, inp, inp2], trace_joint=True)
            aot_export_module(mod, [inp, inp2], trace_joint=False)

    def test_aot_export_input_dupes_banned(self):
        def fn(p, x, y):
            x.mul_(2)
            return (x + y,)
        mod = TestMod(fn)
        inp = torch.randn(2)
        with self.assertRaisesRegex(
            RuntimeError, "Encountered duplicated inputs that are mutated in the graph"
        ):
            aot_export_joint_simple(fn, [mod.p, inp, inp], trace_joint=False)
            aot_export_joint_simple(fn, [mod.p, inp, inp], trace_joint=True)
            aot_export_module(mod, [inp, inp], trace_joint=False)

    def test_aot_export_multiple_outputs_require_grad_banned(self):
        def fn(p, x):
            out = p * x
            return out, out.sum()
        mod = TestMod(fn)
        inp = torch.randn(2)
        with self.assertRaisesRegex(
            RuntimeError, "Found an output of the forward that requires gradients, that was not"
        ):
            aot_export_module(mod, [inp], trace_joint=True, output_loss_index=1)

    @unittest.skipIf(IS_WINDOWS, "Windows isn't supported for this case")
    @unittest.skipIf(not torch._dynamo.is_dynamo_supported(), "Cond needs dynamo to run")
    def test_aot_export_with_torch_cond(self):
        class M(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x):
                def true_fn(x):
                    y = x + 4
                    y.add_(5)
                    return x.cos()

                def false_fn(x):
                    y = x + 5
                    y.add_(6)
                    return x.sin()

                a = torch.cond(x.shape[0] > 4, true_fn, false_fn, [x])
                return (a + 3, a + 4)

        inp = torch.randn(3, 4)
        gm, _ = aot_export_module(M(), (inp,), trace_joint=False)
        self.assertExpectedInline(gm.code.strip(), """\
def forward(self, arg0_1):
    true_graph_0 = self.true_graph_0
    false_graph_0 = self.false_graph_0
    conditional = torch.ops.higher_order.cond(False, true_graph_0, false_graph_0, [arg0_1]);  true_graph_0 = false_graph_0 = arg0_1 = None
    getitem = conditional[0];  conditional = None
    add = torch.ops.aten.add.Tensor(getitem, 3)
    add_1 = torch.ops.aten.add.Tensor(getitem, 4);  getitem = None
    return (add, add_1)""")  # noqa: B950

        self.assertExpectedInline(gm.true_graph_0.code.strip(), """\
def forward(self, arg0_1):
    add = torch.ops.aten.add.Tensor(arg0_1, 4)
    add_1 = torch.ops.aten.add.Tensor(add, 5);  add = None
    cos = torch.ops.aten.cos.default(arg0_1);  arg0_1 = None
    return (cos,)""")

        self.assertExpectedInline(gm.false_graph_0.code.strip(), """\
def forward(self, arg0_1):
    add = torch.ops.aten.add.Tensor(arg0_1, 5)
    add_1 = torch.ops.aten.add.Tensor(add, 6);  add = None
    sin = torch.ops.aten.sin.default(arg0_1);  arg0_1 = None
    return (sin,)""")

    def test_aot_export_simplified_pytrees_banned(self):
        def fn(inps):
            return (inps[0] + inps[1],)
        inp1 = torch.randn(2)
        inp2 = torch.randn(2)
        inps = [inp1, inp2]
        with self.assertRaisesRegex(
            RuntimeError, "aot_export_joint_simple requires individual inputs not to be pytrees"
        ):
            aot_export_joint_simple(fn, [inps], trace_joint=False)
            aot_export_joint_simple(fn, [inps], trace_joint=True)

    def test_aot_export_functionalized_rng_banned(self):
        def fn(p, x):
            return (p + x,)
        mod = TestMod(fn)
        inp = torch.randn(2)
        with patch("functorch.compile.config.functionalize_rng_ops", True), self.assertRaisesRegex(
            RuntimeError, "Functionalized RNG is not currently supported in the aot_export"
        ):
            aot_export_joint_simple(fn, [mod.p, inp], trace_joint=False)
            aot_export_joint_simple(fn, [mod.p, inp], trace_joint=True)
            aot_export_module(mod, [inp], trace_joint=False)


class TestPartitioning(AOTTestCase):
    @unittest.skipIf(not USE_NETWORKX, "networkx not available")
    def test_recompute_partitioning(self):
        def fn(a, b):
            return torch.sin(torch.sin(a)) + b

        # Reference calculation
        ref_a = torch.rand(10, 10, requires_grad=True)
        ref_b = torch.rand(10, 10, requires_grad=True)
        ref = fn(ref_a, ref_b)
        ref.sum().backward()

        # Compiled function calculation
        res_a = ref_a.clone().detach().requires_grad_(True)
        res_b = ref_b.clone().detach().requires_grad_(True)

        def compile_fn(x, _):
            return x

        compiled_fn = compiled_function(fn, compile_fn, compile_fn, min_cut_rematerialization_partition)
        res = compiled_fn(res_a, res_b)
        res.sum().backward()
        assert torch.allclose(ref, res, atol=1e-3, rtol=1e-3)
        assert torch.allclose(ref_a.grad, res_a.grad, atol=1e-3, rtol=1e-3)
        assert torch.allclose(ref_b.grad, res_b.grad, atol=1e-3, rtol=1e-3)

    def test_meta_tensor_inplace_op(self):
        # Following module results in inplace ops while tracing. The test checks
        # that the meta tensor information is stored for inplace ops.
        class MockModule(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.weight = torch.nn.Parameter(torch.randn(3072, 768, requires_grad=True))
                self.bias = torch.nn.Parameter(torch.randn(3072, requires_grad=True))

            def forward(self, add_4):
                linear_4 = torch.nn.functional.linear(add_4, self.weight, bias=self.bias)
                gelu = torch.nn.functional.gelu(linear_4)
                return gelu

        def check_meta_tensor(fx_g, _):
            for node in fx_g.graph.nodes:
                if node.op != 'output':
                    assert 'tensor_meta' in node.meta
            return fx_g

        inp0 = torch.randn(16, 128, 768, requires_grad=True)
        inputs = [inp0, ]
        mod = MockModule().to(device="cpu")
        aot_mod = aot_module(mod, fw_compiler=check_meta_tensor)
        aot_mod(*inputs)

    def test_default_partitioner_getitem(self):
        mod = nn.LayerNorm([10])

        def f(x, mod_weight, mod_bias):
            return torch.nn.functional.layer_norm(x, [10], mod_weight, mod_bias, eps=1e-6)

        fw_graph, bw_graph = get_fw_bw_graph(f, [torch.randn(3, 10, requires_grad=True), mod.weight, mod.bias],
                                             partitioner=default_partition)
        self.assertEqual(get_num_ins_outs(fw_graph), (3, 6))
        self.assertEqual(get_num_ins_outs(bw_graph), (6, 3))

    @unittest.skipIf(not USE_NETWORKX, "networkx not available")
    def test_min_cut_partitioner_save_shape(self):

        def f(x):
            s = x.sum(dim=1)
            return s

        inp = [torch.ones([10, 10], requires_grad=True)]
        fw_graph, bw_graph = get_fw_bw_graph(f, inp, dynamic=True)
        _, fw_output = get_ins_outs(fw_graph)
        self.assertEqual(get_num_ins_outs(fw_graph), (1, 3))
        self.assertEqual(get_num_ins_outs(bw_graph), (3, 1))
        self.assertEqual(str(fw_output[0]), "sum_1")
        # make sure we don't do the suboptimal thing of saving the bigger primals input to sum,
        # rather than saving the sizes of the primals input for use in backward expand
        self.assertEqual(str(fw_output[1]), "sym_size_int")
        self.assertEqual(str(fw_output[2]), "sym_size_int_1")

        inp = [
            torch.randn(10, requires_grad=True),
            torch.randn((3, 10), requires_grad=True),
            torch.randn((2, 10), requires_grad=True),
        ]

        def f(a, b, c):
            # tried to test what happens if we save a size tuple in the graph;
            # turns out we never will due to how we trace, but this is probably
            # still a good test case for various size manipulations
            sb = torch.ops.aten.sym_size(b)
            sc = c.size()
            x = sb[0] + sc[0]
            a_sz = (x, a.size(0))
            return torch.cat([a.expand(a_sz), b, c])
        fw_graph, bw_graph = get_fw_bw_graph(f, inp, dynamic=True)
        self.assertEqual(get_num_ins_outs(fw_graph), (3, 4))
        self.assertEqual(get_num_ins_outs(bw_graph), (4, 3))
        _, outs = get_ins_outs(fw_graph)
        self.assertTrue(all(is_sym_node(n) for n in outs[1:]))

    def test_default_partitioner_output_tensor_shape_tensor(self):

        inp = [
            torch.randn(10, requires_grad=True),
            torch.randn((3, 10), requires_grad=True),
            torch.randn((2, 10), requires_grad=True),
            torch.randn((10, 1), requires_grad=True),
        ]

        def f(a, b, c, d):
            # Try to force symints intermixed with outputs in the function's returns
            sb = b.size()
            sc = c.size()
            x = sb[0] + sc[0]
            a_sz = (x, a.size(0))
            cat = torch.cat([a.expand(a_sz), b, c])
            mm = torch.mm(cat, d)
            mm2 = torch.mm(mm, a.view(mm.size(1), a.size(0)))  # this saves 4 new ints for backward. why?
            # and what do i have to do to make it save a tensor for backward?
            return cat, sb, c, mm2

        fw_graph_cell = [None]
        bw_graph_cell = [None]
        compiled_outs = aot_function(
            f,
            fw_compiler=partial(extract_graph, graph_cell=fw_graph_cell),
            bw_compiler=partial(extract_graph, graph_cell=bw_graph_cell),
            partition_fn=default_partition,
            decompositions=default_decompositions,
            dynamic=True)(*inp)
        fw_graph = fw_graph_cell[0]
        (compiled_outs[0].sum() + compiled_outs[2].sum()).backward()
        bw_graph = bw_graph_cell[0]

        # in the fwd graph, 13 outs because:
        # - 5 original outputs (sb is a tuple, gets expanded to 2 symints)
        # - 8 saved outputs for backward: 5 tensors, 3 symints
        self.assertEqual(get_num_ins_outs(fw_graph), (4, 13))
        # in the bwd graph, 10 inputs (grad outs) because:
        # - The fwd graph had 13 outputs
        # - 1 was a view of an input, which gets regenerated outside of the graph
        #   and doesn't participate in the backward
        # - 2 user outs were symints (b.size()), which don't get tangents in the backward
        self.assertEqual(get_num_ins_outs(bw_graph), (10, 4))
        _, fw_graph_out_nodes = get_ins_outs(fw_graph)
        self.assertEqual(
            # fw outputs include b.size() which expands to 2 symints,
            #
            # TODO(whc)- are the saved-tensors/saved-symints correct here?
            # i just made the test pass based on what default partition did
            # Of the 5 original forward outputs, the 4th (c) is an input,
            # which won't show up in the compiled forward graph
            [False, True, True, False, False] + [False] * 4 + [True] * 4,
            [is_sym_node(n) for n in fw_graph_out_nodes]
        )

        real_outs = f(*inp)
        self.assertEqual(compiled_outs, real_outs)
        self.assertTrue(isinstance(real_outs[1], torch.Size))

        # TODO(whc) we should learn to return torch.Sizes
        self.assertFalse(isinstance(compiled_outs[1], torch.Size))

    @unittest.skipIf(not USE_NETWORKX, "networkx not available")
    def test_min_cut_partitioner_output_tensor_shape_tensor(self):

        inp = [
            torch.randn(10, requires_grad=True),
            torch.randn((3, 10), requires_grad=True),
            torch.randn((2, 10), requires_grad=True),
            torch.randn((10, 1), requires_grad=True),
        ]

        def f(a, b, c, d):
            # Try to force symints intermixed with outputs in the function's returns
            sb = b.size()
            sc = c.size()
            x = sb[0] + sc[0]
            a_sz = (x, a.size(0))
            cat = torch.cat([a.expand(a_sz), b, c])
            mm = torch.mm(cat, d)
            mm2 = torch.mm(mm, a.view(mm.size(1), a.size(0)))  # this saves 4 new ints for backward. why?
            # and what do i have to do to make it save a tensor for backward?
            return cat, sb, c, mm2

        fw_graph_cell = [None]
        bw_graph_cell = [None]
        compiled_outs = aot_function(
            f,
            fw_compiler=partial(extract_graph, graph_cell=fw_graph_cell),
            bw_compiler=partial(extract_graph, graph_cell=bw_graph_cell),
            partition_fn=min_cut_rematerialization_partition,
            decompositions=default_decompositions,
            dynamic=True)(*inp)
        fw_graph = fw_graph_cell[0]
        (compiled_outs[0].sum() + compiled_outs[2].sum()).backward()
        bw_graph = bw_graph_cell[0]

        self.assertEqual(get_num_ins_outs(fw_graph), (4, 12))
        self.assertEqual(get_num_ins_outs(bw_graph), (9, 4))
        _, fw_graph_out_nodes = get_ins_outs(fw_graph)
        self.assertEqual(
            # fw outputs include b.size() which expands to 2 symints,
            # then 4 tensors (transposes of matricies used for mm) are saved
            # finally 3 symints are saved
            [False, True, True, False, False] + [False] * 4 + [True] * 3,
            [is_sym_node(n) for n in fw_graph_out_nodes]
        )

        real_outs = f(*inp)
        self.assertEqual(compiled_outs, real_outs)
        self.assertTrue(isinstance(real_outs[1], torch.Size))

        # TODO(whc) we should learn to return torch.Sizes
        self.assertFalse(isinstance(compiled_outs[1], torch.Size))

    @unittest.skipIf(not USE_NETWORKX, "networkx not available")
    def test_min_cut_partitioner(self):
        def f(x):
            return x.cos().cos().cos()

        fw_graph, bw_graph = get_fw_bw_graph(f, [torch.randn(3, requires_grad=True)])
        self.assertEqual(get_num_ins_outs(fw_graph), (1, 2))
        self.assertEqual(get_num_ins_outs(bw_graph), (2, 1))

        def f(a, b, c, d):
            x = a + b + c + d
            return x.cos().cos()

        fw_graph, bw_graph = get_fw_bw_graph(f, [torch.randn(3, requires_grad=True) for _ in range(4)])
        self.assertEqual(get_num_ins_outs(fw_graph), (4, 2))
        self.assertEqual(get_num_ins_outs(bw_graph), (2, 4))

    @unittest.skipIf(not USE_NETWORKX, "networkx not available")
    def test_min_cut_partitioner_recomputable_ops(self):
        def f(x):
            return x * x * x

        recomputable_ops = []
        partition_fn = partial(min_cut_rematerialization_partition, recomputable_ops=recomputable_ops)

        fw_graph, bw_graph = get_fw_bw_graph(f, [torch.randn(3, requires_grad=True)], partition_fn)
        # Expected forward graph:
        # opcode         name       target           args                        kwargs
        # -------------  ---------  ---------------  --------------------------  --------
        # placeholder    primals_1  primals_1        ()                          {}
        # call_function  mul        aten.mul.Tensor  (primals_1, primals_1)      {}
        # call_function  mul_1      aten.mul.Tensor  (mul, primals_1)            {}
        # output         output     output           ([mul_1, primals_1, mul],)  {}
        self.assertEqual(get_num_ins_outs(fw_graph), (1, 3))
        # Expected backward graph:
        # opcode         name        target           args                     kwargs
        # -------------  ----------  ---------------  -----------------------  --------
        # placeholder    primals_1   primals_1        ()                       {}
        # placeholder    mul         mul              ()                       {}
        # placeholder    tangents_1  tangents_1       ()                       {}
        # call_function  mul_2       aten.mul.Tensor  (tangents_1, mul)        {}
        # call_function  mul_3       aten.mul.Tensor  (tangents_1, primals_1)  {}
        # call_function  mul_4       aten.mul.Tensor  (mul_3, primals_1)       {}
        # call_function  add         aten.add.Tensor  (mul_2, mul_4)           {}
        # call_function  add_1       aten.add.Tensor  (add, mul_4)             {}
        # output         output      output           ([add_1],)               {}
        self.assertEqual(get_num_ins_outs(bw_graph), (3, 1))

        recomputable_ops = [torch.ops.aten.mul]
        partition_fn = partial(min_cut_rematerialization_partition, recomputable_ops=recomputable_ops)
        fw_graph, bw_graph = get_fw_bw_graph(f, [torch.randn(3, requires_grad=True)], partition_fn)
        # Expected forward graph:
        # opcode         name       target           args                    kwargs
        # -------------  ---------  ---------------  ----------------------  --------
        # placeholder    primals_1  primals_1        ()                      {}
        # call_function  mul        aten.mul.Tensor  (primals_1, primals_1)  {}
        # call_function  mul_1      aten.mul.Tensor  (mul, primals_1)        {}
        # output         output     output           ([mul_1, primals_1],)   {}
        self.assertEqual(get_num_ins_outs(fw_graph), (1, 2))
        # Expected backward graph:
        # opcode         name        target           args                     kwargs
        # -------------  ----------  ---------------  -----------------------  --------
        # placeholder    primals_1   primals_1        ()                       {}
        # placeholder    tangents_1  tangents_1       ()                       {}
        # call_function  mul         aten.mul.Tensor  (primals_1, primals_1)   {} # RECOMPUTED
        # call_function  mul_2       aten.mul.Tensor  (tangents_1, mul)        {}
        # call_function  mul_3       aten.mul.Tensor  (tangents_1, primals_1)  {}
        # call_function  mul_4       aten.mul.Tensor  (mul_3, primals_1)       {}
        # call_function  add         aten.add.Tensor  (mul_2, mul_4)           {}
        # call_function  add_1       aten.add.Tensor  (add, mul_4)             {}
        # output         output      output           ([add_1],)               {}
        self.assertEqual(get_num_ins_outs(bw_graph), (2, 1))

    def test_contiguous(self):
        # The test simulates the condition where transpose followed by view
        # happens in the backward pass.
        # https://discuss.pytorch.org/t/error-on-transpose-and-view/434
        def f(x):
            return x.view(2, 3).t()

        inp = torch.randn(6, requires_grad=True)
        out = aot_function(f, nop)(inp)
        torch.autograd.grad(out, inp, torch.randn(3, 2))

    def test_preserve_random(self):
        def fn(x):
            return torch.nn.functional.dropout(x, 0.5) + x

        x = torch.randn(4)

        torch.manual_seed(0)
        ref = fn(x)

        torch.manual_seed(0)
        aot_fn = aot_function(fn, nop)
        res = aot_fn(x)

        assert torch.allclose(ref, res)

    # https://github.com/pytorch/pytorch/issues/110666
    def test_generate_gives_inference_graph(self):
        # We expect this to give an inference graph
        def generate(x):
            with torch.no_grad():
                return torch.mul(x, x)

        inference_graph_cell = [None]
        inference_compiler = make_boxed_compiler(partial(extract_graph, graph_cell=inference_graph_cell))
        aot_fn = aot_function(generate, nop, inference_compiler=inference_compiler)
        # Even though x requires grad, we should still get an inference graph
        x = torch.randn(4, requires_grad=True)
        res = aot_fn(x)
        self.assertTrue(inference_graph_cell[0] is not None)


    @unittest.skipIf(not torch.cuda.is_available(), "CUDA is unavailable")
    @unittest.skipIf(not USE_TORCHVISION, "test requires torchvision")
    def test_autocast(self):
        mod = torchvision.models.resnet18().cuda()
        mod.train()

        x = torch.randn(16, 3, 32, 32, device="cuda")
        aot_mod = memory_efficient_fusion(mod)

        # Ensure that AOT Autograd works with AMP
        with torch.cuda.amp.autocast(True):
            res = aot_mod(x)
        res.sum().backward()


class TestAOTDispatch(AOTTestCase):

    # Tests to add cases for (non-exhaustive list, mostly for my notes):
    # - subclass / mode introduced in the middle of the compiled fn
    # - various input mutation / intermediate base tests
    # - input mutation that changes a tensor into a subclass
    # - metadata mutation? (TBD)
    # - guard tests (fw guards *and* bw guards)
    # - subclass test involving _indices_of_inps_to_detach
    def test_aot_dispatch_simple(self):
        # a is a subclass, b is not
        def f(a, b):
            aa = torch.mul(a, 6)
            bb = torch.div(b, 2)
            return aa + bb

        a1_ref = torch.ones(3, 3, requires_grad=True)
        a2_ref = torch.ones(3, 3, requires_grad=True)
        a_ref = TwoTensor(a1_ref, a2_ref)
        b_ref = torch.ones(3, 3, requires_grad=True)

        a1_test = a1_ref.clone().detach().requires_grad_(True)
        a2_test = a2_ref.clone().detach().requires_grad_(True)
        a_test = TwoTensor(a1_test, a2_test)
        b_test = b_ref.clone().detach().requires_grad_(True)

        fw_graph_cell = [None]
        bw_graph_cell = [None]

        compiled_f = aot_function(
            f,
            fw_compiler=partial(extract_graph, graph_cell=fw_graph_cell),
            bw_compiler=partial(extract_graph, graph_cell=bw_graph_cell),
            partition_fn=min_cut_rematerialization_partition
        )
        out_ref = f(a_ref, b_ref)
        out_test = compiled_f(a_test, b_test)

        # Output is a TwoTensor (check both inner tensors)
        self.assertEqual(out_ref.a, out_test.a)
        self.assertEqual(out_ref.b, out_test.b)

        out_ref.sum().backward()
        out_test.sum().backward()
        # Both grad_inputs are TwoTensor
        self.assertEqual(a_ref.grad.a, a_test.grad.a)
        self.assertEqual(a_ref.grad.b, a_test.grad.b)
        self.assertEqual(b_ref.grad.a, b_test.grad.a)
        self.assertEqual(b_ref.grad.b, b_test.grad.b)

        # Important pieces of the graph:
        # - mul() and div() show up twice, because we called them on a TwoTensor
        # - add() shows up once, because we called it on a plain Tensor
        # - The user forward() fn returns 1 output (the result of add),
        #   while the graph itself returns two outputs (add, add_1)
        # - add, add_1 correspond to the two inner dense tensors that will be wrapped
        # - into a single TwoTensor output.
        self.assertExpectedInline(fw_graph_cell[0].code.strip(), """\
def forward(self, primals_1, primals_2, primals_3):
    mul = torch.ops.aten.mul.Tensor(primals_1, 6);  primals_1 = None
    mul_1 = torch.ops.aten.mul.Tensor(primals_2, 6);  primals_2 = None
    div = torch.ops.aten.div.Tensor(primals_3, 2);  primals_3 = None
    add = torch.ops.aten.add.Tensor(mul, div);  mul = None
    add_1 = torch.ops.aten.add.Tensor(mul_1, div);  mul_1 = div = None
    return [add, add_1]""")

        # Important pieces of the graph:
        # - 4 total dense outputs.
        #   This corresponds to the fact that each user fwd inpt (a, b)
        #   will get a gradient that is a TwoTensor subclass,
        #   so (mul_2, mul_3) will be wrapped into a.grad
        #   and (div_1, div_2) will be wrapped into b.grad
        # - 4 total dense outputs,
        self.assertExpectedInline(bw_graph_cell[0].code.strip(), """\
def forward(self, tangents_1, tangents_2):
    div_1 = torch.ops.aten.div.Tensor(tangents_1, 2)
    div_2 = torch.ops.aten.div.Tensor(tangents_2, 2)
    mul_2 = torch.ops.aten.mul.Tensor(tangents_1, 6);  tangents_1 = None
    mul_3 = torch.ops.aten.mul.Tensor(tangents_2, 6);  tangents_2 = None
    return [mul_2, mul_3, div_1, div_2]""")

    def test_aot_dispatch_inference(self):
        # a is a subclass, b is not
        def f(a, b):
            aa = torch.mul(a, 6)
            bb = torch.div(b, 2)
            return aa + bb

        a1_ref = torch.ones(3, 3)
        a2_ref = torch.ones(3, 3)
        a_ref = TwoTensor(a1_ref, a2_ref)
        b_ref = torch.ones(3, 3)

        a1_test = a1_ref.clone()
        a2_test = a2_ref.clone()
        a_test = TwoTensor(a1_test, a2_test)
        b_test = b_ref.clone()

        compiled_f = aot_function(
            f,
            fw_compiler=nop,
            bw_compiler=nop,
            partition_fn=min_cut_rematerialization_partition
        )
        out_ref = f(a_ref, b_ref)
        out_test = compiled_f(a_test, b_test)

        # Output is a TwoTensor (check both inner tensors)
        self.assertEqual(out_ref.a, out_test.a)
        self.assertEqual(out_ref.b, out_test.b)

    def test_aot_dispatch_incorrect_backward(self):
        # a is a subclass, b is not
        def f(a, b):
            aa = torch.mul(a, 2)
            bb = torch.add(b, 3)
            out_subclass = torch.div(aa, bb)
            out_reg = torch.add(b, b)
            # When creating the joint, we assume that the second grad_out
            # is not a subclass.
            # In the below test case though, we end up being wrong.
            # This would require re-tracing and recompiling the backward.
            return out_subclass, out_reg

        a1_ref = torch.ones(3, 3, requires_grad=True)
        a2_ref = torch.ones(3, 3, requires_grad=True)
        a_ref = TwoTensor(a1_ref, a2_ref)
        b_ref = torch.ones(3, 3, requires_grad=True)

        a1_test = a1_ref.clone().detach().requires_grad_(True)
        a2_test = a2_ref.clone().detach().requires_grad_(True)
        a_test = TwoTensor(a1_test, a2_test)
        b_test = b_ref.clone().detach().requires_grad_(True)

        compiled_f = aot_function(
            f,
            fw_compiler=nop,
            bw_compiler=nop,
            partition_fn=min_cut_rematerialization_partition
        )
        out_ref = f(a_ref, b_ref)
        out_test = compiled_f(a_test, b_test)
        # First out is a TwoTensor, second is an ordinary tensor
        self.assertEqual(out_ref[0].a, out_test[0].a)
        self.assertEqual(out_ref[0].b, out_test[0].b)
        self.assertEqual(out_ref[1], out_test[1])

        # We compiled our graph assuming type(grad_out[1]) == torch.Tensor,
        # but we were wrong: in the below tests, it is a subclass.
        # This will eventually require a repartition + recompile
        with self.assertRaisesRegex(
            AssertionError,
            "incorrectly attempted to compile the backward with incorrect subclass metadata"
        ):
            (out_test[0] + out_test[1]).sum().backward()

    def test_aot_dispatch_output_alias(self):
        # a is a tensor, b is a TwoTensor
        def f(a, b):
            return b.view(b.shape), a * b

        b1_ref = torch.ones(3, 3, requires_grad=True)
        b2_ref = torch.ones(3, 3, requires_grad=True)
        b_ref = TwoTensor(b1_ref, b2_ref)
        a_ref = torch.ones(3, 3, requires_grad=True)

        b1_test = b1_ref.clone().detach().requires_grad_(True)
        b2_test = b2_ref.clone().detach().requires_grad_(True)
        b_test = TwoTensor(b1_test, b2_test)
        a_test = a_ref.clone().detach().requires_grad_(True)

        compiled_f = aot_function(
            f,
            fw_compiler=nop,
            bw_compiler=nop,
            partition_fn=min_cut_rematerialization_partition
        )
        out_ref1, out_ref2 = f(a_ref, b_ref)
        out_test1, out_test2 = compiled_f(a_test, b_test)
        self.assertEqual(out_ref1, out_test1)
        self.assertEqual(out_ref2.a, out_test2.a)
        self.assertEqual(out_ref2.b, out_test2.b)

        (out_ref1 + out_ref2).sum().backward()
        (out_test1 + out_test2).sum().backward()
        # Both grad_inputs are TwoTensor
        self.assertEqual(a_ref.grad.a, a_test.grad.a)
        self.assertEqual(a_ref.grad.b, a_test.grad.b)
        self.assertEqual(b_ref.grad.a, b_test.grad.a)
        self.assertEqual(b_ref.grad.b, b_test.grad.b)

    def test_aot_dispatch_input_mutation(self):
        def f(a, b):
            a.mul_(2)
            b.mul_(3)
            return a + b

        b1_ref = torch.ones(3, 3, requires_grad=True)
        b2_ref = torch.ones(3, 3, requires_grad=True)
        b_ref_base = TwoTensor(b1_ref, b2_ref)
        a_ref_base = torch.ones(3, 3, requires_grad=True)
        b_ref = b_ref_base + 1
        a_ref = a_ref_base + 1

        b1_test = b1_ref.clone().detach().requires_grad_(True)
        b2_test = b2_ref.clone().detach().requires_grad_(True)
        b_test_base = TwoTensor(b1_test, b2_test)
        a_test_base = a_ref_base.clone().detach().requires_grad_(True)
        b_test = b_test_base + 1
        a_test = a_test_base + 1

        compiled_f = aot_function(
            f,
            fw_compiler=nop,
            bw_compiler=nop,
            partition_fn=min_cut_rematerialization_partition
        )
        out_ref = f(a_ref, b_ref)
        out_test = compiled_f(a_test, b_test)
        self.assertEqual(out_ref.a, out_test.a)
        self.assertEqual(out_ref.b, out_test.b)

        # confirm input mutations worked
        self.assertEqual(a_test, a_ref)
        self.assertEqual(b_test.a, b_ref.a)
        self.assertEqual(b_test.b, b_ref.b)

        # NOTE: we need to use b in our gradient compute. Otherwise we will need to recompile teh backward.
        (b_ref * out_ref).sum().backward()
        (b_test * out_test).sum().backward()
        # Both grad_inputs are TwoTensor
        self.assertEqual(a_ref_base.grad.a, a_test_base.grad.a)
        self.assertEqual(a_ref_base.grad.b, a_test_base.grad.b)
        self.assertEqual(b_ref_base.grad.a, b_test_base.grad.a)
        self.assertEqual(b_ref_base.grad.b, b_test_base.grad.b)

    # NB: Metadata mutation for subclasses is currently broken and disabled
    # See https://github.com/pytorch/pytorch/issues/114975
    @unittest.expectedFailure
    def test_aot_dispatch_input_metadata_mutation(self):
        def f(a, b):
            a.t_()
            b.unsqueeze_(0)
            return a + b

        b1_ref = torch.arange(9, requires_grad=True, dtype=torch.float32).reshape(3, 3)
        b2_ref = torch.arange(9, requires_grad=True, dtype=torch.float32).reshape(3, 3)
        b_ref_base = TwoTensor(b1_ref, b2_ref)
        a_ref_base = torch.arange(9, dtype=torch.float32).reshape(3, 3).detach().requires_grad_(True)
        b_ref = b_ref_base + 1
        a_ref = a_ref_base + 1

        b1_test = b1_ref.clone().detach().requires_grad_(True)
        b2_test = b2_ref.clone().detach().requires_grad_(True)
        b_test_base = TwoTensor(b1_test, b2_test)
        a_test_base = a_ref_base.clone().detach().requires_grad_(True)
        b_test = b_test_base + 1
        a_test = a_test_base + 1

        compiled_f = aot_function(
            f,
            fw_compiler=nop,
            bw_compiler=nop,
            partition_fn=min_cut_rematerialization_partition
        )
        out_ref = f(a_ref, b_ref)
        out_test = compiled_f(a_test, b_test)
        self.assertEqual(out_ref.a, out_test.a)
        self.assertEqual(out_ref.b, out_test.b)

        # confirm input mutations worked
        self.assertEqual(a_test, a_ref)
        self.assertEqual(b_test.a, b_ref.a)
        self.assertEqual(b_test.b, b_ref.b)

        # NOTE: we need to use b in our gradient compute. Otherwise we will need to recompile the backward.
        (b_ref * out_ref).sum().backward()
        (b_test * out_test).sum().backward()
        # Both grad_inputs are TwoTensor
        self.assertEqual(a_ref_base.grad.a, a_test_base.grad.a)
        self.assertEqual(a_ref_base.grad.b, a_test_base.grad.b)
        self.assertEqual(b_ref_base.grad.a, b_test_base.grad.a)
        self.assertEqual(b_ref_base.grad.b, b_test_base.grad.b)

    # NB: Metadata mutation for subclasses is currently broken and disabled
    # See https://github.com/pytorch/pytorch/issues/114975
    @unittest.expectedFailure
    def test_aot_dispatch_input_data_and_metadata_mutation(self):
        def f(a, b):
            a.t_()
            b.unsqueeze_(0)
            a.mul_(2)
            b.mul_(3)
            return a + b

        b1_ref = torch.arange(9, requires_grad=True, dtype=torch.float32).reshape(3, 3)
        b2_ref = torch.arange(9, requires_grad=True, dtype=torch.float32).reshape(3, 3)
        b_ref_base = TwoTensor(b1_ref, b2_ref)
        a_ref_base = torch.arange(9, dtype=torch.float32).reshape(3, 3).detach().requires_grad_(True)
        b_ref = b_ref_base + 1
        a_ref = a_ref_base + 1

        b1_test = b1_ref.clone().detach().requires_grad_(True)
        b2_test = b2_ref.clone().detach().requires_grad_(True)
        b_test_base = TwoTensor(b1_test, b2_test)
        a_test_base = a_ref_base.clone().detach().requires_grad_(True)
        b_test = b_test_base + 1
        a_test = a_test_base + 1

        compiled_f = aot_function(
            f,
            fw_compiler=nop,
            bw_compiler=nop,
            partition_fn=min_cut_rematerialization_partition
        )
        out_ref = f(a_ref, b_ref)
        out_test = compiled_f(a_test, b_test)
        self.assertEqual(out_ref.a, out_test.a)
        self.assertEqual(out_ref.b, out_test.b)

        # confirm input mutations worked
        self.assertEqual(a_test, a_ref)
        self.assertEqual(b_test.a, b_ref.a)
        self.assertEqual(b_test.b, b_ref.b)

        # NOTE: we need to use b in our gradient compute. Otherwise we will need to recompile the backward.
        (b_ref * out_ref).sum().backward()
        (b_test * out_test).sum().backward()
        # Both grad_inputs are TwoTensor
        self.assertEqual(a_ref_base.grad.a, a_test_base.grad.a)
        self.assertEqual(a_ref_base.grad.b, a_test_base.grad.b)
        self.assertEqual(b_ref_base.grad.a, b_test_base.grad.a)
        self.assertEqual(b_ref_base.grad.b, b_test_base.grad.b)

    def test_aot_dispatch_input_mutation_and_output_alias(self):
        def f(a, b):
            a.mul_(2)
            b.mul_(3)
            return b.view(b.shape), a + b

        b1_ref = torch.arange(9, requires_grad=True, dtype=torch.float32).reshape(3, 3)
        b2_ref = torch.arange(9, requires_grad=True, dtype=torch.float32).reshape(3, 3)
        b_ref_base = TwoTensor(b1_ref, b2_ref)
        a_ref_base = torch.arange(9, dtype=torch.float32).reshape(3, 3).detach().requires_grad_(True)
        b_ref = b_ref_base + 1
        a_ref = a_ref_base + 1

        b1_test = b1_ref.clone().detach().requires_grad_(True)
        b2_test = b2_ref.clone().detach().requires_grad_(True)
        b_test_base = TwoTensor(b1_test, b2_test)
        a_test_base = a_ref_base.clone().detach().requires_grad_(True)
        b_test = b_test_base + 1
        a_test = a_test_base + 1

        compiled_f = aot_function(
            f,
            fw_compiler=nop,
            bw_compiler=nop,
            partition_fn=min_cut_rematerialization_partition
        )
        out_ref1, out_ref2 = f(a_ref, b_ref)
        out_test1, out_test2 = compiled_f(a_test, b_test)
        self.assertEqual(out_ref1.a, out_test1.a)
        self.assertEqual(out_ref1.b, out_test1.b)
        self.assertEqual(out_ref2.a, out_test2.a)
        self.assertEqual(out_ref2.b, out_test2.b)

        # confirm input mutations worked
        self.assertEqual(a_test, a_ref)
        self.assertEqual(b_test.a, b_ref.a)
        self.assertEqual(b_test.b, b_ref.b)

        (out_ref1 * out_ref2).sum().backward()
        (out_test1 * out_test2).sum().backward()
        # Both grad_inputs are TwoTensors
        self.assertEqual(a_ref_base.grad.a, a_test_base.grad.a)
        self.assertEqual(a_ref_base.grad.b, a_test_base.grad.b)


class TestAOTModuleSimplified(AOTTestCase):
    def test_aot_module_simplified(self):
        class MockModule(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(20, 30)

            def forward(self, x, y):
                return (self.linear(x) + y, )

        mod = MockModule()
        mod.zero_grad()

        x = torch.randn(128, 20, requires_grad=True)
        y = torch.randn(128, 30, requires_grad=True)
        inputs = [x, y]
        cloned_inputs = [x.detach().clone().requires_grad_(True) for x in inputs]

        ref = mod(*inputs)
        ref[0].sum().backward()

        compiled_f = aot_module_simplified(mod, cloned_inputs, nop)
        mod.zero_grad()
        res = compiled_f(*cloned_inputs)
        res[0].sum().backward()

        assert torch.allclose(ref[0], res[0])
        assert torch.allclose(inputs[0].grad, cloned_inputs[0].grad)
        assert torch.allclose(inputs[1].grad, cloned_inputs[1].grad)

    def test_aot_module_simplified_dynamic(self):
        class MockModule(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(20, 30)

            def forward(self, x, y):
                return (self.linear(x) + y, )

        mod = MockModule()

        shape_env = ShapeEnv()
        fake_mode = FakeTensorMode(shape_env=shape_env)

        x = torch.randn(128, 20, requires_grad=True)
        y = torch.randn(128, 30, requires_grad=True)

        inputs = [x, y]
        fake_inputs = [fake_mode.from_tensor(x) for x in inputs]
        compiled_f = aot_module_simplified(mod, fake_inputs, nop)

        ref = mod(*inputs)
        ref[0].sum().backward()

        cloned_inputs = [x.detach().clone().requires_grad_(True) for x in inputs]
        res = compiled_f(*cloned_inputs)
        res[0].sum().backward()

        self.assertExpectedInline(shape_env.format_guards(), """\
 - Eq(s1, 20)
 - Eq(s2, 30)""")

        assert torch.allclose(ref[0], res[0])
        assert torch.allclose(inputs[0].grad, cloned_inputs[0].grad)
        assert torch.allclose(inputs[1].grad, cloned_inputs[1].grad)

    # https://github.com/pytorch/pytorch/issues/105327
    def test_lift_fresh_copy_in_graph(self):
        class MyMod(torch.nn.Module):
            def forward(self, x):
                _tensor_constant0 = torch.tensor([1])
                lift_fresh_copy = torch.ops.aten.lift_fresh_copy.default(_tensor_constant0)
                y = x.mul(lift_fresh_copy)
                return (y,)

        mod = MyMod()
        shape_env = ShapeEnv()
        fake_mode = FakeTensorMode(shape_env=shape_env)
        x = torch.ones(4, requires_grad=True)
        inputs = [x]
        fake_inputs = [fake_mode.from_tensor(x) for x in inputs]
        compiled_f = aot_module_simplified(mod, fake_inputs, nop)

        out_ref = mod(x)
        out_test = compiled_f(x)
        self.assertEqual(out_ref[0].detach(), out_test[0].detach())

    def test_inference_python_dispatcher(self):
        # Extracted from unet
        class MockModule(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.upsample = torch.nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)

            def forward(self, x):
                return (self.upsample(x), )

        mod = MockModule()
        shape_env = ShapeEnv()
        fake_mode = FakeTensorMode(shape_env=shape_env)
        x = torch.randn(2, 512, 40, 59)  # NB: must not require grad
        inputs = [x]
        fake_inputs = [fake_mode.from_tensor(x) for x in inputs]
        compiled_f = aot_module_simplified(mod, fake_inputs, nop)

    def test_aot_module_simplified_preserves_stack_trace(self):
        class MockModule(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(20, 30)

            def forward(self, x, y):
                z = self.linear(x)
                z = z + y
                z = z.relu()
                return (z, )

        tracer = torch.fx.Tracer()
        tracer.record_stack_traces = True
        graph = tracer.trace(MockModule())
        mod = torch.fx.GraphModule(tracer.root, graph)

        for node in mod.graph.nodes:
            if node.op == 'output':
                continue
            self.assertTrue(node.stack_trace is not None)
            assert 'test_aotdispatch.py' in node.stack_trace

        def assert_compiler(gm: torch.fx.GraphModule, _):
            for node in gm.graph.nodes:
                if node.op == 'output' or node.op == 'placeholder':
                    continue
                self.assertTrue(node.stack_trace is not None)
                assert 'test_aotdispatch.py' in node.stack_trace
            return gm.forward  # return a python callable

        x = torch.randn(128, 20, requires_grad=True)
        y = torch.randn(128, 30, requires_grad=True)
        inputs = [x, y]

        compiled_f = aot_module_simplified(mod, inputs, fw_compiler=assert_compiler, bw_compiler=assert_compiler)
        res = compiled_f(*inputs)
        res[0].sum().backward()

    def test_aot_module_simplified_preserves_stack_trace_from_mutation(self):
        class MockModule(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x):
                x_view = x[0]
                x_view.mul_(2)
                return (x + x, )

        tracer = torch.fx.Tracer()
        tracer.record_stack_traces = True
        graph = tracer.trace(MockModule())
        mod = torch.fx.GraphModule(tracer.root, graph)

        for node in mod.graph.nodes:
            if node.op == 'output':
                continue
            self.assertTrue(node.stack_trace is not None)
            assert 'test_aotdispatch.py' in node.stack_trace

        def assert_compiler(gm: torch.fx.GraphModule, _):
            assert torch.ops.aten.copy_.default in [x.target for x in gm.graph.nodes]
            for node in gm.graph.nodes:
                if node.target == torch.ops.aten.copy_.default:
                    assert 'stack_trace' in node.meta
                    assert 'x_view.mul_(2)' in node.meta['stack_trace']
            return gm.forward  # return a python callable

        x = torch.randn(128, 20)
        inputs = [x]

        aot_module_simplified(
            mod,
            inputs,
            fw_compiler=assert_compiler,
            bw_compiler=assert_compiler,
            keep_inference_input_mutations=True,
        )

    def test_aot_module_simplified_fake_tensor_gm_raises(self):
        fake_mode = torch._subclasses.fake_tensor.FakeTensorMode()
        real_x = torch.randn(4, requires_grad=True)
        fake_x = fake_mode.from_tensor(real_x)
        real_z = torch.randn(4)
        fake_z = fake_mode.from_tensor(real_z)

        class MockModule(torch.nn.Module):
            def forward(self, x):
                # Accessing a free variable fake tensor will look like a
                # constant to make_fx, and result in the tensor being traced
                # into the graph, which is an error condition.  Make sure we
                # report adequately in this case.
                return (x + fake_z, )

        with self.assertRaisesRegex(
            AssertionError, "Unexpected fake"
        ):
            aot_module_simplified(MockModule(), (fake_x,), nop)


# entries in here don't work and need to be fixed.
# Each one of these is a bug (or needs to be investigated)
aot_autograd_failures = {
    # data-dependent control flow
    xfail('cov'),
    xfail('nn.functional.gaussian_nll_loss'),
    xfail('tensor_split'),
    xfail('corrcoef'),
    xfail('quantile'),
    xfail('nanquantile'),
    xfail('narrow'),
    xfail('istft'),
    xfail('linalg.eig'),

    skip('as_strided_scatter'),
    skip('as_strided', 'partial_views'),  # flaky

    # Given input size: (s0xs1x2). Calculated output size: ...
    skip('max_pool2d_with_indices_backward'),

    skip('nn.functional.nll_loss', ''),  # UBSAN failure!

    # Misc
    xfail('to_sparse'),
    xfail('corrcoef'),
    xfail('cov'),
    xfail('chalf'),  # RuntimeError: "sum_cpu" not implemented for 'ComplexHalf'
    xfail('sparse.sampled_addmm'),
    xfail('sparse.mm', 'reduce'),
    skip('nn.functional.binary_cross_entropy_with_logits'),  # seems to fail sometimes?
    skip('nn.functional.margin_ranking_loss'),  # seems flaky
    skip('linalg.lu_solve'),  # flaky
    decorate('matmul', decorator=unittest.skipIf(IS_ARM64, 'flaky')),
    decorate('__rmatmul__', decorator=unittest.skipIf(IS_ARM64, 'flaky')),
    # overrides atol=1e-4, rtol=1e-5 would do as well
    decorate('svd_lowrank', decorator=toleranceOverride({torch.float32: tol(atol=1e-04, rtol=1e-05)})),
    decorate('linalg.householder_product', decorator=unittest.skipIf(IS_MACOS and IS_X86, 'flaky')),
    decorate('linalg.pinv', 'singular', decorator=toleranceOverride({torch.float32: tol(atol=1e-05, rtol=1e-05)})),
    decorate('nn.functional.interpolate', 'bicubic', decorator=toleranceOverride({torch.float32: tol(atol=1e-04, rtol=1e-05)})),
    # conv2d sometimes nondeterministic in this config?
    decorate('nn.functional.conv2d', decorator=unittest.skipIf(IS_ARM64, "flaky")),
}

symbolic_aot_autograd_failures = {
    xfail('combinations', ''),  # aten.masked_select.default
    xfail('index_fill', ''),  # Cannot call sizes() on tensor with symbolic sizes/strides
    xfail('kthvalue', ''),  # Cannot call sizes() on tensor with symbolic sizes/strides
    xfail('linalg.lstsq', ''),  # aten.linalg_lstsq.default - couldn't find symbolic meta function/decomposition
    xfail('linalg.lstsq', 'grad_oriented'),  # aten.linalg_lstsq.default - couldn't find symbolic meta funct...
    xfail('linalg.lu_solve', ''),  # aten.linalg_lu_solve.default - couldn't find symbolic meta function/deco...
    skip('nn.functional.batch_norm', ''),  # '0 is not tracked with proxy for <torch.fx.experimental.proxy_te..
    xfail('nn.functional.binary_cross_entropy', ''),  # aten.fill_.Scalar - couldn't find symbolic meta funct...
    xfail('nn.functional.cross_entropy', ''),  # Cannot call sizes() on tensor with symbolic sizes/strides
    xfail('nn.functional.ctc_loss', ''),  # aten._ctc_loss.Tensor - couldn't find symbolic meta function/deco...
    xfail('nn.functional.embedding_bag', ''),  # Cannot call sizes() on tensor with symbolic sizes/strides
    xfail('nn.functional.fractional_max_pool2d', ''),  # rand() received an invalid combination of arguments - g...
    xfail('nn.functional.fractional_max_pool3d', ''),  # rand() received an invalid combination of arguments - g...
    xfail('nn.functional.group_norm', ''),  # Cannot call sizes() on tensor with symbolic sizes/strides
    xfail('nn.functional.nll_loss', ''),  # Cannot call sizes() on tensor with symbolic sizes/strides
    xfail('_segment_reduce', 'lengths'),  # aten.segment_reduce.default - couldn't find symbolic meta functio...
    xfail('_segment_reduce', 'offsets'),  # aten.segment_reduce.default - couldn't find symbolic meta functio...
    xfail('trace', ''),  # Cannot call sizes() on tensor with symbolic sizes/strides
    xfail('_upsample_bilinear2d_aa'),  # RuntimeError: isIntList() INTERNAL ASSERT FAILED  Expected IntList but got GenericList
    decorate('linalg.householder_product', decorator=unittest.skipIf(IS_MACOS and IS_X86, 'flaky')),

    # many complex operators incorrect striding, metadata
    xfail('fft.fft', ''),
    xfail('fft.hfft2', ''),
    xfail('fft.hfft', ''),
    xfail('fft.hfftn', ''),
    xfail('fft.ifft', ''),
    xfail('fft.ihfft2', ''),
    xfail('fft.ihfft', ''),
    xfail('fft.ihfftn', ''),
    xfail('fft.irfft2', ''),
    xfail('fft.irfft', ''),
    xfail('fft.irfftn', ''),
    xfail('fft.rfft2', ''),
    xfail('fft.rfft', ''),
    xfail('fft.rfftn', ''),

    xfail('stft', ''),  # Cannot call sizes() on tensor with symbolic sizes/strides
}

def _test_aot_autograd_helper(self, device, dtype, op, dynamic=False):
    if not op.supports_autograd:
        self.skipTest("Op does not support autograd")

    # aot_autograd_check is able to check data specialization by
    # randomizing the inputs. Here's a list of ops that really do not
    # like random inputs for which we want to disable that.
    cant_check_data_specialization = set({
        'nn.functional.max_unpool1d',
        'nn.functional.max_unpool2d',
        'nn.functional.max_unpool3d',
    })
    try_check_data_specialization = op.name not in cant_check_data_specialization

    sample_inputs_itr = op.sample_inputs(device, dtype, requires_grad=True)
    for sample_input in sample_inputs_itr:
        t_args = [sample_input.input] + list(sample_input.args)
        t_kwargs = sample_input.kwargs
        try:
            aot_autograd_check(
                op.op, t_args, t_kwargs, dynamic,
                self.assertRaisesRegex, self.assertEqual,
                check_gradients=True,
                try_check_data_specialization=try_check_data_specialization)
        except DynamicOutputShapeException:
            self.skipTest("Dynamic output shape operation in trace")
        except GuardOnDataDependentSymNode:
            # Carveout for getitem; I don't want to xfail the entire test
            # because that will reject known to be good tests see
            # https://github.com/pytorch/pytorch/issues/94705
            if op.name == "__getitem__":
                self.skipTest("Dynamic output shape operation in trace")
            else:
                raise

def _test_aot_autograd_module_helper(self, device, dtype, training, module_info, *, dynamic=False):
    module_cls = module_info.module_cls
    module_inputs = module_info.module_inputs_func(module_info, device=device, dtype=dtype,
                                                   requires_grad=True, training=training)
    for module_input in module_inputs:
        if module_input.forward_input is None:
            continue

        args, kwargs = module_input.constructor_input.args, module_input.constructor_input.kwargs
        m = module_cls(*args, **kwargs)
        m.to(device).to(dtype)
        m.train(training)

        # Lazy modules need to see an input first to initialize params.
        args, kwargs = module_input.forward_input.args, module_input.forward_input.kwargs
        flat_args, args_spec = pytree.tree_flatten((args, kwargs))

        # PackedSequence is only used for RNNs. It might be possible to fake-ify if they're pytrees but
        # torchdynamo already doesn't support RNNs
        if any(tuple(isinstance(flat_arg, PackedSequence) for flat_arg in flat_args)):
            continue

        if issubclass(module_info.module_cls, torch.nn.modules.lazy.LazyModuleMixin):
            with torch.no_grad():
                m(*args, **kwargs)

        sentinel_val = -42
        is_tensor_spec = [sentinel_val if isinstance(arg, torch.Tensor)
                          else arg for arg in flat_args]
        args = [arg for arg in flat_args if isinstance(arg, torch.Tensor)]

        def f(params_buffers_args):
            named_params, named_buffers, args = params_buffers_args
            cur_flat_args = list(is_tensor_spec)
            args = iter(args)
            for idx, v in enumerate(cur_flat_args):
                if v == sentinel_val:
                    cur_flat_args[idx] = next(args)
            c_args, c_kwargs = pytree.tree_unflatten(cur_flat_args, args_spec)
            params_and_buffers = {**named_params, **named_buffers}
            return torch.func.functional_call(m, params_and_buffers, c_args, c_kwargs)

        named_params = dict(m.named_parameters(remove_duplicate=False))
        named_buffers = dict(m.named_buffers(remove_duplicate=False))
        num_params_buffers = len(named_params) + len(named_buffers)
        compiled_f = aot_function(f, nop, num_params_buffers=num_params_buffers, dynamic=dynamic)
        params_buffers_args = [named_params, named_buffers, args]
        _test_aot_autograd_forwards_backwards_helper(
            f, compiled_f, params_buffers_args,
            self.assertRaisesRegex, self.assertEqual, True)


class TestEagerFusionOpInfo(AOTTestCase):
    @ops(op_db + control_flow_opinfo_db, allowed_dtypes=(torch.float,))
    @skipOps('TestEagerFusionOpInfo', 'test_aot_autograd_exhaustive', aot_autograd_failures)
    def test_aot_autograd_exhaustive(self, device, dtype, op):
        _test_aot_autograd_helper(self, device, dtype, op)

    @ops(op_db + control_flow_opinfo_db, allowed_dtypes=(torch.float,))
    @patch("functorch.compile.config.debug_assert", True)
    @skipOps('TestEagerFusionOpInfo', 'test_aot_autograd_symbolic_exhaustive',
             aot_autograd_failures | symbolic_aot_autograd_failures)
    def test_aot_autograd_symbolic_exhaustive(self, device, dtype, op):
        _test_aot_autograd_helper(self, device, dtype, op, dynamic=True)


aot_autograd_module_failures = set({
    torch.nn.CTCLoss,  # torch._subclasses.fake_tensor.DynamicOutputShapeException: aten._ctc_loss.default
    torch.nn.GaussianNLLLoss,  # RuntimeError: It appears that you're trying to get value out
                               # of a tracing tensor with aten._local_scalar_dense.default -
                               # erroring out! It's likely that this is caused by data-dependent
                               # control flow or similar.
    torch.nn.MultiLabelMarginLoss,  # AssertionError: The values for attribute 'shape' do not match:
                                    # torch.Size([1]) != torch.Size([]). Outputs of the operator are different in
                                    # eager-mode PyTorch vs AOTAutograd. This means the operator will have incorrect
                                    # output underneath torch.compile. This could be because the operator's
                                    # implementation not traceable or that there is a bug in AOTAutograd.
    torch.nn.TransformerEncoder,  # DataDependentOutputException: aten.eq compares a mask input
                                  # to a causal mask tensor, to see if Boolean is_causal should be set
                                  # for TrnasformerEncoder layers, MHA and sdp custom kernels
    torch.nn.Transformer,  # DataDependentOutputException: aten.equal compares a mask input
                           # to a causal mask tensor, to see if Boolean is_causal should be set
                           # for TransformerEncoder layers, MHA and sdp custom kernels
                           # (this bubbles up to Transformer)
})

symbolic_aot_autograd_module_failures = {
    torch.nn.Transformer,  # DataDependentOutputException: aten.equal compares a mask input to a mask producing a bool
    torch.nn.TransformerEncoder,  # DataDependentOutputException: aten.equal compares a mask input to a mask producing a bool
    torch.nn.GaussianNLLLoss,  # NotImplementedError: local_scalar_dense/item NYI for torch.bool
    torch.nn.GroupNorm,  # in native_group_norm_backward cpg, _rem = divmod(C, group)
                         # TypeError: unsupported operand type(s) for divmod(): 'SymInt' and 'int'
    torch.nn.FractionalMaxPool2d,  # int() argument must be a string, a bytes-like object or a number, not 'SymFloat'
    torch.nn.FractionalMaxPool3d,  # int() argument must be a string, a bytes-like object or a number, not 'SymFloat'
    torch.nn.BCELoss,  # new_size = _infer_size(target.size(), weight.size())
                       # RuntimeError: expected int at position 0, but got: SymInt
}


class TestEagerFusionModuleInfo(AOTTestCase):
    @modules(module_db, allowed_dtypes=(torch.float,))
    @decorateForModules(unittest.expectedFailure, aot_autograd_module_failures)
    def test_aot_autograd_module_exhaustive(self, device, dtype, training, module_info):
        _test_aot_autograd_module_helper(self, device, dtype, training, module_info)

    @modules(module_db, allowed_dtypes=(torch.float,))
    @decorateForModules(unittest.expectedFailure,
                        aot_autograd_module_failures | symbolic_aot_autograd_module_failures)
    def test_aot_autograd_symbolic_module_exhaustive(self, device, dtype, training, module_info):
        _test_aot_autograd_module_helper(self, device, dtype, training, module_info, dynamic=True)


instantiate_parametrized_tests(TestAOTAutograd)
only_for = ("cpu")
instantiate_device_type_tests(
    TestPythonKey,
    globals(),
    only_for=only_for,
)
instantiate_device_type_tests(TestEagerFusionOpInfo, globals(), only_for=only_for)
instantiate_device_type_tests(TestEagerFusionModuleInfo, globals(), only_for=only_for)


if __name__ == '__main__':
    run_tests()
