// A day for the sun (docs/machine-world.md, "A day for the sun"): the owner's
// next step after solar panels, 2026-09-22. A room's sun can go round: it rises
// due east, stands highest due south at noon and sets due west, as at an
// equinox, once in a day as long as the room says, by the world's own clock.
// Low in the sky its beam comes through more air and is weaker; at night it
// shines on nothing.
//
// 1. It is due east at six, due south and as high as the room says at noon,
//    due west at six in the evening, and as far below the horizon at midnight
//    as it was above it at noon; the morning mirrors the afternoon.
// 2. Its beam overhead is what the room declared; lower down, the Meinel
//    air-mass model's share of it; below the horizon, none.
// 3. Its clock is the world's: the hour goes on with every kept step, and a day
//    later the sun is back where it was.
// 4. At night a panel makes nothing, and says why.
// 5. Over a whole day a panel collects the sunlight the model puts on it, to a
//    ten-thousandth of a fine sum of it.
// 6. A saved world keeps its day and the hour it had got to.
// 7. Numbers that are not a day's are refused, and change nothing; a sun told
//    to stand still has no day.

#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <numbers>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>

using namespace banjo;
using namespace banjo::fastlattice;

namespace {

int failures = 0;
constexpr double kDt = 1.0 / 240.0;
constexpr double kPi = std::numbers::pi;
constexpr double kDeg = kPi / 180.0;

void require(bool ok, const std::string &why) {
    if (!ok) {
        std::cout << "[FAIL] " << why << std::endl;
        ++failures;
    }
}

bool near(double got, double want, double tolerance = 1e-9) {
    return std::abs(got - want) <= tolerance * std::max(1.0, std::abs(want));
}

// A concrete slab a metre square on a flat floor, its top at y = 0.1, with an
// empty battery in it and a panel of 0.8 m2 lying on its top, facing up.
struct Rig {
    std::unique_ptr<LiveWorld> world;
    unsigned store{}, panel{};
};
TileImpactRequest slabRoom() {
    TileImpactRequest request;
    request.cell_size_m = 0.05;
    request.backend = BackendKind::CpuParallel;
    SceneBody slab;
    slab.name = "slab";
    slab.shape = BodyShape::Box;
    slab.material = MaterialPreset::Concrete;
    slab.dimensions_m = {1.0, 0.1, 1.0};
    slab.center_m = {0.0, 0.05, 0.0};
    slab.anchored = true;
    request.bodies = {slab};
    return request;
}
Rig rig() {
    Rig r;
    r.world = LiveWorld::open(slabRoom());
    r.store = r.world->energyStore("battery", "slab", 1.0e7, 0.0, 24.0, 0.0);
    r.panel = r.world->solarPanel("panel", "slab", r.store, {0.0, 0.1, 0.0}, {0.0, 1.0, 0.0}, 0.8, 0.2);
    if (r.store == 0 || r.panel == 0) throw std::runtime_error("the panel would not go on");
    return r;
}

void tick(LiveWorld &world) {
    world.step(kDt);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

// The Meinel model, written out again here from its paper form: the beam
// overhead times 0.7 to the power of (the air mass to the 0.678, less one), the
// air mass being 1 / sin(elevation), no more than 38.
double meinel(double zenith_w_m2, double elevation_deg) {
    const double up = std::sin(elevation_deg * kDeg);
    if (!(up > 0.0)) return 0.0;
    const double air = std::min(1.0 / up, 38.0);
    return zenith_w_m2 * std::pow(0.7, std::pow(air, 0.678) - 1.0);
}

// Where a sun with a day 60 degrees up at noon stands at `hour`.
LiveSun at(LiveWorld &world, double hour, double noon_deg = 60.0, double irradiance = 1000.0) {
    if (!world.setDay(240.0, noon_deg, hour, irradiance)) throw std::runtime_error("the day would not start");
    return world.sun();
}

void itRisesEastStandsSouthAndSetsWest() {
    Rig r = rig();
    const LiveSun six = at(*r.world, 6.0), noon = at(*r.world, 12.0), evening = at(*r.world, 18.0),
                  midnight = at(*r.world, 0.0);
    std::cout << "    at six: toward (" << six.toward.x << ", " << six.toward.y << ", " << six.toward.z
              << "), azimuth " << six.azimuth_deg << "; noon: " << noon.elevation_deg << " degrees up, azimuth "
              << noon.azimuth_deg << "; six in the evening: azimuth " << evening.azimuth_deg << "; midnight: "
              << midnight.elevation_deg << " degrees\n";
    require(length(six.toward - Vec3{1.0, 0.0, 0.0}) < 1e-12 && std::abs(six.elevation_deg) < 1e-9 &&
                near(six.azimuth_deg, 90.0),
            "at six it is on the horizon due east, +x");
    require(near(noon.elevation_deg, 60.0) && std::abs(noon.azimuth_deg) < 1e-9 &&
                length(noon.toward - Vec3{0.0, std::sin(60.0 * kDeg), std::cos(60.0 * kDeg)}) < 1e-12,
            "at noon it is due south, +z, as high as the room says");
    require(length(evening.toward - Vec3{-1.0, 0.0, 0.0}) < 1e-12 && near(evening.azimuth_deg, 270.0),
            "at six in the evening it is on the horizon due west");
    require(near(midnight.elevation_deg, -60.0) && midnight.irradiance_w_m2 == 0.0,
            "at midnight it is as far below the horizon as it was above it at noon, and shines on nothing");
    for (const double off : {0.5, 1.0, 2.5, 4.0, 5.5, 7.0, 9.0}) {
        const LiveSun am = at(*r.world, 12.0 - off), pm = at(*r.world, 12.0 + off);
        require(near(am.elevation_deg, pm.elevation_deg) && near(am.azimuth_deg + pm.azimuth_deg, 360.0) &&
                    std::abs(length(am.toward) - 1.0) < 1e-12,
                "the morning mirrors the afternoon, " + std::to_string(off) + " h from noon");
    }
    const LiveSun overhead = at(*r.world, 12.0, 90.0);
    require(length(overhead.toward - Vec3{0.0, 1.0, 0.0}) < 1e-12, "a sun 90 degrees up at noon is overhead");
}

void itsBeamThinsThroughTheAir() {
    Rig r = rig();
    require(at(*r.world, 12.0, 90.0, 1000.0).irradiance_w_m2 == 1000.0, "overhead, what the room declared");
    double before = 0.0;
    for (double hour = 6.25; hour <= 12.0; hour += 0.25) {
        const LiveSun sun = at(*r.world, hour);
        require(near(sun.irradiance_w_m2, meinel(1000.0, sun.elevation_deg), 1e-12),
                "the Meinel model's beam at " + std::to_string(sun.elevation_deg) + " degrees");
        require(sun.irradiance_w_m2 > before, "and stronger as it climbs");
        before = sun.irradiance_w_m2;
    }
    const LiveSun low = at(*r.world, 6.25), noon = at(*r.world, 12.0);
    std::cout << "    " << low.elevation_deg << " degrees up: " << low.irradiance_w_m2 << " W/m2; at noon, "
              << noon.elevation_deg << " degrees: " << noon.irradiance_w_m2 << " W/m2\n";
    require(at(*r.world, 5.9).irradiance_w_m2 == 0.0 && at(*r.world, 18.1).irradiance_w_m2 == 0.0,
            "and below the horizon none");
}

void itsClockIsTheWorlds() {
    Rig r = rig();
    require(r.world->setDay(240.0, 60.0, 11.0, 1000.0), "the day would not start");
    for (int i = 0; i < 10 * 240; ++i) tick(*r.world);   // 10 s: an hour of a 240 s day
    const LiveSun noon = r.world->sun();
    std::cout << "    ten seconds after eleven, a 240 s day: " << noon.hour << " o'clock, " << noon.elevation_deg
              << " degrees up\n";
    require(near(noon.hour, 12.0, 1e-9) && near(noon.elevation_deg, 60.0, 1e-6), "an hour on, it is noon");
    for (int i = 0; i < 240 * 240; ++i) tick(*r.world);   // a whole day
    const LiveSun again = r.world->sun();
    require(near(again.hour, 12.0, 1e-9) && length(again.toward - noon.toward) < 1e-9,
            "a day later it is back where it was");
    // Begun later in a world's life, the day starts at the hour it is told.
    require(r.world->setDay(240.0, 60.0, 7.5, 1000.0) && near(r.world->sun().hour, 7.5, 1e-12),
            "a day begun late starts at its hour");
}

void atNightAPanelMakesNothing() {
    Rig r = rig();
    require(r.world->setDay(240.0, 60.0, 17.0, 1000.0), "the day would not start");
    double at_sunset = -1.0, most_at_night = 0.0;
    int night_steps = 0;
    for (int i = 0; i < 20 * 240; ++i) {   // five to seven in the evening
        tick(*r.world);
        const LiveSun sun = r.world->sun();
        const LiveSolarPanel panel = r.world->solarPanels().front();
        if (sun.elevation_deg < 0.0) {
            if (at_sunset < 0.0) at_sunset = panel.collected_j;
            ++night_steps;
            most_at_night = std::max(most_at_night, panel.sunlight_w + panel.power_w + panel.cos_incidence);
        }
    }
    const LiveSolarPanel panel = r.world->solarPanels().front();
    std::cout << "    " << at_sunset << " J by sunset, " << panel.collected_j << " J at " << r.world->sun().hour
              << " o'clock, after " << night_steps << " steps of night\n";
    require(night_steps > 8 * 240 && at_sunset > 0.0, "the sun set, having shone");
    require(panel.collected_j == at_sunset && most_at_night == 0.0,
            "after sunset the panel had no sun on it and made nothing");
    require(!panel.shaded && panel.shaded_by.empty(), "and nothing shades it: it is night");
}

void aDaysSunlightToATenThousandth() {
    Rig r = rig();
    require(r.world->setDay(240.0, 60.0, 0.0, 1000.0), "the day would not start");
    for (int i = 0; i < 240 * 240; ++i) tick(*r.world);
    const LiveSolarPanel panel = r.world->solarPanels().front();
    // The same day summed finely, from the model on paper: its beam on 0.8 m2
    // lying flat, at the cosine of its angle from overhead, a fifth of it
    // collected. The sun's height from its hour angle h at a latitude of 30
    // degrees (90 less its height at noon): sin(el) = cos(30) cos(h).
    constexpr int kFine = 2000000;
    double sum = 0.0;
    for (int i = 0; i < kFine; ++i) {
        const double hour = 24.0 * (i + 0.5) / kFine;
        const double up = std::cos(30.0 * kDeg) * std::cos((hour - 12.0) * 15.0 * kDeg);
        if (up > 0.0) sum += meinel(1000.0, std::asin(up) / kDeg) * up * 0.8 * 0.2 * (240.0 / kFine);
    }
    std::cout << "    a day of 240 s, 60 degrees up at noon: the panel collected " << panel.collected_j
              << " J; summed finely, " << sum << " J; the sunlight on it " << panel.sunlight_j << " J\n";
    require(near(panel.collected_j, sum, 1e-4), "it collected the day's sunlight to a ten-thousandth");
    require(near(panel.sunlight_j, panel.collected_j + panel.spilled_j + panel.heat_j, 1e-12), "and the account closes");
}

void aSavedWorldKeepsItsDayAndItsHour() {
    Rig r = rig();
    require(r.world->setDay(240.0, 55.0, 13.0, 900.0), "the day would not start");
    for (int i = 0; i < 480; ++i) tick(*r.world);
    std::string why;
    const std::string saved = r.world->snapshot(why);
    require(!saved.empty(), "the world would not save: " + why);
    if (saved.empty()) return;
    const auto again = LiveWorld::open(slabRoom(), saved);
    require(again->restored().tier == "whole", "the world did not come back whole: " + again->restored().why);
    const LiveSun was = r.world->sun(), is = again->sun();
    std::cout << "    saved at " << was.hour << " o'clock; opened again at " << is.hour << "\n";
    require(is.declared && is.day_s == 240.0 && is.noon_elevation_deg == 55.0 && is.zenith_irradiance_w_m2 == 900.0,
            "its day came back as it was");
    require(is.hour == was.hour && length(is.toward - was.toward) == 0.0 && is.irradiance_w_m2 == was.irradiance_w_m2,
            "and the hour it had got to, the sun where it was");
    for (int i = 0; i < 2400; ++i) {
        tick(*r.world);
        tick(*again);
    }
    require(again->sun().hour == r.world->sun().hour &&
                near(again->solarPanels().front().collected_j, r.world->solarPanels().front().collected_j, 1e-12),
            "opened again, its day goes on as it would have");
}

void aDayThatIsNotOneIsRefused() {
    Rig r = rig();
    require(r.world->setDay(240.0, 60.0, 9.0, 1000.0), "the day would not start");
    const LiveSun before = r.world->sun();
    const double nan = std::numeric_limits<double>::quiet_NaN();
    for (const auto &[day, noon, hour, irradiance] :
         {std::tuple{5.0, 60.0, 12.0, 1000.0}, std::tuple{240.0, 0.0, 12.0, 1000.0},
          std::tuple{240.0, 91.0, 12.0, 1000.0}, std::tuple{240.0, 60.0, 24.0, 1000.0},
          std::tuple{240.0, 60.0, -1.0, 1000.0}, std::tuple{240.0, 60.0, 12.0, 1500.0},
          std::tuple{nan, 60.0, 12.0, 1000.0}, std::tuple{240.0, 60.0, nan, 1000.0}})
        require(!r.world->setDay(day, noon, hour, irradiance), "a day that is not one was taken");
    const LiveSun after = r.world->sun();
    require(after.day_s == before.day_s && after.hour == before.hour && after.noon_elevation_deg == 60.0,
            "and refusing it changed nothing");
    // Told to stand still, it has no day, and stays where it is put.
    require(r.world->setSun(40.0, 180.0, 800.0), "the sun would not stand still");
    for (int i = 0; i < 1200; ++i) tick(*r.world);
    const LiveSun still = r.world->sun();
    require(still.day_s == 0.0 && still.elevation_deg == 40.0 && still.azimuth_deg == 180.0 &&
                still.irradiance_w_m2 == 800.0,
            "a sun told to stand still stays where it is put");
}

} // namespace

int main() {
    const std::pair<const char *, void (*)()> tests[] = {
        {"it rises east, stands south and sets west", itRisesEastStandsSouthAndSetsWest},
        {"its beam thins through the air", itsBeamThinsThroughTheAir},
        {"its clock is the world's", itsClockIsTheWorlds},
        {"at night a panel makes nothing", atNightAPanelMakesNothing},
        {"a day's sunlight to a ten-thousandth", aDaysSunlightToATenThousandth},
        {"a saved world keeps its day and its hour", aSavedWorldKeepsItsDayAndItsHour},
        {"a day that is not one is refused", aDayThatIsNotOneIsRefused},
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
