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
};

struct ActiveBondState {
    double accumulated_lambda{};
    double damage{};
    double peak_tensile_stretch{};
    bool alive{true};
};

struct ActiveMatter {
    MatterBodyId body_id{kInvalidMatterBodyId};
    const LatticeAsset *asset{};
    CompiledBrittleMaterial material{};
    std::vector<ActiveNodeState> nodes;
    std::vector<ActiveBondState> bonds;
    bool connectivity_dirty{};
    std::uint64_t step_index{};
};

} // namespace banjo
