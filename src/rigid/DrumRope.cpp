#include "rigid/DrumRope.hpp"

#include <Jolt/Physics/Body/Body.h>
#include <Jolt/Physics/Constraints/SpringSettings.h>
#include <Jolt/Physics/StateRecorder.h>

#include <algorithm>
#include <cfloat>
#include <cmath>

namespace banjo {

namespace {

// A rope that pulled on the last step, is within a millimetre of its length and
// is not being closed faster than this, is held AT its length for the step, as
// JoltWorld::step holds a taut rope (a rope nudged a hair inside its length by
// other corrections otherwise does nothing for a whole step, and the load it
// carries drops and is snatched back).
constexpr float kSlackM = 0.001F;
constexpr float kClosingMS = 0.05F;

} // namespace

JPH::TwoBodyConstraint *DrumRopeSettings::Create(JPH::Body &drum, JPH::Body &load) const {
    return new DrumRopeConstraint(drum, load, *this);
}

DrumRopeConstraint::DrumRopeConstraint(JPH::Body &drum, JPH::Body &load, const DrumRopeSettings &settings)
    : JPH::TwoBodyConstraint(drum, load, settings), mRope(settings.rope) {
    mRope.axis_local = mRope.axis_local.Normalized();
    mRope.winds = mRope.winds < 0.0F ? -1.0F : 1.0F;
    findDeparture();
    mDrumBefore = drum.GetRotation();
    mLeavingBefore = mLeaving;
    if (mRope.wound_m < 0.0) mRope.wound_m = std::max(0.0, mRope.length_m - span());
    mRope.wound_m = std::clamp(mRope.wound_m, 0.0, mRope.length_m);
}

void DrumRopeConstraint::NotifyShapeChanged(const JPH::BodyID &body, JPH::Vec3Arg delta_com) {
    if (mBody1->GetID() == body) {
        mRope.centre_local -= delta_com;
        mAnchorLocal -= delta_com;
    } else if (mBody2->GetID() == body) {
        mRope.load_point_local -= delta_com;
    }
}

// The point on the drum's circle where the rope runs off it towards the load,
// on the side where turning the drum the `winds` way takes rope on: there the
// rope's pull turns the drum the other way, which is what a load does.
void DrumRopeConstraint::departure(JPH::Vec3 &leaving, JPH::RVec3 &anchor_world) const {
    const JPH::RMat44 drum = mBody1->GetCenterOfMassTransform();
    const JPH::Vec3 axis = drum.Multiply3x3(mRope.axis_local).Normalized();
    const JPH::RVec3 centre = drum * mRope.centre_local;
    const JPH::RVec3 load = mBody2->GetCenterOfMassTransform() * mRope.load_point_local;
    const JPH::Vec3 to_load(load - centre);
    const JPH::Vec3 across = to_load - to_load.Dot(axis) * axis;
    const float reach = across.Length();
    const float r = mRope.radius_m;
    if (reach > 1.0001F * r) {
        const JPH::Vec3 u = across / reach;
        const JPH::Vec3 v = axis.Cross(u);
        const float c = r / reach;
        const float s = std::sqrt(std::max(0.0F, 1.0F - c * c));
        leaving = c * u + mRope.winds * s * v;
    } else {
        // The load is over the drum itself, seen along the axle: there is no
        // tangent to run off, so the rope leaves where it points.
        leaving = reach > 1e-9F ? across / reach : axis.GetNormalizedPerpendicular();
    }
    anchor_world = centre + JPH::RVec3(r * leaving);
}

void DrumRopeConstraint::findDeparture() {
    departure(mLeaving, mAnchorWorld);
    mLoadWorld = mBody2->GetCenterOfMassTransform() * mRope.load_point_local;
    mAnchorLocal = JPH::Vec3(mBody1->GetInverseCenterOfMassTransform() * mAnchorWorld);
}

double DrumRopeConstraint::woundNow() const {
    // What turned since the step began: the drum about its axle, and the point
    // the rope leaves from. The arc between is rope taken on, or let off.
    //
    // Worked in double from the bodies' float state. In float, a drum that had
    // not turned at all came out turned 2.5e-8 rad, and a rope opened again
    // from a saved world read 2.5 nm more out than was saved. In double what
    // is left is some 1e-17 rad, which the rope's length does not see.
    const JPH::Quat now = mBody1->GetRotation();
    const JPH::Vec3 axis = (now * mRope.axis_local).Normalized();
    const double ax = axis.GetX(), ay = axis.GetY(), az = axis.GetZ();
    // now * conjugate(before)
    const double nw = now.GetW(), nx = now.GetX(), ny = now.GetY(), nz = now.GetZ();
    const double bw = mDrumBefore.GetW(), bx = mDrumBefore.GetX(), by = mDrumBefore.GetY(),
                 bz = mDrumBefore.GetZ();
    double tw = nw * bw + nx * bx + ny * by + nz * bz;
    double tx = bw * nx - nw * bx - (ny * bz - nz * by);
    double ty = bw * ny - nw * by - (nz * bx - nx * bz);
    double tz = bw * nz - nw * bz - (nx * by - ny * bx);
    if (tw < 0.0) {
        tw = -tw;
        tx = -tx;
        ty = -ty;
        tz = -tz;
    }
    const double twist = 2.0 * std::atan2(tx * ax + ty * ay + tz * az, tw);
    JPH::Vec3 leaving;
    JPH::RVec3 anchor;
    departure(leaving, anchor);
    const double lx = leaving.GetX(), ly = leaving.GetY(), lz = leaving.GetZ();
    const double px = mLeavingBefore.GetX(), py = mLeavingBefore.GetY(), pz = mLeavingBefore.GetZ();
    const double swept = std::atan2(ax * (py * lz - pz * ly) + ay * (pz * lx - px * lz) + az * (px * ly - py * lx),
                                    px * lx + py * ly + pz * lz);
    return std::clamp(mRope.wound_m + static_cast<double>(mRope.winds) * static_cast<double>(mRope.radius_m) *
                                          (twist - swept),
                      0.0, mRope.length_m);
}

void DrumRopeConstraint::calculateConstraintProperties(float dt) {
    mAnchorWorld = mBody1->GetCenterOfMassTransform() * mAnchorLocal;
    mLoadWorld = mBody2->GetCenterOfMassTransform() * mRope.load_point_local;
    const JPH::Vec3 delta(mLoadWorld - mAnchorWorld);
    const float apart = delta.Length();
    if (apart > 0.0F) mNormal = delta / apart;
    // r1 + u = (p1 - x1) + (p2 - p1) = p2 - x1, as in Jolt's own rope.
    const JPH::Vec3 r1_plus_u(mLoadWorld - mBody1->GetCenterOfMassPosition());
    const JPH::Vec3 r2(mLoadWorld - mBody2->GetCenterOfMassPosition());
    const float free = allowed();
    const float last = mAxis.GetTotalLambda();
    bool held = false;
    if (last < 0.0F && apart >= free - kSlackM) {
        const JPH::Vec3 closing = mBody2->GetPointVelocity(mLoadWorld) - mBody1->GetPointVelocity(mAnchorWorld);
        held = -closing.Dot(mNormal) < kClosingMS;
    }
    if (held || apart >= free) {
        mAxis.CalculateConstraintPropertiesWithSettingsForLimit(dt, *mBody1, r1_plus_u, *mBody2, r2, mNormal, 0.0F,
                                                                apart - free, JPH::SpringSettings());
        mMinLambda = -FLT_MAX;
        // Held at its length for the step, it may push as well; otherwise a
        // rope only pulls.
        mMaxLambda = held ? FLT_MAX : 0.0F;
    } else {
        mAxis.Deactivate();
    }
}

void DrumRopeConstraint::SetupVelocityConstraint(float dt) {
    // Take up what the drum wound on or let off in the last step, then anchor
    // this step's rope where it leaves the drum now.
    mRope.wound_m = woundNow();
    findDeparture();
    mDrumBefore = mBody1->GetRotation();
    mLeavingBefore = mLeaving;
    calculateConstraintProperties(dt);
}

void DrumRopeConstraint::ResetWarmStart() { mAxis.Deactivate(); }

void DrumRopeConstraint::WarmStartVelocityConstraint(float ratio) {
    mAxis.WarmStart(*mBody1, *mBody2, mNormal, ratio);
}

bool DrumRopeConstraint::SolveVelocityConstraint(float /*dt*/) {
    if (!mAxis.IsActive()) return false;
    return mAxis.SolveVelocityConstraint(*mBody1, *mBody2, mNormal, mMinLambda, mMaxLambda);
}

bool DrumRopeConstraint::SolvePositionConstraint(float dt, float baumgarte) {
    // Only a rope stretched past what is off the drum is pulled back in: slack
    // is slack.
    const float apart = JPH::Vec3(mLoadWorld - mAnchorWorld).Dot(mNormal);
    const float error = apart - allowed();
    if (!(error > 0.0F)) return false;
    calculateConstraintProperties(dt);
    if (!mAxis.IsActive()) return false;
    return mAxis.SolvePositionConstraint(*mBody1, *mBody2, mNormal, error, baumgarte);
}

#ifdef JPH_DEBUG_RENDERER
void DrumRopeConstraint::DrawConstraint(JPH::DebugRenderer * /*renderer*/) const {}
#endif

void DrumRopeConstraint::SaveState(JPH::StateRecorder &stream) const {
    JPH::TwoBodyConstraint::SaveState(stream);
    mAxis.SaveState(stream);
    stream.Write(mNormal);
    stream.Write(mRope.wound_m);
    stream.Write(mDrumBefore);
    stream.Write(mLeavingBefore);
    stream.Write(mLeaving);
    stream.Write(mAnchorLocal);
}

void DrumRopeConstraint::RestoreState(JPH::StateRecorder &stream) {
    JPH::TwoBodyConstraint::RestoreState(stream);
    mAxis.RestoreState(stream);
    stream.Read(mNormal);
    stream.Read(mRope.wound_m);
    stream.Read(mDrumBefore);
    stream.Read(mLeavingBefore);
    stream.Read(mLeaving);
    stream.Read(mAnchorLocal);
}

JPH::Ref<JPH::ConstraintSettings> DrumRopeConstraint::GetConstraintSettings() const {
    auto *settings = new DrumRopeSettings;
    ToConstraintSettings(*settings);
    settings->rope = mRope;
    return settings;
}

JPH::RVec3 DrumRopeConstraint::leaves() const {
    JPH::Vec3 leaving;
    JPH::RVec3 anchor;
    departure(leaving, anchor);
    return anchor;
}

JPH::RVec3 DrumRopeConstraint::meets() const {
    return mBody2->GetCenterOfMassTransform() * mRope.load_point_local;
}

double DrumRopeConstraint::span() const {
    return static_cast<double>(JPH::Vec3(meets() - leaves()).Length());
}

} // namespace banjo
