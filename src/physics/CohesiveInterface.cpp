#include "physics/CohesiveInterface.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {
void require(bool ok,const char *message){if(!ok)throw std::invalid_argument(message);}
void validate(const CohesiveInterfaceLaw &p){
    require(std::isfinite(p.compression_stiffness_pa_per_m)&&p.compression_stiffness_pa_per_m>=0,"compression stiffness must be finite and nonnegative");
    require(std::isfinite(p.stiffness_pa_per_m)&&p.stiffness_pa_per_m>0&&std::isfinite(p.strength_pa)&&p.strength_pa>0&&
        std::isfinite(p.fracture_energy_j_m2)&&p.fracture_energy_j_m2>0&&std::isfinite(p.area_m2)&&p.area_m2>0,"cohesive parameters must be finite and positive");
    const double d0=p.strength_pa/p.stiffness_pa_per_m,df=2*p.fracture_energy_j_m2/p.strength_pa;
    require(std::isfinite(df)&&std::isfinite(d0)&&d0>0&&df>d0,"fracture energy must exceed elastic work at peak traction");
    require(std::isfinite(p.area_m2*p.fracture_energy_j_m2)&&std::isfinite(p.area_m2*p.strength_pa),"cohesive force or work exceeds numeric range");
}
}
double cohesiveDamageOpening(const CohesiveInterfaceLaw &p){validate(p);return p.strength_pa/p.stiffness_pa_per_m;}
double cohesiveSeparationOpening(const CohesiveInterfaceLaw &p){validate(p);return 2*p.fracture_energy_j_m2/p.strength_pa;}
CohesiveInterfaceResponse evaluateCohesiveInterface(const CohesiveInterfaceLaw &p,const CohesiveInterfaceState &s){
    validate(p);require(std::isfinite(s.opening_m)&&std::isfinite(s.maximum_opening_m)&&s.maximum_opening_m>=std::max(0.0,s.opening_m),"invalid cohesive opening history");
    const double d0=p.strength_pa/p.stiffness_pa_per_m,df=2*p.fracture_energy_j_m2/p.strength_pa;
    const double kappa=s.maximum_opening_m,opening=std::max(0.0,s.opening_m);
    CohesiveInterfaceResponse r;
    if(kappa>=df){r.damage=1;r.separated=true;r.dissipated_energy_j=p.area_m2*p.fracture_energy_j_m2;}
    double secant=p.stiffness_pa_per_m;
    if(kappa>=df)secant=0;
    else if(kappa>d0){
        secant=p.strength_pa*((df-kappa)/(df-d0))/kappa;
        r.damage=1-secant/p.stiffness_pa_per_m;
        r.dissipated_energy_j=(p.area_m2*p.fracture_energy_j_m2)*((kappa-d0)/(df-d0));
    }
    r.traction_pa=secant*opening;r.force_n=p.area_m2*r.traction_pa;
    r.stored_energy_j=.5*r.force_n*opening;
    if(s.opening_m<0){r.traction_pa=p.compression_stiffness_pa_per_m*s.opening_m;r.force_n=p.area_m2*r.traction_pa;r.stored_energy_j=.5*r.force_n*s.opening_m;}
    require(std::isfinite(r.force_n)&&std::isfinite(r.stored_energy_j)&&std::isfinite(r.dissipated_energy_j),"cohesive response exceeds numeric range");return r;
}
CohesiveInterfaceIncrement advanceCohesiveInterface(const CohesiveInterfaceLaw &p,const CohesiveInterfaceState &s,double opening){
    const auto before=evaluateCohesiveInterface(p,s);require(std::isfinite(opening),"cohesive opening must be finite");
    CohesiveInterfaceIncrement out;out.state={opening,std::max(s.maximum_opening_m,std::max(0.0,opening))};out.response=evaluateCohesiveInterface(p,out.state);
    out.dissipated_increment_j=out.response.dissipated_energy_j-before.dissipated_energy_j;
    // Independently integrate the piecewise-linear force path, including
    // unloading/reloading before new damage. Do not define work by balancing
    // the ledger: expose the remaining roundoff residual below.
    const double a=std::max(0.0,s.opening_m),b=std::max(0.0,opening),kappa=s.maximum_opening_m;
    const double d0=p.strength_pa/p.stiffness_pa_per_m,df=2*p.fracture_energy_j_m2/p.strength_pa;
    const double secant=kappa>=df?0:kappa<=d0?p.stiffness_pa_per_m:p.strength_pa*((df-kappa)/(df-d0))/kappa;
    if(b<=kappa)out.opening_work_j=(.5*secant*p.area_m2)*(b+a)*(b-a);
    else {
        out.opening_work_j=(.5*secant*p.area_m2)*(kappa+a)*(kappa-a);
        double x=kappa;
        if(x<d0){const double end=std::min(b,d0);out.opening_work_j+=(.5*p.stiffness_pa_per_m*p.area_m2)*(end+x)*(end-x);x=end;}
        if(x<df&&b>x){const double end=std::min(b,df);const double t0=p.strength_pa*((df-x)/(df-d0)),t1=p.strength_pa*((df-end)/(df-d0));out.opening_work_j+=p.area_m2*(.5*t0+.5*t1)*(end-x);}
    }
    const double ca=std::min(0.0,s.opening_m),cb=std::min(0.0,opening);
    out.opening_work_j+=(.5*p.compression_stiffness_pa_per_m*p.area_m2)*(cb+ca)*(cb-ca);
    out.balance_residual_j=out.opening_work_j-(out.response.stored_energy_j-before.stored_energy_j)-out.dissipated_increment_j;
    const double displacement=opening-s.opening_m;
    out.work_conjugate_force_n=displacement==0?out.response.force_n:out.opening_work_j/displacement;
    require(std::isfinite(out.work_conjugate_force_n)&&std::isfinite(out.opening_work_j)&&out.dissipated_increment_j>=0,"invalid cohesive work increment");return out;
}
}
