#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace banjo;
void check(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
void same(const RigidSnapshot &a,const RigidSnapshot &b){
    check(length(a.center_of_mass_world_m-b.center_of_mass_world_m)==0&&length(a.linear_velocity_m_s-b.linear_velocity_m_s)==0&&length(a.angular_velocity_rad_s-b.angular_velocity_rad_s)==0&&
        a.orientation_world.w==b.orientation_world.w&&a.orientation_world.x==b.orientation_world.x&&a.orientation_world.y==b.orientation_world.y&&a.orientation_world.z==b.orientation_world.z,"trial motion replays exactly on this build");
}
void ropeConfigurationAndTimestepRestore() {
    for (auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        JoltWorld world;const auto material=makeReferenceMaterial(preset);
        world.addBox({1,{.08,.08,.08},material,{{0,1,0},{},{},{}},true});
        world.addBox({2,{.08,.08,.08},material,{{0,.5,0},{},{},{}},false});
        const auto rope=world.addLink({1,2,{0,1,0},{0,.5,0},.5,0});
        for (unsigned k=0;k<40;++k) world.step(1.0/240);
        const auto initial=world.snapshot(2);const auto configuration=world.jointState(rope);
        const double tension=world.jointTension(rope);
        check(tension>0&&configuration.lower==configuration.upper,"rope rollback fixture must start taut and loaded");
        for (double duration:{0.0,-1.0,1e-300,std::numeric_limits<double>::infinity(),std::numeric_limits<double>::quiet_NaN()}) {
            bool refused=false;try {world.step(duration);}catch (const std::invalid_argument &) {refused=true;}
            check(refused&&world.jointTension(rope)==tension,"invalid native duration changed metadata");same(initial,world.snapshot(2));
        }
        RigidSnapshot expected;
        const auto slack=[&] {
            auto lifted=initial;lifted.center_of_mass_world_m.y+=.1;lifted.linear_velocity_m_s={};
            world.applyRigidState(2,lifted);world.step(.01);expected=world.snapshot(2);
            check(world.jointState(rope).lower==0,"tentative step must switch the rope to slack");return false;
        };
        for (bool spring_trial:{false,true}) {
            check(!(spring_trial?world.runSpringTrial(slack):world.runReversibleTrial(slack)),"slack trial refused");
            same(initial,world.snapshot(2));
            check(world.jointState(rope).lower==configuration.lower&&world.jointState(rope).upper==configuration.upper&&
                world.jointTension(rope)==tension,"rope rollback lost taut configuration, cached load or last timestep");
        }
        const auto wanted=expected;(void)slack();same(wanted,world.snapshot(2));
        std::cout<<materialPresetName(preset)<<" rope configuration/timestep restore=exact tension="<<tension<<" N\n";
    }
}
int main(){try{
    ropeConfigurationAndTimestepRestore();
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto material=makeReferenceMaterial(preset);JoltWorld world;world.setGravity({0,-9.81,0});
        world.addBox({1,{.1,.1,.1},material,{{0,.12,0},{},{0,-1,0},{0,0,.2}},false});
        world.addBox({2,{1,.1,1},material,{{0,0,0},{},{},{}},true});
        bool configuration_rejected=false;try{world.setBodyPairContactCacheEnabled(false);}catch(const std::logic_error&){configuration_rejected=true;}
        check(configuration_rejected,"cache setting cannot alter an existing scene");
        configuration_rejected=false;try{world.setContactSolverIterations(80,8);}catch(const std::logic_error&){configuration_rejected=true;}
        check(configuration_rejected,"iteration setting cannot alter an existing scene");
        const auto initial=world.snapshot(1);std::vector<ImpactEvent> events;RigidSnapshot candidate;
        const auto advance=[&]{for(unsigned k=0;k<40;++k)world.step(1.0/240);candidate=world.snapshot(1);events=world.drainImpacts();};
        check(!world.runReversibleTrial([&]{advance();return false;}),"rejected trial returns false");same(initial,world.snapshot(1));
        check(world.drainImpacts().empty(),"rejected trial emits no leaked contacts");const auto expected=candidate;const auto expected_events=events;
        check(expected.center_of_mass_world_m.y>.098&&expected.linear_velocity_m_s.y>-1.1,"fixture has actual support/rebound response rather than ballistic free fall");
        check(!expected_events.empty(),"trial includes a real contact callback");
        check(world.runReversibleTrial([&]{advance();return true;}),"accepted trial returns true");same(expected,world.snapshot(1));
        check(events.size()==expected_events.size(),"event replay count");
        for(std::size_t k=0;k<events.size();++k)check(events[k].fixed_tick==expected_events[k].fixed_tick&&events[k].body_a==expected_events[k].body_a&&events[k].body_b==expected_events[k].body_b&&
            length(events[k].contact_point_world_m-expected_events[k].contact_point_world_m)==0&&events[k].estimated_normal_impulse_n_s==expected_events[k].estimated_normal_impulse_n_s,"event tick and contact data replay");
        // Prepare a resting contact explicitly; the first fixture may rebound.
        auto settled=world.snapshot(1);settled.center_of_mass_world_m={0,.1,0};settled.orientation_world={};settled.linear_velocity_m_s={};settled.angular_velocity_rad_s={};world.applyRigidState(1,settled);
        for(unsigned k=0;k<4;++k)world.step(1.0/240);
        const auto resting=world.snapshot(1);
        check(!world.runReversibleTrial([&]{for(unsigned k=0;k<20;++k)world.step(1.0/120);candidate=world.snapshot(1);return false;}),"cached-contact trial rejects");
        same(resting,world.snapshot(1));for(unsigned k=0;k<20;++k)world.step(1.0/120);same(candidate,world.snapshot(1));
        const auto before_throw=world.snapshot(1);bool threw=false;
        try{(void)world.runReversibleTrial([&]()->bool{world.step(.001);world.removeAndDestroy(1);return true;});}catch(const std::logic_error &){threw=true;}
        check(threw&&world.contains(1),"topology mutation rejects before deletion");same(before_throw,world.snapshot(1));
        check(!world.runReversibleTrial([&]{check(world.runReversibleTrial([&]{world.step(.002);return true;}),"nested acceptance");return false;}),"outer rejection");same(before_throw,world.snapshot(1));
        // A new contact guarantees a nonempty event queue before the trial.
        world.addBox({3,{.1,.1,.1},material,{{.3,.1,0},{},{},{}},false});
        // Queued events that predate a trial must survive a drain inside it.
        auto moved=world.snapshot(1);moved.center_of_mass_world_m={0,.12,0};moved.linear_velocity_m_s={0,-1,0};world.applyRigidState(1,moved);
        for(unsigned k=0;k<40;++k)world.step(1.0/240);
        std::vector<ImpactEvent> pending;
        check(!world.runReversibleTrial([&]{pending=world.drainImpacts();world.step(.001);return false;}),"event-drain trial rejects");
        const auto restored=world.drainImpacts();check(!pending.empty(),"pending event fixture is nonempty");check(restored.size()==pending.size(),"prior event queue restored");
        for(std::size_t k=0;k<pending.size();++k)check(restored[k].fixed_tick==pending[k].fixed_tick,"prior event timestamps preserved");
        world.pinToWorld(1);const auto pinned=world.snapshot(1);
        check(!world.runReversibleTrial([&]{for(unsigned k=0;k<20;++k)world.step(.001);candidate=world.snapshot(1);return false;}),"constraint-state trial rejects");
        same(pinned,world.snapshot(1));for(unsigned k=0;k<20;++k)world.step(.001);same(candidate,world.snapshot(1));world.releaseFromWorld(1);
        bool depth_rejected=false;std::function<bool()> recurse;
        recurse=[&]{return world.runReversibleTrial(recurse);};
        try{(void)world.runReversibleTrial(recurse);}catch(const std::invalid_argument&){depth_rejected=true;}
        check(depth_rejected&&world.runReversibleTrial([]{return true;}),"depth budget unwinds and leaves future trials usable");
        std::cout<<materialPresetName(preset)<<" replay_contacts="<<expected_events.size()<<" first_tick="<<expected_events.front().fixed_tick<<" cached_contact_replay=exact\n";
    }
    std::cout<<"[PASS] reversible contact trials, exceptions, nested state and event queues\n";
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
