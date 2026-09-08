// Algorithm 3 (precomputed multi-step propagators with causal-cone patching)
// against the two premises it rests on and the one exact acceleration it ships.
//
// 1. SubstepMap is the engine's own substep, bit for bit: the probe measures
//    the integrator that exists, not a rederivation of it.
// 2. The substep is NOT an affine map on x = (u, v). With the support planes
//    present the additivity residual is a finite fraction of the image at every
//    amplitude, because the support velocity response switches at zero normal
//    speed; with them removed the residual is smooth and scales as the
//    amplitude over the cell size, because the XPBD constraint is |x_b - x_a| -
//    rest. Either way no matrix reproduces one substep to rounding.
// 3. buildPropagator's matrix is the best linear map there is, and its error on
//    a single substep is the nonlinear floor of point 2, eleven orders above
//    rounding.
// 4. propagatorPower is a correct repeated squaring: P^m applied to a state
//    equals P applied m times, to rounding. The algorithm is right; the map it
//    is applied to is not linear.
// 5. The causal cone is the whole plate. One node's displacement reaches more
//    than ten times the fastest mode's distance in one substep and every cell
//    within ten, because a Gauss-Seidel sweep chains corrections through its
//    colour stages inside one substep.
// 6. The parallel CPU backend is bit identical to the serial one through a
//    fracture cascade: same positions, same velocities, same damage, same
//    broken set, same removed energy, same first failure step.
// 7. The propagator cache round-trips.

#include "fastlattice/FastLattice.hpp"
#include "fastlattice/Propagator.hpp"
#include "fastlattice/TileImpactScene.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <limits>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

void require(bool result, const std::string &message) {
    if (!result) throw std::runtime_error(message);
}

V3<double> toV3(const Vec3 &v) { return {v.x, v.y, v.z}; }

// A small plate on two ledges, struck by an iron ball: the headline scene's
// shape at a size the suite can afford.
TileImpactRequest smallPlate(double speed, double length = 0.06, double width = 0.04) {
    TileImpactRequest request;
    request.tile_material = MaterialPreset::Glass;
    request.ball_material = MaterialPreset::Iron;
    request.tile_dimensions_m = {length, 0.01, width};
    request.cell_size_m = 0.01;
    request.ball_radius_m = 0.03;
    request.ball_speed_m_s = speed;
    request.layout = SceneLayout::Bridge;
    request.backend = BackendKind::Cpu;
    request.precision = Precision::Double;
    return request;
}

struct Scene {
    std::unique_ptr<TileImpactSetup> setup;
    LatticeState state;
    SphereState<double> sphere;

    explicit Scene(const TileImpactRequest &request) {
        setup = buildTileImpactSetup(request);
        state = buildLatticeState(setup->matter, setup->schedule, setup->origin);
        sphere = setup->sphere_world;
        sphere.center = sphere.center - toV3(setup->origin);
    }
};

// -------------------------------------------------------------------------
// 1. The probe probes the engine.
// -------------------------------------------------------------------------
void substepMapIsTheEnginesOwnSubstep() {
    Scene scene(smallPlate(6.0));
    StepSettings<double> settings = scene.setup->settings_scene;
    settings.sphere_enabled = 0;

    // What the engine's own backend does in one substep with contact off.
    LatticeState expected = scene.state;
    SphereState<double> ball = scene.sphere;
    auto backend = makeCpuLatticeBackend(scene.setup->schedule, Precision::Double);
    backend->upload(expected, settings, ball);
    RunControl control{};
    control.max_steps = 1;
    backend->run(control);
    backend->download(expected, ball);

    SubstepMap map(scene.state, scene.setup->schedule, scene.setup->settings_scene, Precision::Double);
    std::vector<double> x(map.dimension()), y(map.dimension()), reference(map.dimension());
    SubstepMap::pack(scene.state, x.data());
    map.apply(x.data(), y.data());
    SubstepMap::pack(expected, reference.data());
    for (std::size_t i = 0; i < y.size(); ++i)
        require(y[i] == reference[i], "SubstepMap is not the engine's own substep");
}

// -------------------------------------------------------------------------
// 2 and 3. The substep is not affine, and the best matrix inherits that error.
// -------------------------------------------------------------------------
void theSubstepIsNotAnAffineMap() {
    Scene scene(smallPlate(6.0));
    std::vector<double> x0(6U * scene.state.node_count);
    SubstepMap::pack(scene.state, x0.data());

    // With the ledges: the residual is a finite fraction of the image, and it
    // does not shrink with the amplitude, because the map is not differentiable
    // where the plate rests.
    {
        SubstepMap map(scene.state, scene.setup->schedule, scene.setup->settings_scene, Precision::Double);
        const LinearityReport coarse = probeLinearity(map, x0.data(), 1.0e-6, 2, 4321U);
        const LinearityReport fine = probeLinearity(map, x0.data(), 1.0e-9, 2, 4321U);
        require(coarse.additivity_rel > 1.0e-3,
                "the supported substep is unexpectedly additive at 1e-6 m: " +
                    std::to_string(coarse.additivity_rel));
        require(fine.additivity_rel > 1.0e-3,
                "the supported substep is unexpectedly additive at 1e-9 m: " +
                    std::to_string(fine.additivity_rel));
    }

    // Without them: a smooth quadratic error, so the residual scales with the
    // amplitude. Ten times the amplitude, about ten times the residual.
    StepSettings<double> free_settings = scene.setup->settings_scene;
    free_settings.support.plane_count = 0;
    SubstepMap map(scene.state, scene.setup->schedule, free_settings, Precision::Double);
    const LinearityReport small = probeLinearity(map, x0.data(), 1.0e-7, 2, 4321U);
    const LinearityReport large = probeLinearity(map, x0.data(), 1.0e-6, 2, 4321U);
    require(small.additivity_rel > 1.0e-9 && large.additivity_rel > 1.0e-6,
            "the unsupported substep is unexpectedly affine");
    const double growth = large.additivity_rel / small.additivity_rel;
    require(growth > 3.0 && growth < 30.0,
            "the unsupported residual does not scale with the amplitude (growth " +
                std::to_string(growth) + " for a tenfold amplitude)");

    // The matrix is the best linear map and carries exactly that error.
    const DensePropagator propagator = buildPropagator(map, x0.data(), 1.0e-9);
    require(propagator.n == x0.size(), "the propagator has the wrong dimension");
    const PropagatorCheck check = checkPropagator(map, propagator, 1.0e-6, 2, 99U);
    require(check.rel_error > 1.0e-6,
            "the propagator reproduces the substep better than the nonlinearity allows");
    require(check.rel_error < 1.0e-2,
            "the propagator is worse than the nonlinear floor; the build is wrong");
}

// -------------------------------------------------------------------------
// 4. Repeated squaring is correct on the linear map it is given.
// -------------------------------------------------------------------------
void propagatorPowerEqualsRepeatedApplication() {
    Scene scene(smallPlate(6.0));
    StepSettings<double> settings = scene.setup->settings_scene;
    settings.support.plane_count = 0;
    SubstepMap map(scene.state, scene.setup->schedule, settings, Precision::Double);
    std::vector<double> x0(map.dimension());
    SubstepMap::pack(scene.state, x0.data());
    const DensePropagator base = buildPropagator(map, x0.data(), 1.0e-9);

    const std::uint32_t m = 7;
    double gemm_seconds = 0.0;
    const DensePropagator power = propagatorPower(base, m, 2, &gemm_seconds);
    require(power.power == m, "the power is mislabelled");

    std::mt19937_64 rng(2026U);
    std::uniform_real_distribution<double> dist(-1.0e-6, 1.0e-6);
    std::vector<double> x(map.dimension()), stepwise(map.dimension()), jumped(map.dimension()),
        work(map.dimension());
    for (std::size_t i = 0; i < x.size(); ++i) x[i] = x0[i] + dist(rng);

    stepwise = x;
    for (std::uint32_t k = 0; k < m; ++k) {
        base.apply(stepwise.data(), work.data());
        stepwise.swap(work);
    }
    power.apply(x.data(), jumped.data());

    double error = 0.0, scale = 0.0;
    for (std::size_t i = 0; i < x.size(); ++i) {
        error = std::max(error, std::abs(jumped[i] - stepwise[i]));
        scale = std::max(scale, std::abs(stepwise[i]));
    }
    require(scale > 0.0, "the stepwise result is empty");
    require(error / scale < 1.0e-9,
            "P^m does not equal m applications of P: relative " + std::to_string(error / scale));
}

// -------------------------------------------------------------------------
// 5. The causal cone is the whole plate.
// -------------------------------------------------------------------------
void causalConeCoversThePlateWithinTenSubsteps() {
    Scene scene(smallPlate(6.0, 0.25, 0.20));
    SubstepMap map(scene.state, scene.setup->schedule, scene.setup->settings_scene, Precision::Double);
    std::vector<double> x0(map.dimension());
    SubstepMap::pack(scene.state, x0.data());

    std::uint32_t seed_node = 0;
    double best = 1.0e30;
    for (std::uint32_t i = 0; i < scene.state.node_count; ++i) {
        const double d = std::abs(scene.state.x0[3 * i]) + std::abs(scene.state.x0[3 * i + 2]);
        if (d < best) { best = d; seed_node = i; }
    }
    const double cell = scene.setup->request.cell_size_m;
    const std::vector<ConeGrowth> growth =
        measureCone(map, x0.data(), seed_node, 1.0e-9, {1, 10}, cell);
    require(growth.size() == 2, "the cone measurement returned the wrong number of checkpoints");

    // What a wave argument would allow in one substep.
    const double mode_cells =
        cell / scene.setup->limit.fastest_mode_period_s * scene.setup->dt_s / cell;
    require(growth[0].max_cell_distance > 10.0 * mode_cells,
            "the one-substep reach (" + std::to_string(growth[0].max_cell_distance) +
                " cells) does not exceed the fastest mode's " + std::to_string(mode_cells));
    require(growth[1].touched_fraction >= 1.0,
            "the cone does not cover the plate within ten substeps: " +
                std::to_string(growth[1].touched_fraction));
}

// -------------------------------------------------------------------------
// 6. The parallel backend is bit identical through a fracture cascade.
// -------------------------------------------------------------------------
void parallelBackendIsBitIdenticalThroughFracture() {
    Scene scene(smallPlate(12.0, 0.12, 0.06));
    RunControl control{};
    control.max_steps = 6000;

    const auto advance = [&](bool parallel, unsigned threads) {
        LatticeState state = scene.state;
        SphereState<double> ball = scene.sphere;
        auto backend = parallel ? makeParallelCpuLatticeBackend(scene.setup->schedule, Precision::Double, threads)
                                : makeCpuLatticeBackend(scene.setup->schedule, Precision::Double);
        backend->upload(state, scene.setup->settings_scene, ball);
        const RunStatus status = backend->run(control);
        backend->download(state, ball);
        return std::pair<LatticeState, RunStatus>{std::move(state), status};
    };

    const auto [serial_state, serial_status] = advance(false, 1);
    require(serial_status.broken_bonds > 0,
            "the cascade test scene did not fracture; it proves nothing");

    for (const unsigned threads : {2U, 4U, 8U}) {
        const auto [parallel_state, parallel_status] = advance(true, threads);
        for (std::size_t i = 0; i < 3U * static_cast<std::size_t>(serial_state.node_count); ++i) {
            require(parallel_state.u[i] == serial_state.u[i],
                    "the parallel backend moved a node differently at " + std::to_string(threads) +
                        " threads");
            require(parallel_state.v[i] == serial_state.v[i],
                    "the parallel backend gave a node a different velocity at " +
                        std::to_string(threads) + " threads");
        }
        for (std::uint32_t j = 0; j < serial_state.bond_count; ++j) {
            require(parallel_state.alive[j] == serial_state.alive[j],
                    "the parallel backend broke a different bond set at " + std::to_string(threads) +
                        " threads");
            require(parallel_state.damage[j] == serial_state.damage[j],
                    "the parallel backend gave a different damage at " + std::to_string(threads) +
                        " threads");
        }
        require(parallel_status.broken_bonds == serial_status.broken_bonds &&
                    parallel_status.removed_energy_j == serial_status.removed_energy_j &&
                    parallel_status.first_failure_step == serial_status.first_failure_step &&
                    parallel_status.failure_rounds == serial_status.failure_rounds &&
                    parallel_status.total_steps == serial_status.total_steps,
                "the parallel backend reported a different cascade at " + std::to_string(threads) +
                    " threads");
    }
    std::cout << "        cascade: " << serial_status.broken_bonds << " bonds, "
              << serial_status.total_steps << " substeps, first failure at "
              << serial_status.first_failure_step << "\n";
}

// -------------------------------------------------------------------------
// 7. The cache round-trips.
// -------------------------------------------------------------------------
void propagatorCacheRoundTrips() {
    Scene scene(smallPlate(6.0, 0.03, 0.02));
    SubstepMap map(scene.state, scene.setup->schedule, scene.setup->settings_scene, Precision::Double);
    std::vector<double> x0(map.dimension());
    SubstepMap::pack(scene.state, x0.data());
    const DensePropagator built = buildPropagator(map, x0.data(), 1.0e-9);

    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() / "banjo-algo3-cache-test";
    std::error_code ec;
    std::filesystem::remove_all(directory, ec);
    const PropagatorCacheKey key{"test-scene;cell=0.01;support=bridge", 1};
    require(storePropagator(directory, key, built), "the propagator did not store");

    DensePropagator loaded;
    require(loadPropagator(directory, key, loaded), "the propagator did not load");
    require(loaded.n == built.n && loaded.power == built.power, "the cache changed the shape");
    for (std::size_t i = 0; i < built.columns.size(); ++i)
        require(loaded.columns[i] == built.columns[i], "the cache changed a matrix entry");
    for (std::size_t i = 0; i < built.offset.size(); ++i)
        require(loaded.offset[i] == built.offset[i] && loaded.base[i] == built.base[i],
                "the cache changed the affine part");

    // A different scene must not load another scene's matrix.
    DensePropagator other;
    require(!loadPropagator(directory, PropagatorCacheKey{"a different scene", 1}, other),
            "the cache handed out a matrix for the wrong scene");
    std::filesystem::remove_all(directory, ec);
}

} // namespace

int main() {
    try {
        substepMapIsTheEnginesOwnSubstep();
        std::cout << "[PASS] SubstepMap is the engine's own substep, bit for bit\n";
        theSubstepIsNotAnAffineMap();
        std::cout << "[PASS] the substep is not an affine map, and the best matrix inherits that error\n";
        propagatorPowerEqualsRepeatedApplication();
        std::cout << "[PASS] P^m equals m applications of P\n";
        causalConeCoversThePlateWithinTenSubsteps();
        std::cout << "[PASS] the causal cone covers the whole plate within ten substeps\n";
        parallelBackendIsBitIdenticalThroughFracture();
        std::cout << "[PASS] the parallel backend is bit identical through a fracture cascade\n";
        propagatorCacheRoundTrips();
        std::cout << "[PASS] the propagator cache round-trips and is keyed by the scene\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
