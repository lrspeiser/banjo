#include "creator/CreatorWorld.hpp"
#include "physics/RollingKinematics.hpp"
#include <nlohmann/json.hpp>
#include <cmath>
#include <functional>
#include <iostream>
#include <numbers>
#include <stdexcept>

namespace {
using namespace banjo;
using Json=nlohmann::json;
void require(bool value,const char *message) {if (!value) throw std::runtime_error(message);}
void near(double a,double b,double tolerance,const char *message) {require(std::isfinite(a)&&std::abs(a-b)<=tolerance,message);}
void rejects(const std::function<void()> &action) {bool failed=false;try {action();}catch(const std::exception &){failed=true;}require(failed,"invalid command must reject");}
void inventoryAndAtomicCreation() {
    CreatorWorld world;ObjectRecipe r;
    const auto before=world.serialize();rejects([&]{(void)world.create("first",r);});require(world.serialize()==before,"uncollected material cannot be spent");
    require(world.collect("oak-pile")&&!world.collect("oak-pile"),"pickup is idempotent");
    const auto plan=world.preview(r);near(world.inventoryMass(MaterialPreset::Oak),10,0,"preview does not consume inventory");
    const auto id=world.create("first",r);near(world.inventoryMass(MaterialPreset::Oak)+plan.mass_kg,10,1e-12,"created matter plus inventory retains original lot mass");
    const auto created=world.serialize();require(world.create("first",r)==id&&world.serialize()==created,"request replay does not mint or debit twice");
    auto changed=r;changed.radius_m=.07;rejects([&]{(void)world.create("first",changed);});
    rejects([&]{(void)world.create("overlapping",r);});changed.shape="door";rejects([&]{(void)world.create("unsupported",changed);});
    changed=r;changed.radius_m=.5;rejects([&]{(void)world.create("unaffordable",changed);});changed=r;changed.physics="brittle";rejects([&]{(void)world.create("wrong-law",changed);});
    require(world.serialize()==created,"all failed creations retain object and inventory state");
    world.step(10);require(world.create("first",r)==id,"replay remains valid after the original object moves");
}
void threeMaterialCreationAndFreeFall() {
    double previous_y=0,previous_v=0;
    for (auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld world({.slope_degrees=0});ObjectRecipe r;r.material=material;r.clearance_m=1.5;
        world.collect(std::string(materialPresetName(material))+"-pile");const auto id=world.create("drop",r);(void)id;
        const auto &first=world.objects().front();const double expected=4.0/3*std::numbers::pi*std::pow(r.radius_m,3)*makeReferenceMaterial(material).density_kg_m3;
        near(first.mass_kg,expected,1e-12,"compiled mass comes from occupied sphere matter");
        near(first.inertia_kg_m2,.4*expected*r.radius_m*r.radius_m,1e-12,"compiled sphere inertia");
        near(world.inventoryMass(material)+expected,10,1e-12,"per-material inventory/matter ledger");
        world.step(48);const auto &s=world.objects().front().state;
        near(s.linear_velocity_m_s.y,-9.81*.2,1e-5,"created object follows gravitational acceleration");
        near(s.center_of_mass_world_m.y,r.radius_m+r.clearance_m-.5*9.81*.2*.2,.005,"created object follows free-fall position within fixed-step truncation bound");
        if (previous_y) {near(s.center_of_mass_world_m.y,previous_y,1e-6,"density does not change free-fall position");near(s.linear_velocity_m_s.y,previous_v,1e-6,"density does not change acceleration");}
        previous_y=s.center_of_mass_world_m.y;previous_v=s.linear_velocity_m_s.y;
        std::cout<<materialPresetName(material)<<" mass="<<expected<<" remaining="<<world.inventoryMass(material)<<" fall-vy="<<previous_v<<'\n';
    }
}
void createdObjectsRoll() {
    CreatorWorld world;
    for (auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        world.collect(std::string(materialPresetName(material))+"-pile");ObjectRecipe r;r.material=material;r.bitangent_m=static_cast<double>(world.objects().size())-1;
        (void)world.create(std::string(materialPresetName(material)),r);
    }
    world.step(240);
    for (const auto &object:world.objects()) {
        const auto measured=measureRollingKinematics(object.state,object.recipe.radius_m,world.support());
        require(dot(object.state.linear_velocity_m_s,world.support().tangent_world)>.2,"created sphere moves downhill");
        require(length(object.state.angular_velocity_rad_s)>.5,"contact creates spin from a nonspinning creation");
        require(measured.state==RollingState::Rolling&&measured.contact_slip_speed_m_s<.02,"rolling is measured from actual contact slip");
        std::cout<<materialPresetName(object.recipe.material)<<" slope-speed="<<measured.translation_speed_m_s<<" slip="<<measured.contact_slip_speed_m_s<<'\n';
    }
}
void finiteMaterialCollision() {
    for (auto target:{MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld world({.slope_degrees=0,.gravity_m_s2={}});
        world.collect("glass-pile");world.collect(std::string(materialPresetName(target))+"-pile");
        ObjectRecipe a;a.material=MaterialPreset::Glass;a.tangent_m=-.3;a.clearance_m=1;a.linear_velocity_m_s={.5,0,0};
        auto b=a;b.material=target;b.tangent_m=.3;b.linear_velocity_m_s={-.5,0,0};
        (void)world.create("a",a);(void)world.create("b",b);
        const double ma=world.objects()[0].mass_kg,mb=world.objects()[1].mass_kg,p0=.5*(ma-mb),k0=.125*(ma+mb);
        world.step(192);
        const auto va=world.objects()[0].state.linear_velocity_m_s,vb=world.objects()[1].state.linear_velocity_m_s;
        near(length(ma*va+mb*vb-Vec3{p0,0,0}),0,2e-6*(ma+mb),"finite created bodies exchange momentum");
        require(.5*ma*lengthSquared(va)+.5*mb*lengthSquared(vb)<=k0+1e-6,"created collision does not create kinetic energy");
        require(va.x<.5&&vb.x>-.5,"both created bodies receive collision reactions");
    }
}
void persistenceAndInputBoundary() {
    CreatorWorld world;world.collect("oak-pile");ObjectRecipe r;r.name="Collected oak ball";(void)world.create("persist",r);world.step(100);
    const auto document=world.serialize();
    {
        auto loaded=CreatorWorld::deserialize(document);
        require(loaded.serialize()==document,"inventory, provenance, recipes, IDs and physical states round trip");
        require(loaded.create("persist",r)==1,"saved request identity remains idempotent");loaded.step(2);
        auto bad=Json::parse(document);bad["lots"][1]["remaining_mass_kg"]=10;rejects([&]{(void)CreatorWorld::deserialize(bad.dump());});
        bad=Json::parse(document);bad["physics_signature"]["object_compiler"]=2;rejects([&]{(void)CreatorWorld::deserialize(bad.dump());});
    }
    world.step(2);(void)world.create("second",ObjectRecipe{.tangent_m=2});require(world.objects().size()==2,"destroying another world preserves this world's runtime");
    const auto before=world.serialize();
    rejects([&]{(void)world.executeJson(R"({"type":"collect","type":"inspect","lot_id":"iron-pile"})");});
    auto response=Json::parse(world.executeJson(R"({"type":"collect","lot_id":"missing","mass_kg":1000})"));require(!response["ok"].get<bool>(),"LLM cannot add quantities to a collection command");
    response=Json::parse(world.executeJson(R"({"type":"execute_code","code":"mint inventory"})"));require(!response["ok"].get<bool>(),"arbitrary commands are not executable capabilities");
    require(world.serialize()==before,"malformed or unauthorized command shapes preserve state");
    const auto path=std::filesystem::current_path()/"creator-test-world.json";world.save(path);world.save(path);
    auto loaded=CreatorWorld::load(path);require(loaded.serialize()==world.serialize(),"atomic save can replace a prior world");std::filesystem::remove(path);
}
}
int main() {
    unsigned failures=0;
    for (const auto &[name,action]:std::vector<std::pair<const char*,std::function<void()>>>{
        {"inventory and transactional creation",inventoryAndAtomicCreation},{"glass/oak/iron creation and free fall",threeMaterialCreationAndFreeFall},
        {"three-material created-object rolling",createdObjectsRoll},{"finite created material collisions",finiteMaterialCollision},
        {"persistence, multi-world lifetime and input boundary",persistenceAndInputBoundary}}) {
        try {action();std::cout<<"[PASS] "<<name<<'\n';}catch(const std::exception &e){++failures;std::cerr<<"[FAIL] "<<name<<": "<<e.what()<<'\n';}
    }
    return failures?1:0;
}
