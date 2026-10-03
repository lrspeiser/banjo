// Terrain and water inside a live world -- the rigid world the playground's room
// runs -- measured the way the owner asked for it:
//
//   a closed basin conserves water, with a log bobbing in it;
//   a lake at rest stays at rest;
//   a dam of loose stone blocks raises the river upstream of it;
//   a new outlet drains the pond;
//   a block cut from the rock is neither lost nor duplicated;
//   digging one corner does not activate the rest -- columns, colliders,
//     bodies and water, counted;
//   a boulder falls when the ground under it is dug;
//   an oak log floats and drifts with the current, and an iron block sinks;
//   water carried into a world opened again is the same water;
//   and the whole valley runs inside the owner's 1.1x realtime rule, with its
//   worst step and active cells reported.
//
// tests/water_tests.cpp and tests/terrain_tests.cpp are the two halves on
// their own; this is the two of them where the person will see them.
#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "terrain/Environment.hpp"
#include "terrain/GroundWork.hpp"
#include "thermo/ThermoWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <functional>
#include <iostream>
#include <limits>
#include <memory>
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
constexpr double kCell = 0.04;        // the yard's cell

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message) + ": actual=" + std::to_string(actual) +
                                 " expected=" + std::to_string(expected) +
                                 " tolerance=" + std::to_string(tolerance));
}

Json box(const std::string &name, const std::string &material, Vec3 size, Vec3 at, bool anchored = false) {
    return {{"name", name}, {"shape", "box"}, {"material", material},
            {"dimensions_m", {size.x, size.y, size.z}}, {"center_m", {at.x, at.y, at.z}},
            {"anchored", anchored}};
}

Json ball(const std::string &name, const std::string &material, double diameter, Vec3 at) {
    return {{"name", name}, {"shape", "sphere"}, {"material", material},
            {"dimensions_m", {diameter, diameter, diameter}}, {"center_m", {at.x, at.y, at.z}}};
}

std::unique_ptr<LiveWorld> open(const Json &scene, const std::string &saved = {}) {
    const std::string text = scene.dump();
    TileImpactRequest request;
    request.cell_size_m = kCell;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(text);
    readSceneSettings(text, request);
    return saved.empty() ? LiveWorld::open(request) : LiveWorld::open(request,saved);
}

// Step for `seconds` of world time, answering every break by running it.
void run(LiveWorld &world, double seconds) {
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    for (int done = 0; done < steps;) {
        world.step(kDt);
        if (world.steppedBack()) {
            for (const std::string &name : world.breakable()) (void)world.fracture(name);
            continue;
        }
        ++done;
    }
}

LiveBodyPose poseOf(const LiveWorld &world, const std::string &name) {
    for (const LiveBodyPose &pose : world.poses())
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

// The valley, as generated -- used to place things on it before opening a
// world with them.
struct Valley {
    std::unique_ptr<terrain::Environment> land;
    Json block;
    Valley() : block({{"generate", "valley"}}) {
        land = terrain::Environment::fromScene(Json{{"terrain", block}}.dump());
    }
    const terrain::TerrainField &ground() const { return land->terrain(); }
    const terrain::Mine &mine() const { return land->landscape().mine; }
    const water::ShallowWater &water() const { return *land->water(); }
    double groundAt(double x, double z) const { return ground().heightAt(x, z); }
    // Across the river at x: the deepest FLOWING column, its bed and surface,
    // and the flowing band's edges. The river is the water that moves: the
    // pond beside it is deeper and still, and is not the river.
    struct Section { double z{}, bed{}, surface{}, left{}, right{}; };
    Section riverAt(double x) const {
        const auto &g = ground().grid();
        const int i = std::clamp(static_cast<int>(std::lround((x - g.x0) / g.dx)), 0, g.nx - 1);
        Section s;
        double deepest = -1.0;
        double left = std::numeric_limits<double>::infinity(), right = -left;
        for (int j = 0; j < g.nz; ++j) {
            const std::size_t c = g.at(i, j);
            if (!(water().depth(c) > 0.02)) continue;
            if (!(std::hypot(water().velocityX(c), water().velocityZ(c)) > 0.03)) continue;
            left = std::min(left, g.zOf(j));
            right = std::max(right, g.zOf(j));
            if (water().depth(c) > deepest) {
                deepest = water().depth(c);
                s.z = g.zOf(j);
                s.bed = water().bed(c);
                s.surface = water().surface(c);
            }
        }
        require(deepest > 0.0, "the river runs past x = " + std::to_string(x));
        s.left = left;
        s.right = right;
        return s;
    }
    const terrain::Lake &pond() const { return land->landscape().lakes.front(); }
    // A marker stone out of the way on the hill, because a world is opened
    // from its bodies.
    Json marker() const {
        const auto &g = ground().grid();
        const double x = g.x0 + 1.0, z = g.z0 + 1.0;
        return box("marker stone", "concrete", {0.16, 0.16, 0.16}, {x, groundAt(x, z) + 0.08, z}, true);
    }
    Json scene(Json bodies, const Json &extra_terrain = Json::object()) const {
        bodies.push_back(marker());
        Json terrain = block;
        for (const auto &item : extra_terrain.items()) terrain[item.key()] = item.value();
        return {{"plasticity", true}, {"bodies", bodies}, {"terrain", terrain}};
    }
};

// The level of the river over its deepest point at x, in a running world.
double riverLevel(const LiveWorld &world, double x) {
    const water::ShallowWater &w = *world.environment()->water();
    const auto &g = w.grid();
    const int i = std::clamp(static_cast<int>(std::lround((x - g.x0) / g.dx)), 0, g.nx - 1);
    double deepest = -1.0, level = std::numeric_limits<double>::quiet_NaN();
    for (int j = 0; j < g.nz; ++j) {
        const std::size_t c = g.at(i, j);
        if (w.depth(c) > deepest) { deepest = w.depth(c); level = w.surface(c); }
    }
    return level;
}

double pondLevel(const LiveWorld &world, const terrain::Lake &pond) {
    const water::ShallowWater &w = *world.environment()->water();
    const auto c = world.environment()->terrain().cellAt(pond.x_m, pond.z_m);
    return w.surface(*c);
}

// ---------------------------------------------------------------------------

// 1. A closed basin keeps its water, with a log bobbing in it: the log takes
// momentum from the water and gives it back, and makes and destroys none.
void aClosedBasinConservesWaterWithALogInIt() {
    const Json scene = {{"plasticity", true},
                        {"bodies", {box("log", "oak", {1.2, 0.24, 0.24}, {0.0, 1.3, 0.0}),
                                    box("marker stone", "concrete", {0.16, 0.16, 0.16}, {-7.5, 2.0, -5.5}, true)}},
                        {"terrain", {{"generate", {{"kind", "basin"}, {"nx", 64}, {"nz", 48},
                                                   {"lake_level_m", 1.0}}}}}};
    auto world = open(scene);
    const water::ShallowWater &w = *world->environment()->water();
    const double v0 = w.volume();
    double worst = 0.0;
    for (int k = 0; k < 40; ++k) {
        run(*world, 0.25);
        worst = std::max(worst, std::abs(w.volume() - v0));
    }
    const LiveBodyPose log = poseOf(*world, "log");
    std::cout << "    10 s with a log dropped in: volume " << v0 << " m^3, worst drift " << worst
              << " m^3; the water took " << w.ledger().impulse_in_x_n_s << ", "
              << w.ledger().impulse_in_z_n_s << " N s back from the log; log at y=" << log.position_m.y << "\n";
    require(worst < 1.0e-10 * v0, "the basin keeps its water to rounding");
    require(w.ledger().numerical_m3 < 1.0e-12, "nothing was put back to keep a depth positive");
    require(log.position_m.y > 0.9 && log.position_m.y < 1.05, "the log floats at the lake's surface");
}

// 2. A lake at rest stays at rest in a live world: no body in it, nothing moves.
void aLakeAtRestStaysAtRest() {
    const Json scene = {{"plasticity", true},
                        {"bodies", {box("marker stone", "concrete", {0.16, 0.16, 0.16}, {-7.5, 2.0, -5.5}, true)}},
                        {"terrain", {{"generate", {{"kind", "basin"}, {"nx", 64}, {"nz", 48},
                                                   {"lake_level_m", 1.0}}}}}};
    auto world = open(scene);
    const water::ShallowWater &w = *world->environment()->water();
    std::vector<double> before(w.grid().cells());
    for (std::size_t c = 0; c < before.size(); ++c) before[c] = w.surface(c);
    run(*world, 10.0);
    double moved = 0.0, fastest = 0.0;
    for (std::size_t c = 0; c < before.size(); ++c) {
        moved = std::max(moved, std::abs(w.surface(c) - before[c]));
        fastest = std::max(fastest, std::hypot(w.velocityX(c), w.velocityZ(c)));
    }
    std::cout << "    10 s: largest change of surface " << moved << " m, fastest water " << fastest << " m/s\n";
    require(moved == 0.0 && fastest == 0.0, "a lake at rest stays exactly at rest in a live world");
}

// 3. A dam of loose stone blocks across the river raises the level upstream.
void aDamOfLooseBlocksRaisesTheRiver() {
    Valley v;
    const double dam_x = -1.0, probe_x = -4.0;
    const Valley::Section s = v.riverAt(dam_x);
    Json bodies = Json::array();
    const double side = 0.48, tall = 0.96;
    int k = 0;
    for (double z = s.left - 0.5; z <= s.right + 0.5 + 1e-9; z += side) {
        // Rest each block on the highest ground under it, so it is standing on
        // the bed and not in it.
        double top = -1e9;
        for (double dx = -0.2; dx <= 0.2; dx += 0.1)
            for (double dz = -0.2; dz <= 0.2; dz += 0.1) top = std::max(top, v.groundAt(dam_x + dx, z + dz));
        bodies.push_back(box("dam block " + std::to_string(++k), "concrete", {side, tall, side},
                             {dam_x, top + 0.5 * tall + 0.005, z}));
    }
    auto world = open(v.scene(bodies));
    run(*world, 1.0);
    const double before = riverLevel(*world, probe_x);
    run(*world, 30.0);
    const double after = riverLevel(*world, probe_x);
    double moved = 0.0;
    for (int b = 1; b <= k; ++b)
        moved = std::max(moved, std::abs(poseOf(*world, "dam block " + std::to_string(b)).position_m.x - dam_x));
    std::cout << "    " << k << " concrete blocks across the river at x=" << dam_x << ": level 3 m upstream "
              << before << " m -> " << after << " m after 30 s; the blocks moved at most " << moved
              << " m downstream\n";
    require(after > before + 0.1, "the dam raised the river upstream of it");
}

// 4. A new outlet drains the pond: dig through its bank to the river, lower
// than the pond, and the pond's level falls.
void aNewOutletDrainsThePond() {
    Valley v;
    const terrain::Lake &pond = v.pond();
    auto world = open(v.scene(Json::array()));
    run(*world, 1.0);
    const double before = pondLevel(*world, pond);
    const Valley::Section river = v.riverAt(pond.x_m);
    const terrain::EditEffect dug = world->dig(pond.x_m, pond.z_m, pond.x_m, river.z, 0.75, 0.7);
    run(*world, 30.0);
    const double after = pondLevel(*world, pond);
    std::cout << "    pond at " << before << " m; dug " << dug.edit.moved.sand_m3 + dug.edit.moved.soil_m3
              << " m^3 from it to the river (" << dug.edit.cells.size() << " columns, "
              << dug.chunks_rebuilt << " colliders rebuilt in " << dug.rebuild_ms
              << " ms); 30 s later the pond is at " << after << " m\n";
    require(after < before - 0.1, "the new outlet drained the pond");
    const water::ShallowWater &w = *world->environment()->water();
    near(w.residual(), 0.0, 1.0e-9 * std::max(1.0, w.volume()), "and the water ledger closes");
}

// 5. A block cut out of the rock is neither lost nor duplicated: the ground
// loses exactly its volume, and when the world is opened again with the cut
// and the block in it, the block holds exactly that much stone.
void aCutBlockIsNeitherLostNorDuplicated() {
    Valley v;
    // Bare, level rock: the top of the knoll. A block's sides are whole
    // cells, so at 0.25 m columns and 0.04 m cells it is 4 columns, 1 m, a side.
    const auto &g = v.ground().grid();
    // Rock all the way down, not only on top: the valley has a vein in its
    // knoll and a bed of clay under it now, and a block of either is refused
    // rather than counted as rock (docs/earth-and-mining-plan.md).
    const auto rockThroughout = [&](std::size_t c, double depth) {
        terrain::Run runs[terrain::TerrainField::kRunsMost];
        const int count = v.ground().runsOf(c, runs);
        const double top = v.ground().rockTop(c), bottom = top - depth;
        for (int k = 0; k < count; ++k)
            if (runs[k].top_m > bottom && runs[k].top_m <= top + 1.0e-9 &&
                !terrain::isRockLike(runs[k].kind))
                return false;
        return true;
    };
    double at_x = 0.0, at_z = 0.0;
    bool found = false;
    for (int j = 3; j < g.nz - 3 && !found; ++j)
        for (int i = 3; i < g.nx - 3 && !found; ++i) {
            bool bare = true;
            for (int dj = -2; dj <= 2; ++dj)
                for (int di = -2; di <= 2; ++di)
                    bare = bare && v.ground().surface(g.at(i + di, j + dj)) == terrain::Surface::Rock &&
                           v.ground().slopeDeg(g.at(i + di, j + dj)) < 15.0 &&
                           rockThroughout(g.at(i + di, j + dj), 0.45);
            if (bare) { at_x = g.xOf(i); at_z = g.zOf(j); found = true; }
        }
    require(found, "there is bare, level rock to cut, rock all the way down");
    auto world = open(v.scene(Json::array()));
    const terrain::Volumes before = world->environment()->terrain().volumes();
    std::string why;
    // A footprint that is not whole cells is refused, and says what would do.
    require(!world->cutBlock(at_x, at_z, 2, 2, 0.4, &why).has_value() && why.find("4 columns") != std::string::npos,
            "a half-metre block of 0.04 m cells is refused, with the size that would do: " + why);
    const auto block = world->cutBlock(at_x, at_z, 4, 4, 0.4, &why);
    require(block.has_value(), "the cut is made: " + why);
    const terrain::Volumes after = world->environment()->terrain().volumes();
    near(before.rock_m3 - after.rock_m3, block->volume_m3, 1.0e-9, "the ground lost the block's volume");
    // The same scene, opened again with the cut and the block as a body.
    Json bodies = Json::array();
    bodies.push_back(box("cut stone", "concrete", block->size_m, block->center_m));
    Json edits = Json::array();
    edits.push_back({{"cut", {{"at_m", {at_x, at_z}}, {"cells", {4, 4}}, {"height_m", 0.4}}}});
    auto again = open(v.scene(bodies, {{"edits", edits}}));
    const terrain::Volumes reopened = again->environment()->terrain().volumes();
    const LiveBodyPose stone = poseOf(*again, "cut stone");
    const double body = stone.dimensions_m.x * stone.dimensions_m.y * stone.dimensions_m.z;
    std::cout << "    cut " << block->volume_m3 << " m^3 (" << block->mass_kg << " kg) of rock; reopened: "
              << "ground " << reopened.rock_m3 << " m^3 + the stone " << body << " m^3 = "
              << reopened.rock_m3 + body << " m^3 against " << before.rock_m3 << " m^3 before\n";
    near(reopened.rock_m3, after.rock_m3, 1.0e-9, "the reopened ground has the same hole");
    near(reopened.rock_m3 + body, before.rock_m3, 1.0e-6, "ground and block together are the rock there was");
}

// 6. Digging one corner does not activate the rest. Four boulders at rest in
// the valley's four quarters, a log in the river; a dig in one dry corner.
// Counted: the columns the ground asked about, the colliders rebuilt, the
// bodies that woke, and the water the corner has nothing to do with.
void diggingOneCornerDoesNotActivateTheRest() {
    Valley v;
    const auto &g = v.ground().grid();
    Json bodies = Json::array();
    const double quarter_x = 0.25 * (g.nx - 1) * g.dx, quarter_z = 0.25 * (g.nz - 1) * g.dx;
    int n = 0;
    for (const double sx : {-1.0, 1.0})
        for (const double sz : {-1.0, 1.0}) {
            const double x = sx * quarter_x, z = sz * quarter_z;
            bodies.push_back(ball("boulder " + std::to_string(++n), "concrete", 0.48,
                                  {x, v.groundAt(x, z) + 0.26, z}));
        }
    auto world = open(v.scene(bodies));
    run(*world, 4.0);   // let everything come to rest
    const unsigned awake_before = world->awakeBodies();
    const std::size_t active_before = world->environment()->stats().water_active_cells;
    // The far corner: dry hillside, nowhere near the water or a boulder.
    const double cx = g.x0 + 2.5, cz = g.z0 + 2.5;
    const terrain::EditEffect dug = world->dig(cx, cz, cx + 1.0, cz, 1.0, 0.5);
    run(*world, 3.0);
    const unsigned awake_after = world->awakeBodies();
    const terrain::EnvironmentStats &stats = world->environment()->stats();
    std::cout << "    dug " << dug.edit.cells.size() << " columns in one corner of " << g.cells()
              << ": the ground asked about " << stats.ground_checked << " column(s) settling it; "
              << dug.chunks_rebuilt << " of " << stats.chunks << " colliders rebuilt ("
              << dug.rebuild_ms << " ms); bodies woken by it: " << dug.bodies_woken
              << "; awake bodies " << awake_before << " -> " << awake_after << "; water columns computed "
              << active_before << " -> " << stats.water_active_cells << " of " << stats.water_cells << "\n";
    require(dug.chunks_rebuilt <= 2, "only the corner's colliders were rebuilt");
    require(dug.bodies_woken == 0, "nothing far from the dig woke");
    require(awake_after <= awake_before, "no body is awake that was not");
    require(stats.ground_checked < 600, "the ground asked about the corner, not the valley");
}

// 7. A boulder falls when the ground under it is dug. A block of stone, not a
// ball: a ball on the floodplain's gentle undulations (up to about 7 degrees)
// rolls, because soil's rolling resistance only holds a ball below about 3,
// and a boulder that never comes to rest cannot show that the dig is what
// moved it.
void aBoulderFallsWhenDugUnder() {
    Valley v;
    // On the river's sandy bank, a stride from the water.
    const Valley::Section s = v.riverAt(-8.0);
    const double x = -8.0, z = s.left - 1.2;
    const Vec3 size{0.56, 0.48, 0.56};
    double rest = -1e9;
    for (double dx = -0.28; dx <= 0.28; dx += 0.07)
        for (double dz = -0.28; dz <= 0.28; dz += 0.07) rest = std::max(rest, v.groundAt(x + dx, z + dz));
    auto world = open(v.scene(Json::array({box("boulder", "concrete", size, {x, rest + 0.5 * size.y + 0.005, z})})));
    // Until it has come to rest and the solver has stopped stepping it: the
    // point is that the dig is what wakes it.
    double waited = 0.0;
    while (world->awakeBodies() > 0 && waited < 15.0) { run(*world, 0.5); waited += 0.5; }
    require(world->awakeBodies() == 0, "the boulder came to rest and went to sleep");
    const LiveBodyPose rested = poseOf(*world, "boulder");
    // Dig under its edge, on the river side.
    const terrain::EditEffect dug = world->dig(x, z + 0.25, x, z + 0.8, 0.9, 0.6);
    run(*world, 4.0);
    const LiveBodyPose fell = poseOf(*world, "boulder");
    std::cout << "    boulder resting at y=" << rested.position_m.y << "; dug " << dug.edit.cells.size()
              << " columns beside and under it (woke " << dug.bodies_woken << " body); 4 s later y="
              << fell.position_m.y << " (dropped " << rested.position_m.y - fell.position_m.y << " m, moved "
              << std::hypot(fell.position_m.x - rested.position_m.x, fell.position_m.z - rested.position_m.z)
              << " m sideways)\n";
    require(dug.bodies_woken >= 1, "the dig woke the boulder it undermined");
    require(fell.position_m.y < rested.position_m.y - 0.15, "and the boulder fell into the hole");
}

// 8. An oak log floats and drifts downstream; an iron block of the same size
// sinks to the bed.
void anOakLogDriftsAndIronSinks() {
    Valley v;
    const double x = -13.0;
    const Valley::Section s = v.riverAt(x);
    const Vec3 size{0.96, 0.24, 0.24};
    const Valley::Section t = v.riverAt(-10.0);
    auto world = open(v.scene(Json::array({box("oak log", "oak", size, {x, s.surface + 0.2, s.z}),
                                           box("iron bar", "iron", size, {-10.0, t.surface + 0.2, t.z})})));
    run(*world, 1.5);
    const LiveBodyPose settled = poseOf(*world, "oak log");
    run(*world, 20.0);
    const LiveBodyPose drifted = poseOf(*world, "oak log");
    const LiveBodyPose iron = poseOf(*world, "iron bar");
    const Valley::Section ends = v.riverAt(drifted.position_m.x);
    const double iron_bed = v.groundAt(iron.position_m.x, iron.position_m.z);
    std::cout << "    oak log: from x=" << settled.position_m.x << " to x=" << drifted.position_m.x
              << " in 20 s (" << (drifted.position_m.x - settled.position_m.x) / 20.0
              << " m/s), riding at y=" << drifted.position_m.y << " over a surface near " << ends.surface
              << "; iron bar resting at y=" << iron.position_m.y << " on a bed at " << iron_bed << "\n";
    require(drifted.position_m.x > settled.position_m.x + 3.0, "the log drifted downstream");
    require(iron.position_m.y < iron_bed + 0.2, "the iron sank to the bed");
}

// 9. Water carried into a world opened again from an edited scene is the same
// water: a dig applied at the reopen changes the ground under it, not how much
// there is.
void waterCarriedIntoAReopenedWorldIsTheSame() {
    Valley v;
    auto world = open(v.scene(Json::array()));
    run(*world, 5.0);
    const water::ShallowWater &w = *world->environment()->water();
    const double volume = w.volume();
    const Json state = Json::parse(world->environmentState());
    Json edits = Json::array();
    edits.push_back({{"dig", {{"from_m", {-6.0, v.riverAt(-6.0).z}}, {"to_m", {-6.0, v.riverAt(-6.0).z + 2.0}},
                               {"width_m", 0.8}, {"depth_m", 0.5}}}});
    Json scene = v.scene(Json::array(), {{"edits", edits}});
    scene["water"] = {{"state", state}};
    auto again = open(scene);
    const double carried = again->environment()->water()->volume();
    std::cout << "    " << volume << " m^3 carried; the reopened world holds " << carried
              << " m^3 (difference " << carried - volume << ")\n";
    near(carried, volume, 1.0e-9 * volume, "the same water, over the dug ground");
    near(again->environment()->water()->ledger().inflow_m3, w.ledger().inflow_m3, 1e-9,
         "and the same ledger, carried with it");
}

// 10. The valley with everything in it, run for a minute of world time: the
// owner's rule is that nothing runs more than 10% slower than real time.
void theValleyRunsInsideRealtime() {
    Valley v;
    Json bodies = Json::array();
    const Valley::Section s = v.riverAt(-13.0);
    bodies.push_back(box("oak log", "oak", {0.96, 0.24, 0.24}, {-13.0, s.surface + 0.2, s.z}));
    const Valley::Section dam = v.riverAt(3.0);
    int k = 0;
    for (double z = dam.left - 0.5; z <= dam.right + 0.5; z += 0.48) {
        double top = -1e9;
        for (double dx = -0.2; dx <= 0.2; dx += 0.1)
            for (double dz = -0.2; dz <= 0.2; dz += 0.1) top = std::max(top, v.groundAt(3.0 + dx, z + dz));
        bodies.push_back(box("dam block " + std::to_string(++k), "concrete", {0.48, 0.96, 0.48}, {3.0, top + 0.485, z}));
    }
    const double bx = -8.0, bz = v.riverAt(-8.0).left - 1.2;
    double rest = -1e9;
    for (double dx = -0.28; dx <= 0.28; dx += 0.07)
        for (double dz = -0.28; dz <= 0.28; dz += 0.07) rest = std::max(rest, v.groundAt(bx + dx, bz + dz));
    bodies.push_back(box("boulder", "concrete", {0.56, 0.48, 0.56}, {bx, rest + 0.245, bz}));
    auto world = open(v.scene(bodies));
    const std::size_t bodies_at_start = world->bodies();
    double worst = 0.0, worst_at = 0.0, fracture_ms = 0.0;
    int breaks = 0;
    std::vector<LiveDelay> waits;
    const Clock::time_point t0 = Clock::now();
    const int steps = static_cast<int>(60.0 / kDt);
    for (int n = 0; n < steps; ++n) {
        const Clock::time_point a = Clock::now();
        world->step(kDt);
        if (world->steppedBack()) {
            const Clock::time_point f = Clock::now();
            for (const std::string &name : world->breakable()) {
                (void)world->fracture(name);
                ++breaks;
            }
            fracture_ms += std::chrono::duration<double, std::milli>(Clock::now() - f).count();
        }
        const double took = std::chrono::duration<double, std::milli>(Clock::now() - a).count();
        if (took > worst) { worst = took; worst_at = world->time_s(); }
        for (const LiveDelay &d : world->delays()) waits.push_back(d);
        world->forgetDelays();
        if (n == steps / 2) (void)world->dig(bx, bz + 0.25, bx, bz + 0.8, 0.9, 0.6);
    }
    for (const LiveDelay &d : waits)
        std::cout << "    the world waited: " << d.kind << " " << d.object << " at t=" << d.at_s << " s, run "
                  << d.cost_ms << " ms, lead " << d.lead_ms << "\n";
    std::cout << "    the worst step was at t=" << worst_at << " s\n";
    const double wall = std::chrono::duration<double>(Clock::now() - t0).count();
    const terrain::EnvironmentStats &stats = world->environment()->stats();
    const double ratio = wall / 60.0;
    const double env_s = (stats.push_ms_total + stats.commit_ms_total) / 1000.0;
    std::cout << "    60 s of valley (" << bodies_at_start << " bodies at the start, " << world->bodies()
              << " at the end; " << breaks << " breaks run, " << fracture_ms / 1000.0
              << " s of lattice) in " << wall << " s of wall clock: " << ratio << "x realtime\n"
              << "    where the time went: terrain and water " << env_s << " s (forces "
              << stats.push_ms_total / 1000.0 << ", water " << stats.water_ms_total / 1000.0
              << ", ground settling " << stats.ground_ms_total / 1000.0 << "); everything else -- the rigid "
              << "solver, its reversible trial and the rest of the live world -- "
              << wall - env_s - fracture_ms / 1000.0 << " s\n"
              << "    worst step " << worst << " ms (a step is " << kDt * 1000.0 << " ms of world); water: "
              << stats.water_active_cells << " of " << stats.water_cells << " columns computed, "
              << stats.water_wet_cells << " wet, worst water work " << stats.water_ms_worst
              << " ms; worst collider rebuild " << stats.rebuild_ms_worst << " ms\n";
    require(ratio < 1.1, "the valley runs inside the owner's 1.1x realtime rule");
}

// Ice floating in a closed basin, heated: it melts at the network's rate,
// shrinks as it goes, and every kilogram of its meltwater is in the lake --
// which holds exactly that much more, and whose ledger counts it as added and
// still closes. The same water, counted once on each side.
void meltingIceFillsTheLake() {
    const Json scene = {{"plasticity", true},
                        {"bodies", {box("ice", "ice", {0.4, 0.2, 0.4}, {0.0, 1.2, 0.0}),
                                    box("marker stone", "concrete", {0.16, 0.16, 0.16}, {-7.5, 2.0, -5.5}, true)}},
                        {"terrain", {{"generate", {{"kind", "basin"}, {"nx", 64}, {"nz", 48},
                                                   {"lake_level_m", 1.0}}}}}};
    auto world = open(scene);
    require(world->thermo() != nullptr && world->thermo()->holds("ice"), "the ice is followed from the start");
    const water::ShallowWater &w = *world->environment()->water();
    run(*world, 2.0);   // let it settle afloat
    const double v0 = w.volume();
    const double added0 = w.ledger().added_m3;
    const double melted0 = world->meltwaterIntoWaterKg();
    const Vec3 size0 = poseOf(*world, "ice").dimensions_m;
    world->heat("ice", 10000.0, 30.0);
    run(*world, 31.0);
    const double into = world->meltwaterIntoWaterKg() - melted0;
    double melted = 0.0;
    for (const thermo::BodyHeat &b : world->thermo()->bodies())
        if (b.body == "ice") melted = b.melted_kg;
    const double density = w.settings().density_kg_m3;
    require(into > 0.5, "the heat melted ice into the lake: " + std::to_string(into) + " kg");
    near(world->meltwaterIntoWaterKg(), melted, 1e-6 * melted, "all the meltwater went into the lake");
    near(w.ledger().added_m3 - added0, into / density, 1e-12 * std::max(1.0, into), "the lake counts it as added");
    near(w.volume() - v0, into / density, 1e-9 * v0, "and holds exactly that much more");
    require(std::abs(w.residual()) < 1e-9 * w.volume(), "its ledger still closes: " + std::to_string(w.residual()));
    near(world->meltwaterRanOffKg(), 0.0, 0.0, "none of it ran off: it was over the water");
    const Vec3 size1 = poseOf(*world, "ice").dimensions_m;
    require(size1.x < size0.x && size1.y < size0.y && size1.z < size0.z, "the ice shrank as it melted");
    std::cout << "    10 kW for 30 s: " << into << " kg of ice melted into the lake, " << (w.volume() - v0)
              << " m^3 more in it; the block is now " << 1000.0 * size1.x << " x " << 1000.0 * size1.y << " x "
              << 1000.0 * size1.z << " mm\n";
}

} // namespace

// The adit is a hole you could walk into: rock under it, rock over it, hillside
// untouched above. A ball put inside rests on its floor and cannot rise through
// its roof, which is the whole of what a tunnel has to be to the solver
// (docs/earth-and-mining-plan.md, stage 3; the arrangement was measured before
// it was built in docs/evidence/earth-spikes/roof_spike.cpp).
void theAditIsAHoleWithRockOverIt() {
    Valley v;
    require(v.mine().worked, "somebody worked this valley");
    const auto &g = v.ground().grid();

    // Find a column of the driven tunnel: a working with hill over its roof.
    std::size_t inside = 0;
    double best = -1.0;
    for (std::size_t c = 0; c < g.cells(); ++c) {
        const auto w = v.ground().workingIn(c);
        if (!w) continue;
        const double cover = v.ground().height(c) - w->roof_m;
        if (cover > best) { best = cover; inside = c; }
    }
    std::size_t workings = 0;
    for (std::size_t c = 0; c < g.cells(); ++c) workings += v.ground().workingIn(c) ? 1 : 0;
    std::cout << "    " << workings << " columns hold a working; the most hill over any roof is "
              << best << " m\n";
    require(best > 0.4, "the adit goes under the hill, with rock over its roof");
    const auto working = *v.ground().workingIn(inside);
    const double x = g.xOf(int(inside % std::size_t(g.nx)));
    const double z = g.zOf(int(inside / std::size_t(g.nx)));
    std::cout << "    the tunnel at [" << x << ", " << z << "]: floor " << working.floor_m
              << " m, roof " << working.roof_m << " m, with " << best
              << " m of hill over it (the ground there is " << v.ground().height(inside) << ")\n";

    // A ball dropped into it from just under the roof.
    const double r = 0.05;
    auto world = open(v.scene(Json::array({
        ball("pebble", "concrete", 2.0 * r, {x, working.roof_m - r - 0.02, z})})));
    run(*world, 2.0);
    const LiveBodyPose rest = poseOf(*world, "pebble");
    std::cout << "    a pebble put in it rests at y=" << rest.position_m.y
              << " (its floor plus its radius is " << working.floor_m + r << ")\n";
    near(rest.position_m.y, working.floor_m + r, 0.05,
         "the pebble rests on the tunnel's floor, not on the world's");
    require(std::abs(rest.position_m.x - x) < 0.4 && std::abs(rest.position_m.z - z) < 0.4,
            "and it is still in the tunnel");

    // And the roof is over it. Fired up at 8 m/s from the floor -- free, not
    // held, because the hand MOVES what it holds and would drag it through any
    // collider at all, which is a fact about hands and not about roofs.
    Json fired = ball("shot", "concrete", 2.0 * r, {x, working.floor_m + r + 0.02, z});
    fired["velocity_m_s"] = {0.0, 8.0, 0.0};
    auto again = open(v.scene(Json::array({fired})));
    double highest = -1.0e30;
    for (int k = 0; k < 120; ++k) {
        run(*again, 0.02);
        highest = std::max(highest, poseOf(*again, "shot").position_m.y);
    }
    const double free_flight = working.floor_m + r + 0.02 + 8.0 * 8.0 / (2.0 * 9.81);
    std::cout << "    fired up at 8 m/s it got to y=" << highest << "; the roof is at "
              << working.roof_m << " and free flight would reach " << free_flight << "\n";
    require(free_flight > working.roof_m + 1.0, "it was trying hard enough to matter");
    require(highest < working.roof_m + 0.05,
            "the roof stopped it: a tunnel has rock over it");
}

// The face can be worked back: rock taken out of a column while the world runs
// becomes a hole you can stand in, and the ground's account still closes.
// Until this, the only workings in any world were the ones the generator laid
// down, so a mine was a ruin and not a thing anybody could make
// (docs/earth-and-mining-plan.md, what it takes to be core, item 2).
// The solid rock at the end of the old adit: the column a miner would be
// standing in front of. Any solid column beside a working with enough hill over
// it to still be a tunnel once it is cut -- the deepest column of a heading is
// in the middle of it, so its own neighbours are all workings too.
struct Face {
    std::size_t column{};
    double x{}, z{};
    terrain::TerrainField::Working working{};
};

Face findTheFace(const Valley &v) {
    const auto &g = v.ground().grid();
    double best = -1.0;
    for (std::size_t c = 0; c < g.cells(); ++c) {
        const auto w = v.ground().workingIn(c);
        if (!w) continue;
        best = std::max(best, v.ground().height(c) - w->roof_m);
    }
    require(best > 0.4, "the old adit goes under the hill");
    Face out;
    out.column = g.cells();
    for (std::size_t c = 0; c < g.cells() && out.column == g.cells(); ++c) {
        const auto w = v.ground().workingIn(c);
        if (!w) continue;
        const int ii = static_cast<int>(c % std::size_t(g.nx));
        const int jj = static_cast<int>(c / std::size_t(g.nx));
        for (const auto [di, dj] : {std::pair{1, 0}, std::pair{-1, 0}, std::pair{0, 1}, std::pair{0, -1}}) {
            const int i = ii + di, j = jj + dj;
            if (i < 0 || j < 0 || i >= g.nx || j >= g.nz) continue;
            const std::size_t n = g.at(i, j);
            if (v.ground().workingIn(n)) continue;
            if (v.ground().rockTop(n) > w->roof_m + 0.3) { out.column = n; out.working = *w; break; }
        }
    }
    require(out.column < g.cells(), "the adit has a face to work");
    out.x = g.xOf(static_cast<int>(out.column % std::size_t(g.nx)));
    out.z = g.zOf(static_cast<int>(out.column / std::size_t(g.nx)));
    return out;
}

void theFaceCanBeWorkedBack() {
    Valley v;
    require(v.mine().worked, "somebody worked this valley");
    const Face f = findTheFace(v);
    const std::size_t face = f.column;
    const terrain::TerrainField::Working working = f.working;
    const double fx = f.x, fz = f.z;

    auto world = open(v.scene(Json::array()));
    const terrain::Volumes before = world->environment()->terrain().volumes();
    require(!world->environment()->terrain().workingIn(face).has_value(),
            "the face is solid before it is worked");

    // Take the next cell of rock out, on the working's own level.
    const terrain::EditEffect effect = world->breakOut(fx, fz, working.floor_m, working.roof_m);
    std::cout << "    worked the face at [" << fx << ", " << fz << "]: "
              << effect.edit.moved.total() << " m^3 out, " << effect.chunks_rebuilt
              << " collider(s) rebuilt in " << effect.rebuild_ms << " ms, "
              << effect.bodies_woken << " bodies woken\n";
    require(effect.edit.moved.total() > 0.0, "the working took rock out");

    const auto now = world->environment()->terrain().workingIn(face);
    require(now.has_value(), "the face is a working now");
    near(now->floor_m, working.floor_m, 1e-9, "its floor is the old working's floor");
    near(now->roof_m, working.roof_m, 1e-9, "and so is its roof");

    // The ground lost exactly what came out, and the ledger closes.
    const terrain::Volumes after = world->environment()->terrain().volumes();
    near(before.total() - after.total(), effect.edit.moved.total(), 1e-9,
         "the ground lost what the working took");
    const terrain::Volumes residual = world->environment()->terrain().residual();
    for (const double x : {residual.rock_m3, residual.soil_m3, residual.sand_m3})
        require(std::abs(x) < 1e-9, "the ledger closes after a working");

    // And the SOLVER has it, not only the ground: a ray dropped down the cell
    // that was solid a moment ago stops on the working's floor, where before it
    // would have stopped on the rock at the top of the column.
    const LivePick down = world->pick({fx, working.roof_m - 0.02, fz}, {0.0, -1.0, 0.0}, 50.0);
    std::cout << "    a ray dropped where the rock was stops at y=" << down.point_world_m.y
              << " (the working's floor is " << working.floor_m << ")\n";
    require(down.hit, "the ray found the ground");
    near(down.point_world_m.y, working.floor_m, 0.05,
         "the collider followed the edit: the ray stops on the floor just cut");
}

// What comes out of the rock is carried, and a full person cannot take the next
// cell. A cell of rock at 0.25 m columns is 0.0156 m^3 and 37.5 kg: two of them
// is nearly everything a person can carry, which is the whole shape of mining
// by hand -- you work, you fill up, you put it down somewhere
// (docs/earth-and-mining-plan.md, what it takes to be core, item 6).
void brokenRockIsCarriedAndWeighs() {
    Valley v;
    require(v.mine().worked, "somebody worked this valley");
    const Face f = findTheFace(v);

    auto world = open(v.scene(Json::array()));
    const terrain::Environment &env = *world->environment();
    const double cell = env.terrain().grid().dx;
    const double one_cell_m3 = cell * cell * cell;
    const double one_cell_kg = one_cell_m3 * terrain::rockMaterial().density_kg_m3;
    std::cout << "    a cell of rock is " << one_cell_m3 << " m^3 and " << one_cell_kg << " kg\n";
    require(env.carried().rock_m3 == 0.0, "nothing is carried before any rock is broken");

    // rock-work-v1 says what a cell of this rock costs: its hardness, the
    // cutting constant, and the volume.
    const double hardness = terrain::groundHardnessPa(
        env.terrain().kindAt(f.column, f.working.floor_m + 0.5 * cell));
    const double a_cell_j = terrain::specificEnergyJPerM3(hardness) * one_cell_m3;
    require(a_cell_j > 0.0, "the face has a price");
    std::cout << "    it costs " << a_cell_j / 1000.0 << " kJ to break one out (rock-work-v1)\n";

    // Work the face upwards, a cell at a time, in eighths of what a cell costs.
    const auto workOneCell = [&](double at) {
        LiveWorld::Chipped c;
        for (int i = 0; i < 20; ++i) {
            c = world->workRock(f.x, at, f.z, a_cell_j / 8.0);
            if (c.full || !c.effect.edit.cells.empty()) break;
        }
        return c;
    };

    const LiveWorld::Chipped first = workOneCell(f.working.floor_m + 0.5 * cell);
    require(!first.effect.edit.cells.empty(), "eight eighths of a cell did not break one out");
    std::cout << "    broke one out; carrying " << env.carried().rock_m3 << " m^3 of rock, "
              << env.carriedKg() << " kg\n";
    near(env.carried().rock_m3, one_cell_m3, 1.0e-9, "a cell of rock is carried");
    near(env.carriedKg(), one_cell_kg, 1.0e-6, "and it weighs what rock weighs");

    // A person who can hold 80 kg has room for two cells and not three. The
    // third is paid for and does not come free: the blow is real, the rock does
    // not move, and the work stays credited to the cell.
    world->setCarryLimitKg(80.0);
    const LiveWorld::Chipped second = workOneCell(f.working.floor_m + 1.5 * cell);
    require(!second.effect.edit.cells.empty() && !second.full,
            "the second cell would not come out under an 80 kg limit");
    near(env.carriedKg(), 2.0 * one_cell_kg, 1.0e-6, "two cells of rock are carried");

    const LiveWorld::Chipped third = workOneCell(f.working.floor_m + 2.5 * cell);
    require(third.full, "a person with 5 kg of room took another 37 kg of rock");
    require(third.effect.edit.cells.empty(), "a refused cell came out anyway");
    require(third.bought_m3 == 0.0, "a refused blow bought something");
    near(third.broken_share, 1.0, 1.0e-9, "the refused cell is worked right through");
    std::cout << "    at " << env.carriedKg() << " kg of 80 the next cell would not come free\n";

    // Put it down -- into a lot, which is what a barrow or a hopper is -- and
    // the cell already paid for comes straight out. This is the shape of mining
    // by hand: work, fill up, carry it somewhere, come back.
    const Json packet = Json::parse(world->withdrawGround(0.0, 0.0, env.carried().rock_m3));
    require(packet.at("form") == "rubble", "broken rock is not granular: " + packet.dump());
    require(env.carriedKg() < 1.0e-9, "the rock did not go into the lot");
    const LiveWorld::Chipped again = world->workRock(f.x, f.working.floor_m + 2.5 * cell, f.z, 1.0);
    require(!again.full && !again.effect.edit.cells.empty(),
            "the cell already paid for did not come out once there was room for it");
    near(env.carried().rock_m3, one_cell_m3, 1.0e-9, "and it is carried, like the others");
    std::cout << "    emptied into a lot ("
              << packet.at("contents")[0].at("mass_kg").get<double>()
              << " kg of rubble); the cell already paid for came out on the next blow\n";

    // The ground's account still closes over all of it.
    const terrain::Volumes residual = world->environment()->terrain().residual();
    for (const double r : {residual.rock_m3, residual.soil_m3, residual.sand_m3})
        require(std::abs(r) < 1.0e-9, "the ledger closes after a face is worked by hand");
}

void exactCompoundsHaveNativeWaterForcesAndRetainTheirState() {
    constexpr double volume=.6*.2*.2;
    for (const auto &[material,density] : std::vector<std::pair<std::string,double>>{{"glass",2500},{"oak",700},{"iron",7870}}) {
        const Json scene={{"plasticity",true},
            {"bodies",{box("marker","concrete",{.08,.08,.08},{-7,10,-5},true)}},
            {"precise_rigid_bodies",{{{"name","compound"},{"material",material},{"position_m",{0,.6,0}},
                {"parts",{{{"shape","box"},{"dimensions_m",{.4,.2,.2}},{"center_local_m",{-.1,0,0}}},
                          {{"shape","box"},{"dimensions_m",{.4,.2,.2}},{"center_local_m",{.1,0,0}}}}}}}},
            {"terrain",{{"generate",{{"kind","basin"},{"nx",64},{"nz",48},{"lake_level_m",1.0}}}}}};
        auto world=open(scene);
        world->step(kDt);
        require(!world->steppedBack(),"first native compound water step accepted");
        const auto report=Json::parse(world->environment()->reportJson());
        const auto &rows=report.at("water").at("bodies_in_water");
        require(rows.size()==1 && rows[0].at("name")=="compound","exact object reaches native water adapter");
        near(rows[0].at("buoyancy_n").get<double>(),1000*9.81*volume,1e-5,"native closed-union buoyancy");
        near(rows[0].at("weight_n").get<double>(),density*9.81*volume,1e-5,"native material-derived weight");
        const auto first=poseOf(*world,"compound");
        const double expected=(1000/density-1)*9.81*kDt;
        near(first.velocity_m_s.y,expected,1e-5,"first native velocity follows pressure and weight, not a float label");
        run(*world,2);
        const auto after=poseOf(*world,"compound");
        if (material=="oak") require(after.position_m.y>.9,"oak compound rises to the surface");
        else require(after.position_m.y<.4,"dense compound sinks to the actual basin bed");
        const auto &water=*world->environment()->water();
        near(water.residual(),0,1e-10*water.volume(),"live compound retains the water volume ledger");
        std::string why;
        const std::string saved=world->snapshot(why);
        require(!saved.empty(),"whole compound water snapshot available");
        auto again=open(scene,saved);
        require(again->restored().tier=="whole","compound water snapshot restores whole");
        const auto restored=poseOf(*again,"compound");
        near(length(restored.position_m-after.position_m),0,1e-12,"actual native position retained");
        near(length(restored.velocity_m_s-after.velocity_m_s),0,1e-12,"actual native velocity retained");
        near(again->environment()->water()->volume(),water.volume(),1e-12,"actual fluid state retained");
        std::cout<<"    exact "<<material<<": "<<density*volume<<" kg; first vy "<<first.velocity_m_s.y
                 <<" m/s, force/weight residual "<<first.velocity_m_s.y-expected
                 <<" m/s; at 2 s y="<<after.position_m.y<<" m, water residual="<<water.residual()<<" m^3\n";
    }
}

int main(int argc, char **argv) {
    namespace fs = std::filesystem;
    // A valley of this test's own, generated once and read back after.
    const fs::path cache = fs::temp_directory_path() / "banjo-valley-live-test-cache";
#if defined(_MSC_VER)
    _putenv_s("BANJO_TERRAIN_CACHE", cache.string().c_str());
#else
    setenv("BANJO_TERRAIN_CACHE", cache.string().c_str(), 1);
#endif
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"exact compounds have native water forces and retain their state",exactCompoundsHaveNativeWaterForcesAndRetainTheirState},
        {"a closed basin conserves water with a log in it", aClosedBasinConservesWaterWithALogInIt},
        {"a lake at rest stays at rest", aLakeAtRestStaysAtRest},
        {"a dam of loose blocks raises the river", aDamOfLooseBlocksRaisesTheRiver},
        {"a new outlet drains the pond", aNewOutletDrainsThePond},
        {"a cut block is neither lost nor duplicated", aCutBlockIsNeitherLostNorDuplicated},
        {"the adit is a hole with rock over it", theAditIsAHoleWithRockOverIt},
        {"the face can be worked back", theFaceCanBeWorkedBack},
        {"broken rock is carried and weighs", brokenRockIsCarriedAndWeighs},
        {"digging one corner does not activate the rest", diggingOneCornerDoesNotActivateTheRest},
        {"a boulder falls when dug under", aBoulderFallsWhenDugUnder},
        {"an oak log drifts and iron sinks", anOakLogDriftsAndIronSinks},
        {"water carried into a reopened world is the same", waterCarriedIntoAReopenedWorldIsTheSame},
        {"the valley runs inside realtime", theValleyRunsInsideRealtime},
        {"melting ice fills the lake", meltingIceFillsTheLake},
    };
    const std::string only = argc > 1 ? argv[1] : "";
    unsigned failures = 0, ran = 0;
    for (const auto &[name, test] : tests) {
        if (!only.empty() && std::string(name).find(only) == std::string::npos) continue;
        ++ran;
        const Clock::time_point t0 = Clock::now();
        try {
            test();
            std::cout << "[PASS] " << name << " ("
                      << std::chrono::duration<double>(Clock::now() - t0).count() << " s)\n";
        } catch (const std::exception &error) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << ran - failures << '/' << ran << " tests passed\n";
    return failures == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
}
