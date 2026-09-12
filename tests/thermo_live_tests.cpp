// The thermochemical network inside a live world: a heated gas lifting a load
// through a real rigid body on a real slide, a step that is taken back taking
// its chemistry back, a burning plank breaking and sharing out what it held,
// and a burning log carried away in the hand.
//
// tests/thermochemistry_tests.cpp is the network on its own; this is the
// network where the owner will see it.
#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "thermo/ThermoWorld.hpp"

#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
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

constexpr double kDt = 1.0 / 240.0;   // what the room steps at
constexpr double kGravity = 9.80665;

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

std::unique_ptr<LiveWorld> openScene(const std::string &scene, double cell_m) {
    TileImpactRequest request;
    request.cell_size_m = cell_m;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(scene);
    readSceneSettings(scene, request);
    return LiveWorld::open(request);
}

// Step for `seconds` of world time, answering every break by running it -- a
// stepper that never answers stops the clock at the first hard contact.
void stepFor(LiveWorld &world, double seconds) {
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    for (int done = 0; done < steps;) {
        world.step(kDt);
        if (world.steppedBack()) {
            for (const std::string &name : world.breakable()) (void)world.fracture(name);
            continue;
        }
        ++done;
    }
}

LiveBodyPose poseOf(const LiveWorld &world, const std::string &name) {
    for (const LiveBodyPose &pose : world.poses())
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

thermo::BodyHeat heatOf(const LiveWorld &world, const std::string &name) {
    for (const thermo::BodyHeat &b : world.thermo()->bodies())
        if (b.body == name) return b;
    throw std::runtime_error("no thermal state for " + name);
}

thermo::RegionState regionOf(const LiveWorld &world) {
    const auto regions = world.thermo()->regions();
    require(!regions.empty(), "the world has a gas region");
    return regions.front();
}

std::string box(const std::string &name, const std::string &material, Vec3 size, Vec3 at,
                bool anchored, const std::string &extra = "") {
    char text[512];
    std::snprintf(text, sizeof text,
                  R"({"name":"%s","shape":"box","material":"%s","dimensions_m":[%g,%g,%g],)"
                  R"("center_m":[%g,%g,%g],"anchored":%s%s})",
                  name.c_str(), material.c_str(), size.x, size.y, size.z, at.x, at.y, at.z,
                  anchored ? "true" : "false", extra.c_str());
    return text;
}

// A cylinder of anchored walls with a glass front, an iron piston on a slide
// with a 0.4 m column of argon under it, and an iron block resting on it.
std::string cylinder(double heater_w, double heater_s) {
    std::string bodies = box("cylinder base", "concrete", {0.48, 0.08, 0.48}, {0, 0.04, 0}, true) + "," +
                         box("cylinder wall left", "concrete", {0.08, 1.2, 0.48}, {-0.2, 0.68, 0}, true) + "," +
                         box("cylinder wall right", "concrete", {0.08, 1.2, 0.48}, {0.2, 0.68, 0}, true) + "," +
                         box("cylinder wall back", "concrete", {0.32, 1.2, 0.08}, {0, 0.68, -0.2}, true) + "," +
                         box("cylinder window", "glass", {0.32, 1.2, 0.08}, {0, 0.68, 0.2}, true) + "," +
                         box("piston", "iron", {0.24, 0.08, 0.24}, {0, 0.52, 0}, false) + "," +
                         box("load", "iron", {0.16, 0.16, 0.16}, {0, 0.64, 0}, false);
    char thermo[512];
    std::snprintf(thermo, sizeof thermo,
                  R"("thermo":{"gas_regions":[{"name":"cylinder gas","contents":{"argon":1},)"
                  R"("piston":"piston","height_m":0.4,"balance":true}],)"
                  R"("heaters":[{"target":"cylinder gas","power_w":%g,"seconds":%g}]})",
                  heater_w, heater_s);
    return std::string(R"({"plasticity":true,"bodies":[)") + bodies + "]," + thermo + "}";
}

double mechanical(const LiveWorld &world, const std::vector<std::string> &names) {
    // Kinetic plus gravitational, from the poses and the masses the network
    // and the solver agree on. Only translation: the slide forbids rotation of
    // the piston, and the block riding on it does not turn.
    double total = 0.0;
    for (const std::string &name : names) {
        const LiveBodyPose pose = poseOf(world, name);
        const double mass = name == "piston" ? 7870.0 * 0.24 * 0.08 * 0.24 : 7870.0 * 0.16 * 0.16 * 0.16;
        const double v2 = pose.velocity_m_s.x * pose.velocity_m_s.x +
                          pose.velocity_m_s.y * pose.velocity_m_s.y +
                          pose.velocity_m_s.z * pose.velocity_m_s.z;
        total += 0.5 * mass * v2 + mass * kGravity * pose.position_m.y;
    }
    return total;
}

// ---------------------------------------------------------------------------

// Milestone 3's acceptance, in a real world: heat the gas and the load goes up;
// let it cool and the load comes down and gives its work back to the gas. The
// work the gas paid is the work the mechanics received, and the mechanics'
// own energy change says so independently.
void aHeatedGasLiftsALoadAndCoolingLetsItDown() {
    auto world = openScene(cylinder(800.0, 30.0), 0.04);
    require(world->thermo() != nullptr, "the scene's gas was declared");
    require(world->slide("cylinder base", "piston", {0, 0.52, 0}, {0, 1, 0}, -0.2, 0.6, 0.0) > 0,
            "the piston runs on a slide");
    const double piston_y0 = poseOf(*world, "piston").position_m.y;
    const double load_y0 = poseOf(*world, "load").position_m.y;
    const double energy0 = mechanical(*world, {"piston", "load"});
    const auto started = std::chrono::steady_clock::now();
    stepFor(*world, 30.0);
    const thermo::RegionState hot = regionOf(*world);
    const double piston_lift = poseOf(*world, "piston").position_m.y - piston_y0;
    const double load_lift = poseOf(*world, "load").position_m.y - load_y0;
    const double gained = mechanical(*world, {"piston", "load"}) - energy0;
    const thermo::Ledger heated = world->thermo()->ledger();
    std::cout << "    after 30 s of 800 W: gas " << hot.temperature_k << " K, "
              << hot.pressure_pa / 1000.0 << " kPa; piston up " << piston_lift * 1000.0
              << " mm, load up " << load_lift * 1000.0 << " mm; gas paid "
              << heated.work_to_bodies_j << " J to the bodies, their energy rose " << gained << " J"
              << std::endl;
    require(piston_lift > 0.1, "heated, the gas lifted the piston by more than 100 mm");
    require(std::abs(load_lift - piston_lift) < 0.005, "and the block riding on it");
    require(std::abs(hot.stroke_m - piston_lift) < 0.002,
            "the gas's own stroke is the piston's real travel");
    require(std::abs(gained - heated.work_to_bodies_j) < 0.03 * heated.work_to_bodies_j,
            "the bodies gained what the gas paid them, within 3%");
    stepFor(*world, 90.0);
    const double wall_s =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    const thermo::Ledger cooled = world->thermo()->ledger();
    const double settle = poseOf(*world, "piston").position_m.y - piston_y0;
    std::cout << "    after cooling: piston " << settle * 1000.0 << " mm from where it began; "
              << "work to bodies " << cooled.work_to_bodies_j << " J; ledger residual "
              << cooled.residualJ() << " J; " << wall_s / 120.0 << "x realtime" << std::endl;
    require(cooled.work_to_bodies_j < 0.5 * heated.work_to_bodies_j,
            "coming down, the load returned its work to the gas");
    require(std::abs(settle) < 0.015, "and the piston is back within 15 mm of where it began");
    require(std::abs(cooled.residualJ()) < 1e-9 * std::abs(cooled.storedJ()), "the ledger closes");
    require(wall_s < 1.1 * 120.0, "and it ran inside the realtime rule");
}

// A step that would break something is taken back, and must take back its
// chemistry too: the network after a refused step is the network before it,
// exactly.
void aRefusedStepTakesItsChemistryBack() {
    const std::string scene =
        std::string(R"({"plasticity":true,"bodies":[)") +
        box("pier left", "iron", {0.04, 0.12, 0.16}, {-0.1, 0.06, 0}, true) + "," +
        box("pier right", "iron", {0.04, 0.12, 0.16}, {0.1, 0.06, 0}, true) + "," +
        box("pane", "glass", {0.24, 0.02, 0.16}, {0, 0.13, 0}, false) + "," +
        R"({"name":"ball","shape":"sphere","material":"iron","dimensions_m":[0.06,0.06,0.06],)"
        R"("center_m":[0,0.3,0],"velocity_m_s":[0,-8,0]},)" +
        box("log", "oak", {0.12, 0.12, 0.48}, {1.0, 0.06, 0}, false, R"(,"temperature_k":1000)") + "]}";
    auto world = openScene(scene, 0.02);
    require(world->thermo() != nullptr && world->thermo()->holds("log"), "the log is declared hot");
    int refused = 0;
    for (int i = 0; i < 480 && refused < 3; ++i) {
        const thermo::ThermoState before = world->thermo()->state();
        world->step(kDt);
        const thermo::ThermoState after = world->thermo()->state();
        if (world->steppedBack()) {
            ++refused;
            require(after.time_s == before.time_s, "a refused step does not move the network's clock");
            require(after.lumps.size() == before.lumps.size(), "nor change what it holds");
            for (std::size_t k = 0; k < after.lumps.size(); ++k) {
                require(after.lumps[k].surface.internal_energy_j == before.lumps[k].surface.internal_energy_j &&
                            after.lumps[k].surface.kg == before.lumps[k].surface.kg &&
                            after.lumps[k].core.kg == before.lumps[k].core.kg,
                        "a refused step burns nothing: fuel, gas and heat are exactly as before");
            }
            require(after.ledger.matter_out_j == before.ledger.matter_out_j &&
                        after.ledger.heat_to_surroundings_j == before.ledger.heat_to_surroundings_j,
                    "and moves nothing across the boundary");
            for (const std::string &name : world->breakable()) (void)world->fracture(name);
            const double t = world->thermo()->timeS();
            world->step(kDt);
            if (!world->steppedBack())
                require(std::abs(world->thermo()->timeS() - (t + kDt)) < 1e-12,
                        "the answered step then runs once");
        } else {
            require(std::abs(after.time_s - (before.time_s + kDt)) < 1e-12,
                    "an accepted step moves the network's clock by one step");
        }
    }
    require(refused > 0, "the ball struck the pane and a step was refused");
    require(heatOf(*world, "log").reacting, "and the log burned on regardless");
}

// A burning plank struck hard enough to break: every piece holds its share of
// what the plank held, at the plank's temperature, and nothing is made or lost.
void aBurningPlankThatBreaksSharesOutWhatItHeld() {
    const std::string scene =
        std::string(R"({"plasticity":true,"bodies":[)") +
        box("pier left", "iron", {0.04, 0.12, 0.12}, {-0.16, 0.06, 0}, true) + "," +
        box("pier right", "iron", {0.04, 0.12, 0.12}, {0.16, 0.06, 0}, true) + "," +
        box("plank", "oak", {0.36, 0.04, 0.12}, {0, 0.14, 0}, false, R"(,"temperature_k":900)") + "," +
        R"({"name":"ball","shape":"sphere","material":"iron","dimensions_m":[0.1,0.1,0.1],)"
        R"("center_m":[0,0.3,0],"velocity_m_s":[0,-25,0]}]})";
    auto world = openScene(scene, 0.02);
    bool broke = false;
    for (int i = 0; i < 480 && !broke; ++i) {
        world->step(kDt);
        if (!world->steppedBack()) continue;
        for (const std::string &name : world->breakable()) {
            const bool plank = name == "plank";
            const auto before = world->thermo()->bodies();
            const thermo::Ledger ledger_before = world->thermo()->ledger();
            double fuel = 0.0, mass = 0.0, temperature = 0.0;
            for (const thermo::BodyHeat &b : before)
                if (b.body == "plank") {
                    fuel = b.fuel_kg;
                    mass = b.mass_kg;
                    temperature = b.temperature_k;
                }
            const std::size_t pieces = world->fracture(name);
            if (!plank || pieces <= 1) continue;
            broke = true;
            double fuel_after = 0.0, mass_after = 0.0;
            int count = 0;
            for (const thermo::BodyHeat &b : world->thermo()->bodies()) {
                if (b.body.rfind("plank piece", 0) != 0) continue;
                ++count;
                fuel_after += b.fuel_kg;
                mass_after += b.mass_kg;
                require(std::abs(b.temperature_k - temperature) < 1e-6 * temperature,
                        "every piece is as hot as the plank was");
            }
            std::cout << "    the plank broke into " << pieces << " pieces; " << count
                      << " carry its matter: " << mass_after << " of " << mass << " kg, "
                      << fuel_after << " of " << fuel << " kg of fuel" << std::endl;
            require(!world->thermo()->holds("plank"), "the plank itself is gone");
            require(count == static_cast<int>(pieces), "every piece holds a share");
            require(std::abs(fuel_after - fuel) < 1e-12 * fuel, "no fuel is made or lost breaking it");
            require(std::abs(mass_after - mass) < 1e-12 * mass, "no matter is made or lost");
            const thermo::Ledger ledger_after = world->thermo()->ledger();
            require(std::abs(ledger_after.residualJ() - ledger_before.residualJ()) < 1e-6,
                    "breaking is not a crossing: the ledger is unchanged by it");
        }
    }
    require(broke, "the ball broke the plank (the premise of this test)");
    stepFor(*world, 1.0);
    const thermo::Ledger l = world->thermo()->ledger();
    require(std::abs(l.residualJ()) < 1e-9 * std::abs(l.storedJ()), "and the ledger still closes");
}

// A burning log carried away in the hand takes its fire with it; the log it
// was warming stops being warmed.
void aBurningLogCarriedAwayTakesItsFireWithIt() {
    const std::string scene =
        std::string(R"({"plasticity":true,"bodies":[)") +
        box("burning log", "oak", {0.12, 0.12, 0.48}, {0, 0.06, 0}, false, R"(,"temperature_k":1000)") + "," +
        box("cold log", "oak", {0.12, 0.12, 0.48}, {0.2, 0.06, 0}, false) + "]}";
    auto world = openScene(scene, 0.04);
    stepFor(*world, 5.0);
    const thermo::BodyHeat warmed = heatOf(*world, "cold log");
    const double fuel_before = heatOf(*world, "burning log").fuel_kg;
    require(warmed.gained_w > 50.0, "the cold log is being warmed by the fire beside it");
    require(world->grab("burning log"), "the burning log can be picked up");
    for (int i = 1; i <= 240; ++i) {
        world->moveHeld({3.0 * i / 240.0, 0.4, 0.0});
        world->step(kDt);
    }
    stepFor(*world, 2.0);
    const thermo::BodyHeat carried = heatOf(*world, "burning log");
    const thermo::BodyHeat left = heatOf(*world, "cold log");
    std::cout << "    carried 3 m: the burning log is at " << carried.temperature_k
              << " K, burning " << carried.heat_release_w / 1000.0 << " kW; the log it left gains "
              << left.gained_w << " W (was " << warmed.gained_w << " W)" << std::endl;
    require(carried.reacting, "the log carried away is still burning");
    require(carried.fuel_kg < fuel_before, "and still using its own fuel");
    require(left.gained_w < 0.1 * warmed.gained_w, "the log it left is no longer being warmed");
}

} // namespace

int main(int argc, char **argv) {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"a heated gas lifts a load and cooling lets it down", aHeatedGasLiftsALoadAndCoolingLetsItDown},
        {"a refused step takes its chemistry back", aRefusedStepTakesItsChemistryBack},
        {"a burning plank that breaks shares out what it held", aBurningPlankThatBreaksSharesOutWhatItHeld},
        {"a burning log carried away takes its fire with it", aBurningLogCarriedAwayTakesItsFireWithIt},
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
