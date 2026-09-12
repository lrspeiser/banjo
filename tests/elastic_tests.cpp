// Elastic elements, and the validation of the model they declare.
//
// The model is an ideal linear spring and it is named as such everywhere it
// appears:
//
//     force  = stiffness * (length - rest)
//     stored = stiffness * (length - rest)^2 / 2
//
// Declaring a simplified model is allowed. Declaring one and not checking it is
// not, because everything built on top -- a bow, a catapult, a sprung cart --
// inherits whatever it actually does rather than whatever it says. So this file
// is the validation, and it is arranged as a chain of increasingly awkward
// questions:
//
// 1. Does it obey Hooke's law? Stretch it and measure the force.
// 2. Does the WORK done stretching it match the energy the model claims to
//    store? Integrated numerically over the draw, not assumed.
// 3. Does that energy come BACK as motion? Release it against a mass and
//    measure the kinetic energy.
// 4. Are the losses the declared ones? Damping should take energy and nothing
//    else should.
// 5. Does it push as well as pull? That is what tells it from a rope.
// 6. Does changing the stiffness change the answer, in the direction and by
//    roughly the amount the model says?
// 7. Does changing the MASS change the answer the same way?
//
// Numbers 3, 6 and 7 are the ones a bow depends on: an arrow's speed has to
// come out of the stored energy rather than being handed to it.

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

// The fastest the block ever goes over the next `steps`.
//
// Not its speed at the end, which was the first version of this and was wrong
// in a way worth writing down. A two-way spring is a HARMONIC OSCILLATOR: let
// go, the block accelerates to the rest length, shoots past it, squashes the
// spring, and comes back. Measured a full second after release -- most of a
// period at 2 kN/m on 63 kg -- it was near the far end of its swing with a
// third of the energy showing as motion and the rest back in the spring, and
// that read as a spring losing two thirds of what was put in.
//
// The peak is at the rest length, where the spring has given everything up and
// taken nothing back. Which is also exactly where an arrow leaves a bowstring,
// so this is not a convenience: it is the quantity a bow is about.
double fastestOver(LiveWorld &world, const std::string &what, int steps) {
    double best = 0.0;
    for (int i = 0; i < steps; ++i) {
        tick(world);
        const Vec3 speed = named(world.poses(), what).velocity_m_s;
        best = std::max(best, std::sqrt(speed.x * speed.x + speed.y * speed.y +
                                        speed.z * speed.z));
    }
    return best;
}

// An anchored post with a block beside it, in free space -- no floor under
// either, so nothing but the spring is acting horizontally.
//
// The block is the thing the spring will throw, and its mass is set by its
// size: 0.2 m of iron is 63 kg, 0.1 m is 7.9 kg.
TileImpactRequest bench(Vec3 block_m = Vec3{0.2, 0.2, 0.2}) {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    // No gravity. This is a bench test of a spring, and a spring that has to be
    // separated from gravity in the arithmetic is a spring whose measurement
    // has a second source of error in it.
    r.gravity_m_s2 = {0.0, 0.0, 0.0};
    SceneBody post;
    post.name = "post";
    post.shape = BodyShape::Box;
    post.material = MaterialPreset::Iron;
    post.dimensions_m = {0.2, 0.2, 0.2};
    post.center_m = {0.0, 2.0, 0.0};
    post.anchored = true;
    SceneBody block;
    block.name = "block";
    block.shape = BodyShape::Box;
    block.material = MaterialPreset::Iron;
    block.dimensions_m = block_m;
    block.center_m = {1.0, 2.0, 0.0};
    r.bodies = {post, block};
    return r;
}

constexpr double ironMassKg(Vec3 size_m) {
    return size_m.x * size_m.y * size_m.z * 7870.0;
}

// Stretch the spring by dragging the block, one millimetre a step, adding up
// the work done: the integral of force along the way.
//
// This is the measurement the whole file turns on. It is a numerical integral
// of the MODEL's force over the path actually travelled, so if the solver were
// not delivering that force the block would not be where the integral thinks it
// is, and the sum would not come out at 1/2 k x^2.
struct Draw {
    double work_j{};
    double drawn_m{};
    double force_at_end_n{};
};

Draw drawTo(LiveWorld &world, unsigned limb, double to_x) {
    Draw out{};
    // A BENCH hand: 3 kN, where an ordinary one has 800 N.
    //
    // The hand pulls with a bounded force, so with the default it simply cannot
    // draw a stiff spring as far as a soft one -- 800 N reaches 400 mm on
    // 2 kN/m and 100 mm on 8 kN/m. Every comparison below that changes the
    // stiffness would then be comparing two different draws, and it did:
    // four times the stiffness came out at 1.64 times the speed instead of 2,
    // because the stiffer spring had been drawn a quarter as far.
    world.setHandStrength(3000.0);
    const auto standing = world.poses();
    const double from_x = named(standing, "block").position_m.x;
    const int steps = static_cast<int>(std::abs(to_x - from_x) / 0.001);
    require(world.grab("block"), "could not take hold of the block");
    double was = jointNumber(world.joints(), limb).at;
    for (int i = 1; i <= steps; ++i) {
        const double x = from_x + (to_x - from_x) * i / steps;
        world.moveHeld(Vec3{x, 2.0, 0.0});
        tick(world);
        const LiveJoint now = jointNumber(world.joints(), limb);
        // Work is force times the distance moved ALONG the spring, which is the
        // change in its length -- not the distance the hand moved. They are the
        // same here and would not be if the draw were off to one side, and
        // getting that wrong is how a work integral quietly becomes a different
        // quantity.
        out.work_j += std::abs(now.force_n) * std::abs(now.at - was);
        was = now.at;
    }
    const LiveJoint ended = jointNumber(world.joints(), limb);
    out.drawn_m = ended.at - ended.rest_m;
    out.force_at_end_n = ended.force_n;
    return out;
}

// -----------------------------------------------------------------------------

void itObeysHookesLaw() {
    const auto world = LiveWorld::open(bench());
    const unsigned limb = world->spring("post", "block", Vec3{0.1, 2.0, 0.0},
                                        Vec3{0.9, 2.0, 0.0}, 0.0, 2000.0);
    require(limb != 0, "the spring would not go between the post and the block");
    const LiveJoint relaxed = jointNumber(world->joints(), limb);
    require(std::abs(relaxed.force_n) < 1.0,
            "a spring built at its own rest length is already pushing");

    // Three known loads, three extensions, against x = F/k.
    //
    // Hung on the hand's own force rather than pulled to a chosen position, and
    // that is what makes it a test rather than a tautology. The scene works out
    // `force_n` FROM the extension, so comparing the two would only ever
    // restate the formula. Pulling with a known load and measuring how far it
    // goes asks the solver instead: if the constraint were not delivering
    // stiffness times extension, the block would settle somewhere else.
    //
    // (It is also the only way that works now the hand pulls with a bounded
    // force rather than going where it is told. Asked to drag the block to a
    // point 200 mm out, a 400 N hand on a 2 kN/m spring simply stops at 200 mm
    // and a 100 N hand stops at 50 -- which is the right answer to a different
    // question, and read as "the force is not stiffness times extension".)
    for (const double load : {100.0, 200.0, 400.0}) {
        const auto fresh = LiveWorld::open(bench());
        // DAMPED, so it actually settles. An undamped spring is a harmonic
        // oscillator and never stops: hauled with 100 N against 2 kN/m it rings
        // about its 50 mm equilibrium for ever, and sampling it after 900 steps
        // caught it at 74.5 mm -- which reads as Hooke's law being wrong and is
        // a reading taken mid-swing. Damping changes how fast equilibrium is
        // reached and not where it is, which is exactly what is wanted here.
        const unsigned spring = fresh->spring("post", "block", Vec3{0.1, 2.0, 0.0},
                                              Vec3{0.9, 2.0, 0.0}, 0.0, 2000.0, 200.0);
        fresh->setHandStrength(load);
        require(fresh->grab("block"), "could not take hold of the block");
        // Well beyond where that load can reach, so the hand is pulling with
        // all of it and the spring decides where things stop.
        fresh->moveHeld(Vec3{3.0, 2.0, 0.0});
        run(*fresh, 900);
        const LiveJoint drawn = jointNumber(fresh->joints(), spring);
        const double wanted = load / 2000.0;
        std::cout << "  hauled with " << load << " N: it settled "
                  << (drawn.at - drawn.rest_m) * 1000.0 << " mm out, against "
                  << "Hooke's " << wanted * 1000.0 << " mm\n";
        require(std::abs((drawn.at - drawn.rest_m) - wanted) < 0.06 * wanted + 0.002,
                "a known load did not stretch it by load over stiffness, so the "
                "solver is not delivering Hooke's law");
    }
}

void theWorkDoneIsTheEnergyStored() {
    const auto world = LiveWorld::open(bench());
    const unsigned limb = world->spring("post", "block", Vec3{0.1, 2.0, 0.0},
                                        Vec3{0.9, 2.0, 0.0}, 0.0, 2000.0);
    require(limb != 0, "the spring would not go on");
    const Draw drawn = drawTo(*world, limb, 1.25);
    const LiveJoint at_full = jointNumber(world->joints(), limb);
    const double claimed = at_full.stored_j;
    std::cout << "  drawn " << drawn.drawn_m * 1000.0 << " mm: the work integral "
              << "is " << drawn.work_j << " J and the model claims to hold "
              << claimed << " J\n";
    require(drawn.drawn_m > 0.2, "the draw did not happen");
    require(std::abs(drawn.work_j - claimed) < 0.05 * claimed,
            "the work put in and the energy claimed do not agree, so the stored "
            "energy is not what was actually done to it");
}

void theEnergyComesBackAsMotion() {
    // The one a bow needs. Draw it, let go, and measure the kinetic energy of
    // what it throws. No damping, so nothing should be lost but the block's own
    // share of a two-body exchange -- and the post is anchored, so there is no
    // other body to share with.
    const auto world = LiveWorld::open(bench());
    const unsigned limb = world->spring("post", "block", Vec3{0.1, 2.0, 0.0},
                                        Vec3{0.9, 2.0, 0.0}, 0.0, 2000.0);
    require(limb != 0, "the spring would not go on");
    const Draw drawn = drawTo(*world, limb, 1.25);
    const double stored = jointNumber(world->joints(), limb).stored_j;
    world->release();
    // The fastest it ever goes, which is at the rest length -- see fastestOver.
    const double fastest = fastestOver(*world, "block", 240);
    const double mass = ironMassKg(Vec3{0.2, 0.2, 0.2});
    const double moving = 0.5 * mass * fastest * fastest;
    std::cout << "  " << stored << " J stored came back as " << moving
              << " J of motion (" << fastest << " m/s on " << mass
              << " kg), which is " << (100.0 * moving / stored) << "%\n";
    require(drawn.work_j > 0.0, "nothing was drawn");
    // Undamped and against an anchored post, most of it should come back. Not
    // all: the solver takes a little, and the block is still touching the
    // spring at the moment this is measured.
    require(moving > 0.8 * stored,
            "less than four fifths of the stored energy came back as motion, so "
            "the spring is losing energy it did not declare");
    require(moving < 1.05 * stored,
            "MORE energy came out than went in, which is a spring that makes "
            "energy rather than storing it");
}

void theLossesAreTheDeclaredOnes() {
    // The same draw through a damped spring. Damping is the declared loss, so
    // it must take energy -- and a spring with none must not.
    double came_back[2] = {0.0, 0.0};
    for (int damped = 0; damped < 2; ++damped) {
        const auto world = LiveWorld::open(bench());
        const unsigned limb = world->spring("post", "block", Vec3{0.1, 2.0, 0.0},
                                            Vec3{0.9, 2.0, 0.0}, 0.0, 2000.0,
                                            damped ? 400.0 : 0.0);
        require(limb != 0, "the spring would not go on");
        drawTo(*world, limb, 1.25);
        world->release();
        const double fastest = fastestOver(*world, "block", 240);
        came_back[damped] = 0.5 * ironMassKg(Vec3{0.2, 0.2, 0.2}) * fastest * fastest;
    }
    std::cout << "  undamped, " << came_back[0] << " J came back; with 400 N s/m "
              << "of damping, " << came_back[1] << " J\n";
    require(came_back[1] < 0.8 * came_back[0],
            "declaring a loss did not lose anything, so the damping is not doing "
            "what it says");
}

void itPushesAsWellAsPulls() {
    // The thing that tells it from a rope. Squash it below its rest length and
    // it must shove back; a rope would do nothing at all.
    // Damped and given time to settle, for the same reason the Hooke bench is:
    // an undamped spring rings for ever and a reading taken mid-swing measures
    // the swing. And leaned on with a known 300 N, so what comes back can be
    // checked against something rather than merely being negative.
    const auto world = LiveWorld::open(bench());
    const unsigned limb = world->spring("post", "block", Vec3{0.1, 2.0, 0.0},
                                        Vec3{0.9, 2.0, 0.0}, 0.0, 2000.0, 200.0);
    require(limb != 0, "the spring would not go on");
    world->setHandStrength(300.0);
    require(world->grab("block"), "could not take hold of the block");
    world->moveHeld(Vec3{0.4, 2.0, 0.0});       // shoved well past where 300 N reaches
    run(*world, 900);
    const LiveJoint squashed = jointNumber(world->joints(), limb);
    world->release();
    run(*world, 600);
    const double after = named(world->poses(), "block").position_m.x;
    std::cout << "  leaned on with 300 N it squashed "
              << (squashed.rest_m - squashed.at) * 1000.0 << " mm and pushes back with "
              << squashed.force_n << " N; released, the block returned to x="
              << after << "\n";
    require(squashed.force_n < -0.8 * 300.0,
            "squashing it produced no push, so it is behaving like a rope");
    require(after > 0.95, "it was let go squashed and did not spring back");
}

void stiffnessChangesTheAnswer() {
    // Same draw, same mass, four times the stiffness. Energy goes as k, and
    // speed as the square root of energy, so the speed should double.
    double speed_at[2] = {0.0, 0.0};
    for (int stiff = 0; stiff < 2; ++stiff) {
        const auto world = LiveWorld::open(bench());
        const unsigned limb = world->spring("post", "block", Vec3{0.1, 2.0, 0.0},
                                            Vec3{0.9, 2.0, 0.0}, 0.0,
                                            stiff ? 8000.0 : 2000.0);
        require(limb != 0, "the spring would not go on");
        drawTo(*world, limb, 1.25);
        world->release();
        speed_at[stiff] = fastestOver(*world, "block", 240);
    }
    const double ratio = speed_at[1] / speed_at[0];
    std::cout << "  2 kN/m throws it at " << speed_at[0] << " m/s; 8 kN/m at "
              << speed_at[1] << " -- a ratio of " << ratio << ", against the "
              << "model's 2\n";
    require(std::abs(ratio - 2.0) < 0.2,
            "four times the stiffness did not double the speed, so the energy "
            "is not going where the model says");
}

void massChangesTheAnswer() {
    // Same spring, same draw, eight times the mass. Energy is the same, so the
    // speed should fall by the square root of eight: about 2.83 times.
    const Vec3 light{0.1, 0.1, 0.1};            // 7.87 kg
    const Vec3 heavy{0.2, 0.2, 0.2};            // 62.96 kg, eight times
    double speed_at[2] = {0.0, 0.0};
    const Vec3 sizes[2] = {light, heavy};
    for (int which = 0; which < 2; ++which) {
        const auto world = LiveWorld::open(bench(sizes[which]));
        const unsigned limb = world->spring("post", "block", Vec3{0.1, 2.0, 0.0},
                                            Vec3{0.9, 2.0, 0.0}, 0.0, 2000.0);
        require(limb != 0, "the spring would not go on");
        drawTo(*world, limb, 1.25);
        world->release();
        speed_at[which] = fastestOver(*world, "block", 240);
    }
    const double ratio = speed_at[0] / speed_at[1];
    std::cout << "  " << ironMassKg(light) << " kg leaves at " << speed_at[0]
              << " m/s and " << ironMassKg(heavy) << " kg at " << speed_at[1]
              << " -- a ratio of " << ratio << ", against the model's 2.83\n";
    require(ratio > 2.3 && ratio < 3.4,
            "eight times the mass did not slow it by about the square root of "
            "eight, so the speed is not coming out of the energy");
}

void itRefusesWhatItCannotBe() {
    const auto world = LiveWorld::open(bench());
    require(world->spring("post", "nothing at all", Vec3{}, Vec3{}) == 0,
            "sprang to a body that does not exist");
    require(world->spring("block", "block", Vec3{}, Vec3{}) == 0,
            "sprang a body to itself");
    require(world->spring("post", "block", Vec3{0.1, 2.0, 0.0}, Vec3{0.9, 2.0, 0.0},
                          0.0, 0.0) == 0,
            "accepted a spring with no stiffness");
    require(world->spring("post", "block", Vec3{0.1, 2.0, 0.0}, Vec3{0.9, 2.0, 0.0},
                          0.0, 2000.0, -5.0) == 0,
            "accepted a spring that makes energy instead of losing it");
    require(world->joints().empty(), "a refused spring was recorded anyway");
    std::cout << "  a spring refuses a missing body, itself, no stiffness, and "
              << "negative damping\n";
}

} // namespace

int main() {
    try {
        itObeysHookesLaw();
        std::cout << "[PASS] it obeys Hooke's law\n";
        theWorkDoneIsTheEnergyStored();
        std::cout << "[PASS] the work done is the energy stored\n";
        theEnergyComesBackAsMotion();
        std::cout << "[PASS] the energy comes back as motion\n";
        theLossesAreTheDeclaredOnes();
        std::cout << "[PASS] the losses are the declared ones\n";
        itPushesAsWellAsPulls();
        std::cout << "[PASS] it pushes as well as pulls\n";
        stiffnessChangesTheAnswer();
        std::cout << "[PASS] stiffness changes the answer, by the model's amount\n";
        massChangesTheAnswer();
        std::cout << "[PASS] mass changes the answer, by the model's amount\n";
        itRefusesWhatItCannotBe();
        std::cout << "[PASS] a spring refuses what it cannot be\n";
        std::cout << "\nall elastic tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\n[FAIL] " << error.what() << "\n";
        return 1;
    }
}
