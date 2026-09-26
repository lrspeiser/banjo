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

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

// Which lattice backend to time, from the environment, so the same binary can
// be run on either lane: BANJO_BENCH_BACKEND=cuda | cpuparallel | cpu.
// Unset means the parallel CPU lane, which is what everything else uses.
//
// This exists because the GPU lane turned out to be TEN TIMES SLOWER than the
// parallel CPU one -- 3358 ms against 331 ms for the same 506-node island over
// the same 5193 substeps -- and the reason is worth being able to re-measure.
// The island schedule is built through the single-argument buildLatticeSchedule
// (Refracture.cpp), which hard-wires block_count = 1, so the kernel runs as one
// cooperative block: one streaming multiprocessor out of a 5090's 170, about
// 0.6% of the card, against all 24 cores on the CPU side. The kernel is not
// wrong -- the parity tests pass bit for bit -- it is starved. When the
// schedule is made multi-block this switch is how you find out whether that
// fixed it.
banjo::fastlattice::BackendKind benchBackend() {
    using banjo::fastlattice::BackendKind;
    const char *v = std::getenv("BANJO_BENCH_BACKEND");
    if (v == nullptr) return BackendKind::CpuParallel;
    const std::string s{v};
    if (s == "cuda") return BackendKind::Cuda;
    if (s == "cpu") return BackendKind::Cpu;
    return BackendKind::CpuParallel;
}
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
    r.backend = benchBackend();
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
    r.backend = benchBackend();
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

// How many bodies in the world are pieces of a given parent, counted by name.
// fracture() returns the same number, so the two can be held against each other.
std::size_t piecesNamedAfter(const LiveWorld &live, const std::string &parent) {
    std::size_t found = 0;
    for (const LiveBodyPose &pose : live.poses(false))
        if (pose.name.rfind(parent, 0) == 0) ++found;
    return found;
}

// Drop the ball, and when the world says the pane cannot take it, break it.
// Returns what the pane became.
struct Drop {
    std::size_t pieces{};
    double at_speed{};
    double threshold{};
    double fracture_wall_ms{};
    std::size_t bodies_after{};
    // What the world actually holds under the pane's name, to hold the reported
    // count against.
    std::size_t pane_bodies{};
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
    out.pane_bodies = piecesNamedAfter(*live, "pane");
    // The world must still be steppable after being rearranged mid-flight.
    for (int i = 0; i < 120; ++i) live->step(1.0 / 240.0);
    return out;
}

// The count fracture() reports is the count that is actually in the world.
//
// It used to be read after the struck body had been erased from nodes_of, so it
// indexed a vector that had just been shortened past the index it was using.
// With the struck body at index 0 the read landed on memory that happened to
// give the right answer and every test passed; with a plate standing on two
// piers -- the playground's own arrangement, where the plate is body 2 of 4 --
// it read off the end. A plate that came apart into eight pieces was reported
// as having held, and the panel said so in the chat while the pieces were on
// screen in front of the reader.
//
// So this scene puts the struck body where the bug shows: not first, and with
// bodies both before and after it.
void theCountIsWhatIsActuallyInTheWorld() {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = benchBackend();
    std::vector<SceneBody> scene;
    for (int side = -1; side <= 1; side += 2) {
        SceneBody pier;
        pier.name = side < 0 ? "pier left" : "pier right";
        pier.shape = BodyShape::Box;
        pier.material = MaterialPreset::Iron;
        pier.dimensions_m = {0.06, 0.2, 0.3};
        pier.center_m = {side * 0.12, 0.1, 0.0};
        pier.anchored = true;
        scene.push_back(pier);
    }
    SceneBody pane;
    pane.name = "pane";
    pane.shape = BodyShape::Box;
    pane.material = MaterialPreset::Glass;
    pane.dimensions_m = {0.3, 0.04, 0.3};
    pane.center_m = {0.0, 0.22, 0.0};
    scene.push_back(pane);
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.1, 0.1, 0.1};
    ball.center_m = {0.0, 0.22 + 0.02 + 0.05 + 10.0, 0.0};
    scene.push_back(ball);
    r.bodies = scene;

    const auto live = LiveWorld::open(r);
    require(live->bodies() == 4, "the scene did not open with its four bodies");
    std::size_t reported = 0;
    bool broke = false;
    for (int i = 0; i < 900 && !broke; ++i) {
        live->step(1.0 / 240.0);
        const auto breakable = live->breakable();
        if (std::find(breakable.begin(), breakable.end(), std::string("pane")) == breakable.end())
            continue;
        reported = live->fracture("pane");
        broke = true;
    }
    require(broke, "the pane was never judged breakable, so this proves nothing");
    const std::size_t present = piecesNamedAfter(*live, "pane");
    std::cout << "  pane at index 2 of 4: fracture() said " << reported
              << ", the world holds " << present << "\n";
    require(reported > 1, "a ball dropped 10 m did not break the pane");
    require(reported == present,
            "fracture() reported a different number of pieces than the world holds");
}

void aHardEnoughHitActuallyBreaksIt() {
    const Drop hard = dropAndBreak(10.0);
    const Drop marginal = dropAndBreak(0.8);
    std::cout << "  dropped 10.00 m: hit at " << hard.at_speed << " m/s (threshold "
              << hard.threshold << ") -> " << hard.pieces << " pieces of pane in "
              << hard.fracture_wall_ms << " ms; world now holds " << hard.bodies_after
              << " bodies\n";
    std::cout << "  dropped  0.80 m: hit at " << marginal.at_speed << " m/s (threshold "
              << marginal.threshold << ") -> " << marginal.pieces << " pieces\n";

    require(hard.at_speed > hard.threshold, "the drop never exceeded the breaking speed");
    require(hard.pieces > 1, "a 14 m/s iron ball did not break a glass pane");
    require(hard.pieces == hard.pane_bodies,
            "fracture() reported a different number of pieces than the world holds");
    require(hard.bodies_after > 2, "the world did not gain the pieces it made");
    require(hard.fracture_wall_ms > 1.0,
            "the lattice cannot have run at all in under a millisecond");

    // The threshold is a LOWER BOUND -- a necessary condition, taken from a
    // spall bound that is deliberately generous. Clearing it means a break is
    // possible, not that one happens, and this pair is the evidence: 3.9 m/s
    // against a 2.25 m/s threshold is admitted and the pane still holds, while
    // 13.9 m/s shatters it. Reading admission as a promise reads the derivation
    // backwards, and a test that only ever checked the hard case would let that
    // misreading stand.
    //
    // It was a 1.5 m drop against a 4.5 m/s threshold. Glass breaks at the
    // 45 MPa EN 572-1 gives annealed float glass now, rather than at twice
    // that strain, so both numbers halved and 1.5 m goes through the pane.
    // 0.8 m clears the bar by the same wide margin and still holds.
    require(marginal.at_speed > marginal.threshold,
            "the 0.8 m drop was supposed to clear the threshold");
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
    // 0.8 m arrives above the threshold and does not break the pane, which is
    // the case that used to wedge. It was 1.5 m against a 4.5 m/s threshold;
    // glass breaks at its declared 45 MPa now rather than at twice that strain,
    // so the threshold is 2.25 m/s and 1.5 m goes through.
    const auto live = LiveWorld::open(ballOntoGlass(0.8));
    int answered = 0;
    for (int i = 0; i < 900; ++i) {
        live->step(1.0 / 240.0);
        // EVERY offer, not only the first. A ball that holds goes on bouncing,
        // and each bounce past the bar is a fresh question -- it used to be
        // asked once because the bar was 4.5 m/s and no bounce came near it.
        // At glass's real 45 MPa the bar is 2.25 and the pane is asked about
        // dozens of times. A host that answers one and ignores the rest stops
        // the world, which is a host bug and not an engine one, but a test
        // that answers once cannot tell the two apart.
        while (!live->breakable().empty()) {
            ++answered;
            require(live->fracture("pane") <= 1,
                    "this drop was supposed to be the marginal one that holds");
        }
    }
    require(answered > 0, "the drop never cleared the threshold, so this proves nothing");
    const double reached = live->time_s();
    std::cout << "  held at the threshold " << answered << " times, then ran on to t="
              << reached << " s\n";
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
// Lift something out of a world that has been sitting still, and let it go.
//
// The other hold-and-drop test grabs an object seconds after the world opens,
// while everything in it is still moving. A playground is not like that: it is
// left running, everything comes to rest, and THEN someone reaches in. A rigid
// solver stops simulating a body that has been still long enough -- that is how
// a scene of a hundred pieces stays cheap -- and a hold that only re-asserts a
// pose never wakes it. The object then rode up with the hand, was let go, and
// hung there, because as far as the solver was concerned it was not a body in
// flight, it was furniture.
//
// This is the bug the owner hit twice: "if I lift an object off the ground and
// let it go, gravity should drop it", and then "when i pick it up it just stays
// up". So the test waits for the world to go quiet before it touches anything.
void somethingLiftedOutOfASettledWorldStillFalls() {
    const auto live = LiveWorld::open(ballOntoGlass(0.06));   // too gentle to break
    // Long enough for everything to come to rest and be put to sleep.
    for (int i = 0; i < 1200; ++i) live->step(1.0 / 240.0);
    const auto ballY = [&] {
        for (const LiveBodyPose &pose : live->poses(false))
            if (pose.name == "ball") return pose.position_m.y;
        throw std::runtime_error("the ball is gone");
    };
    const double settled = ballY();
    std::cout << "  world quiet at t=" << live->time_s() << " s, ball resting at y="
              << settled << "\n";

    require(live->grab("ball"), "a settled ball could not be picked up");
    // Carry it up a metre, the way a hand does: a move per frame.
    const double lifted = settled + 1.0;
    for (int i = 1; i <= 60; ++i) {
        live->moveHeld({0.0, settled + (lifted - settled) * i / 60.0, 0.0});
        live->step(1.0 / 240.0);
    }
    require(std::abs(ballY() - lifted) < 0.02, "the ball did not go where it was carried");
    live->release();
    std::cout << "  let go at y=" << ballY() << "\n";

    for (int i = 0; i < 480; ++i) live->step(1.0 / 240.0);   // two seconds
    const double after = ballY();
    std::cout << "  two seconds later: y=" << after << "\n";
    require(after < lifted - 0.3,
            "it was let go a metre up and did not fall: the world had gone to sleep "
            "and letting go never woke it");
    require(std::abs(after - settled) < 0.05,
            "it fell, but not back to where it had been resting");
}

// What the pointer is on is a question for the solver, not for a second copy
// of the shapes.
//
// The playground answered it in the browser, against each body's bounding box
// with a margin. That is wrong in both directions: it claims a hit in the empty
// corner of a box, and it cannot describe a piece that broke off something,
// whose cells ARE its surface and which no box fits. Asking the world means the
// answer is the shape the body actually collides with.
void aRayFindsWhatItActuallyHits() {
    const auto live = LiveWorld::open(ballOntoGlass(0.5));
    // Straight down the middle from above: the ball is on top, the pane under
    // it, so the first thing met must be the ball.
    const LivePick top = live->pick({0.0, 6.0, 0.0}, {0.0, -1.0, 0.0});
    std::cout << "  down the middle: " << (top.hit ? top.name : "nothing")
              << " at " << top.distance_m << " m\n";
    require(top.hit && top.name == "ball", "a ray down the middle did not meet the ball");

    // A ray that passes beside everything meets the ground, which is a hit with
    // no name -- a different answer from meeting nothing at all.
    const LivePick beside = live->pick({3.0, 6.0, 0.0}, {0.0, -1.0, 0.0});
    require(beside.hit && beside.name.empty(),
            "a ray beside the scene should meet the unnamed ground");

    // And one aimed at the sky meets nothing.
    const LivePick sky = live->pick({0.0, 6.0, 0.0}, {0.0, 1.0, 0.0});
    require(!sky.hit, "a ray fired at the sky hit something");

    // The distance has to be a real distance, not a fraction: the ball's top is
    // 0.5 m of drop plus the pane and its own radius below the ray's start.
    require(top.distance_m > 4.0 && top.distance_m < 6.0,
            "the reported distance is not in metres along the ray");
    // And the point has to be ON the ray.
    require(std::abs(top.point_world_m.x) < 1e-9 &&
                std::abs(top.point_world_m.y - (6.0 - top.distance_m)) < 1e-6,
            "the reported hit point is not on the ray");

    // A ray too short to reach reports nothing, rather than the thing it would
    // have reached.
    require(!live->pick({0.0, 6.0, 0.0}, {0.0, -1.0, 0.0}, 0.5).hit,
            "a ray shorter than the gap still reported a hit");

    // The pointer's real job: pick something and it is the thing you can grab.
    require(live->grab(top.name), "what the ray found could not be picked up");
    require(live->held() == top.name, "a different object ended up in the hand");
    live->release();
}

// A piece that broke off something can be pointed at.
//
// This is the case a bounding box cannot do. A fragment is a hull whose cells
// are its surface; its box covers empty space its neighbours are sitting in, so
// a box test picks whichever fragment happens to be checked first.
void aRayFindsPiecesAfterSomethingBreaks() {
    const auto live = LiveWorld::open(ballOntoGlass(10.0));
    bool broke = false;
    for (int i = 0; i < 900 && !broke; ++i) {
        live->step(1.0 / 240.0);
        const auto breakable = live->breakable();
        if (std::find(breakable.begin(), breakable.end(), std::string("pane")) != breakable.end()) {
            live->fracture("pane");
            broke = true;
        }
    }
    require(broke, "the pane never broke, so this proves nothing");
    for (int i = 0; i < 600; ++i) live->step(1.0 / 240.0);   // let the pieces settle

    // Fire straight down at each piece's own centre. Whatever else is in the
    // way, the ray must come back with the name of a body that is really there.
    std::size_t asked = 0, answered = 0, exact = 0;
    for (const LiveBodyPose &pose : live->poses(false)) {
        if (pose.name.rfind("pane", 0) != 0) continue;
        ++asked;
        const LivePick got = live->pick({pose.position_m.x, pose.position_m.y + 2.0,
                                         pose.position_m.z}, {0.0, -1.0, 0.0});
        if (!got.hit || got.name.empty()) continue;
        ++answered;
        if (got.name == pose.name) ++exact;
        // Whatever it named has to be a body the world is holding.
        bool real = false;
        for (const LiveBodyPose &other : live->poses(false))
            if (other.name == got.name) { real = true; break; }
        require(real, "the ray named something the world is not holding: " + got.name);
    }
    std::cout << "  " << asked << " pieces, " << answered << " rays met a named body, "
              << exact << " met the piece they were aimed at\n";
    require(asked > 4, "the pane did not break into enough pieces to prove anything");
    require(answered == asked, "a ray aimed straight down at a piece met nothing named");
    // Aimed from directly above its own centre, a piece is often what is hit
    // first -- but not always, because another piece can be resting over it,
    // and the finer the shatter the more of them are. Glass breaks at the
    // 45 MPa EN 572-1 gives annealed float now rather than at twice that
    // strain, so the same blow makes 37 pieces where it made 8, and 17 of the
    // 37 rays meet their own piece where more than half used to.
    //
    // The share is a sanity check and not the claim. The claim is the two
    // above it: every ray met a named body, and every name was a body the
    // world is really holding. A ray query that had lost the shapes would
    // score near nothing here, not a third.
    require(exact * 3 >= asked,
            "fewer than a third of the rays found the piece they were aimed at, so the "
            "query is not tracking the real shapes");
}

// How high a ball of some material comes back off a concrete floor, as a
// fraction of the height it fell.
//
// Measured at the turn, not by watching for it to get within some distance of
// the floor. A threshold on height cannot work: a bouncy ball reverses before
// it ever gets that low, so the trigger never fires and the bounciest material
// in the catalogue reads as not bouncing at all. That is not a hypothetical --
// it is what the first version of this measurement said, and rubber came back
// as 0.0 mm, which is the sort of number that should stop you rather than be
// written down.
double bounceFraction(MaterialPreset material) {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = benchBackend();
    SceneBody floor;
    floor.name = "floor";
    floor.shape = BodyShape::Box;
    floor.material = MaterialPreset::Concrete;
    floor.dimensions_m = {3.0, 0.1, 3.0};
    floor.center_m = {0.0, 0.05, 0.0};
    floor.anchored = true;
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = material;
    ball.dimensions_m = {0.1, 0.1, 0.1};
    ball.center_m = {0.0, 1.5, 0.0};
    r.bodies = {floor, ball};

    const auto live = LiveWorld::open(r);
    double lowest = 1.5, apex = -1.0;
    bool rising = false;
    for (int i = 0; i < 960 && apex < 0.0; ++i) {
        live->step(1.0 / 240.0);
        // Decline whatever asks to break, so the clock cannot stop and there is
        // still a ball to measure.
        //
        // This is a question about bouncing, and answering it needs the ball to
        // survive the landing. Concrete can be broken by a 1.5 m drop onto
        // concrete -- its tensile strength is 3 MPa and its threshold is
        // 0.71 m/s -- so letting the breaks through left no ball at all and the
        // bounce read as zero. Declining is a real answer a host can give, and
        // it is the right one here: the contact is then resolved by the rigid
        // solver with its restitution, which IS the thing being measured.
        for (const std::string &name : live->breakable()) live->declineBreak(name);
        for (const LiveBodyPose &pose : live->poses(false)) {
            if (pose.name != "ball") continue;
            lowest = std::min(lowest, pose.position_m.y);
            if (pose.velocity_m_s.y > 0.05) rising = true;
            else if (rising && pose.velocity_m_s.y <= 0.0) apex = pose.position_m.y;
        }
    }
    if (apex < 0.0) return 0.0;
    return std::max(0.0, apex - lowest) / (1.5 - lowest);
}

// What a thing is made of decides how it comes off the floor.
//
// It did not. Every body in a live world was handed one combined contact
// material -- the scene's default matter against the ground -- so a rubber ball
// and an iron ball left the floor at exactly the same height: 29.5 mm for all
// eight materials in the catalogue, to the millimetre. That is not a
// coincidence, it is one number being used eight times.
//
// The fracture threshold two lines from the same place already took the struck
// body's OWN material, with a comment about a glass pin and an oak lane not
// breaking at the same speed. They do not bounce the same either.
void whatAThingIsMadeOfDecidesHowItBounces() {
    const double rubber = bounceFraction(MaterialPreset::Rubber);
    const double concrete = bounceFraction(MaterialPreset::Concrete);
    const double ice = bounceFraction(MaterialPreset::Ice);
    const double glass = bounceFraction(MaterialPreset::Glass);
    std::cout << "  off concrete, as a fraction of the fall: rubber " << rubber
              << ", ice " << ice << ", glass " << glass << ", concrete " << concrete << "\n";

    require(rubber > 0.05, "a rubber ball did not bounce off a concrete floor at all");
    require(concrete > 0.05, "a concrete ball did not bounce at all");
    // Rubber is the least damped thing in the catalogue at 0.05 and concrete
    // the most at 0.30, so this ordering is the catalogue showing through
    // rather than a number anyone picked.
    require(rubber > concrete * 1.5,
            "rubber and concrete bounce the same, so the contact is not taking "
            "the body's own material");
    require(ice > glass, "ice is more compliant than glass and should keep more of its fall");
    // The one that would have passed before the fix is this failing: every
    // material giving the same answer.
    require(std::abs(rubber - concrete) > 1.0e-3 && std::abs(ice - glass) > 1.0e-3,
            "two different materials bounced identically");
}

// A thing can come out of a collision in one piece and a different shape.
//
// It could not before. A body was rebuilt only when it came APART: the run put
// it back into the lattice, worked out what happened, and then, if it was still
// one connected piece, threw the result away and left the authored sphere
// exactly as it was. So an engine of real matter could show you a thing intact
// or a thing in bits, and nothing in between -- no dent, no crumple, no
// flattened side. Which is most of what actually happens to objects.
//
// Now a body that is still one piece but is no longer the shape it was gets
// rebuilt from where its matter ended up. That makes it a hull, because its
// cells ARE its surface once it has been deformed and no sphere describes it.
// The bar for "no longer the shape it was" is a tenth of a cell of permanent
// set, or bonds lost inside it; below that, rebuilding would turn every
// authored sphere into a hull the first time it landed hard.
// Drop one ball of one material onto the floor and report what became of it.
struct Landing {
    std::string outcome;
    double hit{}, break_speed{}, dent_speed{};
    std::size_t pieces{};
};

Landing dropOnFloor(MaterialPreset material, double speed) {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = benchBackend();
    r.plasticity = true;   // nothing can hold a shape it was pushed into without it
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = material;
    ball.dimensions_m = {0.1, 0.1, 0.1};
    ball.center_m = {0.0, 0.30, 0.0};
    ball.velocity_m_s = {0.0, -speed, 0.0};
    r.bodies = {ball};

    const auto live = LiveWorld::open(r);
    Landing out;
    out.outcome = "held";
    for (int i = 0; i < 288; ++i) {
        live->step(1.0 / 960.0);
        for (const LiveImpact &impact : live->impacts(0.2))
            if (impact.struck.rfind("ball", 0) == 0 && impact.closing_speed_m_s > out.hit) {
                out.hit = impact.closing_speed_m_s;
                out.break_speed = impact.threshold_speed_m_s;
                out.dent_speed = impact.dent_speed_m_s;
            }
        for (const std::string &name : live->breakable()) {
            live->fracture(name);
            if (name.rfind("ball", 0) != 0) continue;
            switch (live->lastOutcome()) {
            case LiveOutcome::Broke: out.outcome = "broke"; break;
            case LiveOutcome::Dented: out.outcome = "dented"; break;
            case LiveOutcome::Held: out.outcome = "held"; break;
            default: break;
            }
        }
    }
    for (const LiveBodyPose &pose : live->poses(false))
        if (pose.name.rfind("ball", 0) == 0) ++out.pieces;
    return out;
}

// Hitting the floor is something that happens to things.
//
// It could not be. A contact with the support surface was dropped before it
// was ever reported -- the collector returned early on any pair involving the
// floor -- so it was never judged, the lattice never ran, and nothing could be
// damaged by being dropped. The line in this engine that names an impact's
// other side "the ground" was unreachable.
// A glass pane bridged between two piers, with a ball above it.
TileImpactRequest paneAndBall(double fall_m) {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = benchBackend();
    SceneBody left, right, pane, ball;
    left.name = "left pier";
    left.shape = BodyShape::Box;
    left.material = MaterialPreset::Iron;
    left.dimensions_m = {0.08, 0.40, 0.20};
    left.center_m = {-0.26, 0.20, 0.0};
    left.anchored = true;
    right = left;
    right.name = "right pier";
    right.center_m = {0.26, 0.20, 0.0};
    pane.name = "pane";
    pane.shape = BodyShape::Box;
    pane.material = MaterialPreset::Glass;
    pane.dimensions_m = {0.60, 0.02, 0.20};
    pane.center_m = {0.0, 0.41, 0.0};
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.12, 0.12, 0.12};
    ball.center_m = {0.0, 0.42 + 0.06 + fall_m, 0.0};
    r.bodies = {left, right, pane, ball};
    return r;
}

// The world can see a collision coming, and writes down every time it waited.
//
// Working out a fracture costs between a third of a second and a second, and
// that is irreducible: enabling the energy plateau gives 41 pieces where the
// full run gives 83, the calm exit fires during the approach and nothing breaks
// at all, a shorter window gives 63, a smaller host step costs MORE because the
// shards each pay a full window, and the GPU lane is ten times slower because
// the island schedule is one block. Every way of making the run shorter changes
// the answer or costs more.
//
// So the run has to start before it is needed, and that needs warning. The
// warning has to be measured against the ARRIVAL speed, not the present one: a
// ball a metre up is barely moving and fails every admission test, and by the
// time its current speed clears the bar it is nine milliseconds from the thing
// it is about to break. That is what this pins.
// The world does not stop to work out a fracture.
//
// It used to. The run costs a third of a second to a second and the caller sat
// through all of it -- and because the caller is the thing driving time, the
// whole room stopped: other objects, the camera, walking about. That is the
// pause somebody watching actually complains about, and it is not the physics,
// it is who is made to wait for it.
//
// Now the run goes onto a worker and the world carries on. The pair that is
// about to break is pinned where it is, because letting it carry on means it
// bounces off something that is in fact shattering and has to be put back when
// the answer lands -- measured, an iron ball arcs half a metre up and comes
// down again in the time the run takes, which is a worse thing to watch than
// the wait it replaced.
void theWorldKeepsRunningWhileAFractureIsWorkedOut() {
    const auto live = LiveWorld::open(paneAndBall(3.0));
    // Foresight off, deliberately. This is about the run that HAS to happen at
    // the moment of contact -- something thrown from close range, a piece
    // landing on another piece, anything the ray did not see coming. When the
    // collision is foreseen there is no wait to keep running through, which is
    // a different test.
    live->foreseeCollisions(0.0);
    // Something else entirely, to prove the rest of the room still moves.
    // (The scene's own ball is the one that will be pinned.)
    const auto whereIs = [&](const std::string &what) {
        for (const LiveBodyPose &pose : live->poses(false))
            if (pose.name == what) return pose.position_m;
        return Vec3{0.0, -999.0, 0.0};
    };

    bool started = false;
    double clock_when_started = 0.0;
    int steps_while_working = 0;
    std::size_t pieces = 0;
    Vec3 pinned_at{}, pinned_after{};

    // Long enough in WALL time, not just step count. The world runs far faster
    // than real time -- nine hundred steps go by in about seventy milliseconds
    // -- so a loop counted in steps finishes long before a run that takes a
    // quarter of a second. A live host paces on elapsed time and has no such
    // problem; a test stepping as fast as it can does.
    //
    // So once the run is going the loop is PACED, the way a host paces -- a
    // step, then a wait -- and bounded by a minute of wall clock rather than by
    // a count of steps. Spinning the world as fast as it would go took the
    // cores the run needed: on GitHub's runner 19,811 steps went by with the
    // run still going, and it read as a pane that would not break.
    const auto give_up = std::chrono::steady_clock::now() + std::chrono::seconds(60);
    for (int i = 0; (!started || live->fracturePending()) &&
                    std::chrono::steady_clock::now() < give_up;
         ++i) {
        live->step(1.0 / 240.0);
        if (!started) {
            if (i > 20000) break;           // it was never going to break
            const std::vector<std::string> waiting = live->breakable();
            if (!waiting.empty()) {
                started = live->beginFracture(waiting.front());
                if (started) {
                    clock_when_started = live->time_s();
                    pinned_at = whereIs(live->fractureSubject());
                }
            }
            continue;
        }
        if (live->fracturePending()) {
            ++steps_while_working;
            if (!live->fractureReady()) {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
                continue;
            }
            pinned_after = whereIs(live->fractureSubject());
            pieces = live->finishFracture();
        }
    }

    double blocked_ms = 0.0, held_ms = 0.0;
    for (const LiveDelay &delay : live->delays()) {
        if (std::string(delay.kind) == "blocked") blocked_ms += delay.cost_ms;
        if (std::string(delay.kind) == "precomputed") held_ms += delay.cost_ms;
    }
    std::cout << "  the world took " << steps_while_working
              << " steps while the fracture was worked out (" << held_ms
              << " ms of computing), and broke it into " << pieces << " pieces\n";

    require(started, "the fracture never started, so this proves nothing");
    require(pieces > 1, "it did not break, so there was nothing to work out");
    // The whole point: time moved while the answer was being worked out.
    require(steps_while_working > 10,
            "the world took almost no steps while the fracture ran, so it was "
            "waiting for it after all");
    require(live->time_s() > clock_when_started,
            "the clock did not move while the fracture was worked out");
    // And nothing was BLOCKED: every millisecond of computing was spent off the
    // caller's thread.
    require(blocked_ms == 0.0,
            "something still blocked the caller, so the run is not off the "
            "thread that drives time");
    require(held_ms > 1.0, "no computing was recorded at all");
    // The thing being worked out stayed put rather than carrying on.
    require(std::abs(pinned_after.y - pinned_at.y) < 0.02,
            "the object being worked out moved while it was pinned, so it will "
            "have to be put back when the answer lands");
}

// The clock does not stop because a SECOND thing wants to break.
//
// Taking the fracture off the caller's thread was not enough, and the way it
// failed was invisible: nothing blocked, no fracture took longer, and the room
// still lurched. A break the world has not resolved is a step it will not take
// -- that is the handshake, and it is right when the host can answer. It is not
// right when a run is already going, because asking for a second fracture then
// gets nothing back, so nobody can resolve it and the world sits at one instant
// for as long as the first run takes.
//
// Measured in the owner's own session before this: 756 ms of wall clock in
// which the world advanced 0 ms, and again 750 ms in which it advanced 10 ms,
// inside one cascade that came out at 40% of real time with every delay in the
// log reading "precomputed".
//
// So a break that arrives mid-run is captured where it is detected -- the
// rolled-back step, the only state that still has the closing speed in it --
// and queued. Preparing is a copy; it is the run that costs a third of a
// second.
void aSecondBreakDoesNotStopTheClock() {
    // Driven the way the room drives it: whenever something is breakable and
    // nothing is being worked out, ask. That is what produces the cascade --
    // a pane comes apart, its pieces land, and they want to break too, which is
    // the only way a second break ever turns up while the first is running.
    const auto live = LiveWorld::open(paneAndBall(3.0));
    // Foresight off: a cascade of pieces landing on pieces is exactly what it
    // cannot see coming, and this is about what happens when it does not.
    live->foreseeCollisions(0.0);
    int steps_pending = 0, steps_pending_that_moved = 0;
    int fractures = 0;
    // The symptom, measured the way it is felt: the longest UNBROKEN run of
    // steps that left the clock exactly where it was. A share of steps that
    // moved is not enough to catch this -- most fractures in this scene are
    // milliseconds, so the share stays near one even with the clock stopping,
    // and a test asserting on it passes with the fault in. It is the length of
    // a single stall that is seen, and before this it was the whole run.
    int stall = 0, longest_stall = 0;

    // Runs until a second break has actually been through, not for a fixed
    // number of steps.
    //
    // This loop steps as fast as the machine will let it, and a fracture takes
    // most of a second of WALL clock -- so a step budget is a race against the
    // worker, and on a busy machine the budget runs out first and the test
    // reports "nothing ever broke". It did that, intermittently, which is worse
    // than failing: it passes often enough to be believed.
    for (int i = 0; i < 200000 && fractures < 3; ++i) {
        const double before = live->time_s();
        live->step(1.0 / 240.0);
        const bool moved = live->time_s() > before;

        if (live->fracturePending()) {
            ++steps_pending;
            steps_pending_that_moved += moved ? 1 : 0;
            stall = moved ? 0 : stall + 1;
            longest_stall = std::max(longest_stall, stall);
            if (live->fractureReady()) { live->finishFracture(); ++fractures; }
            continue;
        }
        stall = 0;
        const std::vector<std::string> waiting = live->breakable();
        if (!waiting.empty()) live->beginFracture(waiting.front());
    }

    std::size_t captured = 0;
    for (const LiveDelay &delay : live->delays())
        if (std::string(delay.kind) == "queued") ++captured;

    std::cout << "  " << fractures << " fractures; " << captured
              << " later breaks captured rather than waited on; longest stall "
              << longest_stall << " steps (" << steps_pending_that_moved << " of "
              << steps_pending << " pending steps moved the clock)\n";

    require(fractures > 1, "only one thing ever broke, so no second break can have "
                           "arrived mid-run and this proves nothing");
    require(steps_pending > 50, "nothing was pending for long enough to tell");
    // This is the situation the fix exists for. If it never arose, the numbers
    // below are meaningless and saying so is better than a green tick.
    require(captured > 0,
            "no break ever arrived while another was being worked out, so this "
            "test did not exercise what it claims to");
    // The whole point. A break is captured in the step that detects it, and
    // that step is taken back -- so one stalled step is the floor, and anything
    // past a handful is the world waiting out somebody else's run.
    require(longest_stall <= 4,
            "the clock stood still for " + std::to_string(longest_stall) +
            " steps in a row while a fracture was pending, which is the lurch "
            "this is here to catch");
}

struct ForeseenDrop { double lead_ms, cost_ms; std::string object; bool foreseen, blocked; };

// A pane and a ball dropped from `fall` onto it, watched for 1.8 s by a world
// that looks 4 s ahead: what it foresaw, with how much warning, and what the
// run it started on the back of that warning cost.
ForeseenDrop watchADrop(double fall) {
    const auto live = LiveWorld::open(paneAndBall(fall));
    live->foreseeCollisions(4.0);
    for (int i = 0; i < 432; ++i) {   // 1.8 s at 1/240
        live->step(1.0 / 240.0);
        for (const std::string &name : live->breakable()) live->fracture(name);
    }
    ForeseenDrop out{0.0, 0.0, "", false, false};
    for (const LiveDelay &delay : live->delays()) {
        const std::string kind(delay.kind);
        // The warning, which carries how much lead there was.
        if (kind == "foreseen" && delay.cost_ms == 0.0 && !out.foreseen) {
            out.foreseen = true;
            out.lead_ms = delay.lead_ms;
            out.object = delay.object;
        }
        // The run that was started on the back of it and then used. Its
        // cost is what the warning had to cover.
        if (kind == "foreseen" && delay.cost_ms > 0.0) out.cost_ms = delay.cost_ms;
        if (kind == "blocked" && !out.blocked) out.blocked = true;
    }
    return out;
}

void theWorldSeesACollisionComing() {
    // 0.2 m, not 0.5: glass breaks at the 45 MPa EN 572-1 gives annealed float
    // now rather than at twice that strain, so its bar halved to 2.25 m/s and
    // a half-metre drop arrives at 3.1 -- worth foreseeing, which is the
    // opposite of what this half of the pair is for.
    const ForeseenDrop gentle = watchADrop(0.2);
    const ForeseenDrop fair = watchADrop(1.5);
    const ForeseenDrop high = watchADrop(6.0);
    std::cout << "  1.5 m: " << fair.lead_ms << " ms warning on " << fair.object
              << ", first run cost " << fair.cost_ms << " ms\n"
              << "  6.0 m: " << high.lead_ms << " ms warning on " << high.object
              << ", first run cost " << high.cost_ms << " ms\n";

    // Nothing is coming when nothing will break. A warning about every contact
    // would be a running commentary and no use for deciding anything.
    require(!gentle.foreseen, "a drop too gentle to break anything was still foreseen");
    require(!gentle.blocked, "a drop too gentle to break anything still ran the lattice");

    // What is about to be BROKEN is named, not what is about to do it. The
    // lattice runs on the pane.
    require(fair.foreseen, "a drop that breaks the pane was not seen coming at all");
    require(fair.object == "pane", "the warning named " + fair.object + " and not the pane");

    // And the warning has to be worth having: longer than the run it covers.
    // This is no longer hypothetical -- the run is actually started on the back
    // of the warning and finished before the two things touch, so what proves
    // it is that NOTHING blocked. A caller that waited is a warning that was
    // not acted on, or not long enough to be worth acting on.
    require(fair.cost_ms > 0.0,
            "the warning did not start the run, so looking ahead bought nothing");
    require(high.lead_ms > fair.lead_ms,
            "a longer fall did not give more warning, so the lead is not being "
            "worked out from the approach at all");
    // Whether the run is FINISHED inside the warning is a claim about the
    // machine as much as the engine, and is checked on its own:
    // theDeadlineIsMet.
}

#if defined(_MSC_VER) && !defined(__clang__)
#define BANJO_LIVE_WORLD_STRING2(x) #x
#define BANJO_LIVE_WORLD_STRING(x) BANJO_LIVE_WORLD_STRING2(x)
constexpr const char *kCompiler = "MSVC " BANJO_LIVE_WORLD_STRING(_MSC_FULL_VER);
#elif defined(__clang__)
constexpr const char *kCompiler = "Clang " __clang_version__;
#elif defined(__GNUC__)
constexpr const char *kCompiler = "GCC " __VERSION__;
#else
constexpr const char *kCompiler = "a compiler this does not name";
#endif
#ifdef BANJO_FP_PROFILE
constexpr const char *kProfile = BANJO_FP_PROFILE;
#else
constexpr const char *kProfile = "(none)";
#endif

// Whether a foreseen fracture's first run is finished inside its warning. The
// lattice runs on every core there is, up to 16, and the warning is set by the
// fall, so this is a claim about the machine as much as the engine. On this
// project's 24-thread desktop it holds with room to spare. On a four-core CI
// runner a 1.5 m fall's 485 ms of warning does not cover a 1082 ms run
// (measured, GCC, four cores), and nothing in the engine can make it. Beside
// other heavy work it fails on any build (docs/floating-point-model.md). So it
// runs on its own -- `banjo_live_world_tests --deadline`, ctest's
// banjo_live_world_deadline, labelled performance and run serially -- and says
// the margin, cold and warm, and what it ran on. The requirement is unchanged:
// the first run in a fresh world, started on the way down, done before contact.
void theDeadlineIsMet() {
    const unsigned threads = std::thread::hardware_concurrency();
    const unsigned lattice = threads < 1U ? 1U : (threads > 16U ? 16U : threads);
    std::cout << "  on " << threads << " hardware threads (the lattice uses " << lattice << "), "
              << kCompiler << ", profile " << kProfile << "\n";
    const ForeseenDrop gentle = watchADrop(0.2);   // as the suite runs it: nothing breaks first
    const ForeseenDrop cold = watchADrop(1.5);     // the first run the process makes
    const ForeseenDrop high = watchADrop(6.0);
    const ForeseenDrop warm = watchADrop(1.5);     // the same drop again, the process warm
    const auto say = [](const char *what, const ForeseenDrop &seen) {
        std::cout << "  " << what << ": " << seen.lead_ms << " ms of warning, the run took "
                  << seen.cost_ms << " ms: margin " << seen.lead_ms - seen.cost_ms << " ms"
                  << (seen.blocked ? " (still blocked at contact)" : "") << "\n";
    };
    say("1.5 m, cold", cold);
    say("6.0 m", high);
    say("1.5 m, warm", warm);
    require(!gentle.foreseen, "a drop too gentle to break anything was still foreseen");
    require(cold.foreseen && cold.cost_ms > 0.0, "the 1.5 m drop was not foreseen, or its run never started");
    if (threads < 8) {
        std::cout << "  not checked here: whether the run is done inside the warning needs a "
                     "machine that can run the lattice in time, and this one has "
                  << threads << " hardware threads\n";
        return;
    }
    require(!cold.blocked,
            "something still blocked at the moment of contact, so the run that "
            "was started on the way down was not ready in time");
    require(cold.lead_ms > cold.cost_ms,
            "the warning is shorter than the run it would have to cover, so there "
            "is no time to work the fracture out before it is needed");
}

// The bench room's 20 mm glass plate (playground/world_room.py): 240 x 160 mm,
// bridged between two short iron piers and unsupported between them, with the
// room's 120 mm iron ball lying on the floor beside it. The room asks for
// plasticity, which is what lets an iron ball dent.
TileImpactRequest plateOnPiers() {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = benchBackend();
    r.plasticity = true;
    for (const double x : {-0.1, 0.1}) {
        SceneBody pier;
        pier.name = x < 0.0 ? "left pier" : "right pier";
        pier.shape = BodyShape::Box;
        pier.material = MaterialPreset::Iron;
        pier.dimensions_m = {0.04, 0.12, 0.16};
        pier.center_m = {x, 0.06, 0.0};
        pier.anchored = true;
        r.bodies.push_back(pier);
    }
    SceneBody plate;
    plate.name = "plate";
    plate.shape = BodyShape::Box;
    plate.material = MaterialPreset::Glass;
    plate.dimensions_m = {0.24, 0.02, 0.16};
    plate.center_m = {0.0, 0.13, 0.0};
    r.bodies.push_back(plate);
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.12, 0.12, 0.12};
    ball.center_m = {0.6, 0.06, 0.0};
    r.bodies.push_back(ball);
    return r;
}

// What came of dropping the ball on the plate.
struct PlateDrop {
    LiveImpact hardest{};     // the hardest the plate was hit
    std::size_t pieces{};     // what the plate is in now
    bool ball_whole{};        // the ball is still there, under its own name
    bool ball_broke{};        // and nothing came off it
};

// Dropped the way the bench room drops it (tests/threshold_tests.py drop()):
// picked up, held `fall_m` above the plate, let go, and stepped at 1/120 s in
// batches of four, a batch stopping at a step taken back unless something is
// already being worked out. Whatever is breakable is asked about, first name
// first, without waiting, and each answer is collected in the batch after it is
// ready -- which is what the live runner does with the room's commands.
// Foresight is left on, as the room leaves it.
PlateDrop dropOntoThePlate(double fall_m) {
    const auto live = LiveWorld::open(plateOnPiers());
    require(live->grab("ball"), "the ball could not be picked up");
    live->moveHeld({0.0, 0.13 + fall_m, 0.0});
    live->step(1.0 / 240.0);
    live->release();
    PlateDrop out;
    // Two seconds of room clock is well past the landing. After that only an
    // answer still being worked out keeps it going, paced in wall time the way
    // theWorldKeepsRunningWhileAFractureIsWorkedOut is, so that spinning the
    // world does not take the cores the run needs.
    const auto give_up = std::chrono::steady_clock::now() + std::chrono::seconds(60);
    while ((live->time_s() < 2.0 || live->fracturePending()) &&
           std::chrono::steady_clock::now() < give_up) {
        live->forgetImpacts();
        for (int s = 0; s < 4; ++s) {
            live->step(1.0 / 120.0);
            if (live->steppedBack() && !live->fracturePending()) break;
        }
        for (const LiveImpact &impact : live->impacts())
            if (impact.struck == "plate" && impact.closing_speed_m_s > out.hardest.closing_speed_m_s)
                out.hardest = impact;
        if (live->fracturePending()) {
            if (live->fractureReady()) live->finishFracture();
            else std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        if (live->fracturePending()) continue;
        const std::vector<std::string> waiting = live->breakable();
        if (!waiting.empty()) static_cast<void>(live->beginFracture(waiting.front(), 0.003));
    }
    for (const LiveBodyPose &pose : live->poses(false)) {
        if (pose.name.rfind("plate piece", 0) == 0) ++out.pieces;
        if (pose.name == "ball") out.ball_whole = true;
        if (pose.name.rfind("ball piece", 0) == 0) out.ball_broke = true;
    }
    return out;
}

// A drop that breaks the plate breaks it whatever the phase of the step it
// lands in.
//
// From 6 m the ball arrives at about 10.8 m/s against the plate's 4.51 m/s bar
// and the contact says it would break -- and it came apart into anything from
// nothing to sixty-seven pieces according to where in a 1/120 s step the ball
// met the plate: 8 from 5.99 m, none from 6.00 m, 67 from 6.02 m. Every run for
// that contact started with the ball's cells 75 mm above the ball, left there
// by the run foreseen for the same drop (see LiveWorld::prepared), so whether
// the ball reached the plate inside the run's window was down to the phase.
// And at the phases where the rigid step had already carried the ball into the
// plate, a run started from that overlap broke the ball as well: in the room,
// 5.955 m left the plate in 62 pieces and the iron ball in 23.
// One step's travel at that speed is 90 mm of fall, so six drops 15 mm apart
// cover every phase there is.
void aDropBreaksThePlateWhateverThePhaseOfTheStep() {
    for (int k = 0; k < 6; ++k) {
        const double fall = 5.925 + 0.015 * k;
        const PlateDrop drop = dropOntoThePlate(fall);
        std::cout << "  dropped " << fall << " m: the plate hit at "
                  << drop.hardest.closing_speed_m_s << " m/s against a "
                  << drop.hardest.threshold_speed_m_s << " m/s bar, now in " << drop.pieces
                  << " pieces\n";
        const std::string from = "dropped from " + std::to_string(fall) + " m, ";
        // The premise: a contact that is well past the bar and says so.
        require(drop.hardest.would_break && drop.hardest.closing_speed_m_s > 10.0,
                from + "the ball never hit the plate hard enough to break it, so this "
                       "proves nothing");
        require(drop.pieces > 1,
                from + "the ball hit the plate at " +
                    std::to_string(drop.hardest.closing_speed_m_s) + " m/s against its " +
                    std::to_string(drop.hardest.threshold_speed_m_s) +
                    " m/s bar, the contact said it would break, and it did not");
        require(drop.ball_whole && !drop.ball_broke,
                from + "the ball came apart breaking the plate");
    }
}

// A single cell of glass lying on the floor, and the room's iron ball above it.
TileImpactRequest ballOverAChip(double drop_m) {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = benchBackend();
    r.plasticity = true;
    SceneBody chip;
    chip.name = "chip";
    chip.shape = BodyShape::Box;
    chip.material = MaterialPreset::Glass;
    chip.dimensions_m = {0.02, 0.02, 0.02};
    chip.center_m = {0.0, 0.01, 0.0};
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.12, 0.12, 0.12};
    ball.center_m = {0.0, 0.02 + 0.06 + drop_m, 0.0};
    r.bodies = {chip, ball};
    return r;
}

// A body asked about because a contact would only dent it comes out dented,
// never in pieces.
//
// A single cell of glass has no bonds and cannot break, so on the floor it is a
// punch. An iron ball driven onto one at 13.5 m/s is past its 10 m/s denting
// bar against glass and short of its 25 m/s breaking one, so the ball is what
// the world asks about -- and it was let come apart in its own run whatever it
// had been asked about: twelve pieces here. That is the page's iron ball landing
// on a shard of the plate it had just broken, which came out of its run in two
// to eight pieces while the page said it breaks above 25 m/s. A threshold is
// the speed below which nothing CAN happen (see LiveWorld::prepared).
void aBodyAskedAboutForADentIsNotBroken() {
    const auto live = LiveWorld::open(ballOverAChip(9.3));
    // The chip's contact with the ball. The ball can meet the floor in the same
    // step, at the same closing speed but against the floor's bars, and that is
    // not the contact this is about.
    LiveImpact hit{};
    std::size_t asked = 0, answer = 0;
    for (int i = 0; i < 960; ++i) {   // 4 s at 1/240
        live->step(1.0 / 240.0);
        for (const LiveImpact &impact : live->impacts())
            if (impact.struck == "ball" && impact.by == "chip" &&
                impact.closing_speed_m_s > hit.closing_speed_m_s)
                hit = impact;
        for (const std::string &name : live->breakable()) {
            const std::size_t pieces = live->fracture(name);
            if (name == "ball") { ++asked; answer = pieces; }
        }
    }
    bool whole = false, broke = false;
    for (const LiveBodyPose &pose : live->poses(false)) {
        if (pose.name == "ball") whole = true;
        if (pose.name.rfind("ball piece", 0) == 0) broke = true;
    }
    std::cout << "  iron ball onto a glass cell: hit at " << hit.closing_speed_m_s
              << " m/s, dents above " << hit.dent_speed_m_s << ", breaks above "
              << hit.threshold_speed_m_s << "; asked about " << asked << " time(s), last answer "
              << answer << " piece(s); the ball " << (whole && !broke ? "whole" : "in pieces") << "\n";
    // The premise: the chip hit the ball over its denting bar and under its
    // breaking one, and the world asked about the ball.
    require(hit.would_dent && !hit.would_break,
            "the chip's contact with the ball was not a dent-only one (" +
                std::to_string(hit.closing_speed_m_s) + " m/s, dents above " +
                std::to_string(hit.dent_speed_m_s) + ", breaks above " +
                std::to_string(hit.threshold_speed_m_s) + "), so this proves nothing");
    require(asked > 0, "the ball was never asked about, so its own run never happened");
    require(whole && !broke,
            "the iron ball came apart on a contact under its own breaking bar (" +
                std::to_string(hit.closing_speed_m_s) + " m/s against " +
                std::to_string(hit.threshold_speed_m_s) + ")");
}

void landingOnTheFloorIsAnImpact() {
    const Landing hard = dropOnFloor(MaterialPreset::Glass, 20.0);
    std::cout << "  glass onto the floor at 20 m/s: hit at " << hard.hit
              << " m/s, " << hard.outcome << " into " << hard.pieces << " pieces\n";
    require(hard.hit > 15.0, "landing on the floor was not reported as an impact at all");
    require(hard.outcome == "broke", "a glass ball hit the floor at 20 m/s and survived");
}

// A hard landing breaks the thing whatever the phase of the step it lands in.
//
// The step taken back is the one in which the contact was REPORTED, and at the
// room's 1/120 s a table coming down at 12 m/s has moved 100 mm in it. The
// state handed to the lattice therefore has its feet anywhere from just short
// of the floor to most of a step's travel inside it, by nothing but where in a
// step the floor happened to be. The lattice is started from a lift clear of
// the floor, and used to refuse outright whenever that lift was more than half
// a cell -- the guard against matter that is BURIED, which a body on its way in
// is not. Measured on the Workshop's glass table at 40 mm cells: dropped 4 m
// (8.8 m/s, 14 mm short of the floor at capture) it broke into 40; dropped 6 m
// (10.8 m/s, 25 mm inside) the contact said would_break and the answer was
// "held" with no run made, and the same at 10 and 16 m. A harder hit must not
// be the one that holds.
//
// A table and not a slab: a slab landing flat on a flat floor is loaded evenly
// over its whole face, and its run at 12 m/s against the same 8.7 m/s bar goes
// the full window without a bond failing -- the bar is the speed below which
// nothing CAN happen, not one above which something must. Four legs under a
// top are what the Workshop drops, and they come off.
struct TableLanding {
    LiveImpact hardest;
    std::string outcome{"never asked"};
    std::size_t pieces{};
    int asked{};
};
TableLanding dropAGlassTable(double clearance_m, double speed_m_s) {
    TileImpactRequest r;
    r.cell_size_m = 0.04;
    r.backend = benchBackend();
    r.plasticity = true;
    const double leg = 0.40, across = 0.48;
    const auto glass = [&](const std::string &name, Vec3 size, Vec3 centre) {
        SceneBody part;
        part.name = name;
        part.shape = BodyShape::Box;
        part.material = MaterialPreset::Glass;
        part.dimensions_m = size;
        part.center_m = centre + Vec3{0.0, clearance_m, 0.0};
        part.velocity_m_s = {0.0, -speed_m_s, 0.0};
        part.join = "table";
        return part;
    };
    r.bodies.push_back(glass("table", {across, 0.04, across}, {0.0, leg + 0.02, 0.0}));
    const double at = 0.5 * across - 0.02;
    int n = 0;
    for (const double x : {-at, at})
        for (const double z : {-at, at})
            r.bodies.push_back(glass("table leg " + std::to_string(++n), {0.04, leg, 0.04},
                                     {x, 0.5 * leg, z}));
    const auto live = LiveWorld::open(r);
    TableLanding out;
    for (int i = 0; i < 40 && out.asked == 0; ++i) {
        live->step(1.0 / 120.0);
        for (const LiveImpact &impact : live->impacts(0.2))
            if (impact.struck.rfind("table", 0) == 0 &&
                impact.closing_speed_m_s > out.hardest.closing_speed_m_s)
                out.hardest = impact;
        for (const std::string &name : live->breakable()) {
            if (name.rfind("table", 0) != 0) continue;
            ++out.asked;
            live->fracture(name);
            switch (live->lastOutcome()) {
            case LiveOutcome::Broke: out.outcome = "broke"; break;
            case LiveOutcome::Dented: out.outcome = "dented"; break;
            case LiveOutcome::Held: out.outcome = "held"; break;
            default: out.outcome = "something else"; break;
            }
            break;
        }
    }
    for (const LiveBodyPose &pose : live->poses(false))
        if (pose.name.rfind("table", 0) == 0) ++out.pieces;
    return out;
}
void aHardLandingBreaksItWhateverThePhaseOfTheStep() {
    // 12 m/s is 100 mm a step, and the clearances are whole cells apart (the
    // parts are voxelised where they stand, so anything else moves the shape on
    // its grid): 40 mm at a time walks the floor through a step in fifths --
    // caught 20, 80, 40, 0 and 60 mm in, and round again.
    for (int k = 0; k < 6; ++k) {
        const double clearance = 0.48 + 0.04 * k;
        const TableLanding landing = dropAGlassTable(clearance, 12.0);
        std::cout << "  glass table from " << clearance << " m up at 12 m/s: hit at "
                  << landing.hardest.closing_speed_m_s << " m/s against a "
                  << landing.hardest.threshold_speed_m_s << " m/s bar, " << landing.outcome
                  << ", now in " << landing.pieces << " piece(s)\n";
        const std::string from = "from " + std::to_string(clearance) + " m up, ";
        // The premise: a landing well past the bar that says so, and was asked about.
        require(landing.hardest.would_break &&
                    landing.hardest.closing_speed_m_s > 1.2 * landing.hardest.threshold_speed_m_s,
                from + "the table never landed hard enough to break, so this proves nothing");
        require(landing.asked > 0, from + "the table was never asked about");
        require(landing.outcome == "broke" && landing.pieces > 1,
                from + "the table landed at " + std::to_string(landing.hardest.closing_speed_m_s) +
                    " m/s against its " + std::to_string(landing.hardest.threshold_speed_m_s) +
                    " m/s bar, the contact said it would break, and the answer was \"" +
                    landing.outcome + "\" with " + std::to_string(landing.pieces) + " piece(s)");
    }
}

// A thing bends before it breaks, and the engine can now tell you which.
//
// The trigger only ever asked one question -- can any bond reach its REMOVAL
// threshold -- so the lattice only ever ran at speeds that could break
// something. Everything between yielding and breaking, which for iron on
// concrete is 14 m/s to 36 m/s, was invisible: below the bar the step was not
// even taken back, so an iron ball hammered into the floor came away a perfect
// sphere.
//
// Now the same bound is taken against the yield stretch as well, and a contact
// that can only bend something still stops the step. Which of the two actually
// happens is not predicted -- only running the lattice says.
void aThingBendsBeforeItBreaks() {
    const Landing gentle = dropOnFloor(MaterialPreset::Iron, 10.0);
    const Landing middle = dropOnFloor(MaterialPreset::Iron, 20.0);
    const Landing hard = dropOnFloor(MaterialPreset::Iron, 40.0);
    std::cout << "  iron onto the floor: dents above " << middle.dent_speed
              << " m/s, breaks above " << middle.break_speed << " m/s\n"
              << "    10 m/s -> " << gentle.outcome << ", 20 m/s -> " << middle.outcome
              << ", 40 m/s -> " << hard.outcome << "\n";

    require(middle.dent_speed < middle.break_speed,
            "a thing that can bend should start bending before it starts breaking");
    require(gentle.outcome == "held", "10 m/s should not mark an iron ball");
    require(middle.outcome == "dented",
            "the whole range between yielding and breaking is still invisible");
    require(middle.pieces == 1, "it came apart, so that is a break and not a dent");
    require(hard.outcome == "broke", "40 m/s onto concrete should break an iron ball");
}

// A brittle thing has no bending range at all, and says so.
void somethingBrittleHasNoDentingRange() {
    const Landing glass = dropOnFloor(MaterialPreset::Glass, 20.0);
    const Landing ceramic = dropOnFloor(MaterialPreset::Ceramic, 20.0);
    std::cout << "  glass dents above " << glass.dent_speed << " m/s (breaks above "
              << glass.break_speed << "), ceramic dents above " << ceramic.dent_speed << "\n";
    // Not a large number: no number. Glass and alumina have no yield strength
    // in the catalogue because they have no yield point, and a bound taken
    // against a yield stretch of zero would admit every contact there is.
    require(!std::isfinite(glass.dent_speed), "glass was given a speed at which it bends");
    require(!std::isfinite(ceramic.dent_speed), "ceramic was given a speed at which it bends");
    require(glass.outcome == "broke", "glass hit the floor at 20 m/s and did not break");
    require(glass.pieces > 1, "it broke into one piece, which is not a break");
}

void somethingCanBeDentedWithoutBeingBroken() {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = benchBackend();
    SceneBody anvil;
    anvil.name = "anvil";
    anvil.shape = BodyShape::Box;
    anvil.material = MaterialPreset::Iron;
    anvil.dimensions_m = {0.3, 0.12, 0.3};
    anvil.center_m = {0.0, 0.06, 0.0};
    anvil.anchored = true;
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.1, 0.1, 0.1};
    ball.center_m = {0.0, 0.20, 0.0};
    // Hard enough to bend it and not hard enough to break it: iron against an
    // iron anvil bends above about 4.9 m/s and breaks above 12.3.
    //
    // This used to need 60 m/s, and what happened at 60 was not really a dent:
    // the ball was re-entered on its own with nothing to press against, and
    // what changed its shape was bonds inside it snapping. Anchored scenery is
    // a support plane now, so the ball is squashed against the anvil the way it
    // would be, and it yields at a speed a person could actually produce.
    ball.velocity_m_s = {0.0, -16.0, 0.0};
    r.bodies = {anvil, ball};

    const auto live = LiveWorld::open(r);
    const auto findBall = [&] {
        std::vector<LiveBodyPose> out;
        for (const LiveBodyPose &pose : live->poses(false))
            if (pose.name.rfind("ball", 0) == 0) out.push_back(pose);
        return out;
    };
    const std::vector<LiveBodyPose> before = findBall();
    require(before.size() == 1 && before[0].shape == "sphere",
            "the ball did not start as one sphere");
    const double was = before[0].dimensions_m.x;

    for (int i = 0; i < 288; ++i) {          // 0.6 s at 1/480
        live->step(1.0 / 480.0);
        for (const std::string &name : live->breakable()) live->fracture(name);
    }

    const std::vector<LiveBodyPose> after = findBall();
    require(!after.empty(), "the ball vanished");
    const double now = after[0].dimensions_m.x;
    std::cout << "  iron at 16 m/s onto an anchored iron anvil: " << after.size()
              << " piece(s), " << before[0].shape << " -> " << after[0].shape
              << ", " << was * 1000.0 << " mm across -> " << now * 1000.0
              << " mm, permanent set " << after[0].dent_m * 1000.0 << " mm\n";

    require(after.size() == 1, "it came apart, so this is a break and not a dent");
    require(live->lastOutcome() == LiveOutcome::Dented,
            "the world does not call this a dent, so the shape change came from "
            "somewhere other than the material yielding");
    // A dent is real and it is SMALL. This used to require the ball to be
    // redrawn as a hull of its cells, and to have lost more than a centimetre
    // off its width -- and both passed, which is why it took so long to notice
    // that neither was true.
    //
    // The width was measuring the wrong thing. A sphere's cells never fill its
    // sphere: a 100 mm ball at 20 mm cells has its outermost cell centres well
    // inside the surface, so the extent of its cells is smaller than its
    // diameter BEFORE anything happens to it. The "20 mm of squash" was that
    // gap. Measured properly, against the same cells at rest, this ball is the
    // size it started and its permanent set is a tenth of a millimetre.
    //
    // So what is asserted is what is true: it yielded, the set is real and
    // sub-millimetre, and it is still drawn as the ball it is -- because a
    // 136-cube staircase would show none of that and would lose the rolling
    // besides.
    require(after[0].shape == "sphere",
            "a ball with a tenth of a millimetre of permanent set was redrawn out "
            "of its cells, which shows no dent and costs it the rolling");
    require(after[0].dent_m > 0.0,
            "the world called this a dent and recorded no permanent set, so there "
            "is nothing a host could show or say");
    require(after[0].dent_m < 0.5 * 0.02,
            "the set is half a cell or more, which would be a real change of "
            "shape -- and then drawing it as the sphere it was IS throwing "
            "something away");
    require(std::abs(was - now) < 1e-6,
            "its authored size changed, so the size being reported is not the "
            "size it was made at");
    // Still a real object afterwards: it has somewhere to be and it can be
    // picked up. A rebuild that produced a body the world cannot use would
    // pass every check above.
    require(after[0].position_m.y > 0.0 && after[0].position_m.y < 1.0,
            "the dented ball ended up somewhere impossible");
    require(live->grab(after[0].name), "the dented ball cannot be picked up");
    live->release();
}

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

// A long plank, built turned, 1 m up, over nothing.
TileImpactRequest turnedPlank(const Vec3 &rotation_deg, bool anchored) {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = benchBackend();
    SceneBody plank;
    plank.name = "plank";
    plank.shape = BodyShape::Box;
    plank.material = MaterialPreset::Oak;
    plank.dimensions_m = {1.0, 0.1, 0.2};
    plank.center_m = {0.0, 1.0, 0.0};
    plank.rotation_deg = rotation_deg;
    plank.anchored = anchored;
    r.bodies = {plank};
    return r;
}

Quat quatOf(const double wxyz[4]) { return Quat{wxyz[0], wxyz[1], wxyz[2], wxyz[3]}; }

double degreesBetween(const Quat &a, const Quat &b) {
    const double d = std::abs(a.w * b.w + a.x * b.x + a.y * b.y + a.z * b.z);
    return 2.0 * std::acos(std::min(1.0, d)) * 180.0 / std::acos(-1.0);
}

// Where a ray straight down from (x, 5, z) meets the box of `dims` turned by
// q about c, grown by `grow` on every side: its height, or NaN for a miss.
double topOfBox(const Vec3 &c, const Vec3 &dims, const Quat &q, double x, double z,
                double grow) {
    const Quat back{q.w, -q.x, -q.y, -q.z};
    const Vec3 o = back.rotate(Vec3{x, 5.0, z} - c);
    const Vec3 d = back.rotate(Vec3{0.0, -1.0, 0.0});
    const double half[3] = {0.5 * dims.x + grow, 0.5 * dims.y + grow, 0.5 * dims.z + grow};
    const double from[3] = {o.x, o.y, o.z}, along[3] = {d.x, d.y, d.z};
    double enter = -1.0e300, leave = 1.0e300;
    for (int k = 0; k < 3; ++k) {
        if (std::abs(along[k]) < 1e-12) {
            if (std::abs(from[k]) > half[k]) return std::nan("");
            continue;
        }
        const double t1 = (-half[k] - from[k]) / along[k], t2 = (half[k] - from[k]) / along[k];
        enter = std::max(enter, std::min(t1, t2));
        leave = std::min(leave, std::max(t1, t2));
    }
    return enter <= leave && leave >= 0.0 ? 5.0 - enter : std::nan("");
}

// A body built turned says so, and is where it says it is.
//
// rotation_deg turns a body z first (rotationQuaternion, qx qy qz), and its
// cells and its collision shape were measured to agree with that exactly. But
// the engine carries that turn inside the collision shape rather than in the
// rigid pose, and until 2026-09-13 poses() said such a body faced no way at
// all: a host drew a plank built at [30, 0, 45] square while it collided
// turned.
void aBodyBuiltTurnedSaysSoAndIsWhereItSays() {
    const Vec3 turn{30.0, 0.0, 45.0};
    const auto live = LiveWorld::open(turnedPlank(turn, true));
    const LiveBodyPose plank = named(live->poses(), "plank");
    double built[4];
    rotationQuaternion(turn, built);
    const Quat said = quatOf(plank.orientation_wxyz);
    require(degreesBetween(said, quatOf(built)) < 1e-6,
            "a plank built at [30, 0, 45] was not said to face that way");
    // The box it says it is, is the box that collides: every ray straight down
    // that meets the box shrunk by a millimetre meets the plank, none that
    // misses the box grown by a millimetre does, and each meets it within a
    // millimetre of that box's top.
    int met = 0;
    for (int a = -60; a <= 60; ++a)
        for (int b = -60; b <= 60; ++b) {
            const double x = 0.01 * a, z = 0.01 * b;
            const LivePick hit = live->pick({x, 5.0, z}, {0.0, -1.0, 0.0}, 10.0);
            const bool on = hit.hit && hit.name == "plank";
            const double inner = topOfBox(plank.position_m, plank.dimensions_m, said, x, z, -0.001);
            const double outer = topOfBox(plank.position_m, plank.dimensions_m, said, x, z, 0.001);
            require(on || std::isnan(inner), "a ray missed the plank inside the box it says it is");
            require(!on || !std::isnan(outer), "a ray met the plank outside the box it says it is");
            if (!on) continue;
            ++met;
            const double top = topOfBox(plank.position_m, plank.dimensions_m, said, x, z, 0.0);
            require(!std::isnan(top) && std::abs(5.0 - hit.distance_m - top) < 1e-3,
                    "a ray met the plank away from the top of the box it says it is");
        }
    std::cout << "  " << met << " rays met the plank, each on the box it says it is\n";
    require(met > 1000, "too few rays met the plank to say anything");
}

// A hand that asks a thing to face the way it is said to face leaves it be.
//
// aimHeld takes an orientation in the frame poses() reports; the hand turns
// the body's rigid frame. Without taking the turn its shape carries off first,
// holding a plank built 35 degrees round "as it is" swings it a further 35.
void aHandHoldingATurnedThingAsItIsDoesNotTurnIt() {
    TileImpactRequest r = turnedPlank({0.0, 35.0, 0.0}, false);
    r.bodies[0].center_m = {0.0, 0.052, 0.0};   // lying flat on the floor
    const auto live = LiveWorld::open(r);
    for (int i = 0; i < 120; ++i) live->step(1.0 / 240.0);
    const LiveBodyPose before = named(live->poses(), "plank");
    const Quat facing = quatOf(before.orientation_wxyz);
    require(live->wield("plank", before.position_m), "the plank could not be taken hold of");
    live->aimHeld(facing);
    live->moveHeld(before.position_m + Vec3{0.0, 0.05, 0.0});
    for (int i = 0; i < 240; ++i) live->step(1.0 / 240.0);
    const double turned = degreesBetween(quatOf(named(live->poses(), "plank").orientation_wxyz),
                                         facing);
    std::cout << "  held facing the way it was said to face, it turned " << turned
              << " degrees\n";
    require(turned < 1.0, "asked to face the way it was said to face, the plank turned");
}

// A box that comes through a run whole keeps its turn.
//
// A body that comes through the lattice whole is rebuilt facing the world's
// own way, its cells where the run left them, and its box was put back square:
// measured, an iron bar built 30 degrees round struck a pane that held and came
// back at -0.8 degrees -- colliding, and drawn, square, with its cells at 30.
void aTurnedBoxThatComesThroughARunKeepsItsTurn() {
    TileImpactRequest r = ballOntoGlass(3.0);
    SceneBody &bar = r.bodies[1];
    bar.name = "bar";
    bar.shape = BodyShape::Box;
    bar.dimensions_m = {0.2, 0.06, 0.06};
    bar.rotation_deg = {0.0, 30.0, 0.0};
    const auto live = LiveWorld::open(r);
    int runs = 0;
    for (int i = 0; i < 720; ++i) {
        live->step(1.0 / 240.0);
        for (const std::string &name : live->breakable()) {
            ++runs;
            (void)live->fracture(name);
        }
    }
    require(runs > 0, "the bar never struck the pane hard enough to be run");
    const LiveBodyPose after = named(live->poses(), "bar");
    require(after.shape == "box", "the bar did not come through whole");
    const Vec3 along = quatOf(after.orientation_wxyz).rotate({1.0, 0.0, 0.0});
    const double heading = std::atan2(-along.z, along.x) * 180.0 / std::acos(-1.0);
    // Nine centimetres out along a bar heading 30 degrees is on it; nine out
    // along x is not -- the bar is six across.
    const auto onBar = [&](double degrees) {
        const double h = degrees * std::acos(-1.0) / 180.0;
        const Vec3 at = after.position_m + 0.09 * Vec3{std::cos(h), 0.0, -std::sin(h)};
        const LivePick hit = live->pick({at.x, at.y + 1.0, at.z}, {0.0, -1.0, 0.0}, 2.0);
        return hit.hit && hit.name == "bar";
    };
    std::cout << "  after " << runs << " run(s): said to head " << heading
              << " degrees; its shape is " << (onBar(30.0) ? "" : "not ") << "along 30 and "
              << (onBar(0.0) ? "" : "not ") << "along 0\n";
    require(std::abs(heading - 30.0) < 5.0, "the bar was said to head another way after its run");
    require(onBar(30.0) && !onBar(0.0), "the bar's collision shape came back square");
}

} // namespace

// Set aside and brought back (LiveWorld::park and unpark): the inventory's bag.
// Parked, a thing is out of the world -- nothing meets it, poses() leaves it
// out, a hand cannot take it -- and unparked it is the same thing, at rest where
// it is put, as heavy and as big as it was, falling and landing again.
void aThingSetAsideComesBackAsItWas() {
    const auto live = LiveWorld::open(ballOverFloor());
    for (int i = 0; i < 240; ++i) live->step(1.0 / 120.0);
    const LiveBodyPose before = named(live->poses(), "ball");
    std::string why;
    require(!live->park("floor", why) && !why.empty(), "anchored scenery was set aside");
    require(live->park("ball", why), "the ball could not be set aside: " + why);
    require(live->parked("ball"), "the world does not say the ball is set aside");
    require(!live->park("ball", why), "a thing set aside was set aside again");
    for (int i = 0; i < 120; ++i) live->step(1.0 / 120.0);
    const auto away = live->poses();
    require(away.size() == 1 && away.front().name == "floor",
            "poses() still lists the ball while it is set aside");
    require(!live->grab("ball"), "a hand took hold of a thing set aside");

    require(live->unpark("ball", {0.1, 0.5, 0.0}, Quat{1.0, 0.0, 0.0, 0.0}, why),
            "the ball could not be brought back: " + why);
    require(!live->parked("ball"), "the ball is still said to be set aside");
    require(!live->unpark("ball", {0.1, 0.5, 0.0}, Quat{1.0, 0.0, 0.0, 0.0}, why),
            "a thing in the world was brought back again");
    const LiveBodyPose back = named(live->poses(), "ball");
    std::cout << "  set aside for 1 s, then back at (" << back.position_m.x << ", " << back.position_m.y
              << ", " << back.position_m.z << "), " << back.mass_kg << " kg (was " << before.mass_kg
              << ")\n";
    require(std::abs(back.position_m.y - 0.5) < 1e-6 && std::abs(back.position_m.x - 0.1) < 1e-6,
            "the ball did not come back where it was put");
    require(std::abs(back.mass_kg - before.mass_kg) < 1e-9, "the ball came back a different weight");
    require(std::abs(back.dimensions_m.x - before.dimensions_m.x) < 1e-12,
            "the ball came back a different size");
    for (int i = 0; i < 240; ++i) live->step(1.0 / 120.0);
    const LiveBodyPose landed = named(live->poses(), "ball");
    std::cout << "  brought back: fell to y=" << landed.position_m.y << "\n";
    require(landed.position_m.y < 0.45, "the ball brought back did not fall");
    require(landed.position_m.y > 0.04, "the ball brought back fell through the floor");

    // In the hand: let go first, then set aside.
    require(live->grab("ball"), "the ball could not be picked up again");
    require(live->park("ball", why), "a held ball could not be set aside: " + why);
    require(live->held().empty(), "the hand still holds a thing set aside");
}

// Set aside hot, and brought back: what it holds -- its heat, what it is made
// of, its fuel -- is exactly what it held when it was put away. Nothing in it
// goes on while it is away: it neither burns nor cools, and a heater aimed at it
// warms nothing. It stays the thermal network's the whole time, on its ledger
// and never counted leaving; and brought back, it burns on.
void aHotThingSetAsideKeepsItsHeat() {
    TileImpactRequest r = ballOverFloor();
    SceneBody &block = r.bodies[1];
    block.name = "block";
    block.shape = BodyShape::Box;
    block.material = MaterialPreset::Oak;
    block.dimensions_m = {0.1, 0.1, 0.1};
    block.center_m = {0.0, 0.09, 0.0};   // resting on the floor's top, at 0.04
    r.thermo_scene_json = R"({"bodies":[{"name":"block","temperature_k":1000}]})";
    const auto live = LiveWorld::open(r);
    for (int i = 0; i < 60; ++i) live->step(1.0 / 120.0);
    require(live->thermo() != nullptr && live->thermo()->holds("block"), "the block was not declared hot");
    const auto lumpOf = [&]() {
        for (const thermo::Lump &lump : live->thermo()->state().lumps)
            if (lump.body == "block") return lump;
        throw std::runtime_error("the network does not hold the block");
    };
    const auto heatOf = [&]() {
        for (const thermo::BodyHeat &heat : live->thermo()->bodies())
            if (heat.body == "block") return heat;
        throw std::runtime_error("the network says nothing of the block");
    };
    // Exactly: nothing may have touched any of it.
    const auto same = [](const thermo::Lump &a, const thermo::Lump &b) {
        return a.surface.kg == b.surface.kg && a.core.kg == b.core.kg &&
               a.surface.internal_energy_j == b.surface.internal_energy_j &&
               a.core.internal_energy_j == b.core.internal_energy_j && a.initial_kg == b.initial_kg &&
               a.peak_surface_k == b.peak_surface_k && a.peak_core_k == b.peak_core_k &&
               a.layer_fuel_kg == b.layer_fuel_kg;
    };
    const thermo::BodyHeat was = heatOf();
    require(was.reacting, "the block at 1000 K was not burning");
    const LiveBodyPose before = named(live->poses(), "block");
    const thermo::Lump put_away = lumpOf();
    const double left_kg = live->thermo()->ledger().left_kg;

    std::string why;
    require(live->park("block", why), "the hot block could not be set aside: " + why);
    require(live->thermo()->holds("block"), "the network let go of the block as it was set aside");
    require(same(lumpOf(), put_away), "setting the block aside changed what it holds");
    (void)live->heat("block", 2000.0, 0.5);
    const double heater_in_j = live->thermo()->ledger().heater_in_j;
    for (int i = 0; i < 120; ++i) live->step(1.0 / 120.0);
    const thermo::BodyHeat away = heatOf();
    require(away.parked && !away.reacting, "the block was said to be burning while it was set aside");
    require(same(lumpOf(), put_away), "what the block holds changed while it was set aside");
    const thermo::Ledger ledger = live->thermo()->ledger();
    require(ledger.left_kg == left_kg, "the block was counted leaving the network as it was set aside");
    require(ledger.heater_in_j == heater_in_j, "a heater warmed the block while it was set aside");
    require(std::abs(ledger.residualJ()) < 1e-9 * std::abs(ledger.storedJ()), "the ledger does not close");

    require(live->unpark("block", {0.15, 0.091, 0.0}, Quat{1.0, 0.0, 0.0, 0.0}, why),
            "the block could not be brought back: " + why);
    require(same(lumpOf(), put_away), "bringing the block back changed what it holds");
    const LiveBodyPose back = named(live->poses(), "block");
    require(std::abs(back.mass_kg - before.mass_kg) < 1e-9, "the block came back a different weight");
    for (int i = 0; i < 60; ++i) live->step(1.0 / 120.0);
    const thermo::BodyHeat again = heatOf();
    std::cout << "  set aside at " << was.temperature_k << " K holding " << 1000.0 * was.fuel_kg
              << " g of fuel; after 1 s away " << away.temperature_k << " K and " << 1000.0 * away.fuel_kg
              << " g; back for 0.5 s, " << again.temperature_k << " K and " << 1000.0 * again.fuel_kg << " g\n";
    require(again.fuel_kg < away.fuel_kg, "the block did not burn on once it was back");
}

// A break is worked out at the step its own lattice needs, whatever else is in
// the room (LiveWorld::prepared). The scene's step is set at open by the
// stiffest, lightest thing anywhere in it. An alumina cup rings about twice as
// fast as iron or glass, and every run in the room used to take its step: the
// same pane broken by the same ball took about twice as many steps with a cup on
// the far side of the room, and the owner's rule is that nothing may run more
// than a tenth slower than real time. Now the run is taken at the same step with
// or without the cup, and takes the same number of steps.
//
// The pieces are not asserted, because the room's other bodies still reach the
// break through the rigid phase before the contact. Measured on this scene, the
// ball arrived at the pane differing in its last digits: its x was 7.1e-19 m
// alone and -2.5e-18 m with an iron block where the cup is. The pane broke into
// 81 pieces alone, 69 with the iron block and 50 with the cup, each the same
// every time. Fracture is chaotic. What this change takes away is the room's
// hold on the step, the part of its influence that cost time.
struct PaneBroken {
    double scene_step_s{}, run_step_s{};
    std::uint64_t run_steps{};
    std::size_t pieces{};
};

PaneBroken breakThePane(bool cup_across_the_room) {
    TileImpactRequest r = paneAndBall(3.0);
    if (cup_across_the_room) {
        SceneBody cup;
        cup.name = "alumina cup";
        cup.shape = BodyShape::Box;
        cup.material = MaterialPreset::Ceramic;
        cup.dimensions_m = {0.10, 0.12, 0.10};
        cup.center_m = {1.5, 0.06, 0.0};
        r.bodies.push_back(cup);
    }
    const auto live = LiveWorld::open(r);
    live->foreseeCollisions(0.0);
    PaneBroken out{};
    out.scene_step_s = live->sceneLatticeStep_s();
    bool started = false;
    const auto give_up = std::chrono::steady_clock::now() + std::chrono::seconds(60);
    for (int i = 0; (!started || live->fracturePending()) && std::chrono::steady_clock::now() < give_up; ++i) {
        live->step(1.0 / 240.0);
        if (!started) {
            if (i > 20000) break;           // it was never going to break
            const std::vector<std::string> waiting = live->breakable();
            if (std::find(waiting.begin(), waiting.end(), "pane") != waiting.end())
                started = live->beginFracture("pane");
            continue;
        }
        if (live->fracturePending()) {
            if (!live->fractureReady()) {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
                continue;
            }
            out.pieces = live->finishFracture();
        }
    }
    for (const LiveDelay &delay : live->delays()) {
        if (delay.steps == 0 || delay.object != "pane") continue;
        out.run_step_s = delay.step_s;
        out.run_steps = delay.steps;
    }
    return out;
}

// ---- a world that is kept: a restart gives back the room as it stood --------
//
// LiveWorld::snapshot, and LiveWorld::open with one: the owner's "a workshop
// that remembers" (2026-09-15). A room where things have been dented, broken,
// swung on a hinge, set aside and taken up, saved and opened again from what
// was saved -- as a playground server started again opens it -- is that room:
// every body where it was and as it was, with its cells, its dent and its name;
// the joint at its angle; the hand holding what it held, by the same grip; what
// was set aside still away. And it goes on from there: what was at rest stays
// put, and what breaks next is new, and named and numbered after what there is.

// Six corners of a room, far enough apart not to meet.
TileImpactRequest workshop(double crate_x = 0.0) {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = benchBackend();
    const auto box = [](const char *name, MaterialPreset material, Vec3 size, Vec3 at, bool anchored = false) {
        SceneBody body;
        body.name = name;
        body.shape = BodyShape::Box;
        body.material = material;
        body.dimensions_m = size;
        body.center_m = at;
        body.anchored = anchored;
        return body;
    };
    const auto ball = [](const char *name, double diameter, Vec3 at, Vec3 velocity = {}) {
        SceneBody body;
        body.name = name;
        body.shape = BodyShape::Sphere;
        body.material = MaterialPreset::Iron;
        body.dimensions_m = {diameter, diameter, diameter};
        body.center_m = at;
        body.velocity_m_s = velocity;
        return body;
    };
    r.bodies = {
        // To be dented: iron at 16 m/s onto an anchored iron anvil
        // (somethingCanBeDentedWithoutBeingBroken).
        box("anvil", MaterialPreset::Iron, {0.3, 0.12, 0.3}, {-1.2, 0.06, 0.0}, true),
        ball("iron ball", 0.1, {-1.2, 0.20, 0.0}, {0.0, -16.0, 0.0}),
        // To be broken: a pane across two piers under a ball that falls 3 m
        // (paneAndBall).
        box("left pier", MaterialPreset::Iron, {0.08, 0.40, 0.20}, {0.94, 0.20, 0.0}, true),
        box("right pier", MaterialPreset::Iron, {0.08, 0.40, 0.20}, {1.46, 0.20, 0.0}, true),
        box("pane", MaterialPreset::Glass, {0.60, 0.02, 0.20}, {1.2, 0.41, 0.0}),
        ball("glass breaker", 0.12, {1.2, 0.42 + 0.06 + 3.0, 0.0}),
        // To swing on a hinge: a door by its post, 20 mm clear of it.
        box("post", MaterialPreset::Oak, {0.06, 1.0, 0.06}, {0.0, 0.5, 1.2}, true),
        box("door", MaterialPreset::Oak, {0.5, 0.8, 0.04}, {0.30, 0.45, 1.2}),
        // To be set aside.
        box("crate", MaterialPreset::Oak, {0.1, 0.1, 0.1}, {crate_x, 0.05, -1.2}),
        // To be given a point and an edge, and taken up.
        box("pick", MaterialPreset::Oak, {0.4, 0.04, 0.04}, {-1.2, 0.02, -1.2}),
        // To be broken once the world has been opened again.
        box("window", MaterialPreset::Glass, {0.3, 0.04, 0.3}, {1.2, 0.02, -1.2}),
    };
    return r;
}

// Steps, answering every break the world offers by working it out there and
// then, as a host that waits for each would.
void stepAnswering(LiveWorld &world, int steps, double dt_s = 1.0 / 240.0) {
    for (int i = 0; i < steps; ++i) {
        world.step(dt_s);
        for (const std::string &name : world.breakable()) (void)world.fracture(name);
    }
}

void requireSame(const Vec3 &a, const Vec3 &b, const std::string &what) {
    require(a.x == b.x && a.y == b.y && a.z == b.z, what + " differs");
}

// Where a saved body's centre of mass was, as the saved world says.
Vec3 rigidPoint(const nlohmann::json &body) {
    const nlohmann::json &at = body.at("pose").at("com_m");
    return {at.at(0).get<double>(), at.at(1).get<double>(), at.at(2).get<double>()};
}

// The same world, as a host sees it: every body by name -- what it is, where,
// how it faces and moves, what it weighs, its cells, dent and cuts -- and the
// joints, the hand, the edges and the points. Exactly, but for two things the
// solver keeps in single precision and works out again: a body's mass, and
// what a pin made again reads.
void requireSameWorld(const LiveWorld &was, const LiveWorld &now, const std::string &what) {
    const std::vector<LiveBodyPose> a = was.poses(true);
    const std::vector<LiveBodyPose> b = now.poses(true);
    require(a.size() == b.size() && was.bodies() == now.bodies(),
            what + ": " + std::to_string(b.size()) + " bodies, not " + std::to_string(a.size()));
    for (const LiveBodyPose &x : a) {
        const LiveBodyPose *y = nullptr;
        for (const LiveBodyPose &pose : b)
            if (pose.name == x.name) y = &pose;
        require(y != nullptr, what + ": the " + x.name + " did not come back");
        const std::string of = what + ": the " + x.name + "'s ";
        require(x.shape == y->shape && x.material == y->material && x.fragment == y->fragment &&
                    x.anchored == y->anchored && x.revision == y->revision && x.color_rgba == y->color_rgba &&
                    x.held == y->held,
                of + "description differs");
        requireSame(x.dimensions_m, y->dimensions_m, of + "size");
        requireSame(x.position_m, y->position_m, of + "place");
        for (int k = 0; k < 4; ++k)
            require(x.orientation_wxyz[k] == y->orientation_wxyz[k], of + "facing differs");
        requireSame(x.velocity_m_s, y->velocity_m_s, of + "velocity");
        require(std::abs(x.mass_kg - y->mass_kg) <= 1e-9 * std::max(1.0, x.mass_kg), of + "mass differs");
        require(x.dent_m == y->dent_m, of + "dent differs");
        requireSame(x.dent_at_m, y->dent_at_m, of + "dent's place");
        require(x.cells_local_m.size() == y->cells_local_m.size(), of + "cells differ in number");
        for (std::size_t k = 0; k < x.cells_local_m.size(); ++k)
            requireSame(x.cells_local_m[k], y->cells_local_m[k], of + "cell " + std::to_string(k));
        require(x.kerfs.size() == y->kerfs.size(), of + "cuts differ in number");
        for (std::size_t k = 0; k < x.kerfs.size(); ++k) {
            const LiveBodyPose::Kerf &p = x.kerfs[k], &q = y->kerfs[k];
            requireSame(p.point_local_m, q.point_local_m, of + "cut");
            requireSame(p.along_local, q.along_local, of + "cut");
            requireSame(p.facing_local, q.facing_local, of + "cut");
            requireSame(p.normal_local, q.normal_local, of + "cut");
            require(p.thickness_m == q.thickness_m && p.strips.size() == q.strips.size(), of + "cut differs");
            for (std::size_t s = 0; s < p.strips.size(); ++s)
                require(p.strips[s].along_from == q.strips[s].along_from &&
                            p.strips[s].along_to == q.strips[s].along_to &&
                            p.strips[s].facing_from == q.strips[s].facing_from &&
                            p.strips[s].facing_to == q.strips[s].facing_to,
                        of + "cut's strips differ");
        }
    }
    const std::vector<LiveJoint> ja = was.joints();
    const std::vector<LiveJoint> jb = now.joints();
    require(ja.size() == jb.size(), what + ": a different number of joints");
    for (std::size_t k = 0; k < ja.size(); ++k) {
        const LiveJoint &p = ja[k], &q = jb[k];
        const std::string of = what + ": joint " + std::to_string(p.id) + " (" + p.kind + ")'s ";
        require(p.id == q.id && p.kind == q.kind && p.a == q.a && p.b == q.b && p.attached == q.attached,
                of + "description differs");
        require(p.lower == q.lower && p.upper == q.upper && p.friction == q.friction, of + "travel differs");
        require(std::abs(p.at - q.at) < 1e-5,
                of + "reading differs: " + std::to_string(p.at) + " against " + std::to_string(q.at));
        requireSame(p.point_world_m, q.point_world_m, of + "point");
        requireSame(p.axis_world, q.axis_world, of + "axis");
        require(p.parted_because == q.parted_because, of + "parting differs");
    }
    const LiveHand ha = was.hand(), hb = now.hand();
    require(ha.holding == hb.holding && ha.mode == hb.mode && ha.work_j == hb.work_j,
            what + ": the hand holds " + hb.holding + " (" + hb.mode + "), not " + ha.holding + " (" + ha.mode + ")");
    requireSame(ha.target_m, hb.target_m, what + ": where the hand wants the grip");
    requireSame(ha.grip_m, hb.grip_m, what + ": the grip");
    const std::vector<LiveBlade> ba = was.blades(), bb = now.blades();
    require(ba.size() == bb.size(), what + ": a different number of edges");
    for (std::size_t k = 0; k < ba.size(); ++k) {
        const LiveBlade &p = ba[k], &q = bb[k];
        const std::string of = what + ": edge " + std::to_string(p.id) + "'s ";
        require(p.id == q.id && p.body == q.body && p.attached == q.attached && p.cut_area_m2 == q.cut_area_m2 &&
                    p.cut_work_j == q.cut_work_j && p.thickness_m == q.thickness_m &&
                    p.edge_radius_m == q.edge_radius_m && p.bevel_deg == q.bevel_deg,
                of + "description differs");
        requireSame(p.heel_local_m, q.heel_local_m, of + "heel");
        requireSame(p.tip_local_m, q.tip_local_m, of + "tip");
        requireSame(p.facing_local, q.facing_local, of + "facing");
        requireSame(p.grip_local_m, q.grip_local_m, of + "grip");
        requireSame(p.heel_m, q.heel_m, of + "heel in the world");
    }
    const std::vector<LiveToolPoint> pa = was.toolPoints(), pb = now.toolPoints();
    require(pa.size() == pb.size(), what + ": a different number of tool points");
    for (std::size_t k = 0; k < pa.size(); ++k) {
        const LiveToolPoint &p = pa[k], &q = pb[k];
        const std::string of = what + ": tool point " + std::to_string(p.id) + "'s ";
        require(p.id == q.id && p.body == q.body && p.attached == q.attached && p.width_m == q.width_m &&
                    p.thickness_m == q.thickness_m && p.angle_deg == q.angle_deg && p.length_m == q.length_m &&
                    p.in == q.in,
                of + "description differs");
        requireSame(p.tip_local_m, q.tip_local_m, of + "tip");
        requireSame(p.pointing_local, q.pointing_local, of + "pointing");
        requireSame(p.grip_local_m, q.grip_local_m, of + "grip");
        requireSame(p.tip_m, q.tip_m, of + "tip in the world");
    }
}

// Where two saved worlds first differ, as a path into the document: "" when
// they are the same.
std::string firstDifference(const nlohmann::json &a, const nlohmann::json &b, const std::string &at = "") {
    if (a.type() != b.type()) return at + " (" + a.dump().substr(0, 80) + " against " + b.dump().substr(0, 80) + ")";
    if (a.is_object()) {
        for (auto it = a.begin(); it != a.end(); ++it) {
            if (!b.contains(it.key())) return at + "/" + it.key() + " (missing)";
            const std::string d = firstDifference(it.value(), b.at(it.key()), at + "/" + it.key());
            if (!d.empty()) return d;
        }
        for (auto it = b.begin(); it != b.end(); ++it)
            if (!a.contains(it.key())) return at + "/" + it.key() + " (added)";
        return "";
    }
    if (a.is_array()) {
        if (a.size() != b.size())
            return at + " (" + std::to_string(a.size()) + " against " + std::to_string(b.size()) + ")";
        for (std::size_t i = 0; i < a.size(); ++i) {
            const std::string d = firstDifference(a[i], b[i], at + "/" + std::to_string(i));
            if (!d.empty()) return d;
        }
        return "";
    }
    return a == b ? "" : at + " (" + a.dump() + " against " + b.dump() + ")";
}

// Two saved worlds are one world: every field alike, but for what a pin reads,
// which the solver works out again from single-precision turns -- a pin made
// again reads its angle to about a millionth of a radian.
void requireSameSaved(const std::string &first, const std::string &second, const std::string &what) {
    nlohmann::json a = nlohmann::json::parse(first);
    nlohmann::json b = nlohmann::json::parse(second);
    require(a.at("joints").size() == b.at("joints").size(), what + ": a different number of joints");
    for (std::size_t k = 0; k < a.at("joints").size(); ++k) {
        nlohmann::json &p = a["joints"][k];
        nlohmann::json &q = b["joints"][k];
        require(p.contains("held") == q.contains("held"), what + ": joint " + std::to_string(k) + " holds in one only");
        if (!p.contains("held")) continue;
        const double at_p = p["held"]["at"].get<double>(), at_q = q["held"]["at"].get<double>();
        require(std::abs(at_p - at_q) < 1e-5, what + ": joint " + std::to_string(k) + " reads " +
                                                  std::to_string(at_q) + ", not " + std::to_string(at_p));
        p["held"].erase("at");
        q["held"].erase("at");
    }
    const std::string d = firstDifference(a, b);
    require(d.empty(), what + ": the saved worlds differ at " + d);
}

void aWorldSavedComesBackAsItStood() {
    constexpr double kPi = 3.14159265358979323846;
    const auto live = LiveWorld::open(workshop());
    live->foreseeCollisions(0.0);
    // The ball dents on the anvil in its first hundredth of a second, and the
    // other lands on the pane 0.78 s in.
    stepAnswering(*live, 288, 1.0 / 480.0);
    stepAnswering(*live, 240);
    std::size_t shards = 0;
    for (const LiveBodyPose &pose : live->poses())
        if (pose.name.rfind("pane piece ", 0) == 0) ++shards;
    const LiveBodyPose dented = named(live->poses(), "iron ball");
    require(dented.dent_m > 0.0, "the iron ball took no dent, so this proves nothing about dents");
    require(shards > 1, "the pane did not break, so this proves nothing about pieces");

    // The door, hung by its post and hauled 50 degrees round; its pin's
    // friction holds it where it is left.
    const Vec3 pin{0.04, 0.45, 1.2};
    require(live->hinge("post", "door", pin, {0.0, 1.0, 0.0}, -90.0, 90.0, 2.0) != 0,
            "the door would not hang on its post");
    require(live->grab("door"), "the door could not be taken hold of");
    const double swing = 50.0 * kPi / 180.0;
    live->moveHeld({pin.x + 0.26 * std::cos(swing), 0.45, pin.z - 0.26 * std::sin(swing)});
    stepAnswering(*live, 240);
    live->release();

    // The crate into the bag.
    std::string why;
    require(live->park("crate", why), "the crate could not be set aside: " + why);

    // The pick: a point at one end and an edge along one face, taken up by
    // its middle and held half a metre up.
    require(live->toolPoint("pick", {-1.0, 0.02, -1.2}, {1.0, 0.0, 0.0}, 0.04, 0.04, 30.0, 0.15,
                            {-1.38, 0.02, -1.2}) != 0,
            "the pick would not take a point: " + live->toolPointRefusal());
    require(live->blade("pick", {-1.3, 0.02, -1.22}, {-1.1, 0.02, -1.22}, {0.0, 0.0, -1.0}, 0.01, 0.0002, 30.0,
                        {-1.38, 0.02, -1.2}) != 0,
            "the pick would not take an edge: " + live->bladeRefusal());
    require(live->wield("pick", {-1.2, 0.02, -1.2}), "the pick could not be taken up");
    live->moveHeld({-1.2, 0.6, -1.2});
    stepAnswering(*live, 480);

    const std::string first = live->snapshot(why);
    require(!first.empty(), "the room could not be saved: " + why);
    const nlohmann::json saved = nlohmann::json::parse(first);
    const auto back = LiveWorld::open(workshop(), first);
    const LiveRestore &restored = back->restored();
    std::size_t resting = 0;
    for (const nlohmann::json &body : saved.at("bodies"))
        if (body.contains("pose") && !body.at("awake").get<bool>() && !body.at("anchored").get<bool>()) ++resting;
    std::cout << "  saved at t=" << saved.at("t_s").get<double>() << " s: " << saved.at("bodies").size()
              << " bodies (" << shards << " pieces of pane, " << resting << " of the loose ones at rest), "
              << first.size() / 1024 << " KB; opened again " << restored.tier << " with " << restored.bodies
              << " bodies\n";
    require(restored.tier == "whole", "the room did not come back whole: " + restored.why);
    requireSameWorld(*live, *back, "the room opened again");
    require(back->parked("crate") && live->parked("crate"), "the crate is not still set aside");
    require(back->hand().holding == "pick" && back->hand().mode == "grip", "the hand does not still hold the pick");
    const std::string second = back->snapshot(why);
    require(!second.empty(), "the room opened again could not be saved: " + why);
    requireSameSaved(first, second, "the room opened again, saved");

    // Stepped on, what was at rest stays put -- in the room and in the one
    // opened again.
    std::vector<std::string> still;
    for (const nlohmann::json &body : saved.at("bodies"))
        if (body.contains("pose") && !body.at("awake").get<bool>() && !body.at("anchored").get<bool>())
            still.push_back(body.at("name").get<std::string>());
    const std::vector<LiveBodyPose> live_before = live->poses(), back_before = back->poses();
    stepAnswering(*live, 240);
    stepAnswering(*back, 240);
    const std::vector<LiveBodyPose> live_after = live->poses(), back_after = back->poses();
    for (const std::string &name : still) {
        // What "stays put" is worth: nothing that was at rest walks off, in
        // either room.
        //
        // It used to be a nanometre, and the two rooms were required to track
        // each other to a nanometre as well. Both only ever held because a
        // piece was being made six thousand times harder to turn than its own
        // matter (JoltWorld::addFragments). With its real inertia a pile of
        // ninety pane shards settles a little when it is stepped on: measured
        // here, `pane piece 67` moves 159 nm and `pane piece 89` 733 um.
        //
        // Tracking is not a claim this test can make. The save writes poses
        // rounded to 10 um, so the room opened again starts that far off, and a
        // settling pile is chaotic -- it parted by 22 um over a second on this
        // machine and by more than 100 um on CI's. This repository has the
        // lesson written down elsewhere: the valley moves metres for a
        // nanometre of start. What the two rooms being the same means is
        // checked where it can be, at the moment of reopening
        // (requireSameWorld, requireSameSaved, and the saved bytes above).
        //
        // So what is left here is the thing worth guarding: a body the save
        // called asleep does not wander. A quarter of a cell is the bar.
        const Vec3 moved_back = named(back_after, name).position_m - named(back_before, name).position_m;
        const Vec3 moved_live = named(live_after, name).position_m - named(live_before, name).position_m;
        require(length(moved_back) < 5e-3,
                "the " + name + " was at rest and moved in the room opened again");
        require(length(moved_live) < 5e-3,
                "the " + name + " was at rest and moved in the room");
    }
    std::cout << "  stepped on for 1 s: the " << still.size() << " at rest stayed put in both\n";

    // It goes on from there: what breaks next is new and numbered after it,
    // and so is a joint made next.
    require(back->grab("glass breaker"), "the glass breaker could not be taken up in the room opened again");
    back->moveHeld({1.2, 0.04 + 0.06 + 10.0, -1.2});
    back->release();
    bool broke = false;
    for (int i = 0; i < 720 && !broke; ++i) {
        back->step(1.0 / 240.0);
        for (const std::string &name : back->breakable())
            if (back->fracture(name) > 1 && name == "window") broke = true;
    }
    require(broke, "the window was not broken, so nothing new was made");
    const std::string third = back->snapshot(why);
    require(!third.empty(), "the room opened again could not be saved after the window broke: " + why);
    const nlohmann::json later = nlohmann::json::parse(third);
    std::set<std::string> saved_names;
    for (const nlohmann::json &body : saved.at("bodies")) saved_names.insert(body.at("name").get<std::string>());
    const std::uint64_t next_body = saved.at("next").at("body").get<std::uint64_t>();
    std::size_t made = 0;
    for (const nlohmann::json &body : later.at("bodies")) {
        const std::string name = body.at("name").get<std::string>();
        if (name.rfind("window piece ", 0) != 0) continue;
        ++made;
        require(saved_names.count(name) == 0, "a new piece took a name the room already had: " + name);
        require(body.at("body_id").get<std::uint64_t>() >= next_body,
                "a new piece took a body number from before the room was saved: " + name);
    }
    require(made > 1, "the window's pieces are not in the room");
    const unsigned joint = back->hinge("anvil", "iron ball", named(back->poses(), "iron ball").position_m,
                                       {0.0, 1.0, 0.0});
    require(joint == saved.at("next").at("joint").get<unsigned>(),
            "a joint made in the room opened again did not take the next number: " + std::to_string(joint));
    std::cout << "  then the window broke into " << made << " new pieces, numbered from " << next_body
              << ", and a new pin took number " << joint << "\n";

    // Not while the hand makes a stroke; saved once it is over.
    LiveStroke stroke;
    stroke.path_m = {live->hand().grip_m, live->hand().grip_m + Vec3{0.3, 0.0, 0.0}};
    stroke.speed_m_s = 1.0;
    stroke.accel_m_s2 = 20.0;
    require(live->stroke(stroke, why), "the pick could not be swung: " + why);
    require(live->snapshot(why).empty() && why.find("stroke") != std::string::npos,
            "the room was saved in the middle of a stroke: " + why);
    live->cancelStroke();
    require(!live->snapshot(why).empty(), "the room could not be saved once the stroke was over: " + why);

    // A saved world that does not fit -- this room with its crate authored
    // 100 mm over, whose cells are not these -- opens the room as it is, and
    // puts each thing still whole and its own self back where it was left.
    const auto moved = LiveWorld::open(workshop(0.1), first);
    require(moved->restored().tier == "poses" && moved->restored().why.find("cells") != std::string::npos,
            "a world saved from another scene was not refused whole: " + moved->restored().tier + ", " +
                moved->restored().why);
    for (const nlohmann::json &body : saved.at("bodies")) {
        if (body.at("name") != "glass breaker" || body.at("dent_m").get<double>() > 0.0) continue;
        requireSame(named(moved->poses(), "glass breaker").position_m, rigidPoint(body),
                    "the glass breaker put back where it was left");
    }
    require(!moved->parked("crate"), "the crate was set aside in a room whose bag the engine could not keep");
    const auto unread = LiveWorld::open(workshop(), "{ half a world");
    require(unread->restored().tier == "none" && !unread->restored().why.empty(),
            "a saved world that does not read was taken as one");
    require(unread->bodies() == workshop().bodies.size(), "a saved world that does not read left the room changed");
    std::cout << "  saved from another scene: " << moved->restored().bodies << " whole things put back where they "
              << "were left (" << moved->restored().why << ")\n";
}

// A world is not saved while something it cannot carry is under way -- a break
// being worked out, an edge in a cut -- and is once that is over. A cut block
// comes back with its kerf and its severed bonds.
void aWorldIsNotSavedWhileSomethingIsUnderWay() {
    std::string why;
    {
        const auto live = LiveWorld::open(paneAndBall(3.0));
        live->foreseeCollisions(0.0);
        bool started = false;
        for (int i = 0; i < 2000 && !started; ++i) {
            live->step(1.0 / 240.0);
            const std::vector<std::string> waiting = live->breakable();
            if (std::find(waiting.begin(), waiting.end(), "pane") != waiting.end())
                started = live->beginFracture("pane");
        }
        require(started, "the pane was never struck hard enough to break, so this proves nothing");
        require(live->snapshot(why).empty() && why.find("break") != std::string::npos,
                "a world was saved while a break was being worked out: " + why);
        const auto give_up = std::chrono::steady_clock::now() + std::chrono::seconds(60);
        while (live->fracturePending() && std::chrono::steady_clock::now() < give_up) {
            if (live->fractureReady()) {
                (void)live->finishFracture();
                break;
            }
            live->step(1.0 / 240.0);
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        require(!live->fracturePending(), "the break was never worked out");
        require(!live->snapshot(why).empty(), "the world could not be saved once the break was done: " + why);
    }
    {
        // theCutCostsWhatItTook's partial cut (blade_tests), with nothing but
        // the two bodies and no gravity.
        TileImpactRequest r;
        r.cell_size_m = 0.01;
        r.backend = benchBackend();
        r.gravity_m_s2 = {0.0, 0.0, 0.0};
        SceneBody block;
        block.name = "block";
        block.shape = BodyShape::Box;
        block.material = MaterialPreset::Oak;
        block.dimensions_m = {0.1, 0.1, 0.1};
        block.center_m = {0.0, 0.5, 0.0};
        SceneBody blade = block;
        blade.name = "blade";
        blade.material = MaterialPreset::Iron;
        blade.dimensions_m = {0.2, 0.01, 0.03};
        blade.center_m = {0.0, 0.5, 0.066};
        blade.velocity_m_s = {0.0, 0.0, -6.0};
        r.bodies = {block, blade};
        const auto cut = LiveWorld::open(r);
        require(cut->blade("blade", {-0.09, 0.5, 0.051}, {0.09, 0.5, 0.051}, {0.0, 0.0, -1.0}, 0.01, 0.00005, 30.0,
                           {0.09, 0.5, 0.066}) != 0,
                "the blade would not take an edge: " + cut->bladeRefusal());
        // While the edge is in the block -- its cut open -- the world is not
        // saved.
        bool refused_in_the_cut = false;
        for (int i = 0; i < 120; ++i) {
            cut->step(1.0 / 240.0);
            if (cut->steppedBack())
                for (const std::string &name : cut->breakable()) cut->declineBreak(name);
            const std::vector<LiveCut> cuts = cut->cuts();
            if (!refused_in_the_cut &&
                std::any_of(cuts.begin(), cuts.end(), [](const LiveCut &each) { return each.open; })) {
                require(cut->snapshot(why).empty() && why.find("edge") != std::string::npos,
                        "a world was saved with an edge in a cut: " + why);
                std::cout << "  with the edge in the block: \"" << why << "\"\n";
                refused_in_the_cut = true;
            }
            const std::vector<LiveBodyPose> poses = cut->poses();
            const double closing = named(poses, "block").velocity_m_s.z - named(poses, "blade").velocity_m_s.z;
            if (i > 4 && std::abs(closing) < 0.005) break;
        }
        require(refused_in_the_cut, "the edge was never seen in the block, so this proves nothing");
        require(!named(cut->poses(), "block").kerfs.empty(), "the blade made no kerf, so this proves nothing");
        // Drawn clear of the cut, it is saved, and comes back cut.
        require(cut->grab("blade"), "the blade could not be taken hold of");
        cut->moveHeld(named(cut->poses(), "blade").position_m + Vec3{0.0, 0.0, 0.2});
        for (int i = 0; i < 10; ++i) cut->step(1.0 / 240.0);
        cut->release();
        for (int i = 0; i < 10; ++i) cut->step(1.0 / 240.0);
        const std::string kept = cut->snapshot(why);
        require(!kept.empty(), "the world could not be saved with the blade drawn clear: " + why);
        require(!nlohmann::json::parse(kept).at("dead_bonds_b64").get<std::string>().empty(),
                "the saved world carries no severed bond");
        const auto again = LiveWorld::open(r, kept);
        require(again->restored().tier == "whole", "the cut block did not come back whole: " + again->restored().why);
        requireSameWorld(*cut, *again, "the cut block opened again");
        requireSameSaved(kept, again->snapshot(why), "the cut block opened again, saved");
        std::cout << "  the cut block came back with its " << named(again->poses(), "block").kerfs.size()
                  << " kerf and its severed bonds\n";
    }
}

void aBreakIsTakenAtItsOwnStepWhateverElseIsInTheRoom() {
    const PaneBroken alone = breakThePane(false);
    const PaneBroken with_cup = breakThePane(true);
    std::cout << "  the room's step: " << 1.0e6 * alone.scene_step_s << " us alone, "
              << 1.0e6 * with_cup.scene_step_s << " us with the cup across it\n"
              << "  the pane's run: " << alone.run_steps << " steps of " << 1.0e6 * alone.run_step_s
              << " us alone; " << with_cup.run_steps << " steps of " << 1.0e6 * with_cup.run_step_s
              << " us with the cup (" << alone.pieces << " and " << with_cup.pieces << " pieces)\n";
    require(alone.pieces > 1 && with_cup.pieces > 1, "the pane did not break, so this proves nothing");
    require(with_cup.scene_step_s < 0.9 * alone.scene_step_s,
            "the cup did not set the room a shorter step, so this proves nothing");
    require(alone.run_step_s > 0.0 && with_cup.run_step_s == alone.run_step_s,
            "the pane's run was taken at a different step with a cup across the room");
    require(with_cup.run_steps == alone.run_steps,
            "the pane's run took a different number of steps with a cup across the room");
    require(with_cup.run_step_s > with_cup.scene_step_s,
            "the pane's run was taken at the room's step, not its own lattice's");
}

int main(int argc, char **argv) {
    try {
        if (argc > 1 && std::string(argv[1]) == "--landing") {
            aHardLandingBreaksItWhateverThePhaseOfTheStep();
            std::cout << "[PASS] a hard landing breaks the thing whatever the phase of the step it lands in\n";
            return 0;
        }
        if (argc > 1 && std::string(argv[1]) == "--deadline") {
            theDeadlineIsMet();
            std::cout << "[PASS] a foreseen fracture's first run is done inside its warning\n";
            return 0;
        }
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
        theCountIsWhatIsActuallyInTheWorld();
        std::cout << "[PASS] the piece count reported is the piece count in the world\n";
        aHardEnoughHitActuallyBreaksIt();
        std::cout << "[PASS] a hard enough hit puts the object back in the lattice and breaks it\n";
        aGentleHitLeavesItWhole();
        std::cout << "[PASS] a gentle hit leaves it whole, and asking anyway does not break it\n";
        breakingSomethingThatCannotBreakIsHarmless();
        std::cout << "[PASS] breaking scenery or a name that is not there changes nothing\n";
        aThingThatHeldDoesNotStopTheWorld();
        std::cout << "[PASS] something that was hit hard and held does not deadlock the world\n";
        theWorldKeepsRunningWhileAFractureIsWorkedOut();
        std::cout << "[PASS] the world keeps running while a fracture is worked out\n";
        aBreakIsTakenAtItsOwnStepWhateverElseIsInTheRoom();
        std::cout << "[PASS] a break is taken at its own step, whatever else is in the room\n";
        aSecondBreakDoesNotStopTheClock();
        std::cout << "[PASS] a second break does not stop the clock\n";
        theWorldSeesACollisionComing();
        std::cout << "[PASS] the world sees a collision coming, names what will break and starts its run on the way down\n";
        aDropBreaksThePlateWhateverThePhaseOfTheStep();
        std::cout << "[PASS] a drop breaks the plate whatever the phase of the step it lands in\n";
        aBodyAskedAboutForADentIsNotBroken();
        std::cout << "[PASS] a body asked about for a dent is dented, never broken\n";
        landingOnTheFloorIsAnImpact();
        std::cout << "[PASS] landing on the floor is an impact and is judged like any other\n";
        aHardLandingBreaksItWhateverThePhaseOfTheStep();
        std::cout << "[PASS] a hard landing breaks the thing whatever the phase of the step it lands in\n";
        aThingBendsBeforeItBreaks();
        std::cout << "[PASS] a thing bends before it breaks, and the engine says which\n";
        somethingBrittleHasNoDentingRange();
        std::cout << "[PASS] something brittle has no bending range and says so\n";
        somethingCanBeDentedWithoutBeingBroken();
        std::cout << "[PASS] something can be dented without being broken\n";
        aBodyBuiltTurnedSaysSoAndIsWhereItSays();
        std::cout << "[PASS] a body built turned says which way it faces, and is where it says\n";
        aHandHoldingATurnedThingAsItIsDoesNotTurnIt();
        std::cout << "[PASS] a hand holding a turned thing as it is does not turn it\n";
        aTurnedBoxThatComesThroughARunKeepsItsTurn();
        std::cout << "[PASS] a turned box that comes through a run whole keeps its turn\n";
        whatAThingIsMadeOfDecidesHowItBounces();
        std::cout << "[PASS] what a thing is made of decides how it bounces\n";
        aRayFindsWhatItActuallyHits();
        std::cout << "[PASS] a ray finds what it actually hits, named and measured\n";
        aRayFindsPiecesAfterSomethingBreaks();
        std::cout << "[PASS] a ray finds pieces after something breaks\n";
        somethingLiftedOutOfASettledWorldStillFalls();
        std::cout << "[PASS] something lifted out of a settled world still falls\n";
        theGroundCatchesThingsWhereverTheyAreDropped();
        std::cout << "[PASS] the ground catches things wherever they are dropped\n";
        aThingSetAsideComesBackAsItWas();
        std::cout << "[PASS] a thing set aside is out of the world and comes back as it was\n";
        aHotThingSetAsideKeepsItsHeat();
        std::cout << "[PASS] a hot thing set aside keeps exactly what it holds, and burns on once it is back\n";
        aWorldSavedComesBackAsItStood();
        std::cout << "[PASS] a world saved comes back as it stood, and goes on from there\n";
        aWorldIsNotSavedWhileSomethingIsUnderWay();
        std::cout << "[PASS] a world is not saved while a break or a cut is under way, and is once it is over\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "live world tests failed: " << error.what() << "\n";
        return 1;
    }
}
