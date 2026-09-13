// A bow, built out of things that already existed.
//
// Nothing in this file is a bow feature. There is no bow type, no arrow type,
// no "fire" call and no arrow speed anywhere in the engine. What there is:
//
//   the riser      an anchored body -- the grip
//   two limbs      ELASTIC elements from the riser to the limb tips, which is
//                  where the energy goes when you draw
//   the string     LINKS from each tip to the nocking point, because a string
//                  pulls and does not push and that is exactly what a link is
//   the nock       a FIXING between the arrow and the nocking point, because
//                  what a nock does is hold two things together until it is
//                  released, which is what a latch is
//   loosing        unhinge() on that fixing
//
// The arrow's speed is therefore not chosen. It comes out of the energy in the
// limbs and the mass of what is nocked to the string, and the only way to change
// it is to change the bow, the draw, or the arrow. That is the claim, and every
// test below is a way of trying to catch it not being true.
//
// What is pinned:
//
// 1. A drawn bow stores energy, and drawing further stores more -- as the
//    square of the draw, because that is what a linear limb does.
// 2. Loosed, the arrow leaves with kinetic energy that came from the limbs.
// 3. A STIFFER bow throws the same arrow faster.
// 4. A LONGER draw throws the same arrow faster.
// 5. A HEAVIER arrow leaves slower, and carries more momentum for it.
// 6. The string cannot push: an arrow ahead of the string is not dragged.
// 7. Nothing is loosed until the nock is released.
// 8. The arrow is an ordinary body afterwards -- it falls, it is affected by
//    gravity, and it can be picked up again.

#include "fastlattice/LiveWorld.hpp"

#include <cmath>
#include <cstdlib>
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

double speedOf(LiveWorld &world, const std::string &what) {
    const Vec3 v = named(world.poses(), what).velocity_m_s;
    return std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
}

// The bow is built lying along x. The archer is at -x, the target at +x: the
// string is drawn back in -x and the arrow flies in +x.
//
// THE TIPS ARE LEVEL WITH THE STRING, as on the courtyard's bow and for its
// reason. They used to sit 300 mm forward of it, and the braced string was then
// a V with the nocking point at its apex: push the nock towards the bow and BOTH
// segments go slack, so nothing brings it back, and brace was not an equilibrium
// at all. What decided where the string ended up was rounding. Measured, the
// same bow drawn 100 mm held 22.5 J built by MSVC and 1.3 J built by GCC; loosed
// with no arrow, the string ran on to x = +0.62 on one and never came back to
// brace on the other. With the tips level, moving the nock off the line between
// them in ANY direction lengthens both segments, and it comes back.
//
// (A limb is a hinge at the root and an elastic from a point forward of it --
// see below -- so drawing swings each tip back and inward about its root and
// lengthens that elastic, which is where the energy goes. A real limb stores it
// by bending; this declares it as a lever with a spring on it. Same energy,
// declared differently -- tests/elastic_tests.cpp says what the model is.)
//
// So: grip at x = 0, the string a brace height of 160 mm behind it, and the tips
// level with the string, 400 mm out.
constexpr double kBrace = -0.16;    // where the string sits, unshot
constexpr double kTipX = kBrace;    // the tips, level with the string
constexpr double kTipUp = 0.40;     // how far out along the limb

// A limb is ROOTED, and getting that wrong cost two geometries.
//
// First attempt: one elastic from the grip to the tip. An elastic constrains the
// DISTANCE and nothing else, so the tip was free to swing anywhere on a sphere
// of that radius -- and it did. Drawn 200 mm, the upper tip had orbited back
// past the grip to (-0.38, 2.19) with the limb still at its rest length and the
// string slack at 0.197 of 0.5. The bow stored a hundredth of a joule and
// drawing further stored LESS, because the tip just followed the string round.
//
// Second attempt: two elastics, from points 400 mm apart on the riser. Better --
// 1.9 J at a 100 mm draw -- and still wrong, because two points on the same
// vertical line leave a CIRCLE of free motion: rotation about the line joining
// them. Drawn 300 mm the tip had swung from x=+0.15 to x=-0.135, which is very
// nearly that rotation, and both stays came back to rest. 0.086 J.
//
// What a limb actually is: rooted to the riser so it can only bend in the plane
// of the bow, with something elastic resisting the bend. So --
//
//   a HINGE at the root, axis across the bow, which removes every degree of
//   freedom except the swing;
//   an ELASTIC from a point forward of that root to the tip, which lengthens as
//   the tip swings back.
//
// That is a lever with a spring on it, which is a declared and ordinary way to
// model a limb: the restoring torque is the spring force times the moment arm
// rather than a true bending stiffness. Everything else follows from it.
struct Bow {
    std::unique_ptr<LiveWorld> world;
    unsigned upper_root{}, lower_root{};        // the hinges
    unsigned upper_limb{}, lower_limb{};        // the elastics
    unsigned upper_string{}, lower_string{};
    unsigned nocked{};
};

// Where the limbs are rooted on the riser, and where their springs are anchored.
//
// The string must never pull straight through a root: with the tips forward of
// it, a root 200 mm out put the root, the tip and the nocking point on one line,
// the string exerted no torque on the limb at all, and the hand heaved with its
// full 800 N at a bow that did not move -- which looks exactly like a hand that
// is too weak and is a lever arm of zero. With the tips level with the string
// the braced string runs straight up and down 160 mm behind the roots, so that
// lever arm is the brace height whatever the root. 120 mm out, and the springs
// anchored 360 mm forward of the grip: the courtyard's bow.
constexpr double kRootUp = 0.12;
constexpr double kSpringX = 0.36;

// A DECLARED loss in the limbs, as the courtyard's bow has, and for its reason.
// Undamped, the limbs rang for ever, so what they held after a fixed number of
// steps was a snapshot of an oscillation at whatever phase it had reached --
// the same bow drawn 100 mm read 18.9 J built by MSVC and 30.8 J built by GCC,
// and which bow of two "stored more" came down to that phase.
constexpr double kLimbDamping = 20.0;   // N s/m

TileImpactRequest bowScene(Vec3 arrow_m, bool with_gravity) {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    if (!with_gravity) r.gravity_m_s2 = {0.0, 0.0, 0.0};
    // The riser is TWO blocks with a window between them for the arrow, as the
    // courtyard's bow is. It was one block, and the arrow was built running
    // straight through the middle of it: a dynamic body inside an anchored one
    // from the first step, pushed out by whatever the contact solver made of
    // that. The result depended on the compiler -- drawn 100/200 mm the same bow
    // held 7.3/103 J built by MSVC and 28.9/58.7 J built by GCC, and on Linux
    // the stiffer bow threw slower -- which is a measurement of the overlap, not
    // of a bow. The window is 200 mm, from y = 1.9 to 2.1: the heavy arrow is
    // 100 mm across, and a box here is a whole number of 50 mm cells. The limb
    // roots stay where they were, at 2.1 and 1.9 -- now on the blocks' faces.
    SceneBody riser;
    riser.name = "riser upper";
    riser.shape = BodyShape::Box;
    riser.material = MaterialPreset::Oak;
    riser.dimensions_m = {0.1, 0.1, 0.1};
    riser.center_m = {0.0, 2.15, 0.0};
    riser.anchored = true;              // the grip: a hand that does not move
    SceneBody riser_lower = riser;
    riser_lower.name = "riser lower";
    riser_lower.center_m = {0.0, 1.85, 0.0};
    // Cheeks either side of the window, 25 mm clear of the heaviest arrow: an
    // arrow rest's side plates. Made off at its two ends (see the string),
    // nothing resists the nocking point ROLLING about the string's own length,
    // and rolling it swings the arrow out of the bow's plane. The courtyard's
    // bow has them for that reason, and so do real ones.
    SceneBody cheek = riser;
    cheek.name = "cheek near";
    cheek.dimensions_m = {0.05, 0.05, 0.05};
    cheek.center_m = {0.0, 2.0, 0.1};
    SceneBody cheek_far = cheek;
    cheek_far.name = "cheek far";
    cheek_far.center_m = {0.0, 2.0, -0.1};
    SceneBody upper;
    upper.name = "upper tip";
    upper.shape = BodyShape::Box;
    upper.material = MaterialPreset::Oak;
    // SMALL tips, and the mass ratio is the reason. A limb tip is a thing the
    // spring has to accelerate before any of the energy can reach the arrow, so
    // whatever it weighs is taken out of the shot: 100 mm oak cubes are 0.7 kg
    // each against a 1.05 kg arrow, and measured that way 110 J in the limbs
    // put 3 J into the arrow -- 2.7% -- with the rest thrown into the tips. At
    // 50 mm they are 0.0875 kg and the arrow gets the shot. Real bows are built
    // the same way round and for the same reason.
    upper.dimensions_m = {0.05, 0.05, 0.05};
    upper.center_m = {kTipX, 2.0 + kTipUp, 0.0};
    SceneBody lower = upper;
    lower.name = "lower tip";
    lower.center_m = {kTipX, 2.0 - kTipUp, 0.0};
    // A LENGTH of string, 150 mm of it, not a nocking POINT: see the string's
    // links. A 50 mm one let the arrow's weight turn it, and with gravity on the
    // arrow was hanging nearly straight down from the nock when it was loosed.
    SceneBody nock;
    nock.name = "nocking point";
    nock.shape = BodyShape::Box;
    nock.material = MaterialPreset::Oak;
    nock.dimensions_m = {0.05, 0.15, 0.05};
    nock.center_m = {kBrace, 2.0, 0.0};
    SceneBody arrow;
    arrow.name = "arrow";
    arrow.shape = BodyShape::Box;
    arrow.material = MaterialPreset::Oak;
    arrow.dimensions_m = arrow_m;
    // Its back end at the nocking point, so it lies forward along the shot.
    arrow.center_m = {kBrace + arrow_m.x / 2, 2.0, 0.0};
    r.bodies = {riser, riser_lower, cheek, cheek_far, upper, lower, nock, arrow};
    return r;
}

// Assemble the bow out of the general parts. No step of this knows what a bow
// is: two springs, two ropes and a latch.
Bow buildBow(double stiffness_n_m = 4000.0,
             Vec3 arrow_m = Vec3{0.6, 0.05, 0.05},
             bool with_gravity = false,
             double hand_n = 800.0) {
    Bow bow{};
    bow.world = LiveWorld::open(bowScene(arrow_m, with_gravity));
    LiveWorld &w = *bow.world;
    // The ordinary hand: 800 N, what a person has and what the playground uses.
    //
    // This was a 2 kN "bench" hand, and at 2 kN the hand's pull is not a hand at
    // all: it is pushed as an explicit force once a step, at strength/0.05 N/m
    // and strength/8 N s/m, and across the string -- where the string and the
    // arrow fixed to it are a 0.3 kg thing on a lever -- 2 kN's worth of that is
    // past what a 240 Hz step can integrate (damping 3.5 and stiffness 2.3 of a
    // step's worth, against a limit of 2). Held still at full draw, the string
    // spun the arrow round sideways at 12 m/s for ten seconds, and which way it
    // spun was rounding: MSVC and GCC builds of the same bow disagreed fourteen
    // times over, and "a stiffer bow throws faster" passed on one and failed on
    // the other. The "6 kN demolished the bow" this used to warn about was the
    // same thing. At 800 N the same bow comes to rest, and the two builds agree
    // to three figures.
    //
    // The fix for the hand itself is to pull INSIDE the solver -- a force-bounded
    // constraint, not a force pushed from outside -- which is stable for any mass
    // and any strength (docs/interaction-profiles.md). Until then, a bow is
    // drawn with the hand people actually have.
    w.setHandStrength(hand_n);

    // The limbs. Elastic, from the grip out to each tip -- drawing the string
    // pulls the tips inward and that is where the energy goes.
    // The roots: a pin across the bow, so each limb can only swing in the
    // bow's own plane. Without this the tip orbits and stores nothing.
    // Sixty degrees each way, not a hundred and twenty. A limb that can fold
    // right over is a limb that WILL: heaved at with 6 kN the upper limb went
    // to -120 degrees, which put its tip below the grip, and the string came out
    // 36% longer than it is. A bow whose limbs can turn inside out is not a bow.
    bow.upper_root = w.hinge("riser upper", "upper tip", Vec3{0.0, 2.0 + kRootUp, 0.0},
                             Vec3{0.0, 0.0, 1.0}, -60.0, 60.0);
    bow.lower_root = w.hinge("riser lower", "lower tip", Vec3{0.0, 2.0 - kRootUp, 0.0},
                             Vec3{0.0, 0.0, 1.0}, -60.0, 60.0);
    require(bow.upper_root != 0 && bow.lower_root != 0,
            "the limbs would not root to the riser");

    // And the elastic that resists the swing, anchored forward of the root so
    // that swinging back lengthens it.
    bow.upper_limb = w.spring("riser upper", "upper tip", Vec3{kSpringX, 2.0 + kRootUp, 0.0},
                              Vec3{kTipX, 2.0 + kTipUp, 0.0}, 0.0, stiffness_n_m, kLimbDamping);
    bow.lower_limb = w.spring("riser lower", "lower tip", Vec3{kSpringX, 2.0 - kRootUp, 0.0},
                              Vec3{kTipX, 2.0 - kTipUp, 0.0}, 0.0, stiffness_n_m, kLimbDamping);
    require(bow.upper_limb != 0 && bow.lower_limb != 0, "the limbs would not go on");

    // The string. Links, because a string pulls and does not push -- made off at
    // the string's two ENDS, 150 mm apart, not both at its middle. Two ropes made
    // off at one point are a ball joint: the string, and the arrow fixed 300 mm
    // in front of it, were free to turn about it with nothing to stop them. Made
    // off apart, turning the string has to lengthen one of them. The courtyard's
    // bow learned the same thing and is strung the same way.
    bow.upper_string = w.tie("upper tip", "nocking point",
                             Vec3{kTipX, 2.0 + kTipUp, 0.0}, Vec3{kBrace, 2.075, 0.0});
    bow.lower_string = w.tie("lower tip", "nocking point",
                             Vec3{kTipX, 2.0 - kTipUp, 0.0}, Vec3{kBrace, 1.925, 0.0});
    require(bow.upper_string != 0 && bow.lower_string != 0,
            "the string would not go on");

    // The nock: the arrow held to the string until it is loosed.
    bow.nocked = w.fix("nocking point", "arrow", Vec3{kBrace, 2.0, 0.0},
                       Vec3{1.0, 0.0, 0.0});
    require(bow.nocked != 0, "the arrow would not nock");
    return bow;
}

// Everything the two limbs are holding.
double storedInLimbs(const Bow &bow) {
    const auto joints = bow.world->joints();
    return jointNumber(joints, bow.upper_limb).stored_j +
           jointNumber(joints, bow.lower_limb).stored_j;
}

// Draw the bow by taking hold of the nocking point and pulling it back.
double drawBack(Bow &bow, double by_m) {
    LiveWorld &w = *bow.world;
    require(w.grab("nocking point"), "could not take hold of the string");
    const int steps = static_cast<int>(by_m / 0.002);
    for (int i = 1; i <= steps; ++i)
        { w.moveHeld(Vec3{kBrace - by_m * i / steps, 2.0, 0.0}); tick(w); }
    // And HOLD at full draw until it settles.
    //
    // The hand pulls with a bounded force, so reaching full draw takes as long
    // as it takes -- it is not a position the string is put at. Without the
    // hold, a short draw simply ran out of steps before the force had finished
    // working: 0.027 J at 100 mm and 207 at 300, from the same bow, because the
    // long draw happened to be given three times as many steps to get there.
    // Drawing and holding is also what an archer does.
    //
    // Held until it has STOPPED -- the string still for a quarter of a second
    // -- and not for a fixed count of steps, which read limbs still ringing.
    for (int i = 0, still = 0; i < 2400 && still < 60; ++i) {
        tick(w);
        still = speedOf(w, "nocking point") < 0.001 ? still + 1 : 0;
    }
    return storedInLimbs(bow);
}

// How far back the string actually is: the hand pulls with what it has, so a
// stiff bow is not always drawn as far as the hand went.
double drawnTo(Bow &bow) {
    return kBrace - named(bow.world->poses(), "nocking point").position_m.x;
}

// Everything the bow is doing, for comparing one build of the engine with
// another. BANJO_BOW_TRACE=1 prints it; it changes nothing.
void dumpBow(Bow &bow, const std::string &label) {
    static const bool on = std::getenv("BANJO_BOW_TRACE") != nullptr;
    if (!on) return;
    const auto joints = bow.world->joints();
    const auto poses = bow.world->poses();
    const auto joint = [&](const char *what, unsigned id) {
        const LiveJoint j = jointNumber(joints, id);
        std::cout << "    " << what << ": at " << j.at << " tension " << j.tension_n
                  << " force " << j.force_n << " stored " << j.stored_j << "\n";
    };
    const auto body = [&](const char *name) {
        const LiveBodyPose &p = named(poses, name);
        std::cout << "    " << name << ": at (" << p.position_m.x << ", " << p.position_m.y
                  << ", " << p.position_m.z << ") q (" << p.orientation_wxyz[0] << ", "
                  << p.orientation_wxyz[1] << ", " << p.orientation_wxyz[2] << ", "
                  << p.orientation_wxyz[3] << ") v (" << p.velocity_m_s.x << ", "
                  << p.velocity_m_s.y << ", " << p.velocity_m_s.z << ")\n";
    };
    std::cout << "  [" << label << "]\n";
    joint("upper root", bow.upper_root);
    joint("lower root", bow.lower_root);
    joint("upper limb", bow.upper_limb);
    joint("lower limb", bow.lower_limb);
    joint("upper string", bow.upper_string);
    joint("lower string", bow.lower_string);
    body("upper tip");
    body("lower tip");
    body("nocking point");
    body("arrow");
}

// Loose. Returns the fastest the arrow ever goes.
//
// Let go with the fingers, and let the arrow go from the string AT BRACE --
// which is where an arrow leaves a real string, because that is the point where
// the string stops and the arrow does not. Unhinging the nock at the moment of
// release instead, which was the first version of this, frees the arrow BEFORE
// the string has pushed it: measured, 110 J in the limbs threw the arrow at
// 0.6 m/s, being 0.18% of the stored energy, because the string accelerated
// away from an arrow that was no longer attached to it.
double loose(Bow &bow, int steps = 240) {
    LiveWorld &w = *bow.world;
    w.release();
    bool away = false;
    double best = 0.0;
    for (int i = 0; i < steps; ++i) {
        if (!away && named(w.poses(), "nocking point").position_m.x >= kBrace) {
            w.unhinge(bow.nocked);
            away = true;
        }
        tick(w);
        best = std::max(best, speedOf(w, "arrow"));
    }
    require(away, "the string never came back to brace, so the arrow was never "
                  "loosed at all");
    return best;
}

constexpr double oakMassKg(Vec3 size_m) {
    return size_m.x * size_m.y * size_m.z * 700.0;
}

// -----------------------------------------------------------------------------

void drawingStoresEnergy() {
    // And drawing further stores MORE -- as the square, because the limbs are
    // linear. Three draws on the same bow.
    double held[3] = {0.0, 0.0, 0.0};
    const double draws[3] = {0.1, 0.2, 0.3};
    for (int i = 0; i < 3; ++i) {
        Bow bow = buildBow();
        held[i] = drawBack(bow, draws[i]);
        dumpBow(bow, "drawn " + std::to_string(static_cast<int>(draws[i] * 1000.0)) + " mm");
    }
    std::cout << "  drawn 100/200/300 mm: " << held[0] << " / " << held[1] << " / "
              << held[2] << " J in the limbs\n";
    require(held[0] > 0.1, "drawing the bow stored nothing at all");
    require(held[1] > held[0] && held[2] > held[1],
            "drawing further did not store more");
    // Not exactly four times -- the limb tips move less than the string does,
    // because the string runs at an angle. But well over twice.
    require(held[2] > 2.5 * held[0],
            "trebling the draw barely changed the energy, so the limbs are not "
            "what is storing it");
}

void theArrowLeavesWithTheLimbsEnergy() {
    Bow bow = buildBow();
    const double stored = drawBack(bow, 0.3);
    const double fastest = loose(bow);
    const Vec3 arrow_m{0.6, 0.05, 0.05};
    const double mass = oakMassKg(arrow_m);
    const double moving = 0.5 * mass * fastest * fastest;
    std::cout << "  " << stored << " J in the limbs threw a " << mass << " kg arrow "
              << "at " << fastest << " m/s, which is " << moving << " J ("
              << (100.0 * moving / stored) << "% of it)\n";
    require(fastest > 1.0, "the arrow did not leave the bow");
    require(moving < 1.05 * stored,
            "the arrow carries MORE energy than the limbs held, which is a bow "
            "that makes energy");
    // It will not be all of it: the string and the nocking point have mass of
    // their own and take a share, which is exactly what happens to a real bow
    // and is why light arrows are inefficient.
    require(moving > 0.1 * stored,
            "almost none of the stored energy reached the arrow");
}

void aStifferBowThrowsItFaster() {
    double away[2] = {0.0, 0.0};
    double held[2] = {0.0, 0.0};
    // Twice the stiffness, at a 200 mm draw, with the ordinary hand -- which
    // draws both bows almost all the way (197 and 195 mm, measured).
    //
    // Not four times at 300 mm: that needs about four times the force, and a
    // 6 kN hand drove the limb hard into its 60-degree stop, where the energy
    // goes into the stop rather than the spring. The same 4 kN/m bow then read
    // 38 J where a 2 kN hand had read 161, which is a measurement of the stop.
    const double stiffness[2] = {4000.0, 8000.0};
    double drawn[2] = {0.0, 0.0};
    for (int i = 0; i < 2; ++i) {
        Bow bow = buildBow(stiffness[i]);
        held[i] = drawBack(bow, 0.2);
        drawn[i] = drawnTo(bow);
        dumpBow(bow, std::to_string(static_cast<int>(stiffness[i])) + " N/m drawn 200 mm");
        away[i] = loose(bow);
    }
    std::cout << "  4 kN/m drawn " << drawn[0] * 1000.0 << " mm holds " << held[0]
              << " J and throws it at " << away[0] << " m/s; 8 kN/m drawn "
              << drawn[1] * 1000.0 << " mm holds " << held[1] << " J and throws it at "
              << away[1] << "\n";
    require(held[1] > held[0],
            "the stiffer bow did not even store more energy at the same draw");
    // Faster, but not in proportion to the energy: measured, twice the
    // stiffness stored 1.9 times as much and threw the arrow 11% faster,
    // because a stiffer bow also has to accelerate its own limbs and string
    // harder and they keep the difference. That is a real property of bows --
    // it is why limb mass matters so much to an archer -- and expecting the
    // speed to follow the energy is the thing being caught here.
    require(away[1] > away[0],
            "twice the limb stiffness stored more energy and did NOT throw the "
            "arrow any faster, so the extra energy went nowhere");
}

void aBowTooStiffToDrawThrowsLess() {
    // The other side of the same coin, and a real result rather than a
    // limitation: the hand pulls with a bounded force, so a bow stiff enough to
    // beat it cannot be drawn as far -- and a bow you cannot draw throws less,
    // however good it would be in stronger hands.
    double away[2] = {0.0, 0.0};
    double held[2] = {0.0, 0.0};
    const double stiffness[2] = {4000.0, 16000.0};
    for (int i = 0; i < 2; ++i) {
        // An ordinary person, not the bench.
        Bow bow = buildBow(stiffness[i], Vec3{0.6, 0.05, 0.05}, false, 800.0);
        held[i] = drawBack(bow, 0.3);
        away[i] = loose(bow);
    }
    std::cout << "  an 800 N archer: the 4 kN/m bow stores " << held[0]
              << " J and shoots " << away[0] << " m/s; the 16 kN/m bow stores "
              << held[1] << " J and shoots " << away[1] << "\n";
    require(away[1] < away[0],
            "a bow too stiff for the archer to draw threw the arrow faster, so "
            "the draw is not bounded by what the hand can pull");
}

void aLongerDrawThrowsItFaster() {
    double away[2] = {0.0, 0.0};
    const double draws[2] = {0.15, 0.35};
    for (int i = 0; i < 2; ++i) {
        Bow bow = buildBow();
        drawBack(bow, draws[i]);
        away[i] = loose(bow);
    }
    std::cout << "  drawn 150 mm it leaves at " << away[0] << " m/s; drawn 350 mm, "
              << away[1] << "\n";
    require(away[1] > 1.3 * away[0],
            "drawing more than twice as far did not throw it faster, so the draw "
            "is not what is being stored");
}

void aHeavierArrowLeavesSlower() {
    // And carries more momentum for it, which is why war arrows are heavy.
    const Vec3 light{0.6, 0.05, 0.05};
    const Vec3 heavy{0.6, 0.1, 0.1};            // four times the mass
    double away[2] = {0.0, 0.0};
    const Vec3 sizes[2] = {light, heavy};
    for (int i = 0; i < 2; ++i) {
        Bow bow = buildBow(4000.0, sizes[i]);
        drawBack(bow, 0.3);
        away[i] = loose(bow);
    }
    const double p_light = oakMassKg(light) * away[0];
    const double p_heavy = oakMassKg(heavy) * away[1];
    std::cout << "  a " << oakMassKg(light) << " kg arrow leaves at " << away[0]
              << " m/s (" << p_light << " kg m/s); a " << oakMassKg(heavy)
              << " kg one at " << away[1] << " (" << p_heavy << ")\n";
    require(away[1] < away[0],
            "four times the arrow mass did not slow it down, so the speed is not "
            "coming out of a fixed amount of energy");
    require(p_heavy > p_light,
            "the heavy arrow left slower AND with less momentum, which is not "
            "what a fixed energy does");
}

void theStringCannotPush() {
    // The property that makes it a string rather than a rod. Nock nothing,
    // draw the string back, and let it go: the string snaps forward to brace
    // and stops. It must not carry on and shove the nocking point past brace
    // by some large distance, because past brace there is nothing pulling.
    Bow bow = buildBow();
    LiveWorld &w = *bow.world;
    w.unhinge(bow.nocked);          // no arrow on the string
    drawBack(bow, 0.3);
    w.release();
    run(w, 240);
    const double rest = named(w.poses(), "nocking point").position_m.x;
    std::cout << "  loosed with no arrow, the string settled at x=" << rest
              << " against a brace of " << kBrace << "\n";
    require(rest > kBrace - 0.08,
            "the string ended up well behind brace, so something is holding it "
            "back there");
    require(rest < kBrace + 0.35,
            "the string carried the nocking point far past brace, which means it "
            "is pushing rather than pulling");
}

void nothingIsLoosedUntilTheNockIsReleased() {
    Bow bow = buildBow();
    LiveWorld &w = *bow.world;
    drawBack(bow, 0.3);
    // Let go of the string but NOT the nock. The whole assembly -- string,
    // nocking point and arrow -- comes forward together and stops at brace.
    w.release();
    run(w, 240);
    const double still_on = speedOf(w, "arrow");
    const auto standing = w.poses();
    const double arrow_x = named(standing, "arrow").position_m.x;
    const double nock_x = named(standing, "nocking point").position_m.x;
    std::cout << "  string released, nock still fixed: the arrow is at x="
              << arrow_x << ", the nocking point at x=" << nock_x
              << ", doing " << still_on << " m/s\n";
    // The DISTANCE between them, not the difference in x. Still nocked, the
    // arrow's centre stays half an arrow from the nocking point however the
    // whole assembly has turned -- and it does turn, so comparing x alone
    // reported the arrow "off the string" when it was still firmly on it.
    const auto now = w.poses();
    const double apart = length(named(now, "arrow").position_m -
                                named(now, "nocking point").position_m);
    std::cout << "    they are " << apart << " m apart, against the half-arrow "
              << "0.3 they were nocked at\n";
    require(std::abs(apart - 0.3) < 0.06,
            "the arrow came off the string without the nock being released");
}

void theArrowIsAnOrdinaryBodyAfterwards() {
    // With gravity this time. It is thrown, it flies, it falls, and it can be
    // picked up -- because it is a body and was never anything else.
    Bow bow = buildBow(8000.0, Vec3{0.6, 0.05, 0.05}, true);
    drawBack(bow, 0.3);
    LiveWorld &w = *bow.world;
    const double fastest = loose(bow, 60);
    const Vec3 left_from = named(w.poses(), "arrow").position_m;
    run(w, 600);
    const Vec3 landed = named(w.poses(), "arrow").position_m;
    // How far it went ACROSS the ground, from wherever it happened to be
    // loosed -- not how far along +x. With gravity on, the whole bow sags
    // during the hold: the tips droop, the string settles, and the shot is no
    // longer along the axis the scene was laid out on. Measured that way the
    // arrow "went nowhere" while in fact travelling a metre and a half in a
    // direction the test had decided in advance.
    const double travelled = std::sqrt((landed.x - left_from.x) * (landed.x - left_from.x) +
                                       (landed.z - left_from.z) * (landed.z - left_from.z));
    std::cout << "  loosed at " << fastest << " m/s, the arrow travelled "
              << travelled << " m across the ground and fell from y="
              << left_from.y << " to y=" << landed.y << "\n";
    require(travelled > 0.5, "the arrow went nowhere");
    require(landed.y < left_from.y - 0.5,
            "the arrow did not fall, so gravity is not acting on it");
    require(w.grab("arrow"), "the arrow cannot be picked up again");
}

} // namespace

int main() {
    try {
        drawingStoresEnergy();
        std::cout << "[PASS] drawing stores energy, and drawing further stores more\n";
        theArrowLeavesWithTheLimbsEnergy();
        std::cout << "[PASS] the arrow leaves with the limbs' energy\n";
        aStifferBowThrowsItFaster();
        std::cout << "[PASS] a stiffer bow throws it faster\n";
        aLongerDrawThrowsItFaster();
        std::cout << "[PASS] a longer draw throws it faster\n";
        aHeavierArrowLeavesSlower();
        std::cout << "[PASS] a heavier arrow leaves slower and carries more\n";
        theStringCannotPush();
        std::cout << "[PASS] the string cannot push\n";
        nothingIsLoosedUntilTheNockIsReleased();
        std::cout << "[PASS] nothing is loosed until the nock is released\n";
        theArrowIsAnOrdinaryBodyAfterwards();
        std::cout << "[PASS] the arrow is an ordinary body afterwards\n";
        std::cout << "\
all bow tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\
[FAIL] " << error.what() << "\n";
        return 1;
    }
}
