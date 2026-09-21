// Exact rigid parts that are not all axis-aligned boxes of one material.
//
// A cart's wheelset is an iron axle through two oak wheels: round parts, turned
// onto the axle, of two materials, the axle running into each wheel's hub.
// These pin what that has to mean:
//
// 1. A cylinder weighs what its material and its shape say, and turns about
//    its own axis as a solid cylinder does -- however it is turned in the body.
// 2. Where parts overlap, the matter there is counted ONCE, and belongs to the
//    part listed first: the axle's end in a hub is iron, not iron and oak.
// 3. Two boxes overlapping are one union, to the last cubic millimetre.
// 4. A body given about any origin stands at its centre of mass, measured from
//    each part's own material.
// 5. Parts that do not meet are refused -- two things apart are two bodies and
//    need a joint -- and meeting is judged by the real shapes, so a box turned
//    45 degrees touching another along an edge counts.
// 6. A wheelset rolls down a ramp as its inertia and its rolling resistance
//    say -- a = g (sin t - c cos t) / (1 + I/(m r^2)), c its wheels' share and
//    the ramp's -- in glass, oak and iron alike, turning rather than sliding.
//    On rubber (c = 0.012 with oak wheels) it holds at half a degree and rolls
//    at one, where the resistance takes two thirds of what drives it -- a test
//    that would see a law wrong by a little. On soil (c = 0.06) it holds on a
//    2 degree slope and rolls off a 6 degree one: a couple about its own axle,
//    at most c N r, that also stops the load its wheels carry.
// 7. A part meets things as its OWN material: a glass body's concrete part
//    grips a concrete floor as concrete does.
// 8. A cart of three exact bodies -- a chassis and two wheelsets, each axle
//    running through its two mounts -- turns on two free pins in a live room.
//    Set moving, it rolls: friction spins the wheels up from nothing (no spin
//    is imposed), each rim goes round at the speed the cart goes along, the
//    chassis stands on its wheels at the height it was built, and neither
//    wheelset leaves its pin. The axle inside its mounts is the bearing, held
//    by the pin rather than jammed by the contact.

#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/PreciseRigidScene.hpp"
#include "material/MaterialCatalog.hpp"
#include "rigid/JoltWorld.hpp"

#include <cmath>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <string>

using namespace banjo;
using namespace banjo::fastlattice;

namespace {

int failures = 0;
constexpr double kPi = std::numbers::pi;
constexpr double kG = 9.80665;

void require(bool ok, const std::string &why) {
    if (!ok) {
        std::cout << "[FAIL] " << why << std::endl;
        ++failures;
    }
}

bool close(double got, double want, double relative) {
    return std::abs(got - want) <= relative * std::max(std::abs(want), 1e-12);
}

double density(MaterialPreset preset) { return makeReferenceMaterial(preset).density_kg_m3; }

std::string name(MaterialPreset preset) { return std::string(materialPresetName(preset)); }

// A quarter turn about z: a part's own y (a cylinder's axis) laid along x.
const std::string kOntoX = "[0.7071067811865476, 0.0, 0.0, 0.7071067811865476]";

PreciseRigidBody one(const std::string &json) {
    const auto bodies = readPreciseRigidScene(json);
    if (bodies.size() != 1) throw std::runtime_error("expected one body");
    return bodies.front();
}

bool refused(const std::string &json, const std::string &because) {
    try {
        (void)readPreciseRigidScene(json);
    } catch (const std::invalid_argument &error) {
        if (std::string(error.what()).find(because) != std::string::npos) return true;
        std::cout << "  refused, but for: " << error.what() << "\n";
        return false;
    }
    return false;
}

void aCylinderWeighsAndTurnsAsACylinder() {
    for (MaterialPreset preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        const PreciseRigidBody wheel = one(
            R"([{"name":"wheel","material":")" + name(preset) +
            R"(","position_m":[0,1,0],"parts":[{"shape":"cylinder","dimensions_m":[0.32,0.06,0.32],)"
            R"("center_local_m":[0,0,0],"rotation_wxyz":)" + kOntoX + "}]}]");
        const double r = 0.16, length = 0.06;
        const double mass = density(preset) * kPi * r * r * length;
        std::cout << "  " << name(preset) << " wheel: " << wheel.mass_kg << " kg (" << mass << " by hand)\n";
        require(close(wheel.mass_kg, mass, 1e-12), name(preset) + ": a cylinder's mass is not density x pi r^2 L");
        // Laid along x, its own axis is the body's x.
        require(close(wheel.inertia.m[0][0], mass * r * r / 2, 1e-9),
                name(preset) + ": about its axle a wheel is not m r^2 / 2");
        require(close(wheel.inertia.m[1][1], mass * (3 * r * r + length * length) / 12, 1e-9) &&
                    close(wheel.inertia.m[2][2], mass * (3 * r * r + length * length) / 12, 1e-9),
                name(preset) + ": across a diameter a wheel is not m (3 r^2 + L^2) / 12");
        require(std::abs(wheel.inertia.m[0][1]) < 1e-12 * mass && std::abs(wheel.inertia.m[0][2]) < 1e-12 * mass,
                name(preset) + ": a wheel laid along x has products of inertia");
        require(wheel.parts.front().geometry.kind == PrimitiveKind::Cylinder, "the wheel was not kept a cylinder");
    }
}

void anAxleThroughItsWheelsIsCountedOnce() {
    // As the Workshop draws the cart: the axle first, running to the middle of
    // each wheel, so the last 30 mm at each end is inside a hub.
    const PreciseRigidBody wheelset = one(
        R"([{"name":"wheelset","material":"oak","position_m":[0,0.16,0],"parts":[)"
        R"({"shape":"cylinder","material":"iron","dimensions_m":[0.03,0.76,0.03],"center_local_m":[0,0,0],"rotation_wxyz":)" + kOntoX + "},"
        R"({"shape":"cylinder","dimensions_m":[0.32,0.06,0.32],"center_local_m":[-0.38,0,0],"rotation_wxyz":)" + kOntoX + "},"
        R"({"shape":"cylinder","dimensions_m":[0.32,0.06,0.32],"center_local_m":[0.38,0,0],"rotation_wxyz":)" + kOntoX + "}]}]");
    const double axle = kPi * 0.015 * 0.015 * 0.76, wheel = kPi * 0.16 * 0.16 * 0.06;
    const double hub = kPi * 0.015 * 0.015 * 0.03;       // the axle inside each wheel
    const double counted_twice = density(MaterialPreset::Iron) * axle + 2 * density(MaterialPreset::Oak) * wheel;
    const double once = counted_twice - 2 * density(MaterialPreset::Oak) * hub;
    std::cout << "  wheelset: " << wheelset.mass_kg << " kg; counted once by hand " << once
              << ", counted twice " << counted_twice << "\n";
    // The hubs' oak is 30 g of 45 kg; measured on its own grid it is resolved
    // to a few per cent of itself.
    require(std::abs(wheelset.mass_kg - once) < 0.03 * 2 * density(MaterialPreset::Oak) * hub,
            "the axle's ends inside the hubs were not counted once, as iron");
    require(close(wheelset.volume_m3, axle + 2 * wheel - 2 * hub, 0.001),
            "the wheelset's volume counts the hubs twice");
    require(wheelset.part_materials[0] == MaterialPreset::Iron && wheelset.part_materials[1] == MaterialPreset::Oak,
            "the axle and wheels did not keep their own materials");
    require(wheelset.parts[0].material.has_value() && !wheelset.parts[1].material.has_value(),
            "the iron axle in an oak wheelset should carry its own material, and the oak wheels not");
}

void overlappingBoxesAreOneUnion() {
    for (MaterialPreset preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        const PreciseRigidBody pair = one(
            R"([{"name":"pair","material":")" + name(preset) + R"(","position_m":[0,1,0],"parts":[)"
            R"({"dimensions_m":[0.2,0.2,0.2],"center_local_m":[0,0,0]},)"
            R"({"dimensions_m":[0.2,0.2,0.2],"center_local_m":[0.1,0,0]}]}])");
        const double want = density(preset) * 0.2 * 0.2 * 0.3;
        require(close(pair.mass_kg, want, 1e-9), name(preset) + ": two overlapping boxes are not one 300 x 200 x 200 mm union");
        // The union is a 0.3 m box: its middle is at x = 0.05 and it turns as one.
        const double ix = want * (0.2 * 0.2 + 0.2 * 0.2) / 12, iy = want * (0.3 * 0.3 + 0.2 * 0.2) / 12;
        require(close(pair.inertia.m[0][0], ix, 1e-9) && close(pair.inertia.m[1][1], iy, 1e-9),
                name(preset) + ": the union does not turn as the 300 mm box it is");
        require(close(pair.initial.center_of_mass_world_m.x, 0.05, 1e-9), name(preset) + ": the union's middle is not at x = 50 mm");
    }
}

void aBodyStandsAtItsCentreOfMass() {
    // An iron cube and an oak cube side by side, given about the iron one's
    // middle. Its centre of mass is nearly in the iron.
    const PreciseRigidBody pair = one(
        R"([{"name":"pair","material":"iron","position_m":[1,2,3],"parts":[)"
        R"({"dimensions_m":[0.1,0.1,0.1],"center_local_m":[0,0,0]},)"
        R"({"material":"oak","dimensions_m":[0.1,0.1,0.1],"center_local_m":[0.1,0,0]}]}])");
    const double iron = density(MaterialPreset::Iron), oak = density(MaterialPreset::Oak);
    const double x = 0.1 * oak / (iron + oak);
    std::cout << "  iron-and-oak pair: centre of mass " << x * 1000 << " mm into the pair from the iron cube's middle\n";
    require(close(pair.initial.center_of_mass_world_m.x, 1 + x, 1e-12) &&
                close(pair.initial.center_of_mass_world_m.y, 2, 1e-12),
            "the pair does not stand at its centre of mass");
    require(close(pair.parts[0].center_local_m.x, -x, 1e-9) && close(pair.parts[1].center_local_m.x, 0.1 - x, 1e-9),
            "the parts were not re-centred on the centre of mass");
    // About the centre of mass, the parallel-axis terms of both cubes.
    const double m_i = iron * 1e-3, m_o = oak * 1e-3, own = 0.1 * 0.1 / 6;
    const double iy = m_i * own + m_o * own + m_i * x * x + m_o * (0.1 - x) * (0.1 - x);
    require(close(pair.inertia.m[1][1], iy, 1e-9), "the pair does not turn about its centre of mass");

    // A compound given about its centre of mass, as the Workshop's install has
    // always given them, comes through exactly as before.
    const PreciseRigidBody table = one(
        R"([{"name":"table","material":"oak","position_m":[0,0.76,0],"parts":[)"
        R"({"dimensions_m":[1.2,0.04,0.7],"center_local_m":[0,0,0]}]}])");
    require(close(table.initial.center_of_mass_world_m.y, 0.76, 1e-15) && close(table.parts[0].center_local_m.x, 0, 1e-15),
            "a compound given about its centre of mass moved");
}

void partsThatDoNotMeetAreRefused() {
    const std::string apart =
        R"([{"name":"apart","material":"oak","position_m":[0,1,0],"parts":[)"
        R"({"dimensions_m":[0.1,0.1,0.1],"center_local_m":[0,0,0]},)"
        R"({"dimensions_m":[0.1,0.1,0.1],"center_local_m":[0.102,0,0]}]}])";
    require(refused(apart, "must meet"), "two cubes 2 mm apart were taken as one rigid thing");
    const std::string nearly =
        R"([{"name":"nearly","material":"oak","position_m":[0,1,0],"parts":[)"
        R"({"dimensions_m":[0.1,0.1,0.1],"center_local_m":[0,0,0]},)"
        R"({"dimensions_m":[0.1,0.1,0.1],"center_local_m":[0.1005,0,0]}]}])";
    require(readPreciseRigidScene(nearly).size() == 1, "two cubes half a millimetre apart were refused");
    // A cube turned 45 degrees about z, its edge just touching the first cube's
    // face: the real shapes meet although their boxes' corners would not say so.
    const double reach = 0.05 * std::sqrt(2.0);
    const std::string edge =
        R"([{"name":"edge","material":"oak","position_m":[0,1,0],"parts":[)"
        R"({"dimensions_m":[0.1,0.1,0.1],"center_local_m":[0,0,0]},)"
        R"({"dimensions_m":[0.1,0.1,0.1],"center_local_m":[)" + std::to_string(0.05 + reach) +
        R"(,0,0],"rotation_wxyz":[0.9238795325112867,0,0,0.3826834323650898]}]}])";
    require(readPreciseRigidScene(edge).size() == 1, "a turned cube touching along its edge was refused");
}

void malformedPartsAreRefused() {
    const std::string head = R"([{"name":"bad","material":"oak","position_m":[0,1,0],"parts":[)";
    require(refused(head + R"({"shape":"cylinder","dimensions_m":[0.3,0.06,0.2],"center_local_m":[0,0,0]}]}])",
                    "[diameter, length, diameter]"), "an oval cylinder was accepted");
    require(refused(head + R"({"shape":"sphere","dimensions_m":[0.3,0.3,0.3],"center_local_m":[0,0,0]}]}])",
                    "box or cylinder"), "an unknown part shape was accepted");
    require(refused(head + R"({"dimensions_m":[0.3,0.3,0.3],"center_local_m":[0,0,0],"rotation_wxyz":[1,0,0,0.1]}]}])",
                    "normalized"), "a rotation that is not a unit quaternion was accepted");
    require(refused(head + R"({"material":"rubber","dimensions_m":[0.3,0.3,0.3],"center_local_m":[0,0,0]}]}])",
                    "unsupported precise rigid material"), "a rubber part was accepted");
    require(refused(head + R"({"center_local_m":[0,0,0]}]}])", "needs dimensions_m"),
            "a part without dimensions was accepted");
}

// A ramp and a world to roll on it.
struct Ramp {
    JoltWorld world;
    double theta;
    explicit Ramp(double angle_rad, MaterialPreset surface = MaterialPreset::Oak) : theta(angle_rad) {
        world.setGravity({0.0, -kG, 0.0});
        RigidBoxDescription slope{};
        slope.body_id = 1;
        slope.dimensions_m = {2.0, 0.2, 8.0};
        slope.material = makeReferenceMaterial(surface);
        // Tilted about x so that it falls away towards +z.
        slope.state.orientation_world = {std::cos(theta / 2), std::sin(theta / 2), 0.0, 0.0};
        slope.state.center_of_mass_world_m = {0.0, 0.0, 0.0};
        slope.fixed = true;
        world.addBox(slope);
    }
    // Where on the slope's top surface a point `along` metres down it is,
    // raised by `above` along the slope's normal.
    [[nodiscard]] Vec3 onTop(double along, double above) const {
        const Vec3 down{0.0, -std::sin(theta), std::cos(theta)};
        const Vec3 normal{0.0, std::cos(theta), std::sin(theta)};
        return (0.1 + above) * normal + along * down;
    }
};

// A wheelset as the parser measures it: an axle through two wheels, one body.
PreciseRigidBody measuredWheelset(MaterialPreset preset) {
    return one(R"([{"name":"wheelset","material":")" + name(preset) + R"(","position_m":[0,0,0],"parts":[)"
               R"({"shape":"cylinder","dimensions_m":[0.03,0.76,0.03],"center_local_m":[0,0,0],"rotation_wxyz":)" + kOntoX + "},"
               R"({"shape":"cylinder","dimensions_m":[0.32,0.06,0.32],"center_local_m":[-0.38,0,0],"rotation_wxyz":)" + kOntoX + "},"
               R"({"shape":"cylinder","dimensions_m":[0.32,0.06,0.32],"center_local_m":[0.38,0,0],"rotation_wxyz":)" + kOntoX + "}]}]");
}

RigidCompoundDescription wheelsetBody(MatterBodyId id, const PreciseRigidBody &measured, Vec3 at) {
    RigidCompoundDescription d;
    d.body_id = id;
    d.parts = measured.parts;
    d.material = makeReferenceMaterial(measured.material);
    d.mass_kg = measured.mass_kg;
    d.inertia_local_kg_m2 = measured.inertia;
    d.state.center_of_mass_world_m = at;
    return d;
}

// What a wheelset rolling down a slope accelerates at, rolling resistance and all.
double rollingAcceleration(const PreciseRigidBody &wheels, double theta, double c) {
    const double r = 0.16;
    return kG * (std::sin(theta) - c * std::cos(theta)) / (1.0 + wheels.inertia.m[0][0] / (wheels.mass_kg * r * r));
}

void aWheelsetRollsDownARamp() {
    const double theta = 10.0 * kPi / 180.0, seconds = 1.0;
    for (MaterialPreset preset : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron}) {
        const PreciseRigidBody wheels = measuredWheelset(preset);
        Ramp ramp(theta);
        ramp.world.addCompound(wheelsetBody(2, wheels, ramp.onTop(-3.0, 0.16)));
        // Let it settle onto the slope for a moment before timing.
        for (int i = 0; i < 12; ++i) ramp.world.step(1.0 / 240.0);
        const RigidSnapshot start = ramp.world.snapshot(2);
        for (int i = 0; i < int(seconds * 240); ++i) ramp.world.step(1.0 / 240.0);
        const RigidSnapshot end = ramp.world.snapshot(2);
        const Vec3 down{0.0, -std::sin(theta), std::cos(theta)};
        const double v0 = dot(start.linear_velocity_m_s, down);
        const double travelled = dot(end.center_of_mass_world_m - start.center_of_mass_world_m, down);
        const double c = makeReferenceMaterial(preset).rolling_resistance +
                         makeReferenceMaterial(MaterialPreset::Oak).rolling_resistance;
        const double want = v0 * seconds + 0.5 * rollingAcceleration(wheels, theta, c) * seconds * seconds;
        const double speed = dot(end.linear_velocity_m_s, down), spin = end.angular_velocity_rad_s.x;
        std::cout << "  " << name(preset) << " wheelset down a 10 degree oak ramp (c = " << c << "): " << travelled
                  << " m in 1 s (" << want << " by hand), rim speed " << spin * 0.16 << " m/s for " << speed << " m/s\n";
        require(close(travelled, want, 0.02), name(preset) + ": the wheelset did not roll down as its inertia and rolling resistance say");
        require(close(spin * 0.16, speed, 0.02), name(preset) + ": the wheelset slid rather than rolled");
    }
}

// How far an oak wheelset goes in a second down a ramp of `surface` at
// `degrees`, after a quarter of a second to settle; and the law's answer.
double rollDown(double degrees, MaterialPreset surface, double &want) {
    const double theta = degrees * kPi / 180.0;
    const PreciseRigidBody wheels = measuredWheelset(MaterialPreset::Oak);
    Ramp ramp(theta, surface);
    ramp.world.addCompound(wheelsetBody(2, wheels, ramp.onTop(-3.0, 0.1605)));
    for (int i = 0; i < 60; ++i) ramp.world.step(1.0 / 240.0);
    const RigidSnapshot start = ramp.world.snapshot(2);
    for (int i = 0; i < 240; ++i) ramp.world.step(1.0 / 240.0);
    const RigidSnapshot end = ramp.world.snapshot(2);
    const Vec3 down{0.0, -std::sin(theta), std::cos(theta)};
    const double c = makeReferenceMaterial(surface).rolling_resistance +
                     makeReferenceMaterial(MaterialPreset::Oak).rolling_resistance;
    want = dot(start.linear_velocity_m_s, down) + 0.5 * std::max(0.0, rollingAcceleration(wheels, theta, c));
    return dot(end.center_of_mass_world_m - start.center_of_mass_world_m, down);
}

// The same on the valley's soil: a height field whose rolling resistance is
// the ground's own, 0.06.
double rollOnSoil(double degrees) {
    const double theta = degrees * kPi / 180.0, soil = 0.06;
    JoltWorld world;
    world.setGravity({0.0, -kG, 0.0});
    constexpr unsigned count = 17;
    constexpr double spacing = 0.25, x0 = -2.0, z0 = -2.0;
    std::vector<float> heights(count * count);
    for (unsigned j = 0; j < count; ++j)
        for (unsigned i = 0; i < count; ++i)
            heights[j * count + i] = static_cast<float>(-(z0 + j * spacing) * std::tan(theta));
    world.addGroundPatch(heights, count, spacing, x0, z0, makeReferenceMaterial(MaterialPreset::Concrete));
    world.setGroundRollingResistance([soil](double, double) { return soil; });
    const PreciseRigidBody wheels = measuredWheelset(MaterialPreset::Oak);
    const double z = -1.0, lift = 0.16 / std::cos(theta) + 0.001;
    world.addCompound(wheelsetBody(2, wheels, {0.0, -z * std::tan(theta) + lift, z}));
    for (int i = 0; i < 60; ++i) world.step(1.0 / 240.0);
    const RigidSnapshot start = world.snapshot(2);
    for (int i = 0; i < 240; ++i) world.step(1.0 / 240.0);
    const Vec3 down{0.0, -std::sin(theta), std::cos(theta)};
    return dot(world.snapshot(2).center_of_mass_world_m - start.center_of_mass_world_m, down);
}

void aWheelsetHoldsWhereItsRollingResistanceCanAndRollsWhereItCannot() {
    double want = 0.0;
    const double held = rollDown(0.5, MaterialPreset::Rubber, want);
    std::cout << "  on rubber at 0.5 degrees (tan 0.0087 under c = 0.012) the wheelset went " << held * 1000 << " mm in 1 s\n";
    require(std::abs(held) < 0.001, "a wheelset on rubber gentler than atan(c) did not hold still");
    const double rolled = rollDown(1.0, MaterialPreset::Rubber, want);
    std::cout << "  on rubber at 1 degree (tan 0.0175 over c = 0.012) it went " << rolled << " m in 1 s (" << want
              << " by hand; " << rollingAcceleration(measuredWheelset(MaterialPreset::Oak), kPi / 180.0, 0.0) * 0.5
              << " with no rolling resistance)\n";
    require(close(rolled, want, 0.05), "a wheelset on rubber steeper than atan(c) did not roll as c N r says");
    // On the valley's soil. The height field itself costs a rolling wheel
    // about 7% over a second with no rolling resistance at all -- its heights
    // are held to 2 mm, not flat -- so here the law is held to what matters in
    // the valley: a cart stays where it is put on gentle ground, and runs away
    // down steep ground.
    const double gentle = rollOnSoil(2.0), steep = rollOnSoil(6.0);
    std::cout << "  on soil (c = 0.062): " << gentle * 1000 << " mm in 1 s at 2 degrees, " << steep << " m at 6\n";
    require(std::abs(gentle) < 0.002, "a wheelset on soil gentler than atan(c) did not hold still");
    require(steep > 0.15, "a wheelset on soil steeper than atan(c) did not roll off");
}

// How far a block sliding at 2 m/s goes on a concrete floor before it stops.
double slideOnConcrete(MaterialPreset body_material, std::optional<MaterialPreset> part_material) {
    JoltWorld world;
    world.setGravity({0.0, -kG, 0.0});
    RigidBoxDescription floor{};
    floor.body_id = 1;
    floor.dimensions_m = {6.0, 0.2, 2.0};
    floor.material = makeReferenceMaterial(MaterialPreset::Concrete);
    floor.state.center_of_mass_world_m = {0.0, -0.1, 0.0};
    floor.fixed = true;
    world.addBox(floor);
    RigidCompoundPart part;
    part.geometry.kind = PrimitiveKind::Box;
    part.geometry.dimensions_m = {0.2, 0.1, 0.2};
    if (part_material) part.material = makeReferenceMaterial(*part_material);
    RigidCompoundDescription block;
    block.body_id = 2;
    block.parts = {part};
    block.material = makeReferenceMaterial(body_material);
    block.mass_kg = 5.0;
    block.inertia_local_kg_m2 = part.geometry.inertia(block.mass_kg);
    block.state.center_of_mass_world_m = {-2.0, 0.05, 0.0};
    block.state.linear_velocity_m_s = {2.0, 0.0, 0.0};
    world.addCompound(block);
    for (int i = 0; i < 2 * 240; ++i) world.step(1.0 / 240.0);
    return world.snapshot(2).center_of_mass_world_m.x + 2.0;
}

void aPartMeetsThingsAsItsOwnMaterial() {
    const double glass = slideOnConcrete(MaterialPreset::Glass, std::nullopt);
    const double concrete = slideOnConcrete(MaterialPreset::Concrete, std::nullopt);
    const double glass_with_concrete_face = slideOnConcrete(MaterialPreset::Glass, MaterialPreset::Concrete);
    std::cout << "  sliding at 2 m/s on concrete: glass stops in " << glass << " m, concrete in " << concrete
              << " m, a glass body whose part is concrete in " << glass_with_concrete_face << " m\n";
    require(close(glass_with_concrete_face, concrete, 0.02), "a concrete part did not grip as concrete");
    require(glass > 1.15 * concrete, "glass and concrete slid alike, so this test cannot tell them apart");
}

// The Workshop's cart, without its handle: a deck on four mounts, and two
// wheelsets whose axles run through the mounts' feet. In the design's own
// frame, the floor at y = 0.
std::string cartScene(const std::string &body, const std::string &axle) {
    const std::string onto_x = kOntoX;
    std::string mounts;
    for (double x : {-0.1925, 0.1925})
        for (double z : {-0.32, 0.32})
            mounts += R"(,{"dimensions_m":[0.0345,0.18,0.0345],"center_local_m":[)" + std::to_string(x) +
                      ",0.25," + std::to_string(z) + "]}";
    const auto wheelset = [&](const std::string &name, double z) {
        const std::string at = std::to_string(z);
        return R"({"name":")" + name + R"(","material":")" + body + R"(","position_m":[0,0,0],"velocity_m_s":[0,0,1],"parts":[)"
               R"({"shape":"cylinder","material":")" + axle + R"(","dimensions_m":[0.03,0.76,0.03],"center_local_m":[0,0.16,)" + at +
               R"(],"rotation_wxyz":)" + onto_x + "},"
               R"({"shape":"cylinder","dimensions_m":[0.32,0.06,0.32],"center_local_m":[-0.38,0.16,)" + at +
               R"(],"rotation_wxyz":)" + onto_x + "},"
               R"({"shape":"cylinder","dimensions_m":[0.32,0.06,0.32],"center_local_m":[0.38,0.16,)" + at +
               R"(],"rotation_wxyz":)" + onto_x + "}]}";
    };
    return R"([{"name":"chassis","material":")" + body + R"(","position_m":[0,0,0],"velocity_m_s":[0,0,1],"parts":[)"
           R"({"dimensions_m":[0.7,0.04,1.0],"center_local_m":[0,0.36,0]})" + mounts + "]}," +
           wheelset("front wheels", -0.32) + "," + wheelset("back wheels", 0.32) + "]";
}

const LiveBodyPose &posed(const std::vector<LiveBodyPose> &poses, const std::string &name) {
    for (const LiveBodyPose &pose : poses)
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

double pinAngle(LiveWorld &world, unsigned id) {
    for (const LiveJoint &joint : world.joints())
        if (joint.id == id) return joint.at;
    throw std::runtime_error("no such pin");
}

void tick(LiveWorld &world) {
    world.step(1.0 / 240.0);
    if (!world.steppedBack()) return;
    for (const std::string &name : world.breakable()) world.declineBreak(name);
}

// The cart in a room of its own. A room of exact bodies still has its
// scenery: a marker stone, well away.
TileImpactRequest cartRoom(const std::string &body, const std::string &axle) {
    TileImpactRequest request;
    request.cell_size_m = 0.05;
    request.backend = BackendKind::CpuParallel;
    SceneBody stone;
    stone.name = "marker";
    stone.shape = BodyShape::Box;
    stone.material = MaterialPreset::Concrete;
    stone.dimensions_m = {0.1, 0.1, 0.1};
    stone.center_m = {3.0, 0.05, 3.0};
    stone.anchored = true;
    request.bodies = {stone};
    request.precise_rigid_scene_json = cartScene(body, axle);
    return request;
}

// Each wheelset on a free pin through its axle.
std::pair<unsigned, unsigned> pinWheels(LiveWorld &world, const std::string &what) {
    const unsigned front = world.hinge("chassis", "front wheels", {0.0, 0.16, -0.32}, {1.0, 0.0, 0.0}, -180.0, 180.0, 0.0);
    const unsigned back = world.hinge("chassis", "back wheels", {0.0, 0.16, 0.32}, {1.0, 0.0, 0.0}, -180.0, 180.0, 0.0);
    require(front != 0 && back != 0, what + ": the wheelsets could not be pinned to the chassis");
    return {front, back};
}

void aRigidCartRollsOnItsBearings(const std::string &body, const std::string &axle) {
    const auto world = LiveWorld::open(cartRoom(body, axle));
    const auto [front, back] = pinWheels(*world, body + " cart");
    const double built_y = posed(world->poses(), "chassis").position_m.y;

    for (int i = 0; i < 240; ++i) tick(*world);          // one second to take up rolling
    double turned = 0.0, last = pinAngle(*world, front);
    const Vec3 from = posed(world->poses(), "chassis").position_m;
    for (int i = 0; i < 120; ++i) {                      // half a second measured
        tick(*world);
        const double now = pinAngle(*world, front);
        double step = now - last;
        while (step > kPi) step -= 2 * kPi;
        while (step < -kPi) step += 2 * kPi;
        turned += step;
        last = now;
    }
    const auto poses = world->poses();
    const LiveBodyPose &chassis = posed(poses, "chassis");
    const double along = chassis.position_m.z - from.z;
    const double rim = std::abs(turned) * 0.16;
    std::cout << "  " << body << " cart (" << axle << " axles): went " << along << " m in 0.5 s, its wheels' rims "
              << rim << " m; chassis at " << chassis.position_m.y << " m (built at " << built_y << ")\n";
    require(along > 0.4, body + " cart: it did not keep rolling -- jammed on its own mounts or stopped by friction");
    require(close(rim, along, 0.05), body + " cart: the wheels slid rather than rolled");
    require(std::abs(chassis.position_m.y - built_y) < 0.005, body + " cart: the chassis is not standing on its wheels as built");
    for (const char *name : {"front wheels", "back wheels"}) {
        const LiveBodyPose &wheels = posed(poses, name);
        require(std::abs(wheels.position_m.y - 0.16) < 0.005, body + " cart: a wheelset is not at its axle's height");
        const double z_off = wheels.position_m.z - chassis.position_m.z;
        require(std::abs(std::abs(z_off) - 0.32) < 0.005 && std::abs(wheels.position_m.x - chassis.position_m.x) < 0.005,
                body + " cart: a wheelset has left its pin");
    }
    for (const LiveJoint &joint : world->joints())
        require(joint.attached, body + " cart: a pin let go");
}

// b and then a, as quaternions: the turn a b.
Quat product(const Quat &a, const Quat &b) {
    return Quat{a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z, a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
                a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x, a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w};
}

// Where a part stands against the chassis, in the chassis's own frame: what
// has to be the same after the bag as before it.
struct Against {
    Vec3 at;
    Quat turn;
};
Against against(const std::vector<LiveBodyPose> &poses, const std::string &part) {
    const LiveBodyPose &c = posed(poses, "chassis"), &p = posed(poses, part);
    const Quat back{c.orientation_wxyz[0], -c.orientation_wxyz[1], -c.orientation_wxyz[2], -c.orientation_wxyz[3]};
    const Quat turn{p.orientation_wxyz[0], p.orientation_wxyz[1], p.orientation_wxyz[2], p.orientation_wxyz[3]};
    return {back.rotate(p.position_m - c.position_m), product(back, turn)};
}

// Jolt keeps a body's turn in single precision, so a part half a metre from
// the chassis is put back to within a few tenths of a micrometre: that, and
// not the double's last digit, is what "where it stood" can mean here.
constexpr double kPutBackM = 1e-6;

bool sameTurn(const Quat &a, const Quat &b) {
    return std::abs(a.w * b.w + a.x * b.x + a.y * b.y + a.z * b.z) > 1.0 - 1e-12;
}

// A cart goes in the bag as the one thing it is: taken by a wheelset, all of it
// goes, its pins with it -- in it, not come off -- and it comes back all of it,
// each part where it stood against the others, turned as it is asked, on its
// pins. And the same through a saved world.
void aRigidCartGoesInTheBagWholeAndComesBackWhole() {
    const TileImpactRequest request = cartRoom("oak", "iron");
    auto world = LiveWorld::open(request);
    pinWheels(*world, "bag");
    for (int i = 0; i < 60; ++i) tick(*world);
    const auto before = world->poses();
    std::string why;
    require(world->park("front wheels", why), "bag: the cart would not go in the bag: " + why);
    for (const LiveBodyPose &pose : world->poses())
        require(pose.name != "chassis" && pose.name != "front wheels" && pose.name != "back wheels",
                "bag: the " + pose.name + " is still in the world after the cart went in the bag");
    for (const char *name : {"chassis", "front wheels", "back wheels"})
        require(world->parked(name), std::string("bag: the ") + name + " is not set aside");
    require(world->joints().size() == 2, "bag: the cart's pins went missing");
    for (const LiveJoint &joint : world->joints())
        require(joint.attached && joint.away, "bag: a pin of the bagged cart reads as come off, not away in it");
    for (int i = 0; i < 60; ++i) tick(*world);          // the room carries on without it
    for (const LiveJoint &joint : world->joints())
        require(joint.attached && joint.away, "bag: a pin came off the cart while it was in the bag");

    // Out again by its chassis, a metre off and turned a quarter.
    const double h = std::sqrt(0.5);
    const Vec3 out{1.0, 0.8, -1.0};
    require(world->unpark("chassis", out, Quat{h, 0.0, h, 0.0}, why), "bag: the cart would not come out: " + why);
    const auto after = world->poses();
    require(length(posed(after, "chassis").position_m - out) < 1e-9, "bag: the chassis did not come out where asked");
    for (const char *name : {"front wheels", "back wheels"}) {
        const Against was = against(before, name), is = against(after, name);
        const double off = length(was.at - is.at);
        std::cout << "  the " << name << " came back " << off * 1e9 << " nm from where it stood against the chassis\n";
        require(off < kPutBackM,
                std::string("bag: the ") + name + " did not come back where it stood against the chassis");
        require(sameTurn(was.turn, is.turn), std::string("bag: the ") + name + " came back turned against the chassis");
    }
    for (const LiveJoint &joint : world->joints())
        require(joint.attached && !joint.away, "bag: a pin did not come back in the cart");
    for (int i = 0; i < 480; ++i) tick(*world);         // down onto the floor, and still on its pins
    const auto landed = world->poses();
    for (const char *name : {"front wheels", "back wheels"})
        require(length(against(before, name).at - against(landed, name).at) < 0.005,
                std::string("bag: the ") + name + " left its pin once the cart was out of the bag");
    const double lean = std::acos(std::min(1.0, 1.0 - 2.0 * (std::pow(posed(landed, "chassis").orientation_wxyz[1], 2) +
                                                            std::pow(posed(landed, "chassis").orientation_wxyz[3], 2))));
    require(lean < 0.05, "bag: the cart did not land on its wheels");

    // Through a saved world: in the bag as it is saved, in the bag as it opens,
    // and out of it whole.
    require(world->park("chassis", why), "bag: the cart would not go in the bag again: " + why);
    const std::string saved = world->snapshot(why);
    require(!saved.empty(), "bag: a world with the cart in the bag could not be saved: " + why);
    const auto again = LiveWorld::open(request, saved);
    require(again->restored().tier == "whole", "bag: the saved world did not open whole: " + again->restored().why);
    for (const char *name : {"chassis", "front wheels", "back wheels"})
        require(again->parked(name), std::string("bag: the saved world opened with the ") + name + " out of the bag");
    for (const LiveJoint &joint : again->joints())
        require(joint.attached && joint.away, "bag: the saved world opened with a pin of the bagged cart come off");
    require(again->unpark("back wheels", {-1.0, 0.8, 1.0}, Quat{1.0, 0.0, 0.0, 0.0}, why),
            "bag: the cart would not come out of the saved world's bag: " + why);
    const auto reopened = again->poses();
    for (const char *name : {"front wheels", "back wheels"})
        require(length(against(landed, name).at - against(reopened, name).at) < kPutBackM,
                std::string("bag: the ") + name + " came out of the saved world's bag somewhere else on the cart");
    for (const LiveJoint &joint : again->joints())
        require(joint.attached && !joint.away, "bag: a pin did not come back out of the saved world's bag");
    std::cout << "  the cart went in the bag whole and came back whole, and the same through a saved world\n";
}

// Tied to the room's own stone, it is not the person's to put away: refused, in
// words that say what holds it, and nothing of it moves.
void aCartTiedToTheRoomStaysOutOfTheBag() {
    const auto world = LiveWorld::open(cartRoom("oak", "oak"));
    pinWheels(*world, "tied cart");
    require(world->tie("chassis", "marker", {0.0, 0.38, 0.5}, {3.0, 0.1, 3.0}) != 0, "tied cart: the rope would not tie");
    std::string why;
    require(!world->park("back wheels", why), "tied cart: it went in the bag although it is tied to the room");
    require(why.find("the marker joined to it cannot go with it") != std::string::npos &&
                why.find("fixed in place") != std::string::npos,
            "tied cart: refused in the wrong words: " + why);
    for (const char *name : {"chassis", "front wheels", "back wheels"})
        require(!world->parked(name), std::string("tied cart: the ") + name + " was set aside all the same");
    for (const LiveJoint &joint : world->joints())
        require(joint.attached && !joint.away, "tied cart: a pin came out of the cart");
}

} // namespace

int main() {
    try {
        aCylinderWeighsAndTurnsAsACylinder();
        anAxleThroughItsWheelsIsCountedOnce();
        overlappingBoxesAreOneUnion();
        aBodyStandsAtItsCentreOfMass();
        partsThatDoNotMeetAreRefused();
        malformedPartsAreRefused();
        aWheelsetRollsDownARamp();
        aWheelsetHoldsWhereItsRollingResistanceCanAndRollsWhereItCannot();
        aPartMeetsThingsAsItsOwnMaterial();
        for (const char *material : {"glass", "oak", "iron"}) aRigidCartRollsOnItsBearings(material, material);
        aRigidCartRollsOnItsBearings("oak", "iron");        // as the Workshop builds it
        aRigidCartGoesInTheBagWholeAndComesBackWhole();
        aCartTiedToTheRoomStaysOutOfTheBag();
    } catch (const std::exception &error) {
        std::cout << "[FAIL] unexpected: " << error.what() << std::endl;
        return 1;
    }
    if (failures) {
        std::cout << failures << " failure(s)" << std::endl;
        return 1;
    }
    std::cout << "all precise rigid part checks passed" << std::endl;
    return 0;
}
