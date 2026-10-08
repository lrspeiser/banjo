#include "fastlattice/SheetImpact.hpp"
#include <nlohmann/json.hpp>
#include <chrono>
#include <iostream>
#include <numeric>
#include <set>
#include <string>
using namespace banjo;using namespace banjo::fastlattice;using Json=nlohmann::json;
namespace {
MaterialPreset preset(const std::string &name){for(auto p:kMaterialPresets)if(materialSceneName(p)==name||materialPresetName(p)==name)return p;throw std::invalid_argument("unknown catalog material");}
Json point(Vec3 p){return Json::array({p.x,p.y,p.z});}
Json snapshot(const SheetImpact &world){
    const auto &s=world.state();Json positions=Json::array(),broken=Json::array(),source=Json::array();
    std::vector<unsigned> parent(s.node_count);std::iota(parent.begin(),parent.end(),0);
    const auto root=[&](unsigned id){while(parent[id]!=id)id=parent[id];return id;};
    for(unsigned k=0;k<s.bond_count;++k){if(s.alive[k]){const auto a=root(s.bond_a[k]),b=root(s.bond_b[k]);parent[b]=a;}else broken.push_back(Json::array({s.bond_a[k],s.bond_b[k]}));}
    std::set<unsigned> attached;for(unsigned i=0;i<s.node_count;++i)if(s.inv_mass[i]==0)attached.insert(root(i));
    double displacement=0,plastic=0;unsigned detached=0,empty=0;
    std::vector<Vec3> current;current.reserve(s.node_count);
    for(unsigned i=0;i<s.node_count;++i){const auto p=s.origin+Vec3{s.x0[3*i]+s.u[3*i],s.x0[3*i+1]+s.u[3*i+1],s.x0[3*i+2]+s.u[3*i+2]};
        current.push_back(p);const bool free=!attached.contains(root(i));detached+=free?1U:0U;
        positions.push_back(Json::array({p.x,p.y,p.z,free,s.inv_mass[i]==0}));displacement=std::max(displacement,std::abs(s.u[3*i+1]));}
    // A through-opening must have detached original matter AND no remaining
    // cell intersecting the probe segment across the original sheet thickness.
    // A bent but attached membrane cannot pass this check.
    for(unsigned z=2;z<18;++z)for(unsigned x=2;x<18;++x){const unsigned original=x+20*(1+2*z);
        if(attached.contains(root(original)))continue;
        const double px=-.019+.002*x,pz=-.019+.002*z;bool occupied=false;
        for(const auto &p:current)if(std::abs(p.x-px)<.0010000001&&std::abs(p.z-pz)<.0010000001&&p.y+.001>-.002&&p.y-.001<.002){occupied=true;break;}
        if(!occupied)++empty;
    }
    for(double p:s.plastic_extension)plastic=std::max(plastic,std::abs(p));
    for(const auto &b:world.source().bodies())source.push_back({{"position_m",point(b.motion.center_of_mass_world_m)},
        {"velocity_m_s",point(b.motion.linear_velocity_m_s)},{"mass_kg",b.mass_kg}});
    return {{"schema","banjo.sheet-state.v1"},{"cell_m",.002},{"dimensions_m",point({.04,.004,.04})},
        {"positions",positions},{"broken_interfaces",broken},{"source",source},{"steps",world.status().total_steps},
        {"time_s",world.source().elapsedTime()},{"dt_s",world.timestep()},{"broken_bonds",world.status().broken_bonds},
        {"detached_cells",detached},{"open_columns",empty},{"max_displacement_m",displacement},{"max_plastic_extension_m",plastic},
        {"plastic_work_j",world.status().plastic_work_j},{"initial_energy_j",world.initialEnergy()},{"contact_loss_j",world.contactLoss()},
        {"numerical_energy_j",world.numericalEnergy()},{"energy_residual_j",world.energyResidual()},
        {"momentum_residual_n_s",length(world.momentumResidual())},{"angular_residual_kg_m2_s",length(world.angularResidual())},
        {"limitations",Json::array({"Rigid reference pick: tool deformation/fracture is not implemented here.",
            "Axial elastic/plastic/strength lattice; no calibrated J2 dent, grain or hyperelastic rubber law.",
            "No fragment self-contact, gravity, settling or production-world integration.","Fixed stable timesteps; sustained accuracy/refinement gates remain separate."})}};
}
int serve(){std::unique_ptr<SheetImpact> world;std::string line;while(std::getline(std::cin,line)){
    try{if(line.size()>2048)throw std::invalid_argument("request too large");const auto request=Json::parse(line);const auto op=request.at("op").get<std::string>();
        if(op=="create"){
            const auto p=request.value("point_m",std::vector<double>{0,0,0});if(p.size()!=3)throw std::invalid_argument("point requires three coordinates");
            auto candidate=std::make_unique<SheetImpact>(preset(request.at("material").get<std::string>()),preset(request.at("pick").get<std::string>()),.002,
                request.value("timestep_scale",1.0),Vec3{p[0],p[1],p[2]},request.value("speed_m_s",6.0));world=std::move(candidate);
        }else if(op=="advance"){
            if(!world)throw std::invalid_argument("create a specimen first");const unsigned steps=request.at("steps").get<unsigned>();
            if(steps>1000||world->status().total_steps+steps>60000)throw std::invalid_argument("sheet step budget exceeded");world->advance(steps);
        }else if(op!="snapshot")throw std::invalid_argument("unsupported operation");
        if(!world)throw std::invalid_argument("create a specimen first");std::cout<<Json{{"ok",true},{"state",snapshot(*world)}}.dump()<<'\n'<<std::flush;
    }catch(const std::exception &e){Json failure{{"ok",false},{"error",e.what()}};if(world)failure["state"]=snapshot(*world);std::cout<<failure.dump()<<'\n'<<std::flush;}
}return 0;}
}
int main(int argc,char **argv){try{
    if(argc==2&&std::string(argv[1])=="--serve")return serve();
    const int a=argc>1?std::stoi(argv[1]):2,b=argc>2?std::stoi(argv[2]):0;
    if(a<0||a>7||b<0||b>7)throw std::invalid_argument("material index must be 0..7");
    const auto material=static_cast<MaterialPreset>(a),pick=static_cast<MaterialPreset>(b);
    SheetImpact world(material,pick);const auto start=std::chrono::steady_clock::now();
    const auto batches=argc>3?static_cast<unsigned>(std::stoul(argv[3])):20U;
    if(batches>200)throw std::invalid_argument("batch count exceeds 200");
    for(unsigned batch=0;batch<batches;++batch){world.advance(100);const auto &state=world.state();double displacement=0,plastic=0;
        for(unsigned i=0;i<state.node_count;++i)displacement=std::max(displacement,std::abs(state.u[3*i+1]));
        for(double p:state.plastic_extension)plastic=std::max(plastic,std::abs(p));
        std::cout<<Json{{"material",materialPresetName(material)},{"pick",materialPresetName(pick)},{"steps",world.status().total_steps},
            {"time_s",world.source().elapsedTime()},{"dt_s",world.timestep()},{"broken_bonds",world.status().broken_bonds},
            {"max_displacement_m",displacement},{"max_plastic_extension_m",plastic},{"energy_residual_j",world.energyResidual()},
            {"momentum_residual_n_s",length(world.momentumResidual())},{"angular_residual_kg_m2_s",length(world.angularResidual())},
            {"numerical_energy_j",world.numericalEnergy()},{"initial_energy_j",world.initialEnergy()},
            {"wall_s",std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()}}.dump()<<'\n'<<std::flush;
    }return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
