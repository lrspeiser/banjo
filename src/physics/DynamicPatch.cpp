#include "physics/DynamicPatch.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace banjo {
namespace {

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) &&
           std::isfinite(value.z);
}

double component(const Vec3 &value, unsigned axis) {
    return axis == 0 ? value.x : axis == 1 ? value.y : value.z;
}

void setComponent(Vec3 &value, unsigned axis, double entry) {
    if (axis == 0) value.x = entry;
    else if (axis == 1) value.y = entry;
    else value.z = entry;
}

SymmetricTensor3 strainColumn(Vec3 gradient, unsigned axis) {
    if (axis == 0) return {gradient.x, 0, 0, gradient.y * .5, 0, gradient.z * .5};
    if (axis == 1) return {0, gradient.y, 0, gradient.x * .5, gradient.z * .5, 0};
    return {0, 0, gradient.z, 0, gradient.y * .5, gradient.x * .5};
}

Vec3 stressTimes(const SymmetricTensor3 &stress, Vec3 gradient) {
    return {stress.xx * gradient.x + stress.xy * gradient.y + stress.zx * gradient.z,
            stress.xy * gradient.x + stress.yy * gradient.y + stress.yz * gradient.z,
            stress.zx * gradient.x + stress.yz * gradient.y + stress.zz * gradient.z};
}

void require(bool condition, const char *message) {
    if (!condition) throw std::invalid_argument(message);
}

} // namespace

DynamicPatch::DynamicPatch(PatchDefinition definition, DynamicPatchOptions options)
    : patch_(std::move(definition)), options_(options) {
    require(std::isfinite(options_.stability_safety_factor) &&
                options_.stability_safety_factor > 0 &&
                options_.stability_safety_factor <= 1,
            "Invalid dynamic stability safety factor");
    require(std::isfinite(options_.maximum_displacement_gradient_norm) &&
                options_.maximum_displacement_gradient_norm > 0 &&
                options_.maximum_displacement_gradient_norm <= .25,
            "Invalid dynamic displacement-gradient limit");
    require(std::isfinite(options_.maximum_time_step_s) &&
                options_.maximum_time_step_s > 0 &&
                options_.maximum_time_step_s <= 1,
            "Invalid dynamic time-step bound");
    state_.velocities_m_s.resize(patch_.state_.displacements_m.size());
    compileStabilityBound();
}

void DynamicPatch::compileStabilityBound() {
    std::vector<std::array<double, 9>> stiffness(
        patch_.tangent_block_columns_.size());
    for (std::size_t e = 0; e < patch_.geometry_.size(); ++e) {
        const auto &geometry = patch_.geometry_[e];
        const auto &tet = patch_.definition_.elements[e];
        const auto response = evaluateSmallStrain(
            patch_.definition_.materials[tet.material].law, J2State{}, {});
        for (unsigned i = 0; i < 4; ++i) {
            for (unsigned a = 0; a < 3; ++a) {
                if (patch_.definition_.fixed_components[tet.nodes[i]][a]) continue;
                for (unsigned j = 0; j < 4; ++j) {
                    for (unsigned b = 0; b < 3; ++b) {
                        if (patch_.definition_.fixed_components[tet.nodes[j]][b]) continue;
                        const auto stress = applySmallStrainTangent(
                            response, strainColumn(geometry.gradients[j], b));
                        const Vec3 force = geometry.volume *
                            stressTimes(stress, geometry.gradients[i]);
                        const std::size_t block = geometry.tangent_block_indices[i * 4 + j];
                        stiffness[block][a * 3 + b] += component(force, a);
                    }
                }
            }
        }
    }
    eigenvalue_bound_s2_ = 0;
    for (std::size_t node = 0; node < patch_.nodal_masses_.size(); ++node) {
        for (unsigned axis = 0; axis < 3; ++axis) {
            if (patch_.definition_.fixed_components[node][axis]) continue;
            double absolute_sum = 0;
            for (std::size_t block = patch_.tangent_block_row_offsets_[node];
                 block < patch_.tangent_block_row_offsets_[node + 1]; ++block) {
                const unsigned column_node = patch_.tangent_block_columns_[block];
                for (unsigned column_axis = 0; column_axis < 3; ++column_axis) {
                    if (!patch_.definition_.fixed_components[column_node][column_axis])
                        absolute_sum += std::abs(stiffness[block][axis * 3 + column_axis]);
                }
            }
            eigenvalue_bound_s2_ = std::max(
                eigenvalue_bound_s2_, absolute_sum / patch_.nodal_masses_[node]);
        }
    }
    require(std::isfinite(eigenvalue_bound_s2_) && eigenvalue_bound_s2_ >= 0,
            "Nonfinite dynamic stiffness bound");
    stable_time_step_limit_s_ = eigenvalue_bound_s2_ > 0
        ? options_.stability_safety_factor * 2 / std::sqrt(eigenvalue_bound_s2_)
        : options_.maximum_time_step_s;
    stable_time_step_limit_s_ = std::min(stable_time_step_limit_s_,
                                         options_.maximum_time_step_s);
}

void DynamicPatch::setVelocitiesMPerS(const std::vector<Vec3> &velocities) {
    require(state_.revision == 0 && state_.time_s == 0 && patch_.state_.revision == 0,
            "Dynamic velocity initial condition cannot change after stepping");
    require(velocities.size() == state_.velocities_m_s.size(),
            "Dynamic velocity count differs from nodes");
    for (std::size_t i = 0; i < velocities.size(); ++i) {
        require(finite(velocities[i]) && length(velocities[i]) <= 1.e6,
                "Invalid dynamic velocity");
        for (unsigned axis = 0; axis < 3; ++axis)
            require(!patch_.definition_.fixed_components[i][axis] ||
                        component(velocities[i], axis) == 0,
                    "Nonzero velocity on fixed component");
    }
    state_.velocities_m_s = velocities;
}

double DynamicPatch::kineticEnergyJ(const std::vector<Vec3> &velocities) const {
    double energy = 0;
    for (std::size_t i = 0; i < velocities.size(); ++i)
        energy += .5 * patch_.nodal_masses_[i] * lengthSquared(velocities[i]);
    return energy;
}

Vec3 DynamicPatch::linearMomentum(const std::vector<Vec3> &velocities) const {
    Vec3 momentum;
    for (std::size_t i = 0; i < velocities.size(); ++i)
        momentum += patch_.nodal_masses_[i] * velocities[i];
    return momentum;
}

DynamicPatchReport DynamicPatch::report() const {
    DynamicPatchReport result;
    result.accepted = true;
    result.stable_time_step_limit_s = stable_time_step_limit_s_;
    result.stiffness_mass_eigenvalue_bound_s2 = eigenvalue_bound_s2_;
    result.kinetic_energy_j = kineticEnergyJ(state_.velocities_m_s);
    const auto evaluation = patch_.evaluateFrom(
        patch_.state_, patch_.state_.displacements_m,
        options_.maximum_displacement_gradient_norm);
    result.stored_free_energy_j = evaluation.stored_free_energy_j;
    result.plastic_dissipation_j = evaluation.plastic_dissipation_j;
    result.accumulated_external_force_work_j =
        state_.accumulated_external_force_work_j;
    result.linear_momentum_kg_m_s = linearMomentum(state_.velocities_m_s);
    result.maximum_displacement_gradient_norm =
        evaluation.maximum_displacement_gradient_norm;
    return result;
}

DynamicPatchReport DynamicPatch::step(double dt, const DynamicPatchLoad &load) {
    DynamicPatchReport result;
    result.time_step_s = dt;
    result.stable_time_step_limit_s = stable_time_step_limit_s_;
    result.stiffness_mass_eigenvalue_bound_s2 = eigenvalue_bound_s2_;
    try {
        const std::size_t nodes = patch_.state_.displacements_m.size();
        require(std::isfinite(dt) && dt > 0 && dt <= options_.maximum_time_step_s,
                "Invalid dynamic time step");
        require(dt <= stable_time_step_limit_s_,
                "Dynamic time step exceeds cached stability limit");
        require(load.nodal_forces_n.size() == nodes,
                "Dynamic nodal-force count differs from nodes");
        require(finite(load.gravity_m_s2) && length(load.gravity_m_s2) <= 1.e6,
                "Invalid dynamic gravity");
        for (Vec3 force : load.nodal_forces_n)
            require(finite(force) && length(force) <= 1.e12,
                    "Invalid dynamic nodal force");

        const auto old_evaluation = patch_.evaluateFrom(
            patch_.state_, patch_.state_.displacements_m,
            options_.maximum_displacement_gradient_norm);
        auto candidate_patch = patch_.state_;
        auto candidate_dynamic = state_;
        const double old_kinetic = kineticEnergyJ(state_.velocities_m_s);
        const Vec3 old_momentum = linearMomentum(state_.velocities_m_s);
        Vec3 support_impulse;
        Vec3 external_impulse;
        double external_work = 0;
        for (std::size_t i = 0; i < nodes; ++i) {
            const Vec3 external = load.nodal_forces_n[i] +
                patch_.nodal_masses_[i] * load.gravity_m_s2;
            external_impulse += dt * external;
            const Vec3 net = external - old_evaluation.internal_forces_n[i];
            for (unsigned axis = 0; axis < 3; ++axis) {
                if (patch_.definition_.fixed_components[i][axis]) {
                    setComponent(candidate_dynamic.velocities_m_s[i], axis, 0);
                    setComponent(candidate_patch.displacements_m[i], axis, 0);
                    setComponent(support_impulse, axis,
                        component(support_impulse, axis) - dt * component(net, axis));
                } else {
                    const double velocity = component(candidate_dynamic.velocities_m_s[i], axis) +
                        dt * component(net, axis) / patch_.nodal_masses_[i];
                    require(std::isfinite(velocity) && std::abs(velocity) <= 1.e6,
                            "Dynamic velocity exceeds finite validity bound");
                    setComponent(candidate_dynamic.velocities_m_s[i], axis, velocity);
                    const double increment = dt * velocity;
                    setComponent(candidate_patch.displacements_m[i], axis,
                        component(candidate_patch.displacements_m[i], axis) + increment);
                    external_work += component(external, axis) * increment;
                }
            }
        }
        const auto candidate_evaluation = patch_.evaluateFrom(
            patch_.state_, candidate_patch.displacements_m,
            options_.maximum_displacement_gradient_norm);
        for (std::size_t e = 0; e < candidate_patch.material_points.size(); ++e)
            candidate_patch.material_points[e] = candidate_evaluation.responses[e].state;
        candidate_patch.last_nodal_forces_n = load.nodal_forces_n;
        require(candidate_patch.revision < std::numeric_limits<std::uint64_t>::max() &&
                    candidate_dynamic.revision < std::numeric_limits<std::uint64_t>::max(),
                "Dynamic revision limit reached");
        ++candidate_patch.revision;
        candidate_dynamic.time_s += dt;
        require(std::isfinite(candidate_dynamic.time_s), "Nonfinite dynamic time");
        candidate_dynamic.accumulated_external_force_work_j += external_work;
        candidate_dynamic.accumulated_support_impulse_n_s += support_impulse;
        ++candidate_dynamic.revision;
        require(std::isfinite(external_work) &&
                    std::isfinite(candidate_dynamic.accumulated_external_force_work_j),
                "Nonfinite dynamic external-work ledger");
        require(finite(support_impulse) &&
                    finite(candidate_dynamic.accumulated_support_impulse_n_s),
                "Nonfinite dynamic support-impulse ledger");

        result.kinetic_energy_j = kineticEnergyJ(candidate_dynamic.velocities_m_s);
        result.stored_free_energy_j = candidate_evaluation.stored_free_energy_j;
        result.plastic_dissipation_j = candidate_evaluation.plastic_dissipation_j;
        result.external_force_work_increment_j = external_work;
        result.accumulated_external_force_work_j =
            candidate_dynamic.accumulated_external_force_work_j;
        result.support_impulse_n_s = support_impulse;
        result.linear_momentum_kg_m_s = linearMomentum(candidate_dynamic.velocities_m_s);
        result.linear_momentum_balance_residual_kg_m_s =
            result.linear_momentum_kg_m_s - old_momentum - external_impulse -
            support_impulse;
        result.numerical_energy_balance_residual_j =
            (result.kinetic_energy_j - old_kinetic) +
            (result.stored_free_energy_j - old_evaluation.stored_free_energy_j) +
            (result.plastic_dissipation_j - old_evaluation.plastic_dissipation_j) -
            external_work;
        result.maximum_displacement_gradient_norm =
            candidate_evaluation.maximum_displacement_gradient_norm;
        require(std::isfinite(result.numerical_energy_balance_residual_j),
                "Nonfinite dynamic energy balance");
        require(finite(result.linear_momentum_balance_residual_kg_m_s),
                "Nonfinite dynamic momentum balance");
        patch_.state_ = std::move(candidate_patch);
        state_ = std::move(candidate_dynamic);
        result.accepted = true;
    } catch (const std::exception &error) {
        result.error = error.what();
    }
    return result;
}

} // namespace banjo
