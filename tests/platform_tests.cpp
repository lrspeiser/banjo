#include "platform/PlatformWorld.hpp"
#include <nlohmann/json.hpp>
#include <iostream>
#include <stdexcept>
#include <numbers>
using namespace banjo;using nlohmann::json;
void check(bool ok,const char *s){if(!ok)throw std::runtime_error(s);}
json body(unsigned id,const char *material,double x){return {{"id",id},{"material",material},{"shape","sphere"},{"radius_m",.045},{"position_m",{x,1,0}},{"orientation_wxyz",{1,0,0,0}},{"velocity_m_s",{1,0,0}},{"spin_rad_s",{0,0,0}}};}
json scene(){return {{"package_version",1},{"physics_abi","banjo-platform-1"},{"name","api-test"},{"units","SI"},{"backend","rigid-v1"},{"required_capabilities",{"sphere","gravity"}},{"fixed_dt_s",1./240},{"max_steps_per_call",240},{"gravity_m_s2",{0,0,0}},{"bowl",nullptr},{"objects",{body(1,"glass",0),body(2,"oak",.2),body(3,"iron",.4)}}};}
void rejects(json s){try{auto w=PlatformWorld::load(s.dump());(void)w;}catch(const std::exception &){return;}throw std::runtime_error("invalid scene was accepted");}
int main(){try{
    auto s=scene();auto w=PlatformWorld::load(s.dump());auto clone=PlatformWorld::load(w->packageJson());
    auto step=w->step(24);check(step.completed_steps==24&&step.error.empty(),"API step");clone->step(24);
    auto instances=w->renderInstances();auto other=clone->renderInstances();check(instances.size()==3,"renderer-independent instances");
    for(unsigned i=0;i<3;++i){check(std::abs(instances[i].state.center_of_mass_world_m.x-(i*.2+.1))<1e-5,"three-material free flight");check(length(instances[i].state.center_of_mass_world_m-other[i].state.center_of_mass_world_m)<1e-10,"reproducible package");}
    auto before=w->reportJson();try{w->step(241);throw std::runtime_error("budget accepted");}catch(const std::invalid_argument &){}check(w->reportJson()==before,"invalid call preserves state");
    auto bad=s;bad["units"]="feet";rejects(bad);bad=s;bad["backend"]="automatic";rejects(bad);bad=s;bad["required_capabilities"]={"plasticity"};rejects(bad);bad=s;bad["objects"][1]["id"]=1;rejects(bad);bad=s;bad["objects"][1]["position_m"]={0,1,0};rejects(bad);bad=s;bad["objects"][0]["orientation_wxyz"]={2,0,0,0};rejects(bad);bad=s;bad["objects"][0]["spin_rad_s"]={1000,1000,1000};rejects(bad);bad=s;bad["hidden_script"]="execute";rejects(bad);
    s["backend"]="bonded-reference-v2";s["fixed_dt_s"]=1./2400;auto reference=PlatformWorld::load(s.dump());check(reference->step(12).error.empty(),"reference API advance");check(reference->renderInstances().size()==57,"reference renders actual cells");
    auto report=json::parse(reference->reportJson());check(report["connected_components"]==3&&std::abs(report["energy_residual_j"].get<double>())<1e-8,"reference free flight ledger");
    bad=s;bad["objects"][0]["shape"]="box";bad["objects"][0].erase("radius_m");bad["objects"][0]["dimensions_m"]={.1,.1,.1};rejects(bad);
    auto box=scene();for(auto &b:box["objects"]){b["shape"]="box";b.erase("radius_m");b["dimensions_m"]={.1,.08,.06};}auto boxes=PlatformWorld::load(box.dump());check(boxes->step(12).error.empty(),"box API advance");auto b=boxes->renderInstances();check(b[0].geometry.kind==PrimitiveKind::Box,"box render geometry preserved");
    auto boxReport=json::parse(boxes->reportJson());for(auto &o:boxReport["objects"]){auto mass=o["mass_kg"].get<double>();check(mass>0,"material-derived box mass");}

    for(const char *lower:{"sphere","box"})for(const char *upper:{"sphere","box"}){
        auto drop=scene();drop["gravity_m_s2"]={0,-9.81,0};drop["objects"]=json::array();
        drop["ground"]={{"half_length_m",1.4},{"half_width_m",.7},{"thickness_m",.2},{"surface","concrete"}};
        unsigned id=1;for(auto m:{"glass","oak","iron"}){const double x=-.55+.55*((id-1)/2);for(unsigned level=0;level<2;++level){
            auto b=body(id++,m,x);b["position_m"]={x,level?1.25:.09,0};b["velocity_m_s"]={0,0,0};
            b["shape"]=level?upper:lower;if(b["shape"]=="sphere")b["radius_m"]=.09;else {b.erase("radius_m");b["dimensions_m"]={.18,.18,.18};}drop["objects"].push_back(b);
        }}
        auto trial=PlatformWorld::load(drop.dump());check(trial->supportMesh().size()==2,"ground render surface");
        check(trial->step(48).error.empty(),"drop free flight");
        auto pre=trial->renderInstances();for(unsigned pair=0;pair<3;++pair){
            check(std::abs(pre[2*pair].state.center_of_mass_world_m.y-.09)<.005,"target rests on ground");
            check(std::abs(pre[2*pair+1].state.center_of_mass_world_m.y-(1.25-.5*9.81*.2*.2))<.005,"drop follows gravity before impact");
        }
        bool response[3]{};double previous[3]{};
        for(unsigned pair=0;pair<3;++pair)previous[pair]=pre[2*pair+1].state.linear_velocity_m_s.y;
        for(unsigned tick=0;tick<192;++tick){
            check(trial->step().error.empty(),"drop impact step");auto frame=trial->renderInstances();
            for(unsigned pair=0;pair<3;++pair){auto &a=frame[2*pair];auto &b=frame[2*pair+1];double vy=b.state.linear_velocity_m_s.y;
                response[pair]|=vy-previous[pair]>.1;previous[pair]=vy;
                check(a.state.center_of_mass_world_m.y>.06&&b.state.center_of_mass_world_m.y>.06,"objects retained above finite floor");
            }
        }
        auto r=json::parse(trial->reportJson());for(unsigned pair=0;pair<3;++pair){
            bool contact=false;for(auto &e:r["ball_contact_events"]){unsigned a=e["body_a"],b=e["body_b"];contact|=std::min(a,b)==pair*2+1&&std::max(a,b)==pair*2+2&&e["closing_speed_m_s"].get<double>()>1;}
            check(contact&&response[pair],"falling body hits intended dynamic target and changes motion");
        }
        auto invalid=drop;invalid["backend"]="bonded-reference-v2";invalid["fixed_dt_s"]=1./2400;rejects(invalid);
        invalid=drop;invalid["ground"]["thickness_m"]=0;rejects(invalid);
        invalid=drop;invalid["objects"][0]["position_m"]={0,-.1,0};rejects(invalid);
        std::cout<<"drop "<<upper<<" onto "<<lower<<": glass/oak/iron passed\n";
    }
    std::cout<<"Platform package validation, three-material motion, box geometry, reference cells, clone and call budgets pass\n";return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
