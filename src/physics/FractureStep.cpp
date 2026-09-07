#include "physics/FractureStep.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace banjo {
namespace {

struct MatterSnapshot {
    std::vector<ActiveNodeState> nodes;
    std::vector<ActiveBondState> bonds;
    bool connectivity_dirty{};
    CoupledSphereState sphere{};
};

MatterSnapshot capture(const ActiveMatter &matter, const CoupledSphereState *sphere) {
    return {matter.nodes, matter.bonds, matter.connectivity_dirty,
            sphere ? *sphere : CoupledSphereState{}};
}

void restore(const MatterSnapshot &snapshot, ActiveMatter &matter, CoupledSphereState *sphere) {
    matter.nodes = snapshot.nodes;
    matter.bonds = snapshot.bonds;
    matter.connectivity_dirty = snapshot.connectivity_dirty;
    if (sphere) *sphere = snapshot.sphere;
}

void accumulateSegment(FractureStepResult &result, const ConservativeStepResult &trial) {
    ++result.accepted_segments;
    result.newton_iterations += trial.iterations;
    result.linear_iterations += trial.linear_iterations;
    result.energy_residual_j += trial.energy_residual_j;
    result.normal_contact_loss_j += trial.normal_contact_loss_j;
    result.linear_momentum_residual_kg_m_s += trial.linear_momentum_residual_kg_m_s;
    result.angular_momentum_residual_kg_m2_s += trial.angular_momentum_residual_kg_m2_s;
    result.support_impulse_kg_m_s += trial.support_impulse_kg_m_s;
    result.support_angular_impulse_kg_m2_s += trial.support_angular_impulse_kg_m2_s;
    result.maximum_penetration_m = std::max(result.maximum_penetration_m, trial.maximum_penetration_m);
}

void accumulateFailureSummary(FractureStepResult &result, const BondFailureSummary &summary) {
    result.broken_bonds += summary.newly_broken;
    result.removed_bond_energy_j += summary.removed_elastic_energy_j;
    result.maximum_tensile_stretch =
        std::max(result.maximum_tensile_stretch, summary.maximum_tensile_stretch);
    result.maximum_compressive_strain =
        std::max(result.maximum_compressive_strain, summary.maximum_compressive_strain);
    result.maximum_shear_strain =
        std::max(result.maximum_shear_strain, summary.maximum_shear_strain);
}

} // namespace

FractureStepResult tryFracturingStep(ActiveMatter &matter, double dt_s, const Vec3 &gravity_m_s2,
    CoupledSphereState *sphere, const FractureStepSettings &settings) {
    if (!std::isfinite(dt_s) || dt_s <= 0.0 || settings.maximum_solver_trials == 0U ||
        !std::isfinite(settings.minimum_segment_dt_s) || settings.minimum_segment_dt_s <= 0.0)
        throw std::invalid_argument("fracturing step requires a positive interval and trial budget");

    FractureStepResult result;
    result.live_bonds = matter.bonds.size() - countBrokenBonds(matter);
    result.smallest_segment_dt_s = dt_s;

    const MatterSnapshot frame = capture(matter, sphere);
    const auto abandon = [&](FractureStepFailure failure) {
        restore(frame, matter, sphere);
        FractureStepResult rejected;
        rejected.failure = failure;
        rejected.last_trial = result.last_trial;
        rejected.solver_trials = result.solver_trials;
        rejected.discarded_trials = result.discarded_trials;
        rejected.bisections = result.bisections;
        rejected.discarded_newton_iterations = result.discarded_newton_iterations;
        rejected.discarded_linear_iterations = result.discarded_linear_iterations;
        rejected.live_bonds = frame.bonds.size() - countBrokenBonds(matter);
        rejected.smallest_segment_dt_s = result.smallest_segment_dt_s;
        return rejected;
    };

    double remaining = dt_s;
    double segment_dt = dt_s;
    std::vector<std::uint32_t> removed;
    std::vector<BondFailureMode> removed_modes;

    // A segment ends either at the frame boundary or at a bond removal. Each
    // discarded trial removes at least one bond, so the loop terminates; the
    // trial budget caps a cascade that would otherwise re-solve many times.
    while (remaining > 0.0) {
        if (result.solver_trials >= settings.maximum_solver_trials)
            return abandon(FractureStepFailure::TrialBudgetExhausted);

        // Peaks describe this interval alone, sampled at both of its endpoints,
        // exactly as the explicit lane samples each of its substeps. The step is
        // solved between the two samples, so the strain history belongs to an
        // accepted state at each end and never to a solver iterate.
        resetBondStrainPeaks(matter);
        accumulateBondStrainPeaks(matter);
        const MatterSnapshot segment = capture(matter, sphere);
        const double trial_dt = std::min(segment_dt, remaining);
        ++result.solver_trials;
        const auto trial = tryConservativeStep(matter, trial_dt, gravity_m_s2, sphere, settings.solver);
        result.last_trial = trial;
        if (!trial.converged) return abandon(FractureStepFailure::SolverRejected);

        accumulateBondStrainPeaks(matter);
        removed.clear();
        const auto summary = applyBondFailure(matter, &removed);

        if (summary.newly_broken == 0U) {
            accumulateSegment(result, trial);
            accumulateFailureSummary(result, summary);
            result.smallest_segment_dt_s = std::min(result.smallest_segment_dt_s, trial_dt);
            result.advanced_time_s += trial_dt;
            remaining -= trial_dt;
            // Rounding must not leave a microscopic tail segment behind.
            if (remaining <= 1.0e-12 * dt_s) remaining = 0.0;
            // Grow back toward the frame step after a clean segment.
            segment_dt = std::min(dt_s, 2.0 * segment_dt);
            continue;
        }

        if (settings.timing == BondFailureTiming::EndOfStep) {
            accumulateSegment(result, trial);
            accumulateFailureSummary(result, summary);
            result.smallest_segment_dt_s = std::min(result.smallest_segment_dt_s, trial_dt);
            result.advanced_time_s += trial_dt;
            remaining -= trial_dt;
            // Rounding must not leave a microscopic tail segment behind.
            if (remaining <= 1.0e-12 * dt_s) remaining = 0.0;
            continue;
        }

        // The interval is inadmissible: it was solved with a bond that failed
        // inside it. Record which bonds failed and in which mode, then throw the
        // whole trial away.
        removed_modes.clear();
        removed_modes.reserve(removed.size());
        for (const std::uint32_t bond_index : removed)
            removed_modes.push_back(matter.bonds[bond_index].failure_mode);
        restore(segment, matter, sphere);
        ++result.discarded_trials;
        result.discarded_newton_iterations += trial.iterations;
        result.discarded_linear_iterations += trial.linear_iterations;

        if (settings.timing == BondFailureTiming::BisectedTime &&
            result.bisections < settings.maximum_bisections &&
            0.5 * trial_dt >= settings.minimum_segment_dt_s) {
            // Shrink toward the failure instant rather than removing the bond at
            // the start of a long interval it survived most of.
            segment_dt = 0.5 * trial_dt;
            ++result.bisections;
            continue;
        }

        // Remove at the start of the interval, where the state is the last one
        // that satisfied the criterion, and re-solve the interval without it.
        accumulateFailureSummary(result, removeBondsAtCurrentState(matter, removed, removed_modes));
    }

    result.converged = true;
    result.live_bonds = matter.bonds.size() - countBrokenBonds(matter);
    result.failure_modes = countBondFailureModes(matter);
    return result;
}

} // namespace banjo
