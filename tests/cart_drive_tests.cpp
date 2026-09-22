// A cart that drives itself (docs/machine-world.md, "One autonomous creature",
// its first increment): the Workshop's cart as three exact bodies on two free
// pins, a battery on its chassis, and a DC motor on its back axle's pin.
//
// 1. Driven, it goes: the motor's torque turns the back wheels, friction with
//    the floor pushes the cart along, and every joule the battery gives is the
//    motor's work plus its heat.
// 2. A water sensor on its controller stops it at a lake's edge.
// 3. A saved world keeps the sensor.

#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"

#include <cmath>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <string>
#include <utility>

using namespace banjo;
using namespace banjo::fastlattice;

namespace {

int failures = 0;
constexpr double kPi = std::numbers::pi;
constexpr double kDt = 1.0 / 240.0;

void require(bool ok, const std::string &why) {
    if (!ok) {
        std::cout << "[FAIL] " << why << std::endl;
        ++failures;
    }
}

// A cylinder's axis is its own y; this turns it onto x, across the cart.
const std::string kOntoX = "[0.7071067811865476, 0.0, 0.0, 0.7071067811865476]";

// The Workshop's cart, without its handle: an oak deck on four mounts, and two
// wheelsets -- an iron axle through two 320 mm oak wheels -- whose axles run
// through the mounts' feet. In the design's own frame, the floor at y = 0, the
// cart facing +z.
std::string cartScene(Vec3 at) {
    const auto x = [&](double v) { return std::to_string(at.x + v); };
    const auto y = [&](double v) { return std::to_string(at.y + v); };
    const auto z = [&](double v) { return std::to_string(at.z + v); };
    std::string mounts;
    for (double mx : {-0.1925, 0.1925})
        for (double mz : {-0.32, 0.32})
            mounts += R"(,{"dimensions_m":[0.0345,0.18,0.0345],"center_local_m":[)" + std::to_string(mx) +
                      ",0.25," + std::to_string(mz) + "]}";
    const auto wheelset = [&](const std::string &name, double wz) {
        const std::string c = std::to_string(wz);
        return R"({"name":")" + name + R"(","material":"oak","position_m":[)" + x(0) + "," + y(0) + "," + z(0) +
               R"(],"parts":[)"
               R"({"shape":"cylinder","material":"iron","dimensions_m":[0.03,0.76,0.03],"center_local_m":[0,0.16,)" + c +
               R"(],"rotation_wxyz":)" + kOntoX + "},"
               R"({"shape":"cylinder","dimensions_m":[0.32,0.06,0.32],"center_local_m":[-0.38,0.16,)" + c +
               R"(],"rotation_wxyz":)" + kOntoX + "},"
               R"({"shape":"cylinder","dimensions_m":[0.32,0.06,0.32],"center_local_m":[0.38,0.16,)" + c +
               R"(],"rotation_wxyz":)" + kOntoX + "}]}";
    };
    return R"([{"name":"chassis","material":"oak","position_m":[)" + x(0) + "," + y(0) + "," + z(0) +
           R"(],"parts":[{"dimensions_m":[0.7,0.04,1.0],"center_local_m":[0,0.36,0]})" + mounts + "]}," +
           wheelset("front wheels", 0.32) + "," + wheelset("back wheels", -0.32) + "]";
}

// The cart on a flat floor, with the marker stone every room of exact bodies
// keeps, well away.
TileImpactRequest flatRoom() {
    TileImpactRequest request;
    request.cell_size_m = 0.05;
    request.backend = BackendKind::CpuParallel;
    SceneBody stone;
    stone.name = "marker";
    stone.shape = BodyShape::Box;
    stone.material = MaterialPreset::Concrete;
    stone.dimensions_m = {0.1, 0.1, 0.1};
    stone.center_m = {3.0, 0.05, -3.0};
    stone.anchored = true;
    request.bodies = {stone};
    request.precise_rigid_scene_json = cartScene({0.0, 0.0, 0.0});
    return request;
}

// Each wheelset on a free pin through its axle, where the cart was built
// (`at`, as cartScene took it); the back one's is returned. The pins are given
// in the world: a pin put anywhere but through the axle locks the wheel.
unsigned pinWheels(LiveWorld &world, Vec3 at = {}) {
    const unsigned front =
        world.hinge("chassis", "front wheels", at + Vec3{0.0, 0.16, 0.32}, {1.0, 0.0, 0.0}, -180.0, 180.0, 0.0);
    const unsigned back =
        world.hinge("chassis", "back wheels", at + Vec3{0.0, 0.16, -0.32}, {1.0, 0.0, 0.0}, -180.0, 180.0, 0.0);
    if (front == 0 || back == 0) throw std::runtime_error("the wheelsets could not be pinned to the chassis");
    return back;
}

const LiveBodyPose &posed(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    for (const LiveBodyPose &pose : poses)
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

void tick(LiveWorld &world) {
    world.step(kDt);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

// A 24 V battery on the chassis and a motor on the back pin: 20 N m at stall,
// 60 turns a minute unloaded -- about a metre a second on 320 mm wheels -- and
// a brake. A demonstration machine: every number is the room's to declare.
struct Machine {
    unsigned store{}, motor{}, control{};
};
Machine fit(LiveWorld &world, unsigned back_pin) {
    Machine m;
    m.store = world.energyStore("battery", "chassis", 100000.0, 100000.0, 24.0, 0.0);
    m.motor = world.motor(back_pin, m.store, 20.0, 60.0 * 2.0 * kPi / 60.0, 40.0);
    m.control = world.control("cart", m.motor);
    if (m.store == 0 || m.motor == 0 || m.control == 0) throw std::runtime_error("the cart's machine would not fit");
    return m;
}

void driveForward(LiveWorld &world, const Machine &m, std::uint64_t seq) {
    LiveWorld::ControlCommand go;
    go.sender = "test";
    go.seq = seq;
    go.power = true;
    go.direction = 1;
    go.setting = 1.0;
    const std::string said = world.operate(m.control, go);
    if (said != "applied") throw std::runtime_error("the controller did not take the command: " + said);
}

void aBatteryCartDrivesOnItsBackAxle() {
    const auto world = LiveWorld::open(flatRoom());
    const unsigned back = pinWheels(*world);
    const Machine m = fit(*world, back);
    for (int i = 0; i < 120; ++i) tick(*world);   // settle on its wheels
    const Vec3 from = posed(world->poses(), "chassis").position_m;
    driveForward(*world, m, 1);
    for (int i = 0; i < 3 * 240; ++i) tick(*world);
    const auto poses = world->poses();
    const LiveBodyPose &chassis = posed(poses, "chassis");
    const double along = chassis.position_m.z - from.z;
    const double speed = chassis.velocity_m_s.z;
    LiveEnergyStore battery;
    for (const LiveEnergyStore &s : world->energyStores()) battery = s;
    LiveMotor motor;
    for (const LiveMotor &mm : world->motors()) motor = mm;
    std::cout << "    3 s driven: " << along << " m forward, " << speed << " m/s; the battery gave " << battery.given_j
              << " J: " << motor.work_j << " J of work and " << motor.heat_j << " J of heat; the motor " << motor.state
              << ", " << motor.torque_n_m << " N m\n";
    require(along > 1.0, "driven for 3 s, the cart went forward: " + std::to_string(along) + " m");
    require(std::abs(chassis.position_m.x - from.x) < 0.1, "and straight on");
    require(speed > 0.5 && speed < 1.1, "at about the motor's unloaded speed on its wheels: " + std::to_string(speed));
    require(std::abs(battery.given_j - (motor.work_j + motor.heat_j)) < 1e-6 * battery.given_j + 1e-9,
            "every joule the battery gave is the motor's work plus its heat");
    for (const LiveJoint &joint : world->joints()) require(joint.attached, "a pin let go");
}

// A basin 32 m across with a lake about 16 m across in it, whose shore rises at
// about 6 degrees, soil to its surface (no sand): ground at 0.2 + 1.6 (d/15.875)^2 metres, d from its middle,
// and the lake up to 0.6 m -- so its edge is 7.94 m out.
constexpr double kHalf = 0.5 * 127 * 0.25;
double groundAt(double d) { return 0.2 + 1.6 * (d / kHalf) * (d / kHalf); }

// The cart 10 m out on the shore, facing the lake (+z, towards the middle), set
// down 2 cm above the ground under its back wheels, the higher.
const Vec3 kShoreAt{0.0, groundAt(10.32) + 0.02, -10.0};
TileImpactRequest shoreRoom() {
    const std::string scene =
        R"({"plasticity":true,"bodies":[{"name":"marker","shape":"box","material":"concrete",)"
        R"("dimensions_m":[0.1,0.1,0.1],"center_m":[12.0,2.0,12.0],"anchored":true}],)"
        R"("terrain":{"generate":{"kind":"basin","nx":128,"nz":128,"cell_m":0.25,"lake_level_m":0.6,"sand_m":0}}})";
    TileImpactRequest request;
    request.cell_size_m = 0.05;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(scene);
    readSceneSettings(scene, request);
    request.precise_rigid_scene_json = cartScene(kShoreAt);
    return request;
}

// Where the cart's front wheels meet the ground: their axle, down one radius.
Vec3 frontContact(const LiveWorld &world) {
    const LiveBodyPose &front = posed(world.poses(), "front wheels");
    return {front.position_m.x, front.position_m.y - 0.16, front.position_m.z};
}

// 2. Its controller carries a sensor on the front of the chassis that reads the
//    lake's depth under it. Driven down the shore, the cart goes until the
//    sensor sees water deeper than a centimetre, then stops on its brake with
//    its front wheels still dry -- and says why. Told forward again it will
//    not go; told back, it backs away from the water.
void theCartStopsAtTheWatersEdge() {
    const auto world = LiveWorld::open(shoreRoom());
    require(world->environment() != nullptr && world->environment()->water() != nullptr, "the basin has its lake");
    const unsigned back = pinWheels(*world, kShoreAt);
    const Machine m = fit(*world, back);
    for (int i = 0; i < 240; ++i) tick(*world);   // settle on the shore, held on the brake
    const LiveBodyPose settled = posed(world->poses(), "chassis");
    // The sensor: 0.6 m beyond the front of the deck, at the deck's height.
    const Vec3 ahead = settled.position_m + Vec3{0.0, 0.0, 1.1};
    require(world->sense(m.control, "water", "chassis", ahead, 0.01, 1), "the sensor would not fit");
    require(!world->sense(m.control, "smoke", "chassis", ahead, 0.01, 1), "a sensor of a kind it does not know is refused");
    driveForward(*world, m, 1);
    double stopped_at = -1.0;
    LiveControl said;
    for (int i = 0; i < 12 * 240; ++i) {
        tick(*world);
        for (const LiveControl &c : world->controls()) said = c;
        if (said.condition.find("water ahead") != std::string::npos) {
            stopped_at = (i + 1) * kDt;
            break;
        }
    }
    require(stopped_at > 0.0, "the sensor never stopped it: " + said.condition);
    for (int i = 0; i < 2 * 240; ++i) tick(*world);   // let it come to rest and hold
    const LiveBodyPose rest = posed(world->poses(), "chassis");
    const Vec3 wheel = frontContact(*world);
    const double wet = world->environment()->waterDepthAt(wheel.x, wheel.z);
    std::cout << "    driven from z " << settled.position_m.z << ": the sensor saw " << said.sensors.front().reading_m
              << " m of water at " << stopped_at << " s; at rest at z " << rest.position_m.z
              << ", the front wheels on ground " << -wheel.z - 7.94 << " m short of the water's edge, "
              << wet << " m of water under them; \"" << said.condition << "\"\n";
    require(rest.position_m.z > settled.position_m.z + 0.5, "it drove towards the lake first");
    require(std::abs(rest.velocity_m_s.z) < 0.02, "it is at rest, held on its brake");
    require(wet < 0.001, "its front wheels are not in the water");
    for (const LiveControl &c : world->controls()) said = c;
    require(said.brake && said.command == 0.0, "stopped on its brake");
    require(said.sensors.size() == 1 && said.sensors.front().sees, "and its sensor still sees the water");

    // Forward again: the sensor still sees water, so it stops at once.
    driveForward(*world, m, 2);
    for (int i = 0; i < 240; ++i) tick(*world);
    const double crept = posed(world->poses(), "chassis").position_m.z - rest.position_m.z;
    require(crept < 0.02, "told forward again at the edge, it would not go: " + std::to_string(crept) + " m");

    // Back: the sensor stops only forward, so it backs away.
    LiveWorld::ControlCommand back_off;
    back_off.sender = "test";
    back_off.seq = 3;
    back_off.direction = -1;
    require(world->operate(m.control, back_off) == "applied", "the controller did not take reverse");
    for (int i = 0; i < 2 * 240; ++i) tick(*world);
    const double backed = rest.position_m.z - posed(world->poses(), "chassis").position_m.z;
    require(backed > 0.5, "told back, it backs away from the water: " + std::to_string(backed) + " m");
    for (const LiveJoint &joint : world->joints()) require(joint.attached, "a pin let go");
}

// 3. A saved world keeps the sensor: opened again from it, the controller has
//    the same sensor at the same place on the chassis, and driven, it still
//    stops at the water's edge.
void aSavedCartKeepsItsSensor() {
    const auto world = LiveWorld::open(shoreRoom());
    const unsigned back = pinWheels(*world, kShoreAt);
    const Machine m = fit(*world, back);
    for (int i = 0; i < 240; ++i) tick(*world);
    const Vec3 ahead = posed(world->poses(), "chassis").position_m + Vec3{0.0, 0.0, 1.1};
    require(world->sense(m.control, "water", "chassis", ahead, 0.01, 1), "the sensor would not fit");
    std::string why;
    const std::string saved = world->snapshot(why);
    require(!saved.empty(), "the world would not save: " + why);
    if (saved.empty()) return;
    const auto again = LiveWorld::open(shoreRoom(), saved);
    require(again->restored().tier == "whole", "the world did not come back whole: " + again->restored().why);
    const auto controls = again->controls();
    require(controls.size() == 1 && controls.front().sensors.size() == 1, "the controller came back without its sensor");
    if (controls.size() != 1 || controls.front().sensors.size() != 1) return;
    const LiveSensor was = world->controls().front().sensors.front();
    const LiveSensor &is = controls.front().sensors.front();
    require(is.kind == was.kind && is.body == was.body && is.depth_m == was.depth_m && is.stops == was.stops,
            "the sensor came back another kind, on another thing, or with another depth");
    require(length(is.at_local_m - was.at_local_m) < 1e-9, "the sensor came back at another place on the chassis");
    require(length(is.at_m - was.at_m) < 1e-6 && is.sees == was.sees,
            "before its first step, the sensor is not where the saved world had it");

    driveForward(*again, {m.store, m.motor, controls.front().id}, 1);
    std::string condition;
    for (int i = 0; i < 12 * 240 && condition.find("water ahead") == std::string::npos; ++i) {
        tick(*again);
        condition = again->controls().front().condition;
    }
    std::cout << "    saved and opened again: \"" << condition << "\"\n";
    require(condition.find("water ahead") != std::string::npos, "opened again, the sensor never stopped it");
}

} // namespace

int main() {
    const std::pair<const char *, void (*)()> tests[] = {
        {"a battery cart drives on its back axle", aBatteryCartDrivesOnItsBackAxle},
        {"the cart stops at the water's edge", theCartStopsAtTheWatersEdge},
        {"a saved cart keeps its sensor", aSavedCartKeepsItsSensor},
    };
    for (const auto &[name, test] : tests) {
        const int before = failures;
        try {
            test();
        } catch (const std::exception &error) {
            std::cout << "[FAIL] " << name << ": " << error.what() << std::endl;
            ++failures;
        }
        if (failures == before) std::cout << "[PASS] " << name << std::endl;
    }
    std::cout << (failures == 0 ? "all passed" : std::to_string(failures) + " failed") << std::endl;
    return failures == 0 ? 0 : 1;
}
