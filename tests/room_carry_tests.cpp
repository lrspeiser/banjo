// A room opened again from a scene that has changed keeps everything the change
// did not touch (LiveWorld::open with a LiveCarry).
//
// The owner, 2026-09-15: "nothing should be resetting rooms". Every change the
// room's chat made, and every thing an action stood up, opened the room again
// from its spec, which put everything back where it was authored: what had been
// moved, what had broken, dents, a gate swung open, a hoist's crate wound up and
// its battery's charge, what the hand held, heat. Here a room where all of that
// has happened is saved, its scene is changed -- a thing added, a thing taken
// away, a thing moved -- and it is opened carrying what was saved:
//
// 1. Everything the change did not touch comes back exactly as it was saved:
//    each body field for field and each cell under its new number, the joints
//    reading what they read (a pin to a millionth of a radian, as a restart's),
//    the battery, the motor, the hand and the heat.
// 2. What the change touched is as the scene has it, and `restored` says so
//    thing by thing.
// 3. The room goes on from there: the hoist winds on and the gate still swings.
// 4. What cannot be carried exactly falls back for that thing alone and says
//    why: a pin the room no longer declares the same way, cells that are not
//    the saved ones, heat the room declares anew.

#include "fastlattice/LiveWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using namespace banjo;
using namespace banjo::fastlattice;

constexpr double kPi = 3.14159265358979323846;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}

// How the scene is changed.
struct Change {
    bool new_crate{};                        // a thing added, first, so every other thing's cells move
    bool no_anvil{};                         // a thing taken away, first, likewise
    Vec3 rolling_ball_at{-0.6, 0.04, -1.2};  // where the rolling ball is authored
    double hot_block_k{700.0};               // how hot the room declares the hot block
};

const Vec3 kDoorPin{0.04, 0.45, 1.2};
const Vec3 kDrum{3.0, 2.0, 0.0};
const Vec3 kAxle{0.0, 0.0, 1.0};
constexpr double kDrumRadiusM = 0.1;

// A room with one of everything a change must not reset, far enough apart not
// to meet: an iron ball to be dented on an anvil and a pane to be broken
// (live_world_tests' workshop), a door on a post, a battery hoist
// (motor_tests' hoistRoom, moved over), an iron block declared hot and another
// to be warmed, a mallet to be held, and a ball to be carried somewhere else.
TileImpactRequest carryRoom(const Change &change = {}) {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = BackendKind::CpuParallel;
    const auto box = [](const char *name, MaterialPreset material, Vec3 size, Vec3 at, bool anchored = false) {
        SceneBody body;
        body.name = name;
        body.shape = BodyShape::Box;
        body.material = material;
        body.dimensions_m = size;
        body.center_m = at;
        body.anchored = anchored;
        return body;
    };
    const auto ball = [](const char *name, double diameter, Vec3 at, Vec3 velocity = {}) {
        SceneBody body;
        body.name = name;
        body.shape = BodyShape::Sphere;
        body.material = MaterialPreset::Iron;
        body.dimensions_m = {diameter, diameter, diameter};
        body.center_m = at;
        body.velocity_m_s = velocity;
        return body;
    };
    if (change.new_crate) r.bodies.push_back(box("new crate", MaterialPreset::Oak, {0.2, 0.2, 0.2}, {-3.0, 0.1, 3.0}));
    if (!change.no_anvil)
        r.bodies.push_back(box("anvil", MaterialPreset::Iron, {0.3, 0.12, 0.3}, {-1.2, 0.06, 0.0}, true));
    r.bodies.push_back(ball("iron ball", 0.1, {-1.2, 0.20, 0.0}, {0.0, -16.0, 0.0}));
    r.bodies.push_back(box("left pier", MaterialPreset::Iron, {0.08, 0.40, 0.20}, {0.94, 0.20, 0.0}, true));
    r.bodies.push_back(box("right pier", MaterialPreset::Iron, {0.08, 0.40, 0.20}, {1.46, 0.20, 0.0}, true));
    r.bodies.push_back(box("pane", MaterialPreset::Glass, {0.60, 0.02, 0.20}, {1.2, 0.41, 0.0}));
    r.bodies.push_back(ball("glass breaker", 0.12, {1.2, 0.42 + 0.06 + 3.0, 0.0}));
    r.bodies.push_back(box("post", MaterialPreset::Oak, {0.06, 1.0, 0.06}, {0.0, 0.5, 1.2}, true));
    r.bodies.push_back(box("door", MaterialPreset::Oak, {0.5, 0.8, 0.04}, {0.30, 0.45, 1.2}));
    r.bodies.push_back(box("hoist post", MaterialPreset::Iron, {0.1, 2.0, 0.1}, {2.6, 1.0, 0.0}, true));
    r.bodies.push_back(box("drum", MaterialPreset::Oak, {0.2, 0.2, 0.3}, kDrum));
    // Every box a whole number of the room's 20 mm cells.
    r.bodies.push_back(box("crate", MaterialPreset::Iron, {0.16, 0.16, 0.16}, {3.1, 0.42, 0.0}));
    r.bodies.push_back(box("hot block", MaterialPreset::Iron, {0.1, 0.1, 0.1}, {-2.4, 0.05, 1.2}));
    r.bodies.push_back(box("warm block", MaterialPreset::Iron, {0.1, 0.1, 0.1}, {-2.4, 0.05, -1.2}));
    r.bodies.push_back(box("mallet", MaterialPreset::Oak, {0.3, 0.06, 0.06}, {-2.4, 0.03, 0.0}));
    r.bodies.push_back(ball("rolling ball", 0.08, change.rolling_ball_at));
    char hot[96];
    std::snprintf(hot, sizeof hot, R"({"bodies":[{"name":"hot block","temperature_k":%.17g}]})", change.hot_block_k);
    r.thermo_scene_json = hot;
    return r;
}

// Steps, answering every break the world offers by working it out there and
// then, as a host that waits for each would.
void stepAnswering(LiveWorld &world, int steps, double dt_s = 1.0 / 240.0) {
    for (int i = 0; i < steps; ++i) {
        world.step(dt_s);
        for (const std::string &name : world.breakable()) (void)world.fracture(name);
    }
}

const LiveBodyPose &named(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    for (const LiveBodyPose &pose : poses)
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

LiveJoint jointOf(const LiveWorld &world, unsigned id) {
    for (const LiveJoint &j : world.joints())
        if (j.id == id) return j;
    throw std::runtime_error("there is no joint " + std::to_string(id));
}

LiveMotor motorOf(const LiveWorld &world, unsigned id) {
    for (const LiveMotor &m : world.motors())
        if (m.id == id) return m;
    throw std::runtime_error("there is no motor " + std::to_string(id));
}

// The room, played: everything a change must not reset has happened in it, and
// it is saved.
struct Played {
    std::unique_ptr<LiveWorld> world;
    unsigned door_pin{}, hoist_pin{}, rope{}, battery{}, motor{};
    std::string saved;
    nlohmann::json doc;
    std::size_t pieces{};
};

const Played &played() {
    static const Played room = [] {
        Played p;
        p.world = LiveWorld::open(carryRoom());
        LiveWorld &w = *p.world;
        w.foreseeCollisions(0.0);
        // The door on its post and the hoist put together as the room opens,
        // as a host hangs a room's pins before it steps: a drum and a crate
        // left unhung fall to the ground before anything holds them.
        p.door_pin = w.hinge("post", "door", kDoorPin, {0.0, 1.0, 0.0}, -90.0, 90.0, 2.0);
        p.hoist_pin = w.hinge("hoist post", "drum", kDrum, kAxle);
        p.rope = w.drum("drum", "crate", kDrum, kAxle, kDrumRadiusM, {3.1, 0.5, 0.0}, 1, 2.0);
        p.battery = w.energyStore("battery", "hoist post", 5000.0, 5000.0);
        p.motor = w.motor(p.hoist_pin, p.battery, 60.0, 10.0, 200.0);
        require(p.door_pin != 0 && p.hoist_pin != 0 && p.rope != 0 && p.battery != 0 && p.motor != 0,
                "the door would not hang, or the hoist would not go together");
        w.driveMotor(p.motor, 0.0, true);
        // The iron ball dents on the anvil in its first hundredth of a
        // second, and the glass breaker lands on the pane 0.78 s in.
        stepAnswering(w, 288, 1.0 / 480.0);
        stepAnswering(w, 240);
        for (const LiveBodyPose &pose : w.poses())
            if (pose.name.rfind("pane piece ", 0) == 0) ++p.pieces;
        require(named(w.poses(), "iron ball").dent_m > 0.0, "the iron ball took no dent, so this proves nothing about dents");
        require(p.pieces > 1, "the pane did not break, so this proves nothing about pieces");
        // The door, swung 50 degrees on its post; its pin's friction holds it.
        require(w.grab("door"), "the door could not be taken hold of");
        const double swing = 50.0 * kPi / 180.0;
        w.moveHeld({kDoorPin.x + 0.26 * std::cos(swing), 0.45, kDoorPin.z - 0.26 * std::sin(swing)});
        stepAnswering(w, 240);
        w.release();
        // The hoist, wound up for 0.8 s and braked at the top.
        w.driveMotor(p.motor, 1.0);
        stepAnswering(w, 192);
        w.driveMotor(p.motor, 0.0, true);
        stepAnswering(w, 240);
        // The rolling ball, carried 1.2 m and put down.
        require(w.grab("rolling ball"), "the rolling ball could not be picked up");
        w.moveHeld({-0.2, 0.3, -2.2});
        stepAnswering(w, 240);
        w.release();
        stepAnswering(w, 240);
        // The warm block, heated for a second while the mallet is taken up by
        // one end and held half a metre up: 10 kJ into 7.9 kg of iron, a few
        // kelvin (2 kJ was half a kelvin).
        (void)w.heat("warm block", 10000.0, 1.0);
        require(w.wield("mallet", {-2.52, 0.03, 0.0}), "the mallet could not be taken up");
        w.moveHeld({-2.4, 0.6, 0.0});
        stepAnswering(w, 240);
        std::string why;
        p.saved = w.snapshot(why);
        require(!p.saved.empty(), "the room could not be saved: " + why);
        p.doc = nlohmann::json::parse(p.saved);
        return p;
    }();
    return room;
}

const nlohmann::json *bodyIn(const nlohmann::json &doc, const std::string &name) {
    for (const nlohmann::json &b : doc.at("bodies"))
        if (b.at("name").get<std::string>() == name) return &b;
    return nullptr;
}

std::vector<std::string> namesIn(const nlohmann::json &doc) {
    std::vector<std::string> out;
    for (const nlohmann::json &b : doc.at("bodies")) out.push_back(b.at("name").get<std::string>());
    return out;
}

std::vector<std::uint32_t> numbersIn(const nlohmann::json &holder, const char *key) {
    const std::vector<std::uint8_t> bytes = terrain::decodeBase64(holder.at(key).get<std::string>());
    std::vector<std::uint32_t> out(bytes.size() / sizeof(std::uint32_t));
    if (!out.empty()) std::memcpy(out.data(), bytes.data(), out.size() * sizeof(std::uint32_t));
    return out;
}

std::vector<double> valuesIn(const nlohmann::json &holder, const char *key) {
    const std::vector<std::uint8_t> bytes = terrain::decodeBase64(holder.at(key).get<std::string>());
    std::vector<double> out(bytes.size() / sizeof(double));
    if (!out.empty()) std::memcpy(out.data(), bytes.data(), out.size() * sizeof(double));
    return out;
}

// Where a saved part's cells and bonds are numbered in the world it was carried
// into: the part authored exactly the same way, found by its definition.
struct Shift {
    std::int64_t node{}, bond{};
};

const nlohmann::json *partHolding(const nlohmann::json &doc, const char *key, std::uint32_t k) {
    for (const nlohmann::json &part : doc.at("parts"))
        if (k >= part.at(key).at(0).get<std::uint32_t>() && k < part.at(key).at(1).get<std::uint32_t>()) return &part;
    return nullptr;
}

Shift shiftOf(const nlohmann::json &saved_part, const nlohmann::json &now) {
    for (const nlohmann::json &part : now.at("parts"))
        if (part.at("definition") == saved_part.at("definition"))
            return {part.at("nodes").at(0).get<std::int64_t>() - saved_part.at("nodes").at(0).get<std::int64_t>(),
                    part.at("bonds").at(0).get<std::int64_t>() - saved_part.at("bonds").at(0).get<std::int64_t>()};
    throw std::runtime_error("the world carried into has no part authored as " + saved_part.at("bodies").dump());
}

// What the world opened again says it woke (LiveRestore::woken). Which things lie
// near what did not come back depends on where a break's pieces came to rest,
// and that is not the same on every machine: on Linux one of the pane's pieces
// lay by the door and was woken when the door came back shut, on Windows none did.
std::set<std::string> wokenBy(const LiveRestore &r) { return {r.woken.begin(), r.woken.end()}; }

// Every named body exactly as the saved world had it: field for field, and each
// of its cells under its new number -- its number in its own part, from where
// that part now begins. `woken` are the ones the world says it woke, since what
// they rested on did not come back as it was: each of those is awake, and every
// other one is asleep or awake as it was saved.
void requireCarriedExactly(const nlohmann::json &saved, const nlohmann::json &now, const std::vector<std::string> &names,
                           const std::set<std::string> &woken = {}) {
    std::size_t cells = 0;
    for (const std::string &name : names) {
        const nlohmann::json *a = bodyIn(saved, name);
        const nlohmann::json *b = bodyIn(now, name);
        require(a != nullptr, "the saved world has no " + name);
        require(b != nullptr, "the " + name + " did not come back");
        if (woken.count(name) != 0 && b->contains("awake"))
            require(b->at("awake").get<bool>(), "the " + name + " was said to be woken, and is asleep");
        for (const char *key : {"material", "shape", "dimensions_m", "revision", "color_rgba", "anchored", "fragment",
                                "dent_m", "dent_at_m", "body_id", "friction", "restitution", "rolling_resistance",
                                "from", "tilt_wxyz", "offsets_b64", "pose", "parked"}) {
            require(a->contains(key) == b->contains(key), "the " + name + "'s " + key + " is in only one of the two");
            if (a->contains(key))
                require(a->at(key) == b->at(key), "the " + name + "'s " + key + " differs: " + a->at(key).dump() +
                                                      " saved, " + b->at(key).dump() + " carried");
        }
        if (woken.count(name) == 0 && a->contains("awake"))
            require(a->at("awake") == b->at("awake"), "the " + name + " was " +
                                                          (a->at("awake").get<bool>() ? "awake" : "asleep") +
                                                          " when it was saved, and is not now");
        const std::vector<std::uint32_t> was = numbersIn(*a, "nodes_b64"), is = numbersIn(*b, "nodes_b64");
        require(was.size() == is.size() && !was.empty(), "the " + name + " has a different number of cells");
        const nlohmann::json *part = partHolding(saved, "nodes", was.front());
        require(part != nullptr, "the " + name + "'s cells are in no saved part");
        const Shift shift = shiftOf(*part, now);
        for (std::size_t k = 0; k < was.size(); ++k)
            require(static_cast<std::int64_t>(is[k]) == static_cast<std::int64_t>(was[k]) + shift.node,
                    "the " + name + "'s cell " + std::to_string(k) + " is number " + std::to_string(is[k]) +
                        ", and was " + std::to_string(was[k]) + " moved by " + std::to_string(shift.node));
        cells += was.size();
        const nlohmann::json &kerfs_then = saved.at("kerfs"), &kerfs_now = now.at("kerfs");
        require(kerfs_then.contains(name) == kerfs_now.contains(name) &&
                    (!kerfs_then.contains(name) || kerfs_then.at(name) == kerfs_now.at(name)),
                "the " + name + "'s cuts differ");
    }
    // What blades severed and each bond's permanent set -- a dent is made of
    // it -- under the bonds' new numbers, for the bonds of what came back.
    const std::set<std::string> carried(names.begin(), names.end());
    const auto bondOfCarried = [&](std::uint32_t k, std::int64_t &moved) {
        const nlohmann::json *part = partHolding(saved, "bonds", k);
        if (part == nullptr) return false;
        for (const nlohmann::json &body : part->at("bodies"))
            if (carried.count(body.get<std::string>()) == 0) return false;
        moved = shiftOf(*part, now).bond;
        return true;
    };
    const std::vector<std::uint32_t> dead_then = numbersIn(saved, "dead_bonds_b64");
    const std::vector<std::uint32_t> dead_now = numbersIn(now, "dead_bonds_b64");
    const std::set<std::uint32_t> dead(dead_now.begin(), dead_now.end());
    for (const std::uint32_t k : dead_then) {
        std::int64_t moved = 0;
        if (bondOfCarried(k, moved))
            require(dead.count(static_cast<std::uint32_t>(k + moved)) != 0,
                    "severed bond " + std::to_string(k) + " is whole again");
    }
    const nlohmann::json &set_then = saved.at("plastic"), &set_now = now.at("plastic");
    const std::vector<std::uint32_t> set_bonds_then = numbersIn(set_then, "bonds_b64");
    const std::vector<std::uint32_t> set_bonds_now = numbersIn(set_now, "bonds_b64");
    const std::vector<double> extension_then = valuesIn(set_then, "extension_b64");
    const std::vector<double> extension_now = valuesIn(set_now, "extension_b64");
    std::size_t sets = 0;
    for (std::size_t n = 0; n < set_bonds_then.size(); ++n) {
        std::int64_t moved = 0;
        if (!bondOfCarried(set_bonds_then[n], moved)) continue;
        const auto at = std::find(set_bonds_now.begin(), set_bonds_now.end(),
                                  static_cast<std::uint32_t>(set_bonds_then[n] + moved));
        require(at != set_bonds_now.end(), "bond " + std::to_string(set_bonds_then[n]) + " lost its permanent set");
        require(extension_now[static_cast<std::size_t>(at - set_bonds_now.begin())] == extension_then[n],
                "bond " + std::to_string(set_bonds_then[n]) + "'s permanent set differs");
        ++sets;
    }
    std::cout << "    " << names.size() << " things exactly as saved, " << cells << " cells under their new numbers, "
              << dead_then.size() << " severed bonds and " << sets << " bonds with a permanent set\n";
}

// The joints named, reading what they read: a pin to a millionth of a radian
// -- the solver works it out again from single-precision turns, as a
// restart's does -- and a drum's rope to the last bit.
void requireJointsAsSaved(const nlohmann::json &saved, const nlohmann::json &now, const std::set<unsigned> &ids) {
    for (const unsigned id : ids) {
        const nlohmann::json *a = nullptr, *b = nullptr;
        for (const nlohmann::json &j : saved.at("joints"))
            if (j.at("id").get<unsigned>() == id) a = &j;
        for (const nlohmann::json &j : now.at("joints"))
            if (j.at("id").get<unsigned>() == id) b = &j;
        require(a != nullptr && b != nullptr, "joint " + std::to_string(id) + " did not come back");
        nlohmann::json x = *a, y = *b;
        require(x.contains("held") == y.contains("held"), "joint " + std::to_string(id) + " holds in one only");
        if (x.contains("held")) {
            const double at_x = x["held"]["at"].get<double>(), at_y = y["held"]["at"].get<double>();
            require(std::abs(at_x - at_y) < 1e-5, "joint " + std::to_string(id) + " reads " + std::to_string(at_y) +
                                                      ", not " + std::to_string(at_x));
            if (x.at("kind") == "drum")
                require(at_x == at_y, "the drum's rope has not as much out as it had");
            x["held"].erase("at");
            y["held"].erase("at");
        }
        require(x == y, "joint " + std::to_string(id) + " differs: " + x.dump().substr(0, 300) + " against " +
                            y.dump().substr(0, 300));
    }
}

// The heat of each thing named, as the network held it: its matter and heat
// zone by zone, what it started with and the hottest it has been, and what it
// did over its last step. Two of a lump's fields are the network's bookkeeping
// about the world around it rather than what it holds, and are worked out
// again as it is carried: what it was last told it weighs (its rigid body is
// made again from its cells) and how much of its surface is open to the air,
// which every refresh of the heat paths sums again from its contacts --
// measured, it came back differing in its seventeenth digit (0.0012224296546694768
// against ...763 for a piece of the pane).
std::size_t requireHeatAsSaved(const nlohmann::json &saved, const nlohmann::json &now,
                               const std::set<std::string> &bodies) {
    std::size_t same = 0;
    require(saved.contains("heat"), "the saved world carries no heat");
    for (const nlohmann::json &lump : saved.at("heat").at("lumps")) {
        const std::string body = lump.at("body").get<std::string>();
        if (bodies.count(body) == 0) continue;
        const nlohmann::json *back = nullptr;
        for (const nlohmann::json &l : now.at("heat").at("lumps"))
            if (l.at("body") == body) back = &l;
        require(back != nullptr, "the " + body + "'s heat did not come back");
        nlohmann::json x = lump, y = *back;
        for (const char *bookkeeping : {"mirrored_mass_kg", "exposed_area_m2"}) {
            x.erase(bookkeeping);
            y.erase(bookkeeping);
        }
        std::string differ;
        for (auto it = x.begin(); it != x.end(); ++it)
            if (!y.contains(it.key()) || y.at(it.key()) != it.value())
                differ += " " + it.key() + " (" + it.value().dump().substr(0, 60) + " saved, " +
                          (y.contains(it.key()) ? y.at(it.key()).dump().substr(0, 60) : std::string("none")) + ")";
        require(differ.empty(), "the " + body + "'s heat differs:" + differ);
        ++same;
    }
    return same;
}

bool says(const LiveRestore &restored, const std::string &part) {
    return std::any_of(restored.not_carried.begin(), restored.not_carried.end(),
                       [&](const std::string &line) { return line.find(part) != std::string::npos; });
}

void sayWhatCameBack(const LiveRestore &r) {
    std::cout << "    restored: " << r.tier << ", " << r.bodies << " bodies as saved; " << r.carried.fresh
              << " as the scene has them (" << r.carried.placed << " put back where left), " << r.carried.gone
              << " gone; " << r.carried.joints << " joints, " << r.carried.energy_stores << " store, "
              << r.carried.motors << " motor, " << r.carried.heat << " bodies' heat"
              << (r.carried.hand ? ", the hand's hold" : "") << "\n";
    for (const std::string &line : r.not_carried) std::cout << "      not carried: " << line << "\n";
}

// The hoist winds on from where it was: the drum takes on its radius times its
// turn, and the crate rises by what it takes on.
void theHoistWindsOn(LiveWorld &world, unsigned motor, unsigned rope) {
    const double out_before = jointOf(world, rope).at;
    const double y_before = named(world.poses(), "crate").position_m.y;
    const double turned_before = motorOf(world, motor).turned_rad;
    require(world.driveMotor(motor, 1.0), "the motor would not take a command");
    stepAnswering(world, 288);
    const double turned = motorOf(world, motor).turned_rad - turned_before;
    const double taken = out_before - jointOf(world, rope).at;
    const double rise = named(world.poses(), "crate").position_m.y - y_before;
    std::cout << "    wound on for 1.2 s: the drum turned " << turned / (2.0 * kPi) << " times and took on " << taken
              << " m of rope (r x turn " << kDrumRadiusM * turned << " m); the crate rose " << rise << " m\n";
    require(turned > kPi, "the drum did not turn half a turn");
    require(std::abs(taken - kDrumRadiusM * turned) < 0.002 * kDrumRadiusM * turned,
            "the rope taken on is not the drum's radius times its turn");
    require(std::abs(rise - taken) < 0.01 * taken, "the crate did not rise by the rope taken on");
    world.driveMotor(motor, 0.0, true);
}

// The gate still swings on its pin: hauled round 40 degrees from where it is --
// back towards shut when it is open, open when it is shut -- it turns, and its
// pin stays where it is.
void theGateSwings(LiveWorld &world, unsigned pin) {
    const LiveJoint before = jointOf(world, pin);
    require(world.grab("door"), "the door could not be taken hold of");
    const double open = 50.0 * kPi / 180.0;
    const double to = std::abs(before.at) > 0.5 * open ? 10.0 * kPi / 180.0 : open;
    world.moveHeld({kDoorPin.x + 0.26 * std::cos(to), 0.45, kDoorPin.z - 0.26 * std::sin(to)});
    stepAnswering(world, 240);
    world.release();
    const LiveJoint after = jointOf(world, pin);
    std::cout << "    the door, hauled round: its pin read " << before.at * 180.0 / kPi << " degrees and reads "
              << after.at * 180.0 / kPi << "\n";
    require(std::abs(after.at - before.at) > 20.0 * kPi / 180.0, "the door did not swing");
    require(length(after.point_world_m - before.point_world_m) < 0.01, "the door came off its pin");
}

// ---- the checks ----------------------------------------------------------------

// A thing added -- first in the scene, so that every other thing's cells are
// numbered after its own -- and everything else is as it stood.
void aThingAddedLeavesTheRestAsItStood() {
    const Played &p = played();
    const auto back = LiveWorld::open(carryRoom({.new_crate = true}), p.saved, LiveWorld::carryAll(p.saved));
    const LiveRestore &r = back->restored();
    sayWhatCameBack(r);
    const std::vector<std::string> names = namesIn(p.doc);
    require(r.tier == "carried", "the room was not carried: " + r.tier + ", " + r.why);
    require(r.bodies == names.size(), "only " + std::to_string(r.bodies) + " of " + std::to_string(names.size()) +
                                          " saved bodies came back as they were");
    require(r.carried.fresh == 1 && r.carried.gone == 0 && r.carried.placed == 0,
            "the new crate is not the only thing as the scene has it");
    require(r.carried.joints == 3 && r.carried.energy_stores == 1 && r.carried.motors == 1 && r.carried.hand,
            "the pins, the battery, the motor or the hand did not come back");
    require(r.not_carried.empty(),
            "something was said not to be carried: " + (r.not_carried.empty() ? std::string{} : r.not_carried.front()));
    std::string why;
    const nlohmann::json now = nlohmann::json::parse(back->snapshot(why));
    requireCarriedExactly(p.doc, now, names, wokenBy(r));
    requireJointsAsSaved(p.doc, now, {p.door_pin, p.hoist_pin, p.rope});
    require(p.doc.at("energy_stores") == now.at("energy_stores"), "the battery is not as it was");
    require(p.doc.at("motors") == now.at("motors"), "the motor is not as it was");
    require(p.doc.at("hand") == now.at("hand"), "the hand is not as it was: " + now.at("hand").dump());
    require(back->hand().holding == "mallet" && back->hand().mode == "grip", "the hand does not hold the mallet");
    const std::set<std::string> all(names.begin(), names.end());
    const std::size_t lumps = requireHeatAsSaved(p.doc, now, all);
    require(r.carried.heat == lumps && lumps >= 2, "the heat of " + std::to_string(r.carried.heat) + " bodies came "
                                                   "back, of " + std::to_string(lumps));
    const auto temperatureOf = [](const LiveWorld &world, const std::string &body) {
        for (const thermo::BodyHeat &heat : world.thermo()->bodies())
            if (heat.body == body) return heat.temperature_k;
        throw std::runtime_error("the network does not hold the " + body);
    };
    std::cout << "    the hot block is at " << temperatureOf(*back, "hot block") << " K and the warm block at "
              << temperatureOf(*back, "warm block") << " K, as saved\n";
    for (const char *body : {"hot block", "warm block"})
        require(temperatureOf(*back, body) == temperatureOf(*p.world, body),
                std::string("the ") + body + " is not as hot as it was saved");
    require(temperatureOf(*back, "warm block") > 293.15 + 1.0, "the warm block's heat is gone");
    const LiveBodyPose crate = named(back->poses(), "new crate");
    require(length(crate.position_m - Vec3{-3.0, 0.1, 3.0}) < 1e-6, "the new crate is not where the scene has it");
    require(!crate.fragment && crate.dent_m == 0.0, "the new crate is not whole");

    // And it goes on from there.
    theHoistWindsOn(*back, p.motor, p.rope);
    theGateSwings(*back, p.door_pin);
    const thermo::Ledger ledger = back->thermo()->ledger();
    std::cout << "    after 1.6 s the heat ledger closes to " << ledger.residualJ() << " J of " << ledger.storedJ()
              << " J stored\n";
    require(std::abs(ledger.residualJ()) < 1e-9 * std::abs(ledger.storedJ()), "the heat ledger does not close");
}

// A thing taken away -- the anvil, first in the scene, with the dented ball
// resting on it -- and everything else is as it stood; the ball, woken, falls.
void aThingTakenAwayLeavesTheRestAsItStood() {
    const Played &p = played();
    const auto back = LiveWorld::open(carryRoom({.no_anvil = true}), p.saved, LiveWorld::carryAll(p.saved));
    const LiveRestore &r = back->restored();
    sayWhatCameBack(r);
    std::vector<std::string> names = namesIn(p.doc);
    std::erase(names, std::string("anvil"));
    require(r.tier == "carried", "the room was not carried: " + r.tier + ", " + r.why);
    require(r.bodies == names.size() && r.carried.gone == 1 && r.carried.fresh == 0,
            "not everything but the anvil came back as it was");
    require(says(r, "the anvil: the room no longer has it"), "it was not said that the anvil is gone");
    std::string why;
    const nlohmann::json now = nlohmann::json::parse(back->snapshot(why));
    require(wokenBy(r).count("iron ball") != 0, "the iron ball, resting on the anvil, was not said to be woken");
    requireCarriedExactly(p.doc, now, names, wokenBy(r));
    requireJointsAsSaved(p.doc, now, {p.door_pin, p.hoist_pin, p.rope});
    require(bodyIn(now, "iron ball")->at("awake").get<bool>(), "the iron ball was left asleep with nothing under it");
    const LiveBodyPose ball = named(back->poses(), "iron ball");
    stepAnswering(*back, 120);
    const LiveBodyPose fell = named(back->poses(), "iron ball");
    std::cout << "    with the anvil gone the iron ball fell " << ball.position_m.y - fell.position_m.y
              << " m in 0.5 s, keeping its " << 1000.0 * fell.dent_m << " mm dent\n";
    require(ball.position_m.y - fell.position_m.y > 0.05, "the iron ball did not fall where the anvil was");
    require(fell.dent_m == bodyIn(p.doc, "iron ball")->at("dent_m").get<double>(), "the iron ball lost its dent");
}

// A thing moved in the scene -- the rolling ball, which the hand had carried
// somewhere else -- is where the scene has it now; everything else as it stood.
void aThingMovedInTheSceneIsWhereTheSceneHasIt() {
    const Played &p = played();
    const Vec3 moved{0.6, 0.04, -2.4};
    const auto back = LiveWorld::open(carryRoom({.rolling_ball_at = moved}), p.saved, LiveWorld::carryAll(p.saved));
    const LiveRestore &r = back->restored();
    sayWhatCameBack(r);
    std::vector<std::string> names = namesIn(p.doc);
    std::erase(names, std::string("rolling ball"));
    require(r.tier == "carried" && r.bodies == names.size() && r.carried.fresh == 1 && r.carried.gone == 0,
            "not everything but the rolling ball came back as it was");
    require(says(r, "the rolling ball: the room changed it"), "it was not said that the rolling ball was changed");
    std::string why;
    const nlohmann::json now = nlohmann::json::parse(back->snapshot(why));
    requireCarriedExactly(p.doc, now, names, wokenBy(r));
    const LiveBodyPose ball = named(back->poses(), "rolling ball");
    require(length(ball.position_m - moved) < 1e-6, "the rolling ball is not where the scene has it");
    theHoistWindsOn(*back, p.motor, p.rope);
}

// A pin the room no longer declares the same way: the door on it is as the
// scene has it, shut, its post as it stood, and a pin hung anew takes the next
// number after everything saved.
void aPinTheRoomChangedPutsWhatItHoldsBackAsTheRoomHasIt() {
    const Played &p = played();
    LiveCarry carry = LiveWorld::carryAll(p.saved);
    carry.joints.erase(p.door_pin);
    const auto back = LiveWorld::open(carryRoom(), p.saved, carry);
    const LiveRestore &r = back->restored();
    sayWhatCameBack(r);
    std::vector<std::string> names = namesIn(p.doc);
    std::erase(names, std::string("door"));
    require(r.tier == "carried" && r.bodies == names.size() && r.carried.fresh == 1 && r.carried.joints == 2,
            "not everything but the door and its pin came back as it was");
    require(says(r, "the door: it was on a pin the room changed or took away"), "it was not said why the door is not");
    std::string why;
    const nlohmann::json now = nlohmann::json::parse(back->snapshot(why));
    requireCarriedExactly(p.doc, now, names, wokenBy(r));
    const LiveBodyPose door = named(back->poses(), "door");
    require(length(door.position_m - Vec3{0.30, 0.45, 1.2}) < 1e-6 && std::abs(door.orientation_wxyz[0] - 1.0) < 1e-9,
            "the door is not shut where the scene has it");
    const unsigned again = back->hinge("post", "door", kDoorPin, {0.0, 1.0, 0.0}, -90.0, 90.0, 2.0);
    require(again == p.doc.at("next").at("joint").get<unsigned>(),
            "the pin hung anew took number " + std::to_string(again) + ", not the next after everything saved");
    theGateSwings(*back, again);
}

// Cells that are not the saved ones -- as a build that lays them out another
// way would make them -- cannot be carried exactly: that thing alone is put
// back where it was left, whole, as a world that did not fit puts it back.
void cellsThatAreNotTheSavedOnesFallBackForThatThingAlone() {
    const Played &p = played();
    nlohmann::json doc = p.doc;
    bool marred = false;
    for (nlohmann::json &part : doc["parts"])
        if (part.at("bodies").at(0) == "rolling ball") {
            part["cells"] = "0000000000000000";
            marred = true;
        }
    require(marred, "the saved world has no part for the rolling ball");
    const nlohmann::json &left = *bodyIn(p.doc, "rolling ball");
    require(left.at("dent_m").get<double>() == 0.0 && !left.at("fragment").get<bool>(),
            "the rolling ball is not whole, so it is not one a world that did not fit puts back");
    const auto back = LiveWorld::open(carryRoom(), doc.dump(), LiveWorld::carryAll(p.saved));
    const LiveRestore &r = back->restored();
    sayWhatCameBack(r);
    std::vector<std::string> names = namesIn(p.doc);
    std::erase(names, std::string("rolling ball"));
    require(r.tier == "carried" && r.bodies == names.size() && r.carried.placed == 1 && r.carried.fresh == 1,
            "the rolling ball was not put back where it was left, alone");
    require(says(r, "the rolling ball: its cells are not the ones it was saved with") &&
                says(r, "so it was put back where it was left, whole"),
            "it was not said why the rolling ball could not be carried");
    std::string why;
    const nlohmann::json now = nlohmann::json::parse(back->snapshot(why));
    requireCarriedExactly(p.doc, now, names, wokenBy(r));
    require(bodyIn(now, "rolling ball")->at("pose") == left.at("pose"), "the rolling ball is not where it was left");
}

// Heat the room now declares another way: the hot block is where it stood, and
// as hot as the room says -- not as it was saved.
void heatTheRoomDeclaresAnewIsAsDeclared() {
    const Played &p = played();
    const auto back = LiveWorld::open(carryRoom({.hot_block_k = 400.0}), p.saved, LiveWorld::carryAll(p.saved));
    const LiveRestore &r = back->restored();
    sayWhatCameBack(r);
    const std::vector<std::string> names = namesIn(p.doc);
    require(r.tier == "carried" && r.bodies == names.size(), "not everything came back as it was");
    require(says(r, "the hot block's heat: the room declares it anew"), "it was not said that the heat is declared anew");
    std::string why;
    const nlohmann::json now = nlohmann::json::parse(back->snapshot(why));
    requireCarriedExactly(p.doc, now, names, wokenBy(r));
    double hot = 0.0;
    for (const thermo::BodyHeat &heat : back->thermo()->bodies())
        if (heat.body == "hot block") hot = heat.temperature_k;
    std::cout << "    the hot block is at " << hot << " K, as the room declares it now\n";
    require(std::abs(hot - 400.0) < 1e-6, "the hot block is not as hot as the room declares it");
    require(requireHeatAsSaved(p.doc, now, {"warm block"}) == 1, "the warm block's heat did not come back");
}

// A cut block comes back cut in a scene with a new thing first in it, so every
// cell and bond of the block is numbered anew: the bonds its blade severed, its
// kerf, and the blade's edge, found again in its frame. (live_world_tests'
// aWorldIsNotSavedWhileSomethingIsUnderWay, with nothing but the two bodies
// and no gravity.)
void aCutComesBackCutUnderItsNewNumbers() {
    TileImpactRequest r;
    r.cell_size_m = 0.01;
    r.backend = BackendKind::CpuParallel;
    r.gravity_m_s2 = {0.0, 0.0, 0.0};
    SceneBody block;
    block.name = "block";
    block.shape = BodyShape::Box;
    block.material = MaterialPreset::Oak;
    block.dimensions_m = {0.1, 0.1, 0.1};
    block.center_m = {0.0, 0.5, 0.0};
    SceneBody blade = block;
    blade.name = "blade";
    blade.material = MaterialPreset::Iron;
    blade.dimensions_m = {0.2, 0.01, 0.03};
    blade.center_m = {0.0, 0.5, 0.066};
    blade.velocity_m_s = {0.0, 0.0, -6.0};
    r.bodies = {block, blade};
    const auto cut = LiveWorld::open(r);
    require(cut->blade("blade", {-0.09, 0.5, 0.051}, {0.09, 0.5, 0.051}, {0.0, 0.0, -1.0}, 0.01, 0.00005, 30.0,
                       {0.09, 0.5, 0.066}) != 0,
            "the blade would not take an edge: " + cut->bladeRefusal());
    for (int i = 0; i < 120; ++i) {
        cut->step(1.0 / 240.0);
        if (cut->steppedBack())
            for (const std::string &name : cut->breakable()) cut->declineBreak(name);
        const std::vector<LiveBodyPose> poses = cut->poses();
        const double closing = named(poses, "block").velocity_m_s.z - named(poses, "blade").velocity_m_s.z;
        if (i > 4 && std::abs(closing) < 0.005) break;
    }
    require(!named(cut->poses(), "block").kerfs.empty(), "the blade made no kerf, so this proves nothing");
    // Drawn clear of the cut, and saved.
    require(cut->grab("blade"), "the blade could not be taken hold of");
    cut->moveHeld(named(cut->poses(), "blade").position_m + Vec3{0.0, 0.0, 0.2});
    for (int i = 0; i < 10; ++i) cut->step(1.0 / 240.0);
    cut->release();
    for (int i = 0; i < 10; ++i) cut->step(1.0 / 240.0);
    std::string why;
    const std::string saved = cut->snapshot(why);
    require(!saved.empty(), "the world could not be saved with the blade drawn clear: " + why);
    const nlohmann::json doc = nlohmann::json::parse(saved);
    require(!numbersIn(doc, "dead_bonds_b64").empty(), "the cut severed no bond, so this proves nothing");

    // A marker first in the scene: every cell and bond of both is numbered anew.
    TileImpactRequest changed = r;
    SceneBody marker = block;
    marker.name = "marker";
    marker.material = MaterialPreset::Iron;
    marker.dimensions_m = {0.05, 0.05, 0.05};
    marker.center_m = {0.5, 0.5, 0.5};
    changed.bodies.insert(changed.bodies.begin(), marker);
    const auto back = LiveWorld::open(changed, saved, LiveWorld::carryAll(saved));
    const LiveRestore &restored = back->restored();
    sayWhatCameBack(restored);
    require(restored.tier == "carried" && restored.bodies == 2 && restored.carried.fresh == 1 &&
                restored.carried.blades == 1 && restored.not_carried.empty(),
            "the cut block and the blade did not both come back as they were, with the edge");
    const nlohmann::json now = nlohmann::json::parse(back->snapshot(why));
    requireCarriedExactly(doc, now, namesIn(doc));
    // The edge, where it was on the blade, and the cells it is found by moved
    // with the blade's.
    nlohmann::json edge_then = doc.at("blades").at(0), edge_now = now.at("blades").at(0);
    const std::vector<std::uint32_t> frame_then = numbersIn(edge_then, "frame_nodes_b64");
    const std::vector<std::uint32_t> frame_now = numbersIn(edge_now, "frame_nodes_b64");
    const nlohmann::json *part = partHolding(doc, "nodes", frame_then.at(0));
    require(part != nullptr, "the edge's cells are in no saved part");
    const std::int64_t moved = shiftOf(*part, now).node;
    require(frame_then.size() == frame_now.size(), "the edge is found by a different number of cells");
    for (std::size_t k = 0; k < frame_then.size(); ++k)
        require(static_cast<std::int64_t>(frame_now[k]) == static_cast<std::int64_t>(frame_then[k]) + moved,
                "the edge's cell " + std::to_string(k) + " did not move with the blade's");
    edge_then.erase("frame_nodes_b64");
    edge_now.erase("frame_nodes_b64");
    require(edge_then == edge_now, "the edge differs: " + edge_now.dump().substr(0, 300));
    // And the kerf still crosses what it crossed: the block reports the same
    // cut, and with the blade's help cuts on from there.
    const LiveBodyPose was = named(cut->poses(true), "block"), is = named(back->poses(true), "block");
    require(was.kerfs.size() == is.kerfs.size() && was.kerfs.front().strips.size() == is.kerfs.front().strips.size(),
            "the block's cut differs");
    std::cout << "    the cut block came back with its " << numbersIn(doc, "dead_bonds_b64").size()
              << " severed bonds, its kerf and the blade's edge, every cell and bond moved by " << moved << "\n";
}

// The same scene, opened as a restart opens it, is still whole: carrying is
// only for a scene that has changed.
void theSameSceneStillComesBackWhole() {
    const Played &p = played();
    const auto back = LiveWorld::open(carryRoom(), p.saved);
    require(back->restored().tier == "whole", "the same scene did not come back whole: " + back->restored().why);
    const auto carried = LiveWorld::open(carryRoom(), p.saved, LiveWorld::carryAll(p.saved));
    std::string why;
    const nlohmann::json whole = nlohmann::json::parse(back->snapshot(why));
    const nlohmann::json as_carried = nlohmann::json::parse(carried->snapshot(why));
    requireCarriedExactly(whole, as_carried, namesIn(whole));
    std::cout << "    the same scene comes back whole, and carried it is the same world\n";
    theHoistWindsOn(*back, p.motor, p.rope);
}


// No mechanical movement in this comparison: any drift is lost thermal state,
// not the documented loss of the rigid solver's contact warm start.
void completeThermalStateSurvivesRestart() {
    TileImpactRequest r;
    r.cell_size_m = 0.04;
    for (const auto material : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        SceneBody b;
        b.name = materialPresetName(material);
        b.shape = BodyShape::Box; b.material = material; b.anchored = true;
        b.dimensions_m = {0.08, 0.08, 0.08};
        b.center_m = {static_cast<double>(r.bodies.size()), 1.0, 0.0};
        r.bodies.push_back(b);
    }
    r.thermo_scene_json = R"({"bodies":[
        {"name":"glass","temperature_k":500},{"name":"oak","temperature_k":650},
        {"name":"iron","temperature_k":500}],
        "thermo":{"gas_regions":[{"name":"tank","contents":{"argon":1},"volume_m3":0.1,
        "temperature_k":400,"pressure_pa":150000,"vent_area_m2":0.00001}],
        "heaters":[{"target":"tank","power_w":100,"seconds":0.8}]}})";
    auto world = LiveWorld::open(r);
    require(world->heat("iron", 200, 0.6) != 0, "dynamic heater was refused");
    stepAnswering(*world, 48);
    std::string why;
    const auto saved = world->snapshot(why);
    require(!saved.empty(), "thermal snapshot was refused: " + why);
    auto back = LiveWorld::open(r, saved);
    require(back->restored().tier == "whole", "thermal restart is not whole");
    const auto before = nlohmann::json::parse(saved);
    const auto after = nlohmann::json::parse(back->snapshot(why));
    require(before.at("heat") == after.at("heat"), "thermal state changed on restart");
    auto edited = r;
    SceneBody extra = r.bodies.front();
    extra.name = "new distant part"; extra.center_m = {100, 1, 0};
    edited.bodies.push_back(extra);
    auto carried = LiveWorld::open(edited, saved, LiveWorld::carryAll(saved));
    require(carried->restored().tier == "carried", "active thermal network did not carry");
    require(nlohmann::json::parse(carried->snapshot(why)).at("heat") == before.at("heat"),
            "active gas/heaters changed when a distant part was added");
    auto incompatible = edited;
    auto declarations = nlohmann::json::parse(incompatible.thermo_scene_json);
    declarations["thermo"]["gas_regions"][0]["pressure_pa"] = 180000;
    incompatible.thermo_scene_json = declarations.dump();
    auto changed = LiveWorld::open(incompatible, saved, LiveWorld::carryAll(saved));
    require(nlohmann::json::parse(changed->snapshot(why)).at("heat").at("network") != before.at("heat").at("network"),
            "changed gas declaration incorrectly reused old network");

    require(world->thermo()->ledger().heater_in_j > 0, "heaters did no work before restart");
    stepAnswering(*world, 240);
    stepAnswering(*back, 240);
    const auto continued = nlohmann::json::parse(world->snapshot(why));
    const auto restarted = nlohmann::json::parse(back->snapshot(why));
    require(continued.at("heat") == restarted.at("heat"), "thermal continuation differs after restart");
    stepAnswering(*carried, 240);
    require(nlohmann::json::parse(carried->snapshot(why)).at("heat") == continued.at("heat"),
            "thermal continuation differs after adding an unrelated part");

    const auto &ledger = back->thermo()->ledger();
    require(std::abs(ledger.residualJ()) < 1e-7, "thermal energy ledger failed after restart");
    require(std::abs(ledger.massResidualKg()) < 1e-12, "thermal mass ledger failed after restart");
    require(back->thermo()->state().time_s > 1.1, "thermal clock restarted");
    auto malformed = before;
    malformed["heat"]["network"]["contacts"].push_back({{"a", 999999}, {"b", 0},
        {"area_m2", 1}, {"conductance_w_k", 1}});
    const auto refused = LiveWorld::open(r, malformed.dump());
    require(refused->restored().tier != "whole", "invalid thermal indices were accepted");
    auto legacy = before;
    legacy["heat"].erase("network");
    const auto old = LiveWorld::open(r, legacy.dump());
    require(old->restored().tier == "whole", "legacy snapshot is no longer readable");
    const auto migrated = nlohmann::json::parse(old->snapshot(why));
    for (const auto &lump : legacy.at("heat").at("lumps")) {
        const auto &lumps = migrated.at("heat").at("lumps");
        auto found = std::find_if(lumps.begin(), lumps.end(), [&](const auto &l) { return l.at("body") == lump.at("body"); });
        require(found != lumps.end(), "legacy heat body lost");
        for (const auto *key : {"surface", "core", "initial_kg_b64", "peak_surface_k", "peak_core_k", "parked"})
            require(found->at(key) == lump.at(key), std::string("legacy thermal history changed: ") + key);
    }
    require(old->thermo()->state().heaters.empty(), "legacy heater work would replay without a saved schedule");
    require(std::abs(old->thermo()->ledger().residualJ()) < 1e-7, "legacy import ledger boundary does not close");
    stepAnswering(*old, 24);
    require(std::abs(old->thermo()->ledger().residualJ()) < 1e-7, "legacy migrated thermal continuation failed");

    std::cout << "    glass/oak/iron, finite vented gas, timed/dynamic heaters and ledger resume exactly\n";
}


void pressureWorkSurvivesRestart() {
    TileImpactRequest r;
    r.cell_size_m = 0.04;
    SceneBody base;
    base.name = "base"; base.shape = BodyShape::Box; base.material = MaterialPreset::Iron;
    base.dimensions_m = {0.16, 0.04, 0.16}; base.center_m = {0, 0.02, 0}; base.anchored = true;
    SceneBody piston = base;
    piston.name = "piston"; piston.center_m = {0, 0.5, 0}; piston.anchored = false;
    r.bodies = {base, piston};
    r.thermo_scene_json = R"({"thermo":{"gas_regions":[{"name":"gas","contents":{"argon":1},
        "piston":"piston","height_m":0.4,"balance":true}],
        "heaters":[{"target":"gas","power_w":100,"seconds":1}]}})";
    auto world = LiveWorld::open(r);
    require(world->slide("base", "piston", {0, 0.5, 0}, {0, 1, 0}, -0.2, 0.6, 0) > 0, "piston slide failed");
    stepAnswering(*world, 120);
    std::string why;
    const auto saved = world->snapshot(why);
    auto back = LiveWorld::open(r, saved);
    require(back->restored().tier == "whole", "heated piston did not restore whole");
    const auto before = nlohmann::json::parse(saved);
    const auto after = nlohmann::json::parse(back->snapshot(why));
    require(before.at("heat") == after.at("heat"), "piston pressure/work history changed on restart");
    auto edited = r;
    SceneBody extra = base; extra.name = "new support"; extra.center_m = {100, 0.02, 0};
    edited.bodies.push_back(extra);
    auto carried = LiveWorld::open(edited, saved, LiveWorld::carryAll(saved));
    require(carried->restored().tier == "carried", "piston network did not carry");
    require(nlohmann::json::parse(carried->snapshot(why)).at("heat") == before.at("heat"),
            "piston pressure/work changed when adding a part");

    require(back->thermo()->ledger().work_to_bodies_j > 0, "gas did no mechanical work");
    stepAnswering(*back, 120);
    const auto &ledger = back->thermo()->ledger();
    require(std::abs(ledger.residualJ()) < 1e-7, "restarted piston thermal ledger does not close");
    require(ledger.work_to_bodies_j > 0, "restarted piston lost its work account");
    std::cout << "    pressure, piston boundary and work ledger survive and continue\n";
}

} // namespace

int main() {
    // Said as it happens, so a check that brings the process down leaves what
    // it had got to.
    std::cout << std::unitbuf;
    // Every check runs, and every failure is said: a main that stops at the
    // first failure hides what the rest would have found.
    const std::vector<std::pair<const char *, void (*)()>> checks{
        {"a thing added leaves the rest of the room as it stood, and it goes on from there",
         aThingAddedLeavesTheRestAsItStood},
        {"a thing taken away leaves the rest as it stood, and what rested on it falls",
         aThingTakenAwayLeavesTheRestAsItStood},
        {"a thing moved in the scene is where the scene has it, and the rest as it stood",
         aThingMovedInTheSceneIsWhereTheSceneHasIt},
        {"a pin the room changed puts what it holds back as the room has it, and says so",
         aPinTheRoomChangedPutsWhatItHoldsBackAsTheRoomHasIt},
        {"cells that are not the saved ones fall back for that thing alone, and say so",
         cellsThatAreNotTheSavedOnesFallBackForThatThingAlone},
        {"heat the room declares anew is as declared, and the rest as it stood", heatTheRoomDeclaresAnewIsAsDeclared},
        {"a cut comes back cut, its severed bonds and its edge under their new numbers",
         aCutComesBackCutUnderItsNewNumbers},
        {"the same scene still comes back whole", theSameSceneStillComesBackWhole},
        {"complete thermal state survives restart", completeThermalStateSurvivesRestart},
        {"pressure work survives restart", pressureWorkSurvivesRestart},
    };
    int failed = 0;
    for (const auto &[what, check] : checks) {
        try {
            std::cout << "  " << what << "\n";
            check();
            std::cout << "[PASS] " << what << "\n";
        } catch (const std::exception &error) {
            ++failed;
            std::cout << "[FAIL] " << what << ": " << error.what() << "\n";
        }
    }
    if (failed != 0) std::cerr << "room carry tests: " << failed << " of " << checks.size() << " failed\n";
    return failed == 0 ? 0 : 1;
}
