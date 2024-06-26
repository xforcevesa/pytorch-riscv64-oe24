#include <shared_mutex>

#include <ATen/ATen.h>
#include <ATen/core/op_registration/op_registration.h>
#include <c10/core/DispatchKey.h>
#include <torch/csrc/autograd/function.h>
#include <torch/csrc/distributed/c10d/GroupRegistry.hpp>
#include <torch/csrc/distributed/c10d/ProcessGroup.hpp>
#include <torch/csrc/distributed/c10d/RankLocal.hpp>

namespace {

class WorkRegistry {
 public:
  void register_work(
      const at::Tensor& tensor,
      c10::intrusive_ptr<c10d::Work> work) {
    const auto storage = tensor.storage().getWeakStorageImpl();
    std::unique_lock lock(lock_);
    auto [it, inserted] = registry_.emplace(storage, work);
    TORCH_CHECK(
        inserted || it->second != work,
        "The tensor storage is already associated with another work.");
  }

  c10::intrusive_ptr<c10d::Work> pop_work(const at::Tensor& tensor) {
    const auto storage = tensor.storage().getWeakStorageImpl();
    std::unique_lock lock(lock_);
    auto it = registry_.find(storage);
    if (it == registry_.end()) {
      return nullptr;
    }
    auto work = it->second;
    registry_.erase(it);
    return work;
  }

  ~WorkRegistry() {
    // If there are still unwaited work objects, their corresponding process
    // groups should have already been destroyed at this stage. Any attempts to
    // wait for these work objects or to destroy them will only result in
    // confusing errors. Therefore, we simply issue a warning and intentionally
    // allow the unwaited work objects to leak.
    if (!registry_.empty()) {
      TORCH_WARN(
          "At the time of process termination, there are still ",
          registry_.size(),
          " unwaited c10d_functional collective calls. "
          "Please review your program to ensure c10d_functional.wait_tensor() "
          "is invoked on all tensors returned from c10d_functional collective "
          "ops before they are used.");
    }
    for (auto it = registry_.begin(); it != registry_.end(); ++it) {
      it->second.release();
    }
  }

 private:
  std::unordered_map<
      c10::weak_intrusive_ptr<c10::StorageImpl>,
      c10::intrusive_ptr<c10d::Work>>
      registry_;
  std::mutex lock_;
};

static WorkRegistry process_registry;

void register_work(
    const at::Tensor& tensor,
    c10::intrusive_ptr<c10d::Work> work) {
  if (c10d::get_thread_isolation_mode()) {
    c10d::RankLocal<WorkRegistry>::get().register_work(tensor, work);
  } else {
    process_registry.register_work(tensor, work);
  }
}

c10::intrusive_ptr<c10d::Work> pop_work(const at::Tensor& tensor) {
  if (c10d::get_thread_isolation_mode()) {
    return c10d::RankLocal<WorkRegistry>::get().pop_work(tensor);
  } else {
    return process_registry.pop_work(tensor);
  }
}

const std::unordered_map<std::string, c10d::ReduceOp> str_to_reduce_op = {
    {"sum", c10d::ReduceOp(c10d::ReduceOp::RedOpType::SUM)},
    {"avg", c10d::ReduceOp(c10d::ReduceOp::RedOpType::AVG)},
    {"product", c10d::ReduceOp(c10d::ReduceOp::RedOpType::PRODUCT)},
    {"min", c10d::ReduceOp(c10d::ReduceOp::RedOpType::MIN)},
    {"max", c10d::ReduceOp(c10d::ReduceOp::RedOpType::MAX)},
    {"band", c10d::ReduceOp(c10d::ReduceOp::RedOpType::BAND)},
    {"bor", c10d::ReduceOp(c10d::ReduceOp::RedOpType::BOR)},
    {"bxor", c10d::ReduceOp(c10d::ReduceOp::RedOpType::BXOR)},
    // TODO: support premul_sum
    // {"premul_sum", c10d::ReduceOp(c10d::ReduceOp::RedOpType::PREMUL_SUM)},
    {"unused", c10d::ReduceOp(c10d::ReduceOp::RedOpType::UNUSED)}};

c10d::ReduceOp to_reduce_op(const std::string& reduce_op) {
  auto it = str_to_reduce_op.find(reduce_op);
  TORCH_CHECK(
      it != str_to_reduce_op.end(), "Unrecognized reduce_op: ", reduce_op);
  return it->second;
}

at::Tensor& all_reduce_(
    at::Tensor& input,
    std::string reduce_op,
    std::string group_name) {
  c10d::AllreduceOptions opts;
  opts.reduceOp = to_reduce_op(reduce_op);

  std::vector<at::Tensor> inputs{input};
  auto group = c10d::resolve_process_group(group_name);
  auto work = group->allreduce(inputs, opts);
  c10d::RankLocal<WorkRegistry>::get().register_work(input, work);
  return input;
}

at::Tensor all_reduce(
    const at::Tensor& input,
    std::string reduce_op,
    std::string group_name) {
  auto output = input.clone(at::MemoryFormat::Contiguous);
  return all_reduce_(output, reduce_op, group_name);
}

std::vector<at::Tensor> all_reduce_coalesced_(
    std::vector<at::Tensor> inputs,
    std::string reduce_op,
    std::string group_name) {
  c10d::AllreduceCoalescedOptions opts;
  opts.reduceOp = to_reduce_op(reduce_op);

  auto group = c10d::resolve_process_group(group_name);
  auto work = group->allreduce_coalesced(inputs, opts);
  for (const auto& tensor : inputs) {
    c10d::RankLocal<WorkRegistry>::get().register_work(tensor, work);
  }
  return inputs;
}

std::vector<at::Tensor> all_reduce_coalesced(
    std::vector<at::Tensor> inputs,
    std::string reduce_op,
    std::string group_name) {
  std::vector<at::Tensor> outputs;
  outputs.reserve(inputs.size());
  for (const auto& tensor : inputs) {
    outputs.push_back(tensor.clone(at::MemoryFormat::Contiguous));
  }
  return all_reduce_coalesced_(outputs, reduce_op, group_name);
}

at::Tensor allocate_all_gather_output(
    const at::Tensor& input,
    int64_t group_size) {
  auto output_size = input.sizes().vec();
  output_size[0] *= group_size;
  return at::empty(
      output_size,
      at::TensorOptions().dtype(input.dtype()).device(input.device()));
}

std::vector<at::Tensor> all_gather_into_tensor_coalesced(
    std::vector<at::Tensor> inputs,
    int64_t group_size,
    std::string group_name) {
  std::vector<at::Tensor> outputs;
  for (const auto& tensor : inputs) {
    outputs.push_back(allocate_all_gather_output(tensor, group_size));
  }

  auto group = c10d::resolve_process_group(group_name);
  auto work = group->allgather_into_tensor_coalesced(
      outputs, const_cast<std::vector<at::Tensor>&>(inputs));
  for (const auto& tensor : outputs) {
    c10d::RankLocal<WorkRegistry>::get().register_work(tensor, work);
  }
  return outputs;
}

at::Tensor all_gather_into_tensor(
    const at::Tensor& input,
    int64_t group_size,
    std::string group_name) {
  std::vector<at::Tensor> inputs{input};
  return all_gather_into_tensor_coalesced(inputs, group_size, group_name)[0];
}

at::Tensor allocate_reduce_scatter_output(
    const at::Tensor& input,
    const int64_t group_size) {
  auto output_size = input.sizes().vec();
  if (output_size[0] % group_size != 0) {
    LOG(WARNING) << "The first dimension of the reduce_scatter input ("
                 << output_size[0] << ") is not divisible by the group size ("
                 << group_size << ").";
  }
  output_size[0] /= group_size;
  return at::empty(
      output_size,
      at::TensorOptions().dtype(input.dtype()).device(input.device()));
}

std::vector<at::Tensor> reduce_scatter_tensor_coalesced(
    std::vector<at::Tensor> inputs,
    std::string reduce_op,
    int64_t group_size,
    std::string group_name) {
  c10d::ReduceScatterOptions opts;
  opts.reduceOp = to_reduce_op(reduce_op);
  std::vector<at::Tensor> outputs;
  for (const auto& tensor : inputs) {
    outputs.push_back(allocate_reduce_scatter_output(tensor, group_size));
  }

  auto group = c10d::resolve_process_group(group_name);
  auto work = group->reduce_scatter_tensor_coalesced(
      outputs, const_cast<std::vector<at::Tensor>&>(inputs), opts);
  for (const auto& tensor : outputs) {
    c10d::RankLocal<WorkRegistry>::get().register_work(tensor, work);
  }
  return outputs;
}

at::Tensor reduce_scatter_tensor(
    const at::Tensor& input,
    std::string reduce_op,
    int64_t group_size,
    std::string group_name) {
  std::vector<at::Tensor> inputs{input};
  return reduce_scatter_tensor_coalesced(
      inputs, reduce_op, group_size, group_name)[0];
}

at::Tensor all_to_all_single(
    const at::Tensor& input,
    std::vector<int64_t> output_split_sizes,
    std::vector<int64_t> input_split_sizes,
    std::string group_name) {
  std::vector<int64_t> output_sizes = input.sizes().vec();
  output_sizes[0] =
      std::accumulate(output_split_sizes.begin(), output_split_sizes.end(), 0);
  auto output = input.new_empty(output_sizes);

  auto group = c10d::resolve_process_group(group_name);
  auto work = group->alltoall_base(
      output,
      const_cast<at::Tensor&>(input),
      output_split_sizes,
      input_split_sizes);
  c10d::RankLocal<WorkRegistry>::get().register_work(output, work);
  return output;
}

at::Tensor& broadcast_(at::Tensor& input, int64_t src, std::string group_name) {
  c10d::BroadcastOptions opts;
  opts.rootRank = src;
  std::vector<at::Tensor> inputs{input};

  auto group = c10d::resolve_process_group(group_name);
  auto work = group->broadcast(inputs, opts);
  c10d::RankLocal<WorkRegistry>::get().register_work(input, work);
  return input;
}

at::Tensor broadcast(
    const at::Tensor& input,
    int64_t src,
    std::string group_name) {
  auto output = input.clone(at::MemoryFormat::Contiguous);
  return broadcast_(output, src, group_name);
}

at::Tensor wait_tensor(const at::Tensor& tensor) {
  auto work = c10d::RankLocal<WorkRegistry>::get().pop_work(tensor);
  if (work != nullptr) {
    work->wait();
  }
  return tensor;
}

} // namespace

TORCH_LIBRARY(_c10d_functional, m) {
  m.def(
      "all_reduce(Tensor input, str reduce_op, str group_name) -> Tensor",
      torch::dispatch(
          c10::DispatchKey::CompositeExplicitAutograd, ::all_reduce),
      {at::Tag::pt2_compliant_tag});

  m.def(
      "all_reduce_(Tensor(a!) input, str reduce_op, str group_name) -> Tensor(a!)",
      torch::dispatch(
          c10::DispatchKey::CompositeExplicitAutograd, ::all_reduce_),
      {at::Tag::pt2_compliant_tag});

  m.def(
      "all_reduce_coalesced(Tensor[] inputs, str reduce_op, str group_name) -> Tensor[]",
      torch::dispatch(
          c10::DispatchKey::CompositeExplicitAutograd, ::all_reduce_coalesced),
      {at::Tag::pt2_compliant_tag});

  m.def(
      "all_reduce_coalesced_(Tensor[](a!) inputs, str reduce_op, str group_name) -> Tensor[](a!)",
      torch::dispatch(
          c10::DispatchKey::CompositeExplicitAutograd, ::all_reduce_coalesced_),
      {at::Tag::pt2_compliant_tag});

  m.def(
      "all_gather_into_tensor(Tensor input, int group_size, str group_name) -> Tensor",
      torch::dispatch(
          c10::DispatchKey::CompositeExplicitAutograd,
          ::all_gather_into_tensor),
      {at::Tag::pt2_compliant_tag});

  m.def(
      "all_gather_into_tensor_coalesced(Tensor[] inputs, int group_size, str group_name) -> Tensor[]",
      torch::dispatch(
          c10::DispatchKey::CompositeExplicitAutograd,
          ::all_gather_into_tensor_coalesced),
      {at::Tag::pt2_compliant_tag});

  m.def(
      "reduce_scatter_tensor(Tensor input, str reduce_op, int group_size, str group_name) -> Tensor",
      torch::dispatch(
          c10::DispatchKey::CompositeExplicitAutograd, ::reduce_scatter_tensor),
      {at::Tag::pt2_compliant_tag});

  m.def(
      "reduce_scatter_tensor_coalesced(Tensor[] inputs, str reduce_op, int group_size, str group_name) -> Tensor[]",
      torch::dispatch(
          c10::DispatchKey::CompositeExplicitAutograd,
          ::reduce_scatter_tensor_coalesced),
      {at::Tag::pt2_compliant_tag});

  m.def(
      "all_to_all_single("
      "Tensor input, "
      "SymInt[] output_split_sizes, "
      "SymInt[] input_split_sizes, "
      "str group_name) -> Tensor",
      torch::dispatch(
          c10::DispatchKey::CompositeExplicitAutograd, ::all_to_all_single),
      {at::Tag::pt2_compliant_tag});

  m.def(
      "broadcast(Tensor input, int src, str group_name) -> Tensor",
      torch::dispatch(c10::DispatchKey::CompositeExplicitAutograd, ::broadcast),
      {at::Tag::pt2_compliant_tag});

  m.def(
      "broadcast_(Tensor(a!) input, int src, str group_name) -> Tensor(a!)",
      torch::dispatch(
          c10::DispatchKey::CompositeExplicitAutograd, ::broadcast_),
      {at::Tag::pt2_compliant_tag});

  m.def(
      "wait_tensor(Tensor tensor) -> Tensor",
      torch::dispatch(
          c10::DispatchKey::CompositeExplicitAutograd, ::wait_tensor),
      {at::Tag::pt2_compliant_tag});
}
