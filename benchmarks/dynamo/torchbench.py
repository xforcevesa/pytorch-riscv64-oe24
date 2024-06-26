#!/usr/bin/env python3
import functools
import gc
import importlib
import logging
import os
import re
import sys
import warnings
from os.path import abspath, exists

import torch
import yaml

try:
    from .common import BenchmarkRunner, main
except ImportError:
    from common import BenchmarkRunner, main

from torch._dynamo.testing import collect_results, reduce_to_scalar_loss
from torch._dynamo.utils import clone_inputs

# We are primarily interested in tf32 datatype
torch.backends.cuda.matmul.allow_tf32 = True


def setup_torchbench_cwd():
    original_dir = abspath(os.getcwd())

    os.environ["KALDI_ROOT"] = "/tmp"  # avoids some spam
    for torchbench_dir in (
        "./torchbenchmark",
        "../torchbenchmark",
        "../torchbench",
        "../benchmark",
        "../../torchbenchmark",
        "../../torchbench",
        "../../benchmark",
    ):
        if exists(torchbench_dir):
            break

    if exists(torchbench_dir):
        torchbench_dir = abspath(torchbench_dir)
        os.chdir(torchbench_dir)
        sys.path.append(torchbench_dir)

    return original_dir


@functools.lru_cache(maxsize=1)
def load_yaml_file():
    filename = "torchbench.yaml"
    filepath = os.path.join(os.path.dirname(__file__), filename)

    with open(filepath) as f:
        data = yaml.safe_load(f)

    def flatten(lst):
        for item in lst:
            if isinstance(item, list):
                yield from flatten(item)
            else:
                yield item

    def maybe_list_to_set(obj):
        if isinstance(obj, dict):
            return {k: maybe_list_to_set(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return set(flatten(obj))
        return obj

    return maybe_list_to_set(data)


class TorchBenchmarkRunner(BenchmarkRunner):
    def __init__(self):
        super().__init__()
        self.suite_name = "torchbench"
        self.optimizer = None

    @property
    def _config(self):
        return load_yaml_file()

    @property
    def _skip(self):
        return self._config["skip"]

    @property
    def _batch_size(self):
        return self._config["batch_size"]

    @property
    def _tolerance(self):
        return self._config["tolerance"]

    @property
    def _accuracy(self):
        return self._config["accuracy"]

    @property
    def skip_models(self):
        return self._skip["all"]

    @property
    def skip_models_for_cpu(self):
        return self._skip["device"]["cpu"]

    @property
    def skip_models_for_cuda(self):
        return self._skip["device"]["cuda"]

    @property
    def skip_models_for_freezing(self):
        return self._skip["freezing"]

    @property
    def slow_models(self):
        return self._config["slow"]

    @property
    def very_slow_models(self):
        return self._config["very_slow"]

    @property
    def non_deterministic_models(self):
        return self._config["non_deterministic"]

    @property
    def skip_not_suitable_for_training_models(self):
        return self._skip["test"]["training"]

    @property
    def failing_fx2trt_models(self):
        return self._config["trt_not_yet_working"]

    @property
    def force_amp_for_fp16_bf16_models(self):
        return self._config["dtype"]["force_amp_for_fp16_bf16_models"]

    @property
    def force_fp16_for_bf16_models(self):
        return self._config["dtype"]["force_fp16_for_bf16_models"]

    @property
    def skip_accuracy_checks_large_models_dashboard(self):
        if self.args.dashboard or self.args.accuracy:
            return self._accuracy["skip"]["large_models"]
        return set()

    @property
    def skip_accuracy_check_as_eager_non_deterministic(self):
        if self.args.accuracy and self.args.training:
            return self._accuracy["skip"]["eager_not_deterministic"]
        return set()

    @property
    def skip_multiprocess_models(self):
        return self._skip["multiprocess"]

    @property
    def skip_models_due_to_control_flow(self):
        return self._skip["control_flow"]

    def load_model(
        self,
        device,
        model_name,
        batch_size=None,
        part=None,
        extra_args=None,
    ):
        if self.args.enable_activation_checkpointing:
            raise NotImplementedError(
                "Activation checkpointing not implemented for Torchbench models"
            )
        is_training = self.args.training
        use_eval_mode = self.args.use_eval_mode
        dynamic_shapes = self.args.dynamic_shapes
        candidates = [
            f"torchbenchmark.models.{model_name}",
            f"torchbenchmark.canary_models.{model_name}",
            f"torchbenchmark.models.fb.{model_name}",
        ]
        for c in candidates:
            try:
                module = importlib.import_module(c)
                break
            except ModuleNotFoundError as e:
                if e.name != c:
                    raise
        else:
            raise ImportError(f"could not import any of {candidates}")
        benchmark_cls = getattr(module, "Model", None)
        if benchmark_cls is None:
            raise NotImplementedError(f"{model_name}.Model is None")

        if not hasattr(benchmark_cls, "name"):
            benchmark_cls.name = model_name

        cant_change_batch_size = (
            not getattr(benchmark_cls, "ALLOW_CUSTOMIZE_BSIZE", True)
            or model_name in self._config["dont_change_batch_size"]
        )
        if cant_change_batch_size:
            batch_size = None
        if (
            batch_size is None
            and is_training
            and model_name in self._batch_size["training"]
        ):
            batch_size = self._batch_size["training"][model_name]
        elif (
            batch_size is None
            and not is_training
            and model_name in self._batch_size["inference"]
        ):
            batch_size = self._batch_size["inference"][model_name]

        # Control the memory footprint for few models
        if self.args.accuracy and model_name in self._accuracy["max_batch_size"]:
            batch_size = min(batch_size, self._accuracy["max_batch_size"][model_name])

        # workaround "RuntimeError: not allowed to set torch.backends.cudnn flags"
        torch.backends.__allow_nonbracketed_mutation_flag = True
        if extra_args is None:
            extra_args = []
        if part:
            extra_args += ["--part", part]

        # sam_fast only runs with amp
        if model_name == "sam_fast":
            self.args.amp = True
            self.setup_amp()

        if model_name == "vision_maskrcnn" and is_training:
            # Output of vision_maskrcnn model is a list of bounding boxes,
            # sorted on the basis of their scores. This makes accuracy
            # comparison hard with torch.compile. torch.compile can cause minor
            # divergences in the output because of how fusion works for amp in
            # TorchInductor compared to eager.  Therefore, instead of looking at
            # all the bounding boxes, we compare only top 4.
            model_kwargs = {"box_detections_per_img": 4}
            benchmark = benchmark_cls(
                test="train",
                device=device,
                batch_size=batch_size,
                extra_args=extra_args,
                model_kwargs=model_kwargs,
            )
        elif is_training:
            benchmark = benchmark_cls(
                test="train",
                device=device,
                batch_size=batch_size,
                extra_args=extra_args,
            )
        else:
            benchmark = benchmark_cls(
                test="eval",
                device=device,
                batch_size=batch_size,
                extra_args=extra_args,
            )
        model, example_inputs = benchmark.get_module()
        # Models that must be in train mode while training
        if is_training and (
            not use_eval_mode or model_name in self._config["only_training"]
        ):
            model.train()
        else:
            model.eval()
        gc.collect()
        batch_size = benchmark.batch_size
        # Torchbench has quite different setup for yolov3, so directly passing
        # the right example_inputs
        if model_name == "yolov3":
            example_inputs = (torch.rand(batch_size, 3, 384, 512).to(device),)
        # See https://github.com/pytorch/benchmark/issues/1561
        if model_name == "maml_omniglot":
            batch_size = 5
            assert example_inputs[0].shape[0] == batch_size
        if model_name == "vision_maskrcnn":
            batch_size = 1
        # global current_name, current_device
        # current_device = device
        # current_name = benchmark.name

        if self.args.trace_on_xla:
            # work around for: https://github.com/pytorch/xla/issues/4174
            import torch_xla  # noqa: F401
        self.validate_model(model, example_inputs)
        return device, benchmark.name, model, example_inputs, batch_size

    def iter_model_names(self, args):
        from torchbenchmark import _list_canary_model_paths, _list_model_paths

        models = _list_model_paths()
        models += [
            f
            for f in _list_canary_model_paths()
            if os.path.basename(f) in self._config["canary_models"]
        ]
        models.sort()

        start, end = self.get_benchmark_indices(len(models))
        for index, model_path in enumerate(models):
            if index < start or index >= end:
                continue

            model_name = os.path.basename(model_path)
            if (
                not re.search("|".join(args.filter), model_name, re.I)
                or re.search("|".join(args.exclude), model_name, re.I)
                or model_name in args.exclude_exact
                or model_name in self.skip_models
            ):
                continue

            yield model_name

    def pick_grad(self, name, is_training):
        if is_training or name in ("maml",):
            return torch.enable_grad()
        else:
            return torch.no_grad()

    def get_tolerance_and_cosine_flag(self, is_training, current_device, name):
        tolerance = 1e-4
        cosine = self.args.cosine
        # Increase the tolerance for torch allclose
        if self.args.float16 or self.args.amp:
            if name in self._tolerance["higher_fp16"]:
                return 1e-2, cosine
            return 1e-3, cosine

        if self.args.bfloat16:
            if name in self._tolerance["higher_bf16"]:
                return 1e-2, cosine

        if is_training and current_device == "cuda":
            tolerance = 1e-3
            if name in self._tolerance["cosine"]:
                cosine = True
            elif name in self._tolerance["higher"]:
                tolerance = 1e-3
            elif name in self._tolerance["even_higher"]:
                tolerance = 8 * 1e-2
        return tolerance, cosine

    def compute_loss(self, pred):
        return reduce_to_scalar_loss(pred)

    def forward_pass(self, mod, inputs, collect_outputs=True):
        with self.autocast(**self.autocast_arg):
            return mod(*inputs)

    def forward_and_backward_pass(self, mod, inputs, collect_outputs=True):
        cloned_inputs = clone_inputs(inputs)
        self.optimizer_zero_grad(mod)
        with self.autocast(**self.autocast_arg):
            pred = mod(*cloned_inputs)
            loss = self.compute_loss(pred)
        self.grad_scaler.scale(loss).backward()
        self.optimizer_step()
        if collect_outputs:
            return collect_results(mod, pred, loss, cloned_inputs)
        return None


def torchbench_main():
    original_dir = setup_torchbench_cwd()
    logging.basicConfig(level=logging.WARNING)
    warnings.filterwarnings("ignore")
    main(TorchBenchmarkRunner(), original_dir)


if __name__ == "__main__":
    torchbench_main()
