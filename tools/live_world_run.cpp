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
//        {"op":"dig","from":[x,z],"to":[x,z],"width_m":1,"depth_m":0.5}
//                                            a trench (or a pit, from == to)
//        {"op":"deposit","at":[x,z],"radius_m":1,"sand_m3":0.5,"soil_m3":0}
//        {"op":"cut_block","at":[x,z],"cells":[4,4],"height_m":0.4}  a block of rock
//        {"op":"discharge","river":"the river","discharge_m3_s":0.5}
//        {"op":"survey","at":[x,z]}          ground and water at a point
//        {"op":"environment","full":false}   the ground, the water, their ledgers
//        {"op":"environment_state"}          the water, for carrying into a reopen
//        {"op":"terrain"}                    the whole ground again, for drawing
//        {"op":"blade","body":"sword","heel":[..],"tip":[..],"facing":[0,0,-1],
//         "thickness_m":0.01,"edge_radius_m":0.0002,"bevel_deg":30,"grip":[..]}
//                                            give a body an edge (docs/cutting-model.md)
//        {"op":"blades"}                     every edge, and what each has cut
//        {"op":"wield","name":"sword","grip":[..]}   a bounded hand on a grip
//        {"op":"step","n":4,"hand":[..],"hand_q":[w,x,y,z]}   where it wants the
//                                            grip, and which way it wants it to face
//        {"op":"hand","strength_n":800,"torque_n_m":60}   how strong the hand is
//        {"op":"cuts"}                       every edge contact since the last reply
//   out  {"ok":true,"t":0.033,"stepped_back":false,
//         "bodies":[{"name":"ball","shape":"sphere","dimensions_m":[...],
//                    "position_m":[...],"orientation_wxyz":[...],"held":false,
//                    "anchored":false,"color_rgba":"8a8f99ff"}],
//         "impacts":[{"struck":"pane","by":"ball","closing_speed_m_s":13.9,
//                     "threshold_speed_m_s":4.5,"would_break":true}],
//         "breakable":["pane"]}
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
#include <algorithm>
#include <fstream>
#include <array>
#include <iostream>
#include <iterator>
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
// And what the pins looked like last time, for the same reason. See where this
// is compared, below: the SET of pins is news, their angles are not.
std::string last_joints;

nlohmann::json vec(const Vec3 &v) {
    return nlohmann::json::array({tidy(v.x), tidy(v.y), tidy(v.z)});
}

// Every pin, as the host sees it. `a` and `b` are the names it holds, which do
// change: a pin whose wood is smashed follows the piece it ends up inside, so a
// gate that was hung on "post" can find itself hung on "post piece 3".
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
                          {"section_mm", nlohmann::json::array({roundTo(1000.0 * s.breadth_m, 0.1),
                                                                roundTo(1000.0 * s.depth_m, 0.1)})},
                          {"sound_mm", nlohmann::json::array({roundTo(1000.0 * s.sound_breadth_m, 0.1),
                                                              roundTo(1000.0 * s.sound_depth_m, 0.1)})},
                          {"supported", s.supported}});
    }
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
    if (bodies.empty() && held.empty()) return nullptr;
    return {{"bodies", std::move(bodies)}, {"attachments", std::move(held)}};
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
    nlohmann::json bodies = nlohmann::json::array();
    std::unordered_set<std::string> present;
    std::size_t count = 0;
    for (const LiveBodyPose &pose : world.poses(with_geometry)) {
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
                          {"anchored", pose.anchored},
                          {"held", pose.held},
                          // How deep a permanent set it carries, and where.
                          // A dent is real and small -- a fifth of a millimetre
                          // on a 120 mm ball -- so the number is the honest way
                          // to show it, not a redrawn outline.
                          {"dent_mm", tidy(pose.dent_m * 1000.0)},
                          {"dent_at_m", vec(pose.dent_at_m)},
                          {"color_rgba", std::string(colour)}};
        if (!pose.cells_local_m.empty()) {
            nlohmann::json cells = nlohmann::json::array();
            for (const Vec3 &at : pose.cells_local_m) cells.push_back(vec(at));
            body["cells_local_m"] = std::move(cells);
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
        it = last_sent.erase(it);
    }
    if (!only_moved) last_sent.clear();
    nlohmann::json impacts = nlohmann::json::array();
    for (const LiveImpact &impact : world.impacts())
        impacts.push_back({{"struck", impact.struck}, {"by", impact.by},
                           {"closing_speed_m_s", impact.closing_speed_m_s},
                           {"threshold_speed_m_s", impact.threshold_speed_m_s},
                           {"dent_speed_m_s", impact.dent_speed_m_s},
                           {"energy_j", impact.energy_j},
                           {"would_break", impact.would_break},
                           {"would_dent", impact.would_dent}});
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
    // Every moment the world waited, or was spared waiting, since the last
    // reply carried them. Drained here rather than accumulated, so a host
    // reading each reply sees each one exactly once.
    //
    // This was the whole point of recording them and it was missing: they were
    // kept in the engine and handed to the C library, and the playground talks
    // to this, so nothing that drives the room could see any of it. A log
    // nobody can read is not a log.
    nlohmann::json waits = nlohmann::json::array();
    for (const LiveDelay &delay : world.delays())
        waits.push_back({{"at_s", delay.at_s}, {"object", delay.object},
                         {"kind", delay.kind}, {"lead_ms", delay.lead_ms},
                         {"cost_ms", delay.cost_ms}});
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
    for (const banjo::thermo::BodyHeat &b : all) {
        if (bodies.size() >= 48) break;
        if (!b.reacting && !(b.heater_w > 0.0) && std::abs(b.temperature_k - ambient) < 1.0) continue;
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
std::vector<float> sent_heights;
double water_sent_at = -1.0e9;
constexpr double kWaterEveryS = 0.25;

nlohmann::json terrainBlock(const banjo::terrain::Environment &env, const std::vector<float> &heights) {
    const banjo::terrain::Grid &g = env.terrain().grid();
    const std::vector<std::uint8_t> ground = env.surfaces();
    const banjo::terrain::Landscape &land = env.landscape();
    return {{"kind", land.kind},
            {"grid", {{"nx", g.nx}, {"nz", g.nz}, {"cell_m", g.dx}, {"x0_m", g.x0}, {"z0_m", g.z0}}},
            {"chunks", {env.terrain().chunksX(), env.terrain().chunksZ()}},
            {"heights_b64", banjo::terrain::encodeBase64(heights.data(), heights.size() * sizeof(float))},
            {"ground_b64", banjo::terrain::encodeBase64(ground.data(), ground.size())},
            {"view", {{"eye_m", {land.eye_m[0], land.eye_m[1], land.eye_m[2]}},
                      {"look_m", {land.look_m[0], land.look_m[1], land.look_m[2]}}}}};
}

nlohmann::json waterBlock(const banjo::terrain::Environment &env, double t) {
    const banjo::water::ShallowWater &w = *env.water();
    const banjo::water::Grid &g = w.grid();
    const double base = env.terrain().lowest() - 1.0;
    const std::vector<std::uint16_t> surface = env.waterSurfaceMm(base);
    const std::vector<std::int8_t> flow = env.waterFlow();
    int i0 = g.nx, j0 = g.nz, i1 = -1, j1 = -1;
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < g.nx; ++i)
            if (surface[g.at(i, j)] != 0) {
                i0 = std::min(i0, i); i1 = std::max(i1, i);
                j0 = std::min(j0, j); j1 = std::max(j1, j);
            }
    nlohmann::json out = {{"t", t}, {"base_m", base}, {"volume_m3", tidy(w.volume())},
                          {"wet_cells", w.wetCells()}, {"active_cells", w.stats().active_cells},
                          {"in_m3_s", tidy(w.inflowRate())}, {"out_m3_s", tidy(w.outflowRate())},
                          {"residual_m3", w.residual()}};
    if (i1 < 0) {
        out["box"] = {0, 0, 0, 0};
        return out;
    }
    const int ni = i1 - i0 + 1, nj = j1 - j0 + 1;
    std::vector<std::uint16_t> box_surface(static_cast<std::size_t>(ni) * nj);
    std::vector<std::int8_t> box_flow(2 * static_cast<std::size_t>(ni) * nj);
    for (int j = 0; j < nj; ++j)
        for (int i = 0; i < ni; ++i) {
            const std::size_t from = g.at(i0 + i, j0 + j);
            const std::size_t to = static_cast<std::size_t>(j) * ni + i;
            box_surface[to] = surface[from];
            box_flow[2 * to] = flow[2 * from];
            box_flow[2 * to + 1] = flow[2 * from + 1];
        }
    out["box"] = {i0, j0, ni, nj};
    out["surface_mm_b64"] = banjo::terrain::encodeBase64(box_surface.data(), box_surface.size() * 2);
    out["flow_b64"] = banjo::terrain::encodeBase64(box_flow.data(), box_flow.size());
    return out;
}

// The ground and the water into a reply. `whole` sends the ground whole and the
// water regardless of when it last went.
void addEnvironment(const LiveWorld &world, nlohmann::json &reply, bool whole) {
    const banjo::terrain::Environment *env = world.environment();
    if (env == nullptr) return;
    const std::vector<float> heights = env->heights();
    if (whole || sent_heights.size() != heights.size()) {
        reply["terrain"] = terrainBlock(*env, heights);
        sent_heights = heights;
    } else {
        const banjo::terrain::Grid &g = env->terrain().grid();
        int i0 = g.nx, j0 = g.nz, i1 = -1, j1 = -1;
        for (int j = 0; j < g.nz; ++j)
            for (int i = 0; i < g.nx; ++i)
                if (heights[g.at(i, j)] != sent_heights[g.at(i, j)]) {
                    i0 = std::min(i0, i); i1 = std::max(i1, i);
                    j0 = std::min(j0, j); j1 = std::max(j1, j);
                }
        if (i1 >= 0) {
            const int ni = i1 - i0 + 1, nj = j1 - j0 + 1;
            const std::vector<std::uint8_t> ground = env->surfaces();
            std::vector<float> rect(static_cast<std::size_t>(ni) * nj);
            std::vector<std::uint8_t> rect_ground(rect.size());
            for (int j = 0; j < nj; ++j)
                for (int i = 0; i < ni; ++i) {
                    const std::size_t c = g.at(i0 + i, j0 + j);
                    rect[static_cast<std::size_t>(j) * ni + i] = heights[c];
                    rect_ground[static_cast<std::size_t>(j) * ni + i] = ground[c];
                    sent_heights[c] = heights[c];
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
    return {{"sand_m3", tidy(effect.edit.moved.sand_m3)}, {"soil_m3", tidy(effect.edit.moved.soil_m3)},
            {"kg", tidy(effect.edit.mass_kg)}, {"columns", effect.edit.cells.size()},
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
            else throw std::invalid_argument("unknown option: " + option);
        }
        if (request.bodies.empty()) throw std::invalid_argument("a live world needs --scene");

        std::unique_ptr<LiveWorld> world = LiveWorld::open(request);
        // The opening state, so a host can draw the scene before it moves --
        // the ground and the water whole, if it has them.
        {
            nlohmann::json opening = describe(*world, true);
            addEnvironment(*world, opening, true);
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
                    }
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
                    reply["strength_n"] = world->handStrength();
                    reply["torque_n_m"] = world->handTorque();
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
                    }
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
                    const unsigned peg = world->fix(
                        command.at("a").get<std::string>(),
                        command.at("b").get<std::string>(),
                        readVec(command, "at"), readVec(command, "axis"),
                        command.value("holds_tension_n", 0.0),
                        command.value("holds_shear_n", 0.0));
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
                    std::cout << nlohmann::json{{"ok", true}, {"thermo", std::move(report)}}.dump()
                              << std::endl;
                    continue;
                } else if (op == "dig") {
                    // A trench, or a pit. The ground loses what comes out and
                    // the reply says what it was; the colliders it changed are
                    // rebuilt now, and whatever they held up is woken.
                    const auto a = readXZ(command, "from");
                    const auto b = command.contains("to") ? readXZ(command, "to") : a;
                    reply["dug"] = dugJson(world->dig(a.first, a.second, b.first, b.second,
                                                      command.value("width_m", 1.0),
                                                      command.value("depth_m", 0.5)));
                } else if (op == "deposit") {
                    const auto at = readXZ(command, "at");
                    reply["heaped"] = dugJson(world->deposit(at.first, at.second,
                                                             command.value("radius_m", 1.0),
                                                             command.value("sand_m3", 0.0),
                                                             command.value("soil_m3", 0.0)));
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
                // set of bodies can have changed. A step never carries it.
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
                    network != nullptr && network->active())
                    reply["heat"] = heatSummary(*network);
                // And what that heat has done to what things can carry.
                if (nlohmann::json strength = mechanicsSummary(*world); !strength.is_null())
                    reply["mechanics"] = std::move(strength);
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
                                 (pin.value("attached", false) ? "1" : "0") + ";";
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
