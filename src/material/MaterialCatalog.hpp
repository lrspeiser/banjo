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

} // namespace banjo
