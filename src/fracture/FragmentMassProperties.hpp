#pragma once

#include "core/Math.hpp"
#include "fracture/ActiveMatter.hpp"

#include <cstdint>
#include <span>

namespace banjo {

struct FragmentMassProperties {
    double mass_kg{};
    Vec3 center_of_mass_world_m{};
    Vec3 linear_velocity_m_s{};
    Mat3 inertia_world_kg_m2{};
    Vec3 angular_momentum_kg_m2_s{};
    Vec3 angular_velocity_rad_s{};
    double source_kinetic_energy_j{};
    double rigid_kinetic_energy_j{};
    double coarsening_kinetic_loss_j{};
};

[[nodiscard]] FragmentMassProperties calculateFragmentMassProperties(
    const ActiveMatter &matter,
    std::span<const std::uint32_t> node_indices);

} // namespace banjo
