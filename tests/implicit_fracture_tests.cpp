// Fracture in the implicit (Newton/GMRES) conservative reference.
//
// Three things are pinned here. First, that both lanes use one criterion: the
// explicit XPBD solver and the implicit solver, handed the same state, must
// name the same failing bonds. Second, that adding fracture does not weaken the
// implicit lane's transactional contract: a rejected frame leaves node state,
// bond damage and bond aliveness exactly as they were. Third, that the stored
// energy carried away by a removed bond is reported rather than absorbed, so
// the mechanical ledger still closes.

#include "fracture/BondFailure.hpp"
#include "fracture/BrittleBondSolver.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/FractureStep.hpp"
#include "physics/MechanicalAccounting.hpp"

#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;

void require(bool result, const char *message) {
    if (!result) throw std::runtime_error(message);
}
void near(double actual, double expected, double tolerance, const char *message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message) + ": " + std::to_string(actual) +
                                 " vs " + std::to_string(expected));
}

// A 3x3x3 cubic lattice of unit-spaced nodes with axis-aligned nearest-neighbour
// bonds only, so every bond direction is exactly x, y or z. Same construction as
// the explicit lane's orientation tests, so the two suites load the criterion the
// same way.
struct AxisLattice {
    LatticeAsset asset;
    ActiveMatter matter;
    std::vector<Vec3> directions;

    AxisLattice(const CompiledBrittleMaterial &material, double mass = 1.0) {
        asset.recipe.voxel_size_m = 1;
        for (int z = 0; z < 3; ++z)
            for (int y = 0; y < 3; ++y)
                for (int x = 0; x < 3; ++x) {
                    asset.nodes.push_back({});
                    matter.nodes.push_back({{static_cast<double>(x), static_cast<double>(y),
                                             static_cast<double>(z)}, {}, {}, mass, {}});
                }
        const auto index = [](int x, int y, int z) {
            return static_cast<std::uint32_t>(x + 3 * y + 9 * z);
        };
        for (int z = 0; z < 3; ++z)
            for (int y = 0; y < 3; ++y)
                for (int x = 0; x < 3; ++x)
                    for (const auto step : {std::array<int, 3>{1, 0, 0},
                                            std::array<int, 3>{0, 1, 0},
                                            std::array<int, 3>{0, 0, 1}}) {
                        const int nx = x + step[0], ny = y + step[1], nz = z + step[2];
                        if (nx > 2 || ny > 2 || nz > 2) continue;
                        asset.bonds.push_back({index(x, y, z), index(nx, ny, nz), 1,
                            material.bond_compliance,
                            material.damage_start_stretch, material.damage_end_stretch,
                            material.compression_damage_start_strain, material.compression_damage_end_strain,
                            material.shear_damage_start_strain, material.shear_damage_end_strain});
                        directions.push_back({static_cast<double>(step[0]),
                                              static_cast<double>(step[1]),
                                              static_cast<double>(step[2])});
                    }
        std::vector<std::uint32_t> degree(asset.nodes.size(), 0U);
        for (const auto &bond : asset.bonds) { ++degree[bond.node_a]; ++degree[bond.node_b]; }
        asset.adjacency_offsets.assign(asset.nodes.size() + 1U, 0U);
        for (std::size_t n = 0; n < asset.nodes.size(); ++n)
            asset.adjacency_offsets[n + 1U] = asset.adjacency_offsets[n] + degree[n];
        asset.adjacent_bond_indices.resize(asset.adjacency_offsets.back());
        auto cursor = asset.adjacency_offsets;
        for (std::uint32_t b = 0; b < asset.bonds.size(); ++b) {
            asset.adjacent_bond_indices[cursor[asset.bonds[b].node_a]++] = b;
            asset.adjacent_bond_indices[cursor[asset.bonds[b].node_b]++] = b;
        }
        matter.asset = &asset;
        matter.material = material;
        matter.bonds.resize(asset.bonds.size());
        for (const auto &node : matter.nodes)
            matter.reference_positions_world_m.push_back(node.position_world_m);
    }

    void stretchAlongX(double strain, double poisson) {
        for (auto &node : matter.nodes) {
            node.position_world_m.x *= 1 + strain;
            node.position_world_m.y *= 1 - poisson * strain;
            node.position_world_m.z *= 1 - poisson * strain;
        }
    }
};

CompiledBrittleMaterial fracturingReference(MaterialPreset preset) {
    const auto material = makeReferenceMaterial(preset, 17);
    return withStrengthDerivedFailure(compileElasticLatticeReference(material, 1, 1), material);
}

std::vector<std::uint32_t> deadBonds(const ActiveMatter &matter) {
    std::vector<std::uint32_t> dead;
    for (std::uint32_t i = 0; i < matter.bonds.size(); ++i)
        if (!matter.bonds[i].alive) dead.push_back(i);
    return dead;
}

// The two lanes must agree about when glass, oak and iron break. Both are handed
// the same strained configuration and asked to resolve one very short interval,
// short enough that neither solver relaxes the imposed geometry first.
void bothLanesNameTheSameFailingBonds() {
    for (const auto preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        const auto compiled = fracturingReference(preset);
        // Well past the break threshold so the outcome is not a knife edge.
        const double strain = 1.5 * compiled.damage_end_stretch;
        AxisLattice explicit_lane(compiled), implicit_lane(compiled);
        explicit_lane.stretchAlongX(strain, compiled.poisson_ratio);
        implicit_lane.stretchAlongX(strain, compiled.poisson_ratio);

        BrittleBondSolver solver({.substeps = 1, .constraint_iterations = 1, .support_enabled = false});
        (void)solver.step(explicit_lane.matter, 1e-9, {});
        const auto implicit_result = tryFracturingStep(implicit_lane.matter, 1e-9);
        require(implicit_result.converged, "implicit fracture step converges on the strained lattice");

        const auto explicit_dead = deadBonds(explicit_lane.matter);
        const auto implicit_dead = deadBonds(implicit_lane.matter);
        require(!explicit_dead.empty(), "the explicit lane must break bonds above the break strain");
        require(explicit_dead == implicit_dead,
                "the two lanes must name the same failing bonds from one criterion");
        for (const std::uint32_t bond : implicit_dead)
            require(implicit_lane.directions[bond].x > .5,
                    "only bonds along the loaded axis may fail");
        std::cout << "  " << materialPresetName(preset) << " break_strain=" << compiled.damage_end_stretch
                  << " broken=" << implicit_dead.size() << '/' << implicit_lane.matter.bonds.size()
                  << " components=" << findConnectedComponents(implicit_lane.matter).size() << '\n';
    }
}

// Below the damage threshold no material may lose a bond, and the recorded
// damage must stay at zero rather than creeping up.
void belowThresholdNothingBreaks() {
    for (const auto preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        const auto compiled = fracturingReference(preset);
        AxisLattice lattice(compiled);
        lattice.stretchAlongX(.9 * compiled.damage_start_stretch, compiled.poisson_ratio);
        const auto result = tryFracturingStep(lattice.matter, 1e-9);
        require(result.converged, "an under-loaded lattice converges");
        require(result.broken_bonds == 0, "no bond may fail below the damage threshold");
        require(result.removed_bond_energy_j == 0, "nothing removed means nothing charged");
        for (const auto &bond : lattice.matter.bonds)
            require(bond.alive && bond.damage == 0,
                    "an under-loaded bond keeps zero damage");
    }
}

// The transactional contract must survive the new retopology loop. A trial
// budget too small to solve the step leaves every node, velocity, damage value
// and aliveness flag exactly as it was.
void rejectedFrameLeavesEveryInputUntouched() {
    const auto compiled = fracturingReference(MaterialPreset::Glass);
    AxisLattice lattice(compiled);
    lattice.stretchAlongX(1.5 * compiled.damage_end_stretch, compiled.poisson_ratio);
    for (auto &node : lattice.matter.nodes) node.velocity_m_s = {.01, -.02, .03};
    const auto nodes_before = lattice.matter.nodes;
    const auto bonds_before = lattice.matter.bonds;

    // One Newton update and one Krylov iteration cannot resolve this network.
    const auto starved = tryFracturingStep(lattice.matter, 1e-3, {}, nullptr,
        {.solver = {.maximum_iterations = 1, .maximum_linear_iterations = 1}});
    require(!starved.converged, "a starved solve must be rejected");
    require(starved.failure == FractureStepFailure::SolverRejected, "and reported as a solver rejection");
    for (std::size_t i = 0; i < nodes_before.size(); ++i) {
        near(length(lattice.matter.nodes[i].position_world_m - nodes_before[i].position_world_m), 0, 0,
             "rejected frame retains positions");
        near(length(lattice.matter.nodes[i].velocity_m_s - nodes_before[i].velocity_m_s), 0, 0,
             "rejected frame retains velocities");
    }
    for (std::size_t i = 0; i < bonds_before.size(); ++i) {
        require(lattice.matter.bonds[i].alive == bonds_before[i].alive,
                "rejected frame retains bond aliveness");
        near(lattice.matter.bonds[i].damage, bonds_before[i].damage, 0,
             "rejected frame retains bond damage");
    }

    // A trial budget that stops the retopology loop mid-cascade must roll the
    // whole frame back, not leave a half-broken topology behind.
    const auto capped = tryFracturingStep(lattice.matter, 1e-9, {}, nullptr,
        {.maximum_solver_trials = 1});
    require(!capped.converged && capped.failure == FractureStepFailure::TrialBudgetExhausted,
            "an exhausted trial budget is reported, not silently accepted");
    for (std::size_t i = 0; i < bonds_before.size(); ++i)
        require(lattice.matter.bonds[i].alive == bonds_before[i].alive,
                "an exhausted trial budget removes no bond");
}

// Fragments are the connected components left behind; nothing assigns them
// velocities. Severing every axial bond must split the lattice into planes.
void fragmentsAreTheSurvivingComponents() {
    const auto compiled = fracturingReference(MaterialPreset::Glass);
    AxisLattice lattice(compiled);
    lattice.stretchAlongX(1.5 * compiled.damage_end_stretch, compiled.poisson_ratio);
    const auto result = tryFracturingStep(lattice.matter, 1e-9);
    require(result.converged, "fracture step converges");
    const auto components = findConnectedComponents(lattice.matter);
    require(components.size() == 3, "severing every axial bond leaves the three transverse planes");
    for (const auto &component : components)
        require(component.node_indices.size() == 9,
                "each surviving plane keeps its nine nodes");
    require(result.broken_bonds == 18, "the eighteen axial bonds are the ones that fail");
    require(result.live_bonds + result.broken_bonds == lattice.matter.bonds.size(),
            "live and broken bonds account for the lattice");
}

// Removing a bond takes its stored energy out of the mechanical ledger. That
// energy has to appear in the report, otherwise fracture would look like an
// energy-audit violation or, worse, silently balance.
void removedBondEnergyClosesTheLedger() {
    const auto compiled = fracturingReference(MaterialPreset::Glass);
    AxisLattice lattice(compiled);
    lattice.stretchAlongX(1.5 * compiled.damage_end_stretch, compiled.poisson_ratio);
    const auto before = measureMaterialMechanics(lattice.matter);
    double residual_sum = 0, removed = 0;
    for (unsigned step = 0; step < 20; ++step) {
        const auto result = tryFracturingStep(lattice.matter, 1e-6);
        require(result.converged, "each fracturing step converges");
        residual_sum += result.energy_residual_j;
        removed += result.removed_bond_energy_j;
    }
    const auto after = measureMaterialMechanics(lattice.matter);
    require(removed > 0, "breaking a strained bond must remove stored energy");
    // Nothing here widens an acceptance budget: every trial passed the unmodified
    // per-step audit, and the only extra term is the named removal energy.
    near(after.mechanicalEnergy() - before.mechanicalEnergy() + removed, residual_sum, 1e-9,
         "energy change equals the accepted per-step residuals plus the removed bond energy");
    std::cout << "  ledger removed_j=" << removed << " residual_sum_j=" << residual_sum
              << " mechanical_change_j=" << after.mechanicalEnergy() - before.mechanicalEnergy() << '\n';
}

// The three removal instants are different physics, not different bookkeeping.
// EndOfStep lets the overstressed bond act for the whole interval; StepRestart
// removes it at the interval's start. They must both be reachable and must be
// distinguishable in what leaves the ledger.
void removalTimingChangesTheOutcome() {
    const auto compiled = fracturingReference(MaterialPreset::Glass);
    double energies[3]{};
    unsigned trials[3]{};
    std::size_t broken[3]{};
    const BondFailureTiming timings[3]{BondFailureTiming::EndOfStep,
        BondFailureTiming::StepRestart, BondFailureTiming::BisectedTime};
    for (unsigned mode = 0; mode < 3; ++mode) {
        AxisLattice lattice(compiled);
        lattice.stretchAlongX(1.5 * compiled.damage_end_stretch, compiled.poisson_ratio);
        // Long enough that the lattice relaxes measurably inside the interval,
        // so the two removal instants see genuinely different configurations.
        const auto result = tryFracturingStep(lattice.matter, 2e-6, {}, nullptr,
            {.timing = timings[mode]});
        require(result.converged, "every removal timing must converge on this fixture");
        energies[mode] = result.removed_bond_energy_j;
        trials[mode] = result.solver_trials;
        broken[mode] = result.broken_bonds;
        std::cout << "  timing=" << mode << " removed_j=" << energies[mode]
                  << " trials=" << trials[mode] << " bisections=" << result.bisections
                  << " broken=" << broken[mode] << '\n';
    }
    require(trials[0] == 1, "end-of-step removal costs exactly one solve");
    require(trials[1] > trials[0], "a restart costs at least one extra solve");
    require(trials[2] >= trials[1], "bisection cannot be cheaper than a plain restart");
    for (unsigned mode = 0; mode < 3; ++mode)
        require(broken[mode] > 0 && energies[mode] > 0,
                "each timing must break bonds and charge their stored energy");
    require(std::abs(energies[0] - energies[1]) > 1e-12 * energies[1],
            "keeping an overstressed bond for the whole interval must remove a "
            "different amount of stored energy than removing it at the start");
}

} // namespace

int main() {
    try {
        bothLanesNameTheSameFailingBonds();
        std::cout << "[PASS] explicit and implicit lanes share one failure criterion\n";
        belowThresholdNothingBreaks();
        std::cout << "[PASS] no material loses a bond below its damage threshold\n";
        rejectedFrameLeavesEveryInputUntouched();
        std::cout << "[PASS] a rejected fracturing frame is fully transactional\n";
        fragmentsAreTheSurvivingComponents();
        std::cout << "[PASS] fragments are the surviving connected components\n";
        removedBondEnergyClosesTheLedger();
        std::cout << "[PASS] removed bond energy closes the mechanical ledger\n";
        removalTimingChangesTheOutcome();
        std::cout << "[PASS] removal timing is selectable and measurably different\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
