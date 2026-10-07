#include "physics/GripPull.hpp"
#include <algorithm>
#include <cmath>

namespace banjo {
namespace {
[[nodiscard]] Quat quatProduct(const Quat &a, const Quat &b) {
    return Quat{a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
                a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
                a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
                a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w};
}

}

[[nodiscard]] Mat3 gripEffectiveMass(double mass_kg, const Mat3 &inertia_world, Vec3 arm) {
    Mat3 whole;
    for (int i = 0; i < 3; ++i) whole.m[i][i] = mass_kg;
    if (!(mass_kg > 0.0)) return whole;
    const auto invert = [](const Mat3 &value, Mat3 &inverse) {
        const auto &a = value.m;
        const double c00 = a[1][1] * a[2][2] - a[1][2] * a[2][1];
        const double c01 = a[1][2] * a[2][0] - a[1][0] * a[2][2];
        const double c02 = a[1][0] * a[2][1] - a[1][1] * a[2][0];
        const double det = a[0][0] * c00 + a[0][1] * c01 + a[0][2] * c02;
        if (!(det > 0.0) || !std::isfinite(det)) return false;
        inverse.m[0][0] = c00 / det;
        inverse.m[0][1] = (a[0][2] * a[2][1] - a[0][1] * a[2][2]) / det;
        inverse.m[0][2] = (a[0][1] * a[1][2] - a[0][2] * a[1][1]) / det;
        inverse.m[1][0] = c01 / det;
        inverse.m[1][1] = (a[0][0] * a[2][2] - a[0][2] * a[2][0]) / det;
        inverse.m[1][2] = (a[0][2] * a[1][0] - a[0][0] * a[1][2]) / det;
        inverse.m[2][0] = c02 / det;
        inverse.m[2][1] = (a[0][1] * a[2][0] - a[0][0] * a[2][1]) / det;
        inverse.m[2][2] = (a[0][0] * a[1][1] - a[0][1] * a[1][0]) / det;
        return true;
    };
    Mat3 inverse_inertia;
    if (!invert(inertia_world, inverse_inertia)) return whole;
    // The grip's response to a unit force along each axis, as columns.
    Mat3 response;
    const Vec3 basis[3] = {Vec3{1.0, 0.0, 0.0}, Vec3{0.0, 1.0, 0.0}, Vec3{0.0, 0.0, 1.0}};
    for (int j = 0; j < 3; ++j) {
        const Vec3 column =
            (1.0 / mass_kg) * basis[j] + cross(inverse_inertia * cross(arm, basis[j]), arm);
        response.m[0][j] = column.x;
        response.m[1][j] = column.y;
        response.m[2][j] = column.z;
    }
    // Symmetric by construction; made exactly so before it is inverted.
    for (int i = 0; i < 3; ++i)
        for (int j = i + 1; j < 3; ++j) {
            const double mean = 0.5 * (response.m[i][j] + response.m[j][i]);
            response.m[i][j] = mean;
            response.m[j][i] = mean;
        }
    Mat3 mass;
    if (!invert(response, mass)) return whole;
    return mass;
}

[[nodiscard]] Vec3 gripTurnBetween(const Quat &from, const Quat &to) {
    Quat d = quatProduct(to, Quat{from.w,-from.x,-from.y,-from.z});
    if (d.w < 0.0) d = Quat{-d.w, -d.x, -d.y, -d.z};
    const Vec3 axis{d.x, d.y, d.z};
    const double s = length(axis);
    if (!(s > 1e-12)) return {};
    return (2.0 * std::atan2(s, d.w) / s) * axis;
}

[[nodiscard]] GripPull gripPull(const RigidMechanicalState &held, const Vec3 &grip_local,
                                const Vec3 &wanted_at, const Vec3 &wanted_velocity,
                                const Quat &wanted_facing, double strength_n,
                                double torque_n_m, const Vec3 &gravity, double bandwidth_rad_s) {
    return gripPull(held,grip_local,wanted_at,wanted_velocity,wanted_facing,
                    strength_n,torque_n_m,gravity,bandwidth_rad_s,bandwidth_rad_s);
}

[[nodiscard]] GripPull gripPull(const RigidMechanicalState &held, const Vec3 &grip_local,
                                const Vec3 &wanted_at, const Vec3 &wanted_velocity,
                                const Quat &wanted_facing, double strength_n,
                                double torque_n_m, const Vec3 &gravity,
                                double movement_rad_s, double wrist_rad_s,
                                const Vec3 &wanted_angular_velocity_rad_s) {
    const RigidSnapshot &now = held.motion;
    const Vec3 arm = now.orientation_world.rotate(grip_local);
    const Vec3 grip = now.center_of_mass_world_m + arm;
    const Vec3 grip_velocity = now.linear_velocity_m_s + cross(now.angular_velocity_rad_s, arm);
    // A hand that answers in every direction at the same rate, each
    // direction with the mass the GRIP has there. A push at the grip turns
    // the body as well as moving it, so across the arm the grip is lighter
    // than the body -- 0.6 kg of a 1.9 kg sword held 0.35 m from its
    // middle. Sized for the whole mass instead, the damping came to 2.2 of
    // a step's worth across the arm, past the 2 an explicit step can take,
    // and the sword rang at the step rate: a blade in a kerf turns that into
    // cutting nobody pushed it to do. The rate is 100 rad/s, a tenth of a
    // step per radian, unless full strength would then come sooner than
    // 50 mm off along the arm, where the grip has the whole mass.
    const double kFastest = movement_rad_s;
    constexpr double kDamping = 0.9;
    const double rate = std::min(kFastest, std::sqrt(strength_n / (0.05 * held.mass_kg)));
    const Mat3 feels = gripEffectiveMass(held.mass_kg, held.inertia_world_kg_m2, arm);
    // Its weight is carried first: a hand holding a sword out does not let
    // it sag until the error pays for it, and does not stop carrying it
    // because it is also swinging it. What the hand has left after the
    // weight goes to moving it. (Capped as one vector, a hard swing spent
    // the weight's share on the swing, and the sword dropped 100 mm and
    // passed under the rope it had been aimed at.)
    //
    // The damping is against the grip's speed RELATIVE to how fast the hand
    // wants it to go: nothing, when it is held still -- the hand as it always
    // was -- and the stroke's own speed along its path during a stroke.
    // Against the absolute speed, a stroke is a hand trying to stop the thing
    // it is throwing.
    const Vec3 hold = -held.mass_kg * gravity;
    Vec3 track = feels * ((rate * rate) * (wanted_at - grip) +
                          (2.0 * kDamping * rate) * (wanted_velocity - grip_velocity));
    const double spare = std::max(0.0, strength_n - length(hold));
    const double pull = length(track);
    if (pull > spare && pull > 0.0) track = (spare / pull) * track;
    Vec3 force = hold + track;
    // And never more than the hand has: a thing too heavy to hold up is
    // held up as far as the strength goes.
    const double total = length(force);
    if (total > strength_n && total > 0.0) force = (strength_n / total) * force;
    // The wrist turns it towards where the hand wants it facing, and has to
    // answer the turn the grip force itself puts about the centre of mass:
    // what the wrist supplies is what is left after the grip's own moment.
    const Vec3 turn = gripTurnBetween(now.orientation_world, wanted_facing);
    // Damping follows the desired frame's spin. A body-relative carry must
    // not brake the actor's actual turning as if the wrist were world-fixed.
    // World-fixed hands/strokes retain their existing zero-spin default.
    const Vec3 wanted = (wrist_rad_s * wrist_rad_s) * turn +
                        (2.0 * kDamping * wrist_rad_s) * (wanted_angular_velocity_rad_s - now.angular_velocity_rad_s);
    Vec3 torque = held.inertia_world_kg_m2 * wanted - cross(arm, force);
    const double twist = length(torque);
    if (twist > torque_n_m && twist > 0.0) torque = (torque_n_m / twist) * torque;
    return {force, torque, grip};
}

GripFeedback makeGripFeedback(const RigidMechanicalState &root,
    const std::vector<RigidMechanicalState> &parts,Vec3 grip_local) {
    RigidMechanicalState aggregate=root;
    aggregate.mass_kg=0;
    Vec3 first{};
    for (const auto &part:parts) {
        aggregate.mass_kg+=part.mass_kg;
        first+=part.mass_kg*part.motion.center_of_mass_world_m;
    }
    if (!(aggregate.mass_kg>0)) return {root,grip_local};
    aggregate.motion.center_of_mass_world_m=first/aggregate.mass_kg;
    aggregate.inertia_world_kg_m2={};
    for (const auto &part:parts) {
        const Vec3 r=part.motion.center_of_mass_world_m-aggregate.motion.center_of_mass_world_m;
        const double xyz[3]={r.x,r.y,r.z},r2=lengthSquared(r);
        for (int i=0;i<3;++i) for (int j=0;j<3;++j)
            aggregate.inertia_world_kg_m2.m[i][j]+=part.inertia_world_kg_m2.m[i][j]+
                part.mass_kg*((i==j?r2:0)-xyz[i]*xyz[j]);
    }
    const Vec3 grip=root.motion.center_of_mass_world_m+root.motion.orientation_world.rotate(grip_local);
    aggregate.motion.angular_velocity_rad_s=root.motion.angular_velocity_rad_s;
    const Vec3 omega=root.motion.angular_velocity_rad_s;
    const Vec3 actual_velocity=root.motion.linear_velocity_m_s+
        cross(omega,root.motion.orientation_world.rotate(grip_local));
    aggregate.motion.linear_velocity_m_s=actual_velocity-
        cross(omega,grip-aggregate.motion.center_of_mass_world_m);
    const auto q=root.motion.orientation_world;
    const Vec3 local=Quat{q.w,-q.x,-q.y,-q.z}.rotate(grip-aggregate.motion.center_of_mass_world_m);
    return {aggregate,local};
}
} // namespace banjo
