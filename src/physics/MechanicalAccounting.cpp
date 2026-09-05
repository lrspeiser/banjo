#include "physics/MechanicalAccounting.hpp"

#include <stdexcept>

namespace banjo {

MechanicalTotals &MechanicalTotals::operator+=(const MechanicalTotals &other) {
    mass_kg += other.mass_kg;
    mass_first_moment_kg_m += other.mass_first_moment_kg_m;
    linear_momentum_kg_m_s += other.linear_momentum_kg_m_s;
    angular_momentum_kg_m2_s += other.angular_momentum_kg_m2_s;
    kinetic_energy_j += other.kinetic_energy_j;
    elastic_energy_j += other.elastic_energy_j;
    gravitational_potential_energy_j += other.gravitational_potential_energy_j;
    return *this;
}

MechanicalTotals measureRigidMechanics(
    const RigidMechanicalState &body, const Vec3 &gravity_m_s2) {
    MechanicalTotals result;
    const auto &motion = body.motion;
    result.mass_kg = body.mass_kg;
    result.mass_first_moment_kg_m = body.mass_kg * motion.center_of_mass_world_m;
    result.linear_momentum_kg_m_s = body.mass_kg * motion.linear_velocity_m_s;
    const Vec3 spin = body.inertia_world_kg_m2 * motion.angular_velocity_rad_s;
    result.angular_momentum_kg_m2_s = spin +
        cross(motion.center_of_mass_world_m, result.linear_momentum_kg_m_s);
    result.kinetic_energy_j = 0.5 * body.mass_kg * lengthSquared(motion.linear_velocity_m_s) +
        0.5 * dot(motion.angular_velocity_rad_s, spin);
    result.gravitational_potential_energy_j =
        -dot(gravity_m_s2, result.mass_first_moment_kg_m);
    return result;
}

MechanicalTotals measureMaterialMechanics(
    const ActiveMatter &matter, const Vec3 &gravity_m_s2) {
    if (!matter.asset || matter.bonds.size() != matter.asset->bonds.size()) {
        throw std::invalid_argument("material accounting requires matching lattice state");
    }
    MechanicalTotals result;
    const double h = matter.asset->recipe.voxel_size_m;
    for (const auto &node : matter.nodes) {
        const double cell_inertia = node.mass_kg * h * h / 6.0;
        result.mass_kg += node.mass_kg;
        result.mass_first_moment_kg_m += node.mass_kg * node.position_world_m;
        const Vec3 momentum = node.mass_kg * node.velocity_m_s;
        result.linear_momentum_kg_m_s += momentum;
        result.angular_momentum_kg_m2_s += cross(node.position_world_m, momentum) +
            cell_inertia * node.spin_angular_velocity_rad_s;
        result.kinetic_energy_j += 0.5 * node.mass_kg * lengthSquared(node.velocity_m_s) +
            0.5 * cell_inertia * lengthSquared(node.spin_angular_velocity_rad_s);
    }
    for (std::size_t i = 0; i < matter.bonds.size(); ++i) {
        if (!matter.bonds[i].alive) continue;
        const auto &rest = matter.asset->bonds[i];
        if (rest.compliance <= 0.0) continue;
        const double extension = length(matter.nodes.at(rest.node_b).position_world_m -
            matter.nodes.at(rest.node_a).position_world_m) - rest.rest_length_m;
        result.elastic_energy_j += 0.5 * extension * extension / rest.compliance;
    }
    result.gravitational_potential_energy_j = -dot(gravity_m_s2, result.mass_first_moment_kg_m);
    return result;
}

} // namespace banjo
