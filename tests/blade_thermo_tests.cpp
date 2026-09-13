// Blades and heat in one world: where the cutting model (docs/cutting-model.md)
// meets the thermochemical network (docs/thermochemistry.md).
//
//  1. A burning log cut in two: the halves hold between them exactly what the
//     log held -- the ledger's mass and energy residuals are what they were --
//     every half is as hot as the log was and goes on burning, and the heater
//     that was on the log goes on heating what is left of it.
//  2. A step the engine refuses in the middle of a cut changes nothing: the
//     network's fuel, gas, heat and ledger, and every kerf, severed bond,
//     booked joule and piece, are exactly what they were, and the step that is
//     then taken runs once.
//  3. A hand pushes once per step: moved between every step, and across a
//     refused one, the most it changes what it holds by is its strength times
//     the step.
#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "thermo/ThermoWorld.hpp"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

constexpr double kDt = 1.0 / 240.0;

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

std::unique_ptr<LiveWorld> openScene(const std::string &scene, double cell_m, bool gravity = true) {
    TileImpactRequest request;
    request.cell_size_m = cell_m;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(scene);
    readSceneSettings(scene, request);
    if (!gravity) request.gravity_m_s2 = {0.0, 0.0, 0.0};
    return LiveWorld::open(request);
}

std::string box(const std::string &name, const std::string &material, Vec3 size, Vec3 at,
                bool anchored, const std::string &extra = "") {
    char text[640];
    std::snprintf(text, sizeof text,
                  R"({"name":"%s","shape":"box","material":"%s","dimensions_m":[%g,%g,%g],)"
                  R"("center_m":[%g,%g,%g],"anchored":%s%s})",
                  name.c_str(), material.c_str(), size.x, size.y, size.z, at.x, at.y, at.z,
                  anchored ? "true" : "false", extra.c_str());
    return text;
}

const LiveBodyPose *poseOf(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    for (const LiveBodyPose &pose : poses)
        if (pose.name == name) return &pose;
    return nullptr;
}

// Everything the cutting side has done, to compare exactly.
struct CutState {
    std::size_t bodies{};
    double blade_area{}, blade_work{};
    std::size_t bonds{};
    double booked_area{}, booked_work{};
    double swept{};   // every kerf's swept strips, in m^2
    bool operator==(const CutState &other) const {
        return bodies == other.bodies && blade_area == other.blade_area &&
               blade_work == other.blade_work && bonds == other.bonds &&
               booked_area == other.booked_area && booked_work == other.booked_work &&
               swept == other.swept;
    }
};

CutState cutState(const LiveWorld &world) {
    CutState out;
    const auto poses = world.poses();
    out.bodies = poses.size();
    for (const LiveBlade &blade : world.blades()) {
        out.blade_area += blade.cut_area_m2;
        out.blade_work += blade.cut_work_j;
    }
    for (const LiveCut &cut : world.cuts()) {
        out.bonds += cut.bonds;
        out.booked_area += cut.area_m2;
        out.booked_work += cut.work_j;
    }
    for (const LiveBodyPose &pose : poses)
        for (const LiveBodyPose::Kerf &kerf : pose.kerfs)
            for (const LiveBodyPose::Kerf::Strip &strip : kerf.strips)
                out.swept += (strip.along_to - strip.along_from) * (strip.facing_to - strip.facing_from);
    return out;
}

bool sameNetwork(const thermo::ThermoState &a, const thermo::ThermoState &b) {
    if (a.time_s != b.time_s || a.lumps.size() != b.lumps.size()) return false;
    for (std::size_t k = 0; k < a.lumps.size(); ++k) {
        if (a.lumps[k].body != b.lumps[k].body ||
            a.lumps[k].surface.internal_energy_j != b.lumps[k].surface.internal_energy_j ||
            a.lumps[k].surface.kg != b.lumps[k].surface.kg ||
            a.lumps[k].core.internal_energy_j != b.lumps[k].core.internal_energy_j ||
            a.lumps[k].core.kg != b.lumps[k].core.kg)
            return false;
    }
    return a.ledger.matter_out_j == b.ledger.matter_out_j &&
           a.ledger.matter_in_j == b.ledger.matter_in_j &&
           a.ledger.heat_to_surroundings_j == b.ledger.heat_to_surroundings_j &&
           a.ledger.heater_in_j == b.ledger.heater_in_j;
}

// What every edge has met, for when a premise fails.
void sayCuts(const LiveWorld &world) {
    for (const LiveCut &cut : world.cuts())
        std::cout << "      " << cut.blade << " met " << cut.target << ": " << cut.kind << " at "
                  << cut.speed_m_s << " m/s, " << cut.area_m2 * 1e6 << " mm^2 for " << cut.work_j
                  << " J, " << cut.bonds << " bonds" << (cut.separated ? ", apart" : "")
                  << (cut.open ? " (still in it)" : "") << std::endl;
    for (const LiveBodyPose &pose : world.poses())
        std::cout << "      " << pose.name << " at (" << pose.position_m.x << ", " << pose.position_m.y
                  << ", " << pose.position_m.z << ")" << std::endl;
}

// ---------------------------------------------------------------------------

// A 300 mm oak log, 40 mm square, lying on the floor at 1000 K with 5 kW on it,
// and an iron cleaver pressed edge-down through its middle by a 300 N hand --
// a keen edge in oak resists 40 mm of it with 180 N.
void aBurningLogCutInTwoKeepsWhatItHeld() {
    const std::string scene =
        std::string(R"({"plasticity":true,"bodies":[)") +
        box("log", "oak", {0.3, 0.04, 0.04}, {0.0, 0.02, 0.0}, false, R"(,"temperature_k":1000)") + "," +
        box("cleaver", "iron", {0.01, 0.08, 0.12}, {0.0, 0.081, 0.0}, false) +
        R"(],"thermo":{"heaters":[{"target":"log","power_w":5000,"seconds":60}]}})";
    auto world = openScene(scene, 0.01);
    require(world->thermo() != nullptr && world->thermo()->holds("log"), "the log is in the network");
    require(world->blade("cleaver", {0.0, 0.041, -0.05}, {0.0, 0.041, 0.05}, {0.0, -1.0, 0.0},
                         0.01, 0.00005, 30.0, {0.0, 0.1, 0.0}) != 0,
            "the cleaver would not take an edge");
    require(world->wield("cleaver", {0.0, 0.1, 0.0}), "the hand would not take the cleaver");
    world->setHandStrength(300.0);

    // The step before it comes apart, and the step it does.
    thermo::BodyHeat log_before{};
    thermo::Ledger ledger_before{};
    bool cut = false;
    for (int i = 0; i < 1440 && !cut; ++i) {
        for (const thermo::BodyHeat &b : world->thermo()->bodies())
            if (b.body == "log") log_before = b;
        ledger_before = world->thermo()->ledger();
        world->moveHeld({0.0, -0.4, 0.0});
        world->step(kDt);
        if (world->steppedBack())
            for (const std::string &name : world->breakable()) world->declineBreak(name);
        cut = !world->thermo()->holds("log");
    }
    if (!cut) sayCuts(*world);
    require(cut, "the cleaver went through the log (the premise of this test)");
    require(log_before.reacting && log_before.fuel_kg > 0.0, "the log was burning when it was cut");

    const thermo::Ledger ledger_after = world->thermo()->ledger();
    double fuel = 0.0, mass = 0.0;
    std::vector<thermo::BodyHeat> halves;
    for (const thermo::BodyHeat &b : world->thermo()->bodies())
        if (b.body.rfind("log piece ", 0) == 0) {
            halves.push_back(b);
            fuel += b.fuel_kg;
            mass += b.mass_kg;
        }
    std::cout << "    cut at " << log_before.temperature_k << " K, " << log_before.fuel_kg * 1000.0
              << " g of fuel in " << log_before.mass_kg * 1000.0 << " g: " << halves.size()
              << " halves hold " << fuel * 1000.0 << " g of fuel in " << mass * 1000.0 << " g, at";
    for (const thermo::BodyHeat &h : halves) std::cout << " " << h.temperature_k << " K";
    std::cout << "; ledger residual " << ledger_before.residualJ() << " J before, "
              << ledger_after.residualJ() << " J after; mass residual "
              << ledger_after.massResidualKg() << " kg" << std::endl;
    require(halves.size() == 2, "the log came apart in two, and both are in the network");
    for (const thermo::BodyHeat &h : halves) {
        require(h.fuel_kg > 0.0, "each half keeps its share of the fuel");
        require(std::abs(h.temperature_k - halves.front().temperature_k) <= 1e-9 * h.temperature_k,
                "both halves are as hot as the log was when it came apart");
    }
    // One step of burning passes between the two readings, so the halves hold
    // the log's matter less what that step gave off -- and the ledger says so:
    // its residuals are unchanged by a cut, because nothing crosses its boundary.
    require(std::abs(ledger_after.residualJ() - ledger_before.residualJ()) <=
                1e-9 * std::abs(ledger_after.storedJ()),
            "cutting is not a crossing: the energy residual is what it was");
    require(std::abs(ledger_after.massResidualKg()) <= 1e-12 * ledger_after.mass_kg + 1e-15,
            "and no matter is made or lost");
    require(std::abs(mass - log_before.mass_kg) < 0.001 * log_before.mass_kg,
            "the halves weigh what the log did, less one step of burning");

    // And they go on burning, each on its own fuel.
    world->release();
    for (int i = 0; i < 240; ++i) {
        world->step(kDt);
        if (world->steppedBack())
            for (const std::string &name : world->breakable()) world->declineBreak(name);
    }
    int burning = 0, heated = 0;
    double heater_w = 0.0;
    for (const thermo::BodyHeat &b : world->thermo()->bodies()) {
        if (b.body.rfind("log piece ", 0) != 0) continue;
        if (b.reacting && b.heat_release_w > 0.0) ++burning;
        if (b.heater_w > 0.0) ++heated;
        heater_w += b.heater_w;
    }
    const thermo::Ledger later = world->thermo()->ledger();
    std::cout << "    a second later " << burning << " halves are burning, " << heated
              << " of them under the log's " << heater_w << " W heater; ledger residual "
              << later.residualJ() << " J on " << later.storedJ() << " J stored" << std::endl;
    require(burning == 2, "both halves burn on");
    // The heater was on the log. It is on what is left of the log -- one half,
    // the larger -- and it is still the heater it was.
    require(heated == 1 && std::abs(heater_w - 5000.0) < 1e-9,
            "the heater that was on the log goes on heating one half of it");
    require(std::abs(later.residualJ()) < 1e-9 * std::abs(later.storedJ()), "and the ledger closes");
}

// The thermochemistry test's pane and ball, to make the engine refuse steps,
// beside a burning log that a hand is pressing an iron edge down through.
void aRefusedStepInTheMiddleOfACutChangesNothing() {
    const std::string scene =
        std::string(R"({"plasticity":true,"bodies":[)") +
        box("pier left", "iron", {0.04, 0.12, 0.16}, {-0.1, 0.06, 0}, true) + "," +
        box("pier right", "iron", {0.04, 0.12, 0.16}, {0.1, 0.06, 0}, true) + "," +
        box("pane", "glass", {0.24, 0.02, 0.16}, {0, 0.13, 0}, false) + "," +
        R"({"name":"ball","shape":"sphere","material":"iron","dimensions_m":[0.06,0.06,0.06],)"
        R"("center_m":[0,0.3,0],"velocity_m_s":[0,-8,0]},)" +
        box("log", "oak", {0.3, 0.04, 0.04}, {1.0, 0.02, 0.0}, false, R"(,"temperature_k":1000)") + "," +
        box("cleaver", "iron", {0.01, 0.08, 0.12}, {1.0, 0.081, 0.0}, false) + "]}";
    auto world = openScene(scene, 0.01);
    require(world->blade("cleaver", {1.0, 0.041, -0.05}, {1.0, 0.041, 0.05}, {0.0, -1.0, 0.0},
                         0.01, 0.00005, 30.0, {1.0, 0.1, 0.0}) != 0,
            "the cleaver would not take an edge");
    require(world->wield("cleaver", {1.0, 0.1, 0.0}), "the hand would not take the cleaver");
    // A hand only a little stronger than the log's 180 N: the cut takes long
    // enough that the ball arrives while it is going on.
    world->setHandStrength(250.0);
    int refused = 0, refused_while_cutting = 0;
    for (int i = 0; i < 480 && refused < 3; ++i) {
        // Pressed down with everything the hand has, every step.
        world->moveHeld({1.0, -0.4, 0.0});
        const thermo::ThermoState network = world->thermo()->state();
        const CutState before = cutState(*world);
        const bool cutting = !world->blades().front().cutting.empty();
        world->step(kDt);
        if (!world->steppedBack()) continue;
        ++refused;
        if (cutting) ++refused_while_cutting;
        std::cout << "      refused at step " << i << (cutting ? ", the edge in the log" : ", the edge not in it")
                  << "; cut so far " << before.booked_area * 1e6 << " mm^2" << std::endl;
        require(sameNetwork(world->thermo()->state(), network),
                "a refused step burns nothing: fuel, gas, heat and ledger are exactly as before");
        require(cutState(*world) == before,
                "and cuts nothing: every kerf, bond, booked joule and piece is as it was");
        // Answered by declining: what is being tested is the refusal and the
        // retry, not the pane -- and breaking 768 cells of glass three times over
        // took nine seconds of a two-second world.
        for (const std::string &name : world->breakable()) world->declineBreak(name);
        const double t = world->thermo()->timeS();
        const CutState answered = cutState(*world);
        world->step(kDt);
        if (!world->steppedBack()) {
            require(std::abs(world->thermo()->timeS() - (t + kDt)) < 1e-12,
                    "the step then taken runs the network once");
            const CutState after = cutState(*world);
            require(after.booked_work >= answered.booked_work && after.swept >= answered.swept,
                    "and the cut goes on from where it was");
        }
    }
    const CutState end = cutState(*world);
    std::cout << "    " << refused << " steps refused, " << refused_while_cutting
              << " with the edge in the log; the cut stands at " << end.booked_area * 1e6
              << " mm^2 for " << end.booked_work << " J, " << end.bonds << " bonds" << std::endl;
    require(refused > 0, "the ball struck the pane and a step was refused");
    if (refused_while_cutting == 0) sayCuts(*world);
    require(refused_while_cutting > 0, "a step was refused while the edge was in the log");
    require(end.booked_work > 0.0, "and the log was cut");
}

// No gravity, an iron bar held at one end, the hand told every step to be two
// metres away: it pulls with all it has, every step, and never more. And the
// pane and ball again, so that some of those steps are refused and retried.
void aHandPushesOncePerStep() {
    const std::string scene =
        std::string(R"({"plasticity":true,"bodies":[)") +
        box("pier left", "iron", {0.04, 0.12, 0.16}, {-0.1, 0.06, 0}, true) + "," +
        box("pier right", "iron", {0.04, 0.12, 0.16}, {0.1, 0.06, 0}, true) + "," +
        box("pane", "glass", {0.24, 0.02, 0.16}, {0, 0.13, 0}, false) + "," +
        R"({"name":"ball","shape":"sphere","material":"iron","dimensions_m":[0.06,0.06,0.06],)"
        R"("center_m":[0,0.3,0],"velocity_m_s":[0,-8,0]},)" +
        box("bar", "iron", {0.6, 0.02, 0.04}, {1.5, 1.0, 0.0}, false) + "]}";
    auto world = openScene(scene, 0.02, false);
    require(world->wield("bar", {1.25, 1.0, 0.0}), "the hand would not take the bar");
    const double mass = 0.6 * 0.02 * 0.04 * 7870.0;
    const double most = world->handStrength() * kDt;
    double hardest = 0.0, softest = 1e9;
    int refused = 0, accepted = 0;
    // A tenth of a second: far enough from the target that the hand pulls with
    // all it has the whole time.
    for (int i = 0; i < 24; ++i) {
        world->moveHeld({3.5, 1.0, 0.0});
        const Vec3 v0 = poseOf(world->poses(), "bar")->velocity_m_s;
        world->step(kDt);
        if (world->steppedBack()) {
            ++refused;
            for (const std::string &name : world->breakable()) world->declineBreak(name);
            continue;
        }
        ++accepted;
        const Vec3 v1 = poseOf(world->poses(), "bar")->velocity_m_s;
        const double change = mass * length(v1 - v0);
        hardest = std::max(hardest, change);
        softest = std::min(softest, change);
    }
    std::cout << "    " << accepted << " steps, " << refused << " refused: the hand changed the "
              << "bar's momentum by " << softest << " to " << hardest << " kg m/s a step, against "
              << most << " for its " << world->handStrength() << " N" << std::endl;
    require(refused > 0, "some steps were refused");
    require(hardest <= 1.02 * most, "the hand pushed more than once in a step");
    require(softest >= 0.8 * most, "the hand did not use the strength it has");
}

} // namespace

int main(int argc, char **argv) {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"a burning log cut in two keeps what it held", aBurningLogCutInTwoKeepsWhatItHeld},
        {"a refused step in the middle of a cut changes nothing",
         aRefusedStepInTheMiddleOfACutChangesNothing},
        {"a hand pushes once per step", aHandPushesOncePerStep},
    };
    unsigned failures = 0, ran = 0;
    for (const auto &[name, test] : tests) {
        if (argc > 1 && std::string_view(argv[1]) != name) continue;
        ++ran;
        const auto started = std::chrono::steady_clock::now();
        try {
            test();
            std::cout << "[PASS] " << name;
        } catch (const std::exception &error) {
            ++failures;
            std::cout << "[FAIL] " << name << ": " << error.what();
        }
        std::cout << " (" << std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count()
                  << " s)" << std::endl;
    }
    std::cout << ran - failures << '/' << ran << " tests passed" << std::endl;
    return failures == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
}
