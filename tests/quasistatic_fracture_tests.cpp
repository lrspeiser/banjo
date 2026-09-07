// The quasi-static fracture lane.
//
// Pinned here: the box lattice is what it claims (uniform cells, sphere rules);
// the static solver is an equilibrium solver (reactions balance loads, stored
// energy is the work done, unilateral support never pulls); the lane breaks
// bonds through the shared criterion and nothing else; its energy ledger
// closes with every term named; a rejected configuration is reported, not
// papered over; and glass, oak and iron go through the identical scene.

#include "fracture/BondFailure.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/PieceGeometry.hpp"
#include "fracture/QuasiStaticFracture.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"
#include "physics/ConservativeStep.hpp"
#include "physics/FractureStep.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <numeric>
#include <set>
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
        throw std::runtime_error(std::string(message) + ": " + std::to_string(actual) + " vs " + std::to_string(expected));
}

CompiledBrittleMaterial fracturing(MaterialPreset preset, double cell) {
    const auto material = makeReferenceMaterial(preset, 17);
    return withStrengthDerivedFailure(compileElasticLatticeReference(material, cell, 2), material);
}

struct Tile {
    BoxRecipe recipe;
    CompiledBrittleMaterial compiled;
    LatticeAsset asset;
    ActiveMatter matter;
    Vec3 center;
    Tile(MaterialPreset preset, unsigned nx, unsigned ny, unsigned nz, double cell, Vec3 center_m = {})
        : recipe{nx, ny, nz, cell, 2}, compiled(fracturing(preset, cell)), asset(generateBoxLattice(recipe, compiled)), center(center_m) {
        matter.asset = &asset;
        matter.material = compiled;
        matter.bonds.resize(asset.bonds.size());
        for (const auto &node : asset.nodes) {
            const Vec3 p = node.local_position_m + center;
            matter.nodes.push_back({p, p, {}, node.represented_volume_m3 * compiled.density_kg_m3, {}});
            matter.reference_positions_world_m.push_back(p);
        }
    }
    std::vector<std::uint32_t> bottomRim() const {
        std::vector<std::uint32_t> rim;
        for (std::uint32_t i = 0; i < asset.nodes.size(); ++i) {
            const auto g = asset.nodes[i].grid;
            if (g.y == 0 && (g.x == 0 || g.z == 0 || g.x + 1 == int(recipe.cells_x) || g.z + 1 == int(recipe.cells_z))) rim.push_back(i);
        }
        return rim;
    }
};

// The box lattice: every node carries one full cell, the bond rules are the
// sphere generator's, and the adjacency is consistent.
void boxLatticeIsUniform() {
    Tile tile(MaterialPreset::Glass, 5, 2, 4, 0.02);
    require(tile.asset.nodes.size() == 40, "5x2x4 cells give 40 nodes");
    near(tile.asset.total_mass_kg, 2500.0 * 40 * 0.02 * 0.02 * 0.02, 1e-12, "mass is density times volume");
    for (const auto &node : tile.asset.nodes) near(node.represented_volume_m3, 8e-6, 1e-18, "every cell is full");
    std::set<std::pair<std::uint32_t, std::uint32_t>> seen;
    for (const auto &bond : tile.asset.bonds) {
        require(bond.node_a != bond.node_b, "no self bonds");
        require(seen.insert(std::minmax(bond.node_a, bond.node_b)).second, "no duplicate bonds");
        const double grid_distance = bond.rest_length_m / 0.02;
        require(grid_distance <= 2.0 + 1e-9, "bonds stay within the horizon");
        // Compliance scales with the squared grid distance, as the sphere generator's does.
        near(bond.compliance, tile.compiled.bond_compliance * std::max(1.0, grid_distance * grid_distance), 1e-15 * bond.compliance, "horizon weight");
    }
    // Same rules as the sphere generator: a sphere that fully covers a 1-cell
    // neighbourhood has the interior node's degree equal to the box interior's.
    require(tile.asset.adjacency_offsets.back() == 2 * tile.asset.bonds.size(), "adjacency lists every bond twice");
    std::cout << "  box lattice: nodes=" << tile.asset.nodes.size() << " bonds=" << tile.asset.bonds.size() << '\n';
}

// A bar with one end fixed and a force on the other: the reactions balance the
// load, the stored energy is half the work (Clapeyron), and the residual of
// K u = f + reactions is zero.
void staticSolverIsAnEquilibriumSolver() {
    Tile bar(MaterialPreset::Glass, 6, 2, 2, 0.02);
    StaticLatticeSolver solver(bar.matter);
    std::vector<StaticConstraint> constraints;
    for (std::uint32_t i = 0; i < bar.asset.nodes.size(); ++i)
        if (bar.asset.nodes[i].grid.x == 0)
            for (const Vec3 axis : {Vec3{1, 0, 0}, Vec3{0, 1, 0}, Vec3{0, 0, 1}}) constraints.push_back({i, axis, 0.0});
    std::vector<Vec3> loads(bar.asset.nodes.size());
    Vec3 total{};
    for (std::uint32_t i = 0; i < bar.asset.nodes.size(); ++i)
        if (bar.asset.nodes[i].grid.x == 5) { loads[i] = {100.0, -30.0, 12.0}; total += loads[i]; }
    std::vector<Vec3> u(bar.asset.nodes.size());
    const auto result = solver.solve(loads, constraints, u, {.relative_tolerance = 1e-12});
    require(result.converged, "the bar solve converges");
    require(result.pinned_mechanism_directions == 0, "a bar has no mechanism");
    Vec3 reaction{};
    for (std::size_t k = 0; k < constraints.size(); ++k) reaction += result.reactions_n[k] * constraints[k].direction;
    near(length(reaction + total), 0.0, 1e-8 * length(total), "reactions balance the load");
    double work = 0;
    for (std::size_t i = 0; i < u.size(); ++i) work += dot(loads[i], u[i]);
    near(solver.elasticEnergy(u), 0.5 * work, 1e-9 * work, "stored energy is half the work");
    std::vector<Vec3> force;
    solver.applyStiffness(u, force);
    double residual = 0;
    for (std::size_t i = 0; i < u.size(); ++i)
        if (bar.asset.nodes[i].grid.x != 0) residual = std::max(residual, length(force[i] - loads[i]));
    near(residual, 0.0, 1e-8 * length(total), "free nodes are in equilibrium");
    // Stiffness check against the material: an axial bar of glass, E A / L.
    double axial = 0;
    unsigned tips = 0;
    for (std::uint32_t i = 0; i < u.size(); ++i) if (bar.asset.nodes[i].grid.x == 5) { axial += u[i].x; ++tips; }
    const double apparent_modulus = (total.x / (0.04 * 0.04)) / ((axial / tips) / 0.10);
    std::cout << "  bar: pcg_iterations=" << result.iterations << " apparent_E=" << apparent_modulus << " Pa (glass 7e10; lattice geometry sets the ratio)\n";
    require(apparent_modulus > 1e10 && apparent_modulus < 3e11, "the bar is stiff like glass, not like rubber or steel");
}

// A tile resting on its rim under gravity: unilateral reactions are never
// negative, they carry the weight, and nothing sinks below the plane.
void unilateralSupportCarriesTheWeightWithoutPulling() {
    Tile tile(MaterialPreset::Glass, 6, 2, 6, 0.02, {0, 0.5, 0});
    const auto rim = tile.bottomRim();
    QuasiStaticImpactScene scene;
    scene.gravity_m_s2 = {0, -9.81, 0};
    scene.support = makeSupportPlane({0, 0.5 - 0.02 + 0.01, 0}, {0, 1, 0});
    scene.support_nodes = rim;
    // A ball too slow to matter, so the run is gravity alone.
    scene.ball_center_m = {0, 0.5 + 0.02 + 0.04, 0};
    scene.ball_radius_m = 0.04;
    scene.ball_mass_kg = 2.0;
    scene.ball_speed_m_s = 0.0;
    scene.maximum_travel_m = 0.05;
    const auto result = runQuasiStaticImpact(tile.matter, scene);
    require(result.stop == QuasiStaticStop::BallStopped, "with no kinetic energy the ball is stopped immediately");
    require(result.broken_bonds == 0, "a resting tile does not break");
    near(result.pinned_rigid_force_n, 0.0, 1e-9 * tile.asset.total_mass_kg * 9.81, "a symmetric resting tile needs no friction");
    near(result.required_friction_coefficient, 0.0, 1e-9, "the frame needs no friction coefficient to hold it");
    const double weight = tile.asset.total_mass_kg * 9.81;
    require(result.maximum_support_normal_force_n > 0 && result.maximum_support_normal_force_n < weight, "the largest rim reaction is a fraction of the weight");
    near(result.total_support_normal_force_n, weight, 1e-9 * weight, "the rim carries exactly the weight");
    for (std::uint32_t i = 0; i < tile.matter.nodes.size(); ++i) {
        const double gap = signedDistanceToPlane(scene.support, tile.matter.nodes[i].position_world_m);
        if (tile.asset.nodes[i].grid.y == 0 && std::find(rim.begin(), rim.end(), i) != rim.end()) near(std::min(gap, 0.0), 0.0, 1e-12, "rim nodes stay on the plane");
        else if (tile.asset.nodes[i].grid.y == 0) require(gap < 0.0, "interior bottom nodes sag through the hole in the frame");
    }
    std::cout << "  resting tile: max_rim_reaction=" << result.maximum_support_normal_force_n << " N of " << weight << " N weight\n";
}

// Both lanes, handed the same over-stretched configuration, name the same
// failing bonds: the lane calls the shared criterion and nothing of its own.
void theLaneNamesTheSameBondsAsTheImplicitLane() {
    for (const auto preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        Tile a(preset, 4, 2, 2, 0.02), b(preset, 4, 2, 2, 0.02);
        const double strain = 1.5 * a.compiled.damage_end_stretch;
        for (Tile *tile : {&a, &b})
            for (auto &node : tile->matter.nodes) {
                node.position_world_m.x *= 1 + strain;
                node.position_world_m.y *= 1 - tile->compiled.poisson_ratio * strain;
                node.position_world_m.z *= 1 - tile->compiled.poisson_ratio * strain;
            }
        // The implicit lane over a vanishing interval.
        const auto implicit = tryFracturingStep(a.matter, 1e-9);
        require(implicit.converged, "implicit reference converges");
        // The lane's own evaluation: the shared functions at this configuration.
        resetBondStrainPeaks(b.matter);
        accumulateBondStrainPeaks(b.matter);
        std::vector<std::uint32_t> removed;
        (void)applyBondFailure(b.matter, &removed);
        std::vector<std::uint32_t> implicit_dead;
        for (std::uint32_t i = 0; i < a.matter.bonds.size(); ++i) if (!a.matter.bonds[i].alive) implicit_dead.push_back(i);
        require(!removed.empty(), "over-stretched bonds fail");
        require(removed == implicit_dead, "both lanes name the identical failing bonds");
        std::cout << "  " << materialPresetName(preset) << ": " << removed.size() << " bonds fail in both lanes\n";
    }
}

struct ImpactFixture {
    Tile tile;
    QuasiStaticImpactScene scene;
    explicit ImpactFixture(MaterialPreset preset, double drop = 2.0, unsigned n = 7)
        : tile(preset, n, 2, n, 0.02, {0, 0.30 + 0.02, 0}) {
        scene.gravity_m_s2 = {0, -9.81, 0};
        scene.support = makeSupportPlane({0, 0.30 + 0.01, 0}, {0, 1, 0});
        scene.support_nodes = tile.bottomRim();
        // Centre node of the top layer is the first contact.
        double top = -1;
        for (const auto &node : tile.matter.nodes) top = std::max(top, node.position_world_m.y);
        scene.ball_center_m = {0, top + 0.04, 0};
        scene.ball_radius_m = 0.04;
        scene.ball_mass_kg = 7870.0 * (4.0 / 3.0) * 3.14159265358979 * 0.04 * 0.04 * 0.04;
        scene.ball_speed_m_s = std::sqrt(2 * 9.81 * drop);
        scene.maximum_travel_m = 0.06;
    }
};

// The ledger closes with every term named, the ball's work equals the change of
// the potential within every segment, and the mass is all still there.
void impactLedgerCloses() {
    ImpactFixture f(MaterialPreset::Glass);
    const double mass_before = std::accumulate(f.tile.matter.nodes.begin(), f.tile.matter.nodes.end(), 0.0, [](double s, const auto &n) { return s + n.mass_kg; });
    const auto r = runQuasiStaticImpact(f.tile.matter, f.scene);
    require(r.converged, "the glass impact runs to a physical stop");
    require(r.stop == QuasiStaticStop::BallThrough || r.stop == QuasiStaticStop::BallStopped, "the stop is the ball's, not a budget");
    require(r.broken_bonds > 0 && r.first_failure_bonds.size() > 0, "a 2 kg ball from 2 m breaks bonds in a 140 mm glass tile");
    const double closure = r.ball_work_j - (r.potential_end_j - r.potential_start_j) - r.removed_bond_energy_linear_j - r.released_energy_j - r.relaxation_energy_j;
    near(closure, 0.0, 1e-9 * std::max(1.0, r.ball_work_j), "work = potential change + removed + released + relaxation");
    near(r.kinetic_energy_in_j, r.ball_work_j + r.kinetic_energy_out_j, 1e-12 * r.kinetic_energy_in_j, "kinetic energy in = work + kinetic energy out");
    // The reactions are read from a solve converged to 1e-10 on its residual;
    // the work they integrate to matches the potential change to that order.
    require(r.segment_work_mismatch_j <= 1e-7 * std::max(1.0, r.ball_work_j), "the reactions integrate to the potential change");
    require(r.relaxation_energy_j >= -1e-12, "re-equilibration never creates energy");
    require(r.released_energy_j >= 0 && r.removed_bond_energy_linear_j >= 0, "removed and released energies are non-negative");
    // The shared criterion's own removed-energy figure agrees with the linear
    // model to the strain order, as it must.
    near(r.removed_bond_energy_j, r.removed_bond_energy_linear_j, 1e-2 * r.removed_bond_energy_linear_j + 1e-12, "shared and linear removed energies agree to strain order");
    const double mass_after = std::accumulate(f.tile.matter.nodes.begin(), f.tile.matter.nodes.end(), 0.0, [](double s, const auto &n) { return s + n.mass_kg; });
    near(mass_after, mass_before, 0.0, "mass is untouched");
    const auto components = findConnectedComponents(f.tile.matter);
    require(components.size() == r.components && r.component_frozen.size() == components.size(), "component bookkeeping matches the shared function");
    for (const auto &node : f.tile.matter.nodes) require(length(node.velocity_m_s) == 0, "the lane assigns no velocities");
    std::cout << "  glass impact: stop=" << quasiStaticStopName(r.stop) << " events=" << r.events << " rounds=" << r.rounds << " solves=" << r.static_solves
              << " broken=" << r.broken_bonds << " pieces=" << r.components << " frozen=" << r.frozen_components << " work=" << r.ball_work_j
              << " J of " << r.kinetic_energy_in_j << " J, closure=" << closure << " J, mismatch=" << r.segment_work_mismatch_j << " J\n";
}

// A configuration the static picture cannot answer is reported, never
// silently regularised: a tile with no support at all is frozen whole and the
// ball passes it, breaking nothing.
void anUnsupportedTileIsFrozenNotFaked() {
    ImpactFixture f(MaterialPreset::Glass);
    f.scene.support_nodes.clear();
    const auto r = runQuasiStaticImpact(f.tile.matter, f.scene);
    require(r.stop == QuasiStaticStop::BallThrough, "an unsupported tile offers no static resistance");
    require(r.broken_bonds == 0, "nothing breaks without a load path");
    require(r.frozen_components == 1 && r.components == 1, "the whole tile is one frozen piece");
    near(r.ball_work_j, 0.0, 0.0, "no work is done on a frozen tile");
}

// Glass, oak and iron through the identical scene. Only the comparison is
// asserted: glass, the weakest in strain, breaks; the others run to a
// physical stop and are reported.
void glassOakIronUnderIdenticalConditions() {
    std::size_t glass_broken = 0;
    for (const auto preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        ImpactFixture f(preset);
        const auto r = runQuasiStaticImpact(f.tile.matter, f.scene);
        require(r.converged, "every material reaches a physical stop");
        if (preset == MaterialPreset::Glass) glass_broken = r.broken_bonds;
        std::cout << "  " << materialPresetName(preset) << ": stop=" << quasiStaticStopName(r.stop) << " broken=" << r.broken_bonds
                  << " pieces=" << r.components << " work=" << r.ball_work_j << " J stored=" << r.stored_elastic_j << " J travel=" << r.travel_m << " m\n";
    }
    require(glass_broken > 0, "glass breaks under the shared conditions");
}

// The reference's support mask: only masked nodes rest on the plane, so a tile
// resting on its rim sags through the hole and the masked rim stays up.
void referenceSupportMaskRestrictsTheSupport() {
    Tile tile(MaterialPreset::Glass, 6, 2, 6, 0.02, {0, 0.5, 0});
    std::vector<bool> mask(tile.asset.nodes.size(), false);
    for (const auto rim : tile.bottomRim()) mask[rim] = true;
    const auto plane = makeSupportPlane({0, 0.5 - 0.01, 0}, {0, 1, 0});
    ConservativeStepSettings settings;
    settings.support = &plane;
    settings.support_node_mask = &mask;
    double sag = 0;
    for (unsigned step = 0; step < 40; ++step) {
        const auto result = tryConservativeStep(tile.matter, 2.5e-6, {0, -9.81, 0}, nullptr, settings);
        require(result.converged, "masked support steps converge");
        for (std::uint32_t i = 0; i < tile.matter.nodes.size(); ++i) {
            const double gap = signedDistanceToPlane(plane, tile.matter.nodes[i].position_world_m);
            if (mask[i]) require(gap >= -settings.contact_tolerance_m, "masked rim nodes never penetrate the plane");
            else if (tile.asset.nodes[i].grid.y == 0) sag = std::min(sag, gap);
        }
    }
    require(sag < 0, "interior nodes fall through the hole the mask leaves");
    std::vector<bool> wrong(3, true);
    settings.support_node_mask = &wrong;
    bool rejected = false;
    try { (void)tryConservativeStep(tile.matter, 1e-6, {}, nullptr, settings); } catch (const std::invalid_argument &) { rejected = true; }
    require(rejected, "a mask of the wrong size is rejected");
}

// Greedy boxes cover every cell exactly once and merge solid blocks.
void voxelBoxesCoverCellsExactlyOnce() {
    std::vector<GridCoord> block;
    for (int z = 0; z < 3; ++z) for (int y = 0; y < 2; ++y) for (int x = 0; x < 4; ++x) block.push_back({x, y, z});
    const auto merged = mergeCellsIntoBoxes(block);
    require(merged.size() == 1 && merged.front().cellCount() == 24, "a solid block is one box");
    std::vector<GridCoord> shape{{0, 0, 0}, {1, 0, 0}, {2, 0, 0}, {0, 1, 0}, {0, 2, 0}, {5, 5, 5}};
    const auto boxes = mergeCellsIntoBoxes(shape);
    unsigned covered = 0;
    std::set<std::tuple<int, int, int>> cells;
    for (const auto &box : boxes)
        for (int z = box.minimum.z; z <= box.maximum.z; ++z)
            for (int y = box.minimum.y; y <= box.maximum.y; ++y)
                for (int x = box.minimum.x; x <= box.maximum.x; ++x) { ++covered; require(cells.insert({x, y, z}).second, "boxes do not overlap"); }
    require(covered == shape.size(), "boxes cover every cell");
    for (const auto &cell : shape) require(cells.contains({cell.x, cell.y, cell.z}), "every cell is covered");
    require(boxes.size() == 3, "an L and a loose cell are three boxes");
}

} // namespace

int main() {
    try {
        boxLatticeIsUniform();
        std::cout << "[PASS] the box lattice is uniform and follows the sphere generator's bond rules\n";
        staticSolverIsAnEquilibriumSolver();
        std::cout << "[PASS] the static solver is an equilibrium solver\n";
        unilateralSupportCarriesTheWeightWithoutPulling();
        std::cout << "[PASS] unilateral support carries the weight without pulling\n";
        theLaneNamesTheSameBondsAsTheImplicitLane();
        std::cout << "[PASS] the lane names the same failing bonds as the implicit lane\n";
        impactLedgerCloses();
        std::cout << "[PASS] the impact ledger closes with every term named\n";
        anUnsupportedTileIsFrozenNotFaked();
        std::cout << "[PASS] an unsupported tile is frozen and reported, not regularised\n";
        glassOakIronUnderIdenticalConditions();
        std::cout << "[PASS] glass, oak and iron run through the identical scene\n";
        referenceSupportMaskRestrictsTheSupport();
        std::cout << "[PASS] the reference lane's support mask restricts the support\n";
        voxelBoxesCoverCellsExactlyOnce();
        std::cout << "[PASS] greedy voxel boxes cover every cell exactly once\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
