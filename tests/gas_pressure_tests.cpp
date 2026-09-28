// Three machines that all work the same way: something makes gas fast inside a
// region, the gas presses on what bounds it, and the pressing does work.
//
//   a steam engine   water boils, the steam lifts a piston and its load
//   a cannon         a charge burns, the gas throws the ball down the barrel
//   a rocket         a charge burns, the gas leaves through a nozzle and the
//                    thrust of it pushes the vessel the other way
//
// The point of putting them in one file is that there is one mechanism here,
// not three. The steam engine and the cannon differ only in what fills the
// region and how fast; the rocket differs only in that its boundary is an
// opening rather than a piston.
//
// The mechanics is a one-dimensional stand-in, as in tests/thermochemistry_
// tests.cpp: this pins what the thermochemical network promises a mechanics,
// not what Jolt does with it.
#include "thermo/ThermoWorld.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::thermo;

constexpr double kBoilingK = 373.15;
// The latent heat of vaporisation everyone quotes, which is the ENTHALPY one:
// what boiling costs when the steam is pushed out against a pressure.
constexpr double kVaporisationJKg = 2.257e6;

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance) {
        throw std::runtime_error(std::string(message) + ": actual=" + std::to_string(actual) +
                                 " expected=" + std::to_string(expected) +
                                 " tolerance=" + std::to_string(tolerance));
    }
}

BodyShape box(std::string name, std::string material, Vec3 center, Vec3 size, double density) {
    BodyShape shape;
    shape.name = std::move(name);
    shape.material = std::move(material);
    shape.center_m = center;
    shape.half_extent_m = size * 0.5;
    shape.volume_m3 = size.x * size.y * size.z;
    shape.area_m2 = 2.0 * (size.x * size.y + size.y * size.z + size.x * size.z);
    shape.mass_kg = density * shape.volume_m3;
    return shape;
}

BodyHeat heatOf(const std::vector<BodyHeat> &all, const std::string &name) {
    for (const BodyHeat &b : all)
        if (b.body == name) return b;
    throw std::runtime_error("no thermal state for " + name);
}

double heldInRegion(const RegionState &region, const std::string &substance) {
    for (const auto &[id, kg] : region.contents_kg)
        if (id == substance) return kg;
    return 0.0;
}

double relativeResidual(const Ledger &l) {
    return std::abs(l.residualJ()) / std::max(1.0, std::abs(l.storedJ()));
}

void run(ThermoWorld &world, double seconds, double dt) {
    const int steps = static_cast<int>(std::lround(seconds / dt));
    for (int i = 0; i < steps; ++i) world.advance(dt, {});
}

// ---------------------------------------------------------------------------
// What boiling costs, on its own, with nothing else going on

// A pan of water already at its boiling point, in surroundings AT its boiling
// point so that not one joule leaves by any other road, with the steam going to
// the open air. Every joule the heater puts in then goes into boiling, and the
// kilogram it boils has to cost the handbook's 2.257 MJ -- not the 2.085 MJ of
// latent heat that the two substances' internal energies are apart, because the
// steam has to push the air out of the way to leave.
void boilingCostsTheLatentHeatOfVaporisation() {
    ThermoWorld world;
    Ambient hot;
    hot.temperature_k = kBoilingK;
    hot.floor_conductance_w_m2_k = 0.0;
    world.setAmbient(hot);
    world.refresh({box("pan", "none", {0, 0.05, 0}, {0.2, 0.05, 0.2}, 1000.0)}, 0.0);
    world.declareContents({"pan", {{"water", 1.0}}, kBoilingK, 0.0, ""});
    const double held = heatOf(world.bodies(), "pan").mass_kg;
    constexpr double kWatts = 2000.0;
    constexpr double kSeconds = 30.0;
    world.heat({"pan", kWatts, 0.0, kSeconds, "ring"});
    run(world, kSeconds, 1.0 / 240.0);

    const BodyHeat pan = heatOf(world.bodies(), "pan");
    const Ledger ledger = world.ledger();
    near(pan.temperature_k, kBoilingK, 1.0e-6, "boiling, the water holds at its boiling point");
    require(pan.boiled_kg > 0.0, "some of it boiled away");
    near(ledger.heater_in_j, kWatts * kSeconds, 1.0e-6 * kWatts * kSeconds, "the ring put in what it said");
    const double cost = ledger.heater_in_j / pan.boiled_kg;
    std::cout << "    boiled " << pan.boiled_kg << " kg of " << held << " kg, at " << cost / 1.0e6
              << " MJ/kg\n";
    near(cost, kVaporisationJKg, 1.0e-3 * kVaporisationJKg,
         "a kilogram of steam cost the latent heat of vaporisation");
    near(ledger.heat_to_surroundings_j, 0.0, 1.0e-9,
         "and nothing leaked away: the surroundings were at the same temperature");
    require(relativeResidual(ledger) < 1.0e-12, "the ledger closes");
}

// Driven four times as hard it boils four times as fast and still reads 100 C.
// This is the whole reason boiling cannot be a reaction: a rate would let the
// water climb.
void aKettleHoldsAtItsBoilingPointHoweverHardItIsDriven() {
    const auto boilAt = [](double watts) {
        ThermoWorld world;
        Ambient hot;
        hot.temperature_k = kBoilingK;
        hot.floor_conductance_w_m2_k = 0.0;
        world.setAmbient(hot);
        world.refresh({box("kettle", "none", {0, 0.05, 0}, {0.2, 0.05, 0.2}, 1000.0)}, 0.0);
        world.declareContents({"kettle", {{"water", 1.0}}, kBoilingK, 0.0, ""});
        world.heat({"kettle", watts, 0.0, 20.0, "ring"});
        run(world, 20.0, 1.0 / 240.0);
        return heatOf(world.bodies(), "kettle");
    };
    const BodyHeat gentle = boilAt(1000.0);
    const BodyHeat fierce = boilAt(4000.0);
    near(gentle.temperature_k, kBoilingK, 1.0e-6, "gently boiled, it reads its boiling point");
    near(fierce.temperature_k, kBoilingK, 1.0e-6, "fiercely boiled, it reads the same");
    near(fierce.boiled_kg / gentle.boiled_kg, 4.0, 0.01,
         "four times the heat boiled four times the water");
}

// ---------------------------------------------------------------------------
// A steam engine

// Water boiling into a cylinder whose piston carries a load. The steam is made
// by the water; the volume it needs is taken by lifting the load; the work the
// gas pays is the work the mechanics receives, to the last joule.
struct Engine {
    ThermoWorld world;
    double y{}, v{}, y0{}, mass{}, work{};
    Engine() {
        const BodyShape piston = box("piston", "iron", {0, 0.52, 0}, {0.24, 0.08, 0.24}, 7870.0);
        const BodyShape load = box("load", "iron", {0, 0.64, 0}, {0.16, 0.16, 0.16}, 7870.0);
        // The boiler water sits in the cylinder and boils into it.
        const BodyShape water = box("boiler water", "none", {0, 0.1, 0}, {0.2, 0.04, 0.2}, 1000.0);
        Ambient still;
        still.floor_conductance_w_m2_k = 0.0;
        world.setAmbient(still);
        world.refresh({piston, load, water}, 0.0);
        GasRegionDeclaration cylinder;
        cylinder.name = "cylinder";
        cylinder.mass_fraction = {{"nitrogen", 1.0}};
        cylinder.piston = "piston";
        cylinder.height_m = 0.4;
        cylinder.balance = true;
        world.declareGasRegion(cylinder);
        world.declareContents({"boiler water", {{"water", 1.0}}, kBoilingK, 0.0, "cylinder"});
        world.heat({"boiler water", 4000.0, 0.0, 40.0, "firebox"});
        y = y0 = piston.center_m.y;
        mass = piston.mass_kg + load.mass_kg;
    }
    void step(double dt) {
        const std::vector<Push> pushes = world.pushes();
        double force = 0.0;
        for (const Push &push : pushes)
            if (push.body == "piston") force = push.force_n.y;
        v += (force / mass - 9.80665) * dt;
        const double dy = v * dt;
        y += dy;
        work += force * dy;
        world.advance(dt, {{"piston", {0.0, dy, 0.0}}});
    }
    void run(double seconds, double dt) {
        const int steps = static_cast<int>(std::lround(seconds / dt));
        for (int i = 0; i < steps; ++i) step(dt);
    }
};

void aSteamEngineLiftsItsLoad() {
    Engine engine;
    const RegionState before = engine.world.regions().front();
    const double water_before = heatOf(engine.world.bodies(), "boiler water").mass_kg;
    engine.run(40.0, 1.0 / 240.0);
    const RegionState after = engine.world.regions().front();
    const BodyHeat water = heatOf(engine.world.bodies(), "boiler water");
    const Ledger ledger = engine.world.ledger();

    const double lift = engine.y - engine.y0;
    std::cout << "    boiled " << water.boiled_kg << " kg of water and lifted " << engine.mass
              << " kg by " << lift << " m, doing " << engine.work << " J\n";
    require(water.boiled_kg > 0.0, "the boiler boiled");
    near(water.mass_kg, water_before - water.boiled_kg, 1.0e-9 * water_before,
         "the water it lost is the steam it made");
    require(heldInRegion(after, "water vapour") > 0.0, "the cylinder holds steam");
    near(heldInRegion(after, "water vapour"), water.boiled_kg, 1.0e-9 * water.boiled_kg,
         "and holds exactly the steam the water made: nothing went anywhere else");
    // A tenth of a millikelvin: the water is losing heat to the steam above it
    // between one boiling step and the next, so it rides just under.
    near(water.temperature_k, kBoilingK, 1.0e-3, "boiling, the water holds at its boiling point");
    require(lift > 0.1, "the load went up");
    require(after.volume_m3 > before.volume_m3, "the cylinder grew to take the steam");
    near(ledger.work_to_bodies_j, engine.work, 1.0e-9 * std::abs(engine.work),
         "the gas paid exactly the work the mechanics received");
    require(relativeResidual(ledger) < 1.0e-10,
            "the ledger closes: " + std::to_string(ledger.residualJ()));
}

// ---------------------------------------------------------------------------
// A cannon

// A charge of propellant behind a ball in a barrel. The propellant carries its
// own oxidiser, so it does not need air and burns just as well sealed in; the
// gas it makes has nowhere to go but against the ball.
struct Cannon {
    ThermoWorld world;
    double x{}, v{}, mass{}, work{};
    double barrel_m{1.2};
    double bore_m2{};
    bool left{};
    double muzzle_v{};
    explicit Cannon(double charge_kg) {
        // A 50 mm bore. The ball is iron and fills it.
        constexpr double kBore = 0.05;
        bore_m2 = 0.25 * 3.14159265358979323846 * kBore * kBore;
        const BodyShape ball = box("ball", "iron", {0, 1.0, 0}, {kBore, kBore, kBore}, 7870.0);
        // The charge, at a temperature where it is already going: a primer's
        // job, which this model does not have, is to get it there.
        const double side = std::cbrt(charge_kg / 1700.0);
        const BodyShape charge = box("charge", "none", {-0.2, 1.0, 0}, {side, side, side}, 1700.0);
        Ambient still;
        still.floor_conductance_w_m2_k = 0.0;
        world.setAmbient(still);
        world.refresh({ball, charge}, 0.0);
        GasRegionDeclaration barrel;
        barrel.name = "barrel";
        barrel.mass_fraction = {{"nitrogen", 1.0}};
        barrel.pressure_pa = 101325.0;
        barrel.volume_m3 = 5.0e-4;         // the powder chamber behind the ball
        barrel.piston = "ball";
        barrel.axis = {1.0, 0.0, 0.0};     // it fires along x, so gravity is out of it
        barrel.area_m2 = bore_m2;
        barrel.wall_conductance_w_k = 0.0;
        world.declareGasRegion(barrel);
        world.declareContents({"charge", {{"propellant", 1.0}}, 1000.0, 0.0, "barrel"});
        mass = ball.mass_kg;
    }
    void step(double dt) {
        const std::vector<Push> pushes = world.pushes();
        double force = 0.0;
        for (const Push &push : pushes)
            if (push.body == "ball") force = push.force_n.x;
        // The midpoint rule, so that the work this stand-in accounts for is
        // EXACTLY the kinetic energy it gains: with dx taken at the velocity
        // after the kick, F dx and the change in half m v squared differ by
        // F^2 dt^2 / 2m every step, which is the integrator's arithmetic and
        // nothing to do with the gas. Averaging the two velocities makes
        // F dx = dt F (v0 + v1) / 2, which is the change in kinetic energy to
        // the last bit -- so a mismatch in this test means the GAS is wrong.
        const double before = v;
        v += force / mass * dt;
        const double dx = 0.5 * (before + v) * dt;
        x += dx;
        work += force * dx;
        world.advance(dt, {{"ball", {dx, 0.0, 0.0}}});
        if (!left && x >= barrel_m) {
            left = true;
            muzzle_v = v;
        }
    }
    void run(double seconds, double dt) {
        const int steps = static_cast<int>(std::lround(seconds / dt));
        for (int i = 0; i < steps && !left; ++i) step(dt);
    }
};

void aCannonThrowsItsBall() {
    Cannon cannon(0.05);   // 50 g of powder behind a 1 kg ball
    const double p0 = cannon.world.regions().front().pressure_pa;
    cannon.run(0.5, 2.0e-6);
    const Ledger ledger = cannon.world.ledger();
    const BodyHeat charge = heatOf(cannon.world.bodies(), "charge");

    std::cout << "    a " << cannon.mass << " kg ball left a " << cannon.barrel_m
              << " m barrel at " << cannon.muzzle_v << " m/s, on " << cannon.work << " J of work\n";
    require(cannon.left, "the ball left the barrel");
    require(cannon.muzzle_v > 50.0, "and left it fast");
    near(charge.fuel_kg, 0.0, 1.0e-6, "the charge is spent");
    require(cannon.world.regions().front().pressure_pa > 10.0 * p0,
            "the barrel was still well above atmospheric as it left");
    // Every joule the ball carries away was paid for by the gas.
    const double kinetic = 0.5 * cannon.mass * cannon.muzzle_v * cannon.muzzle_v;
    near(kinetic, cannon.work, 1.0e-6 * kinetic, "the ball's energy is the work done on it");
    near(ledger.work_to_bodies_j, cannon.work, 1.0e-9 * std::abs(cannon.work),
         "which is what the gas paid");
    require(relativeResidual(ledger) < 1.0e-10,
            "the ledger closes: " + std::to_string(ledger.residualJ()));
}

// More powder throws it harder. A cannon that did not would be a cannon in
// name only.
void morePowderThrowsItHarder() {
    Cannon light(0.02);
    Cannon heavy(0.08);
    light.run(0.5, 2.0e-6);
    heavy.run(0.5, 2.0e-6);
    require(light.left && heavy.left, "both balls left their barrels");
    std::cout << "    20 g gave " << light.muzzle_v << " m/s, 80 g gave " << heavy.muzzle_v
              << " m/s\n";
    require(heavy.muzzle_v > 1.5 * light.muzzle_v, "four times the powder threw it much harder");
}

// ---------------------------------------------------------------------------
// A rocket

// The same charge as the cannon, in a chamber that is part of the vessel rather
// than behind a ball, with a hole in one end. Nothing is pushed against: the
// gas leaves, and the momentum it takes away is the momentum the rocket gains.
struct Rocket {
    ThermoWorld world;
    double x{}, v{}, dry_kg{}, work{};
    double nozzle_m2{};
    explicit Rocket(double charge_kg, double nozzle_m2_in) : nozzle_m2(nozzle_m2_in) {
        const BodyShape body = box("rocket", "iron", {0, 1.0, 0}, {0.08, 0.5, 0.08}, 500.0);
        const double side = std::cbrt(charge_kg / 1700.0);
        const BodyShape charge = box("charge", "none", {0, 0.9, 0}, {side, side, side}, 1700.0);
        Ambient still;
        still.floor_conductance_w_m2_k = 0.0;
        world.setAmbient(still);
        world.refresh({body, charge}, 0.0);
        GasRegionDeclaration chamber;
        chamber.name = "chamber";
        chamber.mass_fraction = {{"nitrogen", 1.0}};
        chamber.pressure_pa = 101325.0;
        chamber.volume_m3 = 1.0e-3;
        chamber.wall_conductance_w_k = 0.0;
        chamber.vent_area_m2 = nozzle_m2;
        chamber.vent_open = true;
        chamber.vessel = "rocket";              // what the thrust pushes
        chamber.vent_axis = {0.0, -1.0, 0.0};   // the gas goes down, so it goes up
        world.declareGasRegion(chamber);
        world.declareContents({"charge", {{"propellant", 1.0}}, 1000.0, 0.0, "chamber"});
        dry_kg = body.mass_kg;
    }
    void step(double dt) {
        const std::vector<Push> pushes = world.pushes();
        double force = 0.0;
        for (const Push &push : pushes)
            if (push.body == "rocket") force = push.force_n.y;
        const double before = v;
        v += force / dry_kg * dt;
        const double dy = 0.5 * (before + v) * dt;
        x += dy;
        work += force * dy;
        world.advance(dt, {{"rocket", {0.0, dy, 0.0}}});
    }
    void run(double seconds, double dt) {
        const int steps = static_cast<int>(std::lround(seconds / dt));
        for (int i = 0; i < steps; ++i) step(dt);
    }
};

void aRocketPushesItselfWithWhatLeaves() {
    // A 1.6 kg rocket, 80 g of propellant, a 12 mm throat. No gravity here: this
    // is about whether the gas pushes the vessel, not whether it can lift it.
    Rocket rocket(0.08, 0.25 * 3.14159265358979323846 * 0.012 * 0.012);
    require(rocket.world.regions().front().thrust_n == 0.0,
            "cold, before anything has burned, it pushes with nothing");
    rocket.run(2.0, 2.0e-6);
    const Ledger ledger = rocket.world.ledger();
    const BodyHeat charge = heatOf(rocket.world.bodies(), "charge");
    const RegionState chamber = rocket.world.regions().front();

    std::cout << "    a " << rocket.dry_kg << " kg rocket on 80 g of propellant reached " << rocket.v
              << " m/s in " << rocket.x << " m, " << chamber.thrust_work_j << " J of thrust work\n";
    near(charge.fuel_kg, 0.0, 1.0e-6, "the charge is spent");
    require(rocket.v > 1.0, "it is going somewhere");
    require(rocket.x > 0.0, "upwards, which is the way the nozzle is not pointing");
    require(ledger.matter_out_kg > 0.0, "and it got there by throwing its own mass out");
    near(chamber.thrust_work_j, rocket.work, 1.0e-9 * std::abs(rocket.work),
         "the thrust did exactly the work the mechanics received");
    near(0.5 * rocket.dry_kg * rocket.v * rocket.v, rocket.work,
         1.0e-6 * std::abs(rocket.work), "which is the energy it is carrying");
    require(relativeResidual(ledger) < 1.0e-10,
            "the ledger closes: " + std::to_string(ledger.residualJ()));
}

// A wider throat lets more out per second, so it pushes harder while it lasts.
void aWiderThroatPushesHarder() {
    const double narrow_m2 = 0.25 * 3.14159265358979323846 * 0.008 * 0.008;
    Rocket narrow(0.08, narrow_m2);
    Rocket wide(0.08, 4.0 * narrow_m2);
    narrow.run(0.05, 2.0e-6);
    wide.run(0.05, 2.0e-6);
    std::cout << "    after 50 ms: an 8 mm throat gave " << narrow.v << " m/s, a 16 mm one gave "
              << wide.v << " m/s\n";
    require(wide.v > narrow.v, "the wider throat got it moving faster");
}

// A sealed chamber pushes nothing, however hard it is pressed. The thrust is
// the momentum of what LEAVES, not the pressure inside.
void aSealedChamberPushesNothing() {
    Rocket sealed(0.08, 0.0);
    sealed.run(0.2, 2.0e-6);
    const RegionState chamber = sealed.world.regions().front();
    require(chamber.pressure_pa > 5.0 * 101325.0, "it is well pressed up");
    near(sealed.v, 0.0, 0.0, "and has not moved: a closed box pushes itself nowhere");
    near(chamber.thrust_work_j, 0.0, 0.0, "no thrust, no work");
}

// ---------------------------------------------------------------------------
// A kettle carries its water

// What a body CARRIES is not what it is made of, and the difference is the
// whole reason cargo exists. A kettle's water is not part of the kettle: pour
// it out and the kettle is the same kettle, the same weight of iron, the same
// strength. But it is really there -- it has to be warmed through the kettle's
// own wall, it makes the kettle heavier to pick up, and it boils.
void aKettleCarriesWaterAndBoilsIt() {
    ThermoWorld world;
    Ambient still;
    still.floor_conductance_w_m2_k = 0.0;
    world.setAmbient(still);
    // A THIN-WALLED kettle: 1.2 kg of iron around a 200 mm space, which is
    // what a kettle is. Solid iron at 7,870 would be 63 kg of metal around
    // 1 kg of water, and 3 kW spends four hundred seconds getting that to
    // 52 C -- a fair simulation of heating an anvil, and no test of boiling.
    const BodyShape kettle = box("kettle", "iron", {0, 0.1, 0}, {0.2, 0.2, 0.2}, 150.0);
    world.refresh({kettle}, 0.0);
    world.declareContents({"kettle", {{"iron", 1.0}}, 293.15, 0.0, ""});
    const double iron_kg = heatOf(world.bodies(), "kettle").mass_kg;

    world.carry({"kettle", {{"water", 1.0}}, 293.15, -1.0});
    const BodyHeat filled = heatOf(world.bodies(), "kettle");
    require(filled.carrying_kg.size() == 1 && filled.carrying_kg.front().first == "water",
            "the kettle is carrying water");
    near(filled.carrying_kg.front().second, 1.0, 1.0e-12, "a kilogram of it");
    near(filled.carrying_k, 293.15, 1.0e-9, "at the temperature it was poured in at");
    // And it is NOT part of the kettle: the iron is still just the iron.
    near(filled.mass_kg, iron_kg, 1.0e-12, "the kettle itself is no heavier for holding it");
    for (const auto &[what, kg] : filled.contents_kg)
        require(what != "water", "the water is carried, not what the kettle is made of");

    // Now put it on a ring. The heater warms the KETTLE, and the kettle warms
    // the water through its wall, which is how a kettle works.
    world.heat({"kettle", 3000.0, 0.0, 200.0, "ring"});
    const int steps = 200 * 240;
    for (int i = 0; i < steps; ++i) world.advance(1.0 / 240.0, {});

    const BodyHeat done = heatOf(world.bodies(), "kettle");
    const Ledger ledger = world.ledger();
    const double left = done.carrying_kg.empty() ? 0.0 : done.carrying_kg.front().second;
    std::cout << "    3 kW for 200 s: the water reached " << done.carrying_k - 273.15
              << " C and " << 1.0 - left << " kg of it boiled away\n";
    near(done.carrying_k, kBoilingK, 0.2, "the water it carries is at its boiling point");
    require(left < 1.0, "and some of it has boiled away");
    require(left > 0.0, "but not all of it");
    // The kettle is lighter to carry for what it lost, and the iron is
    // untouched: boiling takes the water, never the pot.
    near(done.mass_kg, iron_kg, 1.0e-12, "the kettle is still all the iron it was");
    require(relativeResidual(ledger) < 1.0e-9,
            "the ledger closes: " + std::to_string(ledger.residualJ()));
}

// Pouring from one into another, which is what a vessel is for. What comes out
// of the first goes into the second at the heat it came out at, and the two of
// them together hold what the first one did.
void pouringCarriesTheHeatWithIt() {
    ThermoWorld world;
    Ambient still;
    still.floor_conductance_w_m2_k = 0.0;
    world.setAmbient(still);
    world.refresh({box("full pail", "iron", {0, 0.1, 0}, {0.2, 0.2, 0.2}, 7870.0),
                   box("empty pail", "iron", {1, 0.1, 0}, {0.2, 0.2, 0.2}, 7870.0)},
                  0.0);
    world.declareContents({"full pail", {{"iron", 1.0}}, 293.15, 0.0, ""});
    world.declareContents({"empty pail", {{"iron", 1.0}}, 293.15, 0.0, ""});
    world.carry({"full pail", {{"water", 2.0}}, 350.0, -1.0});

    const auto [poured, at_k] = world.release("full pail", "water", 0.8);
    near(poured, 0.8, 1.0e-12, "it poured out what was asked for");
    near(at_k, 350.0, 0.01, "at the heat it was holding");
    world.carry({"empty pail", {{"water", poured}}, at_k, -1.0});

    const BodyHeat from = heatOf(world.bodies(), "full pail");
    const BodyHeat into = heatOf(world.bodies(), "empty pail");
    near(from.carrying_kg.front().second, 1.2, 1.0e-9, "the one poured from has the rest");
    near(into.carrying_kg.front().second, 0.8, 1.0e-9, "and the other has what it was given");
    near(into.carrying_k, 350.0, 0.01, "still at the heat it was poured at");
    require(relativeResidual(world.ledger()) < 1.0e-9, "and the ledger closes across the pour");
}

const std::vector<std::pair<std::string, std::function<void()>>> &tests() {
    static const std::vector<std::pair<std::string, std::function<void()>>> all = {
        {"boiling costs the latent heat of vaporisation", boilingCostsTheLatentHeatOfVaporisation},
        {"a kettle holds at its boiling point however hard it is driven",
         aKettleHoldsAtItsBoilingPointHoweverHardItIsDriven},
        {"a steam engine lifts its load", aSteamEngineLiftsItsLoad},
        {"a cannon throws its ball", aCannonThrowsItsBall},
        {"more powder throws it harder", morePowderThrowsItHarder},
        {"a rocket pushes itself with what leaves", aRocketPushesItselfWithWhatLeaves},
        {"a wider throat pushes harder", aWiderThroatPushesHarder},
        {"a sealed chamber pushes nothing", aSealedChamberPushesNothing},
        {"a kettle carries water and boils it", aKettleCarriesWaterAndBoilsIt},
        {"pouring carries the heat with it", pouringCarriesTheHeatWithIt},
    };
    return all;
}

} // namespace

int main() {
    unsigned failures = 0;
    for (const auto &[name, test] : tests()) {
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception &error) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests().size() - failures << '/' << tests().size() << " tests passed\n";
    return failures == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
}
