// The ground beyond the valley: regions streamed in as somebody nears an edge.
//
// See docs/streamed-regions.md. A region is a TerrainField the valley's size,
// made from the seed and its place on the lattice (streamedRegion), with one
// column-surface collider per chunk like the valley's. Its columns tile the
// valley's -- region (1, 0) starts one cell past the valley's last column --
// so every column of the world belongs to exactly one field, and a column at
// a field's edge looks for its neighbour in the field beside it: the walls at
// a seam are the walls one big field would have had there.
//
// What a region does not have yet: water (the valley's water stays in the
// valley), slumping across a seam (each field settles on its own), and a
// smooth or cut surface (only the column surface tiles without a gap).
#include "terrain/Environment.hpp"

#include "material/Material.hpp"
#include "rigid/JoltWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace banjo::terrain {
namespace {

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

double msSince(Clock::time_point t0) {
    return std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
}

// The same strides the valley's ground keeps (Environment.cpp).
constexpr double kGroundStrideS = 1.0 / 60.0;
constexpr double kRebuildStrideS = 0.05;

Json volumesJson(const Volumes &v) {
    return {{"rock_m3", v.rock_m3}, {"soil_m3", v.soil_m3}, {"sand_m3", v.sand_m3}};
}

Volumes volumesFrom(const Json &v) {
    return {v.at("rock_m3").get<double>(), v.at("soil_m3").get<double>(), v.at("sand_m3").get<double>()};
}

template <typename T> std::string packed(const std::vector<T> &v) {
    return encodeBase64(v.data(), v.size() * sizeof(T));
}

template <typename T> void unpack(const Json &node, const char *key, std::vector<T> &into, std::size_t count) {
    const std::vector<std::uint8_t> bytes = decodeBase64(node.at(key).get<std::string>());
    if (bytes.size() != count * sizeof(T)) throw std::invalid_argument(std::string("a saved region's ") + key +
                                                                       " is the wrong size");
    into.resize(count);
    std::memcpy(into.data(), bytes.data(), bytes.size());
}

// Grow a rectangle of points to hold (i, j).
void grow(TerrainField::Rect &r, int i, int j) {
    if (r.ni == 0) { r = {i, j, 1, 1}; return; }
    const int i1 = std::max(r.i0 + r.ni - 1, i), j1 = std::max(r.j0 + r.nj - 1, j);
    r.i0 = std::min(r.i0, i);
    r.j0 = std::min(r.j0, j);
    r.ni = i1 - r.i0 + 1;
    r.nj = j1 - r.j0 + 1;
}

} // namespace

// ---- where things are ----------------------------------------------------------

bool Environment::canStream(std::string *why) const {
    const auto refuse = [&](const char *reason) {
        if (why != nullptr) *why = reason;
        return false;
    };
    if (landscape_.kind != "valley") return refuse("only a generated valley grows");
    if (!terrain_->columnSurface())
        return refuse("only ground in columns grows: a smooth or cut surface would leave a gap a cell wide "
                      "at every seam");
    if (why != nullptr) why->clear();
    return true;
}

std::pair<int, int> Environment::latticeOf(double x, double z) const {
    const Grid &v = landscape_.grid;
    // A column owns the half cell either side of its point.
    const double across_x = v.nx * v.dx, across_z = v.nz * v.dx;
    return {static_cast<int>(std::floor((x - (v.x0 - 0.5 * v.dx)) / across_x)),
            static_cast<int>(std::floor((z - (v.z0 - 0.5 * v.dx)) / across_z))};
}

int Environment::regionIndex(int rx, int rz) const {
    if (rx == 0 && rz == 0) return -1;
    const auto found = region_at_.find({rx, rz});
    return found == region_at_.end() ? -2 : found->second;
}

int Environment::regionAt(double x, double z) const {
    if (!std::isfinite(x) || !std::isfinite(z)) return -2;
    if (regions_.empty()) return terrain_->cellAt(x, z) ? -1 : -2;
    const auto [rx, rz] = latticeOf(x, z);
    const int k = regionIndex(rx, rz);
    if (k == -1 && !terrain_->cellAt(x, z)) return -2;
    return k;
}

const TerrainField &Environment::fieldAt(double x, double z) const {
    const int k = regions_.empty() ? -1 : regionAt(x, z);
    return k >= 0 ? *regions_[static_cast<std::size_t>(k)]->field : *terrain_;
}

std::vector<int> Environment::fieldsTouching(double x_lo, double z_lo, double x_hi, double z_hi) const {
    std::vector<int> out;
    if (regions_.empty()) return {-1};
    const auto [ax, az] = latticeOf(x_lo, z_lo);
    const auto [bx, bz] = latticeOf(x_hi, z_hi);
    // A dig is never more than tens of metres; a rectangle that claims to reach
    // across the whole lattice is clipped to it.
    for (int rz = std::max(az, -kMostRegionsOut); rz <= std::min(bz, kMostRegionsOut); ++rz)
        for (int rx = std::max(ax, -kMostRegionsOut); rx <= std::min(bx, kMostRegionsOut); ++rx) {
            const int k = regionIndex(rx, rz);
            if (k == -1) out.insert(out.begin(), -1);
            else if (k >= 0) out.push_back(k);
        }
    return out;
}

// ---- growing --------------------------------------------------------------------

std::vector<Environment::Grown> Environment::growToward(JoltWorld *world, double x, double z, double within_m) {
    std::vector<Grown> out;
    if (!streaming_ || !std::isfinite(x) || !std::isfinite(z) || !(within_m >= 0.0)) return out;
    // Only from ground there is: somebody off the edge of the world, or a
    // camera flown out over nothing, does not make the world under them.
    if (regionAt(x, z) == -2) return out;
    const Grid &v = landscape_.grid;
    const auto [cx, cz] = latticeOf(x, z);
    for (int dz = -1; dz <= 1; ++dz)
        for (int dx = -1; dx <= 1; ++dx) {
            const int rx = cx + dx, rz = cz + dz;
            if ((dx == 0 && dz == 0) || regionIndex(rx, rz) != -2) continue;
            const double x_lo = v.x0 - 0.5 * v.dx + rx * v.nx * v.dx, x_hi = x_lo + v.nx * v.dx;
            const double z_lo = v.z0 - 0.5 * v.dx + rz * v.nz * v.dx, z_hi = z_lo + v.nz * v.dx;
            const double away = std::hypot(std::max({0.0, x_lo - x, x - x_hi}), std::max({0.0, z_lo - z, z - z_hi}));
            if (away > within_m) continue;
            Grown grown;
            if (addRegion(world, rx, rz, &grown)) out.push_back(grown);
        }
    return out;
}

bool Environment::addRegion(JoltWorld *world, int rx, int rz, Grown *grown) {
    if (!canStream() || (rx == 0 && rz == 0) || regionIndex(rx, rz) != -2) return false;
    if (std::abs(rx) > kMostRegionsOut || std::abs(rz) > kMostRegionsOut ||
        regions_.size() >= static_cast<std::size_t>(kMostRegions))
        return false;
    const Clock::time_point t0 = Clock::now();
    Landscape land = streamedRegion(landscape_, seed_, rx, rz);
    auto region = std::make_unique<StreamedRegion>();
    region->rx = rx;
    region->rz = rz;
    region->field = std::make_unique<TerrainField>(land.grid, std::move(land.beds), std::move(land.soil),
                                                   std::move(land.sand), std::move(land.loose),
                                                   std::move(land.moisture));
    region->field->setColumnSurface(true);
    region->field->resetLedger();
    const int k = static_cast<int>(regions_.size());
    const int chunks = region->field->chunksX() * region->field->chunksZ();
    region->colliders.resize(static_cast<std::size_t>(chunks));
    region->patches.assign(static_cast<std::size_t>(chunks), 0);
    regions_.push_back(std::move(region));
    region_at_[{rx, rz}] = k;
    StreamedRegion &r = *regions_.back();
    for (int chunk = 0; chunk < chunks; ++chunk)
        r.colliders[static_cast<std::size_t>(chunk)] = chunkHeightsOf(k, chunk);
    r.generate_ms = msSince(t0);
    Grown g{rx, rz, r.generate_ms, 0.0, 0.0, 0};
    if (world != nullptr && attached_) {
        attachRegion(*world, k);
        g.colliders_ms = r.colliders_ms;
        // The fields beside it had walls down to the floor along this edge,
        // facing nothing. They face this region now: rebuilt to meet it.
        const Clock::time_point ts = Clock::now();
        const Grid &rg = r.field->grid();
        std::vector<std::size_t> edge;
        for (int i = 0; i < rg.nx; ++i) {
            edge.push_back(rg.at(i, 0));
            edge.push_back(rg.at(i, rg.nz - 1));
        }
        for (int j = 1; j + 1 < rg.nz; ++j) {
            edge.push_back(rg.at(0, j));
            edge.push_back(rg.at(rg.nx - 1, j));
        }
        g.seam_chunks = seamChunks(k, edge).size();
        rebuildSeams(*world, k, edge, nullptr);
        g.seams_ms = msSince(ts);
    }
    regions_added_.push_back(k);
    if (grown != nullptr) *grown = g;
    return true;
}

void Environment::attachRegion(JoltWorld &world, int k) {
    const Clock::time_point t0 = Clock::now();
    StreamedRegion &r = *regions_[static_cast<std::size_t>(k)];
    const MaterialDefinition contact = groundContactMaterial();
    for (std::size_t chunk = 0; chunk < r.patches.size(); ++chunk)
        r.patches[chunk] = world.addGroundTriangles(columnTrianglesOf(k, static_cast<int>(chunk)), contact);
    (void)r.field->takeDirtyChunks();
    r.colliders_ms = msSince(t0);
}

// ---- colliders --------------------------------------------------------------------

std::vector<float> Environment::chunkHeightsOf(int which, int chunk) const {
    const TerrainField &field = fieldOf(which);
    const Grid &g = field.grid();
    const int cx = chunk % field.chunksX(), cz = chunk / field.chunksX();
    const int i0 = cx * TerrainField::kChunkCells, j0 = cz * TerrainField::kChunkCells;
    constexpr int kCount = TerrainField::kChunkCells + 1;
    std::vector<float> heights(static_cast<std::size_t>(kCount) * kCount, std::numeric_limits<float>::quiet_NaN());
    for (int jj = 0; jj < kCount; ++jj)
        for (int ii = 0; ii < kCount; ++ii) {
            const int i = i0 + ii, j = j0 + jj;
            if (i >= g.nx || j >= g.nz) continue;
            heights[static_cast<std::size_t>(jj) * kCount + static_cast<std::size_t>(ii)] =
                static_cast<float>(field.height(g.at(i, j)));
        }
    return heights;
}

void Environment::solidsAt(int which, int i, int j, std::vector<std::pair<double, double>> &out) const {
    out.clear();
    const TerrainField *field = &fieldOf(which);
    const Grid *g = &field->grid();
    if (i < 0 || j < 0 || i >= g->nx || j >= g->nz) {
        // Past this field's edge: the field beside it, if there is one. Every
        // field is the valley's size, so the column is the same distance in.
        if (regions_.empty()) return;
        const int di = i < 0 ? -1 : i >= g->nx ? 1 : 0;
        const int dj = j < 0 ? -1 : j >= g->nz ? 1 : 0;
        const int rx = which < 0 ? 0 : regions_[static_cast<std::size_t>(which)]->rx;
        const int rz = which < 0 ? 0 : regions_[static_cast<std::size_t>(which)]->rz;
        const int other = regionIndex(rx + di, rz + dj);
        if (other == -2) return;
        which = other;
        i -= di * g->nx;
        j -= dj * g->nz;
        field = &fieldOf(which);
        g = &field->grid();
        if (i < 0 || j < 0 || i >= g->nx || j >= g->nz) return;
    }
    // The top as last built into the collider, so a wall is made against the
    // ground its neighbour's collider stands at, not ground still settling.
    const std::vector<std::vector<float>> &colliders =
        which < 0 ? collider_heights_ : regions_[static_cast<std::size_t>(which)]->colliders;
    double top = field->height(g->at(i, j));
    if (!colliders.empty()) {
        const int cx = std::min(i / TerrainField::kChunkCells, field->chunksX() - 1);
        const int cz = std::min(j / TerrainField::kChunkCells, field->chunksZ() - 1);
        const std::vector<float> &chunk = colliders[static_cast<std::size_t>(cz * field->chunksX() + cx)];
        if (!chunk.empty())
            top = chunk[static_cast<std::size_t>((j - cz * TerrainField::kChunkCells) * (TerrainField::kChunkCells + 1) +
                                                 i - cx * TerrainField::kChunkCells)];
    }
    Run runs[TerrainField::kRunsMost];
    const int count = field->runsOf(g->at(i, j), runs);
    double lo = field->floor();
    for (int k = 0; k < count; ++k) {
        const double hi = k == count - 1 ? top : std::min(top, runs[k].top_m);
        if (!isVoid(runs[k].kind) && hi - lo > 1e-7) {
            if (!out.empty() && std::abs(out.back().second - lo) < 1e-7) out.back().second = hi;
            else out.emplace_back(lo, hi);
        }
        lo = hi;
        if (lo >= top) break;
    }
}

// Boundary of the union of actual layered columns. Saved float32 collider
// heights bound the tops; void floors/roofs and exposed walls stay open. Each
// column owns its outward faces, so chunks -- and fields -- share neither a
// wall nor a top.
std::vector<std::array<Vec3, 3>> Environment::columnTrianglesOf(int which, int chunk) const {
    const TerrainField &field = fieldOf(which);
    const Grid &g = field.grid();
    using Interval = std::pair<double, double>;
    std::vector<std::array<Vec3, 3>> out;
    const auto quad = [&](Vec3 a, Vec3 b, Vec3 c, Vec3 d, bool reverse = false) {
        if (reverse) { out.push_back({a, c, b}); out.push_back({a, d, c}); }
        else { out.push_back({a, b, c}); out.push_back({a, c, d}); }
    };
    const int cx = chunk % field.chunksX(), cz = chunk / field.chunksX();
    const int i0 = cx * TerrainField::kChunkCells, j0 = cz * TerrainField::kChunkCells;
    const int i1 = cx + 1 == field.chunksX() ? g.nx : i0 + TerrainField::kChunkCells;
    const int j1 = cz + 1 == field.chunksZ() ? g.nz : j0 + TerrainField::kChunkCells;
    std::vector<Interval> own, neighbor;
    for (int j = j0; j < j1; ++j)
        for (int i = i0; i < i1; ++i) {
            solidsAt(which, i, j, own);
            const double x = g.xOf(i) - g.dx / 2, z = g.zOf(j) - g.dx / 2;
            for (const auto &[lo, hi] : own) {
                quad({x, hi, z}, {x, hi, z + g.dx}, {x + g.dx, hi, z + g.dx}, {x + g.dx, hi, z});
                if (lo > field.floor() + 1e-7)
                    quad({x, lo, z}, {x, lo, z + g.dx}, {x + g.dx, lo, z + g.dx}, {x + g.dx, lo, z}, true);
            }
            for (int side = 0; side < 4; ++side) {
                const int di = side == 0 ? -1 : side == 1 ? 1 : 0, dj = side == 2 ? -1 : side == 3 ? 1 : 0;
                solidsAt(which, i + di, j + dj, neighbor);
                for (const auto &[lo, hi] : own) {
                    double from = lo;
                    const auto wall = [&](double a, double b) {
                        if (b - a <= 1e-7) return;
                        if (di) {
                            const double at = x + (di > 0 ? g.dx : 0);
                            quad({at, a, z}, {at, b, z}, {at, b, z + g.dx}, {at, a, z + g.dx}, di < 0);
                        } else {
                            const double at = z + (dj > 0 ? g.dx : 0);
                            quad({x, a, at}, {x + g.dx, a, at}, {x + g.dx, b, at}, {x, b, at}, dj < 0);
                        }
                    };
                    for (const auto &[nlo, nhi] : neighbor) {
                        if (nhi <= from || nlo >= hi) continue;
                        wall(from, std::min(hi, nlo));
                        from = std::max(from, std::min(hi, nhi));
                    }
                    wall(from, hi);
                }
            }
        }
    return out;
}

void Environment::rebuildRegionChunks(JoltWorld &world, int k, const std::set<int> &chunks, EditEffect *effect) {
    if (!attached_ || chunks.empty()) return;
    const Clock::time_point t0 = Clock::now();
    StreamedRegion &r = *regions_[static_cast<std::size_t>(k)];
    // Every changed chunk's heights first, then their meshes: neighbouring
    // chunks' walls are made against each other's new tops.
    for (const int chunk : chunks) r.colliders[static_cast<std::size_t>(chunk)] = chunkHeightsOf(k, chunk);
    for (const int chunk : chunks) {
        const unsigned patch = r.patches[static_cast<std::size_t>(chunk)];
        if (patch == 0) continue;
        world.replaceGroundTriangles(patch, columnTrianglesOf(k, chunk));
        ++stats_.chunks_rebuilt;
    }
    unsigned woken = 0;
    const TerrainField::Rect w = r.pending_wake;
    if (w.ni > 0) {
        const Grid &g = r.field->grid();
        double low = std::numeric_limits<double>::infinity(), high = -low;
        for (int j = w.j0; j < w.j0 + w.nj; ++j)
            for (int i = w.i0; i < w.i0 + w.ni; ++i) {
                const double h = r.field->height(g.at(i, j));
                low = std::min(low, h);
                high = std::max(high, h);
            }
        const double margin = 0.6;
        woken = world.wakeBodiesIn({g.xOf(w.i0) - margin, low - 1.0, g.zOf(w.j0) - margin},
                                   {g.xOf(w.i0 + w.ni - 1) + margin, high + 4.0, g.zOf(w.j0 + w.nj - 1) + margin});
        r.pending_wake = {};
    }
    const double ms = msSince(t0);
    stats_.rebuild_ms_last = ms;
    stats_.rebuild_ms_worst = std::max(stats_.rebuild_ms_worst, ms);
    stats_.bodies_woken += woken;
    if (effect != nullptr) {
        effect->chunks_rebuilt += chunks.size();
        effect->rebuild_ms += ms;
        effect->bodies_woken += woken;
    }
}

void Environment::rebuildFieldChunks(JoltWorld &world, int which, const std::set<int> &chunks, EditEffect *effect) {
    if (which < 0) rebuildChunks(world, chunks, effect);
    else rebuildRegionChunks(world, which, chunks, effect);
}

std::vector<std::pair<int, int>> Environment::seamChunks(int which, const std::vector<std::size_t> &cells) const {
    std::set<std::pair<int, int>> found;
    if (regions_.empty()) return {};
    const TerrainField &field = fieldOf(which);
    const Grid &g = field.grid();
    const int rx = which < 0 ? 0 : regions_[static_cast<std::size_t>(which)]->rx;
    const int rz = which < 0 ? 0 : regions_[static_cast<std::size_t>(which)]->rz;
    for (const std::size_t c : cells) {
        if (c >= g.cells()) continue;
        const int i = static_cast<int>(c % static_cast<std::size_t>(g.nx));
        const int j = static_cast<int>(c / static_cast<std::size_t>(g.nx));
        const auto add = [&](int di, int dj) {
            const int other = regionIndex(rx + di, rz + dj);
            if (other == -2) return;
            const TerrainField &beside = fieldOf(other);
            const int ni = di < 0 ? g.nx - 1 : di > 0 ? 0 : i;
            const int nj = dj < 0 ? g.nz - 1 : dj > 0 ? 0 : j;
            const int cx = std::min(ni / TerrainField::kChunkCells, beside.chunksX() - 1);
            const int cz = std::min(nj / TerrainField::kChunkCells, beside.chunksZ() - 1);
            found.insert({other, cz * beside.chunksX() + cx});
        };
        if (i == 0) add(-1, 0);
        if (i == g.nx - 1) add(1, 0);
        if (j == 0) add(0, -1);
        if (j == g.nz - 1) add(0, 1);
    }
    return {found.begin(), found.end()};
}

void Environment::queueSeams(int which, const std::vector<std::size_t> &cells) {
    for (const auto &[other, chunk] : seamChunks(which, cells)) {
        if (other < 0) pending_chunks_.insert(chunk);
        else regions_[static_cast<std::size_t>(other)]->pending_chunks.insert(chunk);
    }
}

void Environment::rebuildSeams(JoltWorld &world, int which, const std::vector<std::size_t> &cells, EditEffect *effect) {
    std::map<int, std::set<int>> by_field;
    for (const auto &[other, chunk] : seamChunks(which, cells)) by_field[other].insert(chunk);
    for (const auto &[other, chunks] : by_field) rebuildFieldChunks(world, other, chunks, effect);
}

void Environment::regionEdited(JoltWorld *world, int k, const std::vector<std::size_t> &cells, EditEffect *effect) {
    StreamedRegion &r = *regions_[static_cast<std::size_t>(k)];
    r.edited = true;
    const Grid &g = r.field->grid();
    for (const std::size_t c : cells)
        grow(r.pending_wake, static_cast<int>(c % static_cast<std::size_t>(g.nx)),
             static_cast<int>(c / static_cast<std::size_t>(g.nx)));
    const std::set<int> chunks = r.field->takeDirtyChunks();
    r.edited_chunks.insert(chunks.begin(), chunks.end());
    if (world == nullptr || !attached_) {
        r.pending_chunks.insert(chunks.begin(), chunks.end());
        queueSeams(k, cells);
        return;
    }
    rebuildRegionChunks(*world, k, chunks, effect);
    rebuildSeams(*world, k, cells, effect);
}

void Environment::commitRegions(JoltWorld &world, double dt_s) {
    for (int k = 0; k < static_cast<int>(regions_.size()); ++k) {
        StreamedRegion &r = *regions_[static_cast<std::size_t>(k)];
        r.since_rebuild_s += dt_s;
        if (r.field->settled()) {
            r.ground_behind_s = 0.0;
        } else {
            r.ground_behind_s += dt_s;
            const Grid &g = r.field->grid();
            while (r.ground_behind_s >= kGroundStrideS && !r.field->settled()) {
                const Relaxed relaxed = r.field->relax(kGroundStrideS);
                r.ground_behind_s -= kGroundStrideS;
                for (const std::size_t c : relaxed.changed)
                    grow(r.pending_wake, static_cast<int>(c % static_cast<std::size_t>(g.nx)),
                         static_cast<int>(c / static_cast<std::size_t>(g.nx)));
                queueSeams(k, relaxed.changed);
            }
        }
        for (const int chunk : r.field->takeDirtyChunks()) {
            r.pending_chunks.insert(chunk);
            r.edited_chunks.insert(chunk);
        }
        if (!r.pending_chunks.empty() && r.since_rebuild_s >= kRebuildStrideS) {
            rebuildRegionChunks(world, k, r.pending_chunks, nullptr);
            r.pending_chunks.clear();
            r.since_rebuild_s = 0.0;
        }
    }
}

// ---- for the host -------------------------------------------------------------------

std::vector<int> Environment::takeAddedRegions() {
    std::vector<int> out;
    out.swap(regions_added_);
    return out;
}

std::vector<std::pair<int, TerrainField::Rect>> Environment::takeChangedRegions() {
    std::vector<std::pair<int, TerrainField::Rect>> out;
    for (int k = 0; k < static_cast<int>(regions_.size()); ++k) {
        const TerrainField::Rect r = regions_[static_cast<std::size_t>(k)]->field->takeChangedRect();
        if (r.ni > 0 && r.nj > 0) out.emplace_back(k, r);
    }
    return out;
}

// ---- kept and opened again ------------------------------------------------------------

Volumes Environment::regionsDug() const {
    Volumes out;
    for (const auto &r : regions_) {
        const Ledger &l = r->field->ledger();
        out.rock_m3 += l.dug.rock_m3 + l.cut.rock_m3;
        out.soil_m3 += l.dug.soil_m3;
        out.sand_m3 += l.dug.sand_m3;
    }
    return out;
}

// A region is kept as where it is, and -- only where it has been changed --
// the ground of the chunks that changed, column by column: a region nobody has
// touched is a few bytes, and one with a hole dug in it is the chunk or two
// round the hole, not the whole region. Everything else is made again from the
// seed when the world opens.
namespace {

// The columns a chunk owns: as the colliders count them, the last chunk each
// way taking the points past the last whole chunk.
void chunkColumns(const TerrainField &field, int chunk, int &i0, int &j0, int &i1, int &j1) {
    const Grid &g = field.grid();
    const int cx = chunk % field.chunksX(), cz = chunk / field.chunksX();
    i0 = cx * TerrainField::kChunkCells;
    j0 = cz * TerrainField::kChunkCells;
    i1 = cx + 1 == field.chunksX() ? g.nx : i0 + TerrainField::kChunkCells;
    j1 = cz + 1 == field.chunksZ() ? g.nz : j0 + TerrainField::kChunkCells;
}

} // namespace

std::string Environment::regionsStateJson() const {
    Json list = Json::array();
    for (const auto &r : regions_) {
        Json entry = {{"at", {r->rx, r->rz}}, {"version", kStreamVersion}};
        if (!r->edited) {
            list.push_back(std::move(entry));
            continue;
        }
        const TerrainField::State s = r->field->state();
        const Grid &g = s.grid;
        entry["ledger"] = {{"initial", volumesJson(s.ledger.initial)}, {"dug", volumesJson(s.ledger.dug)},
                           {"cut", volumesJson(s.ledger.cut)}, {"deposited", volumesJson(s.ledger.deposited)},
                           {"slumped_m3", s.ledger.slumped_m3}, {"loosened_m3", s.ledger.loosened_m3}};
        entry["frontier"] = s.frontier;
        Json chunks = Json::array();
        for (const int chunk : r->edited_chunks) {
            int i0, j0, i1, j1;
            chunkColumns(*r->field, chunk, i0, j0, i1, j1);
            // Each column's beds as the field holds them -- its room, how many
            // are live, what each is and its top -- and its loose layers.
            std::vector<std::uint32_t> room, count;
            std::vector<std::uint8_t> kind;
            std::vector<double> top, soil, sand, loose;
            std::vector<float> moisture;
            for (int j = j0; j < j1; ++j)
                for (int i = i0; i < i1; ++i) {
                    const std::size_t c = g.at(i, j);
                    const std::uint32_t from = s.beds.start[c], to = s.beds.start[c + 1];
                    room.push_back(to - from);
                    count.push_back(s.beds.count[c]);
                    for (std::uint32_t k = from; k < to; ++k) {
                        kind.push_back(s.beds.kind[k]);
                        top.push_back(s.beds.top[k]);
                    }
                    soil.push_back(s.soil[c]);
                    sand.push_back(s.sand[c]);
                    loose.push_back(s.loose[c]);
                    moisture.push_back(s.moisture[c]);
                }
            chunks.push_back({{"chunk", chunk}, {"room", packed(room)}, {"count", packed(count)},
                              {"kind", packed(kind)}, {"top", packed(top)}, {"soil", packed(soil)},
                              {"sand", packed(sand)}, {"loose", packed(loose)}, {"moisture", packed(moisture)}});
        }
        entry["chunks"] = std::move(chunks);
        list.push_back(std::move(entry));
    }
    return list.dump();
}

void Environment::restoreRegionsState(const std::string &text) {
    const Json list = Json::parse(text);
    if (!list.is_array() || list.size() > static_cast<std::size_t>(kMostRegions))
        throw std::invalid_argument("saved regions are a list of at most " + std::to_string(kMostRegions));
    if (!list.empty() && !canStream())
        throw std::invalid_argument("saved regions, and this ground cannot have any");
    for (const Json &entry : list) {
        if (!entry.is_object() || !entry.contains("at") || !entry.at("at").is_array() || entry.at("at").size() != 2)
            throw std::invalid_argument("a saved region says where it is");
        const int rx = entry.at("at")[0].get<int>(), rz = entry.at("at")[1].get<int>();
        if (regionIndex(rx, rz) == -2 && !addRegion(nullptr, rx, rz))
            throw std::invalid_argument("a saved region cannot be made again at " + std::to_string(rx) + ", " +
                                        std::to_string(rz));
        const int k = regionIndex(rx, rz);
        if (k < 0) throw std::invalid_argument("a saved region is the valley");
        if (!entry.contains("chunks")) continue;   // as generated
        StreamedRegion &r = *regions_[static_cast<std::size_t>(k)];
        const TerrainField::State made = r.field->state();
        const Grid &g = made.grid;
        const std::size_t n = g.cells();
        // Which columns come from the saved chunks, and what each holds.
        struct Column {
            std::uint32_t room{}, count{};
            std::vector<std::uint8_t> kind;
            std::vector<double> top;
            double soil{}, sand{}, loose{};
            float moisture{};
        };
        std::vector<int> saved_at(n, -1);
        std::vector<Column> saved;
        std::set<int> chunks_seen;
        const int chunk_count = r.field->chunksX() * r.field->chunksZ();
        for (const Json &chunk : entry.at("chunks")) {
            const int id = chunk.at("chunk").get<int>();
            if (id < 0 || id >= chunk_count || !chunks_seen.insert(id).second)
                throw std::invalid_argument("a saved region's chunk is not one of its own, or is there twice");
            int i0, j0, i1, j1;
            chunkColumns(*r.field, id, i0, j0, i1, j1);
            const std::size_t columns = static_cast<std::size_t>(i1 - i0) * static_cast<std::size_t>(j1 - j0);
            std::vector<std::uint32_t> room, count;
            std::vector<double> soil, sand, loose;
            std::vector<float> moisture;
            unpack(chunk, "room", room, columns);
            unpack(chunk, "count", count, columns);
            std::size_t beds = 0;
            for (const std::uint32_t b : room) {
                if (b < 1 || b > 16) throw std::invalid_argument("a saved region's column has no room for its beds");
                beds += b;
            }
            std::vector<std::uint8_t> kind;
            std::vector<double> top;
            unpack(chunk, "kind", kind, beds);
            unpack(chunk, "top", top, beds);
            unpack(chunk, "soil", soil, columns);
            unpack(chunk, "sand", sand, columns);
            unpack(chunk, "loose", loose, columns);
            unpack(chunk, "moisture", moisture, columns);
            std::size_t at = 0, bed = 0;
            for (int j = j0; j < j1; ++j)
                for (int i = i0; i < i1; ++i, ++at) {
                    Column column;
                    column.room = room[at];
                    column.count = count[at];
                    column.kind.assign(kind.begin() + static_cast<std::ptrdiff_t>(bed),
                                       kind.begin() + static_cast<std::ptrdiff_t>(bed + room[at]));
                    column.top.assign(top.begin() + static_cast<std::ptrdiff_t>(bed),
                                      top.begin() + static_cast<std::ptrdiff_t>(bed + room[at]));
                    bed += room[at];
                    column.soil = soil[at];
                    column.sand = sand[at];
                    column.loose = loose[at];
                    column.moisture = moisture[at];
                    saved_at[g.at(i, j)] = static_cast<int>(saved.size());
                    saved.push_back(std::move(column));
                }
        }
        // The whole field's state: generated columns as made, saved ones as kept.
        TerrainField::State s = made;
        s.beds = {};
        s.beds.start.reserve(n + 1);
        s.beds.count.resize(n);
        for (std::size_t c = 0; c < n; ++c) {
            s.beds.start.push_back(static_cast<std::uint32_t>(s.beds.top.size()));
            if (saved_at[c] < 0) {
                const std::uint32_t from = made.beds.start[c], to = made.beds.start[c + 1];
                s.beds.count[c] = made.beds.count[c];
                s.beds.kind.insert(s.beds.kind.end(), made.beds.kind.begin() + from, made.beds.kind.begin() + to);
                s.beds.top.insert(s.beds.top.end(), made.beds.top.begin() + from, made.beds.top.begin() + to);
                continue;
            }
            const Column &column = saved[static_cast<std::size_t>(saved_at[c])];
            s.beds.count[c] = column.count;
            s.beds.kind.insert(s.beds.kind.end(), column.kind.begin(), column.kind.end());
            s.beds.top.insert(s.beds.top.end(), column.top.begin(), column.top.end());
            s.soil[c] = column.soil;
            s.sand[c] = column.sand;
            s.loose[c] = column.loose;
            s.moisture[c] = column.moisture;
        }
        s.beds.start.push_back(static_cast<std::uint32_t>(s.beds.top.size()));
        const Json &l = entry.at("ledger");
        s.ledger = {volumesFrom(l.at("initial")), volumesFrom(l.at("dug")), volumesFrom(l.at("cut")),
                    volumesFrom(l.at("deposited")), l.at("slumped_m3").get<double>(),
                    l.at("loosened_m3").get<double>()};
        s.frontier.clear();
        for (const Json &c : entry.value("frontier", Json::array())) {
            const std::size_t at = c.get<std::size_t>();
            if (at >= n) throw std::invalid_argument("a saved region's unsettled column is off its grid");
            s.frontier.insert(at);
        }
        s.dirty_chunks.clear();
        s.changed = {};
        // The floor is the generated one: a dig does not move it.
        r.field->restore(s);
        r.edited = true;
        r.edited_chunks = chunks_seen;
        for (std::size_t chunk = 0; chunk < r.colliders.size(); ++chunk)
            r.colliders[chunk] = chunkHeightsOf(k, static_cast<int>(chunk));
    }
    // Opened again, nothing is new: the host draws them from the whole ground.
    regions_added_.clear();
}

} // namespace banjo::terrain
