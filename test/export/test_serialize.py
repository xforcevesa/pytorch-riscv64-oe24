"""
PYTEST_DONT_REWRITE (prevents pytest from rewriting assertions, which interferes
with test_sym_bool)
"""
# Owner(s): ["oncall: export"]
import copy
import io
import pathlib
import tempfile
import unittest
import zipfile

import torch
import torch._dynamo as torchdynamo
import torch.utils._pytree as pytree
from torch._export.db.case import ExportCase, normalize_inputs, SupportLevel
from torch._export.db.examples import all_examples
from torch._export.serde.serialize import (
    canonicalize,
    deserialize,
    ExportedProgramDeserializer,
    ExportedProgramSerializer,
    serialize,
    SerializeError,
)
from torch._higher_order_ops.torchbind import enable_torchbind_tracing
from torch._subclasses.fake_tensor import FakeTensor, FakeTensorMode
from torch.export import Dim, export, load, save
from torch.fx.experimental.symbolic_shapes import is_concrete_int
from torch.testing._internal.common_utils import (
    find_library_location,
    instantiate_parametrized_tests,
    IS_FBCODE,
    IS_MACOS,
    IS_SANDCASTLE,
    IS_WINDOWS,
    parametrize,
    run_tests,
    TemporaryFileName,
    TestCase,
)


def get_filtered_export_db_tests():
    return [
        (name, case)
        for name, case in all_examples().items()
        if case.support_level == SupportLevel.SUPPORTED
    ]


def cleanup_op(opname):
    ns, name = opname.split("::")
    if not hasattr(torch.ops, ns):
        return
    actual_ns = getattr(torch.ops, ns)
    if not hasattr(actual_ns, name):
        return
    delattr(actual_ns, name)


@unittest.skipIf(not torchdynamo.is_dynamo_supported(), "dynamo doesn't support")
class TestSerialize(TestCase):
    def test_predispatch_export_with_autograd_op(self):
        class Foo(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x):
                with torch.enable_grad():
                    return x + x

        inp = (torch.ones(10),)
        with torch.no_grad():
            from torch.export._trace import _export
            ep = _export(Foo(), inp, pre_dispatch=True)

        buffer = io.BytesIO()
        torch.export.save(ep, buffer)
        buffer.seek(0)
        loaded_ep = torch.export.load(buffer)

        exp_out = ep.module()(*inp)
        actual_out = loaded_ep.module()(*inp)
        self.assertEqual(exp_out, actual_out)
        self.assertEqual(exp_out.requires_grad, actual_out.requires_grad)


    def test_serialize_multiple_returns_from_node(self) -> None:
        class MyModule(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x, w, b):
                return torch.nn.functional.layer_norm(
                    x,
                    x.size()[1:],
                    weight=w,
                    bias=b,
                    eps=1e-5,
                )

        exported_module = export(
            MyModule(),
            (
                torch.ones([512, 512], requires_grad=True),
                torch.ones([512]),
                torch.ones([512]),
            ),
        )

        serialized = ExportedProgramSerializer().serialize(exported_module)
        node = serialized.exported_program.graph_module.graph.nodes[-1]
        self.assertEqual(node.target, "torch.ops.aten.native_layer_norm.default")
        # aten::native_layer_norm returns 3 tensors
        self.assertEqual(len(node.outputs), 3)

        # check the names are unique
        seen = set()
        for output in node.outputs:
            name = output.as_tensor.name
            self.assertNotIn(name, seen)
            seen.add(name)

    def test_serialize_list_returns(self) -> None:
        class MyModule(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x):
                return torch.split(x, 2)

        input = torch.arange(10.0).reshape(5, 2)
        input.requires_grad = True
        exported_module = export(MyModule(), (input,)).run_decompositions()

        serialized = ExportedProgramSerializer().serialize(exported_module)
        node = serialized.exported_program.graph_module.graph.nodes[-1]
        # split.Tensor gets decomposed to split_with_sizes by the core ATen decomposition table
        self.assertEqual(node.target, "torch.ops.aten.split_with_sizes.default")
        self.assertEqual(len(node.outputs), 1)
        # Input looks like:
        # tensor([[0, 1],
        #         [2, 3],
        #         [4, 5],
        #         [6, 7],
        #         [8, 9]])
        # Output looks like:
        # (tensor([[0, 1],
        #          [2, 3]]),
        #  tensor([[4, 5],
        #          [6, 7]]),
        #  tensor([[8, 9]]))
        self.assertEqual(len(node.outputs[0].as_tensors), 3)

        # check the names are unique
        seen = set()
        for output in node.outputs[0].as_tensors:
            name = output.name
            self.assertNotIn(name, seen)
            seen.add(name)

    def test_multi_return_some_unused(self) -> None:
        """
        Make sure the serialized output matches the op schema, even if some of
        the arguments are never used in the graph.
        """

        class MyModule(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x):
                return torch.ops.aten.var_mean.correction(x, [1])[0]

        exported_module = export(
            MyModule(),
            (torch.ones([512, 512], requires_grad=True),),
        ).run_decompositions()

        serialized = ExportedProgramSerializer().serialize(exported_module)
        node = serialized.exported_program.graph_module.graph.nodes[-1]
        self.assertEqual(node.target, "torch.ops.aten.var_mean.correction")
        self.assertEqual(len(node.outputs), 2)

        # check the names are unique
        seen = set()
        for output in node.outputs:
            name = output.as_tensor.name
            self.assertNotIn(name, seen)
            seen.add(name)

    def test_kwargs_default(self) -> None:
        """
        Tests that the kwargs default values are serialized even if they are not
        specified
        """
        class Foo(torch.nn.Module):
            def forward(self, x: torch.Tensor) -> torch.Tensor:
                values = torch.randn(3, 2)
                return torch.searchsorted(x, values, side="right", right=True)

        f = Foo()

        x, _ = torch.sort(torch.randn(3, 4))
        exported_module = export(f, (x,)).run_decompositions()
        serialized = ExportedProgramSerializer().serialize(exported_module)

        node = serialized.exported_program.graph_module.graph.nodes[-1]
        self.assertEqual(node.target, "torch.ops.aten.searchsorted.Tensor")
        self.assertEqual(len(node.inputs), 4)
        self.assertEqual(node.inputs[2].name, "right")
        self.assertEqual(node.inputs[2].arg.as_bool, True)
        self.assertEqual(node.inputs[3].name, "side")
        self.assertEqual(node.inputs[3].arg.as_string, "right")

    def test_canonicalize(self) -> None:
        class Module(torch.nn.Module):
            def forward(self, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
                a = y + x
                b = x + y
                return b + a

        ep = torch.export.export(Module(), (torch.randn(3, 2), torch.randn(3, 2)))
        s = ExportedProgramSerializer().serialize(ep)
        c = canonicalize(s.exported_program)
        g = c.graph_module.graph
        self.assertLess(
            g.nodes[0].inputs[0].arg.as_tensor.name,
            g.nodes[1].inputs[0].arg.as_tensor.name
        )

@unittest.skipIf(IS_WINDOWS, "Windows not supported for this test")
@unittest.skipIf(not torchdynamo.is_dynamo_supported(), "dynamo doesn't support")
class TestDeserialize(TestCase):
    def _check_graph_nodes(self, gm1, gm2, _check_meta=True):
        # TODO: The _check_meta flag bypasses checking for
        # source_fn/nn_module_stack as there is an issue with
        # roundtripping the source_fn value on torch.ops.map nodes
        # original source_fn: <functorch.experimental._map.MapWrapper object at 0x7f80a0549930>
        # deserialized source_fn: 'functorch.experimental._map.map'

        self.assertEqual(len(gm1.graph.nodes), len(gm2.graph.nodes))

        for node1, node2 in zip(gm1.graph.nodes, gm2.graph.nodes):
            self.assertEqual(node1.op, node2.op)
            if node1.op == "call_function":
                # Check "val" metadata
                val1 = node1.meta.get("val", None)
                val2 = node2.meta.get("val", None)
                if val1 is None or val2 is None:
                    # Either both are None
                    self.assertEqual(val1, val2)
                elif isinstance(val1, FakeTensor) and isinstance(val2, FakeTensor):
                    # Or both are fake tensors with the same shape/dtype
                    self.assertEqual(len(val1.shape), len(val2.shape))
                    for s1, s2 in zip(val1.shape, val2.shape):
                        if is_concrete_int(s1) and is_concrete_int(s2):
                            self.assertEqual(s1, s2)
                        else:
                            self.assertEqual(str(s1), str(s2))
                    self.assertEqual(val1.dtype, val2.dtype)
                elif isinstance(val1, (list, tuple)) and isinstance(val2, (list, tuple)):
                    # Or both are fake tensors lists with one element and with the
                    # same shape/dtype
                    for v1, v2 in zip(pytree.tree_leaves(val1), pytree.tree_leaves(val2)):
                        if isinstance(v1, FakeTensor):
                            self.assertEqual(v1.shape, v2.shape)
                            self.assertEqual(v1.dtype, v2.dtype)
                else:
                    # For expressions like 's0 < 10' can only compare through string
                    self.assertEqual(str(val1), str(val2))

                # Check "stack_trace" metadata
                self.assertEqual(
                    node1.meta.get("stack_trace", None),
                    node2.meta.get("stack_trace", None),
                )

                if node1.target == torch.ops.higher_order.cond:
                    true_graph1 = getattr(gm1, node1.args[1].target)
                    true_graph2 = getattr(gm2, node2.args[1].target)
                    self._check_graph_nodes(true_graph1, true_graph2)

                    false_graph1 = getattr(gm1, node1.args[2].target)
                    false_graph2 = getattr(gm2, node2.args[2].target)
                    self._check_graph_nodes(false_graph1, false_graph2)
                elif node1.target == torch.ops.higher_order.map_impl:
                    map_graph1 = getattr(gm1, node1.args[0].target)
                    map_graph2 = getattr(gm2, node2.args[0].target)
                    self._check_graph_nodes(map_graph1, map_graph2, False)

            if (
                _check_meta and
                node1.op not in ("get_attr", "placeholder", "output")
            ):
                # Check "nn_module_stack" metadata
                # TODO nn_module_stack is not roundtrippable.
                # self.assertEqual(
                #     node1.meta.get("nn_module_stack", None),
                #     node2.meta.get("nn_module_stack", None),
                # )
                # Check "source_fn_stack" metadata
                self.assertEqual(
                    node1.meta.get("source_fn_stack", None),
                    node2.meta.get("source_fn_stack", None),
                )

    def check_graph(self, fn, inputs, dynamic_shapes=None, _check_meta=True, use_pre_dispatch=True) -> None:
        """Export a graph, serialize it, deserialize it, and compare the results."""
        def _check_graph(pre_dispatch):
            if pre_dispatch:
                ep = torch.export._trace._export(fn, copy.deepcopy(inputs), {}, dynamic_shapes=dynamic_shapes, pre_dispatch=True)
            else:
                ep = torch.export.export(fn, copy.deepcopy(inputs), {}, dynamic_shapes=dynamic_shapes)
            ep.graph.eliminate_dead_code()

            serialized_artifact = serialize(ep, opset_version={"aten": 0})
            deserialized_ep = deserialize(serialized_artifact, expected_opset_version={"aten": 0})
            deserialized_ep.graph.eliminate_dead_code()

            orig_outputs = ep.module()(*copy.deepcopy(inputs))
            loaded_outputs = deserialized_ep.module()(*copy.deepcopy(inputs))

            flat_orig_outputs = pytree.tree_leaves(orig_outputs)
            flat_loaded_outputs = pytree.tree_leaves(loaded_outputs)

            for orig, loaded in zip(flat_orig_outputs, flat_loaded_outputs):
                self.assertEqual(type(orig), type(loaded))
                if isinstance(orig, torch.Tensor):
                    if orig.is_meta:
                        self.assertEqual(orig, loaded)
                    else:
                        self.assertTrue(torch.allclose(orig, loaded))
                else:
                    self.assertEqual(orig, loaded)
            self._check_graph_nodes(ep.graph_module, deserialized_ep.graph_module, _check_meta)

        if use_pre_dispatch:
            _check_graph(pre_dispatch=True)
            _check_graph(pre_dispatch=False)
        else:
            _check_graph(pre_dispatch=False)

    def test_auto_functionalize(self):
        try:
            lib = torch.library.Library("mylib", "FRAGMENT")  # noqa: TOR901
            torch.library.define(
                "mylib::foo1",
                "(Tensor(a!) x, Tensor[] y, Tensor(b!) z, SymInt w, Tensor n) -> Tensor",
                tags=torch.Tag.pt2_compliant_tag,
                lib=lib,
            )
            torch.library.define(
                "mylib::foo2",
                "(Tensor(a!) x, Tensor[] y, Tensor(b!) z, SymInt w, Tensor n) -> (Tensor, Tensor)",
                tags=torch.Tag.pt2_compliant_tag,
                lib=lib,
            )
            torch.library.define(
                "mylib::foo3",
                "(Tensor(a!) x, Tensor[] y, Tensor(b!) z, SymInt w, Tensor n) -> ()",
                tags=torch.Tag.pt2_compliant_tag,
                lib=lib,
            )

            @torch.library.impl("mylib::foo1", "cpu", lib=lib)
            @torch.library.impl_abstract("mylib::foo1")
            def foo1_impl(x, y, z, w, n):
                x.add_(y[0] + w)
                z.add_(y[1] + n)
                return n + n

            @torch.library.impl("mylib::foo2", "cpu", lib=lib)
            @torch.library.impl_abstract("mylib::foo2")
            def foo2_impl(x, y, z, w, n):
                x.add_(y[0] + w)
                z.add_(y[1] + n)
                return (n + n, n * n)

            @torch.library.impl("mylib::foo3", "cpu", lib=lib)
            @torch.library.impl_abstract("mylib::foo3")
            def foo3_impl(x, y, z, w, n):
                x.add_(y[0] + w)
                z.add_(y[1] + n)
                return

            class M(torch.nn.Module):
                def forward(self, x, y, z, n):
                    n = torch.ops.mylib.foo1(x, y, z, 2, n)
                    torch.ops.mylib.foo3(x, y, z, 2, n)
                    return torch.ops.mylib.foo2(x, y, z, 2, n)

            x = torch.randn(3)
            y = (torch.randn(3), torch.randn(3))
            z = torch.randn(3)
            n = torch.randn(3)
            orig_args = (x, y, z, n)

            # TODO Auto_functionalize is not supported on pre_dispatch IR
            self.check_graph(M(), orig_args, use_pre_dispatch=False)

        finally:
            cleanup_op("mylib::foo")
            del lib

    def test_multi_return(self) -> None:
        """
        Test multiple return from a single node (ex. layer_norm has 2 outputs)
        """
        class MyModule(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x, w, b):
                return torch.nn.functional.layer_norm(
                    x,
                    x.size()[1:],
                    weight=w,
                    bias=b,
                    eps=1e-5,
                )

        inputs = (
            torch.ones([512, 512], requires_grad=True),
            torch.ones([512]),
            torch.ones([512]),
        )
        self.check_graph(MyModule(), inputs)

    def test_basic(self) -> None:
        class MyModule(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x):
                x = x + x
                x = x * x
                x = x / x
                return x, x.clone()

        inputs = (torch.ones([512], requires_grad=True),)
        self.check_graph(MyModule(), inputs)

    def test_dynamic(self) -> None:
        class DynamicShapeSimpleModel(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, a, b, c) -> torch.Tensor:
                d = (torch.matmul(a, b) + c) / 2
                d_s0 = d.shape[0]
                d_s1 = d.shape[1]
                d_s3 = d_s0 * d_s1
                e = d.view(d_s3)
                return torch.cat([e, e])

        inputs = (torch.randn(2, 4), torch.randn(4, 7), torch.randn(2, 7))
        dim0_ac = torch.export.Dim("dim0_ac")
        dynamic_shapes = {"a": {0: dim0_ac}, "b": None, "c": {0: dim0_ac}}
        self.check_graph(DynamicShapeSimpleModel(), inputs, dynamic_shapes)

    def test_sym_bool(self):
        class Module(torch.nn.Module):
            def forward(self, x, y):
                assert x.size(0) in y
                return x + y

        f = Module()
        self.check_graph(f, (torch.ones(1), torch.ones(3)))

    def test_shape(self):
        class Foo(torch.nn.Module):
            def forward(self, x):
                z, y = x.size()
                return z + y + x[0], z

        inputs = (torch.ones(2, 3),)
        dim0_x, dim1_x = torch.export.dims("dim0_x", "dim1_x")
        dynamic_shapes = {"x": (dim0_x, dim1_x)}
        self.check_graph(Foo(), inputs, dynamic_shapes)

    def test_module(self):
        class M(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear1 = torch.nn.Linear(3, 3)
                self.relu = torch.nn.ReLU()
                self.linear2 = torch.nn.Linear(3, 5)

            def forward(self, x):
                x = self.linear1(x)
                x = self.linear1(x)
                x = torch.nn.functional.relu(x)
                x = self.linear2(x)
                return x

        inputs = (torch.randn(3, 3),)
        self.check_graph(M(), inputs)

    def test_module_meta(self):
        class M(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.p = torch.nn.Parameter(torch.ones(3, 3))

            def forward(self, x):
                return self.p + x

        with torch.device("meta"):
            mod = M()

        inputs = (torch.randn(3, 3, device="meta"),)
        self.check_graph(mod, inputs)

    def test_cond(self):
        from functorch.experimental.control_flow import cond
        inputs = torch.ones(4, 3), torch.zeros(4, 3)

        class M(torch.nn.Module):
            def forward(self, x, y):
                def t(x, y):
                    return x + y

                def f(x, y):
                    return x - y
                return cond(x[0][0] > 4, t, f, [x, y])

        self.check_graph(M(), inputs)

    def test_map(self):
        from functorch.experimental import control_flow

        def f(x, y):
            return x + y

        class Module(torch.nn.Module):
            def forward(self, xs, y):
                return control_flow.map(f, xs, y)

        g = Module()
        inputs = (torch.ones(3, 2, 2), torch.ones(2))
        self.check_graph(g, inputs, _check_meta=False)

    def test_tensor_tensor_list(self):
        try:
            from torch.library import Library
            lib = Library("_export", "FRAGMENT")  # noqa: TOR901
            lib.define(
                "_test_tensor_tensor_list_output(Tensor x, Tensor y) -> (Tensor, Tensor[])",
                tags=torch.Tag.pt2_compliant_tag)

            def _test_tensor_tensor_list_output(x, y):
                return y, [x]

            lib.impl("_test_tensor_tensor_list_output", _test_tensor_tensor_list_output, "CPU")
            lib.impl("_test_tensor_tensor_list_output", _test_tensor_tensor_list_output, "Meta")

            class M(torch.nn.Module):
                def forward(self, x, y):
                    a, b = torch.ops._export._test_tensor_tensor_list_output.default(x, y)
                    return a + b[0]

            self.check_graph(M(), (torch.rand(3, 2), torch.rand(3, 2)))

        finally:
            cleanup_op("_export::_test_tensor_tensor_list_output")
            del lib

    def test_list_of_optional_tensors(self) -> None:
        class MyModule(torch.nn.Module):
            def __init__(self):
                super().__init__()

            def forward(self, x, y, z):
                indices = [None, None, torch.tensor([1, 3, 5, 7])]
                indexed = torch.ops.aten.index.Tensor(x + y, indices)
                return indexed + z

        inputs = (torch.rand(8, 8, 8), torch.rand(8, 8, 8), torch.rand(8, 8, 4))
        self.check_graph(MyModule(), inputs)

    def test_sym_ite(self):
        class Foo(torch.nn.Module):
            def forward(self, x):
                b = x.shape[0] == 5
                ret = torch.sym_ite(b, x.shape[0], x.shape[1])
                return ret

        dynamic_shapes = {'x': {0: Dim("dim0"), 1: Dim("dim1")}}
        self.check_graph(Foo(), (torch.ones(4, 5),), dynamic_shapes=dynamic_shapes)

    @parametrize(
        "name,case",
        get_filtered_export_db_tests(),
        name_fn=lambda name, case: f"case_{name}",
    )
    def test_exportdb_supported(self, name: str, case: ExportCase) -> None:
        model = case.model
        inputs = normalize_inputs(case.example_inputs)
        _check_meta = "map" not in name
        self.check_graph(model, inputs.args, _check_meta=_check_meta)

    def test_constraints(self):
        class Module(torch.nn.Module):
            def forward(self, x, y):
                n = x.item()
                torch._constrain_as_size(n, min=2)
                return y.sum() + torch.ones(n, 5).sum()

        f = Module()
        self.check_graph(f, (torch.tensor(3), torch.randn(4, 5)))

    def test_get_attr(self) -> None:
        class Module(torch.nn.Module):
            def forward(self, x):
                return x + torch.tensor(3)

        f = Module()
        self.check_graph(f, (torch.tensor(3),))

    def test_get_attr_list(self) -> None:
        class Module(torch.nn.Module):
            def forward(self, x):
                return torch.cat([x, torch.tensor([1, 1])])

        f = Module()
        self.check_graph(f, (torch.tensor([1, 1]),))

    @unittest.skipIf(not torch.cuda.is_available(), "Requires cuda")
    def test_device(self) -> None:
        class MyModule(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.conv = torch.nn.Conv2d(3, 16, 3, stride=1, bias=True)
                self.relu = torch.nn.ReLU()

            def forward(self, x):
                conv = self.conv(x)
                relu = self.relu(conv)
                mul = relu * 0.5
                return mul

        inp = torch.randn((1, 3, 224, 224), dtype=torch.float).to("cuda")
        model = MyModule().eval().cuda()
        self.check_graph(model, (inp,))


instantiate_parametrized_tests(TestDeserialize)

@unittest.skipIf(not torchdynamo.is_dynamo_supported(), "dynamo doesn't support")
class TestSchemaVersioning(TestCase):
    def test_error(self):
        class Module(torch.nn.Module):
            def forward(self, x):
                return x + x

        f = Module()
        ep = export(f, (torch.randn(1, 3),))

        serialized_artifact = ExportedProgramSerializer().serialize(ep)
        serialized_artifact.exported_program.schema_version.major = -1
        with self.assertRaisesRegex(SerializeError, r"Serialized schema version .* does not match our current"):
            ExportedProgramDeserializer().deserialize(serialized_artifact)


class TestOpVersioning(TestCase):
    """Test if serializer/deserializer behaves correctly if version mismatch."""

    def test_empty_model_opset_version_raises(self):
        compiler_opset_version = {"aten": 4}
        model_opset_version = None
        deserializer = ExportedProgramDeserializer(compiler_opset_version)
        with self.assertRaises(RuntimeError):
            deserializer._validate_model_opset_version(model_opset_version)

    def test_opset_mismatch_raises(self):
        compiler_opset_version = {"aten": 4}
        model_opset_version = {"aten": 3}
        deserializer = ExportedProgramDeserializer(compiler_opset_version)
        with self.assertRaises(NotImplementedError):
            deserializer._validate_model_opset_version(model_opset_version)

    def test_model_op_namespace_version_missing_from_deserializer_do_not_raises(self):
        compiler_opset_version = {"aten": 3}
        model_opset_version = {"aten": 3, "custom": 4}
        deserializer = ExportedProgramDeserializer(compiler_opset_version)
        with self.assertLogs(level='WARN') as log:
            deserializer._validate_model_opset_version(model_opset_version)
            self.assertIn("Compiler doesn't have a version table for op namespace", log.output[0])

# We didn't set up kwargs input yet
unittest.expectedFailure(
    TestDeserialize.test_exportdb_supported_case_fn_with_kwargs
)

# Failed to produce a graph during tracing. Tracing through 'f' must produce a single graph.
unittest.expectedFailure(
    TestDeserialize.test_exportdb_supported_case_scalar_output
)


@unittest.skipIf(not torchdynamo.is_dynamo_supported(), "dynamo doesn't support")
class TestSaveLoad(TestCase):
    def test_save_buffer(self):
        inp = (torch.tensor([0.1, 0.1]),)

        class Module(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(2, 2)

            def forward(self, x):
                x = x + 1
                y = x.t()
                y = y.relu()
                y = self.linear(y)
                return y

        ep = export(Module(), inp)

        buffer = io.BytesIO()
        save(ep, buffer)
        buffer.seek(0)
        loaded_ep = load(buffer)

        self.assertTrue(torch.allclose(ep.module()(*inp), loaded_ep.module()(*inp)))

    def test_save_file(self):
        class Foo(torch.nn.Module):
            def forward(self, x):
                return x * x

        f = Foo()

        inp = (torch.randn(2, 2),)
        ep = export(f, inp)

        with tempfile.NamedTemporaryFile() as f:
            save(ep, f)
            f.seek(0)
            loaded_ep = load(f)

        self.assertTrue(torch.allclose(ep.module()(*inp), loaded_ep.module()(*inp)))

    def test_save_path(self):
        class Foo(torch.nn.Module):
            def forward(self, x, y):
                return x + y

        f = Foo()

        inp = (torch.tensor([6]), torch.tensor([7]))
        ep = export(f, inp)

        with TemporaryFileName() as fname:
            path = pathlib.Path(fname)
            save(ep, path)
            loaded_ep = load(path)

        self.assertTrue(torch.allclose(ep.module()(*inp), loaded_ep.module()(*inp)))

    def test_save_extra(self):
        inp = (torch.tensor([0.1, 0.1]),)

        class Foo(torch.nn.Module):
            def forward(self, x):
                return x * x + x

        f = Foo()

        ep = export(f, inp)

        buffer = io.BytesIO()
        save(ep, buffer, extra_files={"extra.txt": "moo"})
        buffer.seek(0)
        extra_files = {"extra.txt": ""}
        loaded_ep = load(buffer, extra_files=extra_files)

        self.assertTrue(torch.allclose(ep.module()(*inp), loaded_ep.module()(*inp)))
        self.assertEqual(extra_files["extra.txt"], "moo")

    def test_version_error(self):
        class Foo(torch.nn.Module):
            def forward(self, x):
                return x + x

        f = Foo()

        ep = export(f, (torch.randn(1, 3),))

        with tempfile.NamedTemporaryFile() as f:
            save(ep, f)
            f.seek(0)

            # Modify the version
            with zipfile.ZipFile(f, 'a') as zipf:
                zipf.writestr('version', "-1.1")

            with self.assertRaisesRegex(RuntimeError, r"Serialized version .* does not match our current"):
                f.seek(0)
                load(f)

    def test_save_constants(self):
        class Foo(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.a = torch.tensor(3)

            def forward(self, x):
                list_tensor = [torch.tensor(3), torch.tensor(4)]
                return x + self.a + list_tensor[0] + list_tensor[1]

        ep = export(Foo(), (torch.tensor(1),))
        buffer = io.BytesIO()
        save(ep, buffer)
        buffer.seek(0)
        loaded_ep = load(buffer)

        inp = (torch.tensor(1),)
        self.assertTrue(torch.allclose(ep.module()(*inp), loaded_ep.module()(*inp)))

@unittest.skipIf(not torchdynamo.is_dynamo_supported(), "dynamo doesn't support")
class TestSerializeCustomClass(TestCase):
    def setUp(self):
        if IS_SANDCASTLE or IS_FBCODE:
            torch.ops.load_library(
                "//caffe2/test/cpp/jit:test_custom_class_registrations"
            )
        elif IS_MACOS:
            raise unittest.SkipTest("non-portable load_library call used in test")
        else:
            lib_file_path = find_library_location('libtorchbind_test.so')
            if IS_WINDOWS:
                lib_file_path = find_library_location('torchbind_test.dll')
            torch.ops.load_library(str(lib_file_path))

    def test_custom_class(self):
        custom_obj = torch.classes._TorchScriptTesting._PickleTester([3, 4])

        class Foo(torch.nn.Module):
            def forward(self, x):
                return x + x

        f = Foo()

        inputs = (torch.zeros(4, 4),)
        ep = export(f, inputs)

        # Replace one of the values with an instance of our custom class
        for node in ep.graph.nodes:
            if node.op == "call_function" and node.target == torch.ops.aten.add.Tensor:
                with ep.graph.inserting_before(node):
                    custom_node = ep.graph.call_function(
                        torch.ops._TorchScriptTesting.take_an_instance.default,
                        (custom_obj,),
                    )
                    custom_node.meta["val"] = torch.ones(4, 4)
                    arg0, _ = node.args
                    node.args = (arg0, custom_node)

        serialized_vals = serialize(ep)

        ep_str = serialized_vals.exported_program.decode("utf-8")
        assert "class_fqn" in ep_str
        assert custom_obj._type().qualified_name() in ep_str

        deserialized_ep = deserialize(serialized_vals)

        for node in deserialized_ep.graph.nodes:
            if (
                node.op == "call_function" and
                node.target == torch.ops._TorchScriptTesting.take_an_instance.default
            ):
                arg = node.args[0]
                self.assertTrue(isinstance(arg, torch._C.ScriptObject))
                self.assertEqual(arg._type(), custom_obj._type())
                self.assertEqual(arg.__getstate__(), custom_obj.__getstate__())
                self.assertEqual(arg.top(), 7)

    def test_custom_class_containing_fake_tensor(self):
        class Foo(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.custom_obj = torch.classes._TorchScriptTesting._ContainsTensor(torch.rand(2, 3))

            def forward(self, x):
                return x + self.custom_obj.get()

        with FakeTensorMode():
            f = Foo()

        inputs = (torch.zeros(2, 3),)
        with enable_torchbind_tracing():
            ep = export(f, inputs, strict=False)

        serialized_vals = serialize(ep)
        ep = deserialize(serialized_vals)
        self.assertTrue(isinstance(ep.constants["custom_obj"].get(), FakeTensor))


if __name__ == '__main__':
    run_tests()
