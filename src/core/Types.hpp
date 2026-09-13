#pragma once

#include <cstdint>
#include <limits>

namespace banjo {

using MatterBodyId = std::uint64_t;
using MaterialId = std::uint32_t;

inline constexpr MatterBodyId kInvalidMatterBodyId = 0;
// The ground plane every rigid world stands on. It is a body like any
// other to the contact callbacks, so anything reporting contacts by name
// needs to be able to recognise it.
inline constexpr MatterBodyId kSupportSurfaceMatterId =
    std::numeric_limits<MatterBodyId>::max() - 1U;
// The terrain: every patch of the height-field ground answers to this one id,
// so contacts with it read as "the ground" exactly as the floor's do.
inline constexpr MatterBodyId kGroundPatchMatterId =
    std::numeric_limits<MatterBodyId>::max() - 2U;
inline constexpr MaterialId kInvalidMaterialId = std::numeric_limits<MaterialId>::max();

enum class MatterMode : std::uint8_t {
    Rigid,
    PendingActivation,
    ActiveMaterial,
    Fragmenting,
    RigidFragments,
};

} // namespace banjo
