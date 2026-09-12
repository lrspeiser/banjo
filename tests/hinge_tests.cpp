// A door swings because a push off its centre line makes a torque.
//
// Not because anything plays a door opening. These check the physics the rest
// of the medieval playground is going to be built out of: that an off-centre
// push turns a hinged body and a centred one does not, that the pin holds the
// body in place while it turns, that limits stop it where they are set, that
// friction holds it where it is left, and that a hinge never outlives the
// bodies it joins.

#include "material/MaterialCatalog.hpp"
#include "rigid/JoltWorld.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace banjo;

namespace {

int failures = 0;
constexpr double kPi = 3.14159265358979323846;

void require(bool ok, const std::string &why) {
    if (!ok) {
        std::cout << "[FAIL] " << why << std::endl;
        ++failures;
    }
}

// A door 0.9 m wide and 2 m tall, hung on a post, hinged about vertical so it
// swings the way a real one does.
//
// Two things about the arrangement that are not decoration. The leaf is set
// clear of the post in z rather than sharing the same space -- a leaf that
// overlaps its own frame is jammed against it, and jammed is what it looks like
// when a hinge is working perfectly. And the whole doorway is lifted so the
// bottom of the leaf hangs above the floor, because a door resting on the
// ground is held by friction with the ground and will not swing either. Both
// of those cost an afternoon the first time.
struct Doorway {
    JoltWorld world;
    MatterBodyId post{1};
    MatterBodyId door{2};
    unsigned hinge{};

    explicit Doorway(double lower = -kPi, double upper = kPi, double friction = 0.0) {
        world.setGravity({0.0, -9.80665, 0.0});

        RigidBoxDescription frame{};
        frame.body_id = post;
        frame.dimensions_m = {0.1, 2.4, 0.1};
        frame.material = makeReferenceMaterial(MaterialPreset::Oak, 17);
        frame.state.center_of_mass_world_m = {0.0, 1.7, 0.0};
        // The post is the building: fixed, so it does not move when the door
        // is shoved against it.
        frame.fixed = true;
        world.addBox(frame);

        RigidBoxDescription leaf{};
        leaf.body_id = door;
        leaf.dimensions_m = {0.9, 2.0, 0.04};
        leaf.material = makeReferenceMaterial(MaterialPreset::Oak, 17);
        // In front of the post, not inside it, and hanging clear of the floor.
        leaf.state.center_of_mass_world_m = {0.5, 1.7, 0.09};
        world.addBox(leaf);

        JoltWorld::HingeDescription pin{};
        pin.a = post;
        pin.b = door;
        pin.point_world_m = {0.05, 1.7, 0.09};
        pin.axis_world = {0.0, 1.0, 0.0};
        pin.lower_rad = lower;
        pin.upper_rad = upper;
        pin.friction_torque_n_m = friction;
        hinge = world.addHinge(pin);
    }

    double angleDegrees() { return world.jointState(hinge).angle_rad * 180.0 / kPi; }

    // A shove, as a change of speed rather than a teleport: this is the
    // playground's "push", and a hinge has to answer it with a turn.
    void shove(double speed_m_s, double at_x_m) {
        RigidSnapshot state = world.snapshot(door);
        state.linear_velocity_m_s = {0.0, 0.0, speed_m_s};
        // A push at the handle is off the pin, so it carries angular momentum
        // about the pin as well: w = (r x v) / r^2 for a body being pushed
        // sideways at that distance.
        state.angular_velocity_rad_s = {0.0, -speed_m_s / at_x_m, 0.0};
        world.applyRigidState(door, state);
        world.wake(door);
    }

    void run(int steps) {
        for (int i = 0; i < steps; ++i) world.step(1.0 / 240.0);
    }
};

void anOffCentrePushSwingsTheDoor() {
    Doorway doorway;
    require(std::abs(doorway.angleDegrees()) < 0.5,
            "the door did not start where it was hung");
    doorway.shove(1.2, 0.9);            // at the far edge, where a handle is
    doorway.run(240);                   // one second
    const double turned = doorway.angleDegrees();
    std::cout << "  pushed at the handle: the door swung " << turned << " degrees\n";
    require(std::abs(turned) > 20.0,
            "a push at the far edge barely moved the door, so the pin is not "
            "turning it");
}

void theDoorStaysOnItsPin() {
    Doorway doorway;
    doorway.shove(3.0, 0.9);
    doorway.run(480);
    // Whatever it did, the hinged edge is still at the post. A body that came
    // off its pin would have sailed away or fallen.
    const RigidSnapshot leaf = doorway.world.snapshot(doorway.door);
    const double out = length(leaf.center_of_mass_world_m - Vec3{0.05, 1.7, 0.09});
    std::cout << "  after a hard shove its middle is " << out
              << " m from the pin (it was hung at 0.45)\n";
    require(std::abs(out - 0.45) < 0.05,
            "the door's middle is no longer a leaf's width from the pin, so it "
            "is not hanging on it any more");
    require(std::abs(leaf.center_of_mass_world_m.y - 1.7) < 0.05,
            "the door fell: a hinge is holding it up and it did not");
}

void aPushThroughThePinDoesNotTurnIt() {
    // The distinction that makes this physics rather than a door animation:
    // WHICH WAY you push decides whether it turns.
    //
    // There is no such thing as pushing a hinged body without turning it just
    // by aiming at its middle -- its middle is half a metre from the pin, so
    // that is a lever arm like any other, and the first version of this test
    // was wrong to expect otherwise. What produces no torque is a push along
    // the arm itself: straight at the pin, there is nothing to turn about.
    Doorway along;
    RigidSnapshot state = along.world.snapshot(along.door);
    state.linear_velocity_m_s = {-1.2, 0.0, 0.0};   // straight back at the pin
    along.world.applyRigidState(along.door, state);
    along.world.wake(along.door);
    along.run(240);
    const double at_the_pin = std::abs(along.angleDegrees());

    Doorway across;
    RigidSnapshot other = across.world.snapshot(across.door);
    other.linear_velocity_m_s = {0.0, 0.0, 1.2};    // the same push, square to it
    across.world.applyRigidState(across.door, other);
    across.world.wake(across.door);
    across.run(240);
    const double square_to_it = std::abs(across.angleDegrees());

    std::cout << "  pushed straight at the pin: " << at_the_pin
              << " degrees; the same push square to the arm: " << square_to_it
              << " degrees\n";
    require(square_to_it > at_the_pin * 5.0 + 5.0,
            "a push aimed straight at the pin turned the door about as much as "
            "one square to it, so the lever arm is doing nothing");
}

void theLimitsStopIt() {
    // A door into a frame: it opens one way, to 45 degrees, and no further.
    Doorway doorway(0.0, 45.0 * kPi / 180.0);
    doorway.shove(4.0, 0.9);
    doorway.run(600);
    const double turned = doorway.angleDegrees();
    std::cout << "  a door limited to 0..45 degrees, shoved hard, reached "
              << turned << " degrees\n";
    require(turned < 46.5, "it swung past the limit its hinge was given");
    require(turned > 30.0, "it did not reach the limit at all, so this proves "
                           "nothing about the limit");
    require(turned > -1.0, "it went the wrong way past the closed stop");
}

void frictionHoldsItWhereItIsLeft() {
    // A free hinge and a stiff one, given the same shove.
    Doorway freely(-kPi, kPi, 0.0);
    freely.shove(1.5, 0.9);
    freely.run(480);
    const double swung = std::abs(freely.angleDegrees());

    Doorway stiff(-kPi, kPi, 120.0);
    stiff.shove(1.5, 0.9);
    stiff.run(480);
    const double dragged = std::abs(stiff.angleDegrees());

    std::cout << "  free hinge: " << swung << " degrees; stiff hinge (120 N m): "
              << dragged << " degrees\n";
    require(swung > dragged + 5.0,
            "a hinge with 120 N m of friction let the door swing as far as a "
            "free one, so the friction is doing nothing");
}

void aHingeNeverOutlivesItsBodies() {
    Doorway doorway;
    require(doorway.world.hasJoint(doorway.hinge), "the hinge was not made");
    require(doorway.world.jointsOn(doorway.door).size() == 1,
            "the door does not know it is hinged");
    // Tear the door off -- which is what a fracture does to a body.
    doorway.world.removeAndDestroy(doorway.door);
    std::cout << "  the door was destroyed; the hinge is "
              << (doorway.world.hasJoint(doorway.hinge) ? "STILL THERE" : "gone with it")
              << "\n";
    require(!doorway.world.hasJoint(doorway.hinge),
            "the hinge outlived the door it was holding, so the world has a "
            "constraint pointing at a body that does not exist");
    require(doorway.world.jointsOn(doorway.post).empty(),
            "the post still thinks it is hinged to something");
    // And the world still runs.
    doorway.run(120);
}

void aPinCanBeTakenOut() {
    Doorway doorway;
    doorway.run(120);
    const RigidSnapshot hung = doorway.world.snapshot(doorway.door);
    require(std::abs(hung.center_of_mass_world_m.y - 1.7) < 0.02,
            "the door did not stay up while it was hinged");
    doorway.world.removeJoint(doorway.hinge);
    doorway.world.wake(doorway.door);
    doorway.run(240);
    const RigidSnapshot dropped = doorway.world.snapshot(doorway.door);
    std::cout << "  pin taken out: the door went from y=" << hung.center_of_mass_world_m.y
              << " to y=" << dropped.center_of_mass_world_m.y << "\n";
    require(dropped.center_of_mass_world_m.y < hung.center_of_mass_world_m.y - 0.2,
            "the pin was taken out and the door hung there anyway");
}

void anAssemblyWorksOnItsSide() {
    // The same doorway, hinged about a horizontal axis instead: a hatch. If the
    // frame were being kept in world terms rather than each body's own, this is
    // where it would come apart.
    JoltWorld world;
    world.setGravity({0.0, -9.80665, 0.0});
    RigidBoxDescription post{};
    post.body_id = 1;
    post.dimensions_m = {2.0, 0.1, 0.1};
    post.material = makeReferenceMaterial(MaterialPreset::Oak, 17);
    post.state.center_of_mass_world_m = {0.0, 2.0, 0.0};
    // The flap hangs just below the beam rather than through it.
    post.fixed = true;
    world.addBox(post);

    RigidBoxDescription flap{};
    flap.body_id = 2;
    flap.dimensions_m = {2.0, 0.04, 0.9};
    flap.material = makeReferenceMaterial(MaterialPreset::Oak, 17);
    flap.state.center_of_mass_world_m = {0.0, 1.92, 0.45};
    world.addBox(flap);

    JoltWorld::HingeDescription pin{};
    pin.a = 1;
    pin.b = 2;
    pin.point_world_m = {0.0, 1.92, 0.0};
    pin.axis_world = {1.0, 0.0, 0.0};      // horizontal: it swings down
    const unsigned hinge = world.addHinge(pin);

    for (int i = 0; i < 1440; ++i) world.step(1.0 / 240.0);   // six seconds
    const double turned = world.jointState(hinge).angle_rad * 180.0 / kPi;
    const RigidSnapshot hangs = world.snapshot(2);
    std::cout << "  a hatch on a horizontal pin fell to " << turned
              << " degrees and hangs at y=" << hangs.center_of_mass_world_m.y << "\n";
    require(std::abs(turned) > 60.0,
            "a flap on a horizontal pin did not swing down under its own weight");
    require(hangs.center_of_mass_world_m.y < 1.7,
            "it turned but did not drop, so it is not hanging from the pin");
    require(length(hangs.center_of_mass_world_m - Vec3{0.0, 1.92, 0.0}) < 0.55,
            "it came off the pin on its way down");
}

} // namespace

int main() {
    try {
        anOffCentrePushSwingsTheDoor();
        std::cout << "[PASS] an off-centre push swings the door\n";
        theDoorStaysOnItsPin();
        std::cout << "[PASS] the door stays on its pin\n";
        aPushThroughThePinDoesNotTurnIt();
        std::cout << "[PASS] a push through the pin does not turn it\n";
        theLimitsStopIt();
        std::cout << "[PASS] the limits stop it\n";
        frictionHoldsItWhereItIsLeft();
        std::cout << "[PASS] friction holds it where it is left\n";
        aHingeNeverOutlivesItsBodies();
        std::cout << "[PASS] a hinge never outlives its bodies\n";
        aPinCanBeTakenOut();
        std::cout << "[PASS] a pin can be taken out\n";
        anAssemblyWorksOnItsSide();
        std::cout << "[PASS] the same mechanism works on a horizontal pin\n";
    } catch (const std::exception &error) {
        std::cout << "hinge tests failed: " << error.what() << std::endl;
        return 1;
    }
    if (failures) {
        std::cout << "\n" << failures << " failed\n";
        return 1;
    }
    std::cout << "\nall hinge tests passed\n";
    return 0;
}
