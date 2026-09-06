#include "world/SparseThermalWorld.hpp"
#include "world/WorldPackage.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;
using Json=nlohmann::json;

void require(bool condition,std::string_view message){if(!condition)throw std::runtime_error(std::string(message));}
void near(double actual,double expected,double tolerance,std::string_view message){
    if(!std::isfinite(actual)||std::abs(actual-expected)>tolerance)throw std::runtime_error(std::string(message)+": actual="+std::to_string(actual)+" expected="+std::to_string(expected));}

WorldThermalMaterial material(unsigned id,std::string name,double density,double heat_capacity,double conductivity){
    return {.id=id,.solid_density_kg_m3=density,.thermal={.display_name=std::move(name),.specific_heat_capacity_j_kg_k=heat_capacity,.thermal_conductivity_w_m_k=conductivity}};
}
WorldThermalMaterial reactiveOak(unsigned id){
    auto oak=material(id,"oak",700.,1700.,.12);oak.fuel_mass_fraction=.5;oak.oxygen_kg_per_kg_solid=.5;
    oak.thermal.reaction={.enabled=true,.activation_temperature_k=350.,.maximum_rate_per_s=.5,.heat_of_combustion_j_kg=100000.,.oxygen_required_kg_per_kg_fuel=1.};
    return oak;
}
WorldThermalMaterial water(unsigned id){
    auto result=material(id,"water / ice",1000.,2100.,.6);
    result.phase_change=thermal::EnthalpyMaterial{.solid_heat_capacity_j_kg_k=2100.,.liquid_heat_capacity_j_kg_k=4180.,.melting_temperature_k=273.15,.latent_heat_j_kg=334000.};
    return result;
}
WorldStepBudget generous(){return {.maximum_jobs=4096,.maximum_cell_operations=10000000,.maximum_wall_ms=1000.};}
const ThermalCellView &cellAt(const std::vector<ThermalCellView> &cells,const VoxelAddress &address){
    const auto found=std::find_if(cells.begin(),cells.end(),[&](const auto &cell){return cell.address==address;});
    if(found==cells.end())throw std::runtime_error("expected active cell is missing");return *found;
}
const Json &region(const Json &report,unsigned id){
    const auto found=std::find_if(report["regions"].begin(),report["regions"].end(),[&](const auto &entry){return entry["id"]==id;});
    if(found==report["regions"].end())throw std::runtime_error("expected region report is missing");return *found;
}
ThermalFrontierPolicy policy(double threshold,unsigned probes=64,unsigned additions=8,unsigned pending=128){
    return {.activation_temperature_difference_k=threshold,.maximum_face_probes_per_step=probes,.maximum_cells_added_per_step=additions,.maximum_pending_cells=pending};
}

void optInMixedMaterialGrowthConductsWithoutResettingHistory(){
    SparseThermalWorld world(.1);
    world.addMaterial(material(1,"glass",2500.,840.,1.));
    world.addMaterial(material(2,"oak",700.,1700.,.12));
    world.addMaterial(material(3,"iron",7870.,450.,80.));
    world.addUniformChunk({0,0,0},1,300.);world.addUniformChunk({2,0,0},2,300.);world.addUniformChunk({4,0,0},3,300.);
    const std::vector<VoxelAddress> seeds{{{0,0,0},8,8,8},{{2,0,0},8,8,8},{{4,0,0},8,8,8}};
    world.activateInsulatedRegion(7,seeds,.05);
    for(const auto &seed:seeds)(void)world.addHeat(seed,1000000.,1000000.,0.);
    world.enableThermalFrontier(7,policy(100.,18,18,32),0.);
    const auto receipt=world.advance(.05,generous());
    require(receipt.error.empty()&&receipt.completed_jobs==1&&receipt.frontier_face_probes==18&&receipt.frontier_cells_added==18,
        "mixed frontier must scan six faces and activate bounded cold neighbors");
    const auto cells=world.activeCells();require(cells.size()==21,"three seeds must each activate six unique cold neighbors");
    for(unsigned id=1;id<=3;++id)require(std::count_if(cells.begin(),cells.end(),[&](const auto &cell){return cell.material==id;})==7,
        "glass, oak, and iron identities must survive mixed frontier growth");
    for(const auto &seed:seeds){
        const auto neighbor=VoxelAddress{seed.chunk,seed.x+1,seed.y,seed.z};
        require(cellAt(cells,neighbor).temperature_k>300.,"new glass/oak/iron cells must conduct on their first same-clock step");
    }
    const auto report=Json::parse(world.reportJson());const auto &r=region(report,7);
    near(r["mass_residual_kg"].get<double>(),0.,1e-12,"cold-to-active mass enters the region reference ledger");
    near(r["combined_energy_residual_j"].get<double>(),0.,1e-6,"cold-to-active energy is retained without external heat");
    require(r["frontier"]["cold_to_active"]["mass_kg"].get<double>()>0.&&
        r["frontier"]["cold_to_active"]["combined_energy_j"].get<double>()>0.&&
        r["external_work_j"].get<double>()==3000000.,
        "promotion ledger must remain separate from explicit heater work");
}

void repeatedGrowthPreservesReactionProductsAndExistingCellState(){
    SparseThermalWorld world(.1);world.addMaterial(reactiveOak(2));world.addUniformChunk({0,0,0},2,300.);
    const VoxelAddress seed{{0,0,0},8,8,8};world.activateInsulatedRegion(3,{seed},.1);
    (void)world.addHeat(seed,1000000.,1000000.,0.);world.enableThermalFrontier(3,policy(50.,6,1,16),0.);
    const auto first=world.advance(.1,generous());require(first.frontier_cells_added==1,"first bounded frontier step adds one cell");
    const auto first_cells=world.activeCells();const double fuel_after_first=cellAt(first_cells,seed).fuel_kg;
    const double products_after_first=region(Json::parse(world.reportJson()),3)["products_kg"].get<double>();
    require(products_after_first>0.,"reactive seed must retain explicit reaction products");
    (void)world.advance(.1,generous());(void)world.advance(.1,generous());
    const auto cells=world.activeCells();require(cells.size()==4,"growth limit must add one compact cold cell per accepted step");
    require(cellAt(cells,seed).fuel_kg<fuel_after_first,"existing seed reaction history must continue rather than reinitialize");
    const auto report=Json::parse(world.reportJson());const auto &r=region(report,3);
    require(r["products_kg"].get<double>()>products_after_first&&r["frontier"]["cells_added"]==3,
        "products and cumulative frontier history must survive repeated growth");
    near(r["combined_energy_residual_j"].get<double>(),0.,1e-6,"repeated reaction and promotion combined-energy audit");
}

void negativeCrossChunkIceActivationRetainsMassAndEnthalpy(){
    SparseThermalWorld world(.1);world.addMaterial(material(3,"iron",7870.,450.,80.));world.addMaterial(water(4));
    world.addUniformChunk({-1,0,0},4,273.15,.1);world.addUniformChunk({0,0,0},3,1000.);
    const VoxelAddress iron{{0,0,0},0,0,0};const VoxelAddress ice{{-1,0,0},15,0,0};
    world.activateInsulatedRegion(11,{iron},.1);world.enableThermalFrontier(11,policy(10.,1,1,4),0.);
    const auto receipt=world.advance(.1,generous());require(receipt.frontier_cells_added==1,"negative-coordinate cross-chunk neighbor must activate");
    const auto cells=world.activeCells();const auto &water_cell=cellAt(cells,ice);
    require(water_cell.material==4&&water_cell.phase_change&&water_cell.liquid_fraction>.1,
        "activated ice must keep water identity, latent state, and receive iron enthalpy");
    const auto report=Json::parse(world.reportJson());const auto &r=region(report,11);
    near(r["mass_kg"].get<double>(),8.87,1e-12,"iron plus promoted water mass");
    near(r["frontier"]["cold_to_active"]["mass_kg"].get<double>(),1.,1e-12,"promoted water mass ledger");
    require(r["frontier"]["cold_to_active"]["thermal_enthalpy_j"].get<double>()>0.,
        "promoted phase enthalpy must be explicit");
    near(r["combined_energy_residual_j"].get<double>(),0.,1e-6,"phase promotion and conduction conserve enthalpy");
}

void missingAndOtherRegionFacesRemainInsulatedAndReported(){
    SparseThermalWorld world(1.);world.addMaterial(material(1,"unit",1.,1.,1.));
    world.addUniformChunk({0,0,0},1,600.);world.addUniformChunk({1,0,0},1,300.);
    const VoxelAddress missing_edge{{0,0,0},0,4,4},boundary{{0,0,0},15,4,4},other{{1,0,0},0,4,4};
    world.activateInsulatedRegion(1,{missing_edge,boundary},.1);world.activateInsulatedRegion(2,{other},.1);
    world.enableThermalFrontier(1,policy(400.,12,4,8),0.);
    const auto receipt=world.advance(.1,generous());require(receipt.error.empty()&&world.activeCellCount()==3,
        "missing and other-region faces must neither fabricate matter nor implicitly join regions");
    const auto report=Json::parse(world.reportJson());const auto &first=region(report,1);
    require(first["frontier"]["blocked"]["missing_chunk_face_observations"].get<unsigned>()>0&&
        first["frontier"]["blocked"]["other_active_region_face_observations"].get<unsigned>()>0,
        "missing storage and an existing active region must be distinct blocked reasons");
    const auto &approximation=first["frontier"]["omitted_flux_approximation"];
    require(approximation["deferred_faces_are_insulated"]&&
        !approximation["global_heat_error_bound_available"].get<bool>()&&
        approximation["estimate_is_instantaneous"]&&
        approximation["last_other_region_heat_rate_estimate_w"].get<double>()>0.,
        "blocked-face flux must be labeled as an instantaneous estimate, not a heat-error bound");
    require(region(report,2)["cells"]==1&&first["boundary"].get<std::string>().find("insulated")!=std::string::npos,
        "other active region remains a separate same-clock island");
}

void operationBudgetAndStalePolicyCommandsAreAtomic(){
    SparseThermalWorld world(1.);world.addMaterial(material(1,"unit",1.,1.,1.));world.addUniformChunk({0,0,0},1,300.);
    const VoxelAddress seed{{0,0,0},8,8,8};world.activateInsulatedRegion(1,{seed},.1);(void)world.addHeat(seed,300.,300.,0.);
    bool rejected=false;try{world.enableThermalFrontier(1,policy(1.,0,1,1),0.);}catch(const std::invalid_argument &){rejected=true;}
    require(rejected&&!Json::parse(world.reportJson())["regions"][0]["frontier"]["enabled"].get<bool>(),
        "invalid frontier policy must reject before mutation");
    world.enableThermalFrontier(1,policy(1.,6,1,8),0.);
    const auto before=world.activeCells();const auto deferred=world.advance(.1,{.maximum_jobs=1,.maximum_cell_operations=1,.maximum_wall_ms=1000.});
    require(deferred.completed_jobs==0&&deferred.count_budget_exhausted&&deferred.frontier_regions_budget_blocked==1&&deferred.regions_late==1,
        "frontier copy, lookup, edge, and solve bound must fit before an atomic job starts");
    require(world.activeCellCount()==1&&cellAt(world.activeCells(),seed).region_time_s==0.,
        "budget exhaustion leaves accepted state and active set unchanged");
    const auto caught_up=world.advance(0.,generous());require(caught_up.completed_jobs==1&&caught_up.frontier_cells_added==1,
        "later budget catches up the deferred frontier and thermal job");
    rejected=false;try{world.enableThermalFrontier(1,policy(1.),0.);}catch(const std::invalid_argument &){rejected=true;}
    require(rejected&&world.activeCellCount()==2&&cellAt(world.activeCells(),seed).region_time_s==.1,
        "stale repeated policy command rejects without changing grown state or clock");
    near(cellAt(before,seed).fuel_kg,cellAt(world.activeCells(),seed).fuel_kg,0.,"passive seed state remains stable across rejection");
}

void compactStoredVolumeDoesNotChangeFrontierWork(){
    auto configure=[](SparseThermalWorld &world,unsigned extra_chunks){
        world.addMaterial(material(1,"unit",1.,1.,1.));world.addUniformChunk({0,0,0},1,300.);
        for(unsigned i=0;i<extra_chunks;++i)world.addUniformChunk({int(i)+2,0,0},1,300.);
        const VoxelAddress seed{{0,0,0},8,8,8};world.activateInsulatedRegion(1,{seed},.1);(void)world.addHeat(seed,300.,300.,0.);
        world.enableThermalFrontier(1,policy(1.,2,1,4),0.);
    };
    SparseThermalWorld small(1.),large(1.);configure(small,0);configure(large,128);
    const auto small_receipt=small.advance(.1,generous()),large_receipt=large.advance(.1,generous());
    require(small_receipt.cell_operations==large_receipt.cell_operations&&small_receipt.frontier_face_probes==large_receipt.frontier_face_probes&&
        small_receipt.frontier_cells_added==large_receipt.frontier_cells_added,
        "direct-neighbor frontier work must be independent of unrelated compact stored volume");
    const auto small_report=Json::parse(small.reportJson()),large_report=Json::parse(large.reportJson());
    require(large_report["represented_voxels"].get<std::uint64_t>()>small_report["represented_voxels"].get<std::uint64_t>()&&
        small_report["performance"]["cold_chunks_scanned_per_advance"]==0&&large_report["performance"]["cold_chunks_scanned_per_advance"]==0,
        "larger cold storage remains compact and unscanned");
}

Json packageWithFrontier(){
    return {{"physics_abi","banjo-thermal-world-1"},{"units","SI"},{"voxel_size_m",1.},
        {"materials",Json::array({{{"id",1},{"name","unit"},{"density_kg_m3",1.},{"heat_capacity_j_kg_k",1.},{"conductivity_w_m_k",1.}}})},
        {"chunks",Json::array({{{"position",{0,0,0}},{"material",1},{"temperature_k",300.}}})},
        {"regions",Json::array({{{"id",1},{"step_s",.1},{"cells",Json::array({{{"chunk",{0,0,0}},{"local",{8,8,8}}}})},
            {"frontier",{{"activation_temperature_difference_k",10.},{"maximum_face_probes_per_step",6},{"maximum_cells_added_per_step",1},{"maximum_pending_cells",8}}}}})}};
}
void strictPackageFrontierFieldsAreUnitBearing(){
    auto world=loadWorldPackage(packageWithFrontier().dump());const auto report=Json::parse(world->reportJson());
    require(report["regions"][0]["frontier"]["enabled"]&&report["regions"][0]["frontier"]["policy"]["activation_temperature_difference_k"]==10.,
        "closed package must publish the explicit SI frontier policy");
    auto unknown=packageWithFrontier();unknown["regions"][0]["frontier"]["scan_magic"]=1;
    bool rejected=false;try{(void)loadWorldPackage(unknown.dump());}catch(const std::invalid_argument &){rejected=true;}
    require(rejected,"unknown frontier package field must reject");
    auto zero=packageWithFrontier();zero["regions"][0]["frontier"]["maximum_pending_cells"]=0;
    rejected=false;try{(void)loadWorldPackage(zero.dump());}catch(const std::invalid_argument &){rejected=true;}
    require(rejected,"zero frontier work bound must reject");
}

void growFirstStepMatchesFullyPreactivatedSameDomain(){
    const std::vector<WorldThermalMaterial> materials{
        material(1,"glass",2500.,840.,1.),
        material(2,"oak",700.,1700.,.12),
        material(3,"iron",7870.,450.,80.),
        water(4),
    };
    for(const auto &declared:materials){
        SparseThermalWorld grown(.1),preactivated(.1);
        grown.addMaterial(declared);preactivated.addMaterial(declared);
        const double initial_temperature=declared.phase_change?273.15:300.;
        const double initial_fraction=declared.phase_change?.1:0.;
        grown.addUniformChunk({0,0,0},declared.id,initial_temperature,initial_fraction);
        preactivated.addUniformChunk({0,0,0},declared.id,initial_temperature,initial_fraction);
        const VoxelAddress seed{{0,0,0},8,8,8},neighbor{{0,0,0},7,8,8};
        grown.activateInsulatedRegion(1,{seed},.1);
        preactivated.activateInsulatedRegion(1,{seed,neighbor},.1);
        const double heater_work=declared.phase_change?500000.:100000.;
        (void)grown.addHeat(seed,heater_work,heater_work,0.);
        (void)preactivated.addHeat(seed,heater_work,heater_work,0.);
        grown.enableThermalFrontier(1,policy(1.,1,1,2),0.);
        const auto grown_receipt=grown.advance(.1,generous());
        const auto reference_receipt=preactivated.advance(.1,generous());
        require(grown_receipt.error.empty()&&reference_receipt.error.empty()&&grown_receipt.frontier_cells_added==1,
            "grow-first and preactivated comparison jobs must complete");
        const auto grown_cells=grown.activeCells(),reference_cells=preactivated.activeCells();
        for(const auto address:std::vector<VoxelAddress>{seed,neighbor}){
            const auto &actual=cellAt(grown_cells,address),&expected=cellAt(reference_cells,address);
            require(actual.material==expected.material&&actual.phase_change==expected.phase_change,
                "grow-first oracle compares by address and preserves material/phase identity");
            near(actual.temperature_k,expected.temperature_k,1e-12,"grow-first temperature matches fully preactivated domain");
            near(actual.liquid_fraction,expected.liquid_fraction,1e-12,"grow-first phase state matches fully preactivated domain");
            near(actual.fuel_kg,expected.fuel_kg,1e-12,"grow-first fuel state matches fully preactivated domain");
            near(actual.oxygen_kg,expected.oxygen_kg,1e-12,"grow-first oxygen state matches fully preactivated domain");
        }
        const auto grown_report=Json::parse(grown.reportJson()),reference_report=Json::parse(preactivated.reportJson());
        near(region(grown_report,1)["thermal_enthalpy_j"].get<double>(),region(reference_report,1)["thermal_enthalpy_j"].get<double>(),
            1e-7,"grow-first total enthalpy matches fully preactivated domain");
        near(region(grown_report,1)["combined_energy_residual_j"].get<double>(),0.,1e-7,
            "grow-first same-domain energy audit");
    }
}

void omittedFrontierRetainsLegacyInsulatedDefault(){
    SparseThermalWorld world(1.);world.addMaterial(material(1,"unit",1.,1.,1.));world.addUniformChunk({0,0,0},1,300.);
    const VoxelAddress hot{{0,0,0},8,8,8},cold{{0,0,0},9,8,8};
    world.activateInsulatedRegion(1,{hot,cold},.1);(void)world.addHeat(hot,300.,300.,0.);
    const auto receipt=world.advance(.1,generous());const auto cells=world.activeCells();
    const double decay=std::exp(-.2);
    near(cellAt(cells,hot).temperature_k,450.+150.*decay,1e-12,"legacy insulated hot-cell oracle");
    near(cellAt(cells,cold).temperature_k,450.-150.*decay,1e-12,"legacy insulated cold-cell oracle");
    require(world.activeCellCount()==2&&receipt.frontier_face_probes==0&&receipt.frontier_cells_added==0,
        "omitted frontier policy performs no activation work");
    const auto report=Json::parse(world.reportJson());const auto &r=region(report,1);
    require(!r["frontier"]["enabled"].get<bool>()&&r["boundary"]=="explicitly insulated"&&r["frontier"]["face_probes"]==0,
        "omitted package/API frontier remains the explicit legacy insulated boundary");
}
}

int main(){
    const std::vector<std::pair<std::string_view,std::function<void()>>> tests{
        {"mixed material cold-neighbor conduction",optInMixedMaterialGrowthConductsWithoutResettingHistory},
        {"repeated growth preserves history",repeatedGrowthPreservesReactionProductsAndExistingCellState},
        {"negative cross-chunk phase activation",negativeCrossChunkIceActivationRetainsMassAndEnthalpy},
        {"missing and other-region boundaries",missingAndOtherRegionFacesRemainInsulatedAndReported},
        {"frontier budget and stale commands",operationBudgetAndStalePolicyCommandsAreAtomic},
        {"stored-volume independent work",compactStoredVolumeDoesNotChangeFrontierWork},
        {"strict frontier package schema",strictPackageFrontierFieldsAreUnitBearing},
        {"grow-first equals preactivated domain",growFirstStepMatchesFullyPreactivatedSameDomain},
        {"omitted frontier legacy default",omittedFrontierRetainsLegacyInsulatedDefault},
    };
    unsigned failures=0;for(const auto &[name,test]:tests){try{test();std::cout<<"[PASS] "<<name<<'\n';}
        catch(const std::exception &error){++failures;std::cerr<<"[FAIL] "<<name<<": "<<error.what()<<'\n';}}
    std::cout<<tests.size()-failures<<'/'<<tests.size()<<" tests passed\n";return failures==0?EXIT_SUCCESS:EXIT_FAILURE;
}
