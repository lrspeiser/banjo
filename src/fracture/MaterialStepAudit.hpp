#pragma once

#include "physics/MechanicalAccounting.hpp"
#include <array>
#include <string_view>

namespace banjo {

enum class MaterialStage : std::size_t {
    Gravity, PreContact, Prediction, Constraints, Damping, PostContact, Support, Damage, Count
};
inline constexpr std::array<std::string_view, static_cast<std::size_t>(MaterialStage::Count)>
    kMaterialStageNames{"gravity", "pre_contact", "prediction", "constraints", "damping",
                        "post_contact", "support", "damage"};

// Actual changes across a numerical stage. In particular, a change in elastic
// energy during prediction/correction is NOT automatically physical work.
// Boundary: active matter plus its coupled sphere proxy, excluding Jolt's step.
struct MaterialStageChange {
    Vec3 linear_momentum_kg_m_s{};
    Vec3 angular_momentum_kg_m2_s{};
    double kinetic_energy_j{};
    double elastic_energy_j{};
    double gravity_potential_energy_j{};
    [[nodiscard]] double mechanicalEnergy() const {
        return kinetic_energy_j + elastic_energy_j + gravity_potential_energy_j;
    }
    MaterialStageChange &operator+=(const MaterialStageChange &other) {
        linear_momentum_kg_m_s += other.linear_momentum_kg_m_s;
        angular_momentum_kg_m2_s += other.angular_momentum_kg_m2_s;
        kinetic_energy_j += other.kinetic_energy_j;
        elastic_energy_j += other.elastic_energy_j;
        gravity_potential_energy_j += other.gravity_potential_energy_j;
        return *this;
    }
    [[nodiscard]] static MaterialStageChange between(
        const MechanicalTotals &before, const MechanicalTotals &after) {
        return {after.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s,
                after.angular_momentum_kg_m2_s - before.angular_momentum_kg_m2_s,
                after.kinetic_energy_j - before.kinetic_energy_j,
                after.elastic_energy_j - before.elastic_energy_j,
                after.gravitational_potential_energy_j - before.gravitational_potential_energy_j};
    }
};
using MaterialStageChanges = std::array<MaterialStageChange, kMaterialStageNames.size()>;

} // namespace banjo
