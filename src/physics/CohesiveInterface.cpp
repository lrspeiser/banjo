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
    const auto r=evaluateCohesiveInterfaceUnchecked(p,s);
    require(std::isfinite(r.force_n)&&std::isfinite(r.stored_energy_j)&&std::isfinite(r.dissipated_energy_j),"cohesive response exceeds numeric range");return r;
}
CohesiveInterfaceIncrement advanceCohesiveInterface(const CohesiveInterfaceLaw &p,const CohesiveInterfaceState &s,double opening){
    (void)evaluateCohesiveInterface(p,s);require(std::isfinite(opening),"cohesive opening must be finite");
    const auto out=advanceCohesiveInterfaceUnchecked(p,s,opening);
    (void)evaluateCohesiveInterface(p,out.state);
    require(std::isfinite(out.work_conjugate_force_n)&&std::isfinite(out.opening_work_j)&&out.dissipated_increment_j>=0,"invalid cohesive work increment");return out;
}
}
