// Copyright (c) Facebook, Inc. and its affiliates.
// All rights reserved.
//
// Copyright 2019 Google LLC
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.
//
// Auto-generated file. Do not edit!
//   Specification: test/f32-igemm-relu.yaml
//   Generator: tools/generate-gemm-test.py


#include <gtest/gtest.h>

#include <xnnpack/allocator.h>
#include <xnnpack/common.h>
#include <xnnpack/isa-checks.h>
#include <xnnpack/microparams-init.h>

#include <xnnpack/gemm.h>
#include <xnnpack/igemm.h>
#include <xnnpack/ppmm.h>
#include "gemm-microkernel-tester.h"


#if XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, k_eq_4) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(1)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, strided_cn) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(1)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 1; m++) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 1; m++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(23)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 1; mz++) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(23)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMSIMD_SPLAT, strided_cm) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(1)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, k_eq_4) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(1)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, strided_cn) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(1)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 1; m++) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 1; m++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(23)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 1; mz++) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(23)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMSIMD, strided_cm) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(1)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, k_eq_1) {
    GemmMicrokernelTester()
      .mr(3)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(3)
      .n(8)
      .k(1)
      .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, strided_cn) {
    GemmMicrokernelTester()
      .mr(3)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(3)
      .n(8)
      .k(1)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, k_eq_1_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 3; m++) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(1)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, k_eq_1_subtile_m) {
    for (uint32_t m = 1; m <= 3; m++) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(m)
        .n(8)
        .k(1)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, k_eq_1_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(3)
        .n(n)
        .k(1)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, k_gt_1) {
    for (size_t k = 2; k < 10; k++) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(3)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, k_gt_1_subtile) {
    for (size_t k = 2; k < 10; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, small_kernel) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(3)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, small_kernel_subtile) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, strided_cm_subtile) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, a_offset) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(3)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(17)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, zero) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t mz = 0; mz < 3; mz++) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(17)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMSIMD_LOADSPLAT, strided_cm) {
    GemmMicrokernelTester()
      .mr(3)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(3)
      .n(8)
      .k(1)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, k_eq_1) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(4)
      .n(8)
      .k(1)
      .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, strided_cn) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(4)
      .n(8)
      .k(1)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, k_eq_1_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 4; m++) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(1)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, k_eq_1_subtile_m) {
    for (uint32_t m = 1; m <= 4; m++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(m)
        .n(8)
        .k(1)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, k_eq_1_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(n)
        .k(1)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, k_gt_1) {
    for (size_t k = 2; k < 10; k++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, k_gt_1_subtile) {
    for (size_t k = 2; k < 10; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, small_kernel) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, small_kernel_subtile) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, strided_cm_subtile) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, a_offset) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(23)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, zero) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t mz = 0; mz < 4; mz++) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(23)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_LOADSPLAT, strided_cm) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(4)
      .n(8)
      .k(1)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, k_eq_4) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(4)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, strided_cn) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(4)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 4; m++) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 4; m++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(83)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 4; mz++) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(83)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMSIMD_SPLAT, strided_cm) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(4)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, k_eq_1) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(5)
      .n(8)
      .k(1)
      .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, strided_cn) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(5)
      .n(8)
      .k(1)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, k_eq_1_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 5; m++) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(1)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, k_eq_1_subtile_m) {
    for (uint32_t m = 1; m <= 5; m++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(m)
        .n(8)
        .k(1)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, k_eq_1_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(n)
        .k(1)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, k_gt_1) {
    for (size_t k = 2; k < 10; k++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, k_gt_1_subtile) {
    for (size_t k = 2; k < 10; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, small_kernel) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, small_kernel_subtile) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, strided_cm_subtile) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, a_offset) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(29)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, zero) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t mz = 0; mz < 5; mz++) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(29)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_LOADSPLAT, strided_cm) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(5)
      .n(8)
      .k(1)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_loadsplat, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, k_eq_4) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(5)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, strided_cn) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(5)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 5; m++) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 5; m++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(103)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 5; mz++) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(103)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMSIMD_SPLAT, strided_cm) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(5)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmsimd_splat, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, k_eq_4) {
    GemmMicrokernelTester()
      .mr(6)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(6)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, strided_cn) {
    GemmMicrokernelTester()
      .mr(6)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(6)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 6; m++) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 6; m++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(127)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 6; mz++) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(127)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMSIMD, strided_cm) {
    GemmMicrokernelTester()
      .mr(6)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(6)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmsimd, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(1)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cn) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(1)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 1; m++) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 1; m++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(1)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(23)
        .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 1; mz++) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(1)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(23)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cm) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(1)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_1x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, k_eq_4) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(1)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, strided_cn) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(1)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 1; m++) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 1; m++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(1)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(23)
        .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 1; mz++) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(1)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(23)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X8S4__WASMRELAXEDSIMD_FMA, strided_cm) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(1)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_1x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4) {
    GemmMicrokernelTester()
      .mr(3)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(3)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cn) {
    GemmMicrokernelTester()
      .mr(3)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(3)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 3; m++) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 3; m++) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(3)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(3)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(3)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(3)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(3)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 3; m++) {
          GemmMicrokernelTester()
            .mr(3)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(3)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(3)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(67)
        .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 3; mz++) {
        GemmMicrokernelTester()
          .mr(3)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(3)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(67)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_3X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cm) {
    GemmMicrokernelTester()
      .mr(3)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(3)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_3x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, k_eq_4) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(2)
      .kr(4)
      .sr(1)
      .m(4)
      .n(2)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, strided_cn) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(2)
      .kr(4)
      .sr(1)
      .m(4)
      .n(2)
      .k(4)
      .cn_stride(5)
      .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 2; n++) {
      for (uint32_t m = 1; m <= 4; m++) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(2)
          .kr(4)
          .sr(1)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 4; m++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(2)
        .kr(4)
        .sr(1)
        .m(m)
        .n(2)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 2; n++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(2)
        .kr(4)
        .sr(1)
        .m(4)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(2)
        .kr(4)
        .sr(1)
        .m(4)
        .n(2)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 2; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(2)
            .kr(4)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(2)
        .kr(4)
        .sr(1)
        .m(4)
        .n(2)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 2; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(2)
            .kr(4)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(2)
        .kr(4)
        .sr(1)
        .m(4)
        .n(2)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 2; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(2)
            .kr(4)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, n_gt_2) {
    for (uint32_t n = 3; n < 4; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(2)
          .kr(4)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, n_gt_2_strided_cn) {
    for (uint32_t n = 3; n < 4; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(2)
          .kr(4)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .cn_stride(5)
          .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, n_gt_2_subtile) {
    for (uint32_t n = 3; n < 4; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(2)
            .kr(4)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, n_div_2) {
    for (uint32_t n = 4; n <= 6; n += 2) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(2)
          .kr(4)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, n_div_2_strided_cn) {
    for (uint32_t n = 4; n <= 6; n += 2) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(2)
          .kr(4)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .cn_stride(5)
          .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, n_div_2_subtile) {
    for (uint32_t n = 4; n <= 6; n += 2) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(2)
            .kr(4)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(2)
        .kr(4)
        .sr(1)
        .m(4)
        .n(2)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 2; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(2)
            .kr(4)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, n_gt_2_small_kernel) {
    for (uint32_t n = 3; n < 4; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(2)
          .kr(4)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, n_div_2_small_kernel) {
    for (uint32_t n = 4; n <= 6; n += 2) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(2)
          .kr(4)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 2; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(2)
            .kr(4)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(5)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(2)
        .kr(4)
        .sr(1)
        .m(4)
        .n(2)
        .k(k)
        .ks(3)
        .a_offset(83)
        .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 4; mz++) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(2)
          .kr(4)
          .sr(1)
          .m(4)
          .n(2)
          .k(k)
          .ks(3)
          .a_offset(83)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X2C4__WASMRELAXEDSIMD_FMA, strided_cm) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(2)
      .kr(4)
      .sr(1)
      .m(4)
      .n(2)
      .k(4)
      .cm_stride(5)
      .Test(xnn_f32_igemm_relu_ukernel_4x2c4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(4)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cn) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(4)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 4; m++) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 4; m++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 4; m++) {
          GemmMicrokernelTester()
            .mr(4)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(4)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(4)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(83)
        .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 4; mz++) {
        GemmMicrokernelTester()
          .mr(4)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(4)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(83)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_4X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cm) {
    GemmMicrokernelTester()
      .mr(4)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(4)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_4x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(5)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cn) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(5)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 5; m++) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 5; m++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(5)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(103)
        .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 5; mz++) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(5)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(103)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cm) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(5)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_5x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, k_eq_4) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(5)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, strided_cn) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(5)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 5; m++) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 5; m++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(5)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(5)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(5)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(5)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(5)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(5)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(5)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(5)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(5)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(5)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(5)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 5; m++) {
          GemmMicrokernelTester()
            .mr(5)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(5)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(5)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(103)
        .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 5; mz++) {
        GemmMicrokernelTester()
          .mr(5)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(5)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(103)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_5X8S4__WASMRELAXEDSIMD_FMA, strided_cm) {
    GemmMicrokernelTester()
      .mr(5)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(5)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_5x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4) {
    GemmMicrokernelTester()
      .mr(6)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(6)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cn) {
    GemmMicrokernelTester()
      .mr(6)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(6)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 6; m++) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 6; m++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(6)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(6)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(6)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(6)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(6)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(6)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(6)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(6)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(6)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(6)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(6)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(1)
        .m(6)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(127)
        .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 6; mz++) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(1)
          .m(6)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(127)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8__WASMRELAXEDSIMD_FMA_SPLAT, strided_cm) {
    GemmMicrokernelTester()
      .mr(6)
      .nr(8)
      .kr(1)
      .sr(1)
      .m(6)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_6x8__wasmrelaxedsimd_fma_splat, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, k_eq_4) {
    GemmMicrokernelTester()
      .mr(6)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(6)
      .n(8)
      .k(4)
      .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, strided_cn) {
    GemmMicrokernelTester()
      .mr(6)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(6)
      .n(8)
      .k(4)
      .cn_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile) {
    for (uint32_t n = 1; n <= 8; n++) {
      for (uint32_t m = 1; m <= 6; m++) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(m)
          .n(n)
          .k(4)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile_m) {
    for (uint32_t m = 1; m <= 6; m++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(m)
        .n(8)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, k_eq_4_subtile_n) {
    for (uint32_t n = 1; n <= 8; n++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(n)
        .k(4)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, k_lt_4) {
    for (size_t k = 1; k < 4; k++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, k_lt_4_subtile) {
    for (size_t k = 1; k < 4; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, k_gt_4) {
    for (size_t k = 5; k < 8; k++) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, k_gt_4_subtile) {
    for (size_t k = 5; k < 8; k++) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, k_div_4) {
    for (size_t k = 8; k <= 40; k += 4) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(8)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, k_div_4_subtile) {
    for (size_t k = 8; k <= 40; k += 4) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, n_gt_8) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, n_gt_8_strided_cn) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, n_gt_8_subtile) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, n_div_8) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, n_div_8_strided_cn) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .cn_stride(11)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, n_div_8_subtile) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, small_kernel) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(8)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, small_kernel_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, n_gt_8_small_kernel) {
    for (uint32_t n = 9; n < 16; n++) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, n_div_8_small_kernel) {
    for (uint32_t n = 16; n <= 24; n += 8) {
      for (size_t k = 1; k <= 20; k += 5) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, strided_cm_subtile) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t n = 1; n <= 8; n++) {
        for (uint32_t m = 1; m <= 6; m++) {
          GemmMicrokernelTester()
            .mr(6)
            .nr(8)
            .kr(1)
            .sr(4)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(11)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, a_offset) {
    for (size_t k = 1; k <= 20; k += 5) {
      GemmMicrokernelTester()
        .mr(6)
        .nr(8)
        .kr(1)
        .sr(4)
        .m(6)
        .n(8)
        .k(k)
        .ks(3)
        .a_offset(127)
        .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, zero) {
    for (size_t k = 1; k <= 20; k += 5) {
      for (uint32_t mz = 0; mz < 6; mz++) {
        GemmMicrokernelTester()
          .mr(6)
          .nr(8)
          .kr(1)
          .sr(4)
          .m(6)
          .n(8)
          .k(k)
          .ks(3)
          .a_offset(127)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_6X8S4__WASMRELAXEDSIMD_FMA, strided_cm) {
    GemmMicrokernelTester()
      .mr(6)
      .nr(8)
      .kr(1)
      .sr(4)
      .m(6)
      .n(8)
      .k(4)
      .cm_stride(11)
      .Test(xnn_f32_igemm_relu_ukernel_6x8s4__wasmrelaxedsimd_fma, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASMRELAXEDSIMD


#if XNN_ARCH_WASM || XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD
  TEST(F32_IGEMM_RELU_1X4__WASM, k_eq_1) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(4)
      .kr(1)
      .sr(1)
      .m(1)
      .n(4)
      .k(1)
      .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, strided_cn) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(4)
      .kr(1)
      .sr(1)
      .m(1)
      .n(4)
      .k(1)
      .cn_stride(7)
      .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, k_eq_1_subtile) {
    for (uint32_t n = 1; n <= 4; n++) {
      for (uint32_t m = 1; m <= 1; m++) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(1)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, k_eq_1_subtile_m) {
    for (uint32_t m = 1; m <= 1; m++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(m)
        .n(4)
        .k(1)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, k_eq_1_subtile_n) {
    for (uint32_t n = 1; n <= 4; n++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(1)
        .n(n)
        .k(1)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, k_gt_1) {
    for (size_t k = 2; k < 10; k++) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(1)
        .n(4)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, k_gt_1_subtile) {
    for (size_t k = 2; k < 10; k++) {
      for (uint32_t n = 1; n <= 4; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(4)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, n_gt_4) {
    for (uint32_t n = 5; n < 8; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, n_gt_4_strided_cn) {
    for (uint32_t n = 5; n < 8; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .cn_stride(7)
          .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, n_gt_4_subtile) {
    for (uint32_t n = 5; n < 8; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(4)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, n_div_4) {
    for (uint32_t n = 8; n <= 12; n += 4) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, n_div_4_strided_cn) {
    for (uint32_t n = 8; n <= 12; n += 4) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .cn_stride(7)
          .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, n_div_4_subtile) {
    for (uint32_t n = 8; n <= 12; n += 4) {
      for (size_t k = 1; k <= 5; k += 2) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(4)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, small_kernel) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(1)
        .n(4)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, small_kernel_subtile) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t n = 1; n <= 4; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(4)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .ks(3)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, n_gt_4_small_kernel) {
    for (uint32_t n = 5; n < 8; n++) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, n_div_4_small_kernel) {
    for (uint32_t n = 8; n <= 12; n += 4) {
      for (size_t k = 1; k <= 5; k += 2) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(1)
          .n(n)
          .k(k)
          .ks(3)
          .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, strided_cm_subtile) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t n = 1; n <= 4; n++) {
        for (uint32_t m = 1; m <= 1; m++) {
          GemmMicrokernelTester()
            .mr(1)
            .nr(4)
            .kr(1)
            .sr(1)
            .m(m)
            .n(n)
            .k(k)
            .cm_stride(7)
            .iterations(1)
            .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
        }
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, a_offset) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(1)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(1)
        .n(4)
        .k(k)
        .ks(3)
        .a_offset(7)
        .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, zero) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t mz = 0; mz < 1; mz++) {
        GemmMicrokernelTester()
          .mr(1)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(1)
          .n(4)
          .k(k)
          .ks(3)
          .a_offset(7)
          .zero_index(mz)
          .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
      }
    }
  }

  TEST(F32_IGEMM_RELU_1X4__WASM, strided_cm) {
    GemmMicrokernelTester()
      .mr(1)
      .nr(4)
      .kr(1)
      .sr(1)
      .m(1)
      .n(4)
      .k(1)
      .cm_stride(7)
      .Test(xnn_f32_igemm_relu_ukernel_1x4__wasm, xnn_pack_f32_conv_goki_w);
  }
#endif  // XNN_ARCH_WASM || XNN_ARCH_WASMSIMD || XNN_ARCH_WASMRELAXEDSIMD


TEST(F32_IGEMM_RELU_2X4__SCALAR, k_eq_1) {
  GemmMicrokernelTester()
    .mr(2)
    .nr(4)
    .kr(1)
    .sr(1)
    .m(2)
    .n(4)
    .k(1)
    .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, strided_cn) {
  GemmMicrokernelTester()
    .mr(2)
    .nr(4)
    .kr(1)
    .sr(1)
    .m(2)
    .n(4)
    .k(1)
    .cn_stride(7)
    .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, k_eq_1_subtile) {
  for (uint32_t n = 1; n <= 4; n++) {
    for (uint32_t m = 1; m <= 2; m++) {
      GemmMicrokernelTester()
        .mr(2)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(m)
        .n(n)
        .k(1)
        .iterations(1)
        .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, k_eq_1_subtile_m) {
  for (uint32_t m = 1; m <= 2; m++) {
    GemmMicrokernelTester()
      .mr(2)
      .nr(4)
      .kr(1)
      .sr(1)
      .m(m)
      .n(4)
      .k(1)
      .iterations(1)
      .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, k_eq_1_subtile_n) {
  for (uint32_t n = 1; n <= 4; n++) {
    GemmMicrokernelTester()
      .mr(2)
      .nr(4)
      .kr(1)
      .sr(1)
      .m(2)
      .n(n)
      .k(1)
      .iterations(1)
      .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, k_gt_1) {
  for (size_t k = 2; k < 10; k++) {
    GemmMicrokernelTester()
      .mr(2)
      .nr(4)
      .kr(1)
      .sr(1)
      .m(2)
      .n(4)
      .k(k)
      .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, k_gt_1_subtile) {
  for (size_t k = 2; k < 10; k++) {
    for (uint32_t n = 1; n <= 4; n++) {
      for (uint32_t m = 1; m <= 2; m++) {
        GemmMicrokernelTester()
          .mr(2)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(k)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
      }
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, n_gt_4) {
  for (uint32_t n = 5; n < 8; n++) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(2)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(2)
        .n(n)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, n_gt_4_strided_cn) {
  for (uint32_t n = 5; n < 8; n++) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(2)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(2)
        .n(n)
        .k(k)
        .cn_stride(7)
        .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, n_gt_4_subtile) {
  for (uint32_t n = 5; n < 8; n++) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t m = 1; m <= 2; m++) {
        GemmMicrokernelTester()
          .mr(2)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(k)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
      }
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, n_div_4) {
  for (uint32_t n = 8; n <= 12; n += 4) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(2)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(2)
        .n(n)
        .k(k)
        .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, n_div_4_strided_cn) {
  for (uint32_t n = 8; n <= 12; n += 4) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(2)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(2)
        .n(n)
        .k(k)
        .cn_stride(7)
        .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, n_div_4_subtile) {
  for (uint32_t n = 8; n <= 12; n += 4) {
    for (size_t k = 1; k <= 5; k += 2) {
      for (uint32_t m = 1; m <= 2; m++) {
        GemmMicrokernelTester()
          .mr(2)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(k)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
      }
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, small_kernel) {
  for (size_t k = 1; k <= 5; k += 2) {
    GemmMicrokernelTester()
      .mr(2)
      .nr(4)
      .kr(1)
      .sr(1)
      .m(2)
      .n(4)
      .k(k)
      .ks(3)
      .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, small_kernel_subtile) {
  for (size_t k = 1; k <= 5; k += 2) {
    for (uint32_t n = 1; n <= 4; n++) {
      for (uint32_t m = 1; m <= 2; m++) {
        GemmMicrokernelTester()
          .mr(2)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(k)
          .ks(3)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
      }
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, n_gt_4_small_kernel) {
  for (uint32_t n = 5; n < 8; n++) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(2)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(2)
        .n(n)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, n_div_4_small_kernel) {
  for (uint32_t n = 8; n <= 12; n += 4) {
    for (size_t k = 1; k <= 5; k += 2) {
      GemmMicrokernelTester()
        .mr(2)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(2)
        .n(n)
        .k(k)
        .ks(3)
        .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, strided_cm_subtile) {
  for (size_t k = 1; k <= 5; k += 2) {
    for (uint32_t n = 1; n <= 4; n++) {
      for (uint32_t m = 1; m <= 2; m++) {
        GemmMicrokernelTester()
          .mr(2)
          .nr(4)
          .kr(1)
          .sr(1)
          .m(m)
          .n(n)
          .k(k)
          .cm_stride(7)
          .iterations(1)
          .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
      }
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, a_offset) {
  for (size_t k = 1; k <= 5; k += 2) {
    GemmMicrokernelTester()
      .mr(2)
      .nr(4)
      .kr(1)
      .sr(1)
      .m(2)
      .n(4)
      .k(k)
      .ks(3)
      .a_offset(13)
      .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, zero) {
  for (size_t k = 1; k <= 5; k += 2) {
    for (uint32_t mz = 0; mz < 2; mz++) {
      GemmMicrokernelTester()
        .mr(2)
        .nr(4)
        .kr(1)
        .sr(1)
        .m(2)
        .n(4)
        .k(k)
        .ks(3)
        .a_offset(13)
        .zero_index(mz)
        .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
    }
  }
}

TEST(F32_IGEMM_RELU_2X4__SCALAR, strided_cm) {
  GemmMicrokernelTester()
    .mr(2)
    .nr(4)
    .kr(1)
    .sr(1)
    .m(2)
    .n(4)
    .k(1)
    .cm_stride(7)
    .Test(xnn_f32_igemm_relu_ukernel_2x4__scalar, xnn_pack_f32_conv_goki_w);
}
