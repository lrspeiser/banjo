#pragma once
#include "physics/CompliantStep.hpp"

namespace banjo {
// Limits are coarse-versus-two-half-step differences per reference time.
// A comparison interval h receives h/reference_time_s of each limit. These
// are local error indicators, not a rigorous global exact-solution bound.
struct CompliantErrorLimits {
    double position_m{1e-7};
    double velocity_m_s{1e-3};
    double bond_strain{1e-6};
    double damping_work_j{1e-5};
    double reference_time_s{1e-3};
};
struct CompliantAdvanceSettings {
    CompliantStepSettings step;
    CompliantErrorLimits error;
    double initial_trial_dt_s{5e-5};
    double maximum_trial_dt_s{5e-5};
    // Floor on the comparison interval; accepted physical half-steps are h/2.
    // A smaller final remainder may be attempted once, but never subdivided.
    double minimum_trial_dt_s{1e-9};
    unsigned maximum_trials{65536};
};
struct CompliantErrorEstimate {
    double position_m{}, velocity_m_s{}, bond_strain{}, damping_work_j{}, normalized{};
};
enum class CompliantAdvanceFailure { None, TrialBudget, StepLimit, IntervalBalance };
[[nodiscard]] constexpr const char *compliantAdvanceFailureName(CompliantAdvanceFailure f) {
    switch (f) {
    case CompliantAdvanceFailure::None: return "none";
    case CompliantAdvanceFailure::TrialBudget: return "trial budget";
    case CompliantAdvanceFailure::StepLimit: return "minimum trial interval";
    case CompliantAdvanceFailure::IntervalBalance: return "interval balance";
    }
    return "unknown";
}
struct CompliantAdvanceResult {
    // Ledgers/counters are unpublished diagnostics unless step.balance.converged.
    CompliantStepResult step;
    CompliantStepResult last_trial;
    CompliantErrorEstimate last_error;
    unsigned trials{}, accepted_segments{}, rejected_segments{};
    double advanced_time_s{}, remaining_time_s{}, last_trial_dt_s{};
    double minimum_accepted_step_s{}, maximum_accepted_error{}, suggested_trial_dt_s{};
    CompliantAdvanceFailure failure{CompliantAdvanceFailure::None};
};
// One common clock and one unchanged contact law. Accept the two actual half
// steps, without extrapolation or state projection. Coarse trials and failed
// intervals never publish state or losses. A caller may reuse suggested_trial_dt_s
// as the next call's initial_trial_dt_s after successful publication.
[[nodiscard]] CompliantAdvanceResult tryCompliantAdvance(ActiveMatter &matter, double dt_s,
    const CompliantAdvanceSettings &settings, const Vec3 &gravity_m_s2 = {}, CoupledSphereState *sphere = nullptr);
}
