#include "physics/SweptSegmentTriangle.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace banjo {
namespace {

bool finite(double value) { return std::isfinite(value); }
bool finite(Vec3 value) {
    return finite(value.x) && finite(value.y) && finite(value.z);
}

} // namespace

SweptSegmentTriangleResult sweepSegmentTriangle(
    const std::array<Vec3, 2> &segment,
    const std::array<Vec3, 2> &segment_velocity,
    const std::array<Vec3, 3> &triangle,
    const std::array<Vec3, 3> &triangle_velocity,
    double duration, const SweptSegmentTriangleSettings &settings) {
    SweptSegmentTriangleResult result;
    if (!finite(duration) || duration < 0. || !finite(settings.contact_radius_m) ||
        settings.contact_radius_m < 0. || !finite(settings.distance_tolerance_m) ||
        settings.distance_tolerance_m < 0. || settings.maximum_evaluations == 0 ||
        settings.maximum_evaluations > 4096)
        return result;
    for (unsigned i = 0; i < 2; ++i)
        if (!finite(segment[i]) || !finite(segment_velocity[i])) return result;
    for (unsigned i = 0; i < 3; ++i)
        if (!finite(triangle[i]) || !finite(triangle_velocity[i])) return result;

    // Every point of each simplex has a velocity in the convex hull of its
    // vertex velocities. Thus this maximum pairwise relative vertex speed is
    // a Lipschitz bound for the distance between the two moving convex sets.
    double relative_speed_bound = 0.;
    for (Vec3 segment_v : segment_velocity)
        for (Vec3 triangle_v : triangle_velocity)
            relative_speed_bound = std::max(
                relative_speed_bound, length(segment_v - triangle_v));
    if (!finite(relative_speed_bound)) return result;

    const double threshold = settings.contact_radius_m +
                             settings.distance_tolerance_m;
    if (!finite(threshold)) return result;
    double time = 0.;
    for (; result.evaluations < settings.maximum_evaluations;) {
        std::array<Vec3, 2> current_segment;
        std::array<Vec3, 3> current_triangle;
        for (unsigned i = 0; i < 2; ++i)
            current_segment[i] = segment[i] + time * segment_velocity[i];
        for (unsigned i = 0; i < 3; ++i)
            current_triangle[i] = triangle[i] + time * triangle_velocity[i];
        result.geometry = closestSegmentTriangle(current_segment, current_triangle);
        ++result.evaluations;
        result.time_s = time;
        if (!result.geometry.resolved) return result;
        const double slack = 32. * std::numeric_limits<double>::epsilon() *
                             std::max({1., result.geometry.distance_m, threshold});
        if (result.geometry.distance_m <= threshold + slack) {
            result.hit = true;
            result.resolved = true;
            return result;
        }
        if (time >= duration) {
            result.time_s = duration;
            result.resolved = true;
            return result;
        }
        if (relative_speed_bound == 0.) {
            // The separation is constant, but both shapes may share a nonzero
            // translation. Evaluate once at the interval endpoint so the
            // returned witness geometry agrees with the reported time.
            time = duration;
            continue;
        }
        // Advance toward the physical capsule radius. The tolerance remains a
        // stopping band rather than part of the step target, avoiding an
        // asymptotic approach to its outer boundary.
        const double step = (result.geometry.distance_m -
                             settings.contact_radius_m) /
                            relative_speed_bound;
        if (!finite(step) || !(step > 0.)) {
            result.stagnated = true;
            return result;
        }
        const double next = std::min(duration, time + step);
        if (!(next > time)) {
            result.stagnated = true;
            return result;
        }
        time = next;
    }
    return result;
}

} // namespace banjo
