// A scene that keeps running instead of being run.
//
// The playground plays a recording: to move something you edit the scene and run
// the whole thing again. LiveWorld holds the rigid world open instead, so a host
// can step it a frame at a time, read where everything is, and take hold of an
// object. What is pinned here:
//
// 1. A world opens intact, with every object under the name the request gave it
//    and the shape it was authored as.
// 2. Stepping is gravity: an unsupported ball falls and lands on what is below.
// 3. A held object goes where it is put and stays there -- gravity and contacts
//    stop moving it -- and falls again when it is let go.
// 4. Anchored scenery refuses to be picked up. It is the world, not a prop.
// 5. A step costs far less than the frame it has to fit in.

#include "fastlattice/LiveWorld.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}

// An anchored oak floor with an iron ball held above it.
TileImpactRequest ballOverFloor(double ball_height_mm = 600.0) {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    // The default is CUDA, which this build does not have. The playground
    // asks for the parallel CPU lane and so does this.
    r.backend = BackendKind::CpuParallel;
    SceneBody floor;
    floor.name = "floor";
    floor.shape = BodyShape::Box;
    floor.material = MaterialPreset::Oak;
    floor.dimensions_m = {0.6, 0.04, 0.4};
    floor.center_m = {0.0, 0.02, 0.0};
    floor.anchored = true;
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.1, 0.1, 0.1};
    ball.center_m = {0.0, ball_height_mm / 1000.0, 0.0};
    r.bodies = {floor, ball};
    return r;
}

const LiveBodyPose &named(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    for (const LiveBodyPose &pose : poses)
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

void aWorldOpensIntactAndNamed() {
    const auto live = LiveWorld::open(ballOverFloor());
    const auto poses = live->poses();
    require(poses.size() == 2, "expected the two bodies that were asked for");
    const LiveBodyPose &floor = named(poses, "floor");
    const LiveBodyPose &ball = named(poses, "ball");
    require(floor.shape == "box", "an authored box should open as a box, not a hull");
    require(ball.shape == "sphere", "an authored sphere should open as a sphere");
    require(floor.anchored, "the floor was anchored");
    require(!ball.anchored, "the ball was not anchored");
    require(std::abs(ball.dimensions_m.x - 0.1) < 1e-9, "the ball kept the diameter it was given");
    std::cout << "  opened: " << poses.size() << " bodies, ball at y=" << ball.position_m.y
              << ", floor at y=" << floor.position_m.y << "\n";
}

void steppingIsGravity() {
    const auto live = LiveWorld::open(ballOverFloor());
    const double start = named(live->poses(), "ball").position_m.y;
    for (int i = 0; i < 240; ++i) live->step(1.0 / 120.0);
    const auto poses = live->poses();
    const LiveBodyPose &ball = named(poses, "ball");
    const LiveBodyPose &floor = named(poses, "floor");
    std::cout << "  after 2 s: ball y " << start << " -> " << ball.position_m.y
              << " (floor top is 0.04)\n";
    require(ball.position_m.y < start - 0.2, "the ball did not fall");
    require(ball.position_m.y > 0.04, "the ball fell through the floor it landed on");
    require(std::abs(floor.position_m.y - 0.02) < 1e-6, "the anchored floor moved");
}

void aHeldObjectGoesWhereItIsPut() {
    const auto live = LiveWorld::open(ballOverFloor());
    require(live->grab("ball"), "the ball could not be picked up");
    require(live->held() == "ball", "the world did not report what it was holding");
    live->moveHeld({0.15, 1.5, 0.0});
    // Held through many steps: gravity is pulling and contacts are solving, and
    // it must not move a millimetre.
    for (int i = 0; i < 120; ++i) live->step(1.0 / 120.0);
    const LiveBodyPose held = named(live->poses(), "ball");
    std::cout << "  held for 1 s at (0.15, 1.5, 0): now (" << held.position_m.x << ", "
              << held.position_m.y << ", " << held.position_m.z << ")\n";
    require(std::abs(held.position_m.y - 1.5) < 1e-3, "a held ball drifted under gravity");
    require(std::abs(held.position_m.x - 0.15) < 1e-3, "a held ball did not go where it was put");
    require(held.held, "the pose did not say it was held");

    live->release();
    require(live->held().empty(), "the world still thinks it is holding something");
    for (int i = 0; i < 240; ++i) live->step(1.0 / 120.0);
    const LiveBodyPose dropped = named(live->poses(), "ball");
    std::cout << "  let go: fell to y=" << dropped.position_m.y << "\n";
    require(dropped.position_m.y < 1.0, "the ball did not fall after being let go");
    require(dropped.position_m.y > 0.04, "the dropped ball fell through the floor");
}

void anchoredSceneryCannotBePickedUp() {
    const auto live = LiveWorld::open(ballOverFloor());
    require(!live->grab("floor"), "anchored scenery let itself be picked up");
    require(live->held().empty(), "a refused grab still took hold of something");
    require(!live->grab("nothing called this"), "an unknown name was grabbed");
}

void aStepFitsInAFrame() {
    const auto live = LiveWorld::open(ballOverFloor());
    for (int i = 0; i < 60; ++i) live->step(1.0 / 60.0);  // warm up
    const auto began = std::chrono::steady_clock::now();
    constexpr int kSteps = 600;
    for (int i = 0; i < kSteps; ++i) live->step(1.0 / 60.0);
    const double wall = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - began).count();
    const double per_step_ms = 1000.0 * wall / kSteps;
    std::cout << "  " << kSteps << " steps in " << wall << " s = " << per_step_ms
              << " ms per step (a 60 Hz frame is 16.7 ms)\n";
    // Generous: this is about establishing there is no order-of-magnitude
    // problem, not about pinning a machine's speed.
    require(per_step_ms < 8.0, "a step does not fit in half a frame");
}

// An iron ball dropped from a height onto a glass pane resting on the ground.
TileImpactRequest ballOntoGlass(double drop_m) {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    // The default is CUDA, which this build does not have. The playground
    // asks for the parallel CPU lane and so does this.
    r.backend = BackendKind::CpuParallel;
    SceneBody pane;
    pane.name = "pane";
    pane.shape = BodyShape::Box;
    pane.material = MaterialPreset::Glass;
    pane.dimensions_m = {0.3, 0.04, 0.3};
    pane.center_m = {0.0, 0.02, 0.0};
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.1, 0.1, 0.1};
    ball.center_m = {0.0, 0.04 + 0.05 + drop_m, 0.0};
    r.bodies = {pane, ball};
    return r;
}

// The hardest hit the pane takes over a fall, and whether the engine judged it
// enough to break it.
LiveImpact hardestOnThePane(double drop_m) {
    const auto live = LiveWorld::open(ballOntoGlass(drop_m));
    LiveImpact worst{};
    for (int i = 0; i < 400; ++i) {
        live->step(1.0 / 240.0);
        for (const LiveImpact &impact : live->impacts())
            if (impact.struck == "pane" && impact.closing_speed_m_s > worst.closing_speed_m_s)
                worst = impact;
    }
    return worst;
}

void aContactIsJudgedAgainstWhatItHit() {
    // Falling 1.5 m arrives at about 5.4 m/s; falling 60 mm at about 1 m/s.
    const LiveImpact hard = hardestOnThePane(1.5);
    const LiveImpact soft = hardestOnThePane(0.06);
    std::cout << "  dropped 1.50 m: pane hit at " << hard.closing_speed_m_s
              << " m/s, needs " << hard.threshold_speed_m_s << " m/s -> "
              << (hard.would_break ? "breaks" : "holds") << "\n";
    std::cout << "  dropped 0.06 m: pane hit at " << soft.closing_speed_m_s
              << " m/s, needs " << soft.threshold_speed_m_s << " m/s -> "
              << (soft.would_break ? "breaks" : "holds") << "\n";
    require(hard.closing_speed_m_s > 3.0, "the ball did not arrive with any speed");
    require(hard.threshold_speed_m_s > 0.0, "the pane has no breaking speed at all");
    // Without this the gentle half could pass by never landing at all, which
    // is not the same statement as "it landed and held".
    require(soft.closing_speed_m_s > 0.1, "the gentle drop never actually hit the pane");
    require(soft.closing_speed_m_s < hard.closing_speed_m_s,
            "a shorter drop should land more gently");
    // The point of the test: the SAME pane and the SAME ball give different
    // verdicts, because the verdict is about the contact and not about the
    // scene. If both came back alike the trigger would be reporting nothing.
    require(hard.would_break != soft.would_break,
            "a hard drop and a gentle one were judged identically, so the "
            "trigger is not reading the contact");
    require(hard.would_break, "a 5 m/s iron ball onto a glass pane should break it");
    require(!soft.would_break, "a gentle tap should not break a glass pane");
}

void anImpactNamesBothSides() {
    const auto live = LiveWorld::open(ballOntoGlass(1.0));
    for (int i = 0; i < 400; ++i) {
        live->step(1.0 / 240.0);
        for (const LiveImpact &impact : live->impacts()) {
            require(!impact.struck.empty() && !impact.by.empty(), "an impact with no names");
            require(impact.struck != impact.by, "an object was reported hitting itself");
        }
    }
    // Two things leaning on each other are not an impact.
    require(live->impacts(1000.0).empty(), "a 1000 m/s filter still reported impacts");
}

// Drop the ball, and when the world says the pane cannot take it, break it.
// Returns what the pane became.
struct Drop {
    std::size_t pieces{};
    double at_speed{};
    double threshold{};
    double fracture_wall_ms{};
    std::size_t bodies_after{};
};

Drop dropAndBreak(double drop_m) {
    const auto live = LiveWorld::open(ballOntoGlass(drop_m));
    Drop out{};
    for (int i = 0; i < 600; ++i) {
        live->step(1.0 / 240.0);
        for (const LiveImpact &impact : live->impacts())
            if (impact.struck == "pane" && impact.closing_speed_m_s > out.at_speed) {
                out.at_speed = impact.closing_speed_m_s;
                out.threshold = impact.threshold_speed_m_s;
            }
        const auto breakable = live->breakable();
        if (std::find(breakable.begin(), breakable.end(), std::string("pane")) == breakable.end())
            continue;
        const auto began = std::chrono::steady_clock::now();
        out.pieces = live->fracture("pane");
        out.fracture_wall_ms = 1000.0 * std::chrono::duration<double>(
            std::chrono::steady_clock::now() - began).count();
        break;
    }
    out.bodies_after = live->bodies();
    // The world must still be steppable after being rearranged mid-flight.
    for (int i = 0; i < 120; ++i) live->step(1.0 / 240.0);
    return out;
}

void aHardEnoughHitActuallyBreaksIt() {
    const Drop hard = dropAndBreak(10.0);
    const Drop marginal = dropAndBreak(1.5);
    std::cout << "  dropped 10.00 m: hit at " << hard.at_speed << " m/s (threshold "
              << hard.threshold << ") -> " << hard.pieces << " pieces of pane in "
              << hard.fracture_wall_ms << " ms; world now holds " << hard.bodies_after
              << " bodies\n";
    std::cout << "  dropped  1.50 m: hit at " << marginal.at_speed << " m/s (threshold "
              << marginal.threshold << ") -> " << marginal.pieces << " pieces\n";

    require(hard.at_speed > hard.threshold, "the drop never exceeded the breaking speed");
    require(hard.pieces > 1, "a 14 m/s iron ball did not break a glass pane");
    require(hard.bodies_after > 2, "the world did not gain the pieces it made");
    require(hard.fracture_wall_ms > 1.0,
            "the lattice cannot have run at all in under a millisecond");

    // The threshold is a LOWER BOUND -- a necessary condition, taken from a
    // spall bound that is deliberately generous. Clearing it means a break is
    // possible, not that one happens, and this pair is the evidence: 5.4 m/s
    // against a 4.5 m/s threshold is admitted and the pane still holds, while
    // 13.9 m/s shatters it. Reading admission as a promise reads the derivation
    // backwards, and a test that only ever checked the hard case would let that
    // misreading stand.
    require(marginal.at_speed > marginal.threshold,
            "the 1.5 m drop was supposed to clear the threshold");
    require(marginal.pieces <= 1,
            "the marginal drop broke it after all -- the note about the bound "
            "being necessary rather than sufficient needs revisiting");
}

void aGentleHitLeavesItWhole() {
    const auto live = LiveWorld::open(ballOntoGlass(0.06));
    for (int i = 0; i < 600; ++i) {
        live->step(1.0 / 240.0);
        require(live->breakable().empty(), "a gentle tap was called breakable");
    }
    require(live->bodies() == 2, "a scene that broke nothing changed its body count");
    // And asking directly still refuses to invent a break.
    require(live->fracture("pane") == 1, "a pane nothing happened to came apart anyway");
    require(live->bodies() == 2, "a refused fracture still changed the world");
}

void breakingSomethingThatCannotBreakIsHarmless() {
    const auto live = LiveWorld::open(ballOverFloor());
    require(live->fracture("floor") == 1, "anchored scenery was broken up");
    require(live->fracture("no such object") == 0, "an unknown name was fractured");
    require(live->bodies() == 2, "the world changed size over refused requests");
}

// The world must not deadlock on something that was hit hard enough to be worth
// trying and came through whole.
//
// A step that would break something is taken back, so the world sits one step
// short of the impact. If the fracture then finds the object HELD, nothing has
// changed: the next step meets the same contact, is judged breakable again, and
// is taken back again. The clock stops, and a host is told the same thing for
// ever. That is exactly what a live playground did -- the scene froze and the
// chat repeated "concrete ball was hit hard enough to break" without end.
void aThingThatHeldDoesNotStopTheWorld() {
    // 1.5 m arrives above the threshold and does not break the pane, which is
    // the case that used to wedge.
    const auto live = LiveWorld::open(ballOntoGlass(1.5));
    bool ever_breakable = false, tried = false;
    for (int i = 0; i < 900; ++i) {
        live->step(1.0 / 240.0);
        if (!tried && !live->breakable().empty()) {
            ever_breakable = true;
            tried = true;
            require(live->fracture("pane") <= 1,
                    "this drop was supposed to be the marginal one that holds");
        }
    }
    require(ever_breakable, "the drop never cleared the threshold, so this proves nothing");
    const double reached = live->time_s();
    std::cout << "  held at the threshold, then ran on to t=" << reached << " s\n";
    // The clock is the whole point: a deadlocked world sits at the instant it
    // refused, however many times it is stepped.
    require(reached > 1.0,
            "the world stopped advancing after something held: it is deadlocked");
    require(!live->steppedBack(),
            "the world is still refusing to take a step after the object held");
}

// Lift something, carry it well away from where it started, let go: it falls
// and the ground catches it. It used to fall for ever.
//
// The batch lane's floor is 8 m square, which is ample for a plate dropped where
// it was authored -- nothing in a recording moves sideways on its own. A live
// world is different: someone carries an object where they like, and past 4 m
// there was no floor at all. An iron ball taken to x = 5 m and released reached
// -7.9 m and was still going, which is not a physics answer.
void theGroundCatchesThingsWhereverTheyAreDropped() {
    for (const double x : {0.0, 3.0, 9.0, 40.0}) {
        const auto live = LiveWorld::open(ballOverFloor());
        require(live->grab("ball"), "the ball could not be picked up");
        live->moveHeld({x, 3.0, 0.0});
        live->release();
        for (int i = 0; i < 900; ++i) live->step(1.0 / 240.0);
        const LiveBodyPose ball = named(live->poses(), "ball");
        std::cout << "  let go at x=" << x << " m -> settled y=" << ball.position_m.y << "\n";
        // The oak floor is 40 mm thick and the ball is 100 mm across, so resting
        // on it puts the centre near 0.09; off the world it is tens of metres
        // down and still accelerating.
        require(ball.position_m.y > -0.2,
                "nothing caught it: there is no ground where it was dropped");
    }
}

} // namespace

int main() {
    try {
        aWorldOpensIntactAndNamed();
        std::cout << "[PASS] a world opens intact, named, and in the shapes that were asked for\n";
        steppingIsGravity();
        std::cout << "[PASS] stepping is gravity: the ball falls and lands on the floor\n";
        aHeldObjectGoesWhereItIsPut();
        std::cout << "[PASS] a held object goes where it is put and falls when let go\n";
        anchoredSceneryCannotBePickedUp();
        std::cout << "[PASS] anchored scenery cannot be picked up\n";
        aStepFitsInAFrame();
        std::cout << "[PASS] a step fits inside a frame with room to spare\n";
        aContactIsJudgedAgainstWhatItHit();
        std::cout << "[PASS] a contact is judged against what it hit, hard differs from gentle\n";
        anImpactNamesBothSides();
        std::cout << "[PASS] an impact names both sides; resting contacts are not impacts\n";
        aHardEnoughHitActuallyBreaksIt();
        std::cout << "[PASS] a hard enough hit puts the object back in the lattice and breaks it\n";
        aGentleHitLeavesItWhole();
        std::cout << "[PASS] a gentle hit leaves it whole, and asking anyway does not break it\n";
        breakingSomethingThatCannotBreakIsHarmless();
        std::cout << "[PASS] breaking scenery or a name that is not there changes nothing\n";
        aThingThatHeldDoesNotStopTheWorld();
        std::cout << "[PASS] something that was hit hard and held does not deadlock the world\n";
        theGroundCatchesThingsWhereverTheyAreDropped();
        std::cout << "[PASS] the ground catches things wherever they are dropped\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "live world tests failed: " << error.what() << "\n";
        return 1;
    }
}
