// Never run. What this file is for is the copies of Jolt's inline code it
// makes -- the ones the 9317a5b link maps showed changing hands: the solver's
// inverse inertia and its axis and angle constraint parts, and the closest-point
// code under GJK and EPA, in both of their instantiations.
// banjo_fp_link_order_extra_first lists this file first, so the linker meets
// these copies before Jolt's own and keeps them; tests/fp_link_order_harness.cpp
// must then compute exactly what it computes without them.

#include <Jolt/Jolt.h>
#include <Jolt/Geometry/ClosestPoint.h>
#include <Jolt/Physics/Body/Body.h>
#include <Jolt/Physics/Body/MotionProperties.h>
#include <Jolt/Physics/Constraints/ConstraintPart/AngleConstraintPart.h>
#include <Jolt/Physics/Constraints/ConstraintPart/AxisConstraintPart.h>

void banjoFpLinkOrderExtra(JPH::Body &a, JPH::Body &b, JPH::Vec3Arg axis, float value);

void banjoFpLinkOrderExtra(JPH::Body &a, JPH::Body &b, JPH::Vec3Arg axis, float value) {
    const JPH::Mat44 inverse =
        a.GetMotionProperties()->GetInverseInertiaForRotation(JPH::Mat44::sRotation(a.GetRotation()));
    JPH::AxisConstraintPart part;
    part.CalculateConstraintProperties(a, inverse.GetAxisX(), b, JPH::Vec3::sZero(), axis, value);
    part.WarmStart(a, b, axis, value);
    (void)part.SolveVelocityConstraint(a, b, axis, -value, value);
    (void)part.SolvePositionConstraint(a, b, axis, value, 0.2f);
    JPH::AngleConstraintPart angle;
    angle.CalculateConstraintProperties(a, b, axis, value);
    angle.WarmStart(a, b, value);
    (void)angle.SolveVelocityConstraint(a, b, axis, -value, value);
    (void)angle.SolvePositionConstraint(a, b, value, 0.2f);
    float u = 0.0f, v = 0.0f, w = 0.0f;
    JPH::uint32 set = 0;
    const JPH::Vec3 p(value, 0.0f, 0.0f), q(0.0f, value, 0.0f), r(0.0f, 0.0f, value), s(value, value, value);
    (void)JPH::ClosestPoint::GetBaryCentricCoordinates(p, q, r, u, v, w);
    (void)JPH::ClosestPoint::GetClosestPointOnTriangle<false>(p, q, r, set);
    (void)JPH::ClosestPoint::GetClosestPointOnTriangle<true>(p, q, r, set);
    (void)JPH::ClosestPoint::GetClosestPointOnTetrahedron<false>(p, q, r, s, set);
    (void)JPH::ClosestPoint::GetClosestPointOnTetrahedron<true>(p, q, r, s, set);
}
