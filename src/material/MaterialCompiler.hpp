#pragma once

#include "material/Material.hpp"

#include <cstddef>
#include <string_view>

namespace banjo {

// Explicit central-bond elastic approximation for comparative solver probes.
// Uses catalog density/modulus without changing the preset's model. The legacy
// lattice parameter container is reused with every damage threshold disabled;
// this does not implement wood anisotropy, metal plasticity or fracture.
[[nodiscard]] CompiledBrittleMaterial compileElasticLatticeReference(
    const MaterialDefinition &material, double voxel_size_m, unsigned neighbor_horizon_cells);

// Add the strength-derived failure surface to an already-compiled elastic
// reference so that reference can break. The thresholds come from the declared
// tensile/compressive/shear strengths through the same conversion and the same
// calibration multipliers compileBrittleMaterial uses, so a preset compiled
// either way fails at the same strain.
//
// This does not declare the material brittle. It is the isotropic central-bond
// strength surface only: no yield, plasticity, grain direction, anisotropy or
// rate dependence, and no Gc calibration. Damping and per-bond strength
// variation are left as the elastic reference set them, so a comparison across
// materials is not confounded by a randomised strength field.
// compileBrittleMaterial remains the only path for a catalog BrittleBond preset.
[[nodiscard]] CompiledBrittleMaterial withStrengthDerivedFailure(
    CompiledBrittleMaterial compiled, const MaterialDefinition &material);

// Add axial plastic flow to an already-compiled lattice material, from the
// declared yield strength and hardening ratio, the way the network lane derives
// its yield force (material/NetworkMaterial.cpp directionalNetworkParameters:
// yield_force_n = yield_strength_pa * area, so the yield extension is
// yield_force_n / (E A / L) = yield_strength_pa * L / E).  Here the quotient is
// stored instead of the force, because the lattice's bond stiffness is not
// E A / L; see CompiledBrittleMaterial::yield_stretch.
//
// A material that declares no yield strength (or a non-positive one) is
// returned unchanged with yield_stretch zero, which disables the plastic law
// entirely. This adds no failure law, changes no threshold and touches neither
// of the two failure laws above.
[[nodiscard]] CompiledBrittleMaterial withPlasticFlow(
    CompiledBrittleMaterial compiled, const MaterialDefinition &material);

// The bond geometry of a cubic lattice with a grid horizon of m cells, as
// matter/Lattice.cpp builds it: every integer offset o with 1 <= |o| <= m,
// each unordered pair counted once ("half offsets", one per bond of an
// interior node). These sums are what the energy-scaled failure law and the
// lattice's elastic constants need; they depend on the horizon only.
struct LatticeHorizonGeometry {
    unsigned horizon{};
    std::size_t bonds_per_node{};
    // Sum over half offsets of |o . n| for the plane normal n: the number of
    // bonds crossing a unit area of that lattice plane is this over h^2.
    double crossings_100{};
    double crossings_110{};
    double crossings_111{};
    // Sum over half offsets of n_x^4 and n_x^2 n_y^2 (unit bond directions):
    // with the per-bond energy E h^3 s^2 / (2 m) of this lattice's compliance
    // rule, the lattice is a cubic elastic material with
    // C11 = E * sum_nx4 / m and C12 = C44 = E * sum_nx2ny2 / m.
    double sum_nx4{};
    double sum_nx2ny2{};
};

[[nodiscard]] LatticeHorizonGeometry latticeHorizonGeometry(unsigned neighbor_horizon_cells);

// The removal stretch of the energy-scaled law before any strength bound:
//   s_c = sqrt(2 m Gc / (N_100 E h)),
// where N_100 = crossings_100 of the horizon. Derivation: with the compliance
// rule of compileElasticLatticeReference (stiffness E h / (m |o|^2) for a bond
// of grid offset o) every bond stores E h^3 s^2 / (2 m) at stretch s whatever
// its length, N_100 / h^2 bonds cross a unit area of a {100} lattice plane, so
// removing each at s_c releases N_100 E h s_c^2 / (2 m) per unit area; setting
// that equal to Gc gives s_c. See docs/criterion-energy-scaled-checkpoint.md.
[[nodiscard]] double energyScaledCriticalStretch(
    double fracture_energy_j_m2,
    double young_modulus_pa,
    double voxel_size_m,
    unsigned neighbor_horizon_cells);

// Set the tensile damage ramp of an already-compiled elastic reference from
// the energy-scaled removal stretch: damage ends (the bond is removed) at
// min(s_c, break_strain_multiplier * tensile_strength / E) and starts at the
// same fraction of it that the strength-derived law uses
// (damage_strain_multiplier / break_strain_multiplier). The compressive and
// shear ramps are the strength-derived ones of withStrengthDerivedFailure,
// unchanged: Gc is a mode-I crack energy and the lattice's crushing and shear
// bounds stay strength bounds. The strain-threshold law is untouched by this
// function's existence; select it and the thresholds are bit for bit what
// withStrengthDerivedFailure produced before the energy-scaled law existed.
[[nodiscard]] CompiledBrittleMaterial withEnergyScaledFailure(
    CompiledBrittleMaterial compiled,
    const MaterialDefinition &material,
    double voxel_size_m,
    unsigned neighbor_horizon_cells);

// Apply the failure law the material definition selects.
[[nodiscard]] CompiledBrittleMaterial withFailureLaw(
    CompiledBrittleMaterial compiled,
    const MaterialDefinition &material,
    double voxel_size_m,
    unsigned neighbor_horizon_cells);

[[nodiscard]] std::string_view bondFailureLawName(BondFailureLaw law);
// Accepts "strain-threshold" and "energy-scaled"; throws otherwise.
[[nodiscard]] BondFailureLaw parseBondFailureLaw(std::string_view name);

[[nodiscard]] CompiledBrittleMaterial compileBrittleMaterial(
    const MaterialDefinition &material,
    double voxel_size_m,
    unsigned neighbor_horizon_cells);

[[nodiscard]] double coefficientOfRestitutionFromDamping(double damping_ratio);
[[nodiscard]] double dampingRatioFromCoefficientOfRestitution(double restitution);
[[nodiscard]] CompiledContactMaterial compileContactMaterial(
    const MaterialDefinition &material);
[[nodiscard]] CombinedContactMaterial combineContactMaterials(
    const CompiledContactMaterial &first,
    const CompiledContactMaterial &second);

} // namespace banjo
