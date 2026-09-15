#pragma once

// A rope that winds onto a turning drum (docs/machine-world.md): the joint a
// hoist, a winch or a crane needs, and one Jolt does not have.
//
// It is Jolt's own rope -- a distance constraint that pulls and never pushes --
// with its drum end moved, as each step begins, to where the rope leaves the
// drum: the point on the drum's circle where the rope runs off it tangentially
// towards the load. For that step the anchor is a point of the drum, so the
// rope's tension turns the drum about its axle at the drum's radius, and a drum
// turned winds the load up exactly as its surface carries the anchor away from
// the load. Between steps, the arc the drum has turned past the new departure
// point is rope taken on (or let off), so the free length the rope allows
// changes by it:
//
//     wound += winds * r * (turn of the drum - turn of the departure point)
//
// both about the drum's axle: a load swinging round the drum unwinds it as
// surely as the drum turning back does. Many turns are as good as one, since
// nothing here is an angle that wraps.
//
// It is the same constraint from step to step, so it starts each step from the
// last one's tension, as any constraint does. A rope made afresh each step
// would start every step with none: see the kerf's cold start in
// JoltWorld::addKerf.

#include <Jolt/Jolt.h>

#include <Jolt/Physics/Constraints/ConstraintPart/AxisConstraintPart.h>
#include <Jolt/Physics/Constraints/TwoBodyConstraint.h>

namespace banjo {

struct DrumRopeParameters {
    // The drum: its centre and its axle in the drum body's own centre-of-mass
    // frame, and its radius where the rope lies on it.
    JPH::Vec3 centre_local{JPH::Vec3::sZero()};
    JPH::Vec3 axis_local{JPH::Vec3::sAxisZ()};
    float radius_m{};
    // Where the rope is made off on the load, in the load's centre-of-mass frame.
    JPH::Vec3 load_point_local{JPH::Vec3::sZero()};
    // +1: the drum turning the positive way about its axle takes rope on; -1:
    // turning the other way does.
    float winds{1.0F};
    // The rope's whole length, and how much of it is on the drum. A negative
    // wound means "as it hangs": the rope is exactly as long as the span from
    // the drum to the load is when it is made.
    double length_m{};
    double wound_m{-1.0};
};

class DrumRopeSettings final : public JPH::TwoBodyConstraintSettings {
public:
    // Body 1 is the drum, body 2 the load.
    JPH::TwoBodyConstraint *Create(JPH::Body &drum, JPH::Body &load) const override;
    DrumRopeParameters rope;
};

class DrumRopeConstraint final : public JPH::TwoBodyConstraint {
public:
    JPH_OVERRIDE_NEW_DELETE

    DrumRopeConstraint(JPH::Body &drum, JPH::Body &load, const DrumRopeSettings &settings);

    JPH::EConstraintSubType GetSubType() const override { return JPH::EConstraintSubType::User1; }
    void NotifyShapeChanged(const JPH::BodyID &body, JPH::Vec3Arg delta_com) override;
    void SetupVelocityConstraint(float dt) override;
    void ResetWarmStart() override;
    void WarmStartVelocityConstraint(float ratio) override;
    bool SolveVelocityConstraint(float dt) override;
    bool SolvePositionConstraint(float dt, float baumgarte) override;
#ifdef JPH_DEBUG_RENDERER
    void DrawConstraint(JPH::DebugRenderer *renderer) const override;
#endif
    void SaveState(JPH::StateRecorder &stream) const override;
    void RestoreState(JPH::StateRecorder &stream) override;
    JPH::Ref<JPH::ConstraintSettings> GetConstraintSettings() const override;
    JPH::Mat44 GetConstraintToBody1Matrix() const override { return JPH::Mat44::sTranslation(mAnchorLocal); }
    JPH::Mat44 GetConstraintToBody2Matrix() const override {
        return JPH::Mat44::sTranslation(mRope.load_point_local);
    }

    // The rope's impulse along itself over the last step, newton seconds: zero
    // or less, since it pulls.
    [[nodiscard]] float totalLambda() const { return mAxis.GetTotalLambda(); }
    [[nodiscard]] double length() const { return mRope.length_m; }
    [[nodiscard]] double radius() const { return mRope.radius_m; }
    // What is on the drum and off it as the bodies stand now -- counting what
    // the drum has turned since the step began, which the constraint itself
    // takes up as the next one begins. Off it is the most the span from the
    // drum to the load may be.
    [[nodiscard]] double wound() const { return woundNow(); }
    [[nodiscard]] double out() const { return mRope.length_m - woundNow(); }
    // Where it leaves the drum and where it meets the load, in the world, and
    // how far apart those are, as the bodies stand now.
    [[nodiscard]] JPH::RVec3 leaves() const;
    [[nodiscard]] JPH::RVec3 meets() const;
    [[nodiscard]] double span() const;

private:
    // Where the rope leaves the drum as the bodies stand: a unit vector from
    // the drum's centre, in the world, and the point there.
    void departure(JPH::Vec3 &leaving, JPH::RVec3 &anchor_world) const;
    // The same, kept for this step: mLeaving and the anchor.
    void findDeparture();
    // What is on the drum as the bodies stand: the wound length as the step
    // began, and the arc the drum has turned past the departure point since.
    [[nodiscard]] double woundNow() const;
    // The most the span may be for this step: what was off the drum as it
    // began. Within the step the anchor, a point of the drum, carries the
    // winding itself.
    [[nodiscard]] float allowed() const { return static_cast<float>(mRope.length_m - mRope.wound_m); }
    void calculateConstraintProperties(float dt);

    DrumRopeParameters mRope;
    // The departure point, in the drum's frame, for this step, and in the world
    // as last worked out; the load's point likewise.
    JPH::Vec3 mAnchorLocal{JPH::Vec3::sZero()};
    JPH::RVec3 mAnchorWorld{JPH::RVec3::sZero()};
    JPH::RVec3 mLoadWorld{JPH::RVec3::sZero()};
    JPH::Vec3 mLeaving{JPH::Vec3::sAxisX()};
    JPH::Vec3 mNormal{0.0F, -1.0F, 0.0F};
    // For the winding: the drum's orientation, and where the rope left it, as
    // the last step began.
    JPH::Quat mDrumBefore{JPH::Quat::sIdentity()};
    JPH::Vec3 mLeavingBefore{JPH::Vec3::sAxisX()};
    float mMinLambda{};
    float mMaxLambda{};
    JPH::AxisConstraintPart mAxis;
};

} // namespace banjo
