#include "water/WaterCoupling.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <optional>
#include <set>
#include <stdexcept>
#include <tuple>
#include <utility>

namespace banjo::water {
namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kNoTop = -std::numeric_limits<double>::infinity();

Quat conjugate(const Quat &q) { return Quat{q.w, -q.x, -q.y, -q.z}; }

// The water at a horizontal point: surface and velocity interpolated over the
// wet columns around it; the nearest column; and the lowest bed any of the
// water it was drawn from stands on.
struct Sample {
    bool wet{};
    double eta{}, u{}, w{};
    std::size_t cell{};
    double bed{};
    double wet_bed{std::numeric_limits<double>::infinity()};
};

Sample sampleAt(const ShallowWater &water, double x, double z, double wet_m) {
    Sample s;
    const Grid &g = water.grid();
    const double fx = (x - g.x0) / g.dx, fz = (z - g.z0) / g.dx;
    if (fx < -0.5 || fz < -0.5 || fx > g.nx - 0.5 || fz > g.nz - 0.5) return s;
    const int ni = std::clamp(static_cast<int>(std::lround(fx)), 0, g.nx - 1);
    const int nj = std::clamp(static_cast<int>(std::lround(fz)), 0, g.nz - 1);
    s.cell = g.at(ni, nj);
    s.bed = water.bed(s.cell);
    const int i0 = std::clamp(static_cast<int>(std::floor(fx)), 0, g.nx - 2);
    const int j0 = std::clamp(static_cast<int>(std::floor(fz)), 0, g.nz - 2);
    const double a = std::clamp(fx - i0, 0.0, 1.0), b = std::clamp(fz - j0, 0.0, 1.0);
    const double weights[4] = {(1 - a) * (1 - b), a * (1 - b), (1 - a) * b, a * b};
    const std::size_t cells[4] = {g.at(i0, j0), g.at(i0 + 1, j0), g.at(i0, j0 + 1), g.at(i0 + 1, j0 + 1)};
    double total = 0.0;
    for (int k = 0; k < 4; ++k) {
        if (!(water.depth(cells[k]) > wet_m) || !(weights[k] > 0.0)) continue;
        total += weights[k];
        s.eta += weights[k] * water.surface(cells[k]);
        s.u += weights[k] * water.velocityX(cells[k]);
        s.w += weights[k] * water.velocityZ(cells[k]);
        s.wet_bed = std::min(s.wet_bed, water.bed(cells[k]));
    }
    if (total > 1.0e-9) {
        s.wet = true;
        s.eta /= total;
        s.u /= total;
        s.w /= total;
        return s;
    }
    // Between four dry points the nearest column may still be wet.
    if (water.depth(s.cell) > wet_m) {
        s.wet = true;
        s.eta = water.surface(s.cell);
        s.u = water.velocityX(s.cell);
        s.w = water.velocityZ(s.cell);
        s.wet_bed = water.bed(s.cell);
    }
    return s;
}

// The column straight under (or over) a point, as water: wet or not, and on
// what bed. A face looking down is pressed on by the water UNDER it, which is
// the column it is over and no other.
Sample columnAt(const ShallowWater &water, double x, double z, double wet_m) {
    Sample s;
    const Grid &g = water.grid();
    const long i = std::lround((x - g.x0) / g.dx), j = std::lround((z - g.z0) / g.dx);
    if (i < 0 || j < 0 || i >= g.nx || j >= g.nz) return s;
    s.cell = g.at(static_cast<int>(i), static_cast<int>(j));
    s.bed = s.wet_bed = water.bed(s.cell);
    if (!(water.depth(s.cell) > wet_m)) return s;
    s.wet = true;
    s.eta = water.surface(s.cell);
    s.u = water.velocityX(s.cell);
    s.w = water.velocityZ(s.cell);
    return s;
}

// The part of a planar polygon below y = level (Sutherland-Hodgman against one
// plane). Up to n + 1 points.
int clipBelow(const Vec3 *in, int n, double level, Vec3 *out) {
    int m = 0;
    for (int k = 0; k < n; ++k) {
        const Vec3 &a = in[k];
        const Vec3 &b = in[(k + 1) % n];
        const bool a_in = a.y <= level, b_in = b.y <= level;
        if (a_in) out[m++] = a;
        if (a_in != b_in) {
            const double t = (level - a.y) / (b.y - a.y);
            out[m++] = a + t * (b - a);
        }
    }
    return m;
}

// Area and centroid of a planar polygon, by a fan from its first point.
std::pair<double, Vec3> areaAndCentroid(const Vec3 *p, int n) {
    Vec3 area_vector{};
    Vec3 weighted{};
    double total = 0.0;
    for (int k = 1; k + 1 < n; ++k) {
        const Vec3 tri = 0.5 * cross(p[k] - p[0], p[k + 1] - p[0]);
        const double a = length(tri);
        area_vector += tri;
        weighted += a * ((p[0] + p[k] + p[k + 1]) / 3.0);
        total += a;
    }
    if (!(total > 0.0)) return {0.0, p[0]};
    return {length(area_vector), weighted / total};
}

// The body's extent from its centre, for a cheap first look.
double reachOf(const BodyInWater &b) {
    switch (b.shape) {
    case BodyInWater::Shape::Sphere: return 0.5 * b.dimensions_m.x;
    case BodyInWater::Shape::Box: return 0.5 * length(b.dimensions_m);
    case BodyInWater::Shape::Cells: {
        double far = 0.0;
        if (b.cells_local_m)
            for (const Vec3 &c : *b.cells_local_m) far = std::max(far, length(c));
        return far + 0.87 * b.cell_m;
    }
    }
    return 0.0;
}

// Where a vertical line through (x, z) passes through the body, if it does.
std::optional<std::pair<double, double>> verticalSpan(const BodyInWater &b, double x, double z) {
    if (b.shape == BodyInWater::Shape::Sphere) {
        const double r = 0.5 * b.dimensions_m.x;
        const double d2 = (x - b.com_m.x) * (x - b.com_m.x) + (z - b.com_m.z) * (z - b.com_m.z);
        if (d2 >= r * r) return std::nullopt;
        const double half = std::sqrt(r * r - d2);
        return std::make_pair(b.com_m.y - half, b.com_m.y + half);
    }
    if (b.shape == BodyInWater::Shape::Box) {
        const Quat back = conjugate(b.orientation);
        const Vec3 o = back.rotate(Vec3{x, 0.0, z} - b.com_m);
        const Vec3 d = back.rotate(Vec3{0.0, 1.0, 0.0});
        const double h[3] = {0.5 * b.dimensions_m.x, 0.5 * b.dimensions_m.y, 0.5 * b.dimensions_m.z};
        const double oo[3] = {o.x, o.y, o.z}, dd[3] = {d.x, d.y, d.z};
        double lo = -std::numeric_limits<double>::infinity(), hi = std::numeric_limits<double>::infinity();
        for (int k = 0; k < 3; ++k) {
            if (std::abs(dd[k]) < 1.0e-12) {
                if (std::abs(oo[k]) > h[k]) return std::nullopt;
                continue;
            }
            const double t1 = (-h[k] - oo[k]) / dd[k], t2 = (h[k] - oo[k]) / dd[k];
            lo = std::max(lo, std::min(t1, t2));
            hi = std::min(hi, std::max(t1, t2));
        }
        if (!(lo <= hi)) return std::nullopt;
        return std::make_pair(lo, hi);
    }
    if (!b.cells_local_m) return std::nullopt;
    const double half = 0.5 * b.cell_m;
    double lo = std::numeric_limits<double>::infinity(), hi = -lo;
    for (const Vec3 &offset : *b.cells_local_m) {
        const Vec3 at = b.com_m + b.orientation.rotate(offset);
        if (std::abs(x - at.x) > half || std::abs(z - at.z) > half) continue;
        lo = std::min(lo, at.y - half);
        hi = std::max(hi, at.y + half);
    }
    if (!(lo <= hi)) return std::nullopt;
    return std::make_pair(lo, hi);
}

} // namespace

bool WaterCoupling::isObstacle(const BodyInWater &body, double water_density) {
    if (body.held) return false;
    // Something that would float is lifted by the water rising round it and
    // cannot hold the water back. Something that sinks, or is fixed, can.
    return body.anchored || body.density_kg_m3 > water_density;
}

const std::vector<WaterCoupling::Patch> &WaterCoupling::patchesOf(const BodyInWater &b) {
    char key[256];
    std::snprintf(key, sizeof key, "%d|%.6f|%.6f|%.6f|%zu|%.6f|%s", static_cast<int>(b.shape),
                  b.dimensions_m.x, b.dimensions_m.y, b.dimensions_m.z,
                  b.cells_local_m ? b.cells_local_m->size() : std::size_t{0}, b.cell_m, b.name.c_str());
    const auto found = patches_.find(key);
    if (found != patches_.end()) return found->second;
    std::vector<Patch> made;
    const double most = std::max(0.02, settings_.patch_m);
    // A square face of side `a` by `b` at `centre`, facing `normal`, spanned by
    // `ua` and `ub`, cut into squares no larger than `most`.
    const auto face = [&](const Vec3 &centre, const Vec3 &normal, const Vec3 &ua, const Vec3 &ub,
                          double a, double b_len) {
        const int ma = std::clamp(static_cast<int>(std::ceil(a / most)), 1, 24);
        const int mb = std::clamp(static_cast<int>(std::ceil(b_len / most)), 1, 24);
        const double da = a / ma, db = b_len / mb;
        for (int p = 0; p < ma; ++p)
            for (int q = 0; q < mb; ++q) {
                const Vec3 base = centre + (-0.5 * a + p * da) * ua + (-0.5 * b_len + q * db) * ub;
                Patch patch;
                patch.corner[0] = base;
                patch.corner[1] = base + da * ua;
                patch.corner[2] = base + da * ua + db * ub;
                patch.corner[3] = base + db * ub;
                patch.normal = normal;
                patch.area = da * db;
                made.push_back(patch);
            }
    };
    const Vec3 ex{1, 0, 0}, ey{0, 1, 0}, ez{0, 0, 1};
    if (b.shape == BodyInWater::Shape::Box) {
        const Vec3 h = 0.5 * b.dimensions_m;
        face({h.x, 0, 0}, ex, ey, ez, b.dimensions_m.y, b.dimensions_m.z);
        face({-h.x, 0, 0}, -1.0 * ex, ez, ey, b.dimensions_m.z, b.dimensions_m.y);
        face({0, h.y, 0}, ey, ez, ex, b.dimensions_m.z, b.dimensions_m.x);
        face({0, -h.y, 0}, -1.0 * ey, ex, ez, b.dimensions_m.x, b.dimensions_m.z);
        face({0, 0, h.z}, ez, ex, ey, b.dimensions_m.x, b.dimensions_m.y);
        face({0, 0, -h.z}, -1.0 * ez, ey, ex, b.dimensions_m.y, b.dimensions_m.x);
    } else if (b.shape == BodyInWater::Shape::Sphere) {
        // A polyhedron of flat triangles, scaled so it holds exactly the ball's
        // volume: displaced volume is what buoyancy is made of, and an
        // inscribed polyhedron is a smaller ball.
        const int lat = 14, lon = 28;
        const auto point = [&](int i, int j) {
            const double theta = kPi * i / lat, phi = 2.0 * kPi * j / lon;
            return Vec3{std::sin(theta) * std::cos(phi), std::cos(theta), std::sin(theta) * std::sin(phi)};
        };
        std::vector<std::array<Vec3, 3>> triangles;
        for (int i = 0; i < lat; ++i)
            for (int j = 0; j < lon; ++j) {
                const Vec3 a = point(i, j), bq = point(i + 1, j), c = point(i + 1, j + 1), d = point(i, j + 1);
                if (i > 0) triangles.push_back({a, c, d});
                if (i + 1 < lat) triangles.push_back({a, bq, c});
            }
        double unit_volume = 0.0;
        for (const auto &t : triangles) unit_volume += dot(t[0], cross(t[1], t[2])) / 6.0;
        const double r = 0.5 * b.dimensions_m.x;
        const double scale = r * std::cbrt((4.0 / 3.0 * kPi) / std::abs(unit_volume));
        for (const auto &t : triangles) {
            Patch patch;
            patch.corner[0] = scale * t[0];
            patch.corner[1] = scale * t[1];
            patch.corner[2] = scale * t[2];
            patch.corner[3] = scale * t[2];
            Vec3 n = cross(patch.corner[1] - patch.corner[0], patch.corner[2] - patch.corner[0]);
            // Outward: the triangles are wound either way round.
            if (dot(n, patch.corner[0]) < 0.0) {
                std::swap(patch.corner[1], patch.corner[2]);
                patch.corner[3] = patch.corner[2];
                n = -1.0 * n;
            }
            patch.area = 0.5 * length(n);
            patch.normal = normalized(n);
            made.push_back(patch);
        }
    } else if (b.cells_local_m && b.cell_m > 0.0) {
        // A piece of something: its cells are its surface, and only the faces
        // no other cell of it covers are wetted.
        const std::vector<Vec3> &cells = *b.cells_local_m;
        std::set<std::tuple<long, long, long>> at;
        const Vec3 origin = cells.empty() ? Vec3{} : cells.front();
        for (const Vec3 &c : cells) {
            const Vec3 o = (c - origin) / b.cell_m;
            at.insert({std::lround(o.x), std::lround(o.y), std::lround(o.z)});
        }
        const double s = b.cell_m;
        for (const Vec3 &c : cells) {
            const Vec3 o = (c - origin) / s;
            const long x = std::lround(o.x), y = std::lround(o.y), z = std::lround(o.z);
            if (!at.count({x + 1, y, z})) face(c + Vec3{0.5 * s, 0, 0}, ex, ey, ez, s, s);
            if (!at.count({x - 1, y, z})) face(c - Vec3{0.5 * s, 0, 0}, -1.0 * ex, ez, ey, s, s);
            if (!at.count({x, y + 1, z})) face(c + Vec3{0, 0.5 * s, 0}, ey, ez, ex, s, s);
            if (!at.count({x, y - 1, z})) face(c - Vec3{0, 0.5 * s, 0}, -1.0 * ey, ex, ez, s, s);
            if (!at.count({x, y, z + 1})) face(c + Vec3{0, 0, 0.5 * s}, ez, ex, ey, s, s);
            if (!at.count({x, y, z - 1})) face(c - Vec3{0, 0, 0.5 * s}, -1.0 * ez, ey, ex, s, s);
        }
    }
    return patches_.emplace(key, std::move(made)).first->second;
}

std::vector<BodyForce> WaterCoupling::forces(const ShallowWater &water,
                                             const std::vector<BodyInWater> &bodies,
                                             std::vector<Reaction> &reactions) {
    std::vector<BodyForce> out;
    reactions.clear();
    const Grid &g = water.grid();
    const double rho = water.settings().density_kg_m3;
    const double gravity = water.settings().gravity_m_s2;
    const double wet = settings_.wet_m;
    for (const BodyInWater &b : bodies) {
        if (b.held || b.anchored || !b.awake) continue;
        // A first look: is there water anywhere under it, high enough to reach it?
        const double reach = reachOf(b);
        const int i0 = std::max(0, static_cast<int>(std::floor((b.com_m.x - reach - g.x0) / g.dx)));
        const int i1 = std::min(g.nx - 1, static_cast<int>(std::ceil((b.com_m.x + reach - g.x0) / g.dx)));
        const int j0 = std::max(0, static_cast<int>(std::floor((b.com_m.z - reach - g.z0) / g.dx)));
        const int j1 = std::min(g.nz - 1, static_cast<int>(std::ceil((b.com_m.z + reach - g.z0) / g.dx)));
        bool near_water = false;
        for (int j = j0; j <= j1 && !near_water; ++j)
            for (int i = i0; i <= i1; ++i) {
                const std::size_t c = g.at(i, j);
                if (water.depth(c) > wet && water.surface(c) > b.com_m.y - reach) { near_water = true; break; }
            }
        if (!near_water) continue;

        BodyForce f;
        f.index = b.index;
        for (const Patch &patch : patchesOf(b)) {
            Vec3 world[4];
            for (int k = 0; k < 4; ++k) world[k] = b.com_m + b.orientation.rotate(patch.corner[k]);
            const Vec3 n = b.orientation.rotate(patch.normal);
            const Vec3 centre = 0.25 * (world[0] + world[1] + world[2] + world[3]);
            // The water that presses on this face. A face looking sideways is
            // pressed on by the water beside it, sampled half a cell out; one
            // looking down, by the column under it -- which, under a block
            // resting on the bed, is the block's own sealed column and holds
            // none; one looking up, by whatever stands over it.
            const bool sideways = std::abs(n.y) < 0.7;
            const Sample s = sideways
                ? sampleAt(water, centre.x + 0.5 * g.dx * n.x, centre.z + 0.5 * g.dx * n.z, wet)
                : columnAt(water, centre.x, centre.z, wet);
            if (!s.wet) continue;
            // Only water standing on a bed below the face can reach it: a face
            // beside a bank higher than itself, or under a block's own top,
            // has ground or stone against it, not water.
            if (centre.y < s.wet_bed - 1.0e-3) continue;
            const double lowest = std::min({world[0].y, world[1].y, world[2].y, world[3].y});
            if (!(s.eta > lowest)) continue;
            Vec3 clipped[8];
            const int m = clipBelow(world, 4, s.eta, clipped);
            if (m < 3) continue;
            const auto [area, at] = areaAndCentroid(clipped, m);
            if (!(area > 1.0e-12)) continue;
            const double depth = std::max(0.0, s.eta - at.y);
            const Vec3 pressure = (-rho * gravity * depth * area) * n;
            // Drag, from the water's motion relative to this point of the body.
            const Vec3 moving = b.velocity_m_s + cross(b.angular_velocity_rad_s, at - b.com_m);
            const Vec3 relative{s.u - moving.x, -moving.y, s.w - moving.z};
            const double vn = dot(relative, n);
            Vec3 drag{};
            if (vn < 0.0) drag += (0.5 * rho * settings_.drag_coefficient * std::abs(vn) * area) * (vn * n);
            const Vec3 along = relative - vn * n;
            drag += (0.5 * rho * settings_.skin_coefficient * length(along) * area) * along;
            const Vec3 total = pressure + drag;
            f.force_n += total;
            f.torque_n_m += cross(at - b.com_m, total);
            f.pressure_n += pressure;
            f.drag_n += drag;
            f.submerged_m3 += (at.y - s.eta) * n.y * area;
            f.wetted_m2 += area;
            f.drag_power_w += dot(drag, moving);
            if (drag.x != 0.0 || drag.z != 0.0) reactions.push_back({s.cell, drag.x, drag.z});
        }
        if (f.wetted_m2 > 0.0) out.push_back(f);
    }
    return out;
}

std::vector<double> WaterCoupling::obstacleTops(const ShallowWater &water,
                                                const std::vector<BodyInWater> &bodies) const {
    const Grid &g = water.grid();
    std::vector<double> tops(g.cells(), kNoTop);
    std::vector<const BodyInWater *> resting;
    for (const BodyInWater &b : bodies)
        if (isObstacle(b, water.settings().density_kg_m3)) resting.push_back(&b);
    // Lowest first, so a block stacked on another finds the one under it.
    std::sort(resting.begin(), resting.end(), [](const BodyInWater *a, const BodyInWater *b) {
        return a->com_m.y - reachOf(*a) < b->com_m.y - reachOf(*b);
    });
    for (const BodyInWater *b : resting) {
        const double reach = reachOf(*b);
        const int i0 = std::max(0, static_cast<int>(std::floor((b->com_m.x - reach - g.x0) / g.dx)));
        const int i1 = std::min(g.nx - 1, static_cast<int>(std::ceil((b->com_m.x + reach - g.x0) / g.dx)));
        const int j0 = std::max(0, static_cast<int>(std::floor((b->com_m.z - reach - g.z0) / g.dx)));
        const int j1 = std::min(g.nz - 1, static_cast<int>(std::ceil((b->com_m.z + reach - g.z0) / g.dx)));
        for (int j = j0; j <= j1; ++j)
            for (int i = i0; i <= i1; ++i) {
                const auto span = verticalSpan(*b, g.xOf(i), g.zOf(j));
                if (!span) continue;
                const std::size_t c = g.at(i, j);
                const double ground = water.terrain(c);
                const double under = std::isfinite(tops[c]) ? std::max(ground, tops[c]) : ground;
                if (span->first > under + settings_.seal_gap_m) continue;   // water gets under it
                if (span->second <= ground + 0.01) continue;                // buried: nothing to add
                tops[c] = std::max(tops[c], span->second);
            }
    }
    return tops;
}

} // namespace banjo::water
