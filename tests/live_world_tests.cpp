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
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

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
    const Drop marginal = dropAndBreak(1.5);
    std::cout << "  dropped 10.00 m: hit at " << hard.at_speed << " m/s (threshold "
              << hard.threshold << ") -> " << hard.pieces << " pieces of pane in "
              << hard.fracture_wall_ms << " ms; world now holds " << hard.bodies_after
              << " bodies\n";
    std::cout << "  dropped  1.50 m: hit at " << marginal.at_speed << " m/s (threshold "
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
    // Aimed from directly above its own centre, a piece is usually what is hit
    // first -- but not always, because another piece can be resting over it.
    require(exact * 2 >= asked,
            "fewer than half the rays found the piece they were aimed at, so the "
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
    for (int i = 0; i < 20000 && (!started || live->fracturePending()); ++i) {
        live->step(1.0 / 240.0);
        if (!started) {
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
            if (!live->fractureReady()) continue;
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
    int steps_pending = 0, steps_pending_that_moved = 0;
    int fractures = 0;
    // The symptom, measured the way it is felt: the longest UNBROKEN run of
    // steps that left the clock exactly where it was. A share of steps that
    // moved is not enough to catch this -- most fractures in this scene are
    // milliseconds, so the share stays near one even with the clock stopping,
    // and a test asserting on it passes with the fault in. It is the length of
    // a single stall that is seen, and before this it was the whole run.
    int stall = 0, longest_stall = 0;

    for (int i = 0; i < 6000; ++i) {
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

void theWorldSeesACollisionComing() {
    struct Seen { double lead_ms, cost_ms; std::string object; bool foreseen, blocked; };
    const auto watch = [](double fall) {
        const auto live = LiveWorld::open(paneAndBall(fall));
        live->foreseeCollisions(4.0);
        for (int i = 0; i < 432; ++i) {   // 1.8 s at 1/240
            live->step(1.0 / 240.0);
            for (const std::string &name : live->breakable()) live->fracture(name);
        }
        Seen out{0.0, 0.0, "", false, false};
        for (const LiveDelay &delay : live->delays()) {
            if (std::string(delay.kind) == "foreseen" && !out.foreseen) {
                out.foreseen = true;
                out.lead_ms = delay.lead_ms;
                out.object = delay.object;
            }
            if (std::string(delay.kind) == "blocked" && !out.blocked) {
                out.blocked = true;
                out.cost_ms = delay.cost_ms;
            }
        }
        return out;
    };

    const Seen gentle = watch(0.5);
    const Seen fair = watch(1.5);
    const Seen high = watch(6.0);
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

    // And the warning has to be worth having: longer than the run it is meant
    // to hide. That is the whole test.
    require(fair.blocked, "nothing blocked, so there is nothing to compare against");
    require(fair.lead_ms > fair.cost_ms,
            "the warning is shorter than the run it would have to cover, so there "
            "is no time to work the fracture out before it is needed");
    require(high.lead_ms > fair.lead_ms,
            "a longer fall did not give more warning, so the lead is not being "
            "worked out from the approach at all");
}

void landingOnTheFloorIsAnImpact() {
    const Landing hard = dropOnFloor(MaterialPreset::Glass, 20.0);
    std::cout << "  glass onto the floor at 20 m/s: hit at " << hard.hit
              << " m/s, " << hard.outcome << " into " << hard.pieces << " pieces\n";
    require(hard.hit > 15.0, "landing on the floor was not reported as an impact at all");
    require(hard.outcome == "broke", "a glass ball hit the floor at 20 m/s and survived");
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
              << ", " << was * 1000.0 << " mm across -> " << now * 1000.0 << " mm\n";

    require(after.size() == 1, "it came apart, so this is a break and not a dent");
    require(live->lastOutcome() == LiveOutcome::Dented,
            "the world does not call this a dent, so the shape change came from "
            "somewhere other than the material yielding");
    require(after[0].shape == "hull",
            "it is still being drawn as the sphere it was authored as, so the "
            "shape it ended up in was thrown away");
    require(was - now > 0.01,
            "it held its exact authored size, so nothing was actually deformed");
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
        aSecondBreakDoesNotStopTheClock();
        std::cout << "[PASS] a second break does not stop the clock\n";
        theWorldSeesACollisionComing();
        std::cout << "[PASS] the world sees a collision coming, with more warning than the run costs\n";
        landingOnTheFloorIsAnImpact();
        std::cout << "[PASS] landing on the floor is an impact and is judged like any other\n";
        aThingBendsBeforeItBreaks();
        std::cout << "[PASS] a thing bends before it breaks, and the engine says which\n";
        somethingBrittleHasNoDentingRange();
        std::cout << "[PASS] something brittle has no bending range and says so\n";
        somethingCanBeDentedWithoutBeingBroken();
        std::cout << "[PASS] something can be dented without being broken\n";
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
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "live world tests failed: " << error.what() << "\n";
        return 1;
    }
}
