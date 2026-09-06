#pragma once
#include "physics/DynamicPatch.hpp"
#include <array>
#include <cstdint>
#include <vector>
namespace banjo {
struct PatchSphere {
    Vec3 center_m{}, velocity_m_s{}, spin_rad_s{};
    double radius_m{}, mass_kg{};
};
struct PatchContactOptions {
    double friction_coefficient{0};
    double contact_margin_m{1.e-8};
    double maximum_penetration_m{1.e-7};
    unsigned maximum_contact_events{128};
    unsigned maximum_geometry_queries{32768};
    unsigned maximum_geometry_iterations{262144};
};
struct PatchContactEvent {
    unsigned triangle{};
    double estimated_time_s{}; // event time in the linear drift model for this step
    std::array<double, 3> barycentric{};
    Vec3 point_m{}, normal{}, impulse_to_sphere_n_s{};
    bool final_velocity_constraint{};
    bool normal_constraint_reaction{};
};
struct SpherePatchReport {
    // If false, fields describe a rejected trial; no state was committed.
    bool accepted{};
    std::string error;
    DynamicPatchReport material;
    unsigned geometry_queries{}, geometry_iterations{}, impulse_contacts{};
    unsigned velocity_constraint_contacts{};
    double minimum_gap_m{}, sphere_kinetic_energy_j{}, contact_dissipation_j{};
    // Stage kinetic energy removed by a resting normal constraint after a
    // force kick. It is an integration diagnostic, not irreversible impact heat.
    // The raw whole-step physical energy ledger still controls acceptance.
    double normal_constraint_projection_loss_j{};
    double external_work_j{}, numerical_energy_balance_residual_j{};
    Vec3 contact_support_impulse_n_s{}, linear_momentum_balance_residual_kg_m_s{};
    Vec3 contact_angular_momentum_residual_kg_m2_s{};
    std::vector<PatchContactEvent> contacts; // first 64; counters retain total
};
// Each requested interval receives duration/reference_time_s of these limits.
// A smooth time allocation and consumable contact reserve share that same total.
// Coarse/two-half-step indicators do not certify exact-solution or spatial
// accuracy. Absolute accepted-step energy residuals cannot cancel one another.
struct SpherePatchErrorLimits {
    double position_m{1.e-5};
    double velocity_m_s{.1}; // includes radius times sphere spin difference
    double strain{.01};      // total/plastic tensor norms and equivalent plastic strain
    double energy_disagreement_j{1.e-5};
    double absolute_energy_residual_j{1.e-5};
    double reference_time_s{.1};
};
struct SpherePatchAdvanceOptions {
    SpherePatchErrorLimits error;
    double initial_trial_dt_s{1.e-5};
    double maximum_trial_dt_s{1.e-3};
    double minimum_trial_dt_s{1.e-10};
    // Portion of the SAME interval error budgets reserved for nonsmooth
    // contact events. Spent reserve is never reused by later segments.
    double contact_error_reserve_fraction{.5};
    double maximum_contact_budget_fraction_per_segment{.03125};
    unsigned maximum_step_calls{65536};
    std::uint64_t maximum_reserved_element_visits{10000000};
    std::uint64_t maximum_geometry_queries{10000000};
    std::uint64_t maximum_geometry_iterations{10000000};
};
struct SpherePatchErrorEstimate {
    double position_m{}, velocity_m_s{}, strain{}, energy_disagreement_j{};
    double absolute_energy_residual_j{}, normalized{};
};
struct SpherePatchAdvanceReport {
    // Rejected intervals publish no state/time/ledgers. Tentative counts and
    // errors remain diagnostics; only accepted=true makes these physical totals.
    bool accepted{};
    std::string error;
    unsigned step_calls{}, accepted_segments{}, rejected_segments{};
    std::uint64_t reserved_element_visits{}, geometry_queries{}, geometry_iterations{};
    double advanced_time_s{}, tentative_time_s{}, remaining_time_s{};
    double minimum_accepted_step_s{}, maximum_accepted_error{}, suggested_trial_dt_s{};
    double absolute_energy_residual_j{}, signed_energy_residual_j{}, external_work_j{};
    double contact_energy_reserve_spent_j{};
    double contact_dissipation_j{}, plastic_dissipation_increment_j{};
    double normal_constraint_projection_loss_j{};
    Vec3 momentum_residual_kg_m_s{}, contact_angular_residual_kg_m2_s{};
    std::uint64_t impulse_contacts{};
    SpherePatchErrorEstimate last_error;
    SpherePatchErrorEstimate minimum_step_error;
    SpherePatchErrorEstimate accumulated_error;
    SpherePatchErrorEstimate contact_error_reserve_spent;
    SpherePatchReport last_trial;
};
// One finite-mass sphere coupled to a small-strain tetrahedral patch. Surface
// contact uses barycentric nodal impulses, no restitution or fracture trigger.
// Swept linear geometry locates contact before drift; nodes and sphere advance
// to the event before equal-and-opposite impulses are applied. No restitution
// or position correction is added. Geometry or work limits reject the entire
// step. A caller may refine time without losing accepted state. This is an
// explicit small-strain reference, not a realtime or full material claim.
class SpherePatchWorld {
  public:
    SpherePatchWorld(PatchDefinition definition, PatchSphere sphere,
                     DynamicPatchOptions dynamics = {}, PatchContactOptions contact = {});
    const DynamicPatch &material() const {
        return patch_;
    }
    const PatchSphere &sphere() const {
        return sphere_;
    }
    SpherePatchReport step(double dt_s, const DynamicPatchLoad &load, Vec3 sphere_force_n = {},
                           Vec3 sphere_gravity_m_s2 = {});
    // Constant loads over this interval. Accepts the two actual half steps,
    // without state extrapolation. Failure rolls back the entire interval,
    // including earlier tentative accepted segments. Reference caches are reused.
    SpherePatchAdvanceReport advance(double duration_s, const DynamicPatchLoad &load,
                                     const SpherePatchAdvanceOptions &options = {},
                                     Vec3 sphere_force_n = {}, Vec3 sphere_gravity_m_s2 = {});

  private:
    DynamicPatch patch_;
    PatchSphere sphere_;
    PatchContactOptions contact_;
};
} // namespace banjo
