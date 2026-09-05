#pragma once
#include "world/SparseThermalWorld.hpp"

namespace banjo {
// Comparative numerical fixtures, NOT calibrated fire/material predictions.
// All coupons: 8x8x1 occupied 1 cm voxels, initially 293.15 K, center 2x2
// heated to 650 K with the resulting per-material external work recorded.
// Each coupon is explicitly insulated from every other coupon and cold matter.
std::unique_ptr<SparseThermalWorld> makeWorldLab(unsigned chunks=4096,unsigned regions=4);
const char *worldLabMaterialName(unsigned material);
}
