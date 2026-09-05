#include "physics/CompliantAdvance.hpp"
#include "physics/ConservativeStepInternal.hpp"
#include "physics/MechanicalAccounting.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace banjo {
namespace {
bool positive(double x) { return std::isfinite(x) && x>0; }
bool finite(Vec3 v) { return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z); }
MechanicalTotals measure(const ActiveMatter &matter, const CoupledSphereState *sphere, Vec3 gravity) {
    auto result=measureMaterialMechanics(matter,gravity);
    if (sphere) {
        Mat3 inertia; for (unsigned i=0;i<3;++i) inertia.m[i][i]=sphere->inertia_kg_m2;
        result+=measureRigidMechanics({sphere->motion,sphere->mass_kg,inertia},gravity);
    }
    return result;
}
Vec3 massMoment(const ActiveMatter &matter, const CoupledSphereState *sphere) {
    Vec3 result;
    for (const auto &node:matter.nodes) result+=node.mass_kg*node.position_world_m;
    if (sphere) result+=sphere->mass_kg*sphere->motion.center_of_mass_world_m;
    return result;
}
double contactEnergy(const ActiveMatter &matter,const CoupledSphereState *sphere,const CompliantStepSettings &settings) {
    double result=0;
    const auto &s=settings.solver;
    const auto add=[&](double gap) { const double compression=std::max(0.0,-gap); result+=.5*settings.normal.stiffness_n_m*compression*compression; };
    const auto support=[&](Vec3 p,double radius) {
        if (s.support && insideSupportFootprint(*s.support,p,s.support_half_tangent_m,s.support_half_bitangent_m))
            add(signedDistanceToPlane(*s.support,p)-radius);
    };
    for (const auto &node:matter.nodes) {
        support(node.position_world_m,0);
        if (sphere) add(length(node.position_world_m-sphere->motion.center_of_mass_world_m)-sphere->radius_m);
    }
    if (sphere) support(sphere->motion.center_of_mass_world_m,sphere->radius_m);
    return result;
}
double energyScale(const MechanicalTotals &state,double contact,const ConservativeStepSettings &s) {
    const double bulk=state.mass_kg>0 ? .5*lengthSquared(state.linear_momentum_kg_m_s)/state.mass_kg : 0;
    const double kinetic=s.support ? state.kinetic_energy_j : std::max(0.0,state.kinetic_energy_j-bulk);
    return std::max(1.0,kinetic+state.elastic_energy_j+contact);
}
CompliantErrorEstimate compare(const ActiveMatter &coarse, const ActiveMatter &fine,
    const CoupledSphereState *coarse_sphere, const CoupledSphereState *fine_sphere,
    double damping_difference, double h, const CompliantErrorLimits &limits) {
    CompliantErrorEstimate result;
    for (std::size_t i=0;i<coarse.nodes.size();++i) {
        result.position_m=std::max(result.position_m,length(coarse.nodes[i].position_world_m-fine.nodes[i].position_world_m));
        result.velocity_m_s=std::max(result.velocity_m_s,length(coarse.nodes[i].velocity_m_s-fine.nodes[i].velocity_m_s));
    }
    for (std::size_t i=0;i<coarse.bonds.size();++i) if (coarse.bonds[i].alive) {
        const auto &bond=coarse.asset->bonds[i];
        const auto a=bond.node_a,b=bond.node_b;
        const double first=length(coarse.nodes[a].position_world_m-coarse.nodes[b].position_world_m);
        const double second=length(fine.nodes[a].position_world_m-fine.nodes[b].position_world_m);
        result.bond_strain=std::max(result.bond_strain,std::abs(first-second)/bond.rest_length_m);
    }
    if (coarse_sphere) {
        result.position_m=std::max(result.position_m,length(coarse_sphere->motion.center_of_mass_world_m-fine_sphere->motion.center_of_mass_world_m));
        result.velocity_m_s=std::max(result.velocity_m_s,length(coarse_sphere->motion.linear_velocity_m_s-fine_sphere->motion.linear_velocity_m_s));
        // Normal forces leave isotropic sphere spin unchanged. Both paths use
        // the same exact constant-spin rotation, up to quaternion roundoff.
    }
    result.damping_work_j=std::abs(damping_difference);
    result.normalized=limits.reference_time_s/h*std::max({result.position_m/limits.position_m,
        result.velocity_m_s/limits.velocity_m_s,result.bond_strain/limits.bond_strain,
        result.damping_work_j/limits.damping_work_j});
    return result;
}
}

CompliantAdvanceResult tryCompliantAdvance(ActiveMatter &matter, double dt,
    const CompliantAdvanceSettings &settings, const Vec3 &gravity, CoupledSphereState *sphere) {
    const auto &limits=settings.error;
    if (!positive(dt) || !positive(limits.position_m) || !positive(limits.velocity_m_s) ||
        !positive(limits.bond_strain) || !positive(limits.damping_work_j) || !positive(limits.reference_time_s) ||
        !positive(settings.initial_trial_dt_s) || !positive(settings.maximum_trial_dt_s) ||
        !positive(settings.minimum_trial_dt_s) || settings.minimum_trial_dt_s>settings.maximum_trial_dt_s ||
        settings.initial_trial_dt_s<settings.minimum_trial_dt_s || settings.initial_trial_dt_s>settings.maximum_trial_dt_s ||
        settings.maximum_trials==0)
        throw std::invalid_argument("invalid compliant time/error bounds");
    detail::validateConservativeState(matter,dt,gravity,sphere,settings.step.solver,true);
    CompliantAdvanceResult result;
    result.remaining_time_s=dt;
    result.suggested_trial_dt_s=settings.initial_trial_dt_s;
    const auto before=measure(matter,sphere,gravity);
    const auto &original_solver=settings.step.solver;
    const double interval_energy_budget=original_solver.relative_energy_tolerance*
        energyScale(before,contactEnergy(matter,sphere,settings.step),original_solver);
    const double interval_momentum_budget=original_solver.relative_momentum_tolerance*std::max(1.0,length(before.linear_momentum_kg_m_s));
    const double interval_angular_budget=original_solver.relative_momentum_tolerance*std::max(1.0,length(before.angular_momentum_kg_m2_s));
    ActiveMatter working=matter;
    auto working_sphere=sphere ? *sphere : CoupledSphereState{};
    Vec3 moment=before.mass_first_moment_kg_m,gravity_angular;
    double h=std::min(dt,settings.initial_trial_dt_s);
    const auto solve=[&](ActiveMatter &state,CoupledSphereState &body,double interval) {
        if (result.trials>=settings.maximum_trials) {
            result.failure=CompliantAdvanceFailure::TrialBudget;
            return CompliantStepResult{};
        }
        ++result.trials;
        auto local=settings.step;
        // Allocate part of the whole-interval audit budget to each physical
        // substep. A fixed per-substep tolerance could accumulate excessive
        // drift as accuracy control adds thousands of very small steps.
        // Reserve a duration-proportional share and a bounded per-trial share
        // for tiny final remainders. These tighten equation residuals only;
        // rounded state sums keep their original independent audit tolerances.
        // Accepted durations sum to dt and accepted physical steps cannot
        // exceed maximum_trials: the shares total at most half the budget.
        const double share=.25*(interval/dt+1.0/settings.maximum_trials);
        local.maximum_residual_work_j=std::min(local.maximum_residual_work_j,share*interval_energy_budget);
        local.maximum_residual_linear_impulse_kg_m_s=std::min(local.maximum_residual_linear_impulse_kg_m_s,share*interval_momentum_budget);
        local.maximum_residual_angular_impulse_kg_m2_s=std::min(local.maximum_residual_angular_impulse_kg_m2_s,share*interval_angular_budget);
        auto trial=tryCompliantStep(state,interval,local,gravity,sphere ? &body : nullptr);
        result.last_trial=trial;
        result.step.balance.iterations+=trial.balance.iterations;
        result.step.balance.linear_iterations+=trial.balance.linear_iterations;
        return trial;
    };
    while (result.remaining_time_s>0) {
        h=std::min(h,result.remaining_time_s);
        result.last_trial_dt_s=h;
        if (.5*h<=0 || (h<result.remaining_time_s && result.remaining_time_s-h==result.remaining_time_s)) {
            result.failure=CompliantAdvanceFailure::StepLimit; return result;
        }
        result.last_error={};
        ActiveMatter coarse=working, fine=working;
        auto coarse_sphere=working_sphere, fine_sphere=working_sphere;
        const auto c=solve(coarse,coarse_sphere,h);
        bool accepted=false;
        CompliantStepResult a,b;
        Vec3 middle_moment,end_moment;
        if (c.balance.converged) {
            a=solve(fine,fine_sphere,.5*h);
            if (a.balance.converged) {
                middle_moment=massMoment(fine,sphere ? &fine_sphere : nullptr);
                b=solve(fine,fine_sphere,.5*h);
                if (b.balance.converged) {
                    end_moment=massMoment(fine,sphere ? &fine_sphere : nullptr);
                    result.last_error=compare(coarse,fine,sphere ? &coarse_sphere : nullptr,sphere ? &fine_sphere : nullptr,
                        c.contact_damping_loss_j-a.contact_damping_loss_j-b.contact_damping_loss_j,h,limits);
                    accepted=std::isfinite(result.last_error.normalized) && result.last_error.normalized<=1;
                }
            }
        }
        if (result.failure==CompliantAdvanceFailure::TrialBudget) return result;
        if (!accepted) {
            ++result.rejected_segments;
            const double factor=result.last_error.normalized>1 && std::isfinite(result.last_error.normalized) ?
                std::clamp(.8/std::sqrt(result.last_error.normalized),.25,.5) : .5;
            const double shorter=h*factor;
            if (shorter<settings.minimum_trial_dt_s || shorter<=0 || shorter==h) {
                result.failure=CompliantAdvanceFailure::StepLimit; return result;
            }
            h=shorter;
            continue;
        }
        if (result.accepted_segments==0) result.step.contact_energy_before_j=a.contact_energy_before_j;
        ++result.accepted_segments;
        result.step.contact_energy_after_j=b.contact_energy_after_j;
        result.step.contact_damping_loss_j+=a.contact_damping_loss_j+b.contact_damping_loss_j;
        result.step.maximum_compression_m=std::max({result.step.maximum_compression_m,a.maximum_compression_m,b.maximum_compression_m});
        result.step.balance.support_impulse_kg_m_s+=a.balance.support_impulse_kg_m_s+b.balance.support_impulse_kg_m_s;
        result.step.balance.support_angular_impulse_kg_m2_s+=a.balance.support_angular_impulse_kg_m2_s+b.balance.support_angular_impulse_kg_m2_s;
        result.step.balance.constitutive_velocity_residual_m_s=std::max({result.step.balance.constitutive_velocity_residual_m_s,
            a.balance.constitutive_velocity_residual_m_s,b.balance.constitutive_velocity_residual_m_s});
        gravity_angular+=cross(.25*h*(moment+2*middle_moment+end_moment),gravity);
        moment=end_moment;
        working.nodes=std::move(fine.nodes);
        working_sphere=fine_sphere;
        result.minimum_accepted_step_s=result.minimum_accepted_step_s>0 ? std::min(result.minimum_accepted_step_s,.5*h) : .5*h;
        result.maximum_accepted_error=std::max(result.maximum_accepted_error,result.last_error.normalized);
        // Subtract the exact remainder on the last segment, including values
        // below the comparison floor. Never declare success after dropping time.
        result.remaining_time_s=h==result.remaining_time_s ? 0 : result.remaining_time_s-h;
        const double factor=result.last_error.normalized>0 ? std::clamp(.8/std::sqrt(result.last_error.normalized),.25,2.0) : 2.0;
        result.suggested_trial_dt_s=std::clamp(h*factor,settings.minimum_trial_dt_s,settings.maximum_trial_dt_s);
        h=result.suggested_trial_dt_s;
    }
    const auto after=measure(working,sphere ? &working_sphere : nullptr,gravity);
    auto &balance=result.step.balance;
    balance.balance_measured=true;
    balance.energy_residual_j=after.kinetic_energy_j-before.kinetic_energy_j+after.elastic_energy_j-before.elastic_energy_j+
        result.step.contact_energy_after_j-result.step.contact_energy_before_j+result.step.contact_damping_loss_j-
        dot(gravity,after.mass_first_moment_kg_m-before.mass_first_moment_kg_m);
    const Vec3 gravity_impulse=dt*before.mass_kg*gravity;
    balance.linear_momentum_residual_kg_m_s=after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s-gravity_impulse-balance.support_impulse_kg_m_s;
    balance.angular_momentum_residual_kg_m2_s=after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s-gravity_angular-balance.support_angular_impulse_kg_m2_s;
    const auto &s=settings.step.solver;
    const double bulk=before.mass_kg>0 ? .5*lengthSquared(before.linear_momentum_kg_m_s)/before.mass_kg : 0;
    const double kinetic=s.support ? before.kinetic_energy_j : std::max(0.0,before.kinetic_energy_j-bulk);
    const double energy_budget=s.relative_energy_tolerance*std::max(1.0,kinetic+before.elastic_energy_j+result.step.contact_energy_before_j);
    const double momentum_budget=s.relative_momentum_tolerance*std::max({1.0,length(before.linear_momentum_kg_m_s),length(gravity_impulse),length(balance.support_impulse_kg_m_s)});
    const double angular_budget=s.relative_momentum_tolerance*std::max({1.0,length(before.angular_momentum_kg_m2_s),length(gravity_angular),length(balance.support_angular_impulse_kg_m2_s)});
    balance.converged=std::isfinite(balance.energy_residual_j) && std::abs(balance.energy_residual_j)<=energy_budget &&
        finite(balance.linear_momentum_residual_kg_m_s) && length(balance.linear_momentum_residual_kg_m_s)<=momentum_budget &&
        finite(balance.angular_momentum_residual_kg_m2_s) && length(balance.angular_momentum_residual_kg_m2_s)<=angular_budget &&
        std::isfinite(result.step.contact_damping_loss_j) && result.step.contact_damping_loss_j>=0;
    if (!balance.converged) { result.failure=CompliantAdvanceFailure::IntervalBalance; return result; }
    matter.nodes=std::move(working.nodes);
    if (sphere) *sphere=working_sphere;
    result.advanced_time_s=dt;
    return result;
}
}
