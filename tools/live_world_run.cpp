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
//        {"op":"unhinge","joint":1}          take the pin out; it falls
//        {"op":"joint_friction","joint":1,"friction_n_m":40}   stiffen it
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
        if (sliding) {
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
        out.push_back(std::move(said));
    }
    return out;
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
    return state;
}

Vec3 readVec(const nlohmann::json &node, const char *key) {
    const auto &v = node.at(key);
    if (!v.is_array() || v.size() != 3) throw std::invalid_argument(std::string(key) + " needs three numbers");
    return Vec3{v[0].get<double>(), v[1].get<double>(), v[2].get<double>()};
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
        // The opening state, so a host can draw the scene before it moves.
        std::cout << describe(*world, true).dump() << std::endl;
        world->forgetDelays();

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
                } else if (op != "poses") {
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
                nlohmann::json state = describe(*world, geometry,
                                                !geometry && command.value("moved", false));
                world->forgetDelays();
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
