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
#include <algorithm>
#include <limits>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
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
    bool bench{false};
    bool precompute{false};
    bool gemm_only{false};
    unsigned probe_steps{4000};
    unsigned probe_samples{2};
    double probe_amplitude{-1.0};
    std::uint32_t jump{50};
    unsigned threads{0};
    unsigned spins{0};
    bool exactness{true};
    std::uint64_t exactness_steps{20000};
    double gate_amplitude{1.0e-6};
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


// ---------------------------------------------------------------------------
// The lane
// ---------------------------------------------------------------------------

// Whether a matrix propagator can be exact here at all. The test is the
// definition of affine, applied to the engine's own substep at the amplitude
// the scene reaches: if f(x0 + a + b) - f(x0) differs from the sum of the two
// separate increments by more than rounding, no matrix of any precision
// reproduces the substep, and the lane must not jump. It costs nine substeps.
struct Admissibility {
    bool affine{};
    double additivity_rel{};
    double homogeneity_rel{};
    double amplitude_m{};
    double tolerance{};
    double seconds{};
    std::string reason;
};

Admissibility gate(const TileImpactSetup &setup, const LatticeState &state, double amplitude) {
    const auto begin = Clock::now();
    Admissibility result;
    result.amplitude_m = amplitude;
    // Rounding level for this state vector. The substep works on absolute
    // positions of order 0.1 m, so one ulp there is ~1e-17 m; measured, the
    // probe's own floor is 5e-18 m absolute, which at a 1e-6 m amplitude is
    // 1e-11 relative. A propagator is admissible when the residual is at that
    // level, which is what "exact to floating point" means here.
    result.tolerance = 1.0e-9;
    SubstepMap map(state, setup.schedule, setup.settings_scene, Precision::Double);
    std::vector<double> x0(map.dimension());
    SubstepMap::pack(state, x0.data());
    const LinearityReport report = probeLinearity(map, x0.data(), amplitude, 2, 20260907U);
    result.additivity_rel = report.additivity_rel;
    result.homogeneity_rel = report.homogeneity_rel;
    result.affine = report.additivity_rel <= result.tolerance && report.homogeneity_rel <= result.tolerance;
    if (!result.affine) {
        std::ostringstream reason;
        reason << std::setprecision(3)
               << "the engine's substep is not an affine map on (u, v): the additivity residual is "
               << report.additivity_rel << " of the image at " << amplitude << " m (tolerance "
               << result.tolerance
               << "), so no matrix propagator reproduces it and the lane takes no jumps";
        result.reason = reason.str();
    }
    result.seconds = std::chrono::duration<double>(Clock::now() - begin).count();
    return result;
}

// What one lattice phase produced, for the exactness comparison.
struct LatticeOutcome {
    LatticeState state;
    RunStatus status;
    double wall_s{};
};

RunControl laneControl(const TileImpactSetup &setup) {
    RunControl control{};
    control.max_steps = setup.max_steps;
    control.quiet_steps = setup.quiet_steps;
    control.min_steps = setup.min_steps;
    control.no_failure_steps = setup.no_failure_steps;
    return control;
}

LatticeOutcome runLattice(const TileImpactSetup &setup, const LatticeState &initial,
                          const SphereState<double> &sphere, bool parallel, unsigned threads,
                          Precision precision, const RunControl &control, unsigned spins = 0) {
    LatticeOutcome outcome;
    outcome.state = initial;
    SphereState<double> ball = sphere;
    auto backend = parallel ? makeParallelCpuLatticeBackend(setup.schedule, precision, threads, spins)
                            : makeCpuLatticeBackend(setup.schedule, precision);
    const auto begin = Clock::now();
    backend->upload(outcome.state, setup.settings_scene, ball);
    outcome.status = backend->run(control);
    backend->download(outcome.state, ball);
    outcome.wall_s = std::chrono::duration<double>(Clock::now() - begin).count();
    return outcome;
}

// The bonds that died in the first failing substep, read by running again to
// exactly that step: a capture stride would report everything dead by the next
// capture instead.
std::vector<std::uint32_t> firstFailureBonds(const TileImpactSetup &setup, const LatticeState &initial,
                                             const SphereState<double> &sphere, bool parallel,
                                             unsigned threads, Precision precision,
                                             std::uint64_t first_failure_step) {
    std::vector<std::uint32_t> bonds;
    if (first_failure_step == std::numeric_limits<std::uint64_t>::max()) return bonds;
    RunControl control{};
    control.max_steps = first_failure_step + 1;
    const LatticeOutcome outcome = runLattice(setup, initial, sphere, parallel, threads, precision, control);
    for (std::uint32_t j = 0; j < outcome.state.bond_count; ++j)
        if (!outcome.state.alive[j] && initial.alive[j]) bonds.push_back(setup.schedule.bond_order[j]);
    std::sort(bonds.begin(), bonds.end());
    return bonds;
}


// Wall time of the lattice phase, serial and parallel, so the thread count is
// chosen from measurement rather than from the core count.
int runBench(const LaneOptions &options) {
    auto setup_ptr = buildTileImpactSetup(requestFrom(options));
    TileImpactSetup &setup = *setup_ptr;
    const LatticeState initial = buildLatticeState(setup.matter, setup.schedule, setup.origin);
    SphereState<double> sphere = setup.sphere_world;
    sphere.center = sphere.center - toV3(setup.origin);
    const RunControl control = laneControl(setup);

    nlohmann::json out;
    out["cells"] = setup.asset.nodes.size();
    out["bonds"] = setup.asset.bonds.size();
    out["hardware_concurrency"] = std::thread::hardware_concurrency();
    for (const unsigned threads : {2U, 4U, 8U, 12U, 16U, 24U}) {
        if (threads > std::max(1U, std::thread::hardware_concurrency())) continue;
        for (const unsigned spins : {0U, 100U, 400U, 4000U, 200000U}) {
            const double seconds = measureParallelDispatchCost(threads, spins == 0 ? 1 : spins, 20000);
            out["dispatch_us"].push_back({{"threads", threads},
                                          {"spins", spins == 0 ? 1 : spins},
                                          {"microseconds", seconds * 1.0e6 / 20000.0}});
        }
    }
    const LatticeOutcome reference = runLattice(setup, initial, sphere, false, 1, Precision::Double, control);
    out["serial"] = {{"wall_s", reference.wall_s}, {"substeps", reference.status.total_steps},
                     {"broken", reference.status.broken_bonds}};
    for (const unsigned threads : {4U, 8U, 12U, 16U, 24U}) {
        if (threads > std::max(1U, std::thread::hardware_concurrency())) continue;
        for (const unsigned spins : {100U, 400U, 20000U, 400000U}) {
        const LatticeOutcome lane =
            runLattice(setup, initial, sphere, true, threads, Precision::Double, control, spins);
        double max_du = 0.0;
        for (std::size_t i = 0; i < 3U * static_cast<std::size_t>(initial.node_count); ++i)
            max_du = std::max(max_du, std::abs(lane.state.u[i] - reference.state.u[i]));
        std::size_t mismatches = 0;
        for (std::uint32_t j = 0; j < initial.bond_count; ++j)
            if (lane.state.alive[j] != reference.state.alive[j]) ++mismatches;
        out["parallel"].push_back({{"threads", threads},
                                   {"spins", spins},
                                   {"wall_s", lane.wall_s},
                                   {"speedup", lane.wall_s > 0.0 ? reference.wall_s / lane.wall_s : 0.0},
                                   {"substeps", lane.status.total_steps},
                                   {"broken", lane.status.broken_bonds},
                                   {"max_du_m", max_du},
                                   {"alive_mismatches", mismatches}});
        }
    }
    std::cout << out.dump(2) << std::endl;
    return 0;
}


// What the propagator would cost if it could be used: building P from the
// engine, squaring it up to the jump lengths, the bytes and the cache. The
// gate refuses these powers on this engine (they are not exact), so this mode
// exists to answer the cost question honestly rather than to feed a run.
int runPrecompute(const LaneOptions &options) {
    auto setup_ptr = buildTileImpactSetup(requestFrom(options));
    TileImpactSetup &setup = *setup_ptr;
    const LatticeState initial = buildLatticeState(setup.matter, setup.schedule, setup.origin);
    const std::filesystem::path cache(options.cache);
    const unsigned threads = options.threads == 0 ? defaultLatticeThreadCount() : options.threads;

    nlohmann::json out;
    out["cells"] = setup.asset.nodes.size();
    out["bonds"] = setup.asset.bonds.size();
    out["dimension"] = 6U * setup.asset.nodes.size();
    out["threads"] = threads;
    out["scene_key"] = sceneKey(setup);

    // The unit cost of a squaring, both precisions.
    const std::size_t n = 6U * setup.asset.nodes.size();
    out["gemm"] = {{"n", n},
                   {"double_s", measureGemmSeconds(n, threads, false)},
                   {"float_s", measureGemmSeconds(n, threads, true)},
                   {"double_bytes", n * n * sizeof(double)},
                   {"float_bytes", n * n * sizeof(float)}};
    if (options.gemm_only) {
        std::cout << out.dump(2) << std::endl;
        return 0;
    }

    SubstepMap map(initial, setup.schedule, setup.settings_scene, Precision::Double);
    std::vector<double> x0(map.dimension());
    SubstepMap::pack(initial, x0.data());

    const PropagatorCacheKey key{sceneKey(setup), 1};
    DensePropagator base;
    auto begin = Clock::now();
    bool cached = loadPropagator(cache, key, base);
    if (!cached) {
        base = buildPropagator(map, x0.data(), 1.0e-9);
        storePropagator(cache, key, base);
    }
    out["build"] = {{"seconds", std::chrono::duration<double>(Clock::now() - begin).count()},
                    {"cached", cached},
                    {"bytes", base.bytes()},
                    {"substeps", map.dimension() + 1}};

    // 50 from P, then 200 from 50 and 1000 from 200: twelve multiplies instead
    // of thirty if each power were raised from P.
    double total_bytes = static_cast<double>(base.bytes());
    DensePropagator previous = base;
    std::uint32_t previous_power = 1;
    for (const std::uint32_t m : {50U, 200U, 1000U}) {
        const PropagatorCacheKey power_key{key.scene, m};
        DensePropagator power;
        double gemm_s = 0.0;
        begin = Clock::now();
        const bool hit = loadPropagator(cache, power_key, power);
        if (!hit) {
            power = propagatorPower(previous, m / previous_power, threads, &gemm_s);
            power.power = m;
            storePropagator(cache, power_key, power);
        }
        const double seconds = std::chrono::duration<double>(Clock::now() - begin).count();
        total_bytes += static_cast<double>(power.bytes());
        out["powers"].push_back({{"m", m},
                                 {"from", previous_power},
                                 {"seconds", seconds},
                                 {"gemm_seconds", gemm_s},
                                 {"cached", hit},
                                 {"bytes", power.bytes()}});
        previous = std::move(power);
        previous_power = m;
    }
    out["total_bytes"] = total_bytes;
    std::cout << out.dump(2) << std::endl;
    return 0;
}

int runLane(const LaneOptions &options) {
    if (options.output.empty()) throw std::invalid_argument("--output PATH is required");
    TileImpactRequest request = requestFrom(options);
    request.backend = options.reference ? BackendKind::Cpu : BackendKind::CpuParallel;
    request.cpu_threads = options.threads;

    auto setup_ptr = buildTileImpactSetup(request);
    TileImpactSetup &setup = *setup_ptr;
    const LatticeState initial = buildLatticeState(setup.matter, setup.schedule, setup.origin);
    SphereState<double> sphere = setup.sphere_world;
    sphere.center = sphere.center - toV3(setup.origin);

    // Precompute. The admissibility gate runs first: building P and its powers
    // costs 288 MB and a minute of GEMM, and the gate settles in nine substeps
    // whether any of it can be used.
    nlohmann::json precompute;
    double precompute_s = 0.0, precompute_bytes = 0.0;
    bool precompute_cached = false;
    std::vector<std::uint32_t> jump_powers;
    Admissibility admissibility;
    if (!options.reference) {
        admissibility = gate(setup, initial, options.gate_amplitude);
        precompute_s += admissibility.seconds;
        precompute["gate"] = {{"affine", admissibility.affine},
                              {"additivity_rel", admissibility.additivity_rel},
                              {"homogeneity_rel", admissibility.homogeneity_rel},
                              {"amplitude_m", admissibility.amplitude_m},
                              {"tolerance", admissibility.tolerance},
                              {"seconds", admissibility.seconds},
                              {"reason", admissibility.reason}};
        if (admissibility.affine) {
            // Reached only if the substep is affine after all. The powers are
            // built and cached exactly as the lane would use them; on this
            // engine the gate refuses first.
            const std::filesystem::path cache(options.cache);
            SubstepMap map(initial, setup.schedule, setup.settings_scene, Precision::Double);
            std::vector<double> x0(map.dimension());
            SubstepMap::pack(initial, x0.data());
            const PropagatorCacheKey key{sceneKey(setup), 1};
            DensePropagator base;
            const auto begin = Clock::now();
            if (loadPropagator(cache, key, base)) {
                precompute_cached = true;
            } else {
                base = buildPropagator(map, x0.data(), 1.0e-9);
                storePropagator(cache, key, base);
            }
            precompute_bytes += static_cast<double>(base.bytes());
            for (const std::uint32_t m : {50U, 200U, 1000U}) {
                const PropagatorCacheKey power_key{key.scene, m};
                DensePropagator power;
                if (loadPropagator(cache, power_key, power)) {
                    precompute_cached = true;
                } else {
                    double gemm_s = 0.0;
                    power = propagatorPower(base, m, options.threads, &gemm_s);
                    storePropagator(cache, power_key, power);
                }
                precompute_bytes += static_cast<double>(power.bytes());
                jump_powers.push_back(m);
            }
            precompute_s += std::chrono::duration<double>(Clock::now() - begin).count();
        }
    }

    // The run itself: impact, fracture, connected components, Jolt, recording.
    std::string log;
    const TileImpactResult result = runTileImpact(request, &log);
    const TileImpactMeasurements &m = result.measurements;
    const std::uint64_t first_failure_step =
        m.first_failure_s >= 0.0 ? static_cast<std::uint64_t>(std::llround(m.first_failure_s / setup.dt_s))
                                 : std::numeric_limits<std::uint64_t>::max();

    // Exactness against plain explicit stepping of the same lattice.
    nlohmann::json exactness;
    if (options.exactness) {
        // The comparison runs the whole window twice more, once on one thread.
        // On a long cascade that costs minutes, and the Fracture lab panel
        // gives the lane sixty seconds, so the comparison is capped: it always
        // covers the first failure and the front of the cascade, and the report
        // says how much of the window it covered.
        RunControl control = laneControl(setup);
        const std::uint64_t window = m.lattice_steps;
        const bool full_window = window <= options.exactness_steps;
        control.max_steps = full_window ? window : options.exactness_steps;
        control.quiet_steps = 0;
        control.min_steps = 0;
        control.no_failure_steps = 0;
        const LatticeOutcome reference = runLattice(setup, initial, sphere, false, 1, Precision::Double, control);
        const LatticeOutcome lane =
            options.reference ? reference
                              : runLattice(setup, initial, sphere, true, options.threads, Precision::Double, control, options.spins);
        double max_du = 0.0, max_dv = 0.0, max_damage = 0.0;
        const std::size_t three_n = 3U * static_cast<std::size_t>(reference.state.node_count);
        for (std::size_t i = 0; i < three_n; ++i) {
            max_du = std::max(max_du, std::abs(lane.state.u[i] - reference.state.u[i]));
            max_dv = std::max(max_dv, std::abs(lane.state.v[i] - reference.state.v[i]));
        }
        std::size_t alive_mismatches = 0;
        for (std::uint32_t j = 0; j < reference.state.bond_count; ++j) {
            if (lane.state.alive[j] != reference.state.alive[j]) ++alive_mismatches;
            max_damage = std::max(max_damage, std::abs(lane.state.damage[j] - reference.state.damage[j]));
        }
        const std::vector<std::uint32_t> reference_first = firstFailureBonds(
            setup, initial, sphere, false, 1, Precision::Double, reference.status.first_failure_step);
        const std::vector<std::uint32_t> lane_first =
            options.reference ? reference_first
                              : firstFailureBonds(setup, initial, sphere, true, options.threads,
                                                  Precision::Double, lane.status.first_failure_step);
        exactness = {{"max_du_m", max_du},
                     {"max_dv_m_s", max_dv},
                     {"compared_substeps", control.max_steps},
                     {"window_substeps", window},
                     {"full_window", full_window},
                     {"max_damage_difference", max_damage},
                     {"broken_set_identical", alive_mismatches == 0},
                     {"alive_mismatches", alive_mismatches},
                     {"reference_wall_s", reference.wall_s},
                     {"lane_wall_s", lane.wall_s},
                     {"substeps_reference", reference.status.total_steps},
                     {"substeps_lane", lane.status.total_steps},
                     {"broken_reference", reference.status.broken_bonds},
                     {"broken_lane", lane.status.broken_bonds},
                     {"removed_energy_difference_j",
                      std::abs(lane.status.removed_energy_j - reference.status.removed_energy_j)},
                     {"first_failure_step_reference", reference.status.first_failure_step},
                     {"first_failure_step_lane", lane.status.first_failure_step},
                     {"first_failure_set_identical", reference_first == lane_first},
                     {"speedup_over_reference", lane.wall_s > 0.0 ? reference.wall_s / lane.wall_s : 0.0}};
    } else {
        exactness = {{"max_du_m", nullptr},
                     {"max_dv_m_s", nullptr},
                     {"broken_set_identical", nullptr},
                     {"reference_wall_s", nullptr},
                     {"note", "exactness comparison skipped (--no-exactness)"}};
    }

    const std::vector<std::uint32_t> first_bonds =
        firstFailureBonds(setup, initial, sphere, !options.reference, options.threads, Precision::Double,
                          first_failure_step);

    const double impulse = std::sqrt(m.contact.impulse_to_material_x * m.contact.impulse_to_material_x +
                                     m.contact.impulse_to_material_y * m.contact.impulse_to_material_y +
                                     m.contact.impulse_to_material_z * m.contact.impulse_to_material_z);
    const double window_ratio = m.lattice_simulated_s > 0.0 ? m.lattice_wall_s / m.lattice_simulated_s : 0.0;

    nlohmann::json report;
    report["lane"] = "algo3-propagator-cones";
    report["mode"] = options.reference ? "reference (plain explicit stepping, one thread)"
                                       : "exact lattice; propagator jumps refused by the affineness gate";
    report["backend"] = m.backend_name;
    report["cells"] = m.cells;
    report["bonds"] = m.bonds;
    report["cell_m"] = m.cell_size_m;
    report["dt_s"] = m.dt_s;
    report["precompute_s"] = precompute_s;
    report["precompute_cached"] = precompute_cached;
    report["precompute_bytes"] = precompute_bytes;
    report["precompute"] = precompute;
    report["compute_wall_s"] = m.wall_total_s;
    report["simulated_s"] = m.simulated_total_s;
    report["realtime"] = {{"ratio", m.realtime_ratio},
                          {"simulated_s", m.simulated_total_s},
                          {"compute_wall_s", m.wall_total_s},
                          {"fracture_window_ratio", window_ratio},
                          {"window_simulated_s", m.lattice_simulated_s},
                          {"limit", 1.1}};
    report["jumps"] = {{"m_values", jump_powers},
                       {"count", 0},
                       {"cone_cells_total", 0},
                       {"cone_wall_s", 0.0},
                       {"jump_wall_s", 0.0},
                       {"refused", !options.reference && !admissibility.affine},
                       {"reason", options.reference ? std::string("the reference lane takes no jumps")
                                                    : admissibility.reason}};
    report["contact"] = {{"model", "sphere/node sequential impulses in node order "
                                   "(physics/SphereMaterialContact.cpp), twice per substep"},
                         {"impulse_n_s", impulse},
                         {"impulse_contacts", m.contact.impulse_contacts},
                         {"maximum_penetration_m", m.contact.maximum_penetration_m}};
    report["first_failure"] = {
        {"time_s", m.first_failure_s},
        {"substep", first_failure_step == std::numeric_limits<std::uint64_t>::max()
                        ? -1
                        : static_cast<std::int64_t>(first_failure_step)},
        {"bond_indices", first_bonds}};
    report["broken_bonds"] = m.broken_bonds;
    report["components"] = m.components;
    report["largest_component_cells"] = m.largest_piece_cells;
    report["largest_component_mass_kg"] = m.largest_piece_mass_kg;
    report["removed_energy_j"] = m.removed_energy_j;
    report["exactness"] = exactness;
    report["lattice"] = {{"steps", m.lattice_steps},
                         {"simulated_s", m.lattice_simulated_s},
                         {"wall_s", m.lattice_wall_s},
                         {"failure_rounds", m.failure_rounds},
                         {"exit_reason", m.exit_reason}};
    report["rigid"] = {{"simulated_s", m.rigid_simulated_s},
                       {"wall_s", m.rigid_wall_s},
                       {"came_to_rest", m.came_to_rest}};
    report["threads"] = options.reference
                            ? 1U
                            : (options.threads == 0 ? defaultLatticeThreadCount() : options.threads);

    const std::string report_text = report.dump();
    writePlayback(result, std::filesystem::path(options.output), &report_text);
    std::cout << report.dump(2) << std::endl;
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
        "  --threads N          worker threads (0 = the measured default)\n"
        "  --exactness-steps N  substeps compared against plain stepping (default 20000)\n"
        "  --no-exactness       skip the comparison against plain explicit stepping\n"
        "  --precompute         build and cache P and its powers, report the cost\n"
        "  --bench              time the lattice phase serial and parallel\n"
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
            else if (option == "--bench") options.bench = true;
            else if (option == "--precompute") options.precompute = true;
            else if (option == "--gemm-only") options.gemm_only = true;
            else if (option == "--probe-steps") options.probe_steps = static_cast<unsigned>(number(value()));
            else if (option == "--probe-samples") options.probe_samples = static_cast<unsigned>(number(value()));
            else if (option == "--probe-amplitude") options.probe_amplitude = number(value());
            else if (option == "--jump") options.jump = static_cast<std::uint32_t>(number(value()));
            else if (option == "--threads") options.threads = static_cast<unsigned>(number(value()));
            else if (option == "--no-exactness") options.exactness = false;
            else if (option == "--exactness-steps") options.exactness_steps = static_cast<std::uint64_t>(number(value()));
            else if (option == "--gate-amplitude") options.gate_amplitude = number(value());
            else if (option == "--spins") options.spins = static_cast<unsigned>(number(value()));
            else throw std::invalid_argument("unknown option " + std::string(option));
        }
        if (options.support != "ledges" && options.support != "clamped")
            throw std::invalid_argument("--support must be ledges or clamped");
        if (options.support == "clamped")
            throw std::invalid_argument("clamped support is not implemented in this lane; use --support ledges");
        if (options.probe) return runProbe(options);
        if (options.cone) return runCone(options);
        if (options.bench) return runBench(options);
        if (options.precompute || options.gemm_only) return runPrecompute(options);
        return runLane(options);
    } catch (const std::exception &error) {
        std::cerr << "banjo_fracture_algo3: " << error.what() << "\n";
        return 2;
    }
}
