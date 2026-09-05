#pragma once

#include "core/Math.hpp"
#include "core/Types.hpp"
#include "material/Material.hpp"
#include "matter/Lattice.hpp"

#include <cstdint>
#include <vector>

namespace banjo {

struct RigidSnapshot {
    Vec3 center_of_mass_world_m{};
    Quat orientation_world{};
    Vec3 linear_velocity_m_s{};
    Vec3 angular_velocity_rad_s{};
};

struct ActiveNodeState {
    Vec3 position_world_m{};
    Vec3 previous_position_world_m{};
    Vec3 velocity_m_s{};
    double mass_kg{};
    // Isotropic subcell spin: central bond forces and point contacts apply no
    // nodal torque. Keep it through activation/coarsening instead of losing the
    // rotational momentum and energy represented by finite-cell inertia.
    Vec3 spin_angular_velocity_rad_s{};
};

enum class BondFailureMode : std::uint8_t {
    None,
    Tension,
    Compression,
    Shear,
};

struct ActiveBondState {
    double accumulated_lambda{};
    double damage{};
    double peak_tensile_stretch{};
    double peak_compressive_strain{};
    double peak_shear_strain{};
    BondFailureMode failure_mode{BondFailureMode::None};
    bool alive{true};
};

struct ActiveMatter {
    MatterBodyId body_id{kInvalidMatterBodyId};
    const LatticeAsset *asset{};
    CompiledBrittleMaterial material{};
    std::vector<ActiveNodeState> nodes;
    std::vector<Vec3> reference_positions_world_m;
    std::vector<ActiveBondState> bonds;
    bool connectivity_dirty{};
    std::uint64_t step_index{};
};

} // namespace banjo
