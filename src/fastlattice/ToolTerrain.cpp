#include "fastlattice/ToolTerrain.hpp"

#include "material/Material.hpp"
#include "rigid/JoltWorld.hpp"
#include "terrain/Environment.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>

namespace banjo::fastlattice {
namespace {

constexpr double kPi = 3.14159265358979323846;
// A point more than 60 degrees off straight down meets the ground side-on: it
// does not go in, it skids or stops, an ordinary contact.
constexpr double kPointsDown = 0.5;
// How near the ground the tip counts as touching it.
constexpr double kTouchM = 0.003;
// The margin round a point's region (JoltWorld::GroundPointRegion): what of the
// tool is within it meets the ground as the point, not as a surface.
constexpr double kRegionMarginM = 0.01;
// A point whose tip will be in the ground within this long is arriving: the
// ground under it is handed to it before a corner of its end can meet the
// ground as an ordinary contact. A swing brings a tip down at 5-7 m/s; a tool
// let down slowly does not lead by that, and rests on its corner as before.
constexpr double kArrivingS = 0.05;

// The radius of a point's region: its cells, whatever the declared wedge inside
// them -- half a cell's diagonal across, or the point's own section if that is
// bigger.
[[nodiscard]] double pointRadius(const terrain::ToolPointShape &shape, double cell_m) {
    return std::max(0.5 * std::hypot(shape.width_m, shape.thickness_m), 0.5 * std::sqrt(2.0) * cell_m);
}
// How far back out of where it went in a point has to come before it is out.
constexpr double kOutM = 0.01;
// The resistance of rock under the soil a point has gone through: it stops it.
constexpr double kRockN = 1.0e7;

[[nodiscard]] Quat qMul(const Quat &a, const Quat &b) {
    return {a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
            a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
            a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
            a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w};
}
[[nodiscard]] Quat qConj(const Quat &q) { return {q.w, -q.x, -q.y, -q.z}; }
[[nodiscard]] Quat qNorm(const Quat &q) {
    const double n = std::sqrt(q.w * q.w + q.x * q.x + q.y * q.y + q.z * q.z);
    return n > 0.0 ? Quat{q.w / n, q.x / n, q.y / n, q.z / n} : Quat{};
}
[[nodiscard]] Quat qAxisAngle(const Vec3 &axis, double angle) {
    const Vec3 k = normalized(axis);
    const double s = std::sin(0.5 * angle);
    return {std::cos(0.5 * angle), k.x * s, k.y * s, k.z * s};
}
[[nodiscard]] double qDot(const Quat &a, const Quat &b) {
    return a.w * b.w + a.x * b.x + a.y * b.y + a.z * b.z;
}
[[nodiscard]] Quat qSlerp(const Quat &a, Quat b, double t) {
    double c = qDot(a, b);
    if (c < 0.0) {
        b = {-b.w, -b.x, -b.y, -b.z};
        c = -c;
    }
    if (c > 0.9995)
        return qNorm({a.w + t * (b.w - a.w), a.x + t * (b.x - a.x), a.y + t * (b.y - a.y),
                      a.z + t * (b.z - a.z)});
    const double angle = std::acos(std::clamp(c, -1.0, 1.0));
    const double s = std::sin(angle);
    const double wa = std::sin((1.0 - t) * angle) / s, wb = std::sin(t * angle) / s;
    return qNorm({wa * a.w + wb * b.w, wa * a.x + wb * b.x, wa * a.y + wb * b.y, wa * a.z + wb * b.z});
}
[[nodiscard]] double qAngle(const Quat &a, const Quat &b) {
    return 2.0 * std::acos(std::clamp(std::abs(qDot(a, b)), 0.0, 1.0));
}
// The rotation taking three local axes onto three world ones (both
// orthonormal and right-handed): R = W L^T.
[[nodiscard]] Quat qFromBases(const Vec3 &lx, const Vec3 &ly, const Vec3 &lz, const Vec3 &wx,
                              const Vec3 &wy, const Vec3 &wz) {
    const double l[3][3] = {{lx.x, lx.y, lx.z}, {ly.x, ly.y, ly.z}, {lz.x, lz.y, lz.z}};
    const double w[3][3] = {{wx.x, wx.y, wx.z}, {wy.x, wy.y, wy.z}, {wz.x, wz.y, wz.z}};
    double m[3][3]{};
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            for (int k = 0; k < 3; ++k) m[i][j] += w[k][i] * l[k][j];
    Quat q;
    const double trace = m[0][0] + m[1][1] + m[2][2];
    if (trace > 0.0) {
        const double s = 0.5 / std::sqrt(trace + 1.0);
        q = {0.25 / s, (m[2][1] - m[1][2]) * s, (m[0][2] - m[2][0]) * s, (m[1][0] - m[0][1]) * s};
    } else if (m[0][0] > m[1][1] && m[0][0] > m[2][2]) {
        const double s = 2.0 * std::sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]);
        q = {(m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s};
    } else if (m[1][1] > m[2][2]) {
        const double s = 2.0 * std::sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]);
        q = {(m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s};
    } else {
        const double s = 2.0 * std::sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]);
        q = {(m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s};
    }
    return qNorm(q);
}
// Some direction square to `a`.
[[nodiscard]] Vec3 anyAcross(const Vec3 &a) {
    Vec3 c = cross(a, Vec3{0.0, 1.0, 0.0});
    if (length(c) < 1e-6) c = cross(a, Vec3{1.0, 0.0, 0.0});
    return normalized(c);
}
[[nodiscard]] Vec3 level(const Vec3 &v) { return {v.x, 0.0, v.z}; }

// The rotation nearest a matrix, by Higham's iteration: how a point follows
// its own cells into a body rebuilt in a new frame (as LiveWorld's blades do).
[[nodiscard]] Mat3 nearestRotation(Mat3 m) {
    for (int i = 0; i < 40; ++i) {
        const auto inverse = m.inverse(1e-30);
        if (!inverse) break;
        for (int r = 0; r < 3; ++r)
            for (int c = 0; c < 3; ++c) m.m[r][c] = 0.5 * (m.m[r][c] + inverse->m[c][r]);
    }
    return m;
}

// How near a point in a body's own frame is to the body's matter: the
// distance to its nearest cell centre.
[[nodiscard]] double nearestCell(const std::vector<std::pair<std::uint32_t, Vec3>> &cells, const Vec3 &p) {
    double best = std::numeric_limits<double>::infinity();
    for (const auto &cell : cells) best = std::min(best, length(cell.second - p));
    return best;
}

std::string mm(double metres) {
    char text[32];
    std::snprintf(text, sizeof text, "%.0f mm", 1000.0 * metres);
    return text;
}

} // namespace

// ---- declaring a point --------------------------------------------------------

unsigned ToolTerrain::declare(const ToolTerrainHost &host, const std::string &body,
                              const Vec3 &tip_world_m, const Vec3 &pointing_world,
                              const terrain::ToolPointShape &asked, const Vec3 &grip_world_m,
                              std::string &why) {
    why.clear();
    const auto refuse = [&why](const std::string &reason) {
        why = reason;
        return 0u;
    };
    const auto finite = [](const Vec3 &v) {
        return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
    };
    const std::optional<MatterBodyId> id = host.id_of(body);
    if (host.parked && host.parked(body)) return refuse("it is set aside: bring it back into the world first");
    if (!id || !host.world->contains(*id)) return refuse("there is nothing called that in the scene");
    if (host.anchored && host.anchored(body))
        return refuse("that is anchored scenery: nobody can swing it, so its point would never go anywhere");
    if (!finite(tip_world_m) || !finite(pointing_world) || !finite(grip_world_m))
        return refuse("a point, the pointing or the grip is not a finite number");
    if (!(asked.width_m >= 0.002 && asked.width_m <= 0.5))
        return refuse("the point's width is 2 mm to 0.5 m");
    if (!(asked.thickness_m >= 0.002 && asked.thickness_m <= 0.5))
        return refuse("the point's thickness is 2 mm to 0.5 m");
    if (!(asked.angle_deg >= 5.0 && asked.angle_deg <= 170.0))
        return refuse("the point comes to its tip at an angle of 5 to 170 degrees");
    if (!(asked.length_m >= 0.01 && asked.length_m <= 1.0))
        return refuse("the point is 10 mm to 1 m of the tool");
    if (!(length(pointing_world) > 1e-9)) return refuse("the pointing has no direction");
    const Vec3 a = normalized(pointing_world);

    const RigidSnapshot at = host.world->snapshot(*id);
    const Quat inverse = qConj(at.orientation_world);
    Point made;
    made.id = next_;
    made.body = body;
    made.tip_local = inverse.rotate(tip_world_m - at.center_of_mass_world_m);
    made.pointing_local = normalized(inverse.rotate(a));
    made.grip_local = inverse.rotate(grip_world_m - at.center_of_mass_world_m);
    made.shape = asked;

    // The tip has to be ON the body -- at the end of its matter -- and the
    // point has to come OUT of it there. A tip in the air beside a body would
    // dig where the body never reaches; one pointing back into the body would
    // lead with the handle.
    const auto cells = host.cells_of(body);
    const double cell = host.cell_m;
    if (cells.empty()) return refuse("it has no cells to be a tool of");
    if (nearestCell(cells, made.tip_local) > 0.9 * cell)
        return refuse("the tip is not on the body's matter: it has to be at the end of it, on its surface");
    if (nearestCell(cells, made.tip_local - 0.5 * cell * made.pointing_local) > 0.75 * cell)
        return refuse("there is no matter behind the tip: the pointing has to run out of the body at the tip");
    if (nearestCell(cells, made.tip_local + 0.5 * cell * made.pointing_local) < 0.45 * cell)
        return refuse("the pointing runs back into the body: it has to point out of it, the way the point goes in");
    // And the grip is where a hand closes on it, so it is on the body as well.
    // A grip in the air beside it has the hand holding nothing: every swing is
    // made about a point the tool is not at, and its point meets no ground --
    // measured, the room's chat gave a pick's grip with its height and depth
    // swapped, 1.2 m above the haft, and its trial never reached the soil.
    if (nearestCell(cells, made.grip_local) > 0.9 * cell)
        return refuse("the grip is not on the body's matter: it has to be where a hand takes hold of it, on the body");
    // Which way its edge runs: square to the point and to the line from the
    // tip to the grip. For a pick that is across the swing, which is how a
    // pick's point is shaped to go into the ground.
    const Vec3 handle = made.grip_local - made.tip_local;
    Vec3 width = cross(made.pointing_local, handle);
    made.width_local = length(width) > 1e-6 ? normalized(width) : anyAcross(made.pointing_local);
    made.body_id = *id;
    for (const auto &c : cells) {
        made.frame_nodes.push_back(c.first);
        made.frame_offsets.push_back(c.second);
    }
    ++next_;
    points_.push_back(std::move(made));
    return points_.back().id;
}

std::vector<LiveToolPoint> ToolTerrain::points(const ToolTerrainHost &host) const {
    std::vector<LiveToolPoint> out;
    out.reserve(points_.size());
    for (const Point &p : points_) {
        LiveToolPoint said;
        said.id = p.id;
        said.body = p.body;
        said.tip_local_m = p.tip_local;
        said.pointing_local = p.pointing_local;
        said.grip_local_m = p.grip_local;
        said.width_m = p.shape.width_m;
        said.thickness_m = p.shape.thickness_m;
        said.angle_deg = p.shape.angle_deg;
        said.length_m = p.shape.length_m;
        const std::optional<MatterBodyId> id = host.id_of(p.body);
        said.attached = p.attached && id && host.world->contains(*id);
        if (said.attached) {
            const RigidSnapshot s = host.world->snapshot(*id);
            said.material = host.material_name_of(p.body);
            said.tip_m = s.center_of_mass_world_m + s.orientation_world.rotate(p.tip_local);
            said.grip_m = s.center_of_mass_world_m + s.orientation_world.rotate(p.grip_local);
            said.pointing = s.orientation_world.rotate(p.pointing_local);
            if (p.joint != 0) {
                said.in = p.ground;
                said.depth_m = std::max(0.0, dot(said.tip_m - p.entry, p.axis));
            }
        }
        out.push_back(std::move(said));
    }
    return out;
}

void ToolTerrain::forget() {
    std::vector<std::size_t> moved(log_.size(), kNone);
    std::vector<LiveGroundWork> kept;
    for (std::size_t i = 0; i < log_.size(); ++i) {
        if (!log_[i].open) continue;
        moved[i] = kept.size();
        kept.push_back(log_[i]);
    }
    log_ = std::move(kept);
    for (Point &p : points_) {
        p.report = p.report < moved.size() ? moved[p.report] : kNone;
        p.note = p.note < moved.size() ? moved[p.note] : kNone;
    }
}

bool ToolTerrain::inGround(const std::string &body) const {
    return std::any_of(points_.begin(), points_.end(),
                       [&](const Point &p) { return p.body == body && p.joint != 0; });
}

void ToolTerrain::setAside(const ToolTerrainHost &host, const std::string &body) {
    for (Point &p : points_)
        if (p.body == body) closeNote(host, p);
}

// ---- a body rebuilt, and a body made a tool -----------------------------------

void ToolTerrain::follow(const ToolTerrainHost &host, Point &p, MatterBodyId now) {
    // A body that came through a fracture whole is put back in a new frame.
    // Follow the point's own cells into it, so the tip stays at the end of the
    // wood -- the same fit the blades make (LiveWorld::prepareCuts).
    const auto cells = host.cells_of(p.body);
    std::vector<Vec3> now_at;
    std::vector<Vec3> was_at;
    for (std::size_t k = 0; k < p.frame_nodes.size(); ++k)
        for (const auto &c : cells)
            if (c.first == p.frame_nodes[k]) {
                now_at.push_back(c.second);
                was_at.push_back(p.frame_offsets[k]);
                break;
            }
    if (now_at.size() >= 3) {
        Vec3 was_centre{}, now_centre{};
        for (std::size_t k = 0; k < now_at.size(); ++k) {
            was_centre += was_at[k];
            now_centre += now_at[k];
        }
        was_centre = (1.0 / static_cast<double>(now_at.size())) * was_centre;
        now_centre = (1.0 / static_cast<double>(now_at.size())) * now_centre;
        Mat3 correlation{};
        for (std::size_t k = 0; k < now_at.size(); ++k) {
            const Vec3 a = now_at[k] - now_centre, b = was_at[k] - was_centre;
            const double av[3] = {a.x, a.y, a.z}, bv[3] = {b.x, b.y, b.z};
            for (int r = 0; r < 3; ++r)
                for (int c = 0; c < 3; ++c) correlation.m[r][c] += av[r] * bv[c];
        }
        const Mat3 turn = nearestRotation(correlation);
        const auto carry = [&](const Vec3 &v) { return turn * (v - was_centre) + now_centre; };
        p.tip_local = carry(p.tip_local);
        p.grip_local = carry(p.grip_local);
        p.pointing_local = normalized(turn * p.pointing_local);
        p.width_local = normalized(turn * p.width_local);
    }
    p.frame_nodes.clear();
    p.frame_offsets.clear();
    for (const auto &c : cells) {
        p.frame_nodes.push_back(c.first);
        p.frame_offsets.push_back(c.second);
    }
    p.body_id = now;
    p.shaped = false;
    // A bite on the old body went with it (JoltWorld::removeAndDestroy).
    if (p.joint != 0 && !host.world->hasJoint(p.joint)) p.joint = 0;
}

void ToolTerrain::shape(const ToolTerrainHost &host, Point &p, MatterBodyId id) {
    // A tool collides as its cells: a hull would fill in the crook of a pick,
    // and its handle would reach the ground before its point went in.
    std::vector<Vec3> cells;
    for (const auto &c : host.cells_of(p.body)) cells.push_back(c.second);
    if (!cells.empty()) host.world->setCollisionCells(id, cells, host.cell_m);
    host.world->setManifoldReduction(id, false);
    p.shaped = true;
}

// ---- before the step ---------------------------------------------------------

void ToolTerrain::prepare(const ToolTerrainHost &host, double dt_s) {
    JoltWorld &world = *host.world;
    for (Point &p : points_) {
        if (!p.attached) continue;
        // Set aside (LiveWorld::park), it is out of the world and not gone:
        // left as it is, neither finished nor detached, until it is back.
        if (host.parked && host.parked(p.body)) continue;
        const std::optional<MatterBodyId> id = host.id_of(p.body);
        if (!id || !world.contains(*id)) {
            finish(host, p, false);
            closeNote(host, p);
            p.attached = false;
            continue;
        }
        if (*id != p.body_id) follow(host, p, *id);
        if (!p.shaped) shape(host, p, *id);
        if (p.joint != 0 && !world.hasJoint(p.joint)) finish(host, p, true);
        const RigidSnapshot s = world.snapshot(*id);
        const Vec3 tip = s.center_of_mass_world_m + s.orientation_world.rotate(p.tip_local);
        const Vec3 a = normalized(s.orientation_world.rotate(p.pointing_local));
        const Vec3 v = s.linear_velocity_m_s + cross(s.angular_velocity_rad_s, tip - s.center_of_mass_world_m);
        if (p.joint != 0) {
            holdIn(host, p, *id, tip, v, dt_s);
            continue;
        }
        meet(host, p, *id, s, tip, a, v, dt_s);
    }
}

ToolTerrain::Resistance ToolTerrain::resistance(const Point &p, const terrain::GroundMaterial &ground,
                                                double depth_m, double closing_m_s, double dt_s) const {
    Resistance out;
    const double d = std::max(0.0, depth_m);
    // Going in: the work of going from where the tip is to as far as it could
    // get this step, over that distance -- with nothing to push through while
    // the tip is still above the ground. A limit set from the depth at the
    // start of a step alone lets a fast point through the first few
    // centimetres for nothing. Never deeper than the point is long: beyond it
    // the rest of the tool meets the ground as a surface.
    const double reach = std::min(p.shape.length_m, depth_m + std::max(0.0, closing_m_s) * dt_s);
    if (p.at_rock) {
        out.into = kRockN;
    } else if (reach > depth_m + 1e-6 && reach > 0.0) {
        const double work = terrain::penetrationWorkJ(ground, p.shape, reach) -
                            terrain::penetrationWorkJ(ground, p.shape, d);
        out.into = work / (reach - depth_m);
    } else {
        out.into = terrain::penetrationResistanceN(ground, p.shape, d);
    }
    // Sideways: the passive resistance of the depth that is in. Across the
    // point's broad face (X) it leads with its width, along its edge (Z) with
    // its thickness there.
    out.x = terrain::passiveResistanceN(ground, d, p.shape.width_m);
    out.z = terrain::passiveResistanceN(ground, d, terrain::pointThicknessAt(p.shape, d));
    return out;
}

void ToolTerrain::suspend(const ToolTerrainHost &host, const Point &p, MatterBodyId id, const Vec3 &v,
                          double dt_s) {
    JoltWorld::GroundPointRegion region;
    region.tip_local_m = p.tip_local;
    region.pointing_local = p.pointing_local;
    region.length_m = p.shape.length_m;
    // The point's cells, whatever the declared wedge inside them.
    region.radius_m = pointRadius(p.shape, host.cell_m);
    // A contact found by a sweep is placed where the body will be: allow a
    // step's travel beyond the tip. Behind the point, only a centimetre: what
    // is not point meets the ground as a surface -- it is what stops a pick at
    // its head, and what a lever turns on.
    region.ahead_m = std::max(0.01, length(v) * dt_s + 0.005);
    region.margin_m = kRegionMarginM;
    host.world->suspendGroundContact(id, region);
}

void ToolTerrain::meet(const ToolTerrainHost &host, Point &p, MatterBodyId id, const RigidSnapshot &s,
                       const Vec3 &tip, const Vec3 &a, const Vec3 &v, double dt_s) {
    JoltWorld &world = *host.world;
    terrain::Environment *env = host.environment;
    double ground_y = host.floor_y;
    std::size_t column = 0;
    if (env != nullptr) {
        const auto c = env->terrain().cellAt(tip.x, tip.z);
        if (!c) {
            closeNote(host, p);
            if (world.groundContactSuspended(id)) world.restoreGroundContact(id);
            return;
        }
        column = *c;
        ground_y = env->terrain().heightAt(tip.x, tip.z);
    }
    const Vec3 next = tip + dt_s * v;
    const bool touching = tip.y <= ground_y + kTouchM;
    const bool arriving = next.y <= ground_y + kTouchM;
    // A point comes down tilted, along the way its tip is going, so its end
    // leads with a corner: lower than its tip by up to its region's reach across
    // times the tilt. The rigid world meets that corner as an ordinary contact
    // from its speculative distance away, a step before the tip is near enough
    // to go in, and the swing stopped with the tip 2-3 cm up -- a blade broad
    // along its swing from 3 stand-backs of 8 (ground_work_tests, 8). So the
    // ground under the point is the point's once that corner could meet it this
    // step while the tip follows it in, in the ground within kArrivingS. When
    // the bite opens is still the tip's own meeting.
    bool leading = false;
    if (!touching && !arriving && v.y < 0.0 && tip.y - ground_y <= -v.y * kArrivingS) {
        const double tilt = std::sqrt(std::max(0.0, 1.0 - a.y * a.y));
        const double corner_y = tip.y - (pointRadius(p.shape, host.cell_m) + kRegionMarginM) * tilt;
        leading = corner_y + dt_s * v.y <=
                  ground_y + kTouchM + world.contactDiagnostics().speculative_distance_m;
    }
    if (!touching && !arriving && !leading) {
        if (tip.y > ground_y + 0.02) closeNote(host, p);
        if (world.groundContactSuspended(id)) world.restoreGroundContact(id);
        return;
    }
    const MaterialDefinition *made_of = host.material_of(p.body);
    const double hardness = made_of != nullptr ? made_of->hardness_pa : 0.0;
    const std::string material = host.material_name_of(p.body);
    const double closing = dot(v, a);
    const Vec3 at{tip.x, ground_y, tip.z};
    // Only a point that is arriving, or pressed on, is a meeting worth a note.
    const bool meeting = touching || v.y < -0.05;
    if (env == nullptr) {
        if (meeting) {
            const terrain::GroundVerdict floor = terrain::judgeGround(true, 0.0, hardness, material);
            note(host, p, floor.answer == terrain::GroundAnswer::TooHard ? "stopped" : "not supported",
                 "the floor", "this room's floor is concrete: " + floor.why,
                 floor.answer != terrain::GroundAnswer::NotSupported, at, closing);
        }
        return;
    }
    const terrain::TerrainField &field = env->terrain();
    const bool rock = field.height(column) - field.rockTop(column) < 0.01;
    const double water = env->water() != nullptr ? env->water()->depth(column) : 0.0;
    const terrain::GroundVerdict verdict = terrain::judgeGround(rock, water, hardness, material);
    const std::string layer = rock ? std::string("rock") : terrain::groundAt(field, column, 0.0).name;
    if (verdict.answer != terrain::GroundAnswer::Penetrable) {
        if (meeting)
            note(host, p, verdict.answer == terrain::GroundAnswer::TooHard ? "stopped" : "not supported",
                 layer, verdict.why, verdict.answer != terrain::GroundAnswer::NotSupported, at, closing);
        return;
    }
    const double down = -a.y;
    if (down < kPointsDown) {
        if (meeting) {
            char why[200];
            std::snprintf(why, sizeof why,
                          "the point met the %s %.0f degrees off straight down: side-on, so it did not go "
                          "in -- an ordinary contact",
                          layer.c_str(), std::acos(std::clamp(down, -1.0, 1.0)) * 180.0 / kPi);
            note(host, p, "glanced", layer, why, true, at, closing);
        }
        return;
    }
    // Handed over, and the tip not in it yet: its own meeting opens the bite.
    if (leading) {
        suspend(host, p, id, v, dt_s);
        return;
    }
    // Going in, or pressed in from on the surface.
    if (!(closing > 0.02) && !touching) return;

    // In it goes. The point is held from here on by the ground's own
    // resistance, in its own axes, and the ground no longer meets it as a
    // surface there.
    const double to_surface = (tip.y - ground_y) / std::max(1e-6, down);
    p.entry = tip + to_surface * a;
    p.axis = a;
    const Vec3 width = s.orientation_world.rotate(p.width_local);
    const Vec3 squared = width - dot(width, a) * a;
    p.across_z = length(squared) > 1e-6 ? normalized(squared) : anyAcross(a);
    p.across_x = cross(a, p.across_z);
    p.column = column;
    p.deepest = 0.0;
    p.sideways = 0.0;
    p.pry = {};
    p.broke_out = false;
    p.at_rock = false;
    const double depth = dot(tip - p.entry, a);
    const terrain::GroundAtDepth in = terrain::groundAt(field, column, std::max(0.0, depth));
    p.ground = in.name;
    const Resistance r = resistance(p, in.material, depth, closing, dt_s);
    p.joint = world.addGroundBite({id, tip, a, p.across_x, r.into, r.x, r.z});
    suspend(host, p, id, v, dt_s);
    closeNote(host, p);

    LiveGroundWork opened;
    opened.point = p.id;
    opened.tool = p.body;
    opened.ground = in.name;
    opened.kind = "in the ground";
    opened.at_s = host.time_s;
    opened.at_m = p.entry;
    opened.closing_speed_m_s = std::max(0.0, closing);
    opened.resistance_n = r.into;
    opened.model = terrain::kGroundWorkModel;
    opened.open = true;
    log_.push_back(std::move(opened));
    p.report = log_.size() - 1;
    p.tip_before = tip;
    p.vn_before = dot(v, p.axis);
    p.vx_before = dot(v, p.across_x);
    p.vz_before = dot(v, p.across_z);
}

void ToolTerrain::holdIn(const ToolTerrainHost &host, Point &p, MatterBodyId id, const Vec3 &tip,
                         const Vec3 &v, double dt_s) {
    terrain::Environment *env = host.environment;
    if (env == nullptr) {
        finish(host, p, true);
        return;
    }
    const terrain::TerrainField &field = env->terrain();
    const double depth = dot(tip - p.entry, p.axis);
    // Rock under the soil the point has gone through stops it. What that
    // means for the tool is the same gate as bare rock: harder than the tool
    // and the rock stops it; softer, and breaking rock out is not modelled.
    if (!p.at_rock) {
        const auto c = field.cellAt(tip.x, tip.z);
        if (c && tip.y <= field.rockTop(*c) + kTouchM) {
            p.at_rock = true;
            const MaterialDefinition *made_of = host.material_of(p.body);
            const terrain::GroundVerdict rock = terrain::judgeGround(
                true, 0.0, made_of != nullptr ? made_of->hardness_pa : 0.0, host.material_name_of(p.body));
            if (p.report < log_.size()) {
                LiveGroundWork &r = log_[p.report];
                r.why = "met rock " + mm(std::max(0.0, depth)) + " down: " + rock.why;
                if (rock.answer == terrain::GroundAnswer::NotSupported) r.supported = false;
            }
        }
    }
    const terrain::GroundAtDepth in = terrain::groundAt(field, p.column, std::max(0.0, depth));
    if (!in.rock) p.ground = in.name;
    const Resistance r = resistance(p, in.rock ? terrain::soilMaterial() : in.material, depth,
                                    dot(v, p.axis), dt_s);
    host.world->updateGroundBite(p.joint, r.into, r.x, r.z);
    suspend(host, p, id, v, dt_s);
    p.tip_before = tip;
    p.vn_before = dot(v, p.axis);
    p.vx_before = dot(v, p.across_x);
    p.vz_before = dot(v, p.across_z);
}

// ---- after the step -----------------------------------------------------------

void ToolTerrain::settle(const ToolTerrainHost &host, double dt_s) {
    JoltWorld &world = *host.world;
    for (Point &p : points_) {
        if (p.joint == 0) continue;
        if (host.parked && host.parked(p.body)) continue;   // set aside: not gone
        const std::optional<MatterBodyId> id = host.id_of(p.body);
        if (!id || !world.contains(*id) || !world.hasJoint(p.joint) || host.environment == nullptr) {
            finish(host, p, id && world.contains(*id));
            continue;
        }
        const RigidSnapshot s = world.snapshot(*id);
        const Vec3 tip = s.center_of_mass_world_m + s.orientation_world.rotate(p.tip_local);
        const Vec3 v = s.linear_velocity_m_s + cross(s.angular_velocity_rad_s, tip - s.center_of_mass_world_m);
        // What the ground's resistance took this step, measured from the
        // solver's own impulses: each impulse times how far the point went
        // against it -- the mean of its speeds at the two ends of the step, or
        // its speed at the end when it was being driven through faster than
        // it started (the kerf's rule, docs/cutting-model.md section 3).
        const Vec3 impulse = world.groundBiteImpulse(p.joint);
        const double vn = dot(v, p.axis), vx = dot(v, p.across_x), vz = dot(v, p.across_z);
        const double in_n_s = std::max(0.0, impulse.y);
        const double went_in = std::max({0.0, 0.5 * (p.vn_before + vn), vn});
        const double work_in = in_n_s * went_in;
        const double work_across =
            std::abs(impulse.x) * std::max(std::abs(0.5 * (p.vx_before + vx)), std::abs(vx)) +
            std::abs(impulse.z) * std::max(std::abs(0.5 * (p.vz_before + vz)), std::abs(vz));
        const double depth = dot(tip - p.entry, p.axis);
        if (depth > 0.005) {
            const Vec3 moved = tip - p.tip_before;
            const Vec3 across = moved - dot(moved, p.axis) * p.axis;
            p.sideways += length(across);
            p.pry += across;
        }
        p.deepest = std::max(p.deepest, depth);
        if (p.report < log_.size()) {
            LiveGroundWork &r = log_[p.report];
            r.impulse_n_s += in_n_s;
            r.peak_force_n = std::max(r.peak_force_n, dt_s > 0.0 ? in_n_s / dt_s : 0.0);
            r.work_j += work_in + work_across;
            r.penetration_work_j += work_in;
            r.breakout_work_j += work_across;
            r.depth_m = p.deepest;
            r.sideways_m = p.sideways;
            if (!p.at_rock) {
                const terrain::GroundAtDepth deep =
                    terrain::groundAt(host.environment->terrain(), p.column, p.deepest);
                const terrain::GroundMaterial &g = deep.rock ? terrain::soilMaterial() : deep.material;
                r.resistance_n = terrain::penetrationResistanceN(g, p.shape, p.deepest);
                r.passive_n = terrain::passiveResistanceN(g, p.deepest, leadingWidth(p));
            }
            if (!p.broke_out && loosened(host, p) > 0.0) {
                p.broke_out = true;
                r.kind = "broke out";
            }
        }
        // Out of the ground -- clear of the surface where the tip now is, or
        // drawn back past where it went in: the meeting is over, and what it
        // broke loose comes out of the ground with it.
        const terrain::TerrainField &field = host.environment->terrain();
        if (tip.y > field.heightAt(tip.x, tip.z) + kOutM || depth < -kOutM) finish(host, p, true);
    }
}

double ToolTerrain::leadingWidth(const Point &p) const {
    // The pry's own direction decides which face leads: the broad face when it
    // is pushed across it, the edge when it is pushed along it.
    const double across = std::abs(dot(p.pry, p.across_x));
    const double along = std::abs(dot(p.pry, p.across_z));
    const double total = across + along;
    const double thick = terrain::pointThicknessAt(p.shape, p.deepest);
    if (!(total > 0.0)) return p.shape.width_m;
    return (across * p.shape.width_m + along * thick) / total;
}

double ToolTerrain::loosened(const ToolTerrainHost &host, const Point &p) const {
    if (host.environment == nullptr || !(p.deepest > 0.0)) return 0.0;
    const terrain::GroundAtDepth deep = terrain::groundAt(host.environment->terrain(), p.column, p.deepest);
    const terrain::GroundMaterial &g = deep.rock ? terrain::soilMaterial() : deep.material;
    return terrain::loosenedVolumeM3(g, p.deepest, leadingWidth(p), p.sideways);
}

void ToolTerrain::condition(const ToolTerrainHost &host, LiveGroundWork &r, const Point &p) const {
    const std::optional<MatterBodyId> id = host.id_of(p.body);
    r.tool_whole = id.has_value() && host.world->contains(*id);
    r.tool_dent_m = r.tool_whole ? host.dent_of(p.body) : 0.0;
}

void ToolTerrain::finish(const ToolTerrainHost &host, Point &p, bool tool_here) {
    JoltWorld &world = *host.world;
    if (p.joint != 0 && world.hasJoint(p.joint)) world.removeJoint(p.joint);
    p.joint = 0;
    if (tool_here) {
        const std::optional<MatterBodyId> id = host.id_of(p.body);
        if (id && world.contains(*id)) world.restoreGroundContact(*id);
    }
    if (p.report >= log_.size()) {
        p.report = kNone;
        return;
    }
    LiveGroundWork &r = log_[p.report];
    const double volume = loosened(host, p);
    if (volume > 0.0 && host.environment != nullptr) {
        // What broke loose comes out through the ground's own dig, so it is
        // carried exactly as anything else dug is, and the ground's ledger
        // keeps it. Spread over the ground the wedge reached, along the way
        // the point was pried, as one even layer: the columns are what the
        // ground is made of, and they are coarser than the wedge.
        terrain::Environment &env = *host.environment;
        const terrain::TerrainField &field = env.terrain();
        Vec3 way = level(p.pry);
        if (!(length(way) > 1e-6)) way = level(p.across_x);
        way = normalized(way, Vec3{1.0, 0.0, 0.0});
        const terrain::GroundAtDepth deep = terrain::groundAt(field, p.column, p.deepest);
        const terrain::GroundMaterial &g = deep.rock ? terrain::soilMaterial() : deep.material;
        const double reach = std::max(terrain::wedgeLengthM(g, p.deepest), p.sideways);
        const double dx = field.grid().dx;
        const double width = std::max(terrain::breakoutWidthM(leadingWidth(p), p.deepest), 1.5 * dx);
        const double ax = p.entry.x, az = p.entry.z;
        const double bx = ax + reach * way.x, bz = az + reach * way.z;
        const std::size_t columns = field.columnsAlong(ax, az, bx, bz, width).size();
        if (columns > 0) {
            const double depth = volume / (static_cast<double>(columns) * dx * dx);
            const terrain::EditEffect effect = env.dig(world, ax, az, bx, bz, width, depth);
            r.loosened = effect.edit.moved;
            r.loosened_kg = effect.edit.mass_kg;
            // And the dig as an edit would say it, exactly: made again from
            // these numbers on the same ground, it takes out the same.
            r.dug = true;
            r.dug_from_m[0] = ax;
            r.dug_from_m[1] = az;
            r.dug_to_m[0] = bx;
            r.dug_to_m[1] = bz;
            r.dug_width_m = width;
            r.dug_depth_m = depth;
        }
    }
    r.kind = p.broke_out ? "broke out" : "pulled out";
    if (!tool_here && r.why.empty()) r.why = "the tool was gone before its point came out";
    condition(host, r, p);
    r.open = false;
    p.report = kNone;
}

void ToolTerrain::note(const ToolTerrainHost &host, Point &p, const std::string &kind,
                       const std::string &ground, const std::string &why, bool supported, const Vec3 &at,
                       double closing) {
    if (p.note < log_.size() && log_[p.note].open && p.note_kind == kind) return;
    closeNote(host, p);
    LiveGroundWork said;
    said.point = p.id;
    said.tool = p.body;
    said.ground = ground;
    said.kind = kind;
    said.supported = supported;
    said.why = why;
    said.at_s = host.time_s;
    said.at_m = at;
    said.closing_speed_m_s = std::max(0.0, closing);
    said.model = terrain::kGroundWorkModel;
    said.open = true;
    log_.push_back(std::move(said));
    p.note = log_.size() - 1;
    p.note_kind = kind;
}

void ToolTerrain::closeNote(const ToolTerrainHost &host, Point &p) {
    if (p.note < log_.size() && log_[p.note].open) {
        condition(host, log_[p.note], p);
        log_[p.note].open = false;
    }
    p.note = kNone;
    p.note_kind.clear();
}

// ---- the motion of a tool action ----------------------------------------------

std::optional<LiveStroke> ToolTerrain::plan(const ToolTerrainHost &host, const LiveStrike &strike,
                                            const std::string &held, const Vec3 &grip_local,
                                            std::string &why) const {
    const Point *p = nullptr;
    for (const Point &candidate : points_)
        if (candidate.attached && candidate.body == held) {
            p = &candidate;
            break;
        }
    if (p == nullptr) {
        why = held + " has no point that can go into the ground: give it one first (tool_point)";
        return std::nullopt;
    }
    const auto finite = [](const Vec3 &v) {
        return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
    };
    if (!finite(strike.target_m) || !finite(strike.shoulder_m)) {
        why = "the target and the shoulder are places: three finite numbers each";
        return std::nullopt;
    }
    const std::optional<MatterBodyId> id = host.id_of(held);
    if (!id || !host.world->contains(*id)) {
        why = "the tool is not in the world";
        return std::nullopt;
    }
    const RigidSnapshot s = host.world->snapshot(*id);
    const Vec3 up{0.0, 1.0, 0.0};
    const Vec3 g0 = s.center_of_mass_world_m + s.orientation_world.rotate(grip_local);
    const Quat r0 = s.orientation_world;
    LiveStroke out;
    out.lead_m = 0.05;
    out.let_go_at_end = false;
    out.give_up_s = std::clamp(strike.give_up_s, 0.2, 10.0);

    if (strike.lever) {
        if (p->joint == 0) {
            why = "its point is not in the ground, so there is nothing to lever: swing it in first";
            return std::nullopt;
        }
        // Turned about where the point went in -- the lip of its hole, where
        // the rest of the tool bears on the ground -- the handle coming back
        // and down towards the person and the buried point going forward
        // through the ground; then drawn straight up out of it.
        const Vec3 pivot = p->entry;
        Vec3 u = level(pivot - strike.shoulder_m);
        if (!(length(u) > 1e-3)) u = level(pivot - g0);
        if (!(length(u) > 1e-3)) u = level(s.orientation_world.rotate(cross(p->pointing_local, p->width_local)));
        u = normalized(u, Vec3{1.0, 0.0, 0.0});
        const Vec3 k = normalized(cross(up, u));
        const double turn = std::clamp(strike.lever_deg, 5.0, 80.0) * kPi / 180.0;
        constexpr int kLeverPoints = 8;
        for (int i = 0; i <= kLeverPoints; ++i) {
            const double t = static_cast<double>(i) / kLeverPoints;
            const Quat rot = qAxisAngle(k, -turn * t);
            out.path_m.push_back(pivot + rot.rotate(g0 - pivot));
            out.facings_wxyz.push_back(qNorm(qMul(rot, r0)));
        }
        const double lift = std::max(0.05, p->deepest) + 0.08;
        const Vec3 end = out.path_m.back();
        const Quat facing = out.facings_wxyz.back();
        out.path_m.push_back(end + 0.5 * lift * up);
        out.facings_wxyz.push_back(facing);
        out.path_m.push_back(end + lift * up);
        out.facings_wxyz.push_back(facing);
        out.speed_m_s = std::clamp(strike.speed_m_s, 0.3, 2.0);
        out.accel_m_s2 = 20.0;
        return out;
    }

    // A swing. The tool turns so its point comes down on the target along its
    // own axis, with its swing in the plane through the shoulder and the
    // target and the handle back towards the person; the grip goes round the
    // shoulder, and the wrist turns the tool as it goes.
    const Vec3 target = strike.target_m;
    const Vec3 shoulder = strike.shoulder_m;
    Vec3 u = level(target - shoulder);
    if (!(length(u) > 1e-3)) u = level(target - g0);
    if (!(length(u) > 1e-3)) {
        why = "the target is straight under the shoulder: swing at ground in front of you";
        return std::nullopt;
    }
    u = normalized(u);
    const Vec3 k = normalized(cross(up, u));   // turning about +k swings forward and down
    // The tool's own axes: its point, its edge, and the third square to both.
    const Vec3 handle = grip_local - p->tip_local;
    Vec3 z_local = cross(p->pointing_local, handle);
    z_local = length(z_local) > 1e-6 ? normalized(z_local) : p->width_local;
    const Vec3 y_local = p->pointing_local;
    const Vec3 x_local = cross(y_local, z_local);
    const double raise = std::clamp(strike.raise_deg, 0.0, 170.0) * kPi / 180.0;
    out.speed_m_s = std::clamp(strike.speed_m_s, 0.5, 20.0);
    out.accel_m_s2 = 400.0;

    // The whole swing for a point that comes down along `into` (a direction in
    // the swing's plane): the pose at the blow, then back from it to where the
    // swing starts. What comes back also says which way the tip itself was
    // going over the last stretch before the blow.
    struct Planned {
        std::vector<Vec3> path;
        std::vector<Quat> facings;
        Quat r_hit;
        Vec3 g_hit;
        Vec3 came;
    };
    const auto swingFor = [&](const Vec3 &into) {
        Planned plan;
        plan.r_hit = qFromBases(x_local, y_local, z_local, cross(into, k), into, k);
        plan.g_hit = target - plan.r_hit.rotate(p->tip_local) + plan.r_hit.rotate(grip_local);
        Vec3 g_start = g0;
        Quat r_start = r0;
        if (raise > 0.0) {
            // Back and up, over the shoulder: the arm half as far as the tool.
            const Vec3 g_up = shoulder + qAxisAngle(k, -0.5 * raise).rotate(plan.g_hit - shoulder);
            const Quat r_up = qNorm(qMul(qAxisAngle(k, -raise), plan.r_hit));
            constexpr int kRaisePoints = 3;
            for (int i = 0; i < kRaisePoints; ++i) {
                const double t = static_cast<double>(i) / kRaisePoints;
                plan.path.push_back(g0 + t * (g_up - g0));
                plan.facings.push_back(qSlerp(r0, r_up, t));
            }
            g_start = g_up;
            r_start = r_up;
        }
        // Round the shoulder from where it starts to where it hits, the grip's
        // distance from the shoulder going over from one to the other.
        const Vec3 rel_hit = plan.g_hit - shoulder;
        const Vec3 rel_start = g_start - shoulder;
        const Vec3 flat_hit = rel_hit - dot(rel_hit, k) * k;
        const Vec3 flat_start = rel_start - dot(rel_start, k) * k;
        const double from = std::atan2(dot(k, cross(flat_hit, flat_start)), dot(flat_hit, flat_start));
        const Vec3 correction = qAxisAngle(k, -from).rotate(rel_start) - rel_hit;
        constexpr int kArcPoints = 10;
        for (int i = 0; i <= kArcPoints; ++i) {
            const double t = static_cast<double>(i) / kArcPoints;
            const Quat rot = qAxisAngle(k, from * (1.0 - t));
            plan.path.push_back(shoulder + rot.rotate(rel_hit + (1.0 - t) * correction));
            plan.facings.push_back(qSlerp(r_start, plan.r_hit, t));
        }
        const std::size_t n = plan.path.size();
        const auto tipAt = [&](std::size_t i) {
            return plan.path[i] + plan.facings[i].rotate(p->tip_local - grip_local);
        };
        plan.came = tipAt(n - 1) - tipAt(n - 2);
        return plan;
    };
    // Twice: once with the point straight down, and again with it along the
    // way its tip was then going at the blow, so it goes in point first. A
    // swing that meets the ground side-on skids, and one that comes in at an
    // angle to its own point drags it through the ground sideways -- which is
    // a pry, and a pry is the lever's job.
    Vec3 into = -1.0 * up;
    Planned plan = swingFor(into);
    {
        Vec3 along = plan.came - dot(plan.came, k) * k;
        if (length(along) > 1e-6) {
            along = normalized(along);
            // Never shallower than 45 degrees off straight down: below that
            // the point would come in along the ground.
            if (along.y > -std::sqrt(0.5)) {
                Vec3 flat = level(along);
                flat = length(flat) > 1e-9 ? normalized(flat) : u;
                along = std::sqrt(0.5) * flat - std::sqrt(0.5) * up;
            }
            into = along;
            plan = swingFor(into);
        }
    }
    if (length(plan.g_hit - shoulder) > 3.0) {
        why = "that is out of reach: stand nearer to where you want the point to come down";
        return std::nullopt;
    }
    out.path_m = std::move(plan.path);
    out.facings_wxyz = std::move(plan.facings);
    // And on, into the ground along the point, far enough that the hand is
    // still going at full speed when the point meets it: a hand that keeps
    // hold slows down before the end of its stroke (advanceStrokeHand), and a
    // pick is not swung to stop at the surface. The ground is what stops it,
    // and the hand then only pushes it the way it is already going in.
    const double beyond = out.speed_m_s * out.speed_m_s / (2.0 * out.accel_m_s2) + 0.06;
    for (int j = 1; j <= 2; ++j) {
        const double t = static_cast<double>(j) / 2.0;
        out.path_m.push_back(plan.g_hit + (beyond * t) * into);
        out.facings_wxyz.push_back(plan.r_hit);
    }
    return out;
}

} // namespace banjo::fastlattice
