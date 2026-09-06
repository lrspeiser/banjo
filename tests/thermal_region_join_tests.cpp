#include "world/SparseThermalWorld.hpp"

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
    if(!std::isfinite(actual)||std::abs(actual-expected)>tolerance)throw std::runtime_error(std::string(message));
}
WorldStepBudget generousBudget(){return {.maximum_jobs=4096,.maximum_cell_operations=10'000'000,.maximum_wall_ms=1000};}
WorldThermalMaterial material(unsigned id,std::string name,double density,double heatCapacity,double conductivity){
    return {.id=id,.solid_density_kg_m3=density,.thermal={.display_name=std::move(name),.specific_heat_capacity_j_kg_k=heatCapacity,.thermal_conductivity_w_m_k=conductivity}};
}
WorldThermalMaterial water(unsigned id){
    auto value=material(id,"water / ice",1000,2100,2.2);
    value.phase_change=thermal::EnthalpyMaterial{2100,4200,273.15,334000};return value;
}
WorldThermalMaterial reactiveOak(unsigned id){
    auto value=material(id,"oak",700,1700,.12);value.fuel_mass_fraction=.5;value.oxygen_kg_per_kg_solid=.5;
    value.thermal.reaction={.enabled=true,.activation_temperature_k=600,.maximum_rate_per_s=1,.heat_of_combustion_j_kg=100'000,.oxygen_required_kg_per_kg_fuel=1};return value;
}
const ThermalCellView &cellAt(const std::vector<ThermalCellView> &cells,VoxelAddress address){
    const auto found=std::find_if(cells.begin(),cells.end(),[&](const auto &cell){return cell.address==address;});
    require(found!=cells.end(),"expected active cell is missing");return *found;
}
template<class Action> void rejectsWithoutMutation(SparseThermalWorld &world,Action action,std::string_view message){
    const auto before=world.reportJson();bool rejected=false;
    try{action();}catch(const std::invalid_argument &){rejected=true;}
    require(rejected,message);require(world.reportJson()==before,"rejected join changed observable world state");
}

void crossChunkMixedMaterialsJoinAndRouteByPreservedId(){
    SparseThermalWorld world(1);
    world.addMaterial(material(1,"glass",2500,840,1));
    world.addMaterial(reactiveOak(2));
    world.addMaterial(material(3,"iron",7870,450,80));
    world.addUniformChunk({0,0,0},1,600);
    world.addUniformChunk({1,0,0},2,700);
    world.addUniformChunk({1,-1,0},3,400);
    const VoxelAddress glass{{0,0,0},15,0,0};
    const VoxelAddress oak{{1,0,0},0,0,0};
    const VoxelAddress iron{{1,-1,0},0,15,0};
    world.activateInsulatedRegion(11,{glass},.1);
    world.activateInsulatedRegion(22,{oak,iron},.1);
    near(world.addHeat(glass,840'000,840'000,0),840'000,0,"first-region heater history");
    near(world.addHeat(iron,1000,1000,0),1000,0,"second-region heater history");
    require(world.advance(.1,generousBudget()).completed_jobs==2,"both separate regions should accept one history step");
    const auto beforeCells=world.activeCells();const auto beforeReport=Json::parse(world.reportJson());
    require(cellAt(beforeCells,oak).fuel_kg<350&&cellAt(beforeCells,oak).oxygen_kg<350,
        "reactive oak fixture should create fuel, oxygen, and product history before joining");

    const auto joined=world.joinInsulatedRegions(11,22,.1);
    require(joined.preserved_region_id==11&&joined.retired_region_id==22&&joined.cells==3&&joined.edges==2&&joined.joined_face_edges==1,
        "join receipt should name the preserved island and rebuilt cross-chunk faces");
    auto cells=world.activeCells();
    for(const auto &cell:cells)require(cell.region==11,"every joined cell should publish the preserved region ID");
    near(cellAt(cells,oak).fuel_kg,cellAt(beforeCells,oak).fuel_kg,0,"oak fuel state survives join");
    near(cellAt(cells,oak).oxygen_kg,cellAt(beforeCells,oak).oxygen_kg,0,"oak oxygen state survives join");
    const auto joinedReport=Json::parse(world.reportJson());
    for(const auto key:{"mass_kg","fuel_kg","oxygen_kg","products_kg","thermal_enthalpy_j","chemical_energy_j","external_work_j","reaction_heat_j"}){
        const double expected=beforeReport["regions"][0][key].get<double>()+beforeReport["regions"][1][key].get<double>();
        near(joinedReport["regions"][0][key].get<double>(),expected,1e-7*std::max(1.,std::abs(expected)),"joined state and accounting ledger should equal the two source ledgers");
    }
    require(joinedReport["regions"][0]["jobs"]==2,"joined island retains both source job histories");
    const auto receipt=world.advance(.1,generousBudget());
    require(receipt.completed_jobs==1&&receipt.error.empty(),"joined island should schedule as one atomic job");
    cells=world.activeCells();
    require(cellAt(cells,glass).temperature_k>cellAt(beforeCells,glass).temperature_k,
        "glass and oak should conduct through their rebuilt cross-chunk face");
    require(cellAt(cells,iron).temperature_k>400,"oak and iron should retain their pre-existing face conduction");
    near(world.addHeat(iron,1000,1000,.2),1000,0,"heat should route through the second region's former cell address");
    cells=world.activeCells();require(cellAt(cells,iron).region==11,"heated former second-region cell should still resolve to the first ID");

    const auto report=Json::parse(world.reportJson());
    require(report["active_regions"]==1&&report["regions"][0]["id"]==11&&report["regions"][0]["material"]=="Mixed materials",
        "report should expose one mixed-material insulated island");
    require(report["region_joins"].size()==1&&report["retired_region_ids"]==Json::array({22}),
        "report should retain join and retired-ID history");
    near(report["regions"][0]["external_work_j"].get<double>(),842'000,0,"joined external-work ledger");

    world.addUniformChunk({4,0,0},1,300);const VoxelAddress unused{{4,0,0},0,0,0};
    rejectsWithoutMutation(world,[&]{world.activateInsulatedRegion(22,{unused},.1);},"retired region ID should never be reused");
}

void phaseStateAndHistoryMatchPrejoinedReference(){
    SparseThermalWorld joined(1),reference(1);
    for(auto *world:{&joined,&reference}){
        world->addMaterial(water(1));
        world->addUniformChunk({0,0,0},1,273.15,.1);
        world->addUniformChunk({1,0,0},1,273.15,.9);
    }
    const VoxelAddress ice{{0,0,0},15,0,0};const VoxelAddress liquid{{1,0,0},0,0,0};
    joined.activateInsulatedRegion(7,{ice},.1);joined.activateInsulatedRegion(8,{liquid},.1);
    reference.activateInsulatedRegion(7,{ice,liquid},.1);
    require(joined.advance(.2,generousBudget()).completed_jobs==4,"separate phase regions should each advance twice");
    require(reference.advance(.2,generousBudget()).completed_jobs==2,"reference island should advance twice");
    const auto before=Json::parse(joined.reportJson());double beforeEnthalpy=0;
    for(const auto &region:before["regions"])beforeEnthalpy+=region["thermal_enthalpy_j"].get<double>();
    const auto receipt=joined.joinInsulatedRegions(7,8,.2);
    require(receipt.accepted_time_s==.2&&receipt.joined_face_edges==1,"phase join should acknowledge its exact accepted clock");
    const auto afterJoin=Json::parse(joined.reportJson());
    near(afterJoin["regions"][0]["thermal_enthalpy_j"].get<double>(),beforeEnthalpy,1e-6,"join preserves latent and sensible enthalpy");
    near(afterJoin["regions"][0]["mass_residual_kg"].get<double>(),0,1e-12,"joined initial-mass ledgers sum");
    near(afterJoin["regions"][0]["combined_energy_residual_j"].get<double>(),0,1e-6,"joined initial-energy ledgers sum");
    require(afterJoin["regions"][0]["jobs"]==4,"joined region retains both accepted-step histories");
    auto joinedCells=joined.activeCells();
    near(cellAt(joinedCells,ice).liquid_fraction,.1,1e-12,"ice fraction survives join");
    near(cellAt(joinedCells,liquid).liquid_fraction,.9,1e-12,"liquid fraction survives join");

    near(joined.addHeat(ice,100'000'000,100'000'000,.2),100'000'000,0,"joined phase heater work");
    near(reference.addHeat(ice,100'000'000,100'000'000,.2),100'000'000,0,"reference phase heater work");
    require(joined.advance(.2,generousBudget()).completed_jobs==2,"joined phase island advances two matched steps");
    require(reference.advance(.2,generousBudget()).completed_jobs==2,"prejoined reference advances two matched steps");
    joinedCells=joined.activeCells();const auto referenceCells=reference.activeCells();
    for(const auto address:{ice,liquid}){
        near(cellAt(joinedCells,address).temperature_k,cellAt(referenceCells,address).temperature_k,1e-12,
            "joined phase temperature should match prejoined reference exactly");
        near(cellAt(joinedCells,address).liquid_fraction,cellAt(referenceCells,address).liquid_fraction,1e-12,
            "joined phase fraction should match prejoined reference exactly");
    }
}

void invalidJoinsRejectBeforeMutation(){
    {
        SparseThermalWorld world(1);world.addMaterial(material(1,"unit",1,1,1));world.addUniformChunk({0,0,0},1,300);
        const VoxelAddress a{{0,0,0},0,0,0},b{{0,0,0},1,0,0},far{{0,0,0},5,0,0};
        world.activateInsulatedRegion(1,{a},.1);world.activateInsulatedRegion(2,{far},.1);
        rejectsWithoutMutation(world,[&]{(void)world.joinInsulatedRegions(1,1,0);},"same region ID join should reject");
        rejectsWithoutMutation(world,[&]{(void)world.joinInsulatedRegions(1,99,0);},"unknown region ID join should reject");
        rejectsWithoutMutation(world,[&]{(void)world.joinInsulatedRegions(1,2,0);},"regions without a shared face should reject");
        rejectsWithoutMutation(world,[&]{(void)world.joinInsulatedRegions(1,2,2e-12);},"stale expected clock should reject");
        (void)b;
    }
    {
        SparseThermalWorld world(1);world.addMaterial(material(1,"unit",1,1,1));world.addUniformChunk({0,0,0},1,300);
        const VoxelAddress a{{0,0,0},0,0,0},b{{0,0,0},1,0,0};
        world.activateInsulatedRegion(1,{a},.1);world.activateInsulatedRegion(2,{b},.2);
        rejectsWithoutMutation(world,[&]{(void)world.joinInsulatedRegions(1,2,0);},"different fixed timesteps should reject");
    }
    {
        SparseThermalWorld world(1);world.addMaterial(material(1,"unit",1,1,1));world.addUniformChunk({0,0,0},1,300);
        const VoxelAddress a{{0,0,0},0,0,0},b{{0,0,0},1,0,0};
        world.activateInsulatedRegion(1,{a},.1);world.activateInsulatedRegion(2,{b},.1);
        (void)world.advance(.1,{.maximum_jobs=0,.maximum_cell_operations=0,.maximum_wall_ms=1000});
        rejectsWithoutMutation(world,[&]{(void)world.joinInsulatedRegions(1,2,0);},"backlogged regions should reject even at their accepted clock");
    }
    {
        SparseThermalWorld world(1);world.addMaterial(material(1,"unit",1,1,1));world.addUniformChunk({0,0,0},1,300);
        const VoxelAddress a{{0,0,0},0,0,0},b{{0,0,0},1,0,0};
        world.activateInsulatedRegion(1,{a},.1);world.activateInsulatedRegion(2,{b},.1);
        const auto one=world.advance(.1,{.maximum_jobs=1,.maximum_cell_operations=10,.maximum_wall_ms=1000});
        require(one.completed_jobs==1,"clock mismatch fixture should advance only one region");
        rejectsWithoutMutation(world,[&]{(void)world.joinInsulatedRegions(1,2,.1);},"different accepted clocks should reject");
    }
    {
        SparseThermalWorld world(1);world.addMaterial(material(1,"unit",1,1,1));world.addUniformChunk({0,0,0},1,300);
        std::vector<VoxelAddress> first,second;
        for(unsigned z=0;z<2;++z)for(unsigned y=0;y<16;++y)for(unsigned x=0;x<8;++x)first.push_back({{0,0,0},x,y,z});
        for(unsigned z=0;z<2;++z)for(unsigned y=0;y<16;++y)for(unsigned x=8;x<16;++x)second.push_back({{0,0,0},x,y,z});
        second.push_back({{0,0,0},8,0,2});
        require(first.size()==256&&second.size()==257,"capacity fixture sizes");
        world.activateInsulatedRegion(1,first,.1);world.activateInsulatedRegion(2,second,.1);
        rejectsWithoutMutation(world,[&]{(void)world.joinInsulatedRegions(1,2,0);},"513-cell merged region should reject");
    }
}

void schedulerSurvivesRetiringAnEarlierVectorEntry(){
    SparseThermalWorld world(1);world.addMaterial(material(1,"unit",1,1,1));world.addUniformChunk({0,0,0},1,300);
    const VoxelAddress second{{0,0,0},1,0,0},other{{0,0,0},8,0,0},first{{0,0,0},0,0,0};
    world.activateInsulatedRegion(20,{second},.1);world.activateInsulatedRegion(30,{other},.1);world.activateInsulatedRegion(10,{first},.1);
    (void)world.joinInsulatedRegions(10,20,0);
    const auto receipt=world.advance(.1,generousBudget());
    require(receipt.completed_jobs==2&&receipt.regions_late==0,"scheduler should visit joined and unaffected regions after index compaction");
    const auto cells=world.activeCells();
    require(cellAt(cells,first).region==10&&cellAt(cells,second).region==10&&cellAt(cells,other).region==30,
        "location indices should remain correct after retiring an earlier vector entry");
}
}

int main(){
    const std::vector<std::pair<std::string_view,std::function<void()>>> tests{
        {"cross-chunk mixed join and preserved routing",crossChunkMixedMaterialsJoinAndRouteByPreservedId},
        {"phase state and prejoined equivalence",phaseStateAndHistoryMatchPrejoinedReference},
        {"invalid joins are atomic",invalidJoinsRejectBeforeMutation},
        {"scheduler compaction safety",schedulerSurvivesRetiringAnEarlierVectorEntry},
    };
    unsigned failures=0;for(const auto &[name,test]:tests){try{test();std::cout<<"[PASS] "<<name<<'\n';}catch(const std::exception &error){++failures;std::cerr<<"[FAIL] "<<name<<": "<<error.what()<<'\n';}}
    std::cout<<tests.size()-failures<<'/'<<tests.size()<<" tests passed\n";return failures==0?EXIT_SUCCESS:EXIT_FAILURE;
}
