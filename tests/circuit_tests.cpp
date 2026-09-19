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
}
int main() {
    try {
        const auto start = std::chrono::steady_clock::now();
        circuitsAndHeat(); switchingFailureAndValidation(); liveLoopAndRestore(); stalledAndEmpty();
        sharedMotorsAndGeneration(); housingReactionAndConvergence();
        std::cout << "circuits passed in " << std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() << " s\n";
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
