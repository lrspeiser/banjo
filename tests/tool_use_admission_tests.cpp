#include "fastlattice/LiveWorld.hpp"
#include <nlohmann/json.hpp>
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>

using namespace banjo;
using namespace banjo::fastlattice;
using Json=nlohmann::json;
namespace {
void require(bool value,const char *message) { if(!value)throw std::runtime_error(message); }
struct Fixture {
    std::unique_ptr<LiveWorld> world;
    Vec3 eye{0,2.37,0},target{.65,.75,.2};
    Vec3 direction() const { return normalized(target-eye); }
};
Fixture fixture(const std::string &material,const std::string &family,bool obstruction=false,double soil=.75,bool wet=false) {
    const double width=family=="shovel"?.28:family=="hoe"?.20:family=="unfamiliar"?.16:.12;
    Json scene={{"terrain",{{"surface","columns"},{"generate",{{"kind","flat"},{"nx",32},{"nz",32},
        {"cell_m",.1},{"soil_m",soil},{"sand_m",0},{"discharge_m3_s",0}}}}},
        {"bodies",Json::array({{{"name","head"},{"shape","box"},{"material",material},
            {"dimensions_m",{width,.08,.12}},{"center_m",{.65,1.1,.2}}},
            {{"name","handle"},{"shape","box"},{"material",material},
            {"dimensions_m",{.04,.32,.04}},{"center_m",{.65,1.29,.2}}}})}};
    if(obstruction)scene["bodies"].push_back({{"name","occluder"},{"shape","box"},{"material","iron"},
        {"dimensions_m",{.16,.16,.16}},{"center_m",{.325,1.56,.1}},{"anchored",true}});
    TileImpactRequest request;request.cell_size_m=.02;
    request.bodies=readSceneJson(scene.dump());readSceneSettings(scene.dump(),request);
    if(wet) {
        auto dry=LiveWorld::open(request);
        auto water=Json::parse(dry->environmentState());
        const std::vector<double> depths(32*32,.01);
        water["depth_b64"]=terrain::encodeBase64(depths.data(),depths.size()*sizeof(double));
        water["ledger"]["initial_m3"]=32*32*.1*.1*.01;
        scene["water"]={{"state",water}};
        readSceneSettings(scene.dump(),request);
    }
    Fixture f;f.world=LiveWorld::open(request);f.target.y=soil;f.eye.y=soil+1.62;
    auto &world=*f.world;
    require(world.fix("handle","head",{.65,1.14,.2},{0,1,0},5000,5000)!=0,"fixture fixing failed");
    require(world.toolPoint("head",{.65,1.06,.2},{0,-1,0},width,.04,30,.1,{.65,1.4,.2},"handle")!=0,
        "fixture ground point failed");
    world.spawnNativePlayer("alice",{0,soil,0});world.selectHand("alice");
    require(world.wield("handle",{.65,1.4,.2})&&world.carryWithNativePlayer(),"fixture physical grip failed");
    return f;
}
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
}
int main() {
    try {
        for(const auto &material:{"glass","oak","iron"})
            for(const auto &family:{"pick","shovel","hoe","unfamiliar"})comparative(material,family);
        refusals();std::cout<<"native tool use admission checks passed\n";return 0;
    } catch(const std::exception &error) {std::cerr<<error.what()<<"\n";return 1;}
}
