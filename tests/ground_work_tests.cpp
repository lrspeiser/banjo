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
    require(judgeGround(true, 0.0, 1.5e9, "iron").answer == GroundAnswer::NotSupported,
            "an iron point on rock was not 'not supported'");
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

struct Swing {
    std::unique_ptr<LiveWorld> live;
    std::vector<LiveGroundWork> work;
    std::string ended;
    double carried_before_m3{};
};

// Open a world with the pick in the air above the ground, take it by its grip
// and swing it at the ground 0.3 m out, from a shoulder behind it.
Swing swingAt(double soil, double sand, const std::string &material) {
    const double top = soil + sand;
    Json scene{{"terrain", ground(soil, sand)}, {"bodies", pick(material, top)}};
    Swing out;
    out.live = open(scene);
    LiveWorld &live = *out.live;
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
    require(i.kind == "not supported" && !i.supported, "an iron point on rock was not 'not supported'");
    require(i.why.find("not supported yet") != std::string::npos, "the answer does not say 'not supported yet'");
    require(i.loosened.total() == 0.0, "an unsupported regime loosened something");
}

void aPryBreaksGroundOutAndItIsCarried() {
    Swing swing = swingAt(0.4, 0.0, "oak");
    LiveWorld &live = *swing.live;
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

} // namespace

int main() {
    const std::vector<std::pair<const char *, std::function<void()>>> checks = {
        {"the model is the closed forms", theModelIsTheClosedForms},
        {"a stake dropped into soil, and drawn out", aStakeDroppedIntoSoilAndDrawnOut},
        {"the same swing is the same meeting", theSameSwingIsTheSameMeeting},
        {"soil against rock", soilAgainstRock},
        {"a pry breaks ground out, and it is carried", aPryBreaksGroundOutAndItIsCarried},
        {"a grip off the body is refused", aGripOffTheBodyIsRefused},
        {"a broad end meets the ground from wherever it is swung", aBroadEndMeetsTheGroundFromWhereverItIsSwung},
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
