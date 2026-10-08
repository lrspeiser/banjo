#include "platform/VoxelImpactWorld.hpp"
#include <nlohmann/json.hpp>
#include <iostream>
#include <memory>
int main(int argc,char **argv){
    if(argc!=2||(std::string(argv[1])!="--serve"&&std::string(argv[1])!="--serve-reference"))return 1;
    const auto storage=std::string(argv[1])=="--serve-reference"?
        banjo::VoxelExecution::Reference:banjo::VoxelExecution::Inline;
    using Json=nlohmann::json;std::unique_ptr<banjo::VoxelImpactWorld> world;std::string line;
    while(std::getline(std::cin,line))try{
        if(line.size()>4096)throw std::invalid_argument("request budget exceeded");const auto r=Json::parse(line);const auto op=r.at("op").get<std::string>();
        if(op=="create"){auto candidate=std::make_unique<banjo::VoxelImpactWorld>(r.at("declaration").dump(),storage);world=std::move(candidate);}
        else if(op=="advance"){if(!world)throw std::invalid_argument("create first");world->step(r.value("steps",16U));}
        else if(op!="snapshot")throw std::invalid_argument("unknown intention");
        if(!world)throw std::invalid_argument("create first");std::cout<<Json{{"ok",true},{"state",Json::parse(world->snapshotJson())}}.dump()<<'\n'<<std::flush;
    }catch(const std::exception &e){Json out{{"ok",false},{"error",e.what()}};if(world)out["state"]=Json::parse(world->snapshotJson());std::cout<<out.dump()<<'\n'<<std::flush;}
}
