// The shallow-water solver on its own, with no bodies and no terrain edits
// arriving from outside: a lake at rest stays exactly at rest, a closed basin
// keeps its water to rounding, a flood front advances over dry ground without a
// negative depth, a river fed at one end and drained at the other settles to
// passing what it is given, a row of blocks across a channel backs the water
// up, and digging or filling under water makes and destroys none.
//
// tests/valley_live_tests.cpp puts the same water under real bodies in a live
// world.
#include "water/ShallowWater.hpp"
#include "water/WaterCoupling.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using namespace banjo::water;
using banjo::Vec3;

constexpr double kInf = std::numeric_limits<double>::infinity();

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message) + ": actual=" + std::to_string(actual) +
                                 " expected=" + std::to_string(expected) +
                                 " tolerance=" + std::to_string(tolerance));
}

// A bumpy bowl: a hollow with a hump in the middle and uneven slopes, so no
// face between two cells sees the same bed on both sides.
std::vector<double> bowl(const Grid &g) {
    std::vector<double> bed(g.cells());
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < g.nx; ++i) {
            const double x = (i - 0.5 * (g.nx - 1)) * g.dx;
            const double z = (j - 0.5 * (g.nz - 1)) * g.dx;
            const double r2 = x * x + z * z;
            bed[g.at(i, j)] = 0.08 * r2 + 0.35 * std::exp(-4.0 * r2) +
                              0.05 * std::sin(3.1 * x) * std::cos(2.3 * z) + 0.01 * i;
        }
    return bed;
}

// 1. A lake at rest stays EXACTLY at rest: not to rounding, bit for bit. Over a
// bumpy bed with a shoreline, an island poking through, and a submerged block.
void aLakeAtRestStaysExactlyAtRest() {
    Grid g{48, 40, 0.25, 0.0, 0.0};
    ShallowWater water(g, bowl(g));
    // A block standing on the bed in the lake, poking through, and another
    // wholly under water: both are bed steps to the water.
    std::vector<double> top(g.cells(), -kInf);
    for (int j = 10; j < 14; ++j)
        for (int i = 8; i < 12; ++i) top[g.at(i, j)] = 2.0;       // pierces the surface
    for (int j = 25; j < 28; ++j)
        for (int i = 30; i < 34; ++i) top[g.at(i, j)] = 0.4;      // submerged
    water.setObstacles(top);
    const double level = 1.1;
    for (std::size_t c = 0; c < g.cells(); ++c) water.setSurface(c, level);
    water.resetLedger();
    std::size_t wet = 0, dry = 0;
    for (std::size_t c = 0; c < g.cells(); ++c) (water.wet(c) ? wet : dry) += 1;
    require(wet > 200 && dry > 100, "the lake has both water and shore");
    std::vector<double> eta(g.cells()), qx(g.cells()), qz(g.cells());
    for (std::size_t c = 0; c < g.cells(); ++c) {
        eta[c] = water.surface(c);
        qx[c] = water.dischargeX(c);
        qz[c] = water.dischargeZ(c);
    }
    const double v0 = water.volume();
    int substeps = 0;
    for (int k = 0; k < 400; ++k) substeps += water.advance(1.0 / 60.0);
    require(substeps >= 400, "it was actually stepped");
    for (std::size_t c = 0; c < g.cells(); ++c) {
        const double e = water.surface(c), x = water.dischargeX(c), z = water.dischargeZ(c);
        if (std::memcmp(&e, &eta[c], sizeof e) != 0 || std::memcmp(&x, &qx[c], sizeof x) != 0 ||
            std::memcmp(&z, &qz[c], sizeof z) != 0)
            throw std::runtime_error("cell " + std::to_string(c) + " moved: surface " +
                                     std::to_string(e - eta[c]) + " m, discharge " +
                                     std::to_string(x) + ", " + std::to_string(z));
    }
    require(water.volume() == v0, "and its volume is the same number");
    require(water.ledger().numerical_m3 == 0.0, "nothing had to be put back");
    std::cout << "    " << wet << " wet and " << dry << " dry columns, " << substeps
              << " substeps: every surface and discharge bit-identical\n";
}

// 2. A closed basin keeps its water. Start it sloshing -- a heap of water on
// one side -- and let it run: the volume is conserved to rounding, whatever
// the flow does, and nothing is added to keep depths positive.
void aClosedBasinConservesWater() {
    Grid g{64, 48, 0.25, 0.0, 0.0};
    ShallowWater water(g, bowl(g));
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < g.nx; ++i) {
            const double x = (i - 0.5 * (g.nx - 1)) * g.dx;
            water.setSurface(g.at(i, j), 0.9 + (x < -2.0 ? 0.6 : 0.0));
        }
    water.resetLedger();
    const double v0 = water.volume();
    double worst = 0.0;
    int substeps = 0;
    for (int k = 0; k < 600; ++k) {
        substeps += water.advance(1.0 / 60.0);
        worst = std::max(worst, std::abs(water.volume() - v0));
    }
    const double relative = worst / v0;
    std::cout << "    " << v0 << " m^3 over " << substeps << " substeps and 10 s: worst drift "
              << worst << " m^3 (" << relative << " of the volume), put back "
              << water.ledger().numerical_m3 << " m^3\n";
    require(relative < 1.0e-12, "a closed basin keeps its water to rounding");
    require(water.ledger().numerical_m3 < 1.0e-12 * v0, "and nothing was added to keep depths positive");
    near(water.residual(), 0.0, 1.0e-11 * v0, "the ledger closes");
    // And it really was sloshing.
    double fastest = 0.0;
    for (std::size_t c = 0; c < g.cells(); ++c)
        fastest = std::max(fastest, std::hypot(water.velocityX(c), water.velocityZ(c)));
    require(fastest > 0.01, "the water moved");
}

// 3. A flood over dry ground. A dam breaks onto a flat dry bed: the front must
// advance, no depth goes negative, and nothing runs ahead of the fastest a
// dry-bed front can go (Ritter: 2 sqrt(g h0)).
void aFloodFrontAdvancesOverDryGround() {
    Grid g{400, 4, 0.05, 0.0, 0.0};
    ShallowWater water(g, std::vector<double>(g.cells(), 0.0),
                       Settings{.manning_n = 0.0});
    const double h0 = 0.5;
    const int dam = 100;
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < dam; ++i) water.setDepth(g.at(i, j), h0);
    water.resetLedger();
    const double v0 = water.volume();
    const double t = 1.0;
    water.advance(t);
    int front = dam;
    for (int i = dam; i < g.nx; ++i)
        if (water.depth(g.at(i, 1)) > 1.0e-4) front = i;
    const double reached = (front - dam + 0.5) * g.dx;
    const double ritter = 2.0 * std::sqrt(9.81 * h0) * t;
    double lowest = 0.0;
    for (std::size_t c = 0; c < g.cells(); ++c) lowest = std::min(lowest, water.depth(c));
    std::cout << "    front " << reached << " m after 1 s; Ritter's dry-bed front is " << ritter
              << " m; lowest depth " << lowest << " m; " << water.stats().clamped
              << " clamps, " << water.ledger().numerical_m3 << " m^3 put back\n";
    require(lowest >= 0.0, "no negative depth anywhere");
    require(reached > 0.6 * ritter, "the front advanced most of the way Ritter says");
    require(reached < ritter + 3.0 * g.dx, "and nowhere faster than a dry-bed front can go");
    near(water.volume(), v0, 1.0e-12 * v0, "a flood over dry ground makes no water");
}

// A straight sloping channel, fed at its west end and open at its east.
struct Channel {
    Grid grid{96, 16, 0.25, 0.0, 0.0};
    std::vector<double> bed;
    Channel() : bed(grid.cells()) {
        for (int j = 0; j < grid.nz; ++j)
            for (int i = 0; i < grid.nx; ++i) {
                const double z = (j - 0.5 * (grid.nz - 1)) * grid.dx;
                // 2% down the channel; a V across it, so it has banks.
                bed[grid.at(i, j)] = 1.0 - 0.02 * grid.dx * i + 0.35 * std::abs(z);
            }
    }
};

ShallowWater fedChannel(double discharge) {
    Channel ch;
    ShallowWater water(ch.grid, ch.bed);
    water.addInflow({"river", Edge::West, 4, 11, discharge});
    water.addOutflow({"mouth", Edge::East, 0, ch.grid.nz - 1});
    water.resetLedger();
    return water;
}

// The level of the river at a cross-section: the surface over its deepest
// point. Not the highest wet surface across the section -- a reservoir that
// has drained leaves its banks damp with a film microns thick, standing at the
// old level, and that film is not the river.
double levelAt(const ShallowWater &water, int i) {
    const Grid &g = water.grid();
    std::size_t deepest = g.at(i, 0);
    for (int j = 1; j < g.nz; ++j)
        if (water.bed(g.at(i, j)) < water.bed(deepest)) deepest = g.at(i, j);
    return water.wet(deepest) ? water.surface(deepest) : -kInf;
}

// 4. A river fed at one end and drained at the other settles to passing on
// what it is given, and the ledger says where every cubic metre went.
void aRiverSettlesToPassingWhatItIsGiven() {
    const double q = 0.12;
    ShallowWater water = fedChannel(q);
    for (int k = 0; k < 90; ++k) water.advance(1.0);
    const double in = water.inflowRate(), out = water.outflowRate();
    const double v1 = water.volume();
    for (int k = 0; k < 10; ++k) water.advance(1.0);
    const double drift = (water.volume() - v1) / 10.0;
    std::cout << "    after 100 s: " << in << " m^3/s in, " << water.outflowRate()
              << " m^3/s out, storage changing " << drift << " m^3/s, residual "
              << water.residual() << " m^3 of " << water.volume() << "\n";
    near(in, q, 1.0e-12, "the source delivers what it was given");
    near(out, q, 0.03 * q, "the mouth passes it on, once the channel is full");
    near(drift, 0.0, 0.03 * q, "and the storage has stopped changing");
    near(water.residual(), 0.0, 1.0e-10 * std::max(1.0, water.volume()),
         "every cubic metre accounted: in minus out is the change in storage");
}

// 5. A dam backs the water up, and taking it away lets the water go. The dam
// is a row of solid tops across the channel, the way a row of blocks resting
// on the bed looks to the water.
void aDamBacksWaterUpAndAnOutletDrainsIt() {
    const double q = 0.12;
    ShallowWater water = fedChannel(q);
    for (int k = 0; k < 80; ++k) water.advance(1.0);
    const int upstream = 30;
    const double before = levelAt(water, upstream);
    const double volume_before = water.volume();
    const Grid &g = water.grid();
    std::vector<double> dam(g.cells(), -kInf);
    for (int j = 0; j < g.nz; ++j)
        for (int i = 50; i < 52; ++i) dam[g.at(i, j)] = water.terrain(g.at(i, j)) + 0.5;
    water.setObstacles(dam);
    near(water.volume(), volume_before, 1.0e-12 * volume_before,
         "putting the dam in displaces water and makes or destroys none");
    for (int k = 0; k < 30; ++k) water.advance(1.0);
    const double dammed = levelAt(water, upstream);
    const double out_dammed = water.outflowRate();
    std::cout << "    level 5 m upstream: " << before << " m, dammed " << dammed
              << " m after 30 s; outflow " << out_dammed << " m^3/s\n";
    require(dammed > before + 0.05, "the dam raised the upstream level");
    require(out_dammed < 0.5 * q, "and the mouth downstream went short");
    // An outlet: take the dam away and the stored water goes.
    water.setObstacles(std::vector<double>(g.cells(), -kInf));
    const double full = water.volume();
    for (int k = 0; k < 40; ++k) water.advance(1.0);
    const double drained = levelAt(water, upstream);
    std::cout << "    dam gone: level " << drained << " m after 40 s, storage " << full
              << " -> " << water.volume() << " m^3\n";
    require(drained < dammed - 0.05, "released, the level fell");
    near(water.residual(), 0.0, 1.0e-10 * std::max(1.0, water.volume()), "the ledger closes");
}

// 6. Digging under water makes no water and filling destroys none: a column
// keeps its depth over a lowered bed, and what no longer fits over a raised
// bed is moved next door.
void diggingAndFillingUnderWaterConserveIt() {
    Grid g{32, 32, 0.25, 0.0, 0.0};
    ShallowWater water(g, bowl(g));
    for (std::size_t c = 0; c < g.cells(); ++c) water.setSurface(c, 1.0);
    water.resetLedger();
    const double v0 = water.volume();
    for (int j = 12; j < 20; ++j)
        for (int i = 12; i < 20; ++i) water.setTerrain(g.at(i, j), water.terrain(g.at(i, j)) - 0.4);
    near(water.volume(), v0, 1.0e-12 * v0, "digging under water keeps the water");
    for (int j = 4; j < 8; ++j)
        for (int i = 4; i < 8; ++i) water.setTerrain(g.at(i, j), water.terrain(g.at(i, j)) + 0.8);
    near(water.volume(), v0, 1.0e-12 * v0, "filling under water moves the water, destroys none");
    for (int k = 0; k < 120; ++k) water.advance(1.0 / 30.0);
    near(water.volume(), v0, 1.0e-11 * v0, "and it stays that way while it settles");
}

// 7. The clock: no substep is ever longer than the stability limit allows.
void noSubstepExceedsTheStabilityLimit() {
    ShallowWater water = fedChannel(0.3);
    const Grid &g = water.grid();
    double worst = 0.0;
    for (int k = 0; k < 600; ++k) {
        const double speed_before = [&] {
            double fastest = 0.0;
            for (std::size_t c = 0; c < g.cells(); ++c) {
                if (!water.wet(c)) continue;
                const double h = water.depth(c);
                fastest = std::max(fastest, std::max(std::abs(water.velocityX(c)),
                                                     std::abs(water.velocityZ(c))) + std::sqrt(9.81 * h));
            }
            return fastest;
        }();
        const int n = water.advance(1.0 / 60.0);
        (void)n;
        if (speed_before > 0.0)
            worst = std::max(worst, water.stats().last_substep_s * speed_before / g.dx);
    }
    std::cout << "    worst Courant number " << worst << " against a limit of 0.25\n";
    require(worst <= 0.25 + 1.0e-9, "every substep within the CFL limit");
}

// 8. Only water costs anything: a dry valley computes nothing, a puddle in one
// corner computes its own tile and its neighbours.
void onlyWaterCostsAnything() {
    Grid g{160, 128, 0.25, 0.0, 0.0};
    ShallowWater water(g, std::vector<double>(g.cells(), 1.0));
    water.advance(0.1);
    require(water.stats().active_cells == 0, "a dry valley computes nothing");
    for (int j = 2; j < 6; ++j)
        for (int i = 2; i < 6; ++i) water.setDepth(g.at(i, j), 0.2);
    water.advance(0.1);
    std::cout << "    a puddle in one corner: " << water.stats().active_cells << " of "
              << g.cells() << " columns computed, " << water.stats().active_tiles << " of "
              << water.stats().tiles << " tiles\n";
    require(water.stats().active_cells <= 4u * 16u * 16u, "a corner costs its own tile and neighbours");
}

// ---- bodies in the water ------------------------------------------------------

// Still water `level` deep over flat ground.
ShallowWater stillWater(double level, int nx = 48, int nz = 32) {
    Grid g{nx, nz, 0.25, 0.0, 0.0};
    ShallowWater water(g, std::vector<double>(g.cells(), 0.0));
    for (std::size_t c = 0; c < g.cells(); ++c) water.setSurface(c, level);
    return water;
}

BodyInWater box(const std::string &name, Vec3 size, Vec3 at, double density) {
    BodyInWater b;
    b.name = name;
    b.shape = BodyInWater::Shape::Box;
    b.dimensions_m = size;
    b.com_m = at;
    b.density_kg_m3 = density;
    b.mass_kg = density * size.x * size.y * size.z;
    return b;
}

// 9. Buoyancy is the pressure on the underside, and nothing else: an oak log
// comes to rest with 700/1000 of itself under water, and an iron one finds no
// such place and sinks.
void oakFloatsAtSeventyPercentAndIronSinks() {
    ShallowWater water = stillWater(1.0, 64, 32);
    WaterCoupling coupling;
    std::vector<Reaction> reactions;
    const Vec3 size{1.6, 0.24, 0.24};
    const auto lift = [&](double density, double draft) {
        BodyInWater log = box("log", size, {8.0, 1.0 - draft + 0.5 * size.y, 4.0}, density);
        const auto f = coupling.forces(water, {log}, reactions);
        return f.empty() ? 0.0 : f.front().force_n.y;
    };
    // Where the water holds it up: bisect for the draft where lift = weight.
    const double oak = 700.0, weight = oak * size.x * size.y * size.z * 9.81;
    double lo = 0.0, hi = size.y;
    for (int k = 0; k < 60; ++k) {
        const double mid = 0.5 * (lo + hi);
        (lift(oak, mid) < weight ? lo : hi) = mid;
    }
    const double draft = 0.5 * (lo + hi);
    std::cout << "    oak (700 kg/m^3): floats with " << draft / size.y * 100.0
              << "% of its height under water\n";
    near(draft / size.y, 0.7, 1.0e-6, "oak floats 70 percent under");
    // Iron: fully under water the pressure is rho g V, a seventh of its weight.
    const double iron = 7870.0;
    const double full = lift(iron, size.y + 0.1);
    const double iron_weight = iron * size.x * size.y * size.z * 9.81;
    near(full, 1000.0 * 9.81 * size.x * size.y * size.z, 1.0e-6 * full,
         "wholly under water, the lift is the weight of the water it displaces");
    require(full < iron_weight, "which is less than iron weighs: it sinks");
    std::cout << "    iron (7870 kg/m^3): lift " << full << " N against a weight of " << iron_weight
              << " N\n";
}

// 10. A ball displaces exactly its own volume, not the volume of whatever
// polyhedron it is drawn with.
void aBallDisplacesItsOwnVolume() {
    ShallowWater water = stillWater(2.0);
    WaterCoupling coupling;
    std::vector<Reaction> reactions;
    BodyInWater ball;
    ball.name = "ball";
    ball.shape = BodyInWater::Shape::Sphere;
    ball.dimensions_m = {0.3, 0.3, 0.3};
    ball.density_kg_m3 = 2400.0;
    ball.com_m = {6.0, 1.0, 4.0};
    const auto f = coupling.forces(water, {ball}, reactions);
    const double volume = 3.14159265358979323846 / 6.0 * 0.027;
    require(!f.empty(), "the ball is in the water");
    near(f.front().force_n.y, 1000.0 * 9.81 * volume, 1.0e-9 * 1000.0 * 9.81 * volume,
         "wholly under water it is lifted by the weight of its own volume of water");
    near(f.front().submerged_m3, volume, 1.0e-12, "and it says it displaces that much");
    ball.com_m.y = 2.0;   // half in, half out
    const auto half = coupling.forces(water, {ball}, reactions);
    near(half.front().force_n.y, 0.5 * 1000.0 * 9.81 * volume, 0.005 * 1000.0 * 9.81 * volume,
         "half in, half the lift");
}

// 11. A dam's load: a block resting across a channel with water standing a
// metre deep on one side and 0.4 m on the other is pushed downstream by the
// difference, 1/2 rho g w (h1^2 - h2^2), and not lifted at all.
void aDamBlockCarriesTheDifferenceOfItsTwoSides() {
    Grid g{40, 12, 0.25, 0.0, 0.0};
    ShallowWater water(g, std::vector<double>(g.cells(), 0.0));
    // A block 0.5 m thick in x, the whole channel wide, 1.4 m tall, on the bed.
    BodyInWater block = box("dam block", {0.5, 1.4, 1.0}, {5.0, 0.7, 1.375}, 2400.0);
    WaterCoupling coupling;
    water.setObstacles(coupling.obstacleTops(water, {block}));
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < g.nx; ++i) {
            const std::size_t c = g.at(i, j);
            if (water.bed(c) > 0.5) continue;   // the block
            water.setSurface(c, g.xOf(i) < 5.0 ? 1.0 : 0.4);
        }
    std::vector<Reaction> reactions;
    const auto f = coupling.forces(water, {block}, reactions);
    require(!f.empty(), "the block is in the water");
    const double expected = 0.5 * 1000.0 * 9.81 * 1.0 * (1.0 * 1.0 - 0.4 * 0.4);
    std::cout << "    pushed " << f.front().force_n.x << " N downstream (1/2 rho g w (h1^2-h2^2) = "
              << expected << " N), lifted " << f.front().force_n.y << " N\n";
    near(f.front().force_n.x, expected, 1.0e-6 * expected, "the load is the difference of the two sides");
    near(f.front().force_n.y, 0.0, 1.0e-9, "and nothing gets under a block sealed on the bed");
}

// 12. Drag is the water moving past, relative to the body: a body held still in
// a current feels it, and one carried at the water's own speed does not.
void dragIsRelativeMotion() {
    ShallowWater water = stillWater(1.0);
    const Grid &g = water.grid();
    for (std::size_t c = 0; c < g.cells(); ++c) water.setDischarge(c, 1.0 * water.depth(c), 0.0);  // 1 m/s
    WaterCoupling coupling;
    std::vector<Reaction> reactions;
    BodyInWater held = box("block", {0.3, 0.3, 0.3}, {6.0, 0.5, 4.0}, 2400.0);
    const auto still = coupling.forces(water, {held}, reactions);
    const double form = 0.5 * 1000.0 * 1.0 * 0.09 * 1.0;   // 1/2 rho Cd A v^2
    require(!still.empty(), "in the water");
    std::cout << "    held against 1 m/s: drag " << still.front().drag_n.x << " N (form drag alone "
              << form << " N); handed back to the water: " << reactions.size() << " patches\n";
    require(still.front().drag_n.x > form && still.front().drag_n.x < 1.2 * form,
            "form drag on the upstream face, and a little skin friction");
    double given = 0.0;
    for (const Reaction &r : reactions) given += r.fx_n;
    near(given, still.front().drag_n.x, 1.0e-9, "every newton of drag is handed back to the water");
    BodyInWater carried = held;
    carried.velocity_m_s = {1.0, 0.0, 0.0};
    const auto moving = coupling.forces(water, {carried}, reactions);
    near(moving.front().drag_n.x, 0.0, 1.0e-9, "carried with the stream, it feels no drag");
}

// 13. What holds water back: a stone block on the bed does; an oak log on the
// bed does not (the water lifts it); a stone block with a hand's width of water
// under it lets water through.
void onlySinkersRestingOnTheBedHoldWaterBack() {
    ShallowWater water = stillWater(0.5);
    WaterCoupling coupling;
    const BodyInWater stone = box("stone", {0.5, 0.8, 0.5}, {3.0, 0.4, 3.0}, 2400.0);
    const BodyInWater oak = box("oak", {0.5, 0.8, 0.5}, {6.0, 0.4, 3.0}, 700.0);
    const BodyInWater raised = box("raised", {0.5, 0.8, 0.5}, {9.0, 0.6, 3.0}, 2400.0);
    const std::vector<double> tops = coupling.obstacleTops(water, {stone, oak, raised});
    const Grid &g = water.grid();
    const auto topAt = [&](double x, double z) { return tops[g.at(static_cast<int>(std::lround(x / g.dx)),
                                                                   static_cast<int>(std::lround(z / g.dx)))]; };
    near(topAt(3.0, 3.0), 0.8, 1.0e-12, "the stone block raises the bed to its top");
    require(!std::isfinite(topAt(6.0, 3.0)), "the oak does not: the water would lift it");
    require(!std::isfinite(topAt(9.0, 3.0)), "and water gets under a block standing 0.2 m clear");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"a lake at rest stays exactly at rest", aLakeAtRestStaysExactlyAtRest},
        {"a closed basin conserves water", aClosedBasinConservesWater},
        {"a flood front advances over dry ground", aFloodFrontAdvancesOverDryGround},
        {"a river settles to passing what it is given", aRiverSettlesToPassingWhatItIsGiven},
        {"a dam backs water up and an outlet drains it", aDamBacksWaterUpAndAnOutletDrainsIt},
        {"digging and filling under water conserve it", diggingAndFillingUnderWaterConserveIt},
        {"no substep exceeds the stability limit", noSubstepExceedsTheStabilityLimit},
        {"only water costs anything", onlyWaterCostsAnything},
        {"oak floats at seventy percent and iron sinks", oakFloatsAtSeventyPercentAndIronSinks},
        {"a ball displaces its own volume", aBallDisplacesItsOwnVolume},
        {"a dam block carries the difference of its two sides", aDamBlockCarriesTheDifferenceOfItsTwoSides},
        {"drag is relative motion", dragIsRelativeMotion},
        {"only sinkers resting on the bed hold water back", onlySinkersRestingOnTheBedHoldWaterBack},
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
