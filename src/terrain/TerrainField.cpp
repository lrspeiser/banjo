#include "terrain/TerrainField.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace banjo::terrain {
namespace {

constexpr double kGravity = 9.81;
constexpr double kPi = 3.14159265358979323846;
// Below this a layer is not there. A tenth of a millimetre is nothing anyone
// digs through or stands on.
constexpr double kThin = 1.0e-4;

// Terzaghi's critical height of an unsupported vertical cut, with tension
// cracks: 2.67 (c / gamma) tan(45 + phi / 2).
double criticalHeight(const GroundMaterial &m) {
    if (!(m.cohesion_pa > 0.0)) return 0.0;
    const double gamma = m.density_kg_m3 * kGravity;
    return 2.67 * (m.cohesion_pa / gamma) * std::tan((45.0 + 0.5 * m.friction_angle_deg) * kPi / 180.0);
}

} // namespace

double TerrainField::stableDrop(const GroundMaterial &material, double run_m) {
    const double friction = run_m * std::tan(material.friction_angle_deg * kPi / 180.0);
    return std::max(friction, criticalHeight(material)) + 2.0 * kStopLayerM;
}

const GroundMaterial &rockMaterial() {
    // Rock does not slump. The friction angle is the reason the stability
    // check skips it, not a number anybody should read as a measurement.
    static const GroundMaterial rock{"rock", 2400.0, 90.0, 1.0e7};
    return rock;
}
const GroundMaterial &soilMaterial() {
    // A firm loam: bulk density with its pore space, a friction angle of 30
    // degrees and a little cohesion, enough to hold a spade-deep trench.
    static const GroundMaterial soil{"soil", 1600.0, 30.0, 2000.0};
    return soil;
}
const GroundMaterial &sandMaterial() {
    // Dry sand: no cohesion, and the angle a heap of it stands at.
    static const GroundMaterial sand{"sand", 1600.0, 32.0, 0.0};
    return sand;
}

TerrainField::TerrainField(Grid grid, std::vector<double> rock_top_m, std::vector<double> soil_m,
                           std::vector<double> sand_m, std::vector<double> loose_soil_m,
                           std::vector<float> moisture)
    : grid_(grid), rock_(std::move(rock_top_m)), soil_(std::move(soil_m)),
      sand_(std::move(sand_m)), loose_(std::move(loose_soil_m)), moisture_(std::move(moisture)) {
    if (grid_.nx < 2 || grid_.nz < 2 || !(grid_.dx > 0.0))
        throw std::invalid_argument("terrain needs a grid of at least 2 x 2 points with a positive spacing");
    const std::size_t n = grid_.cells();
    if (loose_.empty()) loose_.assign(n, 0.0);
    if (moisture_.empty()) moisture_.assign(n, 0.0F);
    if (rock_.size() != n || soil_.size() != n || sand_.size() != n || loose_.size() != n ||
        moisture_.size() != n)
        throw std::invalid_argument("terrain needs one value of each layer per point");
    // A layer rounded a hair below zero is a layer of nothing; anything more
    // than rounding below zero is a mistake and is refused below.
    for (std::vector<double> *layer : {&soil_, &sand_, &loose_})
        for (double &v : *layer)
            if (v < 0.0 && v > -1.0e-9) v = 0.0;
    for (std::size_t c = 0; c < n; ++c)
        if (!std::isfinite(rock_[c]) || !(soil_[c] >= 0.0) || !(sand_[c] >= 0.0) ||
            !(loose_[c] >= 0.0) || !std::isfinite(soil_[c] + sand_[c] + loose_[c]))
            throw std::invalid_argument("a terrain layer is negative or not finite");
    floor_ = *std::min_element(rock_.begin(), rock_.end()) - 2.0;
    chunks_x_ = std::max(1, (grid_.nx - 2) / kChunkCells + 1);
    chunks_z_ = std::max(1, (grid_.nz - 2) / kChunkCells + 1);
    resetLedger();
}

Surface TerrainField::surface(std::size_t c) const {
    // A layer is what the surface IS once it is thick enough to stand on: a
    // film of sand a millimetre deep on a soil bank is a soil bank.
    if (sand_[c] + loose_[c] > 0.02) return sand_[c] >= loose_[c] ? Surface::Sand : Surface::Soil;
    if (soil_[c] + sand_[c] + loose_[c] > 0.02) return Surface::Soil;
    return Surface::Rock;
}

std::optional<std::size_t> TerrainField::cellAt(double x, double z) const {
    const long i = std::lround((x - grid_.x0) / grid_.dx);
    const long j = std::lround((z - grid_.z0) / grid_.dx);
    if (i < 0 || j < 0 || i >= grid_.nx || j >= grid_.nz) return std::nullopt;
    return grid_.at(static_cast<int>(i), static_cast<int>(j));
}

double TerrainField::heightAt(double x, double z) const {
    const double fx = std::clamp((x - grid_.x0) / grid_.dx, 0.0, grid_.nx - 1.0);
    const double fz = std::clamp((z - grid_.z0) / grid_.dx, 0.0, grid_.nz - 1.0);
    const int i = std::min(grid_.nx - 2, static_cast<int>(fx));
    const int j = std::min(grid_.nz - 2, static_cast<int>(fz));
    const double u = fx - i, v = fz - j;
    const double h00 = height(grid_.at(i, j)), h10 = height(grid_.at(i + 1, j));
    const double h01 = height(grid_.at(i, j + 1)), h11 = height(grid_.at(i + 1, j + 1));
    // Two triangles per quad, split along the diagonal from (i, j) to
    // (i + 1, j + 1) -- the same split the collider uses, so a thing placed on
    // this height is placed on the surface it will actually touch.
    if (u >= v) return h00 + u * (h10 - h00) + v * (h11 - h10);
    return h00 + v * (h01 - h00) + u * (h11 - h01);
}

double TerrainField::slopeDeg(std::size_t c) const {
    const int i = static_cast<int>(c % static_cast<std::size_t>(grid_.nx));
    const int j = static_cast<int>(c / static_cast<std::size_t>(grid_.nx));
    const int i0 = std::max(0, i - 1), i1 = std::min(grid_.nx - 1, i + 1);
    const int j0 = std::max(0, j - 1), j1 = std::min(grid_.nz - 1, j + 1);
    const double gx = (height(grid_.at(i1, j)) - height(grid_.at(i0, j))) / ((i1 - i0) * grid_.dx);
    const double gz = (height(grid_.at(i, j1)) - height(grid_.at(i, j0))) / ((j1 - j0) * grid_.dx);
    return std::atan(std::hypot(gx, gz)) * 180.0 / kPi;
}

double TerrainField::lowest() const {
    double low = std::numeric_limits<double>::infinity();
    for (std::size_t c = 0; c < grid_.cells(); ++c) low = std::min(low, height(c));
    return low;
}

double TerrainField::highest() const {
    double high = -std::numeric_limits<double>::infinity();
    for (std::size_t c = 0; c < grid_.cells(); ++c) high = std::max(high, height(c));
    return high;
}

void TerrainField::touched(std::size_t c) {
    const int i = static_cast<int>(c % static_cast<std::size_t>(grid_.nx));
    const int j = static_cast<int>(c / static_cast<std::size_t>(grid_.nx));
    // A point on the edge between two chunks is a point of both of them.
    const auto chunksOf = [](int k, int count) {
        std::pair<int, int> out{std::min(count - 1, k / kChunkCells), -1};
        if (k % kChunkCells == 0 && k > 0 && k / kChunkCells - 1 < count)
            out.second = std::min(count - 1, k / kChunkCells - 1);
        return out;
    };
    const auto [cx, cx2] = chunksOf(i, chunks_x_);
    const auto [cz, cz2] = chunksOf(j, chunks_z_);
    for (const int x : {cx, cx2})
        for (const int z : {cz, cz2})
            if (x >= 0 && z >= 0) dirty_chunks_.insert(z * chunks_x_ + x);
    if (changed_i1_ < changed_i0_) {
        changed_i0_ = changed_i1_ = i;
        changed_j0_ = changed_j1_ = j;
    } else {
        changed_i0_ = std::min(changed_i0_, i);
        changed_i1_ = std::max(changed_i1_, i);
        changed_j0_ = std::min(changed_j0_, j);
        changed_j1_ = std::max(changed_j1_, j);
    }
}

void TerrainField::markChanged(const std::vector<std::size_t> &cells) {
    for (const std::size_t c : cells) {
        const int i = static_cast<int>(c % static_cast<std::size_t>(grid_.nx));
        const int j = static_cast<int>(c / static_cast<std::size_t>(grid_.nx));
        for (int dj = -1; dj <= 1; ++dj)
            for (int di = -1; di <= 1; ++di) {
                const int x = i + di, z = j + dj;
                if (x < 0 || z < 0 || x >= grid_.nx || z >= grid_.nz) continue;
                frontier_.insert(grid_.at(x, z));
            }
    }
    frontier_peak_ = std::max(frontier_peak_, frontier_.size());
}

Volumes TerrainField::strip(std::size_t c, double thickness) {
    Volumes took;
    const double area = grid_.dx * grid_.dx;
    double left = std::max(0.0, thickness);
    // The loose layer first, sand and loose soil in proportion: it is one
    // mixture, not two layers in an order.
    const double loose = sand_[c] + loose_[c];
    if (left > 0.0 && loose > 0.0) {
        const double take = std::min(left, loose);
        const double from_sand = take * (sand_[c] / loose);
        const double from_soil = take - from_sand;
        sand_[c] = std::max(0.0, sand_[c] - from_sand);
        loose_[c] = std::max(0.0, loose_[c] - from_soil);
        took.sand_m3 += from_sand * area;
        took.soil_m3 += from_soil * area;
        left -= take;
    }
    if (left > 0.0 && soil_[c] > 0.0) {
        const double take = std::min(left, soil_[c]);
        soil_[c] -= take;
        took.soil_m3 += take * area;
        left -= take;
    }
    return took;
}

EditReport TerrainField::dig(double ax, double az, double bx, double bz, double width_m,
                             double depth_m) {
    EditReport report;
    if (!(width_m > 0.0) || !(depth_m > 0.0) || !std::isfinite(ax + az + bx + bz + width_m + depth_m))
        throw std::invalid_argument("a dig needs two points, a positive width and a positive depth");
    const double r = 0.5 * width_m;
    const double lx = bx - ax, lz = bz - az;
    const double length2 = lx * lx + lz * lz;
    const int i0 = std::max(0, static_cast<int>(std::floor((std::min(ax, bx) - r - grid_.x0) / grid_.dx)));
    const int i1 = std::min(grid_.nx - 1, static_cast<int>(std::ceil((std::max(ax, bx) + r - grid_.x0) / grid_.dx)));
    const int j0 = std::max(0, static_cast<int>(std::floor((std::min(az, bz) - r - grid_.z0) / grid_.dx)));
    const int j1 = std::min(grid_.nz - 1, static_cast<int>(std::ceil((std::max(az, bz) + r - grid_.z0) / grid_.dx)));
    for (int j = j0; j <= j1; ++j)
        for (int i = i0; i <= i1; ++i) {
            const double px = grid_.xOf(i) - ax, pz = grid_.zOf(j) - az;
            const double s = length2 > 0.0 ? std::clamp((px * lx + pz * lz) / length2, 0.0, 1.0) : 0.0;
            const double dx = px - s * lx, dz = pz - s * lz;
            if (dx * dx + dz * dz > r * r) continue;
            const std::size_t c = grid_.at(i, j);
            const Volumes took = strip(c, depth_m);
            if (took.total() <= 0.0) continue;
            report.moved.sand_m3 += took.sand_m3;
            report.moved.soil_m3 += took.soil_m3;
            report.cells.push_back(c);
            touched(c);
        }
    report.mass_kg = report.moved.sand_m3 * sandMaterial().density_kg_m3 +
                     report.moved.soil_m3 * soilMaterial().density_kg_m3;
    ledger_.dug.sand_m3 += report.moved.sand_m3;
    ledger_.dug.soil_m3 += report.moved.soil_m3;
    markChanged(report.cells);
    return report;
}

EditReport TerrainField::deposit(double x, double z, double radius_m, double sand_m3, double soil_m3) {
    EditReport report;
    if (!(radius_m > 0.0) || !(sand_m3 >= 0.0) || !(soil_m3 >= 0.0) || !(sand_m3 + soil_m3 > 0.0))
        throw std::invalid_argument("a heap needs a positive radius and something to heap");
    const double area = grid_.dx * grid_.dx;
    // A cone: the most in the middle, nothing at the rim.
    std::vector<std::pair<std::size_t, double>> weights;
    double total = 0.0;
    const int reach = static_cast<int>(std::ceil(radius_m / grid_.dx));
    const auto centre = cellAt(x, z);
    if (!centre) throw std::invalid_argument("that point is not on the ground");
    const int ci = static_cast<int>(*centre % static_cast<std::size_t>(grid_.nx));
    const int cj = static_cast<int>(*centre / static_cast<std::size_t>(grid_.nx));
    for (int j = cj - reach; j <= cj + reach; ++j)
        for (int i = ci - reach; i <= ci + reach; ++i) {
            if (i < 0 || j < 0 || i >= grid_.nx || j >= grid_.nz) continue;
            const double d = std::hypot(grid_.xOf(i) - x, grid_.zOf(j) - z);
            const double w = std::max(0.0, 1.0 - d / radius_m);
            if (w <= 0.0) continue;
            weights.emplace_back(grid_.at(i, j), w);
            total += w;
        }
    if (weights.empty()) weights.emplace_back(*centre, total = 1.0);
    for (const auto &[c, w] : weights) {
        const double share = w / total;
        sand_[c] += share * sand_m3 / area;
        loose_[c] += share * soil_m3 / area;
        report.cells.push_back(c);
        touched(c);
    }
    report.moved.sand_m3 = sand_m3;
    report.moved.soil_m3 = soil_m3;
    report.mass_kg = sand_m3 * sandMaterial().density_kg_m3 + soil_m3 * soilMaterial().density_kg_m3;
    ledger_.deposited.sand_m3 += sand_m3;
    ledger_.deposited.soil_m3 += soil_m3;
    markChanged(report.cells);
    return report;
}

std::optional<CutBlock> TerrainField::cut(double x, double z, int cells_x, int cells_z, double height_m,
                                          std::string *why) {
    const auto fail = [&](const std::string &reason) -> std::optional<CutBlock> {
        if (why) *why = reason;
        return std::nullopt;
    };
    if (cells_x < 1 || cells_z < 1 || !(height_m > 0.0))
        return fail("a block needs at least one column each way and a positive height");
    const auto centre = cellAt(x, z);
    if (!centre) return fail("that point is not on the ground");
    const int ci = static_cast<int>(*centre % static_cast<std::size_t>(grid_.nx));
    const int cj = static_cast<int>(*centre / static_cast<std::size_t>(grid_.nx));
    const int i0 = ci - cells_x / 2, j0 = cj - cells_z / 2;
    if (i0 < 0 || j0 < 0 || i0 + cells_x > grid_.nx || j0 + cells_z > grid_.nz)
        return fail("the block would run off the edge of the ground");
    double lowest = std::numeric_limits<double>::infinity();
    double mean = 0.0;
    double cover = 0.0;
    for (int j = j0; j < j0 + cells_z; ++j)
        for (int i = i0; i < i0 + cells_x; ++i) {
            const std::size_t c = grid_.at(i, j);
            lowest = std::min(lowest, rock_[c]);
            mean += rock_[c];
            cover = std::max(cover, soil_[c] + sand_[c] + loose_[c]);
        }
    mean /= static_cast<double>(cells_x * cells_z);
    if (cover > 0.01) {
        char text[160];
        std::snprintf(text, sizeof text,
                      "there is %.2f m of soil and sand over the rock there; dig it away first "
                      "or cut where the rock is bare", cover);
        return fail(text);
    }
    const double bottom = mean - height_m;
    if (lowest < bottom) {
        char text[200];
        std::snprintf(text, sizeof text,
                      "the rock there is %.2f m uneven, more than a block %.2f m tall can be cut from "
                      "without filling a hollow: cut deeper, or somewhere flatter", mean - lowest, height_m);
        return fail(text);
    }
    if (bottom < floor_ + 0.05) return fail("that is deeper than the rock goes");
    const double area = grid_.dx * grid_.dx;
    double rock = 0.0;
    std::vector<std::size_t> cells;
    for (int j = j0; j < j0 + cells_z; ++j)
        for (int i = i0; i < i0 + cells_x; ++i) {
            const std::size_t c = grid_.at(i, j);
            // A film of loose material on bare rock comes away with the block's
            // top and is counted as dug, so every kind stays accounted.
            const Volumes film = strip(c, soil_[c] + sand_[c] + loose_[c]);
            ledger_.dug.sand_m3 += film.sand_m3;
            ledger_.dug.soil_m3 += film.soil_m3;
            rock += (rock_[c] - bottom) * area;
            rock_[c] = bottom;
            cells.push_back(c);
            touched(c);
        }
    ledger_.cut.rock_m3 += rock;
    markChanged(cells);
    CutBlock block;
    // Exactly footprint x height by construction; the sum is kept as the
    // volume so the ledger and the block agree to the last bit.
    block.size_m = {cells_x * grid_.dx, height_m, cells_z * grid_.dx};
    const double height = height_m;
    block.center_m = {grid_.xOf(i0) + 0.5 * (cells_x - 1) * grid_.dx, bottom + 0.5 * height,
                      grid_.zOf(j0) + 0.5 * (cells_z - 1) * grid_.dx};
    block.volume_m3 = rock;
    block.mass_kg = rock * rockMaterial().density_kg_m3;
    return block;
}

Relaxed TerrainField::relax(double dt_s) {
    Relaxed out;
    if (frontier_.empty() || !(dt_s > 0.0)) return out;
    const double area = grid_.dx * grid_.dx;
    const std::vector<std::size_t> now(frontier_.begin(), frontier_.end());
    frontier_.clear();
    std::set<std::size_t> changed;
    const double hc_soil = criticalHeight(soilMaterial());
    const double tan_sand = std::tan(sandMaterial().friction_angle_deg * kPi / 180.0);
    const double tan_soil = std::tan(soilMaterial().friction_angle_deg * kPi / 180.0);
    static constexpr int kDi[8] = {1, -1, 0, 0, 1, 1, -1, -1};
    static constexpr int kDj[8] = {0, 0, 1, -1, 1, -1, 1, -1};
    for (const std::size_t c : now) {
        ++out.checked;
        const int i = static_cast<int>(c % static_cast<std::size_t>(grid_.nx));
        const int j = static_cast<int>(c / static_cast<std::size_t>(grid_.nx));
        for (int k = 0; k < 8; ++k) {
            const int x = i + kDi[k], z = j + kDj[k];
            if (x < 0 || z < 0 || x >= grid_.nx || z >= grid_.nz) continue;
            const std::size_t n = grid_.at(x, z);
            const double drop = height(c) - height(n);
            if (!(drop > kThin)) continue;
            const bool diagonal = k >= 4;
            const double run = diagonal ? grid_.dx * 1.4142135623730951 : grid_.dx;
            // What would fail decides what can hold the drop. The loose layer
            // slides at its own angle -- but only as much of it as there is:
            // a film of sand on a firm soil bank slides off it, and the bank
            // is then judged as soil, which stands a spade-deep face.
            const double loose = sand_[c] + loose_[c];
            const double tan_loose = loose > 0.0
                ? (sand_[c] * tan_sand + loose_[c] * tan_soil) / loose : tan_sand;
            const double loose_excess = drop - run * tan_loose;
            const double soil_excess = drop - std::max(run * tan_soil, hc_soil);
            double excess = 0.0;
            double movable = 0.0;
            if (loose > kThin && loose_excess > 2.0 * kStopLayerM) {
                excess = loose_excess;
                // Loose material only, unless the native soil below it would
                // fail too.
                movable = soil_excess > 2.0 * kStopLayerM ? loose + soil_[c] : loose;
            } else if (soil_[c] > kThin && soil_excess > 2.0 * kStopLayerM) {
                excess = soil_excess;
                movable = loose + soil_[c];
            } else {
                continue;   // it holds; bare rock always does
            }
            // Half the excess would level the step to what it can hold. What
            // actually moves in dt is what a layer that thick flows in that
            // time, across a face this wide (a corner neighbour shares its
            // face, so half).
            const double width = diagonal ? 0.5 * grid_.dx : grid_.dx;
            const double half = 0.5 * excess;
            const double flowing = width * half * std::sqrt(kGravity * half) * dt_s / area;
            double thickness = std::min(half, flowing);
            thickness = std::min(thickness, movable);
            if (!(thickness > 1.0e-7)) continue;
            const double native_before = soil_[c];
            const Volumes took = strip(c, thickness);
            sand_[n] += took.sand_m3 / area;
            loose_[n] += took.soil_m3 / area;
            const double loosened = (native_before - soil_[c]) * area;
            ledger_.slumped_m3 += took.total();
            ledger_.loosened_m3 += loosened;
            out.moved_m3 += took.total();
            ++out.failed;
            changed.insert(c);
            changed.insert(n);
        }
    }
    out.changed.assign(changed.begin(), changed.end());
    for (const std::size_t c : out.changed) touched(c);
    markChanged(out.changed);
    checked_total_ += out.checked;
    return out;
}

std::set<int> TerrainField::takeDirtyChunks() {
    std::set<int> out;
    out.swap(dirty_chunks_);
    return out;
}

TerrainField::Rect TerrainField::takeChangedRect() {
    Rect out;
    if (changed_i1_ >= changed_i0_) {
        out = {changed_i0_, changed_j0_, changed_i1_ - changed_i0_ + 1, changed_j1_ - changed_j0_ + 1};
        changed_i0_ = changed_j0_ = 0;
        changed_i1_ = changed_j1_ = -1;
    }
    return out;
}

Volumes TerrainField::volumes() const {
    const double area = grid_.dx * grid_.dx;
    Volumes v;
    for (std::size_t c = 0; c < grid_.cells(); ++c) {
        v.rock_m3 += (rock_[c] - floor_) * area;
        v.soil_m3 += (soil_[c] + loose_[c]) * area;
        v.sand_m3 += sand_[c] * area;
    }
    return v;
}

Volumes TerrainField::residual() const {
    const Volumes now = volumes();
    const Ledger &l = ledger_;
    return {now.rock_m3 - (l.initial.rock_m3 - l.dug.rock_m3 - l.cut.rock_m3 + l.deposited.rock_m3),
            now.soil_m3 - (l.initial.soil_m3 - l.dug.soil_m3 - l.cut.soil_m3 + l.deposited.soil_m3),
            now.sand_m3 - (l.initial.sand_m3 - l.dug.sand_m3 - l.cut.sand_m3 + l.deposited.sand_m3)};
}

void TerrainField::resetLedger() {
    ledger_ = Ledger{};
    ledger_.initial = volumes();
}

} // namespace banjo::terrain
