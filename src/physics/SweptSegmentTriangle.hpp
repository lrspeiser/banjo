#pragma once

#include "physics/SegmentTriangleContact.hpp"

#include <array>

namespace banjo {

struct SweptSegmentTriangleSettings {
    double contact_radius_m{};
    double distance_tolerance_m{1.e-9};
    unsigned maximum_evaluations{64};
};

struct SweptSegmentTriangleResult {
    bool hit{};
    bool resolved{};
    bool stagnated{};
    double time_s{};
    SegmentTriangleContactResult geometry{};
    unsigned evaluations{};
};

// Segment endpoints and triangle vertices vary linearly over [0, duration_s].
// A resolved miss is reported at duration_s. Invalid geometry, work exhaustion,
// and numerical stagnation are unresolved. A hit is only geometric proximity;
// this query never applies contact response, cutting, damage, or separation.
[[nodiscard]] SweptSegmentTriangleResult sweepSegmentTriangle(
    const std::array<Vec3, 2> &segment_m,
    const std::array<Vec3, 2> &segment_velocity_m_s,
    const std::array<Vec3, 3> &triangle_m,
    const std::array<Vec3, 3> &triangle_velocity_m_s,
    double duration_s, const SweptSegmentTriangleSettings &settings = {});

} // namespace banjo
