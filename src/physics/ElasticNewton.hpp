#pragma once

#include "fracture/ActiveMatter.hpp"
#include <vector>

namespace banjo::detail {
// Internal matrix-free Newton update for the same discrete-gradient bond law.
// Contact/support impulses are held in base_velocity for this update.
[[nodiscard]] double elasticVelocityResidual(const ActiveMatter &matter, double dt,
    const std::vector<Vec3> &initial_velocity, const std::vector<Vec3> &base_velocity,
    const std::vector<double> &inverse_mass, const std::vector<Vec3> &velocity,
    std::vector<Vec3> *residual = nullptr);

[[nodiscard]] bool elasticNewtonUpdate(const ActiveMatter &matter, double dt,
    const std::vector<Vec3> &initial_velocity, const std::vector<Vec3> &base_velocity,
    const std::vector<double> &inverse_mass, std::vector<Vec3> &velocity,
    double velocity_tolerance, unsigned maximum_linear_iterations, unsigned &linear_iterations);
}
