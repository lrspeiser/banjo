// Heat, composition and burning changing what things can carry: the owner's
// acceptance for docs/thermal-mechanics.md, in a live world.
//
// The assembly is the owner's: a wooden support heats and chars, its remaining
// load-bearing section becomes insufficient, its attachment fails, and what it
// held falls through the mechanical system that was already there. Here that
// is an oak peg in an oak gatepost with an iron gate hanging on it. Nothing in
// this file sets a time, a temperature or a strength at which anything fails:
// the heater is a declared power, the law is the material's, and the load is
// whatever the solver measures in the fixing.
#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "thermo/ThermalMechanics.hpp"
#include "thermo/ThermoWorld.hpp"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <memory>
#include <optional>
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

bool near(double a, double b, double tolerance) { return std::abs(a - b) <= tolerance; }

std::unique_ptr<LiveWorld> openScene(const std::string &scene, double cell_m) {
    TileImpactRequest request;
    request.cell_size_m = cell_m;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(scene);
    readSceneSettings(scene, request);
    return LiveWorld::open(request);
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

std::string scene(const std::string &bodies) {
    return std::string(R"({"plasticity":true,"bodies":[)") + bodies + "]}";
}

// Step, answering a break the only way this file ever needs to: by running
// it. The assemblies here are never struck; the refused-step test strikes a
// pane on purpose.
void stepOnce(LiveWorld &world) {
    for (int tries = 0; tries < 8; ++tries) {
        world.step(kDt);
        if (!world.steppedBack()) return;
        for (const std::string &name : world.breakable()) (void)world.fracture(name);
    }
}

void stepFor(LiveWorld &world, double seconds) {
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    for (int done = 0; done < steps; ++done) stepOnce(world);
}

LiveBodyPose poseOf(const LiveWorld &world, const std::string &name) {
    for (const LiveBodyPose &pose : world.poses())
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

LiveJoint jointOf(const LiveWorld &world, unsigned id) {
    for (const LiveJoint &joint : world.joints())
        if (joint.id == id) return joint;
    throw std::runtime_error("no joint " + std::to_string(id));
}

thermo::MatterState matterOf(const LiveWorld &world, const std::string &name) {
    require(world.thermo() != nullptr, "the world has a thermal network");
    const std::optional<thermo::MatterState> held = world.thermo()->matter(name);
    require(held.has_value(), "the thermal network holds " + name);
    return *held;
}

// ---- the assembly -----------------------------------------------------------
//
// An anchored oak gatepost 1.6 m tall; an oak peg 40 x 40 mm, 160 mm long,
// standing out of its face along +z; an iron gate 320 x 320 mm hanging on the
// peg's outer half, welded to it. The peg is fixed into the post by a fixing
// MADE OF THE PEG: its declared strength is what the peg carries cold, and
// from there on it is what the peg's law leaves of it.
//
// Jointed bodies stand 5 mm clear of each other, as the room's own builds do:
// the solver still makes contacts between two bodies a joint holds together,
// and a gate pressed into its own peg fights the weld that holds it there.
constexpr Vec3 kPegSize{0.04, 0.04, 0.16};
constexpr double kPegY = 1.40;
constexpr double kClear = 0.005;
constexpr double kPegZ = 0.08 + kClear + 0.08;           // its inner end 5 mm off the post
constexpr double kGateTop = kPegY - 0.02 - kClear;       // 5 mm under the peg
constexpr double kGateZ = 0.205;

// A scene starts with every load suddenly applied -- gravity on, nothing yet
// carrying anything -- and a suddenly applied load reaches up to twice its
// weight while the joint takes it up. So every gate here is held by a peg
// rated at least twice what it weighs, as a real one would be; the heated peg
// then fails on its law, not on the start.
std::string assembly(const std::string &tag, double x, double gate_thickness_m,
                     const std::string &peg_material = "oak", double gate_height_m = 0.32) {
    std::string out = box(tag + " post", "oak", {0.16, 1.6, 0.16}, {x, 0.8, 0.0}, true) + "," +
                      box(tag + " peg", peg_material, kPegSize, {x, kPegY, kPegZ}, false);
    if (gate_thickness_m > 0.0)
        out += "," + box(tag + " gate", "iron", {0.32, gate_height_m, gate_thickness_m},
                         {x, kGateTop - 0.5 * gate_height_m, kGateZ}, false);
    return out;
}

unsigned hang(LiveWorld &world, const std::string &tag, double x, double holds_shear_n,
              bool with_gate) {
    const unsigned peg = world.fix(tag + " post", tag + " peg", {x, kPegY, 0.08}, {0.0, 0.0, 1.0},
                                   0.0, holds_shear_n);
    require(peg > 0, "the peg is fixed into its post");
    require(world.setJointMember(peg, tag + " peg"), "the fixing is made of the peg");
    if (with_gate)
        require(world.fix(tag + " peg", tag + " gate", {x, kGateTop, kGateZ}, {0.0, 1.0, 0.0}, 0.0, 0.0) > 0,
                "the gate is welded to the peg");
    return peg;
}

double gateWeightN(double thickness_m, double height_m = 0.32) {
    return 7870.0 * 0.32 * height_m * thickness_m * kGravity;
}

// What the law says the peg's fixing can take now, worked out here from the
// network's own state -- independently of the joint that reports it.
double lawShearFraction(const LiveWorld &world, const std::string &peg) {
    const thermo::MechanicalLaw *law = thermo::lawFor(poseOf(world, peg).material);
    require(law != nullptr, "the peg's material has a law");
    return thermo::evaluateSection(*law, matterOf(world, peg), kPegSize, 2).shear;
}

struct Failure {
    bool parted{};
    double at_s{};
    double load_n{};         // measured in the step before it parted
    double holds_n{};        // what it could still take then
    double rated_n{};
    unsigned rechecks{};
    std::string why;
    thermo::MatterState peg;
};

// Step until the fixing parts or `limit_s` runs out, checking every step that
// it parts exactly when the model says it should. A step measures the load in
// the fixing and tests it against what the fixing could take as that step
// began -- what the last one's heat left it. So: every step it holds, the load
// it carried was inside that; the step it parts, the load was past it; and
// both numbers are the ones it says it parted at.
Failure heatUntilParted(LiveWorld &world, unsigned joint, const std::string &peg, double limit_s,
                        const std::function<void()> &every_step = {}) {
    Failure out;
    double holds_before = jointOf(world, joint).holds_shear_n;
    const int steps = static_cast<int>(std::lround(limit_s / kDt));
    for (int i = 0; i < steps; ++i) {
        stepOnce(world);
        if (every_step) every_step();
        const LiveJoint now = jointOf(world, joint);
        if (!now.attached) {
            out.parted = true;
            out.at_s = world.time_s();
            out.load_n = now.parted_load_n;
            out.holds_n = now.parted_capacity_n;
            out.rated_n = now.rated_shear_n;
            out.rechecks = now.rechecks;
            out.why = now.parted_because;
            out.peg = matterOf(world, peg);
            require(near(now.parted_capacity_n, holds_before, 1e-9 * (1.0 + holds_before)),
                    "it parted against what it could take as the step began");
            require(now.parted_load_n > now.parted_capacity_n,
                    "and only because the load passed it: " + now.parted_because);
            return out;
        }
        require(now.shear_n_now <= holds_before + 1e-9,
                "the load passed what it could take, and it held");
        holds_before = now.holds_shear_n;
    }
    const LiveJoint now = jointOf(world, joint);
    out.load_n = now.shear_n_now;
    out.holds_n = now.holds_shear_n;
    out.rated_n = now.rated_shear_n;
    out.rechecks = now.rechecks;
    return out;
}

// ---------------------------------------------------------------------------

// The curves are the sources' own numbers, and the section is three rings.
void theLawsAreTheirSourcesNumbers() {
    const thermo::MechanicalLaw *oak = thermo::lawFor("oak");
    const thermo::MechanicalLaw *iron = thermo::lawFor("iron");
    const thermo::MechanicalLaw *concrete = thermo::lawFor("concrete");
    require(oak && iron && concrete, "oak, iron and concrete have laws");
    require(thermo::lawFor("glass") == nullptr && thermo::lawFor("aluminum") == nullptr,
            "glass and aluminium have none, and are not changed by heat");
    const double c100 = 373.15, c200 = 473.15, c300 = 573.15;
    // EN 1995-1-2 Annex B, Figures B.2 and B.3 (softwood).
    require(near(oak->tension.at(c100), 0.65, 1e-12) && near(oak->compression.at(c100), 0.25, 1e-12) &&
                near(oak->shear.at(c100), 0.40, 1e-12) && near(oak->stiffness.at(c100), 0.50, 1e-12),
            "oak at 100 degC: tension 0.65, compression 0.25, shear 0.40, stiffness 0.50");
    require(near(oak->shear.at(c200), 0.20, 1e-12) && oak->tension.at(c300) == 0.0,
            "oak's curves run straight to nothing at 300 degC");
    require(oak->tension.at(293.15) == 1.0 && oak->tension.at(250.0) == 1.0, "and are 1 at and below 20 degC");
    // EN 1993-1-2 Table 3.1.
    require(iron->tension.at(673.15) == 1.0 && near(iron->tension.at(773.15), 0.78, 1e-12) &&
                near(iron->tension.at(873.15), 0.47, 1e-12) && near(iron->stiffness.at(c200), 0.9, 1e-12),
            "iron: yield 1.0 to 400 degC, 0.78 at 500, 0.47 at 600; stiffness 0.9 at 200");
    // EN 1992-1-2 Table 3.1 and 3.2.2.2.
    require(near(concrete->compression.at(673.15), 0.75, 1e-12) && concrete->tension.at(c100) == 1.0 &&
                near(concrete->tension.at(623.15), 0.5, 1e-12) && !concrete->recovers,
            "concrete: compression 0.75 at 400 degC, tension 0.5 at 350, and it does not recover");

    // Three rings: a 40 x 40 mm oak section with a 3 mm layer at 100 degC over
    // a cold core carries (0.65 x ring + 1 x core) / whole in tension.
    thermo::MatterState m;
    m.material = "oak";
    m.layered = true;
    m.layer_depth_m = 0.003;
    m.surface_k = m.peak_surface_k = c100;
    const Vec3 peg{0.04, 0.04, 0.16};
    const thermo::SectionState warm = thermo::evaluateSection(*oak, m, peg, 2);
    const double ring = 0.04 * 0.04 - 0.034 * 0.034, core = 0.034 * 0.034, whole = 0.04 * 0.04;
    require(near(warm.tension, (0.65 * ring + core) / whole, 1e-12), "the rings share the load by area");
    require(warm.tension_if_cooled == 1.0, "wood warmed to 100 degC gets its strength back when it cools");
    // Past the char point the layer is char, cooled or not.
    m.surface_k = 400.0;
    m.peak_surface_k = 600.0;
    const thermo::SectionState charred = thermo::evaluateSection(*oak, m, peg, 2);
    require(near(charred.tension_if_cooled, core / whole, 1e-12) && near(charred.char_m, 0.003, 1e-12),
            "a layer that has been past 300 degC is char for good: only the core carries");
    // What burns goes from every face: 27.1% of a 100 mm cube is 5 mm in.
    require(near(thermo::recessionDepthM({0.1, 0.1, 0.1}, 0.271), 0.005, 1e-9), "burning recedes from every face");
    // Composition: half the load-bearing matter carries half.
    thermo::MatterState thin;
    thin.material = "oak";
    thin.composition_factor = 0.5;
    require(near(thermo::evaluateSection(*oak, thin, peg, 2).shear, 0.5, 1e-12),
            "a body declared with half oak's dry wood carries half");
    // Iron cooled from past 600 degC is outside what is modelled, and says so.
    thermo::MatterState hot_iron;
    hot_iron.material = "iron";
    hot_iron.surface_k = 400.0;
    hot_iron.peak_surface_k = 950.0;
    const thermo::SectionState past = thermo::evaluateSection(*iron, hot_iron, peg, 2);
    require(!past.supported && past.outside.find("cooling") != std::string::npos,
            "iron cooling from 950 K is flagged as outside the supported range");
}

// The cold control: the same assembly, nothing heating it, carries its gate at
// rest -- no motion, no failure, and the load the solver measures is the
// weight it holds.
void aColdAssemblyHoldsItsLoad() {
    auto world = openScene(scene(assembly("cold", 0.0, 0.04)), 0.04);
    const unsigned peg = hang(*world, "cold", 0.0, 800.0, true);
    const Vec3 built = poseOf(*world, "cold gate").position_m;
    // The first moments: the joints take up the gate's weight.
    double peak = 0.0;
    for (int i = 0; i < static_cast<int>(3.0 / kDt); ++i) {
        stepOnce(*world);
        peak = std::max(peak, jointOf(*world, peg).shear_n_now);
    }
    const Vec3 gate0 = poseOf(*world, "cold gate").position_m;
    stepFor(*world, 20.0);
    const LiveJoint held = jointOf(*world, peg);
    const Vec3 moved = poseOf(*world, "cold gate").position_m - gate0;
    const double expected = gateWeightN(0.04) + 700.0 * 0.04 * 0.04 * 0.16 * kGravity;
    std::cout << "    taking up the load: the gate settled " << length(gate0 - built) * 1000.0
              << " mm and the fixing peaked at " << peak << " N (" << peak / expected
              << " of the weight); over the next 20 s the gate moved " << length(moved) * 1000.0
              << " mm; the fixing carries " << held.shear_n_now << " N across it (gate and peg weigh "
              << expected << " N) and holds " << held.holds_shear_n << " of " << held.rated_shear_n
              << " N; " << held.rechecks << " re-checks" << std::endl;
    require(held.attached, "the cold peg holds");
    require(length(gate0 - built) < 0.002, "taking up its load settles the gate by under 2 mm");
    require(length(moved) < 1.0e-4, "and from then on nothing moves");
    require(near(held.shear_n_now, expected, 0.03 * expected), "the load it carries is what hangs on it");
    require(held.capacity_fraction == 1.0 && held.holds_shear_n == 800.0 && held.rechecks == 0,
            "and nothing changed what it can take");
    require(held.member == "cold peg", "it says what it is made of");
}

// Heat one of two identical assemblies. The heated peg's fixing follows its
// law step by step, it parts exactly when the measured load passes what is
// left, and the gate falls; the cold twin beside it is untouched.
void theHeatedTwinWeakensByItsLawAndFails() {
    auto world = openScene(scene(assembly("heated", 0.0, 0.04) + "," + assembly("control", 3.0, 0.04)), 0.04);
    const unsigned heated = hang(*world, "heated", 0.0, 800.0, true);
    const unsigned control = hang(*world, "control", 3.0, 800.0, true);
    stepFor(*world, 3.0);
    const Vec3 control_gate0 = poseOf(*world, "control gate").position_m;
    (void)world->heat("heated peg", 2000.0, 300.0);
    const auto started = std::chrono::steady_clock::now();
    const double t0 = world->time_s();
    double worst = 0.0;
    int compared = 0;
    const Failure f = heatUntilParted(*world, heated, "heated peg", 300.0, [&]() {
        const LiveJoint j = jointOf(*world, heated);
        if (!j.attached) return;
        // What the joint holds is the law's answer for the peg as it is now.
        const double law = lawShearFraction(*world, "heated peg");
        worst = std::max(worst, std::abs(j.holds_shear_n - 800.0 * law));
        ++compared;
    });
    const double wall_s = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    require(f.parted, "the heated peg gave way within 300 s of 2 kW");
    std::cout << "    heated at 2 kW: gave way " << f.at_s - t0 << " s in, carrying " << f.load_n
              << " N against " << f.holds_n << " N left of " << f.rated_n << " N; peg surface "
              << f.peg.surface_k << " K (hottest " << f.peg.peak_surface_k << " K), core " << f.peg.core_k
              << " K, " << 100.0 * f.peg.consumed_fraction << "% of its dry wood burned; " << f.rechecks
              << " re-checks; law vs joint worst " << worst << " N over " << compared << " steps\n"
              << "    why: " << f.why << "\n    " << (f.at_s - t0) / wall_s << "x faster than realtime"
              << std::endl;
    require(worst < 1e-6, "every step the fixing held exactly what the peg's law leaves it");
    require(f.why.find("sheared") != std::string::npos && f.why.find("heated peg") != std::string::npos,
            "and it says why, with the peg's state");
    stepFor(*world, 3.0);
    require(poseOf(*world, "heated gate").position_m.y < 0.5, "the gate fell to the ground");
    // The twin stands 3 m from a fire at 1060 K and sees a little of it, so it
    // warms by a fraction of a kelvin -- and oak's curve takes a fraction of a
    // percent for that. That is the law, not a leak: it is held to within 1%.
    const LiveJoint twin = jointOf(*world, control);
    const double twin_k = world->thermo()->holds("control peg") ? matterOf(*world, "control peg").surface_k
                                                                : thermo::kReferenceTemperatureK;
    std::cout << "    the cold twin: " << twin_k << " K, holds " << twin.holds_shear_n << " of "
              << twin.rated_shear_n << " N, its gate moved "
              << length(poseOf(*world, "control gate").position_m - control_gate0) * 1000.0 << " mm"
              << std::endl;
    require(twin.attached && twin.capacity_fraction > 0.99, "the cold twin still holds, all but untouched");
    require(length(poseOf(*world, "control gate").position_m - control_gate0) < 0.001,
            "and its gate has not moved");
    require(wall_s < 1.1 * (world->time_s() - t0), "inside the realtime rule");
}

// A different load changes the answer: a gate twice as heavy gives way
// sooner, and a peg with nothing on it -- heated the same -- holds.
void aDifferentLoadChangesTheAnswer() {
    auto world = openScene(scene(assembly("light", 0.0, 0.04, "oak", 0.16) + "," +
                                 assembly("heavy", 3.0, 0.04, "oak", 0.32) + "," + assembly("bare", 6.0, 0.0)),
                           0.04);
    const unsigned light = hang(*world, "light", 0.0, 800.0, true);
    const unsigned heavy = hang(*world, "heavy", 3.0, 800.0, true);
    const unsigned bare = hang(*world, "bare", 6.0, 800.0, false);
    stepFor(*world, 3.0);
    require(jointOf(*world, heavy).attached && jointOf(*world, light).attached,
            "cold, both loaded pegs hold their gates (the premise)");
    const double t0 = world->time_s();
    for (const char *peg : {"light peg", "heavy peg", "bare peg"}) (void)world->heat(peg, 2000.0, 300.0);
    double t_light = -1.0, t_heavy = -1.0;
    double bare_at_light_k = 0.0, light_at_light_k = 0.0, bare_holds = 0.0;
    for (int i = 0; i < static_cast<int>(300.0 / kDt) && (t_light < 0.0 || t_heavy < 0.0); ++i) {
        stepOnce(*world);
        if (t_heavy < 0.0 && !jointOf(*world, heavy).attached) t_heavy = world->time_s() - t0;
        if (t_light < 0.0 && !jointOf(*world, light).attached) {
            t_light = world->time_s() - t0;
            bare_at_light_k = matterOf(*world, "bare peg").surface_k;
            light_at_light_k = matterOf(*world, "light peg").surface_k;
            bare_holds = jointOf(*world, bare).holds_shear_n;
            require(jointOf(*world, bare).attached, "the bare peg holds when the loaded one gives way");
        }
    }
    std::cout << "    2 kW each: the " << gateWeightN(0.04) << " N gate fell at " << t_heavy << " s, the "
              << gateWeightN(0.04, 0.16) << " N gate at " << t_light << " s; the bare peg, at "
              << bare_at_light_k << " K against the loaded one's " << light_at_light_k
              << " K, still holds " << bare_holds << " N for its own " << 700.0 * 0.04 * 0.04 * 0.16 * kGravity
              << " N" << std::endl;
    require(t_heavy > 0.0 && t_light > 0.0, "both loaded pegs gave way");
    require(t_heavy < t_light, "the heavier load gave way sooner");
    require(bare_at_light_k >= light_at_light_k - 5.0,
            "the bare peg was at least as hot -- it reached the same temperature and held");
}

// Nothing is moving: the gate has gone to sleep on its peg. Heating it must
// still make the fixing be asked again, and the answer must come from the
// solver.
void aSleepingAssemblyIsRecheckedWhenHeatChangesIt() {
    auto world = openScene(scene(assembly("still", 0.0, 0.04)), 0.04);
    const unsigned peg = hang(*world, "still", 0.0, 800.0, true);
    stepFor(*world, 6.0);
    const unsigned awake = world->awakeBodies();
    const LiveJoint asleep = jointOf(*world, peg);
    std::cout << "    at rest: " << awake << " bodies awake; the sleeping fixing reads " << asleep.shear_n_now
              << " N" << std::endl;
    require(awake == 0, "the assembly has gone to sleep (the premise of this test)");
    (void)world->heat("still peg", 2000.0, 300.0);
    // Nothing else wakes it: a heater pushes nothing, and a body told it
    // weighs less as it burns is not woken by being told. Only the re-check.
    unsigned woken = 0;
    const Failure f = heatUntilParted(*world, peg, "still peg", 300.0,
                                      [&]() { woken = std::max(woken, world->awakeBodies()); });
    std::cout << "    heated: " << f.rechecks << " re-checks woke up to " << woken << " bodies; gave way at "
              << f.at_s << " s carrying " << f.load_n << " N against " << f.holds_n << " N" << std::endl;
    require(f.rechecks > 0 && woken > 0,
            "heat changing the peg made the fixing be asked again, with the assembly woken to measure it");
    require(f.parted, "and the sleeping assembly gave way when the model said so");
}

// Cooling gives back what was reversible and nothing else. Iron heated to
// 740 K and cooled is as strong as it was; oak that charred keeps its char and
// what it burned.
void coolingGivesBackOnlyWhatWasReversible() {
    auto world = openScene(scene(assembly("iron", 0.0, 0.0, "iron") + "," + assembly("oak", 3.0, 0.0)), 0.04);
    const unsigned iron = hang(*world, "iron", 0.0, 800.0, false);
    const unsigned oak = hang(*world, "oak", 3.0, 800.0, false);
    stepFor(*world, 0.5);
    (void)world->heat("iron peg", 8000.0, 60.0);
    (void)world->heat("oak peg", 2000.0, 25.0);
    double iron_low = 1.0, oak_hot = 1.0, oak_predicted = 1.0, iron_hottest = 0.0, oak_hottest = 0.0;
    for (int i = 0; i < static_cast<int>(60.0 / kDt); ++i) {
        stepOnce(*world);
        const LiveJoint a = jointOf(*world, iron), b = jointOf(*world, oak);
        iron_low = std::min(iron_low, a.capacity_fraction);
        if (b.capacity_fraction < oak_hot) {
            oak_hot = b.capacity_fraction;
            // What the law says it would keep if it cooled now.
            const thermo::SectionState s = thermo::evaluateSection(
                *thermo::lawFor("oak"), matterOf(*world, "oak peg"), kPegSize, 2);
            oak_predicted = std::min(s.tension_if_cooled, s.shear_if_cooled);
        }
        iron_hottest = std::max(iron_hottest, matterOf(*world, "iron peg").surface_k);
        oak_hottest = std::max(oak_hottest, matterOf(*world, "oak peg").peak_surface_k);
    }
    const double oak_remaining_hot = 1.0 - matterOf(*world, "oak peg").consumed_fraction;
    // Let both cool until the iron is back near the room.
    int waited = 0;
    while (waited < static_cast<int>(900.0 / kDt) &&
           (matterOf(*world, "iron peg").surface_k > 320.0 || matterOf(*world, "oak peg").core_k > 320.0)) {
        stepOnce(*world);
        ++waited;
    }
    const LiveJoint a = jointOf(*world, iron), b = jointOf(*world, oak);
    const thermo::MatterState cool_oak = matterOf(*world, "oak peg");
    std::cout << "    iron: hottest " << iron_hottest << " K, down to " << iron_low * 100.0 << "% of its "
              << "strength, and " << a.capacity_fraction * 100.0 << "% after " << waited * kDt
              << " s cooling to " << matterOf(*world, "iron peg").surface_k << " K\n"
              << "    oak: hottest " << oak_hottest << " K, down to " << oak_hot * 100.0 << "%, predicted to keep "
              << oak_predicted * 100.0 << "% cooled, keeps " << b.capacity_fraction * 100.0 << "% at "
              << cool_oak.surface_k << " K; " << 100.0 * (1.0 - cool_oak.consumed_fraction)
              << "% of its dry wood left (" << 100.0 * oak_remaining_hot << "% when the heat stopped)"
              << std::endl;
    require(iron_low < 0.95, "hot iron lost strength (EN 1993-1-2 above 400 degC)");
    require(a.capacity_fraction > 0.999, "cooled, it came all the way back");
    require(oak_hottest > 573.15, "the oak peg's surface passed the char point (the premise)");
    require(b.capacity_fraction < 0.9, "cooled oak does not get its char back");
    require(b.capacity_fraction <= oak_predicted + 1e-9,
            "and keeps no more than the law said, while it was hot, it would");
    require(1.0 - cool_oak.consumed_fraction <= oak_remaining_hot + 1e-12, "what burned stays burned");
    require(a.attached && b.attached, "neither was loaded, and neither fell");
}

// A step that is taken back takes back the heat, the history and every
// strength with it: the network and the joints are exactly as they were.
void aRefusedStepLeavesHeatAndStrengthAsTheyWere() {
    const std::string bodies =
        assembly("hot", 0.0, 0.04) + "," +
        box("pier left", "iron", {0.04, 0.12, 0.16}, {2.9, 0.06, 0}, true) + "," +
        box("pier right", "iron", {0.04, 0.12, 0.16}, {3.1, 0.06, 0}, true) + "," +
        box("pane", "glass", {0.24, 0.02, 0.16}, {3.0, 0.13, 0}, false) + "," +
        R"({"name":"ball","shape":"sphere","material":"iron","dimensions_m":[0.06,0.06,0.06],)"
        R"("center_m":[3.0,1.5,0],"velocity_m_s":[0,-8,0]})";
    auto world = openScene(scene(bodies), 0.02);
    const unsigned peg = world->fix("hot post", "hot peg", {0.0, kPegY, 0.08}, {0.0, 0.0, 1.0}, 0.0, 800.0);
    require(peg > 0 && world->setJointMember(peg, "hot peg"), "the peg is fixed and rated by itself");
    (void)world->heat("hot peg", 2000.0, 60.0);
    int refused = 0;
    for (int i = 0; i < 1200 && refused < 3; ++i) {
        const thermo::ThermoState before = world->thermo()->state();
        const LiveJoint joint_before = jointOf(*world, peg);
        world->step(kDt);
        if (!world->steppedBack()) continue;
        ++refused;
        const thermo::ThermoState after = world->thermo()->state();
        const LiveJoint joint_after = jointOf(*world, peg);
        require(after.lumps.size() == before.lumps.size(), "a refused step adds no body to the network");
        for (std::size_t k = 0; k < after.lumps.size(); ++k)
            require(after.lumps[k].peak_surface_k == before.lumps[k].peak_surface_k &&
                        after.lumps[k].peak_core_k == before.lumps[k].peak_core_k &&
                        after.lumps[k].initial_kg == before.lumps[k].initial_kg &&
                        after.lumps[k].surface.kg == before.lumps[k].surface.kg,
                    "a refused step leaves every peak and inventory exactly as it was");
        require(joint_after.holds_shear_n == joint_before.holds_shear_n &&
                    joint_after.rechecks == joint_before.rechecks,
                "and every strength");
        for (const std::string &name : world->breakable()) (void)world->fracture(name);
    }
    require(refused > 0, "the ball struck the pane and a step was refused (the premise)");
}

// Breaking shares the history out: every piece has used the same share of its
// load-bearing matter as the body had, is as hot at its hottest, and nothing is
// made or lost. And a copy of the state is a save: restoring it restores it.
void splittingAndRestoringKeepTheHistory() {
    thermo::ThermoWorld network;
    thermo::BodyShape plank;
    plank.name = "plank";
    plank.material = "oak";
    plank.center_m = {0.0, 1.0, 0.0};
    plank.half_extent_m = {0.2, 0.02, 0.05};
    plank.volume_m3 = 0.4 * 0.04 * 0.1;
    plank.area_m2 = 2.0 * (0.4 * 0.04 + 0.04 * 0.1 + 0.4 * 0.1);
    plank.mass_kg = 700.0 * plank.volume_m3;
    network.refresh({plank}, 0.0);
    (void)network.heat({"plank", 3000.0, 0.0, 120.0, "torch"});
    for (int i = 0; i < static_cast<int>(120.0 / kDt); ++i) network.advance(kDt, {});
    const thermo::MatterState whole = *network.matter("plank");
    require(whole.consumed_fraction > 0.0 && whole.peak_surface_k > 573.15,
            "the plank burned and charred (the premise)");
    // Save, go on, restore.
    const thermo::ThermoState saved = network.state();
    for (int i = 0; i < 240; ++i) network.advance(kDt, {});
    network.restore(saved);
    const thermo::MatterState back = *network.matter("plank");
    require(back.consumed_fraction == whole.consumed_fraction && back.peak_surface_k == whole.peak_surface_k &&
                back.peak_core_k == whole.peak_core_k,
            "a restored state has exactly the history it was saved with");
    // Split.
    double total_initial = 0.0;
    for (const thermo::Lump &l : network.state().lumps) for (double kg : l.initial_kg) total_initial += kg;
    network.split("plank", {{"plank piece 1", 0.3}, {"plank piece 2", 0.7}});
    double pieces_initial = 0.0;
    for (const char *name : {"plank piece 1", "plank piece 2"}) {
        const std::optional<thermo::MatterState> held = network.matter(name);
        require(held.has_value(), std::string("the network holds ") + name);
        const thermo::MatterState &piece = *held;
        char said[320];
        std::snprintf(said, sizeof said, "%s: %.15g of its dry wood used (the plank %.15g), hottest %.9f K "
                      "(the plank %.9f K)", name, piece.consumed_fraction, whole.consumed_fraction,
                      piece.peak_surface_k, whole.peak_surface_k);
        require(near(piece.consumed_fraction, whole.consumed_fraction, 1e-12) &&
                    near(piece.peak_surface_k, whole.peak_surface_k, 1e-9 * whole.peak_surface_k),
                std::string("each piece has used the plank's share of its dry wood and is as charred -- ") +
                    said);
    }
    for (const thermo::Lump &l : network.state().lumps) for (double kg : l.initial_kg) pieces_initial += kg;
    require(near(pieces_initial, total_initial, 1e-12 * total_initial), "and nothing was made or lost");
}

// Material, not temperature, decides: an iron peg in the same fire as the oak
// one that gave way still holds all it could.
void anIronPegInTheSameFireHolds() {
    auto world = openScene(scene(assembly("oak", 0.0, 0.04) + "," + assembly("iron", 3.0, 0.04, "iron")), 0.04);
    const unsigned oak = hang(*world, "oak", 0.0, 800.0, true);
    const unsigned iron = hang(*world, "iron", 3.0, 800.0, true);
    stepFor(*world, 3.0);
    (void)world->heat("oak peg", 2000.0, 300.0);
    (void)world->heat("iron peg", 2000.0, 300.0);
    const Failure f = heatUntilParted(*world, oak, "oak peg", 300.0);
    const LiveJoint held = jointOf(*world, iron);
    const thermo::MatterState steel = matterOf(*world, "iron peg");
    std::cout << "    the oak peg gave way at " << f.at_s << " s; the iron peg, given the same 2 kW, is at "
              << steel.surface_k << " K and holds " << held.holds_shear_n << " of " << held.rated_shear_n
              << " N" << std::endl;
    require(f.parted, "the oak peg gave way");
    require(held.attached && held.capacity_fraction == 1.0,
            "the iron peg holds everything it did: EN 1993-1-2 takes nothing below 400 degC");
}

// A spring whose limb softens with heat: its stiffness follows the law, the
// weight settles lower, and the elastic energy the softening releases is
// handed to the thermal ledger as heat -- not lost, not made.
void aSofteningSpringHandsItsEnergyToTheLedger() {
    const std::string bodies = box("hook", "iron", {0.08, 0.08, 0.08}, {0.0, 2.0, 0.0}, true) + "," +
                               box("weight", "iron", {0.16, 0.16, 0.16}, {0.0, 1.2, 0.0}, false);
    auto world = openScene(scene(bodies), 0.04);
    const double weight_n = 7870.0 * 0.16 * 0.16 * 0.16 * kGravity;
    const double k0 = 20000.0;
    // Built at the length it hangs at, so it starts still.
    const double apart = 1.96 - 1.28;
    const unsigned limb = world->spring("hook", "weight", {0.0, 1.96, 0.0}, {0.0, 1.28, 0.0},
                                        apart - weight_n / k0, k0, 900.0);
    require(limb > 0 && world->setJointMember(limb, "hook"), "the spring is made of the hook");
    stepFor(*world, 2.0);
    const double y0 = poseOf(*world, "weight").position_m.y;
    (void)world->heat("hook", 20000.0, 60.0);
    stepFor(*world, 90.0);
    const LiveJoint soft = jointOf(*world, limb);
    const double y1 = poseOf(*world, "weight").position_m.y;
    const thermo::Ledger ledger = world->thermo()->ledger();
    const thermo::SectionState s =
        thermo::evaluateSection(*thermo::lawFor("iron"), matterOf(*world, "hook"), {0.08, 0.08, 0.08}, 1);
    // Quasi-static softening from k0 to k1 under a constant weight releases
    // W^2 (1/k1 - 1/k0) / 2 of stored energy -- as heat, here.
    const double quasi_static = 0.5 * weight_n * weight_n * (1.0 / soft.stiffness_n_m - 1.0 / k0);
    std::cout << "    hook heated to " << matterOf(*world, "hook").surface_k << " K: stiffness " << k0 << " -> "
              << soft.stiffness_n_m << " N/m (law " << s.axial_stiffness << "); the weight settled "
              << (y0 - y1) * 1000.0 << " mm lower (Hooke " << weight_n * (1.0 / soft.stiffness_n_m - 1.0 / k0) * 1000.0
              << " mm); handed to the ledger " << ledger.mechanical_in_j << " J (quasi-static "
              << quasi_static << " J); residual " << ledger.residualJ() << " J" << std::endl;
    require(near(soft.stiffness_n_m, k0 * s.axial_stiffness, 1e-6 * k0) || s.axial_stiffness < 1e-3,
            "the spring's stiffness is the law's for the hook as it is now");
    require(soft.stiffness_n_m < 0.6 * k0, "and the hook got hot enough to soften (the premise)");
    require(near(y0 - y1, weight_n * (1.0 / soft.stiffness_n_m - 1.0 / k0), 0.003),
            "the weight settled where the softer spring holds it");
    require(ledger.mechanical_in_j > 0.0 && near(ledger.mechanical_in_j, quasi_static, 0.1 * quasi_static),
            "the stored energy it let go of went into the ledger");
    require(std::abs(ledger.residualJ()) < 1e-9 * std::abs(ledger.storedJ()), "and the ledger closes");
}

// A heated plank bridging two piers: the load survey tests the section heat
// has left it, as soon as the section moves, and says so. Its cold twin is
// never offered.
void aHeatedBeamIsSurveyedWithTheSectionItHasLeft() {
    const auto bridge = [](const std::string &tag, double x) {
        return box(tag + " pier left", "concrete", {0.16, 0.4, 0.4}, {x - 0.5, 0.2, 0.0}, true) + "," +
               box(tag + " pier right", "concrete", {0.16, 0.4, 0.4}, {x + 0.5, 0.2, 0.0}, true) + "," +
               box(tag + " plank", "oak", {1.2, 0.02, 0.2}, {x, 0.41, 0.0}, false) + "," +
               box(tag + " block", "iron", {0.3, 0.3, 0.3}, {x, 0.57, 0.0}, false);
    };
    auto world = openScene(scene(bridge("hot", 0.0) + "," + bridge("cold", 4.0)), 0.02);
    stepFor(*world, 1.0);
    (void)world->heat("hot plank", 8000.0, 300.0);
    const thermo::MechanicalLaw *oak = thermo::lawFor("oak");
    int crossed = -1, offered = -1;
    double stress = 0.0, fraction = 0.0, law_fraction = 0.0, lowest = 1.0;
    for (int i = 0; i < static_cast<int>(300.0 / kDt) && offered < 0; ++i) {
        stepOnce(*world);
        for (const LiveOverload &o : world->overloaded()) {
            require(o.name != "cold plank", "the cold twin is never offered");
            if (o.name != "hot plank") continue;
            offered = i;
            stress = o.stress_pa;
            fraction = o.capacity_fraction;
            law_fraction =
                thermo::evaluateSection(*oak, matterOf(*world, "hot plank"), {1.2, 0.02, 0.2}, 0, 1).bending;
            require(near(o.strength_pa, 90.0e6 * o.capacity_fraction, 1.0), "its strength is 90 MPa times what is left");
            require(o.why.find("heated") != std::string::npos, "and it says it is heated");
        }
        if (crossed < 0 && world->thermo() != nullptr && world->thermo()->holds("hot plank")) {
            const double left =
                thermo::evaluateSection(*oak, matterOf(*world, "hot plank"), {1.2, 0.02, 0.2}, 0, 1).bending;
            lowest = std::min(lowest, left);
            // The same stress the survey reports, once it reports one.
            if (stress > 0.0 && 90.0e6 * left < stress) crossed = i;
        }
    }
    if (offered < 0)
        std::cout << "    never offered: the plank's section got down to " << lowest * 100.0 << "% at "
                  << matterOf(*world, "hot plank").surface_k << " K surface, "
                  << matterOf(*world, "hot plank").core_k << " K core" << std::endl;
    std::cout << "    the heated plank was offered as overloaded " << offered * kDt << " s into 8 kW: "
              << stress / 1e6 << " MPa against " << 90.0 * fraction << " MPa (" << fraction * 100.0
              << "% of its section, law " << law_fraction * 100.0 << "%)" << std::endl;
    require(offered >= 0, "the heated plank was offered as overloaded");
    require(near(fraction, law_fraction, 5e-3), "with the section the law leaves it");
}

} // namespace

int main(int argc, char **argv) {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"the laws are their sources' numbers", theLawsAreTheirSourcesNumbers},
        {"a cold assembly holds its load", aColdAssemblyHoldsItsLoad},
        {"the heated twin weakens by its law and fails", theHeatedTwinWeakensByItsLawAndFails},
        {"a different load changes the answer", aDifferentLoadChangesTheAnswer},
        {"a sleeping assembly is rechecked when heat changes it", aSleepingAssemblyIsRecheckedWhenHeatChangesIt},
        {"cooling gives back only what was reversible", coolingGivesBackOnlyWhatWasReversible},
        {"a refused step leaves heat and strength as they were", aRefusedStepLeavesHeatAndStrengthAsTheyWere},
        {"splitting and restoring keep the history", splittingAndRestoringKeepTheHistory},
        {"an iron peg in the same fire holds", anIronPegInTheSameFireHolds},
        {"a softening spring hands its energy to the ledger", aSofteningSpringHandsItsEnergyToTheLedger},
        {"a heated beam is surveyed with the section it has left", aHeatedBeamIsSurveyedWithTheSectionItHasLeft},
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
