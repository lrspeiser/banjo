#include "platform/VoxelImpactWorld.hpp"
#include "rigid/JoltWorld.hpp"
#include "rigid/RigidComponent.hpp"
#include "physics/BoxSweep.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/ConnectorPlasticity.hpp"
#include "physics/RigidStepWork.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <map>
#include <numeric>
#include <set>
#include <stdexcept>
namespace banjo {
namespace {
using Json=nlohmann::json;
Json v(Vec3 x){return {x.x,x.y,x.z};}
MaterialPreset preset(std::string s){for(auto p:kMaterialPresets)if(materialSceneName(p)==s)return p;throw std::invalid_argument("unknown material");}
double scalar(const Json &j,const char *key,double fallback,double lo,double hi){
    const auto value=j.value(key,Json(fallback));if(!value.is_number()||value.is_boolean())throw std::invalid_argument(key);
    const double x=value.get<double>();if(!std::isfinite(x)||x<lo||x>hi)throw std::invalid_argument(key);return x;
}
double quadratic(Vec3 k,Vec3 x){return .5*(k.x*x.x*x.x+k.y*x.y*x.y+k.z*x.z*x.z);}
MaterialDefinition contact(MaterialDefinition m){m.model=MaterialModel::RigidOnly;return m;}
RigidContactCapacity contactCapacity(const Json &d,VoxelExecution storage){
    if(storage==VoxelExecution::Reference)return {32768,16384};
    const double requested=scalar(d,"resolution",8,4,16);
    if(requested!=4&&requested!=8&&requested!=12&&requested!=16)
        throw std::invalid_argument("resolution must be 4, 8, 12 or 16");
    // Allocation only: leave laws, ordering, iteration and admission unchanged.
    // This is headroom for the bounded scene, not a claim about arbitrary worlds.
    // Jolt capacity errors still refuse and restore the trial; never omit contacts.
    const unsigned cells=unsigned(requested*requested)+32+11;
    unsigned pairs=2048,constraints=1024;
    while(pairs<cells*16)pairs*=2;
    while(constraints<cells*8)constraints*=2;
    return {pairs,constraints};
}
}
struct VoxelImpactWorld::Impl {
    struct Cell {unsigned object;MatterBodyId id;Vec3 size,initial;double mass;std::string material;bool fixed;};
    struct Bond {unsigned a,b,joint;double area,iy,iz,width,height,strength,shear,gc;Vec3 k,r,damping,rotation_damping;bool brittle,live{true};double energy{};
        std::optional<ConnectorPlasticParameters> plastic;ConnectorPlasticState plastic_state;};
    struct Pair {unsigned a,b;int bond{-1};};
    JoltWorld world;
    std::unique_ptr<RigidComponent> coast;
    unsigned coast_index{};bool hybrid{};
    double transfer_energy{},coast_time{};Json transfers=Json::array();
    bool active(unsigned i) const {return world.contains(cells[i].id)||(coast&&coast->collapsed()&&i==coast_index);}
    MatterBodyId nativeId(unsigned i) const {return coast&&coast->collapsed()&&i==coast_index?coast->proxy():cells[i].id;}
    unsigned slot(MatterBodyId id) const {return coast&&coast->collapsed()&&id==coast->proxy()?coast_index:unsigned(id-100);}
    bool detailed(const Bond &b) const {return b.live&&!world.faceComponentParked(b.joint);}
    RigidSnapshot cellSnapshot(unsigned i) const {
        if(coast&&coast->collapsed()&&cells[i].object==2)return coast->snapshots(world).at(i-coast_index);
        return world.snapshot(cells[i].id);
    }
    void receipt(const ComponentTransferReceipt &r,const char *action){
        const auto &a=r.audit;const double delta=a.after.mechanicalEnergy()-a.before.mechanicalEnergy();
        if(a.measured)transfer_energy+=delta;
        transfers.push_back({{"time_s",time},{"action",action},{"admitted",r.admitted},{"reason",r.reason},{"measured",a.measured},
            {"mass_change_kg",a.after.mass_kg-a.before.mass_kg},{"energy_change_j",delta},{"nonrigid_energy_j",r.nonrigid_energy_j},
            {"linear_change_n_s",v(a.after.linear_momentum_kg_m_s-a.before.linear_momentum_kg_m_s)},
            {"angular_change_n_m_s",v(a.after.angular_momentum_kg_m2_s-a.before.angular_momentum_kg_m2_s)}});
    }
    void expandCoast(const char *reason){
        if(!coast||!coast->collapsed())return;
        const auto r=coast->expand(world,gravity);receipt(r,reason);totals=world.mechanicalTotals(gravity);
        if(!r.admitted)throw std::runtime_error("component restoration transfer exceeds budget: "+r.reason);
    }
    void guardCoast(double h){
        if(!coast||!coast->collapsed())return;
        if(!actuators.empty()){expandCoast("external loading");return;}
        const auto state=world.snapshot(coast->proxy());
        const auto [lo,hi]=world.shapeBoundsTurned(coast->proxy(),state.orientation_world);
        const auto sweep=boundBoxSweep(hi-lo,state.center_of_mass_world_m+(hi+lo)/2,{},
            (length(state.linear_velocity_m_s)+length(state.angular_velocity_rad_s)*std::max(length(lo),length(hi)))*h+length(gravity)*h*h);
        for(unsigned i=0;i<cells.size();++i)if(cells[i].object!=2){const auto b=world.snapshot(cells[i].id);
            const auto other=boundBoxSweep(cells[i].size,b.center_of_mass_world_m,b.orientation_world,
                (length(b.linear_velocity_m_s)+length(b.angular_velocity_rad_s)*length(cells[i].size)/2)*h+length(gravity)*h*h);
            // A broad enclosing bound only schedules activation. It never
            // supplies contact geometry or relaxes detailed acceptance gates.
            if(boxSweepRatio(sweep,other,.02)>0){expandCoast("prospective contact");return;}
        }
    }
    Json declaration,events=Json::array();std::vector<Cell> cells;std::vector<Bond> bonds;std::vector<Pair> internal;
    std::map<MatterBodyId,unsigned> motion_drivers;
    unsigned motion_splits{},max_motion_depth{};
    bool local_flight{};unsigned flight_candidates{},flight_accepted{},flight_rollbacks{};
    std::map<MatterBodyId,unsigned> flown_cells;std::set<MatterBodyId> returned_contact_cells;
    double peak_flight_surface_travel{};unsigned last_free_cells{};
    // Only a singleton with no live interfaces can leave the material motion
    // budget. Its original native body, mass, pose, spin and history stay put.
    // Use a sphere enclosing every orientation for dynamic boxes, and exact
    // oriented extents for anchored supports. This is broad-phase scheduling,
    // never a contact response. The candidate endpoint envelope is checked
    // again inside the reversible trial before any result is accepted.
    BoxCenterPath flightBounds(unsigned i,const RigidSnapshot &start,double h,
                             const RigidSnapshot *end=nullptr)const{
        const auto &c=cells[i];
        const double travel=end||c.fixed?0:length(start.linear_velocity_m_s)*h+length(gravity)*h*h;
        return boundBoxCenterPath(c.size,start.center_of_mass_world_m,
            end?end->center_of_mass_world_m:start.center_of_mass_world_m,start.orientation_world,c.fixed,travel);
    }
    static bool flightOverlap(const BoxCenterPath &a,const BoxCenterPath &b){
        return boxCenterPathsOverlap(a,b,.02);
    }
    std::vector<bool> isolatedFlight(const std::vector<RigidSnapshot> &states,double h)const{
        std::vector<bool> eligible(cells.size(),false);if(!local_flight||!actuators.empty()||(coast&&coast->collapsed()))return eligible;
        std::vector<unsigned> degree(cells.size());for(const auto &b:bonds)if(b.live){++degree[b.a];++degree[b.b];}
        std::vector<BoxCenterPath> bounds;bounds.reserve(cells.size());
        for(unsigned i=0;i<cells.size();++i)bounds.push_back(flightBounds(i,states[i],h));
        for(unsigned i=0;i<cells.size();++i)if(!cells[i].fixed&&degree[i]==0){
            eligible[i]=true;for(unsigned j=0;j<cells.size();++j)if(i!=j&&flightOverlap(bounds[i],bounds[j])){eligible[i]=false;break;}}
        return eligible;
    }
    bool candidateFlightSafe(const std::vector<bool> &eligible,
                             const std::vector<RigidSnapshot> &before,
                             const std::vector<RigidMechanicalState> &after)const{
        std::vector<BoxCenterPath> bounds;bounds.reserve(cells.size());
        for(unsigned i=0;i<cells.size();++i)bounds.push_back(flightBounds(i,before[i],0,&after[i].motion));
        for(unsigned i=0;i<cells.size();++i)if(eligible[i])for(unsigned j=0;j<cells.size();++j)
            if(i!=j&&flightOverlap(bounds[i],bounds[j]))return false;
        for(const auto &c:world.contactImpulseObservations())if(eligible.at(slot(c.a))||eligible.at(slot(c.b)))return false;
        return true;
    }
    double linear_velocity_quadratic{},peak_spin{};unsigned spin_limit_samples{};
    double material_damping{},implicit_elastic_loss{},spring_endpoint_work{},spring_geometry_change{},spring_residual_work{},max_spring_residual_n{};
    double contact_normal_work{},contact_friction_work{},contact_twist_work{};
    Vec3 support_reaction_impulse{},support_reaction_angular_impulse{},gravity_impulse{},momentum_residual{};
    unsigned contact_manifold_samples{},contact_point_samples{};
    double sweep_wall_ms{},trial_wall_ms{},observation_wall_ms{},native_step_wall_ms{},totals_wall_ms{},candidate_faces_wall_ms{};
    double feature{},dt{},time{},initial_energy{},fracture{},discarded_elastic{},max_wall_ms{},peak_stress_ratio{};
    unsigned ticks{},broken{},substeps{},rejected{};Vec3 gravity;MechanicalTotals initial,totals;
    bool log_faces{},resolved_deformation{},centered_faces{},midpoint_contact{};
    bool sheet_plasticity{};double plastic_work{},plastic_return_excess{};
    std::map<unsigned,Vec3> actuators;unsigned actuator_commands{};bool actuation_used{};double actuator_work{},actuator_started{};
    Vec3 actuator_impulse{},actuator_angular_impulse{},actuator_force_phase_residual{};
    RigidStepWork work_total{};double elastic_change_j{},ledger_change_j{};Vec3 full_angular_residual{};
    Json refused_work=nullptr,boundary_total={{"normal_midpoint_work_j",0.},{"friction_midpoint_work_j",0.},{"twist_midpoint_work_j",0.},{"positive_normal_work_j",0.},{"max_velocity_violation_m_s",0.},{"max_complementarity_error_j",0.},
        {"max_friction_stationarity_gap_j",0.},{"max_twist_stationarity_gap_j",0.},{"max_friction_cap_excess_n_s",0.},{"max_twist_cap_excess_n_m_s",0.}};
    static Json workJson(const RigidStepWork &w){return {
        {"gravity_work_j",w.gravity_work_j},{"gyro_kick_j",w.gyro_kick_j},{"other_force_work_j",w.other_force_work_j},
        {"spring_work_j",w.spring_work_j},{"contact_work_j",w.contact_work_j},{"solver_residual_work_j",w.solver_residual_work_j},
        {"rotation_drift_j",w.rotation_drift_j},{"potential_change_j",w.potential_change_j},{"kinetic_change_j",w.kinetic_change_j},
        {"energy_residual_j",w.energy_residual_j},{"solver_linear_residual_n_s",v(w.solver_linear_residual_n_s)},
        {"solver_angular_residual_n_m_s",v(w.solver_angular_residual_n_m_s)},{"angular_drift_n_m_s",v(w.angular_drift_n_m_s)},
        {"velocity_limit_work_j",w.velocity_limit_work_j},{"post_integration_work_j",w.post_integration_work_j},
        {"velocity_limit_impulse_n_s",v(w.velocity_limit_impulse_n_s)},{"velocity_limit_couple_n_m_s",v(w.velocity_limit_couple_n_m_s)}};}
    RigidStepWork measureWork(const std::vector<RigidSnapshot> &before,
        const std::vector<RigidMechanicalState> &after,const std::vector<JoltWorld::FaceSpringObservation> &faces_before,
        const std::vector<JoltWorld::FaceSpringObservation> &faces_after)const{
        std::vector<RigidStepWorkInput> indexed(cells.size()),dynamic;
        for(const auto &p:world.forcePhaseObservations()){
            const auto i=slot(p.body);if(i>=cells.size()||cells[i].fixed)throw std::runtime_error("unknown native force phase body");
            indexed[i]={p.before,after[i],p.spin_after_gyro_rad_s,p.velocity_after_forces_m_s,p.spin_after_forces_rad_s,p.gravity_impulse_n_s};
            indexed[i].velocity_after_solver_m_s=p.velocity_after_solver_m_s;indexed[i].spin_after_solver_rad_s=p.spin_after_solver_rad_s;
            indexed[i].velocity_after_limit_m_s=p.velocity_after_limit_m_s;indexed[i].spin_after_limit_rad_s=p.spin_after_limit_rad_s;
            indexed[i].integration_observed=p.integration_scheduled;
        }
        const auto push=[&](unsigned a,unsigned b,Vec3 point,Vec3 impulse,bool spring){
            auto &ia=indexed[a],&ib=indexed[b];
            if(spring){ia.spring_impulse_n_s-=impulse;ib.spring_impulse_n_s+=impulse;
                ia.spring_couple_n_m_s-=cross(point-before[a].center_of_mass_world_m,impulse);ib.spring_couple_n_m_s+=cross(point-before[b].center_of_mass_world_m,impulse);}
            else{ia.contact_impulse_n_s-=impulse;ib.contact_impulse_n_s+=impulse;
                ia.contact_couple_n_m_s-=cross(point-before[a].center_of_mass_world_m,impulse);ib.contact_couple_n_m_s+=cross(point-before[b].center_of_mass_world_m,impulse);}
        };
        for(unsigned i=0;i<bonds.size();++i)if(detailed(bonds[i])){const auto &b=bonds[i];const auto &g=faces_before[i],&s=faces_after[i];
            if(!s.solver_scheduled.has_value())throw std::runtime_error("native spring schedule observation missing");
            if(!*s.solver_scheduled)continue;
            const Vec3 linear=g.translation_axes_world[0]*s.linear_impulse_cs_n_s.x+g.translation_axes_world[1]*s.linear_impulse_cs_n_s.y+g.translation_axes_world[2]*s.linear_impulse_cs_n_s.z;
            const Vec3 angular=g.rotation_axes_world[0]*s.angular_impulse_cs_n_m_s.x+g.rotation_axes_world[1]*s.angular_impulse_cs_n_m_s.y+g.rotation_axes_world[2]*s.angular_impulse_cs_n_m_s.z;
            push(b.a,b.b,g.anchor_b_world_m,linear,true);indexed[b.a].spring_couple_n_m_s-=angular;indexed[b.b].spring_couple_n_m_s+=angular;
        }
        for(const auto &c:world.contactImpulseObservations()){
            const unsigned a=slot(c.a),b=slot(c.b);if(a>=cells.size()||b>=cells.size())throw std::runtime_error("unknown work contact body");
            for(const auto &p:c.points)push(a,b,p.point_world_m,c.normal_a_to_b*p.normal_impulse_n_s,false);
            push(a,b,c.friction_point_world_m,c.friction_impulse_on_b_n_s,false);
            indexed[a].contact_couple_n_m_s-=c.twist_impulse_on_b_n_m_s;indexed[b].contact_couple_n_m_s+=c.twist_impulse_on_b_n_m_s;
        }
        for(unsigned i=0;i<cells.size();++i)if(!cells[i].fixed&&active(i)){if(indexed[i].before.mass_kg<=0)throw std::runtime_error("native force phase observation missing");dynamic.push_back(indexed[i]);}
        return auditRigidStepWork(dynamic,gravity);
    }
    Json measureBoundary(const std::vector<RigidSnapshot> &before,double h,Json &worst_twist)const{
        double normal=0,positive=0,friction=0,twist=0,velocity_violation=0,complementarity=0;
        double friction_gap=0,twist_gap=0,friction_excess=0,twist_excess=0;
        worst_twist=nullptr;
        std::vector<RigidSnapshot> solver=before;
        for(const auto &phase:world.forcePhaseObservations()){
            auto &s=solver.at(slot(phase.body));
            s.linear_velocity_m_s=phase.velocity_after_solver_m_s;s.angular_velocity_rad_s=phase.spin_after_solver_rad_s;
        }
        for(const auto &c:world.contactImpulseObservations()){
            const unsigned a=slot(c.a),b=slot(c.b);
            const auto speed=[&](Vec3 point,const std::vector<RigidSnapshot> &states){
                return states[b].linear_velocity_m_s+cross(states[b].angular_velocity_rad_s,point-before[b].center_of_mass_world_m)
                    -states[a].linear_velocity_m_s-cross(states[a].angular_velocity_rad_s,point-before[a].center_of_mass_world_m);
            };
            double cap=0,twist_cap=0;
            for(const auto &p:c.points){
                const double v0=dot(c.normal_a_to_b,speed(p.point_world_m,before)),v1=dot(c.normal_a_to_b,speed(p.point_world_m,solver));
                const double residual=v0+v1+2*std::max(0.,p.initial_gap_m)/h;
                const double work=p.normal_impulse_n_s*(v0+v1)/2;
                normal+=work;
                positive+=std::max(0.,work);
                velocity_violation=std::max(velocity_violation,std::max(0.,-residual));
                complementarity=std::max(complementarity,std::abs(p.normal_impulse_n_s*residual));
                cap+=p.normal_impulse_n_s;twist_cap+=p.normal_impulse_n_s*p.friction_radius_m;
            }
            cap*=c.combined_friction;twist_cap*=c.combined_friction;
            const Vec3 relative=(speed(c.friction_point_world_m,before)+speed(c.friction_point_world_m,solver))/2;
            const Vec3 slip=relative-dot(relative,c.normal_a_to_b)*c.normal_a_to_b;
            const double spin=dot(c.normal_a_to_b,(before[b].angular_velocity_rad_s-before[a].angular_velocity_rad_s+solver[b].angular_velocity_rad_s-solver[a].angular_velocity_rad_s)/2);
            const double impulse=dot(c.normal_a_to_b,c.twist_impulse_on_b_n_m_s);
            const auto row=auditContactFrictionStationarity(c.friction_impulse_on_b_n_s,slip,cap,impulse,spin,twist_cap);
            friction+=dot(c.friction_impulse_on_b_n_s,relative);
            twist+=dot(c.twist_impulse_on_b_n_m_s,(before[b].angular_velocity_rad_s-before[a].angular_velocity_rad_s+solver[b].angular_velocity_rad_s-solver[a].angular_velocity_rad_s)/2);
            friction_gap=std::max(friction_gap,row.friction_gap_j);
            if(row.twist_gap_j>twist_gap){twist_gap=row.twist_gap_j;
                worst_twist={{"a",c.a},{"b",c.b},{"point_m",v(c.friction_point_world_m)},{"normal",v(c.normal_a_to_b)},
                    {"coefficient",c.combined_friction},{"points",c.points.size()},{"twist_impulse_n_m_s",impulse},{"twist_cap_n_m_s",twist_cap},
                    {"midpoint_spin_rad_s",spin},{"twist_work_j",row.twist_work_j},{"twist_stationarity_gap_j",row.twist_gap_j},
                    {"before_spin_a_rad_s",v(before[a].angular_velocity_rad_s)},{"before_spin_b_rad_s",v(before[b].angular_velocity_rad_s)},
                    {"solver_spin_a_rad_s",v(solver[a].angular_velocity_rad_s)},{"solver_spin_b_rad_s",v(solver[b].angular_velocity_rad_s)}};
            }
            friction_excess=std::max(friction_excess,row.friction_cap_excess_n_s);twist_excess=std::max(twist_excess,row.twist_cap_excess_n_m_s);
        }
        return {{"normal_midpoint_work_j",normal},{"friction_midpoint_work_j",friction},{"twist_midpoint_work_j",twist},{"positive_normal_work_j",positive},{"max_velocity_violation_m_s",velocity_violation},{"max_complementarity_error_j",complementarity},
            {"max_friction_stationarity_gap_j",friction_gap},{"max_twist_stationarity_gap_j",twist_gap},{"max_friction_cap_excess_n_s",friction_excess},{"max_twist_cap_excess_n_m_s",twist_excess}};
    }
    std::vector<unsigned> components() const {
        std::vector<unsigned> p(cells.size());std::iota(p.begin(),p.end(),0);
        auto root=[&](unsigned x){while(p[x]!=x){p[x]=p[p[x]];x=p[x];}return x;};
        for(const auto &b:bonds)if(b.live)p[root(b.b)]=root(b.a);
        for(auto &x:p)x=root(x);return p;
    }
    void filtering(){const auto roots=components();for(const auto &p:internal){
        const bool joined=p.bond>=0?bonds[unsigned(p.bond)].live:roots[p.a]==roots[p.b];
        world.setPairContactOwner(cells[p.a].id,cells[p.b].id,joined?PairContactOwner::External:PairContactOwner::Jolt);
    }}
    unsigned cell(unsigned object,Vec3 size,Vec3 position,MaterialPreset p,bool fixed=false){
        const auto m=makeReferenceMaterial(p);const unsigned index=unsigned(cells.size());const MatterBodyId id=100+index;
        world.addBox({id,size,contact(m),{position,{}, {},{}},fixed});
        if(!fixed)world.setContinuousCollision(id,false);
        cells.push_back({object,id,size,position,size.x*size.y*size.z*m.density_kg_m3,std::string(materialSceneName(p)),fixed});return index;
    }
    void connect(unsigned a,unsigned b,Vec3 normal,Vec3 tangent,double length0,double width,double height,const MaterialDefinition &m){
        const double area=width*height,iy=width*height*height*height/12,iz=height*width*width*width/12;
        const double g=m.young_modulus_pa/(2*(1+m.poisson_ratio));
        const Vec3 k{m.young_modulus_pa*area/length0,g*area/length0,g*area/length0};
        // Polar-area torsion approximation; not a calibrated Saint-Venant law.
        const Vec3 r{g*(iy+iz)/length0,m.young_modulus_pa*iy/length0,m.young_modulus_pa*iz/length0};
        const double mass=cells[a].mass*cells[b].mass/(cells[a].mass+cells[b].mass);
        const auto inertia=RigidPrimitive{PrimitiveKind::Box,0,cells[a].size}.inertia(cells[a].mass);
        const double reduced_i=std::min({inertia.m[0][0],inertia.m[1][1],inertia.m[2][2]})/2;
        const auto damp=[&](Vec3 s,double reduced){return Vec3{2*m.damping_ratio*std::sqrt(s.x*reduced),2*m.damping_ratio*std::sqrt(s.y*reduced),2*m.damping_ratio*std::sqrt(s.z*reduced)};};
        const auto joint=world.addFaceSpring({cells[a].id,cells[b].id,(cells[a].initial+cells[b].initial)/2,normal,tangent,k,r,damp(k,mass),damp(r,reduced_i),log_faces,centered_faces});
        bonds.push_back({a,b,joint,area,iy,iz,width,height,m.tensile_strength_pa,m.shear_strength_pa,m.fracture_energy_j_m2,k,r,damp(k,mass),damp(r,reduced_i),m.model==MaterialModel::BrittleBond});
        if(sheet_plasticity&&cells[a].object==1)bonds.back().plastic=compileConnectorPlasticity(m,length0,width,height);
    }
    void grid(unsigned object,MaterialPreset p,Vec3 dimensions,Vec3 center,unsigned nx,unsigned ny,unsigned nz,bool round){
        const Vec3 h{dimensions.x/nx,dimensions.y/ny,dimensions.z/nz};std::map<std::array<int,3>,unsigned> ids;
        for(unsigned x=0;x<nx;++x)for(unsigned y=0;y<ny;++y)for(unsigned z=0;z<nz;++z){
            const Vec3 local{(x+.5)*h.x-dimensions.x/2,(y+.5)*h.y-dimensions.y/2,(z+.5)*h.z-dimensions.z/2};
            if(round&&4*(local.x*local.x/(dimensions.x*dimensions.x)+local.y*local.y/(dimensions.y*dimensions.y)+local.z*local.z/(dimensions.z*dimensions.z))>1)continue;
            ids[{int(x),int(y),int(z)}]=cell(object,h,center+local,p);
        }
        const auto m=makeReferenceMaterial(p);
        for(const auto &[g,a]:ids)for(int dx=-1;dx<=1;++dx)for(int dy=-1;dy<=1;++dy)for(int dz=-1;dz<=1;++dz){
            const auto it=ids.find({g[0]+dx,g[1]+dy,g[2]+dz});if(it==ids.end()||it->second<=a)continue;
            int bond=-1;
            if(dx*dx+dy*dy+dz*dz==1){bond=int(bonds.size());
                if(dx)connect(a,it->second,{double(dx),0,0},{0,1,0},h.x,h.y,h.z,m);
                if(dy)connect(a,it->second,{0,double(dy),0},{0,0,1},h.y,h.z,h.x,m);
                if(dz)connect(a,it->second,{0,0,double(dz)},{1,0,0},h.z,h.x,h.y,m);
            }
            internal.push_back({a,it->second,bond});
        }
    }
    explicit Impl(const Json &d,VoxelExecution storage):world(0,contactCapacity(d,storage),
        storage==VoxelExecution::Reference?RigidJobExecution::ThreadPool:RigidJobExecution::Inline),declaration(d){
        world.setExecutionProfilingEnabled(true);
        if(d.contains("hybrid_free_flight")&&!d["hybrid_free_flight"].is_boolean())throw std::invalid_argument("hybrid_free_flight must be boolean");
        hybrid=d.value("hybrid_free_flight",false);
        if(d.contains("local_rigid_flight")&&!d["local_rigid_flight"].is_boolean())throw std::invalid_argument("local_rigid_flight must be boolean");
        local_flight=d.value("local_rigid_flight",false);
        const std::set<std::string> keys{"sheet","ball","mass_kg","height_m","thickness_m","resolution","support_gap_m","offset_x_m","offset_z_m","dt_s","ball_enabled","gravity_m_s2","solver_iterations","face_law","contact_law","sheet_plasticity","hybrid_free_flight","local_rigid_flight"};
        for(auto i=d.begin();i!=d.end();++i)if(!keys.contains(i.key()))throw std::invalid_argument("unknown voxel experiment field");
        const auto face_law=d.value("face_law",std::string("native-motor"));
        if(face_law!="native-motor"&&face_law!="log-gradient"&&face_law!="centered-log-gradient")throw std::invalid_argument("unsupported face law");
        log_faces=face_law!="native-motor";centered_faces=face_law=="centered-log-gradient";
        const auto plastic=d.value("sheet_plasticity",Json(false));
        if(!plastic.is_boolean())throw std::invalid_argument("sheet_plasticity must be boolean");
        sheet_plasticity=plastic.get<bool>();
        if(sheet_plasticity&&!centered_faces)throw std::invalid_argument("plastic sheet requires centered-log-gradient interfaces");
        world.setCenteredIntegration(centered_faces);
        const auto contact_law=d.value("contact_law",std::string("material-restitution"));
        if(contact_law!="material-restitution"&&contact_law!="resolved-deformation"&&contact_law!="midpoint-unilateral"&&contact_law!="midpoint-block-friction")throw std::invalid_argument("unsupported contact law");
        midpoint_contact=contact_law=="midpoint-unilateral"||contact_law=="midpoint-block-friction";
        resolved_deformation=contact_law!="material-restitution";
        world.setContactRestitutionModel(contact_law=="midpoint-block-friction"?RigidContactRestitution::MidpointBlockFriction:midpoint_contact?RigidContactRestitution::MidpointUnilateral:resolved_deformation?RigidContactRestitution::ResolvedDeformation:RigidContactRestitution::MaterialCombination);
        const auto sheet=preset(d.value("sheet",std::string("glass"))),ball=preset(d.value("ball",std::string("iron")));
        const double requested=scalar(d,"resolution",8,4,16);const unsigned n=unsigned(requested);
        if(n!=requested||(n!=4&&n!=8&&n!=12&&n!=16))throw std::invalid_argument("resolution must be 4, 8, 12 or 16");
        const double thickness=scalar(d,"thickness_m",.004,.002,.04),gap=scalar(d,"support_gap_m",.32,.20,.36);
        if(sheet_plasticity)(void)compileConnectorPlasticity(makeReferenceMaterial(sheet),.4/n,.4/n,thickness);
        const double mass=scalar(d,"mass_kg",1,.1,5),height=scalar(d,"height_m",10,.05,10);
        const double x=scalar(d,"offset_x_m",0,-.8,.8),z=scalar(d,"offset_z_m",0,-.8,.8);
        dt=scalar(d,"dt_s",1./960,1./3840,1./240);
        const double g=scalar(d,"gravity_m_s2",-9.81,-9.81,0);gravity={0,g,0};world.setGravity(gravity);
        const double requested_iterations=scalar(d,"solver_iterations",96,16,256);
        if(requested_iterations!=std::floor(requested_iterations))throw std::invalid_argument("solver_iterations must be integral");
        world.setContactSolverIterations(unsigned(requested_iterations),4);
        feature=thickness;world.configureVoxelContacts(thickness);
        world.setImpactObservationsEnabled(false);
        world.setContactImpulseObservationsEnabled(true);
        world.setForcePhaseObservationsEnabled(true);
        // Supports/floor are declared anchored coarse voxels; no fixed sheet edges.
        cell(3,{.06,.5,.46},{-gap/2,.25,0},MaterialPreset::Concrete,true);
        cell(4,{.06,.5,.46},{gap/2,.25,0},MaterialPreset::Concrete,true);
        for(int xx=-1;xx<=1;++xx)for(int zz=-1;zz<=1;++zz)cell(5,{1,.1,1},{double(xx),-.05,double(zz)},MaterialPreset::Concrete,true);
        grid(1,sheet,{.4,thickness,.4},{0,.5+thickness/2,0},n,1,n,false);
        const auto enabled=d.value("ball_enabled",Json(true));if(!enabled.is_boolean())throw std::invalid_argument("ball_enabled must be boolean");
        if(enabled.get<bool>()){
            const double diameter=std::cbrt(mass/(makeReferenceMaterial(ball).density_kg_m3*.5));
            grid(2,ball,{diameter,diameter,diameter},{x,.5+thickness+height+diameter/2,z},4,4,4,true);
        }
        if(internal.size()>4096)throw std::invalid_argument("voxel neighbour budget exceeded");
        filtering();initial=totals=world.mechanicalTotals(gravity);initial_energy=initial.mechanicalEnergy();
        if(hybrid&&enabled.get<bool>()){
            std::vector<RigidComponentCell> members;
            for(unsigned i=0;i<cells.size();++i)if(cells[i].object==2){if(members.empty())coast_index=i;
                members.push_back({cells[i].id,cells[i].size,contact(makeReferenceMaterial(ball))});}
            coast=std::make_unique<RigidComponent>(10000,std::move(members));
            const auto r=coast->collapse(world,0,{},gravity);receipt(r,"collapse unloaded ball");
            totals=world.mechanicalTotals(gravity);
            if(!r.admitted)throw std::runtime_error("initial component handoff refused: "+r.reason);
        }
    }
    void interval(double h,unsigned depth=0,bool force_full_motion=false){
        guardCoast(h);
        const bool coasting=coast&&coast->collapsed();
        const auto sweep_start=std::chrono::steady_clock::now();
        double minBallY=1e20,maxSpeed=0;MatterBodyId driver{};
        std::vector<RigidSnapshot> before_states;before_states.reserve(cells.size());
        for(unsigned i=0;i<cells.size();++i){const auto &c=cells[i];const auto s=active(i)?world.snapshot(nativeId(i)):RigidSnapshot{};before_states.push_back(s);if(!c.fixed&&active(i)){
            const double speed=length(s.linear_velocity_m_s)+length(s.angular_velocity_rad_s)*length(c.size)/2;
            if(speed>maxSpeed){maxSpeed=speed;driver=c.id;}
            if(c.object==2)minBallY=std::min(minBallY,s.center_of_mass_world_m.y-length(c.size)/2);}}
        auto flight=force_full_motion?std::vector<bool>(cells.size(),false):isolatedFlight(before_states,h);
        if(local_flight){maxSpeed=0;driver=0;
            for(unsigned i=0;i<cells.size();++i)if(!cells[i].fixed&&active(i)){
                if(flight[i]){++flight_candidates;continue;}
                const auto &s=before_states[i];const double speed=length(s.linear_velocity_m_s)+length(s.angular_velocity_rad_s)*length(cells[i].size)/2;
                if(speed>maxSpeed){maxSpeed=speed;driver=cells[i].id;}
            }}
        const unsigned flights=unsigned(std::count(flight.begin(),flight.end(),true));
        sweep_wall_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-sweep_start).count();
        if(minBallY<.65&&maxSpeed*h>feature*.05){++motion_splits;++motion_drivers[driver];max_motion_depth=std::max(max_motion_depth,depth);
            if(depth>=14)throw std::runtime_error("voxel swept distance gate refused");interval(h/2,depth+1,force_full_motion);interval(h/2,depth+1,force_full_motion);return;}
        const auto observation_start=std::chrono::steady_clock::now();
        std::vector<JoltWorld::FaceSpringObservation> faces_before(bonds.size()),faces_after(bonds.size());
        double before_elastic=0;
        for(unsigned i=0;i<bonds.size();++i)if(detailed(bonds[i])){const auto &b=bonds[i];faces_before[i]=world.faceSpringObservation(b.joint);before_elastic+=quadratic(b.k,faces_before[i].displacement_cs_m)+quadratic(b.r,faces_before[i].rotation_cs_rad);}
        observation_wall_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-observation_start).count();
        const double before=totals.mechanicalEnergy()+before_elastic;
        double candidateEnergy=0,after_elastic=0;MechanicalTotals candidateTotals;RigidStepWork candidateWork;Json candidateBoundary,candidateTwist;
        std::vector<RigidMechanicalState> candidate_states;
        std::vector<ConnectorPlasticUpdate> candidate_plastic(sheet_plasticity?bonds.size():0);
        double candidate_plastic_work=0,candidate_return_excess=0,candidate_actuator_work=0;
        Vec3 candidate_actuator_impulse{},candidate_actuator_angular{},candidate_actuator_phase_residual{};
        const auto trial_start=std::chrono::steady_clock::now();
        bool coast_contact=false,flight_unsafe=false;
        const bool accepted=world.runReversibleTrial([&]{
            const auto native_start=std::chrono::steady_clock::now();
            // Queue forces inside the trial so refusal restores both the force
            // accumulator and the body activation, without duplicate reapplication.
            for(const auto &c:cells)if(!c.fixed){const auto a=actuators.find(c.object);
                if(a!=actuators.end()&&lengthSquared(a->second)>0)world.pushBody(c.id,c.mass*a->second);}
            world.step(h);
            if(coasting)for(const auto &c:world.contactImpulseObservations())if(c.a==coast->proxy()||c.b==coast->proxy()){
                coast_contact=true;return false;
            }
            const auto totals_start=std::chrono::steady_clock::now();
            native_step_wall_ms+=std::chrono::duration<double,std::milli>(totals_start-native_start).count();
            candidateTotals={};candidate_states.clear();candidate_states.reserve(cells.size());
            for(unsigned i=0;i<cells.size();++i){const auto state=active(i)?world.mechanicalState(nativeId(i)):RigidMechanicalState{};
                candidate_states.push_back(state);candidateTotals+=measureRigidMechanics(state,gravity);}
            if(flights&&!candidateFlightSafe(flight,before_states,candidate_states)){flight_unsafe=true;return false;}
            after_elastic=0;
            const auto faces_start=std::chrono::steady_clock::now();
            totals_wall_ms+=std::chrono::duration<double,std::milli>(faces_start-totals_start).count();
            for(unsigned i=0;i<bonds.size();++i)if(detailed(bonds[i])){const auto &b=bonds[i];faces_after[i]=world.faceSpringObservation(b.joint);after_elastic+=quadratic(b.k,faces_after[i].displacement_cs_m)+quadratic(b.r,faces_after[i].rotation_cs_rad);}
            candidate_faces_wall_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-faces_start).count();
            candidateWork=measureWork(before_states,candidate_states,faces_before,faces_after);
            candidate_actuator_work=0;candidate_actuator_impulse={};candidate_actuator_angular={};candidate_actuator_phase_residual={};
            for(unsigned i=0;i<cells.size();++i){const auto &c=cells[i];const auto a=actuators.find(c.object);
                if(c.fixed||a==actuators.end()||lengthSquared(a->second)==0)continue;
                const auto force=c.mass*a->second,push=force*h;
                candidate_actuator_work+=dot(force,candidate_states[i].motion.center_of_mass_world_m-before_states[i].center_of_mass_world_m);
                candidate_actuator_impulse+=push;candidate_actuator_angular+=cross(before_states[i].center_of_mass_world_m,push);
            }
            if(actuation_used)for(const auto &phase:world.forcePhaseObservations()){
                const auto &c=cells.at(slot(phase.body));const auto a=actuators.find(c.object);
                if(a==actuators.end()||lengthSquared(a->second)==0)continue;
                candidate_actuator_phase_residual+=phase.before.mass_kg*(phase.velocity_after_forces_m_s-phase.before.motion.linear_velocity_m_s)-phase.gravity_impulse_n_s-c.mass*a->second*h;
            }
            if(midpoint_contact)candidateBoundary=measureBoundary(before_states,h,candidateTwist);
            for(unsigned i=0;i<bonds.size();++i)if(detailed(bonds[i])&&bonds[i].plastic){
                const auto &b=bonds[i];const auto &s=faces_after[i];const auto &rest=b.plastic_state.plastic_rest;
                auto &update=candidate_plastic[i];
                update=advanceConnectorPlasticity(*b.plastic,b.plastic_state,
                    {s.displacement_cs_m.x+rest[0],s.displacement_cs_m.y+rest[1],s.displacement_cs_m.z+rest[2],
                     s.rotation_cs_rad.x+rest[3],s.rotation_cs_rad.y+rest[4],s.rotation_cs_rad.z+rest[5]});
                after_elastic+=update.stored_energy_j-quadratic(b.k,s.displacement_cs_m)-quadratic(b.r,s.rotation_cs_rad);
                candidate_plastic_work+=update.plastic_increment_j;candidate_return_excess+=update.return_excess_increment_j;
                const auto &p=update.state.plastic_rest;
                if(update.yielded)world.setFacePlasticRest(b.joint,{p[0],p[1],p[2]},{p[3],p[4],p[5]});
            }
            const double after=candidateTotals.mechanicalEnergy()+after_elastic;candidateEnergy=after;
            const double accounted=after+candidate_plastic_work+candidate_return_excess-candidate_actuator_work;
            return std::isfinite(accounted)&&accounted-before<=1e-5*std::max(1.,std::abs(before))+1e-6&&
                accounted+fracture+discarded_elastic+plastic_work+plastic_return_excess-actuator_work-transfer_energy-initial_energy<=.1;
        });
        trial_wall_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-trial_start).count();
        if(coast_contact){++rejected;expandCoast("candidate contact rollback");interval(h,depth);return;}
        if(flight_unsafe){++rejected;++flight_rollbacks;
            if(depth>=14)throw std::runtime_error("isolated rigid flight candidate path refused");
            interval(h/2,depth+1,true);interval(h/2,depth+1,true);return;}
        if(!accepted){++rejected;refused_work={{"time_s",time},{"dt_s",h},{"depth",depth},{"before_j",before},{"candidate_j",candidateEnergy},{"elastic_change_j",after_elastic-before_elastic},{"work",workJson(candidateWork)}};if(actuation_used)refused_work["actuator_work_j"]=candidate_actuator_work;if(sheet_plasticity){refused_work["plastic_work_j"]=candidate_plastic_work;refused_work["plastic_return_excess_j"]=candidate_return_excess;}if(midpoint_contact){refused_work["midpoint_boundary"]=candidateBoundary;refused_work["worst_twist_contact"]=candidateTwist;}if(depth>=14)throw std::runtime_error("native integration energy gate refused at "+std::to_string(time)+" s: before="+std::to_string(before)+", candidate="+std::to_string(candidateEnergy)+", h="+std::to_string(h)+"; last accepted state retained");interval(h/2,depth+1,force_full_motion);interval(h/2,depth+1,force_full_motion);return;}
        actuator_work+=candidate_actuator_work;actuator_impulse+=candidate_actuator_impulse;actuator_angular_impulse+=candidate_actuator_angular;actuator_force_phase_residual+=candidate_actuator_phase_residual;
        plastic_work+=candidate_plastic_work;plastic_return_excess+=candidate_return_excess;
        for(unsigned i=0;i<bonds.size();++i)if(detailed(bonds[i])&&bonds[i].plastic)bonds[i].plastic_state=candidate_plastic[i].state;
        if(midpoint_contact)for(auto it=candidateBoundary.begin();it!=candidateBoundary.end();++it){
            const double value=it.value().get<double>();
            boundary_total[it.key()]=it.key().starts_with("max_")?std::max(boundary_total[it.key()].get<double>(),value):boundary_total[it.key()].get<double>()+value;
        }
        const auto add_work=[&](double RigidStepWork::*field){work_total.*field+=candidateWork.*field;};
        for(auto field:{&RigidStepWork::gravity_work_j,&RigidStepWork::gyro_kick_j,&RigidStepWork::other_force_work_j,&RigidStepWork::spring_work_j,&RigidStepWork::contact_work_j,&RigidStepWork::solver_residual_work_j,&RigidStepWork::rotation_drift_j,&RigidStepWork::potential_change_j,&RigidStepWork::kinetic_change_j,&RigidStepWork::energy_residual_j,&RigidStepWork::velocity_limit_work_j,&RigidStepWork::post_integration_work_j})add_work(field);
        work_total.solver_linear_residual_n_s+=candidateWork.solver_linear_residual_n_s;work_total.solver_angular_residual_n_m_s+=candidateWork.solver_angular_residual_n_m_s;work_total.angular_drift_n_m_s+=candidateWork.angular_drift_n_m_s;
        work_total.velocity_limit_impulse_n_s+=candidateWork.velocity_limit_impulse_n_s;work_total.velocity_limit_couple_n_m_s+=candidateWork.velocity_limit_couple_n_m_s;
        elastic_change_j+=after_elastic-before_elastic;ledger_change_j+=candidateEnergy-before;
        std::vector<RigidSnapshot> after_states;after_states.reserve(cells.size());for(unsigned i=0;i<cells.size();++i){const auto &c=cells[i];after_states.push_back(candidate_states[i].motion);if(!c.fixed&&active(i)){linear_velocity_quadratic+=.5*(coasting&&i==coast_index?candidate_states[i].mass_kg:c.mass)*lengthSquared(after_states[i].linear_velocity_m_s-before_states[i].linear_velocity_m_s);peak_spin=std::max(peak_spin,length(after_states[i].angular_velocity_rad_s));if(length(after_states[i].angular_velocity_rad_s)>=999.99)++spin_limit_samples;}}
        Vec3 reaction{};const auto support_angular_before=support_reaction_angular_impulse;
        for(const auto &contact:world.contactImpulseObservations()){
            const auto ai=slot(contact.a),bi=slot(contact.b);
            if(local_flight){for(auto id:{contact.a,contact.b})if(flown_cells.contains(id))returned_contact_cells.insert(id);}
            if(ai>=cells.size()||bi>=cells.size())throw std::runtime_error("voxel contact references an undeclared cell");
            const auto &a=before_states[ai],&b=before_states[bi],&aa=after_states[ai],&bb=after_states[bi];
            const auto transfer=[&](Vec3 point,Vec3 push){
                const auto ra=point-a.center_of_mass_world_m,rb=point-b.center_of_mass_world_m;
                const auto speed=bb.linear_velocity_m_s+cross(bb.angular_velocity_rad_s,rb)-aa.linear_velocity_m_s-cross(aa.angular_velocity_rad_s,ra);
                if(cells[ai].fixed&&!cells[bi].fixed){reaction-=push;support_reaction_angular_impulse-=cross(point,push);}
                if(!cells[ai].fixed&&cells[bi].fixed){reaction+=push;support_reaction_angular_impulse+=cross(point,push);}
                return dot(push,speed);
            };
            for(const auto &point:contact.points)contact_normal_work+=transfer(point.point_world_m,contact.normal_a_to_b*point.normal_impulse_n_s);
            contact_friction_work+=transfer(contact.friction_point_world_m,contact.friction_impulse_on_b_n_s);
            contact_twist_work+=dot(contact.twist_impulse_on_b_n_m_s,bb.angular_velocity_rad_s-aa.angular_velocity_rad_s);
            if(cells[ai].fixed&&!cells[bi].fixed)support_reaction_angular_impulse-=contact.twist_impulse_on_b_n_m_s;
            if(!cells[ai].fixed&&cells[bi].fixed)support_reaction_angular_impulse+=contact.twist_impulse_on_b_n_m_s;
            ++contact_manifold_samples;contact_point_samples+=unsigned(contact.points.size());
        }
        support_reaction_impulse+=reaction;
        Vec3 gravity_angular{};for(const auto &phase:world.forcePhaseObservations())gravity_angular+=cross(phase.before.motion.center_of_mass_world_m,phase.gravity_impulse_n_s);
        full_angular_residual+=candidateTotals.angular_momentum_kg_m2_s-totals.angular_momentum_kg_m2_s-gravity_angular-candidate_actuator_angular+(support_reaction_angular_impulse-support_angular_before);
        // Native gravity acts only on the start-of-Update active bodies.
        // Reactions above are ON the support; their negatives act on dynamics.
        const auto scheduled_gravity=world.observedGravityImpulseN_s();gravity_impulse+=scheduled_gravity;
        momentum_residual+=candidateTotals.linear_momentum_kg_m_s-totals.linear_momentum_kg_m_s-scheduled_gravity-candidate_actuator_impulse+reaction;
        for(unsigned i=0;i<bonds.size();++i)if(detailed(bonds[i])){
            const auto &b=bonds[i];const auto &geometry=faces_before[i],&response=faces_after[i];
            if(!response.solver_scheduled.value())continue;
            const auto &a=before_states[b.a],&c=before_states[b.b],&aa=after_states[b.a],&cc=after_states[b.b];
            // SixDOF applies equal/opposite linear impulses at B's anchor.
            const auto arm_a=geometry.anchor_b_world_m-a.center_of_mass_world_m,arm_b=geometry.anchor_b_world_m-c.center_of_mass_world_m;
            const auto relative=cc.linear_velocity_m_s+cross(cc.angular_velocity_rad_s,arm_b)-aa.linear_velocity_m_s-cross(aa.angular_velocity_rad_s,arm_a);
            auto spin=cc.angular_velocity_rad_s-aa.angular_velocity_rad_s;
            auto evaluated_relative=relative;
            if(centered_faces){
                evaluated_relative=.5*(relative+c.linear_velocity_m_s+cross(c.angular_velocity_rad_s,arm_b)-a.linear_velocity_m_s-cross(a.angular_velocity_rad_s,arm_a));
                spin=.5*(spin+c.angular_velocity_rad_s-a.angular_velocity_rad_s);
            }
            Vec3 speed{},rate{};
            double *vs[]={&speed.x,&speed.y,&speed.z},*ws[]={&rate.x,&rate.y,&rate.z};
            for(unsigned axis=0;axis<3;++axis){*vs[axis]=dot(evaluated_relative,geometry.translation_axes_world[axis]);*ws[axis]=dot(spin,geometry.rotation_axes_world[axis]);}
            const auto q0=geometry.displacement_cs_m,r0=geometry.rotation_error_cs_rad;
            material_damping+=2*h*(quadratic(b.damping,speed)+quadratic(b.rotation_damping,rate));
            if(!centered_faces)implicit_elastic_loss+=h*h*(quadratic(b.k,speed)+quadratic(b.r,rate));
            const double work=dot(response.linear_impulse_cs_n_s,speed)+dot(response.angular_impulse_cs_n_m_s,rate);spring_endpoint_work+=work;
            const double predicted=quadratic(b.k,q0+speed*h)+quadratic(b.r,r0+rate*h);
            const double actual=quadratic(b.k,response.displacement_cs_m)+quadratic(b.r,response.rotation_cs_rad);
            const double old_native=quadratic(b.k,q0)+quadratic(b.r,r0);
            const double old_physical=quadratic(b.k,q0)+quadratic(b.r,geometry.rotation_cs_rad);
            // Compare increments, not absolute potentials. The native motor's
            // 2*sin(angle/2) error differs from the reported physical angle.
            // Counting that absolute offset every step would invent a loss.
            spring_geometry_change+=(actual-old_physical)-(predicted-old_native);
            spring_residual_work+=work+predicted-old_native+2*h*(quadratic(b.damping,speed)+quadratic(b.rotation_damping,rate))+(centered_faces?0:h*h*(quadratic(b.k,speed)+quadratic(b.r,rate)));
            const Vec3 residual{response.linear_impulse_cs_n_s.x/h+b.k.x*q0.x+(b.damping.x+h*b.k.x*(centered_faces?.5:1))*speed.x,
                response.linear_impulse_cs_n_s.y/h+b.k.y*q0.y+(b.damping.y+h*b.k.y*(centered_faces?.5:1))*speed.y,
                response.linear_impulse_cs_n_s.z/h+b.k.z*q0.z+(b.damping.z+h*b.k.z*(centered_faces?.5:1))*speed.z};
            max_spring_residual_n=std::max(max_spring_residual_n,length(residual));
        }

        if(coasting)coast_time+=h;
        flight_accepted+=flights;last_free_cells=flights;
        if(flights)for(unsigned i=0;i<cells.size();++i)if(flight[i]){++flown_cells[cells[i].id];
            peak_flight_surface_travel=std::max(peak_flight_surface_travel,h*(length(before_states[i].linear_velocity_m_s)+length(before_states[i].angular_velocity_rad_s)*length(cells[i].size)/2));}
        time+=h;++substeps;
        bool changed=false;
        for(unsigned i=0;i<bonds.size();++i)if(detailed(bonds[i])){
            auto &b=bonds[i];const auto &s=faces_after[i];b.energy=quadratic(b.k,s.displacement_cs_m)+quadratic(b.r,s.rotation_cs_rad);
            if(b.plastic)b.energy=candidate_plastic[i].stored_energy_j;
            // No new strain/impulse while dormant. Dividing a cached lambda by
            // an unrelated fragment's smaller dt would invent a new stress.
            if(!s.solver_scheduled.value())continue;
            const auto f=s.linear_impulse_cs_n_s/h;auto m=s.angular_impulse_cs_n_m_s/h;
            if(log_faces){
                // Generalized log-strain impulses are not physical torque components.
                // Project the actual start-of-solve torque into the material frame.
                const auto &frame=faces_before[i];
                const auto torque=frame.rotation_axes_world[0]*m.x+frame.rotation_axes_world[1]*m.y+frame.rotation_axes_world[2]*m.z;
                m={dot(torque,frame.translation_axes_world[0]),dot(torque,frame.translation_axes_world[1]),dot(torque,frame.translation_axes_world[2])};
            }
            const double tensile=std::max(0.,-f.x)/b.area+std::abs(m.y)*b.height/(2*b.iy)+std::abs(m.z)*b.width/(2*b.iz);
            const double shear=std::hypot(f.y,f.z)/b.area+std::abs(m.x)*std::max(b.width,b.height)/(2*(b.iy+b.iz));
            const double ratio=std::max(tensile/b.strength,shear/b.shear);peak_stress_ratio=std::max(peak_stress_ratio,ratio);
            if(b.brittle&&ratio>=1&&b.energy>=b.gc*b.area){
                const double work=b.gc*b.area;fracture+=work;discarded_elastic+=b.energy-work;
                b.live=false;changed=true;++broken;world.removeJoint(b.joint);
                if(events.size()<4096)events.push_back({{"time_s",time},{"object",cells[b.a].object},{"a",cells[b.a].id},{"b",cells[b.b].id},{"stress_ratio",ratio},{"stored_energy_j",b.energy},{"fracture_work_j",work}});
            }
        }
        if(changed)filtering();totals=candidateTotals;
    }
    void step(){const auto start=std::chrono::steady_clock::now();interval(dt);++ticks;
        max_wall_ms=std::max(max_wall_ms,std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());
    }
};
VoxelImpactWorld::VoxelImpactWorld(const std::string &source,VoxelExecution storage):impl_(std::make_unique<Impl>(Json::parse(source),storage)){}
VoxelImpactWorld::~VoxelImpactWorld()=default;
void VoxelImpactWorld::step(unsigned count){if(count<1||count>64||impl_->time+count*impl_->dt>4.000001)throw std::invalid_argument("bounded steps/duration exceeded");for(unsigned i=0;i<count;++i)impl_->step();}
void VoxelImpactWorld::setObjectAcceleration(unsigned object,const std::array<double,3> &acceleration){
    auto &w=*impl_;const Vec3 a{acceleration[0],acceleration[1],acceleration[2]};
    if(object<1||object>2||!std::isfinite(lengthSquared(a))||length(a)>30)
        throw std::invalid_argument("external actuator needs dynamic object 1/2 and finite acceleration magnitude <= 30 m/s2");
    if(!w.centered_faces)throw std::invalid_argument("external actuator requires centered pose/interface integration");
    if(!std::any_of(w.cells.begin(),w.cells.end(),[&](const auto &c){return c.object==object&&!c.fixed;}))
        throw std::invalid_argument("external actuator object has no dynamic cells");
    if(w.actuator_commands>=32)throw std::invalid_argument("external actuator command limit reached; reset to continue");
    ++w.actuator_commands;w.actuators[object]=a;w.actuation_used=true;w.actuator_started=w.time;
    w.events.push_back({{"time_s",w.time},{"action","external-acceleration"},{"object",object},{"acceleration_m_s2",v(a)}});
}
std::string VoxelImpactWorld::snapshotJson() const {
    const auto &w=*impl_;const auto roots=w.components();Json cells=Json::array(),objects=Json::array();
    const auto execution=w.world.executionProfile();
    double mass=0,elastic=0;for(const auto &b:w.bonds)if(b.live)elastic+=b.energy;
    for(unsigned i=0;i<w.cells.size();++i){const auto &c=w.cells[i];const auto s=w.cellSnapshot(i);const auto q=s.orientation_world;
        if(!c.fixed)mass+=c.mass;
        cells.push_back({{"id",c.id},{"object",c.object},{"component",roots[i]},{"size_m",v(c.size)},{"position_m",v(s.center_of_mass_world_m)},{"quaternion_wxyz",{q.w,q.x,q.y,q.z}},{"velocity_m_s",v(s.linear_velocity_m_s)},{"spin_rad_s",v(s.angular_velocity_rad_s)},{"mass_kg",c.mass},{"material",c.material},{"fixed",c.fixed}});
    }
    for(unsigned object:{1U,2U}){double objectmass=0;unsigned count=0,breaks=0;std::set<unsigned> parts;Vec3 center{},speed{};double maxtravel=0;
        for(unsigned i=0;i<w.cells.size();++i)if(w.cells[i].object==object){const auto &c=w.cells[i];const auto s=w.cellSnapshot(i);objectmass+=c.mass;++count;parts.insert(roots[i]);center+=s.center_of_mass_world_m*c.mass;speed+=s.linear_velocity_m_s*c.mass;maxtravel=std::max(maxtravel,length(s.center_of_mass_world_m-c.initial));}
        for(const auto &b:w.bonds)if(!b.live&&w.cells[b.a].object==object)++breaks;
        objects.push_back({{"id",object},{"mass_kg",objectmass},{"cells",count},{"pieces",parts.size()},{"broken_faces",breaks},{"center_m",v(objectmass?center/objectmass:Vec3{})},{"velocity_m_s",v(objectmass?speed/objectmass:Vec3{})},{"max_travel_m",maxtravel}});
    }
    Json result={{"schema","banjo.voxel-impact.v1"},{"declaration",w.declaration},{"time_s",w.time},{"dt_s",w.dt},{"ticks",w.ticks},{"substeps",w.substeps},{"rejected_trials",w.rejected},{"cells",cells},{"objects",objects},{"events",w.events},
        {"diagnostics",{{"dynamic_mass_kg",mass},{"kinetic_j",w.totals.kinetic_energy_j},{"potential_j",w.totals.gravitational_potential_energy_j},{"elastic_j",elastic},{"fracture_j",w.fracture},{"fracture_overshoot_loss_j",w.discarded_elastic},{"unclosed_energy_j",w.totals.mechanicalEnergy()+elastic+w.fracture+w.discarded_elastic-w.initial_energy},{"linear_momentum_n_s",v(w.totals.linear_momentum_kg_m_s)},{"angular_momentum_kg_m2_s",v(w.totals.angular_momentum_kg_m2_s)},{"max_step_wall_ms",w.max_wall_ms},{"peak_stress_ratio",w.peak_stress_ratio},{"linear_velocity_quadratic_j",w.linear_velocity_quadratic},{"peak_spin_rad_s",w.peak_spin},{"native_spin_limit_samples",w.spin_limit_samples},{"spring_material_damping_j",w.material_damping},{"spring_implicit_elastic_loss_j",w.implicit_elastic_loss},{"spring_endpoint_work_j",w.spring_endpoint_work},{"spring_geometry_change_j",w.spring_geometry_change},{"spring_residual_work_j",w.spring_residual_work},{"max_spring_solver_residual_n",w.max_spring_residual_n},{"profile",{{"sweep_ms",w.sweep_wall_ms},{"trial_ms",w.trial_wall_ms},{"observation_ms",w.observation_wall_ms},{"native_step_ms",w.native_step_wall_ms},{"totals_ms",w.totals_wall_ms},{"candidate_faces_ms",w.candidate_faces_wall_ms}}}}},
        {"contact_audit",{{"normal_endpoint_work_j",w.contact_normal_work},{"friction_endpoint_work_j",w.contact_friction_work},{"twist_endpoint_work_j",w.contact_twist_work},{"support_reaction_impulse_n_s",v(w.support_reaction_impulse)},{"support_reaction_angular_impulse_n_m_s",v(w.support_reaction_angular_impulse)},{"gravity_impulse_n_s",v(w.gravity_impulse)},{"linear_momentum_residual_n_s",v(w.momentum_residual)},{"manifold_samples",w.contact_manifold_samples},{"point_samples",w.contact_point_samples},{"scope","Actual discrete native solver impulses at start-of-solve contact midpoints; endpoint work is diagnostic, not a closed energy balance. Gravity counts start-of-Update active bodies. Anchored reactions use world-origin moments; no dormant cache impulses or estimated launch velocities."}}},
        {"step_work",{{"measured",Impl::workJson(w.work_total)},{"elastic_change_j",w.elastic_change_j},{"net_change_j",w.ledger_change_j},
            {"closure_residual_j",w.ledger_change_j-w.work_total.kinetic_change_j-w.work_total.potential_change_j-w.elastic_change_j},
            {"full_angular_residual_n_m_s",v(w.full_angular_residual)},{"last_rejected_trial",w.refused_work},
            {"scope","Actual native force-phase velocities and shared-phase spring/contact work. Residual, gyro and rotation drift are signed numerical/unexplained terms, not heat. Algebraic closure is not material realism or solver conservation."}}},
        {"qualification",{{"calibrated",false},{"contact_law",impl_->declaration.value("contact_law",std::string("material-restitution"))=="midpoint-block-friction"?"midpoint-block-friction":impl_->midpoint_contact?"midpoint-unilateral":impl_->resolved_deformation?"resolved-deformation":"material-restitution"},{"face_law",impl_->centered_faces?"centered-log-gradient":impl_->log_faces?"log-gradient":"native-motor"},{"model",impl_->midpoint_contact?
            "Experimental frozen-normal unilateral midpoint boundary and centered interfaces. Not compliant indentation or calibrated material contact. Finite rotations/friction/full energy remain unqualified.":impl_->centered_faces?
            "Experimental centered elastic rows and midpoint pose velocities. Linear energy oracles pass; coupled contact and finite rotations remain unqualified. Not compliant surface contact.":impl_->log_faces?
            "Experimental SO(3) energy-gradient interfaces. Analytical torque gradients pass; full impacts still have unresolved energy refusals/losses. Not a realtime or calibrated material model.":
            "Passive finite-box native six-axis elastic interfaces. Finite-rotation/integration/full energy and angular momentum accounts remain unqualified."},
            {"limits","Brittle strength AND stored fracture-work admission. Metals/oak remain elastic, not brittle; plasticity/grain are unsupported."}}}};
    Json motion_drivers=Json::array();
    for(const auto &[id,count]:w.motion_drivers){const auto &c=w.cells.at(id-100);
        motion_drivers.push_back({{"body",id},{"object",c.object},{"split_proposals",count}});}
    result["diagnostics"]["profile"]["motion"]={{"split_proposals",w.motion_splits},{"max_depth",w.max_motion_depth},{"drivers",motion_drivers},
        {"scope","Recursive proposal counters, not elapsed-time contributions. The fastest cell drives the existing global thickness/surface-speed rule. Energy rejections are separate."}};
    Json flown=Json::array();for(const auto &[id,count]:w.flown_cells)flown.push_back({{"body",id},{"accepted_intervals",count}});
    if(w.local_flight)result["rigid_flight"]={{"flown_cells",flown},{"returned_contact_cells",w.returned_contact_cells},
        {"current_free_cells",w.last_free_cells},{"peak_free_surface_travel_m",w.peak_flight_surface_travel},{"mode","isolated-native-singletons"},{"candidate_cell_intervals",w.flight_candidates},
        {"accepted_cell_intervals",w.flight_accepted},{"candidate_path_rollbacks",w.flight_rollbacks},
        {"scope","Only disconnected native cells without external loading may skip the global thickness motion bound in empty space. Conservative predicted and actual candidate path envelopes restore the original limit near other objects. Connected material, contact response and energy gates remain detailed; not local island integration or calibrated fracture."}};
    if(w.hybrid){result["hybrid"]={{"mode","unloaded-ball-free-flight"},{"collapsed",w.coast&&w.coast->collapsed()},
        {"coast_time_s",w.coast_time},{"active_native_bodies",w.world.activeBodyIds().size()},
        {"transfer_energy_j",w.transfer_energy},{"energy_after_transfer_correction_j",w.totals.mechanicalEnergy()+elastic+w.fracture+w.discarded_elastic+w.plastic_work+w.plastic_return_excess-w.actuator_work-w.transfer_energy-w.initial_energy},{"transfers",w.transfers},
        {"scope","Experimental initial unloaded ball continuation only. Original occupied cells and face rest survive transfer; prospective contact or a candidate contact restores detail before response. No post-fracture coarsening, loaded bending, second-impact speed or calibrated material law admission."}};}
    if(w.sheet_plasticity){
        Json history=Json::array();unsigned yielded=0;
        for(const auto &b:w.bonds)if(b.plastic){const auto &s=b.plastic_state;
            if(s.yielded_updates)++yielded;
            history.push_back({{"a",w.cells[b.a].id},{"b",w.cells[b.b].id},{"plastic_rest",s.plastic_rest},
                {"accumulated_flow",s.accumulated_flow},{"plastic_work_j",s.plastic_dissipation_j},
                {"return_excess_j",s.return_excess_j},{"yielded_updates",s.yielded_updates},{"elastic_j",b.energy}});
        }
        result["plasticity"]={{"model","independent-six-mode-perfect-plastic-v1"},{"yielded_connectors",yielded},
            {"plastic_work_j",w.plastic_work},{"return_excess_j",w.plastic_return_excess},{"history",history},
            {"units","Rest/flow axes 0..2: m; axes 3..5: rad. Work: J."},
            {"scope","Experimental endpoint return with persistent native rest; numerical projection excess is separate from physical yield work. Not continuum J2, hardening, grain, tearing or calibrated plate plasticity."}};
        result["diagnostics"]["unclosed_energy_j"]=w.totals.mechanicalEnergy()+elastic+w.fracture+w.discarded_elastic+w.plastic_work+w.plastic_return_excess-w.initial_energy;
        result["step_work"]["plastic_work_j"]=w.plastic_work;
        result["step_work"]["plastic_return_excess_j"]=w.plastic_return_excess;
        result["qualification"]["limits"]="Sheet uses independent six-mode perfect plasticity; ball retains its declared elastic/brittle law. No hardening, grain, ductile tearing, restart persistence or continuum J2 admission. Full contact/energy/refinement remains unqualified.";
    }
    if(w.actuation_used){
        Json commands=Json::array();for(const auto &[object,a]:w.actuators)commands.push_back({{"object",object},{"acceleration_m_s2",v(a)}});
        result["actuation"]={{"commands",commands},{"started_at_s",w.actuator_started},{"work_j",w.actuator_work},
            {"impulse_n_s",v(w.actuator_impulse)},{"angular_impulse_n_m_s",v(w.actuator_angular_impulse)},
            {"force_phase_impulse_residual_n_s",v(w.actuator_force_phase_residual)},
            {"scope","Declared mass times acceleration is queued as native center-of-mass force; work is force dotted with accepted COM travel. Nominal impulse/torque and observed force-phase residual are separate. No pose/velocity assignment or material removal; full coupled conservation remains unqualified."}};
        result["diagnostics"]["unclosed_energy_j"]=w.totals.mechanicalEnergy()+elastic+w.fracture+w.discarded_elastic+w.plastic_work+w.plastic_return_excess-w.actuator_work-w.initial_energy;
        result["step_work"]["actuator_trajectory_work_j"]=w.actuator_work;
    }
    if(w.midpoint_contact)result["midpoint_boundary"]=w.boundary_total;
    auto &profile=result["diagnostics"]["profile"];
    profile["execution"]={{"enabled",execution.enabled},{"step_calls",execution.step_calls},{"trial_calls",execution.trial_calls},{"trial_restores",execution.trial_restores},
        {"step_prepare_ms",execution.step_prepare_ms},{"native_update_ms",execution.native_update_ms},{"contact_observation_ms",execution.contact_observation_ms},{"post_step_ms",execution.post_step_ms},
        {"trial_capture_ms",execution.trial_capture_ms},{"trial_restore_ms",execution.trial_restore_ms},
        {"scope","Cumulative host wall time including rejected trials; disjoint step stages. Native update includes Jolt jobs and enabled callbacks, not solver-only time. Trial capture/restore are outside the step stages; outer trial_ms is inclusive. Timing never controls physics."}};
    return result.dump();
}
}
