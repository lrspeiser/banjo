#pragma once

#include "fracture/ActiveMatter.hpp"

namespace banjo {

// All angular quantities use the world origin. This is a measured state, not
// a conservation claim: external impulses/work and solver losses are separate.
struct MechanicalTotals {
    double mass_kg{};
    Vec3 mass_first_moment_kg_m{};
    Vec3 linear_momentum_kg_m_s{};
    Vec3 angular_momentum_kg_m2_s{};
    double kinetic_energy_j{};
    double elastic_energy_j{};
    double gravitational_potential_energy_j{};

    [[nodiscard]] Vec3 centerOfMass() const {
        return mass_kg > 0.0 ? mass_first_moment_kg_m / mass_kg : Vec3{};
    }
    [[nodiscard]] double mechanicalEnergy() const {
        return kinetic_energy_j + elastic_energy_j + gravitational_potential_energy_j;
    }
    MechanicalTotals &operator+=(const MechanicalTotals &other);
};

struct RigidMechanicalState {
    RigidSnapshot motion{};
    double mass_kg{};
    Mat3 inertia_world_kg_m2{};
};

struct RepresentationTransferAudit {
    bool measured{};
    MechanicalTotals before{};
    MechanicalTotals after{};
};

[[nodiscard]] MechanicalTotals measureRigidMechanics(
    const RigidMechanicalState &body, const Vec3 &gravity_m_s2 = {});
[[nodiscard]] MechanicalTotals measureMaterialMechanics(
    const ActiveMatter &matter, const Vec3 &gravity_m_s2 = {});

} // namespace banjo
