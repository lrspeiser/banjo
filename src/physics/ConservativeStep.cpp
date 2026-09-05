#include "physics/ConservativeStep.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "physics/ElasticNewton.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace banjo {
namespace {
bool finite(Vec3 v) { return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z); }

Quat advanceSphereOrientation(Quat q, Vec3 omega, double dt) {
    const double speed = length(omega), half_angle = .5 * dt * speed;
    const double scale = speed > 1e-14 ? std::sin(half_angle) / speed : .5 * dt;
    const Quat delta{std::cos(half_angle), scale * omega.x, scale * omega.y, scale * omega.z};
    Quat result{delta.w*q.w - delta.x*q.x - delta.y*q.y - delta.z*q.z,
        delta.w*q.x + delta.x*q.w + delta.y*q.z - delta.z*q.y,
        delta.w*q.y - delta.x*q.z + delta.y*q.w + delta.z*q.x,
        delta.w*q.z + delta.x*q.y - delta.y*q.x + delta.z*q.w};
    const double norm = std::sqrt(result.w*result.w + result.x*result.x + result.y*result.y + result.z*result.z);
    return {result.w/norm, result.x/norm, result.y/norm, result.z/norm};
}

// Discrete gradient of U(q)= (|q|-L)^2/(2*c). Its work is exactly U1-U0,
// and the force is parallel to q0+q1, preserving midpoint angular momentum.
Vec3 bondImpulse(Vec3 q0, Vec3 q1, double rest, double compliance, double dt) {
    const double sum = length(q0) + length(q1);
    if (sum <= 1e-15) throw std::invalid_argument("collapsed spring endpoints");
    return (-.5 * dt / compliance * ((sum - 2 * rest) / sum)) * (q0 + q1);
}

// Exact local nonlinear solve with all other impulses held fixed. The vector
// midpoint edge is parallel to d, reducing the solve to one scalar root.
Vec3 localBondImpulse(Vec3 q0, Vec3 velocity0, Vec3 base_velocity,
                      double inverse_mass, const BondRest &bond, double dt) {
    const Vec3 d = 2 * q0 + .5 * dt * (velocity0 + base_velocity);
    const double r0 = length(q0);
    const double a = .25 * dt * dt * inverse_mass / bond.compliance;
    const auto equation = [&](double s) {
        const double sum = r0 + length(s * d - q0);
        return s * (1 + a * ((sum - 2 * bond.rest_length_m) / sum)) - 1;
    };
    double lo = 0, hi = 1;
    for (unsigned i = 0; equation(hi) < 0 && i < 40; ++i) hi *= 2;
    if (!std::isfinite(equation(hi)) || equation(hi) < 0)
        throw std::runtime_error("could not bracket conservative spring solve");
    for (unsigned i = 0; i < 64; ++i) {
        const double mid = .5 * (lo + hi);
        if (mid == lo || mid == hi) break;
        if (equation(mid) < 0) lo = mid; else hi = mid;
    }
    return bondImpulse(q0, (.5 * (lo + hi)) * d - q0,
                       bond.rest_length_m, bond.compliance, dt);
}

MechanicalTotals measure(const ActiveMatter &matter, const CoupledSphereState *sphere, Vec3 gravity) {
    auto totals = measureMaterialMechanics(matter, gravity);
    if (sphere) {
        Mat3 inertia;
        for (unsigned i = 0; i < 3; ++i) inertia.m[i][i] = sphere->inertia_kg_m2;
        totals += measureRigidMechanics({sphere->motion, sphere->mass_kg, inertia}, gravity);
    }
    return totals;
}
}

ConservativeStepResult tryConservativeStep(ActiveMatter &matter, double dt, const Vec3 &gravity,
    CoupledSphereState *sphere, const ConservativeStepSettings &settings) {
    if (!matter.asset || matter.bonds.size() != matter.asset->bonds.size() ||
        !std::isfinite(dt) || dt <= 0 || !finite(gravity) || settings.maximum_iterations == 0 ||
        settings.maximum_linear_iterations == 0 ||
        !std::isfinite(settings.velocity_tolerance_m_s) || settings.velocity_tolerance_m_s <= 0 ||
        !std::isfinite(settings.relative_energy_tolerance) || settings.relative_energy_tolerance <= 0 ||
        !std::isfinite(settings.relative_momentum_tolerance) || settings.relative_momentum_tolerance <= 0 ||
        !std::isfinite(settings.contact_tolerance_m) || settings.contact_tolerance_m < 0)
        throw std::invalid_argument("invalid conservative step settings/state");
    if (settings.support && (!finite(settings.support->point_world_m) ||
        !finite(settings.support->normal_world) || std::abs(lengthSquared(settings.support->normal_world) - 1) > 1e-12))
        throw std::invalid_argument("support requires a finite point and unit normal");
    const std::size_t count = matter.nodes.size();
    std::vector<Vec3> v0(count), velocity(count), bond_impulses(matter.bonds.size()), contact_impulses(count);
    std::vector<double> inverse_mass(count), support_impulses(count);
    std::vector<bool> supported(count);
    const auto on_support = [&](Vec3 position) {
        return settings.support && insideSupportFootprint(*settings.support, position,
            settings.support_half_tangent_m, settings.support_half_bitangent_m);
    };
    for (std::size_t i = 0; i < count; ++i) {
        const auto &node = matter.nodes[i];
        if (!finite(node.position_world_m) || !finite(node.velocity_m_s) ||
            !finite(node.spin_angular_velocity_rad_s) ||
            !std::isfinite(node.mass_kg) || node.mass_kg <= 0)
            throw std::invalid_argument("conservative reference requires finite positive-mass nodes");
        inverse_mass[i] = 1 / node.mass_kg;
        v0[i] = node.velocity_m_s;
        velocity[i] = v0[i] + dt * gravity;
        supported[i] = on_support(node.position_world_m);
        if (supported[i] && signedDistanceToPlane(*settings.support, node.position_world_m) < -settings.contact_tolerance_m)
            throw std::invalid_argument("initial material/support overlap needs a valid initial state");
    }
    for (std::size_t i = 0; i < matter.bonds.size(); ++i) {
        if (!matter.bonds[i].alive) continue;
        const auto &bond = matter.asset->bonds[i];
        if (bond.node_a >= count || bond.node_b >= count || bond.node_a == bond.node_b ||
            !std::isfinite(bond.compliance) || bond.compliance <= 0 ||
            !std::isfinite(bond.rest_length_m) || bond.rest_length_m <= 0)
            throw std::invalid_argument("invalid live spring for conservative reference");
    }
    CoupledSphereState candidate_sphere = sphere ? *sphere : CoupledSphereState{};
    const Vec3 sphere_v0 = candidate_sphere.motion.linear_velocity_m_s;
    Vec3 sphere_velocity = sphere_v0 + dt * gravity;
    double inverse_sphere_mass = 0, sphere_support_impulse = 0;
    bool sphere_supported = false;
    if (sphere) {
        const auto q = sphere->motion.orientation_world;
        const double qnorm2 = q.w*q.w + q.x*q.x + q.y*q.y + q.z*q.z;
        if (!finite(sphere->motion.center_of_mass_world_m) || !finite(sphere_v0) ||
            !finite(sphere->motion.angular_velocity_rad_s) || !std::isfinite(qnorm2) || std::abs(qnorm2 - 1) > 1e-8 ||
            !std::isfinite(sphere->mass_kg) || sphere->mass_kg <= 0 ||
            !std::isfinite(sphere->radius_m) || sphere->radius_m <= 0 ||
            !std::isfinite(sphere->inertia_kg_m2) || sphere->inertia_kg_m2 <= 0)
            throw std::invalid_argument("invalid sphere for conservative reference");
        inverse_sphere_mass = 1 / sphere->mass_kg;
        for (const auto &node : matter.nodes)
            if (length(node.position_world_m - sphere->motion.center_of_mass_world_m) <
                sphere->radius_m - settings.contact_tolerance_m)
                throw std::invalid_argument("initial sphere/material overlap needs a valid initial state");
        sphere_supported = on_support(sphere->motion.center_of_mass_world_m);
        if (sphere_supported && signedDistanceToPlane(*settings.support, sphere->motion.center_of_mass_world_m) <
            sphere->radius_m - settings.contact_tolerance_m)
            throw std::invalid_argument("initial sphere/support overlap needs a valid initial state");
    }
    const auto before = measure(matter, sphere, gravity);
    ConservativeStepResult result;
    const auto position = [&](std::size_t i) {
        return matter.nodes[i].position_world_m + .5 * dt * (v0[i] + velocity[i]);
    };
    const auto sphere_position = [&]() {
        return candidate_sphere.motion.center_of_mass_world_m + .5 * dt * (sphere_v0 + sphere_velocity);
    };
    detail::ElasticSupport elastic_support;
    const bool coupled_support = settings.global_elastic_solve && settings.global_support_solve && settings.support;
    if (coupled_support) {
        elastic_support.normal = settings.support->normal_world;
        elastic_support.minimum_velocity.resize(count, -std::numeric_limits<double>::infinity());
        for (std::size_t i = 0; i < count; ++i) if (supported[i])
            elastic_support.minimum_velocity[i] = -dot(v0[i], elastic_support.normal) -
                2 * signedDistanceToPlane(*settings.support, matter.nodes[i].position_world_m) / dt;
    }
    const auto *support_constraint = coupled_support ? &elastic_support : nullptr;
    const auto elastic_base = [&]() {
        std::vector<Vec3> base(count);
        for (std::size_t i = 0; i < count; ++i) {
            base[i] = v0[i] + dt * gravity + inverse_mass[i] * contact_impulses[i];
            if (supported[i] && !coupled_support) base[i] += inverse_mass[i] * support_impulses[i] * settings.support->normal_world;
        }
        return base;
    };
    for (unsigned iteration = 0; iteration < settings.maximum_iterations; ++iteration) {
        double change = 0;
        if (settings.global_elastic_solve) {
            const auto previous_velocity = velocity;
            if (!detail::elasticNewtonUpdate(matter, dt, v0, elastic_base(), inverse_mass, velocity,
                    settings.velocity_tolerance_m_s, settings.maximum_linear_iterations, result.linear_iterations, support_constraint)) {
                result.iterations = iteration + 1;
                result.constitutive_velocity_residual_m_s = detail::elasticVelocityResidual(
                    matter, dt, v0, elastic_base(), inverse_mass, velocity, nullptr, support_constraint);
                return result;
            }
            for (std::size_t i = 0; i < count; ++i)
                change = std::max(change, length(velocity[i] - previous_velocity[i]));
        } else for (std::size_t i = 0; i < matter.bonds.size(); ++i) {
            if (!matter.bonds[i].alive) continue;
            const auto &bond = matter.asset->bonds[i];
            const auto a = bond.node_a, b = bond.node_b;
            velocity[a] += inverse_mass[a] * bond_impulses[i];
            velocity[b] -= inverse_mass[b] * bond_impulses[i];
            const Vec3 impulse = localBondImpulse(matter.nodes[b].position_world_m - matter.nodes[a].position_world_m,
                v0[b] - v0[a], velocity[b] - velocity[a], inverse_mass[a] + inverse_mass[b], bond, dt);
            change = std::max(change, (inverse_mass[a] + inverse_mass[b]) * length(impulse - bond_impulses[i]));
            bond_impulses[i] = impulse;
            velocity[a] -= inverse_mass[a] * impulse;
            velocity[b] += inverse_mass[b] * impulse;
        }
        if (sphere) for (std::size_t i = 0; i < count; ++i) {
            velocity[i] -= inverse_mass[i] * contact_impulses[i];
            sphere_velocity += inverse_sphere_mass * contact_impulses[i];
            const Vec3 q0 = matter.nodes[i].position_world_m - sphere->motion.center_of_mass_world_m;
            const Vec3 predicted = q0 + .5 * dt * (v0[i] - sphere_v0 + velocity[i] - sphere_velocity);
            Vec3 impulse;
            if (lengthSquared(predicted) < sphere->radius_m * sphere->radius_m) {
                const Vec3 normal = normalized(q0 + predicted);
                const double projection = dot(predicted, normal);
                const double distance = -projection + std::sqrt(std::max(0.0,
                    projection * projection + sphere->radius_m * sphere->radius_m - lengthSquared(predicted)));
                impulse = (2 * distance / (dt * (inverse_mass[i] + inverse_sphere_mass))) * normal;
            }
            change = std::max(change, (inverse_mass[i] + inverse_sphere_mass) * length(impulse - contact_impulses[i]));
            contact_impulses[i] = impulse;
            velocity[i] += inverse_mass[i] * impulse;
            sphere_velocity -= inverse_sphere_mass * impulse;
        }
        if (settings.support) {
            const auto normal = settings.support->normal_world;
            if (coupled_support) {
                std::vector<Vec3> free_residual;
                const double residual = detail::elasticVelocityResidual(matter, dt, v0, elastic_base(),
                    inverse_mass, velocity, &free_residual);
                if (!std::isfinite(residual)) return result;
                for (std::size_t i = 0; i < count; ++i) if (supported[i]) {
                    const double reaction = dot(free_residual[i], normal);
                    const double gap_velocity = dot(velocity[i], normal) - elastic_support.minimum_velocity[i];
                    // Recover the support reaction from the solved momentum
                    // equation; do not apply a second impulse or position edit.
                    support_impulses[i] = reaction > gap_velocity ? std::max(0.0, reaction) / inverse_mass[i] : 0;
                }
            } else for (std::size_t i = 0; i < count; ++i) if (supported[i]) {
                velocity[i] -= inverse_mass[i] * support_impulses[i] * normal;
                const double impulse = std::max(0.0, -2 * signedDistanceToPlane(*settings.support, position(i)) /
                    (dt * inverse_mass[i]));
                change = std::max(change, inverse_mass[i] * std::abs(impulse - support_impulses[i]));
                support_impulses[i] = impulse;
                velocity[i] += inverse_mass[i] * impulse * normal;
            }
            if (sphere_supported) {
                sphere_velocity -= inverse_sphere_mass * sphere_support_impulse * normal;
                const double gap = signedDistanceToPlane(*settings.support, sphere_position()) - sphere->radius_m;
                const double impulse = std::max(0.0, -2 * gap / (dt * inverse_sphere_mass));
                change = std::max(change, inverse_sphere_mass * std::abs(impulse - sphere_support_impulse));
                sphere_support_impulse = impulse;
                sphere_velocity += inverse_sphere_mass * impulse * normal;
            }
        }
        result.iterations = iteration + 1;
        result.constitutive_velocity_residual_m_s = change;
        if (change > settings.velocity_tolerance_m_s) continue;
        double residual = 0;
        if (settings.global_elastic_solve) {
            residual = detail::elasticVelocityResidual(matter, dt, v0, elastic_base(), inverse_mass, velocity, nullptr, support_constraint);
        } else for (std::size_t i = 0; i < matter.bonds.size(); ++i) {
            if (!matter.bonds[i].alive) continue;
            const auto &bond = matter.asset->bonds[i];
            const Vec3 expected = bondImpulse(matter.nodes[bond.node_b].position_world_m - matter.nodes[bond.node_a].position_world_m,
                position(bond.node_b) - position(bond.node_a), bond.rest_length_m, bond.compliance, dt);
            residual = std::max(residual, (inverse_mass[bond.node_a] + inverse_mass[bond.node_b]) * length(expected - bond_impulses[i]));
        }
        result.constitutive_velocity_residual_m_s = residual;
        if (residual <= settings.velocity_tolerance_m_s) { result.converged = true; break; }
    }
    if (!result.converged) return result;
    ActiveMatter candidate = matter;
    bool footprint_unchanged = true;
    for (std::size_t i = 0; i < count; ++i) {
        candidate.nodes[i].previous_position_world_m = matter.nodes[i].position_world_m;
        candidate.nodes[i].position_world_m = position(i);
        candidate.nodes[i].velocity_m_s = velocity[i];
        footprint_unchanged = footprint_unchanged && on_support(position(i)) == supported[i];
        if (sphere) {
            result.normal_contact_loss_j -= dot(contact_impulses[i], .5 * (v0[i] - sphere_v0 + velocity[i] - sphere_velocity));
            result.maximum_penetration_m = std::max(result.maximum_penetration_m,
                sphere->radius_m - length(position(i) - sphere_position()));
            // A large step must not tunnel through and finish on the far side.
            // Reject it so the caller can retry with a shorter interval.
            const Vec3 q0 = matter.nodes[i].position_world_m - sphere->motion.center_of_mass_world_m;
            const Vec3 path = position(i) - sphere_position() - q0;
            const double fraction = lengthSquared(path) > 0
                ? std::clamp(-dot(q0, path) / lengthSquared(path), 0.0, 1.0) : 0.0;
            result.maximum_penetration_m = std::max(result.maximum_penetration_m,
                sphere->radius_m - length(q0 + fraction * path));
        }
        if (supported[i]) {
            const Vec3 impulse = support_impulses[i] * settings.support->normal_world;
            result.normal_contact_loss_j -= dot(impulse, .5 * (v0[i] + velocity[i]));
            result.support_impulse_kg_m_s += impulse;
            result.support_angular_impulse_kg_m2_s += cross(.5 * (matter.nodes[i].position_world_m + position(i)), impulse);
            result.maximum_penetration_m = std::max(result.maximum_penetration_m,
                -signedDistanceToPlane(*settings.support, position(i)));
        }
    }
    if (sphere) {
        footprint_unchanged = footprint_unchanged && on_support(sphere_position()) == sphere_supported;
        if (sphere_supported) {
            const Vec3 impulse = sphere_support_impulse * settings.support->normal_world;
            result.normal_contact_loss_j -= dot(impulse, .5 * (sphere_v0 + sphere_velocity));
            result.support_impulse_kg_m_s += impulse;
            result.support_angular_impulse_kg_m2_s += cross(.5 * (sphere->motion.center_of_mass_world_m + sphere_position()), impulse);
            result.maximum_penetration_m = std::max(result.maximum_penetration_m,
                sphere->radius_m - signedDistanceToPlane(*settings.support, sphere_position()));
        }
        candidate_sphere.motion.center_of_mass_world_m = sphere_position();
        candidate_sphere.motion.linear_velocity_m_s = sphere_velocity;
        // Isotropic sphere spin is constant under the normal forces here.
        candidate_sphere.motion.orientation_world = advanceSphereOrientation(
            sphere->motion.orientation_world, sphere->motion.angular_velocity_rad_s, dt);
    }
    const auto after = measure(candidate, sphere ? &candidate_sphere : nullptr, gravity);
    result.balance_measured = true;
    result.energy_residual_j = after.kinetic_energy_j - before.kinetic_energy_j +
        after.elastic_energy_j - before.elastic_energy_j -
        dot(gravity, after.mass_first_moment_kg_m - before.mass_first_moment_kg_m) + result.normal_contact_loss_j;
    const Vec3 gravity_impulse = (dt * before.mass_kg) * gravity;
    const Vec3 gravity_angular_impulse = cross(.5 * dt *
        (before.mass_first_moment_kg_m + after.mass_first_moment_kg_m), gravity);
    result.linear_momentum_residual_kg_m_s = after.linear_momentum_kg_m_s - before.linear_momentum_kg_m_s -
        gravity_impulse - result.support_impulse_kg_m_s;
    result.angular_momentum_residual_kg_m2_s = after.angular_momentum_kg_m2_s - before.angular_momentum_kg_m2_s -
        gravity_angular_impulse - result.support_angular_impulse_kg_m2_s;
    // Potential's arbitrary zero must not loosen the error budget. A stationary
    // support gives a preferred frame; isolated bodies use internal kinetic energy.
    const double bulk_kinetic = before.mass_kg > 0
        ? .5 * lengthSquared(before.linear_momentum_kg_m_s) / before.mass_kg : 0;
    const double kinetic_scale = settings.support ? before.kinetic_energy_j
        : std::max(0.0, before.kinetic_energy_j - bulk_kinetic);
    const double energy_budget = settings.relative_energy_tolerance * std::max(1.0, kinetic_scale + before.elastic_energy_j);
    const double linear_budget = settings.relative_momentum_tolerance * std::max({1.0,
        length(before.linear_momentum_kg_m_s), length(gravity_impulse), length(result.support_impulse_kg_m_s)});
    const double angular_budget = settings.relative_momentum_tolerance * std::max({1.0,
        length(before.angular_momentum_kg_m2_s), length(gravity_angular_impulse), length(result.support_angular_impulse_kg_m2_s)});
    result.converged = std::isfinite(result.energy_residual_j) &&
        footprint_unchanged &&
        std::abs(result.energy_residual_j) <= energy_budget && result.normal_contact_loss_j >= -energy_budget &&
        finite(result.linear_momentum_residual_kg_m_s) && length(result.linear_momentum_residual_kg_m_s) <= linear_budget &&
        finite(result.angular_momentum_residual_kg_m2_s) && length(result.angular_momentum_residual_kg_m2_s) <= angular_budget &&
        result.maximum_penetration_m <= settings.contact_tolerance_m;
    if (result.converged) {
        matter.nodes = std::move(candidate.nodes);
        if (sphere) *sphere = candidate_sphere;
    }
    return result;
}
} // namespace banjo
