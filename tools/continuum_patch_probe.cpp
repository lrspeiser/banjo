#include "physics/SmallStrainPatch.hpp"
#include "physics/PatchPressure.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

using namespace banjo;
using json=nlohmann::json;
namespace {
json vectorJson(Vec3 v) { return {v.x,v.y,v.z}; }
json vectorsJson(const std::vector<Vec3> &values) {json out=json::array();for(auto v:values)out.push_back(vectorJson(v));return out;}
std::vector<Vec3> readVectors(const json &values) {std::vector<Vec3> out;for(const auto &v:values)out.push_back({v[0],v[1],v[2]});return out;}
json tensorJson(const SymmetricTensor3 &v) {return {v.xx,v.yy,v.zz,v.xy,v.yz,v.zx};}
SymmetricTensor3 readTensor(const json &v) {return {v[0],v[1],v[2],v[3],v[4],v[5]};}
json stateJson(const PatchState &state) {
    json points=json::array();for(const auto &p:state.material_points)points.push_back({tensorJson(p.total_strain),tensorJson(p.plastic_strain),p.equivalent_plastic_strain,p.plastic_dissipation_j_m3});
    return {{"layout","banjo.quasistatic-tet-state.v1"},{"displacements_m",vectorsJson(state.displacements_m)},
        {"material_points",points},{"last_nodal_forces_n",vectorsJson(state.last_nodal_forces_n)},
        {"trapezoidal_external_work_j",state.accumulated_trapezoidal_external_work_j},
        {"backward_euler_external_work_j",state.accumulated_backward_euler_external_work_j},{"revision",state.revision}};
}
PatchState readState(const json &value) {
    if(value.at("layout")!="banjo.quasistatic-tet-state.v1")throw std::invalid_argument("Unsupported spatial patch state layout");
    PatchState state;state.displacements_m=readVectors(value.at("displacements_m"));state.last_nodal_forces_n=readVectors(value.at("last_nodal_forces_n"));
    for(const auto &p:value.at("material_points"))state.material_points.push_back({readTensor(p[0]),readTensor(p[1]),p[2],p[3]});
    state.accumulated_trapezoidal_external_work_j=value.at("trapezoidal_external_work_j");
    state.accumulated_backward_euler_external_work_j=value.at("backward_euler_external_work_j");state.revision=value.at("revision");return state;
}
PatchMaterial material(unsigned id) {
    PatchMaterial m;auto &law=m.law;law.maximum_total_strain_norm=.05;
    if(id==0){m.density_kg_m3=2500;law.kind=SmallStrainLawKind::IsotropicElastic;law.young_modulus_pa[0]=70e9;law.poisson_xy_yz_zx[0]=.22;}
    else if(id==1){m.density_kg_m3=700;law.kind=SmallStrainLawKind::OrthotropicElastic;
        law.young_modulus_pa={.7e9,12e9,1e9};law.poisson_xy_yz_zx={.025,.30,.30};law.shear_xy_yz_zx_pa={.6e9,.7e9,.1e9};}
    else {m.density_kg_m3=7870;law.kind=SmallStrainLawKind::J2Plastic;law.j2={ContinuumConstitutiveFamily::SmallStrainIsotropicJ2,211e9,.3,250e6,1e9,.05};}
    return m;
}
json lawJson(const PatchMaterial &m) {
    return {{"kind",m.law.kind==SmallStrainLawKind::J2Plastic?"small-strain-isotropic-j2":m.law.kind==SmallStrainLawKind::OrthotropicElastic?"orthotropic-linear-elastic":"isotropic-linear-elastic"},
        {"density_kg_m3",m.density_kg_m3},{"young_modulus_pa",m.law.young_modulus_pa},{"poisson_xy_yz_zx",m.law.poisson_xy_yz_zx},
        {"shear_xy_yz_zx_pa",m.law.shear_xy_yz_zx_pa},{"maximum_total_strain_norm",m.law.maximum_total_strain_norm},
        {"j2",{{"young_modulus_pa",m.law.j2.young_modulus_pa},{"poisson_ratio",m.law.j2.poisson_ratio},
            {"initial_yield_stress_pa",m.law.j2.initial_yield_stress_pa},{"hardening_modulus_pa",m.law.j2.isotropic_hardening_modulus_pa}}}};
}
json runCase(unsigned materialId,unsigned resolution,unsigned increments,double peakPressure,
    PatchPressureProfile profile,PatchLinearBackend backend,bool fullFrames) {
    const auto m=material(materialId);auto definition=makeTetrahedralBrick({.04,.02,.04},{resolution,std::max(1U,resolution/2),resolution},m);
    for(std::size_t i=0;i<definition.reference_positions_m.size();++i)if(definition.reference_positions_m[i].y==0)definition.fixed_components[i]={true,true,true};
    SmallStrainPatch patch(definition);PatchPressure pressure;pressure.center_m={0,.02,0};
    pressure.peak_pressure_pa=peakPressure;pressure.profile=profile;
    const auto pressureLoad=makePatchPressureLoad(patch,pressure);
    PatchLoad load=pressureLoad.load;const auto unitForces=load.nodal_forces_n;
    const double loadedArea=pressureLoad.loaded_area_m2;
    if(std::abs(loadedArea-.0004)>1e-14)throw std::invalid_argument("Pressure mesh must cover the declared 20 mm square exactly");
    PatchSolveOptions options;options.maximum_element_visits=12000000;options.linear_backend=backend;
    const std::array<std::string,3> ids{"glass","oak","iron"};
    json out{{"name",ids[materialId]+" / "+(materialId==2?"J2 load and springback":"elastic control")},
        {"material_id",ids[materialId]},{"law",lawJson(m)},{"reference_positions_m",vectorsJson(definition.reference_positions_m)},
        {"boundary_triangles",patch.boundaryTriangles()},{"elements",json::array()},{"fixed_components",definition.fixed_components},
        {"frames",json::array()},{"physical_response_validated",false},{"status","complete"},
        {"reference_volume_m3",patch.referenceVolumeM3()},{"mass_kg",patch.massKg()},{"loaded_area_m2",loadedArea},
        {"peak_pressure_pa",peakPressure},{"weighted_pressure_area_m2",pressureLoad.weighted_area_m2},
        {"peak_resultant_force_n",vectorJson(pressureLoad.resultant_force_n)},
        {"pressure_quadrature_points",pressureLoad.quadrature_points},
        {"nodes",definition.reference_positions_m.size()},{"tetrahedra",definition.elements.size()},
        {"maximum_displacement_gradient_norm",options.maximum_displacement_gradient_norm},
        {"limitations",{"Fixed-reference small-strain quasistatic mesh; no collision, inertia, fracture or finite rotation.",
            "Illustrative material parameters, not calibrated glass, wood or iron outcomes.",
            "Elastic glass/oak controls do not model strength failure; high-load survival is not a physical prediction.",
            "P1 tetrahedra can lock in near-incompressible plastic response; mesh refinement remains required."}}};
    for(const auto &tet:definition.elements)out["elements"].push_back(tet.nodes);
    double lastFraction=0,totalResidual=0;unsigned acceptedSteps=0;
    auto frame=[&](double fraction,const char *phase,const PatchSolveResult &r) {
        const auto evaluation=patch.evaluate(patch.state().displacements_m);double plastic=0,stress=0,displacement=0,yieldedVolume=0,plasticIntegral=0;
        for(std::size_t e=0;e<definition.elements.size();++e) {
            const auto &point=patch.state().material_points[e];plastic=std::max(plastic,point.equivalent_plastic_strain);
            const auto tet=definition.elements[e].nodes;const auto &x=definition.reference_positions_m;
            const double volume=dot(x[tet[1]]-x[tet[0]],cross(x[tet[2]]-x[tet[0]],x[tet[3]]-x[tet[0]]))/6;
            if(point.equivalent_plastic_strain>1e-10)yieldedVolume+=volume;
            plasticIntegral+=volume*point.equivalent_plastic_strain;
        }
        for(const auto &p:evaluation.responses)stress=std::max(stress,vonMisesEquivalentStressPa(p.stress_pa));
        for(auto d:patch.state().displacements_m)displacement=std::max(displacement,length(d));
        json record{{"load_fraction",fraction},{"phase",phase},{"accepted",r.accepted},{"error",r.error},
            {"displacements_m",vectorsJson(patch.state().displacements_m)},
            {"stored_free_energy_j",evaluation.stored_free_energy_j},{"plastic_dissipation_j",evaluation.plastic_dissipation_j},
            {"maximum_equivalent_plastic_strain",plastic},{"maximum_von_mises_stress_pa",stress},{"maximum_displacement_m",displacement},
            {"yielded_reference_volume_m3",yieldedVolume},{"equivalent_plastic_strain_volume_integral_m3",plasticIntegral},
            {"free_force_residual_n",r.free_force_residual_n},{"force_tolerance_n",r.force_tolerance_n},
            {"force_resultant_residual_n",vectorJson(r.applied_force_n+r.support_reaction_n)},
            {"reference_moment_residual_n_m",vectorJson(r.reference_moment_residual_n_m)},
            {"trapezoidal_work_residual_j",r.trapezoidal_work_residual_j},
            {"backward_euler_balance_residual_j",r.backward_euler_balance_residual_j},
            {"constitutive_backward_euler_excess_j",r.constitutive_backward_euler_excess_j},
            {"newton_iterations",r.newton_iterations},{"cg_iterations",r.cg_iterations},{"element_visits",r.element_visits},{"solve_wall_ms",r.wall_ms},
            {"tangent_block_count",r.tangent_block_count},{"tangent_assembly_element_visits",r.tangent_assembly_element_visits},
            {"matrix_free_matvec_element_visits",r.matrix_free_matvec_element_visits},{"assembled_matvec_block_visits",r.assembled_matvec_block_visits}};
        record["state_scope"]="last accepted displacement and material history";
        record["solve_diagnostics_scope"]=r.accepted?"accepted load":"failed requested load; not retained-state equilibrium";
        if(!r.accepted) {
            // These fields are filled only after convergence. Default zeros
            // from a rejected trial are not a measured equilibrium or work balance.
            for(const auto *field:{"force_resultant_residual_n","reference_moment_residual_n_m",
                "trapezoidal_work_residual_j","backward_euler_balance_residual_j","constitutive_backward_euler_excess_j"})record.erase(field);
        }
        if(!fullFrames)record.erase("displacements_m");
        return record;
    };
    PatchSolveResult initial;initial.accepted=true;out["frames"].push_back(frame(0,"initial",initial));
    for(unsigned step=1;step<=2*increments;++step) {
        const double fraction=step<=increments?double(step)/increments:double(2*increments-step)/increments;
        for(std::size_t i=0;i<unitForces.size();++i)load.nodal_forces_n[i]=unitForces[i]*fraction;
        const auto result=patch.solveLoad(load,options);auto record=frame(result.accepted?fraction:lastFraction,step<=increments?"load":"unload",result);
        record["requested_load_fraction"]=fraction;out["frames"].push_back(std::move(record));
        if(!result.accepted){out["status"]="solver_limit";out["error"]=result.error;break;}
        ++acceptedSteps;lastFraction=fraction;totalResidual+=result.trapezoidal_work_residual_j;
    }
    out["accepted_load_steps"]=acceptedSteps;out["trapezoidal_work_residual_sum_j"]=totalResidual;
    out["saved_state"]=stateJson(patch.state());
    // Exercise actual JSON save/read and all geometry/history equilibrium gates.
    const auto decoded=readState(json::parse(out["saved_state"].dump()));SmallStrainPatch restored(definition);
    restored.restoreState(decoded,.01);out["json_state_round_trip_exact"]=stateJson(restored.state()).dump()==out["saved_state"].dump();
    for(std::size_t i=0;i<unitForces.size();++i)load.nodal_forces_n[i]=unitForces[i]*(lastFraction+.01);
    const auto first=patch.solveLoad(load,options),second=restored.solveLoad(load,options);
    out["continuation"]={{"both_accepted",first.accepted&&second.accepted},{"same_state",stateJson(patch.state()).dump()==stateJson(restored.state()).dump()},
        {"scope","Same immutable mesh/law/constraints in this build. JSON is a full patch state, not compact world persistence or gameplay repair."}};
    if(!fullFrames)for(const auto *field:{"reference_positions_m","boundary_triangles","elements","fixed_components","saved_state"})out.erase(field);
    return out;
}
}

int main(int argc,char **argv) {try {
    std::filesystem::path output;unsigned resolution=4,increments=32;double peakPressure=800e6;
    auto profile=PatchPressureProfile::Uniform;auto backend=PatchLinearBackend::MatrixFreeReference;bool fullFrames=true;
    for(int i=1;i<argc;++i) {
        const std::string flag=argv[i];if(i+1>=argc)throw std::invalid_argument("Missing CLI value");const std::string value=argv[++i];std::size_t consumed=0;
        if(flag=="--output")output=value;
        else if(flag=="--resolution"){const auto v=std::stoul(value,&consumed);if(consumed!=value.size()||v<4||v>16||v%2)throw std::invalid_argument("Resolution must be an even integer in [4,16]");resolution=unsigned(v);}
        else if(flag=="--increments"){const auto v=std::stoul(value,&consumed);if(consumed!=value.size()||v<2||v>100)throw std::invalid_argument("Increments must be in [2,100]");increments=unsigned(v);}
        else if(flag=="--peak-pressure-pa"){peakPressure=std::stod(value,&consumed);if(consumed!=value.size()||!std::isfinite(peakPressure)||peakPressure<=0||peakPressure>1e9)throw std::invalid_argument("Pressure must be in (0,1e9] Pa");}
        else if(flag=="--pressure-profile"){if(value=="uniform")profile=PatchPressureProfile::Uniform;else if(value=="smooth")profile=PatchPressureProfile::Smooth;else throw std::invalid_argument("Pressure profile must be uniform or smooth");}
        else if(flag=="--linear-backend"){if(value=="matrix-free")backend=PatchLinearBackend::MatrixFreeReference;else if(value=="assembled")backend=PatchLinearBackend::AssembledBlockCsr;else throw std::invalid_argument("Linear backend must be matrix-free or assembled");}
        else if(flag=="--frames"){if(value=="full")fullFrames=true;else if(value=="summary")fullFrames=false;else throw std::invalid_argument("Frame output must be full or summary");}
        else throw std::invalid_argument("Unknown continuum CLI option");
    }
    json report{{"schema",fullFrames?"banjo.continuum-patch-trial.v1":"banjo.continuum-patch-summary.v1"},{"units","SI"},{"load_type","fixed-reference central 20 x 20 mm top-face pressure, bottom fully clamped"},
        {"physics_abi","banjo-quasistatic-tet-1"},{"physical_response_validated",false},{"real_time_qualified",false},
        {"pressure_profile",profile==PatchPressureProfile::Uniform?"uniform":"smooth"},
        {"linear_backend",backend==PatchLinearBackend::MatrixFreeReference?"matrix-free":"assembled-block-csr"},
        {"resolution",resolution},{"increments_per_load_or_unload",increments},{"cases",json::array()}};
    for(unsigned m=0;m<3;++m)report["cases"].push_back(runCase(m,resolution,increments,peakPressure,profile,backend,fullFrames));
    if(output.empty())std::cout<<report.dump(2)<<'\n';
    else {if(std::filesystem::exists(output))throw std::invalid_argument("Output must be a new file");std::ofstream file(output,std::ios::out|std::ios::noreplace);
        if(!file)throw std::runtime_error("Cannot create continuum report");file<<report.dump();file.close();if(!file)throw std::runtime_error("Cannot write continuum report");
        std::cout<<json{{"report",output.string()},{"cases",report["cases"].size()},{"physical_response_validated",false}}.dump()<<'\n';}
    return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
