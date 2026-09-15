// A machine's controller (docs/machine-world.md, "Operating a machine"): what a
// person means -- power, a direction, a drive setting -- turned into its motor's
// command and brake before every step, on the motor's own line. These check it
// against the owner's release list:
// - made, it is off and holds its hoist on the brake;
// - a hoist slows for both ends of its travel and stops at them, and stays;
// - a drum hung on its pin the other way round still raises when told to raise;
// - told to turn the other way while turning, it stops first, for no longer
//   than a second;
// - a start that arrives after a later stop is stale and changes nothing;
// - a motor driven into something that will not move is stopped, and one told
//   too little voltage to hold its load is stopped when the load turns it back;
// - lowering stops when the load comes to rest on something;
// - a shaft runs forward, stops on its brake and runs in reverse;
// - telling the motor directly tells its controller, whose limits still hold;
// - a restart gives the controller back as it was told.

#include "fastlattice/LiveWorld.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace banjo;
using namespace banjo::fastlattice;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}

std::string number(double v) {
    std::string s = std::to_string(v);
    return s;
}

constexpr double kDt = 1.0 / 60.0;

// Steps the world for up to `seconds`, stopping early once `done` says so, and
// says how long it stepped.
template <typename Done>
double run(LiveWorld &world, double seconds, Done done) {
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    for (int i = 0; i < steps; ++i) {
        world.step(kDt);
        if (done()) return (i + 1) * kDt;
    }
    return steps * kDt;
}
const auto never = [] { return false; };

// motor_tests' hoist: an anchored iron post, an oak drum 0.2 m square at the
// top of it, and a 26.6 kg iron crate on 2 m of rope, 1.5 m of it out, so the
// crate's bottom is 0.35 m up. With `beam`, an anchored iron beam 5 cm over the
// crate's top, so it cannot be raised further than that; with `slab`, an
// anchored iron slab whose top is 0.15 m under the crate's bottom.
TileImpactRequest hoistRoom(bool beam = false, bool slab = false) {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody post;
    post.name = "post";
    post.shape = BodyShape::Box;
    post.material = MaterialPreset::Iron;
    post.dimensions_m = {0.1, 2.0, 0.1};
    post.center_m = {-0.4, 1.0, 0.0};
    post.anchored = true;
    SceneBody drum;
    drum.name = "drum";
    drum.shape = BodyShape::Box;
    drum.material = MaterialPreset::Oak;
    drum.dimensions_m = {0.2, 0.2, 0.3};
    drum.center_m = {0.0, 2.0, 0.0};
    SceneBody crate;
    crate.name = "crate";
    crate.shape = BodyShape::Box;
    crate.material = MaterialPreset::Iron;
    crate.dimensions_m = {0.15, 0.15, 0.15};
    crate.center_m = {0.1, 0.425, 0.0};
    r.bodies = {post, drum, crate};
    if (beam) {
        SceneBody over;
        over.name = "beam";
        over.shape = BodyShape::Box;
        over.material = MaterialPreset::Iron;
        over.dimensions_m = {0.4, 0.1, 0.4};
        over.center_m = {0.1, 0.6, 0.0};
        over.anchored = true;
        r.bodies.push_back(over);
    }
    if (slab) {
        SceneBody under;
        under.name = "slab";
        under.shape = BodyShape::Box;
        under.material = MaterialPreset::Iron;
        under.dimensions_m = {0.4, 0.1, 0.4};
        under.center_m = {0.1, 0.15, 0.0};
        under.anchored = true;
        r.bodies.push_back(under);
    }
    return r;
}

struct Hoist {
    std::unique_ptr<LiveWorld> world;
    unsigned pin{}, rope{}, battery{}, motor{}, control{};
};

// The hoist, its motor stalling at 60 N m -- over twice the crate's 26 N m on
// the drum -- with a brake of 200, and a controller whose travel runs from 0.4 m
// of rope out at the top to `bottom`. `reversed` hangs the drum's pin the other
// way round, so the motor's positive command lets the rope out.
Hoist hoist(bool reversed = false, double bottom = 1.6, bool beam = false, bool slab = false) {
    Hoist h;
    h.world = LiveWorld::open(hoistRoom(beam, slab));
    const Vec3 axle{0.0, 0.0, 1.0};
    const Vec3 centre{0.0, 2.0, 0.0};
    h.pin = reversed ? h.world->hinge("drum", "post", centre, axle) : h.world->hinge("post", "drum", centre, axle);
    h.rope = h.world->drum("drum", "crate", centre, axle, 0.1, Vec3{0.1, 0.5, 0.0}, 1, 2.0);
    h.battery = h.world->energyStore("battery", "post", 50000.0, 50000.0);
    h.motor = h.world->motor(h.pin, h.battery, 60.0, 10.0, 200.0);
    require(h.pin != 0 && h.rope != 0 && h.battery != 0 && h.motor != 0, "the hoist would not go together");
    h.control = h.world->control("hoist", h.motor, h.rope, 0.4, bottom);
    require(h.control != 0, "the hoist would not take a controller");
    return h;
}

struct Crate {
    double mass{}, y{}, speed{};
};

Crate crateOf(const LiveWorld &world) {
    Crate c;
    for (const LiveBodyPose &p : world.poses())
        if (p.name == "crate") {
            c.mass = p.mass_kg;
            c.y = p.position_m.y;
            const Vec3 &v = p.velocity_m_s;
            c.speed = std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
        }
    return c;
}

double tensionOf(const LiveWorld &world, unsigned rope) {
    for (const LiveJoint &j : world.joints())
        if (j.id == rope) return j.tension_n;
    throw std::runtime_error("there is no rope " + std::to_string(rope));
}

LiveControl controlOf(const LiveWorld &world, unsigned id) {
    for (const LiveControl &c : world.controls())
        if (c.id == id) return c;
    throw std::runtime_error("there is no controller " + std::to_string(id));
}

std::string tell(LiveWorld &world, unsigned control, std::uint64_t seq, std::optional<bool> power,
                 std::optional<int> direction, std::optional<double> setting = std::nullopt,
                 const std::string &sender = "test") {
    LiveWorld::ControlCommand command;
    command.sender = sender;
    command.seq = seq;
    command.power = power;
    command.direction = direction;
    command.setting = setting;
    return world.operate(control, command);
}

void aHoistSlowsForBothEndsAndStopsAtThem() {
    Hoist h = hoist();
    LiveWorld &w = *h.world;
    // Made, it is off, and the motor holds the crate on its brake.
    const LiveControl made = controlOf(w, h.control);
    require(made.forward == 1, "the hoist says its motor's " + std::to_string(made.forward) + " way raises");
    require(!made.power && made.condition == "off" && made.brake,
            "made, the controller is not off with its brake on: " + made.condition);
    run(w, 0.5, never);
    require(crateOf(w).speed < 0.01, "off, the crate is moving");
    require(w.motors().front().state == "braking", "off, the motor is " + w.motors().front().state);

    // Raised at full: it slows for the top and stops at it.
    require(tell(w, h.control, 1, true, 1, 1.0) == "applied", "raise was not applied");
    double fastest = 0.0, fastest_near = 0.0;
    const double up_for = run(w, 8.0, [&] {
        const LiveControl c = controlOf(w, h.control);
        fastest = std::max(fastest, c.rope_speed_m_s);
        if (c.out_m - 0.4 < 0.05) fastest_near = std::max(fastest_near, c.rope_speed_m_s);
        return c.condition == "at the top";
    });
    const LiveControl top = controlOf(w, h.control);
    std::cout << "  raised: at the top in " << up_for << " s with " << top.out_m << " m of rope out (the top is 0.4); "
              << "the rope came in at up to " << fastest << " m/s, and at " << fastest_near
              << " within 5 cm of the top\n";
    require(top.condition == "at the top", "raised for " + number(up_for) + " s, it says " + top.condition);
    require(std::abs(top.out_m - 0.4) < 0.01, "it stopped with " + number(top.out_m) + " m of rope out, not 0.4");
    require(fastest > 0.4, "at full it raised the crate at only " + number(fastest) + " m/s");
    require(fastest_near < 0.15, "within 5 cm of the top the rope came in at " + number(fastest_near) + " m/s");
    run(w, 0.3, never);
    const double drawn = w.motors().front().drawn_j;
    const Crate at_top = crateOf(w);
    run(w, 1.0, never);
    require(std::abs(crateOf(w).y - at_top.y) < 0.002, "at the top, the crate did not stay up");
    require(w.motors().front().drawn_j == drawn, "held at the top, the motor drew on its battery");
    require(w.motors().front().state == "braking", "at the top, the motor is " + w.motors().front().state);

    // Lowered at full: it slows for the bottom and stops at it.
    const double weight = crateOf(w).mass * 9.81;
    require(tell(w, h.control, 2, std::nullopt, -1) == "applied", "lower was not applied");
    fastest = fastest_near = 0.0;
    double slackest = weight, slack_out = 0.0, slack_speed = 0.0;
    std::string slack_said;
    int step = 0, slack_step = 0;
    const double down_for = run(w, 8.0, [&] {
        const LiveControl c = controlOf(w, h.control);
        fastest = std::max(fastest, -c.rope_speed_m_s);
        const double t = tensionOf(w, h.rope);
        ++step;
        if (t < slackest) {
            slackest = t;
            slack_out = c.out_m;
            slack_speed = c.rope_speed_m_s;
            slack_said = c.condition;
            slack_step = step;
        }
        if (1.6 - c.out_m < 0.05) fastest_near = std::max(fastest_near, -c.rope_speed_m_s);
        return c.condition == "at the bottom";
    });
    std::cout << "  the least the rope carried lowering: " << slackest << " N, at step " << slack_step << " of "
              << step << ", with " << slack_out << " m out, the rope at " << slack_speed << " m/s, saying \""
              << slack_said << "\"\n";
    const LiveControl bottom = controlOf(w, h.control);
    // At full voltage the crate's weight turns the motor past its unloaded
    // speed, and the line holds it at r w0 (1 + m g r / stall).
    const double line = 0.1 * 10.0 * (1.0 + weight * 0.1 / 60.0);
    std::cout << "  lowered: at the bottom in " << down_for << " s with " << bottom.out_m
              << " m of rope out (the bottom is 1.6); the rope went out at up to " << fastest
              << " m/s (the line: " << line << "), and at " << fastest_near
              << " within 5 cm of the bottom; the rope carried at least " << slackest << " N of the crate's "
              << weight << "\n";
    require(bottom.condition == "at the bottom", "lowered for " + number(down_for) + " s, it says " + bottom.condition);
    require(std::abs(bottom.out_m - 1.6) < 0.01, "it stopped with " + number(bottom.out_m) + " m of rope out, not 1.6");
    require(fastest_near < 0.15, "within 5 cm of the bottom the rope went out at " + number(fastest_near) + " m/s");
    // Come on gently, the rope stays taut and no faster than the line: a motor
    // let drive the drum down at once outran the falling crate, the rope went
    // slack, and the crate snatched it at 2.24 m/s.
    require(slackest > 0.5 * weight, "lowering, the rope went slack: it carried only " + number(slackest) + " N");
    require(fastest < 1.05 * line, "lowering at full, the rope went out at " + number(fastest) + " m/s, faster "
                                   "than the motor's line allows");
    run(w, 1.0, never);
    require(std::abs(controlOf(w, h.control).out_m - 1.6) < 0.01, "at the bottom, it did not stay there");
}

void aDrumHungTheOtherWayStillRaises() {
    Hoist h = hoist(true);
    LiveWorld &w = *h.world;
    const LiveControl made = controlOf(w, h.control);
    require(made.forward == -1, "on a pin hung the other way, the controller says its motor's " +
                                    std::to_string(made.forward) + " way raises");
    const Crate before = crateOf(w);
    tell(w, h.control, 1, true, 1, 1.0);
    run(w, 1.0, never);
    const Crate after = crateOf(w);
    std::cout << "  on a pin hung the other way, told to raise: the motor's command is "
              << w.motors().front().command << " and the crate rose " << after.y - before.y << " m in a second\n";
    require(w.motors().front().command < 0.0, "told to raise, the motor was not driven its negative way");
    require(after.y - before.y > 0.3, "told to raise, the crate did not rise");
}

void turningTheOtherWayStopsFirst() {
    Hoist h = hoist();
    LiveWorld &w = *h.world;
    tell(w, h.control, 1, true, 1, 1.0);
    run(w, 0.8, never);
    require(controlOf(w, h.control).rope_speed_m_s > 0.4, "it was not raising the crate before it was told to lower");
    require(tell(w, h.control, 2, std::nullopt, -1) == "applied", "lower was not applied");
    const LiveControl told = controlOf(w, h.control);
    require(told.condition == "stopping before it turns the other way" && told.brake,
            "told to lower while raising, it did not stop first: it says " + told.condition);
    double stopping_for = 0.0;
    const double took = run(w, 3.0, [&] {
        const LiveControl c = controlOf(w, h.control);
        if (c.condition == "stopping before it turns the other way") stopping_for += kDt;
        return c.rope_speed_m_s < -0.2;
    });
    std::cout << "  told to lower while raising: it stopped first for " << stopping_for
              << " s, and was letting the crate down " << took << " s after it was told\n";
    require(controlOf(w, h.control).rope_speed_m_s < -0.2, "told to lower, it did not come down within 3 s");
    require(stopping_for <= 1.0 + 1e-9, "it stopped first for " + number(stopping_for) + " s, more than a second");
}

void aStaleCommandChangesNothing() {
    Hoist h = hoist();
    LiveWorld &w = *h.world;
    require(tell(w, h.control, 5, true, 1, 1.0, "page") == "applied", "the start was not applied");
    run(w, 0.3, never);
    require(tell(w, h.control, 6, std::nullopt, 0, std::nullopt, "page") == "applied", "the stop was not applied");
    run(w, 0.3, never);
    // The start, held up on its way, comes after the stop.
    const std::string late = tell(w, h.control, 5, std::nullopt, 1, std::nullopt, "page");
    const LiveControl now = controlOf(w, h.control);
    std::cout << "  a start (5) arriving after a stop (6): " << late << "; the controller's direction is "
              << now.direction << ", from " << now.sender << " " << now.seq << "\n";
    require(late == "stale", "a start arriving after a later stop was " + late);
    require(now.direction == 0 && now.seq == 6, "a stale start changed the controller");
    const Crate stopped = crateOf(w);
    run(w, 1.0, never);
    require(std::abs(crateOf(w).y - stopped.y) < 0.002, "after a stale start, the crate moved");
    // Another sender counts for itself, and a count of 0 is applied as it comes.
    require(tell(w, h.control, 1, std::nullopt, 1, std::nullopt, "chat") == "applied", "the chat's first was stale");
    require(tell(w, h.control, 0, std::nullopt, 0, std::nullopt, "") == "applied", "a command of no count was stale");
    require(tell(w, h.control, 0, std::nullopt, 0, std::nullopt, "") == "applied", "a second of no count was stale");
    // What is not a command is refused, and uses up no count.
    const std::string two = tell(w, h.control, 7, std::nullopt, 2, std::nullopt, "page");
    const std::string much = tell(w, h.control, 7, std::nullopt, std::nullopt, 1.5, "page");
    const std::string none = w.operate(h.control + 100, LiveWorld::ControlCommand{});
    require(two != "applied" && two != "stale", "a direction of 2 was " + two);
    require(much != "applied" && much != "stale", "a setting of 1.5 was " + much);
    require(none != "applied" && none != "stale", "a controller that is not there was " + none);
    require(tell(w, h.control, 7, std::nullopt, 0, std::nullopt, "page") == "applied",
            "a refused command used up the page's count");
}

void aMotorThatGetsNowhereIsStopped() {
    // A beam 5 cm over the crate: raised into it, the motor gets nowhere.
    Hoist h = hoist(false, 1.6, true);
    LiveWorld &w = *h.world;
    tell(w, h.control, 1, true, 1, 1.0);
    const std::string stalled = "stalled: it made no progress, so it stopped";
    const double took = run(w, 5.0, [&] { return controlOf(w, h.control).condition == stalled; });
    const LiveControl c = controlOf(w, h.control);
    std::cout << "  raised into a beam: after " << took << " s it says \"" << c.condition << "\"\n";
    require(c.condition == stalled, "driven into the beam for " + number(took) + " s, it says " + c.condition);
    require(took <= 3.0 + 2 * kDt, "it took " + number(took) + " s to see it was getting nowhere");
    require(c.brake && c.command == 0.0, "stalled, its motor is still driven");
    const double drawn = w.motors().front().drawn_j;
    run(w, 1.0, never);
    require(w.motors().front().drawn_j == drawn, "stopped, it went on drawing on its battery");
    // Told again, it tries again.
    tell(w, h.control, 2, std::nullopt, 1);
    require(controlOf(w, h.control).condition != stalled && controlOf(w, h.control).command > 0.0,
            "told again, it did not try again");

    // Too weak: at 0.3 of its voltage the crate's weight turns it back.
    Hoist weak = hoist();
    tell(*weak.world, weak.control, 1, true, 1, 0.3);
    const std::string back = "too weak at this setting: the load turned it back, so it stopped";
    const double back_after = run(*weak.world, 4.0, [&] { return controlOf(*weak.world, weak.control).condition == back; });
    std::cout << "  raised at 0.3 of its voltage: after " << back_after << " s it says \""
              << controlOf(*weak.world, weak.control).condition << "\"\n";
    require(controlOf(*weak.world, weak.control).condition == back,
            "at 0.3 it says " + controlOf(*weak.world, weak.control).condition);
    const Crate held = crateOf(*weak.world);
    run(*weak.world, 1.0, never);
    require(std::abs(crateOf(*weak.world).y - held.y) < 0.002, "stopped, the crate went on coming down");
}

void aLoadSetDownStopsTheLowering() {
    // A slab 0.15 m under the crate, and the travel's bottom well past it.
    Hoist h = hoist(false, 1.9, false, true);
    LiveWorld &w = *h.world;
    tell(w, h.control, 1, true, -1, 0.3);
    const std::string down = "the load is down: its rope is slack";
    const double took = run(w, 4.0, [&] { return controlOf(w, h.control).condition == down; });
    const LiveControl c = controlOf(w, h.control);
    std::cout << "  lowered onto a slab: after " << took << " s it says \"" << c.condition << "\", with " << c.out_m
              << " m of rope out (the crate meets the slab at 1.65)\n";
    require(c.condition == down, "lowered onto the slab for " + number(took) + " s, it says " + c.condition);
    require(c.out_m < 1.8, "it paid out " + number(c.out_m) + " m of rope before it stopped");
    require(c.brake, "stopped, its brake is off");
    run(w, 1.0, never);
    require(std::abs(controlOf(w, h.control).out_m - c.out_m) < 0.005, "stopped, it went on paying rope out");
    // Raised again, it takes up the slack and lifts the crate off.
    const Crate landed = crateOf(w);
    tell(w, h.control, 2, std::nullopt, 1, 1.0);
    run(w, 1.5, never);
    require(crateOf(w).y > landed.y + 0.1, "told to raise, it did not lift the crate off the slab");
}

// motor_tests' flywheel: an iron post, and an iron flywheel 0.4 x 0.1 x 0.4 m
// on a vertical pin above it.
TileImpactRequest flywheelRoom() {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody post;
    post.name = "post";
    post.shape = BodyShape::Box;
    post.material = MaterialPreset::Iron;
    post.dimensions_m = {0.1, 0.8, 0.1};
    post.center_m = {0.5, 0.4, 0.0};
    post.anchored = true;
    SceneBody wheel;
    wheel.name = "flywheel";
    wheel.shape = BodyShape::Box;
    wheel.material = MaterialPreset::Iron;
    wheel.dimensions_m = {0.4, 0.1, 0.4};
    wheel.center_m = {0.5, 1.0, 0.0};
    r.bodies = {post, wheel};
    return r;
}

void aShaftRunsForwardStopsAndReverses() {
    const auto world = LiveWorld::open(flywheelRoom());
    const Vec3 axle{0.5, 1.0, 0.0};
    const Vec3 up{0.0, 1.0, 0.0};
    const unsigned pin = world->hinge("post", "flywheel", axle, up);
    const unsigned battery = world->energyStore("battery", "post", 50000.0, 50000.0);
    // It stalls at 10 N m, runs at 10 rad/s unloaded, and brakes with 20.
    const unsigned drive = world->motor(pin, battery, 10.0, 10.0, 20.0);
    const unsigned control = world->control("flywheel", drive);
    require(pin != 0 && battery != 0 && drive != 0 && control != 0, "the flywheel would not go together");
    require(controlOf(*world, control).forward == 1 && controlOf(*world, control).rope == 0,
            "a shaft's controller has a rope, or a backward forward");
    require(world->control("again", drive) == 0, "a motor took a second controller");
    tell(*world, control, 1, true, 1, 0.5);
    run(*world, 6.0, never);
    const LiveControl forward = controlOf(*world, control);
    std::cout << "  forward at half its voltage for 6 s: " << forward.speed_rpm << " rpm (it runs at "
              << 0.5 * 10.0 * 60.0 / (2.0 * 3.14159265358979323846) << " unloaded at half)\n";
    require(forward.speed_rpm > 30.0, "forward, the flywheel turns at " + number(forward.speed_rpm) + " rpm");
    require(forward.condition.empty(), "running forward, it says " + forward.condition);
    tell(*world, control, 2, std::nullopt, -1);
    double stopping_for = 0.0;
    run(*world, 4.0, [&] {
        if (controlOf(*world, control).condition == "stopping before it turns the other way") stopping_for += kDt;
        return false;
    });
    const LiveControl reverse = controlOf(*world, control);
    std::cout << "  reversed: it stopped first for " << stopping_for << " s, and 4 s on turns at "
              << reverse.speed_rpm << " rpm\n";
    require(stopping_for > 0.0 && stopping_for <= 1.0 + 1e-9,
            "reversed, it stopped first for " + number(stopping_for) + " s");
    require(reverse.speed_rpm < -5.0, "reversed, the flywheel turns at " + number(reverse.speed_rpm) + " rpm");
    tell(*world, control, 3, std::nullopt, 0);
    run(*world, 3.0, never);
    const LiveControl stopped = controlOf(*world, control);
    require(stopped.condition == "stopped, holding on its brake" && std::abs(stopped.speed_rpm) < 0.5,
            "stopped, it says " + stopped.condition + " at " + number(stopped.speed_rpm) + " rpm");
}

void drivingTheMotorTellsItsController() {
    Hoist h = hoist();
    LiveWorld &w = *h.world;
    require(w.driveMotor(h.motor, 1.0), "the motor would not take a command");
    const LiveControl c = controlOf(w, h.control);
    require(c.power && c.direction == 1 && c.setting == 1.0 && c.sender == "drive",
            "driving the motor did not tell its controller");
    run(w, 8.0, [&] { return controlOf(w, h.control).condition == "at the top"; });
    const LiveControl top = controlOf(w, h.control);
    std::cout << "  driven at 1 through the motor: its controller stopped it " << top.condition << ", with "
              << top.out_m << " m of rope out\n";
    require(top.condition == "at the top", "driven through the motor, the hoist says " + top.condition);
    w.driveMotor(h.motor, 0.0, false);
    require(controlOf(w, h.control).direction == 0 && controlOf(w, h.control).brake,
            "told 0 through the motor, it did not stop on its brake");
}

void aRestartGivesTheControllerBackAsItWasTold() {
    Hoist h = hoist();
    tell(*h.world, h.control, 3, true, 1, 0.9, "page");
    run(*h.world, 0.5, never);
    tell(*h.world, h.control, 4, std::nullopt, 0, std::nullopt, "page");
    run(*h.world, 0.5, never);
    const LiveControl before = controlOf(*h.world, h.control);
    std::string why;
    const std::string saved = h.world->snapshot(why);
    require(!saved.empty(), "the hoist could not be saved: " + why);
    const auto again = LiveWorld::open(hoistRoom(), saved);
    require(again->controls().size() == 1, "the controller did not come back");
    const LiveControl back = again->controls().front();
    std::cout << "  saved and opened again: " << back.name << " is " << (back.power ? "on" : "off")
              << ", direction " << back.direction << ", setting " << back.setting << ", last told by " << back.sender
              << " " << back.seq << ", and says \"" << back.condition << "\"\n";
    require(back.id == before.id && back.name == "hoist" && back.motor == before.motor && back.rope == before.rope &&
                back.top_out_m == before.top_out_m && back.bottom_out_m == before.bottom_out_m &&
                back.forward == before.forward,
            "the controller came back on another machine");
    require(back.power && back.direction == 0 && back.setting == 0.9 && back.sender == "page" && back.seq == 4 &&
                back.condition == before.condition,
            "the controller did not come back as it was told");
    // What it had applied is still applied: a start from before the restart,
    // arriving after it, is stale.
    require(tell(*again, back.id, 3, std::nullopt, 1, std::nullopt, "page") == "stale",
            "after the restart, a start older than the stop was applied");
    // And it goes on from there: raised, it stops at the top.
    require(tell(*again, back.id, 5, std::nullopt, 1, 1.0, "page") == "applied", "after the restart, raise was stale");
    run(*again, 8.0, [&] { return controlOf(*again, back.id).condition == "at the top"; });
    require(controlOf(*again, back.id).condition == "at the top",
            "after the restart, raised, it says " + controlOf(*again, back.id).condition);
}

} // namespace

int main() {
    // Every check runs, and every failure is said: a main that stops at the
    // first failure hides what the rest would have found.
    const std::vector<std::pair<const char *, void (*)()>> checks{
        {"a hoist slows for both ends of its travel and stops at them", aHoistSlowsForBothEndsAndStopsAtThem},
        {"a drum hung on its pin the other way round still raises", aDrumHungTheOtherWayStillRaises},
        {"told to turn the other way, it stops first", turningTheOtherWayStopsFirst},
        {"a start arriving after a later stop changes nothing", aStaleCommandChangesNothing},
        {"a motor that gets nowhere is stopped", aMotorThatGetsNowhereIsStopped},
        {"lowering stops when the load is set down", aLoadSetDownStopsTheLowering},
        {"a shaft runs forward, stops and reverses", aShaftRunsForwardStopsAndReverses},
        {"driving the motor tells its controller", drivingTheMotorTellsItsController},
        {"a restart gives the controller back as it was told", aRestartGivesTheControllerBackAsItWasTold},
    };
    int failed = 0;
    for (const auto &[name, check] : checks) {
        try {
            check();
            std::cout << "[PASS] " << name << "\n";
        } catch (const std::exception &error) {
            ++failed;
            std::cout << "[FAIL] " << name << ": " << error.what() << "\n";
        }
    }
    if (failed == 0) {
        std::cout << "\nall machine control tests passed\n";
        return 0;
    }
    std::cout << "\n" << failed << " of " << checks.size() << " machine control tests failed\n";
    return 1;
}
