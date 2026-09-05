#include "platform/CompiledRuntime.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <limits>
#include <numeric>
#include <set>
#include <stdexcept>

namespace banjo {
namespace {
using json=nlohmann::json;
json vec(Vec3 v){return {v.x,v.y,v.z};}
Quat inverse(Quat q){return {q.w,-q.x,-q.y,-q.z};}
}
CompiledRuntime::CompiledRuntime(Vec3 gravity,const std::vector<CompiledRuntimeObject> &inputs,
    const RigidSurfaceDescription *ground,const std::vector<std::array<Vec3,3>> &bowl,MaterialPreset surface):gravity_(gravity){
    if(inputs.empty()||inputs.size()>128)throw std::invalid_argument("compiled runtime supports 1..128 objects");
    rigid_.setGravity(gravity);rigid_.setDetailedImpactObservations(true);
    if(ground)rigid_.addSupportSurface(*ground);else if(!bowl.empty())rigid_.addTriangleSupport(bowl,makeReferenceMaterial(surface));
    for(auto &input:inputs){
        objects_.push_back({input.id,input.material,input.shape,CompiledDamage(compileObject(input.shape,makeReferenceMaterial(input.material),input.seed))});
        unsigned index=unsigned(objects_.size()-1);std::vector<unsigned> nodes(objects_.back().damage.object().samples.size());std::iota(nodes.begin(),nodes.end(),0);
        Vec3 origin;auto desc=description(index,nodes,input.id,input.state,origin);
        // A smooth primitive is the intact collision proxy. After separation,
        // the quadrature samples supply disjoint coarse fragment proxies.
        desc.parts={{input.shape,{}}};rigid_.addCompound(desc);
        components_.emplace(input.id,Component{index,std::move(nodes),origin});
    }
}
RigidCompoundDescription CompiledRuntime::description(unsigned object,const std::vector<unsigned> &nodes,unsigned id,const RigidSnapshot &state,Vec3 &origin) const{
    const auto &compiled=objects_[object].damage.object();RigidCompoundDescription d;d.body_id=id;d.material=compiled.material;d.state=state;
    origin={};for(auto i:nodes){auto &s=compiled.samples[i];d.mass_kg+=s.mass_kg;origin+=s.center_m*s.mass_kg;}origin=origin/d.mass_kg;
    for(auto i:nodes){const auto &s=compiled.samples[i];const Vec3 r=s.center_m-origin;const double p[3]{r.x,r.y,r.z};
        d.parts.push_back({s.collision,r});for(unsigned a=0;a<3;++a)for(unsigned b=0;b<3;++b)d.inertia_local_kg_m2.m[a][b]+=s.intrinsic_inertia.m[a][b]+s.mass_kg*((a==b?lengthSquared(r):0)-p[a]*p[b]);
    }
    return d;
}
void CompiledRuntime::split(unsigned id){
    auto it=components_.find(id);if(it==components_.end())return;auto old=it->second;
    auto roots=objects_[old.object].damage.components();std::map<unsigned,std::vector<unsigned>> groups;
    for(auto n:old.nodes)groups[roots[n]].push_back(n);if(groups.size()<2)return;
    const auto state=rigid_.snapshot(id);const auto before=measureRigidMechanics(rigid_.mechanicalState(id),gravity_);
    std::vector<std::pair<unsigned,Component>> pending;MechanicalTotals after;
    try{
        for(auto &[root,nodes]:groups){(void)root;Vec3 origin;auto d=description(old.object,nodes,next_id_++,state,origin);
            const Vec3 offset=state.orientation_world.rotate(origin-old.origin);
            d.state.center_of_mass_world_m+=offset;d.state.linear_velocity_m_s+=cross(state.angular_velocity_rad_s,offset);
            rigid_.addCompound(d);pending.push_back({unsigned(d.body_id),{old.object,nodes,origin}});after+=measureRigidMechanics(rigid_.mechanicalState(d.body_id),gravity_);
        }
    }catch(...){for(auto &[body,c]:pending){(void)c;rigid_.removeAndDestroy(body);}throw;}
    const double de=after.mechanicalEnergy()-before.mechanicalEnergy();
    max_transfer_energy_error_=std::max(max_transfer_energy_error_,std::abs(de));transfer_energy_change_+=de;
    max_transfer_mass_error_=std::max(max_transfer_mass_error_,std::abs(after.mass_kg-before.mass_kg));
    max_transfer_momentum_error_=std::max(max_transfer_momentum_error_,length(after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s));
    max_transfer_angular_error_=std::max(max_transfer_angular_error_,length(after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s));
    // No launch impulse, pose projection or omitted debris. Same occupied proxy
    // samples and inherited rigid velocity field before and after separation.
    rigid_.removeAndDestroy(id);components_.erase(id);for(auto &entry:pending)components_.insert(std::move(entry));++splits_;
}
void CompiledRuntime::step(double dt){
    std::map<unsigned,RigidSnapshot> previous;for(auto &[id,c]:components_){(void)c;previous.emplace(id,rigid_.snapshot(id));}
    const auto before=rigid_.mechanicalTotals(gravity_);rigid_.step(dt);time_+=dt;
    const double delta=energy()-before.mechanicalEnergy();rigid_energy_change_+=delta;
    auto impacts=rigid_.drainImpacts();contacts_+=unsigned(impacts.size());
    for(auto &e:impacts)if(e.closing_speed_m_s>.1&&observations_.size()<256)observations_.push_back(e);
    // Allocate only a same-step measured loss, after removing the analytical
    // semi-implicit free-fall energy error. It is an upper bound on dissipative
    // contact work, not an exact per-contact reaction measurement.
    double remaining=std::max(0.,-delta-.5*before.mass_kg*lengthSquared(gravity_)*dt*dt);
    std::sort(impacts.begin(),impacts.end(),[](const auto &a,const auto &b){
        if(a.available_normal_energy_j!=b.available_normal_energy_j)return a.available_normal_energy_j>b.available_normal_energy_j;
        if(a.body_a!=b.body_a)return a.body_a<b.body_a;if(a.body_b!=b.body_b)return a.body_b<b.body_b;
        if(a.contact_point_world_m.x!=b.contact_point_world_m.x)return a.contact_point_world_m.x<b.contact_point_world_m.x;
        if(a.contact_point_world_m.y!=b.contact_point_world_m.y)return a.contact_point_world_m.y<b.contact_point_world_m.y;return a.contact_point_world_m.z<b.contact_point_world_m.z;
    });
    std::set<unsigned> touched;unsigned accepted=0,active=0;
    for(auto &e:impacts){
        if(e.response_deferred_to_material||e.closing_speed_m_s<.1||e.estimated_normal_impulse_n_s<=0)continue;
        auto observedImpulse=[&](MatterBodyId id,Vec3 normal){auto it=previous.find(unsigned(id));if(it==previous.end()||id>100000000)return 0.;
            auto now=rigid_.mechanicalState(id);const auto &old=it->second;
            return std::max(0.,dot((now.motion.linear_velocity_m_s-old.linear_velocity_m_s-gravity_*dt)*now.mass_kg,normal));};
        // A speculative callback alone is insufficient. Require a measured
        // normal velocity response as well as the same-step loss allowance.
        const double observed=std::max(observedImpulse(e.body_a,-e.normal_a_to_b),observedImpulse(e.body_b,e.normal_a_to_b));
        const double pulseImpulse=std::min(e.estimated_normal_impulse_n_s,observed);
        if(pulseImpulse<1e-6)continue;
        double eventBudget=std::min(remaining,e.available_normal_energy_j*(1-e.combined_restitution*e.combined_restitution));
        if(eventBudget<=0)continue;
        // Deterministically share the event allowance between brittle targets.
        unsigned brittle=0;for(auto id:{e.body_a,e.body_b}){auto it=components_.find(unsigned(id));if(it!=components_.end()&&objects_[it->second.object].damage.object().material.model==MaterialModel::BrittleBond)++brittle;}
        if(!brittle)continue;const double share=eventBudget/brittle;
        for(auto id:{e.body_a,e.body_b}){
            auto it=components_.find(unsigned(id));if(it==components_.end())continue;auto &component=it->second;auto &object=objects_[component.object];
            if(object.damage.object().material.model!=MaterialModel::BrittleBond)continue;
            double minimumWork=std::numeric_limits<double>::infinity();
            const auto &compiled=object.damage.object();const auto &live=object.damage.liveLinks();
            for(unsigned i=0;i<live.size();++i)if(live[i]&&std::find(component.nodes.begin(),component.nodes.end(),compiled.links[i].a)!=component.nodes.end())minimumWork=std::min(minimumWork,compiled.links[i].work_j);
            if(std::min(remaining,share)<minimumWork)continue;
            if(active>=16||accepted>=64){++limited_;continue;}++active;
            auto s=rigid_.snapshot(id);const auto qi=inverse(s.orientation_world);
            const Vec3 point=component.origin+qi.rotate(e.contact_point_world_m-s.center_of_mass_world_m);
            const auto &samples=object.damage.object().samples;
            auto nearest=*std::min_element(component.nodes.begin(),component.nodes.end(),[&](auto a,auto b){return lengthSquared(samples[a].center_m-point)<lengthSquared(samples[b].center_m-point);});
            const Vec3 impulse=qi.rotate(e.normal_a_to_b*(pulseImpulse*(id==e.body_a?-1:1)));
            auto outcome=object.damage.impact(nearest,impulse,std::min(remaining,share),64-accepted);
            ++activations_;solves_+=outcome.solves;rebuilds_+=outcome.factor_builds;limited_+=outcome.budget_limited?1:0;
            work_+=outcome.work_j;allocated_loss_+=outcome.work_j;remaining-=outcome.work_j;
            for(auto &f:outcome.failures){++broken_;++accepted;events_.push_back({time_,object.id,unsigned(id),id==e.body_a?e.body_b:e.body_a,f.link,f.solve_index,f.work_j,f.predicted_stress_pa});}
            if(!outcome.failures.empty())touched.insert(unsigned(id));
        }
    }
    for(auto id:touched)split(id);
}
std::vector<PlatformInstance> CompiledRuntime::renderInstances() const{
    std::vector<PlatformInstance> result;
    for(auto &[id,c]:components_){const auto s=rigid_.snapshot(id);const auto &o=objects_[c.object];
        if(c.nodes.size()==o.damage.object().samples.size()){result.push_back({o.id,0,id,o.material,o.shape,s});continue;}
        for(auto n:c.nodes){const auto &node=o.damage.object().samples[n];auto state=s;const Vec3 offset=s.orientation_world.rotate(node.center_m-c.origin);
            state.center_of_mass_world_m+=offset;state.linear_velocity_m_s+=cross(s.angular_velocity_rad_s,offset);result.push_back({o.id,n,id,o.material,node.collision,state});}
    }return result;
}
unsigned CompiledRuntime::componentCount(unsigned object) const{
    unsigned count=0;for(auto &[id,c]:components_){(void)id;if(objects_[c.object].id==object)++count;}return count;
}
RigidSnapshot CompiledRuntime::state(unsigned object) const{
    if(componentCount(object)==1)for(auto &[id,c]:components_)if(objects_[c.object].id==object)return rigid_.snapshot(id);
    MechanicalTotals totals;for(auto &[id,c]:components_)if(objects_[c.object].id==object)totals+=measureRigidMechanics(rigid_.mechanicalState(id),gravity_);
    if(totals.mass_kg<=0)throw std::invalid_argument("unknown compiled object");
    RigidSnapshot s;s.center_of_mass_world_m=totals.centerOfMass();s.linear_velocity_m_s=totals.linear_momentum_kg_m_s/totals.mass_kg;return s;
}
std::vector<PlatformBondLine> CompiledRuntime::renderBonds() const{
    std::vector<PlatformBondLine> lines;
    for(auto &[id,c]:components_){const auto state=rigid_.snapshot(id);const auto &damage=objects_[c.object].damage;const auto &o=damage.object();
        std::set<unsigned> nodes(c.nodes.begin(),c.nodes.end());
        for(unsigned i=0;i<o.links.size();++i){const auto &b=o.links[i];if(!nodes.contains(b.a)||!nodes.contains(b.b))continue;
            lines.push_back({state.center_of_mass_world_m+state.orientation_world.rotate(o.samples[b.a].center_m-c.origin),
                state.center_of_mass_world_m+state.orientation_world.rotate(o.samples[b.b].center_m-c.origin),damage.liveLinks()[i]!=0});}
    }return lines;
}
std::string CompiledRuntime::reportJson() const{
    json r{{"model","compiled-impact-v1"},{"compiler_version",1},{"mechanical_energy_j",energy()},{"energy_residual_j",nullptr},{"fracture_work_j",work_},
        {"connected_components",components_.size()},{"local_solves",solves_},{"response_factor_rebuilds",rebuilds_},{"impact_activations",activations_},
        {"budget_limited_impacts",limited_},{"contact_observations",contacts_},{"representation_splits",splits_},
        {"rigid_step_energy_change_j",rigid_energy_change_},{"contact_loss_assigned_to_fracture_j",allocated_loss_},
        {"representation_energy_change_j",transfer_energy_change_},{"maximum_transfer_energy_error_j",max_transfer_energy_error_},
        {"maximum_transfer_mass_error_kg",max_transfer_mass_error_},{"maximum_transfer_momentum_error_kg_m_s",max_transfer_momentum_error_},
        {"maximum_transfer_angular_error_kg_m2_s",max_transfer_angular_error_},
        {"runtime_limits",{{"impact_activations_per_step",16},{"pulse_solves_per_activation",64},{"failures_per_impact",64},{"failures_per_step",64},{"fallback","leave excess damage unresolved; retain connectivity; report budget pressure"}}},
        {"limitations",{"Linearized 64-step impact pulse predictor; not AVBD or validated continuum fracture", "Fracture work reclassifies a bounded part of measured rigid contact losses; no independent full energy/reaction ledger", "Smooth intact spheres switch to a coarse 19-sample fragment collision skin; mass/inertia retained but surface geometry approximate; 27-cell boxes", "Oak/iron rigid response only; grain, plasticity and their failure unsupported", "Damage is persistent; package exports remain initial state, not live saves", "No cross-platform deterministic guarantee; no whole-scene trajectory reuse"}}};
    r["fragment_states"]=json::array();for(auto &[id,c]:components_){const auto s=rigid_.snapshot(id);const auto mechanics=rigid_.mechanicalState(id);
        r["fragment_states"].push_back({{"object_id",objects_[c.object].id},{"component_id",id},{"source_samples",c.nodes},{"mass_kg",mechanics.mass_kg},
            {"position_m",vec(s.center_of_mass_world_m)},{"orientation_wxyz",{s.orientation_world.w,s.orientation_world.x,s.orientation_world.y,s.orientation_world.z}},
            {"velocity_m_s",vec(s.linear_velocity_m_s)},{"spin_rad_s",vec(s.angular_velocity_rad_s)}});}
    r["object_state_semantics"]="Original objects retain aggregate COM/velocity after separation; their spin is null. Use fragment_states for individual poses and velocities.";
    r["contact_events"]=json::array();for(auto &e:observations_)r["contact_events"].push_back({{"tick",e.fixed_tick},{"body_a",e.body_a},{"body_b",e.body_b},{"point_m",vec(e.contact_point_world_m)},{"closing_speed_m_s",e.closing_speed_m_s},{"estimated_impulse_n_s",e.estimated_normal_impulse_n_s},{"available_normal_energy_j",e.available_normal_energy_j},{"restitution",e.combined_restitution}});
    r["fracture_events"]=json::array();for(auto &e:events_)r["fracture_events"].push_back({{"time_s",e.time},{"object_id",e.object},{"component_id",e.component},{"contact_other_body",e.other},{"link",e.link},{"local_solve",e.round},{"work_j",e.work},{"predicted_stress_pa",e.stress}});
    r["material_results"]=json::array();for(auto &o:objects_){const auto &compiled=o.damage.object();unsigned broken=0;for(auto v:o.damage.liveLinks())broken+=v?0:1;
        std::set<unsigned> groups;for(auto c:o.damage.components())groups.insert(c);
        r["material_results"].push_back({{"object_id",o.id},{"material",materialPresetName(o.material)},{"seed",compiled.seed},{"samples",compiled.samples.size()},
            {"compiled_links",compiled.links.size()},{"broken_links",broken},{"components",groups.size()},{"response_duration_s",compiled.response_duration_s},
            {"fracture_supported",compiled.material.model==MaterialModel::BrittleBond},{"position_m",vec(state(o.id).center_of_mass_world_m)}});
    }return r.dump();
}
}
