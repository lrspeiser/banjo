#include "physics/CompliantStep.hpp"
#include "physics/ConservativeStepInternal.hpp"
#include "physics/ElasticNewton.hpp"
#include "physics/MechanicalAccounting.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {
bool finite(Vec3 v) { return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z); }
MechanicalTotals measure(const ActiveMatter &matter, const CoupledSphereState *sphere, Vec3 gravity) {
    auto result = measureMaterialMechanics(matter, gravity);
    if (sphere) {
        Mat3 inertia;
        for (unsigned i=0;i<3;++i) inertia.m[i][i] = sphere->inertia_kg_m2;
        result += measureRigidMechanics({sphere->motion,sphere->mass_kg,inertia},gravity);
    }
    return result;
}
}

CompliantStepResult tryCompliantStep(ActiveMatter &matter, double dt, const CompliantStepSettings &settings,
                                    const Vec3 &gravity, CoupledSphereState *sphere) {
    const auto &s = settings.solver;
    detail::validateConservativeState(matter,dt,gravity,sphere,s,true);
    if (!s.global_elastic_solve || !std::isfinite(settings.normal.stiffness_n_m) || settings.normal.stiffness_n_m <= 0 ||
        !std::isfinite(settings.normal.compression_damping_kg_s) || settings.normal.compression_damping_kg_s < 0 ||
        !std::isfinite(settings.maximum_compression_m) || settings.maximum_compression_m <= 0 ||
        !(settings.maximum_residual_work_j>0) || !(settings.maximum_residual_linear_impulse_kg_m_s>0) ||
        !(settings.maximum_residual_angular_impulse_kg_m2_s>0) ||
        (sphere && settings.maximum_compression_m >= sphere->radius_m))
        throw std::invalid_argument("compliant reference requires global solve, positive stiffness/compression bound and nonnegative damping");
    CompliantStepResult result;
    auto &balance = result.balance;
    const std::size_t count = matter.nodes.size();
    std::vector<Vec3> initial, base, velocity, position0;
    std::vector<double> inverse_mass;
    for (const auto &node : matter.nodes) {
        initial.push_back(node.velocity_m_s); position0.push_back(node.position_world_m);
        inverse_mass.push_back(1/node.mass_kg);
    }
    if (sphere) {
        initial.push_back(sphere->motion.linear_velocity_m_s); position0.push_back(sphere->motion.center_of_mass_world_m);
        inverse_mass.push_back(1/sphere->mass_kg);
    }
    for (const auto v : initial) base.push_back(v+dt*gravity);
    velocity = base;
    const auto on_support = [&](Vec3 p) {
        return s.support && insideSupportFootprint(*s.support,p,s.support_half_tangent_m,s.support_half_bitangent_m);
    };
    std::vector<detail::ElasticNormalContact> contacts;
    for (std::size_t i=0;i<position0.size();++i) if (on_support(position0[i])) {
        const double radius = i==count && sphere ? sphere->radius_m : 0;
        contacts.push_back({i,detail::fixed_contact_body,{},s.support->normal_world,
            signedDistanceToPlane(*s.support,position0[i])-radius,0,settings.normal});
    }
    if (sphere) for (std::size_t i=0;i<count;++i) {
        const Vec3 q0 = position0[i]-position0[count];
        contacts.push_back({i,count,q0,{},length(q0)-sphere->radius_m,sphere->radius_m,settings.normal});
    }
    for (const auto &contact : contacts) {
        result.maximum_compression_m = std::max(result.maximum_compression_m,-contact.gap0_m);
        if (result.maximum_compression_m > settings.maximum_compression_m) {
            result.failure = CompliantStepFailure::Compression; return result;
        }
    }
    const auto before = measure(matter,sphere,gravity);
    const double bulk = before.mass_kg>0 ? .5*lengthSquared(before.linear_momentum_kg_m_s)/before.mass_kg : 0;
    const double kinetic = s.support ? before.kinetic_energy_j : std::max(0.0,before.kinetic_energy_j-bulk);
    double initial_contact_energy = 0;
    for (const auto &contact : contacts) {
        const double compression = std::max(0.0,-contact.gap0_m);
        initial_contact_energy += .5*contact.law.stiffness_n_m*compression*compression;
    }
    // A per-node velocity tolerance alone does not bound the summed momentum
    // or work defect. Continue Newton until the residual's physical moments
    // also fit inside half the audit budget, reserving room for roundoff in
    // the independent state-based audit below. Never project the final state.
    const double work_stop = .5*std::min(settings.maximum_residual_work_j,
        s.relative_energy_tolerance*std::max(1.0,kinetic+before.elastic_energy_j+initial_contact_energy));
    const double momentum_stop = .5*std::min(settings.maximum_residual_linear_impulse_kg_m_s,
        s.relative_momentum_tolerance*std::max(1.0,length(before.linear_momentum_kg_m_s)));
    const double angular_stop = .5*std::min(settings.maximum_residual_angular_impulse_kg_m2_s,
        s.relative_momentum_tolerance*std::max(1.0,length(before.angular_momentum_kg_m2_s)));
    const auto solved = [&]() {
        std::vector<Vec3> residual;
        balance.constitutive_velocity_residual_m_s = detail::elasticVelocityResidual(
            matter,dt,initial,base,inverse_mass,velocity,&residual,nullptr,nullptr,&contacts);
        if (!std::isfinite(balance.constitutive_velocity_residual_m_s) ||
            balance.constitutive_velocity_residual_m_s > s.velocity_tolerance_m_s) return false;
        Vec3 momentum, angular; double work=0;
        for (std::size_t i=0;i<velocity.size();++i) {
            const Vec3 impulse = residual[i]/inverse_mass[i], midpoint_velocity=.5*(initial[i]+velocity[i]);
            momentum += impulse;
            angular += cross(position0[i]+.5*dt*midpoint_velocity,impulse);
            work += dot(midpoint_velocity,impulse);
        }
        return length(momentum)<=momentum_stop && length(angular)<=angular_stop && std::abs(work)<=work_stop;
    };
    for (unsigned i=0;i<s.maximum_iterations;++i) {
        if (solved()) break;
        ++balance.iterations;
        if (!detail::elasticNewtonUpdate(matter,dt,initial,base,inverse_mass,velocity,0,
            s.maximum_linear_iterations,balance.linear_iterations,nullptr,&contacts)) break;
    }
    if (!solved()) {
        result.failure = CompliantStepFailure::Convergence; return result;
    }
    std::vector<Vec3> position1;
    for (std::size_t i=0;i<position0.size();++i) {
        position1.push_back(position0[i]+.5*dt*(initial[i]+velocity[i]));
        if (on_support(position0[i]) != on_support(position1[i])) {
            result.failure = CompliantStepFailure::Geometry; return result;
        }
    }
    for (const auto &contact : contacts) {
        const auto e = detail::evaluateElasticContact(contact,initial,velocity,dt);
        if (!e.valid) { result.failure = CompliantStepFailure::Convergence; return result; }
        result.contact_energy_before_j += e.energy_before_j;
        result.contact_energy_after_j += e.energy_after_j;
        result.contact_damping_loss_j += e.damping_loss_j;
        result.maximum_compression_m = std::max(result.maximum_compression_m,e.compression_m);
        if (contact.b == detail::fixed_contact_body) {
            balance.support_impulse_kg_m_s += e.impulse_on_a;
            balance.support_angular_impulse_kg_m2_s += cross(.5*(position0[contact.a]+position1[contact.a]),e.impulse_on_a);
        } else {
            // A chord through the sphere is not a valid shallow compression.
            const Vec3 path = position1[contact.a]-position1[contact.b]-contact.relative0;
            const double t = lengthSquared(path)>0 ? std::clamp(-dot(contact.relative0,path)/lengthSquared(path),0.0,1.0) : 0;
            result.maximum_compression_m = std::max(result.maximum_compression_m,
                contact.sphere_radius_m-length(contact.relative0+t*path));
        }
    }
    if (result.maximum_compression_m > settings.maximum_compression_m) {
        result.failure = CompliantStepFailure::Compression; return result;
    }
    ActiveMatter candidate = matter;
    for (std::size_t i=0;i<count;++i) {
        candidate.nodes[i].position_world_m = position1[i]; candidate.nodes[i].velocity_m_s = velocity[i];
    }
    auto candidate_sphere = sphere ? *sphere : CoupledSphereState{};
    if (sphere) {
        candidate_sphere.motion.center_of_mass_world_m = position1[count];
        candidate_sphere.motion.linear_velocity_m_s = velocity[count];
        candidate_sphere.motion.orientation_world = detail::advanceSphereOrientation(
            sphere->motion.orientation_world,sphere->motion.angular_velocity_rad_s,dt);
    }
    const auto after = measure(candidate,sphere ? &candidate_sphere : nullptr,gravity);
    balance.balance_measured = true;
    balance.energy_residual_j = after.kinetic_energy_j-before.kinetic_energy_j + after.elastic_energy_j-before.elastic_energy_j +
        result.contact_energy_after_j-result.contact_energy_before_j -
        dot(gravity,after.mass_first_moment_kg_m-before.mass_first_moment_kg_m) + result.contact_damping_loss_j;
    const Vec3 gravity_impulse = dt*before.mass_kg*gravity;
    const Vec3 gravity_angular = cross(.5*dt*(before.mass_first_moment_kg_m+after.mass_first_moment_kg_m),gravity);
    balance.linear_momentum_residual_kg_m_s = after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s -
        gravity_impulse-balance.support_impulse_kg_m_s;
    balance.angular_momentum_residual_kg_m2_s = after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s -
        gravity_angular-balance.support_angular_impulse_kg_m2_s;
    const double energy_budget = s.relative_energy_tolerance*std::max(1.0,kinetic+before.elastic_energy_j+result.contact_energy_before_j);
    const double linear_budget = s.relative_momentum_tolerance*std::max({1.0,length(before.linear_momentum_kg_m_s),
        length(gravity_impulse),length(balance.support_impulse_kg_m_s)});
    const double angular_budget = s.relative_momentum_tolerance*std::max({1.0,length(before.angular_momentum_kg_m2_s),
        length(gravity_angular),length(balance.support_angular_impulse_kg_m2_s)});
    balance.converged = std::isfinite(balance.energy_residual_j) && std::abs(balance.energy_residual_j)<=energy_budget &&
        std::isfinite(result.contact_damping_loss_j) && result.contact_damping_loss_j>=0 &&
        finite(balance.linear_momentum_residual_kg_m_s) && length(balance.linear_momentum_residual_kg_m_s)<=linear_budget &&
        finite(balance.angular_momentum_residual_kg_m2_s) && length(balance.angular_momentum_residual_kg_m2_s)<=angular_budget;
    if (!balance.converged) { result.failure = CompliantStepFailure::Balance; return result; }
    matter.nodes = std::move(candidate.nodes);
    if (sphere) *sphere = candidate_sphere;
    return result;
}
}
