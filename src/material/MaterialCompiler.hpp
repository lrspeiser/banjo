#pragma once

#include "material/Material.hpp"

namespace banjo {

[[nodiscard]] CompiledBrittleMaterial compileBrittleMaterial(
    const MaterialDefinition &material,
    double voxel_size_m,
    unsigned neighbor_horizon_cells);

} // namespace banjo
