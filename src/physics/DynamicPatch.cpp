#include "physics/DynamicPatch.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace banjo {
namespace {

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

double component(const Vec3 &value, unsigned axis) {
    return axis == 0 ? value.x : axis == 1 ? value.y : value.z;
}

void setComponent(Vec3 &value, unsigned axis, double entry) {
    if (axis == 0)
        value.x = entry;
    else if (axis == 1)
        value.y = entry;
    else
        value.z = entry;
}

SymmetricTensor3 strainColumn(Vec3 gradient, unsigned axis) {
    if (axis == 0)
        return {gradient.x, 0, 0, gradient.y * .5, 0, gradient.z * .5};
    if (axis == 1)
        return {0, gradient.y, 0, gradient.x * .5, gradient.z * .5, 0};
    return {0, 0, gradient.z, 0, gradient.y * .5, gradient.x * .5};
}

Vec3 stressTimes(const SymmetricTensor3 &stress, Vec3 gradient) {
    return {stress.xx * gradient.x + stress.xy * gradient.y + stress.zx * gradient.z,
            stress.xy * gradient.x + stress.yy * gradient.y + stress.yz * gradient.z,
            stress.zx * gradient.x + stress.yz * gradient.y + stress.zz * gradient.z};
}

void require(bool condition, const char *message) {
    if (!condition)
        throw std::invalid_argument(message);
}

} // namespace

DynamicPatch::DynamicPatch(PatchDefinition definition, DynamicPatchOptions options)
    : patch_(std::move(definition)), options_(options) {
    require(std::isfinite(options_.stability_safety_factor) &&
                options_.stability_safety_factor > 0 && options_.stability_safety_factor <= 1,
            "Invalid dynamic stability safety factor");
    require(std::isfinite(options_.maximum_displacement_gradient_norm) &&
                options_.maximum_displacement_gradient_norm > 0 &&
                options_.maximum_displacement_gradient_norm <= .25,
            "Invalid dynamic displacement-gradient limit");
    require(std::isfinite(options_.maximum_time_step_s) && options_.maximum_time_step_s > 0 &&
                options_.maximum_time_step_s <= 1,
            "Invalid dynamic time-step bound");
    require(options_.integrator == DynamicPatchIntegrator::SymplecticEuler ||
                options_.integrator == DynamicPatchIntegrator::VelocityVerlet,
            "Invalid dynamic patch integrator");
    state_.velocities_m_s.resize(patch_.state_.displacements_m.size());
    compileStabilityBound();
    accepted_evaluation_ = std::make_shared<const PatchEvaluation>(patch_.evaluateFrom(
        patch_.state_, patch_.state_.displacements_m, options_.maximum_displacement_gradient_norm));
}

DynamicPatch::Checkpoint DynamicPatch::checkpoint() const {
    return {patch_.state_, state_, accepted_evaluation_};
}

void DynamicPatch::restoreCheckpoint(Checkpoint saved) noexcept {
    patch_.state_ = std::move(saved.patch);
    state_ = std::move(saved.dynamic);
    accepted_evaluation_ = std::move(saved.evaluation);
}

bool finiteTensor(const SymmetricTensor3 &value) {
    return std::isfinite(value.xx) && std::isfinite(value.yy) &&
           std::isfinite(value.zz) && std::isfinite(value.xy) &&
           std::isfinite(value.yz) && std::isfinite(value.zx);
}

double tensorNorm(const SymmetricTensor3 &value) {
    return std::sqrt(value.xx * value.xx + value.yy * value.yy + value.zz * value.zz +
                     2. * (value.xy * value.xy + value.yz * value.yz + value.zx * value.zx));
}

bool close(double captured, double recomputed, double relative_tolerance) {
    return std::isfinite(captured) && std::isfinite(recomputed) &&
           std::abs(captured - recomputed) <=
               relative_tolerance * std::max({1., std::abs(captured), std::abs(recomputed)});
}

bool close(const SymmetricTensor3 &captured, const SymmetricTensor3 &recomputed,
           double relative_tolerance) {
    if (!finiteTensor(captured) || !finiteTensor(recomputed)) return false;
    const SymmetricTensor3 difference{
        captured.xx - recomputed.xx, captured.yy - recomputed.yy,
        captured.zz - recomputed.zz, captured.xy - recomputed.xy,
        captured.yz - recomputed.yz, captured.zx - recomputed.zx};
    return tensorNorm(difference) <=
           relative_tolerance * std::max({1., tensorNorm(captured), tensorNorm(recomputed)});
}

DynamicPatch::PreparedRestore DynamicPatch::prepareRestore(
    const PatchState &patch, const DynamicPatchState &dynamic,
    const PatchEvaluation &captured_evaluation) const {
    const std::size_t nodes = patch_.definition_.reference_positions_m.size();
    require(patch.displacements_m.size() == nodes &&
                patch.last_nodal_forces_n.size() == nodes &&
                patch.material_points.size() == patch_.definition_.elements.size() &&
                dynamic.velocities_m_s.size() == nodes,
            "Dynamic snapshot layout differs from patch");
    require(patch.revision == dynamic.revision,
            "Dynamic snapshot revisions disagree");
    require(std::isfinite(dynamic.time_s) && dynamic.time_s >= 0 &&
                std::isfinite(dynamic.accumulated_external_force_work_j) &&
                finite(dynamic.accumulated_support_impulse_n_s) &&
                std::isfinite(patch.accumulated_trapezoidal_external_work_j) &&
                std::isfinite(patch.accumulated_backward_euler_external_work_j),
            "Dynamic snapshot clock or work ledger is invalid");
    for (std::size_t i = 0; i < nodes; ++i) {
        require(finite(patch.displacements_m[i]) && length(patch.displacements_m[i]) <= 1000 &&
                    finite(patch.last_nodal_forces_n[i]) &&
                    length(patch.last_nodal_forces_n[i]) <= 1.e12 &&
                    finite(dynamic.velocities_m_s[i]) &&
                    length(dynamic.velocities_m_s[i]) <= 1.e6,
                "Dynamic snapshot nodal state is invalid");
        for (unsigned axis = 0; axis < 3; ++axis)
            require(!patch_.definition_.fixed_components[i][axis] ||
                        (component(patch.displacements_m[i], axis) == 0 &&
                         component(dynamic.velocities_m_s[i], axis) == 0),
                    "Dynamic snapshot moves a fixed component");
    }
    auto evaluation = patch_.evaluateFrom(
        patch, patch.displacements_m, options_.maximum_displacement_gradient_norm);
    require(evaluation.responses.size() == patch.material_points.size(),
            "Dynamic snapshot response layout differs from material history");
    for (std::size_t i = 0; i < evaluation.responses.size(); ++i)
        require(evaluation.responses[i].state == patch.material_points[i],
                "Dynamic snapshot material history disagrees with deformation");
    require(captured_evaluation.internal_forces_n.size() == nodes &&
                captured_evaluation.responses.size() == patch.material_points.size(),
            "Dynamic snapshot accepted cache layout differs from patch");
    require(std::isfinite(captured_evaluation.stored_free_energy_j) &&
                std::isfinite(captured_evaluation.plastic_dissipation_j) &&
                std::isfinite(captured_evaluation.backward_euler_work_excess_j) &&
                std::isfinite(captured_evaluation.maximum_displacement_gradient_norm) &&
                close(captured_evaluation.stored_free_energy_j,
                      evaluation.stored_free_energy_j, 1.e-12) &&
                close(captured_evaluation.plastic_dissipation_j,
                      evaluation.plastic_dissipation_j, 1.e-12) &&
                close(captured_evaluation.maximum_displacement_gradient_norm,
                      evaluation.maximum_displacement_gradient_norm, 1.e-12),
            "Dynamic snapshot accepted energy cache disagrees with state");
    for (std::size_t i = 0; i < nodes; ++i) {
        require(finite(captured_evaluation.internal_forces_n[i]),
                "Dynamic snapshot accepted force cache is nonfinite");
        const double scale = std::max(1.0, length(evaluation.internal_forces_n[i]));
        require(length(captured_evaluation.internal_forces_n[i] -
                       evaluation.internal_forces_n[i]) <= 1.e-11 * scale,
                "Dynamic snapshot accepted force cache disagrees with state");
    }
    for (std::size_t i = 0; i < captured_evaluation.responses.size(); ++i) {
        require(captured_evaluation.responses[i].state == patch.material_points[i],
                "Dynamic snapshot accepted response cache disagrees with history");
        require(close(captured_evaluation.responses[i].stress_pa,
                      evaluation.responses[i].stress_pa, 1.e-11) &&
                    close(captured_evaluation.responses[i].stored_free_energy_j_m3,
                          evaluation.responses[i].stored_free_energy_j_m3, 1.e-12) &&
                    close(captured_evaluation.responses[i].plastic_dissipation_j_m3,
                          evaluation.responses[i].plastic_dissipation_j_m3, 1.e-12) &&
                    std::isfinite(
                        captured_evaluation.responses[i].backward_euler_work_excess_j_m3),
                "Dynamic snapshot accepted response cache disagrees with state");
        // Tangent columns, yielded, and backward-Euler excess describe the accepted
        // radial-return path and can legitimately differ from a zero-increment
        // reevaluation. They are retained for exact snapshots but are not consumed
        // by continuation; bound their numeric representation rather than claiming
        // they are reconstructible from persistent J2 history.
        for (const auto &column : captured_evaluation.responses[i].tangent_columns)
            require(finiteTensor(column) && tensorNorm(column) <= 1.e18,
                    "Dynamic snapshot accepted tangent cache is nonfinite");
    }
    // All caller-controlled layouts and values have been checked before these
    // allocations. Construction failure therefore leaves the live patch untouched.
    auto cache = std::make_shared<const PatchEvaluation>(captured_evaluation);
    return {patch, dynamic, std::move(cache)};
}

void DynamicPatch::commitRestore(PreparedRestore prepared) noexcept {
    patch_.state_ = std::move(prepared.patch);
    state_ = std::move(prepared.dynamic);
    accepted_evaluation_ = std::move(prepared.evaluation);
}

void DynamicPatch::compileStabilityBound() {
    std::vector<std::array<double, 9>> stiffness(patch_.tangent_block_columns_.size());
    for (std::size_t e = 0; e < patch_.geometry_.size(); ++e) {
        const auto &geometry = patch_.geometry_[e];
        const auto &tet = patch_.definition_.elements[e];
        const auto response =
            evaluateSmallStrain(patch_.definition_.materials[tet.material].law, J2State{}, {});
        for (unsigned i = 0; i < 4; ++i) {
            for (unsigned a = 0; a < 3; ++a) {
                if (patch_.definition_.fixed_components[tet.nodes[i]][a])
                    continue;
                for (unsigned j = 0; j < 4; ++j) {
                    for (unsigned b = 0; b < 3; ++b) {
                        if (patch_.definition_.fixed_components[tet.nodes[j]][b])
                            continue;
                        const auto stress = applySmallStrainTangent(
                            response, strainColumn(geometry.gradients[j], b));
                        const Vec3 force =
                            geometry.volume * stressTimes(stress, geometry.gradients[i]);
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
            if (patch_.definition_.fixed_components[node][axis])
                continue;
            double absolute_sum = 0;
            for (std::size_t block = patch_.tangent_block_row_offsets_[node];
                 block < patch_.tangent_block_row_offsets_[node + 1]; ++block) {
                const unsigned column_node = patch_.tangent_block_columns_[block];
                for (unsigned column_axis = 0; column_axis < 3; ++column_axis) {
                    if (!patch_.definition_.fixed_components[column_node][column_axis])
                        absolute_sum += std::abs(stiffness[block][axis * 3 + column_axis]);
                }
            }
            eigenvalue_bound_s2_ =
                std::max(eigenvalue_bound_s2_, absolute_sum / patch_.nodal_masses_[node]);
        }
    }
    require(std::isfinite(eigenvalue_bound_s2_) && eigenvalue_bound_s2_ >= 0,
            "Nonfinite dynamic stiffness bound");
    stable_time_step_limit_s_ = eigenvalue_bound_s2_ > 0 ? options_.stability_safety_factor * 2 /
                                                               std::sqrt(eigenvalue_bound_s2_)
                                                         : options_.maximum_time_step_s;
    stable_time_step_limit_s_ = std::min(stable_time_step_limit_s_, options_.maximum_time_step_s);
}

void DynamicPatch::setVelocitiesMPerS(const std::vector<Vec3> &velocities) {
    require(state_.revision == 0 && state_.time_s == 0 && patch_.state_.revision == 0,
            "Dynamic velocity initial condition cannot change after stepping");
    require(velocities.size() == state_.velocities_m_s.size(),
            "Dynamic velocity count differs from nodes");
    for (std::size_t i = 0; i < velocities.size(); ++i) {
        require(finite(velocities[i]) && length(velocities[i]) <= 1.e6, "Invalid dynamic velocity");
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
    const auto &evaluation = *accepted_evaluation_;
    result.stored_free_energy_j = evaluation.stored_free_energy_j;
    result.plastic_dissipation_j = evaluation.plastic_dissipation_j;
    result.accumulated_external_force_work_j = state_.accumulated_external_force_work_j;
    result.linear_momentum_kg_m_s = linearMomentum(state_.velocities_m_s);
    result.maximum_displacement_gradient_norm = evaluation.maximum_displacement_gradient_norm;
    return result;
}

DynamicPatchReport DynamicPatch::step(double dt, const DynamicPatchLoad &load) {
    return stepImpl(dt, load, {}, {}, {});
}

DynamicPatchReport DynamicPatch::stepImpl(
    double dt, const DynamicPatchLoad &load,
    const std::function<void(std::vector<Vec3> &, std::vector<Vec3> &)> &velocity_stage,
    const std::function<void(const std::vector<Vec3> &, const DynamicPatchReport &)> &before_commit,
    const std::function<void(std::vector<Vec3> &, const std::vector<Vec3> &)>
        &final_velocity_stage) {
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
            require(finite(force) && length(force) <= 1.e12, "Invalid dynamic nodal force");

        const auto &old_evaluation = *accepted_evaluation_;
        auto candidate_patch = patch_.state_;
        auto candidate_dynamic = state_;
        const double old_kinetic = kineticEnergyJ(state_.velocities_m_s);
        const Vec3 old_momentum = linearMomentum(state_.velocities_m_s);
        Vec3 support_impulse;
        Vec3 external_impulse;
        double external_work = 0;
        const bool velocity_verlet = options_.integrator == DynamicPatchIntegrator::VelocityVerlet;
        const double first_kick_dt = velocity_verlet ? .5 * dt : dt;
        for (std::size_t i = 0; i < nodes; ++i) {
            const Vec3 external =
                load.nodal_forces_n[i] + patch_.nodal_masses_[i] * load.gravity_m_s2;
            external_impulse += dt * external;
            const Vec3 net = external - old_evaluation.internal_forces_n[i];
            for (unsigned axis = 0; axis < 3; ++axis) {
                if (patch_.definition_.fixed_components[i][axis]) {
                    setComponent(candidate_dynamic.velocities_m_s[i], axis, 0);
                    setComponent(candidate_patch.displacements_m[i], axis, 0);
                    setComponent(support_impulse, axis,
                                 component(support_impulse, axis) -
                                     first_kick_dt * component(net, axis));
                } else {
                    const double velocity =
                        component(candidate_dynamic.velocities_m_s[i], axis) +
                        first_kick_dt * component(net, axis) / patch_.nodal_masses_[i];
                    require(std::isfinite(velocity) && std::abs(velocity) <= 1.e6,
                            "Dynamic velocity exceeds finite validity bound");
                    setComponent(candidate_dynamic.velocities_m_s[i], axis, velocity);
                }
            }
        }
        std::vector<Vec3> drift(nodes);
        if (velocity_stage) {
            const auto momentum_before = linearMomentum(candidate_dynamic.velocities_m_s);
            const double energy_before = kineticEnergyJ(candidate_dynamic.velocities_m_s);
            velocity_stage(candidate_dynamic.velocities_m_s, drift);
            require(candidate_dynamic.velocities_m_s.size() == nodes && drift.size() == nodes,
                    "Contact changed velocity layout");
            result.coupling_impulse_n_s =
                linearMomentum(candidate_dynamic.velocities_m_s) - momentum_before;
            result.coupling_kinetic_work_j =
                kineticEnergyJ(candidate_dynamic.velocities_m_s) - energy_before;
        }
        for (std::size_t i = 0; i < nodes; ++i) {
            const Vec3 external =
                load.nodal_forces_n[i] + patch_.nodal_masses_[i] * load.gravity_m_s2;
            if (!velocity_stage)
                drift[i] = dt * candidate_dynamic.velocities_m_s[i];
            require(finite(drift[i]), "Invalid coupled drift");
            const auto velocity = candidate_dynamic.velocities_m_s[i];
            require(finite(velocity) && length(velocity) <= 1.e6, "Invalid coupled velocity");
            for (unsigned axis = 0; axis < 3; ++axis) {
                if (patch_.definition_.fixed_components[i][axis])
                    require(component(velocity, axis) == 0 && component(drift[i], axis) == 0,
                            "Contact moved a fixed component");
                else {
                    const double increment = component(drift[i], axis);
                    setComponent(candidate_patch.displacements_m[i], axis,
                                 component(candidate_patch.displacements_m[i], axis) + increment);
                    external_work += component(external, axis) * increment;
                }
            }
        }
        result.reserved_element_visits = patch_.definition_.elements.size();
        auto candidate_evaluation =
            patch_.evaluateFrom(patch_.state_, candidate_patch.displacements_m,
                                options_.maximum_displacement_gradient_norm);
        if (velocity_verlet) {
            for (std::size_t i = 0; i < nodes; ++i) {
                const Vec3 external =
                    load.nodal_forces_n[i] + patch_.nodal_masses_[i] * load.gravity_m_s2;
                const Vec3 new_net = external - candidate_evaluation.internal_forces_n[i];
                for (unsigned axis = 0; axis < 3; ++axis) {
                    if (patch_.definition_.fixed_components[i][axis]) {
                        setComponent(support_impulse, axis,
                                     component(support_impulse, axis) -
                                         .5 * dt * component(new_net, axis));
                    } else {
                        const double velocity =
                            component(candidate_dynamic.velocities_m_s[i], axis) +
                            .5 * dt * component(new_net, axis) / patch_.nodal_masses_[i];
                        require(std::isfinite(velocity) && std::abs(velocity) <= 1.e6,
                                "Dynamic velocity exceeds finite validity bound");
                        setComponent(candidate_dynamic.velocities_m_s[i], axis, velocity);
                    }
                }
            }
        }
        if (final_velocity_stage) {
            const Vec3 momentum_before = linearMomentum(candidate_dynamic.velocities_m_s);
            const double energy_before = kineticEnergyJ(candidate_dynamic.velocities_m_s);
            final_velocity_stage(candidate_dynamic.velocities_m_s, candidate_patch.displacements_m);
            require(candidate_dynamic.velocities_m_s.size() == nodes,
                    "Final contact stage changed velocity layout");
            for (std::size_t i = 0; i < nodes; ++i) {
                const Vec3 velocity = candidate_dynamic.velocities_m_s[i];
                require(finite(velocity) && length(velocity) <= 1.e6,
                        "Invalid final coupled velocity");
                for (unsigned axis = 0; axis < 3; ++axis)
                    require(!patch_.definition_.fixed_components[i][axis] ||
                                component(velocity, axis) == 0,
                            "Final contact stage moved a fixed component");
            }
            result.coupling_impulse_n_s +=
                linearMomentum(candidate_dynamic.velocities_m_s) - momentum_before;
            result.coupling_kinetic_work_j +=
                kineticEnergyJ(candidate_dynamic.velocities_m_s) - energy_before;
        }
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
            result.linear_momentum_kg_m_s - old_momentum - external_impulse - support_impulse -
            result.coupling_impulse_n_s;
        result.numerical_energy_balance_residual_j =
            (result.kinetic_energy_j - old_kinetic) +
            (result.stored_free_energy_j - old_evaluation.stored_free_energy_j) +
            (result.plastic_dissipation_j - old_evaluation.plastic_dissipation_j) - external_work -
            result.coupling_kinetic_work_j;
        result.maximum_displacement_gradient_norm =
            candidate_evaluation.maximum_displacement_gradient_norm;
        require(std::isfinite(result.numerical_energy_balance_residual_j),
                "Nonfinite dynamic energy balance");
        require(finite(result.linear_momentum_balance_residual_kg_m_s),
                "Nonfinite dynamic momentum balance");
        auto candidate_evaluation_cache =
            std::make_shared<const PatchEvaluation>(std::move(candidate_evaluation));
        if (before_commit)
            before_commit(candidate_patch.displacements_m, result);
        patch_.state_ = std::move(candidate_patch);
        state_ = std::move(candidate_dynamic);
        accepted_evaluation_ = std::move(candidate_evaluation_cache);
        result.accepted = true;
    } catch (const std::exception &error) {
        result.error = error.what();
    }
    return result;
}

} // namespace banjo
