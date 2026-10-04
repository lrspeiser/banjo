// The ground beyond the valley: regions streamed in as somebody nears an edge
// (docs/streamed-regions.md). Measured the way the owner will meet them:
//
//   a region meets the valley, and every other region, without a step -- the
//     seam no bigger than the ground's own variation from one column to the
//     next -- and is the same whichever order the regions were made in;
//   a body walking out of the valley grows the world in front of it and walks
//     on across the seam onto the new ground;
//   the new ground is dug like the valley's, and a stone resting on it falls
//     into the hole;
//   a grown and dug world saved and opened again has the same ground, and a
//     room kept as edits makes the same regions again from its list;
//   and what it costs: to add a region, to keep it, and to step with 1, 4 and
//     9 of them beside the valley.
#include "fastlattice/LiveWorld.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "terrain/Environment.hpp"
#include "terrain/TerrainGenerator.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <filesystem>
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
using Clock = std::chrono::steady_clock;

constexpr double kDt = 1.0 / 240.0;   // what the room steps at
constexpr double kPi = 3.14159265358979323846;

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

double msSince(Clock::time_point t0) {
    return std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
}

// A new world's ground: the generated valley in 25 cm columns, let grow.
Json terrainBlock(bool stream = true, Json regions = nullptr) {
    Json t = {{"generate", {{"kind", "valley"}, {"seed", 7}}}, {"surface", "columns"}, {"stream", stream}};
    if (!regions.is_null()) t["regions"] = std::move(regions);
    return t;
}

Json box(const std::string &name, const std::string &material, Vec3 size, Vec3 at, bool anchored = false) {
    return {{"name", name}, {"shape", "box"}, {"material", material},
            {"dimensions_m", {size.x, size.y, size.z}}, {"center_m", {at.x, at.y, at.z}},
            {"anchored", anchored}};
}

Json sceneWith(Json terrain, Json bodies = Json::array()) {
    // A marker high out of the way: a scene has at least one body.
    bodies.push_back(box("marker", "concrete", {.08, .08, .08}, {0, 30, 0}, true));
    return {{"bodies", bodies}, {"terrain", std::move(terrain)}};
}

TileImpactRequest requestFor(const Json &scene) {
    const std::string text = scene.dump();
    TileImpactRequest request;
    request.cell_size_m = 0.04;
    request.backend = BackendKind::CpuParallel;
    request.bodies = readSceneJson(text);
    readSceneSettings(text, request);
    return request;
}

std::unique_ptr<LiveWorld> open(const Json &scene, const std::string &saved = {}) {
    const TileImpactRequest request = requestFor(scene);
    return saved.empty() ? LiveWorld::open(request) : LiveWorld::open(request, saved);
}

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

LiveNativePlayer playerOf(const LiveWorld &world, const std::string &actor) {
    for (const auto &player : world.nativePlayers()) if (player.actor == actor) return player;
    throw std::runtime_error("native player missing: " + actor);
}

LiveBodyPose poseOf(const LiveWorld &world, const std::string &name) {
    for (const LiveBodyPose &pose : world.poses())
        if (pose.name == name) return pose;
    throw std::runtime_error("no body called " + name);
}

double tiltDeg(const LiveNativePlayer &p) {
    return std::acos(std::clamp(p.state.orientation_world.rotate(Vec3{0, 1, 0}).y, -1.0, 1.0)) * 180 / kPi;
}

std::unique_ptr<terrain::Environment> ground(const Json &terrain) {
    return terrain::Environment::fromScene(Json{{"terrain", terrain}}.dump());
}

// Along a seam: the step across it against the steps either side of it, one
// column in. `along` walks the seam; `across` is one cell over it.
struct Seam {
    double worst{}, mean{};             // the step across the seam
    double natural_worst{}, natural_mean{};
};
Seam measureSeam(const terrain::Environment &env, double x0, double z0, double ax, double az, int count,
                 double cx, double cz) {
    Seam s;
    std::vector<double> natural;
    for (int k = 0; k < count; ++k) {
        const double x = x0 + k * ax, z = z0 + k * az;   // the last column on the near side
        const double near = env.groundHeightAt(x, z);
        const double far = env.groundHeightAt(x + cx, z + cz);
        const double step = std::abs(far - near);
        s.worst = std::max(s.worst, step);
        s.mean += step / count;
        // The ground's own step, one column in on each side.
        natural.push_back(std::abs(near - env.groundHeightAt(x - cx, z - cz)));
        natural.push_back(std::abs(env.groundHeightAt(x + 2 * cx, z + 2 * cz) - far));
    }
    for (const double n : natural) {
        s.natural_worst = std::max(s.natural_worst, n);
        s.natural_mean += n / static_cast<double>(natural.size());
    }
    return s;
}

void aRegionMeetsTheValleyWithoutAStep() {
    auto env = ground(terrainBlock());
    require(env->canStream(), "a generated valley in columns can grow");
    const terrain::Grid g = env->terrain().grid();
    for (const auto [rx, rz] : {std::pair{1, 0}, std::pair{-1, 0}, std::pair{0, 1}, std::pair{0, -1}, std::pair{1, 1}})
        require(env->addRegion(nullptr, rx, rz), "a region is added");
    require(env->regions().size() == 5, "five regions");
    require(!env->addRegion(nullptr, 1, 0), "a region is only made once");
    // Every column belongs to exactly one field: the first column past the
    // valley's last is the region's, and the two meet half a cell between.
    const double x_last = g.xOf(g.nx - 1), z_last = g.zOf(g.nz - 1);
    require(env->regionAt(x_last, 0.0) == -1, "the valley's last column is the valley's");
    require(env->regionAt(x_last + g.dx, 0.0) >= 0, "the next one is the region's");
    require(env->regionAt(x_last + 0.49 * g.dx, 0.0) == -1 && env->regionAt(x_last + 0.51 * g.dx, 0.0) >= 0,
            "the boundary is half a cell past the last point");
    const double d = g.dx;
    struct Named { const char *name; Seam seam; };
    const std::vector<Named> seams = {
        {"valley | east", measureSeam(*env, x_last, g.z0, 0, d, g.nz, d, 0)},
        {"west | valley", measureSeam(*env, g.x0, g.z0, 0, d, g.nz, -d, 0)},
        {"valley | north", measureSeam(*env, g.x0, z_last, d, 0, g.nx, 0, d)},
        {"south | valley", measureSeam(*env, g.x0, g.z0, d, 0, g.nx, 0, -d)},
        // Region against region: the east region and the one north of it.
        {"east | north-east", measureSeam(*env, x_last + d, z_last, d, 0, g.nx, 0, d)},
        {"north | north-east", measureSeam(*env, x_last, z_last + d, 0, d, g.nz, d, 0)},
    };
    for (const Named &n : seams) {
        std::cout << "    " << n.name << ": the step across the seam " << n.seam.mean * 1000 << " mm on average, "
                  << n.seam.worst * 1000 << " mm at most; the ground's own column to column "
                  << n.seam.natural_mean * 1000 << " mm on average, " << n.seam.natural_worst * 1000
                  << " mm at most\n";
        // Within the ground's own variation: no step at the seam bigger than
        // the biggest the ground already has beside it, and on average no more
        // than it has (with a millimetre for a seam over dead-flat ground).
        require(n.seam.worst <= n.seam.natural_worst + 1e-3, std::string(n.name) + ": a step at the seam");
        require(n.seam.mean <= n.seam.natural_mean + 1e-3, std::string(n.name) + ": the seam is a ledge");
    }
    // The same ground whichever order the regions were made in, to the bit.
    auto other = ground(terrainBlock());
    for (const auto [rx, rz] : {std::pair{1, 1}, std::pair{0, 1}, std::pair{1, 0}})
        require(other->addRegion(nullptr, rx, rz), "a region is added");
    for (const auto [rx, rz] : {std::pair{1, 1}, std::pair{0, 1}, std::pair{1, 0}}) {
        const terrain::TerrainField *a = nullptr, *b = nullptr;
        for (const auto &r : env->regions()) if (r->rx == rx && r->rz == rz) a = r->field.get();
        for (const auto &r : other->regions()) if (r->rx == rx && r->rz == rz) b = r->field.get();
        require(a != nullptr && b != nullptr, "both made it");
        for (std::size_t c = 0; c < a->grid().cells(); ++c)
            require(a->height(c) == b->height(c) && a->rockTop(c) == b->rockTop(c) && a->soil(c) == b->soil(c),
                    "a region is the same whichever order it was made in");
    }
    // And a seam is what the rule says it is: the streamed ground there.
    const double z = 3.0;
    require(std::abs(env->groundHeightAt(x_last + d, z) -
                     terrain::streamedSurfaceM(env->landscape(), 7, x_last + d, z)) < 1e-9,
            "the region's column is the streamed surface");
    // What cannot grow says why: the smooth valley would leave a cell-wide gap.
    std::string why;
    auto smooth = ground({{"generate", {{"kind", "valley"}, {"seed", 7}}}});
    require(!smooth->canStream(&why) && !why.empty(), "smooth ground does not grow, and says why");
    bool refused = false;
    try { (void)ground({{"generate", {{"kind", "valley"}, {"seed", 7}}}, {"stream", true}}); }
    catch (const std::invalid_argument &) { refused = true; }
    require(refused, "a smooth valley asked to stream is refused, not quietly flat");
}

// Somewhere to walk out of the valley east: dry, and no column-to-column step
// a person could not take, from 5 m inside the edge to 4 m beyond it.
double walkingLane(const terrain::Environment &env) {
    const terrain::Grid &g = env.terrain().grid();
    const double x_last = g.xOf(g.nx - 1);
    double best_z = 0.0, best = 1e9;
    for (int j = 8; j + 8 < g.nz; ++j) {
        const double z = g.zOf(j);
        double worst = 0.0, wet = 0.0;
        for (double x = x_last - 5.0; x < x_last + 4.0; x += g.dx) {
            worst = std::max(worst, std::abs(env.groundHeightAt(x + g.dx, z) - env.groundHeightAt(x, z)));
            for (double side = -0.5; side <= 0.5; side += 0.25) wet = std::max(wet, env.waterDepthAt(x, z + side));
        }
        if (wet == 0.0 && worst < best) { best = worst; best_z = z; }
    }
    require(best < 0.2, "a lane out of the valley a person can walk");
    return best_z;
}

void aBodyWalksOutOfTheValleyAndTheWorldGrows() {
    auto world = open(sceneWith(terrainBlock()));
    const terrain::Environment &env = *world->environment();
    require(env.streaming(), "this world grows");
    // Where the lane is, found on ground with the region already made beside
    // it (the same seed, the same ground).
    auto preview = ground(terrainBlock());
    (void)preview->addRegion(nullptr, 1, 0);
    const double z = walkingLane(*preview);
    const terrain::Grid &g = env.terrain().grid();
    const double seam_x = g.xOf(g.nx - 1) + 0.5 * g.dx;
    const double x0 = seam_x - 4.5;
    world->spawnNativePlayer("walker", {x0, env.groundHeightAt(x0, z) + 0.02, z});
    run(*world, 0.5);
    require(env.regions().empty(), "nothing grows until the host asks, between steps");
    // The host asks before every step it sends, as the runner does.
    std::vector<terrain::Environment::Grown> grown;
    double worst_sink = 0.0, worst_tilt = 0.0, crossed_at = 0.0, tilt_at = 0.0, tilt_near_seam = 0.0;
    for (double t = 0; t < 7.0; t += 0.25) {
        for (const auto &r : world->growGround()) grown.push_back(r);
        world->setNativePlayerWalk("walker", {1.5, 0, 0}, kPi / 2, 0.3);
        for (int s = 0; s < 60; ++s) {
            run(*world, kDt);
            const LiveNativePlayer p = playerOf(*world, "walker");
            const Vec3 at = p.state.center_of_mass_world_m;
            // Its middle is 0.85 m over its feet: how far under that the
            // ground has let it sink.
            const double over = at.y - env.groundHeightAt(at.x, at.z);
            worst_sink = std::max(worst_sink, 0.85 - over);
            if (tiltDeg(p) > worst_tilt) { worst_tilt = tiltDeg(p); tilt_at = at.x; }
            if (std::abs(at.x - seam_x) < 1.0) tilt_near_seam = std::max(tilt_near_seam, tiltDeg(p));
            if (crossed_at == 0.0 && at.x > seam_x) crossed_at = t;
        }
    }
    const LiveNativePlayer p = playerOf(*world, "walker");
    std::cout << "    grew " << grown.size() << " region(s) as it walked; the first: made in "
              << (grown.empty() ? 0.0 : grown[0].generate_ms) << " ms, colliders "
              << (grown.empty() ? 0.0 : grown[0].colliders_ms) << " ms, seams "
              << (grown.empty() ? 0.0 : grown[0].seams_ms) << " ms (" << (grown.empty() ? 0 : grown[0].seam_chunks)
              << " chunks)\n    crossed the seam at " << crossed_at << " s, ended at x = "
              << p.state.center_of_mass_world_m.x << " m; sank at most " << worst_sink * 1000
              << " mm into the ground, tilted at most " << worst_tilt << " degrees (at x = " << tilt_at
              << " m), within a metre of the seam at most " << tilt_near_seam << " degrees\n";
    require(std::any_of(grown.begin(), grown.end(), [](const auto &r) { return r.rx == 1 && r.rz == 0; }),
            "the region east of it was grown");
    require(p.state.center_of_mass_world_m.x > seam_x + 2.0, "it walked on onto the new ground");
    require(env.regionAt(p.state.center_of_mass_world_m.x, p.state.center_of_mass_world_m.z) >= 0,
            "and is standing on the region");
    // A cylinder on columns rides a couple of centimetres either way of its
    // column's top as it steps from one to the next; through the ground it
    // would be metres.
    require(worst_sink < 0.1, "it never sank into the ground");
    // It sways as it steps up the valley's own cells (the worst of it inside
    // the valley); across the seam it walks as on any other cells.
    require(tilt_near_seam < 10.0, "it crossed the seam on its feet");
    require(tiltDeg(p) < 10.0 && worst_tilt < 30.0, "it stayed on its feet");
    require(p.supported, "it is standing on something");
}

void theNewGroundIsDugLikeTheValley() {
    // A region made by the scene's own list, and a stone resting on it.
    auto preview = ground(terrainBlock());
    (void)preview->addRegion(nullptr, 1, 0);
    const double sx = 25.0, sz = walkingLane(*preview);
    const double top = preview->groundHeightAt(sx, sz);
    auto world = open(sceneWith(terrainBlock(true, Json::array({Json::array({1, 0})})),
                                Json::array({box("stone", "concrete", {.24, .24, .24}, {sx, top + 0.14, sz})})));
    const terrain::Environment &env = *world->environment();
    require(env.regions().size() == 1, "the scene's region is there when it opens");
    run(*world, 1.0);
    const double rested = poseOf(*world, "stone").position_m.y;
    require(std::abs(rested - (top + 0.12)) < 0.03, "the stone rests on the region's ground");
    const double carried_before = env.carriedTotal().total();
    const terrain::EditEffect dug = world->dig(sx, sz, sx, sz, 1.0, 0.5);
    const double carried = env.carriedTotal().total() - carried_before;
    require(dug.region_columns > 0 && dug.chunks_rebuilt > 0, "the region's columns and colliders changed");
    require(std::abs(env.groundHeightAt(sx, sz) - (top - 0.5)) < 1e-9, "dug half a metre");
    const terrain::Ledger &ledger = env.regions()[0]->field->ledger();
    require(std::abs(ledger.dug.soil_m3 + ledger.dug.sand_m3 - carried) < 1e-12, "what came out is carried");
    run(*world, 1.5);
    const double fell = rested - poseOf(*world, "stone").position_m.y;
    std::cout << "    dug " << dug.region_columns << " columns, " << carried << " m3, " << dug.chunks_rebuilt
              << " chunks rebuilt in " << dug.rebuild_ms << " ms; the stone fell " << fell << " m into it\n";
    require(fell > 0.3, "the stone fell into the hole");
    // A trench across the seam is dug on both sides of it.
    const terrain::Grid &g = env.terrain().grid();
    const double seam_x = g.xOf(g.nx - 1) + 0.5 * g.dx;
    const double near = env.groundHeightAt(seam_x - 0.1, sz + 2), far = env.groundHeightAt(seam_x + 0.1, sz + 2);
    (void)world->dig(seam_x - 1.0, sz + 2, seam_x + 1.0, sz + 2, 0.5, 0.2);
    require(std::abs(env.groundHeightAt(seam_x - 0.1, sz + 2) - (near - 0.2)) < 1e-9 &&
            std::abs(env.groundHeightAt(seam_x + 0.1, sz + 2) - (far - 0.2)) < 1e-9,
            "a trench across the seam is dug on both sides");
    // The survey knows where it is.
    const Json said = Json::parse(world->survey(sx, sz));
    require(said.value("on_the_ground", false) && said.at("region") == Json::array({1, 0}),
            "the survey says which region");
}

// The same swing the valley's ground work is tested with (ground_work_tests),
// a pick of oak swung and pried, out on a region.
std::string finishStroke(LiveWorld &live, int most_steps, int settle_steps) {
    for (int i = 0; i < most_steps; ++i) {
        run(live, kDt);
        if (!live.hand().stroking) break;
    }
    const std::string ended = live.hand().stroke_ended;
    if (!live.held().empty()) live.moveHeld(live.hand().grip_m);
    for (int i = 0; i < settle_steps; ++i) run(live, kDt);
    return ended;
}

void aPickSwungOutThereBreaksTheRegionsGround() {
    // Somewhere level on the region east of the valley, away from the seam.
    auto preview = ground(terrainBlock());
    (void)preview->addRegion(nullptr, 1, 0);
    double best = 1e9, X = 0, Z = 0;
    for (double x = 26.0; x < 52.0; x += 1.0)
        for (double z = -12.0; z < 12.0; z += 1.0) {
            const double h = preview->groundHeightAt(x, z);
            double worst = 0.0;
            for (double dx = -1.0; dx <= 1.5; dx += 0.25)
                for (double dz = -0.5; dz <= 0.5; dz += 0.25)
                    worst = std::max(worst, std::abs(preview->groundHeightAt(x + dx, z + dz) - h));
            if (worst < best) { best = worst; X = x; Z = z; }
        }
    const double top = preview->groundHeightAt(X + 0.3, Z);
    Json bodies = Json::array({box("pick", "oak", {0.8, 0.04, 0.04}, {X, top + 1.02, Z + 0.02}),
                               box("pick arm", "oak", {0.04, 0.28, 0.04}, {X + 0.38, top + 0.86, Z + 0.02})});
    bodies[0]["join"] = "pick";
    bodies[1]["join"] = "pick";
    auto world = open(sceneWith(terrainBlock(true, Json::array({Json::array({1, 0})})), bodies));
    const terrain::Environment &env = *world->environment();
    const Vec3 grip{X - 0.36, top + 1.02, Z + 0.02};
    require(world->toolPoint("pick", {X + 0.38, top + 0.72, Z + 0.02}, {0.0, -1.0, 0.0}, 0.04, 0.04, 30.0, 0.2,
                             grip) != 0, "the pick would not take a point: " + world->toolPointRefusal());
    require(world->wield("pick", grip), "the pick could not be taken by its grip");
    LiveStrike strike;
    strike.target_m = {X + 0.3, top, Z + 0.02};
    strike.shoulder_m = {X - 0.9, top + 1.45, Z + 0.02};
    strike.speed_m_s = 4.0;
    strike.raise_deg = 110.0;
    std::string why;
    require(world->strike(strike, why), "the swing was refused: " + why);
    (void)finishStroke(*world, 480, 120);
    require(!world->groundWork().empty() && world->groundWork().front().open, "the pick is not in the region's ground");
    const LiveGroundWork in = world->groundWork().front();
    const double carried_before = env.carriedTotal().total();
    LiveStrike lever;
    lever.lever = true;
    lever.shoulder_m = {X - 0.9, top + 1.45, Z + 0.02};
    lever.speed_m_s = 1.2;
    lever.lever_deg = 40.0;
    require(world->strike(lever, why), "the lever was refused: " + why);
    (void)finishStroke(*world, 960, 30);
    if (world->groundWork().front().open) {
        const Vec3 at = world->hand().grip_m;
        LiveStroke up;
        up.path_m = {at, at + Vec3{0.0, 0.4, 0.0}};
        up.speed_m_s = 0.6;
        up.accel_m_s2 = 4.0;
        up.give_up_s = 3.0;
        require(world->stroke(up, why), "the pull was refused: " + why);
        (void)finishStroke(*world, 960, 30);
    }
    const LiveGroundWork out = world->groundWork().front();
    const terrain::Ledger &ledger = env.regions()[0]->field->ledger();
    const double gained = env.carriedTotal().total() - carried_before;
    std::cout << "    the pick went " << in.depth_m * 1000 << " mm into the region's " << in.ground << "; pried, it "
              << out.kind << ": " << out.loosened.total() * 1000 << " L loosened, " << gained * 1000
              << " L carried, the region's ledger dug " << (ledger.dug.soil_m3 + ledger.dug.sand_m3) * 1000 << " L\n";
    require(in.depth_m > 0.0, "the point went into the region's ground");
    require(out.kind == "broke out" && out.loosened.total() > 0.0, "the pry broke the region's ground out");
    require(std::abs(gained - out.loosened.total()) < 1e-12, "what came out is carried");
    require(std::abs(ledger.dug.soil_m3 + ledger.dug.sand_m3 - gained) < 1e-12, "and came out of the region");
}

void aGrownWorldIsSavedAndComesBack() {
    const Json scene = sceneWith(terrainBlock());
    auto world = open(scene);
    const terrain::Environment &env = *world->environment();
    std::string why;
    const terrain::Grid &g = env.terrain().grid();
    const double x = g.xOf(g.nx - 1) - 3.0, z = 0.0;
    world->spawnNativePlayer("walker", {x, env.groundHeightAt(x, z) + 0.02, z});
    run(*world, 0.25);
    // What the regions add to a saved world: their own entry in the ground.
    const auto regionsBytes = [](const std::string &text) {
        const Json doc = Json::parse(text);
        return doc.at("ground").contains("regions") ? doc.at("ground").at("regions").dump().size() : 0;
    };
    const std::string bare = world->snapshot(why);
    require(world->growGround().size() == 1, "standing 3 m from the east edge grows one region");
    run(*world, 0.25);
    const std::string grown = world->snapshot(why);
    const double dx = 30.0, dz = 1.0;
    (void)world->dig(dx, dz, dx + 2.0, dz, 1.0, 0.4);
    run(*world, 1.0);
    const std::string saved = world->snapshot(why);
    require(!saved.empty(), "it saves: " + why);
    std::cout << "    the saved world: " << bare.size() / 1024.0 << " KB; with a region nobody has touched "
              << grown.size() / 1024.0 << " KB, its entry " << regionsBytes(grown) << " bytes; with a 2 m trench "
              << "dug in it " << saved.size() / 1024.0 << " KB, its entry " << regionsBytes(saved) / 1024.0
              << " KB (" << Json::parse(saved).at("ground").at("regions")[0].at("chunks").size() << " chunks kept)\n";
    require(regionsBytes(grown) < 200, "an untouched region costs a few bytes to keep");
    require(regionsBytes(saved) < 600 * 1024, "a dug region keeps the chunks it changed, not the whole region");
    auto again = open(scene, saved);
    const terrain::Environment &back = *again->environment();
    require(back.regions().size() == 1 && back.regions()[0]->rx == 1 && back.regions()[0]->rz == 0,
            "the region comes back where it was");
    const terrain::TerrainField &a = *env.regions()[0]->field, &b = *back.regions()[0]->field;
    for (std::size_t c = 0; c < a.grid().cells(); ++c)
        require(a.height(c) == b.height(c) && a.soil(c) == b.soil(c), "the region's ground comes back to the bit");
    require(std::abs(back.groundHeightAt(dx + 1, dz) - env.groundHeightAt(dx + 1, dz)) == 0.0, "dug as it was");
    require(back.streaming(), "and it goes on growing");
    // Something put on it after it came back stands on it: its colliders are there.
    run(*again, 0.5);
    require(again->nativePlayers().size() == 1, "the walker came back too");
    const LiveNativePlayer p = playerOf(*again, "walker");
    require(std::abs(p.state.center_of_mass_world_m.y - (back.groundHeightAt(p.state.center_of_mass_world_m.x,
                                                                               p.state.center_of_mass_world_m.z) + 0.85)) < 0.1,
            "standing on the ground after the reopen");
    // A room kept as edits (no saved world) makes the region again from its
    // list and digs it the same.
    Json kept = terrainBlock(true, Json::array({Json::array({1, 0})}));
    kept["edits"] = Json::array({{{"dig", {{"from_m", {dx, dz}}, {"to_m", {dx + 2.0, dz}}, {"width_m", 1.0},
                                           {"depth_m", 0.4}}}}});
    auto replayed = ground(kept);
    require(replayed->regions().size() == 1, "the edits' room has its region");
    require(std::abs(replayed->groundHeightAt(dx + 1, dz) - env.groundHeightAt(dx + 1, dz)) < 1e-9,
            "the edit replayed digs the same");
    // And an edit out there with no list makes its region all the same.
    Json unlisted = terrainBlock(true);
    unlisted["edits"] = kept["edits"];
    require(ground(unlisted)->regions().size() == 1, "an edit makes the region it needs");
}

double stepMs(LiveWorld &world, double seconds, double *worst) {
    const int steps = static_cast<int>(std::lround(seconds / kDt));
    double total = 0.0;
    *worst = 0.0;
    for (int s = 0; s < steps; ++s) {
        if (s % 60 == 0) world.setNativePlayerWalk("walker", {1.0, 0, 0}, kPi / 2, 0.3);
        const Clock::time_point t0 = Clock::now();
        world.step(kDt);
        const double ms = msSince(t0);
        total += ms;
        *worst = std::max(*worst, ms);
    }
    return total / steps;
}

void whatItCosts() {
    // The same walker, in the valley, with 0, 1, 4 and 9 regions beside it.
    const std::vector<std::vector<std::pair<int, int>>> layouts = {
        {},
        {{1, 0}},
        {{1, 0}, {-1, 0}, {0, 1}, {0, -1}},
        {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {-1, 1}, {1, -1}, {-1, -1}, {2, 0}},
    };
    double base = 0.0;
    for (const auto &layout : layouts) {
        Json list = Json::array();
        for (const auto &[rx, rz] : layout) list.push_back({rx, rz});
        const Clock::time_point t0 = Clock::now();
        auto world = open(sceneWith(terrainBlock(true, list)));
        const double open_ms = msSince(t0);
        const terrain::Environment &env = *world->environment();
        world->spawnNativePlayer("walker", {-4.0, env.groundHeightAt(-4.0, -6.0) + 0.02, -6.0});
        run(*world, 0.5);
        double worst = 0.0;
        // Twice, keeping the second: the first warms what a first run warms.
        (void)stepMs(*world, 1.0, &worst);
        const double ms = stepMs(*world, 3.0, &worst);
        if (layout.empty()) base = ms;
        std::cout << "    " << layout.size() << " regions: a step " << ms << " ms on average (" << (ms - base)
                  << " ms more than none), worst " << worst << " ms; opened in " << open_ms << " ms\n";
    }
    // And growing one while the world runs: the step before, the growth, the
    // step after.
    auto world = open(sceneWith(terrainBlock()));
    const terrain::Environment &env = *world->environment();
    const terrain::Grid &g = env.terrain().grid();
    const double x = g.xOf(g.nx - 1) - 3.0;
    world->spawnNativePlayer("walker", {x, env.groundHeightAt(x, 0.0) + 0.02, 0.0});
    run(*world, 0.5);
    double worst = 0.0;
    const double before = stepMs(*world, 0.5, &worst);
    const Clock::time_point t0 = Clock::now();
    const auto grown = world->growGround();
    const double grow_ms = msSince(t0);
    require(grown.size() == 1, "one region grown");
    // The rest of its colliders come a few a step: every step until they are
    // all there, timed.
    const terrain::StreamedRegion &region = *env.regions()[0];
    double attaching_worst = 0.0;
    int attaching_steps = 0;
    while (!region.unattached.empty() || region.seams_pending) {
        const Clock::time_point t1 = Clock::now();
        world->step(kDt);
        attaching_worst = std::max(attaching_worst, msSince(t1));
        require(++attaching_steps < 240, "its colliders all come within a second");
    }
    const double after = stepMs(*world, 0.5, &worst);
    std::cout << "    growing one region while it runs: " << grow_ms << " ms in the step that grew it (ground "
              << grown[0].generate_ms << " ms, the nearest colliders " << grown[0].colliders_ms << " ms); the rest "
              << "over the next " << attaching_steps << " steps (" << attaching_steps * kDt * 1000
              << " ms of world time), the slowest of them " << attaching_worst << " ms, all its colliders "
              << region.colliders_ms << " ms; steps " << before << " ms before, " << after << " ms after\n";
    require(attaching_worst < 25.0, "no step stalls while its colliders come");
}

} // namespace

int main(int argc, char **argv) {
    namespace fs = std::filesystem;
    // A valley of this test's own, generated once and read back after.
    const fs::path cache = fs::temp_directory_path() / "banjo-streamed-regions-test-cache";
#if defined(_MSC_VER)
    _putenv_s("BANJO_TERRAIN_CACHE", cache.string().c_str());
#else
    setenv("BANJO_TERRAIN_CACHE", cache.string().c_str(), 1);
#endif
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"a region meets the valley without a step", aRegionMeetsTheValleyWithoutAStep},
        {"a body walks out of the valley and the world grows", aBodyWalksOutOfTheValleyAndTheWorldGrows},
        {"the new ground is dug like the valley", theNewGroundIsDugLikeTheValley},
        {"a pick swung out there breaks the region's ground", aPickSwungOutThereBreaksTheRegionsGround},
        {"a grown world is saved and comes back", aGrownWorldIsSavedAndComesBack},
        {"what it costs", whatItCosts},
    };
    const std::string only = argc > 1 ? argv[1] : "";
    unsigned failures = 0, ran = 0;
    for (const auto &[name, test] : tests) {
        if (!only.empty() && std::string(name).find(only) == std::string::npos) continue;
        ++ran;
        const Clock::time_point t0 = Clock::now();
        try {
            test();
            std::cout << "[PASS] " << name << " (" << std::chrono::duration<double>(Clock::now() - t0).count()
                      << " s)\n";
        } catch (const std::exception &error) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << ran - failures << '/' << ran << " tests passed\n";
    return failures == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
}
