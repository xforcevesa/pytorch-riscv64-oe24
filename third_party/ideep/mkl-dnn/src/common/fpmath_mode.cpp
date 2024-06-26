/*******************************************************************************
* Copyright 2021-2022 Intel Corporation
*
* Licensed under the Apache License, Version 2.0 (the "License");
* you may not use this file except in compliance with the License.
* You may obtain a copy of the License at
*
*     http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS,
* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
* See the License for the specific language governing permissions and
* limitations under the License.
*******************************************************************************/

#include "oneapi/dnnl/dnnl.h"

#include "c_types_map.hpp"
#include "utils.hpp"

namespace dnnl {
namespace impl {
static setting_t<fpmath_mode_t> default_fpmath {fpmath_mode::strict};

void init_fpmath_mode() {
    if (default_fpmath.initialized()) return;

    static std::string val = getenv_string_user("DEFAULT_FPMATH_MODE");
    if (!val.empty()) {
        if (val.compare("strict") == 0) default_fpmath.set(fpmath_mode::strict);
        if (val.compare("bf16") == 0) default_fpmath.set(fpmath_mode::bf16);
        if (val.compare("f16") == 0) default_fpmath.set(fpmath_mode::f16);
        if (val.compare("tf32") == 0) default_fpmath.set(fpmath_mode::tf32);
        if (val.compare("any") == 0) default_fpmath.set(fpmath_mode::any);
    }
    if (!default_fpmath.initialized()) default_fpmath.set(default_fpmath.get());
}

status_t check_fpmath_mode(fpmath_mode_t mode) {
    if (utils::one_of(mode, fpmath_mode::strict, fpmath_mode::bf16,
                fpmath_mode::f16, fpmath_mode::tf32, fpmath_mode::any))
        return status::success;
    return status::invalid_arguments;
}

bool is_fpsubtype(data_type_t sub_dt, data_type_t dt) {
    using namespace dnnl::impl::utils;
    using namespace dnnl::impl::data_type;

    if (sub_dt == dt) return true;

    // Check for strict subtype
    if (dt == f32) return one_of(sub_dt, tf32, bf16, f16);
    if (dt == tf32) return one_of(sub_dt, bf16, f16);

    // bf16 and f16 have no strict subtypes
    return false;
}

fpmath_mode_t get_fpmath_mode() {
    init_fpmath_mode();
    auto mode = default_fpmath.get();
    // Should always be proper, since no way to set invalid mode
    assert(check_fpmath_mode(mode) == status::success);
    return mode;
}

} // namespace impl
} // namespace dnnl

dnnl_status_t dnnl_set_default_fpmath_mode(dnnl_fpmath_mode_t mode) {
    using namespace dnnl::impl;
    auto st = check_fpmath_mode(mode);
    if (st == status::success) default_fpmath.set(mode);
    return st;
}

dnnl_status_t dnnl_get_default_fpmath_mode(dnnl_fpmath_mode_t *mode) {
    using namespace dnnl::impl;
    if (mode == nullptr) return status::invalid_arguments;

    auto m = get_fpmath_mode();
    // Should always be proper, since no way to set invalid mode
    auto st = check_fpmath_mode(m);
    if (st == status::success) *mode = m;
    return st;
}
