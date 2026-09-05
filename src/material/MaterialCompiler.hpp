#pragma once

#include "material/Material.hpp"

namespace banjo {

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
