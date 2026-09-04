#include "fracture/ActivationPolicy.hpp"

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
        decision.reason = "target material is not activatable by the brittle solver";
        return decision;
    }
    if (target.radius_m <= 0.0 || target.material.fracture_energy_j_m2 <= 0.0) {
        decision.reason = "target material or geometry is invalid";
        return decision;
    }

    const double projected_area_m2 = std::numbers::pi * target.radius_m * target.radius_m;
    decision.threshold_energy_j =
        projected_area_m2 * target.material.fracture_energy_j_m2 *
        std::max(0.0, target.material.calibration.activation_energy_scale);

    decision.normalized_energy = decision.threshold_energy_j > 0.0
                                     ? impact.available_normal_energy_j /
                                           decision.threshold_energy_j
                                     : 0.0;

    const bool prior_damage_triggers = target.accumulated_damage >= 1.0;
    const bool impact_triggers = impact.closing_speed_m_s > 0.05 &&
                                 impact.available_normal_energy_j >= decision.threshold_energy_j;
    decision.activate = prior_damage_triggers || impact_triggers;
    decision.reason = decision.activate ? "fracture-energy threshold exceeded"
                                        : "impact remains below material activation threshold";
    return decision;
}

} // namespace banjo
