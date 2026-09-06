#include "world/SparseThermalWorld.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <map>
#include <stdexcept>
#include <tuple>

namespace banjo {
namespace {
using json=nlohmann::json;
constexpr unsigned ChunkWidth=16,MaximumRegionCells=512,MaximumActiveCells=32768,MaximumFrontierProbes=3072;
void require(bool ok,const char *message){if(!ok)throw std::invalid_argument(message);}
void validateAddress(VoxelAddress a){require(a.x<ChunkWidth&&a.y<ChunkWidth&&a.z<ChunkWidth,"voxel coordinate outside 16-cube chunk");}
std::tuple<int,int,int> global(VoxelAddress a){return {a.chunk.x*16+int(a.x),a.chunk.y*16+int(a.y),a.chunk.z*16+int(a.z)};}
VoxelAddress faceNeighbor(VoxelAddress a,unsigned face){
    auto shift=[](int &chunk,unsigned &local,int direction){
        if(direction<0){if(local==0){--chunk;local=15;}else --local;}
        else if(local==15){++chunk;local=0;}else ++local;
    };
    switch(face){case 0:shift(a.chunk.x,a.x,-1);break;case 1:shift(a.chunk.x,a.x,1);break;
        case 2:shift(a.chunk.y,a.y,-1);break;case 3:shift(a.chunk.y,a.y,1);break;
        case 4:shift(a.chunk.z,a.z,-1);break;default:shift(a.chunk.z,a.z,1);break;}
    return a;
}
}

struct SparseThermalWorld::Impl {
    struct Chunk{unsigned material;double temperature,liquid_fraction_at_melt;};
    struct Cell{VoxelAddress address;unsigned material;thermal::LumpState state;double phase_enthalpy_j{};};
    struct Edge{unsigned a,b;double conductance;};
    struct FrontierCandidate{
        VoxelAddress address;double first_seen_time_s{};
        std::map<VoxelAddress,double> inspected_face_heat_rate_estimates_w;
    };
    struct Frontier{
        bool enabled{};ThermalFrontierPolicy policy;std::uint64_t probe_cursor{};
        std::deque<FrontierCandidate> pending;
        std::uint64_t scans{},face_probes{},cells_added{},below_threshold_face_observations{},
            missing_chunk_face_observations{},other_region_face_observations{},
            capacity_blocked_candidate_observations{},pending_capacity_face_observations{};
        double cold_to_active_mass_kg{},cold_to_active_energy_j{},
            cold_to_active_thermal_enthalpy_j{},cold_to_active_chemical_energy_j{};
        unsigned last_face_probes{},last_unprobed_faces{},last_cells_added{};
        double last_below_threshold_heat_rate_estimate_w{},last_other_region_heat_rate_estimate_w{};
    };
    struct Region{
        unsigned id;double dt,time,initial_energy,initial_mass,external_work{},reaction_heat{};
        std::vector<Cell> cells;std::vector<Edge> edges;unsigned jobs{};
        double maximum_step_energy_residual{};Frontier frontier;
        unsigned cost()const{return unsigned(cells.size()*2+edges.size()*2);}
    };
    struct FrontierJob{unsigned operations{},face_probes{},cells_added{};};

    double size,requested_time{},maximum_wall{},total_wall{},peak_lag{};
    unsigned next_region{},calls{},total_jobs{},peak_late_regions{},count_limited_calls{},wall_limited_calls{};
    std::map<unsigned,WorldThermalMaterial> materials;
    std::map<ChunkAddress,Chunk> chunks;
    std::map<VoxelAddress,std::pair<unsigned,unsigned>> locations;
    std::vector<Region> regions;std::vector<unsigned> retired_region_ids;
    std::vector<ThermalRegionJoinReceipt> joins;std::vector<double> timings;
    std::size_t cell_count{};WorldStepReceipt last;

    double thermalEnergy(const Cell &c)const{return materials.at(c.material).phase_change?c.phase_enthalpy_j:c.state.sensible_energy_j;}
    double temperature(const Cell &c)const{
        const auto &m=materials.at(c.material);
        return m.phase_change?thermal::stateFromEnthalpy(*m.phase_change,c.phase_enthalpy_j/c.state.mass_kg).temperature_k:thermal::temperatureK(c.state);
    }
    double liquidFraction(const Cell &c)const{
        const auto &m=materials.at(c.material);
        return m.phase_change?thermal::stateFromEnthalpy(*m.phase_change,c.phase_enthalpy_j/c.state.mass_kg).liquid_fraction:0;
    }
    thermal::EnthalpyMaterial phaseLaw(const Cell &c)const{
        const auto &m=materials.at(c.material);const double cp=c.state.reference_heat_capacity_j_k/c.state.mass_kg;
        return m.phase_change.value_or(thermal::EnthalpyMaterial{cp,cp,273.15,0});
    }
    void thermalEnergy(Cell &c,double value){if(materials.at(c.material).phase_change)c.phase_enthalpy_j=value;else c.state.sensible_energy_j=value;}
    double chemicalEnergy(const Cell &c)const{return thermal::totalChemicalEnergyJ(c.state,materials.at(c.material).thermal);}
    double energy(const Cell &c)const{return thermalEnergy(c)+chemicalEnergy(c);}
    double energy(const Region &r)const{double sum=0;for(const auto &c:r.cells)sum+=energy(c);return sum;}
    Cell makeCell(VoxelAddress a)const{
        const auto &chunk=chunks.at(a.chunk);const auto &m=materials.at(chunk.material);
        const double mass=m.solid_density_kg_m3*size*size*size;
        auto state=thermal::makeLumpFromSolidMass(m.thermal,chunk.temperature,mass,m.fuel_mass_fraction,mass*m.oxygen_kg_per_kg_solid);
        double enthalpy=0;
        if(m.phase_change){const auto &law=*m.phase_change;
            const double fraction=chunk.temperature==law.melting_temperature_k?chunk.liquid_fraction_at_melt:(chunk.temperature>law.melting_temperature_k?1.:0.);
            enthalpy=state.mass_kg*thermal::enthalpyFromTemperaturePhase(law,chunk.temperature,fraction);}
        return {a,chunk.material,state,enthalpy};
    }
    double conductance(const Cell &a,const Cell &b)const{
        return thermal::interfaceConductanceWPerK(materials.at(a.material).thermal,materials.at(b.material).thermal,size*size,size);
    }
    void step(Region &r){
        auto candidate=r.cells;double heat=0;
        auto react=[&](double dt){for(auto &cell:candidate){if(materials.at(cell.material).phase_change)continue;
            const auto update=thermal::reactAdiabatic(cell.state,materials.at(cell.material).thermal,dt);cell.state=update.state;heat+=update.released_heat_j;}};
        react(r.dt/2);
        auto exchange=[&](const Edge &edge){auto &a=candidate[edge.a],&b=candidate[edge.b];
            if(materials.at(a.material).phase_change||materials.at(b.material).phase_change){
                const auto update=thermal::exchangePairBackwardEuler(phaseLaw(a),{a.state.mass_kg,thermalEnergy(a)/a.state.mass_kg},
                    phaseLaw(b),{b.state.mass_kg,thermalEnergy(b)/b.state.mass_kg},edge.conductance,r.dt/2);
                thermalEnergy(a,update.first.enthalpy_j_kg*a.state.mass_kg);thermalEnergy(b,update.second.enthalpy_j_kg*b.state.mass_kg);
            }else{const auto update=thermal::exchangePairExact(a.state,b.state,edge.conductance,r.dt/2);a.state=update.first;b.state=update.second;}};
        for(const auto &edge:r.edges)exchange(edge);for(auto it=r.edges.rbegin();it!=r.edges.rend();++it)exchange(*it);react(r.dt/2);
        const double before=energy(r);double after=0,mass=0;for(const auto &cell:candidate){after+=energy(cell);mass+=cell.state.mass_kg;}
        require(std::abs(after-before)<=1e-10*std::max(1.,std::abs(before)),"thermal step failed combined energy audit");
        require(std::abs(mass-r.initial_mass)<=1e-12*std::max(1.,r.initial_mass),"thermal step failed mass audit");
        r.maximum_step_energy_residual=std::max(r.maximum_step_energy_residual,std::abs(after-before));
        r.cells=std::move(candidate);r.time+=r.dt;r.reaction_heat+=heat;++r.jobs;
    }
    unsigned frontierCostBound(const Region &r)const{
        if(!r.frontier.enabled)return r.cost();
        const auto &p=r.frontier.policy;const unsigned faces=unsigned(r.cells.size()*6);
        const unsigned probes=std::min(p.maximum_face_probes_per_step,faces);
        const unsigned pending=std::min(p.maximum_pending_cells,unsigned(r.frontier.pending.size())+probes);
        const unsigned additions=std::min({p.maximum_cells_added_per_step,MaximumRegionCells-unsigned(r.cells.size()),MaximumActiveCells-unsigned(cell_count),pending});
        // Existing solve + region copy + local/pending indexes + bounded probes
        // + six adjacency checks per candidate + initialization, up to six
        // edge inserts and enlarged solve per admitted cell.
        const unsigned staged_copy=unsigned(r.cells.size()+r.edges.size()+r.frontier.pending.size());
        const unsigned local_indexes=unsigned(r.cells.size()+r.frontier.pending.size());
        return r.cost()+staged_copy+local_indexes+probes+6*pending+22*additions;
    }
    FrontierJob growFrontier(Region &r)const{
        FrontierJob job;auto &f=r.frontier;if(!f.enabled||r.cells.empty())return job;
        f.last_face_probes=f.last_cells_added=0;f.last_below_threshold_heat_rate_estimate_w=f.last_other_region_heat_rate_estimate_w=0;
        std::map<VoxelAddress,unsigned> local;for(unsigned i=0;i<r.cells.size();++i)local.emplace(r.cells[i].address,i);
        std::map<VoxelAddress,unsigned> pending_lookup;for(unsigned i=0;i<f.pending.size();++i)pending_lookup.emplace(f.pending[i].address,i);
        job.operations+=unsigned(r.cells.size()+f.pending.size());
        const unsigned initial_count=unsigned(r.cells.size());const std::uint64_t face_count=std::uint64_t(initial_count)*6;
        const unsigned probes=std::min(f.policy.maximum_face_probes_per_step,unsigned(face_count));
        for(unsigned probe=0;probe<probes;++probe){
            const std::uint64_t position=(f.probe_cursor+probe)%face_count;const unsigned source_index=unsigned(position/6),face=unsigned(position%6);
            const auto &source=r.cells[source_index];const auto neighbor=faceNeighbor(source.address,face);++job.operations;++job.face_probes;
            if(local.contains(neighbor))continue;
            if(const auto active=locations.find(neighbor);active!=locations.end()){
                const auto &[other_region,other_cell]=active->second;
                if(regions[other_region].id!=r.id){const auto &other=regions[other_region].cells[other_cell];
                    f.last_other_region_heat_rate_estimate_w+=conductance(source,other)*std::abs(temperature(source)-temperature(other));
                    ++f.other_region_face_observations;}continue;}
            if(!chunks.contains(neighbor.chunk)){++f.missing_chunk_face_observations;continue;}
            const Cell cold=makeCell(neighbor);const double difference=std::abs(temperature(source)-temperature(cold));
            const double estimate=conductance(source,cold)*difference;
            if(difference<f.policy.activation_temperature_difference_k){++f.below_threshold_face_observations;f.last_below_threshold_heat_rate_estimate_w+=estimate;continue;}
            const auto pending=pending_lookup.find(neighbor);
            if(pending==pending_lookup.end()){if(f.pending.size()>=f.policy.maximum_pending_cells){++f.pending_capacity_face_observations;continue;}
                const unsigned index=unsigned(f.pending.size());f.pending.push_back({neighbor,r.time,{{source.address,estimate}}});pending_lookup.emplace(neighbor,index);}
            else f.pending[pending->second].inspected_face_heat_rate_estimates_w[source.address]=estimate;
        }
        f.probe_cursor=face_count?(f.probe_cursor+probes)%face_count:0;f.last_face_probes=probes;f.last_unprobed_faces=unsigned(face_count)-probes;
        ++f.scans;f.face_probes+=probes;
        const unsigned to_examine=unsigned(f.pending.size());
        for(unsigned examined=0;examined<to_examine;++examined){
            if(f.pending.empty()||job.cells_added>=f.policy.maximum_cells_added_per_step)break;
            auto candidate=std::move(f.pending.front());f.pending.pop_front();
            if(local.contains(candidate.address))continue;
            if(locations.contains(candidate.address)){++f.other_region_face_observations;continue;}
            if(!chunks.contains(candidate.address.chunk)){++f.missing_chunk_face_observations;continue;}
            const Cell cold=makeCell(candidate.address);double maximum_difference=0,estimate=0,other_region_estimate=0;bool other_region=false;
            std::vector<unsigned> neighbors;neighbors.reserve(6);
            for(unsigned face=0;face<6;++face){++job.operations;const auto adjacent=faceNeighbor(candidate.address,face);
                if(const auto found=local.find(adjacent);found!=local.end()){const auto &source=r.cells[found->second];
                    const double difference=std::abs(temperature(source)-temperature(cold));maximum_difference=std::max(maximum_difference,difference);
                    estimate+=conductance(source,cold)*difference;neighbors.push_back(found->second);}
                else if(const auto active=locations.find(adjacent);active!=locations.end()&&regions[active->second.first].id!=r.id){
                    const auto &other=regions[active->second.first].cells[active->second.second];other_region=true;
                    other_region_estimate+=conductance(cold,other)*std::abs(temperature(cold)-temperature(other));}}
            if(other_region){++f.other_region_face_observations;f.last_other_region_heat_rate_estimate_w+=other_region_estimate;continue;}
            if(neighbors.empty()||maximum_difference<f.policy.activation_temperature_difference_k){
                ++f.below_threshold_face_observations;f.last_below_threshold_heat_rate_estimate_w+=estimate;continue;}
            if(r.cells.size()>=MaximumRegionCells||cell_count+job.cells_added>=MaximumActiveCells){
                ++f.capacity_blocked_candidate_observations;candidate.inspected_face_heat_rate_estimates_w.clear();
                for(unsigned neighbor:neighbors){const auto &source=r.cells[neighbor];candidate.inspected_face_heat_rate_estimates_w[source.address]=conductance(source,cold)*std::abs(temperature(source)-temperature(cold));}
                f.pending.push_back(std::move(candidate));continue;}
            const unsigned new_index=unsigned(r.cells.size());r.cells.push_back(cold);local.emplace(cold.address,new_index);++job.operations;
            for(unsigned neighbor:neighbors){r.edges.push_back({std::min(neighbor,new_index),std::max(neighbor,new_index),conductance(r.cells[neighbor],r.cells[new_index])});++job.operations;}
            r.initial_mass+=cold.state.mass_kg;r.initial_energy+=energy(cold);
            f.cold_to_active_mass_kg+=cold.state.mass_kg;f.cold_to_active_thermal_enthalpy_j+=thermalEnergy(cold);
            f.cold_to_active_chemical_energy_j+=chemicalEnergy(cold);f.cold_to_active_energy_j+=energy(cold);
            ++job.cells_added;++f.cells_added;
        }
        f.last_cells_added=job.cells_added;return job;
    }
};

SparseThermalWorld::SparseThermalWorld(double size):impl_(std::make_unique<Impl>()){
    require(std::isfinite(size)&&size>=.001&&size<=10,"invalid voxel size");impl_->size=size;}
SparseThermalWorld::~SparseThermalWorld()=default;
void SparseThermalWorld::addMaterial(WorldThermalMaterial material){
    auto &w=*impl_;require(w.materials.size()<256&&material.id>0&&!w.materials.contains(material.id),"material ID or registry budget invalid");
    require(std::isfinite(material.solid_density_kg_m3)&&material.solid_density_kg_m3>0&&material.solid_density_kg_m3<=30000,"invalid solid density");
    require(std::isfinite(material.fuel_mass_fraction)&&material.fuel_mass_fraction>=0&&material.fuel_mass_fraction<=1,"invalid fuel fraction");
    require(std::isfinite(material.oxygen_kg_per_kg_solid)&&material.oxygen_kg_per_kg_solid>=0&&material.oxygen_kg_per_kg_solid<=10,"invalid finite oxygen reservoir");
    thermal::validateMaterial(material.thermal);
    if(material.phase_change){thermal::validateEnthalpyMaterial(*material.phase_change);
        require(!material.thermal.reaction.enabled&&material.fuel_mass_fraction==0&&material.oxygen_kg_per_kg_solid==0,"combined reaction/phase law is not implemented; phase matter requires no reactive reservoirs");
        require(material.thermal.specific_heat_capacity_j_kg_k==material.phase_change->solid_heat_capacity_j_kg_k,"phase solid heat capacity must match thermal declaration");}
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
    auto &w=*impl_;require(id>0&&w.regions.size()<256&&std::none_of(w.regions.begin(),w.regions.end(),[&](const auto&r){return r.id==id;})&&
        std::find(w.retired_region_ids.begin(),w.retired_region_ids.end(),id)==w.retired_region_ids.end(),"invalid, active, or retired region ID, or region budget exceeded");
    require(!cells.empty()&&cells.size()<=MaximumRegionCells&&w.cell_count+cells.size()<=MaximumActiveCells,"active thermal cell budget exceeded");
    require(std::isfinite(dt)&&dt>=.001&&dt<=1,"invalid thermal step");Impl::Region r{id,dt,w.requested_time,0,0};
    std::map<std::tuple<int,int,int>,unsigned> indices;
    for(auto a:cells){validateAddress(a);require(w.chunks.contains(a.chunk)&&!w.locations.contains(a),"missing chunk or overlapping active region");
        require(indices.emplace(global(a),unsigned(r.cells.size())).second,"duplicate region voxel");auto cell=w.makeCell(a);r.initial_mass+=cell.state.mass_kg;r.cells.push_back(std::move(cell));}
    for(const auto &[key,a]:indices){const auto [x,y,z]=key;for(const auto other:std::vector<std::tuple<int,int,int>>{{x+1,y,z},{x,y+1,z},{x,y,z+1}}){
        const auto it=indices.find(other);if(it!=indices.end())r.edges.push_back({a,it->second,w.conductance(r.cells[a],r.cells[it->second])});}}
    r.initial_energy=w.energy(r);const unsigned region=unsigned(w.regions.size());w.regions.push_back(std::move(r));
    for(unsigned i=0;i<cells.size();++i)w.locations.emplace(cells[i],std::pair{region,i});w.cell_count+=cells.size();
}
void SparseThermalWorld::enableThermalFrontier(unsigned id,ThermalFrontierPolicy policy,double expected){
    auto &w=*impl_;const auto found=std::find_if(w.regions.begin(),w.regions.end(),[&](const auto&r){return r.id==id;});
    require(found!=w.regions.end(),"thermal frontier requires an active region ID");
    require(std::isfinite(expected)&&std::abs(expected-found->time)<1e-12&&found->time+found->dt>w.requested_time+1e-12,"thermal frontier policy has stale time or region backlog");
    require(!found->frontier.enabled,"thermal frontier policy is already declared for this region");
    require(std::isfinite(policy.activation_temperature_difference_k)&&policy.activation_temperature_difference_k>=0&&policy.activation_temperature_difference_k<=10000,"invalid frontier temperature-difference threshold");
    require(policy.maximum_face_probes_per_step>0&&policy.maximum_face_probes_per_step<=MaximumFrontierProbes,"invalid frontier face-probe bound");
    require(policy.maximum_cells_added_per_step>0&&policy.maximum_cells_added_per_step<=MaximumRegionCells,"invalid frontier cell-addition bound");
    require(policy.maximum_pending_cells>0&&policy.maximum_pending_cells<=MaximumRegionCells,"invalid frontier pending-candidate bound");
    found->frontier.enabled=true;found->frontier.policy=policy;
}

ThermalRegionJoinReceipt SparseThermalWorld::joinInsulatedRegions(unsigned firstId,unsigned secondId,double expected){
    auto &w=*impl_;require(firstId!=secondId,"thermal region join requires distinct IDs");
    const auto firstIt=std::find_if(w.regions.begin(),w.regions.end(),[&](const auto&r){return r.id==firstId;});
    const auto secondIt=std::find_if(w.regions.begin(),w.regions.end(),[&](const auto&r){return r.id==secondId;});
    require(firstIt!=w.regions.end()&&secondIt!=w.regions.end(),"thermal region join requires two active region IDs");
    const auto firstIndex=std::size_t(firstIt-w.regions.begin()),secondIndex=std::size_t(secondIt-w.regions.begin());const auto &first=*firstIt,&second=*secondIt;
    require(!first.frontier.enabled&&!second.frontier.enabled,"frontier-enabled regions cannot be explicitly joined");
    require(std::isfinite(expected)&&std::abs(expected-first.time)<1e-12&&std::abs(expected-second.time)<1e-12,"thermal region join has stale or mismatched accepted time");
    require(std::abs(first.time-second.time)<1e-12&&std::abs(first.dt-second.dt)<1e-12,"thermal region join requires matching clocks and fixed steps");
    require(first.time+first.dt>w.requested_time+1e-12&&second.time+second.dt>w.requested_time+1e-12,"thermal region join requires both regions to be fully caught up");
    require(first.cells.size()+second.cells.size()<=MaximumRegionCells,"joined thermal region exceeds the 512-cell region budget");
    Impl::Region merged=first;const unsigned firstCount=unsigned(merged.cells.size());merged.cells.insert(merged.cells.end(),second.cells.begin(),second.cells.end());
    merged.initial_energy+=second.initial_energy;merged.initial_mass+=second.initial_mass;merged.external_work+=second.external_work;merged.reaction_heat+=second.reaction_heat;
    merged.jobs+=second.jobs;merged.maximum_step_energy_residual=std::max(merged.maximum_step_energy_residual,second.maximum_step_energy_residual);
    std::map<std::tuple<int,int,int>,unsigned> indices;for(unsigned i=0;i<merged.cells.size();++i)require(indices.emplace(global(merged.cells[i].address),i).second,"joined thermal regions contain duplicate cells");
    merged.edges.clear();unsigned joinedFaces=0;
    for(const auto &[key,a]:indices){const auto [x,y,z]=key;for(const auto other:std::vector<std::tuple<int,int,int>>{{x+1,y,z},{x,y+1,z},{x,y,z+1}}){
        const auto it=indices.find(other);if(it==indices.end())continue;const unsigned b=it->second;merged.edges.push_back({a,b,w.conductance(merged.cells[a],merged.cells[b])});joinedFaces+=(a<firstCount)!=(b<firstCount);}}
    require(joinedFaces>0,"thermal region join requires at least one shared voxel face");
    ThermalRegionJoinReceipt receipt{firstId,secondId,unsigned(merged.cells.size()),unsigned(merged.edges.size()),joinedFaces,first.time};
    auto candidateRegions=w.regions;candidateRegions[firstIndex]=std::move(merged);candidateRegions.erase(candidateRegions.begin()+std::ptrdiff_t(secondIndex));
    std::map<VoxelAddress,std::pair<unsigned,unsigned>> candidateLocations;
    for(unsigned ri=0;ri<candidateRegions.size();++ri)for(unsigned ci=0;ci<candidateRegions[ri].cells.size();++ci)
        require(candidateLocations.emplace(candidateRegions[ri].cells[ci].address,std::pair{ri,ci}).second,"thermal region location index is inconsistent");
    auto candidateRetired=w.retired_region_ids;candidateRetired.push_back(secondId);auto candidateJoins=w.joins;candidateJoins.push_back(receipt);
    const unsigned oldNextId=w.regions[w.next_region].id,desiredNextId=oldNextId==secondId?firstId:oldNextId;unsigned candidateNext=0;bool foundNext=false;
    for(unsigned i=0;i<candidateRegions.size();++i)if(candidateRegions[i].id==desiredNextId){candidateNext=i;foundNext=true;break;}
    require(foundNext,"thermal region scheduler cursor is inconsistent");w.regions.swap(candidateRegions);w.locations.swap(candidateLocations);
    w.retired_region_ids.swap(candidateRetired);w.joins.swap(candidateJoins);w.next_region=candidateNext;return receipt;
}
double SparseThermalWorld::addHeat(VoxelAddress a,double requested,double limit,double expected){
    auto &w=*impl_;validateAddress(a);require(w.locations.contains(a),"heat requires an explicitly activated thermal region");
    const auto [ri,ci]=w.locations.at(a);auto &r=w.regions[ri];
    require(std::isfinite(expected)&&std::abs(expected-r.time)<1e-12&&r.time+r.dt>w.requested_time+1e-12,"heat command has stale time or region backlog");
    auto heaterState=r.cells[ci].state;heaterState.sensible_energy_j=w.thermalEnergy(r.cells[ci]);const auto update=thermal::applyBoundedHeater(heaterState,requested,limit);
    w.thermalEnergy(r.cells[ci],update.state.sensible_energy_j);r.external_work+=update.applied_work_j;return update.applied_work_j;
}
WorldStepReceipt SparseThermalWorld::advance(double elapsed,WorldStepBudget budget){
    auto &w=*impl_;require(std::isfinite(elapsed)&&elapsed>=0&&elapsed<=.25,"invalid world elapsed request");
    require(budget.maximum_jobs<=4096&&budget.maximum_cell_operations<=10000000&&std::isfinite(budget.maximum_wall_ms)&&budget.maximum_wall_ms>0&&budget.maximum_wall_ms<=1000,"invalid world work budget");
    const auto start=std::chrono::steady_clock::now();auto ms=[&]{return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();};
    w.requested_time+=elapsed;WorldStepReceipt receipt;receipt.requested_time_s=w.requested_time;unsigned examined=0;
    std::array<bool,256> frontierBudgetBlocked{};
    while(!w.regions.empty()&&examined<w.regions.size()){
        const unsigned ri=w.next_region;auto &r=w.regions[ri];w.next_region=(w.next_region+1)%unsigned(w.regions.size());++examined;
        if(r.time+r.dt>w.requested_time+1e-12)continue;const unsigned bound=w.frontierCostBound(r);
        if(receipt.completed_jobs>=budget.maximum_jobs||receipt.cell_operations+bound>budget.maximum_cell_operations){
            receipt.count_budget_exhausted=true;
            if(r.frontier.enabled&&!frontierBudgetBlocked[ri]){frontierBudgetBlocked[ri]=true;++receipt.frontier_regions_budget_blocked;}
            continue;}
        if(ms()>=budget.maximum_wall_ms){receipt.wall_budget_exhausted=true;break;}
        try{
            if(!r.frontier.enabled){
                const unsigned actual=r.cost();w.step(r);++receipt.completed_jobs;receipt.cell_operations+=actual;examined=0;continue;
            }
            const unsigned staged_copy=unsigned(r.cells.size()+r.edges.size()+r.frontier.pending.size());
            Impl::Region candidate=r;const auto frontier=w.growFrontier(candidate);
            std::map<VoxelAddress,std::pair<unsigned,unsigned>> addedLocations;
            for(unsigned i=unsigned(r.cells.size());i<candidate.cells.size();++i){
                require(!w.locations.contains(candidate.cells[i].address),"thermal frontier attempted duplicate activation");
                require(addedLocations.emplace(candidate.cells[i].address,std::pair{ri,i}).second,"thermal frontier attempted duplicate staged activation");
            }
            w.step(candidate);const unsigned actual=staged_copy+frontier.operations+candidate.cost()+frontier.cells_added;
            require(actual<=bound,"thermal frontier operation bound was not conservative");
            const unsigned added=frontier.cells_added;w.regions[ri]=std::move(candidate);w.locations.merge(addedLocations);w.cell_count+=added;
            ++receipt.completed_jobs;receipt.cell_operations+=actual;receipt.frontier_face_probes+=frontier.face_probes;receipt.frontier_cells_added+=added;examined=0;
        }catch(const std::exception &e){receipt.error=e.what();break;}
    }
    for(const auto &r:w.regions){const double lag=std::max(0.,w.requested_time-r.time);receipt.maximum_lag_s=std::max(receipt.maximum_lag_s,lag);
        receipt.regions_late+=r.time+r.dt<=w.requested_time+1e-12;receipt.frontier_candidates_pending+=unsigned(r.frontier.pending.size());
        for(const auto &candidate:r.frontier.pending)receipt.oldest_frontier_candidate_age_s=std::max(receipt.oldest_frontier_candidate_age_s,std::max(0.,w.requested_time-candidate.first_seen_time_s));}
    receipt.wall_ms=ms();w.total_wall+=receipt.wall_ms;w.maximum_wall=std::max(w.maximum_wall,receipt.wall_ms);++w.calls;w.total_jobs+=receipt.completed_jobs;
    w.peak_lag=std::max(w.peak_lag,receipt.maximum_lag_s);w.peak_late_regions=std::max(w.peak_late_regions,receipt.regions_late);
    w.count_limited_calls+=receipt.count_budget_exhausted;w.wall_limited_calls+=receipt.wall_budget_exhausted;
    if(w.timings.size()<4096)w.timings.push_back(receipt.wall_ms);else w.timings[(w.calls-1)%4096]=receipt.wall_ms;w.last=receipt;return receipt;
}
std::vector<ThermalCellView> SparseThermalWorld::activeCells()const{
    const auto &w=*impl_;std::vector<ThermalCellView> views;views.reserve(w.cell_count);
    for(const auto &r:w.regions)for(const auto &c:r.cells)views.push_back({c.address,c.material,r.id,w.temperature(c),c.state.remaining_fuel_kg,c.state.available_oxygen_kg,r.time,w.liquidFraction(c),w.materials.at(c.material).phase_change.has_value()});
    return views;
}
std::uint64_t SparseThermalWorld::representedVoxelCount()const{return std::uint64_t(impl_->chunks.size())*4096;}
std::size_t SparseThermalWorld::activeCellCount()const{return impl_->cell_count;}
std::string SparseThermalWorld::reportJson()const{
    const auto &w=*impl_;json regions=json::array(),joins=json::array();double activeMass=0,energyResidual=0,work=0,heat=0;std::size_t edgeCount=0,pendingCount=0;
    for(const auto &r:w.regions){double mass=0,fuel=0,oxygen=0,products=0,minT=1e30,maxT=0,liquidMass=0,enthalpy=0,chemical=0;
        for(const auto &c:r.cells){mass+=c.state.mass_kg;fuel+=c.state.remaining_fuel_kg;oxygen+=c.state.available_oxygen_kg;products+=c.state.reaction_products_kg;
            minT=std::min(minT,w.temperature(c));maxT=std::max(maxT,w.temperature(c));liquidMass+=c.state.mass_kg*w.liquidFraction(c);enthalpy+=w.thermalEnergy(c);chemical+=w.chemicalEnergy(c);}
        const double residual=w.energy(r)-r.initial_energy-r.external_work;energyResidual+=residual;activeMass+=mass;work+=r.external_work;heat+=r.reaction_heat;edgeCount+=r.edges.size();pendingCount+=r.frontier.pending.size();
        double pendingEstimate=0,oldestAge=0;for(const auto &candidate:r.frontier.pending){for(const auto &[source,estimate]:candidate.inspected_face_heat_rate_estimates_w){(void)source;pendingEstimate+=estimate;}
            oldestAge=std::max(oldestAge,std::max(0.,w.requested_time-candidate.first_seen_time_s));}
        regions.push_back({{"id",r.id},{"cells",r.cells.size()},{"edges",r.edges.size()},{"accepted_time_s",r.time},{"lag_s",std::max(0.,w.requested_time-r.time)},{"jobs",r.jobs},
            {"mass_kg",mass},{"mass_residual_kg",mass-r.initial_mass},{"fuel_kg",fuel},{"oxygen_kg",oxygen},{"products_kg",products},{"temperature_min_k",minT},{"temperature_max_k",maxT},
            {"external_work_j",r.external_work},{"reaction_heat_j",r.reaction_heat},{"combined_energy_residual_j",residual},{"maximum_step_energy_residual_j",r.maximum_step_energy_residual},
            {"boundary",r.frontier.enabled?"bounded cold-neighbor frontier; deferred faces are insulated":"explicitly insulated"}});
        auto &entry=regions.back();entry["liquid_mass_kg"]=liquidMass;entry["thermal_enthalpy_j"]=enthalpy;entry["chemical_energy_j"]=chemical;
        const unsigned material=r.cells.front().material;entry["material"]=std::all_of(r.cells.begin(),r.cells.end(),[&](const auto&c){return c.material==material;})?w.materials.at(material).thermal.display_name:"Mixed materials";
        entry["frontier"]={{"enabled",r.frontier.enabled},{"policy",{{"activation_temperature_difference_k",r.frontier.policy.activation_temperature_difference_k},
            {"maximum_face_probes_per_step",r.frontier.policy.maximum_face_probes_per_step},{"maximum_cells_added_per_step",r.frontier.policy.maximum_cells_added_per_step},
            {"maximum_pending_cells",r.frontier.policy.maximum_pending_cells},{"predicate","absolute face temperature difference"}}},
            {"scans",r.frontier.scans},{"face_probes",r.frontier.face_probes},{"cells_added",r.frontier.cells_added},{"pending_candidates",r.frontier.pending.size()},
            {"oldest_candidate_age_s",oldestAge},{"last_face_probes",r.frontier.last_face_probes},{"last_unprobed_active_faces",r.frontier.last_unprobed_faces},{"last_cells_added",r.frontier.last_cells_added},
            {"blocked",{{"below_threshold_face_observations",r.frontier.below_threshold_face_observations},{"missing_chunk_face_observations",r.frontier.missing_chunk_face_observations},
                {"other_active_region_face_observations",r.frontier.other_region_face_observations},{"region_or_world_capacity_candidate_observations",r.frontier.capacity_blocked_candidate_observations},
                {"pending_capacity_face_observations",r.frontier.pending_capacity_face_observations}}},
            {"cold_to_active",{{"mass_kg",r.frontier.cold_to_active_mass_kg},{"thermal_enthalpy_j",r.frontier.cold_to_active_thermal_enthalpy_j},
                {"chemical_energy_j",r.frontier.cold_to_active_chemical_energy_j},{"combined_energy_j",r.frontier.cold_to_active_energy_j}}},
            {"omitted_flux_approximation",{{"deferred_faces_are_insulated",true},{"global_heat_error_bound_available",false},{"estimate_is_instantaneous",true},
                {"estimate_scope","last bounded scan and retained candidates only"},{"last_below_threshold_heat_rate_estimate_w",r.frontier.last_below_threshold_heat_rate_estimate_w},
                {"last_other_region_heat_rate_estimate_w",r.frontier.last_other_region_heat_rate_estimate_w},{"pending_candidate_heat_rate_estimate_w",pendingEstimate}}}};
    }
    auto times=w.timings;std::sort(times.begin(),times.end());for(const auto &joined:w.joins)joins.push_back({{"preserved_region_id",joined.preserved_region_id},{"retired_region_id",joined.retired_region_id},{"accepted_time_s",joined.accepted_time_s},{"cells",joined.cells},{"edges",joined.edges},{"joined_face_edges",joined.joined_face_edges}});
    auto percentile=[&](double p){return times.empty()?0.:times[std::min(times.size()-1,std::size_t(std::ceil(times.size()*p)-1))];};
    std::size_t pendingFaceEntries=0;for(const auto &r:w.regions)for(const auto &candidate:r.frontier.pending)pendingFaceEntries+=candidate.inspected_face_heat_rate_estimates_w.size();
    const auto bytes=w.chunks.size()*(sizeof(ChunkAddress)+sizeof(Impl::Chunk))+w.cell_count*sizeof(Impl::Cell)+edgeCount*sizeof(Impl::Edge)+pendingCount*sizeof(Impl::FrontierCandidate)+pendingFaceEntries*sizeof(std::pair<const VoxelAddress,double>);
    return json{{"backend","sparse-thermal-world-v1"},{"requested_time_s",w.requested_time},{"represented_voxels",representedVoxelCount()},{"uniform_chunks",w.chunks.size()},
        {"active_regions",w.regions.size()},{"active_cells",w.cell_count},{"cold_voxels",representedVoxelCount()-w.cell_count},{"physics_body_count",0},{"state_payload_bytes",bytes},{"payload_excludes_allocator_overhead",true},
        {"active_mass_kg",activeMass},{"external_work_j",work},{"reaction_heat_j",heat},{"combined_active_energy_residual_j",energyResidual},{"regions",regions},{"region_joins",joins},{"retired_region_ids",w.retired_region_ids},
        {"performance",{{"advance_calls",w.calls},{"completed_jobs",w.total_jobs},{"total_wall_ms",w.total_wall},{"advance_p50_ms",percentile(.5)},{"advance_p95_ms",percentile(.95)},{"advance_p99_ms",percentile(.99)},
            {"advance_max_ms",w.maximum_wall},{"timing_sample_window",times.size()},{"cold_chunks_scanned_per_advance",0},{"frontier_uses_bounded_direct_neighbor_lookups",true},{"includes_rendering",false},
            {"peak_lag_s",w.peak_lag},{"peak_late_regions",w.peak_late_regions},{"count_limited_calls",w.count_limited_calls},{"wall_limited_calls",w.wall_limited_calls}}},
        {"last_budget",{{"jobs",w.last.completed_jobs},{"cell_operations",w.last.cell_operations},{"regions_late",w.last.regions_late},{"maximum_lag_s",w.last.maximum_lag_s},
            {"count_exhausted",w.last.count_budget_exhausted},{"wall_exhausted",w.last.wall_budget_exhausted},{"frontier_face_probes",w.last.frontier_face_probes},{"frontier_cells_added",w.last.frontier_cells_added},
            {"frontier_candidates_pending",w.last.frontier_candidates_pending},{"frontier_regions_budget_blocked",w.last.frontier_regions_budget_blocked},{"oldest_frontier_candidate_age_s",w.last.oldest_frontier_candidate_age_s},{"error",w.last.error}}},
        {"limitations",{"Frontier activation is opt-in and same-clock; deferred cold, missing, and other-region faces are insulated approximations, and instantaneous omitted-flux estimates are not global heat-error bounds",
            "No frontier demotion or asynchronous/cross-region exchange; neighboring active regions require the separate explicit same-clock join and are never joined implicitly",
            "No rigid/deformable physics, airflow, smoke, radiation, volume change, liquid flow or mechanical weakening in this backend",
            "Fuel and finite oxygen react into retained products with constant mixture heat capacity; not validated real combustion",
            "Constant-capacity pair conduction is exact; phase edges use first-order backward Euler, graph splitting requires timestep convergence",
            "Cold storage size is not evidence of a fully simulated world; deadlines are soft and checked between bounded atomic region jobs",
            "Single isothermal melt/freeze law; phase + reaction coupling is rejected, phase conductivity is held constant"}}}.dump(2);
}
}
