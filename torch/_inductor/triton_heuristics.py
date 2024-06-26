import builtins
import copy
import functools
import hashlib
import inspect
import json
import logging
import math
import operator
import os
import os.path
import re
import threading
from enum import auto, Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import torch

import torch.autograd.profiler as autograd_profiler
from torch._dynamo.device_interface import get_interface_for_device
from torch._dynamo.utils import dynamo_timed, get_first_attr
from torch.utils._triton import has_triton_package

from . import config
from .codecache import cache_dir, CudaKernelParamCache
from .coordinate_descent_tuner import CoordescTuner

from .ir import ReductionHint, TileHint
from .utils import (
    ceildiv,
    conditional_product,
    create_bandwidth_info_str,
    do_bench,
    get_max_y_grid,
    get_num_bytes,
    next_power_of_2,
    triton_config_to_hashable,
)


log = logging.getLogger(__name__)

if has_triton_package():
    import triton
    from triton import Config
    from triton.runtime.autotuner import OutOfResources
    from triton.runtime.jit import KernelInterface

    try:
        from triton.compiler.compiler import ASTSource
    except ImportError:
        ASTSource = None
else:
    Config = object
    triton = None
    KernelInterface = object
    OutOfResources = object
    ASTSource = None


_NUM_THREADS_PER_WARP = 32


class HeuristicType(Enum):
    PERSISTENT_REDUCTION = auto()
    POINTWISE = auto()
    REDUCTION = auto()
    SPLIT_SCAN = auto()
    TEMPLATE = auto()
    USER_AUTOTUNE = auto()


class AutotuneHint(Enum):
    ELEMENTS_PER_WARP_32 = 0

    # Triton codegen tries to codegen set of AutotuneHints.
    # Enum.__repr__ looks like "<AutotuneHint.ELEMENTS_PER_WARP_32: 0>""
    # which isn't valid python.
    # Enum.__str__ will just return "AutotuneHint.ELEMENTS_PER_WARP_32".
    __repr__ = Enum.__str__


def autotune_hints_to_configs(
    hints: Set[AutotuneHint], size_hints, block_size: int
) -> List[Config]:
    """
    AutotuneHints can be attached to the metadata of triton kernels for providing
    suggestions about what to try for autotuning. One reason to do this is if there are
    some configs that are only useful in specific scenarios, in which case we can avoid
    wasting compile time on autotuning unless we know we are in one of those scenarios.

    Based on those hints, this function will generate a list of additional autotuning
    configs to try.
    """
    xyz_options: Tuple[Tuple[int, Optional[int], Optional[int]], ...]
    configs = []

    for hint in hints:
        if hint == AutotuneHint.ELEMENTS_PER_WARP_32:
            if len(size_hints) == 1:
                xyz_options = ((block_size // 4, None, None),)
            elif len(size_hints) == 2:
                xyz_options = ((block_size // 4, 1, None), (1, block_size // 4, None))
            elif len(size_hints) == 3:
                xyz_options = (
                    (block_size // 4, 1, 1),
                    (1, block_size // 4, 1),
                    (1, 1, block_size // 4),
                )
            for xyz in xyz_options:
                configs.append(
                    triton_config(
                        size_hints,
                        *xyz,
                        num_elements_per_warp=32,
                    )
                )

    return configs


def disable_pointwise_autotuning():
    # Autotuning can give different benchmarking results from run to run, and
    # therefore we disable autotuning when use_deterministic flag is on.
    if torch.are_deterministic_algorithms_enabled():
        return True
    return not config.triton.autotune_pointwise


class CachingAutotuner(KernelInterface):
    """
    Simplified version of Triton autotuner that has no invalidation
    key and caches the best config to disk to improve cold start times.
    Unlike the main triton Autotuner, this version can precompile all
    configs, and does not rely on the Triton JIT.
    """

    def __init__(
        self,
        fn,
        triton_meta,  # passed directly to triton
        configs,
        save_cache_hook,
        mutated_arg_names,
        heuristic_type,
        size_hints=None,
        inductor_meta=None,  # metadata not relevant to triton
        custom_kernel=False,  # whether the kernel is inductor-generated or custom
    ):
        super().__init__()

        assert len(configs) > 0, "Non-empty TritonConfig list required for compiling"
        self.fn = fn
        self.triton_meta = triton_meta
        self.inductor_meta = {} if inductor_meta is None else inductor_meta
        self.save_cache_hook = save_cache_hook
        self.mutated_arg_names = mutated_arg_names
        self.configs = configs
        self.heuristic_type = heuristic_type
        self.custom_kernel = custom_kernel
        self.cuda_kernel_saved = False

        # Align the default design that default as cuda
        self.device_type = (
            triton_meta["device_type"] if "device_type" in triton_meta else "cuda"
        )
        self.gpu_device = get_interface_for_device(self.device_type)

        if log.isEnabledFor(logging.DEBUG):
            log.debug(
                "CachingAutotuner gets %d configs for %s",
                len(self.configs),
                self.fn.__name__,
            )
            for c in self.configs:
                log.debug(c)

        self.launchers = []
        self.lock = threading.Lock()
        if os.getenv("TRITON_CACHE_DIR") is None:
            os.environ["TRITON_CACHE_DIR"] = os.path.join(
                cache_dir(),
                "triton",
                str(self.triton_meta.get("device", 0)),
            )

        self.size_hints = size_hints
        self.coordesc_tuner = CoordescTuner(
            is_mm=False, name=self.fn.__name__, size_hints=size_hints
        )

        # pre-create the profiler context manager to reduce latency
        self.record_function_ctx = torch._C._profiler._RecordFunctionFast(
            self.inductor_meta.get("kernel_name", "triton kernel")
        )

    def precompile(self, warm_cache_only_with_cc=None):
        with self.lock:
            if self.launchers:
                return
            self.launchers = []
            compiled_binaries = []
            if not self.configs:
                raise RuntimeError("No triton configs are available")

            for c in self.configs:
                try:
                    compiled_binary, launcher = self._precompile_config(
                        c, warm_cache_only_with_cc
                    )
                except OutOfResources:
                    # Skip the config if we run out of resource
                    continue
                self.launchers.append(launcher)
                compiled_binaries.append(compiled_binary)

            if len(self.launchers) == 0:
                raise RuntimeError(
                    "No valid triton configs. Report a fatal compilation error"
                )

            seen_configs = set(self.configs)

            device_prop = self.gpu_device.Worker.get_device_properties(
                self.triton_meta["device"]
            )
            if (
                config.dynamic_scale_rblock
                and self.heuristic_type == HeuristicType.REDUCTION
                and self.size_hints is not None
                # Disable for AMDGPU as Triton is not ready to return n_regs for a compiled_binary.
                and torch.version.hip is None
                and device_prop.major >= 8
            ):
                for triton_config, compiled_binary in zip(
                    self.configs, compiled_binaries
                ):
                    assert len(self.size_hints) == 2
                    xblock = triton_config.kwargs.get("XBLOCK", 1)
                    rblock = triton_config.kwargs["RBLOCK"]
                    total_block = (self.size_hints[0] + xblock - 1) // xblock
                    nreg = getattr(compiled_binary, "n_regs", None)
                    if nreg is None:
                        continue

                    # make sure rblock is not too small
                    if rblock <= 64:
                        continue

                    # each SM of A100 has 65536 32-bit registers. To maximize
                    # the theoretical occupancy, we need run 2048 threads on each
                    # SM. So each thread should use no more than 65536 / 2048
                    # = 32 registers. In cases where occupancy matters, and each
                    # thread uses too many registers, reduce RBLOCK to reduce
                    # the register usage.
                    # For kernel https://gist.github.com/shunting314/e4cccc031fe30d378b9b23c08c238cbd
                    # from PLBartForCausalLM, latency improve from
                    # 7.795ms to 4.883ms.
                    #
                    if (
                        nreg
                        <= device_prop.regs_per_multiprocessor
                        // device_prop.max_threads_per_multi_processor
                    ):
                        continue

                    nreg_per_warp = nreg * 32
                    nreg_per_block = nreg_per_warp * triton_config.num_warps

                    # Previously we set max_blocks_per_sm to 'max_threads_per_multi_processo / (32 * num_warps)'
                    # The formula below is a tighter upper bound since we have the assumption that
                    #   nreg > device_prop.regs_per_multiprocessor // device_prop.max_threads_per_multi_processor
                    # due to the if condition above and:
                    #   regs_per_multiprocessor / nreg_per_block
                    #   = regs_per_multiprocessor / (nreg * 32 * num_warps)
                    #   < regs_per_multiprocessor / ((regs_per_multiprocessor / max_threads_per_multi_processor) * 32 * num_warps)
                    #   = max_threads_per_multi_processor / (32 * num_warps)
                    # Using a tigher upper bound can reveal more optimization opportunities.
                    max_blocks_per_sm = max(
                        device_prop.regs_per_multiprocessor // nreg_per_block, 1
                    )

                    if (
                        total_block
                        <= max_blocks_per_sm * device_prop.multi_processor_count
                    ):
                        # no need to improve occupancy
                        continue
                    new_config = copy.deepcopy(triton_config)
                    new_config.kwargs["RBLOCK"] = rblock // 2
                    if new_config in seen_configs:
                        continue
                    seen_configs.add(new_config)
                    self.launchers.append(
                        self._precompile_config(new_config, warm_cache_only_with_cc)[1]
                    )
            self.configs = None

    def _precompile_config(self, cfg: Config, warm_cache_only_with_cc: Optional[int]):
        """Ahead of time compile a given autotuner config."""
        compile_meta = copy.deepcopy(self.triton_meta)
        for k, v in cfg.kwargs.items():
            compile_meta["constants"][self.fn.arg_names.index(k)] = v
        compile_meta["num_warps"] = cfg.num_warps
        compile_meta["num_stages"] = cfg.num_stages
        compile_meta["debug"] = (
            config.assert_indirect_indexing and torch.version.hip is None
        )

        # Setting device_type="hip" required on ROCm to pass down to triton
        compile_meta["device_type"] = (
            self.device_type if torch.version.hip is None else "hip"
        )

        if warm_cache_only_with_cc:
            cc = warm_cache_only_with_cc
        else:
            # Use device_type 'cuda' for both cuda and hip devices to retrieve
            # the compute capability.
            device_type = self.device_type if torch.version.hip is None else "cuda"
            device_id = compile_meta["device"]
            device = torch.device(device_type, device_id)
            cc = self.gpu_device.get_compute_capability(device)

        compile_meta["cc"] = cc

        if ASTSource:
            compile_args = (
                ASTSource(
                    self.fn,
                    compile_meta["signature"],
                    compile_meta["constants"],
                    compile_meta["configs"][0],
                ),
            )

            target = (compile_meta["device_type"], cc)
            options = {
                "num_warps": compile_meta["num_warps"],
                "num_stages": compile_meta["num_stages"],
                "debug": compile_meta["debug"],
            }
            compile_kwargs = {
                "target": target,
                "options": options,
            }
        else:
            compile_args = (self.fn,)
            compile_kwargs = compile_meta

        if warm_cache_only_with_cc:
            return (
                triton.compile(*compile_args, **compile_kwargs),
                None,
            )

        # load binary to the correct device
        with self.gpu_device.device(compile_meta["device"]):  # type: ignore[attr-defined]
            # need to initialize context
            self.gpu_device.synchronize(self.gpu_device.current_device())

            try:
                binary = triton.compile(*compile_args, **compile_kwargs)
            except Exception:
                log.exception(
                    "Triton compilation failed: %s\n%s\nmetadata: %s",
                    self.inductor_meta.get("kernel_name", "triton_"),
                    self.fn.src,
                    compile_meta,
                )
                raise
            binary._init_handles()

        call_args = [
            arg
            for i, arg in enumerate(self.fn.arg_names)
            if i not in self.fn.constexprs
        ]
        def_args = [name for name in self.fn.arg_names if name not in cfg.kwargs]

        scope = {
            "grid_meta": cfg.kwargs,
            "bin": binary,
            "launch_enter_hook": binary.launch_enter_hook,
            "launch_exit_hook": binary.launch_exit_hook,
            "metadata": binary.metadata,
            "torch": torch,
            "set_device": self.gpu_device.set_device,
            "current_device": self.gpu_device.current_device,
        }

        scope["runner"] = get_first_attr(binary, "run", "c_wrapper")
        scope["function"] = get_first_attr(binary, "function", "cu_function")
        scope["cta_args"] = (
            (binary.num_ctas, *get_first_attr(binary, "cluster_dims", "clusterDims"))
            if hasattr(binary, "num_ctas")
            else (
                (binary.metadata.num_ctas, *binary.metadata.cluster_dims)
                if hasattr(binary, "metadata")
                else ()
            )
        )
        scope["num_warps"] = (
            binary.num_warps
            if hasattr(binary, "num_warps")
            else binary.metadata.num_warps
        )
        binary_shared = (
            binary.shared if hasattr(binary, "shared") else binary.metadata.shared
        )
        scope["shared"] = binary_shared

        exec(
            f"""
            def launcher({', '.join(def_args)}, grid, stream):
                if callable(grid):
                    grid_0, grid_1, grid_2 = grid(grid_meta)
                else:
                    grid_0, grid_1, grid_2 = grid

                runner(grid_0, grid_1, grid_2, num_warps,
                            *cta_args, shared,
                            stream, function,
                            launch_enter_hook,
                            launch_exit_hook,
                            metadata,
                            {', '.join(call_args)})
                return bin
            """.lstrip(),
            scope,
        )

        launcher = scope["launcher"]
        launcher.config = cfg
        launcher.n_regs = getattr(binary, "n_regs", None)
        launcher.n_spills = getattr(binary, "n_spills", None)
        launcher.shared = binary_shared
        launcher.store_cubin = config.triton.store_cubin
        # store this global variable to avoid the high overhead of reading it when calling run
        if launcher.store_cubin:
            launcher.fn = self.fn
            launcher.bin = binary

        return binary, launcher

    def bench(self, launcher, *args, grid, **kwargs):
        """Measure the performance of a given launcher"""
        # we don't skip configs wiht spilled registers when auto-tuning custom
        # (user-written) Triton kernels, as (i) we don't have any knowledge or
        # control over the kernel code; (ii) there is empirical evidence that
        # for some (complicated) custom Triton kernels, a register-spilling
        # config may yield the best latency.
        if not self.custom_kernel and launcher.n_spills > config.triton.spill_threshold:
            log.debug(
                "Skip config %s because of register spilling: %d",
                launcher.config,
                launcher.n_spills,
            )
            return float("inf")

        stream = self.gpu_device.get_raw_stream(  # type: ignore[call-arg]
            self.gpu_device.current_device()
        )

        def kernel_call():
            if launcher.config.pre_hook is not None:
                launcher.config.pre_hook(
                    {**dict(zip(self.arg_names, args)), **launcher.config.kwargs}
                )

            cloned_args, cloned_kwargs = self.clone_args(*args, **kwargs)
            launcher(
                *cloned_args,
                **cloned_kwargs,
                grid=grid,
                stream=stream,
            )

        return do_bench(kernel_call, rep=40, fast_flush=True)

    def clone_args(self, *args, **kwargs) -> Tuple[List[Any], Dict[str, Any]]:
        from .compile_fx import clone_preserve_strides

        # clone inplace buffers to avoid autotune contaminating them if
        # the kernel does in-place stores. avoid cloning other buffers because
        # it leads to increase memory use
        cloned_args = []
        for i, arg in enumerate(args):
            if self.fn.arg_names[i] in self.mutated_arg_names:
                assert isinstance(arg, torch.Tensor)
                cloned_args.append(clone_preserve_strides(arg))
            else:
                cloned_args.append(arg)

        cloned_kwargs: Dict[str, Any] = {}
        for name, arg in kwargs.items():
            if name in self.mutated_arg_names:
                assert isinstance(arg, torch.Tensor)
                cloned_kwargs[name] = clone_preserve_strides(arg)
            else:
                cloned_kwargs[name] = arg

        return cloned_args, cloned_kwargs

    @dynamo_timed
    def benchmark_all_configs(self, *args, **kwargs):
        timings = {
            launcher: self.bench(launcher, *args, **kwargs)
            for launcher in self.launchers
        }

        for k, v in timings.items():
            self.coordesc_tuner.cache_benchmark_result(k.config, v)

        if log.isEnabledFor(logging.DEBUG):
            log.debug("Benchmark all input configs for %s, get:", self.fn.__name__)
            for k, v in timings.items():
                log.debug(
                    "%s: %f, nreg %d, nspill %d, #shared-mem %s",
                    k.config,
                    v,
                    k.n_regs,
                    k.n_spills,
                    k.shared,
                )

        return timings

    def autotune_to_one_config(self, *args, **kwargs):
        """Do the actual autotuning"""
        timings = self.benchmark_all_configs(*args, **kwargs)
        self.launchers = [builtins.min(timings, key=timings.get)]
        if self.save_cache_hook:
            self.save_cache_hook(self.launchers[0].config)

    def save_cuda_kernel(self, grid, stream, launcher):
        if callable(grid):
            grid_x, grid_y, grid_z = grid(launcher.config.kwargs)
        else:
            grid_x, grid_y, grid_z = grid

        key = self.inductor_meta.get("kernel_name", None)  # unique kernel name
        assert key is not None, "kernel_name can not be None"
        params = {
            "mangled_name": launcher.bin.metadata.name
            if hasattr(launcher.bin.metadata, "name")
            else launcher.bin.metadata["name"],
            "grid_x": grid_x,
            "grid_y": grid_y,
            "grid_z": grid_z,
            "x_block": launcher.config.kwargs.get("XBLOCK", 1),
            "y_block": launcher.config.kwargs.get("YBLOCK", None),
            "z_block": launcher.config.kwargs.get("ZBLOCK", None),
            "num_warps": launcher.bin.num_warps
            if hasattr(launcher.bin, "num_warps")
            else launcher.bin.metadata.num_warps,
            "shared_mem": launcher.bin.shared
            if hasattr(launcher.bin, "shared")
            else launcher.bin.metadata.shared,
            "stream": stream,
            # User defined triton kernels will have arbitrary kwarg names
            "meta": launcher.config.kwargs,
        }

        if torch.version.hip is None:
            CudaKernelParamCache.set(key, params, launcher.bin.asm["cubin"])
        else:
            # There is some divergence between CUDA and ROCm here.
            # On ROCm's triton we only have the the path to the binary, not the binary itself.
            # For ROCm we will copy the binary to the new location instead of writing to file
            import pathlib

            launcher.bin.asm["hsaco"] = pathlib.Path(
                launcher.bin.asm["hsaco_path"]
            ).read_bytes()
            CudaKernelParamCache.set(key, params, launcher.bin.asm["hsaco"])

        self.cuda_kernel_saved = True

    def coordinate_descent_tuning(self, launcher, *args, **kwargs):
        """
        Coordinate descent tuning can be run with or without max-autotune.

        The only difference between these two is the starting config for coordinate_descent tuning.
        E.g., assuming regular autotune only get one config C1; while max-autotune get 4 configs C1, C2, C3, C4
        and max-autotune figure out C3 is the best.

        Then if coordinate descnt tuning is run with max-autotune disabled, it will start from C1;
        while if coordinate descent tuning is run with max-autotune enabled, it will start from C3.
        """
        if (
            self.heuristic_type == HeuristicType.TEMPLATE
            or self.heuristic_type == HeuristicType.USER_AUTOTUNE
        ):
            # skip triton template
            return launcher

        cloned_args, _ = self.clone_args(*args)
        config2launcher = {launcher.config: launcher}

        def benchmark_one_config(config):
            with self.lock:
                _, launcher = self._precompile_config(config, None)
            config2launcher[config] = launcher

            out = self.bench(launcher, *cloned_args, **kwargs)
            log.debug(
                "COORDESC: %s: %f, nreg %d, nspill %d, #shared-mem %d",
                launcher.config,
                out,
                launcher.n_regs,
                launcher.n_spills,
                launcher.shared,
            )
            return out

        assert not (
            self.heuristic_type == HeuristicType.PERSISTENT_REDUCTION
            and "RBLOCK" in launcher.config.kwargs
        ), "Coordinate descent tuner relies on the assumption that persistent reduction's triton config does not have RBLOCK"
        best_config = self.coordesc_tuner.autotune(
            benchmark_one_config, launcher.config, None
        )
        best_config.found_by_coordesc = True

        if self.save_cache_hook:
            self.save_cache_hook(best_config, found_by_coordesc=True)
        return config2launcher.get(best_config)

    def run(self, *args, grid, stream, **kwargs):
        if len(self.launchers) != 1:
            if len(self.launchers) == 0:
                self.precompile()
            if len(self.launchers) > 1:
                self.autotune_to_one_config(*args, grid=grid, **kwargs)

        if (
            not getattr(self.launchers[0].config, "found_by_coordesc", False)
            and config.coordinate_descent_tuning
        ):
            self.launchers = [
                self.coordinate_descent_tuning(
                    self.launchers[0], *args, grid=grid, **kwargs
                )
            ]

        (launcher,) = self.launchers
        if launcher.store_cubin:
            self.save_cuda_kernel(grid, stream, launcher)

        if launcher.config.pre_hook is not None:
            launcher.config.pre_hook(
                {**dict(zip(self.arg_names, args)), **launcher.config.kwargs, **kwargs}
            )

        # guard the record_function_ctx and only call it if profiling is currently
        # in progress, to reduce latency when profiler is not turned on. Note that
        # the "if" statement (instead of, say, a contextlib.nullcontext) is intentional;
        # it is faster than entering and exiting a context manager, even if the context
        # manager is a nullcontext.
        if autograd_profiler._is_profiler_enabled:
            with self.record_function_ctx:
                return launcher(
                    *args,
                    **kwargs,
                    grid=grid,
                    stream=stream,
                )
        else:
            return launcher(
                *args,
                **kwargs,
                grid=grid,
                stream=stream,
            )


def _find_names(obj):
    import gc
    import inspect

    frame = inspect.currentframe()
    while frame is not None:
        frame.f_locals
        frame = frame.f_back
    obj_names = []
    for referrer in gc.get_referrers(obj):
        if isinstance(referrer, dict):
            for k, v in referrer.items():
                if v is obj:
                    obj_names.append(k)
    return obj_names


collected_calls: List[Any] = []


def start_graph():
    collected_calls.clear()


def end_graph():
    if len(collected_calls) == 0:
        return
    overall_time = sum(call[0] for call in collected_calls)
    overall_gb = sum(call[1] for call in collected_calls)
    cur_file = inspect.stack()[1].filename
    summary_str = (
        f"SUMMARY ({cur_file})\n"
        f"{overall_time:.2f}ms   \t {overall_gb:.2f} GB\t {overall_gb/(overall_time/1e3):.2f}GB/s"
    )
    print(summary_str)
    print()
    output_file = config.profile_bandwidth_output
    if output_file is not None:
        # sort perf numbers in descending order, i.e. placing the
        # most runtime-heavy kernels at the top of the list
        sorted_calls = sorted(collected_calls, key=lambda c: float(c[0]), reverse=True)
        try:
            with open(output_file, "a") as file:
                log.debug("Save profile bandwidth results to %s", output_file)
                file.write("====================\n")
                file.write(f"TRITON KERNELS BANDWIDTH INFO ({cur_file})\n")
                for ms, num_gb, gb_per_s, kernel_name in sorted_calls:
                    # also display the runtime percentage for each kernel
                    percentage = f"{ms/overall_time*100:.2f}%"
                    suffix = f" \t {percentage} \t {kernel_name}"
                    bw_info_str = create_bandwidth_info_str(
                        ms,
                        num_gb,
                        gb_per_s,
                        suffix=suffix,
                        color=False,
                    )
                    file.write(bw_info_str + "\n")
                file.write(f"{summary_str}\n\n")
        except Exception as e:
            log.warning(
                "failed to write profile bandwidth result into %s: %s",
                output_file,
                e,
            )


class DebugAutotuner(CachingAutotuner):
    def __init__(self, *args, regex_filter="", **kwargs):
        self.regex_filter = regex_filter
        super().__init__(*args, **kwargs)
        self.cached = None

    def run(self, *args, grid, stream):
        possible_names = _find_names(self)
        kernel_name = f"{max(possible_names, key=len)}"
        if not re.match(self.regex_filter, kernel_name):
            return
        super().run(*args, grid=grid, stream=stream)
        (launcher,) = self.launchers

        if self.cached is None:
            ms = self.bench(launcher, *args, grid=grid)
            num_in_out_ptrs = len(
                [
                    arg_name
                    for arg_name in self.fn.arg_names
                    if arg_name.startswith("in_out_ptr")
                ]
            )
            num_gb = self.inductor_meta.get("kernel_num_gb", None)
            if num_gb is None:
                num_gb = get_num_bytes(*args, num_in_out_args=num_in_out_ptrs) / 1e9
            gb_per_s = num_gb / (ms / 1e3)
            self.cached = (ms, num_gb, gb_per_s, kernel_name)
        else:
            ms, num_gb, gb_per_s, kernel_name = self.cached
        collected_calls.append((ms, num_gb, gb_per_s, kernel_name))
        print(
            create_bandwidth_info_str(ms, num_gb, gb_per_s, suffix=f" \t {kernel_name}")
        )


def hash_configs(configs: List[Config]):
    """
    Hash used to check for changes in configurations
    """
    hasher = hashlib.sha256()
    for cfg in configs:
        hasher.update(
            f"{sorted(cfg.kwargs.items())} {cfg.num_warps} {cfg.num_stages}\n".encode()
        )
    return hasher.hexdigest()


def load_cached_autotuning(
    best_config,
    configs_hash: str,
    configs: List[Config],
):
    if best_config is None:
        return None
    if best_config.pop("configs_hash", None) != configs_hash:
        return None

    if config.coordinate_descent_tuning and best_config.pop("found_by_coordesc", False):
        num_warps = best_config.pop("num_warps")
        num_stages = best_config.pop("num_stages")
        triton_config = Config(best_config, num_warps=num_warps, num_stages=num_stages)
        triton_config.found_by_coordesc = True
        return triton_config

    matching_configs = [
        cfg
        for cfg in configs
        if all(val == best_config.get(key) for key, val in cfg.kwargs.items())
        and cfg.num_warps == best_config.get("num_warps")
        and cfg.num_stages == best_config.get("num_stages")
    ]
    if len(matching_configs) != 1:
        return None

    return matching_configs[0]


def cached_autotune(
    size_hints: Optional[List[int]],
    configs: List[Config],
    triton_meta,
    heuristic_type,
    filename=None,
    inductor_meta=None,
    custom_kernel=False,
):
    """
    A copy of triton.autotune that calls our subclass.  Our subclass
    has additional debugging, error handling, and on-disk caching.
    """
    configs = unique_configs(configs)
    assert len(configs) == 1 or filename
    save_cache_hook: Optional[Callable[[Any, Any], Any]]
    inductor_meta = {} if inductor_meta is None else inductor_meta

    # on disk caching logic and/or remote caching
    if filename is not None and (len(configs) > 1 or config.coordinate_descent_tuning):
        configs_hash = hash_configs(configs)

        cache_filename = None
        remote_cache = None
        remote_cache_key = None
        if config.use_autotune_local_cache:
            cache_filename = os.path.splitext(filename)[0] + ".best_config"
        if config.use_autotune_remote_cache or (
            config.is_fbcode()
            and torch._utils_internal.justknobs_check(
                "pytorch/autotune_remote_cache:enable"
            )
        ):
            backend_hash = inductor_meta.get("backend_hash", None)
            if backend_hash is not None:
                key = backend_hash + configs_hash + "autotune-best-config"
                key = hashlib.sha256(key.encode("utf-8")).hexdigest()

                try:
                    if config.is_fbcode():
                        remote_cache = (
                            triton.runtime.fb_memcache.FbMemcacheRemoteCacheBackend(
                                key, is_autotune=True
                            )
                        )
                    else:
                        remote_cache = triton.runtime.cache.RedisRemoteCacheBackend(key)
                except Exception:
                    remote_cache = None
                    log.warning("Unable to create a remote cache", exc_info=True)
                # we already sha256 hash the source contents
                remote_cache_key = os.path.basename(filename)
            else:
                log.debug(
                    "backend_hash is not passed on the inductor_meta, unable to use autotune remote cache"
                )

        best_config = None
        if cache_filename is not None and os.path.exists(cache_filename):
            with open(cache_filename) as fd:
                best_config = json.loads(fd.read())
        elif remote_cache is not None and remote_cache_key is not None:
            cache_outs = remote_cache.get([remote_cache_key])
            cache_out = cache_outs.get(remote_cache_key, None)
            best_config = json.loads(cache_out) if cache_out else None

        best_config = load_cached_autotuning(best_config, configs_hash, configs)
        if best_config:
            configs = [best_config]

        def save_cache_hook(cfg, found_by_coordesc=False):
            data = json.dumps(
                {
                    **cfg.kwargs,
                    "num_warps": cfg.num_warps,
                    "num_stages": cfg.num_stages,
                    "configs_hash": configs_hash,
                    "found_by_coordesc": found_by_coordesc,
                }
            )
            if cache_filename is not None:
                with open(cache_filename, "w") as fd:
                    fd.write(data)
            if remote_cache is not None and remote_cache_key is not None:
                remote_cache.put(remote_cache_key, data)

            if log.isEnabledFor(logging.DEBUG):
                type_str = "coordesc" if found_by_coordesc else "heuristic"
                log.debug("Save %s tuning result to %s", type_str, cache_filename)

    else:
        save_cache_hook = None

    mutated_arg_names = inductor_meta.pop("mutated_arg_names", ())

    def decorator(fn):
        # Remove XBLOCK from config if it's not a function argument.
        # This way, coordinate descent tuning will not try to tune it.
        #
        # Context: When TritonKernel.no_x_dim is True, we hardcode XBLOCK to 1.
        import inspect

        if "XBLOCK" not in inspect.signature(fn.fn).parameters:
            for tconfig in configs:
                if "XBLOCK" in tconfig.kwargs:
                    assert tconfig.kwargs["XBLOCK"] == 1
                    tconfig.kwargs.pop("XBLOCK")

        if config.profile_bandwidth:
            return DebugAutotuner(
                fn,
                triton_meta=triton_meta,
                inductor_meta=inductor_meta,
                regex_filter=config.profile_bandwidth_regex,
                configs=configs,
                save_cache_hook=save_cache_hook,
                mutated_arg_names=mutated_arg_names,
                heuristic_type=heuristic_type,
                size_hints=size_hints,
                custom_kernel=custom_kernel,
            )
        return CachingAutotuner(
            fn,
            triton_meta=triton_meta,
            inductor_meta=inductor_meta,
            configs=configs,
            save_cache_hook=save_cache_hook,
            mutated_arg_names=mutated_arg_names,
            heuristic_type=heuristic_type,
            size_hints=size_hints,
            custom_kernel=custom_kernel,
        )

    return decorator


def unique_configs(configs: List[Config]):
    """Remove duplicate configurations"""
    seen = set()
    pruned_configs = []

    for cfg in configs:
        key = triton_config_to_hashable(cfg)
        if key not in seen:
            seen.add(key)
            pruned_configs.append(cfg)
    return pruned_configs


def check_config(cfg, *, xnumel=None, ynumel=None, znumel=None):
    for numel, label in zip((xnumel, ynumel, znumel), "XYZ"):
        if numel is None:
            continue
        block = cfg[f"{label}BLOCK"]
        if numel == 1:
            assert block == 1, (
                f"TritonKernel.indexing assumes numel == 1 => BLOCK == 1"
                f" but {label.lower()}numel=={numel} and {label}BLOCK={block} (cfg={cfg})."
            )
        max_block = config.triton.max_block[label]
        max_block_str = f'config.triton.max_block["{label}"]'
        assert max_block % block == 0, (
            f"TritonKernel.indexing assumes {label}BLOCK divides {max_block_str}"
            f" but {label}BLOCK={block} and {max_block_str}={max_block} (cfg={cfg})."
        )


def triton_config(
    size_hints,
    x,
    y=None,
    z=None,
    num_stages=1,
    num_elements_per_warp=256,
    min_elem_per_thread=0,
) -> Config:
    """
    Construct a pointwise triton config with some adjustment heuristics
    based on size_hints. Size_hints is a tuple of numels in each tile
    dimension and will be rounded up to the nearest power of 2.

    num_elements_per_warp is a suggestion for controlling how many warps
    the triton config should contain. e.g.: if x=16, y=8, z=4 then
    num_elements = 16*8*4 = 512. Then if we set num_elements_per_warp=128,
    we'll launch 512 (elem) / 128 (elem/warp) = 4 warps. Note that it's
    just a suggestion, and sometimes other adjustment heuristics will
    override the num_elements_per_warp.

    min_elem_per_thread controls the minimum number of elements
    processed by each thread. It's always enforced.
    """
    # Ideally we want to read this from some device config

    # for a 2d size_hints [a, b], a should be mapped to YBLOCK rather than XBLOCK
    size_hints = list(reversed(size_hints))

    maxGridSize = [2147483647, 65535, 65535]

    target = conditional_product(x, y, z)
    if conditional_product(*size_hints) < target:
        target //= 8

    # shrink sizes to size hints
    x = min(x, size_hints[0])
    if y:
        y = min(y, size_hints[1])
    if z:
        z = min(z, size_hints[2])

    # if we are below original block size, scale up where we can;
    # or if the calculated grid size is larger than the limit, we bump up the corresponding dimension
    while x < min(size_hints[0], config.triton.max_block["X"]) and (
        x * maxGridSize[0] < size_hints[0] or conditional_product(x, y, z) < target
    ):
        x *= 2
    while (
        y
        and y < min(size_hints[1], config.triton.max_block["Y"])
        and (
            y * maxGridSize[1] < size_hints[1] or conditional_product(x, y, z) < target
        )
    ):
        y *= 2
    while (
        z
        and z < min(size_hints[2], config.triton.max_block["Z"])
        and (
            z * maxGridSize[2] < size_hints[2] or conditional_product(x, y, z) < target
        )
    ):
        z *= 2

    num_warps = next_power_of_2(
        min(max(conditional_product(x, y, z) // num_elements_per_warp, 1), 8)
    )
    # we are going to arrive at 2 warps only if bs was too small due to
    # numel being too small. However to workaround some ptx bugs we still
    # want at least 4 warps if there's enough elements per thread
    # given that this is a rare situation, don't expect this to affect perf
    # in general
    # see https://github.com/pytorch/pytorch/pull/97950
    num_warps = max(num_warps, 4) if conditional_product(x, y, z) >= 128 else num_warps
    xnumel = size_hints[0]
    ynumel = size_hints[1] if y else None
    znumel = size_hints[2] if z else None

    # Increase x to satisfy min_elem_per_thread requirements.
    block_size = max(
        conditional_product(x, y, z),
        min_elem_per_thread * _NUM_THREADS_PER_WARP * num_warps,
    )
    x *= math.ceil(block_size / conditional_product(x, y, z))

    cfg = {"XBLOCK": x}
    if y:
        cfg["YBLOCK"] = y
    if z:
        cfg["ZBLOCK"] = z
    check_config(cfg, xnumel=xnumel, ynumel=ynumel, znumel=znumel)
    return Config(cfg, num_warps=num_warps, num_stages=num_stages)


def triton_config_reduction(size_hints, x, r, num_stages=1, num_warps=None) -> Config:
    """
    Construct a reduction triton config with some adjustment heuristics
    based on size_hints. Size_hints is a tuple of numels in each tile
    dimension and will be rounded up to the nearest power of 2.
    """

    target = conditional_product(x, r)
    if conditional_product(*size_hints) < target:
        target //= 8

    # shrink sizes to size hints
    x = min(x, size_hints[0])
    r = min(r, size_hints[1])

    # if we are below original block size, scale up where we can
    while x < size_hints[0] and conditional_product(x, r) < target:
        x *= 2
    while r < size_hints[1] and conditional_product(x, r) < target:
        r *= 2

    cfg = {"XBLOCK": x, "RBLOCK": r}
    if num_warps is None:
        num_warps = conditional_product(x, r) // 128
    num_warps = next_power_of_2(min(max(num_warps, 2), 8))
    check_config(cfg, xnumel=size_hints[0])
    assert (
        r <= config.triton.max_block["R"]
    ), f"increase config.triton.MAX_BLOCK['r'] to {r}"
    return Config(cfg, num_warps=num_warps, num_stages=num_stages)


def triton_config_tiled_reduction(size_hints, x, y, r, num_stages=1):
    """
    Construct a tile reduction triton config with some adjustment
    heuristics based on size_hints. Size_hints is a tuple of numels in
    each tile dimension and will be rounded up to the nearest power of 2.
    """

    target = conditional_product(x, y, r)
    if conditional_product(*size_hints) < target:
        target //= 8

    # shrink sizes to size hints
    x = min(x, size_hints[0])
    y = min(y, size_hints[1])
    r = min(r, size_hints[2])

    # if we are below original block size, scale up where we can
    while x < size_hints[0] and conditional_product(x, y, r) < target:
        x *= 2
    while r < size_hints[2] and conditional_product(x, y, r) < target:
        r *= 2
    while y < size_hints[1] and conditional_product(x, y, r) < target:
        y *= 2

    cfg = {"XBLOCK": x, "YBLOCK": y, "RBLOCK": r}
    num_warps = next_power_of_2(min(max(conditional_product(x, y, r) // 256, 1), 8))
    check_config(cfg, xnumel=size_hints[0], ynumel=size_hints[1])
    assert (
        r <= config.triton.max_block["R"]
    ), f"increase config.triton.MAX_BLOCK['r'] to {r}"
    return Config(cfg, num_warps=num_warps, num_stages=num_stages)


def pointwise(
    size_hints,
    triton_meta,
    tile_hint=None,
    filename=None,
    min_elem_per_thread=0,
    inductor_meta=None,
):
    """
    Construct @triton.heuristics() based on size_hints.
    """
    inductor_meta = {} if inductor_meta is None else inductor_meta
    assert not inductor_meta.get("no_x_dim")

    numel = functools.reduce(operator.mul, size_hints)
    bs = max(256, min(numel // 128, 1024))

    hinted_configs = autotune_hints_to_configs(
        inductor_meta.get("autotune_hints", set()), size_hints, bs
    )

    triton_config_with_settings = functools.partial(
        triton_config, min_elem_per_thread=min_elem_per_thread
    )

    if len(size_hints) == 1:
        if disable_pointwise_autotuning() and not (
            config.max_autotune or config.max_autotune_pointwise
        ):
            return cached_autotune(
                size_hints,
                [triton_config_with_settings(size_hints, bs)],
                triton_meta=triton_meta,
                inductor_meta=inductor_meta,
                heuristic_type=HeuristicType.POINTWISE,
                filename=filename,
            )
        else:
            return cached_autotune(
                size_hints,
                [
                    triton_config_with_settings(
                        size_hints, bs, num_elements_per_warp=256
                    ),
                    triton_config_with_settings(
                        size_hints, bs // 2, num_elements_per_warp=64
                    ),
                    *hinted_configs,
                ],
                triton_meta=triton_meta,
                inductor_meta=inductor_meta,
                heuristic_type=HeuristicType.POINTWISE,
                filename=filename,
            )
    if len(size_hints) == 2:
        if (disable_pointwise_autotuning() or tile_hint == TileHint.SQUARE) and not (
            config.max_autotune or config.max_autotune_pointwise
        ):
            return cached_autotune(
                size_hints,
                [triton_config_with_settings(size_hints, 32, 32)],
                triton_meta=triton_meta,
                inductor_meta=inductor_meta,
                heuristic_type=HeuristicType.POINTWISE,
                filename=filename,
            )
        return cached_autotune(
            size_hints,
            [
                triton_config_with_settings(size_hints, 32, 32),
                triton_config_with_settings(size_hints, 64, 64),  # ~8% better for fp16
                triton_config_with_settings(size_hints, 256, 16),
                triton_config_with_settings(size_hints, 16, 256),
                triton_config_with_settings(size_hints, bs, 1),
                triton_config_with_settings(size_hints, 1, bs),
                *hinted_configs,
            ],
            triton_meta=triton_meta,
            inductor_meta=inductor_meta,
            filename=filename,
            heuristic_type=HeuristicType.POINTWISE,
        )
    if len(size_hints) == 3:
        if disable_pointwise_autotuning():
            return cached_autotune(
                size_hints,
                [triton_config_with_settings(size_hints, 16, 16, 16)],
                triton_meta=triton_meta,
                inductor_meta=inductor_meta,
                heuristic_type=HeuristicType.POINTWISE,
                filename=filename,
            )
        return cached_autotune(
            size_hints,
            [
                triton_config_with_settings(size_hints, 16, 16, 16),
                triton_config_with_settings(size_hints, 64, 8, 8),
                triton_config_with_settings(size_hints, 8, 64, 8),
                triton_config_with_settings(size_hints, 8, 8, 64),
                triton_config_with_settings(size_hints, bs, 1, 1),
                triton_config_with_settings(size_hints, 1, bs, 1),
                triton_config_with_settings(size_hints, 1, 1, bs),
                *hinted_configs,
            ],
            triton_meta=triton_meta,
            inductor_meta=inductor_meta,
            filename=filename,
            heuristic_type=HeuristicType.POINTWISE,
        )
    raise NotImplementedError(f"size_hints: {size_hints}")


def _reduction_configs(
    *, size_hints: List[int], inductor_meta: Dict[str, Any]
) -> List[Config]:
    reduction_hint = inductor_meta.get("reduction_hint", None)
    assert len(size_hints) == 2
    rnumel = size_hints[-1]

    contiguous_config = triton_config_reduction(
        size_hints, 1, (rnumel if 256 <= rnumel < 2048 else 2048)
    )
    outer_config = triton_config_reduction(size_hints, 64, 8)
    tiny_config = triton_config_reduction(
        size_hints, 2 * (256 // rnumel) if rnumel <= 256 else 1, min(rnumel, 2048)
    )
    if config.max_autotune or config.max_autotune_pointwise:
        pass  # skip all these cases
    elif reduction_hint == ReductionHint.INNER:
        return [contiguous_config]
    elif reduction_hint == ReductionHint.OUTER:
        return [outer_config]
    elif reduction_hint == ReductionHint.OUTER_TINY:
        return [tiny_config]
    if disable_pointwise_autotuning():
        return [triton_config_reduction(size_hints, 32, 128)]
    return [
        contiguous_config,
        outer_config,
        tiny_config,
        triton_config_reduction(size_hints, 64, 64),
        triton_config_reduction(size_hints, 8, 512),
        # halve the XBLOCK/RBLOCK compared to outer_config
        # TODO: this may only be beneficial when each iteration of the reduction
        # is quite heavy. E.g. https://gist.github.com/shunting314/189a8ef69f90db9d614a823385147a72
        triton_config_reduction(size_hints, 64, 4, num_warps=8),
    ]


def reduction(
    size_hints,
    reduction_hint=False,
    triton_meta=None,
    filename=None,
    inductor_meta=None,
):
    """args to @triton.heuristics()"""
    inductor_meta = {} if inductor_meta is None else inductor_meta
    inductor_meta["reduction_hint"] = reduction_hint
    if inductor_meta.get("no_x_dim"):
        size_hints = [1, *size_hints[1:]]

    assert triton_meta is not None
    rnumel = size_hints[-1]
    if len(size_hints) != 2:
        raise NotImplementedError(f"size_hints: {size_hints}")

    configs = _reduction_configs(size_hints=size_hints, inductor_meta=inductor_meta)
    return cached_autotune(
        size_hints,
        configs=configs,
        triton_meta=triton_meta,
        inductor_meta=inductor_meta,
        heuristic_type=HeuristicType.REDUCTION,
        filename=filename,
    )


def persistent_reduction(
    size_hints,
    reduction_hint=False,
    triton_meta=None,
    filename=None,
    inductor_meta=None,
):
    inductor_meta = {} if inductor_meta is None else inductor_meta
    inductor_meta["reduction_hint"] = reduction_hint
    if inductor_meta.get("no_x_dim"):
        size_hints = [1, *size_hints[1:]]

    xnumel, rnumel = size_hints

    configs = [
        triton_config_reduction(size_hints, xblock, rnumel)
        for xblock in (1, 8, 32, 128)
        if xblock == 1 or (rnumel * xblock <= 4096 and xblock <= xnumel)
    ]

    # TODO(jansel): we should be able to improve these heuristics
    if reduction_hint == ReductionHint.INNER and rnumel >= 256:
        configs = configs[:1]
    elif reduction_hint == ReductionHint.OUTER:
        configs = configs[-1:]
    elif reduction_hint == ReductionHint.OUTER_TINY:
        configs = [
            triton_config_reduction(
                size_hints, 2 * (256 // rnumel) if rnumel <= 256 else 1, rnumel
            )
        ]
    for c in configs:
        # we don't need RBLOCK for persistent reduction
        c.kwargs.pop("RBLOCK")

    if disable_pointwise_autotuning():
        configs = configs[:1]

    return cached_autotune(
        size_hints,
        configs,
        triton_meta=triton_meta,
        inductor_meta=inductor_meta,
        filename=filename,
        heuristic_type=HeuristicType.PERSISTENT_REDUCTION,
    )


def split_scan(
    size_hints,
    reduction_hint=False,
    triton_meta=None,
    filename=None,
    inductor_meta=None,
):
    """Heuristic for TritonSplitScanKernel"""
    inductor_meta = {} if inductor_meta is None else inductor_meta
    inductor_meta["reduction_hint"] = reduction_hint
    if inductor_meta.get("no_x_dim"):
        size_hints = [1, *size_hints[1:]]

    assert triton_meta is not None
    rnumel = size_hints[-1]
    if len(size_hints) != 2:
        raise NotImplementedError(f"size_hints: {size_hints}")

    configs = _reduction_configs(size_hints=size_hints, inductor_meta=inductor_meta)

    # Fixup configs to enforce the minimum RBLOCK size
    min_rblock = config.triton.min_split_scan_rblock
    for cfg in configs:
        if cfg.kwargs["RBLOCK"] < min_rblock:
            cfg.kwargs["RBLOCK"] = min_rblock

    return cached_autotune(
        size_hints,
        configs=configs,
        triton_meta=triton_meta,
        inductor_meta=inductor_meta,
        heuristic_type=HeuristicType.SPLIT_SCAN,
        filename=filename,
    )


def template(num_stages, num_warps, triton_meta, filename=None, inductor_meta=None):
    """
    Compile a triton template
    """
    return cached_autotune(
        None,
        [triton.Config({}, num_stages=num_stages, num_warps=num_warps)],
        triton_meta=triton_meta,
        inductor_meta=inductor_meta,
        heuristic_type=HeuristicType.TEMPLATE,
        filename=filename,
    )


def user_autotune(
    configs, triton_meta, filename=None, inductor_meta=None, custom_kernel=False
):
    """
    Compile a user defined triton kernel
    """
    defaults = inspect.signature(triton.Config).parameters
    default_num_stages = defaults["num_stages"].default
    default_num_warps = defaults["num_warps"].default

    if len(configs) == 0:
        configs = [
            triton.Config(
                {}, num_stages=default_num_stages, num_warps=default_num_warps
            )
        ]
    else:
        configs = [
            triton.Config(
                c.get("kwargs", {}),
                num_stages=c.get("num_stages", default_num_stages),
                num_warps=c.get("num_warps", default_num_warps),
            )
            for c in configs
        ]

    return cached_autotune(
        None,
        configs,
        triton_meta=triton_meta,
        heuristic_type=HeuristicType.USER_AUTOTUNE,
        filename=filename,
        inductor_meta=inductor_meta,
        custom_kernel=custom_kernel,
    )


def foreach(triton_meta, num_warps, filename=None, inductor_meta=None):
    """
    Compile a triton foreach kernel
    """
    return cached_autotune(
        None,
        [triton.Config({}, num_stages=1, num_warps=num_warps)],
        triton_meta=triton_meta,
        inductor_meta=inductor_meta,
        heuristic_type=HeuristicType.TEMPLATE,
        filename=filename,
    )


def grid(*numels):
    """Helper function to compute triton grids"""
    if len(numels) == 1:
        xnumel, ynumel, znumel = numels[0], None, None
    elif len(numels) == 2:
        xnumel, ynumel, znumel = numels[1], numels[0], None
    elif len(numels) == 3:
        xnumel, ynumel, znumel = numels[2], numels[1], numels[0]
    else:
        raise AssertionError(f"invalid size for numels {len(numels)}")

    def get_grid_dim(numel, block):
        if numel is None:
            return 1
        if block is None:
            return numel
        return ceildiv(numel, block)

    max_grid_dims = config.triton.max_tiles

    def grid_fn(meta):
        x_grid = get_grid_dim(xnumel, meta.get("XBLOCK", 1))
        y_grid = get_grid_dim(ynumel, meta.get("YBLOCK", None))

        MAX_Y_GRID = get_max_y_grid()
        if znumel is None and max_grid_dims <= 2:
            div = ceildiv(y_grid, MAX_Y_GRID)
            y_grid = y_grid // div
            z_grid = div
        else:
            z_grid = get_grid_dim(znumel, meta.get("ZBLOCK", None))
            torch._check(
                y_grid <= MAX_Y_GRID,
                lambda: f"Generated y grid beyond 2^16 ({y_grid}) not supported with z dimension present. File issue",
            )

        return (
            x_grid,
            y_grid,
            z_grid,
        )

    return grid_fn


def split_scan_grid(xnumel, rnumel):
    def grid_fn(meta):
        assert meta.get("XBLOCK", 1) == 1
        return (ceildiv(rnumel, meta.get("RBLOCK", 1)), xnumel, 1)

    return grid_fn
