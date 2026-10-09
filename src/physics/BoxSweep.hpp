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
// Envelope for a supplied straight COM segment, with arbitrary rotation.
// Anchored boxes use their fixed orientation instead. This does not prove an
// arbitrary curved path lies inside: the host must supply/verify that contract.
struct BoxCenterPath {Vec3 lo_m,hi_m;};
BoxCenterPath boundBoxCenterPath(Vec3 size_m,Vec3 start_m,Vec3 end_m,
                                Quat anchored_orientation,bool anchored,
                                double additional_center_travel_m=0);
bool boxCenterPathsOverlap(const BoxCenterPath &a,const BoxCenterPath &b,double margin_m);
}
