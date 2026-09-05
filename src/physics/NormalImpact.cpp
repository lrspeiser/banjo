#include "physics/NormalImpact.hpp"
#include "physics/MechanicalAccounting.hpp"
#include <algorithm>
#include <cmath>
#include <vector>

namespace banjo::detail {
namespace {
struct Contact { std::size_t a, b; Vec3 normal; double initial, target, impulse{}; bool external; };
}
NormalImpactResult tryNormalImpact(ActiveMatter &matter, CoupledSphereState *sphere,
    const ConservativeContactMask &mask, const ConservativeStepSettings &settings, double restitution) {
    NormalImpactResult result;
    const auto count = matter.nodes.size();
    const std::size_t fixed = count + 1;
    std::vector<Vec3> v, position;
    std::vector<double> inverse_mass;
    for (const auto &node : matter.nodes) {
        v.push_back(node.velocity_m_s); position.push_back(node.position_world_m); inverse_mass.push_back(1/node.mass_kg);
    }
    v.push_back(sphere ? sphere->motion.linear_velocity_m_s : Vec3{});
    position.push_back(sphere ? sphere->motion.center_of_mass_world_m : Vec3{});
    inverse_mass.push_back(sphere ? 1/sphere->mass_kg : 0);
    v.push_back({}); position.push_back({}); inverse_mass.push_back(0);
    const auto initial = v;
    std::vector<Contact> contacts;
    const auto add = [&](std::size_t a, std::size_t b, Vec3 n, bool external) {
        const double speed = dot(v[a]-v[b], n);
        contacts.push_back({a, b, n, speed, -restitution*std::min(0.0, speed), 0, external});
    };
    for (std::size_t i = 0; i < count; ++i) {
        if (mask.support_nodes[i]) add(i, fixed, settings.support->normal_world, true);
        if (sphere && mask.sphere_nodes[i]) add(i, count, normalized(position[i]-position[count]), false);
    }
    if (sphere && mask.sphere_support) add(count, fixed, settings.support->normal_world, true);
    bool incoming = false;
    for (const auto &contact : contacts) incoming = incoming || contact.initial < -settings.velocity_tolerance_m_s;
    if (!incoming) { result.converged = true; return result; }
    for (unsigned iteration = 0; iteration < settings.maximum_iterations; ++iteration) {
        double change = 0;
        for (auto &contact : contacts) {
            const double inverse = inverse_mass[contact.a] + inverse_mass[contact.b];
            const double speed = dot(v[contact.a]-v[contact.b], contact.normal);
            const double impulse = std::max(0.0, contact.impulse + (contact.target-speed)/inverse);
            const double delta = impulse-contact.impulse;
            contact.impulse = impulse;
            v[contact.a] += inverse_mass[contact.a]*delta*contact.normal;
            v[contact.b] -= inverse_mass[contact.b]*delta*contact.normal;
            change = std::max(change, inverse*std::abs(delta));
        }
        result.iterations = iteration+1;
        if (change > settings.velocity_tolerance_m_s) continue;
        double residual = 0;
        for (const auto &contact : contacts) {
            const double speed = dot(v[contact.a]-v[contact.b], contact.normal)-contact.target;
            residual = std::max(residual, contact.impulse > 0 ? std::abs(speed) : std::max(0.0,-speed));
        }
        if (residual <= settings.velocity_tolerance_m_s) { result.converged = true; break; }
    }
    if (!result.converged) return result;
    for (const auto &contact : contacts) {
        result.loss_j -= .5*contact.impulse*(contact.initial + dot(v[contact.a]-v[contact.b], contact.normal));
        if (contact.external) {
            const Vec3 impulse = contact.impulse*contact.normal;
            result.support_impulse += impulse;
            result.support_angular_impulse += cross(position[contact.a], impulse);
        }
        result.applied = result.applied || contact.impulse > 0;
    }
    double kinetic_before = 0, kinetic_change = 0;
    Vec3 momentum_before, angular_before, momentum_change, angular_change;
    for (std::size_t i = 0; i <= count; ++i) if (inverse_mass[i] > 0) {
        const double mass = 1/inverse_mass[i];
        kinetic_before += .5*mass*lengthSquared(initial[i]);
        kinetic_change += .5*mass*(lengthSquared(v[i])-lengthSquared(initial[i]));
        const Vec3 p = mass*initial[i], delta_p = mass*(v[i]-initial[i]);
        momentum_before += p; angular_before += cross(position[i],p);
        momentum_change += delta_p; angular_change += cross(position[i],delta_p);
    }
    const double energy_budget = settings.relative_energy_tolerance*std::max(1.0,kinetic_before);
    result.converged = std::isfinite(result.loss_j) && result.loss_j >= -energy_budget &&
        std::abs(kinetic_change+result.loss_j) <= energy_budget &&
        length(momentum_change-result.support_impulse) <= settings.relative_momentum_tolerance*std::max({1.0,length(momentum_before),length(result.support_impulse)}) &&
        length(angular_change-result.support_angular_impulse) <= settings.relative_momentum_tolerance*std::max({1.0,length(angular_before),length(result.support_angular_impulse)});
    if (result.converged) {
        for (std::size_t i = 0; i < count; ++i) matter.nodes[i].velocity_m_s = v[i];
        if (sphere) sphere->motion.linear_velocity_m_s = v[count];
    }
    return result;
}
}
