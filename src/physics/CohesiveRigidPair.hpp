#pragma once
#include "physics/CohesiveInterface.hpp"
#include "physics/RigidAttachment.hpp"

namespace banjo {
struct CohesiveRigidBody {
    double mass_kg{};
    Vec3 principal_inertia_kg_m2{},center_m{},velocity_m_s{},angular_momentum_kg_m2_s{},attachment_local_m{};
    Quat orientation;
};
struct CohesiveRigidPairState {
    CohesiveRigidBody a,b;
    CohesiveInterfaceState interface;
};
struct CohesiveRigidPairResult {
    CohesiveRigidPairState state;
    double energy_residual_j{}; // Numerical error, never converted to heat.
    Vec3 momentum_residual_kg_m_s{},angular_residual_kg_m2_s{};
};
// One bounded kick/free-rotation/kick step. Caller must refine timestep and
// inspect energy error. No compression contact, shear or external fields.
[[nodiscard]] CohesiveRigidPairResult advanceCohesiveRigidPair(const CohesiveInterfaceLaw &law,
    double rest_distance_m,const CohesiveRigidPairState &initial,double dt_s);
[[nodiscard]] double cohesiveRigidKineticEnergy(const CohesiveRigidPairState &state);
}
