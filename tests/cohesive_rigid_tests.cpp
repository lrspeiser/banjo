#include "physics/CohesiveRigidPair.hpp"
#include "material/MaterialCatalog.hpp"
#include <iostream>
#include <algorithm>
using namespace banjo;
void require(bool b,const char *s){if(!b)throw std::runtime_error(s);}
int main(){try{
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        const auto m=makeReferenceMaterial(preset);const double area=.0001,mass=m.density_kg_m3*.012*.01*.008,work=area*m.fracture_energy_j_m2,rest=.02;
        const CohesiveInterfaceLaw law{2*m.tensile_strength_pa*m.tensile_strength_pa/m.fracture_energy_j_m2,m.tensile_strength_pa,m.fracture_energy_j_m2,area};
        const Vec3 inertia{mass*(.01*.01+.008*.008)/12,mass*(.012*.012+.008*.008)/12,mass*(.012*.012+.01*.01)/12};
        for(double energy_factor:{1.5,6.0}){
        const double speed=std::sqrt(4*energy_factor*work/mass),duration=8*cohesiveSeparationOpening(law)/speed;
        double first_error=0;
        for(unsigned steps:{512u,1024u,2048u}){
            CohesiveRigidPairState s;
            s.a={mass,inertia,{-.015,0,0},{-.5*speed,0,0},{},{.005,.004,0},{}};
            s.b={mass,inertia,{.015,0,0},{.5*speed,0,0},{},{-.005,.004,0},{}};
            const double energy0=cohesiveRigidKineticEnergy(s);double max_error=0,max_p=0,max_l=0;
            for(unsigned i=0;i<steps;++i){const auto next=advanceCohesiveRigidPair(law,rest,s,duration/steps);s=next.state;const auto response=evaluateCohesiveInterface(law,s.interface);
                max_error=std::max(max_error,std::abs(cohesiveRigidKineticEnergy(s)+response.stored_energy_j+response.dissipated_energy_j-energy0));
                max_p=std::max(max_p,length(next.momentum_residual_kg_m_s));max_l=std::max(max_l,length(next.angular_residual_kg_m2_s));
            }
            if(energy_factor==6)require(evaluateCohesiveInterface(law,s.interface).separated,"higher kinetic input separates off-center attachment");
            else require(!evaluateCohesiveInterface(law,s.interface).separated,"lower input retains attachment when motion transfers to spin");
            require(length(s.a.angular_momentum_kg_m2_s)>1e-10,"off-center cohesive force produces intrinsic spin");
            require(std::abs(s.a.orientation.z)>1e-10,"body orientation evolves during separation");
            require(max_p<1e-10&&max_l<1e-10,"closed central attachment preserves momenta");
            if(steps==512)first_error=max_error;
            if(steps==2048)require(max_error<first_error/4&&max_error/work<1e-4,"refinement reduces accounted energy error");
            std::cout<<materialPresetName(preset)<<" energy_factor="<<energy_factor<<" steps="<<steps<<" duration_s="<<duration<<" max_energy_error_j="<<max_error<<" relative_energy_error="<<max_error/work<<" spin_momentum="<<length(s.a.angular_momentum_kg_m2_s)<<" max_angular_residual="<<max_l<<'\n';
        }
        }
    }
    // Torque-free triaxial body: world angular momentum and kinetic energy are
    // independent invariants, with all three principal-axis flows exercised.
    const CohesiveInterfaceLaw free_law{1000,10,1,.1};double previous_error=0;
    CohesiveRigidPairState free_initial;
    free_initial.a={1,{.01,.02,.025},{},{},{.001,.002,.003},{},{}};
    free_initial.b={1,{.01,.02,.025},{1.3,0,0},{},{},{},{}};
    free_initial.interface={.3,.3};
    for(unsigned count:{128u,256u,512u}){
        auto s=free_initial;const double e0=cohesiveRigidKineticEnergy(s);double error=0;
        for(unsigned i=0;i<count;++i){s=advanceCohesiveRigidPair(free_law,1,s,1.0/count).state;error=std::max(error,std::abs(cohesiveRigidKineticEnergy(s)-e0));}
        require(length(s.a.angular_momentum_kg_m2_s-free_initial.a.angular_momentum_kg_m2_s)<1e-12,"free triaxial body preserves world angular momentum");
        require(std::abs(s.a.orientation.x)>.01&&std::abs(s.a.orientation.y)>.01&&std::abs(s.a.orientation.z)>.01,"free asymmetric orientation evolves in three dimensions");
        if(previous_error>0)require(previous_error/error>3.5&&previous_error/error<4.5,"free triaxial energy error converges at second order");
        std::cout<<"free_triaxial steps="<<count<<" max_energy_error_j="<<error<<'\n';previous_error=error;
    }
    auto invalid=free_initial;invalid.a.orientation.w=2;bool rejected=false;
    try{(void)advanceCohesiveRigidPair(free_law,1,invalid,.001);}catch(const std::invalid_argument&){rejected=true;}require(rejected,"invalid orientation rejected");
    std::cout<<"[PASS] coupled rigid cohesive separation and refinement\n";
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
