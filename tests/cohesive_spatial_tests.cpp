#include "physics/CohesiveSpatialPair.hpp"
#include "physics/CohesivePair.hpp"
#include "material/MaterialCatalog.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace banjo;
void require(bool b,const char *s){if(!b)throw std::runtime_error(s);}
void near(double a,double b,double t,const char *s){require(std::isfinite(a)&&std::abs(a-b)<=t,s);}
Vec3 rotate(Vec3 x){return {x.z,x.x,x.y};}
int main(){try{
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        const auto m=makeReferenceMaterial(preset);const double area=.0001,ma=m.density_kg_m3*area*.01,mb=2*ma,mu=1/(1/ma+1/mb),work=area*m.fracture_energy_j_m2,rest=.001;
        const CohesiveInterfaceLaw law{2*m.tensile_strength_pa*m.tensile_strength_pa/m.fracture_energy_j_m2,m.tensile_strength_pa,m.fracture_energy_j_m2,area};
        const double speed=std::sqrt(3*work/mu),dt=8*cohesiveSeparationOpening(law)/speed/512;const Vec3 axis=normalized({1,2,3});
        CohesivePairState scalar{0,-mb/(ma+mb)*speed,ma/(ma+mb)*speed,{}};
        CohesiveSpatialPairState spatial{{},axis*rest,axis*scalar.velocity_a_m_s,axis*scalar.velocity_b_m_s,{}};
        double max_energy=0,max_angular=0;
        for(unsigned i=0;i<512;++i){scalar=advanceCohesivePair(law,ma,mb,scalar,dt).state;const auto step=advanceCohesiveSpatialPair(law,ma,mb,rest,spatial,dt);spatial=step.state;max_energy=std::max(max_energy,std::abs(step.energy_residual_j));max_angular=std::max(max_angular,length(step.angular_momentum_residual_kg_m2_s));}
        near(spatial.interface.opening_m,scalar.interface.opening_m,cohesiveSeparationOpening(law)*1e-5,"rotated 3D opening reduces to collinear reference");
        near(length(spatial.velocity_b_m_s-spatial.velocity_a_m_s),scalar.velocity_b_m_s-scalar.velocity_a_m_s,speed*1e-6,"rotated relative velocity matches finite-pair reference");
        near(evaluateCohesiveInterface(law,spatial.interface).dissipated_energy_j,work,work*1e-12,"spatial separation uses Gc area");
        std::cout<<materialPresetName(preset)<<" max_step_energy_residual_j="<<max_energy<<" max_step_angular_residual="<<max_angular<<'\n';
    }
    const CohesiveInterfaceLaw law{1000,10,1,.1};const double ma=1,mb=2,rest=.1,mu=ma*mb/(ma+mb);
    CohesiveSpatialPairState state{{},{rest,0,0},{0,-2.0/3,0},{0,1.0/3,0},{}};
    auto transformed=state;transformed.center_position_m={1,-2,3};transformed.separation_m=rotate(state.separation_m);const Vec3 boost{.1,.2,-.3};transformed.velocity_a_m_s=rotate(state.velocity_a_m_s)+boost;transformed.velocity_b_m_s=rotate(state.velocity_b_m_s)+boost;
    const auto initial=state;const Vec3 initial_h=mu*cross(state.separation_m,state.velocity_b_m_s-state.velocity_a_m_s);double max_energy=0,max_h=0;
    for(unsigned i=0;i<1000;++i){const auto step=advanceCohesiveSpatialPair(law,ma,mb,rest,state,.0005);state=step.state;transformed=advanceCohesiveSpatialPair(law,ma,mb,rest,transformed,.0005).state;
        const auto response=evaluateCohesiveInterface(law,state.interface);const double ke=.5*ma*lengthSquared(state.velocity_a_m_s)+.5*mb*lengthSquared(state.velocity_b_m_s);
        max_energy=std::max(max_energy,std::abs(ke+response.stored_energy_j+response.dissipated_energy_j-1.0/3));max_h=std::max(max_h,length(mu*cross(state.separation_m,state.velocity_b_m_s-state.velocity_a_m_s)-initial_h));
    }
    require(std::abs(state.separation_m.y)>.1,"noncollinear trajectory actually rotates the line of action");near(max_energy,0,1e-9,"rotating central interaction closes full energy history");near(max_h,0,1e-10,"orbital angular momentum survives rotating line of action");
    near(length(transformed.separation_m-rotate(state.separation_m)),0,1e-10,"rotation and translation preserve relative geometry");near(length(transformed.velocity_a_m_s-rotate(state.velocity_a_m_s)-boost),0,1e-10,"Galilean transform preserves interaction velocity");
    std::cout<<"orbital max_energy_residual_j="<<max_energy<<" max_angular_residual="<<max_h<<" final_angle_rad="<<std::atan2(state.separation_m.y,state.separation_m.x)<<'\n';
    auto bad=initial;bad.interface.opening_m=.01;bool rejected=false;try{(void)advanceCohesiveSpatialPair(law,ma,mb,rest,bad,.001);}catch(const std::invalid_argument&){rejected=true;}require(rejected,"opening cannot disagree with actual point geometry");
    rejected=false;try{(void)advanceCohesiveSpatialPair(law,ma,mb,rest,initial,1,1);}catch(const std::invalid_argument&){rejected=true;}require(rejected,"excess step budget rejects without mutating caller");
    std::cout<<"[PASS] spatial cohesive geometry/momentum/energy/orbital/frame/bounds\n";return 0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
