#pragma once

namespace banjo {

struct HertzSphereImpactInput {
    double effective_modulus_pa{};
    double reduced_radius_m{};
    double reduced_mass_kg{};
    double normal_speed_m_s{};
};

struct HertzSphereImpactResult {
    double available_energy_j{};
    double maximum_indent_m{};
    double peak_force_n{};
    double contact_radius_m{};
    double peak_pressure_pa{};
    double maximum_subsurface_shear_pa{};
};

[[nodiscard]] HertzSphereImpactResult projectHertzSphereImpact(
    const HertzSphereImpactInput &input);

} // namespace banjo
