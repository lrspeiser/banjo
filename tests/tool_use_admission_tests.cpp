#include "fastlattice/LiveWorld.hpp"
#include "native_tool_fixture.hpp"
#include "rigid/JoltWorld.hpp"
#include "material/MaterialCompiler.hpp"
#include "material/MaterialCatalog.hpp"
#include <nlohmann/json.hpp>
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>

using namespace banjo;
using namespace banjo::fastlattice;
using Json=nlohmann::json;
namespace {
using namespace banjo_test;
void comparative(const std::string &material,const std::string &family) {
    auto f=fixture(material,family);auto &world=*f.world;
    std::string why;const auto before=world.snapshot(why);require(!before.empty(),"fixture snapshot failed");
    const auto start=std::chrono::steady_clock::now();
    LiveToolUseAdmission result;
    for(int i=0;i<20;++i)result=world.toolUseAdmission(f.eye,f.direction(),2);
    const double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()/20;
    if(!result.admitted)throw std::runtime_error(material+" "+family+": "+result.reason);
    require(world.snapshot(why)==before,"read-only tool eligibility changed the physical snapshot");
    require(world.time_s()==0&&world.carryingWithNativePlayer(),"preview advanced time or replaced carry authority");
    require(length(result.target_m-f.target)<.001,"preview changed the actual selected ray target");
    require(result.tool=="handle"&&result.point!=0&&result.terrain_region==-1,"preview lost component or region identity");
    require(!result.desired_stroke.path_m.empty(),"eligible preview omitted its native actuator plan");
    require(result.entry_clearance.checked && result.entry_clearance.clear && result.entry_clearance.parts_checked==2,
        "eligible preview omitted actual whole-tool entry clearance");
    require(world.groundWork().empty(),"looking at a target performed cutting work");
    require(world.environment()->terrain().ledger().dug.total()==0,"looking removed material");
    require(Json::parse(world.groundDebrisJson()).at("bodies").empty(),"looking released native matter");
    double mass=0;for(const auto &pose:world.poses())mass+=pose.mass_kg;
    std::cout<<"read-only "<<material<<" "<<family<<", scene cell=.02, terrain=.1, dt=none, mass kg="<<mass
        <<", query mean ms="<<ms<<", desired path points="<<result.desired_stroke.path_m.size()
        <<", removed m3=0, physical snapshot unchanged\n";
}
void refusals() {
    auto f=fixture("iron","pick");auto &world=*f.world;
    require(world.toolUseAdmission(f.eye+Vec3{1,0,0},f.direction(),2).reason=="invalid_input","spoofed eye accepted");
    require(world.toolUseAdmission(f.eye,2*f.direction(),2).reason=="invalid_input","nonunit direction accepted");
    require(world.toolUseAdmission(f.eye,f.direction(),3).reason=="invalid_input","excess ray reach accepted");
    require(world.toolUseAdmission(f.eye,{0,1,0},2).reason=="no_contact","empty sky became ground");
    require(world.toolPoint("head",{.68,1.06,.2},{0,-1,0},.04,.04,30,.1,{.65,1.4,.2},"handle")!=0,
        "second point fixture failed");
    require(world.toolUseAdmission(f.eye,f.direction(),2).reason=="ambiguous_capability","multiple points silently chose the first");
    world.release();
    require(world.toolUseAdmission(f.eye,f.direction(),2).reason=="not_holding","empty hand admitted a tool action");
    world.selectHand("unjoined");
    require(world.toolUseAdmission(f.eye,f.direction(),2).reason=="not_joined","absent actor admitted a tool action");
    auto blocked=fixture("iron","pick",true);
    require(blocked.world->toolUseAdmission(blocked.eye,blocked.direction(),2).reason=="target_blocked",
        "native solid occluder was skipped to admit the ground behind it");
    auto rock=fixture("oak","pick",false,0);
    require(rock.world->toolUseAdmission(rock.eye,rock.direction(),2).reason=="material_too_hard",
        "unsupported point hardness was marked eligible on rock");
    auto flooded=fixture("iron","pick",false,.75,true);
    require(flooded.world->environment()->waterDepthAt(flooded.target.x,flooded.target.z)>.005,"wet fixture has no water");
    require(flooded.world->toolUseAdmission(flooded.eye,flooded.direction(),2).reason=="unsupported_law",
        "wet ground was admitted by a dry constitutive law");
}

void nativeShapes(const MaterialDefinition &material) {
    JoltWorld world;
    RigidCompoundDescription fork;fork.body_id=1;fork.material=material;
    const RigidPrimitive cube{PrimitiveKind::Box,0,{.04,.04,.04}};
    fork.parts={{cube,{-.06,0,0},{},material},{cube,{.06,0,0},{},material}};
    const double leaf_mass=cube.volume()*material.density_kg_m3;
    fork.mass_kg=2*leaf_mass;fork.inertia_local_kg_m2=cube.inertia(fork.mass_kg);
    fork.inertia_local_kg_m2.m[1][1]+=2*leaf_mass*.06*.06;
    fork.inertia_local_kg_m2.m[2][2]+=2*leaf_mass*.06*.06;
    fork.state.center_of_mass_world_m={3,1,0};world.addCompound(fork);
    world.addBox({2,{.02,.02,.02},material,{{0,1,0},{},{},{}},true});
    const std::array<MatterBodyId,1> assembly{1};
    const auto original=world.snapshot(1);
    const auto gap=inspectToolEntry(world,assembly,1,{}, {0,1,0},{});
    require(gap.checked && gap.clear && gap.parts_checked==1,"compound void was filled by a bounds proxy");
    const auto met=inspectToolEntry(world,assembly,1,{}, {.06,1,0},{});
    require(!met.clear && !met.ground && met.tool_part==1 && met.blocking_body==2 && met.overlap_m>.003,
        "actual compound leaf contact lost its external body witness");
    const double r=std::sqrt(.5);const Quat quarter{r,0,0,r};
    const auto rotated=inspectToolEntry(world,assembly,1,{.01,0,0},{0,1.07,0},quarter);
    require(!rotated.clear && rotated.blocking_body==2,"rotated grip offset did not use the native local frame");
    const std::array<MatterBodyId,2> internal{1,2};
    require(inspectToolEntry(world,internal,1,{}, {3,1,0},{}).clear,
        "internal assembly pair became an external obstruction");
    const auto after=world.snapshot(1);
    require(length(after.center_of_mass_world_m-original.center_of_mass_world_m)==0 &&
        length(after.linear_velocity_m_s-original.linear_velocity_m_s)==0 &&
        length(after.angular_velocity_rad_s-original.angular_velocity_rad_s)==0 &&
        after.orientation_world.w==original.orientation_world.w,"native geometry query wrote physical state");
    const std::array<MatterBodyId,2> duplicate{1,1};bool refused=false;
    try {(void)inspectToolEntry(world,duplicate,1,{}, {0,1,0},{});}catch(const std::invalid_argument &) {refused=true;}
    require(refused,"duplicate assembly members bypassed the query bound");
}


}
int main() {
    try {
        for(const auto &material:{"glass","oak","iron"})
            for(const auto &family:{"pick","shovel","hoe","unfamiliar"})comparative(material,family);
        refusals();
        for(const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})
            nativeShapes(makeReferenceMaterial(preset,17));
        std::cout<<"native tool use admission checks passed\n";return 0;
    } catch(const std::exception &error) {std::cerr<<error.what()<<"\n";return 1;}
}
