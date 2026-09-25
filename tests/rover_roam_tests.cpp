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
// 7. Asked to do something for a while (behave) -- by a person at its panel,
//    or by whatever thinks for it -- it does that instead of deciding for
//    itself, and goes on as it would have when the while is up: asked to back
//    off it backs off; asked to wait it holds still, on, until asked otherwise;
//    asked to face a point it turns on the spot until its front is towards it
//    and waits there; a stale ask changes nothing; turned off it drops the
//    ask; and a saved world gives it back doing what it was asked, as far in.
// 8. An ask never drives it into the water: asked to approach a point in the
//    lake, its reflexes have it when a sensor sees water -- it backs off and
//    turns away -- and no wheel gets wet; the ask stands, and it says so.

#include "fastlattice/LiveWorld.hpp"
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
Pins pinUp(LiveWorld &world, Vec3 at = {}) {
    Pins p;
    p.left = world.hinge("rover", "rover: left wheel", at + Vec3{0.1925, 0.16, -0.32}, {1.0, 0.0, 0.0});
    p.right = world.hinge("rover", "rover: right wheel", at + Vec3{-0.1925, 0.16, -0.32}, {1.0, 0.0, 0.0});
    p.swivel = world.hinge("rover", "rover: caster", at + Vec3{0.0, 0.31, 0.38}, {0.0, 1.0, 0.0});
    p.caster = world.hinge("rover: caster", "rover: caster wheel", at + Vec3{0.0, 0.08, 0.32}, {1.0, 0.0, 0.0});
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

} // namespace

void askIt(LiveWorld &world, unsigned program, const std::string &doing, double for_s, std::uint64_t seq,
           const std::string &why = "the test asked", const Vec3 *toward = nullptr) {
    LiveWorld::ProgramAsk ask;
    ask.sender = "test";
    ask.seq = seq;
    ask.doing = doing;
    ask.why = why;
    ask.for_s = for_s;
    if (toward != nullptr) {
        ask.has_toward = true;
        ask.toward_m = *toward;
    }
    const std::string said = world.behave(program, ask);
    if (said != "applied") throw std::runtime_error("the program did not take the ask: " + said);
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
    require(said.doing == "turning left" || said.doing == "turning right",
            "asked to face what is behind it, it turns on the spot: " + said.doing);
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

void anAskNeverDrivesItIntoTheWater() {
    Rover r = roverOnTheShore();
    LiveWorld &world = *r.world;
    runIt(world, r.program, true, 1);
    for (int i = 0; i < 240; ++i) tick(world);
    // The lake's middle is at the origin: asked to approach it, it heads in.
    const Vec3 middle{0.0, 0.0, 0.0};
    askIt(world, r.program, "approaching", 60.0, 2, "the test sent it into the lake", &middle);
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

int main() {
    const std::pair<const char *, void (*)()> tests[] = {
        {"it goes straight and turns on the spot", itGoesStraightAndTurnsOnTheSpot},
        {"it roams the shore and never gets wet", itRoamsTheShoreAndNeverGetsWet},
        {"a saved rover roams on", aSavedRoverRoamsOn},
        {"it rests in the sun and roams on", itRestsInTheSunAndRoamsOn},
        {"it rests through the night and roams on in the morning", itRestsThroughTheNightAndRoamsOnInTheMorning},
        {"it does what it is asked for a while", itDoesWhatItIsAskedForAWhile},
        {"an ask never drives it into the water", anAskNeverDrivesItIntoTheWater},
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
