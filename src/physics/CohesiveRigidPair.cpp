#include "physics/CohesiveRigidPair.hpp"
#include <cmath>
#include <algorithm>
#include <stdexcept>
namespace banjo {
namespace {
bool finite(Vec3 v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
Quat conjugate(Quat q){return {q.w,-q.x,-q.y,-q.z};}
Quat product(Quat a,Quat b){return {a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};}
Vec3 omega(const CohesiveRigidBody &b){const auto l=conjugate(b.orientation).rotate(b.angular_momentum_kg_m2_s);return b.orientation.rotate({l.x/b.principal_inertia_kg_m2.x,l.y/b.principal_inertia_kg_m2.y,l.z/b.principal_inertia_kg_m2.z});}
Vec3 point(const CohesiveRigidBody &b){return b.center_m+b.orientation.rotate(b.attachment_local_m);}
Vec3 momentum(const CohesiveRigidPairState &s){return s.a.mass_kg*s.a.velocity_m_s+s.b.mass_kg*s.b.velocity_m_s;}
Vec3 angular(const CohesiveRigidPairState &s){return cross(s.a.center_m,s.a.mass_kg*s.a.velocity_m_s)+cross(s.b.center_m,s.b.mass_kg*s.b.velocity_m_s)+s.a.angular_momentum_kg_m2_s+s.b.angular_momentum_kg_m2_s;}
AttachmentBody transferBody(const CohesiveRigidBody &b){
    const auto x=b.orientation.rotate({1,0,0}),y=b.orientation.rotate({0,1,0}),z=b.orientation.rotate({0,0,1});
    const double rows[3][3]={{x.x,y.x,z.x},{x.y,y.y,z.y},{x.z,y.z,z.z}},d[3]={b.principal_inertia_kg_m2.x,b.principal_inertia_kg_m2.y,b.principal_inertia_kg_m2.z};
    Mat3 inertia;for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)for(unsigned k=0;k<3;++k)inertia.m[i][j]+=rows[i][k]*d[k]*rows[j][k];
    return {b.mass_kg,inertia,b.center_m,b.velocity_m_s,omega(b)};
}
void kick(CohesiveRigidPairState &s,Vec3 impulse){
    const auto result=applyAttachmentImpulse(transferBody(s.a),transferBody(s.b),point(s.a),point(s.b),impulse);
    s.a.velocity_m_s=result.a.velocity_m_s;s.b.velocity_m_s=result.b.velocity_m_s;
    s.a.angular_momentum_kg_m2_s=result.a.inertia_world_kg_m2*result.a.angular_velocity_rad_s;
    s.b.angular_momentum_kg_m2_s=result.b.inertia_world_kg_m2*result.b.angular_velocity_rad_s;
}
void drift(CohesiveRigidBody &b,double dt){
    b.center_m+=dt*b.velocity_m_s;
    // Symmetric composition of exact principal-axis kinetic Hamiltonian flows.
    // World angular momentum is fixed during free drift; orientation evolves.
    const auto axis=[&](unsigned i,double h){
        const Vec3 l=conjugate(b.orientation).rotate(b.angular_momentum_kg_m2_s);
        const double components[3]={l.x,l.y,l.z},inertias[3]={b.principal_inertia_kg_m2.x,b.principal_inertia_kg_m2.y,b.principal_inertia_kg_m2.z};
        const double angle=.5*h*components[i]/inertias[i],sn=std::sin(angle);
        const Quat rotation{std::cos(angle),i==0?sn:0,i==1?sn:0,i==2?sn:0};
        b.orientation=product(b.orientation,rotation);
    };
    axis(0,.5*dt);axis(1,.5*dt);axis(2,dt);axis(1,.5*dt);axis(0,.5*dt);
}
void validate(const CohesiveRigidBody &b){
    const auto q=b.orientation;const double norm=q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z;
    if(!std::isfinite(b.mass_kg)||b.mass_kg<=0||!finite(b.principal_inertia_kg_m2)||std::min({b.principal_inertia_kg_m2.x,b.principal_inertia_kg_m2.y,b.principal_inertia_kg_m2.z})<=0||!finite(b.center_m)||!finite(b.velocity_m_s)||!finite(b.angular_momentum_kg_m2_s)||!finite(b.attachment_local_m)||!std::isfinite(norm)||std::abs(norm-1)>1e-10)throw std::invalid_argument("invalid cohesive rigid body");
}
}
double cohesiveRigidKineticEnergy(const CohesiveRigidPairState &s){return .5*s.a.mass_kg*lengthSquared(s.a.velocity_m_s)+.5*s.b.mass_kg*lengthSquared(s.b.velocity_m_s)+.5*dot(s.a.angular_momentum_kg_m2_s,omega(s.a))+.5*dot(s.b.angular_momentum_kg_m2_s,omega(s.b));}
CohesivePatchState makeRectangularCohesivePatch(CohesiveRigidBody a,CohesiveRigidBody b,Vec3 ca,Vec3 cb,Vec3 ua,Vec3 va,Vec3 ub,Vec3 vb,double width,double height,unsigned n){
    validate(a);validate(b);
    const auto basis=[](Vec3 u,Vec3 v){return finite(u)&&finite(v)&&std::abs(length(u)-1)<1e-12&&std::abs(length(v)-1)<1e-12&&std::abs(dot(u,v))<1e-12;};
    if(!finite(ca)||!finite(cb)||!basis(ua,va)||!basis(ub,vb)||!std::isfinite(width)||!std::isfinite(height)||width<=0||height<=0||n<1||n>16)throw std::invalid_argument("invalid rectangular cohesive geometry");
    const auto u=a.orientation.rotate(ua),v=a.orientation.rotate(va),gap=b.center_m+b.orientation.rotate(cb)-a.center_m-a.orientation.rotate(ca);
    const double rest=length(gap),area=width*height;
    if(!std::isfinite(area)||area<=0||!std::isfinite(rest)||rest<=0||length(u-b.orientation.rotate(ub))>1e-12||length(v-b.orientation.rotate(vb))>1e-12||std::abs(dot(gap,u))>rest*1e-12||std::abs(dot(gap,v))>rest*1e-12)throw std::invalid_argument("cohesive faces must initially correspond across a normal gap");
    CohesivePatchState out{a,b,{}};
    for(unsigned i=0;i<n;++i)for(unsigned j=0;j<n;++j){const double x=width*((i+.5)/n-.5),y=height*((j+.5)/n-.5);out.sites.push_back({ca+x*ua+y*va,cb+x*ub+y*vb,rest,area/(n*n),{}});}
    return out;
}
CohesivePatchResult advanceCohesivePatch(const CohesiveInterfaceLaw &common,const CohesivePatchState &initial,double dt){
    validate(initial.a);validate(initial.b);
    if(initial.sites.empty()||initial.sites.size()>256||!std::isfinite(dt)||dt<=0||dt>1)throw std::invalid_argument("invalid cohesive patch size/timestep");
    CohesivePatchResult result;result.state=initial;auto &s=result.state;CohesiveRigidPairState pair{s.a,s.b,{}};
    double energy0=cohesiveRigidKineticEnergy(pair),frequency2=0;const auto p0=momentum(pair),l0=angular(pair);
    const auto sitePair=[&](const CohesivePatchSite &site){auto p=pair;p.a.attachment_local_m=site.attachment_a_m;p.b.attachment_local_m=site.attachment_b_m;return p;};
    for(const auto &site:s.sites){auto law=common;law.area_m2=site.area_m2;const auto response=evaluateCohesiveInterface(law,site.history);const auto p=sitePair(site);const double gap=length(point(p.b)-point(p.a));
        if(!finite(site.attachment_a_m)||!finite(site.attachment_b_m)||!std::isfinite(site.rest_distance_m)||site.rest_distance_m<=0||!std::isfinite(gap)||gap<site.rest_distance_m*.25||std::abs(gap-site.rest_distance_m-site.history.opening_m)>1e-12*site.rest_distance_m+1e-14*cohesiveSeparationOpening(law))throw std::invalid_argument("invalid cohesive patch site history/geometry");
        energy0+=response.stored_energy_j+response.dissipated_energy_j;
        const auto mobility=[](const CohesiveRigidBody &b){return 1/b.mass_kg+lengthSquared(b.attachment_local_m)/std::min({b.principal_inertia_kg_m2.x,b.principal_inertia_kg_m2.y,b.principal_inertia_kg_m2.z});};
        const double tensile_slope=response.separated?0:std::max(law.stiffness_pa_per_m,law.strength_pa/(cohesiveSeparationOpening(law)-cohesiveDamageOpening(law)));
        frequency2+=law.area_m2*std::max(tensile_slope,law.compression_stiffness_pa_per_m)*(mobility(p.a)+mobility(p.b));
    }
    if(!std::isfinite(frequency2)||dt*std::sqrt(frequency2)>.1||dt*std::max(length(omega(pair.a)),length(omega(pair.b)))>.1)throw CohesiveTimestepRefinement("cohesive patch timestep needs refinement");
    const auto allKicks=[&](){for(const auto &site:s.sites){auto p=sitePair(site);auto law=common;law.area_m2=site.area_m2;const auto gap=point(p.b)-point(p.a);kick(p,(.5*dt*evaluateCohesiveInterface(law,site.history).force_n/length(gap))*gap);pair.a.velocity_m_s=p.a.velocity_m_s;pair.b.velocity_m_s=p.b.velocity_m_s;pair.a.angular_momentum_kg_m2_s=p.a.angular_momentum_kg_m2_s;pair.b.angular_momentum_kg_m2_s=p.b.angular_momentum_kg_m2_s;}};
    allKicks();drift(pair.a,dt);drift(pair.b,dt);double internal=0;
    for(auto &site:s.sites){const auto p=sitePair(site);const double gap=length(point(p.b)-point(p.a));if(!std::isfinite(gap)||gap<site.rest_distance_m*.25)throw std::invalid_argument("unsupported coincident patch points");auto law=common;law.area_m2=site.area_m2;const auto increment=advanceCohesiveInterface(law,site.history,gap-site.rest_distance_m);site.history=increment.state;internal+=increment.response.stored_energy_j+increment.response.dissipated_energy_j;}
    allKicks();validate(pair.a);validate(pair.b);s.a=pair.a;s.b=pair.b;
    result.energy_residual_j=cohesiveRigidKineticEnergy(pair)+internal-energy0;result.momentum_residual=momentum(pair)-p0;result.angular_residual=angular(pair)-l0;
    if(!std::isfinite(result.energy_residual_j)||!finite(result.momentum_residual)||!finite(result.angular_residual))throw std::invalid_argument("cohesive patch numerical overflow");return result;
}
CohesiveRigidPairResult advanceCohesiveRigidPair(const CohesiveInterfaceLaw &law,double rest,const CohesiveRigidPairState &initial,double dt){
    if(law.compression_stiffness_pa_per_m!=0)throw std::invalid_argument("compression requires distributed patch solver");
    validate(initial.a);validate(initial.b);const auto response=evaluateCohesiveInterface(law,initial.interface);
    if(!std::isfinite(rest)||rest<=0||!std::isfinite(dt)||dt<=0||dt>1)throw std::invalid_argument("invalid rigid cohesive rest distance/timestep");
    const auto r0=point(initial.b)-point(initial.a);const double length0=length(r0);
    if(!std::isfinite(length0)||length0<rest*.25||std::abs(length0-rest-initial.interface.opening_m)>1e-12*rest+1e-14*cohesiveSeparationOpening(law))throw std::invalid_argument("rigid attachment geometry/opening mismatch");
    const auto mobility=[](const CohesiveRigidBody &b){return 1/b.mass_kg+lengthSquared(b.attachment_local_m)/std::min({b.principal_inertia_kg_m2.x,b.principal_inertia_kg_m2.y,b.principal_inertia_kg_m2.z});};
    const double stiffness=law.area_m2*std::max(law.stiffness_pa_per_m,law.strength_pa/(cohesiveSeparationOpening(law)-cohesiveDamageOpening(law)));
    const double measure=dt*std::sqrt(stiffness*(mobility(initial.a)+mobility(initial.b)));
    if(!std::isfinite(measure)||(!response.separated&&measure>.1)||dt*std::max(length(omega(initial.a)),length(omega(initial.b)))>.1)throw CohesiveTimestepRefinement("rigid cohesive timestep needs refinement");
    CohesiveRigidPairResult result;result.state=initial;auto &s=result.state;
    const double energy0=cohesiveRigidKineticEnergy(initial)+response.stored_energy_j+response.dissipated_energy_j;
    kick(s,(.5*dt*response.force_n/length0)*r0);drift(s.a,dt);drift(s.b,dt);
    const auto r1=point(s.b)-point(s.a);const double length1=length(r1);
    if(!std::isfinite(length1)||length1<rest*.25)throw std::invalid_argument("unsupported coincident rigid attachment points");
    const auto increment=advanceCohesiveInterface(law,s.interface,length1-rest);s.interface=increment.state;
    kick(s,(.5*dt*increment.response.force_n/length1)*r1);
    validate(s.a);validate(s.b);
    result.energy_residual_j=cohesiveRigidKineticEnergy(s)+increment.response.stored_energy_j+increment.response.dissipated_energy_j-energy0;
    result.momentum_residual_kg_m_s=momentum(s)-momentum(initial);result.angular_residual_kg_m2_s=angular(s)-angular(initial);
    if(!std::isfinite(result.energy_residual_j)||!finite(result.momentum_residual_kg_m_s)||!finite(result.angular_residual_kg_m2_s))throw std::invalid_argument("rigid cohesive numerical overflow");
    return result;
}
template<class State,class Result,class Step,class HistoryError>
Result adaptiveAdvance(const CohesiveInterfaceLaw &law,const State &initial,double duration,const CohesiveAdaptiveControls &controls,Step step,HistoryError historyError){
    validate(initial.a);validate(initial.b);
    if(!std::isfinite(duration)||duration<=0||duration>1||!std::isfinite(controls.energy_error_budget_j)||controls.energy_error_budget_j<=0||!std::isfinite(controls.state_error_tolerance)||controls.state_error_tolerance<=0||controls.state_error_tolerance>.1||controls.maximum_evaluations<3||controls.maximum_evaluations>65536)throw std::invalid_argument("invalid adaptive cohesive controls");
    Result out;out.state=initial;
    const double distance_scale=cohesiveSeparationOpening(law),work=law.area_m2*law.fracture_energy_j_m2;
    const double speed_scale=std::sqrt(work/std::min(initial.a.mass_kg,initial.b.mass_kg));
    const double angular_scale=std::sqrt(work*std::min({initial.a.principal_inertia_kg_m2.x,initial.a.principal_inertia_kg_m2.y,initial.a.principal_inertia_kg_m2.z,initial.b.principal_inertia_kg_m2.x,initial.b.principal_inertia_kg_m2.y,initial.b.principal_inertia_kg_m2.z}));
    if(!std::isfinite(speed_scale)||!std::isfinite(angular_scale)||speed_scale<=0||angular_scale<=0)throw std::invalid_argument("adaptive scales overflow");
    const auto evaluate=[&](const State &s,double h){if(out.evaluations>=controls.maximum_evaluations)throw std::runtime_error("adaptive cohesive evaluation budget exhausted");++out.evaluations;return step(s,h);};
    const auto disagreement=[&](const State &a,const State &b){
        double error=historyError(a,b)/distance_scale;
        const auto compare=[&](const CohesiveRigidBody &x,const CohesiveRigidBody &y){
            const double qdot=x.orientation.w*y.orientation.w+x.orientation.x*y.orientation.x+x.orientation.y*y.orientation.y+x.orientation.z*y.orientation.z;
            const double sign=qdot<0?-1:1;const auto qx=x.orientation,qy=y.orientation;
            const double qdistance=std::sqrt(std::pow(qx.w-sign*qy.w,2)+std::pow(qx.x-sign*qy.x,2)+std::pow(qx.y-sign*qy.y,2)+std::pow(qx.z-sign*qy.z,2));
            error=std::max({error,length(x.center_m-y.center_m)/distance_scale,length(x.velocity_m_s-y.velocity_m_s)/speed_scale,length(x.angular_momentum_kg_m2_s-y.angular_momentum_kg_m2_s)/angular_scale,qdistance});
        };compare(a.a,b.a);compare(a.b,b.b);return error;
    };
    const auto advance=[&](auto &&self,const State &s,double h,unsigned depth)->State{
        if(depth>24||h<=0)throw std::runtime_error("adaptive cohesive refinement depth exhausted");
        try{
            const auto full=evaluate(s,h),half=evaluate(s,.5*h),fine=evaluate(half.state,.5*h);
            // A bounded per-evaluation floor avoids demanding sub-roundoff
            // accuracy at tiny event intervals. The global energy cap remains.
            const double energy=std::abs(half.energy_residual_j)+std::abs(fine.energy_residual_j),fraction=std::max(h/duration,1.0/controls.maximum_evaluations);
            if(energy<=controls.energy_error_budget_j*fraction&&out.accumulated_absolute_energy_error_j+energy<=controls.energy_error_budget_j&&disagreement(full.state,fine.state)<=controls.state_error_tolerance*fraction){
                out.accumulated_absolute_energy_error_j+=energy;out.accepted_half_steps+=2;return fine.state;
            }
        }catch(const CohesiveTimestepRefinement &){/* only timestep screening is recoverable */}
        const auto middle=self(self,s,.5*h,depth+1);return self(self,middle,.5*h,depth+1);
    };
    out.state=advance(advance,initial,duration,0);
    if(out.accumulated_absolute_energy_error_j>controls.energy_error_budget_j*(1+1e-12))throw std::runtime_error("adaptive cohesive accumulated error exceeds budget");
    return out;
}
CohesiveAdaptiveResult advanceCohesiveRigidAdaptive(const CohesiveInterfaceLaw &law,double rest,const CohesiveRigidPairState &initial,double duration,const CohesiveAdaptiveControls &controls){
    (void)evaluateCohesiveInterface(law,initial.interface);
    return adaptiveAdvance<CohesiveRigidPairState,CohesiveAdaptiveResult>(law,initial,duration,controls,
        [&](const auto &s,double h){return advanceCohesiveRigidPair(law,rest,s,h);},
        [](const auto &a,const auto &b){return std::max(std::abs(a.interface.opening_m-b.interface.opening_m),std::abs(a.interface.maximum_opening_m-b.interface.maximum_opening_m));});
}
CohesivePatchAdaptiveResult advanceCohesivePatchAdaptive(const CohesiveInterfaceLaw &common,const CohesivePatchState &initial,double duration,const CohesiveAdaptiveControls &controls){
    if(initial.sites.empty()||initial.sites.size()>256)throw std::invalid_argument("invalid adaptive patch site count");
    auto law=common;law.area_m2=0;
    for(const auto &site:initial.sites){auto local=common;local.area_m2=site.area_m2;(void)evaluateCohesiveInterface(local,site.history);law.area_m2+=site.area_m2;}
    (void)evaluateCohesiveInterface(law,{});
    return adaptiveAdvance<CohesivePatchState,CohesivePatchAdaptiveResult>(law,initial,duration,controls,
        [&](const auto &s,double h){return advanceCohesivePatch(common,s,h);},
        [](const auto &a,const auto &b){double error=0;for(std::size_t i=0;i<a.sites.size();++i)error=std::max({error,std::abs(a.sites[i].history.opening_m-b.sites[i].history.opening_m),std::abs(a.sites[i].history.maximum_opening_m-b.sites[i].history.maximum_opening_m)});return error;});
}
}
