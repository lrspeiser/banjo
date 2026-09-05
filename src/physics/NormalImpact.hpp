#pragma once
#include "physics/ConservativeStepInternal.hpp"
namespace banjo::detail {
struct NormalImpactResult {
    bool converged{};
    unsigned iterations{};
    double loss_j{};
    Vec3 support_impulse, support_angular_impulse;
    bool applied{};
};
// Instantaneous frictionless Newton restitution for contacts at their event
// positions. Every finite participant receives its reaction. Energy-increasing
// or unresolved simultaneous impact configurations are rejected unchanged.
[[nodiscard]] NormalImpactResult tryNormalImpact(ActiveMatter &matter, CoupledSphereState *sphere,
    const ConservativeContactMask &contacts, const ConservativeStepSettings &settings, double restitution);
}
