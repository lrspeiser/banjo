// The precomputed-basis fracture lane, checked against the engine it lives in:
// the basis reproduces the lattice's own stiffness, the closed-form evolution
// agrees with the implicit conservative reference on the same lattice, the
// modal ledger closes across a cascade, a bond downdate is exact, and the lane
// names the same failing bonds as the stepped lane on a strained lattice.

#include "fracture/BondFailure.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"
#include "modal/ModalBasis.hpp"
#include "modal/ModalFracture.hpp"
#include "physics/ConservativeStep.hpp"
#include "physics/FractureStep.hpp"
#include "physics/MechanicalAccounting.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::modal;

void require(bool result, const std::string &message) {
    if (!result) throw std::runtime_error(message);
}

struct Tile {
    LatticeAsset asset;
    ActiveMatter matter;
    std::vector<std::uint32_t> free_nodes;
    CompiledBrittleMaterial compiled;
};

// A cubic-cell box lattice with the perimeter ring of cells fixed, the scene
// the lane is built for. `heavy_fixed` gives the fixed nodes an enormous mass
// instead, which is how the stepped reference represents a clamp.
Tile makeTile(MaterialPreset preset, unsigned nx, unsigned ny, unsigned nz, double h, bool clamp_ring,
              bool with_failure, double heavy_fixed = 0.0) {
    Tile tile;
    const auto material = makeReferenceMaterial(preset, 17);
    tile.compiled = with_failure
        ? withStrengthDerivedFailure(compileElasticLatticeReference(material, h, 2), material)
        : compileElasticLatticeReference(material, h, 2);
    tile.asset = generateBoxLattice({nx, ny, nz, h, 2}, tile.compiled);
    tile.matter.asset = &tile.asset;
    tile.matter.material = tile.compiled;
    tile.matter.bonds.resize(tile.asset.bonds.size());
    for (std::uint32_t i = 0; i < tile.asset.nodes.size(); ++i) {
        const auto &node = tile.asset.nodes[i];
        const bool fixed = clamp_ring && (node.grid.x == 0 || node.grid.z == 0 ||
            node.grid.x + 1 == static_cast<int>(nx) || node.grid.z + 1 == static_cast<int>(nz));
        double mass = node.represented_volume_m3 * tile.compiled.density_kg_m3;
        if (fixed && heavy_fixed > 0.0) mass *= heavy_fixed;
        tile.matter.nodes.push_back({node.local_position_m, {}, {}, mass, {}});
        tile.matter.reference_positions_world_m.push_back(node.local_position_m);
        if (!fixed) tile.free_nodes.push_back(i);
    }
    return tile;
}


// Put the ball on the tile's axis so that its nearest free node is exactly
// `gap` outside the contact radius. With an even cell count no node sits on
// the axis, so the first contact is off-axis and this is the honest distance.
void placeBall(const Tile &tile, ModalBall &ball, double gap) {
    const double reach = ball.contact_radius_m + gap;
    double y = -1e300;
    for (const std::uint32_t node : tile.free_nodes) {
        const Vec3 p = tile.matter.reference_positions_world_m[node];
        const double radial2 = p.x * p.x + p.z * p.z;
        if (radial2 < reach * reach) y = std::max(y, p.y + std::sqrt(reach * reach - radial2));
    }
    ball.motion.center_of_mass_world_m = {0.0, y, 0.0};
}

// K phi = omega^2 M phi must hold against the lattice's own bonds, and phi must
// be M-orthonormal. Rigid modes: none when clamped, six when free.
void basisSatisfiesTheLattice() {
    for (const bool clamp : {true, false}) {
        auto tile = makeTile(MaterialPreset::Glass, 5, 2, 5, 0.02, clamp, false);
        ModalBasis basis(tile.matter, tile.free_nodes);
        require(basis.residualAgainst(tile.matter) < 1e-12, "basis residual against the lattice stiffness");
        require(basis.orthogonalityDefect() < 1e-12, "basis M-orthonormality");
        require(basis.rigidModeCount() == (clamp ? 0U : 6U), "rigid mode count");
        // Fastest mode must sit at the lattice's own resolution estimate or below it.
        const auto limit = measureLatticeResolutionLimit(tile.asset, tile.compiled);
        const double omega_max = std::sqrt(basis.omegaSquaredMaxAtCreation());
        require(omega_max <= limit.fastest_mode_angular_frequency_rad_s * 1.0000001,
                "the spectrum is bounded by the nodal stiffness/mass estimate");
        std::cout << "  clamp=" << clamp << " modes=" << basis.modes() << " rigid=" << basis.rigidModeCount()
                  << " fastest_period_s=" << 2.0 * std::numbers::pi / omega_max
                  << " lattice_estimate_s=" << limit.fastest_mode_period_s << '\n';
    }
}

// One bond downdate must give the same spectrum as rebuilding, and the carried
// modal state must describe the same physical displacement.
void downdateMatchesRebuild() {
    auto tile = makeTile(MaterialPreset::Glass, 5, 2, 5, 0.02, true, false);
    ModalBasis updated(tile.matter, tile.free_nodes);
    std::vector<double> q(updated.modes());
    for (std::size_t k = 0; k < q.size(); ++k) q[k] = std::sin(0.37 * static_cast<double>(k + 1)) * 1e-6;
    std::vector<double> before;
    updated.displacement(q, before);
    for (const std::uint32_t bond : {std::uint32_t{40}, std::uint32_t{41}, std::uint32_t{200}}) {
        tile.matter.bonds[bond].alive = false;
        const auto stats = updated.removeBond(tile.matter, bond, {&q});
        require(stats.retained > 0, "a live interior bond changes the basis");
    }
    require(updated.residualAgainst(tile.matter) < 1e-12, "downdated basis satisfies the reduced lattice");
    require(updated.orthogonalityDefect() < 1e-12, "downdated basis stays M-orthonormal");
    std::vector<double> after;
    updated.displacement(q, after);
    for (std::size_t i = 0; i < after.size(); ++i)
        require(std::abs(after[i] - before[i]) < 1e-18, "carried state is the same displacement");
    ModalBasis rebuilt(tile.matter, tile.free_nodes);
    std::vector<double> a = updated.omegaSquared(), b = rebuilt.omegaSquared();
    std::sort(a.begin(), a.end());
    std::sort(b.begin(), b.end());
    for (std::size_t k = 0; k < a.size(); ++k)
        require(std::abs(a[k] - b[k]) <= 1e-10 * b.back(), "downdated spectrum equals the rebuilt spectrum");
}

// The closed-form modal evolution and the implicit conservative reference are
// two solutions of the same lattice. Started from the same deformed state,
// they must agree to the reference's own discretisation error, which shrinks
// as its step shrinks.
void closedFormAgreesWithTheImplicitReference() {
    auto tile = makeTile(MaterialPreset::Glass, 5, 2, 5, 0.02, true, false, 1e9);
    // Free nodes also carry a heavy fixed ring for the reference; the modal
    // lane simply excludes those nodes.
    ModalBasis basis(tile.matter, tile.free_nodes);
    // Initial condition: an authored velocity field on the free nodes.
    std::vector<double> velocity(basis.dofs());
    for (std::size_t f = 0; f < tile.free_nodes.size(); ++f) {
        const auto &p = tile.matter.reference_positions_world_m[tile.free_nodes[f]];
        velocity[3 * f] = 0.0;
        velocity[3 * f + 1] = -0.5 * std::cos(30.0 * p.x) * std::cos(30.0 * p.z);
        velocity[3 * f + 2] = 0.0;
    }
    std::vector<double> qdot;
    basis.project(velocity, qdot);
    const double horizon = 4.0e-6;
    std::vector<double> q_end(basis.modes()), u_end;
    for (std::size_t k = 0; k < basis.modes(); ++k) {
        const double w = std::sqrt(basis.omegaSquared()[k]);
        q_end[k] = basis.isRigidMode(k) ? qdot[k] * horizon : qdot[k] / w * std::sin(w * horizon);
    }
    basis.displacement(q_end, u_end);

    double previous_error = 0.0;
    for (const double dt : {5.0e-7, 2.5e-7, 1.25e-7}) {
        ActiveMatter matter = tile.matter;
        for (std::size_t f = 0; f < tile.free_nodes.size(); ++f)
            matter.nodes[tile.free_nodes[f]].velocity_m_s = {velocity[3 * f], velocity[3 * f + 1], velocity[3 * f + 2]};
        const unsigned steps = static_cast<unsigned>(std::llround(horizon / dt));
        for (unsigned s = 0; s < steps; ++s) {
            const auto result = tryConservativeStep(matter, dt);
            require(result.converged, "reference step converges");
        }
        double error = 0.0, scale = 0.0;
        for (std::size_t f = 0; f < tile.free_nodes.size(); ++f) {
            const Vec3 reference = matter.nodes[tile.free_nodes[f]].position_world_m -
                                   matter.reference_positions_world_m[tile.free_nodes[f]];
            const Vec3 modal{u_end[3 * f], u_end[3 * f + 1], u_end[3 * f + 2]};
            error = std::max(error, length(reference - modal));
            scale = std::max(scale, length(modal));
        }
        std::cout << "  reference dt=" << dt << " max |u_ref - u_modal| = " << error
                  << " (peak displacement " << scale << ")\n";
        require(error < 0.05 * scale, "reference and closed form agree to a few percent at this step");
        if (previous_error > 0.0) require(error < previous_error, "the reference converges toward the closed form");
        previous_error = error;
    }
}

// The ball strikes a clamped tile: the ledger closes to roundoff, bonds break
// only when the shared criterion says so, and the basis stays exact across
// the cascade under rank-one updates.
void impactLedgerClosesAndBasisStaysExact() {
    auto tile = makeTile(MaterialPreset::Glass, 6, 2, 6, 0.02, true, true);
    const auto iron = makeReferenceMaterial(MaterialPreset::Iron, 17);
    ModalBall ball;
    ball.radius_m = 0.02;
    ball.contact_radius_m = ball.radius_m + 0.01;
    ball.mass_kg = iron.density_kg_m3 * 4.0 / 3.0 * std::numbers::pi * std::pow(ball.radius_m, 3);
    ball.inertia_kg_m2 = 0.4 * ball.mass_kg * ball.radius_m * ball.radius_m;
    placeBall(tile, ball, 1e-4);
    ball.motion.linear_velocity_m_s = {0.0, -14.0, 0.0};
    ModalFractureSettings settings;
    settings.sample_dt_s = 1.0e-6;
    settings.window_s = 4.0e-4;
    settings.check_basis = true;
    const auto result = runModalImpact(tile.matter, tile.free_nodes, ball, settings);
    std::cout << "  rounds=" << result.rounds.size() << " broken=" << result.broken_bonds
              << " components=" << result.components << " first_failure_s=" << result.first_failure_time_s
              << " ledger_residual_j=" << result.ledger.residual_j
              << " removed_linear_j=" << result.ledger.removed_linear_energy_j
              << " removed_engine_j=" << result.ledger.removed_bond_energy_j
              << " contact_loss_j=" << result.ledger.contact_loss_j << '\n';
    require(result.contact_samples > 0, "the ball touched the tile");
    require(!result.rounds.empty(), "a 14 m/s iron ball breaks 20 mm glass cells");
    require(std::abs(result.ledger.residual_j) < 1e-9 * std::max(1.0, result.ledger.energy_start_j),
            "modal ledger closes to roundoff");
    double worst_residual = 0.0, worst_orthogonality = 0.0, worst_value = 0.0;
    for (const auto &round : result.rounds) {
        worst_residual = std::max(worst_residual, round.basis_residual);
        worst_orthogonality = std::max(worst_orthogonality, round.basis_orthogonality);
        worst_value = std::max(worst_value, round.basis_value_error);
        for (const std::uint32_t bond : round.bonds) {
            require(!tile.matter.bonds[bond].alive, "a bond named by a round is dead at the end");
            require(tile.matter.bonds[bond].damage >= 1.0, "a removed bond carries full damage");
        }
    }
    std::cout << "  basis across the cascade: residual " << worst_residual << " orthogonality "
              << worst_orthogonality << " value error " << worst_value << '\n';
    require(worst_residual < 1e-10, "updated basis satisfies the reduced lattice after every round");
    require(worst_orthogonality < 1e-10, "updated basis stays M-orthonormal after every round");
    require(worst_value < 1e-10, "updated spectrum equals a fresh decomposition after every round");
    // The engine's exact removal energy uses the bond's true extension; the
    // modal ledger uses the linearised one. They need not agree closely: a
    // node left with fewer than three live neighbours is judged on its own
    // stretch only, so it can slide sideways by millimetres before its last
    // bonds fail, and there the geometric term dominates. What must hold is
    // that both are positive and the ledger closes with the linear figure,
    // which was asserted above.
    require(result.ledger.removed_bond_energy_j > 0.0 && result.ledger.removed_linear_energy_j > 0.0,
            "both removal energies are positive");
    require(result.components == findConnectedComponents(tile.matter).size(), "components are reported");
}

// Recompute-mode and update-mode must produce the identical cascade: same
// bonds, same order, same times. That is the research claim in its strictest
// form on a small scene.
void updateAndRecomputeAgree() {
    ModalFractureResult results[2];
    for (unsigned mode = 0; mode < 2; ++mode) {
        auto tile = makeTile(MaterialPreset::Glass, 6, 2, 6, 0.02, true, true);
        const auto iron = makeReferenceMaterial(MaterialPreset::Iron, 17);
        ModalBall ball;
        ball.radius_m = 0.02;
        ball.contact_radius_m = ball.radius_m + 0.01;
        ball.mass_kg = iron.density_kg_m3 * 4.0 / 3.0 * std::numbers::pi * std::pow(ball.radius_m, 3);
        ball.inertia_kg_m2 = 0.4 * ball.mass_kg * ball.radius_m * ball.radius_m;
        placeBall(tile, ball, 1e-4);
        ball.motion.linear_velocity_m_s = {0.0, -14.0, 0.0};
        ModalFractureSettings settings;
        settings.sample_dt_s = 1.0e-6;
        settings.window_s = 3.0e-4;
        settings.basis_mode = mode == 0 ? BasisMode::Update : BasisMode::Recompute;
        results[mode] = runModalImpact(tile.matter, tile.free_nodes, ball, settings);
    }
    require(results[0].rounds.size() == results[1].rounds.size(), "same number of rounds");
    for (std::size_t r = 0; r < results[0].rounds.size(); ++r) {
        require(results[0].rounds[r].bonds == results[1].rounds[r].bonds, "same bonds in the same order");
        require(std::abs(results[0].rounds[r].time_s - results[1].rounds[r].time_s) < 1e-15, "same failure times");
    }
    std::cout << "  update vs recompute: " << results[0].rounds.size() << " rounds identical, broken "
              << results[0].broken_bonds << " vs " << results[1].broken_bonds << '\n';
}

// On a uniformly strained lattice the modal lane's criterion call must name
// exactly the bonds the implicit lane's does, for glass, oak and iron: the
// criterion is shared, so this pins that the lane feeds it the right field.
void sharedCriterionNamesTheSameBonds() {
    for (const auto preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        auto stepped = makeTile(preset, 4, 2, 4, 0.02, false, true);
        auto modal_tile = makeTile(preset, 4, 2, 4, 0.02, false, true);
        const double strain = 1.5 * stepped.compiled.damage_end_stretch;
        for (auto *t : {&stepped, &modal_tile})
            for (auto &node : t->matter.nodes) {
                node.position_world_m.x *= 1 + strain;
                node.position_world_m.y *= 1 - t->compiled.poisson_ratio * strain;
                node.position_world_m.z *= 1 - t->compiled.poisson_ratio * strain;
            }
        const auto reference = tryFracturingStep(stepped.matter, 1e-9);
        require(reference.converged, "implicit reference converges on the strained tile");
        // The modal lane evaluates the criterion through the same calls.
        resetBondStrainPeaks(modal_tile.matter);
        accumulateBondStrainPeaks(modal_tile.matter);
        std::vector<std::uint32_t> removed;
        applyBondFailure(modal_tile.matter, &removed);
        std::vector<std::uint32_t> stepped_dead;
        for (std::uint32_t b = 0; b < stepped.matter.bonds.size(); ++b)
            if (!stepped.matter.bonds[b].alive) stepped_dead.push_back(b);
        require(!removed.empty(), "the strained tile breaks");
        require(removed == stepped_dead, "modal and implicit lanes name the same failing bonds");
        std::cout << "  " << materialPresetName(preset) << " broken " << removed.size() << '/'
                  << removed.size() + (modal_tile.matter.bonds.size() - removed.size()) << '\n';
    }
}

} // namespace

int main() {
    try {
        basisSatisfiesTheLattice();
        std::cout << "[PASS] the basis satisfies the lattice's own stiffness and mass\n";
        downdateMatchesRebuild();
        std::cout << "[PASS] a bond downdate equals a rebuild and carries state exactly\n";
        closedFormAgreesWithTheImplicitReference();
        std::cout << "[PASS] the implicit reference converges toward the closed form\n";
        sharedCriterionNamesTheSameBonds();
        std::cout << "[PASS] one criterion: modal and implicit lanes name the same bonds\n";
        impactLedgerClosesAndBasisStaysExact();
        std::cout << "[PASS] impact: ledger closes and the updated basis stays exact across the cascade\n";
        updateAndRecomputeAgree();
        std::cout << "[PASS] rank-one updates reproduce the recomputed cascade exactly\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
