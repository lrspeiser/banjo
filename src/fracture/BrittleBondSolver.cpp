#include "fracture/BrittleBondSolver.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <stdexcept>
#include <vector>

namespace banjo {
namespace {

[[nodiscard]] std::size_t countBrokenBonds(const ActiveMatter &matter) {
    return static_cast<std::size_t>(std::count_if(
        matter.bonds.begin(), matter.bonds.end(), [](const ActiveBondState &bond) {
            return !bond.alive;
        }));
}

void solveFloorContact(
    ActiveNodeState &node,
    double floor_height_m,
    double floor_friction) {
    if (node.position_world_m.y >= floor_height_m) {
        return;
    }
    node.position_world_m.y = floor_height_m;
    const double friction_scale = std::clamp(1.0 - floor_friction, 0.0, 1.0);
    const Vec3 displacement = node.position_world_m - node.previous_position_world_m;
    node.position_world_m.x =
        node.previous_position_world_m.x + friction_scale * displacement.x;
    node.position_world_m.z =
        node.previous_position_world_m.z + friction_scale * displacement.z;
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
    const double stretch = constraint / rest.rest_length_m;
    state.peak_tensile_stretch = std::max(state.peak_tensile_stretch, stretch);

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

BrittleBondSolver::BrittleBondSolver(BrittleSolverSettings settings) : settings_(settings) {
    if (settings_.substeps == 0U || settings_.constraint_iterations == 0U) {
        throw std::invalid_argument("solver requires at least one substep and constraint iteration");
    }
}

ActiveMatter BrittleBondSolver::activate(
    MatterBodyId body_id,
    const LatticeAsset &asset,
    const CompiledBrittleMaterial &material,
    const RigidSnapshot &rigid,
    const ImpactEvent &impact) const {
    if (!impact.involves(body_id)) {
        throw std::invalid_argument("activation impact does not involve body");
    }

    ActiveMatter matter;
    matter.body_id = body_id;
    matter.asset = &asset;
    matter.material = material;
    matter.nodes.reserve(asset.nodes.size());
    matter.bonds.resize(asset.bonds.size());

    for (const LatticeNodeRest &rest_node : asset.nodes) {
        const Vec3 rotated_local = rigid.orientation_world.rotate(
            rest_node.local_position_m - asset.rest_center_of_mass_m);
        const Vec3 position = rigid.center_of_mass_world_m + rotated_local;
        const Vec3 velocity =
            rigid.linear_velocity_m_s + cross(rigid.angular_velocity_rad_s, rotated_local);
        matter.nodes.push_back({
            position,
            position,
            velocity,
            rest_node.represented_volume_m3 * material.density_kg_m3,
        });
    }

    injectInternalImpactPulse(matter, impact, normalized(impact.normalInto(body_id)));
    return matter;
}

void BrittleBondSolver::injectInternalImpactPulse(
    ActiveMatter &matter,
    const ImpactEvent &impact,
    const Vec3 &normal_into_target) const {
    if (matter.nodes.empty() || impact.available_normal_energy_j <= 0.0) {
        return;
    }

    const double influence_radius = std::max(
        2.5 * matter.asset->recipe.voxel_size_m,
        0.30 * matter.asset->recipe.radius_m);
    std::vector<Vec3> delta_velocity(matter.nodes.size());

    double total_mass = 0.0;
    Vec3 added_momentum{};
    for (std::size_t i = 0; i < matter.nodes.size(); ++i) {
        const ActiveNodeState &node = matter.nodes[i];
        const double distance = length(node.position_world_m - impact.contact_point_world_m);
        const double normalized_distance = distance / influence_radius;
        const double weight = normalized_distance < 1.0
                                  ? std::exp(-4.0 * normalized_distance * normalized_distance)
                                  : 0.0;
        delta_velocity[i] = weight * normal_into_target;
        added_momentum += node.mass_kg * delta_velocity[i];
        total_mass += node.mass_kg;
    }

    if (total_mass <= 0.0) {
        return;
    }

    // Jolt has already transferred the whole-object impulse. Remove the pulse's uniform
    // translation so this injection adds internal motion without a second bulk impulse.
    const Vec3 mean_delta = added_momentum / total_mass;
    double raw_internal_energy = 0.0;
    for (std::size_t i = 0; i < matter.nodes.size(); ++i) {
        delta_velocity[i] -= mean_delta;
        raw_internal_energy +=
            0.5 * matter.nodes[i].mass_kg * lengthSquared(delta_velocity[i]);
    }
    if (raw_internal_energy <= 1.0e-12) {
        return;
    }

    const double requested_energy = std::min(
        settings_.maximum_internal_energy_j,
        settings_.impact_internal_energy_fraction * impact.available_normal_energy_j);
    const double scale = std::sqrt(requested_energy / raw_internal_energy);
    for (std::size_t i = 0; i < matter.nodes.size(); ++i) {
        matter.nodes[i].velocity_m_s += scale * delta_velocity[i];
    }
}

MaterialStepStats BrittleBondSolver::step(
    ActiveMatter &matter,
    double frame_dt_s,
    const Vec3 &gravity_m_s2) const {
    if (matter.asset == nullptr || frame_dt_s <= 0.0) {
        throw std::invalid_argument("active matter and positive frame step are required");
    }

    MaterialStepStats stats;
    const std::size_t broken_before = countBrokenBonds(matter);
    const double substep_dt = frame_dt_s / static_cast<double>(settings_.substeps);

    for (unsigned substep = 0; substep < settings_.substeps; ++substep) {
        for (ActiveBondState &bond : matter.bonds) {
            bond.peak_tensile_stretch = 0.0;
            bond.accumulated_lambda = 0.0;
        }

        for (ActiveNodeState &node : matter.nodes) {
            node.previous_position_world_m = node.position_world_m;
            node.velocity_m_s += substep_dt * gravity_m_s2;
            node.position_world_m += substep_dt * node.velocity_m_s;
        }

        for (unsigned iteration = 0; iteration < settings_.constraint_iterations; ++iteration) {
            for (std::size_t bond_index = 0; bond_index < matter.bonds.size(); ++bond_index) {
                solveBond(matter, bond_index, substep_dt);
            }
            for (ActiveNodeState &node : matter.nodes) {
                solveFloorContact(node, settings_.floor_height_m, settings_.floor_friction);
            }
        }

        const double damping = std::exp(-matter.material.bond_damping * substep_dt);
        for (ActiveNodeState &node : matter.nodes) {
            node.velocity_m_s =
                damping * (node.position_world_m - node.previous_position_world_m) / substep_dt;
        }

        for (std::size_t bond_index = 0; bond_index < matter.bonds.size(); ++bond_index) {
            ActiveBondState &state = matter.bonds[bond_index];
            if (!state.alive) {
                continue;
            }
            const BondRest &rest = matter.asset->bonds[bond_index];
            stats.maximum_tensile_stretch =
                std::max(stats.maximum_tensile_stretch, state.peak_tensile_stretch);
            if (state.peak_tensile_stretch <= rest.damage_start_stretch) {
                continue;
            }

            const double normalized_damage =
                (state.peak_tensile_stretch - rest.damage_start_stretch) /
                (rest.damage_end_stretch - rest.damage_start_stretch);
            state.damage = std::max(state.damage, std::clamp(normalized_damage, 0.0, 1.0));
            if (state.damage >= 1.0) {
                state.alive = false;
                matter.connectivity_dirty = true;
            }
        }
    }

    const std::size_t broken_after = countBrokenBonds(matter);
    stats.broken_bonds_this_step = broken_after - broken_before;
    stats.total_broken_bonds = broken_after;
    stats.live_bonds = matter.bonds.size() - broken_after;
    ++matter.step_index;
    return stats;
}

} // namespace banjo
