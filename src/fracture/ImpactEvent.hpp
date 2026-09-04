#pragma once

#include "core/Math.hpp"
#include "core/Types.hpp"

#include <cstdint>
#include <stdexcept>

namespace banjo {

struct ImpactEvent {
    std::uint64_t fixed_tick{};
    MatterBodyId body_a{kInvalidMatterBodyId};
    MatterBodyId body_b{kInvalidMatterBodyId};

    Vec3 contact_point_world_m{};
    Vec3 normal_a_to_b{};
    Vec3 relative_velocity_b_minus_a_m_s{};

    double closing_speed_m_s{};
    double estimated_normal_impulse_n_s{};
    double available_normal_energy_j{};

    [[nodiscard]] bool involves(MatterBodyId body) const {
        return body == body_a || body == body_b;
    }

    [[nodiscard]] Vec3 normalInto(MatterBodyId target) const {
        if (target == body_b) {
            return normal_a_to_b;
        }
        if (target == body_a) {
            return -normal_a_to_b;
        }
        throw std::invalid_argument("target body is not part of impact event");
    }
};

} // namespace banjo
