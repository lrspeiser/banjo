// Rolling resistance, measured through the real engine (docs/rolling-resistance.md).
//
// A round body rolling on something is resisted at each of its contacts by the
// couple M = c N r against its turning: c the pair's coefficient -- the ball's
// own share plus the surface's -- N the normal force the solver put through the
// contact, r the radius. Everything below is derived from that law and checked
// against the engine; nothing is tuned to pass:
//
//   1. On the level a solid ball rolling without slipping slows at
//          m a = -f,  I alpha = f r - c N r,  a = alpha r,  I = 2/5 m r^2
//          =>  a = 5/7 c g,  and it stops in v0^2 / (2a).
//      Rubber and iron on the concrete floor, beside a control with every
//      coefficient zero that does not slow at all -- in the rigid world, and in
//      the live world the playground runs.
//   2. What the couple takes out of the motion is the kinetic energy the ball
//      loses: the declared loss closes the account.
//   3. On a slope a ball set down at rest stays when tan(theta) < c and rolls
//      at 5/7 g (sin theta - c cos theta) when tan(theta) > c: on a plane of the
//      ground's own height field with its surface declared sand, the same ball
//      beside a zero-resistance control; and on an anchored ramp in the live
//      world, just below and just above atan(c).
//   4. N is the solver's own normal force at each contact, not m g: two balls
//      carrying a plank each carry half of it, which m g would miss entirely.
//   5. In the valley a rubber ball set down on the sand by the river stays put
//      for 10 s, and the same ball set down on sloping bare rock rolls away.
//
// Run one by name as argv[1]; --list names them.
#include "core/Plane.hpp"
#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "rigid/JoltWorld.hpp"
#include "terrain/Environment.hpp"
#include "terrain/TerrainField.hpp"
#include "water/ShallowWater.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <memory>
#include <numbers>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;
using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

constexpr double kDt = 1.0 / 240.0;   // what the room steps at
constexpr double kG = 9.81;
constexpr double kPi = std::numbers::pi;
constexpr double kRadius = 0.06;      // the playground's usual 120 mm ball

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

// Within `fraction` of what the law says, and printed either way.
void within(double measured, double expected, double fraction, const std::string &what) {
    const double off = (measured - expected) / expected;
    std::printf("    %-58s measured %.5g, the law says %.5g (%+.2f%%)\n", what.c_str(), measured,
                expected, 100.0 * off);
    if (!(std::abs(off) <= fraction))
        throw std::runtime_error(what + ": " + std::to_string(100.0 * off) + "% from the law, allowed " +
                                 std::to_string(100.0 * fraction) + "%");
}

double own(MaterialPreset preset) {
    return compileContactMaterial(makeReferenceMaterial(preset, 0)).rolling_resistance;
}

double degrees(double radians) { return radians * 180.0 / kPi; }
double radians(double degrees_) { return degrees_ * kPi / 180.0; }

// Least-squares slope of y against x.
double fittedSlope(const std::vector<double> &x, const std::vector<double> &y) {
    const double n = static_cast<double>(x.size());
    double sx = 0.0, sy = 0.0, sxx = 0.0, sxy = 0.0;
    for (std::size_t i = 0; i < x.size(); ++i) {
        sx += x[i];
        sy += y[i];
        sxx += x[i] * x[i];
        sxy += x[i] * y[i];
    }
    return (n * sxy - sx * sy) / (n * sxx - sx * sx);
}

double kineticEnergy(const JoltWorld &world, MatterBodyId id) {
    const RigidMechanicalState state = world.mechanicalState(id);
    const Vec3 v = state.motion.linear_velocity_m_s;
    const Vec3 w = state.motion.angular_velocity_rad_s;
    return 0.5 * state.mass_kg * lengthSquared(v) + 0.5 * dot(w, state.inertia_world_kg_m2 * w);
}

// ---- the live world, as the playground opens it ---------------------------

Json box(const std::string &name, const std::string &material, Vec3 size, Vec3 at, bool anchored = false) {
    return {{"name", name}, {"shape", "box"}, {"material", material},
            {"dimensions_m", {size.x, size.y, size.z}}, {"center_m", {at.x, at.y, at.z}},
            {"anchored", anchored}};
}

Json ball(const std::string &name, const std::string &material, Vec3 at) {
    const double d = 2.0 * kRadius;
    return {{"name", name}, {"shape", "sphere"}, {"material", material},
            {"dimensions_m", {d, d, d}}, {"center_m", {at.x, at.y, at.z}}};
}

std::unique_ptr<LiveWorld> open(const Json &scene, double cell_m) {
    const std::string text = scene.dump();
    TileImpactRequest request;
    request.cell_size_m = cell_m;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(text);
    readSceneSettings(text, request);
    return LiveWorld::open(request);
}

// One step of the room, answering a break by running it (nothing here breaks).
void stepRoom(LiveWorld &world) {
    for (;;) {
        world.step(kDt);
        if (!world.steppedBack()) return;
        for (const std::string &name : world.breakable()) (void)world.fracture(name);
    }
}

void run(LiveWorld &world, double seconds) {
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    for (int i = 0; i < steps; ++i) stepRoom(world);
}

LiveBodyPose poseOf(const LiveWorld &world, const std::string &name) {
    for (const LiveBodyPose &pose : world.poses())
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

// ---- 1 and 2: on the level --------------------------------------------------

struct Roll {
    double speed_m_s{};       // when the measurement began
    double decel_m_s2{};      // fitted while it is still clearly rolling
    double distance_m{};      // from there to where it stopped
    double loss_j{};          // what rolling resistance declared it took
    double kinetic_lost_j{};  // what the ball actually lost
    bool stopped{};
};

// A ball rolling without slipping along +x at v0 on a flat floor, in the rigid
// world: an analytic sphere, I = 2/5 m r^2 exactly.
Roll rollOnTheFloor(const MaterialDefinition &ball_material, const MaterialDefinition &floor_material,
                    double v0, double seconds) {
    JoltWorld world;
    world.setGravity({0.0, -kG, 0.0});
    world.addSupportSurface({.frame = makeSupportPlane({}, {0.0, 1.0, 0.0}),
                             .material = floor_material,
                             .half_length_tangent_m = 100.0,
                             .half_length_bitangent_m = 20.0});
    world.addBall({.body_id = 1, .radius_m = kRadius, .material = ball_material,
                   .position_world_m = {0.0, kRadius, 0.0},
                   .linear_velocity_m_s = {v0, 0.0, 0.0},
                   .angular_velocity_rad_s = {0.0, 0.0, -v0 / kRadius}});
    // A tenth of a second to take up the contact before anything is measured.
    for (int i = 0; i < 24; ++i) world.step(kDt);
    Roll out;
    const RigidSnapshot start = world.snapshot(1);
    out.speed_m_s = start.linear_velocity_m_s.x;
    const double kinetic0 = kineticEnergy(world, 1);
    const double loss0 = world.rollingLossJ();
    std::vector<double> t, v;
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    for (int i = 1; i <= steps; ++i) {
        world.step(kDt);
        const double speed = world.snapshot(1).linear_velocity_m_s.x;
        if (speed > 0.3 * out.speed_m_s) {
            t.push_back(i * kDt);
            v.push_back(speed);
        }
        if (!world.isAwake(1) || std::abs(speed) < 1.0e-6) {
            out.stopped = true;
            break;
        }
    }
    out.decel_m_s2 = t.size() > 10 ? -fittedSlope(t, v) : 0.0;
    out.distance_m = world.snapshot(1).center_of_mass_world_m.x - start.center_of_mass_world_m.x;
    out.loss_j = world.rollingLossJ() - loss0;
    out.kinetic_lost_j = kinetic0 - kineticEnergy(world, 1);
    return out;
}

// The same, in the live world the playground runs: a ball made of cells, on
// the room's concrete floor, given its speed with "roll": true.
Roll rollInTheRoom(const std::string &material, double v0, double cell_m, double seconds) {
    Json thrown = ball("ball", material, {0.0, kRadius + 0.0005, 0.0});
    thrown["velocity_m_s"] = {v0, 0.0, 0.0};
    thrown["roll"] = true;
    auto world = open(Json{{"bodies", Json::array({thrown})}}, cell_m);
    run(*world, 0.25);
    Roll out;
    const LiveBodyPose start = poseOf(*world, "ball");
    out.speed_m_s = start.velocity_m_s.x;
    const double loss0 = world->rollingLossJ();
    std::vector<double> t, v;
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    for (int i = 1; i <= steps; ++i) {
        stepRoom(*world);
        const double speed = poseOf(*world, "ball").velocity_m_s.x;
        if (speed > 0.3 * out.speed_m_s) {
            t.push_back(i * kDt);
            v.push_back(speed);
        }
        if (world->awakeBodies() == 0 || std::abs(speed) < 1.0e-6) {
            out.stopped = true;
            break;
        }
    }
    out.decel_m_s2 = t.size() > 10 ? -fittedSlope(t, v) : 0.0;
    out.distance_m = poseOf(*world, "ball").position_m.x - start.position_m.x;
    out.loss_j = world->rollingLossJ() - loss0;
    return out;
}

// 1. a = 5/7 c g and d = v0^2 / (2a), rubber and iron on the floor, and a
// control with no rolling resistance that does not slow.
void onTheLevelABallSlowsAtFiveSeventhsCG() {
    const MaterialDefinition concrete = makeReferenceMaterial(MaterialPreset::Concrete, 0);
    struct Pair {
        const char *what;
        MaterialPreset ball;
        const char *material;
        double v0;
    };
    const Pair pairs[] = {{"rubber on the concrete floor", MaterialPreset::Rubber, "rubber", 1.0},
                          {"iron on the concrete floor", MaterialPreset::Iron, "iron", 0.3}};
    for (const Pair &pair : pairs) {
        const double c = own(pair.ball) + own(MaterialPreset::Concrete);
        const double a = 5.0 / 7.0 * c * kG;
        std::printf("  %s: c = %.4f + %.4f = %.4f\n", pair.what, own(pair.ball),
                    own(MaterialPreset::Concrete), c);
        // The rigid world's analytic sphere.
        const Roll rigid =
            rollOnTheFloor(makeReferenceMaterial(pair.ball, 0), concrete, pair.v0, 3.0 * pair.v0 / a);
        require(rigid.stopped, std::string(pair.what) + ": the ball never stopped");
        within(rigid.decel_m_s2, a, 0.10, std::string("rigid world, deceleration (m/s^2)"));
        within(rigid.distance_m, rigid.speed_m_s * rigid.speed_m_s / (2.0 * a), 0.10,
               std::string("rigid world, stopping distance (m)"));
        // The live world, a ball of 1 cm cells: 917 of them, a solid sphere to
        // within 1.5% in its inertia.
        const Roll room = rollInTheRoom(pair.material, pair.v0, 0.01, 3.0 * pair.v0 / a);
        require(room.stopped, std::string(pair.what) + ": the room's ball never stopped");
        within(room.decel_m_s2, a, 0.10, std::string("live world, 10 mm cells, deceleration (m/s^2)"));
        within(room.distance_m, room.speed_m_s * room.speed_m_s / (2.0 * a), 0.10,
               std::string("live world, 10 mm cells, stopping distance (m)"));
        // At the room's own 40 mm cells a 120 mm ball is 19 cells, and its own
        // inertia is 0.54 m r^2, not 0.4: it slows at c g / 1.54, 9% under
        // 5/7 c g. Said, not asserted -- the law for THAT body is c g / (1 + k).
        const Roll coarse = rollInTheRoom(pair.material, pair.v0, 0.04, 3.0 * pair.v0 / a);
        std::printf("    %-58s measured %.5g, 5/7 c g = %.5g (%+.2f%%), stopped %s after %.3f m\n",
                    "live world, 40 mm cells (19 cells), deceleration (m/s^2)", coarse.decel_m_s2, a,
                    100.0 * (coarse.decel_m_s2 - a) / a, coarse.stopped ? "yes" : "no",
                    coarse.distance_m);
    }
    // The control: the same rubber ball on the same floor, every rolling
    // coefficient zero. Nothing else in the engine slows a rolling ball.
    MaterialDefinition ball = makeReferenceMaterial(MaterialPreset::Rubber, 0);
    MaterialDefinition floor = concrete;
    ball.rolling_resistance = 0.0;
    floor.rolling_resistance = 0.0;
    const Roll free = rollOnTheFloor(ball, floor, 1.0, 5.0);
    std::printf("  control, zero rolling resistance: from %.6f m/s, deceleration %.3g m/s^2 over 5 s\n",
                free.speed_m_s, free.decel_m_s2);
    require(!free.stopped, "with no rolling resistance the ball stopped");
    require(std::abs(free.decel_m_s2) < 1.0e-3,
            "with no rolling resistance a rolling ball keeps its speed (under 1.3% of rubber's deceleration)");
}

// 2. The loss declared is the kinetic energy lost.
void theEnergyItTakesIsTheEnergyTheBallLoses() {
    const MaterialDefinition concrete = makeReferenceMaterial(MaterialPreset::Concrete, 0);
    const Roll roll = rollOnTheFloor(makeReferenceMaterial(MaterialPreset::Rubber, 0), concrete, 1.0, 30.0);
    require(roll.stopped, "the rubber ball never stopped");
    std::printf("  rubber ball rolled to rest from %.4f m/s over %.3f m\n", roll.speed_m_s, roll.distance_m);
    within(roll.loss_j, roll.kinetic_lost_j, 0.02,
           std::string("energy rolling resistance declared it took (J)"));
}

// ---- 3: slopes ------------------------------------------------------------------

struct Slope {
    double moved_m{};        // down the slope, in `seconds`
    double accel_m_s2{};     // fitted along the slope
};

// A ball set down at rest on a plane of the ground's own height field, tilted
// `theta_deg` and falling toward +x, the ground's share declared `surface`.
Slope onTheGround(const MaterialDefinition &ball_material, double surface, double theta_deg, double seconds) {
    constexpr unsigned kCount = 32;        // 32 x 32 heights 0.25 m apart: 7.75 m square
    constexpr double kSpacing = 0.25;
    const double theta = radians(theta_deg);
    const double tangent = std::tan(theta);
    const double x0 = -0.5 * (kCount - 1) * kSpacing;
    std::vector<float> heights(static_cast<std::size_t>(kCount) * kCount);
    for (unsigned j = 0; j < kCount; ++j)
        for (unsigned i = 0; i < kCount; ++i)
            heights[static_cast<std::size_t>(j) * kCount + i] =
                static_cast<float>(4.0 - tangent * (x0 + i * kSpacing));
    JoltWorld world;
    world.setGravity({0.0, -kG, 0.0});
    // Dry earth, as the valley's patches are; what it is made of is said by
    // the ground's own rolling-resistance answer, as the valley's is.
    MaterialDefinition earth;
    earth.name = "test ground";
    earth.density_kg_m3 = 1600.0;
    earth.young_modulus_pa = 0.05e9;
    earth.poisson_ratio = 0.3;
    earth.static_friction = 0.7;
    earth.dynamic_friction = 0.6;
    earth.friction = 0.6;
    earth.contact_damping_ratio = 0.6;
    earth.derive_restitution_from_damping = true;
    world.addGroundPatch(heights, kCount, kSpacing, x0, x0, earth, 1.0e-4);
    world.setGroundRollingResistance([surface](double, double) { return surface; });
    const double start_x = x0 + 1.5;
    const double ground_y = 4.0 - tangent * start_x;
    world.addBall({.body_id = 1, .radius_m = kRadius, .material = ball_material,
                   .position_world_m = {start_x, ground_y + kRadius / std::cos(theta) + 1.0e-4, 0.0}});
    const Vec3 down{std::cos(theta), -std::sin(theta), 0.0};
    // It is set down; let it take up the contact.
    for (int i = 0; i < 12; ++i) world.step(kDt);
    const Vec3 p0 = world.snapshot(1).center_of_mass_world_m;
    std::vector<double> t, v;
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    for (int i = 1; i <= steps; ++i) {
        world.step(kDt);
        t.push_back(i * kDt);
        v.push_back(dot(world.snapshot(1).linear_velocity_m_s, down));
    }
    Slope out;
    out.moved_m = dot(world.snapshot(1).center_of_mass_world_m - p0, down);
    out.accel_m_s2 = fittedSlope(t, v);
    return out;
}

// The same on an exact plane: a support plane tilted `theta_deg`, falling
// toward +x, made of `surface`.
Slope onAPlane(const MaterialDefinition &ball_material, const MaterialDefinition &surface, double theta_deg,
               double seconds) {
    const SupportPlaneFrame plane = makeSupportPlaneFromSlopeDegrees(theta_deg);
    JoltWorld world;
    world.setGravity({0.0, -kG, 0.0});
    world.addSupportSurface({.frame = plane, .material = surface,
                             .half_length_tangent_m = 20.0, .half_length_bitangent_m = 5.0});
    world.addBall({.body_id = 1, .radius_m = kRadius, .material = ball_material,
                   .position_world_m = pointInPlaneFrame(plane, -5.0, 0.0, kRadius + 1.0e-4)});
    const Vec3 down = plane.tangent_world;
    for (int i = 0; i < 12; ++i) world.step(kDt);
    const Vec3 p0 = world.snapshot(1).center_of_mass_world_m;
    std::vector<double> t, v;
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    for (int i = 1; i <= steps; ++i) {
        world.step(kDt);
        t.push_back(i * kDt);
        v.push_back(dot(world.snapshot(1).linear_velocity_m_s, down));
    }
    Slope out;
    out.moved_m = dot(world.snapshot(1).center_of_mass_world_m - p0, down);
    out.accel_m_s2 = fittedSlope(t, v);
    return out;
}

// 3a. Declared sand holds a rubber ball on the river bank's 2.1 degrees and on
// 0.85 atan(c), and lets it roll at 1.15 atan(c), on the ground's own height
// field; and on an exact plane the roll goes at the law's rate, beside the
// same ball with no rolling resistance on no-resistance ground, which rolls
// down 2.1 degrees at 5/7 g sin(theta).
void onTheGroundABallRestsBelowAtanCAndRollsAbove() {
    const MaterialDefinition rubber = makeReferenceMaterial(MaterialPreset::Rubber, 0);
    const double sand = terrain::sandMaterial().rolling_resistance;
    const double c = own(MaterialPreset::Rubber) + sand;
    const double limit_deg = degrees(std::atan(c));
    std::printf("  rubber on sand: c = %.3f + %.3f = %.3f, so it rests on slopes up to %.2f degrees\n",
                own(MaterialPreset::Rubber), sand, c, limit_deg);
    const double steep = 1.15 * limit_deg;
    const double law = 5.0 / 7.0 * kG * (std::sin(radians(steep)) - c * std::cos(radians(steep)));
    std::cout << "  on the ground's height field, the surface declared sand where the ball touches it:\n";
    for (const double theta_deg : {2.1, 0.85 * limit_deg}) {
        const Slope held = onTheGround(rubber, sand, theta_deg, 5.0);
        std::printf("    %.2f degrees (tan %.3f < c): moved %.3g m down it in 5 s\n", theta_deg,
                    std::tan(radians(theta_deg)), held.moved_m);
        require(std::abs(held.moved_m) < 0.002, "a ball on a slope below atan(c) must stay where it was set down");
    }
    const Slope rolled = onTheGround(rubber, sand, steep, 3.0);
    std::printf("    %.2f degrees (tan %.3f > c): moved %.3f m in 3 s, accelerating at %.4f m/s^2 "
                "against the law's %.4f (%+.1f%%: the height field keeps its heights to a few tenths "
                "of a millimetre, and a ball rolling over the steps loses a little more)\n",
                steep, std::tan(radians(steep)), rolled.moved_m, rolled.accel_m_s2, law,
                100.0 * (rolled.accel_m_s2 - law) / law);
    require(rolled.moved_m > 0.5, "a ball on a slope above atan(c) must roll");
    MaterialDefinition free_ball = rubber;
    free_ball.rolling_resistance = 0.0;
    const Slope free_ground = onTheGround(free_ball, 0.0, 2.1, 3.0);
    std::printf("    control, no rolling resistance, 2.10 degrees: moved %.3f m in 3 s\n", free_ground.moved_m);
    require(free_ground.moved_m > 0.5, "with no rolling resistance a ball rolls down the bank's 2.1 degrees");
    // An exact plane, where the geometry is not in question, for the rates.
    std::cout << "  on an exact plane of the same declared sand:\n";
    MaterialDefinition sand_surface = makeReferenceMaterial(MaterialPreset::Concrete, 0);
    sand_surface.name = "declared sand";
    sand_surface.rolling_resistance = sand;
    const Slope held_plane = onAPlane(rubber, sand_surface, 0.85 * limit_deg, 5.0);
    std::printf("    %.2f degrees: moved %.3g m in 5 s\n", 0.85 * limit_deg, held_plane.moved_m);
    require(std::abs(held_plane.moved_m) < 0.002, "a ball on a plane below atan(c) must stay where it was set down");
    const Slope rolled_plane = onAPlane(rubber, sand_surface, steep, 3.0);
    within(rolled_plane.accel_m_s2, law, 0.10, "rolling down, acceleration 5/7 g (sin - c cos) (m/s^2)");
    MaterialDefinition free_surface = sand_surface;
    free_surface.rolling_resistance = 0.0;
    const Slope free_plane = onAPlane(free_ball, free_surface, 2.1, 3.0);
    within(free_plane.accel_m_s2, 5.0 / 7.0 * kG * std::sin(radians(2.1)), 0.10,
           "control, no resistance, 2.1 degrees: 5/7 g sin (m/s^2)");
}

// 3b. An anchored ramp in the live world, just below and just above atan(c):
// a rubber ball on a concrete ramp.
double onTheRamp(double theta_deg, double seconds) {
    const double theta = radians(theta_deg);
    const Vec3 centre{0.0, 0.4, 0.0};
    const Vec3 up{-std::sin(theta), std::cos(theta), 0.0};   // the top face, turned theta about z
    Json ramp = box("ramp", "concrete", {2.0, 0.2, 0.6}, centre, true);
    ramp["rotation_deg"] = {0.0, 0.0, theta_deg};
    const Vec3 at = centre + (0.1 + kRadius + 0.0005) * up;
    auto world = open(Json{{"bodies", Json::array({ramp, ball("ball", "rubber", at)})}}, 0.04);
    run(*world, 0.25);
    const Vec3 p0 = poseOf(*world, "ball").position_m;
    run(*world, seconds);
    const Vec3 p1 = poseOf(*world, "ball").position_m;
    return std::hypot(p1.x - p0.x, p1.z - p0.z);
}

void onAnAnchoredRampABallRestsJustBelowAtanCAndRollsJustAbove() {
    const double c = own(MaterialPreset::Rubber) + own(MaterialPreset::Concrete);
    const double limit_deg = degrees(std::atan(c));
    std::printf("  rubber on a concrete ramp: c = %.4f, atan(c) = %.3f degrees\n", c, limit_deg);
    const double below = onTheRamp(0.85 * limit_deg, 5.0);
    std::printf("    %.3f degrees, just below: moved %.3g m in 5 s\n", 0.85 * limit_deg, below);
    require(below < 0.002, "a ball on a ramp just below atan(c) must stay where it was set down");
    const double above = onTheRamp(1.15 * limit_deg, 5.0);
    std::printf("    %.3f degrees, just above: moved %.3g m in 5 s\n", 1.15 * limit_deg, above);
    require(above > 0.02, "a ball on a ramp just above atan(c) must roll");
}

// ---- 4: N is the solver's ----------------------------------------------------

void theNormalForceIsTheSolversOwn() {
    JoltWorld world;
    world.setGravity({0.0, -kG, 0.0});
    world.addFloor();
    const MaterialDefinition rubber = makeReferenceMaterial(MaterialPreset::Rubber, 0);
    const MaterialDefinition iron = makeReferenceMaterial(MaterialPreset::Iron, 0);
    // One ball on its own, and two carrying an iron plank between them.
    world.addBall({.body_id = 1, .radius_m = kRadius, .material = rubber, .position_world_m = {-2.0, kRadius, 0.0}});
    world.addBall({.body_id = 2, .radius_m = kRadius, .material = rubber, .position_world_m = {-0.3, kRadius, 0.0}});
    world.addBall({.body_id = 3, .radius_m = kRadius, .material = rubber, .position_world_m = {0.3, kRadius, 0.0}});
    world.addBox({.body_id = 4, .dimensions_m = {1.0, 0.04, 0.2}, .material = iron,
                  .state = {.center_of_mass_world_m = {0.0, 2.0 * kRadius + 0.02, 0.0}}});
    for (int i = 0; i < 120; ++i) world.step(kDt);
    const double m = world.mechanicalState(1).mass_kg;
    const double plank = world.mechanicalState(4).mass_kg;
    double alone = -1.0, floor_under = -1.0, plank_on = -1.0;
    bool solver = true;
    for (const JoltWorld::RollingContactReport &contact : world.rollingContacts()) {
        solver = solver && contact.from_solver;
        if (contact.sphere == 1 && contact.other == kSupportSurfaceMatterId) alone = contact.normal_force_n;
        if (contact.sphere == 2 && contact.other == kSupportSurfaceMatterId) floor_under = contact.normal_force_n;
        if (contact.sphere == 2 && contact.other == 4) plank_on = contact.normal_force_n;
    }
    std::printf("  ball %.3f kg, plank %.2f kg\n", m, plank);
    require(solver, "N was not read from the solver's contact impulses");
    require(alone > 0.0 && floor_under > 0.0 && plank_on > 0.0, "a contact of the three was not found");
    within(alone, m * kG, 0.01, "a ball alone on the floor, N (N)");
    within(floor_under, (m + 0.5 * plank) * kG, 0.03, "a ball under the plank, N from the floor (N)");
    within(plank_on, 0.5 * plank * kG, 0.03, "the same ball, N from the plank on it (N)");
    std::printf("    m g n_y would have given %.2f N under the plank: %.0f%% short of the solver's %.1f N\n",
                m * kG, 100.0 * (1.0 - m * kG / floor_under), floor_under);
}

// ---- 5: the valley ------------------------------------------------------------

struct Valley {
    std::unique_ptr<terrain::Environment> land;
    Valley() { land = terrain::Environment::fromScene(Json{{"terrain", {{"generate", "valley"}}}}.dump()); }
    const terrain::TerrainField &ground() const { return land->terrain(); }
    const water::ShallowWater &water() const { return *land->water(); }
    double groundAt(double x, double z) const { return ground().heightAt(x, z); }
};

// Somewhere the model says the same rubber ball rolls: a dry square of the
// ground's grid whose four corners lie in one plane to within a millimetre --
// so both of its triangles are that plane, and the ball is set down on a face,
// not balanced on a ridge or sat in a hollow the ground itself would hold it
// in -- sloping 5 to 15 degrees, with the eight squares round it rock (or soil)
// sloping at least 3 degrees too, all dry. Rock first: atan(0.011) is 0.63
// degrees. Soil's atan(0.07) is 4.0.
struct Sloping {
    double x{}, z{}, ground_y{}, slope_deg{};
    std::string surface;
};
std::optional<Sloping> slopingGround(const Valley &v) {
    const terrain::TerrainField &ground = v.ground();
    const terrain::Grid &g = ground.grid();
    const auto square = [&](int i, int j, double &slope_deg, double &flatness) {
        const double h00 = ground.height(g.at(i, j)), h10 = ground.height(g.at(i + 1, j));
        const double h01 = ground.height(g.at(i, j + 1)), h11 = ground.height(g.at(i + 1, j + 1));
        const double bx = 0.5 * ((h10 - h00) + (h11 - h01)) / g.dx;
        const double bz = 0.5 * ((h01 - h00) + (h11 - h10)) / g.dx;
        slope_deg = degrees(std::atan(std::hypot(bx, bz)));
        flatness = std::abs((h00 + h11) - (h10 + h01));
        return 0.25 * (h00 + h10 + h01 + h11);
    };
    for (const terrain::Surface want : {terrain::Surface::Rock, terrain::Surface::Soil}) {
        for (int j = 2; j < g.nz - 3; ++j)
            for (int i = 2; i < g.nx - 3; ++i) {
                double slope = 0.0, flatness = 0.0;
                const double middle = square(i, j, slope, flatness);
                if (slope < 5.0 || slope > 15.0 || flatness > 0.001) continue;
                bool fits = true;
                for (int dj = -1; dj <= 1 && fits; ++dj)
                    for (int di = -1; di <= 1 && fits; ++di) {
                        double around = 0.0, bent = 0.0;
                        (void)square(i + di, j + dj, around, bent);
                        for (int cj = 0; cj <= 1; ++cj)
                            for (int ci = 0; ci <= 1; ++ci) {
                                const std::size_t k = g.at(i + di + ci, j + dj + cj);
                                if (ground.surface(k) != want || v.water().depth(k) > 0.0) fits = false;
                            }
                        if (around < 3.0) fits = false;
                    }
                if (!fits) continue;
                return Sloping{g.xOf(i) + 0.5 * g.dx, g.zOf(j) + 0.5 * g.dx, middle, slope,
                               want == terrain::Surface::Rock ? "rock" : "soil"};
            }
    }
    return std::nullopt;
}

void inTheValleyTheBallByTheRiverStaysOnTheSand() {
    const Valley v;
    constexpr double x = 2.0, z = 4.25;   // the QA case's own spot, beside the person on the bank
    const Json here = Json::parse(v.land->surveyJson(x, z));
    const double c = own(MaterialPreset::Rubber) + here.at("rolling_resistance").get<double>();
    std::printf("  [%.2f, %.2f]: %s, sloping %.2f degrees; c = %.3f, so a ball rests up to %.1f degrees\n", x, z,
                here.at("surface").get<std::string>().c_str(), here.at("slope_deg").get<double>(), c,
                degrees(std::atan(c)));
    require(here.at("surface") == "sand", "the ball by the river is set down on sand");
    require(std::tan(radians(here.at("slope_deg").get<double>())) < c,
            "the model says a ball rests there: tan(slope) < c");
    const auto rock = slopingGround(v);
    require(rock.has_value(), "the valley has a dry plane slope of rock or soil for the control");
    const Json there = Json::parse(v.land->surveyJson(rock->x, rock->z));
    const double c_there = own(MaterialPreset::Rubber) + there.at("rolling_resistance").get<double>();
    std::printf("  control [%.3f, %.3f]: %s, a plane slope of %.2f degrees; c = %.4f, so a ball rolls "
                "above %.2f degrees\n",
                rock->x, rock->z, rock->surface.c_str(), rock->slope_deg, c_there, degrees(std::atan(c_there)));
    require(std::tan(radians(rock->slope_deg)) > c_there, "the model says a ball rolls on the control's slope");
    // Set down as add_object [x, z] sets a thing down: its bottom 2 mm over the
    // ground under its centre.
    Json bodies = Json::array(
        {ball("ball on the sand", "rubber", {x, v.groundAt(x, z) + kRadius + 0.002, z}),
         ball("ball on the rock", "rubber",
              {rock->x, rock->ground_y + kRadius / std::cos(radians(rock->slope_deg)) + 0.002, rock->z}),
         box("marker stone", "concrete", {0.16, 0.16, 0.16},
             {v.ground().grid().x0 + 1.0, v.groundAt(v.ground().grid().x0 + 1.0, v.ground().grid().z0 + 1.0) + 0.08,
              v.ground().grid().z0 + 1.0},
             true)});
    auto world = open(Json{{"plasticity", true}, {"bodies", bodies}, {"terrain", {{"generate", "valley"}}}}, 0.04);
    const Vec3 sand0 = poseOf(*world, "ball on the sand").position_m;
    const Vec3 rock0 = poseOf(*world, "ball on the rock").position_m;
    const Clock::time_point began = Clock::now();
    double worst = 0.0;
    for (int second = 1; second <= 10; ++second) {
        run(*world, 1.0);
        const Vec3 now = poseOf(*world, "ball on the sand").position_m;
        worst = std::max(worst, std::hypot(now.x - sand0.x, now.z - sand0.z));
    }
    const double wall_s = std::chrono::duration<double>(Clock::now() - began).count();
    const Vec3 sand1 = poseOf(*world, "ball on the sand").position_m;
    const Vec3 rock1 = poseOf(*world, "ball on the rock").position_m;
    const double rolled = std::hypot(rock1.x - rock0.x, rock1.z - rock0.z);
    const auto cell = world->environment()->terrain().cellAt(sand1.x, sand1.z);
    const double wet = cell ? world->environment()->water()->depth(*cell) : 0.0;
    std::printf("    on the sand: at most %.4f m from where it was set down over 10 s; water under it %.3f m\n",
                worst, wet);
    std::printf("    the same ball on the %s: rolled %.2f m in the same 10 s\n", rock->surface.c_str(), rolled);
    std::printf("    10 s of the valley took %.2f s: %.2fx realtime\n", wall_s, wall_s / 10.0);
    const Json said = Json::parse(world->rollingReport());
    std::printf("    rolling resistance has taken %.3f J out of the motion\n", said.at("loss_j").get<double>());
    require(worst <= 0.1, "the ball set down on the sand by the river stays within 0.1 m for 10 s");
    require(wet <= 0.0, "and dry");
    require(rolled > 0.1, "the same ball set down on a slope steeper than its atan(c) rolls");
    require(wall_s / 10.0 <= 1.1, "the valley with its balls runs inside the owner's 1.1x realtime rule");
}

} // namespace

int main(int argc, char **argv) {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"level", onTheLevelABallSlowsAtFiveSeventhsCG},
        {"energy", theEnergyItTakesIsTheEnergyTheBallLoses},
        {"ground-slope", onTheGroundABallRestsBelowAtanCAndRollsAbove},
        {"ramp", onAnAnchoredRampABallRestsJustBelowAtanCAndRollsJustAbove},
        {"normal-force", theNormalForceIsTheSolversOwn},
        {"valley", inTheValleyTheBallByTheRiverStaysOnTheSand},
    };
    const std::string_view only = argc > 1 ? std::string_view(argv[1]) : std::string_view();
    if (only == "--list") {
        for (const auto &[name, test] : tests) std::cout << name << '\n';
        return EXIT_SUCCESS;
    }
    std::size_t failures = 0, ran = 0;
    for (const auto &[name, test] : tests) {
        if (!only.empty() && only != name) continue;
        ++ran;
        const Clock::time_point began = Clock::now();
        try {
            std::cout << name << '\n';
            test();
            std::printf("[PASS] %s (%.1f s)\n", std::string(name).c_str(),
                        std::chrono::duration<double>(Clock::now() - began).count());
        } catch (const std::exception &error) {
            ++failures;
            std::printf("[FAIL] %s: %s\n", std::string(name).c_str(), error.what());
        }
        std::fflush(stdout);
    }
    std::cout << ran - failures << '/' << ran << " passed\n";
    return failures == 0 && ran > 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
