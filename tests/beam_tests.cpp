// Supports, beams and levers.
//
// Most of this is the rigid solver doing its job and needs no new machinery:
// mass distribution, gravity, contact, torque balance and load transfer are
// what a solver IS. A plank on two piers already responds to where you put the
// load, and a seesaw is a plank on a pin. The tests for those are here anyway,
// because "it already works" is a claim and claims get measured.
//
// What genuinely was not here is the one the goal names: sustained-load
// failure, without substituting impact-only breaking. Every other break in this
// engine starts from a blow -- a closing speed, an impedance, an energy. A shelf
// with too much stacked on it is struck by nothing at all: measured, a plank
// bridging two piers with an iron block on it reports NO contacts whatsoever
// once it has settled, because the contact ledger is a ledger of impacts. Load
// it until it should snap and nothing would ever ask.
//
// So the load survey asks separately, from statics: what is resting on it, how
// far apart its supports are, and what bending that puts in it. Like every
// other bound here it is necessary and not sufficient -- it says the lattice is
// worth running.
//
// What is pinned:
//
// 1. A plank holds what it can hold, and is not reported.
// 2. Pile on enough and it IS reported -- with no impact anywhere.
// 3. The span matters: the same plank held all along its length is fine.
// 4. What is reported can then actually be broken.
// 5. Load transfers through a stack: a crate on a crate on a shelf.
// 6. A seesaw responds to where the load is placed, not just how much.
// 7. A balance tips towards the heavier side and levels when matched.
// 8. Something in your hand is not weighing on anything.

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

void tick(LiveWorld &world) {
    world.step(1.0 / 240.0);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

void run(LiveWorld &world, int steps) {
    for (int i = 0; i < steps; ++i) tick(world);
}

bool sagging(LiveWorld &world, const std::string &name) {
    for (const LiveOverload &load : world.overloaded())
        if (load.name == name) return true;
    return false;
}

LiveOverload loadOn(LiveWorld &world, const std::string &name) {
    for (const LiveOverload &load : world.overloaded())
        if (load.name == name) return load;
    throw std::runtime_error(name + " is not reported as overloaded");
}

// A stone shelf bridging two piers, with however many crates stacked on it.
//
// STONE, not oak, and the arithmetic is why. The shelf is 1.4 m long, 100 mm
// deep and 300 mm across, with a clear span of 1.0 m between its piers, so
//
//     stress = 3 W L / (2 b d^2) = 500 W
//
// Oak takes 90 MPa in tension, which would need 180 kN on it -- eighteen tonnes,
// or eighty-six crates, which is not a shelf, it is a quarry. Concrete takes
// 3 MPa, because concrete is famously weak in tension and that is the whole
// reason real concrete is reinforced. 6 kN breaks it, which is three crates,
// which is a shelf somebody overloaded.
//
// The span is what decides whether it can be bent at all: the same shelf laid
// on the ground is supported everywhere and cannot be.
TileImpactRequest shelf(int crates = 0, double crate_side_m = 0.2,
                        bool on_the_ground = false) {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody left;
    left.name = "left pier";
    left.shape = BodyShape::Box;
    left.material = MaterialPreset::Iron;
    left.dimensions_m = {0.2, 0.4, 0.3};
    left.center_m = {-0.6, 0.2, 0.0};
    left.anchored = true;
    SceneBody right = left;
    right.name = "right pier";
    right.center_m = {0.6, 0.2, 0.0};
    SceneBody shelf_body;
    shelf_body.name = "shelf";
    shelf_body.shape = BodyShape::Box;
    shelf_body.material = MaterialPreset::Concrete;
    shelf_body.dimensions_m = {1.4, 0.1, 0.3};
    shelf_body.center_m = {0.0, 0.45, 0.0};
    r.bodies = {left, right, shelf_body};
    if (on_the_ground) {
        // A bench under the whole plank: supported everywhere, no clear span.
        SceneBody bench;
        bench.name = "bench";
        bench.shape = BodyShape::Box;
        bench.material = MaterialPreset::Iron;
        bench.dimensions_m = {1.4, 0.4, 0.3};
        bench.center_m = {0.0, 0.2, 0.0};
        bench.anchored = true;
        r.bodies.push_back(bench);
    }
    for (int i = 0; i < crates; ++i) {
        SceneBody crate;
        crate.name = "crate " + std::to_string(i + 1);
        crate.shape = BodyShape::Box;
        crate.material = MaterialPreset::Iron;
        crate.dimensions_m = {crate_side_m, crate_side_m, crate_side_m};
        // Stacked in the middle of the span, which is where a beam is weakest.
        crate.center_m = {0.0, 0.5 + crate_side_m * (0.5 + static_cast<double>(i)), 0.0};
        r.bodies.push_back(crate);
    }
    return r;
}

// -----------------------------------------------------------------------------

void aPlankHoldsWhatItCanHold() {
    const auto world = LiveWorld::open(shelf(1, 0.2));
    run(*world, 480);
    const auto sags = world->overloaded();
    std::cout << "  one 63 kg crate on a stone shelf: " << sags.size()
              << " things reported as overloaded\n";
    require(sags.empty(), "a shelf was called overloaded while holding one crate");
    require(world->breakable().empty(),
            "nothing struck anything and nothing is overloaded, yet something "
            "was offered for breaking");
}

void pileOnEnoughAndItIsReported() {
    // Five crates of iron in the middle of a metre of stone. Nothing is
    // dropped: they are placed, they settle, and the shelf holds them.
    const auto world = LiveWorld::open(shelf(5, 0.3));
    run(*world, 480);
    const auto sags = world->overloaded();
    require(!sags.empty(),
            "a metre of stone with five iron crates on it was not reported as "
            "carrying too much");
    const LiveOverload plank = loadOn(*world, "shelf");
    std::cout << "  the shelf is carrying " << plank.carrying_n << " N over a "
              << plank.span_m << " m span: " << plank.stress_pa / 1e6
              << " MPa against concrete's " << plank.strength_pa / 1e6 << " MPa\n";
    require(plank.carrying_n > 1000.0, "it barely noticed the load");
    require(plank.stress_pa > plank.strength_pa, "it was reported without being over");

    // And the thing that makes this different from every other break here:
    // nothing hit anything. The contact ledger is empty.
    world->forgetImpacts();
    run(*world, 8);
    std::cout << "    and the contact ledger holds " << world->impacts(0.0).size()
              << " contacts, because nothing struck anything\n";
    require(world->impacts(0.0).empty(),
            "something was struck after all, so this is not sustained load");
    // It is offered for breaking all the same.
    const auto offered = world->breakable();
    require(std::find(offered.begin(), offered.end(), "shelf") != offered.end(),
            "the shelf is overloaded but was never offered for breaking");
}

void theSpanIsWhatDecidesIt() {
    // The same plank and the same six crates, with a bench underneath. Held
    // along its whole length it has no clear span, so there is no bending in
    // it however much is piled on -- which is the honest reason a plate lying
    // flat on the floor will not break.
    const auto world = LiveWorld::open(shelf(5, 0.3, true));
    run(*world, 480);
    std::cout << "  the same five crates, on a shelf supported all along its "
              << "length: " << world->overloaded().size() << " overloaded\n";
    require(!sagging(*world, "shelf"),
            "a shelf held everywhere along its length was called overloaded, so "
            "the span is not being taken into account");
}

void whatIsReportedCanActuallyBreak() {
    const auto world = LiveWorld::open(shelf(5, 0.3));
    run(*world, 480);
    require(sagging(*world, "shelf"), "the shelf was not reported in the first place");
    const std::size_t pieces = world->fracture("shelf");
    std::cout << "  put into the lattice under its load, the shelf came out in "
              << pieces << " pieces\n";
    // It has to actually FAIL, not merely be offered. Detecting an overload and
    // then being unable to do anything about it is half a capability.
    //
    // What makes this work is that the island is built with the load ON it. An
    // island normally comes from the CONTACT that caused the break, and a
    // sustained load has no contact -- so the shelf went into the lattice on its
    // own, with nothing pressing on it, and came out in one piece however much
    // was piled on. Impl::bearing_on is what hands it back its crates.
    require(pieces > 1,
            "the lattice was offered an overloaded shelf and gave it back whole, "
            "so the load is not reaching the island");
}

void loadTransfersThroughAStack() {
    // A stack. The shelf must be carrying every crate in it, not just the
    // one touching it.
    const auto world = LiveWorld::open(shelf(3, 0.2));
    run(*world, 480);
    // Not overloaded at this size, so ask the survey by loading it enough to
    // be reported and checking the number it gives.
    const auto heavy = LiveWorld::open(shelf(5, 0.3));
    run(*heavy, 480);
    const LiveOverload plank = loadOn(*heavy, "shelf");
    // Five 0.3 m iron crates: 0.027 m3 each at 7,870 kg/m3 is 212 kg and
    // 2,085 N, so five is 10.4 kN. The top crate is a metre and a half of stack
    // above the shelf and must still be counted.
    constexpr double kEach = 0.3 * 0.3 * 0.3 * 7870.0 * 9.81;
    std::cout << "  five crates of " << kEach << " N stacked: the shelf reports "
              << plank.carrying_n << " N, which is " << (plank.carrying_n / kEach)
              << " of them\n";
    require(plank.carrying_n > 3.5 * kEach,
            "the shelf is only carrying the crate that touches it, so load is "
            "not transferring through the stack");
    require(plank.carrying_n < 6.0 * kEach, "it is counting crates twice");
}

void aSeesawRespondsToWhereTheLoadIs() {
    // A plank on a pin. The same weight tips it one way or the other depending
    // only on which side of the pivot it sits -- which is torque, and is the
    // whole of what a lever is.
    double tilted[2] = {0.0, 0.0};
    for (int side = 0; side < 2; ++side) {
        TileImpactRequest r;
        r.cell_size_m = 0.05;
        r.backend = BackendKind::CpuParallel;
        SceneBody post;
        post.name = "post";
        post.shape = BodyShape::Box;
        post.material = MaterialPreset::Iron;
        post.dimensions_m = {0.2, 0.6, 0.2};
        post.center_m = {0.0, 0.3, 0.0};
        post.anchored = true;
        SceneBody plank;
        plank.name = "plank";
        plank.shape = BodyShape::Box;
        plank.material = MaterialPreset::Oak;
        plank.dimensions_m = {2.0, 0.1, 0.3};
        plank.center_m = {0.0, 0.7, 0.0};
        SceneBody weight;
        weight.name = "weight";
        weight.shape = BodyShape::Box;
        weight.material = MaterialPreset::Iron;
        weight.dimensions_m = {0.2, 0.2, 0.2};
        weight.center_m = {(side == 0 ? -0.8 : 0.8), 0.9, 0.0};
        r.bodies = {post, plank, weight};

        const auto world = LiveWorld::open(r);
        // The pin is through the middle of the plank, across it.
        const unsigned pivot = world->hinge("post", "plank", Vec3{0.0, 0.65, 0.0},
                                            Vec3{0.0, 0.0, 1.0}, -45.0, 45.0);
        require(pivot != 0, "the seesaw would not go on its pin");
        // A second, not four: the weight is sitting on a plank that is tipping
        // under it and will slide off in the end, which is right and is not what
        // this is about. Measured late, both sides read the same -- the weight
        // on the floor at y=0.1 -- and that looked like a seesaw that does not
        // care where you put things.
        run(*world, 240);
        for (const LiveJoint &pin : world->joints())
            if (pin.id == pivot) tilted[side] = pin.at * 180.0 / 3.14159265358979;
    }
    std::cout << "  a 618 N weight on the left of a seesaw tips it " << tilted[0]
              << " degrees; on the right, " << tilted[1] << "\n";
    // The ANGLE of the pin, not the height of anything. Whichever end carries
    // the weight goes down, so the two must come out on opposite sides of zero.
    require(tilted[0] * tilted[1] < 0.0,
            "the seesaw tipped the same way whichever side the weight was on, so "
            "where a load sits is not affecting it");
    require(std::abs(tilted[0]) > 5.0 && std::abs(tilted[1]) > 5.0,
            "the seesaw barely moved either way");
}

void aBalanceTipsTowardsTheHeavierSide() {
    const auto build = [](double left_side_m, double right_side_m) {
        TileImpactRequest r;
        r.cell_size_m = 0.05;
        r.backend = BackendKind::CpuParallel;
        SceneBody post;
        post.name = "post";
        post.shape = BodyShape::Box;
        post.material = MaterialPreset::Iron;
        post.dimensions_m = {0.2, 0.6, 0.2};
        post.center_m = {0.0, 0.3, 0.0};
        post.anchored = true;
        SceneBody beam;
        beam.name = "beam";
        beam.shape = BodyShape::Box;
        beam.material = MaterialPreset::Oak;
        beam.dimensions_m = {2.0, 0.1, 0.3};
        beam.center_m = {0.0, 0.7, 0.0};
        SceneBody left;
        left.name = "left pan";
        left.shape = BodyShape::Box;
        left.material = MaterialPreset::Iron;
        left.dimensions_m = {left_side_m, left_side_m, left_side_m};
        left.center_m = {-0.8, 0.75 + left_side_m / 2, 0.0};
        SceneBody right = left;
        right.name = "right pan";
        right.dimensions_m = {right_side_m, right_side_m, right_side_m};
        right.center_m = {0.8, 0.75 + right_side_m / 2, 0.0};
        r.bodies = {post, beam, left, right};
        return r;
    };

    // The pin's own angle again, for the same reason: the pans slide off a
    // tipping beam eventually, and where they end up on the floor says nothing.
    const auto leanOf = [&](double left_side_m, double right_side_m) {
        const auto world = LiveWorld::open(build(left_side_m, right_side_m));
        const unsigned pivot = world->hinge("post", "beam", Vec3{0.0, 0.65, 0.0},
                                            Vec3{0.0, 0.0, 1.0}, -40.0, 40.0);
        require(pivot != 0, "the balance would not go on its pin");
        run(*world, 240);
        for (const LiveJoint &pin : world->joints())
            if (pin.id == pivot) return pin.at * 180.0 / 3.14159265358979;
        throw std::runtime_error("the pin vanished");
    };
    const double matched = leanOf(0.2, 0.2);
    const double heavy_left = leanOf(0.3, 0.15);
    std::cout << "  matched pans: the beam sits at " << matched << " degrees; "
              << "a heavier left pan takes it to " << heavy_left << "\n";
    require(std::abs(matched) < 4.0, "matched weights did not balance");
    require(std::abs(heavy_left) > std::abs(matched) + 4.0,
            "a heavier pan on one side did not tip the beam any further than "
            "matched ones did");
}

void somethingInAHandWeighsOnNothing() {
    // A held body is pinned out of the simulation, so it is not pressing on
    // whatever it happens to be above.
    const auto world = LiveWorld::open(shelf(5, 0.3));
    run(*world, 480);
    require(sagging(*world, "shelf"), "the shelf was not overloaded to begin with");
    require(world->grab("shelf"), "could not take hold of the shelf");
    run(*world, 120);
    std::cout << "  picked the shelf up: overloaded reports "
              << world->overloaded().size() << " things\n";
    require(!sagging(*world, "shelf"),
            "a shelf in a hand is still being called overloaded");
}

} // namespace

int main() {
    try {
        aPlankHoldsWhatItCanHold();
        std::cout << "[PASS] a plank holds what it can hold\n";
        pileOnEnoughAndItIsReported();
        std::cout << "[PASS] pile on enough and it is reported, with no impact\n";
        theSpanIsWhatDecidesIt();
        std::cout << "[PASS] the span is what decides it\n";
        whatIsReportedCanActuallyBreak();
        std::cout << "[PASS] what is reported can actually break\n";
        loadTransfersThroughAStack();
        std::cout << "[PASS] load transfers through a stack\n";
        aSeesawRespondsToWhereTheLoadIs();
        std::cout << "[PASS] a seesaw responds to where the load is\n";
        aBalanceTipsTowardsTheHeavierSide();
        std::cout << "[PASS] a balance tips towards the heavier side\n";
        somethingInAHandWeighsOnNothing();
        std::cout << "[PASS] something in a hand weighs on nothing\n";
        std::cout << "\nall beam tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\n[FAIL] " << error.what() << "\n";
        return 1;
    }
}
