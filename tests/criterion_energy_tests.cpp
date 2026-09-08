// The energy-scaled bond failure law, against the lattice it is derived for.
//
// The derivation (docs/criterion-energy-scaled-checkpoint.md, section 2) rests
// on three facts about this lattice, and every one of them is measured here on
// a lattice the production generator built, not restated algebraically:
//
//   1. compileElasticLatticeReference gives every bond the compliance
//      m |o|^2 / (E h), so a bond at stretch s stores E h^3 s^2 / (2 m)
//      whatever its grid offset o. The stored energy is length-independent.
//   2. That per-bond energy makes the lattice a cubic elastic solid with
//      C11 = E sum(n_x^4) / m and C12 = C44 = E sum(n_x^2 n_y^2) / m over the
//      half offsets of the horizon.
//   3. N_100 = sum |o_x| bonds cross each h^2 of a {100} lattice plane, so
//      removing them all at the stretch s_c = sqrt(2 m Gc / (N_100 E h))
//      costs exactly Gc per unit area, at every cell size and horizon.
//
// Tests 1-3 below check those. Test 4 checks the scaling that fact 3 implies
// (s_c ~ h^-1/2, crack energy flat in h). Test 5 is the regression the brief
// requires: selecting the strain-threshold law reproduces withStrengthDerived-
// Failure bit for bit, down to the bytes of every generated BondRest.
// Test 6 checks the strength bound: iron's Irwin length is 338 mm, far above
// any cell size here, so its removal stretch stays the strength one.

#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"
#include "matter/Lattice.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <map>
#include <numbers>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
using namespace banjo;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}

void requireClose(double got, double want, double relative_tolerance, const std::string &what) {
    const double scale = std::max(std::abs(want), 1.0e-300);
    const double error = std::abs(got - want) / scale;
    if (!(error <= relative_tolerance)) {
        std::ostringstream out;
        out << what << ": got " << std::setprecision(17) << got << ", want " << want
            << " (relative error " << error << " > " << relative_tolerance << ")";
        throw std::runtime_error(out.str());
    }
}

constexpr double kCells[] = {0.02, 0.01, 0.005};
constexpr unsigned kHorizons[] = {2, 3};
constexpr MaterialPreset kPresets[] = {
    MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron,
    MaterialPreset::Ceramic, MaterialPreset::Ice, MaterialPreset::Concrete,
    MaterialPreset::Aluminum, MaterialPreset::Rubber,
};

// Energy stored by one bond of the built lattice at stretch s, from the
// compliance the generator actually wrote into it.
[[nodiscard]] double storedEnergy(const BondRest &bond, double stretch) {
    const double extension = stretch * bond.rest_length_m;
    return 0.5 * extension * extension / bond.compliance;
}

// ---------------------------------------------------------------------------
// 1. Every bond stores the same energy at the same stretch.
// ---------------------------------------------------------------------------
void perBondEnergyIsLengthIndependent() {
    for (const double cell : kCells) {
        for (const unsigned horizon : kHorizons) {
            const MaterialDefinition material = makeReferenceMaterial(MaterialPreset::Glass, 3);
            const CompiledBrittleMaterial compiled =
                compileElasticLatticeReference(material, cell, horizon);
            const LatticeAsset asset = generateBoxTileLattice(
                {{cell * 8, cell * 8, cell * 8}, cell, horizon}, compiled);
            const double expected = material.young_modulus_pa * cell * cell * cell /
                                    (2.0 * static_cast<double>(horizon));  // at s = 1
            std::map<long long, std::size_t> offsets_seen;
            for (const BondRest &bond : asset.bonds) {
                const double s = 3.7e-4;  // any stretch; the ratio is what matters
                requireClose(storedEnergy(bond, s) / (s * s), expected, 1.0e-13,
                             "per-bond energy at cell " + std::to_string(cell));
                const long long key = std::llround(bond.rest_length_m / cell * 1000.0);
                ++offsets_seen[key];
            }
            require(offsets_seen.size() >= 3,
                    "the lattice must carry bonds of several lengths for this to mean anything");
            const LatticeHorizonGeometry g = latticeHorizonGeometry(horizon);
            std::cout << "  cell " << cell * 1000 << " mm, horizon " << horizon << ": "
                      << asset.bonds.size() << " bonds, " << offsets_seen.size()
                      << " distinct rest lengths, all storing E h^3 s^2 / 2m = " << expected
                      << " J at s = 1; N_100 = " << g.crossings_100 << ", "
                      << g.bonds_per_node << " half offsets\n";
        }
    }
}

// ---------------------------------------------------------------------------
// 2. The lattice's cubic elastic constants are the ones the derivation claims.
//    An affine strain is applied to a built lattice and the energy density of
//    the nodes that carry their full complement of bonds is measured.
// ---------------------------------------------------------------------------
void latticeElasticConstantsMatchTheDerivation() {
    const double cell = 0.01;
    for (const unsigned horizon : kHorizons) {
        const MaterialDefinition material = makeReferenceMaterial(MaterialPreset::Glass, 3);
        const CompiledBrittleMaterial compiled =
            compileElasticLatticeReference(material, cell, horizon);
        const unsigned n = 6 * horizon + 2;  // wide enough for a full-complement interior
        const LatticeAsset asset = generateBoxTileLattice(
            {{cell * n, cell * n, cell * n}, cell, horizon}, compiled);
        const LatticeHorizonGeometry g = latticeHorizonGeometry(horizon);
        const std::size_t full_degree = 2U * g.bonds_per_node;
        const double E = material.young_modulus_pa;
        const double m = static_cast<double>(horizon);

        // Energy density under an affine displacement gradient, summed over the
        // nodes with every bond present; half of each incident bond's energy
        // belongs to the node, and one node occupies h^3.
        const auto densityUnder = [&](const Mat3 &gradient) {
            double energy = 0.0;
            std::size_t counted = 0;
            for (std::size_t i = 0; i < asset.nodes.size(); ++i) {
                const std::uint32_t begin = asset.adjacency_offsets[i];
                const std::uint32_t end = asset.adjacency_offsets[i + 1U];
                if (static_cast<std::size_t>(end - begin) != full_degree) continue;
                ++counted;
                for (std::uint32_t k = begin; k < end; ++k) {
                    const BondRest &bond = asset.bonds[asset.adjacent_bond_indices[k]];
                    const Vec3 rest = asset.nodes[bond.node_b].local_position_m -
                                      asset.nodes[bond.node_a].local_position_m;
                    const Vec3 moved = rest + gradient * rest;
                    const double extension = length(moved) - bond.rest_length_m;
                    energy += 0.5 * 0.5 * extension * extension / bond.compliance;
                }
            }
            require(counted > 0, "no full-complement interior node; grow the block");
            return energy / (static_cast<double>(counted) * cell * cell * cell);
        };

        const double e = 1.0e-6;
        Mat3 uniaxial{};
        uniaxial.m[0][0] = e;
        const double c11 = 2.0 * densityUnder(uniaxial) / (e * e);
        Mat3 shear{};  // engineering shear gamma = 2 e
        shear.m[0][1] = e;
        shear.m[1][0] = e;
        const double c44 = 2.0 * densityUnder(shear) / (4.0 * e * e);

        requireClose(c11, E * g.sum_nx4 / m, 2.0e-5, "C11 of the lattice");
        requireClose(c44, E * g.sum_nx2ny2 / m, 2.0e-5, "C44 of the lattice");
        std::cout << "  horizon " << horizon << ": measured C11 = " << c11 / 1e9 << " GPa (derived "
                  << E * g.sum_nx4 / (m * 1e9) << "), C44 = " << c44 / 1e9 << " GPa (derived "
                  << E * g.sum_nx2ny2 / (m * 1e9) << "); input E = " << E / 1e9 << " GPa\n";
    }
}

// ---------------------------------------------------------------------------
// 3a. One bond pair at the derived stretch releases its share of Gc.
//     A lone pair is the whole of a crack face of area h^2 / N_100.
// ---------------------------------------------------------------------------
void oneBondPairReproducesGc() {
    for (const MaterialPreset preset : {MaterialPreset::Glass, MaterialPreset::Oak,
                                        MaterialPreset::Ceramic, MaterialPreset::Ice}) {
        for (const double cell : kCells) {
            for (const unsigned horizon : kHorizons) {
                MaterialDefinition material = makeReferenceMaterial(preset, 3);
                material.strength_variation = 0.0;
                material.failure_law = BondFailureLaw::EnergyScaled;
                const CompiledBrittleMaterial compiled = withFailureLaw(
                    compileElasticLatticeReference(material, cell, horizon), material, cell, horizon);
                require(compiled.failure_law == BondFailureLaw::EnergyScaled, "law selected");
                require(!compiled.strength_bound_active,
                        "these presets are all below their Irwin length at these cells");
                const LatticeHorizonGeometry g = latticeHorizonGeometry(horizon);

                // A single pair: two nodes one cell apart, bonded by the same rule.
                const LatticeAsset pair = generateBoxTileLattice(
                    {{cell * 2, cell, cell}, cell, horizon}, compiled);
                require(pair.bonds.size() == 1, "a two-node block has exactly one bond");
                const double released = storedEnergy(pair.bonds.front(), compiled.damage_end_stretch);
                const double share = cell * cell / g.crossings_100;  // area this pair answers for
                requireClose(released / share, material.fracture_energy_j_m2, 1.0e-12,
                             std::string("single pair Gc, ") + std::string(materialPresetName(preset)));
            }
        }
    }
    std::cout << "  4 presets x 3 cell sizes x 2 horizons: a lone bond pair broken at the "
                 "derived stretch releases Gc x h^2 / N_100, to 1e-12 relative\n";
}

// ---------------------------------------------------------------------------
// 3b. A whole {100} crack face reproduces Gc, at every resolution.
//     Every bond crossing the mid-plane of a built block is removed at its own
//     recorded threshold and the energy is divided by the area it opened. Only
//     node columns with the full crossing count are charged, so the free
//     surfaces of the finite block do not enter.
// ---------------------------------------------------------------------------
void aUnitCrackFaceReproducesGc() {
    for (const MaterialPreset preset : {MaterialPreset::Glass, MaterialPreset::Oak}) {
        for (const unsigned horizon : kHorizons) {
            std::vector<double> per_area;
            for (const double cell : kCells) {
                MaterialDefinition material = makeReferenceMaterial(preset, 3);
                material.strength_variation = 0.0;
                material.failure_law = BondFailureLaw::EnergyScaled;
                const CompiledBrittleMaterial compiled = withFailureLaw(
                    compileElasticLatticeReference(material, cell, horizon), material, cell, horizon);
                const LatticeHorizonGeometry g = latticeHorizonGeometry(horizon);

                const unsigned n = 6 * horizon + 2;
                BoxLatticeLayout layout{};
                const LatticeAsset asset = generateBoxTileLattice(
                    {{cell * n, cell * n, cell * n}, cell, horizon}, compiled, &layout);
                // The crack plane sits between x layers p-1 and p.
                const int p = static_cast<int>(layout.nx) / 2;
                std::map<std::pair<int, int>, std::pair<double, double>> column;  // (y,z) -> (energy, count)
                for (const BondRest &bond : asset.bonds) {
                    const GridCoord a = asset.nodes[bond.node_a].grid;
                    const GridCoord b = asset.nodes[bond.node_b].grid;
                    const bool crosses = (a.x < p) != (b.x < p);
                    if (!crosses) continue;
                    // Charge the crossing to the column of the lower-x end, which is
                    // how the derivation counts: |o_x| crossings per column per offset.
                    const GridCoord lower = a.x < b.x ? a : b;
                    auto &entry = column[{lower.y, lower.z}];
                    entry.first += storedEnergy(bond, bond.damage_end_stretch);
                    entry.second += 1.0;
                }
                double energy = 0.0;
                std::size_t complete = 0;
                for (const auto &[key, entry] : column) {
                    if (std::llround(entry.second) != std::llround(g.crossings_100)) continue;
                    energy += entry.first;
                    ++complete;
                }
                require(complete > 0, "no complete column across the crack plane");
                const double area = static_cast<double>(complete) * cell * cell;
                per_area.push_back(energy / area);
                requireClose(energy / area, material.fracture_energy_j_m2, 1.0e-12,
                             std::string("crack face Gc, ") + std::string(materialPresetName(preset)) +
                                 " at cell " + std::to_string(cell));
            }
            std::cout << "  " << std::string(materialPresetName(preset)) << ", horizon " << horizon
                      << ": crack-face energy at 20/10/5 mm = " << per_area[0] << " / "
                      << per_area[1] << " / " << per_area[2] << " J/m^2 (Gc = "
                      << makeReferenceMaterial(preset, 3).fracture_energy_j_m2 << ")\n";
        }
    }
}

// ---------------------------------------------------------------------------
// 4. The scaling the derivation implies: s_c ~ h^-1/2 exactly, and the crack
//    energy is flat in h where the old law's grows in proportion to h.
// ---------------------------------------------------------------------------
void theStretchScalesAsTheInverseRootOfTheCell() {
    const MaterialDefinition glass = makeReferenceMaterial(MaterialPreset::Glass, 3);
    for (const unsigned horizon : kHorizons) {
        const LatticeHorizonGeometry g = latticeHorizonGeometry(horizon);
        const auto crackEnergy = [&](double stretch, double cell) {
            return g.crossings_100 * glass.young_modulus_pa * cell * stretch * stretch /
                   (2.0 * static_cast<double>(horizon));
        };
        double previous_stretch = 0.0;
        for (const double cell : kCells) {
            const double s = energyScaledCriticalStretch(
                glass.fracture_energy_j_m2, glass.young_modulus_pa, cell, horizon);
            requireClose(crackEnergy(s, cell), glass.fracture_energy_j_m2, 1.0e-13,
                         "energy-scaled crack energy is flat in the cell size");
            if (previous_stretch > 0.0)
                requireClose(s / previous_stretch, std::sqrt(2.0), 1.0e-13,
                             "halving the cell raises the stretch by sqrt 2");
            previous_stretch = s;
        }
        // The old law, for contrast: its crack energy is proportional to h.
        const double s_strength = glass.calibration.break_strain_multiplier *
                                  glass.tensile_strength_pa / glass.young_modulus_pa;
        const double old_20 = crackEnergy(s_strength, 0.02);
        const double old_05 = crackEnergy(s_strength, 0.005);
        requireClose(old_20 / old_05, 4.0, 1.0e-13, "the old law's crack energy scales with h");
        std::cout << "  horizon " << horizon << ": energy-scaled crack energy 8 J/m^2 at every "
                     "cell; strain-threshold crack energy " << old_20 << " J/m^2 at 20 mm and "
                  << old_05 << " at 5 mm (glass Gc = 8)\n";
    }
}

// ---------------------------------------------------------------------------
// 5. Selecting the strain-threshold law changes nothing, bit for bit.
// ---------------------------------------------------------------------------
void theOldLawIsUnchangedBitForBit() {
    std::size_t compared_materials = 0, compared_bonds = 0;
    for (const MaterialPreset preset : kPresets) {
        for (const double cell : kCells) {
            for (const unsigned horizon : kHorizons) {
                const MaterialDefinition material = makeReferenceMaterial(preset, 971);
                require(material.failure_law == BondFailureLaw::StrainThreshold,
                        "the strain-threshold law stays the default");
                const CompiledBrittleMaterial before = withStrengthDerivedFailure(
                    compileElasticLatticeReference(material, cell, horizon), material);
                const CompiledBrittleMaterial after = withFailureLaw(
                    compileElasticLatticeReference(material, cell, horizon), material, cell, horizon);
                const double a[7] = {before.damage_start_stretch, before.damage_end_stretch,
                                     before.compression_damage_start_strain,
                                     before.compression_damage_end_strain,
                                     before.shear_damage_start_strain,
                                     before.shear_damage_end_strain, before.bond_compliance};
                const double b[7] = {after.damage_start_stretch, after.damage_end_stretch,
                                     after.compression_damage_start_strain,
                                     after.compression_damage_end_strain,
                                     after.shear_damage_start_strain,
                                     after.shear_damage_end_strain, after.bond_compliance};
                require(std::memcmp(a, b, sizeof a) == 0,
                        std::string("strain-threshold thresholds differ for ") +
                            std::string(materialPresetName(preset)));
                require(after.energy_scaled_stretch == 0.0 && !after.strength_bound_active,
                        "the strain-threshold law reports no energy-scaled stretch");
                ++compared_materials;

                // And the bonds the generator writes from them, byte for byte.
                const LatticeAsset old_asset = generateBoxTileLattice(
                    {{cell * 5, cell * 4, cell * 3}, cell, horizon}, before);
                const LatticeAsset new_asset = generateBoxTileLattice(
                    {{cell * 5, cell * 4, cell * 3}, cell, horizon}, after);
                require(old_asset.bonds.size() == new_asset.bonds.size(), "same bond count");
                require(std::memcmp(old_asset.bonds.data(), new_asset.bonds.data(),
                                    old_asset.bonds.size() * sizeof(BondRest)) == 0,
                        "the generated bonds differ under the strain-threshold law");
                compared_bonds += old_asset.bonds.size();

                // compileBrittleMaterial's default route too, for the presets it accepts.
                if (material.model == MaterialModel::BrittleBond) {
                    const CompiledBrittleMaterial full_before =
                        compileBrittleMaterial(material, cell, horizon);
                    MaterialDefinition explicit_old = material;
                    explicit_old.failure_law = BondFailureLaw::StrainThreshold;
                    const CompiledBrittleMaterial full_after =
                        compileBrittleMaterial(explicit_old, cell, horizon);
                    require(std::memcmp(&full_before, &full_after, sizeof full_before) == 0,
                            "compileBrittleMaterial's default is the strain-threshold law");
                }
            }
        }
    }
    std::cout << "  " << compared_materials << " preset x cell x horizon combinations and "
              << compared_bonds << " generated bonds: identical bytes\n";
}

// ---------------------------------------------------------------------------
// 6. The strength bound. Gc / (E) against the cell size decides which of the
//    two thresholds is the smaller; iron's Irwin length is 338 mm so its
//    strength always bites, glass's is 0.28 mm so its energy always does.
// ---------------------------------------------------------------------------
void theStrengthBoundHoldsWhereItShould() {
    for (const MaterialPreset preset : {MaterialPreset::Iron, MaterialPreset::Glass,
                                        MaterialPreset::Oak}) {
        MaterialDefinition material = makeReferenceMaterial(preset, 3);
        material.failure_law = BondFailureLaw::EnergyScaled;
        const double irwin = material.young_modulus_pa * material.fracture_energy_j_m2 /
                             (material.tensile_strength_pa * material.tensile_strength_pa);
        for (const double cell : kCells) {
            const CompiledBrittleMaterial energy = withFailureLaw(
                compileElasticLatticeReference(material, cell, 2), material, cell, 2);
            const CompiledBrittleMaterial strength = withStrengthDerivedFailure(
                compileElasticLatticeReference(material, cell, 2), material);
            const bool bound = energy.strength_bound_active;
            require(bound == (strength.damage_end_stretch < energy.energy_scaled_stretch),
                    "the reported bound flag must say which threshold is smaller");
            requireClose(energy.damage_end_stretch,
                         std::min(energy.energy_scaled_stretch, strength.damage_end_stretch),
                         1.0e-13, "the removal stretch is the smaller of the two");
            std::cout << "  " << std::string(materialPresetName(preset)) << " (Irwin length " << irwin * 1000.0
                      << " mm) at " << cell * 1000 << " mm: s_energy = " << energy.energy_scaled_stretch
                      << ", s_strength = " << strength.damage_end_stretch << " -> "
                      << (bound ? "strength" : "energy") << " governs\n";
        }
        if (preset == MaterialPreset::Iron)
            require(withFailureLaw(compileElasticLatticeReference(material, 0.02, 2), material, 0.02, 2)
                        .strength_bound_active,
                    "iron at 20 mm cells is strength-bounded");
        if (preset == MaterialPreset::Glass)
            require(!withFailureLaw(compileElasticLatticeReference(material, 0.02, 2), material, 0.02, 2)
                         .strength_bound_active,
                    "glass at 20 mm cells is energy-bounded");
    }
}

// ---------------------------------------------------------------------------
// 7. An independent check on the constant, not just the scaling.
//    The derivation is never told about linear elastic fracture mechanics, so
//    LEFM can be asked whether the answer is sane: a crack of length a in a
//    body of modulus E' propagates at the stress sqrt(E' Gc / (pi a)). Take a
//    to be one cell - which is what a lattice that resolves a crack in cells
//    means - and compare with the stress the criterion actually fails at,
//    E_eff s_c. Both scale as h^-1/2, so their ratio is a pure number:
//        E_eff s_c / sqrt(E_eff Gc / (pi h)) = sqrt((E_eff / E) 2 pi m / N_100)
//    and it must come out of order one for the derivation's constant to be
//    right. It does: 1.317 at horizon 2, 0.925 at horizon 3, for every
//    material and every cell size.
// ---------------------------------------------------------------------------
void theImpliedStrengthAgreesWithLefmForACellSizedFlaw() {
    for (const unsigned horizon : kHorizons) {
        const LatticeHorizonGeometry g = latticeHorizonGeometry(horizon);
        const double m = static_cast<double>(horizon);
        double first_ratio = 0.0;
        for (const MaterialPreset preset : {MaterialPreset::Glass, MaterialPreset::Oak,
                                            MaterialPreset::Ceramic, MaterialPreset::Ice,
                                            MaterialPreset::Concrete}) {
            const MaterialDefinition material = makeReferenceMaterial(preset, 3);
            const double c11 = material.young_modulus_pa * g.sum_nx4 / m;
            const double c12 = material.young_modulus_pa * g.sum_nx2ny2 / m;
            const double young_effective = (c11 - c12) * (c11 + 2.0 * c12) / (c11 + c12);
            for (const double cell : kCells) {
                const double s_c = energyScaledCriticalStretch(
                    material.fracture_energy_j_m2, material.young_modulus_pa, cell, horizon);
                const double criterion_stress = young_effective * s_c;
                const double lefm_stress = std::sqrt(
                    young_effective * material.fracture_energy_j_m2 /
                    (std::numbers::pi * cell));
                const double ratio = criterion_stress / lefm_stress;
                if (first_ratio == 0.0) first_ratio = ratio;
                requireClose(ratio, first_ratio, 1.0e-12,
                             "the ratio must not depend on the material or the cell size");
                requireClose(ratio,
                             std::sqrt((young_effective / material.young_modulus_pa) *
                                       2.0 * std::numbers::pi * m / g.crossings_100),
                             1.0e-12, "the closed form of the ratio");
                require(ratio > 0.5 && ratio < 2.0,
                        "the criterion's failure stress must be within a factor two of LEFM's "
                        "for a cell-sized flaw");
            }
        }
        std::cout << "  horizon " << horizon << ": the criterion fails at " << first_ratio
                  << " x the LEFM stress for a crack one cell long, for every material and "
                     "every cell size\n";
    }
}

void namesRoundTrip() {
    require(parseBondFailureLaw("strain-threshold") == BondFailureLaw::StrainThreshold, "parse old");
    require(parseBondFailureLaw("energy-scaled") == BondFailureLaw::EnergyScaled, "parse new");
    require(bondFailureLawName(BondFailureLaw::EnergyScaled) == "energy-scaled", "name new");
    bool threw = false;
    try { parseBondFailureLaw("bazant"); } catch (const std::exception &) { threw = true; }
    require(threw, "an unknown law name is refused, not defaulted");
}

} // namespace

int main() {
    try {
        perBondEnergyIsLengthIndependent();
        std::cout << "[PASS] every bond stores E h^3 s^2 / 2m whatever its grid offset\n";
        latticeElasticConstantsMatchTheDerivation();
        std::cout << "[PASS] the lattice's measured C11 and C44 are the derivation's\n";
        oneBondPairReproducesGc();
        std::cout << "[PASS] one bond pair at the derived stretch reproduces Gc\n";
        aUnitCrackFaceReproducesGc();
        std::cout << "[PASS] a {100} crack face reproduces Gc at 20, 10 and 5 mm cells\n";
        theStretchScalesAsTheInverseRootOfTheCell();
        std::cout << "[PASS] the removal stretch scales as h^-1/2 and the crack energy is flat\n";
        theOldLawIsUnchangedBitForBit();
        std::cout << "[PASS] the strain-threshold law is unchanged bit for bit\n";
        theStrengthBoundHoldsWhereItShould();
        std::cout << "[PASS] the strength bound governs exactly where the Irwin length says\n";
        theImpliedStrengthAgreesWithLefmForACellSizedFlaw();
        std::cout << "[PASS] the implied failure stress agrees with LEFM for a cell-sized flaw\n";
        namesRoundTrip();
        std::cout << "[PASS] failure law names round trip and unknown names are refused\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
