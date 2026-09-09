// Driver for the fast explicit lattice lane: a uniform-cube tile struck by a
// rigid ball, impact through fracture through settling, with the wall time
// measured against the simulated duration and a banjo.playback.v1 recording
// for the playground's 3D tab.

#include "fastlattice/TileImpactScene.hpp"
#include "material/MaterialCompiler.hpp"

#include <nlohmann/json.hpp>

#include <chrono>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

using namespace banjo;
using namespace banjo::fastlattice;

MaterialPreset presetFromName(std::string_view name) {
    if (name == "glass") return MaterialPreset::Glass;
    if (name == "oak") return MaterialPreset::Oak;
    if (name == "iron") return MaterialPreset::Iron;
    if (name == "concrete") return MaterialPreset::Concrete;
    if (name == "ceramic") return MaterialPreset::Ceramic;
    if (name == "ice") return MaterialPreset::Ice;
    throw std::invalid_argument("unknown material: " + std::string(name));
}

// A many-object scene, read from a JSON file. Every body shares the run's cell
// size, because the solver's contact radius is one number for the lattice.
//
// {"bodies":[{"name":"pane","shape":"box","material":"glass",
//             "dimensions_m":[0.2,0.01,0.16],"center_m":[0,0.2,0],
//             "velocity_m_s":[0,0,0],"color_rgba":"9fd3ffff"}, ...]}
std::vector<SceneBody> readScene(const std::string &path) {
    std::ifstream input(path);
    if (!input) throw std::invalid_argument("could not open scene " + path);
    const nlohmann::json document = nlohmann::json::parse(input);
    const auto &list = document.contains("bodies") ? document.at("bodies") : document;
    if (!list.is_array() || list.empty()) throw std::invalid_argument("a scene needs a non-empty bodies array");
    const auto vector3 = [](const nlohmann::json &node, const char *key, Vec3 fallback) {
        if (!node.contains(key)) return fallback;
        const auto &v = node.at(key);
        if (!v.is_array() || v.size() != 3) throw std::invalid_argument(std::string(key) + " needs three numbers");
        return Vec3{v[0].get<double>(), v[1].get<double>(), v[2].get<double>()};
    };
    std::vector<SceneBody> bodies;
    for (const auto &node : list) {
        SceneBody body;
        body.name = node.value("name", std::string("body"));
        const std::string shape = node.value("shape", std::string("box"));
        if (shape == "sphere") body.shape = BodyShape::Sphere;
        else if (shape == "box") body.shape = BodyShape::Box;
        else throw std::invalid_argument("unknown shape: " + shape);
        body.material = presetFromName(node.value("material", std::string("glass")));
        body.dimensions_m = vector3(node, "dimensions_m", Vec3{0.1, 0.1, 0.1});
        body.center_m = vector3(node, "center_m", Vec3{});
        body.velocity_m_s = vector3(node, "velocity_m_s", Vec3{});
        // Bodies sharing a join name are voxelised onto the shared grid and
        // unioned, so a cell both claim is built once and bonds cross the seam.
        body.join = node.value("join", std::string());
        body.spin_rad_s = vector3(node, "spin_rad_s", Vec3{});
        // "roll": true derives the spin that rolls without slipping at the
        // speed already given, which is the sign nobody gets right by hand.
        if (node.value("roll", false)) {
            const double radius = 0.5 * body.dimensions_m.x;
            if (radius > 0.0)
                body.spin_rad_s = {body.velocity_m_s.z / radius, 0.0, -body.velocity_m_s.x / radius};
        }
        if (node.contains("color_rgba"))
            body.color_rgba = static_cast<std::uint32_t>(
                std::stoul(node.at("color_rgba").get<std::string>(), nullptr, 16));
        bodies.push_back(std::move(body));
    }
    return bodies;
}

double number(const std::string &value) {
    std::size_t used = 0;
    const double result = std::stod(value, &used);
    if (used != value.size() || !std::isfinite(result)) throw std::invalid_argument("bad number: " + value);
    return result;
}

void usage() {
    std::cout <<
        "usage: banjo_fast_lattice_run [options]\n"
        "  --scene FILE                  a many-object scene: a JSON bodies array of\n"
        "                                {name, shape box|sphere, material, dimensions_m,\n"
        "                                 center_m, velocity_m_s, color_rgba}. Every body\n"
        "                                shares --cell. There is no rigid striker: what\n"
        "                                falls is the body given a velocity, and it can\n"
        "                                break like any other.\n"
        "  --material glass|oak|iron     tile material (reference route for all three)\n"
        "  --ball-material iron|...      striker material\n"
        "  --tile X Y Z                  tile dimensions in metres (Y is the thickness)\n"
        "  --cell H                      uniform cubic cell size in metres\n"
        "  --horizon N                   neighbour horizon in cells (default 2)\n"
        "  --ball-radius R --speed V     striker radius and downward speed at t=0\n"
        "  --gap G                       initial clearance above the tile top (default 0.002)\n"
        "  --offset X Z                  strike offset from the tile centre\n"
        "  --layout flat|bridge          tile on the ground, or on two ledges\n"
        "  --ledge-height H --ledge-width W\n"
        "  --dt-factor F                 substep = F * explicit substep limit (default 0.5)\n"
        "  --iterations N                constraint iterations per substep (default 1)\n"
        "  --catalog                     glass: catalog BrittleBond route (variation, damping)\n"
        "  --failure-law LAW             strain-threshold (default) or energy-scaled\n"
        "  --plasticity on|off           axial plastic flow from the declared yield strength\n"
        "                                (default off: the elastic-plus-damage lane, bit for\n"
        "                                 bit, whatever the material declares)\n"
        "  --hardening R                 linear isotropic hardening, tangent modulus over the\n"
        "  --relax-steps N               after the lattice phase, relax the plate with the\n"
        "                                striker, gravity and the supports removed for N\n"
        "                                substeps and report the shape it holds unloaded\n"
        "                                (the dent). A measurement, not a recorded frame.\n"
        "  --relax-damping F             radial bond damping of that probe (default 0.5)\n"
        "                                Young modulus (default: what the material declares,\n"
        "                                 which is 0, perfect plasticity, for every preset)\n"
        "  --node-radius-factor F        node contact radius = F * cell (default 0.5)\n"
        "  --node-contact on|measure|off node-to-node contact in the lattice phase\n"
        "                                (default on; measure records the overlap and\n"
        "                                 applies nothing; off is the lane without it)\n"
        "  --node-contact-skin F         pair-list skin = F * cell (default 0.25)\n"
        "  --drop H                      start the tile H metres above its support\n"
        "  --loose-cells                 remove every bond: a heap of separate cells,\n"
        "                                a contact scene, no fracture claim\n"
        "  --energy-audit                measure the damping and striker dissipation too\n"
        "  --quiet-ms --min-ms --max-ms --no-failure-ms   lattice phase exit rules\n"
        "  --settle-s S                  rigid settling limit (default 6)\n"
        "  --refracture on|off           let a fragment that is struck hard enough go back\n"
        "                                into the lattice phase and break again (default off:\n"
        "                                 the lane before this existed, bit for bit)\n"
        "  --refracture-events N         re-entries allowed in one run (default 8)\n"
        "  --refracture-steps N          total re-entry substeps allowed (default 600000)\n"
        "  --refracture-window N         longest re-entry window, in rigid steps (default 6)\n"
        "  --refracture-quiet N          end a window after N rigid steps with no failure\n"
        "                                (default 2; 0 always runs the whole window)\n"
        "  --refracture-max-cells N      refuse to re-enter a fragment larger than this\n"
        "  --second-ball R --second-speed V   a second striker of radius R dropped on the\n"
        "                                debris of the first strike at speed V\n"
        "  --second-material NAME --second-offset X Z --second-gap G\n"
        "  --second-at rest|SECONDS      when it appears: at rest (default) or at a time\n"
        "  --second-wait S               give up waiting for rest after S seconds (default 1)\n"
        "  --backend cpu|parallel|gpu --precision float|double --blocks N --threads N\n"
        "  --steps-per-launch N          GPU substeps per kernel launch (0 = one launch)\n"
        "  --frames N                    lattice-phase frames (default 50); --rigid-frames N\n"
        "  --record PATH                 write the banjo.playback.v1 recording\n"
        "  --report PATH                 write the measurement JSON\n"
        "  --compare-steps N             also run BrittleBondSolver for N substeps (flat layout)\n"
        "  --compare-only                skip the full run; only compare\n"
        "  --compare-permuted            reference sweeps bonds in this lane's schedule order\n";
}

} // namespace

int main(int argc, char **argv) {
    try {
        TileImpactRequest request;
        std::string record_path, report_path;
        std::uint64_t compare_steps = 0;
        bool compare_only = false;
        bool compare_permuted = false;
        for (int i = 1; i < argc; ++i) {
            const std::string_view option = argv[i];
            const auto value = [&]() -> std::string {
                if (++i >= argc) throw std::invalid_argument("missing option value");
                return argv[i];
            };
            if (option == "--help" || option == "-h") { usage(); return 0; }
            else if (option == "--scene") request.bodies = readScene(value());
            else if (option == "--material") request.tile_material = presetFromName(value());
            else if (option == "--ball-material") request.ball_material = presetFromName(value());
            else if (option == "--ground-material") request.ground_material = presetFromName(value());
            else if (option == "--tile") { request.tile_dimensions_m.x = number(value()); request.tile_dimensions_m.y = number(value()); request.tile_dimensions_m.z = number(value()); }
            else if (option == "--cell") request.cell_size_m = number(value());
            else if (option == "--horizon") request.neighbor_horizon_cells = static_cast<unsigned>(number(value()));
            else if (option == "--ball-radius") request.ball_radius_m = number(value());
            else if (option == "--speed") request.ball_speed_m_s = number(value());
            else if (option == "--gap") request.ball_gap_m = number(value());
            else if (option == "--offset") { request.ball_offset_x_m = number(value()); request.ball_offset_z_m = number(value()); }
            else if (option == "--layout") { const auto v = value(); request.layout = v == "flat" ? SceneLayout::Flat : SceneLayout::Bridge; }
            else if (option == "--ledge-height") request.ledge_height_m = number(value());
            else if (option == "--ledge-width") request.ledge_width_m = number(value());
            else if (option == "--dt-factor") request.dt_factor = number(value());
            else if (option == "--iterations") request.constraint_iterations = static_cast<unsigned>(number(value()));
            else if (option == "--catalog") request.catalog_material = true;
            else if (option == "--failure-law") request.failure_law = parseBondFailureLaw(value());
            else if (option == "--plasticity") { const auto v = value();
                if (v == "on") request.plasticity = true;
                else if (v == "off") request.plasticity = false;
                else throw std::invalid_argument("--plasticity takes on or off"); }
            else if (option == "--hardening") request.hardening_ratio = number(value());
            else if (option == "--relax-steps") request.relax_steps = static_cast<std::uint64_t>(number(value()));
            else if (option == "--relax-damping") request.relax_damping_fraction = number(value());
            else if (option == "--node-radius-factor") request.node_contact_radius_factor = number(value());
            else if (option == "--node-contact") { const auto v = value();
                if (v == "off") request.node_contact = NodeContactMode::Off;
                else if (v == "measure") request.node_contact = NodeContactMode::Measure;
                else if (v == "on") request.node_contact = NodeContactMode::On;
                else throw std::invalid_argument("--node-contact takes on, measure or off"); }
            else if (option == "--node-contact-skin") request.node_contact_skin_factor = number(value());
            else if (option == "--drop") request.tile_drop_m = number(value());
            else if (option == "--loose-cells") request.loose_cells = true;
            else if (option == "--energy-audit") request.audit_energy = true;
            else if (option == "--quiet-ms") request.quiet_ms = number(value());
            else if (option == "--min-ms") request.min_ms = number(value());
            else if (option == "--max-ms") request.max_ms = number(value());
            else if (option == "--no-failure-ms") request.no_failure_ms = number(value());
            else if (option == "--settle-s") request.settle_limit_s = number(value());
            else if (option == "--refracture") { const auto v = value();
                if (v == "on") request.refracture = true;
                else if (v == "off") request.refracture = false;
                else throw std::invalid_argument("--refracture takes on or off"); }
            else if (option == "--refracture-events") request.refracture_max_events = static_cast<unsigned>(number(value()));
            else if (option == "--refracture-steps") request.refracture_max_steps = static_cast<std::uint64_t>(number(value()));
            else if (option == "--refracture-window") request.refracture_window_steps = static_cast<unsigned>(number(value()));
            else if (option == "--refracture-quiet") request.refracture_quiet_steps = static_cast<unsigned>(number(value()));
            else if (option == "--refracture-max-cells") request.refracture_max_cells = static_cast<std::size_t>(number(value()));
            else if (option == "--refracture-trace") request.refracture_trace = true;
            else if (option == "--second-ball") request.second_ball_radius_m = number(value());
            else if (option == "--second-speed") request.second_ball_speed_m_s = number(value());
            else if (option == "--second-material") request.second_ball_material = presetFromName(value());
            else if (option == "--second-offset") { request.second_ball_offset_x_m = number(value()); request.second_ball_offset_z_m = number(value()); }
            else if (option == "--second-gap") request.second_ball_gap_m = number(value());
            else if (option == "--second-at") { const auto v = value();
                request.second_strike_at_s = v == "rest" ? -1.0 : number(v); }
            else if (option == "--second-wait") request.second_strike_wait_s = number(value());
            else if (option == "--backend") { const auto v = value(); request.backend = v == "cpu" ? BackendKind::Cpu
                : v == "parallel" ? BackendKind::CpuParallel : BackendKind::Cuda; }
            else if (option == "--precision") { const auto v = value(); request.precision = v == "double" ? Precision::Double : Precision::Float; }
            else if (option == "--blocks") request.blocks = static_cast<unsigned>(number(value()));
            else if (option == "--threads") request.threads_per_block = static_cast<unsigned>(number(value()));
            else if (option == "--cpu-threads") request.cpu_threads = static_cast<unsigned>(number(value()));
            else if (option == "--steps-per-launch") request.steps_per_launch = static_cast<std::uint64_t>(number(value()));
            else if (option == "--frames") request.lattice_frames = static_cast<unsigned>(number(value()));
            else if (option == "--rigid-frames") request.rigid_frames = static_cast<unsigned>(number(value()));
            else if (option == "--seed") request.material_seed = static_cast<std::uint64_t>(number(value()));
            else if (option == "--record") record_path = value();
            else if (option == "--report") report_path = value();
            else if (option == "--compare-steps") compare_steps = static_cast<std::uint64_t>(number(value()));
            else if (option == "--compare-only") compare_only = true;
            else if (option == "--compare-permuted") compare_permuted = true;
            else throw std::invalid_argument("unknown option: " + std::string(option));
        }
        nlohmann::json output;
        output["cuda"] = cudaLatticeDescription();
        if (!compare_only) {
            std::string log;
            TileImpactResult result = runTileImpact(request, &log);
            if (!record_path.empty()) {
                const auto begin = std::chrono::steady_clock::now();
                writePlayback(result, record_path);
                result.measurements.recording_wall_s =
                    std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
                output["recording"] = record_path;
            }
            output["measurements"] = nlohmann::json::parse(measurementsJson(result.measurements));
            output["frames"] = result.frames.size();
        }
        if (compare_steps > 0) {
            const SolverComparison comparison = compareWithBrittleBondSolver(
                request, compare_steps, request.precision, request.backend, compare_permuted);
            output["comparison"] = nlohmann::json::parse(comparisonJson(comparison));
        }
        const std::string text = output.dump(2);
        std::cout << text << '\n';
        if (!report_path.empty()) {
            std::ofstream file(report_path, std::ios::binary);
            file << text << '\n';
        }
        return 0;
    } catch (const std::exception &error) {
        std::cout << nlohmann::json{{"status", "error"}, {"error", error.what()}}.dump() << '\n';
        return 1;
    }
}
