#pragma once
#include "thermal/ThermalFieldApi.hpp"
#include <cstdint>
// Reorder retained field records by persistent matter ID while mechanical
// owners change. Every input matter ID appears exactly once in the destination.
// No averaging, field reset, heat/work or elapsed time is introduced. Outputs
// are atomic on invalid IDs, states or owner declarations.
// Receipt width 7: thermal energy, chemical energy, species mass before/after
// (interleaved pairs) and count whose owner ID changed.
extern "C" BANJO_FIELD_API int banjo_thermal_matter_rebind(
 const double* source_cells,const std::uint64_t* source_matter,
 const std::uint64_t* source_owner,const std::uint64_t* target_matter,
 const std::uint64_t* target_owner,int count,double* target_cells,double* receipt);
