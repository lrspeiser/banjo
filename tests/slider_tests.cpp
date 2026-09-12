// Things that slide.
//
// The same idea as a pin, one degree of freedom the other way round: two bodies
// locked in rotation and free to move along one line. A portcullis in its
// grooves, a sliding door, a bolt going across a door.
//
// The reason this is a joint and not an animation is the first test below. A
// portcullis that has been hauled up and let go FALLS -- because gravity is
// still acting on a body that is free to move down its own axis -- and it stops
// on whatever is under it, at whatever height that thing happens to be. Nothing
// here knows what a portcullis is.
//
// What is pinned:
//
// 1. A grate hauled up and released falls back down under its own weight.
// 2. It stops on what is under it, wherever that is, rather than at a scripted
//    height -- so a barrel in the gateway holds the gate open.
// 3. Travel limits are metres and they hold, at both ends.
// 4. Friction is what makes it stay where it is left.
// 5. It only moves along its own axis, whatever it is pushed with.
// 6. The axis can be any direction, not just up: a bolt slides sideways.
// 7. A slide survives the room rearranging itself, and follows its material.

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

// By value: joints() hands back a fresh vector, so a reference into one dies at
// the end of the statement. That has cost an hour twice in this area.
LiveJoint jointNumber(const std::vector<LiveJoint> &joints, unsigned id) {
    for (const LiveJoint &joint : joints)
        if (joint.id == id) return joint;
    throw std::runtime_error("no joint with that id");
}

// A gateway with a grate in it, sitting on the ground.
//
// The grate is in FRONT of the jambs in z rather than between them, for the
// same reason a door leaf is: something sharing space with its own frame is
// jammed against it, and jammed looks exactly like a broken joint.
TileImpactRequest gateway(double grate_bottom_mm = 0.0) {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody ground;
    ground.name = "ground";
    ground.shape = BodyShape::Box;
    ground.material = MaterialPreset::Concrete;
    ground.dimensions_m = {4.0, 0.1, 2.0};
    ground.center_m = {0.75, -0.05, 0.0};
    ground.anchored = true;
    SceneBody left;
    left.name = "left jamb";
    left.shape = BodyShape::Box;
    left.material = MaterialPreset::Concrete;
    left.dimensions_m = {0.15, 3.0, 0.15};
    left.center_m = {-0.1, 1.5, 0.0};
    left.anchored = true;
    SceneBody right;
    right.name = "right jamb";
    right.shape = BodyShape::Box;
    right.material = MaterialPreset::Concrete;
    right.dimensions_m = {0.15, 3.0, 0.15};
    right.center_m = {1.6, 1.5, 0.0};
    right.anchored = true;
    SceneBody grate;
    grate.name = "grate";
    grate.shape = BodyShape::Box;
    grate.material = MaterialPreset::Iron;
    grate.dimensions_m = {1.5, 1.8, 0.1};
    // Its middle sits half its height above its own bottom edge.
    grate.center_m = {0.75, grate_bottom_mm / 1000.0 + 0.9, 0.15};
    r.bodies = {ground, left, right, grate};
    return r;
}

// The grooves: the grate may move straight up and down and nothing else.
unsigned hangGrate(LiveWorld &world, double lift_m = 2.0, double friction_n = 0.0) {
    const auto standing = world.poses();
    const Vec3 at = named(standing, "grate").position_m;
    return world.slide("left jamb", "grate", at, Vec3{0.0, 1.0, 0.0},
                       0.0, lift_m, friction_n);
}

void tick(LiveWorld &world) {
    world.step(1.0 / 240.0);
    if (!world.steppedBack()) return;
    // Answer the handshake, or the clock stops and everything below reads as a
    // gate that will not move.
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

void run(LiveWorld &world, int steps) {
    for (int i = 0; i < steps; ++i) tick(world);
}

// Haul the grate up by hand, and let go.
void haul(LiveWorld &world, double by_m) {
    require(world.grab("grate"), "could not take hold of the grate");
    const auto standing = world.poses();
    const Vec3 from = named(standing, "grate").position_m;
    const int steps = static_cast<int>(by_m / 0.01);
    for (int i = 1; i <= steps; ++i) {
        world.moveHeld(from + Vec3{0.0, by_m * i / steps, 0.0});
        tick(world);
    }
    world.release();
}

double heightOf(LiveWorld &world) {
    return named(world.poses(), "grate").position_m.y;
}

// -----------------------------------------------------------------------------

void aRaisedGrateFallsWhenYouLetGo() {
    // The whole claim, in one test. Nothing knows what a portcullis is: the
    // grate falls because it is 216 kg of iron free to move along a vertical
    // line and there is nothing holding it up.
    const auto world = LiveWorld::open(gateway());
    const unsigned grooves = hangGrate(*world);
    require(grooves != 0, "the grate would not go into its grooves");

    const double down = heightOf(*world);
    haul(*world, 1.5);
    const double up = heightOf(*world);
    run(*world, 480);
    const double after = heightOf(*world);

    std::cout << "  hauled from y=" << down << " to y=" << up
              << "; two seconds after letting go it is at y=" << after << "\n";
    require(up > down + 1.2, "the haul did not lift it");
    require(after < down + 0.15, "it was let go a metre and a half up and stayed there");
}

void itStopsOnWhateverIsUnderIt() {
    // And this is why it matters. A barrel left in the gateway holds the gate
    // open -- at the barrel's height, not at a number anybody wrote down.
    TileImpactRequest request = gateway();
    SceneBody barrel;
    barrel.name = "barrel";
    barrel.shape = BodyShape::Box;
    barrel.material = MaterialPreset::Oak;
    barrel.dimensions_m = {0.5, 0.6, 0.5};
    barrel.center_m = {0.75, 0.3, 0.15};
    barrel.anchored = true;         // wedged, rather than knocked aside
    request.bodies.push_back(barrel);

    const auto world = LiveWorld::open(request);
    const unsigned grooves = hangGrate(*world);
    require(grooves != 0, "the grate would not go into its grooves");
    haul(*world, 1.5);
    run(*world, 600);

    const double rest = heightOf(*world);
    // Its bottom edge should be sitting on the barrel's top, at 0.6 m.
    const double bottom = rest - 0.9;
    std::cout << "  with a 600 mm barrel under it the grate came to rest with its "
              << "bottom edge at y=" << bottom << "\n";
    require(bottom > 0.5 && bottom < 0.75,
            "the grate did not come to rest on the barrel: it went through it, or "
            "it stopped somewhere the barrel is not");
}

void travelIsMetresAndItHolds() {
    const auto world = LiveWorld::open(gateway());
    const unsigned grooves = hangGrate(*world, 0.8);
    require(grooves != 0, "the grate would not go into its grooves");
    const double down = heightOf(*world);
    haul(*world, 2.0);          // hauled well past the 0.8 m it is allowed
    const double up = heightOf(*world);
    std::cout << "  a grate with 800 mm of travel, hauled 2 m, reached "
              << (up - down) << " m\n";
    require(up - down <= 0.83, "it went further than its grooves allow");
    require(up - down > 0.6, "it barely moved, so the haul proved nothing");

    // And the bottom stop holds too: it falls back and does not go through the
    // floor of its own travel.
    run(*world, 600);
    const double back = heightOf(*world);
    std::cout << "    and it fell back to " << (back - down) << " m above where "
              << "it started\n";
    require(back - down > -0.02, "it dropped below the bottom of its own travel");
}

void frictionIsWhatMakesItStay() {
    // Weigh it first, rather than guessing at the friction that holds it.
    //
    // 1.5 x 1.8 x 0.1 m of iron is 0.27 cubic metres at 7,870 kg/m3, which is
    // 2,125 kg and 20.8 kN of weight. The first version of this test used 4 kN
    // and reported that friction does nothing -- it was holding a fifth of a
    // portcullis.
    constexpr double kGrateWeightN = 1.5 * 1.8 * 0.1 * 7870.0 * 9.81;
    double left_at[2] = {0.0, 0.0};
    for (int stiff = 0; stiff < 2; ++stiff) {
        const auto world = LiveWorld::open(gateway());
        const unsigned grooves =
            hangGrate(*world, 2.0, stiff ? 2.0 * kGrateWeightN : 0.0);
        require(grooves != 0, "the grate would not go into its grooves");
        const double down = heightOf(*world);
        haul(*world, 1.2);
        run(*world, 600);
        left_at[stiff] = heightOf(*world) - down;
    }
    std::cout << "  the grate weighs " << (kGrateWeightN / 1000.0)
              << " kN. Hauled 1.2 m and let go: a free groove left it "
              << left_at[0] << " m up, one gripping at twice its weight left it "
              << left_at[1] << " m up\n";
    require(left_at[1] > left_at[0] + 0.5,
            "the stiff groove let the grate drop as far as the free one, so "
            "friction is not holding anything");
    require(left_at[1] > 0.8, "even the stiff groove did not hold it");
}

void itOnlyMovesAlongItsOwnLine() {
    const auto world = LiveWorld::open(gateway());
    const unsigned grooves = hangGrate(*world);
    require(grooves != 0, "the grate would not go into its grooves");
    const auto before = world->poses();
    const Vec3 was = named(before, "grate").position_m;

    // Drag it sideways and forwards as hard as the hand can. The grooves are
    // vertical, so none of that may move it.
    require(world->grab("grate"), "could not take hold of the grate");
    for (int i = 1; i <= 120; ++i) {
        world->moveHeld(was + Vec3{0.02 * i, 0.0, 0.02 * i});
        tick(*world);
    }
    world->release();
    run(*world, 240);

    const auto after = world->poses();
    const Vec3 now = named(after, "grate").position_m;
    std::cout << "  dragged 2.4 m sideways and 2.4 m forward, the grate moved "
              << std::abs(now.x - was.x) * 1000.0 << " mm in x and "
              << std::abs(now.z - was.z) * 1000.0 << " mm in z\n";
    require(std::abs(now.x - was.x) < 0.02, "the grate came out of its grooves sideways");
    require(std::abs(now.z - was.z) < 0.02, "the grate came out of its grooves forwards");
}

void theLineCanPointAnyWay() {
    // A bolt across a door: the same joint, lying down. If this only worked
    // vertically it would be a portcullis feature rather than a capability.
    TileImpactRequest request = gateway();
    SceneBody bolt;
    bolt.name = "bolt";
    bolt.shape = BodyShape::Box;
    bolt.material = MaterialPreset::Iron;
    bolt.dimensions_m = {0.6, 0.1, 0.1};
    bolt.center_m = {0.2, 2.0, 0.3};
    request.bodies.push_back(bolt);

    const auto world = LiveWorld::open(request);
    const auto standing = world->poses();
    const Vec3 at = named(standing, "bolt").position_m;
    // It shoots along x, and only along x.
    const unsigned groove = world->slide("left jamb", "bolt", at, Vec3{1.0, 0.0, 0.0},
                                         0.0, 0.8, 0.0);
    require(groove != 0, "the bolt would not go into its groove");

    require(world->grab("bolt"), "could not take hold of the bolt");
    for (int i = 1; i <= 60; ++i) {
        world->moveHeld(at + Vec3{0.01 * i, -0.5, 0.0});   // shove it along, and down
        tick(*world);
    }
    world->release();
    run(*world, 240);

    const auto after = world->poses();
    const Vec3 now = named(after, "bolt").position_m;
    const double shot = jointNumber(world->joints(), groove).at;
    std::cout << "  a bolt on a horizontal line: shot " << shot
              << " m along, and fell " << std::abs(now.y - at.y) * 1000.0 << " mm\n";
    require(shot > 0.3, "the bolt did not shoot");
    require(std::abs(now.y - at.y) < 0.02,
            "the bolt fell: a horizontal groove is holding it up against gravity, "
            "and if that is not happening the axis is not being used");
}

void aSlideSurvivesTheRoomRearranging() {
    // Same guarantee as a pin: bodies do not survive breaking, and a joint held
    // against a body id is a constraint pointing at nothing as soon as anything
    // in its island comes apart.
    TileImpactRequest request = gateway();
    // BRIDGED between two piers, not lying on the ground.
    //
    // A pane held everywhere does not break however hard it is hit: the first
    // version of this lay flat on the floor, took an iron ball at 9.67 m/s
    // against a bar of 4.51, and came through whole -- which is the engine
    // being right and the fixture being wrong. Unsupported in the middle is the
    // arrangement that comes apart.
    SceneBody left_pier;
    left_pier.name = "left pier";
    left_pier.shape = BodyShape::Box;
    left_pier.material = MaterialPreset::Iron;
    left_pier.dimensions_m = {0.1, 0.3, 0.3};
    left_pier.center_m = {-2.25, 0.15, 0.0};
    left_pier.anchored = true;
    SceneBody right_pier = left_pier;
    right_pier.name = "right pier";
    right_pier.center_m = {-1.75, 0.15, 0.0};
    SceneBody pane;
    pane.name = "pane";
    pane.shape = BodyShape::Box;
    pane.material = MaterialPreset::Glass;
    pane.dimensions_m = {0.6, 0.05, 0.3};
    pane.center_m = {-2.0, 0.325, 0.0};
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.2, 0.2, 0.2};
    ball.center_m = {-2.0, 5.0, 0.0};
    request.bodies.push_back(left_pier);
    request.bodies.push_back(right_pier);
    request.bodies.push_back(pane);
    request.bodies.push_back(ball);

    const auto world = LiveWorld::open(request);
    // Gripping at twice the grate's own weight, so it stays where it is hauled
    // and a drop afterwards means something went wrong rather than gravity
    // being gravity.
    const unsigned grooves = hangGrate(*world, 2.0, 2.0 * 1.5 * 1.8 * 0.1 * 7870.0 * 9.81);
    require(grooves != 0, "the grate would not go into its grooves");
    haul(*world, 1.0);

    std::size_t pieces = 0;
    for (int i = 0; i < 2400 && pieces == 0; ++i) {
        world->step(1.0 / 240.0);
        if (!world->steppedBack()) continue;
        for (const std::string &name : world->breakable()) {
            if (name != "pane") { world->declineBreak(name); continue; }
            pieces = world->fracture(name);
            break;
        }
    }
    if (pieces <= 1) {
        for (const LiveImpact &hit : world->impacts(0.5))
            std::cout << "    " << hit.by << " -> " << hit.struck << " at "
                      << hit.closing_speed_m_s << " against a bar of "
                      << hit.threshold_speed_m_s << "\n";
        for (const LiveBodyPose &pose : world->poses())
            std::cout << "    " << pose.name << " at y=" << pose.position_m.y
                      << " x=" << pose.position_m.x << "\n";
    }
    require(pieces > 1, "the pane never broke, so nothing rearranged the body table");
    run(*world, 240);

    const LiveJoint groove = jointNumber(world->joints(), grooves);
    std::cout << "  the pane broke into " << pieces << "; the grate's groove still holds \""
              << groove.a << "\" and \"" << groove.b << "\", attached=" << groove.attached
              << ", " << groove.at << " m up\n";
    require(groove.attached, "the groove came out when an unrelated pane broke");
    require(groove.kind == "slider", "the groove came back as the wrong kind of joint");
    require(groove.a == "left jamb" && groove.b == "grate",
            "the groove changed what it was holding");
    // And it is still held up: a groove that quietly came apart would show as a
    // grate back on the ground.
    require(groove.at > 0.5,
            "the grate dropped when the room rearranged itself, so its groove "
            "lost either its travel or its friction");
}

} // namespace

int main() {
    try {
        aRaisedGrateFallsWhenYouLetGo();
        std::cout << "[PASS] a raised grate falls when you let go\n";
        itStopsOnWhateverIsUnderIt();
        std::cout << "[PASS] it stops on whatever is under it\n";
        travelIsMetresAndItHolds();
        std::cout << "[PASS] travel is metres and it holds at both ends\n";
        frictionIsWhatMakesItStay();
        std::cout << "[PASS] friction is what makes it stay where it is left\n";
        itOnlyMovesAlongItsOwnLine();
        std::cout << "[PASS] it only moves along its own line\n";
        theLineCanPointAnyWay();
        std::cout << "[PASS] the line can point any way\n";
        aSlideSurvivesTheRoomRearranging();
        std::cout << "[PASS] a slide survives the room rearranging itself\n";
        std::cout << "\nall slider tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\n[FAIL] " << error.what() << "\n";
        return 1;
    }
}
