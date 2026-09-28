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
    double tangential_speed_m_s{};
    double estimated_normal_impulse_n_s{};
    double available_normal_energy_j{};

    double combined_static_friction{};
    double combined_dynamic_friction{};
    double applied_friction{};
    double combined_restitution{};
    double effective_contact_modulus_pa{};
    bool response_deferred_to_material{};

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

// A total order over contacts, for anything whose ANSWER depends on the order
// it reads them in.
//
// Jolt's collector is filled from its worker threads under a mutex, so the
// order events arrive in is a thread-completion order: it is not the same
// twice, and nothing built on it is reproducible. Every decision that reads
// contacts in sequence -- which body is offered first, which partner a struck
// body keeps when two contacts hit it equally hard -- is taken on this order
// instead, which is a function of the contacts themselves. Same world, same
// answer, on every backend and every run.
//
// Hardest first, because that is the one that matters and every caller wants
// it; everything after the speed is there only to break a tie the same way
// twice.
[[nodiscard]] inline bool hardestContactFirst(const ImpactEvent &a, const ImpactEvent &b) {
    if (a.closing_speed_m_s != b.closing_speed_m_s)
        return a.closing_speed_m_s > b.closing_speed_m_s;
    if (a.body_a != b.body_a) return a.body_a < b.body_a;
    if (a.body_b != b.body_b) return a.body_b < b.body_b;
    const Vec3 &pa = a.contact_point_world_m, &pb = b.contact_point_world_m;
    if (pa.x != pb.x) return pa.x < pb.x;
    if (pa.y != pb.y) return pa.y < pb.y;
    if (pa.z != pb.z) return pa.z < pb.z;
    const Vec3 &na = a.normal_a_to_b, &nb = b.normal_a_to_b;
    if (na.x != nb.x) return na.x < nb.x;
    if (na.y != nb.y) return na.y < nb.y;
    if (na.z != nb.z) return na.z < nb.z;
    return a.available_normal_energy_j > b.available_normal_energy_j;
}

} // namespace banjo
