#include "physics/ContactMechanics.hpp"

#include <cmath>
#include <numbers>
#include <stdexcept>

namespace banjo {

HertzSphereImpactResult projectHertzSphereImpact(
    const HertzSphereImpactInput &input) {
    if (input.effective_modulus_pa <= 0.0 ||
        input.reduced_radius_m <= 0.0 ||
        input.reduced_mass_kg <= 0.0 ||
        input.normal_speed_m_s < 0.0) {
        throw std::invalid_argument(
            "Hertz sphere impact inputs must be physically positive");
    }

    HertzSphereImpactResult result;
    result.available_energy_j =
        0.5 * input.reduced_mass_kg * input.normal_speed_m_s *
        input.normal_speed_m_s;
    if (input.normal_speed_m_s == 0.0) {
        return result;
    }

    // F = K * delta^(3/2), K = 4/3 E* sqrt(R*). Equating the
    // integrated elastic work with the normal kinetic energy gives delta_max.
    const double stiffness_coefficient =
        (4.0 / 3.0) * input.effective_modulus_pa *
        std::sqrt(input.reduced_radius_m);
    result.maximum_indent_m = std::pow(
        (5.0 * input.reduced_mass_kg * input.normal_speed_m_s *
         input.normal_speed_m_s) /
            (4.0 * stiffness_coefficient),
        0.4);
    result.peak_force_n = stiffness_coefficient *
                          std::pow(result.maximum_indent_m, 1.5);
    result.contact_radius_m = std::sqrt(
        input.reduced_radius_m * result.maximum_indent_m);
    const double contact_area =
        std::numbers::pi * result.contact_radius_m *
        result.contact_radius_m;
    result.peak_pressure_pa =
        contact_area > 0.0 ? 1.5 * result.peak_force_n / contact_area : 0.0;

    // For frictionless Hertz point contact, maximum subsurface shear is
    // approximately 0.31 p0. This is a screening value, not a flaw model.
    result.maximum_subsurface_shear_pa =
        0.31 * result.peak_pressure_pa;
    return result;
}

} // namespace banjo
