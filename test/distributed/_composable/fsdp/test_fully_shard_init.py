# Owner(s): ["oncall: distributed"]

import itertools
import unittest
from typing import List

import torch
import torch.nn as nn
from torch.distributed._composable import replicate
from torch.distributed._composable.fsdp import fully_shard
from torch.distributed._composable.fsdp._fsdp_init import (
    _get_managed_modules,
    _get_managed_states,
)
from torch.distributed._composable.fsdp._fsdp_param import ParamModuleInfo
from torch.distributed._composable.fsdp._fsdp_param_group import _get_param_module_infos
from torch.distributed._tensor import DeviceMesh, DTensor, Replicate, Shard
from torch.distributed.device_mesh import init_device_mesh
from torch.distributed.tensor.parallel import (
    ColwiseParallel,
    parallelize_module,
    RowwiseParallel,
)
from torch.testing._internal.common_cuda import TEST_CUDA
from torch.testing._internal.common_fsdp import FSDPTestMultiThread, MLP
from torch.testing._internal.common_utils import run_tests, wrapSwapTensorsTest


class TestFullyShardDeviceTensor(FSDPTestMultiThread):
    """Tests that tensor parameters are moved to the expected device."""

    @property
    def world_size(self) -> int:
        return 1

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_move_states_to_device_tensor(self):
        model = MLP(8, torch.device("cpu"), with_buffer=True)
        for tensor in itertools.chain(model.parameters(), model.buffers()):
            self.assertEqual(tensor.device, torch.device("cpu"))
        fully_shard(model)
        cuda_device = torch.device("cuda", torch.cuda.current_device())
        for tensor in itertools.chain(model.parameters(), model.buffers()):
            self.assertEqual(tensor.device, cuda_device)


class TestFullyShardDeviceDTensor(FSDPTestMultiThread):
    """Tests that DTensor parameters are moved to the expected device."""

    @property
    def world_size(self) -> int:
        return 4

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_move_states_to_device_dtensor_valid(self):
        assert self.world_size >= 4, f"{self.world_size}"
        dp_size = 2
        global_mesh = init_device_mesh(
            "cuda", (dp_size, self.world_size // dp_size), mesh_dim_names=("dp", "tp")
        )
        dp_mesh, tp_mesh = global_mesh["dp"], global_mesh["tp"]
        model = MLP(8, torch.device("cpu"), with_buffer=True)
        parallelize_module(
            model,
            tp_mesh,
            {"in_proj": ColwiseParallel(), "out_proj": RowwiseParallel()},
        )
        cuda_device = torch.device("cuda", torch.cuda.current_device())
        for tensor in itertools.chain(model.parameters(), model.buffers()):
            if isinstance(tensor, DTensor):
                # DTensor constructor moves to the mesh's device
                self.assertEqual(tensor.device, cuda_device)
                self.assertEqual(tensor._local_tensor.device, cuda_device)
            else:
                self.assertEqual(tensor.device, torch.device("cpu"))
        fully_shard(model, mesh=dp_mesh)
        for tensor in itertools.chain(model.parameters(), model.buffers()):
            self.assertEqual(tensor.device, cuda_device)
            if isinstance(tensor, DTensor):
                self.assertEqual(tensor._local_tensor.device, cuda_device)

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_move_states_to_device_dtensor_invalid(self):
        assert self.world_size >= 4, f"{self.world_size}"
        dp_size = 2
        global_cuda_mesh = init_device_mesh(
            "cuda", (dp_size, self.world_size // dp_size), mesh_dim_names=("dp", "tp")
        )
        global_cpu_mesh = init_device_mesh(
            "cpu", (dp_size, self.world_size // dp_size), mesh_dim_names=("dp", "tp")
        )
        dp_mesh = global_cuda_mesh["dp"]
        tp_mesh = global_cpu_mesh["tp"]  # mismatched meshes!
        model = MLP(8, torch.device("cpu"), with_buffer=True)
        parallelize_module(
            model,
            tp_mesh,
            {"in_proj": ColwiseParallel(), "out_proj": RowwiseParallel()},
        )
        for tensor in itertools.chain(model.parameters(), model.buffers()):
            self.assertEqual(tensor.device, torch.device("cpu"))
            if isinstance(tensor, DTensor):
                self.assertEqual(tensor._local_tensor.device, torch.device("cpu"))
        regex = r"Requires DTensor to have mesh of the same type as the FSDP mesh but got cpu for DTensor and cuda for FSDP"
        with self.assertRaisesRegex(ValueError, regex):
            fully_shard(model, mesh=dp_mesh)


class TestFullyShardMeshArg(FSDPTestMultiThread):
    """Tests the ``mesh`` argument."""

    @property
    def world_size(self) -> int:
        return 2

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_invalid_mesh_ndim(self):
        mesh = init_device_mesh("cuda", (self.world_size, 1, 1))
        model = MLP(8)
        regex = r"fully\_shard expects a 1D or 2D DeviceMesh but got DeviceMesh\(\[\[\[0\]\], \[\[1\]\]\]\)"
        with self.assertRaisesRegex(ValueError, regex):
            fully_shard(model, mesh=mesh)


class TestFullyShardManagedModulesAndStates(FSDPTestMultiThread):
    """Tests getting the managed modules/states for a ``fully_shard`` module."""

    @property
    def world_size(self) -> int:
        return 1

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_managed_modules_single(self):
        model = MLP(8)
        # Assume calling `fully_shard` on `model`
        managed_modules = _get_managed_modules(model)
        expected_managed_modules = list(model.modules())
        self._check_managed_modules(managed_modules, expected_managed_modules)

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_managed_modules_nested(self):
        model = nn.Sequential(*[MLP(8) for _ in range(2)])
        fully_shard(model[0])
        # Assume calling `fully_shard` on `model`
        managed_modules = _get_managed_modules(model)
        expected_managed_modules = list(model[1].modules()) + [model]
        self._check_managed_modules(managed_modules, expected_managed_modules)

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_managed_modules_nested_fully_shard_and_replicate(self):
        model = nn.Sequential(*[MLP(8) for _ in range(3)])
        replicate(model[0])
        fully_shard(model[2])
        # Assume calling `fully_shard` on `model`
        managed_modules = _get_managed_modules(model)
        expected_managed_modules = list(model[1].modules()) + [model]
        self._check_managed_modules(managed_modules, expected_managed_modules)

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_managed_modules_duplicate(self):
        mlp = MLP(8)
        model = nn.Sequential(mlp, mlp)  # duplicate MLP
        # Assume calling `fully_shard` on `model`
        managed_modules = _get_managed_modules(model)
        # Check that the duplicate module is only counted once
        expected_managed_modules = list(mlp.modules()) + [model]
        self._check_managed_modules(managed_modules, expected_managed_modules)

    def _check_managed_modules(
        self,
        managed_modules: List[nn.Module],
        expected_managed_modules: List[nn.Module],
    ):
        self.assertEqual(len(managed_modules), len(expected_managed_modules))
        # Check set comparison since we do not require anything about the order
        self.assertEqual(set(managed_modules), set(expected_managed_modules))

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_managed_states_shared_params_and_buffers(self):
        model = nn.Sequential(*[MLP(8, with_buffer=True) for _ in range(3)])
        model[0].in_proj.weight = model[1].in_proj.weight
        model[2].in_proj.weight = model[1].in_proj.weight
        model[1].buffer = model[2].buffer
        # Assume calling `fully_shard` on `model`
        managed_modules = _get_managed_modules(model)
        params, buffers = _get_managed_states(managed_modules)
        expected_params = list(model.parameters())  # de-dups shared
        expected_buffers = list(model.buffers())  # de-dups shared
        self._check_managed_states(params, buffers, expected_params, expected_buffers)

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_managed_states_nested_fully_shard(self):
        model = nn.Sequential(*[MLP(8, with_buffer=True) for _ in range(2)])
        fully_shard(model[0])
        # Assume calling `fully_shard` on `model`
        managed_modules = _get_managed_modules(model)
        params, buffers = _get_managed_states(managed_modules)
        expected_params = list(model[1].parameters())
        expected_buffers = list(model[1].buffers())
        self._check_managed_states(params, buffers, expected_params, expected_buffers)

    def _check_managed_states(
        self,
        managed_params: List[nn.Parameter],
        managed_buffers: List[torch.Tensor],
        expected_managed_params: List[nn.Parameter],
        expected_managed_buffers: List[torch.Tensor],
    ):
        self.assertEqual(len(managed_params), len(expected_managed_params))
        self.assertEqual(len(managed_buffers), len(expected_managed_buffers))
        self.assertEqual(set(managed_params), set(expected_managed_params))
        self.assertEqual(set(managed_buffers), set(expected_managed_buffers))


class TestFullyShardParamModuleInfos(FSDPTestMultiThread):
    @property
    def world_size(self) -> int:
        return 2

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_get_param_module_infos_shared_params(self):
        model = nn.Sequential(*[MLP(8) for _ in range(2)])
        model[0].in_proj.weight = model[1].in_proj.weight
        managed_modules = _get_managed_modules(model)
        params, _ = _get_managed_states(managed_modules)
        param_module_infos = _get_param_module_infos(params, model)
        self.assertEqual(len(param_module_infos), len(params))
        # We expect `params` to already have de-duplicated shared parameters
        expected_param_module_infos = [
            ParamModuleInfo(model[0].in_proj, "weight", [model[1].in_proj], ["weight"]),
            ParamModuleInfo(model[0].in_proj, "bias", [], []),
            ParamModuleInfo(model[0].out_proj, "weight", [], []),
            ParamModuleInfo(model[0].out_proj, "bias", [], []),
            ParamModuleInfo(model[1].in_proj, "bias", [], []),
            ParamModuleInfo(model[1].out_proj, "weight", [], []),
            ParamModuleInfo(model[1].out_proj, "bias", [], []),
        ]
        self.assertEqual(len(param_module_infos), len(expected_param_module_infos))
        self.assertEqual(param_module_infos, expected_param_module_infos)

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_get_param_module_infos_duplicates(self):
        mlp = MLP(8)
        model = nn.Sequential(mlp, mlp)  # shared MLP
        params = list(model.parameters())
        param_module_infos = _get_param_module_infos(params, model)
        self.assertEqual(len(param_module_infos), len(params))
        expected_param_module_infos = [
            ParamModuleInfo(mlp.in_proj, "weight", [mlp.in_proj], ["weight"]),
            ParamModuleInfo(mlp.in_proj, "bias", [mlp.in_proj], ["bias"]),
            ParamModuleInfo(mlp.out_proj, "weight", [mlp.out_proj], ["weight"]),
            ParamModuleInfo(mlp.out_proj, "bias", [mlp.out_proj], ["bias"]),
        ]
        self.assertEqual(len(param_module_infos), len(expected_param_module_infos))
        self.assertEqual(param_module_infos, expected_param_module_infos)

        model = nn.Sequential(*[MLP(8) for _ in range(2)])
        model[0].in_proj = model[1].in_proj  # shared in-projection
        params = list(model.parameters())
        param_module_infos = _get_param_module_infos(params, model)
        self.assertEqual(len(param_module_infos), len(params))
        expected_param_module_infos = [
            ParamModuleInfo(model[0].in_proj, "weight", [model[1].in_proj], ["weight"]),
            ParamModuleInfo(mlp.in_proj, "bias", [], []),
            ParamModuleInfo(mlp.out_proj, "weight", [], []),
            ParamModuleInfo(mlp.out_proj, "bias", [], []),
        ]


class TestFullyShardShardedParameterTensor(FSDPTestMultiThread):
    @property
    def world_size(self) -> int:
        return 2

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_shard_tensor_parameters(self):
        # Use odd dim sizes to test uneven shards
        model = nn.Sequential(*[MLP(3, dim_multiplier=3) for _ in range(3)])
        orig_params = [param.detach().clone() for param in model.parameters()]
        fully_shard(model)
        sharded_params = list(model.parameters())
        self._check_1d_sharded_parameters(orig_params, sharded_params)

        model = nn.Sequential(*[MLP(3, dim_multiplier=3) for _ in range(3)])
        model[0].in_proj = model[1].in_proj
        orig_params = [param.detach().clone() for param in model.parameters()]
        fully_shard(model)
        sharded_params = list(model.parameters())
        self._check_1d_sharded_parameters(orig_params, sharded_params)

    def _check_1d_sharded_parameters(
        self, orig_params: List[nn.Parameter], sharded_params: List[nn.Parameter]
    ):
        self.assertEqual(len(orig_params), len(sharded_params))
        global_mesh = init_device_mesh("cuda", (self.world_size,))
        for orig_param, sharded_param in zip(orig_params, sharded_params):
            self.assertIsInstance(sharded_param, DTensor)
            self.assertEqual(sharded_param.device_mesh, global_mesh)
            self.assertEqual(sharded_param.size(), orig_param.size())
            self.assertEqual(sharded_param.stride(), orig_param.stride())
            self.assertEqual(sharded_param._spec.placements, (Shard(0),))
            chunks = torch.chunk(orig_param, self.world_size, dim=0)
            self.assertEqual(sharded_param._local_tensor, chunks[self.rank])


class TestFullyShardShardedParameterDTensor(FSDPTestMultiThread):
    @property
    def world_size(self) -> int:
        return 4

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_shard_dtensor_parameters(self):
        dp_size = 2 if self.world_size > 2 else 1
        global_mesh = init_device_mesh(
            "cuda", (dp_size, self.world_size // dp_size), mesh_dim_names=("dp", "tp")
        )
        dp_mesh, tp_mesh = global_mesh["dp"], global_mesh["tp"]
        # Use odd dim sizes to test uneven shards
        model = MLP(9, dim_multiplier=3)
        orig_params = [param.detach().clone() for param in model.parameters()]
        orig_param_names = [param_name for param_name, _ in model.named_parameters()]
        parallelize_module(
            model,
            tp_mesh,
            {"in_proj": ColwiseParallel(), "out_proj": RowwiseParallel()},
        )
        fully_shard(model, mesh=dp_mesh)
        sharded_params = list(model.parameters())
        self.assertEqual(len(orig_params), len(sharded_params))
        for orig_param_name, orig_param, sharded_param in zip(
            orig_param_names, orig_params, sharded_params
        ):
            self.assertIsInstance(sharded_param, DTensor)
            self.assertEqual(sharded_param.device_mesh, global_mesh)
            self.assertEqual(sharded_param.size(), orig_param.size())
            self.assertEqual(sharded_param.stride(), orig_param.stride())
            if "in_proj" in orig_param_name:
                expected_placements = (Shard(0), Shard(0))
            elif "out_proj" in orig_param_name and "weight" in orig_param_name:
                expected_placements = (Shard(0), Shard(1))
            else:
                expected_placements = (Shard(0), Replicate())
            self.assertEqual(sharded_param._spec.placements, expected_placements)


class TestFullyShardLazyInit(FSDPTestMultiThread):
    @property
    def world_size(self) -> int:
        return 2

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_fully_shard_is_root(self):
        """
        Tests that ``_is_root`` is set correctly after lazy initialization.

        FSDP(model(
            0: MLP(FSDP(in_proj), FSDP(out_proj)),
            1: MLP(in_proj, out_proj),
        ))
        """
        model = nn.Sequential(MLP(8), MLP(8))
        fully_shard(model[0].in_proj)
        fully_shard(model[0].out_proj)
        fully_shard(model)  # root gets `model[1]`
        root_state = fully_shard.state(model)
        root_state._lazy_init()

        model0_in_proj_state = fully_shard.state(model[0].in_proj)
        model0_out_proj_state = fully_shard.state(model[0].out_proj)
        self.assertTrue(root_state._is_root)
        self.assertFalse(model0_in_proj_state._is_root)
        self.assertFalse(model0_out_proj_state._is_root)

        all_states = root_state._state_ctx.all_states
        self.assertEqual(len(all_states), 3)
        self.assertEqual(
            all_states, [root_state, model0_in_proj_state, model0_out_proj_state]
        )

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_fully_shard_module_and_param_fqns(self):
        """
        Tests that the module and parameter FQNs are computed correctly after
        lazy initialization.

        FSDP(model(
            0: MLP(FSDP(in_proj), FSDP(out_proj)),
            1: MLP(in_proj, out_proj),
        ))
        """
        model = nn.Sequential(MLP(8), MLP(8))
        fully_shard(model[0].in_proj)
        fully_shard(model[0].out_proj)
        fully_shard(model)  # root gets `model[1]`
        root_state = fully_shard.state(model)
        root_state._lazy_init()

        root_param_group = root_state._fsdp_param_group
        self.assertIsNotNone(root_param_group)
        self.assertEqual(root_param_group._module_fqn, "")
        root_param_fqns = {
            fsdp_param._param_fqn for fsdp_param in root_param_group.fsdp_params
        }
        self.assertEqual(
            root_param_fqns,
            {
                "1.in_proj.weight",
                "1.in_proj.bias",
                "1.out_proj.weight",
                "1.out_proj.bias",
            },
        )

        model0_in_proj_state = fully_shard.state(model[0].in_proj)
        model0_in_proj_param_group = model0_in_proj_state._fsdp_param_group
        self.assertIsNotNone(model0_in_proj_param_group)
        self.assertEqual(model0_in_proj_param_group._module_fqn, "0.in_proj")
        model0_in_proj_param_fqns = {
            fsdp_param._param_fqn
            for fsdp_param in model0_in_proj_param_group.fsdp_params
        }
        self.assertEqual(
            model0_in_proj_param_fqns, {"0.in_proj.weight", "0.in_proj.bias"}
        )

        model0_out_proj_state = fully_shard.state(model[0].out_proj)
        model0_out_proj_param_group = model0_out_proj_state._fsdp_param_group
        self.assertIsNotNone(model0_out_proj_param_group)
        self.assertEqual(model0_out_proj_param_group._module_fqn, "0.out_proj")
        model0_out_proj_param_fqns = {
            fsdp_param._param_fqn
            for fsdp_param in model0_out_proj_param_group.fsdp_params
        }
        self.assertEqual(
            model0_out_proj_param_fqns, {"0.out_proj.weight", "0.out_proj.bias"}
        )

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_fully_shard_double_lazy_init(self):
        model = nn.Sequential(MLP(8), MLP(8))
        fully_shard(model[0].in_proj)
        fully_shard(model[0].out_proj)
        fully_shard(model)
        root_state = fully_shard.state(model)
        model0_in_proj_state = fully_shard.state(model[0].in_proj)
        model0_in_proj_state._lazy_init()
        regex = (
            "FSDP state has already been lazily initialized for 0.in_proj\n"
            "FSDP requires running forward through the root module first"
        )
        with self.assertRaisesRegex(RuntimeError, regex):
            root_state._lazy_init()


class TestFullyShardMetaDeviceInit(FSDPTestMultiThread):
    """
    Set ``torch.__future__.set_swap_module_params_on_conversion(True)`` using
    ``@wrapSwapTensorsTest(True)`` until ``_apply`` swaps wrapper subclasses by
    default in the future.
    """

    @property
    def world_size(self) -> int:
        return 4

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    @wrapSwapTensorsTest(True)
    def test_meta_device_1d_init(self):
        default_pg = torch.distributed.distributed_c10d._get_default_group()
        mesh = init_device_mesh("cuda", mesh_shape=(default_pg.size(),))

        # Test both even sharding (8) and uneven sharding (3)
        for mlp_dim in (8, 3):
            with torch.device("meta"):
                model = nn.Sequential(MLP(mlp_dim, with_buffer=True), MLP(mlp_dim))
                for param in model.parameters():
                    self.assertEqual(param.device, torch.device("meta"))
                fully_shard(model[0], mesh=mesh)
                fully_shard(model[1], mesh=mesh)
                fully_shard(model, mesh=mesh)
            for param in model.parameters():
                self.assertEqual(param.device, torch.device("meta"))
            self._test_to_empty_and_reset_parameters(model, mesh, mlp_dim)

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    @wrapSwapTensorsTest(True)
    def test_meta_device_2d_init(self):
        assert self.world_size >= 4, f"{self.world_size}"
        dp_size = 2
        global_mesh = init_device_mesh(
            "cuda", (dp_size, self.world_size // dp_size), mesh_dim_names=("dp", "tp")
        )
        dp_mesh, tp_mesh = global_mesh["dp"], global_mesh["tp"]

        # Test both even sharding (8) and uneven sharding (3)
        for mlp_dim in (8, 3):
            with torch.device("meta"):
                model = MLP(mlp_dim, with_buffer=True)
                for param in model.parameters():
                    self.assertEqual(param.device, torch.device("meta"))
                parallelize_module(
                    model,
                    tp_mesh,
                    {"in_proj": ColwiseParallel(), "out_proj": RowwiseParallel()},
                )
                for param in model.parameters():
                    self.assertEqual(param.device, torch.device("meta"))
                fully_shard(model.in_proj, mesh=dp_mesh)
                fully_shard(model.out_proj, mesh=dp_mesh)
                fully_shard(model, mesh=dp_mesh)
            for param in model.parameters():
                self.assertEqual(param.device, torch.device("meta"))
            self._test_to_empty_and_reset_parameters(model, global_mesh, mlp_dim)

    def _test_to_empty_and_reset_parameters(
        self, model: nn.Module, mesh: DeviceMesh, mlp_dim: int
    ):
        # Check that we can materialize it on GPU with empty values
        device = torch.device("cuda", torch.cuda.current_device())
        model.to_empty(device=device)
        for param in model.parameters():
            self.assertEqual(param.device, device)
        optim = torch.optim.Adam(model.parameters(), lr=1e-2)

        # Check that `reset_parameters()` on each module initializes values
        const = 1337
        for tensor in itertools.chain(model.parameters(), model.buffers()):
            tensor.detach().fill_(const)
        for module in model.modules():
            if hasattr(module, "reset_parameters"):
                module.reset_parameters()
        for param in model.parameters():
            local_tensor = param.to_local()
            if local_tensor.numel() > 0:
                self.assertNotEqual(local_tensor, torch.ones_like(local_tensor) * const)
        for buffer in model.buffers():
            self.assertNotEqual(buffer, torch.ones_like(buffer) * const)

        # Check that we can run an iteration without erroring
        inp = torch.randn((4, mlp_dim), device="cuda")
        model(inp).sum().backward()
        optim.step()

    @unittest.skipIf(not TEST_CUDA, "no cuda")
    def test_invalid_meta_device_init(self):
        default_pg = torch.distributed.distributed_c10d._get_default_group()
        mesh = init_device_mesh("cuda", mesh_shape=(default_pg.size(),))
        mlp_dim = 8
        with torch.device("meta"):
            model = nn.Sequential(MLP(mlp_dim, with_buffer=True), MLP(mlp_dim))
            for param in model.parameters():
                self.assertEqual(param.device, torch.device("meta"))
            fully_shard(model[0], mesh=mesh)
            fully_shard(model[1], mesh=mesh)
            fully_shard(model, mesh=mesh)
        inp = torch.randn((4, mlp_dim), device="cuda")
        error_regex = (
            "FSDP parameters should be materialized from meta device before training, "
            "but the following were still on meta device: "
            r"\['0.in_proj.weight', '0.in_proj.bias', '0.out_proj.weight', '0.out_proj.bias'\]"
        )
        with self.assertRaisesRegex(RuntimeError, error_regex):
            model(inp)


if __name__ == "__main__":
    run_tests()
