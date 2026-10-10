// Lit spots (docs/light-spots.md): light concentrated on a small spot heats the
// matter there far faster than the body it is part of, and a beam strong enough
// takes that matter away -- oak chars through, ice melts -- at the rate the
// absorbed power over what taking it away costs, by the thermochemistry's own
// substances. Every test prints what it measures.
//
// 1. A 4.5 kW beam bounced off a polished aluminium mirror onto an oak cord
//    20 x 20 x 300 mm holding a 13.6 kg iron weight parts the cord in a few
//    seconds; the energy it took against the cells' energy per volume, worked
//    by hand from the model; light's ledger and the heat network's close; a
//    world saved half way through goes on exactly as the one that was not.
// 2. A weaker beam takes proportionally longer, and below the spot's threshold
//    it only warms the cord.
// 3. The mirror the beam bounced off is not cut: it reflects most of the beam,
//    and what it absorbs is conducted away.
// 4. Glass and ice: glass lets the beam through and absorbs a share of it along
//    its way, and nothing in the model takes glass away, so it is warmed and
//    never cut; ice absorbs a visible beam slowly and an infrared one quickly,
//    by depth, and melts where it does -- an ice cord parts under an infrared
//    beam, and melts slowly under a visible one.

#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "thermo/ThermoWorld.hpp"
#include "thermo/Thermochemistry.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

using namespace banjo;
using namespace banjo::fastlattice;

namespace {

int failures = 0;
constexpr double kDt = 1.0 / 240.0;

void require(bool ok, const std::string &why) {
    if (!ok) {
        std::cout << "[FAIL] " << why << std::endl;
        ++failures;
    }
}

SceneBody box(const std::string &name, MaterialPreset material, Vec3 size, Vec3 centre, bool anchored = true,
              Vec3 rotation_deg = {}) {
    SceneBody b;
    b.name = name;
    b.shape = BodyShape::Box;
    b.material = material;
    b.dimensions_m = size;
    b.center_m = centre;
    b.rotation_deg = rotation_deg;
    b.anchored = anchored;
    return b;
}

TileImpactRequest requestFor(std::vector<SceneBody> bodies) {
    TileImpactRequest request;
    request.cell_size_m = 0.02;
    request.backend = BackendKind::CpuParallel;
    request.bodies = std::move(bodies);
    return request;
}

void tick(LiveWorld &world) {
    world.step(kDt);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

// A lamp pinned in the world at `at`, on a full store, switched on, with its
// light declared down `axis`: `watts` drawn at `efficacy_lm_w`, its light
// `radiant_efficacy_lm_w` lumens a watt, `visible_share` of it visible.
void laser(LiveWorld &world, Vec3 at, Vec3 axis, double watts, double visible_share = 1.0, unsigned rays = 64,
           double half_angle_deg = 0.3) {
    const unsigned store = world.energyStore("laser battery", "", 1.0e9, 1.0e9, 230.0, 0.0);
    const unsigned lamp = world.lamp("laser", "", 0, store, at, watts, 270.0);
    if (store == 0 || lamp == 0 || !world.switchLamp(lamp, true)) throw std::runtime_error("the laser would not go up");
    if (world.lampLight("beam", lamp, axis, half_angle_deg, rays, 300.0, visible_share) == 0)
        throw std::runtime_error("the laser's light would not go on");
}

// The rig of the brief: a laser along +x at 0.575 m, a polished aluminium
// mirror turned 45 degrees about the vertical at x = 0.5 sending its beam along
// +z, and 1 m on, a cord hanging from a concrete arm with an iron weight on it.
std::vector<SceneBody> rig(MaterialPreset cord = MaterialPreset::Oak, double cord_m = 0.3, double weight_m = 0.12) {
    const double top = 0.575 + 0.5 * cord_m;
    // Its face is 10 mm in front of its middle: set back so the beam leaves it
    // along the cord's line.
    return {box("mirror", MaterialPreset::Aluminum, {0.02, 0.2, 0.2}, {0.5 + 0.01 * std::sqrt(2.0), 0.575, 0.0}, true,
                {0.0, 45.0, 0.0}),
            box("arm", MaterialPreset::Concrete, {0.2, 0.04, 0.06}, {0.5, top + 0.02, 1.0}),
            box("cord", cord, {0.02, cord_m, 0.02}, {0.5, 0.575, 1.0}, false),
            box("weight", MaterialPreset::Iron, {weight_m, weight_m, weight_m},
                {0.5, 0.575 - 0.5 * cord_m - 0.005 - 0.5 * weight_m, 1.0}, false)};
}

std::unique_ptr<LiveWorld> hang(std::vector<SceneBody> bodies, double cord_m = 0.3) {
    auto world = LiveWorld::open(requestFor(std::move(bodies)));
    const double top = 0.575 + 0.5 * cord_m, bottom = 0.575 - 0.5 * cord_m;
    const unsigned fixing = world->fix("arm", "cord", {0.5, top, 1.0}, {0.0, 1.0, 0.0}, 800.0, 800.0);
    const unsigned hook = world->fix("cord", "weight", {0.5, bottom, 1.0}, {0.0, 1.0, 0.0});
    if (fixing == 0 || hook == 0 || !world->setJointMember(fixing, "cord")) throw std::runtime_error("no cord");
    if (!world->polish("mirror", true).empty()) throw std::runtime_error("the mirror would not polish");
    return world;
}

double heightOf(const LiveWorld &world, const std::string &name) {
    for (const LiveBodyPose &b : world.poses())
        if (b.name == name) return b.position_m.y;
    return 0.0;
}

// Light on everything whose name starts with `stem` (a body and its pieces).
double litJ(const LiveOptics &o, const std::string &stem, double LiveOptics::Lit::*field) {
    double sum = 0.0;
    for (const LiveOptics::Lit &b : o.bodies)
        if (b.body.rfind(stem, 0) == 0) sum += b.*field;
    return sum;
}

const LiveOptics::Lit *litRow(const LiveOptics &o, const std::string &name) {
    for (const LiveOptics::Lit &b : o.bodies)
        if (b.body == name) return &b;
    return nullptr;
}

nlohmann::json heatLedger(const LiveWorld &world) {
    return nlohmann::json::parse(world.thermoReport(false)).at("ledger");
}

// What taking a kilogram of oak at `t0` to gone costs, worked by hand from the
// model's own numbers: dry wood and ash heated to oak's char line (EN 1995-1-2,
// 300 degC), its moisture driven off as water vapour where free water boils.
double oakJPerKg(double t0) {
    const thermo::Model model = thermo::demonstrationModel();
    const thermo::Substance &wood = model[model.index("dry wood")], &ash = model[model.index("ash")],
                            &moisture = model[model.index("moisture")], &vapour = model[model.index("water vapour")];
    const double char_k = 573.15, boil_k = 373.15;
    return 0.88 * wood.cv_j_kg_k * (char_k - t0) + 0.02 * ash.cv_j_kg_k * (char_k - t0) +
           0.10 * (thermo::specificEnthalpyJKg(vapour, boil_k) - thermo::specificEnergyJKg(moisture, t0));
}

struct Parting {
    double parted_s{-1.0};    // the weight is falling
    double first_cell_s{-1.0};
    double absorbed_j{};      // by the cord and its pieces, until it parted
};

// Run until the weight has dropped 5 cm, or `limit_s`.
Parting runUntilParted(LiveWorld &world, double limit_s, const std::string &weight = "weight") {
    Parting p;
    const double start = heightOf(world, weight);
    for (int i = 0; i < static_cast<int>(limit_s * 240.0); ++i) {
        tick(world);
        const LiveOptics o = world.optics();
        if (p.first_cell_s < 0.0 && !o.taken.empty()) p.first_cell_s = o.taken.front().t_s;
        if (start - heightOf(world, weight) > 0.05) {
            p.parted_s = (i + 1) * kDt;
            p.absorbed_j = litJ(o, "cord", &LiveOptics::Lit::absorbed_j);
            return p;
        }
    }
    p.absorbed_j = litJ(world.optics(), "cord", &LiveOptics::Lit::absorbed_j);
    return p;
}

// ---- 1. a laser parts an oak cord ---------------------------------------------

double fullBeamPartingS = 0.0;

void aLaserPartsAnOakCord() {
    auto world = hang(rig());
    laser(*world, {-1.0, 0.575, 0.0}, {1.0, 0.0, 0.0}, 5000.0);
    // Its first step lights it; the cord's spot after a few.
    for (int i = 0; i < 8; ++i) tick(*world);
    const LiveOptics early = world->optics();
    const LiveOptics::Lit *cord = litRow(early, "cord");
    require(cord != nullptr && cord->spot_w > 0.0, "the beam lands on the cord");
    if (cord == nullptr) return;
    std::cout << std::setprecision(6) << "    beam: " << early.watts.sent << " W of light; the cord absorbs "
              << cord->absorbed_w << " W, its brightest spot " << cord->spot_w << " W over "
              << cord->spot_area_m2 * 1e6 << " mm2 (" << cord->spot_w / cord->spot_area_m2 / 1e6
              << " MW/m2), at " << cord->spot_k << " K, " << cord->cut_w << " W of it taking oak away ("
              << cord->spot_how << ")\n";
    require(cord->spot_how == "chars" && std::abs(cord->spot_k - 573.15) < 1e-9,
            "oak's spot is held at its char line while it is taken away");

    const Parting p = runUntilParted(*world, 30.0);
    const LiveOptics o = world->optics();
    double taken_j = 0.0, taken_m3 = 0.0, taken_kg = 0.0;
    for (const LiveOptics::Taken &t : o.taken) {
        taken_j += t.energy_j;
        taken_m3 += t.volume_m3;
        taken_kg += t.kg;
    }
    const double density = o.taken.empty() ? 0.0 : taken_kg / taken_m3;
    const double by_hand = oakJPerKg(293.15) * density;   // J per m3, from the room's temperature
    std::cout << "    the cord: first cell taken at " << p.first_cell_s << " s; the weight falls at " << p.parted_s
              << " s; " << o.taken.size() << " cell(s) taken, " << taken_m3 * 1e6 << " cm3, " << taken_kg * 1e3
              << " g, for " << taken_j << " J = " << taken_j / taken_m3 / 1e6 << " MJ/m3 (by hand from the model, "
              << "oak at 293.15 K of " << density << " kg/m3: " << by_hand / 1e6 << " MJ/m3; volume x that = "
              << by_hand * taken_m3 << " J); the cord absorbed " << p.absorbed_j << " J by then\n";
    for (const LiveOptics::Taken &t : o.taken)
        std::cout << "      " << t.body << " at " << t.t_s << " s, y = " << t.at_m.y << " m: " << t.energy_j
                  << " J for " << t.volume_m3 * 1e6 << " cm3 (" << t.how << " at " << t.gone_k << " K)\n";
    if (std::getenv("SPOT_DEBUG")) {
        for (const LiveBodyPose &b : world->poses())
            std::cout << "      body " << b.name << " y " << b.position_m.y << " shape " << b.shape << " mass "
                      << b.mass_kg << "\n";
        for (const LiveJoint &j : world->joints())
            std::cout << "      joint " << j.id << " " << j.a << " - " << j.b << (j.attached ? " attached" : " off")
                      << "\n";
    }
    require(p.parted_s > 0.0 && p.parted_s < 5.0, "a 4.5 kW beam parts a 20 mm oak cord in a few seconds");
    require(!o.taken.empty(), "and it does so by taking the lit oak away");
    // Warmer than the room by what was conducted into it, a cell costs a
    // little less than one at the room's temperature, never more.
    require(taken_j <= by_hand * taken_m3 * (1.0 + 1e-9) && taken_j >= 0.97 * by_hand * taken_m3,
            "what it took is the energy per volume of oak, by the model, times the volume");
    fullBeamPartingS = p.parted_s;

    // The ledgers, light's and the heat network's.
    const nlohmann::json heat = heatLedger(*world);
    const double spot_in = heat.at("spot_in_j"), taken = heat.at("taken_by_light_j"),
                 returned = heat.at("spot_returned_j");
    double held = 0.0;
    for (const auto &b : nlohmann::json::parse(world->thermoReport(false)).at("bodies"))
        held += b.value("spot_j", 0.0);
    std::cout << "    light: sent " << o.joules.sent << " J, heated " << o.joules.heated << " J, of which into spots "
              << o.joules.spots << " J; residual " << o.joules.residual() << " J\n"
              << "    heat network: spots took in " << spot_in << " J = taken away " << taken << " J + given back "
              << "as heat " << returned << " J + held " << held << " J (" << spot_in - taken - returned - held
              << "); its residual " << heat.at("residual_j").get<double>() << " J, mass residual "
              << heat.at("mass_residual_kg").get<double>() << " kg\n";
    const double absorbed = litJ(o, "cord", &LiveOptics::Lit::absorbed_j);
    std::cout << "    the cord and its pieces absorbed " << absorbed << " J = heat into them "
              << absorbed - taken - held << " J + spent taking oak away " << taken << " J + held in spots " << held
              << " J\n";
    require(std::abs(o.joules.residual()) <= 1e-9 * o.joules.sent, "light's ledger closes");
    require(std::abs(o.joules.spots - spot_in) <= 1e-9 * spot_in, "light's spots and the network's agree");
    require(std::abs(spot_in - taken - returned - held) <= 1e-9 * spot_in, "what spots took in is accounted for");
    require(std::abs(taken - taken_j) <= 1e-9 * taken_j, "what was taken is what the cells cost");
    require(std::abs(heat.at("residual_j").get<double>()) <= 1e-6 * spot_in, "the heat network's ledger closes");
    require(std::abs(heat.at("mass_residual_kg").get<double>()) <= 1e-12, "and its mass");
}

// ---- 1b. saved half way, it goes on as it would have ------------------------------

void aSavedWorldKeepsItsSpots() {
    auto world = hang(rig());
    laser(*world, {-1.0, 0.575, 0.0}, {1.0, 0.0, 0.0}, 5000.0);
    for (int i = 0; i < 240; ++i) tick(*world);   // 1 s: part way through its first cell
    double held = 0.0;
    for (const auto &b : nlohmann::json::parse(world->thermoReport(false)).at("bodies")) held += b.value("spot_j", 0.0);
    std::string why;
    const std::string saved = world->snapshot(why);
    require(!saved.empty(), "the world would not save: " + why);
    if (saved.empty()) return;
    auto again = LiveWorld::open(requestFor(rig()), saved);
    require(again->restored().tier == "whole", "the world did not come back whole: " + again->restored().why);
    double held_again = 0.0;
    for (const auto &b : nlohmann::json::parse(again->thermoReport(false)).at("bodies"))
        held_again += b.value("spot_j", 0.0);
    const Parting a = runUntilParted(*world, 10.0), b = runUntilParted(*again, 10.0);
    std::cout << "    saved at 1 s with " << held << " J held in the cord's spots, opened with " << held_again
              << " J; the weight fell " << a.parted_s << " s and " << b.parted_s << " s later; "
              << world->optics().taken.size() << " and " << again->optics().taken.size() << " cells taken\n";
    require(held > 0.0 && held == held_again, "a saved world keeps the heat in its spots");
    require(a.parted_s > 0.0 && a.parted_s == b.parted_s &&
                world->optics().taken.size() == again->optics().taken.size(),
            "and goes on as it would have");
}

// ---- 2. weaker beams --------------------------------------------------------------

void aWeakerBeamTakesLonger() {
    struct Run {
        double watts, parted_s, absorbed_w, cut_w, loss_w;
    };
    std::vector<Run> runs;
    for (const double watts : {5000.0, 2500.0, 1250.0}) {
        auto world = hang(rig());
        laser(*world, {-1.0, 0.575, 0.0}, {1.0, 0.0, 0.0}, watts);
        for (int i = 0; i < 8; ++i) tick(*world);
        const LiveOptics::Lit *cord = litRow(world->optics(), "cord");
        const double absorbed = cord ? cord->absorbed_w : 0.0, cut = cord ? cord->cut_w : 0.0;
        const Parting p = runUntilParted(*world, 40.0);
        runs.push_back({watts, p.parted_s + 8 * kDt, absorbed, cut, absorbed - cut});
        std::cout << "    " << watts << " W laser: the cord absorbs " << absorbed << " W, " << cut
                  << " W taking oak away; the weight falls at " << p.parted_s + 8 * kDt << " s\n";
    }
    for (std::size_t k = 1; k < runs.size(); ++k) {
        const double ratio = runs[k].parted_s / runs[0].parted_s;
        const double expected = runs[0].cut_w / runs[k].cut_w;
        std::cout << "    " << runs[k].watts << " W against 5000 W: " << ratio << " times as long (the power "
                  << "taking oak away is " << expected << " times less)\n";
        // Within a trace stride and the few kelvin the body warms meanwhile.
        require(runs[k].parted_s > 0.0 && std::abs(ratio / expected - 1.0) < 0.08,
                "a weaker beam takes proportionally longer");
    }

    // Below the spot's threshold it only warms. The threshold is what the spot
    // loses held at the char line, about 7 W for the cord under a beam this
    // wide; a 10 W laser puts about 3.6 W on it.
    auto world = hang(rig());
    laser(*world, {-1.0, 0.575, 0.0}, {1.0, 0.0, 0.0}, 10.0);
    for (int i = 0; i < 20 * 240; ++i) tick(*world);
    const LiveOptics o = world->optics();
    const LiveOptics::Lit *cord = litRow(o, "cord");
    double loss = 0.0;
    if (world->thermo() != nullptr)
        for (const thermo::SpotState &s : world->thermo()->spotStates())
            if (s.body == "cord") loss = std::max(loss, s.loss_w);
    std::cout << "    10 W laser: the cord absorbs " << (cord ? cord->absorbed_w : 0.0) << " W; its spot would lose "
              << loss << " W held at the char line, so it settles at " << (cord ? cord->spot_k : 0.0)
              << " K and takes nothing away (" << o.taken.size() << " cells in 20 s)\n";
    require(cord != nullptr && cord->absorbed_w < loss && cord->cut_w == 0.0 && o.taken.empty() &&
                cord->spot_k > 293.15 && cord->spot_k < 573.15,
            "below the threshold the spot only warms");
    require(heightOf(*world, "weight") > 0.2, "and the weight still hangs");
}

// ---- 3. the mirror ------------------------------------------------------------------

void theMirrorIsNotCut() {
    auto world = hang(rig());
    laser(*world, {-1.0, 0.575, 0.0}, {1.0, 0.0, 0.0}, 5000.0);
    for (int i = 0; i < 10 * 240; ++i) tick(*world);
    const LiveOptics o = world->optics();
    const LiveOptics::Lit *mirror = litRow(o, "mirror");
    double mirror_k = 0.0;
    for (const auto &b : nlohmann::json::parse(world->thermoReport(false)).at("bodies"))
        if (b.at("name") == "mirror") mirror_k = b.at("temperature_k");
    bool taken = false;
    for (const LiveOptics::Taken &t : o.taken) taken = taken || t.body.rfind("mirror", 0) == 0;
    std::cout << "    mirror: " << o.watts.sent << " W on it, it absorbs " << (mirror ? mirror->absorbed_w : 0.0)
              << " W (" << 100.0 * (mirror ? mirror->absorbed_w : 0.0) / o.watts.sent << "%); after 10 s the plate "
              << "is at " << mirror_k << " K and its spot at " << (mirror ? mirror->spot_k : 0.0) << " K ("
              << (mirror && !mirror->spot_how.empty() ? mirror->spot_how : "nothing in the model takes aluminium away")
              << "; aluminium melts at 933 K)\n";
    require(mirror != nullptr && mirror->absorbed_w < 0.09 * o.watts.sent, "a polished mirror absorbs little");
    require(!taken && mirror != nullptr && mirror->spot_how.empty() && mirror->cut_w == 0.0, "and is not cut");
    require(mirror != nullptr && mirror->spot_k - mirror_k < 100.0,
            "what it absorbs is conducted away: its spot is within 100 K of the plate");
}

// ---- 4. glass and ice ---------------------------------------------------------------

void glassIsWarmedAndNeverCut() {
    for (const double watts : {5000.0, 500.0}) {
        // A pane 20 mm thick square to the beam, a concrete target behind it.
        auto world = LiveWorld::open(requestFor(
            {box("pane", MaterialPreset::Glass, {0.02, 0.2, 0.2}, {0.0, 0.575, 0.0}),
             box("target", MaterialPreset::Concrete, {0.04, 0.2, 0.2}, {0.5, 0.575, 0.0})}));
        laser(*world, {-1.0, 0.575, 0.0}, {1.0, 0.0, 0.0}, watts);
        for (int i = 0; i < 5 * 240; ++i) tick(*world);
        const LiveOptics o = world->optics();
        const LiveOptics::Lit *pane = litRow(o, "pane"), *target = litRow(o, "target");
        std::cout << "    " << watts << " W laser through a 20 mm pane: " << o.watts.sent << " W sent, the pane absorbs "
                  << (pane ? pane->absorbed_w : 0.0) << " W along its way through it (9 per metre, visible), the "
                  << "target behind absorbs " << (target ? target->absorbed_w : 0.0) << " W; the pane's spot would be "
                  << (pane ? pane->spot_k : 0.0) << " K, and " << o.taken.size() << " of its cells are taken\n";
        const double expected = o.watts.sent * (1.0 - std::exp(-9.0 * 0.02));
        require(pane != nullptr && std::abs(pane->absorbed_w - expected) < 0.06 * expected,
                "glass absorbs by depth, by Beer and Lambert");
        require(pane != nullptr && pane->spot_how.empty() && o.taken.empty(), "glass is never cut");
        require(target != nullptr && target->absorbed_w > 0.5 * 0.6 * o.watts.sent,
                "most of the beam goes through it");
    }
}

void iceMeltsByDepth() {
    struct Run {
        double visible, absorbed_w, cut_w, parted_s;
        std::size_t cells;
    };
    for (const double visible : {0.0, 1.0}) {
        // An ice cord 20 x 20 x 300 mm holding a 1.7 kg iron weight.
        auto world = hang(rig(MaterialPreset::Ice, 0.3, 0.06));
        laser(*world, {-1.0, 0.575, 0.0}, {1.0, 0.0, 0.0}, 5000.0, visible);
        for (int i = 0; i < 8; ++i) tick(*world);
        const LiveOptics::Lit *cord = litRow(world->optics(), "cord");
        const double absorbed = cord ? cord->absorbed_w : 0.0, cut = cord ? cord->cut_w : 0.0;
        const Parting p = runUntilParted(*world, visible > 0.0 ? 4.0 : 10.0);
        const LiveOptics o = world->optics();
        double j = 0.0, m3 = 0.0, kg = 0.0;
        for (const LiveOptics::Taken &t : o.taken) {
            j += t.energy_j;
            m3 += t.volume_m3;
            kg += t.kg;
        }
        // Ice at its melting point: melting is all a cell costs.
        const thermo::Model model = thermo::demonstrationModel();
        const double latent = model.latentHeatJPerKg(*model.meltingOf(model.index("ice")));
        std::cout << "    " << (visible > 0.0 ? "visible" : "infrared") << " 4.5 kW beam on an ice cord: it absorbs "
                  << absorbed << " W by depth, all of it melting where it is absorbed (" << cut << " W); "
                  << o.taken.size() << " cell(s) melted (" << m3 * 1e6 << " cm3, " << kg * 1e3 << " g, " << j
                  << " J = " << (kg > 0.0 ? j / kg : 0.0) << " J/kg against ice's latent heat " << latent
                  << " J/kg); the weight " << (p.parted_s > 0.0 ? "falls at " + std::to_string(p.parted_s) + " s"
                                                                 : std::string("still hangs")) << "\n";
        require(cut > 0.99 * absorbed, "ice at its melting point loses nothing from a spot: it melts there");
        if (visible > 0.0) {
            // 1.5 per metre: a 20 mm cord takes 3% of it, about 130 W; a cell
            // of ice costs about 2.4 kJ to melt, so nothing parts in 4 s.
            require(absorbed < 0.05 * world->optics().watts.sent && p.parted_s < 0.0,
                    "a visible beam passes through ice and melts it only slowly");
        } else {
            require(p.parted_s > 0.0 && p.parted_s < 3.0, "an infrared beam melts through an ice cord");
            require(kg > 0.0 && std::abs(j / kg - latent) < 0.01 * latent, "for ice's latent heat a kilogram");
        }
    }
}

// ---- 4b. a lens ------------------------------------------------------------------

// A wider beam (0.6 degrees) puts less than half of itself on the cord, over
// three cells. A convex lens in its way, its back focus on the cord's face,
// brings all of it onto one small spot: the spot is smaller and the cord parts
// sooner, by as much as the power on the cell it cuts is more.
void aLensFocusesTheBeamOnTheCord() {
    struct Run {
        double spot_w{}, area_mm2{}, parted_s{}, cut_w{};
    };
    std::vector<Run> runs;
    for (const bool lensed : {false, true}) {
        std::vector<SceneBody> bodies = rig();
        // A 60 x 60 x 20 mm block of glass holding a lens 60 mm across, faces
        // of radius 100 mm, 12 mm thick: f = 96.7 mm, 93.4 mm from its back
        // vertex to its focus for parallel light; the laser is 2.4 m back, so
        // its light comes to a focus a few millimetres further on.
        if (lensed) bodies.push_back(box("lens", MaterialPreset::Glass, {0.06, 0.06, 0.02}, {0.5, 0.575, 0.89}));
        auto world = hang(std::move(bodies));
        if (lensed) {
            const std::string refused = world->lens("lens", {0.5, 0.575, 0.89}, {0.0, 0.0, 1.0}, 0.1, -0.1, 0.012, 0.03);
            require(refused.empty(), "the lens: " + refused);
        }
        laser(*world, {-1.0, 0.575, 0.0}, {1.0, 0.0, 0.0}, 5000.0, 1.0, 256, 0.6);
        for (int i = 0; i < 8; ++i) tick(*world);
        Run run;
        const LiveOptics::Lit *cord = litRow(world->optics(), "cord");
        const double absorbed = cord ? cord->absorbed_w : 0.0;
        for (const thermo::SpotState &s : world->thermo()->spotStates())
            if (s.body == "cord" && s.power_w > run.spot_w) {
                run.spot_w = s.power_w;
                run.area_mm2 = s.area_m2 * 1e6;
                run.cut_w = s.cut_w;
            }
        const Parting p = runUntilParted(*world, 30.0);
        run.parted_s = p.parted_s + 8 * kDt;
        runs.push_back(run);
        std::cout << "    " << (lensed ? "through the lens" : "no lens") << ": the cord absorbs " << absorbed
                  << " W; its brightest spot " << run.spot_w << " W over "
                  << run.area_mm2 << " mm2, " << run.cut_w << " W of it taking oak away; the weight falls at "
                  << run.parted_s << " s\n";
    }
    require(runs[1].area_mm2 < 0.25 * runs[0].area_mm2, "the lens makes the spot smaller");
    require(runs[1].spot_w > 1.5 * runs[0].spot_w, "and puts more of the beam on it");
    require(runs[0].parted_s > 0.0 && runs[1].parted_s > 0.0 && runs[1].parted_s < 0.7 * runs[0].parted_s,
            "and the cord parts sooner");
}

// ---- 5. a burning glass -----------------------------------------------------------

// A 100 mm glass ball in an overhead sun of 1000 W/m2, an oak board at its
// focus. What the spot there does is measured, not assumed: the light on it
// against what it would lose held at oak's char line decides.
void aBurningGlass() {
    const double plane = 0.02, centre = plane + 0.0675;
    auto world = LiveWorld::open(requestFor(
        {box("board", MaterialPreset::Oak, {0.2, 0.02, 0.2}, {0.0, 0.01, 0.0}, false),
         [&] {
             SceneBody b;
             b.name = "ball";
             b.shape = BodyShape::Sphere;
             b.material = MaterialPreset::Glass;
             b.dimensions_m = {0.1, 0.1, 0.1};
             b.center_m = {0.0, centre, 0.0};
             b.anchored = true;
             return b;
         }()}));
    require(world->setSun(90.0, 0.0, 1000.0), "the sun would not go up");
    require(world->sunlight("sun", {{{0.0, centre, 0.0}, {0.1, 0.1, 0.1}}}, 0.0015) != 0, "the sunlight");
    for (int i = 0; i < 10 * 240; ++i) tick(*world);
    const thermo::SpotState *brightest = nullptr;
    if (std::getenv("SPOT_DEBUG"))
        for (const thermo::SpotState &s : world->thermo()->spotStates())
            std::cout << "      spot " << s.body << " " << s.power_w << " W over " << s.area_m2 * 1e6 << " mm2\n";
    for (const thermo::SpotState &s : world->thermo()->spotStates())
        if (s.body == "board" && (brightest == nullptr || s.power_w / s.area_m2 > brightest->power_w / brightest->area_m2))
            brightest = &s;
    require(brightest != nullptr, "the focus lands on the board");
    if (brightest == nullptr) return;
    std::cout << "    burning glass: the board's brightest spot takes " << brightest->power_w << " W over "
              << brightest->area_m2 * 1e6 << " mm2 (" << brightest->power_w / brightest->area_m2 / 1000.0
              << " kW/m2, the open sun's absorbed share is 0.5 kW/m2); held at oak's char line it would lose "
              << brightest->loss_w << " W, so it " << (brightest->cut_w > 0.0 ? "chars, " : "settles at ")
              << brightest->temperature_k << " K" << (brightest->cut_w > 0.0 ? ", with " : "")
              << (brightest->cut_w > 0.0 ? std::to_string(brightest->cut_w) + " W taking oak away" : std::string{})
              << "; " << world->optics().taken.size() << " cells taken in 10 s\n";
    require((brightest->cut_w > 0.0) == (brightest->power_w > brightest->loss_w),
            "it chars exactly when the light on it is more than it loses held at the char line");
    // The focus is a spot of its own, not averaged into the light round it.
    require(brightest->power_w / brightest->area_m2 > 50.0 * 500.0, "the focus is many times the open sun");
    require(brightest->temperature_k > 400.0, "and far hotter than the board");
}

} // namespace

int main() {
    const auto run = [](const char *name, void (*test)()) {
        std::cout << name << "\n";
        try {
            test();
        } catch (const std::exception &e) {
            std::cout << "[FAIL] " << name << " threw: " << e.what() << std::endl;
            ++failures;
        }
    };
    run("a laser parts an oak cord", aLaserPartsAnOakCord);
    run("a saved world keeps its spots", aSavedWorldKeepsItsSpots);
    run("a weaker beam takes longer, and a weak one only warms", aWeakerBeamTakesLonger);
    run("the mirror is not cut", theMirrorIsNotCut);
    run("glass is warmed and never cut", glassIsWarmedAndNeverCut);
    run("ice melts by depth", iceMeltsByDepth);
    run("a lens focuses the beam on the cord", aLensFocusesTheBeamOnTheCord);
    run("a burning glass", aBurningGlass);
    if (failures) {
        std::cout << failures << " failure(s)\n";
        return 1;
    }
    std::cout << "all light spot tests passed\n";
    return 0;
}
