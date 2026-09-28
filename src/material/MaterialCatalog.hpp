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
// The name a SCENE or a package calls it, which is the catalogue's own name
// for every material but the alumina: a scene says "ceramic" where the
// catalogue says "alumina ceramic" (mcp/engine_materials.scene_name, and
// presetFromName, which reads either). A body REPORTS the catalogue name,
// because that is what it is made of; what is read back and echoed as a
// declaration uses this one, so a caller's own words still match it.
[[nodiscard]] std::string_view materialSceneName(MaterialPreset preset);
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
