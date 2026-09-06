#include "world/WorldPackage.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace banjo {
namespace {
using Json = nlohmann::json;

constexpr std::size_t kMaximumDocumentBytes = 4U * 1024U * 1024U;

void require(bool condition, std::string_view message) {
    if (!condition) throw std::invalid_argument(std::string(message));
}

Json parse(const std::string &text) {
    require(text.size() <= kMaximumDocumentBytes, "world package exceeds 4 MiB");
    std::vector<std::set<std::string>> keys;
    return Json::parse(text, [&](int depth, Json::parse_event_t event, Json &value) {
        require(depth <= 24, "world package nesting exceeds 24");
        if (event == Json::parse_event_t::object_start) keys.emplace_back();
        if (event == Json::parse_event_t::key) {
            require(keys.back().insert(value.get<std::string>()).second,
                    "duplicate world package field");
        }
        if (event == Json::parse_event_t::object_end) keys.pop_back();
        return true;
    });
}

void fields(
    const Json &object,
    std::initializer_list<const char *> allowed,
    std::initializer_list<const char *> required = {}) {
    require(object.is_object(), "world package declaration must be an object");
    for (auto it = object.begin(); it != object.end(); ++it) {
        const bool known = std::any_of(allowed.begin(), allowed.end(), [&](const char *field) {
            return it.key() == field;
        });
        require(known, "unknown world package field");
    }
    for (const char *field : required) {
        require(object.contains(field), std::string("missing world package field: ") + field);
    }
}

double number(const Json &value, double minimum, double maximum) {
    require(value.is_number() && !value.is_boolean(), "expected an SI number");
    const double result = value.get<double>();
    require(std::isfinite(result) && result >= minimum && result <= maximum,
            "SI number outside bounds");
    return result;
}

std::uint64_t unsignedInteger(const Json &value, std::uint64_t maximum) {
    require(value.is_number_integer() && !value.is_boolean(), "expected an unsigned integer");
    if (value.is_number_unsigned()) {
        const auto result = value.get<std::uint64_t>();
        require(result <= maximum, "unsigned integer outside bounds");
        return result;
    }
    const auto result = value.get<std::int64_t>();
    require(result >= 0 && static_cast<std::uint64_t>(result) <= maximum,
            "unsigned integer outside bounds");
    return static_cast<std::uint64_t>(result);
}

int signedInteger(const Json &value, int magnitude_limit) {
    require(value.is_number_integer() && !value.is_boolean(), "expected a signed integer");
    if (value.is_number_unsigned()) {
        const auto result = value.get<std::uint64_t>();
        require(result <= static_cast<std::uint64_t>(magnitude_limit),
                "signed integer outside bounds");
        return static_cast<int>(result);
    }
    const auto result = value.get<std::int64_t>();
    require(result >= -static_cast<std::int64_t>(magnitude_limit) &&
                result <= static_cast<std::int64_t>(magnitude_limit),
            "signed integer outside bounds");
    return static_cast<int>(result);
}

std::string text(const Json &value, std::size_t maximum_length) {
    require(value.is_string(), "expected a string");
    auto result = value.get<std::string>();
    require(!result.empty() && result.size() <= maximum_length,
            "string length outside bounds");
    require(std::none_of(result.begin(), result.end(), [](unsigned char character) {
                return character < 32U;
            }),
            "control characters are not allowed");
    return result;
}

ChunkAddress chunkAddress(const Json &value) {
    require(value.is_array() && value.size() == 3, "chunk position requires three integers");
    return {
        signedInteger(value[0], 1'000'000),
        signedInteger(value[1], 1'000'000),
        signedInteger(value[2], 1'000'000),
    };
}

VoxelAddress cellAddress(const Json &value) {
    fields(value, {"chunk", "local"}, {"chunk", "local"});
    const auto &local = value.at("local");
    require(local.is_array() && local.size() == 3, "local position requires three integers");
    return {
        chunkAddress(value.at("chunk")),
        static_cast<unsigned>(unsignedInteger(local[0], 15)),
        static_cast<unsigned>(unsignedInteger(local[1], 15)),
        static_cast<unsigned>(unsignedInteger(local[2], 15)),
    };
}

thermal::MaterialProperties::FuelReaction reaction(const Json &value) {
    fields(value,
           {"activation_temperature_k", "rate_per_s", "heat_of_combustion_j_kg",
            "oxygen_per_kg_fuel"},
           {"activation_temperature_k", "rate_per_s", "heat_of_combustion_j_kg",
            "oxygen_per_kg_fuel"});
    return {
        .enabled = true,
        .activation_temperature_k = number(value.at("activation_temperature_k"), 0.0, 10'000.0),
        .maximum_rate_per_s = number(value.at("rate_per_s"),
                                     std::numeric_limits<double>::min(),
                                     std::numeric_limits<double>::max()),
        .heat_of_combustion_j_kg = number(value.at("heat_of_combustion_j_kg"),
                                          std::numeric_limits<double>::min(),
                                          std::numeric_limits<double>::max()),
        .oxygen_required_kg_per_kg_fuel = number(value.at("oxygen_per_kg_fuel"),
                                                 std::numeric_limits<double>::min(),
                                                 std::numeric_limits<double>::max()),
    };
}

thermal::EnthalpyMaterial phaseChange(const Json &value) {
    fields(value,
           {"liquid_heat_capacity_j_kg_k", "melting_temperature_k", "latent_heat_j_kg"},
           {"liquid_heat_capacity_j_kg_k", "melting_temperature_k", "latent_heat_j_kg"});
    return {
        .liquid_heat_capacity_j_kg_k = number(
            value.at("liquid_heat_capacity_j_kg_k"),
            std::numeric_limits<double>::min(),
            std::numeric_limits<double>::max()),
        .melting_temperature_k = number(value.at("melting_temperature_k"),
                                        std::numeric_limits<double>::min(), 10'000.0),
        .latent_heat_j_kg = number(value.at("latent_heat_j_kg"), 0.0,
                                   std::numeric_limits<double>::max()),
    };
}

ThermalFrontierPolicy frontierPolicy(const Json &value) {
    fields(value,
           {"activation_temperature_difference_k", "maximum_face_probes_per_step",
            "maximum_cells_added_per_step", "maximum_pending_cells"},
           {"activation_temperature_difference_k", "maximum_face_probes_per_step",
            "maximum_cells_added_per_step", "maximum_pending_cells"});
    ThermalFrontierPolicy policy;
    policy.activation_temperature_difference_k = number(
        value.at("activation_temperature_difference_k"), 0.0, 10'000.0);
    policy.maximum_face_probes_per_step = static_cast<unsigned>(
        unsignedInteger(value.at("maximum_face_probes_per_step"), 3'072));
    policy.maximum_cells_added_per_step = static_cast<unsigned>(
        unsignedInteger(value.at("maximum_cells_added_per_step"), 512));
    policy.maximum_pending_cells = static_cast<unsigned>(
        unsignedInteger(value.at("maximum_pending_cells"), 512));
    require(policy.maximum_face_probes_per_step > 0 &&
                policy.maximum_cells_added_per_step > 0 &&
                policy.maximum_pending_cells > 0,
            "thermal frontier work bounds must be positive");
    return policy;
}

} // namespace

std::unique_ptr<SparseThermalWorld> loadWorldPackage(const std::string &document) {
    const Json package = parse(document);
    fields(package,
           {"physics_abi", "units", "voxel_size_m", "materials", "chunks", "regions",
            "heaters"},
           {"physics_abi", "units", "voxel_size_m", "materials", "chunks", "regions"});
    require(package.at("physics_abi").is_string() &&
                package.at("physics_abi") == "banjo-thermal-world-1",
            "unsupported thermal world ABI");
    require(package.at("units").is_string() && package.at("units") == "SI",
            "thermal world package requires SI units");

    const double voxel_size_m = number(package.at("voxel_size_m"), 0.001, 10.0);
    const auto &materials = package.at("materials");
    require(materials.is_array() && !materials.empty() && materials.size() <= 256,
            "world material count outside bounds");
    std::map<unsigned, WorldThermalMaterial> parsed_materials;
    for (const auto &declaration : materials) {
        fields(declaration,
               {"id", "name", "density_kg_m3", "heat_capacity_j_kg_k",
                "conductivity_w_m_k", "fuel_fraction", "oxygen_per_kg_solid", "reaction",
                "phase_change"},
               {"id", "name", "density_kg_m3", "heat_capacity_j_kg_k",
                "conductivity_w_m_k"});
        WorldThermalMaterial material;
        material.id = static_cast<unsigned>(unsignedInteger(declaration.at("id"), 1'000'000));
        require(material.id > 0, "material ID must be positive");
        material.solid_density_kg_m3 = number(declaration.at("density_kg_m3"),
                                              std::numeric_limits<double>::min(), 30'000.0);
        material.fuel_mass_fraction = number(declaration.value("fuel_fraction", Json(0.0)),
                                             0.0, 1.0);
        material.oxygen_kg_per_kg_solid = number(
            declaration.value("oxygen_per_kg_solid", Json(0.0)), 0.0, 10.0);
        material.thermal.display_name = text(declaration.at("name"), 128);
        material.thermal.specific_heat_capacity_j_kg_k = number(
            declaration.at("heat_capacity_j_kg_k"),
            std::numeric_limits<double>::min(), std::numeric_limits<double>::max());
        material.thermal.thermal_conductivity_w_m_k = number(
            declaration.at("conductivity_w_m_k"), 0.0,
            std::numeric_limits<double>::max());
        if (declaration.contains("reaction")) {
            material.thermal.reaction = reaction(declaration.at("reaction"));
        }
        if (declaration.contains("phase_change")) {
            material.phase_change = phaseChange(declaration.at("phase_change"));
            material.phase_change->solid_heat_capacity_j_kg_k =
                material.thermal.specific_heat_capacity_j_kg_k;
        }
        require(!(material.phase_change && material.thermal.reaction.enabled),
                "combined phase-change and reaction law is not implemented");
        require(parsed_materials.emplace(material.id, material).second,
                "duplicate world material ID");
    }

    const auto &chunks = package.at("chunks");
    require(chunks.is_array() && !chunks.empty() && chunks.size() <= 1'000'000,
            "world chunk count outside bounds");
    struct ParsedChunk {
        ChunkAddress address{};
        unsigned material{};
        double temperature_k{};
        double liquid_fraction_at_melt{};
    };
    std::vector<ParsedChunk> parsed_chunks;
    parsed_chunks.reserve(chunks.size());
    std::set<ChunkAddress> chunk_addresses;
    for (const auto &declaration : chunks) {
        fields(declaration,
               {"position", "material", "temperature_k", "liquid_fraction_at_melt"},
               {"position", "material", "temperature_k"});
        ParsedChunk chunk;
        chunk.address = chunkAddress(declaration.at("position"));
        chunk.material = static_cast<unsigned>(unsignedInteger(declaration.at("material"), 1'000'000));
        require(parsed_materials.contains(chunk.material), "chunk references unknown material");
        chunk.temperature_k = number(declaration.at("temperature_k"), 0.0, 10'000.0);
        chunk.liquid_fraction_at_melt = number(
            declaration.value("liquid_fraction_at_melt", Json(0.0)), 0.0, 1.0);
        require(parsed_materials.at(chunk.material).phase_change.has_value() ||
                    chunk.liquid_fraction_at_melt == 0.0,
                "liquid fraction requires a phase-change material");
        require(chunk_addresses.insert(chunk.address).second, "duplicate world chunk position");
        parsed_chunks.push_back(chunk);
    }

    const auto &regions = package.at("regions");
    require(regions.is_array() && regions.size() <= 256, "world region count outside bounds");
    struct ParsedRegion {
        unsigned id{};
        double step_s{};
        std::vector<VoxelAddress> cells;
        std::optional<ThermalFrontierPolicy> frontier;
    };
    std::vector<ParsedRegion> parsed_regions;
    parsed_regions.reserve(regions.size());
    std::size_t total_active_cells = 0;
    std::set<unsigned> region_ids;
    std::set<VoxelAddress> active_addresses;
    for (const auto &declaration : regions) {
        fields(declaration, {"id", "step_s", "cells", "frontier"},
               {"id", "step_s", "cells"});
        ParsedRegion region;
        region.id = static_cast<unsigned>(unsignedInteger(declaration.at("id"), 1'000'000));
        require(region.id > 0 && region_ids.insert(region.id).second,
                "region ID must be positive and unique");
        region.step_s = number(declaration.at("step_s"), 0.001, 1.0);
        const auto &cells = declaration.at("cells");
        require(cells.is_array() && !cells.empty() && cells.size() <= 512,
                "region cell count outside bounds");
        total_active_cells += cells.size();
        require(total_active_cells <= 32'768, "total active cell count outside bounds");
        region.cells.reserve(cells.size());
        for (const auto &cell : cells) {
            const auto address = cellAddress(cell);
            require(chunk_addresses.contains(address.chunk), "region cell references missing chunk");
            require(active_addresses.insert(address).second,
                    "region cells must be globally unique");
            region.cells.push_back(address);
        }
        if (declaration.contains("frontier")) {
            region.frontier = frontierPolicy(declaration.at("frontier"));
        }
        parsed_regions.push_back(std::move(region));
    }

    struct ParsedHeater {
        VoxelAddress cell{};
        double energy_j{};
        double maximum_energy_j{};
    };
    std::vector<ParsedHeater> parsed_heaters;
    if (package.contains("heaters")) {
        const auto &heaters = package.at("heaters");
        require(heaters.is_array() && heaters.size() <= 32'768,
                "heater count outside bounds");
        parsed_heaters.reserve(heaters.size());
        for (const auto &declaration : heaters) {
            fields(declaration, {"cell", "energy_j", "maximum_energy_j"},
                   {"cell", "energy_j", "maximum_energy_j"});
            ParsedHeater heater;
            heater.cell = cellAddress(declaration.at("cell"));
            require(active_addresses.contains(heater.cell),
                    "heater requires a cell in an active region");
            heater.energy_j = number(declaration.at("energy_j"), 0.0,
                                     std::numeric_limits<double>::max());
            heater.maximum_energy_j = number(declaration.at("maximum_energy_j"), 0.0,
                                             std::numeric_limits<double>::max());
            parsed_heaters.push_back(heater);
        }
    }

    auto candidate = std::make_unique<SparseThermalWorld>(voxel_size_m);
    for (auto &[id, material] : parsed_materials) {
        (void)id;
        candidate->addMaterial(std::move(material));
    }
    for (const auto &chunk : parsed_chunks) {
        candidate->addUniformChunk(chunk.address, chunk.material, chunk.temperature_k,
                                   chunk.liquid_fraction_at_melt);
    }
    for (const auto &region : parsed_regions) {
        candidate->activateInsulatedRegion(region.id, region.cells, region.step_s);
        if (region.frontier) {
            candidate->enableThermalFrontier(region.id, *region.frontier, 0.0);
        }
    }
    for (const auto &heater : parsed_heaters) {
        (void)candidate->addHeat(heater.cell, heater.energy_j, heater.maximum_energy_j, 0.0);
    }
    return candidate;
}

} // namespace banjo
