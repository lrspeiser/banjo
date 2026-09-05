#include "creator/BowlLab.hpp"
#include <nlohmann/json.hpp>
#include <iostream>
#include <stdexcept>
using namespace banjo;
void check(bool value,const char *message){if(!value)throw std::runtime_error(message);}
int main(){try{
    BowlSettings settings;auto triangles=compileBowl(settings);check(triangles.size()==4512,"bounded shared mesh triangle count");
    for(const auto &t:triangles)check(cross(t[1]-t[0],t[2]-t[0]).y>0,"upward winding");
    bool rejected=false;try{settings.tilt_degrees=21;(void)compileBowl(settings);}catch(const std::invalid_argument&){rejected=true;}check(rejected,"invalid tilt rejected");
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){
        BowlLab lab;rejected=false;try{(void)lab.craft(material);}catch(const std::invalid_argument&){rejected=true;}check(rejected&&lab.stock().objects().empty(),"uncollected stock cannot craft");
        lab.collect(material);for(int i=0;i<3;++i){check(lab.stock().assess(lab.craftRecipe(material)).buildable(),"menu preview matches next placement");(void)lab.craft(material);}
        const auto inventory=lab.stock().inventoryMass(material);const auto before=lab.state(1);
        lab.release();double peak_spin=0;for(int k=0;k<240;++k){lab.step();peak_spin=std::max(peak_spin,length(lab.state(1).angular_velocity_rad_s));}lab.pause();const auto after=lab.state(1);
        check(after.center_of_mass_world_m.y>-.1,"bowl supports ball");
        check(length(after.center_of_mass_world_m-before.center_of_mass_world_m)>.01,"gravity and bowl cause motion");
        check(peak_spin>.01,"contact creates spin");
        check(lab.stock().inventoryMass(material)==inventory,"simulation never spends stock");
        lab.configure({});check(lab.stock().inventoryMass(material)==inventory&&lab.timeSeconds()==0,"reset preserves allocations");
        BowlLab restored(CreatorWorld::deserialize(lab.stock().serialize()));check(restored.stock().objects().size()==3,"stock restart retains crafted balls");
        auto report=nlohmann::json::parse(lab.reportJson());check(!report.at("fracture_supported").get<bool>(),"unsupported fracture explicit");
        JoltWorld inertial;inertial.setGravity({});inertial.addBall({.body_id=1,.radius_m=.045,.material=makeReferenceMaterial(material),.angular_velocity_rad_s={1,0,0}});
        const auto actual=inertial.mechanicalState(1);const double expected=.4*actual.mass_kg*.045*.045;
        check(std::abs(actual.inertia_world_kg_m2.m[0][0]-expected)<expected*1e-5,"sphere inertia matches geometry");
        std::cout<<materialPresetName(material)<<" inventory="<<inventory<<" y="<<after.center_of_mass_world_m.y<<" spin="<<length(after.angular_velocity_rad_s)<<'\n';
    }
    BowlLab mixed;for(int round=0;round<2;++round)for(auto m:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}){mixed.collect(m);(void)mixed.craft(m);}
    mixed.release();mixed.step(1200);check(mixed.contacts()>0,"mixed ball contact callbacks");
    for(const auto &o:mixed.stock().objects())check(mixed.state(o.id).center_of_mass_world_m.y>-.1,"six balls retained in level bowl");
    for(auto surface:{MaterialPreset::Concrete,MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(double tilt:{0.0,10.0}){
        BowlSettings setup;setup.surface=surface;setup.tilt_degrees=tilt;mixed.configure(setup);
        const auto stock=mixed.stock().serialize();mixed.release();mixed.step(480);mixed.pause();
        for(const auto &o:mixed.stock().objects()){
            const auto state=mixed.state(o.id);check(std::isfinite(length(state.linear_velocity_m_s))&&state.center_of_mass_world_m.y>-.5,"surface/tilt matrix finite and supported");
        }
        check(stock==mixed.stock().serialize(),"surface test stock immutable");
        const auto report=nlohmann::json::parse(mixed.reportJson());
        std::cout<<"matrix "<<materialPresetName(surface)<<" tilt="<<tilt<<" E0="<<report.at("initial_mechanical_energy_j")<<" E="<<report.at("mechanical_energy_j")<<" callbacks="<<mixed.contacts()<<'\n';
    }
    std::cout<<mixed.reportJson()<<'\n';return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
