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
};
struct SpherePatchReport {
    // If false, fields describe a rejected trial; no state was committed.
    bool accepted{};
    std::string error;
    DynamicPatchReport material;
    unsigned geometry_queries{}, geometry_iterations{}, impulse_contacts{};
    double minimum_gap_m{}, sphere_kinetic_energy_j{}, contact_dissipation_j{};
    double external_work_j{}, numerical_energy_balance_residual_j{};
    Vec3 contact_support_impulse_n_s{}, linear_momentum_balance_residual_kg_m_s{};
    Vec3 contact_angular_momentum_residual_kg_m2_s{};
    std::vector<PatchContactEvent> contacts; // first 64; counters retain total
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

  private:
    DynamicPatch patch_;
    PatchSphere sphere_;
    PatchContactOptions contact_;
};
} // namespace banjo
