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

#include <nlohmann/json.hpp>

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

// Four 100 mm cubes on the floor, glass, oak, iron and ice, each under the
// same 2 kW for 20 s. Three warm and keep their size; the ice melts at its
// melting point, shrinks from every face by what melted, weighs what is left,
// and -- with no water in the room -- its meltwater runs off across the floor.
void iceOnTheFloorShrinksAndItsWaterRunsOff() {
    const std::vector<std::pair<std::string, double>> materials{
        {"glass", 2500.0}, {"oak", 700.0}, {"iron", 7870.0}, {"ice", 917.0}};
    std::string bodies;
    for (std::size_t k = 0; k < materials.size(); ++k) {
        if (k) bodies += ",";
        bodies += box(materials[k].first + " cube", materials[k].first, {0.1, 0.1, 0.1},
                      {1.0 * static_cast<double>(k), 0.05, 0.0}, false);
    }
    auto world = openScene(std::string(R"({"plasticity":true,"bodies":[)") + bodies + "]}", 0.02);
    require(world->thermo() != nullptr && world->thermo()->holds("ice cube"),
            "the ice is followed from the start, with nothing heating it");
    const Vec3 ice_was = poseOf(*world, "ice cube").dimensions_m;
    for (const auto &[material, density] : materials) world->heat(material + " cube", 2000.0, 20.0);
    stepFor(*world, 21.0);
    for (const auto &[material, density] : materials) {
        const thermo::BodyHeat b = heatOf(*world, material + " cube");
        const Vec3 now = poseOf(*world, material + " cube").dimensions_m;
        if (material == "ice") continue;
        require(!b.melting && b.melted_kg == 0.0, material + " does not melt");
        require(b.temperature_k > 300.0, material + " warmed instead: " + std::to_string(b.temperature_k));
        require(std::abs(now.x - 0.1) < 1e-9 && std::abs(now.y - 0.1) < 1e-9, material + " kept its size");
    }
    const thermo::BodyHeat ice = heatOf(*world, "ice cube");
    const Vec3 ice_now = poseOf(*world, "ice cube").dimensions_m;
    require(ice.melted_kg > 0.05, "the ice melted: " + std::to_string(ice.melted_kg) + " kg");
    require(ice.temperature_k <= 273.15 + 1e-6, "and stayed at its melting point");
    require(ice_now.x < ice_was.x - 0.002 && ice_now.y < ice_was.y - 0.002,
            "it shrank: " + std::to_string(1000.0 * ice_now.x) + " mm from 100");
    const double left = 917.0 * ice_was.x * ice_was.y * ice_was.z - ice.melted_kg;
    require(std::abs(ice.mass_kg - left) < 1e-6 * left, "it weighs what is left of it");
    require(std::abs(world->meltwaterRanOffKg() - ice.melted_kg) < 1e-6 * ice.melted_kg,
            "with no water in the room, every kilogram of meltwater ran off");
    require(world->meltwaterIntoWaterKg() == 0.0, "none went into water there is none of");
    const thermo::Ledger l = world->thermo()->ledger();
    require(std::abs(l.residualJ()) < 1e-9 * std::abs(l.storedJ()), "and the ledger closes");
    std::cout << "    2 kW for 20 s: the ice cube melted " << ice.melted_kg << " kg and is now "
              << 1000.0 * ice_now.x << " mm across; glass, oak and iron warmed and kept their size\n";
}

// A small cube of ice heated until it is gone leaves the world, and says it
// melted away -- not that it burned.
void iceThatMeltsAwayLeavesTheWorld() {
    auto world = openScene(std::string(R"({"plasticity":true,"bodies":[)") +
                               box("ice cube", "ice", {0.06, 0.06, 0.06}, {0, 0.03, 0}, false) + "]}",
                           0.02);
    const double had = 917.0 * 0.06 * 0.06 * 0.06;
    world->heat("ice cube", 10000.0, 30.0);
    stepFor(*world, 30.0);
    bool there = false;
    for (const LiveBodyPose &pose : world->poses()) there = there || pose.name == "ice cube";
    require(!there, "the ice cube is gone from the world");
    const std::vector<LiveBurnedAway> gone = world->burnedAway();
    require(gone.size() == 1 && gone.front().name == "ice cube" && gone.front().gone == "melted",
            "and it melted away");
    require(gone.front().why.find("melted") != std::string::npos, "in those words: " + gone.front().why);
    const double accounted = world->meltwaterRanOffKg() + gone.front().residue_kg;
    require(std::abs(accounted - had) < 1e-6 * had,
            "its meltwater and the last of it together are all the ice there was");
    std::cout << "    a 60 mm cube under 10 kW: gone at " << gone.front().time_s << " s, "
              << world->meltwaterRanOffKg() << " kg of meltwater run off and " << gone.front().residue_kg
              << " kg left with it\n";
}

// A world saved before ice could melt (heat model version 1, whose ice had a
// reference energy of 0) is opened now: its ice comes back at the temperature
// it was saved at, and the ledger's unaccounted energy is what it was.
void iceSavedBeforeMeltingComesBackAtItsTemperature() {
    const std::string scene = std::string(R"({"plasticity":true,"bodies":[)") +
                              box("ice cube", "ice", {0.1, 0.1, 0.1}, {0, 0.05, 0}, false,
                                  R"(,"temperature_k":258.15)") +
                              "]}";
    TileImpactRequest request;
    request.cell_size_m = 0.02;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(scene);
    readSceneSettings(scene, request);
    auto world = LiveWorld::open(request);
    stepFor(*world, 0.5);
    const thermo::BodyHeat was = heatOf(*world, "ice cube");
    require(was.temperature_k < 270.0 && !was.melting, "cold ice that has not started to melt");
    const double residual = world->thermo()->ledger().residualJ();
    std::string why;
    const std::string saved = world->snapshot(why);
    require(!saved.empty(), "the world saves: " + why);

    // The same world as version 1 wrote it: no model version, and its ice's
    // energy -- and the ledger's opening energy -- without the reference.
    nlohmann::json doc = nlohmann::json::parse(saved);
    require(doc["heat"]["model"]["version"] == "2", "a save says which model version wrote it");
    doc["heat"].erase("model");
    const thermo::Model model = thermo::demonstrationModel();
    const std::size_t ice = model.index("ice");
    const double u0 = model[ice].reference_energy_j_kg;
    double taken = 0.0;
    for (const thermo::Lump &lump : world->thermo()->state().lumps) {
        for (nlohmann::json &entry : doc["heat"]["lumps"]) {
            if (entry["body"] != lump.body) continue;
            const double surface = lump.surface.kg[ice] * u0, core = lump.core.kg[ice] * u0;
            entry["surface"]["internal_energy_j"] = entry["surface"]["internal_energy_j"].get<double>() - surface;
            entry["core"]["internal_energy_j"] = entry["core"]["internal_energy_j"].get<double>() - core;
            taken += surface + core;
        }
    }
    require(taken > 0.0, "the save held ice to bring across");
    nlohmann::json &ledger = doc["heat"]["network"]["ledger"];
    ledger["initial_j"] = ledger["initial_j"].get<double>() - taken;

    auto again = LiveWorld::open(request, doc.dump());
    require(again->restored().tier == "whole", "the version-1 world opens whole: " + again->restored().why);
    const thermo::BodyHeat now = heatOf(*again, "ice cube");
    require(std::abs(now.temperature_k - was.temperature_k) < 1e-9 &&
                std::abs(now.core_temperature_k - was.core_temperature_k) < 1e-9,
            "its ice is at the temperature it was saved at: " + std::to_string(now.temperature_k) + " K, was " +
                std::to_string(was.temperature_k));
    require(std::abs(again->thermo()->ledger().residualJ() - residual) < 1e-6,
            "and the ledger's unaccounted energy is what it was");
    std::cout << "    a version-1 save's ice came back at " << now.temperature_k << " K (saved at "
              << was.temperature_k << " K); without the migration it would read "
              << was.temperature_k - u0 / model[ice].cv_j_kg_k << " K\n";
}

} // namespace

int main(int argc, char **argv) {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"a heated gas lifts a load and cooling lets it down", aHeatedGasLiftsALoadAndCoolingLetsItDown},
        {"a refused step takes its chemistry back", aRefusedStepTakesItsChemistryBack},
        {"a burning plank that breaks shares out what it held", aBurningPlankThatBreaksSharesOutWhatItHeld},
        {"a burning log carried away takes its fire with it", aBurningLogCarriedAwayTakesItsFireWithIt},
        {"ice on the floor shrinks and its water runs off", iceOnTheFloorShrinksAndItsWaterRunsOff},
        {"ice that melts away leaves the world", iceThatMeltsAwayLeavesTheWorld},
        {"ice saved before melting comes back at its temperature", iceSavedBeforeMeltingComesBackAtItsTemperature},
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
