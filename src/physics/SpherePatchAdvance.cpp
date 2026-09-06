#include "physics/SpherePatchWorld.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <stdexcept>

namespace banjo {
namespace {
bool positive(double value) {
    return std::isfinite(value) && value > 0;
}
bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}
void require(bool condition, const char *message) {
    if (!condition)
        throw std::invalid_argument(message);
}
double difference(SymmetricTensor3 a, SymmetricTensor3 b) {
    return frobeniusNorm(
        {a.xx - b.xx, a.yy - b.yy, a.zz - b.zz, a.xy - b.xy, a.yz - b.yz, a.zx - b.zx});
}
SpherePatchErrorEstimate compare(const PatchState &coarse, const DynamicPatchState &coarse_dynamic,
                                 const PatchSphere &coarse_sphere, const PatchState &fine,
                                 const DynamicPatchState &fine_dynamic,
                                 const PatchSphere &fine_sphere, const SpherePatchReport &c,
                                 const SpherePatchReport &a, const SpherePatchReport &b,
                                 const SpherePatchErrorEstimate &allowance) {
    SpherePatchErrorEstimate error;
    error.position_m = length(coarse_sphere.center_m - fine_sphere.center_m);
    error.velocity_m_s = std::max(length(coarse_sphere.velocity_m_s - fine_sphere.velocity_m_s),
                                  coarse_sphere.radius_m *
                                      length(coarse_sphere.spin_rad_s - fine_sphere.spin_rad_s));
    for (std::size_t i = 0; i < coarse.displacements_m.size(); ++i) {
        error.position_m =
            std::max(error.position_m, length(coarse.displacements_m[i] - fine.displacements_m[i]));
        error.velocity_m_s = std::max(error.velocity_m_s, length(coarse_dynamic.velocities_m_s[i] -
                                                                 fine_dynamic.velocities_m_s[i]));
    }
    for (std::size_t i = 0; i < coarse.material_points.size(); ++i) {
        const auto &x = coarse.material_points[i];
        const auto &y = fine.material_points[i];
        error.strain =
            std::max({error.strain, difference(x.total_strain, y.total_strain),
                      difference(x.plastic_strain, y.plastic_strain),
                      std::abs(x.equivalent_plastic_strain - y.equivalent_plastic_strain)});
    }
    error.energy_disagreement_j = std::max(
        {std::abs(c.sphere_kinetic_energy_j - b.sphere_kinetic_energy_j),
         std::abs(c.material.kinetic_energy_j - b.material.kinetic_energy_j),
         std::abs(c.material.stored_free_energy_j - b.material.stored_free_energy_j),
         std::abs(c.material.plastic_dissipation_j - b.material.plastic_dissipation_j),
         std::abs(c.contact_dissipation_j - a.contact_dissipation_j - b.contact_dissipation_j)});
    error.absolute_energy_residual_j = std::abs(a.numerical_energy_balance_residual_j) +
                                       std::abs(b.numerical_energy_balance_residual_j);
    error.normalized =
        std::max({error.position_m / allowance.position_m,
                  error.velocity_m_s / allowance.velocity_m_s, error.strain / allowance.strain,
                  error.energy_disagreement_j / allowance.energy_disagreement_j,
                  error.absolute_energy_residual_j / allowance.absolute_energy_residual_j});
    return error;
}
} // namespace

SpherePatchAdvanceReport SpherePatchWorld::advance(double duration, const DynamicPatchLoad &load,
                                                   const SpherePatchAdvanceOptions &options,
                                                   Vec3 sphere_force, Vec3 gravity) {
    SpherePatchAdvanceReport out;
    const auto original_sphere = sphere_;
    const auto original_contact = contact_;
    std::optional<DynamicPatch::Checkpoint> original;
    try {
        const auto &e = options.error;
        require(positive(duration) && duration <= 1, "Invalid coupled advance duration (0,1] s");
        out.remaining_time_s = duration;
        require(positive(e.position_m) && positive(e.velocity_m_s) && positive(e.strain) &&
                    positive(e.energy_disagreement_j) && positive(e.absolute_energy_residual_j) &&
                    positive(e.reference_time_s),
                "Invalid coupled advance error limits");
        require(positive(options.minimum_trial_dt_s) && positive(options.initial_trial_dt_s) &&
                    positive(options.maximum_trial_dt_s) && options.maximum_trial_dt_s <= 1 &&
                    options.minimum_trial_dt_s <= options.initial_trial_dt_s &&
                    options.initial_trial_dt_s <= options.maximum_trial_dt_s,
                "Invalid coupled advance time bounds");
        require(std::isfinite(options.contact_error_reserve_fraction) &&
                    options.contact_error_reserve_fraction >= 0 &&
                    options.contact_error_reserve_fraction < 1 &&
                    positive(options.maximum_contact_budget_fraction_per_segment) &&
                    options.maximum_contact_budget_fraction_per_segment <= 1,
                "Invalid coupled advance contact reserve");
        require(options.maximum_step_calls > 0 && options.maximum_step_calls <= 1000000 &&
                    options.maximum_reserved_element_visits > 0 &&
                    options.maximum_reserved_element_visits <= 1000000000 &&
                    options.maximum_geometry_queries > 0 &&
                    options.maximum_geometry_queries <= 1000000000 &&
                    options.maximum_geometry_iterations > 0 &&
                    options.maximum_geometry_iterations <= 1000000000,
                "Invalid coupled advance work budget");
        require(load.nodal_forces_n.size() ==
                        patch_.patch().definition().reference_positions_m.size() &&
                    finite(load.gravity_m_s2) && length(load.gravity_m_s2) <= 1.e6 &&
                    finite(sphere_force) && length(sphere_force) <= 1.e12 && finite(gravity) &&
                    length(gravity) <= 1.e6,
                "Invalid coupled advance load");
        for (Vec3 force : load.nodal_forces_n)
            require(finite(force) && length(force) <= 1.e12, "Invalid coupled advance nodal force");
        const double maximum = std::min(options.maximum_trial_dt_s, patch_.stableTimeStepLimitS());
        require(maximum >= options.minimum_trial_dt_s,
                "Material stability limit is below minimum trial interval");
        const double total_energy_budget =
            e.absolute_energy_residual_j * duration / e.reference_time_s;
        require(positive(total_energy_budget),
                "Coupled advance energy budget is nonfinite or underflowed");
        const SpherePatchErrorEstimate interval_limits{
            e.position_m * duration / e.reference_time_s,
            e.velocity_m_s * duration / e.reference_time_s,
            e.strain * duration / e.reference_time_s,
            e.energy_disagreement_j * duration / e.reference_time_s, total_energy_budget};
        using ErrorField = double SpherePatchErrorEstimate::*;
        const std::array<ErrorField, 5> fields{
            &SpherePatchErrorEstimate::position_m, &SpherePatchErrorEstimate::velocity_m_s,
            &SpherePatchErrorEstimate::strain, &SpherePatchErrorEstimate::energy_disagreement_j,
            &SpherePatchErrorEstimate::absolute_energy_residual_j};
        for (auto field : fields)
            require(positive(interval_limits.*field), "Invalid interval error budget");
        original.emplace(patch_.checkpoint());
        const auto initial_material = patch_.report();
        const double initial_sphere_energy =
            .5 * sphere_.mass_kg * lengthSquared(sphere_.velocity_m_s) +
            .2 * sphere_.mass_kg * sphere_.radius_m * sphere_.radius_m *
                lengthSquared(sphere_.spin_rad_s);
        const auto initial_momentum =
            initial_material.linear_momentum_kg_m_s + sphere_.mass_kg * sphere_.velocity_m_s;
        Vec3 accumulated_support{};
        Vec3 external_force = sphere_force + sphere_.mass_kg * gravity;
        const auto &masses = patch_.patch().nodalMassesKg();
        for (std::size_t i = 0; i < masses.size(); ++i)
            external_force += load.nodal_forces_n[i] + masses[i] * load.gravity_m_s2;
        const std::uint64_t elements = patch_.patch().definition().elements.size();
        double h = std::min(maximum, options.initial_trial_dt_s);
        auto solve = [&](double interval) {
            require(out.step_calls < options.maximum_step_calls,
                    "Coupled advance step-call budget exhausted");
            require(elements <=
                        options.maximum_reserved_element_visits - out.reserved_element_visits,
                    "Coupled advance constitutive-work budget exhausted");
            require(out.geometry_queries < options.maximum_geometry_queries &&
                        out.geometry_iterations < options.maximum_geometry_iterations,
                    "Coupled advance geometry budget exhausted");
            // Reserve a full constitutive pass before calling the step. A
            // rejected pass may visit fewer elements; this is an upper bound.
            out.reserved_element_visits += elements;
            ++out.step_calls;
            contact_.maximum_geometry_queries = static_cast<unsigned>(
                std::min<std::uint64_t>(original_contact.maximum_geometry_queries,
                                        options.maximum_geometry_queries - out.geometry_queries));
            contact_.maximum_geometry_iterations = static_cast<unsigned>(std::min<std::uint64_t>(
                original_contact.maximum_geometry_iterations,
                options.maximum_geometry_iterations - out.geometry_iterations));
            auto report = step(interval, load, sphere_force, gravity);
            out.geometry_queries += report.geometry_queries;
            out.geometry_iterations += report.geometry_iterations;
            out.last_trial = report;
            return report;
        };
        while (out.remaining_time_s > 0) {
            const double unclipped_h = h;
            h = std::min(h, out.remaining_time_s);
            require(
                h * .5 > 0 && patch_.state().time_s + h * .5 > patch_.state().time_s &&
                    (h == out.remaining_time_s || out.remaining_time_s - h < out.remaining_time_s),
                "Coupled advance time resolution exhausted");
            const auto start = patch_.checkpoint();
            const auto start_sphere = sphere_;
            out.last_error = {};
            out.last_error.normalized = std::numeric_limits<double>::infinity();
            const auto c = solve(h);
            std::optional<DynamicPatch::Checkpoint> coarse;
            const auto coarse_sphere = sphere_;
            if (c.accepted)
                coarse.emplace(patch_.checkpoint());
            patch_.restoreCheckpoint(start);
            sphere_ = start_sphere;
            SpherePatchReport a, b;
            SpherePatchErrorEstimate smooth_allowance;
            for (auto field : fields)
                smooth_allowance.*field = (1 - options.contact_error_reserve_fraction) *
                                          (interval_limits.*field) * h / duration;
            if (c.accepted) {
                a = solve(h * .5);
                if (a.accepted) {
                    b = solve(h * .5);
                    if (b.accepted) {
                        // Impulse events need a finite absolute allowance:
                        // their force-splitting error can be O(h), so dividing
                        // every event budget by h prevents convergence. This
                        // reserve changes allocation, never the total budget.
                        auto allowance = smooth_allowance;
                        if ((a.impulse_contacts + b.impulse_contacts + c.impulse_contacts) > 0)
                            for (auto field : fields)
                                allowance.*field += std::min(
                                    std::max(0., options.contact_error_reserve_fraction *
                                                         (interval_limits.*field) -
                                                     out.contact_error_reserve_spent.*field),
                                    options.maximum_contact_budget_fraction_per_segment *
                                        (interval_limits.*field));
                        out.last_error = compare(coarse->patch, coarse->dynamic, coarse_sphere,
                                                 patch_.patch().state(), patch_.state(), sphere_, c,
                                                 a, b, allowance);
                    }
                }
            }
            const bool accept = c.accepted && a.accepted && b.accepted &&
                                std::isfinite(out.last_error.normalized) &&
                                out.last_error.normalized <= 1;
            if (!accept) {
                patch_.restoreCheckpoint(start);
                sphere_ = start_sphere;
                ++out.rejected_segments;
                const double factor =
                    std::isfinite(out.last_error.normalized) && out.last_error.normalized > 1
                        ? std::clamp(.8 / std::sqrt(out.last_error.normalized), .1, .8)
                        : .5;
                const double next = h * factor;
                require(next >= options.minimum_trial_dt_s && next < h,
                        "Coupled advance minimum interval cannot meet geometry/error limits");
                h = next;
                continue;
            }
            ++out.accepted_segments;
            if (out.minimum_accepted_step_s == 0 || h * .5 < out.minimum_accepted_step_s)
                out.minimum_step_error = out.last_error;
            out.minimum_accepted_step_s = out.minimum_accepted_step_s > 0
                                              ? std::min(out.minimum_accepted_step_s, h * .5)
                                              : h * .5;
            out.maximum_accepted_error =
                std::max(out.maximum_accepted_error, out.last_error.normalized);
            out.absolute_energy_residual_j += out.last_error.absolute_energy_residual_j;
            for (auto field : fields) {
                out.accumulated_error.*field += out.last_error.*field;
                out.contact_error_reserve_spent.*field +=
                    std::max(0., out.last_error.*field - smooth_allowance.*field);
            }
            out.contact_energy_reserve_spent_j =
                out.contact_error_reserve_spent.absolute_energy_residual_j;
            out.signed_energy_residual_j +=
                a.numerical_energy_balance_residual_j + b.numerical_energy_balance_residual_j;
            out.contact_dissipation_j += a.contact_dissipation_j + b.contact_dissipation_j;
            out.external_work_j += a.external_work_j + b.external_work_j;
            out.contact_angular_residual_kg_m2_s += a.contact_angular_momentum_residual_kg_m2_s +
                                                    b.contact_angular_momentum_residual_kg_m2_s;
            out.impulse_contacts += a.impulse_contacts + b.impulse_contacts;
            accumulated_support += a.contact_support_impulse_n_s + b.contact_support_impulse_n_s +
                                   a.material.support_impulse_n_s + b.material.support_impulse_n_s;
            out.remaining_time_s = h == out.remaining_time_s ? 0 : out.remaining_time_s - h;
            out.tentative_time_s = duration - out.remaining_time_s;
            const double factor =
                out.last_error.normalized > 0
                    ? std::clamp(.9 / std::sqrt(out.last_error.normalized), .5, 1.5)
                    : 1.5;
            out.suggested_trial_dt_s = std::clamp(h * factor, options.minimum_trial_dt_s, maximum);
            // A short output-boundary remainder is not evidence that the next
            // full interval needs tiny steps. Keep the pre-clipping proposal.
            if (out.remaining_time_s == 0 && h < unclipped_h)
                out.suggested_trial_dt_s =
                    std::clamp(unclipped_h, options.minimum_trial_dt_s, maximum);
            h = out.suggested_trial_dt_s;
        }
        const auto final = patch_.report();
        for (auto field : fields)
            require(std::isfinite(out.accumulated_error.*field) &&
                        out.accumulated_error.*field <= interval_limits.*field,
                    "Coupled advance accumulated error-indicator budget exceeded");
        const double final_sphere_energy =
            .5 * sphere_.mass_kg * lengthSquared(sphere_.velocity_m_s) +
            .2 * sphere_.mass_kg * sphere_.radius_m * sphere_.radius_m *
                lengthSquared(sphere_.spin_rad_s);
        out.plastic_dissipation_increment_j =
            final.plastic_dissipation_j - initial_material.plastic_dissipation_j;
        const double endpoint_residual =
            final_sphere_energy - initial_sphere_energy + final.kinetic_energy_j -
            initial_material.kinetic_energy_j + final.stored_free_energy_j -
            initial_material.stored_free_energy_j + out.plastic_dissipation_increment_j +
            out.contact_dissipation_j - out.external_work_j;
        // Both the uncancelled step ledger and direct endpoint identity must
        // fit the same duration budget; step doubling alone is insufficient.
        require(std::isfinite(out.absolute_energy_residual_j) && std::isfinite(endpoint_residual) &&
                    out.absolute_energy_residual_j <= total_energy_budget &&
                    std::abs(endpoint_residual) <= total_energy_budget,
                "Coupled advance interval energy budget exceeded");
        out.signed_energy_residual_j = endpoint_residual;
        out.momentum_residual_kg_m_s = final.linear_momentum_kg_m_s +
                                       sphere_.mass_kg * sphere_.velocity_m_s - initial_momentum -
                                       duration * external_force - accumulated_support;
        require(finite(out.momentum_residual_kg_m_s), "Nonfinite coupled advance momentum ledger");
        contact_ = original_contact;
        out.advanced_time_s = duration;
        out.accepted = true;
    } catch (const std::exception &error) {
        if (original)
            patch_.restoreCheckpoint(std::move(*original));
        sphere_ = original_sphere;
        contact_ = original_contact;
        out.error = error.what();
    }
    return out;
}
} // namespace banjo
