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
// 9. A ONE-WAY fixing -- an arrow's nock on a string -- takes any push back
//    into its seat, holds a pull along its axis up to its rating without
//    creeping, and lets go of a harder one by itself, saying it "came off" and
//    what it was holding when it did. It has no tension strength to give.

#include "fastlattice/LiveWorld.hpp"

#include <algorithm>
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

void rectangularBendingUsesActualReactionAndSurvivesRestart() {
    for (const auto material : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        for (const double lever : {0.1,0.2}) {
            auto request=wall();request.bodies[1].material=material;
            request.bodies[1].center_m.x=0.15+lever;
            auto world=LiveWorld::open(request);
            const unsigned id=world->fix("wall","bracket",{0.15,2.0,0.0},{1,0,0},
                1e6,1e6,0,{0,1,0},0.2,0.1);
            require(id!=0,"rectangular section refused");
            run(*world,120);
            auto held=jointNumber(world->joints(),id);
            const double mass=named(world->poses(),"bracket").mass_kg;
            const double expected=mass*9.81*lever;
            require(held.attached,"large rectangular section failed");
            require(std::abs(std::abs(held.bending_v_n_m)-expected)<0.02*expected,
                "fixing moment did not equal actual weight times lever arm");
            require(std::abs(held.bending_u_n_m)<1e-3,"reaction leaked into perpendicular bending axis");
            std::string why;auto saved=world->snapshot(why);
            require(why.empty(),"section snapshot refused");
            auto reopened=LiveWorld::open(request,saved);
            require(reopened->restored().tier=="whole","section snapshot did not wholly reopen");
            auto restored=jointNumber(reopened->joints(),id);
            require(restored.section_u_m==.2 && restored.section_v_m==.1,"section dimensions lost on reopen");
            run(*reopened,1);
            restored=jointNumber(reopened->joints(),id);
            if (std::abs(restored.bending_v_n_m-held.bending_v_n_m)>=0.02*expected)
                std::cout<<"  restart moment before="<<held.bending_v_n_m<<" after="<<restored.bending_v_n_m<<"\n";
            run(*reopened,119);
            restored=jointNumber(reopened->joints(),id);
            require(std::abs(std::abs(restored.bending_v_n_m)-expected)<0.02*expected,"section reaction did not recover after reopen");
            // Same declared stress criterion in all three materials. Strength
            // remains a declaration here; only actual density determines load.
            auto weak=LiveWorld::open(request);
            const unsigned weak_id=weak->fix("wall","bracket",{.15,2,0},{1,0,0},
                0.5*6*expected/.2,1e6,0,{0,1,0},.2,.1);
            run(*weak,1);
            const auto gone=jointNumber(weak->joints(),weak_id);
            require(!gone.attached && gone.parted_because.find("axial and bending")!=std::string::npos,
                "bending-only overload did not part section");
            require(named(weak->poses(),"bracket").mass_kg==mass,"opening interface changed mass");
            require(gone.parted_load_n>gone.parted_capacity_n,"section failure receipt lost deciding loads");
            auto swapped=LiveWorld::open(request);
            const unsigned swapped_id=swapped->fix("wall","bracket",{.15,2,0},{1,0,0},
                0.5*6*expected/.2,1e6,0,{0,0,1},.1,.2);
            run(*swapped,1);
            const auto swapped_gone=jointNumber(swapped->joints(),swapped_id);
            require(!swapped_gone.attached && std::abs(swapped_gone.parted_load_n-gone.parted_load_n)<1e-9,
                "swapping section axes changed normal stress failure");
            auto failed_saved=weak->snapshot(why);
            auto failed_reopen=LiveWorld::open(request,failed_saved);
            require(jointNumber(failed_reopen->joints(),weak_id).parted_because==gone.parted_because,
                "bending failure history lost on reopen");
            const auto count=world->joints().size();
            require(world->fix("wall","bracket",{.15,2,0},{1,0,0},1e6,1e6,0,{1,0,0},.2,.2)==0 &&
                world->joints().size()==count,"invalid section mutated joints");
            std::cout<<"  rectangular / "<<materialPresetName(material)<<" lever="<<lever
                <<" mass="<<mass<<" measured moment="<<held.bending_v_n_m
                <<" expected="<<expected<<" failed equivalent N="<<gone.parted_load_n<<"\n";
        }
    }
}

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

// A bracket seated on the wall ONE WAY: it comes off along `off`, and the wall
// holds it that way with no more than `grip_n`.
unsigned seat(LiveWorld &world, Vec3 off, double grip_n) {
    const Vec3 at = named(world.poses(), "bracket").position_m;
    return world.fix("wall", "bracket", Vec3{0.15, at.y, at.z}, off, 0.0, 0.0, grip_n);
}

void aOneWayFixingTakesAnyPush() {
    // Seated so that it comes off UPWARDS, the bracket's own weight pushes it
    // back into its seat rather than off it -- and that is contact, which takes
    // whatever the push is. 618 N on a seat that would let go of a 1 N pull.
    const auto world = LiveWorld::open(wall());
    const unsigned fixing = seat(*world, Vec3{0.0, 1.0, 0.0}, 1.0);
    require(fixing != 0, "the bracket would not seat on the wall");
    const double hung = named(world->poses(), "bracket").position_m.y;
    run(*world, 720);
    const double after = named(world->poses(), "bracket").position_m.y;
    const LiveJoint held = jointNumber(world->joints(), fixing);
    std::cout << "  618 N pushing a bracket into a seat that comes off at 1 N: it moved "
              << (after - hung) * 1000.0 << " mm, carrying " << held.tension_n_now
              << " N along the axis\n";
    require(held.attached, "a one-way fixing let go of a PUSH");
    require(held.kind == "fixing" && held.comes_off_n == 1.0,
            "the fixing does not say it is one-way");
    require(std::abs(after - hung) < 0.002, "the bracket sank into its seat");
    require(held.tension_n_now > 0.9 * ironWeightN(kBracketLoad),
            "the seat is holding 618 N up and says it is carrying less");
}

void aOneWayFixingHoldsAPullItIsRatedFor() {
    // Seated to come off DOWNWARDS -- the way its weight pulls -- and rated for
    // four times that weight. It holds, and it does not creep off.
    const auto world = LiveWorld::open(wall());
    const unsigned fixing =
        seat(*world, Vec3{0.0, -1.0, 0.0}, 4.0 * ironWeightN(kBracketLoad));
    require(fixing != 0, "the bracket would not seat on the wall");
    const double hung = named(world->poses(), "bracket").position_m.y;
    run(*world, 720);
    const double after = named(world->poses(), "bracket").position_m.y;
    const LiveJoint held = jointNumber(world->joints(), fixing);
    std::cout << "  618 N pulling a bracket off a seat rated for "
              << 4.0 * ironWeightN(kBracketLoad) << " N: it moved "
              << (after - hung) * 1000.0 << " mm in three seconds, carrying "
              << held.tension_n_now << " N\n";
    require(held.attached, "a one-way fixing let go of a pull under its rating");
    require(std::abs(after - hung) < 0.001, "the bracket crept off its seat");
    require(std::abs(held.tension_n_now - ironWeightN(kBracketLoad)) <
                0.05 * ironWeightN(kBracketLoad),
            "the seat is holding the bracket's weight up and reports a different pull");
}

void aOneWayFixingLetsGoOfAHarderPull() {
    // Rated for a quarter of the weight pulling it off: it slides off and the
    // bracket falls. And the fixing says it CAME OFF, with the pull it was
    // holding when it did -- which is its rating, because past that it slides.
    const auto world = LiveWorld::open(wall());
    const double rating = 0.25 * ironWeightN(kBracketLoad);
    const unsigned fixing = seat(*world, Vec3{0.0, -1.0, 0.0}, rating);
    require(fixing != 0, "the bracket would not seat on the wall");
    const double hung = named(world->poses(), "bracket").position_m.y;
    double pull_when_off = -1.0;
    for (int i = 0; i < 480; ++i) {
        tick(*world);
        for (const LiveDelay &delay : world->delays())
            if (std::string(delay.kind) == "came off") pull_when_off = delay.lead_ms;
        world->forgetDelays();
    }
    const double after = named(world->poses(), "bracket").position_m.y;
    const LiveJoint gone = jointNumber(world->joints(), fixing);
    std::cout << "  618 N on a seat rated for " << rating << " N: it came off holding "
              << pull_when_off << " N, and the bracket fell from y=" << hung
              << " to y=" << after << "\n";
    require(!gone.attached, "a one-way fixing held four times its rating");
    require(after < hung - 1.0, "the seat let go but the bracket did not fall");
    require(pull_when_off >= 0.0, "it came off without saying so");
    require(std::abs(pull_when_off - rating) < 0.05 * rating,
            "it came off holding something other than its rating, so the pull is "
            "not what decided it");
}

void aOneWayFixingHasNoTensionStrength() {
    // What pulls a one-way fixing apart is what it comes off at. A tension
    // strength as well would be a second answer to the same question.
    const auto world = LiveWorld::open(wall());
    const Vec3 at = named(world->poses(), "bracket").position_m;
    require(world->fix("wall", "bracket", Vec3{0.15, at.y, at.z}, Vec3{0.0, -1.0, 0.0},
                       100.0, 0.0, 50.0) == 0,
            "a one-way fixing was given a tension strength as well, and took it");
}

void aHeldToolCanPartANativeFixing() {
    for (const bool break_tool : {false,true}) {
    for (const auto material : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        TileImpactRequest request;
        request.cell_size_m = .02;
        request.backend = BackendKind::CpuParallel;
        request.gravity_m_s2 = {};
        SceneBody head;
        head.name = "head"; head.shape = BodyShape::Sphere; head.material = MaterialPreset::Iron;
        head.dimensions_m = {.1,.1,.1}; head.center_m = {.08,1.5,0};
        SceneBody handle;
        handle.name = "handle"; handle.shape = BodyShape::Box; handle.material = MaterialPreset::Oak;
        handle.dimensions_m = {.04,.24,.04}; handle.center_m = {0,1.38,0};
        SceneBody target;
        target.name = "target"; target.shape = BodyShape::Box; target.material = material;
        target.dimensions_m = {.1,.1,.1}; target.center_m = {.24,1.5,0};
        SceneBody anchor;
        anchor.name = "anchor"; anchor.shape = BodyShape::Box; anchor.material = MaterialPreset::Iron;
        anchor.dimensions_m = {.08,.08,.08}; anchor.center_m = {.4,1.5,0}; anchor.anchored = true;
        request.bodies = {head,handle,target,anchor};
        auto world = LiveWorld::open(request);
        world->foreseeCollisions(0);
        const double capacity = break_tool?60:200;
        const auto source_joint = world->fix("handle","head",{.02,1.49,0},{0,1,0},break_tool?capacity:0,break_tool?capacity:0);
        const auto target_joint = world->fix("anchor","target",{.3,1.5,0},{1,0,0},break_tool?0:200,break_tool?0:200);
        const auto failed_joint = break_tool?source_joint:target_joint;
        require(source_joint && target_joint, "object-strike native fixture cannot fix its parts");
        const Vec3 grip{0,1.3,0};
        const auto point = world->toolPoint("head",{.12,1.5,0},{1,0,0},.04,.04,30,.1,grip,"handle");
        require(point!=0, "object-strike fixture cannot attach its working point: "+world->toolPointRefusal());
        world->selectHand("striker player");
        require(world->wield("handle",grip), "object-strike fixture cannot wield its handle");
        const double mass = named(world->poses(),"target").mass_kg;
        const double initial_energy = world->mechanicalEnergyJ();
        world->moveHeld(grip);
        run(*world,240);
        require(jointNumber(world->joints(),source_joint).attached,
                "tool fixture failed during readiness rather than object contact");
        const auto ready = world->hand().grip_m;
        LiveStroke stroke;
        stroke.path_m = {ready,ready+Vec3{.14,0,0}};
        stroke.speed_m_s = 4; stroke.accel_m_s2 = 80; stroke.lead_m = .025;
        stroke.give_up_s = .125;
        std::string why;
        require(world->stroke(stroke,why), "object-strike fixture cannot start its bounded stroke: "+why);
        bool contacted = false, parted = false, withdrew = false;
        double failure_load = 0, first_contact_s = -1, failure_s = -1;
        for (unsigned step=0; step<120; ++step) {
            world->step(1.0/240.0);
            require(!world->steppedBack(), "held contact tried to run a target without its hand/source");
            for (const auto &impact : world->impacts()) if (impact.struck=="target" && impact.by=="head") {
                if (!contacted) first_contact_s = (step+1)/240.0;
                contacted = true;
                if (impact.would_break || impact.would_dent)
                    require(!impact.declined.empty(), "unsupported held internal damage was silently reported as held");
            }
            for (const auto &joint : world->joints()) if (joint.id==failed_joint && !joint.attached) {
                if (!parted) failure_s = (step+1)/240.0;
                parted = true; failure_load = joint.parted_load_n;
                require(!joint.parted_because.empty(), "native failure lost its reason");
            }
            require(world->breakable().empty(), "declined held damage still launches a detached fracture job");
            if (!withdrew && !world->hand().stroking) {
                withdrew = true;
                if (world->toolPoints().front().grip_connected) {
                    LiveStroke withdrawal = stroke;
                    const Vec3 now = world->hand().grip_m;
                    withdrawal.path_m = {now,now-Vec3{.06,0,0}};
                    require(world->stroke(withdrawal,why), "object-strike withdrawal refused: "+why);
                }
            }
        }
        require(contacted && parted && failure_load>capacity, "bounded held contact did not overload the declared fixing");
        require(jointNumber(world->joints(),break_tool?target_joint:source_joint).attached &&
                world->toolPoints().front().grip_connected!=break_tool,
                "native failure changed the wrong fixture or retained a disconnected working point");
        require(world->held()=="handle" && named(world->poses(),"target").mass_kg==mass,
                "native part separation released the player's tool or changed target mass");
        world->cancelStroke();
        const auto saved = world->snapshot(why);
        require(!saved.empty(), "native separated state cannot be saved: "+why);
        auto reopened = LiveWorld::open(request,saved);
        require(reopened->restored().tier=="whole" && named(reopened->poses(),"target").mass_kg==mass,
                "native separated state lost geometry/mass at restart");
        for (const auto &joint : reopened->joints())
            require(joint.id!=failed_joint || !joint.attached, "restart silently repaired the overloaded fixing");
        reopened->selectHand("striker player");
        require(reopened->held()=="handle" && reopened->toolPoints().front().grip_connected!=break_tool,
                "restart lost the player's retained grip or working-point connection state");
        std::cout << "  held contact / " << (break_tool?"tool fixing / ":"target fixing / ")
                  << materialPresetName(material) << ": mass=" << mass
                  << " kg; failed joint load=" << failure_load
                  << " N; first contact=" << first_contact_s << " s; connection failure=" << failure_s << " s; hand work=" << world->hand().work_j
                  << " J; mechanical energy=" << initial_energy << " -> " << world->mechanicalEnergyJ()
                  << " J; delta mechanical energy minus hand work="
                  << world->mechanicalEnergyJ()-initial_energy-world->hand().work_j << " J (unclosed native remainder)\n";
    }
    }
}

void aHeldContactRefusesAnIncompleteFractureIsland() {
    bool offered = false;
    for (const auto material : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        TileImpactRequest request;
        request.cell_size_m = .02;
        request.backend = BackendKind::CpuParallel;
        request.gravity_m_s2 = {};
        SceneBody head;
        head.name="head"; head.shape=BodyShape::Sphere; head.material=MaterialPreset::Iron;
        head.dimensions_m={.1,.1,.1}; head.center_m={.08,1.5,0};
        SceneBody target;
        target.name="target"; target.material=material;
        target.dimensions_m={.1,.1,.1}; target.center_m={.6,1.5,0};
        request.bodies={head,target};
        auto world=LiveWorld::open(request);
        world->foreseeCollisions(0);
        require(world->wield("head",{.08,1.5,0}),"guard fixture cannot wield its source");
        LiveStroke stroke;
        stroke.path_m={{.08,1.5,0},{.88,1.5,0}};
        stroke.speed_m_s=4; stroke.accel_m_s2=80; stroke.lead_m=.025; stroke.give_up_s=1;
        std::string why;
        require(world->stroke(stroke,why),"guard fixture cannot stroke: "+why);
        bool contacted=false, material_offer=false;
        for (unsigned step=0;step<360;++step) {
            world->step(1.0/240);
            require(!world->steppedBack(),"held source was omitted from a target-only fracture offer");
            for (const auto &impact:world->impacts()) if (impact.struck=="target" && impact.by=="head") {
                contacted=true;
                if (impact.would_break || impact.would_dent) {
                    material_offer=true; offered=true;
                    require(impact.declined.find("held tool")!=std::string::npos,
                            "held admission lost its explicit unsupported coupled-target reason");
                }
            }
            require(world->breakable().empty(),"held admission still queues an incomplete fracture island");
        }
        require(contacted,"guard fixture never met the target");
        std::cout << "  held admission / " << materialPresetName(material)
                  << ": native contact=1; declined material offer=" << material_offer << "\n";
    }
    require(offered,"held guard test never reached material admission");
}

} // namespace

int main() {
    try {
        rectangularBendingUsesActualReactionAndSurvivesRestart();
        aHeldToolCanPartANativeFixing();
        aHeldContactRefusesAnIncompleteFractureIsland();
        std::cout << "[PASS] bounded held contact separates native fixings and retains state across restart\n";
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
        aOneWayFixingTakesAnyPush();
        std::cout << "[PASS] a one-way fixing takes any push\n";
        aOneWayFixingHoldsAPullItIsRatedFor();
        std::cout << "[PASS] a one-way fixing holds a pull it is rated for\n";
        aOneWayFixingLetsGoOfAHarderPull();
        std::cout << "[PASS] a one-way fixing lets go of a harder pull, and says so\n";
        aOneWayFixingHasNoTensionStrength();
        std::cout << "[PASS] a one-way fixing has no tension strength\n";
        std::cout << "\nall fixing tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\n[FAIL] " << error.what() << "\n";
        return 1;
    }
}
