from typing import List

from ..scheduler import BaseSchedulerNode, BaseScheduling, Scheduler, SchedulerNode
from .cuda.cuda_cpp_scheduling import CUDACPPScheduling

from .triton import TritonScheduling


class CUDACombinedScheduling(BaseScheduling):
    """
    Scheduler for CUDA Kernels, which delegates calls as appropriate
    to the CUDA-C++ and Triton Schedulers, which both work for CUDA devices
    and use a unified-wrapper for codegen.

    If Scheduling code needs to be specialized for the case of mixed Triton / CUDA C++ code,
    this would also be the place to do it.
    """

    def __init__(self, scheduler: Scheduler):
        super().__init__()
        self._scheduler = scheduler
        self._triton_scheduling = TritonScheduling(scheduler)
        self._cuda_cpp_scheduling = CUDACPPScheduling(scheduler)

    def choose_node_backend(self, node: BaseSchedulerNode) -> BaseScheduling:
        if self._cuda_cpp_scheduling.is_cuda_cpp_template(
            node
        ) or self._cuda_cpp_scheduling.is_cuda_cpp_fused_template(node):
            return self._cuda_cpp_scheduling
        return self._triton_scheduling

    def can_fuse_vertical(self, node1: BaseSchedulerNode, node2: BaseSchedulerNode):
        if self._cuda_cpp_scheduling.can_fuse_vertical(node1, node2):
            return True
        return self._triton_scheduling.can_fuse_vertical(node1, node2)

    def can_fuse_horizontal(self, node1: BaseSchedulerNode, node2: BaseSchedulerNode):
        for node in (node1, node2):
            if self._cuda_cpp_scheduling.is_cuda_cpp_template(
                node
            ) or self._cuda_cpp_scheduling.is_cuda_cpp_fused_template(node):
                return self._cuda_cpp_scheduling.can_fuse_horizontal(
                    node1, node2
                )  # always False at the moment
        return self._triton_scheduling.can_fuse_horizontal(node1, node2)

    def group_fn(self, sizes):
        return self._triton_scheduling.group_fn(sizes)

    def codegen_template(
        self, template_node: SchedulerNode, epilogue_nodes: List[SchedulerNode]
    ):
        if self._cuda_cpp_scheduling.is_cuda_cpp_template(template_node):
            return self._cuda_cpp_scheduling.codegen_template(
                template_node, epilogue_nodes
            )
        else:
            return self._triton_scheduling.codegen_template(
                template_node, epilogue_nodes
            )

    def codegen_nodes(self, nodes: List[SchedulerNode]):
        return self._triton_scheduling.codegen_nodes(nodes)

    def codegen_sync(self):
        return self._triton_scheduling.codegen_sync()

    def flush(self):
        return self._triton_scheduling.flush()

    def codegen_foreach(self, *args, **kwargs):
        return self._triton_scheduling.codegen_foreach(*args, **kwargs)

    def benchmark_fused_nodes(self, nodes):
        return self._triton_scheduling.benchmark_fused_nodes(nodes)
