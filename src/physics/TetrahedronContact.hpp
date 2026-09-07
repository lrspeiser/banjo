#pragma once

#include "core/Math.hpp"

#include <array>

namespace banjo {

struct TetrahedronContactResult {
    // True when the query produced a contact description for the supplied pair.
    // False only when the inputs cannot be described (non-finite, outside the
    // accepted coordinate range, or zero-volume) or when the solver could not
    // certify an answer; every other field is then meaningless except
    // narrow_phase_calls, which still reports the work that was paid for.
    bool resolved{};

    // True when the two tetrahedra intersect as closed convex sets. Touching in
    // a single point or across a shared face counts as intersecting and reports
    // penetration_depth_m == 0; see tetrahedronContact below.
    bool hit{};

    // Unit vector pointing from the witness point on A towards the witness point
    // on B. Note what that means for its sign: for a disjoint pair it points out
    // of A towards B, but for an overlapping pair the witness point on B lies
    // inside A, so it points into A instead. The direction is the literal one
    // stated here in both regimes; there is no fixed inward or outward
    // convention across them. When hit is true and penetration_depth_m is zero
    // the witness points coincide and there is no such direction at all: the
    // touch admits a whole cone of separating directions, and the reported
    // vector is one deterministic representative of that cone, oriented out of A
    // towards B to agree with the disjoint case.
    Vec3 normal_a_to_b{};

    // Depth of overlap, zero unless hit is true.
    double penetration_depth_m{};

    // Gap between the closest points, zero unless the tetrahedra are disjoint.
    double separation_distance_m{};

    Vec3 point_a_world_m{};
    Vec3 point_b_world_m{};
    std::array<double, 4> barycentric_a{};
    std::array<double, 4> barycentric_b{};

    // Bounded narrow-phase passes over the pair. One tetrahedronContact call
    // performs at most one pass and never loops, subdivides or retries, so this
    // is 1 for any query that reached the solver and 0 for one rejected on its
    // inputs alone. It is preserved on every exit, including unresolved ones, so
    // that summing it over a batch counts the pairs actually tested.
    unsigned narrow_phase_calls{};
};

// Pure bounded GJK/EPA query. Barycentric arrays follow the supplied vertex
// order. Contact geometry never implies fracture, cutting, or an impulse.
//
// Contact semantics for exactly-touching tetrahedra: a pair that shares only
// boundary points resolves as a contact, hit == true with
// penetration_depth_m == 0, rather than being rejected as degenerate. Two
// reasons. First, it is the common limit of both neighbouring regimes -
// separation -> 0+ and depth -> 0+ - so rejecting it would put an unresolvable
// hole in the answer exactly at the instant contact begins, which is the instant
// a contact solver most needs an answer. Second, resolved == false is reserved
// here for inputs the query cannot describe; a touching pair is a well-posed
// configuration with a unique witness point and a well-defined zero depth. Only
// the normal is under-determined, and that is stated in normal_a_to_b above.
[[nodiscard]] TetrahedronContactResult tetrahedronContact(
    const std::array<Vec3, 4> &tetrahedron_a_world_m,
    const std::array<Vec3, 4> &tetrahedron_b_world_m);

} // namespace banjo
