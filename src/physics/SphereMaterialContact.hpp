#pragma once

#include "fracture/ActiveMatter.hpp"

namespace banjo {
// A sphere proxy at the current synchronization point. A contact updates this
// state immediately, so later nodes see the accumulated rigid-body reaction.
struct CoupledSphereState {
    RigidSnapshot motion{};
    double radius_m{};
    double mass_kg{};
    double inertia_kg_m2{}; // isotropic sphere inertia, not a generic-body tensor
};
struct SphereMaterialContactSettings {
    double static_friction{};
    double dynamic_friction{};
    double restitution{};
    double restitution_speed_threshold_m_s{0.5};
    double node_contact_radius_m{};
    double contact_margin_m{1.0e-5};
};
struct SphereMaterialContactStats {
    std::size_t impulse_contacts{};
    Vec3 impulse_to_material_n_s{};
    Vec3 angular_impulse_to_sphere_kg_m2_s{};
    double dissipated_kinetic_energy_j{};
    double maximum_penetration_m{};
    double maximum_position_correction_m{};
};

// Point-material / finite-mass sphere contact. Uses a shared application point
// for both impulses, including the rigid angular reaction. No damage trigger,
// explosion force, target shard velocities, or extra energy budget is used.
[[nodiscard]] SphereMaterialContactStats solveSphereMaterialContacts(
    ActiveMatter &matter, CoupledSphereState &sphere, double dt_s,
    const SphereMaterialContactSettings &settings, bool correct_positions = false);
} // namespace banjo
