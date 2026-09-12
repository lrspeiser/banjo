// Pulleys and hoists.
//
// This is the IDEAL pulley: a relationship between cable lengths, not a wheel
// with a rope wrapped round it. What the engine holds is
//
//     |a - over_a|  +  ratio * |b - over_b|  <=  length
//
// and nothing else. There is no wheel, so no wheel inertia and no bearing
// friction; there is no wrap, so the rope cannot slip or come off. The physical
// alternative is in tests/rope_tests.cpp -- a run of bodies tied together and
// draped over something, which has real wrap and real friction and costs a body
// per segment. Both exist on purpose; this file is about the ideal one, and
// every test below is written so that it would fail if the constraint were
// quietly doing something else.
//
// What is pinned:
//
// 1. Pull one end down and the other comes up. The cable length is conserved.
// 2. A counterweight of the same mass balances: neither side moves.
// 3. Mechanical advantage is real, and it has a SIDE. The ratio applies to
//    the second end, so that end moves 1/ratio as far and feels ratio times the
//    tension: put the load there and half the weight holds it at a ratio of 2.
// 4. Too light a counterweight and the load wins; too heavy and it lifts.
// 5. The rope pulls and does not push: slack on one side is just slack.
// 6. Tension is reported and is about the load it carries.
// 7. Cutting the rope drops both ends.
// 8. A hoist lifts a portcullis in its grooves -- the whole point of one.

#include "fastlattice/LiveWorld.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace banjo;
using namespace banjo::fastlattice;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}

const LiveBodyPose &named(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    for (const LiveBodyPose &pose : poses)
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

LiveJoint jointNumber(const std::vector<LiveJoint> &joints, unsigned id) {
    for (const LiveJoint &joint : joints)
        if (joint.id == id) return joint;
    throw std::runtime_error("no joint with that id");
}

void tick(LiveWorld &world) {
    world.step(1.0 / 240.0);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

void run(LiveWorld &world, int steps) {
    for (int i = 0; i < steps; ++i) tick(world);
}

double heightOf(LiveWorld &world, const std::string &name) {
    return named(world.poses(), name).position_m.y;
}

// What a lump of iron of these dimensions weighs, in newtons. Everything below
// is sized against this rather than against round numbers: a counterweight only
// means something next to the load it is balancing.
constexpr double ironWeightN(Vec3 size_m) {
    return size_m.x * size_m.y * size_m.z * 7870.0 * 9.81;
}

// The weights, as BOXES rather than cubes.
//
// Every extent has to be a whole number of cells -- 50 mm here -- and mass goes
// as the cube of a side, so a cube of half the mass has a side of 0.1587 m,
// which is 3.17 cells and does not exist. Flattening one axis instead gives
// exact ratios in whole cells: 4x4x4 is 64 cells, 4x2x4 is 32, and 32 is
// exactly half of 64 however the engine rounds.
constexpr Vec3 kLoad{0.2, 0.2, 0.2};          // 64 cells,   618 N
constexpr Vec3 kHalf{0.2, 0.1, 0.2};          // 32 cells,   309 N
constexpr Vec3 kQuarter{0.1, 0.1, 0.2};       // 16 cells,   154 N
constexpr Vec3 kFourfold{0.4, 0.2, 0.4};      // 256 cells, 2471 N

// A gantry with two sheaves on it, a load under one and a counterweight under
// the other. Nothing is tied yet.
TileImpactRequest gantry(Vec3 load_m = kLoad, Vec3 weight_m = kLoad) {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody beam;
    beam.name = "beam";
    beam.shape = BodyShape::Box;
    beam.material = MaterialPreset::Oak;
    beam.dimensions_m = {3.0, 0.2, 0.2};
    beam.center_m = {0.0, 5.0, 0.0};
    beam.anchored = true;
    SceneBody load;
    load.name = "load";
    load.shape = BodyShape::Box;
    load.material = MaterialPreset::Iron;
    load.dimensions_m = load_m;
    load.center_m = {-1.0, 3.0, 0.0};
    SceneBody counter;
    counter.name = "counterweight";
    counter.shape = BodyShape::Box;
    counter.material = MaterialPreset::Iron;
    counter.dimensions_m = weight_m;
    counter.center_m = {1.0, 3.0, 0.0};
    r.bodies = {beam, load, counter};
    return r;
}

// The two sheaves, at each end of the beam's underside.
const Vec3 kOverLoad{-1.0, 4.9, 0.0};
const Vec3 kOverWeight{1.0, 4.9, 0.0};

unsigned reeve(LiveWorld &world, double ratio = 1.0) {
    const auto standing = world.poses();
    return world.reeve("load", "counterweight",
                       named(standing, "load").position_m,
                       named(standing, "counterweight").position_m,
                       kOverLoad, kOverWeight, ratio);
}

// The same rope the other way round, with the LOAD as the second end.
//
// The ratio multiplies the second run, so the second end is the one with the
// mechanical advantage. Reeving it with the load first and expecting half a
// counterweight to hold it measures the machine backwards -- and it did, once:
// a 618 N load against a 309 N counterweight at "a ratio of 2" fell 2.9 m,
// because in that arrangement the ratio asks for TWICE the weight, not half.
unsigned reeveWithLoadOnTheTackle(LiveWorld &world, double ratio) {
    const auto standing = world.poses();
    return world.reeve("counterweight", "load",
                       named(standing, "counterweight").position_m,
                       named(standing, "load").position_m,
                       kOverWeight, kOverLoad, ratio);
}

// -----------------------------------------------------------------------------

void pullOneEndDownAndTheOtherComesUp() {
    const auto world = LiveWorld::open(gantry());
    const unsigned rope = reeve(*world);
    require(rope != 0, "the rope would not reeve");
    const double load_was = heightOf(*world, "load");
    const double weight_was = heightOf(*world, "counterweight");
    const double rove_at = jointNumber(world->joints(), rope).at;

    // Haul the counterweight down by hand. The load has nowhere to go but up.
    require(world->grab("counterweight"), "could not take hold of the counterweight");
    for (int i = 1; i <= 80; ++i) {
        world->moveHeld(Vec3{1.0, weight_was - 0.01 * i, 0.0});
        tick(*world);
    }
    world->release();
    run(*world, 120);

    const double load_now = heightOf(*world, "load");
    const double weight_now = heightOf(*world, "counterweight");
    const LiveJoint rove = jointNumber(world->joints(), rope);
    std::cout << "  hauled the counterweight down " << (weight_was - weight_now)
              << " m: the load went up " << (load_now - load_was)
              << " m, and the rope is " << rove.at << " m of its " << rove.upper
              << "\n";
    require(weight_now < weight_was - 0.5, "the haul did not pull it down");
    require(load_now > load_was + 0.4, "the load did not come up");
    // The cable cannot get longer than it is. This is the whole constraint.
    require(rove.at <= rove.upper + 0.02,
            "the rope is longer than it is, so the length relationship is not held");
    require(std::abs(rove.upper - rove_at) < 0.01, "the rope changed length by itself");
    require(rove.kind == "pulley", "a pulley came back as the wrong kind of joint");
}

void anEqualCounterweightBalances() {
    const auto world = LiveWorld::open(gantry());
    const unsigned rope = reeve(*world);
    require(rope != 0, "the rope would not reeve");
    const double load_was = heightOf(*world, "load");
    run(*world, 960);
    const double moved = std::abs(heightOf(*world, "load") - load_was);
    std::cout << "  two equal weights on a 1:1 rope: after four seconds the load "
              << "has moved " << moved * 1000.0 << " mm\n";
    require(moved < 0.06, "equal weights did not balance");
}

void mechanicalAdvantageIsReal() {
    // A ratio of 2 is a block and tackle: the counterweight side of the rope
    // counts twice, so HALF the weight balances the load -- and the load moves
    // half as far as the counterweight does.
    //
    const auto world = LiveWorld::open(gantry(kLoad, kHalf));
    const unsigned rope = reeveWithLoadOnTheTackle(*world, 2.0);
    require(rope != 0, "the rope would not reeve");
    const double load_was = heightOf(*world, "load");
    run(*world, 960);
    const double load_moved = std::abs(heightOf(*world, "load") - load_was);
    std::cout << "  a " << ironWeightN(kLoad) << " N load against a "
              << ironWeightN(kHalf) << " N counterweight at a ratio of 2: "
              << "the load moved " << load_moved * 1000.0 << " mm\n";
    require(load_moved < 0.08,
            "half the weight did not balance the load at a ratio of two, so the "
            "mechanical advantage is not there");

    // And the other half of the claim: at that ratio the load moves half as far
    // as the counterweight. Haul the weight down and measure both.
    const double weight_was = heightOf(*world, "counterweight");
    const double load_then = heightOf(*world, "load");
    require(world->grab("counterweight"), "could not take hold of the counterweight");
    for (int i = 1; i <= 60; ++i) {
        world->moveHeld(Vec3{1.0, weight_was - 0.01 * i, 0.0});
        tick(*world);
    }
    world->release();
    run(*world, 60);
    const double weight_fell = weight_was - heightOf(*world, "counterweight");
    const double load_rose = heightOf(*world, "load") - load_then;
    std::cout << "    hauling it down " << weight_fell << " m raised the load "
              << load_rose << " m, a ratio of " << (weight_fell / load_rose) << "\n";
    require(load_rose > 0.05, "the load did not move at all");
    require(std::abs(weight_fell / load_rose - 2.0) < 0.35,
            "the load did not move half as far as the counterweight, so the "
            "ratio is not doing what a ratio does");
}

void tooLightACounterweightLosesAndTooHeavyOneLifts() {
    // A quarter of the load's weight, at 1:1. The load must win.
    {
        const auto world = LiveWorld::open(gantry(kLoad, kQuarter));
        require(reeve(*world) != 0, "the rope would not reeve");
        const double load_was = heightOf(*world, "load");
        const double weight_was = heightOf(*world, "counterweight");
        run(*world, 720);
        std::cout << "  a " << ironWeightN(kQuarter) << " N counterweight "
                  << "against a " << ironWeightN(kLoad) << " N load: the load fell "
                  << (load_was - heightOf(*world, "load")) << " m and the weight "
                  << "rose " << (heightOf(*world, "counterweight") - weight_was)
                  << " m\n";
        require(heightOf(*world, "load") < load_was - 0.3, "the load did not win");
        require(heightOf(*world, "counterweight") > weight_was + 0.3,
                "the load fell but did not pull the counterweight up, so the "
                "rope is not connecting them");
    }
    // Four times the load's weight. Now the load goes up.
    {
        const auto world = LiveWorld::open(gantry(kLoad, kFourfold));
        require(reeve(*world) != 0, "the rope would not reeve");
        const double load_was = heightOf(*world, "load");
        run(*world, 720);
        std::cout << "    and a " << ironWeightN(kFourfold) << " N one lifts it "
                  << (heightOf(*world, "load") - load_was) << " m\n";
        require(heightOf(*world, "load") > load_was + 0.3,
                "four times the weight did not lift the load");
    }
}

void theRopePullsAndDoesNotPush() {
    // Lift the load up under its own sheave. The rope goes slack, and a slack
    // rope must do nothing at all: the counterweight stays exactly where it is.
    // A rod bent round two corners would shove it, and a rope that could push
    // would drive it into the floor.
    //
    // The counterweight has to be RESTING ON SOMETHING for this to mean
    // anything. Hanging free, it simply falls to take up the slack -- which is
    // also correct, and is what the first version of this test measured: the
    // rope went from 3.8 m to 3.66 and the weight dropped 858 mm, which looks
    // like a failure and is a rope behaving perfectly.
    TileImpactRequest request = gantry();
    for (SceneBody &body : request.bodies)
        if (body.name == "counterweight") body.center_m = {1.0, 0.1, 0.0};
    const auto world = LiveWorld::open(request);
    const unsigned rope = reeve(*world);
    require(rope != 0, "the rope would not reeve");
    run(*world, 240);                        // let it settle on the floor
    const double taut = jointNumber(world->joints(), rope).upper;
    const double weight_was = heightOf(*world, "counterweight");

    require(world->grab("load"), "could not take hold of the load");
    for (int i = 1; i <= 150; ++i) {
        world->moveHeld(Vec3{-1.0, 3.0 + 0.01 * i, 0.0});
        tick(*world);
    }
    const double slack = jointNumber(world->joints(), rope).at;
    const double weight_now = heightOf(*world, "counterweight");
    world->release();
    std::cout << "  the load lifted to its sheave: the rope is " << slack
              << " m of its " << taut << ", and the counterweight on the floor "
              << "moved " << (weight_now - weight_was) * 1000.0 << " mm\n";
    require(slack < taut - 0.3, "the rope did not go slack when one end was lifted");
    require(std::abs(weight_now - weight_was) < 0.02,
            "lifting one end moved the other, so the slack rope is pushing");
}

void tensionIsReported() {
    const auto world = LiveWorld::open(gantry());
    const unsigned rope = reeve(*world);
    require(rope != 0, "the rope would not reeve");
    run(*world, 720);
    const double carrying = jointNumber(world->joints(), rope).tension_n;
    std::cout << "  two " << ironWeightN(kLoad) << " N weights balanced: the rope "
              << "reports " << carrying << " N\n";
    require(carrying > 0.3 * ironWeightN(kLoad),
            "a rope holding two 618 N weights up reports almost nothing");
}

void cuttingTheRopeDropsBothEnds() {
    const auto world = LiveWorld::open(gantry());
    const unsigned rope = reeve(*world);
    require(rope != 0, "the rope would not reeve");
    run(*world, 240);
    const double load_was = heightOf(*world, "load");
    const double weight_was = heightOf(*world, "counterweight");
    world->unhinge(rope);
    run(*world, 480);
    std::cout << "  cut: the load went from y=" << load_was << " to y="
              << heightOf(*world, "load") << " and the counterweight from y="
              << weight_was << " to y=" << heightOf(*world, "counterweight") << "\n";
    require(heightOf(*world, "load") < load_was - 1.0, "the load did not fall");
    require(heightOf(*world, "counterweight") < weight_was - 1.0,
            "the counterweight did not fall");
    require(world->joints().empty(), "the cut rope is still listed");
}

void aHoistLiftsAPortcullis() {
    // What all of this is for. A grate in its grooves, a rope from its top over
    // a sheave to a counterweight, and nobody touching either of them.
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody ground;
    ground.name = "ground";
    ground.shape = BodyShape::Box;
    ground.material = MaterialPreset::Concrete;
    ground.dimensions_m = {6.0, 0.1, 2.0};
    ground.center_m = {0.0, -0.05, 0.0};
    ground.anchored = true;
    SceneBody jamb;
    jamb.name = "jamb";
    jamb.shape = BodyShape::Box;
    jamb.material = MaterialPreset::Concrete;
    jamb.dimensions_m = {0.15, 4.0, 0.15};
    jamb.center_m = {-0.9, 2.0, 0.0};
    jamb.anchored = true;
    SceneBody grate;
    grate.name = "grate";
    grate.shape = BodyShape::Box;
    grate.material = MaterialPreset::Iron;
    grate.dimensions_m = {1.2, 1.0, 0.1};
    grate.center_m = {0.0, 0.5, 0.15};
    SceneBody counter;
    counter.name = "counterweight";
    counter.shape = BodyShape::Box;
    counter.material = MaterialPreset::Iron;
    // Heavier than the grate, so it hauls rather than merely balances.
    counter.dimensions_m = {0.65, 0.65, 0.65};
    counter.center_m = {2.0, 3.0, 0.0};
    r.bodies = {ground, jamb, grate, counter};

    const auto world = LiveWorld::open(r);
    const unsigned grooves = world->slide("jamb", "grate", Vec3{0.0, 0.5, 0.15},
                                          Vec3{0.0, 1.0, 0.0}, 0.0, 1.6, 0.0);
    require(grooves != 0, "the grate would not go into its grooves");
    const unsigned rope = world->reeve("grate", "counterweight",
                                       Vec3{0.0, 1.0, 0.15}, Vec3{2.0, 3.325, 0.0},
                                       Vec3{0.0, 3.9, 0.0}, Vec3{2.0, 3.9, 0.0});
    require(rope != 0, "the rope would not reeve");

    const double down = heightOf(*world, "grate");
    run(*world, 1440);
    const double up = heightOf(*world, "grate");
    const LiveJoint lifted = jointNumber(world->joints(), grooves);
    std::cout << "  a counterweight on a rope raised the portcullis from y=" << down
              << " to y=" << up << " (" << lifted.at << " m up its grooves), with "
              << "nobody touching it\n";
    require(up > down + 0.5, "the counterweight did not lift the portcullis");
    require(lifted.at > 0.5, "the grate moved but not along its grooves");
}

} // namespace

int main() {
    try {
        pullOneEndDownAndTheOtherComesUp();
        std::cout << "[PASS] pull one end down and the other comes up\n";
        anEqualCounterweightBalances();
        std::cout << "[PASS] an equal counterweight balances\n";
        mechanicalAdvantageIsReal();
        std::cout << "[PASS] mechanical advantage is real\n";
        tooLightACounterweightLosesAndTooHeavyOneLifts();
        std::cout << "[PASS] too light a counterweight loses, too heavy one lifts\n";
        theRopePullsAndDoesNotPush();
        std::cout << "[PASS] the rope pulls and does not push\n";
        tensionIsReported();
        std::cout << "[PASS] tension is reported\n";
        cuttingTheRopeDropsBothEnds();
        std::cout << "[PASS] cutting the rope drops both ends\n";
        aHoistLiftsAPortcullis();
        std::cout << "[PASS] a hoist lifts a portcullis\n";
        std::cout << "\nall pulley tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\n[FAIL] " << error.what() << "\n";
        return 1;
    }
}
