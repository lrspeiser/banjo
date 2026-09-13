#pragma once

// Rivers, lakes and floods as columns of water, not as water voxels.
//
// This is the Saint-Venant (shallow-water) system on a horizontal grid: every
// cell holds one column of water -- how high its surface stands and how fast
// it is moving sideways -- and the ground under it is the bottom boundary. A
// 256 x 256 valley is 65,536 columns where the same volume as 3D cells would be
// sixteen million; the extra dimension is what is not paid for.
//
// It is still physics. The two equations are conservation of mass and of
// horizontal momentum, with hydrostatic pressure, the slope of the bed, and
// bed friction:
//
//     dh/dt  + d(hu)/dx + d(hv)/dz                    = 0
//     d(hu)/dt + d(hu^2 + g h^2/2)/dx + d(huv)/dz    = -g h db/dx - friction
//     d(hv)/dt + d(huv)/dx + d(hv^2 + g h^2/2)/dz    = -g h db/dz - friction
//
// THE THREE THINGS IT HAS TO GET RIGHT, AND HOW
//
// 1. A lake at rest stays EXACTLY at rest. A naive discretisation of the bed
//    slope term leaves a residual force wherever the bed is not flat, and a
//    still pond starts to slosh on its own. The hydrostatic reconstruction of
//    Audusse, Bouchut, Bristeau, Klein & Perthame (2004) -- the scheme behind
//    Basilisk's saint-venant.h -- balances the pressure and the bed slope face
//    by face. It is well balanced in exact arithmetic; to make it well balanced
//    in FLOATING POINT the state is stored as the surface elevation eta rather
//    than the depth h. Two columns of a still lake then hold the same eta bit
//    for bit, the reconstructed depths on both sides of every face are the same
//    number, and every flux is exactly zero. Stored as depth, eta = h + b is
//    rebuilt from two rounded numbers and a still lake creeps at 1e-16 m/s.
//
// 2. Wet and dry. A cell with no water in it is a cell, not a hole in the
//    grid: the reconstruction takes the depth on each side of a face down to
//    zero wherever the bed on the other side stands higher than the water, so
//    a lake meets its shore without pushing through it, and a flood front
//    advances over dry ground without negative depths (the scheme is positive
//    for a step within the CFL limit below, and anything rounding takes below
//    zero is put back and COUNTED, never hidden).
//
// 3. Its own clock, within its own stability limit. An explicit scheme is
//    stable only while no wave crosses more than a fraction of a cell per
//    step: dt <= C dx / max(|u| + sqrt(g h)). advance(dt) takes exactly the
//    world time it is asked for, in as many substeps as that limit requires --
//    never one enormous step, which is the tempting and wrong way to make a
//    solver "fast". The safe levers are fewer active cells and coarser grids,
//    and this uses the first: only tiles holding water, and their neighbours,
//    are computed at all.
//
// Mass is conserved to rounding: every face flux leaves one cell and enters its
// neighbour, and the ledger counts everything that crosses the domain's edge.
#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

namespace banjo::water {

// Square cells, centred on the points of the terrain's height field, so a
// column of water and the column of ground under it are the same column.
struct Grid {
    int nx{};
    int nz{};
    double dx{};
    // World position of the CENTRE of cell (0, 0). x runs along i, z along j.
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

// The four edges of the domain. West is i = 0 (lowest x), east is i = nx - 1,
// south is j = 0 (lowest z), north is j = nz - 1.
enum class Edge : std::uint8_t { West = 0, East = 1, South = 2, North = 3 };

// Water arriving across part of one edge: a river's source. The discharge is
// shared equally among the faces, and each carries in the momentum of water
// arriving at that rate -- the water does not appear standing still.
struct Inflow {
    std::string name;
    Edge edge{Edge::West};
    int from{};   // cells along that edge, inclusive
    int to{};
    double discharge_m3_s{};
};

// Where water may leave freely across part of an edge: a river's mouth. It is
// a free outfall -- the water leaves over the edge's own bed as over a
// broad-crested weir, at no less than the critical discharge for its depth --
// so water standing at the mouth drains rather than waiting to be pushed.
// Nothing comes back in.
struct Outflow {
    std::string name;
    Edge edge{Edge::East};
    int from{};
    int to{};
};

struct Settings {
    double gravity_m_s2{9.81};
    double density_kg_m3{1000.0};
    // Manning's roughness for the bed, s / m^(1/3). 0.03 is a clean natural
    // stream; a weedy one is 0.05. DECLARED, not calibrated to any river.
    double manning_n{0.03};
    // Fraction of the CFL limit. Positivity of this scheme needs 1/4 with four
    // faces per cell, so 0.24 leaves rounding room.
    double cfl{0.24};
    // Below this a column is dry: it keeps its water, but has no velocity.
    double dry_m{1.0e-6};
    // Kurganov-Petrova desingularisation: how thin a film has to be before
    // its velocity is damped rather than divided out.
    double film_m{1.0e-3};
    // The longest substep ever taken, even when the CFL limit allows more: the
    // coupling to bodies reads this state between substeps.
    double max_step_s{1.0 / 30.0};
    // A ceiling on speed that no river reaches. Reaching it is a fault and is
    // counted in Stats::speed_capped.
    double max_speed_m_s{30.0};
    // Tiles of this many cells on a side are skipped when they, and their
    // neighbours, hold no water. Small, because a river is narrow and the
    // one-tile halo around it is what a big tile wastes.
    int tile{8};
};

// Everything that crossed the boundary of the water, in cubic metres.
//
//     volume - initial = inflow - outflow + numerical + residual
//
// residual is what rounding did and nothing else.
struct Ledger {
    double initial_m3{};
    double inflow_m3{};
    double outflow_m3{};
    // Water the arithmetic had to put back to keep a depth from going
    // negative. Reported, never hidden.
    double numerical_m3{};
    // Momentum bodies put into the water (the reaction to the drag the water
    // put on them), newton seconds, and what could not be given to a column
    // too shallow to carry it.
    double impulse_in_x_n_s{};
    double impulse_in_z_n_s{};
    double impulse_dropped_n_s{};
};

struct Stats {
    double time_s{};
    std::uint64_t substeps{};
    double last_substep_s{};
    double max_speed_m_s{};       // |u| + sqrt(g h), the wave speed the CFL uses
    std::size_t active_cells{};   // cells computed in the last substep
    std::size_t wet_cells{};
    std::size_t tiles{};
    std::size_t active_tiles{};
    std::uint64_t speed_capped{};
    std::uint64_t clamped{};      // depths rounding took below zero
};

class ShallowWater {
public:
    ShallowWater(Grid grid, std::vector<double> terrain_m, Settings settings = {});

    [[nodiscard]] const Grid &grid() const { return grid_; }
    [[nodiscard]] const Settings &settings() const { return settings_; }

    // The ground, the bed the water actually stands on (ground or whatever
    // obstacle is resting on it), the surface, and the depth between them.
    [[nodiscard]] double terrain(std::size_t cell) const { return terrain_[cell]; }
    [[nodiscard]] double bed(std::size_t cell) const { return bed_[cell]; }
    [[nodiscard]] double surface(std::size_t cell) const { return eta_[cell]; }
    [[nodiscard]] double depth(std::size_t cell) const { return eta_[cell] - bed_[cell]; }
    [[nodiscard]] double dischargeX(std::size_t cell) const { return qx_[cell]; }
    [[nodiscard]] double dischargeZ(std::size_t cell) const { return qz_[cell]; }
    [[nodiscard]] bool wet(std::size_t cell) const { return depth(cell) > settings_.dry_m; }
    // Depth-averaged velocity, zero in a dry column.
    [[nodiscard]] double velocityX(std::size_t cell) const;
    [[nodiscard]] double velocityZ(std::size_t cell) const;

    // Put water in: depth over the bed, or a surface (a lake's level: cells
    // whose bed stands above it stay dry). Setting state is not flow and is not
    // in the ledger; call resetLedger() after building the starting water.
    void setDepth(std::size_t cell, double depth_m);
    void setSurface(std::size_t cell, double surface_m);
    void setDischarge(std::size_t cell, double qx_m2_s, double qz_m2_s);

    // The ground under a column has changed -- dug out, filled in. The column
    // keeps its WATER: digging does not make any and filling does not destroy
    // any. Water over ground that was raised past it is pushed to the nearest
    // open column.
    void setTerrain(std::size_t cell, double terrain_m);
    // Solid tops resting on the bed, one per cell; -infinity where there is
    // nothing. A block sitting on the riverbed raises the bed the water sees to
    // its top, so a row of them is a dam and water has to rise over it. Water
    // standing where a block has just arrived is displaced to its open
    // neighbours; where one has gone, the column keeps its water and the
    // surface drops into the space.
    void setObstacles(const std::vector<double> &top_m);
    [[nodiscard]] const std::vector<double> &obstacles() const { return obstacle_; }

    void addInflow(const Inflow &inflow);
    void addOutflow(const Outflow &outflow);
    [[nodiscard]] const std::vector<Inflow> &inflows() const { return inflows_; }
    [[nodiscard]] const std::vector<Outflow> &outflows() const { return outflows_; }
    // Change a source's discharge from now: a flood, a drought.
    bool setInflow(const std::string &name, double discharge_m3_s);

    // Momentum a body gave the water this step, newton seconds, horizontal.
    // Applied at the start of the next substep, to the column it was given to.
    void addImpulse(std::size_t cell, double jx_n_s, double jz_n_s);

    // Exactly dt_s of world time, in as many substeps as the CFL limit needs.
    // Returns how many.
    int advance(double dt_s);

    [[nodiscard]] double volume() const;
    [[nodiscard]] double wetArea() const;
    [[nodiscard]] const Ledger &ledger() const { return ledger_; }
    [[nodiscard]] double residual() const;
    // Starts the ledger from the water as it stands.
    void resetLedger();
    [[nodiscard]] const Stats &stats() const { return stats_; }
    // What is crossing the edges right now, cubic metres per second, from the
    // last substep.
    [[nodiscard]] double inflowRate() const { return inflow_rate_; }
    [[nodiscard]] double outflowRate() const { return outflow_rate_; }

    // Everything that makes the water what it is, for carrying it into another
    // world: depth (not surface, so a column keeps its water over whatever
    // ground it is put back on), discharge, the clock and the ledger.
    struct State {
        std::vector<double> depth, qx, qz;
        Ledger ledger;
        double time_s{};
    };
    [[nodiscard]] State state() const;
    // Depths are taken over the TERRAIN (obstacles are re-applied afterwards
    // by whoever knows where they are now), so the volume is exactly what was
    // saved.
    void restore(const State &state);

private:
    void substep(double dt);
    void refreshTiles();
    [[nodiscard]] double waveSpeed() const;
    void displace(std::size_t cell, double volume_m3);
    [[nodiscard]] double faceArea() const { return grid_.dx * grid_.dx; }

    Grid grid_;
    Settings settings_;
    std::vector<double> terrain_, obstacle_, bed_, eta_, qx_, qz_;
    std::vector<double> d_eta_, d_qx_, d_qz_;
    std::vector<double> impulse_x_, impulse_z_;
    std::vector<std::size_t> impulse_cells_;
    bool impulses_pending_{};
    std::vector<Inflow> inflows_;
    std::vector<Outflow> outflows_;
    // Per boundary face: 0 wall, 1 + inflow index, -(1 + outflow index).
    std::vector<int> west_, east_, south_, north_;
    int tiles_x_{}, tiles_z_{};
    std::vector<std::uint8_t> tile_wet_, tile_active_;
    // Tiles computed whether or not they hold water: the ones a source is in.
    std::vector<std::uint8_t> tile_always_;
    bool tiles_dirty_{true};
    Ledger ledger_;
    Stats stats_;
    double inflow_rate_{}, outflow_rate_{};
    double speed_{};   // wave speed for the next substep
    bool speed_known_{};
};

} // namespace banjo::water
