#pragma once

#include "core/Math.hpp"
#include "material/MaterialCatalog.hpp"
#include "prediction/BallScenarioProjection.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <unordered_map>

namespace banjo {

struct ScenarioKey {
    MaterialPreset striker{MaterialPreset::Iron};
    MaterialPreset target{MaterialPreset::Glass};
    MaterialPreset surface{MaterialPreset::Concrete};
    std::int32_t radius_micrometers{};
    std::int32_t speed_millimeters_per_second{};
    std::int32_t slope_millidegrees{};
    std::int32_t gravity_x_millimeters_per_second2{};
    std::int32_t gravity_y_millimeters_per_second2{};
    std::int32_t gravity_z_millimeters_per_second2{};
    std::int32_t voxel_micrometers{};
    std::uint64_t material_seed{};

    [[nodiscard]] bool operator==(const ScenarioKey &) const = default;
};

struct ScenarioKeyHash {
    [[nodiscard]] std::size_t operator()(const ScenarioKey &key) const noexcept;
};

struct ProjectionLookup {
    ScenarioProjection projection{};
    bool cache_hit{};
};

[[nodiscard]] ScenarioKey makeScenarioKey(
    MaterialPreset striker,
    MaterialPreset target,
    MaterialPreset surface,
    double radius_m,
    double speed_m_s,
    double slope_degrees,
    const Vec3 &gravity_world_m_s2,
    double voxel_size_m,
    std::uint64_t material_seed);

class ScenarioProjectionCache {
public:
    [[nodiscard]] std::optional<ScenarioProjection> lookup(
        const ScenarioKey &key) const;
    void store(const ScenarioKey &key, const ScenarioProjection &projection);

    [[nodiscard]] ProjectionLookup lookupOrProject(
        const ScenarioKey &key,
        const BallScenarioInput &input);

    [[nodiscard]] std::size_t size() const { return entries_.size(); }
    void clear() { entries_.clear(); }

    void saveCsv(const std::filesystem::path &path) const;
    [[nodiscard]] std::size_t loadCsv(const std::filesystem::path &path);

private:
    std::unordered_map<ScenarioKey, ScenarioProjection, ScenarioKeyHash> entries_;
};

} // namespace banjo
