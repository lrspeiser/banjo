// A live scene, driven a line at a time.
//
// The playground plays recordings: it asks the engine for a run and gets back a
// film. A live world has to be talked to instead, so this holds one open and
// speaks JSON over stdin and stdout, one object per line -- which is the same
// shape everything else in the playground already uses to reach the engine, and
// needs no new transport on either side.
//
//   in   {"op":"step","dt":0.0166,"n":2}
//        {"op":"grab","name":"ball"}  {"op":"move","to":[0,1.2,0]}  {"op":"release"}
//        {"op":"step","n":4,"hand":[0,1.2,0]}   move the hand, then step
//        {"op":"fracture","name":"pane"}   {"op":"poses"}   {"op":"quit"}
//        {"op":"fracture","name":"pane","wait":false}
//        {"op":"step","dt":0.008,"n":4,"moved":true}   only what changed
//        {"op":"collect","at":[0,1.6,0],"radius_m":1.2}   sweep up the pieces
//        {"op":"foresee","horizon_s":2.5}   how far ahead to start runs (0 = off)
//        {"op":"pick","from":[0,6,0],"dir":[0,-1,0],"max_m":1000}
//        {"op":"hinge","a":"post","b":"gate","at":[0,1.2,0],"axis":[0,1,0],
//         "lower_deg":0,"upper_deg":110,"friction_n_m":2}   hang it on a pin
//        {"op":"joints"}                     every pin, and where each has got to
//        {"op":"slide","a":"jamb","b":"grate","at":[0,0.9,0],"axis":[0,1,0],
//         "lower_m":0,"upper_m":2,"friction_n":40000}      put it in a groove
//        {"op":"tie","a":"beam","b":"weight","at_a":[0,3.9,0],"at_b":[0,3,0],
//         "length_m":0,"breaks_at_n":2000}     a rope: it pulls, it cannot push
//        {"op":"reeve","a":"grate","b":"counterweight","at_a":[0,1,0.15],
//         "at_b":[2,3.3,0],"over_a":[0,3.9,0],"over_b":[2,3.9,0],"ratio":1}
//                                            a hoist: pull one end, the other rises
//        {"op":"fix","a":"jamb","b":"bar","at":[0,1.4,0.2],"axis":[1,0,0],
//         "holds_tension_n":0,"holds_shear_n":0}   a peg, a bracket, a latch
//        {"op":"fix",...,"member":"bar"}     ... MADE of the bar: heat changes what
//                                            it can take (fix, tie and spring all
//                                            take "member"; docs/thermal-mechanics.md)
//        {"op":"member","joint":1,"member":"bar"}   the same, afterwards ("" undoes it)
//        {"op":"mechanics","laws":false}    what heat has done to what things can
//                                            carry; replies that describe the world
//                                            carry a trimmed "mechanics" block too
//        {"op":"spring","a":"riser","b":"tip","at_a":[0,1,0],"at_b":[0,1.4,0],
//         "rest_m":0,"stiffness_n_m":4000,"damping_n_s_m":5}   a bow limb
//        {"op":"unhinge","joint":1}          take the pin out; it falls
//        {"op":"joint_friction","joint":1,"friction_n_m":40}   stiffen it
//        {"op":"heat","target":"log","power_w":10000,"seconds":60}   kindling,
//                                            a torch, a stove: external work, counted
//        {"op":"declare","json":{"gas_regions":[...],"heaters":[...]}}
//        {"op":"vent","region":"cylinder gas","open":true}
//        {"op":"thermo","model":false}      heat, chemistry, gas and the ledger
//        (a ground block carries "beyond": the river network beyond the
//         edges, for a picture of it -- "connections" {name, edge, from_m,
//         to_m, basin | reach and end}, "basins" and "junctions" {name, at_m,
//         side_m, bed_m}, "reaches" {name, width_m, cells, length_m, points_m
//         at its cells' boundaries, bed_m a cell}; the water block, "basins"
//         and "junctions" {name, level_m, volume_m3, fed_m3_s, out_m3_s,
//         across_m3_s, from_reaches_m3_s}, "reaches" {name, level_m a cell,
//         in_m3_s, middle_m3_s, out_m3_s, froude} and "all_unaccounted_m3"
//         -- docs/watershed.md)
//        {"op":"dig","from":[x,z],"to":[x,z],"width_m":1,"depth_m":0.5}
//                                            a trench (or a pit, from == to);
//                                            "carried" in the reply is the sand
//                                            and soil out of the ground and not
//                                            put back -- also in "terrain"
//        {"op":"deposit","at":[x,z],"radius_m":1,"sand_m3":0.5,"soil_m3":0,
//         "from_carried":true}               a heap; from_carried refuses one
//                                            bigger than what is carried
//        {"op":"cut_block","at":[x,z],"cells":[4,4],"height_m":0.4}  a block of rock
//        {"op":"discharge","river":"the river","discharge_m3_s":0.5}
//        {"op":"survey","at":[x,z]}          ground and water at a point
//        {"op":"materials"}                  friction and rolling resistance of each
//                                            material and surface, and their sources
//        {"op":"rolling"}                    what rolling resistance is doing: each
//                                            ball's contacts, and the energy it took
//        {"op":"environment","full":false}   the ground, the water, their ledgers
//        {"op":"environment_state"}          the water, for carrying into a reopen
//        {"op":"terrain"}                    the whole ground again, for drawing
//        {"op":"place_check","name":"stool","on":[x,y,z],"yaw_deg":30,"onto":"table"}
//                                            where it would go set down square to the
//                                            ground at a point on a surface, and whether
//                                            it fits (LiveWorld::placement); changes
//                                            nothing. "square":false keeps it upright
//        {"op":"blade","body":"sword","heel":[..],"tip":[..],"facing":[0,0,-1],
//         "thickness_m":0.01,"edge_radius_m":0.0002,"bevel_deg":30,"grip":[..]}
//                                            give a body an edge (docs/cutting-model.md)
//        {"op":"blades"}                     every edge, and what each has cut
//        {"op":"wield","name":"sword","grip":[..]}   a bounded hand on a grip
//        {"op":"step","n":4,"hand":[..],"hand_q":[w,x,y,z]}   where it wants the
//                                            grip, and which way it wants it to face
//        {"op":"hand","strength_n":800,"torque_n_m":60}   how strong the hand is
//        {"op":"hand","mass_kg":2}           the hand and arm a throw also moves
//        {"op":"stroke","path":[[..],[..]],"speed_m_s":20,"accel_m_s2":2000,
//         "lead_m":0.05,"let_go":true,"give_up_s":2}   a motion the hand makes by
//                                            itself, at the step's own rate; the
//                                            reply's "hand" says how it is going
//        {"op":"cancel_stroke"}              the host takes the hand back
//        {"op":"preview_stroke", ...a stroke..., "horizon_s":4}   what it would do
//                                            and where it would fly (a lean reply);
//                                            always a throw, let go of at the end
//        {"op":"preview_flight","from":[..],"velocity":[..],"horizon_s":4,
//         "ignoring":"ball"}                 gravity and the world's shapes (lean)
//        {"op":"cuts"}                       every edge contact since the last reply
//        {"op":"tool_point","body":"pick","tip":[..],"pointing":[0,-1,0],"width_m":0.04,
//         "thickness_m":0.04,"angle_deg":30,"length_m":0.2,"grip":[..]}
//                                            give a body a point that can go into the
//                                            ground (docs/ground-work.md); it then
//                                            collides as its cells
//        {"op":"tool_points"}                every point, and what each is in (lean)
//        {"op":"strike","at":[x,y,z],"shoulder":[x,y,z],"speed_m_s":4,"raise_deg":110}
//                                            swing what is wielded so its point comes
//                                            down on `at`; with "lever":true (and
//                                            "lever_deg"), pry a point that is in the
//                                            ground and draw it out. The reply's "hand"
//                                            says how it goes; a step reply carries
//                                            "ground_work" -- every meeting of a point
//                                            with the ground since the last one that
//                                            said so, open ones every time -- and
//                                            "carried" with it
//        {"op":"ground_work"}                the same list on its own (lean)
//        {"op":"snapshot","spec_digest":".."}   the whole world as it stands, for
//                                            opening again after a restart (lean):
//                                            {"ok":true,"snapshot":{"format":
//                                            "banjo.world.v1",...}}, or {"ok":true,
//                                            "refused":why} while a break, a stroke,
//                                            a cut or a point in the ground is under
//                                            way. `spec_digest` is the host's own
//                                            word for its scene, carried as it is
//   args --scene FILE [--cell M] [--snapshot FILE [--carry FILE]]
//                                            with --snapshot, the scene opened again
//                                            as the saved world left it; the opening
//                                            reply carries "restored": {tier ("whole",
//                                            "poses" or "none"), why, saved_t_s,
//                                            bodies, not_kept, parked}. With --carry
//                                            too, the saved world carried into a
//                                            scene that has changed since, thing by
//                                            thing (LiveWorld::open with a LiveCarry):
//                                            the file is {"joints", "energy_stores",
//                                            "motors", "blades", "tool_points": [the
//                                            saved world's ids of those the host still
//                                            declares the same way], "declared_anew":
//                                            [things it will declare something new
//                                            on]}, and "restored" says tier "carried"
//                                            with "carried" {placed, fresh, gone,
//                                            joints, energy_stores, motors, blades,
//                                            tool_points, heat, hand},
//                                            "not_carried", what did not come back as
//                                            it was saved and why, and "woken", what
//                                            was woken because a saved thing near it
//                                            did not come back as it was
//   out  {"ok":true,"t":0.033,"stepped_back":false,
//         "bodies":[{"name":"ball","shape":"sphere","dimensions_m":[...],
//                    "position_m":[...],"orientation_wxyz":[...],"held":false,
//                    "anchored":false,"color_rgba":"8a8f99ff"}],
//         "impacts":[{"struck":"pane","by":"ball","closing_speed_m_s":13.9,
//                     "threshold_speed_m_s":4.5,"would_break":true}],
//         "breakable":["pane"],
//         "elastics":[{"id":7,"metres":0.093,"force_n":558,"stored_j":25.9}]}
//                                            what each spring holds; a partial
//                                            reply carries only those that changed
//
// Every reply carries the whole world. A scene of a dozen objects is about a
// kilobyte, which is what drawing one authored body per object rather than one
// per cell bought: the same reply for a bowling lane used to be 9,841 poses.
//
// `pick` is the exception. It answers
//
//   {"ok":true,"hit":true,"name":"ball","distance_m":5.36,"point_m":[0,0.64,0]}
//
// and nothing else, because it changes nothing and a pointer asks it on every
// mouse move: carrying 78 poses along with each answer would be most of a
// megabyte a second to say which object is under the cursor. An empty name with
// hit true is the ground -- something stopped the ray, but not one of the
// scene's bodies.

#include "fastlattice/LiveWorld.hpp"

#include <nlohmann/json.hpp>

#include <cmath>
#include <cstdio>
#include <algorithm>
#include <fstream>
#include <array>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

// A number at the precision anyone can use, rather than the precision a double
// happens to have.
//
// Every reply carries every body, and a scene that has shattered holds
// hundreds: a step reply was measured at 259 KB, thirty times a second, which
// the host has to fetch, parse and walk. Most of that was seventeen digits of a
// position meaningful to about five. Ten micrometres is a two-thousandth of the
// smallest cell the engine will build, and nothing anybody can see.
[[nodiscard]] double tidy(double v) {
    return std::isfinite(v) ? std::round(v * 1.0e5) / 1.0e5 : v;
}

// What each body looked like in the last reply that carried it.
//
// A room that has shattered holds hundreds of bodies and almost all of them are
// lying still: of 244 bodies a step, four were moving. Sending the other 240
// again, thirty times a second, was 200 KB a reply -- six megabytes a second
// for the host to fetch, parse and walk, to be told that nothing happened. That
// is a real pause and it is not the physics.
//
// One world to a process, so one cache.
std::unordered_map<std::string, std::string> last_sent;
// The revision each piece's cells last went out at in the room's own stream,
// the `moved` replies. See describe().
std::unordered_map<std::string, unsigned> cells_sent_at;
// And what the pins looked like last time, for the same reason. See where this
// is compared, below: the SET of pins is news, their angles are not.
std::string last_joints;
// What each elastic said it held in the last reply that carried it, by joint
// id (see describe()): unlike a pin's angle, that is news every step a spring
// is being drawn.
std::unordered_map<unsigned, std::string> last_elastics;

nlohmann::json vec(const Vec3 &v) {
    return nlohmann::json::array({tidy(v.x), tidy(v.y), tidy(v.z)});
}

// What the hand is doing and what it has done (LiveHand). On every reply while
// it holds something, and after a stroke has opened it, so a host can show a
// throw's result: the speed it left with and the work the hand put in.
nlohmann::json handJson(const LiveHand &hand) {
    nlohmann::json out{{"holding", hand.holding}, {"mode", hand.mode},
                       {"target_m", vec(hand.target_m)}, {"grip_m", vec(hand.grip_m)},
                       {"grip_velocity_m_s", vec(hand.grip_velocity_m_s)},
                       {"force_n", vec(hand.force_n)}, {"work_j", tidy(hand.work_j)},
                       {"stroking", hand.stroking}, {"stroke_ended", hand.stroke_ended}};
    if (hand.stroking) {
        out["stroke_along_m"] = tidy(hand.stroke_along_m);
        out["stroke_length_m"] = tidy(hand.stroke_length_m);
    }
    if (hand.let_go_at_s >= 0.0)
        out["let_go"] = {{"body", hand.let_go_body},
                         {"velocity_m_s", vec(hand.let_go_velocity_m_s)},
                         {"at_s", tidy(hand.let_go_at_s)},
                         {"work_j", tidy(hand.let_go_work_j)}};
    return out;
}

// What opening from a saved world gave back (LiveRestore), on the opening reply
// of a world started with --snapshot. Unrounded: a thing set aside is brought
// back where it was put away, to the last digit.
nlohmann::json restoredJson(const LiveRestore &restored) {
    nlohmann::json parked = nlohmann::json::array();
    for (const LiveRestore::Parked &p : restored.parked)
        parked.push_back({{"name", p.name},
                          {"at_m", nlohmann::json::array({p.at_m.x, p.at_m.y, p.at_m.z})},
                          {"facing_wxyz", nlohmann::json::array({p.facing.w, p.facing.x, p.facing.y, p.facing.z})}});
    nlohmann::json out{{"tier", restored.tier}, {"why", restored.why}, {"saved_t_s", restored.saved_t_s},
                       {"bodies", restored.bodies}, {"not_kept", restored.not_kept}, {"parked", std::move(parked)}};
    // Carried into a scene that has changed: how much of each came back as it
    // was saved, and thing by thing what did not.
    if (restored.tier == "carried") {
        const LiveRestore::Carried &n = restored.carried;
        out["carried"] = {{"placed", n.placed}, {"fresh", n.fresh}, {"gone", n.gone}, {"joints", n.joints},
                          {"energy_stores", n.energy_stores}, {"motors", n.motors},
                          {"controls", n.controls}, {"programs", n.programs},
                          {"solar_panels", n.solar_panels}, {"blades", n.blades},
                          {"tool_points", n.tool_points}, {"heat", n.heat}, {"hand", n.hand}};
        out["not_carried"] = restored.not_carried;
        out["woken"] = restored.woken;
    }
    return out;
}

// What a host still declares of a saved world, from --carry's file (LiveCarry):
// the saved world's ids for the pins, stores, motors, edges and points it
// declares the same way, and the things it will declare something new on.
LiveCarry carryFrom(const nlohmann::json &doc) {
    LiveCarry carry;
    if (doc.contains("ground")) carry.ground = doc.at("ground").get<bool>();
    const auto ids = [&doc](const char *key, std::set<unsigned> &into) {
        if (!doc.contains(key)) return;
        for (const nlohmann::json &id : doc.at(key)) into.insert(id.get<unsigned>());
    };
    ids("joints", carry.joints);
    ids("energy_stores", carry.energy_stores);
    ids("motors", carry.motors);
    ids("controls", carry.controls);
    ids("programs", carry.programs);
    ids("solar_panels", carry.solar_panels);
    ids("blades", carry.blades);
    ids("tool_points", carry.tool_points);
    if (doc.contains("declared_anew"))
        for (const nlohmann::json &name : doc.at("declared_anew")) carry.declared_anew.insert(name.get<std::string>());
    return carry;
}

nlohmann::json flightJson(const LiveFlight &flight) {
    nlohmann::json points = nlohmann::json::array();
    for (const Vec3 &p : flight.points_m) points.push_back(vec(p));
    return {{"points_m", std::move(points)}, {"hit", flight.hit}, {"hit_name", flight.hit_name},
            {"hit_point_m", vec(flight.hit_point_m)}, {"hit_after_s", tidy(flight.hit_after_s)},
            {"hit_speed_m_s", tidy(flight.hit_speed_m_s)}};
}

// A stroke from a command: {"path":[[x,y,z],...],"speed_m_s":..,"accel_m_s2":..,
// "lead_m":0.05,"let_go":true,"give_up_s":2}. The engine checks the numbers.
LiveStroke readStroke(const nlohmann::json &command) {
    LiveStroke stroke;
    const nlohmann::json &path = command.at("path");
    if (!path.is_array()) throw std::invalid_argument("a stroke's path is a list of points");
    for (const nlohmann::json &p : path) {
        if (!p.is_array() || p.size() != 3)
            throw std::invalid_argument("a stroke's path is points of three numbers");
        stroke.path_m.push_back({p[0].get<double>(), p[1].get<double>(), p[2].get<double>()});
    }
    stroke.speed_m_s = command.value("speed_m_s", 0.0);
    stroke.accel_m_s2 = command.value("accel_m_s2", 0.0);
    stroke.lead_m = command.value("lead_m", 0.05);
    stroke.let_go_at_end = command.value("let_go", false);
    stroke.give_up_s = command.value("give_up_s", 2.0);
    return stroke;
}

// Every pin, as the host sees it. `a` and `b` are the names it holds, which do
// change: a pin whose wood is smashed follows the piece it ends up inside, so a
// gate that was hung on "post" can find itself hung on "post piece 3".
// Stores of energy, the motors that draw on them and the ropes on drums
// (docs/machine-world.md), or null when the world has none of them. Sent with
// every step that has any: a battery's charge, a motor's power and a hoist's
// rope change every step, and a host that polled for them would draw them a
// poll behind, as the bow's meter did at 4 Hz.
// A machine's controller, as a host shows it (docs/machine-world.md,
// "Operating a machine"): what it was told and by whom, what it has its motor
// doing, what the machine is measured doing, and what stands in the way -- with
// the things it is made of, by name (its motor's pin's two, and a hoist's
// load), since a host finds the machine from the thing a person looks at, and
// whether its motor has a brake to stop and hold with.
nlohmann::json controlOf(const LiveControl &c, const std::vector<LiveMotor> &motors,
                         const std::vector<LiveJoint> &joints, const LiveWorld &world) {
    nlohmann::json parts = nlohmann::json::array();
    bool holds = false;
    for (const LiveMotor &m : motors) {
        if (m.id != c.motor) continue;
        holds = m.brake_torque_n_m > 0.0;
        for (const LiveJoint &joint : joints)
            if (joint.id == m.joint) parts = {joint.a, joint.b};
    }
    if (c.rope != 0)
        for (const LiveJoint &joint : joints)
            if (joint.id == c.rope && std::find(parts.begin(), parts.end(), joint.b) == parts.end())
                parts.push_back(joint.b);
    // And whatever else turns on a pin through a part of it that moves with
    // the machine, and on through those: a cart's front wheels turn on the
    // chassis its motor drives from, and a caster's wheel on its fork -- all as
    // much the machine, and E on any of them finds it. Nothing is followed
    // through anchored scenery: two hoists on one post are two machines.
    if (parts.size() >= 2) {
        for (std::size_t k = 0; k < parts.size(); ++k) {
            const std::string from = parts[k];
            if (world.anchored(from)) continue;
            for (const LiveJoint &joint : joints) {
                if (joint.kind != "hinge" || !joint.attached) continue;
                const std::string other = joint.a == from ? joint.b : joint.b == from ? joint.a : std::string{};
                if (!other.empty() && std::find(parts.begin(), parts.end(), other) == parts.end())
                    parts.push_back(other);
            }
        }
    }
    // What it senses, where each sensor is now, and what each reads.
    nlohmann::json sensors = nlohmann::json::array();
    for (const LiveSensor &s : c.sensors)
        sensors.push_back({{"kind", s.kind}, {"body", s.body}, {"depth_m", tidy(s.depth_m)},
                           {"stops", s.stops}, {"at_m", {tidy(s.at_m.x), tidy(s.at_m.y), tidy(s.at_m.z)}},
                           {"reading_m", tidy(s.reading_m)}, {"sees", s.sees}});
    return {{"id", c.id},
            {"sensors", std::move(sensors)},
            {"name", c.name},
            {"kind", c.rope != 0 ? "hoist" : "shaft"},
            {"motor", c.motor},
            {"rope", c.rope},
            {"parts", std::move(parts)},
            {"holds", holds},
            {"top_out_m", tidy(c.top_out_m)},
            {"bottom_out_m", tidy(c.bottom_out_m)},
            {"forward", c.forward},
            {"power", c.power},
            {"direction", c.direction},
            {"setting", tidy(c.setting)},
            {"sender", c.sender},
            {"seq", c.seq},
            {"command", tidy(c.command)},
            {"brake", c.brake},
            {"speed_rpm", tidy(c.speed_rpm)},
            {"out_m", tidy(c.out_m)},
            {"rope_speed_m_s", tidy(c.rope_speed_m_s)},
            {"condition", c.condition}};
}

// A program as a host reads it (LiveProgram): what it is doing and why, what
// each of its sensors reads and which side it is on, and the parts of its
// machine -- its controllers' parts -- so a person's E on any of them finds it.
nlohmann::json programOf(const LiveProgram &p, const nlohmann::json &controls) {
    nlohmann::json parts = nlohmann::json::array();
    for (const nlohmann::json &c : controls) {
        if (c.at("id") != p.left && c.at("id") != p.right) continue;
        for (const nlohmann::json &part : c.at("parts"))
            if (std::find(parts.begin(), parts.end(), part) == parts.end()) parts.push_back(part);
    }
    nlohmann::json sensors = nlohmann::json::array();
    for (const LiveSensor &s : p.sensors)
        sensors.push_back({{"kind", s.kind}, {"body", s.body}, {"depth_m", tidy(s.depth_m)}, {"side", s.side},
                           {"at_m", {tidy(s.at_m.x), tidy(s.at_m.y), tidy(s.at_m.z)}},
                           {"reading_m", tidy(s.reading_m)}, {"sees", s.sees}});
    return {{"id", p.id},
            {"name", p.name},
            {"kind", p.kind},
            {"left", p.left},
            {"right", p.right},
            {"body", p.body},
            {"parts", std::move(parts)},
            {"setting", tidy(p.setting)},
            {"climb_deg", tidy(p.climb_deg)},
            {"sensors", std::move(sensors)},
            {"power", p.power},
            {"sender", p.sender},
            {"seq", p.seq},
            {"doing", p.doing},
            {"why", p.why},
            {"doing_s", tidy(p.doing_s)},
            {"turned_deg", tidy(p.turned_deg)},
            {"turns", p.turns},
            {"pitch_deg", tidy(p.pitch_deg)},
            {"roll_deg", tidy(p.roll_deg)},
            {"rest_below", tidy(p.rest_below)},
            {"rest_until", tidy(p.rest_until)},
            {"charge_share", tidy(p.charge_share)},
            {"rests", p.rests}};
}

// What a break cost, as a host reads it (LiveBreakCost): the bonds the lattice
// removed, the crack they stand for, the energy that left with them and what
// that is per square metre -- against the material's own fracture energy and
// what the room's law charges for a crack at this cell size.
nlohmann::json costOf(const LiveBreakCost &cost) {
    if (cost.material.empty() && cost.broken_bonds == 0) return nullptr;
    return {{"material", cost.material},
            {"failure_law", cost.failure_law},
            {"broken_bonds", cost.broken_bonds},
            {"tensile_bonds", cost.tensile_bonds},
            {"compressive_bonds", cost.compressive_bonds},
            {"shear_bonds", cost.shear_bonds},
            {"removed_energy_j", tidy(cost.removed_energy_j)},
            {"crack_area_m2", tidy(cost.crack_area_m2)},
            {"crack_energy_j_m2", tidy(cost.crack_energy_j_m2)},
            {"declared_energy_j_m2", tidy(cost.declared_energy_j_m2)},
            {"law_energy_j_m2", tidy(cost.law_energy_j_m2)},
            {"bounded_by_strength", cost.bounded_by_strength},
            {"cell_size_m", tidy(cost.cell_size_m)}};
}

// The room's sun as a host reads it: where it is in the sky, and the way to it;
// and, for a sun with a day, the day and the hour.
nlohmann::json sunOf(const LiveSun &sun) {
    if (!sun.declared) return nullptr;
    nlohmann::json out = {{"elevation_deg", tidy(sun.elevation_deg)},
                          {"azimuth_deg", tidy(sun.azimuth_deg)},
                          {"irradiance_w_m2", tidy(sun.irradiance_w_m2)},
                          {"toward", {tidy(sun.toward.x), tidy(sun.toward.y), tidy(sun.toward.z)}}};
    if (sun.day_s > 0.0) {
        out["day_s"] = tidy(sun.day_s);
        out["noon_elevation_deg"] = tidy(sun.noon_elevation_deg);
        out["zenith_irradiance_w_m2"] = tidy(sun.zenith_irradiance_w_m2);
        out["hour"] = tidy(sun.hour);
    }
    return out;
}

// A solar panel as a host reads it (LiveSolarPanel).
nlohmann::json panelOf(const LiveSolarPanel &panel) {
    return {{"id", panel.id},
            {"name", panel.name},
            {"body", panel.body},
            {"store", panel.store},
            {"area_m2", tidy(panel.area_m2)},
            {"efficiency", tidy(panel.efficiency)},
            {"at_m", vec(panel.at_m)},
            {"normal", vec(panel.normal)},
            {"cos_incidence", tidy(panel.cos_incidence)},
            {"shaded", panel.shaded},
            {"shaded_by", panel.shaded_by},
            {"sunlight_w", tidy(panel.sunlight_w)},
            {"power_w", tidy(panel.power_w)},
            {"sunlight_j", tidy(panel.sunlight_j)},
            {"collected_j", tidy(panel.collected_j)},
            {"spilled_j", tidy(panel.spilled_j)},
            {"heat_j", tidy(panel.heat_j)}};
}

nlohmann::json machinesOf(const LiveWorld &world) {
    const std::vector<LiveEnergyStore> stores = world.energyStores();
    const std::vector<LiveMotor> motors = world.motors();
    const std::vector<LiveJoint> joints = world.joints();
    const std::vector<LiveControl> controls = world.controls();
    const std::vector<LiveProgram> programs = world.programs();
    const std::vector<LiveSolarPanel> panels = world.solarPanels();
    nlohmann::json ropes = nlohmann::json::array();
    for (const LiveJoint &joint : joints) {
        if (joint.kind != "drum" || !joint.attached) continue;
        ropes.push_back({{"joint", joint.id},
                         {"out_m", tidy(joint.at)},
                         {"wound_m", tidy(joint.wound_m)},
                         {"tension_n", tidy(joint.tension_n)},
                         {"leaves", vec(joint.leaves_m)},
                         {"meets", vec(joint.meets_m)}});
    }
    if (stores.empty() && motors.empty() && ropes.empty() && controls.empty() && programs.empty() && panels.empty())
        return nullptr;
    nlohmann::json out{{"stores", nlohmann::json::array()}, {"motors", nlohmann::json::array()},
                       {"ropes", std::move(ropes)}, {"controls", nlohmann::json::array()}};
    for (const LiveControl &c : controls) out["controls"].push_back(controlOf(c, motors, joints, world));
    for (const LiveEnergyStore &s : stores)
        out["stores"].push_back({{"id", s.id},
                                 {"name", s.name},
                                 {"body", s.body},
                                 {"capacity_j", tidy(s.capacity_j)},
                                 {"charge_j", tidy(s.charge_j)},
                                 {"voltage_v", tidy(s.voltage_v)},
                                 {"max_power_w", tidy(s.max_power_w)},
                                 {"given_j", tidy(s.given_j)},
                                 {"taken_j", tidy(s.taken_j)},
                                 {"short_j", tidy(s.short_j)}});
    for (const LiveMotor &m : motors) {
        // The two things its pin joins, by name: a step's joints travel only
        // when their set changes, and a host looking for the motor that turns
        // the drum it is looking at has the names.
        nlohmann::json on = nlohmann::json::array();
        for (const LiveJoint &joint : joints)
            if (joint.id == m.joint) on = {joint.a, joint.b};
        out["motors"].push_back({{"id", m.id},
                                 {"joint", m.joint},
                                 {"on", std::move(on)},
                                 {"store", m.store},
                                 {"state", m.state},
                                 {"command", tidy(m.command)},
                                 {"brake", m.brake},
                                 {"stall_torque_n_m", tidy(m.stall_torque_n_m)},
                                 {"no_load_rad_s", tidy(m.no_load_rad_s)},
                                 {"brake_torque_n_m", tidy(m.brake_torque_n_m)},
                                 {"speed_rad_s", tidy(m.speed_rad_s)},
                                 {"torque_n_m", tidy(m.torque_n_m)},
                                 {"current_a", tidy(m.current_a)},
                                 {"power_w", tidy(m.power_w)},
                                 {"turned_rad", tidy(m.turned_rad)},
                                 {"work_j", tidy(m.work_j)},
                                 {"heat_j", tidy(m.heat_j)},
                                 {"drawn_j", tidy(m.drawn_j)},
                                 {"friction_heat_j", tidy(m.friction_heat_j)}});
    }
    out["circuits"] = nlohmann::json::parse(world.circuits());
    // Only a world with a program says anything of programs, and only one
    // with a solar panel of panels.
    if (!programs.empty()) {
        out["programs"] = nlohmann::json::array();
        for (const LiveProgram &p : programs) out["programs"].push_back(programOf(p, out["controls"]));
    }
    if (!panels.empty()) {
        out["panels"] = nlohmann::json::array();
        for (const LiveSolarPanel &panel : panels) out["panels"].push_back(panelOf(panel));
    }
    return out;
}

nlohmann::json jointsOf(const LiveWorld &world) {
    constexpr double kDegrees = 180.0 / 3.14159265358979323846;
    nlohmann::json out = nlohmann::json::array();
    for (const LiveJoint &joint : world.joints()) {
        // The unit is the kind. A pin has turned so many degrees and grips in
        // newton metres; a slide has moved so many metres and grips in newtons.
        // Spelled out in the key rather than left for the reader to work out
        // from `kind`, because a host that draws "0.8" next to a portcullis had
        // better not be reading it as degrees.
        const bool sliding = joint.kind == "slider";
        nlohmann::json said{{"id", joint.id},
                            {"kind", joint.kind},
                            {"a", joint.a},
                            {"b", joint.b},
                            {"at", vec(joint.point_world_m)},
                            {"axis", vec(joint.axis_world)},
                            {"attached", joint.attached}};
        // Away in the bag with the thing it is in (LiveWorld::park): still in
        // it, and made again when the thing is back.
        if (joint.away) said["away"] = true;
        if (joint.kind == "elastic") {
            // The declared linear model, and what it currently holds.
            said["metres"] = tidy(joint.at);
            said["rest_m"] = tidy(joint.rest_m);
            said["stiffness_n_m"] = tidy(joint.stiffness_n_m);
            said["damping_n_s_m"] = tidy(joint.damping_n_s_m);
            said["force_n"] = tidy(joint.force_n);
            said["stored_j"] = tidy(joint.stored_j);
        } else if (joint.kind == "fixing") {
            // Two loads and two bounds, because a peg pulled straight out and a
            // peg sheared sideways fail at different loads.
            said["tension_n"] = tidy(joint.tension_n_now);
            said["shear_n"] = tidy(joint.shear_n_now);
            said["holds_tension_n"] = tidy(joint.holds_tension_n);
            said["holds_shear_n"] = tidy(joint.holds_shear_n);
            // One-way: an arrow on a string. What it holds b with, along the
            // axis that points the way b comes off.
            if (joint.comes_off_n > 0.0) said["comes_off_n"] = tidy(joint.comes_off_n);
        } else if (joint.kind == "pulley") {
            // The whole run: one side plus the ratio times the other, which is
            // the quantity the constraint actually holds.
            said["metres"] = tidy(joint.at);
            said["length_m"] = tidy(joint.upper);
            said["tension_n"] = tidy(joint.tension_n);
            said["ratio"] = tidy(joint.ratio);
            said["over_a"] = vec(joint.over_a_m);
            said["over_b"] = vec(joint.over_b_m);
        } else if (joint.kind == "link") {
            // A rope's state is its length and what it is carrying. It has no
            // friction and no travel in either direction -- it is nought to its
            // length, and the asymmetry IS the rope.
            said["metres"] = tidy(joint.at);
            said["length_m"] = tidy(joint.upper);
            said["tension_n"] = tidy(joint.tension_n);
            said["breaks_at_n"] = tidy(joint.breaks_at_n);
        } else if (joint.kind == "drum") {
            // A rope on a drum (rigid/DrumRope.hpp): how much of it is off the
            // drum and on it, what it carries, and where it leaves the drum and
            // meets the load, for a host that draws it.
            said["metres"] = tidy(joint.at);
            said["length_m"] = tidy(joint.upper);
            said["wound_m"] = tidy(joint.wound_m);
            said["radius_m"] = tidy(joint.radius_m);
            said["winds"] = joint.winds;
            said["tension_n"] = tidy(joint.tension_n);
            said["leaves"] = vec(joint.leaves_m);
            said["meets"] = vec(joint.meets_m);
        } else if (sliding) {
            said["metres"] = tidy(joint.at);
            said["lower_m"] = tidy(joint.lower);
            said["upper_m"] = tidy(joint.upper);
            said["friction_n"] = tidy(joint.friction);
        } else {
            said["degrees"] = tidy(joint.at * kDegrees);
            said["lower_deg"] = tidy(joint.lower * kDegrees);
            said["upper_deg"] = tidy(joint.upper * kDegrees);
            said["friction_n_m"] = tidy(joint.friction);
        }
        // What it is made of, what it could take cold and what is left -- only
        // for a joint with a member (docs/thermal-mechanics.md) -- and, for one
        // that let go, why, in the numbers that decided it.
        if (!joint.member.empty()) {
            said["member"] = joint.member;
            said["capacity_fraction"] = tidy(joint.capacity_fraction);
            said["rechecks"] = joint.rechecks;
            if (joint.kind == "fixing") {
                said["rated_tension_n"] = tidy(joint.rated_tension_n);
                said["rated_shear_n"] = tidy(joint.rated_shear_n);
            } else if (joint.kind == "link") {
                said["rated_breaks_at_n"] = tidy(joint.rated_breaks_at_n);
            } else if (joint.kind == "elastic") {
                said["rated_stiffness_n_m"] = tidy(joint.rated_stiffness_n_m);
            }
        }
        if (!joint.parted_because.empty()) {
            said["parted_because"] = joint.parted_because;
            said["parted_load_n"] = tidy(joint.parted_load_n);
            said["parted_capacity_n"] = tidy(joint.parted_capacity_n);
        }
        out.push_back(std::move(said));
    }
    return out;
}

// A number rounded to what can be seen.
[[nodiscard]] double roundTo(double v, double unit) {
    return std::isfinite(v) ? std::round(v / unit) * unit : v;
}

// What heat has done to what things can carry, for a host that draws it
// (docs/thermal-mechanics.md): each heated body with a law -- what is left of
// its section and how much of it is char -- and every joint made of a member,
// with the load it carries against what it can still take. Empty when there is
// neither; small when there is, like the heat block beside it.
nlohmann::json mechanicsSummary(const LiveWorld &world) {
    nlohmann::json bodies = nlohmann::json::array();
    for (const LiveMaterialState &m : world.materialStates()) {
        if (m.law.empty() || !m.tracked || bodies.size() >= 24) continue;
        const banjo::thermo::SectionState &s = m.section;
        bodies.push_back({{"name", m.name},
                          {"tension", roundTo(s.tension, 1e-3)},
                          {"shear", roundTo(s.shear, 1e-3)},
                          {"bending", roundTo(s.bending, 1e-3)},
                          {"stiffness", roundTo(s.axial_stiffness, 1e-3)},
                          {"if_cooled", roundTo(std::min(s.tension_if_cooled, s.shear_if_cooled), 1e-3)},
                          {"char_mm", roundTo(1000.0 * s.char_m, 0.1)},
                          {"burned_mm", roundTo(1000.0 * s.consumed_m, 0.01)},
                          // How that matter went: "burned" (oak), "melted" (ice).
                          {"gone", banjo::thermo::lawFor(m.material) != nullptr
                                       ? banjo::thermo::lawFor(m.material)->gone : std::string("burned")},
                          {"section_mm", nlohmann::json::array({roundTo(1000.0 * s.breadth_m, 0.1),
                                                                roundTo(1000.0 * s.depth_m, 0.1)})},
                          {"sound_mm", nlohmann::json::array({roundTo(1000.0 * s.sound_breadth_m, 0.1),
                                                              roundTo(1000.0 * s.sound_depth_m, 0.1)})},
                          {"supported", s.supported},
                          // The compression side of the bending, and what is
                          // left of it (docs/thermal-mechanics.md, "One
                          // material state"): what collides and is drawn, what
                          // it weighs, its cells, what a lattice run gets.
                          {"bending_compression", roundTo(s.bending_compression, 1e-3)},
                          {"now_mm", nlohmann::json::array({roundTo(1000.0 * m.remaining_m.x, 0.1),
                                                            roundTo(1000.0 * m.remaining_m.y, 0.1),
                                                            roundTo(1000.0 * m.remaining_m.z, 0.1)})},
                          {"mass_kg", roundTo(m.mass_kg, 1e-3)},
                          {"cells", m.cells},
                          {"cells_burned", m.cells_burned},
                          {"bond_tension", roundTo(m.bond_tension_mean, 1e-3)},
                          {"revision", m.revision}});
    }
    // What statics said about each body it answered for a sustained load, and
    // what has burned away entirely.
    nlohmann::json statics = nlohmann::json::array();
    for (const LiveStatics &s : world.statics())
        statics.push_back({{"name", s.name},
                           {"stop", s.stop},
                           {"load_n", roundTo(s.load_n, 0.1)},
                           {"ratio", roundTo(s.first_failure_ratio, 1e-3)},
                           {"bonds", s.bonds_removed},
                           {"pieces", s.pieces},
                           {"t", roundTo(s.time_s, 0.01)}});
    nlohmann::json burned = nlohmann::json::array();
    for (const LiveBurnedAway &b : world.burnedAway())
        burned.push_back({{"name", b.name}, {"t", roundTo(b.time_s, 0.01)},
                          {"residue_kg", roundTo(b.residue_kg, 1e-3)}, {"why", b.why}, {"gone", b.gone}});
    nlohmann::json held = nlohmann::json::array();
    for (const LiveJoint &j : world.joints()) {
        if (j.member.empty()) continue;
        nlohmann::json said{{"id", j.id}, {"kind", j.kind}, {"a", j.a}, {"b", j.b},
                            {"member", j.member}, {"attached", j.attached},
                            {"fraction", roundTo(j.capacity_fraction, 1e-4)}};
        if (j.kind == "fixing") {
            // The one of its two nearer to giving.
            const double t = j.holds_tension_n > 0.0 ? j.tension_n_now / j.holds_tension_n : 0.0;
            const double v = j.holds_shear_n > 0.0 ? j.shear_n_now / j.holds_shear_n : 0.0;
            const bool shear = v >= t;
            said["mode"] = shear ? "shear" : "tension";
            said["load_n"] = roundTo(shear ? j.shear_n_now : j.tension_n_now, 0.1);
            said["holds_n"] = roundTo(shear ? j.holds_shear_n : j.holds_tension_n, 0.1);
            said["rated_n"] = roundTo(shear ? j.rated_shear_n : j.rated_tension_n, 0.1);
        } else if (j.kind == "link") {
            said["mode"] = "tension";
            said["load_n"] = roundTo(j.tension_n, 0.1);
            said["holds_n"] = roundTo(j.breaks_at_n, 0.1);
            said["rated_n"] = roundTo(j.rated_breaks_at_n, 0.1);
        } else {
            said["mode"] = "stiffness";
            said["stiffness_n_m"] = roundTo(j.stiffness_n_m, 0.1);
            said["rated_stiffness_n_m"] = roundTo(j.rated_stiffness_n_m, 0.1);
            said["force_n"] = roundTo(j.force_n, 0.1);
        }
        if (!j.parted_because.empty()) said["parted_because"] = j.parted_because;
        held.push_back(std::move(said));
    }
    if (bodies.empty() && held.empty() && statics.empty() && burned.empty()) return nullptr;
    return {{"bodies", std::move(bodies)},
            {"attachments", std::move(held)},
            {"statics", std::move(statics)},
            {"burned_away", std::move(burned)}};
}

// Every edge in the room. Sent when the SET of them changes, like the pins: the
// edge rides on its body's pose, so its local frame is all a host needs to draw
// it from then on.
std::string last_blades;

nlohmann::json bladesOf(const LiveWorld &world) {
    nlohmann::json out = nlohmann::json::array();
    for (const LiveBlade &blade : world.blades())
        out.push_back({{"id", blade.id},
                       {"body", blade.body},
                       {"material", blade.material},
                       {"heel_local", vec(blade.heel_local_m)},
                       {"tip_local", vec(blade.tip_local_m)},
                       {"facing_local", vec(blade.facing_local)},
                       {"grip_local", vec(blade.grip_local_m)},
                       {"heel", vec(blade.heel_m)},
                       {"tip", vec(blade.tip_m)},
                       {"grip", vec(blade.grip_m)},
                       {"thickness_m", tidy(blade.thickness_m)},
                       {"edge_radius_m", blade.edge_radius_m},
                       {"bevel_deg", tidy(blade.bevel_deg)},
                       {"cut_area_mm2", tidy(blade.cut_area_m2 * 1.0e6)},
                       {"cut_work_j", tidy(blade.cut_work_j)},
                       {"cutting", blade.cutting},
                       {"attached", blade.attached}});
    return out;
}

// Every point a tool has (docs/ground-work.md). Sent when the SET of them
// changes, like the edges: what a point is in, and how deep, comes with the
// ground work instead.
std::string last_tool_points;

nlohmann::json toolPointsOf(const LiveWorld &world) {
    nlohmann::json out = nlohmann::json::array();
    for (const LiveToolPoint &p : world.toolPoints())
        out.push_back({{"id", p.id},
                       {"body", p.body},
                       {"material", p.material},
                       {"tip_local", vec(p.tip_local_m)},
                       {"pointing_local", vec(p.pointing_local)},
                       {"grip_local", vec(p.grip_local_m)},
                       {"tip", vec(p.tip_m)},
                       {"pointing", vec(p.pointing)},
                       {"grip", vec(p.grip_m)},
                       {"width_m", tidy(p.width_m)},
                       {"thickness_m", tidy(p.thickness_m)},
                       {"angle_deg", tidy(p.angle_deg)},
                       {"length_m", tidy(p.length_m)},
                       {"in", p.in},
                       {"depth_m", tidy(p.depth_m)},
                       {"attached", p.attached}});
    return out;
}

// One meeting between a point and the ground, in the room's units.
nlohmann::json groundWorkFields(const LiveGroundWork &w);

nlohmann::json groundWorkJson(const LiveGroundWork &w) {
    nlohmann::json out = groundWorkFields(w);
    // Where what came loose went out through the ground's dig, as a dig edit
    // says it, and not rounded: a host that keeps the ground's edits makes it
    // again from these numbers and has to get the same hole.
    if (w.dug)
        out["dug"] = {{"from_m", {w.dug_from_m[0], w.dug_from_m[1]}},
                      {"to_m", {w.dug_to_m[0], w.dug_to_m[1]}},
                      {"width_m", w.dug_width_m},
                      {"depth_m", w.dug_depth_m}};
    return out;
}

nlohmann::json groundWorkFields(const LiveGroundWork &w) {
    return {{"point", w.point},
            {"tool", w.tool},
            {"ground", w.ground},
            {"kind", w.kind},
            {"supported", w.supported},
            {"why", w.why},
            {"at_s", tidy(w.at_s)},
            {"at_m", vec(w.at_m)},
            {"closing_speed_m_s", tidy(w.closing_speed_m_s)},
            {"depth_m", tidy(w.depth_m)},
            {"sideways_m", tidy(w.sideways_m)},
            {"impulse_n_s", tidy(w.impulse_n_s)},
            {"peak_force_n", tidy(w.peak_force_n)},
            {"work_j", tidy(w.work_j)},
            {"penetration_work_j", tidy(w.penetration_work_j)},
            {"breakout_work_j", tidy(w.breakout_work_j)},
            {"resistance_n", tidy(w.resistance_n)},
            {"passive_n", tidy(w.passive_n)},
            // Not rounded: the carried account is kept to the bit, and what a
            // meeting took out of the ground is part of it.
            {"loosened", {{"sand_m3", w.loosened.sand_m3}, {"soil_m3", w.loosened.soil_m3}}},
            {"loosened_kg", tidy(w.loosened_kg)},
            {"tool_whole", w.tool_whole},
            {"tool_dent_mm", tidy(w.tool_dent_m * 1000.0)},
            {"model", w.model},
            {"open", w.open}};
}

// A tool action from a command (LiveStrike). The engine checks the numbers.
LiveStrike readStrike(const nlohmann::json &command) {
    const auto point = [&](const char *key) -> Vec3 {
        if (!command.contains(key)) return {};
        const nlohmann::json &p = command.at(key);
        if (!p.is_array() || p.size() != 3)
            throw std::invalid_argument(std::string(key) + " is a point: three numbers");
        return {p[0].get<double>(), p[1].get<double>(), p[2].get<double>()};
    };
    LiveStrike strike;
    strike.lever = command.value("lever", false);
    if (!strike.lever && !command.contains("at"))
        throw std::invalid_argument("a swing needs \"at\": the point on the ground it comes down on");
    if (!command.contains("shoulder"))
        throw std::invalid_argument("a tool action needs \"shoulder\": where the swing turns about");
    strike.target_m = point("at");
    strike.shoulder_m = point("shoulder");
    strike.speed_m_s = command.value("speed_m_s", strike.speed_m_s);
    strike.raise_deg = command.value("raise_deg", strike.raise_deg);
    strike.lever_deg = command.value("lever_deg", strike.lever_deg);
    strike.give_up_s = command.value("give_up_s", strike.give_up_s);
    return strike;
}

// One meeting between an edge and something, in the room's units.
nlohmann::json cutJson(const LiveCut &cut) {
    return {{"blade", cut.blade},
            {"target", cut.target},
            {"kind", cut.kind},
            {"at_s", tidy(cut.at_s)},
            {"speed_m_s", tidy(cut.speed_m_s)},
            {"into_m_s", tidy(cut.into_m_s)},
            {"along_m_s", tidy(cut.along_m_s)},
            {"across_m_s", tidy(cut.across_m_s)},
            {"resistance_j_m2", tidy(cut.resistance_j_m2)},
            {"area_mm2", tidy(cut.area_m2 * 1.0e6)},
            {"work_j", tidy(cut.work_j)},
            {"bonds", cut.bonds},
            {"links", cut.links},
            {"separated", cut.separated},
            {"pieces", cut.pieces},
            {"open", cut.open}};
}

// `only_moved` sends a body only if it is not identical to the last one sent
// under that name. The reply then says so, and says which names have gone, so a
// host can tell "this body did not change" from "this body no longer exists" --
// which it has to, because it deletes anything a reply leaves out.
nlohmann::json describe(LiveWorld &world, bool with_geometry, bool only_moved = false) {
    // A reply that goes out whole leaves the cache empty behind it, because
    // whoever got it is up to date and nobody else is: one process can be
    // driving a room and answering a chat window's questions at the same time,
    // and the room must not be told a body is unchanged on the strength of a
    // reply that went somewhere else. The next partial request after that is
    // answered in full -- marked not partial, so the host replaces what it has
    // -- and trimming resumes from there. It costs one big reply and it cannot
    // go stale.
    const bool trim = only_moved && !last_sent.empty();
    // A piece's cells are its surface, and they can change where it stands:
    // burning takes cells away (docs/thermal-mechanics.md, "One material
    // state"), and a piece can come apart into new pieces during a step.
    // Geometry travels only with the opening state, a poses request or a
    // fracture, so the room's own stream carries a piece's cells whenever its
    // revision is not the one that stream last carried them at -- that piece's
    // only, and only then. Not recorded from replies that carry geometry: those
    // can have gone to a chat window, and a piece sent twice costs less than a
    // piece drawn from cells it no longer has.
    std::vector<LiveBodyPose> poses = world.poses(with_geometry);
    const auto reshaped = [&](const LiveBodyPose &p) {
        if (!only_moved || p.shape != "hull") return false;
        const auto sent = cells_sent_at.find(p.name);
        return sent == cells_sent_at.end() || sent->second != p.revision;
    };
    if (!with_geometry && std::any_of(poses.begin(), poses.end(), reshaped)) poses = world.poses(true);
    nlohmann::json bodies = nlohmann::json::array();
    std::unordered_set<std::string> present;
    std::size_t count = 0;
    for (const LiveBodyPose &pose : poses) {
        char colour[16];
        std::snprintf(colour, sizeof colour, "%08x", pose.color_rgba);
        nlohmann::json body = {{"name", pose.name}, {"material", pose.material},
                          {"shape", pose.shape},
                          {"dimensions_m", vec(pose.dimensions_m)},
                          {"position_m", vec(pose.position_m)},
                          {"orientation_wxyz", nlohmann::json::array({
                               tidy(pose.orientation_wxyz[0]), tidy(pose.orientation_wxyz[1]),
                               tidy(pose.orientation_wxyz[2]), tidy(pose.orientation_wxyz[3])})},
                          {"velocity_m_s", vec(pose.velocity_m_s)},
                          // What a hand has to hold up and a throw accelerate.
                          {"mass_kg", tidy(pose.mass_kg)},
                          {"anchored", pose.anchored},
                          {"held", pose.held},
                          // How deep a permanent set it carries, and where.
                          // A dent is real and small -- a fifth of a millimetre
                          // on a 120 mm ball -- so the number is the honest way
                          // to show it, not a redrawn outline.
                          {"dent_mm", tidy(pose.dent_m * 1000.0)},
                          {"dent_at_m", vec(pose.dent_at_m)},
                          // Times its shape changed where it stands: burning
                          // takes a box in from every face, and a piece whose
                          // cells burn away is rebuilt. Redraw when it moves.
                          {"revision", pose.revision},
                          {"color_rgba", std::string(colour)}};
        if (!pose.mechanical_model.empty()) {
            body["mechanical_model"] = pose.mechanical_model;
            body["internal_failure_supported"] = false;
            // Bounded to 256 parts per room. Send exact geometry on every
            // emitted compound record so partial/full clients cannot lose it:
            // each part about the centre of mass, box or cylinder (along its
            // own y, sized diameter/length/diameter), turned, of its material.
            nlohmann::json parts = nlohmann::json::array();
            for (const auto &part : pose.rigid_parts_local) {
                nlohmann::json entry = {
                    {"shape", part.shape},
                    {"center_local_m", {part.center_local_m.x, part.center_local_m.y, part.center_local_m.z}},
                    {"dimensions_m", {part.dimensions_m.x, part.dimensions_m.y, part.dimensions_m.z}},
                    {"rotation_wxyz", {part.rotation_wxyz[0], part.rotation_wxyz[1], part.rotation_wxyz[2], part.rotation_wxyz[3]}},
                    {"material", part.material}};
                if (!part.name.empty()) entry["name"] = part.name;
                parts.push_back(std::move(entry));
            }
            body["rigid_parts_local"] = std::move(parts);
        }
        if (!pose.cells_local_m.empty() && (with_geometry || reshaped(pose))) {
            nlohmann::json cells = nlohmann::json::array();
            for (const Vec3 &at : pose.cells_local_m) cells.push_back(vec(at));
            body["cells_local_m"] = std::move(cells);
            if (only_moved) cells_sent_at[pose.name] = pose.revision;
        }
        // Where a blade has been through it: the plane, and what of it was
        // swept, as strips. Part of the body's own record, so it goes out when it
        // changes and not otherwise -- the comparison below sees to that.
        if (!pose.kerfs.empty()) {
            nlohmann::json cuts = nlohmann::json::array();
            for (const LiveBodyPose::Kerf &kerf : pose.kerfs) {
                nlohmann::json strips = nlohmann::json::array();
                for (const LiveBodyPose::Kerf::Strip &strip : kerf.strips)
                    strips.push_back(nlohmann::json::array(
                        {tidy(strip.along_from), tidy(strip.along_to),
                         tidy(strip.facing_from), tidy(strip.facing_to)}));
                cuts.push_back({{"at", vec(kerf.point_local_m)},
                                {"along", vec(kerf.along_local)},
                                {"facing", vec(kerf.facing_local)},
                                {"normal", vec(kerf.normal_local)},
                                {"thickness_m", tidy(kerf.thickness_m)},
                                {"strips", std::move(strips)}});
            }
            body["kerfs"] = std::move(cuts);
        }
        ++count;
        present.insert(pose.name);
        // Compared as written, so the comparison is exactly what the host would
        // have received -- a difference too small to survive tidy() is not a
        // difference anybody can see.
        std::string written = body.dump();
        std::string &remembered = last_sent[pose.name];
        const bool same = remembered == written;
        remembered = std::move(written);
        if (trim && same) continue;
        bodies.push_back(std::move(body));
    }
    // Names the cache still holds that the world no longer has: broken up,
    // or replaced by their pieces.
    nlohmann::json gone = nlohmann::json::array();
    for (auto it = last_sent.begin(); it != last_sent.end();) {
        if (present.count(it->first)) { ++it; continue; }
        gone.push_back(it->first);
        // A body that comes back (LiveWorld::unpark) is drawn from its cells
        // again, so what was sent of them goes with it.
        cells_sent_at.erase(it->first);
        it = last_sent.erase(it);
    }
    if (!only_moved) last_sent.clear();
    // What each elastic holds -- how far it is stretched, how hard it pulls and
    // the energy in it: the declared model's numbers (LiveWorld::joints), which
    // a host cannot work out from the poses without deciding physics itself.
    // Sent like the bodies and on the same terms, all of them in a whole reply
    // and in a partial one only those that changed: a bow being drawn, its two
    // limbs every step; a spring at rest, nothing. The pins themselves travel
    // only when their SET changes (the step's reply, below), and while these
    // travelled with them the room asked for the whole list a few times a
    // second instead: its bow meter read 16.4 J at 387 mm into a 0.4 m/s draw,
    // where the engine held 32.0 J.
    nlohmann::json elastics = nlohmann::json::array();
    std::unordered_set<unsigned> springs;
    for (const LiveJoint &joint : world.joints()) {
        if (joint.kind != "elastic") continue;
        springs.insert(joint.id);
        nlohmann::json said = {{"id", joint.id}, {"metres", tidy(joint.at)},
                               {"force_n", tidy(joint.force_n)},
                               {"stored_j", tidy(joint.stored_j)}};
        std::string written = said.dump();
        std::string &remembered = last_elastics[joint.id];
        const bool same = remembered == written;
        remembered = std::move(written);
        if (trim && same) continue;
        elastics.push_back(std::move(said));
    }
    for (auto it = last_elastics.begin(); it != last_elastics.end();)
        it = springs.count(it->first) ? std::next(it) : last_elastics.erase(it);
    if (!only_moved) last_elastics.clear();
    for (auto it = cells_sent_at.begin(); it != cells_sent_at.end();)
        it = present.count(it->first) ? std::next(it) : cells_sent_at.erase(it);
    nlohmann::json impacts = nlohmann::json::array();
    for (const LiveImpact &impact : world.impacts()) {
        nlohmann::json said = {{"struck", impact.struck}, {"by", impact.by},
                               {"closing_speed_m_s", impact.closing_speed_m_s},
                               {"threshold_speed_m_s", impact.threshold_speed_m_s},
                               {"dent_speed_m_s", impact.dent_speed_m_s},
                               {"energy_j", impact.energy_j},
                               {"would_break", impact.would_break},
                               {"would_dent", impact.would_dent}};
        if (!impact.declined.empty()) said["declined"] = impact.declined;
        impacts.push_back(std::move(said));
    }
    nlohmann::json state = {{"ok", true}, {"t", world.time_s()}, {"stepped_back", world.steppedBack()},
            {"cell_size_m", world.cellSize()}, {"geometry", with_geometry},
            // `partial` true means bodies missing from this reply are unchanged,
            // not gone; `gone` names the ones that really did go. `count` is how
            // many the world holds either way.
            {"partial", trim}, {"count", count}, {"gone", std::move(gone)},
            {"held", world.held()}, {"bodies", std::move(bodies)},
            {"impacts", std::move(impacts)}, {"breakable", world.breakable()},
            // What is being worked out right now, if anything. A host that asks
            // for a second fracture while one is running gets nothing, so it
            // needs to know.
            {"working_on", world.fracturePending() ? world.fractureSubject() : std::string{}}};
    if (!elastics.empty()) state["elastics"] = std::move(elastics);
    // The hand, while it holds something and once a stroke has opened it.
    const LiveHand hand = world.hand();
    if (!hand.holding.empty() || hand.let_go_at_s >= 0.0 || !hand.stroke_ended.empty())
        state["hand"] = handJson(hand);
    // Every moment the world waited, or was spared waiting, since the last
    // reply carried them. Drained here rather than accumulated, so a host
    // reading each reply sees each one exactly once.
    //
    // This was the whole point of recording them and it was missing: they were
    // kept in the engine and handed to the C library, and the playground talks
    // to this, so nothing that drives the room could see any of it. A log
    // nobody can read is not a log.
    nlohmann::json waits = nlohmann::json::array();
    for (const LiveDelay &delay : world.delays()) {
        nlohmann::json wait{{"at_s", delay.at_s}, {"object", delay.object},
                            {"kind", delay.kind}, {"lead_ms", delay.lead_ms},
                            {"cost_ms", delay.cost_ms}};
        // A lattice run: the step it was taken at, its own lattice's, and how
        // many it took.
        if (delay.steps > 0) {
            wait["step_us"] = 1.0e6 * delay.step_s;
            wait["steps"] = delay.steps;
        }
        waits.push_back(std::move(wait));
    }
    if (!waits.empty()) state["waits"] = std::move(waits);
    // Every edge contact since the last reply that carried them: the open ones
    // as they now stand, the closed ones one last time. The caller forgets the
    // closed ones after sending, so each is seen finished exactly once.
    nlohmann::json cut_list = nlohmann::json::array();
    for (const LiveCut &cut : world.cuts()) cut_list.push_back(cutJson(cut));
    if (!cut_list.empty()) state["cuts"] = std::move(cut_list);
    return state;
}

// What is hot, what is burning and what the gas is doing, for a host that
// draws it. Every reply that describes the world carries this while the world
// has any heat, chemistry or gas in it -- rounded to what can be seen, and only
// the bodies worth drawing: a room of two hundred shards at room temperature is
// not news, and the wire is where the room's lags have been found before.
nlohmann::json heatSummary(const banjo::thermo::ThermoWorld &network) {
    const auto round = [](double v, double unit) {
        return std::isfinite(v) ? std::round(v / unit) * unit : v;
    };
    const double ambient = network.ambient().temperature_k;
    std::vector<banjo::thermo::BodyHeat> all = network.bodies();
    std::sort(all.begin(), all.end(), [&](const auto &a, const auto &b) {
        return std::abs(a.temperature_k - ambient) + (a.reacting ? 1.0e4 : 0.0) >
               std::abs(b.temperature_k - ambient) + (b.reacting ? 1.0e4 : 0.0);
    });
    nlohmann::json bodies = nlohmann::json::array();
    nlohmann::json stored = nlohmann::json::array();
    for (const banjo::thermo::BodyHeat &b : all) {
        // Stored items remain observable even when cold, and are never drawn
        // as world-space glow/flames. Do not let the visible-body cap hide them.
        if (b.parked) {
            stored.push_back({{"name", b.body}, {"t_k", round(b.temperature_k, 0.1)},
                              {"core_k", round(b.core_temperature_k, 0.1)},
                              {"boundary", "insulated-nonreacting"}});
            continue;
        }
        if (bodies.size() >= 48) continue;
        if (!b.reacting && !b.melting && !(b.heater_w > 0.0) && std::abs(b.temperature_k - ambient) < 1.0) continue;
        bodies.push_back({{"name", b.body},
                          {"t_k", round(b.temperature_k, 0.1)},
                          {"core_k", round(b.core_temperature_k, 0.1)},
                          {"fuel_kg", round(b.fuel_kg, 1.0e-4)},
                          {"power_w", round(b.heat_release_w, 1.0)},
                          {"heater_w", round(b.heater_w, 1.0)},
                          {"remaining_s", std::isfinite(b.remaining_s)
                                              ? nlohmann::json(round(b.remaining_s, 1.0))
                                              : nlohmann::json(nullptr)},
                          {"reacting", b.reacting}});
        // Melting, only for what melts: how fast, in grams a second, and how
        // much has gone since it was followed.
        if (b.melting || b.melted_kg > 0.0) {
            bodies.back()["melt_g_s"] = round(1000.0 * b.melt_kg_s, 0.01);
            bodies.back()["melted_kg"] = round(b.melted_kg, 1.0e-4);
        }
    }
    nlohmann::json regions = nlohmann::json::array();
    for (const banjo::thermo::RegionState &r : network.regions())
        regions.push_back({{"name", r.name},
                           {"piston", r.piston},
                           {"t_k", round(r.temperature_k, 0.1)},
                           {"p_pa", round(r.pressure_pa, 1.0)},
                           {"v_m3", round(r.volume_m3, 1.0e-7)},
                           {"base_m", vec(r.base_m)},
                           {"axis", vec(r.axis)},
                           {"area_m2", round(r.area_m2, 1.0e-6)},
                           {"height_m", tidy(r.height_m)},
                           {"stroke_m", tidy(r.stroke_m)},
                           {"force_n", round(r.force_n, 0.1)},
                           {"work_j", round(r.work_to_bodies_j, 0.01)},
                           {"heater_w", round(r.heater_w, 1.0)}});
    const banjo::thermo::Ledger l = network.ledger();
    return {{"t", network.timeS()},
            {"ambient_k", ambient},
            {"bodies", std::move(bodies)},
            {"stored", std::move(stored)},
            {"regions", std::move(regions)},
            {"ledger", {{"stored_j", round(l.storedJ(), 1.0)},
                        {"residual_j", l.residualJ()},
                        {"heater_in_j", round(l.heater_in_j, 1.0)},
                        {"heat_out_j", round(l.heat_to_surroundings_j, 1.0)}}}};
}

Vec3 readVec(const nlohmann::json &node, const char *key) {
    const auto &v = node.at(key);
    if (!v.is_array() || v.size() != 3) throw std::invalid_argument(std::string(key) + " needs three numbers");
    return Vec3{v[0].get<double>(), v[1].get<double>(), v[2].get<double>()};
}

// A joint's "member", when it has one: which of its two ends it is MADE of
// (docs/thermal-mechanics.md). Checked before the joint is made, so a joint is
// never left standing without the member it was asked to be made of.
std::string madeOf(const nlohmann::json &command) {
    if (!command.contains("member") || command.at("member").is_null()) return {};
    const std::string member = command.at("member").get<std::string>();
    if (member.empty()) return {};
    if (member != command.at("a").get<std::string>() && member != command.at("b").get<std::string>())
        throw std::invalid_argument("a joint is made of one of the two things it holds, and \"" + member +
                                    "\" is neither");
    return member;
}

// A point on the ground: [x, z], or [x, y, z] with y ignored.
std::pair<double, double> readXZ(const nlohmann::json &node, const char *key) {
    const auto &v = node.at(key);
    if (!v.is_array() || (v.size() != 2 && v.size() != 3))
        throw std::invalid_argument(std::string(key) + " needs [x, z] or [x, y, z]");
    return {v[0].get<double>(), v[v.size() - 1].get<double>()};
}

// ---- the ground and the water, for a host that draws them ----------------------
//
// The ground is sent whole once -- float32 heights and one byte per column for
// what it is made of -- and after that only the rectangle that changed, found by
// comparing with what was last sent, so a bank slumping into a trench is caught
// as surely as the trench. The water's surface goes as whole millimetres over
// the smallest box holding all the water, a few times a world-second: the wire
// is where this room's stutters have been found before, and a river's surface
// does not need to be sent at 240 Hz to be seen moving.
double water_sent_at = -1.0e9;
constexpr double kWaterEveryS = 0.25;

// What the person carries out of the ground: the sand and soil dug, less what
// went back (terrain::Environment::carried). Not rounded -- a heap of all of it
// is asked for with these very numbers, and a heap bigger than what is carried
// is refused.
nlohmann::json carriedJson(const banjo::terrain::Environment &env, double objects_kg) {
    const banjo::terrain::Volumes &c = env.carried();
    nlohmann::json out{{"sand_m3", c.sand_m3}, {"soil_m3", c.soil_m3},
                       {"sand_kg", c.sand_m3 * banjo::terrain::sandMaterial().density_kg_m3},
                       {"soil_kg", c.soil_m3 * banjo::terrain::soilMaterial().density_kg_m3}};
    // How much of it a person can carry, where a host has said.
    out["objects_kg"]=objects_kg;out["total_kg"]=objects_kg+env.carriedKg();
    if (std::isfinite(env.carryLimitKg())) {
        out["limit_kg"] = env.carryLimitKg();
        out["available_kg"]=std::max(0.0,env.carryLimitKg()-objects_kg-env.carriedKg());
        out["over_limit_kg"]=std::max(0.0,objects_kg+env.carriedKg()-env.carryLimitKg());
    }
    return out;
}

// How far past what is carried a heap may go: a cubic millimetre, for a host
// that added the numbers up another way. A heap of everything carried, asked
// for with the numbers a reply gave, needs none.
constexpr double kCarriedSlackM3 = 1.0e-9;

// A point `s` metres along a path of points.
std::array<double, 2> pointAlong(const std::vector<std::array<double, 2>> &path, double s) {
    for (std::size_t k = 1; k < path.size(); ++k) {
        const double dx = path[k][0] - path[k - 1][0], dz = path[k][1] - path[k - 1][1];
        const double len = std::hypot(dx, dz);
        if (s <= len || k + 1 == path.size()) {
            const double t = len > 0.0 ? std::clamp(s / len, 0.0, 1.0) : 0.0;
            return {path[k - 1][0] + t * dx, path[k - 1][1] + t * dz};
        }
        s -= len;
    }
    return path.empty() ? std::array<double, 2>{0.0, 0.0} : path.front();
}

// The river network beyond the edges, for a picture of it (docs/watershed.md):
// where each connection meets it -- the end columns of its span in world
// metres, and which edge -- where each basin and junction stands and how big
// it is drawn (a square of its surface's area), and each reach's course cut at
// its cells' boundaries with the bed under each cell. Where a scene says where
// they are, that; where it does not, a reach at a connection runs straight out
// from the middle of the span, and a basin stands where its reach ends -- or,
// met at the edge itself, just beyond it.
nlohmann::json beyondBlock(const banjo::terrain::Environment &env) {
    nlohmann::json beyond = {{"connections", nlohmann::json::array()}, {"basins", nlohmann::json::array()},
                             {"junctions", nlohmann::json::array()}, {"reaches", nlohmann::json::array()}};
    const banjo::water::RiverNetwork *net = env.network();
    if (env.water() == nullptr || net == nullptr) return beyond;
    const banjo::terrain::Grid &g = env.terrain().grid();
    static constexpr const char *kEdge[] = {"west", "east", "south", "north"};
    using Point = std::array<double, 2>;
    const std::size_t nodes = net->nodes().size(), reaches = net->reaches().size();
    std::vector<Point> node_at(nodes);
    std::vector<bool> node_placed(nodes, false);
    std::vector<double> node_side(nodes);
    for (std::size_t k = 0; k < nodes; ++k) {
        const banjo::water::RiverNetwork::Node &n = net->nodes()[k];
        node_side[k] = std::sqrt(std::max(1.0, n.storage.area(n.level_m)));
        if (n.x_m != 0.0 || n.z_m != 0.0) {
            node_at[k] = {n.x_m, n.z_m};
            node_placed[k] = true;
        }
    }
    std::vector<std::vector<Point>> path(reaches);
    for (std::size_t k = 0; k < reaches; ++k)
        for (const auto &p : net->reaches()[k].path_m) path[k].push_back({p.first, p.second});
    for (const auto &link : env.links()) {
        const banjo::water::Connection &span =
            env.water()->connections()[static_cast<std::size_t>(link.connection)];
        const auto at = [&](int k) -> Point {
            switch (span.edge) {
            case banjo::water::Edge::West: return {g.x0, g.z0 + k * g.dx};
            case banjo::water::Edge::East: return {g.x0 + (g.nx - 1) * g.dx, g.z0 + k * g.dx};
            case banjo::water::Edge::South: return {g.x0 + k * g.dx, g.z0};
            case banjo::water::Edge::North: return {g.x0 + k * g.dx, g.z0 + (g.nz - 1) * g.dx};
            }
            return {0.0, 0.0};
        };
        const Point a = at(span.from), b = at(span.to), mid = {(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0};
        const Point out = span.edge == banjo::water::Edge::West ? Point{-1.0, 0.0}
                        : span.edge == banjo::water::Edge::East ? Point{1.0, 0.0}
                        : span.edge == banjo::water::Edge::South ? Point{0.0, -1.0} : Point{0.0, 1.0};
        nlohmann::json said = {{"name", link.name}, {"edge", kEdge[static_cast<int>(span.edge)]},
                               {"from_m", {a[0], a[1]}}, {"to_m", {b[0], b[1]}}};
        if (link.end.node != banjo::water::RiverNetwork::kOpen) {
            const std::size_t k = static_cast<std::size_t>(link.end.node);
            said["basin"] = net->nodes()[k].name;
            if (!node_placed[k]) {
                const double off = g.dx / 2.0 + node_side[k] / 2.0;
                node_at[k] = {mid[0] + out[0] * off, mid[1] + out[1] * off};
                node_placed[k] = true;
            }
        } else {
            const std::size_t k = static_cast<std::size_t>(link.end.reach);
            const banjo::water::RiverNetwork::Reach &r = net->reaches()[k];
            said["reach"] = r.name;
            said["end"] = link.end.at_to ? "to" : "from";
            if (path[k].empty()) {
                const Point far = {mid[0] + out[0] * r.length_m, mid[1] + out[1] * r.length_m};
                path[k] = link.end.at_to ? std::vector<Point>{far, mid} : std::vector<Point>{mid, far};
            }
        }
        beyond["connections"].push_back(said);
    }
    // Basins and junctions where their reaches end, then reaches between them.
    for (int pass = 0; pass < 4; ++pass)
        for (std::size_t k = 0; k < reaches; ++k) {
            const banjo::water::RiverNetwork::Reach &r = net->reaches()[k];
            for (const bool at_to : {false, true}) {
                const int node = at_to ? r.to : r.from;
                if (node == banjo::water::RiverNetwork::kOpen || path[k].size() < 2) continue;
                const std::size_t n = static_cast<std::size_t>(node);
                if (node_placed[n]) continue;
                const Point end = at_to ? path[k].back() : path[k].front();
                const Point next = at_to ? path[k][path[k].size() - 2] : path[k][1];
                const double len = std::max(1e-9, std::hypot(end[0] - next[0], end[1] - next[1]));
                const double off = node_side[n] / 2.0;
                node_at[n] = {end[0] + (end[0] - next[0]) / len * off, end[1] + (end[1] - next[1]) / len * off};
                node_placed[n] = true;
            }
            if (path[k].empty() && r.from != banjo::water::RiverNetwork::kOpen &&
                r.to != banjo::water::RiverNetwork::kOpen && node_placed[static_cast<std::size_t>(r.from)] &&
                node_placed[static_cast<std::size_t>(r.to)])
                path[k] = {node_at[static_cast<std::size_t>(r.from)], node_at[static_cast<std::size_t>(r.to)]};
        }
    for (std::size_t k = 0; k < nodes; ++k) {
        const banjo::water::RiverNetwork::Node &n = net->nodes()[k];
        if (!node_placed[k]) continue;
        beyond[n.junction ? "junctions" : "basins"].push_back(
            {{"name", n.name}, {"at_m", {node_at[k][0], node_at[k][1]}}, {"side_m", node_side[k]},
             {"bed_m", n.storage.bottom()}});
    }
    for (std::size_t k = 0; k < reaches; ++k) {
        const banjo::water::RiverNetwork::Reach &r = net->reaches()[k];
        if (path[k].size() < 2) continue;
        double along = 0.0;
        for (std::size_t p = 1; p < path[k].size(); ++p)
            along += std::hypot(path[k][p][0] - path[k][p - 1][0], path[k][p][1] - path[k][p - 1][1]);
        nlohmann::json points = nlohmann::json::array(), beds = nlohmann::json::array();
        for (int c = 0; c <= r.cells; ++c) {
            const Point p = pointAlong(path[k], along * c / r.cells);
            points.push_back({p[0], p[1]});
        }
        for (const double b : r.bed_m) beds.push_back(b);
        beyond["reaches"].push_back({{"name", r.name}, {"width_m", r.width_m}, {"cells", r.cells},
                                     {"length_m", r.length_m}, {"points_m", points}, {"bed_m", beds}});
    }
    return beyond;
}

nlohmann::json terrainBlock(const banjo::terrain::Environment &env, const std::vector<float> &heights, double objects_kg) {
    const banjo::terrain::Grid &g = env.terrain().grid();
    const std::vector<std::uint8_t> ground = env.surfaces();
    const banjo::terrain::Landscape &land = env.landscape();
    return {{"kind", land.kind},
            {"beyond", beyondBlock(env)},
            {"carried", carriedJson(env, objects_kg)},
            {"grid", {{"nx", g.nx}, {"nz", g.nz}, {"cell_m", g.dx}, {"x0_m", g.x0}, {"z0_m", g.z0}}},
            {"chunks", {env.terrain().chunksX(), env.terrain().chunksZ()}},
            {"heights_b64", banjo::terrain::encodeBase64(heights.data(), heights.size() * sizeof(float))},
            {"ground_b64", banjo::terrain::encodeBase64(ground.data(), ground.size())},
            {"view", {{"eye_m", {land.eye_m[0], land.eye_m[1], land.eye_m[2]}},
                      {"look_m", {land.look_m[0], land.look_m[1], land.look_m[2]}}}}};
}

nlohmann::json waterBlock(const banjo::terrain::Environment &env, double t) {
    const banjo::water::ShallowWater &w = *env.water();
    // Surfaces are sent in millimetres above the floor under all the rock: it
    // never moves, so nothing is scanned to find it (the lowest ground was
    // looked for across the whole valley, four times a second).
    const double base = env.terrain().floor();
    // Only the columns that hold water are looked at for the picture; the
    // volume, which the ledger needs exact, is summed once, not twice.
    const banjo::terrain::Environment::WaterBox box = env.waterBox(base);
    const double volume = w.volume();
    nlohmann::json out = {{"t", t}, {"base_m", base}, {"volume_m3", tidy(volume)},
                          {"wet_cells", box.wet_cells}, {"active_cells", w.stats().active_cells},
                          {"in_m3_s", tidy(w.inflowRate())}, {"out_m3_s", tidy(w.outflowRate())},
                          {"residual_m3", w.residualFor(volume)}};
    if (const banjo::water::RiverNetwork *net = env.network()) {
        // The river network beyond the edges, and one account for all the
        // water: this region's and the network's, against what was there plus
        // everything fed from beyond the world less everything let go to it.
        // What crossed between them is in both ledgers with opposite signs.
        nlohmann::json basins = nlohmann::json::array(), junctions = nlohmann::json::array();
        nlohmann::json reaches = nlohmann::json::array();
        for (const auto &n : net->nodes())
            (n.junction ? junctions : basins)
                .push_back({{"name", n.name}, {"level_m", tidy(n.level_m)}, {"volume_m3", tidy(n.volume_m3)},
                            {"fed_m3_s", tidy(n.fed_m3_s)}, {"out_m3_s", tidy(n.out_rate_m3_s)},
                            {"across_m3_s", tidy(n.across_rate_m3_s)},
                            {"from_reaches_m3_s", tidy(n.from_reaches_rate_m3_s)}});
        for (const auto &r : net->reaches()) {
            nlohmann::json levels = nlohmann::json::array();
            for (const double level : r.level_m) levels.push_back(tidy(level));
            reaches.push_back({{"name", r.name}, {"level_m", levels}, {"in_m3_s", tidy(r.q_m3_s.front())},
                               {"middle_m3_s", tidy(r.q_m3_s[r.q_m3_s.size() / 2])},
                               {"out_m3_s", tidy(r.q_m3_s.back())}, {"froude", tidy(r.froude_now)}});
        }
        const banjo::water::Ledger &wl = w.ledger();
        const banjo::water::RiverNetwork::Totals totals = net->totals();
        const double held = volume + net->volume();
        const double expected = wl.initial_m3 + wl.inflow_m3 - wl.outflow_m3 + wl.added_m3 + wl.numerical_m3 +
                                totals.initial_m3 + totals.fed_m3 - totals.out_m3 + totals.numerical_m3;
        out["basins"] = basins;
        out["junctions"] = junctions;
        out["reaches"] = reaches;
        out["all_unaccounted_m3"] = held - expected;
    }
    if (box.ni == 0) {
        out["box"] = {0, 0, 0, 0};
        return out;
    }
    out["box"] = {box.i0, box.j0, box.ni, box.nj};
    out["surface_mm_b64"] = banjo::terrain::encodeBase64(box.surface_mm.data(), box.surface_mm.size() * 2);
    out["flow_b64"] = banjo::terrain::encodeBase64(box.flow.data(), box.flow.size());
    return out;
}

// The ground and the water into a reply. `whole` sends the ground whole and the
// water regardless of when it last went.
void addEnvironment(LiveWorld &world, nlohmann::json &reply, bool whole) {
    const banjo::terrain::Environment *env = world.environment();
    if (env == nullptr) return;
    reply["carried"]=carriedJson(*env, world.carriedObjectsKg());
    // The ground whole when a world opens; afterwards only the rectangle an
    // edit or a slump changed since the last reply, as the ground itself
    // keeps it -- nothing copied or compared when nothing changed. Every reply
    // used to copy all of the valley's heights and compare them.
    const banjo::terrain::TerrainField::Rect changed = world.takeChangedGround();
    if (whole) {
        reply["terrain"] = terrainBlock(*env, env->heights(), world.carriedObjectsKg());
    } else {
        const banjo::terrain::TerrainField &field = env->terrain();
        const banjo::terrain::Grid &g = field.grid();
        const int i0 = changed.i0, j0 = changed.j0, ni = changed.ni, nj = changed.nj;
        if (ni > 0 && nj > 0) {
            std::vector<float> rect(static_cast<std::size_t>(ni) * nj);
            std::vector<std::uint8_t> rect_ground(rect.size());
            for (int j = 0; j < nj; ++j)
                for (int i = 0; i < ni; ++i) {
                    const std::size_t c = g.at(i0 + i, j0 + j);
                    rect[static_cast<std::size_t>(j) * ni + i] = static_cast<float>(field.height(c));
                    rect_ground[static_cast<std::size_t>(j) * ni + i] = static_cast<std::uint8_t>(field.surface(c));
                }
            reply["terrain_changed"] = {
                {"box", {i0, j0, ni, nj}},
                {"heights_b64", banjo::terrain::encodeBase64(rect.data(), rect.size() * sizeof(float))},
                {"ground_b64", banjo::terrain::encodeBase64(rect_ground.data(), rect_ground.size())}};
        }
    }
    const double t = world.time_s();
    if (whole || t - water_sent_at >= kWaterEveryS - 1.0e-9) {
        reply["water"] = waterBlock(*env, t);
        water_sent_at = t;
    }
}

nlohmann::json dugJson(const banjo::terrain::EditEffect &effect) {
    // depth_m is how deep it went, unrounded: a room keeps the dig at that depth,
    // and made again from it the dig takes out the same. `limited` says it went
    // less deep than it was asked to, because no more could be carried.
    return {{"sand_m3", tidy(effect.edit.moved.sand_m3)}, {"soil_m3", tidy(effect.edit.moved.soil_m3)},
            {"kg", tidy(effect.edit.mass_kg)}, {"columns", effect.edit.cells.size()},
            {"depth_m", effect.edit.depth_m}, {"limited", effect.edit.limited},
            {"chunks_rebuilt", effect.chunks_rebuilt}, {"rebuild_ms", tidy(effect.rebuild_ms)},
            {"bodies_woken", effect.bodies_woken}};
}

} // namespace

int main(int argc, char **argv) {
    try {
        TileImpactRequest request;
        request.cell_size_m = 0.02;
        // CUDA is the request default and most builds do not have it; the
        // playground asks for the parallel CPU lane and so does this.
        request.backend = BackendKind::CpuParallel;
        // A saved world to open the scene into (LiveWorld::snapshot), if any,
        // and what of it to carry into a scene that has changed since.
        std::string snapshot_path, carry_path;
        for (int i = 1; i < argc; ++i) {
            const std::string option = argv[i];
            const auto value = [&]() -> std::string {
                if (i + 1 >= argc) throw std::invalid_argument(option + " needs a value");
                return argv[++i];
            };
            if (option == "--scene") {
                // Once. value() walks the argument list forward, so asking it
                // twice eats the next option's value and the engine is handed
                // "0.02" as though it were a flag.
                const std::string path = value();
                request.bodies = readSceneFile(path);
                // The same settings the C face reads, so a scene behaves the
                // same whichever way it reaches the engine.
                std::ifstream input(path);
                if (input)
                    readSceneSettings(std::string(std::istreambuf_iterator<char>(input),
                                                  std::istreambuf_iterator<char>()), request);
            }
            else if (option == "--cell") request.cell_size_m = std::stod(value());
            else if (option == "--ground-material") request.ground_material = presetFromName(value());
            else if (option == "--snapshot") snapshot_path = value();
            else if (option == "--carry") carry_path = value();
            else throw std::invalid_argument("unknown option: " + option);
        }
        if (request.bodies.empty()) throw std::invalid_argument("a live world needs --scene");
        if (!carry_path.empty() && snapshot_path.empty())
            throw std::invalid_argument("--carry says what to carry of a saved world, and there is no --snapshot");

        std::unique_ptr<LiveWorld> world;
        if (snapshot_path.empty()) {
            world = LiveWorld::open(request);
        } else {
            // The scene opened again as a saved world left it. One that does
            // not fit, or will not read, opens the scene as it is, and the
            // opening reply says so (`restored`).
            std::ifstream saved(snapshot_path, std::ios::binary);
            if (!saved) throw std::invalid_argument("cannot read the saved world " + snapshot_path);
            std::string text{std::istreambuf_iterator<char>(saved), std::istreambuf_iterator<char>()};
            if (carry_path.empty()) {
                world = LiveWorld::open(request, text);
            } else {
                // Carried into a scene that has changed since it was saved,
                // thing by thing: what the host still declares is in the file.
                std::ifstream asked(carry_path, std::ios::binary);
                if (!asked) throw std::invalid_argument("cannot read what to carry, " + carry_path);
                const nlohmann::json carry = nlohmann::json::parse(
                    std::string(std::istreambuf_iterator<char>(asked), std::istreambuf_iterator<char>()));
                world = LiveWorld::open(request, text, carryFrom(carry));
            }
        }
        // The opening state, so a host can draw the scene before it moves --
        // the ground and the water whole, if it has them.
        {
            nlohmann::json opening = describe(*world, true);
            addEnvironment(*world, opening, true);
            if (!snapshot_path.empty()) {
                // Opened again from a saved world, it already has its pins,
                // edges and points -- where they were, not where the scene
                // first put them -- and its batteries and motors, so the
                // opening says them, as a poses reply does, for a host that
                // must not declare them again. Without its machines here, a
                // host that opened a hoist again could not find its motor
                // until the first step.
                opening["restored"] = restoredJson(world->restored());
                opening["joints"] = jointsOf(*world);
                opening["blades"] = bladesOf(*world);
                opening["tool_points"] = toolPointsOf(*world);
                if (nlohmann::json machines = machinesOf(*world); !machines.is_null())
                    opening["machines"] = std::move(machines);
            }
            std::cout << opening.dump() << std::endl;
        }
        world->forgetDelays();
        world->forgetCuts();

        std::string line;
        while (std::getline(std::cin, line)) {
            if (line.empty()) continue;
            nlohmann::json reply;
            try {
                const nlohmann::json command = nlohmann::json::parse(line);
                const std::string op = command.value("op", std::string());
                if (op == "quit") break;
                // Set by whatever produced new bodies this line, so the
                // reply carries their shape as well as their place.
                bool made_bodies = false;
                if (op == "step") {
                    const double dt = command.value("dt", 1.0 / 60.0);
                    // Where the hand is, if the caller is carrying something.
                    //
                    // Sent with the step rather than as its own command because
                    // a round trip to this process is 14.9 ms and four steps of
                    // physics are 0.5 ms -- so a host that moves the hand and
                    // then steps pays TWICE the transport to do one frame's
                    // work, and halves its frame rate for as long as it is
                    // carrying anything. Measured, not guessed: the step itself
                    // is 0.03 ms.
                    // Which way it should face, for something wielded: the
                    // hand turns it there with the torque it has.
                    if (command.contains("hand_q")) {
                        const auto &q = command.at("hand_q");
                        if (!q.is_array() || q.size() != 4)
                            throw std::invalid_argument("hand_q needs four numbers, w first");
                        world->aimHeld(Quat{q[0].get<double>(), q[1].get<double>(),
                                            q[2].get<double>(), q[3].get<double>()});
                    }
                    if (command.contains("hand")) world->moveHeld(readVec(command, "hand"));
                    const int count = std::max(1, command.value("n", 1));
                    // A fresh batch: what follows is what this call reports.
                    world->forgetImpacts();
                    // Stop early on a step that was taken back: the world is
                    // one step short of an impact and the host has a decision
                    // to make before time moves again.
                    //
                    // The test is AFTER the step, not before it. Testing first
                    // meant that once a step had been taken back the loop never
                    // ran again -- and since step() is what clears the flag,
                    // nothing could ever clear it. The world froze permanently
                    // at the instant of the first refusal, whatever the host
                    // did about it.
                    for (int s = 0; s < count; ++s) {
                        world->step(dt);
                        // A step taken back is the world asking the host to
                        // decide, and the batch stops so it can. Unless
                        // something is already being worked out: then the break
                        // was captured by the engine and the next step takes.
                        // Stopping there spent a whole round trip per break,
                        // and a cascade has dozens of them -- the world fell
                        // behind by one break per reply for as long as the
                        // pieces kept landing.
                        if (world->steppedBack() && !world->fracturePending()) break;
                    }
                    // A fracture that was started without waiting is collected
                    // here, the first step after its answer is ready.
                    if (world->fracturePending() && world->fractureReady()) {
                        const std::string what = world->fractureSubject();
                        reply["pieces"] = world->finishFracture();
                        reply["finished"] = what;
                        // The pieces are new and a piece's cells ARE its
                        // surface, so this reply has to carry them. Waiting for
                        // a fracture used to mean the fracture's own reply
                        // carried the shape; not waiting means it lands on a
                        // step instead, and a step does not normally carry
                        // shape. Without this every shard is drawn as a box
                        // around itself, which is a lie about what broke.
                        made_bodies = true;
                        reply["outcome"] = std::array<const char *, 4>{
                            "nothing", "held", "dented", "broke"}
                            [static_cast<std::size_t>(world->lastOutcome())];
                        if (nlohmann::json cost = costOf(world->lastBreak()); !cost.is_null())
                            reply["cost"] = std::move(cost);
                    }
                } else if (op == "snapshot") {
                    // The whole world as it stands, for opening again after a
                    // restart (LiveWorld::snapshot). Lean, like `collect`: it
                    // changes nothing, and the world it describes is itself. A
                    // refusal is an answer -- something is under way that a
                    // saved world cannot carry -- not a failure.
                    std::string why;
                    const std::string saved = world->snapshot(why, command.value("spec_digest", std::string{}));
                    nlohmann::json answer{{"ok", true}};
                    if (saved.empty())
                        answer["refused"] = why;
                    else
                        answer["snapshot"] = nlohmann::json::parse(saved);
                    std::cout << answer.dump() << std::endl;
                    continue;
                } else if (op == "foresee") {
                    // How far ahead to look, in seconds. Zero is off, which is
                    // what a caller comparing the two paths wants.
                    world->foreseeCollisions(command.value("horizon_s", 2.5));
                } else if (op == "collect") {
                    // Loose pieces near a point, out of the world and into
                    // whatever the host wants to do with them. A room that
                    // shatters fills up, and past the body budget the step
                    // cannot be taken back, which is what breaking needs --
                    // so sweeping the floor is also how the room keeps working.
                    const std::vector<LiveCollected> haul = world->collect(
                        readVec(command, "at"), command.value("radius_m", 1.0),
                        static_cast<std::size_t>(command.value("largest_cells", 64)));
                    nlohmann::json got = nlohmann::json::array();
                    for (const LiveCollected &what : haul)
                        got.push_back({{"material", what.material},
                                       {"kg", tidy(what.kilograms)},
                                       {"pieces", what.pieces},
                                       {"cells", what.cells},
                                       {"took", what.took}});
                    reply["ok"] = true;
                    reply["collected"] = std::move(got);
                    // Lean, like `pick`. A sweep is asked for whenever there is
                    // debris underfoot, and carrying the world along with each
                    // answer would put back exactly the cost that trimming the
                    // step reply took out. The host does not need it: every
                    // body that went is named in `took`, which is all it has to
                    // remove -- and the next step reply lists them in `gone`
                    // anyway, which is harmless because they are already gone.
                    std::cout << reply.dump() << std::endl;
                    continue;
                } else if (op == "park") {
                    // Set a body aside, out of the world, kept as it is
                    // (LiveWorld::park): the next reply names it gone.
                    std::string why;
                    const std::string name = command.at("name").get<std::string>();
                    if (!world->park(name, why)) throw std::invalid_argument(why);
                    reply["parked"] = name;
                } else if (op == "unpark") {
                    // And back, at rest, at `at` facing `q` (w, x, y, z) -- as a
                    // reply's position_m and orientation_wxyz say a body is.
                    std::string why;
                    const std::string name = command.at("name").get<std::string>();
                    Quat facing{1.0, 0.0, 0.0, 0.0};
                    if (command.contains("q")) {
                        const auto &q = command.at("q");
                        facing = Quat{q.at(0).get<double>(), q.at(1).get<double>(),
                                      q.at(2).get<double>(), q.at(3).get<double>()};
                    }
                    if (!world->unpark(name, readVec(command, "at"), facing, why))
                        throw std::invalid_argument(why);
                    reply["unparked"] = name;
                } else if (op == "grab") {
                    if (!world->grab(command.at("name").get<std::string>()))
                        throw std::invalid_argument("that object cannot be picked up");
                } else if (op == "wield") {
                    // A grip, not a carry: a bounded force at the grip and a
                    // bounded torque. Without a grip given, a body that carries
                    // an edge is held where its blade says it is held.
                    const std::string name = command.at("name").get<std::string>();
                    Vec3 grip{};
                    bool have_grip = command.contains("grip");
                    if (have_grip) grip = readVec(command, "grip");
                    for (const LiveBlade &blade : world->blades())
                        if (!have_grip && blade.body == name && blade.attached) {
                            grip = blade.grip_m;
                            have_grip = true;
                        }
                    if (!have_grip)
                        throw std::invalid_argument("wield needs a grip, or a body with an edge");
                    if (!world->wield(name, grip))
                        throw std::invalid_argument("that object cannot be taken hold of");
                    reply["wielding"] = name;
                } else if (op == "hand") {
                    if (command.contains("strength_n"))
                        world->setHandStrength(command.at("strength_n").get<double>());
                    if (command.contains("torque_n_m"))
                        world->setHandTorque(command.at("torque_n_m").get<double>());
                    if (command.contains("mass_kg"))
                        world->setHandMass(command.at("mass_kg").get<double>());
                    reply["strength_n"] = world->handStrength();
                    reply["torque_n_m"] = world->handTorque();
                    reply["mass_kg"] = world->handMass();
                } else if (op == "stroke") {
                    // A motion the hand makes by itself, at the step's own rate
                    // (LiveStroke). The reply's `hand` says how it goes.
                    std::string why;
                    if (!world->stroke(readStroke(command), why))
                        throw std::invalid_argument(why);
                    reply["stroking"] = true;
                } else if (op == "cancel_stroke") {
                    world->cancelStroke();
                } else if (op == "preview_stroke") {
                    // What the throw would do, and where the thing would fly.
                    // Changes nothing, so it answers on its own, like `pick`.
                    //
                    // Always a THROW, whatever the line says about let_go, as
                    // banjo_preview_stroke is: a hand that keeps hold at the end
                    // has no flight. Read as a stroke, with stroke's default of
                    // false, a line without let_go was previewed as a hand
                    // slowing to arrive at the end, and the room drew its aim
                    // from that -- measured, a ball the arc said would leave at
                    // 4.7 m/s left at 14.7.
                    LiveStroke asked = readStroke(command);
                    asked.let_go_at_end = true;
                    const LiveStrokePreview seen = world->previewStroke(
                        asked, command.value("dt", 1.0 / 240.0), command.value("horizon_s", 3.0));
                    nlohmann::json answer{{"ok", true}, {"possible", seen.possible},
                                          {"why", seen.why}, {"reaches_end", seen.reaches_end},
                                          {"stroke_s", tidy(seen.stroke_s)},
                                          {"work_j", tidy(seen.work_j)},
                                          {"let_go_at_m", vec(seen.let_go_at_m)},
                                          {"let_go_velocity_m_s", vec(seen.let_go_velocity_m_s)},
                                          {"flight", flightJson(seen.flight)}};
                    std::cout << answer.dump() << std::endl;
                    continue;
                } else if (op == "preview_flight") {
                    nlohmann::json answer = flightJson(world->previewFlight(
                        readVec(command, "from"), readVec(command, "velocity"),
                        command.value("horizon_s", 3.0),
                        command.value("ignoring", std::string())));
                    answer["ok"] = true;
                    std::cout << answer.dump() << std::endl;
                    continue;
                } else if (op == "blade") {
                    // Give a body an edge. See docs/cutting-model.md: nothing
                    // here is a cutting power; what the edge does is decided by
                    // its geometry, the materials and the motion.
                    const unsigned id = world->blade(
                        command.at("body").get<std::string>(), readVec(command, "heel"),
                        readVec(command, "tip"), readVec(command, "facing"),
                        command.value("thickness_m", 0.01),
                        command.value("edge_radius_m", 0.0002),
                        command.value("bevel_deg", 30.0),
                        command.contains("grip") ? readVec(command, "grip")
                                                 : readVec(command, "heel"));
                    if (id == 0)
                        throw std::invalid_argument("that body cannot take that edge: " +
                                                    world->bladeRefusal());
                    reply["blade"] = id;
                } else if (op == "blades") {
                    std::cout << nlohmann::json{{"ok", true}, {"blades", bladesOf(*world)}}.dump()
                              << std::endl;
                    continue;
                } else if (op == "cuts") {
                    nlohmann::json list = nlohmann::json::array();
                    for (const LiveCut &cut : world->cuts()) list.push_back(cutJson(cut));
                    world->forgetCuts();
                    std::cout << nlohmann::json{{"ok", true}, {"cuts", std::move(list)}}.dump()
                              << std::endl;
                    continue;
                } else if (op == "tool_point") {
                    // A point that can go into the ground. docs/ground-work.md:
                    // what the ground does about it is decided by the ground's
                    // own materials and the point's shape, never by a name.
                    const unsigned id = world->toolPoint(
                        command.at("body").get<std::string>(), readVec(command, "tip"),
                        readVec(command, "pointing"), command.value("width_m", 0.04),
                        command.value("thickness_m", 0.04), command.value("angle_deg", 30.0),
                        command.value("length_m", 0.15),
                        command.contains("grip") ? readVec(command, "grip") : readVec(command, "tip"));
                    if (id == 0)
                        throw std::invalid_argument("that body cannot take that point: " +
                                                    world->toolPointRefusal());
                    reply["tool_point"] = id;
                } else if (op == "tool_points") {
                    std::cout << nlohmann::json{{"ok", true}, {"tool_points", toolPointsOf(*world)}}.dump()
                              << std::endl;
                    continue;
                } else if (op == "strike") {
                    // A bounded tool action: the hand makes it at the step's own
                    // rate; what it does to the ground is the ground's.
                    std::string why;
                    if (!world->strike(readStrike(command), why)) throw std::invalid_argument(why);
                    reply["striking"] = true;
                } else if (op == "ground_work") {
                    nlohmann::json list = nlohmann::json::array();
                    for (const LiveGroundWork &w : world->groundWork()) list.push_back(groundWorkJson(w));
                    world->forgetGroundWork();
                    nlohmann::json answer{{"ok", true}, {"ground_work", std::move(list)}};
                    if (const banjo::terrain::Environment *env = world->environment(); env != nullptr)
                        answer["carried"] = carriedJson(*env, world->carriedObjectsKg());
                    std::cout << answer.dump() << std::endl;
                    continue;
                } else if (op == "move") {
                    world->moveHeld(readVec(command, "to"));
                } else if (op == "release") {
                    world->release();
                } else if (op == "fracture") {
                    const std::string what = command.at("name").get<std::string>();
                    const double window = command.value("window_s", 0.003);
                    // Without waiting, if the host says so. The run goes onto a
                    // worker, the pair is pinned where it is, and the reply
                    // comes straight back saying it is being worked out. A
                    // later step carries the answer. The host keeps stepping
                    // the whole time, so the room never stops -- which is the
                    // pause anyone watching actually complains about.
                    if (!command.value("wait", true) && world->beginFracture(what, window)) {
                        reply["working_on"] = what;
                        reply["pieces"] = 0;
                        reply["outcome"] = "working";
                    } else {
                        reply["pieces"] = world->fracture(what, window);
                        // What it turned out to be. A count of one cannot
                        // tell a thing that held from a thing that bent.
                        reply["outcome"] = std::array<const char *, 4>{
                            "nothing", "held", "dented", "broke"}
                            [static_cast<std::size_t>(world->lastOutcome())];
                        // And what it cost the thing that took the hit.
                        if (nlohmann::json cost = costOf(world->lastBreak()); !cost.is_null())
                            reply["cost"] = std::move(cost);
                    }
                } else if (op == "carry_limit") {
                    // How much dug ground the person can carry, from now
                    // (terrain::Environment::setCarryLimitKg). A host that says
                    // nothing has a world as it was: no limit.
                    // Moves nothing, so it answers on its own and carries no
                    // bodies: a host's picture of the room stays as it is.
                    world->setCarryLimitKg(command.at("kg").get<double>());
                    nlohmann::json out{{"ok", true}};
                    if (const banjo::terrain::Environment *env = world->environment())
                        out["carried"] = carriedJson(*env, world->carriedObjectsKg());
                    std::cout << out.dump() << std::endl;
                    continue;
                } else if (op == "decline") {
                    // Not asked about: this body has had its chance at this
                    // contact and the world goes on with it whole
                    // (LiveWorld::declineBreak). A step that would break
                    // something is taken back until the host answers, and a
                    // host that has seen what it came to see -- a table give
                    // under its load -- had no way to let the wreck fall
                    // without paying for a lattice run on every shard that
                    // landed on another.
                    world->declineBreak(command.at("name").get<std::string>());
                    reply["outcome"] = "declined";
                } else if (op == "hinge") {
                    // Hang one named thing off another. The pin is given where
                    // it is in the world right now and is kept in both bodies'
                    // own frames from then on, so the mechanism goes on working
                    // when the whole assembly is carried or turned over.
                    const unsigned pin = world->hinge(
                        command.at("a").get<std::string>(),
                        command.at("b").get<std::string>(),
                        readVec(command, "at"), readVec(command, "axis"),
                        command.value("lower_deg", -180.0),
                        command.value("upper_deg", 180.0),
                        command.value("friction_n_m", 0.0));
                    if (pin == 0)
                        throw std::invalid_argument(
                            "those two cannot be hung on a pin together");
                    reply["joint"] = pin;
                } else if (op == "slide") {
                    // A line two things move along. A portcullis in its
                    // grooves, a sliding door, a bolt across a door -- and,
                    // like a pin, nothing is played: a grate hauled up and let
                    // go falls, because gravity is still acting on a body that
                    // is free to move down its own axis.
                    const unsigned groove = world->slide(
                        command.at("a").get<std::string>(),
                        command.at("b").get<std::string>(),
                        readVec(command, "at"), readVec(command, "axis"),
                        command.value("lower_m", -1.0),
                        command.value("upper_m", 1.0),
                        command.value("friction_n", 0.0));
                    if (groove == 0)
                        throw std::invalid_argument(
                            "those two cannot be put in a groove together");
                    reply["joint"] = groove;
                } else if (op == "tie") {
                    // A rope. It pulls and it does not push, which is the one
                    // asymmetry that makes a rope a rope: below its length it
                    // does nothing at all, so slack is really slack.
                    const std::string member = madeOf(command);
                    const unsigned rope = world->tie(
                        command.at("a").get<std::string>(),
                        command.at("b").get<std::string>(),
                        readVec(command, "at_a"), readVec(command, "at_b"),
                        command.value("length_m", 0.0),
                        command.value("breaks_at_n", 0.0));
                    if (rope == 0)
                        throw std::invalid_argument("those two cannot be tied together");
                    if (!member.empty()) (void)world->setJointMember(rope, member);
                    reply["joint"] = rope;
                } else if (op == "reeve") {
                    // A hoist: a rope from one thing, over two fixed points, to
                    // another. `ratio` applies to B's run, so b moves 1/ratio as
                    // far and feels ratio times the tension -- hang the LOAD at
                    // b and a counterweight of load/ratio balances it.
                    const unsigned rove = world->reeve(
                        command.at("a").get<std::string>(),
                        command.at("b").get<std::string>(),
                        readVec(command, "at_a"), readVec(command, "at_b"),
                        readVec(command, "over_a"), readVec(command, "over_b"),
                        command.value("ratio", 1.0),
                        command.value("length_m", 0.0));
                    if (rove == 0)
                        throw std::invalid_argument("that rope cannot be rove");
                    reply["joint"] = rove;
                } else if (op == "fix") {
                    // A peg, a bracket, a catch, a locking bar. Two bodies held
                    // as one, with a strength along the axis and another across
                    // it. Release it with "unhinge" -- which is what a latch is.
                    // With "member", one of the two names: what it is MADE of,
                    // so heat changes what it can take (docs/thermal-mechanics.md).
                    const std::string member = madeOf(command);
                    // With comes_off_n it is one-way instead, like an arrow on
                    // a string: pushed freely, held lightly, off when pulled.
                    const double tension = command.value("holds_tension_n", 0.0);
                    const double comes_off = command.value("comes_off_n", 0.0);
                    if (!(comes_off >= 0.0))
                        throw std::invalid_argument(
                            "comes_off_n is newtons, zero (two-way) or more");
                    if (comes_off > 0.0 && tension > 0.0)
                        throw std::invalid_argument(
                            "a one-way fixing has no tension strength: what pulls it "
                            "off is comes_off_n");
                    const unsigned peg = world->fix(
                        command.at("a").get<std::string>(),
                        command.at("b").get<std::string>(),
                        readVec(command, "at"), readVec(command, "axis"),
                        tension, command.value("holds_shear_n", 0.0), comes_off);
                    if (peg == 0)
                        throw std::invalid_argument("those two cannot be fixed together");
                    if (!member.empty()) (void)world->setJointMember(peg, member);
                    reply["joint"] = peg;
                } else if (op == "spring") {
                    // An elastic element: a bow limb, a spring, a bent plank.
                    // A DECLARED linear model -- force is stiffness times
                    // extension, stored energy is half stiffness times
                    // extension squared -- validated in tests/elastic_tests.cpp
                    // against the work actually done drawing it.
                    const std::string member = madeOf(command);
                    const unsigned limb = world->spring(
                        command.at("a").get<std::string>(),
                        command.at("b").get<std::string>(),
                        readVec(command, "at_a"), readVec(command, "at_b"),
                        command.value("rest_m", 0.0),
                        command.value("stiffness_n_m", 1000.0),
                        command.value("damping_n_s_m", 0.0));
                    if (limb == 0)
                        throw std::invalid_argument("a spring cannot go between those two");
                    if (!member.empty()) (void)world->setJointMember(limb, member);
                    reply["joint"] = limb;
                } else if (op == "member") {
                    // Say which of a joint's two bodies it is made of, or ""
                    // to go back to the numbers it was declared with.
                    if (!world->setJointMember(command.at("joint").get<unsigned>(),
                                               command.value("member", std::string{})))
                        throw std::invalid_argument(
                            "a joint is made of one of its own two ends, and only a fixing, a "
                            "tie or a spring has a strength or a stiffness for heat to change");
                } else if (op == "mechanics") {
                    // What heat has done to what everything can carry, answered
                    // on its own like `thermo`: it moves nothing.
                    std::cout << nlohmann::json{{"ok", true},
                                                {"mechanics", nlohmann::json::parse(world->mechanicsReport(
                                                                  command.value("laws", false)))}}
                                     .dump()
                              << std::endl;
                    continue;
                } else if (op == "drum") {
                    // A rope that winds onto a turning drum (rigid/DrumRope.hpp):
                    // from the drum -- a thing on a pin of its own -- to a load,
                    // for as many turns as there is rope.
                    const unsigned rope = world->drum(
                        command.at("drum").get<std::string>(), command.at("load").get<std::string>(),
                        readVec(command, "centre"), readVec(command, "axis"), command.value("radius_m", 0.0),
                        readVec(command, "load_point"), command.value("winds", 1), command.value("length_m", 0.0),
                        command.value("out_m", 0.0));
                    if (rope == 0)
                        throw std::invalid_argument("that rope cannot go on that drum");
                    reply["joint"] = rope;
                } else if (op == "store") {
                    // A store of energy -- a battery -- in a named thing
                    // (docs/machine-world.md). Full unless it is said otherwise.
                    const double capacity = command.value("capacity_j", 0.0);
                    const unsigned store = world->energyStore(
                        command.value("name", std::string{}), command.value("body", std::string{}), capacity,
                        command.value("charge_j", capacity), command.value("voltage_v", 24.0),
                        command.value("max_power_w", 0.0));
                    if (store == 0)
                        throw std::invalid_argument(
                            "a store needs a thing that is here to be in, and a charge no more than it holds");
                    reply["store"] = store;
                } else if (op == "motor") {
                    // A motor on a pin, wired to a store: its stall torque and
                    // the speed it runs at unloaded, and the brake it holds with.
                    const unsigned motor = world->motor(
                        command.at("joint").get<unsigned>(), command.at("store").get<unsigned>(),
                        command.value("stall_torque_n_m", 0.0), command.value("no_load_rad_s", 0.0),
                        command.value("brake_torque_n_m", 0.0));
                    if (motor == 0)
                        throw std::invalid_argument(
                            "a motor goes on a pin with none, wired to a store, with a stall torque and an "
                            "unloaded speed above zero");
                    reply["motor"] = motor;
                } else if (op == "circuit") {
                    reply["circuit"] = world->circuit(command.at("network").dump());
                } else if (op == "circuit_switch") {
                    const auto &id = command.at("circuit");
                    if (!id.is_number_integer() || id.get<std::int64_t>() <= 0 ||
                        id.get<std::int64_t>() > std::numeric_limits<unsigned>::max())
                        throw std::invalid_argument("circuit must be a positive uint32 handle");
                    world->circuitSwitch(id.get<unsigned>(), command.at("branch").get<std::string>(),
                                         command.at("closed").get<bool>());
                } else if (op == "circuits") {
                    std::cout << nlohmann::json{{"ok", true},
                        {"circuits", nlohmann::json::parse(world->circuits())}}.dump() << std::endl;
                    continue;
                } else if (op == "drive") {
                    // What a motor is told: a command from -1 to 1, and its brake.
                    if (!world->driveMotor(command.at("motor").get<unsigned>(), command.value("command", 0.0),
                                           command.value("brake", false)))
                        throw std::invalid_argument("there is no such motor");
                } else if (op == "control") {
                    // A machine's controller (docs/machine-world.md, "Operating a
                    // machine"): a hoist's, on a motor and the rope on its drum,
                    // with the rope out at the two ends of its travel; or a
                    // shaft's, on a motor alone.
                    const unsigned control = world->control(
                        command.value("name", std::string{}), command.at("motor").get<unsigned>(),
                        command.value("rope", 0U), command.value("top_out_m", 0.0), command.value("bottom_out_m", 0.0));
                    if (control == 0)
                        throw std::invalid_argument(
                            "a controller goes on a motor that has none; a hoist's rope is on a drum the motor's pin "
                            "turns, and its travel runs from the rope out at the top to the rope out at the bottom, "
                            "the top the less and the bottom no more than the rope");
                    reply["control"] = control;
                } else if (op == "sense") {
                    // A sensor on a controller's machine (LiveSensor): of a kind
                    // ("water"), on a part at a point given where it is now,
                    // stopping the machine going one way when it reads deeper
                    // than depth_m.
                    // On a program's machine instead with "program": its side
                    // is worked out from where it is.
                    const nlohmann::json &at = command.at("at_m");
                    const Vec3 point{at.at(0).get<double>(), at.at(1).get<double>(), at.at(2).get<double>()};
                    const bool fitted =
                        command.contains("program")
                            ? world->programSense(command.at("program").get<unsigned>(),
                                                  command.value("kind", std::string{}),
                                                  command.value("body", std::string{}), point,
                                                  command.value("depth_m", 0.0))
                            : world->sense(command.at("control").get<unsigned>(), command.value("kind", std::string{}),
                                           command.value("body", std::string{}), point,
                                           command.value("depth_m", 0.0), command.value("stops", 1));
                    if (!fitted)
                        throw std::invalid_argument(
                            "a sensor goes on a controller or a program that is there, on a part that is in the "
                            "world: of kind \"water\", with a depth above nothing and no more than 10 m, stopping "
                            "the way 1 or -1");
                    reply["sensed"] = true;
                } else if (op == "sun" && command.contains("day_s")) {
                    // A sun with a day (LiveSun): how long the day is, how high
                    // the sun stands at noon, the hour it is now and how
                    // strongly it shines overhead. With "keep", a world that
                    // already has this very day -- one opened again from its
                    // save, or carried -- keeps the hour it has got to: its day
                    // goes on rather than starting again.
                    const double day_s = command.value("day_s", -1.0);
                    const double noon = command.value("noon_elevation_deg", -1.0);
                    const double irradiance = command.value("irradiance_w_m2", -1.0);
                    const LiveSun now = world->sun();
                    const bool kept = command.value("keep", false) && now.declared && now.day_s == day_s &&
                                      now.noon_elevation_deg == noon && now.zenith_irradiance_w_m2 == irradiance;
                    if (!kept && !world->setDay(day_s, noon, command.value("hour", -1.0), irradiance))
                        throw std::invalid_argument(
                            "a sun's day is at least 10 s long; at noon the sun stands above the horizon and no "
                            "higher than 90 degrees; the hour is from 0 up to 24; and it shines from 0 to 1400 "
                            "W/m2 overhead");
                    reply["sun"] = sunOf(world->sun());
                    reply["kept"] = kept;
                } else if (op == "sun") {
                    // The room's sun (LiveSun): where it stands in the sky and
                    // how strongly it shines.
                    if (!world->setSun(command.value("elevation_deg", -1.0), command.value("azimuth_deg", 0.0),
                                       command.value("irradiance_w_m2", -1.0)))
                        throw std::invalid_argument(
                            "a sun is from 0 to 90 degrees above the horizon, at any azimuth, shining from 0 to "
                            "1400 W/m2");
                    reply["sun"] = sunOf(world->sun());
                } else if (op == "solar_panel") {
                    // A solar panel (LiveSolarPanel) on a part, wired to a store:
                    // its middle and the way its face looks, given in the world.
                    const nlohmann::json &at = command.at("at_m");
                    const nlohmann::json &normal = command.at("normal");
                    const unsigned made = world->solarPanel(
                        command.value("name", std::string{}), command.value("body", std::string{}),
                        command.at("store").get<unsigned>(),
                        Vec3{at.at(0).get<double>(), at.at(1).get<double>(), at.at(2).get<double>()},
                        Vec3{normal.at(0).get<double>(), normal.at(1).get<double>(), normal.at(2).get<double>()},
                        command.value("area_m2", 0.0), command.value("efficiency", 0.0));
                    if (made == 0)
                        throw std::invalid_argument(
                            "a solar panel goes on a part that is in the world, wired to a store that is there, "
                            "with a face that looks some way, an area above 0 and up to 100 m2, and an efficiency "
                            "above 0 and at most 1");
                    reply["solar_panel"] = made;
                } else if (op == "program") {
                    // A program for a machine (LiveProgram): of a kind ("roam"),
                    // working the controllers of its left and right wheels, on a
                    // body both turn on; it starts off.
                    const unsigned made = world->program(
                        command.value("name", std::string{}), command.value("kind", std::string{}),
                        command.at("left").get<unsigned>(), command.at("right").get<unsigned>(),
                        command.value("body", std::string{}), command.value("setting", 1.0),
                        command.value("climb_deg", 8.0), command.value("rest_below", 0.0),
                        command.value("rest_until", 0.0));
                    if (made == 0)
                        throw std::invalid_argument(
                            "a program is of kind \"roam\", on two shafts' controllers that no program works yet, "
                            "each on a pin through the body it names, with a setting above 0 and no more than 1, "
                            "a climb above 0 and below 60 degrees, and a rest_until above its rest_below and no "
                            "more than 1");
                    reply["program"] = made;
                } else if (op == "run") {
                    // A program turned on or off, by a sender and its count,
                    // answered as operate is, with the program as it now stands.
                    LiveWorld::ProgramCommand told;
                    told.sender = command.value("sender", std::string{});
                    told.seq = command.value("seq", std::uint64_t{0});
                    told.power = command.at("power").get<bool>();
                    const unsigned id = command.at("program").get<unsigned>();
                    const std::string answer = world->run(id, told);
                    if (answer != "applied" && answer != "stale") throw std::invalid_argument(answer);
                    reply["ran"] = answer;
                    const nlohmann::json machines = machinesOf(*world);
                    if (machines.is_object() && machines.contains("programs"))
                        for (const nlohmann::json &each : machines.at("programs"))
                            if (each.at("id") == id) reply["program"] = each;
                } else if (op == "operate") {
                    // What a controller is told, by a sender and its count --
                    // power, a direction, a drive setting, each only if given --
                    // answered "applied" or "stale", with the controller as it
                    // now stands: the acknowledgement a panel waits for.
                    LiveWorld::ControlCommand told;
                    told.sender = command.value("sender", std::string{});
                    told.seq = command.value("seq", std::uint64_t{0});
                    if (command.contains("power")) told.power = command.at("power").get<bool>();
                    if (command.contains("direction")) told.direction = command.at("direction").get<int>();
                    if (command.contains("setting")) told.setting = command.at("setting").get<double>();
                    const unsigned id = command.at("control").get<unsigned>();
                    const std::string answer = world->operate(id, told);
                    if (answer != "applied" && answer != "stale") throw std::invalid_argument(answer);
                    reply["operated"] = answer;
                    for (const LiveControl &c : world->controls())
                        if (c.id == id) reply["control"] = controlOf(c, world->motors(), world->joints(), *world);
                } else if (op == "unhinge") {
                    world->unhinge(command.at("joint").get<unsigned>());
                } else if (op == "joint_friction") {
                    // Newton metres for a pin, newtons for a slide; the joint
                    // knows which it is, so either spelling is accepted.
                    world->setJointFriction(
                        command.at("joint").get<unsigned>(),
                        command.contains("friction_n")
                            ? command.at("friction_n").get<double>()
                            : command.value("friction_n_m", 0.0));
                } else if (op == "joints") {
                    // Reports nothing about where the bodies are, so it answers
                    // on its own like `pick` does.
                    std::cout << nlohmann::json{{"ok", true},
                                                {"joints", jointsOf(*world)}}
                                     .dump()
                              << std::endl;
                    continue;
                } else if (op == "pick") {
                    // Changes nothing and reports nothing about the world, so
                    // it answers on its own rather than through describe().
                    const LivePick found = world->pick(readVec(command, "from"),
                                                       readVec(command, "dir"),
                                                       command.value("max_m", 1000.0));
                    nlohmann::json answer{{"ok", true}, {"hit", found.hit},
                                          {"name", found.name},
                                          {"distance_m", found.distance_m},
                                          {"point_m", vec(found.point_world_m)}};
                    std::cout << answer.dump() << std::endl;
                    continue;
                } else if (op == "place_check") {
                    // Where a thing would go set down on a surface, and whether
                    // it fits there (LiveWorld::placement): the page's
                    // see-through copy asks this while someone chooses where.
                    // Changes nothing, so it answers on its own, as pick does.
                    constexpr double kDegree = 3.14159265358979323846 / 180.0;
                    const LivePlacement p = world->placement(command.at("name").get<std::string>(),
                                                             readVec(command, "on"),
                                                             command.value("yaw_deg", 0.0) * kDegree,
                                                             command.value("onto", std::string{}),
                                                             command.value("square", true));
                    nlohmann::json touching = nlohmann::json::array();
                    for (const auto &[what, depth] : p.touching)
                        touching.push_back({{"name", what}, {"depth_mm", tidy(1000.0 * depth)}});
                    nlohmann::json answer{
                        {"ok", true}, {"fits", p.fits}, {"why", p.why}, {"at_m", vec(p.at_m)},
                        {"q", nlohmann::json::array({tidy(p.turn_wxyz[0]), tidy(p.turn_wxyz[1]),
                                                     tidy(p.turn_wxyz[2]), tidy(p.turn_wxyz[3])})},
                        {"facing", nlohmann::json::array({tidy(p.facing_wxyz[0]), tidy(p.facing_wxyz[1]),
                                                          tidy(p.facing_wxyz[2]), tidy(p.facing_wxyz[3])})},
                        {"rests_on", p.rests_on}, {"supported_corners", p.supported_corners},
                        {"tipping_used", tidy(p.tipping_used)}, {"may_fall_over", p.may_fall_over},
                        {"touching", std::move(touching)}};
                    std::cout << answer.dump() << std::endl;
                    continue;
                } else if (op == "heat") {
                    // Kindling, a torch, a stove: external work into a body or a
                    // gas region from now, and counted in the ledger. Whether
                    // it lights anything is the model's answer, not this one's.
                    reply["heater"] = world->heat(command.at("target").get<std::string>(),
                                                  command.value("power_w", 0.0),
                                                  command.value("seconds", 0.0));
                } else if (op == "declare") {
                    // Contents, gas regions and heaters into the running world.
                    world->declareThermo(command.at("json").dump());
                } else if (op == "vent") {
                    world->setVent(command.at("region").get<std::string>(),
                                   command.value("open", true));
                } else if (op == "thermo") {
                    // Everything about heat, chemistry and gas, answered on its
                    // own like `joints`: it moves nothing.
                    nlohmann::json report =
                        nlohmann::json::parse(world->thermoReport(command.value("model", false)));
                    report["ledger"]["mechanical_j"] = world->mechanicalEnergyJ();
                    // A declared mechanical loss beside it: what rolling
                    // resistance has taken out of the motion.
                    report["ledger"]["rolling_loss_j"] = world->rollingLossJ();
                    std::cout << nlohmann::json{{"ok", true}, {"thermo", std::move(report)}}.dump()
                              << std::endl;
                    continue;
                } else if (op == "dig") {
                    // A trench, or a pit. The ground loses what comes out and
                    // the reply says what it was; the colliders it changed are
                    // rebuilt now, and whatever they held up is woken.
                    const auto a = readXZ(command, "from");
                    const auto b = command.contains("to") ? readXZ(command, "to") : a;
                    // Carrying all that can be carried: said before the ground
                    // is touched, like a heap bigger than what is carried.
                    if (const banjo::terrain::Environment *env = world->environment();
                        env != nullptr && env->carryLimitKg() - env->carriedKg() < 0.05) {
                        char why[240];
                        std::snprintf(why, sizeof why,
                                      "you are carrying %.1f kg of sand and soil, and %.1f kg is all you can "
                                      "carry: heap some of it first",
                                      env->carriedKg(), env->carryLimitKg());
                        throw std::invalid_argument(why);
                    }
                    reply["dug"] = dugJson(world->dig(a.first, a.second, b.first, b.second,
                                                      command.value("width_m", 1.0),
                                                      command.value("depth_m", 0.5)));
                    // What came out is carried, and the reply says how much is.
                    reply["carried"] = carriedJson(*world->environment(), world->carriedObjectsKg());
                } else if (op == "ground_return") {
                    world->returnGround(command.at("sand_m3").get<double>(),command.at("soil_m3").get<double>());
                    reply["carried"] = carriedJson(*world->environment(), world->carriedObjectsKg());
                } else if (op == "ground_withdraw") {
                    reply["material_packet"] = nlohmann::json::parse(world->withdrawGround(
                        command.at("sand_m3").get<double>(),command.at("soil_m3").get<double>()));
                    reply["carried"] = carriedJson(*world->environment(), world->carriedObjectsKg());
                } else if (op == "deposit") {
                    const auto at = readXZ(command, "at");
                    const double sand = command.value("sand_m3", 0.0);
                    const double soil = command.value("soil_m3", 0.0);
                    // A heap a person makes is made of what they carry, and one
                    // bigger is refused before the ground is touched. A host
                    // building a scene heaps what it declares instead.
                    const banjo::terrain::Environment *env = world->environment();
                    if (env != nullptr && command.value("from_carried", false)) {
                        const banjo::terrain::Volumes &have = env->carried();
                        if (sand > have.sand_m3 + kCarriedSlackM3 || soil > have.soil_m3 + kCarriedSlackM3) {
                            char why[240];
                            std::snprintf(why, sizeof why,
                                          "ground does not come from nowhere: %.3f m3 of sand and %.3f m3 of "
                                          "soil are carried, and that heap is %.3f and %.3f",
                                          have.sand_m3, have.soil_m3, sand, soil);
                            throw std::invalid_argument(why);
                        }
                    }
                    reply["heaped"] = dugJson(world->deposit(at.first, at.second,
                                                             command.value("radius_m", 1.0), sand, soil));
                    reply["carried"] = carriedJson(*world->environment(), world->carriedObjectsKg());
                } else if (op == "cut_block") {
                    // The ground loses the block now; the host adds it as a body
                    // in the scene it opens next.
                    const auto at = readXZ(command, "at");
                    int cx = 4, cz = 4;
                    if (command.contains("cells")) {
                        cx = command.at("cells").at(0).get<int>();
                        cz = command.at("cells").at(1).get<int>();
                    }
                    std::string why;
                    const auto block = world->cutBlock(at.first, at.second, cx, cz,
                                                       command.value("height_m", 0.4), &why);
                    if (!block) throw std::invalid_argument(why.empty() ? "that block cannot be cut" : why);
                    reply["block"] = {{"center_m", vec(block->center_m)}, {"size_m", vec(block->size_m)},
                                      {"volume_m3", block->volume_m3}, {"kg", block->mass_kg}};
                } else if (op == "discharge") {
                    if (!world->setDischarge(command.at("river").get<std::string>(),
                                             command.value("discharge_m3_s", 0.0)))
                        throw std::invalid_argument("there is no river by that name");
                } else if (op == "survey") {
                    // Answers on its own, like `pick`: it changes nothing.
                    const auto at = readXZ(command, "at");
                    std::cout << nlohmann::json{{"ok", true},
                                                {"survey", nlohmann::json::parse(world->survey(at.first, at.second))}}
                                     .dump()
                              << std::endl;
                    continue;
                } else if (op == "materials") {
                    // What each material and surface rolls like, and where the
                    // numbers came from. Answers on its own: it moves nothing.
                    std::cout << nlohmann::json{{"ok", true},
                                                {"materials", nlohmann::json::parse(LiveWorld::materialsJson())}}
                                     .dump()
                              << std::endl;
                    continue;
                } else if (op == "rolling") {
                    std::cout << nlohmann::json{{"ok", true},
                                                {"rolling", nlohmann::json::parse(world->rollingReport())}}
                                     .dump()
                              << std::endl;
                    continue;
                } else if (op == "environment") {
                    std::cout << nlohmann::json{{"ok", true},
                                                {"environment", nlohmann::json::parse(world->environmentReport(
                                                                    command.value("full", false)))}}
                                     .dump()
                              << std::endl;
                    continue;
                } else if (op == "environment_state") {
                    std::cout << nlohmann::json{{"ok", true},
                                                {"state", nlohmann::json::parse(world->environmentState())}}
                                     .dump()
                              << std::endl;
                    continue;
                } else if (op == "terrain") {
                    nlohmann::json out{{"ok", true}};
                    addEnvironment(*world, out, true);
                    std::cout << out.dump() << std::endl;
                    continue;
                } else if (op != "poses" && op != "overloaded") {
                    // "overloaded" changes nothing and reports nothing about
                    // where anything is; it falls through to the ordinary reply
                    // below, which carries the survey whenever it has anything.
                    throw std::invalid_argument("unknown op: " + op);
                }
                // Pins travel with anything that rebuilt the room. A gate that
                // came off its hinges when its post was smashed is exactly the
                // sort of thing a host has to stop drawing, and it can only
                // learn that here.
                // Geometry travels with the opening state, with an explicit
                // poses request, and after a fracture -- the three moments the
                // set of bodies can have changed. A step never carries it --
                // except a piece's cells, when burning has changed them
                // (describe()).
                // A host that draws the room asks for only what moved. A
                // reply that carries geometry carries all of it regardless:
                // that is the reply that rebuilds the scene.
                const bool geometry = made_bodies || op == "poses" || op == "fracture";
                // Anything carrying more than it can hold up.
                //
                // Sent whenever there is something to send rather than on a
                // cache, because the list is almost always empty and it is the
                // one thing a host cannot work out for itself: a shelf at rest
                // under a pile of crates reports no contacts at all, so nothing
                // else in the reply hints that it is about to give.
                nlohmann::json sagging = nlohmann::json::array();
                for (const LiveOverload &load : world->overloaded())
                    sagging.push_back({{"name", load.name},
                                       {"carrying_n", tidy(load.carrying_n)},
                                       {"span_m", tidy(load.span_m)},
                                       {"stress_mpa", tidy(load.stress_pa / 1e6)},
                                       {"holds_mpa", tidy(load.strength_pa / 1e6)},
                                       {"capacity_fraction", tidy(load.capacity_fraction)},
                                       {"why", load.why}});
                if (!sagging.empty()) reply["overloaded"] = std::move(sagging);
                if (const banjo::thermo::ThermoWorld *network = world->thermo();
                    network != nullptr && network->active()) {
                    reply["heat"] = heatSummary(*network);
                    // Where the meltwater off ice has gone since the world
                    // opened, when any has.
                    const double into = world->meltwaterIntoWaterKg(), off = world->meltwaterRanOffKg();
                    if (into > 0.0 || off > 0.0)
                        reply["heat"]["meltwater"] = {{"into_water_kg", std::round(into / 1.0e-4) * 1.0e-4},
                                                      {"ran_off_kg", std::round(off / 1.0e-4) * 1.0e-4}};
                }
                // And what that heat has done to what things can carry.
                if (nlohmann::json strength = mechanicsSummary(*world); !strength.is_null())
                    reply["mechanics"] = std::move(strength);
                // Batteries, motors and ropes on drums, on every reply that has
                // any (machinesOf).
                if (nlohmann::json machines = machinesOf(*world); !machines.is_null())
                    reply["machines"] = std::move(machines);
                // A sun with a day, on every reply: it moves with the world's
                // clock, and the host lights the room from it.
                if (const LiveSun sun = world->sun(); sun.declared && sun.day_s > 0.0) reply["sun"] = sunOf(sun);
                // Pins travel when the SET of them changes -- one hung, one
                // taken out, one that came off because its wood was smashed --
                // and not on every tick. Their angles change every frame, but
                // the host already gets each body's pose, which is the same
                // fact in the form it actually draws; sending the pin's angle
                // sixty times a second would put back a slice of exactly the
                // traffic that trimming the step reply took out (259 KB to
                // 0.2 KB median, 7.8 MB/s to 0.6). What a host cannot work out
                // for itself is a gate coming off its hinges, so that is what
                // this sends.
                {
                    nlohmann::json pins = jointsOf(*world);
                    std::string shape;
                    for (const auto &pin : pins)
                        shape += std::to_string(pin.value("id", 0u)) + "/" +
                                 pin.value("a", std::string{}) + "/" +
                                 pin.value("b", std::string{}) + "/" +
                                 (pin.value("attached", false) ? "1" : "0") +
                                 // Or one gone into the bag with its thing,
                                 // or back out: the host stops drawing it.
                                 (pin.value("away", false) ? "a" : "") + ";";
                    if (shape != last_joints || geometry) {
                        last_joints = shape;
                        reply["joints"] = std::move(pins);
                    }
                }
                // The edges travel like the pins: when the set changes -- one
                // made, one whose body has gone -- or with anything that rebuilt
                // the room.
                {
                    nlohmann::json edges = bladesOf(*world);
                    std::string shape;
                    for (const auto &edge : edges)
                        shape += std::to_string(edge.value("id", 0u)) + "/" +
                                 edge.value("body", std::string{}) + "/" +
                                 (edge.value("attached", false) ? "1" : "0") + ";";
                    if (shape != last_blades || geometry) {
                        last_blades = shape;
                        reply["blades"] = std::move(edges);
                    }
                }
                // A tool's points, the same way: when the set changes.
                {
                    nlohmann::json points = toolPointsOf(*world);
                    std::string shape;
                    for (const auto &p : points)
                        shape += std::to_string(p.value("id", 0u)) + "/" + p.value("body", std::string{}) +
                                 "/" + (p.value("attached", false) ? "1" : "0") + ";";
                    if (shape != last_tool_points || geometry) {
                        last_tool_points = shape;
                        if (!points.empty() || geometry) reply["tool_points"] = std::move(points);
                    }
                }
                // And what points did in the ground since the last reply that
                // said so: the meetings that ended, and every open one, each
                // time -- a host follows a point in the ground by it. With the
                // carried account, which a meeting that broke ground out adds to.
                if (const std::vector<LiveGroundWork> work = world->groundWork(); !work.empty()) {
                    nlohmann::json list = nlohmann::json::array();
                    for (const LiveGroundWork &w : work) list.push_back(groundWorkJson(w));
                    reply["ground_work"] = std::move(list);
                    world->forgetGroundWork();
                    if (const banjo::terrain::Environment *env = world->environment(); env != nullptr)
                        reply["carried"] = carriedJson(*env, world->carriedObjectsKg());
                }
                nlohmann::json state = describe(*world, geometry,
                                                !geometry && command.value("moved", false));
                // The ground whole only when the host asks for the scene whole;
                // otherwise only what changed, and the water at its stride.
                addEnvironment(*world, state, op == "poses");
                world->forgetDelays();
                world->forgetCuts();
                for (auto &[key, value] : reply.items()) state[key] = value;
                std::cout << state.dump() << std::endl;
            } catch (const std::exception &error) {
                std::cout << nlohmann::json{{"ok", false}, {"error", error.what()}}.dump()
                          << std::endl;
            }
        }
        return 0;
    } catch (const std::exception &error) {
        std::cout << nlohmann::json{{"ok", false}, {"error", error.what()}}.dump() << std::endl;
        return 1;
    }
}
