#include "physics/CohesiveSpatialPair.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
namespace banjo {
namespace {
void require(bool b,const char *s){if(!b)throw std::invalid_argument(s);}
bool finite(Vec3 v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
Vec3 momentum(double a,double b,const CohesiveSpatialPairState &s){return a*s.velocity_a_m_s+b*s.velocity_b_m_s;}
Vec3 angular(double a,double b,const CohesiveSpatialPairState &s){return cross(s.center_position_m,momentum(a,b,s))+(a*b/(a+b))*cross(s.separation_m,s.velocity_b_m_s-s.velocity_a_m_s);}
double kinetic(double a,double b,const CohesiveSpatialPairState &s){return .5*a*lengthSquared(s.velocity_a_m_s)+.5*b*lengthSquared(s.velocity_b_m_s);}
}
CohesiveSpatialPairResult advanceCohesiveSpatialPair(const CohesiveInterfaceLaw &law,double ma,double mb,double rest,const CohesiveSpatialPairState &initial,double dt,std::size_t budget){
    require(law.compression_stiffness_pa_per_m==0,"compression requires distributed patch solver");
    const auto response0=evaluateCohesiveInterface(law,initial.interface);
    require(std::isfinite(ma)&&std::isfinite(mb)&&ma>0&&mb>0&&std::isfinite(ma+mb)&&std::isfinite(ma*mb),"spatial pair masses are invalid");
    require(std::isfinite(rest)&&rest>0&&finite(initial.center_position_m)&&finite(initial.separation_m)&&finite(initial.velocity_a_m_s)&&finite(initial.velocity_b_m_s),"spatial pair geometry/state is invalid");
    require(std::isfinite(dt)&&dt>0&&dt<=1&&budget>0&&budget<=4096,"spatial pair duration/budget is invalid");
    const double failure=cohesiveSeparationOpening(law),onset=cohesiveDamageOpening(law),inv=1/ma+1/mb;
    require(length(initial.separation_m)>=rest*.25&&std::abs(length(initial.separation_m)-rest-initial.interface.opening_m)<=1e-12*rest+1e-14*failure,"opening does not match point geometry or points are too close");
    const double stiffness=law.area_m2*(std::max(law.stiffness_pa_per_m,law.strength_pa/(failure-onset))+8*law.strength_pa/rest);
    const double limit=std::sqrt(.1/(inv*stiffness)),needed=response0.separated?1:std::max(1.0,std::ceil(dt/limit));
    require(std::isfinite(stiffness)&&std::isfinite(inv)&&std::isfinite(needed)&&needed<=static_cast<double>(budget),"spatial pair requires a smaller interval");
    CohesiveSpatialPairResult result;result.state=initial;result.substeps=static_cast<std::size_t>(needed);const double h=dt/static_cast<double>(result.substeps);
    const auto p0=momentum(ma,mb,initial),l0=angular(ma,mb,initial);const double e0=kinetic(ma,mb,initial)+response0.stored_energy_j+response0.dissipated_energy_j;
    require(finite(p0)&&finite(l0)&&std::isfinite(e0),"spatial pair initial mechanics overflow");
    for(std::size_t i=0;i<result.substeps;++i){
        const auto before=result.state;const auto r0=before.separation_m;const double length0=length(r0);const auto free=r0+h*(before.velocity_b_m_s-before.velocity_a_m_s);
        const double coefficient=.5*h*h*inv,tolerance=2e-14*std::max(rest,length0);
        const auto force=[&](Vec3 r){const double length1=length(r);require(finite(r)&&std::isfinite(length1)&&length1>=rest*.25,"spatial pair approaches unsupported coincident points");
            const auto direction=(r+r0)/(length1+length0);
            // Discrete length gradient: dot(direction,r-r0) = |r|-|r0|.
            const double opening=before.interface.opening_m+dot(direction,r-r0);
            return direction*advanceCohesiveInterface(law,before.interface,opening).work_conjugate_force_n;
        };
        Vec3 r=free;bool converged=false;
        for(unsigned iteration=0;iteration<100;++iteration){const auto next=free-coefficient*force(r);if(length(next-r)<=tolerance){r=next;converged=true;break;}r=next;}
        require(converged&&length(r-free+coefficient*force(r))<=4*tolerance,"spatial cohesive opening solve did not converge");
        const auto impulse=h*force(r),direction=(r+r0)/(length(r)+length0);
        result.state.interface=advanceCohesiveInterface(law,before.interface,before.interface.opening_m+dot(direction,r-r0)).state;
        result.state.separation_m=r;result.state.velocity_a_m_s=before.velocity_a_m_s+impulse/ma;result.state.velocity_b_m_s=before.velocity_b_m_s-impulse/mb;
        result.state.center_position_m=before.center_position_m+h*momentum(ma,mb,before)/(ma+mb);result.impulse_on_a_n_s+=impulse;
    }
    const auto response=evaluateCohesiveInterface(law,result.state.interface);
    result.energy_residual_j=kinetic(ma,mb,result.state)+response.stored_energy_j+response.dissipated_energy_j-e0;
    result.momentum_residual_kg_m_s=momentum(ma,mb,result.state)-p0;result.angular_momentum_residual_kg_m2_s=angular(ma,mb,result.state)-l0;
    require(std::isfinite(result.energy_residual_j)&&std::abs(result.energy_residual_j)<=1e-12+1e-9*std::abs(e0)&&length(result.momentum_residual_kg_m_s)<=1e-12+1e-9*length(p0)&&length(result.angular_momentum_residual_kg_m2_s)<=1e-12+1e-9*length(l0),"spatial cohesive mechanics exceed conservation budget");
    return result;
}
}
