#include "material/MaterialCatalog.hpp"
#include "material/ConnectorPlasticity.hpp"
#include "physics/CohesiveInterface.hpp"
#include <nlohmann/json.hpp>
#include <array>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
using namespace banjo;
using Json=nlohmann::json;
namespace {
MaterialPreset preset(const std::string &name){
    if(name=="glass")return MaterialPreset::Glass;
    if(name=="oak")return MaterialPreset::Oak;
    if(name=="iron")return MaterialPreset::Iron;
    if(name=="ice")return MaterialPreset::Ice;
    throw std::invalid_argument("unsupported oracle material");
}
CohesiveInterfaceLaw law(const MaterialDefinition &m){
    // Same explicit interface coupon shape as cohesive_interface_tests.cpp.
    // This stiffness is NOT inferred bulk elasticity or oak grain failure.
    return {2*m.tensile_strength_pa*m.tensile_strength_pa/m.fracture_energy_j_m2,
        m.tensile_strength_pa,m.fracture_energy_j_m2,.0001,0};
}
Json catalog(){
    Json result=Json::array();
    for(const auto name:{"glass","oak","iron","ice"}){
        const auto m=makeReferenceMaterial(preset(name));const auto l=law(m);
        Json row{{"material",name},{"density_kg_m3",m.density_kg_m3},{"young_pa",m.young_modulus_pa},
            {"cell_size_m",.01},{"cohesive_law",{l.stiffness_pa_per_m,l.strength_pa,l.fracture_energy_j_m2,l.area_m2,l.compression_stiffness_pa_per_m}},
            {"display_model",std::string(name)=="iron"?"connector-plastic":"normal-cohesive"}};
        if(std::string(name)=="iron"){
            const auto p=compileConnectorPlasticity(m,.01,.01,.01);
            row["connector_stiffness"]=p.stiffness;row["connector_yield_load"]=p.yield_load;
        }
        result.push_back(row);
    }
    return result;
}
Json advance(const Json &input){
    const auto &lanes=input.at("lanes");if(!lanes.is_array()||lanes.size()>65536)throw std::invalid_argument("invalid lane count");
    Json output=Json::array();
    for(const auto &lane:lanes){
        const auto m=makeReferenceMaterial(preset(lane.at("material").get<std::string>()));
        const auto s=lane.at("state").get<std::array<double,32>>();auto o=s;
        const auto q=lane.at("coordinates").get<std::array<double,6>>();
        for(double x:s)if(!std::isfinite(x))throw std::invalid_argument("invalid oracle state");
        if(lane.at("model")=="normal-cohesive"){
            const auto r=advanceCohesiveInterface(law(m),{s[0],s[1]},q[0]);
            o[0]=r.state.opening_m;o[1]=r.state.maximum_opening_m;
            o[2]=r.response.force_n;o[3]=r.response.stored_energy_j;o[4]=r.response.dissipated_energy_j;
            o[5]=r.response.damage;o[6]=r.response.separated?1:0;o[7]+=r.opening_work_j;
            o[8]=r.opening_work_j;o[9]=r.dissipated_increment_j;o[10]=r.balance_residual_j;o[11]=r.work_conjugate_force_n;
        }else if(lane.at("model")=="connector-plastic"){
            const auto p=compileConnectorPlasticity(m,.01,.01,.01);ConnectorPlasticState old;
            for(unsigned i=0;i<6;++i){old.plastic_rest[i]=s[i];old.accumulated_flow[i]=s[6+i];}
            old.plastic_dissipation_j=s[12];old.return_excess_j=s[13];old.yielded_updates=static_cast<std::uint64_t>(s[14]);
            double work=0;
            for(unsigned i=0;i<6;++i){const double before=s[22+i]-s[i],after=q[i]-s[i];work+=(.5*p.stiffness[i])*(after+before)*(after-before);}
            const auto r=advanceConnectorPlasticity(p,old,q);
            for(unsigned i=0;i<6;++i){o[i]=r.state.plastic_rest[i];o[6+i]=r.state.accumulated_flow[i];o[22+i]=q[i];}
            o[12]=r.state.plastic_dissipation_j;o[13]=r.state.return_excess_j;o[14]=static_cast<double>(r.state.yielded_updates);
            o[15]=r.stored_energy_j;o[16]+=work;o[17]=work;
            o[18]=work-(r.stored_energy_j-s[15])-r.plastic_increment_j-r.return_excess_increment_j;
            o[19]=p.stiffness[0]*(q[0]-r.state.plastic_rest[0]);o[20]=r.plastic_increment_j;o[21]=r.return_excess_increment_j;
        }else throw std::invalid_argument("unknown oracle model");
        output.push_back(o);
    }
    return output;
}
}
int main(){std::string line;while(std::getline(std::cin,line))try{
    const auto input=Json::parse(line);const auto op=input.at("op");
    if(op=="catalog")std::cout<<Json{{"ok",true},{"profiles",catalog()}}.dump()<<'\n';
    else if(op=="advance")std::cout<<Json{{"ok",true},{"states",advance(input)}}.dump()<<'\n';
    else throw std::invalid_argument("unknown oracle command");
}catch(const std::exception &e){std::cout<<Json{{"ok",false},{"error",e.what()}}.dump()<<'\n';}}
