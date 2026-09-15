// One translation unit's own observation of its floating-point rules.
//
// Included by exactly one .cpp in each library that reports on itself
// (FpProfile.cpp, FpProbeRuntime.cpp, FpProbeJolt.cpp). Everything here has
// internal linkage, so each includer compiles its own copy under its own
// flags -- which is what is being asked -- and no copy can be swapped for
// another at link. C++17, because Jolt's target compiles as C++17.

#include "FpProfile.hpp"

#include <cmath>

namespace {

#if defined(_MSC_VER)
#define BANJO_FP_PROBE_NOINLINE __declspec(noinline)
#else
#define BANJO_FP_PROBE_NOINLINE __attribute__((noinline))
#endif

BANJO_FP_PROBE_NOINLINE banjo::fp::Observations observeHere(const banjo::fp::Inputs &in) {
    banjo::fp::Observations o;
    o.product_sum = in.near_one_up * in.near_one_down + in.minus_one;
    o.explicit_fma = std::fma(in.near_one_up, in.near_one_down, in.minus_one);
    o.product_sum_f = in.near_one_up_f * in.near_one_down_f + in.minus_one_f;
    o.explicit_fma_f = std::fma(in.near_one_up_f, in.near_one_down_f, in.minus_one_f);
    o.sum_in_order = (in.big + in.minus_big) + in.one;
    o.nan_unequal = in.nan != in.nan;
    o.nan_not_positive = !(in.nan > 0.0);
    o.nan_not_finite = !std::isfinite(in.nan);
    o.inf_not_finite = !std::isfinite(in.inf);
    o.inf_is_inf = std::isinf(in.inf);
    o.huge_val_is_inf = std::isinf(HUGE_VAL + in.zero);
    o.infinity_is_inf = std::isinf(INFINITY + in.zero_f);
    o.negative_zero_sum_is_positive = !std::signbit(in.negative_zero + in.zero);
    o.negative_zero_product_is_negative = std::signbit(in.minus_one * in.zero);
    o.denormal_kept = in.min_normal * in.half != 0.0;
    return o;
}

} // namespace
