// What the ground does about the point of a tool: ground-work-v1 and the
// tool-terrain process, in the real engine (Jolt and the terrain, nothing
// stubbed). docs/ground-work.md.
//
//  1. The model's numbers are the closed forms they claim to be.
//  2. A stake dropped point-first into soil: the work the ground's bite
//     measured is the energy the stake lost -- to the integrator's own term,
//     worked out -- and it went as deep as the model's resistance allows for
//     that work.
//  3. Drawn straight back out, the stake breaks nothing out.
//  4. The same swing twice is the same meeting, to the bit: the engine takes
//     nothing that is not physics, so nothing else can change it.
//  5. Soil against rock: the same swing into soil goes in and no further than
//     the point is long; onto bare rock it is stopped, loosens nothing and
//     says why; an iron point on the rock is "not supported", not "it failed".
//  6. A pry breaks ground out, and it is carried: the carried account grows by
//     exactly what the dig took, and the ground's ledger still closes.
//  7. The ground opened again from the dig as the report says it -- the edit a
//     room keeps -- has the same hole, to the bit, and carries the same.
//  8. A broad end -- a blade 0.12 m broad, across its swing as a hoe's is or
//     along it as an axe's is -- goes into the ground from every stand-back from
//     1.0 to 2.0 m: the corner it leads with, coming in tilted, is the point's,
//     not an ordinary contact that stops the swing short of the ground.
//
// Every number checked is printed.
#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "terrain/Environment.hpp"
#include "terrain/GroundWork.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <functional>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;
using Json = nlohmann::json;

constexpr double kDt = 1.0 / 240.0;   // what the room steps at
constexpr double kCell = 0.04;        // the yard's cell
constexpr double kG = 9.80665;        // the live world's gravity
constexpr double kPi = 3.14159265358979323846;

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message) + ": actual=" + std::to_string(actual) +
                                 " expected=" + std::to_string(expected) +
                                 " tolerance=" + std::to_string(tolerance));
}

Json box(const std::string &name, const std::string &material, Vec3 size, Vec3 at,
         const std::string &join = {}) {
    Json out{{"name", name}, {"shape", "box"}, {"material", material},
             {"dimensions_m", {size.x, size.y, size.z}}, {"center_m", {at.x, at.y, at.z}}};
    if (!join.empty()) out["join"] = join;
    return out;
}

// Level ground: rock at y = 0, then `soil` of soil and `sand` of sand over it,
// 4.7 m square in 0.1 m columns, centred on the origin, dry.
Json ground(double soil, double sand) {
    return {{"generate", {{"kind", "flat"}, {"nx", 48}, {"nz", 48}, {"cell_m", 0.1},
                          {"soil_m", soil}, {"sand_m", sand}, {"discharge_m3_s", 0.0}}}};
}
// The same, as the game's 25 cm cubes: 5 m square.
Json cubeGround(double soil, double sand) {
    return {{"surface", "columns"},
            {"generate", {{"kind", "flat"}, {"nx", 20}, {"nz", 20}, {"cell_m", 0.25},
                          {"soil_m", soil}, {"sand_m", sand}, {"discharge_m3_s", 0.0}}}};
}

std::unique_ptr<LiveWorld> open(const Json &scene) {
    const std::string text = scene.dump();
    TileImpactRequest request;
    request.cell_size_m = kCell;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(text);
    readSceneSettings(text, request);
    return LiveWorld::open(request);
}

// Step, answering every break by running it -- as the room and the MCP do.
void stepOnce(LiveWorld &world) {
    for (int tries = 0; tries < 8; ++tries) {
        world.step(kDt);
        if (!world.steppedBack()) return;
        for (const std::string &name : world.breakable()) (void)world.fracture(name);
    }
}

LiveBodyPose poseOf(const LiveWorld &world, const std::string &name) {
    for (const LiveBodyPose &pose : world.poses())
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

std::string said(const LiveGroundWork &w) {
    char text[700];
    std::snprintf(text, sizeof text,
                  "%s in %s%s: closing %.2f m/s, deepest %.1f mm, sideways %.1f mm, impulse %.3f N s, "
                  "peak %.0f N, work %.3f J (in %.3f, sideways %.3f), loosened %.2f L (%.3f kg)%s%s",
                  w.kind.c_str(), w.ground.c_str(), w.open ? " (open)" : "", w.closing_speed_m_s,
                  1000.0 * w.depth_m, 1000.0 * w.sideways_m, w.impulse_n_s, w.peak_force_n, w.work_j,
                  w.penetration_work_j, w.breakout_work_j, 1000.0 * w.loosened.total(), w.loosened_kg,
                  w.why.empty() ? "" : " -- ", w.why.c_str());
    return text;
}

// Take the stroke to its end, then let the hand hold where the grip is -- as a
// person stops pushing once the blow has landed -- and let the world settle.
std::string finishStroke(LiveWorld &live, int most_steps, int settle_steps) {
    for (int i = 0; i < most_steps; ++i) {
        stepOnce(live);
        if (!live.hand().stroking) break;
    }
    const std::string ended = live.hand().stroke_ended;
    if (!live.held().empty()) live.moveHeld(live.hand().grip_m);
    for (int i = 0; i < settle_steps; ++i) stepOnce(live);
    return ended;
}

// ---- 1. the model ------------------------------------------------------------

void theModelIsTheClosedForms() {
    using namespace banjo::terrain;
    // Prandtl's N_q and N_c and Vesic's N_gamma at 30 degrees, worked by hand:
    // N_q = e^(pi tan 30) tan^2 60 = 6.1337 x 3 = 18.401, N_c = (N_q - 1) cot 30
    // = 30.140, N_gamma = 2 (N_q + 1) tan 30 = 22.402.
    const BearingFactors f = bearingFactors(30.0);
    near(f.nq, 18.401, 0.001, "N_q at 30 degrees");
    near(f.nc, 30.140, 0.001, "N_c at 30 degrees");
    near(f.ngamma, 22.402, 0.001, "N_gamma at 30 degrees");
    near(passiveCoefficient(30.0), 3.0, 1e-12, "K_p at 30 degrees");
    // No friction: Prandtl's 2 + pi.
    near(bearingFactors(0.0).nc, 2.0 + kPi, 1e-12, "N_c at 0 degrees");

    const GroundMaterial &soil = soilMaterial();
    ToolPointShape point{0.04, 0.04, 30.0, 0.2};
    // The wedge: 2 mm at the tip, thickening at tan 15 each side, to 40 mm.
    near(pointThicknessAt(point, 0.0), 0.002, 1e-12, "the tip's thickness");
    near(pointThicknessAt(point, 0.05), 0.002 + 0.1 * std::tan(15.0 * kPi / 180.0), 1e-12,
         "the thickness 50 mm back");
    near(pointThicknessAt(point, 0.1), 0.04, 1e-12, "the thickness where it stops growing");
    // q at 100 mm in firm soil: c N_c + gamma d N_q + 1/2 gamma t N_gamma.
    const double gamma = 1600.0 * 9.81;
    const double q = 2000.0 * f.nc + gamma * 0.1 * f.nq + 0.5 * gamma * 0.04 * f.ngamma;
    near(bearingPressurePa(soil, point, 0.1), q, 1e-6, "q at 100 mm");
    near(penetrationResistanceN(soil, point, 0.1), q * 0.04 * 0.04, 1e-9, "F at 100 mm");
    // The work integral and its inverse agree.
    const double w = penetrationWorkJ(soil, point, 0.12);
    near(depthForWorkM(soil, point, w), 0.12, 1e-6, "the depth that work reaches");
    // Passive: (1/2 gamma d^2 K_p + 2 c d sqrt(K_p)) (b + d).
    const double p = (0.5 * gamma * 0.04 * 3.0 + 2.0 * 2000.0 * 0.2 * std::sqrt(3.0)) * (0.04 + 0.2);
    near(passiveResistanceN(soil, 0.2, 0.04), p, 1e-6, "P at 200 mm");
    // Nothing comes loose until the point has moved a tenth of its depth;
    // then the wedge, and what it sweeps after that.
    near(loosenedVolumeM3(soil, 0.2, 0.04, 0.019), 0.0, 0.0, "loosened before the wedge fails");
    const double wedge = 0.5 * 0.2 * 0.2 * std::sqrt(3.0);
    near(loosenedVolumeM3(soil, 0.2, 0.04, 0.03), (0.04 + 0.2) * (wedge + 0.2 * (0.03 - 0.02)), 1e-12,
         "the wedge and 10 mm more");
    // The gate.
    require(judgeGround(true, 0.0, 35.0e6, "oak").answer == GroundAnswer::TooHard,
            "an oak point on rock was not stopped");
    require(judgeGround(true, 0.0, 1.5e9, "iron").answer == GroundAnswer::Breakable,
            "an iron point on rock does not break it out");
    // rock-work-v1: what a cubic metre of each ground costs to break, and what
    // that means for the two things that will do the breaking.
    const double rock_es = specificEnergyJPerM3(groundHardnessPa(RunKind::Rock));
    const double cap_es = specificEnergyJPerM3(groundHardnessPa(RunKind::OxidisedOre));
    require(rock_es > 25.0e6 && rock_es < 35.0e6, "fresh rock costs about 30 MJ the cubic metre");
    require(cap_es < 0.1 * rock_es, "and the oxidised cap of a vein is far cheaper");
    // A hand blow of a hundred joules, against a 0.25 m cube of each.
    const double cube = 0.25 * 0.25 * 0.25;
    const double blows_rock = cube / brokenVolumeM3(groundHardnessPa(RunKind::Rock), 100.0);
    const double blows_cap = cube / brokenVolumeM3(groundHardnessPa(RunKind::OxidisedOre), 100.0);
    std::printf("  rock-work-v1: fresh rock %.0f MJ/m^3, oxidised ore %.1f MJ/m^3; a 0.25 m cube is "
                "%.0f hand blows of 100 J in the rock and %.0f in the cap\n",
                rock_es / 1.0e6, cap_es / 1.0e6, blows_rock, blows_cap);
    // 4,688 blows to a 0.25 m cube, which at a swing every two seconds is two
    // and a half hours: nobody hand-mines fresh rock, and the model says so.
    require(blows_rock > 3000.0, "fresh rock is hours of hand work to the cube, as it should be");
    require(blows_cap < 1000.0, "the oxidised cap is what a person can work");
    require(brokenVolumeM3(groundHardnessPa(RunKind::Void), 100.0) == 0.0,
            "there is nothing in a void to break");
    require(judgeGround(false, 0.02, 35.0e6, "oak").answer == GroundAnswer::NotSupported,
            "wet ground was not 'not supported'");
    require(judgeGround(false, 0.0, 35.0e6, "oak").answer == GroundAnswer::Penetrable,
            "dry soil was not penetrable");
    std::printf("  model: N_q %.3f, N_c %.3f, N_gamma %.3f; F(100 mm) %.1f N; P(200 mm) %.1f N; "
                "the wedge at 200 mm %.2f L\n",
                f.nq, f.nc, f.ngamma, penetrationResistanceN(soil, point, 0.1),
                passiveResistanceN(soil, 0.2, 0.04), 1000.0 * (0.04 + 0.2) * wedge);
}

// ---- 2 and 3. a stake dropped into soil, and drawn out ------------------------

void aStakeDroppedIntoSoilAndDrawnOut() {
    // An oak stake 400 mm long standing point-down, its tip a metre above firm
    // soil, let fall. Nothing but gravity and the ground act on it.
    const double top = 0.4;   // the ground's surface
    Json scene{{"terrain", ground(0.4, 0.0)},
               {"bodies", {box("stake", "oak", {0.04, 0.4, 0.04}, {0.02, top + 1.0 + 0.2, 0.02})}}};
    auto live = open(scene);
    const Vec3 tip{0.02, top + 1.0, 0.02};
    const unsigned id = live->toolPoint("stake", tip, {0.0, -1.0, 0.0}, 0.04, 0.04, 30.0, 0.2,
                                        {0.02, top + 1.38, 0.02});
    require(id != 0, "the stake would not take a point: " + live->toolPointRefusal());
    const double mass = poseOf(*live, "stake").mass_kg;
    const auto speed = [&]() { return length(poseOf(*live, "stake").velocity_m_s); };
    const auto energy = [&]() {
        const LiveBodyPose p = poseOf(*live, "stake");
        return 0.5 * mass * lengthSquared(p.velocity_m_s) + mass * kG * p.position_m.y;
    };
    double at_entry = 0.0;
    double kinetic_at_entry = 0.0;
    int entered = -1, at_rest = -1;
    for (int i = 0; i < 480; ++i) {
        const double was = energy();
        const double moving = speed();
        stepOnce(*live);
        const std::vector<LiveGroundWork> work = live->groundWork();
        if (entered < 0 && !work.empty() && work.front().kind == "in the ground") {
            entered = i;
            at_entry = was;   // the step the bite first acted in began here
            kinetic_at_entry = 0.5 * mass * moving * moving;
        }
        if (entered >= 0 && at_rest < 0 && speed() < 0.01) at_rest = i;
    }
    require(entered >= 0, "the stake never went into the ground");
    require(at_rest >= 0, "the stake never came to rest in the ground");
    const LiveGroundWork w = live->groundWork().front();
    const double lost = at_entry - energy();
    std::printf("  stake, %.3f kg, from 1 m: %s\n", mass, said(w).c_str());
    // The work is the energy lost. What the bite's impulses took out of the
    // stake is its impulse times the MEAN of the speeds at the two ends of each
    // step -- which for a step is exactly what a constant force takes. The
    // solver moves the stake by its END speed (semi-implicit Euler), so in its
    // books gravity does m g v_end dt a step, and over the steps it takes to
    // bring the stake to rest that comes to m g dt v_entry / 2 less than the
    // mean-speed account: the integrator's term, not the ground's. Beyond it,
    // the damping every live body carries (0.02 a second on its speed) takes
    // at most 2 x 0.02 of the kinetic energy for each second it is moving.
    const double integrator = mass * kG * kDt * w.closing_speed_m_s / 2.0;
    const double damping = 2.0 * 0.02 * kinetic_at_entry * (at_rest - entered + 1) * kDt;
    std::printf("  lost %.4f J from the step the bite first acted in; the bite measured %.4f J; "
                "the integrator's term %.4f J; damping at most %.4f J\n",
                lost, w.work_j, integrator, damping);
    near(w.work_j - lost, integrator, damping + 1e-6,
         "the bite's work against the energy the stake lost, less the integrator's term");
    // And the depth is what the model's resistance allows for that work. Each
    // step's limit is the mean resistance over as far as the point COULD go that
    // step, and once the ground is slowing it it goes less far than that, so
    // the ground's resistance runs ahead of the depth: by at most one step's
    // travel at the arrival speed.
    const terrain::ToolPointShape shape{0.04, 0.04, 30.0, 0.2};
    const double modelled = terrain::depthForWorkM(terrain::soilMaterial(), shape, w.work_j);
    const double step_travel = w.closing_speed_m_s * kDt;
    std::printf("  the model's depth for that work: %.1f mm; it went %.1f mm (one step's travel %.1f mm)\n",
                1000.0 * modelled, 1000.0 * w.depth_m, 1000.0 * step_travel);
    require(w.depth_m <= modelled + 1e-9 && modelled - w.depth_m <= step_travel,
            "the depth is not within a step's travel short of the model's depth for the work");
    require(w.depth_m > 0.01 && w.depth_m < 0.2, "the stake went in less than a centimetre, or through");

    // Drawn straight back out the way it went in: nothing is broken out.
    const double carried_before = live->environment()->carried().total();
    const Vec3 grip = poseOf(*live, "stake").position_m + Vec3{0.0, 0.18, 0.0};
    require(live->wield("stake", grip), "the stake could not be taken by its top");
    LiveStroke up;
    up.path_m = {grip, grip + Vec3{0.0, 0.3, 0.0}};
    up.speed_m_s = 0.5;
    up.accel_m_s2 = 4.0;
    up.give_up_s = 3.0;
    std::string why;
    require(live->stroke(up, why), "the pull was refused: " + why);
    (void)finishStroke(*live, 960, 30);
    const LiveGroundWork out = live->groundWork().front();
    std::printf("  drawn straight out: %s\n", said(out).c_str());
    require(!out.open && out.kind == "pulled out", "the stake was not drawn out cleanly");
    require(out.loosened.total() == 0.0, "drawing a point straight out loosened ground");
    near(live->environment()->carried().total(), carried_before, 0.0, "the carried account");
}

// ---- the pick, and swinging it --------------------------------------------------

// A one-piece oak pick: a handle along x and an arm hanging from its +x end,
// joined as one body -- a branch with a long section to hold and a short arm
// that is the point. Cells are 40 mm; every centre is on the cell grid.
Json pick(const std::string &material, double lift) {
    return {box("pick", material, {0.8, 0.04, 0.04}, {0.0, lift + 1.02, 0.02}, "pick"),
            box("pick arm", material, {0.04, 0.28, 0.04}, {0.38, lift + 0.86, 0.02}, "pick")};
}
constexpr double kTipX = 0.38, kTipZ = 0.02;
constexpr double kGripX = -0.36;
constexpr double kPointLength = 0.2;

Json splitPick(const std::string &head_material, double top = .4) {
    return {{"terrain", ground(top, 0)}, {"bodies", {
        box("handle", "oak", {.8,.04,.04}, {0,top+1.02,.02}),
        box("head", head_material, {.04,.28,.04}, {.38,top+.86,.02})}}};
}

unsigned headPoint(LiveWorld &world, const std::string &grip_body = "handle", Vec3 grip = {-.36,1.42,.02}) {
    return world.toolPoint("head", {.38,1.12,.02}, {0,-1,0}, .04,.04,30,.2,grip,grip_body);
}

void aSeparateHeadNeedsAnActualFixedHandle() {
    auto world = open(splitPick("iron"));
    std::string why;
    const auto before = world->snapshot(why);
    require(headPoint(*world) == 0, "nearby wood was mistaken for an attached handle");
    require(world->snapshot(why) == before, "refused point changed the world");
    require(world->hinge("handle", "head", {.38,1.4,.02}, {0,0,1}) != 0, "fixture hinge refused");
    require(headPoint(*world) == 0, "a hinge was mistaken for a fixed tool");
    world = open(splitPick("iron"));
    require(world->fix("handle", "head", {.38,1.4,.02}, {0,1,0}, 0,1000,100) != 0, "fixture release refused");
    require(headPoint(*world) == 0, "a one-way release was mistaken for a fixed handle");
    world = open(splitPick("iron"));
    require(world->fix("handle", "head", {.38,1.4,.02}, {0,1,0}, 5000,5000) != 0, "fixture fixing refused");
    require(headPoint(*world,"absent") == 0, "an absent handle was admitted");
    require(headPoint(*world,"handle", {3,1.42,.02}) == 0, "a grip off handle matter was admitted");
    require(headPoint(*world) != 0, "actual fixed handle refused: " + world->toolPointRefusal());
}

void groundRaysIgnoreOnlyTheActorsWholeFixedTool() {
    for (const std::string material : {"glass", "oak", "iron"}) {
        auto scene = splitPick(material);
        scene["bodies"].push_back(box("target", "oak", {.04,.12,.04}, {.37,.76,.02}));
        auto world = open(scene);
        const auto joint = world->fix("handle", "head", {.38,1.4,.02}, {0,1,0}, 5000,5000);
        require(joint != 0, "fixture fixing refused");
        world->selectHand("alice");
        require(world->wield("handle", {-.36,1.42,.02}), "fixture handle refused");
        const Vec3 from{.38,2,.02}, down{0,-1,0};
        std::string why;
        const auto before = world->snapshot(why);
        const auto ordinary = world->pick(from, down, 3, false);
        require(ordinary.hit && ordinary.name == "handle", material + ": ordinary ray lost held matter");
        const auto past = world->pick(from, down, 3, true);
        require(past.hit && past.name == "target", material + ": own separate head hid unrelated matter");
        const auto ground_ray = world->pick({.38,1.0,.025}, down, 3, true);
        require(ground_ray.hit && ground_ray.name == "target", "ray skipped the next actual shape");
        const auto bare = world->pick({.395,2,.02}, down, 3, true);
        require(bare.hit && bare.name.empty(), "filtered ray lost terrain");
        near(bare.point_world_m.y, .4, 1e-5, "actual terrain height");
        require(world->snapshot(why) == before, "ray filtering changed the world");
        world->selectHand("bob");
        const auto peer = world->pick({.38,1.3,.02}, down, 3, true);
        require(peer.hit && peer.name == "head", "another actor's held head was hidden");
        world->selectHand("alice");
        world->unhinge(joint);
        const auto detached = world->pick({.38,1.3,.02}, down, 3, true);
        require(detached.hit && detached.name == "head", "detached head was still filtered as held");
    }
}

void fixedMixedToolsRetainMaterialsMassAndOwnedWork() {
    for (const auto &[material, density] : std::vector<std::pair<std::string,double>>{
            {"glass",2500}, {"oak",700}, {"iron",7870}}) {
        const auto scene = splitPick(material);
        auto world = open(scene);
        // Explicit finite fixture strengths, not a calibrated metal/wood joint law.
        const auto joint = world->fix("handle", "head", {.38,1.4,.02}, {0,1,0}, 5000,5000);
        require(joint != 0 && headPoint(*world) != 0, material + ": fixed tool refused");
        const double head_mass = poseOf(*world,"head").mass_kg;
        const double handle_mass = poseOf(*world,"handle").mass_kg;
        near(head_mass, .04*.28*.04*density, 2e-6*head_mass, "head's own material mass");
        near(handle_mass, .8*.04*.04*700, 2e-6*handle_mass, "wood handle's own mass");
        require(world->toolPoints().front().material == material, "point material was homogenized");
        world->selectHand("alice");
        world->setCarryLimitKg(head_mass+handle_mass-.01);
        require(!world->wield("handle", {-.36,1.42,.02}),"pickup ignored the head's native mass at the carry limit");
        world->setCarryLimitKg(80);
        require(world->wield("handle", {-.36,1.42,.02}), "could not wield through handle");
        near(world->carriedObjectsKg(), head_mass+handle_mass, 2e-6*(head_mass+handle_mass), "whole fixed tool carrying mass");
        near(world->heldObjectsKg(),head_mass+handle_mass,2e-6*(head_mass+handle_mass),"actual held mass excludes bag");
        world->selectHand("bob");
        require(!world->wield("head", {.38,1.26,.02}), "another player took a held tool's head");
        world->selectHand("alice");
        std::string why;
        const auto saved = world->snapshot(why);
        require(!saved.empty(), "fixed tool could not save: " + why);
        TileImpactRequest request; request.cell_size_m=kCell;request.backend=BackendKind::CpuParallel;
        request.bodies=readSceneJson(scene.dump());readSceneSettings(scene.dump(),request);
        world=LiveWorld::open(request,saved);
        require(world->restored().tier == "whole", "fixed tool did not reopen whole");
        world->selectHand("alice");
        require(world->held() == "handle" && world->toolPoints().front().grip_body == "handle" &&
                world->toolPoints().front().grip_connected, "reopen lost fixed grip binding");
        near(world->carriedObjectsKg(),head_mass+handle_mass,2e-6*(head_mass+handle_mass),"reopened tool mass");
        const double energy_before=world->mechanicalEnergyJ();
        // Match the ordinary contact gesture: bounded point-down readiness,
        // 60 mm clearance, 80 mm bite, 40 mm working drag and withdrawal.
        // The hand acts only on the handle; the fixing transmits actual load.
        const Vec3 ready{-.44,.76,.02};
        world->moveHeld(ready);
        for (int i=0;i<480;++i) {
            stepOnce(*world);
            require(length(world->hand().force_n)<=world->handStrength()+1e-8,"fixed assembly exceeds hand force limit");
        }
        const Vec3 grip=world->hand().grip_m;
        LiveStroke contact;contact.path_m={grip,grip+Vec3{0,-.14,0},grip+Vec3{-.04,-.14,0},grip+Vec3{-.04,0,0}};
        contact.speed_m_s=4;contact.accel_m_s2=80;contact.lead_m=.025;contact.give_up_s=1;
        const auto preview=world->previewStroke(contact,kDt,3);
        require(!preview.why.empty() && preview.why.find("jointed native trial")!=std::string::npos,
            "fixed assembly was passed through an unjointed free-body projection");
        require(world->stroke(contact,why), material + ": handle contact refused: " + why);
        (void)finishStroke(*world,480,120);
        require(!world->groundWork().empty(),material + ": the separate head met no ground");
        if (world->groundWork().front().open && world->toolPoints().front().grip_connected) {
            LiveStrike pry;pry.lever=true;pry.shoulder_m={-.9,1.85,.02};pry.speed_m_s=1.2;pry.lever_deg=40;
            require(world->strike(pry,why), material + ": handle lever refused: " + why);
            (void)finishStroke(*world,960,30);
            if (world->groundWork().front().open) {
                LiveStroke up;const auto at=world->hand().grip_m;up.path_m={at,at+Vec3{0,.4,0}};
                up.speed_m_s=.6;up.accel_m_s2=4;up.give_up_s=3;
                require(world->stroke(up,why), "fixed tool pull refused: " + why);
                (void)finishStroke(*world,960,30);
            }
        }
        const auto work=world->groundWork().front();
        require(work.tool == "handle", "native work is not associated with the held assembly root");
        double collected=0,ground_work=0;
        for (const auto &meeting : world->groundWork()) {
            collected+=meeting.loosened.total();ground_work+=meeting.work_j;
            if (meeting.loosened_kg>0) require(meeting.actor == "alice", "a subsequent contact credited another player");
        }
        const double unclosed=world->hand().work_j-(world->mechanicalEnergyJ()-energy_before)-ground_work;
        require(std::isfinite(unclosed),"fixed tool energy accounting became non-finite");
        std::printf("  fixed %s head / oak handle: %.9g + %.9g kg; hand work %.9g J; %s; actor %s; terrain residual %.12g m3; all ground work %.9g J; unclosed work - delta mechanical - ground work %.9g J\n",
            material.c_str(),head_mass,handle_mass,world->hand().work_j,said(work).c_str(),work.actor.c_str(),
            world->environment()->terrain().residual().total(),ground_work,unclosed);
        require(work.actor == "alice", "head contact lost handle owner's account");
        if (material == "iron") require(!work.open && work.loosened_kg > 0 && work.tool_whole,
            "iron head / oak handle did not complete usable digging");
        near(world->environment()->carried().total(),collected,1e-12,"all owned fixed-tool removal credits");
        world->selectHand("bob");near(world->environment()->carriedKg(),0,0,"peer receives no fixed-tool ground");
    }
}

void aDetachedHeadCannotBeUsedThroughItsOldHandle() {
    auto world=open(splitPick("iron"));
    const auto joint=world->fix("handle","head",{.38,1.4,.02},{0,1,0},5000,5000);
    require(joint && headPoint(*world), "fixture fixing/point refused");
    require(world->wield("handle",{-.36,1.42,.02}), "fixture handle refused");
    world->unhinge(joint);
    require(!world->toolPoints().front().grip_connected, "released fixing still reports a connected grip");
    LiveStrike strike;strike.target_m={.3,.4,.02};strike.shoulder_m={-.9,1.85,.02};
    std::string why;require(!world->strike(strike,why), "detached head operated through its old handle");
    require(why.find("no longer fixed") != std::string::npos, "detached tool refusal lost its reason");
    near(world->carriedObjectsKg(),poseOf(*world,"handle").mass_kg,2e-6,"detached head no longer adds held mass");
}

void fixedHorizontalToolsLiftWithoutASecondSeamResponse() {
    for (const std::string material : {"glass","oak","iron"}) {
        const Json scene={{"terrain",ground(.4,0)},{"bodies",{
            box("handle","oak",{.8,.04,.04},{0,.42,1.22}),
            box("head",material,{.04,.04,.28},{.38,.42,1.06})}}};
        auto world=open(scene);
        require(world->fix("handle","head",{.38,.42,1.2},{0,0,1},5000,5000)!=0,"horizontal fixing refused");
        require(world->toolPoint("head",{.38,.42,.92},{0,0,-1},.04,.04,30,.2,{-.36,.42,1.22},"handle")!=0,
            "horizontal point refused");
        for (int i=0;i<240;++i) stepOnce(*world);
        const auto point=world->toolPoints().front();
        require(point.grip_connected && world->wield("handle",point.grip_m),"grounded tool lost its fixing");
        const double before=world->mechanicalEnergyJ();
        double peak_axial=0,peak_shear=0;
        const auto advance=[&](int n) {
            for (int i=0;i<n;++i) {
                stepOnce(*world);
                const auto joint=world->joints().front();
                peak_axial=std::max(peak_axial,joint.tension_n_now);
                peak_shear=std::max(peak_shear,joint.shear_n_now);
                require(joint.attached,"ordinary horizontal lift broke the fixing: "+joint.parted_because);
                require(length(world->hand().force_n)<=800+1e-8,"horizontal lift exceeded the hand bound");
            }
        };
        world->moveHeld(point.grip_m+Vec3{0,.6,0});advance(48);
        world->moveHeld({-.9,1.52,.02});advance(480);
        world->aimHeld({std::sqrt(.5),-std::sqrt(.5),0,0});
        world->moveHeld({-.44,1.36,.02});advance(480);
        require(world->toolPoints().front().grip_connected,"turn lost separate grip");
        const double unclosed=world->hand().work_j-(world->mechanicalEnergyJ()-before);
        require(std::isfinite(unclosed),"lift energy account is non-finite");
        std::printf("  horizontal %s / oak: peak axial %.9g N; shear %.9g N; hand work %.9g J; unclosed work - delta mechanical %.9g J\n",
            material.c_str(),peak_axial,peak_shear,world->hand().work_j,unclosed);
    }
}

void fixedToolsKeepPrivateBagOwnershipAndCarry() {
    for (const std::string material : {"glass","oak","iron"}) {
        const auto scene=splitPick(material);
        auto world=open(scene);
        require(world->fix("handle","head",{.38,1.4,.02},{0,1,0},5000,5000) && headPoint(*world),
            "fixed bag fixture refused");
        const double mass=poseOf(*world,"handle").mass_kg+poseOf(*world,"head").mass_kg;
        world->selectHand("alice");
        require(world->wield("handle",{-.36,1.42,.02}),"fixed bag fixture not wieldable");
        std::string why;
        require(world->park("handle",why),"fixed assembly could not be stowed: "+why);
        require(world->parked("handle") && world->parked("head"),"only part of tool entered bag");
        near(world->carriedObjectsKg(),mass,2e-6*mass,"bag counts both materials once");
        const auto saved=world->snapshot(why);
        require(!saved.empty(),"parked tool did not save: "+why);
        TileImpactRequest request;request.cell_size_m=kCell;request.backend=BackendKind::CpuParallel;
        request.bodies=readSceneJson(scene.dump());readSceneSettings(scene.dump(),request);
        for (const bool carry : {false,true}) {
            auto restored=carry?LiveWorld::open(request,saved,LiveWorld::carryAll(saved)):LiveWorld::open(request,saved);
            restored->selectHand("bob");
            near(restored->carriedObjectsKg(),0,0,"peer counts none of parked assembly");
            require(!restored->unpark("head",{.38,1.26,.02},{},why),"peer took parked head alone");
            restored->selectHand("alice");
            near(restored->carriedObjectsKg(),mass,2e-6*mass,"restart retains private whole tool mass");
            require(restored->unpark("handle",{0,1.42,.02},{},why),"owner cannot equip saved assembly: "+why);
            require(!restored->parked("handle") && !restored->parked("head"),"head left behind in bag");
            const auto points=restored->toolPoints();
            require(points.size()==1 && points.front().grip_body=="handle" && points.front().grip_connected,
                "bag restart lost native fixed point binding");
            require(points.front().material==material,"bag restart homogenized head material");
            require(restored->wield("handle",points.front().grip_m),"restored assembly cannot wield");
            near(restored->carriedObjectsKg(),mass,2e-6*mass,"equipped assembly not counted once");
        }
    }
}

struct Swing {
    std::unique_ptr<LiveWorld> live;
    std::vector<LiveGroundWork> work;
    std::string ended;
    double carried_before_m3{};
};

// Open a world with the pick in the air above the ground, take it by its grip
// and swing it at the ground 0.3 m out, from a shoulder behind it.
Swing swingAt(double soil, double sand, const std::string &material, bool cubes = false,
              std::optional<Vec3> aim = std::nullopt) {
    const double top = soil + sand;
    Json scene{{"terrain", cubes ? cubeGround(soil, sand) : ground(soil, sand)}, {"bodies", pick(material, top)}};
    Swing out;
    out.live = open(scene);
    LiveWorld &live = *out.live;
    if (aim) live.setGroundAim(*aim);
    const Vec3 tip{kTipX, top + 0.72, kTipZ};
    const Vec3 grip{kGripX, top + 1.02, kTipZ};
    require(live.toolPoint("pick", tip, {0.0, -1.0, 0.0}, 0.04, 0.04, 30.0, kPointLength, grip) != 0,
            "the pick would not take a point: " + live.toolPointRefusal());
    require(live.wield("pick", grip), "the pick could not be taken by its grip");
    out.carried_before_m3 = live.environment()->carried().total();
    LiveStrike strike;
    strike.target_m = {0.3, top, kTipZ};
    strike.shoulder_m = {-0.9, top + 1.45, kTipZ};
    strike.speed_m_s = 4.0;
    strike.raise_deg = 110.0;
    std::string why;
    require(live.strike(strike, why), "the swing was refused: " + why);
    out.ended = finishStroke(live, 480, 120);
    out.work = live.groundWork();
    return out;
}

void theSameSwingIsTheSameMeeting() {
    const Swing a = swingAt(0.4, 0.0, "oak");
    const Swing b = swingAt(0.4, 0.0, "oak");
    require(!a.work.empty() && !b.work.empty(), "a swing met no ground");
    require(a.work.size() == b.work.size(), "two identical swings met the ground a different number of times");
    for (std::size_t i = 0; i < a.work.size(); ++i) {
        const LiveGroundWork &x = a.work[i], &y = b.work[i];
        require(x.kind == y.kind && x.ground == y.ground, "two identical swings met different ground");
        require(x.depth_m == y.depth_m && x.work_j == y.work_j && x.impulse_n_s == y.impulse_n_s &&
                    x.closing_speed_m_s == y.closing_speed_m_s && x.sideways_m == y.sideways_m,
                "two identical swings did not do the same to the bit");
    }
    std::printf("  twice (stroke %s): %s\n", a.ended.c_str(), said(a.work.front()).c_str());
}

// An iron stake 400 mm long, dropped point-down onto bare rock from 0.5 m.
// (Not an iron PICK: 13.6 kg on the end of an 0.8 m handle is 61 N m about the
// grip, more than the hand's 60 N m wrist can hold level, so the swing droops
// and the point never meets the ground where it was aimed -- which is the
// physics, and not what this checks.)
std::vector<LiveGroundWork> ironStakeOnRock() {
    Json scene{{"terrain", ground(0.0, 0.0)},
               {"bodies", {box("iron stake", "iron", {0.04, 0.4, 0.04}, {0.02, 0.5 + 0.2, 0.02})}}};
    auto live = open(scene);
    require(live->toolPoint("iron stake", {0.02, 0.5, 0.02}, {0.0, -1.0, 0.0}, 0.04, 0.04, 30.0, 0.2,
                            {0.02, 0.88, 0.02}) != 0,
            "the iron stake would not take a point: " + live->toolPointRefusal());
    for (int i = 0; i < 360; ++i) stepOnce(*live);
    return live->groundWork();
}

void soilAgainstRock() {
    const Swing soil = swingAt(0.4, 0.0, "oak");
    const Swing rock = swingAt(0.0, 0.0, "oak");
    struct {
        std::vector<LiveGroundWork> work;
        std::string ended{"(dropped)"};
    } iron{ironStakeOnRock()};
    require(!soil.work.empty(), "the swing into soil met nothing");
    const LiveGroundWork &s = soil.work.front();
    std::printf("  oak into soil (stroke %s): %s\n", soil.ended.c_str(), said(s).c_str());
    require(s.ground == "soil" && s.open, "the oak point is not in the soil");
    require(s.kind == "in the ground" || s.kind == "broke out", "the oak point's meeting is not a bite");
    require(s.depth_m > 0.03, "the oak point went less than 30 mm into the soil");
    // No further than it is point. What lies beyond meets the ground as a
    // surface, which lets a cell in by Jolt's penetration slop (20 mm) and a
    // step's travel before it stops it.
    require(s.depth_m <= kPointLength + 0.02 + s.closing_speed_m_s * kDt,
            "the pick went further into the soil than its point is long");
    require(s.work_j > 0.0 && s.impulse_n_s > 0.0, "the soil took no work from the swing");

    require(!rock.work.empty(), "the swing onto rock met nothing");
    const LiveGroundWork &r = rock.work.front();
    std::printf("  oak onto rock (stroke %s): %s\n", rock.ended.c_str(), said(r).c_str());
    require(r.kind == "stopped" && r.supported && r.ground == "rock", "the rock did not stop the oak point");
    require(r.loosened.total() == 0.0 && r.depth_m == 0.0, "the rock gave something up to an oak point");
    require(r.why.find("cannot press") != std::string::npos, "the rock's answer does not say why");
    require(rock.live->environment()->carried().total() == rock.carried_before_m3,
            "the rock was carried away by an oak point");

    require(!iron.work.empty(), "the iron stake met no rock");
    const LiveGroundWork &i = iron.work.front();
    std::printf("  iron onto rock %s: %s\n", iron.ended.c_str(), said(i).c_str());
    // Since rock-work-v1 a point harder than the rock breaks it, where before
    // there was no law and the engine said so. A stake DROPPED on it does 20-odd
    // joules of work, which at 30 MJ the cubic metre buys about a cubic
    // millimetre: it chips the rock and the ground keeps the change until a
    // whole cell has been paid for.
    require(i.kind == "chipped the rock", "an iron point dropped on rock did not chip it: " + i.kind);
    require(i.supported, "breaking rock is a regime the engine covers now");
    require(i.work_j > 1.0, "the solver measured no work on the rock");
    require(i.loosened.total() == 0.0, "one blow is not a cell of rock");
    require(i.broken_share > 0.0 && i.broken_share < 0.01,
            "the blow bought a sliver of the cell, and the ground kept it: " +
            std::to_string(i.broken_share));
    std::printf("  one blow on rock: %.3f J measured, %.6f of a cell paid for\n",
                i.work_j, i.broken_share);
}

void aPryBreaksGroundOutAndItIsCarried(bool limited = false) {
    Swing swing = swingAt(0.4, 0.0, "oak");
    LiveWorld &live = *swing.live;
    if (limited) live.setCarryLimitKg(live.carriedObjectsKg()+0.001);
    require(!swing.work.empty() && swing.work.front().open, "the pick is not in the ground to pry with");
    const terrain::Environment &env = *live.environment();
    const terrain::Volumes carried_before = env.carried();
    const terrain::Volumes residual_before = env.terrain().residual();
    LiveStrike lever;
    lever.lever = true;
    lever.shoulder_m = {-0.9, 1.85, kTipZ};
    lever.speed_m_s = 1.2;
    lever.lever_deg = 40.0;
    std::string why;
    require(live.strike(lever, why), "the lever was refused: " + why);
    const std::string levered = finishStroke(live, 960, 30);
    std::printf("  levered (stroke %s): %s\n", levered.c_str(), said(live.groundWork().front()).c_str());
    // And if the lever's own lift did not bring it out, drawn up out of the
    // ground by hand.
    if (live.groundWork().front().open) {
        const Vec3 grip = live.hand().grip_m;
        LiveStroke up;
        up.path_m = {grip, grip + Vec3{0.0, 0.4, 0.0}};
        up.speed_m_s = 0.6;
        up.accel_m_s2 = 4.0;
        up.give_up_s = 3.0;
        require(live.stroke(up, why), "the pull was refused: " + why);
        const std::string pulled = finishStroke(live, 960, 30);
        std::printf("  then drawn up (stroke %s)\n", pulled.c_str());
    }
    const LiveGroundWork w = live.groundWork().front();
    std::printf("  out: %s\n", said(w).c_str());
    require(!w.open, "the point never came out of the ground");
    require(w.kind == "broke out", "the pry broke nothing out");
    require(w.loosened.total() > 0.0 && w.breakout_work_j > 0.0, "the pry loosened nothing, or for nothing");
    const terrain::Volumes carried_after = env.carried();
    const double gained = carried_after.total() - carried_before.total();
    std::printf("  carried %.6f m3 more; the dig took %.6f m3, %.3f kg of %s\n", gained,
                w.loosened.total(), w.loosened_kg, w.ground.c_str());
    near(gained, w.loosened.total(), 1e-12, "what is carried against what the dig took");
    const terrain::Volumes residual = env.terrain().residual();
    near(residual.soil_m3 - residual_before.soil_m3, 0.0, 1e-9, "the ground's soil ledger");
    near(residual.sand_m3 - residual_before.sand_m3, 0.0, 1e-9, "the ground's sand ledger");
    require(w.tool_whole, "the pick did not come through a pry in soil");

    if (limited) {
        require(w.loosened_kg<=0.001+1e-10, "the tool bypassed shared carrying capacity");
        near(env.carriedKg(),0.001,1e-10,"the tool fills only the gram left after its own mass");
        return;
    }

    // 7. The ground opened again from the dig as the report says it -- the edit
    // a room keeps -- once both have come to rest: the same hole, to the bit,
    // and the same carried. Both are the same dig on the same settled ground,
    // relaxed in the same strides, so nothing may differ.
    require(w.dug, "the report does not say where what came loose went out");
    for (int i = 0; i < 2400 && !env.terrain().settled(); ++i) stepOnce(live);
    require(env.terrain().settled(), "the ground did not come to rest after the pry");
    Json edited = ground(0.4, 0.0);
    edited["edits"] = Json::array({Json{{"dig", {{"from_m", {w.dug_from_m[0], w.dug_from_m[1]}},
                                                  {"to_m", {w.dug_to_m[0], w.dug_to_m[1]}},
                                                  {"width_m", w.dug_width_m},
                                                  {"depth_m", w.dug_depth_m}}}}});
    const auto again = open(Json{{"terrain", edited}, {"bodies", pick("oak", 0.4)}});
    const terrain::Environment &reopened = *again->environment();
    const terrain::Volumes kept = env.carried(), made = reopened.carried();
    double worst = 0.0;
    const std::size_t cells = env.terrain().grid().cells();
    for (std::size_t c = 0; c < cells; ++c)
        worst = std::max(worst, std::abs(env.terrain().height(c) - reopened.terrain().height(c)));
    std::printf("  opened again from the dig as an edit (%.3f m wide, %.5f m deep): carried %.9f and "
                "%.9f m3; heights differ by at most %.3g m\n",
                w.dug_width_m, w.dug_depth_m, kept.total(), made.total(), worst);
    require(kept.soil_m3 == made.soil_m3 && kept.sand_m3 == made.sand_m3,
            "the ground opened again from its edits carries a different amount");
    require(worst == 0.0, "the ground opened again from its edits does not have the same hole");
}

// On cube ground a swing that breaks soil loose takes out the whole cube it
// struck (the owner, 2026-10-04): that column a cell lower, its neighbours
// untouched, and the cube carried at its real mass.
void aSwingTakesAWholeCubeOutOfCubeGround(std::optional<Vec3> aim = std::nullopt) {
    Swing swing = swingAt(0.75, 0.0, "oak", true, aim);
    LiveWorld &live = *swing.live;
    const terrain::Environment &env = *live.environment();
    const terrain::TerrainField &field = env.terrain();
    const double q = field.grid().dx;
    std::vector<double> before(field.grid().cells());
    for (std::size_t c = 0; c < before.size(); ++c) before[c] = field.height(c);
    const double carried_before = swing.carried_before_m3;
    // Pried and drawn out, as the pick test above does.
    LiveStrike lever;
    lever.lever = true;
    lever.shoulder_m = {-0.9, 0.75 + 1.85 - 0.4, kTipZ};
    lever.speed_m_s = 1.2;
    lever.lever_deg = 40.0;
    std::string why;
    if (!swing.work.empty() && swing.work.front().open) {
        require(live.strike(lever, why), "the lever was refused: " + why);
        (void)finishStroke(live, 960, 30);
    }
    if (!live.groundWork().empty() && live.groundWork().front().open) {
        const Vec3 grip = live.hand().grip_m;
        LiveStroke up;
        up.path_m = {grip, grip + Vec3{0.0, 0.4, 0.0}};
        up.speed_m_s = 0.6; up.accel_m_s2 = 4.0; up.give_up_s = 3.0;
        require(live.stroke(up, why), "the pull was refused: " + why);
        (void)finishStroke(live, 960, 30);
    }
    require(!live.groundWork().empty(), "the swing met no ground");
    const LiveGroundWork w = live.groundWork().front();
    std::printf("  on cube ground: %s\n", said(w).c_str());
    require(w.kind == "broke out" && w.dug, "the swing broke nothing out");
    std::size_t lowered = 0, struck = 0;
    for (std::size_t c = 0; c < before.size(); ++c)
        if (std::abs(field.height(c) - before[c]) > 1e-9) { ++lowered; struck = c; }
    require(lowered == 1, "one swing lowered " + std::to_string(lowered) + " columns, not one");
    near(before[struck] - field.height(struck), q, 1e-9, "the struck column is a whole cell lower");
    near(w.loosened.total(), q * q * q, 1e-9, "the cube's volume came out");
    near(env.carried().total() - carried_before, q * q * q, 1e-9, "and is carried");
    if (aim) {
        // The cube that came out is the one aimed at, not the one the point met.
        const auto &g = field.grid();
        const int i = static_cast<int>(std::floor((aim->x - g.x0) / q + 0.5));
        const int j = static_cast<int>(std::floor((aim->z - g.z0) / q + 0.5));
        require(struck == g.at(i, j), "the cube that came out is not the one aimed at");
    }
}

// ---- the grip ------------------------------------------------------------------

// The grip is where a hand closes on the tool, so it is on the tool. The room's
// chat once gave a pick's grip with its height and depth swapped, 1.2 m above
// the haft, and it was taken: the hand held a point in the air, and the pick's
// point met no ground.
void aGripOffTheBodyIsRefused() {
    const double top = 0.4;
    Json scene{{"terrain", ground(top, 0.0)}, {"bodies", pick("oak", top)}};
    auto live = open(scene);
    const Vec3 tip{kTipX, top + 0.72, kTipZ};
    const Vec3 on{kGripX, top + 1.02, kTipZ};
    const Vec3 off{kGripX, top + 1.02 + 1.2, kTipZ};
    require(live->toolPoint("pick", tip, {0.0, -1.0, 0.0}, 0.04, 0.04, 30.0, kPointLength, off) == 0,
            "a grip 1.2 m above the haft was taken");
    std::printf("  refused: %s\n", live->toolPointRefusal().c_str());
    require(live->toolPointRefusal().find("the grip is not on the body's matter") != std::string::npos,
            "a grip off the body was refused without saying why: " + live->toolPointRefusal());
    require(live->toolPoint("pick", tip, {0.0, -1.0, 0.0}, 0.04, 0.04, 30.0, kPointLength, on) != 0,
            "the same point with its grip on the haft was refused: " + live->toolPointRefusal());
}

// ---- a broad end, from wherever it is swung ---------------------------------------

// A one-piece oak tool: the pick's handle, and hanging from its +x end a blade a
// cell thick and 0.12 m deep, 0.12 m broad -- across the swing (along z), as a
// hoe's or a mattock's edge is, or along it (along x), as an axe's is and as
// build_recipe once laid a mattock's and a hoe's head, along the haft. Its point
// is the whole of the blade's lower edge, and the engine takes a point's width
// as square to the point and to the handle: across the swing.
Json blade(double lift, bool along) {
    return {box("hoe", "oak", {0.8, 0.04, 0.04}, {0.0, lift + 1.02, 0.02}, "hoe"),
            along ? box("hoe blade", "oak", {0.12, 0.12, 0.04}, {0.34, lift + 0.94, 0.02}, "hoe")
                  : box("hoe blade", "oak", {0.04, 0.12, 0.12}, {0.38, lift + 0.94, 0.02}, "hoe")};
}

// Swung at the ground 0.3 m out from a shoulder `back` behind it. A point comes
// down tilted -- along the way its tip is going, 25-35 degrees off straight down
// -- so an end broad in the swing leads with a corner, up to 3 cm below its tip.
Swing swingBladeFrom(double back, bool along) {
    const double top = 0.4;
    Json scene{{"terrain", ground(top, 0.0)}, {"bodies", blade(top, along)}};
    Swing out;
    out.live = open(scene);
    LiveWorld &live = *out.live;
    const Vec3 tip{along ? 0.34 : kTipX, top + 0.88, kTipZ};
    const Vec3 grip{kGripX, top + 1.02, kTipZ};
    require(live.toolPoint("hoe", tip, {0.0, -1.0, 0.0}, 0.12, 0.01, 20.0, 0.1, grip) != 0,
            "the hoe would not take a point: " + live.toolPointRefusal());
    require(live.wield("hoe", grip), "the hoe could not be taken by its grip");
    out.carried_before_m3 = live.environment()->carried().total();
    LiveStrike strike;
    strike.target_m = {0.3, top, kTipZ};
    strike.shoulder_m = {0.3 - back, top + 1.45, kTipZ};
    strike.speed_m_s = 4.0;
    strike.raise_deg = 110.0;
    std::string why;
    require(live.strike(strike, why), "the swing was refused: " + why);
    out.ended = finishStroke(live, 480, 120);
    out.work = live.groundWork();
    return out;
}

// That corner met the ground as an ordinary contact a step before the tip was
// near enough for the ground to be the point's, and the swing stopped with the
// tip 2-3 cm up: build_recipe's hoe from 6 of 8 stand-backs in the world's
// valley, and in CI's clearing from 1.2 m ("its point met no ground"). Broad
// across its swing or along it, from wherever it is swung, the point goes in.
void aBroadEndMeetsTheGroundFromWhereverItIsSwung() {
    int missed = 0;
    for (const bool along : {false, true}) {
        for (const double back : {1.0, 1.1, 1.2, 1.3, 1.4, 1.6, 1.8, 2.0}) {
            const Swing s = swingBladeFrom(back, along);
            double deepest = 0.0;
            for (const LiveGroundWork &w : s.work) deepest = std::max(deepest, w.depth_m);
            std::printf("  broad %s its swing, from %.1f m: the stroke %s; %s\n", along ? "along" : "across",
                        back, s.ended.c_str(),
                        s.work.empty() ? "its point met no ground" : said(s.work.front()).c_str());
            if (!(deepest > 0.02)) ++missed;
        }
    }
    require(missed == 0, std::to_string(missed) + " of 16 swings did not go into the ground");
}

// The same declared drop, with and without an unrelated exact rigid body.
// This is scene admission, not a new tool or fracture law. Compare the full
// trajectory and the work ledger, including gravity/integration/damping.
void latticeGroundToolsCanShareExactEquipment() {
    const Json exact = {{"name", "equipment"}, {"material", "iron"},
                        {"position_m", {3.0, 0.01, 3.0}},
                        {"parts", {{{"dimensions_m", {0.02, 0.02, 0.02}},
                                    {"center_local_m", {0.0, 0.0, 0.0}}}}}};
    for (const std::string material : {"glass", "oak", "iron"}) {
        Json scene{{"terrain", ground(0.4, 0.0)},
                   {"bodies", {box("stake", material, {0.04, 0.4, 0.04}, {0.02, 0.85, 0.02})}}};
        auto reference = open(scene);
        scene["precise_rigid_bodies"] = Json::array({exact});
        auto mixed = open(scene);
        for (LiveWorld *world : {reference.get(), mixed.get()})
            require(world->toolPoint("stake", {0.02, 0.65, 0.02}, {0.0, -1.0, 0.0},
                                    0.04, 0.04, 30.0, 0.2, {0.02, 1.03, 0.02}) != 0,
                    material + ": lattice point refused: " + world->toolPointRefusal());
        bool refused = false;
        try { (void)mixed->toolPoint("equipment", {3.0, 0.0, 3.0}, {0.0, -1.0, 0.0},
                                   0.04, 0.04, 30.0, 0.2, {3.0, 0.02, 3.0}); }
        catch (const std::invalid_argument &) { refused = true; }
        require(refused, "a tool point on an exact body was admitted");

        // Preserve the actual point, cells and exact compound through both
        // whole restore and changed-scene carry, before a bite is in flight.
        std::string why;
        const std::string saved = mixed->snapshot(why);
        require(!saved.empty(), "mixed scene could not be saved: " + why);
        TileImpactRequest request;
        request.cell_size_m = kCell;
        request.backend = BackendKind::CpuParallel;
        request.bodies = readSceneJson(scene.dump());
        readSceneSettings(scene.dump(), request);
        const auto restored = LiveWorld::open(request, saved);
        require(restored->restored().tier == "whole", "mixed tool did not restore whole");
        const Json before = Json::parse(saved), after = Json::parse(restored->snapshot(why));
        for (const char *key : {"bodies", "tool_points"})
            require(before.contains(key) && before.at(key) == after.at(key),
                    std::string("mixed restore changed ") + key);
        request.bodies.push_back(readSceneJson(Json{{"bodies", {box("new marker", "concrete",
                                        {0.04, 0.04, 0.04}, {4.0, 0.02, 4.0})}}}.dump()).front());
        const auto carried = LiveWorld::open(request, saved, LiveWorld::carryAll(saved));
        require(carried->restored().tier == "carried" && carried->restored().carried.tool_points == 1,
                "unchanged lattice point was not carried into a mixed edited room");
        const Json carry_saved = Json::parse(carried->snapshot(why));
        require(before.at("tool_points") == carry_saved.at("tool_points"), "carry changed a point");
        for (const auto &body : before.at("bodies"))
            if (body.at("name") == "equipment") {
                const auto found = std::find_if(carry_saved.at("bodies").begin(), carry_saved.at("bodies").end(),
                                               [](const auto &b) { return b.at("name") == "equipment"; });
                require(found != carry_saved.at("bodies").end() && *found == body,
                        "carry changed an exact body");
            }
        Json corrupt = before;
        corrupt["tool_points"][0]["body"] = "equipment";
        refused = false;
        try { (void)LiveWorld::open(request, corrupt.dump(), LiveWorld::carryAll(corrupt.dump())); }
        catch (const std::exception &) { refused = true; }
        require(refused, "a saved exact tool point was silently restored or downgraded");

        const double mass = poseOf(*mixed, "stake").mass_kg;
        const auto energy = [&](const LiveBodyPose &pose) {
            return 0.5 * mass * lengthSquared(pose.velocity_m_s) + mass * kG * pose.position_m.y;
        };
        double at_entry = 0.0, kinetic_at_entry = 0.0, max_difference = 0.0;
        int entered = -1, rested = -1;
        for (int i = 0; i < 480; ++i) {
            const LiveBodyPose was = poseOf(*mixed, "stake");
            stepOnce(*reference); stepOnce(*mixed);
            const LiveBodyPose a = poseOf(*reference, "stake"), b = poseOf(*mixed, "stake");
            max_difference = std::max({max_difference, length(a.position_m - b.position_m),
                                      length(a.velocity_m_s - b.velocity_m_s)});
            require(a.mass_kg == b.mass_kg, "mixed scene changed material-derived mass");
            const auto work = mixed->groundWork();
            if (entered < 0 && !work.empty() && work.front().kind == "in the ground") {
                entered = i; at_entry = energy(was);
                kinetic_at_entry = 0.5 * mass * lengthSquared(was.velocity_m_s);
            }
            if (entered >= 0 && rested < 0 && length(b.velocity_m_s) < 0.01) rested = i;
        }
        require(entered >= 0 && rested >= 0, material + ": dropped point did not enter and rest");
        const auto a = reference->groundWork(), b = mixed->groundWork();
        require(a.size() == b.size() && !b.empty(), "mixed scene changed ground events");
        near(max_difference, 0.0, 1e-10, "mixed vs lattice trajectory");
        near(a.front().work_j, b.front().work_j, 1e-10, "mixed vs lattice bite work");
        const auto &work = b.front();
        require(work.depth_m < 0.2, "drop bottomed out beyond the point's modeled length");
        const double lost = at_entry - energy(poseOf(*mixed, "stake"));
        const double correction = mass * kG * kDt * work.closing_speed_m_s / 2.0;
        const double damping_bound = 2.0 * 0.02 * kinetic_at_entry * (rested - entered + 1) * kDt;
        const double residual = work.work_j - lost - correction;
        near(residual, 0.0, damping_bound + 1e-6, "drop energy after integration correction and damping");
        near(mixed->environment()->terrain().residual().total(), 0.0, 1e-10, "ground mass ledger");
        std::printf("  mixed %s, dt %.9f, h %.3f: mass %.6f kg; depth %.6f m; work %.6f J; "
                    "energy residual %.9f J, damping bound %.9f J; trajectory difference %.9g\n",
                    material.c_str(), kDt, kCell, mass, work.depth_m, work.work_j,
                    residual, damping_bound, max_difference);
    }
}

void playersHaveSeparateGroundBudgets() {
    for (const std::string material : {"glass","oak","iron"}) {
        Json scene{{"terrain",ground(.4,0.)},{"bodies",pick(material,.4)}};
        auto live=open(scene);
        live->setCarryLimitKg(80);
        live->selectHand("alice");
        require(live->wield("pick",{kGripX,1.42,kTipZ}),"Alice could not hold tool");
        const double tool=live->carriedObjectsKg();
        near(tool,poseOf(*live,"pick").mass_kg,1e-9,"native tool mass");
        std::string why;
        require(live->park("pick",why),"Alice could not stow tool: "+why);
        near(live->carriedObjectsKg(),tool,1e-9,"Alice parked mass");
        const auto alice=live->dig(-1,0,-1,0,.8,.4);
        near(alice.edit.mass_kg+tool,80,1e-5,"Alice capacity includes her bag");
        const auto alice_volume=live->environment()->carried();
        live->selectHand("bob");
        near(live->carriedObjectsKg(),0,0,"Bob does not carry Alice's bag");
        near(live->environment()->carriedKg(),0,0,"Bob starts empty");
        const auto bob=live->dig(1,0,1,0,.8,.4);
        near(bob.edit.mass_kg,80,1e-5,"Bob has his own capacity");
        const auto bob_volume=live->environment()->carried();
        live->selectHand("");
        near(live->environment()->carriedKg(),0,0,"clock does not own either load");
        auto accounts=Json::parse(live->playerCarriedGround());
        near(accounts["alice"]["total_kg"].get<double>(),80,1e-5,"Alice report");
        near(accounts["bob"]["total_kg"].get<double>(),80,1e-5,"Bob report");
        const std::string saved=live->snapshot(why);
        require(!saved.empty(),"private loads did not save: "+why);
        TileImpactRequest request;request.cell_size_m=kCell;request.backend=BackendKind::CpuParallel;
        request.bodies=readSceneJson(scene.dump());readSceneSettings(scene.dump(),request);
        Json forged=Json::parse(saved);
        forged["ground"]["carriers"]["clone"]=forged["ground"]["carriers"]["alice"];
        bool refused=false;
        try { (void)LiveWorld::open(request,forged.dump()); }
        catch (const std::exception &) { refused=true; }
        require(refused,"cloned private ground exceeded excavation without refusal");
        auto restored=LiveWorld::open(request,saved);
        require(restored->restored().tier=="whole","private loads did not restore whole");
        near(restored->environment()->carriedTotal().total(),alice_volume.total()+bob_volume.total(),1e-12,"restored total");
        restored->selectHand("bob");
        const std::string protected_bag=restored->snapshot(why);
        require(!restored->unpark("pick",{1,1,0},{},why),"Bob took Alice's bag item");
        require(why=="it is in another player's bag","bag refusal does not explain ownership");
        require(restored->snapshot(why)==protected_bag,"bag refusal changed saved state");
        restored->selectHand("alice");
        near(restored->carriedObjectsKg(),tool,1e-9,"parked owner restored");
        near(restored->environment()->carried().total(),alice_volume.total(),1e-12,"Alice restored stock");
        (void)restored->deposit(-1,1,.8,alice_volume.sand_m3,alice_volume.soil_m3);
        near(restored->environment()->carriedKg(),0,1e-9,"Alice heaps only her own stock");
        restored->selectHand("bob");
        near(restored->environment()->carried().total(),bob_volume.total(),1e-12,"Alice heap preserves Bob");
        near(restored->environment()->terrain().residual().total(),0,1e-10,"shared terrain mass ledger");
        std::printf("  private %s h %.3f dt %.9f: tool %.6f kg; Alice %.6f kg, Bob %.6f kg; terrain residual %.12g m3\n",
            material.c_str(),kCell,kDt,tool,alice.edit.mass_kg,bob.edit.mass_kg,
            restored->environment()->terrain().residual().total());
    }
}

void toolMeetingKeepsItsOwner() {
    const double top=.4;
    Json scene{{"terrain",ground(top,0.)},{"bodies",pick("oak",top)}};
    auto live=open(scene);live->selectHand("alice");live->setCarryLimitKg(80);
    const Vec3 grip{kGripX,top+1.02,kTipZ};
    require(live->toolPoint("pick",{kTipX,top+.72,kTipZ},{0,-1,0},.04,.04,30,kPointLength,grip)!=0,"declare owned point");
    require(live->wield("pick",grip),"wield owned point");
    const auto finish=[&](int most,int settle) {
        for (int i=0;i<most;++i) {
            live->selectHand("bob");stepOnce(*live);live->selectHand("alice");
            if (!live->hand().stroking) break;
        }
        live->moveHeld(live->hand().grip_m);
        for (int i=0;i<settle;++i) { live->selectHand("");stepOnce(*live); }
        live->selectHand("alice");
    };
    LiveStrike strike;strike.target_m={.3,top,kTipZ};strike.shoulder_m={-.9,top+1.45,kTipZ};
    strike.speed_m_s=4;strike.raise_deg=110;std::string why;
    require(live->strike(strike,why),"owned strike: "+why);finish(480,120);
    require(!live->groundWork().empty() && live->groundWork().front().open,"owned stroke did not enter soil");
    LiveStrike lever;lever.lever=true;lever.shoulder_m=strike.shoulder_m;lever.speed_m_s=1.2;lever.lever_deg=40;
    require(live->strike(lever,why),"owned lever: "+why);finish(960,30);
    if (live->groundWork().front().open) {
        LiveStroke up;const Vec3 at=live->hand().grip_m;up.path_m={at,at+Vec3{0,.4,0}};
        up.speed_m_s=.6;up.accel_m_s2=4;up.give_up_s=3;
        require(live->stroke(up,why),"owned pull: "+why);finish(960,30);
    }
    const auto work=live->groundWork().front();
    require(!work.open && work.loosened_kg>0 && work.actor=="alice","completed bite lost its owner");
    near(live->environment()->carried().total(),work.loosened.total(),1e-12,"Alice receives measured loosened ground");
    live->selectHand("bob");near(live->environment()->carriedKg(),0,0,"stepping player receives none");
    live->selectHand("");near(live->environment()->carriedKg(),0,0,"clock receives none");
    std::printf("  owned native stroke: %s; owner %s; terrain residual %.12g m3\n",said(work).c_str(),work.actor.c_str(),live->environment()->terrain().residual().total());
}

// The cube action is the game's fixed-work abstraction, not a calibrated wet
// soil constitutive law. Test its real held-tool path and the water bed it edits.
void cubeStrikesOpenAWetChannel() {
    constexpr int nx = 20, nz = 20, first = 8, row = 10, length = 5;
    constexpr double q = .25, top = .75, waterVolume = .1 * q * q;
    for (const std::string material : {"glass", "oak", "iron"}) {
        Json scene{{"terrain", cubeGround(top, 0)}, {"bodies", pick(material, top)}};
        auto dry = open(scene);
        Json saved = Json::parse(dry->environmentState());
        std::vector<double> depths(nx * nz, 0);
        depths[row * nx + first] = .1;
        saved["depth_b64"] = terrain::encodeBase64(depths.data(), depths.size() * sizeof(double));
        saved["ledger"]["initial_m3"] = waterVolume;
        scene["water"] = {{"state", saved}};
        auto live = open(scene);
        live->selectHand("alice");
        const Vec3 grip{kGripX, top + 1.02, kTipZ};
        require(live->toolPoint("pick", {kTipX, top + .72, kTipZ}, {0,-1,0}, .04,.04,30,kPointLength,grip) != 0,
                "declare channel pick point");
        require(live->wield("pick", grip), "wield channel pick");
        const auto &field = live->environment()->terrain();
        const auto &g = field.grid();
        near(live->environment()->water()->depth(g.at(first,row)), .1, 1e-12, "initial wet target");
        double kg = 0;
        for (int i = first; i < first + length; ++i) {
            const auto receipt = live->strikeCell({g.xOf(i),top,g.zOf(row)});
            require(receipt.dug && !receipt.open && receipt.actor == "alice", "owned closed channel receipt");
            near(receipt.loosened.total(), q*q*q, 1e-12, "one targeted cube removed");
            near(field.height(g.at(i,row)), top-q, 1e-12, "channel floor matches edit");
            near(field.height(g.at(i,row+1)), top, 1e-12, "neighboring bank unchanged");
            kg += receipt.loosened_kg;
        }
        near(live->environment()->carried().total(), length*q*q*q, 1e-12, "Alice receives all channel material");
        near(live->environment()->carriedKg(), kg, 1e-9, "carried mass matches receipts");
        live->selectHand("bob");
        near(live->environment()->carriedKg(), 0, 0, "Bob receives none of Alice's excavation");
        for (int i = 0; i < 480; ++i) stepOnce(*live);
        const auto &water = *live->environment()->water();
        near(water.volume(), waterVolume, 1e-10, "channel conserves water volume");
        near(water.residual(), 0, 1e-10, "channel water ledger closes");
        near(field.residual().total(), 0, 1e-10, "channel ground ledger closes");
        require(water.depth(g.at(first+length-1,row)) > .005, "water reaches the end of the dug channel");
        near(water.depth(g.at(first+length-1,row+1)), 0, 1e-12, "uncut bank stays dry");
        std::printf("  %s cube channel: dt %.9g s, cell %.2f m; %.6g kg removed; water %.12g m3, residual %.12g; ground residual %.12g m3\n",
                    material.c_str(), kDt, q, kg, water.volume(), water.residual(), field.residual().total());
    }
}

void cubeStrikesRemoveTheClickedRockWallCell() {
    constexpr double q=.25;
    for (const std::string material : {"glass", "oak", "iron"}) for(const std::string ground : {"soil","sand","rock"}) {
        const bool soft=ground!="rock";
        const double top=soft ? .75 : 0, y=soft ? .375 : -.375;
        const auto expected=ground=="soil" ? terrain::RunKind::Soil : ground=="sand" ? terrain::RunKind::Sand : terrain::RunKind::Rock;
        const int strikes=soft ? 1 : 10;
        auto live=open(Json{{"terrain",cubeGround(ground=="soil" ? top : 0,ground=="sand" ? top : 0)},{"bodies",pick(material,top)}});
        live->selectHand("alice");
        const Vec3 grip{kGripX,top+1.02,kTipZ};
        require(live->toolPoint("pick",{kTipX,top+.72,kTipZ},{0,-1,0},.04,.04,30,kPointLength,grip)!=0,"wall point");
        require(live->wield("pick",grip),"wall pick held");
        const auto &field=live->environment()->terrain();const auto &g=field.grid();
        const auto c=g.at(10,10),neighbor=g.at(11,10);
        double kg=0;
        for(int n=1;n<=strikes;n++) {
            const auto receipt=live->strikeCell({g.xOf(10),y,g.zOf(10)});
            require(receipt.actor=="alice" && !receipt.open,"private closed wall receipt");
            if(n<strikes) {
                near(receipt.loosened.total(),0,0,"no early wall loot");
                near(receipt.broken_share,n/10.0,1e-10,"each wall strike advances progress");
                require(field.kindAt(c,y)==expected,"wall stays solid until paid");
            } else {
                near(receipt.loosened.total(),q*q*q,1e-12,"one full clicked material cube");
                kg=receipt.loosened_kg;
            }
            near(field.height(c),top,1e-12,"wall strike retains roof above it");
            require(field.kindAt(neighbor,y)==expected,"adjacent wall cube retained");
        }
        require(field.kindAt(c,y)==terrain::RunKind::Void,"clicked vertical band becomes a void");
        require(field.kindAt(c,y-q)==expected,"floor below clicked band retained");
        near(live->environment()->carriedKg(),kg,1e-10,"wall mass credited once to owner");
        near(field.residual().total(),0,1e-10,"wall volume ledger closes");
        terrain::TerrainField restored=field;
        restored.restore(field.state());
        require(restored.kindAt(c,y)==terrain::RunKind::Void,"expanded saved beds retain the clicked hole");
        near(restored.residual().total(),0,1e-10,"expanded bed save retains material ledger");
        std::printf("  %s %s wall: cell %.2f m, %d immediate strikes, %.6g kg removed; volume residual %.12g m3\n",material.c_str(),ground.c_str(),q,strikes,kg,field.residual().total());
        live->selectHand("bob");near(live->environment()->carriedKg(),0,0,"peer receives no wall loot");
    }
}

} // namespace

int main() {
    const std::vector<std::pair<const char *, std::function<void()>>> checks = {
        {"held cube tools remove the clicked wall band and retain its roof",cubeStrikesRemoveTheClickedRockWallCell},
        {"held cube tools open a wet channel without creating water", cubeStrikesOpenAWetChannel},
        {"the model is the closed forms", theModelIsTheClosedForms},
        {"a stake dropped into soil, and drawn out", aStakeDroppedIntoSoilAndDrawnOut},
        {"the same swing is the same meeting", theSameSwingIsTheSameMeeting},
        {"soil against rock", soilAgainstRock},
        {"a pry breaks ground out, and it is carried", [] { aPryBreaksGroundOutAndItIsCarried(); }},
        {"a held tool shares the excavation budget", [] { aPryBreaksGroundOutAndItIsCarried(true); }},
        {"a swing takes a whole cube out of cube ground", [] { aSwingTakesAWholeCubeOutOfCubeGround(); }},
        {"a swing takes out the cube aimed at", [] { aSwingTakesAWholeCubeOutOfCubeGround(Vec3{0.3 + 0.25, 0.75, kTipZ}); }},
        {"a grip off the body is refused", aGripOffTheBodyIsRefused},
        {"a broad end meets the ground from wherever it is swung", aBroadEndMeetsTheGroundFromWhereverItIsSwung},
        {"lattice ground tools share exact equipment", latticeGroundToolsCanShareExactEquipment},
        {"players have separate ground and bag budgets",playersHaveSeparateGroundBudgets},
        {"tool meetings keep their owner during shared stepping",toolMeetingKeepsItsOwner},
        {"a separate head needs an actual fixed handle",aSeparateHeadNeedsAnActualFixedHandle},
        {"ground rays ignore only the actor's whole fixed tool",groundRaysIgnoreOnlyTheActorsWholeFixedTool},
        {"fixed mixed tools retain materials mass and owned work",fixedMixedToolsRetainMaterialsMassAndOwnedWork},
        {"a detached head cannot be used through its old handle",aDetachedHeadCannotBeUsedThroughItsOldHandle},
        {"fixed horizontal tools lift without a second seam response",fixedHorizontalToolsLiftWithoutASecondSeamResponse},
        {"fixed tools keep private bag ownership and carry",fixedToolsKeepPrivateBagOwnershipAndCarry},
    };
    int failed = 0;
    for (const auto &[name, check] : checks) {
        std::cout << name << "\n";
        try {
            check();
            std::cout << "  ok\n";
        } catch (const std::exception &error) {
            ++failed;
            std::cout << "  FAILED: " << error.what() << "\n";
        }
    }
    std::cout << (failed == 0 ? "all ground work checks passed\n" : "ground work checks FAILED\n");
    return failed == 0 ? 0 : 1;
}
