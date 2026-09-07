#pragma once

#include "fracture/BondFailure.hpp"
#include "physics/ConservativeStep.hpp"

#include <cstddef>
#include <cstdint>

namespace banjo {

// Fracture for the implicit conservative reference.
//
// The implicit step is transactional: a trial that fails its convergence or
// mechanical audit leaves every input state untouched. Bond failure reuses that
// mechanism. A bond that crosses its failure criterion during a step means the
// step was solved with a bond that should not have been there, so the trial is
// discarded, the bond is removed, and the same interval is solved again against
// the new topology. Fragments are whatever connected components remain; nothing
// here assigns fragment velocities, precuts geometry or adds impulses.
//
// The criterion is evaluated at both endpoints of an interval, the same two
// samples per substep the explicit lane takes. A strain excursion that peaks
// strictly inside an interval and returns below threshold before its end is
// therefore invisible at that step length; that is a resolution limit of the
// step, not of the criterion, and shortening the interval exposes it.
//
// Each conservative trial still runs under the unmodified acceptance budgets.
// Removing a bond is a topology change *between* trials, so it can never widen
// a trial's own energy/momentum/penetration audit. The stored energy the bond
// carried at the instant of removal leaves the ledger and is reported as
// removed_bond_energy_j, exactly as the explicit lane reports it.

// When during a step is a failing bond removed.
enum class BondFailureTiming : std::uint8_t {
    // Keep the bond for the whole interval, then remove it. One solve per step,
    // but the bond carried load while it was already past failure.
    EndOfStep,
    // Discard the interval and re-solve it without the bond, i.e. treat failure
    // as having happened at the start of the interval.
    StepRestart,
    // Halve the interval until the failure is bracketed more tightly, then
    // restart at the shortened interval. Converges the removal instant from
    // above at the cost of extra solves.
    BisectedTime,
};

struct FractureStepSettings {
    ConservativeStepSettings solver{};
    BondFailureTiming timing{BondFailureTiming::StepRestart};
    // Conservative-step trials allowed for one frame, including discarded ones.
    unsigned maximum_solver_trials{64};
    // Interval halvings allowed per frame while locating a failure instant.
    unsigned maximum_bisections{8};
    // An interval at or below this length is not shortened further.
    double minimum_segment_dt_s{1.0e-9};
};

enum class FractureStepFailure : std::uint8_t {
    None,
    // A conservative trial did not converge or did not pass its audits.
    SolverRejected,
    // Failures kept appearing after the allowed number of trials.
    TrialBudgetExhausted,
};

struct FractureStepResult {
    bool converged{};
    FractureStepFailure failure{FractureStepFailure::None};
    // The last conservative trial attempted, converged or not.
    ConservativeStepResult last_trial{};

    unsigned solver_trials{};
    unsigned discarded_trials{};
    unsigned accepted_segments{};
    unsigned bisections{};
    // Summed over accepted segments only; discarded trial work is counted in
    // solver_trials but its iterations are reported separately.
    unsigned newton_iterations{};
    unsigned linear_iterations{};
    unsigned discarded_newton_iterations{};
    unsigned discarded_linear_iterations{};

    std::size_t broken_bonds{};
    std::size_t live_bonds{};
    double removed_bond_energy_j{};
    BondFailureModeCounts failure_modes{};
    double maximum_tensile_stretch{};
    double maximum_compressive_strain{};
    double maximum_shear_strain{};

    // Sums over the accepted segments of this frame.
    double energy_residual_j{};
    double normal_contact_loss_j{};
    Vec3 linear_momentum_residual_kg_m_s{};
    Vec3 angular_momentum_residual_kg_m2_s{};
    Vec3 support_impulse_kg_m_s{};
    Vec3 support_angular_impulse_kg_m2_s{};
    double maximum_penetration_m{};
    double smallest_segment_dt_s{};
    double advanced_time_s{};
};

// Transactional over the whole frame: on failure every node, bond and sphere
// value is exactly what it was on entry, including partially advanced segments.
[[nodiscard]] FractureStepResult tryFracturingStep(
    ActiveMatter &matter, double dt_s, const Vec3 &gravity_m_s2 = {},
    CoupledSphereState *sphere = nullptr, const FractureStepSettings &settings = {});

} // namespace banjo
