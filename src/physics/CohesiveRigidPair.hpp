#pragma once
#include "physics/CohesiveInterface.hpp"
#include "physics/RigidAttachment.hpp"

namespace banjo {
struct CohesiveTimestepRefinement : std::invalid_argument { using std::invalid_argument::invalid_argument; };
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
struct CohesiveAdaptiveControls {
    double energy_error_budget_j{};
    double state_error_tolerance{}; // Dimensionless step-doubling disagreement.
    unsigned maximum_evaluations{8192};
};
struct CohesiveAdaptiveResult {
    CohesiveRigidPairState state;
    double accumulated_absolute_energy_error_j{};
    unsigned evaluations{},accepted_half_steps{};
};
// Returns only a fully accepted candidate. Exhaustion/unsupported states throw;
// caller input is immutable. This is error control, not exact event location.
[[nodiscard]] CohesiveAdaptiveResult advanceCohesiveRigidAdaptive(const CohesiveInterfaceLaw &law,
    double rest_distance_m,const CohesiveRigidPairState &initial,double duration_s,const CohesiveAdaptiveControls &controls);
}
