import functools
import os
import sys
from itertools import count
from typing import List, Optional, Tuple

import sympy
from sympy import Expr

import torch
import torch._ops
from .. import config, ir

from ..codecache import CudaKernelParamCache
from ..utils import cache_on_self, sympy_product
from ..virtualized import V
from .common import IndentedBuffer
from .wrapper import EnterSubgraphLine, ExitSubgraphLine, pexpr, WrapperCodeGen


class CppWrapperCpu(WrapperCodeGen):
    """
    Generates cpp wrapper for running on CPU and calls cpp kernels
    """

    def __init__(self):
        if not hasattr(self, "device"):
            self.device = "cpu"
        super().__init__()
        self.declare = "auto "
        self.declare_maybe_reference = "decltype(auto) "
        self.ending = ";"
        self.open_bracket = "{"
        self.closed_bracket = "}"
        self.comment = "//"
        self.namespace = "at::"
        self.none_str = "nullptr" if config.abi_compatible else "at::Tensor()"
        self.extern_call_ops = set()
        self.size = "sizes()"
        self.stride = "strides()"
        self.cuda = False
        self.supports_intermediate_hooks = False
        self.outputs_need_copy = set()
        self.kernel_callsite_id = count()
        self.int_array_id = count()  # for int array local variable declarations
        self.declared_int_array_vars = set()
        self.tmp_tensor_id = count()  # for tmp tensor local variable declarations
        self.arg_var_id = count()
        self.used_cached_devices = set()
        self.used_cached_dtypes = set()
        self.cached_output_id = count()
        self.scalar_to_tensor_id = count()

        from .cpp import cexpr, CppPrinter

        self.expr_printer = cexpr

        # CppPrinter sometimes calls at::native functions which causes problems in
        # the ABI-compatible mode. Currently we are hitting this problem when codegen
        # Grid computation expressions, but we my need to fix other size computation
        # as well.
        class GridExprCppPrinter(CppPrinter):
            def _print_FloorDiv(self, expr):
                x, div = expr.args
                x = self.paren(self.doprint(x))
                div = self.paren(self.doprint(div))
                assert expr.is_integer, "Expect integers in GridExprPrinter"
                return f"({x}/{div})"

        self.grid_expr_printer = GridExprCppPrinter().doprint

    def generate_kernel_call(
        self,
        name,
        call_args,
        grid=None,
        device_index=None,
        cuda=True,
        triton=True,
        arg_types=None,
        grid_fn: str = "grid",
        triton_meta=None,
    ):
        """
        Generates kernel call code.

        cuda: Defines whether the backend is GPU. Otherwise the backend is CPU.

        triton: Defines whether the GPU backend uses Triton for codegen.
                Otherwise it uses the CUDA language for codegen.
                Only valid when cuda == True.
        """
        if cuda:
            return super().generate_kernel_call(
                name,
                call_args,
                grid,
                device_index,
                cuda,
                triton,
                arg_types,
                grid_fn,
            )
        else:
            if config.abi_compatible:
                assert arg_types is not None and len(call_args) == len(
                    arg_types
                ), "Mismatch call_args and arg_types in generate_kernel_call"
                new_args = []
                for idx, arg in enumerate(call_args):
                    if "*" in arg_types[idx]:
                        var_name = f"var_{next(self.arg_var_id)}"
                        self.writeline(
                            f"auto* {var_name} = get_data_ptr_wrapper({arg});"
                        )
                        new_args.append(f"({arg_types[idx]})({var_name})")
                    else:
                        # arg is a scalar
                        new_args.append(arg)
                self.writeline(self.wrap_kernel_call(name, new_args))
            else:
                self.writeline(self.wrap_kernel_call(name, call_args))

    def write_constant(self, name, hashed):
        # include a hash so our code cache gives different constants different files
        self.header.writeline(f"// {name} {hashed}")

    def write_header(self):
        if V.graph.is_const_graph:
            # We do not write header for constant graph, it will be written by main module.
            return

        if V.graph.aot_mode:
            for header_cpp_file in ("interface.cpp", "implementation.cpp"):
                with open(
                    os.path.join(
                        os.path.dirname(__file__), "aoti_runtime", header_cpp_file
                    )
                ) as f:
                    self.header.splice(f.read())
        else:
            self.header.splice(
                """
                import torch
                from torch._inductor.codecache import CppWrapperCodeCache

                cpp_wrapper_src = (
                '''
                """
            )

        if config.abi_compatible:
            if config.c_shim_version == "1":
                self.header.splice("#include <torch/csrc/inductor/aoti_torch/c/shim.h>")
            else:
                self.header.splice(
                    f"#include <torch/csrc/inductor/aoti_torch/generated/c_shim_{self.device}.h>"
                )
            self.header.splice(
                """
                #include <torch/csrc/inductor/aoti_runtime/arrayref_tensor.h>
                #include <torch/csrc/inductor/aoti_runtime/thread_local.h>
                #include <torch/csrc/inductor/aoti_runtime/scalar_to_tensor.h>
                """
            )
            if V.graph.aot_mode:
                self.header.splice(
                    """
                    #include <torch/csrc/inductor/aoti_runtime/model.h>
                    """
                )
        else:
            self.header.splice(
                """
                #include <ATen/ATen.h>
                #include <ATen/core/dispatch/Dispatcher.h>
                #include <ATen/native/BinaryOps.h>
                #include <torch/csrc/inductor/aoti_runtime/utils.h>
                #include <torch/csrc/inductor/aoti_torch/tensor_converter.h>
                #include <torch/csrc/inductor/inductor_ops.h>
                #include <torch/types.h>
                #include <ATen/ops/bernoulli_native.h>

                #define reinterpret_tensor torch::inductor::_reinterpret_tensor
                #define alloc_from_pool torch::inductor::_alloc_from_pool
                """
            )

        self.header.splice("#include <c10/util/generic_math.h>")

        if not V.graph.aot_mode:
            self.header.splice(
                """
                #include <pybind11/pybind11.h>

                using namespace torch::aot_inductor;
                """
            )

        from .memory_planning import ALIGN_BYTES

        # Round up to the nearest multiple of ALIGN_BYTES
        # ALIGN_BYTES must be a power of 2
        self.header.splice(
            f"""
            [[maybe_unused]] static int64_t align(int64_t nbytes) {{
              return (nbytes + {ALIGN_BYTES} - 1) & -{ALIGN_BYTES};
            }}
            """
        )

    def mark_output_type(self):
        # mark output type to unwrap tensor back to python scalar
        from ..ir import ShapeAsConstantBuffer

        output_is_tensor = dict()
        for idx, x in enumerate(V.graph.graph_outputs):
            if isinstance(x, ShapeAsConstantBuffer):
                output_is_tensor[idx] = False
            else:
                output_is_tensor[idx] = True

        self.output_is_tensor = output_is_tensor

    def write_prefix(self):
        if V.graph.is_const_graph:
            # We do not write prefix for constant graph, it will be written by main module.
            return

        if V.graph.aot_mode:
            self.prefix.writeline("namespace torch {")
            self.prefix.writeline("namespace aot_inductor {")

    def write_input_output_info(
        self,
        info_kind: str,
        idx: int,
        name: str,
    ):
        self.prefix.writeline(f"""{info_kind}[{idx}].name = "{name}";""")

    @staticmethod
    def get_input_cpp_type(input):
        assert config.use_minimal_arrayref_interface
        from .cpp import DTYPE_TO_CPP

        if isinstance(input, sympy.Expr):
            from ..graph import may_get_constant_buffer_dtype

            dtype = may_get_constant_buffer_dtype(input)
            assert dtype is not None, f"Failed to get the dtype of sympy.Expr: {input}"
            return DTYPE_TO_CPP[dtype]
        return f"ArrayRefTensor<{DTYPE_TO_CPP[input.get_dtype()]}>"

    def write_wrapper_decl(self):
        inputs_len = len(V.graph.graph_inputs.keys())
        if V.graph.aot_mode:
            if config.use_minimal_arrayref_interface and not V.graph.is_const_graph:
                from .cpp import DTYPE_TO_CPP

                input_cpp_types = ", ".join(
                    f"{CppWrapperCpu.get_input_cpp_type(x)}"
                    for x in V.graph.graph_inputs.values()
                )

                output_arrayref_types = ", ".join(
                    f"ArrayRefTensor<{DTYPE_TO_CPP[x.get_dtype()]}>"
                    for x in V.graph.graph_outputs
                )

                self.prefix.splice(
                    f"""
                    using AOTInductorModelInputs = std::tuple<{input_cpp_types}>;
                    using AOTInductorModelOutputs = std::tuple<{output_arrayref_types}>;
                    """
                )

            if V.graph.const_module:
                self.header.splice(V.graph.const_module.wrapper_code.header)
                self.prefix.splice(V.graph.const_code)

            if V.graph.is_const_graph:
                self.prefix.splice(
                    """
                    void AOTInductorModel::_const_run_impl(
                        std::vector<AtenTensorHandle>& output_handles,
                        DeviceStreamType stream,
                        AOTIProxyExecutorHandle proxy_executor
                    ) {
                    """
                )
            else:
                if not config.aot_inductor.use_runtime_constant_folding:
                    # If we do not split the constant graph, we'll just create
                    # an empty implementation when wrapping the main module.
                    self.prefix.splice(
                        """
                        void AOTInductorModel::_const_run_impl(
                            std::vector<AtenTensorHandle>& output_handles,
                            DeviceStreamType stream,
                            AOTIProxyExecutorHandle proxy_executor
                        ) {}

                        """
                    )

                run_impl_proto = """
                    void AOTInductorModel::run_impl(
                        AtenTensorHandle*
                            input_handles, // array of input AtenTensorHandle; handles
                                            // are stolen; the array itself is borrowed
                        AtenTensorHandle*
                            output_handles, // array for writing output AtenTensorHandle; handles
                                            // will be stolen by the caller; the array itself is
                                            // borrowed
                        DeviceStreamType stream,
                        AOTIProxyExecutorHandle proxy_executor
                    ) {
                    """
                if config.use_minimal_arrayref_interface:
                    self.prefix.splice(
                        """
                        template <>
                        AOTInductorModelOutputs AOTInductorModel::run_impl_minimal_arrayref_interface<
                          AOTInductorModelInputs, AOTInductorModelOutputs>(
                            const AOTInductorModelInputs& inputs,
                            DeviceStreamType stream,
                            AOTIProxyExecutorHandle proxy_executor
                        ) {
                        """
                    )
                    self.suffix.splice(run_impl_proto)
                    self.suffix.splice(
                        """
                            AOTInductorModelInputs inputs;
                            convert_handles_to_inputs(input_handles, inputs);
                            auto outputs = run_impl_minimal_arrayref_interface<AOTInductorModelInputs, AOTInductorModelOutputs>(
                                inputs, stream, proxy_executor);
                            // NOTE: outputs is full of ArrayRef to thread_local storage. If in the future we need this
                            // interface to perform well for a DSO using the minimal arrayref interface, all we need
                            // to do is provide ThreadLocalCachedTensor for each one!
                            convert_outputs_to_handles(outputs, output_handles);
                        }
                    """
                    )

                    self.suffix.splice(
                        """
                        extern "C" AOTIRuntimeError AOTInductorModelRunMinimalArrayrefInterface(
                            AOTInductorModelHandle model_handle,
                            const AOTInductorModelInputs& inputs,
                            AOTInductorModelOutputs& outputs) {
                          auto model = reinterpret_cast<torch::aot_inductor::AOTInductorModel*>(model_handle);
                          CONVERT_EXCEPTION_TO_ERROR_CODE({
                              outputs = model->run_impl_minimal_arrayref_interface<AOTInductorModelInputs, AOTInductorModelOutputs>(
                                  inputs,
                                  (torch::aot_inductor::DeviceStreamType)nullptr,
                                  nullptr);
                          })
                        }
                    """
                    )
                else:
                    self.prefix.splice(run_impl_proto)
        else:
            self.prefix.splice(
                """
                void inductor_entry_impl(
                    AtenTensorHandle*
                        input_handles, // array of input AtenTensorHandle; handles
                                        // are stolen; the array itself is borrowed
                    AtenTensorHandle*
                        output_handles  // array for writing output AtenTensorHandle; handles
                                        // will be stolen by the caller; the array itself is
                                        // borrowed)
                ) {
                """
            )
        with self.prefix.indent():
            # assign inputs and outputs in both cases so the later codegen can be simplified
            if not config.use_minimal_arrayref_interface:
                if not V.graph.is_const_graph:
                    if V.graph.aot_mode:
                        num_args = len(V.graph.graph_inputs)
                    else:
                        # Weights are promoted in the JIT mode
                        num_args = len(V.graph.graph_inputs) + len(V.graph.constants)
                        self.prefix.splice(
                            """
                                pybind11::gil_scoped_release release;
                            """
                        )

                    if config.abi_compatible:
                        self.prefix.splice(
                            f"""
                                auto inputs = steal_from_raw_handles_to_raii_handles(input_handles, {num_args});
                            """
                        )
                    else:
                        # This looks dumb, but can avoid creating two versions of code in the AOTInductor runtime.
                        self.prefix.splice(
                            f"""
                                auto inputs = alloc_tensors_by_stealing_from_handles(input_handles, {num_args});
                            """
                        )

            if inputs_len != 0:
                for idx, input_key in enumerate(V.graph.graph_inputs.keys()):
                    if config.use_minimal_arrayref_interface:
                        self.prefix.writeline(
                            f"auto {input_key} = std::get<{idx}>(inputs);"
                        )
                        continue
                    # unwrap input tensor back to scalar
                    if isinstance(V.graph.graph_inputs[input_key], sympy.Expr):
                        from ..graph import may_get_constant_buffer_dtype
                        from .cpp import DTYPE_TO_CPP

                        dtype = may_get_constant_buffer_dtype(
                            V.graph.graph_inputs[input_key]
                        )
                        assert (
                            dtype is not None
                        ), "Fails to get the dtype of the sympy.Expr"
                        cpp_dtype = DTYPE_TO_CPP[dtype]
                        if config.abi_compatible:
                            self.prefix.writeline(f"{cpp_dtype} {input_key};")
                            dtype_str = str(dtype).split(".")[-1]
                            self.prefix.writeline(
                                f"aoti_torch_item_{dtype_str}(inputs[{idx}], &{input_key});"
                            )
                        else:
                            self.prefix.writeline(
                                f"{cpp_dtype} {input_key} = inputs[{idx}].item<{cpp_dtype}>();"
                            )
                    else:
                        self.prefix.writeline(
                            f"auto {input_key} = std::move(inputs[{idx}]);"
                        )

            assert all(
                isinstance(v, torch.Tensor) for v in list(V.graph.constants.values())
            ), "Expect all constants to be Tensor"
            for idx, constants_key in enumerate(V.graph.constants.keys()):
                if V.graph.aot_mode:
                    # Weights are stored in constants_ and owned by RAIIAtenTensorHandle there.
                    # Don't call std::move here because it will cause constants_ to lose the ownership.
                    if config.abi_compatible:
                        self.prefix.writeline(
                            f"""auto {constants_key} = constants_->at({idx});"""
                        )
                    else:
                        self.prefix.writeline(
                            f"auto {constants_key} = *tensor_handle_to_tensor_pointer("
                            + f"""constants_->at({idx}));"""
                        )
                else:
                    # Append constants as inputs to the graph
                    constants_idx = inputs_len + idx
                    self.prefix.writeline(
                        f"auto {constants_key} = inputs[{constants_idx}];"
                    )

            self.codegen_inputs(self.prefix, V.graph.graph_inputs)

            if V.graph.aot_mode:
                if not V.graph.is_const_graph:
                    if config.use_minimal_arrayref_interface:
                        # TODO: input shape checking for regular tensor interface as well?
                        self.codegen_input_numel_asserts()
                    else:
                        self.prefix.writeline("inputs.clear();")
                self.prefix.writeline(
                    "auto& kernels = static_cast<AOTInductorModelKernels&>(*this->kernels_.get());"
                )

    def codegen_input_numel_asserts(self):
        for name, buf in V.graph.graph_inputs.items():
            if isinstance(buf, sympy.Expr):
                continue

            # comparing strides for 0 size tensor is tricky. Ignore them for now.
            if sympy_product(buf.get_size()) == 0:
                continue
            numel = buf.get_numel()
            self.prefix.writeline(f"assert_numel({name}, {numel});")

    def codegen_input_size_var_decl(self, code: IndentedBuffer, name):
        if config.abi_compatible:
            code.writeline(f"int64_t* {name}_size;")
            code.writeline(
                f"AOTI_TORCH_ERROR_CODE_CHECK(aoti_torch_get_sizes({name}, &{name}_size));"
            )
        else:
            super().codegen_input_size_var_decl(code, name)

    def codegen_input_stride_var_decl(self, code: IndentedBuffer, name):
        if config.abi_compatible:
            code.writeline(f"int64_t* {name}_stride;")
            code.writeline(
                f"AOTI_TORCH_ERROR_CODE_CHECK(aoti_torch_get_strides({name}, &{name}_stride));"
            )
        else:
            super().codegen_input_stride_var_decl(code, name)

    def codegen_model_kernels(self):
        self.prefix.writeline("namespace {")
        self.prefix.writeline(
            "class AOTInductorModelKernels : public AOTInductorModelKernelsBase {"
        )
        self.prefix.writeline("  public:")
        declare_kernel = set(self.src_to_kernel.values())
        declare_kernel.update(
            entry[0] for entry in self.user_defined_kernel_cache.values()
        )
        if V.graph.const_module:
            declare_kernel.update(
                V.graph.const_module.wrapper_code.src_to_kernel.values()
            )
        for kernel in declare_kernel:
            self.prefix.writeline(f"    CUfunction {kernel}{{nullptr}};")
        self.prefix.writeline("};")
        self.prefix.writeline("}  // namespace")

    def codegen_model_constructor(self):
        """
        // Generated code example
        AOTInductorModel::AOTInductorModel()
            : AOTInductorModelBase(4, 1) {
        inputs_info_[0].name = "input0";
        inputs_info_[0].dtype = "torch.float16";
        ...
        constants_info_[0].name = "L__self___weight";
        constants_info_[0].dtype = at::kFloat;
        constants_info_[0].offset = 0;
        constants_info_[0].data_size = 8192;
        constants_info_[0].shape = {64, 32};
        constants_info_[0].stride = {32, 1};
        ...
        outputs_info_[0].name = "output0";
        outputs_info_[0].dtype = "torch.float16";
        }
        """

        num_inputs = len(V.graph.graph_inputs)
        num_outputs = len(V.graph.graph_outputs)
        num_constants = len(V.graph.constants)
        self.prefix.splice(
            f"""
            AOTInductorModel::AOTInductorModel(std::shared_ptr<ConstantMap> constants_map,
                                               std::shared_ptr<std::vector<ConstantHandle>> constants_array,
                                               const std::string& device_str,
                                               std::optional<std::string> cubin_dir)
                : AOTInductorModelBase({num_inputs}, {num_outputs}, {num_constants}, device_str, cubin_dir) {{
            """
        )

        with self.prefix.indent():
            for idx, (name, inp) in enumerate(V.graph.graph_inputs.items()):
                assert not isinstance(
                    inp, sympy.Expr
                ), f"input {name=} cannot be symbolic"
                self.write_input_output_info("inputs_info_", idx, name)

            for idx, (name, tensor) in enumerate(V.graph.constants.items()):
                assert isinstance(tensor, torch.Tensor)
                self.prefix.writeline(f"""constants_info_[{idx}].name = "{name}";""")
                self.prefix.writeline(
                    f"constants_info_[{idx}].dtype = static_cast<int32_t>({self.codegen_dtype(tensor.dtype)});"
                )
                self.prefix.writeline(
                    f"constants_info_[{idx}].offset = {tensor.storage_offset()};"
                )
                self.prefix.writeline(
                    f"constants_info_[{idx}].data_size = {tensor.untyped_storage().nbytes()};"
                )
                from_folded = "true" if name in V.graph.folded_constants else "false"
                self.prefix.writeline(
                    f"constants_info_[{idx}].from_folded = {from_folded};"
                )

                size_str = ", ".join([str(s) for s in tensor.size()])
                self.prefix.writeline(f"constants_info_[{idx}].shape = {{{size_str}}};")

                stride_str = ", ".join([str(s) for s in tensor.stride()])
                self.prefix.writeline(
                    f"constants_info_[{idx}].stride = {{{stride_str}}};"
                )
                if name in V.graph.dynamo_flat_name_to_original_fqn:
                    original_fqn = V.graph.dynamo_flat_name_to_original_fqn.get(
                        name, name
                    )
                elif name in V.graph.allocated_constant_name:
                    original_fqn = V.graph.allocated_constant_name[name]
                else:
                    raise AssertionError("original_fqn must be set for constant")
                self.prefix.writeline(
                    f"""constants_info_[{idx}].original_fqn = "{original_fqn}";"""
                )
            self.prefix.writeline("update_constants_map(std::move(constants_map));")
            self.prefix.writeline("update_constants_array(std::move(constants_array));")

            def escape_string(x):
                return (
                    x.replace("\\", "\\\\")
                    .replace('"', '\\"')
                    .replace("\n", "\\n")
                    .replace("\t", "\\t")
                )

            self.prefix.writeline(
                f'in_spec_ = "{escape_string(config.aot_inductor.serialized_in_spec)}";'
            )
            self.prefix.writeline(
                f'out_spec_ = "{escape_string(config.aot_inductor.serialized_out_spec)}";'
            )

            for idx, output in enumerate(V.graph.graph_outputs):
                assert not isinstance(
                    output, sympy.Expr
                ), f"output {name=} cannot be symbolic"
                name = f"output{idx}"
                self.write_input_output_info("outputs_info_", idx, name)

            self.prefix.writeline(
                "this->kernels_ = std::make_unique<AOTInductorModelKernels>();"
            )

        self.prefix.writeline("}")

    def codegen_const_run_driver(self):
        """
        // Generated code example
        std::unordered_map<std::string, AtenTensorHandle> AOTInductorModel::const_run_impl(
            DeviceStreamType stream,
            AOTIProxyExecutorHandle proxy_executor,
            bool initialization
        ) {
            std::unordered_map<std::string, AtenTensorHandle> folded_constants_map;
            std::vector<AtenTensorHandle> output_handles;
            // build up output_handles over here.
            _const_run_impl(output_handles, stream, proxy_executor);
            // build up folded_constants_map
            return folded_constants_map;
        }
        """

        self.prefix.splice(
            """
            std::unordered_map<std::string, AtenTensorHandle> AOTInductorModel::const_run_impl(
                DeviceStreamType stream,
                AOTIProxyExecutorHandle proxy_executor,
                bool initialization
            ) {
            """
        )
        if not config.aot_inductor.use_runtime_constant_folding:
            self.prefix.splice(
                """
                    if (!initialization) {
                        std::cerr << "[WARNING] Calling constant_folding in model, but compiled with config: "
                                  << "aot_inductor.use_runtime_constant_folding=False\\n";
                    }
                    return {};
                }
                """
            )
            return

        with self.prefix.indent():
            # This is a mapping to the index of constant folding graph's output
            const_index_mapping: List[Optional[Tuple[int, str]]] = [None] * len(
                V.graph.const_output_index
            )
            for idx, (name, _) in enumerate(V.graph.constants.items()):
                if name in V.graph.const_output_index:
                    const_index_mapping[V.graph.const_output_index[name]] = (idx, name)  # type: ignore[call-overload]
            assert (
                None not in const_index_mapping
            ), "Not all constant gets mapped for constant folding graph."

            self.prefix.writeline(
                f"""
                std::unordered_map<std::string, AtenTensorHandle> folded_constants_map;
                folded_constants_map.reserve({len(const_index_mapping)});
                std::vector<AtenTensorHandle> output_handles({len(const_index_mapping)});
                """
            )

            self.prefix.splice(
                """
                // The below assignment of output_handles to constants is not used directly.
                // It's only used to memo the correspondence of handle and constants.
                """
            )

            for output_idx, (const_idx, _) in enumerate(const_index_mapping):  # type: ignore[misc]
                self.prefix.writeline(
                    f"output_handles[{output_idx}] = constants_->at({const_idx});"
                )

            self.prefix.writeline(
                "_const_run_impl(output_handles, stream, proxy_executor);"
            )

            for output_idx, (_, const_name) in enumerate(const_index_mapping):  # type: ignore[misc]
                self.prefix.writeline(
                    f'folded_constants_map["{const_name}"] = output_handles[{output_idx}];'
                )
            self.prefix.writeline("return folded_constants_map;")

        self.prefix.writeline("}")

    def generate(self, is_inference):
        if V.graph.aot_mode and not V.graph.is_const_graph:
            self.codegen_model_kernels()
            self.codegen_model_constructor()
            self.codegen_const_run_driver()
        self.write_wrapper_decl()
        return super().generate(is_inference)

    def finalize_prefix(self):
        cached_dtypes_buffer = IndentedBuffer()
        if config.abi_compatible:
            for dtype in self.used_cached_dtypes:
                cached_dtypes_buffer.writeline(f"CACHE_TORCH_DTYPE({dtype});")
            for device in self.used_cached_devices:
                cached_dtypes_buffer.writeline(f"CACHE_TORCH_DEVICE({device});")
        cached_dtypes_buffer.splice(self.prefix)
        self.prefix = cached_dtypes_buffer

    def define_kernel(
        self, name: str, kernel: str, metadata: Optional[str] = None, cuda=False
    ):
        self.header.splice(f"\n{kernel}\n")

    def codegen_scalar_to_tensor(self, output: str):
        name = f"scalar_to_tensor_{next(self.scalar_to_tensor_id)}"
        self.wrapper_call.writeline(
            f"RAIIAtenTensorHandle {name} = scalar_to_tensor_handle({output});"
        )
        return name

    @cache_on_self
    def get_output_refs(self):
        return [
            f"torch::tensor({x.codegen_reference(self.wrapper_call)})"
            if isinstance(x, ir.ShapeAsConstantBuffer) and not config.abi_compatible
            else x.codegen_reference(self.wrapper_call)
            for x in V.graph.graph_outputs
        ]

    def generate_return(self, output_refs):
        cst_names = V.graph.constants.keys()
        arr_iface = (
            not V.graph.is_const_graph and config.use_minimal_arrayref_interface
        )  # For brevity.

        def use_thread_local_cached_output_tensor(idx, output):
            cached_output_name = f"cached_output_{next(self.cached_output_id)}"
            cache_type = "Array" if arr_iface else "Tensor"
            self.wrapper_call.writeline(
                f"thread_local ThreadLocalCachedOutput{cache_type}<std::decay_t<decltype({output})>> "
                f"{cached_output_name}({output});"
            )
            if arr_iface:
                self.wrapper_call.writeline(
                    f"{cached_output_name}.copy_data_from({output});"
                )
                output_entry = f"std::get<{idx}>(output_arrayref_tensors)"
                element_type = f"std::decay_t<decltype({output_entry}.data()[0])>"
                self.wrapper_call.writeline(
                    f"{output_entry} = {cached_output_name}.arrayref_tensor<{element_type}>();"
                )
            else:
                self.wrapper_call.writeline(
                    f"{cached_output_name}.copy_data_from({output});"
                )
                self.wrapper_call.writeline(
                    f"AOTI_TORCH_ERROR_CODE_CHECK(aoti_torch_new_uninitialized_tensor(&output_handles[{idx}]));"
                )
                self.wrapper_call.writeline(
                    f"AOTI_TORCH_ERROR_CODE_CHECK(aoti_torch_assign_tensors({cached_output_name}.tensor(), "
                    f"output_handles[{idx}]));"
                )

        if arr_iface:
            self.wrapper_call.writeline(
                "AOTInductorModelOutputs output_arrayref_tensors;"
            )
        for idx, output in enumerate(output_refs):
            if config.abi_compatible:
                output_buffer = V.graph.graph_outputs[idx]
                if isinstance(output_buffer, ir.ShapeAsConstantBuffer):
                    # Need to wrap scalar into tensor as the main function returns a vector of tensors
                    output_tensor = self.codegen_scalar_to_tensor(output)
                    self.wrapper_call.writeline(
                        f"output_handles[{idx}] = {output_tensor}.release();"
                    )
                    continue

                output_is_tensor_handle_expr = (
                    f"std::is_same_v<std::decay_t<decltype({output})>,"
                    "RAIIAtenTensorHandle> || "
                    f"std::is_same_v<std::decay_t<decltype({output})>,"
                    "AtenTensorHandle> || "
                    f"std::is_same_v<std::decay_t<decltype({output})>,"
                    "ConstantHandle>"
                )
                self.wrapper_call.writeline(
                    f"if constexpr ({output_is_tensor_handle_expr}) {{"
                )
                with self.wrapper_call.indent():
                    if arr_iface:
                        cached_output_name = (
                            f"cached_output_{next(self.cached_output_id)}"
                        )
                        output_value_type = f"std::decay_t<decltype(std::get<{idx}>(output_arrayref_tensors).data()[0])>"
                        self.wrapper_call.writeline(
                            f"thread_local RAIIAtenTensorHandle {cached_output_name};"
                        )
                        if output in cst_names:
                            # NOTE(return_constant): In some rare cases where we return
                            # a constant, we have to return a copy of this constant,
                            # because (1) constants are not owned by the Model instance
                            # (2) constants remain the same cross inference runs,
                            # assuming they are not updated at runtime Basically, we
                            # cannot release or transfer the ownership of any original
                            # constant to the user.
                            self.wrapper_call.writeline(
                                f"AtenTensorHandle {cached_output_name}_tmp;"
                            )
                            self.wrapper_call.writeline(
                                f"aoti_torch_clone({output}, &{cached_output_name}_tmp);"
                            )
                            self.wrapper_call.writeline(
                                f"{cached_output_name} = {cached_output_name}_tmp;"
                            )
                        else:
                            self.wrapper_call.writeline(
                                f"{cached_output_name} = {output}.release();"
                            )
                        self.wrapper_call.writeline(
                            f"convert_handle_to_arrayref_tensor({cached_output_name}, "
                            f"std::get<{idx}>(output_arrayref_tensors));"
                        )
                    else:
                        if output in cst_names:
                            # See NOTE(return_constant) above.
                            self.wrapper_call.writeline(
                                f"aoti_torch_clone({output}, &output_handles[{idx}]);"
                            )
                        else:
                            self.wrapper_call.writeline(
                                f"output_handles[{idx}] = {output}.release();"
                            )
                self.wrapper_call.writeline("} else {")
                with self.wrapper_call.indent():
                    use_thread_local_cached_output_tensor(idx, output)
                self.wrapper_call.writeline("}")

            else:
                assert (
                    not arr_iface
                ), "minimal ArrayRef interface is only supported in ABI-compatible mode"
                if output in cst_names:
                    output_expr = f"{output}.clone()"
                    # See NOTE(return_constant) above.
                else:
                    output_expr = output
                self.wrapper_call.writeline(
                    f"output_handles[{idx}] = reinterpret_cast<AtenTensorHandle>("
                    + f"new at::Tensor({output_expr}));"
                )
        if arr_iface:
            self.wrapper_call.writeline("return output_arrayref_tensors;")

    def generate_before_suffix(self, result):
        if not V.graph.is_const_graph:
            if V.graph.aot_mode:
                result.writeline("} // AOTInductorModel::run_impl")
            else:
                result.writeline("} // inductor_entry_impl")

    def generate_end(self, result):
        if V.graph.aot_mode:
            if V.graph.is_const_graph:
                result.writeline("} // AOTInductorModel::_const_run_impl")
            else:
                result.writeline("} // namespace aot_inductor")
                result.writeline("} // namespace torch")
            return

        result.writeline("'''\n)")
        result.splice(
            f"""
            inductor_entry = CppWrapperCodeCache.load_pybinding(
                ["std::vector<at::Tensor>"], cpp_wrapper_src, {self.cuda}, {len(V.graph.graph_outputs)})
            """
        )

        # unwrap output tensor back to python scalar
        if all(x for x in self.output_is_tensor.values()):
            # If no ShapeAsConstantBuffer in the output, directly return the output as tensors
            return_str = "return f(args_tensor)"
        else:
            outputs = [
                f"outputs[{i}]" if self.output_is_tensor[i] else f"outputs[{i}].item()"
                for i in range(len(V.graph.graph_outputs))
            ]
            outputs_str = f"[{', '.join(outputs)}]"
            return_str = f"""
                    outputs = f(args_tensor)
                    return {outputs_str}
            """

        args_str = "args_tensor = [arg if isinstance(arg, torch.Tensor) else torch.tensor(arg) for arg in args]"
        if V.graph.constants:
            # Append constants to the input args for cpp wrapper.
            # Python wrapper directly gets the value inside the wrapper call
            # as a global variable passed when calling exec(code, mod.__dict__, mod.__dict__).
            # For cpp wrapper, we need to pass this python value to the inductor_entry_impl function explicitly.
            assert all(
                isinstance(v, torch.Tensor) for v in list(V.graph.constants.values())
            ), "Expect all constants to be Tensor"
            constants_str = f"[{', '.join(V.graph.constants.keys())}]"
            args_str += f"""
                    constants_tensor = {constants_str}
                    args_tensor.extend(constants_tensor)
            """

        # Wrap the func to support setting result._boxed_call = True
        result.splice(
            f"""
            def _wrap_func(f):
                def g(args):
                    {args_str}
                    {return_str}
                return g
            call = _wrap_func(inductor_entry)
            """
        )

    def generate_c_shim_extern_kernel_call(self, kernel, args):
        # In the abi_compatible mode, we call fallback aten ops through a C shim layer
        self.allow_stack_allocation = False
        kernel_tokens = kernel.split("::")
        kernel_suffix = kernel_tokens[-1]
        if kernel_suffix == "call":
            kernel_suffix = kernel_tokens[-2]
        if config.c_shim_version == "1":
            shim_fn = f"aoti_torch_{kernel_suffix}"
        else:
            shim_fn = f"aoti_torch_{self.device}_{kernel_suffix}"

        # HACK: val_to_arg_str jams multiple arguments together using a comma. If that
        # ever breaks, it needs to be reworked to be able to return multiple arguments,
        # and the split-on-comma code here needs to be removed.
        wrapped_args = []
        for x in args:
            pieces = x.split(", ")
            for piece in pieces:
                # We only really *need* convert_arrayref_tensor_to_tensor for
                # ArrayRefTensors. The code flowing into here uses `0` for nullptr,
                # which convert_arrayref_tensor_to_tensor would blindly coerce to int,
                # so just avoid wrapping integers.
                if not piece.isdigit():
                    piece = f"convert_arrayref_tensor_to_tensor({piece})"
                wrapped_args.append(piece)
        self.writeline(
            f"AOTI_TORCH_ERROR_CODE_CHECK({shim_fn}({', '.join(wrapped_args)}));"
        )

    def generate_c_shim_extern_kernel_alloc(self, extern_kernel, args):
        # registered output buffer name
        name = extern_kernel.name
        output_handle_name = f"{name}_handle"
        self.writeline(f"AtenTensorHandle {output_handle_name};")
        output_arg = f"&{output_handle_name}"
        self.generate_c_shim_extern_kernel_call(
            extern_kernel.get_kernel_name(), args + [output_arg]
        )
        self.writeline(f"RAIIAtenTensorHandle {name}({output_handle_name});")

    def generate_extern_kernel_alloc(self, extern_kernel, args):
        if config.abi_compatible:
            self.generate_c_shim_extern_kernel_alloc(extern_kernel, args)
        else:
            super().generate_extern_kernel_alloc(extern_kernel, args)

    def generate_c_shim_fallback_kernel(self, fallback_kernel, args):
        output_args = []
        output_raii_handles = []
        output_name_base = fallback_kernel.get_name()
        for idx, output in enumerate(fallback_kernel.outputs):
            if isinstance(output, ir.MultiOutput):
                name = f"{output.get_name()}"
                output_handle_name = f"{name}_handle"
                if output.indices:
                    assert (
                        output.indices[0][1] == idx
                    ), f"expected {output.indices[0][1]=} == {idx=} for {output_name_base=}"
                self.writeline(f"AtenTensorHandle {output_handle_name};")
                output_args.append(f"&{output_handle_name}")
                output_raii_handles.append(
                    f"RAIIAtenTensorHandle {name}({output_handle_name});"
                )
            elif isinstance(output, int):
                output_name = f"{output_name_base}_{idx}"
                self.writeline(f"int64_t {output_name} = {output};")
                output_args.append(f"&{output_name}")
            elif output is None:
                output_args.append("nullptr")
            else:
                raise NotImplementedError("unsupported type of {output=}")
        args = args + output_args
        assert (
            fallback_kernel.abi_compatible_kernel is not None
        ), f"abi_compatible_kernel is None for {fallback_kernel.python_kernel_name=}"
        self.generate_c_shim_extern_kernel_call(
            fallback_kernel.abi_compatible_kernel, args
        )
        for raii_handle in output_raii_handles:
            self.writeline(raii_handle)

    def generate_fallback_kernel(self, fallback_kernel, args):
        if config.abi_compatible:
            self.generate_c_shim_fallback_kernel(fallback_kernel, args)
        else:
            super().generate_fallback_kernel(fallback_kernel, args)

    def generate_extern_kernel_out(self, output_view, codegen_reference, args, kernel):
        if output_view:
            output_as_strided = f"{output_view.codegen_reference()}"
            output_name = f"{output_view.get_name()}_as_strided"
            self.writeline(f"auto {output_name} = {output_as_strided};")

            args.insert(0, output_name)
        else:
            args.insert(0, f"{codegen_reference}")

        if config.abi_compatible:
            self.generate_c_shim_extern_kernel_call(kernel, args)
        else:
            self.writeline(self.wrap_kernel_call(kernel, args))

    def generate_user_defined_triton_kernel(
        self, kernel_name, grid, configs, args, triton_meta
    ):
        assert len(grid) != 0
        if len(grid) == 1:
            grid_decision = grid[0]
        else:
            meta = CudaKernelParamCache.get(kernel_name)
            assert meta is not None
            grid_decision = None
            for i, c in enumerate(configs):
                if all(arg == meta["meta"][key] for key, arg in c.kwargs.items()):
                    grid_decision = grid[i]
                    break
            assert grid_decision is not None

        self.generate_kernel_call(
            kernel_name,
            args,
            grid=grid_decision,
            device_index=V.graph.scheduler.current_device.index,
            cuda=True,
            triton=True,
            triton_meta=triton_meta,
        )

    def generate_scatter_fallback(
        self, output, inputs, kernel, python_kernel_name, src_is_tensor, reduce, kwargs
    ):
        # TODO: support other overload for cpp wrapper and remove the below assertions
        if config.abi_compatible:
            # call the ABI shim function instead of the ATen one
            kernel = kernel.replace("at::", "aoti_torch_")
        line = f"{kernel}({output}, {','.join(map(str, inputs))}"
        if python_kernel_name == "aten.scatter_":
            if src_is_tensor:
                if reduce:
                    line += f", {V.graph.wrapper_code.val_to_arg_str(reduce)}"
            else:
                assert (
                    reduce is None
                ), "Expect reduce to be None for aten.scatter_ with scalar src"
        else:
            line += f", {','.join(kwargs)}"
        line += f"){self.ending}"
        self.writeline(line)

    def generate_index_put_fallback(self, kernel, x, indices, values, accumulate):
        if V.graph.aot_mode and V.graph.cpp_wrapper and config.abi_compatible:
            # See the comment in codegen_reinterpret_view about why having something like
            # RAIIAtenTensorHandle(tmp_tensor_handle_2) in a tmp array can cause the correponding
            # tensor prematurely deallocated, thus this std::vector().data() trick here.
            indices_str = (
                f"std::vector<AtenTensorHandle>{{{', '.join(indices)}}}.data()"
            )
            args = [x, indices_str, str(len(indices)), values, accumulate]
        else:
            indices_str = (
                f"{self.open_bracket}{', '.join(indices)}{self.closed_bracket}"
            )
            args = [x, indices_str, values, accumulate]

        args.insert(0, x)  # set x as the output tensor, this fallback mutates x.
        self.writeline(self.wrap_kernel_call(kernel, args))

    def add_benchmark_harness(self, output):
        if V.graph.aot_mode:
            return
        super().add_benchmark_harness(output)

    def codegen_sizevar(self, x: Expr) -> str:
        return self.expr_printer(V.graph.sizevars.simplify(x))

    def codegen_tuple_access(self, basename: str, name: str, index: str) -> str:
        if config.abi_compatible:
            # in the abi_compatible mode, outputs are returned via arguments
            return name
        else:
            return f"std::get<{index}>({basename})"

    def codegen_shape_tuple(self, shape: Tuple[Expr, ...]) -> str:
        parts = list(map(self.codegen_sizevar, shape))
        if len(parts) == 0:
            return "{}"
        if len(parts) == 1:
            return f"{{{parts[0]}, }}"
        return f"{{{', '.join(parts)}}}"

    def codegen_dynamic_scalar(self, node):
        from .cpp import DTYPE_TO_ATEN, DTYPE_TO_CPP

        (data,) = (t.codegen_reference() for t in node.inputs)
        if config.abi_compatible:
            dtype = node.inputs[0].get_dtype()
            dtype_str = str(dtype).split(".")[-1]
            self.writeline(f"{DTYPE_TO_CPP[dtype]} {node.sym};")
            self.writeline(f"aoti_torch_item_{dtype_str}({data}, &{node.sym});")
            # record in unbacked_symbol_decls so we won't generate a declaration of the symbol again
            self.unbacked_symbol_decls.add(str(node.sym))
        else:
            if node.is_bool:
                self.writeline(f"bool {node.sym} = {data}.item() ? 1 : 0;")
            else:
                convert_type = DTYPE_TO_ATEN[node.inputs[0].get_dtype()].replace(
                    "at::k", "to"
                )
                self.writeline(f"auto {node.sym} = {data}.item().{convert_type}();")

    def can_stack_allocate_buffer(self, buffer):
        return (
            self.allow_stack_allocation
            and buffer.get_device().type == "cpu"
            and self.can_prove_buffer_has_static_shape(buffer)
            and ir.is_contiguous_strides_for_shape(
                buffer.get_stride(), buffer.get_size()
            )
        )

    def make_buffer_free(self, buffer):
        return (
            ""
            if isinstance(buffer.get_layout(), ir.MultiOutputLayout)
            or (V.graph.aot_mode and buffer.get_name() in self.stack_allocated_buffers)
            or (
                config.use_minimal_arrayref_interface
                and V.graph.aot_mode
                and buffer.get_name() in V.graph.graph_inputs
            )
            else f"{buffer.get_name()}.reset();"
        )

    def make_free_by_names(self, names_to_del: List[str]):
        return " ".join(f"{name}.reset();" for name in names_to_del)

    def codegen_exact_buffer_reuse(self, old_name: str, new_name: str, del_line: str):
        if config.abi_compatible:
            return f"auto {new_name} = std::move({old_name});  // reuse"
        else:
            return super().codegen_exact_buffer_reuse(old_name, new_name, del_line)

    def generate_profiler_mark_wrapper_call(self, stack):
        self.wrapper_call.writeline(
            'RECORD_FUNCTION("inductor_wrapper_call", c10::ArrayRef<c10::IValue>());'
        )

    def write_triton_header_once(self):
        pass

    def generate_start_graph(self):
        pass

    def generate_end_graph(self):
        pass

    def generate_inf_and_nan_checker(self, nodes):
        for buf in nodes.get_names():
            # TODO: Add buf name directly into check_inf_and_nan.
            self.writeline(
                f"AOTI_TORCH_ERROR_CODE_CHECK(aoti_check_inf_and_nan({buf}));"
            )

    def codegen_device(self, device):
        if config.abi_compatible:
            self.used_cached_devices.add(device.type)
            return f"cached_torch_device_type_{device.type},{device.index if device.index else 0}"
        else:
            from .cpp import DEVICE_TO_ATEN

            return (
                f"c10::Device({DEVICE_TO_ATEN[device.type]}, {device.index})"
                if device.index is not None
                else f"{DEVICE_TO_ATEN[device.type]}"
            )

    def codegen_dtype(self, dtype):
        if config.abi_compatible:
            dtype_str = str(dtype).split(".")[-1]
            self.used_cached_dtypes.add(dtype_str)
            return f"cached_torch_dtype_{dtype_str}"
        else:
            from .cpp import DTYPE_TO_ATEN

            return DTYPE_TO_ATEN[dtype]

    @functools.lru_cache(None)
    def codegen_int_array_var(
        self,
        int_array: str,
        writer=None,
        known_statically=False,
        graph=None,  # for per-graph caching
    ):
        # Because the memory planning is done in two passes (see the implementation
        # of self.generate), the writeline behavior is different in the two passes.
        # As a result, the emitted int array declarations may appear in a later
        # position of the generated code, so the second pass codegen should not
        # reuse int array declarations generated in the first pass
        if writer is None:
            # The first pass codegen uses `self` as the writer
            writer = self

        var = f"int_array_{next(self.int_array_id)}"
        if var not in self.declared_int_array_vars:
            self.declared_int_array_vars.add(var)
            if known_statically:
                writer.writeline(f"static constexpr int64_t {var}[] = {int_array};")
            else:
                writer.writeline(f"int64_t {var}[] = {int_array};")
        return var

    def make_buffer_allocation(self, buffer):
        return self.make_allocation(
            buffer.get_name(),
            buffer.get_device(),
            buffer.get_dtype(),
            buffer.get_size(),
            buffer.get_stride(),
            buffer if self.can_stack_allocate_buffer(buffer) else None,
        )

    def make_allocation(
        self, name, device, dtype, shape, stride, buffer_if_can_stack_allocate=None
    ):
        orig_stride = stride
        device_str = self.codegen_device(device)
        dtype_code = self.codegen_dtype(dtype)
        size = self.codegen_shape_tuple(shape)
        stride = self.codegen_shape_tuple(orig_stride)
        if config.abi_compatible:
            size_array_var = self.codegen_int_array_var(
                size,
                self.wrapper_call,
                known_statically=self.is_statically_known_list_of_ints(shape),
                graph=self.get_codegened_graph(),
            )
            stride_array_var = self.codegen_int_array_var(
                stride,
                self.wrapper_call,
                known_statically=self.is_statically_known_list_of_ints(orig_stride),
                graph=self.get_codegened_graph(),
            )
            device_type, device_id = device_str.split(",")
            device_idx = "this->device_idx_" if V.graph.aot_mode else device_id
            if buffer_if_can_stack_allocate is not None:
                from .cpp import DTYPE_TO_CPP

                self.stack_allocated_buffers[name] = buffer_if_can_stack_allocate
                cpp_type = DTYPE_TO_CPP[dtype]
                numel = buffer_if_can_stack_allocate.get_numel()
                # Note: we don't zero storage because empty_strided doesn't zero either.
                self.wrapper_call.writeline(f"{cpp_type} {name}_storage[{numel}];")
                args = [
                    f"{name}_storage",
                    size_array_var,
                    stride_array_var,
                    device_type,
                    device_idx,
                ]
                return f"ArrayRefTensor<{cpp_type}> {name}({', '.join(args)});"

            args = [
                str(len(shape)),
                size_array_var,
                stride_array_var,
                dtype_code,
                device_type,
                device_idx,
                f"&{name}_handle",
            ]

            self.wrapper_call.writeline(f"AtenTensorHandle {name}_handle;")
            self.wrapper_call.writeline(
                f"AOTI_TORCH_ERROR_CODE_CHECK(aoti_torch_empty_strided({', '.join(args)}));"
            )

            return f"RAIIAtenTensorHandle {name}({name}_handle);"

        if V.graph.aot_mode and device_str.startswith("c10::Device("):
            tensor_device = f"{device_str.split(',')[0]}, this->device_idx_)"
        else:
            tensor_device = device_str

        if device.type == "cpu":
            return f"at::Tensor {name} = at::detail::empty_strided_cpu({size}, {stride}, {dtype_code});"
        if device.type == "cuda":
            return (
                f"at::Tensor {name} = at::detail::empty_strided_cuda("
                f"{size}, {stride}, {dtype_code}, c10::DeviceType::CUDA);"
            )
        return (
            f"{self.declare}{name} = {self.namespace}empty_strided("
            f"{size}, {stride}, at::TensorOptions({tensor_device}).dtype({dtype_code})){self.ending}"
        )

    def codegen_alloc_from_pool(self, name, offset, dtype, shape, stride) -> str:
        if config.abi_compatible:
            size = self.codegen_shape_tuple(shape)
            stride = self.codegen_shape_tuple(stride)
            tmp_name = f"tmp_tensor_handle_{next(self.tmp_tensor_id)}"
            args = [
                name,
                pexpr(offset),  # bytes not numel
                self.codegen_dtype(dtype),
                str(len(shape)),
                self.codegen_int_array_var(
                    size, self.wrapper_call, graph=self.get_codegened_graph()
                ),
                self.codegen_int_array_var(
                    stride, self.wrapper_call, graph=self.get_codegened_graph()
                ),
                f"&{tmp_name}",
            ]
            self.wrapper_call.writeline(f"AtenTensorHandle {tmp_name};")
            self.wrapper_call.writeline(
                f"AOTI_TORCH_ERROR_CODE_CHECK(aoti_torch__alloc_from_pool({', '.join(args)}));"
            )
            return f"RAIIAtenTensorHandle({tmp_name})"

        return "alloc_from_pool({})".format(
            ", ".join(
                [
                    name,
                    pexpr(offset),  # bytes not numel
                    self.codegen_dtype(dtype),
                    self.codegen_shape_tuple(shape),
                    self.codegen_shape_tuple(stride),
                ]
            )
        )

    def codegen_reinterpret_view(
        self, data, size_list, stride_list, offset, writer
    ) -> str:
        dim = str(len(size_list))
        size = self.codegen_shape_tuple(size_list)
        stride = self.codegen_shape_tuple(stride_list)
        offset = self.codegen_sizevar(offset)

        if config.abi_compatible:
            tmp_name = f"tmp_tensor_handle_{next(self.tmp_tensor_id)}"
            # Because the memory planning is done in two passes (see the implementation
            # of self.generate), the writeline behavior is different in the two passes.
            if writer is None:
                writer = self

            args = [
                f"{data.get_name()}",
                dim,
                self.codegen_int_array_var(
                    size,
                    writer,
                    known_statically=self.is_statically_known_list_of_ints(size_list),
                    graph=self.get_codegened_graph(),
                ),
                self.codegen_int_array_var(
                    stride,
                    writer,
                    known_statically=self.is_statically_known_list_of_ints(stride_list),
                    graph=self.get_codegened_graph(),
                ),
                offset,
            ]

            def gen_reinterpret_call(writer, args):
                writer.writeline(
                    f"auto {tmp_name} = reinterpret_tensor_wrapper({', '.join(args)});"
                )

            if (
                self.can_stack_allocate_buffer(data)
                and self.is_statically_known_list_of_ints(size_list)
                and self.is_statically_known_list_of_ints(stride_list)
                and ir.is_contiguous_strides_for_shape(stride_list, size_list)
            ):
                gen_reinterpret_call(writer, args)
                return tmp_name

            gen_reinterpret_call(writer, args)

            # NB, the return handle here represents a temporary tensor, which will be automatically
            # released.
            # Here's a sample usage in the cpp wrapper code:
            # ```
            # aoti_torch_addmm_out(
            #     buf1,
            #     arg1_1,
            #     RAIIAtenTensorHandle(tmp_tensor_handle_0),
            #     buf0,
            #     1L,
            #     1L));
            # ```
            # RAIIAtenTensorHandle(tmp_tensor_handle_0) will be released after the call to addmm_out.
            # This could be problematic when it's used in a different pattern, for example:
            # ````
            # AtenTensorHandle tensor_args[] = {RAIIAtenTensorHandle(tmp_tensor_handle_2), buf5, buf6};
            # aoti_torch_proxy_executor_call_function(..., tensor_args);
            # ````
            # RAIIAtenTensorHandle(tmp_tensor_handle_2) will be invalid when it's used in the latter
            # kernel call.
            #
            # This is solved by updating the proxy_executor invocation to
            # ```
            # aoti_torch_proxy_executor_call_function(...,
            #     std::vector<AtenTensorHandle>{
            #         RAIIAtenTensorHandle(tmp_tensor_handle_2), buf5, buf6
            #     }.data()
            # );
            # ```
            return f"wrap_with_raii_handle_if_needed({tmp_name})"
        else:
            args = [data.get_name(), size, stride, offset]
            return f"reinterpret_tensor({', '.join(args)})"

    def codegen_device_copy(self, src, dst):
        if config.abi_compatible:
            self.writeline(
                f"AOTI_TORCH_ERROR_CODE_CHECK(aoti_torch_tensor_copy_(expensive_copy_to_tensor_if_needed({src}), {dst}));"
            )
        else:
            self.writeline(f"{dst}.copy_({src});")

    def codegen_multi_output(self, name, value):
        # in the abi_compatible mode, outputs are retrieved by passing
        # output pointers, so we skip its codegen here.
        if not config.abi_compatible:
            super().codegen_multi_output(name, value)

    def codegen_subgraph_prefix(self, subgraph, outer_inputs, outer_outputs):
        for inner_input, outer_input in zip(subgraph.graph.graph_inputs, outer_inputs):
            if config.abi_compatible:
                # in ABI-compatible mode, we copy the underlying at::Tensor of the conditional
                # input (outer_input) into another at::Tensor to be used as a subgraph input
                # (inner_input) in the nested scope. we can't std::move here, as the codegened
                # outer input may be an expression / rvalue (e.g., reinterpret_view(x)), so we
                # can't necessarily std::move it back to the origin (x).
                self.writeline(f"AtenTensorHandle {inner_input}_handle;")
                self.writeline(
                    f"AOTI_TORCH_ERROR_CODE_CHECK(aoti_torch_assign_tensors_out({outer_input}, &{inner_input}_handle));"
                )
                self.writeline(
                    f"RAIIAtenTensorHandle {inner_input}({inner_input}_handle);"
                )
            else:
                self.writeline(
                    f"{self.declare}{inner_input} = {outer_input}{self.ending}"
                )

    def codegen_subgraph_suffix(self, subgraph, outer_inputs, outer_outputs):
        for inner_output, outer_output in zip(
            subgraph.graph.graph_outputs, outer_outputs
        ):
            src = inner_output.codegen_reference()
            if config.abi_compatible:
                # in ABI-compatible mode, we need to std::move subgraph output (inner_output)
                # to the conditional output (outer_output), as RAIIAtenTensorHandle's copy
                # constructor is deleted.
                src = f"std::move({src})"
            self.writeline(f"{outer_output} = {src}{self.ending}")

    def codegen_conditional(self, conditional):
        name = conditional.get_name()
        outer_inputs = [f"{buf.codegen_reference()}" for buf in conditional.operands]
        if config.abi_compatible:
            outer_outputs = []
            for out in conditional.outputs:
                # in ABI-compatible mode, ir.MultiOutput is not codegened,
                # hence pre-declare output variables directly and separately
                self.writeline(f"RAIIAtenTensorHandle {out.get_name()};")
                outer_outputs.append(out.get_name())
            predicate = f"{conditional.predicate.get_name()}_scalar"
            self.writeline(f"bool {predicate};")
            # in ABI-compatible mode, we need to use the ABI shim function
            # to extract a C++ bool from the unrelying scalar bool Tensor
            self.writeline(
                f"AOTI_TORCH_ERROR_CODE_CHECK(aoti_torch_item_bool({conditional.predicate.codegen_reference()}, &{predicate}));"
            )
        else:
            # in non-ABI-compatible mode, we can codegen the conditional outputs
            # as array of at::Tensor instances, as the ir.MultiOutput is codegened
            outer_outputs = [f"{name}[{i}]" for i in range(len(conditional.outputs))]
            self.writeline(f"at::Tensor {name}[{len(conditional.outputs)}];")
            predicate = f"{conditional.predicate.codegen_reference()}.item<bool>()"

        self.writeline(f"if ({predicate}) {{")
        self.writeline(EnterSubgraphLine(self, conditional.true_subgraph.graph))
        self.codegen_subgraph(conditional.true_subgraph, outer_inputs, outer_outputs)
        self.writeline(ExitSubgraphLine(self))
        self.writeline("} else {")
        self.writeline(EnterSubgraphLine(self, conditional.false_subgraph.graph))
        self.codegen_subgraph(conditional.false_subgraph, outer_inputs, outer_outputs)
        self.writeline(ExitSubgraphLine(self))
        self.writeline("}")

    def generate_extern_kernel_args_decl_if_needed(
        self, op_overload, raw_args, output_args
    ):
        arg_types = [x.real_type for x in op_overload._schema.arguments]
        return_types = [x.type for x in op_overload._schema.returns]

        new_tensor_args = []
        new_int_args = []

        def fill_args(arg, arg_type):
            static_arg_types = (
                torch.FloatType,
                torch.BoolType,
                torch.StringType,
                torch.Type,
                torch.DeviceObjType,
            )
            inductor_tensor_buffers = (
                ir.Buffer,
                ir.ReinterpretView,
            )

            if isinstance(arg_type, torch.TensorType):
                assert isinstance(arg, inductor_tensor_buffers), f"got {type(arg)}"
                new_tensor_args.append(f"{arg.codegen_reference()}")
            elif isinstance(arg_type, torch.IntType):
                # int
                new_int_args.append(str(arg))
            elif isinstance(arg_type, torch.SymIntType):
                # SymInt
                expr = arg.node.expr if isinstance(arg, torch.SymInt) else arg
                new_int_args.append(self.expr_printer(expr))
            elif isinstance(arg_type, torch.NumberType):
                # Scalar of type int
                assert isinstance(arg, (int, float, bool))
                # Only treat int Scalar as dynamic
                if isinstance(arg, int):
                    new_int_args.append(str(arg))
            elif isinstance(arg_type, torch.ListType):
                assert isinstance(arg, (list, tuple))

                # List[Tensor]
                if isinstance(arg_type.getElementType(), torch.TensorType):
                    new_tensor_args.extend([f"{a.codegen_reference()}" for a in arg])
                # List[Optional[Tensor]]
                elif isinstance(
                    arg_type.getElementType(), torch.OptionalType
                ) and isinstance(
                    arg_type.getElementType().getElementType(), torch.TensorType
                ):
                    new_tensor_args.extend(
                        [f"{a.codegen_reference()}" for a in arg if a is not None]
                    )
                # List[int]
                elif isinstance(arg_type.getElementType(), torch.IntType):
                    new_int_args.extend([str(a) for a in arg])
                # List[SymInt]
                elif isinstance(arg_type.getElementType(), torch.SymIntType):
                    expressions = [
                        a.node.expr if isinstance(a, torch.SymInt) else a for a in arg
                    ]
                    new_int_args.extend(
                        [self.expr_printer(expr) for expr in expressions]
                    )
                # List[Scalar]
                elif isinstance(arg_type.getElementType(), torch.NumberType):
                    # Only treat int Scalar as dynamic
                    is_int_type = [isinstance(a, int) for a in arg]
                    if any(is_int_type):
                        assert all(
                            is_int_type
                        ), "AOTInductor only supports int scalars of the same type"
                        new_int_args.extend([str(a) for a in arg])
                else:
                    assert isinstance(
                        arg_type.getElementType(), static_arg_types  # type: ignore[arg-type]
                    ), f"Fall through arguments must be one of static_arg_types, got {type(arg_type)}"
            else:
                assert isinstance(
                    arg_type, static_arg_types  # type: ignore[arg-type]
                ), f"Fall through arguments must be one of static_arg_types, got {type(arg_type)}"

        for arg, arg_type in zip(raw_args, arg_types):
            if arg is not None:
                if isinstance(arg_type, torch.OptionalType):
                    fill_args(arg, arg_type.getElementType())
                else:
                    fill_args(arg, arg_type)

        def fill_output_arg(arg, return_type):
            if isinstance(return_type, torch.TensorType):
                self.writeline(f"AtenTensorHandle {arg}_handle;  // output buffer")
                self.writeline(
                    f"AOTI_TORCH_ERROR_CODE_CHECK(aoti_torch_new_uninitialized_tensor(&{arg}_handle));"
                )
                self.writeline(f"RAIIAtenTensorHandle {arg}({arg}_handle);")
                new_tensor_args.append(f"{arg}")
            elif isinstance(return_type, torch.SymIntType):
                raise NotImplementedError("NYI support for return type: SymInt")
            elif isinstance(return_type, torch.ListType) and isinstance(
                return_type.getElementType(), torch.SymIntType
            ):
                raise NotImplementedError("NYI support for return type: List[SymInt]")
            else:
                raise AssertionError(f"Unsupported return type found: {return_type}")

        # TODO: Only support tensor(s) returns for now, SymInt is not implemented yet
        for return_type in return_types:
            if isinstance(return_type, (torch.TensorType)):
                pass
            elif isinstance(return_type, torch.OptionalType):
                assert isinstance(return_type.getElementType(), torch.TensorType)
            elif isinstance(return_type, torch.ListType):
                assert isinstance(return_type.getElementType(), torch.TensorType)
            else:
                raise NotImplementedError(
                    f"return type {return_type} is not yet supported."
                )

        for output_arg in output_args:
            assert output_arg is not None, "Optional return types are not yet supported"
            if isinstance(output_arg, (list, tuple)):
                for out in output_arg:
                    fill_output_arg(out, torch.TensorType.get())
            else:
                fill_output_arg(output_arg, torch.TensorType.get())

        return new_tensor_args, new_int_args

    def generate_extern_kernel_alloc_and_find_schema_if_needed(
        self,
        name,
        kernel,
        codegen_args,
        cpp_op_schema,
        cpp_kernel_key,
        cpp_kernel_overload_name="",
        op_overload=None,
        raw_args=None,
        outputs=None,
    ):
        if config.is_fbcode():
            assert op_overload is not None
            assert raw_args is not None
            assert outputs is not None

            return self.generate_extern_kernel_alloc_and_find_schema_if_needed_fbcode(
                name,
                cpp_kernel_key,
                op_overload,
                raw_args,
                outputs,
            )
        else:
            return self.generate_extern_kernel_alloc_and_find_schema_if_needed_oss(
                name,
                kernel,
                codegen_args,
                cpp_op_schema,
                cpp_kernel_key,
                cpp_kernel_overload_name,
            )

    def generate_extern_kernel_alloc_and_find_schema_if_needed_oss(
        self,
        name,
        kernel,
        codegen_args,
        cpp_op_schema,
        cpp_kernel_key,
        cpp_kernel_overload_name="",
    ):
        if cpp_kernel_key not in self.extern_call_ops:
            self.writeline(
                f"static auto op_{cpp_kernel_key} = c10::Dispatcher::singleton()"
            )
            self.writeline(
                f'\t.findSchemaOrThrow("{kernel}", "{cpp_kernel_overload_name}")'
            )
            self.writeline(f"\t.typed<{cpp_op_schema}>();")
            self.extern_call_ops.add(cpp_kernel_key)

        self.writeline(
            f"auto {name} = op_{cpp_kernel_key}.call({', '.join(codegen_args)});"
        )

    def generate_extern_kernel_alloc_and_find_schema_if_needed_fbcode(
        self,
        name,
        cpp_kernel_key,
        op_overload,
        raw_args,  # contains both args and flatten kwargs
        outputs,
    ):
        def extract_output_name(out):
            assert out is not None, "None, i.e. optional output is not supported"
            if isinstance(out, ir.MultiOutput):
                return out.get_name()
            elif isinstance(out, (list, tuple)):
                return type(out)(extract_output_name(o) for o in out)
            else:
                raise AssertionError(f"Unexpected output: {type(out)}")

        # output_args has the same pytree structure as outputs
        output_args = extract_output_name(outputs)
        if isinstance(output_args, str):
            output_args = [output_args]

        (
            tensor_call_args,
            int_call_args,
        ) = self.generate_extern_kernel_args_decl_if_needed(
            op_overload, raw_args, output_args
        )

        tensor_call_args_str = ", ".join(tensor_call_args)
        int_call_args_str = ", ".join(int_call_args)

        extern_kernel_node_index = len(V.graph.extern_kernel_nodes) - 1

        self.writeline(
            f"aoti_torch_proxy_executor_call_function(proxy_executor, "
            f"{extern_kernel_node_index}, "
            f"{len(int_call_args)}, "
            f"std::vector<int64_t>{{{int_call_args_str}}}.data(), "
            f"{len(tensor_call_args)}, "
            f"std::vector<AtenTensorHandle>{{{tensor_call_args_str}}}.data());"
        )

        self.extern_call_ops.add(cpp_kernel_key)

    def generate_reset_kernel_saved_flags(self):
        pass

    def generate_save_uncompiled_kernels(self):
        pass

    def val_to_cpp_arg_str(self, type_, val, is_legacy_abi) -> str:
        if (
            config.abi_compatible
            and not is_legacy_abi
            and isinstance(type_, torch.OptionalType)
        ):
            if val is None:
                return "0"  # nullptr is not available in C
            if not isinstance(type_.getElementType(), torch.TensorType):
                var_name = f"var_{next(self.arg_var_id)}"
                self.writeline(f"auto {var_name} = {self.val_to_arg_str(val)};")
                return f"&{var_name}"
            elif config.c_shim_version == "2":
                # Similar to other data type, use pointer to denote optional tensor arg in v2 C shim
                base_handle = self.val_to_arg_str(val)
                if "wrap_with_raii_handle_if_needed" in base_handle:
                    # wrap_with_raii_handle_if_needed creates a temp RAIIAtenTensorHandle, so we need to
                    # explicitly store it. Otherwise, it will be destroyed before the fallback kernel call.
                    tmp_var_name = f"var_{next(self.arg_var_id)}"
                    self.writeline(
                        f"RAIIAtenTensorHandle {tmp_var_name} = {base_handle};"
                    )
                    base_handle = tmp_var_name
                var_name = f"var_{next(self.arg_var_id)}"
                self.writeline(f"AtenTensorHandle {var_name} = {base_handle}.get();")
                return f"&{var_name}"

        return self.val_to_arg_str(val)

    def val_to_arg_str(self, val) -> str:
        if val is None:
            # When None is passed as an argument, it represents an optional that does not contain a value.
            if config.abi_compatible:
                return "0"  # nullptr is not available in C
            return "c10::nullopt"
        elif isinstance(val, bool):
            if config.abi_compatible:
                return "1" if val else "0"
            else:
                return "true" if val else "false"
        elif isinstance(val, int):
            # uint64_t is long on Linux, but long long on MacOS
            return f"{val}LL" if sys.platform == "darwin" else f"{val}L"
        elif isinstance(val, str):
            return f'"{val}"'
        elif isinstance(
            val, (ir.Buffer, ir.ReinterpretView, ir.StorageBox, ir.TensorBox)
        ):
            return val.codegen_reference()
        elif isinstance(val, torch.device):
            return self.codegen_device(val)
        elif isinstance(val, torch.dtype):
            return self.codegen_dtype(val)
        elif isinstance(val, float) and val in [float("inf"), float("-inf")]:
            if val == float("inf"):
                return "std::numeric_limits<float>::infinity()"
            else:
                return "-std::numeric_limits<float>::infinity()"
        elif isinstance(val, (list, tuple)):
            # FIXME handle embedded optional types?
            result = f"{{{', '.join(self.val_to_arg_str(x) for x in val)}}}"
            if config.abi_compatible:
                static = self.is_statically_known_list_of_ints(val)
                # Need to pass the array length because we can't use std::vector
                int_var_array = self.codegen_int_array_var(
                    result,
                    known_statically=static,
                    graph=self.get_codegened_graph(),
                )
                return f"{int_var_array}, {len(val)}"
            else:
                return result
        else:
            return repr(val)
