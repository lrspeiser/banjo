#pragma once
#include "fracture/EnergyRupture.hpp"
namespace banjo {
struct RuptureCascadeSettings {
    CompliantStepSettings contact;
    double maximum_step_s{1e-5};
    double minimum_step_s{1e-12};
    // Additional characteristic stiffness/mass step cap. This is an accuracy
    // control for wave propagation, not a proof of event/trajectory convergence.
    double wave_step_fraction{.1};
    double maximum_event_overshoot_j{}; // one budget for the ENTIRE advance
    unsigned maximum_evaluations{65536};
    unsigned maximum_refinement_depth{30};
};
struct RuptureCascadeEvent {
    double time_s{}; // relative to this advance
    std::vector<std::uint32_t> broken_bonds;
    std::vector<unsigned> component_node_counts;
    double fracture_work_j{},event_overshoot_loss_j{};
};
struct RuptureCascadeResult {
    bool accepted{};
    unsigned evaluations{},rejected_trials{},accepted_steps{},discarded_events{};
    double advanced_time_s{},stiffness_step_limit_s{};
    double fracture_work_j{},event_overshoot_loss_j{},contact_damping_loss_j{};
    double final_contact_energy_j{},initial_contact_energy_j{};
    std::vector<RuptureCascadeEvent> events;
    const char *failure{"none"};
};
// Local forces evolve the entire surviving connector network. Breaks remove
// ONLY their own edges; detached components retain nodes, motion and live edges
// and can sustain later waves/failure. No recursive 'break all neighbors'.
// A failed trial recursively subdivides time, then advances the remaining
// interval with the newly accepted topology. The full call is transactional.
// One finite sphere; no component/component contact or bowl handoff yet.
RuptureCascadeResult tryRuptureCascade(ActiveMatter &matter,CoupledSphereState &sphere,double duration_s,
    std::span<const RuptureInterface> interfaces,const RuptureCascadeSettings &settings,Vec3 gravity_m_s2={});
}
