#include "platform/PlatformWorld.hpp"

#include <nlohmann/json.hpp>

#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_set>

namespace {
using Json = nlohmann::json;
using banjo::PlatformInstance;
using banjo::PlatformWorld;
using banjo::Quat;
using banjo::Vec3;

constexpr std::size_t kMaximumBodies = 4096;
constexpr std::size_t kMaximumBonds = 20000;
constexpr std::size_t kMaximumOutputBytes = 64U * 1024U * 1024U;

void require(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

void finite(double value) {
    require(std::isfinite(value), "playback contains a non-finite number");
}

Json vectorJson(Vec3 value) {
    finite(value.x); finite(value.y); finite(value.z);
    return {value.x, value.y, value.z};
}

Json quaternionJson(Quat value) {
    finite(value.w); finite(value.x); finite(value.y); finite(value.z);
    return {value.w, value.x, value.y, value.z};
}

std::string bodyId(const PlatformInstance &instance) {
    return std::to_string(instance.object_id) + ":" + std::to_string(instance.element_id);
}

Json trianglesJson(const std::vector<std::array<Vec3, 3>> &triangles) {
    Json result = Json::array();
    for (const auto &triangle : triangles)
        result.push_back({vectorJson(triangle[0]), vectorJson(triangle[1]),
                          vectorJson(triangle[2])});
    return result;
}

Json bodyJson(const PlatformInstance &instance) {
    Json body{{"id", bodyId(instance)},
              {"object_id", instance.object_id},
              {"element_id", instance.element_id},
              {"material_id", instance.material_id.empty()
                                  ? std::string(banjo::materialPresetName(instance.material))
                                  : instance.material_id},
              {"color_rgba", instance.color_rgba}};
    if (!instance.local_mesh.empty()) {
        body["shape"] = "mesh";
        body["dimensions_m"] = vectorJson(instance.geometry.dimensions_m);
        body["local_triangles_m"] = trianglesJson(instance.local_mesh);
    } else if (instance.geometry.kind == banjo::PrimitiveKind::Box) {
        body["shape"] = "box";
        body["dimensions_m"] = vectorJson(instance.geometry.dimensions_m);
    } else {
        finite(instance.geometry.radius_m);
        require(instance.geometry.radius_m > 0, "sphere has an invalid radius");
        const double diameter = 2 * instance.geometry.radius_m;
        body["shape"] = "sphere";
        body["dimensions_m"] = {diameter, diameter, diameter};
    }
    return body;
}

Json errorJson(const std::string &message) {
    return Json{{"status", "error"}, {"error", message}};
}

struct Arguments {
    std::filesystem::path package;
    std::filesystem::path output;
    unsigned steps{};
};

Arguments arguments(int argc, char **argv) {
    Arguments result;
    bool have_package = false, have_output = false, have_steps = false;
    for (int i = 1; i < argc; ++i) {
        const std::string option = argv[i];
        require(i + 1 < argc, "each option requires a value");
        const std::string value = argv[++i];
        if (option == "--package" && !have_package) {
            result.package = value; have_package = true;
        } else if (option == "--output" && !have_output) {
            result.output = value; have_output = true;
        } else if (option == "--steps" && !have_steps) {
            std::size_t parsed = 0;
            const unsigned long number = std::stoul(value, &parsed);
            require(parsed == value.size() && number >= 1 && number <= 1440,
                    "steps must be 1..1440");
            result.steps = static_cast<unsigned>(number); have_steps = true;
        } else {
            throw std::runtime_error("usage: playground_record --package PATH --steps N --output NEW_PATH");
        }
    }
    require(have_package && have_output && have_steps,
            "usage: playground_record --package PATH --steps N --output NEW_PATH");
    return result;
}

std::string readPackage(const std::filesystem::path &path) {
    require(std::filesystem::is_regular_file(path), "package path is not a regular file");
    require(std::filesystem::file_size(path) <= 4194304, "package byte budget exceeded");
    std::ifstream input(path, std::ios::binary);
    require(bool(input), "could not open package");
    return {(std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>()};
}

void writeExclusive(const std::filesystem::path &path, const std::string &content) {
    std::ofstream output(path, std::ios::binary | std::ios::out | std::ios::noreplace);
    require(bool(output), "output must be a new writable file");
    output.write(content.data(), static_cast<std::streamsize>(content.size()));
    output.close();
    if (!output) {
        std::error_code ignored;
        std::filesystem::remove(path, ignored);
        throw std::runtime_error("could not write complete playback artifact");
    }
}
} // namespace

int main(int argc, char **argv) {
    try {
        const Arguments args = arguments(argc, argv);
        const auto package_path = std::filesystem::weakly_canonical(args.package);
        const auto output_path = std::filesystem::absolute(args.output).lexically_normal();
        require(package_path != std::filesystem::weakly_canonical(output_path),
                "output path must differ from package path");
        require(!std::filesystem::exists(output_path), "output path already exists");

        auto world = PlatformWorld::load(readPackage(package_path));
        Json artifact{{"schema", "banjo.playback.v1"},
                      {"mode", "network"},
                      {"units", "SI"},
                      {"bodies", Json::array()},
                      {"supports", trianglesJson(world->supportMesh())},
                      {"frames", Json::array()},
                      {"requested_steps", args.steps},
                      {"completed_steps", 0},
                      {"sampling", {{"stride_steps", (args.steps + 119) / 120},
                                     {"maximum_frames", 122},
                                     {"interpolation", "none"}}},
                      {"physical_response_validated", false}};
        auto &bodies = artifact["bodies"];
        auto &frames = artifact["frames"];
        std::unordered_set<std::string> described;
        std::size_t frame_bytes = 0;

        const auto capture = [&](double time) {
            finite(time);
            const auto instances = world->renderInstances();
            require(instances.size() <= kMaximumBodies, "playback body budget exceeded");
            Json poses = Json::array();
            std::unordered_set<std::string> frame_ids;
            for (const auto &instance : instances) {
                const std::string id = bodyId(instance);
                require(frame_ids.insert(id).second, "duplicate body id in rendered state");
                if (!described.contains(id)) {
                    require(described.size() < kMaximumBodies,
                            "playback cumulative body budget exceeded");
                    described.insert(id);
                    bodies.push_back(bodyJson(instance));
                }
                poses.push_back({{"id", id},
                                 {"position_m", vectorJson(instance.state.center_of_mass_world_m)},
                                 {"orientation_wxyz", quaternionJson(instance.state.orientation_world)},
                                 {"component_id", instance.component_id}});
            }
            const auto lines = world->renderBonds();
            require(lines.size() <= kMaximumBonds, "playback bond budget exceeded");
            Json bonds = Json::array();
            for (const auto &line : lines) {
                finite(line.damage);
                require(line.damage >= 0 && line.damage <= 1,
                        "bond damage is outside the supported range");
                bonds.push_back({{"a_m", vectorJson(line.a)}, {"b_m", vectorJson(line.b)},
                                 {"live", line.live}, {"damage", line.damage}});
            }
            Json frame{{"time_s", time}, {"poses", std::move(poses)},
                       {"bonds", std::move(bonds)},
                       {"fracture_count", world->fractureCount()}};
            const std::size_t bytes = frame.dump().size();
            require(bytes <= kMaximumOutputBytes && frame_bytes <= kMaximumOutputBytes - bytes,
                    "playback frame byte budget exceeded");
            frame_bytes += bytes;
            frames.push_back(std::move(frame));
        };

        double elapsed = 0;
        capture(elapsed);
        const unsigned stride = (args.steps + 119) / 120;
        unsigned completed = 0;
        std::string solver_error;
        for (unsigned tick = 1; tick <= args.steps; ++tick) {
            const auto result = world->step(1);
            completed += result.completed_steps;
            elapsed = result.elapsed_s;
            if (!result.error.empty()) {
                solver_error = result.error;
                break;
            }
            if (tick % stride == 0 || tick == args.steps) capture(elapsed);
        }
        if (frames.back().at("time_s").get<double>() != elapsed) capture(elapsed);
        const Json final_report = Json::parse(world->reportJson());

        artifact["report"] = final_report;
        artifact["status"] = solver_error.empty() ? "complete" : "solver_limit";
        artifact["error"] = solver_error;
        artifact["completed_steps"] = completed;
        const std::string serialized = artifact.dump();
        require(serialized.size() <= kMaximumOutputBytes, "playback output exceeds 64 MiB");
        writeExclusive(output_path, serialized);
        std::cout << Json{{"status", artifact["status"]}, {"output", output_path.string()},
                          {"completed_steps", completed}}.dump() << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cout << errorJson(error.what()).dump() << '\n';
        return 1;
    }
}
