#include "physics/CohesivePair.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {
void require(bool ok,const char *message){if(!ok)throw std::invalid_argument(message);}
double kinetic(double ma,double mb,const CohesivePairState &s){return .5*ma*s.velocity_a_m_s*s.velocity_a_m_s+.5*mb*s.velocity_b_m_s*s.velocity_b_m_s;}
double momentum(double ma,double mb,const CohesivePairState &s){return ma*s.velocity_a_m_s+mb*s.velocity_b_m_s;}
}
CohesivePairResult advanceCohesivePair(const CohesiveInterfaceLaw &law,double ma,double mb,const CohesivePairState &initial,double dt,std::size_t budget){
    const auto initial_response=evaluateCohesiveInterface(law,initial.interface);
    require(std::isfinite(ma)&&std::isfinite(mb)&&ma>0&&mb>0&&std::isfinite(ma+mb),"pair masses must be finite and positive");
    require(std::isfinite(initial.center_position_m)&&std::isfinite(initial.velocity_a_m_s)&&std::isfinite(initial.velocity_b_m_s),"pair state must be finite");
    require(std::isfinite(dt)&&dt>0&&dt<=1&&budget>0&&budget<=4096,"invalid pair duration or substep budget");
    const double inv=1/ma+1/mb,onset=cohesiveDamageOpening(law),failure=cohesiveSeparationOpening(law);
    // Bound both elastic and softening slopes. This makes the scalar implicit
    // opening residual monotone; it is a stability/uniqueness guard, not an
    // accuracy estimator. Refinement tests remain necessary.
    const double slope=law.area_m2*std::max(law.stiffness_pa_per_m,law.strength_pa/(failure-onset));
    const double safe_dt=std::sqrt(.5/(inv*slope));
    require(std::isfinite(inv)&&std::isfinite(slope)&&safe_dt>0,"pair stiffness/mass range is unsupported");
    const double needed=initial_response.separated?1:std::max(1.0,std::ceil(dt/safe_dt));
    require(needed<=static_cast<double>(budget),"cohesive pair requires more substeps; reduce the interval");
    CohesivePairResult result;result.state=initial;result.substeps=static_cast<std::size_t>(needed);
    const double h=dt/static_cast<double>(result.substeps),p0=momentum(ma,mb,initial);
    const double e0=kinetic(ma,mb,initial)+initial_response.stored_energy_j+initial_response.dissipated_energy_j;
    require(std::isfinite(e0)&&std::isfinite(p0),"pair initial mechanics exceed numeric range");
    for(std::size_t step=0;step<result.substeps;++step){
        const auto before=result.state;const double q0=before.interface.opening_m,v0=before.velocity_b_m_s-before.velocity_a_m_s;
        const double free=q0+h*v0,coefficient=.5*h*h*inv;
        double lo=free-coefficient*law.area_m2*law.strength_pa,hi=free;
        const double scale=std::max({failure,std::abs(q0),std::abs(h*v0)}),tolerance=2e-13*scale;
        require(std::isfinite(lo)&&std::isfinite(hi)&&std::isfinite(tolerance),"pair opening range is unsupported");
        const auto residual=[&](double q){return q-free+coefficient*advanceCohesiveInterface(law,before.interface,q).work_conjugate_force_n;};
        require(residual(lo)<=tolerance&&residual(hi)>=-tolerance,"cohesive pair opening root is not bracketed");
        for(unsigned iteration=0;iteration<80&&hi-lo>tolerance;++iteration){const double middle=lo+(hi-lo)*.5;if(residual(middle)>0)hi=middle;else lo=middle;}
        const double q=lo+(hi-lo)*.5;require(std::abs(residual(q))<=4*tolerance,"cohesive pair opening solve did not converge");
        const auto constitutive=advanceCohesiveInterface(law,before.interface,q);
        const double impulse=h*constitutive.work_conjugate_force_n;
        result.state.velocity_a_m_s=before.velocity_a_m_s+impulse/ma;result.state.velocity_b_m_s=before.velocity_b_m_s-impulse/mb;
        result.state.center_position_m=before.center_position_m+h*momentum(ma,mb,before)/(ma+mb);
        result.state.interface=constitutive.state;result.impulse_on_a_n_s+=impulse;result.impulse_on_b_n_s-=impulse;
    }
    const auto final_response=evaluateCohesiveInterface(law,result.state.interface);
    result.dissipated_increment_j=final_response.dissipated_energy_j-initial_response.dissipated_energy_j;
    result.energy_residual_j=kinetic(ma,mb,result.state)+final_response.stored_energy_j+final_response.dissipated_energy_j-e0;
    result.momentum_residual_kg_m_s=momentum(ma,mb,result.state)-p0;
    const double energy_tolerance=1e-12+1e-10*std::abs(e0),momentum_tolerance=1e-12+1e-10*(std::abs(ma*initial.velocity_a_m_s)+std::abs(mb*initial.velocity_b_m_s));
    require(std::isfinite(result.state.center_position_m)&&std::isfinite(result.energy_residual_j)&&std::abs(result.energy_residual_j)<=energy_tolerance&&std::abs(result.momentum_residual_kg_m_s)<=momentum_tolerance,"cohesive pair mechanics exceed conservation budget");
    return result;
}
}
