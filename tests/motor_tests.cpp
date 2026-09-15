// Motors on pins, and the stores of energy they draw on (docs/machine-world.md).
//
// The machine world's first need is a joint that is driven, and an account of
// the energy that drives it. A motor here is a DC motor's line -- the torque it
// stalls at and the speed it runs at unloaded -- run by Jolt's own hinge motor,
// with its torque limit set each step from the line, and what it did is read
// back from the impulse the solver applied. So these check the solver against
// the line and against the energy:
// - a flywheel spun up follows the line's own curve, turn after turn, and the
//   work the motor did is the flywheel's spin;
// - a stalled motor turns all it draws into heat;
// - a flat battery stops it, and never goes below empty;
// - a battery gives no more than its power;
// - a brake holds without drawing, and lets go;
// - a load driving the motor gives nothing back to the battery.

#include "fastlattice/LiveWorld.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace banjo;
using namespace banjo::fastlattice;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}

constexpr double kDt = 1.0 / 60.0;
const Vec3 kUp{0.0, 1.0, 0.0};
const Vec3 kAxle{0.5, 1.0, 0.0};

// Steps the world for about `seconds`, calling `each` after every step, and
// says how long it stepped.
template <typename Each>
double run(LiveWorld &world, double seconds, Each each) {
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    for (int i = 0; i < steps; ++i) {
        world.step(kDt);
        each();
    }
    return steps * kDt;
}

// An iron post fixed in place, and an iron flywheel 0.4 x 0.1 x 0.4 m clear
// above it, to be hung on a vertical pin through its middle.
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
    wheel.center_m = kAxle;
    r.bodies = {post, wheel};
    return r;
}

// The motor these use: it stalls at 10 N m and runs at 10 rad/s unloaded.
constexpr double kStall = 10.0;
constexpr double kUnloaded = 10.0;

void aFlywheelSpunUpFollowsTheMotorsLine() {
    const auto world = LiveWorld::open(flywheelRoom());
    const unsigned pin = world->hinge("post", "flywheel", kAxle, kUp);
    require(pin != 0, "the flywheel would not go on its pin");
    const unsigned battery = world->energyStore("battery", "post", 20000.0, 20000.0);
    require(battery != 0, "the post would not take a battery");
    const unsigned drive = world->motor(pin, battery, kStall, kUnloaded);
    require(drive != 0, "the pin would not take a motor");
    require(world->motor(pin, battery, kStall, kUnloaded) == 0, "a pin took a second motor");
    require(world->motor(pin, battery + 1, kStall, kUnloaded) == 0, "a motor was wired to no store");
    require(world->energyStore("battery", "nowhere", 1.0, 1.0) == 0, "a store went into nothing called nowhere");
    require(world->energyStore("battery", "post", 1.0, 2.0) == 0, "a store took more than it holds");
    const double inertia = world->inertiaAbout("flywheel", kUp);
    require(inertia > 0.0 && std::isfinite(inertia), "the flywheel has no inertia about its axle");
    // Anchored scenery does not turn: as hard to turn as anything can be. (Asked
    // of Jolt unchecked, the question killed the process.)
    require(std::isinf(world->inertiaAbout("post", kUp)), "the anchored post has an inertia that could be turned");
    // The line makes a first-order spin-up, w(t) = w0 (1 - exp(-t / T)), with
    // T = J w0 / stall.
    const double lag = inertia * kUnloaded / kStall;
    std::cout << "  the flywheel: " << inertia << " kg m^2 about its axle, so the line's time constant is "
              << lag << " s\n";
    require(world->driveMotor(drive, 1.0), "the motor would not take a command");
    double t = 0.0;
    for (const double until : {lag, 2.0 * lag}) {
        t += run(*world, until - t, [] {});
        const LiveMotor m = world->motors().front();
        const double expected = kUnloaded * (1.0 - std::exp(-t / lag));
        std::cout << "  at " << t << " s it turns at " << m.speed_rad_s << " rad/s; the line says " << expected
                  << "\n";
        // Stepping the line at 1/60 s puts the curve about dt / 2T behind the
        // exponential: 0.25% here. A hundredth is four times that.
        require(std::abs(m.speed_rad_s - expected) < 0.01 * expected, "the flywheel is not on the motor's line");
    }
    const LiveMotor m = world->motors().front();
    require(m.state == "driving", "the motor says it is " + m.state + ", not driving");
    // Turn after turn: the whole turn, not a reading wrapped at 180 degrees.
    const double turned = kUnloaded * (t - lag * (1.0 - std::exp(-t / lag)));
    std::cout << "  it has turned " << m.turned_rad / (2.0 * 3.14159265358979323846) << " times; the line says "
              << turned / (2.0 * 3.14159265358979323846) << "\n";
    require(std::abs(m.turned_rad - turned) < 0.01 * turned, "the motor's count of its turns is not the line's");
    // The account: what the battery gave is what the motor asked for, which is
    // its work and its heat; and its work is the flywheel's spin.
    const LiveEnergyStore s = world->energyStores().front();
    const double spin = 0.5 * inertia * m.speed_rad_s * m.speed_rad_s;
    std::cout << "  it drew " << m.drawn_j << " J: " << m.work_j << " J of work and " << m.heat_j
              << " J of heat; the flywheel's spin is " << spin << " J\n";
    require(s.short_j == 0.0 && std::abs(s.given_j - m.drawn_j) <= 1e-9 * m.drawn_j,
            "the battery's account and the motor's differ");
    require(std::abs(s.capacity_j - s.charge_j - s.given_j) <= 1e-9 * s.capacity_j,
            "the battery lost charge it did not give");
    require(std::abs(m.drawn_j - m.work_j - m.heat_j) <= 1e-9 * m.drawn_j,
            "what the motor drew is not its work and its heat");
    // Work as torque times the turn a step makes, with the turn taken at the
    // speed the step ends at (as the solver moves things), is ahead of the
    // spin by half J dw^2 a step: about dt / 2T of it over a spin-up, 0.3%.
    require(std::abs(m.work_j - spin) <= 0.01 * m.work_j, "the motor's work did not turn up as the flywheel's spin");
}

void aStalledMotorTurnsAllItDrawsIntoHeat() {
    const auto world = LiveWorld::open(flywheelRoom());
    // No travel either way: the pin cannot turn.
    const unsigned pin = world->hinge("post", "flywheel", kAxle, kUp, 0.0, 0.0);
    const unsigned battery = world->energyStore("battery", "post", 20000.0, 20000.0);
    const unsigned drive = world->motor(pin, battery, kStall, kUnloaded);
    require(pin != 0 && battery != 0 && drive != 0, "the stalled rig would not go together");
    const double command = 0.5;
    world->driveMotor(drive, command);
    const double t = run(*world, 2.0, [] {});
    const LiveMotor m = world->motors().front();
    // Stalled, the line gives the command's share of the stall torque, and all
    // of what it draws is the windings' I^2 R.
    const double torque = command * kStall;
    const double heat = torque * torque * (kUnloaded / kStall) * t;
    std::cout << "  stalled: " << m.torque_n_m << " N m (the line: " << torque << "), " << m.heat_j
              << " J of heat in " << t << " s (I^2 R: " << heat << "), " << m.work_j << " J of work\n";
    require(std::abs(m.torque_n_m - torque) < 0.01 * torque, "a stalled motor is not pushing its stall torque");
    require(std::abs(m.heat_j - heat) < 0.01 * heat, "a stalled motor's heat is not I^2 R");
    require(std::abs(m.work_j) < 0.01 * m.heat_j, "a stalled motor did work");
    require(std::abs(m.drawn_j - m.work_j - m.heat_j) <= 1e-9 * m.drawn_j,
            "what the stalled motor drew is not its heat");
}

void aFlatBatteryStopsTheMotorAndNeverGoesBelowEmpty() {
    const auto world = LiveWorld::open(flywheelRoom());
    const unsigned pin = world->hinge("post", "flywheel", kAxle, kUp);
    const double capacity = 30.0;
    const unsigned battery = world->energyStore("battery", "post", capacity, capacity);
    const unsigned drive = world->motor(pin, battery, kStall, kUnloaded);
    require(pin != 0 && battery != 0 && drive != 0, "the rig would not go together");
    world->driveMotor(drive, 1.0);
    double lowest = capacity;
    run(*world, 5.0, [&] { lowest = std::min(lowest, world->energyStores().front().charge_j); });
    const double at_five = world->motors().front().speed_rad_s;
    run(*world, 1.0, [] {});
    const LiveMotor m = world->motors().front();
    const LiveEnergyStore s = world->energyStores().front();
    std::cout << "  flat: it gave " << s.given_j << " J of " << capacity << ", " << s.short_j
              << " J short; the flywheel coasts at " << m.speed_rad_s << " rad/s (" << at_five
              << " a second before); the motor is " << m.state << "\n";
    require(lowest >= 0.0, "the battery went below empty");
    require(s.charge_j == 0.0 && std::abs(s.given_j - capacity) <= 1e-9 * capacity,
            "the battery was not emptied, or gave more than it held");
    // The drive is held to the charge from the speed a step starts at; the
    // last step ends a little faster, and does that little more work.
    require(s.short_j < 1e-3 * capacity, "the last step asked for far more than was left");
    require(m.state == "flat", "the motor says it is " + m.state + ", not flat");
    require(std::abs(m.speed_rad_s - at_five) <= 1e-3 * at_five, "with nothing driving it the flywheel did not coast");
}

void aBatteryGivesNoMoreThanItsPower() {
    const auto world = LiveWorld::open(flywheelRoom());
    const unsigned pin = world->hinge("post", "flywheel", kAxle, kUp);
    // The motor stalls at 100 W; the battery gives 20.
    const double most = 20.0;
    const unsigned battery = world->energyStore("battery", "post", 20000.0, 20000.0, 24.0, most);
    const unsigned drive = world->motor(pin, battery, kStall, kUnloaded);
    require(pin != 0 && battery != 0 && drive != 0, "the rig would not go together");
    world->driveMotor(drive, 1.0);
    double highest = 0.0;
    run(*world, 3.0, [&] { highest = std::max(highest, world->motors().front().power_w); });
    std::cout << "  the most it asked of a 20 W battery: " << highest << " W\n";
    require(highest <= 1.01 * most, "the motor took more than the battery's power");
    require(highest >= 0.95 * most, "the battery's power never bound");
}

// An iron post, and an oak bar 1 m long held out from it at the height of a
// pin through the bar's near end, the pin across the bar.
TileImpactRequest leverRoom() {
    TileImpactRequest r;
    r.cell_size_m = 0.05;
    r.backend = BackendKind::CpuParallel;
    SceneBody post;
    post.name = "post";
    post.shape = BodyShape::Box;
    post.material = MaterialPreset::Iron;
    post.dimensions_m = {0.1, 1.0, 0.1};
    post.center_m = {-0.5, 0.5, 0.0};
    post.anchored = true;
    SceneBody bar;
    bar.name = "bar";
    bar.shape = BodyShape::Box;
    bar.material = MaterialPreset::Oak;
    bar.dimensions_m = {1.0, 0.1, 0.1};
    bar.center_m = {0.15, 1.0, 0.0};
    r.bodies = {post, bar};
    return r;
}

void aBrakeHoldsWithoutDrawingAndLetsGo() {
    const auto world = LiveWorld::open(leverRoom());
    const unsigned pin = world->hinge("post", "bar", Vec3{-0.35, 1.0, 0.0}, Vec3{0.0, 0.0, 1.0});
    const unsigned battery = world->energyStore("battery", "post", 1000.0, 1000.0);
    const unsigned drive = world->motor(pin, battery, kStall, kUnloaded, 100.0);
    require(pin != 0 && battery != 0 && drive != 0, "the lever would not go together");
    world->driveMotor(drive, 0.0, true);
    run(*world, 2.0, [] {});
    LiveMotor m = world->motors().front();
    std::cout << "  braked: the bar turned " << m.turned_rad << " rad in 2 s, holding " << m.torque_n_m
              << " N m; the motor is " << m.state << " and drew " << m.drawn_j << " J\n";
    require(m.state == "braking", "the motor says it is " + m.state + ", not braking");
    require(std::abs(m.turned_rad) < 0.01, "the brake did not hold the bar");
    require(m.drawn_j == 0.0 && world->energyStores().front().given_j == 0.0, "holding drew on the battery");
    world->driveMotor(drive, 0.0, false);
    run(*world, 1.0, [] {});
    m = world->motors().front();
    std::cout << "  let go: it swung " << m.turned_rad << " rad down in a second; the motor is " << m.state << "\n";
    require(m.state == "coasting", "the motor says it is " + m.state + ", not coasting");
    require(std::abs(m.turned_rad) > 0.5, "let go, the bar did not swing down");
}

void aLoadDrivingTheMotorGivesNothingBack() {
    const auto world = LiveWorld::open(flywheelRoom());
    const unsigned pin = world->hinge("post", "flywheel", kAxle, kUp);
    const unsigned battery = world->energyStore("battery", "post", 20000.0, 20000.0);
    const unsigned drive = world->motor(pin, battery, kStall, kUnloaded);
    require(pin != 0 && battery != 0 && drive != 0, "the rig would not go together");
    const double inertia = world->inertiaAbout("flywheel", kUp);
    world->driveMotor(drive, 1.0);
    run(*world, 6.0, [] {});
    // Told a fifth of the voltage, it runs at 2 rad/s unloaded: the spinning
    // flywheel drives it faster than that, and it brakes as a generator would
    // -- with nowhere for what it makes to go but heat.
    const LiveMotor before = world->motors().front();
    const double charge_before = world->energyStores().front().charge_j;
    world->driveMotor(drive, 0.2);
    double charge = charge_before;
    bool gained = false;
    run(*world, 4.0, [&] {
        const double now = world->energyStores().front().charge_j;
        if (now > charge) gained = true;
        charge = now;
    });
    const LiveMotor after = world->motors().front();
    const double spin_lost = 0.5 * inertia *
                             (before.speed_rad_s * before.speed_rad_s - after.speed_rad_s * after.speed_rad_s);
    const double heat = after.heat_j - before.heat_j;
    const double drawn = after.drawn_j - before.drawn_j;
    std::cout << "  braking from " << before.speed_rad_s << " to " << after.speed_rad_s << " rad/s: " << spin_lost
              << " J of spin lost, " << heat << " J of heat, " << drawn << " J drawn\n";
    require(!gained && charge <= charge_before, "the battery gained charge from a load driving its motor");
    // All of what the flywheel lost, and all that was drawn, is heat -- less
    // the same half J dw^2 a step the spin-up shows, the other way round.
    require(std::abs(spin_lost + drawn - heat) <= 0.01 * heat, "what the flywheel lost did not turn into heat");
}

// An iron post; an oak drum 0.2 x 0.2 x 0.3 m on an axle along z at (0, 2, 0);
// and an iron crate 0.15 m across hanging 1.5 m below the drum's right-hand
// side, where a rope off the drum's 0.1 m radius comes straight down to it.
TileImpactRequest hoistRoom() {
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
    return r;
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

LiveJoint jointOf(const LiveWorld &world, unsigned id) {
    for (const LiveJoint &j : world.joints())
        if (j.id == id) return j;
    throw std::runtime_error("there is no joint " + std::to_string(id));
}

void aHoistWindsItsRopeOnAndLiftsTheCrate() {
    constexpr double kG = 9.81;
    constexpr double kTurn = 2.0 * 3.14159265358979323846;
    const auto world = LiveWorld::open(hoistRoom());
    const Vec3 axle{0.0, 0.0, 1.0};
    const Vec3 centre{0.0, 2.0, 0.0};
    const double radius = 0.1;
    const unsigned pin = world->hinge("post", "drum", centre, axle);
    // Two metres of rope, 1.5 of it out: the drum turning the positive way
    // about z takes it on.
    const unsigned rope = world->drum("drum", "crate", centre, axle, radius, Vec3{0.1, 0.5, 0.0}, 1, 2.0);
    const unsigned battery = world->energyStore("battery", "post", 5000.0, 5000.0);
    // It stalls at 60 N m, over twice the crate's 26 N m on the drum; its brake
    // holds 200.
    const unsigned drive = world->motor(pin, battery, 60.0, 10.0, 200.0);
    require(pin != 0 && rope != 0 && battery != 0 && drive != 0, "the hoist would not go together");
    const double inertia = world->inertiaAbout("drum", axle);

    // The brake holds the drum, and the rope carries the crate.
    world->driveMotor(drive, 0.0, true);
    run(*world, 1.0, [] {});
    const Crate held = crateOf(*world);
    const LiveJoint hanging = jointOf(*world, rope);
    std::cout << "  held by the brake: the rope carries " << hanging.tension_n << " N of the crate's "
              << held.mass * kG << " N, with " << hanging.at << " m of it out and " << hanging.wound_m
              << " m on the drum; the drum turned " << world->motors().front().turned_rad
              << " rad, and the crate hangs " << 0.5 - 0.075 - held.y << " m below where it was made\n";
    require(hanging.kind == "drum", "the rope says it is a " + hanging.kind);
    require(std::abs(hanging.tension_n - held.mass * kG) < 0.01 * held.mass * kG,
            "the rope does not carry the crate's weight");
    require(world->motors().front().drawn_j == 0.0, "holding the crate drew on the battery");

    // Lifting.
    const LiveMotor before = world->motors().front();
    const double out_before = hanging.at;
    world->driveMotor(drive, 1.0);
    run(*world, 1.5, [] {});
    const LiveMotor lifted = world->motors().front();
    const Crate up = crateOf(*world);
    const LiveJoint wound = jointOf(*world, rope);
    const double rise = up.y - held.y;
    const double turned = lifted.turned_rad - before.turned_rad;
    const double taken = out_before - wound.at;
    std::cout << "  lifting for 1.5 s: the drum turned " << turned / kTurn << " times, taking on " << taken
              << " m of rope (r x turn: " << radius * turned << " m), and the crate rose " << rise << " m\n";
    require(turned > kTurn, "the drum did not turn even once");
    require(std::abs(taken - radius * turned) < 0.002 * radius * turned,
            "the rope taken on is not the drum's radius times its turn");
    require(std::abs(rise - taken) < 0.01 * taken, "the crate did not rise by the rope taken on");
    // The account: the motor's work is the crate's height and the motion.
    const double height = up.mass * kG * rise;
    const double motion = 0.5 * up.mass * up.speed * up.speed +
                          0.5 * inertia * lifted.speed_rad_s * lifted.speed_rad_s;
    const double work = lifted.work_j - before.work_j;
    const double heat = lifted.heat_j - before.heat_j;
    const double drawn = lifted.drawn_j - before.drawn_j;
    std::cout << "  it drew " << drawn << " J: " << work << " J of work -- " << height
              << " J into the crate's height and " << motion << " J into motion -- and " << heat << " J of heat\n";
    require(std::abs(drawn - work - heat) <= 1e-9 * drawn, "what the motor drew is not its work and its heat");
    require(std::abs(work - height - motion) <= 0.01 * work,
            "the motor's work is not the crate's height and the motion");

    // Braked at the top: it stays there, and holding it draws nothing.
    world->driveMotor(drive, 0.0, true);
    run(*world, 0.5, [] {});
    const Crate stopped = crateOf(*world);
    const double drawn_stopped = world->motors().front().drawn_j;
    run(*world, 1.0, [] {});
    const Crate still = crateOf(*world);
    std::cout << "  braked: in a second the crate moved " << still.y - stopped.y << " m\n";
    require(std::abs(still.y - stopped.y) < 0.002, "braked, the crate did not stay up");
    require(world->motors().front().drawn_j == drawn_stopped, "holding the crate up drew on the battery");
}

// A world saved with a hoist in it, and opened again from what was saved: the
// battery holds what it held, the motor has its account and its brake, as much
// rope is off the drum, and the crate hangs where it hung. And it goes on from
// there: driven again, the drum winds the rope on as before.
void aRestartGivesTheHoistBackAsItStood() {
    constexpr double kTurn = 2.0 * 3.14159265358979323846;
    const TileImpactRequest room = hoistRoom();
    const auto world = LiveWorld::open(room);
    const Vec3 axle{0.0, 0.0, 1.0};
    const Vec3 centre{0.0, 2.0, 0.0};
    const double radius = 0.1;
    const unsigned pin = world->hinge("post", "drum", centre, axle);
    const unsigned rope = world->drum("drum", "crate", centre, axle, radius, Vec3{0.1, 0.5, 0.0}, 1, 2.0);
    const unsigned battery = world->energyStore("battery", "post", 5000.0, 5000.0);
    const unsigned drive = world->motor(pin, battery, 60.0, 10.0, 200.0);
    require(pin != 0 && rope != 0 && battery != 0 && drive != 0, "the hoist would not go together");
    world->driveMotor(drive, 0.0, true);
    run(*world, 0.5, [] {});
    world->driveMotor(drive, 1.0);
    run(*world, 0.8, [] {});
    world->driveMotor(drive, 0.0, true);
    run(*world, 1.0, [] {});
    const LiveEnergyStore store_before = world->energyStores().front();
    const LiveMotor motor_before = world->motors().front();
    const double out_before = jointOf(*world, rope).at;
    const double wound_before = jointOf(*world, rope).wound_m;
    const Crate crate_before = crateOf(*world);

    std::string why;
    const std::string saved = world->snapshot(why);
    require(!saved.empty(), "the hoist could not be saved: " + why);
    const auto again = LiveWorld::open(room, saved);
    require(again->energyStores().size() == 1 && again->motors().size() == 1,
            "the battery or the motor did not come back");
    const LiveEnergyStore store = again->energyStores().front();
    const LiveMotor motor = again->motors().front();
    const LiveJoint back = jointOf(*again, rope);
    const Crate crate = crateOf(*again);
    std::cout << "  saved and opened again: the battery holds " << store.charge_j << " J (" << store_before.charge_j
              << " saved), the motor has drawn " << motor.drawn_j << " J (" << motor_before.drawn_j << ") and is "
              << (motor.brake ? "braked" : "not braked") << ", " << back.at << " m of rope is out (" << out_before
              << "), and the crate hangs at " << crate.y << " m (" << crate_before.y << ")\n";
    require(store.charge_j == store_before.charge_j && store.given_j == store_before.given_j,
            "the battery did not come back holding what it held");
    require(motor.id == motor_before.id && motor.joint == motor_before.joint && motor.brake &&
                motor.command == 0.0 && motor.drawn_j == motor_before.drawn_j &&
                motor.turned_rad == motor_before.turned_rad,
            "the motor did not come back with its account and its brake");
    // And saying what it said of its last step before it was saved, until it
    // takes another: braked, holding the crate up.
    require(motor.state == "braking" && motor.state == motor_before.state &&
                motor.speed_rad_s == motor_before.speed_rad_s && motor.torque_n_m == motor_before.torque_n_m &&
                motor.current_a == motor_before.current_a && motor.power_w == motor_before.power_w,
            "the motor came back saying it was " + motor.state + ", and it was " + motor_before.state +
                " when it was saved");
    // To the last bit: the saved world keeps the rope's own tally.
    require(back.kind == "drum" && back.at == out_before && back.wound_m == wound_before,
            "the rope did not come back with as much off the drum and on it");
    require(std::abs(crate.y - crate_before.y) < 0.001, "the crate did not come back where it hung");

    // And it goes on from there.
    run(*again, 0.5, [] {});
    const LiveMotor held = again->motors().front();
    const Crate still = crateOf(*again);
    require(std::abs(still.y - crate.y) < 0.002, "opened again, the brake did not hold the crate");
    const double out_held = jointOf(*again, rope).at;
    again->driveMotor(drive, 1.0);
    run(*again, 0.6, [] {});
    const LiveMotor lifted = again->motors().front();
    const double turned = lifted.turned_rad - held.turned_rad;
    const double taken = out_held - jointOf(*again, rope).at;
    const double rise = crateOf(*again).y - still.y;
    std::cout << "  driven again: the drum turned " << turned / kTurn << " times, took on " << taken
              << " m of rope and the crate rose " << rise << " m\n";
    require(turned > 0.0 && std::abs(taken - radius * turned) < 0.002 * radius * turned,
            "opened again, the rope taken on is not the drum's radius times its turn");
    require(std::abs(rise - taken) < 0.01 * taken, "opened again, the crate did not rise by the rope taken on");
}

// A motor says what it is doing from the moment it is told, and the step that
// follows does just that. A room opened with its hoist braked said "coasting"
// until its first step, and a page that drew the opening showed it so.
void aMotorSaysAtOnceWhatItIsToldToDo() {
    const auto world = LiveWorld::open(flywheelRoom());
    const unsigned pin = world->hinge("post", "flywheel", kAxle, kUp);
    const unsigned battery = world->energyStore("battery", "post", 20000.0, 20000.0);
    const unsigned drive = world->motor(pin, battery, kStall, kUnloaded, 50.0);
    require(pin != 0 && battery != 0 && drive != 0, "the rig would not go together");
    require(world->motors().front().state == "coasting",
            "made, the motor says it is " + world->motors().front().state + ", not coasting");
    const auto told = [](LiveWorld &in, unsigned motor, double command, bool brake, const std::string &says) {
        in.driveMotor(motor, command, brake);
        const std::string now = in.motors().front().state;
        run(in, 0.1, [] {});
        const std::string after = in.motors().front().state;
        std::cout << "  told " << command << (brake ? " with its brake" : "") << ": it says it is " << now
                  << " at once, and " << after << " after the steps that follow\n";
        require(now == says, "told, the motor says it is " + now + ", not " + says);
        require(after == says, "stepped, the motor says it is " + after + ", not " + says);
    };
    told(*world, drive, 0.0, true, "braking");
    told(*world, drive, 1.0, false, "driving");
    told(*world, drive, 0.0, false, "coasting");
    // Told to drive from a store with nothing in it.
    const auto spent = LiveWorld::open(flywheelRoom());
    const unsigned pin_spent = spent->hinge("post", "flywheel", kAxle, kUp);
    const unsigned empty = spent->energyStore("battery", "post", 100.0, 0.0);
    const unsigned motor_spent = spent->motor(pin_spent, empty, kStall, kUnloaded);
    require(pin_spent != 0 && empty != 0 && motor_spent != 0, "the spent rig would not go together");
    told(*spent, motor_spent, 1.0, false, "flat");
}

} // namespace

int main() {
    // Every check runs, and every failure is said: a main that stops at the
    // first failure hides what the rest would have found.
    const std::vector<std::pair<const char *, void (*)()>> checks{
        {"a flywheel spun up follows the motor's line, and its work is the spin",
         aFlywheelSpunUpFollowsTheMotorsLine},
        {"a stalled motor turns all it draws into heat", aStalledMotorTurnsAllItDrawsIntoHeat},
        {"a flat battery stops the motor, and never goes below empty",
         aFlatBatteryStopsTheMotorAndNeverGoesBelowEmpty},
        {"a battery gives no more than its power", aBatteryGivesNoMoreThanItsPower},
        {"a brake holds without drawing, and lets go", aBrakeHoldsWithoutDrawingAndLetsGo},
        {"a load driving the motor gives nothing back", aLoadDrivingTheMotorGivesNothingBack},
        {"a hoist winds its rope on and lifts the crate", aHoistWindsItsRopeOnAndLiftsTheCrate},
        {"a restart gives the hoist back as it stood", aRestartGivesTheHoistBackAsItStood},
        {"a motor says at once what it is told to do", aMotorSaysAtOnceWhatItIsToldToDo},
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
        std::cout << "\nall motor tests passed\n";
        return 0;
    }
    std::cout << "\n" << failed << " of " << checks.size() << " motor tests failed\n";
    return 1;
}
