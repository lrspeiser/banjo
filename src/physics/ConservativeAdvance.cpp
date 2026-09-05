#include "physics/ConservativeAdvance.hpp"
#include "physics/ConservativeStepInternal.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "physics/NormalImpact.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace banjo {
namespace {
using Mask = detail::ConservativeContactMask;
bool onSupport(Vec3 p, const ConservativeStepSettings &s) {
    return s.support && insideSupportFootprint(*s.support, p, s.support_half_tangent_m, s.support_half_bitangent_m);
}
Mask touching(const ActiveMatter &matter, const CoupledSphereState *sphere,
              const ConservativeStepSettings &s, double tolerance, bool keep_departing = true) {
    Mask mask;
    mask.support_nodes.resize(matter.nodes.size()); mask.sphere_nodes.resize(matter.nodes.size());
    for (std::size_t i = 0; i < matter.nodes.size(); ++i) {
        const auto p = matter.nodes[i].position_world_m;
        mask.support_nodes[i] = onSupport(p, s) && signedDistanceToPlane(*s.support, p) <= tolerance;
        mask.sphere_nodes[i] = sphere && length(p - sphere->motion.center_of_mass_world_m) - sphere->radius_m <= tolerance;
        if (!keep_departing) {
            if (mask.support_nodes[i] && dot(matter.nodes[i].velocity_m_s, s.support->normal_world) > s.velocity_tolerance_m_s)
                mask.support_nodes[i] = false;
            if (mask.sphere_nodes[i] && dot(matter.nodes[i].velocity_m_s-sphere->motion.linear_velocity_m_s,
                normalized(p-sphere->motion.center_of_mass_world_m)) > s.velocity_tolerance_m_s) mask.sphere_nodes[i] = false;
        }
    }
    mask.sphere_support = sphere && onSupport(sphere->motion.center_of_mass_world_m, s) &&
        signedDistanceToPlane(*s.support, sphere->motion.center_of_mass_world_m) - sphere->radius_m <= tolerance;
    if (!keep_departing && mask.sphere_support && dot(sphere->motion.linear_velocity_m_s, s.support->normal_world) > s.velocity_tolerance_m_s)
        mask.sphere_support = false;
    return mask;
}
double newGap(const ActiveMatter &matter, const CoupledSphereState *sphere,
              const ConservativeStepSettings &s, const Mask &mask) {
    double gap = std::numeric_limits<double>::infinity();
    for (std::size_t i = 0; i < matter.nodes.size(); ++i) {
        const auto p = matter.nodes[i].position_world_m;
        if (!mask.support_nodes[i] && onSupport(p, s)) gap = std::min(gap, signedDistanceToPlane(*s.support, p));
        if (sphere && !mask.sphere_nodes[i]) gap = std::min(gap, length(p - sphere->motion.center_of_mass_world_m) - sphere->radius_m);
    }
    if (sphere && !mask.sphere_support && onSupport(sphere->motion.center_of_mass_world_m, s))
        gap = std::min(gap, signedDistanceToPlane(*s.support, sphere->motion.center_of_mass_world_m) - sphere->radius_m);
    return gap;
}
bool crossedSphere(const ActiveMatter &start, const CoupledSphereState *sphere0,
                   const ActiveMatter &end, const CoupledSphereState *sphere1, const Mask &mask, double tolerance) {
    if (!sphere0) return false;
    for (std::size_t i = 0; i < start.nodes.size(); ++i) if (!mask.sphere_nodes[i]) {
        const Vec3 q0 = start.nodes[i].position_world_m - sphere0->motion.center_of_mass_world_m;
        const Vec3 path = end.nodes[i].position_world_m - sphere1->motion.center_of_mass_world_m - q0;
        const double t = lengthSquared(path) > 0 ? std::clamp(-dot(q0, path) / lengthSquared(path), 0.0, 1.0) : 0;
        if (length(q0 + t*path) < sphere0->radius_m - tolerance) return true;
    }
    return false;
}
MechanicalTotals measure(const ActiveMatter &matter, const CoupledSphereState *sphere, Vec3 gravity) {
    auto result = measureMaterialMechanics(matter, gravity);
    if (sphere) {
        Mat3 inertia;
        for (unsigned i = 0; i < 3; ++i) inertia.m[i][i] = sphere->inertia_kg_m2;
        result += measureRigidMechanics({sphere->motion, sphere->mass_kg, inertia}, gravity);
    }
    return result;
}
bool finite(Vec3 v) { return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z); }
}

ConservativeAdvanceResult tryConservativeAdvance(ActiveMatter &matter, double dt, const Vec3 &gravity,
    CoupledSphereState *sphere, const ConservativeAdvanceSettings &settings) {
    if (!std::isfinite(dt) || dt <= 0 || !finite(gravity) || !matter.asset ||
        settings.maximum_trials == 0 || settings.maximum_substeps == 0 ||
        !std::isfinite(settings.minimum_substep_s) || settings.minimum_substep_s <= 0 ||
        !std::isfinite(settings.event_gap_tolerance_m) || settings.event_gap_tolerance_m <= 0 ||
        settings.event_gap_tolerance_m > settings.step.contact_tolerance_m ||
        !std::isfinite(settings.relative_normal_loss_tolerance) || settings.relative_normal_loss_tolerance < 0 ||
        !std::isfinite(settings.normal_restitution) || settings.normal_restitution < 0 || settings.normal_restitution > 1)
        throw std::invalid_argument("invalid conservative advance settings/state");
    detail::validateConservativeState(matter, dt, gravity, sphere, settings.step);
    ConservativeAdvanceResult result;
    ActiveMatter current = matter;
    CoupledSphereState current_sphere = sphere ? *sphere : CoupledSphereState{};
    const auto before = measure(matter, sphere, gravity);
    const double bulk_kinetic = before.mass_kg > 0 ? .5*lengthSquared(before.linear_momentum_kg_m_s)/before.mass_kg : 0;
    const double energy_scale = std::max(1.0, before.elastic_energy_j +
        (settings.step.support ? before.kinetic_energy_j : std::max(0.0, before.kinetic_energy_j - bulk_kinetic)));
    const double loss_budget = settings.relative_normal_loss_tolerance * energy_scale;
    Vec3 gravity_angular_impulse;
    double remaining = dt;
    while (remaining > 0 && result.substeps < settings.maximum_substeps) {
        const auto impact_mask = touching(current, sphere ? &current_sphere : nullptr, settings.step, settings.event_gap_tolerance_m);
        const auto impact = detail::tryNormalImpact(current, sphere ? &current_sphere : nullptr, impact_mask, settings.step, settings.normal_restitution);
        result.balance.iterations += impact.iterations;
        if (!impact.converged) { result.failure = ConservativeAdvanceFailure::ImpactSolve; return result; }
        result.impact_loss_j += impact.loss_j;
        result.balance.support_impulse_kg_m_s += impact.support_impulse;
        result.balance.support_angular_impulse_kg_m2_s += impact.support_angular_impulse;
        if (impact.applied) ++result.impact_events;
        const auto mask = touching(current, sphere ? &current_sphere : nullptr, settings.step, settings.event_gap_tolerance_m, false);
        const double starting_gap = std::max(0.0,newGap(current, sphere ? &current_sphere : nullptr, settings.step, mask));
        double trial_dt = remaining;
        ActiveMatter candidate;
        CoupledSphereState candidate_sphere;
        ConservativeStepResult accepted;
        bool found = false;
        const auto trial = [&](double h) {
            if (result.trials >= settings.maximum_trials) return false;
            candidate = current; candidate_sphere = current_sphere;
            ++result.trials;
            result.last_trial = detail::tryConservativeStepMasked(candidate, h, gravity,
                sphere ? &candidate_sphere : nullptr, settings.step, &mask);
            result.balance.iterations += result.last_trial.iterations;
            result.balance.linear_iterations += result.last_trial.linear_iterations;
            return result.last_trial.converged;
        };
        while (trial_dt >= settings.minimum_substep_s && result.trials < settings.maximum_trials) {
            if (!trial(trial_dt)) { trial_dt *= .5; continue; }
            double gap = newGap(candidate, sphere ? &candidate_sphere : nullptr, settings.step, mask);
            const bool swept = crossedSphere(current, sphere ? &current_sphere : nullptr, candidate,
                sphere ? &candidate_sphere : nullptr, mask, settings.event_gap_tolerance_m);
            if (gap >= 0 && swept) { trial_dt *= .5; continue; }
            if (gap < 0) {
                // Re-solve from the same starting state while bracketing first
                // arrival. No interpolated positions/velocities are committed.
                double lo = 0, hi = trial_dt, lo_gap = starting_gap, hi_gap = gap;
                bool arrival = false;
                for (unsigned root = 0; root < 80 && result.trials < settings.maximum_trials; ++root) {
                    double guess = lo + (hi-lo)*lo_gap/(lo_gap-hi_gap);
                    // A just-departing contact can have an almost-zero initial
                    // gap yet return later under elastic force. A tiny secant
                    // estimate is not proof that the later root is unresolved.
                    if (!std::isfinite(guess) || guess < settings.minimum_substep_s || guess <= lo || guess >= hi || root % 8 == 7)
                        guess = .5*(lo+hi);
                    if (guess < settings.minimum_substep_s || guess <= lo || guess >= hi) break;
                    if (!trial(guess)) { hi = guess; hi_gap = std::min(hi_gap, -settings.event_gap_tolerance_m); continue; }
                    gap = newGap(candidate, sphere ? &candidate_sphere : nullptr, settings.step, mask);
                    if (gap >= 0 && gap <= settings.event_gap_tolerance_m &&
                        !crossedSphere(current, sphere ? &current_sphere : nullptr, candidate,
                            sphere ? &candidate_sphere : nullptr, mask, settings.event_gap_tolerance_m)) {
                        trial_dt = guess; arrival = true; ++result.event_splits; break;
                    }
                    if (gap >= 0) { lo = guess; lo_gap = gap; } else { hi = guess; hi_gap = gap; }
                }
                if (!arrival) {
                    result.failure = result.trials >= settings.maximum_trials ? ConservativeAdvanceFailure::TrialBudget : ConservativeAdvanceFailure::EventLocation;
                    return result;
                }
            }
            if (result.balance.normal_contact_loss_j + result.last_trial.normal_contact_loss_j > loss_budget) {
                trial_dt *= .5; continue;
            }
            accepted = result.last_trial;
            found = true;
            break;
        }
        if (!found) {
            result.failure = result.trials >= settings.maximum_trials ? ConservativeAdvanceFailure::TrialBudget : ConservativeAdvanceFailure::StepLimit;
            return result;
        }
        const auto sub_before = measure(current, sphere ? &current_sphere : nullptr, gravity);
        const auto sub_after = measure(candidate, sphere ? &candidate_sphere : nullptr, gravity);
        gravity_angular_impulse += cross(.5*trial_dt*(sub_before.mass_first_moment_kg_m + sub_after.mass_first_moment_kg_m), gravity);
        result.balance.normal_contact_loss_j += accepted.normal_contact_loss_j;
        result.balance.support_impulse_kg_m_s += accepted.support_impulse_kg_m_s;
        result.balance.support_angular_impulse_kg_m2_s += accepted.support_angular_impulse_kg_m2_s;
        result.balance.maximum_penetration_m = std::max(result.balance.maximum_penetration_m, accepted.maximum_penetration_m);
        result.balance.constitutive_velocity_residual_m_s = std::max(result.balance.constitutive_velocity_residual_m_s,
            accepted.constitutive_velocity_residual_m_s);
        current = std::move(candidate); current_sphere = candidate_sphere;
        remaining -= trial_dt;
        ++result.substeps;
    }
    if (remaining > 0) { result.failure = ConservativeAdvanceFailure::SubstepBudget; return result; }
    const auto after = measure(current, sphere ? &current_sphere : nullptr, gravity);
    auto &balance = result.balance;
    balance.balance_measured = true;
    balance.energy_residual_j = after.kinetic_energy_j - before.kinetic_energy_j + after.elastic_energy_j - before.elastic_energy_j -
        dot(gravity, after.mass_first_moment_kg_m - before.mass_first_moment_kg_m) + balance.normal_contact_loss_j + result.impact_loss_j;
    const Vec3 gravity_impulse = dt*before.mass_kg*gravity;
    balance.linear_momentum_residual_kg_m_s = after.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s - gravity_impulse - balance.support_impulse_kg_m_s;
    balance.angular_momentum_residual_kg_m2_s = after.angular_momentum_kg_m2_s - before.angular_momentum_kg_m2_s - gravity_angular_impulse - balance.support_angular_impulse_kg_m2_s;
    const double linear_budget = settings.step.relative_momentum_tolerance*std::max({1.0, length(before.linear_momentum_kg_m_s), length(gravity_impulse), length(balance.support_impulse_kg_m_s)});
    const double angular_budget = settings.step.relative_momentum_tolerance*std::max({1.0, length(before.angular_momentum_kg_m2_s), length(gravity_angular_impulse), length(balance.support_angular_impulse_kg_m2_s)});
    balance.converged = std::isfinite(balance.energy_residual_j) && std::abs(balance.energy_residual_j) <= settings.step.relative_energy_tolerance*energy_scale &&
        finite(balance.linear_momentum_residual_kg_m_s) && length(balance.linear_momentum_residual_kg_m_s) <= linear_budget &&
        finite(balance.angular_momentum_residual_kg_m2_s) && length(balance.angular_momentum_residual_kg_m2_s) <= angular_budget &&
        std::isfinite(balance.normal_contact_loss_j) && std::isfinite(result.impact_loss_j) &&
        balance.normal_contact_loss_j <= loss_budget &&
        balance.normal_contact_loss_j >= -settings.step.relative_energy_tolerance*energy_scale &&
        result.impact_loss_j >= -settings.step.relative_energy_tolerance*energy_scale;
    if (balance.converged) {
        matter.nodes = std::move(current.nodes);
        if (sphere) *sphere = current_sphere;
        result.advanced_time_s = dt;
    } else result.failure = ConservativeAdvanceFailure::IntervalBalance;
    return result;
}
}
