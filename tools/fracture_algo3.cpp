// Algorithm 3 lane: precomputed multi-step propagators with causal-cone
// patching. This file is the CLI the playground's Fracture lab panel calls.
//
// The lane's premise is that one substep of the lattice integrator, at a fixed
// topology and with the ball contact disabled, is an affine map on the state
// x = (u, v). Whether that premise holds is measured, not assumed: --probe
// reports the additivity and homogeneity residuals of the engine's own
// substep, and every run reports its exactness against plain explicit stepping.

#include "fastlattice/Propagator.hpp"
#include "fastlattice/TileImpactScene.hpp"

#include <nlohmann/json.hpp>

#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

using namespace banjo;
using namespace banjo::fastlattice;
using Clock = std::chrono::steady_clock;

constexpr double kGravity = 9.81;

V3<double> toV3(const Vec3 &v) { return {v.x, v.y, v.z}; }

double number(const std::string &value) {
    std::size_t used = 0;
    const double result = std::stod(value, &used);
    if (used != value.size() || !std::isfinite(result)) throw std::invalid_argument("bad number: " + value);
    return result;
}

struct LaneOptions {
    double plate_l{0.25}, plate_w{0.20}, plate_t{0.01};
    double cell{0.01};
    double ball_diameter{0.06};
    double drop{2.0};
    double speed{-1.0};
    double offset_x{}, offset_z{};
    std::string support{"ledges"};
    double duration{2.0};
    std::string output;
    std::string cache{"build/fracture-cache"};
    bool reference{false};
    Precision precision{Precision::Double};
    // Diagnostics.
    bool probe{false};
    bool cone{false};
    unsigned probe_steps{4000};
    unsigned probe_samples{2};
    double probe_amplitude{-1.0};
    std::uint32_t jump{50};
};

TileImpactRequest requestFrom(const LaneOptions &options) {
    TileImpactRequest request;
    request.tile_material = MaterialPreset::Glass;
    request.ball_material = MaterialPreset::Iron;
    request.tile_dimensions_m = {options.plate_l, options.plate_t, options.plate_w};
    request.cell_size_m = options.cell;
    request.ball_radius_m = 0.5 * options.ball_diameter;
    request.ball_speed_m_s = options.speed >= 0.0 ? options.speed : std::sqrt(2.0 * kGravity * options.drop);
    request.ball_offset_x_m = options.offset_x;
    request.ball_offset_z_m = options.offset_z;
    request.layout = SceneLayout::Bridge;
    request.backend = BackendKind::Cpu;
    request.precision = options.precision;
    request.settle_limit_s = options.duration;
    return request;
}

std::string sceneKey(const TileImpactSetup &setup) {
    const TileImpactRequest &r = setup.request;
    std::ostringstream key;
    key << std::setprecision(17);
    key << "plate=" << r.tile_dimensions_m.x << "," << r.tile_dimensions_m.y << "," << r.tile_dimensions_m.z
        << ";cell=" << r.cell_size_m << ";horizon=" << r.neighbor_horizon_cells
        << ";support=bridge,h=" << r.ledge_height_m << ",w=" << r.ledge_width_m
        << ";material=glass;seed=" << r.material_seed << ";dt=" << setup.dt_s
        << ";iters=" << r.constraint_iterations << ";nodes=" << setup.asset.nodes.size()
        << ";bonds=" << setup.asset.bonds.size();
    return key.str();
}

// Advance the real scene (ball contact live) for `steps` substeps and return
// the state, so the probe can ask about the map where the lane would use it.
void advanceScene(const TileImpactSetup &setup, LatticeState &state, SphereState<double> &sphere,
                  std::uint64_t steps, Precision precision) {
    if (steps == 0) return;
    auto backend = makeCpuLatticeBackend(setup.schedule, precision);
    backend->upload(state, setup.settings_scene, sphere);
    RunControl control{};
    control.max_steps = steps;
    backend->run(control);
    backend->download(state, sphere);
}

nlohmann::json linearityJson(const LinearityReport &r) {
    nlohmann::json row;
    row["amplitude_m"] = r.amplitude_m;
    row["u_image_m"] = r.u_image;
    row["v_image_m_s"] = r.v_image;
    row["u_additivity_m"] = r.u_additivity;
    row["v_additivity_m_s"] = r.v_additivity;
    row["additivity_rel"] = r.additivity_rel;
    row["homogeneity_rel"] = r.homogeneity_rel;
    return row;
}

nlohmann::json checkJson(const PropagatorCheck &c) {
    nlohmann::json row;
    row["amplitude_m"] = c.amplitude_m;
    row["u_error_m"] = c.u_error;
    row["v_error_m_s"] = c.v_error;
    row["u_image_m"] = c.u_image;
    row["v_image_m_s"] = c.v_image;
    row["rel_error"] = c.rel_error;
    return row;
}

int runProbe(const LaneOptions &options) {
    auto setup_ptr = buildTileImpactSetup(requestFrom(options));
    TileImpactSetup &setup = *setup_ptr;
    LatticeState state = buildLatticeState(setup.matter, setup.schedule, setup.origin);
    SphereState<double> sphere = setup.sphere_world;
    sphere.center = sphere.center - toV3(setup.origin);

    nlohmann::json out;
    out["lane"] = "algo3-propagator-cones";
    out["cells"] = setup.asset.nodes.size();
    out["bonds"] = setup.asset.bonds.size();
    out["dt_s"] = setup.dt_s;
    out["dimension"] = 6U * setup.asset.nodes.size();
    out["scene_key"] = sceneKey(setup);

    // Two probe points: the initial state (plate at rest on its ledges, ball
    // still clear) and the state after probe_steps substeps of the real scene,
    // which is inside the window the lane would have to jump over. Two settings
    // at each: the scene's own, and the same with the support planes removed,
    // which separates the contact switches from the bond solve.
    struct Point { std::string name; std::uint64_t step; };
    const std::vector<Point> points{{"initial", 0}, {"loaded", options.probe_steps}};
    const std::vector<double> amplitudes =
        options.probe_amplitude > 0.0 ? std::vector<double>{options.probe_amplitude}
                                      : std::vector<double>{1.0e-12, 1.0e-10, 1.0e-8, 1.0e-6, 1.0e-4};

    for (const Point &point : points) {
        LatticeState here = state;
        SphereState<double> ball = sphere;
        advanceScene(setup, here, ball, point.step, Precision::Double);
        std::size_t broken = 0;
        for (const std::uint8_t alive : here.alive) broken += alive ? 0U : 1U;
        double max_u = 0.0;
        for (std::size_t i = 0; i < 3U * here.node_count; ++i) max_u = std::max(max_u, std::abs(here.u[i]));

        nlohmann::json entry;
        entry["step"] = point.step;
        entry["time_s"] = static_cast<double>(point.step) * setup.dt_s;
        entry["max_u_m"] = max_u;
        entry["broken_bonds"] = broken;

        for (const bool supports : {true, false}) {
            StepSettings<double> settings = setup.settings_scene;
            if (!supports) settings.support.plane_count = 0;
            SubstepMap map(here, setup.schedule, settings, Precision::Double);
            std::vector<double> x0(map.dimension());
            SubstepMap::pack(here, x0.data());

            nlohmann::json block;
            for (const double amplitude : amplitudes)
                block["linearity"].push_back(
                    linearityJson(probeLinearity(map, x0.data(), amplitude, options.probe_samples, 20260907U)));

            // The brief's own acceptance test: build P from the engine and see
            // whether it reproduces a substep on a fresh random state.
            const auto build_begin = Clock::now();
            const DensePropagator p = buildPropagator(map, x0.data(), 1.0e-9);
            block["build_s"] = std::chrono::duration<double>(Clock::now() - build_begin).count();
            block["bytes"] = p.bytes();
            for (const double amplitude : {1.0e-9, 1.0e-7, 1.0e-6, 1.0e-4})
                block["matrix_check"].push_back(
                    checkJson(checkPropagator(map, p, amplitude, options.probe_samples, 777U)));
            entry[supports ? "with_supports" : "no_supports"] = block;
        }
        out["points"][point.name] = entry;
    }
    std::cout << out.dump(2) << std::endl;
    return 0;
}

// The lattice's own signal speed, measured: how far one node's displacement
// has spread after k substeps, counting any nonzero difference.
int runCone(const LaneOptions &options) {
    auto setup_ptr = buildTileImpactSetup(requestFrom(options));
    TileImpactSetup &setup = *setup_ptr;
    LatticeState state = buildLatticeState(setup.matter, setup.schedule, setup.origin);
    SphereState<double> sphere = setup.sphere_world;
    sphere.center = sphere.center - toV3(setup.origin);
    advanceScene(setup, state, sphere, options.probe_steps, Precision::Double);

    nlohmann::json out;
    out["lane"] = "algo3-propagator-cones";
    out["cells"] = setup.asset.nodes.size();
    out["cell_m"] = setup.request.cell_size_m;
    out["dt_s"] = setup.dt_s;
    out["seed_step"] = options.probe_steps;
    // The lattice's fastest mode, which sets the substep: the brief's
    // "measure it, do not assume".
    out["fastest_mode_period_s"] = setup.limit.fastest_mode_period_s;
    out["explicit_substep_limit_s"] = setup.limit.explicit_substep_limit_s;
    const double wave_speed = setup.request.cell_size_m / setup.limit.fastest_mode_period_s;
    out["fastest_mode_cell_speed_m_s"] = wave_speed;
    out["cells_per_substep_from_mode"] = wave_speed * setup.dt_s / setup.request.cell_size_m;

    // Seed at the node nearest the plate centre, where the ball strikes.
    std::uint32_t seed_node = 0;
    double best = 1.0e30;
    for (std::uint32_t i = 0; i < state.node_count; ++i) {
        const double d = std::abs(state.x0[3 * i]) + std::abs(state.x0[3 * i + 2]);
        if (d < best) { best = d; seed_node = i; }
    }
    out["seed_node"] = seed_node;

    const std::vector<std::uint64_t> checkpoints{1, 2, 3, 5, 10, 20, 50, 100, 200};
    StepSettings<double> settings = setup.settings_scene;
    SubstepMap map(state, setup.schedule, settings, Precision::Double);
    std::vector<double> x0(map.dimension());
    SubstepMap::pack(state, x0.data());
    for (const ConeGrowth &g : measureCone(map, x0.data(), seed_node, 1.0e-9, checkpoints,
                                           setup.request.cell_size_m)) {
        nlohmann::json row;
        row["substeps"] = g.substeps;
        row["touched_nodes"] = g.touched_nodes;
        row["touched_fraction"] = g.touched_fraction;
        row["max_cell_distance"] = g.max_cell_distance;
        row["max_du_m"] = g.max_du_m;
        out["cone"].push_back(row);
    }
    std::cout << out.dump(2) << std::endl;
    return 0;
}

void usage() {
    std::cout <<
        "usage: banjo_fracture_algo3 [options]\n"
        "  --plate L W T        plate length, width, thickness in metres\n"
        "  --cell H             uniform cubic cell size in metres\n"
        "  --ball D             ball diameter in metres\n"
        "  --drop H | --speed V drop height or impact speed\n"
        "  --offset X Z         strike offset from the plate centre\n"
        "  --support ledges|clamped\n"
        "  --duration S         simulated seconds (default 2)\n"
        "  --output PATH        banjo.playback.v1 recording\n"
        "  --cache DIR          propagator cache (default build/fracture-cache)\n"
        "  --reference          plain explicit stepping instead of the lane\n"
        "  --precision float|double\n"
        "  --probe              measure the substep map's linearity and exit\n"
        "  --probe-steps N      substeps of the real scene before the loaded probe\n"
        "  --probe-amplitude A  single probe amplitude in metres\n";
}

} // namespace

int main(int argc, char **argv) {
    try {
        LaneOptions options;
        for (int i = 1; i < argc; ++i) {
            const std::string_view option = argv[i];
            const auto value = [&]() -> std::string {
                if (++i >= argc) throw std::invalid_argument("missing value for " + std::string(option));
                return argv[i];
            };
            if (option == "--help" || option == "-h") { usage(); return 0; }
            else if (option == "--plate") { options.plate_l = number(value()); options.plate_w = number(value()); options.plate_t = number(value()); }
            else if (option == "--cell") options.cell = number(value());
            else if (option == "--ball") options.ball_diameter = number(value());
            else if (option == "--drop") options.drop = number(value());
            else if (option == "--speed") options.speed = number(value());
            else if (option == "--offset") { options.offset_x = number(value()); options.offset_z = number(value()); }
            else if (option == "--support") options.support = value();
            else if (option == "--duration") options.duration = number(value());
            else if (option == "--output") options.output = value();
            else if (option == "--cache") options.cache = value();
            else if (option == "--reference") options.reference = true;
            else if (option == "--precision") { const auto v = value(); options.precision = v == "float" ? Precision::Float : Precision::Double; }
            else if (option == "--probe") options.probe = true;
            else if (option == "--cone") options.cone = true;
            else if (option == "--probe-steps") options.probe_steps = static_cast<unsigned>(number(value()));
            else if (option == "--probe-samples") options.probe_samples = static_cast<unsigned>(number(value()));
            else if (option == "--probe-amplitude") options.probe_amplitude = number(value());
            else if (option == "--jump") options.jump = static_cast<std::uint32_t>(number(value()));
            else throw std::invalid_argument("unknown option " + std::string(option));
        }
        if (options.support != "ledges" && options.support != "clamped")
            throw std::invalid_argument("--support must be ledges or clamped");
        if (options.support == "clamped")
            throw std::invalid_argument("clamped support is not implemented in this lane; use --support ledges");
        if (options.probe) return runProbe(options);
        if (options.cone) return runCone(options);
        throw std::invalid_argument("the lane run is not implemented yet; use --probe");
    } catch (const std::exception &error) {
        std::cerr << "banjo_fracture_algo3: " << error.what() << "\n";
        return 2;
    }
}
