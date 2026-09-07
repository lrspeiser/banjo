#include "physics/CohesiveDynamicPatch.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace banjo {
namespace {

class ContactHandoffRequired : public std::runtime_error {
  public:
    ContactHandoffRequired(std::size_t facet, double energy)
        : std::runtime_error("Severed interface retains compression energy; contact handoff required"),
          evidence{facet, energy} {}
    CohesiveContactHandoff evidence;
};

void require(bool condition, const char *message) {
    if (!condition) throw std::invalid_argument(message);
}

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

double component(Vec3 value, unsigned axis) {
    return axis == 0 ? value.x : axis == 1 ? value.y : value.z;
}

void setComponent(Vec3 &value, unsigned axis, double component_value) {
    if (axis == 0)
        value.x = component_value;
    else if (axis == 1)
        value.y = component_value;
    else
        value.z = component_value;
}

} // namespace

struct CohesiveDynamicPatch::CombinedEvaluation {
    std::vector<Vec3> internal_forces_n;
    std::vector<CohesiveFacetState> facet_states;
    std::vector<CorotatedCohesiveFacetState> corotated_facet_states;
    std::vector<bool> fully_separated_facets;
    FractureSeparation separation;
    double bulk_stored_energy_j{};
    double cohesive_stored_energy_j{};
    double plastic_dissipation_j{};
    double fracture_dissipation_j{};
    double fracture_dissipation_increment_j{};
    double maximum_gradient{};
    std::uint64_t tet_evaluations{};
    std::uint64_t facet_evaluations{};
    std::uint64_t nodal_scatters{};
    std::uint64_t polar_iterations{};
    std::uint64_t facet_derivative_evaluations{};
    double maximum_elastic_stretch_norm{};
};

CohesiveDynamicPatch::CohesiveDynamicPatch(
    PatchDefinition definition, std::vector<CohesiveFacetLaw> facet_laws,
    CohesiveDynamicPatchOptions options)
    : topology_(compileFractureTopology(definition)),
      facet_laws_(std::move(facet_laws)), options_(options) {
    require(facet_laws_.size() == topology_.internal_facets.size(),
            "Cohesive dynamic patch law count differs from internal facets");
    require(std::isfinite(options_.stability_safety_factor) &&
                options_.stability_safety_factor > 0 && options_.stability_safety_factor <= 1 &&
                std::isfinite(options_.maximum_time_step_s) &&
                options_.maximum_time_step_s > 0 && options_.maximum_time_step_s <= 1 &&
                std::isfinite(options_.maximum_displacement_gradient_norm) &&
                options_.maximum_displacement_gradient_norm > 0 &&
                options_.maximum_displacement_gradient_norm <= 0.25 &&
                std::isfinite(options_.maximum_absolute_energy_residual_j) &&
                options_.maximum_absolute_energy_residual_j > 0 &&
                options_.maximum_tet_evaluations > 0 &&
                options_.maximum_tet_evaluations <= 100000000,
            "Invalid cohesive dynamic patch options");
    require(options_.kinematics == CohesiveKinematics::SmallDisplacement ||
                options_.kinematics == CohesiveKinematics::Corotated,
            "Unknown cohesive kinematics");
    if (options_.kinematics == CohesiveKinematics::Corotated)
        require(std::isfinite(options_.minimum_deformation_jacobian) &&
                    options_.minimum_deformation_jacobian > 0 &&
                    options_.minimum_deformation_jacobian <= 1 &&
                    std::isfinite(options_.maximum_deformation_gradient_norm) &&
                    options_.maximum_deformation_gradient_norm >= std::sqrt(3.) &&
                    options_.maximum_deformation_gradient_norm <= 100,
                "Invalid corotated cohesive deformation domain");
    require(topology_.tetrahedra.size() <= options_.maximum_tet_evaluations,
            "Cohesive dynamic patch tet-evaluation budget exhausted");

    double bulk_eigenvalue_bound = 0;
    tet_patches_.reserve(topology_.duplicated_definition.elements.size());
    for (std::size_t tet_id = 0; tet_id < topology_.duplicated_definition.elements.size(); ++tet_id) {
        const auto &source_tet = topology_.duplicated_definition.elements[tet_id];
        const auto &law = topology_.duplicated_definition.materials[source_tet.material].law;
        require(law.kind == SmallStrainLawKind::IsotropicElastic ||
                    law.kind == SmallStrainLawKind::OrthotropicElastic,
                "Cohesive dynamic patch currently supports elastic bulk laws only");
        if (options_.kinematics == CohesiveKinematics::Corotated) {
            require(law.kind == SmallStrainLawKind::IsotropicElastic,
                    "Corotated cohesive bulk requires an isotropic elastic descriptor");
            const double e = law.young_modulus_pa[0], nu = law.poisson_xy_yz_zx[0];
            require(nu >= 0, "Corotated cohesive bulk requires nonnegative Lame lambda");
            CorotatedTetLaw objective;
            objective.shear_modulus_pa = e / (2 * (1 + nu));
            objective.lame_lambda_pa = e * nu / ((1 + nu) * (1 - 2 * nu));
            objective.density_kg_m3 = topology_.duplicated_definition.materials[source_tet.material].density_kg_m3;
            objective.minimum_deformation_jacobian = options_.minimum_deformation_jacobian;
            objective.maximum_deformation_gradient_norm = options_.maximum_deformation_gradient_norm;
            corotated_laws_.push_back(objective);
        }
        PatchDefinition local;
        local.materials = topology_.duplicated_definition.materials;
        local.fixed_components.resize(4);
        PatchTet local_tet;
        local_tet.material = source_tet.material;
        for (unsigned i = 0; i < 4; ++i) {
            local.reference_positions_m.push_back(
                topology_.duplicated_definition.reference_positions_m[source_tet.nodes[i]]);
            local.fixed_components[i] =
                topology_.duplicated_definition.fixed_components[source_tet.nodes[i]];
            local_tet.nodes[i] = i;
        }
        local.elements.push_back(local_tet);
        DynamicPatchOptions dynamic_options;
        dynamic_options.stability_safety_factor = 1;
        dynamic_options.maximum_displacement_gradient_norm =
            options_.maximum_displacement_gradient_norm;
        dynamic_options.maximum_time_step_s = options_.maximum_time_step_s;
        DynamicPatch probe(local, dynamic_options);
        bulk_eigenvalue_bound =
            std::max(bulk_eigenvalue_bound, probe.stiffnessMassEigenvalueBoundS2());
        tet_patches_.push_back(std::make_unique<SmallStrainPatch>(std::move(local)));
    }

    std::vector<double> cohesive_row_bound(topology_.local_nodal_masses_kg.size());
    for (std::size_t facet_id = 0; facet_id < topology_.internal_facets.size(); ++facet_id) {
        const auto &facet = topology_.internal_facets[facet_id];
        const auto &law = facet_laws_[facet_id];
        const double damage_opening = law.strength_pa / law.stiffness_pa_per_m;
        const double separation_opening =
            2 * law.fracture_energy_j_m2 / law.strength_pa;
        const double tangential_ratio =
            law.tangential_stiffness_pa_per_m / law.stiffness_pa_per_m;
        const double softening_tangent =
            law.strength_pa / (separation_opening - damage_opening) *
            std::max(1.0, tangential_ratio);
        const double stiffness = std::max({law.stiffness_pa_per_m,
                                           law.tangential_stiffness_pa_per_m,
                                           law.compression_stiffness_pa_per_m,
                                           softening_tangent});
        require(std::isfinite(stiffness) && stiffness > 0,
                "Invalid cohesive dynamic facet stiffness");
        const double contribution =
            2 * std::sqrt(3.0) * stiffness * facet.reference_area_m2 / 3;
        for (unsigned i = 0; i < 3; ++i) {
            cohesive_row_bound[facet.side_a.local_nodes[i]] += contribution;
            cohesive_row_bound[facet.side_b.local_nodes[i]] += contribution;
        }
    }
    double cohesive_eigenvalue_bound = 0;
    for (std::size_t i = 0; i < cohesive_row_bound.size(); ++i) {
        const double mass = topology_.local_nodal_masses_kg[i];
        require(std::isfinite(mass) && mass > 0,
                "Invalid cohesive dynamic local nodal mass");
        cohesive_eigenvalue_bound =
            std::max(cohesive_eigenvalue_bound, cohesive_row_bound[i] / mass);
    }
    const double eigenvalue_bound = bulk_eigenvalue_bound + cohesive_eigenvalue_bound;
    require(std::isfinite(eigenvalue_bound) && eigenvalue_bound >= 0,
            "Cohesive dynamic stiffness bound exceeds numeric range");
    stable_time_step_limit_s_ = eigenvalue_bound > 0
                                    ? options_.stability_safety_factor * 2 /
                                          std::sqrt(eigenvalue_bound)
                                    : options_.maximum_time_step_s;
    stable_time_step_limit_s_ =
        std::min(stable_time_step_limit_s_, options_.maximum_time_step_s);

    const std::size_t nodes = topology_.duplicated_definition.reference_positions_m.size();
    state_.displacements_m.resize(nodes);
    state_.velocities_m_s.resize(nodes);
    if (options_.kinematics == CohesiveKinematics::SmallDisplacement)
        state_.facet_states.resize(facet_laws_.size());
    else {
        state_.corotated_facet_states.resize(facet_laws_.size());
        // Validate immutable compiled topology, law and assembly budgets once.
        (void)evaluateCohesiveAssembly(topology_, state_.displacements_m,
            std::vector<CohesiveFacetState>(facet_laws_.size()), facet_laws_, options_.cohesive);
    }
    accepted_evaluation_ = std::make_shared<const CombinedEvaluation>(
        evaluate(state_.displacements_m, state_.facet_states, state_.corotated_facet_states));
    state_.facet_states = accepted_evaluation_->facet_states;
    state_.corotated_facet_states = accepted_evaluation_->corotated_facet_states;
    state_.fully_separated_facets = accepted_evaluation_->fully_separated_facets;
    state_.separation = accepted_evaluation_->separation;
}

CohesiveDynamicPatch::CombinedEvaluation CohesiveDynamicPatch::evaluate(
    const std::vector<Vec3> &displacements,
    const std::vector<CohesiveFacetState> &facet_states,
    const std::vector<CorotatedCohesiveFacetState> &objective_states) const {
    require(displacements.size() == topology_.duplicated_definition.reference_positions_m.size(),
            "Cohesive dynamic displacement count differs from local nodes");
    CombinedEvaluation out;
    out.internal_forces_n.resize(displacements.size());
    for (std::size_t tet_id = 0; tet_id < tet_patches_.size(); ++tet_id) {
        require(out.tet_evaluations < options_.maximum_tet_evaluations,
                "Cohesive dynamic tet-evaluation budget exhausted");
        const auto &tet = topology_.duplicated_definition.elements[tet_id];
        if (options_.kinematics == CohesiveKinematics::Corotated) {
            std::array<Vec3, 4> reference, current;
            for (unsigned i = 0; i < 4; ++i) {
                reference[i] = topology_.duplicated_definition.reference_positions_m[tet.nodes[i]];
                current[i] = reference[i] + displacements[tet.nodes[i]];
            }
            const auto evaluation = evaluateCorotatedTet(corotated_laws_[tet_id], reference, current);
            double stretch2 = 0;
            for (unsigned row = 0; row < 3; ++row)
                for (unsigned col = 0; col < 3; ++col) {
                    const double value = evaluation.deformation_gradient.m[row][col] - evaluation.rotation.m[row][col];
                    stretch2 += value * value;
                }
            const double stretch = std::sqrt(stretch2);
            require(stretch <= topology_.duplicated_definition.materials[tet.material].law.maximum_total_strain_norm,
                    "Corotated elastic stretch exceeds declared material domain");
            out.maximum_elastic_stretch_norm = std::max(out.maximum_elastic_stretch_norm, stretch);
            ++out.tet_evaluations;
            out.polar_iterations += evaluation.polar_iterations;
            out.bulk_stored_energy_j += evaluation.stored_energy_j;
            for (unsigned i = 0; i < 4; ++i)
                out.internal_forces_n[tet.nodes[i]] += evaluation.internal_forces_n[i];
            continue;
        }
        std::vector<Vec3> local_displacements(4);
        for (unsigned i = 0; i < 4; ++i)
            local_displacements[i] = displacements[tet.nodes[i]];
        const auto evaluation = tet_patches_[tet_id]->evaluate(
            local_displacements, options_.maximum_displacement_gradient_norm);
        ++out.tet_evaluations;
        out.bulk_stored_energy_j += evaluation.stored_free_energy_j;
        out.plastic_dissipation_j += evaluation.plastic_dissipation_j;
        out.maximum_gradient =
            std::max(out.maximum_gradient, evaluation.maximum_displacement_gradient_norm);
        for (unsigned i = 0; i < 4; ++i)
            out.internal_forces_n[tet.nodes[i]] += evaluation.internal_forces_n[i];
    }
    if (options_.kinematics == CohesiveKinematics::Corotated) {
        require(objective_states.size() == facet_laws_.size(), "Objective cohesive history count mismatch");
        for (std::size_t index = 0; index < facet_laws_.size(); ++index) {
            const auto &facet = topology_.internal_facets[index];
            bool already_detached = true;
            double retained_dissipation = 0;
            const auto &law = facet_laws_[index];
            const CohesiveInterfaceLaw point_law{law.stiffness_pa_per_m, law.strength_pa,
                law.fracture_energy_j_m2, facet.reference_area_m2 / 3, 0};
            for (const auto &point : objective_states[index].integration_points) {
                const auto response = evaluateCohesiveInterface(point_law, point);
                already_detached = already_detached && response.separated;
                retained_dissipation += response.dissipated_energy_j;
            }
            if (already_detached) {
                // A severed material interface is no longer a spring between
                // paired material vertices. Later closure belongs to contact.
                out.corotated_facet_states.push_back(objective_states[index]);
                out.fully_separated_facets.push_back(true);
                out.fracture_dissipation_j += retained_dissipation;
                ++out.facet_evaluations;
                continue;
            }
            std::array<Vec3, 3> reference, a, b;
            std::array<unsigned, 3> b_nodes;
            for (unsigned i = 0; i < 3; ++i) {
                const auto ai = facet.side_a.local_nodes[i];
                b_nodes[i] = facet.side_b.local_nodes[facet.side_b_index_for_side_a[i]];
                reference[i] = topology_.duplicated_definition.reference_positions_m[ai];
                a[i] = reference[i] + displacements[ai];
                b[i] = reference[i] + displacements[b_nodes[i]];
            }
            const auto evaluation = advanceCorotatedCohesiveFacet(facet_laws_[index], reference, a, b,
                                                                 objective_states[index], options_.objective_facets);
            if (evaluation.separated_integration_points == 3 && evaluation.stored_energy_j > 0)
                throw ContactHandoffRequired(index, evaluation.stored_energy_j);
            out.corotated_facet_states.push_back(evaluation.state);
            out.fully_separated_facets.push_back(evaluation.separated_integration_points == 3);
            out.cohesive_stored_energy_j += evaluation.stored_energy_j;
            out.fracture_dissipation_j += evaluation.fracture_dissipation_j;
            out.fracture_dissipation_increment_j += evaluation.fracture_dissipation_increment_j;
            ++out.facet_evaluations;
            out.facet_derivative_evaluations += evaluation.derivative_evaluations;
            for (unsigned i = 0; i < 3; ++i) {
                out.internal_forces_n[facet.side_a.local_nodes[i]] -= evaluation.forces_on_a_n[i];
                out.internal_forces_n[b_nodes[i]] -= evaluation.forces_on_b_n[i];
                out.nodal_scatters += 2;
            }
        }
        out.separation = evaluateAcceptedSeparations(topology_, out.fully_separated_facets, options_.cohesive.separation);
        return out;
    }
    const auto cohesive = evaluateCohesiveAssembly(
        topology_, displacements, facet_states, facet_laws_, options_.cohesive);
    out.facet_states = cohesive.candidate_facet_states;
    out.fully_separated_facets = cohesive.fully_separated_facets;
    out.separation = cohesive.separation;
    out.cohesive_stored_energy_j = cohesive.stored_energy_j;
    out.fracture_dissipation_j = cohesive.fracture_dissipation_j;
    out.fracture_dissipation_increment_j = cohesive.fracture_dissipation_increment_j;
    out.facet_evaluations = cohesive.facet_evaluations;
    out.nodal_scatters = cohesive.nodal_scatters;
    for (std::size_t i = 0; i < out.internal_forces_n.size(); ++i)
        out.internal_forces_n[i] -= cohesive.nodal_forces_n[i];
    return out;
}

double CohesiveDynamicPatch::kineticEnergyJ(const std::vector<Vec3> &velocities) const {
    double energy = 0;
    for (std::size_t i = 0; i < velocities.size(); ++i)
        energy += 0.5 * topology_.local_nodal_masses_kg[i] * lengthSquared(velocities[i]);
    return energy;
}

Vec3 CohesiveDynamicPatch::momentum(const std::vector<Vec3> &velocities) const {
    Vec3 result;
    for (std::size_t i = 0; i < velocities.size(); ++i)
        result += topology_.local_nodal_masses_kg[i] * velocities[i];
    return result;
}

void CohesiveDynamicPatch::setVelocitiesMPerS(const std::vector<Vec3> &velocities) {
    require(state_.revision == 0 && state_.time_s == 0,
            "Cohesive dynamic initial velocity cannot change after stepping");
    require(velocities.size() == state_.velocities_m_s.size(),
            "Cohesive dynamic velocity count differs from local nodes");
    for (std::size_t i = 0; i < velocities.size(); ++i) {
        require(finite(velocities[i]) && length(velocities[i]) <= 1.e6,
                "Invalid cohesive dynamic velocity");
        for (unsigned axis = 0; axis < 3; ++axis)
            require(!topology_.duplicated_definition.fixed_components[i][axis] ||
                        component(velocities[i], axis) == 0,
                    "Nonzero cohesive dynamic velocity on fixed component");
    }
    state_.velocities_m_s = velocities;
}

std::vector<Vec3> CohesiveDynamicPatch::positionsM() const {
    auto positions = topology_.duplicated_definition.reference_positions_m;
    for (std::size_t i = 0; i < positions.size(); ++i)
        positions[i] += state_.displacements_m[i];
    return positions;
}

CohesiveDynamicPatchReport CohesiveDynamicPatch::report() const {
    CohesiveDynamicPatchReport result;
    result.accepted = true;
    result.stable_time_step_limit_s = stable_time_step_limit_s_;
    result.kinetic_energy_j = kineticEnergyJ(state_.velocities_m_s);
    result.bulk_stored_energy_j = accepted_evaluation_->bulk_stored_energy_j;
    result.cohesive_stored_energy_j = accepted_evaluation_->cohesive_stored_energy_j;
    result.plastic_dissipation_j = accepted_evaluation_->plastic_dissipation_j;
    result.fracture_dissipation_j = accepted_evaluation_->fracture_dissipation_j;
    result.accumulated_external_work_j = state_.accumulated_external_work_j;
    result.maximum_elastic_stretch_norm = accepted_evaluation_->maximum_elastic_stretch_norm;
    result.linear_momentum_kg_m_s = momentum(state_.velocities_m_s);
    result.fully_separated_facets = static_cast<unsigned>(std::count(
        state_.fully_separated_facets.begin(), state_.fully_separated_facets.end(), true));
    return result;
}

CohesiveDynamicPatchReport CohesiveDynamicPatch::step(
    double dt, const std::vector<Vec3> &nodal_forces, Vec3 gravity) {
    return stepImpl(dt, nodal_forces, gravity, {}, {}, {});
}

CohesiveDynamicPatchReport CohesiveDynamicPatch::stepImpl(
    double dt, const std::vector<Vec3> &nodal_forces, Vec3 gravity,
    const std::function<void(std::vector<Vec3> &, std::vector<Vec3> &)> &drift_stage,
    const std::function<void(std::vector<Vec3> &, const CohesiveDynamicPatchState &)>
        &final_velocity_stage,
    const std::function<void(const CohesiveDynamicPatchState &,
                             const CohesiveDynamicPatchReport &)> &before_commit) {
    CohesiveDynamicPatchReport result;
    result.time_step_s = dt;
    result.stable_time_step_limit_s = stable_time_step_limit_s_;
    try {
        require(std::isfinite(dt) && dt > 0 && dt <= stable_time_step_limit_s_,
                "Invalid or unstable cohesive dynamic time step");
        require(nodal_forces.size() == state_.velocities_m_s.size(),
                "Cohesive dynamic nodal-force count differs from local nodes");
        require(finite(gravity) && length(gravity) <= 1.e6,
                "Invalid cohesive dynamic gravity");
        for (Vec3 force : nodal_forces)
            require(finite(force) && length(force) <= 1.e12,
                    "Invalid cohesive dynamic nodal force");

        auto candidate = state_;
        const double old_kinetic = kineticEnergyJ(state_.velocities_m_s);
        const double old_stored = accepted_evaluation_->bulk_stored_energy_j +
                                  accepted_evaluation_->cohesive_stored_energy_j;
        const double old_dissipation = accepted_evaluation_->plastic_dissipation_j +
                                       accepted_evaluation_->fracture_dissipation_j;
        const Vec3 old_momentum = momentum(state_.velocities_m_s);
        Vec3 external_impulse;
        Vec3 support_impulse;
        double external_work = 0;
        std::vector<Vec3> drift(candidate.velocities_m_s.size());
        for (std::size_t i = 0; i < candidate.velocities_m_s.size(); ++i) {
            const Vec3 external = nodal_forces[i] +
                                  topology_.local_nodal_masses_kg[i] * gravity;
            external_impulse += dt * external;
            const Vec3 net = external - accepted_evaluation_->internal_forces_n[i];
            for (unsigned axis = 0; axis < 3; ++axis) {
                if (topology_.duplicated_definition.fixed_components[i][axis]) {
                    setComponent(support_impulse, axis,
                                 component(support_impulse, axis) -
                                     0.5 * dt * component(net, axis));
                    setComponent(candidate.velocities_m_s[i], axis, 0);
                    setComponent(candidate.displacements_m[i], axis, 0);
                } else {
                    setComponent(candidate.velocities_m_s[i], axis,
                                 component(candidate.velocities_m_s[i], axis) +
                                     0.5 * dt * component(net, axis) /
                                         topology_.local_nodal_masses_kg[i]);
                }
            }
        }
        if (drift_stage) {
            const double kinetic_before = kineticEnergyJ(candidate.velocities_m_s);
            const Vec3 momentum_before = momentum(candidate.velocities_m_s);
            drift_stage(candidate.velocities_m_s, drift);
            require(drift.size() == candidate.velocities_m_s.size() &&
                        candidate.velocities_m_s.size() == state_.velocities_m_s.size(),
                    "Cohesive dynamic drift hook changed array layout");
            result.coupling_kinetic_work_j +=
                kineticEnergyJ(candidate.velocities_m_s) - kinetic_before;
            result.coupling_impulse_n_s += momentum(candidate.velocities_m_s) - momentum_before;
        } else {
            for (std::size_t i = 0; i < drift.size(); ++i)
                drift[i] = dt * candidate.velocities_m_s[i];
        }
        for (std::size_t i = 0; i < candidate.velocities_m_s.size(); ++i) {
            require(finite(candidate.velocities_m_s[i]) &&
                        length(candidate.velocities_m_s[i]) <= 1.e6,
                    "Invalid cohesive dynamic post-hook velocity");
            for (unsigned axis = 0; axis < 3; ++axis)
                require(!topology_.duplicated_definition.fixed_components[i][axis] ||
                            component(candidate.velocities_m_s[i], axis) == 0,
                        "Cohesive dynamic drift hook moved a fixed component velocity");
        }
        for (std::size_t i = 0; i < candidate.velocities_m_s.size(); ++i) {
            const Vec3 external = nodal_forces[i] +
                                  topology_.local_nodal_masses_kg[i] * gravity;
            require(finite(drift[i]), "Invalid cohesive dynamic coupled drift");
            for (unsigned axis = 0; axis < 3; ++axis) {
                if (topology_.duplicated_definition.fixed_components[i][axis]) {
                    require(component(drift[i], axis) == 0,
                            "Cohesive dynamic hook moved a fixed component");
                } else {
                    const double increment = component(drift[i], axis);
                    setComponent(candidate.displacements_m[i], axis,
                                 component(candidate.displacements_m[i], axis) + increment);
                    external_work += component(external, axis) * increment;
                }
            }
        }
        auto evaluation = evaluate(candidate.displacements_m, state_.facet_states, state_.corotated_facet_states);
        for (std::size_t i = 0; i < candidate.velocities_m_s.size(); ++i) {
            const Vec3 external = nodal_forces[i] +
                                  topology_.local_nodal_masses_kg[i] * gravity;
            const Vec3 net = external - evaluation.internal_forces_n[i];
            for (unsigned axis = 0; axis < 3; ++axis) {
                if (topology_.duplicated_definition.fixed_components[i][axis]) {
                    setComponent(support_impulse, axis,
                                 component(support_impulse, axis) -
                                     0.5 * dt * component(net, axis));
                } else {
                    setComponent(candidate.velocities_m_s[i], axis,
                                 component(candidate.velocities_m_s[i], axis) +
                                     0.5 * dt * component(net, axis) /
                                         topology_.local_nodal_masses_kg[i]);
                }
            }
            require(finite(candidate.velocities_m_s[i]) &&
                        length(candidate.velocities_m_s[i]) <= 1.e6,
                    "Cohesive dynamic velocity exceeds finite validity bound");
        }
        if (final_velocity_stage) {
            const double kinetic_before = kineticEnergyJ(candidate.velocities_m_s);
            const Vec3 momentum_before = momentum(candidate.velocities_m_s);
            // Publish the candidate fracture topology to the hook before its
            // velocity projection, while facet histories remain immutable.
            candidate.facet_states = evaluation.facet_states;
            candidate.corotated_facet_states = evaluation.corotated_facet_states;
            candidate.fully_separated_facets = evaluation.fully_separated_facets;
            candidate.separation = evaluation.separation;
            final_velocity_stage(candidate.velocities_m_s, candidate);
            require(candidate.velocities_m_s.size() == state_.velocities_m_s.size(),
                    "Cohesive dynamic final hook changed velocity layout");
            for (std::size_t i = 0; i < candidate.velocities_m_s.size(); ++i) {
                require(finite(candidate.velocities_m_s[i]) &&
                            length(candidate.velocities_m_s[i]) <= 1.e6,
                        "Invalid cohesive dynamic final-hook velocity");
                for (unsigned axis = 0; axis < 3; ++axis)
                    require(!topology_.duplicated_definition.fixed_components[i][axis] ||
                                component(candidate.velocities_m_s[i], axis) == 0,
                            "Cohesive dynamic final hook moved a fixed component");
            }
            result.coupling_kinetic_work_j +=
                kineticEnergyJ(candidate.velocities_m_s) - kinetic_before;
            result.coupling_impulse_n_s += momentum(candidate.velocities_m_s) - momentum_before;
        }
        candidate.facet_states = evaluation.facet_states;
        candidate.corotated_facet_states = evaluation.corotated_facet_states;
        candidate.fully_separated_facets = evaluation.fully_separated_facets;
        candidate.separation = evaluation.separation;
        candidate.time_s += dt;
        candidate.accumulated_external_work_j += external_work;
        require(candidate.revision < std::numeric_limits<std::uint64_t>::max(),
                "Cohesive dynamic revision limit reached");
        ++candidate.revision;

        result.kinetic_energy_j = kineticEnergyJ(candidate.velocities_m_s);
        result.bulk_stored_energy_j = evaluation.bulk_stored_energy_j;
        result.cohesive_stored_energy_j = evaluation.cohesive_stored_energy_j;
        result.plastic_dissipation_j = evaluation.plastic_dissipation_j;
        result.fracture_dissipation_j = evaluation.fracture_dissipation_j;
        result.fracture_dissipation_increment_j =
            evaluation.fracture_dissipation_increment_j;
        result.external_work_increment_j = external_work;
        result.accumulated_external_work_j = candidate.accumulated_external_work_j;
        result.linear_momentum_kg_m_s = momentum(candidate.velocities_m_s);
        result.momentum_residual_kg_m_s =
            result.linear_momentum_kg_m_s - old_momentum - external_impulse -
            support_impulse - result.coupling_impulse_n_s;
        result.support_impulse_n_s = support_impulse;
        result.numerical_energy_residual_j =
            result.kinetic_energy_j - old_kinetic +
            result.bulk_stored_energy_j + result.cohesive_stored_energy_j - old_stored +
            result.plastic_dissipation_j + result.fracture_dissipation_j - old_dissipation -
            external_work - result.coupling_kinetic_work_j;
        result.tet_evaluations = evaluation.tet_evaluations;
        result.facet_evaluations = evaluation.facet_evaluations;
        result.nodal_scatters = evaluation.nodal_scatters;
        result.polar_iterations = evaluation.polar_iterations;
        result.facet_derivative_evaluations = evaluation.facet_derivative_evaluations;
        result.maximum_elastic_stretch_norm = evaluation.maximum_elastic_stretch_norm;
        result.fully_separated_facets = static_cast<unsigned>(std::count(
            evaluation.fully_separated_facets.begin(),
            evaluation.fully_separated_facets.end(), true));
        require(std::isfinite(result.numerical_energy_residual_j) &&
                    std::abs(result.numerical_energy_residual_j) <=
                        options_.maximum_absolute_energy_residual_j,
                "Cohesive dynamic energy residual exceeds acceptance budget");
        require(finite(result.momentum_residual_kg_m_s),
                "Cohesive dynamic momentum residual is not finite");
        require(std::isfinite(candidate.time_s) &&
                    std::isfinite(candidate.accumulated_external_work_j),
                "Cohesive dynamic ledger exceeds numeric range");
        if (before_commit)
            before_commit(candidate, result);
        auto candidate_evaluation =
            std::make_shared<const CombinedEvaluation>(std::move(evaluation));
        state_ = std::move(candidate);
        accepted_evaluation_ = std::move(candidate_evaluation);
        result.accepted = true;
    } catch (const ContactHandoffRequired &error) {
        result.error = error.what();
        result.contact_handoff_required = error.evidence;
    } catch (const std::exception &error) {
        result.error = error.what();
    }
    return result;
}

} // namespace banjo
