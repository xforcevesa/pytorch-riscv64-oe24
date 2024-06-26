/*******************************************************************************
* Copyright 2020-2023 Intel Corporation
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

#include <sstream>

#include "dnnl_common.hpp"

#include "zeropad/zeropad.hpp"

namespace zeropad {

std::string prb_t::set_repro_line() {
    std::stringstream s;
    dump_global_params(s);
    settings_t def;

    if (canonical || dt != def.dt[0]) s << "--dt=" << dt << " ";
    if (canonical || tag != def.tag[0]) s << "--tag=" << tag << " ";

    s << static_cast<prb_dims_t>(*this);

    return s.str();
}

} // namespace zeropad
