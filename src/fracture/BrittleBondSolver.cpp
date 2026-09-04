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

[[nodiscard]] Vec3 centerOfMass(const ActiveMatter &matter) {
    double total_mass = 0.0;
    Vec3 weighted{};
    for (const ActiveNodeState &node : matter.nodes) {
        total_mass += node.mass_kg;
        weighted += node.mass_kg * node.position_world_m;
    }
    return total_mass > 0.0 ? weighted / total_mass : Vec3{};
}

[[nodiscard]] Mat3 pointMassInertia(
    const ActiveMatter &matter,
    const Vec3 &center_of_mass) {
    Mat3 inertia{};
    for (const ActiveNodeState &node : matter.nodes) {
        const Vec3 r = node.position_world_m - center_of_mass;
        inertia.m[0][0] += node.mass_kg * (r.y * r.y + r.z * r.z);
        inertia.m[1][1] += node.mass_kg * (r.x * r.x + r.z * r.z);
        inertia.m[2][2] += node.mass_kg * (r.x * r.x + r.y * r.y);
        inertia.m[0][1] -= node.mass_kg * r.x * r.y;
        inertia.m[1][0] = inertia.m[0][1];
        inertia.m[0][2] -= node.mass_kg * r.x * r.z;
        inertia.m[2][0] = inertia.m[0][2];
        inertia.m[1][2] -= node.mass_kg * r.y * r.z;
        inertia.m[2][1] = inertia.m[1][2];
    }
    return inertia;
}

void removeRigidMomentumComponents(
    const ActiveMatter &matter,
    std::vector<Vec3> &delta_velocity) {
    if (matter.nodes.empty() || delta_velocity.size() != matter.nodes.size()) {
        return;
    }

    double total_mass = 0.0;
    Vec3 linear_momentum{};
    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        total_mass += matter.nodes[index].mass_kg;
        linear_momentum += matter.nodes[index].mass_kg * delta_velocity[index];
    }
    if (total_mass <= 0.0) {
        return;
    }

    const Vec3 mean_delta = linear_momentum / total_mass;
    for (Vec3 &velocity : delta_velocity) {
        velocity -= mean_delta;
    }

    const Vec3 center = centerOfMass(matter);
    Vec3 angular_momentum{};
    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        const Vec3 r = matter.nodes[index].position_world_m - center;
        angular_momentum += cross(r, matter.nodes[index].mass_kg * delta_velocity[index]);
    }

    const Mat3 inertia = pointMassInertia(matter, center);
    if (const auto inverse = inertia.inverse(1.0e-18)) {
        const Vec3 angular_velocity = *inverse * angular_momentum;
        for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
            const Vec3 r = matter.nodes[index].position_world_m - center;
            delta_velocity[index] -= cross(angular_velocity, r);
        }
    }

    // Remove residual translation from floating-point roundoff after the rotational projection.
    Vec3 residual_momentum{};
    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        residual_momentum += matter.nodes[index].mass_kg * delta_velocity[index];
    }
    const Vec3 residual_mean = residual_momentum / total_mass;
    for (Vec3 &velocity : delta_velocity) {
        velocity -= residual_mean;
    }
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

    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        const ActiveNodeState &node = matter.nodes[index];
        const double distance = length(node.position_world_m - impact.contact_point_world_m);
        const double normalized_distance = distance / influence_radius;
        const double weight = normalized_distance < 1.0
                                  ? std::exp(-4.0 * normalized_distance * normalized_distance)
                                  : 0.0;
        delta_velocity[index] = weight * normal_into_target;
    }

    // Jolt already transferred the whole-object collision impulse. Project both the
    // uniform translation and rigid rotation out of this local pulse so it can only
    // add internal deformation energy.
    removeRigidMomentumComponents(matter, delta_velocity);

    double raw_internal_energy = 0.0;
    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        raw_internal_energy +=
            0.5 * matter.nodes[index].mass_kg * lengthSquared(delta_velocity[index]);
    }
    if (raw_internal_energy <= 1.0e-12) {
        return;
    }

    const double requested_energy = std::min(
        settings_.maximum_internal_energy_j,
        settings_.impact_internal_energy_fraction * impact.available_normal_energy_j);
    const double scale = std::sqrt(requested_energy / raw_internal_energy);
    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        matter.nodes[index].velocity_m_s += scale * delta_velocity[index];
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

    for (const ActiveNodeState &node : matter.nodes) {
        const double speed = length(node.velocity_m_s);
        stats.maximum_speed_m_s = std::max(stats.maximum_speed_m_s, speed);
        stats.kinetic_energy_j += 0.5 * node.mass_kg * speed * speed;
    }
    for (std::size_t bond_index = 0; bond_index < matter.bonds.size(); ++bond_index) {
        if (!matter.bonds[bond_index].alive) {
            continue;
        }
        const BondRest &rest = matter.asset->bonds[bond_index];
        const double extension =
            length(matter.nodes[rest.node_b].position_world_m -
                   matter.nodes[rest.node_a].position_world_m) -
            rest.rest_length_m;
        if (rest.compliance > 0.0) {
            stats.estimated_elastic_energy_j += 0.5 * extension * extension / rest.compliance;
        }
    }

    ++matter.step_index;
    return stats;
}

} // namespace banjo
