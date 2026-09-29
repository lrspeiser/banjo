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
//
// And the other end of the wire (docs/machine-world.md, "Light underground"),
// the owner's answer, 2026-09-28, to how a mine is lit: electric light, on
// cables running up to the solar farm, rather than torches.
//
// 6. A lamp draws its watts and gives its lumens, and the store pays.
// 7. A cable's resistance is real, and in series with the lamps on it: a long
//    thin run keeps some of the voltage, so its lamps are dim even off a full
//    battery, and a short fat one hardly any.
// 8. A flat store puts the lights out; the sun charging it lights them again.
// 9. Lamps on one run share it: a second lamp dims the first.
// 10. A saved world keeps its cables and its lamps.

#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"

#include <cmath>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <memory>
#include <string>
#include <utility>
#include <vector>

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

// ---- light underground -----------------------------------------------------

// A 20 W lamp at 120 lm/W, fed from the slab's battery along a run of cable of
// `length_m` and `area_mm2` (copper). One lamp unless `lamps` says more.
struct Lit {
    std::unique_ptr<LiveWorld> world;
    unsigned store{}, cable{};
    std::vector<unsigned> lamps;
};
Lit lit(double length_m, double area_mm2, double charge_j = 1.0e6, int lamps = 1, double watts = 20.0) {
    Lit l;
    l.world = LiveWorld::open(slabRoom());
    l.store = l.world->energyStore("battery", "slab", 1.0e6, charge_j, 24.0, 0.0);
    if (l.store == 0) throw std::runtime_error("the battery would not go in");
    if (length_m > 0.0) {
        // A straight run, off along +x from the slab: its length is what decides
        // its resistance, and where it goes does not matter to this.
        l.cable = l.world->cable("feeder", l.store, {{0.0, 0.2, 0.0}, {length_m, 0.2, 0.0}}, area_mm2, 1.68e-8);
        if (l.cable == 0) throw std::runtime_error("the cable would not run");
    }
    for (int i = 0; i < lamps; ++i) {
        const unsigned id = l.world->lamp("lamp " + std::to_string(i + 1), "", l.cable, l.store,
                                          {1.0 + 0.5 * i, 1.8, 0.0}, watts, 120.0);
        if (id == 0) throw std::runtime_error("the lamp would not go up");
        if (!l.world->switchLamp(id, true)) throw std::runtime_error("the lamp would not switch on");
        l.lamps.push_back(id);
    }
    return l;
}
LiveLamp lampNamed(const LiveWorld &world, unsigned id) {
    for (const LiveLamp &lamp : world.lamps())
        if (lamp.id == id) return lamp;
    throw std::runtime_error("no such lamp");
}
LiveCable cableOf(const LiveWorld &world) { return world.cables().front(); }

void aLampDrawsItsWattsAndGivesItsLumens() {
    // Wired straight to the store: no cable, so nothing lost on the way.
    Lit l = lit(0.0, 0.0);
    const double seconds = 240 * kDt;
    const LiveEnergyStore was = storeOf(*l.world);
    for (int i = 0; i < 240; ++i) tick(*l.world);
    const LiveLamp lamp = lampNamed(*l.world, l.lamps.front());
    const LiveEnergyStore store = storeOf(*l.world);
    std::cout << "    20 W straight off the battery for " << seconds << " s: " << lamp.drawn_w << " W, "
              << lamp.lumens << " lm, " << was.charge_j - store.charge_j << " J out of the battery\n";
    require(lamp.lit && lamp.why.empty(), "it is lit, with nothing to explain: " + lamp.why);
    require(near(lamp.drawn_w, 20.0) && near(lamp.lumens, 2400.0), "its watts and its lumens");
    require(near(was.charge_j - store.charge_j, 20.0 * seconds, 1e-9), "and the battery paid for every joule");
    require(near(store.given_j, 20.0 * seconds, 1e-9), "which is what the store says it gave");
    require(near(lamp.drawn_j, 20.0 * seconds, 1e-9), "and what the lamp says it took");
    // Switched off it draws nothing, and says why it is dark.
    require(l.world->switchLamp(l.lamps.front(), false), "it would not switch off");
    for (int i = 0; i < 24; ++i) tick(*l.world);
    const LiveLamp off = lampNamed(*l.world, l.lamps.front());
    require(!off.lit && off.drawn_w == 0.0 && off.why == "switched off", "off, and it says so: " + off.why);
    require(near(storeOf(*l.world).charge_j, store.charge_j, 1e-12), "and the battery is not paying for it");
}

// A lamp rated `watts` at `volts` on a run of `ohm`, worked out with nothing but
// Ohm's law: the lamp's own resistance, the current through the pair of them in
// series, and what each of them then takes.
struct Series { double amps{}, at_lamps_w{}, in_run_w{}; };
Series series(double watts, double volts, double ohm) {
    Series out;
    const double load = volts * volts / watts;
    out.amps = volts / (load + ohm);
    out.at_lamps_w = out.amps * out.amps * load;
    out.in_run_w = out.amps * out.amps * ohm;
    return out;
}

void aLongThinRunLosesMoreOfIt() {
    // 60 m of 1.5 mm2 copper, out and back: 2 x 1.68e-8 x 60 / 1.5e-6 = 1.344 ohm.
    Lit thin = lit(60.0, 1.5);
    for (int i = 0; i < 240; ++i) tick(*thin.world);
    const LiveCable run = cableOf(*thin.world);
    const LiveLamp lamp = lampNamed(*thin.world, thin.lamps.front());
    const double ohm = 2.0 * 1.68e-8 * 60.0 / 1.5e-6;
    const Series want = series(20.0, 24.0, ohm);
    std::cout << "    60 m of 1.5 mm2 to one 20 W lamp: " << run.resistance_ohm << " ohm, " << run.current_a
              << " A, " << run.volts_lost << " V lost on the way, " << run.loss_w << " W in the cable, the lamp at "
              << lamp.drawn_w << " W of the 20 it asked for\n";
    require(near(run.resistance_ohm, ohm, 1e-9), "resistivity times twice the run, over the conductor");
    require(near(run.length_m, 60.0, 1e-9), "and the run is as long as it was laid");
    // The run is in series with the lamp, so even off a full battery the lamp
    // does not get its 20 W: the cable keeps some of the voltage.
    require(near(run.current_a, want.amps, 1e-9), "the current is the voltage over both resistances");
    require(near(lamp.drawn_w, want.at_lamps_w, 1e-9), "and the lamp gets I squared times its own resistance");
    require(near(run.loss_w, want.in_run_w, 1e-9), "the run keeps I squared R");
    require(near(run.volts_lost, want.amps * ohm, 1e-9), "and that much of the voltage never arrives");
    require(lamp.drawn_w < 20.0 && lamp.why.find("dim") == 0, "it is dim, and says why: " + lamp.why);
    require(near(run.carried_w, lamp.drawn_w, 1e-12), "what the run carried is what the lamp took");
    // Four times the conductor: a quarter of the resistance, and the lamp gets
    // nearly all of what it asked for.
    Lit fat = lit(60.0, 6.0);
    for (int i = 0; i < 240; ++i) tick(*fat.world);
    const LiveCable fatter = cableOf(*fat.world);
    const LiveLamp brighter = lampNamed(*fat.world, fat.lamps.front());
    std::cout << "    the same run in 6 mm2: " << fatter.resistance_ohm << " ohm, " << fatter.loss_w
              << " W in the cable, the lamp at " << brighter.drawn_w << " W\n";
    require(near(fatter.resistance_ohm, ohm / 4.0, 1e-9), "four times the copper, a quarter of the resistance");
    require(near(brighter.drawn_w, series(20.0, 24.0, ohm / 4.0).at_lamps_w, 1e-9), "and Ohm's law again");
    require(brighter.drawn_w > lamp.drawn_w && fatter.loss_w < run.loss_w, "the fat run is better on both counts");
    // What the store gave is what the lamp took plus what the cable lost.
    const LiveEnergyStore store = storeOf(*thin.world);
    require(near(store.given_j, run.carried_j + run.lost_j, 1e-9),
            "the store gave the lamp's joules and the cable's together");
}

void aFlatStorePutsTheLightsOut() {
    // A lamp with almost nothing behind it: 2 J will not run 20 W for a second.
    Lit l = lit(0.0, 0.0, 2.0);
    for (int i = 0; i < 240; ++i) tick(*l.world);
    LiveLamp lamp = lampNamed(*l.world, l.lamps.front());
    LiveEnergyStore store = storeOf(*l.world);
    std::cout << "    2 J of battery and a 20 W lamp: out after " << store.given_j / 20.0 << " s, "
              << store.short_j << " J it could not give\n";
    require(!lamp.lit && lamp.why == "the store is flat", "the light went out, and it says why: " + lamp.why);
    require(near(store.charge_j, 0.0, 1e-12) && near(store.given_j, 2.0, 1e-9), "it gave all it had and no more");
    require(store.short_j > 0.0, "and it says what it could not give");
    // The sun on a panel charges it, and the same lamp lights again -- which is
    // the whole point of the wire going up to the farm.
    require(l.world->solarPanel("panel", "slab", l.store, {0.0, 0.1, 0.0}, {0.0, 1.0, 0.0}, 1.0, 0.2) != 0,
            "the panel would not go on");
    require(l.world->setSun(90.0, 0.0, 1000.0), "the sun would not go in the sky");
    for (int i = 0; i < 240; ++i) tick(*l.world);
    lamp = lampNamed(*l.world, l.lamps.front());
    store = storeOf(*l.world);
    std::cout << "    200 W of panel on it: the lamp is back at " << lamp.drawn_w << " W and the battery is "
              << "gaining " << store.taken_j - store.given_j << " J\n";
    require(lamp.lit && near(lamp.drawn_w, 20.0), "the panel lit it again");
    require(store.taken_j > store.given_j, "and the farm is making more than the light spends");
}

void lampsOnOneRunShareIt() {
    // Six 100 W lamps on 120 m of 1 mm2: 4.032 ohm in front of 0.96 ohm of lamps,
    // which is a run far too thin for the load and a heading barely lit.
    const double ohm = 2.0 * 1.68e-8 * 120.0 / 1.0e-6;
    Lit l = lit(120.0, 1.0, 1.0e6, 6, 100.0);
    for (int i = 0; i < 240; ++i) tick(*l.world);
    const LiveCable run = cableOf(*l.world);
    const LiveLamp one = lampNamed(*l.world, l.lamps.front());
    const Series six = series(600.0, 24.0, ohm);
    std::cout << "    six 100 W lamps on 120 m of 1 mm2 (" << run.resistance_ohm << " ohm, " << run.volts_lost
              << " V lost): each at " << one.drawn_w << " W, " << run.loss_w << " W in the run\n";
    require(one.lit && one.drawn_w < 100.0, "they are dim, not dark");
    require(one.why.find("dim") == 0, "and it says they are dim: " + one.why);
    for (const unsigned id : l.lamps)
        require(near(lampNamed(*l.world, id).drawn_w, one.drawn_w, 1e-9), "every lamp on the run dims the same");
    require(near(run.carried_w, six.at_lamps_w, 1e-9), "the six together take what Ohm's law gives them");
    require(near(one.drawn_w, six.at_lamps_w / 6.0, 1e-9), "and each takes a sixth of it");
    require(near(run.loss_w, six.in_run_w, 1e-9), "the run keeps the rest");
    require(near(run.current_a, six.amps, 1e-9), "at the current through the pair of them");
    // One lamp alone on the same run gets far more than one of six does: fewer
    // lamps, less current, and the run keeps less of the voltage.
    Lit alone = lit(120.0, 1.0, 1.0e6, 1, 100.0);
    for (int i = 0; i < 240; ++i) tick(*alone.world);
    const LiveLamp only = lampNamed(*alone.world, alone.lamps.front());
    std::cout << "    one of them alone on the same run: " << only.drawn_w << " W -- "
              << only.drawn_w / one.drawn_w << " times as much\n";
    require(near(only.drawn_w, series(100.0, 24.0, ohm).at_lamps_w, 1e-9), "Ohm's law for the one");
    require(only.drawn_w > one.drawn_w, "a lamp alone on a run is brighter than one of six");
}

void aSavedWorldKeepsItsCablesAndLamps() {
    Lit l = lit(60.0, 1.5);
    for (int i = 0; i < 240; ++i) tick(*l.world);
    const LiveCable was_run = cableOf(*l.world);
    const LiveLamp was_lamp = lampNamed(*l.world, l.lamps.front());
    std::string why;
    const std::string saved = l.world->snapshot(why);
    require(!saved.empty(), "the world would not save: " + why);
    if (saved.empty()) return;
    const auto again = LiveWorld::open(slabRoom(), saved);
    require(again->restored().tier == "whole", "the world did not come back whole: " + again->restored().why);
    require(again->cables().size() == 1 && again->lamps().size() == 1, "its cable and its lamp came back");
    const LiveCable run = again->cables().front();
    const LiveLamp lamp = again->lamps().front();
    require(near(run.resistance_ohm, was_run.resistance_ohm, 1e-12) && near(run.length_m, was_run.length_m, 1e-12),
            "the run is the same run");
    require(near(run.carried_j, was_run.carried_j, 1e-12) && near(run.lost_j, was_run.lost_j, 1e-12),
            "and its account came with it");
    require(lamp.on && near(lamp.watts, 20.0) && near(lamp.drawn_j, was_lamp.drawn_j, 1e-12),
            "the lamp is still on, and still says what it has drawn");
    for (int i = 0; i < 240; ++i) tick(*again);
    const LiveLamp now = again->lamps().front();
    std::cout << "    saved and opened again: the lamp is at " << now.drawn_w << " W on a "
              << run.resistance_ohm << " ohm run\n";
    require(now.lit && near(now.drawn_w, was_lamp.drawn_w, 1e-9), "and it lights the same on the next step");
}

int main() {
    const std::pair<const char *, void (*)()> tests[] = {
        {"square to the sun, it puts in what the sun gives", squareToTheSunItPutsInWhatTheSunGives},
        {"at an angle the cosine of it, and from behind nothing", atAnAngleTheCosineOfItAndFromBehindNothing},
        {"in shade nothing, and it says what shades it", inShadeNothingAndItSaysWhat},
        {"a full store takes no more", aFullStoreTakesNoMore},
        {"a saved world keeps its sun and panels", aSavedWorldKeepsItsSunAndPanels},
        {"a lamp draws its watts and gives its lumens", aLampDrawsItsWattsAndGivesItsLumens},
        {"a long thin run loses more of it", aLongThinRunLosesMoreOfIt},
        {"a flat store puts the lights out", aFlatStorePutsTheLightsOut},
        {"lamps on one run share it", lampsOnOneRunShareIt},
        {"a saved world keeps its cables and lamps", aSavedWorldKeepsItsCablesAndLamps},
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
