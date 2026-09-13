#pragma once

#include "material/Material.hpp"

#include <array>
#include <cstdint>
#include <string_view>

namespace banjo {

enum class MaterialPreset : std::uint8_t {
    Iron,
    Aluminum,
    Glass,
    Ceramic,
    Oak,
    Rubber,
    Ice,
    Concrete,
};

inline constexpr std::array<MaterialPreset, 8> kMaterialPresets{
    MaterialPreset::Iron,
    MaterialPreset::Aluminum,
    MaterialPreset::Glass,
    MaterialPreset::Ceramic,
    MaterialPreset::Oak,
    MaterialPreset::Rubber,
    MaterialPreset::Ice,
    MaterialPreset::Concrete,
};

[[nodiscard]] std::string_view materialPresetName(MaterialPreset preset);
[[nodiscard]] MaterialDefinition makeReferenceMaterial(
    MaterialPreset preset,
    std::uint64_t seed = 0);
[[nodiscard]] MaterialPreset materialPresetFromOrdinal(unsigned ordinal);
[[nodiscard]] MaterialPreset nextMaterialPreset(MaterialPreset preset);

// Where a preset's rolling-resistance share came from. `sourced` means an
// engineering table or a measurement gives it (or bounds it) for this material;
// otherwise it is a DEMONSTRATION value: no measurement was found, and the
// number is carried over from a sourced one by the elastic-hysteresis scaling
// that `basis` states. docs/rolling-resistance.md has the references.
struct RollingResistanceSource {
    bool sourced{};
    std::string_view basis;
};
[[nodiscard]] RollingResistanceSource rollingResistanceSource(MaterialPreset preset);

} // namespace banjo
