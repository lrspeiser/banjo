#include "material/MaterialCatalog.hpp"
#include "material/ConnectorPlasticity.hpp"
#include "physics/CohesiveInterface.hpp"
#include "physics/MaterialWrench.hpp"
#include "physics/NormalComplianceKernel.hpp"
#include "material/ConnectorModeKernel.hpp"
#include "physics/MaterialHistoryKernel.hpp"
#include "physics/CoupledGpuKernel.hpp"
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
Json frame(const Json &j){
    auto read=[](const Json &r){
        const auto p=r.at("com").get<std::array<double,3>>(),l=r.at("anchor").get<std::array<double,3>>();
        const auto q=r.at("orientation").get<std::array<double,4>>(),f=r.at("frame").get<std::array<double,4>>();
        return MaterialFrame{{p[0],p[1],p[2]},{l[0],l[1],l[2]},{q[0],q[1],q[2],q[3]},{f[0],f[1],f[2],f[3]}};
    };
    const auto a=read(j.at("a")),b=read(j.at("b"));const auto loads=j.at("loads").get<std::array<double,6>>();
    const auto c=materialCoordinates(a,b);const auto w=materialWrenches(a,b,loads);
    auto v=[](FrameVector p){return Json::array({p.x,p.y,p.z});};
    return {{"q",c.q},{"wrenches",Json::array({v(w.force_a),v(w.torque_a),v(w.force_b),v(w.torque_b)})}};
}
Json coupled(const Json &input){
    const auto b=input.at("bodies").get<std::vector<std::array<double,dgBodyWidth>>>();
    const auto e=input.at("edges").get<std::vector<std::array<double,dgEdgeWidth>>>();
    const auto v=input.at("velocity").get<std::vector<std::array<double,6>>>();
    if(b.empty()||b.size()>dgMaxBodies||e.size()>dgMaxEdges||v.size()!=b.size())throw std::invalid_argument("invalid coupled trial size");
    for(const auto &row:b){for(const auto x:row)if(!std::isfinite(x))throw std::invalid_argument("nonfinite coupled body");
        if(row[0]<0||row[0]>2||row[0]!=std::floor(row[0])||row[1]<0||row[2]<0||row[3]<=0||(row[0]==0&&row[1]>0)||(row[1]>0&&row[2]<=0))throw std::invalid_argument("invalid coupled body properties");
        for(unsigned j=4;j<7;++j)if(row[j]<=0)throw std::invalid_argument("invalid coupled half extent");
        for(const unsigned start:{10u,26u}){double norm=0;for(unsigned j=0;j<4;++j)norm+=row[start+j]*row[start+j];if(fabs(norm-1)>1e-10)throw std::invalid_argument("invalid coupled unit frame");}
        for(unsigned j=0;j<3;++j)if(fabs(row[7+j]-(row[20+j]+row[23+j]))>1e-12)throw std::invalid_argument("inconsistent coupled reference position");
        if(row[1]>0&&row[0]==1&&(row[4]!=row[5]||row[4]!=row[6]))throw std::invalid_argument("dynamic boxes require isotropic cube inertia");}
    for(const auto &row:e){for(const auto x:row)if(!std::isfinite(x))throw std::invalid_argument("nonfinite coupled edge");
        if(row[0]<0||row[1]<0||row[0]>=b.size()||row[1]>=b.size()||row[0]==row[1]||row[0]!=std::floor(row[0])||row[1]!=std::floor(row[1])||row[3]<=0||row[2]<0||row[2]>2||row[2]!=std::floor(row[2]))throw std::invalid_argument("invalid coupled edge");
        for(const unsigned start:{10u,14u}){double norm=0;for(unsigned j=0;j<4;++j)norm+=row[start+j]*row[start+j];if(fabs(norm-1)>1e-10)throw std::invalid_argument("invalid coupled attachment frame");}
        if(row[2]==1){for(unsigned j=23;j<35;++j)if(row[j]<=0)throw std::invalid_argument("invalid plastic coefficient");}
        else {if(row[18]<=0||row[19]<=0||row[20]<=0||row[21]<=0||row[22]<0||(row[2]==2&&row[23]<=0))throw std::invalid_argument("invalid cohesive coefficient");}}
    const double h=input.at("dt_s").get<double>();const auto g=input.at("gravity").get<std::array<double,3>>();
    if(!std::isfinite(h)||h<=0||h>1)throw std::invalid_argument("invalid coupled dt");
    for(const auto &row:v)for(double x:row)if(!std::isfinite(x))throw std::invalid_argument("invalid coupled velocity");
    for(double x:g)if(!std::isfinite(x))throw std::invalid_argument("invalid coupled gravity");
    if(input.at("op")=="contact_schedule"){
        const double phase=input.at("phase").get<double>(),tolerance=input.at("velocity_tolerance_m_s").get<double>();
        if(!std::isfinite(phase)||phase<=0||phase>1||!std::isfinite(tolerance)||tolerance<0)throw std::invalid_argument("invalid contact timestep policy");
        Json rows=Json::array();
        for(unsigned a=0;a<b.size();++a)for(unsigned c=a+1;c<b.size();++c){
            if(b[a][1]==0&&b[c][1]==0)continue;
            const auto pa=dgPrepareTrial(b[a].data(),v[a].data(),h),pc=dgPrepareTrial(b[c].data(),v[c].data(),h);
            const auto r=dgContactSchedule(b[a].data(),b[c].data(),pa.initial,pc.initial,pa.ending,pc.ending,h,phase,tolerance);
            rows.push_back({{"pair",{a,c}},{"step_s",r.step_s},{"frequency_rad_s",r.frequency_rad_s},{"excitation_m_s",r.excitation_m_s}});
        }
        return {{"schedules",rows}};
    }
    std::vector<std::array<double,7>> poses(b.size());std::vector<std::array<double,6>> residual(b.size()),forces(b.size());
    std::vector<std::array<double,32>> history(e.size());std::array<double,dgLedgerWidth> ledger;
    const int fault=coupledTrialUnchecked(b.front().data(),static_cast<unsigned>(b.size()),e.empty()?nullptr:e.front().data(),static_cast<unsigned>(e.size()),v.front().data(),h,{g[0],g[1],g[2]},poses.front().data(),residual.front().data(),history.empty()?nullptr:history.front().data(),forces.front().data(),ledger.data());
    return {{"fault",fault},{"poses",poses},{"residual",residual},{"forces",forces},{"history",history},{"ledger",ledger}};
}
}
int main(){std::string line;while(std::getline(std::cin,line))try{
    const auto input=Json::parse(line);const auto op=input.at("op");
    if(op=="catalog")std::cout<<Json{{"ok",true},{"profiles",catalog()}}.dump()<<'\n';
    else if(op=="advance")std::cout<<Json{{"ok",true},{"states",advance(input)}}.dump()<<'\n';
    else if(op=="frames"){
        const auto &lanes=input.at("lanes");if(!lanes.is_array()||lanes.size()>65536)throw std::invalid_argument("invalid frame count");
        Json out=Json::array();for(const auto &lane:lanes)out.push_back(frame(lane));
        std::cout<<Json{{"ok",true},{"frames",out}}.dump()<<'\n';
    }
    else if(op=="coupled"||op=="contact_schedule")std::cout<<Json{{"ok",true},{"trial",coupled(input)}}.dump()<<'\n';
    else throw std::invalid_argument("unknown oracle command");
}catch(const std::exception &e){std::cout<<Json{{"ok",false},{"error",e.what()}}.dump()<<'\n';}}
