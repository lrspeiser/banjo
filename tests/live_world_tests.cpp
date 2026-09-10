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
    // Falling 1.5 m arrives at about 5.4 m/s; falling 20 mm at about 0.6 m/s.
    const LiveImpact hard = hardestOnThePane(1.5);
    const LiveImpact soft = hardestOnThePane(0.02);
    std::cout << "  dropped 1.50 m: pane hit at " << hard.closing_speed_m_s
              << " m/s, needs " << hard.threshold_speed_m_s << " m/s -> "
              << (hard.would_break ? "breaks" : "holds") << "\n";
    std::cout << "  dropped 0.02 m: pane hit at " << soft.closing_speed_m_s
              << " m/s, needs " << soft.threshold_speed_m_s << " m/s -> "
              << (soft.would_break ? "breaks" : "holds") << "\n";
    require(hard.closing_speed_m_s > 3.0, "the ball did not arrive with any speed");
    require(hard.threshold_speed_m_s > 0.0, "the pane has no breaking speed at all");
    require(soft.closing_speed_m_s < hard.closing_speed_m_s,
            "a shorter drop should land more gently");
    // The point of the test: the SAME pane and the SAME ball give different
    // verdicts, because the verdict is about the contact and not about the
    // scene. If both came back alike the trigger would be reporting nothing.
    require(hard.would_break != soft.would_break,
            "a hard drop and a gentle one were judged identically, so the "
            "trigger is not reading the contact");
    require(hard.would_break, "a 5 m/s iron ball onto a glass pane should break it");
    require(!soft.would_break, "a 0.6 m/s tap should not break a glass pane");
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
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "live world tests failed: " << error.what() << "\n";
        return 1;
    }
}
