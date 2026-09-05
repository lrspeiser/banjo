#include "creator/PrecisionConversion.hpp"
#include "creator/StarterWorld.hpp"
#include <nlohmann/json.hpp>
#include <iostream>
#include <stdexcept>
using namespace banjo;
using Json=nlohmann::json;
void require(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
template<class F> void rejects(F f){bool caught=false;try{f();}catch(const std::exception&){caught=true;}require(caught,"invalid conversion must reject");}
void verify(const std::string &current,bool starter) {
    require(Json::parse(normalizeSavedWorldJson(current))==Json::parse(current),"normalization preserves current world state");
    auto source=Json::parse(current);source["physics_signature"]["position_bits"]=32;
    const auto original="\n  "+source.dump(2)+"\n";
    if(JoltWorld::positionPrecisionBits()!=64){rejects([&]{(void)upgradePositionPrecisionJson(original);});return;}
    const auto package=Json::parse(upgradePositionPrecisionJson(original));
    require(package["source_document"]==original,"package retains exact original source text");
    auto expected=source;expected["physics_signature"]["position_bits"]=64;
    require(package["converted_world"]==expected,"only physics identity changes");
    require(package["receipt"]["state_preserved_except_signature"]==true&&package["receipt"]["simulation_steps"]==0,"explicit no-step conversion receipt");
    require(package["receipt"]["source_signature"]==source["physics_signature"]&&package["receipt"]["target_signature"]==expected["physics_signature"],"receipt retains both identities");
    require(Json::parse(normalizeSavedWorldJson(expected.dump()))==expected,"converted world loads with current authority");
    rejects([&]{(void)upgradePositionPrecisionJson(expected.dump());});
    auto bad=source;bad[starter?"starter_version":"world_version"]=4;rejects([&]{(void)upgradePositionPrecisionJson(bad.dump());});
    bad=source;bad["physics_signature"]["profiles"][0]["density_kg_m3"]=0;rejects([&]{(void)upgradePositionPrecisionJson(bad.dump());});
    bad=source;bad["physics_signature"].erase("position_bits");rejects([&]{(void)upgradePositionPrecisionJson(bad.dump());});
    bad=source;if(starter)bad["inventory_m3"][0]=100;else bad["lots"][0]["remaining_mass_kg"]=1e9;
    rejects([&]{(void)upgradePositionPrecisionJson(bad.dump());});
    const std::string duplicated="{\"physics_signature\":null,"+source.dump().substr(1);
    rejects([&]{(void)upgradePositionPrecisionJson(duplicated);});
}
int main(){try {
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld creator;creator.collect(std::string(materialPresetName(material))+"-pile");
        ObjectRecipe recipe;recipe.material=material;(void)creator.create("source",recipe);creator.step(1);
        const auto creator_before=creator.serialize();verify(creator_before,false);require(creator.serialize()==creator_before,"offline creator conversion leaves live source unchanged");
        StarterWorld starter;const unsigned id=material==MaterialPreset::Oak?1:material==MaterialPreset::Iron?7:13;
        auto eye=starter.objects().at(id-1).state.center_of_mass_world_m;eye.y+=1;
        (void)starter.interact("collected-source",id,eye);
        const auto starter_before=starter.serialize();verify(starter_before,true);require(starter.serialize()==starter_before,"offline starter conversion leaves live source unchanged");
    }
    rejects([]{(void)normalizeSavedWorldJson(std::string(1024*1024+1,' '));});
    rejects([]{(void)normalizeSavedWorldJson("{}");});
    rejects([]{(void)normalizeSavedWorldJson("{\"world_version\":5,\"starter_version\":5}");});
    std::cout<<"[PASS] glass/oak/iron precision conversion, source preservation and invalid-state rejection; position bits="<<JoltWorld::positionPrecisionBits()<<'\n';return 0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
