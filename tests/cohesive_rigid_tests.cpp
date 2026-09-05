#include "physics/CohesiveRigidPair.hpp"
#include "material/MaterialCatalog.hpp"
#include <iostream>
#include <algorithm>
using namespace banjo;
void require(bool b,const char *s){if(!b)throw std::runtime_error(s);}
void asymmetric(MaterialPreset preset){
    const auto material=makeReferenceMaterial(preset);const double area=.0001,rest=.02;
    const CohesiveInterfaceLaw law{2*material.tensile_strength_pa*material.tensile_strength_pa/material.fracture_energy_j_m2,material.tensile_strength_pa,material.fracture_energy_j_m2,area};
    const auto body=[&](Vec3 dimensions,Vec3 arm,Quat q){CohesiveRigidBody b;b.mass_kg=material.density_kg_m3*dimensions.x*dimensions.y*dimensions.z;
        b.principal_inertia_kg_m2=b.mass_kg/12*Vec3{dimensions.y*dimensions.y+dimensions.z*dimensions.z,dimensions.x*dimensions.x+dimensions.z*dimensions.z,dimensions.x*dimensions.x+dimensions.y*dimensions.y};b.attachment_local_m=arm;b.orientation=q;return b;};
    CohesiveRigidPairState initial;
    initial.a=body({.012,.01,.008},{.005,.003,.002},{std::cos(.15),0,0,std::sin(.15)});
    initial.b=body({.014,.009,.01},{-.006,-.003,.003},{std::cos(.2),0,std::sin(.2),0});
    const Vec3 axis=normalized({1,.1,-.2});
    initial.a.center_m={-.015,0,0};initial.b.center_m=initial.a.center_m+initial.a.orientation.rotate(initial.a.attachment_local_m)+rest*axis-initial.b.orientation.rotate(initial.b.attachment_local_m);
    const double ma=initial.a.mass_kg,mb=initial.b.mass_kg,mu=ma*mb/(ma+mb),work=area*material.fracture_energy_j_m2,speed=std::sqrt(12*work/mu);
    const Vec3 relative=speed*normalized({1,.2,.3}),boost=speed*Vec3{.13,.07,-.05};
    initial.a.velocity_m_s=boost-mb/(ma+mb)*relative;initial.b.velocity_m_s=boost+ma/(ma+mb)*relative;
    const auto momentum=[](const CohesiveRigidPairState &s){return s.a.mass_kg*s.a.velocity_m_s+s.b.mass_kg*s.b.velocity_m_s;};
    const auto angular=[&](const CohesiveRigidPairState &s){return cross(s.a.center_m,s.a.mass_kg*s.a.velocity_m_s)+cross(s.b.center_m,s.b.mass_kg*s.b.velocity_m_s)+s.a.angular_momentum_kg_m2_s+s.b.angular_momentum_kg_m2_s;};
    const double e0=cohesiveRigidKineticEnergy(initial),duration=8*cohesiveSeparationOpening(law)/speed;
    const Vec3 p0=momentum(initial),l0=angular(initial);double coarse_error=0,previous_difference=0;Vec3 previous_relative_velocity{};
    for(unsigned steps:{512u,1024u,2048u}){
        auto s=initial;double max_e=0,max_p=0,max_l=0;
        for(unsigned i=0;i<steps;++i){s=advanceCohesiveRigidPair(law,rest,s,duration/steps).state;const auto response=evaluateCohesiveInterface(law,s.interface);
            max_e=std::max(max_e,std::abs(cohesiveRigidKineticEnergy(s)+response.stored_energy_j+response.dissipated_energy_j-e0));
            max_p=std::max(max_p,length(momentum(s)-p0));max_l=std::max(max_l,length(angular(s)-l0));}
        require(evaluateCohesiveInterface(law,s.interface).separated,"asymmetric high-input attachment separates");
        require(max_p<1e-12+1e-10*length(p0)&&max_l<1e-12+1e-10*length(l0),"whole asymmetric trajectory preserves total momenta");
        require(length(s.a.angular_momentum_kg_m2_s)>1e-10&&length(s.b.angular_momentum_kg_m2_s)>1e-10,"both unequal bodies gain spin");
        const auto final_relative=s.b.velocity_m_s-s.a.velocity_m_s;const double difference=length(final_relative-previous_relative_velocity)/speed;
        if(steps==512)coarse_error=max_e;
        if(steps==2048){require(max_e<coarse_error/4&&max_e/work<1e-4,"asymmetric energy error refines");require(difference<previous_difference&&difference<1e-4,"asymmetric endpoint velocity refines");}
        std::cout<<materialPresetName(preset)<<" asymmetric_steps="<<steps<<" duration_s="<<duration<<" max_energy_error_j="<<max_e<<" max_momentum_error="<<max_p<<" max_angular_error="<<max_l<<" relative_velocity_difference="<<(steps==512?0:difference)<<'\n';
        previous_relative_velocity=final_relative;previous_difference=difference;
    }
    double previous_adaptive_error=0;
    for(double tolerance:{1e-4,1e-5}){
        const auto result=advanceCohesiveRigidAdaptive(law,rest,initial,duration,{work*tolerance,tolerance,65536});
        const auto response=evaluateCohesiveInterface(law,result.state.interface);
        const double error=std::abs(cohesiveRigidKineticEnergy(result.state)+response.stored_energy_j+response.dissipated_energy_j-e0);
        require(response.separated,"adaptive asymmetric interface separates");
        require(result.accumulated_absolute_energy_error_j<=work*tolerance&&error<=work*tolerance+1e-12,"adaptive accepted error stays in requested budget");
        if(previous_adaptive_error>0)require(result.accumulated_absolute_energy_error_j<previous_adaptive_error,"tighter requested budget reduces accumulated numerical error");
        std::cout<<materialPresetName(preset)<<" adaptive_tolerance="<<tolerance<<" evaluations="<<result.evaluations<<" accepted_half_steps="<<result.accepted_half_steps<<" accumulated_energy_error_j="<<result.accumulated_absolute_energy_error_j<<" final_energy_error_j="<<error<<'\n';
        previous_adaptive_error=result.accumulated_absolute_energy_error_j;
    }
    bool exhausted=false;try{(void)advanceCohesiveRigidAdaptive(law,rest,initial,duration,{work*1e-5,1e-5,3});}catch(const std::runtime_error&){exhausted=true;}require(exhausted,"insufficient adaptive budget rejects entire candidate");
}
int main(){try{
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        asymmetric(preset);
        const auto m=makeReferenceMaterial(preset);const double area=.0001,mass=m.density_kg_m3*.012*.01*.008,work=area*m.fracture_energy_j_m2,rest=.02;
        const CohesiveInterfaceLaw law{2*m.tensile_strength_pa*m.tensile_strength_pa/m.fracture_energy_j_m2,m.tensile_strength_pa,m.fracture_energy_j_m2,area};
        const Vec3 inertia{mass*(.01*.01+.008*.008)/12,mass*(.012*.012+.008*.008)/12,mass*(.012*.012+.01*.01)/12};
        for(unsigned cells:{2u,4u,8u}){
            for(double loading:{.25,1.0,4.0}){
            CohesiveRigidBody a{mass,inertia,{-.016,0,0},{},{},{},{}},b{mass,inertia,{.016,0,0},{},{},{},{}};
            auto patch=makeRectangularCohesivePatch(a,b,{.006,0,0},{-.006,0,0},{0,1,0},{0,0,1},{0,1,0},{0,0,1},.01,.008,cells);
            double total_area=0;for(const auto &site:patch.sites)total_area+=site.area_m2;
            require(std::abs(total_area-.00008)<1e-16,"patch area derives from physical rectangle");
            const double rotation_speed=std::sqrt(2*loading*total_area*m.fracture_energy_j_m2/inertia.z);
            patch.b.angular_momentum_kg_m2_s={0,0,inertia.z*rotation_speed};
            const double duration=cohesiveSeparationOpening(law)/(.005*rotation_speed),dt=duration/2048;
            double damage_min=1,damage_max=0,max_error=0,max_trajectory_error=0;
            const double e0=cohesiveRigidKineticEnergy({patch.a,patch.b,{}});
            for(unsigned i=0;i<2048;++i){const auto next=advanceCohesivePatch(law,patch,dt);patch=next.state;max_error=std::max(max_error,std::abs(next.energy_residual_j));require(length(next.angular_residual)<1e-10,"distributed patch preserves total angular momentum");double energy=cohesiveRigidKineticEnergy({patch.a,patch.b,{}});for(const auto &site:patch.sites){auto local=law;local.area_m2=site.area_m2;const auto response=evaluateCohesiveInterface(local,site.history);energy+=response.stored_energy_j+response.dissipated_energy_j;}max_trajectory_error=std::max(max_trajectory_error,std::abs(energy-e0));}
            for(const auto &site:patch.sites){auto local=law;local.area_m2=site.area_m2;const auto response=evaluateCohesiveInterface(local,site.history);damage_min=std::min(damage_min,response.damage);damage_max=std::max(damage_max,response.damage);}
            if(loading==4)require(damage_max>damage_min+.01,"bending damages different parts of the finite joint differently");
            require(max_trajectory_error<total_area*m.fracture_energy_j_m2*1e-4,"patch whole-trajectory energy error bounded in test");
            std::cout<<materialPresetName(preset)<<" patch_sites="<<patch.sites.size()<<" loading="<<loading<<" area_m2="<<total_area<<" min_damage="<<damage_min<<" max_damage="<<damage_max<<" max_step_energy_error_j="<<max_error<<" max_trajectory_energy_error_j="<<max_trajectory_error<<'\n';
            }
        }
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
