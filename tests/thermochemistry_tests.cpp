// The thermochemical network on its own, with no rigid world: conservation,
// finite inventories, rollback, the declared wood model, and the gas side of a
// pressure boundary. tests/thermo_live_tests.cpp puts the same network inside a
// live world.
#include "thermo/ThermoJson.hpp"
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

constexpr double kDt = 1.0 / 240.0;   // what the room steps at

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

// A 5.2 kg oak log, 120 x 120 x 480 mm, lying along z.
BodyShape log(std::string name = "log", Vec3 at = {0.0, 0.06, 0.0}) {
    return box(std::move(name), "oak", at, {0.12, 0.12, 0.48}, 700.0);
}

void run(ThermoWorld &world, double seconds, double dt = kDt) {
    const int steps = static_cast<int>(std::lround(seconds / dt));
    for (int i = 0; i < steps; ++i) world.advance(dt, {});
}

// By value: bodies() and regions() return temporaries, and a reference into
// one dangles at the end of the statement that made it.
BodyHeat heatOf(const std::vector<BodyHeat> &all, const std::string &name) {
    for (const BodyHeat &b : all)
        if (b.body == name) return b;
    throw std::runtime_error("no thermal state for " + name);
}

double relativeResidual(const Ledger &l) {
    return std::abs(l.residualJ()) / std::max(1.0, std::abs(l.storedJ()));
}

// ---------------------------------------------------------------------------
// Milestone 1: unified accounting and generalised reactions
// ---------------------------------------------------------------------------

// A reaction with nothing coming from outside and nothing leaving: every
// joule and every gram stays. The final temperature is then known in closed
// form -- internal energy is conserved, so T = (U0 - R_final) / C_final -- and
// the network has to land on it.
void closedReactionReachesItsAdiabaticTemperature() {
    Model model;
    model.id = "closed-test";
    model.version = "1";
    const std::size_t a = model.add({"reactant", Phase::Solid, 0.0, 1000.0, 1.0e6, 0.5, 0.0});
    const std::size_t b = model.add({"residue", Phase::Solid, 0.0, 800.0, 0.0, 0.5, 0.0});
    const std::size_t g = model.add({"trapped gas", Phase::Gas, 0.030, 700.0, 0.0, 0.0, 0.0});
    Reaction reaction;
    reaction.id = "closed";
    reaction.version = "1";
    reaction.reactants = {{a, 1.0, Supply::Material, Fate::Retained}};
    reaction.products = {{b, 0.7, Supply::Material, Fate::Retained},
                         {g, 0.3, Supply::Material, Fate::Retained}};
    reaction.rate = {RateKind::Volume, 1.0e3, 3000.0, 400.0, 1.0e5, 0.0};
    model.addReaction(reaction);
    model.setComposition("test charge", {{"reactant", 1.0}});

    ThermoWorld world(model);
    Ambient still;
    still.film_coefficient_w_m2_k = 0.0;
    still.floor_conductance_w_m2_k = 0.0;
    world.setAmbient(still);
    world.refresh({box("charge", "test charge", {0, 1, 0}, {0.1, 0.1, 0.1}, 1000.0)}, 0.0);
    world.declareContents({"charge", {}, 450.0, 0.0, ""});
    const Ledger before = world.ledger();
    run(world, 5.0, 1.0e-3);
    const Ledger after = world.ledger();
    const BodyHeat charge = heatOf(world.bodies(), "charge");

    const double m0 = 1.0;   // 0.1 m cube at 1000 kg/m3
    near(before.mass_kg, m0, 1e-12, "the charge holds its declared mass");
    near(after.mass_kg, before.mass_kg, 1e-12 * m0, "closed: mass is conserved");
    near(after.storedJ(), before.storedJ(), 1e-9 * before.storedJ(), "closed: energy is conserved");
    near(after.residualJ(), 0.0, 1e-9 * before.storedJ(), "closed: nothing unaccounted");
    near(after.matter_in_kg + after.matter_out_kg + after.heater_in_j + after.heat_to_surroundings_j,
         0.0, 0.0, "closed: nothing crossed the boundary");
    double reactant = 0.0;
    for (const auto &[id, kg] : charge.contents_kg)
        if (id == "reactant") reactant = kg;
    require(reactant < 1e-9, "the finite inventory was consumed");
    const double u0 = m0 * (1.0e6 + 1000.0 * 450.0);
    const double capacity = m0 * (0.7 * 800.0 + 0.3 * 700.0);
    near(charge.temperature_k, u0 / capacity, 1e-6 * (u0 / capacity),
         "the closed fixture lands on its adiabatic temperature");
}

// A propellant charge inside a sealed chamber: the gas it makes goes into the
// chamber, not out of the world, so the whole thing is closed and the chamber
// pressure is where the energy went.
void rapidReactionInASealedChamberIsClosed() {
    ThermoWorld world;
    Ambient still;
    still.floor_conductance_w_m2_k = 0.0;
    world.setAmbient(still);
    world.refresh({box("charge", "none", {0, 1, 0}, {0.04, 0.04, 0.04}, 1700.0)}, 0.0);
    GasRegionDeclaration chamber;
    chamber.name = "chamber";
    chamber.mass_fraction = {{"nitrogen", 1.0}};
    chamber.pressure_pa = 101325.0;
    chamber.volume_m3 = 0.002;
    chamber.wall_conductance_w_k = 0.0;
    world.declareGasRegion(chamber);
    world.declareContents({"charge", {{"propellant", 1.0}}, 600.0, 0.0, "chamber"});
    const Ledger before = world.ledger();
    const double p0 = world.regions().front().pressure_pa;
    run(world, 2.0, 1.0e-4);
    const Ledger after = world.ledger();
    near(after.mass_kg, before.mass_kg, 1e-12 * before.mass_kg, "sealed: mass is conserved");
    near(after.residualJ(), 0.0, 1e-9 * std::abs(before.storedJ()), "sealed: energy is conserved");
    near(after.matter_out_kg + after.matter_in_kg, 0.0, 0.0, "sealed: nothing left the world");
    const RegionState gas = world.regions().front();
    const BodyHeat charge = heatOf(world.bodies(), "charge");
    const double charge_kg = 1700.0 * 0.04 * 0.04 * 0.04;
    near(charge.fuel_kg, 0.0, 1e-9, "the charge is spent");
    double made = 0.0;
    for (const auto &[id, kg] : gas.contents_kg)
        if (id == "propellant gas") made = kg;
    near(made, 0.56 * charge_kg, 1e-9 * charge_kg, "the chamber holds exactly the gas it made");
    require(gas.pressure_pa > 3.0 * p0, "the chamber pressure rose");
}

// Save, go on, go back, go on again: the second attempt must be the first one
// exactly, and the fuel must have been burned once. This is what a rejected
// rigid step relies on.
void saveAndRestoreDoNotDuplicateConsumption() {
    ThermoWorld world;
    world.refresh({log()}, 0.0);
    world.declareContents({"log", {}, 1000.0, -1.0, ""});
    run(world, 1.0);
    const ThermoState saved = world.state();
    const double fuel_saved = heatOf(world.bodies(), "log").fuel_kg;
    run(world, 0.5);
    const double fuel_first = heatOf(world.bodies(), "log").fuel_kg;
    const Ledger ledger_first = world.ledger();
    world.restore(saved);
    near(heatOf(world.bodies(), "log").fuel_kg, fuel_saved, 0.0, "restoring gives the fuel back");
    run(world, 0.5);
    const double fuel_second = heatOf(world.bodies(), "log").fuel_kg;
    const Ledger ledger_second = world.ledger();
    require(fuel_first < fuel_saved, "the log was burning");
    near(fuel_second, fuel_first, 0.0, "the retried half second burns exactly the same fuel");
    near(ledger_second.matter_out_j, ledger_first.matter_out_j, 0.0, "and releases exactly the same gas");
    near(ledger_second.storedJ(), ledger_first.storedJ(), 0.0, "and ends with exactly the same energy");
}

// A reaction can only take what is there: all of a small inventory, and none
// of a reactant the surroundings do not hold.
void aReactionCannotTakeWhatIsNotThere() {
    {
        ThermoWorld world;
        world.refresh({log()}, 0.0);
        world.declareContents({"log", {{"dry wood", 0.001}, {"ash", 0.999}}, 1500.0, 0.0, ""});
        for (int i = 0; i < 20; ++i) world.advance(10.0, {});
        const BodyHeat &b = heatOf(world.bodies(), "log");
        require(b.fuel_kg >= 0.0, "fuel never goes negative");
        near(b.fuel_kg, 0.0, 1e-12, "a small inventory burns out, and no further");
        near(world.ledger().residualJ(), 0.0, 1e-6, "and the ledger closes");
    }
    {
        ThermoWorld world;
        Ambient nitrogen;
        nitrogen.mass_fraction.assign(world.model().size(), 0.0);
        nitrogen.mass_fraction[world.model().index("nitrogen")] = 1.0;
        world.setAmbient(nitrogen);
        world.refresh({log()}, 0.0);
        world.declareContents({"log", {{"dry wood", 1.0}}, 1200.0, 0.0, ""});
        const double fuel = heatOf(world.bodies(), "log").fuel_kg;
        run(world, 2.0);
        near(heatOf(world.bodies(), "log").fuel_kg, fuel, 0.0,
             "without oxygen in the surroundings, hot wood does not burn");
    }
}

void anUnbalancedReactionIsRefused() {
    Model model = demonstrationModel();
    const std::size_t reactions = model.reactions.size();
    Reaction wrong;
    wrong.id = "makes mass";
    wrong.version = "1";
    wrong.reactants = {{model.index("dry wood"), 1.0, Supply::Material, Fate::Retained}};
    wrong.products = {{model.index("ash"), 1.2, Supply::Material, Fate::Retained}};
    bool refused = false;
    try {
        model.addReaction(wrong);
    } catch (const std::invalid_argument &) {
        refused = true;
    }
    require(refused, "a reaction that makes mass is refused");
    require(model.reactions.size() == reactions, "and the model is left as it was");
}

void theReferenceEnergiesImplyTheDeclaredHeatingValues() {
    const Model model = demonstrationModel();
    const auto reaction = [&](const std::string &id) -> const Reaction & {
        for (const Reaction &r : model.reactions)
            if (r.id == id) return r;
        throw std::runtime_error("missing reaction " + id);
    };
    near(model.heatOfReactionJPerKg(reaction("wood combustion"), 298.15), 16.0e6, 1.0,
         "dry wood releases its declared 16.0 MJ/kg at 298.15 K");
    near(-model.heatOfReactionJPerKg(reaction("drying"), 373.15), 2.257e6, 1.0,
         "drying takes the latent heat at 373.15 K");
    near(model.heatOfReactionJPerKg(reaction("rapid reaction"), 298.15), 2.8e6, 1.0,
         "the rapid reaction releases its declared 2.8 MJ/kg");
    require(model.isFuel(model.index("dry wood")) && !model.isFuel(model.index("moisture")),
            "a fuel is what a heat-releasing reaction consumes");
}

void aNameCannotChangePhysics() {
    const auto burn = [](const std::string &name, const std::string &material) {
        ThermoWorld world;
        BodyShape shape = log(name);
        shape.material = material;
        world.refresh({shape}, 0.0);
        world.declareContents({name, {{"dry wood", 0.88}, {"moisture", 0.10}, {"ash", 0.02}}, 900.0, -1.0, ""});
        run(world, 3.0);
        const BodyHeat b = heatOf(world.bodies(), name);
        return std::pair{b.temperature_k, b.fuel_kg};
    };
    const auto oak = burn("oak log", "oak");
    const auto blue = burn("fictional blue block", "painted");
    near(blue.first, oak.first, 0.0, "the name does not change the temperature");
    near(blue.second, oak.second, 0.0, "the name does not change the fuel burned");
}

// ---------------------------------------------------------------------------
// Milestone 2: a fuel-fed hearth, on the network
// ---------------------------------------------------------------------------

// Burning is a result, not a property: enough kindling lights the log and less
// does not, and the log then burns at the rate the model decides.
void kindlingLightsALogAndLessDoesNot() {
    const auto light = [](double power_w) {
        ThermoWorld world;
        world.refresh({log()}, 0.0);
        world.declareContents({"log", {}, 0.0, -1.0, ""});
        world.heat({"log", power_w, 0.0, 60.0, "kindling"});
        run(world, 150.0);
        return heatOf(world.bodies(), "log");
    };
    const BodyHeat lit = light(10000.0);
    const BodyHeat unlit = light(5000.0);
    require(lit.reacting && lit.temperature_k > 800.0, "10 kW for a minute lights the log");
    require(!unlit.reacting && unlit.temperature_k < 500.0, "5 kW for a minute does not");
    require(lit.heat_release_w > 5.0e3 && lit.heat_release_w < 40.0e3,
            "a log burns at a few kilowatts to tens of kilowatts");
    const double minutes = lit.remaining_s / 60.0;
    require(minutes > 20.0 && minutes < 150.0,
            "the estimated remaining burn time is tens of minutes (" + std::to_string(minutes) + ")");
}

// The ledger of an open fire: oxygen comes in, flue gas and steam go out, heat
// leaves through the surroundings -- and it all adds up.
void anOpenFireBalancesItsLedger() {
    ThermoWorld world;
    world.refresh({log()}, 0.0);
    world.declareContents({"log", {}, 0.0, -1.0, ""});
    world.heat({"log", 10000.0, 0.0, 60.0, "kindling"});
    run(world, 180.0);
    const Ledger l = world.ledger();
    near(l.heater_in_j, 10000.0 * 60.0, 1e-6, "the kindling's energy is exactly what it declared");
    require(l.matter_in_kg > 0.0 && l.matter_out_kg > l.matter_in_kg,
            "oxygen came in and more flue gas went out");
    require(l.heat_to_surroundings_j > 0.0, "heat left through the surroundings");
    require(relativeResidual(l) < 1e-10, "and the ledger closes: " + std::to_string(l.residualJ()));
    near(l.massResidualKg(), 0.0, 1e-9, "mass closes too");
    near(l.numerical_j, 0.0, 0.0, "no numerical corrections were needed");
}

// Geometry decides who is warmed: an iron block beside a burning log joins the
// network and warms; one far away barely does.
void aFireWarmsWhatIsBesideIt() {
    ThermoWorld world;
    world.refresh({log(), box("near iron", "iron", {0.25, 0.08, 0.0}, {0.16, 0.16, 0.16}, 7870.0),
                   box("far iron", "iron", {6.0, 0.08, 0.0}, {0.16, 0.16, 0.16}, 7870.0)},
                  0.0);
    world.declareContents({"log", {}, 1000.0, -1.0, ""});
    world.refresh({log(), box("near iron", "iron", {0.25, 0.08, 0.0}, {0.16, 0.16, 0.16}, 7870.0),
                   box("far iron", "iron", {6.0, 0.08, 0.0}, {0.16, 0.16, 0.16}, 7870.0)},
                  0.0);
    require(world.holds("near iron"), "the block beside the fire joined the network");
    run(world, 120.0);
    const auto all = world.bodies();
    const double near_t = heatOf(all, "near iron").temperature_k;
    require(near_t > 293.15 + 2.0, "the block beside the fire warmed: " + std::to_string(near_t));
    double far_t = 293.15;
    for (const BodyHeat &b : all)
        if (b.body == "far iron") far_t = b.temperature_k;
    require(far_t - 293.15 < 0.1 * (near_t - 293.15), "the far block warmed far less, if at all");
    require(relativeResidual(world.ledger()) < 1e-10, "and the ledger still closes");
}

// Breaking a burning log shares out what it holds: no fuel is made, none is
// lost, and every piece is as hot as the log was.
void splittingShareOutTheInventoryExactly() {
    ThermoWorld world;
    world.refresh({log()}, 0.0);
    world.declareContents({"log", {}, 1000.0, -1.0, ""});
    run(world, 20.0);
    const BodyHeat whole = heatOf(world.bodies(), "log");
    const Ledger before = world.ledger();
    world.split("log", {{"log piece 1", 0.5}, {"log piece 2", 0.3}, {"log piece 3", 0.2}});
    const auto pieces = world.bodies();
    require(pieces.size() == 3 && !world.holds("log"), "three pieces and no log");
    double mass = 0.0, fuel = 0.0;
    for (const BodyHeat &piece : pieces) {
        mass += piece.mass_kg;
        fuel += piece.fuel_kg;
        near(piece.temperature_k, whole.temperature_k, 1e-9 * whole.temperature_k,
             "each piece is as hot as the log was");
    }
    near(mass, whole.mass_kg, 1e-12 * whole.mass_kg, "no matter is made or lost");
    near(fuel, whole.fuel_kg, 1e-12 * whole.fuel_kg, "no fuel is made or lost");
    near(heatOf(pieces, "log piece 1").mass_kg, 0.5 * whole.mass_kg, 1e-9 * whole.mass_kg,
         "a piece holds its share");
    const Ledger after = world.ledger();
    near(after.storedJ(), before.storedJ(), 1e-12 * std::abs(before.storedJ()),
         "breaking is not a boundary crossing");
    near(after.residualJ() - before.residualJ(), 0.0, 1e-6, "the ledger is unchanged by it");
}

void removingABodyCarriesItsMatterOut() {
    ThermoWorld world;
    world.refresh({log("first"), log("second", {0.5, 0.06, 0.0})}, 0.0);
    world.declareContents({"first", {}, 900.0, -1.0, ""});
    world.declareContents({"second", {}, 300.0, -1.0, ""});
    run(world, 2.0);
    const BodyHeat going = heatOf(world.bodies(), "first");
    const double carried = going.mass_kg;
    world.remove("first");
    const Ledger l = world.ledger();
    near(l.left_kg, carried, 1e-12, "what left was exactly what the body held");
    require(relativeResidual(l) < 1e-10, "and the ledger closes");
}

// ---------------------------------------------------------------------------
// Milestone 3: gas state and mechanical work, gas side
// ---------------------------------------------------------------------------

struct Piston {
    double y{};          // centre of the piston
    double v{};
    double mass{};
    double work{};       // the force's work, as the mechanics sees it
};

// The gas side of a piston, driven by a one-dimensional stand-in for the
// mechanics. The real coupling is in tests/thermo_live_tests.cpp; this pins
// what the network itself promises.
struct Cylinder {
    ThermoWorld world;
    Piston piston;
    double y0{};
    Cylinder(double heater_w, double heater_s) {
        const BodyShape body = box("piston", "iron", {0, 0.52, 0}, {0.24, 0.08, 0.24}, 7870.0);
        const BodyShape load = box("load", "iron", {0, 0.64, 0}, {0.16, 0.16, 0.16}, 7870.0);
        world.refresh({body, load}, 0.0);
        GasRegionDeclaration gas;
        gas.name = "cylinder gas";
        gas.mass_fraction = {{"argon", 1.0}};
        gas.piston = "piston";
        gas.height_m = 0.4;
        gas.balance = true;
        world.declareGasRegion(gas);
        if (heater_w > 0.0) world.heat({"cylinder gas", heater_w, 0.0, heater_s, "heater"});
        piston.y = y0 = body.center_m.y;
        piston.mass = body.mass_kg + load.mass_kg;
    }
    void step(double dt) {
        const std::vector<Push> pushes = world.pushes();
        const double force = pushes.empty() ? 0.0 : pushes.front().force_n.y;
        piston.v += (force / piston.mass - 9.80665) * dt;
        const double dy = piston.v * dt;
        piston.y += dy;
        piston.work += force * dy;
        world.advance(dt, {{"piston", {0.0, dy, 0.0}}});
    }
    void run(double seconds, double dt) {
        const int steps = static_cast<int>(std::lround(seconds / dt));
        for (int i = 0; i < steps; ++i) step(dt);
    }
};

void pistonWorkIsTheWorkTheMechanicsReceived() {
    Cylinder c(800.0, 30.0);
    const RegionState start = c.world.regions().front();
    near(start.force_n, 9.80665 * c.piston.mass, 1e-9 * start.force_n,
         "balanced: the gas holds the piston and its load up");
    c.run(30.0, kDt);
    const Ledger heated = c.world.ledger();
    const RegionState hot = c.world.regions().front();
    near(heated.work_to_bodies_j, c.piston.work, 1e-9 * std::abs(c.piston.work),
         "the gas paid exactly the work the mechanics received");
    require(c.piston.work > 0.0 && hot.stroke_m > 0.1, "heated, it lifted the load");
    // Slow heating is quasi-static: the pressure stays what holds the load up,
    // so volume goes with temperature.
    const double expected = hot.temperature_k / start.temperature_k;
    near(hot.volume_m3 / start.volume_m3, expected, 0.01 * expected,
         "at constant pressure the volume follows the temperature");
    near(hot.stroke_m, c.piston.y - c.y0, 1e-9, "the stroke is the piston's own travel");
    c.run(90.0, kDt);
    const Ledger cooled = c.world.ledger();
    require(cooled.work_to_bodies_j < heated.work_to_bodies_j - 0.5 * heated.work_to_bodies_j,
            "cooling, the load came down and returned work to the gas");
    near(c.piston.y, c.y0, 0.01, "and the piston is back near where it started");
    require(relativeResidual(cooled) < 1e-10, "the ledger closes: " + std::to_string(cooled.residualJ()));
    near(cooled.numerical_j, 0.0, 0.0, "without numerical corrections");
}

// Shrink the step and the answer approaches a much finer one.
//
// The piston rides on the gas as on a spring (a period of about 0.3 s here),
// so its height at one instant carries the phase of that ringing, which is
// not what is being refined. The mean over the last second is the lift.
void pistonLiftConvergesAsTheStepShrinks() {
    const auto lift = [](double dt) {
        Cylinder c(800.0, 10.0);
        c.run(9.0, dt);
        const int steps = static_cast<int>(std::lround(1.0 / dt));
        double sum = 0.0;
        for (int i = 0; i < steps; ++i) {
            c.step(dt);
            sum += c.world.regions().front().stroke_m;
        }
        return sum / steps;
    };
    const double reference = lift(1.0 / 1920.0);
    const double e60 = std::abs(lift(1.0 / 60.0) - reference);
    const double e240 = std::abs(lift(1.0 / 240.0) - reference);
    const std::string said = "the lift converges: at 1/60 s " + std::to_string(e60 * 1000.0) +
                             " mm off, at 1/240 s " + std::to_string(e240 * 1000.0) + " mm off";
    std::cout << "    " << said << " (reference lift " << reference * 1000.0 << " mm)" << std::endl;
    require(e240 < e60, said);
    require(e240 < 0.5e-3, "and at the room's own step it is within half a millimetre: " + said);
}

void anOpenVentLetsTheGasOut() {
    ThermoWorld world;
    world.refresh({}, 0.0);
    GasRegionDeclaration tank;
    tank.name = "tank";
    tank.mass_fraction = {{"argon", 1.0}};
    tank.pressure_pa = 2.0 * 101325.0;
    tank.volume_m3 = 0.01;
    tank.vent_area_m2 = 1.0e-4;
    world.declareGasRegion(tank);
    const double m0 = world.regions().front().mass_kg;
    run(world, 5.0);
    const RegionState after = world.regions().front();
    near(after.pressure_pa, 101325.0, 0.02 * 101325.0, "the tank relaxes to the surroundings");
    const Ledger l = world.ledger();
    near(l.matter_out_kg - l.matter_in_kg, m0 - after.mass_kg, 1e-12, "what left is accounted for");
    require(relativeResidual(l) < 1e-10, "and the energy it carried too");
}

// ---------------------------------------------------------------------------
// Declarations
// ---------------------------------------------------------------------------

void aSceneDeclaresItsThermochemistry() {
    const std::string scene = R"({"bodies": [
        {"name": "log", "material": "oak", "contents": {"dry wood": 0.8, "moisture": 0.2}},
        {"name": "piston", "material": "iron"},
        {"name": "stone", "material": "concrete"}],
      "thermo": {"gas_regions": [{"name": "cylinder gas", "contents": {"argon": 1},
                                  "piston": "piston", "height_m": 0.4, "balance": true}],
                 "heaters": [{"target": "log", "power_w": 10000, "seconds": 60}]}})";
    const Declarations d = readSceneDeclarations(scene);
    require(d.contents.size() == 1 && d.contents.front().body == "log", "one body declares contents");
    require(d.regions.size() == 1 && d.regions.front().balance, "one gas region, balanced");
    require(d.heaters.size() == 1 && d.heaters.front().power_w == 10000.0, "one heater");
    bool refused = false;
    try {
        (void)readSceneDeclarations(R"({"bodies": [], "thermo": {"heaters": [{"target": "log", "tempreature": 3}]}})");
    } catch (const std::invalid_argument &error) {
        refused = std::string(error.what()).find("tempreature") != std::string::npos;
    }
    require(refused, "a misspelt key is refused, by name");
    ThermoWorld world;
    world.refresh({log(), box("piston", "iron", {1, 0.52, 0}, {0.24, 0.08, 0.24}, 7870.0)}, 0.0);
    apply(world, d);
    const std::string report = reportJson(world, true);
    require(report.find("\"wood combustion\"") != std::string::npos, "the report carries the model");
    require(report.find("demonstration") != std::string::npos, "and says where its numbers came from");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"closed reaction reaches its adiabatic temperature", closedReactionReachesItsAdiabaticTemperature},
        {"rapid reaction in a sealed chamber is closed", rapidReactionInASealedChamberIsClosed},
        {"save and restore do not duplicate consumption", saveAndRestoreDoNotDuplicateConsumption},
        {"a reaction cannot take what is not there", aReactionCannotTakeWhatIsNotThere},
        {"an unbalanced reaction is refused", anUnbalancedReactionIsRefused},
        {"reference energies imply the declared heating values", theReferenceEnergiesImplyTheDeclaredHeatingValues},
        {"a name cannot change physics", aNameCannotChangePhysics},
        {"kindling lights a log and less does not", kindlingLightsALogAndLessDoesNot},
        {"an open fire balances its ledger", anOpenFireBalancesItsLedger},
        {"a fire warms what is beside it", aFireWarmsWhatIsBesideIt},
        {"splitting shares out the inventory exactly", splittingShareOutTheInventoryExactly},
        {"removing a body carries its matter out", removingABodyCarriesItsMatterOut},
        {"piston work is the work the mechanics received", pistonWorkIsTheWorkTheMechanicsReceived},
        {"piston lift converges as the step shrinks", pistonLiftConvergesAsTheStepShrinks},
        {"an open vent lets the gas out", anOpenVentLetsTheGasOut},
        {"a scene declares its thermochemistry", aSceneDeclaresItsThermochemistry},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception &error) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size() << " tests passed\n";
    return failures == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
}
