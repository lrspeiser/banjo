// Solar panels (docs/machine-world.md, "Solar panels"): the owner's answer,
// 2026-09-22, to how a machine's battery is charged. A room's sun, and a flat
// collector on a part, wired to a store: each kept step it puts into the store
// the sunlight on its face times its efficiency.
//
// 1. Square to the sun, a panel puts in irradiance x area x efficiency, to the
//    last joule; the rest of the sunlight is heat.
// 2. At an angle, the cosine of it; with the sun behind its face, nothing.
// 3. In shade, nothing -- and it says what shades it.
// 4. A full store takes no more: the rest is spilled, and the account still
//    closes.
// 5. A saved world keeps its sun, its panels and their accounts.

#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"

#include <cmath>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <string>
#include <utility>

using namespace banjo;
using namespace banjo::fastlattice;

namespace {

int failures = 0;
constexpr double kDt = 1.0 / 240.0;
constexpr double kPi = std::numbers::pi;

void require(bool ok, const std::string &why) {
    if (!ok) {
        std::cout << "[FAIL] " << why << std::endl;
        ++failures;
    }
}

bool near(double got, double want, double relative = 1e-9) {
    return std::abs(got - want) <= relative * std::max(1.0, std::abs(want));
}

SceneBody block(const std::string &name, Vec3 size, Vec3 centre) {
    SceneBody b;
    b.name = name;
    b.shape = BodyShape::Box;
    b.material = MaterialPreset::Concrete;
    b.dimensions_m = size;
    b.center_m = centre;
    b.anchored = true;
    return b;
}

// A flat floor with a concrete slab a metre square lying on it, its top face at
// y = 0.1: what the panel is on. `shade`, when given, is a second slab held up
// in the air over it.
TileImpactRequest slabRoom(bool shade = false) {
    TileImpactRequest request;
    request.cell_size_m = 0.05;
    request.backend = BackendKind::CpuParallel;
    request.bodies = {block("slab", {1.0, 0.1, 1.0}, {0.0, 0.05, 0.0})};
    if (shade) request.bodies.push_back(block("awning", {1.4, 0.1, 1.4}, {0.0, 2.05, 0.0}));
    return request;
}

void tick(LiveWorld &world) {
    world.step(kDt);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

struct Rig {
    std::unique_ptr<LiveWorld> world;
    unsigned store{}, panel{};
};
// A battery in the slab, empty, and a panel of 0.8 m2 lying on its top, facing
// up, turning a fifth of the sunlight on it into charge.
Rig rig(bool shade = false, double capacity_j = 1.0e6, double charge_j = 0.0) {
    Rig r;
    r.world = LiveWorld::open(slabRoom(shade));
    r.store = r.world->energyStore("battery", "slab", capacity_j, charge_j, 24.0, 0.0);
    r.panel = r.world->solarPanel("panel", "slab", r.store, {0.0, 0.1, 0.0}, {0.0, 1.0, 0.0}, 0.8, 0.2);
    if (r.store == 0 || r.panel == 0) throw std::runtime_error("the panel would not go on");
    return r;
}

LiveSolarPanel panelOf(const LiveWorld &world) { return world.solarPanels().front(); }
LiveEnergyStore storeOf(const LiveWorld &world) { return world.energyStores().front(); }

void squareToTheSunItPutsInWhatTheSunGives() {
    Rig r = rig();
    require(r.world->setSun(90.0, 0.0, 1000.0), "the sun would not go in the sky");
    for (int i = 0; i < 10 * 240; ++i) tick(*r.world);
    const LiveSolarPanel panel = panelOf(*r.world);
    const LiveEnergyStore store = storeOf(*r.world);
    const double seconds = 10 * 240 * kDt;
    std::cout << "    overhead, 1000 W/m2 on 0.8 m2 at 20% for " << seconds << " s: " << panel.power_w << " W, "
              << store.charge_j << " J in the battery; " << panel.heat_j << " J of heat\n";
    require(near(panel.cos_incidence, 1.0) && !panel.shaded, "square to the sun, and in it");
    require(near(panel.sunlight_w, 800.0) && near(panel.power_w, 160.0), "800 W of sun on it, 160 W into the battery");
    require(near(store.charge_j, 160.0 * seconds, 1e-9), "the battery holds what it put in: " +
                                                            std::to_string(store.charge_j));
    require(near(store.taken_j, store.charge_j) && store.given_j == 0.0, "all of it taken in, none given");
    require(near(panel.sunlight_j, panel.collected_j + panel.spilled_j + panel.heat_j), "the account closes");
    require(near(panel.heat_j, 640.0 * seconds, 1e-9), "and the rest is heat");
}

void atAnAngleTheCosineOfItAndFromBehindNothing() {
    Rig r = rig();
    require(r.world->setSun(60.0, 30.0, 1000.0), "the sun would not go in the sky");
    for (int i = 0; i < 240; ++i) tick(*r.world);
    LiveSolarPanel panel = panelOf(*r.world);
    const double cos30 = std::cos(30.0 * kPi / 180.0);
    std::cout << "    the sun 60 degrees up: cos " << panel.cos_incidence << ", " << panel.power_w << " W\n";
    require(near(panel.cos_incidence, cos30, 1e-9), "the cosine of the angle from its face to the sun");
    require(near(panel.power_w, 160.0 * cos30, 1e-9), "and that share of the power");
    // A panel on the slab's side, facing away from a low sun.
    const unsigned away = r.world->solarPanel("back", "slab", r.store, {0.0, 0.05, -0.5}, {0.0, 0.0, -1.0}, 0.1, 0.2);
    require(r.world->setSun(10.0, 0.0, 1000.0), "a low sun");
    for (int i = 0; i < 24; ++i) tick(*r.world);
    for (const LiveSolarPanel &p : r.world->solarPanels())
        if (p.id == away) panel = p;
    require(panel.cos_incidence == 0.0 && panel.power_w == 0.0, "with the sun behind its face, it makes nothing");
    require(!r.world->setSun(-5.0, 0.0, 1000.0) && !r.world->setSun(45.0, 0.0, 5000.0), "no sun below the horizon, "
                                                                                          "none past 1400 W/m2");
}

void inShadeNothingAndItSaysWhat() {
    Rig r = rig(true);
    require(r.world->setSun(90.0, 0.0, 1000.0), "the sun would not go in the sky");
    for (int i = 0; i < 240; ++i) tick(*r.world);
    const LiveSolarPanel panel = panelOf(*r.world);
    std::cout << "    under the awning: shaded by \"" << panel.shaded_by << "\", " << panel.power_w << " W\n";
    require(panel.shaded && panel.shaded_by == "awning", "the awning shades it: " + panel.shaded_by);
    require(panel.power_w == 0.0 && storeOf(*r.world).charge_j == 0.0, "and it makes nothing");
    // The sun low, from the side, under the awning's edge: in the sun again.
    require(r.world->setSun(12.0, 90.0, 1000.0), "a low sun");
    for (int i = 0; i < 24; ++i) tick(*r.world);
    require(!panelOf(*r.world).shaded && panelOf(*r.world).power_w > 0.0, "from under the awning's edge, it is lit");
}

void aFullStoreTakesNoMore() {
    Rig r = rig(false, 100.0, 90.0);
    require(r.world->setSun(90.0, 0.0, 1000.0), "the sun would not go in the sky");
    for (int i = 0; i < 240; ++i) tick(*r.world);
    const LiveSolarPanel panel = panelOf(*r.world);
    const LiveEnergyStore store = storeOf(*r.world);
    std::cout << "    a 100 J battery at 90 J: now " << store.charge_j << " J; " << panel.spilled_j
              << " J spilled\n";
    require(near(store.charge_j, 100.0, 1e-12) && near(store.taken_j, 10.0), "it filled, and took only the 10 J it had room for");
    require(near(panel.spilled_j, 160.0 - 10.0, 1e-9) && panel.power_w == 0.0, "the rest spilled; full, it takes nothing");
    require(near(panel.sunlight_j, panel.collected_j + panel.spilled_j + panel.heat_j), "and the account closes");
}

void aSavedWorldKeepsItsSunAndPanels() {
    Rig r = rig(true);
    require(r.world->setSun(35.0, 120.0, 900.0), "the sun would not go in the sky");
    for (int i = 0; i < 480; ++i) tick(*r.world);
    std::string why;
    const std::string saved = r.world->snapshot(why);
    require(!saved.empty(), "the world would not save: " + why);
    if (saved.empty()) return;
    const auto again = LiveWorld::open(slabRoom(true), saved);
    require(again->restored().tier == "whole", "the world did not come back whole: " + again->restored().why);
    const LiveSun sun = again->sun();
    require(sun.declared && sun.elevation_deg == 35.0 && sun.azimuth_deg == 120.0 && sun.irradiance_w_m2 == 900.0,
            "its sun came back where it was");
    const LiveSolarPanel was = panelOf(*r.world), is = panelOf(*again);
    require(is.name == was.name && is.store == was.store && is.area_m2 == was.area_m2 &&
                length(is.at_local_m - was.at_local_m) < 1e-12 && is.collected_j == was.collected_j &&
                is.sunlight_j == was.sunlight_j && is.heat_j == was.heat_j,
            "its panel came back with its account");
    require(storeOf(*again).taken_j == storeOf(*r.world).taken_j, "and its battery with what it had taken in");
    for (int i = 0; i < 240; ++i) {
        tick(*r.world);
        tick(*again);
    }
    require(near(panelOf(*again).collected_j, panelOf(*r.world).collected_j, 1e-12),
            "opened again, it goes on as it would have");
}

} // namespace

int main() {
    const std::pair<const char *, void (*)()> tests[] = {
        {"square to the sun, it puts in what the sun gives", squareToTheSunItPutsInWhatTheSunGives},
        {"at an angle the cosine of it, and from behind nothing", atAnAngleTheCosineOfItAndFromBehindNothing},
        {"in shade nothing, and it says what shades it", inShadeNothingAndItSaysWhat},
        {"a full store takes no more", aFullStoreTakesNoMore},
        {"a saved world keeps its sun and panels", aSavedWorldKeepsItsSunAndPanels},
    };
    for (const auto &[name, test] : tests) {
        const int before = failures;
        try {
            test();
        } catch (const std::exception &error) {
            std::cout << "[FAIL] " << name << ": " << error.what() << std::endl;
            ++failures;
        }
        if (failures == before) std::cout << "[PASS] " << name << std::endl;
    }
    std::cout << (failures == 0 ? "all passed" : std::to_string(failures) + " failed") << std::endl;
    return failures == 0 ? 0 : 1;
}
