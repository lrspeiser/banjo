#include "fastlattice/SolidMatterPatch.hpp"
#include "material/MaterialCatalog.hpp"
#include "numeric/FpProfile.hpp"
#include <nlohmann/json.hpp>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <numeric>
#include <set>
#include <stdexcept>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;
using Json = nlohmann::json;
Json vector(Vec3 v) { return Json::array({v.x,v.y,v.z}); }
Vec3 at(const std::vector<double> &v,unsigned i) {return {v[3*i],v[3*i+1],v[3*i+2]};}
Json frame(const SolidMatterPatch &patch) {
    const auto &s=patch.state();const auto r=patch.report();
    Json nodes=Json::array(),bonds=Json::array();
    std::vector<unsigned> group(s.node_count);
    std::vector<bool> attached(s.node_count);
    for(const auto &part:patch.components()) {
        const auto id=part.cells.front().source_node;
        for(const auto &cell:part.cells) {group[cell.source_node]=id;attached[cell.source_node]=part.attached_to_boundary;}
    }
    for(unsigned i=0;i<s.node_count;++i)
        nodes.push_back({{"id",i},{"position_m",vector(s.origin+at(s.x0,i)+at(s.u,i))},
            {"displacement_m",vector(at(s.u,i))},{"velocity_m_s",vector(at(s.v,i))},
            {"mass_kg",s.mass[i]},{"component",group[i]},{"attached",attached[i]},
            {"clamped",s.inv_mass[i]==0}});
    for(unsigned o=0;o<s.bond_count;++o) {
        const auto k=patch.schedule().bond_schedule_index[o];
        bonds.push_back(Json::array({s.alive[k]!=0,s.damage[k]}));
    }
    return {{"step",r.accepted_steps},{"time_s",r.time_s},{"phase",r.accepted_steps<=512?"loading":"released"},
        {"nodes",std::move(nodes)},{"bond_state",std::move(bonds)},{"components",patch.components().size()},
        {"mass_kg",r.mass_kg},{"volume_m3",r.volume_m3},{"work_j",r.source_work_j},
        {"positive_work_j",r.positive_source_work_j},{"kinetic_j",r.kinetic_j},{"elastic_j",r.elastic_j},
        {"removed_bond_energy_j",r.removed_bond_energy_j},{"integration_error_j",r.integration_error_j},
        {"energy_residual_j",r.energy_residual_j},{"broken_bonds",r.broken_bonds},
        {"support_impulse_n_s",vector(r.boundary_impulse_n_s)},
        {"source_impulse_n_s",vector(r.source_impulse_n_s)},
        {"source_angular_impulse_kg_m2_s",vector(r.source_angular_impulse_kg_m2_s)},
        {"support_angular_impulse_kg_m2_s",vector(r.boundary_angular_impulse_kg_m2_s)},
        {"bond_roundoff_impulse_n_s",vector(r.bond_roundoff_impulse_n_s)},
        {"bond_roundoff_angular_kg_m2_s",vector(r.bond_roundoff_angular_kg_m2_s)},
        {"momentum_residual_n_s",vector(r.momentum_residual_kg_m_s)},
        {"angular_residual_kg_m2_s",vector(r.angular_residual_kg_m2_s)}};
}
double requestScale(const char *path) {
    std::ifstream input(path,std::ios::binary|std::ios::ate);
    if(!input || input.tellg()<0 || input.tellg()>1024)
        throw std::invalid_argument("request must be an accessible JSON file of at most 1024 bytes");
    input.seekg(0);
    std::set<std::string> keys;
    const Json request=Json::parse(input,[&keys](int depth,Json::parse_event_t event,Json &value) {
        if(depth==1 && event==Json::parse_event_t::key && !keys.insert(value.get<std::string>()).second)
            throw std::invalid_argument("repeated request field");
        return true;
    });
    if(!request.is_object() || request.size()!=2 ||
       request.value("schema",std::string{})!="banjo.material-lab-request.v1" ||
       !request.contains("force_scale") || !request["force_scale"].is_number())
        throw std::invalid_argument("unsupported experiment request fields/schema");
    const auto scale=request["force_scale"].get<double>();
    if(!std::isfinite(scale) || (scale!=.25 && scale!=.5 && scale!=1 && scale!=1.25))
        throw std::invalid_argument("force_scale must be 0.25, 0.5, 1 or 1.25");
    return scale;
}
Json experiment(MaterialPreset preset,bool strong,double scale) {
    const auto material=makeReferenceMaterial(preset,17);
    std::vector<unsigned> clamps;
    for(unsigned z=0;z<5;++z)for(unsigned x=0;x<5;++x)clamps.push_back(x+25*z);
    SolidMatterPatch patch("material-lab:block",{.25,.25,.25},.05,material,{},.1,1e-7,clamps);
    const Vec3 force=(strong?Vec3{0,1e6,0}:Vec3{10000,-20000,30000})*scale;
    std::vector<Vec3> input(125);input[72]=force; // top-centre source cell
    Json frames=Json::array();frames.push_back(frame(patch));
    const auto started=std::chrono::steady_clock::now();
    double remaining=50000;
    Json topology=Json::array();
    for(unsigned o=0;o<patch.state().bond_count;++o) {
        const auto k=patch.schedule().bond_schedule_index[o];
        topology.push_back(Json::array({patch.state().bond_a[k],patch.state().bond_b[k]}));
    }
    for(unsigned chunk=0;chunk<20;++chunk) {
        const auto result=patch.pulse(chunk<16?input:std::vector<Vec3>(125),32,remaining);
        if(result.accepted_steps!=32)throw std::runtime_error("bounded experiment exhausted work budget");
        remaining-=result.positive_work_j;frames.push_back(frame(patch));
    }
    return {{"id",std::string(materialPresetName(preset))+":"+(strong?"pull":"load")},
        {"material",materialPresetName(preset)},{"interaction",strong?"pull":"load"},
        {"density_kg_m3",material.density_kg_m3},{"young_modulus_pa",material.young_modulus_pa},
        {"tensile_strength_pa",material.tensile_strength_pa},{"cell_m",.05},{"dimensions_m",vector({.25,.25,.25})},
        {"force_n",vector(force)},{"loaded_node",72},{"load_steps",512},{"total_steps",640},
        {"dt_s",patch.report().timestep_s},{"positive_work_ceiling_j",50000},
        {"solver_wall_s",std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count()},
        {"bond_topology",std::move(topology)},{"frames",std::move(frames)}};
}
}
int main(int argc,char **argv) {
    try {
        if(argc!=2 && !(argc==4 && std::string(argv[1])=="--request"))
            throw std::invalid_argument("usage: banjo_material_lab_record [--request REQUEST.json] OUTPUT.json");
        const double scale=argc==4?requestScale(argv[2]):1;
        const char *output=argv[argc-1];
        Json runs=Json::array();
        for(bool strong:{false,true})for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})
            runs.push_back(experiment(material,strong,scale));
        Json out={{"schema","banjo.material-lab-recording.v2"},{"kind","solver-recording"},
            {"request",{{"schema","banjo.material-lab-request.v1"},{"force_scale",scale}}},
            {"backend","serial-double CPU Verlet"},{"fp_profile",fp::profile()},
            {"model","existing isotropic elastic central-bond strength reference"},
            {"boundary","25 positive-mass stationary bottom-face clamps"},
            {"gravity_m_s2",vector({})},{"damping",0},{"seed",17},
            {"limits",Json::array({"No self/contact/settling solver in this experiment", "No grain, plasticity, fatigue or calibrated crack work in this wrapper", "High laboratory force, not hand/tool calibration", "Recorded replay, not live world physics"})},
            {"experiments",std::move(runs)}};
        std::ofstream file(output,std::ios::binary|std::ios::trunc);
        if(!file)throw std::runtime_error("cannot open experiment recording output");
        file<<out.dump();file.close();if(!file)throw std::runtime_error("experiment recording write failed");
        std::cout<<"Recorded six matched material experiments, 21 frames each.\n";
        return 0;
    } catch(const std::exception &error) {std::cerr<<error.what()<<'\n';return 1;}
}
