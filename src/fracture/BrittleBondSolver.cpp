#include "fracture/BrittleBondSolver.hpp"
#include "fracture/BondFailure.hpp"
#include "physics/MechanicalAccounting.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace banjo {
namespace {

// The nonlocal strain measure, the damage ramp and the removal rule now live in
// fracture/BondFailure.hpp so the implicit solver applies the same criterion.

void applySupportContact(
    ActiveNodeState &node, const BrittleSolverSettings &settings) {
    if (!settings.support_enabled) return;
    const auto &plane = settings.support_plane;
    if (!insideSupportFootprint(plane, node.position_world_m,
            settings.support_half_tangent_m, settings.support_half_bitangent_m)) return;
    const double distance = signedDistanceToPlane(plane, node.position_world_m);
    if (distance > 1.0e-8) return;
    const double normal_speed = dot(node.velocity_m_s, plane.normal_world);
    if (normal_speed < 0.0) {
        const double restitution = -normal_speed > 0.5
            ? std::clamp(settings.surface_restitution, 0.0, 1.0) : 0.0;
        const double normal_delta = -(1.0 + restitution) * normal_speed;
        node.velocity_m_s += normal_delta * plane.normal_world;
        const Vec3 tangent = projectVectorOntoPlane(plane, node.velocity_m_s);
        const double speed = length(tangent);
        if (speed > 1.0e-12) {
            const double friction_delta = speed <= settings.surface_static_friction * normal_delta
                ? speed : std::min(speed, settings.surface_dynamic_friction * normal_delta);
            node.velocity_m_s -= (friction_delta / speed) * tangent;
        }
    }
    // Split position correction, after reconstructing velocities. A penetrating
    // point is not given artificial rebound energy by moving it out of the floor.
    node.position_world_m -= distance * plane.normal_world;
}

// Position-level non-penetration for one node, intended to run inside the
// constraint sweep so that the correction is redistributed through the bonds by
// the following iterations instead of displacing a node relative to neighbours
// that were never solved against it. Returns the depth removed this call.
[[nodiscard]] double projectSupportPosition(
    ActiveNodeState &node, const BrittleSolverSettings &settings) {
    if (!settings.support_enabled) return 0.0;
    const auto &plane = settings.support_plane;
    if (!insideSupportFootprint(plane, node.position_world_m,
            settings.support_half_tangent_m, settings.support_half_bitangent_m)) return 0.0;
    const double distance = signedDistanceToPlane(plane, node.position_world_m);
    if (distance > 1.0e-8) return 0.0;
    node.position_world_m -= distance * plane.normal_world;
    return -distance;
}

// Velocity-level support response for a node whose position was constrained in
// this substep. The normal velocity implied by the position solve is replaced by
// the restitution target measured from the approach velocity, so the projection
// cannot act as an energy source, and Coulomb friction is charged against the
// actual normal velocity change.
void applySupportVelocity(
    ActiveNodeState &node, double approach_normal_speed,
    const BrittleSolverSettings &settings) {
    const auto &plane = settings.support_plane;
    const double restitution = -approach_normal_speed > 0.5
        ? std::clamp(settings.surface_restitution, 0.0, 1.0) : 0.0;
    const double target = approach_normal_speed < 0.0
        ? -restitution * approach_normal_speed : 0.0;
    const double normal_speed = dot(node.velocity_m_s, plane.normal_world);
    double corrected = normal_speed;
    if (normal_speed > target) corrected = target;
    else if (normal_speed < 0.0) corrected = 0.0;
    node.velocity_m_s += (corrected - normal_speed) * plane.normal_world;
    const double normal_delta = corrected - std::min(0.0, approach_normal_speed);
    if (normal_delta <= 0.0) return;
    const Vec3 tangent = projectVectorOntoPlane(plane, node.velocity_m_s);
    const double speed = length(tangent);
    if (speed <= 1.0e-12) return;
    const double friction_delta = speed <= settings.surface_static_friction * normal_delta
        ? speed : std::min(speed, settings.surface_dynamic_friction * normal_delta);
    node.velocity_m_s -= (friction_delta / speed) * tangent;
}

void accumulateContactStats(SphereMaterialContactStats &out,
                            const SphereMaterialContactStats &in) {
    out.impulse_contacts += in.impulse_contacts;
    out.impulse_to_material_n_s += in.impulse_to_material_n_s;
    out.angular_impulse_to_sphere_kg_m2_s += in.angular_impulse_to_sphere_kg_m2_s;
    out.dissipated_kinetic_energy_j += in.dissipated_kinetic_energy_j;
    out.maximum_penetration_m = std::max(out.maximum_penetration_m, in.maximum_penetration_m);
    out.maximum_position_correction_m = std::max(out.maximum_position_correction_m, in.maximum_position_correction_m);
    out.position_correction_angular_momentum_delta_kg_m2_s +=
        in.position_correction_angular_momentum_delta_kg_m2_s;
}

// Radial pair damping is translation/rotation invariant and exchanges equal,
// opposite central impulses. It must not damp whole-object motion in a vacuum.
double dampInternalBonds(ActiveMatter &matter, double dt) {
    const double fraction = 1.0 - std::exp(-matter.material.bond_damping * dt);
    double loss = 0.0;
    if (fraction <= 0.0) return loss;
    for (std::size_t i = 0; i < matter.bonds.size(); ++i) {
        if (!matter.bonds[i].alive) continue;
        const auto &bond = matter.asset->bonds[i];
        auto &a = matter.nodes[bond.node_a];
        auto &b = matter.nodes[bond.node_b];
        if (a.mass_kg <= 0.0 || b.mass_kg <= 0.0) continue;
        const Vec3 normal = normalized(b.position_world_m - a.position_world_m);
        const double relative_speed = dot(b.velocity_m_s - a.velocity_m_s, normal);
        const double inverse_mass = 1.0 / a.mass_kg + 1.0 / b.mass_kg;
        const double impulse = -fraction * relative_speed / inverse_mass;
        a.velocity_m_s -= (impulse / a.mass_kg) * normal;
        b.velocity_m_s += (impulse / b.mass_kg) * normal;
        loss += -(impulse * relative_speed + 0.5 * inverse_mass * impulse * impulse);
    }
    return loss;
}

void solveBond(
    ActiveMatter &matter,
    std::size_t bond_index,
    double substep_dt_s) {
    ActiveBondState &state = matter.bonds[bond_index];
    if (!state.alive) {
        return;
    }

    const BondRest &rest = matter.asset->bonds[bond_index];
    ActiveNodeState &a = matter.nodes[rest.node_a];
    ActiveNodeState &b = matter.nodes[rest.node_b];

    const Vec3 delta = b.position_world_m - a.position_world_m;
    const double current_length = length(delta);
    if (current_length <= 1.0e-12) {
        return;
    }

    const double constraint = current_length - rest.rest_length_m;
    const Vec3 direction = delta / current_length;
    const double inverse_mass_a = a.mass_kg > 0.0 ? 1.0 / a.mass_kg : 0.0;
    const double inverse_mass_b = b.mass_kg > 0.0 ? 1.0 / b.mass_kg : 0.0;
    const double alpha = rest.compliance / (substep_dt_s * substep_dt_s);
    const double delta_lambda =
        (-constraint - alpha * state.accumulated_lambda) /
        (inverse_mass_a + inverse_mass_b + alpha);

    state.accumulated_lambda += delta_lambda;
    a.position_world_m -= inverse_mass_a * delta_lambda * direction;
    b.position_world_m += inverse_mass_b * delta_lambda * direction;
}

} // namespace

BrittleBondSolver::BrittleBondSolver(BrittleSolverSettings settings)
    : settings_(settings) {
    if (settings_.impact_internal_energy_fraction != 0.0) {
        throw std::invalid_argument("synthetic impact energy is unsupported; use physical contact or authored initial state");
    }
    if (settings_.substeps == 0U ||
        settings_.constraint_iterations == 0U) {
        throw std::invalid_argument(
            "solver requires at least one substep and constraint iteration");
    }
    if (!settings_.use_support_plane) {
        settings_.support_plane = makeSupportPlane(
            {0.0, settings_.floor_height_m, 0.0},
            {0.0, 1.0, 0.0});
        settings_.surface_dynamic_friction = settings_.floor_friction;
    }
}

ActiveMatter BrittleBondSolver::activate(
    MatterBodyId body_id,
    const LatticeAsset &asset,
    const CompiledBrittleMaterial &material,
    const RigidSnapshot &rigid,
    const ImpactEvent &impact) const {
    if (!impact.involves(body_id)) {
        throw std::invalid_argument(
            "activation impact does not involve body");
    }

    ActiveMatter matter;
    matter.body_id = body_id;
    matter.asset = &asset;
    matter.material = material;
    matter.nodes.reserve(asset.nodes.size());
    matter.reference_positions_world_m.reserve(asset.nodes.size());
    matter.bonds.resize(asset.bonds.size());

    for (const LatticeNodeRest &rest_node : asset.nodes) {
        const Vec3 rotated_local = rigid.orientation_world.rotate(
            rest_node.local_position_m - asset.rest_center_of_mass_m);
        const Vec3 position =
            rigid.center_of_mass_world_m + rotated_local;
        const Vec3 velocity =
            rigid.linear_velocity_m_s +
            cross(rigid.angular_velocity_rad_s, rotated_local);
        matter.nodes.push_back({
            position,
            position,
            velocity,
            rest_node.represented_volume_m3 * material.density_kg_m3,
            rigid.angular_velocity_rad_s,
        });
        matter.reference_positions_world_m.push_back(position);
    }

    return matter;
}

MaterialStepStats BrittleBondSolver::step(
    ActiveMatter &matter,
    double frame_dt_s,
    const Vec3 &gravity_m_s2,
    CoupledSphereState *sphere,
    const SphereMaterialContactSettings &contact) const {
    if (matter.asset == nullptr || frame_dt_s <= 0.0) {
        throw std::invalid_argument(
            "active matter and positive frame step are required");
    }

    MaterialStepStats stats;
    const auto measure_boundary = [&]() {
        auto totals = measureMaterialMechanics(matter, gravity_m_s2);
        if (sphere) {
            Mat3 inertia;
            for (unsigned i = 0; i < 3; ++i) inertia.m[i][i] = sphere->inertia_kg_m2;
            totals += measureRigidMechanics({sphere->motion, sphere->mass_kg, inertia}, gravity_m_s2);
        }
        return totals;
    };
    MechanicalTotals previous_stage;
    if (settings_.audit_stages) {
        previous_stage = measure_boundary();
        stats.stages_measured = true;
    }
    const auto record_stage = [&](MaterialStage stage) {
        if (!settings_.audit_stages) return;
        const auto current = measure_boundary();
        stats.stage_changes[static_cast<std::size_t>(stage)] +=
            MaterialStageChange::between(previous_stage, current);
        previous_stage = current;
    };
    const std::size_t broken_before = countBrokenBonds(matter);
    const double substep_dt =
        frame_dt_s / static_cast<double>(settings_.substeps);
    std::vector<double> approach_normal_speed;
    std::vector<std::uint8_t> support_engaged;

    for (unsigned substep = 0; substep < settings_.substeps; ++substep) {
        resetBondStrainPeaks(matter);
        for (ActiveBondState &bond : matter.bonds) bond.accumulated_lambda = 0.0;
        accumulateBondStrainPeaks(matter);

        for (ActiveNodeState &node : matter.nodes) {
            node.previous_position_world_m = node.position_world_m;
            node.velocity_m_s += substep_dt * gravity_m_s2;
        }
        record_stage(MaterialStage::Gravity);
        if (sphere) {
            accumulateContactStats(stats.rigid_contact, solveSphereMaterialContacts(
                matter, *sphere, substep_dt, contact));
        }
        record_stage(MaterialStage::PreContact);
        const bool constrained_support =
            settings_.support_in_constraint_solve && settings_.support_enabled;
        if (constrained_support) {
            approach_normal_speed.assign(matter.nodes.size(),
                                         std::numeric_limits<double>::quiet_NaN());
            for (std::size_t i = 0; i < matter.nodes.size(); ++i)
                approach_normal_speed[i] =
                    dot(matter.nodes[i].velocity_m_s, settings_.support_plane.normal_world);
            support_engaged.assign(matter.nodes.size(), 0);
        }
        for (ActiveNodeState &node : matter.nodes) {
            node.position_world_m += substep_dt * node.velocity_m_s;
        }
        record_stage(MaterialStage::Prediction);

        const auto before_constraints = measureMaterialMechanics(matter, gravity_m_s2);
        for (unsigned iteration = 0;
             iteration < settings_.constraint_iterations;
             ++iteration) {
            for (std::size_t bond_index = 0;
                 bond_index < matter.bonds.size();
                 ++bond_index) {
                solveBond(matter, bond_index, substep_dt);
            }
            if (!constrained_support) continue;
            for (std::size_t i = 0; i < matter.nodes.size(); ++i) {
                const double depth = projectSupportPosition(matter.nodes[i], settings_);
                if (depth > 0.0) {
                    support_engaged[i] = 1;
                    stats.maximum_support_projection_m =
                        std::max(stats.maximum_support_projection_m, depth);
                }
            }
        }

        for (ActiveNodeState &node : matter.nodes) {
            node.velocity_m_s =
                (node.position_world_m - node.previous_position_world_m) / substep_dt;
        }
        const auto after_constraints = measureMaterialMechanics(matter, gravity_m_s2);
        stats.constraint_angular_momentum_delta_kg_m2_s +=
            after_constraints.angular_momentum_kg_m2_s - before_constraints.angular_momentum_kg_m2_s;
        stats.constraint_mechanical_energy_delta_j +=
            after_constraints.mechanicalEnergy() - before_constraints.mechanicalEnergy();
        record_stage(MaterialStage::Constraints);
        stats.internal_damping_loss_j += dampInternalBonds(matter, substep_dt);
        record_stage(MaterialStage::Damping);
        if (sphere) {
            accumulateContactStats(stats.rigid_contact, solveSphereMaterialContacts(
                matter, *sphere, substep_dt, contact, true));
        }
        record_stage(MaterialStage::PostContact);
        if (constrained_support) {
            for (std::size_t i = 0; i < matter.nodes.size(); ++i) {
                if (support_engaged[i] == 0) continue;
                applySupportVelocity(matter.nodes[i], approach_normal_speed[i], settings_);
            }
        } else {
            for (ActiveNodeState &node : matter.nodes) {
                applySupportContact(node, settings_);
            }
        }
        record_stage(MaterialStage::Support);

        accumulateBondStrainPeaks(matter);
        // One criterion, shared with the implicit lane: see fracture/BondFailure.hpp.
        const auto failure = applyBondFailure(matter);
        stats.maximum_tensile_stretch = std::max(
            stats.maximum_tensile_stretch, failure.maximum_tensile_stretch);
        stats.maximum_compressive_strain = std::max(
            stats.maximum_compressive_strain, failure.maximum_compressive_strain);
        stats.maximum_shear_strain = std::max(
            stats.maximum_shear_strain, failure.maximum_shear_strain);
        stats.unassigned_bond_removal_energy_j += failure.removed_elastic_energy_j;
        record_stage(MaterialStage::Damage);
    }

    const std::size_t broken_after = countBrokenBonds(matter);
    stats.broken_bonds_this_step = broken_after - broken_before;
    stats.total_broken_bonds = broken_after;
    stats.live_bonds = matter.bonds.size() - broken_after;
    const auto mode_counts = countBondFailureModes(matter);
    stats.tensile_failures += mode_counts.tensile;
    stats.compressive_failures += mode_counts.compressive;
    stats.shear_failures += mode_counts.shear;

    for (const ActiveNodeState &node : matter.nodes) {
        const double speed = length(node.velocity_m_s);
        stats.maximum_speed_m_s =
            std::max(stats.maximum_speed_m_s, speed);
        stats.kinetic_energy_j +=
            0.5 * node.mass_kg * speed * speed;
        const double cell_size = matter.asset->recipe.voxel_size_m;
        stats.kinetic_energy_j += node.mass_kg * cell_size * cell_size / 12.0 *
            lengthSquared(node.spin_angular_velocity_rad_s);
    }
    for (std::size_t bond_index = 0;
         bond_index < matter.bonds.size();
         ++bond_index) {
        if (!matter.bonds[bond_index].alive) {
            continue;
        }
        const BondRest &rest = matter.asset->bonds[bond_index];
        const double extension =
            length(
                matter.nodes[rest.node_b].position_world_m -
                matter.nodes[rest.node_a].position_world_m) -
            rest.rest_length_m;
        if (rest.compliance > 0.0) {
            stats.estimated_elastic_energy_j +=
                0.5 * extension * extension / rest.compliance;
        }
    }

    ++matter.step_index;
    return stats;
}

} // namespace banjo
