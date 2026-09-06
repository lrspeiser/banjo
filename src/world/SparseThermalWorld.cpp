#include "world/SparseThermalWorld.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <map>
#include <stdexcept>
#include <tuple>

namespace banjo {
namespace {
using json=nlohmann::json;
void require(bool ok,const char *message){if(!ok)throw std::invalid_argument(message);}
void address(VoxelAddress a){require(a.x<16&&a.y<16&&a.z<16,"voxel coordinate outside 16-cube chunk");}
std::tuple<int,int,int> global(VoxelAddress a){return {a.chunk.x*16+int(a.x),a.chunk.y*16+int(a.y),a.chunk.z*16+int(a.z)};}
}
struct SparseThermalWorld::Impl {
    struct Chunk {unsigned material;double temperature,liquid_fraction_at_melt;};
    struct Cell {VoxelAddress address;unsigned material;thermal::LumpState state;double phase_enthalpy_j{};};
    struct Edge {unsigned a,b;double conductance;};
    struct Region {
        unsigned id;double dt,time,initial_energy,initial_mass,external_work{},reaction_heat{};
        std::vector<Cell> cells;std::vector<Edge> edges;
        unsigned jobs{};double maximum_step_energy_residual{};
        unsigned cost() const {return unsigned(cells.size()*2+edges.size()*2);}
    };
    double size,requested_time{},maximum_wall{},total_wall{};
    unsigned next_region{},calls{},total_jobs{};
    double peak_lag{};unsigned peak_late_regions{},count_limited_calls{},wall_limited_calls{};
    std::map<unsigned,WorldThermalMaterial> materials;
    std::map<ChunkAddress,Chunk> chunks;
    std::map<VoxelAddress,std::pair<unsigned,unsigned>> locations;
    std::vector<Region> regions;
    // A join permanently adds cells to one active island, so these histories
    // are bounded by the world's 32,768 permanent active-cell budget.
    std::vector<unsigned> retired_region_ids;
    std::vector<ThermalRegionJoinReceipt> joins;
    std::vector<double> timings;
    std::size_t cell_count{};
    WorldStepReceipt last;
    double thermalEnergy(const Cell &c) const{return materials.at(c.material).phase_change?c.phase_enthalpy_j:c.state.sensible_energy_j;}
    double temperature(const Cell &c) const{auto &m=materials.at(c.material);return m.phase_change?thermal::stateFromEnthalpy(*m.phase_change,c.phase_enthalpy_j/c.state.mass_kg).temperature_k:thermal::temperatureK(c.state);}
    double liquidFraction(const Cell &c) const{auto &m=materials.at(c.material);return m.phase_change?thermal::stateFromEnthalpy(*m.phase_change,c.phase_enthalpy_j/c.state.mass_kg).liquid_fraction:0;}
    thermal::EnthalpyMaterial phaseLaw(const Cell &c) const{const auto &m=materials.at(c.material);const double cp=c.state.reference_heat_capacity_j_k/c.state.mass_kg;return m.phase_change.value_or(thermal::EnthalpyMaterial{cp,cp,273.15,0});}
    void thermalEnergy(Cell &c,double value){if(materials.at(c.material).phase_change)c.phase_enthalpy_j=value;else c.state.sensible_energy_j=value;}
    double energy(const Cell &cell) const{return thermalEnergy(cell)+thermal::totalChemicalEnergyJ(cell.state,materials.at(cell.material).thermal);}
    double energy(const Region &r) const{double sum=0;for(auto &c:r.cells)sum+=energy(c);return sum;}
    void step(Region &r){
        auto candidate=r.cells;double heat=0;
        auto react=[&](double dt){for(auto &cell:candidate){if(materials.at(cell.material).phase_change)continue;const auto update=thermal::reactAdiabatic(cell.state,materials.at(cell.material).thermal,dt);cell.state=update.state;heat+=update.released_heat_j;}};
        // Symmetric operator splitting. Pair exchange is exact; this whole
        // graph is NOT an exact network solve, especially across ignition.
        react(r.dt/2);
        auto exchange=[&](const Edge &edge){
            auto &a=candidate[edge.a],&b=candidate[edge.b];
            if(materials.at(a.material).phase_change||materials.at(b.material).phase_change){
                const auto update=thermal::exchangePairBackwardEuler(phaseLaw(a),{a.state.mass_kg,thermalEnergy(a)/a.state.mass_kg},phaseLaw(b),{b.state.mass_kg,thermalEnergy(b)/b.state.mass_kg},edge.conductance,r.dt/2);
                thermalEnergy(a,update.first.enthalpy_j_kg*a.state.mass_kg);thermalEnergy(b,update.second.enthalpy_j_kg*b.state.mass_kg);
            }else{auto update=thermal::exchangePairExact(a.state,b.state,edge.conductance,r.dt/2);a.state=update.first;b.state=update.second;}
        };
        for(auto &edge:r.edges)exchange(edge);
        for(auto it=r.edges.rbegin();it!=r.edges.rend();++it)exchange(*it);
        react(r.dt/2);
        const double before=energy(r);double after=0,mass=0;
        for(auto &cell:candidate){after+=energy(cell);mass+=cell.state.mass_kg;}
        require(std::abs(after-before)<=1e-10*std::max(1.,std::abs(before)),"thermal step failed combined energy audit");
        require(std::abs(mass-r.initial_mass)<=1e-12*std::max(1.,r.initial_mass),"thermal step failed mass audit");
        r.maximum_step_energy_residual=std::max(r.maximum_step_energy_residual,std::abs(after-before));
        r.cells=std::move(candidate);r.time+=r.dt;r.reaction_heat+=heat;++r.jobs;
    }
};
SparseThermalWorld::SparseThermalWorld(double size):impl_(std::make_unique<Impl>()){
    require(std::isfinite(size)&&size>=.001&&size<=10,"invalid voxel size");impl_->size=size;
}
SparseThermalWorld::~SparseThermalWorld()=default;
void SparseThermalWorld::addMaterial(WorldThermalMaterial material){
    auto &w=*impl_;require(w.materials.size()<256&&material.id>0&&!w.materials.contains(material.id),"material ID or registry budget invalid");
    require(std::isfinite(material.solid_density_kg_m3)&&material.solid_density_kg_m3>0&&material.solid_density_kg_m3<=30000,"invalid solid density");
    require(std::isfinite(material.fuel_mass_fraction)&&material.fuel_mass_fraction>=0&&material.fuel_mass_fraction<=1,"invalid fuel fraction");
    require(std::isfinite(material.oxygen_kg_per_kg_solid)&&material.oxygen_kg_per_kg_solid>=0&&material.oxygen_kg_per_kg_solid<=10,"invalid finite oxygen reservoir");
    thermal::validateMaterial(material.thermal);
    if(material.phase_change){
        thermal::validateEnthalpyMaterial(*material.phase_change);
        require(!material.thermal.reaction.enabled&&material.fuel_mass_fraction==0&&material.oxygen_kg_per_kg_solid==0,
            "combined reaction/phase law is not implemented; phase matter requires no reactive reservoirs");
        require(material.thermal.specific_heat_capacity_j_kg_k==material.phase_change->solid_heat_capacity_j_kg_k,"phase solid heat capacity must match thermal declaration");
    }
    (void)thermal::makeLumpFromSolidMass(material.thermal,293.15,1,material.fuel_mass_fraction,material.oxygen_kg_per_kg_solid);
    w.materials.emplace(material.id,std::move(material));
}
void SparseThermalWorld::addUniformChunk(ChunkAddress a,unsigned material,double temperature,double fraction){
    auto &w=*impl_;require(w.chunks.size()<1000000&&!w.chunks.contains(a),"chunk budget exceeded or duplicate");
    require(std::abs(std::int64_t(a.x))<=1000000&&std::abs(std::int64_t(a.y))<=1000000&&std::abs(std::int64_t(a.z))<=1000000,"chunk coordinate outside world bounds");
    require(w.materials.contains(material)&&std::isfinite(temperature)&&temperature>=0&&temperature<=10000,"invalid chunk material/temperature");
    require(std::isfinite(fraction)&&fraction>=0&&fraction<=1,"invalid melt fraction");
    require(w.materials.at(material).phase_change.has_value()||fraction==0,"liquid fraction requires phase law");
    require(fraction==0||temperature==w.materials.at(material).phase_change->melting_temperature_k,"nonzero melt fraction must be initialized at melting temperature");
    w.chunks.emplace(a,Impl::Chunk{material,temperature,fraction});
}
void SparseThermalWorld::activateInsulatedRegion(unsigned id,const std::vector<VoxelAddress>& cells,double dt){
    auto &w=*impl_;require(id>0&&w.regions.size()<256&&std::none_of(w.regions.begin(),w.regions.end(),[&](auto &r){return r.id==id;})&&
        std::find(w.retired_region_ids.begin(),w.retired_region_ids.end(),id)==w.retired_region_ids.end(),"invalid, active, or retired region ID, or region budget exceeded");
    require(!cells.empty()&&cells.size()<=512&&w.cell_count+cells.size()<=32768,"active thermal cell budget exceeded");
    require(std::isfinite(dt)&&dt>=.001&&dt<=1,"invalid thermal step");
    Impl::Region r{id,dt,w.requested_time,0,0};
    std::map<std::tuple<int,int,int>,unsigned> indices;
    for(auto a:cells){address(a);require(w.chunks.contains(a.chunk)&&!w.locations.contains(a),"missing chunk or overlapping active region");
        require(indices.emplace(global(a),unsigned(r.cells.size())).second,"duplicate region voxel");
        const auto &chunk=w.chunks.at(a.chunk);const auto &m=w.materials.at(chunk.material);
        const double solidMass=m.solid_density_kg_m3*w.size*w.size*w.size;
        auto state=thermal::makeLumpFromSolidMass(m.thermal,chunk.temperature,solidMass,m.fuel_mass_fraction,solidMass*m.oxygen_kg_per_kg_solid);
        double enthalpy=0;if(m.phase_change){const auto &law=*m.phase_change;
            const double fraction=chunk.temperature==law.melting_temperature_k?chunk.liquid_fraction_at_melt:(chunk.temperature>law.melting_temperature_k?1.:0.);
            enthalpy=state.mass_kg*thermal::enthalpyFromTemperaturePhase(law,chunk.temperature,fraction);
        }
        r.cells.push_back({a,chunk.material,state,enthalpy});r.initial_mass+=state.mass_kg;
    }
    for(auto &[key,a]:indices){auto [x,y,z]=key;
        for(auto other:std::vector<std::tuple<int,int,int>>{{x+1,y,z},{x,y+1,z},{x,y,z+1}}){auto it=indices.find(other);if(it==indices.end())continue;
            const unsigned b=it->second;const double conductance=thermal::interfaceConductanceWPerK(w.materials.at(r.cells[a].material).thermal,w.materials.at(r.cells[b].material).thermal,w.size*w.size,w.size);
            r.edges.push_back({a,b,conductance});}
    }
    r.initial_energy=w.energy(r);
    const unsigned region=unsigned(w.regions.size());
    w.regions.push_back(std::move(r));
    for(unsigned i=0;i<cells.size();++i)w.locations.emplace(cells[i],std::pair{region,i});
    w.cell_count+=cells.size();
}
ThermalRegionJoinReceipt SparseThermalWorld::joinInsulatedRegions(unsigned firstId,unsigned secondId,double expected){
    auto &w=*impl_;require(firstId!=secondId,"thermal region join requires distinct IDs");
    const auto firstIt=std::find_if(w.regions.begin(),w.regions.end(),[&](const auto &r){return r.id==firstId;});
    const auto secondIt=std::find_if(w.regions.begin(),w.regions.end(),[&](const auto &r){return r.id==secondId;});
    require(firstIt!=w.regions.end()&&secondIt!=w.regions.end(),"thermal region join requires two active region IDs");
    const auto firstIndex=std::size_t(firstIt-w.regions.begin()),secondIndex=std::size_t(secondIt-w.regions.begin());
    const auto &first=*firstIt;const auto &second=*secondIt;
    require(std::isfinite(expected)&&std::abs(expected-first.time)<1e-12&&std::abs(expected-second.time)<1e-12,
        "thermal region join has stale or mismatched accepted time");
    require(std::abs(first.time-second.time)<1e-12&&std::abs(first.dt-second.dt)<1e-12,
        "thermal region join requires matching clocks and fixed steps");
    require(first.time+first.dt>w.requested_time+1e-12&&second.time+second.dt>w.requested_time+1e-12,
        "thermal region join requires both regions to be fully caught up");
    require(first.cells.size()+second.cells.size()<=512,"joined thermal region exceeds the 512-cell region budget");

    Impl::Region merged=first;const unsigned firstCellCount=unsigned(merged.cells.size());
    merged.cells.insert(merged.cells.end(),second.cells.begin(),second.cells.end());
    merged.initial_energy+=second.initial_energy;merged.initial_mass+=second.initial_mass;
    merged.external_work+=second.external_work;merged.reaction_heat+=second.reaction_heat;
    merged.jobs+=second.jobs;merged.maximum_step_energy_residual=std::max(merged.maximum_step_energy_residual,second.maximum_step_energy_residual);
    std::map<std::tuple<int,int,int>,unsigned> indices;
    for(unsigned i=0;i<merged.cells.size();++i)require(indices.emplace(global(merged.cells[i].address),i).second,"joined thermal regions contain duplicate cells");
    merged.edges.clear();unsigned joinedFaces=0;
    for(auto &[key,a]:indices){auto [x,y,z]=key;
        for(auto other:std::vector<std::tuple<int,int,int>>{{x+1,y,z},{x,y+1,z},{x,y,z+1}}){auto it=indices.find(other);if(it==indices.end())continue;
            const unsigned b=it->second;const double conductance=thermal::interfaceConductanceWPerK(w.materials.at(merged.cells[a].material).thermal,w.materials.at(merged.cells[b].material).thermal,w.size*w.size,w.size);
            merged.edges.push_back({a,b,conductance});joinedFaces+=(a<firstCellCount)!=(b<firstCellCount);}
    }
    require(joinedFaces>0,"thermal region join requires at least one shared voxel face");
    ThermalRegionJoinReceipt receipt{firstId,secondId,unsigned(merged.cells.size()),unsigned(merged.edges.size()),joinedFaces,first.time};

    // Build all fallible state before publishing. Swaps below commit the joined
    // region, location index, retirement record, and scheduler cursor together.
    auto candidateRegions=w.regions;candidateRegions[firstIndex]=std::move(merged);candidateRegions.erase(candidateRegions.begin()+std::ptrdiff_t(secondIndex));
    std::map<VoxelAddress,std::pair<unsigned,unsigned>> candidateLocations;
    for(unsigned ri=0;ri<candidateRegions.size();++ri)for(unsigned ci=0;ci<candidateRegions[ri].cells.size();++ci)
        require(candidateLocations.emplace(candidateRegions[ri].cells[ci].address,std::pair{ri,ci}).second,"thermal region location index is inconsistent");
    auto candidateRetired=w.retired_region_ids;candidateRetired.push_back(secondId);
    auto candidateJoins=w.joins;candidateJoins.push_back(receipt);
    const unsigned oldNextId=w.regions[w.next_region].id;
    const unsigned desiredNextId=oldNextId==secondId?firstId:oldNextId;unsigned candidateNext=0;bool foundNext=false;
    for(unsigned i=0;i<candidateRegions.size();++i)if(candidateRegions[i].id==desiredNextId){candidateNext=i;foundNext=true;break;}
    require(foundNext,"thermal region scheduler cursor is inconsistent");
    w.regions.swap(candidateRegions);w.locations.swap(candidateLocations);w.retired_region_ids.swap(candidateRetired);w.joins.swap(candidateJoins);w.next_region=candidateNext;
    return receipt;
}
double SparseThermalWorld::addHeat(VoxelAddress a,double requested,double limit,double expected){
    auto &w=*impl_;address(a);require(w.locations.contains(a),"heat requires an explicitly activated thermal region");
    const auto [ri,ci]=w.locations.at(a);auto &r=w.regions[ri];
    require(std::isfinite(expected)&&std::abs(expected-r.time)<1e-12&&r.time+r.dt>w.requested_time+1e-12,"heat command has stale time or region backlog");
    auto heaterState=r.cells[ci].state;heaterState.sensible_energy_j=w.thermalEnergy(r.cells[ci]);
    const auto update=thermal::applyBoundedHeater(heaterState,requested,limit);
    w.thermalEnergy(r.cells[ci],update.state.sensible_energy_j);r.external_work+=update.applied_work_j;return update.applied_work_j;
}
WorldStepReceipt SparseThermalWorld::advance(double elapsed,WorldStepBudget budget){
    auto &w=*impl_;require(std::isfinite(elapsed)&&elapsed>=0&&elapsed<=.25,"invalid world elapsed request");
    require(budget.maximum_jobs<=4096&&budget.maximum_cell_operations<=10000000&&std::isfinite(budget.maximum_wall_ms)&&budget.maximum_wall_ms>0&&budget.maximum_wall_ms<=1000,"invalid world work budget");
    const auto start=std::chrono::steady_clock::now();
    auto ms=[&]{return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();};
    w.requested_time+=elapsed;WorldStepReceipt receipt;receipt.requested_time_s=w.requested_time;
    unsigned examined=0;
    while(!w.regions.empty()&&examined<w.regions.size()){
        auto &r=w.regions[w.next_region];w.next_region=(w.next_region+1)%unsigned(w.regions.size());++examined;
        if(r.time+r.dt>w.requested_time+1e-12)continue;
        if(receipt.completed_jobs>=budget.maximum_jobs||receipt.cell_operations+r.cost()>budget.maximum_cell_operations){receipt.count_budget_exhausted=true;continue;}
        if(ms()>=budget.maximum_wall_ms){receipt.wall_budget_exhausted=true;break;}
        try{w.step(r);}catch(const std::exception &e){receipt.error=e.what();break;}
        ++receipt.completed_jobs;receipt.cell_operations+=r.cost();examined=0;
    }
    for(auto &r:w.regions){const double lag=std::max(0.,w.requested_time-r.time);receipt.maximum_lag_s=std::max(receipt.maximum_lag_s,lag);receipt.regions_late+=r.time+r.dt<=w.requested_time+1e-12;}
    receipt.wall_ms=ms();w.total_wall+=receipt.wall_ms;w.maximum_wall=std::max(w.maximum_wall,receipt.wall_ms);++w.calls;w.total_jobs+=receipt.completed_jobs;
    w.peak_lag=std::max(w.peak_lag,receipt.maximum_lag_s);w.peak_late_regions=std::max(w.peak_late_regions,receipt.regions_late);
    w.count_limited_calls+=receipt.count_budget_exhausted;w.wall_limited_calls+=receipt.wall_budget_exhausted;
    if(w.timings.size()<4096)w.timings.push_back(receipt.wall_ms);else w.timings[(w.calls-1)%4096]=receipt.wall_ms;
    w.last=receipt;return receipt;
}
std::vector<ThermalCellView> SparseThermalWorld::activeCells() const{
    const auto &w=*impl_;std::vector<ThermalCellView> views;views.reserve(w.cell_count);
    for(auto &r:w.regions)for(auto &c:r.cells)views.push_back({c.address,c.material,r.id,w.temperature(c),c.state.remaining_fuel_kg,c.state.available_oxygen_kg,r.time,w.liquidFraction(c),w.materials.at(c.material).phase_change.has_value()});
    return views;
}
std::uint64_t SparseThermalWorld::representedVoxelCount() const{return std::uint64_t(impl_->chunks.size())*4096;}
std::size_t SparseThermalWorld::activeCellCount() const{return impl_->cell_count;}
std::string SparseThermalWorld::reportJson() const{
    const auto &w=*impl_;json regions=json::array(),joins=json::array();double activeMass=0,energyResidual=0,work=0,heat=0;std::size_t edgeCount=0;
    for(auto &r:w.regions){double mass=0,fuel=0,oxygen=0,products=0,minT=1e30,maxT=0,liquidMass=0,enthalpy=0,chemical=0;
        for(auto &c:r.cells){mass+=c.state.mass_kg;fuel+=c.state.remaining_fuel_kg;oxygen+=c.state.available_oxygen_kg;products+=c.state.reaction_products_kg;minT=std::min(minT,w.temperature(c));maxT=std::max(maxT,w.temperature(c));liquidMass+=c.state.mass_kg*w.liquidFraction(c);enthalpy+=w.thermalEnergy(c);chemical+=thermal::totalChemicalEnergyJ(c.state,w.materials.at(c.material).thermal);}
        const double residual=w.energy(r)-r.initial_energy-r.external_work;energyResidual+=residual;activeMass+=mass;work+=r.external_work;heat+=r.reaction_heat;edgeCount+=r.edges.size();
        regions.push_back({{"id",r.id},{"cells",r.cells.size()},{"edges",r.edges.size()},{"accepted_time_s",r.time},{"lag_s",std::max(0.,w.requested_time-r.time)},{"jobs",r.jobs},{"mass_kg",mass},{"mass_residual_kg",mass-r.initial_mass},{"fuel_kg",fuel},{"oxygen_kg",oxygen},{"products_kg",products},{"temperature_min_k",minT},{"temperature_max_k",maxT},{"external_work_j",r.external_work},{"reaction_heat_j",r.reaction_heat},{"combined_energy_residual_j",residual},{"maximum_step_energy_residual_j",r.maximum_step_energy_residual},{"boundary","explicitly insulated"}});
        regions.back()["liquid_mass_kg"]=liquidMass;regions.back()["thermal_enthalpy_j"]=enthalpy;regions.back()["chemical_energy_j"]=chemical;
        const unsigned material=r.cells.front().material;
        regions.back()["material"]=std::all_of(r.cells.begin(),r.cells.end(),[&](auto &c){return c.material==material;})?w.materials.at(material).thermal.display_name:"Mixed materials";
    }
    auto times=w.timings;std::sort(times.begin(),times.end());
    for(const auto &joined:w.joins)joins.push_back({{"preserved_region_id",joined.preserved_region_id},{"retired_region_id",joined.retired_region_id},{"accepted_time_s",joined.accepted_time_s},{"cells",joined.cells},{"edges",joined.edges},{"joined_face_edges",joined.joined_face_edges}});
    auto percentile=[&](double p){return times.empty()?0:times[std::min(times.size()-1,std::size_t(std::ceil(times.size()*p)-1))];};
    // Payload accounting deliberately excludes STL allocator/node overhead.
    const auto bytes=w.chunks.size()*(sizeof(ChunkAddress)+sizeof(Impl::Chunk))+w.cell_count*sizeof(Impl::Cell)+edgeCount*sizeof(Impl::Edge);
    return json{{"backend","sparse-thermal-world-v1"},{"requested_time_s",w.requested_time},{"represented_voxels",representedVoxelCount()},{"uniform_chunks",w.chunks.size()},{"active_regions",w.regions.size()},{"active_cells",w.cell_count},{"cold_voxels",representedVoxelCount()-w.cell_count},{"physics_body_count",0},{"state_payload_bytes",bytes},{"payload_excludes_allocator_overhead",true},{"active_mass_kg",activeMass},{"external_work_j",work},{"reaction_heat_j",heat},{"combined_active_energy_residual_j",energyResidual},{"regions",regions},{"region_joins",joins},{"retired_region_ids",w.retired_region_ids},
        {"performance",{{"advance_calls",w.calls},{"completed_jobs",w.total_jobs},{"total_wall_ms",w.total_wall},{"advance_p50_ms",percentile(.5)},{"advance_p95_ms",percentile(.95)},{"advance_p99_ms",percentile(.99)},{"advance_max_ms",w.maximum_wall},{"timing_sample_window",times.size()},{"cold_chunks_scanned_per_advance",0},{"includes_rendering",false},{"peak_lag_s",w.peak_lag},{"peak_late_regions",w.peak_late_regions},{"count_limited_calls",w.count_limited_calls},{"wall_limited_calls",w.wall_limited_calls}}},
        {"last_budget",{{"jobs",w.last.completed_jobs},{"cell_operations",w.last.cell_operations},{"regions_late",w.last.regions_late},{"maximum_lag_s",w.last.maximum_lag_s},{"count_exhausted",w.last.count_budget_exhausted},{"wall_exhausted",w.last.wall_budget_exhausted},{"error",w.last.error}}},
        {"limitations",{"Explicit insulated thermal regions; only an explicit same-clock atomic join adds cross-region faces, with no cold-neighbor frontier or asynchronous exchange", "No rigid/deformable physics, airflow, smoke, radiation, volume change, liquid flow or mechanical weakening in this backend", "Fuel and finite oxygen react into retained products with constant mixture heat capacity; not validated real combustion", "Constant-capacity pair conduction is exact; phase edges use first-order backward Euler, graph splitting requires timestep convergence", "Cold storage size is not evidence of a fully simulated world; deadlines checked between bounded region jobs", "Single isothermal melt/freeze law; phase + reaction coupling is rejected, phase conductivity is held constant"}}}.dump(2);
}
}
