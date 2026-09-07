// The fast explicit lattice lane against the code it claims to reproduce.
//
// 1. The box lattice follows the sphere generator's bond rules.
// 2. The schedule is a proper edge colouring over adjacent slabs.
// 3. The failure criterion evaluated one element at a time equals
//    fracture/BondFailure.cpp on the same state: same peaks, same damage, same
//    removed bonds, same removed energy (double: to rounding; float: to the
//    precision the displacement formulation promises).
// 4. The CPU backend and the CUDA backend (when built and a device exists)
//    advance the same scene to the same state, in both precisions and with a
//    multi-block slab schedule.
// 5. The colour-order sweep names the same failing bonds as the index-order
//    BrittleBondSolver on a strained lattice, for glass, oak and iron, and
//    stays within Gauss-Seidel ordering noise of it on the impact scene.

#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticeWorking.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "fracture/BondFailure.hpp"
#include "fracture/BrittleBondSolver.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

void require(bool result, const std::string &message) {
    if (!result) throw std::runtime_error(message);
}

struct Lcg {
    std::uint64_t state{0x9e3779b97f4a7c15ULL};
    double next() {
        state = state * 6364136223846793005ULL + 1442695040888963407ULL;
        return static_cast<double>(state >> 11U) * (1.0 / 9007199254740992.0);
    }
    double symmetric() { return 2.0 * next() - 1.0; }
};

CompiledBrittleMaterial referenceMaterial(MaterialPreset preset, double cell, unsigned horizon) {
    const auto material = makeReferenceMaterial(preset, 17);
    return withStrengthDerivedFailure(compileElasticLatticeReference(material, cell, horizon), material);
}

struct Fixture {
    std::unique_ptr<LatticeAsset> asset;
    ActiveMatter matter;
    BoxLatticeLayout layout{};
    Fixture(MaterialPreset preset, Vec3 dims, double cell, unsigned horizon) {
        const auto compiled = referenceMaterial(preset, cell, horizon);
        asset = std::make_unique<LatticeAsset>(generateBoxLattice({dims, cell, horizon}, compiled, &layout));
        matter.asset = asset.get();
        matter.material = compiled;
        for (const auto &node : asset->nodes) {
            matter.nodes.push_back({node.local_position_m, node.local_position_m, {},
                                    node.represented_volume_m3 * compiled.density_kg_m3, {}});
            matter.reference_positions_world_m.push_back(node.local_position_m);
        }
        matter.bonds.resize(asset->bonds.size());
    }
};

void boxLatticeFollowsTheSphereBondRules() {
    const double cell = 0.02;
    const auto compiled = referenceMaterial(MaterialPreset::Glass, cell, 2);
    BoxLatticeLayout layout{};
    const auto box = generateBoxLattice({{5 * cell, 5 * cell, 5 * cell}, cell, 2}, compiled, &layout);
    require(layout.nx == 5 && layout.ny == 5 && layout.nz == 5, "5x5x5 cells");
    require(box.nodes.size() == 125, "125 nodes");
    // The centre node has every offset within grid distance 2: 6 + 12 + 8 + 6.
    const std::uint32_t centre = 2 + 5 * (2 + 5 * 2);
    require(box.adjacency_offsets[centre + 1] - box.adjacency_offsets[centre] == 32, "32 bonds at an interior node");
    for (const auto &bond : box.bonds) {
        const auto &a = box.nodes[bond.node_a].grid, &b = box.nodes[bond.node_b].grid;
        const int dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
        const double d2 = dx * dx + dy * dy + dz * dz;
        require(std::abs(bond.rest_length_m - std::sqrt(d2) * cell) < 1e-15, "rest length is the grid distance");
        require(std::abs(bond.compliance - compiled.bond_compliance * std::max(1.0, d2)) <
                    1e-12 * bond.compliance,
                "compliance scales with the horizon weight");
        require(bond.node_a < bond.node_b, "bonds point to the higher index");
    }
    // Same rules as the sphere generator: a sphere large enough to contain a
    // full-horizon node gives the same compliance for the same offset.
    const auto sphere = generateSphereLattice({0.2, cell, 2, 3}, compiled);
    const auto sphere_centre = std::find_if(sphere.nodes.begin(), sphere.nodes.end(),
        [](const LatticeNodeRest &n) { return n.grid == GridCoord{0, 0, 0}; });
    require(sphere_centre != sphere.nodes.end(), "sphere has a centre node");
    const auto index = static_cast<std::uint32_t>(sphere_centre - sphere.nodes.begin());
    require(sphere.adjacency_offsets[index + 1] - sphere.adjacency_offsets[index] == 32,
            "sphere interior node has 32 bonds too");
    require(std::abs(box.total_mass_kg - 125 * cell * cell * cell * compiled.density_kg_m3) < 1e-12, "uniform mass");
    bool refused = false;
    try { (void)generateBoxLattice({{0.05, 0.04, 0.04}, cell, 2}, compiled); } catch (const std::invalid_argument &) { refused = true; }
    require(refused, "non-integer cell counts are refused");
}

void scheduleIsAProperColouring() {
    Fixture f(MaterialPreset::Glass, {0.12, 0.04, 0.16}, 0.02, 2);
    for (const unsigned requested : {1U, 4U}) {
        const auto slabs = boxLatticeSlabs(f.layout, 2, requested);
        const LatticeSchedule s = buildLatticeSchedule(*f.asset, slabs);
        require(s.block_count == requested, "requested slab count is honoured for an 8-layer tile");
        require(s.color_count > 0 && s.color_count <= 64, "colour count in range");
        std::vector<std::uint32_t> seen(f.asset->bonds.size(), 0);
        for (std::uint32_t block = 0; block < s.block_count; ++block) {
            for (unsigned boundary = 0; boundary < 2; ++boundary) {
                for (std::uint32_t c = 0; c < s.color_count; ++c) {
                    const std::size_t key = (static_cast<std::size_t>(block) * 2 + boundary) * s.color_count + c;
                    std::vector<std::uint8_t> touched(f.asset->nodes.size(), 0);
                    for (std::uint32_t k = s.range_begin[key]; k < s.range_end[key]; ++k) {
                        const BondRest &bond = f.asset->bonds[s.bond_order[k]];
                        require(!touched[bond.node_a] && !touched[bond.node_b], "one colour never shares a node");
                        touched[bond.node_a] = touched[bond.node_b] = 1;
                        ++seen[s.bond_order[k]];
                        const auto blockOf = [&](std::uint32_t node) {
                            return static_cast<std::uint32_t>(std::upper_bound(slabs.begin(), slabs.end(), node) - slabs.begin() - 1);
                        };
                        const std::uint32_t ba = blockOf(bond.node_a), bb = blockOf(bond.node_b);
                        require(std::min(ba, bb) == block, "owner is the lower slab");
                        require((ba != bb) == (boundary == 1), "boundary flag matches the slabs");
                        require(std::max(ba, bb) - std::min(ba, bb) <= 1, "bonds join adjacent slabs only");
                    }
                }
            }
        }
        for (const auto count : seen) require(count == 1, "every bond is swept exactly once");
        std::cout << "  schedule blocks=" << s.block_count << " colours=" << s.color_count
                  << " boundary_bonds=" << s.boundary_bond_count << '\n';
    }
}

// Load a lattice with an affine strain plus noise and kill some bonds.
void deform(Fixture &f, double strain, double noise, double dead_fraction, Lcg &rng) {
    for (auto &node : f.matter.nodes) {
        Vec3 &p = node.position_world_m;
        const Vec3 x = p;
        p.x = x.x * (1 + strain) + 0.3 * strain * x.y + noise * rng.symmetric();
        p.y = x.y * (1 - 0.22 * strain) + noise * rng.symmetric();
        p.z = x.z * (1 - 0.22 * strain) + 0.2 * strain * x.x + noise * rng.symmetric();
        node.velocity_m_s = {rng.symmetric(), rng.symmetric(), rng.symmetric()};
    }
    for (auto &bond : f.matter.bonds) bond.alive = rng.next() >= dead_fraction;
}

void criterionMatchesBondFailure() {
    for (const auto preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        Fixture cpu(preset, {0.12, 0.06, 0.08}, 0.02, 2);
        Lcg rng;
        const double strain = 1.2 * cpu.matter.material.damage_end_stretch;
        deform(cpu, strain, 2e-6, 0.2, rng);
        // CPU lane: one substep's worth of the criterion on a static state.
        resetBondStrainPeaks(cpu.matter);
        accumulateBondStrainPeaks(cpu.matter);
        std::vector<double> peak_t, peak_c, peak_s;
        for (const auto &bond : cpu.matter.bonds) {
            peak_t.push_back(bond.peak_tensile_stretch);
            peak_c.push_back(bond.peak_compressive_strain);
            peak_s.push_back(bond.peak_shear_strain);
        }
        accumulateBondStrainPeaks(cpu.matter);
        std::vector<std::uint32_t> removed;
        const BondFailureSummary summary = applyBondFailure(cpu.matter, &removed);
        require(summary.newly_broken > 0, "the fixture must break something");

        for (const Precision precision : {Precision::Double, Precision::Float}) {
            Fixture fast(preset, {0.12, 0.06, 0.08}, 0.02, 2);
            Lcg rng2;
            deform(fast, strain, 2e-6, 0.2, rng2);
            const LatticeSchedule schedule = buildLatticeSchedule(*fast.asset);
            LatticeState state = buildLatticeState(fast.matter, schedule, {});
            StepSettings<double> settings{};
            settings.dt = 1e-6;
            settings.constraint_iterations = 1;
            settings.direct_arithmetic = precision == Precision::Double ? 1 : 0;
            settings.sphere_enabled = 0;
            SphereState<double> sphere{};
            sphere.radius = sphere.mass = sphere.inertia = 1.0;
            const auto run = [&](auto real_tag) {
                using Real = decltype(real_tag);
                WorkingLattice<Real> w = WorkingLattice<Real>::fromState(state, schedule);
                LatticeArrays<Real> L = w.arrays();
                const bool direct = settings.direct_arithmetic != 0;
                for (std::uint32_t i = 0; i < L.node_count; ++i) nodeStrain(L, i, direct);
                for (std::uint32_t j = 0; j < L.bond_count; ++j) if (L.alive[j]) bondStartSample(L, j, direct);
                double max_peak_error = 0.0;
                std::uint32_t worst = 0;
                for (std::uint32_t j = 0; j < L.bond_count; ++j) {
                    if (!L.alive[j]) continue;
                    const std::uint32_t o = schedule.bond_order[j];
                    const double error = std::max({
                        std::abs(static_cast<double>(L.prev_tensile[j]) - peak_t[o]),
                        std::abs(static_cast<double>(L.prev_compressive[j]) - peak_c[o]),
                        std::abs(static_cast<double>(L.prev_shear[j]) - peak_s[o])});
                    if (error > max_peak_error) { max_peak_error = error; worst = j; }
                }
                if (max_peak_error > 1e-9) {
                    const std::uint32_t o = schedule.bond_order[worst];
                    const auto live = [&](std::uint32_t n) {
                        std::uint32_t count = 0;
                        for (std::uint32_t k = L.adj_offsets[n]; k < L.adj_offsets[n + 1]; ++k) count += L.alive[L.adj_bonds[k]];
                        return count;
                    };
                    std::cout << "    worst bond " << o << " (" << L.bond_a[worst] << "-" << L.bond_b[worst]
                              << "): cpu t/c/s = " << peak_t[o] << " " << peak_c[o] << " " << peak_s[o]
                              << " fast = " << L.prev_tensile[worst] << " " << L.prev_compressive[worst] << " "
                              << L.prev_shear[worst] << " valid a/b = " << int(L.node_valid[L.bond_a[worst]])
                              << "/" << int(L.node_valid[L.bond_b[worst]]) << " live a/b = "
                              << live(L.bond_a[worst]) << "/" << live(L.bond_b[worst]) << '\n';
                }
                double removed_energy = 0.0;
                std::size_t broken = 0, alive_mismatch = 0, mode_mismatch = 0;
                double max_damage_error = 0.0;
                for (std::uint32_t j = 0; j < L.bond_count; ++j) {
                    if (!L.alive[j]) continue;
                    const FailureOutcome out = bondEndSampleAndFailure(L, j, direct);
                    if (out.broke) { removed_energy += out.removed_energy_j; ++broken; }
                    const std::uint32_t o = schedule.bond_order[j];
                    const ActiveBondState &ref = cpu.matter.bonds[o];
                    if ((L.alive[j] != 0) != ref.alive) ++alive_mismatch;
                    if (!ref.alive && static_cast<BondFailureMode>(L.failure_mode[j]) != ref.failure_mode) ++mode_mismatch;
                    max_damage_error = std::max(max_damage_error, std::abs(static_cast<double>(L.damage[j]) - ref.damage));
                }
                const double energy_error = std::abs(removed_energy - summary.removed_elastic_energy_j) /
                                            std::max(1e-12, summary.removed_elastic_energy_j);
                std::cout << "  " << materialPresetName(preset) << " " << precisionName(precision)
                          << ": bonds=" << L.bond_count << " broken=" << broken << "/" << summary.newly_broken
                          << " max_peak_err=" << max_peak_error << " max_damage_err=" << max_damage_error
                          << " energy_rel_err=" << energy_error << " alive_mismatch=" << alive_mismatch
                          << " mode_mismatch=" << mode_mismatch << '\n';
                const double tolerance = precision == Precision::Double ? 1e-13 : 2e-6;
                require(max_peak_error <= tolerance, "resolved strain peaks equal the CPU criterion");
                require(broken == summary.newly_broken && alive_mismatch == 0, "same removed bond set");
                require(mode_mismatch == 0, "same failure modes");
                require(max_damage_error <= (precision == Precision::Double ? 1e-12 : 1e-4), "same damage");
                require(energy_error <= (precision == Precision::Double ? 1e-12 : 1e-5), "same removed energy");
            };
            if (precision == Precision::Double) run(double{}); else run(float{});
        }
    }
}

TileImpactRequest smallScene(BackendKind backend, Precision precision, unsigned blocks) {
    TileImpactRequest r;
    r.tile_dimensions_m = {0.12, 0.04, 0.16};
    r.cell_size_m = 0.02;
    r.ball_radius_m = 0.03;
    r.ball_speed_m_s = 6.0;
    r.ball_gap_m = 0.0005;
    r.layout = SceneLayout::Flat;
    r.backend = backend;
    r.precision = precision;
    r.blocks = blocks;
    r.threads_per_block = 256;
    return r;
}

struct Advanced {
    LatticeState state;
    SphereState<double> sphere;
    RunStatus status;
};

Advanced advance(const TileImpactRequest &request, std::uint64_t steps, std::uint64_t steps_per_launch = 0) {
    auto setup = buildTileImpactSetup(request);
    Advanced out;
    out.state = buildLatticeState(setup->matter, setup->schedule, setup->origin);
    out.sphere = setup->sphere_world;
    out.sphere.center = out.sphere.center - V3<double>{setup->origin.x, setup->origin.y, setup->origin.z};
    std::unique_ptr<LatticeBackend> backend = request.backend == BackendKind::Cuda
        ? makeCudaLatticeBackend(setup->schedule, request.precision, request.threads_per_block)
        : makeCpuLatticeBackend(setup->schedule, request.precision);
    backend->upload(out.state, setup->settings_scene, out.sphere);
    RunControl control{};
    control.max_steps = steps;
    control.steps_per_launch = steps_per_launch;
    out.status = backend->run(control);
    backend->download(out.state, out.sphere);
    return out;
}

double maxDifference(const std::vector<double> &a, const std::vector<double> &b) {
    require(a.size() == b.size(), "comparable arrays");
    double m = 0.0;
    for (std::size_t i = 0; i < a.size(); ++i) m = std::max(m, std::abs(a[i] - b[i]));
    return m;
}

std::size_t aliveMismatches(const LatticeState &a, const LatticeState &b) {
    std::size_t n = 0;
    for (std::size_t j = 0; j < a.alive.size(); ++j) n += a.alive[j] != b.alive[j];
    return n;
}

void backendsAgree() {
    const std::uint64_t steps = 400;
    const Advanced cpu_double = advance(smallScene(BackendKind::Cpu, Precision::Double, 1), steps);
    const Advanced cpu_float = advance(smallScene(BackendKind::Cpu, Precision::Float, 1), steps);
    require(cpu_double.status.total_steps == steps, "cpu double ran every step");
    require(cpu_double.status.contact.impulse_contacts > 0, "the ball touches the tile within the window");
    const double float_vs_double = maxDifference(cpu_double.state.u, cpu_float.state.u);
    std::cout << "  cpu float vs cpu double: max |du| = " << float_vs_double
              << " m, alive mismatches " << aliveMismatches(cpu_double.state, cpu_float.state)
              << ", broken " << cpu_double.status.broken_bonds << "/" << cpu_float.status.broken_bonds << '\n';
    require(float_vs_double < 1e-6, "float displacement path stays within a micrometre of double");
    if (!cudaLatticeAvailable()) {
        std::cout << "  [SKIP] CUDA backend not available: " << cudaLatticeDescription() << '\n';
        return;
    }
    const Advanced gpu_double = advance(smallScene(BackendKind::Cuda, Precision::Double, 1), steps);
    const Advanced gpu_float = advance(smallScene(BackendKind::Cuda, Precision::Float, 1), steps);
    const Advanced gpu_float_4 = advance(smallScene(BackendKind::Cuda, Precision::Float, 4), steps, 37);
    const Advanced cpu_float_4 = advance(smallScene(BackendKind::Cpu, Precision::Float, 4), steps);
    const double dd = maxDifference(cpu_double.state.u, gpu_double.state.u);
    const double dv = maxDifference(cpu_double.state.v, gpu_double.state.v);
    const double ff = maxDifference(cpu_float.state.u, gpu_float.state.u);
    const double f4 = maxDifference(cpu_float_4.state.u, gpu_float_4.state.u);
    std::cout << "  cuda double vs cpu double: max |du| = " << dd << " m, max |dv| = " << dv
              << " m/s, alive mismatches " << aliveMismatches(cpu_double.state, gpu_double.state) << '\n';
    std::cout << "  cuda float vs cpu float: max |du| = " << ff << " m, alive mismatches "
              << aliveMismatches(cpu_float.state, gpu_float.state) << '\n';
    std::cout << "  cuda float 4 blocks (37 steps/launch) vs cpu float 4 blocks: max |du| = " << f4
              << " m, alive mismatches " << aliveMismatches(cpu_float_4.state, gpu_float_4.state)
              << ", launches " << gpu_float_4.status.launches << '\n';
    require(dd < 1e-10, "cuda double reproduces cpu double to rounding");
    require(aliveMismatches(cpu_double.state, gpu_double.state) == 0, "same bonds alive (double)");
    require(ff < 1e-8, "cuda float reproduces cpu float to float rounding");
    require(aliveMismatches(cpu_float.state, gpu_float.state) == 0, "same bonds alive (float)");
    require(f4 < 1e-8, "multi-block slab sweep reproduces the single-thread colour sweep");
    require(gpu_float_4.status.launches == (steps + 36) / 37, "steps per launch honoured");
    require(std::abs(gpu_double.sphere.center.y - cpu_double.sphere.center.y) < 1e-10, "sphere state agrees");
}

// A 3x3x3 cubic lattice of unit-spaced nodes with axis-aligned bonds only,
// as tests/implicit_fracture_tests.cpp builds it.
struct AxisLattice {
    LatticeAsset asset;
    ActiveMatter matter;
    std::vector<Vec3> directions;
    explicit AxisLattice(const CompiledBrittleMaterial &material) {
        asset.recipe.voxel_size_m = 1;
        for (int z = 0; z < 3; ++z) for (int y = 0; y < 3; ++y) for (int x = 0; x < 3; ++x) {
            asset.nodes.push_back({{double(x), double(y), double(z)}, {x, y, z}, 1.0, true});
            matter.nodes.push_back({{double(x), double(y), double(z)}, {}, {}, 1.0, {}});
        }
        const auto index = [](int x, int y, int z) { return static_cast<std::uint32_t>(x + 3 * y + 9 * z); };
        for (int z = 0; z < 3; ++z) for (int y = 0; y < 3; ++y) for (int x = 0; x < 3; ++x)
            for (const auto step : {std::array<int, 3>{1, 0, 0}, std::array<int, 3>{0, 1, 0}, std::array<int, 3>{0, 0, 1}}) {
                const int nx = x + step[0], ny = y + step[1], nz = z + step[2];
                if (nx > 2 || ny > 2 || nz > 2) continue;
                asset.bonds.push_back({index(x, y, z), index(nx, ny, nz), 1, material.bond_compliance,
                    material.damage_start_stretch, material.damage_end_stretch,
                    material.compression_damage_start_strain, material.compression_damage_end_strain,
                    material.shear_damage_start_strain, material.shear_damage_end_strain});
                directions.push_back({double(step[0]), double(step[1]), double(step[2])});
            }
        std::vector<std::uint32_t> degree(asset.nodes.size(), 0U);
        for (const auto &bond : asset.bonds) { ++degree[bond.node_a]; ++degree[bond.node_b]; }
        asset.adjacency_offsets.assign(asset.nodes.size() + 1U, 0U);
        for (std::size_t n = 0; n < asset.nodes.size(); ++n) asset.adjacency_offsets[n + 1U] = asset.adjacency_offsets[n] + degree[n];
        asset.adjacent_bond_indices.resize(asset.adjacency_offsets.back());
        auto cursor = asset.adjacency_offsets;
        for (std::uint32_t b = 0; b < asset.bonds.size(); ++b) {
            asset.adjacent_bond_indices[cursor[asset.bonds[b].node_a]++] = b;
            asset.adjacent_bond_indices[cursor[asset.bonds[b].node_b]++] = b;
        }
        matter.asset = &asset;
        matter.material = material;
        matter.bonds.resize(asset.bonds.size());
        for (const auto &node : matter.nodes) matter.reference_positions_world_m.push_back(node.position_world_m);
    }
    void stretchAlongX(double strain, double poisson) {
        for (auto &node : matter.nodes) {
            node.position_world_m.x *= 1 + strain;
            node.position_world_m.y *= 1 - poisson * strain;
            node.position_world_m.z *= 1 - poisson * strain;
        }
    }
};

std::vector<std::uint32_t> deadBonds(const ActiveMatter &matter) {
    std::vector<std::uint32_t> dead;
    for (std::uint32_t i = 0; i < matter.bonds.size(); ++i) if (!matter.bonds[i].alive) dead.push_back(i);
    return dead;
}

void colourOrderNamesTheSameFailingBonds() {
    for (const auto preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        const auto compiled = referenceMaterial(preset, 1.0, 1);
        AxisLattice reference(compiled), fast(compiled);
        reference.stretchAlongX(1.5 * compiled.damage_end_stretch, compiled.poisson_ratio);
        fast.stretchAlongX(1.5 * compiled.damage_end_stretch, compiled.poisson_ratio);
        BrittleBondSolver solver({.substeps = 1, .constraint_iterations = 1, .support_enabled = false});
        (void)solver.step(reference.matter, 1e-9, {});

        const LatticeSchedule schedule = buildLatticeSchedule(fast.asset);
        LatticeState state = buildLatticeState(fast.matter, schedule, {});
        StepSettings<double> settings{};
        settings.dt = 1e-9;
        settings.constraint_iterations = 1;
        settings.direct_arithmetic = 1;
        settings.sphere_enabled = 0;
        auto backend = makeCpuLatticeBackend(schedule, Precision::Double);
        backend->upload(state, settings, SphereState<double>{{}, {}, {}, 1.0, 1.0, 1.0});
        RunControl control{};
        control.max_steps = 1;
        (void)backend->run(control);
        SphereState<double> sphere{};
        backend->download(state, sphere);
        writeBackLatticeState(state, schedule, fast.matter);
        const auto reference_dead = deadBonds(reference.matter), fast_dead = deadBonds(fast.matter);
        require(!reference_dead.empty(), "the reference must break bonds above the break strain");
        require(reference_dead == fast_dead, "colour-order and index-order sweeps name the same failing bonds");
        std::cout << "  " << materialPresetName(preset) << ": broken " << fast_dead.size() << "/" << fast.matter.bonds.size()
                  << " in both lanes, components " << findConnectedComponents(fast.matter).size() << '\n';
    }
}

// BrittleBondSolver on a copy of the lattice whose bonds are stored in this
// lane's schedule order must match this lane to rounding: the same physics in
// the same sweep order. Against the asset's own bond order the difference is
// the Gauss-Seidel ordering effect, reported for the record.
void colourOrderIsBrittleBondSolverInAPermutedOrder() {
    TileImpactRequest request = smallScene(BackendKind::Cpu, Precision::Double, 1);
    const SolverComparison same = compareWithBrittleBondSolver(request, 600, Precision::Double, BackendKind::Cpu, true);
    std::cout << "  600 substeps, schedule-order reference: max |dx| = " << same.max_position_difference_m
              << " m, max |dv| = " << same.max_velocity_difference_m_s << " m/s, alive mismatches "
              << same.alive_mismatches << ", contacts " << same.reference.bond_updates_per_s / 1e6
              << " M bond-updates/s reference, " << same.fast.bond_updates_per_s / 1e6 << " M fast\n";
    require(same.max_position_difference_m < 1e-9, "the lane is BrittleBondSolver's physics in schedule order");
    require(same.max_velocity_difference_m_s < 1e-6, "velocities agree to rounding");
    require(same.alive_mismatches == 0, "same bonds alive after the window");
    const SolverComparison index = compareWithBrittleBondSolver(request, 600, Precision::Double, BackendKind::Cpu, false);
    std::cout << "  600 substeps, index-order reference: max |dx| = " << index.max_position_difference_m
              << " m, max |dv| = " << index.max_velocity_difference_m_s << " m/s, alive mismatches "
              << index.alive_mismatches << " (Gauss-Seidel ordering effect)\n";
    require(index.max_position_difference_m < 1e-4, "ordering effect stays far below the cell size");
}

} // namespace

int main() {
    try {
        boxLatticeFollowsTheSphereBondRules();
        std::cout << "[PASS] box lattice follows the sphere generator's bond rules\n";
        scheduleIsAProperColouring();
        std::cout << "[PASS] schedule is a proper edge colouring over adjacent slabs\n";
        criterionMatchesBondFailure();
        std::cout << "[PASS] one-element criterion equals fracture/BondFailure.cpp\n";
        colourOrderNamesTheSameFailingBonds();
        std::cout << "[PASS] colour-order sweep names the same failing bonds as the index-order solver\n";
        colourOrderIsBrittleBondSolverInAPermutedOrder();
        std::cout << "[PASS] the lane is BrittleBondSolver's physics in a permuted sweep order\n";
        backendsAgree();
        std::cout << "[PASS] CPU and CUDA backends agree\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
