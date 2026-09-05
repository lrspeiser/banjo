#include "physics/RollingKinematics.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
RollingKinematics measureRollingKinematics(
    const RigidSnapshot &body, double radius_m, const SupportPlaneFrame &plane,
    bool over_support, double contact_tolerance_m, double slip_tolerance_m_s) {
    if (!std::isfinite(radius_m) || radius_m <= 0.0 ||
        !std::isfinite(contact_tolerance_m) || contact_tolerance_m < 0.0 ||
        !std::isfinite(slip_tolerance_m_s) || slip_tolerance_m_s <= 0.0) {
        throw std::invalid_argument("rolling diagnostic requires valid radius and tolerances");
    }
    RollingKinematics result;
    const Vec3 translation = projectVectorOntoPlane(plane, body.linear_velocity_m_s);
    const Vec3 spin_surface = cross(body.angular_velocity_rad_s, -radius_m * plane.normal_world);
    const Vec3 slip = translation + spin_surface;
    result.translation_speed_m_s = length(translation);
    result.rolling_surface_speed_m_s = length(spin_surface);
    result.contact_velocity_world_m_s = body.linear_velocity_m_s + spin_surface;
    result.contact_slip_speed_m_s = length(slip);
    const double speed_scale = std::max({result.translation_speed_m_s,
        result.rolling_surface_speed_m_s, slip_tolerance_m_s});
    result.normalized_slip = result.contact_slip_speed_m_s / speed_scale;
    const double gap = signedDistanceToPlane(plane, body.center_of_mass_world_m) - radius_m;
    if (!over_support || std::abs(gap) > contact_tolerance_m) {
        result.state = RollingState::Airborne;
    } else if (result.translation_speed_m_s < slip_tolerance_m_s &&
               length(body.angular_velocity_rad_s) * radius_m < slip_tolerance_m_s) {
        result.state = RollingState::Resting;
    } else if (result.contact_slip_speed_m_s <= slip_tolerance_m_s) {
        result.state = RollingState::Rolling;
    } else {
        result.state = RollingState::Slipping;
    }
    return result;
}
std::string_view rollingStateName(RollingState state) {
    switch (state) {
    case RollingState::Airborne: return "airborne";
    case RollingState::Resting: return "resting";
    case RollingState::Rolling: return "rolling (near-zero slip)";
    case RollingState::Slipping: return "sliding / slipping";
    }
    return "unknown";
}
} // namespace banjo
