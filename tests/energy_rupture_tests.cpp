#include "fracture/EnergyRupture.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/FragmentMassProperties.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "material/MaterialCatalog.hpp"
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace banjo;
void check(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
void near(double a,double b,double tol,const char *why){check(std::isfinite(a)&&std::abs(a-b)<=tol,why);}
void rejects(const std::function<void()> &fn){bool rejected=false;try{fn();}catch(const std::invalid_argument&){rejected=true;}check(rejected,"invalid input rejected");}
struct Fixture {
    LatticeAsset asset;ActiveMatter matter;std::vector<RuptureInterface> laws;
    explicit Fixture(MaterialPreset preset){
        auto m=makeReferenceMaterial(preset);const double h=1e-5,area=h*h;
        asset.recipe.voxel_size_m=h;asset.nodes.resize(2);
        asset.bonds.push_back({.node_a=0,.node_b=1,.rest_length_m=h,.compliance=h/(m.young_modulus_pa*area)});
        matter.asset=&asset;matter.nodes={{{0,0,0},{},{},m.density_kg_m3*h*h*h,{}},{{h,0,0},{},{},m.density_kg_m3*h*h*h,{}}};matter.bonds.resize(1);
        laws.push_back({area,m.fracture_energy_j_m2,m.tensile_strength_pa});
    }
    void extension(double q){matter.nodes[1].position_world_m.x=asset.bonds[0].rest_length_m+q;}
};
int main(){try{
    // Same geometry/initial motion across three material-property sets. These
    // low-level connector oracles explicitly select the ideal law; the adapter
    // below separately proves oak/iron catalog models cannot enable it.
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        Fixture f(preset);const auto threshold=compileRuptureThreshold(f.asset.bonds[0],f.laws[0]);
        f.extension(.99*threshold.extension_m);auto r=tryEnergyRupture(f.matter,f.laws,0);check(r.accepted&&r.broken_bonds.empty(),"below-energy no break");
        f.extension(-1.01*threshold.extension_m);r=tryEnergyRupture(f.matter,f.laws,threshold.work_j);check(r.accepted&&r.broken_bonds.empty(),"compression cannot fund tensile rupture");
        f.extension(threshold.extension_m*(1+1e-8));
        for(auto &n:f.matter.nodes){n.velocity_m_s={.02,-.03,.04};n.spin_angular_velocity_rad_s={1,2,3};}
        const auto before=measureMaterialMechanics(f.matter);const auto original=f.matter;
        r=tryEnergyRupture(f.matter,f.laws,threshold.work_j*1e-10);check(!r.accepted&&f.matter.bonds[0].alive,"overshoot rejection atomic");
        near(length(f.matter.nodes[1].position_world_m-original.nodes[1].position_world_m),0,0,"failed transition preserves pose");
        r=tryEnergyRupture(f.matter,f.laws,threshold.work_j*1e-6);check(r.accepted&&r.broken_bonds.size()==1&&!f.matter.bonds[0].alive&&f.matter.connectivity_dirty,"energy-backed tensile break");
        const auto after=measureMaterialMechanics(f.matter);
        near(after.elastic_energy_j+r.fracture_work_j+r.event_overshoot_loss_j,before.elastic_energy_j,threshold.work_j*1e-12,"fracture energy ledger");
        near(after.kinetic_energy_j,before.kinetic_energy_j,0,"no launch energy");
        near(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s),0,0,"rupture preserves momentum");
        near(length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s),0,0,"rupture preserves spin and orbital momentum");
        const auto components=findConnectedComponents(f.matter);check(components.size()==2,"topology follows failed bond");
        double mass=0,energy=0;Vec3 p{},h{};
        for(const auto &component:components){const auto fragment=calculateFragmentMassProperties(f.matter,component.node_indices);mass+=fragment.mass_kg;energy+=fragment.rigid_kinetic_energy_j;p+=fragment.mass_kg*fragment.linear_velocity_m_s;h+=fragment.angular_momentum_kg_m2_s+cross(fragment.center_of_mass_world_m,fragment.mass_kg*fragment.linear_velocity_m_s);}
        near(mass,after.mass_kg,after.mass_kg*1e-12,"fragment mass retained");near(energy,after.kinetic_energy_j,after.kinetic_energy_j*1e-12,"finite-cell fragment kinetic energy");
        near(length(p-after.linear_momentum_kg_m_s),0,1e-25,"fragment momentum");near(length(h-after.angular_momentum_kg_m2_s),0,1e-25,"fragment angular momentum");
        auto repeat=tryEnergyRupture(f.matter,f.laws,0);check(repeat.accepted&&repeat.fracture_work_j==0&&repeat.broken_bonds.empty(),"no double spending after break");
        std::cout<<materialPresetName(preset)<<" ideal connector GcA="<<r.fracture_work_j<<" event_error="<<r.event_overshoot_loss_j<<" closure="<<r.balance_residual_j<<" components="<<components.size()<<'\n';
        Fixture model(preset);const double area=1e-10;
        if(makeReferenceMaterial(preset).model==MaterialModel::BrittleBond){auto laws=compileMaterialRuptureInterfaces(makeReferenceMaterial(preset),model.asset,std::span(&area,1));check(laws.size()==1,"brittle model adapter");}
        else rejects([&]{(void)compileMaterialRuptureInterfaces(makeReferenceMaterial(preset),model.asset,std::span(&area,1));});
    }
    Fixture invalid(MaterialPreset::Glass);auto law=invalid.laws[0];law.minimum_tensile_strength_pa=1e20;rejects([&]{(void)compileRuptureThreshold(invalid.asset.bonds[0],law);});
    rejects([&]{(void)tryEnergyRupture(invalid.matter,invalid.laws,-1);});
    invalid.matter.bonds[0].damage=.5;rejects([&]{(void)tryEnergyRupture(invalid.matter,invalid.laws,0);});invalid.matter.bonds[0].damage=0;
    invalid.asset.bonds.push_back(invalid.asset.bonds[0]);invalid.matter.bonds.emplace_back();invalid.laws.push_back(invalid.laws[0]);
    const auto critical=compileRuptureThreshold(invalid.asset.bonds[0],invalid.laws[0]);invalid.extension(critical.extension_m*1.001);
    invalid.laws[1].area_m2=std::numeric_limits<double>::quiet_NaN();rejects([&]{(void)tryEnergyRupture(invalid.matter,invalid.laws,1);});check(invalid.matter.bonds[0].alive,"bad final interface cannot partially break earlier bonds");
    {
        Fixture f(MaterialPreset::Glass);const auto t=compileRuptureThreshold(f.asset.bonds[0],f.laws[0]);f.extension(t.extension_m*1.001);
        rejects([&]{(void)tryEnergyRuptureStep(f.matter,1e-12,f.laws,t.work_j);});check(f.matter.bonds[0].alive,"initial failed state cannot advance before topology resolution");
    }
    {
        Fixture f(MaterialPreset::Glass);const auto t=compileRuptureThreshold(f.asset.bonds[0],f.laws[0]);const double rest=f.asset.bonds[0].rest_length_m;
        f.asset.nodes.resize(4);f.matter.nodes.resize(4,f.matter.nodes[0]);f.asset.bonds.resize(3,f.asset.bonds[0]);f.matter.bonds.resize(3);f.laws.resize(3,f.laws[0]);
        const auto direction=normalized(Vec3{1,2,3});const Vec3 omega{.1,.2,-.3},boost{.03,-.02,.01};
        for(unsigned i=0;i<4;++i){auto &n=f.matter.nodes[i];n.position_world_m=direction*(i*rest+(i>=2?t.extension_m*(1+1e-8):0));n.velocity_m_s=boost+cross(omega,n.position_world_m);n.spin_angular_velocity_rad_s=omega;}
        for(unsigned i=0;i<3;++i){f.asset.bonds[i].node_a=i;f.asset.bonds[i].node_b=i+1;}
        const auto before=measureMaterialMechanics(f.matter);const auto result=tryEnergyRupture(f.matter,f.laws,t.work_j*1e-6);
        check(result.accepted&&result.broken_bonds==std::vector<std::uint32_t>{1},"only currently loaded middle connector fails");
        const auto components=findConnectedComponents(f.matter);check(components.size()==2&&components[0].node_indices.size()==2&&components[1].node_indices.size()==2,"two multi-cell fragments emerge from connectivity");
        double mass=0,energy=0;Vec3 momentum{},angular{};
        for(const auto &component:components){auto fragment=calculateFragmentMassProperties(f.matter,component.node_indices);mass+=fragment.mass_kg;energy+=fragment.rigid_kinetic_energy_j;momentum+=fragment.mass_kg*fragment.linear_velocity_m_s;angular+=fragment.angular_momentum_kg_m2_s+cross(fragment.center_of_mass_world_m,fragment.mass_kg*fragment.linear_velocity_m_s);}
        near(mass,before.mass_kg,before.mass_kg*1e-12,"multi-cell mass");near(energy,before.kinetic_energy_j,before.kinetic_energy_j*1e-12,"multi-cell spin energy");
        near(length(momentum-before.linear_momentum_kg_m_s),0,1e-25,"multi-cell momentum");near(length(angular-before.angular_momentum_kg_m2_s),0,1e-25,"multi-cell angular momentum");
    }
    // Dynamic motion supplies stored work; no imposed stretch, impact pulse or
    // predetermined pieces. Event-budget failures halve/replay the whole step.
    for(double energy_factor:{.5,2.0}){
        Fixture f(MaterialPreset::Glass);const auto threshold=compileRuptureThreshold(f.asset.bonds[0],f.laws[0]);
        const double mass=f.matter.nodes[0].mass_kg,reduced=mass/2,omega=std::sqrt(1/(reduced*f.asset.bonds[0].compliance));
        const double speed=std::sqrt(2*energy_factor*threshold.work_j/reduced);
        f.matter.nodes[0].velocity_m_s={-speed/2,0,0};f.matter.nodes[1].velocity_m_s={speed/2,0,0};
        const auto before=measureMaterialMechanics(f.matter);double time=0,work=0,event_loss=0;unsigned rejected=0,steps=0;
        ConservativeStepSettings settings;settings.velocity_tolerance_m_s=1e-8;settings.relative_energy_tolerance=1e-10;
        while(time<2/omega){
            double dt=std::min(.02/omega,2/omega-time);RuptureStepResult result;
            for(unsigned refinement=0;;++refinement){
                const auto pose=f.matter.nodes[0].position_world_m;
                result=tryEnergyRuptureStep(f.matter,dt,f.laws,threshold.work_j*1e-5,settings);
                if(result.accepted)break;
                near(length(f.matter.nodes[0].position_world_m-pose),0,0,"whole motion step rolled back");
                check(refinement<30,"bounded dynamic refinement");dt*=.5;++rejected;
            }
            work+=result.rupture.fracture_work_j;event_loss+=result.rupture.event_overshoot_loss_j;time+=dt;check(++steps<2000,"bounded dynamic steps");
        }
        const auto after=measureMaterialMechanics(f.matter);check(f.matter.bonds[0].alive==(energy_factor<1),"low energy intact, high energy ruptures");
        near(after.mechanicalEnergy()+work+event_loss,before.mechanicalEnergy(),threshold.work_j*1e-7,"dynamic trajectory closes energy");
        std::cout<<"glass dynamic input/GcA="<<energy_factor<<" broken="<<!f.matter.bonds[0].alive<<" steps="<<steps<<" rejected="<<rejected<<" residual="<<after.mechanicalEnergy()+work+event_loss-before.mechanicalEnergy()<<'\n';
    }
    for(double input_factor:{.1,20.0}){
        Fixture f(MaterialPreset::Glass);const auto t=compileRuptureThreshold(f.asset.bonds[0],f.laws[0]);
        const double m=f.matter.nodes[0].mass_kg,omega=std::sqrt(2/(m*f.asset.bonds[0].compliance));
        CoupledSphereState sphere;sphere.radius_m=2e-6;sphere.mass_kg=m;sphere.inertia_kg_m2=.4*m*sphere.radius_m*sphere.radius_m;
        sphere.motion.center_of_mass_world_m={-sphere.radius_m-1e-7,0,0};sphere.motion.linear_velocity_m_s={std::sqrt(2*input_factor*t.work_j/m),0,0};
        const auto totals=[&]{auto total=measureMaterialMechanics(f.matter);Mat3 inertia;for(int a=0;a<3;++a)inertia.m[a][a]=sphere.inertia_kg_m2;total+=measureRigidMechanics({sphere.motion,sphere.mass_kg,inertia});return total;};
        const auto before=totals();double time=0,work=0,error=0,contact_energy=0,damping=0;unsigned rejects_count=0,steps=0;
        CompliantStepSettings settings;settings.normal={4/f.asset.bonds[0].compliance,0};settings.maximum_compression_m=1e-6;
        settings.solver.velocity_tolerance_m_s=1e-10;settings.solver.relative_energy_tolerance=1e-9;settings.maximum_residual_work_j=t.work_j*1e-10;
        settings.maximum_residual_linear_impulse_kg_m_s=1e-25;settings.maximum_residual_angular_impulse_kg_m2_s=1e-30;
        while(time<12/omega){
            double dt=std::min(.02/omega,12/omega-time);CompliantRuptureStepResult result;
            for(unsigned r=0;;++r){
                const auto old=sphere;
                result=tryCompliantRuptureStep(f.matter,sphere,dt,f.laws,t.work_j*1e-5,settings);
                if(result.accepted)break;
                near(length(old.motion.center_of_mass_world_m-sphere.motion.center_of_mass_world_m),0,0,"contact rejection restores sphere pose");
                near(length(old.motion.linear_velocity_m_s-sphere.motion.linear_velocity_m_s),0,0,"contact rejection restores sphere velocity");
                check(r<30,"bounded contact refinement");dt*=.5;++rejects_count;
            }
            time+=dt;work+=result.rupture.fracture_work_j;error+=result.rupture.event_overshoot_loss_j;
            contact_energy=result.contact.contact_energy_after_j;damping+=result.contact.contact_damping_loss_j;check(++steps<3000,"bounded contact trajectory");
        }
        const auto after=totals();
        near(after.mechanicalEnergy()+contact_energy+damping+work+error,before.mechanicalEnergy(),t.work_j*1e-6,"impact-to-fracture closed energy");
        std::cout<<"impact momentum residual="<<length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s)<<" initial="<<length(before.linear_momentum_kg_m_s)<<" energy residual="<<after.mechanicalEnergy()+contact_energy+damping+work+error-before.mechanicalEnergy()<<'\n';
        near(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s),0,1e-20,"finite impactor reaction momentum");
        check(f.matter.bonds[0].alive==(input_factor<1),"low impact intact, high impact fracture");
        std::cout<<"glass impact input/GcA="<<input_factor<<" broken="<<!f.matter.bonds[0].alive<<" steps="<<steps<<" rejected="<<rejects_count<<" residual="<<after.mechanicalEnergy()+contact_energy+damping+work+error-before.mechanicalEnergy()<<'\n';
    }
    // Matched physical inputs across the catalog: same geometry, projectile,
    // speed, contact stiffness, timestep and duration. Oak/iron retain explicitly
    // elastic reference networks, without converting their models to brittle.
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(double speed:{4.0,120.0}){
        Fixture f(preset);const bool brittle=makeReferenceMaterial(preset).model==MaterialModel::BrittleBond;
        CoupledSphereState sphere;sphere.radius_m=2e-6;sphere.mass_kg=2.5e-12;sphere.inertia_kg_m2=.4*sphere.mass_kg*sphere.radius_m*sphere.radius_m;
        sphere.motion.center_of_mass_world_m={-sphere.radius_m-1e-7,0,0};sphere.motion.linear_velocity_m_s={speed,0,0};
        const auto energy=[&]{return measureMaterialMechanics(f.matter).mechanicalEnergy()+.5*sphere.mass_kg*lengthSquared(sphere.motion.linear_velocity_m_s);};
        const double initial=energy();double elapsed=0,work=0,event_loss=0,contact_energy=0;unsigned accepted=0;
        CompliantStepSettings settings;settings.normal={2.8e6,0};settings.maximum_compression_m=1e-6;settings.solver.velocity_tolerance_m_s=1e-10;
        settings.maximum_residual_work_j=1e-20;settings.maximum_residual_linear_impulse_kg_m_s=1e-25;settings.maximum_residual_angular_impulse_kg_m2_s=1e-30;
        while(elapsed<1e-7){double dt=std::min(4e-11,1e-7-elapsed);bool success=false;
            for(unsigned refinement=0;refinement<30;++refinement){
                if(brittle){auto result=tryCompliantRuptureStep(f.matter,sphere,dt,f.laws,8e-15,settings);success=result.accepted;
                    if(success){work+=result.rupture.fracture_work_j;event_loss+=result.rupture.event_overshoot_loss_j;contact_energy=result.contact.contact_energy_after_j;}}
                else {auto result=tryCompliantStep(f.matter,dt,settings,{},&sphere);success=result.balance.converged;if(success)contact_energy=result.contact_energy_after_j;}
                if(success)break;dt*=.5;
            }
            check(success&&++accepted<10000,"bounded matched impact experiment");elapsed+=dt;
        }
        near(energy()+contact_energy+work+event_loss,initial,initial*1e-7,"matched impact energy accounting");
        check(!brittle||f.matter.bonds[0].alive==(speed<100),"matched glass no-break/break");
        check(brittle||f.matter.bonds[0].alive,"rigid-only presets never acquire brittle failure");
        std::cout<<"matched "<<materialPresetName(preset)<<" speed="<<speed<<" broken="<<!f.matter.bonds[0].alive<<" fracture_J="<<work<<" residual="<<energy()+contact_energy+work+event_loss-initial<<'\n';
    }
    return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
