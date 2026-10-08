#include "platform/PlatformWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include <nlohmann/json.hpp>
#include <cmath>
#include <iostream>
#include <memory>
#include <string>

using namespace banjo;
using Json=nlohmann::json;
namespace {
Json vec(Vec3 p){return {p.x,p.y,p.z};}
MaterialPreset preset(const std::string &name){
    for(auto p:kMaterialPresets)if(materialSceneName(p)==name)return p;
    throw std::invalid_argument("unknown catalog material");
}
Json material(MaterialPreset p){
    const auto m=makeReferenceMaterial(p);const auto triple=[](double v){return Json{v,v,v};};
    return {{"id",materialSceneName(p)},{"density_kg_m3",m.density_kg_m3},
        {"young_modulus_pa",triple(m.young_modulus_pa)},{"tensile_strength_pa",triple(m.tensile_strength_pa)},
        {"fracture_energy_j_m2",triple(m.fracture_energy_j_m2)},{"damping_ratio",m.damping_ratio},
        {"friction",m.dynamic_friction},{"contact_damping_ratio",m.contact_damping_ratio},
        {"yield_strength_pa",m.yield_strength_pa},{"fracture_enabled",m.model==MaterialModel::BrittleBond},
        {"failure_law",m.model==MaterialModel::BrittleBond?"brittle":"cohesive"},
        {"color_rgb",p==MaterialPreset::Glass?0x68bbd2:p==MaterialPreset::Oak?0xae794d:0x889baa},
        {"provenance","Catalog properties mapped to the experimental isotropic axial network. No continuum, grain or J2 calibration."}};
}
Json object(unsigned id,const char *name,MaterialPreset m,const char *shape,const char *representation,Vec3 dimensions,Vec3 position){
    return {{"id",id},{"name",name},{"material",materialSceneName(m)},{"shape",shape},
        {"representation",representation},{"dimensions_m",vec(dimensions)},{"position_m",vec(position)},
        {"orientation_wxyz",{1,0,0,0}},{"velocity_m_s",{0,0,0}},{"spin_rad_s",{0,0,0}}};
}
Json declaration(const Json &r){
    const auto target=preset(r.at("sheet").get<std::string>()),ball=preset(r.at("ball").get<std::string>());
    const double mass=r.value("mass_kg",1.0),height=r.value("height_m",10.0),offset=r.value("offset_m",0.0);
    const auto mode=r.value("mode",std::string("deformable"));const bool deformable=mode=="deformable";
    const double speed=r.value("speed_m_s",0.0);
    if(!std::isfinite(mass)||mass<.1||mass>5||!std::isfinite(height)||height<0||height>10||
       !std::isfinite(offset)||std::abs(offset)>.08||!std::isfinite(speed)||speed<0||speed>15||
       (mode!="rigid"&&!deformable))throw std::invalid_argument("drop declaration outside admitted bounds");
    // 32 of the 4^3 equal-volume cells lie inside this ellipsoid. Its mass
    // comes from their occupied material volume, not a sphere mass override.
    const double occupied_fraction=deformable?.5:3.141592653589793/6;
    const double diameter=std::cbrt(mass/(makeReferenceMaterial(ball).density_kg_m3*occupied_fraction));
    auto sheet=object(1,"Sheet",target,"box",deformable?"network":"rigid",{.24,.08,.24},{0,.54,0});
    auto projectile=object(2,"Ball",ball,deformable?"ellipsoid":"sphere",deformable?"network":"rigid",{diameter,diameter,diameter},
        {offset,(deformable?.5796:.58)+height+(deformable?.4975:.5)*diameter,0});
    projectile["velocity_m_s"]={0,-speed,0};
    if(deformable){sheet["resolution"]={6,2,6};projectile["resolution"]={4,4,4};}
    Json materials=Json::array();for(auto p:kMaterialPresets)if(p==target||p==ball||p==MaterialPreset::Iron)materials.push_back(material(p));
    return {{"package_version",2},{"physics_abi","banjo-network-2"},{"backend","material-network-v2"},
        {"name","Shared native drop world"},{"units","SI"},{"required_capabilities",{"gravity","contact","cell-deformation","cohesive-damage"}},
        {"fixed_dt_s",deformable?1./4800:1./240},{"max_steps_per_call",4},{"solver_iterations",96},{"gravity_m_s2",{0,-9.81,0}},
        {"contact_budget",{{"body_pairs",4096},{"constraints",2048}}},
        {"ground",{{"half_length_m",2},{"half_width_m",2},{"friction",.4}}},{"materials",materials},
        {"objects",{sheet,projectile,object(3,"Left post",MaterialPreset::Iron,"box","rigid",{.06,.5,.3},{-.10,.25,0}),
             object(4,"Right post",MaterialPreset::Iron,"box","rigid",{.06,.5,.3},{.10,.25,0})}}};
}
Json snapshot(PlatformWorld &world,const Json &input){
    auto report=Json::parse(world.reportJson());report.erase("package");Json cells=Json::array(),bonds=Json::array();
    for(const auto &i:world.renderInstances()){const auto q=i.state.orientation_world;
        cells.push_back({{"object_id",i.object_id},{"element_id",i.element_id},{"component_id",i.component_id},
            {"shape",i.geometry.kind==PrimitiveKind::Box?"box":"sphere"},{"radius_m",i.geometry.radius_m},
            {"dimensions_m",vec(i.geometry.dimensions_m)},{"position_m",vec(i.state.center_of_mass_world_m)},
            {"orientation_wxyz",{q.w,q.x,q.y,q.z}},{"velocity_m_s",vec(i.state.linear_velocity_m_s)},
            {"angular_velocity_rad_s",vec(i.state.angular_velocity_rad_s)},
            {"material",i.material_id},{"deformable",i.deformable_cell}});}
    for(const auto &b:world.renderBonds())if(b.live)bonds.push_back({{"a",b.a_element},{"b",b.b_element},{"object_id",b.object_id},{"damage",b.damage}});
    return {{"schema","banjo.shared-world.v1"},{"declaration",input},{"instances",cells},{"bonds",bonds},{"report",report},
        {"qualification",{{"release_ready",false},{"reason","Experimental axial network; full contact/work accounting, cell-frame bending and refinement remain open."}}}};
}
}
int main(int argc,char **argv){
    if(argc!=2||std::string(argv[1])!="--serve")return 1;
    std::unique_ptr<PlatformWorld> world;Json input;unsigned steps=0;std::string line;
    while(std::getline(std::cin,line))try{
        Json frames=Json::array();
        if(line.size()>4096)throw std::invalid_argument("intention exceeds byte budget");const auto r=Json::parse(line);const auto op=r.at("op").get<std::string>();
        if(op=="create") {auto candidate=PlatformWorld::load(declaration(r).dump());world=std::move(candidate);input=r;steps=0;}
        else if(op=="advance") {if(!world)throw std::invalid_argument("create a world first");const unsigned n=r.value("steps",1U);
            if(n<1||n>4||steps+n>12000)throw std::invalid_argument("world step budget exceeded");
            for(unsigned i=0;i<n;++i){const auto receipt=world->step(1);steps+=receipt.completed_steps;
                if(!receipt.error.empty())throw std::runtime_error(receipt.error);
                const auto frame=snapshot(*world,input);frames.push_back({{"time_s",receipt.elapsed_s},{"instances",frame["instances"]}});}}
        else if(op!="snapshot")throw std::invalid_argument("unknown world intention");
        if(!world)throw std::invalid_argument("create a world first");
        std::cout<<Json{{"ok",true},{"state",snapshot(*world,input)},{"frames",frames}}.dump()<<'\n'<<std::flush;
    }catch(const std::exception &e){Json error{{"ok",false},{"error",e.what()}};if(world)error["state"]=snapshot(*world,input);std::cout<<error.dump()<<'\n'<<std::flush;}
}
