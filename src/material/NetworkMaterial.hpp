#pragma once

#include "core/Math.hpp"

#include <string>

namespace banjo {

enum class NetworkFailureLaw : unsigned char {
    Cohesive,
    Brittle,
};

// A directional axial cohesive-lattice approximation.  This is deliberately
// smaller than a full orthotropic continuum law: each bond has one reference
// direction and carries opening/compression, plastic extension, and damage.
struct NetworkMaterial {
    std::string name;
    double density_kg_m3{};
    Vec3 young_modulus_pa{};
    Vec3 tensile_strength_pa{};
    Vec3 fracture_energy_j_m2{};
    double damping_ratio{};
    double friction{};
    double yield_strength_pa{};
    double hardening_ratio{};
    bool fracture_enabled{true};
    NetworkFailureLaw failure_law{NetworkFailureLaw::Cohesive};
    // Contact loss is declared separately from internal (bond) damping; the
    // rigid lane derives restitution from it. Defaults to the engine's general
    // MaterialDefinition value and records that it did, because a silent zero
    // here previously made every contact perfectly elastic.
    // Declared last so positional aggregate initialisers of the fields above
    // keep their meaning.
    double contact_damping_ratio{0.05};
    bool contact_damping_defaulted{true};
};

struct DirectionalNetworkParameters {
    double stiffness_n_m{};
    double strength_n{};
    double fracture_work_j{};
    double area_m2{};
    double rest_length_m{};
    double yield_force_n{};
};

struct NetworkBondHistory {
    double plastic_extension_m{};
    double maximum_elastic_opening_m{};
    double damage{};
    double fracture_dissipation_j{};
    double plastic_dissipation_j{};
    double unreleased_energy_j{};
};

struct NetworkBondUpdate {
    NetworkBondHistory history;
    double stiffness_n_m{};
    double elastic_energy_j{};
    double fracture_increment_j{};
    double plastic_increment_j{};
    double unreleased_energy_j{};
    bool failed{};
};

void validateNetworkMaterial(const NetworkMaterial &material);

[[nodiscard]] DirectionalNetworkParameters directionalNetworkParameters(
    const NetworkMaterial &material,
    Vec3 unit_reference_direction,
    double area_m2,
    double rest_length_m);

[[nodiscard]] NetworkBondUpdate advanceNetworkBond(
    const NetworkMaterial &material,
    const DirectionalNetworkParameters &parameters,
    const NetworkBondHistory &history,
    double total_extension_m,
    double rest_length_m);

} // namespace banjo
