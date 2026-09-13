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

std::unique_ptr<LiveWorld> open(const Json &scene) {
    const std::string text = scene.dump();
    TileImpactRequest request;
    request.cell_size_m = kCell;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(text);
    readSceneSettings(text, request);
    return LiveWorld::open(request);
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
    double at_x = 0.0, at_z = 0.0;
    bool found = false;
    for (int j = 3; j < g.nz - 3 && !found; ++j)
        for (int i = 3; i < g.nx - 3 && !found; ++i) {
            bool bare = true;
            for (int dj = -2; dj <= 2; ++dj)
                for (int di = -2; di <= 2; ++di)
                    bare = bare && v.ground().surface(g.at(i + di, j + dj)) == terrain::Surface::Rock &&
                           v.ground().slopeDeg(g.at(i + di, j + dj)) < 15.0;
            if (bare) { at_x = g.xOf(i); at_z = g.zOf(j); found = true; }
        }
    require(found, "there is bare, level rock to cut");
    auto world = open(v.scene(Json::array()));
    const terrain::Volumes before = world->environment()->terrain().volumes();
    std::string why;
    // A footprint that is not whole cells is refused, and says what would do.
    require(!world->cut(at_x, at_z, 2, 2, 0.4, &why).has_value() && why.find("4 columns") != std::string::npos,
            "a half-metre block of 0.04 m cells is refused, with the size that would do: " + why);
    const auto block = world->cut(at_x, at_z, 4, 4, 0.4, &why);
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

} // namespace

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
        {"a closed basin conserves water with a log in it", aClosedBasinConservesWaterWithALogInIt},
        {"a lake at rest stays at rest", aLakeAtRestStaysAtRest},
        {"a dam of loose blocks raises the river", aDamOfLooseBlocksRaisesTheRiver},
        {"a new outlet drains the pond", aNewOutletDrainsThePond},
        {"a cut block is neither lost nor duplicated", aCutBlockIsNeitherLostNorDuplicated},
        {"digging one corner does not activate the rest", diggingOneCornerDoesNotActivateTheRest},
        {"a boulder falls when dug under", aBoulderFallsWhenDugUnder},
        {"an oak log drifts and iron sinks", anOakLogDriftsAndIronSinks},
        {"water carried into a reopened world is the same", waterCarriedIntoAReopenedWorldIsTheSame},
        {"the valley runs inside realtime", theValleyRunsInsideRealtime},
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
