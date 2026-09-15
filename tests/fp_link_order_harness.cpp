// Whether adding a file can change what the simulation computes.
//
// A Jolt scene that exercises the inline code the 9317a5b link maps showed
// changing hands (docs/floating-point-model.md): the constraint solver -- a
// motored hinge and a six-degree-of-freedom joint with limits, which ask
// MotionProperties::GetInverseInertiaForRotation and the axis and angle
// constraint parts -- and the narrow phase's GJK and EPA, through convex hulls
// tumbling onto each other and the floor. It prints every body's state after
// three seconds, bit for bit. banjo_fp_link_order_tests builds it twice, alone
// and with tests/fp_link_order_extra.cpp -- our own copies of those inlines --
// first on the link line, where the linker meets them before Jolt's, and
// requires the two to print the same.

#include <Jolt/Jolt.h>
#include <Jolt/RegisterTypes.h>
#include <Jolt/Core/Factory.h>
#include <Jolt/Core/JobSystemSingleThreaded.h>
#include <Jolt/Core/TempAllocator.h>
#include <Jolt/Physics/Body/BodyCreationSettings.h>
#include <Jolt/Physics/Collision/Shape/BoxShape.h>
#include <Jolt/Physics/Collision/Shape/ConvexHullShape.h>
#include <Jolt/Physics/Constraints/HingeConstraint.h>
#include <Jolt/Physics/Constraints/SixDOFConstraint.h>
#include <Jolt/Physics/PhysicsSettings.h>
#include <Jolt/Physics/PhysicsSystem.h>

#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

namespace {

constexpr JPH::ObjectLayer kStill = 0;
constexpr JPH::ObjectLayer kMoving = 1;
constexpr JPH::BroadPhaseLayer kStillBroad(0);
constexpr JPH::BroadPhaseLayer kMovingBroad(1);

class BroadPhaseLayers final : public JPH::BroadPhaseLayerInterface {
public:
    JPH::uint GetNumBroadPhaseLayers() const override { return 2; }
    JPH::BroadPhaseLayer GetBroadPhaseLayer(JPH::ObjectLayer layer) const override {
        return layer == kStill ? kStillBroad : kMovingBroad;
    }
#if defined(JPH_EXTERNAL_PROFILE) || defined(JPH_PROFILE_ENABLED)
    const char *GetBroadPhaseLayerName(JPH::BroadPhaseLayer layer) const override {
        return layer == kStillBroad ? "still" : "moving";
    }
#endif
};

class ObjectVsBroadPhase final : public JPH::ObjectVsBroadPhaseLayerFilter {
public:
    bool ShouldCollide(JPH::ObjectLayer layer, JPH::BroadPhaseLayer broad) const override {
        return layer == kMoving || broad == kMovingBroad;
    }
};

class ObjectPairs final : public JPH::ObjectLayerPairFilter {
public:
    bool ShouldCollide(JPH::ObjectLayer a, JPH::ObjectLayer b) const override { return a == kMoving || b == kMoving; }
};

// An irregular convex hull, so contacts go through GJK and EPA.
JPH::RefConst<JPH::Shape> hull(float size) {
    const JPH::Vec3 points[] = {
        {-0.21f * size, -0.14f * size, -0.18f * size}, {0.19f * size, -0.16f * size, -0.20f * size},
        {0.22f * size, -0.13f * size, 0.17f * size},   {-0.18f * size, -0.15f * size, 0.21f * size},
        {-0.16f * size, 0.17f * size, -0.14f * size},  {0.15f * size, 0.19f * size, -0.17f * size},
        {0.18f * size, 0.14f * size, 0.16f * size},    {-0.17f * size, 0.16f * size, 0.13f * size},
        {0.02f * size, 0.27f * size, 0.01f * size},
    };
    JPH::ConvexHullShapeSettings settings(points, static_cast<int>(sizeof points / sizeof points[0]));
    return settings.Create().Get();
}

JPH::BodyID add(JPH::BodyInterface &bodies, JPH::RefConst<JPH::Shape> shape, JPH::RVec3Arg at, JPH::QuatArg turned,
                JPH::EMotionType motion, JPH::Vec3Arg velocity = JPH::Vec3::sZero(),
                JPH::Vec3Arg spin = JPH::Vec3::sZero()) {
    JPH::BodyCreationSettings settings(shape, at, turned, motion,
                                       motion == JPH::EMotionType::Static ? kStill : kMoving);
    settings.mLinearVelocity = velocity;
    settings.mAngularVelocity = spin;
    return bodies.CreateAndAddBody(settings, motion == JPH::EMotionType::Static ? JPH::EActivation::DontActivate
                                                                               : JPH::EActivation::Activate);
}

std::string run() {
    JPH::TempAllocatorImpl scratch(16 * 1024 * 1024);
    JPH::JobSystemSingleThreaded jobs(JPH::cMaxPhysicsJobs);
    BroadPhaseLayers broad;
    ObjectVsBroadPhase object_vs_broad;
    ObjectPairs pairs;
    JPH::PhysicsSystem physics;
    physics.Init(64, 0, 1024, 1024, broad, object_vs_broad, pairs);
    JPH::BodyInterface &bodies = physics.GetBodyInterface();

    std::vector<JPH::BodyID> ids;
    ids.push_back(add(bodies, new JPH::BoxShape(JPH::Vec3(10.0f, 0.5f, 10.0f)), JPH::RVec3(0.0, -0.5, 0.0),
                      JPH::Quat::sIdentity(), JPH::EMotionType::Static));
    // Three hulls dropped onto each other and the floor.
    for (int i = 0; i < 3; ++i) {
        const float f = static_cast<float>(i);
        ids.push_back(add(bodies, hull(1.0f + 0.2f * f), JPH::RVec3(0.05 * i, 0.4 + 0.45 * i, -0.03 * i),
                          JPH::Quat::sRotation(JPH::Vec3(0.3f, 1.0f, 0.2f).Normalized(), 0.4f * (f + 1.0f)),
                          JPH::EMotionType::Dynamic, JPH::Vec3(0.2f, 0.0f, -0.1f * f), JPH::Vec3(0.0f, 0.5f * f, 0.3f)));
    }
    // A bar on a motored hinge, driven round against gravity.
    const JPH::BodyID post = add(bodies, new JPH::BoxShape(JPH::Vec3(0.05f, 0.5f, 0.05f)), JPH::RVec3(2.0, 1.0, 0.0),
                                 JPH::Quat::sIdentity(), JPH::EMotionType::Static);
    const JPH::BodyID bar = add(bodies, new JPH::BoxShape(JPH::Vec3(0.5f, 0.05f, 0.05f)), JPH::RVec3(2.5, 1.9, 0.0),
                                JPH::Quat::sIdentity(), JPH::EMotionType::Dynamic);
    ids.push_back(post);
    ids.push_back(bar);
    JPH::HingeConstraintSettings hinge;
    hinge.mPoint1 = hinge.mPoint2 = JPH::RVec3(2.0, 1.9, 0.0);
    hinge.mHingeAxis1 = hinge.mHingeAxis2 = JPH::Vec3::sAxisZ();
    hinge.mNormalAxis1 = hinge.mNormalAxis2 = JPH::Vec3::sAxisX();
    hinge.mMotorSettings.SetTorqueLimit(40.0f);
    auto *motored = static_cast<JPH::HingeConstraint *>(bodies.CreateConstraint(&hinge, post, bar));
    physics.AddConstraint(motored);
    motored->SetMotorState(JPH::EMotorState::Velocity);
    motored->SetTargetAngularVelocity(2.0f);
    // Two boxes on a six-degree-of-freedom joint: sliding along x within
    // limits, turning about y within limits, fixed otherwise; one thrown.
    const JPH::BodyID a = add(bodies, new JPH::BoxShape(JPH::Vec3(0.2f, 0.2f, 0.2f)), JPH::RVec3(-2.0, 0.21, 0.0),
                              JPH::Quat::sIdentity(), JPH::EMotionType::Dynamic);
    const JPH::BodyID b = add(bodies, new JPH::BoxShape(JPH::Vec3(0.2f, 0.2f, 0.2f)), JPH::RVec3(-2.0, 0.21, 0.8),
                              JPH::Quat::sIdentity(), JPH::EMotionType::Dynamic, JPH::Vec3(1.5f, 0.0f, 0.4f),
                              JPH::Vec3(0.0f, 1.0f, 0.0f));
    ids.push_back(a);
    ids.push_back(b);
    JPH::SixDOFConstraintSettings joint;
    joint.mPosition1 = joint.mPosition2 = JPH::RVec3(-2.0, 0.21, 0.4);
    joint.mAxisX1 = joint.mAxisX2 = JPH::Vec3::sAxisX();
    joint.mAxisY1 = joint.mAxisY2 = JPH::Vec3::sAxisY();
    joint.SetLimitedAxis(JPH::SixDOFConstraintSettings::EAxis::TranslationX, -0.2f, 0.2f);
    joint.MakeFixedAxis(JPH::SixDOFConstraintSettings::EAxis::TranslationY);
    joint.MakeFixedAxis(JPH::SixDOFConstraintSettings::EAxis::TranslationZ);
    joint.MakeFixedAxis(JPH::SixDOFConstraintSettings::EAxis::RotationX);
    joint.SetLimitedAxis(JPH::SixDOFConstraintSettings::EAxis::RotationY, -0.5f, 0.5f);
    joint.MakeFixedAxis(JPH::SixDOFConstraintSettings::EAxis::RotationZ);
    physics.AddConstraint(bodies.CreateConstraint(&joint, a, b));

    for (int step = 0; step < 180; ++step)
        physics.Update(1.0f / 60.0f, 1, &scratch, &jobs);

    std::string out;
    char line[512];
    for (std::size_t i = 0; i < ids.size(); ++i) {
        const JPH::RVec3 p = bodies.GetPosition(ids[i]);
        const JPH::Quat q = bodies.GetRotation(ids[i]);
        const JPH::Vec3 v = bodies.GetLinearVelocity(ids[i]);
        const JPH::Vec3 w = bodies.GetAngularVelocity(ids[i]);
        std::snprintf(line, sizeof line, "body %zu at %a %a %a turned %a %a %a %a moving %a %a %a spinning %a %a %a\n", i,
                      static_cast<double>(p.GetX()), static_cast<double>(p.GetY()), static_cast<double>(p.GetZ()),
                      static_cast<double>(q.GetX()), static_cast<double>(q.GetY()), static_cast<double>(q.GetZ()),
                      static_cast<double>(q.GetW()), static_cast<double>(v.GetX()), static_cast<double>(v.GetY()),
                      static_cast<double>(v.GetZ()), static_cast<double>(w.GetX()), static_cast<double>(w.GetY()),
                      static_cast<double>(w.GetZ()));
        out += line;
    }
    std::uint64_t digest = 14695981039346656037ULL;
    for (const char c : out) {
        digest ^= static_cast<unsigned char>(c);
        digest *= 1099511628211ULL;
    }
    std::snprintf(line, sizeof line, "digest %016llx\n", static_cast<unsigned long long>(digest));
    return out + line;
}

} // namespace

int main() {
    JPH::RegisterDefaultAllocator();
    JPH::Factory::sInstance = new JPH::Factory();
    JPH::RegisterTypes();
    const std::string state = run();
    std::fputs(state.c_str(), stdout);
    JPH::UnregisterTypes();
    delete JPH::Factory::sInstance;
    JPH::Factory::sInstance = nullptr;
    return 0;
}
