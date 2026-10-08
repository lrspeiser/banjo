#pragma once
#include "physics/MechanicalAccounting.hpp"

namespace banjo {
// Authoritative CPU state. World spin angular momentum survives free rotation;
// angular velocity is derived from the rotated physical inertia, never stored
// in a native float velocity or set to a no-slip/render target.
struct DoubleRigidState {
    double mass_kg{};
    Mat3 inertia_body_kg_m2{};
    Vec3 center_world_m{},velocity_world_m_s{},spin_momentum_world_kg_m2_s{};
    Quat orientation_world{};
};
struct DoubleRigidTransfer {
    DoubleRigidState state;
    Vec3 impulse_n_s{},angular_impulse_origin_kg_m2_s{};
    double work_j{},numerical_energy_j{};
    Vec3 momentum_residual_n_s{},angular_residual_kg_m2_s{};
};
[[nodiscard]] DoubleRigidState makeDoubleRigidState(const RigidMechanicalState &);
[[nodiscard]] RigidMechanicalState doubleRigidMechanics(const DoubleRigidState &);
// Reversible second-order composition of exact rank-one kinetic Hamiltonian
// flows. Inverse body inertia is Cholesky-decomposed: each term rotates about
// its own body axis with conserved world L. No angular dead zone. Signed dt
// supports reversal tests; finite |dt| <= 1 s. Energy error is numerical, not heat.
[[nodiscard]] Quat driftDoubleRigidOrientation(Quat orientation_world,
    Vec3 spin_momentum_world_kg_m2_s,const Mat3 &inertia_body_kg_m2,double dt_s);
[[nodiscard]] DoubleRigidTransfer advanceDoubleRigidFree(const DoubleRigidState &,double dt_s);
// Instantaneous real point impulse and independent free couple, both on this
// body. Work is the signed kinetic change using midpoint contact velocity/spin.
// No pose, time, constitutive history or mass change.
[[nodiscard]] DoubleRigidTransfer applyDoubleRigidImpulse(const DoubleRigidState &,
    Vec3 point_world_m,Vec3 impulse_n_s,Vec3 free_angular_impulse_kg_m2_s={});
} // namespace banjo
