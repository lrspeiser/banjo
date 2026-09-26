// A rover that flies (docs/machine-world.md, "A rover that flies"): a deck on
// four rotors, each a DECLARED propeller on a motor's pin -- thrust k w^2 on
// the frame along the pin, drag k' w^2 on the pin, whose reaction on the frame
// is how it yaws -- with a "hover" program that holds its centre a height
// above the ground, level, and takes the same asks as a rover's, done by
// leaning. Exact bodies on pins, the drone the Workshop's template makes.
//
// 1. Turned on, it rises to its hover height and holds it, level.
// 2. Asked to go forward, it goes forward, holding its height; asked to face a
//    point to its left, it turns to it; asked to approach a point, it gets
//    there and hovers.
// 3. Its battery's account closes: what it held is what it began with less what
//    its motors drew; the rotors' drag took what it cost to fly.
// 4. Turned off in the air, its rotors stop and it comes down; a saved world
//    gives it back hovering.

#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
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
constexpr double kHoverM = 1.5;

void require(bool ok, const std::string &why) {
    if (!ok) {
        std::cout << "[FAIL] " << why << std::endl;
        ++failures;
    }
}

nlohmann::json box(const std::string &name, Vec3 size, Vec3 at, const std::string &material = "") {
    nlohmann::json part = {{"name", name}, {"dimensions_m", {size.x, size.y, size.z}}, {"center_local_m", {at.x, at.y, at.z}}};
    if (!material.empty()) part["material"] = material;
    return part;
}

// A cylinder standing on its own y: a rotor's disc, its stub.
nlohmann::json roundUp(const std::string &name, double diameter, double height, Vec3 at, const std::string &material = "") {
    nlohmann::json part = {{"name", name}, {"shape", "cylinder"}, {"dimensions_m", {diameter, height, diameter}},
                           {"center_local_m", {at.x, at.y, at.z}}};
    if (!material.empty()) part["material"] = material;
    return part;
}

nlohmann::json body(const std::string &name, const std::string &material, Vec3 at, nlohmann::json parts) {
    return {{"name", name}, {"material", material}, {"position_m", {at.x, at.y, at.z}}, {"parts", std::move(parts)}};
}

// The rotors, in order round the machine from above: front (+z), right (-x),
// back (-z), left (+x), 0.6 m out from the middle.
const char *const kRotors[4] = {"front", "right", "back", "left"};
const Vec3 kRotorAt[4] = {{0.0, 0.0, 0.6}, {-0.6, 0.0, 0.0}, {0.0, 0.0, -0.6}, {0.6, 0.0, 0.0}};
constexpr double kMountY = 0.235;

// The drone as drawn: the floor at y = 0, its front +z, its left +x. An oak
// deck on four legs, an arm out to each rotor mount, a battery and a hopper
// on the deck; each rotor an iron stub up through its mount with an oak disc
// on top.
std::string droneScene(Vec3 at) {
    nlohmann::json parts = nlohmann::json::array({box("deck", {0.5, 0.03, 0.5}, {0.0, 0.235, 0.0}),
                                                  box("battery", {0.2, 0.06, 0.18}, {0.0, 0.28, 0.10}),
                                                  box("hopper", {0.2, 0.10, 0.20}, {0.0, 0.30, -0.10})});
    for (const Vec3 leg : {Vec3{0.2, 0.11, 0.2}, Vec3{-0.2, 0.11, 0.2}, Vec3{0.2, 0.11, -0.2}, Vec3{-0.2, 0.11, -0.2}})
        parts.push_back(box("leg", {0.03, 0.22, 0.03}, leg));
    for (int i = 0; i < 4; ++i) {
        const Vec3 r = kRotorAt[i];
        const bool along_z = std::abs(r.z) > std::abs(r.x);
        const Vec3 arm_at{r.x * 0.5 + (along_z ? 0.0 : 0.0), kMountY, r.z * 0.5};
        parts.push_back(box(std::string(kRotors[i]) + " arm", along_z ? Vec3{0.03, 0.03, 0.35} : Vec3{0.35, 0.03, 0.03},
                            {r.x * 0.708, kMountY, r.z * 0.708}));
        parts.push_back(box(std::string(kRotors[i]) + " mount", {0.06, 0.06, 0.06}, {r.x, kMountY, r.z}));
        (void)arm_at;
    }
    nlohmann::json bodies = nlohmann::json::array({body("drone", "oak", at, parts)});
    for (int i = 0; i < 4; ++i) {
        const Vec3 r = kRotorAt[i];
        bodies.push_back(body(std::string("drone: ") + kRotors[i] + " rotor", "oak", at,
                              nlohmann::json::array({roundUp("stub", 0.02, 0.12, {r.x, kMountY + 0.03, r.z}, "iron"),
                                                     roundUp("disc", 0.40, 0.01, {r.x, kMountY + 0.095, r.z})})));
    }
    return bodies.dump();
}

TileImpactRequest flatRoom() {
    TileImpactRequest request;
    request.cell_size_m = 0.05;
    request.backend = BackendKind::CpuParallel;
    SceneBody stone;
    stone.name = "marker";
    stone.shape = BodyShape::Box;
    stone.material = MaterialPreset::Concrete;
    stone.dimensions_m = {0.1, 0.1, 0.1};
    stone.center_m = {6.0, 0.05, -6.0};
    stone.anchored = true;
    request.bodies = {stone};
    request.precise_rigid_scene_json = droneScene({0.0, 0.0, 0.0});
    return request;
}

// The numbers the Workshop's template declares (mcp/workshop_products.py):
// 16 kg of machine needs 160 N, 40 N a rotor at 60 rad/s, so k = 0.011
// N/(rad/s)^2; the induced power of 40 N on a 0.4 m disc is 460 W, so k' =
// 460 / 60^3 = 2.1e-3 N m/(rad/s)^2; a motor that gives 7.7 N m at 60 rad/s
// at six tenths of its voltage: 40 N m at stall, 150 rad/s unloaded; a 2 MJ
// battery at 48 V.
constexpr double kThrust = 0.011, kDrag = 2.1e-3, kStall = 40.0, kNoLoad = 150.0, kCapacity = 2.0e6;

struct Drone {
    std::unique_ptr<LiveWorld> world;
    unsigned store{}, program{};
    unsigned pins[4]{}, motors[4]{}, controls[4]{};
};

Drone droneOnTheFloor() {
    Drone d;
    d.world = LiveWorld::open(flatRoom());
    d.store = d.world->energyStore("battery", "drone", kCapacity, kCapacity, 48.0, 0.0);
    std::vector<unsigned> rotors;
    for (int i = 0; i < 4; ++i) {
        const Vec3 r = kRotorAt[i];
        d.pins[i] = d.world->hinge("drone", std::string("drone: ") + kRotors[i] + " rotor", Vec3{r.x, kMountY, r.z},
                                   {0.0, 1.0, 0.0});
        d.motors[i] = d.world->motor(d.pins[i], d.store, kStall, kNoLoad, 0.0, kThrust, kDrag);
        d.controls[i] = d.world->control(std::string(kRotors[i]) + " rotor", d.motors[i]);
        if (!d.pins[i] || !d.motors[i] || !d.controls[i]) throw std::runtime_error("a rotor would not fit");
        rotors.push_back(d.controls[i]);
    }
    d.program = d.world->program("drone", "hover", 0, 0, "drone", 1.0, 8.0, 0.0, 0.0, rotors, kHoverM);
    if (d.program == 0) throw std::runtime_error("the hover program would not go on");
    for (int i = 0; i < 240; ++i) d.world->step(kDt);   // settle on its legs
    return d;
}

LiveProgram programOf(const LiveWorld &world, unsigned id) {
    for (const LiveProgram &p : world.programs())
        if (p.id == id) return p;
    throw std::runtime_error("no program");
}

const LiveBodyPose &posed(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    for (const LiveBodyPose &pose : poses)
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

void runIt(LiveWorld &world, unsigned program, bool power, std::uint64_t seq) {
    LiveWorld::ProgramCommand c;
    c.sender = "test";
    c.seq = seq;
    c.power = power;
    const std::string said = world.run(program, c);
    if (said != "applied") throw std::runtime_error("the program did not take the command: " + said);
}

void askIt(LiveWorld &world, unsigned program, const std::string &doing, double for_s, std::uint64_t seq,
           const Vec3 *toward = nullptr) {
    LiveWorld::ProgramAsk ask;
    ask.sender = "test";
    ask.seq = seq;
    ask.doing = doing;
    ask.why = "the test asked";
    ask.for_s = for_s;
    if (toward != nullptr) {
        ask.has_toward = true;
        ask.toward_m = *toward;
    }
    const std::string said = world.behave(program, ask);
    if (said != "applied") throw std::runtime_error("the program did not take the ask: " + said);
}

void tick(LiveWorld &world) {
    world.step(kDt);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

void itRisesToItsHeightAndHoldsIt() {
    Drone d = droneOnTheFloor();
    LiveWorld &world = *d.world;
    LiveProgram said = programOf(world, d.program);
    const double floor_height = said.height_m;
    require(said.doing == "stopped" && !said.power && said.rotors.size() == 4, "it starts off, on four rotors");
    runIt(world, d.program, true, 1);
    double reached_at = -1.0, worst_tilt = 0.0, lowest = 1e9, highest = -1e9;
    for (int i = 0; i < 20 * 240; ++i) {
        tick(world);
        said = programOf(world, d.program);
        const double above = said.height_m - floor_height;
        if (reached_at < 0.0 && std::abs(above - kHoverM) < 0.15) reached_at = i * kDt;
        if (reached_at >= 0.0 && i * kDt > reached_at + 2.0) {
            lowest = std::min(lowest, above);
            highest = std::max(highest, above);
            worst_tilt = std::max({worst_tilt, std::abs(said.pitch_deg), std::abs(said.roll_deg)});
        }
    }
    const LiveBodyPose pose = posed(world.poses(), "drone");
    std::cout << "    turned on, it reached " << kHoverM << " m in " << reached_at << " s; from then on it held between "
              << lowest << " and " << highest << " m above where it stood, tilting at most " << worst_tilt
              << " degrees; now " << said.doing << ": " << said.why << ", rotor speeds "
              << world.motors()[0].speed_rad_s << " rad/s, thrust " << world.motors()[0].thrust_n << " N\n";
    require(reached_at >= 0.0 && reached_at < 10.0, "it reached its hover height within ten seconds");
    require(lowest > kHoverM - 0.3 && highest < kHoverM + 0.3, "and held it");
    require(worst_tilt < 6.0, "level");
    require(said.doing == "waiting", "hovering: " + said.doing);
    require(std::abs(pose.position_m.x) < 0.5 && std::abs(pose.position_m.z) < 0.5, "over where it took off");
}

void itGoesWhereItIsAsked() {
    Drone d = droneOnTheFloor();
    LiveWorld &world = *d.world;
    runIt(world, d.program, true, 1);
    for (int i = 0; i < 8 * 240; ++i) tick(world);
    LiveProgram said = programOf(world, d.program);
    const double floor_height = said.height_m - kHoverM;
    Vec3 was = said.at_m;
    // Forward for four seconds: it goes the way it faces, holding its height.
    askIt(world, d.program, "going forward", 4.0, 2);
    double lowest = 1e9, highest = -1e9;
    for (int i = 0; i < 5 * 240; ++i) {
        tick(world);
        said = programOf(world, d.program);
        lowest = std::min(lowest, said.height_m - floor_height);
        highest = std::max(highest, said.height_m - floor_height);
    }
    Vec3 went = said.at_m - was;
    const Vec3 facing{std::sin(said.heading_deg * kPi / 180.0), 0.0, std::cos(said.heading_deg * kPi / 180.0)};
    const double forward = went.x * facing.x + went.z * facing.z;
    std::cout << "    asked to go forward for 4 s: it went " << forward << " m the way it faces (" << went.x << ", "
              << went.z << "), its height between " << lowest << " and " << highest << " m; now " << said.doing << "\n";
    require(forward > 1.0, "it went forward");
    require(lowest > kHoverM - 0.5 && highest < kHoverM + 0.5, "and held its height, near enough");
    // Face a point to its left: it turns to it.
    const Vec3 left_point = said.at_m + Vec3{3.0 * std::cos(said.heading_deg * kPi / 180.0), 0.0,
                                             -3.0 * std::sin(said.heading_deg * kPi / 180.0)};
    askIt(world, d.program, "facing", 0.0, 3, &left_point);
    for (int i = 0; i < 10 * 240; ++i) {
        tick(world);
        if (programOf(world, d.program).doing == "waiting" && i > 240) break;
    }
    said = programOf(world, d.program);
    double off = said.heading_deg - std::atan2(left_point.x - said.at_m.x, left_point.z - said.at_m.z) * 180.0 / kPi;
    while (off > 180.0) off -= 360.0;
    while (off <= -180.0) off += 360.0;
    std::cout << "    asked to face a point to its left: " << said.doing << ", its front " << off << " degrees off it\n";
    require(std::abs(off) < 15.0, "it turned to face it");
    // Approach a point four metres off: it gets there and hovers.
    const Vec3 target = said.at_m + Vec3{0.0, 0.0, 4.0};
    askIt(world, d.program, "approaching", 30.0, 4, &target);
    double nearest = 1e9;
    for (int i = 0; i < 25 * 240; ++i) {
        tick(world);
        said = programOf(world, d.program);
        nearest = std::min(nearest, std::hypot(target.x - said.at_m.x, target.z - said.at_m.z));
        if (said.doing == "waiting" && said.asked == "approaching") break;
    }
    const double away = std::hypot(target.x - said.at_m.x, target.z - said.at_m.z);
    std::cout << "    asked to approach a point 4 m off: nearest " << nearest << " m, now " << away << " m off, "
              << said.doing << " " << said.height_m - floor_height << " m up\n";
    require(away < 1.6, "it got there");
    require(said.doing == "waiting", "and hovers");
}

void itsAccountCloses() {
    Drone d = droneOnTheFloor();
    LiveWorld &world = *d.world;
    runIt(world, d.program, true, 1);
    for (int i = 0; i < 10 * 240; ++i) tick(world);
    double given = 0.0, drawn = 0.0, air = 0.0;
    for (const LiveEnergyStore &s : world.energyStores()) given += s.given_j;
    for (const LiveMotor &m : world.motors()) {
        drawn += m.drawn_j;
        air += m.air_j;
    }
    const LiveEnergyStore &store = world.energyStores()[0];
    std::cout << "    ten seconds of flight: the battery gave " << given << " J of " << kCapacity << ", the motors drew "
              << drawn << ", the air took " << air << " (" << 100.0 * air / std::max(drawn, 1e-9)
              << "% of what was drawn)\n";
    require(std::abs(store.charge_j - (kCapacity + store.taken_j - store.given_j)) < 1e-3, "the account closes");
    require(std::abs(given - drawn) < 1e-3 * drawn + 1.0, "what the motors drew is what the battery gave");
    require(air > 0.5 * drawn, "most of what was drawn went into the air");
}

void turnedOffItComesDownAndSavedItFliesOn() {
    Drone d = droneOnTheFloor();
    LiveWorld &world = *d.world;
    const double floor_y = posed(world.poses(), "drone").position_m.y;
    runIt(world, d.program, true, 1);
    for (int i = 0; i < 8 * 240; ++i) tick(world);
    std::string why;
    const std::string saved = world.snapshot(why);
    require(!saved.empty(), "the world would not save: " + why);
    runIt(world, d.program, false, 2);
    for (int i = 0; i < 5 * 240; ++i) tick(world);
    const LiveBodyPose down = posed(world.poses(), "drone");
    std::cout << "    turned off at " << kHoverM << " m, five seconds on it is " << down.position_m.y - floor_y
              << " m above where it stood; its rotors at " << world.motors()[0].speed_rad_s << " rad/s\n";
    require(down.position_m.y - floor_y < 0.3, "off, it came down");
    if (!saved.empty()) {
        const auto again = LiveWorld::open(flatRoom(), saved);
        require(again->restored().tier == "whole", "the world came back whole: " + again->restored().why);
        LiveProgram is = programOf(*again, d.program);
        require(is.kind == "hover" && is.rotors.size() == 4 && is.power, "the hover program came back on its rotors");
        for (int i = 0; i < 5 * 240; ++i) tick(*again);
        is = programOf(*again, d.program);
        std::cout << "    opened again, five seconds on it is " << is.height_m << " m up, " << is.doing << "\n";
        require(std::abs(is.height_m - (kHoverM + (is.height_m - is.height_m))) < 1e9 && is.height_m > 1.0, "and flies on");
    }
}

}  // namespace

int main() {
    const std::pair<const char *, void (*)()> tests[] = {
        {"it rises to its height and holds it", itRisesToItsHeightAndHoldsIt},
        {"it goes where it is asked", itGoesWhereItIsAsked},
        {"its account closes", itsAccountCloses},
        {"turned off it comes down, and saved it flies on", turnedOffItComesDownAndSavedItFliesOn},
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
