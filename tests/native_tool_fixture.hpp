#pragma once
#include "fastlattice/LiveWorld.hpp"
#include <nlohmann/json.hpp>
#include <stdexcept>
namespace banjo_test {
using namespace banjo;
using namespace banjo::fastlattice;
using Json=nlohmann::json;
inline void require(bool value,const char *message) { if(!value)throw std::runtime_error(message); }
struct Fixture {
    std::unique_ptr<LiveWorld> world;
    Vec3 eye{0,2.37,0},target{.65,.75,.2};
    Vec3 direction() const { return normalized(target-eye); }
};
inline Fixture fixture(const std::string &material,const std::string &family,bool obstruction=false,double soil=.75,bool wet=false,bool physical=false,double declared_width_m=0) {
    const double width=declared_width_m>0?declared_width_m:family=="shovel"?.28:family=="hoe"?.20:family=="unfamiliar"?.16:.12;
    Json scene={{"terrain",{{"surface","columns"},{"generate",{{"kind","flat"},{"nx",32},{"nz",32},
        {"cell_m",.1},{"soil_m",soil},{"sand_m",0},{"discharge_m3_s",0}}}}},
        {"bodies",Json::array({{{"name","head"},{"shape","box"},{"material",material},
            {"dimensions_m",{width,.08,physical?.04:.12}},{"center_m",{.65,1.1,.2}}},
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
}
