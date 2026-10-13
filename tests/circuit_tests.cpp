#include "machines/Circuit.hpp"
#include "fastlattice/LiveWorld.hpp"
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {
using nlohmann::json;
using namespace banjo;
using namespace banjo::machines;
using namespace banjo::fastlattice;
void check(bool ok, const std::string &why) { if (!ok) throw std::runtime_error(why); }
void near(double value, double expected, double tolerance, const char *why) {
    check(std::abs(value - expected) <= tolerance, std::string(why) + ": " + std::to_string(value));
}
template<class F> void rejects(F f) {
    bool rejected = false;
    try { f(); } catch (const std::exception &) { rejected = true; }
    check(rejected, "invalid declaration was accepted");
}
json network() {
    return {{"schema", "banjo.circuit.v1"}, {"id", "test"}, {"nodes", {"p", "n", "bus"}},
        {"source", {{"store", 1}, {"positive", "p"}, {"negative", "n"}, {"resistance_ohm", 1.0}, {"thermal", "case"}}},
        {"thermal_nodes", {{{"id", "case"}, {"component", "battery"}, {"capacity_j_k", 100.0}},
                           {{"id", "winding"}, {"component", "motor"}, {"capacity_j_k", 10.0}}}},
        {"thermal_links", {{{"a", "winding"}, {"b", "case"}, {"conductance_w_k", 1.0}}}},
        {"branches", {{{"id", "one"}, {"kind", "resistor"}, {"component", "load1"}, {"a", "p"}, {"b", "n"},
                        {"thermal", "winding"}, {"resistance_ohm", 10.0}},
                       {{"id", "two"}, {"kind", "resistor"}, {"component", "load2"}, {"a", "p"}, {"b", "n"},
                        {"thermal", "case"}, {"resistance_ohm", 10.0}}}}};
}
void circuitsAndHeat() {
    auto c = Circuit::read(network());
    auto s = c.solve(0.1, 24.0, 1000.0, 0.0, {});
    near(s.source_current_a, 4.0, 1e-12, "parallel current");
    near(s.current_a[0], 2.0, 1e-12, "load current");
    near(s.electrical_residual_j, 0.0, 1e-12, "electrical balance");
    near(s.max_kcl_a, 0.0, 1e-12, "junction balance");
    s = c.solve(0.1, 24.0, 1000.0, 48.0, {});
    near(s.source_j, 4.8, 1e-12, "shared power budget");
    near(s.current_a[0], 1.0, 1e-12, "weak supply load one");
    near(s.current_a[1], 1.0, 1e-12, "weak supply load two");
    auto reversed = network(); std::reverse(reversed["branches"].begin(), reversed["branches"].end());
    near(Circuit::read(reversed).solve(0.1, 24.0, 1000.0, 48.0, {}).source_j, s.source_j, 1e-12, "order invariance");
    c.commit(s, 0.0);
    const auto saved = c.saved();
    near(saved["ledger"]["thermal_residual_j"], 0.0, 1e-10, "thermal balance");
    check(saved["thermal_nodes"][0]["temperature_k"].get<double>() > 293.15, "supply did not heat");
    check(saved["thermal_nodes"][1]["temperature_k"].get<double>() > 293.15, "load did not heat");
    auto restored = Circuit::read(saved, true);
    near(restored.solve(0.1, 24, 0.3, 0, {}).source_j, 0.3, 1e-12, "finite final joules");
    near(c.solve(0.1, 24, 0, 0, {}).source_j, 0, 1e-12, "empty source");
    // Merely calculating a trial neither warms nor consumes a fuse.
    check(c.saved() == saved, "an uncommitted trial mutated the circuit");
    auto cooling = network(); cooling["branches"] = json::array();
    cooling["thermal_nodes"][0]["temperature_k"] = 400.0;
    cooling["thermal_nodes"][0]["ambient_w_k"] = 10.0;
    auto cool = Circuit::read(cooling); cool.commit(cool.solve(100, 24, 0, 0, {}), 0);
    check(cool.saved()["thermal_nodes"][0]["temperature_k"].get<double>() < 400, "no cooling");
    near(cool.saved()["ledger"]["thermal_residual_j"], 0, 1e-8, "cooling energy");
}
void switchingFailureAndValidation() {
    auto d = network();
    d["branches"][0]["kind"] = "switch";
    d["branches"][1]["kind"] = "fuse"; d["branches"][1]["fuse_a2_s"] = 0.1;
    auto c = Circuit::read(d);
    c.setSwitch("one", false);
    auto s = c.solve(0.1, 24, 100, 0, {});
    near(s.current_a[0], 0.0, 1e-12, "open switch leaks");
    c.commit(s, 0.0);
    check(c.saved()["branches"][1]["failed"].get<bool>(), "fuse did not open");
    auto back = Circuit::read(c.saved(), true);
    near(back.solve(0.1, 24, 100, 0, {}).source_j, 0.0, 1e-10, "failed fuse reset on restore");
    back.setSwitch("one", true);
    check(back.solve(0.1, 24, 100, 0, {}).source_j > 0.0, "switch did not reclose");
    auto wire = network(); wire["branches"].erase(1);
    wire["branches"][0]["kind"] = "wire"; wire["branches"][0]["alpha_per_k"] = 0.004;
    auto cold = Circuit::read(wire).solve(0.1, 24, 100, 0, {}).source_current_a;
    wire["thermal_nodes"][1]["temperature_k"] = 393.15;
    check(Circuit::read(wire).solve(0.1, 24, 100, 0, {}).source_current_a < cold, "hot wire resistance unchanged");
    wire["branches"][0]["trip_k"] = 390;
    auto hot = Circuit::read(wire); hot.commit(hot.solve(.1, 24, 100, 0, {}), 0);
    check(hot.saved()["branches"][0]["failed"].get<bool>(), "wire did not fail");
    rejects([&] { auto bad = d; bad["branches"][0]["a"] = "missing"; Circuit::read(bad); });
    rejects([&] { auto bad = d; bad["branches"][0]["resistance_ohm"] = 0; Circuit::read(bad); });
    rejects([&] { auto bad = d; bad["branches"][1]["kind"] = "diode"; Circuit::read(bad); });
    rejects([&] { c.setSwitch("two", true); });
    rejects([&] { (void)c.solve(-1, 24, 100, 0, {}); });
}
void bulbEnergyAndSharedSupply() {
    auto d = network();
    d["branches"][0]["kind"] = "bulb";
    d["branches"][0]["lamp"] = 1;
    d["branches"][0]["efficiency"] = .2;
    auto c = Circuit::read(d);
    const auto s = c.solve(.1, 24, 1000, 48, {});
    near(s.source_j, 4.8, 1e-12, "bulb shared supply");
    near(s.emitted_j, .2, 1e-12, "bounded bulb light");
    near(s.branch_heat_j[0], .8, 1e-12, "bulb heat fraction");
    near(s.electrical_residual_j, 0, 1e-12, "bulb full energy transfer");
    c.commit(s, 0);
    const auto saved = c.saved();
    near(saved["ledger"]["emitted_j"], .2, 1e-12, "emission ledger");
    near(saved["branches"][0]["power_w"], 10, 1e-12, "measured bulb power");
    near(Circuit::read(saved, true).solve(.1, 24, 0, 0, {}).emitted_j, 0, 1e-12, "empty bulb emitted light");
    rejects([&] { auto bad = d; bad["branches"][0]["efficiency"] = 1.1; Circuit::read(bad); });

    TileImpactRequest scene;
    scene.cell_size_m = .05; scene.gravity_m_s2 = {0, 0, 0};
    SceneBody post;
    post.name = "post"; post.shape = BodyShape::Box; post.material = MaterialPreset::Iron;
    post.dimensions_m = {.2, .2, .2}; post.center_m = {0, 1, 0}; post.anchored = true;
    scene.bodies = {post};
    auto world = LiveWorld::open(scene);
    const unsigned store = world->energyStore("battery", "post", 100, 100, 24, 0);
    const unsigned lamp = world->lamp("bulb", "post", 0, 0, {0, 1.3, 0}, 10, 683);
    check(world->lampLight("bulb light", lamp, {0, 1, 0}, 180, 48, 683) != 0, "bulb optics was not built");
    auto live = d;
    live["source"]["store"] = store;
    live["branches"][0]["lamp"] = lamp;
    world->circuit(live.dump());
    for (int i = 0; i < 24; ++i) world->step(1.0 / 240);
    const auto ledger = json::parse(world->circuits())[0]["ledger"];
    near(100 - world->energyStores()[0].charge_j, ledger["source_j"], 1e-9, "lamp duplicated battery draw");
    check(world->lamps()[0].lit, "solved bulb failed to emit");
    world->traceLight();
    const auto live_network = json::parse(world->circuits())[0];
    near(world->optics().watts.sent, live_network["branches"][0]["emitted_w"], 1e-10, "light trace lost solved power");
    near(world->optics().watts.residual(), 0, 1e-10, "optical transfer ledger");
    std::string why;
    const auto restored = LiveWorld::open(scene, world->snapshot(why));
    restored->step(1.0 / 240);
    check(restored->lamps()[0].lit, "circuit lamp lost on restore");
}
TileImpactRequest room(bool locked = false, bool free_housing = false) {
    TileImpactRequest r; r.cell_size_m = 0.05; r.backend = BackendKind::CpuParallel;
    r.gravity_m_s2 = {0, 0, 0};
    SceneBody post; post.name = "post"; post.shape = BodyShape::Box; post.material = MaterialPreset::Iron;
    post.dimensions_m = {0.2, 0.2, 0.2}; post.center_m = {0, 1, 0}; post.anchored = !free_housing;
    SceneBody wheel = post; wheel.name = "wheel"; wheel.dimensions_m = {0.4, 0.1, 0.4};
    wheel.center_m = {0, 1.3, 0}; wheel.anchored = locked;
    r.bodies = {post, wheel}; return r;
}
json motorNetwork(unsigned store, unsigned motor, double ratio = 1.0) {
    auto d = network(); d["source"]["store"] = store;
    d["source"]["resistance_ohm"] = 0.1;
    d["branches"] = json::array({
        {{"id", "switch"}, {"kind", "switch"}, {"component", "switch"}, {"a", "p"}, {"b", "bus"},
         {"thermal", "case"}, {"resistance_ohm", 0.1}},
        {{"id", "motor"}, {"kind", "motor"}, {"component", "motor"}, {"a", "bus"}, {"b", "n"},
         {"thermal", "winding"}, {"motor", motor}, {"gear_ratio", ratio}}});
    return d;
}
void liveLoopAndRestore() {
    const auto r = room(); auto w = LiveWorld::open(r);
    const auto pin = w->hinge("post", "wheel", {0, 1.3, 0}, {0, 1, 0});
    const auto store = w->energyStore("battery", "post", 1000, 1000, 24, 50);
    const auto motor = w->motor(pin, store, 10, 10);
    check(pin && store && motor, "could not build machine");
    const auto circuit = w->circuit(motorNetwork(store, motor, 2).dump());
    const auto before_invalid_step = w->circuits();
    rejects([&] { w->step(1.0); });
    check(w->circuits() == before_invalid_step, "refused timestep changed circuit state");
    check(w->driveMotor(motor, 1), "no command");
    rejects([&] { w->circuit(motorNetwork(store, motor).dump()); });
    for (int i = 0; i < 240; ++i) w->step(1.0 / 240);
    const auto m = w->motors().front(); const auto battery = w->energyStores().front();
    check(m.speed_rad_s > 0.1 && m.speed_rad_s < 5.1, "gearbox motor speed outside line");
    check(m.heat_j > 0 && battery.charge_j < 1000, "motor did not spend and heat");
    check(battery.given_j <= 50.0 + 1e-8, "shared supply exceeded power");
    auto report = json::parse(w->circuits())[0];
    near(report["ledger"]["source_j"], battery.given_j, 1e-9, "world store differs from circuit");
    near(report["ledger"]["electrical_residual_j"], 0, 1e-8, "live circuit residual");
    check(std::abs(report["ledger"]["coupling_residual_j"].get<double>()) < 0.25,
          "electromechanical timestep residual too large");
    std::cout << "live 1s: speed=" << m.speed_rad_s << " charge=" << battery.charge_j
              << " coupling_residual_j=" << report["ledger"]["coupling_residual_j"] << '\n';
    w->circuitSwitch(circuit, "switch", false);
    std::string why; const auto snapshot = w->snapshot(why);
    check(!snapshot.empty(), "snapshot failed: " + why);
    auto resumed = LiveWorld::open(r, snapshot);
    auto resumed_report = json::parse(resumed->circuits())[0];
    check(resumed_report == json::parse(w->circuits())[0], "reopening lost circuit readings or state");
    check(resumed_report["thermal_nodes"] == report["thermal_nodes"], "reopening cooled machine");
    near(resumed->energyStores()[0].charge_j, battery.charge_j, 1e-10, "reopening charged battery");
    for (int i = 0; i < 12; ++i) { w->step(1.0 / 240); resumed->step(1.0 / 240); }
    near(resumed->energyStores()[0].charge_j, battery.charge_j, 1e-8, "open switch spent energy");
    near(resumed->motors()[0].current_a, 0, 1e-10, "open motor carries current");
    near(resumed->motors()[0].speed_rad_s, w->motors()[0].speed_rad_s, 1e-5, "restart changed motion");
    near(resumed->motors()[0].speed_rad_s, m.speed_rad_s, 1e-4, "open switch prescribed stop");
}
void stalledAndEmpty() {
    // Hinge travel fixed at zero is a real mechanical obstruction.
    auto w = LiveWorld::open(room());
    const auto pin = w->hinge("post", "wheel", {0, 1.3, 0}, {0, 1, 0}, 0, 0);
    const auto store = w->energyStore("battery", "post", 1, 1, 24, 10);
    const auto motor = w->motor(pin, store, 10, 10);
    w->circuit(motorNetwork(store, motor).dump()); w->driveMotor(motor, 1);
    for (int i = 0; i < 60; ++i) w->step(1.0 / 240);
    near(w->energyStores()[0].charge_j, 0, 1e-8, "battery did not exhaust");
    near(w->motors()[0].speed_rad_s, 0, 1e-5, "stalled motor moves through stop");
    check(w->motors()[0].heat_j > 0, "stall did not heat");
    const auto report = json::parse(w->circuits())[0];
    near(report["ledger"]["heat_j"], 1, 1e-7, "stall energy did not become heat");
}
void sharedMotorsAndGeneration() {
    auto d = motorNetwork(1, 1); auto second = d["branches"][1];
    second["id"] = "second"; second["motor"] = 2; d["branches"].push_back(second);
    auto c = Circuit::read(d);
    const std::vector<CircuitMotorInput> inputs{{1, 1, 0, 2.4, 5.76}, {2, 1, 0, 2.4, 5.76}};
    auto shared = c.solve(.01, 24, 100, 48, inputs);
    near(shared.source_j, .48, 1e-12, "two motors double spent supply");
    near(shared.motor_current_a[1], 1, 1e-12, "first motor unfair allocation");
    near(shared.motor_current_a[2], 1, 1e-12, "second motor unfair allocation");
    auto off = inputs; off[1].command = 0;
    near(c.solve(.01, 24, 100, 48, off).motor_current_a[1], 2, 1e-12, "loads do not interact");
    auto back = inputs; back[0].speed_rad_s = 30; back[1].command = .5;
    const auto generated = c.solve(.01, 24, 100, 48, back);
    near(generated.source_j, 0, 1e-12, "backdrive charged a non-rechargeable supply");
    check(generated.shaft_j[1] < 0 && generated.motor_current_a[2] > 0, "backdrive did not power connected load");
    near(generated.electrical_residual_j, 0, 1e-10, "backdrive energy balance");
}
void housingReactionAndConvergence() {
    auto w = LiveWorld::open(room(false, true));
    const auto pin = w->hinge("post", "wheel", {0, 1.3, 0}, {0, 1, 0});
    const auto store = w->energyStore("battery", "", 1000, 1000);
    const auto motor = w->motor(pin, store, 10, 10);
    w->circuit(motorNetwork(store, motor).dump()); w->driveMotor(motor, 1);
    w->step(1.0 / 1000);
    const auto poses = w->poses();
    double momentum = 0.0; double total = 0.0;
    for (const auto &p : poses) {
        // Both start at identity and rotate about y. The first step's
        // quaternion gives their independently measured angular displacements.
        const double omega = 2.0 * std::atan2(p.orientation_wxyz[2], p.orientation_wxyz[0]) * 1000.0;
        const double angular = w->inertiaAbout(p.name, {0, 1, 0}) * omega;
        momentum += angular; total += std::abs(angular);
    }
    check(total > 0, "free housing and shaft did not respond");
    near(momentum, 0, 1e-6, "housing reaction lost angular momentum");
    double previous = 1e9;
    for (int hz : {120, 240, 480}) {
        auto trial = LiveWorld::open(room());
        const auto j = trial->hinge("post", "wheel", {0, 1.3, 0}, {0, 1, 0});
        const auto battery = trial->energyStore("battery", "post", 1000, 1000, 24, 50);
        const auto drive = trial->motor(j, battery, 10, 10);
        trial->circuit(motorNetwork(battery, drive, 2).dump()); trial->driveMotor(drive, 1);
        for (int i = 0; i < hz; ++i) trial->step(1.0 / hz);
        const auto ledger = json::parse(trial->circuits())[0]["ledger"];
        const double omega = trial->motors()[0].speed_rad_s;
        const double kinetic = .5 * trial->inertiaAbout("wheel", {0, 1, 0}) * omega * omega;
        // Whole mechanical/electrical/thermal boundary, independently from the
        // circuit's own conversion-work counters.
        const double residual = ledger["source_j"].get<double>() - ledger["heat_j"].get<double>() - kinetic;
        check(std::abs(residual) < .65 * previous, "whole-loop energy did not converge with timestep");
        previous = std::abs(residual);
        std::cout << "loop " << hz << " Hz: source=" << ledger["source_j"] << " heat=" << ledger["heat_j"]
                  << " kinetic=" << kinetic << " whole_residual=" << residual
                  << " coupling=" << ledger["coupling_residual_j"] << '\n';
    }
    check(previous < .1, "fine-step whole-loop residual exceeds measured budget");
}
// A coil wound on a world body and a switch worked by a pin: the two links a
// machine needs between its circuit and the rest of the world.
json coilNetwork(unsigned store, unsigned pin) {
    return {{"schema", "banjo.circuit.v1"}, {"id", "coil"}, {"nodes", {"p", "n", "in"}},
        {"source", {{"store", store}, {"positive", "p"}, {"negative", "n"}, {"resistance_ohm", 0.05}, {"thermal", "pack"}}},
        {"thermal_nodes", {{{"id", "pack"}, {"component", "battery"}, {"capacity_j_k", 500.0}}}},
        {"branches", {{{"id", "lever switch"}, {"kind", "switch"}, {"component", "switch"}, {"a", "p"}, {"b", "in"},
                        {"thermal", "pack"}, {"resistance_ohm", 0.001}, {"closed", false},
                        {"follows_hinge", {{"joint", pin}, {"closed_at_or_below_deg", -20.0}}}},
                       {{"id", "coil"}, {"kind", "resistor"}, {"component", "heating coil"}, {"a", "in"}, {"b", "n"},
                        {"resistance_ohm", 1.0}, {"heats_body", "peg"}}}}};
}
void hingeSwitchAndBodyHeat() {
    // The circuit alone: a world-heating branch leaves its own lumped nodes.
    auto alone = Circuit::read(coilNetwork(1, 1));
    alone.setSwitch("lever switch", true);
    auto s = alone.solve(0.1, 24.0, 1.0e6, 0.0, {});
    const double current = 24.0 / (0.05 + 0.001 + 1.0);
    near(s.current_a[1], current, 1e-12, "coil current");
    near(s.exported_j, current * current * 1.0 * 0.1, 1e-12, "exported coil heat");
    near(s.electrical_residual_j, 0.0, 1e-12, "balance with exported heat");
    const auto owed = alone.bodyHeat(s);
    check(owed.size() == 1 && owed[0].body == "peg" && std::abs(owed[0].joules - s.exported_j) < 1e-12,
          "coil heat not owed to its body");
    auto kept = s; alone.keepHeat(kept, "coil");
    near(kept.exported_j, 0.0, 1e-12, "kept heat still exported");
    near(kept.heat_j[0], s.heat_j[0] + s.exported_j, 1e-12, "kept heat not in its node");
    alone.commit(s, 0.0);
    const auto saved = alone.saved();
    near(saved["ledger"]["exported_j"], s.exported_j, 1e-12, "exported heat not on the ledger");
    check(saved["branches"][1]["heats_body"] == "peg", "heats_body lost on save");
    check(saved["branches"][0]["follows_hinge"]["joint"] == 1, "follows_hinge lost on save");
    near(Circuit::read(saved, true).saved()["ledger"]["exported_j"], s.exported_j, 1e-12, "restore lost exported heat");
    rejects([] { auto bad = coilNetwork(1, 1); bad["branches"][0]["heats_body"] = "peg"; Circuit::read(bad); });
    rejects([] { auto bad = coilNetwork(1, 1); bad["branches"][1]["alpha_per_k"] = 0.004; Circuit::read(bad); });
    rejects([] { auto bad = coilNetwork(1, 1); bad["branches"][1]["follows_hinge"] = {{"joint", 1}, {"closed_at_or_above_deg", 5}}; Circuit::read(bad); });
    rejects([] { auto bad = coilNetwork(1, 1);
                 bad["branches"][0]["follows_hinge"]["closed_at_or_above_deg"] = 5.0; Circuit::read(bad); });

    // In a world: a bar swings down on its pin; past -20 degrees its switch
    // closes and the coil warms an oak peg through the world's heat network.
    TileImpactRequest r; r.cell_size_m = 0.05; r.backend = BackendKind::CpuParallel;
    r.gravity_m_s2 = {0, -9.81, 0};
    SceneBody post; post.name = "post"; post.shape = BodyShape::Box; post.material = MaterialPreset::Iron;
    post.dimensions_m = {0.2, 0.2, 0.2}; post.center_m = {0, 1, 0}; post.anchored = true;
    SceneBody bar = post; bar.name = "bar"; bar.material = MaterialPreset::Oak; bar.anchored = false;
    bar.dimensions_m = {0.6, 0.05, 0.1}; bar.center_m = {0.45, 1.0, 0};
    SceneBody peg = post; peg.name = "peg"; peg.material = MaterialPreset::Oak;
    peg.dimensions_m = {0.1, 0.1, 0.1}; peg.center_m = {2.0, 0.5, 0};
    r.bodies = {post, bar, peg};
    auto w = LiveWorld::open(r);
    const auto pin = w->hinge("post", "bar", {0.15, 1.0, 0}, {0, 0, 1});
    const auto store = w->energyStore("battery", "post", 1.0e5, 1.0e5, 24, 0);
    check(pin && store, "could not build the coil machine");
    rejects([&] { auto bad = coilNetwork(store, pin); bad["branches"][1]["heats_body"] = "nothing here"; w->circuit(bad.dump()); });
    rejects([&] { auto bad = coilNetwork(store, pin + 7); w->circuit(bad.dump()); });
    const auto circuit = w->circuit(coilNetwork(store, pin).dump());
    rejects([&] { w->circuitSwitch(circuit, "lever switch", true); });
    double closed_at = -1.0, last_deg = 0.0;
    for (int i = 0; i < 480; ++i) {
        w->step(1.0 / 240);
        const auto report = json::parse(w->circuits())[0];
        for (const LiveJoint &j : w->joints()) if (j.id == pin) last_deg = j.at * 180.0 / 3.14159265358979323846;
        if (closed_at < 0.0 && report["branches"][0]["closed"].get<bool>()) {
            closed_at = (i + 1) / 240.0;
            // Read at the start of the step that closed it, so the pin was at or past the
            // reading one step before; after that step it is further on still.
            check(last_deg <= -20.0, "switch closed before its pin reached -20 degrees");
        }
        if (closed_at < 0.0) near(report["ledger"]["source_j"], 0.0, 1e-12, "open switch drew current");
    }
    check(closed_at > 0.0, "the swinging bar never closed its switch");
    const auto report = json::parse(w->circuits())[0];
    const auto heat = json::parse(w->thermoReport(false));
    const double exported = report["ledger"]["exported_j"], received = heat["ledger"]["heater_in_j"];
    // Closed from the start of the step that first reported it closed, at a
    // constant current (no power limit): I^2 R for exactly that long.
    const double closed_for = 480.0 / 240.0 - closed_at + 1.0 / 240.0;
    near(exported, current * current * 1.0 * closed_for, 1e-9 * exported, "coil heat differs from I^2 R t");
    near(received, exported, 1e-9 * exported, "world heat network did not receive the coil's heat");
    near(report["ledger"]["electrical_residual_j"], 0.0, 1e-8, "electrical balance in the world");
    double peg_k = 0.0;
    for (const auto &b : heat["bodies"]) if (b["name"] == "peg") peg_k = b["temperature_k"];
    check(peg_k > 293.15 + 0.01, "the peg did not warm");
    std::cout << "hinge switch closed at " << closed_at << " s; coil " << exported << " J out, " << received
              << " J into the peg, now " << peg_k << " K\n";
}
// A switch closed by contact: a ball dropped onto a plate closes it as the two
// touch, measured from their shapes -- not when the solver first pairs them,
// which Jolt does up to 2 cm apart -- and it stays closed while the ball lies
// on the plate.
json touchNetwork(unsigned store) {
    auto n = coilNetwork(store, 1);
    n["branches"][0].erase("follows_hinge");
    n["branches"][0]["follows_contact"] = {{"a", "ball"}, {"b", "plate"}};
    return n;
}
void contactSwitch() {
    const auto alone = Circuit::read(touchNetwork(1));
    check(alone.contactSwitches().size() == 1 && alone.contactSwitches()[0].a == "ball" &&
              alone.contactSwitches()[0].b == "plate", "contact switch not read");
    check(alone.saved()["branches"][0]["follows_contact"]["b"] == "plate", "follows_contact lost on save");
    rejects([] { auto bad = touchNetwork(1); bad["branches"][0]["follows_contact"]["b"] = "ball"; Circuit::read(bad); });
    rejects([] { auto bad = touchNetwork(1);
                 bad["branches"][0]["follows_hinge"] = {{"joint", 1}, {"closed_at_or_above_deg", 5}}; Circuit::read(bad); });
    rejects([] { auto bad = touchNetwork(1); bad["branches"][1]["follows_contact"] = {{"a", "ball"}, {"b", "plate"}};
                 Circuit::read(bad); });

    TileImpactRequest r; r.cell_size_m = 0.05; r.backend = BackendKind::CpuParallel;
    r.gravity_m_s2 = {0, -9.81, 0};
    SceneBody plate; plate.name = "plate"; plate.shape = BodyShape::Box; plate.material = MaterialPreset::Iron;
    plate.dimensions_m = {0.4, 0.1, 0.4}; plate.center_m = {0, 0.05, 0}; plate.anchored = true;
    SceneBody ball = plate; ball.name = "ball"; ball.anchored = false;
    ball.dimensions_m = {0.1, 0.1, 0.1}; ball.center_m = {0, 0.6, 0};
    SceneBody peg = plate; peg.name = "peg"; peg.material = MaterialPreset::Oak;
    peg.dimensions_m = {0.1, 0.1, 0.1}; peg.center_m = {1.0, 0.05, 0};
    r.bodies = {plate, ball, peg};
    auto w = LiveWorld::open(r);
    const auto store = w->energyStore("battery", "plate", 1.0e5, 1.0e5, 24, 0);
    rejects([&] { auto bad = touchNetwork(store); bad["branches"][0]["follows_contact"]["a"] = "nothing here";
                  w->circuit(bad.dump()); });
    const auto circuit = w->circuit(touchNetwork(store).dump());
    rejects([&] { w->circuitSwitch(circuit, "lever switch", true); });
    double closed_at = -1.0;
    for (int i = 0; i < 480; ++i) {
        // Where the ball stands at the start of the step: what the switch is set from.
        double bottom = 0.0;
        for (const auto &p : w->poses()) if (p.name == "ball") bottom = p.position_m.y - 0.05;
        w->step(1.0 / 240);
        const bool closed = json::parse(w->circuits())[0]["branches"][0]["closed"].get<bool>();
        if (closed_at < 0.0 && closed) {
            closed_at = (i + 1) / 240.0;
            check(bottom - 0.1 <= 0.001 + 1e-6, "switch closed with the ball still above the plate");
        }
        if (closed_at < 0.0) check(bottom - 0.1 > 0.001, "the ball touched the plate and the switch stayed open");
    }
    check(closed_at > 0.0, "the dropped ball never closed its switch");
    check(json::parse(w->circuits())[0]["branches"][0]["closed"].get<bool>(),
          "the switch opened with the ball at rest on the plate");
    std::cout << "contact switch closed at " << closed_at << " s\n";
}
}
// Electrical storage oracles are material-neutral. Housing comparisons live
// in the product regressions; a resistor/capacitor rating is not a bulk law.
void capacitorTransients() {
    auto declaration = network();
    declaration["nodes"] = {"p", "n", "bus"};
    declaration["source"]["resistance_ohm"] = 1.0;
    declaration["branches"] = json::array({
        {{"id","feed"},{"component","feed"},{"kind","switch"},{"a","p"},{"b","bus"},
         {"thermal","case"},{"resistance_ohm",9.0}},
        {{"id","storage"},{"component","storage"},{"kind","capacitor"},{"a","bus"},{"b","n"},
         {"thermal","winding"},{"resistance_ohm",.1},{"capacitance_f",.1}}});
    double previous_error = 1.0, previous_loss = 100.0;
    for (const double dt : {.01, .005, .0025}) {
        auto circuit = Circuit::read(declaration);
        const auto before = circuit.saved();
        (void)circuit.solve(dt,12,1000,0,{});
        check(circuit.saved()==before,"trial charged a capacitor");
        for (int k=0;k<static_cast<int>(std::round(1.0/dt));++k) {
            const auto step = circuit.solve(dt,12,1000,0,{});
            near(step.electrical_residual_j,0,1e-10,"RC energy balance");
            circuit.commit(step,0);
        }
        auto state = circuit.saved();
        const double voltage = state["branches"][1]["capacitor_voltage_v"];
        const double exact = 12*(1-std::exp(-1.0/1.01));
        const double error = std::abs(voltage-exact);
        const double loss = state["ledger"]["numerical_loss_j"];
        check(error<previous_error && loss<previous_loss,"RC did not converge with timestep");
        check(error<.025,"RC charging curve wrong");
        previous_error=error;previous_loss=loss;
        near(state["ledger"]["source_j"].get<double>(),
             state["ledger"]["heat_j"].get<double>()+state["ledger"]["storage_delta_j"].get<double>()+loss,
             1e-9,"RC complete energy transfer");
        auto resumed = Circuit::read(state,true);
        circuit.setSwitch("feed",false);resumed.setSwitch("feed",false);
        const auto isolated = circuit.solve(dt,12,0,0,{});
        near(isolated.current_a[1],0,1e-10,"isolated capacitor loses charge");
        circuit.commit(isolated,0);
        resumed.commit(resumed.solve(dt,12,0,0,{}),0);
        check(circuit.saved()==resumed.saved(),"capacitor snapshot changed continuation");
        // An independent capacitor/load island, with zero source current.
        auto discharge = state;
        discharge["branches"][0]["closed"] = false;
        discharge["branches"].push_back({{"id","load"},{"component","load"},{"kind","resistor"},
            {"a","bus"},{"b","n"},{"thermal","case"},{"resistance_ohm",10.0}});
        discharge.erase("last");
        auto draining = Circuit::read(discharge,true);
        for (int k=0;k<static_cast<int>(std::round(1.0/dt));++k) {
            const auto step=draining.solve(dt,12,0,0,{});
            near(step.source_j,0,1e-12,"discharge borrowed battery energy");
            check(step.current_a[2]>0 && step.current_a[1]<0,"discharge current sign wrong");
            draining.commit(step,0);
        }
        const auto end=draining.saved();
        near(end["branches"][1]["capacitor_voltage_v"],voltage*std::exp(-1.0/1.01),.015,"RC discharge curve");
        std::cout << "RC dt=" << dt << " V=" << voltage << " error=" << error << " numerical_j=" << loss
                  << " residual_j=" << state["ledger"]["electrical_residual_j"] << '\n';
    }
    // Equal capacitors in series share voltage, in parallel add charge.
    for (const bool parallel : {false,true}) {
        auto d=declaration;
        d["nodes"].push_back("mid");
        auto second=d["branches"][1];second["id"]="second";second["component"]="second";
        if (!parallel) {d["branches"][1]["b"]="mid";second["a"]="mid";}
        d["branches"].push_back(second);
        auto c=Circuit::read(d);
        for (int k=0;k<4000;++k)c.commit(c.solve(.0025,12,1000,0,{}),0);
        const auto state=c.saved();
        near(state["branches"][1]["capacitor_voltage_v"],parallel?12:6, .09,"capacitor topology voltage");
        near(state["branches"][1]["charge_c"],state["branches"][2]["charge_c"],1e-9,"equal capacitor charge");
    }
    rejects([&]{auto d=declaration;d["branches"][1]["capacitance_f"]=0;Circuit::read(d);});
    rejects([&]{auto d=declaration;d["branches"][0]["capacitance_f"]=1;Circuit::read(d);});
    auto world=LiveWorld::open(room());
    auto live=declaration;
    live["source"]["store"]=world->energyStore("battery","post",8,8,12,0);
    world->circuit(live.dump());
    for(int k=0;k<240;++k)world->step(1.0/240);
    std::string why;
    auto restored=LiveWorld::open(room(),world->snapshot(why));
    check(restored->circuits()==world->circuits(),"world snapshot lost capacitor state");
    for(int k=0;k<240;++k){world->step(1.0/240);restored->step(1.0/240);}
    check(restored->circuits()==world->circuits(),"world capacitor continuation changed");
}
int main() {
    try {
        const auto start = std::chrono::steady_clock::now();
        capacitorTransients(); circuitsAndHeat(); switchingFailureAndValidation(); bulbEnergyAndSharedSupply(); liveLoopAndRestore(); stalledAndEmpty();
        sharedMotorsAndGeneration(); housingReactionAndConvergence(); hingeSwitchAndBodyHeat(); contactSwitch();
        std::cout << "circuits passed in " << std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() << " s\n";
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
