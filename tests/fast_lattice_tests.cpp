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
        asset = std::make_unique<LatticeAsset>(generateBoxTileLattice({dims, cell, horizon}, compiled, &layout));
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
    const auto box = generateBoxTileLattice({{5 * cell, 5 * cell, 5 * cell}, cell, 2}, compiled, &layout);
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
    try { (void)generateBoxTileLattice({{0.05, 0.04, 0.04}, cell, 2}, compiled); } catch (const std::invalid_argument &) { refused = true; }
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

// A rigid motion is not a deformation. This is the invariant the node strain
// measure exists to respect, and it is the one that was broken: with the rest
// covariance inverted on a direction its neighbourhood does not sample, a plate
// one cell thick reported shear for merely flexing, and a plate on its ledges
// broke 436 bonds under gravity alone, never having been struck. Both the CPU
// criterion and the lattice must read zero here, for a solid block and for a
// sheet one cell thick, which is the rank-deficient case.
void rigidMotionProducesNoStrain() {
    struct Case { const char *name; Vec3 dimensions; double cell; };
    const Case cases[] = {
        {"solid block", {0.12, 0.06, 0.08}, 0.02},
        {"sheet one cell thick", {0.12, 0.01, 0.08}, 0.01},
        {"two cells thick", {0.12, 0.02, 0.08}, 0.01},
    };
    for (const auto &scene : cases) {
        for (const auto preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
            Fixture f(preset, scene.dimensions, scene.cell, 2);
            // A rotation of 0.37 rad about a tilted axis, then a translation:
            // large enough that any non-invariant term shows up far above
            // rounding, and applied to the current positions only, so the rest
            // configuration the covariance is built from is untouched.
            const double angle = 0.37;
            const Vec3 axis = normalized(Vec3{0.3, 0.8, 0.5});
            const double c = std::cos(angle), s = std::sin(angle), t = 1.0 - c;
            const double R[9] = {
                t * axis.x * axis.x + c,          t * axis.x * axis.y - s * axis.z, t * axis.x * axis.z + s * axis.y,
                t * axis.x * axis.y + s * axis.z, t * axis.y * axis.y + c,          t * axis.y * axis.z - s * axis.x,
                t * axis.x * axis.z - s * axis.y, t * axis.y * axis.z + s * axis.x, t * axis.z * axis.z + c};
            const Vec3 shift{0.31, -0.17, 0.09};
            for (std::size_t i = 0; i < f.matter.nodes.size(); ++i) {
                const Vec3 x = f.matter.reference_positions_world_m[i];
                f.matter.nodes[i].position_world_m =
                    Vec3{R[0] * x.x + R[1] * x.y + R[2] * x.z + shift.x,
                         R[3] * x.x + R[4] * x.y + R[5] * x.z + shift.y,
                         R[6] * x.x + R[7] * x.y + R[8] * x.z + shift.z};
            }
            for (auto &bond : f.matter.bonds) bond.alive = true;

            resetBondStrainPeaks(f.matter);
            accumulateBondStrainPeaks(f.matter);
            double worst_cpu = 0.0;
            for (const auto &bond : f.matter.bonds) {
                worst_cpu = std::max({worst_cpu, std::abs(bond.peak_tensile_stretch),
                                      std::abs(bond.peak_compressive_strain), std::abs(bond.peak_shear_strain)});
            }
            require(worst_cpu < 1.0e-9,
                    std::string("a rigid motion must not strain the CPU criterion: ") + scene.name);

            const LatticeSchedule schedule = buildLatticeSchedule(*f.asset);
            LatticeState state = buildLatticeState(f.matter, schedule, {});
            WorkingLattice<double> w = WorkingLattice<double>::fromState(state, schedule);
            LatticeArrays<double> L = w.arrays();
            for (std::uint32_t i = 0; i < L.node_count; ++i) nodeStrain(L, i, true);
            double worst_lattice = 0.0;
            for (std::uint32_t j = 0; j < L.bond_count; ++j) {
                if (!L.alive[j]) continue;
                double tensile = 0, compressive = 0, shear = 0;
                bondStrainSample(L, j, true, tensile, compressive, shear);
                worst_lattice = std::max({worst_lattice, std::abs(tensile), std::abs(compressive), std::abs(shear)});
            }
            require(worst_lattice < 1.0e-9,
                    std::string("a rigid motion must not strain the lattice: ") + scene.name);
            std::cout << "  " << scene.name << ", " << std::string(materialPresetName(preset)) << ": worst |strain| cpu "
                      << worst_cpu << " lattice " << worst_lattice << '\n';
        }
    }
}

// A sheet one cell thick spans two directions, not three, and the criterion has
// to state its strain on the plane it does span rather than fall back to the
// bond's own stretch. Before the pseudo-inverse every such node was rejected,
// which showed up as a shear strain of exactly zero however the sheet was
// deformed: the term that produces it was never evaluated. An in-plane shear
// must therefore read as shear, and the rank deficiency must be reported.
void thinSheetKeepsTheNonlocalCriterion() {
    Fixture f(MaterialPreset::Glass, {0.12, 0.01, 0.08}, 0.01, 2);
    for (std::size_t i = 0; i < f.matter.nodes.size(); ++i) {
        const Vec3 x = f.matter.reference_positions_world_m[i];
        // Simple shear in the plane of the sheet: x displaced along z.
        f.matter.nodes[i].position_world_m = Vec3{x.x, x.y, x.z + 0.02 * x.x};
    }
    for (auto &bond : f.matter.bonds) bond.alive = true;
    resetBondStrainPeaks(f.matter);
    accumulateBondStrainPeaks(f.matter);
    double worst_shear = 0.0;
    for (const auto &bond : f.matter.bonds) worst_shear = std::max(worst_shear, bond.peak_shear_strain);
    require(worst_shear > 1.0e-4,
            "an in-plane shear on a one-cell sheet must reach the criterion as shear");

    const LatticeSchedule schedule = buildLatticeSchedule(*f.asset);
    LatticeState state = buildLatticeState(f.matter, schedule, {});
    WorkingLattice<double> w = WorkingLattice<double>::fromState(state, schedule);
    LatticeArrays<double> L = w.arrays();
    std::uint32_t rank_deficient = 0;
    L.rank_deficient_nodes = &rank_deficient;
    for (std::uint32_t i = 0; i < L.node_count; ++i) nodeStrain(L, i, true);
    double lattice_shear = 0.0;
    for (std::uint32_t j = 0; j < L.bond_count; ++j) {
        if (!L.alive[j]) continue;
        double tensile = 0, compressive = 0, shear = 0;
        bondStrainSample(L, j, true, tensile, compressive, shear);
        lattice_shear = std::max(lattice_shear, shear);
    }
    require(lattice_shear > 1.0e-4, "the lattice must read the same in-plane shear");
    require(rank_deficient == L.node_count,
            "every node of a one-cell sheet spans two directions and must be reported as such");
    std::cout << "  one-cell sheet: shear cpu " << worst_shear << " lattice " << lattice_shear << ", "
              << rank_deficient << " of " << L.node_count << " nodes rank-deficient\n";
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
                const StepSettings<Real> settings_r = convertSettings<Real>(settings);
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
                    const FailureOutcome out = bondEndSampleAndFailure(L, settings_r, j, direct);
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

// Through fracture. The removal decisions are discrete, so any rounding
// difference between the backends becomes a different cascade within a few
// hundred substeps; agreement here means the kernel executes the criterion
// and the solve bit for bit (the CUDA target is built without FMA contraction
// for that reason: CMakeLists.txt, BANJO_CUDA_FMAD). Checked in double and in
// float, on one block and on four slabs with several launches.
void backendsAgreeThroughFracture() {
    const std::uint64_t steps = 2500;
    TileImpactRequest cpu_double_request = smallScene(BackendKind::Cpu, Precision::Double, 1);
    cpu_double_request.ball_speed_m_s = 12.0;
    const Advanced cpu_double = advance(cpu_double_request, steps);
    require(cpu_double.status.broken_bonds > 0, "the window must contain fracture");
    std::cout << "  cpu double: broken " << cpu_double.status.broken_bonds << " in "
              << cpu_double.status.failure_rounds << " rounds, first at step "
              << cpu_double.status.first_failure_step << ", removed " << cpu_double.status.removed_energy_j << " J\n";
    if (!cudaLatticeAvailable()) {
        std::cout << "  [SKIP] CUDA backend not available: " << cudaLatticeDescription() << '\n';
        return;
    }
    struct Pair { const char *name; Precision precision; unsigned blocks; };
    for (const Pair pair : {Pair{"double, 1 block", Precision::Double, 1U}, Pair{"double, 4 slabs", Precision::Double, 4U},
                            Pair{"float, 1 block", Precision::Float, 1U}, Pair{"float, 4 slabs", Precision::Float, 4U}}) {
        TileImpactRequest cpu_request = smallScene(BackendKind::Cpu, pair.precision, pair.blocks);
        cpu_request.ball_speed_m_s = 12.0;
        TileImpactRequest gpu_request = cpu_request;
        gpu_request.backend = BackendKind::Cuda;
        const Advanced cpu = advance(cpu_request, steps);
        const Advanced gpu = advance(gpu_request, steps, 250);
        const double du = maxDifference(cpu.state.u, gpu.state.u);
        const double dv = maxDifference(cpu.state.v, gpu.state.v);
        const double ddamage = maxDifference(cpu.state.damage, gpu.state.damage);
        const std::size_t mismatches = aliveMismatches(cpu.state, gpu.state);
        const double energy_error = std::abs(cpu.status.removed_energy_j - gpu.status.removed_energy_j) /
                                    std::max(1e-12, cpu.status.removed_energy_j);
        std::cout << "  " << pair.name << ": broken cpu " << cpu.status.broken_bonds << " / cuda "
                  << gpu.status.broken_bonds << ", rounds " << cpu.status.failure_rounds << " / "
                  << gpu.status.failure_rounds << ", first step " << cpu.status.first_failure_step << " / "
                  << gpu.status.first_failure_step << ", alive mismatches " << mismatches << ", max |du| = " << du
                  << " m, max |dv| = " << dv << " m/s, max |ddamage| = " << ddamage
                  << ", removed energy rel err " << energy_error << ", launches " << gpu.status.launches << '\n';
        require(cpu.status.broken_bonds > 0, "the window must contain fracture in every configuration");
        require(mismatches == 0, "same bonds alive after the fracture window");
        require(cpu.status.broken_bonds == gpu.status.broken_bonds && cpu.status.failure_rounds == gpu.status.failure_rounds &&
                cpu.status.first_failure_step == gpu.status.first_failure_step,
                "same failure history");
        require(du == 0.0 && dv == 0.0 && ddamage == 0.0, "positions, velocities and damage are bit for bit equal");
        // The kernel sums the removed energy with atomics, in whatever order
        // the failing bonds' threads arrive; the addends are identical.
        require(energy_error <= 1e-12, "same removed energy to summation order");
    }
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
// lane's schedule order must match this lane to rounding through a fracture
// cascade: the same physics in the same sweep order, on a hard strike (a
// 12 m/s ball on the 192-cell tile, which breaks 28 bonds at step 219 and
// several hundred by the end of the window). Against the asset's own bond
// order the difference is the Gauss-Seidel ordering effect, reported for the
// record; the first failure step and set must still agree.
void colourOrderIsBrittleBondSolverInAPermutedOrder() {
    TileImpactRequest request = smallScene(BackendKind::Cpu, Precision::Double, 1);
    request.tile_dimensions_m = {0.24, 0.04, 0.16};
    request.ball_radius_m = 0.04;
    request.ball_speed_m_s = 12.0;
    request.ball_gap_m = 0.002;
    const std::uint64_t steps = 4000;
    const SolverComparison same = compareWithBrittleBondSolver(request, steps, Precision::Double, BackendKind::Cpu, true);
    std::cout << "  " << steps << " substeps, schedule-order reference: first failure step " << same.reference.first_failure_step
              << " (" << same.reference.first_failure_bonds.size() << " bonds) / " << same.fast.first_failure_step << " ("
              << same.fast.first_failure_bonds.size() << " bonds), set difference " << same.first_failure_set_symmetric_difference
              << ", broken " << same.reference.broken_bonds << " / " << same.fast.broken_bonds << ", pieces "
              << same.reference.components << " / " << same.fast.components << ", removed " << same.reference.removed_energy_j
              << " / " << same.fast.removed_energy_j << " J, max |dx| = " << same.max_position_difference_m
              << " m, max |dv| = " << same.max_velocity_difference_m_s << " m/s, alive mismatches "
              << same.alive_mismatches << ", " << same.reference.bond_updates_per_s / 1e6
              << " M bond-updates/s reference, " << same.fast.bond_updates_per_s / 1e6 << " M fast\n";
    require(same.reference.first_failure_step >= 0 && same.reference.broken_bonds > 100, "the window must contain a cascade");
    require(same.fast.first_failure_step == same.reference.first_failure_step, "same first failure step");
    require(same.first_failure_set_symmetric_difference == 0, "same first failure set");
    require(same.alive_mismatches == 0, "same bonds alive after the cascade");
    require(same.max_position_difference_m < 1e-8, "the lane is BrittleBondSolver's physics in schedule order");
    require(same.max_velocity_difference_m_s < 1e-5, "velocities agree to rounding");
    require(std::abs(same.reference.removed_energy_j - same.fast.removed_energy_j) <= 1e-9 * same.reference.removed_energy_j,
            "same removed energy");
    const SolverComparison index = compareWithBrittleBondSolver(request, steps, Precision::Double, BackendKind::Cpu, false);
    std::cout << "  " << steps << " substeps, index-order reference: first failure step " << index.reference.first_failure_step
              << " (" << index.reference.first_failure_bonds.size() << " bonds), set difference "
              << index.first_failure_set_symmetric_difference << ", broken " << index.reference.broken_bonds << " / "
              << index.fast.broken_bonds << ", pieces " << index.reference.components << " / " << index.fast.components
              << ", largest " << index.reference.largest_piece_cells << " / " << index.fast.largest_piece_cells
              << ", removed " << index.reference.removed_energy_j << " / " << index.fast.removed_energy_j
              << " J, max |dx| = " << index.max_position_difference_m << " m, alive mismatches "
              << index.alive_mismatches << " (Gauss-Seidel ordering effect)\n";
    require(index.fast.first_failure_step == index.reference.first_failure_step &&
            index.first_failure_set_symmetric_difference == 0,
            "the first failure does not depend on the sweep order");
}

// -------------------------------------------------------------------------
// 6. Node-to-node contact.
// -------------------------------------------------------------------------

// Two cells on the x axis, `separation` apart, optionally joined by a bond.
// Nothing else exists: no ground, no gravity, no striker and no damping, so a
// node contact is the only thing that can change either cell's motion.
struct TwoCells {
    CompiledBrittleMaterial compiled{};
    std::unique_ptr<LatticeAsset> asset;
    ActiveMatter matter;
    LatticeSchedule schedule;
    StepSettings<double> settings{};
    LatticeState state;
    double cell{}, radius{};
};

std::unique_ptr<TwoCells> twoCells(double cell, double separation, bool bonded, std::uint8_t mode,
                                   double mass_ratio = 1.0) {
    auto p = std::make_unique<TwoCells>();
    p->cell = cell;
    p->radius = 0.5 * cell;
    p->compiled = referenceMaterial(MaterialPreset::Glass, cell, 2);
    p->asset = std::make_unique<LatticeAsset>();
    LatticeAsset &a = *p->asset;
    for (int i = 0; i < 2; ++i) {
        LatticeNodeRest node{};
        node.local_position_m = {(i == 0 ? -0.5 : 0.5) * separation, 0.0, 0.0};
        node.grid = {i, 0, 0};
        node.represented_volume_m3 = cell * cell * cell;
        node.surface_node = true;
        a.nodes.push_back(node);
    }
    a.adjacency_offsets.assign(3, 0U);
    if (bonded) {
        BondRest bond{};
        bond.node_a = 0;
        bond.node_b = 1;
        bond.rest_length_m = separation; // at rest: the bond pulls nothing
        bond.compliance = p->compiled.bond_compliance;
        // Thresholds far out of reach: this test is about contact, and a bond
        // that failed would change which rule applies to the pair.
        bond.damage_start_stretch = 1.0;
        bond.damage_end_stretch = 2.0;
        bond.compression_damage_start_strain = 1.0;
        bond.compression_damage_end_strain = 2.0;
        bond.shear_damage_start_strain = 1.0;
        bond.shear_damage_end_strain = 2.0;
        a.bonds.push_back(bond);
        a.adjacency_offsets = {0U, 1U, 2U};
        a.adjacent_bond_indices = {0U, 0U};
    }
    p->matter.asset = p->asset.get();
    p->matter.material = p->compiled;
    for (std::size_t i = 0; i < a.nodes.size(); ++i) {
        const Vec3 position = a.nodes[i].local_position_m;
        const double mass = a.nodes[i].represented_volume_m3 * p->compiled.density_kg_m3 *
                            (i == 1 ? mass_ratio : 1.0);
        p->matter.nodes.push_back({position, position, {}, mass, {}});
        p->matter.reference_positions_world_m.push_back(position);
    }
    p->matter.bonds.resize(a.bonds.size());
    p->schedule = buildLatticeSchedule(a);

    StepSettings<double> &S = p->settings;
    S.dt = 1.0e-6;
    S.gravity = {0.0, 0.0, 0.0};
    S.constraint_iterations = 1;
    S.damping_fraction = 0.0;
    S.sphere_enabled = 0;
    S.direct_arithmetic = 1;
    S.support.plane_count = 0;
    S.node_contact.mode = mode;
    S.node_contact.radius = 0.5 * cell;
    S.node_contact.skin = 0.25 * cell;
    S.node_contact.margin = 1.0e-5;
    S.node_contact.restitution = 0.0;
    S.node_contact.restitution_speed_threshold = 0.5;
    S.node_contact.static_friction = 0.5;
    S.node_contact.dynamic_friction = 0.4;
    S.node_contact.bucket_mask = latticeContactBucketMask(2U);

    p->state = buildLatticeState(p->matter, p->schedule, Vec3{});
    return p;
}

struct PairRun {
    double minimum_separation_m{};
    double final_separation_m{};
    double momentum_before{}, momentum_after{};
    RunStatus status;
    LatticeState state;
};

// Steps the pair, sampling the separation every substep so a pass-through
// cannot hide between samples.
PairRun runPair(TwoCells &p, double v0, double v1, std::uint64_t steps, unsigned threads) {
    LatticeState state = p.state;
    state.v[0] = v0;
    state.v[3] = v1;
    const double m0 = state.mass[0], m1 = state.mass[1];
    PairRun out;
    out.momentum_before = m0 * v0 + m1 * v1;
    auto backend = threads == 0 ? makeCpuLatticeBackend(p.schedule, Precision::Double)
                                : makeParallelCpuLatticeBackend(p.schedule, Precision::Double, threads);
    SphereState<double> sphere{};
    sphere.radius = 1.0;
    sphere.mass = 1.0;
    sphere.inertia = 1.0;
    backend->upload(state, p.settings, sphere);
    out.minimum_separation_m = std::numeric_limits<double>::infinity();
    RunControl control{};
    control.max_steps = 1;
    for (std::uint64_t s = 0; s < steps; ++s) {
        out.status = backend->run(control);
        LatticeState probe = state;
        SphereState<double> probe_sphere = sphere;
        backend->download(probe, probe_sphere);
        const double separation = (probe.x0[3] + probe.u[3]) - (probe.x0[0] + probe.u[0]);
        out.minimum_separation_m = std::min(out.minimum_separation_m, separation);
        out.final_separation_m = separation;
        out.state = probe;
    }
    out.momentum_after = m0 * out.state.v[0] + m1 * out.state.v[3];
    return out;
}

void unbondedCellsDoNotPassThroughEachOther() {
    const double cell = 0.01, touch = cell; // two cells touch one cell apart
    const double speed = 2.0;
    // Two cells apart, closing at 4 m/s: 2.5 ms to touch, 6 ms of run.
    const std::uint64_t steps = 6000;
    auto without = twoCells(cell, 2.0 * cell, false, kNodeContactOff);
    const PairRun off = runPair(*without, speed, -speed, steps, 0);
    auto with = twoCells(cell, 2.0 * cell, false, kNodeContactOn);
    const PairRun on = runPair(*with, speed, -speed, steps, 0);
    std::cout << "  unbonded pair closing at " << 2.0 * speed << " m/s: contact off -> minimum separation "
              << off.minimum_separation_m << " m (touching is " << touch << "), contact on -> "
              << on.minimum_separation_m << " m, " << on.status.node_contact.contacts << " contacts\n";
    require(off.minimum_separation_m < 0.0,
            "without contact the two cells must pass clean through each other; the test proves nothing otherwise");
    require(on.status.node_contact.contacts > 0, "contact never engaged on an unbonded closing pair");
    // The margin is what the response is allowed to leave; anything deeper is
    // an overlap the contact failed to stop.
    require(on.minimum_separation_m > touch - 2.0 * with->settings.node_contact.margin,
            "the unbonded pair overlapped by more than the contact margin");
    require(on.final_separation_m >= on.minimum_separation_m,
            "the pair did not come apart again after the contact");
}

void bondedCellsAreUntouchedByContact() {
    // Deeply overlapping and held there by their own bond's rest length: if
    // contact acted on a bonded pair this configuration would be blown apart.
    const double cell = 0.01, separation = 0.6 * cell;
    auto bonded_off = twoCells(cell, separation, true, kNodeContactOff);
    auto bonded_on = twoCells(cell, separation, true, kNodeContactOn);
    const PairRun off = runPair(*bonded_off, 0.0, 0.0, 2000, 0);
    const PairRun on = runPair(*bonded_on, 0.0, 0.0, 2000, 0);
    std::cout << "  bonded pair overlapping by " << (cell - separation) * 1e3 << " mm: "
              << on.status.node_contact.pairs_listed << " pairs listed, "
              << on.status.node_contact.contacts << " contacts, separation " << on.final_separation_m
              << " m (contact off: " << off.final_separation_m << " m)\n";
    require(on.status.node_contact.rebuilds > 0, "the broad phase never ran, so it proves nothing");
    require(on.status.node_contact.pairs_listed == 0, "a live bond's pair was put in the contact list");
    require(on.status.node_contact.contacts == 0, "contact acted on a pair a live bond already holds");
    for (std::size_t i = 0; i < off.state.u.size(); ++i)
        require(on.state.u[i] == off.state.u[i], "contact moved a bonded pair");
    for (std::size_t i = 0; i < off.state.v.size(); ++i)
        require(on.state.v[i] == off.state.v[i], "contact changed a bonded pair's velocity");
    // ... and the same pair with its bond dead is exactly the case contact is
    // for, so it must separate. That is what makes the assertion above a rule
    // and not an accident of the geometry.
    auto broken = twoCells(cell, separation, true, kNodeContactOn);
    broken->state.alive[0] = 0;
    broken->state.nbr_alive[broken->state.bond_slot_a[0]] = 0;
    broken->state.nbr_alive[broken->state.bond_slot_b[0]] = 0;
    const PairRun dead = runPair(*broken, 0.0, 0.0, 2000, 0);
    std::cout << "  the same pair with the bond dead: " << dead.status.node_contact.pairs_listed
              << " pairs listed, worst correction " << dead.status.node_contact.maximum_position_correction_m
              << " m, separation " << dead.final_separation_m << " m\n";
    require(dead.status.node_contact.pairs_listed > 0, "a failed bond's pair was not put in the contact list");
    // At rest and already overlapping there is no approach to stop, so the
    // response is the overlap correction alone and no impulse is applied. The
    // pair must end up touching, not overlapping.
    require(dead.status.node_contact.maximum_position_correction_m > 0.0,
            "contact did not correct the overlap of a pair whose bond had failed");
    require(dead.final_separation_m > cell - 2.0 * broken->settings.node_contact.margin,
            "the failed pair was not pushed apart to touching");
}

void contactConservesMomentum() {
    // Unequal masses and an unbalanced closing pair, so a response that was not
    // equal and opposite would show up in the total.
    const double cell = 0.01;
    auto p = twoCells(cell, 2.0 * cell, false, kNodeContactOn, 3.0);
    const PairRun run = runPair(*p, 4.0, -1.0, 8000, 0);
    const double scale = std::max(std::abs(run.momentum_before), 1e-30);
    const double drift = std::abs(run.momentum_after - run.momentum_before) / scale;
    double residual = 0.0;
    for (const double component : {run.status.node_contact.momentum_residual_x,
                                   run.status.node_contact.momentum_residual_y,
                                   run.status.node_contact.momentum_residual_z})
        residual = std::max(residual, std::abs(component));
    // Control: the same pair, same velocities, contact off, so it never
    // interacts. Its drift is the XPBD velocity reconstruction alone --
    // v = (u - u_prev) / dt every substep -- which is what the total below
    // carries as well; the contact's own contribution is the residual.
    auto control = twoCells(cell, 2.0 * cell, false, kNodeContactOff, 3.0);
    const PairRun free_flight = runPair(*control, 4.0, -1.0, 8000, 0);
    const double control_drift =
        std::abs(free_flight.momentum_after - free_flight.momentum_before) / scale;
    std::cout << "  momentum " << run.momentum_before << " -> " << run.momentum_after << " kg m/s (relative drift "
              << drift << ", free flight without contact " << control_drift << ") over "
              << run.status.node_contact.contacts << " contacts, reported residual " << residual
              << " N s, dissipated " << run.status.node_contact.dissipated_kinetic_energy_j << " J\n";
    require(run.status.node_contact.contacts > 0, "no contact happened, so nothing was conserved");
    require(residual < 1e-14 * scale,
            "node contact created momentum: the response is not equal and opposite");
    require(drift < 1e-10, "the pair's momentum moved by more than the velocity reconstruction's rounding");
    require(run.status.node_contact.dissipated_kinetic_energy_j > 0.0,
            "a zero-restitution contact removed no kinetic energy");
}

void parallelBackendMatchesSerialWithContact() {
    // A pair first: the narrow phase is the same one thread's work in both
    // backends, and this asserts it.
    for (const unsigned threads : {2U, 4U, 8U}) {
        auto serial_pair = twoCells(0.01, 0.02, false, kNodeContactOn, 3.0);
        auto parallel_pair = twoCells(0.01, 0.02, false, kNodeContactOn, 3.0);
        const PairRun serial = runPair(*serial_pair, 4.0, -1.0, 4000, 0);
        const PairRun parallel = runPair(*parallel_pair, 4.0, -1.0, 4000, threads);
        for (std::size_t i = 0; i < serial.state.u.size(); ++i)
            require(parallel.state.u[i] == serial.state.u[i] && parallel.state.v[i] == serial.state.v[i],
                    "the parallel backend moved a contacting pair differently");
        require(parallel.status.node_contact.contacts == serial.status.node_contact.contacts &&
                    parallel.status.node_contact.dissipated_kinetic_energy_j ==
                        serial.status.node_contact.dissipated_kinetic_energy_j,
                "the parallel backend reported a different contact ledger");
    }
    // Then a fracture cascade, where the pair list changes every failure round
    // and the narrow phase runs over hundreds of pairs.
    TileImpactRequest request = smallScene(BackendKind::Cpu, Precision::Double, 1);
    request.ball_speed_m_s = 20.0;
    auto setup = buildTileImpactSetup(request);
    RunControl control{};
    control.max_steps = 4000;
    const auto run = [&](unsigned threads) {
        LatticeState state = buildLatticeState(setup->matter, setup->schedule, setup->origin);
        SphereState<double> sphere = setup->sphere_world;
        sphere.center = sphere.center - V3<double>{setup->origin.x, setup->origin.y, setup->origin.z};
        auto backend = threads == 0
            ? makeCpuLatticeBackend(setup->schedule, Precision::Double)
            : makeParallelCpuLatticeBackend(setup->schedule, Precision::Double, threads);
        backend->upload(state, setup->settings_scene, sphere);
        const RunStatus status = backend->run(control);
        backend->download(state, sphere);
        return std::pair<LatticeState, RunStatus>{std::move(state), status};
    };
    const auto [serial_state, serial_status] = run(0);
    require(serial_status.broken_bonds > 0 && serial_status.node_contact.contacts > 0,
            "the cascade scene neither fractured nor contacted; it proves nothing");
    std::cout << "  cascade with contact: " << serial_status.broken_bonds << " bonds broken, "
              << serial_status.node_contact.contacts << " contacts, "
              << serial_status.node_contact.rebuilds << " rebuilds, worst overlap "
              << serial_status.node_contact.maximum_overlap_m << " m\n";
    for (const unsigned threads : {2U, 4U, 8U}) {
        const auto [parallel_state, parallel_status] = run(threads);
        for (std::size_t i = 0; i < serial_state.u.size(); ++i)
            require(parallel_state.u[i] == serial_state.u[i] && parallel_state.v[i] == serial_state.v[i],
                    "the parallel backend diverged from the serial one with contact on, at " +
                        std::to_string(threads) + " threads");
        require(aliveMismatches(parallel_state, serial_state) == 0,
                "the parallel backend broke a different bond set with contact on");
        require(parallel_status.node_contact.contacts == serial_status.node_contact.contacts &&
                    parallel_status.node_contact.rebuilds == serial_status.node_contact.rebuilds &&
                    parallel_status.node_contact.dissipated_kinetic_energy_j ==
                        serial_status.node_contact.dissipated_kinetic_energy_j &&
                    parallel_status.node_contact.maximum_overlap_m ==
                        serial_status.node_contact.maximum_overlap_m,
                "the parallel backend reported a different contact ledger at " + std::to_string(threads) +
                    " threads");
    }
}

// Off is the lane as it was, and measuring is not acting: the broad phase and
// the overlap record must leave every number the run reports untouched.
void measuringTheOverlapChangesNothing() {
    TileImpactRequest request = smallScene(BackendKind::Cpu, Precision::Double, 1);
    request.ball_speed_m_s = 20.0;
    const auto run = [&](NodeContactMode mode) {
        TileImpactRequest local = request;
        local.node_contact = mode;
        auto setup = buildTileImpactSetup(local);
        LatticeState state = buildLatticeState(setup->matter, setup->schedule, setup->origin);
        SphereState<double> sphere = setup->sphere_world;
        sphere.center = sphere.center - V3<double>{setup->origin.x, setup->origin.y, setup->origin.z};
        auto backend = makeCpuLatticeBackend(setup->schedule, Precision::Double);
        backend->upload(state, setup->settings_scene, sphere);
        RunControl control{};
        control.max_steps = 4000;
        const RunStatus status = backend->run(control);
        backend->download(state, sphere);
        return std::pair<LatticeState, RunStatus>{std::move(state), status};
    };
    const auto [off_state, off_status] = run(NodeContactMode::Off);
    const auto [measure_state, measure_status] = run(NodeContactMode::Measure);
    std::cout << "  measure mode: worst overlap " << measure_status.node_contact.maximum_overlap_m
              << " m over " << measure_status.node_contact.pair_tests << " pair tests, "
              << off_status.broken_bonds << " bonds broken either way\n";
    require(measure_status.node_contact.pair_tests > 0, "the measure mode tested no pair");
    require(measure_status.node_contact.maximum_overlap_m > 0.0,
            "the measure mode found no overlap, so it is not measuring the case it exists for");
    require(measure_status.node_contact.contacts == 0, "the measure mode applied a response");
    for (std::size_t i = 0; i < off_state.u.size(); ++i)
        require(measure_state.u[i] == off_state.u[i] && measure_state.v[i] == off_state.v[i],
                "measuring the overlap moved a node");
    require(aliveMismatches(measure_state, off_state) == 0, "measuring the overlap changed the broken set");
    require(measure_status.broken_bonds == off_status.broken_bonds &&
                measure_status.removed_energy_j == off_status.removed_energy_j &&
                measure_status.first_failure_step == off_status.first_failure_step,
            "measuring the overlap changed the fracture answer");
}

// The CUDA kernel runs the same broad and narrow phases: the per-node steps are
// spread over its threads, the hash build, the staleness scan and the whole
// narrow phase run on its leader thread. A scene that contacts hard is the only
// way to assert that, since the windows the other CUDA suites use never list a
// pair (their broken bonds are all longer than the contact reach).
void cudaAgreesWithContact() {
    const std::uint64_t steps = 4000;
    TileImpactRequest cpu_request = smallScene(BackendKind::Cpu, Precision::Double, 1);
    cpu_request.ball_speed_m_s = 20.0;
    const Advanced reference = advance(cpu_request, steps);
    require(reference.status.node_contact.contacts > 0, "the CUDA contact window never contacts");
    std::cout << "  cpu double: " << reference.status.broken_bonds << " bonds broken, "
              << reference.status.node_contact.contacts << " contacts, "
              << reference.status.node_contact.rebuilds << " rebuilds, worst overlap "
              << reference.status.node_contact.maximum_overlap_m << " m\n";
    if (!cudaLatticeAvailable()) {
        std::cout << "  [SKIP] CUDA backend not available: " << cudaLatticeDescription() << '\n';
        return;
    }
    struct Case { const char *name; Precision precision; unsigned blocks; };
    for (const Case c : {Case{"double, 1 block", Precision::Double, 1U},
                         Case{"double, 4 slabs", Precision::Double, 4U},
                         Case{"float, 1 block", Precision::Float, 1U},
                         Case{"float, 4 slabs", Precision::Float, 4U}}) {
        TileImpactRequest cpu = smallScene(BackendKind::Cpu, c.precision, c.blocks);
        cpu.ball_speed_m_s = 20.0;
        TileImpactRequest gpu = cpu;
        gpu.backend = BackendKind::Cuda;
        const Advanced host = advance(cpu, steps);
        const Advanced device = advance(gpu, steps, 250);
        const double du = maxDifference(host.state.u, device.state.u);
        const double dv = maxDifference(host.state.v, device.state.v);
        std::cout << "  " << c.name << ": contacts cpu " << host.status.node_contact.contacts << " / cuda "
                  << device.status.node_contact.contacts << ", rebuilds "
                  << host.status.node_contact.rebuilds << " / " << device.status.node_contact.rebuilds
                  << ", broken " << host.status.broken_bonds << " / " << device.status.broken_bonds
                  << ", max |du| = " << du << " m, max |dv| = " << dv << " m/s\n";
        require(host.status.node_contact.contacts > 0, "no contact in this configuration");
        require(du == 0.0 && dv == 0.0, "the CUDA node contact moved a node differently");
        require(aliveMismatches(host.state, device.state) == 0,
                "the CUDA node contact changed the broken set");
        require(host.status.node_contact.contacts == device.status.node_contact.contacts &&
                    host.status.node_contact.rebuilds == device.status.node_contact.rebuilds &&
                    host.status.node_contact.pairs_listed == device.status.node_contact.pairs_listed &&
                    host.status.node_contact.maximum_overlap_m ==
                        device.status.node_contact.maximum_overlap_m &&
                    host.status.node_contact.dissipated_kinetic_energy_j ==
                        device.status.node_contact.dissipated_kinetic_energy_j,
                "the CUDA node contact reported a different ledger");
    }
}

// Where the broad phase lists no pair the answer must be the one the lane gave
// before the contact existed, bit for bit. The horizon is 2 cells and the
// contact list reaches 1.25, so every pair inside the list radius of an intact
// lattice is bonded: contact cannot act until a SHORT bond fails, and this
// window breaks only long ones.
void fractureWithoutContactIsUnchanged() {
    TileImpactRequest request = smallScene(BackendKind::Cpu, Precision::Double, 1);
    request.ball_speed_m_s = 12.0;
    const auto run = [&](NodeContactMode mode) {
        TileImpactRequest local = request;
        local.node_contact = mode;
        auto setup = buildTileImpactSetup(local);
        LatticeState state = buildLatticeState(setup->matter, setup->schedule, setup->origin);
        SphereState<double> sphere = setup->sphere_world;
        sphere.center = sphere.center - V3<double>{setup->origin.x, setup->origin.y, setup->origin.z};
        auto backend = makeCpuLatticeBackend(setup->schedule, Precision::Double);
        backend->upload(state, setup->settings_scene, sphere);
        RunControl control{};
        control.max_steps = 4000;
        const RunStatus status = backend->run(control);
        backend->download(state, sphere);
        return std::pair<LatticeState, RunStatus>{std::move(state), status};
    };
    const auto [off_state, off_status] = run(NodeContactMode::Off);
    const auto [on_state, on_status] = run(NodeContactMode::On);
    std::cout << "  fracture window with no near unbonded pair: " << off_status.broken_bonds
              << " bonds broken, " << on_status.node_contact.rebuilds << " broad-phase rebuilds, "
              << on_status.node_contact.pairs_listed << " pairs listed, "
              << on_status.node_contact.contacts << " contacts\n";
    require(off_status.broken_bonds > 0, "the window contains no fracture, so it proves nothing");
    require(on_status.node_contact.rebuilds > 0, "the broad phase never ran");
    require(on_status.node_contact.pairs_listed == 0 && on_status.node_contact.contacts == 0,
            "this window was supposed to have no unbonded pair within the contact reach");
    for (std::size_t i = 0; i < off_state.u.size(); ++i)
        require(on_state.u[i] == off_state.u[i] && on_state.v[i] == off_state.v[i],
                "contact moved a node in a window where it never acted");
    require(aliveMismatches(on_state, off_state) == 0, "contact changed the broken set where it never acted");
    require(on_status.broken_bonds == off_status.broken_bonds &&
                on_status.removed_energy_j == off_status.removed_energy_j &&
                on_status.first_failure_step == off_status.first_failure_step &&
                on_status.failure_rounds == off_status.failure_rounds,
            "contact changed the fracture answer in a window where it never acted");
}


// 6. The energy plateau exit (reason 4) stops the window once the removed energy
//    has stopped growing, and is off unless asked for.
//
//    It exists because the three things this phase produces settle at very
//    different times. On a 250 x 200 x 20 mm glass plate the removed energy is
//    within 0.8% of its final value by 106 wave transits while the piece count is
//    still 38% short, and the piece count does not converge in cell size, time
//    step, sweep order or precision anyway, so it was never a quantity to wait on.
void energyPlateauStopsTheWindow() {
    // The rule itself, before any scene: reason 4 needs a failure, a window, and
    // a gap since the last energy gain, and never outranks the quiet rule.
    const auto reason = [](unsigned broken, unsigned long long completed,
                           unsigned long long last_fail, unsigned long long quiet,
                           unsigned long long flat, unsigned long long last_gain) {
        return latticeExitReason(completed, broken, last_fail, quiet, /*min_steps=*/10,
                                 /*no_failure_steps=*/0, flat, last_gain);
    };
    const auto never = std::numeric_limits<unsigned long long>::max();
    require(reason(0, 500, 0, 0, 100, 100) == 0U,
            "the plateau fired on a scene that has broken nothing");
    require(reason(3, 500, 400, 0, 0, 100) == 0U,
            "a zero window is supposed to disable the rule");
    require(reason(3, 5, 0, 0, 100, never) == 0U,
            "the plateau fired before min_steps");
    require(reason(3, 500, 400, 0, 100, 380) == 4U,
            "the plateau did not fire after a long flat run");
    require(reason(3, 500, 400, 0, 100, 450) == 0U,
            "the plateau fired while energy was still growing");
    require(reason(3, 500, 300, 100, 100, 380) == 1U,
            "the quiet rule is supposed to win when both are satisfied");

    // And on a real cascade: the same scene run to a fixed long window, then with
    // the plateau deciding. The plateau must stop sooner and must not lose a
    // material amount of the energy the long run removed.
    TileImpactRequest request = smallScene(BackendKind::Cpu, Precision::Double, 1);
    request.ball_speed_m_s = 12.0;
    const auto advance = [&](std::uint64_t flat_steps) {
        auto setup = buildTileImpactSetup(request);
        LatticeState state = buildLatticeState(setup->matter, setup->schedule, setup->origin);
        SphereState<double> sphere = setup->sphere_world;
        sphere.center = sphere.center - V3<double>{setup->origin.x, setup->origin.y, setup->origin.z};
        auto backend = makeCpuLatticeBackend(setup->schedule, Precision::Double);
        backend->upload(state, setup->settings_scene, sphere);
        RunControl control{};
        control.max_steps = 20000;
        control.min_steps = 200;
        control.energy_flat_steps = flat_steps;
        return backend->run(control);
    };
    const RunStatus full = advance(0);
    const RunStatus capped = advance(1500);
    std::cout << "  full window: " << full.total_steps << " steps, " << full.broken_bonds
              << " bonds, " << full.removed_energy_j << " J (exit " << full.exit_reason
              << ")\n  energy plateau: " << capped.total_steps << " steps, "
              << capped.broken_bonds << " bonds, " << capped.removed_energy_j
              << " J (exit " << capped.exit_reason << ")\n";
    require(full.broken_bonds > 0, "the window contains no fracture, so it proves nothing");
    require(full.exit_reason != 4U, "the rule was off and fired anyway");
    require(capped.exit_reason == 4U, "the plateau rule did not stop this run");
    require(capped.total_steps < full.total_steps, "the plateau did not stop sooner");
    const double lost = (full.removed_energy_j - capped.removed_energy_j) /
                        std::max(full.removed_energy_j, 1.0e-12);
    require(lost < 0.02,
            "the plateau lost more than 2% of the removed energy: " + std::to_string(lost));
}

} // namespace

int main() {
    try {
        boxLatticeFollowsTheSphereBondRules();
        std::cout << "[PASS] box lattice follows the sphere generator's bond rules\n";
        scheduleIsAProperColouring();
        std::cout << "[PASS] schedule is a proper edge colouring over adjacent slabs\n";
        rigidMotionProducesNoStrain();
        std::cout << "[PASS] a rigid motion strains nothing, at every thickness\n";
        thinSheetKeepsTheNonlocalCriterion();
        std::cout << "[PASS] a one-cell sheet keeps the nonlocal criterion\n";
        criterionMatchesBondFailure();
        std::cout << "[PASS] one-element criterion equals fracture/BondFailure.cpp\n";
        colourOrderNamesTheSameFailingBonds();
        std::cout << "[PASS] colour-order sweep names the same failing bonds as the index-order solver\n";
        colourOrderIsBrittleBondSolverInAPermutedOrder();
        std::cout << "[PASS] the lane is BrittleBondSolver's physics in a permuted sweep order\n";
        backendsAgree();
        std::cout << "[PASS] CPU and CUDA backends agree\n";
        backendsAgreeThroughFracture();
        std::cout << "[PASS] CPU and CUDA backends agree bit for bit through a fracture cascade\n";
        unbondedCellsDoNotPassThroughEachOther();
        std::cout << "[PASS] two unbonded cells cannot pass through each other\n";
        bondedCellsAreUntouchedByContact();
        std::cout << "[PASS] a live bond's pair is left to the bond, and a failed one is not\n";
        contactConservesMomentum();
        std::cout << "[PASS] node contact conserves momentum and removes kinetic energy\n";
        parallelBackendMatchesSerialWithContact();
        std::cout << "[PASS] the parallel backend is bit identical with node contact on\n";
        measuringTheOverlapChangesNothing();
        std::cout << "[PASS] measuring the overlap changes nothing the run reports\n";
        energyPlateauStopsTheWindow();
        std::cout << "[PASS] the energy plateau stops the window and is off unless asked for\n";
        fractureWithoutContactIsUnchanged();
        std::cout << "[PASS] the fracture answer is unchanged where contact does not act\n";
        cudaAgreesWithContact();
        std::cout << "[PASS] CPU and CUDA agree bit for bit with node contact on\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
