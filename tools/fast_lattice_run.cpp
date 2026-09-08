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

double number(const std::string &value) {
    std::size_t used = 0;
    const double result = std::stod(value, &used);
    if (used != value.size() || !std::isfinite(result)) throw std::invalid_argument("bad number: " + value);
    return result;
}

void usage() {
    std::cout <<
        "usage: banjo_fast_lattice_run [options]\n"
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
        "  --node-radius-factor F        node contact radius = F * cell (default 0.5)\n"
        "  --quiet-ms --min-ms --max-ms --no-failure-ms   lattice phase exit rules\n"
        "  --settle-s S                  rigid settling limit (default 6)\n"
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
            else if (option == "--node-radius-factor") request.node_contact_radius_factor = number(value());
            else if (option == "--quiet-ms") request.quiet_ms = number(value());
            else if (option == "--min-ms") request.min_ms = number(value());
            else if (option == "--max-ms") request.max_ms = number(value());
            else if (option == "--no-failure-ms") request.no_failure_ms = number(value());
            else if (option == "--settle-s") request.settle_limit_s = number(value());
            else if (option == "--backend") { const auto v = value(); request.backend = v == "cpu" ? BackendKind::Cpu
                : v == "parallel" ? BackendKind::CpuParallel : BackendKind::Cuda; }
            else if (option == "--precision") { const auto v = value(); request.precision = v == "double" ? Precision::Double : Precision::Float; }
            else if (option == "--blocks") request.blocks = static_cast<unsigned>(number(value()));
            else if (option == "--threads") request.threads_per_block = static_cast<unsigned>(number(value()));
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
