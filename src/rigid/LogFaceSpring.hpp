#pragma once
#include "rigid/JoltWorld.hpp"
#include <Jolt/Jolt.h>
#include <Jolt/Physics/Constraints/TwoBodyConstraint.h>
namespace banjo {
JPH::Ref<JPH::TwoBodyConstraintSettings> logFaceSpringSettings(const JoltWorld::FaceSpringDescription &description);
JoltWorld::FaceSpringObservation observeLogFaceSpring(const JPH::TwoBodyConstraint &constraint);
}
