#include "fracture/FragmentMassProperties.hpp"

#include <stdexcept>

namespace banjo {

FragmentMassProperties calculateFragmentMassProperties(
    const ActiveMatter &matter,
    std::span<const std::uint32_t> node_indices) {
    if (matter.asset == nullptr || node_indices.empty()) {
        throw std::invalid_argument("fragment requires at least one material node");
    }

    FragmentMassProperties result;
    Vec3 weighted_position{};
    Vec3 linear_momentum{};
    for (const std::uint32_t index : node_indices) {
        if (index >= matter.nodes.size()) {
            throw std::out_of_range("fragment node index is invalid");
        }
        const ActiveNodeState &node = matter.nodes[index];
        result.mass_kg += node.mass_kg;
        weighted_position += node.mass_kg * node.position_world_m;
        linear_momentum += node.mass_kg * node.velocity_m_s;
    }
    if (result.mass_kg <= 0.0) {
        throw std::runtime_error("fragment has no mass");
    }

    result.center_of_mass_world_m = weighted_position / result.mass_kg;
    result.linear_velocity_m_s = linear_momentum / result.mass_kg;

    const double cell_size = matter.asset->recipe.voxel_size_m;
    for (const std::uint32_t index : node_indices) {
        const ActiveNodeState &node = matter.nodes[index];
        const Vec3 r = node.position_world_m - result.center_of_mass_world_m;
        const double cell_diagonal_inertia = node.mass_kg * cell_size * cell_size / 6.0;

        result.inertia_world_kg_m2.m[0][0] +=
            node.mass_kg * (r.y * r.y + r.z * r.z) + cell_diagonal_inertia;
        result.inertia_world_kg_m2.m[1][1] +=
            node.mass_kg * (r.x * r.x + r.z * r.z) + cell_diagonal_inertia;
        result.inertia_world_kg_m2.m[2][2] +=
            node.mass_kg * (r.x * r.x + r.y * r.y) + cell_diagonal_inertia;
        result.inertia_world_kg_m2.m[0][1] -= node.mass_kg * r.x * r.y;
        result.inertia_world_kg_m2.m[1][0] = result.inertia_world_kg_m2.m[0][1];
        result.inertia_world_kg_m2.m[0][2] -= node.mass_kg * r.x * r.z;
        result.inertia_world_kg_m2.m[2][0] = result.inertia_world_kg_m2.m[0][2];
        result.inertia_world_kg_m2.m[1][2] -= node.mass_kg * r.y * r.z;
        result.inertia_world_kg_m2.m[2][1] = result.inertia_world_kg_m2.m[1][2];

        result.angular_momentum_kg_m2_s +=
            cross(r, node.mass_kg * (node.velocity_m_s - result.linear_velocity_m_s));
    }

    if (const auto inverse = result.inertia_world_kg_m2.inverse()) {
        result.angular_velocity_rad_s = *inverse * result.angular_momentum_kg_m2_s;
    }
    return result;
}

} // namespace banjo
