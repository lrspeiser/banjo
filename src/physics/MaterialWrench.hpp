#pragma once
#include "core/Math.hpp"
#include "physics/FiniteFrameKernel.hpp"
#include <array>
namespace banjo {
struct MaterialFrame {
    Vec3 com,local_anchor;
    Quat orientation,local_frame;
};
FiniteFrameCoordinates materialCoordinates(const MaterialFrame &a,const MaterialFrame &b);
FiniteFrameWrenches materialWrenches(const MaterialFrame &a,const MaterialFrame &b,const std::array<double,6> &loads);
}
