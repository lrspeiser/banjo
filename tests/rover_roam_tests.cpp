// A rover that roams (docs/machine-world.md, "One autonomous creature", its
// second step): a battery cart whose back wheels each have a motor of their
// own, so it steers by driving them differently, and whose front runs on a
// caster that swivels to follow. Exact bodies on pins.
//
// 1. Its two wheels driven alike, it goes straight; driven against each other,
//    it turns on the spot, the caster swinging round to follow.
// 2. Its program roams a lake's shore: for a minute it turns away from the
//    water wherever a sensor sees it, and none of it is ever in the water.
// 3. Turned off, it stops on its brakes; a stale command changes nothing.
// 4. A saved world gives it back roaming, as far into what it was doing.
// 5. With a solar panel on its deck and its battery low, it rests in the sun
//    until the panel has charged it, and roams on; every joule the battery
//    held, took in and gave is accounted for.
// 6. Under a sun with a day, begun at four in the afternoon, it roams on into
//    the night on what its battery holds; low, it rests where it is, and says
//    it is waiting for the morning; nothing charges it in the dark; and when the
//    morning sun has charged it, it roams on.
//
// And a robot of the same parts, drawn short so that it can turn: told to go to
// a stool and put its torso down on it, it comes round onto the stool, drives
// at it, stops within reach and lowers the torso until the seat stops it --
// short of the angle it was reaching for, because the stool is carrying it --
// and holds there.
// 7. Asked to do something for a while (behave) -- by a person at its panel,
//    or by whatever thinks for it -- it does that instead of deciding for
//    itself, and goes on as it would have when the while is up: asked to back
//    off it backs off; asked to wait it holds still, on, until asked otherwise;
//    asked to face a point it turns on the spot until its front is towards it
//    and waits there; a stale ask changes nothing; turned off it drops the
//    ask; and a saved world gives it back doing what it was asked, as far in.
// 8. An ask that is not a person's never drives it into the water: asked by
//    its routine or its decider to approach a point in the lake, its reflexes
//    have it when a sensor sees water -- it backs off and turns away -- and no
//    wheel gets wet; three scares and it gives the ask up.
// 9. A person's order does drive it into the water. The same ask, marked as a
//    person's, takes it in until it is wet, its reflexes never touching it;
//    and the moment the order is lifted the reflex has it back and it comes
//    out. The order is the one bit of difference between 8 and 9.

#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/PreciseRigidScene.hpp"
#include "fastlattice/TileImpactScene.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <iostream>
#include <memory>
#include <numbers>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

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

// A cylinder's axis is its own y; this turns it onto x, across the rover.
const nlohmann::json kOntoX = {0.7071067811865476, 0.0, 0.0, 0.7071067811865476};

nlohmann::json box(const std::string &name, Vec3 size, Vec3 at, const std::string &material = "") {
    nlohmann::json part = {{"name", name},
                           {"dimensions_m", {size.x, size.y, size.z}},
                           {"center_local_m", {at.x, at.y, at.z}}};
    if (!material.empty()) part["material"] = material;
    return part;
}
nlohmann::json roundAcross(const std::string &name, double diameter, double width, Vec3 at,
                           const std::string &material = "") {
    nlohmann::json part = {{"name", name},
                           {"shape", "cylinder"},
                           {"dimensions_m", {diameter, width, diameter}},
                           {"center_local_m", {at.x, at.y, at.z}},
                           {"rotation_wxyz", kOntoX}};
    if (!material.empty()) part["material"] = material;
    return part;
}
nlohmann::json body(const std::string &name, const std::string &material, Vec3 at, nlohmann::json parts) {
    return {{"name", name}, {"material", material}, {"position_m", {at.x, at.y, at.z}}, {"parts", std::move(parts)}};
}

// The rover, in its own frame as drawn: the floor at y = 0, facing +z, its
// left the +x side. An oak deck on two bearing mounts at the back and a caster
// mount at the front; each back wheel a 320 mm oak wheel on an iron stub
// through its mount; the caster an iron fork on a swivel under the front, with
// a 160 mm iron wheel trailing 60 mm behind the swivel's axis -- iron, as a
// real caster's is: a light oak one sank into the ground under the rover's
// weight at steps longer than the page's.
std::string roverScene(Vec3 at) {
    const nlohmann::json chassis = body(
        "rover", "oak", at,
        nlohmann::json::array({box("deck", {0.7, 0.04, 1.0}, {0.0, 0.36, 0.0}),
                               box("solar panel", {0.4, 0.01, 0.5}, {0.0, 0.385, -0.05}, "glass"),
                               box("left mount", {0.0345, 0.18, 0.0345}, {0.1925, 0.25, -0.32}),
                               box("right mount", {0.0345, 0.18, 0.0345}, {-0.1925, 0.25, -0.32}),
                               box("caster mount", {0.10, 0.03, 0.10}, {0.0, 0.325, 0.38})}));
    const auto wheel = [&](const std::string &name, double side) {
        return body(name, "oak", at,
                    nlohmann::json::array({roundAcross("stub", 0.03, 0.20, {side * 0.26, 0.16, -0.32}, "iron"),
                                           roundAcross("wheel", 0.32, 0.06, {side * 0.38, 0.16, -0.32})}));
    };
    const nlohmann::json fork = body(
        "rover: caster", "iron", at,
        nlohmann::json::array({box("top", {0.08, 0.02, 0.08}, {0.0, 0.30, 0.38}),
                               box("left cheek", {0.012, 0.22, 0.05}, {0.035, 0.18, 0.335}),
                               box("right cheek", {0.012, 0.22, 0.05}, {-0.035, 0.18, 0.335}),
                               roundAcross("pin", 0.012, 0.082, {0.0, 0.08, 0.32})}));
    const nlohmann::json caster_wheel =
        body("rover: caster wheel", "iron", at,
             nlohmann::json::array({roundAcross("wheel", 0.16, 0.04, {0.0, 0.08, 0.32})}));
    return nlohmann::json::array({chassis, wheel("rover: left wheel", 1.0), wheel("rover: right wheel", -1.0), fork,
                                  caster_wheel})
        .dump();
}

// The rover on a flat floor, with the marker stone every room of exact bodies
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
    request.precise_rigid_scene_json = roverScene({0.0, 0.0, 0.0});
    return request;
}

struct Pins {
    unsigned left{}, right{}, swivel{}, caster{};
};
// Each wheel on its pin through its mount, and the caster on its swivel and its
// axle, where the rover was built (`at`).
Pins pinUp(LiveWorld &world, Vec3 at = {}, Quat facing = {}) {
    Pins p;
    p.left = world.hinge("rover", "rover: left wheel", at + facing.rotate({0.1925, 0.16, -0.32}), facing.rotate({1.0, 0.0, 0.0}));
    p.right = world.hinge("rover", "rover: right wheel", at + facing.rotate({-0.1925, 0.16, -0.32}), facing.rotate({1.0, 0.0, 0.0}));
    p.swivel = world.hinge("rover", "rover: caster", at + facing.rotate({0.0, 0.31, 0.38}), facing.rotate({0.0, 1.0, 0.0}));
    p.caster = world.hinge("rover: caster", "rover: caster wheel", at + facing.rotate({0.0, 0.08, 0.32}), facing.rotate({1.0, 0.0, 0.0}));
    if (!p.left || !p.right || !p.swivel || !p.caster) throw std::runtime_error("the rover could not be pinned");
    return p;
}

// A 24 V battery in the chassis and a motor on each back wheel's pin: 20 N m at
// stall, 60 turns a minute unloaded, about a metre a second on 320 mm wheels,
// and a brake; each worked by a controller of its own.
struct Machine {
    unsigned store{}, left_motor{}, right_motor{}, left{}, right{};
};
Machine fit(LiveWorld &world, const Pins &pins) {
    Machine m;
    m.store = world.energyStore("battery", "rover", 100000.0, 100000.0, 24.0, 0.0);
    m.left_motor = world.motor(pins.left, m.store, 20.0, 2.0 * kPi, 40.0);
    m.right_motor = world.motor(pins.right, m.store, 20.0, 2.0 * kPi, 40.0);
    m.left = world.control("left wheel", m.left_motor);
    m.right = world.control("right wheel", m.right_motor);
    if (!m.store || !m.left_motor || !m.right_motor || !m.left || !m.right)
        throw std::runtime_error("the rover's machine would not fit");
    return m;
}

void tell(LiveWorld &world, unsigned control, int direction, std::uint64_t seq, double setting = 1.0) {
    LiveWorld::ControlCommand c;
    c.sender = "test";
    c.seq = seq;
    c.power = true;
    c.direction = direction;
    c.setting = setting;
    const std::string said = world.operate(control, c);
    if (said != "applied") throw std::runtime_error("a controller did not take the command: " + said);
}

const LiveBodyPose &posed(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    for (const LiveBodyPose &pose : poses)
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

// Which way a body faces, about the vertical: the angle of its own +z from the
// world's +z towards +x, radians.
double heading(const LiveBodyPose &pose) {
    const double w = pose.orientation_wxyz[0], x = pose.orientation_wxyz[1], y = pose.orientation_wxyz[2],
                 z = pose.orientation_wxyz[3];
    const double fx = 2.0 * (x * z + w * y), fz = 1.0 - 2.0 * (x * x + y * y);
    return std::atan2(fx, fz);
}
double turnedBy(double from, double to) {
    double d = to - from;
    while (d > kPi) d -= 2.0 * kPi;
    while (d < -kPi) d += 2.0 * kPi;
    return d;
}

void tick(LiveWorld &world) {
    world.step(kDt);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

void itGoesStraightAndTurnsOnTheSpot() {
    const auto world = LiveWorld::open(flatRoom());
    const Pins pins = pinUp(*world);
    const Machine m = fit(*world, pins);
    for (int i = 0; i < 120; ++i) tick(*world);   // settle on its wheels and caster
    LiveBodyPose from = posed(world->poses(), "rover");
    tell(*world, m.left, 1, 1);
    tell(*world, m.right, 1, 1);
    for (int i = 0; i < 3 * 240; ++i) tick(*world);
    LiveBodyPose to = posed(world->poses(), "rover");
    const double along = to.position_m.z - from.position_m.z;
    const double aside = to.position_m.x - from.position_m.x;
    const double veered = turnedBy(heading(from), heading(to)) * 180.0 / kPi;
    std::cout << "    both wheels forward for 3 s: " << along << " m forward, " << aside << " m aside, turned "
              << veered << " degrees\n";
    require(along > 2.0, "driven straight for 3 s, it went forward: " + std::to_string(along) + " m");
    require(std::abs(aside) < 0.15 && std::abs(veered) < 5.0, "and straight on");

    // Against each other: it turns on the spot. From rest, so the wheel told
    // back is not first stopping from forward.
    tell(*world, m.left, 0, 2);
    tell(*world, m.right, 0, 2);
    for (int i = 0; i < 2 * 240; ++i) tick(*world);
    tell(*world, m.left, 1, 3);
    tell(*world, m.right, -1, 3);
    from = posed(world->poses(), "rover");
    double swept = 0.0, last = heading(from), furthest = 0.0;
    for (int i = 0; i < 3 * 240; ++i) {
        tick(*world);
        const LiveBodyPose now = posed(world->poses(), "rover");
        swept += turnedBy(last, heading(now));
        last = heading(now);
        furthest = std::max(furthest, length(now.position_m - from.position_m));
    }
    std::cout << "    from rest, left forward and right back for 3 s: turned " << swept * 180.0 / kPi
              << " degrees, never more than " << furthest << " m from where it began\n";
    // Its iron caster wheel scrubs as it swings round to follow, so it turns on
    // the spot slowly: 68 degrees in the 3 s here (the oak wheel it had first
    // let it turn 200, but sank into the ground at the page's longer steps).
    require(swept * 180.0 / kPi < -45.0,
            "driven against each other, it turns right, the left wheel forward: " +
                std::to_string(swept * 180.0 / kPi) + " degrees");
    require(furthest < 1.5, "and turns near where it is: " + std::to_string(furthest) + " m");
    for (const LiveJoint &joint : world->joints()) require(joint.attached, "a pin let go");
}

// A basin 32 m across holding a lake to `lake_m`: ground at 0.2 + 1.6
// (d/15.875)^2 metres, d from its middle, soil to its surface. At 0.35 m the
// lake is 9.7 m across, its edge 4.86 m out.
constexpr double kHalf = 0.5 * 127 * 0.25;
double groundAt(double d) { return 0.2 + 1.6 * (d / kHalf) * (d / kHalf); }
constexpr double kLakeM = 0.35;
double edgeOfLake() { return kHalf * std::sqrt((kLakeM - 0.2) / 1.6); }

// The rover 9 m out on the shore facing the lake (+z), set down 2 cm above the
// ground under its back wheels, the higher: it settles forward onto its caster.
const Vec3 kShoreAt{0.0, groundAt(9.32) + 0.02, -9.0};
TileImpactRequest shoreRoom() {
    const std::string scene =
        R"({"plasticity":true,"bodies":[{"name":"marker","shape":"box","material":"concrete",)"
        R"("dimensions_m":[0.1,0.1,0.1],"center_m":[12.0,2.0,12.0],"anchored":true}],)"
        R"("terrain":{"generate":{"kind":"basin","nx":128,"nz":128,"cell_m":0.25,"lake_level_m":0.35,"sand_m":0}}})";
    TileImpactRequest request;
    request.cell_size_m = 0.05;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(scene);
    readSceneSettings(scene, request);
    request.precise_rigid_scene_json = roverScene(kShoreAt);
    return request;
}

// The rover on its shore with its machine, and its program: a water sensor at
// each front corner, half a metre ahead of the deck and 0.55 m either side of
// its middle, looking down for more than 3 mm of water -- the depth the water
// itself calls wet. Wider than its wheels, and by more than they cut inside
// the line the front takes on a curve: at 0.25 m and then 0.45 m, and looking
// for a centimetre, a back wheel ran along the shore into water no sensor had
// seen.
struct Rover {
    std::unique_ptr<LiveWorld> world;
    Machine machine;
    unsigned program{};
};
Rover roverOnTheShore() {
    Rover r;
    r.world = LiveWorld::open(shoreRoom());
    const Pins pins = pinUp(*r.world, kShoreAt);
    r.machine = fit(*r.world, pins);
    r.program = r.world->program("rover", "roam", r.machine.left, r.machine.right, "rover", 1.0, 8.0);
    if (r.program == 0) throw std::runtime_error("the rover's program would not go on");
    for (const double side : {0.55, -0.55})
        if (!r.world->programSense(r.program, "water", "rover", kShoreAt + Vec3{side, 0.36, 1.0}, 0.003))
            throw std::runtime_error("a sensor would not fit");
    for (int i = 0; i < 240; ++i) tick(*r.world);   // settle onto its caster
    return r;
}

LiveProgram programOf(const LiveWorld &world, unsigned id) {
    for (const LiveProgram &p : world.programs())
        if (p.id == id) return p;
    throw std::runtime_error("no program " + std::to_string(id));
}

void runIt(LiveWorld &world, unsigned program, bool power, std::uint64_t seq) {
    LiveWorld::ProgramCommand c;
    c.sender = "test";
    c.seq = seq;
    c.power = power;
    const std::string said = world.run(program, c);
    if (said != "applied") throw std::runtime_error("the program did not take the command: " + said);
}

// The deepest water under any of its wheels, where each meets the ground, and
// which wheel that is.
double wettest(const LiveWorld &world, std::string *which = nullptr) {
    double most = 0.0;
    const auto poses = world.poses();
    for (const char *name : {"rover: left wheel", "rover: right wheel", "rover: caster wheel"}) {
        const LiveBodyPose &wheel = posed(poses, name);
        const double here = world.environment()->waterDepthAt(wheel.position_m.x, wheel.position_m.z);
        if (here > most && which != nullptr) *which = name;
        most = std::max(most, here);
    }
    return most;
}

void itRoamsTheShoreAndNeverGetsWet() {
    Rover r = roverOnTheShore();
    LiveWorld &world = *r.world;
    require(world.environment() != nullptr && world.environment()->water() != nullptr, "the basin has its lake");
    LiveProgram said = programOf(world, r.program);
    require(said.doing == "stopped" && !said.power, "a program starts off: " + said.doing);
    require(said.sensors.size() == 2 && said.sensors[0].side == 1 && said.sensors[1].side == -1,
            "its sensors are on its left and its right");
    runIt(world, r.program, true, 1);
    require(programOf(world, r.program).doing == "going forward", "turned on, it goes forward");
    double path = 0.0, wet = 0.0, nearest = 1e9, furthest = 0.0;
    Vec3 was = posed(world.poses(), "rover").position_m;
    std::vector<std::string> seen, trace;
    for (int i = 0; i < 60 * 240; ++i) {
        tick(world);
        if (i % 24 != 23) continue;   // every tenth of a second
        const LiveBodyPose now = posed(world.poses(), "rover");
        path += length(now.position_m - was);
        was = now.position_m;
        const double out = std::hypot(now.position_m.x, now.position_m.z);
        nearest = std::min(nearest, out);
        furthest = std::max(furthest, out);
        std::string which;
        const double here = wettest(world, &which);
        const LiveProgram now_said = programOf(world, r.program);
        {
            const auto ps = world.poses();
            const LiveBodyPose &lw = posed(ps, "rover: left wheel");
            const LiveBodyPose &rw = posed(ps, "rover: right wheel");
            char line[400];
            std::snprintf(line, sizeof line,
                          "      %6.2f s %-14s at (%6.2f %6.2f) out %5.2f heading %7.1f pitch %5.1f roll %5.1f "
                          "sensors %4.1f/%4.1f mm; wheels out %5.2f %5.2f, wet %4.1f mm",
                          (i + 1) * kDt, now_said.doing.c_str(), now.position_m.x, now.position_m.z, out,
                          heading(now) * 180.0 / kPi, now_said.pitch_deg, now_said.roll_deg,
                          now_said.sensors[0].reading_m * 1000.0, now_said.sensors[1].reading_m * 1000.0,
                          std::hypot(lw.position_m.x, lw.position_m.z), std::hypot(rw.position_m.x, rw.position_m.z),
                          here * 1000.0);
            trace.push_back(line);
            if (trace.size() > 40) trace.erase(trace.begin());
        }
        if (here > 0.003 && wet <= 0.003) {
            std::cout << "      first wet at " << (i + 1) * kDt << " s: " << which << " in " << here * 1000.0
                      << " mm, " << now_said.doing << " (" << now_said.why << "); the four seconds before:\n";
            for (const std::string &line : trace) std::cout << line << "\n";
        }
        wet = std::max(wet, here);
        const std::string doing = now_said.doing;
        if (seen.empty() || seen.back() != doing) seen.push_back(doing);
    }
    said = programOf(world, r.program);
    double given = 0.0, spent = 0.0;
    for (const LiveEnergyStore &s : world.energyStores()) given += s.given_j;
    for (const LiveMotor &m : world.motors()) spent += m.work_j + m.heat_j;
    std::cout << "    roamed for 60 s: " << path << " m, " << said.turns << " turns away, from " << nearest
              << " m to " << furthest << " m out (the lake's edge is " << edgeOfLake() << " m out); at most "
              << wet * 1000.0 << " mm of water under a wheel; the battery gave " << given << " J; now \""
              << said.doing << "\": " << said.why << "\n";
    require(path > 15.0, "it roamed: " + std::to_string(path) + " m in a minute");
    require(said.turns >= 3, "it turned away from something again and again: " + std::to_string(said.turns));
    require(wet <= 0.003, "none of it was ever in the water: " + std::to_string(wet * 1000.0) + " mm");
    require(furthest < 14.0, "it kept to the basin: " + std::to_string(furthest) + " m out");
    require(std::find(seen.begin(), seen.end(), "turning left") != seen.end() ||
                std::find(seen.begin(), seen.end(), "turning right") != seen.end(),
            "it turned");
    require(std::abs(given - spent) < 1e-6 * given + 1e-9, "every joule the battery gave went to its motors");
    for (const LiveJoint &joint : world.joints()) require(joint.attached, "a pin let go");

    // 3. Turned off, it stops on its brakes; a command no newer is dropped.
    runIt(world, r.program, false, 2);
    for (int i = 0; i < 2 * 240; ++i) tick(world);
    said = programOf(world, r.program);
    const LiveBodyPose still = posed(world.poses(), "rover");
    require(said.doing == "stopped", "turned off, it stops: " + said.doing);
    require(length(still.velocity_m_s) < 0.02, "and is still: " + std::to_string(length(still.velocity_m_s)));
    for (const LiveControl &c : world.controls()) require(c.brake && !c.power, "its wheels are off, on their brakes");
    LiveWorld::ProgramCommand late;
    late.sender = "test";
    late.seq = 2;
    late.power = true;
    require(world.run(r.program, late) == "stale", "a command no newer than the last is stale");
    require(programOf(world, r.program).doing == "stopped", "and changes nothing");
}

// 4. Saved mid-roam and opened again: the same program, as far into what it
//    was doing, its sensors where they were -- and it roams on, dry.
void aSavedRoverRoamsOn() {
    Rover r = roverOnTheShore();
    runIt(*r.world, r.program, true, 1);
    for (int i = 0; i < 20 * 240; ++i) tick(*r.world);
    std::string why;
    const std::string saved = r.world->snapshot(why);
    require(!saved.empty(), "the world would not save: " + why);
    if (saved.empty()) return;
    const LiveProgram was = programOf(*r.world, r.program);
    const auto again = LiveWorld::open(shoreRoom(), saved);
    require(again->restored().tier == "whole", "the world did not come back whole: " + again->restored().why);
    const LiveProgram is = programOf(*again, r.program);
    require(is.power && is.doing == was.doing && is.why == was.why && is.turns == was.turns &&
                is.doing_s == was.doing_s && is.turned_deg == was.turned_deg,
            "it came back doing something else: " + is.doing + " (it was " + was.doing + ")");
    require(is.sensors.size() == 2 && length(is.sensors[0].at_m - was.sensors[0].at_m) < 1e-6 &&
                std::abs(is.pitch_deg - was.pitch_deg) < 1e-6,
            "its sensors and its slope came back as they were");
    double wet = 0.0;
    for (int i = 0; i < 20 * 240; ++i) {
        tick(*again);
        if (i % 24 == 23) wet = std::max(wet, wettest(*again));
    }
    const LiveProgram after = programOf(*again, r.program);
    std::cout << "    saved after 20 s " << was.doing << " (" << was.turns << " turns); opened again, 20 s on: "
              << after.turns << " turns, at most " << wet * 1000.0 << " mm of water under a wheel\n";
    require(after.turns > was.turns, "opened again, it roams on, turning away as before");
    require(wet <= 0.003, "and stays out of the water");
}

// 5. The rover with a solar panel on its deck -- 0.2 m2, a fifth of the
//    sunlight into charge -- under a sun 50 degrees up, and a small battery
//    already down to 28%: told to rest below a quarter and roam again at
//    three fifths. Roaming draws more than the panel gives, so it runs down,
//    stops where it is on its brakes, rests while the sun charges it, and goes
//    on. Nothing else puts energy in or takes it out.
void itRestsInTheSunAndRoamsOn() {
    const auto world = LiveWorld::open(shoreRoom());
    const Pins pins = pinUp(*world, kShoreAt);
    Machine m;
    m.store = world->energyStore("battery", "rover", 5000.0, 1400.0, 24.0, 0.0);
    m.left_motor = world->motor(pins.left, m.store, 20.0, 2.0 * kPi, 40.0);
    m.right_motor = world->motor(pins.right, m.store, 20.0, 2.0 * kPi, 40.0);
    m.left = world->control("left wheel", m.left_motor);
    m.right = world->control("right wheel", m.right_motor);
    const unsigned panel =
        world->solarPanel("panel", "rover", m.store, kShoreAt + Vec3{0.0, 0.39, -0.05}, {0.0, 1.0, 0.0}, 0.2, 0.2);
    const unsigned program = world->program("rover", "roam", m.left, m.right, "rover", 1.0, 8.0, 0.25, 0.6);
    require(panel != 0 && program != 0, "the panel or the program would not go on");
    require(world->program("twin", "roam", m.left, m.right, "rover", 1.0, 8.0, 0.5, 0.4) == 0,
            "a program that would rest until less than it rests below is refused");
    for (const double side : {0.55, -0.55})
        require(world->programSense(program, "water", "rover", kShoreAt + Vec3{side, 0.36, 1.0}, 0.003),
                "a sensor would not fit");
    require(world->setSun(50.0, 200.0, 1000.0), "the sun would not go in the sky");
    for (int i = 0; i < 240; ++i) tick(*world);
    const double began = 1400.0;   // as the battery was made; the sun has been on it since
    runIt(*world, program, true, 1);
    std::vector<std::string> seen;
    double rested_from = -1.0, charged_to = 0.0, moved_while_resting = 0.0, wet = 0.0;
    Vec3 rested_at{};
    bool stopped = false;
    for (int i = 0; i < 180 * 240; ++i) {
        tick(*world);
        const LiveProgram said = programOf(*world, program);
        if (seen.empty() || seen.back() != said.doing) {
            seen.push_back(said.doing);
            if (said.doing == "resting") {
                rested_from = world->energyStores().front().charge_j;
                stopped = false;
            }
        }
        // Once it has come to a stop on its brakes -- a second in -- it stays put.
        if (said.doing == "resting" && said.doing_s >= 1.0 && i % 24 == 0) {
            const Vec3 at = posed(world->poses(), "rover").position_m;
            if (!stopped) rested_at = at;
            stopped = true;
            moved_while_resting = std::max(moved_while_resting, length(at - rested_at));
        }
        if (said.doing == "resting") charged_to = std::max(charged_to, world->energyStores().front().charge_j);
        if (i % 24 == 23) wet = std::max(wet, wettest(*world));
        // Rested, and roaming again a while: enough seen.
        if (said.rests >= 1 && said.doing != "resting" && seen.size() >= 3 && said.doing_s > 5.0) break;
    }
    const LiveProgram said = programOf(*world, program);
    const LiveEnergyStore store = world->energyStores().front();
    LiveSolarPanel p;
    for (const LiveSolarPanel &each : world->solarPanels()) p = each;
    std::string order;
    for (const std::string &each : seen) order += (order.empty() ? "" : ", ") + each;
    std::cout << "    from " << began << " J: " << order << "; it rested from " << rested_from << " J up to "
              << charged_to << " J, the panel giving " << p.power_w << " W of " << p.sunlight_w
              << " W of sun; now " << store.charge_j << " J (took in " << store.taken_j << ", gave "
              << store.given_j << "); at most " << wet * 1000.0 << " mm of water under a wheel\n";
    require(said.rests >= 1 && rested_from > 0.0, "its battery ran low and it rested: " + order);
    require(rested_from < 0.25 * 5000.0 + 50.0, "it rested when the battery was down to a quarter");
    require(charged_to >= 0.6 * 5000.0 - 1.0, "resting, the sun charged it back to three fifths");
    require(moved_while_resting < 0.02, "resting, it stayed where it stopped: " + std::to_string(moved_while_resting));
    require(said.doing != "resting" && std::find(seen.begin(), seen.end(), "resting") != seen.end(),
            "and then it roamed on");
    require(std::abs(store.charge_j - (began + store.taken_j - store.given_j)) < 1e-6,
            "what the battery holds is what it held, plus what it took in, less what it gave");
    require(std::abs(store.taken_j - p.collected_j) < 1e-9, "and all it took in came from its panel");
    require(wet <= 0.003, "and it stayed out of the water");
}

// A sun whose day is four minutes long, 60 degrees up at noon, from four in
// the afternoon; a 5 kJ battery at 3.5 kJ; resting below a quarter until two
// fifths.
void itRestsThroughTheNightAndRoamsOnInTheMorning() {
    const auto world = LiveWorld::open(shoreRoom());
    const Pins pins = pinUp(*world, kShoreAt);
    Machine m;
    m.store = world->energyStore("battery", "rover", 5000.0, 3500.0, 24.0, 0.0);
    m.left_motor = world->motor(pins.left, m.store, 20.0, 2.0 * kPi, 40.0);
    m.right_motor = world->motor(pins.right, m.store, 20.0, 2.0 * kPi, 40.0);
    m.left = world->control("left wheel", m.left_motor);
    m.right = world->control("right wheel", m.right_motor);
    const unsigned panel =
        world->solarPanel("panel", "rover", m.store, kShoreAt + Vec3{0.0, 0.39, -0.05}, {0.0, 1.0, 0.0}, 0.2, 0.2);
    const unsigned program = world->program("rover", "roam", m.left, m.right, "rover", 1.0, 8.0, 0.25, 0.4);
    require(panel != 0 && program != 0, "the panel or the program would not go on");
    for (const double side : {0.55, -0.55})
        require(world->programSense(program, "water", "rover", kShoreAt + Vec3{side, 0.36, 1.0}, 0.003),
                "a sensor would not fit");
    require(world->setDay(240.0, 60.0, 16.0, 1000.0), "the day would not start");
    for (int i = 0; i < 240; ++i) tick(*world);
    runIt(*world, program, true, 1);
    struct When {
        double t{-1.0}, hour{}, charge_j{}, taken_j{};
    };
    When sunset, rested, sunrise, woke;
    const auto now = [&]() {
        const LiveEnergyStore store = world->energyStores().front();
        return When{world->time_s(), world->sun().hour, store.charge_j, store.taken_j};
    };
    std::vector<std::string> said_resting;
    double moved_while_resting = 0.0, wet = 0.0;
    Vec3 rested_at{};
    bool stopped = false, up = true;
    for (int i = 0; i < 300 * 240; ++i) {
        tick(*world);
        const LiveProgram said = programOf(*world, program);
        const bool is_up = world->sun().elevation_deg > 0.0;
        if (up && !is_up && sunset.t < 0.0) sunset = now();
        if (!up && is_up && sunset.t >= 0.0 && sunrise.t < 0.0) sunrise = now();
        up = is_up;
        if (said.doing == "resting") {
            if (rested.t < 0.0) rested = now();
            if (said_resting.empty() || said_resting.back() != said.why) said_resting.push_back(said.why);
            // Once it has come to a stop on its brakes -- a second in -- it stays put.
            if (said.doing_s >= 1.0 && i % 24 == 0) {
                const Vec3 at = posed(world->poses(), "rover").position_m;
                if (!stopped) rested_at = at;
                stopped = true;
                moved_while_resting = std::max(moved_while_resting, length(at - rested_at));
            }
        } else if (rested.t >= 0.0 && woke.t < 0.0) {
            woke = now();
        }
        if (i % 24 == 23) wet = std::max(wet, wettest(*world));
        if (woke.t >= 0.0 && said.doing_s > 5.0) break;
    }
    const LiveEnergyStore store = world->energyStores().front();
    LiveSolarPanel p;
    for (const LiveSolarPanel &each : world->solarPanels()) p = each;
    const auto told = [](const char *what, const When &w) {
        std::cout << "    " << what << " at " << w.hour << " o'clock (t = " << w.t << " s), the battery " << w.charge_j
                  << " J, having taken in " << w.taken_j << " J\n";
    };
    told("the sun set", sunset);
    told("it rested", rested);
    told("the sun rose", sunrise);
    told("it woke", woke);
    for (const std::string &why : said_resting) std::cout << "    resting, it said: " << why << "\n";
    std::cout << "    it moved " << moved_while_resting * 1000.0 << " mm while resting; at most " << wet * 1000.0
              << " mm of water under a wheel\n";
    require(sunset.t >= 0.0 && rested.t > sunset.t && sunrise.t > rested.t && woke.t > sunrise.t,
            "the sun set, it ran low in the night and rested, the sun rose, and it woke");
    require(!said_resting.empty() &&
                said_resting.front() == "its battery is low and the sun is down, so it rests until morning",
            "resting in the night, it said it waits for the morning");
    require(sunrise.taken_j == sunset.taken_j, "nothing charged it in the dark");
    require(rested.charge_j < 0.25 * 5000.0 + 50.0 && woke.charge_j >= 0.4 * 5000.0 - 1.0,
            "it rested at a quarter and woke at two fifths");
    require(moved_while_resting < 0.02, "resting, it stayed where it stopped");
    require(std::abs(store.charge_j - (3500.0 + store.taken_j - store.given_j)) < 1e-6,
            "what the battery holds is what it held, plus what it took in, less what it gave");
    require(std::abs(store.taken_j - p.collected_j) < 1e-9, "and all it took in came from its panel");
    require(wet <= 0.003, "and it stayed out of the water");
}

// A robot that goes somewhere and sits down.
//
// Not the rover: the rover cannot hold a line after a turn. Its caster is
// 0.70 m in front of the axle its wheels turn about, so coming round on the
// spot swings the caster through a wide circle and leaves it lying across the
// way the machine then wants to go; driving off, it scrubs round and pulls the
// machine about 20 degrees off for every metre travelled. Measured that way, a
// rover told to go to a stool 3.8 m away zigzagged for 40 s and arrived 30
// degrees off, its torso coming down beside the stool rather than on it.
//
// So the robot is the same machine drawn short: a driven wheel on each side and
// one small caster, 0.27 m in front of the axle instead of 0.70 m, so it
// swings through a quarter of the circle and scrubs with a quarter of the arm.
// Three points on the ground, and no more: a caster at each end was built and
// measured first, and it could not turn at all -- four points on a rigid deck
// are one too many, the casters took the weight, and the driven wheels span at
// their unloaded speed while the robot stood still. Everything else is the
// rover's: a wheel on each side driven by a motor of its own, oak on iron
// stubs, and a battery in the deck.
//
// Its torso is an oak bar 500 mm long standing up from a pin on a mast at the
// front of the deck, which a motor of its own swings forward and down. Nothing
// about it is a person; it is the simplest thing a machine can have that it can
// put down on something else. The mast holds the pin 600 mm up, above the
// 450 mm seat it is going to reach, because a torso swinging up from below the
// seat catches its near edge: measured, it stopped 15 mm off that edge with its
// far end still 127 mm above the seat, and called itself sat down. Swinging
// from above, the bar comes down onto the seat with the rest of it in the air.
std::string robotScene(Vec3 at) {
    const nlohmann::json chassis = body(
        "robot", "oak", at,
        nlohmann::json::array({box("deck", {0.40, 0.06, 0.50}, {0.0, 0.29, -0.05}),
                               box("left mount", {0.03, 0.16, 0.03}, {0.175, 0.20, -0.20}),
                               box("right mount", {0.03, 0.16, 0.03}, {-0.175, 0.20, -0.20}),
                               box("caster mount", {0.08, 0.03, 0.08}, {0.0, 0.245, 0.15}),
                               box("mast", {0.10, 0.29, 0.10}, {0.0, 0.465, 0.15})}));
    const auto wheel = [&](const std::string &name, double side) {
        return body(name, "oak", at,
                    nlohmann::json::array({roundAcross("stub", 0.03, 0.18, {side * 0.24, 0.16, -0.20}, "iron"),
                                           roundAcross("wheel", 0.32, 0.06, {side * 0.33, 0.16, -0.20})}));
    };
    // The caster: a fork on a swivel under the front of the deck, its 100 mm
    // iron wheel trailing 35 mm behind the swivel, so it follows.
    const nlohmann::json caster =
        body("robot: caster", "iron", at,
             nlohmann::json::array({box("top", {0.06, 0.02, 0.06}, {0.0, 0.215, 0.15}),
                                    box("left cheek", {0.010, 0.17, 0.04}, {0.026, 0.125, 0.115}),
                                    box("right cheek", {0.010, 0.17, 0.04}, {-0.026, 0.125, 0.115}),
                                    roundAcross("pin", 0.010, 0.062, {0.0, 0.05, 0.115})}));
    const nlohmann::json caster_wheel =
        body("robot: caster wheel", "iron", at,
             nlohmann::json::array({roundAcross("wheel", 0.10, 0.03, {0.0, 0.05, 0.115})}));
    return nlohmann::json::array({chassis, wheel("robot: left wheel", 1.0), wheel("robot: right wheel", -1.0),
                                  caster, caster_wheel,
                                  body("robot: torso", "oak", at,
                                       nlohmann::json::array({box("bar", {0.10, 0.50, 0.05}, {0.0, 0.85, 0.15})}))})
        .dump();
}

struct Robot {
    std::unique_ptr<LiveWorld> world;
    unsigned store{}, left{}, right{}, torso{}, program{};
};
// Every pin the robot stands on, and the machine that works it: a 24 V battery
// in the deck, a motor on each wheel as the rover has, and a slow strong motor
// on the torso's pin -- 20 N m at stall and 5.7 turns a minute unloaded, so the
// torso takes seconds to come down rather than slamming.
Robot robotIn(const TileImpactRequest &room, Vec3 at) {
    Robot r;
    r.world = LiveWorld::open(room);
    LiveWorld &w = *r.world;
    const unsigned left_pin = w.hinge("robot", "robot: left wheel", at + Vec3{0.175, 0.16, -0.20}, {1.0, 0.0, 0.0});
    const unsigned right_pin = w.hinge("robot", "robot: right wheel", at + Vec3{-0.175, 0.16, -0.20}, {1.0, 0.0, 0.0});
    const unsigned hip = w.hinge("robot", "robot: torso", at + Vec3{0.0, 0.60, 0.15}, {1.0, 0.0, 0.0});
    const unsigned swivel = w.hinge("robot", "robot: caster", at + Vec3{0.0, 0.22, 0.15}, {0.0, 1.0, 0.0});
    const unsigned axle = w.hinge("robot: caster", "robot: caster wheel", at + Vec3{0.0, 0.05, 0.115}, {1.0, 0.0, 0.0});
    if (!left_pin || !right_pin || !hip || !swivel || !axle)
        throw std::runtime_error("the robot could not be pinned");
    r.store = w.energyStore("battery", "robot", 100000.0, 100000.0, 24.0, 0.0);
    r.left = w.control("left wheel", w.motor(left_pin, r.store, 20.0, 2.0 * kPi, 40.0));
    r.right = w.control("right wheel", w.motor(right_pin, r.store, 20.0, 2.0 * kPi, 40.0));
    r.torso = w.control("torso", w.motor(hip, r.store, 20.0, 0.6, 40.0));
    if (!r.store || !r.left || !r.right || !r.torso) throw std::runtime_error("the robot's machine would not fit");
    for (int i = 0; i < 240; ++i) tick(w);   // settle onto its casters
    return r;
}

// A stool: a 450 mm oak seat on four legs, its top 450 mm up, standing free --
// nothing holds it down, so leaning on it is a thing that can go wrong.
nlohmann::json stoolAt(Vec3 at) {
    nlohmann::json parts = nlohmann::json::array({box("seat", {0.45, 0.04, 0.45}, {0.0, 0.43, 0.0})});
    for (const double x : {0.18, -0.18})
        for (const double z : {0.18, -0.18})
            parts.push_back(box("leg " + std::to_string(parts.size()), {0.05, 0.41, 0.05}, {x, 0.205, z}));
    return body("stool", "oak", at, std::move(parts));
}

// The robot at the origin facing +z, 2 cm above the floor, with a stool 3.5 m
// ahead of it and 1.5 m to its left -- 23 degrees off its nose, so it has to
// come round before it can drive at it.
const Vec3 kRobotAt{0.0, 0.02, 0.0};
const Vec3 kStoolAt{1.5, 0.0, 3.5};
TileImpactRequest roomWithAStool() {
    TileImpactRequest request = flatRoom();
    nlohmann::json bodies = nlohmann::json::parse(robotScene(kRobotAt));
    bodies.push_back(stoolAt(kStoolAt));
    request.precise_rigid_scene_json = bodies.dump();
    return request;
}

// Where the far end of the torso has got to: 500 mm along the bar from its pin.
Vec3 endOfTheTorso(const LiveWorld &world) {
    const LiveBodyPose at = posed(world.poses(), "robot: torso");
    const Quat facing{at.orientation_wxyz[0], at.orientation_wxyz[1], at.orientation_wxyz[2],
                      at.orientation_wxyz[3]};
    return at.position_m + facing.rotate(Vec3{0.0, 0.25, 0.0});
}

// It comes round onto the stool, drives at it, and puts its torso down on it.
//
// It is told where the stool is, how near it wants to be, and the angle it
// would turn its torso to. Everything else is the world's: it turns until its
// nose is on the stool, drives at it, stops within 0.78 m of its middle, and
// then swings its torso forward -- and the torso comes to rest on the seat
// short of the angle it was reaching for, because the stool is in the way.
// That is the sit: the stool carries it.
void itGoesToTheStoolAndSitsOnIt() {
    Robot r = robotIn(roomWithAStool(), kRobotAt);
    LiveWorld &world = *r.world;

    LiveWorld::SitOrders orders;
    orders.toward = "stool";
    orders.close_m = 0.68;
    orders.pose = r.torso;
    orders.pose_deg = 125.0;   // past the seat: the seat is what stops it
    r.program = world.program("robot", "sit", r.left, r.right, "robot", 0.6, 8.0, 0.0, 0.0, orders);
    require(r.program != 0, "the sit program would not go on");
    if (r.program == 0) return;
    require(world.program("twin", "sit", r.left, r.right, "robot", 0.6, 8.0, 0.25, 0.6, orders) == 0,
            "a sit program is not given a rest: it is on its way somewhere");
    {
        LiveWorld::SitOrders nowhere = orders;
        nowhere.toward = "a stool that is not there";
        require(world.program("lost", "sit", r.left, r.right, "robot", 0.6, 8.0, 0.0, 0.0, nowhere) == 0,
                "a sit program goes to something that is in the world");
    }
    const LiveProgram start = programOf(world, r.program);
    require(start.doing == "stopped" && !start.power, "a program starts off: " + start.doing);
    require(std::abs(start.bearing_deg - 23.2) < 1.5 && std::abs(start.toward_m - 3.81) < 0.06,
            "it reads the stool 3.81 m off and 23 degrees to its left: " + std::to_string(start.toward_m) + " m, " +
                std::to_string(start.bearing_deg) + " degrees");

    runIt(world, r.program, true, 1);
    std::vector<std::string> order;
    const Vec3 stool_was = posed(world.poses(), "stool").position_m;
    double took_s = 0.0;
    for (int i = 0; i < 60 * 240; ++i) {
        tick(world);
        const LiveProgram now = programOf(world, r.program);
        if (order.empty() || order.back() != now.doing) order.push_back(now.doing);
        took_s = (i + 1) * kDt;
        if (now.doing == "sitting" && now.doing_s > 3.0) break;
    }
    const LiveProgram said = programOf(world, r.program);
    std::string went;
    for (const std::string &each : order) went += (went.empty() ? "" : " -> ") + each;
    const Vec3 stool_now = posed(world.poses(), "stool").position_m;
    const Vec3 tip = endOfTheTorso(world);
    const double above = tip.y - (kStoolAt.y + 0.45);
    const double in_from = length(Vec3{tip.x - stool_now.x, 0.0, tip.z - stool_now.z});
    std::cout << "    " << went << "\n";
    std::cout << "    in " << took_s << " s it stopped " << said.toward_m << " m from the stool's middle, "
              << said.bearing_deg << " degrees off square, its torso at " << said.pose_at_deg << " of the "
              << said.pose_deg << " degrees it reached for\n";
    std::cout << "    the end of the torso is " << above * 1000.0 << " mm above the seat and " << in_from * 1000.0
              << " mm in from its middle; the stool moved " << length(stool_now - stool_was) * 1000.0 << " mm\n";
    std::cout << "    it says: " << said.why << "\n";

    require(said.doing == "sitting", "it ends up sitting: " + said.doing + " (" + said.why + ")");
    require(order.size() >= 3 && order.front().rfind("turning", 0) == 0,
            "it turned to the stool before it drove at it: " + went);
    require(std::find(order.begin(), order.end(), std::string("going to it")) != order.end(),
            "and drove at it: " + went);
    require(said.toward_m <= 0.75, "it stopped within reach of the stool: " + std::to_string(said.toward_m) + " m");
    require(said.pose_at_deg < said.pose_deg - 5.0,
            "the seat stopped its torso short of the angle it reached for: " + std::to_string(said.pose_at_deg));
    require(std::abs(above) < 0.06, "the end of the torso is on the seat: " + std::to_string(above * 1000.0) + " mm");
    require(in_from < 0.225, "and within the seat, not over its edge: " + std::to_string(in_from * 1000.0) + " mm");
    require(length(stool_now - stool_was) < 0.15, "and the stool is still where it stood");

    // It holds: three more seconds and nothing has moved.
    const Vec3 held = endOfTheTorso(world);
    for (int i = 0; i < 3 * 240; ++i) tick(world);
    const double drift = length(endOfTheTorso(world) - held);
    std::cout << "    three seconds on, the end of the torso has moved " << drift * 1000.0 << " mm\n";
    require(drift < 0.01, "it stays where it came to rest: " + std::to_string(drift * 1000.0) + " mm");
    for (const LiveJoint &joint : world.joints()) require(joint.attached, "a pin let go");
}

} // namespace

void askIt(LiveWorld &world, unsigned program, const std::string &doing, double for_s, std::uint64_t seq,
           const std::string &why = "the test asked", const Vec3 *toward = nullptr,
           bool by_person = false) {
    LiveWorld::ProgramAsk ask;
    ask.sender = "test";
    ask.seq = seq;
    ask.doing = doing;
    ask.why = why;
    ask.for_s = for_s;
    ask.by_person = by_person;
    if (toward != nullptr) {
        ask.has_toward = true;
        ask.toward_m = *toward;
    }
    const std::string said = world.behave(program, ask);
    if (said != "applied") throw std::runtime_error("the program did not take the ask: " + said);
}

// One wall across the flat floor, a metre and a half in front of where the
// rover is built: it drives into it, and nothing it watches says so.
TileImpactRequest walledRoom() {
    TileImpactRequest request = flatRoom();
    SceneBody wall;
    wall.name = "wall";
    wall.shape = BodyShape::Box;
    wall.material = MaterialPreset::Concrete;
    wall.dimensions_m = {8.0, 0.6, 0.3};
    wall.center_m = {0.0, 0.3, 1.5};
    wall.anchored = true;
    request.bodies.push_back(wall);
    return request;
}

void itFreesItselfFromAWallItDroveIntoAndRoamsOn() {
    const auto world = LiveWorld::open(walledRoom());
    const Pins pins = pinUp(*world);
    const Machine m = fit(*world, pins);
    const unsigned program = world->program("rover", "roam", m.left, m.right, "rover", 1.0, 8.0);
    if (program == 0) throw std::runtime_error("the rover's program would not go on");
    for (int i = 0; i < 240; ++i) tick(*world);   // settle onto its caster
    runIt(*world, program, true, 1);
    // Nobody asks it anything: roaming, it goes forward, and the wall is in
    // front of it. Its wheels never stall against the wall, so only getting
    // nowhere finds it.
    bool stalled_ever = false;
    double nowhere_s = 0.0, freed_after_s = 0.0;
    std::string said_backing;
    Vec3 against{};
    for (int i = 0; i < 120 * 240; ++i) {
        tick(*world);
        const LiveProgram said = programOf(*world, program);
        nowhere_s = std::max(nowhere_s, said.stuck_s);
        for (const LiveControl &c : world->controls())
            if ((c.id == m.left || c.id == m.right) && c.condition.rfind("stalled", 0) == 0) stalled_ever = true;
        if (said.stucks == 1 && said_backing.empty()) {
            said_backing = said.doing + ": " + said.why;
            against = said.at_m;
        }
        // Free once it is two metres from where it stuck, and roaming again.
        if (said.stucks >= 1 && said.doing == "going forward" && length(said.at_m - against) > 2.0) {
            freed_after_s = static_cast<double>(i) * kDt;
            break;
        }
    }
    const LiveProgram said = programOf(*world, program);
    const double from_wall = 1.5 - said.at_m.z;
    std::cout << "    driven into a wall while roaming: it got nowhere for " << nowhere_s << " s, then "
              << said_backing << "; " << freed_after_s << " s in it is " << said.doing << " again, " << from_wall
              << " m back from the wall, having backed out " << said.stucks << " time(s)\n";
    require(!stalled_ever, "no wheel ever stalled against the wall: nothing watching a motor could see this");
    require(said_backing.find("not getting anywhere") != std::string::npos,
            "it backed itself out and said why: " + said_backing);
    require(freed_after_s > 0.0 && said.doing == "going forward",
            "it got itself out and roams on: " + said.doing + ", " + said.why);
    require(from_wall > 0.5, "well back from the wall: " + std::to_string(from_wall) + " m");
    require(said.stucks <= 2, "it took one back-out, or two: " + std::to_string(said.stucks));
    // Clear of it, it is not still counting that place against itself: the next
    // thing in its way gets the same patience as the first.
    require(said.stuck_s < 1.0, "and is getting somewhere again: " + std::to_string(said.stuck_s) + " s");
}

// A pen of anchored concrete round where the rover is built, 1.6 m inside its
// walls: it can turn in there and go nowhere. Nothing a machine watches says
// this -- its wheels turn freely against the wall, its motors are not
// overloaded, no sensor sees anything -- so only getting nowhere finds it.
TileImpactRequest pennedRoom() {
    TileImpactRequest request = flatRoom();
    const auto wall = [](const std::string &name, Vec3 size, Vec3 at) {
        SceneBody b;
        b.name = name;
        b.shape = BodyShape::Box;
        b.material = MaterialPreset::Concrete;
        b.dimensions_m = {size.x, size.y, size.z};
        b.center_m = {at.x, at.y, at.z};
        b.anchored = true;
        return b;
    };
    request.bodies.push_back(wall("wall ahead", {1.95, 0.6, 0.15}, {0.0, 0.3, 0.875}));
    request.bodies.push_back(wall("wall behind", {1.95, 0.6, 0.15}, {0.0, 0.3, -0.875}));
    request.bodies.push_back(wall("wall left", {0.15, 0.6, 1.95}, {0.875, 0.3, 0.0}));
    request.bodies.push_back(wall("wall right", {0.15, 0.6, 1.95}, {-0.875, 0.3, 0.0}));
    return request;
}

void itBacksOutOfWhereItGetsNowhereAndSaysWhenItCannot() {
    const auto world = LiveWorld::open(pennedRoom());
    const Pins pins = pinUp(*world);
    const Machine m = fit(*world, pins);
    const unsigned program = world->program("rover", "roam", m.left, m.right, "rover", 1.0, 8.0);
    if (program == 0) throw std::runtime_error("the rover's program would not go on");
    for (int i = 0; i < 240; ++i) tick(*world);   // settle onto its caster
    runIt(*world, program, true, 1);
    // Asked to go to a point six metres beyond the wall: it cannot, and no
    // wheel will ever stall telling it so.
    const Vec3 beyond{0.0, 0.0, 6.0};
    askIt(*world, program, "approaching", 0.0, 2, "the test sent it through a wall", &beyond);
    const Vec3 began = posed(world->poses(), "rover").position_m;
    double nowhere_s = 0.0, backed_out_after_s = 0.0, gave_up_after_s = 0.0, went_m = 0.0;
    std::string said_backing, said_stuck;
    for (int i = 0; i < 180 * 240; ++i) {
        tick(*world);
        const LiveProgram said = programOf(*world, program);
        nowhere_s = std::max(nowhere_s, said.stuck_s);
        went_m = std::max(went_m, length(posed(world->poses(), "rover").position_m - began));
        if (backed_out_after_s == 0.0 && said.stucks > 0) {
            backed_out_after_s = static_cast<double>(i) * kDt;
            said_backing = said.doing + ": " + said.why;
        }
        if (said.doing == "stuck") {
            gave_up_after_s = static_cast<double>(i) * kDt;
            said_stuck = said.why;
            break;
        }
    }
    LiveProgram said = programOf(*world, program);
    std::cout << "    penned in: it got nowhere for " << nowhere_s << " s, backed out after " << backed_out_after_s
              << " s (" << said_backing << "), gave up after " << gave_up_after_s << " s (" << said_stuck
              << "); it never got further than " << went_m << " m from where it began\n";
    require(backed_out_after_s > 0.0 && said_backing.find("not getting anywhere") != std::string::npos,
            "it backed itself out and said why: " + said_backing);
    require(said.doing == "stuck" && said.why.find("cannot get itself out") != std::string::npos,
            "a few tries on it stops and says it cannot get itself out: " + said.doing + ": " + said.why);
    require(said.stucks == 3, "after three tries, not more: " + std::to_string(said.stucks));
    require(said.asked.empty(), "and it has given up the ask it could not do");
    require(went_m < 1.5, "it never got out of the pen: " + std::to_string(went_m) + " m");
    // Stuck, its wheels are held, not driving.
    for (const LiveControl &c : world->controls())
        if (c.id == m.left || c.id == m.right)
            require(c.direction == 0, "stuck, its " + c.name + " is held, not driving");
    // And it stays stuck rather than butting the wall again: no more tries, and
    // it does not wander off from where it gave up.
    const Vec3 gave_up_at = posed(world->poses(), "rover").position_m;
    for (int i = 0; i < 40 * 240; ++i) tick(*world);
    said = programOf(*world, program);
    require(said.doing == "stuck" && said.stucks == 3,
            "forty seconds on it is still stuck, and has not tried again: " + said.doing + ", " +
                std::to_string(said.stucks));
    require(length(posed(world->poses(), "rover").position_m - gave_up_at) < 0.1, "and has not moved");
    // Saved where it gave up and opened again, it is still given up: it has not
    // moved, and it still knows what getting clear of that place would be.
    std::string why;
    const std::string saved = world->snapshot(why);
    require(!saved.empty(), "the world would not save: " + why);
    if (!saved.empty()) {
        const auto again = LiveWorld::open(pennedRoom(), saved);
        const LiveProgram is = programOf(*again, program);
        require(is.doing == "stuck" && is.stucks == 3 && is.why.find("cannot get itself out") != std::string::npos,
                "opened again, it is still stuck: " + is.doing + ", " + is.why);
        for (int i = 0; i < 20 * 240; ++i) tick(*again);
        require(programOf(*again, program).doing == "stuck", "and stays stuck rather than starting over");
    }
    // Being stuck does not make it deaf: asked to back off, it backs off, so a
    // person who comes to get it out can.
    askIt(*world, program, "backing off", 4.0, 3, "a person came to get it out");
    said = programOf(*world, program);
    require(said.doing == "backing off" && said.why == "a person came to get it out",
            "asked to back off where it is stuck, it does: " + said.doing + ", " + said.why);
    for (int i = 0; i < 240; ++i) tick(*world);
    require(programOf(*world, program).doing == "backing off", "and goes on doing it");
    std::cout << "    asked to back off where it gave up: " << programOf(*world, program).doing << "\n";
}

void itDoesWhatItIsAskedForAWhile() {
    Rover r = roverOnTheShore();
    LiveWorld &world = *r.world;
    runIt(world, r.program, true, 1);
    for (int i = 0; i < 240; ++i) tick(world);
    require(programOf(world, r.program).doing == "going forward", "it goes forward on its own");
    // Asked to back off for two and a half seconds: it backs off -- against
    // the way it was going, once its wheels have stopped turning forward --
    // says why it was asked, and when the while is up it goes forward again
    // on its own.
    Vec3 was = posed(world.poses(), "rover").position_m;
    Vec3 going = posed(world.poses(), "rover").velocity_m_s;
    going.y = 0.0;
    require(length(going) > 0.1, "it was going somewhere: " + std::to_string(length(going)) + " m/s");
    going = normalized(going);
    askIt(world, r.program, "backing off", 2.5, 2, "something is in its way");
    LiveProgram said = programOf(world, r.program);
    require(said.doing == "backing off" && said.why == "something is in its way" && said.asked == "backing off" &&
                said.asked_by == "test",
            "asked to back off, it backs off and says why: " + said.doing + ", " + said.why);
    for (int i = 0; i < 240; ++i) tick(world);
    was = posed(world.poses(), "rover").position_m;
    for (int i = 0; i < 240; ++i) tick(world);
    const double along = dot(posed(world.poses(), "rover").position_m - was, going);
    std::cout << "    asked to back off: in its second second it went " << along << " m along the way it was going\n";
    require(along < -0.05, "in its second second it has backed off: " + std::to_string(along) + " m");
    require(programOf(world, r.program).doing == "backing off", "and is still backing off");
    for (int i = 0; i < 240; ++i) tick(world);
    said = programOf(world, r.program);
    require(said.doing == "going forward" && said.asked.empty() && said.why.find("goes on") != std::string::npos,
            "the second up, it goes on as it would have: " + said.doing + ", " + said.why);
    // A stale ask changes nothing.
    LiveWorld::ProgramAsk stale;
    stale.sender = "test";
    stale.seq = 2;
    stale.doing = "waiting";
    require(world.behave(r.program, stale) == "stale", "an ask no newer than the last from its sender is stale");
    require(programOf(world, r.program).doing == "going forward", "and changes nothing");
    // Asked to wait until asked otherwise: it holds still, on, for as long as
    // that is; asked nothing more, it goes on.
    askIt(world, r.program, "waiting", 0.0, 3, "the person is talking to it");
    for (int i = 0; i < 480; ++i) tick(world);
    was = posed(world.poses(), "rover").position_m;
    for (int i = 0; i < 480; ++i) tick(world);
    said = programOf(world, r.program);
    require(said.doing == "waiting" && said.power && said.asked_s > 3.9,
            "asked to wait, it is still waiting four seconds on: " + said.doing);
    require(length(posed(world.poses(), "rover").position_m - was) < 0.02, "and holds still");
    askIt(world, r.program, "", 0.0, 4);
    require(programOf(world, r.program).doing == "going forward" && programOf(world, r.program).asked.empty(),
            "asked nothing more, it goes on");
    // Asked to face a point away from the lake -- out from the basin's
    // middle, so dry ground it can then drive on without its water reflex
    // taking it -- it turns on the spot until its front is towards it, then
    // waits, facing it.
    for (int i = 0; i < 240; ++i) tick(world);
    const LiveBodyPose here = posed(world.poses(), "rover");
    Vec3 outward = here.position_m;
    outward.y = 0.0;
    require(length(outward) > 1.0, "it is out from the lake's middle");
    outward = normalized(outward);
    const Vec3 behind = here.position_m + 3.0 * outward;
    askIt(world, r.program, "facing", 0.0, 5, "the person came to talk to it", &behind);
    said = programOf(world, r.program);
    // Moving when it was asked, it stops first: turning with its wheels
    // opposed has no braking, so one that turns while it is still going
    // coasts off its way while it spins.
    require(said.doing == "stopping" || said.doing == "turning left" || said.doing == "turning right",
            "asked to face what is behind it, it stops to turn on the spot: " + said.doing);
    double stopped_for_s = 0.0;
    for (int i = 0; i < 3 * 240; ++i) {
        tick(world);
        stopped_for_s += kDt;
        const std::string doing = programOf(world, r.program).doing;
        if (doing == "turning left" || doing == "turning right") break;
    }
    said = programOf(world, r.program);
    std::cout << "    asked to face a point behind it: it stopped for " << stopped_for_s << " s, then "
              << said.doing << "\n";
    require(said.doing == "turning left" || said.doing == "turning right",
            "and then turns on the spot: " + said.doing);
    require(stopped_for_s < 2.5, "without dawdling: " + std::to_string(stopped_for_s) + " s");
    double turned_s = 0.0;
    for (int i = 0; i < 16 * 240; ++i) {
        tick(world);
        turned_s += kDt;
        if (programOf(world, r.program).doing == "waiting") break;
    }
    said = programOf(world, r.program);
    // Facing it: the heading the engine reports is the bearing to the point.
    const double bearing = std::atan2(behind.x - said.at_m.x, behind.z - said.at_m.z) * 180.0 / kPi;
    double off = said.heading_deg - bearing;
    while (off > 180.0) off -= 360.0;
    while (off <= -180.0) off += 360.0;
    std::cout << "    asked to face a point away from the lake: " << said.doing << " after " << turned_s
              << " s, its front " << off << " degrees off it\n";
    require(said.doing == "waiting", "and waits facing it: " + said.doing);
    require(std::abs(off) < 12.0, "with its front towards it");
    askIt(world, r.program, "going forward", 1.0, 6);
    for (int i = 0; i < 240; ++i) tick(world);
    // A saved world gives it back doing what it was asked, as far in.
    askIt(world, r.program, "backing off", 5.0, 7, "saved while backing off");
    for (int i = 0; i < 240; ++i) tick(world);
    std::string why;
    const std::string saved = world.snapshot(why);
    require(!saved.empty(), "the world would not save: " + why);
    if (!saved.empty()) {
        const auto again = LiveWorld::open(shoreRoom(), saved);
        const LiveProgram is = programOf(*again, r.program);
        require(is.asked == "backing off" && is.asked_by == "test" && is.asked_for_s == 5.0 && is.asked_s > 0.9 &&
                    is.doing == "backing off" && is.why == "saved while backing off",
                "opened again, it is doing what it was asked, as far in: " + is.doing + ", " + is.asked);
    }
    // Turned off, it drops what it was asked.
    runIt(world, r.program, false, 8);
    said = programOf(world, r.program);
    require(said.doing == "stopped" && said.asked.empty(), "turned off, it drops the ask");
}

// An ask the machine made of itself -- its routine's, its decider's -- is
// governed by its reflexes like everything else it does: it never drives
// itself into the lake, and after three scares it gives the ask up.
void anAskThatIsNotAPersonsNeverDrivesItIntoTheWater() {
    Rover r = roverOnTheShore();
    LiveWorld &world = *r.world;
    runIt(world, r.program, true, 1);
    for (int i = 0; i < 240; ++i) tick(world);
    // The lake's middle is at the origin: asked to approach it, it heads in.
    const Vec3 middle{0.0, 0.0, 0.0};
    askIt(world, r.program, "approaching", 60.0, 2, "the test sent it into the lake", &middle, false);
    double wet = 0.0;
    bool interrupted = false, resumed = false;
    (void)resumed;
    std::string why_when_wet;
    for (int i = 0; i < 150 * 240; ++i) {
        tick(world);
        const LiveProgram said = programOf(world, r.program);
        if (said.why.find("reflexes have it") != std::string::npos) interrupted = true;
        if (said.asked.empty() && said.why.find("gave it up") != std::string::npos) break;
        if (interrupted && said.doing == "going forward" && said.why == "the test sent it into the lake") resumed = true;
        if (i % 24 == 23) {
            const double here = wettest(world);
            if (here > wet) {
                wet = here;
                why_when_wet = said.doing + ": " + said.why;
            }
        }
    }
    const LiveProgram after = programOf(world, r.program);
    std::cout << "    sent into the lake: at most " << wet * 1000.0 << " mm of water under a wheel ("
              << why_when_wet << "); interrupted " << interrupted << ", the ask resumed " << resumed
              << "; now " << after.doing << ": " << after.why << "\n";
    require(interrupted, "its reflexes took it when a sensor saw water");
    require(wet <= 0.003, "and no wheel got wet");
    require(after.asked.empty() && after.why.find("gave it up") != std::string::npos,
            "three times turned back, it gave the ask up: " + after.why);
}

// The owner, 2026-09-26, having tried to send a rover into the lake and
// watched it turn away: "your order wins". A person's order outranks the
// water reflex. The ask here is the same ask as above, to the same point, in
// the same room; the only difference is that it says a person made it.
// A sensor says HOW LONG it has been seeing, not only that it is.
//
// Every reading a host or a brain gets off a machine is otherwise an edge: a
// sensor starts seeing and that is the last word on it, however long the
// machine then stays where it is. Measured on this rover, it raised one
// "water ahead on its left" and slid down the basin into the lake over the
// next thirty-nine seconds without another word. `seeing_s` is what says "and
// it still is", and it belongs to the sensor rather than to anything that
// knows what a rover is.
void aSensorSaysHowLongItHasBeenSeeing() {
    Rover r = roverOnTheShore();
    LiveWorld &world = *r.world;
    runIt(world, r.program, true, 1);
    for (int i = 0; i < 240; ++i) tick(world);
    for (const LiveSensor &sensor : programOf(world, r.program).sensors)
        require(sensor.seeing_s == 0.0, "a dry sensor has been seeing for no time at all");
    // Ordered in, because the reflexes exist to stop it being wet for long.
    const Vec3 middle{0.0, 0.0, 0.0};
    askIt(world, r.program, "approaching", 60.0, 2, "the person sent it into the lake", &middle, true);
    double longest = 0.0;
    for (int i = 0; i < 60 * 240 && longest < 5.0; ++i) {
        tick(world);
        for (const LiveSensor &sensor : programOf(world, r.program).sensors) {
            // The whole of the invariant: seeing, and it counts; not seeing,
            // and it is zero the same step.
            require(sensor.sees || sensor.seeing_s == 0.0,
                    "a sensor that sees nothing says it has been seeing for " +
                        std::to_string(sensor.seeing_s) + " s");
            longest = std::max(longest, sensor.seeing_s);
        }
    }
    std::cout << "    a sensor had been seeing for " << longest << " s" << std::endl;
    require(longest >= 5.0, "a sensor counted the time it was in the water, and it did not: " +
                                std::to_string(longest) + " s");
}

void aPersonsOrderDrivesItIntoTheWater() {
    Rover r = roverOnTheShore();
    LiveWorld &world = *r.world;
    runIt(world, r.program, true, 1);
    for (int i = 0; i < 240; ++i) tick(world);
    const Vec3 middle{0.0, 0.0, 0.0};
    askIt(world, r.program, "approaching", 60.0, 2, "the person sent it into the lake", &middle, true);
    double wet = 0.0, wet_at_s = 0.0;
    bool interrupted = false, saw_water = false;
    std::string doing_when_wet;
    for (int i = 0; i < 60 * 240 && wet < 0.05; ++i) {
        tick(world);
        const LiveProgram said = programOf(world, r.program);
        if (said.why.find("reflexes have it") != std::string::npos) interrupted = true;
        if (said.asked.empty()) break;
        for (const LiveSensor &sensor : said.sensors)
            if (sensor.sees) saw_water = true;
        if (i % 24 != 23) continue;
        const double here = wettest(world);
        if (here <= wet) continue;
        wet = here;
        wet_at_s = static_cast<double>(i + 1) * kDt;
        doing_when_wet = said.doing + ": " + said.why;
    }
    const LiveProgram in_it = programOf(world, r.program);
    std::cout << "    ordered into the lake: " << wet * 1000.0 << " mm of water under a wheel by "
              << wet_at_s << " s (" << doing_when_wet << "); its sensors saw the water " << saw_water
              << ", its reflexes took it " << interrupted << "\n";
    require(saw_water, "its sensors saw the water it was ordered into");
    require(!interrupted, "and its reflexes never took it: " + in_it.doing + ": " + in_it.why);
    require(wet >= 0.05, "a person's order drove it into the water: " + std::to_string(wet * 1000.0) + " mm");
    require(in_it.asked == "approaching" && in_it.asked_by_person,
            "and the order still stands: " + in_it.asked);

    // The order stood the reflex aside; it did not take it away. Asked nothing
    // more, the machine is its own again and backs out of the water at once.
    askIt(world, r.program, "", 0.0, 3);
    bool reflexed = false;
    std::string said_out;
    for (int i = 0; i < 10 * 240 && !reflexed; ++i) {
        tick(world);
        const LiveProgram said = programOf(world, r.program);
        if (said.doing != "backing off" && said.doing != "turning left" && said.doing != "turning right")
            continue;
        if (said.why.find("water") == std::string::npos) continue;
        reflexed = true;
        said_out = said.doing + ": " + said.why;
    }
    const LiveProgram after = programOf(world, r.program);
    std::cout << "    the order lifted: " << said_out << "; now " << after.doing << ": " << after.why
              << ", ordered by a person " << after.asked_by_person << "\n";
    require(!after.asked_by_person, "the order is gone with the ask");
    require(reflexed, "and its water reflex has it back: " + after.doing + ": " + after.why);
}

// A dry native basin, with no water cue to stand in for missing ground.
Rover dryGroundRover() {
    TileImpactRequest request = shoreRoom();
    auto environment = nlohmann::json::parse(request.environment_scene_json);
    environment["terrain"]["generate"]["lake_level_m"] = 0.0;
    request.environment_scene_json = environment.dump();
    const Vec3 at{0.0,0.22,0.0};
    request.precise_rigid_scene_json = roverScene(at);
    Rover r;
    r.world=LiveWorld::open(request);
    r.machine=fit(*r.world,pinUp(*r.world,at));
    r.program=r.world->program("rover","roam",r.machine.left,r.machine.right,"rover",1.0,8.0);
    for (int i=0;i<240;i++) tick(*r.world);
    return r;
}

TileImpactRequest rampRoom(double grade, const std::string &material) {
            const double angle=-grade*kPi/180.;
            const Quat q{std::cos(angle/2),std::sin(angle/2),0,0};
            const Vec3 floor{0,10,0},at=floor+Vec3{0,.02,0};
            auto request=flatRoom();
            SceneBody ramp; ramp.name="ramp";ramp.shape=BodyShape::Box;
            ramp.material=MaterialPreset::Concrete;ramp.anchored=true;
            ramp.dimensions_m={3,.1,20};ramp.center_m=floor+q.rotate({0,-.05,0});
            ramp.rotation_deg={-grade,0,0};request.bodies={ramp};
            auto scene=nlohmann::json::parse(roverScene({}));
            for(auto &b:scene) {
                b["position_m"]={at.x,at.y,at.z};b["orientation_wxyz"]={q.w,q.x,q.y,q.z};
                if(b["name"]=="rover: left wheel" || b["name"]=="rover: right wheel") {
                    b["material"]=material;
                    for(auto &part:b["parts"])if(part["name"]=="wheel")part["material"]=material;
                }
            }
            request.precise_rigid_scene_json=scene.dump();
            return request;
}

void rampGradesMeasureNativeDriveSlipAndEnergy() {
    for(const std::string material : {"glass","oak","iron"}) {
        for(double grade : {0.,5.,8.,12.,16.,20.}) {
            const double angle=-grade*kPi/180.;
            const Quat q{std::cos(angle/2),std::sin(angle/2),0,0};
            const Vec3 floor{0,10,0},at=floor+Vec3{0,.02,0};
            auto request=rampRoom(grade,material);
            const auto compiled=readPreciseRigidScene(request.precise_rigid_scene_json);
            auto world=LiveWorld::open(request);const auto m=fit(*world,pinUp(*world,at,q));
            for(int i=0;i<2*240;i++)tick(*world);
            const auto before=world->poses();const auto from=posed(before,"rover");
            double mass=0;for(const auto &p:before)mass+=p.mass_kg;
            const double energy=world->mechanicalEnergyJ();
            const double charge=world->energyStores()[0].charge_j;
            tell(*world,m.left,1,1);tell(*world,m.right,1,1);
            const Vec3 normal=q.rotate({0,1,0}),tangent=q.rotate({0,0,1});
            double torque=0,slip=0,torque_excess=0;int contacts=0;
            std::string why;
            for(int i=0;i<6*240;i++) {
                const auto previous=world->motors();
                tick(*world);
                for(const auto &motor:world->motors()) {
                    torque=std::max(torque,std::abs(motor.torque_n_m));
                    const auto was=std::find_if(previous.begin(),previous.end(),[&](const auto &p){return p.id==motor.id;});
                    // Stall torque is at zero speed, not a current limiter. A
                    // back-driven DC motor can exceed it; a brake has its own bound.
                    const double bound=motor.state=="driving" ? std::abs(motor.stall_torque_n_m*
                        (motor.command-was->speed_rad_s/motor.no_load_rad_s)) : motor.brake_torque_n_m;
                    torque_excess=std::max(torque_excess,std::abs(motor.torque_n_m)-bound);
                }
                if(i%240!=239)continue;
                const auto saved=nlohmann::json::parse(world->snapshot(why));
                for(const auto &b:saved["bodies"]) {
                    if(b["name"]!="rover: left wheel" && b["name"]!="rover: right wheel")continue;
                    const auto &s=b["pose"];
                    const auto vector=[](const auto &v){return Vec3{v[0].template get<double>(),v[1].template get<double>(),v[2].template get<double>()};};
                    const auto turn=s["q_wxyz"];const Quat facing{turn[0],turn[1],turn[2],turn[3]};
                    const auto name=b["name"].get<std::string>();
                    const auto authored=std::find_if(compiled.begin(),compiled.end(),[&](const auto &part){return part.name==name;});
                    const auto rim=std::find(authored->part_names.begin(),authored->part_names.end(),"wheel")-authored->part_names.begin();
                    const Vec3 axis=facing.rotate({1,0,0});
                    const Vec3 radial=normal-axis*dot(normal,axis);
                    const Vec3 lever=facing.rotate(authored->parts[static_cast<std::size_t>(rim)].center_local_m)-radial*(.16/length(radial));
                    const Vec3 point=vector(s["com_m"])+lever;
                    // Actual native rigid v/w at the cylinder's supporting point.
                    // Only sample where its analytical support touches this plane.
                    if(std::abs(dot(point-floor,normal))>.01)continue;
                    const Vec3 velocity=vector(s["v_m_s"])+cross(vector(s["w_rad_s"]),lever);
                    slip=std::max(slip,length(velocity-normal*dot(velocity,normal)));++contacts;
                }
            }
            const auto to=posed(world->poses(),"rover");
            double work=0,heat=0,drawn=0;
            for(const auto &motor:world->motors()){work+=motor.work_j;heat+=motor.heat_j;drawn+=motor.drawn_j;}
            const double battery_residual=charge-world->energyStores()[0].charge_j-drawn;
            const double mechanical_residual=work-(world->mechanicalEnergyJ()-energy);
            const double along=dot(to.position_m-from.position_m,tangent);
            require(torque_excess<1e-4,"ramp drive retains declared DC torque-speed and brake bounds (float joint impulses)");
            require(std::abs(battery_residual)<1e-7,"ramp battery debit equals actual motor draw");
            require(std::isfinite(mechanical_residual) && contacts>0,"ramp measures finite energy and real contact-point slip");
            if(grade==0 && material=="oak")require(along>4,"ordinary oak rover drives at least four metres on the flat ramp");
            std::cout<<"    ramp "<<material<<" "<<grade<<" deg; mass "<<mass<<" kg; uphill "<<along
                     <<" m; rise "<<to.position_m.y-from.position_m.y<<" m; slip "<<slip
                     <<" m/s ("<<contacts<<" contacts); max torque "<<torque<<" N m; motor work "<<work
                     <<" J; torque envelope excess "<<torque_excess<<" N m"
                     <<"; heat "<<heat<<" J; battery residual "<<battery_residual
                     <<" J; unclosed work - delta mechanical "<<mechanical_residual<<" J\n";
        }
    }
}

void autonomousGradeUsesMeasuredLimit() {
    for(const auto [grade,limit] : {std::pair{10.,8.},std::pair{10.,12.},std::pair{16.,12.}}) {
        const double angle=-grade*kPi/180.;
        const Quat q{std::cos(angle/2),std::sin(angle/2),0,0};
        const Vec3 at{0,10.02,0},tangent=q.rotate({0,0,1});
        auto world=LiveWorld::open(rampRoom(grade,"oak"));
        const auto m=fit(*world,pinUp(*world,at,q));
        const auto id=world->program("rover","roam",m.left,m.right,"rover",1.,limit);
        require(id!=0,"ramp autonomous program is admitted");
        for(int i=0;i<2*240;i++)tick(*world);
        const auto from=posed(world->poses(),"rover").position_m;
        runIt(*world,id,true,1);
        bool refused=false;double max_pitch=0;
        for(int i=0;i<6*240;i++) {
            tick(*world);const auto said=programOf(*world,id);
            refused=refused || said.why.find("steeper than it climbs")!=std::string::npos;
            max_pitch=std::max(max_pitch,said.pitch_deg);
        }
        const double uphill=dot(posed(world->poses(),"rover").position_m-from,tangent);
        std::cout<<"    autonomous ramp "<<grade<<" deg, declared limit "<<limit
                 <<" deg; uphill "<<uphill<<" m; max pitch "<<max_pitch<<" deg; refused "<<refused<<"\n";
        if(grade==10 && limit==12) {
            require(!refused && uphill>3,"qualified oak rover climbs ordinary grade without forced motion");
        } else require(refused,"autonomous rover refuses a grade beyond its declaration");
        for(const auto &j:world->joints())require(j.attached,"ramp climbing preserves the assembly");
        std::string why;const auto saved=world->snapshot(why);
        auto again=LiveWorld::open(rampRoom(grade,"oak"),saved);
        require(programOf(*again,id).climb_deg==limit,"reopen retains the explicit grade limit");
    }
}

void autonomousGradesOnNativeTerrain() {
    double old_reach=0,new_reach=0;
    for(double cell:{.25,.125}) {
    for(double limit:{8.,12.}) {
        auto request=shoreRoom();auto environment=nlohmann::json::parse(request.environment_scene_json);
        auto &generation=environment["terrain"]["generate"];
        generation["lake_level_m"]=0.;generation["cell_m"]=cell;
        request.environment_scene_json=environment.dump();request.precise_rigid_scene_json="";
        auto survey=LiveWorld::open(request);
        const double z=cell==.25 ? 9. : 2.;
        const auto height=[&](double point){return survey->environment()->terrain().heightAt(0,point);};
        const Vec3 at{0,height(z)+.02,z};
        const double angle=-std::atan((height(z+.38)-height(z-.72))/1.1);
        const Quat q{std::cos(angle/2),std::sin(angle/2),0,0};
        auto scene=nlohmann::json::parse(roverScene(at));
        for(auto &body:scene)body["orientation_wxyz"]={q.w,q.x,q.y,q.z};
        request.precise_rigid_scene_json=scene.dump();survey.reset();
        auto world=LiveWorld::open(request);const auto m=fit(*world,pinUp(*world,at,q));
        const auto id=world->program("rover","roam",m.left,m.right,"rover",1.,limit);
        for(double side:{-.55,0.,.55})
            require(world->programSense(id,"ground","rover",at+q.rotate({side,.36,1.5}),.12),"native terrain ground probe admitted");
        for(int i=0;i<2*240;i++)tick(*world);
        const auto from=posed(world->poses(),"rover").position_m;
        runIt(*world,id,true,1);
        bool refused=false,hazard=false;double furthest=0,max_pitch=0,reading=0;
        for(int i=0;i<6*240;i++) {
            tick(*world);const auto said=programOf(*world,id);
            furthest=std::max(furthest,posed(world->poses(),"rover").position_m.z-from.z);
            max_pitch=std::max(max_pitch,said.pitch_deg);
            for(const auto &s:said.sensors){hazard=hazard||s.sees;reading=std::max(reading,std::abs(s.reading_m));}
            if(said.why.find("steeper than it climbs")!=std::string::npos){refused=true;break;}
        }
        std::cout<<"    native dry basin, grid "<<cell<<" m, limit "<<limit<<" deg; uphill reach "<<furthest
                 <<" m; max pitch "<<max_pitch<<" deg; ground discrepancy "<<reading<<" m; refused "<<refused<<"\n";
        if(cell==.125) {
            require(hazard && reading>.12 && furthest<1,"sharp curvature retains a bounded ground warning before driving into it");
        } else if(limit==8) {
            require(!hazard,"ordinary continuous hill is not mistaken for a ground hole");
            require(refused,"old declaration turns away when actual pitch exceeds its limit");old_reach=furthest;
        } else {
            require(!hazard,"ordinary continuous hill is not mistaken for a ground hole");
            require(!refused && max_pitch>8,"qualified rover climbs native terrain beyond the old pitch limit");new_reach=furthest;
        }
    }
    }
    require(new_reach>old_reach+.5,"qualified declaration extends native hill climbing without forced motion");
}

void groundProbeDoesNotTreatBodyPitchAsTerrain() {
    auto request=shoreRoom();auto environment=nlohmann::json::parse(request.environment_scene_json);
    environment["terrain"]["generate"]["kind"]="flat";
    environment["terrain"]["generate"]["lake_level_m"]=0.;
    request.environment_scene_json=environment.dump();
    // A declared initially tilted pose above a flat surface. This measures
    // the probe before falling; it never assigns a runtime pose or velocity.
    const Vec3 at{0,2,0};const double angle=-20*kPi/180.;
    const Quat q{std::cos(angle/2),std::sin(angle/2),0,0};
    auto scene=nlohmann::json::parse(roverScene(at));
    for(auto &body:scene)body["orientation_wxyz"]={q.w,q.x,q.y,q.z};
    request.precise_rigid_scene_json=scene.dump();
    auto world=LiveWorld::open(request);const auto m=fit(*world,pinUp(*world,at,q));
    const auto id=world->program("rover","roam",m.left,m.right,"rover",1.,12.);
    require(world->programSense(id,"ground","rover",at+q.rotate({0,.36,1.5}),.12),"tilted ground probe admitted");
    const auto before=programOf(*world,id).sensors[0];
    require(!before.sees && std::abs(before.reading_m)<1e-9,"body pitch alone does not invent a ground discontinuity");
    world->setCarryLimitKg(10000);
    require(!world->dig(-.5,before.at_m.z,.5,before.at_m.z,.8,.5).edit.cells.empty(),"probe experiment cuts real flat terrain");
    for(int i=0;i<24;i++)tick(*world);
    const auto after=programOf(*world,id).sensors[0];
    require(after.sees && after.reading_m>.35,"same tilted probe detects the actual cut");
    const auto now=programOf(*world,id);
    const auto root=nlohmann::json::parse(world->survey(now.at_m.x,now.at_m.z));
    const auto tip=nlohmann::json::parse(world->survey(after.at_m.x,after.at_m.z));
    const auto gradient=root.at("ground_gradient_xz");
    const double predicted=root.at("ground_m").get<double>()+
        gradient[0].get<double>()*(after.at_m.x-now.at_m.x)+
        gradient[1].get<double>()*(after.at_m.z-now.at_m.z)-tip.at("ground_m").get<double>();
    require(std::abs(predicted-after.reading_m)<1e-9,"survey gradient predicts the actual native ground probe");
    std::cout<<"    tilted flat probe "<<before.reading_m<<" m; actual cut "<<after.reading_m<<" m\n";
}

void boundedHandRecoversAnExcavatedRover() {
    Rover r=dryGroundRover();
    auto &world=*r.world;
    // Declared excavation experiment: enough ground storage to cut the basin,
    // not a player capacity grant or a chassis pose/velocity edit.
    world.setCarryLimitKg(10000);
    const auto before=world.poses();
    const auto original=posed(before,"rover").position_m;
    require(!world.dig(-.8,0,.8,0,1.6,.6).edit.cells.empty(),"recovery pit removes actual ground");
    for(int i=0;i<3*240;i++)tick(world);
    const auto fallen=posed(world.poses(),"rover").position_m;
    const auto joints_before=world.joints();
    const double energy_before=world.mechanicalEnergyJ();
    require(original.y-fallen.y>.2,"the attached rover falls into the actual excavation");
    world.selectHand("recovering-player");
    std::string why;
    require(world.wield("rover",fallen),"a bounded hand can take the chassis");
    require(length(posed(world.poses(),"rover").position_m-fallen)<1e-12,"taking the grip does not move the rover");
    const Vec3 raised{fallen.x,original.y+.65,fallen.z};
    world.moveHeld(raised);
    require(length(posed(world.poses(),"rover").position_m-fallen)<1e-12,"setting the target does not teleport it");
    double peak=0;
    for(int i=0;i<4*240;i++){tick(world);peak=std::max(peak,length(world.hand().force_n));}
    const auto lifted=posed(world.poses(),"rover").position_m;
    require(lifted.y>original.y+.25,"native force lifts the entire attached rover above the rim");
    world.moveHeld({raised.x,raised.y,-2.0});
    for(int i=0;i<4*240;i++){tick(world);peak=std::max(peak,length(world.hand().force_n));}
    const auto moved=posed(world.poses(),"rover").position_m;
    const double work=world.hand().work_j;
    const double unclosed=work-(world.mechanicalEnergyJ()-energy_before);
    require(std::isfinite(unclosed),"recovery mechanical energy/work residual remains finite");
    require(moved.z<-1.5,"bounded grip pulls the assembly onto unexcavated ground");
    require(peak<=world.handStrength()+1e-6 && work>0,"recovery records bounded force and actual positive hand work");
    auto saved=world.snapshot(why);
    auto request=shoreRoom();auto env=nlohmann::json::parse(request.environment_scene_json);
    env["terrain"]["generate"]["lake_level_m"]=0.;request.environment_scene_json=env.dump();
    request.precise_rigid_scene_json=roverScene({0,.22,0});
    auto again=LiveWorld::open(request,saved);again->selectHand("recovering-player");
    require(again->hand().mode=="grip" && std::abs(again->hand().work_j-work)<1e-6,"restart retains bounded grip and measured work");
    world.release();for(int i=0;i<3*240;i++)tick(world);
    const auto after=world.poses();
    double mass=0,after_mass=0;
    for(const auto &p:before)mass+=p.mass_kg;
    for(const auto &p:after)after_mass+=p.mass_kg;
    require(after.size()==before.size() && std::abs(after_mass-mass)<1e-9,"recovery preserves native bodies and mass");
    const auto joints_after=world.joints();
    require(joints_after.size()==joints_before.size(),"recovery preserves joints");
    for(std::size_t i=0;i<joints_before.size() && i<joints_after.size();i++)
        require(joints_after[i].attached==joints_before[i].attached,"recovery retains each actual joint attachment");
    require(!programOf(world,r.program).power && world.hand().holding.empty(),"release leaves the rover stopped and hand empty");
    require(posed(after,"rover").position_m.z<-1.5,"released rover rests beyond the pit");
    std::cout<<"    pit drop "<<original.y-fallen.y<<" m; lift "<<lifted.y-fallen.y
             <<" m; peak hand "<<peak<<" N; measured work "<<work<<" J; native mass "<<mass
             <<" kg; unclosed work - delta mechanical energy "<<unclosed<<" J\n";
}

void machineDigUsesActualAttachedCollisionShapes() {
    Rover r=dryGroundRover();
    std::string why;
    const auto before=r.world->snapshot(why);
    require(!before.empty(),"the support-check fixture saves: "+why);
    const auto under=r.world->digClearance(r.program,0,0,0,0,.5);
    require(!under.clear && under.why.find("support below")!=std::string::npos,"dig reads actual support");
    const double narrow_margin=.05+std::sqrt(2.0)*r.world->environment()->terrain().grid().dx;
    const auto wheel=r.world->digClearance(r.program,.35+narrow_margin+.02,-.32,.35+narrow_margin+.02,-.32,.1);
    require(!wheel.clear && wheel.why.find("left wheel")!=std::string::npos,
            "attached wheel support outside the chassis is included");
    bool refused=false;
    try { r.world->dig(0,0,0,0,.5,.15,r.program); }
    catch(const std::invalid_argument &) { refused=true; }
    require(refused,"actual machine dig refuses its support before editing");
    require(r.world->snapshot(why)==before,"clearance and refused dig preserve the complete native snapshot");
    const auto pose=posed(r.world->poses(),"rover");
    const double reach=under.stand_off_m+.02;
    const auto ahead=pose.position_m+Vec3{0,0,reach};
    require(r.world->digClearance(r.program,ahead.x,ahead.z,ahead.x,ahead.z,.5).clear,"bounded reach clears the assembly");
    require(!r.world->dig(ahead.x,ahead.z,ahead.x,ahead.z,.5,.15,r.program).edit.cells.empty(),"safe machine dig removes actual native ground");
    const auto wide=r.world->digClearance(r.program,ahead.x,ahead.z,ahead.x,ahead.z,2);
    require(!wide.clear,"a wider scoop cannot bypass footprint clearance");
    std::cout<<"    shape-derived scoop stand-off "<<under.stand_off_m<<" m; wide scoop refused\n";
}

void groundSensorsReadActualHolesAndSurviveSaving() {
    Rover r=dryGroundRover();
    const auto at=posed(r.world->poses(),"rover").position_m;
    for (double x : {-.55,0.0,.55})
        require(r.world->programSense(r.program,"ground","rover",at+Vec3{x,0,1.5},.12,1),"front ground probe fits");
    for (double x : {-.55,.55})
        require(r.world->programSense(r.program,"ground","rover",at+Vec3{x,0,-.9},.12,-1),"rear ground probe fits");
    auto said=programOf(*r.world,r.program);
    for(const auto &sensor:said.sensors)require(!sensor.sees,"continuous basin is not a hole");
    const auto cut=r.world->dig(-1,1.5,1,1.5,.8,1.0);
    require(!cut.edit.cells.empty(),"the hole edits real native ground");
    for(int i=0;i<24;i++)tick(*r.world);
    said=programOf(*r.world,r.program);
    require(said.sensors[1].reading_m>.4 && said.sensors[1].sees,"ground probe sees an actual dry drop");
    require(!said.sensors[3].sees && !said.sensors[4].sees,"rear reads the unchanged ground behind");
    std::string why;
    const auto saved=r.world->snapshot(why);
    require(!saved.empty(),"ground probes save: "+why);
    TileImpactRequest request=shoreRoom();
    auto env=nlohmann::json::parse(request.environment_scene_json);
    env["terrain"]["generate"]["lake_level_m"]=0.0;
    request.environment_scene_json=env.dump();request.precise_rigid_scene_json=roverScene({0,.22,0});
    auto again=LiveWorld::open(request,saved);
    const auto is=programOf(*again,r.program);
    require(is.sensors.size()==5 && is.sensors[1].kind=="ground" && is.sensors[3].stops==-1,
            "saving retains kind, threshold and rear direction");
    require(std::abs(is.sensors[1].reading_m-said.sensors[1].reading_m)<1e-6,"reopen retains the measured dry drop");
    runIt(*r.world,r.program,true,1);
    bool avoided=false;double closest=0;
    for(int i=0;i<6*240;i++) {
        tick(*r.world);const auto now=programOf(*r.world,r.program);
        avoided=avoided || now.why.find("ground drop/step")!=std::string::npos;
        const auto p=posed(r.world->poses(),"rover").position_m;
        closest=std::max(closest,p.z);
    }
    std::cout<<"    dry drop "<<said.sensors[1].reading_m<<" m; closest chassis z "<<closest<<" m\n";
    require(avoided,"native rover reports ground avoidance");
    require(closest<.8,"native torque/brakes keep the chassis before its dry hole");
}

void requestedReverseStopsAtActualRearHazards() {
    Rover clear=dryGroundRover();
    const auto clear_start=posed(clear.world->poses(),"rover").position_m;
    for(double x:{-.55,.55})
        require(clear.world->programSense(clear.program,"ground","rover",clear_start+Vec3{x,0,-1.2},.12,-1),"clear rear probe fits");
    runIt(*clear.world,clear.program,true,1);
    askIt(*clear.world,clear.program,"backing off",5.,2);
    for(int i=0;i<120;i++)tick(*clear.world);
    const double clear_travel=clear_start.z-posed(clear.world->poses(),"rover").position_m.z;
    require(clear_travel>.02,"a clear autonomous reverse moves through actual motors");
    Rover r=dryGroundRover();
    const auto at=posed(r.world->poses(),"rover").position_m;
    for(double x:{-.55,.55})
        require(r.world->programSense(r.program,"ground","rover",at+Vec3{x,0,-1.2},.12,-1),"rear probe fits");
    require(!r.world->dig(-1,-1.2,1,-1.2,.8,.6).edit.cells.empty(),"rear drop cuts actual terrain");
    for(int i=0;i<24;i++)tick(*r.world);
    const auto sensed=programOf(*r.world,r.program);
    require(sensed.sensors[0].sees && sensed.sensors[1].sees,"both rear probes detect the dry drop");
    runIt(*r.world,r.program,true,1);
    const auto start=posed(r.world->poses(),"rover").position_m;
    askIt(*r.world,r.program,"backing off",5.,2);
    double most=0;
    for(int i=0;i<240;i++) {
        tick(*r.world);
        most=std::max(most,start.z-posed(r.world->poses(),"rover").position_m.z);
        require(programOf(*r.world,r.program).doing=="waiting","rear hazard brakes the autonomous reverse");
    }
    require(most<.01,"an autonomous requested reverse does not enter the rear drop");
    require(programOf(*r.world,r.program).why.find("rear probes")!=std::string::npos,"held reverse gives its reason");
    askIt(*r.world,r.program,"backing off",5.,3,"explicit person",nullptr,true);
    for(int i=0;i<120;i++)tick(*r.world);
    require(programOf(*r.world,r.program).doing=="backing off","explicit human control retains its override");
    const double human=start.z-posed(r.world->poses(),"rover").position_m.z;
    require(human>.02,"human override drives actual wheels");
    std::cout<<"    reverse: clear autonomous travel "<<clear_travel<<" m; rear-hazard travel "<<most<<" m; explicit human travel "<<human<<" m\n";
}

void nativeApproachRadiusMovesAndStopsWithoutAPoseConstraint() {
    for(double near:{1.,.2}) {
        auto world=LiveWorld::open(flatRoom());const auto m=fit(*world,pinUp(*world));
        const auto id=world->program("rover","roam",m.left,m.right,"rover",1.,8.);
        for(int i=0;i<2*240;i++)tick(*world);
        const auto from=posed(world->poses(),"rover").position_m;
        runIt(*world,id,true,1);
        LiveWorld::ProgramAsk ask;ask.sender="waypoint-test";ask.seq=1;ask.doing="approaching";
        ask.has_toward=true;ask.toward_m=from+Vec3{0,0,.7};ask.for_s=20.;ask.near_m=near;
        require(world->behave(id,ask)=="applied","native bounded approach accepted");
        std::string why;const auto before=world->snapshot(why);
        ask.near_m=.01;ask.seq=2;
        require(world->behave(id,ask)!="applied" && world->snapshot(why)==before,
                "invalid approach radius preserves complete native state and sender sequence");
        for(int i=0;i<240;i++)tick(*world);
        const auto saved=world->snapshot(why);auto again=LiveWorld::open(flatRoom(),saved);
        require(programOf(*again,id).asked_near_m==near,"saved native approach radius is restored");
        for(int i=0;i<4*240;i++)tick(*again);
        const auto to=posed(again->poses(),"rover").position_m;
        const double travelled=to.z-from.z;
        const double off=std::hypot(to.x-ask.toward_m.x,to.z-ask.toward_m.z);
        std::cout<<"    approach radius "<<near<<" m; target .7 m; travelled "<<travelled<<" m; off "<<off<<" m\n";
        if(near==1.)require(std::abs(travelled)<.05,"legacy default still waits within one metre");
        else require(travelled>.45 && off<.35,"smaller waypoint radius drives and brakes through native motors");
        require(programOf(*again,id).doing=="waiting","native approach ends in actual waiting");
        for(const auto &j:again->joints())require(j.attached,"waypoint drive preserves actual assembly joints");
    }
}

int main(int argc, char **argv) {
    const std::pair<const char *, void (*)()> tests[] = {
        {"bounded native approach radius moves and stops through actual motors",nativeApproachRadiusMovesAndStopsWithoutAPoseConstraint},
        {"ground probes distinguish actual terrain from body pitch",groundProbeDoesNotTreatBodyPitchAsTerrain},
        {"autonomous rover climbs native terrain to its declared pitch limit",autonomousGradesOnNativeTerrain},
        {"autonomous rover uses declared grade limit with actual native motors",autonomousGradeUsesMeasuredLimit},
        {"native ramp grades measure material mass, bounded torque, contact slip and energy",rampGradesMeasureNativeDriveSlipAndEnergy},
        {"bounded native hand recovers a rover from an actual excavation",boundedHandRecoversAnExcavatedRover},
        {"machine digging preserves support of actual attached collision shapes",machineDigUsesActualAttachedCollisionShapes},
        {"ground probes read and avoid a native dry hole and survive saving",groundSensorsReadActualHolesAndSurviveSaving},
        {"requested reverse stops at actual rear hazards",requestedReverseStopsAtActualRearHazards},
        {"it goes straight and turns on the spot", itGoesStraightAndTurnsOnTheSpot},
        {"it roams the shore and never gets wet", itRoamsTheShoreAndNeverGetsWet},
        {"a saved rover roams on", aSavedRoverRoamsOn},
        {"it rests in the sun and roams on", itRestsInTheSunAndRoamsOn},
        {"it rests through the night and roams on in the morning", itRestsThroughTheNightAndRoamsOnInTheMorning},
        {"it goes to the stool and sits on it", itGoesToTheStoolAndSitsOnIt},
        {"it does what it is asked for a while", itDoesWhatItIsAskedForAWhile},
        {"an ask that is not a person's never drives it into the water",
         anAskThatIsNotAPersonsNeverDrivesItIntoTheWater},
        {"a person's order drives it into the water", aPersonsOrderDrivesItIntoTheWater},
        {"a sensor says how long it has been seeing", aSensorSaysHowLongItHasBeenSeeing},
        {"it frees itself from a wall it drove into and roams on", itFreesItselfFromAWallItDroveIntoAndRoamsOn},
        {"it backs out of where it gets nowhere, and says when it cannot",
         itBacksOutOfWhereItGetsNowhereAndSaysWhenItCannot},
    };
    int ran=0;
    for (const auto &[name, test] : tests) {
        if(argc>1 && std::string(name).find(argv[1])==std::string::npos)continue;
        ++ran;
        const int before = failures;
        try {
            test();
        } catch (const std::exception &error) {
            std::cout << "[FAIL] " << name << ": " << error.what() << std::endl;
            ++failures;
        }
        if (failures == before) std::cout << "[PASS] " << name << std::endl;
    }
    require(ran>0,"test filter matches a registered native scenario");
    std::cout << (failures == 0 ? "all passed" : std::to_string(failures) + " failed") << std::endl;
    return failures == 0 ? 0 : 1;
}
