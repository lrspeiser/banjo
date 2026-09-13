// The ground on its own: what digging takes and where it goes, how a bank of
// sand and a trench in soil respond to being dug, a block cut out of rock
// carrying exactly the rock that left the ground, and a dig in one corner
// asking about that corner and nowhere else.
#include "terrain/TerrainField.hpp"
#include "terrain/TerrainGenerator.hpp"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using namespace banjo::terrain;

constexpr double kPi = 3.14159265358979323846;

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message) + ": actual=" + std::to_string(actual) +
                                 " expected=" + std::to_string(expected) +
                                 " tolerance=" + std::to_string(tolerance));
}

// A flat piece of ground: rock at 0, then `soil` of soil and `sand` of sand.
TerrainField flat(int nx, int nz, double soil, double sand, double dx = 0.25) {
    Grid g{nx, nz, dx, 0.0, 0.0};
    const std::size_t n = g.cells();
    return TerrainField(g, std::vector<double>(n, 0.0), std::vector<double>(n, soil),
                        std::vector<double>(n, sand));
}

void settle(TerrainField &ground, double seconds) {
    for (int k = 0; k < static_cast<int>(seconds * 60.0) && !ground.settled(); ++k)
        (void)ground.relax(1.0 / 60.0);
}

double steepestLooseSlopeDeg(const TerrainField &ground) {
    const Grid &g = ground.grid();
    double worst = 0.0;
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i + 1 < g.nx; ++i) {
            const std::size_t a = g.at(i, j), b = g.at(i + 1, j);
            const double drop = std::abs(ground.height(a) - ground.height(b));
            worst = std::max(worst, std::atan(drop / g.dx) * 180.0 / kPi);
        }
    return worst;
}

// 1. Digging takes material out and says exactly how much, of what; heaping it
// back puts exactly that much back.
void diggingIsAccountedByMaterial() {
    TerrainField ground = flat(40, 40, 0.6, 0.3);
    const Volumes before = ground.volumes();
    const EditReport dug = ground.dig(3.0, 5.0, 7.0, 5.0, 1.0, 0.5);
    require(!dug.cells.empty(), "the dig touched the ground");
    // 0.3 m of sand, then 0.2 m of soil, from every column it reached.
    const double area = 0.25 * 0.25;
    near(dug.moved.sand_m3, dug.cells.size() * 0.3 * area, 1e-12, "the sand that came out");
    near(dug.moved.soil_m3, dug.cells.size() * 0.2 * area, 1e-12, "the soil that came out");
    near(dug.mass_kg, dug.moved.sand_m3 * 1600.0 + dug.moved.soil_m3 * 1600.0, 1e-9, "its mass");
    const Volumes after = ground.volumes();
    near(before.sand_m3 - after.sand_m3, dug.moved.sand_m3, 1e-12, "the sand left the ground");
    near(before.soil_m3 - after.soil_m3, dug.moved.soil_m3, 1e-12, "the soil left the ground");
    (void)ground.deposit(8.0, 8.0, 1.0, dug.moved.sand_m3, dug.moved.soil_m3);
    settle(ground, 10.0);
    const Volumes back = ground.volumes();
    near(back.sand_m3, before.sand_m3, 1e-10, "heaped back, the sand is all there");
    near(back.soil_m3, before.soil_m3, 1e-10, "and the soil");
    const Volumes residual = ground.residual();
    near(residual.rock_m3 + residual.soil_m3 + residual.sand_m3, 0.0, 1e-10, "the ledger closes");
    std::cout << "    dug " << dug.moved.sand_m3 << " m^3 of sand and " << dug.moved.soil_m3
              << " m^3 of soil from " << dug.cells.size() << " columns; heaped back to within "
              << std::abs(back.total() - before.total()) << " m^3\n";
}

// 2. A pit dug in sand does not keep vertical walls: the sand slumps in until
// no slope is steeper than it can stand at -- and not one grain is lost.
void aPitInSandSlumpsToItsAngleOfRepose() {
    TerrainField ground = flat(48, 48, 0.2, 1.2);
    const Volumes before = ground.volumes();
    const EditReport dug = ground.dig(6.0, 6.0, 6.0, 6.0, 2.0, 1.0);
    const Volumes after_dig = ground.volumes();
    settle(ground, 20.0);
    require(ground.settled(), "the slump comes to an end");
    const double steepest = steepestLooseSlopeDeg(ground);
    // The model's own bar: the angle of repose plus the stopping layer, which
    // is what it declares a sand face stands to. Not a margin picked here.
    const double stands = std::atan(TerrainField::stableDrop(sandMaterial(), 0.25) / 0.25) * 180.0 / kPi;
    std::cout << "    after the dig: steepest slope " << steepest << " deg; sand's angle of repose is "
              << sandMaterial().friction_angle_deg << ", and with the stopping layer it stands to "
              << stands << "; slumped " << ground.ledger().slumped_m3 << " m^3\n";
    require(ground.ledger().slumped_m3 > 0.05, "sand fell into the pit");
    require(steepest <= stands + 1.0e-9, "no sand slope steeper than the model says it stands");
    require(steepest >= sandMaterial().friction_angle_deg - 3.0, "and the slump did not overshoot to a gentle slope");
    const Volumes now = ground.volumes();
    near(now.sand_m3, after_dig.sand_m3, 1e-10, "slumping moved sand and lost none");
    near(before.sand_m3 - now.sand_m3, dug.moved.sand_m3, 1e-10, "only the dig took any away");
}

// 3. The same pit in firm soil stands: a spade-deep trench keeps its walls.
// And a deep one does not.
void aTrenchInSoilStandsAndADeepOneDoesNot() {
    TerrainField shallow = flat(48, 24, 2.0, 0.0);
    (void)shallow.dig(2.0, 3.0, 9.0, 3.0, 1.0, 0.5);
    settle(shallow, 10.0);
    require(shallow.ledger().slumped_m3 == 0.0, "a 0.5 m trench in firm soil keeps its walls");
    TerrainField deep = flat(48, 24, 2.5, 0.0);
    (void)deep.dig(2.0, 3.0, 9.0, 3.0, 1.0, 1.6);
    settle(deep, 20.0);
    std::cout << "    0.5 m trench: nothing slumped; 1.6 m trench: " << deep.ledger().slumped_m3
              << " m^3 slumped into it\n";
    require(deep.ledger().slumped_m3 > 0.0, "a 1.6 m trench in the same soil caves in");
}

// 4. Rock does not slump, however steep.
void rockDoesNotSlump() {
    TerrainField ground = flat(24, 24, 0.0, 0.0);
    std::string why;
    const auto block = ground.cut(3.0, 3.0, 4, 4, 1.5, &why);
    require(block.has_value(), "bare rock can be cut: " + why);
    settle(ground, 5.0);
    require(ground.ledger().slumped_m3 == 0.0, "a 1.5 m vertical rock face stands");
}

// 5. A block cut out of rock carries exactly the rock that left the ground --
// neither lost nor duplicated -- and it is refused where there is soil over
// the rock.
void aCutBlockIsExactlyTheRockThatLeft() {
    // Rock that is not flat, so the block cannot just be read off a box.
    Grid g{24, 24, 0.25, 0.0, 0.0};
    std::vector<double> rock(g.cells());
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < g.nx; ++i) rock[g.at(i, j)] = 0.02 * i + 0.01 * std::sin(1.7 * j);
    TerrainField ground(g, rock, std::vector<double>(g.cells(), 0.0),
                        std::vector<double>(g.cells(), 0.0));
    const Volumes before = ground.volumes();
    std::string why;
    const auto block = ground.cut(3.0, 3.0, 3, 2, 0.4, &why);
    require(block.has_value(), "the cut is made: " + why);
    const Volumes after = ground.volumes();
    near(before.rock_m3 - after.rock_m3, block->volume_m3, 1e-12, "the ground lost the block's volume");
    near(block->size_m.x * block->size_m.y * block->size_m.z, block->volume_m3, 1e-12,
         "and the block holds exactly that volume");
    near(block->mass_kg, block->volume_m3 * rockMaterial().density_kg_m3, 1e-9,
         "at the rock's own density");
    near(ground.residual().rock_m3, 0.0, 1e-12, "the ledger says where it went");
    std::cout << "    cut a " << block->size_m.x << " x " << block->size_m.y << " x "
              << block->size_m.z << " m block, " << block->mass_kg << " kg; the ground lost "
              << before.rock_m3 - after.rock_m3 << " m^3 and the block is " << block->volume_m3
              << " m^3\n";
    TerrainField covered = flat(24, 24, 0.4, 0.0);
    require(!covered.cut(3.0, 3.0, 2, 2, 0.4, &why).has_value(), "no cut through soil");
    require(why.find("soil") != std::string::npos, "and it says why: " + why);
}

// 6. Digging one corner asks about that corner. The stability check visits
// the columns the dig touched, and whatever its collapse actually reaches --
// and the chunks marked for new colliders are only the ones that changed.
void diggingOneCornerDoesNotActivateTheRest() {
    // 156 x 125 points: 5 x 4 chunks, the valley's size.
    TerrainField ground = flat(156, 125, 0.3, 0.5);
    (void)ground.takeDirtyChunks();
    ground.resetActivity();
    (void)ground.dig(1.5, 1.5, 2.5, 1.5, 1.0, 0.6);
    std::size_t passes = 0;
    while (!ground.settled() && passes < 2000) { (void)ground.relax(1.0 / 60.0); ++passes; }
    const std::set<int> chunks = ground.takeDirtyChunks();
    const std::size_t total = ground.grid().cells();
    std::cout << "    one corner: " << ground.checkedSinceReset() << " column checks over "
              << passes << " passes (at most " << ground.frontierPeak() << " at once) of "
              << total << " columns; " << chunks.size() << " of "
              << ground.chunksX() * ground.chunksZ() << " chunks need a new collider\n";
    require(ground.settled(), "the corner settles");
    require(ground.frontierPeak() < 400, "never more than a corner's worth of columns asked at once");
    require(chunks.size() == 1 && *chunks.begin() == 0, "only the corner chunk changed");
}

// 7. The ground under a point is the surface the collider is: interpolated on
// the same diagonal.
void heightAtFollowsTheColliderSplit() {
    Grid g{4, 4, 1.0, 0.0, 0.0};
    std::vector<double> rock(g.cells(), 0.0);
    rock[g.at(1, 1)] = 1.0;   // one raised point
    TerrainField ground(g, rock, std::vector<double>(g.cells(), 0.0),
                        std::vector<double>(g.cells(), 0.0));
    near(ground.heightAt(1.0, 1.0), 1.0, 1e-12, "at a point, its own height");
    // Across the quad from (0,0) to (1,1): the diagonal carries the peak.
    near(ground.heightAt(0.5, 0.5), 0.5, 1e-12, "half way up the diagonal");
    near(ground.heightAt(0.75, 0.25), 0.25, 1e-12, "below the diagonal, the (1,0) triangle");
    near(ground.heightAt(0.25, 0.75), 0.25, 1e-12, "above it, the (0,1) triangle");
}

// 8. The valley: made once by physical processes, and read back the same. The
// drainage route runs from the source to the mouth, the hollow on the
// floodplain is kept as a pond brimming at the level it spills at, the river
// has been run until it passes on what it is fed, the knoll's rock is bare --
// and the same parameters make the same valley, whether generated or loaded.
void aValleyIsShapedByWaterAndSaved() {
    namespace fs = std::filesystem;
    const fs::path folder = fs::temp_directory_path() / "banjo-terrain-test-cache";
    std::error_code ignored;
    fs::remove_all(folder, ignored);
    ValleyParameters p;
    const Landscape made = valley(p, folder.string());
    const GenerationReport &r = made.report;
    // For looking at: BANJO_TERRAIN_DUMP=<file> writes every column as text,
    // "i j ground rock soil sand loose depth qx qz", for a plot.
    if (const char *dump = std::getenv("BANJO_TERRAIN_DUMP"); dump != nullptr && *dump != '\0') {
        std::FILE *out = std::fopen(dump, "w");
        if (out != nullptr) {
            std::fprintf(out, "%d %d %.6f %.6f %.6f\n", made.grid.nx, made.grid.nz, made.grid.dx,
                         made.grid.x0, made.grid.z0);
            for (int j = 0; j < made.grid.nz; ++j)
                for (int i = 0; i < made.grid.nx; ++i) {
                    const std::size_t c = made.grid.at(i, j);
                    std::fprintf(out, "%d %d %.5f %.5f %.5f %.5f %.5f %.5f %.5f %.5f\n", i, j,
                                 made.rock[c] + made.soil[c] + made.sand[c] + made.loose[c],
                                 made.rock[c], made.soil[c], made.sand[c], made.loose[c],
                                 made.depth[c], made.qx[c], made.qz[c]);
                }
            std::fclose(out);
        }
    }
    std::cout << "    generated in " << r.total_ms << " ms (drainage " << r.drainage_ms << ", erosion "
              << r.erosion_ms << ", river " << r.river_ms << " ms for " << r.river_time_s
              << " s of river); " << r.depressions << " depressions: " << r.lakes << " kept as ponds, "
              << r.pits_filled << " pits filled with " << r.pits_filled_m3 << " m^3; carved "
              << r.carved_m3 << " m^3; erosion took up " << r.eroded_m3 << " m^3 and laid down "
              << r.deposited_m3 << " m^3\n";
    std::cout << "    river: " << r.river_in_m3_s << " m^3/s in, " << r.river_out_m3_s
              << " m^3/s out, " << r.river_volume_m3 << " m^3 standing\n";
    require(!r.from_cache, "the first valley is generated");
    require(made.grid.nx == 156 && made.grid.nz == 125, "5 x 4 chunks of 31 cells");
    require(r.lakes >= 1 && !made.lakes.empty(), "the hollow on the floodplain is kept as a pond");
    const Lake &pond = made.lakes.front();
    require(pond.deepest_m > 0.3 && pond.area_m2 > 5.0, "and it is a real pond");
    near(r.river_out_m3_s, p.discharge_m3_s, 0.05 * p.discharge_m3_s, "the river passes on what it is fed");
    // The pond brims at its spill level.
    const TerrainField ground(made.grid, made.rock, made.soil, made.sand, made.loose, made.moisture);
    const auto centre = ground.cellAt(pond.x_m, pond.z_m);
    require(centre.has_value(), "the pond is on the ground");
    near(ground.height(*centre) + made.depth[*centre], pond.surface_m, 0.01, "the pond stands at its spill level");
    // Bare rock somewhere: the knoll.
    std::size_t bare = 0;
    for (std::size_t c = 0; c < made.grid.cells(); ++c) bare += ground.surface(c) == Surface::Rock;
    require(bare > 50, "the knoll's rock is bare");
    const Landscape again = valley(p, folder.string());
    require(again.report.from_cache, "the second time it is read back");
    require(again.rock == made.rock && again.soil == made.soil && again.sand == made.sand &&
                again.depth == made.depth && again.qx == made.qx,
            "and it is the same valley, bit for bit");
    std::cout << "    read back from " << again.report.cache_path << "\n";
    fs::remove_all(folder, ignored);
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"digging is accounted by material", diggingIsAccountedByMaterial},
        {"a pit in sand slumps to its angle of repose", aPitInSandSlumpsToItsAngleOfRepose},
        {"a trench in soil stands and a deep one does not", aTrenchInSoilStandsAndADeepOneDoesNot},
        {"rock does not slump", rockDoesNotSlump},
        {"a cut block is exactly the rock that left", aCutBlockIsExactlyTheRockThatLeft},
        {"digging one corner does not activate the rest", diggingOneCornerDoesNotActivateTheRest},
        {"height follows the collider's split", heightAtFollowsTheColliderSplit},
        {"a valley is shaped by water and saved", aValleyIsShapedByWaterAndSaved},
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
