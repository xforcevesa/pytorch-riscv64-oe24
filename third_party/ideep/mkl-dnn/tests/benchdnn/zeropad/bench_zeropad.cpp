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

#include <stdio.h>
#include <stdlib.h>

#include "dnnl_common.hpp"
#include "utils/parser.hpp"

#include "zeropad/zeropad.hpp"

namespace zeropad {

void check_correctness(const settings_t &s) {
    for_(const auto &i_dt : s.dt)
    for (const auto &i_tag : s.tag) {
        const prb_t prb(s.prb_dims, i_dt, i_tag);
        BENCHDNN_PRINT(1, "run: %s\n", prb.str());

        res_t res {};
        doit(&prb, &res);

        parse_result(res, prb.str());

        if (has_bench_mode_bit(mode_bit_t::perf)) {
            perf_report_t pr(&prb, s.perf_template);
            pr.report(&res, prb.str());
        }
    }
}

int bench(int argc, char **argv) {
    driver_name = "zeropad";
    using namespace parser;
    static settings_t s;
    static const settings_t def {};
    for (; argc > 0; --argc, ++argv) {
        const bool parsed_options = parse_bench_settings(argv[0])
                || parse_batch(bench, argv[0])
                || parse_dt(s.dt, def.dt, argv[0])
                || parse_tag(s.tag, def.tag, argv[0])
                || parse_perf_template(s.perf_template, s.perf_template_def,
                        s.perf_template_csv(), argv[0])
                || parse_reset(s, argv[0]) || parse_help(argv[0]);
        if (!parsed_options) {
            catch_unknown_options(argv[0]);

            parse_prb_dims(s.prb_dims, argv[0]);
            check_correctness(s);
        }
    }

    return parse_last_argument();
}
} // namespace zeropad
