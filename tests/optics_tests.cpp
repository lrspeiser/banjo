// Light (docs/optics-checkpoint.md): rays from the sun and from lamps, followed
// through the world's own shapes, reflected, refracted and absorbed, heating
// what absorbs them and working light sensors.
//
// 1. The laws on their own: Snell's law, Fresnel's equations at normal
//    incidence and past the critical angle.
// 2. A polished aluminium plate, tilted, reflects sunlight at the angle it was
//    met, and keeps its reflectance of it; a rough one does not reflect.
// 3. A glass slab shifts a ray sideways by Snell's law and sends it on
//    parallel to where it came from, and the power out is Fresnel's and Beer
//    and Lambert's.
// 4. Light inside glass past the critical angle turns back whole.
// 5. A glass ball concentrates sunlight: the power density at its focus
//    against the open sun, and the same ray grid traced by hand through a
//    perfect sphere agrees.
// 6. What absorbs light is heated by exactly what it absorbed.
// 7. A heat lamp's beam heats an oak cord until it burns and parts.
// 8. A beam on a light sensor closes a circuit's switch; a ball that falls into
//    the beam opens it; a hand cannot work it.
// 9. The ledger closes, and a world with no light is untouched by all this.
// 10. A saved world keeps its light, its sensors, its polish and its accounts,
//     and goes on as it would have.

#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "optics/OpticalProperties.hpp"
#include "optics/RayOptics.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <memory>
#include <numbers>
#include <stdexcept>
#include <string>
#include <vector>

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

double angleBetween(const Vec3 &a, const Vec3 &b) {
    return std::acos(std::clamp(dot(normalized(a), normalized(b)), -1.0, 1.0));
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

SceneBody ball(const std::string &name, MaterialPreset material, double diameter, Vec3 centre, bool anchored) {
    SceneBody b;
    b.name = name;
    b.shape = BodyShape::Sphere;
    b.material = material;
    b.dimensions_m = {diameter, diameter, diameter};
    b.center_m = centre;
    b.anchored = anchored;
    return b;
}

std::unique_ptr<LiveWorld> open(std::vector<SceneBody> bodies) {
    TileImpactRequest request;
    request.cell_size_m = 0.02;
    request.backend = BackendKind::CpuParallel;
    request.bodies = std::move(bodies);
    return LiveWorld::open(request);
}

void tick(LiveWorld &world) {
    world.step(kDt);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

// A lamp pinned in the world at `at`, wired straight to a full store, switched
// on, with its light declared down `axis`. One step lights it (a lamp's lumens
// are what its last kept step gave it).
unsigned beam(LiveWorld &world, Vec3 at, Vec3 axis, unsigned rays, double half_angle_deg, double watts,
              double efficacy_lm_w, double radiant_efficacy_lm_w, double visible_share, const std::string &body = "",
              const std::string &store_body = "") {
    const unsigned store = world.energyStore("lamp battery", store_body, 1.0e9, 1.0e9, 230.0, 0.0);
    const unsigned lamp = world.lamp("lamp", body, 0, store, at, watts, efficacy_lm_w);
    if (store == 0 || lamp == 0 || !world.switchLamp(lamp, true)) throw std::runtime_error("the lamp would not go up");
    const unsigned light =
        world.lampLight("beam", lamp, axis, half_angle_deg, rays, radiant_efficacy_lm_w, visible_share);
    if (light == 0) throw std::runtime_error("the lamp's light would not go on");
    return light;
}

double ledgerResidual(const LiveOptics &o) { return o.watts.residual(); }

void checkLedger(const LiveOptics &o, const std::string &what) {
    const double tolerance = 1e-12 * std::max(1.0, o.watts.sent);
    std::cout << "    ledger, " << what << ": sent " << o.watts.sent << " W = heated " << o.watts.heated
              << " + warms nothing " << o.watts.unheated << " + ground " << o.watts.ground << " + escaped "
              << o.watts.escaped << " + scattered " << o.watts.scattered << " + unfollowed " << o.watts.unfollowed
              << " + bounce limit " << o.watts.bounce_limit << "; residual " << ledgerResidual(o) << " W\n";
    require(std::abs(ledgerResidual(o)) <= tolerance, what + ": the ledger does not close: " +
                                                          std::to_string(ledgerResidual(o)) + " W");
}

// ---- 1. the laws -------------------------------------------------------------

void theLawsOnTheirOwn() {
    const double n = 1.526;
    // Normal incidence: ((n - 1) / (n + 1))^2, the same both ways.
    const double r0 = std::pow((n - 1.0) / (n + 1.0), 2.0);
    require(std::abs(optics::fresnelReflectance(1.0, 1.0, n) - r0) < 1e-15, "normal incidence, air to glass");
    require(std::abs(optics::fresnelReflectance(1.0, n, 1.0) - r0) < 1e-15, "normal incidence, glass to air");
    // The critical angle, asin(1/n): just below it some gets out, just past it
    // none does.
    const double critical = std::asin(1.0 / n);
    require(optics::fresnelReflectance(std::cos(critical - 1e-6), n, 1.0) < 1.0, "just below the critical angle");
    require(optics::fresnelReflectance(std::cos(critical + 1e-6), n, 1.0) == 1.0, "just past the critical angle");
    // Snell's law, as vectors.
    const Vec3 in = normalized(Vec3{std::sin(40 * kDeg), -std::cos(40 * kDeg), 0.0});
    const optics::Refraction r = optics::refract(in, {0.0, 1.0, 0.0}, 1.0, n);
    const double sin_t = std::sqrt(r.along.x * r.along.x + r.along.z * r.along.z);
    require(!r.total && std::abs(std::sin(40 * kDeg) - n * sin_t) < 1e-14, "Snell's law");
    require(std::abs(length(r.along) - 1.0) < 1e-15, "a refracted ray is a unit vector");
    std::cout << "    laws: R(0) = " << r0 << ", critical angle " << critical / kDeg << " degrees\n";
}

// ---- 2. a mirror -------------------------------------------------------------

void aMirrorReflectsAtTheAngleItIsMet() {
    // A polished aluminium plate tilted 20 degrees about z, in a sun 50 degrees
    // up, to the east.
    auto world = open({box("mirror", MaterialPreset::Aluminum, {0.4, 0.02, 0.4}, {0.0, 0.5, 0.0}, true,
                           {0.0, 0.0, 20.0})});
    require(world->setSun(50.0, 90.0, 1000.0), "the sun would not go up");
    require(world->polish("mirror", true).empty(), "aluminium takes a polish");
    const unsigned light = world->sunlight("sun", {{{0.0, 0.5, 0.0}, {0.42, 0.2, 0.42}}}, 0.02);
    require(light != 0, "the sunlight would not go on");
    world->traceLight();
    const LiveOptics o = world->optics();
    const Vec3 normal = normalized(Vec3{-std::sin(20 * kDeg), std::cos(20 * kDeg), 0.0});
    const Vec3 in = -1.0 * world->sun().toward;
    const Vec3 want = in - 2.0 * dot(in, normal) * normal;
    double worst = 0.0, worst_balance = 0.0;
    int seen = 0;
    const double reflectance = optics::kSunVisibleShare * 0.92 + (1.0 - optics::kSunVisibleShare) * 0.93;
    for (const LiveOptics::Path &p : o.paths) {
        // In, off the mirror's face (not its edge), and away.
        if (p.points.size() != 3 || std::abs(dot(p.points[1] - Vec3{0.0, 0.5, 0.0}, normal) - 0.01) > 1e-6) continue;
        ++seen;
        const Vec3 d = p.points[1] - p.points[0], r = p.points[2] - p.points[1];
        if (angleBetween(r, want) > 1e-5 * kDeg)
            std::cout << "      off the law: in " << d.x << " " << d.y << " " << d.z << " at " << p.points[1].x << " "
                      << p.points[1].y << " " << p.points[1].z << " out " << r.x << " " << r.y << " " << r.z << "\n";
        worst = std::max(worst, angleBetween(r, want));
        // The angle out equals the angle in.
        worst_balance = std::max(worst_balance, std::abs(angleBetween(-1.0 * d, normal) - angleBetween(r, normal)));
        require(std::abs(p.power_w[1] / p.power_w[0] - reflectance) < 1e-12, "the mirror keeps its reflectance");
    }
    std::cout << "    mirror: " << seen << " drawn rays off it; the reflected ray is within " << worst / kDeg
              << " degrees of the law's, and the angles in and out differ by " << worst_balance / kDeg
              << " degrees at most\n";
    require(seen >= 10, "rays drawn off the mirror");
    // To the precision of Jolt's single-precision shapes: the tilted plate's
    // normal is a float.
    require(worst < 1e-5 * kDeg, "the reflected ray is where the law of reflection puts it");
    require(worst_balance < 1e-5 * kDeg, "the angle of reflection equals the angle of incidence");
    // The ray is in the plane of incidence: in, normal and out are coplanar.
    checkLedger(o, "mirror");
    // Rough, it reflects nothing; and it cannot be polished if it is not metal.
    require(world->polish("mirror", false).empty(), "the polish comes off");
    world->traceLight();
    int reflected = 0;
    for (const LiveOptics::Path &p : world->optics().paths) reflected += p.points.size() > 2 ? 1 : 0;
    require(reflected == 0, "a rough plate reflects nothing as a mirror");
    auto other = open({box("plank", MaterialPreset::Oak, {0.2, 0.02, 0.2}, {0.0, 0.5, 0.0}),
                       box("pane", MaterialPreset::Glass, {0.2, 0.02, 0.2}, {0.5, 0.5, 0.0})});
    require(!other->polish("plank", true).empty() && !other->polish("pane", true).empty() &&
                !other->polish("nothing", true).empty(),
            "only a metal takes a mirror polish");
}

// ---- 3. a glass slab ---------------------------------------------------------

void aGlassSlabShiftsARayBySnellsLaw() {
    const double t = 0.1, n = 1.526;
    auto world = open({box("slab", MaterialPreset::Glass, {0.6, t, 0.6}, {0.0, 0.5, 0.0})});
    require(world->setSun(50.0, 90.0, 1000.0), "the sun would not go up");
    // The rays through a small box above the middle of the slab.
    require(world->sunlight("sun", {{{0.0, 0.6, 0.0}, {0.1, 0.01, 0.1}}}, 0.01) != 0, "sunlight");
    world->traceLight();
    const LiveOptics o = world->optics();
    const double incidence = 40.0 * kDeg;
    const double inside = std::asin(std::sin(incidence) / n);
    const double shift_want = t * std::sin(incidence - inside) / std::cos(inside);
    const optics::OpticalProperties glass = optics::opticalProperties(MaterialPreset::Glass);
    const double path = t / std::cos(inside);
    const double r1 = optics::fresnelReflectance(std::cos(incidence), 1.0, n);
    const double r2 = optics::fresnelReflectance(std::cos(inside), n, 1.0);
    double worst_snell = 0.0, worst_parallel = 0.0, worst_shift = 0.0, worst_power = 0.0;
    int seen = 0;
    for (const LiveOptics::Path &p : o.paths) {
        if (p.points.size() != 4) continue;   // in, into the top, out of the bottom, to the floor
        ++seen;
        const Vec3 d = normalized(p.points[1] - p.points[0]);
        const Vec3 through = normalized(p.points[2] - p.points[1]);
        const Vec3 out = normalized(p.points[3] - p.points[2]);
        const double sin_in = std::sqrt(d.x * d.x + d.z * d.z);
        const double sin_t = std::sqrt(through.x * through.x + through.z * through.z);
        worst_snell = std::max(worst_snell, std::abs(sin_in - n * sin_t));
        worst_parallel = std::max(worst_parallel, angleBetween(out, d));
        // How far the ray out is from the line of the ray in.
        const double shift = length(cross(p.points[2] - p.points[1], d));
        worst_shift = std::max(worst_shift, std::abs(shift - shift_want));
        // What comes out: through one face, absorbed on the way, out of the
        // other, band by band.
        const double vis = optics::kSunVisibleShare * std::exp(-glass.absorption_per_m[0] * path);
        const double ir = (1.0 - optics::kSunVisibleShare) * std::exp(-glass.absorption_per_m[1] * path);
        const double want = p.power_w[0] * (1.0 - r1) * (vis + ir) * (1.0 - r2);
        worst_power = std::max(worst_power, std::abs(p.power_w[2] / want - 1.0));
    }
    std::cout << std::setprecision(10) << "    slab: " << seen << " drawn rays through it; |sin i - n sin t| <= "
              << worst_snell << "; out parallel to in within " << worst_parallel / kDeg
              << " degrees; sideways shift " << shift_want * 1000.0 << " mm by Snell's law, the engine's within "
              << worst_shift * 1e6 << " um; power out within " << worst_power << " of Fresnel and Beer-Lambert\n"
              << std::setprecision(6);
    require(seen >= 10, "rays drawn through the slab");
    require(worst_snell < 1e-6, "Snell's law at the top face");
    require(worst_parallel < 1e-5 * kDeg, "the ray leaves parallel to where it came from");
    require(worst_shift < 5e-6, "the sideways shift is Snell's");
    // To the precision of Jolt's single-precision shapes: a hundredth of a
    // micrometre on a 0.11 m path through the glass.
    require(worst_power < 1e-6, "the power out is Fresnel's and Beer-Lambert's");
    checkLedger(o, "slab");
}

// ---- 4. total internal reflection ----------------------------------------------

void pastTheCriticalAngleLightTurnsBack() {
    // A glass block 0.2 m on a side, its top at y = 0.4. A ray enters the top
    // 40 degrees from the vertical, 4 cm from the +x side: inside it runs 24.9
    // degrees from the vertical and meets that side 65.1 degrees from its
    // normal, past glass's critical angle of 40.9 degrees.
    auto world = open({box("block", MaterialPreset::Glass, {0.2, 0.2, 0.2}, {0.0, 0.3, 0.0})});
    const Vec3 along = normalized(Vec3{std::sin(40 * kDeg), -std::cos(40 * kDeg), 0.0});
    const Vec3 entry{0.06, 0.4, 0.0};
    beam(*world, entry - 0.3 * along, along, 1, 1e-6, 100.0, 120.0, 300.0, 1.0);
    tick(*world);
    world->traceLight();
    const LiveOptics o = world->optics();
    require(o.paths.size() == 1, "one ray drawn");
    if (o.paths.empty()) return;
    const LiveOptics::Path &p = o.paths.front();
    // lamp -> top -> side (turned back) -> bottom -> floor
    require(p.points.size() == 5, "the ray meets the top, the side and the bottom: " +
                                      std::to_string(p.points.size()) + " points");
    if (p.points.size() < 5) return;
    require(std::abs(p.points[2].x - 0.1) < 1e-6, "it meets the +x side");
    const Vec3 before = normalized(p.points[2] - p.points[1]), after = normalized(p.points[3] - p.points[2]);
    const double incidence = std::acos(before.x);
    const Vec3 mirrored{-before.x, before.y, before.z};
    const optics::OpticalProperties glass = optics::opticalProperties(MaterialPreset::Glass);
    const double kept = std::exp(-glass.absorption_per_m[0] * length(p.points[2] - p.points[1]));
    std::cout << "    total internal reflection: met the side " << incidence / kDeg
              << " degrees from its normal (critical " << std::asin(1.0 / 1.526) / kDeg << "); power on, "
              << p.power_w[2] << " W after " << p.power_w[1] << " W less absorption " << p.power_w[1] * (1 - kept)
              << " W\n";
    require(incidence > std::asin(1.0 / 1.526), "past the critical angle");
    require(angleBetween(after, mirrored) < 1e-5 * kDeg, "turned back by the law of reflection");
    require(std::abs(p.power_w[2] - p.power_w[1] * kept) < 1e-12 * p.power_w[1],
            "all of it turned back: nothing got out of the side");
    checkLedger(o, "total internal reflection");
}

// ---- 5. a ball lens ----------------------------------------------------------

// A ray down the y axis entering a perfect glass sphere at distance h from the
// axis: what comes out (main path only), where, and which way.
struct ThroughBall {
    double power_vis{}, power_ir{};
    double radius_at_plane{};
    bool down{};
};
ThroughBall throughBall(double h, double radius, double centre_y, double plane_y, double n, double k_vis,
                        double k_ir, double each_w) {
    ThroughBall out;
    const double a = std::asin(h / radius), b = std::asin(std::sin(a) / n);
    const double t1 = 1.0 - optics::fresnelReflectance(std::cos(a), 1.0, n);
    const double t2 = 1.0 - optics::fresnelReflectance(std::cos(b), n, 1.0);
    const double path = 2.0 * radius * std::cos(b);
    out.power_vis = each_w * optics::kSunVisibleShare * t1 * t2 * std::exp(-k_vis * path);
    out.power_ir = each_w * (1.0 - optics::kSunVisibleShare) * t1 * t2 * std::exp(-k_ir * path);
    const double deviation = 2.0 * (a - b);
    const double theta = a + kPi - 2.0 * b;     // the exit point, round from the top
    const double x = radius * std::sin(theta), y = centre_y + radius * std::cos(theta);
    const double dx = -std::sin(deviation), dy = -std::cos(deviation);
    out.down = dy < 0.0;
    if (out.down) out.radius_at_plane = std::abs(x + (plane_y - y) / dy * dx);
    return out;
}

void aGlassBallConcentratesSunlight() {
    const double d = 0.1, centre = 0.5, plane = 0.4325, spacing = 0.0015;
    const double focus_r = 0.001, open_r = 0.036;
    auto world = open({ball("lens", MaterialPreset::Glass, d, {0.0, centre, 0.0}, true),
                       box("board", MaterialPreset::Oak, {0.4, 0.02, 0.4}, {0.0, plane - 0.01, 0.0})});
    require(world->setSun(90.0, 0.0, 1000.0), "the sun would not go up");
    require(world->photocell("focus", "board", {0.0, plane, 0.0}, {0.0, 1.0, 0.0}, kPi * focus_r * focus_r) != 0,
            "the sensor at the focus");
    require(world->photocell("open", "board", {0.12, plane, 0.12}, {0.0, 1.0, 0.0}, kPi * open_r * open_r) != 0,
            "the sensor in the open sun");
    const unsigned light = world->sunlight(
        "sun", {{{0.0, centre, 0.0}, {d, d, d}}, {{0.12, plane + 0.01, 0.12}, {0.08, 0.01, 0.08}}}, spacing);
    require(light != 0, "the sunlight would not go on");
    world->traceLight();
    const LiveOptics o = world->optics();
    double focus_w = 0.0, open_w = 0.0;
    for (const LivePhotocell &cell : world->photocells())
        (cell.name == "focus" ? focus_w : open_w) = cell.power_w;
    const double open_density = open_w / (kPi * open_r * open_r);
    const double focus_density = focus_w / (kPi * focus_r * focus_r);
    // The same grid of rays, through a perfect sphere by hand.
    const optics::OpticalProperties glass = optics::opticalProperties(MaterialPreset::Glass);
    const double each = 1000.0 * spacing * spacing;
    double by_hand = 0.0, through = 0.0;
    const int reach = static_cast<int>(std::ceil(0.5 * d / spacing)) + 1;
    for (int i = -reach; i <= reach; ++i)
        for (int j = -reach; j <= reach; ++j) {
            const double x = (i + 0.5) * spacing, z = (j + 0.5) * spacing, h = std::hypot(x, z);
            if (h >= 0.5 * d) continue;
            const ThroughBall t = throughBall(h, 0.5 * d, centre, plane, glass.refractive_index,
                                              glass.absorption_per_m[0], glass.absorption_per_m[1], each);
            through += t.power_vis + t.power_ir;
            if (t.down && t.radius_at_plane <= focus_r) by_hand += t.power_vis + t.power_ir;
        }
    double ball_absorbed = 0.0;
    for (const LiveOptics::Lit &b : o.bodies)
        if (b.body == "lens") ball_absorbed = b.absorbed_w;
    std::cout << "    ball lens, 100 mm glass in a 1000 W/m2 sun: " << o.rays << " rays, " << o.casts
              << " casts in " << o.last_trace_ms << " ms. Open sun measured " << open_density
              << " W/m2; at the focus, 67.5 mm below the ball's centre, " << focus_w * 1000.0 << " mW in a 1 mm "
              << "radius: " << focus_density << " W/m2, " << focus_density / open_density << " times the open sun. "
              << "By hand through a perfect sphere: " << by_hand * 1000.0 << " mW. The ball passes "
              << through << " W of the " << 1000.0 * kPi * 0.25 * d * d << " W on it and absorbs "
              << ball_absorbed << " W\n";
    require(std::abs(open_density / 1000.0 - 1.0) < 0.02, "the open sun is what the sun gives");
    require(focus_density / open_density > 50.0, "the ball concentrates sunlight");
    require(std::abs(focus_w / by_hand - 1.0) < 0.02, "the engine's focus is the perfect sphere's");
    checkLedger(o, "ball lens");
}

// ---- 6. light heats what absorbs it ------------------------------------------

void whatAbsorbsLightIsHeatedByIt() {
    auto world = open({box("board", MaterialPreset::Oak, {0.3, 0.02, 0.3}, {0.0, 0.5, 0.0})});
    require(world->setSun(90.0, 0.0, 1000.0), "the sun would not go up");
    require(world->sunlight("sun", {{{0.0, 0.5, 0.0}, {0.3, 0.04, 0.3}}}, 0.01) != 0, "sunlight");
    for (int i = 0; i < 240; ++i) tick(*world);
    const LiveOptics o = world->optics();
    const auto heat = nlohmann::json::parse(world->thermoReport(false));
    const double heater_j = heat.at("ledger").at("heater_in_j").get<double>();
    double board_w = 0.0, board_j = 0.0;
    for (const LiveOptics::Lit &b : o.bodies)
        if (b.body == "board") board_w = b.absorbed_w, board_j = b.absorbed_j;
    std::cout << "    a 0.3 m oak board square to the sun: absorbs " << board_w << " W (half of the "
              << 1000.0 * 0.09 << " W on it); in 1 s the heat network took " << heater_j << " J and light gave "
              << o.joules.heated << " J; its ledger residual " << heat.at("ledger").at("residual_j") << " J\n";
    require(std::abs(board_w - 0.5 * 90.0) < 1e-9, "a rough oak board absorbs half the sunlight on it");
    require(std::abs(heater_j - o.joules.heated) < 1e-9 * heater_j, "the heat network took what light gave");
    require(std::abs(board_j - o.joules.heated) < 1e-9 * board_j, "and that is what the board absorbed");
    const double residual_j = o.joules.residual();
    require(std::abs(residual_j) < 1e-9 * o.joules.sent, "the joule ledger closes");

    // An exact rigid body (a precise compound) absorbs too, but the heat
    // network cannot hold one: what it absorbs is counted as warming nothing,
    // and the network is not handed it.
    TileImpactRequest request;
    request.cell_size_m = 0.02;
    request.backend = BackendKind::CpuParallel;
    request.bodies = {box("board", MaterialPreset::Oak, {0.3, 0.02, 0.3}, {0.0, 0.5, 0.0})};
    request.precise_rigid_scene_json =
        nlohmann::json::array({{{"name", "exact board"}, {"material", "oak"}, {"position_m", {1.0, 0.011, 0.0}},
                                {"parts", nlohmann::json::array({{{"name", "plank"},
                                                                  {"dimensions_m", {0.3, 0.02, 0.3}},
                                                                  {"center_local_m", {0.0, 0.0, 0.0}}}})}}})
            .dump();
    auto mixed = LiveWorld::open(request);
    require(mixed->setSun(90.0, 0.0, 1000.0), "the sun would not go up");
    require(mixed->sunlight("sun", {{{0.0, 0.5, 0.0}, {0.3, 0.04, 0.3}}, {{1.0, 0.03, 0.0}, {0.3, 0.06, 0.3}}}, 0.01) != 0,
            "sunlight on both");
    for (int i = 0; i < 240; ++i) tick(*mixed);
    const LiveOptics m = mixed->optics();
    const double mixed_heater_j =
        nlohmann::json::parse(mixed->thermoReport(false)).at("ledger").at("heater_in_j").get<double>();
    std::cout << "    beside it an exact oak board absorbs " << m.watts.unheated << " W that warms nothing; the heat "
              << "network took " << mixed_heater_j << " J, all of it the ordinary board's\n";
    require(std::abs(m.watts.unheated - 45.0) < 1e-6, "the exact board absorbs half its sunlight, warming nothing");
    require(std::abs(mixed_heater_j - m.joules.heated) < 1e-9 * mixed_heater_j &&
                std::abs(m.joules.heated - 45.0) < 1e-6,
            "and only the ordinary board's light reaches the heat network");
    require(std::abs(m.joules.residual()) < 1e-9 * m.joules.sent, "the joule ledger closes");
}

// ---- 7. a heat lamp burns an oak cord ------------------------------------------

void aHeatLampBurnsAnOakCord() {
    // An oak cord 20 x 20 x 100 mm hangs from a fixed arm and carries a 32 kg
    // iron weight; the fixing is made of the cord, so as heat weakens the cord
    // what it can hold falls. A 2 kW filament heat lamp 25 cm away shines on it.
    auto world = open({box("arm", MaterialPreset::Concrete, {0.2, 0.04, 0.06}, {0.0, 1.02, 0.0}),
                       box("cord", MaterialPreset::Oak, {0.02, 0.1, 0.02}, {0.0, 0.945, 0.0}, false),
                       box("weight", MaterialPreset::Iron, {0.16, 0.16, 0.16}, {0.0, 0.81, 0.0}, false)});
    const unsigned top = world->fix("arm", "cord", {0.0, 0.995, 0.0}, {0.0, 1.0, 0.0}, 800.0, 800.0);
    const unsigned hook = world->fix("cord", "weight", {0.0, 0.895, 0.0}, {0.0, 1.0, 0.0});
    require(top != 0 && hook != 0 && world->setJointMember(top, "cord"), "the cord would not hang");
    // A filament heat lamp: 2 kW at 15 lumens a watt; a filament's light carries
    // about 17 lumens a radiant watt, a tenth of it visible.
    beam(*world, {-0.25, 0.945, 0.0}, {1.0, 0.0, 0.0}, 256, 3.0, 2000.0, 15.0, 17.0, 0.1);
    bool parted = false;
    double parted_at = 0.0, hottest = 0.0;
    std::string why;
    for (int i = 0; i < 60 * 240 && !parted; ++i) {
        tick(*world);
        for (const LiveJoint &j : world->joints())
            if (j.id == top && !j.attached) {
                parted = true;
                parted_at = (i + 1) * kDt;
            }
    }
    const LiveOptics o = world->optics();
    double cord_w = 0.0;
    for (const LiveOptics::Lit &b : o.bodies)
        if (b.body == "cord") cord_w = b.absorbed_w;
    const auto heat = nlohmann::json::parse(world->thermoReport(false));
    bool burned = false;
    for (const auto &b : heat.at("bodies"))
        if (b.at("name") == "cord") {
            hottest = b.value("temperature_k", 0.0);
            burned = b.value("reacting", false);
        }
    std::cout << "    heat lamp: " << o.watts.sent << " W of light, the cord absorbing " << cord_w
              << " W; it parted at " << parted_at << " s, its surface " << hottest << " K"
              << (burned ? ", burning" : "") << "; " << o.traces << " traces, " << o.trace_ms / o.traces
              << " ms each\n";
    require(parted, "the heat lamp's light burns through the cord");
    require(burned, "and the cord is burning");
    checkLedger(o, "heat lamp");
}

// ---- 8. a light sensor works a switch ------------------------------------------

nlohmann::json lightNetwork(unsigned store) {
    return {{"schema", "banjo.circuit.v1"}, {"id", "eye"}, {"nodes", {"p", "n", "in"}},
            {"source", {{"store", store}, {"positive", "p"}, {"negative", "n"}, {"resistance_ohm", 0.05},
                        {"thermal", "pack"}}},
            {"thermal_nodes", {{{"id", "pack"}, {"component", "battery"}, {"capacity_j_k", 500.0}}}},
            {"branches", {{{"id", "eye switch"}, {"kind", "switch"}, {"component", "switch"}, {"a", "p"},
                           {"b", "in"}, {"thermal", "pack"}, {"resistance_ohm", 0.001}, {"closed", false},
                           {"follows_light", {{"sensor", "eye"}, {"closed_at_or_above_w", 2.0}}}},
                          {{"id", "bell"}, {"kind", "resistor"}, {"component", "bell"}, {"a", "in"}, {"b", "n"},
                           {"thermal", "pack"}, {"resistance_ohm", 10.0}}}}};
}

bool switchClosed(const LiveWorld &world) {
    const auto c = nlohmann::json::parse(world.circuits())[0];
    return c.at("branches")[0].at("closed").get<bool>();
}

void aBeamWorksASwitchAndAFallingBallBreaksIt() {
    // A lamp's narrow beam crosses 2 m at 0.5 m up to a sensor on a post. A
    // 0.16 m iron ball falls from 1.2 m onto a block whose top is at 0.42 m,
    // where it sits in the beam.
    auto world = open({box("post", MaterialPreset::Concrete, {0.1, 0.8, 0.1}, {1.05, 0.4, 0.0}),
                       box("block", MaterialPreset::Concrete, {0.12, 0.42, 0.12}, {0.0, 0.21, 0.0}),
                       ball("ball", MaterialPreset::Iron, 0.16, {0.0, 1.2, 0.0}, false)});
    beam(*world, {-1.0, 0.5, 0.0}, {1.0, 0.0, 0.0}, 64, 1.0, 10.0, 120.0, 300.0, 1.0);
    require(world->photocell("eye", "post", {1.0, 0.5, 0.0}, {-1.0, 0.0, 0.0}, kPi * 0.06 * 0.06) != 0,
            "the sensor");
    const unsigned store = world->energyStore("bell battery", "post", 1.0e5, 1.0e5, 12.0, 0.0);
    require(world->circuit(lightNetwork(store).dump()) != 0, "the circuit");
    bool threw = false;
    try {
        world->circuitSwitch(1, "eye switch", true);
    } catch (const std::invalid_argument &) {
        threw = true;
    }
    require(threw, "a hand cannot work a switch the light works");
    double closed_at = -1.0, opened_at = -1.0, ball_in_beam_at = -1.0;
    for (int i = 0; i < 2 * 240; ++i) {
        tick(*world);
        const double t = (i + 1) * kDt;
        const bool closed = switchClosed(*world);
        if (closed && closed_at < 0.0) closed_at = t;
        if (!closed && closed_at >= 0.0 && opened_at < 0.0) opened_at = t;
        for (const LiveBodyPose &b : world->poses())
            if (b.name == "ball" && b.position_m.y - 0.08 < 0.5 + 0.02 && ball_in_beam_at < 0.0) ball_in_beam_at = t;
    }
    double eye_w = 0.0;
    for (const LivePhotocell &cell : world->photocells()) eye_w = cell.power_w;
    const auto c = nlohmann::json::parse(world->circuits())[0];
    std::cout << "    light switch: closed at " << closed_at << " s by the beam; the ball reached the beam at "
              << ball_in_beam_at << " s and the switch opened at " << opened_at << " s; the sensor reads "
              << eye_w << " W with the ball in the beam, and the switch is "
              << (switchClosed(*world) ? "closed" : "open") << "\n";
    require(closed_at > 0.0 && closed_at <= 2.0 * kDt, "the beam closes the switch at once");
    require(opened_at > 0.0, "the ball in the beam opens it");
    require(opened_at - ball_in_beam_at <= 8.0 * kDt && opened_at >= ball_in_beam_at,
            "within a trace stride of the ball reaching the beam");
    require(!switchClosed(*world), "and it stays open while the ball sits in the beam");
    require(c.at("ledger").at("source_j").get<double>() > 0.0, "current flowed while it was closed");
    checkLedger(world->optics(), "light switch");
}

// ---- 10. a saved world keeps its light ---------------------------------------------

std::vector<SceneBody> periscope() {
    // A lamp's beam along +x meets a polished aluminium plate turned 45 degrees,
    // which sends it straight up to a sensor under a slab.
    return {box("mirror", MaterialPreset::Aluminum, {0.2, 0.02, 0.2}, {0.0, 0.5, 0.0}, true, {0.0, 0.0, 45.0}),
            box("slab", MaterialPreset::Concrete, {0.4, 0.04, 0.4}, {0.0, 1.2, 0.0})};
}

void aSavedWorldKeepsItsLight() {
    auto world = open(periscope());
    require(world->polish("mirror", true).empty(), "polish");
    beam(*world, {-1.0, 0.5, 0.0}, {1.0, 0.0, 0.0}, 32, 1.0, 10.0, 120.0, 300.0, 1.0);
    require(world->photocell("eye", "slab", {0.0, 1.18, 0.0}, {0.0, -1.0, 0.0}, kPi * 0.06 * 0.06) != 0, "sensor");
    const unsigned store = world->energyStore("bell battery", "slab", 1.0e5, 1.0e5, 12.0, 0.0);
    require(world->circuit(lightNetwork(store).dump()) != 0, "circuit");
    for (int i = 0; i < 60; ++i) tick(*world);
    std::string why;
    const std::string saved = world->snapshot(why);
    require(!saved.empty(), "the world would not save: " + why);
    if (saved.empty()) return;
    auto again = LiveWorld::open(TileImpactRequest{[] {
                                     TileImpactRequest r;
                                     r.cell_size_m = 0.02;
                                     r.backend = BackendKind::CpuParallel;
                                     r.bodies = periscope();
                                     return r;
                                 }()},
                                 saved);
    require(again->restored().tier == "whole", "the world did not come back whole: " + again->restored().why);
    require(again->lights().size() == 1 && again->photocells().size() == 1 && again->polished("mirror"),
            "its light, sensor and polish came back");
    require(again->optics().joules.sent == world->optics().joules.sent &&
                again->photocells()[0].received_j == world->photocells()[0].received_j,
            "and its accounts");
    for (int i = 0; i < 60; ++i) {
        tick(*world);
        tick(*again);
    }
    const LiveOptics a = world->optics(), b = again->optics();
    std::cout << "    saved and opened again: the sensor read " << world->photocells()[0].power_w << " W and "
              << again->photocells()[0].power_w << " W; light sent " << a.joules.sent << " J and " << b.joules.sent
              << " J; switch " << (switchClosed(*world) ? "closed" : "open") << " and "
              << (switchClosed(*again) ? "closed" : "open") << "\n";
    require(std::abs(a.joules.sent - b.joules.sent) <= 1e-12 * a.joules.sent &&
                std::abs(a.joules.heated - b.joules.heated) <= 1e-9 * std::max(1.0, a.joules.heated) &&
                std::abs(world->photocells()[0].received_j - again->photocells()[0].received_j) <=
                    1e-9 * world->photocells()[0].received_j,
            "opened again, its light goes on as it would have");
    require(world->photocells()[0].power_w > 2.0 && switchClosed(*again), "the mirror sends the beam to the sensor");
    checkLedger(b, "opened again");
}

// ---- 9. untouched without light --------------------------------------------------

void aWorldWithoutLightIsUntouched() {
    const auto scene = [] {
        return std::vector<SceneBody>{box("ramp", MaterialPreset::Oak, {0.6, 0.04, 0.2}, {0.0, 0.3, 0.0}, true,
                                          {0.0, 0.0, -15.0}),
                                      ball("marble", MaterialPreset::Iron, 0.06, {0.2, 0.5, 0.0}, false),
                                      box("block", MaterialPreset::Oak, {0.1, 0.1, 0.1}, {-0.5, 0.05, 0.0}, false)};
    };
    auto plain = open(scene());
    auto watched = open(scene());
    // A sensor and a lamp's light whose lamp is switched off: light is
    // declared, traced each stride, and sends nothing.
    require(watched->photocell("eye", "block", {-0.45, 0.05, 0.0}, {1.0, 0.0, 0.0}, 0.001) != 0, "sensor");
    const unsigned store = watched->energyStore("cell", "", 1.0e3, 1.0e3, 12.0, 0.0);
    const unsigned lamp = watched->lamp("lamp", "", 0, store, {1.0, 0.5, 0.0}, 5.0, 100.0);
    require(watched->lampLight("beam", lamp, {-1.0, 0.0, 0.0}, 10.0, 64, 300.0, 1.0) != 0, "light");
    double plain_s = 0.0, watched_s = 0.0;
    for (int i = 0; i < 480; ++i) {
        auto t0 = std::chrono::steady_clock::now();
        tick(*plain);
        auto t1 = std::chrono::steady_clock::now();
        tick(*watched);
        auto t2 = std::chrono::steady_clock::now();
        plain_s += std::chrono::duration<double>(t1 - t0).count();
        watched_s += std::chrono::duration<double>(t2 - t1).count();
    }
    const auto a = plain->poses(), b = watched->poses();
    bool same = a.size() == b.size();
    for (std::size_t i = 0; same && i < a.size(); ++i)
        same = a[i].position_m.x == b[i].position_m.x && a[i].position_m.y == b[i].position_m.y &&
               a[i].position_m.z == b[i].position_m.z && a[i].velocity_m_s.x == b[i].velocity_m_s.x &&
               a[i].velocity_m_s.y == b[i].velocity_m_s.y && a[i].velocity_m_s.z == b[i].velocity_m_s.z;
    std::cout << "    untouched: 2 s with and without light declared, every body the same to the last bit: "
              << (same ? "yes" : "NO") << "; " << plain_s * 1000.0 / 480 << " ms a step without, "
              << watched_s * 1000.0 / 480 << " ms with (" << watched->optics().traces << " traces)\n";
    require(same, "declaring light that sends nothing changes nothing");
    require(plain->optics().traces == 0 && !plain->optics().declared, "a world with no light never traces");
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
    run("the laws on their own", theLawsOnTheirOwn);
    run("a mirror reflects at the angle it is met", aMirrorReflectsAtTheAngleItIsMet);
    run("a glass slab shifts a ray by Snell's law", aGlassSlabShiftsARayBySnellsLaw);
    run("past the critical angle light turns back", pastTheCriticalAngleLightTurnsBack);
    run("a glass ball concentrates sunlight", aGlassBallConcentratesSunlight);
    run("what absorbs light is heated by it", whatAbsorbsLightIsHeatedByIt);
    run("a heat lamp burns an oak cord", aHeatLampBurnsAnOakCord);
    run("a beam works a switch and a falling ball breaks it", aBeamWorksASwitchAndAFallingBallBreaksIt);
    run("a saved world keeps its light", aSavedWorldKeepsItsLight);
    run("a world without light is untouched", aWorldWithoutLightIsUntouched);
    if (failures) {
        std::cout << failures << " failure(s)\n";
        return 1;
    }
    std::cout << "all optics tests passed\n";
    return 0;
}
