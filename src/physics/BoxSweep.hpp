#pragma once
#include "core/Math.hpp"
namespace banjo {
// Start-of-interval box bounds and a supplied upper bound on any vertex's
// travelled distance. Broad-phase eligibility, not a collision response law.
struct BoxSweep {
    Vec3 center_m, half_extent_m;
    double vertex_travel_m{}, minimum_feature_m{};
};
BoxSweep boundBoxSweep(Vec3 size_m, Vec3 center_m, Quat orientation,
                      double vertex_travel_m);
// Zero when the swept bounds cannot meet. Otherwise return combined vertex
// travel divided by 5% of the smaller box feature. Speculative margin is in m.
double boxSweepRatio(const BoxSweep &a,const BoxSweep &b,double margin_m);
}
