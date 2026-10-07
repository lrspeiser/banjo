#pragma once
#include "physics/MechanicalAccounting.hpp"
#include <vector>

namespace banjo {
struct GripPull { Vec3 force{},torque{},grip{}; };
struct GripFeedback { RigidMechanicalState held;Vec3 grip_local{}; };
// Same bounded hand law used by LiveWorld and its native coupled reference.
// SI inputs, finite current mechanical state and nonnegative force/torque caps.
// This evaluates a local root wrench; it applies no state or physical time.
[[nodiscard]] GripPull gripPull(const RigidMechanicalState &held,const Vec3 &grip_local,
    const Vec3 &wanted_at,const Vec3 &wanted_velocity,const Quat &wanted_facing,
    double strength_n,double torque_n_m,const Vec3 &gravity,double bandwidth_rad_s=100.0);
// Separate movement/wrist feedback for fixed assemblies. The original overload
// retains its single-rate law. Rates size bounded feedback, not physical caps.
[[nodiscard]] GripPull gripPull(const RigidMechanicalState &held,const Vec3 &grip_local,
    const Vec3 &wanted_at,const Vec3 &wanted_velocity,const Quat &wanted_facing,
    double strength_n,double torque_n_m,const Vec3 &gravity,double movement_rad_s,double wrist_rad_s,
    const Vec3 &wanted_angular_velocity_rad_s = {});
// Aggregate mass/inertia size the controller; feedback velocity/spin remains
// the actual gripped root's. Members are the currently attached native group,
// including root. This is a feedback frame, not merged physical geometry.
[[nodiscard]] GripFeedback makeGripFeedback(const RigidMechanicalState &root,
    const std::vector<RigidMechanicalState> &members,Vec3 grip_local);
[[nodiscard]] Mat3 gripEffectiveMass(double mass_kg,const Mat3 &inertia_world,Vec3 arm);
[[nodiscard]] Vec3 gripTurnBetween(const Quat &from,const Quat &to);
} // namespace banjo
