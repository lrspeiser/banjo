#pragma once

#include "material/Material.hpp"

namespace banjo {

// Explicit central-bond elastic approximation for comparative solver probes.
// Uses catalog density/modulus without changing the preset's model. The legacy
// lattice parameter container is reused with every damage threshold disabled;
// this does not implement wood anisotropy, metal plasticity or fracture.
[[nodiscard]] CompiledBrittleMaterial compileElasticLatticeReference(
    const MaterialDefinition &material, double voxel_size_m, unsigned neighbor_horizon_cells);

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
