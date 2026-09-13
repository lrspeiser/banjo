#include "water/ShallowWater.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo::water {
namespace {

constexpr double kNoObstacle = -std::numeric_limits<double>::infinity();

// Depth-averaged velocity from discharge and depth, damped rather than divided
// out in a film too thin to have one (Kurganov & Petrova 2007). For any column
// deeper than `film` it is q / h exactly, and for q = 0 it is 0 exactly, which
// is what keeps a lake at rest bit for bit.
inline double speedOf(double q, double h, double dry, double film) {
    if (!(h > dry)) return 0.0;
    const double h2 = h * h;
    const double h4 = h2 * h2;
    const double f2 = film * film;
    const double f4 = f2 * f2;
    if (h4 >= f4) return q / h;
    return 1.4142135623730951 * h * q / std::sqrt(h4 + f4);
}

// One face, hydrostatically reconstructed (Audusse et al. 2004) with a Rusanov
// flux. L is the side the face's normal points away from.
//
//   mass   the discharge across the face, per unit width
//   left   the normal momentum flux cell L loses  (F - g hL*^2 / 2)
//   right  the normal momentum flux cell R gains  (F - g hR*^2 / 2)
//   along  the tangential momentum flux
//
// The two momentum fluxes differ by exactly the pressure the bed step holds
// back, which is the whole of the well-balancing: each cell subtracts the
// hydrostatic pressure of its OWN reconstructed column, so a lake at rest --
// equal surfaces on both sides, no velocity -- produces the same number twice
// and subtracts it from itself, and the flux is exactly zero.
struct Face {
    double mass{}, left{}, right{}, along{};
};

inline Face faceFlux(double g, double dry, double film,
                     double eta_l, double bed_l, double qn_l, double qt_l,
                     double eta_r, double bed_r, double qn_r, double qt_r) {
    Face out;
    const double top = std::max(bed_l, bed_r);
    const double hs_l = std::max(0.0, eta_l - top);
    const double hs_r = std::max(0.0, eta_r - top);
    if (!(hs_l > 0.0) && !(hs_r > 0.0)) return out;
    const double h_l = eta_l - bed_l;
    const double h_r = eta_r - bed_r;
    const double u_l = speedOf(qn_l, h_l, dry, film);
    const double v_l = speedOf(qt_l, h_l, dry, film);
    const double u_r = speedOf(qn_r, h_r, dry, film);
    const double v_r = speedOf(qt_r, h_r, dry, film);
    const double a = std::max(std::abs(u_l) + std::sqrt(g * hs_l),
                              std::abs(u_r) + std::sqrt(g * hs_r));
    const double q_l = hs_l * u_l;
    const double q_r = hs_r * u_r;
    const double p_l = 0.5 * g * hs_l * hs_l;
    const double p_r = 0.5 * g * hs_r * hs_r;
    out.mass = 0.5 * (q_l + q_r) - 0.5 * a * (hs_r - hs_l);
    const double momentum = 0.5 * (q_l * u_l + p_l + q_r * u_r + p_r) - 0.5 * a * (q_r - q_l);
    out.left = momentum - p_l;
    out.right = momentum - p_r;
    out.along = 0.5 * (q_l * v_l + q_r * v_r) - 0.5 * a * (hs_r * v_r - hs_l * v_l);
    return out;
}

} // namespace

ShallowWater::ShallowWater(Grid grid, std::vector<double> terrain_m, Settings settings)
    : grid_(grid), settings_(settings), terrain_(std::move(terrain_m)) {
    if (grid_.nx < 2 || grid_.nz < 2 || !(grid_.dx > 0.0))
        throw std::invalid_argument("water needs a grid of at least 2 x 2 cells with a positive size");
    if (terrain_.size() != grid_.cells())
        throw std::invalid_argument("water needs one ground height per cell");
    for (const double t : terrain_)
        if (!std::isfinite(t)) throw std::invalid_argument("the ground under the water is not finite");
    if (!(settings_.cfl > 0.0 && settings_.cfl <= 0.25))
        throw std::invalid_argument("the CFL fraction is above 0 and at most 1/4 for this scheme");
    const std::size_t n = grid_.cells();
    obstacle_.assign(n, kNoObstacle);
    bed_ = terrain_;
    eta_ = terrain_;
    qx_.assign(n, 0.0);
    qz_.assign(n, 0.0);
    d_eta_.assign(n, 0.0);
    d_qx_.assign(n, 0.0);
    d_qz_.assign(n, 0.0);
    impulse_x_.assign(n, 0.0);
    impulse_z_.assign(n, 0.0);
    west_.assign(static_cast<std::size_t>(grid_.nz), 0);
    east_.assign(static_cast<std::size_t>(grid_.nz), 0);
    south_.assign(static_cast<std::size_t>(grid_.nx), 0);
    north_.assign(static_cast<std::size_t>(grid_.nx), 0);
    settings_.tile = std::max(4, settings_.tile);
    tiles_x_ = (grid_.nx + settings_.tile - 1) / settings_.tile;
    tiles_z_ = (grid_.nz + settings_.tile - 1) / settings_.tile;
    const std::size_t tiles = static_cast<std::size_t>(tiles_x_) * static_cast<std::size_t>(tiles_z_);
    tile_wet_.assign(tiles, 0);
    tile_active_.assign(tiles, 0);
    tile_always_.assign(tiles, 0);
    stats_.tiles = tiles;
    refreshTiles();
}

double ShallowWater::velocityX(std::size_t cell) const {
    return speedOf(qx_[cell], depth(cell), settings_.dry_m, settings_.film_m);
}

double ShallowWater::velocityZ(std::size_t cell) const {
    return speedOf(qz_[cell], depth(cell), settings_.dry_m, settings_.film_m);
}

void ShallowWater::setDepth(std::size_t cell, double depth_m) {
    eta_[cell] = bed_[cell] + std::max(0.0, depth_m);
    if (!(depth_m > 0.0)) { qx_[cell] = 0.0; qz_[cell] = 0.0; }
    tiles_dirty_ = true;
    speed_known_ = false;
}

void ShallowWater::setSurface(std::size_t cell, double surface_m) {
    eta_[cell] = std::max(bed_[cell], surface_m);
    if (!(eta_[cell] > bed_[cell])) { qx_[cell] = 0.0; qz_[cell] = 0.0; }
    tiles_dirty_ = true;
    speed_known_ = false;
}

void ShallowWater::setDischarge(std::size_t cell, double qx_m2_s, double qz_m2_s) {
    qx_[cell] = qx_m2_s;
    qz_[cell] = qz_m2_s;
    speed_known_ = false;
}

// Water that has to leave a column because something solid now stands where it
// was. It goes to the nearest column with nothing resting in it -- the lowest
// surface of the nearest ring, because that is the way water goes -- so it is
// moved, never lost. Only a column walled in on every side for eight cells keeps
// it, standing on top of what displaced it, and then it simply runs off.
void ShallowWater::displace(std::size_t cell, double volume_m3) {
    if (!(volume_m3 > 0.0)) return;
    const int ci = static_cast<int>(cell % static_cast<std::size_t>(grid_.nx));
    const int cj = static_cast<int>(cell / static_cast<std::size_t>(grid_.nx));
    for (int ring = 1; ring <= 8; ++ring) {
        std::size_t best = cell;
        double lowest = std::numeric_limits<double>::infinity();
        for (int dj = -ring; dj <= ring; ++dj)
            for (int di = -ring; di <= ring; ++di) {
                if (std::max(std::abs(di), std::abs(dj)) != ring) continue;
                const int i = ci + di, j = cj + dj;
                if (i < 0 || j < 0 || i >= grid_.nx || j >= grid_.nz) continue;
                const std::size_t n = grid_.at(i, j);
                if (obstacle_[n] > terrain_[n]) continue;   // something is standing there too
                if (eta_[n] < lowest) { lowest = eta_[n]; best = n; }
            }
        if (best != cell) {
            eta_[best] += volume_m3 / faceArea();
            tiles_dirty_ = true;
            return;
        }
    }
    eta_[cell] += volume_m3 / faceArea();
    tiles_dirty_ = true;
}

namespace {
// Move a column's bed, keeping its water. Returns the depth that no longer
// fits over the new bed, to be put somewhere else.
double moveBed(double &eta, double &bed, double &qx, double &qz, double new_bed) {
    const double old_bed = bed;
    if (new_bed == old_bed) return 0.0;
    const double h = eta - old_bed;
    if (new_bed < old_bed) {
        // Dug out, or something lifted off it: the same water, lower down.
        bed = new_bed;
        eta = new_bed + h;
        return 0.0;
    }
    bed = new_bed;
    if (eta >= new_bed) {
        // The water still covers it. The surface stays exactly where it is;
        // what the solid now occupies has to go.
        const double keep = eta - new_bed;
        if (h > 0.0) {
            const double scale = keep / h;
            qx *= scale;
            qz *= scale;
        }
        return h - keep;
    }
    eta = new_bed;
    qx = 0.0;
    qz = 0.0;
    return std::max(0.0, h);
}
} // namespace

void ShallowWater::setTerrain(std::size_t cell, double terrain_m) {
    if (!std::isfinite(terrain_m)) throw std::invalid_argument("ground height is not finite");
    terrain_[cell] = terrain_m;
    const double target = std::max(terrain_m, obstacle_[cell]);
    const double spill = moveBed(eta_[cell], bed_[cell], qx_[cell], qz_[cell], target);
    if (spill > 0.0) displace(cell, spill * faceArea());
    tiles_dirty_ = true;
    speed_known_ = false;
}

void ShallowWater::setObstacles(const std::vector<double> &top_m) {
    if (top_m.size() != grid_.cells()) throw std::invalid_argument("one obstacle top per cell");
    // Every obstacle first, then the water: displaced water must not be sent
    // into a column that is about to be filled by another block of the same
    // dam.
    std::vector<std::size_t> raised;
    for (std::size_t c = 0; c < top_m.size(); ++c) {
        obstacle_[c] = top_m[c];
        const double target = std::max(terrain_[c], top_m[c]);
        if (target > bed_[c]) raised.push_back(c);
        else if (target < bed_[c]) (void)moveBed(eta_[c], bed_[c], qx_[c], qz_[c], target);
    }
    for (const std::size_t c : raised) {
        const double target = std::max(terrain_[c], obstacle_[c]);
        const double spill = moveBed(eta_[c], bed_[c], qx_[c], qz_[c], target);
        if (spill > 0.0) displace(c, spill * faceArea());
    }
    tiles_dirty_ = true;
    speed_known_ = false;
}

namespace {
std::vector<int> &edgeOf(Edge edge, std::vector<int> &west, std::vector<int> &east,
                         std::vector<int> &south, std::vector<int> &north) {
    switch (edge) {
    case Edge::West: return west;
    case Edge::East: return east;
    case Edge::South: return south;
    case Edge::North: return north;
    }
    return west;
}
} // namespace

void ShallowWater::addInflow(const Inflow &inflow) {
    std::vector<int> &faces = edgeOf(inflow.edge, west_, east_, south_, north_);
    if (inflow.from < 0 || inflow.to < inflow.from || inflow.to >= static_cast<int>(faces.size()))
        throw std::invalid_argument("an inflow's cells are outside its edge");
    if (!(inflow.discharge_m3_s >= 0.0) || !std::isfinite(inflow.discharge_m3_s))
        throw std::invalid_argument("an inflow's discharge is zero or more cubic metres a second");
    inflows_.push_back(inflow);
    const int marker = static_cast<int>(inflows_.size());
    for (int k = inflow.from; k <= inflow.to; ++k) {
        faces[static_cast<std::size_t>(k)] = marker;
        // A source is always computed: it is where water starts, dry or not.
        int i = 0, j = 0;
        switch (inflow.edge) {
        case Edge::West: i = 0; j = k; break;
        case Edge::East: i = grid_.nx - 1; j = k; break;
        case Edge::South: i = k; j = 0; break;
        case Edge::North: i = k; j = grid_.nz - 1; break;
        }
        tile_always_[static_cast<std::size_t>(j / settings_.tile) * static_cast<std::size_t>(tiles_x_) +
                     static_cast<std::size_t>(i / settings_.tile)] = 1;
    }
    tiles_dirty_ = true;
}

void ShallowWater::addOutflow(const Outflow &outflow) {
    std::vector<int> &faces = edgeOf(outflow.edge, west_, east_, south_, north_);
    if (outflow.from < 0 || outflow.to < outflow.from || outflow.to >= static_cast<int>(faces.size()))
        throw std::invalid_argument("an outflow's cells are outside its edge");
    outflows_.push_back(outflow);
    const int marker = -static_cast<int>(outflows_.size());
    for (int k = outflow.from; k <= outflow.to; ++k) faces[static_cast<std::size_t>(k)] = marker;
}

bool ShallowWater::setInflow(const std::string &name, double discharge_m3_s) {
    if (!(discharge_m3_s >= 0.0) || !std::isfinite(discharge_m3_s)) return false;
    for (Inflow &inflow : inflows_)
        if (inflow.name == name) { inflow.discharge_m3_s = discharge_m3_s; return true; }
    return false;
}

void ShallowWater::addImpulse(std::size_t cell, double jx_n_s, double jz_n_s) {
    if (cell >= grid_.cells() || !std::isfinite(jx_n_s) || !std::isfinite(jz_n_s)) return;
    if (impulse_x_[cell] == 0.0 && impulse_z_[cell] == 0.0) impulse_cells_.push_back(cell);
    impulse_x_[cell] += jx_n_s;
    impulse_z_[cell] += jz_n_s;
    impulses_pending_ = true;
}

void ShallowWater::refreshTiles() {
    const int t = settings_.tile;
    std::fill(tile_wet_.begin(), tile_wet_.end(), std::uint8_t{0});
    for (int j = 0; j < grid_.nz; ++j)
        for (int i = 0; i < grid_.nx; ++i)
            if (eta_[grid_.at(i, j)] - bed_[grid_.at(i, j)] > settings_.dry_m)
                tile_wet_[static_cast<std::size_t>(j / t) * static_cast<std::size_t>(tiles_x_) +
                          static_cast<std::size_t>(i / t)] = 1;
    // A tile is computed when it or any tile touching it holds water: water
    // can only arrive from next door.
    std::size_t active = 0;
    for (int tz = 0; tz < tiles_z_; ++tz)
        for (int tx = 0; tx < tiles_x_; ++tx) {
            std::uint8_t on = tile_always_[static_cast<std::size_t>(tz) * static_cast<std::size_t>(tiles_x_) +
                                           static_cast<std::size_t>(tx)];
            for (int dz = -1; dz <= 1 && !on; ++dz)
                for (int dx = -1; dx <= 1 && !on; ++dx) {
                    const int x = tx + dx, z = tz + dz;
                    if (x < 0 || z < 0 || x >= tiles_x_ || z >= tiles_z_) continue;
                    on = tile_wet_[static_cast<std::size_t>(z) * static_cast<std::size_t>(tiles_x_) +
                                   static_cast<std::size_t>(x)];
                }
            tile_active_[static_cast<std::size_t>(tz) * static_cast<std::size_t>(tiles_x_) +
                         static_cast<std::size_t>(tx)] = on;
            active += on;
        }
    stats_.active_tiles = active;
    tiles_dirty_ = false;
}

double ShallowWater::waveSpeed() const {
    const double g = settings_.gravity_m_s2;
    const int t = settings_.tile;
    double fastest = 0.0;
    for (int tz = 0; tz < tiles_z_; ++tz)
        for (int tx = 0; tx < tiles_x_; ++tx) {
            if (!tile_active_[static_cast<std::size_t>(tz) * static_cast<std::size_t>(tiles_x_) +
                              static_cast<std::size_t>(tx)]) continue;
            const int i1 = std::min(grid_.nx, (tx + 1) * t), j1 = std::min(grid_.nz, (tz + 1) * t);
            for (int j = tz * t; j < j1; ++j)
                for (int i = tx * t; i < i1; ++i) {
                    const std::size_t c = grid_.at(i, j);
                    const double h = eta_[c] - bed_[c];
                    if (!(h > settings_.dry_m)) continue;
                    const double c0 = std::sqrt(g * h);
                    const double u = std::abs(speedOf(qx_[c], h, settings_.dry_m, settings_.film_m));
                    const double v = std::abs(speedOf(qz_[c], h, settings_.dry_m, settings_.film_m));
                    fastest = std::max(fastest, std::max(u, v) + c0);
                }
        }
    // The inflows' own water arrives at a speed the columns do not show yet.
    for (const Inflow &inflow : inflows_) {
        const int faces = inflow.to - inflow.from + 1;
        const double q = inflow.discharge_m3_s / (faces * grid_.dx);
        const double h = std::cbrt(q * q / g);
        if (h > 0.0) fastest = std::max(fastest, q / h + std::sqrt(g * h));
    }
    return fastest;
}

int ShallowWater::advance(double dt_s) {
    if (!(dt_s > 0.0) || !std::isfinite(dt_s)) return 0;
    if (tiles_dirty_) refreshTiles();
    double remaining = dt_s;
    int taken = 0;
    while (remaining > 0.0) {
        if (!speed_known_) { speed_ = waveSpeed(); speed_known_ = true; }
        double longest = settings_.max_step_s;
        if (speed_ > 0.0) longest = std::min(longest, settings_.cfl * grid_.dx / speed_);
        // Equal pieces of what is left, never a sliver at the end.
        const double pieces = std::ceil(remaining / longest - 1.0e-9);
        const double step = pieces <= 1.0 ? remaining : remaining / pieces;
        substep(step);
        remaining = pieces <= 1.0 ? 0.0 : remaining - step;
        ++taken;
    }
    return taken;
}

void ShallowWater::substep(double dt) {
    const double g = settings_.gravity_m_s2;
    const double dry = settings_.dry_m;
    const double film = settings_.film_m;
    const double dx = grid_.dx;
    const double area = faceArea();
    const int t = settings_.tile;
    const int nx = grid_.nx, nz = grid_.nz;
    const auto tileOf = [&](int i, int j) {
        return static_cast<std::size_t>(j / t) * static_cast<std::size_t>(tiles_x_) +
               static_cast<std::size_t>(i / t);
    };

    // What bodies gave the water since the last substep. A column too shallow
    // to carry it would be given an absurd speed; that share is counted as
    // dropped rather than silently turned into a jet.
    if (impulses_pending_) {
        const double rho = settings_.density_kg_m3;
        for (const std::size_t c : impulse_cells_) {
            const double h = eta_[c] - bed_[c];
            if (h > 0.01) {
                qx_[c] += impulse_x_[c] / (rho * area);
                qz_[c] += impulse_z_[c] / (rho * area);
                ledger_.impulse_in_x_n_s += impulse_x_[c];
                ledger_.impulse_in_z_n_s += impulse_z_[c];
            } else {
                ledger_.impulse_dropped_n_s += std::hypot(impulse_x_[c], impulse_z_[c]);
            }
            impulse_x_[c] = 0.0;
            impulse_z_[c] = 0.0;
        }
        impulse_cells_.clear();
        impulses_pending_ = false;
        speed_known_ = false;
    }

    // Accumulators, zeroed where they will be written.
    for (int tz = 0; tz < tiles_z_; ++tz)
        for (int tx = 0; tx < tiles_x_; ++tx) {
            if (!tile_active_[static_cast<std::size_t>(tz) * static_cast<std::size_t>(tiles_x_) +
                              static_cast<std::size_t>(tx)]) continue;
            const int i1 = std::min(nx, (tx + 1) * t), j1 = std::min(nz, (tz + 1) * t);
            for (int j = tz * t; j < j1; ++j)
                for (int i = tx * t; i < i1; ++i) {
                    const std::size_t c = grid_.at(i, j);
                    d_eta_[c] = 0.0;
                    d_qx_[c] = 0.0;
                    d_qz_[c] = 0.0;
                }
        }

    double came_in = 0.0, went_out = 0.0;   // per unit time, m^3/s
    // A boundary face. `inward` is +1 when the domain is on the high side of
    // the face (west and south edges), -1 when it is on the low side. The
    // state is the cell's; `qn` is its discharge along the axis through the
    // face and `qt` along the face.
    const auto boundary = [&](int marker, int inward, std::size_t c, double qn, double qt,
                              double &d_mass, double &d_n, double &d_t) {
        const double h = eta_[c] - bed_[c];
        if (marker > 0) {
            const Inflow &in = inflows_[static_cast<std::size_t>(marker - 1)];
            const int faces = in.to - in.from + 1;
            const double q = in.discharge_m3_s / (faces * dx);
            if (!(q > 0.0)) return;
            // Water arriving at this rate is at least critically deep: it
            // cannot be thinner than that and still carry the discharge.
            const double critical = std::cbrt(q * q / g);
            const double h_ref = std::max(h, critical);
            // Flux along the axis: positive into the domain for the west and
            // south edges, negative for the east and north.
            const double mass = inward * q;
            const double momentum = q * q / h_ref;   // the pressure cancels
            // A cell on the high side of the face GAINS what crosses it.
            if (inward > 0) { d_mass -= mass; d_n -= momentum; }
            else { d_mass += mass; d_n += momentum; }
            came_in += q * dx;
            return;
        }
        if (marker < 0) {
            // A free outfall: the river leaves over its own bed at the edge,
            // as over a broad-crested weir. Water standing at the mouth is
            // not held there -- nothing is on the other side to hold it -- so
            // it leaves at no less than the critical discharge for its depth,
            //
            //     q = (2/3)^(3/2) sqrt(g) h^(3/2),
            //
            // and faster if it is already running out faster than that. The
            // face carries the pressure of the critical depth, 2h/3, not the
            // column's own: the missing pressure on the far side is what
            // draws the water out. Nothing comes back in.
            if (!(h > dry)) return;
            const double u = speedOf(qn, h, dry, film);
            const double v = speedOf(qt, h, dry, film);
            const double outward_u = inward > 0 ? -u : u;
            const double weir = 0.5443310539518174 * std::sqrt(g) * h * std::sqrt(h);
            const double q_out = std::max(h * std::max(0.0, outward_u), weir);
            const double speed_out = q_out / h;
            const double face = (2.0 / 3.0) * h;
            // Normal momentum flux through the face and the pressure it
            // carries, less the column's own pressure (the reconstruction's
            // convention: each cell subtracts its own hydrostatic push).
            const double momentum = q_out * speed_out + 0.5 * g * face * face - 0.5 * g * h * h;
            // Signed along the axis: out of a west or south edge is -axis. The
            // water that leaves takes its sideways momentum with it.
            const double mass = inward > 0 ? -q_out : q_out;
            const double along = mass * v;
            if (inward > 0) { d_mass -= mass; d_n -= momentum; d_t -= along; }
            else { d_mass += mass; d_n += momentum; d_t += along; }
            went_out += q_out * dx;
            return;
        }
        // A wall: the mirror image of the column on the other side.
        const Face f = inward > 0
            ? faceFlux(g, dry, film, eta_[c], bed_[c], -qn, qt, eta_[c], bed_[c], qn, qt)
            : faceFlux(g, dry, film, eta_[c], bed_[c], qn, qt, eta_[c], bed_[c], -qn, qt);
        if (inward > 0) { d_mass -= f.mass; d_n -= f.right; d_t -= f.along; }
        else { d_mass += f.mass; d_n += f.left; d_t += f.along; }
    };

    std::size_t computed = 0;
    for (int tz = 0; tz < tiles_z_; ++tz)
        for (int tx = 0; tx < tiles_x_; ++tx) {
            if (!tile_active_[static_cast<std::size_t>(tz) * static_cast<std::size_t>(tiles_x_) +
                              static_cast<std::size_t>(tx)]) continue;
            const int i1 = std::min(nx, (tx + 1) * t), j1 = std::min(nz, (tz + 1) * t);
            for (int j = tz * t; j < j1; ++j)
                for (int i = tx * t; i < i1; ++i) {
                    const std::size_t c = grid_.at(i, j);
                    ++computed;
                    // East face.
                    if (i + 1 < nx) {
                        const std::size_t e = c + 1;
                        const Face f = faceFlux(g, dry, film, eta_[c], bed_[c], qx_[c], qz_[c],
                                                eta_[e], bed_[e], qx_[e], qz_[e]);
                        d_eta_[c] += f.mass; d_qx_[c] += f.left; d_qz_[c] += f.along;
                        if (tile_active_[tileOf(i + 1, j)]) {
                            d_eta_[e] -= f.mass; d_qx_[e] -= f.right; d_qz_[e] -= f.along;
                        }
                    } else {
                        boundary(east_[static_cast<std::size_t>(j)], -1, c, qx_[c], qz_[c],
                                 d_eta_[c], d_qx_[c], d_qz_[c]);
                    }
                    // North face.
                    if (j + 1 < nz) {
                        const std::size_t n = c + static_cast<std::size_t>(nx);
                        const Face f = faceFlux(g, dry, film, eta_[c], bed_[c], qz_[c], qx_[c],
                                                eta_[n], bed_[n], qz_[n], qx_[n]);
                        d_eta_[c] += f.mass; d_qz_[c] += f.left; d_qx_[c] += f.along;
                        if (tile_active_[tileOf(i, j + 1)]) {
                            d_eta_[n] -= f.mass; d_qz_[n] -= f.right; d_qx_[n] -= f.along;
                        }
                    } else {
                        boundary(north_[static_cast<std::size_t>(i)], -1, c, qz_[c], qx_[c],
                                 d_eta_[c], d_qz_[c], d_qx_[c]);
                    }
                    if (i == 0)
                        boundary(west_[static_cast<std::size_t>(j)], +1, c, qx_[c], qz_[c],
                                 d_eta_[c], d_qx_[c], d_qz_[c]);
                    if (j == 0)
                        boundary(south_[static_cast<std::size_t>(i)], +1, c, qz_[c], qx_[c],
                                 d_eta_[c], d_qz_[c], d_qx_[c]);
                }
        }

    // The update, friction, and the speed the next substep has to respect.
    const double lambda = dt / dx;
    const double n2 = settings_.manning_n * settings_.manning_n;
    const double cap = settings_.max_speed_m_s;
    double fastest = 0.0;
    std::size_t wet = 0;
    for (int tz = 0; tz < tiles_z_; ++tz)
        for (int tx = 0; tx < tiles_x_; ++tx) {
            const std::size_t tile = static_cast<std::size_t>(tz) * static_cast<std::size_t>(tiles_x_) +
                                     static_cast<std::size_t>(tx);
            if (!tile_active_[tile]) continue;
            std::uint8_t any = 0;
            const int i1 = std::min(nx, (tx + 1) * t), j1 = std::min(nz, (tz + 1) * t);
            for (int j = tz * t; j < j1; ++j)
                for (int i = tx * t; i < i1; ++i) {
                    const std::size_t c = grid_.at(i, j);
                    if (d_eta_[c] != 0.0) eta_[c] -= lambda * d_eta_[c];
                    if (d_qx_[c] != 0.0) qx_[c] -= lambda * d_qx_[c];
                    if (d_qz_[c] != 0.0) qz_[c] -= lambda * d_qz_[c];
                    if (eta_[c] < bed_[c]) {
                        ledger_.numerical_m3 += (bed_[c] - eta_[c]) * area;
                        eta_[c] = bed_[c];
                        ++stats_.clamped;
                    }
                    const double h = eta_[c] - bed_[c];
                    if (!(h > dry)) {
                        qx_[c] = 0.0;
                        qz_[c] = 0.0;
                        continue;
                    }
                    any = 1;
                    ++wet;
                    double u = speedOf(qx_[c], h, dry, film);
                    double v = speedOf(qz_[c], h, dry, film);
                    double speed = std::sqrt(u * u + v * v);
                    if (n2 > 0.0 && speed > 0.0) {
                        // Manning, implicit in the friction: it can slow the
                        // water to a stop and never past it.
                        const double factor = 1.0 + dt * g * n2 * speed / (h * std::cbrt(h));
                        qx_[c] /= factor;
                        qz_[c] /= factor;
                        u /= factor;
                        v /= factor;
                        speed /= factor;
                    }
                    if (speed > cap) {
                        const double scale = cap / speed;
                        qx_[c] *= scale;
                        qz_[c] *= scale;
                        u *= scale;
                        v *= scale;
                        ++stats_.speed_capped;
                    }
                    fastest = std::max(fastest, std::max(std::abs(u), std::abs(v)) + std::sqrt(g * h));
                }
            tile_wet_[tile] = any;
        }

    ledger_.inflow_m3 += came_in * dt;
    ledger_.outflow_m3 += went_out * dt;
    inflow_rate_ = came_in;
    outflow_rate_ = went_out;
    stats_.time_s += dt;
    ++stats_.substeps;
    stats_.last_substep_s = dt;
    stats_.active_cells = computed;
    stats_.wet_cells = wet;
    stats_.max_speed_m_s = fastest;
    // Tiles again: water may have reached a tile that was dry.
    std::size_t active = 0;
    for (int tz = 0; tz < tiles_z_; ++tz)
        for (int tx = 0; tx < tiles_x_; ++tx) {
            std::uint8_t on = tile_always_[static_cast<std::size_t>(tz) * static_cast<std::size_t>(tiles_x_) +
                                           static_cast<std::size_t>(tx)];
            for (int dz = -1; dz <= 1 && !on; ++dz)
                for (int ddx = -1; ddx <= 1 && !on; ++ddx) {
                    const int x = tx + ddx, z = tz + dz;
                    if (x < 0 || z < 0 || x >= tiles_x_ || z >= tiles_z_) continue;
                    on = tile_wet_[static_cast<std::size_t>(z) * static_cast<std::size_t>(tiles_x_) +
                                   static_cast<std::size_t>(x)];
                }
            tile_active_[static_cast<std::size_t>(tz) * static_cast<std::size_t>(tiles_x_) +
                         static_cast<std::size_t>(tx)] = on;
            active += on;
        }
    stats_.active_tiles = active;
    // The inflows' arriving water sets a floor on the wave speed too.
    speed_ = fastest;
    for (const Inflow &inflow : inflows_) {
        const int faces = inflow.to - inflow.from + 1;
        const double q = inflow.discharge_m3_s / (faces * dx);
        const double h = std::cbrt(q * q / g);
        if (h > 0.0) speed_ = std::max(speed_, q / h + std::sqrt(g * h));
    }
    speed_known_ = true;
}

double ShallowWater::volume() const {
    const double area = faceArea();
    double total = 0.0;
    for (std::size_t c = 0; c < eta_.size(); ++c) total += (eta_[c] - bed_[c]) * area;
    return total;
}

std::size_t ShallowWater::wetCells() const {
    std::size_t wet = 0;
    for (std::size_t c = 0; c < eta_.size(); ++c)
        if (eta_[c] - bed_[c] > settings_.dry_m) ++wet;
    return wet;
}

double ShallowWater::wetArea() const { return static_cast<double>(wetCells()) * faceArea(); }

double ShallowWater::residual() const {
    return volume() - (ledger_.initial_m3 + ledger_.inflow_m3 - ledger_.outflow_m3 +
                       ledger_.numerical_m3);
}

void ShallowWater::resetLedger() {
    ledger_ = Ledger{};
    ledger_.initial_m3 = volume();
}

ShallowWater::State ShallowWater::state() const {
    State out;
    out.depth.resize(eta_.size());
    for (std::size_t c = 0; c < eta_.size(); ++c) out.depth[c] = eta_[c] - bed_[c];
    out.qx = qx_;
    out.qz = qz_;
    out.ledger = ledger_;
    out.time_s = stats_.time_s;
    return out;
}

void ShallowWater::restore(const State &state) {
    const std::size_t n = grid_.cells();
    if (state.depth.size() != n || state.qx.size() != n || state.qz.size() != n)
        throw std::invalid_argument("a saved water state is for a grid of a different size");
    for (std::size_t c = 0; c < n; ++c) {
        if (!std::isfinite(state.depth[c]) || state.depth[c] < 0.0)
            throw std::invalid_argument("a saved water state has a depth that is not a depth");
        obstacle_[c] = kNoObstacle;
        bed_[c] = terrain_[c];
        eta_[c] = terrain_[c] + state.depth[c];
        qx_[c] = state.qx[c];
        qz_[c] = state.qz[c];
    }
    ledger_ = state.ledger;
    stats_.time_s = state.time_s;
    tiles_dirty_ = true;
    speed_known_ = false;
}

} // namespace banjo::water
