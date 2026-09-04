#pragma once

#include <cstdint>
#include <limits>

namespace banjo {

using MatterBodyId = std::uint64_t;
using MaterialId = std::uint32_t;

inline constexpr MatterBodyId kInvalidMatterBodyId = 0;
inline constexpr MaterialId kInvalidMaterialId = std::numeric_limits<MaterialId>::max();

enum class MatterMode : std::uint8_t {
    Rigid,
    PendingActivation,
    ActiveMaterial,
    Fragmenting,
    RigidFragments,
};

} // namespace banjo
