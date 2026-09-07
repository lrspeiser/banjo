#include "world/WorldPackage.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <map>
#include <nlohmann/json.hpp>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Json = nlohmann::json;
constexpr std::size_t kInputLimit = 256 * 1024, kOutputLimit = 8 * 1024 * 1024;
void require(bool value, const char *message) {
    if (!value)
        throw std::invalid_argument(message);
}
void fields(const Json &o, std::initializer_list<const char *> allowed,
            std::initializer_list<const char *> required = {}) {
    require(o.is_object(), "Expected object");
    for (auto it = o.begin(); it != o.end(); ++it)
        require(std::any_of(allowed.begin(), allowed.end(), [&](auto n) { return it.key() == n; }),
                "Unknown field");
    for (auto n : required)
        require(o.contains(n), "Missing field");
}
double number(const Json &v, double lo, double hi) {
    require(v.is_number() && !v.is_boolean(), "Expected SI number");
    double x = v.get<double>();
    require(std::isfinite(x) && x >= lo && x <= hi, "SI number outside bounds");
    return x;
}
unsigned integer(const Json &v, unsigned lo, unsigned hi) {
    require(v.is_number_integer() && !v.is_boolean(), "Expected integer");
    auto x = v.get<std::int64_t>();
    require(x >= lo && x <= hi, "Integer outside bounds");
    return static_cast<unsigned>(x);
}
int signedInteger(const Json &v, int limit) {
    require(v.is_number_integer() && !v.is_boolean(), "Expected integer");
    auto x = v.get<std::int64_t>();
    require(x >= -limit && x <= limit, "Integer outside bounds");
    return static_cast<int>(x);
}
Json parse(const std::string &text) {
    std::vector<std::set<std::string>> stack;
    return Json::parse(text, [&](int depth, Json::parse_event_t e, Json &v) {
        require(depth <= 20, "Nesting limit");
        if (e == Json::parse_event_t::object_start)
            stack.emplace_back();
        if (e == Json::parse_event_t::key)
            require(stack.back().insert(v.get<std::string>()).second, "Duplicate field");
        if (e == Json::parse_event_t::object_end)
            stack.pop_back();
        return true;
    });
}

struct Parsed {
    Json request, package;
    unsigned frames, jobs, operations;
    double wall_ms, dt, horizon;
};
Parsed validate(const Json &r) {
    fields(
        r,
        {"schema", "voxel_size_m", "materials", "cells", "heater", "step_s", "horizon_s", "limits"},
        {"schema", "voxel_size_m", "materials", "cells", "heater", "step_s", "horizon_s",
         "limits"});
    require(r["schema"] == "banjo.thermal-experiment-request.v1", "Unsupported schema");
    const double size = number(r["voxel_size_m"], .001, 10), dt = number(r["step_s"], .001, .25),
                 horizon = number(r["horizon_s"], .001, 10);
    const double count = horizon / dt;
    require(std::abs(count - std::round(count)) <= 1e-10 * std::max(1., count),
            "Horizon must contain whole fixed steps");
    const auto &materials = r["materials"];
    require(materials.is_array() && !materials.empty() && materials.size() <= 16,
            "Materials must contain 1..16 declarations");
    const auto &cells = r["cells"];
    require(cells.is_array() && !cells.empty() && cells.size() <= 16,
            "Cells must contain 1..16 declarations");
    fields(r["heater"], {"cell_index", "energy_j", "maximum_energy_j"},
           {"cell_index", "energy_j", "maximum_energy_j"});
    fields(r["limits"],
           {"maximum_jobs", "maximum_cell_operations", "maximum_wall_ms", "maximum_frames"},
           {"maximum_jobs", "maximum_cell_operations", "maximum_wall_ms", "maximum_frames"});
    const unsigned jobs = integer(r["limits"]["maximum_jobs"], 1, 4096),
                   operations = integer(r["limits"]["maximum_cell_operations"], 1, 10000000),
                   frames = integer(r["limits"]["maximum_frames"], 2, 1024);
    const double wall = number(r["limits"]["maximum_wall_ms"], .001, 1000);
    Json package = {{"physics_abi", "banjo-thermal-world-1"},
                    {"units", "SI"},
                    {"voxel_size_m", size},
                    {"materials", materials},
                    {"chunks", Json::array()},
                    {"regions", Json::array()},
                    {"heaters", Json::array()}};
    std::set<std::array<int, 6>> addresses;
    std::map<std::array<int, 3>, Json> chunks;
    Json region_cells = Json::array();
    for (const auto &c : cells) {
        fields(c, {"chunk", "local", "material", "temperature_k", "liquid_fraction_at_melt"},
               {"chunk", "local", "material", "temperature_k"});
        require(c["chunk"].is_array() && c["chunk"].size() == 3 && c["local"].is_array() &&
                    c["local"].size() == 3,
                "Cell coordinates require triples");
        std::array<int, 3> chunk{};
        std::array<int, 6> key{};
        for (unsigned a = 0; a < 3; ++a) {
            chunk[a] = signedInteger(c["chunk"][a], 1000000);
            key[a] = chunk[a];
            key[a + 3] = static_cast<int>(integer(c["local"][a], 0, 15));
        }
        require(addresses.insert(key).second, "Duplicate cell");
        Json declaration = {{"position", c["chunk"]},
                            {"material", c["material"]},
                            {"temperature_k", c["temperature_k"]}};
        if (c.contains("liquid_fraction_at_melt"))
            declaration["liquid_fraction_at_melt"] = c["liquid_fraction_at_melt"];
        auto [it, inserted] = chunks.emplace(chunk, declaration);
        require(inserted || it->second == declaration,
                "Cells in one compact chunk require identical initial material and temperature");
        region_cells.push_back({{"chunk", c["chunk"]}, {"local", c["local"]}});
    }
    for (const auto &[key, value] : chunks) {
        (void)key;
        package["chunks"].push_back(value);
    }
    package["regions"].push_back({{"id", 1}, {"step_s", dt}, {"cells", region_cells}});
    const unsigned heater_index =
        integer(r["heater"]["cell_index"], 0, static_cast<unsigned>(cells.size() - 1));
    package["heaters"].push_back({{"cell", region_cells[heater_index]},
                                  {"energy_j", r["heater"]["energy_j"]},
                                  {"maximum_energy_j", r["heater"]["maximum_energy_j"]}});
    (void)number(r["heater"]["energy_j"], 0, 1e12);
    (void)number(r["heater"]["maximum_energy_j"], 0, 1e12);
    return {r, package, frames, jobs, operations, wall, dt, horizon};
}
Json frame(const banjo::SparseThermalWorld &world) {
    Json cells = Json::array();
    for (const auto &c : world.activeCells())
        cells.push_back({{"chunk", {c.address.chunk.x, c.address.chunk.y, c.address.chunk.z}},
                         {"local", {c.address.x, c.address.y, c.address.z}},
                         {"material", c.material},
                         {"temperature_k", c.temperature_k},
                         {"fuel_kg", c.fuel_kg},
                         {"oxygen_kg", c.oxygen_kg},
                         {"liquid_fraction", c.liquid_fraction},
                         {"phase_change", c.phase_change}});
    const auto report = Json::parse(world.reportJson());
    return {{"time_s", cells.empty() ? 0. : world.activeCells().front().region_time_s},
            {"cells", cells},
            {"ledger", report["regions"][0]}};
}
} // namespace
int main() {
    try {
        std::string input;
        char c;
        while (std::cin.get(c)) {
            require(input.size() < kInputLimit, "Input limit");
            input.push_back(c);
        }
        const auto parsed = validate(parse(input));
        auto world = banjo::loadWorldPackage(parsed.package.dump());
        Json frames = Json::array();
        frames.push_back(frame(*world));
        unsigned jobs = 0, operations = 0;
        double wall = 0;
        std::string error;
        while (world->activeCells().front().region_time_s + 1e-12 < parsed.horizon &&
               frames.size() < parsed.frames) {
            if (jobs >= parsed.jobs || operations >= parsed.operations || wall >= parsed.wall_ms) {
                error = "Cumulative experiment work limit exhausted";
                break;
            }
            if (parsed.wall_ms - wall < .001) {
                error = "Cumulative experiment wall-time limit exhausted";
                break;
            }
            banjo::WorldStepBudget budget{parsed.jobs - jobs, parsed.operations - operations,
                                          std::max(.001, parsed.wall_ms - wall)};
            const auto receipt = world->advance(parsed.dt, budget);
            jobs += receipt.completed_jobs;
            operations += receipt.cell_operations;
            wall += receipt.wall_ms;
            if (!receipt.error.empty()) {
                error = receipt.error;
                break;
            }
            frames.push_back(frame(*world));
            if (receipt.maximum_lag_s > 1e-12 &&
                (receipt.count_budget_exhausted || receipt.wall_budget_exhausted)) {
                error = "Thermal experiment remains backlogged under work limits";
                break;
            }
        }
        const auto final_report = Json::parse(world->reportJson());
        const double completed = world->activeCells().front().region_time_s;
        const bool complete = error.empty() && completed + 1e-12 >= parsed.horizon;
        const double remaining = complete ? 0. : std::max(0., parsed.horizon - completed);
        Json output = {
            {"schema", "banjo.thermal-experiment-response.v1"},
            {"status", complete ? "complete" : "solver_limit"},
            {"request", parsed.request},
            {"frames", frames},
            {"completed_time_s", completed},
            {"requested_horizon_s", parsed.horizon},
            {"remaining_duration_s", remaining},
            {"scheduler_backlog_s", final_report["regions"][0]["lag_s"]},
            {"work",
             {{"completed_jobs", jobs},
              {"cell_operations", operations},
              {"wall_ms", wall},
              {"maximum_frames", parsed.frames}}},
            {"final_ledger", final_report["regions"][0]},
            {"limitations",
             Json::array(
                 {"insulated fixed-grid solid thermal reference",
                  "no airflow, smoke, radiation, moisture transport or calibrated combustion",
                  "phase change and reaction cannot be combined",
                  "budget exhaustion preserves and reports the last accepted state"})}};
        if (!complete)
            output["error"] = error.empty() ? "Frame limit exhausted" : error;
        const auto text = output.dump();
        require(text.size() <= kOutputLimit, "Output limit");
        std::cout << text << '\n';
        return 0;
    } catch (const nlohmann::json::parse_error &) {
        std::cout << Json({{"status", "rejected"},
                           {"error", "Malformed JSON thermal experiment request"}})
                         .dump()
                  << '\n';
        return 1;
    } catch (const std::exception &error) {
        std::string diagnostic = error.what();
        if (diagnostic.empty() || diagnostic.size() > 256)
            diagnostic = "Invalid or unsupported bounded thermal experiment request";
        std::cout << Json({{"status", "rejected"}, {"error", diagnostic}}).dump() << '\n';
        return 1;
    }
}
