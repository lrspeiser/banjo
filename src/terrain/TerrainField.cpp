#include "terrain/TerrainField.hpp"

#include "material/MaterialCatalog.hpp"

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

// A volume onto the kind it is made of. Loose soil is soil: it is the same
// matter, and the ledger has always counted it there.
void addByKind(Volumes &v, RunKind kind, double m3) {
    switch (kind) {
    // Rock, the rock that has rotted, and the ore in it are all the ground's
    // stone: the ledger counts matter, and what it is worth is the goods
    // account's business, not the ground's (docs/earth-and-mining-plan.md).
    case RunKind::Rock:
    case RunKind::WeatheredRock:
    case RunKind::Ore:
    case RunKind::OxidisedOre: v.rock_m3 += m3; return;
    case RunKind::Sand: v.sand_m3 += m3; return;
    // A void is nothing. It is not matter and the ledger counts none of it.
    case RunKind::Void: return;
    case RunKind::Soil:
    case RunKind::Clay:
    case RunKind::LooseSoil: v.soil_m3 += m3; return;
    }
    v.soil_m3 += m3;
}

} // namespace

double TerrainField::stableDrop(const GroundMaterial &material, double run_m) {
    const double friction = run_m * std::tan(material.friction_angle_deg * kPi / 180.0);
    return std::max(friction, criticalHeight(material)) + 2.0 * kStopLayerM;
}

Beds Beds::ofRock(const std::vector<double> &rock_top_m) {
    Beds beds;
    const std::size_t n = rock_top_m.size();
    beds.start.resize(n + 1);
    beds.count.assign(n, 1);
    beds.kind.assign(n, static_cast<std::uint8_t>(RunKind::Rock));
    beds.top = rock_top_m;
    for (std::size_t c = 0; c <= n; ++c) beds.start[c] = static_cast<std::uint32_t>(c);
    return beds;
}

TerrainField::State TerrainField::state() const {
    Rect changed{};
    if (changed_i1_ >= changed_i0_ && changed_j1_ >= changed_j0_)
        changed = {changed_i0_, changed_j0_, changed_i1_ - changed_i0_ + 1, changed_j1_ - changed_j0_ + 1};
    return {grid_, beds_, soil_, sand_, loose_, moisture_, floor_, ledger_, frontier_,
            dirty_chunks_, changed, checked_total_, frontier_peak_};
}

void TerrainField::restore(const State &s) {
    const auto refuse = [] { throw std::invalid_argument("invalid terrain continuation state"); };
    if (s.grid.nx != grid_.nx || s.grid.nz != grid_.nz || s.grid.dx != grid_.dx ||
        s.grid.x0 != grid_.x0 || s.grid.z0 != grid_.z0) refuse();
    const auto n = grid_.cells();
    if (s.soil.size() != n || s.sand.size() != n ||
        s.loose.size() != n || s.moisture.size() != n || !std::isfinite(s.floor)) refuse();
    if (s.beds.start.size() != n + 1 || s.beds.count.size() != n ||
        s.beds.kind.size() != s.beds.top.size() || s.beds.start[n] != s.beds.top.size()) refuse();
    for (std::size_t c = 0; c < n; ++c) {
        // At least one bed, no more than there is room for, and each bed's top
        // above the one below it, from the floor up.
        const std::uint32_t from = s.beds.start[c], to = s.beds.start[c + 1];
        if (to < from || s.beds.count[c] < 1 || s.beds.count[c] > to - from) refuse();
        double below = s.floor;
        for (std::uint32_t k = 0; k < s.beds.count[c]; ++k) {
            const double top = s.beds.top[from + k];
            if (!std::isfinite(top) || !(top >= below) || s.beds.kind[from + k] >= kRunKinds) refuse();
            below = top;
        }
        if (isVoid(static_cast<RunKind>(s.beds.kind[from + s.beds.count[c] - 1]))) refuse();
        if (!std::isfinite(s.moisture[c]) || s.moisture[c] < 0 || s.moisture[c] > 1) refuse();
        for (double v : {s.soil[c], s.sand[c], s.loose[c]})
            if (!std::isfinite(v) || v < 0) refuse();
        if (!std::isfinite(below + s.soil[c] + s.sand[c] + s.loose[c])) refuse();
    }
    for (const auto &v : {s.ledger.initial, s.ledger.dug, s.ledger.cut, s.ledger.deposited})
        for (double x : {v.rock_m3, v.soil_m3, v.sand_m3})
            if (!std::isfinite(x) || x < 0) refuse();
    for (double x : {s.ledger.slumped_m3, s.ledger.loosened_m3})
        if (!std::isfinite(x) || x < 0) refuse();
    for (auto c : s.frontier) if (c >= n) refuse();
    for (int c : s.dirty_chunks) if (c < 0 || c >= chunks_x_ * chunks_z_) refuse();
    const auto &r = s.changed;
    if (r.i0 < 0 || r.j0 < 0 || r.i0 > grid_.nx || r.j0 > grid_.nz ||
        r.ni < 0 || r.nj < 0 || r.ni > grid_.nx - r.i0 || r.nj > grid_.nz - r.j0 ||
        ((r.ni == 0) != (r.nj == 0)) || s.frontier_peak > n) refuse();

    // Construct and validate a candidate before touching this field, including
    // allocations. The saved rock floor is not recomputed from the cut surface.
    TerrainField candidate(grid_, s.beds, s.soil, s.sand, s.loose, s.moisture);
    candidate.column_surface_ = column_surface_;
    candidate.cut_surface_ = cut_surface_;
    candidate.baseline_ = baseline_;
    candidate.floor_ = s.floor;
    candidate.ledger_ = s.ledger;
    const auto residual = candidate.residual();
    const double scale = std::max(1.0, s.ledger.initial.total() + s.ledger.deposited.total() +
                                      s.ledger.dug.total() + s.ledger.cut.total());
    for (double v : {residual.rock_m3, residual.soil_m3, residual.sand_m3})
        if (!std::isfinite(v) || std::abs(v) > 1e-9 * scale) refuse();
    candidate.frontier_ = s.frontier;
    candidate.dirty_chunks_ = s.dirty_chunks;
    candidate.changed_i0_ = r.i0; candidate.changed_j0_ = r.j0;
    candidate.changed_i1_ = r.i0 + r.ni - 1; candidate.changed_j1_ = r.j0 + r.nj - 1;
    candidate.checked_total_ = s.checked_total;
    candidate.frontier_peak_ = s.frontier_peak;
    *this = std::move(candidate);
}

const GroundMaterial &rockMaterial() {
    // Rock does not slump. The friction angle is the reason the stability
    // check skips it, not a number anybody should read as a measurement.
    // Rolling on it is rolling on the engine's stone: the concrete preset's
    // own share, taken from there so the two cannot drift apart.
    static const GroundMaterial rock{
        "rock", 2400.0, 90.0, 1.0e7,
        makeReferenceMaterial(MaterialPreset::Concrete, 0).rolling_resistance,
        rollingResistanceSource(MaterialPreset::Concrete).sourced,
        "the engine's stone, concrete: a bicycle tyre on concrete is 0.002 in all "
        "(Engineering ToolBox). A natural rock surface's roughness is not modelled"};
    return rock;
}
const GroundMaterial &soilMaterial() {
    // A firm loam: bulk density with its pore space, a friction angle of 30
    // degrees and a little cohesion, enough to hold a spade-deep trench.
    // Rolling: a car tyre on medium-hard soil is 0.04-0.08, and a 19th-century
    // stagecoach on a dirt road 0.04-0.07 (docs/rolling-resistance.md).
    static const GroundMaterial soil{
        "soil", 1600.0, 30.0, 2000.0, 0.06, true,
        "a car tyre on medium-hard soil 0.04-0.08 (Engineering ToolBox); a stagecoach on a "
        "dirt road 0.0385-0.073 (Baker 1914)"};
    return soil;
}
const GroundMaterial &sandMaterial() {
    // Dry sand: no cohesion, and the angle a heap of it stands at. Rolling: a
    // car tyre on loose sand is 0.2-0.4 (0.30 in Gillespie's table), and
    // glass and steel spheres on loose quartz sand measured 0.43-0.67 (de
    // Blasio & Saeter 2009): a ball sinks in and ploughs.
    static const GroundMaterial sand{
        "sand", 1600.0, 32.0, 0.0, 0.30, true,
        "a car tyre on loose sand 0.2-0.4 (Engineering ToolBox), 0.30 (Gillespie 1992, p. 117); "
        "glass and steel spheres on loose quartz sand 0.43-0.67 (de Blasio & Saeter 2009)"};
    return sand;
}
const GroundMaterial &groundMaterialOf(Surface surface) {
    switch (surface) {
    case Surface::Rock: return rockMaterial();
    case Surface::Soil: return soilMaterial();
    case Surface::Sand: return sandMaterial();
    }
    return soilMaterial();
}

TerrainField::TerrainField(Grid grid, std::vector<double> rock_top_m, std::vector<double> soil_m,
                           std::vector<double> sand_m, std::vector<double> loose_soil_m,
                           std::vector<float> moisture)
    : TerrainField(grid, Beds::ofRock(rock_top_m), std::move(soil_m), std::move(sand_m),
                   std::move(loose_soil_m), std::move(moisture)) {}

TerrainField::TerrainField(Grid grid, Beds beds, std::vector<double> soil_m,
                           std::vector<double> sand_m, std::vector<double> loose_soil_m,
                           std::vector<float> moisture)
    : grid_(grid), beds_(std::move(beds)), soil_(std::move(soil_m)),
      sand_(std::move(sand_m)), loose_(std::move(loose_soil_m)), moisture_(std::move(moisture)) {
    if (grid_.nx < 2 || grid_.nz < 2 || !(grid_.dx > 0.0))
        throw std::invalid_argument("terrain needs a grid of at least 2 x 2 points with a positive spacing");
    const std::size_t n = grid_.cells();
    if (loose_.empty()) loose_.assign(n, 0.0);
    if (moisture_.empty()) moisture_.assign(n, 0.0F);
    if (beds_.start.size() != n + 1 || beds_.count.size() != n ||
        beds_.kind.size() != beds_.top.size() || beds_.start[n] != beds_.top.size())
        throw std::invalid_argument("terrain needs a bed list per point");
    if (soil_.size() != n || sand_.size() != n || loose_.size() != n || moisture_.size() != n)
        throw std::invalid_argument("terrain needs one value of each layer per point");
    // A layer rounded a hair below zero is a layer of nothing; anything more
    // than rounding below zero is a mistake and is refused below.
    for (std::vector<double> *layer : {&soil_, &sand_, &loose_})
        for (double &v : *layer)
            if (v < 0.0 && v > -1.0e-9) v = 0.0;
    for (std::size_t c = 0; c < n; ++c) {
        if (beds_.count[c] < 1 || beds_.count[c] > beds_.start[c + 1] - beds_.start[c])
            throw std::invalid_argument("every column needs at least one bed of rock");
        for (std::uint32_t k = beds_.start[c]; k < beds_.start[c] + beds_.count[c]; ++k)
            if (!std::isfinite(beds_.top[k]) ||
                (k > beds_.start[c] && beds_.top[k] < beds_.top[k - 1]))
                throw std::invalid_argument("a bed's top is not finite, or is below the bed under it");
        // A hole open to the sky is a hole in the surface, which the height
        // field says on its own; a void is always something with rock over it.
        if (isVoid(static_cast<RunKind>(beds_.kind[beds_.start[c] + beds_.count[c] - 1])))
            throw std::invalid_argument("a column's topmost bed cannot be a void");
        if (!(soil_[c] >= 0.0) || !(sand_[c] >= 0.0) ||
            !(loose_[c] >= 0.0) || !std::isfinite(soil_[c] + sand_[c] + loose_[c]))
            throw std::invalid_argument("a terrain layer is negative or not finite");
    }
    // How far the rock goes down. Every world before this had 2 m of it, which
    // is no earth to mine at all (docs/earth-and-mining-plan.md).
    double lowest_rock = std::numeric_limits<double>::infinity();
    for (std::size_t c = 0; c < n; ++c) {
        lowest_rock = std::min(lowest_rock, rockTop(c));
        for (std::uint32_t k = beds_.start[c]; k < beds_.start[c] + beds_.count[c]; ++k)
            if (isVoid(static_cast<RunKind>(beds_.kind[k]))) { ++workings_; break; }
    }
    floor_ = lowest_rock - kEarthDepthM;
    chunks_x_ = std::max(1, (grid_.nx - 2) / kChunkCells + 1);
    chunks_z_ = std::max(1, (grid_.nz - 2) / kChunkCells + 1);
    baseline_.resize(n);
    for (std::size_t c=0;c<n;++c) baseline_[c]=static_cast<float>(height(c));
    resetLedger();
}

Surface TerrainField::surface(std::size_t c) const {
    // A layer is what the surface IS once it is thick enough to stand on: a
    // film of sand a millimetre deep on a soil bank is a soil bank.
    if (sand_[c] + loose_[c] > 0.02) return sand_[c] >= loose_[c] ? Surface::Sand : Surface::Soil;
    if (soil_[c] + sand_[c] + loose_[c] > 0.02) return Surface::Soil;
    return Surface::Rock;
}

std::optional<TerrainField::Working> TerrainField::workingIn(std::size_t c) const {
    const std::uint32_t from = beds_.start[c];
    for (std::uint32_t k = 0; k < beds_.count[c]; ++k)
        if (isVoid(static_cast<RunKind>(beds_.kind[from + k])))
            return Working{bedBottom(c, k), beds_.top[from + k]};
    return std::nullopt;
}

int TerrainField::runsOf(std::size_t c, Run *out) const {
    int n = 0;
    // The beds first: the lowest goes down to the floor, and nothing is dug
    // below that.
    const std::uint32_t from = beds_.start[c];
    for (std::uint32_t k = 0; k < beds_.count[c] && n < kRunsMost - 2; ++k)
        out[n++] = {static_cast<RunKind>(beds_.kind[from + k]), beds_.top[from + k]};
    if (soil_[c] > 0.0) out[n++] = {RunKind::Soil, rockTop(c) + soil_[c]};
    const double loose = sand_[c] + loose_[c];
    if (loose > 0.0) out[n++] = {sand_[c] >= loose_[c] ? RunKind::Sand : RunKind::LooseSoil, height(c)};
    return n;
}

void TerrainField::takeRockDownTo(std::size_t c, double bottom, Volumes &took) {
    const double area = grid_.dx * grid_.dx;
    const std::uint32_t from = beds_.start[c];
    while (beds_.count[c] > 0) {
        const std::uint32_t k = beds_.count[c] - 1;
        const double top = beds_.top[from + k];
        if (!(top > bottom)) return;
        const double below = bedBottom(c, k);
        addByKind(took, static_cast<RunKind>(beds_.kind[from + k]),
                  (top - std::max(bottom, below)) * area);
        // A bed taken whole goes, unless it is the last one: a column always
        // keeps a bed, and the cut is refused before it reaches the floor.
        if (below > bottom && k > 0) --beds_.count[c];
        else { beds_.top[from + k] = bottom; return; }
    }
}

std::optional<std::size_t> TerrainField::cellAt(double x, double z) const {
    const long i = (column_surface_ || cut_surface_) ? static_cast<long>(std::floor((x-grid_.x0)/grid_.dx+.5)) : std::lround((x - grid_.x0) / grid_.dx);
    const long j = (column_surface_ || cut_surface_) ? static_cast<long>(std::floor((z-grid_.z0)/grid_.dx+.5)) : std::lround((z - grid_.z0) / grid_.dx);
    if (i < 0 || j < 0 || i >= grid_.nx || j >= grid_.nz) return std::nullopt;
    return grid_.at(static_cast<int>(i), static_cast<int>(j));
}

double TerrainField::heightAt(double x, double z) const {
    if (cut_surface_) {
        const int i=std::clamp(static_cast<int>(std::floor((x-grid_.x0)/grid_.dx+.5)),0,grid_.nx-1);
        const int j=std::clamp(static_cast<int>(std::floor((z-grid_.z0)/grid_.dx+.5)),0,grid_.nz-1);
        const auto c=grid_.at(i,j);
        return baselineHeightAt(x,z)+(height(c)-baseline_[c]);
    }
    if (column_surface_) {
        const int i=std::clamp(static_cast<int>(std::floor((x-grid_.x0)/grid_.dx+.5)),0,grid_.nx-1);
        const int j=std::clamp(static_cast<int>(std::floor((z-grid_.z0)/grid_.dx+.5)),0,grid_.nz-1);
        return height(grid_.at(i,j));
    }
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

double TerrainField::baselineHeightAt(double x, double z) const {
    const double fx=std::clamp((x-grid_.x0)/grid_.dx,0.0,grid_.nx-1.0);
    const double fz=std::clamp((z-grid_.z0)/grid_.dx,0.0,grid_.nz-1.0);
    const int i=std::min(grid_.nx-2,static_cast<int>(fx)),j=std::min(grid_.nz-2,static_cast<int>(fz));
    const double u=fx-i,v=fz-j;
    const double a=baseline_[grid_.at(i,j)],b=baseline_[grid_.at(i+1,j)];
    const double c=baseline_[grid_.at(i,j+1)],d=baseline_[grid_.at(i+1,j+1)];
    return u>=v ? a+u*(b-a)+v*(d-b) : a+v*(c-a)+u*(d-c);
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
    if(column_surface_ || cut_surface_)for(const auto [di,dj]:{std::pair{-1,0},std::pair{1,0},std::pair{0,-1},std::pair{0,1}}) {
        const int x=i+di,z=j+dj;
        if(x>=0 && z>=0 && x<grid_.nx && z<grid_.nz)
            dirty_chunks_.insert(std::min(z/kChunkCells,chunks_z_-1)*chunks_x_+std::min(x/kChunkCells,chunks_x_-1));
    }
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

Volumes TerrainField::wouldStrip(std::size_t c, double thickness) const {
    // strip()'s own arithmetic, on nothing.
    Volumes would;
    const double area = grid_.dx * grid_.dx;
    double left = std::max(0.0, thickness);
    const double loose = sand_[c] + loose_[c];
    if (left > 0.0 && loose > 0.0) {
        const double take = std::min(left, loose);
        const double from_sand = take * (sand_[c] / loose);
        would.sand_m3 += from_sand * area;
        would.soil_m3 += (take - from_sand) * area;
        left -= take;
    }
    if (left > 0.0 && soil_[c] > 0.0) would.soil_m3 += std::min(left, soil_[c]) * area;
    return would;
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

std::vector<std::size_t> TerrainField::columnsAlong(double ax, double az, double bx, double bz,
                                                    double width_m) const {
    std::vector<std::size_t> out;
    if (!(width_m > 0.0) || !std::isfinite(ax + az + bx + bz + width_m)) return out;
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
            out.push_back(grid_.at(i, j));
        }
    return out;
}

EditReport TerrainField::dig(double ax, double az, double bx, double bz, double width_m,
                             double depth_m, double max_kg) {
    EditReport report;
    if (!(width_m > 0.0) || !(depth_m > 0.0) || !std::isfinite(ax + az + bx + bz + width_m + depth_m))
        throw std::invalid_argument("a dig needs two points, a positive width and a positive depth");
    if (std::isnan(max_kg) || max_kg < 0.0)
        throw std::invalid_argument("what a dig may take out is zero or more kilograms");
    // The same columns, in the same order, columnsAlong names.
    const std::vector<std::size_t> columns = columnsAlong(ax, az, bx, bz, width_m);
    // As deep as was asked, unless that is more than may come out: then as deep
    // as takes out exactly that much. What comes out only grows with depth, so
    // the depth is found by halving; nothing is touched until it is known.
    if (std::isfinite(max_kg)) {
        // Added up the way the report below adds it up -- the volumes column by
        // column, and the mass from their totals -- so that what is found to fit
        // is, to the last bit, what is then said to have come out.
        const auto massAt = [&](double depth) {
            Volumes would;
            for (const std::size_t c : columns) {
                const Volumes column = wouldStrip(c, depth);
                would.sand_m3 += column.sand_m3;
                would.soil_m3 += column.soil_m3;
            }
            return would.sand_m3 * sandMaterial().density_kg_m3 + would.soil_m3 * soilMaterial().density_kg_m3;
        };
        if (massAt(depth_m) > max_kg) {
            report.limited = true;
            double holds = 0.0, too_deep = depth_m;
            for (int halving = 0; halving < 60; ++halving) {
                const double middle = 0.5 * (holds + too_deep);
                (massAt(middle) > max_kg ? too_deep : holds) = middle;
            }
            depth_m = holds;
        }
    }
    report.depth_m = depth_m;
    if (!(depth_m > 0.0)) return report;
    for (const std::size_t c : columns) {
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

EditReport TerrainField::breakOut(double x, double z, double from_m, double to_m) {
    EditReport report;
    const auto cell = cellAt(x, z);
    if (!cell) throw std::invalid_argument("that point is not on the ground");
    if (!std::isfinite(from_m) || !std::isfinite(to_m))
        throw std::invalid_argument("a working needs two finite heights");
    const std::size_t c = *cell;
    const double area = grid_.dx * grid_.dx;
    // Cell-quantised, as every void is: a working is made of cubes, and its
    // floor and roof land where the collider's two extra height fields can say
    // them exactly.
    const double q = grid_.dx;
    double lo = std::floor(std::min(from_m, to_m) / q) * q;
    double hi = std::ceil(std::max(from_m, to_m) / q) * q;
    lo = std::max(lo, floor_ + q);          // never through the bottom of the world
    const double top = rockTop(c);
    if (!(hi > lo) || !(lo < top)) return report;
    hi = std::min(hi, top);

    // Broken out to daylight, or near enough: this is an open cut, not a hole
    // with rock over it, and a column's topmost bed is never a void. Everything
    // over the rock comes off with it.
    if (hi >= top - 1.0e-9) {
        const Volumes film = strip(c, soil_[c] + sand_[c] + loose_[c]);
        report.moved.sand_m3 += film.sand_m3;
        report.moved.soil_m3 += film.soil_m3;
        takeRockDownTo(c, lo, report.moved);
        report.cells.push_back(c);
        touched(c);
        ledger_.dug.rock_m3 += report.moved.rock_m3;
        ledger_.dug.sand_m3 += report.moved.sand_m3;
        ledger_.dug.soil_m3 += report.moved.soil_m3;
        report.depth_m = top - lo;
        markChanged(report.cells);
        return report;
    }

    // A hole with rock over it: the beds it passes through are split into what
    // is under the working, the working, and what is over it. A column with no
    // room to say that keeps its rock -- which is a refusal, not a silence.
    const std::uint32_t from = beds_.start[c];
    const std::uint32_t room = beds_.start[c + 1] - from;
    std::uint8_t kind[kRunsMost];
    double bed_top[kRunsMost];
    std::uint32_t n = 0;
    double below = floor_;
    const auto push = [&](std::uint8_t k, double t) {
        if (n > 0 && kind[n - 1] == k) { bed_top[n - 1] = t; return; }
        if (n + 1 >= static_cast<std::uint32_t>(kRunsMost)) return;
        kind[n] = k; bed_top[n] = t; ++n;
    };
    for (std::uint32_t b = 0; b < beds_.count[c]; ++b) {
        const double t = beds_.top[from + b];
        const std::uint8_t k = beds_.kind[from + b];
        const double bottom = below;
        if (t <= lo) { push(k, t); below = t; continue; }
        if (below < lo) { push(k, lo); below = lo; }
        // What this bed loses to the working, counted as what it is made of.
        // A bed that is already a void gives nothing: there is nothing in it.
        const double gone = std::min(t, hi) - std::max(bottom, lo);
        if (gone > 0.0) addByKind(report.moved, static_cast<RunKind>(k), gone * area);
        if (t <= hi) { below = std::max(below, std::min(t, hi)); continue; }
        if (below < hi) { push(static_cast<std::uint8_t>(RunKind::Void), hi); below = hi; }
        push(k, t);
        below = t;
    }
    if (n == 0 || n > room) {
        throw std::invalid_argument("there is no room left in that column for another working");
    }
    const bool was_working = workingIn(c).has_value();
    for (std::uint32_t b = 0; b < n; ++b) {
        beds_.kind[from + b] = kind[b];
        beds_.top[from + b] = bed_top[b];
    }
    beds_.count[c] = n;
    if (!was_working) ++workings_;
    ledger_.dug.rock_m3 += report.moved.rock_m3;
    ledger_.dug.sand_m3 += report.moved.sand_m3;
    ledger_.dug.soil_m3 += report.moved.soil_m3;
    report.cells.push_back(c);
    report.depth_m = hi - lo;
    touched(c);
    markChanged(report.cells);
    return report;
}

RunKind TerrainField::kindAt(std::size_t c, double height_m) const {
    const std::uint32_t from = beds_.start[c];
    for (std::uint32_t k = 0; k < beds_.count[c]; ++k)
        if (height_m <= beds_.top[from + k]) return static_cast<RunKind>(beds_.kind[from + k]);
    // Above the rock: whatever is lying on it.
    const double loose = sand_[c] + loose_[c];
    if (loose > 0.0 && height_m > rockTop(c) + soil_[c])
        return sand_[c] >= loose_[c] ? RunKind::Sand : RunKind::LooseSoil;
    if (soil_[c] > 0.0) return RunKind::Soil;
    return static_cast<RunKind>(beds_.kind[from + beds_.count[c] - 1]);
}

double TerrainField::brokenShare(std::size_t c) const {
    const auto found = chipped_.find(c);
    if (found == chipped_.end()) return 0.0;
    const double holds = cellRockM3(c, (found->second.level + 0.5) * grid_.dx);
    return holds > 0.0 ? std::clamp(found->second.m3 / holds, 0.0, 1.0) : 0.0;
}

double TerrainField::cellRockM3(std::size_t c, double at_height_m) const {
    const double q = grid_.dx;
    // The band the height falls in, counted (lo, hi]: a point pressing on a
    // surface works the cell UNDER it, not the empty one above. A blow landing
    // at or over the top of the rock works the topmost cell of it -- a tip
    // resting on a hillside is a hair above the rock as often as a hair into it,
    // and that is the same blow.
    const double lo = std::max((std::ceil(std::min(at_height_m, rockTop(c)) / q) - 1.0) * q, floor_);
    const double hi = std::min(lo + q, rockTop(c));
    if (!(hi > lo)) return 0.0;
    // Everything in the band that is not a void: what has to be broken to take
    // the cell out. A band that straddles the top of the rock holds only the
    // part below it, which is why a first bite at a hillside is cheaper than a
    // cell.
    double solid = 0.0, below = floor_;
    const std::uint32_t from = beds_.start[c];
    for (std::uint32_t b = 0; b < beds_.count[c]; ++b) {
        const double top = beds_.top[from + b];
        const double overlap = std::min(top, hi) - std::max(below, lo);
        if (overlap > 0.0 && static_cast<RunKind>(beds_.kind[from + b]) != RunKind::Void)
            solid += overlap;
        below = top;
        if (below >= hi) break;
    }
    return solid * grid_.dx * grid_.dx;
}

TerrainField::Chipped TerrainField::chip(double x, double z, double at_height_m, double volume_m3,
                                         double rock_budget_m3) {
    Chipped out;
    const auto cell = cellAt(x, z);
    if (!cell || !(volume_m3 > 0.0) || !std::isfinite(at_height_m)) return out;
    const std::size_t c = *cell;
    const double q = grid_.dx;
    // The cell the blow landed in, named by its level so that working across to
    // another one does not spend what was paid here.
    const int level = static_cast<int>(std::ceil(std::min(at_height_m, rockTop(c)) / q)) - 1;
    const double holds = cellRockM3(c, at_height_m);
    if (!(holds > 0.0)) return out;      // no rock there to break
    Owed &owed = chipped_[c];
    if (owed.level != level) owed = Owed{level, 0.0};
    owed.m3 += volume_m3;
    if (owed.m3 + 1.0e-12 < holds) {
        out.broken = owed.m3 / holds;
        return out;
    }
    // Paid for. It only comes out if it can be carried away: a cell of rock is
    // 37 kg, and one nobody can lift stays in the wall with the work still
    // credited to it.
    if (holds > rock_budget_m3) {
        out.broken = 1.0;
        out.full = true;
        return out;
    }
    const double lo = std::max(static_cast<double>(level) * q, floor_);
    out.edit = breakOut(grid_.xOf(static_cast<int>(c % static_cast<std::size_t>(grid_.nx))),
                        grid_.zOf(static_cast<int>(c / static_cast<std::size_t>(grid_.nx))),
                        lo, std::min(lo + q, rockTop(c)));
    // What it cost is what was in it, not a nominal cell: a bite that trims a
    // hillside to the lattice is smaller than a cell and is charged as such, and
    // anything overpaid is credited to the next one.
    owed.m3 -= holds;
    if (!(std::abs(owed.m3) > 1.0e-15)) chipped_.erase(c);
    out.broken = brokenShare(c);
    return out;
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
            lowest = std::min(lowest, rockTop(c));
            mean += rockTop(c);
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
    // Every bed the cut would reach has to be rock, because rock is the only
    // kind the ledger counts. A block of anything else is said, not guessed.
    for (int j = j0; j < j0 + cells_z; ++j)
        for (int i = i0; i < i0 + cells_x; ++i) {
            const std::size_t c = grid_.at(i, j);
            const std::uint32_t from = beds_.start[c];
            for (std::uint32_t k = 0; k < beds_.count[c]; ++k) {
                if (!(beds_.top[from + k] > bottom)) continue;
                const auto kind = static_cast<RunKind>(beds_.kind[from + k]);
                if (isVoid(kind))
                    return fail("there is a working under there: a block cut out of rock with a "
                                "hole in it is not a block");
                if (!isRockLike(kind))
                    return fail("the rock there is not all rock: cutting a block out of a bed of "
                                "clay or ore is not accounted for yet");
            }
        }
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
            Volumes out;
            takeRockDownTo(c, bottom, out);
            rock += out.rock_m3;
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
        const std::uint32_t from = beds_.start[c];
        for (std::uint32_t k = 0; k < beds_.count[c]; ++k)
            addByKind(v, static_cast<RunKind>(beds_.kind[from + k]),
                      (beds_.top[from + k] - bedBottom(c, k)) * area);
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
