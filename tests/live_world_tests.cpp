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
    r.backend = BackendKind::CpuParallel;
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
