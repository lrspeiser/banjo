#pragma once

#include "physics/ConservativeStep.hpp"
#include <vector>

namespace banjo::detail {
// Only the event controller may defer new contacts while locating first arrival.
// Masked trial states must never be published without geometric event checks.
struct ConservativeContactMask {
    std::vector<bool> support_nodes, sphere_nodes;
    bool sphere_support{};
};
// Shared by the raw solver and the event controller before any impact work.
void validateConservativeState(const ActiveMatter &matter, double dt_s, const Vec3 &gravity_m_s2,
    const CoupledSphereState *sphere, const ConservativeStepSettings &settings);
[[nodiscard]] ConservativeStepResult tryConservativeStepMasked(
    ActiveMatter &matter, double dt_s, const Vec3 &gravity_m_s2,
    CoupledSphereState *sphere, const ConservativeStepSettings &settings,
    const ConservativeContactMask *contacts);
}
