#include "fracture/ActivationPolicy.hpp"

#include "physics/ContactMechanics.hpp"

#include <algorithm>
#include <numbers>

namespace banjo {

ActivationDecision ActivationPolicy::evaluate(
    const ImpactEvent &impact,
    const ActivationTarget &target) const {
    ActivationDecision decision;

    if (!impact.involves(target.body_id)) {
        decision.reason = "impact does not involve target";
        return decision;
    }
    if (target.material.model != MaterialModel::BrittleBond) {
        decision.reason =
            "target material is not activatable by the brittle solver";
        return decision;
    }
    if (target.radius_m <= 0.0 ||
        target.material.fracture_energy_j_m2 <= 0.0 ||
        target.material.young_modulus_pa <= 0.0 ||
        target.material.tensile_strength_pa <= 0.0) {
        decision.reason = "target material or geometry is invalid";
        return decision;
    }

    const double projected_area_m2 =
        std::numbers::pi * target.radius_m * target.radius_m;
    decision.threshold_energy_j =
        projected_area_m2 * target.material.fracture_energy_j_m2 *
        std::max(
            0.0,
            target.material.calibration.activation_energy_scale);
    decision.normalized_energy = decision.threshold_energy_j > 0.0
                                     ? impact.available_normal_energy_j /
                                           decision.threshold_energy_j
                                     : 0.0;

    if (impact.closing_speed_m_s > 0.0 &&
        impact.available_normal_energy_j > 0.0) {
        const double reduced_mass_kg =
            2.0 * impact.available_normal_energy_j /
            (impact.closing_speed_m_s * impact.closing_speed_m_s);
        const double reduced_radius_m =
            target.reduced_radius_m > 0.0
                ? target.reduced_radius_m
                : 0.5 * target.radius_m;
        const double fallback_effective_modulus_pa =
            target.material.young_modulus_pa /
            (2.0 *
             (1.0 - target.material.poisson_ratio *
                        target.material.poisson_ratio));
        const double effective_modulus_pa =
            impact.effective_contact_modulus_pa > 0.0
                ? impact.effective_contact_modulus_pa
                : fallback_effective_modulus_pa;
        const HertzSphereImpactResult contact = projectHertzSphereImpact({
            effective_modulus_pa,
            reduced_radius_m,
            reduced_mass_kg,
            impact.closing_speed_m_s,
        });
        decision.predicted_peak_pressure_pa = contact.peak_pressure_pa;
        decision.tensile_stress_ratio =
            contact.maximum_subsurface_shear_pa /
            target.material.tensile_strength_pa;
        if (target.material.compressive_strength_pa > 0.0) {
            decision.compressive_stress_ratio =
                contact.peak_pressure_pa /
                target.material.compressive_strength_pa;
        }
    }

    const bool prior_damage_triggers = target.accumulated_damage >= 1.0;
    const bool global_energy_triggers =
        impact.closing_speed_m_s > 0.05 &&
        decision.normalized_energy >= 1.0;
    const double stress_energy_floor = std::max(
        0.0,
        target.material.calibration.stress_activation_energy_floor_ratio);
    const bool local_stress_triggers =
        impact.closing_speed_m_s > 0.05 &&
        decision.normalized_energy >= stress_energy_floor &&
        (decision.tensile_stress_ratio >= 1.0 ||
         decision.compressive_stress_ratio >= 1.0);

    decision.activate = prior_damage_triggers || global_energy_triggers ||
                        local_stress_triggers;
    if (prior_damage_triggers) {
        decision.reason = "accumulated material damage requires physicalization";
    } else if (global_energy_triggers) {
        decision.reason = "global fracture-energy threshold exceeded";
    } else if (local_stress_triggers) {
        decision.reason = "Hertz contact stress exceeds brittle strength";
    } else {
        decision.reason =
            "impact remains below energy and local-stress activation thresholds";
    }
    return decision;
}

} // namespace banjo
