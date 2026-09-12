// Attachments and latches.
//
// A fixing holds two bodies together as one piece: a peg, a bracket, a nail, a
// door catch, a locking bar, a rope anchor. All six degrees of freedom are
// held, and whatever their relative pose is when it is made is the pose they
// keep -- which is what "defined alignment" means here. It is defined by where
// they are when the peg goes in, which is also how a peg works.
//
// What makes it a fixing rather than a weld is that it has a strength, and TWO
// of them: a peg pulled straight out and a peg sheared sideways fail at
// different loads and it is rarely the same number. Tension is along the axis,
// shear is across it, and either one exceeded parts it.
//
// And what makes it a LATCH is that letting it go changes what the assembly is.
// That is the last test here and it is the one that matters: a gate with a bar
// across it is not a gate that happens to be shut, it is a different machine,
// and lifting the bar turns it back into the first one.
//
// What is pinned:
//
// 1. A fixing holds: a body pegged to an anchored one does not fall.
// 2. It holds the ALIGNMENT, not just the position -- pegged things do not
//    rotate relative to each other.
// 3. A weld (zero strength) holds whatever you hang on it.
// 4. Too much tension pulls it apart, and it says so.
// 5. Too much shear parts it, at a different load from tension.
// 6. Releasing it deliberately drops what it was holding.
// 7. A fixing survives the room rearranging itself.
// 8. A latch changes the assembly: barred, a gate will not swing; unbarred, it
//    does -- and nothing about the gate itself changed.

#include "fastlattice/LiveWorld.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace banjo;
using namespace banjo::fastlattice;

constexpr double kPi = 3.14159265358979323846;

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

// Iron, in newtons, for a box of these dimensions.
constexpr double ironWeightN(Vec3 size_m) {
    return size_m.x * size_m.y * size_m.z * 7870.0 * 9.81;
}

constexpr Vec3 kBracketLoad{0.2, 0.2, 0.2};     // 618 N

// A wall with a bracket pegged to it, and nothing under either.
TileImpactRequest wall(Vec3 load_m = kBracketLoad) {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody post;
    post.name = "wall";
    post.shape = BodyShape::Box;
    post.material = MaterialPreset::Oak;
    post.dimensions_m = {0.2, 3.0, 1.0};
    post.center_m = {0.0, 1.5, 0.0};
    post.anchored = true;
    SceneBody bracket;
    bracket.name = "bracket";
    bracket.shape = BodyShape::Box;
    bracket.material = MaterialPreset::Iron;
    bracket.dimensions_m = load_m;
    // Beside the wall, not inside it.
    bracket.center_m = {0.15 + load_m.x / 2, 2.0, 0.0};
    r.bodies = {post, bracket};
    return r;
}

unsigned peg(LiveWorld &world, double holds_tension_n = 0.0,
             double holds_shear_n = 0.0) {
    const auto standing = world.poses();
    const Vec3 at = named(standing, "bracket").position_m;
    // The peg is driven sideways into the wall, so tension is along x -- the
    // direction that pulls it out -- and shear is anything across that, which
    // is what a weight hanging on the bracket does.
    return world.fix("wall", "bracket", Vec3{0.15, at.y, at.z},
                     Vec3{1.0, 0.0, 0.0}, holds_tension_n, holds_shear_n);
}

// -----------------------------------------------------------------------------

void aFixingHolds() {
    const auto world = LiveWorld::open(wall());
    const unsigned fixing = peg(*world);
    require(fixing != 0, "the bracket would not peg to the wall");
    const double hung = named(world->poses(), "bracket").position_m.y;
    run(*world, 720);
    const double after = named(world->poses(), "bracket").position_m.y;
    const LiveJoint held = jointNumber(world->joints(), fixing);
    std::cout << "  a 618 N bracket pegged to a wall: after three seconds it is "
              << "at y=" << after << " (it was at " << hung << "), carrying "
              << held.shear_n_now << " N of shear\n";
    require(std::abs(after - hung) < 0.02, "the bracket fell off the wall");
    require(held.kind == "fixing", "a fixing came back as the wrong kind of joint");
    require(held.shear_n_now > 0.3 * ironWeightN(kBracketLoad),
            "the fixing is holding a 618 N bracket up and reports almost no load");
}

void aFixingHoldsTheAlignment() {
    // Not just the place: the angle. A peg that held position but let things
    // spin would be a ball joint, and a bracket is not a ball joint.
    const auto world = LiveWorld::open(wall());
    require(peg(*world) != 0, "the bracket would not peg to the wall");
    const auto before = world->poses();
    const double was[4] = {named(before, "bracket").orientation_wxyz[0],
                           named(before, "bracket").orientation_wxyz[1],
                           named(before, "bracket").orientation_wxyz[2],
                           named(before, "bracket").orientation_wxyz[3]};
    run(*world, 720);
    const auto after = world->poses();
    double drift = 0.0;
    for (int i = 0; i < 4; ++i)
        drift = std::max(drift, std::abs(named(after, "bracket").orientation_wxyz[i] - was[i]));
    std::cout << "  after three seconds of hanging, the bracket's facing has "
              << "drifted by " << drift << "\n";
    require(drift < 0.01,
            "the bracket turned while pegged, so the fixing is holding its place "
            "and not its alignment");
}

void aWeldHoldsWhateverYouHangOnIt() {
    // Zero strength means it never lets go on its own. Hang four times the
    // bracket on it and it stays.
    const auto world = LiveWorld::open(wall(Vec3{0.4, 0.2, 0.4}));
    require(peg(*world) != 0, "the bracket would not peg to the wall");
    const double hung = named(world->poses(), "bracket").position_m.y;
    run(*world, 720);
    std::cout << "  a " << ironWeightN(Vec3{0.4, 0.2, 0.4})
              << " N bracket on a weld: it moved "
              << std::abs(named(world->poses(), "bracket").position_m.y - hung) * 1000.0
              << " mm\n";
    require(std::abs(named(world->poses(), "bracket").position_m.y - hung) < 0.02,
            "a weld let go");
}

void tooMuchShearPartsIt() {
    // The bracket's own weight hangs ACROSS the peg, so a shear strength under
    // its weight must give. 618 N of bracket against a peg rated for 150.
    const auto world = LiveWorld::open(wall());
    const unsigned fixing = peg(*world, 0.0, 0.25 * ironWeightN(kBracketLoad));
    require(fixing != 0, "the bracket would not peg to the wall");
    const double hung = named(world->poses(), "bracket").position_m.y;
    run(*world, 480);
    const double after = named(world->poses(), "bracket").position_m.y;
    const LiveJoint gone = jointNumber(world->joints(), fixing);
    std::cout << "  a 618 N bracket on a peg rated for "
              << 0.25 * ironWeightN(kBracketLoad) << " N of shear: it fell from y="
              << hung << " to y=" << after << ", attached=" << gone.attached << "\n";
    require(after < hung - 1.0, "the peg held four times what it was rated for");
    require(!gone.attached, "the peg gave way but still says it is holding");
}

void tensionAndShearAreDifferentNumbers() {
    // The same bracket and the same hanging weight. A peg with NO shear
    // strength but plenty of tension strength must give; one with no tension
    // strength but plenty of shear must hold, because nothing is pulling it
    // out of the wall.
    //
    // If the two were one number this could not come out both ways.
    const auto sheared = LiveWorld::open(wall());
    const unsigned weak_across = peg(*sheared, 1.0e6, 0.25 * ironWeightN(kBracketLoad));
    require(weak_across != 0, "the bracket would not peg");
    run(*sheared, 480);
    const bool fell = !jointNumber(sheared->joints(), weak_across).attached;

    const auto pulled = LiveWorld::open(wall());
    const unsigned weak_along = peg(*pulled, 0.25 * ironWeightN(kBracketLoad), 1.0e6);
    require(weak_along != 0, "the bracket would not peg");
    run(*pulled, 480);
    const LiveJoint still = jointNumber(pulled->joints(), weak_along);
    std::cout << "  weak across the peg: it " << (fell ? "gave way" : "held")
              << ". Weak along it: it " << (still.attached ? "held" : "gave way")
              << ", carrying " << still.tension_n_now << " N of tension and "
              << still.shear_n_now << " N of shear\n";
    require(fell, "a peg with no shear strength held a weight hanging across it");
    require(still.attached,
            "a peg with no TENSION strength gave way to a load that is entirely "
            "shear, so the two are not being told apart");
}

void releasingItDropsWhatItHeld() {
    const auto world = LiveWorld::open(wall());
    const unsigned fixing = peg(*world);
    require(fixing != 0, "the bracket would not peg to the wall");
    run(*world, 240);
    const double hung = named(world->poses(), "bracket").position_m.y;
    world->unhinge(fixing);              // pull the peg
    run(*world, 480);
    const double fell = named(world->poses(), "bracket").position_m.y;
    std::cout << "  peg pulled: the bracket went from y=" << hung << " to y="
              << fell << "\n";
    require(fell < hung - 1.0, "pulling the peg did not drop the bracket");
    require(world->joints().empty(), "the pulled peg is still listed");
}

void aFixingSurvivesTheRoomRearranging() {
    TileImpactRequest request = wall();
    SceneBody pier;
    pier.name = "left pier";
    pier.shape = BodyShape::Box;
    pier.material = MaterialPreset::Iron;
    pier.dimensions_m = {0.1, 0.3, 0.3};
    pier.center_m = {-2.25, 0.15, 0.0};
    pier.anchored = true;
    SceneBody right = pier;
    right.name = "right pier";
    right.center_m = {-1.75, 0.15, 0.0};
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
    request.bodies.push_back(pier);
    request.bodies.push_back(right);
    request.bodies.push_back(pane);
    request.bodies.push_back(ball);

    const auto world = LiveWorld::open(request);
    const unsigned fixing = peg(*world);
    require(fixing != 0, "the bracket would not peg to the wall");

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
    require(pieces > 1, "the pane never broke, so nothing rearranged the body table");
    run(*world, 240);
    const LiveJoint held = jointNumber(world->joints(), fixing);
    std::cout << "  the pane broke into " << pieces << "; the peg still holds \""
              << held.a << "\" and \"" << held.b << "\", attached=" << held.attached
              << "\n";
    require(held.attached, "the peg gave way when an unrelated pane broke");
    require(held.a == "wall" && held.b == "bracket", "the peg changed what it holds");
}

void aLatchChangesWhatTheAssemblyIs() {
    // The one that matters. A gate on a pin, and a bar across it fixed to the
    // jamb. Barred, the gate will not swing however hard it is shoved; unbarred,
    // the same shove opens it. NOTHING about the gate changed -- same pin, same
    // limits, same push. What changed is what the assembly IS.
    const auto build = []() {
        TileImpactRequest r;
        r.cell_size_m = 0.05;
        r.backend = BackendKind::CpuParallel;
        SceneBody ground;
        ground.name = "ground";
        ground.shape = BodyShape::Box;
        ground.material = MaterialPreset::Concrete;
        ground.dimensions_m = {4.0, 0.1, 3.0};
        ground.center_m = {0.5, -0.05, 0.0};
        ground.anchored = true;
        SceneBody jamb;
        jamb.name = "jamb";
        jamb.shape = BodyShape::Box;
        jamb.material = MaterialPreset::Oak;
        jamb.dimensions_m = {0.15, 2.4, 0.15};
        jamb.center_m = {0.0, 1.2, 0.0};
        jamb.anchored = true;
        SceneBody gate;
        gate.name = "gate";
        gate.shape = BodyShape::Box;
        gate.material = MaterialPreset::Oak;
        gate.dimensions_m = {0.8, 1.6, 0.05};
        gate.center_m = {0.45, 1.0, 0.1};
        // The bar lies across the gate and reaches back to the jamb.
        SceneBody bar;
        bar.name = "bar";
        bar.shape = BodyShape::Box;
        bar.material = MaterialPreset::Oak;
        bar.dimensions_m = {1.0, 0.1, 0.1};
        bar.center_m = {0.3, 1.4, 0.2};
        SceneBody fist;
        fist.name = "fist";
        fist.shape = BodyShape::Box;
        fist.material = MaterialPreset::Iron;
        fist.dimensions_m = {0.15, 0.15, 0.15};
        fist.center_m = {0.5, 1.0, 1.0};
        r.bodies = {ground, jamb, gate, bar, fist};
        return r;
    };

    const auto shove = [](LiveWorld &world) {
        require(world.grab("fist"), "could not take hold of the fist");
        const Vec3 from{0.5, 1.0, 1.0};
        world.moveHeld(from);
        tick(world);
        for (int i = 1; i <= 110; ++i) {
            world.moveHeld(from + Vec3{0.0, 0.0, -0.01 * i});
            tick(world);
        }
        world.release();
        run(world, 240);
    };

    // Barred.
    double barred = 0.0;
    {
        const auto world = LiveWorld::open(build());
        // 0..100, not -100..0. A push in -z on a leaf reaching out in +x makes
        // a torque about +y, which is a POSITIVE angle -- so a gate limited to
        // the negative side is a gate held shut by its own stop, and both runs
        // below would have come out at zero degrees for a reason that has
        // nothing to do with the bar.
        const unsigned pin = world->hinge("jamb", "gate", Vec3{0.05, 1.0, 0.1},
                                          Vec3{0.0, 1.0, 0.0}, 0.0, 100.0);
        require(pin != 0, "the gate would not hang");
        // The bar is fixed to BOTH: to the jamb, and to the gate. That is what
        // a bar across a gate does -- it makes the two into one piece.
        require(world->fix("jamb", "bar", Vec3{0.0, 1.4, 0.2},
                           Vec3{1.0, 0.0, 0.0}) != 0, "the bar would not fix to the jamb");
        require(world->fix("bar", "gate", Vec3{0.45, 1.4, 0.15},
                           Vec3{0.0, 0.0, 1.0}) != 0, "the bar would not fix to the gate");
        shove(*world);
        barred = std::abs(jointNumber(world->joints(), pin).at * 180.0 / kPi);
    }
    // Unbarred: the same gate, the same pin, the same shove.
    double unbarred = 0.0;
    {
        const auto world = LiveWorld::open(build());
        const unsigned pin = world->hinge("jamb", "gate", Vec3{0.05, 1.0, 0.1},
                                          Vec3{0.0, 1.0, 0.0}, 0.0, 100.0);
        require(pin != 0, "the gate would not hang");
        const unsigned to_jamb = world->fix("jamb", "bar", Vec3{0.0, 1.4, 0.2},
                                            Vec3{1.0, 0.0, 0.0});
        const unsigned to_gate = world->fix("bar", "gate", Vec3{0.45, 1.4, 0.15},
                                            Vec3{0.0, 0.0, 1.0});
        require(to_jamb != 0 && to_gate != 0, "the bar would not go on");
        // Lift the bar off. This is the latch being released, and it is the
        // only difference between this run and the one above.
        world->unhinge(to_jamb);
        world->unhinge(to_gate);
        run(*world, 60);
        shove(*world);
        unbarred = std::abs(jointNumber(world->joints(), pin).at * 180.0 / kPi);
    }
    std::cout << "  the same shove on the same gate: barred it moved " << barred
              << " degrees, unbarred " << unbarred << "\n";
    require(barred < 5.0, "a barred gate swung open");
    require(unbarred > 15.0, "the unbarred gate did not swing, so the shove "
                             "proved nothing either way");
}

} // namespace

int main() {
    try {
        aFixingHolds();
        std::cout << "[PASS] a fixing holds\n";
        aFixingHoldsTheAlignment();
        std::cout << "[PASS] a fixing holds the alignment, not just the place\n";
        aWeldHoldsWhateverYouHangOnIt();
        std::cout << "[PASS] a weld holds whatever you hang on it\n";
        tooMuchShearPartsIt();
        std::cout << "[PASS] too much shear parts it\n";
        tensionAndShearAreDifferentNumbers();
        std::cout << "[PASS] tension and shear are different numbers\n";
        releasingItDropsWhatItHeld();
        std::cout << "[PASS] releasing it drops what it held\n";
        aFixingSurvivesTheRoomRearranging();
        std::cout << "[PASS] a fixing survives the room rearranging itself\n";
        aLatchChangesWhatTheAssemblyIs();
        std::cout << "[PASS] a latch changes what the assembly is\n";
        std::cout << "\nall fixing tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\n[FAIL] " << error.what() << "\n";
        return 1;
    }
}
