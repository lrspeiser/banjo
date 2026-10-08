#pragma once
#include "rigid/JoltWorld.hpp"
#include <Jolt/Jolt.h>
#include <Jolt/Physics/Constraints/TwoBodyConstraint.h>
namespace banjo {
JPH::Ref<JPH::TwoBodyConstraintSettings> logFaceSpringSettings(const JoltWorld::FaceSpringDescription &description);
void prepareCenteredFaceSpring(JPH::TwoBodyConstraint &,Vec3 va,Vec3 wa,Vec3 vb,Vec3 wb);
JoltWorld::FaceSpringObservation observeLogFaceSpring(const JPH::TwoBodyConstraint &constraint);
}
