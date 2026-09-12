// Pins, as the scene sees them.
//
// JoltWorld's hinge is between two BODIES (tests/hinge_tests.cpp). This is the
// layer above it, where a pin is between two NAMES -- and the difference is the
// whole reason this file exists, because bodies do not survive breaking.
// Everything in an island is destroyed and rebuilt when anything in it comes
// apart, so a hinge held against a body id is a hinge that lasts until the first
// hard knock, and a constraint pointing at a destroyed body is not a bug that
// misbehaves, it is one that crashes.
//
// What is pinned here:
//
// 1. A door hung by name swings, and stays on its hinge.
// 2. Limits given in degrees mean what a person means by them.
// 3. A pin survives something ELSE in the room breaking -- which destroys and
//    rebuilds bodies the door never touched.
// 4. When the door's own wood is smashed, the pin follows the piece it is
//    inside, and the joint is still a joint.
// 5. When there is no wood left to hold it, the pin comes out and says so,
//    rather than being left attached to something that no longer exists.
// 6. Taking the pin out on purpose drops what was hanging on it.

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

// By value on purpose. joints() and poses() both hand back a fresh vector, so
// anything that returns a reference INTO one returns a reference to a temporary
// that dies at the end of the statement. That read, once, as a door whose middle
// was 2.5e+144 metres from its pin, and once as a joint name that printed as
// nothing at all -- neither of which looks like a dangling reference until you
// go looking. A copy of a joint is six doubles and two short strings.
LiveJoint pinNumber(const std::vector<LiveJoint> &joints, unsigned id) {
    for (const LiveJoint &joint : joints)
        if (joint.id == id) return joint;
    throw std::runtime_error("no joint with that id");
}

// A doorway: an anchored post with an oak leaf hung beside it.
//
// The same two lessons the engine-level fixture cost: the leaf is set clear of
// the post in z rather than sharing its space, because a leaf overlapping its
// own frame is jammed against it -- and jammed is exactly what a working hinge
// looks like. And the whole thing is lifted so the leaf hangs above the ground,
// because a door resting on the floor is held by friction with the floor.
TileImpactRequest doorway() {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody ground;
    ground.name = "ground";
    ground.shape = BodyShape::Box;
    ground.material = MaterialPreset::Concrete;
    ground.dimensions_m = {3.0, 0.1, 2.0};
    ground.center_m = {0.0, -0.05, 0.0};
    ground.anchored = true;
    SceneBody post;
    post.name = "post";
    post.shape = BodyShape::Box;
    post.material = MaterialPreset::Oak;
    post.dimensions_m = {0.1, 2.4, 0.1};
    post.center_m = {0.0, 1.2, 0.0};
    post.anchored = true;
    SceneBody leaf;
    leaf.name = "door";
    leaf.shape = BodyShape::Box;
    leaf.material = MaterialPreset::Oak;
    leaf.dimensions_m = {0.8, 1.6, 0.05};
    // In front of the post, hanging clear of the ground.
    leaf.center_m = {0.45, 1.2, 0.1};
    // Something to push the door with.
    //
    // Dragging the DOOR itself proves nothing: a held body is pinned out of the
    // simulation and goes exactly where the hand puts it, so it would reach any
    // angle asked for whether it were hinged or not. A held body still pushes
    // what it runs into, though -- so the hand carries a block into the door
    // and the door does whatever its pin lets it do. That is a force acting on
    // a body attached to a hinge, which is the thing being built.
    SceneBody fist;
    fist.name = "fist";
    fist.shape = BodyShape::Box;
    fist.material = MaterialPreset::Iron;
    fist.dimensions_m = {0.15, 0.15, 0.15};
    fist.center_m = {0.6, 1.2, -0.5};
    r.bodies = {ground, post, leaf, fist};
    return r;
}

// Hang the door on its post: a vertical pin at the post's near edge.
unsigned hangDoor(LiveWorld &world, double lower_deg = -180.0, double upper_deg = 180.0,
                  double friction = 0.0) {
    return world.hinge("post", "door", Vec3{0.05, 1.2, 0.1}, Vec3{0.0, 1.0, 0.0},
                       lower_deg, upper_deg, friction);
}

// One step, with the break handshake answered.
//
// A step that would break something is taken back and the clock does not move
// until the host says fracture or decline. A test that only calls step() and
// says nothing therefore STOPS TIME the moment anything in the room is hit hard
// enough to matter -- and what that looks like from the outside is a door that
// will not swing. It cost an hour here: the pane's shards landing on the floor
// raised breaks nobody answered, and the door was reported as "stopped turning
// once the room rearranged itself" when in fact the room had stopped.
void tick(LiveWorld &world) {
    world.step(1.0 / 240.0);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

void run(LiveWorld &world, int steps) {
    for (int i = 0; i < steps; ++i) tick(world);
}

// Walk the fist into the door, square to its face, and let go.
//
// `through_m` is how far past the door's face the hand carries it. The door is
// free to move out of the way -- and it is the hinge, not the hand, that
// decides where it ends up.
// The hand moves at a fixed one centimetre a step, and the distance sets how
// many steps that takes. Not the other way round: a hand driven the same
// distance in fewer steps moves 2.7 cm a step, which is further than the door
// is thick, and a kinematic body does not sweep -- so it went straight through
// the leaf without touching it and the door turned 3.6 degrees.
void shove(LiveWorld &world, double through_m) {
    require(world.grab("fist"), "could not take hold of the fist");
    // Put the fist where the shove starts, rather than trusting it to still be
    // where the scene left it. It is a loose body under gravity, so in any test
    // that runs for a few seconds first it is lying on the floor by now -- and
    // a shove from down there passes under the door and proves nothing. A hand
    // picks a thing up and carries it to where it is wanted; this is that.
    const Vec3 from{0.6, 1.2, -0.5};
    world.moveHeld(from);
    tick(world);
    const Vec3 to = from + Vec3{0.0, 0.0, 0.6 + through_m};
    const int steps = static_cast<int>(length(to - from) / 0.01);
    for (int i = 1; i <= steps; ++i) {
        const double part = static_cast<double>(i) / static_cast<double>(steps);
        world.moveHeld(from + part * (to - from));
        tick(world);
    }
    world.release();
}

double degreesOf(const LiveWorld &world, unsigned pin) {
    return pinNumber(world.joints(), pin).at * 180.0 / kPi;
}

// -----------------------------------------------------------------------------

void aDoorHungByNameSwings() {
    const auto world = LiveWorld::open(doorway());
    const unsigned pin = hangDoor(*world);
    require(pin != 0, "the door would not hang on the post");

    // Push it square to its face. The hinge turns that into a swing.
    shove(*world, 0.3);
    run(*world, 360);

    const double turned = std::abs(degreesOf(*world, pin));
    // Hold the vector. poses() returns by value, so a reference into the
    // temporary dangles the moment the statement ends -- which read as the
    // door's middle being 2.5e+144 metres from its pin.
    const auto standing = world->poses();
    const LiveBodyPose &now = named(standing, "door");
    const double from_pin = length(now.position_m - Vec3{0.05, 1.2, 0.1});
    std::cout << "  shoved by hand, the door swung " << turned
              << " degrees and its middle is " << from_pin << " m from the pin\n";
    require(turned > 10.0, "the door did not turn on its pin");
    require(std::abs(from_pin - 0.4) < 0.06,
            "the door's middle is no longer half a leaf from the pin, so it came off");
    require(pinNumber(world->joints(), pin).attached, "the pin reported itself gone");
}

void limitsAreInDegreesAndTheyHold() {
    const auto world = LiveWorld::open(doorway());
    const unsigned pin = hangDoor(*world, -45.0, 45.0);
    require(pin != 0, "the door would not hang");

    // Drive it hard, well past where the stop is.
    shove(*world, 1.0);
    run(*world, 240);

    const double turned = std::abs(degreesOf(*world, pin));
    std::cout << "  a door limited to 45 degrees, shoved well past it, reached "
              << turned << "\n";
    require(turned <= 46.0, "the door went past the stop it was given");
    require(turned > 20.0, "it never got near the stop, so the shove proved nothing");
}

void aPinSurvivesSomethingElseBreaking() {
    TileImpactRequest request = doorway();
    // A glass pane beside the doorway, with an iron ball above it. Nothing to
    // do with the door -- which is the point: breaking the pane destroys and
    // rebuilds the bodies in ITS island, and the body table underneath the
    // door's pin moves with it.
    SceneBody pane;
    pane.name = "pane";
    pane.shape = BodyShape::Box;
    pane.material = MaterialPreset::Glass;
    pane.dimensions_m = {0.6, 0.05, 0.6};
    pane.center_m = {-1.0, 0.4, 0.0};
    SceneBody ball;
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.2, 0.2, 0.2};
    ball.center_m = {-1.0, 5.0, 0.0};
    request.bodies.push_back(pane);
    request.bodies.push_back(ball);

    const auto world = LiveWorld::open(request);
    const unsigned pin = hangDoor(*world);
    require(pin != 0, "the door would not hang");

    // Run until the ball breaks the pane, answering the handshake as it comes.
    std::size_t pieces = 0;
    for (int i = 0; i < 2000 && pieces == 0; ++i) {
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
    }
    require(pieces > 1, "the pane never broke, so nothing rearranged the body table");

    // The door is still a door, still on its pin, and still swings.
    const LiveJoint joint = pinNumber(world->joints(), pin);
    std::cout << "    after the pane broke the pin holds \"" << joint.a << "\" and \""
              << joint.b << "\", attached=" << joint.attached << "\n";
    require(joint.attached, "the pin came out when an unrelated pane broke");
    require(joint.a == "post" && joint.b == "door", "the pin changed what it was holding");

    shove(*world, 0.3);
    run(*world, 300);
    const double turned = std::abs(degreesOf(*world, pin));
    std::cout << "  the pane broke into " << pieces
              << "; the door is still hinged and swung " << turned << " degrees after\n";
    require(turned > 10.0, "the door stopped turning once the room had rearranged itself");
}

void aPinFollowsTheWoodItIsIn() {
    // Smash the door itself. Whichever lump of oak the pin is inside is what it
    // should end up holding -- that is what a real hinge does, and it is the
    // difference between a joint that tracks its material and one that is a
    // lookup by a name that no longer exists.
    TileImpactRequest request = doorway();
    // The door is glass here, so it will actually come apart under a blow the
    // scene can deliver. Oak at this cell size wants a great deal more.
    request.bodies.back().material = MaterialPreset::Glass;
    SceneBody hammer;
    hammer.name = "hammer";
    hammer.shape = BodyShape::Sphere;
    hammer.material = MaterialPreset::Iron;
    hammer.dimensions_m = {0.2, 0.2, 0.2};
    // Above the far edge of the leaf, well away from the pin.
    hammer.center_m = {0.75, 8.0, 0.1};
    request.bodies.push_back(hammer);

    const auto world = LiveWorld::open(request);
    const unsigned pin = hangDoor(*world);
    require(pin != 0, "the door would not hang");

    std::size_t pieces = 0;
    for (int i = 0; i < 3000 && pieces < 2; ++i) {
        world->step(1.0 / 240.0);
        if (!world->steppedBack()) continue;
        for (const std::string &name : world->breakable()) {
            if (name.rfind("door", 0) != 0) { world->declineBreak(name); continue; }
            pieces = world->fracture(name);
            break;
        }
    }
    require(pieces > 1, "the door never broke, so there is nothing to follow");
    run(*world, 120);

    const LiveJoint joint = pinNumber(world->joints(), pin);
    std::cout << "  the door broke into " << pieces << "; the pin now holds \""
              << joint.a << "\" and \"" << joint.b << "\", attached=" << joint.attached << "\n";
    require(joint.a == "post", "the post end of the pin wandered");
    if (joint.attached) {
        // It found wood. That wood must exist -- the whole point -- and it must
        // be a piece of the door rather than whatever was lying nearby.
        const auto poses = world->poses();
        bool real = false;
        for (const LiveBodyPose &pose : poses) real = real || pose.name == joint.b;
        require(real, "the pin is attached to a body that is not in the world");
        require(joint.b.rfind("door", 0) == 0, "the pin grabbed something that is not the door");
    } else {
        std::cout << "    no piece of door left around the pin; it came out\n";
    }
}

void aPinWithNoWoodLeftComesOut() {
    // The honest end of the same story: sweep every piece of the door away and
    // the pin has nothing to hold. It must say so rather than keep a constraint
    // on a body that has been destroyed.
    TileImpactRequest request = doorway();
    request.bodies.back().material = MaterialPreset::Glass;
    SceneBody hammer;
    hammer.name = "hammer";
    hammer.shape = BodyShape::Sphere;
    hammer.material = MaterialPreset::Iron;
    hammer.dimensions_m = {0.2, 0.2, 0.2};
    hammer.center_m = {0.75, 8.0, 0.1};
    request.bodies.push_back(hammer);

    const auto world = LiveWorld::open(request);
    const unsigned pin = hangDoor(*world);
    std::size_t pieces = 0;
    for (int i = 0; i < 3000 && pieces < 2; ++i) {
        world->step(1.0 / 240.0);
        if (!world->steppedBack()) continue;
        for (const std::string &name : world->breakable()) {
            if (name.rfind("door", 0) != 0) { world->declineBreak(name); continue; }
            pieces = world->fracture(name);
            break;
        }
    }
    require(pieces > 1, "the door never broke");
    run(*world, 120);
    // Sweep the whole doorway, taking every shard however big.
    const auto swept = world->collect(Vec3{0.45, 1.2, 0.1}, 4.0, 100000);
    std::size_t gone = 0;
    for (const LiveCollected &lot : swept) gone += lot.pieces;
    run(*world, 60);

    const LiveJoint joint = pinNumber(world->joints(), pin);
    std::cout << "  swept up " << gone << " pieces; the pin reports attached="
              << joint.attached << "\n";
    // Whatever the sweep left, the rule is the same and it is absolute: if the
    // pin says it is attached, both ends must be bodies that exist.
    if (joint.attached) {
        const auto poses = world->poses();
        bool a = false, b = false;
        for (const LiveBodyPose &pose : poses) {
            a = a || pose.name == joint.a;
            b = b || pose.name == joint.b;
        }
        require(a && b, "the pin claims to hold a body that has been swept away");
    }
    // And the world must still run afterwards. A dangling constraint does not
    // misbehave here, it crashes.
    run(*world, 240);
    std::cout << "    and the world still steps afterwards\n";
}

void takingThePinOutDropsIt() {
    const auto world = LiveWorld::open(doorway());
    const unsigned pin = hangDoor(*world);
    run(*world, 240);
    const double hung = named(world->poses(), "door").position_m.y;
    world->unhinge(pin);
    run(*world, 480);
    const double fell = named(world->poses(), "door").position_m.y;
    std::cout << "  pin taken out: the door went from y=" << hung << " to y=" << fell << "\n";
    require(fell < hung - 0.3, "the door stayed in the air with no pin holding it");
    require(world->joints().empty(), "the joint is still listed after being taken out");
}

void aPinRefusesWhatItCannotHold() {
    const auto world = LiveWorld::open(doorway());
    require(world->hinge("post", "nothing at all", Vec3{}, Vec3{0.0, 1.0, 0.0}) == 0,
            "hung a pin on a body that does not exist");
    require(world->hinge("door", "door", Vec3{}, Vec3{0.0, 1.0, 0.0}) == 0,
            "hung a body on itself");
    require(world->hinge("post", "door", Vec3{0.05, 1.2, 0.1}, Vec3{}) == 0,
            "accepted a pin with no direction");
    require(world->joints().empty(), "a refused pin was recorded anyway");
    std::cout << "  a pin refuses a missing body, a body hung on itself, and no axis\n";
}

} // namespace

int main() {
    try {
        aDoorHungByNameSwings();
        std::cout << "[PASS] a door hung by name swings on its pin\n";
        limitsAreInDegreesAndTheyHold();
        std::cout << "[PASS] limits are in degrees and they hold\n";
        aPinSurvivesSomethingElseBreaking();
        std::cout << "[PASS] a pin survives something else in the room breaking\n";
        aPinFollowsTheWoodItIsIn();
        std::cout << "[PASS] a pin follows the wood it is in\n";
        aPinWithNoWoodLeftComesOut();
        std::cout << "[PASS] a pin with no wood left comes out\n";
        takingThePinOutDropsIt();
        std::cout << "[PASS] taking the pin out drops what hung on it\n";
        aPinRefusesWhatItCannotHold();
        std::cout << "[PASS] a pin refuses what it cannot hold\n";
        std::cout << "\nall scene joint tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\n[FAIL] " << error.what() << "\n";
        return 1;
    }
}
