# Copyright (c) Meta Platforms, Inc. and affiliates
# Owner(s): ["oncall: distributed"]

from copy import deepcopy
import itertools
import torch
import torch.distributed as dist
import torch.nn.functional as F
from torch.distributed._tensor import DeviceMesh, DTensor, Replicate, Shard, distribute_tensor
from torch.distributed._tensor.debug import CommDebugMode
from torch.distributed.algorithms._checkpoint.checkpoint_wrapper import (
    checkpoint_wrapper,
    CheckpointImpl,
)
from torch.distributed.tensor.parallel import (
    ColwiseParallel,
    loss_parallel,
    parallelize_module,
    PrepareModuleInput,
    RowwiseParallel,
    SequenceParallel,
)
from torch.distributed.tensor.parallel.input_reshard import input_reshard
from torch.testing._internal.common_utils import (
    instantiate_parametrized_tests,
    parametrize,
    run_tests,
)
from torch.testing._internal.distributed._tensor.common_dtensor import (
    DTensorTestBase,
    MLPModule,
    ModelArgs,
    NUM_DEVICES,
    skip_unless_torch_gpu,
    Transformer,
    with_comms,
)


c10d_functional = torch.ops.c10d_functional

class DistTensorParallelExampleTest(DTensorTestBase):
    def _check_module(self, m1, m2, check_grad=False):
        named_parameters = dict(m1.named_parameters())
        for name, param_m2 in m2.named_parameters():
            self.assertTrue(name in named_parameters)
            param_m1 = named_parameters[name]
            if check_grad:
                param_m2 = param_m2.grad
                param_m1 = param_m1.grad
            if isinstance(param_m2, DTensor):
                replicate = [Replicate()]
                param_m2 = param_m2.redistribute(
                    device_mesh=param_m2.device_mesh, placements=replicate
                ).to_local()
            self.assertEqual(param_m2, param_m1)

    def _test_mlp_training_e2e(self, is_seq_parallel=False, recompute_activation=False):
        inp_size = [8, 10]
        # Ensure all tp ranks have same input.
        rng_seed = self.rank if is_seq_parallel else 0
        torch.manual_seed(rng_seed)
        inp = torch.rand(*inp_size, device=self.device_type)
        model = MLPModule(self.device_type)
        model_tp = deepcopy(model)

        # Ensure model are initialized the same way.
        self._check_module(model, model_tp)

        # Shard module and initialize optimizer.
        LR = 0.25
        device_mesh = DeviceMesh(
            self.device_type,
            torch.arange(0, NUM_DEVICES),
        )
        parallelize_plan = {
            "net1": ColwiseParallel(input_layouts=Shard(0))
            if is_seq_parallel
            else ColwiseParallel(),
            "net2": RowwiseParallel(output_layouts=Shard(0))
            if is_seq_parallel
            else RowwiseParallel(),
        }
        model_tp = parallelize_module(model_tp, device_mesh, parallelize_plan)
        if recompute_activation:
            model_tp = input_reshard(
                checkpoint_wrapper(
                    model_tp, checkpoint_impl=CheckpointImpl.NO_REENTRANT
                ),
                device_mesh,
                None if is_seq_parallel else 0,
            )
        optim = torch.optim.SGD(model.parameters(), lr=LR)
        optim_tp = torch.optim.SGD(model_tp.parameters(), lr=LR)

        output = model(inp)
        output.sum().backward()

        from torch.distributed._tensor.debug import CommDebugMode
        comm_mode = CommDebugMode()
        with comm_mode:
            output_tp = model_tp(inp)
            output_tp.sum().backward()

        self.assertEqual(output, output_tp)
        if is_seq_parallel:
            self.assertEqual(comm_mode.get_comm_counts()[c10d_functional.all_gather_into_tensor], 2)
            self.assertEqual(comm_mode.get_comm_counts()[c10d_functional.reduce_scatter_tensor], 1)
        else:
            self.assertEqual(comm_mode.get_comm_counts()[c10d_functional.all_reduce], 1)

        if is_seq_parallel:
            # Sum gradients from different ranks, since input
            # are different across ranks for sequence parallel.
            dist.all_reduce(model.net1.weight.grad)
            dist.all_reduce(model.net1.bias.grad)
            dist.all_reduce(model.net2.weight.grad)
            dist.all_reduce(model.net2.bias.grad)

        # Ensure gradients are same.
        self._check_module(model, model_tp, check_grad=True)

        optim.step()
        optim_tp.step()

        # Ensure model weights are still same after update.
        # Due to the trick we use for Partial aggregation, we only check the weight when local_rank = 0.
        self._check_module(model, model_tp)

        inp = torch.rand(*inp_size, device=self.device_type)
        output = model(inp)
        output_tp = model_tp(inp)
        self.assertEqual(output, output_tp)

    def _test_mlp_inference(self, device_mesh):
        inp_size = [8, 10]
        # Ensure all tp ranks have same input.
        torch.manual_seed(0)
        inp = torch.rand(*inp_size, device=self.device_type)
        model = MLPModule(self.device_type)
        model_tp = deepcopy(model)

        # Ensure model are initialized the same way.
        self._check_module(model, model_tp)

        # Shard module and initialize optimizer.
        parallelize_plan = {
            "net1": ColwiseParallel(),
            "net2": RowwiseParallel(),
        }
        model_tp = parallelize_module(model_tp, device_mesh, parallelize_plan)

        output = model(inp)
        output_tp = model_tp(inp)
        self.assertEqual(output, output_tp)

    @with_comms
    @parametrize("is_seq_parallel", [True, False])
    # TODO: need to revisit input_reshard API about why it failed multi-gpu tests.
    # @parametrize("recompute_activation", [True, False])
    @parametrize("recompute_activation", [False])
    def test_mlp_training(self, is_seq_parallel, recompute_activation):
        self._test_mlp_training_e2e(
            is_seq_parallel=is_seq_parallel, recompute_activation=recompute_activation
        )

    @with_comms
    def test_mlp_inference(self):
        device_mesh = DeviceMesh(
            self.device_type,
            torch.arange(0, NUM_DEVICES),
        )
        with torch.inference_mode():
            self._test_mlp_inference(device_mesh)

    @with_comms
    @skip_unless_torch_gpu
    @parametrize("is_seq_parallel", [True, False])
    def test_transformer_training(self, is_seq_parallel=False):
        # Step 1: Initialize single-gpu models and optimizers.

        # Disable dropout in the test since we cannot reproduce the same random
        # behaviors when comparing single-gpu models with multi-gpu models.
        model_args = ModelArgs(dropout_p=0.0)

        # float64 precision is needed for the computation results on the single-gpu
        # model and the distributed model to be asserted equal, especially when
        # model size is large and various operations (e.g., positional embedding,
        # weight tying, etc.) are performed.
        model = Transformer(model_args).to(device=self.device_type, dtype=torch.float64)
        model_tp = deepcopy(model)
        self._check_module(model, model_tp)

        # Step 2: Set up and execute the parallelize plan to shard the test model
        # onto the device mesh.

        device_mesh = DeviceMesh(self.device_type, torch.arange(0, NUM_DEVICES))

        # Parallelize the root submodules.
        if is_seq_parallel:
            root_plan = {
                "tok_embeddings": ColwiseParallel(output_layouts=Shard(1)),
                "pos_embeddings": ColwiseParallel(output_layouts=Shard(0)),
                "norm": SequenceParallel(),
            }
        else:
            root_plan = {
                "tok_embeddings": ColwiseParallel(output_layouts=Replicate()),
                "pos_embeddings": ColwiseParallel(output_layouts=Replicate()),
            }

        model_tp = parallelize_module(
            model_tp,
            device_mesh,
            root_plan
        )
        # Parallelize the attention and feed forward submodules.
        for layer in model_tp.layers:
            layer_parallelize_plan = {}
            if is_seq_parallel:
                layer_parallelize_plan["attention"] = PrepareModuleInput(
                    input_layouts=Shard(1),
                    desired_input_layouts=Replicate(),
                )
                # shard the RMSNorms
                layer_parallelize_plan["attention_norm"] = SequenceParallel()
                layer_parallelize_plan["ffn_norm"] = SequenceParallel()
            layer_parallelize_plan["attention.wq"] = ColwiseParallel()
            layer_parallelize_plan["attention.wk"] = ColwiseParallel()
            layer_parallelize_plan["attention.wv"] = ColwiseParallel()
            layer_parallelize_plan["attention.wo"] = RowwiseParallel(
                output_layouts=Shard(1)
            ) if is_seq_parallel else RowwiseParallel()

            layer_parallelize_plan["feed_forward.w1"] = ColwiseParallel(
                input_layouts=Shard(1)
            ) if is_seq_parallel else ColwiseParallel()
            layer_parallelize_plan["feed_forward.w2"] = RowwiseParallel(
                output_layouts=Shard(1)
            ) if is_seq_parallel else RowwiseParallel()

            parallelize_module(layer, device_mesh, layer_parallelize_plan)

        # Parallelize the output submodule. If weight tying is enabled, we need to
        # make sure output.weight is sharded consistently as tok_embeddings.weight,
        # at the cost of the all_reduce operation using RowwiseParallel.
        output_parallelize_plan = None
        if not model_args.weight_tying:
            output_parallelize_plan = ColwiseParallel(
                input_layouts=Shard(1),
                output_layouts=Replicate(),
            ) if is_seq_parallel else ColwiseParallel(output_layouts=Replicate())
        else:
            output_parallelize_plan = RowwiseParallel(
                input_layouts=Shard(1),
                output_layouts=Replicate(),
            ) if is_seq_parallel else RowwiseParallel(input_layouts=Replicate())
        parallelize_module(model_tp.output, device_mesh, output_parallelize_plan)

        # Step 2.5: Do manual setup on features that DTensor does not support yet.

        # Manually adjust the number of heads after sharding the attention modules.
        for layer in model_tp.layers:
            layer.attention.n_heads = model_args.n_heads // self.world_size

        # Manually set output.weight so that parameters and gradients are shared.
        if model_args.weight_tying:
            model_tp.output.weight = model_tp.tok_embeddings.weight

        # Step 3: Run test by comparing outputs from single-gpu and multi-gpu models.

        LR = 0.25
        optim = torch.optim.Adam(model.parameters(), lr=LR)
        optim_tp = torch.optim.Adam(model_tp.parameters(), lr=LR)

        # Initialize input and make sure all ranks have the same input.
        inp_size = [8, 12]  # [batch_size, seq_len]
        if is_seq_parallel:
            assert inp_size[1] % self.world_size == 0
        torch.manual_seed(0)
        inp = torch.randint(model_args.vocab_size, inp_size, device=self.device_type)

        # Compare outputs on the same input.
        output = model(inp)
        output_tp = model_tp(inp)
        self.assertEqual(output, output_tp)

        # Ensure gradients are equal.
        output.sum().backward()
        output_tp.sum().backward()
        self._check_module(model, model_tp, check_grad=True)

        # Ensure model weights are still the same after update.
        optim.step()
        optim_tp.step()
        self._check_module(model, model_tp)

        # Compare outputs on another input.
        torch.manual_seed(11)
        inp = torch.randint(model_args.vocab_size, inp_size, device=self.device_type)
        output = model(inp)
        output_tp = model_tp(inp)
        self.assertEqual(output, output_tp)

    @with_comms
    def test_weight_tying(self):
        class TestModule(torch.nn.Module):
            def __init__(self):
                super().__init__()
                # Initialize different weights for embedding and fc.
                torch.manual_seed(1)
                self.embedding = torch.nn.Embedding(16, 8)
                torch.manual_seed(2)
                self.fc = torch.nn.Linear(8, 16)

            def forward(self, x):
                return self.fc(self.embedding(x))

        model = TestModule().to(self.device_type)
        parallelize_plan = {
            "embedding": ColwiseParallel(),
            "fc": RowwiseParallel(),
        }
        device_mesh = DeviceMesh(self.device_type, list(range(self.world_size)))
        parallelize_module(model, device_mesh, parallelize_plan)

        input_size = [5]
        torch.manual_seed(0)
        inp = torch.randint(16, input_size, device=self.device_type)

        # Without weight tying.
        self.assertNotEqual(
            model.embedding.weight.to_local(), model.fc.weight.to_local()
        )
        output = model(inp)
        output.sum().backward()
        self.assertNotEqual(
            model.embedding.weight.grad.to_local(), model.fc.weight.grad.to_local()
        )
        model.zero_grad()

        # With weight tying.
        model.fc.weight = model.embedding.weight

        self.assertEqual(model.embedding.weight, model.fc.weight)
        self.assertEqual(id(model.embedding.weight), id(model.fc.weight))
        output = model(inp)
        output.sum().backward()
        self.assertEqual(model.embedding.weight.grad, model.fc.weight.grad)
        self.assertEqual(id(model.embedding.weight.grad), id(model.fc.weight.grad))

    @with_comms
    def test_loss_parallel(self):
        device_mesh = self.build_device_mesh()
        comm_mode = CommDebugMode()

        channel_size, channel_dim = 16, 1
        test_setup = [
            (2, (8, channel_size), (8,)),  # calling aten.nll_loss_forward
            (3, (8, channel_size, 12), (8, 12)),  # calling aten.nll_loss2d_forward
        ]
        weight = torch.rand(channel_size, device=self.device_type)
        for input_ndim, input_size, target_size in test_setup:
            x = torch.rand(*input_size, device=self.device_type, requires_grad=True)
            target = torch.randint(channel_size, target_size, device=self.device_type)

            shard_dims = list(range(input_ndim))
            reductions = ["none", "mean", "sum"]
            for shard_dim, reduction in itertools.product(shard_dims, reductions):
                dist_x = distribute_tensor(x, device_mesh, [Shard(shard_dim)])
                y = F.cross_entropy(x, target, weight, reduction=reduction)
                with loss_parallel():
                    if shard_dim == channel_dim:
                        with comm_mode:
                            dist_y = F.cross_entropy(dist_x, target, weight, reduction=reduction)
                            self.assertEqual(comm_mode.get_total_counts(), 3)
                            self.assertEqual(
                                comm_mode.get_comm_counts()[c10d_functional.all_reduce],
                                3,
                            )
                            self.assertTrue(dist_y.placements[0].is_replicate())
                            self.assertEqual(dist_y.to_local(), y)

                        with comm_mode:
                            if reduction == "none":
                                y.sum().backward()
                                dist_y.sum().backward()
                            else:
                                y.backward()
                                dist_y.backward()
                            self.assertEqual(comm_mode.get_total_counts(), 0)
                            self.assertTrue(dist_x.grad.placements[0].is_shard(shard_dim))
                            self.assertEqual(dist_x.grad.full_tensor(), x.grad)
                        x.grad.zero_()
                    else:
                        with self.assertRaisesRegex(
                            ValueError,
                            "loss_parallel",
                        ):
                            dist_y = F.cross_entropy(dist_x, target, reduction=reduction)



instantiate_parametrized_tests(DistTensorParallelExampleTest)

if __name__ == "__main__":
    run_tests()
