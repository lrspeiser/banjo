#pragma once

#include "fracture/ActiveMatter.hpp"
#include "physics/NormalCompliance.hpp"
#include <vector>

namespace banjo::detail {
// One static plane expressed as lower bounds on endpoint normal velocity.
// The bound is -v0.n - 2*initial_gap/dt; -infinity excludes a node.
struct ElasticSupport {
    Vec3 normal;
    std::vector<double> minimum_velocity;
};
// Internal matrix-free Newton update for the same discrete-gradient bond law.
// Other contact impulses are held in base_velocity. When support is supplied,
// its unilateral reaction is solved with elasticity and excluded from base.
[[nodiscard]] double elasticVelocityResidual(const ActiveMatter &matter, double dt,
    const std::vector<Vec3> &initial_velocity, const std::vector<Vec3> &base_velocity,
    const std::vector<double> &inverse_mass, const std::vector<Vec3> &velocity,
    std::vector<Vec3> *residual = nullptr, const ElasticSupport *support = nullptr,
    std::vector<bool> *active_support = nullptr,
    const std::vector<ElasticNormalContact> *normal_contacts = nullptr);

[[nodiscard]] bool elasticNewtonUpdate(const ActiveMatter &matter, double dt,
    const std::vector<Vec3> &initial_velocity, const std::vector<Vec3> &base_velocity,
    const std::vector<double> &inverse_mass, std::vector<Vec3> &velocity,
    double velocity_tolerance, unsigned maximum_linear_iterations, unsigned &linear_iterations,
    const ElasticSupport *support = nullptr,
    const std::vector<ElasticNormalContact> *normal_contacts = nullptr);
}
