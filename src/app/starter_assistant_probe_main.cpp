#include "creator/StarterWorld.hpp"
#include "creator/CodexAssistant.hpp"
#include <fstream>
#include <iostream>
#include <thread>
using namespace banjo;
void require(bool v,const char *s){if(!v)throw std::runtime_error(s);}
int main(int argc,char **argv){try{
    require(argc==2,"Usage: banjo_starter_assistant_probe NEW_WORKSPACE");
    const std::filesystem::path workspace=argv[1];require(std::filesystem::create_directories(workspace),"Use a fresh evidence workspace");
    for(unsigned test=0;test<5;++test){
        const auto material=test==0?MaterialPreset::Glass:test==1?MaterialPreset::Oak:MaterialPreset::Iron;
        StarterWorld world;const unsigned first=material==MaterialPreset::Glass?13:material==MaterialPreset::Oak?1:7;
        if(test<3)for(unsigned i=0;i<4;++i){auto eye=world.objects().at(first+i-1).state.center_of_mass_world_m;eye.y+=1;(void)world.interact("gather-"+std::to_string(i),first+i,eye);}
        const auto id="starter-"+std::to_string(test);const std::string prompt=test==4?"Make a functional iron saw that cuts wood with physically modeled fracture energy.":"Make a solid "+std::string(materialPresetName(material))+" block exactly 8 cm by 6 cm by 10 cm, world aligned.";
        world.save(workspace/(id+"-before.json"));const auto before=world.serialize();
        CodexAssistant assistant;assistant.start(workspace,id,world.designerRequest(id,prompt));
        std::optional<AssistantReply> reply;while(!(reply=assistant.poll()))std::this_thread::sleep_for(std::chrono::milliseconds(50));
        require(world.serialize()==before,"Assistant must not mutate the world");
        if(test==4){require(!reply->recipe,"Unsupported functional saw must clarify");std::cout<<id<<" unsupported: "<<reply->explanation<<std::endl;continue;}
        require(reply->recipe.has_value(),"Supported design must remain a proposal even when blocked");const auto &r=*reply->recipe;
        require(r.material==material&&r.shape=="box"&&length(r.dimensions_m-Vec3{.08,.06,.1})<1e-9,"Requested material and full dimensions must survive");
        const auto quote=world.quoteRecipe(r);require(quote.ready()==(test<3),"Readiness must reflect actual inventory and level");
        if(test<3){(void)world.craftRecipe(id,r,{0,1.65,0});const auto built=world.serialize();(void)world.craftRecipe(id,r,{0,1.65,0});require(world.serialize()==built,"Build replay must be idempotent");world.step(240);world.save(workspace/(id+"-after.json"));}
        else require(world.serialize()==before,"Blocked design must preserve state");
        std::cout<<id<<" material="<<materialPresetName(material)<<" required_kg="<<quote.required_kg<<" held_kg="<<quote.held_kg<<" missing_kg="<<quote.missing_kg<<" stamina="<<quote.stamina<<" ready="<<quote.ready()<<std::endl;
    }
    return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<std::endl;return 1;}}
