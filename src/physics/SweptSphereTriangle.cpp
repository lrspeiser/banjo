#include "physics/SweptSphereTriangle.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace banjo {
namespace {
bool finite(double x) {
    return std::isfinite(x);
}
bool finite(const Vec3 &v) {
    return finite(v.x) && finite(v.y) && finite(v.z);
}

TriangleClosestPointResult finishClosest(const Vec3 &p, const std::array<Vec3, 3> &t,
                                         const std::array<double, 3> &b) {
    TriangleClosestPointResult result;
    result.barycentric = b;
    result.position_world_m = b[0] * t[0] + b[1] * t[1] + b[2] * t[2];
    const Vec3 separation = p - result.position_world_m;
    result.distance_m = length(separation);
    if (!finite(result.position_world_m) || !finite(separation) || !finite(result.distance_m))
        return {};
    result.resolved = true;
    if (result.distance_m > 0) {
        result.normal_triangle_to_query = separation / result.distance_m;
    } else {
        const Vec3 winding = cross(t[1] - t[0], t[2] - t[0]);
        result.normal_triangle_to_query = winding / length(winding);
        result.used_winding_normal = true;
    }
    return result;
}

void copyClosest(SweptSphereTriangleResult &to, const TriangleClosestPointResult &from) {
    to.closest_point_world_m = from.position_world_m;
    to.barycentric = from.barycentric;
    to.normal_triangle_to_sphere = from.normal_triangle_to_query;
    to.distance_m = from.distance_m;
    to.used_winding_normal = from.used_winding_normal;
}

bool addQuadraticRoots(double a, double b, double c, double duration, std::array<double, 16> &roots,
                       unsigned &count) {
    if (!finite(a) || !finite(b) || !finite(c))
        return false;
    if (!(a > 0))
        return true;
    double discriminant = b * b - 4 * a * c;
    const double roundoff =
        16 * std::numeric_limits<double>::epsilon() * (std::abs(b * b) + std::abs(4 * a * c));
    if (!finite(discriminant) || !finite(roundoff))
        return false;
    if (discriminant < -roundoff)
        return true;
    discriminant = std::max(0.0, discriminant);
    const double root = std::sqrt(discriminant);
    const double q = -0.5 * (b + std::copysign(root, b));
    const double first = q / a;
    const double second = q != 0 ? c / q : -b / (2 * a);
    for (const double value : {first, second})
        if (finite(value) && value >= 0 && value <= duration && count < roots.size())
            roots[count++] = value;
    return true;
}

SweptSphereTriangleResult rigidTranslationSweep(const Vec3 &center, const Vec3 &relative_velocity,
                                                double radius, const std::array<Vec3, 3> &triangle,
                                                double duration, double tolerance,
                                                unsigned iterations) {
    SweptSphereTriangleResult result;
    result.iterations = iterations;
    const double contact_distance = radius + tolerance;
    std::array<double, 16> candidates{};
    unsigned count = 0;
    // Closest-point validation already established a nondegenerate triangle;
    // normalize without an absolute-size fallback so small geometry retains
    // its actual orientation.
    const Vec3 area_vector = cross(triangle[1] - triangle[0], triangle[2] - triangle[0]);
    const Vec3 winding = area_vector / length(area_vector);
    const double plane_position = dot(center - triangle[0], winding);
    const double plane_velocity = dot(relative_velocity, winding);
    if (plane_velocity != 0) {
        for (const double side : {-contact_distance, contact_distance}) {
            const double time = (side - plane_position) / plane_velocity;
            if (finite(time) && time >= 0 && time <= duration)
                candidates[count++] = time;
        }
    }
    for (unsigned edge = 0; edge < 3; ++edge) {
        const Vec3 a = triangle[edge], segment = triangle[(edge + 1) % 3] - a;
        const double segment2 = lengthSquared(segment);
        const Vec3 offset = center - a;
        const Vec3 perpendicular_offset = offset - dot(offset, segment) / segment2 * segment;
        const Vec3 perpendicular_velocity =
            relative_velocity - dot(relative_velocity, segment) / segment2 * segment;
        std::array<double, 16> roots{};
        unsigned root_count = 0;
        if (!addQuadraticRoots(lengthSquared(perpendicular_velocity),
                               2 * dot(perpendicular_offset, perpendicular_velocity),
                               lengthSquared(perpendicular_offset) -
                                   contact_distance * contact_distance,
                               duration, roots, root_count))
            return result;
        for (unsigned i = 0; i < root_count; ++i) {
            const double coordinate =
                dot(offset + roots[i] * relative_velocity, segment) / segment2;
            if (coordinate >= 0 && coordinate <= 1 && count < candidates.size())
                candidates[count++] = roots[i];
        }
    }
    for (const Vec3 vertex : triangle)
        if (!addQuadraticRoots(lengthSquared(relative_velocity),
                               2 * dot(center - vertex, relative_velocity),
                               lengthSquared(center - vertex) - contact_distance * contact_distance,
                               duration, candidates, count))
            return result;
    std::sort(candidates.begin(), candidates.begin() + count);
    const double slack =
        32 * std::numeric_limits<double>::epsilon() * std::max(1.0, contact_distance);
    for (unsigned i = 0; i < count; ++i) {
        const auto closest =
            closestPointOnTriangle(center + candidates[i] * relative_velocity, triangle);
        if (closest.resolved && closest.distance_m <= contact_distance + slack) {
            result.hit = true;
            result.resolved = true;
            result.time_s = candidates[i];
            copyClosest(result, closest);
            return result;
        }
    }
    const auto end = closestPointOnTriangle(center + duration * relative_velocity, triangle);
    if (!end.resolved)
        return result;
    result.resolved = true;
    result.time_s = duration;
    copyClosest(result, end);
    return result;
}
} // namespace

TriangleClosestPointResult closestPointOnTriangle(const Vec3 &p, const std::array<Vec3, 3> &t) {
    TriangleClosestPointResult invalid;
    if (!finite(p) || !finite(t[0]) || !finite(t[1]) || !finite(t[2]))
        return invalid;
    const Vec3 ab = t[1] - t[0], ac = t[2] - t[0];
    const double scale2 =
        std::max({lengthSquared(ab), lengthSquared(ac), lengthSquared(t[2] - t[1])});
    const double area2 = lengthSquared(cross(ab, ac));
    if (!finite(scale2) || !finite(area2) || !(scale2 > 0) ||
        area2 <= 64.0 * std::numeric_limits<double>::epsilon() * scale2 * scale2)
        return invalid;

    const Vec3 ap = p - t[0];
    const double d1 = dot(ab, ap), d2 = dot(ac, ap);
    if (d1 <= 0 && d2 <= 0)
        return finishClosest(p, t, {1, 0, 0});

    const Vec3 bp = p - t[1];
    const double d3 = dot(ab, bp), d4 = dot(ac, bp);
    if (d3 >= 0 && d4 <= d3)
        return finishClosest(p, t, {0, 1, 0});

    const double vc = d1 * d4 - d3 * d2;
    if (vc <= 0 && d1 >= 0 && d3 <= 0) {
        const double v = d1 / (d1 - d3);
        return finishClosest(p, t, {1 - v, v, 0});
    }

    const Vec3 cp = p - t[2];
    const double d5 = dot(ab, cp), d6 = dot(ac, cp);
    if (d6 >= 0 && d5 <= d6)
        return finishClosest(p, t, {0, 0, 1});

    const double vb = d5 * d2 - d1 * d6;
    if (vb <= 0 && d2 >= 0 && d6 <= 0) {
        const double w = d2 / (d2 - d6);
        return finishClosest(p, t, {1 - w, 0, w});
    }

    const double va = d3 * d6 - d5 * d4;
    if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) {
        const double w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
        return finishClosest(p, t, {0, 1 - w, w});
    }

    const double inverse_sum = 1.0 / (va + vb + vc);
    const double v = vb * inverse_sum, w = vc * inverse_sum;
    return finishClosest(p, t, {1 - v - w, v, w});
}

SweptSphereTriangleResult sweepSphereTriangle(const Vec3 &center, const Vec3 &sphere_velocity,
                                              double radius, const std::array<Vec3, 3> &triangle,
                                              const std::array<Vec3, 3> &triangle_velocity,
                                              double duration,
                                              const SweptSphereTriangleSettings &settings) {
    SweptSphereTriangleResult result;
    if (!finite(center) || !finite(sphere_velocity) || !finite(radius) || radius < 0 ||
        !finite(duration) || duration < 0 || !finite(settings.distance_tolerance_m) ||
        settings.distance_tolerance_m < 0 || settings.maximum_iterations == 0 ||
        settings.maximum_iterations > 4096)
        return result;
    for (unsigned i = 0; i < 3; ++i)
        if (!finite(triangle[i]) || !finite(triangle_velocity[i]))
            return result;

    double speed_bound = 0;
    for (const Vec3 velocity : triangle_velocity)
        speed_bound = std::max(speed_bound, length(sphere_velocity - velocity));
    if (!finite(speed_bound))
        return result;

    double time = 0;
    for (unsigned iteration = 0; iteration < settings.maximum_iterations; ++iteration) {
        ++result.iterations;
        std::array<Vec3, 3> current_triangle;
        for (unsigned i = 0; i < 3; ++i)
            current_triangle[i] = triangle[i] + time * triangle_velocity[i];
        const auto closest =
            closestPointOnTriangle(center + time * sphere_velocity, current_triangle);
        result.time_s = time;
        if (!closest.resolved)
            return result;
        copyClosest(result, closest);
        const double comparison_slack = 32.0 * std::numeric_limits<double>::epsilon() *
                                        std::max({1.0, closest.distance_m, radius});
        if (closest.distance_m <= radius + settings.distance_tolerance_m + comparison_slack) {
            result.hit = true;
            result.resolved = true;
            return result;
        }
        const bool rigid_translation = triangle_velocity[0].x == triangle_velocity[1].x &&
                                       triangle_velocity[0].y == triangle_velocity[1].y &&
                                       triangle_velocity[0].z == triangle_velocity[1].z &&
                                       triangle_velocity[0].x == triangle_velocity[2].x &&
                                       triangle_velocity[0].y == triangle_velocity[2].y &&
                                       triangle_velocity[0].z == triangle_velocity[2].z;
        if (rigid_translation) {
            auto rigid_result = rigidTranslationSweep(
                center, sphere_velocity - triangle_velocity[0], radius, triangle, duration,
                settings.distance_tolerance_m, result.iterations);
            if (rigid_result.resolved)
                rigid_result.closest_point_world_m += rigid_result.time_s * triangle_velocity[0];
            return rigid_result;
        }
        if (time >= duration || speed_bound == 0) {
            result.time_s = duration;
            result.resolved = true;
            return result;
        }
        // The closest-point normal defines a separating support plane for the
        // entire triangle. Under linear vertex motion that plane cannot reach
        // the sphere sooner than gap / maximum projected closing speed. Unlike
        // a norm-speed bound this certifies tangential/receding motion quickly,
        // while remaining conservative when the closest feature changes.
        double closing_bound = 0;
        for (const Vec3 velocity : triangle_velocity)
            closing_bound = std::max(
                closing_bound, -dot(sphere_velocity - velocity, closest.normal_triangle_to_query));
        if (!finite(closing_bound))
            return result;
        if (closing_bound == 0) {
            time = duration;
            continue;
        }
        // Advance conservatively toward physical contact, and use the declared
        // distance tolerance as the stopping band. Advancing toward the band
        // itself asymptotically stalls near its outer edge under deformation.
        const double step = (closest.distance_m - radius) / closing_bound;
        if (!(step > 0) || !finite(step))
            return result;
        time = std::min(duration, time + step);
    }
    return result;
}

} // namespace banjo
