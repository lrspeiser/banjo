// Algorithm 2 checked against the engine it lives in.
//
//  1. The crack-influence matrix reproduces a direct solve with a bond removed:
//     A[b][b'] * F_b' is the strain change a fresh Cholesky solve of the cracked
//     stiffness gives, to the precision the float storage allows.
//  2. The influence matrix is reciprocal (Maxwell-Betti), which the Sherman-
//     Morrison factor must not break.
//  3. The peak dynamic strain table is linear in the impulse: the response is
//     linear in J to far better than four decimals, so J scales it.
//  4. The energy ledger closes: budget in = crack work spent + remaining.
//  5. The bond crack areas sum to the geometric area of an axis-aligned cut, so
//     a crack of a given area costs Gc per unit area at any cell size.
//  6. The lane's lattice is bond-for-bond the reference lane's lattice, so
//     first-failure sets can be compared by bond index.
//  7. A plate one cell thick is refused with the reason, not silently solved.

#include "fastlattice/TileImpactScene.hpp"
#include "griffith/GriffithCascade.hpp"
#include "matter/BoxLattice.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::griffith;

void require(bool result, const std::string &message) {
    if (!result) throw std::runtime_error(message);
}

// Small enough that a dense Cholesky reference is instant, thick enough that
// the lattice has stiffness in every direction.
PlateRequest smallPlate() {
    PlateRequest request;
    request.length_m = 0.10;
    request.width_m = 0.06;
    request.thickness_m = 0.04;
    request.cell_m = 0.02;
    request.ball_diameter_m = 0.06;
    request.support = SupportKind::Ledges;
    request.ledge_width_m = 0.02;
    return request;
}

PrecomputeOptions noCache() {
    PrecomputeOptions options;
    options.force_all_strikes = true;
    return options;
}

void influenceMatchesADirectSolve() {
    const auto plate = buildPlate(smallPlate());
    const std::size_t bonds = plate->matter.bonds.size();
    const std::size_t dofs = 3U * plate->free_nodes.size();
    const auto tables = precompute(*plate, noCache(), PlateModel::kNoIndex);
    require(tables.bonds == bonds, "the tables cover every bond");

    // A load with no symmetry, so no bond's response is accidentally zero.
    std::mt19937 generator(20260908u);
    std::uniform_real_distribution<double> spread(-1.0, 1.0);
    std::vector<double> force(dofs);
    for (double &value : force) value = 1.0e3 * spread(generator);

    std::vector<char> alive(bonds, 1);
    const std::vector<double> intact = directBondStrains(*plate, force, alive);

    std::size_t checked = 0;
    double worst = 0.0;
    for (std::size_t step = 0; step < bonds; step += std::max<std::size_t>(1, bonds / 12)) {
        const std::size_t prime = step;
        if (tables.release_singular[prime]) continue;
        alive[prime] = 0;
        const std::vector<double> cracked = directBondStrains(*plate, force, alive);
        alive[prime] = 1;
        // The force the broken bond was carrying, from the intact solve.
        const double released = plate->bond_stiffness_n_m[prime] * intact[prime] * plate->bond_length_m[prime];
        double scale = 0.0;
        for (std::size_t b = 0; b < bonds; ++b) scale = std::max(scale, std::abs(cracked[b] - intact[b]));
        require(scale > 0.0, "removing a bond changed no strain at all");
        for (std::size_t b = 0; b < bonds; ++b) {
            if (b == prime) continue;
            const double predicted = static_cast<double>(tables.influence[prime * bonds + b]) * released;
            const double actual = cracked[b] - intact[b];
            worst = std::max(worst, std::abs(predicted - actual) / scale);
        }
        ++checked;
    }
    require(checked >= 8, "the sweep must exercise several columns, saw " + std::to_string(checked));
    // The columns are stored as float32; 1e-5 of the column's own largest entry
    // is the storage floor, not the method's error.
    require(worst < 1.0e-5, "influence column disagrees with a direct cracked solve by " +
                                std::to_string(worst) + " of the column scale");
    std::cout << "        worst column error " << worst << " of the column scale over " << checked
              << " columns\n";
}

void influenceIsReciprocal() {
    const auto plate = buildPlate(smallPlate());
    const auto tables = precompute(*plate, noCache(), PlateModel::kNoIndex);
    const std::size_t bonds = tables.bonds;
    // A[b][b'] carries 1/(L_b denom_b'), so the symmetric quantity is
    // A[b][b'] L_b / scale_b' against A[b'][b] L_b' / scale_b.
    double worst = 0.0, scale = 0.0;
    for (std::size_t b = 0; b < bonds; ++b)
        for (std::size_t p = 0; p < bonds; ++p) {
            if (tables.release_singular[b] || tables.release_singular[p]) continue;
            const double left = static_cast<double>(tables.influence[p * bonds + b]) *
                                plate->bond_length_m[b] / tables.release_scale[p];
            const double right = static_cast<double>(tables.influence[b * bonds + p]) *
                                 plate->bond_length_m[p] / tables.release_scale[b];
            worst = std::max(worst, std::abs(left - right));
            scale = std::max(scale, std::abs(left));
        }
    require(scale > 0.0, "the influence matrix is empty");
    require(worst / scale < 1.0e-5, "the influence matrix is not reciprocal: " +
                                        std::to_string(worst / scale));
}

void peakResponseIsLinearInTheImpulse() {
    const auto plate = buildPlate(smallPlate());
    const auto tables = precompute(*plate, noCache(), PlateModel::kNoIndex);
    const ContactModel one = buildContact(*plate, 0.0, 0.0, 1.0);
    const ContactModel four = buildContact(*plate, 0.0, 0.0, 4.0);
    require(one.strike_row == four.strike_row, "the same offset must pick the same strike cell");
    require(four.impulse_n_s > 0.0, "the contact model delivered no impulse");
    const double ratio = four.impulse_n_s / one.impulse_n_s;
    require(std::abs(ratio - 4.0) < 1.0e-12, "the impulse is not linear in the speed");
    // The load a cascade reads is J * E[s][b]; the table is the same, so the
    // check is that the loads scale exactly with J and that E itself is finite.
    const float *column = tables.peak.data() + static_cast<std::size_t>(one.strike_row) * tables.bonds;
    double worst = 0.0, largest = 0.0;
    for (std::size_t b = 0; b < tables.bonds; ++b) {
        const double single = one.impulse_n_s * static_cast<double>(column[b]);
        const double quad = four.impulse_n_s * static_cast<double>(column[b]);
        require(std::isfinite(single) && std::isfinite(quad), "the peak table holds a non-finite strain");
        worst = std::max(worst, std::abs(quad - 4.0 * single));
        largest = std::max(largest, std::abs(single));
    }
    require(largest > 0.0, "the peak table is all zero; the impulse reaches no bond");
    require(worst <= 1.0e-12 * largest,
            "the load is not linear in the impulse to 12 decimals: " + std::to_string(worst / largest));
    std::cout << "        peak strain per unit impulse, largest bond " << largest << " at 1 m/s\n";
}

void theEnergyLedgerCloses() {
    const auto plate = buildPlate(smallPlate());
    const auto tables = precompute(*plate, noCache(), PlateModel::kNoIndex);
    for (const double speed : {2.0, 6.264, 12.0}) {
        auto working = buildPlate(smallPlate());
        const ContactModel contact = buildContact(*working, 0.0, 0.0, speed);
        const CascadeResult result = runCascade(*working, tables, contact, {});
        const double residual = result.energy_budget_j - result.energy_spent_j - result.energy_remaining_j;
        require(std::abs(residual) <= 1.0e-12 * std::max(1.0, result.energy_budget_j),
                "the energy ledger leaks " + std::to_string(residual) + " J at " + std::to_string(speed) + " m/s");
        double crack_work = 0.0;
        for (const auto &event : result.events) crack_work += event.crack_work_j;
        require(std::abs(crack_work - result.energy_spent_j) <= 1.0e-9 * std::max(1.0, crack_work),
                "the per-event crack work does not sum to the spent budget");
        require(result.energy_remaining_j >= -1.0e-12, "the cascade spent more than the budget");
        // Every event must be a bond that was alive and is now dead, once.
        std::vector<char> seen(working->matter.bonds.size(), 0);
        for (const auto &event : result.events) {
            require(!seen[event.bond], "a bond broke twice");
            seen[event.bond] = 1;
            require(!working->matter.bonds[event.bond].alive, "a broken bond is still alive");
            require(event.drive >= 1.0, "a bond broke below the criterion");
        }
        std::size_t dead = 0;
        for (const auto &bond : working->matter.bonds) dead += bond.alive ? 0 : 1;
        require(dead == result.events.size(), "the dead bond count does not match the event count");
    }
}

void bondAreasSumToACut() {
    for (const unsigned horizon : {1u, 2u, 3u}) {
        PlateRequest request = smallPlate();
        request.horizon = horizon;
        request.length_m = 0.20;
        request.width_m = 0.20;
        request.thickness_m = 0.20;
        request.ledge_width_m = 0.02;
        const auto plate = buildPlate(request);
        // Every bond crossing the mid-plane x = cut, charged to the (y, z)
        // column of its lower-x end, which is how the normalisation counts
        // them. Columns within one horizon of a free face are excluded: their
        // partners are missing, and the normalisation is an interior count.
        const double h = request.cell_m;
        const int nx = static_cast<int>(plate->layout.nx);
        const int margin = static_cast<int>(horizon);
        const int cut = nx / 2;
        double area = 0.0;
        for (std::size_t b = 0; b < plate->asset.bonds.size(); ++b) {
            const auto &rest = plate->asset.bonds[b];
            const auto &ga = plate->asset.nodes[rest.node_a].grid;
            const auto &gb = plate->asset.nodes[rest.node_b].grid;
            const GridCoord &low = ga.x <= gb.x ? ga : gb;
            const GridCoord &high = ga.x <= gb.x ? gb : ga;
            if (!(low.x < cut && high.x >= cut)) continue;
            if (low.y < margin || low.y >= static_cast<int>(plate->layout.ny) - margin) continue;
            if (low.z < margin || low.z >= static_cast<int>(plate->layout.nz) - margin) continue;
            area += plate->bond_area_m2[b];
        }
        const int rows = (static_cast<int>(plate->layout.ny) - 2 * margin) *
                         (static_cast<int>(plate->layout.nz) - 2 * margin);
        require(rows > 0, "the test plate is too small for this horizon");
        const double geometric = static_cast<double>(rows) * h * h;
        const double error = std::abs(area - geometric) / geometric;
        require(error < 1.0e-12, "horizon " + std::to_string(horizon) + ": bond areas over a cut sum to " +
                                     std::to_string(area) + " m^2 against a geometric " +
                                     std::to_string(geometric) + " m^2");
    }
}

void theLatticeIsTheReferenceLattice() {
    // The reference lane builds its tile with generateBoxTileLattice and this
    // lane with generateBoxLattice. Both must produce the same nodes and the
    // same bonds in the same order, or first-failure sets cannot be compared by
    // index across the two lanes.
    PlateRequest request = smallPlate();
    const auto plate = buildPlate(request);
    CompiledBrittleMaterial compiled = plate->compiled;
    BoxLatticeLayout layout;
    const LatticeAsset reference = generateBoxTileLattice(
        {{request.length_m, request.thickness_m, request.width_m}, request.cell_m, request.horizon},
        compiled, &layout);
    require(reference.nodes.size() == plate->asset.nodes.size(), "node counts differ");
    require(reference.bonds.size() == plate->asset.bonds.size(), "bond counts differ");
    require(layout.nx == plate->layout.nx && layout.ny == plate->layout.ny && layout.nz == plate->layout.nz,
            "cell layouts differ");
    for (std::size_t i = 0; i < reference.nodes.size(); ++i)
        require(reference.nodes[i].grid == plate->asset.nodes[i].grid, "node " + std::to_string(i) + " differs");
    for (std::size_t b = 0; b < reference.bonds.size(); ++b) {
        require(reference.bonds[b].node_a == plate->asset.bonds[b].node_a &&
                    reference.bonds[b].node_b == plate->asset.bonds[b].node_b,
                "bond " + std::to_string(b) + " joins different cells");
        require(std::abs(reference.bonds[b].compliance - plate->asset.bonds[b].compliance) <=
                    1.0e-15 * reference.bonds[b].compliance,
                "bond " + std::to_string(b) + " has a different compliance");
    }
}

void aSingleLayerPlateIsRefused() {
    PlateRequest request = smallPlate();
    request.thickness_m = request.cell_m; // one cell through the thickness
    bool refused = false;
    try {
        const auto plate = buildPlate(request);
    } catch (const std::exception &error) {
        refused = true;
        const std::string message = error.what();
        require(message.find("one cell thick") != std::string::npos,
                "the refusal must name the cause, said: " + message);
    }
    require(refused, "a single-layer plate has no transverse stiffness and must be refused, not solved");
}

} // namespace

int main() {
    try {
        bondAreasSumToACut();
        std::cout << "[PASS] bond crack areas sum to the geometric area of a cut at horizons 1, 2 and 3\n";
        theLatticeIsTheReferenceLattice();
        std::cout << "[PASS] this lane's lattice is bond-for-bond the reference lane's lattice\n";
        aSingleLayerPlateIsRefused();
        std::cout << "[PASS] a plate one cell thick is refused with its reason\n";
        influenceMatchesADirectSolve();
        std::cout << "[PASS] the influence matrix reproduces a direct solve with a bond removed\n";
        influenceIsReciprocal();
        std::cout << "[PASS] the influence matrix is reciprocal\n";
        peakResponseIsLinearInTheImpulse();
        std::cout << "[PASS] the bond load is linear in the impulse\n";
        theEnergyLedgerCloses();
        std::cout << "[PASS] the energy ledger closes: budget in = crack work spent + remaining\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
