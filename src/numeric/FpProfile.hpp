#pragma once

// The numerical profile the engine is built to, and how to ask a library what
// its own objects do under it (cmake/FloatingPointModel.cmake,
// docs/floating-point-model.md).
//
// Standalone on purpose: src/numeric/FpProbeJolt.cpp includes it from inside
// Jolt's own target, which sees none of our other headers.

#include <cstdint>

namespace banjo::fp {

// "banjo-cpu-precise-v1": what the build was compiled to.
[[nodiscard]] const char *profile();

// FNV-1a of profile(). A numerical cache -- the valley's ground, the scenario
// and outcome tables, the propagators -- is keyed by it, so one written under
// another profile is left where it is and not used.
[[nodiscard]] std::uint64_t profileHash();

// Inputs a probe computes from. They come from the caller at run time, so no
// compiler can fold the arithmetic away before the probe's own rules decide it.
struct Inputs {
    double near_one_up{};      // 1 + 2^-27: its product with the next is 1 - 2^-54,
    double near_one_down{};    // 1 - 2^-27  which rounds to 1, a tie to even
    double minus_one{};
    double big{};              // 1e16, and its negative: (big - big) + 1 is 1 in
    double minus_big{};        // order, 0 if the sum is reassociated
    double one{};
    double nan{};
    double inf{};
    double zero{};
    double negative_zero{};
    double min_normal{};       // DBL_MIN; half of it is a denormal
    double half{};
    float near_one_up_f{};     // 1 + 2^-13 and 1 - 2^-13: 1 - 2^-26 rounds to 1
    float near_one_down_f{};
    float minus_one_f{};
    float zero_f{};
};

// What one translation unit's own rules made of the inputs.
struct Observations {
    double product_sum{};      // near_one_up * near_one_down + minus_one: 0 unfused
    double explicit_fma{};     // std::fma of the same: -2^-54 always
    float product_sum_f{};
    float explicit_fma_f{};
    double sum_in_order{};     // (big + minus_big) + one: 1 in the order written
    bool nan_unequal{};                     // nan != nan
    bool nan_not_positive{};                // !(nan > 0)
    bool nan_not_finite{};                  // !isfinite(nan)
    bool inf_not_finite{};                  // !isfinite(inf)
    bool inf_is_inf{};                      // isinf(inf)
    bool huge_val_is_inf{};                 // isinf(HUGE_VAL): 1e+300 under /fp:fast
    bool infinity_is_inf{};                 // isinf(INFINITY), in float
    bool negative_zero_sum_is_positive{};   // -0 + +0 is +0
    bool negative_zero_product_is_negative{};  // -1 * +0 is -0
    bool denormal_kept{};                   // DBL_MIN / 2 is not flushed to zero
};

// The same probe, compiled into each library that reports on its own rules.
[[nodiscard]] Observations observeCore(const Inputs &inputs);     // banjo_core
[[nodiscard]] Observations observeRuntime(const Inputs &inputs);  // banjo_runtime, with Jolt's usage requirements
[[nodiscard]] Observations observeJolt(const Inputs &inputs);     // inside Jolt's own target

// Jolt's explicit fused multiply-add (Vec4::sFusedMultiplyAdd), compiled in
// Jolt, and whether Jolt was built to use FMA instructions for it.
[[nodiscard]] float joltFusedMultiplyAdd(float a, float b, float c);
[[nodiscard]] bool joltUsesFusedMultiplyAdd();

} // namespace banjo::fp
