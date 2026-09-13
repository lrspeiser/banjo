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

// A DECLARED simplified model: each material is a bulk density, a friction
// angle and a cohesion. Values are textbook ranges for dry-ish ground, not a
// calibration of any site. Rock is the engine's stone -- the "concrete" preset,
// 2400 kg/m^3 -- so a block cut out of it is exactly the matter it was.
struct GroundMaterial {
    const char *name{};
    double density_kg_m3{};
    double friction_angle_deg{};
    double cohesion_pa{};
};
[[nodiscard]] const GroundMaterial &rockMaterial();
[[nodiscard]] const GroundMaterial &soilMaterial();
[[nodiscard]] const GroundMaterial &sandMaterial();

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

    TerrainField(Grid grid, std::vector<double> rock_top_m, std::vector<double> soil_m,
                 std::vector<double> sand_m, std::vector<double> loose_soil_m = {},
                 std::vector<float> moisture = {});

    [[nodiscard]] const Grid &grid() const { return grid_; }
    [[nodiscard]] double height(std::size_t c) const {
        return rock_[c] + soil_[c] + sand_[c] + loose_[c];
    }
    [[nodiscard]] double rockTop(std::size_t c) const { return rock_[c]; }
    [[nodiscard]] double soil(std::size_t c) const { return soil_[c]; }
    [[nodiscard]] double sand(std::size_t c) const { return sand_[c]; }
    [[nodiscard]] double looseSoil(std::size_t c) const { return loose_[c]; }
    [[nodiscard]] float moisture(std::size_t c) const { return moisture_[c]; }
    [[nodiscard]] Surface surface(std::size_t c) const;
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
    EditReport dig(double ax, double az, double bx, double bz, double width_m, double depth_m);
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

    Grid grid_;
    std::vector<double> rock_, soil_, sand_, loose_;
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
