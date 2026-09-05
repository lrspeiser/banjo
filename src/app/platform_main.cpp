#include "platform/PlatformWorld.hpp"
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <chrono>
int main(int argc,char **argv){try{
    if(argc==2&&std::string(argv[1])=="--capabilities"){std::cout<<banjo::PlatformWorld::capabilitiesJson()<<'\n';return 0;}
    if(argc!=3&&argc!=4)throw std::invalid_argument("usage: banjo_platform_cli --validate package.json | --run package.json steps | --capabilities");
    const std::string command=argv[1];if(command!="--validate"&&command!="--run")throw std::invalid_argument("unknown command");
    if((command=="--validate"&&argc!=3)||(command=="--run"&&argc!=4))throw std::invalid_argument("incorrect argument count");
    if(std::filesystem::file_size(argv[2])>4194304)throw std::invalid_argument("package byte budget exceeded");
    std::ifstream input(argv[2]);if(!input)throw std::runtime_error("cannot read package");
    std::string source((std::istreambuf_iterator<char>(input)),{});
    const auto start=std::chrono::steady_clock::now();auto world=banjo::PlatformWorld::load(source);
    const double load=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
    if(command=="--run"){std::size_t parsed=0;const auto steps=std::stoul(argv[3],&parsed);if(parsed!=std::string(argv[3]).size()||steps==0||steps>24000)throw std::invalid_argument("steps must be 1..24000");for(unsigned i=0;i<steps;++i)if(!world->step().error.empty())break;}
    auto result=nlohmann::json::parse(world->reportJson());result["load_wall_ms"]=load;
#ifdef _MSC_VER
    result["compiler"]="MSVC "+std::to_string(_MSC_VER);
#else
    result["compiler"]=std::string(__VERSION__);
#endif
    std::cout<<result.dump(2)<<'\n';return result["fault"]==""?0:2;
}catch(const std::exception &e){std::cout<<nlohmann::json{{"error",e.what()}}.dump()<<'\n';return 1;}}
