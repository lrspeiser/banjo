#include "prediction/ScenarioCache.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <functional>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace banjo {
namespace {

[[nodiscard]] std::int32_t quantize(double value, double scale) {
    if (!std::isfinite(value)) {
        throw std::invalid_argument("scenario key values must be finite");
    }
    const long long rounded = std::llround(value * scale);
    if (rounded < std::numeric_limits<std::int32_t>::min() ||
        rounded > std::numeric_limits<std::int32_t>::max()) {
        throw std::out_of_range("scenario key value is outside int32 range");
    }
    return static_cast<std::int32_t>(rounded);
}

template <typename Value>
void hashCombine(std::size_t &seed, const Value &value) noexcept {
    const std::size_t hashed = std::hash<Value>{}(value);
    seed ^= hashed + static_cast<std::size_t>(0x9e3779b9U) + (seed << 6U) + (seed >> 2U);
}

[[nodiscard]] auto sortableKey(const ScenarioKey &key) {
    return std::tuple{
        static_cast<unsigned>(key.striker),
        static_cast<unsigned>(key.target),
        static_cast<unsigned>(key.surface),
        key.radius_micrometers,
        key.speed_millimeters_per_second,
        key.slope_millidegrees,
        key.gravity_millimeters_per_second2,
        key.voxel_micrometers,
        key.material_seed,
    };
}

[[nodiscard]] std::vector<std::string> splitCsvLine(const std::string &line) {
    std::vector<std::string> fields;
    std::stringstream stream(line);
    std::string field;
    while (std::getline(stream, field, ',')) {
        fields.push_back(field);
    }
    return fields;
}

[[nodiscard]] unsigned parseUnsigned(const std::string &text) {
    const unsigned long value = std::stoul(text);
    if (value > std::numeric_limits<unsigned>::max()) {
        throw std::out_of_range("CSV unsigned value is too large");
    }
    return static_cast<unsigned>(value);
}

[[nodiscard]] std::int32_t parseInt32(const std::string &text) {
    const long long value = std::stoll(text);
    if (value < std::numeric_limits<std::int32_t>::min() ||
        value > std::numeric_limits<std::int32_t>::max()) {
        throw std::out_of_range("CSV int32 value is too large");
    }
    return static_cast<std::int32_t>(value);
}

} // namespace

std::size_t ScenarioKeyHash::operator()(const ScenarioKey &key) const noexcept {
    std::size_t seed = 0U;
    hashCombine(seed, static_cast<unsigned>(key.striker));
    hashCombine(seed, static_cast<unsigned>(key.target));
    hashCombine(seed, static_cast<unsigned>(key.surface));
    hashCombine(seed, key.radius_micrometers);
    hashCombine(seed, key.speed_millimeters_per_second);
    hashCombine(seed, key.slope_millidegrees);
    hashCombine(seed, key.gravity_millimeters_per_second2);
    hashCombine(seed, key.voxel_micrometers);
    hashCombine(seed, key.material_seed);
    return seed;
}

ScenarioKey makeScenarioKey(
    MaterialPreset striker,
    MaterialPreset target,
    MaterialPreset surface,
    double radius_m,
    double speed_m_s,
    double slope_degrees,
    double gravity_m_s2,
    double voxel_size_m,
    std::uint64_t material_seed) {
    if (radius_m <= 0.0 || speed_m_s < 0.0 || gravity_m_s2 < 0.0 ||
        voxel_size_m <= 0.0) {
        throw std::invalid_argument("scenario key physical values are invalid");
    }
    return {
        striker,
        target,
        surface,
        quantize(radius_m, 1.0e6),
        quantize(speed_m_s, 1.0e3),
        quantize(slope_degrees, 1.0e3),
        quantize(gravity_m_s2, 1.0e3),
        quantize(voxel_size_m, 1.0e6),
        material_seed,
    };
}

std::optional<ScenarioProjection> ScenarioProjectionCache::lookup(
    const ScenarioKey &key) const {
    const auto found = entries_.find(key);
    return found == entries_.end()
               ? std::nullopt
               : std::optional<ScenarioProjection>{found->second};
}

void ScenarioProjectionCache::store(
    const ScenarioKey &key,
    const ScenarioProjection &projection) {
    entries_[key] = projection;
}

ProjectionLookup ScenarioProjectionCache::lookupOrProject(
    const ScenarioKey &key,
    const BallScenarioInput &input) {
    if (const auto cached = lookup(key)) {
        return {*cached, true};
    }
    ScenarioProjection projection = projectBallScenario(input);
    store(key, projection);
    return {projection, false};
}

void ScenarioProjectionCache::saveCsv(const std::filesystem::path &path) const {
    if (path.has_parent_path()) {
        std::filesystem::create_directories(path.parent_path());
    }
    std::ofstream output(path);
    if (!output) {
        throw std::runtime_error("could not open scenario cache for writing");
    }

    output << "striker,target,surface,radius_um,speed_mm_s,slope_mdeg,gravity_mm_s2,"
              "voxel_um,seed,impact_energy_j,peak_force_n,peak_pressure_pa,"
              "fracture_energy_ratio,tensile_stress_ratio,post_striker_m_s,"
              "post_target_m_s,rolling_accel_m_s2,required_static_friction,"
              "combined_static_friction,combined_dynamic_friction,restitution,"
              "failure,regime,strategy,constraint_solves\n";

    std::vector<std::pair<ScenarioKey, ScenarioProjection>> ordered;
    ordered.reserve(entries_.size());
    for (const auto &[key, projection] : entries_) {
        ordered.emplace_back(key, projection);
    }
    std::sort(ordered.begin(), ordered.end(), [](const auto &left, const auto &right) {
        return sortableKey(left.first) < sortableKey(right.first);
    });

    output.precision(17);
    for (const auto &[key, projection] : ordered) {
        const ImpactProjection &impact = projection.impact;
        const InclineProjection &incline = projection.incline;
        output << static_cast<unsigned>(key.striker) << ','
               << static_cast<unsigned>(key.target) << ','
               << static_cast<unsigned>(key.surface) << ','
               << key.radius_micrometers << ','
               << key.speed_millimeters_per_second << ','
               << key.slope_millidegrees << ','
               << key.gravity_millimeters_per_second2 << ','
               << key.voxel_micrometers << ','
               << key.material_seed << ','
               << impact.available_energy_j << ','
               << impact.peak_force_n << ','
               << impact.peak_contact_pressure_pa << ','
               << impact.fracture_energy_ratio << ','
               << impact.tensile_stress_ratio << ','
               << impact.striker_post_speed_m_s << ','
               << impact.target_post_speed_m_s << ','
               << incline.acceleration_along_slope_m_s2 << ','
               << incline.required_static_friction << ','
               << impact.combined_static_friction << ','
               << impact.combined_dynamic_friction << ','
               << impact.combined_restitution << ','
               << static_cast<unsigned>(impact.predicted_failure) << ','
               << static_cast<unsigned>(incline.regime) << ','
               << static_cast<unsigned>(projection.runtime_strategy) << ','
               << projection.estimated_constraint_solves << '\n';
    }
}

std::size_t ScenarioProjectionCache::loadCsv(const std::filesystem::path &path) {
    std::ifstream input(path);
    if (!input) {
        return 0U;
    }

    std::string line;
    if (!std::getline(input, line)) {
        return 0U;
    }

    std::size_t loaded = 0U;
    while (std::getline(input, line)) {
        if (line.empty()) {
            continue;
        }
        const std::vector<std::string> fields = splitCsvLine(line);
        if (fields.size() != 25U) {
            throw std::runtime_error("scenario cache CSV row has unexpected field count");
        }

        ScenarioKey key;
        key.striker = materialPresetFromOrdinal(parseUnsigned(fields[0]));
        key.target = materialPresetFromOrdinal(parseUnsigned(fields[1]));
        key.surface = materialPresetFromOrdinal(parseUnsigned(fields[2]));
        key.radius_micrometers = parseInt32(fields[3]);
        key.speed_millimeters_per_second = parseInt32(fields[4]);
        key.slope_millidegrees = parseInt32(fields[5]);
        key.gravity_millimeters_per_second2 = parseInt32(fields[6]);
        key.voxel_micrometers = parseInt32(fields[7]);
        key.material_seed = std::stoull(fields[8]);

        ScenarioProjection projection;
        projection.impact.available_energy_j = std::stod(fields[9]);
        projection.impact.peak_force_n = std::stod(fields[10]);
        projection.impact.peak_contact_pressure_pa = std::stod(fields[11]);
        projection.impact.fracture_energy_ratio = std::stod(fields[12]);
        projection.impact.tensile_stress_ratio = std::stod(fields[13]);
        projection.impact.striker_post_speed_m_s = std::stod(fields[14]);
        projection.impact.target_post_speed_m_s = std::stod(fields[15]);
        projection.incline.acceleration_along_slope_m_s2 = std::stod(fields[16]);
        projection.incline.required_static_friction = std::stod(fields[17]);
        projection.impact.combined_static_friction = std::stod(fields[18]);
        projection.impact.combined_dynamic_friction = std::stod(fields[19]);
        projection.impact.combined_restitution = std::stod(fields[20]);
        projection.impact.predicted_failure = static_cast<PredictedFailureMode>(
            parseUnsigned(fields[21]));
        projection.incline.regime = static_cast<InclineMotionRegime>(
            parseUnsigned(fields[22]));
        projection.runtime_strategy = static_cast<RuntimeStrategy>(
            parseUnsigned(fields[23]));
        projection.estimated_constraint_solves = std::stoull(fields[24]);
        entries_[key] = projection;
        ++loaded;
    }
    return loaded;
}

} // namespace banjo
