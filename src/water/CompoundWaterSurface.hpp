#pragma once

#include "water/WaterCoupling.hpp"

namespace banjo::water {
// Closed union of convex boxes and volume-matched faceted cylinders. Covered
// faces are subtracted, including overlaps and deterministic coplanar ownership.
std::vector<WaterCoupling::Patch> compoundWaterSurface(
    const std::vector<CompoundWaterPart> &parts, double patch_m);
// Full geometry key: no pointer, rounded dimensions, material or pose aliases.
std::string compoundWaterKey(const std::vector<CompoundWaterPart> &parts);
// Exact primitive ray intervals; gaps between parts remain separate.
std::vector<std::pair<double, double>> compoundVerticalSpans(
    const BodyInWater &body, double x, double z);
}
