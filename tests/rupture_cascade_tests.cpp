#include "fracture/RuptureCascade.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "material/MaterialCatalog.hpp"
#include <iostream>
#include <stdexcept>
using namespace banjo;
void check(bool value,const char *why){if(!value)throw std::runtime_error(why);}
struct Chain {
    LatticeAsset asset;ActiveMatter matter;CoupledSphereState sphere;std::vector<RuptureInterface> laws;
    Chain(MaterialPreset preset,double speed){
        auto material=makeReferenceMaterial(preset);double h=1e-5,area=h*h;asset.recipe.voxel_size_m=h;asset.nodes.resize(8);matter.asset=&asset;
        for(unsigned i=0;i<8;++i){matter.nodes.push_back({{i*h,0,0},{},{},material.density_kg_m3*h*h*h,{}});
            if(i){asset.bonds.push_back({.node_a=i-1,.node_b=i,.rest_length_m=h,.compliance=h/(material.young_modulus_pa*area)});matter.bonds.emplace_back();}}
        if(material.model==MaterialModel::BrittleBond){std::vector<double> areas(7,area);laws=compileMaterialRuptureInterfaces(material,asset,areas);}
        sphere.radius_m=2e-6;sphere.mass_kg=2.5e-12;sphere.inertia_kg_m2=.4*sphere.mass_kg*sphere.radius_m*sphere.radius_m;
        sphere.motion.center_of_mass_world_m={-sphere.radius_m-1e-7,0,0};sphere.motion.linear_velocity_m_s={speed,0,0};
    }
    MechanicalTotals totals()const{auto t=measureMaterialMechanics(matter);Mat3 inertia;for(unsigned i=0;i<3;++i)inertia.m[i][i]=sphere.inertia_kg_m2;t+=measureRigidMechanics({sphere.motion,sphere.mass_kg,inertia});return t;}
};
RuptureCascadeSettings settings(double step=4e-11){
    RuptureCascadeSettings s;s.maximum_step_s=step;s.minimum_step_s=1e-20;s.maximum_event_overshoot_j=8e-15;
    s.contact.normal={2.8e6,0};s.contact.maximum_compression_m=1e-6;s.contact.solver.velocity_tolerance_m_s=1e-10;
    s.contact.maximum_residual_work_j=1e-20;s.contact.maximum_residual_linear_impulse_kg_m_s=1e-25;s.contact.maximum_residual_angular_impulse_kg_m2_s=1e-30;return s;
}
int main(){try{
    for(double speed:{4.0,60.0,120.0,240.0}){
        Chain c(MaterialPreset::Glass,speed);auto before=c.totals();const auto r=tryRuptureCascade(c.matter,c.sphere,1e-7,c.laws,settings());
        check(r.accepted,r.failure);const auto after=c.totals();double error=after.mechanicalEnergy()+r.final_contact_energy_j+r.contact_damping_loss_j+r.fracture_work_j+r.event_overshoot_loss_j-before.mechanicalEnergy()-r.initial_contact_energy_j;
        check(std::abs(error)<before.mechanicalEnergy()*1e-7,"cascade closes energy");
        check(length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s)<1e-20,"finite impactor momentum retained");
        std::cout<<"glass speed="<<speed<<" events="<<r.events.size()<<" work="<<r.fracture_work_j<<" residual="<<error<<" evals="<<r.evaluations<<'\n';
        if(speed==4)check(r.events.empty()&&findConnectedComponents(c.matter).size()==1,"low impact leaves entire network intact");
        if(speed==60){
            check(r.events.size()==2&&r.events[0].broken_bonds==std::vector<std::uint32_t>{5}&&r.events[1].broken_bonds==std::vector<std::uint32_t>{6},"sequential local failures under unchanged uniform law");
            check(r.events[0].component_node_counts==std::vector<unsigned>{6,2}&&r.events[1].component_node_counts==std::vector<unsigned>{6,1,1},"detached two-cell fragment fails later while core survives");
            check(r.events[1].time_s>r.events[0].time_s+1e-10,"secondary fracture advances physical time");
            for(unsigned i=0;i<5;++i)check(c.matter.bonds[i].alive,"unfailed core bonds retain connectivity");
        }
        for(const auto &e:r.events){std::cout<<"  time="<<e.time_s<<" bonds=";for(auto b:e.broken_bonds)std::cout<<b<<',';std::cout<<" components=";for(auto n:e.component_node_counts)std::cout<<n<<',';std::cout<<'\n';}
    }
    {
        Chain coarse(MaterialPreset::Glass,60),fine(MaterialPreset::Glass,60);
        const auto a=tryRuptureCascade(coarse.matter,coarse.sphere,1e-7,coarse.laws,settings(2e-11));
        const auto b=tryRuptureCascade(fine.matter,fine.sphere,1e-7,fine.laws,settings(1e-11));
        check(a.accepted&&b.accepted&&a.events.size()==b.events.size()&&a.events.size()==2,"refined partial fracture persists");
        for(std::size_t i=0;i<a.events.size();++i){
            check(a.events[i].broken_bonds==b.events[i].broken_bonds&&a.events[i].component_node_counts==b.events[i].component_node_counts,"refinement preserves event order and surviving core");
            check(std::abs(a.events[i].time_s-b.events[i].time_s)<2e-11,"refined event times agree within coarse interval");
            std::cout<<"refinement event="<<i<<" coarse="<<a.events[i].time_s<<" fine="<<b.events[i].time_s<<" difference="<<std::abs(a.events[i].time_s-b.events[i].time_s)<<'\n';
        }
    }
    {
        Chain c(MaterialPreset::Glass,60);const auto before=c.matter;const auto sphere=c.sphere;auto limited=settings();limited.maximum_evaluations=1100;
        const auto result=tryRuptureCascade(c.matter,c.sphere,1e-7,c.laws,limited);
        check(!result.accepted&&result.evaluations==1100&&result.discarded_events>0&&result.events.empty()&&result.fracture_work_j==0&&result.advanced_time_s==0,"budget exhaustion publishes no partial cascade");
        for(std::size_t i=0;i<c.matter.nodes.size();++i)check(length(c.matter.nodes[i].position_world_m-before.nodes[i].position_world_m)==0&&length(c.matter.nodes[i].velocity_m_s-before.nodes[i].velocity_m_s)==0,"full material rollback");
        for(const auto &bond:c.matter.bonds)check(bond.alive,"no leaked topology after event budget exhaustion");
        check(c.matter.step_index==before.step_index&&c.matter.connectivity_dirty==before.connectivity_dirty&&length(c.sphere.motion.center_of_mass_world_m-sphere.motion.center_of_mass_world_m)==0&&length(c.sphere.motion.linear_velocity_m_s-sphere.motion.linear_velocity_m_s)==0,"clock, connectivity and impactor rollback");
        auto invalid=settings();invalid.wave_step_fraction=0;bool rejected=false;try{(void)tryRuptureCascade(c.matter,c.sphere,1e-7,c.laws,invalid);}catch(const std::invalid_argument&){rejected=true;}check(rejected,"invalid wave limit rejected");
    }
    {
        Chain c(MaterialPreset::Glass,0);for(auto &node:c.matter.nodes)node.velocity_m_s={1000,0,0};c.sphere.motion.linear_velocity_m_s={1000,0,0};
        const auto result=tryRuptureCascade(c.matter,c.sphere,1e-7,c.laws,settings());
        check(result.accepted&&result.events.empty()&&findConnectedComponents(c.matter).size()==1,"large bulk kinetic energy does not trigger a fracture cascade without local strain");
    }
    {
        Chain plain(MaterialPreset::Glass,60),recorded(MaterialPreset::Glass,60);auto s=settings();s.capture_interval_s=1e-10;
        const auto baseline=tryRuptureCascade(plain.matter,plain.sphere,1e-7,plain.laws,settings());
        const auto trace=tryRuptureCascade(recorded.matter,recorded.sphere,1e-7,recorded.laws,s);
        check(baseline.accepted&&trace.accepted&&trace.frames.size()>500&&trace.frames.front().time_s==0,"bounded accepted visual trace");
        check(trace.events.size()==baseline.events.size()&&trace.evaluations==baseline.evaluations,"recording does not change solver steps");
        for(unsigned i=0;i<8;++i)check(length(plain.matter.nodes[i].position_world_m-recorded.matter.nodes[i].position_world_m)==0,"recording preserves exact final state");
        for(const auto &event:trace.events){bool found=false;for(const auto &frame:trace.frames)if(frame.time_s==event.time_s){found=true;for(auto bond:event.broken_bonds)check(!frame.live_bonds[bond],"event capture shows accepted broken connections");}check(found,"every fracture event has a visual frame");}
        Chain exhausted(MaterialPreset::Glass,60);s.maximum_capture_frames=2;auto failed=tryRuptureCascade(exhausted.matter,exhausted.sphere,1e-7,exhausted.laws,s);
        check(!failed.accepted&&failed.frames.empty()&&failed.events.empty()&&exhausted.matter.step_index==0,"capture exhaustion rolls back and publishes no frames");
    }
    // Matched early-time wave transmission: identical chain geometry, impactor,
    // speed/contact settings and 2e-11 s maximum step. Oak/iron remain elastic
    // references; their material models are never converted to brittle.
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        Chain c(preset,60);const auto before=c.totals();auto s=settings(2e-11);
        if(!c.laws.empty()){auto result=tryRuptureCascade(c.matter,c.sphere,3e-9,c.laws,s);check(result.accepted&&result.events.empty(),"no fracture ahead of early wave");}
        else for(unsigned step=0;step<150;++step){auto result=tryCompliantStep(c.matter,2e-11,s.contact,{},&c.sphere);check(result.balance.converged,"matched elastic material wave");}
        const double near_speed=length(c.matter.nodes.front().velocity_m_s),far_speed=length(c.matter.nodes.back().velocity_m_s);
        check(near_speed>1&&far_speed<near_speed*.01,"contact region responds before distant region");
        check(findConnectedComponents(c.matter).size()==1,"early wave leaves material connected");
        std::cout<<materialPresetName(preset)<<" at 3 ns near_speed="<<near_speed<<" far_speed="<<far_speed<<'\n';
        (void)before;
    }
    return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
