#include "material/ConnectorPlasticity.hpp"
#include "material/ConnectorModeKernel.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
namespace banjo {
ConnectorPlasticParameters compileConnectorPlasticity(const MaterialDefinition &m,double l,double w,double h){
    for(double x:{l,w,h,m.young_modulus_pa,m.yield_strength_pa})
        if(!std::isfinite(x)||x<=0)throw std::invalid_argument("connector plasticity needs positive finite geometry, modulus and yield stress");
    if(m.model!=MaterialModel::RigidOnly||m.anisotropy_ratio!=1||m.hardening_ratio!=0||
       !std::isfinite(m.poisson_ratio)||m.poisson_ratio<=-1||m.poisson_ratio>=.5)
        throw std::invalid_argument("connector plasticity supports isotropic perfect-plastic declarations only; no brittle, grain or hardening law");
    const double area=w*h,iy=w*h*h*h/12,iz=h*w*w*w/12;
    const double shear=m.young_modulus_pa/(2*(1+m.poisson_ratio)),tau=m.yield_strength_pa/std::sqrt(3.);
    // Same reduced section stiffness as the live elastic faces. Polar torsion
    // and first-fibre bending yield are approximations, not calibrated plates.
    ConnectorPlasticParameters p{{m.young_modulus_pa*area/l,shear*area/l,shear*area/l,
        shear*(iy+iz)/l,m.young_modulus_pa*iy/l,m.young_modulus_pa*iz/l},
        {m.yield_strength_pa*area,tau*area,tau*area,tau*(iy+iz)/(std::max(w,h)/2),
         m.yield_strength_pa*iy/(h/2),m.yield_strength_pa*iz/(w/2)}};
    for(unsigned i=0;i<6;++i)if(!std::isfinite(p.stiffness[i])||p.stiffness[i]<=0||
        !std::isfinite(p.yield_load[i])||p.yield_load[i]<=0)throw std::invalid_argument("connector coefficient overflow");
    return p;
}
ConnectorPlasticUpdate advanceConnectorPlasticity(const ConnectorPlasticParameters &p,
    const ConnectorPlasticState &s,const std::array<double,6> &q){
    if(!std::isfinite(s.plastic_dissipation_j)||s.plastic_dissipation_j<0||
       !std::isfinite(s.return_excess_j)||s.return_excess_j<0)
        throw std::invalid_argument("invalid connector plastic ledger");
    ConnectorPlasticUpdate out;out.state=s;
    for(unsigned i=0;i<6;++i){
        const double k=p.stiffness[i],y=p.yield_load[i],old=s.plastic_rest[i],flow=s.accumulated_flow[i];
        if(!std::isfinite(k)||k<=0||!std::isfinite(y)||y<=0||!std::isfinite(q[i])||
           !std::isfinite(old)||!std::isfinite(flow)||flow<0||std::abs(old)>flow+1e-12*std::max(1.,flow))
            throw std::invalid_argument("invalid connector coordinate, history or coefficient");
        double elastic=q[i]-old;const double limit=y/k;
        if(!std::isfinite(elastic)||!std::isfinite(limit)||limit<=0)throw std::invalid_argument("connector return overflow");
        const auto mode=connectorModeReturnUnchecked(k,y,q[i],old,flow);
        out.state.plastic_rest[i]=mode.plastic_rest;
        out.state.accumulated_flow[i]=mode.accumulated_flow;
        out.plastic_increment_j+=mode.plastic_increment_j;
        // Numerical return excess is separate from physical yield work.
        out.return_excess_increment_j+=mode.return_excess_increment_j;
        out.yielded|=mode.yielded;
        out.stored_energy_j+=mode.stored_energy_j;
        if(!std::isfinite(out.state.plastic_rest[i])||!std::isfinite(out.state.accumulated_flow[i]))
            throw std::invalid_argument("connector history overflow");
    }
    out.state.plastic_dissipation_j+=out.plastic_increment_j;
    out.state.return_excess_j+=out.return_excess_increment_j;
    if(out.yielded){
        if(out.state.yielded_updates==std::numeric_limits<std::uint64_t>::max())throw std::invalid_argument("connector history count overflow");
        ++out.state.yielded_updates;
    }
    if(!std::isfinite(out.stored_energy_j+out.state.plastic_dissipation_j+out.state.return_excess_j))
        throw std::invalid_argument("connector energy overflow");
    return out;
}
}
