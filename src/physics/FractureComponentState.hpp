#pragma once

#include "physics/FractureTopology.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace banjo {

struct FractureComponentStateLimits {
    std::size_t maximum_local_nodes{65536};
    std::size_t maximum_tetrahedra{16384};
    std::size_t maximum_components{16384};
    std::uint64_t maximum_node_visits{196608};
};

struct FractureComponentState {
    unsigned component{};
    std::vector<unsigned> tetrahedra;
    double mass_kg{};
    Vec3 center_of_mass_m{};
    Vec3 linear_momentum_kg_m_s{};
    Vec3 angular_momentum_about_com_kg_m2_s{};
    Mat3 inertia_about_com_kg_m2{};
    Vec3 center_of_mass_velocity_m_s{};
    Vec3 best_fit_angular_velocity_rad_s{};
    bool inertia_singular{};
    double kinetic_energy_j{};
    double translational_kinetic_energy_j{};
    double rigid_rotational_kinetic_energy_j{};
    // Energy in velocity that the best-fit rigid translation/spin cannot represent.
    double internal_kinetic_energy_j{};
    double kinetic_decomposition_residual_j{};
};

struct FractureComponentStateResult {
    std::vector<FractureComponentState> components;
    Vec3 common_origin_m{};
    double mass_kg{};
    Vec3 linear_momentum_kg_m_s{};
    Vec3 angular_momentum_about_common_origin_kg_m2_s{};
    double kinetic_energy_j{};
    std::uint64_t node_visits{};
};

// Observes accepted component state without assigning fragment velocities or
// applying forces. SmallStrainPatch cannot evolve freely rotating fragments;
// blade loading, cutting laws, finite-strain matter and rigid handoff remain open.
[[nodiscard]] FractureComponentStateResult extractFractureComponentStates(
    const FractureTopology &topology,
    const FractureSeparation &accepted_separation,
    const std::vector<Vec3> &local_positions_m,
    const std::vector<Vec3> &local_velocities_m_s,
    Vec3 common_origin_m = {},
    const FractureComponentStateLimits &limits = {});

} // namespace banjo
