#pragma once

// What the ground is made of, held still until something makes it move.
//
// A mountain does not need millions of soil grains asking every step whether
// they should fall. This holds the ground as COLUMNS -- one per point of the
// height field -- and each column is layered: bedrock at the bottom, the soil
// that formed on it, and loose material on top (sand washed down by water, and
// soil that has slid or been heaped there). Nothing here moves on its own. The
// ground changes when something changes it: a spade, material slumping into a
// hole the spade made, material heaped up.
//
// WHEN IT DOES MOVE
//
// Every edit marks the columns it touched, and only those -- and their
// neighbours -- are asked whether they are still stable. A face between two
// columns fails when the drop across it is more than the material on top of
// the higher one can hold:
//
//     drop  >  max( d tan(phi),  H_c )          H_c = 2.67 (c / gamma) tan(45 + phi/2)
//
// friction angle phi and cohesion c from the material (Mohr-Coulomb); H_c is
// the height an unsupported vertical cut in cohesive soil stands to (Terzaghi,
// with tension cracks). Loose sand has no cohesion and slumps to its angle of
// repose; native soil holds a spade-deep trench with vertical walls; rock does
// not slump at all. What fails slides down to the lower column at the speed a
// granular layer of that thickness flows, sqrt(g h), so a bank collapses over
// a fraction of a second rather than in one frame -- and every column it lands
// on is checked in turn. Digging one corner therefore asks about that corner
// and whatever the collapse actually reaches, and nothing else in the valley.
//
// A face only STARTS to give way when the layer that would flow -- half the
// excess drop -- is thicker than a granular layer can flow at all: Pouliquen's
// h_stop, about ten grain diameters, 5 mm for sand. Below that a layer on a
// slope stops, which is why a real heap stands a couple of degrees steeper
// than its angle of repose (its angle of maximum stability) and why a slump
// ends rather than creeping for ever. Declared: kStopLayerM below.
//
// Every cubic metre is accounted, by material: dug out and carried away, cut
// out as a block, heaped up, or moved from one column to another by a slump.
#include "core/Math.hpp"

#include <cstddef>
#include <cstdint>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace banjo::terrain {

// Height-field points, dx apart. Point (i, j) is at x0 + i dx, z0 + j dx, and
// is also the centre of the column (and of the water cell) at (i, j).
struct Grid {
    int nx{};
    int nz{};
    double dx{};
    double x0{};
    double z0{};
    [[nodiscard]] std::size_t cells() const {
        return static_cast<std::size_t>(nx) * static_cast<std::size_t>(nz);
    }
    [[nodiscard]] std::size_t at(int i, int j) const {
        return static_cast<std::size_t>(j) * static_cast<std::size_t>(nx) +
               static_cast<std::size_t>(i);
    }
    [[nodiscard]] double xOf(int i) const { return x0 + dx * i; }
    [[nodiscard]] double zOf(int j) const { return z0 + dx * j; }
};

// What is on top of a column, for drawing and for saying what it is.
enum class Surface : std::uint8_t { Rock = 0, Soil = 1, Sand = 2 };

// What one run of a column is made of. The first three are the Surface values,
// so a run's kind and a column's surface never disagree. Loose soil is its own
// kind because it IS a different material -- soil that lost its cohesion when it
// was dug -- and a pit someone has heaped back into should not look like the
// bank it came out of.
//
// The rest are what the rock is made of, and they are the reason a column is
// said in runs at all (docs/earth-and-mining-plan.md): a mantle of rock rotted
// near the surface, a bed of clay dipping across the valley -- the weak ground a
// roof will fall out of -- and a vein of ore, whose top is oxidised and soft
// where the weather has been at it.
enum class RunKind : std::uint8_t {
    Rock = 0, Soil = 1, Sand = 2, LooseSoil = 3,
    WeatheredRock = 4, Clay = 5, Ore = 6, OxidisedOre = 7,
    // A bed of nothing: what somebody took out and did not fill in. A void is
    // held as a bed because that is where it is -- between the rock under it
    // and the rock over it -- and because everything that already walks a
    // column then walks the hole too (docs/earth-and-mining-plan.md, stage 3).
    Void = 8,
};
inline constexpr int kRunKinds = 9;
// A column's TOPMOST bed is never a void: a hole open to the sky is a hole in
// the ground's own surface, which a height field already says. So the surface,
// the soil on it and everything that reads them are untouched by a void, and a
// void is always something with rock over it.
[[nodiscard]] constexpr bool isVoid(RunKind kind) { return kind == RunKind::Void; }
// Rock a block can be cut out of. Weathered rock is rock, rotted: it is the same
// matter at the same density, so a block of it is a block. Clay and ore are not,
// and a cut that would reach them is refused rather than counted as rock.
[[nodiscard]] constexpr bool isRockLike(RunKind kind) {
    return kind == RunKind::Rock || kind == RunKind::WeatheredRock;
}

// A column bottom to top, as runs: a material and the height it reaches. A
// column is already this -- rock, the soil that formed on it, and the loose
// mixture on top -- and saying it in runs is what lets a cut face be drawn in
// the materials it goes through, and what the ground will keep on holding when
// it holds strata and veins (docs/earth-and-mining-plan.md).
struct Run {
    RunKind kind{};
    double top_m{};
};

// A DECLARED simplified model: each material is a bulk density, a friction
// angle and a cohesion. Values are textbook ranges for dry-ish ground, not a
// calibration of any site. Rock is the engine's stone -- the "concrete" preset,
// 2400 kg/m^3 -- so a block cut out of it is exactly the matter it was.
struct GroundMaterial {
    const char *name{};
    double density_kg_m3{};
    double friction_angle_deg{};
    double cohesion_pa{};
    // The ground's own share of the coefficient c in the rolling-resistance
    // couple M = c N r on a ball rolling over it (the ball adds its own). What
    // keeps a ball set down on a gentle sandy bank where it was put, and lets
    // one roll on across bare rock. Sources and uncertainty:
    // docs/rolling-resistance.md.
    double rolling_resistance{};
    // Whether a table or a measurement gives it, and which.
    bool rolling_sourced{};
    const char *rolling_basis{};
};
[[nodiscard]] const GroundMaterial &rockMaterial();
[[nodiscard]] const GroundMaterial &soilMaterial();
[[nodiscard]] const GroundMaterial &sandMaterial();
[[nodiscard]] const GroundMaterial &groundMaterialOf(Surface surface);

// The rock under a column, bottom to top: what each bed is and the height it
// reaches. Every world there has been has one bed of rock, and that is what this
// holds today; beds and veins are what the rest of it is for
// (docs/earth-and-mining-plan.md). Held the way the engine walks it -- where a
// column's beds begin, how many are live, what each is, and its top -- because a
// column's beds are read far more often than they change.
//
// A column always keeps at least one bed. A cut lowers the top bed and drops the
// ones it takes whole. Excavation can split beds; spare rows grow on demand,
// bounded by kRunsMost minus the two surface layers sent to the renderer.
struct Beds {
    std::vector<std::uint32_t> start;    // cells + 1 offsets into kind and top
    std::vector<std::uint32_t> count;    // how many of each column's are live
    std::vector<std::uint8_t> kind;
    std::vector<double> top;
    [[nodiscard]] bool empty() const { return start.empty(); }
    // One bed of rock under every column, from a rock top per column: the ground
    // as every world has had it.
    [[nodiscard]] static Beds ofRock(const std::vector<double> &rock_top_m);
};

// Matter by kind, in cubic metres.
struct Volumes {
    double rock_m3{};
    double soil_m3{};
    double sand_m3{};
    [[nodiscard]] double total() const { return rock_m3 + soil_m3 + sand_m3; }
};

// Everything that has crossed the ground's boundary, by kind.
//
//     now = initial - dug - cut + deposited          (each kind, to rounding)
//
// A slump moves matter between columns and changes none of these; it is
// counted separately so it can be seen.
struct Ledger {
    Volumes initial;
    Volumes dug;
    Volumes cut;
    Volumes deposited;
    double slumped_m3{};
    // Native soil that slid and is now loose: still soil, no longer cohesive.
    double loosened_m3{};
};

// What an edit touched: columns changed, the material that left or arrived.
struct EditReport {
    Volumes moved;                       // dug out, cut out, or heaped up
    std::vector<std::size_t> cells;      // columns whose height changed
    double mass_kg{};
    // How deep a dig actually went, and whether that was less than it was asked
    // to because what came out had to fit a budget (TerrainField::dig). A dig
    // made again at THIS depth takes out the same, which is what a room keeps.
    double depth_m{};
    bool limited{};
};

// A block of rock taken out of the ground as one piece.
struct CutBlock {
    Vec3 center_m{};
    Vec3 size_m{};
    double volume_m3{};
    double mass_kg{};
};

// One pass of the stability check.
struct Relaxed {
    std::size_t checked{};               // columns asked
    std::size_t failed{};                // faces that gave way
    double moved_m3{};
    std::vector<std::size_t> changed;    // columns whose height changed
};

class TerrainField {
public:
    // Columns chunked for the colliders: 31 cells on a side, so a chunk's
    // height field is 32 x 32 points and neighbouring chunks share an edge.
    static constexpr int kChunkCells = 31;
    // The thinnest layer that flows (Pouliquen's h_stop): a face gives way
    // only when half its excess drop is more than this.
    static constexpr double kStopLayerM = 0.005;
    // The steepest drop across a face of this run that the material on top of
    // a column holds before it starts to go: tan(phi) run, or the height a
    // cohesive cut stands, plus the stopping layer on both sides.
    [[nodiscard]] static double stableDrop(const GroundMaterial &material, double run_m);

    // How deep the rock goes below the lowest of it: the earth a mine has to
    // work in. It was 2 m, which is no earth at all.
    static constexpr double kEarthDepthM = 30.0;

    TerrainField(Grid grid, std::vector<double> rock_top_m, std::vector<double> soil_m,
                 std::vector<double> sand_m, std::vector<double> loose_soil_m = {},
                 std::vector<float> moisture = {});
    // The same, with the rock said as beds.
    TerrainField(Grid grid, Beds beds, std::vector<double> soil_m, std::vector<double> sand_m,
                 std::vector<double> loose_soil_m, std::vector<float> moisture);

    [[nodiscard]] const Grid &grid() const { return grid_; }
    // Declared surface geometry. Material volumes/laws still use the same
    // layered columns; this changes the surface contacted, not their contents.
    void setColumnSurface(bool enabled) { column_surface_ = enabled; }
    [[nodiscard]] bool columnSurface() const { return column_surface_; }
    void setCutSurface(bool enabled) { cut_surface_ = enabled; }
    [[nodiscard]] bool cutSurface() const { return cut_surface_; }
    [[nodiscard]] const char *surfaceGeometry() const { return column_surface_ ? "columns" : cut_surface_ ? "cuts" : "smooth"; }
    // Generated triangular landscape plus a cell-local displacement. Changes
    // retain their exact height instead of influencing the adjacent hillside.
    [[nodiscard]] const std::vector<float> &baseline() const { return baseline_; }
    [[nodiscard]] double baselineHeightAt(double x, double z) const;
    [[nodiscard]] double height(std::size_t c) const {
        return rockTop(c) + soil_[c] + sand_[c] + loose_[c];
    }
    // The top of the topmost bed: where the rock stops and the soil starts.
    [[nodiscard]] double rockTop(std::size_t c) const {
        return beds_.top[beds_.start[c] + beds_.count[c] - 1];
    }
    [[nodiscard]] const Beds &beds() const { return beds_; }
    // The working in a column, if it has one: the top of what is under it, and
    // the underside of the rock over it. One to a column today.
    struct Working { double floor_m{}; double roof_m{}; };
    [[nodiscard]] std::optional<Working> workingIn(std::size_t c) const;
    [[nodiscard]] bool hasWorkings() const { return workings_ > 0; }
    // The bed `k` of a column reaches from here to its own top; the lowest
    // reaches down to floor().
    [[nodiscard]] double bedBottom(std::size_t c, std::uint32_t k) const {
        return k == 0 ? floor_ : beds_.top[beds_.start[c] + k - 1];
    }
    [[nodiscard]] double soil(std::size_t c) const { return soil_[c]; }
    [[nodiscard]] double sand(std::size_t c) const { return sand_[c]; }
    [[nodiscard]] double looseSoil(std::size_t c) const { return loose_[c]; }
    [[nodiscard]] float moisture(std::size_t c) const { return moisture_[c]; }
    [[nodiscard]] Surface surface(std::size_t c) const;
    // The runs of one column, bottom to top, into a buffer of at least
    // kRunsMost. Returns how many it wrote; never none, because there is always
    // rock. The beds come first, then the soil that formed on them, then the
    // loose layer -- which is sand and loose soil MIXED (see strip(): it is one
    // mixture, not two layers in an order), so it is one run, of whichever it is
    // mostly, the rule surface() uses.
    static constexpr int kRunsMost = 16;
    int runsOf(std::size_t c, Run *out) const;
    // The ground under a point, interpolated the way the collider is.
    [[nodiscard]] double heightAt(double x, double z) const;
    [[nodiscard]] std::optional<std::size_t> cellAt(double x, double z) const;
    // Slope at a column, as the angle from horizontal, degrees.
    [[nodiscard]] double slopeDeg(std::size_t c) const;
    // The level the rock goes down to. Nothing is dug below it and the
    // world's safety floor stands under it.
    [[nodiscard]] double floor() const { return floor_; }
    [[nodiscard]] double lowest() const;
    [[nodiscard]] double highest() const;

    // Dig along a line: every column whose centre is within width/2 of the
    // segment from a to b (x, z) is taken down `depth` below where it stands,
    // loose material first, then soil. Rock is not dug -- a spade stops on it.
    //
    // With a budget, it takes out no more than `max_kg`: the same trench, as
    // deep as the budget lets it go and no deeper -- every column to the one
    // depth, as a dig always is -- so a spade that can lift 30 kg more takes
    // 30 kg and leaves the rest in the ground. Nothing at all fits a budget of
    // nothing, and the ground is then untouched.
    EditReport dig(double ax, double az, double bx, double bz, double width_m, double depth_m,
                   double max_kg = std::numeric_limits<double>::infinity());
    // The columns such a dig takes, in the order it takes them: every column
    // whose centre is within width/2 of the segment. Changes nothing -- it is
    // how a caller that knows a VOLUME, not a depth, works out the depth.
    [[nodiscard]] std::vector<std::size_t> columnsAlong(double ax, double az, double bx, double bz,
                                                        double width_m) const;
    // Take rock out of a column between two heights: what a tool has broken
    // loose (docs/earth-and-mining-plan.md, stage 4). Cell-quantised, so a
    // working is made of cubes. Broken out to daylight it is an open cut and
    // everything over the rock comes off with it; under cover it is a hole with
    // rock over it, and the beds it passes through are split into what is under
    // the working, the working, and what is over it. What leaves is counted by
    // what it was made of. Refused, with the reason, where the column has no
    // room left to say another working.
    EditReport breakOut(double x, double z, double from_m, double to_m);
    // What one kind of ground is at a height in a column: what a point meets
    // when it gets there.
    [[nodiscard]] RunKind kindAt(std::size_t c, double height_m) const;
    // Rock broken a little at a time. A blow buys a volume (rock-work-v1), and
    // a volume smaller than a cell is not a hole -- it is progress towards one.
    // This keeps that progress and takes a cell of rock out when it has been
    // paid for; `broken` is how far through that cell the work has got, 0 to 1,
    // for anyone drawing it.
    //
    // The cell is the one the blow landed in, at `at_height_m`: a pick swung at
    // a tunnel face takes rock out at the miner's chest, and does not bring the
    // hill down from the top of the column. Working a different level in the
    // same column starts that level, and what was owed on the old one is left
    // there.
    //
    // A cell comes out only if `rock_budget_m3` of rock can be carried away,
    // the same budget dig() takes: a cell of rock nobody can lift stays where it
    // is, the account keeps what was paid, and `full` says why nothing moved.
    struct Chipped {
        EditReport edit;         // empty until a cell is paid for
        double broken{};         // how far through the cell this column now is
        bool full{};             // paid for, and more rock than can be carried
    };
    Chipped chip(double x, double z, double at_height_m, double volume_m3,
                 double rock_budget_m3 = std::numeric_limits<double>::infinity());
    [[nodiscard]] double brokenShare(std::size_t c) const;
    // What a cell holds: the rock in the cell at this height in this column,
    // which is what a chip there has to pay for. Less than a whole cell where
    // the cell is the one the ground surface runs through, and 0 where there is
    // no rock there at all.
    [[nodiscard]] double cellRockM3(std::size_t c, double at_height_m) const;
    // Heap material up around a point: a cone of it within `radius`, which the
    // stability check then lets settle to whatever slope it can hold.
    EditReport deposit(double x, double z, double radius_m, double sand_m3, double soil_m3);
    // Cut a block `height_m` tall out of bare rock, `cells_x` by `cells_z`
    // columns centred on (x, z). The cut is a flat plane `height_m` below the
    // mean of the rock's top over the footprint, so exactly footprint x height
    // of rock leaves the ground and the block is that box -- the same volume,
    // the same footprint, at the rock's own density. Refused, with the reason,
    // where there is soil over the rock, or where the rock is too uneven for a
    // block that shallow (some of it would have to come out of thin air).
    std::optional<CutBlock> cut(double x, double z, int cells_x, int cells_z, double height_m,
                                std::string *why = nullptr);

    // The stability check, on the world clock: one pass over the columns that
    // might have become unstable, moving what fails as far as it can flow in
    // dt. Returns what it did; nothing, once everything holds.
    Relaxed relax(double dt_s);
    [[nodiscard]] bool settled() const { return frontier_.empty(); }
    [[nodiscard]] std::size_t unsettled() const { return frontier_.size(); }
    // Ask about these columns (and their neighbours) on the next pass.
    void markChanged(const std::vector<std::size_t> &cells);

    // Chunks whose height changed since they were last taken.
    [[nodiscard]] int chunksX() const { return chunks_x_; }
    [[nodiscard]] int chunksZ() const { return chunks_z_; }
    [[nodiscard]] std::set<int> takeDirtyChunks();
    // The rectangle of points changed since it was last taken, for a host that
    // redraws only what moved. Empty (ni == 0) when nothing has.
    struct Rect { int i0{}, j0{}, ni{}, nj{}; };
    [[nodiscard]] Rect takeChangedRect();

    // An accepted state, not an edit recipe. In particular, pending columns
    // resume their next relaxation pass instead of settling during restore.
    struct State {
        Grid grid;
        Beds beds;
        std::vector<double> soil, sand, loose;
        std::vector<float> moisture;
        double floor{};
        Ledger ledger;
        std::set<std::size_t> frontier;
        std::set<int> dirty_chunks;
        Rect changed;
        std::size_t checked_total{}, frontier_peak{};
    };
    [[nodiscard]] State state() const;
    // Same-grid restoration. Invalid input leaves every current field intact.
    void restore(const State &saved);

    [[nodiscard]] Volumes volumes() const;
    [[nodiscard]] const Ledger &ledger() const { return ledger_; }
    // now - (initial - dug - cut + deposited), by kind: rounding and nothing else.
    [[nodiscard]] Volumes residual() const;
    void resetLedger();
    // Columns the stability check has looked at since the last reset, and at
    // most how many at once.
    [[nodiscard]] std::size_t checkedSinceReset() const { return checked_total_; }
    [[nodiscard]] std::size_t frontierPeak() const { return frontier_peak_; }
    void resetActivity() { checked_total_ = 0; frontier_peak_ = 0; }

private:
    void touched(std::size_t c);
    // Take up to `thickness` off the top of a column, loose first, then soil,
    // never rock. Returns how much of each came off.
    Volumes strip(std::size_t c, double thickness);
    // What strip() would take, taking nothing.
    [[nodiscard]] Volumes wouldStrip(std::size_t c, double thickness) const;

    // Take a column's rock down to `bottom`, dropping the beds that go whole,
    // and add what left to `took`. A column always keeps its lowest bed.
    void takeRockDownTo(std::size_t c, double bottom, Volumes &took);

    Grid grid_;
    bool column_surface_{};
    bool cut_surface_{};
    std::vector<float> baseline_;
    Beds beds_;
    std::size_t workings_{};     // how many columns hold one, so a world with
                                 // none pays nothing for them
    // Rock broken but not yet a cell's worth, by column: the level being worked
    // and what has been paid towards it. Only faces being worked are in it.
    struct Owed { int level{}; double m3{}; };
    std::map<std::size_t, Owed> chipped_;
    std::vector<double> soil_, sand_, loose_;
    std::vector<float> moisture_;
    double floor_{};
    Ledger ledger_;
    std::set<std::size_t> frontier_;
    std::set<int> dirty_chunks_;
    int chunks_x_{}, chunks_z_{};
    int changed_i0_{}, changed_j0_{}, changed_i1_{-1}, changed_j1_{-1};
    std::size_t checked_total_{}, frontier_peak_{};
};

} // namespace banjo::terrain
