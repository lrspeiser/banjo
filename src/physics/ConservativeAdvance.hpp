#pragma once
#include "physics/ConservativeStep.hpp"

namespace banjo {
enum class ConservativeAdvanceFailure { None, ImpactSolve, TrialBudget, SubstepBudget, EventLocation, StepLimit, IntervalBalance };
[[nodiscard]] constexpr const char *advanceFailureName(ConservativeAdvanceFailure failure) {
    switch (failure) {
    case ConservativeAdvanceFailure::None: return "none";
    case ConservativeAdvanceFailure::ImpactSolve: return "impact solve";
    case ConservativeAdvanceFailure::TrialBudget: return "trial budget";
    case ConservativeAdvanceFailure::SubstepBudget: return "substep budget";
    case ConservativeAdvanceFailure::EventLocation: return "event location";
    case ConservativeAdvanceFailure::StepLimit: return "minimum step or loss limit";
    case ConservativeAdvanceFailure::IntervalBalance: return "interval balance";
    }
    return "unknown";
}
struct ConservativeAdvanceSettings {
    ConservativeStepSettings step;
    unsigned maximum_trials{2048};
    unsigned maximum_substeps{128};
    double minimum_substep_s{1e-15};
    double event_gap_tolerance_m{1e-14};
    // Bound the raw method's numerical normal loss across the entire requested
    // interval, separately from work lost by the prescribed restitution law.
    double relative_normal_loss_tolerance{1e-8};
    // Explicit contact law, independent of elastic material stiffness.
    double normal_restitution{1};
};
struct ConservativeAdvanceResult {
    ConservativeStepResult balance;
    ConservativeStepResult last_trial;
    unsigned trials{}, substeps{}, event_splits{}, impact_events{};
    double impact_loss_j{};
    double advanced_time_s{};
    ConservativeAdvanceFailure failure{ConservativeAdvanceFailure::None};
};
// Advances all participants on one clock. New contact times are located through
// masked, unpublished trial solves; existing contacts retain their reaction.
// Failure rolls back the whole interval, including otherwise accepted substeps.
// Restitution is prescribed, not material-calibrated. Friction is absent.
[[nodiscard]] ConservativeAdvanceResult tryConservativeAdvance(
    ActiveMatter &matter, double dt_s, const Vec3 &gravity_m_s2 = {},
    CoupledSphereState *sphere = nullptr, const ConservativeAdvanceSettings &settings = {});
}
