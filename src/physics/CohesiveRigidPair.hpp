#pragma once
#include "physics/CohesiveInterface.hpp"
#include "physics/RigidAttachment.hpp"
#include <vector>

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
struct CohesivePatchSite {
    Vec3 attachment_a_m{},attachment_b_m{};
    double rest_distance_m{},area_m2{};
    CohesiveInterfaceState history;
};
struct CohesivePatchState { CohesiveRigidBody a,b;std::vector<CohesivePatchSite> sites; };
struct CohesivePatchResult { CohesivePatchState state;double energy_residual_j{};Vec3 momentum_residual{},angular_residual{}; };
// Corresponding congruent rectangular faces, midpoint area quadrature. Width
// and height determine area; common law.area_m2 is ignored by the patch solver.
[[nodiscard]] CohesivePatchState makeRectangularCohesivePatch(CohesiveRigidBody a,CohesiveRigidBody b,
    Vec3 center_a,Vec3 center_b,Vec3 u_a,Vec3 v_a,Vec3 u_b,Vec3 v_b,double width_m,double height_m,unsigned cells_per_axis);
[[nodiscard]] CohesivePatchResult advanceCohesivePatch(const CohesiveInterfaceLaw &law,const CohesivePatchState &initial,double dt_s);
struct CohesivePatchAdaptiveResult {
    CohesivePatchState state;
    double accumulated_absolute_energy_error_j{};
    unsigned evaluations{},accepted_half_steps{};
};
[[nodiscard]] CohesivePatchAdaptiveResult advanceCohesivePatchAdaptive(const CohesiveInterfaceLaw &law,
    const CohesivePatchState &initial,double duration_s,const CohesiveAdaptiveControls &controls);
struct CohesiveBoxDeclaration {
    Vec3 dimensions_m{};
    double density_kg_m3{};
    Vec3 center_m{};
    Quat orientation;
};
struct CohesiveBoxFace {
    unsigned normal_axis{}; // 0=x, 1=y, 2=z. Tangents use cyclic next axes.
    bool positive{};
    double u_offset_m{},v_offset_m{},width_m{},height_m{};
};
// Creates at-rest bodies from matter and patches wholly contained in opposing
// box faces. Positive initial gap required; no mass is assigned to the gap.
[[nodiscard]] CohesivePatchState makeBoxFaceCohesivePatch(const CohesiveBoxDeclaration &a,const CohesiveBoxDeclaration &b,
    const CohesiveBoxFace &face_a,const CohesiveBoxFace &face_b,unsigned cells_per_axis);
}
