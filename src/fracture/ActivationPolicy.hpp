#pragma once

#include "fracture/ImpactEvent.hpp"
#include "material/Material.hpp"

#include <string>

namespace banjo {

struct ActivationTarget {
    MatterBodyId body_id{kInvalidMatterBodyId};
    double radius_m{};
    MaterialDefinition material{};
    double accumulated_damage{};
    double reduced_radius_m{};
};

struct ActivationDecision {
    bool activate{};
    double threshold_energy_j{};
    double normalized_energy{};
    double predicted_peak_pressure_pa{};
    double tensile_stress_ratio{};
    double compressive_stress_ratio{};
    std::string reason;
};

class ActivationPolicy {
public:
    [[nodiscard]] ActivationDecision evaluate(
        const ImpactEvent &impact,
        const ActivationTarget &target) const;
};

} // namespace banjo
