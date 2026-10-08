#pragma once
#include "core/Math.hpp"
#include <array>
namespace banjo {
struct RotationStrain {
    Vec3 angle_rad;
    // Rows of the angle-strain differential, expressed as world angular axes.
    // rate_i = dot(gradient_axes_world[i], omega_b - omega_a).
    std::array<Vec3,3> gradient_axes_world;
};
// Shortest relative SO(3) logarithm and its exact first differential.
// Refuses the nonunique pi branch; no small-angle dead zone or angle clamp.
RotationStrain rotationStrain(Quat frame_a,Quat frame_b);
}
