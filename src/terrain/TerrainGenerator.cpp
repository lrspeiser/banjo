#include "terrain/TerrainGenerator.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <limits>
#include <queue>
#include <stdexcept>
#include <tuple>

namespace banjo::terrain {
namespace {

using Clock = std::chrono::steady_clock;
constexpr double kPi = 3.14159265358979323846;
constexpr double kGravity = 9.81;
constexpr std::size_t kNone = static_cast<std::size_t>(-1);

double msSince(Clock::time_point t0) {
    return std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
}

// ---- noise, deterministic in the seed --------------------------------------

std::uint64_t mix(std::uint64_t x) {
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}

double lattice(std::uint64_t seed, long i, long j) {
    const std::uint64_t h = mix(seed ^ mix(static_cast<std::uint64_t>(i) * 0x632be59bd9b4e019ULL ^
                                           static_cast<std::uint64_t>(j) * 0x85157af5ULL));
    return static_cast<double>(h >> 11) * (2.0 / 9007199254740992.0) - 1.0;
}

double fade(double t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }

double valueNoise(std::uint64_t seed, double x, double z) {
    const double fx = std::floor(x), fz = std::floor(z);
    const long i = static_cast<long>(fx), j = static_cast<long>(fz);
    const double u = fade(x - fx), v = fade(z - fz);
    const double a = lattice(seed, i, j), b = lattice(seed, i + 1, j);
    const double c = lattice(seed, i, j + 1), d = lattice(seed, i + 1, j + 1);
    return (a + u * (b - a)) + v * ((c + u * (d - c)) - (a + u * (b - a)));
}

double fbm(std::uint64_t seed, double x, double z, int octaves, double frequency) {
    double sum = 0.0, amplitude = 0.5, norm = 0.0;
    for (int k = 0; k < octaves; ++k) {
        sum += amplitude * valueNoise(seed + static_cast<std::uint64_t>(k) * 1013ULL, x * frequency, z * frequency);
        norm += amplitude;
        amplitude *= 0.5;
        frequency *= 2.0;
    }
    return sum / norm;
}

double smoothstep(double e0, double e1, double x) {
    const double t = std::clamp((x - e0) / (e1 - e0), 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

// ---- drainage ---------------------------------------------------------------

// Priority-Flood with a FIFO among equal levels (Barnes et al. 2014): every
// column is reached from the lowest route to a seed, `filled` is the level it
// would have to stand at to drain, and `down` is where it drains to. Seeds are
// where water can leave -- here, only the river's mouth, because everywhere
// else the domain's edge is a wall to the water too.
struct Drainage {
    std::vector<double> filled;
    std::vector<std::size_t> order;
    std::vector<std::size_t> down;
};

Drainage priorityFlood(const Grid &g, const std::vector<double> &h, const std::vector<std::size_t> &seeds) {
    Drainage out;
    const std::size_t n = g.cells();
    out.filled = h;
    out.down.assign(n, kNone);
    out.order.reserve(n);
    std::vector<std::uint8_t> closed(n, 0);
    using Item = std::tuple<double, std::uint64_t, std::size_t>;
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> open;
    std::uint64_t counter = 0;
    for (const std::size_t s : seeds) {
        if (closed[s]) continue;
        closed[s] = 1;
        open.emplace(h[s], counter++, s);
    }
    static constexpr int kDi[8] = {1, -1, 0, 0, 1, 1, -1, -1};
    static constexpr int kDj[8] = {0, 0, 1, -1, 1, -1, 1, -1};
    while (!open.empty()) {
        const auto [level, tick, c] = open.top();
        (void)tick;
        open.pop();
        out.order.push_back(c);
        const int i = static_cast<int>(c % static_cast<std::size_t>(g.nx));
        const int j = static_cast<int>(c / static_cast<std::size_t>(g.nx));
        for (int k = 0; k < 8; ++k) {
            const int x = i + kDi[k], z = j + kDj[k];
            if (x < 0 || z < 0 || x >= g.nx || z >= g.nz) continue;
            const std::size_t m = g.at(x, z);
            if (closed[m]) continue;
            closed[m] = 1;
            out.filled[m] = std::max(h[m], level);
            out.down[m] = c;
            open.emplace(out.filled[m], counter++, m);
        }
    }
    return out;
}

// How much water passes through each column: its own rain plus everything
// upstream of it, in the reverse of the order the flood reached them.
std::vector<double> accumulate(const Drainage &d, const std::vector<double> &rain) {
    std::vector<double> acc = rain;
    for (auto it = d.order.rbegin(); it != d.order.rend(); ++it)
        if (d.down[*it] != kNone) acc[d.down[*it]] += acc[*it];
    return acc;
}

struct Depression {
    std::vector<std::size_t> cells;
    double level{};
    double area{}, volume{}, deepest{};
    double x{}, z{};
};

std::vector<Depression> depressions(const Grid &g, const std::vector<double> &h,
                                    const std::vector<double> &filled) {
    std::vector<Depression> out;
    std::vector<std::uint8_t> seen(g.cells(), 0);
    const double area = g.dx * g.dx;
    for (std::size_t c = 0; c < g.cells(); ++c) {
        if (seen[c] || !(filled[c] - h[c] > 1.0e-6)) continue;
        Depression d;
        std::deque<std::size_t> queue{c};
        seen[c] = 1;
        while (!queue.empty()) {
            const std::size_t k = queue.front();
            queue.pop_front();
            d.cells.push_back(k);
            const double depth = filled[k] - h[k];
            d.volume += depth * area;
            d.deepest = std::max(d.deepest, depth);
            d.level = std::max(d.level, filled[k]);
            d.x += g.xOf(static_cast<int>(k % static_cast<std::size_t>(g.nx)));
            d.z += g.zOf(static_cast<int>(k / static_cast<std::size_t>(g.nx)));
            const int i = static_cast<int>(k % static_cast<std::size_t>(g.nx));
            const int j = static_cast<int>(k / static_cast<std::size_t>(g.nx));
            for (int dj = -1; dj <= 1; ++dj)
                for (int di = -1; di <= 1; ++di) {
                    const int x = i + di, z = j + dj;
                    if (x < 0 || z < 0 || x >= g.nx || z >= g.nz) continue;
                    const std::size_t m = g.at(x, z);
                    if (seen[m] || !(filled[m] - h[m] > 1.0e-6)) continue;
                    seen[m] = 1;
                    queue.push_back(m);
                }
        }
        d.area = static_cast<double>(d.cells.size()) * area;
        d.x /= static_cast<double>(d.cells.size());
        d.z /= static_cast<double>(d.cells.size());
        out.push_back(std::move(d));
    }
    return out;
}

// ---- erosion ----------------------------------------------------------------

// A limited hydraulic erosion pass in the manner of Mei, Decaudin & Hu (2007):
// water on the ground flows through virtual pipes to its four neighbours,
// driven by the difference in surface height; where it can carry more sediment
// than it holds (capacity ~ tilt x speed) it picks loose material up, and where
// it can carry less it puts it down as sand. Sediment moves with the water in
// proportion to the water that moved, so none is made or lost: whatever is
// still suspended at the end is put down where it is.
struct ErosionResult {
    double eroded_m3{};
    double deposited_m3{};
    double exported_m3{};
};

ErosionResult erode(const Grid &g, std::vector<double> &rock, std::vector<double> &soil,
                    std::vector<double> &sand, std::vector<double> &loose,
                    const std::vector<std::size_t> &sources, double source_m3_s,
                    const std::vector<std::size_t> &mouth, int iterations) {
    ErosionResult out;
    const std::size_t n = g.cells();
    const double area = g.dx * g.dx;
    const double dt = 0.05;                 // s, of the pass's own clock
    const double pipe = g.dx * g.dx;        // cross-section of a virtual pipe
    const double rain = 2.0e-5;             // m per iteration, everywhere
    const double capacity_k = 0.03, dissolve_k = 0.4, settle_k = 0.4, evaporate_k = 0.05;
    std::vector<double> d(n, 0.0), s(n, 0.0);
    std::vector<std::array<double, 4>> f(n, {0.0, 0.0, 0.0, 0.0});
    std::vector<std::uint8_t> is_mouth(n, 0);
    for (const std::size_t m : mouth) is_mouth[m] = 1;
    static constexpr int kDi[4] = {1, -1, 0, 0};
    static constexpr int kDj[4] = {0, 0, 1, -1};
    const auto surface = [&](std::size_t c) { return rock[c] + soil[c] + sand[c] + loose[c]; };
    std::vector<double> d_before(n), s_new(n);
    for (int it = 0; it < iterations; ++it) {
        for (std::size_t c = 0; c < n; ++c) d[c] += rain;
        for (const std::size_t c : sources) d[c] += source_m3_s * dt / (area * static_cast<double>(sources.size()));
        // Pipes.
        for (int j = 0; j < g.nz; ++j)
            for (int i = 0; i < g.nx; ++i) {
                const std::size_t c = g.at(i, j);
                double total = 0.0;
                for (int k = 0; k < 4; ++k) {
                    const int x = i + kDi[k], z = j + kDj[k];
                    if (x < 0 || z < 0 || x >= g.nx || z >= g.nz) { f[c][k] = 0.0; continue; }
                    const std::size_t m = g.at(x, z);
                    const double drop = (surface(c) + d[c]) - (surface(m) + d[m]);
                    f[c][k] = std::max(0.0, f[c][k] + dt * pipe * kGravity * drop / g.dx);
                    total += f[c][k];
                }
                if (total > 0.0) {
                    const double scale = std::min(1.0, d[c] * area / (total * dt));
                    for (double &v : f[c]) v *= scale;
                }
            }
        d_before = d;
        // Water and the sediment it carries.
        s_new = s;
        for (int j = 0; j < g.nz; ++j)
            for (int i = 0; i < g.nx; ++i) {
                const std::size_t c = g.at(i, j);
                for (int k = 0; k < 4; ++k) {
                    if (f[c][k] <= 0.0) continue;
                    const int x = i + kDi[k], z = j + kDj[k];
                    const std::size_t m = g.at(x, z);
                    const double moved = f[c][k] * dt / area;   // m of water column
                    d[c] -= moved;
                    d[m] += moved;
                    if (d_before[c] > 0.0) {
                        const double carried = s[c] * (moved / d_before[c]);
                        s_new[c] -= carried;
                        s_new[m] += carried;
                    }
                }
            }
        s.swap(s_new);
        // Pick up and put down.
        for (int j = 0; j < g.nz; ++j)
            for (int i = 0; i < g.nx; ++i) {
                const std::size_t c = g.at(i, j);
                d[c] = std::max(0.0, d[c]);
                s[c] = std::max(0.0, s[c]);
                if (d[c] < 1.0e-5) continue;
                const double u = (f[c][0] - f[c][1]) / (g.dx * std::max(d[c], 1.0e-3)) * 0.5;
                const double w = (f[c][2] - f[c][3]) / (g.dx * std::max(d[c], 1.0e-3)) * 0.5;
                const int i0 = std::max(0, i - 1), i1 = std::min(g.nx - 1, i + 1);
                const int j0 = std::max(0, j - 1), j1 = std::min(g.nz - 1, j + 1);
                const double gx = (surface(g.at(i1, j)) - surface(g.at(i0, j))) / ((i1 - i0) * g.dx);
                const double gz = (surface(g.at(i, j1)) - surface(g.at(i, j0))) / ((j1 - j0) * g.dx);
                const double tilt = std::sin(std::atan(std::hypot(gx, gz)));
                const double capacity = capacity_k * std::max(tilt, 0.02) * std::hypot(u, w) *
                                        std::min(1.0, d[c] / 0.05);
                if (capacity > s[c]) {
                    double take = dissolve_k * (capacity - s[c]) * dt;
                    // Loose material first, then soil; rock is not worn here.
                    const double from_loose = std::min(take, sand[c] + loose[c]);
                    if (from_loose > 0.0) {
                        const double share = sand[c] / std::max(1e-12, sand[c] + loose[c]);
                        // Taking all of a layer in proportion can round to a
                        // hair below zero; a layer is never less than none.
                        sand[c] = std::max(0.0, sand[c] - from_loose * share);
                        loose[c] = std::max(0.0, loose[c] - from_loose * (1.0 - share));
                        take -= from_loose;
                    }
                    const double from_soil = std::min(std::max(0.0, take), soil[c]);
                    soil[c] = std::max(0.0, soil[c] - from_soil);
                    const double got = from_loose + from_soil;
                    s[c] += got;
                    out.eroded_m3 += got * area;
                } else {
                    const double put = settle_k * (s[c] - capacity) * dt;
                    s[c] -= put;
                    sand[c] += put;
                    out.deposited_m3 += put * area;
                }
                d[c] *= (1.0 - evaporate_k * dt);
            }
        // What reaches the mouth leaves, water and sediment both.
        for (std::size_t c = 0; c < n; ++c)
            if (is_mouth[c]) {
                out.exported_m3 += s[c] * area;
                s[c] = 0.0;
                d[c] = 0.0;
            }
    }
    for (std::size_t c = 0; c < n; ++c) {
        sand[c] += s[c];
        out.deposited_m3 += s[c] * area;
    }
    (void)rock;
    return out;
}

} // namespace

void placeStillPonds(water::ShallowWater &water, const Landscape &land) {
    const Grid &g = land.grid;
    // Columns a river enters or leaves by: a pond reaching one of these is a
    // pond a river runs through, and its water is moving.
    std::vector<std::uint8_t> edge_of_river(g.cells(), 0);
    const auto mark = [&](water::Edge edge, int from, int to) {
        for (int k = from; k <= to; ++k) {
            int i = 0, j = 0;
            switch (edge) {
            case water::Edge::West: i = 0; j = k; break;
            case water::Edge::East: i = g.nx - 1; j = k; break;
            case water::Edge::South: i = k; j = 0; break;
            case water::Edge::North: i = k; j = g.nz - 1; break;
            }
            edge_of_river[g.at(i, j)] = 1;
        }
    };
    for (const auto &in : land.inflows) mark(in.edge, in.from, in.to);
    for (const auto &out : land.outflows) mark(out.edge, out.from, out.to);
    for (const Lake &lake : land.lakes) {
        const long ci = std::lround((lake.x_m - g.x0) / g.dx), cj = std::lround((lake.z_m - g.z0) / g.dx);
        if (ci < 0 || cj < 0 || ci >= g.nx || cj >= g.nz) continue;
        const std::size_t start = g.at(static_cast<int>(ci), static_cast<int>(cj));
        if (!(land.depth[start] > 0.0)) continue;
        std::vector<std::uint8_t> seen(g.cells(), 0);
        std::vector<std::size_t> pond{start};
        seen[start] = 1;
        bool river = false;
        for (std::size_t k = 0; k < pond.size(); ++k) {
            const std::size_t c = pond[k];
            river = river || edge_of_river[c];
            const int i = static_cast<int>(c % static_cast<std::size_t>(g.nx));
            const int j = static_cast<int>(c / static_cast<std::size_t>(g.nx));
            for (const auto &[di, dj] : {std::pair{1, 0}, std::pair{-1, 0}, std::pair{0, 1}, std::pair{0, -1}}) {
                const int x = i + di, z = j + dj;
                if (x < 0 || z < 0 || x >= g.nx || z >= g.nz) continue;
                const std::size_t m = g.at(x, z);
                if (seen[m] || !(land.depth[m] > 0.0)) continue;
                seen[m] = 1;
                pond.push_back(m);
            }
        }
        if (river) continue;
        for (const std::size_t c : pond) {
            water.setSurface(c, lake.surface_m);
            water.setDischarge(c, 0.0, 0.0);
        }
    }
}

namespace {

// ---- the river, run until it passes on what it is fed ------------------------

void settleRiver(Landscape &land, double limit_s) {
    const Grid &tg = land.grid;
    std::vector<double> ground(tg.cells());
    for (std::size_t c = 0; c < ground.size(); ++c)
        ground[c] = land.rock[c] + land.soil[c] + land.sand[c] + land.loose[c];
    water::ShallowWater sw({tg.nx, tg.nz, tg.dx, tg.x0, tg.z0}, ground);
    for (std::size_t c = 0; c < ground.size(); ++c)
        if (land.depth[c] > 0.0) sw.setDepth(c, land.depth[c]);
    for (const auto &in : land.inflows) sw.addInflow(in);
    for (const auto &out : land.outflows) sw.addOutflow(out);
    placeStillPonds(sw, land);
    sw.resetLedger();
    const Clock::time_point t0 = Clock::now();
    double fed = 0.0;
    for (const auto &in : land.inflows) fed += in.discharge_m3_s;
    double run = 0.0, before = sw.volume();
    while (run < limit_s) {
        sw.advance(5.0);
        run += 5.0;
        const double now = sw.volume();
        const double storage = (now - before) / 5.0;
        before = now;
        if (fed <= 0.0) break;
        if (std::abs(sw.outflowRate() - fed) < 0.03 * fed && std::abs(storage) < 0.02 * fed && run >= 30.0)
            break;
    }
    const water::ShallowWater::State state = sw.state();
    land.depth = state.depth;
    land.qx = state.qx;
    land.qz = state.qz;
    land.report.river_ms = msSince(t0);
    land.report.river_time_s = run;
    land.report.river_in_m3_s = sw.inflowRate();
    land.report.river_out_m3_s = sw.outflowRate();
    land.report.river_volume_m3 = sw.volume();
}

void setView(Landscape &land, double ex, double ez, double lx, double lz, double look_above) {
    const TerrainField field(land.grid, land.rock, land.soil, land.sand, land.loose, land.moisture);
    land.eye_m[0] = ex;
    land.eye_m[2] = ez;
    land.eye_m[1] = field.heightAt(ex, ez) + 1.62;
    land.look_m[0] = lx;
    land.look_m[2] = lz;
    land.look_m[1] = field.heightAt(lx, lz) + look_above;
}

} // namespace

// ---------------------------------------------------------------------------

Landscape generateValley(const ValleyParameters &p) {
    const Clock::time_point t0 = Clock::now();
    if (p.chunks_x < 1 || p.chunks_z < 1 || p.chunks_x > 16 || p.chunks_z > 16 || !(p.cell_m >= 0.05 && p.cell_m <= 2.0))
        throw std::invalid_argument("a valley is 1 to 16 chunks each way, with cells of 0.05 to 2 m");
    Landscape land;
    land.kind = "valley";
    Grid &g = land.grid;
    g.nx = p.chunks_x * TerrainField::kChunkCells + 1;
    g.nz = p.chunks_z * TerrainField::kChunkCells + 1;
    g.dx = p.cell_m;
    g.x0 = -0.5 * (g.nx - 1) * g.dx;
    g.z0 = -0.5 * (g.nz - 1) * g.dx;
    const std::size_t n = g.cells();
    const double length = (g.nx - 1) * g.dx;
    const double width = (g.nz - 1) * g.dx;
    const std::uint64_t seed = p.seed;
    const double phase = (static_cast<double>(mix(seed) % 1000) / 1000.0) * 2.0 * kPi;
    // The line the valley's floor meanders along, kept well inside the domain.
    const double swing = std::min(3.2, 0.12 * width);
    const auto centre = [&](double x) {
        const double t = (x - g.x0) / length;
        return swing * std::sin(2.0 * kPi * t * 1.5 + phase) +
               0.25 * swing * std::sin(2.0 * kPi * t * 4.0 + 1.3 * phase);
    };
    const double floodplain = std::min(4.5, 0.15 * width);
    const double valley_top = std::min(13.0, 0.42 * width);
    // A hollow on the floodplain, south of the river, and a rocky knoll north.
    const double pond_x = g.x0 + 0.62 * length;
    const double pond_z = centre(pond_x) - (floodplain + 0.6);
    const double pond_r = 2.0;
    const double knoll_x = g.x0 + 0.27 * length;
    const double knoll_z = centre(knoll_x) + floodplain + 4.0;
    const double knoll_r = 2.2;

    // The land before the knoll: floor, walls, hills, the hollow and its rim.
    const auto landform = [&](double x, double z) {
        const double d = std::abs(z - centre(x));
        // The floor falls about 1.2 percent along the valley.
        double y = 1.0 - 0.012 * (x - g.x0);
        y += 4.0 * smoothstep(floodplain, valley_top, d);
        y += 0.9 * fbm(seed, x, z, 4, 1.0 / 9.0) * smoothstep(floodplain - 0.5, floodplain + 5.0, d);
        y += 0.05 * fbm(seed + 17, x, z, 3, 1.0 / 2.5);
        const double rp = std::hypot(x - pond_x, z - pond_z);
        if (rp < pond_r) y -= 0.85 * (1.0 - (rp / pond_r) * (rp / pond_r));
        y += 0.2 * std::exp(-((rp - pond_r - 0.3) / 0.45) * ((rp - pond_r - 0.3) / 0.45));
        return y;
    };
    // The knoll is a flat-topped outcrop of rock -- a mesa, 1.4 m above the
    // land at its middle, with steep sides -- so there is somewhere level to
    // cut stone from.
    const double knoll_top = landform(knoll_x, knoll_z) + 1.4;
    std::vector<double> surface(n), outcrop(n, 0.0);
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < g.nx; ++i) {
            const double x = g.xOf(i), z = g.zOf(j);
            double y = landform(x, z);
            const double rk = std::hypot(x - knoll_x, z - knoll_z);
            const double on_knoll = smoothstep(knoll_r + 0.6, knoll_r - 0.4, rk);
            y += (std::max(y, knoll_top) - y) * on_knoll;
            outcrop[g.at(i, j)] = smoothstep(knoll_r + 0.9, knoll_r, rk);
            surface[g.at(i, j)] = y;
        }

    // ---- drainage decides where the river runs.
    const Clock::time_point t_drain = Clock::now();
    std::vector<std::size_t> mouth;
    const double mouth_z = centre(g.xOf(g.nx - 1));
    for (int j = 0; j < g.nz; ++j)
        if (std::abs(g.zOf(j) - mouth_z) < 2.5) mouth.push_back(g.at(g.nx - 1, j));
    int source_j = 0;
    double lowest = std::numeric_limits<double>::infinity();
    const double source_z = centre(g.x0);
    for (int j = 0; j < g.nz; ++j)
        if (std::abs(g.zOf(j) - source_z) < 2.0 && surface[g.at(0, j)] < lowest) {
            lowest = surface[g.at(0, j)];
            source_j = j;
        }
    Drainage drainage = priorityFlood(g, surface, mouth);
    const std::size_t source = g.at(0, source_j);
    std::vector<std::size_t> path;
    for (std::size_t c = source; c != kNone && path.size() < n; c = drainage.down[c]) path.push_back(c);

    // The channel, carved along that route: a flat bed with sloping banks, the
    // shape a stream wears into loose ground.
    const double channel_r = 1.6, channel_flat = 0.8, channel_depth = 0.55;
    std::vector<double> carve(n, 0.0), from_path(n, std::numeric_limits<double>::infinity());
    const int reach = static_cast<int>(std::ceil(std::max(channel_r, 6.0) / g.dx));
    for (const std::size_t c : path) {
        const int ci = static_cast<int>(c % static_cast<std::size_t>(g.nx));
        const int cj = static_cast<int>(c / static_cast<std::size_t>(g.nx));
        for (int j = cj - reach; j <= cj + reach; ++j)
            for (int i = ci - reach; i <= ci + reach; ++i) {
                if (i < 0 || j < 0 || i >= g.nx || j >= g.nz) continue;
                const double dist = std::hypot((i - ci) * g.dx, (j - cj) * g.dx);
                const std::size_t k = g.at(i, j);
                from_path[k] = std::min(from_path[k], dist);
            }
    }
    for (std::size_t c = 0; c < n; ++c)
        if (from_path[c] < channel_r)
            carve[c] = channel_depth * (1.0 - smoothstep(channel_flat, channel_r, from_path[c]));
    // Layers: soil over rock everywhere, thinned later where it is steep.
    land.rock.resize(n);
    land.soil.assign(n, 1.2);
    land.sand.assign(n, 0.0);
    land.loose.assign(n, 0.0);
    for (std::size_t c = 0; c < n; ++c) {
        land.rock[c] = surface[c] - 1.2;
        land.soil[c] -= carve[c];
        land.report.carved_m3 += carve[c] * g.dx * g.dx;
    }
    land.report.drainage_ms = msSince(t_drain);

    // ---- a limited erosion pass.
    const Clock::time_point t_erode = Clock::now();
    const std::vector<std::size_t> sources{source};
    const ErosionResult eroded = erode(g, land.rock, land.soil, land.sand, land.loose, sources,
                                       p.discharge_m3_s, mouth, p.erosion_iterations);
    land.report.eroded_m3 = eroded.eroded_m3;
    land.report.deposited_m3 = eroded.deposited_m3;
    land.report.erosion_ms = msSince(t_erode);

    // ---- depressions after it all: ponds kept, pits filled.
    std::vector<double> ground(n);
    for (std::size_t c = 0; c < n; ++c) ground[c] = land.rock[c] + land.soil[c] + land.sand[c] + land.loose[c];
    drainage = priorityFlood(g, ground, mouth);
    const std::vector<Depression> hollows = depressions(g, ground, drainage.filled);
    land.depth.assign(n, 0.0);
    int lake_number = 0;
    const auto touchesEdge = [&](const Depression &d) {
        for (const std::size_t c : d.cells) {
            const int i = static_cast<int>(c % static_cast<std::size_t>(g.nx));
            const int j = static_cast<int>(c / static_cast<std::size_t>(g.nx));
            if (i == 0 || j == 0 || i == g.nx - 1 || j == g.nz - 1) return true;
        }
        return false;
    };
    for (const Depression &d : hollows) {
        ++land.report.depressions;
        // A hollow cut off by the edge of the world is where the world ends,
        // not a pond: it is filled like any pit.
        if (d.deepest >= 0.25 && d.area >= 3.0 && !touchesEdge(d)) {
            Lake lake;
            lake.name = ++lake_number == 1 ? "the pond" : "pond " + std::to_string(lake_number);
            lake.surface_m = d.level;
            lake.area_m2 = d.area;
            lake.volume_m3 = d.volume;
            lake.deepest_m = d.deepest;
            lake.x_m = d.x;
            lake.z_m = d.z;
            for (const std::size_t c : d.cells) land.depth[c] = drainage.filled[c] - ground[c];
            land.lakes.push_back(lake);
            ++land.report.lakes;
        } else {
            for (const std::size_t c : d.cells) {
                const double fill = drainage.filled[c] - ground[c];
                land.sand[c] += fill;
                land.report.pits_filled_m3 += fill * g.dx * g.dx;
            }
            ++land.report.pits_filled;
        }
    }

    // ---- soil thinned where it is steep, rock bare on the knoll, sand along
    // the water. The surface does not move: what changes is what it is made of.
    land.moisture.assign(n, 0.0F);
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < g.nx; ++i) {
            const std::size_t c = g.at(i, j);
            const int i0 = std::max(0, i - 1), i1 = std::min(g.nx - 1, i + 1);
            const int j0 = std::max(0, j - 1), j1 = std::min(g.nz - 1, j + 1);
            const double gx = (ground[g.at(i1, j)] - ground[g.at(i0, j)]) / ((i1 - i0) * g.dx);
            const double gz = (ground[g.at(i, j1)] - ground[g.at(i, j0)]) / ((j1 - j0) * g.dx);
            const double steep = std::hypot(gx, gz);
            // A pond's basin holds the silt and soil that settled in it, steep
            // or not: its sides are not a rock face.
            const double in_pond = smoothstep(pond_r + 1.2, pond_r + 0.6,
                                              std::hypot(g.xOf(i) - pond_x, g.zOf(j) - pond_z));
            const double keep = std::max(std::clamp(1.0 - steep / 0.75, 0.0, 1.0), in_pond) *
                                (1.0 - outcrop[c]);
            // The surface as it now stands -- pits filled and all -- which this
            // pass does not move.
            const double top = land.rock[c] + land.soil[c] + land.sand[c] + land.loose[c];
            const double soil = std::min(land.soil[c], 1.2 * keep);
            // Alluvium: the river's banks and bed are sand.
            const double alluvium = std::min(soil, 0.35 * std::exp(-(from_path[c] / 2.2) * (from_path[c] / 2.2)));
            land.soil[c] = soil - alluvium;
            land.sand[c] += alluvium;
            if (outcrop[c] > 0.5) { land.sand[c] = 0.0; land.loose[c] = 0.0; }
            land.rock[c] = top - land.soil[c] - land.sand[c] - land.loose[c];
            const double wetness = std::exp(-from_path[c] / 4.0);
            land.moisture[c] = static_cast<float>(std::clamp(land.depth[c] > 0.0 ? 1.0 : wetness, 0.0, 1.0));
        }

    // ---- the river: in where the drainage starts, out at the mouth.
    int in_from = source_j, in_to = source_j;
    while (in_from > 0 && std::abs(g.zOf(in_from - 1) - g.zOf(source_j)) < 0.9) --in_from;
    while (in_to + 1 < g.nz && std::abs(g.zOf(in_to + 1) - g.zOf(source_j)) < 0.9) ++in_to;
    land.inflows.push_back({"the river", water::Edge::West, in_from, in_to, p.discharge_m3_s});
    int out_from = g.nz, out_to = -1;
    for (const std::size_t m : mouth) {
        const int j = static_cast<int>(m / static_cast<std::size_t>(g.nx));
        out_from = std::min(out_from, j);
        out_to = std::max(out_to, j);
    }
    land.outflows.push_back({"the river's mouth", water::Edge::East, out_from, out_to});
    land.qx.assign(n, 0.0);
    land.qz.assign(n, 0.0);
    settleRiver(land, p.spinup_limit_s);

    // Somebody arriving stands on the south slope and looks across the river.
    const double view_x = g.x0 + 0.5 * length;
    setView(land, view_x - 2.0, centre(view_x - 2.0) - (floodplain + 5.0), view_x + 3.0,
            centre(view_x + 3.0), 0.2);
    land.report.total_ms = msSince(t0);
    return land;
}

// ---- simple landscapes ------------------------------------------------------

namespace {
Landscape simple(const SimpleParameters &p, const char *kind) {
    if (p.nx < 4 || p.nz < 4 || p.nx > 1024 || p.nz > 1024 || !(p.cell_m > 0.0))
        throw std::invalid_argument("a landscape is 4 to 1024 cells each way");
    Landscape land;
    land.kind = kind;
    land.grid = {p.nx, p.nz, p.cell_m, -0.5 * (p.nx - 1) * p.cell_m, -0.5 * (p.nz - 1) * p.cell_m};
    const std::size_t n = land.grid.cells();
    land.rock.assign(n, 0.0);
    land.soil.assign(n, std::max(0.0, p.soil_m));
    land.sand.assign(n, std::max(0.0, p.sand_m));
    land.loose.assign(n, 0.0);
    land.moisture.assign(n, 0.0F);
    land.depth.assign(n, 0.0);
    land.qx.assign(n, 0.0);
    land.qz.assign(n, 0.0);
    return land;
}
} // namespace

Landscape basin(const SimpleParameters &p) {
    Landscape land = simple(p, "basin");
    const Grid &g = land.grid;
    const double half = 0.5 * std::min(g.nx - 1, g.nz - 1) * g.dx;
    double area = 0.0, volume = 0.0, deepest = 0.0;
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < g.nx; ++i) {
            const std::size_t c = g.at(i, j);
            const double x = g.xOf(i), z = g.zOf(j);
            const double r = std::hypot(x, z) / half;
            // A bowl rising to the rim everywhere, so the lake cannot leave.
            const double top = 0.2 + 1.6 * r * r + 0.03 * std::sin(2.1 * x) * std::cos(1.7 * z);
            land.rock[c] = top - land.soil[c] - land.sand[c];
            const double depth = std::max(0.0, p.lake_level_m - top);
            land.depth[c] = depth;
            if (depth > 0.0) {
                area += g.dx * g.dx;
                volume += depth * g.dx * g.dx;
                deepest = std::max(deepest, depth);
            }
            land.moisture[c] = depth > 0.0 ? 1.0F : 0.2F;
        }
    land.lakes.push_back({"the lake", p.lake_level_m, area, volume, deepest, 0.0, 0.0});
    setView(land, 0.0, g.z0 + 1.0, 0.0, 0.0, 0.0);
    return land;
}

Landscape channel(const SimpleParameters &p) {
    Landscape land = simple(p, "channel");
    const Grid &g = land.grid;
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < g.nx; ++i) {
            const std::size_t c = g.at(i, j);
            const double z = g.zOf(j);
            // Two percent down the channel, and banks either side of it.
            const double top = 1.0 - 0.02 * (g.xOf(i) - g.x0) + 0.35 * std::abs(z);
            land.rock[c] = top - land.soil[c] - land.sand[c];
            land.moisture[c] = std::abs(z) < 1.0 ? 1.0F : 0.3F;
        }
    const int middle = g.nz / 2;
    const int half = std::max(1, g.nz / 5);
    land.inflows.push_back({"the stream", water::Edge::West, middle - half, middle + half, p.discharge_m3_s});
    land.outflows.push_back({"the stream's end", water::Edge::East, 0, g.nz - 1});
    settleRiver(land, 240.0);
    setView(land, g.x0 + 2.0, g.z0 + 0.5, 0.0, 0.0, 0.0);
    return land;
}

Landscape flatGround(const SimpleParameters &p) {
    Landscape land = simple(p, "flat");
    setView(land, 0.0, land.grid.z0 + 1.0, 0.0, 0.0, 0.0);
    return land;
}

// ---- the cache -------------------------------------------------------------

std::string cacheFileName(const ValleyParameters &p) {
    char name[160];
    const std::uint64_t key =
        mix(p.seed ^ mix(static_cast<std::uint64_t>(p.chunks_x) * 131ULL + static_cast<std::uint64_t>(p.chunks_z)) ^
            mix(static_cast<std::uint64_t>(std::llround(p.cell_m * 1e6))) ^
            mix(static_cast<std::uint64_t>(std::llround(p.discharge_m3_s * 1e6)) * 7ULL) ^
            mix(static_cast<std::uint64_t>(p.erosion_iterations) * 13ULL) ^
            mix(static_cast<std::uint64_t>(std::llround(p.spinup_limit_s)) * 17ULL));
    std::snprintf(name, sizeof name, "valley-g%d-%016llx.terrain", kGeneratorVersion,
                  static_cast<unsigned long long>(key));
    return name;
}

namespace {
constexpr char kMagic[8] = {'B', 'A', 'N', 'J', 'O', 'T', 'R', 'N'};

template <typename T> void put(std::ofstream &out, const T &value) {
    out.write(reinterpret_cast<const char *>(&value), sizeof value);
}
template <typename T> bool take(std::ifstream &in, T &value) {
    in.read(reinterpret_cast<char *>(&value), sizeof value);
    return static_cast<bool>(in);
}
void putString(std::ofstream &out, const std::string &s) {
    const std::uint32_t size = static_cast<std::uint32_t>(s.size());
    put(out, size);
    out.write(s.data(), static_cast<std::streamsize>(size));
}
bool takeString(std::ifstream &in, std::string &s) {
    std::uint32_t size = 0;
    if (!take(in, size) || size > 4096) return false;
    s.resize(size);
    in.read(s.data(), static_cast<std::streamsize>(size));
    return static_cast<bool>(in);
}
// The report, number by number: it holds a path, which is not bytes to copy.
void putReport(std::ofstream &out, const GenerationReport &r) {
    for (const double v : {r.total_ms, r.drainage_ms, r.erosion_ms, r.river_ms, r.pits_filled_m3,
                           r.carved_m3, r.eroded_m3, r.deposited_m3, r.river_time_s, r.river_in_m3_s,
                           r.river_out_m3_s, r.river_volume_m3})
        put(out, v);
    for (const int v : {r.depressions, r.lakes, r.pits_filled}) put(out, static_cast<std::int32_t>(v));
}
bool takeReport(std::ifstream &in, GenerationReport &r) {
    for (double *v : {&r.total_ms, &r.drainage_ms, &r.erosion_ms, &r.river_ms, &r.pits_filled_m3,
                      &r.carved_m3, &r.eroded_m3, &r.deposited_m3, &r.river_time_s, &r.river_in_m3_s,
                      &r.river_out_m3_s, &r.river_volume_m3})
        if (!take(in, *v)) return false;
    for (int *v : {&r.depressions, &r.lakes, &r.pits_filled}) {
        std::int32_t value = 0;
        if (!take(in, value)) return false;
        *v = value;
    }
    return true;
}
template <typename T> void putVector(std::ofstream &out, const std::vector<T> &v) {
    const std::uint64_t size = v.size();
    put(out, size);
    out.write(reinterpret_cast<const char *>(v.data()), static_cast<std::streamsize>(size * sizeof(T)));
}
template <typename T> bool takeVector(std::ifstream &in, std::vector<T> &v, std::size_t expected) {
    std::uint64_t size = 0;
    if (!take(in, size) || size != expected) return false;
    v.resize(expected);
    in.read(reinterpret_cast<char *>(v.data()), static_cast<std::streamsize>(expected * sizeof(T)));
    return static_cast<bool>(in);
}
} // namespace

bool saveLandscape(const Landscape &land, const std::string &path) {
    namespace fs = std::filesystem;
    std::error_code error;
    fs::create_directories(fs::path(path).parent_path(), error);
    // Written aside and moved into place, so another process opening the same
    // valley at the same moment reads a whole file or none.
    const std::string partial = path + ".part" + std::to_string(mix(static_cast<std::uint64_t>(
                                    Clock::now().time_since_epoch().count())) % 100000);
    {
        std::ofstream out(partial, std::ios::binary);
        if (!out) return false;
        out.write(kMagic, sizeof kMagic);
        put(out, static_cast<std::int32_t>(kGeneratorVersion));
        putString(out, land.kind);
        put(out, land.grid.nx); put(out, land.grid.nz);
        put(out, land.grid.dx); put(out, land.grid.x0); put(out, land.grid.z0);
        putVector(out, land.rock); putVector(out, land.soil); putVector(out, land.sand);
        putVector(out, land.loose); putVector(out, land.moisture);
        putVector(out, land.depth); putVector(out, land.qx); putVector(out, land.qz);
        put(out, static_cast<std::uint32_t>(land.inflows.size()));
        for (const auto &in : land.inflows) {
            putString(out, in.name); put(out, static_cast<std::uint8_t>(in.edge));
            put(out, in.from); put(out, in.to); put(out, in.discharge_m3_s);
        }
        put(out, static_cast<std::uint32_t>(land.outflows.size()));
        for (const auto &o : land.outflows) {
            putString(out, o.name); put(out, static_cast<std::uint8_t>(o.edge));
            put(out, o.from); put(out, o.to);
        }
        put(out, static_cast<std::uint32_t>(land.lakes.size()));
        for (const auto &l : land.lakes) {
            putString(out, l.name); put(out, l.surface_m); put(out, l.area_m2);
            put(out, l.volume_m3); put(out, l.deepest_m); put(out, l.x_m); put(out, l.z_m);
        }
        putReport(out, land.report);
        for (double v : land.eye_m) put(out, v);
        for (double v : land.look_m) put(out, v);
        if (!out) return false;
    }
    fs::rename(partial, path, error);
    if (error) {
        fs::remove(partial, error);
        return fs::exists(path);
    }
    return true;
}

std::optional<Landscape> loadLandscape(const std::string &path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return std::nullopt;
    char magic[8];
    in.read(magic, sizeof magic);
    if (!in || std::memcmp(magic, kMagic, sizeof magic) != 0) return std::nullopt;
    std::int32_t version = 0;
    if (!take(in, version) || version != kGeneratorVersion) return std::nullopt;
    Landscape land;
    if (!takeString(in, land.kind)) return std::nullopt;
    if (!take(in, land.grid.nx) || !take(in, land.grid.nz) || !take(in, land.grid.dx) ||
        !take(in, land.grid.x0) || !take(in, land.grid.z0))
        return std::nullopt;
    if (land.grid.nx < 2 || land.grid.nz < 2 || land.grid.nx > 4096 || land.grid.nz > 4096) return std::nullopt;
    const std::size_t n = land.grid.cells();
    if (!takeVector(in, land.rock, n) || !takeVector(in, land.soil, n) || !takeVector(in, land.sand, n) ||
        !takeVector(in, land.loose, n) || !takeVector(in, land.moisture, n) ||
        !takeVector(in, land.depth, n) || !takeVector(in, land.qx, n) || !takeVector(in, land.qz, n))
        return std::nullopt;
    std::uint32_t count = 0;
    if (!take(in, count) || count > 64) return std::nullopt;
    for (std::uint32_t k = 0; k < count; ++k) {
        water::Inflow i;
        std::uint8_t edge = 0;
        if (!takeString(in, i.name) || !take(in, edge) || !take(in, i.from) || !take(in, i.to) ||
            !take(in, i.discharge_m3_s))
            return std::nullopt;
        i.edge = static_cast<water::Edge>(edge);
        land.inflows.push_back(i);
    }
    if (!take(in, count) || count > 64) return std::nullopt;
    for (std::uint32_t k = 0; k < count; ++k) {
        water::Outflow o;
        std::uint8_t edge = 0;
        if (!takeString(in, o.name) || !take(in, edge) || !take(in, o.from) || !take(in, o.to))
            return std::nullopt;
        o.edge = static_cast<water::Edge>(edge);
        land.outflows.push_back(o);
    }
    if (!take(in, count) || count > 64) return std::nullopt;
    for (std::uint32_t k = 0; k < count; ++k) {
        Lake l;
        if (!takeString(in, l.name) || !take(in, l.surface_m) || !take(in, l.area_m2) ||
            !take(in, l.volume_m3) || !take(in, l.deepest_m) || !take(in, l.x_m) || !take(in, l.z_m))
            return std::nullopt;
        land.lakes.push_back(l);
    }
    if (!takeReport(in, land.report)) return std::nullopt;
    for (double &v : land.eye_m) if (!take(in, v)) return std::nullopt;
    for (double &v : land.look_m) if (!take(in, v)) return std::nullopt;
    return land;
}

namespace {
std::string environmentVariable(const char *name) {
#if defined(_MSC_VER)
    char *value = nullptr;
    std::size_t size = 0;
    std::string out;
    if (_dupenv_s(&value, &size, name) == 0 && value != nullptr) out = value;
    std::free(value);
    return out;
#else
    const char *value = std::getenv(name);
    return value != nullptr ? std::string(value) : std::string();
#endif
}
} // namespace

Landscape valley(const ValleyParameters &p, const std::string &directory) {
    namespace fs = std::filesystem;
    fs::path folder = directory;
    if (folder.empty()) {
        const std::string configured = environmentVariable("BANJO_TERRAIN_CACHE");
        folder = configured.empty() ? fs::temp_directory_path() / "banjo-terrain-cache"
                                    : fs::path(configured);
    }
    const fs::path path = folder / cacheFileName(p);
    if (std::optional<Landscape> cached = loadLandscape(path.string())) {
        cached->report.from_cache = true;
        cached->report.cache_path = path.string();
        return std::move(*cached);
    }
    Landscape made = generateValley(p);
    made.report.cache_path = path.string();
    (void)saveLandscape(made, path.string());
    return made;
}

} // namespace banjo::terrain
