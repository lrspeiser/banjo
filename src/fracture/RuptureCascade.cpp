#include "fracture/RuptureCascade.hpp"
#include "fracture/ConnectedComponents.hpp"
#include <algorithm>
#include <cmath>
#include <functional>
#include <stdexcept>
#include <string_view>
namespace banjo {
RuptureCascadeResult tryRuptureCascade(ActiveMatter &matter,CoupledSphereState &sphere,double duration,
    std::span<const RuptureInterface> laws,const RuptureCascadeSettings &settings,Vec3 gravity){
    if(!std::isfinite(duration)||duration<=0||duration>1||!std::isfinite(settings.maximum_step_s)||settings.maximum_step_s<=0||
       !std::isfinite(settings.minimum_step_s)||settings.minimum_step_s<=0||settings.minimum_step_s>settings.maximum_step_s||
       !std::isfinite(settings.wave_step_fraction)||settings.wave_step_fraction<1e-4||settings.wave_step_fraction>.25||
       !std::isfinite(settings.maximum_event_overshoot_j)||settings.maximum_event_overshoot_j<0||
       settings.maximum_evaluations<1||settings.maximum_evaluations>65536||settings.maximum_refinement_depth>40)
        throw std::invalid_argument("invalid bounded rupture cascade settings");
    if(!std::isfinite(settings.capture_interval_s)||settings.capture_interval_s<0||settings.maximum_capture_frames<2||settings.maximum_capture_frames>4096||
       (settings.capture_interval_s>0&&matter.nodes.size()>128))throw std::invalid_argument("invalid bounded cascade capture settings");
    // Validate the physical state/laws without changing the caller. Resolve no
    // initial failures implicitly: their event time/energy belongs to the caller.
    auto candidate=matter;auto candidate_sphere=sphere;
    const auto initial=tryEnergyRupture(candidate,laws,settings.maximum_event_overshoot_j);
    if(!initial.broken_bonds.empty())throw std::invalid_argument("resolve initial failure before advancing a cascade");
    if(!std::isfinite(sphere.mass_kg)||sphere.mass_kg<=0||!std::isfinite(settings.contact.normal.stiffness_n_m)||settings.contact.normal.stiffness_n_m<=0)
        throw std::invalid_argument("cascade requires positive finite contact stiffness and sphere mass");
    std::vector<double> stiffness(matter.nodes.size(),2*settings.contact.normal.stiffness_n_m);
    for(std::size_t i=0;i<matter.bonds.size();++i)if(matter.bonds[i].alive){const auto &b=matter.asset->bonds[i];stiffness[b.node_a]+=2/b.compliance;stiffness[b.node_b]+=2/b.compliance;}
    double max_frequency_squared=2*settings.contact.normal.stiffness_n_m*matter.nodes.size()/sphere.mass_kg;
    for(std::size_t i=0;i<matter.nodes.size();++i)max_frequency_squared=std::max(max_frequency_squared,stiffness[i]/matter.nodes[i].mass_kg);
    RuptureCascadeResult result;result.stiffness_step_limit_s=settings.wave_step_fraction/std::sqrt(max_frequency_squared);
    const double maximum_step=std::min(settings.maximum_step_s,result.stiffness_step_limit_s);
    if(!std::isfinite(maximum_step)||maximum_step<settings.minimum_step_s){result.failure="stiffness step below minimum";return result;}
    const auto capture=[&]{
        if(settings.capture_interval_s==0)return true;
        if(result.frames.size()>=settings.maximum_capture_frames)return false;
        RuptureCascadeFrame frame;frame.time_s=result.advanced_time_s;frame.impactor_position=candidate_sphere.motion.center_of_mass_world_m;
        for(const auto &node:candidate.nodes)frame.positions.push_back(node.position_world_m);
        for(const auto &bond:candidate.bonds)frame.live_bonds.push_back(bond.alive);
        result.frames.push_back(std::move(frame));return true;
    };
    (void)capture();double next_capture=settings.capture_interval_s;
    const auto fail=[&](const char *why){result.failure=why;return false;};
    std::function<bool(double,unsigned)> advance=[&](double dt,unsigned depth){
        if(result.evaluations>=settings.maximum_evaluations)return fail("evaluation budget");
        ++result.evaluations;
        const double remaining=std::max(0.0,settings.maximum_event_overshoot_j-result.event_overshoot_loss_j);
        const auto trial=tryCompliantRuptureStep(candidate,candidate_sphere,dt,laws,remaining,settings.contact,gravity);
        if(!trial.accepted){
            ++result.rejected_trials;
            if(depth>=settings.maximum_refinement_depth||dt/2<settings.minimum_step_s)return fail("event/contact refinement floor");
            return advance(dt/2,depth+1)&&advance(dt/2,depth+1);
        }
        if(result.accepted_steps==0)result.initial_contact_energy_j=trial.contact.contact_energy_before_j;
        ++result.accepted_steps;result.advanced_time_s+=dt;
        result.fracture_work_j+=trial.rupture.fracture_work_j;result.event_overshoot_loss_j+=trial.rupture.event_overshoot_loss_j;
        result.contact_damping_loss_j+=trial.contact.contact_damping_loss_j;result.final_contact_energy_j=trial.contact.contact_energy_after_j;
        if(!trial.rupture.broken_bonds.empty()){
            RuptureCascadeEvent event;event.time_s=result.advanced_time_s;event.broken_bonds=trial.rupture.broken_bonds;
            event.fracture_work_j=trial.rupture.fracture_work_j;event.event_overshoot_loss_j=trial.rupture.event_overshoot_loss_j;
            for(const auto &component:findConnectedComponents(candidate))event.component_node_counts.push_back(static_cast<unsigned>(component.node_indices.size()));
            result.events.push_back(std::move(event));
        }
        if(settings.capture_interval_s>0&&(result.advanced_time_s>=next_capture||!trial.rupture.broken_bonds.empty()||result.advanced_time_s>=duration)){
            if(!capture())return fail("capture frame budget");
            next_capture=result.advanced_time_s+settings.capture_interval_s;
        }
        return true;
    };
    while(result.advanced_time_s<duration){
        const double remaining=duration-result.advanced_time_s;
        if(result.advanced_time_s+std::min(remaining,maximum_step)==result.advanced_time_s||!advance(std::min(remaining,maximum_step),0)){
            if(result.failure==std::string_view("none"))result.failure="time not representable";
            // Failed intervals publish no candidate events, work or elapsed time.
            result.discarded_events=static_cast<unsigned>(result.events.size());result.accepted_steps=0;result.advanced_time_s=0;result.events.clear();result.frames.clear();result.fracture_work_j=0;result.event_overshoot_loss_j=0;
            result.contact_damping_loss_j=0;result.initial_contact_energy_j=0;result.final_contact_energy_j=0;return result;
        }
    }
    matter=std::move(candidate);sphere=candidate_sphere;result.accepted=true;return result;
}
}
