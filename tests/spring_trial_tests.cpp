#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

using namespace banjo;

namespace {

void check(bool value,const char *message) {
    if(!value)throw std::runtime_error(message);
}

void same(const RigidSnapshot &a,const RigidSnapshot &b) {
    check(a.center_of_mass_world_m.x==b.center_of_mass_world_m.x&&
          a.center_of_mass_world_m.y==b.center_of_mass_world_m.y&&
          a.center_of_mass_world_m.z==b.center_of_mass_world_m.z&&
          a.orientation_world.w==b.orientation_world.w&&
          a.orientation_world.x==b.orientation_world.x&&
          a.orientation_world.y==b.orientation_world.y&&
          a.orientation_world.z==b.orientation_world.z&&
          a.linear_velocity_m_s.x==b.linear_velocity_m_s.x&&
          a.linear_velocity_m_s.y==b.linear_velocity_m_s.y&&
          a.linear_velocity_m_s.z==b.linear_velocity_m_s.z&&
          a.angular_velocity_rad_s.x==b.angular_velocity_rad_s.x&&
          a.angular_velocity_rad_s.y==b.angular_velocity_rad_s.y&&
          a.angular_velocity_rad_s.z==b.angular_velocity_rad_s.z,
          "spring trial body state replays exactly on this build");
}

void same(const ImpactEvent &a,const ImpactEvent &b) {
    check(a.fixed_tick==b.fixed_tick&&a.body_a==b.body_a&&a.body_b==b.body_b&&
          a.contact_point_world_m.x==b.contact_point_world_m.x&&
          a.contact_point_world_m.y==b.contact_point_world_m.y&&
          a.contact_point_world_m.z==b.contact_point_world_m.z&&
          a.normal_a_to_b.x==b.normal_a_to_b.x&&a.normal_a_to_b.y==b.normal_a_to_b.y&&
          a.normal_a_to_b.z==b.normal_a_to_b.z&&
          a.relative_velocity_b_minus_a_m_s.x==b.relative_velocity_b_minus_a_m_s.x&&
          a.relative_velocity_b_minus_a_m_s.y==b.relative_velocity_b_minus_a_m_s.y&&
          a.relative_velocity_b_minus_a_m_s.z==b.relative_velocity_b_minus_a_m_s.z&&
          a.closing_speed_m_s==b.closing_speed_m_s&&a.tangential_speed_m_s==b.tangential_speed_m_s&&
          a.estimated_normal_impulse_n_s==b.estimated_normal_impulse_n_s&&
          a.available_normal_energy_j==b.available_normal_energy_j&&
          a.combined_static_friction==b.combined_static_friction&&
          a.combined_dynamic_friction==b.combined_dynamic_friction&&
          a.applied_friction==b.applied_friction&&a.combined_restitution==b.combined_restitution&&
          a.effective_contact_modulus_pa==b.effective_contact_modulus_pa&&
          a.response_deferred_to_material==b.response_deferred_to_material,
          "spring trial contact event replays exactly on this build");
}

void same(const RigidContactDiagnostics &a,const RigidContactDiagnostics &b) {
    check(a.capacity.body_pairs==b.capacity.body_pairs&&a.capacity.constraints==b.capacity.constraints&&
          a.speculative_distance_m==b.speculative_distance_m&&
          a.temporary_arena_bytes==b.temporary_arena_bytes&&
          a.last_manifolds==b.last_manifolds&&a.peak_manifolds==b.peak_manifolds&&
          a.last_points==b.last_points&&a.peak_points==b.peak_points&&
          a.last_speculative_manifolds==b.last_speculative_manifolds&&
          a.peak_speculative_manifolds==b.peak_speculative_manifolds,
          "spring trial contact diagnostics replay exactly on this build");
}

struct Fixture {
    std::unique_ptr<JoltWorld> world;
    unsigned left_spring{};
    unsigned right_spring{};
};

Fixture makeFixture(MaterialPreset preset) {
    Fixture fixture{std::make_unique<JoltWorld>(0)};
    auto &world=*fixture.world;
    world.setContactSolverIterations(24,4);
    world.setGravity({0,-9.81,0});
    world.addFloor();
    auto material=makeReferenceMaterial(preset);
    RigidBallDescription ball;
    ball.radius_m=.05;ball.material=material;ball.mass_override_kg=.2;
    ball.linear_velocity_m_s={0,-.2,0};
    ball.body_id=1;ball.position_world_m={-.12,.049,0};world.addBall(ball);
    ball.body_id=2;ball.position_world_m={0,.049,0};ball.linear_velocity_m_s={};world.addBall(ball);
    ball.body_id=3;ball.position_world_m={.12,.049,0};ball.linear_velocity_m_s={0,-.2,0};world.addBall(ball);
    fixture.left_spring=world.addDistanceSpring(1,2,.1,250,2);
    world.pinToWorld(2);
    fixture.right_spring=world.addDistanceSpring(2,3,.1,250,2);
    return fixture;
}

void step(JoltWorld &world,unsigned count) {
    for(unsigned i=0;i<count;++i)world.step(1.0/240.0);
}

bool springExists(const JoltWorld &world,unsigned spring) {
    try {(void)world.distanceSpringImpulse(spring);return true;}
    catch(const std::out_of_range &) {return false;}
}

struct Chain {
    std::unique_ptr<JoltWorld> world;
    unsigned left{},right{};
};

Chain makeNeutralChain(unsigned iterations,double rest,double stiffness,double damping,
                       const std::vector<RigidSnapshot> *states=nullptr) {
    Chain chain{std::make_unique<JoltWorld>(0)};auto &world=*chain.world;
    world.setGravity({});world.setContactSolverIterations(iterations,4);
    auto neutral=makeReferenceMaterial(MaterialPreset::Iron);
    neutral.name="material-neutral spring transaction oracle";neutral.restitution=0;
    RigidBallDescription ball;ball.radius_m=.01;ball.material=neutral;ball.mass_override_kg=1;
    for(unsigned i=0;i<3;++i) {
        ball.body_id=i+1;ball.position_world_m={.1*i,0,0};
        if(states) {
            ball.position_world_m=states->at(i).center_of_mass_world_m;
            ball.linear_velocity_m_s=states->at(i).linear_velocity_m_s;
            ball.angular_velocity_rad_s=states->at(i).angular_velocity_rad_s;
        }
        world.addBall(ball);
        if(states)world.applyRigidState(i+1,states->at(i));
    }
    chain.left=world.addDistanceSpring(1,2,rest,stiffness,damping);
    chain.right=world.addDistanceSpring(2,3,rest,stiffness,damping);
    return chain;
}

struct UpdateOracleError {
    double position_m{},linear_velocity_m_s{},angular_velocity_rad_s{};
    double orientation_component{},impulse_n_s{};
};

UpdateOracleError significantUpdateOracle(unsigned iterations) {
    constexpr double dt=1.0/240.0;
    constexpr double old_rest=.08,old_stiffness=4000,old_damping=30;
    constexpr double new_rest=.13,new_stiffness=80,new_damping=.5;
    auto updated=makeNeutralChain(iterations,old_rest,old_stiffness,old_damping);
    updated.world->step(dt);
    std::vector<RigidSnapshot> restart;
    for(MatterBodyId id=1;id<=3;++id)restart.push_back(updated.world->snapshot(id));
    auto clean=makeNeutralChain(iterations,new_rest,new_stiffness,new_damping,&restart);
    updated.world->updateDistanceSpring(updated.left,new_rest,new_stiffness,new_damping);
    updated.world->updateDistanceSpring(updated.right,new_rest,new_stiffness,new_damping);
    updated.world->step(dt);clean.world->step(dt);
    UpdateOracleError error;
    for(MatterBodyId id=1;id<=3;++id) {
        const auto a=updated.world->snapshot(id),b=clean.world->snapshot(id);
        error.position_m=std::max(error.position_m,length(a.center_of_mass_world_m-b.center_of_mass_world_m));
        error.linear_velocity_m_s=std::max(error.linear_velocity_m_s,length(a.linear_velocity_m_s-b.linear_velocity_m_s));
        error.angular_velocity_rad_s=std::max(error.angular_velocity_rad_s,length(a.angular_velocity_rad_s-b.angular_velocity_rad_s));
        error.orientation_component=std::max({error.orientation_component,
            std::abs(a.orientation_world.w-b.orientation_world.w),std::abs(a.orientation_world.x-b.orientation_world.x),
            std::abs(a.orientation_world.y-b.orientation_world.y),std::abs(a.orientation_world.z-b.orientation_world.z)});
    }
    error.impulse_n_s=std::max(std::abs(updated.world->distanceSpringImpulse(updated.left)-
        clean.world->distanceSpringImpulse(clean.left)),std::abs(updated.world->distanceSpringImpulse(updated.right)-
        clean.world->distanceSpringImpulse(clean.right)));
    return error;
}

void identicalUpdatePreservesWarmStart() {
    constexpr double rest=.08,stiffness=4000,damping=30;
    auto chain=makeNeutralChain(2,rest,stiffness,damping);auto &world=*chain.world;
    world.step(1.0/240.0);
    std::vector<RigidSnapshot> expected;double left_impulse{},right_impulse{};
    check(!world.runSpringTrial([&] {
        world.step(1.0/240.0);
        for(MatterBodyId id=1;id<=3;++id)expected.push_back(world.snapshot(id));
        left_impulse=world.distanceSpringImpulse(chain.left);
        right_impulse=world.distanceSpringImpulse(chain.right);
        return false;
    }),"warm-start reference trial rolls back");
    world.updateDistanceSpring(chain.left,rest,stiffness,damping);
    world.updateDistanceSpring(chain.right,rest,stiffness,damping);
    world.step(1.0/240.0);
    for(MatterBodyId id=1;id<=3;++id)same(expected[id-1],world.snapshot(id));
    check(left_impulse==world.distanceSpringImpulse(chain.left)&&
          right_impulse==world.distanceSpringImpulse(chain.right),
          "identical spring update preserves cached warm start exactly");
}

void rejectedEditReplay(MaterialPreset preset) {
    auto fixture=makeFixture(preset);auto &world=*fixture.world;
    std::vector<RigidSnapshot> expected;
    std::vector<ImpactEvent> expected_events;
    RigidContactDiagnostics expected_diagnostics;
    double expected_left_impulse{},expected_right_impulse{};
    check(!world.runSpringTrial([&] {
        step(world,8);
        for(MatterBodyId id=1;id<=3;++id)expected.push_back(world.snapshot(id));
        expected_left_impulse=world.distanceSpringImpulse(fixture.left_spring);
        expected_right_impulse=world.distanceSpringImpulse(fixture.right_spring);
        expected_events=world.drainImpacts();
        expected_diagnostics=world.contactDiagnostics();
        return false;
    }),"reference spring trial rejects");

    check(!world.runSpringTrial([&] {
        world.updateDistanceSpring(fixture.left_spring,.075,700,5);
        world.removeDistanceSpring(fixture.right_spring);
        step(world,5);
        return false;
    }),"updated and removed springs reject transactionally");
    check(springExists(world,fixture.left_spring)&&springExists(world,fixture.right_spring),
        "rejected trial restores both spring map entries");

    step(world,8);
    for(MatterBodyId id=1;id<=3;++id)same(expected[id-1],world.snapshot(id));
    check(expected_left_impulse==world.distanceSpringImpulse(fixture.left_spring)&&
          expected_right_impulse==world.distanceSpringImpulse(fixture.right_spring),
          "rejected edits restore spring settings and runtime impulses");
    const auto actual_events=world.drainImpacts();
    check(!expected_events.empty()&&actual_events.size()==expected_events.size(),
        "contact replay is nonempty and has the same event count");
    for(std::size_t i=0;i<expected_events.size();++i)same(expected_events[i],actual_events[i]);
    same(expected_diagnostics,world.contactDiagnostics());
}

void nestingExceptionsAndGuards() {
    auto fixture=makeFixture(MaterialPreset::Iron);auto &world=*fixture.world;
    const auto initial1=world.snapshot(1),initial2=world.snapshot(2),initial3=world.snapshot(3);
    check(!world.runSpringTrial([&] {
        world.updateDistanceSpring(fixture.left_spring,.08,500,3);
        check(world.runSpringTrial([&] {
            world.removeDistanceSpring(fixture.right_spring);
            step(world,2);
            return true;
        }),"inner accepted spring trial");
        return false;
    }),"outer spring trial rejects after inner acceptance");
    same(initial1,world.snapshot(1));same(initial2,world.snapshot(2));same(initial3,world.snapshot(3));
    check(springExists(world,fixture.left_spring)&&springExists(world,fixture.right_spring),
        "outer rejection restores springs removed by accepted inner trial");

    bool callback_exception=false;
    try {
        (void)world.runSpringTrial([&]() -> bool {
            world.updateDistanceSpring(fixture.left_spring,.07,800,6);
            world.removeDistanceSpring(fixture.right_spring);
            step(world,2);
            throw std::runtime_error("intentional spring trial exception");
        });
    } catch(const std::runtime_error &) {callback_exception=true;}
    check(callback_exception&&springExists(world,fixture.left_spring)&&springExists(world,fixture.right_spring),
        "exception restores spring topology and configuration");
    same(initial1,world.snapshot(1));same(initial2,world.snapshot(2));same(initial3,world.snapshot(3));

    check(world.runSpringTrial([&] {
        bool add_rejected=false,gravity_rejected=false,pin_rejected=false,body_rejected=false;
        bool geometry_rejected=false,contact_rejected=false,solver_rejected=false;
        try {(void)world.addDistanceSpring(1,3,.2,100,1);}catch(const std::logic_error &){add_rejected=true;}
        try {world.setGravity({});}catch(const std::logic_error &){gravity_rejected=true;}
        try {world.pinToWorld(1);}catch(const std::logic_error &){pin_rejected=true;}
        try {world.removeAndDestroy(1);}catch(const std::logic_error &){body_rejected=true;}
        try {world.addFloor();}catch(const std::logic_error &){geometry_rejected=true;}
        try {world.setImpactObservationsEnabled(false);}catch(const std::logic_error &){contact_rejected=true;}
        try {world.setContactSolverIterations(12,2);}catch(const std::logic_error &){solver_rejected=true;}
        check(add_rejected&&gravity_rejected&&pin_rejected&&body_rejected&&geometry_rejected&&
              contact_rejected&&solver_rejected,
            "spring trial forbids new springs and non-spring configuration/topology changes");
        bool reversible_edit_rejected=false;
        try {
            (void)world.runReversibleTrial([&] {
                world.updateDistanceSpring(fixture.left_spring,.09,300,1);
                return true;
            });
        } catch(const std::logic_error &) {reversible_edit_rejected=true;}
        check(reversible_edit_rejected,
            "ordinary reversible trial nested in spring trial still forbids spring mutation");
        return true;
    }),"guard checks leave spring trial usable");

    bool spring_inside_reversible_rejected=false;
    try {
        (void)world.runReversibleTrial([&] {
            return world.runSpringTrial([] {return true;});
        });
    } catch(const std::invalid_argument &) {spring_inside_reversible_rejected=true;}
    check(spring_inside_reversible_rejected,
        "spring trial cannot bypass an enclosing reversible trial contract");

    step(world,1);
    std::vector<ImpactEvent> drained_in_trial;
    check(!world.runSpringTrial([&] {
        drained_in_trial=world.drainImpacts();
        world.updateDistanceSpring(fixture.left_spring,.08,450,2);
        step(world,1);
        return false;
    }),"event-draining spring trial rejects");
    const auto restored_events=world.drainImpacts();
    check(!drained_in_trial.empty()&&restored_events.size()==drained_in_trial.size(),
        "spring trial restores its pre-existing event queue");
    for(std::size_t i=0;i<drained_in_trial.size();++i)same(drained_in_trial[i],restored_events[i]);

    bool depth_rejected=false;
    std::function<bool()> recurse;
    recurse=[&] {return world.runSpringTrial(recurse);};
    try {(void)world.runSpringTrial(recurse);}
    catch(const std::invalid_argument &) {depth_rejected=true;}
    check(depth_rejected&&world.runSpringTrial([] {return true;}),
        "spring trial depth budget unwinds and leaves later trials usable");
}

void acceptedEdits() {
    auto fixture=makeFixture(MaterialPreset::Iron);auto &world=*fixture.world;
    double old_impulse{};
    check(!world.runSpringTrial([&] {step(world,1);old_impulse=world.distanceSpringImpulse(fixture.left_spring);return false;}),
        "original spring impulse sample rolls back");
    check(world.runSpringTrial([&] {
        world.updateDistanceSpring(fixture.left_spring,.06,900,4);
        return true;
    }),"spring update accepts");
    step(world,1);
    const double new_impulse=world.distanceSpringImpulse(fixture.left_spring);
    check(std::isfinite(new_impulse)&&new_impulse!=old_impulse,"accepted spring settings affect the next solve");
    check(world.runSpringTrial([&] {world.removeDistanceSpring(fixture.right_spring);return true;}),
        "spring removal accepts");
    check(!springExists(world,fixture.right_spring),"accepted spring removal persists");
    step(world,1);
}

} // namespace

int main() {
    try {
        for(const MaterialPreset preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
            rejectedEditReplay(preset);
            std::cout<<materialPresetName(preset)<<" spring_trial_replay=exact\n";
        }
        nestingExceptionsAndGuards();
        acceptedEdits();
        identicalUpdatePreservesWarmStart();
        const auto low_iteration_error=significantUpdateOracle(2);
        const auto high_iteration_error=significantUpdateOracle(24);
        const auto bounded=[](const UpdateOracleError &e){return e.position_m<2e-7&&e.linear_velocity_m_s<2e-7&&
            e.angular_velocity_rad_s<2e-7&&e.orientation_component<2e-7&&e.impulse_n_s<2e-7;};
        check(bounded(low_iteration_error)&&bounded(high_iteration_error),
            "significant spring update matches a clean zero-warm-start reconstruction");
        check(high_iteration_error.position_m<=low_iteration_error.position_m+1e-9&&
              high_iteration_error.linear_velocity_m_s<=low_iteration_error.linear_velocity_m_s+1e-9&&
              high_iteration_error.angular_velocity_rad_s<=low_iteration_error.angular_velocity_rad_s+1e-9&&
              high_iteration_error.orientation_component<=low_iteration_error.orientation_component+1e-9&&
              high_iteration_error.impulse_n_s<=low_iteration_error.impulse_n_s+1e-9,
            "higher iteration update oracle is no less consistent than low iteration oracle");
        std::cout<<"spring_update_low_velocity_error_m_s="<<low_iteration_error.linear_velocity_m_s
                 <<" high_velocity_error_m_s="<<high_iteration_error.linear_velocity_m_s
                 <<" low_impulse_error_n_s="<<low_iteration_error.impulse_n_s
                 <<" high_impulse_error_n_s="<<high_iteration_error.impulse_n_s<<'\n';
        std::cout<<"[PASS] bounded spring edit transactions and exact rollback replay\n";
    } catch(const std::exception &error) {
        std::cerr<<"[FAIL] "<<error.what()<<'\n';
        return 1;
    }
}
