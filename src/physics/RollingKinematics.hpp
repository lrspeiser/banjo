#pragma once

#include "core/Plane.hpp"
#include "fracture/ActiveMatter.hpp"
#include <string_view>

namespace banjo {
enum class RollingState { Airborne, Resting, Rolling, Slipping };
struct RollingKinematics {
    RollingState state{RollingState::Airborne};
    double translation_speed_m_s{};
    double rolling_surface_speed_m_s{};
    double contact_slip_speed_m_s{};
    double normalized_slip{};
    Vec3 contact_velocity_world_m_s{};
};

// Diagnostic only: never writes simulation velocities or imposes v = r*omega.
[[nodiscard]] RollingKinematics measureRollingKinematics(
    const RigidSnapshot &body, double radius_m, const SupportPlaneFrame &plane,
    bool over_support = true, double contact_tolerance_m = 0.003,
    double slip_tolerance_m_s = 0.02);
[[nodiscard]] std::string_view rollingStateName(RollingState state);
} // namespace banjo
