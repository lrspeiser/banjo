#include "physics/TetrahedronContact.hpp"

#include <Jolt/Jolt.h>
#include <Jolt/Geometry/ConvexSupport.h>
#include <Jolt/Geometry/EPAPenetrationDepth.h>
#include <Jolt/Geometry/GJKClosestPoint.h>

#include <algorithm>
#include <cfloat>
#include <cmath>

namespace banjo {
namespace {

// Hard bound on admissible world coordinates. It is an input sanity gate, not
// an accuracy guarantee: Jolt's support mapping and both solvers are single
// precision, so the absolute error of a witness point grows with the coordinate
// magnitude while the barycentric gate in weights() below stays fixed at 2e-5 of
// the tetrahedron's own size. What actually limits the query is therefore the
// ratio of the two, not either alone. Measured with a unit tetrahedron pair
// overlapping by (0.8, 0.05, 0.05), swept along x: the most negative barycentric
// weight is -3e-8 at the origin, -1.2e-5 at 300 m and 400 m, and -4.9e-5 at
// 600 m, where it crosses the gate and the query reports unresolved. A 100 m
// tetrahedron in the same configuration at 600 m is still at -4.2e-7 and
// resolves. So a pair resolves while it sits within roughly 500 of its own edge
// lengths of the origin, and beyond that this query declines rather than
// returning a witness point it cannot place. Callers needing wider worlds must
// rebase the pair near the origin before calling.
constexpr double kMaximumCoordinateM = 1000.;

// Asks GJK to iterate to machine precision rather than stopping at Jolt's much
// looser default collision tolerance of 1e-4 m.
constexpr float kGjkToleranceM = 1.e-8f;

// Jolt asserts that the EPA tolerance is at least FLT_EPSILON.
constexpr float kEpaTolerance = FLT_EPSILON;

// Width of the band, relative to the largest input coordinate, inside which a
// witness pair that EPA refused to expand is accepted as a zero-thickness touch.
// EPA declines exactly when the Minkowski hull around the origin is degenerate,
// which is what a touching pair looks like, but it also declines on a few
// numerical failure modes. Requiring the two witness points to coincide to this
// tolerance separates the two: a genuine touch puts both witness points on the
// same shared boundary point, so their gap is only the residual of the
// single-precision barycentric reconstruction inside GJK. Measured residuals:
// 0 exactly (bit-identical witness points) for the vertex, edge-point and face
// touches of the unit tetrahedron at the origin, and 2.4e-7 m - one float ulp -
// for the same edge-point touch rotated and translated to a coordinate
// magnitude of 3.6 m, where the bound below stands at 3.6e-4 m. Three orders of
// headroom over the observed residual, while still refusing to invent a zero
// depth for a pair whose witness points are visibly apart.
constexpr double kTouchWitnessGapM = 1.e-4;

// Below this the witness gap carries no usable direction and the normal has to
// come from elsewhere.
constexpr double kDegenerateGapM = 1.e-12;

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

JPH::Vec3 jolt(Vec3 value) {
    return JPH::Vec3(float(value.x), float(value.y), float(value.z));
}

Vec3 native(JPH::Vec3Arg value) { return {value.GetX(), value.GetY(), value.GetZ()}; }

double determinant(Vec3 a, Vec3 b, Vec3 c) { return dot(a, cross(b, c)); }

// Barycentric coordinates of `point` in `tetrahedron`, following the supplied
// vertex order. Fails when the tetrahedron has no usable volume relative to its
// own edge lengths, or when the point lies outside it by more than the witness
// tolerance the callers and tests assert.
bool weights(Vec3 point, const std::array<Vec3, 4> &tetrahedron, std::array<double, 4> &out) {
    const Vec3 edge_1 = tetrahedron[1] - tetrahedron[0];
    const Vec3 edge_2 = tetrahedron[2] - tetrahedron[0];
    const Vec3 edge_3 = tetrahedron[3] - tetrahedron[0];
    const Vec3 offset = point - tetrahedron[0];
    const double volume = determinant(edge_1, edge_2, edge_3);
    const double scale = length(edge_1) * length(edge_2) * length(edge_3);
    if (!std::isfinite(volume) || !std::isfinite(scale) ||
        std::abs(volume) <= std::max(1.e-24, scale * 1.e-12))
        return false;
    out[1] = determinant(offset, edge_2, edge_3) / volume;
    out[2] = determinant(edge_1, offset, edge_3) / volume;
    out[3] = determinant(edge_1, edge_2, offset) / volume;
    out[0] = 1. - out[1] - out[2] - out[3];
    for (double weight : out)
        if (!std::isfinite(weight) || weight < -2.e-5 || weight > 1.00002) return false;
    return true;
}

Vec3 centroid(const std::array<Vec3, 4> &tetrahedron) {
    return (tetrahedron[0] + tetrahedron[1] + tetrahedron[2] + tetrahedron[3]) / 4.;
}

double extent(const std::array<Vec3, 4> &tetrahedron) {
    double largest = 0.;
    for (Vec3 vertex : tetrahedron) largest = std::max(largest, length(vertex));
    return largest;
}

bool admissible(const std::array<Vec3, 4> &tetrahedron) {
    for (Vec3 vertex : tetrahedron)
        if (!finite(vertex) || length(vertex) > kMaximumCoordinateM) return false;
    std::array<double, 4> unused{};
    return weights(tetrahedron[0], tetrahedron, unused);
}

} // namespace

TetrahedronContactResult tetrahedronContact(const std::array<Vec3, 4> &tetrahedron_a_world_m,
                                            const std::array<Vec3, 4> &tetrahedron_b_world_m) {
    TetrahedronContactResult result;
    if (!admissible(tetrahedron_a_world_m) || !admissible(tetrahedron_b_world_m)) return result;

    std::array<JPH::Vec3, 4> vertices_a{};
    std::array<JPH::Vec3, 4> vertices_b{};
    for (unsigned i = 0; i < 4; ++i) {
        vertices_a[i] = jolt(tetrahedron_a_world_m[i]);
        vertices_b[i] = jolt(tetrahedron_b_world_m[i]);
    }
    const JPH::PolygonConvexSupport support_a(vertices_a);
    const JPH::PolygonConvexSupport support_b(vertices_b);

    // One bounded narrow-phase pass over the pair. The counter is raised before
    // the solver runs and is never cleared afterwards, so an unresolved query
    // still reports the cost it paid; that is the case where a caller auditing
    // narrow-phase cost most needs the number.
    ++result.narrow_phase_calls;

    JPH::EPAPenetrationDepth penetration;
    JPH::Vec3 axis = JPH::Vec3::sAxisX();
    JPH::Vec3 witness_a = JPH::Vec3::sZero();
    JPH::Vec3 witness_b = JPH::Vec3::sZero();
    const JPH::EPAPenetrationDepth::EStatus status = penetration.GetPenetrationDepthStepGJK(
        support_a, 0.f, support_b, 0.f, kGjkToleranceM, axis, witness_a, witness_b);

    bool separated = false;
    bool touching = false;
    switch (status) {
    case JPH::EPAPenetrationDepth::EStatus::NotColliding: {
        // Jolt documents witness_a and witness_b as invalid on this path, and
        // they are: with a zero convex radius GetPenetrationDepthStepGJK hands
        // GJK inMaxDistSq = 0, so GJK bails out at the first support point that
        // proves any positive separation and returns before it ever evaluates
        // the closest points. Run the closest-point query again without that
        // distance cap to obtain the witness pair.
        JPH::GJKClosestPoint closest;
        JPH::Vec3 separating_axis = JPH::Vec3::sAxisX();
        const float distance_sq =
            closest.GetClosestPoints(support_a, support_b, kGjkToleranceM, FLT_MAX,
                                     separating_axis, witness_a, witness_b);
        // FLT_MAX means GJK gave up on the distance and the points are invalid.
        // It cannot happen with an uncapped inMaxDistSq, but there is nothing
        // usable to report if it ever does.
        if (!std::isfinite(distance_sq) || distance_sq >= FLT_MAX) return result;
        axis = separating_axis;
        separated = distance_sq > 0.f;
        // The capped and uncapped runs can disagree for a pair that is barely
        // apart: the capped one proves a positive separation, the uncapped one
        // converges onto zero. Zero is the finer answer, so take it as a touch.
        touching = !separated;
        break;
    }
    case JPH::EPAPenetrationDepth::EStatus::Colliding:
        // Unreachable with zero convex radii, because this status means the
        // separation is positive but no larger than the combined convex radius.
        // Handled rather than asserted: the witness points are valid and the
        // depth is bounded by that radius, which is zero, so it is a touch.
        touching = true;
        break;
    case JPH::EPAPenetrationDepth::EStatus::Indeterminate: {
        JPH::Vec3 epa_axis = JPH::Vec3::sZero();
        JPH::Vec3 epa_a = JPH::Vec3::sZero();
        JPH::Vec3 epa_b = JPH::Vec3::sZero();
        if (penetration.GetPenetrationDepthStepEPA(support_a, support_b, kEpaTolerance, epa_axis,
                                                   epa_a, epa_b)) {
            axis = epa_axis;
            witness_a = epa_a;
            witness_b = epa_b;
        } else {
            // Every EPA failure path in Jolt is a refusal to build a hull that
            // encloses the origin, which is what a pair sharing only boundary
            // points looks like: Jolt's own comment is that the hull is
            // degenerate when the shapes touch in one point or in a plane. The
            // GJK step already placed a witness pair on that shared boundary,
            // so keep it and report a zero-depth contact. The gap check below
            // refuses the case where the witness points do not agree.
            touching = true;
        }
        break;
    }
    }

    const Vec3 point_a = native(witness_a);
    const Vec3 point_b = native(witness_b);
    if (!finite(point_a) || !finite(point_b)) return result;
    const Vec3 gap = point_b - point_a;
    const double magnitude = length(gap);
    if (!std::isfinite(magnitude)) return result;

    if (touching) {
        const double scale = std::max(1., std::max(extent(tetrahedron_a_world_m),
                                                   extent(tetrahedron_b_world_m)));
        if (magnitude > kTouchWitnessGapM * scale) return result;
    }

    if (!weights(point_a, tetrahedron_a_world_m, result.barycentric_a) ||
        !weights(point_b, tetrahedron_b_world_m, result.barycentric_b))
        return result;

    if (touching) {
        // The witness pair certifies a shared boundary point, so whatever is
        // left of the gap is single-precision noise rather than a direction: at
        // a coordinate magnitude of 3 m the two witness points of a touching
        // pair differ by one float ulp, and normalising that returns an
        // axis-aligned vector with no relation to the contact. A touch admits a
        // whole cone of separating directions anyway. Report the centroid
        // offset, a deterministic representative of that cone which rotates and
        // translates with the pair, so the normal stays equivariant under rigid
        // motion, and points from A to B like the separated-pair normal - the
        // sign the impulse resolver reads as "closing".
        result.normal_a_to_b =
            normalized(centroid(tetrahedron_b_world_m) - centroid(tetrahedron_a_world_m));
    } else if (magnitude > kDegenerateGapM) {
        result.normal_a_to_b = gap / magnitude;
    } else {
        // Coincident witness points with a non-zero depth: fall back to EPA's
        // own separating axis, and without one there is nothing to report.
        const Vec3 direction = native(axis);
        if (lengthSquared(direction) == 0.) return result;
        result.normal_a_to_b = normalized(direction);
    }

    result.point_a_world_m = point_a;
    result.point_b_world_m = point_b;
    result.hit = !separated;
    if (separated) {
        result.separation_distance_m = magnitude;
    } else if (!touching) {
        result.penetration_depth_m = magnitude;
    }
    // A touch leaves both distances at zero. The witness residual is not a
    // depth, and the gap check above has already bounded it; callers that want
    // the residual can take it from the two reported witness points.
    result.resolved = true;
    return result;
}

} // namespace banjo
