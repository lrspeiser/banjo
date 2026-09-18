#include "platform/PlatformWorld.hpp"
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <chrono>
int main(int argc,char **argv){try{
    if(argc==2&&std::string(argv[1])=="--capabilities"){std::cout<<banjo::PlatformWorld::capabilitiesJson()<<'\n';return 0;}
    if(argc<3||argc>5)throw std::invalid_argument("usage: banjo_platform_cli --validate package.json | --run package.json steps | --skin package.json steps output.json | --trace package.json steps | --capabilities");
    const std::string command=argv[1];if(command!="--validate"&&command!="--run"&&command!="--skin"&&command!="--trace")throw std::invalid_argument("unknown command");
    if((command=="--validate"&&argc!=3)||((command=="--run"||command=="--trace")&&argc!=4)||(command=="--skin"&&argc!=5))throw std::invalid_argument("incorrect argument count");
    if(std::filesystem::file_size(argv[2])>4194304)throw std::invalid_argument("package byte budget exceeded");
    std::ifstream input(argv[2]);if(!input)throw std::runtime_error("cannot read package");
    std::string source((std::istreambuf_iterator<char>(input)),{});
    if(command=="--trace"&&nlohmann::json::parse(source).value("backend",std::string{})!="rigid-v1")
        throw std::invalid_argument("rigid trace requires rigid-v1; fracture/network playback needs its own geometry protocol");
    const auto start=std::chrono::steady_clock::now();auto world=banjo::PlatformWorld::load(source);
    const double load=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
    nlohmann::json trace=nlohmann::json::array();
    const auto capture=[&](double time){
        const auto instances=world->renderInstances();
        if(instances.size()>64)throw std::invalid_argument("trace supports at most 64 collision primitives");
        nlohmann::json bodies=nlohmann::json::array();
        for(const auto &part:instances){
            const auto p=part.state.center_of_mass_world_m;const auto q=part.state.orientation_world;
            const auto d=part.geometry.dimensions_m;
            bodies.push_back({{"object_id",part.object_id},{"element_id",part.element_id},
                {"material",banjo::materialPresetName(part.material)},
                {"shape",part.geometry.kind==banjo::PrimitiveKind::Box?"box":"sphere"},
                {"dimensions_m",part.geometry.kind==banjo::PrimitiveKind::Box?nlohmann::json{d.x,d.y,d.z}:nlohmann::json{2*part.geometry.radius_m,2*part.geometry.radius_m,2*part.geometry.radius_m}},
                {"position_m",{p.x,p.y,p.z}},{"orientation_wxyz",{q.w,q.x,q.y,q.z}}});
        }
        trace.push_back({{"t_s",time},{"bodies",bodies}});
    };
    if(command=="--trace")capture(0);
    if(command=="--run"||command=="--skin"||command=="--trace"){std::size_t parsed=0;const auto steps=std::stoul(argv[3],&parsed);if(parsed!=std::string(argv[3]).size()||(steps==0&&(command=="--run"||command=="--trace"))||steps>24000)throw std::invalid_argument("steps must be 1..24000 (skin permits initial state 0)");if(command=="--trace"&&steps>2400)throw std::invalid_argument("trace supports at most 2400 fixed steps");
        const unsigned stride=std::max(1U,static_cast<unsigned>((steps+598)/599));
        for(unsigned i=0;i<steps;++i){const auto step=world->step();if(!step.error.empty())throw std::runtime_error(step.error);
            if(command=="--trace"&&((i+1)%stride==0||i+1==steps))capture(step.elapsed_s);}
    }
    if(command=="--skin"){
        const auto skins=world->renderSkins();if(skins.empty())throw std::invalid_argument("backend has no cell skin capability");
        nlohmann::json objects=nlohmann::json::array();
        for(const auto &skin:skins){nlohmann::json triangles=nlohmann::json::array();for(const auto &t:skin.mesh.triangles){nlohmann::json vertices=nlohmann::json::array();for(auto p:t.positions_world_m)vertices.push_back({p.x,p.y,p.z});triangles.push_back({{"vertices_m",vertices},{"component_id",t.component},{"cell_id",t.source_cell},{"fracture_surface",t.fracture_surface}});}
            objects.push_back({{"object_id",skin.object_id},{"material_id",skin.material_id},{"color_rgba",skin.color_rgba},{"topology_revision",skin.mesh.revision},{"triangles",triangles}});}
        const auto path=std::filesystem::absolute(argv[4]);if(path.lexically_normal()==std::filesystem::absolute(argv[2]).lexically_normal()||std::filesystem::exists(path))throw std::invalid_argument("skin output must be a new file");
        std::ofstream output(path,std::ios::out|std::ios::noreplace);if(!output)throw std::runtime_error("cannot exclusively create skin output");output<<nlohmann::json{{"schema","banjo-cell-skin-1"},{"units","SI"},{"derived_render_data",true},{"simulation_snapshot",false},{"objects",objects}}.dump(2);output.close();if(!output)throw std::runtime_error("cannot write skin output");
    }
    auto result=nlohmann::json::parse(world->reportJson());result["load_wall_ms"]=load;
    if(command=="--trace")result["trace"]={{"schema","banjo.rigid-trace.v1"},{"frames",trace},{"interpolated",false}};
#ifdef _MSC_VER
    result["compiler"]="MSVC "+std::to_string(_MSC_VER);
#else
    result["compiler"]=std::string(__VERSION__);
#endif
    std::cout<<result.dump(2)<<'\n';return result["fault"]==""?0:2;
}catch(const std::exception &e){std::cout<<nlohmann::json{{"error",e.what()}}.dump()<<'\n';return 1;}}
