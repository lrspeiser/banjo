#pragma once

#include "material/Material.hpp"

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
