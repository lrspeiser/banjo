// A live scene, driven a line at a time.
//
// The playground plays recordings: it asks the engine for a run and gets back a
// film. A live world has to be talked to instead, so this holds one open and
// speaks JSON over stdin and stdout, one object per line -- which is the same
// shape everything else in the playground already uses to reach the engine, and
// needs no new transport on either side.
//
//   in   {"op":"step","dt":0.0166,"n":2}
//        {"op":"grab","name":"ball"}  {"op":"move","to":[0,1.2,0]}  {"op":"release"}
//        {"op":"fracture","name":"pane"}   {"op":"poses"}   {"op":"quit"}
//        {"op":"pick","from":[0,6,0],"dir":[0,-1,0],"max_m":1000}
//   out  {"ok":true,"t":0.033,"stepped_back":false,
//         "bodies":[{"name":"ball","shape":"sphere","dimensions_m":[...],
//                    "position_m":[...],"orientation_wxyz":[...],"held":false,
//                    "anchored":false,"color_rgba":"8a8f99ff"}],
//         "impacts":[{"struck":"pane","by":"ball","closing_speed_m_s":13.9,
//                     "threshold_speed_m_s":4.5,"would_break":true}],
//         "breakable":["pane"]}
//
// Every reply carries the whole world. A scene of a dozen objects is about a
// kilobyte, which is what drawing one authored body per object rather than one
// per cell bought: the same reply for a bowling lane used to be 9,841 poses.
//
// `pick` is the exception. It answers
//
//   {"ok":true,"hit":true,"name":"ball","distance_m":5.36,"point_m":[0,0.64,0]}
//
// and nothing else, because it changes nothing and a pointer asks it on every
// mouse move: carrying 78 poses along with each answer would be most of a
// megabyte a second to say which object is under the cursor. An empty name with
// hit true is the ground -- something stopped the ray, but not one of the
// scene's bodies.

#include "fastlattice/LiveWorld.hpp"

#include <nlohmann/json.hpp>

#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

nlohmann::json vec(const Vec3 &v) { return nlohmann::json::array({v.x, v.y, v.z}); }

nlohmann::json describe(const LiveWorld &world, bool with_geometry) {
    nlohmann::json bodies = nlohmann::json::array();
    for (const LiveBodyPose &pose : world.poses(with_geometry)) {
        char colour[16];
        std::snprintf(colour, sizeof colour, "%08x", pose.color_rgba);
        bodies.push_back({{"name", pose.name}, {"material", pose.material},
                          {"shape", pose.shape},
                          {"dimensions_m", vec(pose.dimensions_m)},
                          {"position_m", vec(pose.position_m)},
                          {"orientation_wxyz", nlohmann::json::array({
                               pose.orientation_wxyz[0], pose.orientation_wxyz[1],
                               pose.orientation_wxyz[2], pose.orientation_wxyz[3]})},
                          {"velocity_m_s", vec(pose.velocity_m_s)},
                          {"anchored", pose.anchored},
                          {"held", pose.held},
                          {"color_rgba", std::string(colour)}});
        if (!pose.cells_local_m.empty()) {
            nlohmann::json cells = nlohmann::json::array();
            for (const Vec3 &at : pose.cells_local_m) cells.push_back(vec(at));
            bodies.back()["cells_local_m"] = std::move(cells);
        }
    }
    nlohmann::json impacts = nlohmann::json::array();
    for (const LiveImpact &impact : world.impacts())
        impacts.push_back({{"struck", impact.struck}, {"by", impact.by},
                           {"closing_speed_m_s", impact.closing_speed_m_s},
                           {"threshold_speed_m_s", impact.threshold_speed_m_s},
                           {"energy_j", impact.energy_j},
                           {"would_break", impact.would_break}});
    return {{"ok", true}, {"t", world.time_s()}, {"stepped_back", world.steppedBack()},
            {"cell_size_m", world.cellSize()}, {"geometry", with_geometry},
            {"held", world.held()}, {"bodies", std::move(bodies)},
            {"impacts", std::move(impacts)}, {"breakable", world.breakable()}};
}

Vec3 readVec(const nlohmann::json &node, const char *key) {
    const auto &v = node.at(key);
    if (!v.is_array() || v.size() != 3) throw std::invalid_argument(std::string(key) + " needs three numbers");
    return Vec3{v[0].get<double>(), v[1].get<double>(), v[2].get<double>()};
}

} // namespace

int main(int argc, char **argv) {
    try {
        TileImpactRequest request;
        request.cell_size_m = 0.02;
        // CUDA is the request default and most builds do not have it; the
        // playground asks for the parallel CPU lane and so does this.
        request.backend = BackendKind::CpuParallel;
        for (int i = 1; i < argc; ++i) {
            const std::string option = argv[i];
            const auto value = [&]() -> std::string {
                if (i + 1 >= argc) throw std::invalid_argument(option + " needs a value");
                return argv[++i];
            };
            if (option == "--scene") {
                // Once. value() walks the argument list forward, so asking it
                // twice eats the next option's value and the engine is handed
                // "0.02" as though it were a flag.
                const std::string path = value();
                request.bodies = readSceneFile(path);
                // The same settings the C face reads, so a scene behaves the
                // same whichever way it reaches the engine.
                std::ifstream input(path);
                if (input)
                    readSceneSettings(std::string(std::istreambuf_iterator<char>(input),
                                                  std::istreambuf_iterator<char>()), request);
            }
            else if (option == "--cell") request.cell_size_m = std::stod(value());
            else if (option == "--ground-material") request.ground_material = presetFromName(value());
            else throw std::invalid_argument("unknown option: " + option);
        }
        if (request.bodies.empty()) throw std::invalid_argument("a live world needs --scene");

        std::unique_ptr<LiveWorld> world = LiveWorld::open(request);
        // The opening state, so a host can draw the scene before it moves.
        std::cout << describe(*world, true).dump() << std::endl;

        std::string line;
        while (std::getline(std::cin, line)) {
            if (line.empty()) continue;
            nlohmann::json reply;
            try {
                const nlohmann::json command = nlohmann::json::parse(line);
                const std::string op = command.value("op", std::string());
                if (op == "quit") break;
                if (op == "step") {
                    const double dt = command.value("dt", 1.0 / 60.0);
                    const int count = std::max(1, command.value("n", 1));
                    // Stop early on a step that was taken back: the world is
                    // one step short of an impact and the host has a decision
                    // to make before time moves again.
                    //
                    // The test is AFTER the step, not before it. Testing first
                    // meant that once a step had been taken back the loop never
                    // ran again -- and since step() is what clears the flag,
                    // nothing could ever clear it. The world froze permanently
                    // at the instant of the first refusal, whatever the host
                    // did about it.
                    for (int s = 0; s < count; ++s) {
                        world->step(dt);
                        if (world->steppedBack()) break;
                    }
                } else if (op == "grab") {
                    if (!world->grab(command.at("name").get<std::string>()))
                        throw std::invalid_argument("that object cannot be picked up");
                } else if (op == "move") {
                    world->moveHeld(readVec(command, "to"));
                } else if (op == "release") {
                    world->release();
                } else if (op == "fracture") {
                    const std::size_t pieces = world->fracture(
                        command.at("name").get<std::string>(),
                        command.value("window_s", 0.003));
                    reply["pieces"] = pieces;
                } else if (op == "pick") {
                    // Changes nothing and reports nothing about the world, so
                    // it answers on its own rather than through describe().
                    const LivePick found = world->pick(readVec(command, "from"),
                                                       readVec(command, "dir"),
                                                       command.value("max_m", 1000.0));
                    nlohmann::json answer{{"ok", true}, {"hit", found.hit},
                                          {"name", found.name},
                                          {"distance_m", found.distance_m},
                                          {"point_m", vec(found.point_world_m)}};
                    std::cout << answer.dump() << std::endl;
                    continue;
                } else if (op != "poses") {
                    throw std::invalid_argument("unknown op: " + op);
                }
                // Geometry travels with the opening state, with an explicit
                // poses request, and after a fracture -- the three moments the
                // set of bodies can have changed. A step never carries it.
                nlohmann::json state = describe(*world, op == "poses" || op == "fracture");
                for (auto &[key, value] : reply.items()) state[key] = value;
                std::cout << state.dump() << std::endl;
            } catch (const std::exception &error) {
                std::cout << nlohmann::json{{"ok", false}, {"error", error.what()}}.dump()
                          << std::endl;
            }
        }
        return 0;
    } catch (const std::exception &error) {
        std::cout << nlohmann::json{{"ok", false}, {"error", error.what()}}.dump() << std::endl;
        return 1;
    }
}
