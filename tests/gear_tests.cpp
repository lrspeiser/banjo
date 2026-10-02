// Two wheels that turn together: gears in mesh, a chain between sprockets, and
// teeth that strip when too much is put through them.
//
// Jolt solves a gear as a relationship between the two HINGE constraints the
// wheels turn on, so what is tested here is the coupling, not a tooth touching
// a tooth. Nothing collides: a 12-tooth wheel and a 36-tooth wheel are two
// cylinders with a number each, and the number is what makes the big one turn a
// third as fast. That is worth being plain about, because it decides what can
// go wrong -- a gear here cannot ride up, jam, or lose a single tooth. It can
// only carry what it is given or strip, which is what the last check is for.

#include "material/MaterialCatalog.hpp"
#include "rigid/JoltWorld.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
using namespace banjo;

void require(bool ok, const std::string &what) {
    if (!ok) throw std::runtime_error(what);
}

constexpr double kDt = 1.0 / 120.0;

// A wheel on a pin: a disc that turns about z, on a post that does not move.
struct Wheel {
    MatterBodyId body{};
    unsigned pin{};
};

Wheel wheelAt(JoltWorld &world, MatterBodyId anchor_id, MatterBodyId wheel_id,
              double x, double radius_m) {
    // The post the wheel turns on: the building, so it does not move.
    RigidBoxDescription post{};
    post.body_id = anchor_id;
    post.dimensions_m = {0.1, 0.1, 0.1};
    post.material = makeReferenceMaterial(MaterialPreset::Iron, 17);
    post.state.center_of_mass_world_m = {x, 1.0, -0.2};
    post.fixed = true;
    world.addBox(post);

    // The wheel itself. A box rather than a disc: what makes it a gear is the
    // number of teeth on it, and nothing here ever touches a tooth. The
    // wheels are set well apart on purpose -- a coupling is the only thing
    // between them, and two wheels close enough to touch would collide and
    // lock each other, which is the scaffolding lying about the physics.
    RigidBoxDescription wheel{};
    wheel.body_id = wheel_id;
    wheel.dimensions_m = {2.0 * radius_m, 2.0 * radius_m, 0.04};
    wheel.material = makeReferenceMaterial(MaterialPreset::Iron, 17);
    wheel.state.center_of_mass_world_m = {x, 1.0, 0.0};
    world.addBox(wheel);

    JoltWorld::HingeDescription pin{};
    pin.a = anchor_id;
    pin.b = wheel_id;
    pin.point_world_m = {x, 1.0, 0.0};
    pin.axis_world = {0.0, 0.0, 1.0};
    const unsigned joint = world.addHinge(pin);
    return {wheel_id, joint};
}

double turnRate(const JoltWorld &world, MatterBodyId body) {
    return world.snapshot(body).angular_velocity_rad_s.z;
}

// A pair that is driven: the first wheel is turned by its pin's motor, and what
// the second does is the gear's doing.
void aGearPairTurnsAtItsRatio() {
    JoltWorld world;
    world.setGravity({0.0, 0.0, 0.0});
    const Wheel small = wheelAt(world, 1, 2, 0.0, 0.10);
    const Wheel large = wheelAt(world, 3, 4, 1.20, 0.25);

    JoltWorld::GearDescription gear;
    gear.a = small.body;
    gear.b = large.body;
    gear.pin_a = small.pin;
    gear.pin_b = large.pin;
    gear.teeth_a = 12;
    gear.teeth_b = 36;
    gear.strips_at_n_m = 0.0;          // strength is the last check's business
    const unsigned coupling = world.addGear(gear);

    world.driveHinge(small.pin, 6.0, 500.0);
    for (int tick = 0; tick < 240; ++tick) world.step(kDt);

    const double driver = turnRate(world, small.body);
    const double driven = turnRate(world, large.body);
    require(std::abs(driver) > 1.0,
            "the DRIVER never got going (" + std::to_string(driver)
                + "): the motor is not reaching it");
    // Three times the teeth, a third of the rate.
    const double ratio = driven / driver;
    require(std::abs(ratio + 1.0 / 3.0) < 0.05,
            "36 teeth on 12 should turn at a third, the other way; got " + std::to_string(ratio));
    // And opposite ways, which is what teeth in mesh do.
    require(driver * driven < 0.0, "gears in mesh turn opposite ways");
    require(world.gearTorque(coupling) > 0.0, "a coupling that is driving something carries something");
    std::cout << "  gears: 12 on 36, driver " << driver << " rad/s, driven " << driven
              << " rad/s, ratio " << ratio << "\n";
}

// The same pair with a chain round them instead of teeth in mesh.
void aChainTurnsBothTheSameWay() {
    JoltWorld world;
    world.setGravity({0.0, 0.0, 0.0});
    const Wheel small = wheelAt(world, 1, 2, 0.0, 0.10);
    const Wheel large = wheelAt(world, 3, 4, 1.20, 0.25);

    JoltWorld::GearDescription chain;
    chain.a = small.body;
    chain.b = large.body;
    chain.pin_a = small.pin;
    chain.pin_b = large.pin;
    chain.teeth_a = 12;
    chain.teeth_b = 36;
    chain.chain = true;
    (void)world.addGear(chain);

    world.driveHinge(small.pin, 6.0, 500.0);
    for (int tick = 0; tick < 240; ++tick) world.step(kDt);

    const double driver = turnRate(world, small.body);
    const double driven = turnRate(world, large.body);
    require(std::abs(driver) > 1.0, "the chain's driver never got going");
    require(driver * driven > 0.0,
            "a chain turns both sprockets the SAME way; got " + std::to_string(driver)
                + " and " + std::to_string(driven));
    const double ratio = driven / driver;
    require(std::abs(ratio - 1.0 / 3.0) < 0.05,
            "a chain onto three times the teeth still turns a third as fast; got "
                + std::to_string(ratio));
    std::cout << "  chain: same way, ratio " << ratio << "\n";
}

// Too much through the teeth, and they go.
void teethStripUnderTooMuch() {
    JoltWorld world;
    world.setGravity({0.0, 0.0, 0.0});
    const Wheel small = wheelAt(world, 1, 2, 0.0, 0.10);
    const Wheel large = wheelAt(world, 3, 4, 1.20, 0.25);

    JoltWorld::GearDescription gear;
    gear.a = small.body;
    gear.b = large.body;
    gear.pin_a = small.pin;
    gear.pin_b = large.pin;
    gear.teeth_a = 12;
    gear.teeth_b = 36;
    // A weak little wheel: it may carry two newton metres.
    gear.strips_at_n_m = 2.0;
    const unsigned coupling = world.addGear(gear);

    // Hold the big wheel still and drive the small one hard into it. Everything
    // the motor makes has to go through the teeth, because there is nowhere
    // else for it to go.
    world.setJointFriction(large.pin, 5000.0);
    world.driveHinge(small.pin, 20.0, 400.0);

    const auto initial_small=world.snapshot(small.body),initial_large=world.snapshot(large.body);
    const auto same=[](const RigidSnapshot &a,const RigidSnapshot &b) {
        require(length(a.center_of_mass_world_m-b.center_of_mass_world_m)==0&&
            length(a.linear_velocity_m_s-b.linear_velocity_m_s)==0&&length(a.angular_velocity_rad_s-b.angular_velocity_rad_s)==0&&
            a.orientation_world.w==b.orientation_world.w&&a.orientation_world.x==b.orientation_world.x&&
            a.orientation_world.y==b.orientation_world.y&&a.orientation_world.z==b.orientation_world.z,"gear trial replay changed motion");
    };
    RigidSnapshot expected_small,expected_large;unsigned expected_ticks=0;
    const auto strip_trial=[&] {
        expected_ticks=0;
        while (world.hasJoint(coupling)&&expected_ticks<600) {world.step(kDt);++expected_ticks;}
        require(!world.hasJoint(coupling)&&!world.strippedGears().empty(),"gear trial never stripped actual coupling");
        expected_small=world.snapshot(small.body);expected_large=world.snapshot(large.body);return false;
    };
    for (bool spring_trial:{false,true}) {
        require(!(spring_trial?world.runSpringTrial(strip_trial):world.runReversibleTrial(strip_trial)),"gear refusal accepted");
        require(world.hasJoint(coupling)&&world.strippedGears().empty()&&world.gearTorque(coupling)==0,
            "gear rollback lost coupling, strength metadata, prior strip receipt or timestep");
        same(initial_small,world.snapshot(small.body));same(initial_large,world.snapshot(large.body));
    }
    bool stripped = false;
    unsigned ticks=0;
    for (int tick = 0; tick < 600 && !stripped; ++tick) {
        world.step(kDt);
        ++ticks;
        for (const unsigned id : world.strippedGears()) stripped = stripped || id == coupling;
    }
    require(stripped, "the teeth carried 400 N m through a 2 N m gear and held");
    require(!world.hasJoint(coupling), "a gear that stripped is gone");
    require(ticks==expected_ticks,"gear retry changed strip time");
    same(expected_small,world.snapshot(small.body));same(expected_large,world.snapshot(large.body));
    // And with the teeth off, the driver runs away: nothing is holding it now.
    const double before = turnRate(world, small.body);
    for (int tick = 0; tick < 120; ++tick) world.step(kDt);
    require(std::abs(turnRate(world, small.body)) >= std::abs(before) - 1e-6,
            "with its teeth stripped the driver is not held back by anything");
    std::cout << "  strip: a 2 N m gear gave way under a 400 N m drive, and the drive ran on\n";
}

}  // namespace

int main() {
    try {
        aGearPairTurnsAtItsRatio();
        aChainTurnsBothTheSameWay();
        teethStripUnderTooMuch();
    } catch (const std::exception &error) {
        std::cerr << "gears: " << error.what() << "\n";
        return 1;
    }
    std::cout << "gears: a ratio, a chain's direction, and teeth that strip\n";
    return 0;
}
