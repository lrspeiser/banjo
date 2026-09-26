#include "fastlattice/LiveWorld.hpp"
#include "machines/Circuit.hpp"
#include "fastlattice/ToolTerrain.hpp"
#include "fastlattice/PreciseRigidScene.hpp"

#include "core/Plane.hpp"
#include "core/RigidPrimitive.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticePhysics.hpp"
#include "fastlattice/Refracture.hpp"
#include "fracture/BondFailure.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "material/MaterialCompiler.hpp"
#include "rigid/JoltWorld.hpp"
#include "fracture/SustainedLoad.hpp"
#include "thermo/ThermalMechanics.hpp"
#include "thermo/ThermoJson.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <thread>
#include <deque>
#include <future>
#include <map>
#include <optional>
#include <tuple>
#include <set>
#include <unordered_set>
#include <unordered_map>

namespace banjo::fastlattice {
namespace {
// The lattice's own vector type. The support planes are templated on it, and a
// scene's Vec3 is a different struct with the same three numbers in it.
V3<double> toV3(const Vec3 &v) { return {v.x, v.y, v.z}; }

// How big a piece is, from the cells it is made of. A body authored as a box or
// a sphere reports the size it was asked for; a piece that broke off something
// was never asked for at any size, and a host still has to draw it, so it gets
// the extent of its own cells rather than nothing at all.
Vec3 cellBounds(const std::vector<std::uint32_t> &nodes,
                const std::vector<Vec3> &offsets, double cell_m) {
    if (nodes.empty()) return {cell_m, cell_m, cell_m};
    Vec3 low = offsets[nodes.front()], high = low;
    for (const std::uint32_t node : nodes) {
        const Vec3 &at = offsets[node];
        low = {std::min(low.x, at.x), std::min(low.y, at.y), std::min(low.z, at.z)};
        high = {std::max(high.x, at.x), std::max(high.y, at.y), std::max(high.z, at.z)};
    }
    // The offsets are cell CENTRES, so the piece reaches half a cell past each.
    return {high.x - low.x + cell_m, high.y - low.y + cell_m, high.z - low.z + cell_m};
}
// The turn from one orientation to another, as axis times angle. Defined with
// the blades at the end of this file; the hand's wrist needs it too.
[[nodiscard]] Vec3 turnBetween(const Quat &from, const Quat &to);
// How heavy a push at `arm` from the centre of mass feels, direction by
// direction. Defined with the blades; the wielding hand is shaped by it.
[[nodiscard]] Mat3 gripMassMatrix(double mass_kg, const Mat3 &inertia_world, const Vec3 &arm);

// A force in the words a person reads it in.
std::string newtons(double n) {
    char text[48];
    if (std::abs(n) >= 1000.0) std::snprintf(text, sizeof text, "%.2f kN", n / 1000.0);
    else std::snprintf(text, sizeof text, "%.0f N", n);
    return text;
}

std::string percent(double fraction) {
    char text[24];
    std::snprintf(text, sizeof text, "%.0f%%", 100.0 * fraction);
    return text;
}

// What taking a body's load-bearing matter away is called, for its material:
// oak's burns, ice's melts (thermo::MechanicalLaw::gone).
std::string goneWord(const std::string &material) {
    const thermo::MechanicalLaw *law = thermo::lawFor(material);
    return law != nullptr ? law->gone : std::string("burned");
}

// What a member is now, in one line: the words a joint made of it parts with.
std::string describeMember(const LiveMaterialState &m) {
    char text[640];
    const thermo::SectionState &s = m.section;
    if (m.law.empty()) {
        std::snprintf(text, sizeof text, "%s is %s, which has no law for heat: nothing about it changed",
                      m.name.c_str(), m.material.c_str());
        return text;
    }
    std::snprintf(text, sizeof text,
                  "%s: surface %.0f K (hottest %.0f K), core %.0f K; %.1f mm %s away and %.1f mm "
                  "char; %.0f x %.0f mm of its %.0f x %.0f mm section still sound; %s of its tension, "
                  "%s of its shear and %s of its stiffness left",
                  m.name.c_str(), m.surface_k, m.peak_surface_k, m.core_k, 1000.0 * s.consumed_m,
                  goneWord(m.material).c_str(),
                  1000.0 * s.char_m, 1000.0 * s.sound_breadth_m, 1000.0 * s.sound_depth_m,
                  1000.0 * s.breadth_m, 1000.0 * s.depth_m, percent(s.tension).c_str(),
                  percent(s.shear).c_str(), percent(s.axial_stiffness).c_str());
    return text;
}

// The hand on a grip, as ONE law: a step pushes with it and a preview of a
// stroke integrates it, so the two cannot come to disagree about what a hand
// can do. Defined with the blades, where the law was first written down.
struct GripPull {
    Vec3 force{}, torque{}, grip{};
};
[[nodiscard]] GripPull gripPull(const RigidMechanicalState &held, const Vec3 &grip_local,
                                const Vec3 &wanted_at, const Vec3 &wanted_velocity,
                                const Quat &wanted_facing, double strength_n,
                                double torque_n_m, const Vec3 &gravity);

// A stroke's path (LiveStroke): how far along it each of its points is.
[[nodiscard]] std::vector<double> arcLengths(const std::vector<Vec3> &path) {
    std::vector<double> at(path.size(), 0.0);
    for (std::size_t i = 1; i < path.size(); ++i) at[i] = at[i - 1] + length(path[i] - path[i - 1]);
    return at;
}

// The point `along` metres down a path.
[[nodiscard]] Vec3 pointAlong(const std::vector<Vec3> &path, const std::vector<double> &at,
                              double along) {
    if (!(along > 0.0)) return path.front();
    for (std::size_t i = 1; i < path.size(); ++i) {
        if (along > at[i] && i + 1 < path.size()) continue;
        const double span = at[i] - at[i - 1];
        const double s = span > 0.0 ? std::clamp((along - at[i - 1]) / span, 0.0, 1.0) : 1.0;
        return path[i - 1] + s * (path[i] - path[i - 1]);
    }
    return path.back();
}

// How far down a path the point on it nearest `p` is: where a grip has got to.
[[nodiscard]] double alongNearest(const std::vector<Vec3> &path, const std::vector<double> &at,
                                  const Vec3 &p) {
    double best = 0.0, nearest = std::numeric_limits<double>::max();
    for (std::size_t i = 1; i < path.size(); ++i) {
        const Vec3 d = path[i] - path[i - 1];
        const double span2 = lengthSquared(d);
        const double s = span2 > 0.0 ? std::clamp(dot(p - path[i - 1], d) / span2, 0.0, 1.0) : 0.0;
        const double gap = lengthSquared(path[i - 1] + s * d - p);
        if (gap < nearest) {
            nearest = gap;
            best = at[i - 1] + s * (at[i] - at[i - 1]);
        }
    }
    return best;
}

// One step of a stroke's hand: faster by accel*dt, up to the speed asked, and
// never further ahead of the grip than the lead -- the hand is ON the thing
// and cannot run on without it. That clamp is the whole difference between a
// hand and a target: measured without it, a 33 kg iron ball "thrown" at a 12 m/s
// sweep left at 1.5 m/s, because the target was 700 mm ahead of it and the
// hand let go before the ball had been pushed through the stroke at all.
//
// Held back, it goes only as fast as it actually went. A hand that waited on a
// heavy thing has not got up to speed without it, and must not leap ahead the
// moment the thing gives.
struct StrokeHand {
    double along{}, speed{};
};
[[nodiscard]] StrokeHand advanceStrokeHand(const LiveStroke &stroke, double length_m,
                                           double along, double speed, double grip_along,
                                           double most_accel_m_s2, double dt_s) {
    const double accel = std::min(stroke.accel_m_s2, most_accel_m_s2);
    double wants = std::min(stroke.speed_m_s, speed + accel * dt_s);
    // A stroke that keeps hold at the end ARRIVES there: a hand slows down no
    // faster than it speeds up. One that stopped dead at the end of a draw left
    // the string doing 0.38 m/s a step later with its hand stood still, and the
    // pull that brought it up short rang it -- measured, from -0.38 to +0.24 and
    // back to -1.57 m/s inside nine steps, which snatched a 1 kg arrow off its
    // nock. A throw lets go at the end at full speed, and that is its point.
    if (!stroke.let_go_at_end)
        wants = std::min(wants, std::sqrt(2.0 * accel * std::max(0.0, length_m - along)));
    const double next = std::max(0.0, std::min({along + wants * dt_s,
                                                grip_along + stroke.lead_m, length_m}));
    const double went = std::max(0.0, next - along) / dt_s;
    return {next, std::min(wants, went)};
}

// How fast the hand itself can get going with this in it. The strength has to
// move the hand and arm as well as the thing -- a person throws a tennis ball
// far faster than a shot, and not because the shot is hard to hold -- and
// whatever of it is holding the thing up is not there to throw it with.
[[nodiscard]] double handAcceleration(double strength_n, double hand_mass_kg, double mass_kg,
                                      const Vec3 &gravity) {
    const double spare = std::max(0.0, strength_n - mass_kg * length(gravity));
    const double moving = hand_mass_kg + mass_kg;
    return moving > 0.0 ? spare / moving : std::numeric_limits<double>::max();
}

// Which way a path runs at `along`.
[[nodiscard]] Vec3 pathDirection(const std::vector<Vec3> &path, const std::vector<double> &at,
                                 double along) {
    return normalized(pointAlong(path, at, std::min(at.back(), along + 1e-3)) -
                      pointAlong(path, at, std::max(0.0, along - 1e-3)));
}

// Why a stroke cannot be made as asked, or "" when it can.
[[nodiscard]] std::string strokeProblem(const LiveStroke &stroke) {
    if (stroke.path_m.size() < 2 || stroke.path_m.size() > 16)
        return "a stroke's path is two to sixteen points";
    for (const Vec3 &p : stroke.path_m)
        if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z) ||
            std::abs(p.x) > 1e5 || std::abs(p.y) > 1e5 || std::abs(p.z) > 1e5)
            return "a stroke's path has a point that is not a place";
    if (!(stroke.speed_m_s > 0.0 && stroke.speed_m_s <= 50.0))
        return "a stroke's speed is more than 0 and at most 50 m/s";
    if (!(stroke.accel_m_s2 > 0.0 && stroke.accel_m_s2 <= 5000.0))
        return "a stroke's acceleration is more than 0 and at most 5000 m/s2";
    if (!(stroke.lead_m >= 0.001 && stroke.lead_m <= 0.5))
        return "a stroke's lead is 1 mm to 0.5 m";
    if (!(stroke.give_up_s > 0.0 && stroke.give_up_s <= 30.0))
        return "a stroke gives up after more than 0 and at most 30 s";
    if (!(arcLengths(stroke.path_m).back() > 1e-4)) return "a stroke's path has no length";
    if (!stroke.facings_wxyz.empty()) {
        if (stroke.facings_wxyz.size() != stroke.path_m.size())
            return "a stroke's facings are one for each point of its path, or none";
        for (const Quat &q : stroke.facings_wxyz) {
            const double size = std::sqrt(q.w * q.w + q.x * q.x + q.y * q.y + q.z * q.z);
            if (!std::isfinite(size) || !(size > 1e-9))
                return "a stroke's facing is a quaternion with a size, w first";
        }
    }
    return {};
}

// Which way the hand wants the thing to face `along` metres down a path that
// turns as it goes (LiveStroke::facings_wxyz): from one point's facing to the
// next's, by the shortest turn between them.
[[nodiscard]] Quat facingAlong(const std::vector<Quat> &facings, const std::vector<double> &at,
                               double along) {
    const auto unit = [](const Quat &q) {
        const double n = std::sqrt(q.w * q.w + q.x * q.x + q.y * q.y + q.z * q.z);
        return Quat{q.w / n, q.x / n, q.y / n, q.z / n};
    };
    if (facings.size() == 1 || !(along > 0.0)) return unit(facings.front());
    std::size_t i = 1;
    while (i + 1 < at.size() && along > at[i]) ++i;
    const double span = at[i] - at[i - 1];
    const double t = span > 0.0 ? std::clamp((along - at[i - 1]) / span, 0.0, 1.0) : 1.0;
    const Quat a = unit(facings[i - 1]);
    Quat b = unit(facings[i]);
    double c = a.w * b.w + a.x * b.x + a.y * b.y + a.z * b.z;
    if (c < 0.0) {
        b = Quat{-b.w, -b.x, -b.y, -b.z};
        c = -c;
    }
    if (c > 0.9995)
        return unit(Quat{a.w + t * (b.w - a.w), a.x + t * (b.x - a.x), a.y + t * (b.y - a.y),
                         a.z + t * (b.z - a.z)});
    const double angle = std::acos(std::clamp(c, -1.0, 1.0));
    const double wa = std::sin((1.0 - t) * angle) / std::sin(angle);
    const double wb = std::sin(t * angle) / std::sin(angle);
    return unit(Quat{wa * a.w + wb * b.w, wa * a.x + wb * b.x, wa * a.y + wb * b.y, wa * a.z + wb * b.z});
}
} // namespace

// One fracture in progress: everything the three phases pass between them.
struct LiveWorld::Pending {
    std::string name;
    double window_s{};
    // The step the run is taken at: its own lattice's, as it is (prepared).
    double dt_s{};
    // Set when prepare decided there was nothing to run -- an anchored body, a
    // name that is not there, something in a hand. `answer` is what fracture()
    // would have returned.
    bool settled{};
    std::size_t answer{};
    bool worked{};
    double cost_ms{};
    // Captured, and started. They are not the same moment for anything that had
    // to wait its turn, and reporting the gap as cost made the log say a
    // fracture took four seconds when it took thirty milliseconds and spent the
    // rest queued. A log that misattributes time is worse than no log: it sends
    // you to optimise the wrong thing.
    std::chrono::steady_clock::time_point began{};
    std::chrono::steady_clock::time_point started{};
    double waited_ms{};

    FragmentLattice island{};
    LatticeState state{};
    std::unique_ptr<LatticeBackend> backend;
    RunControl control{};
    double entry_kinetic_j{}, entry_elastic_j{};
    SphereState<double> parked{};
    RunStatus status{};
    std::size_t which{};
    std::size_t anvil{static_cast<std::size_t>(-1)};
    std::vector<std::size_t> island_bodies;
    std::unordered_map<std::size_t, RigidSnapshot> poses_before;
    std::unordered_map<std::uint32_t, std::size_t> body_of_node;
    RigidSnapshot snap{};
    const MaterialDefinition *struck_material{};
    double yield_extension{};
    // Set when this run was started before the collision happened, so it can be
    // checked against the collision that actually turned up.
    // The cells of the bodies that were ADMITTED for breaking at this contact.
    //
    // An island has to contain whatever struck the thing being broken -- a body
    // entered alone is a free-flying object with no stress in it and cannot
    // break however hard it was hit. But the striker is then in a lattice run
    // that is not about it, and its own bonds can fail there: measured, an iron
    // ball hit a glass plate at 11.5 m/s against its own breaking threshold of
    // 25.03 m/s, with every contact reporting would_break false, and came out
    // of the plate's run as twenty-nine pieces.
    //
    // A threshold is "the speed below which nothing CAN happen". A body that
    // never cleared its own breaking bar is not allowed to come apart in any
    // island -- somebody else's, or its own when what it was asked about would
    // only dent it (see prepared) -- so only the cells of the bodies that did
    // are recorded here, and every other bond is put back before the pieces are
    // counted.
    //
    // Kept as cells rather than body numbers because cells are not renumbered
    // by anything, and the body table is.
    std::unordered_set<std::uint32_t> may_break;
    bool guessed{};
    std::string guessed_striker;
    double guessed_speed{};
    Vec3 guessed_at{};
    // A sustained load rather than a blow (fracture/SustainedLoad.hpp): the
    // body alone, held up where it rests and loaded by the weight of what rests
    // on it, solved for equilibrium rather than run through a few milliseconds
    // of a wave. In the island's own node numbering.
    bool sustained{};
    SustainedLoadScene load{};
    SustainedLoadResult statics{};
    double load_n{};
    std::size_t supported_cells{}, loaded_cells{};
};

// ---- one material state: shared rules (docs/thermal-mechanics.md) -----------
namespace {
// Below this share of a cell's matter, the cell has burned away.
constexpr double kGoneShare = 0.02;
// The softest a bond can be and still be one is banjo::kSoftestBond, which the
// bond law itself owns (matter/Lattice.hpp).
// A box or a sphere is cut again once its burned depth has moved this far.
constexpr double kReviseDepthM = 2.0e-4;
// A section a hundredth weaker than statics last held, or a load a hundredth
// heavier, is a different question and is asked again.
constexpr double kStaticsAskAgain = 0.01;

bool wholeFactors(const thermo::ZoneFactors &f) {
    return f.stiffness == 1.0 && f.tension == 1.0 && f.compression == 1.0 && f.shear == 1.0;
}

// A bond as heat has left it: its stiffness and each strength by the field's
// factors, applied once. A damage threshold is a stretch, and a stretch is a
// strength over a modulus, so each goes by its strength's factor over the
// stiffness's -- and the force a bond fails at goes by its strength's factor
// alone, which is the law. False when it carries nothing at all.
// What rests on a box whose faces have just come in by burning comes down with
// its top, and the box comes down onto what it stands on -- by exactly what came
// off each face, and without waking anything -- rather than each dropping onto
// what is left and settling. Burning takes wood away a little at a time, but the
// shape is cut again only every kReviseDepthM. Woken at every cut to settle, the
// owner's 258 kg block on its 80 mm beam (40 mm cells), sunk a few millimetres
// into it -- Jolt lets a resting body sink 20 mm (mPenetrationSlop) without
// pushing it back -- rolled a little further each time it was awake: 0.14
// degrees before the first cut, 1.9 after eight, 9.4 after eighteen, 28 mm to
// one side, and then off a beam that had not broken. Carried exactly and left
// asleep, it has nothing to settle. The plan is made before the cut, against
// the box as it is; a joint anywhere in the stack, or anything standing on
// something else as well, and it declines, and the solver settles the stack as
// before. Extents are world-aligned boxes, so a body slightly tilted is carried
// by its lowest point.
struct Recession {
    bool applies{};
    bool lower_burned{};
    double recess{}, top_drop{};
    std::vector<std::size_t> carried;
};

Recession planRecession(const JoltWorld &world, const std::vector<LiveBodyPose> &described,
                        const std::vector<MatterBodyId> &body_of, const std::vector<bool> &jointed,
                        double ground_y, std::size_t burned, const Vec3 &was_m, const Vec3 &now_m) {
    constexpr double kRest = 0.02;   // the load survey's whisker, for the same reason
    const std::size_t count = std::min({described.size(), body_of.size(), jointed.size()});
    if (burned >= count || described[burned].anchored || jointed[burned] || !world.contains(body_of[burned]))
        return {};
    const auto halfOf = [](const Quat &q, const Vec3 &h) {
        const Vec3 ex = q.rotate(Vec3{h.x, 0.0, 0.0}), ey = q.rotate(Vec3{0.0, h.y, 0.0}),
                   ez = q.rotate(Vec3{0.0, 0.0, h.z});
        return Vec3{std::abs(ex.x) + std::abs(ey.x) + std::abs(ez.x), std::abs(ex.y) + std::abs(ey.y) + std::abs(ez.y),
                    std::abs(ex.z) + std::abs(ey.z) + std::abs(ez.z)};
    };
    struct Extent {
        Vec3 centre, half;
        bool known{};
    };
    std::vector<Extent> at(count);
    for (std::size_t k = 0; k < count; ++k) {
        if (!world.contains(body_of[k])) continue;
        const RigidSnapshot s = world.snapshot(body_of[k]);
        const LiveBodyPose &p = described[k];
        at[k].centre = s.center_of_mass_world_m;
        if (p.shape == "sphere")
            at[k].half = Vec3{0.5 * p.dimensions_m.x, 0.5 * p.dimensions_m.x, 0.5 * p.dimensions_m.x};
        else if (p.shape == "box")
            at[k].half = halfOf(s.orientation_world, 0.5 * p.dimensions_m);
        else
            at[k].half = 0.5 * p.dimensions_m;   // a hull: the box of its cells
        at[k].known = true;
    }
    const Quat turn = world.snapshot(body_of[burned]).orientation_world;
    const Vec3 before = halfOf(turn, 0.5 * was_m);
    const double recess = before.y - halfOf(turn, 0.5 * now_m).y;
    if (!(recess > 0.0)) return {};
    at[burned].half = before;   // everything below is judged against the box as it was
    const auto restsOn = [&](std::size_t upper, std::size_t lower) {
        if (upper == lower || !at[upper].known || !at[lower].known) return false;
        const double underside = at[upper].centre.y - at[upper].half.y;
        const double top = at[lower].centre.y + at[lower].half.y;
        return std::abs(underside - top) < kRest &&
               std::abs(at[upper].centre.x - at[lower].centre.x) < at[upper].half.x + at[lower].half.x &&
               std::abs(at[upper].centre.z - at[lower].centre.z) < at[upper].half.z + at[lower].half.z;
    };
    const auto onTheFloor = [&](std::size_t k) {
        return std::abs(at[k].centre.y - at[k].half.y - ground_y) < kRest;
    };
    bool stands = onTheFloor(burned);
    for (std::size_t k = 0; k < count && !stands; ++k) stands = restsOn(burned, k);
    // Its underside rose by the recess: standing on something, it comes down by
    // that, and its top comes down by twice it.
    const double top_drop = stands ? 2.0 * recess : recess;
    std::vector<bool> moved(count, false);
    moved[burned] = true;
    std::vector<std::size_t> carried, frontier{burned};
    while (!frontier.empty()) {
        const std::size_t base = frontier.back();
        frontier.pop_back();
        for (std::size_t k = 0; k < count; ++k) {
            if (moved[k] || described[k].anchored || !restsOn(k, base)) continue;
            // A joint on it, or a second support under it: the solver's to settle.
            if (jointed[k]) return {};
            bool elsewhere = onTheFloor(k);
            for (std::size_t other = 0; other < count && !elsewhere; ++other)
                elsewhere = !moved[other] && restsOn(k, other);
            if (elsewhere) return {};
            moved[k] = true;
            carried.push_back(k);
            frontier.push_back(k);
        }
    }
    Recession plan;
    plan.applies = true;
    plan.lower_burned = stands;
    plan.recess = recess;
    plan.top_drop = top_drop;
    plan.carried = std::move(carried);
    return plan;
}

// What heat has left a bond, by the one law that says what any factor does to
// a bond (banjo::weakenBond, matter/Lattice.hpp). A declared joint weakens the
// same way, at asset build, so the two cannot drift apart.
bool weakenBond(BondRest &bond, const thermo::ZoneFactors &f) {
    return banjo::weakenBond(bond, BondFactors{f.stiffness, f.tension, f.compression, f.shear});
}

// A cell below kGoneShare that the revision has not yet taken out (it runs at
// the network's stride) keeps that much, so nothing in a run has no mass.
thermo::CellShare atLeast(thermo::CellShare share) {
    const double left = share.remaining();
    if (left >= kGoneShare) return share;
    if (!(left > 0.0)) return {kGoneShare, 0.0};
    const double scale = kGoneShare / left;
    return {share.surface * scale, share.core * scale};
}

// Where a joint holds one of its ends, in that end's body: a pin's two ends
// share a point, a rope's, a spring's and a pulley's are tied at their own.
template <typename Joint>
Vec3 &jointPoint(Joint &joint, int end) {
    if (end == 0) return joint.point_local_a;
    const bool tied = joint.kind == JoltWorld::JointKind::Link ||
                      joint.kind == JoltWorld::JointKind::Elastic ||
                      joint.kind == JoltWorld::JointKind::Pulley;
    return tied ? joint.point_local_b_tie : joint.point_local_b;
}

Quat composeTurns(const Quat &a, const Quat &b) {
    return {a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z, a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
            a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x, a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w};
}

// Defined with the blades, further down: every bond among these cells that
// crosses a kerf's plane. A piece rebuilt because its cells burned away hands
// its kerfs on exactly as a cut piece does.
template <class KerfT>
void findCrossings(KerfT &kerf, const std::vector<std::uint32_t> &nodes,
                   const std::vector<Vec3> &offsets, const LatticeAsset &asset);
}  // namespace

// What a body's matter is measured against, and what has been done to its shape
// because of it (docs/thermal-mechanics.md, "One material state").
struct LiveWorld::MatterRecord {
    // The reference box: as authored for a box or a sphere, the cells' box for
    // anything else. Taken once and never again from what is left -- taking it
    // from what is left would burn the same share away twice.
    Vec3 box_m{};
    // Its centre and axes in the body's own frame. An authored shape is centred
    // on its centre of mass; a tilted box's axes are its tilt.
    Vec3 centre_m{};
    Quat turn{};
    bool round{};
    // The burned depth the collision shape was last cut to.
    double applied_m{};
    // Times the shape has been changed where it stands.
    unsigned revision{};
    // Cells whose matter burned away entirely, since this record was made.
    std::size_t cells_burned{};
    // As of the last revision: the volume left and the bond summary a fracture
    // run would be given (LiveMaterialState).
    double remaining_volume_m3{-1.0};
    double bond_tension_min{1.0}, bond_tension_mean{1.0}, bond_stiffness_mean{1.0};
    // The field those were worked out from. A bond summary is a sum over every
    // bond of the body -- hundreds per cell's worth -- so it is worked out
    // again only when the field has moved, not at every stride.
    thermo::ZoneFactors seen_surface{}, seen_core{};
    double seen_consumed_m{-1.0};
    std::size_t seen_cells{};
    // Whether the admission bound is the heated one, to put the cold one back
    // when the body recovers.
    bool limits_heated{};
    bool reference_inferred{};  // Legacy primitive migration; original history was not saved.
};

// What heat has done to the cells a lattice run is about to be given.
struct LiveWorld::HeatedCells {
    // Per cell of a heated body: its factors against the same cell cold and
    // whole, and what it weighs now.
    std::unordered_map<std::uint32_t, thermo::ZoneFactors> factors;
    std::unordered_map<std::uint32_t, double> mass_kg;
    // Per heated body, the mean of its cells' factors.
    std::unordered_map<std::string, thermo::ZoneFactors> mean;
};

namespace {

// One authored part of a scene -- a body, or the bodies of one join -- as a
// saved world names it (LiveWorld::snapshot "parts"), so that a world saved
// before the scene changed can find each part's cells again in the scene as it
// is now (LiveWorld::open with a carry). The scene generates each part's cells
// on their own, from that part's own definition, and lays the parts end to end
// (buildTileImpactSetup, mergeLattices): a part is one run of cells and one run
// of bonds, and an unchanged part is the same runs moved by where it now begins.
struct PartPrint {
    std::uint32_t node_begin{}, node_end{}, bond_begin{}, bond_end{};
    // Its cells and bonds in a few numbers, as fingerprintOf takes the whole
    // lattice's: "" when they are not one run each, which no scene builds and
    // which could not then be carried.
    std::string cells;
    // Every field its bodies were authored with, and what the scene declares
    // of their heat.
    std::string definition, heat;
    std::vector<std::string> bodies;
    bool anchored{};
};

}  // namespace

struct LiveWorld::Impl {
    TileImpactRequest request{};
    std::unique_ptr<TileImpactSetup> setup;
    std::unique_ptr<JoltWorld> world;
    std::map<std::string, PreciseRigidBody> precise_bodies;
    void requireLatticeRoom(const char *operation) const {
        if (!precise_bodies.empty())
            throw std::invalid_argument(std::string(operation) + ": precise-rigid rooms currently support motion, picking, carrying and joints only; internal failure, thermal mechanics, blades and fabrication are unavailable");
    }
    // Heat on an exact body: its matter has no thermal model yet (thermoShapes
    // leaves it out), so it is refused by name rather than lost silently.
    void refuseExactHeat(const std::string &name, const char *operation) const {
        if (!name.empty() && precise_bodies.count(name) != 0)
            throw std::invalid_argument(std::string(operation) + ": " + name +
                                        " is an exact (precise rigid) body, and heat is not modelled for exact "
                                        "bodies yet: only things made of cells can be heated");
    }
    // An exact compound rather than a body made of cells.
    [[nodiscard]] bool isPrecise(std::size_t body) const {
        return body < described.size() && !described[body].mechanical_model.empty();
    }
    // Two exact bodies on a pin, a groove or a weld are held by that joint, not
    // by their surfaces: a bearing's axle runs through its mount by design, and
    // welded parts meet face to face. So while the joint stands the pair's
    // contacts are the joint's, and Jolt leaves them alone. Pairs joined by a
    // rope, a spring, a pulley or a drum still collide, as the things they are,
    // and so does anything made of cells, which keeps the clearance it was
    // built with (workshop_articulation demands it).
    std::set<std::pair<MatterBodyId, MatterBodyId>> held_by_joints;
    void settleJointedContacts();
    std::vector<LiveBodyPose> described;   // one per rigid fragment, static parts
    std::vector<MatterBodyId> body_of;     // parallel to described
    // What each body is made of, kept because breaking one means rebuilding its
    // lattice from the parent it was cut out of.
    std::vector<std::vector<std::uint32_t>> nodes_of;
    std::vector<FragmentFractureLimits> limits_of;
    std::vector<double> impedance_of;
    std::vector<double> density_of;
    // What each PART of the scene is made of, in the words the room uses.
    //
    // Filled once, when the scene opens, because that is the only place both
    // halves are in hand at the same time: the part index, and the common name
    // the bodies carry. A piece works out what it is from the part its cells
    // mostly belong to, and looking that up through whichever body happened to
    // be in the island was wrong twice over -- a part with no body in the
    // island gave a piece no material at all ("2,833 g of "), and a part whose
    // slot had been claimed by something else gave it the wrong one (iron
    // shards reported as 4.3 kg of glass where there were 2.5).
    std::vector<std::string> material_of_part;
    // This step's contacts, which is what breakable() and the step-back
    // decision are about: a body that has already been answered for must not be
    // re-offered on the strength of a contact from three steps ago.
    std::vector<LiveImpact> last_impacts;
    // Every contact since the host last said it had read them. The hardest of
    // each pair survives, because a landing reports the same pair many times as
    // it settles and the one that matters is the one that arrived.
    std::vector<LiveImpact> reported;
    // For each body the last step would have broken, the body that hit it, or
    // npos for the ground. An island built without the thing that struck it is
    // a free-flying object with no stress in it, which breaks nothing.
    std::unordered_map<std::size_t, std::size_t> partner_of;
    bool stepped_back{};
    LiveOutcome last_outcome{LiveOutcome::Nothing};
    LiveBreakCost last_break{};
    std::vector<LiveDelay> delays;
    std::unique_ptr<LiveWorld::Pending> pending;
    std::future<void> worker;
    // Breaks that arrived while one was already being worked out.
    //
    // They are PREPARED at the moment they are detected -- from the rolled-back
    // step, which is the only state that still has the closing speed in it --
    // and only the expensive part waits. Preparing is a copy; the run is the
    // third of a second.
    //
    // Without this the clock simply stopped. A break the world has not resolved
    // is a step it will not take, and the host cannot resolve it because asking
    // for a second fracture while one is running gets nothing back. So the
    // world sat at one instant for as long as the run took: measured in the
    // owner's own session, 756 ms of wall clock in which the world advanced
    // 0 ms, twice in one cascade.
    std::deque<std::unique_ptr<LiveWorld::Pending>> queued;
    // A run started for a collision that has not happened yet. Kept apart from
    // `pending` on purpose: nothing has actually broken, so the world must look
    // exactly as it did -- nothing is pinned, `working_on` is empty, and a host
    // behaves as though no fracture were running, because none is.
    std::unique_ptr<LiveWorld::Pending> guessing;
    std::future<void> guess_worker;
    // How many passes in a row the collision a guess was made for has not been
    // expected. One is nothing -- the instant somebody lets go of a thing, it
    // stops being a held drop and has not yet become a falling one, and a guess
    // binned in that gap is binned at the exact moment it was about to pay.
    // That happened: a run started while the object was being held, finished
    // 816 ms of work, and was thrown away on release.
    int guess_unseen{};
    LiveWorld::Foresight guess{};
    double guess_error_pct{};
    // Pinned while their fracture is worked out, so they do not carry on as
    // though nothing were about to happen to them. A ball that bounced off a
    // pane which was in fact shattering would have to be put back afterwards,
    // and that correction is more jarring than the wait it replaced.
    std::vector<std::size_t> held_for_fracture;
    // How far ahead to look, and how often. Looking every step would cost a ray
    // per moving body per step; every eighth is thirty times a second at the
    // rate a live host runs, which is far finer than the tenths of a second
    // this is trying to see coming.
    // Far enough ahead to be worth having: the lattice run costs about as long
    // as a two-metre fall takes, so a horizon shorter than that can only ever
    // narrate what is about to happen rather than get ahead of it. It was 0,
    // which means off -- and nothing in the playground ever turned it on, so
    // the foresight this engine already had was never once used.
    double foresee_horizon_s{2.5};
    std::uint64_t steps_taken{};
    // What has already been said about, so one approach is not reported on
    // every step for a third of a second.
    std::set<std::string> foreseen;
    // The rigid step that was taken back. The lattice has to cover it before it
    // can cover the impact, because the world is that far short of contact.
    double last_dt_s{};
    // Where each parent cell sits in its body's frame, in parent node order --
    // the same array the batch lane keeps, because buildFragmentLattice reads
    // it that way. Rewritten whenever a body is replaced by its pieces.
    std::vector<Vec3> cell_offset_m;
    // How far a point in a body's own frame stands off that body's matter: the
    // distance to its nearest cell centre. Next to nothing for a pin through
    // the middle of a cell, half a cell for one on a face -- and for a pin put
    // on the face of something ELSE, beside the body, whatever gap was left
    // between the two, which is where the playground's chat puts a hinge.
    [[nodiscard]] double standOff(std::size_t body, const Vec3 &local) const {
        double nearest = -1.0;
        for (const std::uint32_t node : nodes_of[body]) {
            if (node >= cell_offset_m.size()) continue;
            const double gap = length(cell_offset_m[node] - local);
            if (nearest < 0.0 || gap < nearest) nearest = gap;
        }
        return std::max(0.0, nearest);
    }
    // Permanent extension a bond carries. Zero in a world that has not broken
    // anything yet; a piece that has flowed comes back having flowed.
    std::vector<double> plastic_extension_m, plastic_strain_m;
    MatterBodyId next_body_id{1000};
    // How many cells one authored part has, so a component that is all of them
    // can be recognised as still being that object rather than a piece of it.
    std::vector<std::size_t> part_cells;
    [[nodiscard]] std::size_t cellsOfPart(std::size_t part) const {
        return part < part_cells.size() ? part_cells[part] : 0;
    }
    // The floor is concrete, not a rigid abstraction: it has a finite impedance
    // and the admission test uses it like any other partner.
    double ground_impedance{};
    std::unordered_map<std::string, std::size_t> index_of;
    double time_s{};
    std::size_t holding{static_cast<std::size_t>(-1)};
    // Where the hand is. A held body is put back here after every step, which
    // is what makes it a hold rather than a shove: gravity and contacts still
    // act on everything else, and the held object simply does not move unless
    // the hand does.
    Vec3 held_at{};
    Quat held_facing{};
    // How hard the hand can pull on something attached to other things.
    //
    // 800 N is a hard two-handed heave -- enough to draw a stiff bow, work a
    // winch or wrench a gate open, and not enough to tear the gate off its
    // hinges, which is the line this number draws.
    double hand_strength_n{800.0};
    // Bodies that were put back into the lattice for this contact and came
    // through it whole.
    //
    // Without this the world deadlocks. A step that would break something is
    // taken back, so the world sits one step short of the impact. If the
    // fracture then finds the object HELD, nothing has changed -- the next step
    // meets the same contact, is judged breakable again, and is taken back
    // again, for ever. The scene freezes and the host is told the same thing
    // over and over.
    //
    // An object that has already been tried at this contact therefore stops
    // being a reason to refuse a step. It is cleared again the moment its
    // contacts stop being hard enough to break it, which is what happens as
    // soon as the two bodies separate.
    std::set<std::string> held_through;
    // What is carrying more than it can hold up, from the last survey. Kept
    // rather than recomputed on every ask, because a host reads it once a frame
    // and the survey is a stride thing.
    std::vector<LiveOverload> overloaded;
    // Heat changed what something can carry since the last survey: survey
    // again on the next step rather than at the stride. A load that has not
    // moved does not need asking about -- a section that has shrunk under it
    // does. See refreshMechanics.
    bool survey_due{};
    // The bending factor each heated body was last surveyed at.
    std::unordered_map<std::string, double> bending_seen;
    // What elastic elements have handed the thermal network as heat because
    // their matter softened while stretched (negative when one stiffened again
    // and took it back). The same number is a crossing in the network's ledger.
    double elastic_to_heat_j{};
    // For an overloaded body, the heaviest thing sitting on it.
    //
    // The island a fracture is run on is built from the CONTACT that caused it,
    // and a sustained load has no contact -- so an overloaded shelf would go
    // into the lattice on its own, with nothing pressing on it, and come out
    // whole however much was piled on. This is what gives it its load back.
    std::unordered_map<std::size_t, std::size_t> bearing_on;
    // For an overloaded body, from the same survey: what it rests on, and what
    // rests on it with the weight each brings (its own and everything stacked
    // above it). By name, because indices do not survive a break. This is what
    // a sustained load's statics is set up from.
    struct Sustained {
        std::vector<std::string> on;
        std::vector<std::pair<std::string, double>> loads_n;
        // Held up by the ground, on its own feet, rather than by anything in
        // `on`: a table, which is one body and has nothing under it.
        bool on_ground{};
    };
    std::unordered_map<std::string, Sustained> sustained_by;
    // What statics last said about each body it was asked about, for reports.
    struct SustainedAnswer {
        double time_s{};
        std::string stop;
        double load_n{};
        double first_failure_ratio{};
        double deflection_m{};
        std::size_t bonds_removed{}, rounds{}, solves{}, supported_cells{}, loaded_cells{}, pieces{};
        double cost_ms{};
    };
    std::unordered_map<std::string, SustainedAnswer> sustained_answers;
    // A body statics has just said holds, with the section and the load it
    // held at. It is not offered again until one of them moves -- a load does
    // not go away by itself, and asking the same question of the same answer
    // every quarter of a second is waste and noise.
    struct HeldAt {
        double capacity_fraction{1.0};
        double carrying_n{};
    };
    std::unordered_map<std::string, HeldAt> statics_held;
    // What each part is made of, in the engine's terms, so a survey can ask a
    // body what it can take without going back through the scene.
    std::vector<double> tensile_of;
    // And in compression: a beam gives on whichever side of its section
    // reaches its strength first. Zero where the material declares none.
    std::vector<double> compressive_of;
    // Heat, chemistry and gas (thermo/ThermoWorld.hpp). Null until something
    // declares any, so a world without them pays nothing for them.
    std::unique_ptr<thermo::ThermoWorld> thermo;
    // Terrain and water (terrain/Environment.hpp). Null unless the scene
    // declares them, so a room without them pays nothing.
    std::unique_ptr<terrain::Environment> environment;
    // Meltwater that has run off ice since the world opened: into the room's
    // water under it, or off across the floor where there is none to take it.
    double meltwater_into_water_kg{};
    double meltwater_ran_off_kg{};
    // A broken piece's cells in its own frame, for the water to press on,
    // kept by name while its cell count stays the same.
    std::unordered_map<std::string, std::pair<std::size_t, std::vector<Vec3>>> water_cells_of;
    // The turn a whole box or ball carries INSIDE its collision shape, which its
    // rigid pose does not: rotation_deg as rotationQuaternion builds it. The
    // water has to press on the box that is there -- and everything said about
    // the body has to be said of that box too: which way it faces, and where
    // its dent, its cuts and its edge are in its own frame. See shapeTurn.
    std::unordered_map<std::string, Quat> tilt_of;
    // What body `i`'s shape carries inside it (tilt_of), or no turn at all for
    // a hull, whose cells are its shape and are kept in its rigid frame. Its
    // rigid pose composed with this is which way the body faces.
    [[nodiscard]] Quat shapeTurn(std::size_t i) const {
        if (i >= described.size() || described[i].shape == "hull") return Quat{};
        const auto found = tilt_of.find(described[i].name);
        return found == tilt_of.end() ? Quat{} : found->second;
    }
    // A hull's surface, from its cells, worked out once per body.
    mutable std::unordered_map<std::string, std::pair<std::size_t, double>> hull_area_of;

    // ---- one material state (docs/thermal-mechanics.md) ------------------
    //
    // What a body's matter is measured against, and what has been done to its
    // shape because of it. The thermal network owns the state itself -- how
    // hot, how charred, how much has burned; this owns WHERE: the reference box
    // the network's state is laid over, and the geometry that follows from it.
    // Keyed by name, like the kerfs. Everything here is a plain value, so it
    // copies and restores with the rest of a world (listed in the doc). See
    // LiveWorld::MatterRecord above.
    //
    // Mutable because it is filled in the first time anything asks, which can
    // be a report; what it is filled with is the same whenever that happens.
    mutable std::unordered_map<std::string, MatterRecord> matter_of;
    // Bodies that burned or melted away entirely, with what was left of them,
    // in order.
    struct BurnedAway {
        std::string name;
        std::string material;
        double time_s{};
        double residue_kg{};
        std::string why;
        std::string gone{"burned"};
    };
    std::vector<BurnedAway> burned_away;

    // Pins, by name. See LiveJoint in the header for why it is names and not
    // bodies. `rigid` is the engine-level constraint that is currently standing
    // in for it, remade every time the body table is rearranged.
    struct SceneJoint {
        unsigned id{};
        std::string a, b;
        // Where the pin sits inside each body's OWN matter, and which way it
        // runs in the first one's. This is the part that survives: the assembly
        // can be carried across the room or turned over and the pin is still in
        // the same place in the wood.
        Vec3 point_local_a{}, point_local_b{}, axis_local_a{};
        // How far each of those points stood off its own body's matter
        // (Impl::standOff). A pin is not always IN what it holds: one put on a
        // post's face stands in the gap beside the pane it carries. When a body
        // breaks, this is how near a piece of it has to be to carry the pin.
        double stand_off_a{}, stand_off_b{};
        JoltWorld::JointKind kind{JoltWorld::JointKind::Hinge};
        double lower{}, upper{}, friction{};
        // A link's second attachment, which a pin and a slide do not have: they
        // are one point shared by two bodies, while a rope is tied at one place
        // on each and the two are not the same place.
        Vec3 point_local_b_tie{};
        double breaks_at_n{};
        // A pulley's two fixed points and its advantage. The points are in the
        // WORLD and stay there: a sheave bolted to a beam is the fixed half of
        // the relationship, and making it follow a body would make it not fixed.
        Vec3 over_a{}, over_b{};
        double ratio{1.0};
        // A fixing's two strengths, and where its axis points in the first
        // body's own frame -- so that tension and shear stay tension and shear
        // when the whole assembly is carried somewhere else or turned over.
        double holds_tension_n{}, holds_shear_n{};
        // A one-way fixing's hold along its axis (LiveWorld::fix). Zero is two-way.
        double comes_off_n{};
        // An elastic's declared model.
        double rest_m{}, stiffness_n_m{}, damping_n_s_m{};
        // A drum's rope (rigid/DrumRope.hpp): the radius it lies at on the drum,
        // and which way the drum turns to take it on. Its whole length is
        // `upper`, as a link's is; how much is off the drum is the constraint's.
        double radius_m{};
        int winds{1};
        // How far it had got, last time anyone could ask. Kept up to date every
        // step because the thing that destroys the constraint is the same thing
        // that needs to know it -- once the wood is rebuilt there is nobody left
        // to ask, and a door that had swung 60 degrees, or a portcullis hauled
        // a metre up, would be re-made as though it were shut.
        double at_when_hung{};
        unsigned rigid{};        // 0 when the pin is not currently in anything
        bool attached{true};
        // ---- heat and strength (docs/thermal-mechanics.md) ----------------
        // Which end the joint is made of: 0 for a, 1 for b, -1 for neither. An
        // END rather than a name, so it follows its member into whichever
        // piece carries the joint when the member breaks or is cut.
        int member_end{-1};
        // What was declared, kept the first time a member is named so that
        // naming none goes back to it. holds_tension_n, holds_shear_n,
        // breaks_at_n and stiffness_n_m above are what the joint has NOW, and
        // are what a rehung joint is made again with.
        double declared_tension_n{}, declared_shear_n{}, declared_breaks_at_n{};
        double declared_stiffness_n_m{};
        bool declared_kept{};
        // What it could take cold: the declared numbers, or the member's own
        // section times its material's strength where they were zero.
        double rated_tension_n{}, rated_shear_n{}, rated_breaks_at_n{}, rated_stiffness_n_m{};
        double capacity_fraction{1.0};
        // The fraction the last re-check was asked at.
        double checked_fraction{1.0};
        unsigned rechecks{};
        std::string parted_because;
        double parted_load_n{}, parted_capacity_n{};
        // The member as it was when last read, for the words it parts with.
        std::string member_said;
    };
    std::vector<SceneJoint> joints;
    unsigned next_joint{1};

    // ---- machines (docs/machine-world.md) ----------------------------------
    std::vector<LiveEnergyStore> energy_stores;
    struct Motor {
        LiveMotor said;
        // The pin's reading as this step began, for the turn it makes.
        double at_before{};
        // What this step's prepareMotors set: a drive, or friction to coast on;
        // and whether its store's power held the drive under the line.
        bool drove{}, coasted_on_friction{}, limited{};
        // The friction last put on the pin, so that a brake let off (or put
        // on) wakes what it held: a body still for half a second is asleep,
        // and a sleeping body does not notice that its pin has let go.
        double friction_set{-1.0};
        bool on_circuit{};
        double circuit_torque{};
    };
    std::vector<Motor> motors;
    std::vector<machines::Circuit> circuits;
    std::vector<machines::CircuitStep> circuit_steps;
    unsigned next_energy_store{1}, next_motor{1};
    // A machine's controller (LiveControl), and what it keeps between steps.
    struct Control {
        LiveControl said;
        // The last count applied from each of the most recent senders.
        std::vector<std::pair<std::string, std::uint64_t>> seen;
        // Stopped for want of progress, until it is told something again.
        bool tripped{};
        // A stretch of driving one way: its shaft's count when the stretch
        // began, and how long it has gone on. Progress is judged over kStallS.
        double turned_from{};
        double driving_s{};
        // How long it has been stopping before it turns the other way.
        double reversing_s{};
        // How long a hoist's rope has been slack with its load at rest.
        double slack_s{};
        // A hoist's rope out as the last kept step began: its rope's speed.
        double out_before{-1.0};
        // Whether it is driving a stretch now, and whether this step it is
        // stopping before it turns the other way (decide), for settleControls.
        bool stretch{}, reversing_now{};
        // Told a direction: until it is going that way, it first stops what
        // it was doing the other way. Only then -- a load that turns it back
        // once it is going is judged by its progress, not stopped for again.
        bool reversing{};
        // Lowering a hoist, the command it has come on to so far, the forward
        // way: from the share that holds the load still, ramped down to the
        // setting by settleControls.
        double ramp_u{};
    };
    std::vector<Control> controls;
    unsigned next_control{1};
    // A machine's program (LiveProgram), and what it keeps to itself: its
    // chassis's forward and left in the chassis's own frame, worked out when it
    // was made; which way it is turning, how far at least, and the heading the
    // last kept step left it at; which way it turns once it has backed off; and
    // the count it tells its wheels by.
    struct Program {
        LiveProgram said;
        std::vector<std::pair<std::string, std::uint64_t>> seen;
        Vec3 forward_local{0.0, 0.0, 1.0}, left_local{1.0, 0.0, 0.0};
        int turn_sign{};
        double turn_least_deg{};
        double heading_rad{};
        int then_turn{1};
        std::uint64_t told{};
        // Asked to drive somewhere and its sensors saw water: its reflexes
        // have it -- backing off, turning away -- until it is going forward
        // clear again, and then the ask has it back. An ask never drives it
        // into the water.
        bool interrupted{};
        // How many times its reflexes have taken it since it was last asked:
        // three, and it gives the ask up, since the water is in the way.
        unsigned interruptions{};
        // Hovering: where each rotor's pin is in the chassis's own level, the
        // way each spins (+1 or -1), the height its centre stood at when it was
        // made (where it lands), the height term's memory, and its motion as
        // the last kept step left it.
        std::vector<Vec3> rotor_local;
        std::vector<int> spins;
        double last_dt_s{};
        // The spot it hovers over, kept from when it began to wait there.
        Vec3 hold_at{};
        bool holding{};
        double landed_height_m{};
        double hover_i{};
        Vec3 velocity{}, spin{};
    };
    std::vector<Program> programs;
    unsigned next_program{1};
    [[nodiscard]] Motor *motorById(unsigned id) {
        for (Motor &m : motors)
            if (m.said.id == id) return &m;
        return nullptr;
    }
    [[nodiscard]] Control *controlOfMotor(unsigned motor) {
        for (Control &c : controls)
            if (c.said.motor == motor) return &c;
        return nullptr;
    }
    [[nodiscard]] SceneJoint *motorPin(unsigned id) {
        for (SceneJoint &joint : joints)
            if (joint.id == id) return &joint;
        return nullptr;
    }
    [[nodiscard]] LiveEnergyStore *energyStoreById(unsigned id) {
        for (LiveEnergyStore &store : energy_stores)
            if (store.id == id) return &store;
        return nullptr;
    }
    // What a motor will do at the next step, as prepareMotors will decide it
    // from its command, its brake and its store: said as soon as it is told,
    // so that a report between being told and the next step -- a room's
    // opening, with its hoist braked -- says what it is doing, not the last
    // step's.
    [[nodiscard]] std::string stateToBe(const LiveMotor &s) {
        const SceneJoint *pin = motorPin(s.joint);
        if (pin == nullptr || pin->rigid == 0 || !world->hasJoint(pin->rigid)) return "gone";
        const LiveEnergyStore *store = energyStoreById(s.store);
        const double u = std::clamp(s.command, -1.0, 1.0);
        if (u == 0.0 || store == nullptr || !(store->charge_j > 0.0))
            return u != 0.0 ? "flat" : s.brake && s.brake_torque_n_m > 0.0 ? "braking" : "coasting";
        return "driving";
    }
    // Wakes both of a pin's bodies.
    void wakePin(const SceneJoint &pin) {
        for (const std::string *name : {&pin.a, &pin.b}) {
            const auto found = index_of.find(*name);
            if (found != index_of.end() && inWorld(found->second)) world->wake(body_of[found->second]);
        }
    }
    // Wakes a pin's two bodies and whatever hangs from either on a rope wound
    // on a drum: what a motor on the pin moves.
    void wakeMachine(const SceneJoint &pin) {
        wakePin(pin);
        for (const SceneJoint &rope : joints) {
            if (rope.kind != JoltWorld::JointKind::Drum || (rope.a != pin.a && rope.a != pin.b)) continue;
            const auto found = index_of.find(rope.b);
            if (found != index_of.end() && inWorld(found->second)) world->wake(body_of[found->second]);
        }
    }
    // Before the step's reversible trial: each motor's drive for this step,
    // from its line at the speed its pin has now, held to what its store can
    // give. A constraint's settings are not state the trial winds back, so they
    // are set here -- as a tool's bite in the ground is -- and a retry after a
    // refused step sets the same again.
    void prepareMotors(double dt_s) {
        for (Motor &m : motors) {
            if (m.on_circuit) continue;
            LiveMotor &s = m.said;
            // Whether it drove in the step before: one starting to drive wakes
            // what it moves (below).
            const bool drove_before = m.drove;
            m.drove = m.coasted_on_friction = m.limited = false;
            SceneJoint *pin = motorPin(s.joint);
            if (pin == nullptr || pin->rigid == 0 || !world->hasJoint(pin->rigid)) {
                s.state = "gone";
                continue;
            }
            m.at_before = world->jointState(pin->rigid).at;
            // A rotor: the air's drag on the pin, and the thrust on its frame
            // for the step to come, both from the spin the last step left it.
            const double omega_rotor = world->hingeRate(pin->rigid);
            if (s.rotor_thrust_n_per_rad2 > 0.0 || s.rotor_drag_n_m_per_rad2 > 0.0) {
                const auto frame = index_of.find(pin->a);
                const auto disc = index_of.find(pin->b);
                if (frame != index_of.end() && inWorld(frame->second) && disc != index_of.end() &&
                    inWorld(disc->second)) {
                    const RigidSnapshot at = world->snapshot(body_of[frame->second]);
                    const Vec3 axis = normalized(at.orientation_world.rotate(pin->axis_local_a));
                    const Vec3 point = at.center_of_mass_world_m + at.orientation_world.rotate(pin->point_local_a);
                    world->addForce(body_of[frame->second],
                                    axis * (s.rotor_thrust_n_per_rad2 * omega_rotor * omega_rotor), point);
                    // The air's drag on the disc, against its spin, and its
                    // reaction on the frame: a torque, not the pin's friction,
                    // which Jolt applies only while the pin's motor is off, so
                    // a driven rotor would spin against nothing and lift for
                    // free.
                    const double drag = s.rotor_drag_n_m_per_rad2 * omega_rotor * std::abs(omega_rotor);
                    world->addTorque(body_of[disc->second], axis * (-drag));
                    world->addTorque(body_of[frame->second], axis * drag);
                }
            }
            // What a motor turns runs in bearings: its losses are the pin's
            // friction and the motor's windings. The engine's slight drag on
            // every moving piece but a ball -- 0.02 of its speed a second, a
            // numerical stand-in and not a law -- would be a third, and one no
            // account names, so it is taken off. Every step, because a piece
            // rebuilt after a break or a cut comes back with it.
            for (const std::string *name : {&pin->a, &pin->b}) {
                const auto found = index_of.find(*name);
                if (found != index_of.end() && inWorld(found->second))
                    world->setDamping(body_of[found->second], 0.0, 0.0);
            }
            LiveEnergyStore *store = energyStoreById(s.store);
            const double u = std::clamp(s.command, -1.0, 1.0);
            const bool empty = store == nullptr || !(store->charge_j > 0.0);
            if (u == 0.0 || empty) {
                world->coastHinge(pin->rigid);
                // A motor with no brake, told to brake, has nothing to brake
                // with: it coasts, and says so.
                const bool braking = s.brake && u == 0.0 && s.brake_torque_n_m > 0.0;
                const double friction = braking ? std::max(pin->friction, s.brake_torque_n_m) : pin->friction;
                world->setJointFriction(pin->rigid, friction);
                if (friction != m.friction_set) wakePin(*pin);
                m.friction_set = friction;
                m.coasted_on_friction = friction > 0.0;
                s.state = u != 0.0 ? "flat" : braking ? "braking" : "coasting";
                continue;
            }
            // The line at this share of the voltage: its stall torque at a
            // standstill, nothing at its unloaded speed, and braking past it.
            const double omega = world->hingeRate(pin->rigid);
            const double lean = u - omega / s.no_load_rad_s;
            double limit = std::abs(s.stall_torque_n_m * lean);
            // What a torque t costs the store at this speed: the work t*omega
            // and the windings' t^2 * no_load / stall (I^2 R, with the torque
            // constant V / no_load and R = V^2 / (stall * no_load), so the
            // voltage cancels). Held to the store's power, and to its charge
            // over this step.
            const double windings = s.no_load_rad_s / s.stall_torque_n_m;
            double most_w = store->charge_j / dt_s;
            if (store->max_power_w > 0.0) most_w = std::min(most_w, store->max_power_w);
            const double along = (lean >= 0.0 ? 1.0 : -1.0) * omega;
            const double most_torque =
                (-along + std::sqrt(along * along + 4.0 * windings * most_w)) / (2.0 * windings);
            m.limited = most_torque < limit;
            limit = std::min(limit, most_torque);
            world->setJointFriction(pin->rigid, pin->friction);
            m.friction_set = pin->friction;
            // Starting to drive, it wakes its pin's two bodies and what hangs
            // from either on a drum's rope. A crate asleep under a braked drum
            // was not in the step that turned the drum: the drum wound 7.7 mm of
            // rope in under it, slack, and the crate snatched the rope when it
            // woke (machine_control_tests, lowering from the top).
            if (!drove_before) wakeMachine(*pin);
            world->driveHinge(pin->rigid, u * s.no_load_rad_s, limit);
            m.drove = limit > 0.0;
            s.state = "driving";
        }
    }
    // After a kept step: what each motor did, from the impulse the solver
    // applied in it and the turn its pin made.
    void settleMotors(double dt_s) {
        constexpr double kTurn = 2.0 * 3.14159265358979323846;
        for (Motor &m : motors) {
            if (m.on_circuit) continue;
            LiveMotor &s = m.said;
            SceneJoint *pin = motorPin(s.joint);
            if (pin == nullptr || pin->rigid == 0 || !world->hasJoint(pin->rigid)) {
                s.state = "gone";
                s.speed_rad_s = s.torque_n_m = s.current_a = s.power_w = 0.0;
                continue;
            }
            // The reading wraps at +-pi, and a step turns a pin far less than
            // half a turn: the turn is the short way round.
            double turn = world->jointState(pin->rigid).at - m.at_before;
            turn -= kTurn * std::round(turn / kTurn);
            s.turned_rad += turn;
            s.speed_rad_s = world->hingeRate(pin->rigid);
            if (s.rotor_thrust_n_per_rad2 > 0.0 || s.rotor_drag_n_m_per_rad2 > 0.0) {
                const double w2 = s.speed_rad_s * s.speed_rad_s;
                s.thrust_n = s.rotor_thrust_n_per_rad2 * w2;
                s.air_j += s.rotor_drag_n_m_per_rad2 * w2 * std::abs(s.speed_rad_s) * dt_s;
            }
            const double torque =
                m.drove || m.coasted_on_friction ? world->hingeMotorImpulse(pin->rigid) / dt_s : 0.0;
            const double work = torque * turn;
            s.torque_n_m = torque;
            if (!m.drove) {
                // Coasting or braking: what the pin's friction took.
                s.friction_heat_j += std::max(-work, 0.0);
                s.current_a = s.power_w = 0.0;
                continue;
            }
            const double heat = torque * torque * (s.no_load_rad_s / s.stall_torque_n_m) * dt_s;
            const double asked = std::max(work + heat, 0.0);
            s.work_j += work;
            // Nothing goes back into the store: what a load driving the motor
            // gives back is heat, as the windings' is.
            s.heat_j += heat + std::max(-(work + heat), 0.0);
            s.drawn_j += asked;
            s.power_w = asked / dt_s;
            LiveEnergyStore *store = energyStoreById(s.store);
            if (store != nullptr) {
                const double given = std::min(asked, store->charge_j);
                store->short_j += asked - given;
                store->charge_j -= given;
                store->given_j += given;
                s.current_a = torque * s.no_load_rad_s / store->voltage_v;
            }
        }
    }

    void attachCircuit(machines::Circuit c) {
        if (circuits.size() >= 32) throw std::invalid_argument("at most 32 live circuits");
        if (!energyStoreById(c.store())) throw std::invalid_argument("circuit store does not exist");
        for (const auto &old : circuits)
            if (old.store() == c.store()) throw std::invalid_argument("store already has a circuit");
        const auto ids = c.motors();
        for (unsigned id : ids) {
            auto *m = motorById(id);
            if (!m || m->said.store != c.store() || m->on_circuit)
                throw std::invalid_argument("circuit motor must belong to its store and to no other circuit");
        }
        for (const auto &m : motors)
            if (m.said.store == c.store() && std::find(ids.begin(), ids.end(), m.said.id) == ids.end())
                throw std::invalid_argument("circuit must include every motor sharing the store");
        circuits.push_back(std::move(c));
        for (unsigned id : ids) motorById(id)->on_circuit = true;
    }
    void prepareCircuits(double dt) {
        circuit_steps.clear();
        for (const auto &c : circuits) {
            const auto *store = energyStoreById(c.store());
            std::vector<machines::CircuitMotorInput> inputs;
            for (unsigned id : c.motors()) {
                auto &m = *motorById(id);
                auto *pin = motorPin(m.said.joint);
                const bool present = pin && pin->rigid && world->hasJoint(pin->rigid);
                inputs.push_back({id, m.said.command, present ? world->hingeRate(pin->rigid) : 0.0,
                    store->voltage_v / m.said.no_load_rad_s,
                    store->voltage_v * store->voltage_v / (m.said.stall_torque_n_m * m.said.no_load_rad_s), present});
            }
            circuit_steps.push_back(c.solve(dt, store->voltage_v, store->charge_j, store->max_power_w, inputs));
            const auto &s = circuit_steps.back();
            for (std::size_t b = 0; b < c.size(); ++b) {
                if (!c.motor(b)) continue;
                auto &m = *motorById(c.motor(b)); auto &out = m.said;
                auto *pin = motorPin(out.joint);
                m.circuit_torque = s.torque_n_m[b];
                m.drove = m.circuit_torque != 0.0; m.limited = s.limited;
                if (!pin || !pin->rigid || !world->hasJoint(pin->rigid)) { out.state = "gone"; continue; }
                m.at_before = world->jointState(pin->rigid).at;
                world->coastHinge(pin->rigid);
                const bool brake = out.command == 0.0 && out.brake && out.brake_torque_n_m > 0.0;
                const double friction = brake ? std::max(pin->friction, out.brake_torque_n_m) : pin->friction;
                world->setJointFriction(pin->rigid, friction);
                if (friction != m.friction_set || m.drove) wakeMachine(*pin);
                m.friction_set = friction; m.coasted_on_friction = friction > 0.0;
                for (const auto *name : {&pin->a, &pin->b}) {
                    const auto found = index_of.find(*name);
                    if (found != index_of.end() && inWorld(found->second))
                        world->setDamping(body_of[found->second], 0.0, 0.0);
                }
                out.state = m.drove ? "driving" : brake ? "braking" : out.command == 0.0 ? "coasting" :
                            store->charge_j <= 0.0 ? "flat" : "open-circuit";
            }
        }
    }
    void validateCircuitStep(double dt) {
        // Explicit electrical damping must resolve the smallest relative-shaft
        // time constant. Refuse an unsupported step BEFORE mutating the world;
        // the caller can reduce its step rather than silently losing energy.
        double bound = 1.0 / 60.0;
        for (const auto &c : circuits) for (std::size_t b = 0; b < c.size(); ++b) {
            if (!c.motor(b)) continue;
            const auto &m = *motorById(c.motor(b));
            const auto *pin = motorPin(m.said.joint);
            if (!pin || !pin->rigid || !world->hasJoint(pin->rigid)) continue;
            const Vec3 axis = worldAxis(pin->a, pin->axis_local_a);
            double inverse_inertia = 0.0;
            for (const auto *name : {&pin->a, &pin->b}) {
                const auto at = index_of.find(*name);
                if (at != index_of.end() && inWorld(at->second))
                    inverse_inertia += 1.0 / world->inertiaAbout(body_of[at->second], axis);
            }
            const double damping = m.said.stall_torque_n_m / m.said.no_load_rad_s * c.ratio(b) * c.ratio(b);
            if (inverse_inertia > 0.0)
                bound = std::min(bound, 0.1 * c.resistanceFactor(b) / (inverse_inertia * damping));
            const double speed = std::abs(world->hingeRate(pin->rigid));
            if (speed > 0.0) bound = std::min(bound, 0.5 / speed);
        }
        if (!std::isfinite(dt) || dt > bound * (1.0 + 1e-12))
            throw std::invalid_argument("circuit coupling needs dt <= " + nlohmann::json(bound).dump() + " seconds");
    }
    // Inside each mechanical trial: equal/opposite torques, so mounts and
    // world contacts see the same loads as exposed parts. No prescribed speed.
    void pushCircuits() {
        for (const auto &m : motors) {
            if (!m.on_circuit || !m.drove) continue;
            const auto *pin = motorPin(m.said.joint);
            if (!pin || !pin->rigid || !world->hasJoint(pin->rigid)) continue;
            const Vec3 torque = m.circuit_torque * worldAxis(pin->a, pin->axis_local_a);
            world->twistBody(body_of[index_of.at(pin->a)], -1.0 * torque);
            world->twistBody(body_of[index_of.at(pin->b)], torque);
        }
    }
    void settleCircuits(double dt) {
        constexpr double turn_rad = 2.0 * 3.14159265358979323846;
        for (std::size_t ci = 0; ci < circuits.size(); ++ci) {
            auto &c = circuits[ci]; auto &s = circuit_steps[ci];
            double actual_work = 0.0;
            for (std::size_t b = 0; b < c.size(); ++b) {
                if (!c.motor(b)) continue;
                auto &m = *motorById(c.motor(b)); auto &out = m.said;
                const auto *pin = motorPin(out.joint);
                if (!pin || !pin->rigid || !world->hasJoint(pin->rigid)) {
                    out.speed_rad_s = out.torque_n_m = out.current_a = out.power_w = 0.0; continue;
                }
                double turn = world->jointState(pin->rigid).at - m.at_before;
                turn -= turn_rad * std::round(turn / turn_rad);
                const double work = m.circuit_torque * turn;
                const double friction = m.coasted_on_friction ?
                    std::max(0.0, -world->hingeMotorImpulse(pin->rigid) * turn / dt) : 0.0;
                out.turned_rad += turn; out.speed_rad_s = world->hingeRate(pin->rigid);
                out.torque_n_m = m.circuit_torque; out.current_a = s.motor_current_a[b];
                out.power_w = (s.branch_heat_j[b] + s.shaft_j[b]) / dt;
                out.drawn_j += out.power_w * dt; out.heat_j += s.branch_heat_j[b];
                out.work_j += work; out.friction_heat_j += friction;
                c.addFrictionHeat(s, b, friction); actual_work += work - friction;
            }
            c.commit(s, actual_work);
            auto *store = energyStoreById(c.store());
            store->charge_j = std::max(0.0, store->charge_j - s.source_j);
            store->given_j += s.source_j;
        }
    }

    // ---- a machine's controller (LiveControl) -------------------------------
    // A hoist's rope as its controller reads it: whether it is there, how much
    // is out, what it carries, the radius it winds at, and its load and how
    // fast that is moving.
    struct HoistRope {
        bool there{};
        double out_m{}, tension_n{}, radius_m{}, load_speed_m_s{}, load_mass_kg{};
        std::string load;
    };
    [[nodiscard]] HoistRope hoistRope(unsigned id) const {
        HoistRope r;
        for (const SceneJoint &joint : joints) {
            if (joint.id != id || joint.kind != JoltWorld::JointKind::Drum) continue;
            if (joint.rigid == 0 || !world->hasJoint(joint.rigid)) break;
            const JoltWorld::DrumReport now = world->drumState(joint.rigid);
            r.there = true;
            r.out_m = now.out_m;
            r.tension_n = now.tension_n;
            r.radius_m = joint.radius_m;
            r.load = joint.b;
            const auto found = index_of.find(joint.b);
            if (found != index_of.end() && inWorld(found->second)) {
                r.load_speed_m_s = length(world->snapshot(body_of[found->second]).linear_velocity_m_s);
                // What it weighs, as the solver has it (as poses() says it).
                r.load_mass_kg = world->mechanicalState(body_of[found->second]).mass_kg;
            }
            break;
        }
        return r;
    }
    // A direction kept in a named body's own frame, in the world's.
    [[nodiscard]] Vec3 worldAxis(const std::string &name, const Vec3 &local) const {
        const auto found = index_of.find(name);
        if (found == index_of.end() || !inWorld(found->second)) return local;
        return world->snapshot(body_of[found->second]).orientation_world.rotate(local);
    }
    // Whether the hand holds a part of a machine: either side of its motor's
    // pin, or a hoist's load.
    [[nodiscard]] bool handOn(const SceneJoint &pin, const HoistRope &rope) const {
        if (holding == static_cast<std::size_t>(-1) || holding >= described.size()) return false;
        const std::string &held = described[holding].name;
        return held == pin.a || held == pin.b || (rope.there && held == rope.load);
    }
    // What a controller has its motor do in the next step: from what it was
    // told, where its hoist's rope stands and how the kept steps have gone, the
    // command and the brake the motor takes into the step (prepareMotors drives
    // it on its own line from them), and what stands in the way. Before every
    // step, with the step's length; and with 0 when it is told something, to say
    // at once what it will do. Nothing is timed here: settleControls times what
    // it did over kept steps only, as a motor's account is kept.
    void decide(Control &c, double dt_s) {
        // Turning the other way faster than this share of its unloaded speed,
        // it stops first, for no longer than kReverseMostS.
        constexpr double kReverseAtShare = 0.1;
        constexpr double kReverseMostS = 1.0;
        // A hoist slows within kSlowWithinM of rope of either end of its travel,
        // to kApproachPerS metres a second for each metre left, and never below
        // kCreepM_S; and a rope slack for kSlackS with its load at rest, its load
        // is down.
        constexpr double kSlowWithinM = 0.2;
        constexpr double kApproachPerS = 2.0;
        constexpr double kCreepM_S = 0.05;
        constexpr double kSlackS = 0.25;
        // A rope carrying less than kSlackN is slack; raising, a slack rope is
        // taken up at no more than kTakeUpShare of the voltage.
        constexpr double kSlackN = 1.0;
        constexpr double kTakeUpShare = 0.15;
        LiveControl &s = c.said;
        c.reversing_now = false;
        Motor *m = motorById(s.motor);
        SceneJoint *pin = m != nullptr ? motorPin(m->said.joint) : nullptr;
        if (m == nullptr || pin == nullptr || pin->rigid == 0 || !world->hasJoint(pin->rigid)) {
            s.command = 0.0;
            s.brake = false;
            s.condition = "its motor is gone";
            c.stretch = false;
            return;
        }
        LiveMotor &motor = m->said;
        const bool holds = motor.brake_torque_n_m > 0.0;
        // The shaft's speed the forward way, as the last kept step left it.
        const double speed = s.forward * motor.speed_rad_s;
        const HoistRope rope = s.rope != 0 ? hoistRope(s.rope) : HoistRope{};
        double u = 0.0;  // the command, the forward way
        std::string why;
        if (!s.power) {
            why = "off";
        } else if (s.direction == 0) {
            why = holds ? "stopped, holding on its brake" : "stopped: it coasts, with no brake to hold it";
        } else if (c.tripped) {
            why = s.condition;  // what stopped it, until it is told something again
        } else if (!(s.setting > 0.0)) {
            why = "its drive setting is at nothing";
        } else if (stopping(s, s.direction) != nullptr) {
            // A sensor sees what it was fitted to stop for: it stops, on its
            // brake if it has one, until it is told something again -- told the
            // same way while the sensor still sees it, it stops again at once;
            // the other way, it goes.
            c.tripped = true;
            why = s.direction > 0 ? "water ahead: it stopped at the water's edge"
                                  : "water behind: it stopped at the water's edge";
        } else if (c.reversing && s.direction * speed < -kReverseAtShare * motor.no_load_rad_s &&
                   c.reversing_s < kReverseMostS) {
            c.reversing_now = true;
            why = "stopping before it turns the other way";
        } else {
            c.reversing = false;
            u = s.direction * s.setting;
            if (rope.there && rope.radius_m > 0.0) {
                // The rope's speed at the motor's unloaded speed, and the share
                // of the voltage that holds the load still against its weight:
                // from what it weighs, not from what the rope carried in the
                // last step. A load speeding up pulls less, and a command
                // worked out from that holds back less, and feeds on itself --
                // the rope fell to 56 N of the crate's 261 slowing for the
                // bottom. With no load to weigh, from the rope.
                const double unloaded = rope.radius_m * motor.no_load_rad_s;
                const double carried =
                    rope.load_mass_kg > 0.0 ? rope.load_mass_kg * length(request.gravity_m_s2) : rope.tension_n;
                const double hold = carried * rope.radius_m / motor.stall_torque_n_m;
                // A stretch of lowering comes on from where the motor is: the
                // share that holds the load still, or what it drives at now if
                // that is further down already.
                if (!c.stretch)
                    c.ramp_u = s.direction < 0 && motor.command != 0.0 ? std::min(hold, s.forward * motor.command)
                                                                        : hold;
                // The rope left before the end it is going to, against how far
                // the rope goes in this step.
                const double left = s.direction > 0 ? rope.out_m - s.top_out_m : s.bottom_out_m - rope.out_m;
                if (left <= std::abs(s.rope_speed_m_s) * dt_s) {
                    u = 0.0;
                    why = s.direction > 0 ? "at the top" : "at the bottom";
                } else if (s.direction < 0 && c.slack_s >= kSlackS) {
                    u = 0.0;
                    why = "the load is down: its rope is slack";
                } else {
                    // Lowering, it drives at the setting as raising does -- the
                    // load's weight turns the motor past its unloaded speed, and
                    // the motor's line holds it back -- but it comes on from the
                    // share that holds the load still, no faster than
                    // settleControls ramps it: from rest, a motor let drive the
                    // drum down at once outruns a load that can only fall, the
                    // rope goes slack, and the load snatches it when it catches
                    // up (2.24 m/s, where the line says 1.43).
                    if (s.direction < 0) u = std::max(u, c.ramp_u);
                    if (left < kSlowWithinM) {
                        // Near an end: the command that gives the rope the speed
                        // it should have this near, from the motor's line and
                        // the torque the load puts on the drum -- never more
                        // effort the way it was told than it was told, and
                        // holding back as much as a load coming down needs.
                        const double want = std::max(kCreepM_S, kApproachPerS * left);
                        const double line = hold + s.direction * want / unloaded;
                        u = s.direction > 0 ? std::clamp(line, 0.0, s.setting)
                                            : std::max(std::clamp(line, -s.setting, 1.0), c.ramp_u);
                        why = s.direction > 0 ? "slowing for the top" : "slowing for the bottom";
                    } else if (s.direction > 0 && rope.tension_n < kSlackN) {
                        // Raising on a slack rope: taken up gently, so the load
                        // is not snatched off what it rests on.
                        u = std::min(u, kTakeUpShare);
                    }
                }
            }
        }
        const bool drives = u != 0.0;
        if (drives && !c.stretch) {
            c.stretch = true;
            c.turned_from = s.forward * motor.turned_rad;
            c.driving_s = 0.0;
        } else if (!drives) {
            c.stretch = false;
            c.driving_s = 0.0;
        }
        motor.command = std::clamp(s.forward * u, -1.0, 1.0);
        motor.brake = !drives && holds;
        motor.state = stateToBe(motor);
        s.command = motor.command;
        s.brake = motor.brake;
        if (why.empty() && drives) {
            if (motor.state == "flat") why = "its battery is flat";
            else if (m->limited) why = "held back by its battery's power";
        }
        if (why.empty() && handOn(*pin, rope)) why = "the hand is on it";
        s.condition = why;
    }
    // A controller told something: what was said replaces what it had; a stall
    // it stopped for is forgotten and progress is judged afresh; and what it
    // will do is said at once.
    void tell(Control &c, std::optional<bool> power, std::optional<int> direction, std::optional<double> setting,
              const std::string &sender, std::uint64_t seq) {
        LiveControl &s = c.said;
        if (power) s.power = *power;
        if (direction) s.direction = std::clamp(*direction, -1, 1);
        if (setting) s.setting = std::clamp(*setting, 0.0, 1.0);
        s.sender = sender;
        s.seq = seq;
        c.tripped = false;
        c.stretch = false;
        c.reversing = true;
        c.driving_s = c.reversing_s = c.slack_s = 0.0;
        decide(c, 0.0);
    }
    void prepareControls(double dt_s) {
        for (Control &c : controls) decide(c, dt_s);
    }
    // What each of a controller's sensors reads now: for "water", the depth of
    // the room's water under its point, wherever its part has got to.
    void readSensors(Control &c) { readSensorList(c.said.sensors); }
    void readSensorList(std::vector<LiveSensor> &sensors) {
        for (LiveSensor &sensor : sensors) {
            sensor.reading_m = 0.0;
            const auto found = index_of.find(sensor.body);
            if (found != index_of.end() && inWorld(found->second)) {
                const RigidSnapshot at = world->snapshot(body_of[found->second]);
                sensor.at_m = at.center_of_mass_world_m + at.orientation_world.rotate(sensor.at_local_m);
                if (environment) sensor.reading_m = environment->waterDepthAt(sensor.at_m.x, sensor.at_m.z);
            }
            sensor.sees = sensor.reading_m > sensor.depth_m;
        }
    }
    // The first sensor that stops a controller going `direction`, if any.
    [[nodiscard]] static const LiveSensor *stopping(const LiveControl &s, int direction) {
        for (const LiveSensor &sensor : s.sensors)
            if (sensor.stops == direction && sensor.sees) return &sensor;
        return nullptr;
    }
    // After a kept step: what each controller's machine did -- its shaft's
    // speed, a hoist's rope -- and the timing of what it decided: a stretch of
    // driving that got nowhere in kStallS stops it, since a motor driven into
    // something that will not move only heats; lowering, its command comes on
    // at kRampPerS of the voltage a second. Then what it will do next, said at
    // once, as a motor says what it was told before the step that does it.
    void settleControls(double dt_s) {
        constexpr double kStallS = 1.5;
        constexpr double kProgressRad = 0.05;
        constexpr double kSlackN = 1.0;
        constexpr double kRestM_S = 0.05;
        constexpr double kRampPerS = 2.0;
        constexpr double kRpmPerRadS = 60.0 / (2.0 * 3.14159265358979323846);
        for (Control &c : controls) {
            LiveControl &s = c.said;
            const Motor *m = motorById(s.motor);
            if (m == nullptr) continue;
            const LiveMotor &motor = m->said;
            s.speed_rpm = s.forward * motor.speed_rad_s * kRpmPerRadS;
            HoistRope rope;
            if (s.rope != 0) rope = hoistRope(s.rope);
            if (rope.there) {
                if (c.out_before >= 0.0 && dt_s > 0.0) s.rope_speed_m_s = (c.out_before - rope.out_m) / dt_s;
                s.out_m = rope.out_m;
                c.out_before = rope.out_m;
            }
            c.reversing_s = c.reversing_now ? c.reversing_s + dt_s : 0.0;
            const bool lowering = s.power && s.direction < 0 && !c.tripped;
            c.slack_s = lowering && rope.there && rope.tension_n < kSlackN && rope.load_speed_m_s < kRestM_S
                            ? c.slack_s + dt_s
                            : 0.0;
            if (lowering && rope.there && c.stretch) c.ramp_u = std::max(-s.setting, c.ramp_u - kRampPerS * dt_s);
            if (c.stretch && s.command != 0.0) {
                c.driving_s += dt_s;
                if (c.driving_s >= kStallS) {
                    const double progress = s.direction * (s.forward * motor.turned_rad - c.turned_from);
                    if (progress < kProgressRad) {
                        c.tripped = true;
                        c.stretch = false;
                        s.condition = progress < -kProgressRad
                                          ? "too weak at this setting: the load turned it back, so it stopped"
                                          : "stalled: it made no progress, so it stopped";
                    }
                    c.driving_s = 0.0;
                    c.turned_from = s.forward * motor.turned_rad;
                }
            }
            readSensors(c);
            decide(c, dt_s);
        }
    }

    // ---- the sun and solar panels (LiveSun, LiveSolarPanel) --------------------
    LiveSun sun;
    std::vector<LiveSolarPanel> panels;
    unsigned next_panel{1};
    // Where a sun with a day stands at the world's time now: its hour angle from
    // the hour, and from that and the latitude its noon height means, its way
    // across the sky -- east at six, south at noon, west at six -- and its beam
    // through the air it comes through. A sun without a day stays where it is.
    void advanceSun() {
        if (!sun.declared || !(sun.day_s > 0.0)) return;
        constexpr double kPi = 3.14159265358979323846;
        constexpr double kRadPerDeg = kPi / 180.0;
        sun.hour = std::fmod(sun.hour_at_start + 24.0 * time_s / sun.day_s, 24.0);
        if (sun.hour < 0.0) sun.hour += 24.0;
        const double h = (sun.hour - 12.0) * 15.0 * kRadPerDeg;       // the hour angle, 0 at noon
        const double latitude = (90.0 - sun.noon_elevation_deg) * kRadPerDeg;
        // East, up and north, the world's +x, +y and -z.
        const double east = -std::sin(h);
        const double up = std::cos(latitude) * std::cos(h);
        const double north = -std::sin(latitude) * std::cos(h);
        sun.toward = Vec3{east, up, -north};
        sun.elevation_deg = std::asin(std::clamp(up, -1.0, 1.0)) / kRadPerDeg;
        sun.azimuth_deg = std::atan2(sun.toward.x, sun.toward.z) / kRadPerDeg;
        if (sun.azimuth_deg < 0.0) sun.azimuth_deg += 360.0;
        if (up > 0.0) {
            // The air mass, as flat layers of air: 1 overhead, 1/sin of the
            // elevation lower down; the Meinel model's 38 at the horizon.
            const double air = std::min(1.0 / up, 38.0);
            sun.irradiance_w_m2 = sun.zenith_irradiance_w_m2 * std::pow(0.7, std::pow(air, 0.678) - 1.0);
        } else {
            sun.irradiance_w_m2 = 0.0;
        }
    }
    // After a kept step: where each panel is and which way it faces, the
    // sunlight on it, and what it put into its store -- after the motors have
    // drawn what the step cost them, so the step's charge is what they had.
    void settlePanels(double dt_s) {
        constexpr double kOffFaceM = 0.01;
        constexpr double kReachM = 1000.0;
        for (LiveSolarPanel &panel : panels) {
            panel.cos_incidence = panel.sunlight_w = panel.power_w = 0.0;
            panel.shaded = false;
            panel.shaded_by.clear();
            const auto found = index_of.find(panel.body);
            if (found == index_of.end() || !inWorld(found->second)) continue;
            const RigidSnapshot at = world->snapshot(body_of[found->second]);
            panel.at_m = at.center_of_mass_world_m + at.orientation_world.rotate(panel.at_local_m);
            panel.normal = at.orientation_world.rotate(panel.normal_local);
            if (!sun.declared || sun.toward.y < 0.0) continue;   // none, or below the horizon
            panel.cos_incidence = std::max(0.0, dot(panel.normal, sun.toward));
            if (!(panel.cos_incidence > 0.0)) continue;
            // Anything between it and the sun: a thing, or the ground itself.
            const RayHit hit = world->castRay(panel.at_m + kOffFaceM * panel.normal, sun.toward, kReachM);
            if (hit.hit) {
                panel.shaded = true;
                panel.shaded_by = "the ground";
                if (hit.named)
                    for (std::size_t i = 0; i < body_of.size(); ++i)
                        if (body_of[i] == hit.body_id) panel.shaded_by = described[i].name;
                continue;
            }
            panel.sunlight_w = sun.irradiance_w_m2 * panel.area_m2 * panel.cos_incidence;
            const double sunlight = panel.sunlight_w * dt_s;
            const double made = sunlight * panel.efficiency;
            double taken = 0.0;
            if (LiveEnergyStore *store = energyStoreById(panel.store); store != nullptr) {
                taken = std::clamp(store->capacity_j - store->charge_j, 0.0, made);
                store->charge_j += taken;
                store->taken_j += taken;
            }
            panel.power_w = taken / dt_s;
            panel.sunlight_j += sunlight;
            panel.collected_j += taken;
            panel.spilled_j += made - taken;
            panel.heat_j += sunlight - made;
        }
    }

    // ---- a machine's program (LiveProgram) ------------------------------------
    [[nodiscard]] Control *controlById(unsigned id) {
        for (Control &c : controls)
            if (c.said.id == id) return &c;
        return nullptr;
    }
    // A program's machine as the last kept step left it: what its sensors
    // read, and its chassis's slope, nose up and left side up, and heading.
    // The store a program's machine runs on: the one its left wheel's motor
    // draws on.
    [[nodiscard]] LiveEnergyStore *storeOfProgram(const Program &p) {
        if (p.said.store != 0) return energyStoreById(p.said.store);
        const Control *left = controlById(p.said.left);
        const Motor *motor = left != nullptr ? motorById(left->said.motor) : nullptr;
        return motor != nullptr ? energyStoreById(motor->said.store) : nullptr;
    }
    void readProgram(Program &p) {
        constexpr double kDegPerRad = 57.295779513082320876798;
        readSensorList(p.said.sensors);
        if (const LiveEnergyStore *store = storeOfProgram(p); store != nullptr && store->capacity_j > 0.0)
            p.said.charge_share = store->charge_j / store->capacity_j;
        const auto found = index_of.find(p.said.body);
        if (found == index_of.end() || !inWorld(found->second)) return;
        const RigidSnapshot at = world->snapshot(body_of[found->second]);
        const Vec3 forward = at.orientation_world.rotate(p.forward_local);
        const Vec3 left = at.orientation_world.rotate(p.left_local);
        p.said.pitch_deg = std::asin(std::clamp(forward.y, -1.0, 1.0)) * kDegPerRad;
        p.said.roll_deg = std::asin(std::clamp(left.y, -1.0, 1.0)) * kDegPerRad;
        p.heading_rad = std::atan2(forward.x, forward.z);
        p.said.at_m = at.center_of_mass_world_m;
        p.velocity = at.linear_velocity_m_s;
        p.spin = at.angular_velocity_rad_s;
        p.said.climb_m_s = at.linear_velocity_m_s.y;
        const double ground = environment ? environment->terrain().heightAt(at.center_of_mass_world_m.x,
                                                                             at.center_of_mass_world_m.z)
                                          : 0.0;
        p.said.height_m = at.center_of_mass_world_m.y - ground;
        p.said.heading_deg = p.heading_rad * kDegPerRad;
        if (p.said.heading_deg < 0.0) p.said.heading_deg += 360.0;
    }
    // What a program's machine does next, from what the last kept step left it
    // reading, and what its wheels are told for it. "roam": going forward, from
    // water seen ahead it backs off for kBackOffS and then turns away on the
    // spot, from the side that saw it -- one way and the other in turn when
    // both did -- the wheel on that side driving and the other backing. It
    // backs off first because a turn on the spot swings its front round: turned
    // where it saw the water, the caster went in. From wheels that stopped for
    // want of progress it does the same. From ground steeper than its climb_deg
    // -- rising ahead, or falling away to one side, where running along a
    // slope it climbs as surely and could tip -- it turns towards the lower
    // side. Turning, it goes on until
    // it has turned at least as far as it was turning for and nothing is in its
    // way ahead -- or kTurnMostS has passed, when it goes on regardless. Before
    // every step; nothing is timed here (settlePrograms).
    // What a hovering machine does next (LiveProgram, "hover"): its centre
    // held hover_m above the ground under it and level, moving by leaning --
    // the same asks as a rover's, done with thrust. Off, its rotors are off
    // and it falls: a machine that flies on its power. Low, it lands where it
    // is and rests on its brakes until charged. A height loop (a share of the
    // voltage for the weight, learnt; the error; the climb) and an attitude
    // loop (a lean of kLeanDeg to go; the rate) are mixed onto the four
    // rotors by where each stands on the chassis and which way it spins.
    void decideHover(Program &p, double dt_s) {
        constexpr double kPi = 3.14159265358979323846;
        constexpr double kDegPerRad = 180.0 / kPi;
        constexpr double kLeanDeg = 5.0;
        constexpr double kYawDegS = 40.0;
        constexpr double kFacedDeg = 6.0;
        constexpr double kNearM = 1.0;
        constexpr double kLandedM = 0.06;
        LiveProgram &s = p.said;
        std::vector<Control *> rotors;
        for (unsigned id : s.rotors)
            if (Control *c = controlById(id)) rotors.push_back(c);
        if (rotors.size() != s.rotors.size() || rotors.size() != p.rotor_local.size()) {
            s.doing = "stopped";
            s.why = "its rotors' controllers are gone";
            return;
        }
        const auto into = [&](const char *doing, std::string why) {
            if (s.doing != doing) {
                s.doing_s = 0.0;
                s.turned_deg = 0.0;
            }
            s.doing = doing;
            s.why = std::move(why);
        };
        const auto tellAll = [&](bool power, const std::vector<double> &settings) {
            for (std::size_t i = 0; i < rotors.size(); ++i) {
                LiveControl &now = rotors[i]->said;
                const int direction = power ? p.spins[i] : 0;
                const double setting = power ? std::clamp(settings[i], 0.0, 1.0) : now.setting;
                if (now.power == power && now.direction == direction && std::abs(now.setting - setting) < 1e-9)
                    continue;
                tell(*rotors[i], power, direction, setting, "program " + s.name, ++p.told);
            }
        };
        const std::vector<double> none(rotors.size(), 0.0);
        // Asks run out; a low battery drops them; off drops everything.
        const bool low = s.rest_below > 0.0 && s.charge_share < s.rest_below;
        if (!s.asked.empty() && (!s.power || low || (s.asked_for_s > 0.0 && s.asked_s >= s.asked_for_s))) {
            const bool done = s.power && !low;
            s.asked.clear();
            s.asked_why.clear();
            s.asked_by.clear();
            s.asked_for_s = s.asked_s = 0.0;
            if (done) into("waiting", "it has done what it was asked, and hovers");
        }
        if (!s.power) {
            into("stopped", "off");
            tellAll(false, none);
            p.hover_i = 0.0;
            return;
        }
        const bool landed = s.height_m <= p.landed_height_m + kLandedM && std::abs(s.climb_m_s) < 0.05;
        if (s.doing == "resting") {
            if (s.charge_share >= s.rest_until) {
                into("waiting", "its battery is charged again, and it takes off");
            } else {
                s.why = landed ? "its battery is low, so it rests on the ground where it landed"
                               : "its battery is low, so it comes down to rest";
                if (landed) {
                    tellAll(false, none);
                    return;
                }
            }
        } else if (low) {
            into("resting", "its battery is low, so it comes down to rest");
            ++s.rests;
        } else if (s.doing == "stopped") {
            into("waiting", "hovering");
        }
        // What it is asked, in its doing.
        double lean_deg = 0.0, yaw_deg_s = 0.0;
        if (!s.asked.empty() && s.doing != "resting") {
            if (s.asked == "facing" || s.asked == "approaching") {
                const double dx = s.asked_toward_m.x - s.at_m.x, dz = s.asked_toward_m.z - s.at_m.z;
                const double away = std::sqrt(dx * dx + dz * dz);
                double off = std::atan2(dx, dz) - p.heading_rad;
                while (off > kPi) off -= 2.0 * kPi;
                while (off <= -kPi) off += 2.0 * kPi;
                const double off_deg = off * kDegPerRad;
                if (s.asked == "approaching" && away <= kNearM) {
                    into("waiting", s.asked_why);
                } else if (std::abs(off_deg) > kFacedDeg &&
                           !(s.asked == "approaching" && s.doing == "going forward" && std::abs(off_deg) < 3.0 * kFacedDeg)) {
                    into(off_deg > 0.0 ? "turning left" : "turning right", s.asked_why);
                    p.turn_sign = off_deg > 0.0 ? 1 : -1;
                    yaw_deg_s = std::clamp(off_deg, -kYawDegS, kYawDegS);
                } else if (s.asked == "approaching") {
                    into("going forward", s.asked_why);
                    lean_deg = -kLeanDeg;
                    yaw_deg_s = std::clamp(off_deg, -kYawDegS, kYawDegS);
                } else {
                    into("waiting", s.asked_why);
                }
            } else {
                into(s.asked.c_str(), s.asked_why);
                if (s.asked == "going forward") lean_deg = -kLeanDeg;
                else if (s.asked == "backing off") lean_deg = kLeanDeg;
                else if (s.asked == "turning left") yaw_deg_s = kYawDegS;
                else if (s.asked == "turning right") yaw_deg_s = -kYawDegS;
                if (s.asked == "turning left") p.turn_sign = 1;
                if (s.asked == "turning right") p.turn_sign = -1;
            }
        } else if (s.doing != "resting") {
            into("waiting", "hovering");
        }
        // The chassis's own axes in the world, and its rates about them: nose
        // up is a turn about its left axis the negative way, its left side up
        // a turn about its front, and a turn to the left a turn about up.
        const auto found = index_of.find(s.body);
        if (found == index_of.end() || !inWorld(found->second)) return;
        const RigidSnapshot at = world->snapshot(body_of[found->second]);
        const Vec3 forward = at.orientation_world.rotate(p.forward_local);
        const Vec3 left = at.orientation_world.rotate(p.left_local);
        const Vec3 up = cross(forward, left);
        const double pitch_rate = -dot(p.spin, left) * kDegPerRad;
        const double roll_rate = dot(p.spin, forward) * kDegPerRad;
        const double yaw_rate = dot(p.spin, up) * kDegPerRad;
        // The height loop: a target of hover_m, or the ground to land; the
        // climb held to kClimbM_S either way.
        constexpr double kHoverShare = 0.6, kHeightP = 0.25, kHeightD = 0.35, kHeightI = 0.04, kClimbM_S = 1.0;
        const double target = s.doing == "resting" ? p.landed_height_m : p.landed_height_m + s.hover_m;
        const double error = target - s.height_m;
        const double climb_wanted = std::clamp(2.0 * error, -kClimbM_S, kClimbM_S);
        if (s.doing != "resting" && std::abs(error) < 0.5)
            p.hover_i = std::clamp(p.hover_i + kHeightI * error * dt_s, -0.3, 0.3);
        double collective = kHoverShare + p.hover_i + kHeightP * error + kHeightD * (climb_wanted - s.climb_m_s);
        if (s.doing == "resting") collective = std::min(collective, kHoverShare + p.hover_i - 0.05);
        // Holding its spot: not asked to go, it leans against the way it
        // drifts and back towards where it began to wait. Nose up slows it
        // going forward and brings it back from ahead, its left side up the
        // same from the left, the way a pilot does.
        constexpr double kHoldDegPerM_S = 6.0, kHoldDegPerM = 4.0, kHoldMostDeg = 6.0;
        Vec3 level_forward = forward, level_left = left;
        level_forward.y = level_left.y = 0.0;
        level_forward = normalized(level_forward);
        level_left = normalized(level_left);
        const double v_forward = dot(p.velocity, level_forward), v_left = dot(p.velocity, level_left);
        if (s.doing == "waiting") {
            if (!p.holding) {
                p.hold_at = s.at_m;
                p.holding = true;
            }
        } else {
            p.holding = false;
        }
        const Vec3 off_spot = p.holding ? s.at_m - p.hold_at : Vec3{};
        const double d_forward = dot(off_spot, level_forward), d_left = dot(off_spot, level_left);
        double lean_target = lean_deg, roll_target = 0.0;
        if (lean_deg == 0.0)
            lean_target = std::clamp(kHoldDegPerM_S * v_forward + kHoldDegPerM * d_forward, -kHoldMostDeg, kHoldMostDeg);
        roll_target = std::clamp(kHoldDegPerM_S * v_left + kHoldDegPerM * d_left, -kHoldMostDeg, kHoldMostDeg);
        // The attitude loop: lean as asked or as holding needs; turn as asked.
        constexpr double kAngleP = 0.012, kRateD = 0.0035, kYawP = 0.004;
        const double pitch_cmd = kAngleP * (lean_target - s.pitch_deg) - kRateD * pitch_rate;
        const double roll_cmd = kAngleP * (roll_target - s.roll_deg) - kRateD * roll_rate;
        const double yaw_cmd = kYawP * (yaw_deg_s - yaw_rate);
        double reach = 0.0;
        for (const Vec3 &r : p.rotor_local) reach = std::max(reach, std::max(std::abs(r.x), std::abs(r.z)));
        if (reach < 1e-6) reach = 1.0;
        std::vector<double> settings(rotors.size());
        for (std::size_t i = 0; i < rotors.size(); ++i) {
            const Vec3 &r = p.rotor_local[i];
            settings[i] = collective + pitch_cmd * (r.z / reach) + roll_cmd * (r.x / reach) - yaw_cmd * p.spins[i];
        }
        tellAll(true, settings);
    }

    // A machine that goes nowhere (a "still" program): on, it stands by;
    // asked to wait, it waits, for as long as it was asked; its battery low,
    // it rests until charged; off, it is stopped. Nothing is told to any
    // controller: what it does with its power is the routine over it.
    void decideStill(Program &p) {
        LiveProgram &s = p.said;
        const auto into = [&](const char *doing, std::string why) {
            if (s.doing != doing) {
                s.doing_s = 0.0;
                s.turned_deg = 0.0;
            }
            s.doing = doing;
            s.why = std::move(why);
        };
        const auto dropAsk = [&]() {
            s.asked.clear();
            s.asked_why.clear();
            s.asked_by.clear();
            s.asked_for_s = s.asked_s = 0.0;
        };
        if (!s.power) {
            dropAsk();
            into("stopped", "off");
            return;
        }
        const bool low = s.rest_below > 0.0 && s.charge_share < s.rest_below;
        if (s.doing == "resting") {
            if (s.charge_share < s.rest_until) return;
            into("standing by", "its battery is charged again");
        } else if (low) {
            dropAsk();
            into("resting", "its battery is low, so it rests until it is charged");
            ++s.rests;
            return;
        }
        if (!s.asked.empty() && s.asked_for_s > 0.0 && s.asked_s >= s.asked_for_s) {
            dropAsk();
            into("standing by", "it has done what it was asked");
        }
        if (!s.asked.empty()) {
            into("waiting", s.asked_why);
            return;
        }
        if (s.doing != "standing by") into("standing by", "ready");
    }

    void decideProgram(Program &p) {
        if (p.said.kind == "hover") {
            decideHover(p, p.last_dt_s > 0.0 ? p.last_dt_s : 1.0 / 240.0);
            return;
        }
        if (p.said.kind == "still") {
            decideStill(p);
            return;
        }
        constexpr double kPi = 3.14159265358979323846;
        constexpr double kBackOffS = 1.2;
        constexpr double kTurnMostS = 6.0;
        constexpr double kSideTurnDeg = 50.0;
        constexpr double kBackedTurnDeg = 110.0;
        constexpr double kClimbTurnDeg = 90.0;
        LiveProgram &s = p.said;
        Control *left = controlById(s.left);
        Control *right = controlById(s.right);
        if (left == nullptr || right == nullptr) {
            s.doing = "stopped";
            s.why = "its wheels' controllers are gone";
            return;
        }
        const auto into = [&](const char *doing, std::string why) {
            s.doing = doing;
            s.why = std::move(why);
            s.doing_s = 0.0;
            s.turned_deg = 0.0;
        };
        const auto turn = [&](int sign, double least, std::string why) {
            into(sign > 0 ? "turning left" : "turning right", std::move(why));
            p.turn_sign = sign;
            p.turn_least_deg = least;
            ++s.turns;
        };
        bool water_left = false, water_right = false;
        for (const LiveSensor &sensor : s.sensors) {
            if (!sensor.sees) continue;
            if (sensor.side >= 0) water_left = true;
            if (sensor.side <= 0) water_right = true;
        }
        const auto stalled = [](const Control &c) {
            return c.tripped && c.said.condition.rfind("stalled", 0) == 0;
        };
        const int alternate = s.turns % 2 == 0 ? 1 : -1;
        // What charges its battery: a solar panel wired to it with the sun on it.
        const LiveEnergyStore *store = storeOfProgram(p);
        const auto charging = [&]() {
            return std::any_of(panels.begin(), panels.end(), [&](const LiveSolarPanel &panel) {
                return store != nullptr && panel.store == store->id && panel.power_w > 0.0;
            });
        };
        // Why it rests: its panel charging it; or, with a panel and the sun
        // down, the night, which only the morning ends; or its panel in the
        // shade of something, or turned away from the sun, which a sun with a
        // day comes round to; or nothing at all.
        const auto resting = [&]() -> std::string {
            if (charging()) return "its battery is low, so it rests while its panel charges it";
            const LiveSolarPanel *mine = nullptr;
            for (const LiveSolarPanel &panel : panels)
                if (store != nullptr && panel.store == store->id) {
                    mine = &panel;
                    break;
                }
            if (mine != nullptr && sun.declared && sun.day_s > 0.0 && sun.toward.y <= 0.0)
                return "its battery is low and the sun is down, so it rests until morning";
            if (mine != nullptr && mine->shaded)
                return "its battery is low and its panel is in the shade of " + mine->shaded_by +
                       ", so it rests until the sun reaches it";
            if (mine != nullptr && sun.declared && sun.irradiance_w_m2 > 0.0 && !(mine->cos_incidence > 0.0))
                return sun.day_s > 0.0 ? "its battery is low and its panel is turned away from the sun, so it rests "
                                         "until the sun comes round to it"
                                       : "its battery is low and its panel is turned away from the sun, so nothing "
                                         "is charging it";
            return "its battery is low, and nothing is charging it";
        };
        const bool low = s.rest_below > 0.0 && s.charge_share < s.rest_below;
        // Asked to do something (LiveWorld::behave): that, until it has done it
        // for as long as it was asked, and then on as it would have. Turned
        // off or run low it drops the ask: it cannot do it anyway.
        const auto askDone = [&](const char *why) {
            s.asked.clear();
            s.asked_why.clear();
            s.asked_by.clear();
            s.asked_for_s = s.asked_s = 0.0;
            into("going forward", why);
        };
        if (!s.asked.empty() && (!s.power || low)) {
            s.asked.clear();
            s.asked_why.clear();
            s.asked_by.clear();
            s.asked_for_s = s.asked_s = 0.0;
        }
        const bool driving_ask = s.asked == "going forward" || s.asked == "approaching" || s.asked == "facing";
        constexpr double kClearBeforeAskS = 2.0;
        constexpr unsigned kInterruptionsMost = 3;
        if (!s.asked.empty() && !p.interrupted && driving_ask && (water_left || water_right)) {
            // As the roaming reflex meets water: back off first, whatever it
            // was doing -- a turn on the spot where it saw the water swings
            // the caster in -- and then turn away from the side that saw it.
            p.interrupted = true;
            ++p.interruptions;
            // And turn well away -- the ask was driving it AT the water, so
            // a glancing turn leaves a wheel at the edge.
            if (water_left && water_right) {
                into("backing off", "water ahead: its reflexes have it");
                p.then_turn = alternate;
            } else if (water_left) {
                into("backing off", "water ahead on its left: its reflexes have it");
                p.then_turn = -1;
            } else {
                into("backing off", "water ahead on its right: its reflexes have it");
                p.then_turn = 1;
            }
            p.turn_least_deg = kBackedTurnDeg;
        }
        // The ask has it back only after a couple of seconds of clear going:
        // turned back towards the water at once, it would turn on the spot at
        // the shore and its caster would go in.
        if (p.interrupted && (s.asked.empty() || (s.doing == "going forward" && !water_left && !water_right &&
                                                  s.doing_s >= kClearBeforeAskS)))
            p.interrupted = false;
        if (!s.asked.empty() && !p.interrupted && p.interruptions >= kInterruptionsMost) {
            p.interruptions = 0;
            askDone("the water was in the way of what it was asked, so it gave it up and goes on");
        } else if (!s.asked.empty() && s.asked_for_s > 0.0 && s.asked_s >= s.asked_for_s) {
            askDone("it has done what it was asked, and goes on");
        } else if (!s.asked.empty() && !p.interrupted) {
            constexpr double kFacedDeg = 6.0;
            constexpr double kNearM = 1.0;
            // The same ask again is the same doing: doing_s and turned_deg run on.
            const auto stay = [&](const char *doing) {
                if (s.doing != doing) into(doing, s.asked_why);
                else s.why = s.asked_why;
            };
            if (s.asked == "facing" || s.asked == "approaching") {
                // Which way, and how far, its front is from where it was asked
                // to look: positive is to its left, as heading is measured.
                const auto found = index_of.find(s.body);
                Vec3 at{};
                if (found != index_of.end() && inWorld(found->second))
                    at = world->snapshot(body_of[found->second]).center_of_mass_world_m;
                const double dx = s.asked_toward_m.x - at.x, dz = s.asked_toward_m.z - at.z;
                const double away = std::sqrt(dx * dx + dz * dz);
                double off = std::atan2(dx, dz) - p.heading_rad;
                while (off > kPi) off -= 2.0 * kPi;
                while (off < -kPi) off += 2.0 * kPi;
                const double off_deg = off * 180.0 / kPi;
                if (s.asked == "approaching" && away <= kNearM) stay("waiting");
                else if (std::abs(off_deg) > kFacedDeg && !(s.asked == "approaching" && s.doing == "going forward" &&
                                                            std::abs(off_deg) < 3.0 * kFacedDeg)) {
                    const char *doing = off_deg > 0.0 ? "turning left" : "turning right";
                    if (s.doing != doing) {
                        into(doing, s.asked_why);
                        p.turn_sign = off_deg > 0.0 ? 1 : -1;
                        p.turn_least_deg = std::abs(off_deg);
                    } else {
                        s.why = s.asked_why;
                    }
                } else if (s.asked == "approaching") {
                    stay("going forward");
                } else {
                    stay("waiting");
                }
            } else {
                stay(s.asked.c_str());
            }
        } else if (!s.power) {
            if (s.doing != "stopped") into("stopped", "off");
        } else if (s.doing == "stopped" || s.doing == "waiting") {
            into("going forward", p.interrupted ? "its reflexes have it: water ahead" : "nothing in its way");
        } else if (s.doing == "resting") {
            if (s.charge_share >= s.rest_until) into("going forward", "its battery is charged again");
            else s.why = resting();
        } else if (low) {
            // Whatever it is doing: it stops where it is, on its brakes.
            into("resting", resting());
            ++s.rests;
        } else if (s.doing == "going forward") {
            if (water_left && water_right) {
                into("backing off", "water ahead");
                p.then_turn = alternate;
                p.turn_least_deg = kBackedTurnDeg;
            } else if (water_left) {
                into("backing off", "water ahead on its left");
                p.then_turn = -1;
                p.turn_least_deg = kSideTurnDeg;
            } else if (water_right) {
                into("backing off", "water ahead on its right");
                p.then_turn = 1;
                p.turn_least_deg = kSideTurnDeg;
            } else if (stalled(*left) || stalled(*right)) {
                into("backing off", "its wheels made no progress");
                p.then_turn = alternate;
                p.turn_least_deg = kBackedTurnDeg;
            } else if (s.pitch_deg > s.climb_deg || std::abs(s.roll_deg) > s.climb_deg) {
                // Towards the lower side: its left side up, that is the right.
                turn(s.roll_deg > 0.0 ? -1 : 1, kClimbTurnDeg, "the ground here is steeper than it climbs");
            }
        } else if (s.doing == "backing off") {
            // Taken from an ask that was driving it at the water, it backs
            // off twice as far before it turns: it may be at the very edge.
            const double back_off_s = p.interrupted ? 2.0 * kBackOffS : kBackOffS;
            if (s.doing_s >= back_off_s || stalled(*left) || stalled(*right)) {
                const std::string why = s.why;
                turn(p.then_turn, p.turn_least_deg, why);
            }
        } else if (s.doing == "turning left" || s.doing == "turning right") {
            const bool clear = !water_left && !water_right && s.pitch_deg <= s.climb_deg &&
                               std::abs(s.roll_deg) <= s.climb_deg;
            if (clear && s.turned_deg >= p.turn_least_deg)
                into("going forward", "nothing in its way");
            else if (s.doing_s >= kTurnMostS)
                into("going forward", "it could not turn clear in time, so it goes on");
        }
        int l = 0, r = 0;   // stopped, resting or waiting: held on their brakes
        if (s.doing == "going forward") l = r = 1;
        else if (s.doing == "backing off") l = r = -1;
        else if (s.doing == "turning left") l = -1, r = 1;
        else if (s.doing == "turning right") l = 1, r = -1;
        // Each wheel told only what it is not doing already: one that stopped
        // for want of progress stays stopped, told the same, and the program
        // reads that and backs off.
        const auto tellWheel = [&](Control &c, int direction) {
            const LiveControl &now = c.said;
            if (now.power == s.power && now.direction == direction && now.setting == s.setting) return;
            tell(c, s.power, direction, s.setting, "program " + s.name, ++p.told);
        };
        tellWheel(*left, l);
        tellWheel(*right, r);
    }
    void preparePrograms() {
        for (Program &p : programs) decideProgram(p);
    }
    // After a kept step: what each program's machine reads now, how long it
    // has been doing what it is doing, and how far it has turned in it.
    void settlePrograms(double dt_s) {
        constexpr double kPi = 3.14159265358979323846;
        constexpr double kDegPerRad = 180.0 / kPi;
        for (Program &p : programs) {
            const double was = p.heading_rad;
            readProgram(p);
            p.last_dt_s = dt_s;
            if (!p.said.power) continue;
            p.said.doing_s += dt_s;
            if (!p.said.asked.empty()) p.said.asked_s += dt_s;
            if (p.said.doing == "turning left" || p.said.doing == "turning right") {
                double turned = p.heading_rad - was;
                while (turned > kPi) turned -= 2.0 * kPi;
                while (turned < -kPi) turned += 2.0 * kPi;
                p.said.turned_deg += p.turn_sign * turned * kDegPerRad;
            }
        }
    }

    void rememberJointAngles(const JoltWorld &in) {
        for (SceneJoint &joint : joints)
            if (joint.rigid != 0 && in.hasJoint(joint.rigid))
                joint.at_when_hung = in.jointState(joint.rigid).at;
    }
    // Which way a joint's load runs through its member: along a fixing's axis,
    // or along the line between a link's or a spring's two ends. The member's
    // section across that is what carries it. Zero when an end is missing, or
    // not in the world (set aside, LiveWorld::park).
    [[nodiscard]] Vec3 loadDirection(const SceneJoint &joint) const {
        const auto one = index_of.find(joint.a), two = index_of.find(joint.b);
        if (one == index_of.end() || two == index_of.end()) return {};
        if (!inWorld(one->second) || !inWorld(two->second)) return {};
        const RigidSnapshot sa = world->snapshot(body_of[one->second]);
        if (joint.kind == JoltWorld::JointKind::Fixing)
            return sa.orientation_world.rotate(joint.axis_local_a);
        const RigidSnapshot sb = world->snapshot(body_of[two->second]);
        return (sb.center_of_mass_world_m + sb.orientation_world.rotate(joint.point_local_b_tie)) -
               (sa.center_of_mass_world_m + sa.orientation_world.rotate(joint.point_local_a));
    }
    // How far apart a link's or a spring's two attachment points are now.
    [[nodiscard]] double spanOf(const SceneJoint &joint) const { return length(loadDirection(joint)); }
    // The material a body was built from, as the scene defined it.
    [[nodiscard]] const MaterialDefinition &definitionOf(std::size_t body) const {
        // An exact body is made of what it says, not of the scene's tile.
        if (isPrecise(body)) {
            const auto found = precise_bodies.find(described[body].name);
            if (found != precise_bodies.end()) return found->second.made_of;
        }
        if (setup->multi_body && body < nodes_of.size() && !nodes_of[body].empty() &&
            nodes_of[body].front() < setup->part_of_node.size()) {
            const std::uint32_t part = setup->part_of_node[nodes_of[body].front()];
            if (part < setup->part_definitions.size()) return setup->part_definitions[part];
        }
        return setup->tile_material;
    }

    // ---- Blades and cuts (docs/cutting-model.md) --------------------------
    struct Blade {
        unsigned id{};
        std::string body;
        // In the body's own frame, about its centre of mass -- which is what
        // lets a sword be carried across the room with its edge still on the
        // same side of the steel.
        Vec3 heel_local{}, tip_local{}, facing_local{}, grip_local{};
        double thickness{}, edge_radius{}, bevel_deg{};
        double cut_area{}, cut_work{};
        std::string cutting;
        bool attached{true};
        // The rigid body the frame above belongs to, and the body's cells as
        // they sat in it. A body that comes through a fracture whole is put
        // back in a NEW frame; these are what let the edge follow its own steel
        // into it rather than end up somewhere in the air beside it.
        MatterBodyId body_id{};
        std::vector<std::uint32_t> frame_nodes;
        std::vector<Vec3> frame_offsets;
    };
    std::vector<Blade> blades;
    unsigned next_blade{1};
    std::string blade_refusal;   // why the last blade() said no, in words
    // Every contact the rigid solver resolved this step between a blade and
    // anything else: how a flat strike or a glance gets reported, from the
    // contact's own normal rather than from a guess.
    std::vector<ImpactEvent> blade_contacts;
    // Bodies whose severed bonds leave them in pieces, waiting for a fracture
    // that holds indices into the body table to finish before they are split.
    std::set<std::string> split_later;
    // A cut through one body, in that body's own frame. `u` runs along the
    // edge as it was when it bit, `v` the way it faced and `w` across its
    // flats. What has been swept is kept per strip of `u` as the stretches of
    // `v` the edge has been through. Stretches, not one: an edge that turns or
    // slides as it cuts crosses each strip's matter somewhere new, and a strip
    // kept as one stretch grown from its end refused a mark that did not touch
    // it -- the matter stayed, and it held the pieces together.
    struct Kerf {
        unsigned blade{};
        Vec3 origin{}, u{}, v{}, w{};
        double strip{};
        double half_width{};
        std::map<int, std::vector<std::pair<double, double>>> swept;
        // Every bond that crosses this kerf's plane, and where. A bond is
        // severed when the swept part of the plane reaches where it crosses.
        struct Crossing {
            std::uint32_t bond{};
            double u{}, v{};
            Vec3 at_local{};
        };
        std::vector<Crossing> crossings;
        [[nodiscard]] bool covers(double at_u, double at_v, double slack = 0.0) const {
            const auto found = swept.find(static_cast<int>(std::floor(at_u / strip)));
            if (found == swept.end()) return false;
            for (const auto &span : found->second)
                if (at_v >= span.first - slack && at_v <= span.second + slack) return true;
            return false;
        }
        // How much of [low, high] strip `s` does not hold yet. Its stretches
        // are kept apart and in order, so what they cover can be subtracted.
        [[nodiscard]] double uncovered(int s, double low, double high) const {
            double open = std::max(0.0, high - low);
            const auto found = swept.find(s);
            if (found == swept.end()) return open;
            for (const auto &span : found->second)
                open -= std::max(0.0, std::min(high, span.second) - std::max(low, span.first));
            return std::max(0.0, open);
        }
        // [low, high] swept through strip `s`, joined to whatever it touches.
        void add(int s, double low, double high, double join) {
            if (!(high > low)) return;
            auto &spans = swept[s];
            spans.emplace_back(low, high);
            std::sort(spans.begin(), spans.end());
            std::vector<std::pair<double, double>> merged;
            for (const auto &span : spans) {
                if (!merged.empty() && span.first <= merged.back().second + join)
                    merged.back().second = std::max(merged.back().second, span.second);
                else
                    merged.push_back(span);
            }
            spans = std::move(merged);
        }
        // Where the stretch that `at` is in ends, or `at` if it is in none.
        [[nodiscard]] double throughTo(int s, double at) const {
            const auto found = swept.find(s);
            if (found == swept.end()) return at;
            for (const auto &span : found->second)
                if (span.first <= at + 1e-6 && span.second > at) return span.second;
            return at;
        }
        [[nodiscard]] double area() const {
            double total = 0.0;
            for (const auto &entry : swept)
                for (const auto &span : entry.second) total += std::max(0.0, span.second - span.first);
            return total * strip;
        }
    };
    std::unordered_map<std::string, std::vector<Kerf>> kerfs;
    // An edge in matter this step: set up before the step, accounted after it.
    struct Engagement {
        unsigned blade{};
        std::string target;
        std::size_t kerf{};
        unsigned rigid{};
        bool embedded{};
        double resistance{};     // R = G + H w, J/m^2
        double push_n{};         // how hard the hand and gravity push the edge in, N
        std::size_t cut{};       // its entry in cut_log
        // The constraint's frame and the relative motion at the start of the
        // step, so the step can be accounted for once it has run.
        Vec3 point_blade_local{}, point_target_local{};
        Vec3 n_world{}, t_world{};
        double vn_before{}, vt_before{};
        double touching_m{};
        // What the edge cut on its way out of the far side that the step's
        // work did not cover, m^2: taken at once from the closing motion
        // (settleCuts, settleOwed), so no cut is left unpaid.
        double owed_m2{};
        // The engaged part of the edge: each sample's place in the blade's own
        // frame and, at the start of the step, in the target's.
        std::vector<Vec3> sample_blade_local, sample_start_target_local;
        double sample_ds{};
    };
    std::vector<Engagement> engaged;
    // Pairs whose ordinary rigid contact is suspended until the blade is clear
    // of the target's matter: a blade still in its kerf, or lying between two
    // pieces it has just made.
    std::set<std::pair<unsigned, std::string>> exempt;
    // Where the bodies a cut has just replaced were at that moment, so a joint
    // can follow its own end into the piece that holds it. See rehangJoints.
    std::unordered_map<std::string, RigidSnapshot> vanished;
    std::vector<LiveCut> cut_log;
    // Contacts that did not bite, still open, by (blade, target).
    std::map<std::pair<unsigned, std::string>, std::pair<std::size_t, std::uint64_t>> touching;
    // The physical grip. See wield(): a bounded force at a point on the body
    // and a bounded torque, towards where the hand wants it.
    bool wielding{};
    Vec3 grip_local{};
    double hand_torque_n_m{60.0};
    // The moving mass of the hand and arm, which the strength has to get going
    // along with whatever it throws: 2 kg, a DEMONSTRATION value for a hand,
    // forearm and part of an upper arm as felt at the hand. Only a stroke uses
    // it, to bound how fast the hand itself can accelerate.
    double hand_mass_kg{2.0};
    // How fast the hand wants the grip to move: the stroke's own speed along its
    // path, or nothing when the host holds the hand still. The hand damps motion
    // RELATIVE to this. Damped against the absolute velocity it is a hand that
    // wants everything at rest, and a throw stops where that damping cancels the
    // pull -- 2.8 m/s, for a ball held 50 mm behind the hand.
    Vec3 held_velocity{};
    // What the hand is applying for the coming step. The cut's static rule
    // needs to know which way the blade is being pushed when it is not moving.
    Vec3 hand_force{};

    // A stroke the hand is making by itself (LiveWorld::stroke).
    struct Stroke {
        LiveStroke asked;
        std::vector<double> at_m;         // how far along the path each point is
        double length_m{};
        double target_along_m{};          // where the hand wants the grip, on the path
        double target_speed_m_s{};
        double grip_along_m{};            // where the grip has got to
        double began_s{};
        // Where the grip has been lately, (time, along), for "blocked".
        std::deque<std::pair<double, double>> recent;
    };
    std::optional<Stroke> stroke;
    std::string stroke_ended;
    // The work the hand has done on what it holds since taking hold, and what
    // it pulled with in the last kept step. See LiveHand.
    double hand_work_j{};
    Vec3 hand_applied_n{};
    // A haul is pushed after one step to act in the next -- and again whenever
    // the hand is moved between steps, which is the double pull -- so these are
    // the haul pulls sitting in the force accumulator for the coming step. Its
    // work is counted in the step it acts in, not the one that pushed it.
    Vec3 haul_pushed{};
    // Taken as a step begins, for what the step does; kept only if it is kept.
    struct HandStep {
        bool measuring{};
        std::string name;
        // How fast the grip moves and the body turns as the step begins. A
        // force's work over a step is the force times the AVERAGE of the
        // velocities at the two ends: for the solver's step that is exactly
        // what the force added to the kinetic energy, which the grip's
        // displacement is not -- that overstates it by F dt^2 / 2m a step,
        // 14% of a light ball's throw.
        Vec3 grip_velocity_from{}, spin_from{};
        Vec3 haul_in{};                   // the haul pulls this step starts with
        double target_along_m{}, target_speed_m_s{};
    };
    HandStep hand_step;
    // What the last stroke that opened the hand let go of, and how.
    std::string let_go_body;
    Vec3 let_go_velocity{};
    double let_go_at_s{-1.0};
    double let_go_work_j{};

    // Tools that work the ground (ToolTerrain.hpp, docs/ground-work.md): the
    // points declared on bodies, and each one's meetings with the ground.
    ToolTerrain tools;
    std::string tool_point_refusal;

    // Things set aside (LiveWorld::park), by name: the body table is
    // rearranged by every break and every sweep, and a name survives that where
    // an index does not. Each keeps where it was and what it weighed when it was
    // put away -- what a bag holding it would say of it. Its slot in the tables
    // stays, so everything it is made of stays with it.
    struct ParkedRecord {
        RigidSnapshot pose{};
        double mass_kg{};
    };
    std::unordered_map<std::string, ParkedRecord> parked;
    [[nodiscard]] bool isParked(std::size_t slot) const {
        return slot < described.size() && parked.count(described[slot].name) != 0;
    }
    // Whether a slot's body is in the world to be asked about. Not one set
    // aside: its rigid body is kept out of the world, and every question the
    // rigid world is asked about it is a throw rather than an answer.
    [[nodiscard]] bool inWorld(std::size_t slot) const {
        return slot < body_of.size() && world->contains(body_of[slot]);
    }
    // Everything held to a slot by a joint still attached, that slot first:
    // the whole of a thing of parts on pins -- a cart and its two wheelsets --
    // by whichever part it is taken. What goes into the bag with it and comes
    // back out with it (LiveWorld::park, unpark).
    [[nodiscard]] std::vector<std::size_t> jointedWith(std::size_t slot) const {
        std::vector<std::size_t> out{slot};
        for (std::size_t k = 0; k < out.size(); ++k) {
            const std::string &name = described[out[k]].name;
            for (const SceneJoint &joint : joints) {
                if (!joint.attached || (joint.a != name && joint.b != name)) continue;
                const auto other = index_of.find(joint.a == name ? joint.b : joint.a);
                if (other != index_of.end() && std::find(out.begin(), out.end(), other->second) == out.end())
                    out.push_back(other->second);
            }
        }
        return out;
    }
    // A joint away in the bag with the thing it is in: still attached, with
    // nothing standing in for it until the thing is back.
    [[nodiscard]] bool setAside(const SceneJoint &joint) const {
        if (!joint.attached) return false;
        for (const std::string *end : {&joint.a, &joint.b}) {
            const auto at = index_of.find(*end);
            if (at != index_of.end() && isParked(at->second)) return true;
        }
        return false;
    }
    [[nodiscard]] double carriedObjectsKg(bool include_hand = true) const {
        // Use native mass, including saved parked mass. Construction recipes
        // would silently restore material removed by damage or burning.
        double kg=0;
        for (const auto &entry:parked) kg+=entry.second.mass_kg;
        if (include_hand && holding!=static_cast<std::size_t>(-1) && inWorld(holding))
            kg+=world->mechanicalState(body_of[holding]).mass_kg;
        return kg;
    }
    // The lattice this world's scene builds, in a few numbers (fingerprintOf):
    // a saved world carries them, and is only ever opened into the same cells.
    std::size_t fingerprint_nodes{}, fingerprint_bonds{};
    std::string fingerprint_hash;
    // And each authored part of it, and what lays every cell out (PartPrint,
    // latticeSettingsOf): what a world carried into this scene once it has
    // changed finds each thing's cells again by.
    std::vector<PartPrint> part_prints;
    std::string lattice_settings;
    // What opening from a saved world gave back (LiveWorld::restored).
    LiveRestore restored;
    // The rigid bodies told what the thermal network says they weigh now, so
    // momentum and energy are about what is really there: after an accepted
    // step, and when a thing set aside comes back into the world.
    void mirrorMasses() {
        if (!thermo) return;
        for (const auto &[name, kg] : thermo->massesToMirror(1.0e-3)) {
            const auto found = index_of.find(name);
            if (found == index_of.end() || described[found->second].anchored) continue;
            const MatterBodyId id = body_of[found->second];
            if (world->contains(id)) world->setMass(id, kg);
        }
    }
};

// A saved world, as read back (LiveWorld::snapshot).
struct LiveWorld::Saved {
    nlohmann::json doc;
};

namespace {

// What a saved world says it is. It carries the scene's cells under their own
// numbers, so a document written by anything else is not read as one.
constexpr const char *kWorldFormat = "banjo.world.v1";

// A saved world that does not fit the scene it is being opened into.
struct SavedWorldMismatch : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// The lattice a scene builds, in a few numbers: how many cells and bonds, and a
// hash of where each cell is (to the micrometre), which part it belongs to, and
// which two cells each bond joins. A saved world names its bodies' cells by
// these numbers, so it can only be opened into a scene that builds the same
// ones: another scene, or this one under a build that lays its cells out
// another way, would hand it cells it does not have.
struct LatticeFingerprint {
    std::size_t nodes{}, bonds{};
    std::string hash;
};

LatticeFingerprint fingerprintOf(const TileImpactSetup &setup) {
    std::uint64_t h = 1469598103934665603ULL;   // FNV-1a, 64 bits
    const auto mix = [&h](std::uint64_t v) {
        for (int i = 0; i < 8; ++i) {
            h ^= (v >> (8 * i)) & 0xffU;
            h *= 1099511628211ULL;
        }
    };
    const auto micrometres = [](double v) {
        return static_cast<std::uint64_t>(static_cast<std::int64_t>(std::llround(v * 1.0e6)));
    };
    mix(setup.matter.nodes.size());
    mix(setup.asset.bonds.size());
    for (std::size_t i = 0; i < setup.matter.nodes.size(); ++i) {
        const Vec3 &at = setup.matter.nodes[i].position_world_m;
        mix(i < setup.part_of_node.size() ? setup.part_of_node[i] : 0xffffffffU);
        mix(micrometres(at.x));
        mix(micrometres(at.y));
        mix(micrometres(at.z));
    }
    for (const BondRest &bond : setup.asset.bonds) {
        mix(bond.node_a);
        mix(bond.node_b);
    }
    char text[17];
    std::snprintf(text, sizeof text, "%016llx", static_cast<unsigned long long>(h));
    return {setup.matter.nodes.size(), setup.asset.bonds.size(), text};
}

// A number as text, exactly: two definitions are the same only when every
// number in them is.
std::string exactly(double v) {
    char text[40];
    std::snprintf(text, sizeof text, "%.17g", v);
    return text;
}

// What lays out every cell of every body, whatever the body: a saved thing's
// cells can only be found again under their numbers in a scene that lays cells
// out the same way.
std::string latticeSettingsOf(const TileImpactRequest &r) {
    return "cell " + exactly(r.cell_size_m) + " horizon " + std::to_string(r.neighbor_horizon_cells) + " seed " +
           std::to_string(r.material_seed) + " law " + std::to_string(static_cast<int>(r.failure_law)) +
           " plastic " + std::to_string(r.plasticity ? 1 : 0) + " hardening " + exactly(r.hardening_ratio) +
           " loose " + std::to_string(r.loose_cells ? 1 : 0) + " catalog " + std::to_string(r.catalog_material ? 1 : 0);
}

// One authored body by every field it was authored with: a thing is unchanged
// only when every one of them is -- where it was made, how it was set moving,
// its colour and its join as much as its shape and what it is made of.
std::string bodyDefinition(const SceneBody &b) {
    const auto three = [](const Vec3 &v) { return exactly(v.x) + " " + exactly(v.y) + " " + exactly(v.z); };
    const auto word = [](const std::string &s) { return std::to_string(s.size()) + ":" + s; };
    return word(b.name) + " shape " + std::to_string(static_cast<int>(b.shape)) + " material " +
           std::to_string(static_cast<int>(b.material)) + " size " + three(b.dimensions_m) + " at " +
           three(b.center_m) + " moving " + three(b.velocity_m_s) + " spinning " + three(b.spin_rad_s) +
           " turned " + three(b.rotation_deg) + (b.anchored ? " anchored" : " loose") + (b.subtract ? " cuts" : " adds") +
           " colour " + std::to_string(b.color_rgba) + " join " + word(b.join);
}

// What the scene declares of each body's heat and contents, by name: the fields
// of a body's own entry in the scene document the thermal network reads
// (readSceneSettings).
std::unordered_map<std::string, std::string> heatDeclarationsOf(const std::string &scene_json) {
    std::unordered_map<std::string, std::string> out;
    if (scene_json.empty()) return out;
    const nlohmann::json doc = nlohmann::json::parse(scene_json, nullptr, false);
    if (!doc.is_object() || !doc.contains("bodies") || !doc.at("bodies").is_array()) return out;
    for (const nlohmann::json &body : doc.at("bodies")) {
        if (!body.is_object() || !body.contains("name") || !body.at("name").is_string()) continue;
        nlohmann::json said = nlohmann::json::object();
        for (const char *key : {"contents", "temperature_k", "layer_depth_m", "environment"})
            if (body.contains(key)) said[key] = body.at(key);
        if (!said.empty()) out[body.at("name").get<std::string>()] = said.dump();
    }
    return out;
}

// Each authored part of a scene, as a saved world names it (PartPrint): where
// its cells and bonds begin and end, what they are, and what its bodies were
// authored as.
std::vector<PartPrint> partPrintsOf(const TileImpactSetup &setup, const TileImpactRequest &r) {
    if (!setup.multi_body || setup.part_of_node.size() != setup.matter.nodes.size()) return {};
    const std::size_t count = setup.part_bodies.size();
    constexpr std::uint32_t kNone = std::numeric_limits<std::uint32_t>::max();
    std::vector<std::uint32_t> first_node(count, kNone), last_node(count, 0), nodes(count, 0);
    std::vector<std::uint32_t> first_bond(count, kNone), last_bond(count, 0), bonds(count, 0);
    std::vector<char> crossed(count, 0);
    for (std::uint32_t i = 0; i < setup.part_of_node.size(); ++i) {
        const std::uint32_t p = setup.part_of_node[i];
        if (p >= count) return {};
        first_node[p] = std::min(first_node[p], i);
        last_node[p] = std::max(last_node[p], i);
        ++nodes[p];
    }
    const std::vector<BondRest> &rest = setup.asset.bonds;
    for (std::uint32_t k = 0; k < rest.size(); ++k) {
        if (rest[k].node_a >= setup.part_of_node.size() || rest[k].node_b >= setup.part_of_node.size()) return {};
        const std::uint32_t p = setup.part_of_node[rest[k].node_a];
        if (setup.part_of_node[rest[k].node_b] != p) crossed[p] = 1;
        first_bond[p] = std::min(first_bond[p], k);
        last_bond[p] = std::max(last_bond[p], k);
        ++bonds[p];
    }
    const std::unordered_map<std::string, std::string> heat = heatDeclarationsOf(r.thermo_scene_json);
    std::vector<PartPrint> parts(count);
    for (std::size_t p = 0; p < count; ++p) {
        PartPrint &part = parts[p];
        for (const std::size_t index : setup.part_bodies[p]) {
            if (index >= r.bodies.size()) continue;
            const SceneBody &body = r.bodies[index];
            part.bodies.push_back(body.name);
            part.definition += bodyDefinition(body) + "\n";
            const auto said = heat.find(body.name);
            part.heat += (said == heat.end() ? std::string{} : said->second) + "\n";
            if (body.anchored) part.anchored = true;
        }
        if (nodes[p] == 0) continue;
        part.node_begin = first_node[p];
        part.node_end = last_node[p] + 1;
        part.bond_begin = bonds[p] == 0 ? part.node_begin : first_bond[p];
        part.bond_end = bonds[p] == 0 ? part.node_begin : last_bond[p] + 1;
        if (part.node_end - part.node_begin != nodes[p] || crossed[p] != 0 ||
            (bonds[p] != 0 && part.bond_end - part.bond_begin != bonds[p]))
            continue;
        // What fingerprintOf takes of the whole lattice, for this part alone:
        // where each of its cells is, to the micrometre, and which two of its
        // cells each of its bonds joins, counted from its own first cell.
        std::uint64_t h = 1469598103934665603ULL;   // FNV-1a, 64 bits
        const auto mix = [&h](std::uint64_t v) {
            for (int i = 0; i < 8; ++i) {
                h ^= (v >> (8 * i)) & 0xffU;
                h *= 1099511628211ULL;
            }
        };
        const auto micrometres = [](double v) {
            return static_cast<std::uint64_t>(static_cast<std::int64_t>(std::llround(v * 1.0e6)));
        };
        mix(nodes[p]);
        mix(bonds[p]);
        for (std::uint32_t i = part.node_begin; i < part.node_end; ++i) {
            const Vec3 &at = setup.matter.nodes[i].position_world_m;
            mix(micrometres(at.x));
            mix(micrometres(at.y));
            mix(micrometres(at.z));
        }
        for (std::uint32_t k = part.bond_begin; k < part.bond_end; ++k) {
            mix(rest[k].node_a - part.node_begin);
            mix(rest[k].node_b - part.node_begin);
        }
        char text[17];
        std::snprintf(text, sizeof text, "%016llx", static_cast<unsigned long long>(h));
        part.cells = text;
    }
    return parts;
}

// Numbers as a saved world writes them: every double exactly (a JSON number
// round-trips a double), and the few that are not finite as words, because
// JSON has no infinity.
nlohmann::json savedNumber(double v) {
    if (std::isfinite(v)) return v;
    if (std::isnan(v)) return "nan";
    return v > 0.0 ? "inf" : "-inf";
}

double numberFrom(const nlohmann::json &j) {
    if (j.is_number()) return j.get<double>();
    const std::string word = j.get<std::string>();
    if (word == "inf") return std::numeric_limits<double>::infinity();
    if (word == "-inf") return -std::numeric_limits<double>::infinity();
    if (word == "nan") return std::numeric_limits<double>::quiet_NaN();
    throw std::invalid_argument("\"" + word + "\" is not a number");
}

nlohmann::json savedVec(const Vec3 &v) {
    return nlohmann::json::array({savedNumber(v.x), savedNumber(v.y), savedNumber(v.z)});
}

Vec3 vecFrom(const nlohmann::json &j) { return {numberFrom(j.at(0)), numberFrom(j.at(1)), numberFrom(j.at(2))}; }

nlohmann::json savedQuat(const Quat &q) {
    return nlohmann::json::array({savedNumber(q.w), savedNumber(q.x), savedNumber(q.y), savedNumber(q.z)});
}

Quat quatFrom(const nlohmann::json &j) {
    return Quat{numberFrom(j.at(0)), numberFrom(j.at(1)), numberFrom(j.at(2)), numberFrom(j.at(3))};
}

nlohmann::json savedRigid(const RigidSnapshot &s) {
    return {{"com_m", savedVec(s.center_of_mass_world_m)}, {"q_wxyz", savedQuat(s.orientation_world)},
            {"v_m_s", savedVec(s.linear_velocity_m_s)}, {"w_rad_s", savedVec(s.angular_velocity_rad_s)}};
}

RigidSnapshot rigidFrom(const nlohmann::json &j) {
    RigidSnapshot s{};
    s.center_of_mass_world_m = vecFrom(j.at("com_m"));
    s.orientation_world = quatFrom(j.at("q_wxyz"));
    s.linear_velocity_m_s = vecFrom(j.at("v_m_s"));
    s.angular_velocity_rad_s = vecFrom(j.at("w_rad_s"));
    return s;
}

// Arrays as base64 of their bytes, little-endian as every machine this runs on
// is: a bowl's two thousand cells are two thousand numbers, not a page of them.
template <class T>
std::string packedArray(const std::vector<T> &values) {
    return terrain::encodeBase64(values.data(), values.size() * sizeof(T));
}

template <class T>
std::vector<T> unpackedArray(const nlohmann::json &holder, const char *key) {
    const std::vector<std::uint8_t> bytes = terrain::decodeBase64(holder.at(key).get<std::string>());
    if (bytes.size() % sizeof(T) != 0) throw std::invalid_argument(std::string(key) + " is cut short");
    std::vector<T> out(bytes.size() / sizeof(T));
    if (!bytes.empty()) std::memcpy(out.data(), bytes.data(), bytes.size());
    return out;
}

std::string packedVecs(const std::vector<Vec3> &values) {
    std::vector<double> flat;
    flat.reserve(3 * values.size());
    for (const Vec3 &v : values) {
        flat.push_back(v.x);
        flat.push_back(v.y);
        flat.push_back(v.z);
    }
    return packedArray(flat);
}

std::vector<Vec3> unpackedVecs(const nlohmann::json &holder, const char *key) {
    const std::vector<double> flat = unpackedArray<double>(holder, key);
    if (flat.size() % 3 != 0) throw std::invalid_argument(std::string(key) + " is not points of three numbers");
    std::vector<Vec3> out;
    out.reserve(flat.size() / 3);
    for (std::size_t k = 0; k + 2 < flat.size(); k += 3) out.push_back({flat[k], flat[k + 1], flat[k + 2]});
    return out;
}

const char *savedKind(JoltWorld::JointKind kind) {
    switch (kind) {
    case JoltWorld::JointKind::Slider: return "slider";
    case JoltWorld::JointKind::Link: return "link";
    case JoltWorld::JointKind::Pulley: return "pulley";
    case JoltWorld::JointKind::Fixing: return "fixing";
    case JoltWorld::JointKind::Elastic: return "elastic";
    case JoltWorld::JointKind::Drum: return "drum";
    default: return "hinge";
    }
}

JoltWorld::JointKind kindFrom(const std::string &word) {
    if (word == "slider") return JoltWorld::JointKind::Slider;
    if (word == "link") return JoltWorld::JointKind::Link;
    if (word == "pulley") return JoltWorld::JointKind::Pulley;
    if (word == "fixing") return JoltWorld::JointKind::Fixing;
    if (word == "elastic") return JoltWorld::JointKind::Elastic;
    if (word == "drum") return JoltWorld::JointKind::Drum;
    if (word == "hinge") return JoltWorld::JointKind::Hinge;
    throw std::invalid_argument("\"" + word + "\" is not a kind of joint");
}

// One body of a saved world: where it goes once it is made from its cells.
struct Placement {
    std::string name;
    MatterBodyId id{};
    RigidSnapshot pose{};
    bool anchored{};
    bool awake{true};
    bool parked{};
    double parked_mass_kg{};
};

// What the scene declares about heat, for a world opened from a saved one:
// only what is about something still there. A pane that broke is its pieces
// now, and a declaration naming it would refuse the scene.
void keepWhatIsThere(thermo::Declarations &declared,
                     const std::unordered_map<std::string, std::size_t> &index_of) {
    const auto there = [&index_of](const std::string &name) { return index_of.count(name) != 0; };
    std::erase_if(declared.regions, [&](const thermo::GasRegionDeclaration &region) {
        return (!region.piston.empty() && !there(region.piston)) ||
               (!region.container.empty() && !there(region.container));
    });
    std::set<std::string> regions;
    for (const thermo::GasRegionDeclaration &region : declared.regions) regions.insert(region.name);
    std::erase_if(declared.contents, [&](const thermo::ContentsDeclaration &contents) {
        return !there(contents.body) || (!contents.environment.empty() && regions.count(contents.environment) == 0);
    });
    std::erase_if(declared.heaters, [&](const thermo::HeaterDeclaration &heater) {
        return !there(heater.target) && regions.count(heater.target) == 0;
    });
}

// How a saved world goes into a scene that has changed since it was saved
// (LiveWorld::open with a carry): which of its authored parts are still what
// they were and where their cells and bonds are numbered now, which of its
// bodies come back as they were saved, and why each of the rest does not.
struct CarryPlan {
    static constexpr std::size_t npos = static_cast<std::size_t>(-1);
    static constexpr std::uint32_t none = std::numeric_limits<std::uint32_t>::max();
    // False when no cell can be found again: the saved world does not say what
    // its parts were, or the scene now lays every cell out another way.
    bool exact{};
    std::string why_not;
    struct SavedPart {
        std::uint32_t node_begin{}, node_end{}, bond_begin{}, bond_end{};
        std::string cells, definition, heat;
        std::vector<std::string> bodies;
        std::size_t now{npos};    // this scene's part authored the same way, or npos
    };
    std::vector<SavedPart> saved;
    // Per part of this scene: the saved part authored the same way (npos for
    // one new or changed), whether it comes back as it was saved, and if not,
    // why -- and whether that is because its cells are not the saved ones.
    std::vector<std::size_t> saved_of;
    std::vector<char> carried, cells_differ;
    std::vector<std::string> why;
    // Per part of this scene, where its cells and bonds begin.
    std::vector<std::uint32_t> node_begin_now, bond_begin_now;
    // Each saved body's part, by the body's name (npos for one whose cells are
    // not all of one part), and the saved bodies of each saved part.
    std::set<std::string> precise_carried;
    std::unordered_map<std::string, std::size_t> part_of_body;
    std::vector<std::vector<std::string>> bodies_of;
    // The saved parts in the order their cells and bonds begin, for finding
    // the part a saved cell or bond is in.
    std::vector<std::pair<std::uint32_t, std::size_t>> by_node, by_bond;

    [[nodiscard]] std::size_t partOfNode(std::uint32_t k) const {
        auto it = std::upper_bound(by_node.begin(), by_node.end(), k,
                                   [](std::uint32_t v, const auto &entry) { return v < entry.first; });
        if (it == by_node.begin()) return npos;
        const std::size_t p = std::prev(it)->second;
        return k < saved[p].node_end ? p : npos;
    }
    [[nodiscard]] std::size_t partOfBond(std::uint32_t k) const {
        auto it = std::upper_bound(by_bond.begin(), by_bond.end(), k,
                                   [](std::uint32_t v, const auto &entry) { return v < entry.first; });
        if (it == by_bond.begin()) return npos;
        const std::size_t p = std::prev(it)->second;
        return k < saved[p].bond_end ? p : npos;
    }
    [[nodiscard]] bool partBack(std::size_t p) const {
        return p != npos && saved[p].now != npos && carried[saved[p].now] != 0;
    }
    // Whether a saved body comes back as it was saved.
    [[nodiscard]] bool carries(const std::string &body) const {
        if (precise_carried.count(body)) return true;
        const auto found = part_of_body.find(body);
        return found != part_of_body.end() && partBack(found->second);
    }
    // This scene's number for a saved cell or bond of a part that comes back:
    // its number in its own part, from where that part now begins. None for
    // one that does not come back.
    [[nodiscard]] std::uint32_t node(std::uint32_t k) const {
        const std::size_t p = partOfNode(k);
        if (!partBack(p)) return none;
        return k - saved[p].node_begin + node_begin_now[saved[p].now];
    }
    [[nodiscard]] std::uint32_t bond(std::uint32_t k) const {
        const std::size_t p = partOfBond(k);
        if (!partBack(p)) return none;
        return k - saved[p].bond_begin + bond_begin_now[saved[p].now];
    }
};

// A joint's kind in the room's words, for saying why a thing is not carried.
std::string jointWord(const std::string &kind) {
    if (kind == "hinge") return "pin";
    if (kind == "slider") return "slide";
    if (kind == "link") return "rope";
    if (kind == "drum") return "drum's rope";
    if (kind == "elastic") return "spring";
    return kind;
}

// Which of a saved world's things come back as they were saved in a scene that
// has changed since (CarryPlan). A part comes back when this scene authors it
// exactly as the saved one was authored and builds it the same cells; and it
// comes back whole or not at all -- its pieces, its dent and its cuts are all
// of its cells. Then, since a thing on a joint is made again only with it: a
// part is not carried when it holds on to anything by a joint that does not
// come back -- the host no longer declares it the same way, or its other end
// is not carried -- or when the host is about to declare something new on it.
// Scenery never moves, so it is carried all the same; and a saved thing whose
// name the scene now gives something new is not carried either, since a room
// has one of each name.
CarryPlan planCarry(const nlohmann::json &doc, const std::vector<PartPrint> &now, const std::string &settings,
                    const LiveCarry &carry) {
    CarryPlan plan;
    const std::size_t count = now.size();
    plan.saved_of.assign(count, CarryPlan::npos);
    plan.carried.assign(count, 0);
    plan.cells_differ.assign(count, 0);
    plan.why.assign(count, std::string{});
    for (const PartPrint &part : now) {
        plan.node_begin_now.push_back(part.node_begin);
        plan.bond_begin_now.push_back(part.bond_begin);
    }
    if (!doc.contains("parts") || !doc.at("parts").is_array() || count == 0) {
        plan.why_not = "it does not say what its things were, so what the room left alone cannot be told from what "
                       "it changed";
        return plan;
    }
    for (const nlohmann::json &p : doc.at("parts")) {
        CarryPlan::SavedPart part;
        part.node_begin = p.at("nodes").at(0).get<std::uint32_t>();
        part.node_end = p.at("nodes").at(1).get<std::uint32_t>();
        part.bond_begin = p.at("bonds").at(0).get<std::uint32_t>();
        part.bond_end = p.at("bonds").at(1).get<std::uint32_t>();
        part.cells = p.value("cells", std::string{});
        part.definition = p.value("definition", std::string{});
        part.heat = p.value("heat", std::string{});
        part.bodies = p.value("bodies", std::vector<std::string>{});
        plan.saved.push_back(std::move(part));
    }
    plan.bodies_of.assign(plan.saved.size(), {});
    for (std::size_t s = 0; s < plan.saved.size(); ++s) {
        if (plan.saved[s].node_end > plan.saved[s].node_begin) plan.by_node.emplace_back(plan.saved[s].node_begin, s);
        if (plan.saved[s].bond_end > plan.saved[s].bond_begin) plan.by_bond.emplace_back(plan.saved[s].bond_begin, s);
    }
    std::sort(plan.by_node.begin(), plan.by_node.end());
    std::sort(plan.by_bond.begin(), plan.by_bond.end());
    // Each part of this scene is the saved part authored exactly the same way.
    std::unordered_map<std::string, std::size_t> by_definition;
    for (std::size_t s = 0; s < plan.saved.size(); ++s) by_definition.emplace(plan.saved[s].definition, s);
    for (std::size_t g = 0; g < count; ++g) {
        const auto found = by_definition.find(now[g].definition);
        if (found == by_definition.end() || plan.saved[found->second].now != CarryPlan::npos) continue;
        plan.saved_of[g] = found->second;
        plan.saved[found->second].now = g;
    }
    // Each saved body's part, from its cells: all of one part, which no bond
    // crosses, or it cannot be carried.
    for (const nlohmann::json &b : doc.at("bodies")) {
        const std::string name = b.at("name").get<std::string>();
        const std::vector<std::uint32_t> cells = unpackedArray<std::uint32_t>(b, "nodes_b64");
        std::size_t part = cells.empty() ? CarryPlan::npos : plan.partOfNode(cells.front());
        for (const std::uint32_t k : cells)
            if (plan.partOfNode(k) != part) {
                if (part != CarryPlan::npos && plan.saved[part].now != CarryPlan::npos)
                    plan.why[plan.saved[part].now] = "the " + name + "'s cells are not all of one thing";
                part = CarryPlan::npos;
                break;
            }
        plan.part_of_body[name] = part;
        if (part != CarryPlan::npos) plan.bodies_of[part].push_back(name);
    }
    const std::string settings_then = doc.value("lattice", std::string{});
    if (settings_then != settings) {
        plan.why_not = settings_then.empty()
                           ? "it does not say how its cells were laid out, so none of them can be found again"
                           : "the room lays its cells out another way now (" + settings_then + " then, " + settings +
                                 " now), so no thing's cells are the ones it was saved with";
        return plan;
    }
    plan.exact = true;
    for (std::size_t g = 0; g < count; ++g) {
        const std::size_t s = plan.saved_of[g];
        if (s == CarryPlan::npos || !plan.why[g].empty()) continue;
        const CarryPlan::SavedPart &part = plan.saved[s];
        if (now[g].cells.empty() || part.cells != now[g].cells) {
            plan.why[g] = "its cells are not the ones it was saved with (" +
                          (part.cells.empty() ? std::string("none said") : part.cells) + " then, " +
                          (now[g].cells.empty() ? std::string("not one run") : now[g].cells) + " now)";
            plan.cells_differ[g] = 1;
            continue;
        }
        plan.carried[g] = 1;
    }

    std::unordered_map<std::string, std::size_t> part_now_of_name;
    for (std::size_t g = 0; g < count; ++g)
        for (const std::string &name : now[g].bodies) part_now_of_name.emplace(name, g);
    const auto partNowOf = [&](const std::string &body) {
        const auto found = plan.part_of_body.find(body);
        return found == plan.part_of_body.end() || found->second == CarryPlan::npos ? CarryPlan::npos
                                                                                    : plan.saved[found->second].now;
    };
    const auto uncarry = [&](std::size_t g, const std::string &why, bool scenery_too) {
        if (g == CarryPlan::npos || plan.carried[g] == 0 || (now[g].anchored && !scenery_too)) return false;
        plan.carried[g] = 0;
        plan.why[g] = why;
        return true;
    };
    for (const std::string &name : carry.declared_anew)
        if (const auto found = part_now_of_name.find(name); found != part_now_of_name.end())
            uncarry(found->second, "the room gave it a new pin, edge or point, written where it was made", false);
    struct Held {
        unsigned id{};
        std::string a, b, kind;
    };
    std::vector<Held> held;
    for (const nlohmann::json &j : doc.value("joints", nlohmann::json::array()))
        if (j.value("attached", false))
            held.push_back({j.at("id").get<unsigned>(), j.value("a", std::string{}), j.value("b", std::string{}),
                            j.value("kind", std::string{"hinge"})});
    for (bool again = true; again;) {
        again = false;
        for (const Held &j : held) {
            const bool declared = carry.joints.count(j.id) != 0;
            if (declared && plan.carries(j.a) && plan.carries(j.b)) continue;
            const std::string kind = jointWord(j.kind);
            for (const auto &[end, other] : {std::pair{j.a, j.b}, std::pair{j.b, j.a}}) {
                const std::string why = declared ? "it is on a " + kind + " to the " + other +
                                                       ", which did not come back as it was"
                                                 : "it was on a " + kind + " the room changed or took away";
                again = uncarry(partNowOf(end), why, false) || again;
            }
        }
        // A thing this scene makes as it has it, under a name a saved thing
        // that comes back already has: the saved thing is not carried.
        std::set<std::string> fresh_names;
        for (std::size_t g = 0; g < count; ++g)
            if (plan.carried[g] == 0 && !now[g].bodies.empty()) fresh_names.insert(now[g].bodies.front());
        for (const auto &[name, part] : plan.part_of_body)
            if (plan.partBack(part) && fresh_names.count(name) != 0 && now[plan.saved[part].now].bodies.front() != name)
                again = uncarry(plan.saved[part].now, "the room has made something else called " + name, true) || again;
    }
    return plan;
}

// A parcel of matter as a saved world writes it: each substance's mass, and
// its one internal energy, exactly.
nlohmann::json savedParcel(const thermo::Parcel &parcel) {
    return {{"kg_b64", packedArray(parcel.kg)}, {"internal_energy_j", savedNumber(parcel.internal_energy_j)}};
}

thermo::Parcel parcelFrom(const nlohmann::json &j) {
    thermo::Parcel parcel;
    parcel.kg = unpackedArray<double>(j, "kg_b64");
    parcel.internal_energy_j = numberFrom(j.at("internal_energy_j"));
    return parcel;
}

// What the thermal network holds for one body, whole (thermo::Lump): its matter
// and its heat zone by zone, what it held when it joined and the hottest each
// zone has been -- what char and what pyrolysis took are decided by those. Its
// gas region by name, since regions are numbered as they are declared.
nlohmann::json savedLump(const thermo::Lump &l, const thermo::ThermoState &state) {
    const bool in_region = l.environment >= 0 && static_cast<std::size_t>(l.environment) < state.regions.size();
    return {{"body", l.body},
            {"material", l.material},
            {"surface", savedParcel(l.surface)},
            {"core", savedParcel(l.core)},
            {"layer_depth_m", savedNumber(l.layer_depth_m)},
            {"layer_fuel_kg", savedNumber(l.layer_fuel_kg)},
            {"area_m2", savedNumber(l.area_m2)},
            {"exposed_area_m2", savedNumber(l.exposed_area_m2)},
            {"volume_m3", savedNumber(l.volume_m3)},
            {"emissivity", savedNumber(l.emissivity)},
            {"conductivity_w_m_k", savedNumber(l.conductivity_w_m_k)},
            {"core_conductance_w_k", savedNumber(l.core_conductance_w_k)},
            {"declared", l.declared},
            {"anchored", l.anchored},
            {"environment", in_region ? state.regions[static_cast<std::size_t>(l.environment)].name : std::string{}},
            {"mirrored_mass_kg", savedNumber(l.mirrored_mass_kg)},
            {"initial_kg_b64", packedArray(l.initial_kg)},
            {"peak_surface_k", savedNumber(l.peak_surface_k)},
            {"peak_core_k", savedNumber(l.peak_core_k)},
            {"heat_release_w", savedNumber(l.heat_release_w)},
            {"fuel_use_kg_s", savedNumber(l.fuel_use_kg_s)},
            {"heater_w", savedNumber(l.heater_w)},
            {"gained_w", savedNumber(l.gained_w)},
            {"lost_w", savedNumber(l.lost_w)},
            {"layer_melt_kg", savedNumber(l.layer_melt_kg)},
            {"melt_kg_s", savedNumber(l.melt_kg_s)},
            {"meltwater_kg", savedNumber(l.meltwater_kg)},
            {"parked", l.parked}};
}

// What to add to each kilogram of each substance's energy to bring a saved
// world's matter across to this model at the same temperature. A world saved
// before the model said which version it was is version 1, whose ice had a
// reference energy of 0: version 2 sets it against liquid water's so that
// melting takes the latent heat (thermo/Thermochemistry.cpp). Empty when
// nothing changed.
std::vector<double> referenceShift(const nlohmann::json &heat, const thermo::Model &model) {
    const std::string version =
        heat.contains("model") && heat.at("model").is_object() ? heat.at("model").value("version", std::string{"1"})
                                                                : std::string{"1"};
    if (version != "1" || model.id != "banjo-demonstration" || model.version != "2" || !model.has("ice"))
        return {};
    std::vector<double> shift(model.size(), 0.0);
    const std::size_t ice = model.index("ice");
    shift[ice] = model[ice].reference_energy_j_kg;   // less version 1's 0
    return shift;
}

// The energy that shift adds to a parcel.
double shiftOf(const thermo::Parcel &p, const std::vector<double> &shift) {
    double added = 0.0;
    for (std::size_t i = 0; i < shift.size() && i < p.kg.size(); ++i) added += p.kg[i] * shift[i];
    return added;
}

thermo::Lump lumpFrom(const nlohmann::json &j, const thermo::ThermoState &state, std::size_t substances,
                      const thermo::Model &model, const std::vector<double> &shift) {
    thermo::Lump l;
    l.body = j.at("body").get<std::string>();
    l.material = j.value("material", std::string{});
    l.surface = parcelFrom(j.at("surface"));
    l.core = parcelFrom(j.at("core"));
    l.initial_kg = unpackedArray<double>(j, "initial_kg_b64");
    if (l.surface.kg.size() != substances || l.core.kg.size() != substances || l.initial_kg.size() != substances)
        throw std::invalid_argument("the " + l.body + "'s heat is not one number a substance");
    l.surface.internal_energy_j += shiftOf(l.surface, shift);
    l.core.internal_energy_j += shiftOf(l.core, shift);
    l.layer_depth_m = numberFrom(j.at("layer_depth_m"));
    l.layer_fuel_kg = numberFrom(j.at("layer_fuel_kg"));
    // Saved before melting was modelled: the melting front keeps what the
    // layer holds now.
    if (j.contains("layer_melt_kg")) {
        l.layer_melt_kg = numberFrom(j.at("layer_melt_kg"));
    } else {
        for (const thermo::Transition &transition : model.transitions)
            if (transition.solid < l.surface.kg.size()) l.layer_melt_kg += l.surface.kg[transition.solid];
    }
    l.melt_kg_s = j.contains("melt_kg_s") ? numberFrom(j.at("melt_kg_s")) : 0.0;
    l.meltwater_kg = j.contains("meltwater_kg") ? numberFrom(j.at("meltwater_kg")) : 0.0;
    l.area_m2 = numberFrom(j.at("area_m2"));
    l.exposed_area_m2 = numberFrom(j.at("exposed_area_m2"));
    l.volume_m3 = numberFrom(j.at("volume_m3"));
    l.emissivity = numberFrom(j.at("emissivity"));
    l.conductivity_w_m_k = numberFrom(j.at("conductivity_w_m_k"));
    l.core_conductance_w_k = numberFrom(j.at("core_conductance_w_k"));
    l.declared = j.value("declared", false);
    l.anchored = j.value("anchored", false);
    l.environment = -1;
    const std::string region = j.value("environment", std::string{});
    for (std::size_t i = 0; i < state.regions.size() && !region.empty(); ++i)
        if (state.regions[i].name == region) l.environment = static_cast<int>(i);
    l.mirrored_mass_kg = numberFrom(j.at("mirrored_mass_kg"));
    l.peak_surface_k = numberFrom(j.at("peak_surface_k"));
    l.peak_core_k = numberFrom(j.at("peak_core_k"));
    l.heat_release_w = numberFrom(j.at("heat_release_w"));
    l.fuel_use_kg_s = numberFrom(j.at("fuel_use_kg_s"));
    l.heater_w = numberFrom(j.at("heater_w"));
    l.gained_w = numberFrom(j.at("gained_w"));
    l.lost_w = numberFrom(j.at("lost_w"));
    l.parked = j.value("parked", false);
    return l;
}

// Global thermal declarations are a compatibility boundary for carrying a
// running network into an edited scene. Body-local declarations already have
// per-component fingerprints in CarryPlan.
nlohmann::json thermalSettings(const std::string &scene) {
    if (scene.empty()) return nlohmann::json::object();
    const auto doc = nlohmann::json::parse(scene);
    return doc.contains("thermo") && !doc.at("thermo").is_null()
        ? doc.at("thermo") : nlohmann::json::object();
}

// Versioned complete thermal state for reopening the identical world.
// Doubles use the same lossless representation as mechanical snapshots.
nlohmann::json savedHeaterDeclaration(const thermo::HeaterDeclaration &v) {
    return {{"target", v.target},
            {"label", v.label},
            {"power_w", savedNumber(v.power_w)},
            {"start_s", savedNumber(v.start_s)},
            {"seconds", savedNumber(v.seconds)}};
}
thermo::HeaterDeclaration readHeaterDeclaration(const nlohmann::json &j) {
    thermo::HeaterDeclaration v;
    v.target = j.at("target").get<std::string>();
    v.label = j.at("label").get<std::string>();
    v.power_w = numberFrom(j.at("power_w"));
    v.start_s = numberFrom(j.at("start_s"));
    v.seconds = numberFrom(j.at("seconds"));
    return v;
}
nlohmann::json savedPistonBoundary(const thermo::PistonBoundary &v) {
    return {{"body", v.body},
            {"container", v.container},
            {"axis", savedVec(v.axis)},
            {"base_m", savedVec(v.base_m)},
            {"pushed_force_n", savedVec(v.pushed_force_n)},
            {"area_m2", savedNumber(v.area_m2)},
            {"stroke_m", savedNumber(v.stroke_m)},
            {"base_volume_m3", savedNumber(v.base_volume_m3)},
            {"minimum_volume_m3", savedNumber(v.minimum_volume_m3)},
            {"pushed_pressure_pa", savedNumber(v.pushed_pressure_pa)},
            {"work_to_bodies_j", savedNumber(v.work_to_bodies_j)},
            {"work_to_atmosphere_j", savedNumber(v.work_to_atmosphere_j)}};
}
thermo::PistonBoundary readPistonBoundary(const nlohmann::json &j) {
    thermo::PistonBoundary v;
    v.body = j.at("body").get<std::string>();
    v.container = j.at("container").get<std::string>();
    v.axis = vecFrom(j.at("axis"));
    v.base_m = vecFrom(j.at("base_m"));
    v.pushed_force_n = vecFrom(j.at("pushed_force_n"));
    v.area_m2 = numberFrom(j.at("area_m2"));
    v.stroke_m = numberFrom(j.at("stroke_m"));
    v.base_volume_m3 = numberFrom(j.at("base_volume_m3"));
    v.minimum_volume_m3 = numberFrom(j.at("minimum_volume_m3"));
    v.pushed_pressure_pa = numberFrom(j.at("pushed_pressure_pa"));
    v.work_to_bodies_j = numberFrom(j.at("work_to_bodies_j"));
    v.work_to_atmosphere_j = numberFrom(j.at("work_to_atmosphere_j"));
    return v;
}
nlohmann::json savedContact(const thermo::Contact &v) {
    return {{"a", v.a},
            {"b", v.b},
            {"area_m2", savedNumber(v.area_m2)},
            {"conductance_w_k", savedNumber(v.conductance_w_k)}};
}
thermo::Contact readContact(const nlohmann::json &j) {
    thermo::Contact v;
    v.a = j.at("a").get<std::size_t>();
    v.b = j.at("b").get<std::size_t>();
    v.area_m2 = numberFrom(j.at("area_m2"));
    v.conductance_w_k = numberFrom(j.at("conductance_w_k"));
    return v;
}
nlohmann::json savedSight(const thermo::Sight &v) {
    return {{"a", v.a},
            {"b", v.b},
            {"exchange_area_m2", savedNumber(v.exchange_area_m2)},
            {"emissivity", savedNumber(v.emissivity)}};
}
thermo::Sight readSight(const nlohmann::json &j) {
    thermo::Sight v;
    v.a = j.at("a").get<std::size_t>();
    v.b = j.at("b").get<std::size_t>();
    v.exchange_area_m2 = numberFrom(j.at("exchange_area_m2"));
    v.emissivity = numberFrom(j.at("emissivity"));
    return v;
}
nlohmann::json savedLedger(const thermo::Ledger &v) {
    return {{"reference_j", savedNumber(v.reference_j)},
            {"sensible_j", savedNumber(v.sensible_j)},
            {"mass_kg", savedNumber(v.mass_kg)},
            {"initial_j", savedNumber(v.initial_j)},
            {"initial_mass_kg", savedNumber(v.initial_mass_kg)},
            {"heater_in_j", savedNumber(v.heater_in_j)},
            {"heat_to_surroundings_j", savedNumber(v.heat_to_surroundings_j)},
            {"matter_in_j", savedNumber(v.matter_in_j)},
            {"matter_in_kg", savedNumber(v.matter_in_kg)},
            {"matter_out_j", savedNumber(v.matter_out_j)},
            {"matter_out_kg", savedNumber(v.matter_out_kg)},
            {"joined_j", savedNumber(v.joined_j)},
            {"joined_kg", savedNumber(v.joined_kg)},
            {"left_j", savedNumber(v.left_j)},
            {"left_kg", savedNumber(v.left_kg)},
            {"work_to_bodies_j", savedNumber(v.work_to_bodies_j)},
            {"work_to_atmosphere_j", savedNumber(v.work_to_atmosphere_j)},
            {"mechanical_in_j", savedNumber(v.mechanical_in_j)},
            {"numerical_j", savedNumber(v.numerical_j)},
            {"out_of_range_steps", v.out_of_range_steps}};
}
thermo::Ledger readLedger(const nlohmann::json &j) {
    thermo::Ledger v;
    v.reference_j = numberFrom(j.at("reference_j"));
    v.sensible_j = numberFrom(j.at("sensible_j"));
    v.mass_kg = numberFrom(j.at("mass_kg"));
    v.initial_j = numberFrom(j.at("initial_j"));
    v.initial_mass_kg = numberFrom(j.at("initial_mass_kg"));
    v.heater_in_j = numberFrom(j.at("heater_in_j"));
    v.heat_to_surroundings_j = numberFrom(j.at("heat_to_surroundings_j"));
    v.matter_in_j = numberFrom(j.at("matter_in_j"));
    v.matter_in_kg = numberFrom(j.at("matter_in_kg"));
    v.matter_out_j = numberFrom(j.at("matter_out_j"));
    v.matter_out_kg = numberFrom(j.at("matter_out_kg"));
    v.joined_j = numberFrom(j.at("joined_j"));
    v.joined_kg = numberFrom(j.at("joined_kg"));
    v.left_j = numberFrom(j.at("left_j"));
    v.left_kg = numberFrom(j.at("left_kg"));
    v.work_to_bodies_j = numberFrom(j.at("work_to_bodies_j"));
    v.work_to_atmosphere_j = numberFrom(j.at("work_to_atmosphere_j"));
    v.mechanical_in_j = numberFrom(j.at("mechanical_in_j"));
    v.numerical_j = numberFrom(j.at("numerical_j"));
    v.out_of_range_steps = j.at("out_of_range_steps").get<unsigned long long>();
    return v;
}

nlohmann::json savedThermoState(const thermo::ThermoState &v) {
    nlohmann::json j = {{"schema", "banjo.thermal-state.v1"},
        {"time_s", savedNumber(v.time_s)}, {"next_heater", v.next_heater}, {"opened", v.opened},
        {"ledger", savedLedger(v.ledger)}, {"sky_fraction", packedArray(v.sky_fraction)},
        {"floor_conductance_w_k", packedArray(v.floor_conductance_w_k)}};
    for (const char *key : {"regions", "heaters", "contacts", "sights"}) j[key] = nlohmann::json::array();
    for (const auto &r : v.regions) {
        nlohmann::json region = {{"name", r.name}, {"gas", savedParcel(r.gas)},
            {"volume_m3", savedNumber(r.volume_m3)}, {"wall_conductance_w_k", savedNumber(r.wall_conductance_w_k)},
            {"vent_area_m2", savedNumber(r.vent_area_m2)}, {"vent_open", r.vent_open},
            {"heater_w", savedNumber(r.heater_w)}, {"wall_loss_w", savedNumber(r.wall_loss_w)},
            {"vent_flow_kg_s", savedNumber(r.vent_flow_kg_s)}};
        if (r.piston) region["piston"] = savedPistonBoundary(*r.piston);
        j["regions"].push_back(std::move(region));
    }
    for (const auto &h : v.heaters) j["heaters"].push_back({{"id", h.id}, {"what", savedHeaterDeclaration(h.what)}});
    for (const auto &c : v.contacts) j["contacts"].push_back(savedContact(c));
    for (const auto &c : v.sights) j["sights"].push_back(savedSight(c));
    return j;
}

thermo::ThermoState readThermoState(const nlohmann::json &heat, const thermo::Model &model) {
    const std::size_t substances = model.size();
    const auto &j = heat.at("network");
    if (j.at("schema") != "banjo.thermal-state.v1" || heat.at("substances").get<std::size_t>() != substances)
        throw std::invalid_argument("incompatible saved thermal network");
    const std::vector<double> shift = referenceShift(heat, model);
    thermo::ThermoState v;
    v.time_s = numberFrom(j.at("time_s"));
    v.next_heater = j.at("next_heater").get<unsigned>();
    v.opened = j.at("opened").get<bool>();
    v.ledger = readLedger(j.at("ledger"));
    v.sky_fraction = unpackedArray<double>(j, "sky_fraction");
    v.floor_conductance_w_k = unpackedArray<double>(j, "floor_conductance_w_k");
    std::set<std::string> regions, bodies;
    for (const auto &r : j.at("regions")) {
        thermo::GasRegion region;
        region.name = r.at("name").get<std::string>();
        region.gas = parcelFrom(r.at("gas"));
        if (!regions.insert(region.name).second || region.gas.kg.size() != substances)
            throw std::invalid_argument("invalid saved gas region");
        region.gas.internal_energy_j += shiftOf(region.gas, shift);
        region.volume_m3 = numberFrom(r.at("volume_m3"));
        region.wall_conductance_w_k = numberFrom(r.at("wall_conductance_w_k"));
        region.vent_area_m2 = numberFrom(r.at("vent_area_m2"));
        region.vent_open = r.at("vent_open").get<bool>();
        region.heater_w = numberFrom(r.at("heater_w"));
        region.wall_loss_w = numberFrom(r.at("wall_loss_w"));
        region.vent_flow_kg_s = numberFrom(r.at("vent_flow_kg_s"));
        if (r.contains("piston")) region.piston = readPistonBoundary(r.at("piston"));
        v.regions.push_back(std::move(region));
    }
    for (const auto &l : heat.at("lumps")) {
        const auto environment = l.value("environment", std::string{});
        if (!environment.empty() && !regions.count(environment))
            throw std::invalid_argument("saved thermal body has no gas region");
        auto lump = lumpFrom(l, v, substances, model, shift);
        if (!bodies.insert(lump.body).second) throw std::invalid_argument("duplicate saved thermal body");
        v.lumps.push_back(std::move(lump));
    }
    // Brought across to this model's reference energies, the network holds
    // more by exactly the shift; its ledger is re-based by the same amount, so
    // what was unaccounted before is unaccounted still -- no more, no less.
    if (!shift.empty()) {
        double added = 0.0;
        for (const thermo::Lump &lump : v.lumps) added += shiftOf(lump.surface, shift) + shiftOf(lump.core, shift);
        for (const thermo::GasRegion &region : v.regions) added += shiftOf(region.gas, shift);
        v.ledger.initial_j += added;
    }
    std::set<unsigned> ids;
    for (const auto &h : j.at("heaters")) {
        thermo::Heater heater{h.at("id").get<unsigned>(), readHeaterDeclaration(h.at("what"))};
        if (!ids.insert(heater.id).second || heater.id >= v.next_heater ||
            (!bodies.count(heater.what.target) && !regions.count(heater.what.target)))
            throw std::invalid_argument("invalid saved heater reference");
        v.heaters.push_back(std::move(heater));
    }
    for (const auto &c : j.at("contacts")) {
        auto value = readContact(c);
        if (value.a >= v.lumps.size() || value.b >= v.lumps.size()) throw std::invalid_argument("invalid saved heat contact");
        v.contacts.push_back(value);
    }
    for (const auto &c : j.at("sights")) {
        auto value = readSight(c);
        if (value.a >= v.lumps.size() || value.b >= v.lumps.size()) throw std::invalid_argument("invalid saved heat sight");
        v.sights.push_back(value);
    }
    if (v.sky_fraction.size() != v.lumps.size() || v.floor_conductance_w_k.size() != v.lumps.size())
        throw std::invalid_argument("invalid saved thermal boundary arrays");
    return v;
}

}  // namespace

void LiveWorld::Impl::settleJointedContacts() {
    std::set<std::pair<MatterBodyId, MatterBodyId>> now;
    for (const SceneJoint &joint : joints) {
        if (!joint.attached || joint.rigid == 0) continue;
        if (joint.kind != JoltWorld::JointKind::Hinge && joint.kind != JoltWorld::JointKind::Slider &&
            joint.kind != JoltWorld::JointKind::Fixing)
            continue;
        const auto a = index_of.find(joint.a), b = index_of.find(joint.b);
        if (a == index_of.end() || b == index_of.end()) continue;
        if (!isPrecise(a->second) || !isPrecise(b->second)) continue;
        if (!inWorld(a->second) || !inWorld(b->second)) continue;
        const auto pair = std::minmax(body_of[a->second], body_of[b->second]);
        now.insert({pair.first, pair.second});
    }
    for (const auto &pair : held_by_joints)
        if (!now.count(pair) && world->contains(pair.first) && world->contains(pair.second))
            world->setPairContactOwner(pair.first, pair.second, PairContactOwner::Jolt);
    for (const auto &pair : now)
        if (!held_by_joints.count(pair))
            world->setPairContactOwner(pair.first, pair.second, PairContactOwner::External);
    held_by_joints = std::move(now);
}

LiveWorld::LiveWorld() : impl_(std::make_unique<Impl>()) {}
LiveWorld::~LiveWorld() = default;

std::unique_ptr<LiveWorld> LiveWorld::open(const TileImpactRequest &request) { return openFrom(request, nullptr); }

std::unique_ptr<LiveWorld> LiveWorld::openFrom(const TileImpactRequest &request, const Saved *saved,
                                               const LiveCarry *carry) {
    std::unique_ptr<LiveWorld> live(new LiveWorld());
    Impl &impl = *live->impl_;
    impl.request = request;
    // Ledges belong to the single-tile lane, which drops one plate across two
    // of them. A scene of objects stands on the ground, and leaving the bridge
    // layout in place puts a support plane at the ledge height through the
    // middle of everything -- a pane resting on the floor then reads as 140 mm
    // buried and every attempt to break it is refused as too deeply penetrated.
    if (!impl.request.bodies.empty()) impl.request.layout = SceneLayout::Flat;
    for (auto &body : readPreciseRigidScene(request.precise_rigid_scene_json))
        impl.precise_bodies.emplace(body.name, std::move(body));
    if (!impl.precise_bodies.empty()) {
        // Exact bodies share the room with everything made of cells, and with
        // its ground and water. A breakable body they strike is judged against
        // their real material; a break that would need them INSIDE the lattice
        // run is declined and said so (judgeStep), never run without them. What
        // they cannot share yet is heat -- the thermal model has no exact bodies
        // -- and loose cells.
        if (request.bodies.empty() || !request.thermo_scene_json.empty() || request.loose_cells)
            throw std::invalid_argument("precise-rigid rooms need at least one lattice body and no thermal or loose-cell declarations");
        for (const SceneBody &body : request.bodies)
            if (impl.precise_bodies.count(body.name) ||
                (!body.join.empty() && impl.precise_bodies.count(body.join)))
                throw std::invalid_argument("a precise rigid body cannot share its name with a lattice body");
        // Joints are kept: they hold bodies, not cells, and are rebuilt from the
        // save like any others -- and so are the motors on them and the
        // controllers that work those, which name a pin, a store and a motor and
        // never a cell (a cart driving itself, tests/cart_drive_tests.cpp).
        // What works on cells is not.
        if (saved) {
            for (const char *key : {"blades", "tool_points"})
                if (saved->doc.contains(key) && !saved->doc[key].empty())
                    throw std::invalid_argument("precise-rigid carry cannot preserve an unsupported attached mechanism");
        }
    }
    auto lattice_request = impl.request;
    lattice_request.precise_rigid_scene_json.clear();
    impl.setup = buildTileImpactSetup(lattice_request);
    TileImpactSetup &setup = *impl.setup;
    const TileImpactRequest &r = impl.request;
    // Terrain and water. With ground that is not flat, the flat floor the
    // setup assumes goes under all of it -- to the rock's own floor -- where it
    // is a safety net and not a surface: the floor under a lattice run and the
    // plane heat conducts into both follow it there.
    //
    // A saved world's water goes back as the scene's own carried water
    // ("water": {"state": ...}), which is how a world opened again after the
    // chat keeps its water: the same water over whatever ground the scene's
    // edits leave. Water that will not go back -- saved on another grid, say --
    // is said, and the scene's own is used.
    //
    // Carried into a scene that has changed, the water is the scene's own: a
    // host carries the running room's water into the scene it hands over
    // whenever the ground under it is the same (server.with_water), and ground
    // that has changed is new water.
    const bool carrying = saved != nullptr && carry != nullptr;
    std::string water_note;
    if (!r.environment_scene_json.empty()) {
        const bool carry_ground = saved != nullptr && (!carrying || carry->ground) && saved->doc.contains("ground");
        const bool carry_water = saved != nullptr && !carrying && saved->doc.contains("water") &&
                                 saved->doc.at("water").is_object();
        try {
            std::string scene_text = r.environment_scene_json;
            if (carry_water) {
                nlohmann::json scene = nlohmann::json::parse(scene_text);
                scene["water"]["state"] = saved->doc.at("water");
                scene_text = scene.dump();
            }
            impl.environment = terrain::Environment::fromScene(scene_text,
                carry_ground ? saved->doc.at("ground").dump() : std::string{});
        } catch (const std::exception &error) {
            // A corrupt ground continuation must never become replayed terrain.
            if (carry_ground) throw;
            if (!carry_water) throw;
            water_note = std::string("the water: it could not be put back (") + error.what() +
                         "), so it is as the room declares it";
            impl.environment = terrain::Environment::fromScene(r.environment_scene_json);
        }
        if (impl.environment) setup.ground_y = std::min(setup.ground_y, impl.environment->floorY());
    }

    // The setup leaves its matter in the frame of the scene's own origin. The
    // batch lane only ever sees world coordinates because its lattice phase
    // writes a state back before the handoff, and that write-back is where the
    // origin is added. Nothing has been simulated here, so do the same round
    // trip with no steps in it: build a state and write it straight back, which
    // moves the cells into world coordinates and changes nothing else.
    {
        const LatticeState rest = buildLatticeState(setup.matter, setup.schedule, setup.origin);
        writeBackLatticeState(rest, setup.schedule, setup.matter);
    }

    impl.cell_offset_m.assign(setup.matter.nodes.size(), Vec3{});
    impl.part_cells.assign(setup.part_bodies.size(), 0);
    for (const std::uint32_t part : setup.part_of_node)
        if (part < impl.part_cells.size()) ++impl.part_cells[part];
    impl.plastic_extension_m.assign(setup.asset.bonds.size(), 0.0);
    impl.plastic_strain_m.assign(setup.asset.bonds.size(), 0.0);

    // The lattice this scene builds, in a few numbers, which a saved world has
    // to have been taken from.
    const LatticeFingerprint print = fingerprintOf(setup);
    impl.fingerprint_nodes = print.nodes;
    impl.fingerprint_bonds = print.bonds;
    impl.fingerprint_hash = print.hash;
    // And each authored part of it, which a world carried into this scene once
    // it has changed finds its things' cells by.
    impl.part_prints = partPrintsOf(setup, r);
    impl.lattice_settings = latticeSettingsOf(r);
    // Carried into a changed scene: which saved things are still what they
    // were, and where their cells and bonds are numbered now (CarryPlan).
    CarryPlan plan;
    if (carrying) plan = planCarry(saved->doc, impl.part_prints, impl.lattice_settings, *carry);
    if (saved) {
        std::set<std::string> precise_names, saved_names;
        for (const auto &b : saved->doc.at("bodies")) {
            if (!saved_names.insert(b.at("name").get<std::string>()).second)
                throw std::invalid_argument("duplicate saved body name");
            if (b.value("mechanical_model", std::string{}) != "precise-rigid-v1") continue;
            const auto name = b.at("name").get<std::string>();
            const auto found = impl.precise_bodies.find(name);
            if (!precise_names.insert(name).second || found == impl.precise_bodies.end() ||
                b.at("precise_rigid_definition") != nlohmann::json::parse(found->second.definition_json))
                throw std::invalid_argument("saved precise-rigid geometry or material changed; exact state carry refused");
            if (carrying) plan.precise_carried.insert(name);
        }
        if (!carrying && precise_names.size() != impl.precise_bodies.size())
            throw std::invalid_argument("saved precise-rigid body set differs from the scene");
        if (!impl.precise_bodies.empty() && carrying && !plan.exact)
            throw std::invalid_argument("precise-rigid installation requires exact preservation of existing scenery");
    }
    // A saved bond's number in this scene: the same for a world opened whole;
    // for one carried, its number in its own part from where that part begins
    // now -- or none, for a part that does not come back as it was saved.
    const auto bondNow = [&](std::uint32_t k) { return carrying ? plan.bond(k) : k; };
    if (saved != nullptr && (!carrying || plan.exact)) {
        const nlohmann::json &doc = saved->doc;
        if (!carrying) {
            const nlohmann::json &was = doc.at("fingerprint");
            const std::size_t was_nodes = was.at("nodes").get<std::size_t>();
            const std::size_t was_bonds = was.at("bonds").get<std::size_t>();
            const std::string was_hash = was.at("hash").get<std::string>();
            if (was_nodes != print.nodes || was_bonds != print.bonds || was_hash != print.hash)
                throw SavedWorldMismatch("it was saved from a scene whose cells are not this one's: " +
                                         std::to_string(was_nodes) + " cells and " + std::to_string(was_bonds) +
                                         " bonds (" + was_hash + ") against " + std::to_string(print.nodes) +
                                         " and " + std::to_string(print.bonds) + " (" + print.hash + ")");
        }
        // What a blade severed stays severed, in the scene's own matter where
        // every later run finds it -- before anything reads the bonds.
        for (const std::uint32_t severed : unpackedArray<std::uint32_t>(doc, "dead_bonds_b64")) {
            const std::uint32_t k = bondNow(severed);
            if (carrying && k == CarryPlan::none) continue;
            if (k >= setup.matter.bonds.size())
                throw std::invalid_argument("a severed bond is not one of this scene's");
            ActiveBondState &bond = setup.matter.bonds[k];
            if (!bond.alive) continue;
            bond.alive = false;
            bond.damage = 1.0;
            bond.failure_mode = BondFailureMode::Shear;
        }
        // And the permanent set each bond carries: what a dent is made of.
        const nlohmann::json &set = doc.at("plastic");
        const auto set_bonds = unpackedArray<std::uint32_t>(set, "bonds_b64");
        const auto extension = unpackedArray<double>(set, "extension_b64");
        const auto strain = unpackedArray<double>(set, "strain_b64");
        if (extension.size() != set_bonds.size() || strain.size() != set_bonds.size())
            throw std::invalid_argument("the saved permanent set is not one number a bond");
        for (std::size_t n = 0; n < set_bonds.size(); ++n) {
            const std::uint32_t k = bondNow(set_bonds[n]);
            if (carrying && k == CarryPlan::none) continue;
            if (k >= impl.plastic_extension_m.size())
                throw std::invalid_argument("a bond with a permanent set is not one of this scene's");
            impl.plastic_extension_m[k] = extension[n];
            impl.plastic_strain_m[k] = strain[n];
        }
    }

    // Nothing has been struck, so every part is still one whole component --
    // unless the world is opened again from a saved one, whose bodies are made
    // from their own cells below instead.
    //
    // Carried into a changed scene, only the parts that do not come back as
    // they were saved are made here -- as the scene has them, and numbered
    // after every body the saved world numbered.
    std::vector<FragmentComponent> components;
    if (saved == nullptr || carrying) components = findConnectedComponents(setup.matter);
    if (carrying)
        std::erase_if(components, [&](const FragmentComponent &component) {
            if (component.node_indices.empty() || component.node_indices.front() >= setup.part_of_node.size())
                return false;
            const std::uint32_t part = setup.part_of_node[component.node_indices.front()];
            return part < plan.carried.size() && plan.carried[part] != 0;
        });
    if (saved == nullptr && components.empty()) throw std::runtime_error("a live world needs at least one body");
    MatterBodyId first_fresh = 1000;
    if (carrying && saved->doc.contains("next") && saved->doc.at("next").contains("body"))
        first_fresh = std::max<MatterBodyId>(first_fresh, saved->doc.at("next").at("body").get<MatterBodyId>());

    FragmentBuildResult build = components.empty() ? FragmentBuildResult{} : buildFragmentRepresentations(setup.matter, components, {
        .first_body_id = first_fresh,
        .maximum_rigid_fragments = std::max<std::size_t>(1, components.size()),
        .minimum_nodes_per_rigid_fragment = 1,
        .maximum_collision_points = 192,
        .friction = setup.tile_ground.dynamic_friction,
        .restitution = setup.tile_ground.restitution,
    });

    // Give each whole un-joined body the shape it was authored as, so a tilted
    // ramp collides as a ramp and a ball rolls. This is the batch lane's rule
    // and the same conditions: a join is a union that no primitive describes,
    // and a cone's cell hull is already its true surface.
    std::vector<std::size_t> part_size(setup.part_bodies.size(), 0);
    for (const std::uint32_t part : setup.part_of_node) ++part_size[part];
    std::size_t fragment_index = 0;
    for (const auto &component : components) {
        if (fragment_index >= build.rigid_fragments.size()) break;
        RigidFragmentDescription &fragment = build.rigid_fragments[fragment_index];
        if (fragment.source_node_count != component.node_indices.size()) continue;
        const std::size_t here = fragment_index++;
        if (component.node_indices.empty()) continue;

        LiveBodyPose described{};
        described.name = "piece " + std::to_string(here);
        if (setup.multi_body && !setup.part_of_node.empty()) {
            const std::uint32_t part = setup.part_of_node[component.node_indices.front()];
            bool whole = part_size[part] == component.node_indices.size();
            for (const std::uint32_t node : component.node_indices)
                if (setup.part_of_node[node] != part) { whole = false; break; }
            if (part < setup.part_bodies.size() && !setup.part_bodies[part].empty()) {
                const SceneBody &lead = r.bodies[setup.part_bodies[part].front()];
                described.name = lead.name;
                described.material = materialPresetName(lead.material);
                described.color_rgba = lead.color_rgba;
                for (const std::size_t which : setup.part_bodies[part])
                    if (r.bodies[which].anchored) described.anchored = true;
                fragment.anchored = described.anchored;
                if (whole && setup.part_bodies[part].size() == 1 &&
                    lead.shape != BodyShape::Cone) {
                    fragment.primitive = lead.shape == BodyShape::Sphere
                                             ? FragmentPrimitive::Sphere
                                             : FragmentPrimitive::Box;
                    fragment.primitive_dimensions_m = lead.dimensions_m;
                    rotationQuaternion(lead.rotation_deg, fragment.primitive_rotation_wxyz);
                    if (lead.rotation_deg.x != 0.0 || lead.rotation_deg.y != 0.0 || lead.rotation_deg.z != 0.0)
                        impl.tilt_of[lead.name] = Quat{fragment.primitive_rotation_wxyz[0],
                                                       fragment.primitive_rotation_wxyz[1],
                                                       fragment.primitive_rotation_wxyz[2],
                                                       fragment.primitive_rotation_wxyz[3]};
                    described.shape = lead.shape == BodyShape::Sphere ? "sphere" : "box";
                    described.dimensions_m = lead.dimensions_m;
                }
            }
        }
        // What it would take to break this one. The impedance is the struck
        // body's own material, not the tile's: a glass pin and an oak lane in
        // the same scene do not break at the same speed.
        const MaterialDefinition *definition = &setup.tile_material;
        if (setup.multi_body && !setup.part_of_node.empty()) {
            const std::uint32_t part = setup.part_of_node[component.node_indices.front()];
            if (part < setup.part_definitions.size()) definition = &setup.part_definitions[part];
        }
        impl.limits_of.push_back(fragmentFractureLimits(
            setup.matter, component.node_indices,
            definition->density_kg_m3, definition->young_modulus_pa,
            definition->yield_strength_pa, definition->fracture_energy_j_m2,
            impl.request.cell_size_m));
        impl.impedance_of.push_back(
            acousticImpedance(definition->density_kg_m3, definition->young_modulus_pa));
        // Kept so a piece can say what it weighs. Its cells are its volume, and
        // volume times this is matter somebody can carry away.
        impl.density_of.push_back(definition->density_kg_m3);
        // And what it can take in bending, for the load survey. A beam fails on
        // the tension side, so this is the number that decides a loaded shelf.
        impl.tensile_of.push_back(definition->tensile_strength_pa);
        impl.compressive_of.push_back(definition->compressive_strength_pa);
        if (!setup.part_of_node.empty()) {
            if (impl.material_of_part.size() < setup.part_bodies.size())
                impl.material_of_part.resize(setup.part_bodies.size());
            for (const std::uint32_t node : component.node_indices) {
                const std::uint32_t part = setup.part_of_node[node];
                if (part < impl.material_of_part.size() &&
                    impl.material_of_part[part].empty())
                    impl.material_of_part[part] = described.material;
            }
        }
        // How it meets the floor, from the same material the threshold came
        // from. Without this every body in the scene carried the contact of the
        // scene's default matter and nothing bounced differently from anything
        // else.
        const CombinedContactMaterial against_ground = combineContactMaterials(
            compileContactMaterial(*definition), compileContactMaterial(setup.ground_material));
        fragment.friction = against_ground.dynamic_friction;
        fragment.restitution = against_ground.restitution;
        // Its own share of rolling resistance, NOT combined with the floor's:
        // the world adds the share of whatever it actually rolls on, contact
        // by contact -- the floor, the ground where it is sand or rock, a plank.
        fragment.rolling_resistance = compileContactMaterial(*definition).rolling_resistance;
        impl.nodes_of.emplace_back(component.node_indices.begin(), component.node_indices.end());
        for (const std::uint32_t node : component.node_indices)
            impl.cell_offset_m[node] = setup.matter.nodes[node].position_world_m -
                                       fragment.mass_properties.center_of_mass_world_m;
        impl.next_body_id = std::max(impl.next_body_id, fragment.body_id + 1);
        if (described.shape == "hull")
            described.dimensions_m = cellBounds(impl.nodes_of.back(), impl.cell_offset_m,
                                                r.cell_size_m);
        impl.described.push_back(std::move(described));
        impl.body_of.push_back(fragment.body_id);
    }

    // A saved world's bodies, made again from their own cells (open with a
    // snapshot). Each is built at its saved centre of mass, facing the world's
    // own way, from its cells laid out as its frame had them: so its offsets are
    // the ones it had, and everything kept in its frame -- a dent, a kerf, a
    // joint's point, an edge, a tool's point, the grip -- is where it was on it.
    // It is turned and set moving as it was once it is in the world, below.
    // Under our own body ids, which the rest of the engine keys by.
    //
    // Carried into a changed scene: only the saved bodies of parts that come
    // back as they were saved, each cell under this scene's number for it.
    std::vector<Placement> placements;
    if (saved != nullptr && (!carrying || plan.exact)) {
        const nlohmann::json &doc = saved->doc;
        // What each part is made of, as the scene's bodies say: what the loop
        // above fills in from each whole part.
        if (!setup.part_of_node.empty()) {
            impl.material_of_part.assign(setup.part_bodies.size(), std::string{});
            for (std::size_t part = 0; part < setup.part_bodies.size(); ++part)
                if (!setup.part_bodies[part].empty())
                    impl.material_of_part[part] =
                        materialPresetName(r.bodies[setup.part_bodies[part].front()].material);
        }
        ActiveMatter placed = setup.matter;
        std::vector<char> taken(setup.matter.nodes.size(), 0);
        std::set<std::string> names;
        std::set<MatterBodyId> ids;
        for (const nlohmann::json &b : doc.at("bodies")) {
            if (b.value("mechanical_model", std::string{}) == "precise-rigid-v1") continue;
            LiveBodyPose described{};
            described.name = b.at("name").get<std::string>();
            const std::string name = described.name;
            if (name.empty() || !names.insert(name).second)
                throw std::invalid_argument("two saved bodies are called \"" + name + "\"");
            if (carrying && !plan.carries(name)) continue;
            described.material = b.value("material", std::string{});
            described.shape = b.value("shape", std::string{"hull"});
            described.dimensions_m = vecFrom(b.at("dimensions_m"));
            described.revision = b.value("revision", 0U);
            described.color_rgba = b.value("color_rgba", std::uint32_t{0});
            described.anchored = b.value("anchored", false);
            described.fragment = b.value("fragment", false);
            described.dent_m = numberFrom(b.at("dent_m"));
            described.dent_at_m = vecFrom(b.at("dent_at_m"));
            const MatterBodyId id = b.at("body_id").get<MatterBodyId>();
            if (id < 1000 || !ids.insert(id).second)
                throw std::invalid_argument("the saved " + name + " has a body id that is not its own");
            std::vector<std::uint32_t> nodes = unpackedArray<std::uint32_t>(b, "nodes_b64");
            if (carrying)
                for (std::uint32_t &node : nodes) node = plan.node(node);
            const std::vector<Vec3> offsets = unpackedVecs(b, "offsets_b64");
            if (nodes.empty() || offsets.size() != nodes.size())
                throw std::invalid_argument("the saved " + name + " has no cells, or not a place for each");
            for (const std::uint32_t node : nodes) {
                if (node >= taken.size() || taken[node] != 0)
                    throw std::invalid_argument("the saved " + name + " has a cell that is not its own");
                taken[node] = 1;
            }
            Placement at;
            at.name = name;
            at.id = id;
            at.anchored = described.anchored;
            at.parked = b.contains("parked");
            if (at.parked) {
                // Set aside: made where it was put away, and set aside again
                // before anything steps (below).
                at.pose = rigidFrom(b.at("parked").at("pose"));
                at.pose.linear_velocity_m_s = {};
                at.pose.angular_velocity_rad_s = {};
                at.parked_mass_kg = numberFrom(b.at("parked").at("mass_kg"));
            } else {
                at.pose = rigidFrom(b.at("pose"));
                at.awake = b.value("awake", true);
            }
            for (std::size_t k = 0; k < nodes.size(); ++k) {
                ActiveNodeState &node = placed.nodes[nodes[k]];
                node.position_world_m = at.pose.center_of_mass_world_m + offsets[k];
                node.previous_position_world_m = node.position_world_m;
                node.velocity_m_s = {};
                node.spin_angular_velocity_rad_s = {};
            }
            const MaterialDefinition *definition = &setup.tile_material;
            if (setup.multi_body && !setup.part_of_node.empty()) {
                const std::uint32_t part = setup.part_of_node[nodes.front()];
                if (part < setup.part_definitions.size()) definition = &setup.part_definitions[part];
            }
            // How it meets things, as it was made: a piece a fracture made takes
            // the scene's, one a cut made its own material's.
            const double friction = numberFrom(b.at("friction"));
            const double restitution = numberFrom(b.at("restitution"));
            const double rolling = numberFrom(b.at("rolling_resistance"));
            const FragmentComponent component{0, nodes};
            FragmentBuildResult one = buildFragmentRepresentations(
                placed, std::span<const FragmentComponent>(&component, 1),
                {.first_body_id = id,
                 .maximum_rigid_fragments = 1,
                 .minimum_nodes_per_rigid_fragment = 1,
                 .maximum_collision_points = 192,
                 .friction = friction,
                 .restitution = restitution,
                 .rolling_resistance = rolling});
            if (one.rigid_fragments.empty())
                throw std::invalid_argument("the saved " + name + " could not be made from its cells");
            RigidFragmentDescription fragment = std::move(one.rigid_fragments.front());
            fragment.body_id = id;
            fragment.anchored = described.anchored;
            fragment.friction = friction;
            fragment.restitution = restitution;
            fragment.rolling_resistance = rolling;
            if (described.shape == "sphere" || described.shape == "box") {
                fragment.primitive = described.shape == "sphere" ? FragmentPrimitive::Sphere : FragmentPrimitive::Box;
                fragment.primitive_dimensions_m = described.dimensions_m;
            }
            if (b.contains("tilt_wxyz")) {
                const Quat tilt = quatFrom(b.at("tilt_wxyz"));
                fragment.primitive_rotation_wxyz[0] = tilt.w;
                fragment.primitive_rotation_wxyz[1] = tilt.x;
                fragment.primitive_rotation_wxyz[2] = tilt.y;
                fragment.primitive_rotation_wxyz[3] = tilt.z;
                impl.tilt_of[name] = tilt;
            }
            // Exactly where it was: its cells' middle, worked out again from the
            // same cells, is the same but for its last bits, and its offsets are
            // the saved ones exactly.
            fragment.mass_properties.center_of_mass_world_m = at.pose.center_of_mass_world_m;
            fragment.mass_properties.linear_velocity_m_s = {};
            fragment.mass_properties.angular_velocity_rad_s = {};
            for (std::size_t k = 0; k < nodes.size(); ++k) impl.cell_offset_m[nodes[k]] = offsets[k];
            impl.limits_of.push_back(fragmentFractureLimits(setup.matter, nodes, definition->density_kg_m3,
                                                            definition->young_modulus_pa,
                                                            definition->yield_strength_pa,
                                                            definition->fracture_energy_j_m2,
                                                            impl.request.cell_size_m));
            impl.impedance_of.push_back(acousticImpedance(definition->density_kg_m3, definition->young_modulus_pa));
            impl.density_of.push_back(definition->density_kg_m3);
            impl.tensile_of.push_back(definition->tensile_strength_pa);
            impl.compressive_of.push_back(definition->compressive_strength_pa);
            impl.nodes_of.push_back(nodes);
            impl.described.push_back(std::move(described));
            impl.body_of.push_back(id);
            build.rigid_fragments.push_back(std::move(fragment));
            placements.push_back(std::move(at));
        }
        // Carried, nothing of it may come back -- the room changed everything
        // in it -- and what the scene has instead is there.
        if (placements.empty() && !carrying) throw std::invalid_argument("the saved world has nothing in it");
        impl.next_body_id = std::max({impl.next_body_id, doc.at("next").at("body").get<MatterBodyId>(),
                                      ids.empty() ? MatterBodyId{1000} : *ids.rbegin() + 1});
    }
    // Carried, the room is never left empty: a scene whose every thing is
    // unchanged, and was swept up in the saved world, is opened as it is.
    if (carrying && build.rigid_fragments.empty())
        throw std::invalid_argument("nothing of the saved world or of the scene would be in the room");

    // The most bodies a live world will hold: what runReversibleTrial allows,
    // which is what breaking depends on.
    constexpr std::size_t kLiveBodyCeiling = 2048;
    const auto clampCapacity = [](std::size_t value, unsigned low, unsigned high) {
        return static_cast<unsigned>(std::clamp<std::size_t>(value, low, high));
    };
    impl.world = std::make_unique<JoltWorld>(
        std::clamp(std::thread::hardware_concurrency(), 1U, 64U),
        // Sized for what the world may GROW to, not for what it opened with.
        //
        // A live world starts with a few dozen bodies and reaches hundreds by
        // breaking them, and the capacity was worked out once from the opening
        // count. That was fine while the reversible trial capped the world at
        // 256; with the cap at 2,048 it is not, and going over does not slow
        // anything down -- it drops contacts and says "the step is not
        // validated", which is a worse failure than any pause.
        RigidContactCapacity{clampCapacity(64U * kLiveBodyCeiling, 16384U, 262144U),
                             clampCapacity(128U * kLiveBodyCeiling, 8192U, 65536U)});
    impl.ground_impedance = acousticImpedance(setup.ground_material.density_kg_m3,
                                             setup.ground_material.young_modulus_pa);
    impl.world->setGravity(r.gravity_m_s2);
    // A live world always watches contacts: they are how it will know when
    // something has been hit hard enough to break, and they are what a host
    // narrates back to whoever is playing with it.
    impl.world->setImpactObservationsEnabled(true);
    // The floor reaches as far as a hand can carry something.
    //
    // The batch lane's ground is 8 m square, which is ample for a plate dropped
    // where it was authored -- nothing in a recording ever moves sideways on
    // its own. A live world is different: someone picks an object up and takes
    // it where they like, and past 4 m there was simply no floor. An iron ball
    // carried to x = 5 m and let go fell to -7.9 m and kept going, which is not
    // a physics answer, it is the absence of one.
    //
    // A support plane costs one entry in a fixed-size set however big it is, so
    // there is nothing to trade: make it larger than anywhere a pointer can
    // reasonably drag something.
    // Hitting the floor is something that happens to things, so it is judged
    // like any other contact. The batch lane does not ask for this and is
    // unchanged by it.
    impl.world->setSurfaceImpactObservations(true);
    constexpr double kLiveGroundHalfSpanM = 200.0;
    impl.world->addSupportSurface({
        .frame = makeSupportPlane({0.0, setup.ground_y, 0.0}, {0.0, 1.0, 0.0}),
        .material = setup.ground_material,
        .half_length_tangent_m = kLiveGroundHalfSpanM,
        .half_length_bitangent_m = kLiveGroundHalfSpanM,
        .thickness_m = 0.5,
    });
    if (impl.environment) impl.environment->attach(*impl.world);
    MatterBodyId next_static = 900;
    for (const StaticBox &ledge : setup.ledges)
        impl.world->addBox({.body_id = next_static++, .dimensions_m = ledge.dimensions_m,
                            .material = setup.ground_material,
                            .state = {.center_of_mass_world_m = ledge.center_m}, .fixed = true});
    impl.world->addFragments(build.rigid_fragments);

    // Exact compounds live in the same Jolt world as the anchored lattice
    // scenery. Their source definition, COM frame and native mass properties
    // are authoritative; an empty cell array is intentional, never a hull.
    std::set<MatterBodyId> used_ids(impl.body_of.begin(), impl.body_of.end());
    for (const auto &[name, body] : impl.precise_bodies) {
        const nlohmann::json *previous = nullptr;
        if (saved) for (const auto &b : saved->doc.at("bodies"))
            if (b.at("name") == name) previous = &b;
        MatterBodyId id = previous ? previous->at("body_id").get<MatterBodyId>() : impl.next_body_id++;
        if (id < 1000 || !used_ids.insert(id).second)
            throw std::invalid_argument("precise rigid saved body ID collision");
        impl.next_body_id = std::max(impl.next_body_id, id + 1);
        RigidSnapshot pose = body.initial;
        bool awake = true;
        bool away = false;
        double away_kg = 0.0;
        if (previous) {
            if (previous->value("shape", std::string{}) != "compound" ||
                previous->value("anchored", false) || previous->value("fragment", false) ||
                !previous->at("nodes_b64").get<std::string>().empty() ||
                !previous->at("offsets_b64").get<std::string>().empty() ||
                previous->value("revision", 0U) != 0 || numberFrom(previous->at("dent_m")) != 0.0)
                throw std::invalid_argument("invalid or unsupported saved precise-rigid state");
            const Vec3 dims = vecFrom(previous->at("dimensions_m"));
            // Compare as a string, the way this block already reads nodes_b64
            // and color_rgba. materialPresetName returns std::string_view, and
            // `json != std::string_view` gives MSVC two equally good
            // conversions (json's own operator!= and string_view's), so it
            // refuses with C2666 and the whole live world stops building on
            // Windows while gcc accepts it.
            if (length(dims - body.dimensions_m) > 1e-12
                || previous->at("material").get<std::string>() != materialPresetName(body.material) ||
                previous->at("color_rgba").get<std::uint32_t>() != body.color_rgba)
                throw std::invalid_argument("saved precise-rigid descriptor does not match its source");
            // Set aside in the bag (park): made where it was put away, and set
            // aside again before anything steps, as a cell body is (below).
            away = previous->contains("parked");
            pose = rigidFrom(away ? previous->at("parked").at("pose") : previous->at("pose"));
            if (away) {
                pose.linear_velocity_m_s = {};
                pose.angular_velocity_rad_s = {};
                away_kg = numberFrom(previous->at("parked").at("mass_kg"));
            }
            awake = !away && previous->at("awake").get<bool>();
        }
        impl.world->addCompound({.body_id=id, .parts=body.parts,
            .material=makeReferenceMaterial(body.material), .state=pose,
            .mass_kg=body.mass_kg, .inertia_local_kg_m2=body.inertia});
        if (previous) {
            const auto surface = impl.world->surfaceOf(id);
            if (numberFrom(previous->at("friction")) != surface.friction ||
                numberFrom(previous->at("restitution")) != surface.restitution ||
                numberFrom(previous->at("rolling_resistance")) != surface.rolling_resistance)
                throw std::invalid_argument("saved precise-rigid surface differs from its material model");
            Placement at; at.name=name; at.id=id; at.pose=pose; at.awake=awake;
            at.parked=away; at.parked_mass_kg=away_kg;
            placements.push_back(at);
        }
        LiveBodyPose d;
        d.name=name; d.material=materialPresetName(body.material); d.shape="compound";
        d.mechanical_model="precise-rigid-v1"; d.dimensions_m=body.dimensions_m; d.color_rgba=body.color_rgba;
        for (std::size_t k = 0; k < body.parts.size(); ++k) {
            const RigidCompoundPart &part = body.parts[k];
            LiveBodyPose::PrecisePart drawn;
            drawn.shape = part.geometry.kind == PrimitiveKind::Cylinder ? "cylinder" : "box";
            drawn.center_local_m = part.center_local_m;
            drawn.dimensions_m = part.geometry.dimensions_m;
            drawn.rotation_wxyz = {part.rotation_local.w, part.rotation_local.x,
                                   part.rotation_local.y, part.rotation_local.z};
            drawn.material = materialPresetName(body.part_materials[k]);
            drawn.name = body.part_names[k];
            d.rigid_parts_local.push_back(std::move(drawn));
        }
        impl.described.push_back(std::move(d)); impl.body_of.push_back(id); impl.nodes_of.emplace_back();
        // What a breakable body it strikes is struck BY: its own material's
        // impedance, as for anything else. Zero here used to mean "the struck
        // body's own" (Refracture.cpp), so an iron cart meeting a glass pane
        // would have been judged as glass meeting glass. Its density is its
        // mean, parts of two materials and all.
        impl.limits_of.emplace_back();
        impl.impedance_of.push_back(acousticImpedance(body.made_of.density_kg_m3, body.made_of.young_modulus_pa));
        impl.density_of.push_back(body.mass_kg / body.volume_m3);
        impl.tensile_of.push_back(0); impl.compressive_of.push_back(0);
    }

    for (std::size_t i = 0; i < impl.described.size(); ++i)
        impl.index_of.emplace(impl.described[i].name, i);
    // A saved world's bodies turned and moving as they were -- or asleep, as
    // bodies at rest are, so a room that had settled does not all start being
    // simulated, and nudged, again. Scenery was made where it stands.
    for (const Placement &at : placements) {
        if (at.anchored) continue;
        impl.world->applyRigidState(at.id, at.pose);
        if (!at.parked && !at.awake) impl.world->sleep(at.id);
    }
    // Carried into a changed scene: a whole thing whose cells could not be
    // found again is put back where it was left, as a world that did not fit
    // puts it back (putBackWhereLeft); and what rested on a saved thing that did
    // not come back as it was -- the room took it away, or has it as the room
    // makes it now -- is woken to fall. Jolt wakes nothing sleeping on a body
    // that is simply not there (LiveWorld::park).
    std::vector<std::string> put_back;
    // What that wakes, by name, for the report (LiveRestore::woken): which
    // things lie near what did not come back depends on where the pieces of a
    // break came to rest, and that is not the same on every machine.
    std::vector<std::string> woken;
    if (carrying && plan.exact) {
        std::set<std::string> unmatched;
        for (std::size_t g = 0; g < plan.carried.size(); ++g)
            if (plan.cells_differ[g] != 0 && plan.saved_of[g] != CarryPlan::npos)
                for (const std::string &name : plan.bodies_of[plan.saved_of[g]]) unmatched.insert(name);
        if (!unmatched.empty()) put_back = live->putBackWhereLeft(*saved, &unmatched);
        const std::set<std::string> there(put_back.begin(), put_back.end());
        for (const nlohmann::json &b : saved->doc.at("bodies")) {
            const std::string name = b.at("name").get<std::string>();
            if (plan.carries(name) || there.count(name) != 0 || !b.contains("pose")) continue;
            const Vec3 at = rigidFrom(b.at("pose")).center_of_mass_world_m;
            const double reach = 0.5 * length(vecFrom(b.at("dimensions_m"))) + 0.05;
            for (const Placement &p : placements) {
                if (p.anchored || p.parked) continue;
                const std::size_t j = impl.index_of.at(p.name);
                if (length(p.pose.center_of_mass_world_m - at) <= reach + 0.5 * length(impl.described[j].dimensions_m)) {
                    impl.world->wake(p.id);
                    if (std::find(woken.begin(), woken.end(), p.name) == woken.end()) woken.push_back(p.name);
                }
            }
        }
    }
    if (saved && saved->doc.contains("material_geometry")) {
        const auto &geometry = saved->doc.at("material_geometry");
        if (geometry.at("schema") != "banjo.material-geometry.v1" || !geometry.at("records").is_object())
            throw std::invalid_argument("unsupported saved material geometry");
        for (const auto &[name, entry] : geometry.at("records").items()) {
            if (carrying && !plan.carries(name)) continue;
            const auto found = impl.index_of.find(name);
            if (found == impl.index_of.end()) throw std::invalid_argument("saved material geometry body is absent");
            const auto i = found->second;
            MatterRecord m;
            m.applied_m = numberFrom(entry.at("applied_m"));
            m.remaining_volume_m3 = numberFrom(entry.at("remaining_volume_m3"));
            m.bond_tension_min = numberFrom(entry.at("bond_tension_min"));
            m.bond_tension_mean = numberFrom(entry.at("bond_tension_mean"));
            m.bond_stiffness_mean = numberFrom(entry.at("bond_stiffness_mean"));
            m.seen_consumed_m = numberFrom(entry.at("seen_consumed_m"));
            m.reference_inferred = entry.value("reference_inferred", false);
            m.round = entry.at("round").get<bool>();
            m.revision = entry.at("revision").get<unsigned>();
            m.cells_burned = entry.at("cells_burned").get<std::size_t>();
            m.seen_cells = entry.at("seen_cells").get<std::size_t>();
            m.limits_heated = entry.at("limits_heated").get<bool>();
            m.box_m = vecFrom(entry.at("box_m"));
            m.centre_m = vecFrom(entry.at("centre_m"));
            m.turn = quatFrom(entry.at("turn"));
            m.seen_surface.stiffness = numberFrom(entry.at("seen_surface").at("stiffness"));
            m.seen_surface.tension = numberFrom(entry.at("seen_surface").at("tension"));
            m.seen_surface.compression = numberFrom(entry.at("seen_surface").at("compression"));
            m.seen_surface.shear = numberFrom(entry.at("seen_surface").at("shear"));
            m.seen_core.stiffness = numberFrom(entry.at("seen_core").at("stiffness"));
            m.seen_core.tension = numberFrom(entry.at("seen_core").at("tension"));
            m.seen_core.compression = numberFrom(entry.at("seen_core").at("compression"));
            m.seen_core.shear = numberFrom(entry.at("seen_core").at("shear"));
            impl.limits_of[i].minimum_removal_stretch = numberFrom(entry.at("limits").at("minimum_removal_stretch"));
            impl.limits_of[i].minimum_removal_energy_j = numberFrom(entry.at("limits").at("minimum_removal_energy_j"));
            impl.limits_of[i].yield_stretch = numberFrom(entry.at("limits").at("yield_stretch"));
            impl.limits_of[i].bar_wave_speed_m_s = numberFrom(entry.at("limits").at("bar_wave_speed_m_s"));
            impl.limits_of[i].acoustic_impedance_pa_s_m = numberFrom(entry.at("limits").at("acoustic_impedance_pa_s_m"));
            impl.limits_of[i].live_bonds = entry.at("limits").at("live_bonds").get<std::size_t>();
            impl.limits_of[i].cells = entry.at("limits").at("cells").get<std::size_t>();
            impl.impedance_of[i] = numberFrom(entry.at("impedance"));
            if (!(m.box_m.x > 0 && m.box_m.y > 0 && m.box_m.z > 0) || !(m.applied_m >= 0))
                throw std::invalid_argument("invalid saved material reference geometry");
            impl.matter_of.emplace(name, std::move(m));
        }
    }
    // What the scene declares about heat, chemistry and gas. A declaration the
    // network refuses refuses the scene, with the network's own words, rather
    // than opening a world that quietly lacks the fire it was asked for. A world
    // opened again from a saved one declares only what is about something still
    // there. Versioned saved network state replaces these initial values below.
    if (!r.thermo_scene_json.empty()) {
        thermo::Declarations declared = thermo::readSceneDeclarations(r.thermo_scene_json);
        if (saved != nullptr) keepWhatIsThere(declared, impl.index_of);
        if (declared.any()) thermo::apply(live->ensureThermo(), declared);
    }
    // Ice melts in a warm room whether or not anything heats it -- the network
    // follows it from the start (ThermoWorld::refresh) -- so a room holding
    // something that melts below the room's temperature has a network even
    // when its scene declares no heat at all.
    if (!impl.thermo) {
        const thermo::Model model = thermo::demonstrationModel();
        const double room = thermo::Ambient{}.temperature_k;
        for (const LiveBodyPose &pose : impl.described)
            if (impl.precise_bodies.count(pose.name) == 0 && thermo::meltingPointOf(model, pose.material) < room) {
                (void)live->ensureThermo();
                break;
            }
    }
    // Carried: the heat of each thing that came back as it was saved -- what
    // it holds and how hot each zone is, its fuel and its char, the hottest it
    // has been -- as the saved world's network held it, unless the scene now
    // declares that thing's heat another way, when it is as declared. Heaters
    // and gas regions are the scene's, from the start (notCarried).
    std::size_t carried_heat = 0;
    // What the host declared that did not come back as it was, in words.
    std::vector<std::string> lost;
    if (carrying && plan.exact && saved->doc.contains("heat") && saved->doc.at("heat").is_object()) {
        const nlohmann::json &heat = saved->doc.at("heat");
        // Into the saved world itself, which outlives what is kept of it here.
        static const nlohmann::json no_lumps = nlohmann::json::array();
        const nlohmann::json &lumps = heat.contains("lumps") && heat.at("lumps").is_array() ? heat.at("lumps") : no_lumps;
        std::vector<const nlohmann::json *> coming;
        for (const nlohmann::json &j : lumps) {
            const std::string body = j.value("body", std::string{});
            if (!plan.carries(body)) continue;
            const std::size_t s = plan.part_of_body.at(body);
            if (plan.saved[s].heat != impl.part_prints[plan.saved[s].now].heat) {
                lost.push_back("the " + body + "'s heat: the room declares it anew");
                continue;
            }
            coming.push_back(&j);
        }
        if (!coming.empty()) {
            thermo::ThermoWorld &network = live->ensureThermo();
            const std::size_t substances = network.model().size();
            const std::size_t then = heat.value("substances", std::size_t{0});
            if (then != substances) {
                lost.push_back("heat: the saved world's network knew " + std::to_string(then) + " substances and this "
                               "one knows " + std::to_string(substances) + ", so every thing's heat is as the room "
                               "declares it");
            } else {
                thermo::ThermoState state = network.state();
                const std::vector<double> shift = referenceShift(heat, network.model());
                for (const nlohmann::json *j : coming) {
                    thermo::Lump lump = lumpFrom(*j, state, substances, network.model(), shift);
                    // The rigid body was made again from its cells, so it is
                    // told what the network says it weighs -- only when that
                    // differs, so a thing heat has not lightened keeps its
                    // motion to the last bit.
                    const double kg = thermo::massKg(lump.surface) + thermo::massKg(lump.core);
                    if (const auto at = impl.index_of.find(lump.body);
                        at != impl.index_of.end() && impl.inWorld(at->second) && !impl.described[at->second].anchored) {
                        const MatterBodyId id = impl.body_of[at->second];
                        if (kg > 0.0 && std::abs(kg - impl.world->mechanicalState(id).mass_kg) > 1.0e-3 * kg)
                            impl.world->setMass(id, kg);
                    }
                    lump.mirrored_mass_kg = kg;
                    bool replaced = false;
                    for (thermo::Lump &have : state.lumps)
                        if (have.body == lump.body) {
                            have = lump;
                            replaced = true;
                        }
                    if (!replaced) state.lumps.push_back(std::move(lump));
                    ++carried_heat;
                }
                network.restore(state);
                network.refresh(live->thermoShapes(), setup.ground_y);
            }
        }
    }
    bool carried_thermal_network = false;
    // Preserve an unchanged operating network through a scene edit. Native
    // geometry refresh may change paths or admit a new thermal lump; atomic
    // installation compares all network fields and refuses such changes.
    if (carrying && plan.exact && saved->doc.contains("heat") &&
        saved->doc.at("heat").contains("network") && impl.thermo) {
        const auto &heat = saved->doc.at("heat");
        const auto &networkDoc = heat.at("network");
        const auto &current = impl.thermo->state();
        const bool stamped = heat.contains("scene_settings");
        const bool compatible = stamped
            ? heat.at("scene_settings") == thermalSettings(r.thermo_scene_json)
            : current.regions.empty() && current.heaters.empty() &&
              networkDoc.at("regions").empty() && networkDoc.at("heaters").empty();
        bool supports = true;
        for (const auto &region : networkDoc.at("regions")) {
            if (!region.contains("piston")) continue;
            const auto &piston = region.at("piston");
            const auto body = piston.at("body").get<std::string>();
            const auto container = piston.at("container").get<std::string>();
            supports = supports && plan.carries(body) && (container.empty() || plan.carries(container));
        }
        std::set<std::string> prior_thermal_bodies;
        for (const auto &lump : heat.at("lumps")) prior_thermal_bodies.insert(lump.at("body").get<std::string>());
        // Fresh, undeclared cold lumps are admitted by refresh and counted as
        // crossings into the thermal network. A newly declared hot inventory
        // needs a separate explicit transfer and is not imported by this rule.
        const bool cold_additions = std::all_of(current.lumps.begin(), current.lumps.end(),
            [&](const thermo::Lump &lump) { return prior_thermal_bodies.count(lump.body) || !lump.declared; });
        if (compatible && supports && cold_additions && carried_heat == heat.at("lumps").size()) {
            impl.thermo->restore(readThermoState(heat, impl.thermo->model()));
            impl.thermo->refresh(live->thermoShapes(), setup.ground_y);
            carried_thermal_network = true;
        }
    }
    // Legacy saves already contain body parcels and damage history. Import
    // those rather than cooling/refuelling the bodies. Missing network history
    // cannot be inferred: gas retains its legacy policy, heaters are suspended and
    // the ledger starts at the imported state, an explicit migration boundary.
    if (saved && !carrying && saved->doc.contains("heat") && !saved->doc.at("heat").contains("network")) {
        const auto &heat = saved->doc.at("heat");
        auto &network = live->ensureThermo();
        const auto substances = network.model().size();
        if (heat.at("substances").get<std::size_t>() != substances)
            throw std::invalid_argument("incompatible legacy thermal substances");
        auto state = network.state();
        state.lumps.clear();
        std::set<std::string> names;
        for (const auto &record : heat.at("lumps")) {
            auto lump = lumpFrom(record, state, substances, network.model(), referenceShift(heat, network.model()));
            if (!impl.index_of.count(lump.body) || !names.insert(lump.body).second)
                throw std::invalid_argument("invalid legacy thermal body");
            const auto region = record.value("environment", std::string{});
            if (!region.empty() && lump.environment < 0)
                throw std::invalid_argument("legacy thermal environment is absent");
            state.lumps.push_back(std::move(lump));
        }
        state.ledger = {};
        state.opened = false;
        // No saved schedule means no authority to replay heater work. The
        // user can issue a new heater command after this explicit migration.
        state.heaters.clear();
        network.restore(state);
        network.refresh(live->thermoShapes(), setup.ground_y);
    }
    // Identical-scene restores retain all thermal state, including the network
    // clock, finite gas contents, heater schedules and accumulated ledger.
    // Older snapshots remain readable through the existing legacy path.
    if (saved && !carrying && saved->doc.contains("heat") && saved->doc.at("heat").contains("network")) {
        auto &network = live->ensureThermo();
        auto state = readThermoState(saved->doc.at("heat"), network.model());
        for (const auto &lump : state.lumps)
            if (!impl.index_of.count(lump.body)) throw std::invalid_argument("saved thermal body is absent");
        for (const auto &region : state.regions)
            if (region.piston && (!impl.index_of.count(region.piston->body) ||
                (!region.piston->container.empty() && !impl.index_of.count(region.piston->container))))
                throw std::invalid_argument("saved gas piston or container is absent");
        network.restore(state);
    }
    // Older saves retained the collision shape and reacted inventories, but
    // not their reference frame. For surviving primitives infer a reference
    // whose remaining volume is exactly the saved shape at today's consumed
    // fraction. Do not regrow geometry or reset fuel to pretend history exists.
    std::vector<std::string> geometry_notes;
    if (saved && !saved->doc.contains("material_geometry") && impl.thermo) {
        for (std::size_t i = 0; i < impl.described.size(); ++i) {
            const auto &pose = impl.described[i];
            if (carrying && !plan.carries(pose.name)) continue;
            if (carrying) {
                const auto part = plan.part_of_body.at(pose.name);
                if (plan.saved[part].heat != impl.part_prints[plan.saved[part].now].heat) continue;
            }
            const auto matter = impl.thermo->matter(pose.name);
            if (!matter || !thermo::lawFor(pose.material) || !(matter->consumed_fraction > 0)) continue;
            if (pose.shape != "box" && pose.shape != "sphere") {
                geometry_notes.push_back(pose.name + ": legacy nonprimitive thermal reference history is unavailable");
                continue;
            }
            const double retained = 1.0 - matter->consumed_fraction;
            const Vec3 now = pose.dimensions_m;
            if (!(retained > 0 && now.x > 0 && now.y > 0 && now.z > 0)) continue;
            // V(now + 2d) = V(now)/(1-consumed). Ratios avoid dividing by a
            // tiny volume. The largest dimension provides a bounded bracket.
            double low = 0;
            double high = 0.5 * std::max({now.x, now.y, now.z}) * (std::cbrt(1.0 / retained) - 1.0);
            for (int k = 0; k < 80; ++k) {
                const double depth = 0.5 * (low + high);
                const double ratio = (now.x / (now.x + 2 * depth)) *
                    (now.y / (now.y + 2 * depth)) * (now.z / (now.z + 2 * depth));
                if (ratio > retained) low = depth;
                else high = depth;
            }
            auto &record = live->recordOf(i);
            const double depth = 0.5 * (low + high);
            record.box_m = now + Vec3{2 * depth, 2 * depth, 2 * depth};
            record.applied_m = thermo::recessionDepthM(record.box_m, matter->consumed_fraction);
            record.revision = pose.revision;
            record.reference_inferred = true;
            const auto field = live->fieldOf(i);
            if (field) {
                record.remaining_volume_m3 = thermo::remainingVolumeM3(*field);
                record.seen_consumed_m = -1;
                live->refreshHeatedBonds(i, *field);
            }
            geometry_notes.push_back(pose.name + ": legacy thermal reference inferred from saved shape and consumed fraction; original geometry history is unavailable");
        }
    }
    if (saved == nullptr) return live;
    if (carrying && !plan.exact) {
        // Nothing can be carried exactly -- the saved world does not say what
        // its things were, or the room lays its cells out another way now --
        // so the room opens as it is, with each whole thing the change did not
        // touch put back where it was left, as a world that did not fit puts it
        // back: never a thing the room has changed.
        LiveRestore said;
        said.tier = "none";
        said.why = plan.why_not;
        said.saved_t_s = saved->doc.contains("t_s") ? numberFrom(saved->doc.at("t_s")) : 0.0;
        said.not_kept = notCarried();
        std::set<std::string> unchanged;
        for (std::size_t s = 0; s < plan.saved.size(); ++s)
            if (plan.saved[s].now != CarryPlan::npos)
                for (const std::string &name : plan.bodies_of[s]) unchanged.insert(name);
        said.bodies = live->putBackWhereLeft(*saved, &unchanged).size();
        if (said.bodies > 0) said.tier = "poses";
        impl.restored = std::move(said);
        return live;
    }

    // ---- the rest of a saved world -------------------------------------------
    const nlohmann::json &doc = saved->doc;
    LiveRestore said;
    said.tier = carrying ? "carried" : "whole";
    said.saved_t_s = numberFrom(doc.at("t_s"));
    said.bodies = placements.size();
    said.not_kept = carrying ? notCarried() : notKept();
    if (carrying && carried_thermal_network && !said.not_kept.empty()) said.not_kept.erase(said.not_kept.begin());
    if (!water_note.empty()) said.not_kept.push_back(water_note);
    said.not_kept.insert(said.not_kept.end(), geometry_notes.begin(), geometry_notes.end());
    // What comes back of what the host declared: all of it, for a world opened
    // whole; carried into a changed scene, what the host still declares the
    // same way (LiveCarry), on things that came back as they were saved.
    const LiveCarry nothing_asked;
    const LiveCarry &asked = carrying ? *carry : nothing_asked;
    const auto kept = [&](const std::set<unsigned> &declared, unsigned id) {
        return !carrying || declared.count(id) != 0;
    };
    const auto back = [&](const std::string &body) { return !carrying || plan.carries(body); };
    // A pin by the two things it joins, as the saved world has it.
    const auto pinBetween = [&](unsigned id) {
        for (const nlohmann::json &o : doc.at("joints"))
            if (o.value("id", 0U) == id)
                return "the " + o.value("a", std::string{}) + " and the " + o.value("b", std::string{});
        return std::string("pin ") + std::to_string(id);
    };
    // Set aside again, where each was put away and holding what it held.
    for (const Placement &at : placements) {
        if (!at.parked) continue;
        std::string refused;
        if (!impl.world->park(at.id, refused))
            throw std::invalid_argument("the saved " + at.name + " could not be set aside again: " + refused);
        impl.parked.emplace(at.name, Impl::ParkedRecord{at.pose, at.parked_mass_kg});
        if (impl.thermo && impl.thermo->holds(at.name)) impl.thermo->park(at.name);
        said.parked.push_back({at.name, at.pose.center_of_mass_world_m,
                               composeTurns(at.pose.orientation_world, impl.shapeTurn(impl.index_of.at(at.name)))});
    }
    // Where blades have been through things, each in its body's own frame, and
    // the bonds each crosses, found again from its cells.
    for (const auto &[name, list] : doc.at("kerfs").items()) {
        const auto found = impl.index_of.find(name);
        if (found == impl.index_of.end() || !back(name)) continue;
        for (const nlohmann::json &k : list) {
            Impl::Kerf kerf{};
            kerf.blade = k.at("blade").get<unsigned>();
            kerf.origin = vecFrom(k.at("origin"));
            kerf.u = vecFrom(k.at("u"));
            kerf.v = vecFrom(k.at("v"));
            kerf.w = vecFrom(k.at("w"));
            kerf.strip = numberFrom(k.at("strip"));
            kerf.half_width = numberFrom(k.at("half_width"));
            for (const nlohmann::json &entry : k.at("swept")) {
                auto &spans = kerf.swept[entry.at(0).get<int>()];
                for (const nlohmann::json &span : entry.at(1))
                    spans.emplace_back(numberFrom(span.at(0)), numberFrom(span.at(1)));
            }
            findCrossings(kerf, impl.nodes_of[found->second], impl.cell_offset_m, setup.asset);
            impl.kerfs[name].push_back(std::move(kerf));
        }
    }
    // Edges, in their bodies' frames, with what each has cut.
    for (const nlohmann::json &b : doc.at("blades")) {
        Impl::Blade blade{};
        blade.id = b.at("id").get<unsigned>();
        blade.body = b.at("body").get<std::string>();
        blade.heel_local = vecFrom(b.at("heel_local"));
        blade.tip_local = vecFrom(b.at("tip_local"));
        blade.facing_local = vecFrom(b.at("facing_local"));
        blade.grip_local = vecFrom(b.at("grip_local"));
        blade.thickness = numberFrom(b.at("thickness_m"));
        blade.edge_radius = numberFrom(b.at("edge_radius_m"));
        blade.bevel_deg = numberFrom(b.at("bevel_deg"));
        blade.cut_area = numberFrom(b.at("cut_area_m2"));
        blade.cut_work = numberFrom(b.at("cut_work_j"));
        blade.attached = b.value("attached", true);
        blade.body_id = b.at("body_id").get<MatterBodyId>();
        blade.frame_nodes = unpackedArray<std::uint32_t>(b, "frame_nodes_b64");
        blade.frame_offsets = unpackedVecs(b, "frame_offsets_b64");
        if (carrying) {
            if (!kept(asked.blades, blade.id) || !back(blade.body)) continue;
            for (std::uint32_t &node : blade.frame_nodes) node = plan.node(node);
            if (std::find(blade.frame_nodes.begin(), blade.frame_nodes.end(), CarryPlan::none) !=
                blade.frame_nodes.end()) {
                lost.push_back("the " + blade.body + "'s edge: its cells are not all the " + blade.body +
                               "'s, so it is as the room declares it");
                continue;
            }
            ++said.carried.blades;
        }
        impl.blades.push_back(std::move(blade));
    }
    impl.next_blade = doc.at("next").at("blade").get<unsigned>();
    // Tools' points, likewise.
    {
        std::vector<ToolTerrain::SavedPoint> points;
        for (const nlohmann::json &p : doc.at("tool_points")) {
            ToolTerrain::SavedPoint point;
            point.id = p.at("id").get<unsigned>();
            point.body = p.at("body").get<std::string>();
            point.tip_local = vecFrom(p.at("tip_local"));
            point.pointing_local = vecFrom(p.at("pointing_local"));
            point.grip_local = vecFrom(p.at("grip_local"));
            point.width_local = vecFrom(p.at("width_local"));
            point.shape.width_m = numberFrom(p.at("width_m"));
            point.shape.thickness_m = numberFrom(p.at("thickness_m"));
            point.shape.angle_deg = numberFrom(p.at("angle_deg"));
            point.shape.length_m = numberFrom(p.at("length_m"));
            point.body_id = p.at("body_id").get<MatterBodyId>();
            point.frame_nodes = unpackedArray<std::uint32_t>(p, "frame_nodes_b64");
            point.frame_offsets = unpackedVecs(p, "frame_offsets_b64");
            point.attached = p.value("attached", true);
            if (carrying) {
                if (!kept(asked.tool_points, point.id) || !back(point.body)) continue;
                for (std::uint32_t &node : point.frame_nodes) node = plan.node(node);
                if (std::find(point.frame_nodes.begin(), point.frame_nodes.end(), CarryPlan::none) !=
                    point.frame_nodes.end()) {
                    lost.push_back("the " + point.body + "'s point: its cells are not all the " + point.body +
                                   "'s, so it is as the room declares it");
                    continue;
                }
                ++said.carried.tool_points;
            }
            points.push_back(std::move(point));
        }
        impl.tools.restore(points, doc.at("next").at("point").get<unsigned>());
    }
    // Joints: every one on record, and each that was holding made again where
    // it holds -- a pin and a slide reading what they read, with the travel
    // they had either side of it (HingeDescription::at_rad).
    constexpr double kPi = 3.14159265358979323846;
    for (const nlohmann::json &o : doc.at("joints")) {
        Impl::SceneJoint joint{};
        joint.id = o.at("id").get<unsigned>();
        joint.kind = kindFrom(o.at("kind").get<std::string>());
        joint.a = o.at("a").get<std::string>();
        joint.b = o.at("b").get<std::string>();
        joint.point_local_a = vecFrom(o.at("point_local_a"));
        joint.point_local_b = vecFrom(o.at("point_local_b"));
        joint.axis_local_a = vecFrom(o.at("axis_local_a"));
        joint.point_local_b_tie = vecFrom(o.at("point_local_b_tie"));
        joint.stand_off_a = numberFrom(o.at("stand_off_a"));
        joint.stand_off_b = numberFrom(o.at("stand_off_b"));
        joint.lower = numberFrom(o.at("lower"));
        joint.upper = numberFrom(o.at("upper"));
        joint.friction = numberFrom(o.at("friction"));
        joint.breaks_at_n = numberFrom(o.at("breaks_at_n"));
        joint.over_a = vecFrom(o.at("over_a"));
        joint.over_b = vecFrom(o.at("over_b"));
        joint.ratio = numberFrom(o.at("ratio"));
        joint.holds_tension_n = numberFrom(o.at("holds_tension_n"));
        joint.holds_shear_n = numberFrom(o.at("holds_shear_n"));
        joint.comes_off_n = numberFrom(o.at("comes_off_n"));
        joint.rest_m = numberFrom(o.at("rest_m"));
        joint.stiffness_n_m = numberFrom(o.at("stiffness_n_m"));
        joint.damping_n_s_m = numberFrom(o.at("damping_n_s_m"));
        joint.at_when_hung = numberFrom(o.at("at_when_hung"));
        joint.attached = o.at("attached").get<bool>();
        joint.member_end = o.at("member_end").get<int>();
        joint.declared_tension_n = numberFrom(o.at("declared_tension_n"));
        joint.declared_shear_n = numberFrom(o.at("declared_shear_n"));
        joint.declared_breaks_at_n = numberFrom(o.at("declared_breaks_at_n"));
        joint.declared_stiffness_n_m = numberFrom(o.at("declared_stiffness_n_m"));
        joint.declared_kept = o.at("declared_kept").get<bool>();
        joint.rated_tension_n = numberFrom(o.at("rated_tension_n"));
        joint.rated_shear_n = numberFrom(o.at("rated_shear_n"));
        joint.rated_breaks_at_n = numberFrom(o.at("rated_breaks_at_n"));
        joint.rated_stiffness_n_m = numberFrom(o.at("rated_stiffness_n_m"));
        joint.capacity_fraction = numberFrom(o.at("capacity_fraction"));
        joint.checked_fraction = numberFrom(o.at("checked_fraction"));
        joint.rechecks = o.at("rechecks").get<unsigned>();
        joint.parted_because = o.at("parted_because").get<std::string>();
        joint.parted_load_n = numberFrom(o.at("parted_load_n"));
        joint.parted_capacity_n = numberFrom(o.at("parted_capacity_n"));
        joint.member_said = o.at("member_said").get<std::string>();
        // A drum's, absent from a world saved before there were drums.
        joint.radius_m = o.value("radius_m", 0.0);
        joint.winds = o.value("winds", 1) < 0 ? -1 : 1;
        joint.rigid = 0;
        // Carried: one the host still declares the same way, between two
        // things that came back as they were saved (planCarry has already
        // left out anything that was on one that does not).
        if (carrying) {
            if (!kept(asked.joints, joint.id) || !back(joint.a) || !back(joint.b)) continue;
            ++said.carried.joints;
        }
        const auto one = impl.index_of.find(joint.a);
        const auto two = impl.index_of.find(joint.b);
        if (joint.attached && o.contains("held") && one != impl.index_of.end() && two != impl.index_of.end() &&
            impl.inWorld(one->second) && impl.inWorld(two->second)) {
            const nlohmann::json &held = o.at("held");
            const MatterBodyId ida = impl.body_of[one->second];
            const MatterBodyId idb = impl.body_of[two->second];
            const RigidSnapshot sa = impl.world->snapshot(ida);
            const RigidSnapshot sb = impl.world->snapshot(idb);
            const Vec3 point = sa.center_of_mass_world_m + sa.orientation_world.rotate(joint.point_local_a);
            const Vec3 along = sa.orientation_world.rotate(joint.axis_local_a);
            const Vec3 point_b = sb.center_of_mass_world_m + sb.orientation_world.rotate(joint.point_local_b_tie);
            switch (joint.kind) {
            case JoltWorld::JointKind::Hinge: {
                JoltWorld::HingeDescription pin{};
                pin.a = ida;
                pin.b = idb;
                pin.point_world_m = point;
                pin.axis_world = along;
                // Jolt keeps a limit as a float, and pi as a float is a hair
                // past pi: a full turn's limits, read back, are clamped to it.
                pin.lower_rad = std::max(-kPi, numberFrom(held.at("lower")));
                pin.upper_rad = std::min(kPi, numberFrom(held.at("upper")));
                pin.friction_torque_n_m = joint.friction;
                pin.at_rad = std::clamp(numberFrom(held.at("at")), -kPi, kPi);
                joint.rigid = impl.world->addHinge(pin);
                break;
            }
            case JoltWorld::JointKind::Slider: {
                JoltWorld::SliderDescription groove{};
                groove.a = ida;
                groove.b = idb;
                groove.point_world_m = point;
                groove.axis_world = along;
                groove.lower_m = std::min(0.0, numberFrom(held.at("lower")));
                groove.upper_m = std::max(0.0, numberFrom(held.at("upper")));
                groove.friction_n = joint.friction;
                groove.at_m = numberFrom(held.at("at"));
                joint.rigid = impl.world->addSlider(groove);
                break;
            }
            case JoltWorld::JointKind::Link: {
                JoltWorld::LinkDescription rope{};
                rope.a = ida;
                rope.b = idb;
                rope.point_a_world_m = point;
                rope.point_b_world_m = point_b;
                rope.length_m = joint.upper;
                rope.breaking_tension_n = joint.breaks_at_n;
                rope.taut_at_restore = numberFrom(held.at("lower")) > 0.0;
                joint.rigid = impl.world->addLink(rope);
                break;
            }
            case JoltWorld::JointKind::Pulley: {
                JoltWorld::PulleyDescription rove{};
                rove.a = ida;
                rove.b = idb;
                rove.point_a_world_m = point;
                rove.point_b_world_m = point_b;
                rove.over_a_world_m = joint.over_a;
                rove.over_b_world_m = joint.over_b;
                rove.ratio = joint.ratio;
                rove.length_m = joint.upper;
                joint.rigid = impl.world->addPulley(rove);
                break;
            }
            case JoltWorld::JointKind::Elastic: {
                JoltWorld::ElasticDescription limb{};
                limb.a = ida;
                limb.b = idb;
                limb.point_a_world_m = point;
                limb.point_b_world_m = point_b;
                limb.rest_m = joint.rest_m;
                limb.stiffness_n_m = joint.stiffness_n_m;
                limb.damping_n_s_m = joint.damping_n_s_m;
                joint.rigid = impl.world->addElastic(limb);
                break;
            }
            case JoltWorld::JointKind::Fixing: {
                JoltWorld::FixingDescription peg{};
                peg.a = ida;
                peg.b = idb;
                peg.point_world_m = point;
                peg.axis_world = along;
                peg.holds_tension_n = joint.holds_tension_n;
                peg.holds_shear_n = joint.holds_shear_n;
                peg.comes_off_n = joint.comes_off_n;
                joint.rigid = impl.world->addFixing(peg);
                break;
            }
            case JoltWorld::JointKind::Drum: {
                JoltWorld::DrumDescription rope{};
                rope.drum = ida;
                rope.load = idb;
                rope.centre_world_m = point;
                rope.axis_world = along;
                rope.radius_m = joint.radius_m;
                rope.load_point_world_m = point_b;
                rope.winds = joint.winds;
                rope.length_m = joint.upper;
                // As much off the drum as there was when it was saved, however
                // many turns are on it. (Zero would mean "as it hangs".)
                rope.out_m = std::clamp(numberFrom(held.at("at")), 1e-6, joint.upper);
                // And the tally itself, where it was kept, so that what is on
                // the drum and off it come back to the last bit.
                if (held.contains("wound_m"))
                    rope.wound_m = std::clamp(numberFrom(held.at("wound_m")), 0.0, joint.upper);
                joint.rigid = impl.world->addDrum(rope);
                break;
            }
            default:
                break;
            }
        }
        impl.joints.push_back(std::move(joint));
    }
    impl.next_joint = doc.at("next").at("joint").get<unsigned>();
    // Stores of energy and the motors on pins, as they stood: what each battery
    // holds and has given, and each motor's command, brake and account. None
    // in a world saved before there were machines.
    for (const nlohmann::json &o : doc.value("energy_stores", nlohmann::json::array())) {
        LiveEnergyStore store{};
        store.id = o.at("id").get<unsigned>();
        store.name = o.at("name").get<std::string>();
        store.body = o.at("body").get<std::string>();
        store.capacity_j = numberFrom(o.at("capacity_j"));
        store.charge_j = numberFrom(o.at("charge_j"));
        store.voltage_v = numberFrom(o.at("voltage_v"));
        store.max_power_w = numberFrom(o.at("max_power_w"));
        store.given_j = numberFrom(o.at("given_j"));
        store.taken_j = o.contains("taken_j") ? numberFrom(o.at("taken_j")) : 0.0;
        store.short_j = numberFrom(o.at("short_j"));
        // Carried: what it holds and has given, while what it is in came back
        // as it was saved and the host still declares it the same way.
        if (carrying) {
            const bool declared = kept(asked.energy_stores, store.id);
            if (!declared || (!store.body.empty() && !back(store.body))) {
                if (declared)
                    lost.push_back("the " + store.name + ": the " + store.body + " it is in did not come back as it "
                                   "was, so it is as the room declares it");
                continue;
            }
            ++said.carried.energy_stores;
        }
        impl.energy_stores.push_back(std::move(store));
    }
    for (const nlohmann::json &o : doc.value("motors", nlohmann::json::array())) {
        Impl::Motor motor{};
        motor.said.id = o.at("id").get<unsigned>();
        motor.said.joint = o.at("joint").get<unsigned>();
        motor.said.store = o.at("store").get<unsigned>();
        motor.said.stall_torque_n_m = numberFrom(o.at("stall_torque_n_m"));
        motor.said.no_load_rad_s = numberFrom(o.at("no_load_rad_s"));
        motor.said.brake_torque_n_m = numberFrom(o.at("brake_torque_n_m"));
        motor.said.command = numberFrom(o.at("command"));
        motor.said.brake = o.at("brake").get<bool>();
        // What it said of the last kept step before it was saved, until it
        // takes another. A world saved before these were kept has only its
        // command and brake to go on.
        motor.said.state = o.value("state", std::string(motor.said.brake            ? "braking"
                                                        : motor.said.command != 0.0 ? "driving"
                                                                                    : "coasting"));
        const auto lastStep = [&](const char *key) { return o.contains(key) ? numberFrom(o.at(key)) : 0.0; };
        motor.said.speed_rad_s = lastStep("speed_rad_s");
        motor.said.torque_n_m = lastStep("torque_n_m");
        motor.said.current_a = lastStep("current_a");
        motor.said.power_w = lastStep("power_w");
        motor.said.turned_rad = numberFrom(o.at("turned_rad"));
        motor.said.work_j = numberFrom(o.at("work_j"));
        motor.said.heat_j = numberFrom(o.at("heat_j"));
        motor.said.drawn_j = numberFrom(o.at("drawn_j"));
        motor.said.rotor_thrust_n_per_rad2 = o.contains("rotor_thrust_n_per_rad2") ? numberFrom(o.at("rotor_thrust_n_per_rad2")) : 0.0;
        motor.said.rotor_drag_n_m_per_rad2 = o.contains("rotor_drag_n_m_per_rad2") ? numberFrom(o.at("rotor_drag_n_m_per_rad2")) : 0.0;
        motor.said.air_j = o.contains("air_j") ? numberFrom(o.at("air_j")) : 0.0;
        motor.said.friction_heat_j = numberFrom(o.at("friction_heat_j"));
        // Carried: its command, brake and account, while its pin and its store
        // came back and the host still declares it the same way.
        if (carrying) {
            const bool declared = kept(asked.motors, motor.said.id);
            const bool pin = std::any_of(impl.joints.begin(), impl.joints.end(),
                                         [&](const Impl::SceneJoint &j) { return j.id == motor.said.joint; });
            const bool store = std::any_of(impl.energy_stores.begin(), impl.energy_stores.end(),
                                           [&](const LiveEnergyStore &s) { return s.id == motor.said.store; });
            if (!declared || !pin || !store) {
                if (declared)
                    lost.push_back("the motor on the pin between " + pinBetween(motor.said.joint) + ": " +
                                   (pin ? "its store" : "its pin") +
                                   " did not come back as it was, so it is as the room declares it");
                continue;
            }
            ++said.carried.motors;
        }
        impl.motors.push_back(std::move(motor));
    }
    impl.next_energy_store = doc.value("next_energy_store", 1U);
    impl.next_motor = doc.value("next_motor", 1U);
    if (carrying && doc.contains("circuits") && !doc.at("circuits").empty())
        throw std::invalid_argument("circuit state needs an unchanged-world restore; edited-scene carry is not supported");
    for (const auto &c : doc.value("circuits", nlohmann::json::array()))
        impl.attachCircuit(machines::Circuit::read(c, true));
    // Each machine's controller, as it was told; carried while its motor, and a
    // hoist's rope, came back and the host still declares it the same way.
    for (const nlohmann::json &o : doc.value("controls", nlohmann::json::array())) {
        Impl::Control c{};
        c.said.id = o.at("id").get<unsigned>();
        c.said.name = o.at("name").get<std::string>();
        c.said.motor = o.at("motor").get<unsigned>();
        c.said.rope = o.at("rope").get<unsigned>();
        c.said.top_out_m = numberFrom(o.at("top_out_m"));
        c.said.bottom_out_m = numberFrom(o.at("bottom_out_m"));
        c.said.forward = o.at("forward").get<int>() < 0 ? -1 : 1;
        c.said.power = o.at("power").get<bool>();
        c.said.direction = std::clamp(o.at("direction").get<int>(), -1, 1);
        c.said.setting = std::clamp(numberFrom(o.at("setting")), 0.0, 1.0);
        c.said.sender = o.value("sender", std::string{});
        c.said.seq = o.value("seq", std::uint64_t{0});
        for (const nlohmann::json &p : o.value("seen", nlohmann::json::array()))
            if (p.is_array() && p.size() == 2)
                c.seen.emplace_back(p[0].get<std::string>(), p[1].get<std::uint64_t>());
        c.tripped = o.value("tripped", false);
        c.said.condition = o.value("condition", std::string{});
        for (const nlohmann::json &p : o.value("sensors", nlohmann::json::array())) {
            LiveSensor sensor;
            sensor.kind = p.at("kind").get<std::string>();
            sensor.body = p.at("body").get<std::string>();
            sensor.at_local_m = vecFrom(p.at("at_local_m"));
            sensor.depth_m = numberFrom(p.at("depth_m"));
            sensor.stops = p.at("stops").get<int>() < 0 ? -1 : 1;
            if (sensor.kind != "water" || !(sensor.depth_m > 0.0))
                throw std::invalid_argument("a saved controller's sensor is not one this engine knows");
            c.said.sensors.push_back(std::move(sensor));
        }
        if (carrying) {
            const bool declared = kept(asked.controls, c.said.id);
            const bool motor = std::any_of(impl.motors.begin(), impl.motors.end(),
                                           [&](const Impl::Motor &m) { return m.said.id == c.said.motor; });
            const bool rope = c.said.rope == 0 ||
                              std::any_of(impl.joints.begin(), impl.joints.end(),
                                          [&](const Impl::SceneJoint &j) { return j.id == c.said.rope; });
            if (!declared || !motor || !rope) {
                if (declared)
                    lost.push_back("the controller of " + c.said.name + ": its " + (motor ? "rope" : "motor") +
                                   " did not come back as it was, so it is as the room declares it");
                continue;
            }
            ++said.carried.controls;
        }
        // What its sensors read where their parts now are, before the first
        // step says it: a reply before that would put each at the world's origin.
        impl.readSensors(c);
        impl.controls.push_back(std::move(c));
    }
    impl.next_control = doc.value("next_control", 1U);
    // Each machine's program, as it was told and as far as it had got; carried
    // while both of its wheels' controllers came back and the host still
    // declares it the same way.
    for (const nlohmann::json &o : doc.value("programs", nlohmann::json::array())) {
        Impl::Program p{};
        p.said.id = o.at("id").get<unsigned>();
        p.said.name = o.at("name").get<std::string>();
        p.said.kind = o.at("kind").get<std::string>();
        p.said.left = o.at("left").get<unsigned>();
        p.said.right = o.at("right").get<unsigned>();
        p.said.body = o.at("body").get<std::string>();
        p.said.setting = std::clamp(numberFrom(o.at("setting")), 0.0, 1.0);
        p.said.climb_deg = numberFrom(o.at("climb_deg"));
        if (p.said.kind != "roam" && p.said.kind != "hover")
            throw std::invalid_argument("a saved program is not of a kind this engine knows");
        for (const nlohmann::json &r : o.value("rotors", nlohmann::json::array())) p.said.rotors.push_back(r.get<unsigned>());
        for (const nlohmann::json &r : o.value("rotor_local", nlohmann::json::array())) p.rotor_local.push_back(vecFrom(r));
        for (const nlohmann::json &r : o.value("spins", nlohmann::json::array())) p.spins.push_back(r.get<int>());
        p.said.hover_m = o.value("hover_m", 0.0);
        p.landed_height_m = o.value("landed_height_m", 0.0);
        p.hover_i = o.value("hover_i", 0.0);
        for (const nlohmann::json &q : o.at("sensors")) {
            LiveSensor sensor;
            sensor.kind = q.at("kind").get<std::string>();
            sensor.body = q.at("body").get<std::string>();
            sensor.at_local_m = vecFrom(q.at("at_local_m"));
            sensor.depth_m = numberFrom(q.at("depth_m"));
            sensor.side = std::clamp(q.at("side").get<int>(), -1, 1);
            if (sensor.kind != "water" || !(sensor.depth_m > 0.0))
                throw std::invalid_argument("a saved program's sensor is not one this engine knows");
            p.said.sensors.push_back(std::move(sensor));
        }
        p.forward_local = vecFrom(o.at("forward_local"));
        p.left_local = vecFrom(o.at("left_local"));
        p.said.power = o.at("power").get<bool>();
        p.said.sender = o.value("sender", std::string{});
        p.said.seq = o.value("seq", std::uint64_t{0});
        for (const nlohmann::json &q : o.value("seen", nlohmann::json::array()))
            if (q.is_array() && q.size() == 2) p.seen.emplace_back(q[0].get<std::string>(), q[1].get<std::uint64_t>());
        p.said.doing = o.at("doing").get<std::string>();
        p.said.why = o.at("why").get<std::string>();
        p.said.doing_s = numberFrom(o.at("doing_s"));
        p.said.turned_deg = numberFrom(o.at("turned_deg"));
        p.said.turns = o.at("turns").get<unsigned>();
        p.said.rest_below = o.contains("rest_below") ? numberFrom(o.at("rest_below")) : 0.0;
        p.said.rest_until = o.contains("rest_until") ? numberFrom(o.at("rest_until")) : 0.0;
        p.said.rests = o.value("rests", 0U);
        p.said.asked = o.value("asked", std::string{});
        p.said.asked_why = o.value("asked_why", std::string{});
        p.said.asked_by = o.value("asked_by", std::string{});
        p.said.asked_for_s = o.contains("asked_for_s") ? numberFrom(o.at("asked_for_s")) : 0.0;
        p.said.asked_s = o.contains("asked_s") ? numberFrom(o.at("asked_s")) : 0.0;
        if (o.contains("asked_toward_m")) p.said.asked_toward_m = vecFrom(o.at("asked_toward_m"));
        p.said.store = o.value("store", 0U);
        p.turn_sign = std::clamp(o.at("turn_sign").get<int>(), -1, 1);
        p.turn_least_deg = numberFrom(o.at("turn_least_deg"));
        p.then_turn = o.at("then_turn").get<int>() < 0 ? -1 : 1;
        p.told = o.at("told").get<std::uint64_t>();
        p.interrupted = o.value("interrupted", false);
        p.interruptions = o.value("interruptions", 0U);
        if (carrying) {
            const bool declared = kept(asked.programs, p.said.id);
            const bool wheels = p.said.kind == "still"
                                    ? impl.energyStoreById(p.said.store) != nullptr
                                    : impl.controlById(p.said.left) != nullptr && impl.controlById(p.said.right) != nullptr;
            if (!declared || !wheels) {
                if (declared)
                    lost.push_back("the program of " + p.said.name +
                                   ": its wheels' controllers did not come back as they were, so it is as the "
                                   "room declares it");
                continue;
            }
            ++said.carried.programs;
        }
        // Its slope and heading, and what its sensors read, where its parts
        // now are, before the first step says it.
        impl.readProgram(p);
        impl.programs.push_back(std::move(p));
    }
    impl.next_program = doc.value("next_program", 1U);
    // The room's sun, and each solar panel, carried while its part and its
    // store came back and the host still declares it the same way.
    if (doc.contains("sun")) {
        const nlohmann::json &sun = doc.at("sun");
        if (sun.contains("day_s")) {
            // Its day as it was; where it stands follows from the world's clock,
            // once that is back (below).
            if (!live->setDay(numberFrom(sun.at("day_s")), numberFrom(sun.at("noon_elevation_deg")), 0.0,
                              numberFrom(sun.at("irradiance_w_m2"))))
                throw std::invalid_argument("a saved sun's day is not one this engine can keep");
            impl.sun.hour_at_start = numberFrom(sun.at("hour_at_start"));
            if (!std::isfinite(impl.sun.hour_at_start))
                throw std::invalid_argument("a saved sun's hour is not a number");
        } else if (!live->setSun(numberFrom(sun.at("elevation_deg")), numberFrom(sun.at("azimuth_deg")),
                                 numberFrom(sun.at("irradiance_w_m2")))) {
            throw std::invalid_argument("a saved sun is not one this engine can put in the sky");
        }
    }
    for (const nlohmann::json &o : doc.value("solar_panels", nlohmann::json::array())) {
        LiveSolarPanel panel;
        panel.id = o.at("id").get<unsigned>();
        panel.name = o.at("name").get<std::string>();
        panel.body = o.at("body").get<std::string>();
        panel.store = o.at("store").get<unsigned>();
        panel.at_local_m = vecFrom(o.at("at_local_m"));
        panel.normal_local = vecFrom(o.at("normal_local"));
        panel.area_m2 = numberFrom(o.at("area_m2"));
        panel.efficiency = numberFrom(o.at("efficiency"));
        panel.sunlight_j = numberFrom(o.at("sunlight_j"));
        panel.collected_j = numberFrom(o.at("collected_j"));
        panel.spilled_j = numberFrom(o.at("spilled_j"));
        panel.heat_j = numberFrom(o.at("heat_j"));
        if (carrying) {
            const bool declared = kept(asked.solar_panels, panel.id);
            const bool store = impl.energyStoreById(panel.store) != nullptr;
            if (!declared || !store || !back(panel.body)) {
                if (declared)
                    lost.push_back("the " + panel.name + ": the " + (store ? panel.body : std::string("store")) +
                                   " it is on did not come back as it was, so it is as the room declares it");
                continue;
            }
            ++said.carried.solar_panels;
        }
        impl.panels.push_back(std::move(panel));
    }
    impl.next_panel = doc.value("next_panel", 1U);
    // Anything still attached with nothing standing in for it as it was saved
    // is hung now, as after any rearrangement of the bodies.
    live->rehangJoints();
    // The hand: what it holds, how, and where it wants it.
    {
        const nlohmann::json &hand = doc.at("hand");
        impl.hand_strength_n = numberFrom(hand.at("strength_n"));
        impl.hand_torque_n_m = numberFrom(hand.at("torque_n_m"));
        impl.hand_mass_kg = numberFrom(hand.at("mass_kg"));
        // Plain values, kept whether or not it holds anything: an empty hand
        // still says what the work was, and where it last wanted the grip.
        impl.grip_local = vecFrom(hand.at("grip_local_m"));
        impl.held_at = vecFrom(hand.at("held_at_m"));
        impl.held_facing = quatFrom(hand.at("held_facing_wxyz"));
        impl.hand_work_j = numberFrom(hand.at("work_j"));
        const std::string holding = hand.value("holding", std::string{});
        if (const auto found = impl.index_of.find(holding);
            !holding.empty() && found != impl.index_of.end() && impl.inWorld(found->second) && back(holding)) {
            impl.holding = found->second;
            impl.wielding = hand.value("wielding", false);
            said.carried.hand = carrying;
        } else if (carrying && !holding.empty()) {
            lost.push_back("the hand: what it held, the " + holding + ", did not come back as it was, so the hand is "
                           "empty");
        }
    }
    // The clock and the counters, so what comes next is named and numbered
    // after what there is.
    impl.time_s = numberFrom(doc.at("t_s"));
    impl.advanceSun();   // a sun with a day stands where the world's clock puts it
    impl.steps_taken = doc.at("steps").get<std::uint64_t>();
    impl.last_dt_s = numberFrom(doc.at("last_dt_s"));
    impl.foresee_horizon_s = numberFrom(doc.at("foresee_horizon_s"));
    impl.survey_due = true;
    if (carrying) {
        LiveRestore::Carried &n = said.carried;
        n.placed = put_back.size();
        n.fresh = impl.described.size() - placements.size();
        n.heat = carried_heat;
        // Thing by thing, what did not come back as it was saved and why: this
        // scene's own things first -- changed, or not carried -- and then what
        // the scene no longer has.
        std::vector<char> spoken(plan.saved.size(), 0);
        const std::set<std::string> there(put_back.begin(), put_back.end());
        const auto savedPartNamed = [&](const std::vector<std::string> &names) {
            for (std::size_t t = 0; t < plan.saved.size(); ++t) {
                if (plan.saved[t].now != CarryPlan::npos || spoken[t] != 0) continue;
                for (const std::string &name : names)
                    if (std::find(plan.saved[t].bodies.begin(), plan.saved[t].bodies.end(), name) !=
                        plan.saved[t].bodies.end())
                        return t;
            }
            return CarryPlan::npos;
        };
        for (std::size_t g = 0; g < plan.carried.size(); ++g) {
            if (plan.carried[g] != 0 || impl.part_prints[g].bodies.empty()) continue;
            const std::string &lead = impl.part_prints[g].bodies.front();
            if (const std::size_t s = plan.saved_of[g]; s != CarryPlan::npos) {
                spoken[s] = 1;
                if (plan.bodies_of[s].empty()) continue;
                const bool returned = std::any_of(plan.bodies_of[s].begin(), plan.bodies_of[s].end(),
                                                  [&](const std::string &name) { return there.count(name) != 0; });
                std::string line = "the " + lead + ": " + plan.why[g] +
                                   (returned ? ", so it was put back where it was left, whole"
                                             : ", so it is as the room has it");
                if (plan.bodies_of[s].size() > 1)
                    line += " (it was in " + std::to_string(plan.bodies_of[s].size()) + " pieces)";
                said.not_carried.push_back(std::move(line));
                continue;
            }
            // Changed: the saved thing that had one of its names. Otherwise it
            // is new, and there is nothing to say.
            const std::size_t t = savedPartNamed(impl.part_prints[g].bodies);
            if (t == CarryPlan::npos) continue;
            spoken[t] = 1;
            if (plan.bodies_of[t].empty()) continue;
            said.not_carried.push_back("the " + lead + ": the room changed it, so it is as the room has it now" +
                                       std::string(plan.bodies_of[t].size() > 1 ? ", whole" : ""));
        }
        for (std::size_t t = 0; t < plan.saved.size(); ++t) {
            if (plan.saved[t].now != CarryPlan::npos || spoken[t] != 0 || plan.bodies_of[t].empty()) continue;
            n.gone += plan.bodies_of[t].size();
            said.not_carried.push_back("the " + (plan.saved[t].bodies.empty() ? plan.bodies_of[t].front()
                                                                              : plan.saved[t].bodies.front()) +
                                       ": the room no longer has it");
        }
        said.not_carried.insert(said.not_carried.end(), lost.begin(), lost.end());
        said.not_kept.insert(said.not_kept.begin(), said.not_carried.begin(), said.not_carried.end());
        said.woken = std::move(woken);
    }
    impl.restored = std::move(said);
    return live;
}

// Fills last_impacts and partner_of from the contacts of the step just taken,
// and answers whether any of them would break something.
bool LiveWorld::judgeStep() {
    impl_->last_impacts.clear();
    impl_->partner_of.clear();
    std::unordered_map<MatterBodyId, std::size_t> index_of_body;
    for (std::size_t i = 0; i < impl_->body_of.size(); ++i)
        index_of_body.emplace(impl_->body_of[i], i);
    bool any_would_break = false;
    std::set<std::string> breaking_now;
    std::unordered_map<std::size_t, double> worst_speed;
    impl_->blade_contacts.clear();
    std::set<MatterBodyId> blade_bodies;
    for (const Impl::Blade &blade : impl_->blades) {
        const auto holder = impl_->index_of.find(blade.body);
        if (blade.attached && holder != impl_->index_of.end())
            blade_bodies.insert(impl_->body_of[holder->second]);
    }
    for (const ImpactEvent &event : impl_->world->drainImpacts()) {
        // A blade's own contacts are kept for the cutting model, which reports
        // the ones that did not bite -- a flat strike, a glance -- from them.
        if (blade_bodies.count(event.body_a) || blade_bodies.count(event.body_b))
            impl_->blade_contacts.push_back(event);
        const auto a = index_of_body.find(event.body_a);
        const auto b = index_of_body.find(event.body_b);
        const bool a_known = a != index_of_body.end();
        const bool b_known = b != index_of_body.end();
        if (!a_known && !b_known) continue;
        const std::size_t pair[2] = {a_known ? a->second : b->second,
                                     b_known ? b->second : a->second};
        for (int which = 0; which < 2; ++which) {
            const std::size_t struck = pair[which];
            const std::size_t other = pair[1 - which];
            const bool both = a_known && b_known;
            if (which == 1 && !both) break;
            if (impl_->described[struck].anchored || impl_->precise_bodies.count(impl_->described[struck].name)) continue;
            // The ground is what it is made of where it was hit: a stone that
            // lands on sand meets soft ground, and one that lands on bare rock
            // meets stone. Judging every landing against the flat floor's
            // concrete shattered a boulder that rolled into a hole in sand.
            const bool on_terrain = impl_->environment &&
                                    (event.body_a == kGroundPatchMatterId || event.body_b == kGroundPatchMatterId);
            const double ground_impedance =
                on_terrain ? impl_->environment->contactImpedanceAt(event.contact_point_world_m)
                           : impl_->ground_impedance;
            const double other_impedance = both && other != struck
                                               ? impl_->impedance_of[other]
                                               : ground_impedance;
            const RefractureAdmission admission = admitRefracture(
                impl_->limits_of[struck], other_impedance,
                event.closing_speed_m_s, event.available_normal_energy_j);
            LiveImpact impact{};
            impact.struck = impl_->described[struck].name;
            impact.by = both && other != struck ? impl_->described[other].name
                                                : std::string("the ground");
            impact.closing_speed_m_s = event.closing_speed_m_s;
            impact.threshold_speed_m_s = admission.threshold_speed_m_s;
            impact.energy_j = event.available_normal_energy_j;
            impact.threshold_speed_m_s = admission.threshold_speed_m_s;
            impact.dent_speed_m_s = admission.yield_speed_m_s;
            impact.would_break = admission.admitted();
            impact.would_dent = admission.yields;
            // An exact rigid striker cannot go into the lattice run that would
            // answer this: the run has room for a static floor and one ball,
            // not a compound (LatticePhysics.hpp). Run without it, the answer
            // would be "held" for a reason that is not the physics; run with
            // it, the striker would be rebuilt from cells it does not have. So
            // the blow is judged against its real material, and when it would
            // need the run it is declined -- said, not hidden -- and the
            // contact stays Jolt's.
            const bool rigid_striker = both && other != struck && impl_->isPrecise(other);
            if (rigid_striker && admission.worthRunning())
                impact.declined = "struck by an exact rigid body, which the lattice run cannot hold yet";
            // Either one needs the lattice, and only the lattice can say which
            // of them actually happens. A trigger that asked about breaking
            // alone never ran below the breaking bar, which is exactly where a
            // dent lives.
            if (admission.worthRunning() && !rigid_striker) {
                breaking_now.insert(impact.struck);
                // Remember what hit it, for the island a fracture would build.
                // The hardest contact wins: a body resting on the floor and
                // struck by a ball reports both, and the ball is the one that
                // matters.
                double &worst = worst_speed[struck];
                if (impact.closing_speed_m_s >= worst) {
                    worst = impact.closing_speed_m_s;
                    impl_->partner_of[struck] =
                        both && other != struck ? other : static_cast<std::size_t>(-1);
                }
            }
            impl_->last_impacts.push_back(std::move(impact));
        }
    }

    // One body reports several contacts in a step -- a ball on a panel is also
    // resting on something, and most of those are gentle. Deciding "has this
    // already been tried" inside the event loop made the answer depend on the
    // order the events happened to arrive in: a gentle contact cleared the flag
    // that a hard one then set again, and the world stayed wedged even though
    // every part of the rule looked right. Decide it once, after all of them.
    // Keep them where the host can still find them after the batch.
    for (const LiveImpact &impact : impl_->last_impacts) {
        auto same = std::find_if(impl_->reported.begin(), impl_->reported.end(),
                                 [&](const LiveImpact &seen) {
                                     return seen.struck == impact.struck && seen.by == impact.by;
                                 });
        if (same == impl_->reported.end()) impl_->reported.push_back(impact);
        else if (impact.closing_speed_m_s > same->closing_speed_m_s) *same = impact;
    }

    // A body whose answer is already being worked out, or already captured and
    // waiting for a worker, is accounted for: stopping the world over it a
    // second time achieves nothing, because nobody can answer for it twice.
    //
    // `held_through` alone was not enough. It is cleared for any body that is
    // not in contact this step, and a captured body whose contact lapses for a
    // step and resumes was then treated as brand new -- it stopped the clock,
    // and queueBreaks skipped it because it was already in the queue, so
    // nothing cleared it and nothing could. Measured, that stalled the world for
    // 106 steps in a row with the capture working perfectly.
    const auto accounted = [&](const std::string &name) {
        if (impl_->pending && impl_->pending->name == name) return true;
        for (const auto &waiting : impl_->queued)
            if (waiting->name == name) return true;
        return false;
    };
    for (const std::string &name : breaking_now)
        if (impl_->held_through.count(name) == 0 && !accounted(name)) any_would_break = true;
    // A body that is no longer in danger from anything gets a fresh hearing the
    // next time something hits it hard.
    for (auto it = impl_->held_through.begin(); it != impl_->held_through.end();)
        it = breaking_now.count(*it) ? std::next(it) : impl_->held_through.erase(it);
    return any_would_break;
}

void LiveWorld::step(double dt_s) {
    if (!(dt_s > 0.0)) throw std::invalid_argument("a live step needs a positive dt");
    if (!impl_->circuits.empty()) impl_->validateCircuitStep(dt_s);

    // A held object goes back where the hand put it after the step. This is a
    // kinematic hold rather than a constraint: a world-fixed constraint
    // auto-detects its anchor from wherever the body was when it was made, so
    // it drags a moved body straight back, while re-asserting the pose has no
    // such memory and still lets a dragged object push what it runs into.
    // Whatever is waiting on a fracture stays put. The same kinematic hold the
    // hand uses: the pose is re-asserted after the step, so the body does not
    // move and does not accumulate speed, but still pushes what runs into it.
    // Everything waiting on an answer, running or queued. A queued body must be
    // pinned for the same reason a running one is: its pieces will be put back
    // where it was when it broke, so if it is allowed to bounce away first it
    // visibly springs back to the impact before it comes apart.
    const auto holdPending = [&]() {
        for (const std::size_t body : impl_->held_for_fracture) {
            if (body >= impl_->body_of.size()) continue;
            const MatterBodyId id = impl_->body_of[body];
            if (!impl_->world->contains(id)) continue;
            RigidSnapshot state = impl_->world->snapshot(id);
            state.linear_velocity_m_s = {};
            state.angular_velocity_rad_s = {};
            impl_->world->applyRigidState(id, state);
            impl_->world->wake(id);
        }
    };

    const auto holdStill = [&]() { carryOrHaul(dt_s); };

    // Where a stroke wants the grip for this step, and where the grip is, for
    // the work the step does. Before the grip's pull below, which is towards
    // exactly that.
    beginHandStep(dt_s);

    // The hand on a wielded grip: pulling AT the grip with a bounded force and
    // turning with a bounded torque, both towards where the hand wants the body
    // (docs/cutting-model.md section 7). Worked out once, from the world as the
    // step starts, and pushed INSIDE the step's reversible trial, so a step that
    // is taken back takes its push back with it and the retry pushes once.
    // Nothing here writes a pose: whatever the body meets can slow it, turn it
    // aside or stop it.
    struct HandPush {
        bool on{};
        MatterBodyId id{};
        Vec3 force{}, torque{}, grip{};
    };
    const HandPush hand = [&]() {
        HandPush out;
        if (!impl_->wielding || impl_->holding == static_cast<std::size_t>(-1)) return out;
        const MatterBodyId id = impl_->body_of[impl_->holding];
        if (!impl_->world->contains(id)) return out;
        const RigidMechanicalState held = impl_->world->mechanicalState(id);
        if (!(held.mass_kg > 0.0)) return out;
        // The law itself is gripPull, which previewStroke integrates too: a
        // preview of a throw and the throw must not disagree about the hand.
        const GripPull pull = gripPull(held, impl_->grip_local, impl_->held_at,
                                       impl_->held_velocity, impl_->held_facing,
                                       impl_->hand_strength_n, impl_->hand_torque_n_m,
                                       impl_->request.gravity_m_s2);
        out.on = true;
        out.id = id;
        out.force = pull.force;
        out.torque = pull.torque;
        out.grip = pull.grip;
        return out;
    }();
    // Which way the blade is being pushed, for the cut's rule at rest.
    impl_->hand_force = hand.on ? hand.force : Vec3{};
    const auto pushHand = [&]() {
        if (!hand.on) return;
        impl_->world->pushBodyAt(hand.id, hand.force, hand.grip);
        impl_->world->twistBody(hand.id, hand.torque);
        impl_->world->wake(hand.id);
    };

    // A step that would break something is taken back.

    //
    // Jolt resolves a contact within the step, so by the time the contact is
    // reported the energy has already gone into bouncing the two bodies apart.
    // Handing THAT state to the lattice is handing it a ball that has already
    // bounced: the island flies off with a uniform velocity, carries no stress
    // anywhere in it, and breaks nothing however hard it was hit -- measured,
    // as 171 ms of lattice that produced one piece. Rolling the step back
    // leaves the world one step short of the impact with the closing speed
    // intact, which is the state fracture() has to start from.
    //
    // runReversibleTrial caps out at 2,048 bodies. Past that the step is taken
    // straight; impacts are still reported, but they describe a collision that
    // has already been resolved, so fracture() will find nothing left to break.
    // That is a silent failure -- the room keeps running and simply stops
    // shattering -- so the ceiling is set where a room has to work to reach it
    // rather than where two broken panes reach it.
    impl_->stepped_back = false;
    impl_->last_dt_s = dt_s;
    ++impl_->steps_taken;

    // Heat, chemistry and gas step with the rigid world and on its clock.
    //
    // A pressure boundary pushes on its body INSIDE the trial, so a step that
    // is taken back takes the push back with it -- Jolt's recorded state holds
    // the force accumulator, and a push made outside would survive the rewind
    // and be applied again on the retry. After the rigid step the network is
    // advanced with how far each pushed body actually went, and charges the gas
    // exactly that force times that displacement. And if the step is refused,
    // the network is put back to where it was: the fuel the step would have
    // burned, the gas it would have made, the heat it would have moved.
    thermo::ThermoWorld *const network =
        impl_->thermo && impl_->thermo->active() ? impl_->thermo.get() : nullptr;
    std::optional<thermo::ThermoState> network_before;
    if (network != nullptr) network_before = network->state();
    struct Driven {
        std::string body;
        MatterBodyId id{};
        Vec3 from{};
    };
    std::vector<Driven> driven;
    const auto pushGas = [&]() {
        driven.clear();
        if (network == nullptr) return;
        for (const thermo::Push &push : network->pushes()) {
            const auto found = impl_->index_of.find(push.body);
            if (found == impl_->index_of.end()) continue;
            const MatterBodyId id = impl_->body_of[found->second];
            if (!impl_->world->contains(id)) continue;
            impl_->world->pushBody(id, push.force_n);
            driven.push_back({push.body, id, impl_->world->snapshot(id).center_of_mass_world_m});
        }
    };
    const auto advanceGas = [&]() {
        if (network == nullptr) return;
        std::vector<thermo::Moved> moved;
        moved.reserve(driven.size());
        for (const Driven &d : driven)
            moved.push_back({d.body, impl_->world->snapshot(d.id).center_of_mass_world_m - d.from});
        network->advance(dt_s, moved);
    };
    // Terrain and water, the same way round: the water's pressure and drag are
    // pushed inside the trial, so a refused step takes them back; the water,
    // the ground and its colliders move on only once the step is accepted.
    terrain::Environment *const environment = impl_->environment.get();
    const auto pushWater = [&]() {
        if (environment != nullptr) environment->push(*impl_->world, waterBodies());
    };
    const auto settleEnvironment = [&]() {
        if (environment != nullptr) environment->commit(*impl_->world, waterBodies(), dt_s);
    };

    // Edges first. Where one is about to meet matter, or is already in it, the
    // kerf constraint that stands in for the material has to be in place before
    // the solver moves anything -- and it changes the world's configuration,
    // which a reversible trial forbids, so it goes before the trial opens.
    // docs/cutting-model.md.
    prepareCuts(dt_s);
    // A tool's point at the ground, the same way round: its bite -- the
    // ground's resistance at the depth it has reached -- is set before the
    // trial, because making or changing it changes the world's configuration.
    if (!impl_->tools.empty()) impl_->tools.prepare(toolHost(), dt_s);
    // A motor's drive, the same way round: set before the trial, from its line
    // at the speed its pin has now (docs/machine-world.md) -- after its
    // controller, if it has one, has said what the motor is to do this step.
    if (!impl_->programs.empty()) impl_->preparePrograms();
    if (!impl_->controls.empty()) impl_->prepareControls(dt_s);
    if (!impl_->motors.empty()) impl_->prepareMotors(dt_s);
    if (!impl_->circuits.empty()) impl_->prepareCircuits(dt_s);
    if (impl_->body_of.size() + 8 <= 2000) {
        bool committed = false;
        try {
            committed = impl_->world->runReversibleTrial([&]() {
                pushGas();
                pushHand();
                pushWater();
                impl_->pushCircuits();
                impl_->world->step(dt_s);
                holdStill();
                holdPending();
                if (judgeStep()) return false;
                advanceGas();
                return true;
            });
        } catch (...) {
            if (network != nullptr) network->restore(*network_before);
            throw;
        }
        if (!committed && network != nullptr) network->restore(*network_before);
        impl_->stepped_back = !committed;
        // A step that was taken back did not happen, so the clock does not move
        // and the hold does not need re-asserting -- the world is as it was.
        //
        // That is the handshake, and it is right when the host can answer. It is
        // NOT right when something is already being worked out: the host asking
        // for a second fracture gets nothing back, so nobody can resolve this
        // break and the world sits at one instant for as long as the first run
        // takes. Measured in the owner's own session: 756 ms of wall clock in
        // which the world advanced 0 ms, and again 750 ms for 10 ms, in a
        // cascade that came out at 40% of real time with nothing "blocked".
        //
        // So take the break now instead of waiting to be asked. Right here the
        // world is one step short of the impact with the closing speed intact,
        // which is exactly the state the host would have handed back, and
        // preparing is a copy -- it is the RUN that costs a third of a second.
        // Preparing also records the name as heard, so the next step commits
        // and the clock moves again.
        if (!committed) {
            // The step did not happen, so neither did the hand's part of it.
            abandonHandStep();
            if (impl_->pending) queueBreaks();
            return;
        }
        impl_->time_s += dt_s;
        impl_->advanceSun();
        impl_->rememberJointAngles(*impl_->world);
        // What each motor did, once the step is kept: a refused step takes
        // nothing from a store.
        if (!impl_->motors.empty()) impl_->settleMotors(dt_s);
        if (!impl_->circuits.empty()) impl_->settleCircuits(dt_s);
        if (!impl_->panels.empty()) impl_->settlePanels(dt_s);
        if (!impl_->controls.empty()) impl_->settleControls(dt_s);
        if (!impl_->programs.empty()) impl_->settlePrograms(dt_s);
        // What each edge took this step, the kerfs it bought, and whatever came
        // apart. After the trial, for the same reason prepareCuts is before it.
        settleCuts(dt_s);
        // What each point in the ground took this step, and a point that has
        // come out takes what it broke loose out of the ground with it.
        if (!impl_->tools.empty()) impl_->tools.settle(toolHost(), dt_s);
        partOverloadedLinks();
        // Load does not change in a quarter of a second, and the survey is
        // O(bodies squared). Sixty times a second would be waste; four is not.
        // Unless heat has changed what something can carry: then the load that
        // has not moved is asked about again now, because the section under it
        // has.
        if (impl_->steps_taken % 60 == 0 || impl_->survey_due) {
            impl_->survey_due = false;
            surveyLoads();
        }
        foresee();
        settleThermo();
        settleEnvironment();
        // Last, because a stroke that has got to its end opens the hand, and
        // everything above still has to see the step as it was taken.
        endHandStep(hand.force, hand.torque, dt_s);
        return;
    }
    pushGas();
    pushHand();
    pushWater();
    impl_->pushCircuits();
    impl_->world->step(dt_s);
    holdStill();
    holdPending();
    (void)judgeStep();
    advanceGas();
    impl_->time_s += dt_s;
    impl_->advanceSun();
    impl_->rememberJointAngles(*impl_->world);
    if (!impl_->motors.empty()) impl_->settleMotors(dt_s);
    if (!impl_->circuits.empty()) impl_->settleCircuits(dt_s);
    if (!impl_->panels.empty()) impl_->settlePanels(dt_s);
    if (!impl_->controls.empty()) impl_->settleControls(dt_s);
    if (!impl_->programs.empty()) impl_->settlePrograms(dt_s);
    settleCuts(dt_s);
    if (!impl_->tools.empty()) impl_->tools.settle(toolHost(), dt_s);
    partOverloadedLinks();
    if (impl_->steps_taken % 60 == 0 || impl_->survey_due) {
        impl_->survey_due = false;
        surveyLoads();
    }
    foresee();
    settleThermo();
    settleEnvironment();
    endHandStep(hand.force, hand.torque, dt_s);
}

// Part every link carrying more than it can take.
//
// A rope that cannot fail is a rope that will hold a cathedral up, and the
// whole point of a hoist is that you have to think about what you hang on it.
// So a link with a breaking tension is checked against what the solver actually
// applied on the step just taken -- not against a guess from the load, which
// would miss the shock of something being dropped on the end of it.
//
// The link goes, and says so: `attached` turns false and stays in the list for
// one report, the same as a gate coming off its hinges, because a host that drew
// a rope has to be told to stop drawing it. What was hanging on it falls.
void LiveWorld::partOverloadedLinks() {
    // Less than this is not a load. A fixing at rest reports around 1e-17 N
    // along an axis nothing pulls on, and a member burned to nothing -- which
    // holds exactly zero -- must not part on that.
    constexpr double kNoLoadN = 1.0e-6;
    // How far b can slide along a one-way fixing and still be on it. A nock's
    // throat is a few millimetres deep; past that the string is out of it and
    // there is nothing left of the fixing around what it held.
    constexpr double kThroatM = 0.005;
    for (Impl::SceneJoint &joint : impl_->joints) {
        const bool a_link = joint.kind == JoltWorld::JointKind::Link;
        const bool a_fixing = joint.kind == JoltWorld::JointKind::Fixing;
        if (!a_link && !a_fixing) continue;
        if (!joint.attached || joint.rigid == 0) continue;
        if (!impl_->world->hasJoint(joint.rigid)) continue;
        // A joint made of a member can lose everything it held, and then zero
        // is a strength -- it holds nothing -- not the weld a declared zero is.
        const bool rated = joint.member_end >= 0;

        double carrying = 0.0, bar = 0.0, cold = 0.0;
        const char *how = "pulled apart";
        const char *what = a_fixing ? "gave way" : "parted";
        if (a_fixing) {
            // Two bounds, checked separately, because a peg pulled straight out
            // and a peg sheared sideways fail at different loads. Whichever is
            // the nearer to giving is the one that decides.
            const bool one_way = joint.comes_off_n > 0.0;
            if (!rated && !one_way && !(joint.holds_tension_n > 0.0) &&
                !(joint.holds_shear_n > 0.0))
                continue;
            const auto found = impl_->index_of.find(joint.a);
            const Vec3 along =
                found != impl_->index_of.end()
                    ? impl_->world->snapshot(impl_->body_of[found->second])
                          .orientation_world.rotate(joint.axis_local_a)
                    : joint.axis_local_a;
            const JoltWorld::JointLoad load = impl_->world->jointLoad(joint.rigid, along);
            // One-way, what pulls it along its axis is its grip and never a
            // tension strength -- not even one a member's law would give it.
            const bool pulled_apart = !one_way && (rated || joint.holds_tension_n > 0.0) &&
                                      load.tension_n > kNoLoadN &&
                                      load.tension_n > joint.holds_tension_n;
            const bool sheared = (rated || joint.holds_shear_n > 0.0) &&
                                 load.shear_n > kNoLoadN &&
                                 load.shear_n > joint.holds_shear_n;
            // A one-way fixing is never overloaded along its axis, because it
            // cannot be: it holds with up to comes_off_n and whatever pulls
            // harder slides b off it. It is OFF once b has slid further than
            // the throat -- measured between the two points it was made at.
            bool came_off = false;
            const auto other = impl_->index_of.find(joint.b);
            if (one_way && !sheared && found != impl_->index_of.end() &&
                other != impl_->index_of.end()) {
                const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[found->second]);
                const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[other->second]);
                const Vec3 here = one.center_of_mass_world_m +
                                  one.orientation_world.rotate(joint.point_local_a);
                const Vec3 there = two.center_of_mass_world_m +
                                   two.orientation_world.rotate(joint.point_local_b);
                came_off = dot(there - here, along) > kThroatM;
            }
            if (!pulled_apart && !sheared && !came_off) continue;
            if (came_off) {
                what = "came off";
                how = "came off along its axis";
                carrying = std::max(0.0, -load.axial_n);
                bar = joint.comes_off_n;
                cold = joint.comes_off_n;
            } else {
                carrying = pulled_apart ? load.tension_n : load.shear_n;
                bar = pulled_apart ? joint.holds_tension_n : joint.holds_shear_n;
                cold = pulled_apart ? joint.rated_tension_n : joint.rated_shear_n;
                how = pulled_apart ? "pulled out along its axis" : "sheared across its axis";
            }
        } else {
            if (!rated && !(joint.breaks_at_n > 0.0)) continue;
            carrying = impl_->world->jointTension(joint.rigid);
            if (!(carrying > kNoLoadN) || carrying <= joint.breaks_at_n) continue;
            bar = joint.breaks_at_n;
            cold = joint.rated_breaks_at_n;
        }
        impl_->world->removeJoint(joint.rigid);
        joint.rigid = 0;
        joint.attached = false;
        // Why, in the numbers that decided it: the load the solver measured
        // against what the joint could still take -- and, for one made of a
        // member, what heat had left of that member.
        joint.parted_load_n = carrying;
        joint.parted_capacity_n = bar;
        if (std::string(what) == "came off")
            // A one-way fixing coming off is what it is for, not a failure: it
            // held on with all the grip it has, and something pulled harder.
            joint.parted_because = std::string(how) + ", holding " + newtons(carrying) +
                                   " -- all the " + newtons(bar) + " it grips with";
        else
            joint.parted_because = std::string(how) + ": carrying " + newtons(carrying) +
                                   " against the " + newtons(bar) +
                                   (rated ? " it could still take (" + newtons(cold) + " cold) -- " +
                                                joint.member_said
                                          : std::string(" it was declared to hold"));
        impl_->delays.push_back({impl_->time_s, joint.a + " to " + joint.b, what,
                                 carrying, bar});
        // Both ends have to wake or what was hanging there stays hanging in the
        // air until something else disturbs it.
        for (const std::string &side : {joint.a, joint.b}) {
            const auto found = impl_->index_of.find(side);
            if (found != impl_->index_of.end())
                impl_->world->wake(impl_->body_of[found->second]);
        }
    }
    // A weld that let go between two exact bodies leaves them to meet as
    // their surfaces again.
    impl_->settleJointedContacts();
}

double LiveWorld::time_s() const { return impl_->time_s; }
std::size_t LiveWorld::bodies() const {
    // What poses() lists: a thing set aside (park) is not in the world.
    if (impl_->parked.empty()) return impl_->described.size();
    std::size_t in_world = 0;
    for (std::size_t i = 0; i < impl_->described.size(); ++i)
        if (!impl_->isParked(i)) ++in_world;
    return in_world;
}

double LiveWorld::cellSize() const { return impl_->request.cell_size_m; }

namespace {
// A quaternion's conjugate, which is its inverse for the unit quaternions a
// rigid body carries. Quat has rotate() but no inverse, and taking a world
// vector into a body's own frame needs one on every call below.
[[nodiscard]] Quat conjugateOf(const Quat &q) { return Quat{q.w, -q.x, -q.y, -q.z}; }
// b and then a: the Hamilton product a b, which turns a vector by b first.
// Quat carries no product either.
[[nodiscard]] Quat compose(const Quat &a, const Quat &b) {
    return Quat{a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
                a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
                a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
                a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w};
}
} // namespace

std::vector<LiveBodyPose> LiveWorld::poses(bool with_geometry) const {
    std::vector<LiveBodyPose> out = impl_->described;
    for (std::size_t i = 0; i < out.size(); ++i) {
        // Said of the body that is there. A whole box or ball built turned
        // carries its turn inside its collision shape and not in its rigid pose
        // (Impl::shapeTurn), so which way it faces is that pose with the turn
        // on top, and what is in its own frame -- its dent, its cuts -- comes
        // off the rigid frame by the same turn. Until this, a box built at any
        // rotation_deg was said to face no way at all: a host drew it square
        // while it collided turned.
        const Quat turn = impl_->shapeTurn(i);
        const Quat back = conjugateOf(turn);
        out[i].dent_at_m = back.rotate(out[i].dent_at_m);
        if (with_geometry && out[i].shape == "hull") {
            out[i].cells_local_m.reserve(impl_->nodes_of[i].size());
            for (const std::uint32_t node : impl_->nodes_of[i])
                out[i].cells_local_m.push_back(impl_->cell_offset_m[node]);
        }
        // The cuts it carries. They change while a blade works, so they are read
        // every time rather than kept with the parts that do not.
        if (const auto carried = impl_->kerfs.find(out[i].name); carried != impl_->kerfs.end()) {
            for (const Impl::Kerf &kerf : carried->second) {
                if (kerf.swept.empty()) continue;
                LiveBodyPose::Kerf drawn{};
                drawn.point_local_m = back.rotate(kerf.origin);
                drawn.along_local = back.rotate(kerf.u);
                drawn.facing_local = back.rotate(kerf.v);
                drawn.normal_local = back.rotate(kerf.w);
                drawn.thickness_m = 2.0 * (kerf.half_width - 0.001);
                for (const auto &[strip, spans] : kerf.swept)
                    for (const auto &span : spans)
                        drawn.strips.push_back({strip * kerf.strip, (strip + 1) * kerf.strip,
                                                span.first, span.second});
                out[i].kerfs.push_back(std::move(drawn));
            }
        }
        if (!impl_->world->contains(impl_->body_of[i])) continue;
        const RigidSnapshot snap = impl_->world->snapshot(impl_->body_of[i]);
        out[i].position_m = snap.center_of_mass_world_m;
        const Quat facing = compose(snap.orientation_world, turn);
        out[i].orientation_wxyz[0] = facing.w;
        out[i].orientation_wxyz[1] = facing.x;
        out[i].orientation_wxyz[2] = facing.y;
        out[i].orientation_wxyz[3] = facing.z;
        out[i].velocity_m_s = snap.linear_velocity_m_s;
        out[i].mass_kg = out[i].anchored ? 0.0
                                         : impl_->world->mechanicalState(impl_->body_of[i]).mass_kg;
        out[i].held = i == impl_->holding;
    }
    // A thing set aside (park) is not in the world, so it is not said to be
    // anywhere: a host that drew it stops drawing it, and names it gone.
    if (!impl_->parked.empty())
        std::erase_if(out, [&](const LiveBodyPose &pose) { return impl_->parked.count(pose.name) != 0; });
    return out;
}

unsigned LiveWorld::hinge(const std::string &a, const std::string &b,
                          const Vec3 &point_world_m, const Vec3 &axis_world,
                          double lower_deg, double upper_deg,
                          double friction_torque_n_m) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    // A thing set aside (park) is not in the world to be joined to anything.
    if (!impl_->inWorld(first->second) || !impl_->inWorld(second->second)) return 0;
    const double reach = length(axis_world);
    if (!(reach > 1e-9)) return 0;

    constexpr double kPi = 3.14159265358979323846;
    const double lower = std::max(-kPi, std::min(0.0, lower_deg * kPi / 180.0));
    const double upper = std::min(kPi, std::max(0.0, upper_deg * kPi / 180.0));

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Hinge;
    joint.lower = lower;
    joint.upper = upper;
    joint.friction = std::max(0.0, friction_torque_n_m);

    // Write the pin down in each body's own frame. Where they are standing at
    // this moment is the only thing that ties the two together, and after this
    // it never matters again.
    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_world_m - one.center_of_mass_world_m);
    joint.point_local_b = conjugateOf(two.orientation_world)
                              .rotate(point_world_m - two.center_of_mass_world_m);
    joint.axis_local_a = conjugateOf(one.orientation_world).rotate((1.0 / reach) * axis_world);
    // And how far it stands off each body's matter, which is what the pieces
    // of either are measured against if it breaks (bodyHolding).
    joint.stand_off_a = impl_->standOff(first->second, joint.point_local_a);
    joint.stand_off_b = impl_->standOff(second->second, joint.point_local_b);

    try {
        JoltWorld::HingeDescription pin{};
        pin.a = impl_->body_of[first->second];
        pin.b = impl_->body_of[second->second];
        pin.point_world_m = point_world_m;
        pin.axis_world = (1.0 / reach) * axis_world;
        pin.lower_rad = lower;
        pin.upper_rad = upper;
        pin.friction_torque_n_m = joint.friction;
        joint.rigid = impl_->world->addHinge(pin);
    } catch (const std::exception &) {
        return 0;
    }
    // Two things hung on a pin are touching by definition -- that is what being
    // hinged IS -- and a body that has been asleep does not notice a push.
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    impl_->settleJointedContacts();
    return impl_->joints.back().id;
}

unsigned LiveWorld::slide(const std::string &a, const std::string &b,
                          const Vec3 &point_world_m, const Vec3 &axis_world,
                          double lower_m, double upper_m, double friction_n) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    // A thing set aside (park) is not in the world to be joined to anything.
    if (!impl_->inWorld(first->second) || !impl_->inWorld(second->second)) return 0;
    const double reach = length(axis_world);
    if (!(reach > 1e-9)) return 0;
    if (!(lower_m <= 0.0) || !(upper_m >= 0.0)) return 0;

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Slider;
    joint.lower = lower_m;
    joint.upper = upper_m;
    joint.friction = std::max(0.0, friction_n);

    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_world_m - one.center_of_mass_world_m);
    joint.point_local_b = conjugateOf(two.orientation_world)
                              .rotate(point_world_m - two.center_of_mass_world_m);
    joint.axis_local_a = conjugateOf(one.orientation_world).rotate((1.0 / reach) * axis_world);
    joint.stand_off_a = impl_->standOff(first->second, joint.point_local_a);
    joint.stand_off_b = impl_->standOff(second->second, joint.point_local_b);

    try {
        JoltWorld::SliderDescription groove{};
        groove.a = impl_->body_of[first->second];
        groove.b = impl_->body_of[second->second];
        groove.point_world_m = point_world_m;
        groove.axis_world = (1.0 / reach) * axis_world;
        groove.lower_m = lower_m;
        groove.upper_m = upper_m;
        groove.friction_n = joint.friction;
        joint.rigid = impl_->world->addSlider(groove);
    } catch (const std::exception &) {
        return 0;
    }
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    impl_->settleJointedContacts();
    return impl_->joints.back().id;
}

unsigned LiveWorld::tie(const std::string &a, const std::string &b,
                        const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                        double length_m, double breaking_tension_n) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    // A thing set aside (park) is not in the world to be joined to anything.
    if (!impl_->inWorld(first->second) || !impl_->inWorld(second->second)) return 0;

    // "As they stand" is the ordinary case: a rope laid out and then tied does
    // not want to be told its own length, and getting it wrong by a millimetre
    // either way is either a rope under tension at rest or one that sags.
    const double apart = length(point_b_world_m - point_a_world_m);
    const double ties_at = length_m > 0.0 ? length_m : std::max(apart, 1e-4);

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Link;
    joint.lower = 0.0;
    joint.upper = ties_at;
    joint.friction = 0.0;
    joint.breaks_at_n = std::max(0.0, breaking_tension_n);

    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_a_world_m - one.center_of_mass_world_m);
    joint.point_local_b_tie = conjugateOf(two.orientation_world)
                                  .rotate(point_b_world_m - two.center_of_mass_world_m);
    // A link has no axis. The end that follows its material still needs the
    // other body's local point, and point_local_b is what rehangJoints reads.
    joint.point_local_b = joint.point_local_b_tie;
    joint.axis_local_a = Vec3{0.0, 1.0, 0.0};
    joint.stand_off_a = impl_->standOff(first->second, joint.point_local_a);
    joint.stand_off_b = impl_->standOff(second->second, joint.point_local_b);

    try {
        JoltWorld::LinkDescription rope{};
        rope.a = impl_->body_of[first->second];
        rope.b = impl_->body_of[second->second];
        rope.point_a_world_m = point_a_world_m;
        rope.point_b_world_m = point_b_world_m;
        rope.length_m = ties_at;
        rope.breaking_tension_n = joint.breaks_at_n;
        joint.rigid = impl_->world->addLink(rope);
    } catch (const std::exception &) {
        return 0;
    }
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    return impl_->joints.back().id;
}

unsigned LiveWorld::spring(const std::string &a, const std::string &b,
                           const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                           double rest_m, double stiffness_n_m, double damping_n_s_m) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    // A thing set aside (park) is not in the world to be joined to anything.
    if (!impl_->inWorld(first->second) || !impl_->inWorld(second->second)) return 0;
    if (!(stiffness_n_m > 0.0) || !(damping_n_s_m >= 0.0) || !(rest_m >= 0.0)) return 0;

    const double apart = length(point_b_world_m - point_a_world_m);

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Elastic;
    joint.rest_m = rest_m > 0.0 ? rest_m : std::max(apart, 1e-4);
    joint.stiffness_n_m = stiffness_n_m;
    joint.damping_n_s_m = damping_n_s_m;
    joint.lower = joint.rest_m;
    joint.upper = joint.rest_m;

    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_a_world_m - one.center_of_mass_world_m);
    joint.point_local_b_tie = conjugateOf(two.orientation_world)
                                  .rotate(point_b_world_m - two.center_of_mass_world_m);
    joint.point_local_b = joint.point_local_b_tie;
    joint.axis_local_a = Vec3{0.0, 1.0, 0.0};
    joint.stand_off_a = impl_->standOff(first->second, joint.point_local_a);
    joint.stand_off_b = impl_->standOff(second->second, joint.point_local_b);

    try {
        JoltWorld::ElasticDescription limb{};
        limb.a = impl_->body_of[first->second];
        limb.b = impl_->body_of[second->second];
        limb.point_a_world_m = point_a_world_m;
        limb.point_b_world_m = point_b_world_m;
        limb.rest_m = joint.rest_m;
        limb.stiffness_n_m = stiffness_n_m;
        limb.damping_n_s_m = damping_n_s_m;
        joint.rigid = impl_->world->addElastic(limb);
    } catch (const std::exception &) {
        return 0;
    }
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    return impl_->joints.back().id;
}

unsigned LiveWorld::fix(const std::string &a, const std::string &b,
                        const Vec3 &point_world_m, const Vec3 &axis_world,
                        double holds_tension_n, double holds_shear_n,
                        double comes_off_n) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    // A thing set aside (park) is not in the world to be joined to anything.
    if (!impl_->inWorld(first->second) || !impl_->inWorld(second->second)) return 0;
    const double reach = length(axis_world);
    if (!(reach > 1e-9)) return 0;
    if (!(holds_tension_n >= 0.0) || !(holds_shear_n >= 0.0)) return 0;
    // One-way, it has no tension strength: what pulls it apart is comes_off_n.
    if (!(comes_off_n >= 0.0) || !std::isfinite(comes_off_n)) return 0;
    if (comes_off_n > 0.0 && holds_tension_n > 0.0) return 0;

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Fixing;
    joint.holds_tension_n = holds_tension_n;
    joint.holds_shear_n = holds_shear_n;
    joint.comes_off_n = comes_off_n;

    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_world_m - one.center_of_mass_world_m);
    joint.point_local_b = conjugateOf(two.orientation_world)
                              .rotate(point_world_m - two.center_of_mass_world_m);
    joint.point_local_b_tie = joint.point_local_b;
    joint.axis_local_a = conjugateOf(one.orientation_world).rotate((1.0 / reach) * axis_world);
    joint.stand_off_a = impl_->standOff(first->second, joint.point_local_a);
    joint.stand_off_b = impl_->standOff(second->second, joint.point_local_b);

    try {
        JoltWorld::FixingDescription peg{};
        peg.a = impl_->body_of[first->second];
        peg.b = impl_->body_of[second->second];
        peg.point_world_m = point_world_m;
        peg.axis_world = (1.0 / reach) * axis_world;
        peg.holds_tension_n = holds_tension_n;
        peg.holds_shear_n = holds_shear_n;
        peg.comes_off_n = comes_off_n;
        joint.rigid = impl_->world->addFixing(peg);
    } catch (const std::exception &) {
        return 0;
    }
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    impl_->settleJointedContacts();
    return impl_->joints.back().id;
}

unsigned LiveWorld::reeve(const std::string &a, const std::string &b,
                          const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                          const Vec3 &over_a_world_m, const Vec3 &over_b_world_m,
                          double ratio, double length_m) {
    const auto first = impl_->index_of.find(a);
    const auto second = impl_->index_of.find(b);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    // A thing set aside (park) is not in the world to be joined to anything.
    if (!impl_->inWorld(first->second) || !impl_->inWorld(second->second)) return 0;
    if (!(ratio > 0.0) || !(length_m >= 0.0)) return 0;

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = a;
    joint.b = b;
    joint.kind = JoltWorld::JointKind::Pulley;
    joint.over_a = over_a_world_m;
    joint.over_b = over_b_world_m;
    joint.ratio = ratio;
    joint.lower = 0.0;
    joint.upper = length_m > 0.0
                      ? length_m
                      : length(point_a_world_m - over_a_world_m) +
                            ratio * length(point_b_world_m - over_b_world_m);
    joint.friction = 0.0;

    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world)
                              .rotate(point_a_world_m - one.center_of_mass_world_m);
    joint.point_local_b_tie = conjugateOf(two.orientation_world)
                                  .rotate(point_b_world_m - two.center_of_mass_world_m);
    joint.point_local_b = joint.point_local_b_tie;
    joint.axis_local_a = Vec3{0.0, 1.0, 0.0};
    joint.stand_off_a = impl_->standOff(first->second, joint.point_local_a);
    joint.stand_off_b = impl_->standOff(second->second, joint.point_local_b);

    try {
        JoltWorld::PulleyDescription rove{};
        rove.a = impl_->body_of[first->second];
        rove.b = impl_->body_of[second->second];
        rove.point_a_world_m = point_a_world_m;
        rove.point_b_world_m = point_b_world_m;
        rove.over_a_world_m = over_a_world_m;
        rove.over_b_world_m = over_b_world_m;
        rove.ratio = ratio;
        rove.length_m = length_m;
        joint.rigid = impl_->world->addPulley(rove);
    } catch (const std::exception &) {
        return 0;
    }
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    return impl_->joints.back().id;
}

std::vector<LiveJoint> LiveWorld::joints() const {
    std::vector<LiveJoint> out;
    out.reserve(impl_->joints.size());
    for (const Impl::SceneJoint &joint : impl_->joints) {
        LiveJoint said{};
        said.id = joint.id;
        said.kind = joint.kind == JoltWorld::JointKind::Slider   ? "slider"
                    : joint.kind == JoltWorld::JointKind::Link   ? "link"
                    : joint.kind == JoltWorld::JointKind::Pulley ? "pulley"
                    : joint.kind == JoltWorld::JointKind::Fixing ? "fixing"
                    : joint.kind == JoltWorld::JointKind::Elastic ? "elastic"
                    : joint.kind == JoltWorld::JointKind::Drum    ? "drum"
                                                                 : "hinge";
        said.rest_m = joint.rest_m;
        said.stiffness_n_m = joint.stiffness_n_m;
        said.damping_n_s_m = joint.damping_n_s_m;
        said.holds_tension_n = joint.holds_tension_n;
        said.holds_shear_n = joint.holds_shear_n;
        said.comes_off_n = joint.comes_off_n;
        said.breaks_at_n = joint.breaks_at_n;
        said.ratio = joint.ratio;
        said.over_a_m = joint.over_a;
        said.over_b_m = joint.over_b;
        said.a = joint.a;
        said.b = joint.b;
        said.lower = joint.lower;
        said.upper = joint.upper;
        said.friction = joint.friction;
        // Away with the thing it is in, it is still in it: attached, reading
        // what it read as it went, and made again when the thing is back.
        said.away = impl_->setAside(joint);
        said.attached = joint.attached && (joint.rigid != 0 || said.away);
        if (said.away) said.at = joint.at_when_hung;
        if (joint.rigid != 0 && impl_->world->hasJoint(joint.rigid)) {
            const JoltWorld::JointReport now = impl_->world->jointState(joint.rigid);
            said.at = now.at;
            said.lower = now.lower;
            said.upper = now.upper;
            said.friction = now.friction;
            said.tension_n = impl_->world->jointTension(joint.rigid);
            if (joint.kind == JoltWorld::JointKind::Drum) {
                const JoltWorld::DrumReport rope = impl_->world->drumState(joint.rigid);
                said.radius_m = joint.radius_m;
                said.winds = joint.winds;
                said.wound_m = rope.wound_m;
                said.leaves_m = rope.leaves_m;
                said.meets_m = rope.meets_m;
            }
            if (joint.kind == JoltWorld::JointKind::Elastic) {
                // How far apart the two ATTACHMENT POINTS are, worked out from
                // where the bodies now stand. Not their centres: a bow limb
                // pulls on the end of the limb, and using the centres would be
                // a different machine reporting the same name.
                const auto at_a = impl_->index_of.find(joint.a);
                const auto at_b = impl_->index_of.find(joint.b);
                if (at_a != impl_->index_of.end() && at_b != impl_->index_of.end()) {
                    const RigidSnapshot one =
                        impl_->world->snapshot(impl_->body_of[at_a->second]);
                    const RigidSnapshot two =
                        impl_->world->snapshot(impl_->body_of[at_b->second]);
                    const Vec3 here = one.center_of_mass_world_m +
                                      one.orientation_world.rotate(joint.point_local_a);
                    const Vec3 there = two.center_of_mass_world_m +
                                       two.orientation_world.rotate(joint.point_local_b_tie);
                    said.at = length(there - here);
                }
                const double stretched = said.at - joint.rest_m;
                said.force_n = joint.stiffness_n_m * stretched;
                said.stored_j = 0.5 * joint.stiffness_n_m * stretched * stretched;
                said.tension_n = std::abs(said.force_n);
            }
            if (joint.kind == JoltWorld::JointKind::Fixing) {
                const auto found = impl_->index_of.find(joint.a);
                const Vec3 along =
                    found != impl_->index_of.end()
                        ? impl_->world->snapshot(impl_->body_of[found->second])
                              .orientation_world.rotate(joint.axis_local_a)
                        : joint.axis_local_a;
                const JoltWorld::JointLoad carrying =
                    impl_->world->jointLoad(joint.rigid, along);
                said.tension_n_now = carrying.tension_n;
                said.shear_n_now = carrying.shear_n;
                // One number for a host that only wants "how hard is this
                // working": whichever of the two is nearer its own limit.
                said.tension_n = std::max(carrying.tension_n, carrying.shear_n);
            }
        }
        // Where the pin has got to, worked out from the body it is in rather
        // than remembered, so a gate that has been carried across the room
        // reports its hinge where the gate is. Not from a body that is not in
        // the world: one set aside (park) is nowhere to say it from.
        const auto found = impl_->index_of.find(joint.a);
        if (found != impl_->index_of.end() && impl_->inWorld(found->second)) {
            const RigidSnapshot at = impl_->world->snapshot(impl_->body_of[found->second]);
            said.point_world_m = at.center_of_mass_world_m +
                                 at.orientation_world.rotate(joint.point_local_a);
            said.axis_world = at.orientation_world.rotate(joint.axis_local_a);
        }
        // What it is made of, what it could take cold, and what is left.
        if (joint.member_end >= 0) said.member = joint.member_end == 0 ? joint.a : joint.b;
        said.rated_tension_n = joint.rated_tension_n;
        said.rated_shear_n = joint.rated_shear_n;
        said.rated_breaks_at_n = joint.rated_breaks_at_n;
        said.rated_stiffness_n_m = joint.rated_stiffness_n_m;
        said.capacity_fraction = joint.member_end >= 0 ? joint.capacity_fraction : 1.0;
        said.rechecks = joint.rechecks;
        said.parted_because = joint.parted_because;
        said.parted_load_n = joint.parted_load_n;
        said.parted_capacity_n = joint.parted_capacity_n;
        out.push_back(std::move(said));
    }
    return out;
}

unsigned LiveWorld::energyStore(const std::string &name, const std::string &body, double capacity_j,
                                double charge_j, double voltage_v, double max_power_w) {
    if (!body.empty() && impl_->index_of.find(body) == impl_->index_of.end()) return 0;
    if (!(capacity_j > 0.0) || !std::isfinite(capacity_j) || !(charge_j >= 0.0) || charge_j > capacity_j ||
        !(voltage_v > 0.0) || !std::isfinite(voltage_v) || !(max_power_w >= 0.0) || !std::isfinite(max_power_w))
        return 0;
    LiveEnergyStore store{};
    store.id = impl_->next_energy_store++;
    store.name = name.empty() ? "store " + std::to_string(store.id) : name;
    store.body = body;
    store.capacity_j = capacity_j;
    store.charge_j = charge_j;
    store.voltage_v = voltage_v;
    store.max_power_w = max_power_w;
    impl_->energy_stores.push_back(store);
    return store.id;
}

unsigned LiveWorld::motor(unsigned joint, unsigned store, double stall_torque_n_m, double no_load_rad_s,
                          double brake_torque_n_m, double rotor_thrust_n_per_rad2, double rotor_drag_n_m_per_rad2) {
    if (!(rotor_thrust_n_per_rad2 >= 0.0) || !std::isfinite(rotor_thrust_n_per_rad2) ||
        !(rotor_drag_n_m_per_rad2 >= 0.0) || !std::isfinite(rotor_drag_n_m_per_rad2))
        return 0;
    for (const auto &c : impl_->circuits) if (c.store() == store) return 0;
    const Impl::SceneJoint *pin = impl_->motorPin(joint);
    if (pin == nullptr || pin->kind != JoltWorld::JointKind::Hinge) return 0;
    if (impl_->energyStoreById(store) == nullptr) return 0;
    if (!(stall_torque_n_m > 0.0) || !std::isfinite(stall_torque_n_m) || !(no_load_rad_s > 0.0) ||
        !std::isfinite(no_load_rad_s) || !(brake_torque_n_m >= 0.0) || !std::isfinite(brake_torque_n_m))
        return 0;
    for (const Impl::Motor &m : impl_->motors)
        if (m.said.joint == joint) return 0;
    Impl::Motor m{};
    m.said.id = impl_->next_motor++;
    m.said.joint = joint;
    m.said.store = store;
    m.said.stall_torque_n_m = stall_torque_n_m;
    m.said.no_load_rad_s = no_load_rad_s;
    m.said.brake_torque_n_m = brake_torque_n_m;
    m.said.rotor_thrust_n_per_rad2 = rotor_thrust_n_per_rad2;
    m.said.rotor_drag_n_m_per_rad2 = rotor_drag_n_m_per_rad2;
    m.said.state = impl_->stateToBe(m.said);
    impl_->motors.push_back(m);
    return m.said.id;
}

bool LiveWorld::driveMotor(unsigned motor, double command, bool brake) {
    if (!std::isfinite(command)) return false;
    for (Impl::Motor &m : impl_->motors) {
        if (m.said.id != motor) continue;
        // A motor with a controller is worked by it: what it is told here is
        // told to the controller -- power on, the command's way as its
        // direction and its size as the setting -- so its limits still hold,
        // and stopped it holds on its brake if it has one.
        if (Impl::Control *c = impl_->controlOfMotor(motor)) {
            const double u = std::clamp(command, -1.0, 1.0);
            const int way = u > 0.0 ? 1 : u < 0.0 ? -1 : 0;
            impl_->tell(*c, true, way * c->said.forward,
                        u != 0.0 ? std::optional<double>(std::abs(u)) : std::nullopt, "drive", 0);
            return true;
        }
        m.said.command = std::clamp(command, -1.0, 1.0);
        m.said.brake = brake;
        // Said at once: the next step does what it is told.
        m.said.state = impl_->stateToBe(m.said);
        return true;
    }
    return false;
}

std::vector<LiveEnergyStore> LiveWorld::energyStores() const { return impl_->energy_stores; }

std::string LiveWorld::drawEnergy(unsigned store, double joules) {
    LiveEnergyStore *s = impl_->energyStoreById(store);
    if (s == nullptr) return "there is no store " + std::to_string(store);
    if (!std::isfinite(joules) || joules < 0.0) return "joules drawn are a number from 0";
    if (joules > s->charge_j + 1e-9) return "the store holds less than that";
    s->charge_j = std::max(0.0, s->charge_j - joules);
    s->given_j += joules;
    return "drawn";
}

unsigned LiveWorld::circuit(const std::string &declaration) {
    auto c = machines::Circuit::read(nlohmann::json::parse(declaration));
    impl_->attachCircuit(std::move(c));
    return static_cast<unsigned>(impl_->circuits.size());
}
void LiveWorld::circuitSwitch(unsigned id, const std::string &branch, bool closed) {
    if (!id || id > impl_->circuits.size()) throw std::invalid_argument("unknown circuit");
    impl_->circuits[id - 1].setSwitch(branch, closed);
}
std::string LiveWorld::circuits() const {
    auto out = nlohmann::json::array();
    for (const auto &c : impl_->circuits) out.push_back(c.saved());
    return out.dump();
}

std::vector<LiveMotor> LiveWorld::motors() const {
    std::vector<LiveMotor> out;
    out.reserve(impl_->motors.size());
    for (const Impl::Motor &m : impl_->motors) out.push_back(m.said);
    return out;
}

unsigned LiveWorld::control(const std::string &name, unsigned motor, unsigned rope, double top_out_m,
                            double bottom_out_m) {
    Impl::Motor *m = impl_->motorById(motor);
    if (m == nullptr || impl_->controlOfMotor(motor) != nullptr) return 0;
    const Impl::SceneJoint *pin = impl_->motorPin(m->said.joint);
    if (pin == nullptr) return 0;
    int forward = 1;
    if (rope != 0) {
        const Impl::SceneJoint *drum = nullptr;
        for (const Impl::SceneJoint &joint : impl_->joints)
            if (joint.id == rope && joint.kind == JoltWorld::JointKind::Drum) drum = &joint;
        if (drum == nullptr || (drum->a != pin->a && drum->a != pin->b)) return 0;
        if (!(top_out_m >= 0.0) || !(bottom_out_m > top_out_m) || !std::isfinite(bottom_out_m) ||
            bottom_out_m > drum->upper)
            return 0;
        // Which way the motor's command winds the rope on. The motor turns the
        // pin's b about the pin's axis, relative to its a, and the rope winds on
        // as its drum turns the `winds` way about the rope's own axle; both axes
        // are kept in their bodies' own frames, and are compared in the world's.
        const Vec3 about = impl_->worldAxis(pin->a, pin->axis_local_a);
        const Vec3 axle = impl_->worldAxis(drum->a, drum->axis_local_a);
        const double along = about.x * axle.x + about.y * axle.y + about.z * axle.z;
        if (std::abs(along) < 0.5) return 0;  // the drum does not turn about the pin
        forward = (drum->a == pin->b ? 1 : -1) * (along > 0.0 ? 1 : -1) * (drum->winds < 0 ? -1 : 1);
    }
    Impl::Control c{};
    c.said.id = impl_->next_control++;
    c.said.name = name.empty() ? "machine " + std::to_string(c.said.id) : name;
    c.said.motor = motor;
    c.said.rope = rope;
    c.said.top_out_m = rope != 0 ? top_out_m : 0.0;
    c.said.bottom_out_m = rope != 0 ? bottom_out_m : 0.0;
    c.said.forward = forward;
    impl_->controls.push_back(std::move(c));
    // Off, its motor stopped on its brake: said at once.
    impl_->decide(impl_->controls.back(), 0.0);
    return impl_->controls.back().said.id;
}

bool LiveWorld::sense(unsigned control, const std::string &kind, const std::string &body, const Vec3 &point_world_m,
                      double depth_m, int stops) {
    Impl::Control *c = nullptr;
    for (Impl::Control &each : impl_->controls)
        if (each.said.id == control) c = &each;
    if (c == nullptr || kind != "water" || (stops != 1 && stops != -1)) return false;
    if (!std::isfinite(depth_m) || !(depth_m > 0.0) || depth_m > 10.0) return false;
    if (!std::isfinite(point_world_m.x) || !std::isfinite(point_world_m.y) || !std::isfinite(point_world_m.z))
        return false;
    const auto found = impl_->index_of.find(body);
    if (found == impl_->index_of.end() || !impl_->inWorld(found->second)) return false;
    // Kept in the part's own frame, so the sensor goes where the part goes.
    const RigidSnapshot at = impl_->world->snapshot(impl_->body_of[found->second]);
    LiveSensor sensor;
    sensor.kind = kind;
    sensor.body = body;
    sensor.at_local_m = conjugateOf(at.orientation_world).rotate(point_world_m - at.center_of_mass_world_m);
    sensor.depth_m = depth_m;
    sensor.stops = stops;
    c->said.sensors.push_back(sensor);
    impl_->readSensors(*c);
    return true;
}

std::string LiveWorld::operate(unsigned control, const ControlCommand &command) {
    Impl::Control *c = nullptr;
    for (Impl::Control &each : impl_->controls)
        if (each.said.id == control) c = &each;
    if (c == nullptr) return "there is no controller " + std::to_string(control);
    if (command.direction && (*command.direction < -1 || *command.direction > 1))
        return "a direction is -1 (lower, reverse), 0 (stop) or 1 (raise, forward)";
    if (command.setting && !(*command.setting >= 0.0 && *command.setting <= 1.0))
        return "a drive setting is from 0 to 1: the share of the battery's voltage it drives at";
    if (command.sender.size() > 64) return "a sender's name is 64 characters at most";
    // The last count applied from each of the most recent senders, the latest
    // last: a command no newer than its sender's last is stale and changes
    // nothing. A count of 0 is no count: applied as it comes.
    if (command.seq != 0) {
        for (std::size_t i = 0; i < c->seen.size(); ++i) {
            if (c->seen[i].first != command.sender) continue;
            if (command.seq <= c->seen[i].second) return "stale";
            c->seen.erase(c->seen.begin() + static_cast<std::ptrdiff_t>(i));
            break;
        }
        c->seen.emplace_back(command.sender, command.seq);
        constexpr std::size_t kSendersKept = 8;
        if (c->seen.size() > kSendersKept) c->seen.erase(c->seen.begin());
    }
    impl_->tell(*c, command.power, command.direction, command.setting, command.sender, command.seq);
    return "applied";
}

std::vector<LiveControl> LiveWorld::controls() const {
    std::vector<LiveControl> out;
    out.reserve(impl_->controls.size());
    for (const Impl::Control &c : impl_->controls) out.push_back(c.said);
    return out;
}

unsigned LiveWorld::stillProgram(const std::string &name, const std::string &body, unsigned store, double rest_below,
                                 double rest_until) {
    Impl &I = *impl_;
    if (!(rest_below >= 0.0 && rest_below < 1.0) || (rest_below > 0.0 && !(rest_until > rest_below && rest_until <= 1.0)))
        return 0;
    if (I.energyStoreById(store) == nullptr) return 0;
    const auto found = I.index_of.find(body);
    if (found == I.index_of.end() || !I.inWorld(found->second)) return 0;
    for (const Impl::Program &other : I.programs)
        if (other.said.kind == "still" && other.said.body == body) return 0;
    Impl::Program p{};
    p.forward_local = Vec3{0.0, 0.0, 1.0};
    p.left_local = Vec3{1.0, 0.0, 0.0};
    p.said.id = I.next_program++;
    p.said.name = name.empty() ? "program " + std::to_string(p.said.id) : name;
    p.said.kind = "still";
    p.said.store = store;
    p.said.body = body;
    p.said.setting = 1.0;
    p.said.climb_deg = 90.0;
    p.said.rest_below = rest_below;
    p.said.rest_until = rest_below > 0.0 ? rest_until : 0.0;
    I.readProgram(p);
    I.programs.push_back(std::move(p));
    return I.programs.back().said.id;
}

unsigned LiveWorld::program(const std::string &name, const std::string &kind, unsigned left, unsigned right,
                            const std::string &body, double setting, double climb_deg, double rest_below,
                            double rest_until, const std::vector<unsigned> &rotors, double hover_m) {
    Impl &I = *impl_;
    if (kind == "hover") return hoverProgram(name, body, setting, rest_below, rest_until, rotors, hover_m);
    if (kind != "roam" || left == right) return 0;
    if (!(setting > 0.0 && setting <= 1.0) || !(climb_deg > 0.0 && climb_deg < 60.0)) return 0;
    if (!(rest_below >= 0.0 && rest_below < 1.0) || (rest_below > 0.0 && !(rest_until > rest_below && rest_until <= 1.0)))
        return 0;
    Impl::Control *l = I.controlById(left);
    Impl::Control *r = I.controlById(right);
    if (l == nullptr || r == nullptr || l->said.rope != 0 || r->said.rope != 0) return 0;
    for (const Impl::Program &p : I.programs)
        if (p.said.left == left || p.said.right == left || p.said.left == right || p.said.right == right) return 0;
    // Each wheel: the other thing on its motor's pin through `body`.
    const auto wheelOf = [&](const Impl::Control &c) -> std::string {
        const Impl::Motor *m = I.motorById(c.said.motor);
        const Impl::SceneJoint *pin = m != nullptr ? I.motorPin(m->said.joint) : nullptr;
        if (pin == nullptr) return {};
        if (pin->a == body) return pin->b;
        if (pin->b == body) return pin->a;
        return {};
    };
    const std::string left_wheel = wheelOf(*l), right_wheel = wheelOf(*r);
    if (left_wheel.empty() || right_wheel.empty() || left_wheel == right_wheel) return 0;
    const auto chassis = I.index_of.find(body);
    const auto lw = I.index_of.find(left_wheel);
    const auto rw = I.index_of.find(right_wheel);
    if (chassis == I.index_of.end() || lw == I.index_of.end() || rw == I.index_of.end() ||
        !I.inWorld(chassis->second) || !I.inWorld(lw->second) || !I.inWorld(rw->second))
        return 0;
    // From the right wheel to the left, in the chassis's own level: its left;
    // and forward, square to that across the level.
    const RigidSnapshot at = I.world->snapshot(I.body_of[chassis->second]);
    Vec3 across = conjugateOf(at.orientation_world)
                      .rotate(I.world->snapshot(I.body_of[lw->second]).center_of_mass_world_m -
                              I.world->snapshot(I.body_of[rw->second]).center_of_mass_world_m);
    across.y = 0.0;
    if (length(across) < 0.01) return 0;
    Impl::Program p{};
    p.left_local = normalized(across);
    p.forward_local = cross(p.left_local, Vec3{0.0, 1.0, 0.0});
    p.said.id = I.next_program++;
    p.said.name = name.empty() ? "program " + std::to_string(p.said.id) : name;
    p.said.kind = kind;
    p.said.left = left;
    p.said.right = right;
    p.said.body = body;
    p.said.setting = setting;
    p.said.climb_deg = climb_deg;
    p.said.rest_below = rest_below;
    p.said.rest_until = rest_below > 0.0 ? rest_until : 0.0;
    I.readProgram(p);
    I.programs.push_back(std::move(p));
    return I.programs.back().said.id;
}

unsigned LiveWorld::hoverProgram(const std::string &name, const std::string &body, double setting,
                                 double rest_below, double rest_until, const std::vector<unsigned> &rotors,
                                 double hover_m) {
    Impl &I = *impl_;
    if (rotors.size() != 4 || !(setting > 0.0 && setting <= 1.0) || !(hover_m > 0.0 && hover_m <= 50.0)) return 0;
    if (!(rest_below >= 0.0 && rest_below < 1.0) || (rest_below > 0.0 && !(rest_until > rest_below && rest_until <= 1.0)))
        return 0;
    const auto chassis = I.index_of.find(body);
    if (chassis == I.index_of.end() || !I.inWorld(chassis->second)) return 0;
    const RigidSnapshot at = I.world->snapshot(I.body_of[chassis->second]);
    Impl::Program p{};
    for (unsigned id : rotors) {
        if (std::count(rotors.begin(), rotors.end(), id) != 1) return 0;
        Impl::Control *c = I.controlById(id);
        if (c == nullptr || c->said.rope != 0) return 0;
        for (const Impl::Program &other : I.programs)
            if (other.said.left == id || other.said.right == id ||
                std::find(other.said.rotors.begin(), other.said.rotors.end(), id) != other.said.rotors.end())
                return 0;
        const Impl::Motor *m = I.motorById(c->said.motor);
        const Impl::SceneJoint *pin = m != nullptr ? I.motorPin(m->said.joint) : nullptr;
        if (pin == nullptr || (pin->a != body && pin->b != body) || !(m->said.rotor_thrust_n_per_rad2 > 0.0)) return 0;
        // Where the pin stands on the chassis, in its own level.
        const std::string other = pin->a == body ? pin->b : pin->a;
        const auto part = I.index_of.find(other);
        if (part == I.index_of.end() || !I.inWorld(part->second)) return 0;
        const RigidSnapshot rotor = I.world->snapshot(I.body_of[part->second]);
        Vec3 local = conjugateOf(at.orientation_world).rotate(rotor.center_of_mass_world_m - at.center_of_mass_world_m);
        local.y = 0.0;
        p.rotor_local.push_back(local);
        p.spins.push_back(p.spins.size() % 2 == 0 ? 1 : -1);
    }
    // Its front is its own +z and its left its own +x, as it was drawn.
    p.forward_local = Vec3{0.0, 0.0, 1.0};
    p.left_local = Vec3{1.0, 0.0, 0.0};
    p.said.id = I.next_program++;
    p.said.name = name.empty() ? "program " + std::to_string(p.said.id) : name;
    p.said.kind = "hover";
    p.said.left = rotors[0];
    p.said.right = rotors[1];
    p.said.rotors = rotors;
    p.said.body = body;
    p.said.setting = setting;
    p.said.climb_deg = 90.0;
    p.said.hover_m = hover_m;
    p.said.rest_below = rest_below;
    p.said.rest_until = rest_below > 0.0 ? rest_until : 0.0;
    I.readProgram(p);
    p.landed_height_m = p.said.height_m;
    I.programs.push_back(std::move(p));
    return I.programs.back().said.id;
}

bool LiveWorld::programSense(unsigned program, const std::string &kind, const std::string &body,
                             const Vec3 &point_world_m, double depth_m) {
    Impl &I = *impl_;
    Impl::Program *p = nullptr;
    for (Impl::Program &each : I.programs)
        if (each.said.id == program) p = &each;
    if (p == nullptr || kind != "water") return false;
    if (!std::isfinite(depth_m) || !(depth_m > 0.0) || depth_m > 10.0) return false;
    if (!std::isfinite(point_world_m.x) || !std::isfinite(point_world_m.y) || !std::isfinite(point_world_m.z))
        return false;
    const auto found = I.index_of.find(body);
    const auto chassis = I.index_of.find(p->said.body);
    if (found == I.index_of.end() || !I.inWorld(found->second) || chassis == I.index_of.end() ||
        !I.inWorld(chassis->second))
        return false;
    // Kept in the part's own frame, so the sensor goes where the part goes; and
    // on the side of the machine it is across its chassis, the middle within
    // kMiddleM counting as both.
    constexpr double kMiddleM = 0.02;
    const RigidSnapshot at = I.world->snapshot(I.body_of[found->second]);
    const RigidSnapshot frame = I.world->snapshot(I.body_of[chassis->second]);
    LiveSensor sensor;
    sensor.kind = kind;
    sensor.body = body;
    sensor.at_local_m = conjugateOf(at.orientation_world).rotate(point_world_m - at.center_of_mass_world_m);
    sensor.depth_m = depth_m;
    const double across =
        dot(frame.orientation_world.rotate(p->left_local), point_world_m - frame.center_of_mass_world_m);
    sensor.side = across > kMiddleM ? 1 : across < -kMiddleM ? -1 : 0;
    p->said.sensors.push_back(sensor);
    I.readSensorList(p->said.sensors);
    return true;
}

std::string LiveWorld::run(unsigned program, const ProgramCommand &command) {
    Impl::Program *p = nullptr;
    for (Impl::Program &each : impl_->programs)
        if (each.said.id == program) p = &each;
    if (p == nullptr) return "there is no program " + std::to_string(program);
    if (command.sender.size() > 64) return "a sender's name is 64 characters at most";
    // As a controller keeps them (operate): a command no newer than its
    // sender's last is stale and changes nothing; a count of 0 is no count.
    if (command.seq != 0) {
        for (std::size_t i = 0; i < p->seen.size(); ++i) {
            if (p->seen[i].first != command.sender) continue;
            if (command.seq <= p->seen[i].second) return "stale";
            p->seen.erase(p->seen.begin() + static_cast<std::ptrdiff_t>(i));
            break;
        }
        p->seen.emplace_back(command.sender, command.seq);
        constexpr std::size_t kSendersKept = 8;
        if (p->seen.size() > kSendersKept) p->seen.erase(p->seen.begin());
    }
    p->said.power = command.power;
    p->said.sender = command.sender;
    p->said.seq = command.seq;
    // What it will do, said at once, and its wheels told.
    impl_->decideProgram(*p);
    return "applied";
}

std::string LiveWorld::behave(unsigned program, const ProgramAsk &ask) {
    Impl::Program *p = nullptr;
    for (Impl::Program &each : impl_->programs)
        if (each.said.id == program) p = &each;
    if (p == nullptr) return "there is no program " + std::to_string(program);
    if (ask.sender.size() > 64) return "a sender's name is 64 characters at most";
    static const char *const kAsks[] = {"going forward", "backing off", "turning left", "turning right",
                                        "waiting",       "facing",      "approaching",  ""};
    if (std::find(std::begin(kAsks), std::end(kAsks), ask.doing) == std::end(kAsks))
        return "a program can be asked to be going forward, backing off, turning left, turning right, waiting, "
               "facing or approaching, or asked nothing (\"\")";
    if (!std::isfinite(ask.for_s) || ask.for_s < 0.0 || ask.for_s > 60.0)
        return "a program is asked for from 0 s (until asked otherwise) to 60 s";
    if (ask.why.size() > 200) return "why it was asked is 200 characters at most";
    if (p->said.kind == "still" && !ask.doing.empty() && ask.doing != "waiting")
        return "a machine that goes nowhere can only be asked to be waiting, or asked nothing (\"\")";
    const bool needs_toward = ask.doing == "facing" || ask.doing == "approaching";
    if (needs_toward && (!ask.has_toward || !std::isfinite(ask.toward_m.x) || !std::isfinite(ask.toward_m.z)))
        return "facing and approaching need a point in the world to look toward";
    if (ask.seq != 0) {
        for (std::size_t i = 0; i < p->seen.size(); ++i) {
            if (p->seen[i].first != ask.sender) continue;
            if (ask.seq <= p->seen[i].second) return "stale";
            p->seen.erase(p->seen.begin() + static_cast<std::ptrdiff_t>(i));
            break;
        }
        p->seen.emplace_back(ask.sender, ask.seq);
        constexpr std::size_t kSendersKept = 8;
        if (p->seen.size() > kSendersKept) p->seen.erase(p->seen.begin());
    }
    LiveProgram &s = p->said;
    p->interruptions = 0;
    p->interrupted = false;
    s.asked = ask.doing;
    s.asked_why = ask.doing.empty() ? std::string{} : ask.why.empty() ? "it was asked to" : ask.why;
    s.asked_by = ask.doing.empty() ? std::string{} : ask.sender;
    s.asked_for_s = ask.doing.empty() ? 0.0 : ask.for_s;
    s.asked_s = 0.0;
    s.asked_toward_m = needs_toward ? ask.toward_m : Vec3{};
    if (ask.doing.empty() && s.power && s.doing != "resting") {
        // Asked nothing more: it decides again from going forward, as it does
        // from stopped, rather than from whatever it was asked last.
        s.doing = "stopped";
    }
    impl_->readProgram(*p);
    impl_->decideProgram(*p);
    return "applied";
}

std::vector<LiveProgram> LiveWorld::programs() const {
    std::vector<LiveProgram> out;
    out.reserve(impl_->programs.size());
    for (const Impl::Program &p : impl_->programs) out.push_back(p.said);
    return out;
}

bool LiveWorld::setSun(double elevation_deg, double azimuth_deg, double irradiance_w_m2) {
    if (!std::isfinite(elevation_deg) || !std::isfinite(azimuth_deg) || !std::isfinite(irradiance_w_m2) ||
        elevation_deg < 0.0 || elevation_deg > 90.0 || irradiance_w_m2 < 0.0 || irradiance_w_m2 > 1400.0)
        return false;
    constexpr double kRadPerDeg = 3.14159265358979323846 / 180.0;
    LiveSun &sun = impl_->sun;
    sun = LiveSun{};   // standing still: no day
    sun.declared = true;
    sun.elevation_deg = elevation_deg;
    sun.azimuth_deg = azimuth_deg;
    sun.irradiance_w_m2 = irradiance_w_m2;
    sun.zenith_irradiance_w_m2 = irradiance_w_m2;
    const double el = elevation_deg * kRadPerDeg, az = azimuth_deg * kRadPerDeg;
    sun.toward = Vec3{std::cos(el) * std::sin(az), std::sin(el), std::cos(el) * std::cos(az)};
    return true;
}

bool LiveWorld::setDay(double day_s, double noon_elevation_deg, double hour, double irradiance_w_m2) {
    if (!std::isfinite(day_s) || !std::isfinite(noon_elevation_deg) || !std::isfinite(hour) ||
        !std::isfinite(irradiance_w_m2) || day_s < 10.0 || !(noon_elevation_deg > 0.0) || noon_elevation_deg > 90.0 ||
        hour < 0.0 || hour >= 24.0 || irradiance_w_m2 < 0.0 || irradiance_w_m2 > 1400.0)
        return false;
    LiveSun &sun = impl_->sun;
    sun = LiveSun{};
    sun.declared = true;
    sun.day_s = day_s;
    sun.noon_elevation_deg = noon_elevation_deg;
    sun.zenith_irradiance_w_m2 = irradiance_w_m2;
    // The hour it was when the world's clock stood at zero, so that it is
    // `hour` now.
    sun.hour_at_start = hour - 24.0 * impl_->time_s / day_s;
    impl_->advanceSun();
    return true;
}

LiveSun LiveWorld::sun() const { return impl_->sun; }

unsigned LiveWorld::solarPanel(const std::string &name, const std::string &body, unsigned store,
                               const Vec3 &at_world_m, const Vec3 &normal_world, double area_m2, double efficiency) {
    Impl &I = *impl_;
    if (I.energyStoreById(store) == nullptr) return 0;
    if (!(area_m2 > 0.0 && area_m2 <= 100.0) || !(efficiency > 0.0 && efficiency <= 1.0)) return 0;
    if (!std::isfinite(at_world_m.x) || !std::isfinite(at_world_m.y) || !std::isfinite(at_world_m.z) ||
        !std::isfinite(normal_world.x) || !std::isfinite(normal_world.y) || !std::isfinite(normal_world.z) ||
        length(normal_world) < 1e-6)
        return 0;
    const auto found = I.index_of.find(body);
    if (found == I.index_of.end() || !I.inWorld(found->second)) return 0;
    // Kept in the part's own frame, so the panel goes, and turns, where the
    // part does.
    const RigidSnapshot at = I.world->snapshot(I.body_of[found->second]);
    const Quat back = conjugateOf(at.orientation_world);
    LiveSolarPanel panel;
    panel.id = I.next_panel++;
    panel.name = name.empty() ? "solar panel " + std::to_string(panel.id) : name;
    panel.body = body;
    panel.store = store;
    panel.at_local_m = back.rotate(at_world_m - at.center_of_mass_world_m);
    panel.normal_local = back.rotate(normalized(normal_world));
    panel.area_m2 = area_m2;
    panel.efficiency = efficiency;
    panel.at_m = at_world_m;
    panel.normal = normalized(normal_world);
    I.panels.push_back(std::move(panel));
    return I.panels.back().id;
}

std::vector<LiveSolarPanel> LiveWorld::solarPanels() const { return impl_->panels; }

double LiveWorld::inertiaAbout(const std::string &name, const Vec3 &axis_world) const {
    const auto found = impl_->index_of.find(name);
    if (found == impl_->index_of.end() || !impl_->inWorld(found->second)) return 0.0;
    return impl_->world->inertiaAbout(impl_->body_of[found->second], axis_world);
}

unsigned LiveWorld::drum(const std::string &drum, const std::string &load, const Vec3 &centre_world_m,
                         const Vec3 &axis_world, double radius_m, const Vec3 &load_point_world_m, int winds,
                         double length_m, double out_m) {
    const auto first = impl_->index_of.find(drum);
    const auto second = impl_->index_of.find(load);
    if (first == impl_->index_of.end() || second == impl_->index_of.end()) return 0;
    if (first->second == second->second) return 0;
    // A thing set aside (park) is not in the world to be joined to anything.
    if (!impl_->inWorld(first->second) || !impl_->inWorld(second->second)) return 0;
    const double reach = length(axis_world);
    if (!(reach > 1e-9) || !(radius_m > 0.0) || !std::isfinite(radius_m) || !(length_m > 0.0) ||
        !std::isfinite(length_m) || !(out_m >= 0.0) || out_m > length_m)
        return 0;

    Impl::SceneJoint joint{};
    joint.id = impl_->next_joint++;
    joint.a = drum;
    joint.b = load;
    joint.kind = JoltWorld::JointKind::Drum;
    joint.lower = 0.0;
    joint.upper = length_m;
    joint.radius_m = radius_m;
    joint.winds = winds < 0 ? -1 : 1;
    // The drum's centre and axle in its own frame, and the rope's end in the
    // load's, as a pin's and a rope's are kept.
    const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[first->second]);
    const RigidSnapshot two = impl_->world->snapshot(impl_->body_of[second->second]);
    joint.point_local_a = conjugateOf(one.orientation_world).rotate(centre_world_m - one.center_of_mass_world_m);
    joint.axis_local_a = conjugateOf(one.orientation_world).rotate((1.0 / reach) * axis_world);
    joint.point_local_b_tie =
        conjugateOf(two.orientation_world).rotate(load_point_world_m - two.center_of_mass_world_m);
    joint.point_local_b = joint.point_local_b_tie;
    joint.stand_off_a = impl_->standOff(first->second, joint.point_local_a);
    joint.stand_off_b = impl_->standOff(second->second, joint.point_local_b);
    try {
        JoltWorld::DrumDescription rope{};
        rope.drum = impl_->body_of[first->second];
        rope.load = impl_->body_of[second->second];
        rope.centre_world_m = centre_world_m;
        rope.axis_world = (1.0 / reach) * axis_world;
        rope.radius_m = radius_m;
        rope.load_point_world_m = load_point_world_m;
        rope.winds = joint.winds;
        rope.length_m = length_m;
        rope.out_m = out_m;
        joint.rigid = impl_->world->addDrum(rope);
    } catch (const std::exception &) {
        return 0;
    }
    impl_->world->wake(impl_->body_of[first->second]);
    impl_->world->wake(impl_->body_of[second->second]);
    impl_->joints.push_back(std::move(joint));
    return impl_->joints.back().id;
}

void LiveWorld::setJointFriction(unsigned joint, double friction_torque_n_m) {
    for (Impl::SceneJoint &held : impl_->joints) {
        if (held.id != joint) continue;
        held.friction = std::max(0.0, friction_torque_n_m);
        if (held.rigid != 0 && impl_->world->hasJoint(held.rigid))
            impl_->world->setJointFriction(held.rigid, held.friction);
        return;
    }
}

void LiveWorld::unhinge(unsigned joint) {
    for (std::size_t i = 0; i < impl_->joints.size(); ++i) {
        if (impl_->joints[i].id != joint) continue;
        if (impl_->joints[i].rigid != 0) impl_->world->removeJoint(impl_->joints[i].rigid);
        // What was hanging on it is about to fall, and a body asleep on its pin
        // would hang in the air until something else woke it.
        for (const std::string &side : {impl_->joints[i].a, impl_->joints[i].b}) {
            const auto found = impl_->index_of.find(side);
            if (found != impl_->index_of.end() && impl_->inWorld(found->second))
                impl_->world->wake(impl_->body_of[found->second]);
        }
        impl_->joints.erase(impl_->joints.begin() + static_cast<std::ptrdiff_t>(i));
        // Two exact bodies no longer held meet as their surfaces again.
        impl_->settleJointedContacts();
        return;
    }
}

// Which piece of a broken body now carries a pin.
//
// Asked of the cells rather than of the bounding box, because the pieces this
// is chasing are hulls and a hull's box is mostly not the hull. Restricted to
// bodies descended from the name the pin used to be in: a pin that loses its
// wood should come out, not grab whatever happens to be lying against it.
//
// The NEAREST such piece -- not one the pin has to be inside, because a pin is
// often not inside what it holds. The playground's chat hangs a pane on the
// face of its post, which leaves the pin in the gap between them: 63 mm from
// the pane's nearest cell centre in the build that found this. This used to ask
// for a piece within one cell of the pin, so that pin let go when the pane
// broke -- though the piece carrying the whole hinge edge, 293 of its 300
// cells, was 49 mm away. A piece now carries the pin if it stands no further
// off than the body did when the pin went in, `stand_off_m`, plus a cell for
// what the break moved it: the lattice run knows nothing of pins, and in that
// build it carried the piece 14 mm nearer. Further off than that, nothing of
// the body is left at the pin, and it comes out. `stand_off_m` comes back as
// the piece's own, which is what its next break is measured against.
std::size_t LiveWorld::bodyHolding(const Vec3 &point_world_m, const std::string &was_called,
                                   double &stand_off_m) const {
    std::size_t best = static_cast<std::size_t>(-1);
    double closest = stand_off_m + impl_->request.cell_size_m;
    for (std::size_t i = 0; i < impl_->described.size(); ++i) {
        const std::string &name = impl_->described[i].name;
        const bool descended = name == was_called ||
                               name.rfind(was_called + " piece ", 0) == 0;
        // Nor a piece that is not in the world: one set aside carries no pin.
        if (!descended || !impl_->inWorld(i)) continue;
        const RigidSnapshot at = impl_->world->snapshot(impl_->body_of[i]);
        const Quat inverse = conjugateOf(at.orientation_world);
        const Vec3 local = inverse.rotate(point_world_m - at.center_of_mass_world_m);
        for (const std::uint32_t node : impl_->nodes_of[i]) {
            if (node >= impl_->cell_offset_m.size()) continue;
            const double gap = length(impl_->cell_offset_m[node] - local);
            if (gap < closest) { closest = gap; best = i; }
        }
    }
    if (best != static_cast<std::size_t>(-1)) stand_off_m = closest;
    return best;
}

// Put the pins back after the body table has been rearranged.
//
// Every body in an island is destroyed and rebuilt when anything in it breaks,
// so every engine-level constraint touching it is gone -- including the ones on
// bodies that came through the collision untouched. This is what puts them
// back, and it is also where a pin decides what to do when its wood is no
// longer there: it follows the piece that carries it, and if nothing of the
// body is left near it, it comes out and what hung on it falls.
void LiveWorld::rehangJoints() {
    for (Impl::SceneJoint &joint : impl_->joints) {
        if (!joint.attached) continue;
        if (joint.rigid != 0 && impl_->world->hasJoint(joint.rigid)) continue;
        joint.rigid = 0;
        // Away in the bag with the thing it is in (park): kept as it is, and
        // made again when the thing is back (unpark). Hung now, it would find
        // neither end in the world and come off.
        if (impl_->setAside(joint)) continue;

        // Find each end again. By name if the name is still there -- which it is
        // whenever a body came through whole -- and otherwise by following the
        // pin into whichever piece of the old body now carries it.
        std::size_t side[2] = {static_cast<std::size_t>(-1), static_cast<std::size_t>(-1)};
        std::string *names[2] = {&joint.a, &joint.b};
        Vec3 *locals[2] = {&joint.point_local_a, &joint.point_local_b};
        double *stand_offs[2] = {&joint.stand_off_a, &joint.stand_off_b};
        // The pin's last known place in the world, taken from whichever end is
        // still standing. Both ends cannot have moved without one of them being
        // findable, because a joint with neither end left is simply gone.
        bool have_point = false;
        Vec3 point{};
        for (int end = 0; end < 2 && !have_point; ++end) {
            const auto found = impl_->index_of.find(*names[end]);
            if (found == impl_->index_of.end() || !impl_->inWorld(found->second)) continue;
            const RigidSnapshot at = impl_->world->snapshot(impl_->body_of[found->second]);
            point = at.center_of_mass_world_m + at.orientation_world.rotate(*locals[end]);
            have_point = true;
        }
        for (int end = 0; end < 2; ++end) {
            const auto found = impl_->index_of.find(*names[end]);
            if (found != impl_->index_of.end()) { side[end] = found->second; continue; }
            // Where THIS end was attached, if a cut has just replaced its body:
            // a rope, a pulley or a spring is tied at two different points, and
            // a rope's are a cell apart across the join -- searched for with the
            // other end's point, the pieces had nothing within a cell of it, and
            // the ties on both sides of a cut segment came off. A pin's two ends
            // share one point, so for a pin this is the same place.
            Vec3 own = point;
            bool have_own = have_point;
            if (const auto gone = impl_->vanished.find(*names[end]); gone != impl_->vanished.end()) {
                own = gone->second.center_of_mass_world_m +
                      gone->second.orientation_world.rotate(*locals[end]);
                have_own = true;
            }
            if (!have_own) break;
            // Measured from this end's own point, against how far that same
            // point stood off the body's matter when the joint was made: the
            // stand-offs are recorded per end, from each end's own point.
            const std::size_t heir = bodyHolding(own, *names[end], *stand_offs[end]);
            if (heir == static_cast<std::size_t>(-1)) break;
            // This piece carries the pin now. Re-write where it sits in the new
            // body's frame -- the piece has its own centre of mass, nowhere near
            // the one the parent had -- and rename the end to match, so the next
            // break follows the piece's own pieces.
            const RigidSnapshot at = impl_->world->snapshot(impl_->body_of[heir]);
            *locals[end] = conjugateOf(at.orientation_world).rotate(own - at.center_of_mass_world_m);
            if (end == 1) joint.point_local_b_tie = *locals[end];
            *names[end] = impl_->described[heir].name;
            side[end] = heir;
            impl_->delays.push_back({impl_->time_s, *names[end], "rehung", 0.0, 0.0});
        }
        if (side[0] == static_cast<std::size_t>(-1) || side[1] == static_cast<std::size_t>(-1) ||
            side[0] == side[1] || !have_point) {
            // Nothing left to hang it on. The gate is off its hinges, which is
            // the honest outcome -- and it is reported rather than dropped, so a
            // host that drew a pin knows to stop drawing it.
            joint.attached = false;
            continue;
        }
        try {
            const RigidSnapshot one = impl_->world->snapshot(impl_->body_of[side[0]]);
            const Vec3 along = one.orientation_world.rotate(joint.axis_local_a);
            // A rope, a pulley or a spring is tied at two points, and end a's is
            // its own -- not the point a pin's two ends share.
            const Vec3 point_a = one.center_of_mass_world_m +
                                 one.orientation_world.rotate(joint.point_local_a);
            // The limits were measured from where the thing was standing when
            // the joint was made, and it is not standing there now. Jolt
            // measures a fresh constraint from where it finds the bodies, so
            // what can be asked for is the travel that is LEFT: a door that has
            // swung 30 of its 90 degrees has 60 to go and 30 to come back, and
            // a portcullis hauled 1 m of its 2 has 1 m either way.
            const double got = std::max(joint.lower, std::min(joint.upper,
                                                              joint.at_when_hung));
            if (joint.kind == JoltWorld::JointKind::Pulley) {
                JoltWorld::PulleyDescription rove{};
                rove.a = impl_->body_of[side[0]];
                rove.b = impl_->body_of[side[1]];
                rove.point_a_world_m = point_a;
                const RigidSnapshot far = impl_->world->snapshot(impl_->body_of[side[1]]);
                rove.point_b_world_m = far.center_of_mass_world_m +
                                       far.orientation_world.rotate(joint.point_local_b_tie);
                // The sheaves do not move with anything. They are points in the
                // world, and re-making the constraint must not quietly relocate
                // them onto whichever piece of beam survived.
                rove.over_a_world_m = joint.over_a;
                rove.over_b_world_m = joint.over_b;
                rove.ratio = joint.ratio;
                rove.length_m = joint.upper;
                joint.rigid = impl_->world->addPulley(rove);
            } else if (joint.kind == JoltWorld::JointKind::Link) {
                JoltWorld::LinkDescription rope{};
                rope.a = impl_->body_of[side[0]];
                rope.b = impl_->body_of[side[1]];
                rope.point_a_world_m = point_a;
                // The far end is tied somewhere else on the other body, so it
                // has to be worked out from that body rather than shared. This
                // is the one place a link differs from a pin: two points, not
                // one.
                const RigidSnapshot other = impl_->world->snapshot(impl_->body_of[side[1]]);
                rope.point_b_world_m = other.center_of_mass_world_m +
                                       other.orientation_world.rotate(joint.point_local_b_tie);
                rope.length_m = joint.upper;
                rope.breaking_tension_n = joint.breaks_at_n;
                joint.rigid = impl_->world->addLink(rope);
            } else if (joint.kind == JoltWorld::JointKind::Elastic) {
                JoltWorld::ElasticDescription limb{};
                limb.a = impl_->body_of[side[0]];
                limb.b = impl_->body_of[side[1]];
                limb.point_a_world_m = point_a;
                const RigidSnapshot far = impl_->world->snapshot(impl_->body_of[side[1]]);
                limb.point_b_world_m = far.center_of_mass_world_m +
                                       far.orientation_world.rotate(joint.point_local_b_tie);
                limb.rest_m = joint.rest_m;
                limb.stiffness_n_m = joint.stiffness_n_m;
                limb.damping_n_s_m = joint.damping_n_s_m;
                joint.rigid = impl_->world->addElastic(limb);
            } else if (joint.kind == JoltWorld::JointKind::Fixing) {
                JoltWorld::FixingDescription peg{};
                peg.a = impl_->body_of[side[0]];
                peg.b = impl_->body_of[side[1]];
                peg.point_world_m = point;
                peg.axis_world = along;
                peg.holds_tension_n = joint.holds_tension_n;
                peg.holds_shear_n = joint.holds_shear_n;
                peg.comes_off_n = joint.comes_off_n;
                joint.rigid = impl_->world->addFixing(peg);
            } else if (joint.kind == JoltWorld::JointKind::Slider) {
                JoltWorld::SliderDescription groove{};
                groove.a = impl_->body_of[side[0]];
                groove.b = impl_->body_of[side[1]];
                groove.point_world_m = point;
                groove.axis_world = along;
                groove.lower_m = joint.lower - got;
                groove.upper_m = joint.upper - got;
                groove.friction_n = joint.friction;
                joint.rigid = impl_->world->addSlider(groove);
            } else {
                JoltWorld::HingeDescription pin{};
                pin.a = impl_->body_of[side[0]];
                pin.b = impl_->body_of[side[1]];
                pin.point_world_m = point;
                pin.axis_world = along;
                // A pin free all the way round -- a wheel's -- has no travel
                // left to measure: it turns on as it did. Shifting its limits
                // by how far it had turned asked for more than a full turn,
                // which a hinge cannot be made with, and the wheel came off.
                constexpr double kFullTurn = 3.14159265358979323846 - 1e-9;
                const bool free_turning = joint.lower <= -kFullTurn && joint.upper >= kFullTurn;
                pin.lower_rad = free_turning ? joint.lower : joint.lower - got;
                pin.upper_rad = free_turning ? joint.upper : joint.upper - got;
                pin.friction_torque_n_m = joint.friction;
                joint.rigid = impl_->world->addHinge(pin);
            }
        } catch (const std::exception &) {
            joint.attached = false;
        }
    }
    impl_->settleJointedContacts();
}

bool LiveWorld::grab(const std::string &name) {
    const auto found = impl_->index_of.find(name);
    if (found == impl_->index_of.end()) return false;
    // Anchored scenery is the world, not a prop. Letting it be dragged would
    // move the floor out from under everything standing on it.
    if (impl_->described[found->second].anchored) return false;
    // Nor can a hand take what is not in the world: a thing set aside (park)
    // is somewhere else until it is brought back.
    if (!impl_->inWorld(found->second)) return false;
    if (impl_->environment && impl_->holding!=found->second) {
        const double new_mass=impl_->world->mechanicalState(impl_->body_of[found->second]).mass_kg;
        if (impl_->carriedObjectsKg(false)+new_mass+impl_->environment->carriedKg()>
            impl_->environment->carryLimitKg()) return false;
    }
    if (impl_->holding != static_cast<std::size_t>(-1)) release();
    impl_->holding = found->second;
    // Carried, which is placement. wield() makes a grip of it afterwards.
    impl_->wielding = false;
    impl_->hand_force = {};
    // The world it is being taken out of has probably been still for a while,
    // and a body that has been still is not being simulated. Everything below
    // -- carrying it, and gravity when it is let go -- needs it back in the
    // step, and writing a pose does not do that.
    impl_->world->wake(impl_->body_of[found->second]);
    const RigidSnapshot now = impl_->world->snapshot(impl_->body_of[impl_->holding]);
    impl_->held_at = now.center_of_mass_world_m;
    impl_->held_facing = now.orientation_world;
    // A new hold: nothing done to it yet, and no stroke.
    impl_->held_velocity = {};
    impl_->stroke.reset();
    impl_->stroke_ended.clear();
    impl_->hand_work_j = 0.0;
    impl_->hand_applied_n = {};
    impl_->haul_pushed = {};
    impl_->let_go_body.clear();
    impl_->let_go_velocity = {};
    impl_->let_go_at_s = -1.0;
    impl_->let_go_work_j = 0.0;
    return true;
}

void LiveWorld::moveHeld(const Vec3 &to_world_m) {
    if (impl_->holding == static_cast<std::size_t>(-1)) return;
    // Whoever moves the hand is driving it, so a stroke stops here -- and the
    // hand is being PUT somewhere, not moved along something.
    cancelStroke();
    impl_->held_velocity = {};
    impl_->held_at = to_world_m;
    // And put it there now, rather than waiting for the next step: a host that
    // moves the hand and then reads the world back expects the thing to have
    // moved. Which of the two things below that means is carryOrHaul's
    // business, and the whole reason it is a function rather than a lambda
    // inside step() -- the hand writes the world in two places, and the first
    // version of hauling only fixed one of them. A portcullis with 800 mm of
    // travel went 1.57 m up, because this line here was still a teleport.
    carryOrHaul(impl_->last_dt_s > 0.0 ? impl_->last_dt_s : 1.0 / 240.0);
}

// Where the hand puts what it is holding.
//
// Two different things, and which one depends on whether the thing is attached
// to anything.
//
// A LOOSE body is carried: put exactly where the hand is, every step, at zero
// velocity. That is what makes dragging feel like holding rather than pushing,
// and it is right, because nothing else has an opinion about where it should be.
//
// A body on a JOINT is hauled instead. Carrying it would override everything it
// is attached to -- writing a pose is the last word, and a portcullis with
// 800 mm of travel dragged two metres went two metres, with its grooves
// reporting `upper = 0.8` the whole way and working perfectly. So the hand
// pulls, by velocity, and the mechanism decides what that does: a grate goes up
// its grooves and no further, a gate goes round its pin, and nothing comes off
// its mountings because somebody dragged hard.
//
// For a slide the pull is resolved along the groove and clamped to the travel
// that is actually left, rather than left for the limit to fight. A hard
// constraint against a velocity written in from outside on every step is a tug
// of war, and position correction does not win it -- that is where the 1.57 m
// came from even after the pull became a velocity.
void LiveWorld::setHandStrength(double newtons) {
    impl_->hand_strength_n = std::max(0.0, newtons);
}
double LiveWorld::handStrength() const { return impl_->hand_strength_n; }

void LiveWorld::carryOrHaul(double dt_s) {
    if (impl_->holding == static_cast<std::size_t>(-1)) return;
    if (!(dt_s > 0.0)) dt_s = 1.0 / 240.0;
    const MatterBodyId id = impl_->body_of[impl_->holding];
    // A hand cannot hold what is not in the world. park() lets go first, so
    // this is only ever a backstop -- but a pose written onto a body set aside
    // is a throw from inside the step's trial, not a no-op.
    if (!impl_->world->contains(id)) {
        release();
        return;
    }
    RigidSnapshot state = impl_->world->snapshot(id);

    // WIELDED: a hand on a grip. Its pull is not made here but once per step,
    // inside the step's reversible trial (step(), `hand`). Made here -- after
    // each step for the next one, and again whenever the hand was moved between
    // steps -- the pushes added up in the body's force accumulator, and the first
    // step after every move of the hand had the hand's force twice. And the
    // accumulator is part of the state a trial rewinds to, so a push made out
    // here survived a refused step and was pushed again on the retry.
    // docs/cutting-model.md section 7.
    if (impl_->wielding) return;

    const std::string carrying = impl_->described[impl_->holding].name;
    const Impl::SceneJoint *on = nullptr;
    for (const Impl::SceneJoint &joint : impl_->joints) {
        if (!joint.attached || joint.rigid == 0) continue;
        if (joint.a != carrying && joint.b != carrying) continue;
        // A SLIDER wins over anything else on the same body, because a slider
        // is the joint that says where the thing may go at all -- and the hand
        // can then ask for exactly the travel it has left, which is the one
        // case that can be answered exactly rather than pulled towards.
        //
        // The courtyard's portcullis is on a slider AND on the winch's rope,
        // and taking whichever came last in the list meant the hand treated it
        // as a rope-and-pulley problem: a person heaving with 800 N against
        // 14.2 kN of iron, which is honest arithmetic and is not what hauling a
        // grate up its own grooves is.
        if (on == nullptr || joint.kind == JoltWorld::JointKind::Slider) on = &joint;
        if (joint.kind == JoltWorld::JointKind::Slider) break;
    }

    if (on != nullptr) {
        constexpr double kFastestHaul = 6.0;   // a hard haul, not a teleport
        const Vec3 gap = impl_->held_at - state.center_of_mass_world_m;
        Vec3 pull{};
        if (on->kind == JoltWorld::JointKind::Slider) {
            const auto found = impl_->index_of.find(on->a);
            const RigidSnapshot anchor =
                found != impl_->index_of.end()
                    ? impl_->world->snapshot(impl_->body_of[found->second])
                    : RigidSnapshot{};
            const Vec3 along = anchor.orientation_world.rotate(on->axis_local_a);
            const double got = impl_->world->hasJoint(on->rigid)
                                   ? impl_->world->jointState(on->rigid).at
                                   : 0.0;
            double wanted = dot(gap, along);
            wanted = std::max(on->lower - got, std::min(on->upper - got, wanted));
            const double speed =
                std::max(-kFastestHaul, std::min(kFastestHaul, wanted / dt_s));
            pull = speed * along;
            state.linear_velocity_m_s = pull;
            impl_->world->applyRigidState(id, state);
            impl_->world->wake(id);
            return;
        }

        // Everything else is PULLED, with a bounded force, and that is not the
        // same as being moved and does not reduce to it.
        //
        // Setting a velocity towards the hand looks like it should work and
        // does not, because a hard constraint cancels it inside the same step:
        // the hand gets one step of authority, never accumulates any, and so
        // can never win against anything stiff. Measured on a bow -- the hand
        // asked for a 300 mm draw, the string went taut, and the nocking point
        // moved 1.6 mm in fifty steps while the limbs stored a ten-thousandth
        // of a joule. From the outside that is a bow that cannot be drawn.
        //
        // A force accumulates. An archer pulls with however many newtons they
        // have and the bow yields until the two balance, which is what a draw
        // IS -- and the same bound is why a hand can heave a gate open and
        // cannot tear it off its hinges.
        const double far = length(gap);
        if (far > 1e-9) {
            // Full strength towards where the hand wants it, and that is the
            // whole of the rule.
            //
            // NOT "the force needed to close the gap this step, given this
            // body's mass", which was the first version and is wrong for the
            // reason a bowstring makes obvious: the thing in your fingers is a
            // nocking point weighing 87 grams, and the force required to move
            // IT is nothing like the force required to move what it is attached
            // to. Measured, that formula asked for 1,512 N however strong the
            // hand was declared to be, and a 16 kN/m bow would not draw with a
            // 6 kN hand.
            //
            // A hand does not know what it is pulling on. It pulls with what it
            // has, and the assembly yields or it does not.
            // Pull towards the target, brake against the speed, and clamp the
            // whole thing to what the hand has got. A hand that is not damped
            // does not hold anything: it slams its target, overshoots, hauls
            // back, and whatever it is attached to rings. Measured on a bow, an
            // undamped 6 kN hand read a different stored energy every time it
            // was asked, because the draw never settled.
            //
            // Full strength at 50 mm of error, and full braking at 8 m/s. Both
            // are a hand's own scale rather than the held body's, which is the
            // point: what the hand can do should not depend on the mass of the
            // thing in its fingers.
            //
            // 8 m/s and not 2. At 2 the braking term reached full strength
            // whenever the held thing was jostled at walking pace, cancelling
            // the pull outright -- a bow that stored 170 J with a plain capped
            // pull stored 7 with that hand, and drawing it further stored less.
            // A hand that stops everything is not a steadier hand.
            const RigidSnapshot now = impl_->world->snapshot(id);
            const double strength = impl_->hand_strength_n;
            // And never stiffer or more damped than the step can integrate. This
            // pull is pushed from outside the solver once a step, and an explicit
            // push past about 2 steps' worth of damping or 4 of stiffness puts
            // energy IN instead of taking it out. Bounded by the body's own mass
            // -- the least it can present, which is what it presents across the
            // way it is attached -- at 0.8 and 1.5 of those limits. Measured: a
            // bare bowstring (0.18 kg, its arrow shot) was "held" at a full 800 N
            // while it shook at brace, at 2.3 steps' worth of damping; and a
            // 2 kN hand spun a drawn test bow's arrow round at 12 m/s. A body
            // heavier than about half a kilogram is untouched by this: a gate is
            // hauled exactly as before. The real fix is a hand that pulls inside
            // the solver (docs/interaction-profiles.md).
            const double mass = impl_->world->mechanicalState(id).mass_kg;
            const double stiffness = mass > 0.0 ? std::min(strength / 0.05, 1.5 * mass / (dt_s * dt_s))
                                                : strength / 0.05;
            const double braking = mass > 0.0 ? std::min(strength / 8.0, 0.8 * mass / dt_s)
                                              : strength / 8.0;
            //
            // The brake is against the speed RELATIVE to the hand's own, so a
            // stroke can haul at speed; held still, it is the plain brake it
            // always was.
            Vec3 force = stiffness * gap -
                         braking * (now.linear_velocity_m_s - impl_->held_velocity);
            const double push = length(force);
            if (push > strength) force = (strength / push) * force;
            impl_->world->pushBody(id, force);
            // It acts in the coming step, and its work is counted there.
            impl_->haul_pushed = impl_->haul_pushed + force;
        }
        impl_->world->wake(id);
        return;
    }

    state.center_of_mass_world_m = impl_->held_at;
    state.orientation_world = impl_->held_facing;
    // A carried object does not accumulate speed from being carried; letting go
    // is what hands it back to gravity.
    state.linear_velocity_m_s = {};
    state.angular_velocity_rad_s = {};
    impl_->world->applyRigidState(id, state);
    // Held still at zero velocity is exactly what "has come to rest" looks like,
    // so a carried object puts itself to sleep within half a second of being
    // picked up unless this keeps saying otherwise. Asleep, it stops pushing
    // what it is carried into, and it does not fall when it is let go.
    impl_->world->wake(id);
}

void LiveWorld::release() {
    if (impl_->holding == static_cast<std::size_t>(-1)) return;
    // The hold was only the pose being re-asserted, so there is nothing to undo
    // -- but the object has spent the whole hold perfectly still, which is the
    // one thing a rigid solver reads as "stop simulating this". Letting go has
    // to put it back in the step, or it hangs in the air where it was released.
    // Watched: let go a metre up, still a metre up two seconds later. (A thing
    // that is not in the world -- set aside, park -- has nothing to wake, and
    // is let go of all the same.)
    if (impl_->inWorld(impl_->holding)) impl_->world->wake(impl_->body_of[impl_->holding]);
    impl_->holding = static_cast<std::size_t>(-1);
    impl_->wielding = false;
    impl_->hand_force = {};
    impl_->held_velocity = {};
    // Letting go ends a stroke. One that let go by itself has already said so.
    if (impl_->stroke) {
        impl_->stroke.reset();
        impl_->stroke_ended = "cancelled";
    }
}

void LiveWorld::forgetImpacts() { impl_->reported.clear(); }

std::vector<LiveImpact> LiveWorld::impacts(double quiet_speed_m_s) const {
    std::vector<LiveImpact> out;
    for (const LiveImpact &impact : impl_->reported)
        if (impact.closing_speed_m_s >= quiet_speed_m_s) out.push_back(impact);
    std::sort(out.begin(), out.end(), [](const LiveImpact &lhs, const LiveImpact &rhs) {
        return lhs.closing_speed_m_s > rhs.closing_speed_m_s;
    });
    return out;
}

// Everything waiting on an answer stays where it is. Rebuilt rather than
// patched, because there are five places that change what is waiting and a
// pinned body that nobody unpins never moves again.
// What everything is carrying, and whether it can hold it.
//
// Statics, not dynamics. Nothing here looks at a contact, because a thing at
// rest reports none: a plank bridging two piers with an iron block on it comes
// back with an empty contact ledger once it has settled, which is correct -- a
// ledger of impacts has no impacts to report -- and is why a shelf could be
// loaded until it should snap without anything ever asking.
//
// So it is asked from geometry. A sits on B when A's underside is within a
// whisker of B's top and they overlap from above. That gives what is stacked on
// what, and the weight follows from the cells and the density. O(bodies squared)
// on axis-aligned boxes, which is nothing for a room -- and is why it runs at a
// stride rather than every step.
void LiveWorld::surveyLoads() {
    impl_->overloaded.clear();
    impl_->bearing_on.clear();
    impl_->sustained_by.clear();
    const std::size_t count = impl_->described.size();
    if (count == 0) return;

    // Only what is in the world rests on anything or carries anything: a thing
    // set aside (park) is nowhere, and weighs on nothing. Read from the rigid
    // world rather than from poses(), which leaves such a thing out and so no
    // longer lines up with the body table.
    std::vector<Vec3> middle(count), half(count);
    std::vector<double> weight(count, 0.0);
    std::vector<bool> present(count, false);
    for (std::size_t i = 0; i < count; ++i) {
        if (!impl_->inWorld(i)) continue;
        // An exact body has no internal strength here to survey, and the box
        // this reads about a centre of mass is not where a compound is. It is
        // left out -- which also means a breakable thing it rests on does not
        // yet feel its weight here.
        if (impl_->isPrecise(i)) continue;
        present[i] = true;
        middle[i] = impl_->world->snapshot(impl_->body_of[i]).center_of_mass_world_m;
        half[i] = 0.5 * impl_->described[i].dimensions_m;
        const double cell = impl_->request.cell_size_m;
        // A box about the centre of mass is where a BOX is. A thing joined from
        // several shapes is somewhere else: a table's weight is nearly all in its
        // top, so that box stood 0.3 m proud of it and nothing put on the table
        // was found resting on it. Where its cells say it is more than half a
        // cell from that box, its cells are believed.
        if (!impl_->nodes_of[i].empty()) {
            const RigidSnapshot pose = impl_->world->snapshot(impl_->body_of[i]);
            Vec3 low{1e30, 1e30, 1e30}, high{-1e30, -1e30, -1e30};
            for (const std::uint32_t node : impl_->nodes_of[i]) {
                const Vec3 at = pose.center_of_mass_world_m + pose.orientation_world.rotate(impl_->cell_offset_m[node]);
                low = {std::min(low.x, at.x), std::min(low.y, at.y), std::min(low.z, at.z)};
                high = {std::max(high.x, at.x), std::max(high.y, at.y), std::max(high.z, at.z)};
            }
            const Vec3 centre = 0.5 * (low + high);
            const Vec3 reach = 0.5 * (high - low) + Vec3{0.5 * cell, 0.5 * cell, 0.5 * cell};
            const auto apart = [&](const Vec3 &a, const Vec3 &b) {
                return std::max({std::abs(a.x - b.x), std::abs(a.y - b.y), std::abs(a.z - b.z)}) > 0.5 * cell;
            };
            if (apart(centre, middle[i]) || apart(reach, half[i])) { middle[i] = centre; half[i] = reach; }
        }
        const double volume = static_cast<double>(impl_->nodes_of[i].size()) *
                              cell * cell * cell;
        const double density = i < impl_->density_of.size() ? impl_->density_of[i] : 0.0;
        weight[i] = volume * density * 9.81;
        // What it weighs now, where the thermal network holds it: a crate that
        // burns on a shelf gets lighter as it burns.
        if (impl_->thermo)
            if (const auto matter = impl_->thermo->matter(impl_->described[i].name))
                weight[i] = (matter->surface_kg + matter->core_kg) * 9.81;
    }

    // Who is sitting on whom. A whisker of slack because a body at rest sinks
    // into its support by the solver's penetration allowance -- exactly zero
    // would find nothing at all.
    constexpr double kWhisker = 0.02;
    const auto overlapsFromAbove = [&](std::size_t upper, std::size_t lower) {
        return std::abs(middle[upper].x - middle[lower].x) <
                   half[upper].x + half[lower].x &&
               std::abs(middle[upper].z - middle[lower].z) <
                   half[upper].z + half[lower].z;
    };
    const auto restsOn = [&](std::size_t upper, std::size_t lower) {
        if (upper == lower || !present[upper] || !present[lower]) return false;
        const double underside = middle[upper].y - half[upper].y;
        const double top = middle[lower].y + half[lower].y;
        return underside > top - kWhisker && underside < top + kWhisker &&
               overlapsFromAbove(upper, lower);
    };

    // What each body carries: everything stacked above it, however deep. Walked
    // upwards from each body rather than summed downwards, because a stack can
    // fork and the same crate must not be counted twice on one shelf.
    std::vector<double> carrying(count, 0.0);
    for (std::size_t base = 0; base < count; ++base) {
        if (impl_->described[base].anchored) continue;
        std::vector<bool> counted(count, false);
        std::vector<std::size_t> above;
        for (std::size_t i = 0; i < count; ++i)
            if (restsOn(i, base)) { above.push_back(i); counted[i] = true; }
        for (std::size_t at = 0; at < above.size(); ++at) {
            const std::size_t here = above[at];
            carrying[base] += weight[here];
            for (std::size_t i = 0; i < count; ++i)
                if (!counted[i] && restsOn(i, here)) { above.push_back(i); counted[i] = true; }
        }
    }

    // A thing that stands on the ground on its own feet: a table, which is a top
    // between its legs and all one body.
    //
    // The survey below looks for a beam held up by OTHER bodies and takes the
    // span between them, so a table -- nothing under it but the ground -- was
    // "falling, not carrying", and was never asked about whatever was piled on
    // it: measured through the Workshop's load test, five tonnes of iron on a
    // glass table. Nor would the whole body's box have been its section: legs
    // and all, that is most of a metre deep, where what bridges the gap is the
    // 40 mm of top.
    //
    // So both are read from the body's own cells, on their own grid and in the
    // body's own frame, which is right whichever way it faces. Its feet are the
    // cells whose underside is on the ground beneath them. Along each of its two
    // level axes the feet fall into runs, the widest gap between two runs is
    // the clear span, and the section is what is actually there in the middle of
    // that gap: in each column across it, the cells in one run down from the
    // top, which is the member the load sits on (a stretcher lower down is a
    // second beam, not more depth for this one). Its section modulus is summed
    // over those cells, which for a plain rectangle is b d^2 / 6 exactly. Feet
    // in one run -- a block, a plinth -- leave no gap, and nothing to bend.
    struct OwnFeet {
        bool stands{};
        double span_m{}, section_modulus_m3{};
    };
    const auto onItsOwnFeet = [&](std::size_t body) {
        OwnFeet best;
        const std::vector<std::uint32_t> &nodes = impl_->nodes_of[body];
        if (nodes.empty()) return best;
        const RigidSnapshot pose = impl_->world->snapshot(impl_->body_of[body]);
        const double cell = impl_->request.cell_size_m;
        // Which of its own axes is up. One that is not square to the ground is
        // tipping, and is not at rest under anything.
        int up = -1;
        double up_sign = 1.0;
        for (int axis = 0; axis < 3; ++axis) {
            const Vec3 unit{axis == 0 ? 1.0 : 0.0, axis == 1 ? 1.0 : 0.0, axis == 2 ? 1.0 : 0.0};
            const double y = pose.orientation_world.rotate(unit).y;
            if (std::abs(y) > 0.996) { up = axis; up_sign = y > 0.0 ? 1.0 : -1.0; }
        }
        if (up < 0) return best;
        const int level[2] = {(up + 1) % 3, (up + 2) % 3};
        const auto part = [](const Vec3 &v, int axis) { return axis == 0 ? v.x : axis == 1 ? v.y : v.z; };
        const Vec3 first = impl_->cell_offset_m[nodes.front()];
        struct Cell { long long at[3]; bool foot; };
        std::vector<Cell> cells;
        cells.reserve(nodes.size());
        const double reach = std::max(kWhisker, 0.25 * cell);
        for (const std::uint32_t node : nodes) {
            const Vec3 offset = impl_->cell_offset_m[node];
            Cell c{};
            for (int axis = 0; axis < 3; ++axis)
                c.at[axis] = std::llround((part(offset, axis) - part(first, axis)) / cell);
            c.at[up] = static_cast<long long>(up_sign) * c.at[up];
            const Vec3 world = pose.center_of_mass_world_m + pose.orientation_world.rotate(offset);
            const double ground = impl_->environment ? impl_->environment->terrain().heightAt(world.x, world.z)
                                                     : impl_->setup->ground_y;
            c.foot = std::abs(world.y - 0.5 * cell - ground) < reach;
            best.stands = best.stands || c.foot;
            cells.push_back(c);
        }
        if (!best.stands) return best;
        double worst = 0.0;
        for (const int along : level) {
            const int across = along == level[0] ? level[1] : level[0];
            std::set<long long> feet;
            for (const Cell &c : cells)
                if (c.foot) feet.insert(c.at[along]);
            // The widest gap between two runs of feet.
            long long gap = 0, from = 0, last = 0;
            bool any = false;
            for (const long long at : feet) {
                if (any && at - last - 1 > gap) { gap = at - last - 1; from = last; }
                last = at;
                any = true;
            }
            if (gap < 1) continue;
            const long long middle = from + (gap + 1) / 2;
            // What is there in the middle of it: each column's run down from the top.
            std::map<long long, std::set<long long>> column;
            for (const Cell &c : cells)
                if (c.at[along] == middle) column[c.at[across]].insert(c.at[up]);
            std::vector<long long> carrying_cells;
            for (const auto &[where, heights] : column) {
                long long at = *heights.rbegin();
                while (heights.count(at) != 0) carrying_cells.push_back(at--);
            }
            if (carrying_cells.empty()) continue;
            double mean = 0.0;
            for (const long long at : carrying_cells) mean += static_cast<double>(at);
            mean /= static_cast<double>(carrying_cells.size());
            double second_moment = 0.0, furthest = 0.0;
            for (const long long at : carrying_cells) {
                const double away = static_cast<double>(at) - mean;
                second_moment += 1.0 / 12.0 + away * away;
                furthest = std::max(furthest, std::abs(away));
            }
            const double modulus = second_moment * cell * cell * cell / (furthest + 0.5);
            const double span = static_cast<double>(gap) * cell;
            // The worse of its two ways across: the longer span over the smaller section.
            if (!(modulus > 0.0) || span / modulus <= worst) continue;
            worst = span / modulus;
            best.span_m = span;
            best.section_modulus_m3 = modulus;
        }
        return best;
    };

    for (std::size_t i = 0; i < count; ++i) {
        if (impl_->described[i].anchored) continue;
        if (i == impl_->holding) continue;             // in a hand, not on anything
        static const bool survey_trace = std::getenv("BANJO_CUT_TRACE") != nullptr;
        const bool traced = survey_trace && impl_->kerfs.count(impl_->described[i].name) != 0;
        if (traced)
            std::fprintf(stderr, "survey %s carrying=%.1f N\n", impl_->described[i].name.c_str(),
                         carrying[i]);
        if (!(carrying[i] > 0.0)) continue;            // nothing on it: nothing to do

        // What is holding it up, and how far apart. A beam supported all along
        // its length has no span and cannot be bent -- which is the honest
        // reason a plate lying flat on the floor will not break however much is
        // piled on it.
        double leftmost = 1e30, rightmost = -1e30;
        bool held = false;
        for (std::size_t under = 0; under < count; ++under) {
            if (!restsOn(i, under)) continue;
            held = true;
            leftmost = std::min(leftmost, middle[under].x - half[under].x);
            rightmost = std::max(rightmost, middle[under].x + half[under].x);
        }
        // Nothing under it: falling, not carrying -- unless what is under it is
        // the ground, and it stands there on its own feet.
        const OwnFeet feet = held ? OwnFeet{} : onItsOwnFeet(i);
        if (!held && !feet.stands) continue;
        // The clear span: from the inner edge of one support to the inner edge
        // of the other, capped at the beam itself.
        double span = std::min(rightmost - leftmost, 2.0 * half[i].x);
        // Supports that touch along the whole length leave no clear span.
        double supported_length = 0.0;
        for (std::size_t under = 0; under < count; ++under) {
            if (!restsOn(i, under)) continue;
            supported_length += std::min(2.0 * half[under].x, 2.0 * half[i].x);
        }
        span = std::max(0.0, span - supported_length);
        if (!held) span = feet.span_m;
        if (!(span > 1e-3)) continue;                   // held everywhere: no bending

        // Section: breadth across the span, depth in the direction it bends --
        // of the REFERENCE box, as authored. What has burned away is taken out
        // once, by the section factor below (the field's rings); measuring the
        // stress on what is left AND applying that factor would take it twice.
        const Vec3 reference = referenceBoxOf(i);
        const double breadth = reference.z;
        const double depth = reference.y;
        if (!(breadth > 1e-6) || !(depth > 1e-6)) continue;

        // Simply supported, point load in the middle, plus its own weight as a
        // uniform load. The worst case for both, on purpose: this decides
        // whether the lattice is worth running, and it is meant to err towards
        // asking rather than towards silence.
        const double own_per_m = weight[i] / std::max(span, 1e-6);
        double stress = 3.0 * carrying[i] * span / (2.0 * breadth * depth * depth) +
                        3.0 * own_per_m * span * span / (4.0 * breadth * depth * depth);
        // On its own feet the section is the one its cells have in the middle of
        // the gap, and the same two moments go over its modulus: W L / 4 and
        // w L^2 / 8, which over b d^2 / 6 are the two terms above.
        if (!held)
            stress = (0.25 * carrying[i] * span + 0.125 * own_per_m * span * span) / feet.section_modulus_m3;
        // And at every cut it carries. A kerf across the span leaves the bonds
        // still alive across its plane as the only section there -- the
        // ligament -- so the bending there is the moment where the kerf is over
        // what that ligament can take. docs/cutting-model.md section 8.
        if (const auto cut = impl_->kerfs.find(impl_->described[i].name);
            cut != impl_->kerfs.end()) {
            double inner_left = -1e30, inner_right = 1e30;
            bool on_left = false, on_right = false;
            for (std::size_t under = 0; under < count; ++under) {
                if (!restsOn(i, under)) continue;
                if (middle[under].x < middle[i].x) {
                    inner_left = std::max(inner_left, middle[under].x + half[under].x);
                    on_left = true;
                } else {
                    inner_right = std::min(inner_right, middle[under].x - half[under].x);
                    on_right = true;
                }
            }
            const double clear = inner_right - inner_left;
            if (on_left && on_right && clear > 1e-3) {
                const RigidSnapshot at = impl_->world->snapshot(impl_->body_of[i]);
                const double cell = impl_->request.cell_size_m;
                const auto &bonds = impl_->setup->matter.bonds;
                for (const Impl::Kerf &kerf : cut->second) {
                    // Only a cut ACROSS the span takes out bending section.
                    if (kerf.swept.empty()) continue;
                    if (std::abs(at.orientation_world.rotate(kerf.w).x) < 0.7) continue;
                    double low_y = 1e30, high_y = -1e30, low_z = 1e30, high_z = -1e30;
                    double where = 0.0;
                    std::size_t alive = 0;
                    for (const auto &crossing : kerf.crossings) {
                        if (crossing.bond >= bonds.size() || !bonds[crossing.bond].alive) continue;
                        const Vec3 p = at.center_of_mass_world_m +
                                       at.orientation_world.rotate(crossing.at_local);
                        low_y = std::min(low_y, p.y);
                        high_y = std::max(high_y, p.y);
                        low_z = std::min(low_z, p.z);
                        high_z = std::max(high_z, p.z);
                        where += p.x;
                        ++alive;
                    }
                    if (alive == 0) continue;
                    where /= static_cast<double>(alive);
                    const double ligament_depth = high_y - low_y + cell;
                    const double ligament_breadth = high_z - low_z + cell;
                    const double a = std::clamp(where - inner_left, 0.0, clear);
                    const double moment = 0.5 * carrying[i] * std::min(a, clear - a) +
                                          0.5 * own_per_m * a * (clear - a);
                    stress = std::max(stress, 6.0 * moment /
                                                  (ligament_breadth * ligament_depth *
                                                   ligament_depth));
                    if (traced)
                        std::fprintf(stderr,
                                     "survey %s kerf: clear=%.3f a=%.3f moment=%.2f N m "
                                     "ligament %.4f x %.4f m (%zu bonds) -> %.3g Pa\n",
                                     impl_->described[i].name.c_str(), clear, a, moment,
                                     ligament_breadth, ligament_depth, alive,
                                     6.0 * moment /
                                         (ligament_breadth * ligament_depth * ligament_depth));
                }
            }
        }
        // A beam gives on whichever side of its section reaches its strength
        // first: the tension side by the tensile strength, the compression side
        // by the compressive one -- the lattice applies both, and so does this.
        // Oak's 52 MPa in compression is below its 90 in tension, so for oak the
        // compression side governs; a material that declares no compressive
        // strength is asked about in tension alone.
        const double tensile = i < impl_->tensile_of.size() ? impl_->tensile_of[i] : 0.0;
        const double compressive = i < impl_->compressive_of.size() ? impl_->compressive_of[i] : 0.0;
        const double cold_strength = compressive > 0.0 && compressive < tensile ? compressive : tensile;
        // What heat has left of each side of the section that carries the
        // bending: the same beam's section, three rings of it
        // (thermo/ThermalMechanics.hpp), with the span along x and the depth up,
        // as the formula above has it. One for anything the thermal network
        // does not hold, or whose material has no law.
        double tension_left = 1.0, compression_left = 1.0;
        std::string heated;
        std::optional<thermo::SectionState> heated_section;
        std::optional<thermo::MatterState> heated_matter;
        if (impl_->thermo) {
            const thermo::MechanicalLaw *law = thermo::lawFor(impl_->described[i].material);
            const std::optional<thermo::MatterState> matter =
                impl_->thermo->matter(impl_->described[i].name);
            if (law != nullptr && matter) {
                heated_section = thermo::evaluateSection(*law, *matter, reference, 0, 1);
                heated_matter = matter;
                tension_left = heated_section->bending;
                compression_left = heated_section->bending_compression;
            }
        }
        const double on_tension = tensile * tension_left;
        const double on_compression =
            compressive > 0.0 ? compressive * compression_left : std::numeric_limits<double>::infinity();
        const double strength = std::min(on_tension, on_compression);
        const bool compression_governs = on_compression < on_tension;
        const double capacity = cold_strength > 0.0 ? strength / cold_strength : 1.0;
        if (heated_section) {
            char text[320];
            std::snprintf(text, sizeof text,
                          "; heated: surface %.0f K, core %.0f K, %.1f mm %s away and %.1f mm "
                          "char, so its section holds %s of what it did cold",
                          heated_matter->surface_k, heated_matter->core_k, 1000.0 * heated_section->consumed_m,
                          goneWord(heated_matter->material).c_str(), 1000.0 * heated_section->char_m,
                          percent(capacity).c_str());
            heated = text;
        }
        if (traced)
            std::fprintf(stderr, "survey %s span=%.3f stress=%.3g Pa strength=%.3g Pa\n",
                         impl_->described[i].name.c_str(), span, stress, strength);
        if (!(cold_strength > 0.0)) continue;
        if (!(stress > strength)) continue;

        char said[200];
        std::snprintf(said, sizeof said, "bending %.3g MPa against the %.3g MPa it can take on its %s side",
                      stress / 1.0e6, strength / 1.0e6, compression_governs ? "compression" : "tension");
        impl_->overloaded.push_back(LiveOverload{impl_->described[i].name, carrying[i], span, stress,
                                                 strength, capacity, std::string(said) + heated});
        // And remember the heaviest thing sitting directly on it, so the
        // fracture has something to press with. Directly on it rather than the
        // heaviest in the whole stack: the lattice needs a body that is really
        // touching, and what is above THAT presses on it in turn.
        std::size_t heaviest = static_cast<std::size_t>(-1);
        double most = 0.0;
        for (std::size_t on_top = 0; on_top < count; ++on_top) {
            if (!restsOn(on_top, i)) continue;
            if (weight[on_top] <= most) continue;
            most = weight[on_top];
            heaviest = on_top;
        }
        if (heaviest != static_cast<std::size_t>(-1)) impl_->bearing_on[i] = heaviest;
        // And the whole of it, for statics: what it rests on, and every body
        // directly on it with the weight that body brings down.
        Impl::Sustained &sustained = impl_->sustained_by[impl_->described[i].name];
        sustained.on_ground = !held;
        for (std::size_t under = 0; under < count; ++under)
            if (restsOn(i, under)) sustained.on.push_back(impl_->described[under].name);
        for (std::size_t on_top = 0; on_top < count; ++on_top)
            if (restsOn(on_top, i))
                sustained.loads_n.emplace_back(impl_->described[on_top].name, weight[on_top] + carrying[on_top]);
    }
    // A body statics answered that no longer carries a sustained load -- what
    // rested on it was taken off, or fell -- is not under its load any more:
    // its answer and its throttle go, so no report says "under its load:
    // holds" of a beam with nothing on it. A body that broke keeps its answer,
    // the last thing said about it.
    for (auto it = impl_->sustained_answers.begin(); it != impl_->sustained_answers.end();) {
        if (impl_->index_of.count(it->first) != 0 && impl_->sustained_by.count(it->first) == 0) {
            impl_->statics_held.erase(it->first);
            it = impl_->sustained_answers.erase(it);
        } else {
            ++it;
        }
    }
}

std::vector<LiveOverload> LiveWorld::overloaded() const { return impl_->overloaded; }

void LiveWorld::repin() {
    impl_->held_for_fracture.clear();
    const auto pin = [&](const Pending &job) {
        // A body statics is answering is at rest under its load, and statics
        // puts any pieces where it rests: there is nothing for it to bounce away
        // from. Holding it -- its velocity zeroed and it woken after every step
        // the answer takes -- only upsets the contact that carries the load.
        // Measured in the owner's room (40 mm cells, answers not waited for):
        // each held answer left the 258 kg block about a millimetre deeper in the
        // beam it rested on, 4.1 mm to 9.3 mm over eight, and then the block
        // fell through a beam that had not broken.
        if (job.sustained) return;
        for (const std::size_t body : job.island_bodies)
            if (body < impl_->described.size() && !impl_->described[body].anchored)
                impl_->held_for_fracture.push_back(body);
    };
    if (impl_->pending && !impl_->pending->settled) pin(*impl_->pending);
    for (const auto &job : impl_->queued) pin(*job);
}

// Start the run for a collision that has not happened yet.
//
// The run costs about as long as a two-metre fall takes, and it used to start
// when the two things touched -- so you dropped something, it landed, and then
// it sat there for most of a second before coming apart. Measured on an iron
// ball onto a 20 mm pane: 856 ms between the contact and the pieces, with the
// world running at 99% of real time throughout. The clock was never the
// problem. The EVENT was late.
//
// So it starts on the way down instead, from where the two things are going to
// be. Nothing is pinned and nothing is told: the world carries on exactly as it
// would have, and if the collision turns up as expected the answer is already
// waiting. If it does not, the work is thrown away -- which costs a worker
// thread and nothing else.
void LiveWorld::guessAhead(const Foresight &guess, const std::string &name) {
    if (impl_->pending || impl_->guessing || !impl_->queued.empty()) return;
    if (guess.struck >= impl_->described.size()) return;
    // The hand is not a collision anybody is waiting on.
    // The thing in the hand can be the thing that DOES the breaking -- that is
    // what a hold guess is -- but not the thing broken.
    if (guess.struck == impl_->holding) return;
    std::unique_ptr<Pending> job = prepared(name, 0.003, &guess);
    if (job->settled) return;                    // nothing to run
    impl_->guess = guess;
    impl_->guess_unseen = 0;
    impl_->guessing = std::move(job);
    // Said out loud. A run that starts early and is never heard from again is
    // indistinguishable from one that never started, which cost an afternoon.
    // `lead_ms` carries the speed it is expecting, so the log can be read
    // against what actually turned up.
    impl_->delays.push_back({impl_->time_s, name, "guessing",
                             guess.arrival_speed_m_s, 0.0});
    Pending *running = impl_->guessing.get();
    running->started = std::chrono::steady_clock::now();
    impl_->guess_worker = std::async(std::launch::async, [running] { work(*running); });
}

void LiveWorld::dropGuess(const char *why) {
    if (!impl_->guessing) return;
    if (impl_->guess_worker.valid()) impl_->guess_worker.get();   // let it finish, then bin it
    impl_->delays.push_back({impl_->time_s, impl_->guessing->name, why, 0.0,
                             impl_->guessing->cost_ms, impl_->guessing->dt_s,
                             impl_->guessing->status.total_steps});
    impl_->guessing.reset();
}

// Is the run that is already going the run for THIS collision?
//
// A guess is built from where things were going to be, and what actually turned
// up has to match it or the answer describes a different impact. Three things
// are checked: the same thing struck, by the same thing, arriving at close to
// the speed that was expected. The speed is the one that matters -- it sets how
// much energy goes into the lattice, and the whole answer turns on it.
bool LiveWorld::adoptGuess(const std::string &name) {
    if (!impl_->guessing) return false;
    if (impl_->guessing->name != name) { dropGuess("guess-wasted"); return false; }

    // What actually hit it, and how hard.
    double came_in = 0.0;
    std::string by;
    for (const LiveImpact &impact : impl_->last_impacts) {
        if (impact.struck != name) continue;
        if (impact.closing_speed_m_s >= came_in) { came_in = impact.closing_speed_m_s; by = impact.by; }
    }
    const double expected = impl_->guessing->guessed_speed;
    const bool same_striker = impl_->guessing->guessed_striker.empty()
                                  ? by == "the ground"
                                  : by == impl_->guessing->guessed_striker;
    // Five per cent of the speed, because the energy handed to the lattice goes
    // as the square of it: five per cent of speed is ten of energy, and fifteen
    // would have been a third. Measured on clean drops the prediction is out by
    // 0.18%, so this is a bar against a DIFFERENT collision turning up, not
    // against the arithmetic.
    const bool same_speed = expected > 0.0 &&
                            std::abs(came_in - expected) <= 0.05 * expected;
    if (!same_striker || !same_speed) {
        // Worth knowing WHY, or a guess that is never adopted looks like a
        // guess that is never made.
        impl_->delays.push_back({impl_->time_s, name, "guess-missed",
                                 expected, came_in});
        dropGuess("guess-wasted");
        return false;
    }

    if (impl_->guess_worker.valid()) impl_->guess_worker.get();
    // NOW it has had its chance at this contact. prepare() records that for a
    // run it starts itself, and a guess deliberately does not -- a prediction
    // about a later collision must not stop the world reporting a different
    // impact in the meantime. But adopting one IS the body having its chance,
    // and without this a thing that held was never written down as having held:
    // the world went on offering the same break, the step went on being taken
    // back, and it deadlocked exactly as the handshake is designed not to.
    impl_->held_through.insert(name);
    // How far out the prediction was, as a percentage of the speed it expected.
    // This is the one number that says whether looking ahead is sound: the
    // arrival speed is what sets the energy going into the lattice, and the
    // whole answer turns on it.
    impl_->guess_error_pct = 100.0 * std::abs(came_in - expected) / expected;
    impl_->pending = std::move(impl_->guessing);
    impl_->worker = std::future<void>{};          // already run
    return true;
}

// Capture every break the world is refusing to step past, so it can step.
void LiveWorld::queueBreaks() {
    for (const std::string &name : breakable()) {
        if (impl_->pending && impl_->pending->name == name) continue;
        bool already = false;
        for (const auto &waiting : impl_->queued)
            already = already || waiting->name == name;
        if (already) continue;
        // Capacity: a cascade can want dozens at once, and each one holds an
        // island's worth of lattice. Past this the world goes back to stopping,
        // which is slow but bounded -- unlike memory.
        if (impl_->queued.size() >= 16) {
            impl_->delays.push_back({impl_->time_s, name, "blocked", 0.0, 0.0});
            continue;
        }
        std::unique_ptr<Pending> job = prepared(name, impl_->pending->window_s);
        if (job->settled) continue;          // nothing to run; it will be re-heard
        impl_->delays.push_back({impl_->time_s, name, "queued", 0.0, 0.0});
        impl_->queued.push_back(std::move(job));
        repin();
    }
}

// Take the next one waiting and put it on the worker.
void LiveWorld::startNextQueued() {
    // One lattice run at a time. A guess is speculative and the queue is not.
    if (!impl_->queued.empty()) dropGuess("guess-wasted");
    while (!impl_->queued.empty()) {
        impl_->pending = std::move(impl_->queued.front());
        impl_->queued.pop_front();
        if (impl_->pending->settled) {       // nothing to run; apply it and move on
            applyPending();
            impl_->pending.reset();
            continue;
        }
        Pending *job = impl_->pending.get();
        job->started = std::chrono::steady_clock::now();
        job->waited_ms = 1000.0 * std::chrono::duration<double>(
            job->started - job->began).count();
        impl_->worker = std::async(std::launch::async, [job] { work(*job); });
        repin();
        return;
    }
    repin();
}

// The queue's indices are into the body table, and applying a fracture erases
// the island it broke from that table. Everything above those slots shifts
// down -- the same fixup `holding` already gets a few lines below the drop.
//
// A queued job whose island shared a body with the one just applied is not
// fixable and must go: the thing it was going to break has itself just come
// apart, and its pieces are new and untried. They will be heard on their own.
// Where everything ended up, given where it was.
//
// `before` is the body table's names in index order, taken just before whatever
// rearranged it. Names are unique and a body keeps its name across a rebuild, so
// they are what survives an operation that indices do not.
//
// Counting how many slots below an index were erased is NOT enough, and getting
// that wrong is what this is written the long way to prevent. A body that came
// through a fracture whole keeps its name and is erased and RE-APPENDED at the
// end: it has not gone, so nothing counts it as gone, and yet every index above
// its old slot has moved down by one. Queued jobs then held indices one too
// high, and the next apply erased the body next door -- measured, an iron ball
// dropped on a plate quietly destroyed two anchored piers, one of them across
// the room, and the only sign was scenery missing afterwards.
void LiveWorld::restackQueue(const std::vector<std::string> &before) {
    std::unordered_map<std::string, std::size_t> now;
    for (std::size_t i = 0; i < impl_->described.size(); ++i)
        now.emplace(impl_->described[i].name, i);

    constexpr std::size_t kGone = static_cast<std::size_t>(-1);
    std::vector<std::size_t> moved(before.size(), kGone);
    for (std::size_t i = 0; i < before.size(); ++i) {
        const auto found = now.find(before[i]);
        if (found != now.end()) moved[i] = found->second;
    }
    const auto follow = [&](std::size_t was) {
        return was < moved.size() ? moved[was] : kGone;
    };

    std::deque<std::unique_ptr<Pending>> keeping;
    for (auto &job : impl_->queued) {
        // A job whose subject or island no longer exists cannot be applied: the
        // thing it was going to break has itself come apart, and its pieces are
        // new and untried.
        bool lost = follow(job->which) == kGone;
        for (const std::size_t body : job->island_bodies)
            lost = lost || follow(body) == kGone;
        if (lost) continue;

        job->which = follow(job->which);
        if (job->anvil != kGone) {
            const std::size_t anvil = follow(job->anvil);
            job->anvil = anvil;            // kGone here simply means "no anvil"
        }
        for (std::size_t &body : job->island_bodies) body = follow(body);
        std::unordered_map<std::size_t, RigidSnapshot> poses;
        for (auto &entry : job->poses_before) poses.emplace(follow(entry.first), entry.second);
        job->poses_before = std::move(poses);
        for (auto &entry : job->body_of_node) entry.second = follow(entry.second);
        keeping.push_back(std::move(job));
    }
    impl_->queued = std::move(keeping);
}

// Take the loose pieces near a point out of the world, and say what they were.
//
// A room that shatters fills up: every pane is dozens of shards that will lie
// where they fell for as long as the world is open, and past a couple of
// thousand bodies the reversible trial cannot run, which is what breaking
// depends on. Sweeping them up is the natural answer -- they are debris, and
// somebody walking through the room is the obvious thing to sweep with.
//
// What is taken is deliberately narrow. Only a piece -- a "hull", which is what
// something that broke or bent becomes, never an authored object, so walking
// past a bowl does not pocket it. Never anchored scenery, never what is in a
// hand, and never anything an unfinished fracture is holding an index to.
//
// What comes back is what the pieces were MADE of, added up by material, which
// is the useful form: nobody wants forty entries called "glass plate 20mm
// piece 31", they want to know they now have 400 grams of glass.
std::vector<LiveCollected> LiveWorld::collect(const Vec3 &at, double radius_m,
                                              std::size_t largest_cells,
                                              const std::string &except) {
    std::vector<LiveCollected> haul;
    if (!(radius_m > 0.0)) return haul;
    const double reach = radius_m * radius_m;
    const double cell_volume = impl_->request.cell_size_m * impl_->request.cell_size_m *
                               impl_->request.cell_size_m;

    // Anything a fracture still has an index into stays. Its job holds body
    // numbers, and taking one out from under it would either resurrect a body
    // that is gone or write a piece back onto somebody else's slot.
    std::set<std::size_t> spoken_for;
    const auto reserve = [&](const Pending &job) {
        for (const std::size_t body : job.island_bodies) spoken_for.insert(body);
    };
    if (impl_->pending) reserve(*impl_->pending);
    for (const auto &job : impl_->queued) reserve(*job);

    std::vector<std::size_t> taking;
    for (std::size_t i = 0; i < impl_->described.size(); ++i) {
        const LiveBodyPose &body = impl_->described[i];
        // A hull is not enough: a dented whole object is a hull too, and it is
        // still the object it was. Only what came off something is debris.
        if (body.anchored || !body.fragment) continue;
        if (i == impl_->holding || spoken_for.count(i)) continue;
        // Held by the person, in a hand this side does not keep: not debris.
        if (!except.empty() && body.name == except) continue;
        if (i >= impl_->nodes_of.size() || impl_->nodes_of[i].size() > largest_cells) continue;
        if (!impl_->world->contains(impl_->body_of[i])) continue;
        // From where the body IS, not from where `described` remembers it.
        // `described` carries the pose a body was built with and poses() is
        // what refreshes it from the world -- so reading it here found every
        // piece sitting at the origin, a fixed 3.06 m from the plate they came
        // off. A sweep of 3 m collected nothing and a sweep of 50 m collected
        // the room, which is the shape of a bug that looks like a tuning problem.
        const Vec3 gap = impl_->world->snapshot(impl_->body_of[i]).center_of_mass_world_m - at;
        if (dot(gap, gap) > reach) continue;
        taking.push_back(i);
    }
    if (taking.empty()) return haul;

    // Added up by what it is, not by which shard it was.
    std::map<std::string, LiveCollected> by_material;
    for (const std::size_t i : taking) {
        const std::size_t cells = impl_->nodes_of[i].size();
        const double density = i < impl_->density_of.size() ? impl_->density_of[i] : 0.0;
        LiveCollected &into = by_material[impl_->described[i].material];
        into.material = impl_->described[i].material;
        into.cells += cells;
        into.pieces += 1;
        into.kilograms += static_cast<double>(cells) * cell_volume * density;
        into.took.push_back(impl_->described[i].name);
    }
    for (auto &entry : by_material) haul.push_back(std::move(entry.second));

    dropBodies(taking);
    return haul;
}

// Take bodies out of the world and out of every table that is parallel to it.
//
// The tables are indexed in step, so an erase shifts everything above it -- and
// three other things hold indices into them: the hand, the fracture being
// worked out, and anything queued behind it. Missing one of those does not
// crash, it silently moves somebody else's body, which is far worse.
void LiveWorld::dropBodies(const std::vector<std::size_t> &which) {
    // Whatever a body held leaves the world with it, and the ledger says so.
    if (impl_->thermo)
        for (const std::size_t body : which)
            if (body < impl_->described.size()) impl_->thermo->remove(impl_->described[body].name);
    // What was where, so anything still holding an index can follow it.
    std::vector<std::string> before;
    before.reserve(impl_->described.size());
    for (const LiveBodyPose &pose : impl_->described) before.push_back(pose.name);
    std::vector<std::size_t> going = which;
    std::sort(going.begin(), going.end(), std::greater<std::size_t>());
    going.erase(std::unique(going.begin(), going.end()), going.end());
    for (const std::size_t body : going) {
        if (body >= impl_->body_of.size()) continue;
        // A thing set aside goes too, should it ever be asked to: destroyed
        // where it is kept (JoltWorld::removeAndDestroy), and set aside no more.
        const MatterBodyId id = impl_->body_of[body];
        if (impl_->world->contains(id) || impl_->world->parked(id)) impl_->world->removeAndDestroy(id);
        if (body < impl_->described.size()) {
            impl_->matter_of.erase(impl_->described[body].name);
            impl_->parked.erase(impl_->described[body].name);
        }
        const auto drop = [&](auto &vector) {
            if (body < vector.size())
                vector.erase(vector.begin() + static_cast<std::ptrdiff_t>(body));
        };
        drop(impl_->described); drop(impl_->body_of); drop(impl_->nodes_of);
        drop(impl_->limits_of); drop(impl_->impedance_of); drop(impl_->density_of);
        drop(impl_->tensile_of); drop(impl_->compressive_of);
        if (impl_->holding != static_cast<std::size_t>(-1) && impl_->holding > body)
            --impl_->holding;
    }
    // A guess holds indices into these tables as well, and unlike a queued job
    // it is speculative -- so it is thrown away rather than carefully followed.
    // It cost a worker thread and nothing else.
    dropGuess("guess-wasted");
    restackQueue(before);
    impl_->index_of.clear();
    for (std::size_t i = 0; i < impl_->described.size(); ++i)
        impl_->index_of.emplace(impl_->described[i].name, i);
    rehangJoints();
    repin();
}

bool LiveWorld::steppedBack() const { return impl_->stepped_back; }

LiveOutcome LiveWorld::lastOutcome() const { return impl_->last_outcome; }

LiveBreakCost LiveWorld::lastBreak() const { return impl_->last_break; }

// What a crack costs here, before anything breaks: the law in force, the charge
// it makes per square metre at this cell size, and what the material declares.
LiveBreakCost LiveWorld::crackCost(const std::string &name) const {
    Impl &I = *impl_;
    LiveBreakCost cost{};
    cost.cell_size_m = I.request.cell_size_m;
    cost.failure_law = std::string(bondFailureLawName(I.request.failure_law));
    const auto found = I.index_of.find(name);
    if (found == I.index_of.end() || I.isPrecise(found->second)) return cost;
    const MaterialDefinition &made_of = I.definitionOf(found->second);
    cost.material = made_of.name;
    cost.declared_energy_j_m2 = made_of.fracture_energy_j_m2;
    // The same compile the room's own lattice uses for this material
    // (TileImpactScene): the elastic reference, then the law in force.
    const CompiledBrittleMaterial compiled = withFailureLaw(
        compileElasticLatticeReference(made_of, I.request.cell_size_m, I.request.neighbor_horizon_cells),
        made_of, I.request.cell_size_m, I.request.neighbor_horizon_cells);
    const LatticeHorizonGeometry g = latticeHorizonGeometry(I.request.neighbor_horizon_cells);
    cost.law_energy_j_m2 = g.crossings_100 * made_of.young_modulus_pa * I.request.cell_size_m *
                           compiled.damage_end_stretch * compiled.damage_end_stretch /
                           (2.0 * static_cast<double>(I.request.neighbor_horizon_cells));
    cost.bounded_by_strength = compiled.strength_bound_active;
    return cost;
}

std::vector<LiveDelay> LiveWorld::delays() const { return impl_->delays; }
void LiveWorld::forgetDelays() { impl_->delays.clear(); }
void LiveWorld::foreseeCollisions(double horizon_s) {
    impl_->foresee_horizon_s = std::max(0.0, horizon_s);
}

// Look ahead for a collision that is going to need the lattice.
//
// A ray along each moving body's own path says what is in front of it and how
// far; its speed says how long until it gets there. The same admission test the
// step uses then says whether that arrival would need the lattice at all. What
// comes out is a name and an amount of warning -- and warning is the whole
// point, because the run costs about as long as a two-metre fall takes.
//
// Cheap, but not free: a ray is 0.02 ms and there can be a hundred bodies. So
// it is asked at a stride, and only of things actually going somewhere.
void LiveWorld::foresee() {
    if (!(impl_->foresee_horizon_s > 0.0)) return;
    constexpr std::uint64_t kStride = 8;   // ~30 times a second at a live rate
    if (impl_->steps_taken % kStride != 0) return;

    std::set<std::string> still_coming;
    for (std::size_t i = 0; i < impl_->described.size(); ++i) {
        const LiveBodyPose &body = impl_->described[i];
        // Nor anything set aside (park): it is not going anywhere.
        if (body.anchored || i == impl_->holding || !impl_->inWorld(i)) continue;
        // An exact body cannot go into the run a warning would start
        // (prepared), whichever end of the blow it is.
        if (impl_->isPrecise(i)) continue;
        const RigidSnapshot now = impl_->world->snapshot(impl_->body_of[i]);
        const double speed = length(now.linear_velocity_m_s);
        // Below this nothing can be admitted anywhere in the catalogue, so
        // there is nothing to look for.
        if (speed < 0.5) continue;
        // From the leading surface, not the centre, or the ray starts inside
        // the body and meets it.
        const Vec3 heading = (1.0 / speed) * now.linear_velocity_m_s;
        const double clear = 0.5 * std::max({body.dimensions_m.x, body.dimensions_m.y,
                                             body.dimensions_m.z}) + 0.005;
        const double reach = speed * impl_->foresee_horizon_s;
        const RayHit ahead = impl_->world->castRay(
            now.center_of_mass_world_m + clear * heading, heading, reach);
        if (!ahead.hit) continue;
        // How fast it will be going when it gets there, not how fast it is
        // going now. This is the whole difference between foresight and a
        // running commentary: a ball a metre up is barely moving and would fail
        // every admission test, and by the time its present speed clears the
        // bar it is nine milliseconds from the thing it is about to break.
        //
        // Falling accelerates it, so the arrival speed comes from the drop
        // still to go: v^2 = u^2 + 2*g*h. Rising or level, the drop is negative
        // and it arrives no faster than it is going.
        constexpr double kGravity = 9.80665;
        const double falling = -ahead.distance_m * heading.y;   // metres of drop left
        const double arrival =
            std::sqrt(std::max(0.0, speed * speed + 2.0 * kGravity * std::max(0.0, falling)));
        // Time to contact at the average of the two speeds, which is exact for
        // constant acceleration along the path and near enough otherwise.
        const double lead_s = 2.0 * ahead.distance_m / std::max(0.1, speed + arrival);

        // Would that arrival need the lattice? The same question the step asks,
        // asked early. Impedance from whatever is in the way, or the ground's
        // when the ray stopped on something with no id of ours.
        // The limits are the STRUCK body's, and the impedance is the striker's
        // -- that is the way round admitRefracture reads them, and it matters:
        // a glass pane hit by iron and an iron ball hit by glass have very
        // different answers from the same contact.
        FragmentFractureLimits struck = impl_->limits_of[i];
        double other = impl_->impedance_of[i];
        if (ahead.named) {
            for (std::size_t k = 0; k < impl_->body_of.size(); ++k)
                if (impl_->body_of[k] == ahead.body_id) { struck = impl_->limits_of[k]; break; }
        } else {
            // The floor. Nothing of ours is struck, so ask about the mover --
            // against the ground that is actually there: sand where the ray
            // came down on sand, rock on rock.
            struck = impl_->limits_of[i];
            other = impl_->environment ? impl_->environment->contactImpedanceAt(ahead.point_world_m)
                                       : impl_->ground_impedance;
        }
        const RefractureAdmission would = admitRefracture(struck, other, arrival,
                                                          std::numeric_limits<double>::max());
        if (!would.worthRunning()) continue;

        // Name what is about to be HIT, where there is one. That is what the
        // lattice will be run on, and what the warning is for. A ray that
        // stopped on the floor has no name, so the mover is named instead.
        std::string about = body.name;
        if (ahead.named)
            for (std::size_t k = 0; k < impl_->body_of.size(); ++k)
                if (impl_->body_of[k] == ahead.body_id) { about = impl_->described[k].name; break; }
        still_coming.insert(about);
        // Start it now, from where the two of them are going to be. Everything
        // this needs has just been worked out to decide whether to warn at all.
        if (!impl_->guessing && !impl_->pending && impl_->queued.empty()) {
            Foresight guess{};
            guess.striker = i;
            guess.arrival_speed_m_s = arrival;
            guess.struck = i;
            if (ahead.named)
                for (std::size_t k = 0; k < impl_->body_of.size(); ++k)
                    if (impl_->body_of[k] == ahead.body_id) { guess.struck = k; break; }
            // Where it will be when it gets there, going as fast as it will be
            // going. The rest of its state -- how it is turned, how it is
            // spinning -- carries over unchanged, which is right for the short
            // flight that is left.
            guess.striker_state = now;
            guess.striker_state.center_of_mass_world_m =
                now.center_of_mass_world_m + ahead.distance_m * heading;
            guess.striker_state.linear_velocity_m_s = arrival * heading;
            guess.would_break = would.admitted();
            if (guess.struck != guess.striker) guessAhead(guess, about);
        }
        if (impl_->foreseen.count(about)) continue;   // already said
        impl_->delays.push_back({impl_->time_s, about, "foreseen", lead_s * 1000.0, 0.0});
    }
    guessWhatIsHeld(still_coming);
    // A guess whose collision has stopped being expected for a while is not
    // going to be adopted. For a WHILE: see guess_unseen above.
    if (impl_->guessing) {
        impl_->guess_unseen = still_coming.count(impl_->guessing->name)
                                  ? 0 : impl_->guess_unseen + 1;
        if (impl_->guess_unseen >= 4) dropGuess("guess-wasted");
    } else {
        impl_->guess_unseen = 0;
    }
    impl_->foreseen.swap(still_coming);
}

// What would happen if the thing in the hand were let go right now.
//
// The warning a fall gives can never be longer than the fall. Measured on a
// concrete pane, whose run costs about 810 ms: a 4 m drop gives 702 ms of
// warning and the pieces are 147 ms late; a 0.6 m drop gives 268 ms and they are
// 573 ms late. Below about three and a half metres there is simply not enough
// air to work in, and no amount of looking further ahead creates any.
//
// But somebody holding a ball over a pane has already given us all the warning
// anyone could want -- seconds of it -- and nothing was being done with it. So
// the run for the drop they are lining up starts while they are still lining it
// up. If they move, the guess is thrown away and made again; if they throw it
// instead of dropping it the arrival speed will not match and it is refused.
// Being wrong costs a worker thread.
void LiveWorld::guessWhatIsHeld(std::set<std::string> &still_coming) {
    if (impl_->holding == static_cast<std::size_t>(-1)) return;
    if (impl_->pending || !impl_->queued.empty()) return;
    const std::size_t held = impl_->holding;
    if (held >= impl_->described.size() || !impl_->inWorld(held)) return;
    const RigidSnapshot now = impl_->world->snapshot(impl_->body_of[held]);

    // Straight down, from underneath it.
    const LiveBodyPose &body = impl_->described[held];
    const double clear = 0.5 * std::max({body.dimensions_m.x, body.dimensions_m.y,
                                         body.dimensions_m.z}) + 0.005;
    const Vec3 down{0.0, -1.0, 0.0};
    const RayHit below = impl_->world->castRay(
        now.center_of_mass_world_m + clear * down, down, 40.0);
    if (!below.hit || !below.named) return;

    std::size_t struck = static_cast<std::size_t>(-1);
    for (std::size_t k = 0; k < impl_->body_of.size(); ++k)
        if (impl_->body_of[k] == below.body_id) { struck = k; break; }
    if (struck == static_cast<std::size_t>(-1) || struck == held) return;
    if (impl_->described[struck].anchored) return;
    if (impl_->isPrecise(struck) || impl_->isPrecise(held)) return;

    constexpr double kGravity = 9.80665;
    const double arrival = std::sqrt(2.0 * kGravity * std::max(0.0, below.distance_m));
    if (arrival < 0.5) return;
    const RefractureAdmission would = admitRefracture(
        impl_->limits_of[struck], impl_->impedance_of[held], arrival,
        std::numeric_limits<double>::max());
    if (!would.worthRunning()) return;

    const std::string about = impl_->described[struck].name;
    still_coming.insert(about);
    // Already working on this exact drop? Then leave it alone. Re-making the
    // guess every time the hand wobbles a millimetre would mean never finishing
    // one.
    if (impl_->guessing) {
        const bool same = impl_->guessing->name == about &&
                          std::abs(impl_->guessing->guessed_speed - arrival) <=
                              0.02 * std::max(0.5, arrival);
        if (same) return;
        dropGuess("guess-wasted");
    }
    if (impl_->pending) return;

    Foresight guess{};
    guess.striker = held;
    guess.struck = struck;
    guess.arrival_speed_m_s = arrival;
    guess.striker_state = now;
    guess.striker_state.center_of_mass_world_m =
        now.center_of_mass_world_m + below.distance_m * down;
    guess.striker_state.linear_velocity_m_s = arrival * down;
    guess.would_break = would.admitted();
    guessAhead(guess, about);
}

std::vector<std::string> LiveWorld::breakable() const {
    std::vector<std::string> out;
    for (const LiveImpact &impact : impl_->last_impacts) {
        // Either bound. The name is a hangover from when breaking was the only
        // thing the lattice was ever run for; what it means is "the lattice has
        // something to say about this one", and a dent is one of the things it
        // can say.
        if (!impact.would_break && !impact.would_dent) continue;
        if (impl_->held_through.count(impact.struck)) continue;
        // Gone: it broke, and what it became carries different names. Or set
        // aside (park): it is not in the world to be broken.
        if (impl_->index_of.find(impact.struck) == impl_->index_of.end()) continue;
        if (impl_->parked.count(impact.struck) != 0) continue;
        if (std::find(out.begin(), out.end(), impact.struck) == out.end())
            out.push_back(impact.struck);
    }
    // And anything carrying more than it can hold up. From the outside these
    // are the same question -- this thing may come apart, do you want to know --
    // and a host that only handled blows would never be offered a shelf.
    //
    // declineBreak silences them the same way it silences a contact, which
    // matters more here than there: a load does not go away by itself, so an
    // overloaded shelf would otherwise be offered on every survey for ever.
    for (const LiveOverload &sagging : impl_->overloaded) {
        if (impl_->held_through.count(sagging.name)) continue;
        if (impl_->index_of.find(sagging.name) == impl_->index_of.end()) continue;
        if (impl_->parked.count(sagging.name) != 0) continue;
        // Statics has answered this very load on this very section: it held.
        // Asked again once heat has weakened the section or more is piled on.
        if (const auto held = impl_->statics_held.find(sagging.name); held != impl_->statics_held.end() &&
            sagging.capacity_fraction > held->second.capacity_fraction * (1.0 - kStaticsAskAgain) &&
            sagging.carrying_n < held->second.carrying_n * (1.0 + kStaticsAskAgain))
            continue;
        if (std::find(out.begin(), out.end(), sagging.name) == out.end())
            out.push_back(sagging.name);
    }
    return out;
}

void LiveWorld::declineBreak(const std::string &name) {
    // The same record fracture() keeps, without the lattice run: this body has
    // had its chance at this contact.
    impl_->held_through.insert(name);
}

void LiveWorld::prepare(const std::string &name, double window_s) {
    impl_->pending = prepared(name, window_s);
}

double LiveWorld::sceneLatticeStep_s() const { return impl_->setup ? impl_->setup->dt_s : 0.0; }

std::unique_ptr<LiveWorld::Pending> LiveWorld::prepared(const std::string &name,
                                                        double window_s,
                                                        const Foresight *guess) {
    auto held = std::make_unique<Pending>();
    Pending &job = *held;
    job.name = name;
    job.window_s = window_s;
    // Whatever happens below, this object has now had its chance at this
    // contact. Recording that here rather than at each of the five ways out is
    // what stops one of them being forgotten and deadlocking the world.
    //
    // Not for a guess. A guess is about a collision that has not happened, so
    // the body has had no chance at anything yet -- and marking it would stop
    // the world reporting a DIFFERENT impact on it in the meantime, which is a
    // real break quietly suppressed by a prediction about a later one.
    if (!guess) impl_->held_through.insert(name);
    impl_->last_outcome = LiveOutcome::Nothing;
    // What this one costs, before it has cost anything: the law in force and
    // what it charges for a crack in the thing being asked about.
    impl_->last_break = crackCost(name);
    const auto found = impl_->index_of.find(name);
    if (found == impl_->index_of.end()) { job.settled = true; job.answer = 0; return held; }
    const std::size_t which = found->second;
    // Anchored scenery is the world. Breaking the floor is a different feature.
    impl_->last_outcome = LiveOutcome::Held;
    if (impl_->described[which].anchored) { job.settled = true; job.answer = 1; return held; }
    if (impl_->holding == which) { job.settled = true; job.answer = 1; return held; }   // it is in a hand, not in a collision
    // An exact body has no cells to break: it holds, as it was built to.
    if (impl_->isPrecise(which)) { job.settled = true; job.answer = 1; return held; }
    const TileImpactSetup &setup = *impl_->setup;
    // Whatever struck it goes into the island too. A body on its own, entered
    // after the contact, is a free-flying object with a uniform velocity and no
    // stress anywhere in it: it cannot break however hard it was hit. Both
    // bodies are cut from the same parent lattice, so the island is simply the
    // union of their cells, and running it resolves the collision through the
    // failure criterion rather than through Jolt's contact solver.
    std::vector<std::size_t> island_bodies{which};
    // Scenery that was struck, kept aside. It does not go INTO the island --
    // it is immovable, and putting immovable matter into a lattice run is
    // paying to solve something whose answer is "it did not move". But it must
    // not simply be dropped either, which is what used to happen: a ball that
    // hit an anchored anvil was re-entered on its own, a free-flying object
    // with a uniform velocity and nothing to press against, and came away a
    // perfect sphere however hard it was driven in. Below, it becomes what it
    // physically is -- a surface that does not give.
    std::size_t anvil = static_cast<std::size_t>(-1);
    // Whether what it is run against struck it, as against resting on it.
    bool struck = false;
    {
        // A guess names its own striker: partner_of is written by the step that
        // saw the contact, and for a collision that has not happened there is
        // no such step yet.
        std::size_t with = static_cast<std::size_t>(-1);
        if (guess) {
            with = guess->striker;
            struck = true;
        } else {
            const auto partner = impl_->partner_of.find(which);
            if (partner != impl_->partner_of.end()) {
                with = partner->second;
                struck = true;
            } else if (impl_->sustained_by.count(name) != 0) {
                // No contact caused this: it is a load rather than a blow, and
                // statics answers it (fracture/SustainedLoad.hpp). The body goes
                // in alone; what it rests on holds it up and what rests on it
                // presses on it, as forces and supports rather than as matter.
                //
                // It used to go in with the heaviest thing sitting on it and
                // nothing under it, for a few milliseconds of a wave: measured
                // (tests/thermal_geometry_tests.cpp), plank and load then fell
                // freely together and the plank broke -- or held -- on how far
                // the load's cells had sunk into it, not on the load.
                job.sustained = true;
            } else {
                // No contact and no load the survey knows of: the body alone,
                // as the host asked.
                const auto bearing = impl_->bearing_on.find(which);
                if (bearing != impl_->bearing_on.end()) with = bearing->second;
            }
        }
        // A held body is normally kept out of an island: it is in a hand, not in
        // a collision. A guess that names it is saying what will happen when it
        // is let go, and its state is overridden to the moment it lands, so it
        // belongs in the island exactly like anything else that is falling.
        const bool in_a_hand = with == impl_->holding && !(guess && guess->striker == with);
        // Nor does an exact body go in: an island is cells, and it would be
        // rebuilt from cells it does not have -- deleted, in fact. The step
        // declines a blow that would need one (judgeStep); a body merely
        // resting on one runs alone, as against the floor.
        if (with != static_cast<std::size_t>(-1) && with < impl_->described.size() &&
            !in_a_hand && !impl_->isPrecise(with)) {
            if (impl_->described[with].anchored) anvil = with;
            else island_bodies.push_back(with);
        }
    }
    for (const std::size_t body : island_bodies)
        if (!impl_->world->contains(impl_->body_of[body])) { job.settled = true; job.answer = 0; return held; }
    // What the island is, for anyone asking why a run said what it said.
    // What heat has done to the matter in this island, read now: each body's
    // cells are still in that body's own frame, and the loop below moves them
    // into the struck body's. docs/thermal-mechanics.md, "One material state".
    const std::unique_ptr<HeatedCells> heated = heatedCellsOf(island_bodies);
    // Where a body is, or -- for the one thing that has not arrived yet -- where
    // it is going to be. Everything below asks through this, so a run started
    // early is built from the collision as it is expected to happen.
    std::unordered_map<std::size_t, RigidSnapshot> at;
    for (const std::size_t body : island_bodies)
        at.emplace(body, guess && body == guess->striker
                             ? guess->striker_state
                             : impl_->world->snapshot(impl_->body_of[body]));
    // And the one that struck, from where it met the other -- which is not
    // always where the rigid step left it.
    //
    // The step taken back is the one in which the contact was REPORTED, and a
    // fast body can be well into what it hit by then: the rigid world moved it a
    // whole step, 89 mm at 10.7 m/s, and found the contact only on the next.
    // Measured on the iron ball dropped 5.95 m onto the 20 mm glass plate, the
    // state handed to the lattice had the ball 10 mm into the plate. The lattice
    // cannot start there. Two cells inside one another with no bond between them
    // are thrown apart at once, which is energy the impact never had: bonds
    // failed on the first substep, 215 J went into them against 15 to 40 J for a
    // clean hit, and an iron ball that had not cleared half its own breaking bar
    // came out in eleven pieces.
    //
    // So the one moving in is put back along its way in until no cell of it is
    // nearer a cell of the other than two cells touching -- where it was when
    // they met. A translation, like the lift below: its speed and spin are its
    // own and the closing speed is untouched. Something that is resting on the
    // body has no way in, and is left where it is.
    if (struck && island_bodies.size() == 2) {
        const std::size_t one = island_bodies[0], two = island_bodies[1];
        const bool first_moves =
            length(at[one].linear_velocity_m_s) >= length(at[two].linear_velocity_m_s);
        const std::size_t mover = first_moves ? one : two, other = first_moves ? two : one;
        const Vec3 closing = at[mover].linear_velocity_m_s - at[other].linear_velocity_m_s;
        const double closing_m_s = length(closing);
        if (closing_m_s > 1.0e-6) {
            const Vec3 back = (-1.0 / closing_m_s) * closing;
            const double touching =
                2.0 * impl_->request.node_contact_radius_factor * impl_->request.cell_size_m;
            const auto cellsOf = [&](std::size_t body) {
                std::vector<Vec3> cells;
                cells.reserve(impl_->nodes_of[body].size());
                const RigidSnapshot &pose = at[body];
                for (const std::uint32_t node : impl_->nodes_of[body])
                    cells.push_back(pose.center_of_mass_world_m +
                                    pose.orientation_world.rotate(impl_->cell_offset_m[node]));
                return cells;
            };
            // The other body's cells, bucketed at the touching distance, so any
            // pair near enough to matter is in neighbouring buckets.
            const auto bucket = [&](const Vec3 &p) {
                return std::array<long long, 3>{static_cast<long long>(std::floor(p.x / touching)),
                                                static_cast<long long>(std::floor(p.y / touching)),
                                                static_cast<long long>(std::floor(p.z / touching))};
            };
            std::map<std::array<long long, 3>, std::vector<Vec3>> by_bucket;
            for (const Vec3 &cell : cellsOf(other)) by_bucket[bucket(cell)].push_back(cell);
            const std::vector<Vec3> moving = cellsOf(mover);
            double back_m = 0.0;
            // Going back along its way in takes it away from what it was driven
            // into, but could bring it nearer some other part of the same body,
            // so it is looked at again from where it got to.
            for (int pass = 0; pass < 8; ++pass) {
                double further = 0.0;
                for (const Vec3 &cell : moving) {
                    const Vec3 p = cell + back_m * back;
                    const std::array<long long, 3> k = bucket(p);
                    for (long long dx = -1; dx <= 1; ++dx)
                        for (long long dy = -1; dy <= 1; ++dy)
                            for (long long dz = -1; dz <= 1; ++dz) {
                                const auto there = by_bucket.find(
                                    std::array<long long, 3>{k[0] + dx, k[1] + dy, k[2] + dz});
                                if (there == by_bucket.end()) continue;
                                for (const Vec3 &q : there->second) {
                                    const Vec3 r = p - q;
                                    const double r2 = dot(r, r);
                                    if (r2 >= touching * touching) continue;
                                    // How much further back puts this pair exactly
                                    // touching: |r + t * back| = touching.
                                    const double along = dot(r, back);
                                    further = std::max(
                                        further, -along + std::sqrt(along * along - r2 +
                                                                    touching * touching));
                                }
                            }
                }
                if (!(further > 1.0e-9)) break;
                back_m += further;
            }
            at[mover].center_of_mass_world_m = at[mover].center_of_mass_world_m + back_m * back;
        }
    }
    const auto stateOf = [&](std::size_t body) { return at.at(body); };
    const MatterBodyId old_body = impl_->body_of[which];
    const RigidSnapshot snap = stateOf(which);

    // Every cell of every body in the island, in parent numbering. Each body's
    // cells are placed by ITS own rigid pose, which is what buildFragmentLattice
    // does for one body -- so the offsets are rewritten into the frame the
    // island will be built in, one body at a time.
    //
    // Into a copy. The table is each body's own shape in its own frame, every
    // later island that body is in reads it again, and only an apply writes it
    // back -- while a run prepared here may never be applied: a guess that is
    // not adopted, a queued job dropped, a run in which nothing happened.
    // Rewriting it in place left the striker's cells in the frame of whatever
    // it last struck. Measured on an iron ball dropped 6 m onto a 20 mm glass
    // plate: the guess made while it was held put the ball's cells 75 mm above
    // the ball, so every run at the real contact started with the ball 75 mm
    // further off than it was, and the plate broke or not according to whether
    // that 75 mm could be closed inside the run's window -- which is to say by
    // the phase of the drop within a step. The run queued behind it was another
    // 100 mm out, and a body rebuilt from such a run was put where its
    // misplaced cells had got to.
    std::vector<Vec3> island_offset_m = impl_->cell_offset_m;
    std::vector<std::uint32_t> island_nodes;
    std::unordered_map<std::uint32_t, std::size_t> body_of_node;
    std::unordered_map<std::size_t, RigidSnapshot> poses_before;
    for (const std::size_t body : island_bodies) {
        const RigidSnapshot pose = stateOf(body);
        poses_before.emplace(body, pose);
        for (const std::uint32_t node : impl_->nodes_of[body]) {
            island_nodes.push_back(node);
            body_of_node.emplace(node, body);
            // Where this cell is in the STRUCK body's frame, so that one pose
            // places the whole island correctly.
            const Vec3 world = pose.center_of_mass_world_m +
                               pose.orientation_world.rotate(impl_->cell_offset_m[node]);
            // Into the struck body's frame. A unit quaternion's inverse is its
            // conjugate, and Quat carries no operation for it.
            const Quat inverse{snap.orientation_world.w, -snap.orientation_world.x,
                               -snap.orientation_world.y, -snap.orientation_world.z};
            island_offset_m[node] = inverse.rotate(world - snap.center_of_mass_world_m);
        }
    }

    // The rigid solver tolerates a penetration the lattice's support projection
    // does not: a cell centre below the floor is pushed back up THROUGH its
    // bonds, which injects energy that has nothing to do with the impact. Lift
    // the island clear first -- a rigid translation, so no momentum and no
    // kinetic energy change -- and refuse outright if it is buried deeper than
    // half a cell, rather than hand the lattice a state it will explode on.
    //
    // Buried, which is not the same as on its way in. The step taken back is
    // the one in which the contact was REPORTED, and a body landing fast is well
    // into the floor by then for the same reason a striker is well into what it
    // struck (above): at the room's 1/120 s a table coming down at 10.8 m/s
    // moves 90 mm a step, more than two 40 mm cells. Counting that as burial
    // made the answer a matter of where in a step the floor happened to be.
    // Measured on the Workshop's glass table against its 8.7 m/s bar: dropped
    // 4 m it was caught 14 mm short of the floor and broke into 40; dropped 6 m
    // it was caught 25 mm inside, and at 10 and 16 m deeper still, the contact
    // said would_break each time and the answer was "held" with no run made. A
    // harder landing held where a softer one broke. So the depth a cell can owe
    // to its own body's way in -- what that cell moves into the plane in one
    // step -- is not burial, and lifting it out is putting the body back where
    // it was when it met the floor. Only what is deeper than that is refused.
    double lift = 0.0, on_its_way_in = 0.0;
    {
        const SupportSet<double> &support = setup.settings_world.support;
        const double step_s = impl_->last_dt_s > 0.0 ? impl_->last_dt_s : 1.0 / 240.0;
        for (const std::uint32_t node : island_nodes) {
            const Vec3 position = snap.center_of_mass_world_m +
                snap.orientation_world.rotate(island_offset_m[node]);
            for (std::uint32_t p = 0; p < support.plane_count; ++p) {
                const SupportPlane<double> &plane = support.planes[p];
                if (plane.normal.y < 0.999) continue;
                if (!insideFootprints(plane, toV3(position))) continue;
                const double depth =
                    dot(toV3(position) - plane.point, plane.normal) - plane.node_radius;
                if (-depth <= lift) continue;
                lift = -depth;
                // This cell's own speed into the plane: its body's, with its spin.
                const RigidSnapshot &owner = poses_before.at(body_of_node.at(node));
                const Vec3 velocity = owner.linear_velocity_m_s +
                    cross(owner.angular_velocity_rad_s, position - owner.center_of_mass_world_m);
                on_its_way_in = std::max(0.0, -velocity.y) * step_s;
            }
        }
    }
    if (lift > 0.5 * impl_->request.cell_size_m + on_its_way_in) {
        job.settled = true; job.answer = 1; return held;
    }

    const FragmentPose pose{snap.center_of_mass_world_m + Vec3{0.0, lift, 0.0},
                            snap.orientation_world, snap.linear_velocity_m_s,
                            snap.angular_velocity_rad_s};
    FragmentLattice island = buildFragmentLattice(
        setup.matter, island_nodes, island_offset_m, pose,
        impl_->plastic_extension_m, impl_->plastic_strain_m);
    // buildFragmentLattice places every cell with ONE rigid pose, because it was
    // written for one fragment: position, orientation AND velocity all come from
    // that pose. An island of two bodies therefore arrives with the struck
    // body's velocity on both of them -- the ball sits in exactly the right
    // place with exactly the wrong speed, the closing speed is zero, and 2,174
    // substeps later nothing has broken. Give every cell back the velocity of
    // the body it actually belongs to.
    for (std::size_t local = 0; local < island.parent_node.size(); ++local) {
        const std::uint32_t node = island.parent_node[local];
        const auto owner = body_of_node.find(node);
        if (owner == body_of_node.end() || owner->second == which) continue;
        const RigidSnapshot pose = poses_before[owner->second];
        const Vec3 arm = island.matter.nodes[local].position_world_m - pose.center_of_mass_world_m;
        island.matter.nodes[local].velocity_m_s =
            pose.linear_velocity_m_s + cross(pose.angular_velocity_rad_s, arm);
    }
    // Two bodies are two bodies. The scene's matter still holds as whole the
    // bonds that broke when a body came apart -- an applied run rebuilds its
    // bodies from its components and writes nothing back there -- so an island
    // of two pieces of one thing took in the bonds between them alive,
    // stretched across whatever gap had opened since. Measured on the owner's
    // two beams (tests/thermal_geometry_tests.cpp): two pieces of the heated
    // beam 79 mm apart, of 3 and 2 cells, went into a run at 4.8 and 5.4 m/s
    // and came out one body at 97.5 m/s. A bond between cells of different
    // bodies starts broken.
    for (std::size_t k = 0; k < island.matter.bonds.size() && k < island.matter.asset->bonds.size(); ++k) {
        const BondRest &rest = island.matter.asset->bonds[k];
        if (rest.node_a >= island.parent_node.size() || rest.node_b >= island.parent_node.size()) continue;
        const auto end_a = body_of_node.find(island.parent_node[rest.node_a]);
        const auto end_b = body_of_node.find(island.parent_node[rest.node_b]);
        if (end_a == body_of_node.end() || end_b == body_of_node.end() || end_a->second == end_b->second)
            continue;
        island.matter.bonds[k].alive = false;
        island.matter.bonds[k].damage = 1.0;
    }
    // A heated body's cells weigh what the network says is left, and its bonds
    // carry what the law leaves them -- the same field its section, its shape
    // and its report are read from. Nothing cold is touched.
    heatIsland(island, *heated, name, true);
    LatticeState island_state = buildLatticeState(island.matter, island.schedule, island.origin);
    for (std::size_t k = 0; k < island_state.bond_count; ++k) {
        const std::uint32_t o = island.schedule.bond_order[k];
        island_state.plastic_extension[k] = island.plastic_extension_m[o];
        island_state.plastic_strain[k] = island.plastic_strain_m[o];
    }
    // The step this run is taken at: the one ITS lattice needs -- the bodies in
    // it, as heat and earlier breaks have left them -- at the scene's fraction of
    // it (dt_factor), which is the step they would take in a room of their own.
    // The scene's step is set at open by the stiffest, lightest thing anywhere in
    // the room, so an alumina cup on a shelf made every run in the room, of oak
    // or glass or ice, take that cup's step: 1.7 times as many steps for a glass
    // pane under an iron ball. Not for the same answer, though. A break near its
    // bar comes out one way or the other by the step: the pane under the ball in
    // tests/scene_joint_tests.cpp, dropped from 5 m, broke into five pieces or
    // one at steps within 20% of the room's with no trend between them, and into
    // 13 at half the room's step. What the room no longer does is pick the step.
    // A body heat has left lighter, which rings faster than it did cold, gets
    // the shorter step it needs, where the scene's cold one was too long.
    const double own_limit_s = latticeStateSubstepLimit(island_state);
    const double dt_s = own_limit_s > 0.0 ? impl_->request.dt_factor * own_limit_s : setup.dt_s;
    job.dt_s = dt_s;

    // The island alone: no striker, the same support planes the scene uses.
    StepSettings<double> settings = buildSettings(setup, island.origin, dt_s);
    // Yield from the struck body's OWN material.
    //
    // buildSettings takes it from the scene's default matter, because there is
    // one plastic_yield_stretch for the whole solve and the single-tile lane
    // has one material to put in it. In a scene of objects that default is
    // glass, which has no yield point at all -- so an iron ball being hammered
    // into an anvil was solved with a yield stretch of zero and could not take
    // a permanent set however hard it was hit. An island is one body, or a body
    // and the thing that struck it, so the struck body's material is the one
    // that belongs here.
    const MaterialDefinition *struck_material = &setup.tile_material;
    if (setup.multi_body && !setup.part_of_node.empty() && !impl_->nodes_of[which].empty()) {
        const std::uint32_t part = setup.part_of_node[impl_->nodes_of[which].front()];
        if (part < setup.part_definitions.size()) {
            const MaterialDefinition &own = setup.part_definitions[part];
            struck_material = &own;
            const bool yields = own.yield_strength_pa > 0.0 && own.young_modulus_pa > 0.0;
            settings.plastic_yield_stretch =
                yields ? own.yield_strength_pa / own.young_modulus_pa : 0.0;
            settings.plastic_hardening = yields ? std::max(0.0, own.hardening_ratio) : 0.0;
        }
    }
    // The solve takes one yield stretch, the struck body's: a yield strength
    // over a modulus, so heat moves it by its strength's factor over its
    // stiffness's, averaged over its cells (declared).
    if (settings.plastic_yield_stretch > 0.0) {
        const auto mean = heated->mean.find(impl_->described[which].name);
        if (mean != heated->mean.end() && mean->second.stiffness > kSoftestBond)
            settings.plastic_yield_stretch *= mean->second.tension / mean->second.stiffness;
    }
    // The scenery it was driven into, as the surface it is.
    //
    // A support plane is exactly "a thing that does not give", which is what
    // anchored matter is, and the lattice already has the ground as one. The
    // footprint is the body's own extent, so the island is stopped where the
    // scenery actually is and passes beside it where it is not.
    //
    // Horizontal only: the plane's normal is +Y. So this is a table top, an
    // anvil, a floor -- the cases where something is driven DOWN into
    // something. A wall or a tilted ramp is not covered, and would need a
    // plane that can face any direction.
    if (anvil != static_cast<std::size_t>(-1) && impl_->inWorld(anvil) &&
        settings.support.plane_count < kMaxSupportPlanes) {
        const RigidSnapshot on = impl_->world->snapshot(impl_->body_of[anvil]);
        const Vec3 half = 0.5 * impl_->described[anvil].dimensions_m;
        const double top = on.center_of_mass_world_m.y + half.y;
        // How the struck body meets the scenery, from the two materials.
        const MaterialDefinition &anvil_material =
            setup.multi_body && !impl_->nodes_of[anvil].empty() &&
                    setup.part_of_node[impl_->nodes_of[anvil].front()] <
                        setup.part_definitions.size()
                ? setup.part_definitions[setup.part_of_node[impl_->nodes_of[anvil].front()]]
                : setup.ground_material;
        const CombinedContactMaterial against = combineContactMaterials(
            compileContactMaterial(*struck_material), compileContactMaterial(anvil_material));
        SupportPlane<double> plane{};
        const SupportPlaneFrame frame = makeSupportPlane(
            Vec3{on.center_of_mass_world_m.x, top, on.center_of_mass_world_m.z} - island.origin,
            Vec3{0.0, 1.0, 0.0});
        plane.point = toV3(frame.point_world_m);
        plane.normal = toV3(frame.normal_world);
        plane.tangent = toV3(frame.tangent_world);
        plane.bitangent = toV3(frame.bitangent_world);
        plane.restitution = against.restitution;
        plane.static_friction = against.static_friction;
        plane.dynamic_friction = against.dynamic_friction;
        plane.node_radius = impl_->request.node_contact_radius_factor * impl_->request.cell_size_m;
        plane.reach_capped = 1;
        plane.footprint_count = 1;
        plane.footprints[0] = {0.0, 0.0, half.x, half.z};
        settings.support.planes[settings.support.plane_count++] = plane;
    }
    settings.node_contact.bucket_mask =
        latticeContactBucketMask(static_cast<std::uint32_t>(island.matter.nodes.size()));
    settings.sphere_enabled = 0U;
    SphereState<double> parked = setup.sphere_world;
    parked.center = {0.0, 1.0e4, 0.0};
    parked.velocity = {0.0, 0.0, 0.0};
    parked.angular_velocity = {0.0, 0.0, 0.0};

    const auto stepsFor = [&](double seconds) {
        return static_cast<std::uint64_t>(
            std::max<long long>(0, std::llround(seconds / dt_s)));
    };
    // A sustained load: supports and forces instead of a striker and a wave.
    std::unique_ptr<LatticeBackend> backend;
    // Char through: heat has left no bond in it carrying anything. Statics has
    // no strength to say where such a body gives, and would hand back one piece
    // per cell; said, and left as it is (docs/thermal-mechanics.md).
    if (job.sustained &&
        std::none_of(island.matter.bonds.begin(), island.matter.bonds.end(),
                     [](const ActiveBondState &bond) { return bond.alive; })) {
        impl_->delays.push_back({impl_->time_s, name, "char through", 0.0, 0.0});
        Impl::SustainedAnswer &answer = impl_->sustained_answers[name];
        answer = {};
        answer.time_s = impl_->time_s;
        answer.stop = "char through: no bond in it carries anything, so statics cannot say where it gives";
        for (const LiveOverload &o : impl_->overloaded)
            if (o.name == name) impl_->statics_held[name] = {o.capacity_fraction, o.carrying_n};
        job.settled = true;
        job.answer = 1;
        return held;
    }
    if (job.sustained) {
        const Impl::Sustained &sustained = impl_->sustained_by.at(name);
        const double cell = impl_->request.cell_size_m;
        const std::size_t count = island.matter.nodes.size();
        job.load.loads_n.assign(count, Vec3{});
        // Its own weight, cell by cell, each cell as heat has left it.
        for (std::size_t local = 0; local < count; ++local)
            job.load.loads_n[local] = island.matter.nodes[local].mass_kg * impl_->request.gravity_m_s2;
        const Vec3 down = normalized(impl_->request.gravity_m_s2, Vec3{0.0, -1.0, 0.0});
        // A body's box as it stands now -- what the survey measured from.
        const auto boxOf = [&](const std::string &who, Vec3 &centre, Vec3 &half) {
            const auto found = impl_->index_of.find(who);
            if (found == impl_->index_of.end() || !impl_->world->contains(impl_->body_of[found->second]))
                return false;
            centre = impl_->world->snapshot(impl_->body_of[found->second]).center_of_mass_world_m;
            half = 0.5 * impl_->described[found->second].dimensions_m;
            return true;
        };
        // Held from below: its bottom cells over each thing it rests on.
        std::set<std::uint32_t> holding_cells;
        for (const std::string &under : sustained.on) {
            Vec3 centre{}, half{};
            if (!boxOf(under, centre, half)) continue;
            const double top = centre.y + half.y;
            for (std::size_t local = 0; local < count; ++local) {
                const Vec3 p = island.matter.nodes[local].position_world_m;
                if (std::abs(p.x - centre.x) > half.x || std::abs(p.z - centre.z) > half.z) continue;
                if (p.y - top > cell || p.y < top - 0.5 * cell) continue;
                holding_cells.insert(static_cast<std::uint32_t>(local));
            }
        }
        // Held from below by the ground: its own feet, where the survey found
        // them -- the cells whose underside is on the ground beneath them.
        if (sustained.on_ground)
            for (std::size_t local = 0; local < count; ++local) {
                const Vec3 p = island.matter.nodes[local].position_world_m;
                const double ground = impl_->environment ? impl_->environment->terrain().heightAt(p.x, p.z)
                                                         : setup.ground_y;
                if (p.y - ground > cell || p.y < ground - 0.5 * cell) continue;
                holding_cells.insert(static_cast<std::uint32_t>(local));
            }
        job.load.supported_nodes.assign(holding_cells.begin(), holding_cells.end());
        job.supported_cells = holding_cells.size();
        // Pressed from above: the weight each thing on it brings down, shared
        // among its top cells under that thing.
        for (const auto &[over, newtons] : sustained.loads_n) {
            Vec3 centre{}, half{};
            if (!boxOf(over, centre, half)) continue;
            const double bottom = centre.y - half.y;
            std::vector<std::size_t> under_it;
            for (std::size_t local = 0; local < count; ++local) {
                const Vec3 p = island.matter.nodes[local].position_world_m;
                if (std::abs(p.x - centre.x) > half.x || std::abs(p.z - centre.z) > half.z) continue;
                if (p.y < bottom - cell) continue;
                under_it.push_back(local);
            }
            if (under_it.empty()) continue;
            for (const std::size_t local : under_it)
                job.load.loads_n[local] += (newtons / static_cast<double>(under_it.size())) * down;
            job.loaded_cells += under_it.size();
            job.load_n += newtons;
        }
        if (job.load.supported_nodes.empty()) {
            // Statics has no answer for a body nothing holds up: it would carry
            // nothing and say it held. Said, not guessed.
            impl_->delays.push_back({impl_->time_s, name, "no support", 0.0, 0.0});
            Impl::SustainedAnswer &answer = impl_->sustained_answers[name];
            answer = {};
            answer.time_s = impl_->time_s;
            answer.stop = "no support found under it";
            answer.load_n = job.load_n;
            job.settled = true;
            job.answer = 1;
            return held;
        }
    } else {
        backend = makeBackend(impl_->request, island.schedule);
        backend->upload(island_state, settings, parked);
    }
    RunControl control{};
    // What this run has to spend. A break may not take more energy out of the
    // world than the island brought into it: the kinetic energy of its cells
    // and the elastic energy its bonds already hold, both read off the state
    // the run is about to start from. No number anyone picked comes into it.
    //
    // It is an upper bound and not a tight one -- an island drifting past
    // something carries kinetic energy that no contact of its could ever turn
    // into cracks -- which is the right way round: the ceiling never invents
    // damage, it only refuses to keep paying for it.
    job.entry_kinetic_j = latticeStateKineticEnergy(island_state);
    job.entry_elastic_j = latticeStateElasticEnergy(island_state);
    control.removable_energy_j = job.entry_kinetic_j + job.entry_elastic_j;
    // The window has to cover the rigid step that was taken back BEFORE it can
    // cover the impact: the world is one step short of contact, so a ball at
    // 5 m/s is still up to a step's travel away when the lattice starts. A 3 ms
    // window on its own runs out while the ball is still in the air.
    control.max_steps =
        std::max<std::uint64_t>(1, stepsFor(window_s + impl_->last_dt_s));
    // The energy plateau still applies -- it only fires after something has
    // failed, and stopping once the removed energy is flat is the whole reason
    // this window can be short.
    control.min_steps = stepsFor(impl_->request.min_ms / 1000.0);
    control.energy_flat_steps = stepsFor(impl_->request.energy_flat_ms / 1000.0);
    control.energy_flat_fraction = impl_->request.energy_flat_fraction;
    // The calm exit does NOT apply here. It stops a run once nothing is near
    // failing, which is exactly the state a re-entry starts in while the two
    // bodies are still closing -- it would fire a millisecond in and end the
    // run before the impact it was opened for.
    control.calm_steps = 0;
    job.island = std::move(island);
    job.state = std::move(island_state);
    job.backend = std::move(backend);
    job.control = control;
    job.parked = parked;
    job.which = which;
    job.anvil = anvil;
    job.island_bodies = std::move(island_bodies);
    job.poses_before = std::move(poses_before);
    job.body_of_node = std::move(body_of_node);
    job.snap = snap;
    job.struck_material = struck_material;
    job.yield_extension = settings.plastic_yield_stretch * impl_->request.cell_size_m;
    // Who is allowed to come apart in this run: a body that a contact drove past
    // its own BREAKING bar. A dent needs no leave -- the permanent set a run
    // leaves is carried out of it whatever happens -- but a body that has cleared
    // only its denting bar has not reached the speed at which it can come apart,
    // and a threshold is the speed below which nothing CAN happen. That holds for
    // the body asked about as well. It used to be let come apart whatever it had
    // been asked about, and a dent is one of the things it is asked about for:
    // measured in the page, the iron ball that had just gone through the 20 mm
    // glass plate met a shard bouncing off the floor at 13.7 m/s, over its 10 m/s
    // denting bar and under its 25 m/s breaking one, and came out of its own run
    // in two to eight pieces while the page said it breaks above 25 m/s.
    //
    // The body asked about with no contact to judge it by keeps the leave it
    // always had: a load, which the survey found carrying more than it can hold,
    // and a collision still coming, judged at the speed it will arrive at.
    for (const std::size_t body : job.island_bodies) {
        const std::string &called = impl_->described[body].name;
        bool admitted = false, hit_here = false;
        for (const LiveImpact &impact : impl_->last_impacts) {
            if (impact.struck != called) continue;
            hit_here = true;
            admitted = admitted || impact.would_break;
        }
        if (body == which) {
            if (guess) admitted = guess->would_break;
            else if (!hit_here) admitted = true;
            for (const LiveOverload &load : impl_->overloaded)
                admitted = admitted || load.name == called;
        }
        if (!admitted) continue;
        if (body < impl_->nodes_of.size())
            for (const std::uint32_t node : impl_->nodes_of[body]) job.may_break.insert(node);
    }
    job.began = std::chrono::steady_clock::now();
    job.started = job.began;
    if (guess) {
        job.guessed = true;
        job.guessed_speed = guess->arrival_speed_m_s;
        job.guessed_at = guess->striker_state.center_of_mass_world_m;
        if (guess->striker < impl_->described.size())
            job.guessed_striker = impl_->described[guess->striker].name;
    }
    return held;
}

// The only part that takes any time, and the only part that touches nothing
// shared. Safe to call from a worker.
void LiveWorld::work(Pending &job) {
    if (job.sustained) {
        // Statics on the body's own lattice; then the state the apply reads,
        // rebuilt from where equilibrium left it. Plastic set is carried
        // through untouched: statics adds no flow.
        job.statics = solveSustainedLoad(job.island.matter, job.load);
        LatticeState solved = buildLatticeState(job.island.matter, job.island.schedule, job.island.origin);
        solved.plastic_extension = job.state.plastic_extension;
        solved.plastic_strain = job.state.plastic_strain;
        job.state = std::move(solved);
        job.status = RunStatus{};
        job.status.broken_bonds = static_cast<std::uint32_t>(job.statics.bonds_removed);
        job.cost_ms = 1000.0 * std::chrono::duration<double>(
            std::chrono::steady_clock::now() - job.started).count();
        job.worked = true;
        return;
    }
    job.status = job.backend->run(job.control);
    job.backend->download(job.state, job.parked);
    job.cost_ms = 1000.0 * std::chrono::duration<double>(
        std::chrono::steady_clock::now() - job.started).count();
    job.worked = true;
}

std::size_t LiveWorld::applyPending() {
    Pending &job = *impl_->pending;
    if (job.settled) return job.answer;
    const std::string &name = job.name;
    // What statics said, for the reports and the log: how near its bonds came
    // to the criterion under the load, and what that cost.
    if (job.sustained) {
        Impl::SustainedAnswer &answer = impl_->sustained_answers[name];
        answer = {};
        answer.time_s = impl_->time_s;
        answer.stop = job.statics.stop;
        answer.load_n = job.load_n;
        answer.first_failure_ratio = job.statics.first_failure_ratio;
        answer.deflection_m = job.statics.first_deflection_m;
        answer.bonds_removed = job.statics.bonds_removed;
        answer.rounds = job.statics.rounds;
        answer.solves = job.statics.solves;
        answer.supported_cells = job.supported_cells;
        answer.loaded_cells = job.loaded_cells;
        answer.pieces = 1;
        answer.cost_ms = job.cost_ms;
        impl_->delays.push_back({impl_->time_s, name, "statics", 100.0 * job.statics.first_failure_ratio,
                                 job.cost_ms});
        // Still whole -- it held, or statics could not say (a solve that did not
        // converge, a round limit): remember against what, so the same question
        // is not asked again until heat weakens it or more is put on it. Asked
        // again unchanged, it would get the same answer at the same cost.
        impl_->statics_held.erase(name);
        if (job.statics.stop != "broke")
            for (const LiveOverload &o : impl_->overloaded)
                if (o.name == name) impl_->statics_held[name] = {o.capacity_fraction, o.carrying_n};
    }
    const RunStatus &status = job.status;
    FragmentLattice &island = job.island;
    LatticeState &island_state = job.state;
    const std::size_t which = job.which;
    const std::vector<std::size_t> &island_bodies = job.island_bodies;
    const auto &poses_before = job.poses_before;
    const auto &body_of_node = job.body_of_node;
    const RigidSnapshot &snap = job.snap;
    const TileImpactSetup &setup = *impl_->setup;
    writeBackLatticeState(island_state, island.schedule, island.matter);
    // Put back every bond that belongs to a body which was never admitted for
    // breaking at this contact. See Pending::may_break: the island must hold the
    // striker for the collision to have any stress in it, and holding it must
    // not be the same as condemning it. Every broken bond when nobody was
    // admitted: a body asked about for a dent alone is not admitted either, and
    // skipping that case, which used to be impossible, left an iron ball in
    // twelve pieces on a contact under its breaking bar.
    if (island.matter.asset != nullptr) {
        std::size_t revived = 0;
        for (std::size_t o = 0; o < island.matter.bonds.size() &&
                                o < island.matter.asset->bonds.size(); ++o) {
            if (island.matter.bonds[o].alive) continue;
            const BondRest &rest = island.matter.asset->bonds[o];
            if (rest.node_a >= island.parent_node.size() ||
                rest.node_b >= island.parent_node.size()) continue;
            const std::uint32_t a = island.parent_node[rest.node_a];
            const std::uint32_t b = island.parent_node[rest.node_b];
            // A bond inside a body that was allowed to break stays broken.
            if (job.may_break.count(a) && job.may_break.count(b)) continue;
            // And so does one between two bodies: it is inside neither, and
            // putting it back joined two bodies into one.
            const auto end_a = body_of_node.find(a), end_b = body_of_node.find(b);
            if (end_a == body_of_node.end() || end_b == body_of_node.end() || end_a->second != end_b->second)
                continue;
            island.matter.bonds[o].alive = true;
            island.matter.bonds[o].damage = 0.0;
            island.matter.bonds[o].failure_mode = BondFailureMode::None;
            ++revived;
        }
        if (revived > 0)
            impl_->delays.push_back({impl_->time_s, name, "spared",
                                     static_cast<double>(revived), 0.0});
    }
    // The permanent set the run left behind: bond lengths the material will not
    // give back. This is a dent. It is carried out of the island and into the
    // parent's own record, so the next hit starts from the shape this one left
    // rather than from the shape it was authored as.
    double dent_m = 0.0;
    Vec3 dent_at{};
    for (std::size_t k = 0; k < island_state.bond_count; ++k) {
        const std::uint32_t o = island.schedule.bond_order[k];
        const std::uint32_t parent_bond = island.parent_bond.empty()
                                              ? static_cast<std::uint32_t>(o)
                                              : island.parent_bond[o];
        // Only a body admitted to break or dent at this contact takes a set
        // from it. One that was only there to deliver the blow comes out as it
        // went in: its bonds are put back above, and its cells below.
        if (!job.may_break.empty() && island.matter.asset != nullptr &&
            o < island.matter.asset->bonds.size()) {
            const BondRest &rest = island.matter.asset->bonds[o];
            if (rest.node_a < island.parent_node.size() && rest.node_b < island.parent_node.size() &&
                !(job.may_break.count(island.parent_node[rest.node_a]) &&
                  job.may_break.count(island.parent_node[rest.node_b])))
                continue;
        }
        if (parent_bond < impl_->plastic_extension_m.size()) {
            impl_->plastic_extension_m[parent_bond] = island_state.plastic_extension[k];
            impl_->plastic_strain_m[parent_bond] = island_state.plastic_strain[k];
        }
        // And the damage, including a bond the run removed. This is the world's
        // own record of its matter, and until now nothing wrote a break into
        // it: a run's removals lived in the island, which is a copy, and the
        // pieces were told apart by which cells ended up connected. A bond
        // removed INSIDE a piece -- one whose going left the piece in one
        // piece -- was therefore forgotten, and came back alive the next time
        // that piece went into a run, stretched across the gap its going had
        // opened.
        //
        // Measured in tests-break before this line existed: an oak plank piece
        // came back with 59 of its 1,442 bonds alive and over a tenth of a
        // percent stretched, one of them joining two cells 35.2 mm apart that
        // want to be 20.0 mm. That piece entered its next run holding 31,167 J
        // of stretch -- seventy times the energy of the ball that broke the
        // plank -- and came out of it moving with 167 J having gone in with 13,
        // in 83 pieces. Energy out of nothing, and a shattering to go with it.
        if (parent_bond < impl_->setup->matter.bonds.size() && o < island.matter.bonds.size()) {
            const ActiveBondState &ran = island.matter.bonds[o];
            ActiveBondState &world = impl_->setup->matter.bonds[parent_bond];
            world.damage = ran.damage;
            world.peak_tensile_stretch = ran.peak_tensile_stretch;
            world.peak_compressive_strain = ran.peak_compressive_strain;
            world.peak_shear_strain = ran.peak_shear_strain;
            world.failure_mode = ran.failure_mode;
            // One way only: this run can remove a bond, and cannot bring one
            // back that an earlier run removed.
            if (!ran.alive) world.alive = false;
        }
        const double set_here = std::abs(island_state.plastic_extension[k]);
        if (set_here > dent_m) {
            dent_m = set_here;
            // Where it happened: the middle of the bond that took the set. In
            // the island's frame, which is the frame the cells are already in.
            // Which two cells the bond joins lives on the asset the island was
            // cut from; the state alongside it carries only how it is doing.
            if (island.matter.asset != nullptr && o < island.matter.asset->bonds.size()) {
                const BondRest &bond = island.matter.asset->bonds[o];
                if (bond.node_a < island.matter.nodes.size() &&
                    bond.node_b < island.matter.nodes.size())
                    dent_at = 0.5 * (island.matter.nodes[bond.node_a].position_world_m +
                                     island.matter.nodes[bond.node_b].position_world_m);
            }
        }
    }

    const auto island_components = findConnectedComponents(island.matter);
    // Nothing came apart. Usually that is the end of it -- the body held, and
    // it keeps the shape it was authored with.
    //
    // Unless it took a permanent set. A dent is not a break: the object is one
    // piece still, but it is not the shape it was, and an engine that throws
    // that away can only ever show things intact or in bits. So a body that
    // has yielded is rebuilt from where its matter actually ended up, which
    // makes it a hull -- because that IS its surface now, and no box or sphere
    // describes a dented thing.
    //
    // The bar is in the material's own units, not the grid's.
    //
    // It was a tenth of a cell -- 2 mm on a 20 mm cell -- which is a tenth of
    // permanent strain on one bond. Nothing reaches that without coming apart
    // first, so the test could never fire: an iron ball hammered into the floor
    // flowed 173 micrometres per bond, nine times what it took to start
    // flowing, and was still called unchanged.
    //
    // What "permanently deformed" means is set by where the material stops
    // springing back, so that is what it is measured against. Twice the yield
    // extension is past the point where the flow could be one substep's
    // overshoot rather than a set.
    const double yield_extension = job.yield_extension;
    const bool dented = yield_extension > 0.0 && dent_m > 2.0 * yield_extension;

    if (status.broken_bonds == 0 && island_components.size() <= 1 && !dented) return 1;
    if (island_components.empty()) return 1;


    // What was only there to deliver the blow goes back to how it was made to
    // sit, about the middle the run left it at: a body not admitted to break or
    // dent at this contact comes out of the run as it went in but for how it
    // moved -- its bonds put back and no set taken (above), its cells as they
    // were (here), and its name and its shape (below). Handed back with its
    // cells where the run had left them, a held body took whatever the run did
    // to them into the next run it was part of: measured on the owner's two
    // beams (tests/thermal_geometry_tests.cpp), a 212 kg iron block that had
    // been through several runs in the 30 ms before, its cells by then 0.13 m
    // from where its box touched a piece, came out of the next at 188 m/s.
    std::unordered_map<std::size_t, std::pair<LiveBodyPose, std::size_t>> held_pose;
    if (!job.may_break.empty()) {
        for (const std::size_t body : island_bodies) {
            if (body >= impl_->nodes_of.size() || impl_->nodes_of[body].empty()) continue;
            if (job.may_break.count(impl_->nodes_of[body].front())) continue;
            const auto before = poses_before.find(body);
            if (before == poses_before.end()) continue;
            std::vector<std::size_t> mine;
            double mass = 0.0;
            Vec3 middle{}, laid{};
            for (std::size_t local = 0; local < island.parent_node.size() && local < island.matter.nodes.size();
                 ++local) {
                const auto owner = body_of_node.find(island.parent_node[local]);
                if (owner == body_of_node.end() || owner->second != body) continue;
                const double m = island.matter.nodes[local].mass_kg;
                mine.push_back(local);
                mass += m;
                middle = middle + m * island.matter.nodes[local].position_world_m;
                laid = laid + m * before->second.orientation_world.rotate(impl_->cell_offset_m[island.parent_node[local]]);
            }
            if (mine.empty() || !(mass > 0.0)) continue;
            middle = (1.0 / mass) * middle;
            laid = (1.0 / mass) * laid;
            for (const std::size_t local : mine) {
                ActiveNodeState &node = island.matter.nodes[local];
                const Vec3 at = middle - laid +
                                before->second.orientation_world.rotate(impl_->cell_offset_m[island.parent_node[local]]);
                node.previous_position_world_m = node.previous_position_world_m + (at - node.position_world_m);
                node.position_world_m = at;
            }
            held_pose.emplace(body, std::make_pair(impl_->described[body], mine.size()));
        }
    }

    // It broke, or it bent. Either way it is not what it was, so replace it.
    FragmentBuildResult rebuilt = buildFragmentRepresentations(island.matter, island_components, {
        .first_body_id = impl_->next_body_id,
        .maximum_rigid_fragments = std::max<std::size_t>(1, island_components.size()),
        .minimum_nodes_per_rigid_fragment = 1,
        .maximum_collision_points = 192,
        .friction = setup.tile_ground.dynamic_friction,
        .restitution = setup.tile_ground.restitution,
    });
    // Where each body that is about to go stood, and how far it reached: what
    // rested on it or against it is woken once its pieces are in (below).
    std::vector<std::pair<Vec3, double>> gone_from;
    for (const std::size_t body : island_bodies)
        if (impl_->world->contains(impl_->body_of[body]))
            gone_from.emplace_back(impl_->world->snapshot(impl_->body_of[body]).center_of_mass_world_m,
                                   0.5 * length(impl_->described[body].dimensions_m) + 0.05);
    for (const std::size_t body : island_bodies)
        impl_->world->removeAndDestroy(impl_->body_of[body]);

    // A cell's part is what names its piece, so a ball that came through intact
    // is still the ball and the pane's shards are the pane's.
    std::vector<LiveBodyPose> parent_of_part(setup.part_bodies.size());
    std::vector<std::size_t> counted(setup.part_bodies.size(), 0);
    // Every part a body covers, not just the part of its first cell.
    //
    // A body used to be filed under its first cell alone, and a piece that is
    // itself made of pieces can span several parts. Any component whose
    // dominant part was not the first cell of anything found an empty slot and
    // took an empty name and an empty material out of it: the room filled with
    // things called " piece 1 piece 1" made of nothing, and sweeping the floor
    // up reported "2,833 g of ".
    // And which way each of them faced as its cells went into the island: the
    // pose that placed them, with the turn its shape carried on top. A body
    // that comes through whole is rebuilt facing the world's own way, its cells
    // where the run left them, so its box has to be turned by this -- or it
    // collides, and is drawn, square. Measured: an iron bar built 30 degrees
    // round, and one turned 30 degrees by the wrist, each struck a pane that
    // held and came back at -0.8 degrees while their cells lay at 30.
    std::vector<RigidSnapshot> before_of_part(setup.part_bodies.size());
    std::vector<Quat> facing_of_part(setup.part_bodies.size());
    const auto beforeOf = [&](std::size_t body) {
        const auto found = poses_before.find(body);
        return found != poses_before.end() ? found->second
                                           : impl_->world->snapshot(impl_->body_of[body]);
    };
    for (const std::size_t body : island_bodies)
        for (const std::uint32_t node : impl_->nodes_of[body]) {
            const std::uint32_t part = setup.part_of_node[node];
            if (part < parent_of_part.size() && parent_of_part[part].name.empty()) {
                parent_of_part[part] = impl_->described[body];
                before_of_part[part] = beforeOf(body);
                facing_of_part[part] = compose(before_of_part[part].orientation_world,
                                               impl_->shapeTurn(body));
            }
        }
    // And if a part still has nobody -- it was not in the island at all -- the
    // thing that was struck is the honest answer for whose piece this is.
    const LiveBodyPose fell_from = impl_->described[which];
    const RigidSnapshot fell_before = beforeOf(which);
    const Quat fell_facing = compose(fell_before.orientation_world, impl_->shapeTurn(which));
    // Read now, while the struck body is still in nodes_of. The drop loop below
    // erases it, and reading afterwards indexed off the end of the shortened
    // vector: the answer matched no piece, so a plate that had just come apart
    // into eight was reported as having held.
    const std::uint32_t asked_part =
        impl_->nodes_of[which].empty() ? 0 : setup.part_of_node[impl_->nodes_of[which].front()];
    // Which body each cell came from, so that what a body HELD is shared out
    // among its pieces by the cells each one took: a burning log that breaks
    // gives every piece its share of the fuel, the moisture and the heat, and
    // no piece gets any that was not there.
    const bool thermal = impl_->thermo && impl_->thermo->active();
    std::unordered_map<std::uint32_t, std::string> source_of_cell;
    std::unordered_map<std::string, std::size_t> source_cells;
    std::map<std::string, std::vector<std::pair<std::string, double>>> shares;
    if (thermal)
        for (const std::size_t body : island_bodies) {
            const std::string &source = impl_->described[body].name;
            if (!impl_->thermo->holds(source)) continue;
            source_cells[source] = impl_->nodes_of[body].size();
            for (const std::uint32_t node : impl_->nodes_of[body]) source_of_cell[node] = source;
        }

    // What each body's matter was measured against (docs/thermal-mechanics.md).
    // One that comes through whole in its authored shape keeps its record;
    // anything rebuilt from cells starts a new one from the cells it has.
    std::vector<std::string> island_names;
    for (const std::size_t body : island_bodies) island_names.push_back(impl_->described[body].name);

    // Drop every body in the island and append what they became. A piece is a
    // hull: its cells ARE its surface now, so no authored primitive fits.
    std::vector<std::size_t> going = island_bodies;
    std::sort(going.begin(), going.end(), std::greater<std::size_t>());
    for (const std::size_t body : going) {
        const auto drop = [&](auto &vector) {
            vector.erase(vector.begin() + static_cast<std::ptrdiff_t>(body));
        };
        drop(impl_->described); drop(impl_->body_of); drop(impl_->nodes_of);
        drop(impl_->limits_of); drop(impl_->impedance_of); drop(impl_->density_of);
        drop(impl_->tensile_of); drop(impl_->compressive_of);
        if (impl_->holding != static_cast<std::size_t>(-1) && impl_->holding > body) --impl_->holding;
    }

    // What was asked about is `asked_part`, taken above. The island may hold the
    // thing that struck it, and that thing may have come apart too, so counting
    // every component would answer a question nobody asked.
    std::size_t made = 0, of_asked = 0, fragment_index = 0;
    for (const auto &component : island_components) {
        if (fragment_index >= rebuilt.rigid_fragments.size()) break;
        // Not const: a piece that came through whole has its authored collision
        // shape put back below, and the fragments are handed to the world after
        // this loop rather than during it.
        RigidFragmentDescription &fragment = rebuilt.rigid_fragments[fragment_index];
        if (fragment.source_node_count != component.node_indices.size()) continue;
        ++fragment_index;
        std::vector<std::uint32_t> parent_nodes;
        parent_nodes.reserve(component.node_indices.size());
        std::fill(counted.begin(), counted.end(), 0);
        for (const std::uint32_t local : component.node_indices) {
            const std::uint32_t node = island.parent_node[local];
            parent_nodes.push_back(node);
            const std::uint32_t part = setup.part_of_node[node];
            if (part < counted.size()) ++counted[part];
            impl_->cell_offset_m[node] = island.matter.nodes[local].position_world_m -
                                         fragment.mass_properties.center_of_mass_world_m;
        }
        const std::size_t dominant = static_cast<std::size_t>(
            std::max_element(counted.begin(), counted.end()) - counted.begin());
        // A body that was only there to deliver the blow, all of it, is still
        // itself: its own pose stands in as its parent, and it keeps its name.
        const LiveBodyPose *held = nullptr;
        if (!held_pose.empty()) {
            const auto owner = body_of_node.find(island.parent_node[component.node_indices.front()]);
            if (owner != body_of_node.end())
                if (const auto found = held_pose.find(owner->second);
                    found != held_pose.end() && found->second.second == component.node_indices.size())
                    held = &found->second.first;
        }
        const LiveBodyPose &parent = held ? *held
                                     : parent_of_part[dominant].name.empty() ? fell_from
                                                                             : parent_of_part[dominant];
        const bool own = !parent_of_part[dominant].name.empty();
        const RigidSnapshot &was = own ? before_of_part[dominant] : fell_before;
        const Quat &faced = own ? facing_of_part[dominant] : fell_facing;
        const MaterialDefinition &material = dominant < setup.part_definitions.size()
                                                 ? setup.part_definitions[dominant]
                                                 : setup.tile_material;
        // What it slides and bounces on, as every other way of making a body
        // works it out: the piece's material against the ground's. Only the
        // rolling share was set here, so every piece of every break in the
        // world went into Jolt with friction 0 and no bounce at all -- and
        // Jolt takes the pair's friction as the root of the two, so nothing a
        // piece touched had any either. Measured in tests-break before this:
        // thirteen of twenty-five pieces were still going 30 s after the break,
        // sliding flat at 46 cm/s and losing nothing but the 0.02/s damping.
        //
        // This is not the whole of "little pieces roll forever" (the owner,
        // 2026-09-22). What is left after it rolls rather than slides: a 20 mm
        // chip measured at 42 rad/s of spin while travelling 0.49 m/s, where
        // rolling without slipping would be 49 -- and friction does no work on
        // a rolling contact. Only rolling resistance can stop that, and the
        // engine gives it to round bodies alone (docs/rolling-resistance.md).
        const CombinedContactMaterial against_ground = combineContactMaterials(
            compileContactMaterial(material), compileContactMaterial(setup.ground_material));
        fragment.friction = against_ground.dynamic_friction;
        fragment.restitution = against_ground.restitution;
        fragment.rolling_resistance = compileContactMaterial(material).rolling_resistance;
        LiveBodyPose piece{};
        // A piece that is still all of its parent kept its parent; only a piece
        // that is part of one is numbered.
        const bool whole_parent = counted[dominant] == component.node_indices.size() &&
                                  !parent_of_part[dominant].name.empty() &&
                                  component.node_indices.size() ==
                                      impl_->cellsOfPart(dominant);
        piece.name = held || whole_parent ? parent.name
                                          : parent.name + " piece " + std::to_string(++made);
        if (!source_of_cell.empty()) {
            std::unordered_map<std::string, std::size_t> from;
            for (const std::uint32_t node : parent_nodes) {
                const auto found = source_of_cell.find(node);
                if (found != source_of_cell.end()) ++from[found->second];
            }
            for (const auto &[source, cells] : from)
                shares[source].emplace_back(piece.name, static_cast<double>(cells));
        }
        // A piece that is still all of its parent is that parent, bent. Only
        // something that actually came off is debris.
        piece.fragment = !whole_parent || parent.fragment;
        // The deepest set it carries, and where. A piece keeps what its parent
        // had unless this run went deeper.
        piece.dent_m = parent.dent_m;
        // Kept in the rigid frame, and the piece is made facing the world's own
        // way: what the parent faced comes into it, or the mark would move.
        piece.dent_at_m = was.orientation_world.rotate(parent.dent_at_m);
        if (whole_parent && dent_m > piece.dent_m) {
            piece.dent_m = dent_m;
            piece.dent_at_m = dent_at - fragment.mass_properties.center_of_mass_world_m;
        }
        // What it is made of is a property of the PART, not of whichever body
        // happened to be standing in as its parent. Asked of the scene, which
        // has known the answer since it opened. (The material definition has a
        // name too -- "soda_lime_glass" -- but the bodies say "glass", and an
        // inventory holding both has two entries for one substance.)
        piece.material = dominant < impl_->material_of_part.size() &&
                                 !impl_->material_of_part[dominant].empty()
                             ? impl_->material_of_part[dominant]
                             : parent.material;
        if (dominant == asked_part) ++of_asked;

        // Something that came through whole is still the shape it was.
        //
        // Every piece used to be made a hull, including the ones nothing had
        // happened to. An island is the struck body AND the thing that struck
        // it, so a ball that cracked a pane was rebuilt too -- and came out of
        // the collision as a lump of cubes, having not been damaged at all.
        // From the outside that reads as the whole scene turning to voxels the
        // moment anything breaks, which is what it looked like because it is
        // what it was.
        //
        // A hull is the honest surface of a piece that BROKE: its boundary is
        // where the material failed and there is no smooth original to keep.
        // For a body still in one piece there is, and it is the shape it was
        // authored as. The collision primitive goes back with it, or a ball
        // with a flat-bottomed hull slides where it should roll.
        // "Whole" is not the same as "unchanged". A body that yielded still has
        // all of its cells and is still one piece -- that is what a dent IS --
        // and giving it back its authored sphere would hide the very thing that
        // just happened to it. So the permanent set decides too.
        // Whether the SHAPE changed enough to be worth drawing differently,
        // which is a different question from whether the body was dented.
        //
        // Everything that yielded used to be rebuilt out of its cells. That is
        // right when something has really been squashed and wrong when it has
        // not: measured on an iron ball dropped twelve metres onto an anvil, the
        // permanent set is a tenth of a millimetre, the cells end up within
        // ninety micrometres of where they started, and a 120 mm sphere was
        // redrawn as a 136-cube staircase showing no dent whatever -- strictly
        // worse than the sphere it replaced, and it cost the rolling too,
        // because a hull of cells has a flat bottom.
        //
        // The deepest single bond does not answer this: many bonds each giving
        // a little adds up along a chain, and the same ball driven at 16 m/s
        // loses more than a centimetre off its width with no single bond
        // anywhere near that.
        //
        // Nor does the outline against the size it was AUTHORED at, which was
        // the first answer here and was wrong for a reason worth writing down:
        // a sphere's cells never fill its sphere. A 140 mm ball voxelised at
        // 20 mm has its outermost cell centres at 52 mm, so its cell extent is
        // 124 mm before anything happens to it -- a 16 mm "change" that is
        // nothing but the grid. Every ball that so much as entered an island
        // was therefore redrawn as a blob: measured on an aluminium ball that
        // struck an ice plate at 8.75 m/s against a bending threshold of 58.2,
        // took a permanent set of exactly zero, and came out a 168-cell hull.
        //
        // What answers it is the cells against THEMSELVES: how far the furthest
        // one reaches from the middle of them, now, against how far it reached
        // when the body was made. Same measure, same cells, so the grid cancels
        // -- and it does not care how the body is turned, which an axis-aligned
        // box would.
        const auto reachOf = [&](auto &&placeOf) {
            Vec3 middle{};
            for (const std::uint32_t node : parent_nodes) middle = middle + placeOf(node);
            const double count = static_cast<double>(parent_nodes.size());
            if (count > 0.0) middle = (1.0 / count) * middle;
            double far = 0.0;
            for (const std::uint32_t node : parent_nodes)
                far = std::max(far, length(placeOf(node) - middle));
            return far;
        };
        const double reaches_now =
            reachOf([&](std::uint32_t node) { return impl_->cell_offset_m[node]; });
        const double reached_when_made =
            reachOf([&](std::uint32_t node) { return setup.matter.nodes[node].position_world_m; });
        const double moved = std::abs(reaches_now - reached_when_made);
        // A quarter of a cell. Measured, an undeformed body comes out at a few
        // micrometres and a genuinely squashed one at about half a cell, so the
        // two are nowhere near each other and the bar only has to sit between.
        const bool reshaped = moved > 0.25 * impl_->request.cell_size_m;
        const bool untouched = whole_parent && !reshaped && parent.shape != "hull";
        if (untouched) {
            piece.shape = parent.shape;
            piece.dimensions_m = parent.dimensions_m;
            fragment.primitive = parent.shape == "sphere" ? FragmentPrimitive::Sphere
                                                          : FragmentPrimitive::Box;
            fragment.primitive_dimensions_m = parent.dimensions_m;
        } else {
            piece.shape = "hull";
        }
        // A box comes back turned the way it faced going in: the new body starts
        // facing the world's own way, so the turn goes inside its shape -- where
        // rotation_deg goes when a box is built turned -- and poses() puts it on
        // top of the pose, as it does for that. A ball collides the same however
        // it is turned, so its shape is left as it was; a hull's cells are its
        // shape. For those nothing is carried under the name any more.
        if (untouched && piece.shape == "box" &&
            (faced.x != 0.0 || faced.y != 0.0 || faced.z != 0.0)) {
            fragment.primitive_rotation_wxyz[0] = faced.w;
            fragment.primitive_rotation_wxyz[1] = faced.x;
            fragment.primitive_rotation_wxyz[2] = faced.y;
            fragment.primitive_rotation_wxyz[3] = faced.z;
            impl_->tilt_of[piece.name] = faced;
        } else {
            impl_->tilt_of.erase(piece.name);
        }
        piece.color_rgba = parent.color_rgba;
        impl_->limits_of.push_back(fragmentFractureLimits(
            setup.matter, parent_nodes, material.density_kg_m3, material.young_modulus_pa,
            material.yield_strength_pa, material.fracture_energy_j_m2,
            impl_->request.cell_size_m));
        impl_->impedance_of.push_back(
            acousticImpedance(material.density_kg_m3, material.young_modulus_pa));
        impl_->density_of.push_back(material.density_kg_m3);
        impl_->tensile_of.push_back(material.tensile_strength_pa);
        impl_->compressive_of.push_back(material.compressive_strength_pa);
        impl_->nodes_of.push_back(std::move(parent_nodes));
        if (piece.shape == "hull")
            piece.dimensions_m = cellBounds(impl_->nodes_of.back(), impl_->cell_offset_m,
                                            impl_->request.cell_size_m);
        impl_->described.push_back(std::move(piece));
        impl_->body_of.push_back(fragment.body_id);
        impl_->next_body_id = std::max(impl_->next_body_id, fragment.body_id + 1);
    }
    for (const std::string &was : island_names) {
        const auto record = impl_->matter_of.find(was);
        if (record == impl_->matter_of.end()) continue;
        bool kept = false;
        for (LiveBodyPose &pose : impl_->described) {
            if (pose.name != was || pose.shape == "hull") continue;
            pose.revision = record->second.revision;
            // Its new body is unturned, and how it is turned is its shape's now.
            if (const auto tilt = impl_->tilt_of.find(was); tilt != impl_->tilt_of.end())
                record->second.turn = tilt->second;
            kept = true;
            break;
        }
        if (!kept) impl_->matter_of.erase(record);
    }
    impl_->world->addFragments(rebuilt.rigid_fragments);
    impl_->index_of.clear();
    for (std::size_t i = 0; i < impl_->described.size(); ++i)
        impl_->index_of.emplace(impl_->described[i].name, i);
    // And what stood on what came apart finds out whether it still stands.
    // Jolt wakes nothing when a body is taken out from under a sleeping one,
    // and the pieces put in its place did not wake it either. Measured on the
    // heated beam: the 258 kg block had slept on it through the re-cuts,
    // statics broke the beam into 56 pieces under it, the pieces fell to the
    // floor, and the block hung where it was, 0.43 m up with nothing under
    // it, for the four and a half minutes the check went on watching.
    for (const auto &[at, reach] : gone_from)
        for (std::size_t j = 0; j < impl_->described.size(); ++j) {
            if (impl_->described[j].anchored || !impl_->world->contains(impl_->body_of[j])) continue;
            const Vec3 there = impl_->world->snapshot(impl_->body_of[j]).center_of_mass_world_m;
            if (length(there - at) <= reach + 0.5 * length(impl_->described[j].dimensions_m))
                impl_->world->wake(impl_->body_of[j]);
        }
    if (thermal) {
        for (auto &[source, pieces] : shares) {
            const double cells = static_cast<double>(source_cells[source]);
            for (auto &piece : pieces) piece.second /= cells;
            impl_->thermo->split(source, pieces);
        }
        impl_->thermo->refresh(thermoShapes(), setup.ground_y);
    }
    // Every body in the island was destroyed and rebuilt above, so every pin
    // touching any of them is holding nothing. This is where they find their
    // wood again -- or find there is none left, and let go.
    rehangJoints();
    // What happened to the body that was ASKED about, which is not the same as
    // what happened to the island. An island can come apart while the thing in
    // question survives whole -- a ball that cracked the pane it hit is one
    // piece still -- and reporting the island's fate as the body's says a thing
    // broke when it did not.
    impl_->last_outcome = of_asked > 1 ? LiveOutcome::Broke
                        : dented       ? LiveOutcome::Dented
                                       : LiveOutcome::Held;
    // And what it cost: the bonds the lattice removed, the crack area they
    // stand for (h^2 / N_100 each) and the elastic energy that went with them.
    // The charge and the declaration were set when the run began (crackCost).
    {
        const LatticeHorizonGeometry g = latticeHorizonGeometry(impl_->request.neighbor_horizon_cells);
        LiveBreakCost &cost = impl_->last_break;
        if (job.struck_material != nullptr && cost.material.empty()) {
            cost.material = job.struck_material->name;
            cost.declared_energy_j_m2 = job.struck_material->fracture_energy_j_m2;
        }
        cost.broken_bonds = status.broken_bonds;
        const BondFailureModeCounts modes = countBondFailureModes(island.matter);
        cost.tensile_bonds = modes.tensile;
        cost.compressive_bonds = modes.compressive;
        cost.shear_bonds = modes.shear;
        cost.removed_energy_j = status.removed_energy_j;
        cost.available_energy_j = job.control.removable_energy_j;
        cost.available_kinetic_j = job.entry_kinetic_j;
        cost.available_elastic_j = job.entry_elastic_j;
        // Exit reason 6: the run stopped because what the island brought in was
        // spent. Whatever was still damaged stays damaged and can go in a later
        // blow that pays for it.
        cost.spent_it_all = status.exit_reason == 6U;
        cost.crack_area_m2 = g.crossings_100 > 0.0
            ? static_cast<double>(status.broken_bonds) * impl_->request.cell_size_m *
                  impl_->request.cell_size_m / g.crossings_100
            : 0.0;
        cost.crack_energy_j_m2 = cost.crack_area_m2 > 0.0 ? cost.removed_energy_j / cost.crack_area_m2 : 0.0;
    }
    // It broke, so the name it held under is gone and its pieces are new ones
    // that have never been tried. A body that only BENT keeps its name, and
    // must keep its place in the already-answered set with it -- otherwise the
    // same contact is offered again on the next step, dents it again, and the
    // world spends itself deforming one object for ever.
    if (impl_->index_of.find(name) == impl_->index_of.end()) impl_->held_through.erase(name);
    if (job.sustained) impl_->sustained_answers[name].pieces = of_asked;
    return of_asked;
}


bool LiveWorld::beginFracture(const std::string &name, double window_s) {
    {
        const auto found = impl_->index_of.find(name);
        if (found != impl_->index_of.end() && impl_->isPrecise(found->second))
            throw std::invalid_argument("fracture: a precise-rigid body has no internal failure to run");
    }
    // One at a time, and a second one waits for the first.
    //
    // Dropping it instead is not an option: the step that turned it up was
    // taken back, and it stays taken back until somebody answers, so ignoring
    // it stops the clock -- the very thing this is here to prevent. So the
    // first is collected, waiting for it if it is not ready yet, and that wait
    // is written down as a block because that is what it is.
    //
    // Two that share no matter could run side by side; that is a real
    // improvement and not this one. Until then a queue is correct, and honest
    // about what it costs.
    // If the run for exactly this impact was started on the way down, it is
    // finished or nearly so, and there is nothing left to wait for. This is the
    // whole point of looking ahead: the pieces appear when the thing lands
    // rather than most of a second later.
    if (!impl_->pending && adoptGuess(name)) {
        impl_->delays.push_back({impl_->time_s, name, "foreseen",
                                 impl_->guess_error_pct, impl_->pending->cost_ms,
                                 impl_->pending->dt_s, impl_->pending->status.total_steps});
        repin();
        return true;
    }
    if (impl_->pending) {
        const bool ready = fractureReady();
        const auto waited_from = std::chrono::steady_clock::now();
        const std::string first = impl_->pending->name;
        finishFracture();
        if (!ready)
            impl_->delays.push_back({impl_->time_s, first, "blocked", 0.0,
                1000.0 * std::chrono::duration<double>(
                    std::chrono::steady_clock::now() - waited_from).count()});
    }
    prepare(name, window_s);
    if (impl_->pending->settled) {
        // Nothing to run. Apply it here and now -- there is no cost to hide.
        applyPending();
        impl_->pending.reset();
        return false;
    }
    // Pin what is about to happen to something. Letting it carry on means it
    // bounces off a thing that is in fact breaking, and has to be put back when
    // the answer lands: measured, an iron ball arcs half a metre into the air
    // and comes back down in the time the run takes.
    repin();
    impl_->delays.push_back({impl_->time_s, name, "held", 0.0, 0.0});
    Pending *job = impl_->pending.get();
    job->started = std::chrono::steady_clock::now();
    impl_->worker = std::async(std::launch::async, [job] { work(*job); });
    return true;
}

bool LiveWorld::fracturePending() const { return impl_->pending != nullptr; }

bool LiveWorld::fractureReady() const {
    if (!impl_->pending) return false;
    if (!impl_->worker.valid()) return true;
    return impl_->worker.wait_for(std::chrono::seconds(0)) == std::future_status::ready;
}

std::string LiveWorld::fractureSubject() const {
    return impl_->pending ? impl_->pending->name : std::string{};
}

std::size_t LiveWorld::finishFracture() {
    if (!impl_->pending) return 0;
    if (impl_->worker.valid()) impl_->worker.get();   // waits only if it has to
    // `lead_ms` here is how long it sat in the queue before a worker took it;
    // `cost_ms` is what the run itself cost. Neither was paid by the caller.
    impl_->delays.push_back({impl_->time_s, impl_->pending->name, "precomputed",
                             impl_->pending->waited_ms, impl_->pending->cost_ms,
                             impl_->pending->dt_s, impl_->pending->status.total_steps});
    // Which slots the apply is about to empty, read by name rather than by
    // trusting what the island said it would drop: a body that held drops
    // nothing, and a body that came apart drops its whole island. Names are
    // unique and survive the apply, indices do not.
    std::vector<std::string> before;
    before.reserve(impl_->described.size());
    for (const LiveBodyPose &pose : impl_->described) before.push_back(pose.name);

    const std::size_t pieces = applyPending();
    impl_->pending.reset();

    // A guess holds indices into the table that has just changed shape, and
    // unlike a queued job it is speculative, so it is thrown away rather than
    // carefully followed.
    dropGuess("guess-wasted");
    restackQueue(before);

    // Whatever was waiting behind it starts now, on the same worker.
    startNextQueued();
    return pieces;
}

// The whole thing at once, which is what a caller that does not mind waiting
// wants. Identical to what this always did.
std::size_t LiveWorld::fracture(const std::string &name, double window_s) {
    {
        const auto found = impl_->index_of.find(name);
        if (found != impl_->index_of.end() && impl_->isPrecise(found->second))
            throw std::invalid_argument("fracture: a precise-rigid body has no internal failure to run");
    }
    // A run may already be going for this very impact, started on the way down.
    // Take it if it fits, and if it does not, wait for it and bin it -- because
    // starting a second lattice run beside it is two at once, which nothing
    // here was built for. That was a real deadlock: the guess and the real run
    // went side by side, the answer came back wrong, and the world sat refusing
    // the same step for ever.
    if (adoptGuess(name)) {
        impl_->delays.push_back({impl_->time_s, name, "foreseen",
                                 impl_->guess_error_pct, impl_->pending->cost_ms,
                                 impl_->pending->dt_s, impl_->pending->status.total_steps});
        impl_->held_through.insert(name);
        const std::size_t early = applyPending();
        impl_->pending.reset();
        return early;
    }
    dropGuess("guess-wasted");
    prepare(name, window_s);
    if (!impl_->pending->settled) {
        work(*impl_->pending);
        impl_->delays.push_back({impl_->time_s, name, "blocked", 0.0,
                                 impl_->pending->cost_ms, impl_->pending->dt_s,
                                 impl_->pending->status.total_steps});
    }
    const std::size_t pieces = applyPending();
    impl_->pending.reset();
    return pieces;
}

LivePick LiveWorld::pick(const Vec3 &from_world_m, const Vec3 &direction,
                         double max_distance_m) const {
    LivePick out{};
    const RayHit hit = impl_->world->castRay(from_world_m, direction, max_distance_m);
    if (!hit.hit) return out;
    out.hit = true;
    out.distance_m = hit.distance_m;
    out.point_world_m = hit.point_world_m;
    if (!hit.named) return out;   // the ground: hit, but not one of the scene's
    for (std::size_t i = 0; i < impl_->body_of.size(); ++i)
        if (impl_->body_of[i] == hit.body_id) { out.name = impl_->described[i].name; break; }
    return out;
}

namespace {

// The ground under a thing's footprint, a point of it: x and z in the thing's
// own axes from its centre of mass, y the ground's height in the world.
struct GroundSample {
    double x, y, z;
};

// The plane a flat underside comes to rest on over its middle: of the planes
// through three samples with no sample above them, the one lowest over (0, 0)
// -- the facet of the ground's upper hull there, which the three it passes
// through hold up. y = a x + b z + c, as {a, b, c}; none from fewer than three
// samples, or none that has its middle between them.
std::optional<std::array<double, 3>> restingPlane(const std::vector<GroundSample> &ground) {
    const std::size_t n = ground.size();
    if (n < 3) return std::nullopt;
    // Every triple: at most 81 samples, and a triple is dropped at once unless
    // it is around the middle and lower there than the best so far. Measured on
    // the valley, place_check's whole round trip: 0.2 ms for the shelf unit's
    // 36 samples, 0.5 ms for the table's 81. (Searching only the samples
    // highest above the plane that fits them best misses this plane on flat
    // ground, where which is highest is rounding.)
    std::optional<std::array<double, 3>> best;
    const auto side = [](const GroundSample &u, const GroundSample &v) {
        return (v.x - u.x) * (0.0 - u.z) - (v.z - u.z) * (0.0 - u.x);
    };
    for (std::size_t i = 0; i < n; ++i)
        for (std::size_t j = i + 1; j < n; ++j)
            for (std::size_t k = j + 1; k < n; ++k) {
                const GroundSample &p = ground[i], &q = ground[j], &r = ground[k];
                const double s1 = side(p, q), s2 = side(q, r), s3 = side(r, p);
                const bool around = (s1 >= -1e-12 && s2 >= -1e-12 && s3 >= -1e-12) ||
                                    (s1 <= 1e-12 && s2 <= 1e-12 && s3 <= 1e-12);
                if (!around) continue;
                const double det = (q.x - p.x) * (r.z - p.z) - (r.x - p.x) * (q.z - p.z);
                if (std::abs(det) < 1e-9) continue;
                const double a = ((q.y - p.y) * (r.z - p.z) - (r.y - p.y) * (q.z - p.z)) / det;
                const double b = ((q.x - p.x) * (r.y - p.y) - (r.x - p.x) * (q.y - p.y)) / det;
                const double c = p.y - a * p.x - b * p.z;
                if (best && c >= (*best)[2]) continue;
                bool over = true;
                for (const GroundSample &g : ground)
                    if (a * g.x + b * g.z + c < g.y - 1e-6) { over = false; break; }
                if (over) best = std::array<double, 3>{a, b, c};
            }
    return best;
}

// The outline of points in (x, z), anticlockwise (Andrew's monotone chain).
std::vector<std::array<double, 2>> outlineOf(std::vector<std::array<double, 2>> points) {
    std::sort(points.begin(), points.end());
    points.erase(std::unique(points.begin(), points.end()), points.end());
    if (points.size() < 3) return points;
    const auto turn = [](const std::array<double, 2> &o, const std::array<double, 2> &a,
                         const std::array<double, 2> &b) {
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    };
    std::vector<std::array<double, 2>> hull(2 * points.size());
    std::size_t k = 0;
    for (std::size_t i = 0; i < points.size(); ++i) {
        while (k >= 2 && turn(hull[k - 2], hull[k - 1], points[i]) <= 0.0) --k;
        hull[k++] = points[i];
    }
    for (std::size_t i = points.size() - 1, lower = k + 1; i-- > 0;) {
        while (k >= lower && turn(hull[k - 2], hull[k - 1], points[i]) <= 0.0) --k;
        hull[k++] = points[i];
    }
    hull.resize(k - 1);
    return hull;
}

// How far a lean takes a thing towards the edge of what it rests on: the lean
// is where its middle's plumb line meets its underside, from the middle, and 1
// is that point on the outline's edge -- where it goes over. 1000 for a thing
// standing on an edge already and leaning across it.
double tippingUsed(const std::vector<std::array<double, 2>> &outline, double px, double pz) {
    if (outline.size() < 3) return 1000.0;
    double worst = 0.0;
    for (std::size_t k = 0; k < outline.size(); ++k) {
        const auto &p = outline[k], &q = outline[(k + 1) % outline.size()];
        const double ex = q[0] - p[0], ez = q[1] - p[1], length = std::hypot(ex, ez);
        if (!(length > 0.0)) continue;
        const double nx = ez / length, nz = -ex / length;  // outwards, anticlockwise
        const double inside = p[0] * nx + p[1] * nz;       // the middle's distance in from the edge
        const double towards = px * nx + pz * nz;
        if (inside <= 1e-9) {
            if (towards > 1e-12) return 1000.0;
            continue;
        }
        worst = std::max(worst, towards / inside);
    }
    return std::min(worst, 1000.0);
}

}  // namespace

LivePlacement LiveWorld::placement(const std::string &name, const Vec3 &on_world_m, double yaw_rad,
                                   const std::string &onto, bool square) const {
    LivePlacement out{};
    const auto found = impl_->index_of.find(name);
    if (found == impl_->index_of.end()) { out.why = "there is nothing called that here"; return out; }
    const std::size_t i = found->second;
    if (impl_->described[i].anchored) { out.why = "it is fixed in place"; return out; }
    if (!impl_->inWorld(i)) { out.why = "it is not in the room: take it out of the bag first"; return out; }
    const MatterBodyId id = impl_->body_of[i];
    // Upright as it was made, turned about the vertical: a body's rigid frame is
    // the one it was built in, and a thing is built standing the way it stands
    // -- a stool on its feet, a plank flat, a cup on its base. Then, below,
    // square to the ground under it.
    const Quat turn{std::cos(0.5 * yaw_rad), 0.0, std::sin(0.5 * yaw_rad), 0.0};
    const auto [low, high] = impl_->world->shapeBoundsTurned(id, turn);
    // Its own box, in its own axes: its footprint whichever way it is turned.
    const auto [own_low, own_high] = impl_->world->shapeBoundsTurned(id, Quat{});
    // Its underside on the surface, 2 mm clear of it, its middle over the point.
    constexpr double kClearM = 0.002;
    out.at_m = Vec3{on_world_m.x, on_world_m.y - low.y + kClearM, on_world_m.z};
    const Vec3 down{0.0, -1.0, 0.0};
    // What it is being set down on: the thing the point is on, as the host
    // found it, or the ground. Not guessed from under the point: a ball lying
    // on the spot is under it too, and a crate lifted off that ball would be
    // put on top of it rather than said to be in its way.
    MatterBodyId onto_id{};
    bool onto_body = false;
    if (const auto on = impl_->index_of.find(onto);
        !onto.empty() && on != impl_->index_of.end() && on->second != i && impl_->inWorld(on->second)) {
        onto_id = impl_->body_of[on->second];
        onto_body = true;
    }
    // Raised off what it is set down on until it clears it -- on flat ground
    // not at all, on a slope or a rounded top by however much its shape would
    // go in (measured on the valley's hillside, a ball set 2 mm over the spot
    // went into the slope above it everywhere steeper than about 15 degrees).
    // Only off that, and the ground: anything else it would go into is a thing
    // in the way, and is said.
    // Clear of it, not merely within the 3 mm said of other things below: a
    // 50 mm ball on a 20 degree slope goes 1 mm in, and let go there it would
    // be pushed out with a jump.
    const auto clear_of_it = [&](const Quat &stand) {
        for (int k = 0; k < 8; ++k) {
            double deepest = 0.0;
            for (const PlacementOverlap &met : impl_->world->overlapsAt(id, out.at_m, stand, 0.0005))
                if (!met.named || (onto_body && met.body_id == onto_id)) deepest = std::max(deepest, met.depth_m);
            if (!(deepest > 0.0)) return true;
            out.at_m.y += deepest + 0.001;
        }
        return false;
    };
    double start_y = out.at_m.y;
    bool clear = clear_of_it(turn);
    // The ground under it: a grid over its whole footprint, in its own axes
    // turned the way it would stand, out to its edges -- a twisted or folded
    // ground holds a thing up there, and four samples in from its corners missed
    // a 15 mm rise at one end of the valley's shelf unit, which then stood on
    // that and fell -- read from just over its underside, clear upright, and as
    // far down as the ground goes; only where the ray meets the thing the point
    // is on (a corner out over a crate's edge that finds the floor is a drop,
    // not a slope).
    const double xs[2] = {0.8 * own_low.x, 0.8 * own_high.x};
    const double zs[2] = {0.8 * own_low.z, 0.8 * own_high.z};
    std::vector<GroundSample> under_it;
    if (clear) {
        const double wide = own_high.x - own_low.x, deep = own_high.z - own_low.z;
        const double span = std::max(wide, deep);
        const double reach = 0.045 + span;
        // About every 10 cm, 3 to 9 a side: finer than the valley's 25 cm ground.
        const int nx = std::clamp(static_cast<int>(std::ceil(wide / 0.1)) + 1, 3, 9);
        const int nz = std::clamp(static_cast<int>(std::ceil(deep / 0.1)) + 1, 3, 9);
        for (int a = 0; a < nx; ++a)
            for (int c = 0; c < nz; ++c) {
                const double lx = own_low.x + wide * a / (nx - 1);
                const double lz = own_low.z + deep * c / (nz - 1);
                const Vec3 corner = turn.rotate(Vec3{lx, 0.0, lz});
                const Vec3 from{out.at_m.x + corner.x, out.at_m.y + low.y + 0.005, out.at_m.z + corner.z};
                RayHit met = impl_->world->castRay(from, down, reach, id);
                // A round or tapered underside clears a slope only where it is
                // lowest, and under its uphill corners the ground is higher than
                // that: a ray started there is inside the ramp (which answers
                // at once, where the ray began) or under the ground (which it
                // passes). Asked again from over ground rising 45 degrees
                // across it; the lower start stays first, so that nothing over
                // a thing's footprint -- a shelf above, a container's rim --
                // is taken for the ground under it.
                if (!met.hit || !(met.distance_m > 0.0))
                    met = impl_->world->castRay(from + Vec3{0.0, 1.2 * span, 0.0}, down, reach + 1.2 * span, id);
                if (met.hit && (onto_body ? met.named && met.body_id == onto_id : !met.named))
                    under_it.push_back({lx, met.point_world_m.y, lz});
            }
    }
    // What its flat underside would come to rest on there: the plane through
    // the three highest points around its middle (restingPlane). Not the plane
    // that fits the ground best -- on ground twisted across its footprint that
    // is a plane it touches at one point and rocks off.
    const std::optional<std::array<double, 3>> rests = restingPlane(under_it);
    const bool plane = rests.has_value();
    const double along_x = plane ? (*rests)[0] : 0.0, along_z = plane ? (*rests)[1] : 0.0;
    // Set down SQUARE to that ground, not upright over it. Let go upright over
    // a slope, a thing first pivots on its uphill edge down onto the slope, and
    // what that swing gains carries a tall one over its downhill edge long
    // before the slope itself would: the valley's 1.8 m shelf unit, let go at
    // rest and exactly upright on planar ramps across its 0.28 m side, stood on
    // 2.25 degrees and fell over every time from 2.5 -- where it statically
    // tips at 8.8. Square to the ground there is no swing, and what tips it is
    // the slope alone. Its middle stays over the point and its underside 2 mm
    // clear of the ground, measured square to it; a bump is still lifted off.
    // Past 45 degrees under it the ground is a wall, and it is upright as it
    // always was -- so the crosshair on a crate's side is too steep, as ever.
    // `square` false keeps it upright: the host putting a thing of several
    // parts down as one shape asks for each part as it stands in that shape.
    Quat stand = turn;
    const double steepest = std::hypot(along_x, along_z);
    if (square && plane && steepest > 1e-4 && steepest <= 1.0) {
        const Vec3 n = normalized(turn.rotate(Vec3{-along_x, 1.0, -along_z}));
        const double s = std::hypot(n.x, n.z);
        const double half = 0.5 * std::atan2(s, n.y);
        // About the level line of that slope, by its steepness: its own up to
        // the ground's.
        stand = compose(Quat{std::cos(half), std::sin(half) * n.z / s, 0.0, -std::sin(half) * n.x / s}, turn);
        // Its underside 2 mm clear of that plane, square to it; the plane is
        // where it stands over its middle, which the point may be a dip under.
        out.at_m = Vec3{on_world_m.x, (*rests)[2] + (kClearM - low.y) / n.y, on_world_m.z};
        start_y = out.at_m.y;
        clear = clear_of_it(stand);
    }
    out.turn_wxyz[0] = stand.w;
    out.turn_wxyz[1] = stand.x;
    out.turn_wxyz[2] = stand.y;
    out.turn_wxyz[3] = stand.z;
    // Which way it would face there, as poses() says of a body: the rigid turn
    // with the one a whole box or ball carries inside its shape on top.
    const Quat facing = compose(stand, impl_->shapeTurn(i));
    out.facing_wxyz[0] = facing.w;
    out.facing_wxyz[1] = facing.x;
    out.facing_wxyz[2] = facing.y;
    out.facing_wxyz[3] = facing.z;
    // Lifted more than half its own height, or still not clear: it is not being
    // set ON that -- the crosshair is on a wall, or on the side of a crate -- and
    // it is not put on top of it by being pushed up it. Measured on the page: a
    // ball aimed at a crate's side went up the side and came out "fits, but
    // little of it is on the oak crate".
    if (!clear || out.at_m.y - start_y > std::max(0.02, 0.5 * (high.y - low.y))) {
        out.at_m.y = start_y;
        out.why = "that is too steep to set it on";
        return out;
    }
    const std::string ground = impl_->environment ? "ground" : "floor";
    const auto called = [&](bool named, MatterBodyId body) {
        if (!named) return ground;
        for (std::size_t j = 0; j < impl_->body_of.size(); ++j)
            if (impl_->body_of[j] == body) return impl_->described[j].name;
        return std::string("something");
    };
    // What is under the middle of its underside, and under each corner of its
    // footprint -- a little in from the corners, so a rounded or tapered
    // underside counts -- straight down from its underside as it would stand.
    // Its own body is where the hand has it, not here, and is not an answer.
    // Its middle is looked under down to the same depth below the point
    // whatever lifted it or set it square. Lifted clear of a slope, it stands
    // that much further over the point and is on it all the same: a 0.9 m
    // bookcase turned 45 degrees on 8 is lifted 60 mm, past the 55 mm looked
    // under unlifted. And a point out in the air is still over nothing,
    // however far it was lifted.
    const Vec3 over{0.0, 0.005, 0.0};
    const Vec3 middle = out.at_m + stand.rotate(Vec3{0.0, own_low.y, 0.0}) + over;
    const RayHit under = impl_->world->castRay(middle, down, std::max(0.06, middle.y - (on_world_m.y - 0.053)), id);
    if (under.hit && !(under.named && under.body_id == id)) out.rests_on = called(under.named, under.body_id);
    // Each corner is looked under as far as it would reach not lifted: set
    // square it sits flush on even ground, and only a bump lifts it, which is
    // not the corners' lack of ground.
    double highest = -1e30, lowest = 1e30;
    for (const double cx : xs)
        for (const double cz : zs) {
            const RayHit corner = impl_->world->castRay(
                out.at_m + stand.rotate(Vec3{cx, own_low.y, cz}) + over, down, 0.04 + (out.at_m.y - start_y), id);
            if (!corner.hit || (corner.named && corner.body_id == id)) continue;
            ++out.supported_corners;
            highest = std::max(highest, corner.point_world_m.y);
            lowest = std::min(lowest, corner.point_world_m.y);
        }
    // How steep what it stands on is, across its footprint -- steeper than 15
    // degrees (tan = 0.268) is said: a ball on a slope fits, and then rolls,
    // which is the engine's to show, not the copy's to hide.
    const double across = 0.8 * std::max(own_high.x - own_low.x, own_high.z - own_low.z);
    const bool sloped = out.supported_corners >= 2 && across > 1e-6 && highest - lowest > 0.268 * across;
    // Whether a TALL thing would stay up on that slope. Stood on ground rising
    // s along one of its sides, its middle, h over its underside, leans out
    // over the downhill edge by h s; it goes over once that passes the edge,
    // b from its middle: at s = b / h. A 1.8 m shelf unit on a 0.28 m base goes
    // over at 8.8 degrees across its narrow side, and at 27 along its wide one.
    // Geometry only: its shape, where its centre of mass is, and the ground.
    //
    // Read in its own axes, from the plane it rests on, against the outline of
    // what it rests on: the ground within 2 mm of that plane under its
    // footprint, which on flat or evenly sloping ground is all of its footprint
    // and on twisted ground may be a small triangle of it -- the valley's shelf
    // unit, set square at rest on such ground, fell over on 3.5 to 5 degrees
    // with three points under it. Its lean is where its middle's plumb line
    // meets its underside, h along the plane's fall from its middle. Not the
    // box around it turned, which for that shelf unit at 45 degrees is three
    // times as deep as the shelf, and not the drop over its longer side, which
    // puts a slope across its narrow side at 0.28 / 0.92 of what it is. Set down
    // square, the slope is all that leans it out; half of what tips it is what
    // is said, the other half the margin a hand's let-go has.
    // Only a thing whose middle stands higher than its nearest edge is from it
    // -- taller than it is wide: a ball rolls and a cube slides long before
    // they tip, and saying so is the slope's rule above.
    const double rise = -low.y;
    const double nearest = std::min({-own_low.x, own_high.x, -own_low.z, own_high.z});
    if (plane && !out.rests_on.empty() && nearest > 0.0 && rise > nearest + 0.001) {
        std::vector<std::array<double, 2>> held_up_by;
        for (const GroundSample &g : under_it)
            if (along_x * g.x + along_z * g.z + (*rests)[2] - g.y <= 0.002) held_up_by.push_back({g.x, g.z});
        out.tipping_used = tippingUsed(outlineOf(std::move(held_up_by)), -rise * along_x, -rise * along_z);
        out.may_fall_over = out.tipping_used > 0.5;
    }
    // What it would go into, standing there: more than 3 mm, which a thing set
    // down 2 mm clear of what it rests on cannot be by resting on it.
    for (const PlacementOverlap &met : impl_->world->overlapsAt(id, out.at_m, stand, 0.003))
        out.touching.emplace_back(called(met.named, met.body_id), met.depth_m);
    if (!out.touching.empty()) {
        out.why = out.touching.front().first == ground ? "the " + ground + " is too uneven there"
                                                       : "it would go into the " + out.touching.front().first;
    } else if (out.rests_on.empty()) {
        out.why = "there is nothing under it to rest on";
    } else if (out.tipping_used > 1.0) {
        out.why = "it is too tall for that slope: it would fall over";
    } else if (out.may_fall_over) {
        // Said before its corners: stood upright on a slope that far over (not
        // set square: one of several parts), a tall thing's downhill corners are
        // what is out of reach, and why is the slope.
        out.fits = true;
        out.why = "it fits, but it is tall for that slope: it may fall over";
    } else if (out.supported_corners < 3) {
        out.fits = true;
        out.why = "it fits, but little of it is on the " + out.rests_on + ": it may tip off";
    } else if (sloped) {
        out.fits = true;
        out.why = "it fits, on the " + out.rests_on + ", but that slopes: it may slide or roll";
    } else {
        out.fits = true;
        out.why = "it fits here, on the " + out.rests_on;
    }
    return out;
}

std::string LiveWorld::held() const {
    return impl_->holding == static_cast<std::size_t>(-1)
               ? std::string{}
               : impl_->described[impl_->holding].name;
}

// ---- heat, chemistry and gas ------------------------------------------------

double LiveWorld::hullArea(std::size_t body) const {
    const double cell = impl_->request.cell_size_m;
    const std::vector<std::uint32_t> &nodes = impl_->nodes_of[body];
    if (nodes.empty()) return 6.0 * cell * cell;
    const std::string &name = impl_->described[body].name;
    const auto cached = impl_->hull_area_of.find(name);
    if (cached != impl_->hull_area_of.end() && cached->second.first == nodes.size())
        return cached->second.second;
    // A face is open when no cell of the same body sits against it. Cells lie
    // on one grid, so their offsets differ by whole cells; rounding from the
    // first one puts a bent body back on it too.
    std::set<std::tuple<long, long, long>> at;
    const Vec3 origin = impl_->cell_offset_m[nodes.front()];
    for (const std::uint32_t node : nodes) {
        const Vec3 o = (impl_->cell_offset_m[node] - origin) / cell;
        at.insert({std::lround(o.x), std::lround(o.y), std::lround(o.z)});
    }
    std::size_t faces = 0;
    for (const auto &[x, y, z] : at)
        for (const auto &[dx, dy, dz] : {std::tuple{1L, 0L, 0L}, std::tuple{-1L, 0L, 0L},
                                         std::tuple{0L, 1L, 0L}, std::tuple{0L, -1L, 0L},
                                         std::tuple{0L, 0L, 1L}, std::tuple{0L, 0L, -1L}})
            if (!at.count({x + dx, y + dy, z + dz})) ++faces;
    const double area = static_cast<double>(faces) * cell * cell;
    impl_->hull_area_of[name] = {nodes.size(), area};
    return area;
}

std::vector<thermo::BodyShape> LiveWorld::thermoShapes() const {
    constexpr double kPi = 3.14159265358979323846;
    const double cell = impl_->request.cell_size_m;
    std::vector<thermo::BodyShape> shapes;
    shapes.reserve(impl_->described.size());
    for (std::size_t i = 0; i < impl_->described.size(); ++i) {
        const LiveBodyPose &body = impl_->described[i];
        if (impl_->precise_bodies.count(body.name)) continue; // thermal model is not implemented
        const MatterBodyId id = impl_->body_of[i];
        if (!impl_->world->contains(id)) continue;
        const RigidMechanicalState state = impl_->world->mechanicalState(id);
        thermo::BodyShape shape;
        shape.name = body.name;
        shape.material = body.material;
        shape.anchored = body.anchored;
        shape.center_m = state.motion.center_of_mass_world_m;
        const Vec3 d = body.dimensions_m;
        const std::size_t cells = i < impl_->nodes_of.size() ? impl_->nodes_of[i].size() : 0;
        const double matter = static_cast<double>(cells) * cell * cell * cell;
        if (body.shape == "sphere") {
            shape.area_m2 = kPi * d.x * d.x;
            shape.volume_m3 = kPi * d.x * d.x * d.x / 6.0;
        } else if (body.shape == "box") {
            shape.area_m2 = 2.0 * (d.x * d.y + d.y * d.z + d.x * d.z);
            shape.volume_m3 = d.x * d.y * d.z;
        } else {
            shape.area_m2 = hullArea(i);
            shape.volume_m3 = matter > 0.0 ? matter : d.x * d.y * d.z;
            // What is left of its cells, where some of their matter has burned.
            if (const auto record = impl_->matter_of.find(body.name);
                record != impl_->matter_of.end() && record->second.remaining_volume_m3 > 0.0)
                shape.volume_m3 = record->second.remaining_volume_m3;
        }
        // What it weighs now, which the network may itself have changed.
        // Scenery is static to the solver and has no mass there, so its matter
        // is counted from its cells.
        const double density = i < impl_->density_of.size() ? impl_->density_of[i] : 0.0;
        shape.mass_kg = state.mass_kg > 0.0 ? state.mass_kg : matter * density;
        const Quat q = state.motion.orientation_world;
        const Vec3 h = d * 0.5;
        const Vec3 ax = q.rotate({1.0, 0.0, 0.0}), ay = q.rotate({0.0, 1.0, 0.0}),
                   az = q.rotate({0.0, 0.0, 1.0});
        shape.half_extent_m = {std::abs(ax.x) * h.x + std::abs(ay.x) * h.y + std::abs(az.x) * h.z,
                               std::abs(ax.y) * h.x + std::abs(ay.y) * h.y + std::abs(az.y) * h.z,
                               std::abs(ax.z) * h.x + std::abs(ay.z) * h.y + std::abs(az.z) * h.z};
        shapes.push_back(std::move(shape));
    }
    return shapes;
}

thermo::ThermoWorld &LiveWorld::ensureThermo() {
    if (!impl_->thermo) impl_->thermo = std::make_unique<thermo::ThermoWorld>();
    impl_->thermo->refresh(thermoShapes(), impl_->setup->ground_y);
    return *impl_->thermo;
}

void LiveWorld::settleThermo() {
    thermo::ThermoWorld *network = impl_->thermo.get();
    if (network == nullptr || !network->active()) return;
    // Where things are changes slowly next to a step, so the heat paths are
    // worked out again every eighth accepted step -- thirty times a second at
    // the room's rate -- and whenever the body table changes.
    if (impl_->steps_taken % 8 == 0) network->refresh(thermoShapes(), impl_->setup->ground_y);
    // A body whose matter has been used up or given off weighs less, and the
    // rigid body is told, so momentum and energy are about what is really there.
    impl_->mirrorMasses();
    // Meltwater that ran off ice in the step just kept goes where the ice
    // stands: into the column of the room's water under it -- which carries it
    // on downhill, into the river if that is where the ground runs -- or, in a
    // room with no water, off across the floor. Before settleEnvironment, so
    // the water steps with it; before reviseMatter, which may take away ice
    // that has melted to nothing.
    for (const auto &[name, kg] : network->takeMeltwater()) {
        double into_water = 0.0;
        const auto found = impl_->index_of.find(name);
        if (impl_->environment && found != impl_->index_of.end() &&
            impl_->world->contains(impl_->body_of[found->second])) {
            const Vec3 at = impl_->world->snapshot(impl_->body_of[found->second]).center_of_mass_world_m;
            const water::ShallowWater *water = impl_->environment->water();
            const double density = water != nullptr ? water->settings().density_kg_m3 : 1000.0;
            into_water = density * impl_->environment->addWater(at.x, at.z, kg / density);
        }
        impl_->meltwater_into_water_kg += into_water;
        impl_->meltwater_ran_off_kg += std::max(0.0, kg - into_water);
    }
    // And where it is: the shape, the cells and the attachments of everything
    // whose matter has burned, at the network's own stride.
    if (impl_->steps_taken % 8 == 0) reviseMatter();
    // And what the heat has done to what everything can carry.
    refreshMechanics();
}

const thermo::ThermoWorld *LiveWorld::thermo() const { return impl_->thermo.get(); }

double LiveWorld::meltwaterIntoWaterKg() const { return impl_->meltwater_into_water_kg; }

double LiveWorld::meltwaterRanOffKg() const { return impl_->meltwater_ran_off_kg; }

// Heat skips exact bodies one by one, as breaking and the load survey do: the
// network never holds one (thermoShapes), so a room with a cart in it can
// still heat its ice. What is refused is heat ON an exact body, in words.
void LiveWorld::declareThermo(const std::string &json) {
    thermo::Declarations declared = thermo::readDeclarations(json);
    for (const thermo::ContentsDeclaration &contents : declared.contents)
        impl_->refuseExactHeat(contents.body, "declareThermo");
    for (const thermo::HeaterDeclaration &heater : declared.heaters)
        impl_->refuseExactHeat(heater.target, "declareThermo");
    for (const thermo::GasRegionDeclaration &region : declared.regions) {
        impl_->refuseExactHeat(region.piston, "declareThermo");
        impl_->refuseExactHeat(region.container, "declareThermo");
    }
    thermo::ThermoWorld &network = ensureThermo();
    // A heater declared into a running world starts from now.
    for (thermo::HeaterDeclaration &heater : declared.heaters) heater.start_s += network.timeS();
    thermo::apply(network, declared);
}

unsigned LiveWorld::heat(const std::string &target, double power_w, double seconds) {
    impl_->refuseExactHeat(target, "heat");
    thermo::ThermoWorld &network = ensureThermo();
    return network.heat({target, power_w, network.timeS(), seconds, "heater"});
}

void LiveWorld::setVent(const std::string &region, bool open) { ensureThermo().setVent(region, open); }

std::string LiveWorld::thermoReport(bool with_model) const {
    if (impl_->thermo) return thermo::reportJson(*impl_->thermo, with_model);
    const thermo::ThermoWorld nothing;
    return thermo::reportJson(nothing, with_model);
}

// Of what is in the world. A thing set aside (park) is not: its energy leaves
// the world with it and comes back with it -- at rest, at whatever height it is
// put -- so a total taken across a park moves by exactly that.
double LiveWorld::mechanicalEnergyJ() const {
    return impl_->world->mechanicalTotals(impl_->request.gravity_m_s2).mechanicalEnergy();
}

// ---- heat and strength (docs/thermal-mechanics.md) ------------------------------

LiveMaterialState LiveWorld::materialStateOf(std::size_t body, const Vec3 *load_world) const {
    LiveMaterialState out;
    if (body >= impl_->described.size()) return out;
    const LiveBodyPose &pose = impl_->described[body];
    out.name = pose.name;
    out.material = pose.material;
    // The section is taken across the box its matter is measured against --
    // as authored -- with what burned away inside it: once, never twice.
    const Vec3 d = referenceBoxOf(body);
    out.dimensions_m = d;
    out.reference_m = d;
    out.remaining_m = pose.dimensions_m;
    {
        const double cell = impl_->request.cell_size_m;
        const std::size_t cells = body < impl_->nodes_of.size() ? impl_->nodes_of[body].size() : 0;
        out.cells = cells;
        const Vec3 &now = pose.dimensions_m;
        double volume = pose.shape == "sphere" ? 3.14159265358979323846 * now.x * now.x * now.x / 6.0
                      : pose.shape == "box"    ? now.x * now.y * now.z
                                               : static_cast<double>(cells) * cell * cell * cell;
        if (const auto record = impl_->matter_of.find(pose.name); record != impl_->matter_of.end()) {
            const MatterRecord &r = record->second;
            if (r.remaining_volume_m3 > 0.0) volume = r.remaining_volume_m3;
            out.cells_burned = r.cells_burned;
            out.revision = r.revision;
            out.bond_tension_min = r.bond_tension_min;
            out.bond_tension_mean = r.bond_tension_mean;
            out.bond_stiffness_mean = r.bond_stiffness_mean;
        }
        out.remaining_volume_m3 = volume;
        // What the solver moves, and its inertia about the body's own axes. The
        // world holds the inertia in the world's frame; turned back here.
        const MatterBodyId id = impl_->body_of[body];
        if (impl_->world->contains(id)) {
            const RigidMechanicalState held = impl_->world->mechanicalState(id);
            out.mass_kg = held.mass_kg;
            const Quat q = held.motion.orientation_world;
            const Vec3 axes[3] = {q.rotate({1.0, 0.0, 0.0}), q.rotate({0.0, 1.0, 0.0}), q.rotate({0.0, 0.0, 1.0})};
            out.inertia_kg_m2 = {dot(axes[0], held.inertia_world_kg_m2 * axes[0]),
                                 dot(axes[1], held.inertia_world_kg_m2 * axes[1]),
                                 dot(axes[2], held.inertia_world_kg_m2 * axes[2])};
        }
        // Scenery has no mass in the solver; its matter still has one.
        if (!(out.mass_kg > 0.0)) {
            const double density = body < impl_->density_of.size() ? impl_->density_of[body] : 0.0;
            out.mass_kg = static_cast<double>(cells) * cell * cell * cell * density;
            if (impl_->thermo)
                if (const auto held = impl_->thermo->matter(pose.name)) out.mass_kg = held->surface_kg + held->core_kg;
        }
    }
    // The axis of the body's own box the load runs along: the one the load's
    // direction lies nearest, taken into the body's frame -- and into its
    // shape's, for a box authored at a tilt, whose tilt lives in the shape.
    // With no load given, its longest axis.
    int along = d.x >= d.y && d.x >= d.z ? 0 : (d.y >= d.z ? 1 : 2);
    const MatterBodyId id = impl_->body_of[body];
    if (load_world != nullptr && length(*load_world) > 1e-12 && impl_->world->contains(id)) {
        Vec3 local = conjugateOf(impl_->world->snapshot(id).orientation_world).rotate(*load_world);
        if (const auto tilt = impl_->tilt_of.find(pose.name); tilt != impl_->tilt_of.end())
            local = conjugateOf(tilt->second).rotate(local);
        const double ax = std::abs(local.x), ay = std::abs(local.y), az = std::abs(local.z);
        along = ax >= ay && ax >= az ? 0 : (ay >= az ? 1 : 2);
    }
    // Cold and whole unless the thermal network holds it.
    thermo::MatterState matter;
    matter.body = pose.name;
    matter.material = pose.material;
    if (impl_->thermo) {
        if (const std::optional<thermo::MatterState> held = impl_->thermo->matter(pose.name)) {
            matter = *held;
            out.tracked = true;
        }
    }
    out.surface_k = matter.surface_k;
    out.core_k = matter.core_k;
    out.peak_surface_k = matter.peak_surface_k;
    out.peak_core_k = matter.peak_core_k;
    out.remaining_fraction = 1.0 - matter.consumed_fraction;
    out.composition_factor = matter.composition_factor;
    if (const thermo::MechanicalLaw *law = thermo::lawFor(pose.material)) {
        out.law = law->id;
        out.provenance = std::string(thermo::provenanceName(law->provenance));
        out.section = thermo::evaluateSection(*law, matter, d, along);
    } else {
        // No law: the section is as it was built, and every factor is one.
        const auto side = [&](int k) { return k == 0 ? d.x : (k == 1 ? d.y : d.z); };
        const double u = side((along + 1) % 3), v = side((along + 2) % 3);
        out.section.breadth_m = std::min(u, v);
        out.section.depth_m = std::max(u, v);
        out.section.sound_breadth_m = out.section.breadth_m;
        out.section.sound_depth_m = out.section.depth_m;
    }
    return out;
}

std::vector<LiveMaterialState> LiveWorld::materialStates() const {
    std::set<std::size_t> listed;
    if (impl_->thermo)
        for (const thermo::BodyHeat &heat : impl_->thermo->bodies())
            if (const auto found = impl_->index_of.find(heat.body); found != impl_->index_of.end())
                listed.insert(found->second);
    for (const Impl::SceneJoint &joint : impl_->joints) {
        if (joint.member_end < 0 || !joint.attached) continue;
        const auto found = impl_->index_of.find(joint.member_end == 0 ? joint.a : joint.b);
        if (found != impl_->index_of.end()) listed.insert(found->second);
    }
    std::vector<LiveMaterialState> out;
    out.reserve(listed.size());
    for (const std::size_t body : listed) out.push_back(materialStateOf(body, nullptr));
    return out;
}

bool LiveWorld::setJointMember(unsigned joint, const std::string &member) {
    for (Impl::SceneJoint &j : impl_->joints) {
        if (j.id != joint) continue;
        const bool fixing = j.kind == JoltWorld::JointKind::Fixing;
        const bool link = j.kind == JoltWorld::JointKind::Link;
        const bool elastic = j.kind == JoltWorld::JointKind::Elastic;
        // A pin, a slide and an ideal pulley have no strength here to lose.
        if (!fixing && !link && !elastic) return false;
        if (!member.empty() && member != j.a && member != j.b) return false;
        // A member is rated from its own cells' section. An exact body has no
        // cells, and a rating read off the box round it would be invented; its
        // joint holds what was declared.
        if (!member.empty()) {
            const auto found = impl_->index_of.find(member);
            if (found != impl_->index_of.end() && impl_->isPrecise(found->second)) return false;
        }
        if (!j.declared_kept) {
            j.declared_tension_n = j.holds_tension_n;
            j.declared_shear_n = j.holds_shear_n;
            j.declared_breaks_at_n = j.breaks_at_n;
            j.declared_stiffness_n_m = j.stiffness_n_m;
            j.declared_kept = true;
        }
        const auto wakeEnds = [&]() {
            for (const std::string &side : {j.a, j.b}) {
                const auto found = impl_->index_of.find(side);
                if (found != impl_->index_of.end() && impl_->inWorld(found->second))
                    impl_->world->wake(impl_->body_of[found->second]);
            }
        };
        if (member.empty()) {
            // Back to the numbers that were declared. A spring's stiffness goes
            // back too, and what that does to the energy it holds is accounted
            // for exactly as heat changing it would be.
            if (elastic && j.rigid != 0 && impl_->world->hasJoint(j.rigid) &&
                j.stiffness_n_m != j.declared_stiffness_n_m) {
                const double stretched = impl_->spanOf(j) - j.rest_m;
                const double stored_change =
                    0.5 * (j.declared_stiffness_n_m - j.stiffness_n_m) * stretched * stretched;
                impl_->world->updateElastic(j.rigid, j.declared_stiffness_n_m, j.damping_n_s_m);
                if (stored_change != 0.0 && impl_->thermo && j.member_end >= 0)
                    impl_->thermo->receiveMechanicalWork(j.member_end == 0 ? j.a : j.b, -stored_change);
                if (j.member_end >= 0) impl_->elastic_to_heat_j -= stored_change;
            }
            j.member_end = -1;
            j.holds_tension_n = j.declared_tension_n;
            j.holds_shear_n = j.declared_shear_n;
            j.breaks_at_n = j.declared_breaks_at_n;
            j.stiffness_n_m = j.declared_stiffness_n_m;
            j.rated_tension_n = j.rated_shear_n = j.rated_breaks_at_n = j.rated_stiffness_n_m = 0.0;
            j.capacity_fraction = j.checked_fraction = 1.0;
            j.member_said.clear();
            wakeEnds();
            return true;
        }
        const auto at = impl_->index_of.find(member);
        if (at == impl_->index_of.end()) return false;
        j.member_end = member == j.a ? 0 : 1;
        // Cold, it holds what was declared -- or, where that was zero, what the
        // member's own section can take in its own material: shear strength
        // across it, tensile strength along it.
        const Vec3 load = impl_->loadDirection(j);
        const LiveMaterialState whole = materialStateOf(at->second, &load);
        const double area = whole.section.breadth_m * whole.section.depth_m;
        const MaterialDefinition &made_of = impl_->definitionOf(at->second);
        if (fixing) {
            j.rated_tension_n = j.declared_tension_n > 0.0 ? j.declared_tension_n
                                                           : made_of.tensile_strength_pa * area;
            j.rated_shear_n = j.declared_shear_n > 0.0 ? j.declared_shear_n
                                                       : made_of.shear_strength_pa * area;
        } else if (link) {
            j.rated_breaks_at_n = j.declared_breaks_at_n > 0.0 ? j.declared_breaks_at_n
                                                               : made_of.tensile_strength_pa * area;
        } else {
            j.rated_stiffness_n_m = j.declared_stiffness_n_m;
        }
        j.capacity_fraction = j.checked_fraction = 1.0;
        wakeEnds();
        refreshMechanics();
        return true;
    }
    return false;
}

void LiveWorld::refreshMechanics() {
    // A change of a fifth of a percent of what a joint could take cold is
    // worth asking about again; less is the heat creeping on.
    constexpr double kRecheck = 0.002;
    // The least of its stiffness an elastic keeps: Jolt's spring needs some.
    constexpr double kSoftest = 1.0e-3;
    for (Impl::SceneJoint &j : impl_->joints) {
        if (j.member_end < 0 || !j.attached || j.rigid == 0) continue;
        if (!impl_->world->hasJoint(j.rigid)) continue;
        const std::string member = j.member_end == 0 ? j.a : j.b;
        const auto at = impl_->index_of.find(member);
        if (at == impl_->index_of.end()) continue;
        const Vec3 load = impl_->loadDirection(j);
        const LiveMaterialState state = materialStateOf(at->second, &load);
        const thermo::SectionState &s = state.section;
        double fraction = 1.0;
        if (j.kind == JoltWorld::JointKind::Fixing) {
            j.holds_tension_n = j.rated_tension_n * s.tension;
            j.holds_shear_n = j.rated_shear_n * s.shear;
            fraction = std::min(s.tension, s.shear);
        } else if (j.kind == JoltWorld::JointKind::Link) {
            j.breaks_at_n = j.rated_breaks_at_n * s.tension;
            fraction = s.tension;
        } else if (j.kind == JoltWorld::JointKind::Elastic) {
            fraction = s.axial_stiffness;
            const double k = j.rated_stiffness_n_m * std::max(fraction, kSoftest);
            if (std::abs(k - j.stiffness_n_m) > 1.0e-9 * j.rated_stiffness_n_m) {
                // At the stretch it has now, the energy it holds changes by
                // half the change in stiffness times the stretch squared. That
                // energy is not made or lost: what a softening limb stops
                // holding goes into its matter as heat, and what stiffening
                // takes comes out of it -- a crossing in the thermal ledger.
                const double stretched = impl_->spanOf(j) - j.rest_m;
                const double stored_change = 0.5 * (k - j.stiffness_n_m) * stretched * stretched;
                impl_->world->updateElastic(j.rigid, k, j.damping_n_s_m);
                j.stiffness_n_m = k;
                if (stored_change != 0.0 && impl_->thermo)
                    impl_->thermo->receiveMechanicalWork(member, -stored_change);
                impl_->elastic_to_heat_j -= stored_change;
            }
        }
        j.capacity_fraction = fraction;
        j.member_said = describeMember(state);
        // Heat moved what it can take: ask again, now, whether it still holds.
        // Both ends are woken so the next step's solve MEASURES the load -- a
        // gate asleep on its peg carries its weight all the same, and the
        // answer must come from the solver, not from before the change.
        if (std::abs(fraction - j.checked_fraction) > kRecheck) {
            j.checked_fraction = fraction;
            ++j.rechecks;
            for (const std::string &side : {j.a, j.b}) {
                const auto found = impl_->index_of.find(side);
                if (found != impl_->index_of.end()) impl_->world->wake(impl_->body_of[found->second]);
            }
            impl_->survey_due = true;
        }
    }
    // Beams: a heated body whose bending section has moved is surveyed again
    // on the next step. At the thermal network's own stride -- its heat paths
    // are worked out every eighth step, and a section does not move faster.
    if (impl_->thermo && impl_->steps_taken % 8 == 0) {
        for (const thermo::BodyHeat &heat : impl_->thermo->bodies()) {
            const thermo::MechanicalLaw *law = thermo::lawFor(heat.material);
            if (law == nullptr) continue;
            const auto found = impl_->index_of.find(heat.body);
            if (found == impl_->index_of.end()) continue;
            const std::optional<thermo::MatterState> matter = impl_->thermo->matter(heat.body);
            if (!matter) continue;
            const thermo::SectionState s =
                thermo::evaluateSection(*law, *matter, referenceBoxOf(found->second), 0, 1);
            // Either side of the bending moving is a reason to ask again.
            const double side = std::min(s.bending, s.bending_compression);
            double &seen = impl_->bending_seen.try_emplace(heat.body, 1.0).first->second;
            if (std::abs(side - seen) > kRecheck) {
                seen = side;
                impl_->survey_due = true;
            }
        }
    }
}

// ---- one material state (docs/thermal-mechanics.md, "One material state") ------
//
// The thermal network owns the state of a body's matter -- how hot each zone is
// and has been, how much of what it holds is left. Everything below lays that
// state over the body's reference box, as the MaterialField, and reads it from
// there and nowhere else: the lattice a fracture is run in, the collision shape,
// the mass properties, the attachments and the reports.

LiveWorld::MatterRecord &LiveWorld::recordOf(std::size_t body) const {
    Impl &I = *impl_;
    const LiveBodyPose &pose = I.described[body];
    if (const auto found = I.matter_of.find(pose.name); found != I.matter_of.end()) return found->second;
    MatterRecord record;
    if (pose.shape == "box" || pose.shape == "sphere") {
        // As authored. Nothing has cut it yet -- only a revision does, and a
        // revision makes this record first -- so this is the box it was made as.
        record.box_m = pose.dimensions_m;
        record.round = pose.shape == "sphere";
        if (const auto tilt = I.tilt_of.find(pose.name); tilt != I.tilt_of.end()) record.turn = tilt->second;
    } else {
        // The cells' own box, in the body's frame: a piece, a join, a cone.
        const double cell = I.request.cell_size_m;
        Vec3 low{}, high{};
        bool first = true;
        for (const std::uint32_t node : I.nodes_of[body]) {
            const Vec3 &at = I.cell_offset_m[node];
            if (first) { low = high = at; first = false; continue; }
            low = {std::min(low.x, at.x), std::min(low.y, at.y), std::min(low.z, at.z)};
            high = {std::max(high.x, at.x), std::max(high.y, at.y), std::max(high.z, at.z)};
        }
        record.box_m = high - low + Vec3{cell, cell, cell};
        record.centre_m = 0.5 * (low + high);
    }
    return I.matter_of.emplace(pose.name, record).first->second;
}

Vec3 LiveWorld::referenceBoxOf(std::size_t body) const {
    if (body >= impl_->described.size()) return {};
    const auto found = impl_->matter_of.find(impl_->described[body].name);
    return found != impl_->matter_of.end() ? found->second.box_m : impl_->described[body].dimensions_m;
}

Vec3 LiveWorld::inReference(std::size_t body, const Vec3 &local_m) const {
    const MatterRecord &record = recordOf(body);
    return conjugateOf(record.turn).rotate(local_m - record.centre_m);
}

std::optional<thermo::MaterialField> LiveWorld::fieldOf(std::size_t body) const {
    if (!impl_->thermo || body >= impl_->described.size()) return std::nullopt;
    const LiveBodyPose &pose = impl_->described[body];
    const thermo::MechanicalLaw *law = thermo::lawFor(pose.material);
    if (law == nullptr) return std::nullopt;
    const std::optional<thermo::MatterState> matter = impl_->thermo->matter(pose.name);
    if (!matter) return std::nullopt;
    const MatterRecord &record = recordOf(body);
    return thermo::materialField(law, *matter, record.box_m, record.round);
}

std::unique_ptr<LiveWorld::HeatedCells> LiveWorld::heatedCellsOf(const std::vector<std::size_t> &bodies) const {
    auto out = std::make_unique<HeatedCells>();
    const Impl &I = *impl_;
    const double cell = I.request.cell_size_m;
    for (const std::size_t body : bodies) {
        if (body >= I.nodes_of.size() || I.nodes_of[body].empty()) continue;
        const std::optional<thermo::MaterialField> field = fieldOf(body);
        if (!field) continue;
        const std::vector<std::uint32_t> &nodes = I.nodes_of[body];
        std::vector<thermo::CellShare> shares;
        shares.reserve(nodes.size());
        double cold = 0.0, weighted = 0.0;
        bool changed = false;
        for (const std::uint32_t node : nodes) {
            const thermo::CellShare share =
                atLeast(thermo::cellShare(*field, inReference(body, I.cell_offset_m[node]), cell));
            shares.push_back(share);
            const double m0 = I.setup->matter.nodes[node].mass_kg;
            cold += m0;
            weighted += m0 * share.remaining();
            changed = changed || !wholeFactors(thermo::cellFactors(*field, share));
        }
        const double lump = field->surface_kg + field->core_kg;
        // Nothing has happened to it that a run could see: it is left exactly
        // as it was built, bit for bit.
        if (!changed && std::abs(lump - cold) <= 1.0e-9 * cold) continue;
        thermo::ZoneFactors sum{0.0, 0.0, 0.0, 0.0};
        for (std::size_t k = 0; k < nodes.size(); ++k) {
            const std::uint32_t node = nodes[k];
            const double m0 = I.setup->matter.nodes[node].mass_kg;
            // The network's mass, spread over what is left: each cell's share is
            // its cold mass times the share of it still there (declared).
            out->mass_kg[node] = weighted > 0.0 ? lump * m0 * shares[k].remaining() / weighted : m0;
            const thermo::ZoneFactors f = thermo::cellFactors(*field, shares[k]);
            out->factors[node] = f;
            sum.stiffness += f.stiffness;
            sum.tension += f.tension;
            sum.compression += f.compression;
            sum.shear += f.shear;
        }
        const double n = static_cast<double>(nodes.size());
        out->mean[I.described[body].name] = {sum.stiffness / n, sum.tension / n, sum.compression / n,
                                             sum.shear / n};
    }
    return out;
}

void LiveWorld::heatIsland(FragmentLattice &island, const HeatedCells &heated, const std::string &name,
                           bool bonds) {
    if (heated.mass_kg.empty() || island.asset == nullptr) return;
    double total = 0.0;
    for (std::size_t local = 0; local < island.parent_node.size(); ++local) {
        const auto mass = heated.mass_kg.find(island.parent_node[local]);
        if (mass != heated.mass_kg.end()) island.matter.nodes[local].mass_kg = mass->second;
        total += island.matter.nodes[local].mass_kg;
    }
    island.asset->total_mass_kg = total;
    if (!bonds) return;
    std::size_t weakened = 0, carries_nothing = 0;
    double weakest = 1.0;
    for (std::size_t k = 0; k < island.asset->bonds.size() && k < island.matter.bonds.size(); ++k) {
        BondRest &bond = island.asset->bonds[k];
        const auto a = heated.factors.find(island.parent_node[bond.node_a]);
        const auto b = heated.factors.find(island.parent_node[bond.node_b]);
        if (a == heated.factors.end() && b == heated.factors.end()) continue;
        const thermo::ZoneFactors &fa = a != heated.factors.end() ? a->second : b->second;
        const thermo::ZoneFactors &fb = b != heated.factors.end() ? b->second : a->second;
        const thermo::ZoneFactors f = thermo::bondFactors(fa, fb);
        if (wholeFactors(f) || !island.matter.bonds[k].alive) continue;
        if (!weakenBond(bond, f)) {
            island.matter.bonds[k].alive = false;
            ++carries_nothing;
            continue;
        }
        ++weakened;
        weakest = std::min(weakest, f.tension);
    }
    // Said, like a spared bond: how many bonds heat changed, and the weakest
    // tension factor among them. A bond that carries nothing is char or burned.
    if (weakened + carries_nothing > 0)
        impl_->delays.push_back({impl_->time_s, name, "heated", static_cast<double>(weakened + carries_nothing),
                                 weakest});
}

void LiveWorld::refreshHeatedBonds(std::size_t body, const thermo::MaterialField &field) {
    Impl &I = *impl_;
    MatterRecord &record = recordOf(body);
    const std::vector<std::uint32_t> &nodes = I.nodes_of[body];
    const TileImpactSetup &setup = *I.setup;
    if (setup.matter.asset == nullptr || nodes.empty()) return;
    // Only when the field has moved since the last time -- a fifth of a percent
    // in any factor, 0.1 mm of burning, or a cell gone.
    const auto moved = [](const thermo::ZoneFactors &a, const thermo::ZoneFactors &b) {
        return std::abs(a.stiffness - b.stiffness) > 2.0e-3 || std::abs(a.tension - b.tension) > 2.0e-3 ||
               std::abs(a.compression - b.compression) > 2.0e-3 || std::abs(a.shear - b.shear) > 2.0e-3;
    };
    if (record.seen_consumed_m >= 0.0 && record.seen_cells == nodes.size() &&
        std::abs(field.consumed_m - record.seen_consumed_m) < 1.0e-4 && !moved(field.surface, record.seen_surface) &&
        !moved(field.core, record.seen_core))
        return;
    record.seen_surface = field.surface;
    record.seen_core = field.core;
    record.seen_consumed_m = field.consumed_m;
    record.seen_cells = nodes.size();
    const LatticeAsset &asset = *setup.matter.asset;
    const double cell = I.request.cell_size_m;
    std::unordered_map<std::uint32_t, thermo::ZoneFactors> factor;
    factor.reserve(nodes.size());
    for (const std::uint32_t node : nodes)
        factor.emplace(node, thermo::cellFactors(field, atLeast(thermo::cellShare(
                                                            field, inReference(body, I.cell_offset_m[node]), cell))));
    std::size_t counted = 0, live = 0;
    bool changed = false;
    double tension_min = 1.0, tension_sum = 0.0, stiffness_sum = 0.0;
    double stretch_min = std::numeric_limits<double>::infinity();
    double energy_min = std::numeric_limits<double>::infinity();
    for (const std::uint32_t node : nodes) {
        if (node + 1U >= asset.adjacency_offsets.size()) continue;
        for (std::uint32_t k = asset.adjacency_offsets[node]; k < asset.adjacency_offsets[node + 1U]; ++k) {
            const std::uint32_t o = asset.adjacent_bond_indices[k];
            const BondRest &rest = asset.bonds[o];
            if (rest.node_a != node) continue;   // each bond once, from its first end
            const auto other = factor.find(rest.node_b);
            if (other == factor.end() || o >= setup.matter.bonds.size() || !setup.matter.bonds[o].alive) continue;
            const thermo::ZoneFactors f = thermo::bondFactors(factor.at(node), other->second);
            ++counted;
            tension_min = std::min(tension_min, f.tension);
            tension_sum += f.tension;
            stiffness_sum += f.stiffness;
            changed = changed || !wholeFactors(f);
            BondRest given = rest;
            if (!wholeFactors(f) && !weakenBond(given, f)) continue;
            ++live;
            const double stretch = bondRemovalStretch(given);
            if (!std::isfinite(stretch) || !(stretch > 0.0)) continue;
            stretch_min = std::min(stretch_min, stretch);
            if (given.compliance > 0.0) {
                const double extension = stretch * given.rest_length_m;
                energy_min = std::min(energy_min, 0.5 * extension * extension / given.compliance);
            }
        }
    }
    const double count = static_cast<double>(counted);
    record.bond_tension_min = counted > 0 ? tension_min : 1.0;
    record.bond_tension_mean = counted > 0 ? tension_sum / count : 1.0;
    record.bond_stiffness_mean = counted > 0 ? stiffness_sum / count : 1.0;
    // The admission bound -- the speed below which a blow CANNOT break this --
    // follows the same bonds, or a heated body would only ever be offered for
    // blows that would have broken it cold. Left as it was built while nothing
    // has happened to it, and put back as it was built when it recovers.
    if (body >= I.limits_of.size()) return;
    const MaterialDefinition &made_of = I.definitionOf(body);
    if (!changed) {
        if (record.limits_heated) {
            I.limits_of[body] = fragmentFractureLimits(setup.matter, nodes, made_of.density_kg_m3,
                                                       made_of.young_modulus_pa, made_of.yield_strength_pa,
                                                       made_of.fracture_energy_j_m2, I.request.cell_size_m);
            if (body < I.impedance_of.size())
                I.impedance_of[body] = acousticImpedance(made_of.density_kg_m3, made_of.young_modulus_pa);
            record.limits_heated = false;
        }
        return;
    }
    record.limits_heated = true;
    const double volume = record.remaining_volume_m3 > 0.0
                              ? record.remaining_volume_m3
                              : static_cast<double>(nodes.size()) * cell * cell * cell;
    const double mass = field.surface_kg + field.core_kg;
    const double density = volume > 0.0 && mass > 0.0 ? mass / volume : made_of.density_kg_m3;
    const double modulus = made_of.young_modulus_pa * record.bond_stiffness_mean;
    FragmentFractureLimits &limits = I.limits_of[body];
    limits.cells = nodes.size();
    limits.live_bonds = live;
    limits.bar_wave_speed_m_s = density > 0.0 && modulus > 0.0 ? std::sqrt(modulus / density) : 0.0;
    limits.acoustic_impedance_pa_s_m = acousticImpedance(density, modulus);
    limits.minimum_removal_stretch = stretch_min;
    limits.minimum_removal_energy_j = std::isfinite(energy_min) ? energy_min : 0.0;
    limits.yield_stretch = made_of.yield_strength_pa > 0.0 && made_of.young_modulus_pa > 0.0 &&
                                   record.bond_stiffness_mean > kSoftestBond
                               ? made_of.yield_strength_pa / made_of.young_modulus_pa *
                                     record.bond_tension_mean / record.bond_stiffness_mean
                               : 0.0;
    if (body < I.impedance_of.size()) I.impedance_of[body] = limits.acoustic_impedance_pa_s_m;
}

void LiveWorld::reviseMatter() {
    Impl &I = *impl_;
    thermo::ThermoWorld *network = I.thermo.get();
    if (network == nullptr || !network->active()) return;
    const double cell = I.request.cell_size_m;
    // Whatever an unfinished fracture holds an index to waits for the next pass.
    const auto busy = [&](std::size_t body) {
        const auto holds = [&](const Pending &job) {
            if (job.which == body || job.anvil == body) return true;
            return std::find(job.island_bodies.begin(), job.island_bodies.end(), body) != job.island_bodies.end();
        };
        if (I.pending && holds(*I.pending)) return true;
        if (I.guessing && holds(*I.guessing)) return true;
        for (const auto &job : I.queued)
            if (holds(*job)) return true;
        return std::find(I.held_for_fracture.begin(), I.held_for_fracture.end(), body) !=
               I.held_for_fracture.end();
    };
    // Anything that might have been resting on or against a body whose shape
    // has changed is woken: a crate asleep on a plank that burns thinner would
    // otherwise hang in the air where the plank's top used to be.
    const auto wakeAround = [&](std::size_t body) {
        if (!I.world->contains(I.body_of[body])) return;
        const Vec3 at = I.world->snapshot(I.body_of[body]).center_of_mass_world_m;
        const double reach = 0.5 * length(referenceBoxOf(body)) + 0.05;
        for (std::size_t j = 0; j < I.described.size(); ++j) {
            if (I.described[j].anchored || !I.world->contains(I.body_of[j])) continue;
            const Vec3 there = I.world->snapshot(I.body_of[j]).center_of_mass_world_m;
            if (length(there - at) <= reach + 0.5 * length(I.described[j].dimensions_m)) I.world->wake(I.body_of[j]);
        }
    };
    // A joint holds what it was fixed to until that has burned away from under
    // its point by more than it grips -- half a cell, declared: the joint model
    // has no embedment depth of its own.
    const auto partBurnedJoints = [&](std::size_t body, const thermo::MaterialField &field) {
        const std::string &name = I.described[body].name;
        const double grip = 0.5 * cell;
        for (Impl::SceneJoint &joint : I.joints) {
            if (!joint.attached) continue;
            for (int end = 0; end < 2 && joint.attached; ++end) {
                if ((end == 0 ? joint.a : joint.b) != name) continue;
                const Vec3 at = inReference(body, jointPoint(joint, end));
                const double gone = thermo::outsideRemainingM(field, at) - thermo::outsideReferenceM(field, at);
                if (!(gone > grip)) continue;
                if (joint.rigid != 0 && I.world->hasJoint(joint.rigid)) I.world->removeJoint(joint.rigid);
                joint.rigid = 0;
                joint.attached = false;
                char text[400];
                const std::string word = goneWord(I.described[body].material);
                std::snprintf(text, sizeof text,
                              "the %s it was fixed to has %s away under it: %.1f mm of it gone from where "
                              "the joint held, more than the %.1f mm a joint grips (half a cell)",
                              name.c_str(), word.c_str(), 1000.0 * gone, 1000.0 * grip);
                joint.parted_because = text;
                for (const std::string &side : {joint.a, joint.b})
                    if (const auto found = I.index_of.find(side); found != I.index_of.end())
                        I.world->wake(I.body_of[found->second]);
                I.delays.push_back({I.time_s, name, word == "melted" ? "melted off" : "burned off", 1000.0 * gone, 0.0});
            }
        }
    };

    std::vector<std::pair<std::string, std::string>> going;
    std::vector<std::string> reform;
    for (const thermo::BodyHeat &heat : network->bodies()) {
        const auto found = I.index_of.find(heat.body);
        if (found == I.index_of.end()) continue;
        const std::size_t i = found->second;
        // A thing set aside is kept as it was put away: time stands still for
        // its matter, and whatever its shape is owed is paid once it is back.
        if (I.isParked(i)) continue;
        const std::optional<thermo::MaterialField> field = fieldOf(i);
        if (!field) continue;
        MatterRecord &record = recordOf(i);
        LiveBodyPose &pose = I.described[i];
        const bool primitive = pose.shape == "box" || pose.shape == "sphere";
        // Nothing has burned: no cell can have gone and no shape has moved, so
        // only its bonds -- heat alone -- can need working out again.
        if (!(field->consumed_m > 0.0)) {
            refreshHeatedBonds(i, *field);
            continue;
        }
        // Cells whose matter has all burned away leave the body.
        std::vector<std::uint32_t> kept;
        kept.reserve(I.nodes_of[i].size());
        double volume = 0.0;
        for (const std::uint32_t node : I.nodes_of[i]) {
            const thermo::CellShare share = thermo::cellShare(*field, inReference(i, I.cell_offset_m[node]), cell);
            if (share.remaining() < kGoneShare) continue;
            kept.push_back(node);
            volume += share.remaining() * cell * cell * cell;
        }
        const double left = primitive ? thermo::remainingVolumeM3(*field) : volume;
        if (kept.empty() || !(left > 0.0)) {
            if (!busy(i)) {
                char why[200];
                const std::optional<thermo::MatterState> matter = network->matter(pose.name);
                std::snprintf(why, sizeof why, "%.1f%% of its load-bearing matter %s: nothing left to hold a shape",
                              100.0 * (matter ? matter->consumed_fraction : 1.0), goneWord(pose.material).c_str());
                going.emplace_back(pose.name, why);
            }
            continue;
        }
        const std::size_t burned_now = I.nodes_of[i].size() - kept.size();
        if (burned_now > 0 && !busy(i)) {
            I.nodes_of[i] = std::move(kept);
            record.cells_burned += burned_now;
            I.hull_area_of.erase(pose.name);
            I.water_cells_of.erase(pose.name);
            if (!primitive) reform.push_back(pose.name);
        }
        record.remaining_volume_m3 = left;
        // A box or a sphere is cut to what is left of it where it stands: every
        // face in by the burned depth, the centre of mass where it was, and the
        // mass and inertia of the matter left spread over the volume left.
        if (primitive && std::abs(field->consumed_m - record.applied_m) >= kReviseDepthM &&
            I.world->contains(I.body_of[i])) {
            const Vec3 box = thermo::remainingBox(*field);
            if (box.x > 0.0 && box.y > 0.0 && box.z > 0.0) {
                const thermo::FieldMassProperties mass = thermo::massProperties(*field);
                const double turn[4] = {record.turn.w, record.turn.x, record.turn.y, record.turn.z};
                const Vec3 was = pose.dimensions_m;
                const Vec3 cut = record.round ? Vec3{box.x, box.x, box.x} : box;
                // What stands on it comes down with its top, and it comes down
                // onto what it stands on, exactly and without waking
                // (planRecession). A box turned inside its body, one in a hand,
                // or a stack the plan declines is woken and left to the solver.
                Recession plan;
                if (!record.round && i != I.holding && std::abs(std::abs(record.turn.w) - 1.0) < 1e-9) {
                    std::vector<bool> jointed(I.described.size(), false);
                    for (const Impl::SceneJoint &joint : I.joints) {
                        if (!joint.attached) continue;
                        for (const std::string *end : {&joint.a, &joint.b})
                            if (const auto at = I.index_of.find(*end);
                                at != I.index_of.end() && at->second < jointed.size())
                                jointed[at->second] = true;
                    }
                    plan = planRecession(*I.world, I.described, I.body_of, jointed, I.setup->ground_y, i, was, cut);
                }
                I.world->reshapePrimitive(I.body_of[i], record.round, box, turn, mass.mass_kg, mass.inertia_kg_m2,
                                          !plan.applies);
                pose.dimensions_m = cut;
                if (plan.applies) {
                    if (plan.lower_burned) I.world->translateBody(I.body_of[i], Vec3{0.0, -plan.recess, 0.0});
                    for (const std::size_t k : plan.carried)
                        I.world->translateBody(I.body_of[k], Vec3{0.0, -plan.top_drop, 0.0});
                }
                record.applied_m = field->consumed_m;
                pose.revision = ++record.revision;
                if (!plan.applies) wakeAround(i);
                I.survey_due = true;
            }
        }
        refreshHeatedBonds(i, *field);
        partBurnedJoints(i, *field);
    }
    for (const auto &[name, why] : going)
        if (const auto found = I.index_of.find(name); found != I.index_of.end()) burnAway(found->second, why);
    for (const std::string &name : reform)
        if (const auto found = I.index_of.find(name); found != I.index_of.end()) (void)reformFromCells(found->second);
}

void LiveWorld::burnAway(std::size_t body, const std::string &why) {
    Impl &I = *impl_;
    if (body >= I.described.size()) return;
    const std::string name = I.described[body].name;
    double residue = 0.0;
    if (I.thermo)
        if (const auto matter = I.thermo->matter(name)) residue = matter->surface_kg + matter->core_kg;
    if (I.holding == body) release();
    const std::string word = goneWord(I.described[body].material);
    // Everything fixed to it comes off, and says why.
    for (Impl::SceneJoint &joint : I.joints) {
        if (!joint.attached || (joint.a != name && joint.b != name)) continue;
        if (joint.rigid != 0 && I.world->hasJoint(joint.rigid)) I.world->removeJoint(joint.rigid);
        joint.rigid = 0;
        joint.attached = false;
        joint.parted_because = "the " + name + " it was fixed to " + word + " away";
        for (const std::string &side : {joint.a, joint.b})
            if (const auto found = I.index_of.find(side); found != I.index_of.end() && side != name)
                I.world->wake(I.body_of[found->second]);
    }
    // And what rested on it falls.
    if (I.world->contains(I.body_of[body])) {
        const Vec3 at = I.world->snapshot(I.body_of[body]).center_of_mass_world_m;
        const double reach = 0.5 * length(referenceBoxOf(body)) + 0.05;
        for (std::size_t j = 0; j < I.described.size(); ++j) {
            if (j == body || I.described[j].anchored || !I.world->contains(I.body_of[j])) continue;
            const Vec3 there = I.world->snapshot(I.body_of[j]).center_of_mass_world_m;
            if (length(there - at) <= reach + 0.5 * length(I.described[j].dimensions_m)) I.world->wake(I.body_of[j]);
        }
    }
    I.burned_away.push_back({name, I.described[body].material, I.time_s, residue, why, word});
    I.delays.push_back({I.time_s, name, word == "melted" ? "melted away" : "burned away", 1000.0 * residue, 0.0});
    // What it still held -- its ash, the last of its moisture -- leaves the
    // thermal network with it, as a crossing the ledger counts (left_kg).
    dropBodies({body});
}

std::size_t LiveWorld::reformFromCells(std::size_t which) {
    Impl &I = *impl_;
    TileImpactSetup &setup = *I.setup;
    if (which >= I.described.size() || which >= I.nodes_of.size()) return 0;
    const LiveBodyPose parent = I.described[which];
    const std::vector<std::uint32_t> nodes = I.nodes_of[which];
    const MatterBodyId old_body = I.body_of[which];
    if (parent.anchored || nodes.empty() || !I.world->contains(old_body)) return 1;
    const RigidSnapshot snap = I.world->snapshot(old_body);
    const MaterialDefinition material = I.definitionOf(which);
    const std::unique_ptr<HeatedCells> heated = heatedCellsOf({which});
    std::optional<MatterRecord> record;
    if (const auto found = I.matter_of.find(parent.name); found != I.matter_of.end()) record = found->second;

    // Its cells as they are, moving as it moves.
    FragmentLattice island = buildFragmentLattice(
        setup.matter, nodes, I.cell_offset_m,
        FragmentPose{snap.center_of_mass_world_m, snap.orientation_world, snap.linear_velocity_m_s,
                     snap.angular_velocity_rad_s},
        I.plastic_extension_m, I.plastic_strain_m);
    // Weighed as what is left of them, so the rebuilt body's mass, centre of
    // mass and inertia are the matter's. Its bonds are left alone: char holds
    // its place until something tests it.
    heatIsland(island, *heated, parent.name, false);
    const auto components = findConnectedComponents(island.matter);
    if (components.empty()) return 0;
    const bool whole = components.size() == 1;

    const CombinedContactMaterial against_ground = combineContactMaterials(
        compileContactMaterial(material), compileContactMaterial(setup.ground_material));
    const double rolling = compileContactMaterial(material).rolling_resistance;
    std::vector<RigidFragmentDescription> fragments;
    fragments.reserve(components.size());
    for (const FragmentComponent &component : components) {
        FragmentBuildResult built = buildFragmentRepresentations(
            island.matter, std::span<const FragmentComponent>(&component, 1),
            {.first_body_id = I.next_body_id++,
             .maximum_rigid_fragments = 1,
             .minimum_nodes_per_rigid_fragment = 1,
             .maximum_collision_points = 192,
             .friction = against_ground.dynamic_friction,
             .restitution = against_ground.restitution,
             .rolling_resistance = rolling});
        if (built.rigid_fragments.empty()) return 1;
        fragments.push_back(std::move(built.rigid_fragments.front()));
    }

    std::vector<std::string> before;
    before.reserve(I.described.size());
    for (const LiveBodyPose &pose : I.described) before.push_back(pose.name);

    // Where its joints hold it, in the world, before it is rebuilt.
    struct Pinned {
        Impl::SceneJoint *joint;
        int end;
        Vec3 world;
        Vec3 world_b;   // end b of a pin also keeps point_local_b in step
    };
    std::vector<Pinned> pinned;
    for (Impl::SceneJoint &joint : I.joints) {
        if (!joint.attached) continue;
        for (int end = 0; end < 2; ++end) {
            if ((end == 0 ? joint.a : joint.b) != parent.name) continue;
            const Vec3 world = snap.center_of_mass_world_m + snap.orientation_world.rotate(jointPoint(joint, end));
            const Vec3 world_b = snap.center_of_mass_world_m + snap.orientation_world.rotate(joint.point_local_b);
            pinned.push_back({&joint, end, world, world_b});
        }
    }
    // The kerfs it carried, in the world, to hand on.
    std::vector<Impl::Kerf> handed;
    if (const auto carried = I.kerfs.find(parent.name); carried != I.kerfs.end()) {
        for (Impl::Kerf kerf : carried->second) {
            kerf.origin = snap.center_of_mass_world_m + snap.orientation_world.rotate(kerf.origin);
            kerf.u = snap.orientation_world.rotate(kerf.u);
            kerf.v = snap.orientation_world.rotate(kerf.v);
            kerf.w = snap.orientation_world.rotate(kerf.w);
            handed.push_back(std::move(kerf));
        }
        I.kerfs.erase(carried);
    }

    I.world->removeAndDestroy(old_body);
    const auto drop = [&](auto &vector) {
        if (which < vector.size()) vector.erase(vector.begin() + static_cast<std::ptrdiff_t>(which));
    };
    drop(I.described); drop(I.body_of); drop(I.nodes_of);
    drop(I.limits_of); drop(I.impedance_of); drop(I.density_of); drop(I.tensile_of);
    drop(I.compressive_of);
    if (I.holding == which) {
        I.holding = static_cast<std::size_t>(-1);
        I.wielding = false;
    } else if (I.holding != static_cast<std::size_t>(-1) && I.holding > which) {
        --I.holding;
    }

    std::vector<std::string> made;
    for (std::size_t k = 0; k < components.size(); ++k) {
        const RigidFragmentDescription &fragment = fragments[k];
        std::vector<std::uint32_t> parent_nodes;
        parent_nodes.reserve(components[k].node_indices.size());
        for (const std::uint32_t local : components[k].node_indices) {
            const std::uint32_t node = island.parent_node[local];
            parent_nodes.push_back(node);
            I.cell_offset_m[node] =
                island.matter.nodes[local].position_world_m - fragment.mass_properties.center_of_mass_world_m;
        }
        LiveBodyPose piece{};
        piece.name = whole ? parent.name : parent.name + " piece " + std::to_string(k + 1);
        piece.material = parent.material;
        piece.color_rgba = parent.color_rgba;
        piece.fragment = !whole || parent.fragment;
        piece.shape = "hull";
        if (whole) {
            piece.dent_m = parent.dent_m;
            piece.dent_at_m = snap.center_of_mass_world_m + snap.orientation_world.rotate(parent.dent_at_m) -
                              fragment.mass_properties.center_of_mass_world_m;
            piece.revision = (record ? record->revision : parent.revision) + 1;
        }
        I.limits_of.push_back(fragmentFractureLimits(setup.matter, parent_nodes, material.density_kg_m3,
                                                     material.young_modulus_pa, material.yield_strength_pa,
                                                     material.fracture_energy_j_m2, I.request.cell_size_m));
        I.impedance_of.push_back(acousticImpedance(material.density_kg_m3, material.young_modulus_pa));
        I.density_of.push_back(material.density_kg_m3);
        I.tensile_of.push_back(material.tensile_strength_pa);
        I.compressive_of.push_back(material.compressive_strength_pa);
        I.nodes_of.push_back(std::move(parent_nodes));
        piece.dimensions_m = cellBounds(I.nodes_of.back(), I.cell_offset_m, I.request.cell_size_m);
        made.push_back(piece.name);
        I.described.push_back(std::move(piece));
        I.body_of.push_back(fragment.body_id);
        I.next_body_id = std::max(I.next_body_id, fragment.body_id + 1);
    }
    I.world->addFragments(fragments);
    I.index_of.clear();
    for (std::size_t i = 0; i < I.described.size(); ++i) I.index_of.emplace(I.described[i].name, i);

    // Still one body: it measures its matter against the same box as before,
    // carried into its new frame (a rebuilt body faces the world's way, about
    // its new centre of mass). In pieces: each measures against its own cells.
    if (whole && record) {
        MatterRecord moved = *record;
        const Vec3 centre = snap.center_of_mass_world_m + snap.orientation_world.rotate(record->centre_m);
        moved.centre_m = centre - fragments.front().mass_properties.center_of_mass_world_m;
        moved.turn = composeTurns(snap.orientation_world, record->turn);
        moved.revision = record->revision + 1;
        I.matter_of[parent.name] = moved;
    } else {
        I.matter_of.erase(parent.name);
    }
    // Its joints: still one body, the same points in its new frame; in pieces,
    // rehangJoints follows each to the piece that carries it.
    if (whole) {
        const Vec3 origin = fragments.front().mass_properties.center_of_mass_world_m;
        for (const Pinned &p : pinned) {
            jointPoint(*p.joint, p.end) = p.world - origin;
            if (p.end == 1) p.joint->point_local_b = p.world_b - origin;
            if (p.end == 0) p.joint->axis_local_a = snap.orientation_world.rotate(p.joint->axis_local_a);
            p.joint->rigid = 0;
        }
    } else {
        I.vanished[parent.name] = snap;
    }
    // What it held, shared out by cells, exactly as a cut shares it.
    if (I.thermo && I.thermo->active()) {
        if (!whole && I.thermo->holds(parent.name)) {
            std::vector<std::pair<std::string, double>> shares;
            const double all = static_cast<double>(nodes.size());
            for (std::size_t k = 0; k < made.size(); ++k)
                shares.emplace_back(made[k], static_cast<double>(components[k].node_indices.size()) / all);
            I.thermo->split(parent.name, shares);
        }
        I.thermo->refresh(thermoShapes(), setup.ground_y);
    }
    for (std::size_t k = 0; k < made.size(); ++k) {
        const Vec3 centre = fragments[k].mass_properties.center_of_mass_world_m;
        const std::size_t index = I.index_of[made[k]];
        for (Impl::Kerf kerf : handed) {
            kerf.origin = kerf.origin - centre;
            findCrossings(kerf, I.nodes_of[index], I.cell_offset_m, setup.asset);
            I.kerfs[made[k]].push_back(std::move(kerf));
        }
    }
    dropGuess("guess-wasted");
    restackQueue(before);
    rehangJoints();
    I.vanished.clear();
    repin();
    I.held_through.erase(parent.name);
    I.partner_of.clear();
    I.survey_due = true;
    // Its bonds and its admission bound follow the field at once.
    for (const std::string &name : made)
        if (const auto found = I.index_of.find(name); found != I.index_of.end())
            if (const auto field = fieldOf(found->second)) refreshHeatedBonds(found->second, *field);
    I.delays.push_back({I.time_s, parent.name, whole ? "burned smaller" : "burned apart",
                        static_cast<double>(components.size()), 0.0});
    return components.size();
}

namespace {
// What is not modelled about heat and strength, for anyone reporting on it.
std::vector<std::string> mechanicsLimitations() {
    return {
        "A section is at most three rings -- what burned away, the surface layer, the core -- "
        "each at one temperature: a thick member's char front is not resolved inside its core",
        "One material field per body (docs/thermal-mechanics.md, \"One material state\"): burned "
        "away within the burned depth of its reference box's faces, then the surface layer, then "
        "the core. The section, the lattice a fracture is run in, the collision shape, the drawn "
        "shape, the mass, centre of mass and inertia and the attachments all read it, and nothing "
        "else",
        "Burning eats in from every face of a body's box alike (a declared approximation), so its "
        "centre of mass stays at its box's centre; the network does know that a face against the "
        "floor or another body does not burn (it takes it out of the area that reacts) but the "
        "burned depth is not yet shared out by face",
        "A lattice cell carries the field averaged over its own cube, zone by zone (a declared rule "
        "of mixtures); a bond is its two half-cells in series for stiffness and as strong as its "
        "weaker end. The failure thresholds are stretches, so each goes by its strength's factor "
        "over the stiffness's; the fracture energy has no law of its own and is not changed",
        "A cell is taken out once less than 2% of its matter is left, and a piece is then rebuilt "
        "from the cells it has; between cells, a piece's hull keeps the burned part of a cell until "
        "the whole cell has gone. A box or a sphere is cut to what is left every 0.2 mm",
        "The matter left is spread evenly over the volume left for mass, centre of mass and "
        "inertia: the network knows each zone's mass, not how it is spread within the zone",
        "A body whose load-bearing matter has all burned away leaves the world; its residue (ash, "
        "the last moisture) is not modelled as a body and leaves the thermal network with it, on "
        "the ledger",
        "A joint lets go of matter burned away from under its point by more than half a cell "
        "(declared: the joint model has no embedment depth of its own)",
        "A sustained load is answered by statics on the body's own lattice "
        "(fracture/SustainedLoad.hpp): unilateral supports under it, the weight of what rests on it "
        "on its top cells, the shared failure criterion at constant load. No creep, no dynamic "
        "amplification, and the load does not follow the body as it sags",
        "A joint is weakened by heat only when it names the body it is made of (its member): its "
        "declared strength is what that member carries cold, scaled by the share of the "
        "member's section strength that remains",
        "A fixing is checked against the force it carries, along its axis and across it, not "
        "against a bending moment",
        "Thermal expansion is not modelled",
        "Glass, aluminium, alumina ceramic, rubber and ice have no law: heat does not change what "
        "they can carry"};
}
}  // namespace

std::string LiveWorld::mechanicsReport(bool with_laws) const {
    using json = nlohmann::json;
    json bodies = json::array();
    for (const LiveMaterialState &m : materialStates()) {
        const thermo::SectionState &s = m.section;
        bodies.push_back({{"name", m.name},
                          {"material", m.material},
                          {"law", m.law},
                          {"provenance", m.provenance},
                          {"tracked", m.tracked},
                          {"surface_k", m.surface_k},
                          {"core_k", m.core_k},
                          {"peak_surface_k", m.peak_surface_k},
                          {"peak_core_k", m.peak_core_k},
                          {"remaining_fraction", m.remaining_fraction},
                          {"composition_factor", m.composition_factor},
                          {"dimensions_m", json::array({m.dimensions_m.x, m.dimensions_m.y, m.dimensions_m.z})},
                          {"section", {{"breadth_m", s.breadth_m},
                                       {"depth_m", s.depth_m},
                                       {"consumed_m", s.consumed_m},
                                       {"char_m", s.char_m},
                                       {"layer_m", s.layer_m},
                                       {"sound_breadth_m", s.sound_breadth_m},
                                       {"sound_depth_m", s.sound_depth_m}}},
                          {"factors", {{"stiffness", s.axial_stiffness},
                                       {"tension", s.tension},
                                       {"compression", s.compression},
                                       {"shear", s.shear},
                                       {"bending", s.bending}}},
                          {"if_cooled", {{"stiffness", s.stiffness_if_cooled},
                                         {"tension", s.tension_if_cooled},
                                         {"shear", s.shear_if_cooled},
                                         {"bending", s.bending_if_cooled}}},
                          {"supported", s.supported},
                          {"outside", s.outside},
                          // What is left of it, from the same field.
                          {"reference_m", json::array({m.reference_m.x, m.reference_m.y, m.reference_m.z})},
                          {"remaining_m", json::array({m.remaining_m.x, m.remaining_m.y, m.remaining_m.z})},
                          {"remaining_volume_m3", m.remaining_volume_m3},
                          {"mass_kg", m.mass_kg},
                          {"inertia_kg_m2", json::array({m.inertia_kg_m2.x, m.inertia_kg_m2.y, m.inertia_kg_m2.z})},
                          {"cells", m.cells},
                          {"cells_burned", m.cells_burned},
                          {"bonds", {{"tension_min", m.bond_tension_min},
                                     {"tension_mean", m.bond_tension_mean},
                                     {"stiffness_mean", m.bond_stiffness_mean}}},
                          {"revision", m.revision}});
    }
    for (const auto &[name, body] : impl_->precise_bodies) {
        bodies.push_back({{"name", name}, {"material", materialPresetName(body.material)},
                          {"mechanical_model", "precise-rigid-v1"}, {"tracked", false},
                          {"internal_failure_supported", false}, {"thermal_supported", false},
                          {"attachment_failure_supported", false}, {"cells", 0},
                          {"collision_boxes", body.parts.size()},
                          {"mass_kg", impl_->world->mechanicalState(impl_->body_of[impl_->index_of.at(name)]).mass_kg}});
    }
    json statics_json = json::array();
    for (const LiveStatics &s : statics())
        statics_json.push_back({{"name", s.name},
                                {"time_s", s.time_s},
                                {"stop", s.stop},
                                {"load_n", s.load_n},
                                {"first_failure_ratio", s.first_failure_ratio},
                                {"deflection_mm", 1000.0 * s.deflection_m},
                                {"bonds_removed", s.bonds_removed},
                                {"rounds", s.rounds},
                                {"solves", s.solves},
                                {"supported_cells", s.supported_cells},
                                {"loaded_cells", s.loaded_cells},
                                {"pieces", s.pieces},
                                {"cost_ms", s.cost_ms}});
    json burned_json = json::array();
    for (const LiveBurnedAway &b : burnedAway())
        burned_json.push_back({{"name", b.name},
                               {"material", b.material},
                               {"time_s", b.time_s},
                               {"residue_kg", b.residue_kg},
                               {"why", b.why},
                               {"gone", b.gone}});
    json attachments = json::array();
    for (const LiveJoint &j : joints()) {
        if (j.member.empty() && j.parted_because.empty()) continue;
        json a = {{"joint", j.id},
                  {"kind", j.kind},
                  {"a", j.a},
                  {"b", j.b},
                  {"member", j.member},
                  {"attached", j.attached},
                  {"capacity_fraction", j.capacity_fraction},
                  {"rechecks", j.rechecks},
                  {"parted_because", j.parted_because}};
        if (j.kind == "fixing") {
            a["tension_n"] = j.tension_n_now;
            a["shear_n"] = j.shear_n_now;
            a["holds_tension_n"] = j.holds_tension_n;
            a["holds_shear_n"] = j.holds_shear_n;
            a["rated_tension_n"] = j.rated_tension_n;
            a["rated_shear_n"] = j.rated_shear_n;
        } else if (j.kind == "link") {
            a["tension_n"] = j.tension_n;
            a["breaks_at_n"] = j.breaks_at_n;
            a["rated_breaks_at_n"] = j.rated_breaks_at_n;
        } else if (j.kind == "elastic") {
            a["force_n"] = j.force_n;
            a["stored_j"] = j.stored_j;
            a["stiffness_n_m"] = j.stiffness_n_m;
            a["rated_stiffness_n_m"] = j.rated_stiffness_n_m;
        }
        attachments.push_back(std::move(a));
    }
    json out = {{"time_s", impl_->time_s},
                {"bodies", std::move(bodies)},
                {"attachments", std::move(attachments)},
                {"statics", std::move(statics_json)},
                {"burned_away", std::move(burned_json)},
                {"elastic_to_heat_j", impl_->elastic_to_heat_j}};
    if (with_laws) {
        out["laws"] = json::parse(thermo::mechanicalLawsJson());
        out["limitations"] = mechanicsLimitations();
    }
    return out.dump();
}

std::vector<LiveStatics> LiveWorld::statics() const {
    std::vector<LiveStatics> out;
    out.reserve(impl_->sustained_answers.size());
    for (const auto &[name, a] : impl_->sustained_answers)
        out.push_back({name, a.time_s, a.stop, a.load_n, a.first_failure_ratio, a.deflection_m, a.bonds_removed,
                       a.rounds, a.solves, a.supported_cells, a.loaded_cells, a.pieces, a.cost_ms});
    std::sort(out.begin(), out.end(), [](const LiveStatics &a, const LiveStatics &b) { return a.name < b.name; });
    return out;
}

std::vector<LiveBurnedAway> LiveWorld::burnedAway() const {
    std::vector<LiveBurnedAway> out;
    out.reserve(impl_->burned_away.size());
    for (const Impl::BurnedAway &b : impl_->burned_away)
        out.push_back({b.name, b.material, b.time_s, b.residue_kg, b.why, b.gone});
    return out;
}

// ---- rolling resistance ---------------------------------------------------------

double LiveWorld::rollingLossJ() const { return impl_->world->rollingLossJ(); }

std::string LiveWorld::rollingReport() const {
    std::unordered_map<MatterBodyId, std::string> name_of;
    for (std::size_t i = 0; i < impl_->body_of.size() && i < impl_->described.size(); ++i)
        name_of.emplace(impl_->body_of[i], impl_->described[i].name);
    const auto nameOf = [&](MatterBodyId id) -> std::string {
        if (id == kSupportSurfaceMatterId) return "the floor";
        if (id == kGroundPatchMatterId) return "the ground";
        const auto found = name_of.find(id);
        return found == name_of.end() ? std::string() : found->second;
    };
    nlohmann::json contacts = nlohmann::json::array();
    for (const JoltWorld::RollingContactReport &c : impl_->world->rollingContacts())
        contacts.push_back({{"ball", nameOf(c.sphere)}, {"on", nameOf(c.other)},
                            {"normal", {c.normal_world.x, c.normal_world.y, c.normal_world.z}},
                            {"normal_force_n", c.normal_force_n}, {"from_solver", c.from_solver},
                            {"coefficient", c.coefficient}, {"limit_n_m", c.limit_n_m},
                            {"applied_n_m", c.applied_n_m}, {"held", c.held}, {"loss_j", c.loss_j}});
    nlohmann::json balls = nlohmann::json::array();
    for (std::size_t i = 0; i < impl_->body_of.size() && i < impl_->described.size(); ++i) {
        if (impl_->described[i].shape != "sphere") continue;
        balls.push_back({{"name", impl_->described[i].name}, {"material", impl_->described[i].material},
                         {"loss_j", impl_->world->rollingLossJ(impl_->body_of[i])}});
    }
    return nlohmann::json{
        {"loss_j", impl_->world->rollingLossJ()},
        {"contacts", std::move(contacts)},
        {"balls", std::move(balls)},
        {"law", "a couple M = c N r against a ball's turning at each contact: c the ball's own "
                "share plus the surface's, N the solver's normal force there, r the radius"}}
        .dump();
}

std::string LiveWorld::materialsJson() {
    // The names a scene uses for them.
    const auto sceneName = [](MaterialPreset preset) -> std::string {
        if (preset == MaterialPreset::Aluminum) return "aluminum";
        if (preset == MaterialPreset::Ceramic) return "ceramic";
        return std::string(materialPresetName(preset));
    };
    nlohmann::json materials = nlohmann::json::array();
    for (const MaterialPreset preset : kMaterialPresets) {
        const MaterialDefinition material = makeReferenceMaterial(preset, 0);
        const CompiledContactMaterial contact = compileContactMaterial(material);
        const RollingResistanceSource source = rollingResistanceSource(preset);
        materials.push_back({{"name", sceneName(preset)}, {"density_kg_m3", material.density_kg_m3},
                             {"static_friction", contact.static_friction},
                             {"dynamic_friction", contact.dynamic_friction},
                             {"rolling_resistance", contact.rolling_resistance},
                             {"rolling_resistance_sourced", source.sourced},
                             {"rolling_resistance_basis", std::string(source.basis)}});
    }
    nlohmann::json surfaces = nlohmann::json::array();
    const RollingResistanceSource stone = rollingResistanceSource(MaterialPreset::Concrete);
    surfaces.push_back(
        {{"name", "floor"}, {"made_of", "concrete"},
         {"rolling_resistance",
          compileContactMaterial(makeReferenceMaterial(MaterialPreset::Concrete, 0)).rolling_resistance},
         {"rolling_resistance_sourced", stone.sourced},
         {"rolling_resistance_basis", std::string(stone.basis)}});
    for (const terrain::GroundMaterial *ground :
         {&terrain::rockMaterial(), &terrain::soilMaterial(), &terrain::sandMaterial()})
        surfaces.push_back({{"name", ground->name}, {"made_of", ground->name},
                            {"rolling_resistance", ground->rolling_resistance},
                            {"rolling_resistance_sourced", ground->rolling_sourced},
                            {"rolling_resistance_basis", ground->rolling_basis}});
    return nlohmann::json{
        {"materials", std::move(materials)},
        {"surfaces", std::move(surfaces)},
        {"rolling_resistance",
         {{"law", "a couple M = c N r against a round body's turning at each contact"},
          {"pair", "c = the ball's own share + the surface's: both are deformed"},
          {"rests_if", "tan(slope) < c: a ball set down on a slope gentler than atan(c) stays"},
          {"stops_in_m", "v^2 / (2 * 5/7 * c * g) for a solid ball rolling on the level"},
          {"source", "docs/rolling-resistance.md"}}}}
        .dump();
}

// ---- terrain and water --------------------------------------------------------

std::vector<water::BodyInWater> LiveWorld::waterBodies() {
    constexpr double kPi = 3.14159265358979323846;
    std::vector<water::BodyInWater> out;
    out.reserve(impl_->described.size());
    const double cell = impl_->request.cell_size_m;
    for (std::size_t i = 0; i < impl_->described.size(); ++i) {
        const MatterBodyId id = impl_->body_of[i];
        if (!impl_->world->contains(id)) continue;
        const LiveBodyPose &pose = impl_->described[i];
        const RigidSnapshot snap = impl_->world->snapshot(id);
        water::BodyInWater b;
        b.index = out.size();
        b.body_id = id;
        b.name = pose.name;
        b.com_m = snap.center_of_mass_world_m;
        b.orientation = snap.orientation_world;
        b.velocity_m_s = snap.linear_velocity_m_s;
        b.angular_velocity_rad_s = snap.angular_velocity_rad_s;
        b.density_kg_m3 = i < impl_->density_of.size() ? impl_->density_of[i] : 1000.0;
        b.anchored = pose.anchored;
        b.held = i == impl_->holding;
        b.awake = impl_->world->isAwake(id);
        b.cell_m = cell;
        b.dimensions_m = pose.dimensions_m;
        const std::size_t cells = i < impl_->nodes_of.size() ? impl_->nodes_of[i].size() : 0;
        if (pose.shape == "sphere") {
            b.shape = water::BodyInWater::Shape::Sphere;
            b.volume_m3 = kPi / 6.0 * pose.dimensions_m.x * pose.dimensions_m.x * pose.dimensions_m.x;
        } else if (pose.shape == "box") {
            b.shape = water::BodyInWater::Shape::Box;
            b.volume_m3 = pose.dimensions_m.x * pose.dimensions_m.y * pose.dimensions_m.z;
            // A box authored tilted carries its tilt in its shape, not in its
            // pose: the box the water meets is the pose turned by the tilt.
            if (const auto tilt = impl_->tilt_of.find(pose.name); tilt != impl_->tilt_of.end()) {
                const Quat &p = b.orientation, &q = tilt->second;
                b.orientation = Quat{p.w * q.w - p.x * q.x - p.y * q.y - p.z * q.z,
                                     p.w * q.x + p.x * q.w + p.y * q.z - p.z * q.y,
                                     p.w * q.y - p.x * q.z + p.y * q.w + p.z * q.x,
                                     p.w * q.z + p.x * q.y - p.y * q.x + p.z * q.w};
            }
        } else {
            // A piece, a join or a cone: its cells are its matter and its
            // surface.
            b.shape = water::BodyInWater::Shape::Cells;
            auto &cached = impl_->water_cells_of[pose.name];
            if (cached.first != cells || cached.second.size() != cells) {
                cached.first = cells;
                cached.second.clear();
                cached.second.reserve(cells);
                for (const std::uint32_t node : impl_->nodes_of[i]) cached.second.push_back(impl_->cell_offset_m[node]);
            }
            b.cells_local_m = &cached.second;
            b.volume_m3 = static_cast<double>(cells) * cell * cell * cell;
        }
        b.mass_kg = b.density_kg_m3 * b.volume_m3;
        out.push_back(std::move(b));
    }
    return out;
}

const terrain::Environment *LiveWorld::environment() const { return impl_->environment.get(); }

terrain::TerrainField::Rect LiveWorld::takeChangedGround() {
    return impl_->environment ? impl_->environment->takeChangedGround() : terrain::TerrainField::Rect{};
}

namespace {
terrain::Environment &requireEnvironment(const std::unique_ptr<terrain::Environment> &environment) {
    if (!environment) throw std::invalid_argument("this world has no terrain: its scene declares none");
    return *environment;
}
} // namespace

terrain::EditEffect LiveWorld::dig(double ax, double az, double bx, double bz, double width_m,
                                   double depth_m) {
    return requireEnvironment(impl_->environment).dig(*impl_->world, ax, az, bx, bz, width_m, depth_m, impl_->carriedObjectsKg());
}

double LiveWorld::carriedObjectsKg() const { return impl_->carriedObjectsKg(); }

void LiveWorld::setCarryLimitKg(double kg) {
    if (impl_->environment) impl_->environment->setCarryLimitKg(kg);
}

terrain::EditEffect LiveWorld::deposit(double x, double z, double radius_m, double sand_m3, double soil_m3) {
    return requireEnvironment(impl_->environment).deposit(*impl_->world, x, z, radius_m, sand_m3, soil_m3);
}

std::string LiveWorld::withdrawGround(double sand_m3, double soil_m3) {
    return requireEnvironment(impl_->environment).withdrawCarried(sand_m3,soil_m3);
}

void LiveWorld::returnGround(double sand_m3, double soil_m3) {
    requireEnvironment(impl_->environment).returnCarried(sand_m3,soil_m3,impl_->carriedObjectsKg());
}

std::optional<terrain::CutBlock> LiveWorld::cutBlock(double x, double z, int cells_x, int cells_z,
                                                     double height_m, std::string *why) {
    terrain::Environment &environment = requireEnvironment(impl_->environment);
    // The block has to be something the world can build: matter here is cubic
    // cells, so every side of it is a whole number of them. Said with the
    // nearest sizes that are, rather than refused bare.
    const double cell = impl_->request.cell_size_m;
    const double column = environment.terrain().grid().dx;
    const auto whole = [&](double length) {
        const double n = length / cell;
        return std::abs(n - std::round(n)) < 1.0e-6;
    };
    if (!whole(cells_x * column) || !whole(cells_z * column)) {
        int fits = 1;
        while (fits < 64 && !whole(fits * column)) ++fits;
        if (why) {
            char text[240];
            std::snprintf(text, sizeof text,
                          "a block is a whole number of %.3g m cells on every side, and the ground's "
                          "columns are %.3g m: cut %d columns at a time (%.3g m) each way",
                          cell, column, fits, fits * column);
            *why = text;
        }
        return std::nullopt;
    }
    const double cells_tall = std::max(1.0, std::round(height_m / cell));
    return environment.cut(*impl_->world, x, z, cells_x, cells_z, cells_tall * cell, why);
}

bool LiveWorld::setDischarge(const std::string &river, double discharge_m3_s) {
    return requireEnvironment(impl_->environment).setDischarge(river, discharge_m3_s);
}

std::string LiveWorld::environmentReport(bool full) const {
    if (!impl_->environment) return "{}";
    auto report=nlohmann::json::parse(impl_->environment->reportJson(full));
    auto &carried=report["ground"]["carried"];
    const double objects=impl_->carriedObjectsKg();
    const double total=objects+impl_->environment->carriedKg();
    carried["objects_kg"]=objects;carried["total_kg"]=total;
    if (std::isfinite(impl_->environment->carryLimitKg())) {
        carried["limit_kg"]=impl_->environment->carryLimitKg();
        carried["available_kg"]=std::max(0.0,impl_->environment->carryLimitKg()-total);
        carried["over_limit_kg"]=std::max(0.0,total-impl_->environment->carryLimitKg());
    }
    return report.dump();
}

std::string LiveWorld::environmentState() const {
    if (!impl_->environment) return "{}";
    return impl_->environment->stateJson();
}

std::string LiveWorld::survey(double x, double z) const {
    if (!impl_->environment) return R"({"on_the_ground":false})";
    return impl_->environment->surveyJson(x, z);
}

unsigned LiveWorld::awakeBodies() const { return impl_->world->awakeBodies(); }

// ===========================================================================
// Blades, and cutting that changes what things are.
//
// The declared model is docs/cutting-model.md, and this is that model and
// nothing more. An edge is engaged when its path takes it into a target's
// matter and the rules at the surface say it bites. While it is engaged, a
// friction constraint in the blade's own axes resists it with R = G + H w per
// metre of engaged edge. After the step the friction's work is read back, the
// kerf is advanced by exactly the area that work bought, and every bond -- and
// every rope link -- the kerf has reached is severed. A body whose severed
// bonds leave it in more than one piece is replaced by its pieces.
//
// Nothing here knows what anything is called. A rope is cut because it is a run
// of bodies tied by links and an edge went through it; a plank because it is
// cells and bonds; and neither because of its name.
// ===========================================================================

namespace {

constexpr double kPiBlade = 3.14159265358979323846;

// BANJO_CUT_TRACE=1 prints every engaged edge's step to stderr: what it was set
// up with and what it took. Observation only; it changes nothing computed.
[[nodiscard]] bool cutTrace() {
    static const bool on = std::getenv("BANJO_CUT_TRACE") != nullptr;
    return on;
}

[[nodiscard]] Quat quatProduct(const Quat &a, const Quat &b) {
    return Quat{a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
                a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
                a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
                a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w};
}

// How heavy a push at `arm` from the centre of mass feels, direction by
// direction: the grip's effective mass matrix. A force at a point both moves
// the body and turns it, so the point answers a force f with
// f / m + (I^-1 (arm x f)) x arm, and the mass it meets is the inverse of that
// map. Along the arm it is the body's whole mass; across it, less -- a sword
// held 0.35 m from its middle is 0.6 kg across the grip and 1.9 kg along it.
// docs/cutting-model.md section 7.
[[nodiscard]] Mat3 gripMassMatrix(double mass_kg, const Mat3 &inertia_world, const Vec3 &arm) {
    Mat3 whole;
    for (int i = 0; i < 3; ++i) whole.m[i][i] = mass_kg;
    if (!(mass_kg > 0.0)) return whole;
    const auto invert = [](const Mat3 &value, Mat3 &inverse) {
        const auto &a = value.m;
        const double c00 = a[1][1] * a[2][2] - a[1][2] * a[2][1];
        const double c01 = a[1][2] * a[2][0] - a[1][0] * a[2][2];
        const double c02 = a[1][0] * a[2][1] - a[1][1] * a[2][0];
        const double det = a[0][0] * c00 + a[0][1] * c01 + a[0][2] * c02;
        if (!(det > 0.0) || !std::isfinite(det)) return false;
        inverse.m[0][0] = c00 / det;
        inverse.m[0][1] = (a[0][2] * a[2][1] - a[0][1] * a[2][2]) / det;
        inverse.m[0][2] = (a[0][1] * a[1][2] - a[0][2] * a[1][1]) / det;
        inverse.m[1][0] = c01 / det;
        inverse.m[1][1] = (a[0][0] * a[2][2] - a[0][2] * a[2][0]) / det;
        inverse.m[1][2] = (a[0][2] * a[1][0] - a[0][0] * a[1][2]) / det;
        inverse.m[2][0] = c02 / det;
        inverse.m[2][1] = (a[0][1] * a[2][0] - a[0][0] * a[2][1]) / det;
        inverse.m[2][2] = (a[0][0] * a[1][1] - a[0][1] * a[1][0]) / det;
        return true;
    };
    Mat3 inverse_inertia;
    if (!invert(inertia_world, inverse_inertia)) return whole;
    // The grip's response to a unit force along each axis, as columns.
    Mat3 response;
    const Vec3 basis[3] = {Vec3{1.0, 0.0, 0.0}, Vec3{0.0, 1.0, 0.0}, Vec3{0.0, 0.0, 1.0}};
    for (int j = 0; j < 3; ++j) {
        const Vec3 column =
            (1.0 / mass_kg) * basis[j] + cross(inverse_inertia * cross(arm, basis[j]), arm);
        response.m[0][j] = column.x;
        response.m[1][j] = column.y;
        response.m[2][j] = column.z;
    }
    // Symmetric by construction; made exactly so before it is inverted.
    for (int i = 0; i < 3; ++i)
        for (int j = i + 1; j < 3; ++j) {
            const double mean = 0.5 * (response.m[i][j] + response.m[j][i]);
            response.m[i][j] = mean;
            response.m[j][i] = mean;
        }
    Mat3 mass;
    if (!invert(response, mass)) return whole;
    return mass;
}

// The turn that takes `from` to `to`, as its axis times its angle, the short
// way round.
[[nodiscard]] Vec3 turnBetween(const Quat &from, const Quat &to) {
    Quat d = quatProduct(to, conjugateOf(from));
    if (d.w < 0.0) d = Quat{-d.w, -d.x, -d.y, -d.z};
    const Vec3 axis{d.x, d.y, d.z};
    const double s = length(axis);
    if (!(s > 1e-12)) return {};
    return (2.0 * std::atan2(s, d.w) / s) * axis;
}

[[nodiscard]] Mat3 transposeOf(const Mat3 &m) {
    Mat3 t;
    for (int r = 0; r < 3; ++r)
        for (int c = 0; c < 3; ++c) t.m[r][c] = m.m[c][r];
    return t;
}

// The rotation nearest a matrix -- its orthogonal polar factor -- by Higham's
// iteration. Used only to follow a blade's frame into a body that has been
// rebuilt, which puts a body that came through a fracture whole back into the
// world in a new frame.
[[nodiscard]] Mat3 nearestRotation(Mat3 m) {
    for (int i = 0; i < 40; ++i) {
        const auto inverse = m.inverse(1e-30);
        if (!inverse) break;
        const Mat3 t = transposeOf(*inverse);
        for (int r = 0; r < 3; ++r)
            for (int c = 0; c < 3; ++c) m.m[r][c] = 0.5 * (m.m[r][c] + t.m[r][c]);
    }
    return m;
}

// A body's cells, looked up by where they are in its own frame. One body's
// cells sit on the grid of the lattice they were cut from, so rounding a point
// to the nearest centre finds the cell whose cube holds it.
struct CellGrid {
    Vec3 anchor{};
    double cell{1.0};
    std::unordered_map<std::int64_t, std::uint32_t> at;
    [[nodiscard]] static std::int64_t key(long long x, long long y, long long z) {
        constexpr long long kOffset = 1LL << 20;
        return ((x + kOffset) << 42) | ((y + kOffset) << 21) | (z + kOffset);
    }
    void place(const Vec3 &local, long long &x, long long &y, long long &z) const {
        x = std::llround((local.x - anchor.x) / cell);
        y = std::llround((local.y - anchor.y) / cell);
        z = std::llround((local.z - anchor.z) / cell);
    }
    [[nodiscard]] bool holds(const Vec3 &local) const {
        long long x = 0, y = 0, z = 0;
        place(local, x, y, z);
        return at.count(key(x, y, z)) != 0;
    }
    [[nodiscard]] Vec3 centre(long long x, long long y, long long z) const {
        return anchor + cell * Vec3{static_cast<double>(x), static_cast<double>(y),
                                    static_cast<double>(z)};
    }
};

[[nodiscard]] CellGrid gridOf(const std::vector<std::uint32_t> &nodes,
                              const std::vector<Vec3> &offsets, double cell) {
    CellGrid grid;
    grid.cell = cell;
    if (nodes.empty()) return grid;
    grid.anchor = offsets[nodes.front()];
    grid.at.reserve(nodes.size() * 2);
    for (const std::uint32_t node : nodes) {
        long long x = 0, y = 0, z = 0;
        grid.place(offsets[node], x, y, z);
        grid.at.emplace(CellGrid::key(x, y, z), node);
    }
    return grid;
}

// Whether a point in a body's frame has already been cut through, by any of the
// kerfs the body carries: inside a kerf's slab, and inside what it has swept.
template <class Kerfs>
[[nodiscard]] bool alreadyCut(const Kerfs *kerfs, const Vec3 &local) {
    if (kerfs == nullptr) return false;
    for (const auto &kerf : *kerfs) {
        const Vec3 d = local - kerf.origin;
        if (std::abs(dot(d, kerf.w)) > kerf.half_width) continue;
        if (kerf.covers(dot(d, kerf.u), dot(d, kerf.v), 1e-9)) return true;
    }
    return false;
}

// Every bond among these cells that crosses the kerf's plane, and where.
template <class KerfT>
void findCrossings(KerfT &kerf, const std::vector<std::uint32_t> &nodes,
                   const std::vector<Vec3> &offsets, const LatticeAsset &asset) {
    kerf.crossings.clear();
    const std::unordered_set<std::uint32_t> inside(nodes.begin(), nodes.end());
    for (const std::uint32_t node : nodes) {
        if (node + 1U >= asset.adjacency_offsets.size()) continue;
        for (std::uint32_t k = asset.adjacency_offsets[node]; k < asset.adjacency_offsets[node + 1U];
             ++k) {
            const std::uint32_t o = asset.adjacent_bond_indices[k];
            const BondRest &bond = asset.bonds[o];
            const std::uint32_t other = bond.node_a == node ? bond.node_b : bond.node_a;
            // Each bond once, from its lower end, and only if both ends are here.
            if (other < node || inside.count(other) == 0) continue;
            const Vec3 &pa = offsets[node];
            const Vec3 &pb = offsets[other];
            const double sa = dot(pa - kerf.origin, kerf.w);
            const double sb = dot(pb - kerf.origin, kerf.w);
            if ((sa >= 0.0) == (sb >= 0.0)) continue;
            const Vec3 x = pa + (sa / (sa - sb)) * (pb - pa);
            kerf.crossings.push_back({o, dot(x - kerf.origin, kerf.u), dot(x - kerf.origin, kerf.v), x});
        }
    }
}

// Whether a body's cells are still one piece through the bonds left alive.
[[nodiscard]] bool stillWhole(const std::vector<std::uint32_t> &nodes, const ActiveMatter &matter) {
    if (nodes.size() <= 1 || matter.asset == nullptr) return true;
    const LatticeAsset &asset = *matter.asset;
    const std::unordered_set<std::uint32_t> inside(nodes.begin(), nodes.end());
    std::unordered_set<std::uint32_t> seen{nodes.front()};
    std::vector<std::uint32_t> stack{nodes.front()};
    while (!stack.empty()) {
        const std::uint32_t node = stack.back();
        stack.pop_back();
        if (node + 1U >= asset.adjacency_offsets.size()) continue;
        for (std::uint32_t k = asset.adjacency_offsets[node]; k < asset.adjacency_offsets[node + 1U];
             ++k) {
            const std::uint32_t o = asset.adjacent_bond_indices[k];
            if (o >= matter.bonds.size() || !matter.bonds[o].alive) continue;
            const BondRest &bond = asset.bonds[o];
            const std::uint32_t other = bond.node_a == node ? bond.node_b : bond.node_a;
            if (inside.count(other) == 0) continue;
            if (seen.insert(other).second) stack.push_back(other);
        }
    }
    return seen.size() == nodes.size();
}

// Which face of a cell a path crossed going in, as that face's outward normal in
// the body's frame. `outside` is the last point of the path not in matter and
// `inside` the first one that is.
[[nodiscard]] Vec3 faceCrossed(const CellGrid &grid, const Vec3 &outside, const Vec3 &inside) {
    long long x = 0, y = 0, z = 0;
    grid.place(inside, x, y, z);
    const Vec3 off = outside - grid.centre(x, y, z);
    const double ax = std::abs(off.x), ay = std::abs(off.y), az = std::abs(off.z);
    if (ax >= ay && ax >= az) return {off.x >= 0.0 ? 1.0 : -1.0, 0.0, 0.0};
    if (ay >= az) return {0.0, off.y >= 0.0 ? 1.0 : -1.0, 0.0};
    return {0.0, 0.0, off.z >= 0.0 ? 1.0 : -1.0};
}

} // namespace

unsigned LiveWorld::blade(const std::string &body, const Vec3 &heel_world_m,
                          const Vec3 &tip_world_m, const Vec3 &facing_world,
                          double thickness_m, double edge_radius_m, double bevel_deg,
                          const Vec3 &grip_world_m) {
    impl_->requireLatticeRoom("blade");
    Impl &I = *impl_;
    // Every refusal says which rule it broke: a caller told only "no" -- a
    // model, say -- tries something else at random.
    I.blade_refusal.clear();
    const auto refuse = [&I](const char *why) {
        I.blade_refusal = why;
        return 0u;
    };
    const auto found = I.index_of.find(body);
    if (found == I.index_of.end()) return refuse("there is nothing called that in the scene");
    const auto finite = [](const Vec3 &v) {
        return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
    };
    if (!finite(heel_world_m) || !finite(tip_world_m) || !finite(facing_world) ||
        !finite(grip_world_m))
        return refuse("a point or the facing is not a finite number");
    if (!(thickness_m > 0.0) || !(thickness_m < 1.0))
        return refuse("the thickness must be more than 0 and less than 1 m");
    if (!(edge_radius_m > 0.0) || !(edge_radius_m < 0.05))
        return refuse("the edge radius must be more than 0 and less than 50 mm");
    if (!(bevel_deg > 0.0) || !(bevel_deg < 180.0))
        return refuse("the bevel must be more than 0 and less than 180 degrees");
    const double reach = length(tip_world_m - heel_world_m);
    if (!(reach > 1e-4)) return refuse("the heel and the tip are the same point");
    const Vec3 t = (1.0 / reach) * (tip_world_m - heel_world_m);
    // Squared up against the edge, so "roughly this way" is enough.
    const Vec3 squared = facing_world - dot(facing_world, t) * t;
    if (!(length(squared) > 1e-6))
        return refuse("the facing runs along the edge; it has to point across it");
    const Vec3 n = normalized(squared);

    const std::size_t which = found->second;
    const MatterBodyId id = I.body_of[which];
    if (!I.world->contains(id)) return refuse("it is not in the world");
    const RigidSnapshot at = I.world->snapshot(id);
    const Quat inverse = conjugateOf(at.orientation_world);
    Impl::Blade made{};
    made.body = body;
    made.heel_local = inverse.rotate(heel_world_m - at.center_of_mass_world_m);
    made.tip_local = inverse.rotate(tip_world_m - at.center_of_mass_world_m);
    made.facing_local = inverse.rotate(n);
    made.grip_local = inverse.rotate(grip_world_m - at.center_of_mass_world_m);
    made.thickness = thickness_m;
    made.edge_radius = edge_radius_m;
    made.bevel_deg = bevel_deg;

    // The edge has to be ON the body. An edge floating beside it would cut what
    // the body itself never reaches.
    const double cell = I.request.cell_size_m;
    const CellGrid grid = gridOf(I.nodes_of[which], I.cell_offset_m, cell);
    const Vec3 inward = -0.25 * cell * made.facing_local;
    const auto onBody = [&](const Vec3 &local) {
        // A point on a face, an edge or a corner of the body's cells is on the
        // body, and exactly there a cell lookup rounds either way: try it a
        // hair inside in every direction, and a quarter cell in behind the
        // edge. (An edge declared corner to corner of a plate was refused.)
        const double hair = 1e-4 * cell;
        for (int corner = 0; corner < 8; ++corner) {
            const Vec3 nudge{(corner & 1) != 0 ? hair : -hair, (corner & 2) != 0 ? hair : -hair,
                             (corner & 4) != 0 ? hair : -hair};
            if (grid.holds(local + nudge) || grid.holds(local + inward + nudge)) return true;
        }
        return false;
    };
    if (!onBody(made.heel_local) || !onBody(made.tip_local))
        return refuse("the edge does not lie on its matter: the heel and the tip have to be on "
                      "the body's surface");
    // And it faces OUT of the body. An edge on a bar's far face declared as
    // facing back into the bar leads with the bar's OTHER face: a model built
    // a sword that way, and swung edge first it glanced off the rope it was
    // meant to cut. Out along the facing from an edge on a face there is no
    // matter of the body's own, and in behind it there is.
    const Vec3 across = 0.25 * cell * made.facing_local;
    const auto facesIn = [&](const Vec3 &local) {
        return grid.holds(local + across) && !grid.holds(local - across);
    };
    if (facesIn(made.heel_local) || facesIn(0.5 * (made.heel_local + made.tip_local)) ||
        facesIn(made.tip_local))
        return refuse("the edge faces into it: the facing has to point out of the face the "
                      "edge is on, away from the body's matter");

    made.body_id = id;
    made.frame_nodes = I.nodes_of[which];
    made.frame_offsets.reserve(made.frame_nodes.size());
    for (const std::uint32_t node : made.frame_nodes) made.frame_offsets.push_back(I.cell_offset_m[node]);
    made.id = I.next_blade++;
    I.blades.push_back(std::move(made));
    return I.blades.back().id;
}

const std::string &LiveWorld::bladeRefusal() const { return impl_->blade_refusal; }

std::vector<LiveBlade> LiveWorld::blades() const {
    const Impl &I = *impl_;
    std::vector<LiveBlade> out;
    out.reserve(I.blades.size());
    for (const Impl::Blade &blade : I.blades) {
        LiveBlade said{};
        said.id = blade.id;
        said.body = blade.body;
        const auto found = I.index_of.find(blade.body);
        // Kept in its body's rigid frame; said in the frame poses() says the
        // body faces in, because a host draws the edge on the box it draws.
        const Quat back =
            conjugateOf(found != I.index_of.end() ? I.shapeTurn(found->second) : Quat{});
        said.heel_local_m = back.rotate(blade.heel_local);
        said.tip_local_m = back.rotate(blade.tip_local);
        said.facing_local = back.rotate(blade.facing_local);
        said.grip_local_m = back.rotate(blade.grip_local);
        said.thickness_m = blade.thickness;
        said.edge_radius_m = blade.edge_radius;
        said.bevel_deg = blade.bevel_deg;
        said.cut_area_m2 = blade.cut_area;
        said.cut_work_j = blade.cut_work;
        said.cutting = blade.cutting;
        // Not while the body carrying it is set aside (park): the edge is out
        // of the world with it, and comes back with it.
        said.attached = blade.attached && found != I.index_of.end() && !I.isParked(found->second);
        if (said.attached && I.world->contains(I.body_of[found->second])) {
            const RigidSnapshot at = I.world->snapshot(I.body_of[found->second]);
            said.material = I.described[found->second].material;
            said.heel_m = at.center_of_mass_world_m + at.orientation_world.rotate(blade.heel_local);
            said.tip_m = at.center_of_mass_world_m + at.orientation_world.rotate(blade.tip_local);
            said.grip_m = at.center_of_mass_world_m + at.orientation_world.rotate(blade.grip_local);
            said.facing = at.orientation_world.rotate(blade.facing_local);
            said.flat = cross(normalized(said.tip_m - said.heel_m), said.facing);
        }
        out.push_back(std::move(said));
    }
    return out;
}

std::vector<LiveCut> LiveWorld::cuts() const { return impl_->cut_log; }

void LiveWorld::forgetCuts() {
    Impl &I = *impl_;
    // Closed contacts go; open ones are still happening and stay, with every
    // index that points at them moved to where they now are.
    std::vector<std::size_t> moved(I.cut_log.size(), static_cast<std::size_t>(-1));
    std::vector<LiveCut> kept;
    for (std::size_t i = 0; i < I.cut_log.size(); ++i) {
        if (!I.cut_log[i].open) continue;
        moved[i] = kept.size();
        kept.push_back(I.cut_log[i]);
    }
    I.cut_log = std::move(kept);
    for (Impl::Engagement &e : I.engaged)
        e.cut = e.cut < moved.size() ? moved[e.cut] : static_cast<std::size_t>(-1);
    for (auto it = I.touching.begin(); it != I.touching.end();) {
        const std::size_t was = it->second.first;
        if (was < moved.size() && moved[was] != static_cast<std::size_t>(-1)) {
            it->second.first = moved[was];
            ++it;
        } else {
            it = I.touching.erase(it);
        }
    }
}

bool LiveWorld::wield(const std::string &name, const Vec3 &grip_world_m) {
    if (!std::isfinite(grip_world_m.x) || !std::isfinite(grip_world_m.y) ||
        !std::isfinite(grip_world_m.z))
        return false;
    if (!grab(name)) return false;
    Impl &I = *impl_;
    const RigidSnapshot now = I.world->snapshot(I.body_of[I.holding]);
    I.wielding = true;
    I.grip_local = conjugateOf(now.orientation_world)
                       .rotate(grip_world_m - now.center_of_mass_world_m);
    // The hand starts exactly where the grip is and facing the way the body
    // faces, so taking hold of something does not itself shove it.
    I.held_at = grip_world_m;
    I.held_facing = now.orientation_world;
    I.hand_force = {};
    return true;
}

void LiveWorld::aimHeld(const Quat &orientation_world) {
    const double size = std::sqrt(orientation_world.w * orientation_world.w +
                                  orientation_world.x * orientation_world.x +
                                  orientation_world.y * orientation_world.y +
                                  orientation_world.z * orientation_world.z);
    if (!(size > 1e-9) || !std::isfinite(size)) return;
    // Asked of the body as poses() says it faces. The hand turns its rigid
    // frame, so the turn its shape carries (shapeTurn) comes off first:
    // otherwise taking hold of a thing built turned and asking it to stay as it
    // is would swing it round by its whole turn.
    impl_->held_facing = compose(Quat{orientation_world.w / size, orientation_world.x / size,
                                      orientation_world.y / size, orientation_world.z / size},
                                 conjugateOf(impl_->shapeTurn(impl_->holding)));
}

bool LiveWorld::wielding() const {
    return impl_->wielding && impl_->holding != static_cast<std::size_t>(-1);
}

void LiveWorld::setHandTorque(double newton_metres) {
    impl_->hand_torque_n_m = std::isfinite(newton_metres) ? std::max(0.0, newton_metres) : 0.0;
}

double LiveWorld::handTorque() const { return impl_->hand_torque_n_m; }

void LiveWorld::setHandMass(double kilograms) {
    impl_->hand_mass_kg = std::isfinite(kilograms) ? std::max(0.0, kilograms) : 0.0;
}

double LiveWorld::handMass() const { return impl_->hand_mass_kg; }

// ---- the hand's own motions -------------------------------------------------
//
// docs/interaction-profiles.md. Two things people do with their hands cannot be
// done a frame at a time from outside: a throw is over in a tenth of a second,
// and a draw is decided by how hard a hand can pull against what resists it. So
// the engine makes the stroke itself, at the step's rate, with the same bounded
// hand every other hold has -- and counts the work the hand does.

namespace {

[[nodiscard]] GripPull gripPull(const RigidMechanicalState &held, const Vec3 &grip_local,
                                const Vec3 &wanted_at, const Vec3 &wanted_velocity,
                                const Quat &wanted_facing, double strength_n,
                                double torque_n_m, const Vec3 &gravity) {
    const RigidSnapshot &now = held.motion;
    const Vec3 arm = now.orientation_world.rotate(grip_local);
    const Vec3 grip = now.center_of_mass_world_m + arm;
    const Vec3 grip_velocity = now.linear_velocity_m_s + cross(now.angular_velocity_rad_s, arm);
    // A hand that answers in every direction at the same rate, each
    // direction with the mass the GRIP has there. A push at the grip turns
    // the body as well as moving it, so across the arm the grip is lighter
    // than the body -- 0.6 kg of a 1.9 kg sword held 0.35 m from its
    // middle. Sized for the whole mass instead, the damping came to 2.2 of
    // a step's worth across the arm, past the 2 an explicit step can take,
    // and the sword rang at the step rate: a blade in a kerf turns that into
    // cutting nobody pushed it to do. The rate is 100 rad/s, a tenth of a
    // step per radian, unless full strength would then come sooner than
    // 50 mm off along the arm, where the grip has the whole mass.
    constexpr double kFastest = 100.0;
    constexpr double kDamping = 0.9;
    const double rate = std::min(kFastest, std::sqrt(strength_n / (0.05 * held.mass_kg)));
    const Mat3 feels = gripMassMatrix(held.mass_kg, held.inertia_world_kg_m2, arm);
    // Its weight is carried first: a hand holding a sword out does not let
    // it sag until the error pays for it, and does not stop carrying it
    // because it is also swinging it. What the hand has left after the
    // weight goes to moving it. (Capped as one vector, a hard swing spent
    // the weight's share on the swing, and the sword dropped 100 mm and
    // passed under the rope it had been aimed at.)
    //
    // The damping is against the grip's speed RELATIVE to how fast the hand
    // wants it to go: nothing, when it is held still -- the hand as it always
    // was -- and the stroke's own speed along its path during a stroke.
    // Against the absolute speed, a stroke is a hand trying to stop the thing
    // it is throwing.
    const Vec3 hold = -held.mass_kg * gravity;
    Vec3 track = feels * ((rate * rate) * (wanted_at - grip) +
                          (2.0 * kDamping * rate) * (wanted_velocity - grip_velocity));
    const double spare = std::max(0.0, strength_n - length(hold));
    const double pull = length(track);
    if (pull > spare && pull > 0.0) track = (spare / pull) * track;
    Vec3 force = hold + track;
    // And never more than the hand has: a thing too heavy to hold up is
    // held up as far as the strength goes.
    const double total = length(force);
    if (total > strength_n && total > 0.0) force = (strength_n / total) * force;
    // The wrist turns it towards where the hand wants it facing, and has to
    // answer the turn the grip force itself puts about the centre of mass:
    // what the wrist supplies is what is left after the grip's own moment.
    const Vec3 turn = turnBetween(now.orientation_world, wanted_facing);
    const Vec3 wanted = (kFastest * kFastest) * turn -
                        (2.0 * kDamping * kFastest) * now.angular_velocity_rad_s;
    Vec3 torque = held.inertia_world_kg_m2 * wanted - cross(arm, force);
    const double twist = length(torque);
    if (twist > torque_n_m && twist > 0.0) torque = (torque_n_m / twist) * torque;
    return {force, torque, grip};
}

// An orientation after turning at `spin` for `dt_s`, integrated the way a
// solver does it -- by the spin's quaternion rate -- and renormalised.
[[nodiscard]] Quat turnedBy(const Quat &q, const Vec3 &spin, double dt_s) {
    const Quat rate = quatProduct(Quat{0.0, spin.x, spin.y, spin.z}, q);
    const Quat out{q.w + 0.5 * dt_s * rate.w, q.x + 0.5 * dt_s * rate.x,
                   q.y + 0.5 * dt_s * rate.y, q.z + 0.5 * dt_s * rate.z};
    const double size = std::sqrt(out.w * out.w + out.x * out.x + out.y * out.y + out.z * out.z);
    return size > 0.0 ? Quat{out.w / size, out.x / size, out.y / size, out.z / size} : q;
}

} // namespace

std::pair<Vec3, Vec3> LiveWorld::gripNow() const {
    const Impl &I = *impl_;
    if (I.holding == static_cast<std::size_t>(-1)) return {};
    const MatterBodyId id = I.body_of[I.holding];
    if (!I.world->contains(id)) return {};
    const RigidSnapshot now = I.world->snapshot(id);
    if (!I.wielding) return {now.center_of_mass_world_m, now.linear_velocity_m_s};
    const Vec3 arm = now.orientation_world.rotate(I.grip_local);
    return {now.center_of_mass_world_m + arm,
            now.linear_velocity_m_s + cross(now.angular_velocity_rad_s, arm)};
}

bool LiveWorld::hauling() const {
    const Impl &I = *impl_;
    if (I.holding == static_cast<std::size_t>(-1) || I.wielding) return false;
    const std::string &name = I.described[I.holding].name;
    // The same test carryOrHaul makes: any joint still in place on it.
    for (const Impl::SceneJoint &joint : I.joints)
        if (joint.attached && joint.rigid != 0 && (joint.a == name || joint.b == name)) return true;
    return false;
}

bool LiveWorld::stroke(const LiveStroke &asked, std::string &why) {
    Impl &I = *impl_;
    if (I.holding == static_cast<std::size_t>(-1)) {
        why = "the hand is empty";
        return false;
    }
    if (!I.wielding && !hauling()) {
        why = "a carried thing goes exactly where it is put and is never pushed, so no stroke "
              "can move it with a force: take hold of it by a grip (wield) to throw it";
        return false;
    }
    if (std::string problem = strokeProblem(asked); !problem.empty()) {
        why = std::move(problem);
        return false;
    }
    Impl::Stroke made;
    made.asked = asked;
    made.at_m = arcLengths(asked.path_m);
    made.length_m = made.at_m.back();
    const auto [grip, velocity] = gripNow();
    made.grip_along_m = alongNearest(asked.path_m, made.at_m, grip);
    made.target_along_m = made.grip_along_m;
    // Already moving along the path, the hand is moving with it; against it,
    // it starts from rest.
    made.target_speed_m_s =
        std::clamp(dot(velocity, pathDirection(asked.path_m, made.at_m, made.grip_along_m)),
                   0.0, asked.speed_m_s);
    made.began_s = I.time_s;
    I.stroke = std::move(made);
    I.stroke_ended.clear();
    why.clear();
    return true;
}

void LiveWorld::cancelStroke() {
    if (!impl_->stroke) return;
    impl_->stroke.reset();
    impl_->stroke_ended = "cancelled";
    impl_->held_velocity = {};
}

LiveHand LiveWorld::hand() const {
    const Impl &I = *impl_;
    LiveHand out;
    out.work_j = I.hand_work_j;
    out.stroke_ended = I.stroke_ended;
    out.let_go_body = I.let_go_body;
    out.let_go_velocity_m_s = I.let_go_velocity;
    out.let_go_at_s = I.let_go_at_s;
    out.let_go_work_j = I.let_go_work_j;
    if (I.holding == static_cast<std::size_t>(-1)) return out;
    out.holding = I.described[I.holding].name;
    out.mode = I.wielding ? "grip" : hauling() ? "haul" : "carry";
    out.target_m = I.held_at;
    const auto [grip, velocity] = gripNow();
    out.grip_m = grip;
    out.grip_velocity_m_s = velocity;
    out.force_n = I.hand_applied_n;
    if (I.stroke) {
        out.stroking = true;
        out.stroke_along_m = I.stroke->grip_along_m;
        out.stroke_length_m = I.stroke->length_m;
    }
    return out;
}

void LiveWorld::beginHandStep(double dt_s) {
    Impl &I = *impl_;
    I.hand_step = Impl::HandStep{};
    // The haul pulls this step acts with -- pushed after the last step, and
    // whenever the hand moved since. Anything pushed from here on is for the
    // step after this one.
    I.hand_step.haul_in = I.haul_pushed;
    I.haul_pushed = {};
    if (I.holding == static_cast<std::size_t>(-1)) return;
    const MatterBodyId id = I.body_of[I.holding];
    if (!I.world->contains(id)) return;
    const auto [grip, velocity] = gripNow();
    I.hand_step.measuring = true;
    I.hand_step.name = I.described[I.holding].name;
    I.hand_step.grip_velocity_from = velocity;
    I.hand_step.spin_from = I.world->snapshot(id).angular_velocity_rad_s;
    if (!I.stroke) return;
    const Impl::Stroke &s = *I.stroke;
    // Wielded, the hand holds the whole weight up. Hauled, the thing hangs on
    // its joint, which holds up all of its weight but what lies along the way
    // the hand is taking it: a gate is pushed round its upright pins with none
    // of it, a grate up its grooves with all of it. Counting the whole of it, a
    // 110 kg oak gate -- more than the hand can lift -- left the hand nothing to
    // move it with, and a stroke round its pins never began.
    Vec3 bearing = I.request.gravity_m_s2;
    if (!I.wielding) {
        const Vec3 way = pathDirection(s.asked.path_m, s.at_m, s.target_along_m);
        bearing = dot(bearing, way) * way;
    }
    const double most = handAcceleration(I.hand_strength_n, I.hand_mass_kg,
                                         I.world->mechanicalState(id).mass_kg, bearing);
    const StrokeHand next = advanceStrokeHand(s.asked, s.length_m, s.target_along_m,
                                              s.target_speed_m_s,
                                              alongNearest(s.asked.path_m, s.at_m, grip), most,
                                              dt_s);
    I.hand_step.target_along_m = next.along;
    I.hand_step.target_speed_m_s = next.speed;
    I.held_at = pointAlong(s.asked.path_m, s.at_m, next.along);
    I.held_velocity = next.speed * pathDirection(s.asked.path_m, s.at_m, next.along);
    // A stroke that turns as it goes -- a swing -- turns the wrist's wish with
    // the hand; the wrist turns the thing towards it with what it has.
    if (!s.asked.facings_wxyz.empty())
        I.held_facing = facingAlong(s.asked.facings_wxyz, s.at_m, next.along);
}

void LiveWorld::abandonHandStep() {
    Impl &I = *impl_;
    // The world is back as it was when the step began, and the pulls it began
    // with are back in the accumulator; whatever the trial pushed is gone.
    I.haul_pushed = I.hand_step.haul_in;
    I.hand_step = Impl::HandStep{};
}

void LiveWorld::endHandStep(const Vec3 &grip_force_n, const Vec3 &grip_torque_n_m, double dt_s) {
    Impl &I = *impl_;
    const Impl::HandStep was = I.hand_step;
    I.hand_step = Impl::HandStep{};
    if (!was.measuring || I.holding == static_cast<std::size_t>(-1) ||
        I.described[I.holding].name != was.name)
        return;
    const MatterBodyId id = I.body_of[I.holding];
    if (!I.world->contains(id)) return;
    const auto [grip, velocity] = gripNow();
    const Vec3 spin = I.world->snapshot(id).angular_velocity_rad_s;
    // What the hand did in this step: its pull -- at the grip, or at the centre
    // of what it hauls -- over the grip's motion, and its wrist over the turn.
    // A carry is placement: no force, and so no work.
    const Vec3 force = grip_force_n + was.haul_in;
    I.hand_applied_n = force;
    I.hand_work_j += dot(force, (0.5 * dt_s) * (was.grip_velocity_from + velocity)) +
                     dot(grip_torque_n_m, (0.5 * dt_s) * (was.spin_from + spin));
    if (!I.stroke) return;
    Impl::Stroke &s = *I.stroke;
    s.target_along_m = was.target_along_m;
    s.target_speed_m_s = was.target_speed_m_s;
    s.grip_along_m = alongNearest(s.asked.path_m, s.at_m, grip);
    s.recent.emplace_back(I.time_s, s.grip_along_m);
    while (s.recent.size() > 2 && s.recent.front().first < I.time_s - 0.25) s.recent.pop_front();
    const auto finish = [&I](const char *how) {
        I.stroke.reset();
        I.stroke_ended = how;
        I.held_velocity = {};
    };
    if (s.asked.let_go_at_end && s.grip_along_m >= s.length_m - 0.005) {
        // The release of a throw: the moment the GRIP gets to the end.
        I.let_go_body = was.name;
        I.let_go_velocity = I.world->snapshot(id).linear_velocity_m_s;
        I.let_go_at_s = I.time_s;
        I.let_go_work_j = I.hand_work_j;
        finish("let go");
        release();
        return;
    }
    if (!s.asked.let_go_at_end && s.target_along_m >= s.length_m - 1e-9) {
        finish("reached");
        return;
    }
    // Blocked: for a fifth of a second the grip has gone nowhere while the hand
    // is as far ahead of it as it may be -- pulling with everything it has. As
    // far as this hand can take it, which for a bow is the draw.
    const double elapsed = I.time_s - s.began_s;
    const bool at_lead = s.target_along_m >= s.grip_along_m + s.asked.lead_m - 1e-4;
    if (elapsed >= 0.25 && at_lead && s.recent.back().first - s.recent.front().first >= 0.2 &&
        std::abs(s.recent.back().second - s.recent.front().second) < 0.003) {
        finish("blocked");
        return;
    }
    if (elapsed >= s.asked.give_up_s) finish("gave up");
}

LiveFlight LiveWorld::previewFlight(const Vec3 &from_world_m, const Vec3 &velocity_m_s,
                                    double horizon_s, const std::string &ignoring) const {
    const Impl &I = *impl_;
    LiveFlight out;
    const auto usable = [](const Vec3 &v) {
        return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
    };
    if (!usable(from_world_m) || !usable(velocity_m_s) || !std::isfinite(horizon_s)) return out;
    const double horizon = std::clamp(horizon_s, 0.0, 10.0);
    // The thing that is flying is still where it starts, in the hand, and a ray
    // from inside it meets it first. It is stepped over by as much as it could
    // possibly be across.
    bool skipping = false;
    MatterBodyId skip{};
    double across = 0.0;
    if (const auto found = I.index_of.find(ignoring);
        !ignoring.empty() && found != I.index_of.end() && I.inWorld(found->second)) {
        skipping = true;
        skip = I.body_of[found->second];
        const Vec3 d = I.described[found->second].dimensions_m;
        across = std::sqrt(d.x * d.x + d.y * d.y + d.z * d.z) + 0.002;
    }
    const Vec3 g = I.request.gravity_m_s2;
    // Stepped the way the solver steps a free body, at the rate this world is
    // being stepped: gravity, then the body's own damping, then the move.
    // Exact ballistics came down 84 mm beyond a real throw over 11.5 m. The
    // solver's step and the 0.02 a second of damping every live body carries
    // are both part of how things fly here, and a preview that leaves them out
    // is a preview of some other world.
    const double dt = I.last_dt_s > 0.0 ? I.last_dt_s : 1.0 / 240.0;
    const double damping = skipping ? I.world->linearDamping(skip) : 0.0;
    const int per_point = std::max(1, static_cast<int>(std::lround((1.0 / 60.0) / dt)));
    const int steps = static_cast<int>(std::ceil(horizon / dt));
    Vec3 p = from_world_m, v = velocity_m_s;
    out.points_m.push_back(p);
    for (int done = 0; done < steps && out.points_m.size() < 601;) {
        const Vec3 start = p, v_start = v;
        const int here = std::min(per_point, steps - done);
        for (int k = 0; k < here; ++k) {
            v = std::max(0.0, 1.0 - damping * dt) * (v + dt * g);
            p = p + dt * v;
        }
        const Vec3 span = p - start;
        const double reach = length(span);
        if (reach > 1e-12) {
            const Vec3 dir = (1.0 / reach) * span;
            Vec3 origin = start;
            double gone = 0.0;
            RayHit hit{};
            for (int tries = 0; tries < 4 && gone < reach; ++tries) {
                hit = I.world->castRay(origin, dir, reach - gone);
                if (!hit.hit || !skipping || !hit.named || !(hit.body_id == skip)) break;
                const double past = std::min(reach - gone, hit.distance_m + across);
                origin = origin + past * dir;
                gone += past;
                hit = RayHit{};
            }
            if (hit.hit) {
                const double fraction = std::clamp((gone + hit.distance_m) / reach, 0.0, 1.0);
                out.hit = true;
                out.hit_point_m = hit.point_world_m;
                out.hit_after_s = (done + fraction * here) * dt;
                out.hit_speed_m_s = length(v_start + fraction * (v - v_start));
                if (hit.named)
                    for (std::size_t i = 0; i < I.body_of.size(); ++i)
                        if (I.body_of[i] == hit.body_id) {
                            out.hit_name = I.described[i].name;
                            break;
                        }
                out.points_m.push_back(hit.point_world_m);
                return out;
            }
        }
        done += here;
        out.points_m.push_back(p);
    }
    return out;
}

LiveStrokePreview LiveWorld::previewStroke(const LiveStroke &asked, double dt_s,
                                           double horizon_s) const {
    const Impl &I = *impl_;
    LiveStrokePreview out;
    if (I.holding == static_cast<std::size_t>(-1)) {
        out.why = "the hand is empty";
        return out;
    }
    if (!I.wielding) {
        out.why = hauling() ? "it is attached to other things, and where it goes depends on them"
                            : "a carried thing is placed, not pushed: take hold of it by a grip "
                              "(wield) to throw it";
        return out;
    }
    if (std::string problem = strokeProblem(asked); !problem.empty()) {
        out.why = std::move(problem);
        return out;
    }
    const MatterBodyId id = I.body_of[I.holding];
    if (!I.world->contains(id)) {
        out.why = "what the hand holds is not in the world";
        return out;
    }
    RigidMechanicalState body = I.world->mechanicalState(id);
    if (!(body.mass_kg > 0.0)) {
        out.why = "it has no mass to move";
        return out;
    }
    if (!(dt_s > 0.0 && dt_s <= 0.02)) dt_s = 1.0 / 240.0;
    // The body alone, with its own mass and inertia, this hand and gravity --
    // stepped the way the solver steps a free body: velocity, then position.
    const Mat3 inertia_local = rotateInertia(body.inertia_world_kg_m2,
                                             conjugateOf(body.motion.orientation_world));
    const std::vector<double> at = arcLengths(asked.path_m);
    const double length_m = at.back();
    const Vec3 g = I.request.gravity_m_s2;
    const double most = handAcceleration(I.hand_strength_n, I.hand_mass_kg, body.mass_kg, g);
    // The damping the solver applies to it every step, after the forces.
    const double keep_speed = std::max(0.0, 1.0 - I.world->linearDamping(id) * dt_s);
    const double keep_spin = std::max(0.0, 1.0 - I.world->angularDamping(id) * dt_s);
    RigidSnapshot &now = body.motion;
    const auto gripOf = [&]() {
        const Vec3 arm = now.orientation_world.rotate(I.grip_local);
        return std::pair<Vec3, Vec3>{now.center_of_mass_world_m + arm,
                                     now.linear_velocity_m_s +
                                         cross(now.angular_velocity_rad_s, arm)};
    };
    Vec3 grip{}, grip_velocity{};
    std::tie(grip, grip_velocity) = gripOf();
    double along = alongNearest(asked.path_m, at, grip);
    double speed = std::clamp(dot(grip_velocity, pathDirection(asked.path_m, at, along)), 0.0,
                              asked.speed_m_s);
    double t = 0.0;
    while (t < asked.give_up_s) {
        std::tie(grip, grip_velocity) = gripOf();
        const double grip_along = alongNearest(asked.path_m, at, grip);
        if (grip_along >= length_m - 0.005) {
            out.reaches_end = true;
            break;
        }
        const StrokeHand next =
            advanceStrokeHand(asked, length_m, along, speed, grip_along, most, dt_s);
        along = next.along;
        speed = next.speed;
        body.inertia_world_kg_m2 = rotateInertia(inertia_local, now.orientation_world);
        const GripPull pull = gripPull(body, I.grip_local, pointAlong(asked.path_m, at, along),
                                       speed * pathDirection(asked.path_m, at, along),
                                       I.held_facing, I.hand_strength_n, I.hand_torque_n_m, g);
        const Vec3 spin_before = now.angular_velocity_rad_s;
        const Vec3 arm = pull.grip - now.center_of_mass_world_m;
        now.linear_velocity_m_s =
            keep_speed * (now.linear_velocity_m_s + dt_s * ((1.0 / body.mass_kg) * pull.force + g));
        if (const auto inverse = body.inertia_world_kg_m2.inverse(1e-18))
            now.angular_velocity_rad_s =
                keep_spin * (now.angular_velocity_rad_s +
                             dt_s * ((*inverse) * (pull.torque + cross(arm, pull.force))));
        now.center_of_mass_world_m = now.center_of_mass_world_m + dt_s * now.linear_velocity_m_s;
        now.orientation_world = turnedBy(now.orientation_world, now.angular_velocity_rad_s, dt_s);
        const Vec3 velocity_after = gripOf().second;
        out.work_j += dot(pull.force, (0.5 * dt_s) * (grip_velocity + velocity_after)) +
                      dot(pull.torque, (0.5 * dt_s) * (spin_before + now.angular_velocity_rad_s));
        t += dt_s;
    }
    out.possible = true;
    out.stroke_s = t;
    out.let_go_at_m = now.center_of_mass_world_m;
    out.let_go_velocity_m_s = now.linear_velocity_m_s;
    if (!out.reaches_end) {
        out.why = "the hand would give up before the grip got to the end: it cannot move this "
                  "that far in time";
        return out;
    }
    out.flight = previewFlight(now.center_of_mass_world_m, now.linear_velocity_m_s, horizon_s,
                               I.described[I.holding].name);
    return out;
}

void LiveWorld::prepareCuts(double dt_s) {
    Impl &I = *impl_;
    if (I.blades.empty()) return;

    const TileImpactSetup &setup = *I.setup;
    const double cell = I.request.cell_size_m;
    const Vec3 gravity = I.request.gravity_m_s2;
    constexpr double kPress = 0.25;                     // m/s: slower than this is a press
    constexpr double kCreep = 0.02;                     // m/s: slower than this is at rest
    constexpr double kShallow = 0.25881904510252074;    // sin 15 degrees
    const auto materialOf = [&](std::size_t body) -> const MaterialDefinition & {
        if (setup.multi_body && !setup.part_of_node.empty() && body < I.nodes_of.size() &&
            !I.nodes_of[body].empty()) {
            const std::uint32_t part = setup.part_of_node[I.nodes_of[body].front()];
            if (part < setup.part_definitions.size()) return setup.part_definitions[part];
        }
        return setup.tile_material;
    };
    const auto closeCut = [&](std::size_t index) {
        if (index < I.cut_log.size()) I.cut_log[index].open = false;
    };
    // An engagement ends by taking its constraint with it. Otherwise the
    // constraint is KEPT from step to step, and that is not a detail: the
    // friction impulse it has built up is carried into the next step, which is
    // what lets a slow press be held. Remade every step, it started from nothing
    // each time, and against a heavy blade on a light batten lying on the floor
    // it delivered a fifth of its limit and let the blade sink uncut.
    const auto endEngagement = [&](std::vector<Impl::Engagement>::iterator it) {
        if (it->rigid != 0 && I.world->hasJoint(it->rigid)) I.world->removeJoint(it->rigid);
        closeCut(it->cut);
        return I.engaged.erase(it);
    };

    // Anything a fracture holds an index to is left alone until it is done.
    std::set<std::size_t> spoken_for;
    const auto reserve = [&](const Pending &job) {
        spoken_for.insert(job.which);
        for (const std::size_t body : job.island_bodies) spoken_for.insert(body);
    };
    if (I.pending) reserve(*I.pending);
    for (const auto &job : I.queued) reserve(*job);

    // Engagements whose blade or target has gone are over, and the kerfs of a
    // body that no longer exists go with it.
    for (auto it = I.engaged.begin(); it != I.engaged.end();) {
        bool blade_here = false;
        for (const Impl::Blade &blade : I.blades)
            blade_here = blade_here ||
                         (blade.id == it->blade && blade.attached && I.index_of.count(blade.body));
        if (blade_here && I.index_of.count(it->target)) { ++it; continue; }
        it = endEngagement(it);
    }
    for (auto it = I.kerfs.begin(); it != I.kerfs.end();)
        it = I.index_of.count(it->first) ? std::next(it) : I.kerfs.erase(it);
    for (auto it = I.exempt.begin(); it != I.exempt.end();)
        it = I.index_of.count(it->second) ? std::next(it) : I.exempt.erase(it);
    // A meeting that has not been heard from for a twentieth of a second is over.
    for (auto it = I.touching.begin(); it != I.touching.end();) {
        if (I.steps_taken > it->second.second + 12) {
            closeCut(it->second.first);
            it = I.touching.erase(it);
        } else {
            ++it;
        }
    }

    const auto noteTouch = [&](const std::pair<unsigned, std::string> &key, const std::string &body,
                               const std::string &kind, const Vec3 &a, const Vec3 &n,
                               const Vec3 &t, const Vec3 &f) {
        const auto open = I.touching.find(key);
        if (open != I.touching.end() && open->second.first < I.cut_log.size() &&
            I.cut_log[open->second.first].kind == kind) {
            open->second.second = I.steps_taken;
            return;
        }
        if (open != I.touching.end()) closeCut(open->second.first);
        LiveCut said{};
        said.blade = body;
        said.target = key.second;
        said.kind = kind;
        said.at_s = I.time_s;
        said.speed_m_s = length(a);
        said.into_m_s = dot(a, n);
        said.along_m_s = dot(a, t);
        said.across_m_s = dot(a, f);
        said.open = true;
        I.cut_log.push_back(said);
        I.touching[key] = {I.cut_log.size() - 1, I.steps_taken};
    };

    for (Impl::Blade &blade : I.blades) {
        if (!blade.attached) continue;
        const auto holder = I.index_of.find(blade.body);
        if (holder == I.index_of.end()) {
            blade.attached = false;
            blade.cutting.clear();
            continue;
        }
        const std::size_t bi = holder->second;
        const MatterBodyId blade_id = I.body_of[bi];
        // Set aside (park), the edge is out of the world with its body: in
        // nothing, and cutting nothing, until it is back.
        if (!I.world->contains(blade_id)) {
            blade.cutting.clear();
            continue;
        }
        // A body that came through a fracture whole is put back in a new frame.
        // Follow the blade's own cells into it, so the edge stays on the steel.
        if (blade_id != blade.body_id && !blade.frame_offsets.empty()) {
            Vec3 was_centre{}, now_centre{};
            const double count = static_cast<double>(blade.frame_nodes.size());
            for (std::size_t k = 0; k < blade.frame_nodes.size(); ++k) {
                was_centre += blade.frame_offsets[k];
                now_centre += I.cell_offset_m[blade.frame_nodes[k]];
            }
            was_centre = (1.0 / count) * was_centre;
            now_centre = (1.0 / count) * now_centre;
            Mat3 correlation{};
            for (std::size_t k = 0; k < blade.frame_nodes.size(); ++k) {
                const Vec3 a = I.cell_offset_m[blade.frame_nodes[k]] - now_centre;
                const Vec3 b = blade.frame_offsets[k] - was_centre;
                const double av[3] = {a.x, a.y, a.z}, bv[3] = {b.x, b.y, b.z};
                for (int r = 0; r < 3; ++r)
                    for (int c = 0; c < 3; ++c) correlation.m[r][c] += av[r] * bv[c];
            }
            const Mat3 turn = nearestRotation(correlation);
            const auto carry = [&](const Vec3 &p) { return turn * (p - was_centre) + now_centre; };
            blade.heel_local = carry(blade.heel_local);
            blade.tip_local = carry(blade.tip_local);
            blade.grip_local = carry(blade.grip_local);
            blade.facing_local = normalized(turn * blade.facing_local);
            for (std::size_t k = 0; k < blade.frame_nodes.size(); ++k)
                blade.frame_offsets[k] = I.cell_offset_m[blade.frame_nodes[k]];
            if (I.wielding && I.holding == bi) I.grip_local = blade.grip_local;
            blade.body_id = blade_id;
        }

        const RigidMechanicalState blade_state = I.world->mechanicalState(blade_id);
        const RigidSnapshot &bs = blade_state.motion;
        const Vec3 heel = bs.center_of_mass_world_m + bs.orientation_world.rotate(blade.heel_local);
        const Vec3 tip = bs.center_of_mass_world_m + bs.orientation_world.rotate(blade.tip_local);
        const double edge_length = length(tip - heel);
        if (!(edge_length > 1e-9)) continue;
        const Vec3 t = (1.0 / edge_length) * (tip - heel);
        Vec3 n = bs.orientation_world.rotate(blade.facing_local);
        n = normalized(n - dot(n, t) * t);
        const Vec3 f = cross(t, n);
        const std::size_t samples = std::max<std::size_t>(
            4, static_cast<std::size_t>(std::ceil(edge_length / (0.5 * cell))));
        const double ds = edge_length / static_cast<double>(samples);
        std::vector<Vec3> along(samples);
        for (std::size_t k = 0; k < samples; ++k)
            along[k] = heel + ((static_cast<double>(k) + 0.5) * ds) * t;
        const Quat to_blade = conjugateOf(bs.orientation_world);
        const MaterialDefinition &blade_material = materialOf(bi);
        // Which way the blade is being pushed when it is not moving: the hand,
        // if it is in one, and its own weight.
        const bool in_hand = I.wielding && I.holding == bi;
        const Vec3 intent = (in_hand ? I.hand_force : Vec3{}) + blade_state.mass_kg * gravity;
        // Whatever it is welded to is part of it, not something to cut.
        std::set<std::string> welded;
        for (const Impl::SceneJoint &joint : I.joints) {
            if (!joint.attached || joint.kind != JoltWorld::JointKind::Fixing) continue;
            if (joint.a == blade.body) welded.insert(joint.b);
            if (joint.b == blade.body) welded.insert(joint.a);
        }
        // The blade's own matter against another body's, for knowing when it is
        // clear of it and ordinary contact can resume.
        const auto overlaps = [&](const CellGrid &grid, const RigidSnapshot &ts) {
            const Quat to_target = conjugateOf(ts.orientation_world);
            for (const std::uint32_t node : I.nodes_of[bi]) {
                const Vec3 p = to_target.rotate(bs.center_of_mass_world_m +
                                                bs.orientation_world.rotate(I.cell_offset_m[node]) -
                                                ts.center_of_mass_world_m);
                long long x = 0, y = 0, z = 0;
                grid.place(p, x, y, z);
                for (long long dx = -1; dx <= 1; ++dx)
                    for (long long dy = -1; dy <= 1; ++dy)
                        for (long long dz = -1; dz <= 1; ++dz) {
                            if (!grid.at.count(CellGrid::key(x + dx, y + dy, z + dz))) continue;
                            const Vec3 off = p - grid.centre(x + dx, y + dy, z + dz);
                            const double reach = cell - 0.002;
                            if (std::abs(off.x) < reach && std::abs(off.y) < reach &&
                                std::abs(off.z) < reach)
                                return true;
                        }
            }
            return false;
        };

        blade.cutting.clear();
        for (std::size_t j = 0; j < I.described.size(); ++j) {
            if (j == bi) continue;
            const std::string target_name = I.described[j].name;
            const std::pair<unsigned, std::string> key{blade.id, target_name};
            const auto engaged_it = std::find_if(I.engaged.begin(), I.engaged.end(),
                                                 [&](const Impl::Engagement &e) {
                                                     return e.blade == blade.id &&
                                                            e.target == target_name;
                                                 });
            const bool was_engaged = engaged_it != I.engaged.end();
            const MatterBodyId target_id = I.body_of[j];
            const bool carried = j == I.holding && !I.wielding;
            const bool eligible = !I.described[j].anchored && welded.count(target_name) == 0 &&
                                  spoken_for.count(j) == 0 && !carried &&
                                  I.world->contains(target_id);
            if (!eligible) {
                if (was_engaged) endEngagement(engaged_it);
                if (I.exempt.erase(key) && I.world->contains(target_id))
                    I.world->setPairContactOwner(blade_id, target_id, PairContactOwner::Jolt);
                continue;
            }
            const RigidSnapshot ts = I.world->snapshot(target_id);

            // Nowhere near: nothing to do. A bounding sphere against the edge,
            // widened by how far the two can close in a step.
            const double target_reach = 0.5 * length(I.described[j].dimensions_m) + cell;
            const double spin = length(bs.angular_velocity_rad_s) *
                                    (edge_length + length(blade.grip_local) + cell) +
                                length(ts.angular_velocity_rad_s) * target_reach;
            const double sweep =
                (length(bs.linear_velocity_m_s - ts.linear_velocity_m_s) + spin) * dt_s + 2.0 * cell;
            const double along_edge =
                std::clamp(dot(ts.center_of_mass_world_m - heel, t), 0.0, edge_length);
            const double gap = length(ts.center_of_mass_world_m - (heel + along_edge * t));
            if (gap > target_reach + sweep && !was_engaged && I.exempt.count(key) == 0) continue;

            const CellGrid grid = gridOf(I.nodes_of[j], I.cell_offset_m, cell);
            const auto held_kerfs = I.kerfs.find(target_name);
            const std::vector<Impl::Kerf> *kerfs_here =
                held_kerfs == I.kerfs.end() ? nullptr : &held_kerfs->second;
            const Quat to_target = conjugateOf(ts.orientation_world);
            const auto toLocal = [&](const Vec3 &w) {
                return to_target.rotate(w - ts.center_of_mass_world_m);
            };
            const Vec3 n_local = to_target.rotate(n);
            const Vec3 t_local = to_target.rotate(t);
            const Vec3 f_local = to_target.rotate(f);
            const auto uncut = [&](const Vec3 &p) {
                return grid.holds(p) && !alreadyCut(kerfs_here, p);
            };
            // The outward normal of the target's surface nearest a point in its
            // uncut matter: the shortest way out along the target's own axes,
            // which are its cells' faces, to a twentieth of a cell. Two cells
            // from anywhere out, the edge's own facing stands in.
            const auto nearestFace = [&](const Vec3 &p) {
                const Vec3 axes[6] = {Vec3{1.0, 0.0, 0.0}, Vec3{-1.0, 0.0, 0.0},
                                      Vec3{0.0, 1.0, 0.0}, Vec3{0.0, -1.0, 0.0},
                                      Vec3{0.0, 0.0, 1.0}, Vec3{0.0, 0.0, -1.0}};
                const double step = 0.05 * cell;
                constexpr int kMost = 40;
                int best = kMost + 1;
                Vec3 out = -1.0 * n_local;
                for (const Vec3 &axis : axes) {
                    for (int m = 1; m < best; ++m) {
                        if (!uncut(p + (static_cast<double>(m) * step) * axis)) {
                            best = m;
                            out = axis;
                            break;
                        }
                    }
                }
                return out;
            };

            // Whether a point is in the slit a kerf in this blade's own plane has
            // already opened: the target's matter, cut, and cut the way this
            // edge would cut it.
            const auto inOwnSlit = [&](const Vec3 &p) {
                if (kerfs_here == nullptr || !grid.holds(p)) return false;
                for (const auto &kerf : *kerfs_here) {
                    if (std::abs(dot(kerf.w, f_local)) < std::cos(5.0 * kPiBlade / 180.0)) continue;
                    const Vec3 d = p - kerf.origin;
                    if (std::abs(dot(d, kerf.w)) > kerf.half_width) continue;
                    if (kerf.covers(dot(d, kerf.u), dot(d, kerf.v), 1e-9)) return true;
                }
                return false;
            };

            // Each part of the edge: is it in the target's matter, against uncut
            // matter, and how much uncut matter will its path cross this step.
            double touching_m = 0.0, swept_area = 0.0, weight = 0.0;
            bool any_inside = false;
            Vec3 contact_sum{}, normal_sum{};
            std::vector<Vec3> engaged_blade_local, engaged_start_local;
            for (std::size_t k = 0; k < samples; ++k) {
                const Vec3 pw = along[k];
                const Vec3 vb = bs.linear_velocity_m_s +
                                cross(bs.angular_velocity_rad_s, pw - bs.center_of_mass_world_m);
                const Vec3 vt = ts.linear_velocity_m_s +
                                cross(ts.angular_velocity_rad_s, pw - ts.center_of_mass_world_m);
                const Vec3 p0 = toLocal(pw);
                const Vec3 d = dt_s * to_target.rotate(vb - vt);
                const bool inside = grid.holds(p0);
                any_inside = any_inside || inside;
                const bool start_uncut = uncut(p0);
                const Vec3 probe = p0 + 0.001 * n_local;
                const bool touching = start_uncut || uncut(probe);
                double in_len = 0.0;
                // Coming back into its own kerf from outside the body. The body's
                // rigid shape knows nothing of the slit, and met there it stopped
                // a second stroke at the kerf's mouth: along a partial cut, the
                // cut could never be carried on.
                bool into_slit = false;
                const double travel = length(d);
                if (travel > 1e-12) {
                    const int steps = std::max(1, static_cast<int>(std::ceil(travel / (0.125 * cell))));
                    bool entered = start_uncut;
                    Vec3 previous = p0;
                    for (int m = 0; m < steps; ++m) {
                        const Vec3 q = p0 + ((static_cast<double>(m) + 0.5) / steps) * d;
                        if (!into_slit && !uncut(q) && inOwnSlit(q)) into_slit = true;
                        if (uncut(q)) {
                            in_len += travel / steps;
                            if (!entered) {
                                entered = true;
                                // Came in through a face, or out of an old kerf
                                // into the uncut matter ahead of it.
                                normal_sum += grid.holds(previous) ? -1.0 * n_local
                                                                   : faceCrossed(grid, previous, q);
                            }
                        }
                        previous = q;
                    }
                }
                if (start_uncut) {
                    // Already in uncut matter as the step starts. At a kerf's
                    // frontier -- cut matter just behind the edge -- the surface
                    // it is against is the frontier, facing it head on.
                    // Otherwise it was pressed in: a contact's slop lets a flat
                    // pushed with 800 N sink millimetres into oak, and the edge
                    // along its side goes in with it. What that edge is against
                    // is the surface nearest it. Taken as head-on, a pressed flat
                    // "bit" with its side edge and cut the batten it lay on.
                    const bool at_frontier = alreadyCut(kerfs_here, p0 - 0.0005 * n_local);
                    normal_sum += at_frontier ? -1.0 * n_local : nearestFace(p0);
                } else if (touching && in_len <= 0.0) {
                    const Vec3 outside = p0 - 0.0005 * n_local;
                    normal_sum += grid.holds(outside) ? -1.0 * n_local
                                                      : faceCrossed(grid, outside, probe);
                }
                if (touching) touching_m += ds;
                if (travel > 1e-12 && in_len > 0.0)
                    swept_area += ds * (in_len / travel) * std::max(0.0, dot(d, n_local));
                if (touching || in_len > 0.0 || inside || into_slit) {
                    contact_sum += pw;
                    weight += 1.0;
                    engaged_blade_local.push_back(to_blade.rotate(pw - bs.center_of_mass_world_m));
                    engaged_start_local.push_back(p0);
                }
            }

            if (!(weight > 0.0)) {
                if (was_engaged) {
                    // Out of it. The blade may still be lying in the kerf's
                    // mouth, so ordinary contact waits until it is clear.
                    endEngagement(engaged_it);
                    I.exempt.insert(key);
                }
                if (I.exempt.count(key) && !overlaps(grid, ts)) {
                    I.world->setPairContactOwner(blade_id, target_id, PairContactOwner::Jolt);
                    I.exempt.erase(key);
                }
                continue;
            }

            const Vec3 centroid = (1.0 / weight) * contact_sum;
            const Vec3 a = (bs.linear_velocity_m_s +
                            cross(bs.angular_velocity_rad_s, centroid - bs.center_of_mass_world_m)) -
                           (ts.linear_velocity_m_s +
                            cross(ts.angular_velocity_rad_s, centroid - ts.center_of_mass_world_m));
            const double a_n = dot(a, n), a_t = dot(a, t), a_f = dot(a, f);
            const double speed = length(a);

            Impl::Engagement *e = was_engaged ? &*engaged_it : nullptr;
            if (e == nullptr) {
                // A new meeting. Decide what it is, from the surface it meets,
                // the edge's own geometry, and the motion (section 5).
                const MaterialDefinition &target_material = materialOf(j);
                const Vec3 surface = length(normal_sum) > 1e-9
                                         ? ts.orientation_world.rotate(normalized(normal_sum))
                                         : -1.0 * n;
                const Vec3 into = -1.0 * surface;
                const double v_in = dot(a, into);
                const double push_in = dot(intent, into);
                const double sin_half_bevel = std::sin(0.5 * blade.bevel_deg * kPiBlade / 180.0);
                std::string kind;
                bool bites = false;
                if (!(target_material.yield_strength_pa > 0.0)) {
                    kind = "brittle";
                } else if (target_material.hardness_pa >= blade_material.hardness_pa) {
                    kind = "blunt";
                } else if (dot(t, into) > 0.7 && a_t > 0.0) {
                    kind = "point";
                } else if (dot(n, into) < sin_half_bevel) {
                    // The bevel or the flat lies against the surface and rides it.
                    kind = std::abs(dot(f, surface)) >= std::abs(dot(n, surface)) ? "flat" : "glancing";
                } else {
                    const bool moving = speed >= kCreep;
                    const double lead_n = moving ? a_n : dot(intent, n);
                    const double lead_f = moving ? std::abs(a_f) : std::abs(dot(intent, f));
                    const bool leads = lead_n > 0.0 && lead_n >= lead_f;
                    const bool pressed = v_in > 0.005 || push_in > 0.0;
                    if (!leads) {
                        kind = "flat";
                    } else if (pressed) {
                        bites = true;
                        kind = speed < kPress           ? "press"
                             : std::abs(a_t) > a_n      ? "slice"
                             : v_in < kShallow * speed  ? "glancing"
                                                        : "edge";
                    }
                    // Resting on it without pressing is not a meeting worth a word.
                }
                if (!bites) {
                    if (!kind.empty()) noteTouch(key, blade.body, kind, a, n, t, f);
                    // Ordinary contact, unless the blade is still inside it from
                    // before, in which case it stays suspended until it is clear.
                    continue;
                }

                // It bites. Continue a kerf this blade is lying in, or start one.
                const Vec3 origin = toLocal(centroid);
                std::vector<Impl::Kerf> &list = I.kerfs[target_name];
                std::size_t kerf_index = list.size();
                for (std::size_t k = 0; k < list.size(); ++k) {
                    if (std::abs(dot(list[k].w, f_local)) < std::cos(5.0 * kPiBlade / 180.0)) continue;
                    if (std::abs(dot(origin - list[k].origin, list[k].w)) > list[k].half_width) continue;
                    kerf_index = k;
                    break;
                }
                if (kerf_index == list.size()) {
                    Impl::Kerf kerf{};
                    kerf.blade = blade.id;
                    kerf.origin = origin;
                    kerf.u = t_local;
                    kerf.v = n_local;
                    kerf.w = f_local;
                    kerf.strip = 0.25 * cell;
                    kerf.half_width = 0.5 * blade.thickness + 0.001;
                    findCrossings(kerf, I.nodes_of[j], I.cell_offset_m, setup.asset);
                    list.push_back(std::move(kerf));
                }
                const double resistance =
                    target_material.fracture_energy_j_m2 +
                    target_material.hardness_pa * 2.0 * blade.edge_radius;

                // A meeting that did not bite a moment ago and does now is the
                // same meeting going somewhere; the note of it closes.
                if (const auto open = I.touching.find(key); open != I.touching.end()) {
                    closeCut(open->second.first);
                    I.touching.erase(open);
                }
                LiveCut said{};
                said.blade = blade.body;
                said.target = target_name;
                said.kind = kind;
                said.at_s = I.time_s;
                said.speed_m_s = speed;
                said.into_m_s = a_n;
                said.along_m_s = a_t;
                said.across_m_s = a_f;
                said.resistance_j_m2 = resistance;
                said.open = true;
                I.cut_log.push_back(said);
                Impl::Engagement fresh{};
                fresh.blade = blade.id;
                fresh.target = target_name;
                fresh.kerf = kerf_index;
                fresh.resistance = resistance;
                fresh.cut = I.cut_log.size() - 1;
                I.engaged.push_back(std::move(fresh));
                e = &I.engaged.back();
            }

            std::vector<Impl::Kerf> &list = I.kerfs[target_name];
            if (e->kerf >= list.size()) continue;
            Impl::Kerf &kerf = list[e->kerf];
            // Until anything has been cut it is not a kerf yet, only where the
            // edge is resting: it follows the blade.
            if (kerf.swept.empty()) {
                const Vec3 origin = toLocal(centroid);
                const bool moved = std::abs(dot(kerf.w, f_local)) < std::cos(kPiBlade / 180.0) ||
                                   std::abs(dot(origin - kerf.origin, kerf.w)) > 0.0005;
                kerf.origin = origin;
                kerf.u = t_local;
                kerf.v = n_local;
                if (moved) {
                    kerf.w = f_local;
                    findCrossings(kerf, I.nodes_of[j], I.cell_offset_m, setup.asset);
                } else {
                    // Same plane: the crossings are unchanged but their
                    // coordinates in it follow the new origin.
                    for (auto &crossing : kerf.crossings) {
                        crossing.u = dot(crossing.at_local - kerf.origin, kerf.u);
                        crossing.v = dot(crossing.at_local - kerf.origin, kerf.v);
                    }
                }
            }
            const bool embedded = !kerf.swept.empty() && any_inside;

            // The resistance, from the relative motion at the start of the step.
            // Into the material it is ONE-SIDED: the kerf pushes the edge back and
            // never pulls it in (JoltWorld::addKerf), so an edge drawn out of its
            // kerf is not held by it and nothing here has to decide which way the
            // edge is going. (Something did, and a solver bounce of -20 mm/s
            // switched the resistance off for a step: the blade fell into the
            // batten unresisted and cut what a 219 N press should not have.) At
            // rest the edge is held with all of R L; moving, the resistance is
            // shared between the two directions with power R L v_n -- the
            // slice-push law.
            const double v_n_plus = std::max(0.0, a_n);
            // What the edge is up against. At rest, the length of it touching
            // uncut matter. Moving into the material, the area its path will
            // sweep through uncut matter this step over how far it goes -- which
            // is less than what it touches when it comes out of the far side
            // within the step. (Taken as the larger of the two, the step in which
            // an edge left a rope segment was charged whole, and the account
            // said a 400 mm^2 rope had cost 480 mm^2 to cut.)
            double length_eff = touching_m;
            if (v_n_plus > kCreep) length_eff = swept_area / (v_n_plus * dt_s);
            length_eff = std::min(length_eff, edge_length);
            double c_n = 1.0, c_t = 0.0;
            if (std::hypot(v_n_plus, a_t) >= kCreep) {
                const double denominator = v_n_plus * v_n_plus + a_t * a_t + kCreep * kCreep;
                c_n = (v_n_plus * v_n_plus + kCreep * kCreep) / denominator;
                c_t = v_n_plus * std::abs(a_t) / denominator;
            }
            I.world->setPairContactOwner(blade_id, target_id, PairContactOwner::External);
            JoltWorld::KerfDescription constraint{};
            constraint.blade = blade_id;
            constraint.target = target_id;
            constraint.point_world_m = centroid;
            constraint.facing_world = n;
            constraint.flat_world = f;
            constraint.embedded = embedded;
            constraint.resist_facing_n = e->resistance * length_eff * c_n;
            constraint.resist_along_n = e->resistance * length_eff * c_t;
            // The same constraint as last step if nothing about its shape has
            // changed: same state (touching or embedded), and the engaged part of
            // the edge within two cells of where it acts. Its axes are the
            // blade's own and turn with it, so a swing does not need a new one.
            const Vec3 point_blade = to_blade.rotate(centroid - bs.center_of_mass_world_m);
            const bool keep = e->rigid != 0 && I.world->hasJoint(e->rigid) &&
                              e->embedded == embedded &&
                              length(point_blade - e->point_blade_local) < 2.0 * cell;
            if (keep) {
                I.world->updateKerf(e->rigid, constraint.resist_facing_n,
                                    constraint.resist_along_n);
            } else {
                if (e->rigid != 0 && I.world->hasJoint(e->rigid)) I.world->removeJoint(e->rigid);
                e->rigid = I.world->addKerf(constraint);
                e->point_blade_local = point_blade;
                e->point_target_local = toLocal(centroid);
            }
            I.world->wake(blade_id);
            I.world->wake(target_id);
            e->embedded = embedded;
            e->n_world = n;
            e->t_world = t;
            // The motion the step is accounted against is at the constraint's
            // own point, which is where its impulses act.
            {
                const Vec3 at = bs.center_of_mass_world_m +
                                bs.orientation_world.rotate(e->point_blade_local);
                const Vec3 va =
                    (bs.linear_velocity_m_s +
                     cross(bs.angular_velocity_rad_s, at - bs.center_of_mass_world_m)) -
                    (ts.linear_velocity_m_s +
                     cross(ts.angular_velocity_rad_s, at - ts.center_of_mass_world_m));
                e->vn_before = dot(va, n);
                e->vt_before = dot(va, t);
            }
            e->touching_m = touching_m;
            e->push_n = dot(intent, n);
            e->sample_blade_local = std::move(engaged_blade_local);
            e->sample_start_target_local = std::move(engaged_start_local);
            e->sample_ds = ds;
            blade.cutting = target_name;
            if (cutTrace()) {
                // Where the engaged edge is against the frontier of its kerf:
                // depth along the facing, and the swept interval of the strips
                // under it.
                double v_low = 1e9, v_high = -1e9, front_low = 1e9, front_high = -1e9;
                for (const Vec3 &p : e->sample_start_target_local) {
                    const Vec3 d = p - kerf.origin;
                    const double v = dot(d, kerf.v);
                    v_low = std::min(v_low, v);
                    v_high = std::max(v_high, v);
                    const auto strip = kerf.swept.find(static_cast<int>(std::floor(dot(d, kerf.u) / kerf.strip)));
                    if (strip != kerf.swept.end() && !strip->second.empty()) {
                        front_low = std::min(front_low, strip->second.back().second);
                        front_high = std::max(front_high, strip->second.back().second);
                    }
                }
                std::fprintf(stderr,
                             "cut  t=%.4f %s>%s touch=%.4f swept=%.3g owed=%.3g Leff=%.4f cn=%.3f ct=%.3f "
                             "Fn=%.1f Ft=%.1f vn=%.4f vt=%.4f vf=%.4f emb=%d samples=%zu "
                             "edge_v=[%.5f,%.5f] front=[%.5f,%.5f]\n",
                             I.time_s, blade.body.c_str(), target_name.c_str(), touching_m,
                             swept_area, e->owed_m2, length_eff, c_n, c_t, constraint.resist_facing_n,
                             constraint.resist_along_n, a_n, a_t, a_f, embedded ? 1 : 0,
                             e->sample_blade_local.size(), v_low, v_high, front_low, front_high);
            }
        }
    }
}

void LiveWorld::settleCuts(double dt_s) {
    (void)dt_s;
    Impl &I = *impl_;
    TileImpactSetup &setup = *I.setup;
    const double cell = I.request.cell_size_m;

    // Contacts the rigid solver resolved between a blade and something it did
    // not bite: the flat of it, the point, a glance. Said once per meeting, from
    // the contact's own normal against the blade's axes.
    for (const ImpactEvent &event : I.blade_contacts) {
        for (const Impl::Blade &blade : I.blades) {
            if (!blade.attached) continue;
            const auto holder = I.index_of.find(blade.body);
            if (holder == I.index_of.end()) continue;
            const MatterBodyId blade_id = I.body_of[holder->second];
            if (event.body_a != blade_id && event.body_b != blade_id) continue;
            const MatterBodyId other = event.body_a == blade_id ? event.body_b : event.body_a;
            std::size_t j = static_cast<std::size_t>(-1);
            for (std::size_t k = 0; k < I.body_of.size(); ++k)
                if (I.body_of[k] == other) { j = k; break; }
            if (j == static_cast<std::size_t>(-1) || I.described[j].anchored) continue;
            const std::string &target_name = I.described[j].name;
            const bool engaged_now = std::any_of(I.engaged.begin(), I.engaged.end(),
                                                 [&](const Impl::Engagement &e) {
                                                     return e.blade == blade.id && e.target == target_name;
                                                 });
            if (engaged_now || event.closing_speed_m_s < 0.05) continue;
            const RigidSnapshot bs = I.world->snapshot(blade_id);
            const Vec3 heel = bs.center_of_mass_world_m + bs.orientation_world.rotate(blade.heel_local);
            const Vec3 tip = bs.center_of_mass_world_m + bs.orientation_world.rotate(blade.tip_local);
            const Vec3 t = normalized(tip - heel);
            Vec3 n = bs.orientation_world.rotate(blade.facing_local);
            n = normalized(n - dot(n, t) * t);
            const Vec3 f = cross(t, n);
            // The contact normal, pointing out of the target at the blade.
            const Vec3 surface = event.body_b == blade_id ? event.normal_a_to_b : -1.0 * event.normal_a_to_b;
            const Vec3 a = event.body_b == blade_id ? event.relative_velocity_b_minus_a_m_s
                                                    : -1.0 * event.relative_velocity_b_minus_a_m_s;
            const double on_flat = std::abs(dot(surface, f));
            const double on_point = std::abs(dot(surface, t));
            const double on_edge = std::abs(dot(surface, n));
            std::string kind;
            if (on_flat >= on_point && on_flat >= on_edge) kind = "flat";
            else if (on_point >= on_edge) kind = "point";
            else kind = "glancing";
            // Iterating a blade's own contacts from Jolt; key them the same way
            // the cutting side does so one meeting is one note.
            const std::pair<unsigned, std::string> key{blade.id, target_name};
            const auto open = I.touching.find(key);
            if (open != I.touching.end() && open->second.first < I.cut_log.size() &&
                I.cut_log[open->second.first].kind == kind) {
                open->second.second = I.steps_taken;
                continue;
            }
            if (open != I.touching.end() && open->second.first < I.cut_log.size())
                I.cut_log[open->second.first].open = false;
            LiveCut said{};
            said.blade = blade.body;
            said.target = target_name;
            said.kind = kind;
            said.at_s = I.time_s;
            said.speed_m_s = length(a);
            said.into_m_s = dot(a, n);
            said.along_m_s = dot(a, t);
            said.across_m_s = dot(a, f);
            said.open = true;
            I.cut_log.push_back(said);
            I.touching[key] = {I.cut_log.size() - 1, I.steps_taken};
        }
    }
    I.blade_contacts.clear();

    // Pieces waiting for a fracture to finish before they can be split off.
    if (!I.pending && I.queued.empty() && !I.split_later.empty()) {
        const std::set<std::string> waiting = std::move(I.split_later);
        I.split_later.clear();
        for (const std::string &name : waiting) {
            const auto found = I.index_of.find(name);
            if (found == I.index_of.end()) continue;
            if (!stillWhole(I.nodes_of[found->second], setup.matter)) splitCut(found->second);
        }
    }
    if (I.engaged.empty()) return;

    // What an engagement has cut and not yet paid for, paid now: one equal and
    // opposite impulse along the way the edge faced, taken from how fast the
    // two are closing there, so the work the cut cost is work the two bodies
    // gave. Bounded by what that closing motion has: an edge with nothing left
    // to give leaves the rest unpaid, and the trace says so.
    const auto settleOwed = [&](Impl::Engagement &owing, Impl::Blade &cutter,
                                MatterBodyId cutter_id, MatterBodyId owed_id) {
        if (!(owing.owed_m2 > 0.0) || !(owing.resistance > 0.0)) return;
        const RigidMechanicalState one = I.world->mechanicalState(cutter_id);
        const RigidMechanicalState two = I.world->mechanicalState(owed_id);
        const RigidSnapshot &a = one.motion, &b = two.motion;
        const Vec3 at = a.center_of_mass_world_m + a.orientation_world.rotate(owing.point_blade_local);
        const Vec3 closing =
            (a.linear_velocity_m_s + cross(a.angular_velocity_rad_s, at - a.center_of_mass_world_m)) -
            (b.linear_velocity_m_s + cross(b.angular_velocity_rad_s, at - b.center_of_mass_world_m));
        const double v_n = dot(closing, owing.n_world);
        const double due = owing.resistance * owing.owed_m2;
        double took = 0.0;
        if (v_n > 1e-6 && one.mass_kg > 0.0 && two.mass_kg > 0.0) {
            const double reduced = one.mass_kg * two.mass_kg / (one.mass_kg + two.mass_kg);
            const double impulse = std::min(due / v_n, reduced * v_n);
            try {
                const PairImpulseAudit audit = I.world->applyPairImpulse(
                    cutter_id, owed_id, at, at, -impulse * owing.n_world, std::max(1e-3, 1e-4 * due));
                took = std::max(0.0, -audit.impulse_work_j);
            } catch (const std::exception &refused) {
                if (cutTrace())
                    std::fprintf(stderr, "unpaid t=%.4f %s owed=%.3g: %s\n", I.time_s,
                                 owing.target.c_str(), owing.owed_m2, refused.what());
            }
        }
        const double bought = took / owing.resistance;
        cutter.cut_area += bought;
        cutter.cut_work += took;
        if (owing.cut < I.cut_log.size()) {
            I.cut_log[owing.cut].area_m2 += bought;
            I.cut_log[owing.cut].work_j += took;
        }
        if (cutTrace())
            std::fprintf(stderr, "paid t=%.4f %s owed=%.3g due=%.4g took=%.4g J v_n=%.4f\n", I.time_s,
                         owing.target.c_str(), owing.owed_m2, due, took, v_n);
        owing.owed_m2 = std::max(0.0, owing.owed_m2 - bought);
    };

    std::vector<std::string> to_split;
    for (Impl::Engagement &e : I.engaged) {
        if (e.rigid == 0 || !I.world->hasJoint(e.rigid)) continue;
        Impl::Blade *blade = nullptr;
        for (Impl::Blade &candidate : I.blades)
            if (candidate.id == e.blade) blade = &candidate;
        if (blade == nullptr) continue;
        const auto bi = I.index_of.find(blade->body);
        const auto tj = I.index_of.find(e.target);
        if (bi == I.index_of.end() || tj == I.index_of.end()) continue;
        auto &list = I.kerfs[e.target];
        if (e.kerf >= list.size()) continue;
        Impl::Kerf &kerf = list[e.kerf];
        const MatterBodyId blade_id = I.body_of[bi->second];
        const MatterBodyId target_id = I.body_of[tj->second];
        const RigidSnapshot bs = I.world->snapshot(blade_id);
        const RigidSnapshot ts = I.world->snapshot(target_id);

        // What the friction took. The kinetic energy an impulse J removes from a
        // relative motion that went from v_before to v_after along its axis is
        // exactly J (v_before + v_after) / 2, whatever the two masses are.
        const JoltWorld::KerfImpulse impulse = I.world->kerfImpulse(e.rigid);
        const Vec3 at = bs.center_of_mass_world_m + bs.orientation_world.rotate(e.point_blade_local);
        const Vec3 va = (bs.linear_velocity_m_s +
                         cross(bs.angular_velocity_rad_s, at - bs.center_of_mass_world_m)) -
                        (ts.linear_velocity_m_s +
                         cross(ts.angular_velocity_rad_s, at - ts.center_of_mass_world_m));
        const double vn_after = dot(va, e.n_world);
        const double vt_after = dot(va, e.t_world);
        // That is the measure for an edge LOSING speed -- one stopped dead
        // inside a step went less far than the energy it lost would have carried
        // it, and the energy is where the cut went. An edge GAINING speed went
        // further than its mean speed says, because a step moves a body by its
        // speed at the end of the step; the resistance acted over that distance,
        // so it did its force times that distance of work. (Charging the mean
        // there let an edge driven through at 800 N run ahead of what it had
        // paid for, by half a step's gain in speed every step.) So: the impulse
        // times the larger of the two. Into the material the kerf only ever
        // pushes the edge back, and does cutting work only on an edge going in;
        // along the edge it is a friction, which takes energy either way. What
        // this leaves unaccounted is the step's own M dv^2 / 2, which is never
        // negative: no cut is paid for with energy that was not there.
        const double work_measured =
            std::max(0.0, impulse.facing_n_s) *
                std::max({0.0, 0.5 * (e.vn_before + vn_after), vn_after}) +
            std::abs(impulse.along_n_s) *
                std::max(0.5 * std::abs(e.vt_before + vt_after), std::abs(vt_after));
        if (!(e.resistance > 0.0)) continue;

        // Where it bought it: along each engaged part of the edge's ACTUAL path
        // through uncut matter this step, scaled so that exactly `area` is cut.
        const CellGrid grid = gridOf(I.nodes_of[tj->second], I.cell_offset_m, cell);
        const Quat to_target = conjugateOf(ts.orientation_world);
        // One part of the edge's advance this step: the pieces of uncut matter
        // it crossed, each as (u, v_low, v_high) in the kerf's plane, in the
        // order it crossed them, and how much depth that came to.
        struct Advance {
            std::vector<std::array<double, 3>> pieces;
            double gained{};
            bool against{};
        };
        std::vector<Advance> advances;
        advances.reserve(e.sample_blade_local.size());
        double actual = 0.0;
        const auto uncut = [&](const Vec3 &q) { return grid.holds(q) && !alreadyCut(&list, q); };
        // The blade's own steel, where it is now, asked in the target's frame.
        const CellGrid steel = gridOf(I.nodes_of[bi->second], I.cell_offset_m, cell);
        const Quat to_blade_now = conjugateOf(bs.orientation_world);
        const auto underSteel = [&](const Vec3 &q) {
            const Vec3 world = ts.center_of_mass_world_m + ts.orientation_world.rotate(q);
            return steel.holds(to_blade_now.rotate(world - bs.center_of_mass_world_m));
        };
        // How far back from p, against the facing, runs uncut matter with the
        // blade's steel in it: to the kerf's frontier, to the surface, or to the
        // back of the blade, whichever comes first -- to a hundredth of a cell.
        const auto backFrom = [&](const Vec3 &p) {
            const double coarse = 0.1 * cell, fine = 0.01 * cell;
            const int most = static_cast<int>(std::ceil(64.0 * cell / coarse));
            int m = 1;
            for (; m <= most; ++m) {
                const Vec3 q = p - (m * coarse) * kerf.v;
                if (!uncut(q) || !underSteel(q)) break;
            }
            double back = (m - 1) * coarse;
            for (int f = 1; f < 10; ++f) {
                const Vec3 q = p - (back + fine) * kerf.v;
                if (!uncut(q) || !underSteel(q)) break;
                back += fine;
            }
            return back;
        };
        for (std::size_t k = 0; k < e.sample_blade_local.size(); ++k) {
            const Vec3 start = e.sample_start_target_local[k];
            const Vec3 end = to_target.rotate(bs.center_of_mass_world_m +
                                              bs.orientation_world.rotate(e.sample_blade_local[k]) -
                                              ts.center_of_mass_world_m);
            const Vec3 path = end - start;
            const double travel = length(path);
            Advance advance{};
            advance.against = grid.holds(end + 0.001 * kerf.v) &&
                              !alreadyCut(&list, end + 0.001 * kerf.v);
            // The path, piece by piece: each stretch of it in uncut matter is
            // laid into the strip it is over, so a slicing edge -- one moving
            // along its own length as it goes in, crossing a strip every few
            // millimetres -- cuts where it went. (Laid down as one strip-wide
            // rectangle at the middle of the path, a 12 m/s slice through a rope
            // booked 88% of the rope's section and severed four of its bonds.)
            bool met = false;
            Vec3 entered{};
            if (travel > 1e-12) {
                const int steps = std::max(1, static_cast<int>(std::ceil(travel / (0.125 * cell))));
                const double rise = dot(path, kerf.v) / steps;
                for (int m = 0; m < steps; ++m) {
                    const Vec3 q = start + ((static_cast<double>(m) + 0.5) / steps) * path;
                    if (!uncut(q)) continue;
                    if (!met) {
                        entered = q - (0.5 * rise) * kerf.v;
                        met = true;
                    }
                    if (rise > 0.0) {
                        const double v_q = dot(q - kerf.origin, kerf.v);
                        advance.pieces.push_back(
                            {dot(q - kerf.origin, kerf.u), v_q - 0.5 * rise, v_q + 0.5 * rise});
                        advance.gained += rise;
                    }
                }
            } else if (uncut(start + 1e-7 * kerf.v)) {
                entered = start;   // at rest, in uncut matter
                met = true;
            }
            // A kerf is one cut in from the surface, not a row of separate ones,
            // so what is cut here starts where the uncut matter the steel is in
            // begins: the frontier, or the surface. An edge can be in matter
            // ahead of the frontier -- the first step of a press that has not
            // yet been held, or any step a solver did not quite finish -- and
            // that matter is the blade's to pay for with what it sweeps now.
            // Marking only from where this step's path met matter left a gap
            // behind it, and the strip, which is one interval, then closed the
            // gap for nothing. docs/cutting-model.md section 3.
            if (met) {
                const double back = backFrom(entered);
                if (back > 0.0) {
                    const double v_in = dot(entered - kerf.origin, kerf.v);
                    advance.pieces.insert(advance.pieces.begin(),
                                          {dot(entered - kerf.origin, kerf.u), v_in - back, v_in});
                    advance.gained += back;
                }
            }
            advances.push_back(std::move(advance));
        }
        // Touching means to within the resolution the path is followed at, an
        // eighth of a cell: pieces of a path are that far apart.
        const double join = 0.125 * cell;
        // Where the edge went through uncut matter this step, strip by strip.
        // Each part of the edge covers a sample's width of the kerf -- several
        // strips -- and its path is laid into every strip in that width that has
        // matter in it: a part of the edge covers its width whether or not all
        // of that is inside the body, and a strip beyond the body's face has
        // nothing in it to cut or to pay for.
        std::map<int, std::vector<std::pair<double, double>>> wanted;
        for (const Advance &advance : advances) {
            for (const auto &piece : advance.pieces) {
                const int first = static_cast<int>(std::floor((piece[0] - 0.5 * e.sample_ds) / kerf.strip));
                const int last = static_cast<int>(std::floor((piece[0] + 0.5 * e.sample_ds) / kerf.strip));
                const double v_mid = 0.5 * (piece[1] + piece[2]);
                for (int s = first; s <= last; ++s) {
                    const double u_s = (static_cast<double>(s) + 0.5) * kerf.strip;
                    if (!grid.holds(kerf.origin + u_s * kerf.u + v_mid * kerf.v)) continue;
                    wanted[s].emplace_back(piece[1], piece[2]);
                }
            }
        }
        // What of it is new, merged where it touches.
        for (auto &[s, spans] : wanted) {
            std::sort(spans.begin(), spans.end());
            std::vector<std::pair<double, double>> merged;
            for (const auto &span : spans) {
                if (!merged.empty() && span.first <= merged.back().second + join)
                    merged.back().second = std::max(merged.back().second, span.second);
                else
                    merged.push_back(span);
            }
            spans = std::move(merged);
            for (const auto &span : spans) actual += kerf.strip * kerf.uncovered(s, span.first, span.second);
        }

        const auto mark = [&](double u_centre, double v_low, double v_high) {
            if (!(v_high > v_low)) return;
            const int first = static_cast<int>(std::floor((u_centre - 0.5 * e.sample_ds) / kerf.strip));
            const int last = static_cast<int>(std::floor((u_centre + 0.5 * e.sample_ds) / kerf.strip));
            for (int s = first; s <= last; ++s) kerf.add(s, v_low, v_high, join);
        };
        // What it bought: the area the work cuts at the declared resistance,
        // whatever the speed (docs/cutting-model.md section 3) -- and one case
        // more. An edge held still by something ELSE, a batten pressed to the
        // floor under it, while it is pushed in harder than the matter under
        // it resists: that matter is not what is holding it, and it cannot
        // hold, so what the steel is in is cut, at its declared cost. The
        // energy is the push's, delivered in the step that stopped the blade
        // and taken by the other contact; nothing moves now for an impulse to
        // measure. A push short of R L -- the 181 N a 200 N hand has left after
        // holding the blade up, on oak that resists with 300 -- cuts nothing
        // this way.
        constexpr double kStill = 0.02;     // m/s
        const bool still = std::abs(e.vn_before) <= kStill && std::abs(vn_after) <= kStill;
        const bool overpowered =
            still && actual > 0.0 && e.push_n > e.resistance * e.touching_m;
        double work = work_measured;
        double area = overpowered ? std::max(work / e.resistance, actual) : work / e.resistance;
        // Bought first, then cut, as far as the work goes -- every strip the
        // same share of what the edge went through in it -- and what is not
        // bought is still there under the steel for the next step to find and
        // buy. Except in the step the edge comes out of the far side: no later
        // step sweeps that matter again, so all of it is cut, and what this
        // step's work did not cover is taken at once from the closing motion
        // (settleOwed). Left standing, it was a strip at the far edge of an oak
        // panel that held the two halves together.
        bool leaving = !still;
        for (std::size_t k = 0; leaving && k < e.sample_blade_local.size(); ++k) {
            const Vec3 end = to_target.rotate(bs.center_of_mass_world_m +
                                              bs.orientation_world.rotate(e.sample_blade_local[k]) -
                                              ts.center_of_mass_world_m);
            if (grid.holds(end)) leaving = false;
        }
        // Coming out, it cuts as far as it can pay: this step's work, and what
        // one impulse along the facing can still take out of the closing motion
        // (settleOwed takes it, audited). An edge that came out into something
        // that stopped it -- a cleaver through a log onto the floor, bouncing
        // back up -- has no closing motion left to pay with, and the last 26 mm
        // of oak it went through in that step were marked free: a 1600 mm^2
        // section came apart for 623 mm^2 of work.
        double affordable = area;
        if (leaving) {
            const double closing = std::max(0.0, vn_after);
            const double m_b = I.world->mechanicalState(blade_id).mass_kg;
            const double m_t = I.world->mechanicalState(target_id).mass_kg;
            if (closing > 0.0 && m_b > 0.0 && m_t > 0.0)
                affordable += 0.5 * (m_b * m_t / (m_b + m_t)) * closing * closing / e.resistance;
        }
        if (!(affordable > 0.0)) continue;
        // What the kerf holds before this step's marks, so what they add can be
        // counted: an overpowered edge is charged for what it actually cut.
        const auto sweptArea = [&kerf]() { return kerf.area(); };
        const double swept_before = sweptArea();
        if (actual > 1e-15) {
            const double scale = overpowered ? 1.0 : std::min(1.0, affordable / actual);
            for (const auto &[s, spans] : wanted)
                for (const auto &span : spans)
                    kerf.add(s, span.first, span.first + scale * (span.second - span.first), join);
        }
        const double marked = sweptArea() - swept_before;
        const double remaining = area - marked;
        e.owed_m2 = leaving ? std::max(0.0, marked - area) : 0.0;
        // What the friction took beyond what the edge was seen to sweep went
        // into the uncut matter just ahead of it. A friction limit in a velocity
        // solver can stop a body within one step, and a body stopped within a
        // step has not moved in it -- so an edge that should have run 12 mm into
        // a block before stopping ends the step where it started, and the 12 mm
        // is where the energy went. The cut goes where the energy went: from the
        // first uncut matter ahead of each engaged part of the edge, along the
        // way it faces, no further than it could have closed in the step.
        if (remaining > 1e-9 * std::max(area, 1e-12)) {
            const double reach = 2.0 * cell + (std::abs(e.vn_before) + std::abs(e.vt_before)) * dt_s;
            // Fine: the look starts AT the frontier and a coarse step past it
            // marks matter nobody paid for. (It was a sixteenth of a cell, and
            // the frontier ran a millimetre ahead of a stationary edge.)
            const int looks = std::max(1, static_cast<int>(std::ceil(reach / (0.01 * cell))));
            std::vector<std::pair<double, double>> ahead;   // (u, where uncut matter starts)
            for (std::size_t k = 0; k < e.sample_blade_local.size(); ++k) {
                const Vec3 end = to_target.rotate(bs.center_of_mass_world_m +
                                                  bs.orientation_world.rotate(e.sample_blade_local[k]) -
                                                  ts.center_of_mass_world_m);
                const Vec3 rel = end - kerf.origin;
                const double u_here = dot(rel, kerf.u);
                const double v_end = dot(rel, kerf.v);
                // Uncut matter ahead begins at the kerf's frontier under this
                // part of the edge if that is ahead of it, and where the edge is
                // otherwise -- and it has to be matter.
                const double from =
                    kerf.throughTo(static_cast<int>(std::floor(u_here / kerf.strip)), v_end);
                for (int m = 0; m <= looks; ++m) {
                    const double v_try = from + reach * m / looks;
                    const Vec3 q = end + (v_try - v_end + 1e-7) * kerf.v;
                    if (!grid.holds(q) || alreadyCut(&list, q)) continue;
                    ahead.emplace_back(u_here, v_try);
                    break;
                }
            }
            if (!ahead.empty()) {
                const double depth = remaining / (static_cast<double>(ahead.size()) * e.sample_ds);
                for (const auto &[u, from] : ahead) mark(u, from, from + depth);
            }
        }
        if (overpowered) {
            // Charged for what the marks added to the kerf and no more. A mark
            // that could not join the kerf cut nothing; charged for anyway, the
            // same overlap was paid for again every step the edge stood there,
            // and a 6 J section was booked at 14 J.
            const double realized = std::max(0.0, sweptArea() - swept_before);
            area = std::max(work_measured / e.resistance, realized);
            work = area * e.resistance;
            if (!(area > 0.0)) continue;
        }
        blade->cut_area += area;
        blade->cut_work += work;
        if (e.cut < I.cut_log.size()) {
            I.cut_log[e.cut].area_m2 += area;
            I.cut_log[e.cut].work_j += work;
        }

        // Every bond the kerf has now reached is severed, in the scene's matter,
        // where every later lattice run will find it severed too.
        std::size_t severed = 0;
        for (const auto &crossing : kerf.crossings) {
            if (crossing.bond >= setup.matter.bonds.size()) continue;
            ActiveBondState &bond = setup.matter.bonds[crossing.bond];
            if (!bond.alive) continue;
            if (!kerf.covers(crossing.u, crossing.v, 1e-9)) continue;
            bond.alive = false;
            bond.damage = 1.0;
            bond.failure_mode = BondFailureMode::Shear;
            ++severed;
        }

        // And every rope link the kerf has reached where it runs through matter:
        // the fibres between two segments of a rope are cut with the segments.
        std::size_t parted = 0;
        for (Impl::SceneJoint &joint : I.joints) {
            if (!joint.attached || joint.rigid == 0 || joint.kind != JoltWorld::JointKind::Link) continue;
            if (joint.a != e.target && joint.b != e.target) continue;
            const auto ja = I.index_of.find(joint.a);
            const auto jb = I.index_of.find(joint.b);
            if (ja == I.index_of.end() || jb == I.index_of.end()) continue;
            const RigidSnapshot sa = I.world->snapshot(I.body_of[ja->second]);
            const RigidSnapshot sb = I.world->snapshot(I.body_of[jb->second]);
            const Vec3 la = to_target.rotate(sa.center_of_mass_world_m +
                                             sa.orientation_world.rotate(joint.point_local_a) -
                                             ts.center_of_mass_world_m);
            const Vec3 lb = to_target.rotate(sb.center_of_mass_world_m +
                                             sb.orientation_world.rotate(joint.point_local_b_tie) -
                                             ts.center_of_mass_world_m);
            const double da = dot(la - kerf.origin, kerf.w);
            const double db = dot(lb - kerf.origin, kerf.w);
            if ((da >= 0.0) == (db >= 0.0)) continue;
            const Vec3 x = la + (da / (da - db)) * (lb - la);
            if (!kerf.covers(dot(x - kerf.origin, kerf.u), dot(x - kerf.origin, kerf.v), 1e-9)) continue;
            bool in_matter = grid.holds(x);
            if (!in_matter) {
                const std::size_t other = joint.a == e.target ? jb->second : ja->second;
                const RigidSnapshot so = I.world->snapshot(I.body_of[other]);
                const Vec3 xo = conjugateOf(so.orientation_world)
                                    .rotate(ts.center_of_mass_world_m +
                                            ts.orientation_world.rotate(x) - so.center_of_mass_world_m);
                in_matter = gridOf(I.nodes_of[other], I.cell_offset_m, cell).holds(xo);
            }
            if (!in_matter) continue;
            I.world->removeJoint(joint.rigid);
            joint.rigid = 0;
            joint.attached = false;
            I.delays.push_back({I.time_s, joint.a + " to " + joint.b, "cut", 0.0, 0.0});
            for (const std::string &side : {joint.a, joint.b}) {
                const auto found = I.index_of.find(side);
                if (found != I.index_of.end()) I.world->wake(I.body_of[found->second]);
            }
            ++parted;
        }
        if (e.cut < I.cut_log.size()) {
            I.cut_log[e.cut].bonds += severed;
            I.cut_log[e.cut].links += parted;
        }
        if (cutTrace())
            std::fprintf(stderr,
                         "took t=%.4f %s work=%.4g area=%.4g actual=%.4g marked=%.4g "
                         "severed=%zu parted=%zu Jn=%.4g Jt=%.4g vn %.4f->%.4f vt %.4f->%.4f\n",
                         I.time_s, e.target.c_str(), work, area, actual, marked, severed, parted,
                         impulse.facing_n_s, impulse.along_n_s, e.vn_before, vn_after,
                         e.vt_before, vt_after);
        // Came out of the far side with more cut than paid for: paid now,
        // while the two bodies it is owed between are still the two there are.
        if (e.owed_m2 > 0.0) settleOwed(e, *blade, blade_id, target_id);
        if (severed > 0) to_split.push_back(e.target);
    }

    for (const std::string &name : to_split) {
        const auto found = I.index_of.find(name);
        if (found == I.index_of.end()) continue;
        if (stillWhole(I.nodes_of[found->second], setup.matter)) continue;
        // A fracture holds indices into the body table while it runs; splitting
        // under it would move them. The severed bonds wait, and so does this.
        if (I.pending || !I.queued.empty()) {
            I.split_later.insert(name);
            continue;
        }
        splitCut(found->second);
    }
}

std::size_t LiveWorld::splitCut(std::size_t which) {
    Impl &I = *impl_;
    TileImpactSetup &setup = *I.setup;
    if (which >= I.described.size() || which >= I.nodes_of.size()) return 0;
    const LiveBodyPose parent = I.described[which];
    const std::vector<std::uint32_t> nodes = I.nodes_of[which];
    const MatterBodyId old_body = I.body_of[which];
    if (!I.world->contains(old_body) || nodes.empty()) return 1;
    const RigidSnapshot snap = I.world->snapshot(old_body);
    I.vanished[parent.name] = snap;

    const MaterialDefinition *material = &setup.tile_material;
    if (setup.multi_body && !setup.part_of_node.empty()) {
        const std::uint32_t part = setup.part_of_node[nodes.front()];
        if (part < setup.part_definitions.size()) material = &setup.part_definitions[part];
    }

    // The body's own cells, where they are and moving as it moves -- so each
    // piece carries away exactly the momentum its cells had.
    FragmentLattice island = buildFragmentLattice(
        setup.matter, nodes, I.cell_offset_m,
        FragmentPose{snap.center_of_mass_world_m, snap.orientation_world,
                     snap.linear_velocity_m_s, snap.angular_velocity_rad_s},
        I.plastic_extension_m, I.plastic_strain_m);
    const auto components = findConnectedComponents(island.matter);
    if (components.size() <= 1) return 1;

    const CombinedContactMaterial against_ground = combineContactMaterials(
        compileContactMaterial(*material), compileContactMaterial(setup.ground_material));
    // One at a time, so piece k is exactly component k.
    std::vector<RigidFragmentDescription> fragments;
    fragments.reserve(components.size());
    for (const FragmentComponent &component : components) {
        FragmentBuildResult built = buildFragmentRepresentations(
            island.matter, std::span<const FragmentComponent>(&component, 1),
            {.first_body_id = I.next_body_id++,
             .maximum_rigid_fragments = 1,
             .minimum_nodes_per_rigid_fragment = 1,
             .maximum_collision_points = 192,
             .friction = against_ground.dynamic_friction,
             .restitution = against_ground.restitution,
             .rolling_resistance = compileContactMaterial(*material).rolling_resistance});
        if (built.rigid_fragments.empty()) return 1;
        fragments.push_back(std::move(built.rigid_fragments.front()));
    }

    std::vector<std::string> before;
    before.reserve(I.described.size());
    for (const LiveBodyPose &pose : I.described) before.push_back(pose.name);

    // The kerfs it carried, in the world, to hand on to its pieces.
    std::vector<Impl::Kerf> handed;
    if (const auto carried = I.kerfs.find(parent.name); carried != I.kerfs.end()) {
        for (Impl::Kerf kerf : carried->second) {
            kerf.origin = snap.center_of_mass_world_m + snap.orientation_world.rotate(kerf.origin);
            kerf.u = snap.orientation_world.rotate(kerf.u);
            kerf.v = snap.orientation_world.rotate(kerf.v);
            kerf.w = snap.orientation_world.rotate(kerf.w);
            handed.push_back(std::move(kerf));
        }
        I.kerfs.erase(carried);
    }

    I.world->removeAndDestroy(old_body);
    const auto drop = [&](auto &vector) {
        if (which < vector.size()) vector.erase(vector.begin() + static_cast<std::ptrdiff_t>(which));
    };
    drop(I.described); drop(I.body_of); drop(I.nodes_of);
    drop(I.limits_of); drop(I.impedance_of); drop(I.density_of); drop(I.tensile_of);
    drop(I.compressive_of);
    // Its pieces measure their matter against their own cells' boxes.
    I.matter_of.erase(parent.name);
    if (I.holding == which) {
        I.holding = static_cast<std::size_t>(-1);
        I.wielding = false;
    } else if (I.holding != static_cast<std::size_t>(-1) && I.holding > which) {
        --I.holding;
    }

    std::vector<std::string> made_names;
    for (std::size_t k = 0; k < components.size(); ++k) {
        const RigidFragmentDescription &fragment = fragments[k];
        std::vector<std::uint32_t> parent_nodes;
        parent_nodes.reserve(components[k].node_indices.size());
        for (const std::uint32_t local : components[k].node_indices) {
            const std::uint32_t node = island.parent_node[local];
            parent_nodes.push_back(node);
            I.cell_offset_m[node] = island.matter.nodes[local].position_world_m -
                                    fragment.mass_properties.center_of_mass_world_m;
        }
        LiveBodyPose piece{};
        piece.name = parent.name + " piece " + std::to_string(k + 1);
        piece.material = parent.material;
        piece.color_rgba = parent.color_rgba;
        // Something that came off something: debris, in the room's terms.
        piece.fragment = true;
        piece.shape = "hull";
        I.limits_of.push_back(fragmentFractureLimits(setup.matter, parent_nodes,
                                                     material->density_kg_m3,
                                                     material->young_modulus_pa,
                                                     material->yield_strength_pa,
                                                     material->fracture_energy_j_m2,
                                                     I.request.cell_size_m));
        I.impedance_of.push_back(acousticImpedance(material->density_kg_m3, material->young_modulus_pa));
        I.density_of.push_back(material->density_kg_m3);
        I.tensile_of.push_back(material->tensile_strength_pa);
        I.compressive_of.push_back(material->compressive_strength_pa);
        I.nodes_of.push_back(std::move(parent_nodes));
        piece.dimensions_m = cellBounds(I.nodes_of.back(), I.cell_offset_m, I.request.cell_size_m);
        made_names.push_back(piece.name);
        I.described.push_back(std::move(piece));
        I.body_of.push_back(fragment.body_id);
        I.next_body_id = std::max(I.next_body_id, fragment.body_id + 1);
    }
    I.world->addFragments(fragments);
    I.index_of.clear();
    for (std::size_t i = 0; i < I.described.size(); ++i) I.index_of.emplace(I.described[i].name, i);

    // Each piece takes the kerfs that made it, in its own frame: a new body is
    // made facing the world's own way, about its own centre of mass.
    for (std::size_t k = 0; k < made_names.size(); ++k) {
        const Vec3 centre = fragments[k].mass_properties.center_of_mass_world_m;
        const std::size_t index = I.index_of[made_names[k]];
        for (Impl::Kerf kerf : handed) {
            kerf.origin = kerf.origin - centre;
            findCrossings(kerf, I.nodes_of[index], I.cell_offset_m, setup.asset);
            I.kerfs[made_names[k]].push_back(std::move(kerf));
        }
    }

    // What it held -- fuel, moisture, the heat in it -- is shared out among its
    // pieces by the cells each one took, exactly as a fracture shares it out:
    // a burning log cut in two is two burning halves, each with its share of
    // the fuel and at the temperature the log was, and nothing is made or lost
    // (the ledger does not see a cut, because nothing crosses its boundary).
    // What was attached to it -- a heater under it, a gas pushing on it -- goes
    // with the piece ThermoWorld::split gives it to, and the heat paths are
    // worked out again from where the pieces are.
    if (I.thermo && I.thermo->active()) {
        if (I.thermo->holds(parent.name)) {
            std::vector<std::pair<std::string, double>> shares;
            shares.reserve(made_names.size());
            const double whole = static_cast<double>(nodes.size());
            for (std::size_t k = 0; k < made_names.size(); ++k)
                shares.emplace_back(made_names[k],
                                    static_cast<double>(components[k].node_indices.size()) / whole);
            I.thermo->split(parent.name, shares);
        }
        I.thermo->refresh(thermoShapes(), setup.ground_y);
    }

    // Everything else that holds an index, exactly as an apply does it.
    dropGuess("guess-wasted");
    restackQueue(before);
    rehangJoints();
    I.vanished.clear();
    repin();
    I.held_through.erase(parent.name);
    I.partner_of.clear();
    surveyLoads();

    // Whatever was cutting it has cut it: those meetings end as separations,
    // and the blade is in ordinary contact with the pieces from now on -- the
    // two halves' cut faces bear on its flats, as a kerf's walls do. The cells
    // the blade passed through stay with one side, so a piece starts out
    // overlapping the steel by up to a cell. That is inside the contact's
    // penetration slop, so the solver only keeps it from growing rather than
    // throwing the piece off; suspended "until clear" instead, it was never
    // clear, nothing stopped a 140 g half sliding into the blade under the
    // hand's push, and the edge then cut a second kerf into it for 8.75 J.
    for (auto it = I.engaged.begin(); it != I.engaged.end();) {
        if (it->target != parent.name) { ++it; continue; }
        if (it->cut < I.cut_log.size()) {
            I.cut_log[it->cut].separated = true;
            I.cut_log[it->cut].pieces = components.size();
            I.cut_log[it->cut].open = false;
        }
        for (const std::string &piece : made_names) {
            I.exempt.erase({it->blade, piece});
            for (const Impl::Blade &blade : I.blades) {
                if (blade.id != it->blade) continue;
                const auto holder = I.index_of.find(blade.body);
                const auto made = I.index_of.find(piece);
                if (holder == I.index_of.end() || made == I.index_of.end() || !I.inWorld(holder->second))
                    continue;
                I.world->setPairContactOwner(I.body_of[holder->second], I.body_of[made->second],
                                             PairContactOwner::Jolt);
            }
        }
        it = I.engaged.erase(it);
    }
    for (auto it = I.exempt.begin(); it != I.exempt.end();)
        it = it->second == parent.name ? I.exempt.erase(it) : std::next(it);
    I.delays.push_back({I.time_s, parent.name, "cut apart", static_cast<double>(components.size()), 0.0});
    return components.size();
}

// ===========================================================================
// Tools that work the ground (docs/ground-work.md). The process is
// ToolTerrain; this is where it meets the world, and all it is told.
// ===========================================================================

ToolTerrainHost LiveWorld::toolHost() const {
    const Impl &I = *impl_;
    ToolTerrainHost host;
    host.world = I.world.get();
    host.environment = I.environment.get();
    host.floor_y = I.setup ? I.setup->ground_y : 0.0;
    host.cell_m = I.request.cell_size_m;
    host.time_s = I.time_s;
    host.carried_objects_kg = I.carriedObjectsKg();
    host.id_of = [this](const std::string &name) -> std::optional<MatterBodyId> {
        const auto found = impl_->index_of.find(name);
        if (found == impl_->index_of.end()) return std::nullopt;
        return impl_->body_of[found->second];
    };
    host.cells_of = [this](const std::string &name) {
        std::vector<std::pair<std::uint32_t, Vec3>> out;
        const auto found = impl_->index_of.find(name);
        if (found == impl_->index_of.end()) return out;
        for (const std::uint32_t node : impl_->nodes_of[found->second])
            if (node < impl_->cell_offset_m.size()) out.emplace_back(node, impl_->cell_offset_m[node]);
        return out;
    };
    host.material_of = [this](const std::string &name) -> const MaterialDefinition * {
        const auto found = impl_->index_of.find(name);
        return found == impl_->index_of.end() ? nullptr : &impl_->definitionOf(found->second);
    };
    host.material_name_of = [this](const std::string &name) {
        const auto found = impl_->index_of.find(name);
        return found == impl_->index_of.end() ? std::string() : impl_->described[found->second].material;
    };
    host.dent_of = [this](const std::string &name) {
        const auto found = impl_->index_of.find(name);
        return found == impl_->index_of.end() ? 0.0 : impl_->described[found->second].dent_m;
    };
    host.anchored = [this](const std::string &name) {
        const auto found = impl_->index_of.find(name);
        return found != impl_->index_of.end() && impl_->described[found->second].anchored;
    };
    host.parked = [this](const std::string &name) { return impl_->parked.count(name) != 0; };
    return host;
}

unsigned LiveWorld::toolPoint(const std::string &body, const Vec3 &tip_world_m, const Vec3 &pointing_world,
                              double width_m, double thickness_m, double angle_deg, double length_m,
                              const Vec3 &grip_world_m) {
    impl_->requireLatticeRoom("toolPoint");
    Impl &I = *impl_;
    const terrain::ToolPointShape shape{width_m, thickness_m, angle_deg, length_m};
    return I.tools.declare(toolHost(), body, tip_world_m, pointing_world, shape, grip_world_m,
                           I.tool_point_refusal);
}

const std::string &LiveWorld::toolPointRefusal() const { return impl_->tool_point_refusal; }

std::vector<LiveToolPoint> LiveWorld::toolPoints() const { return impl_->tools.points(toolHost()); }

bool LiveWorld::strike(const LiveStrike &asked, std::string &why) {
    Impl &I = *impl_;
    if (I.holding == static_cast<std::size_t>(-1) || !I.wielding) {
        why = "a tool action needs the tool in the hand by its grip: wield it first";
        return false;
    }
    const std::string held = I.described[I.holding].name;
    const std::optional<LiveStroke> planned = I.tools.plan(toolHost(), asked, held, I.grip_local, why);
    if (!planned) return false;
    return stroke(*planned, why);
}

std::vector<LiveGroundWork> LiveWorld::groundWork() const { return impl_->tools.reports(); }

void LiveWorld::forgetGroundWork() { impl_->tools.forget(); }

// ===========================================================================
// Set aside and brought back (park, unpark): the inventory's bag.
//
// A thing set aside keeps its slot in the body table -- its cells, its dents and
// kerfs, what it is made of -- and its rigid body, which JoltWorld takes out of
// the broadphase without destroying it. Everything that walks the table asks
// whether a body is in the world (Impl::inWorld) before it asks the rigid world
// anything about it, so a thing that is away is not there to be met, held,
// joined, broken or cut. And nothing it is part of carries on without it: what
// it cannot be set aside from is refused, in words, before anything is touched.
// ===========================================================================

namespace {
// A joint's kind in the words a person uses for it.
const char *jointWord(JoltWorld::JointKind kind) {
    switch (kind) {
    case JoltWorld::JointKind::Slider: return "slide";
    case JoltWorld::JointKind::Link: return "rope";
    case JoltWorld::JointKind::Pulley: return "pulley";
    case JoltWorld::JointKind::Fixing: return "fixing";
    case JoltWorld::JointKind::Elastic: return "spring";
    case JoltWorld::JointKind::Drum: return "drum rope";
    default: return "hinge";
    }
}
} // namespace

bool LiveWorld::park(const std::string &name, std::string &why) {
    Impl &I = *impl_;
    why.clear();
    const auto found = I.index_of.find(name);
    if (found == I.index_of.end()) {
        why = "there is nothing called that in the scene";
        return false;
    }
    const std::size_t which = found->second;
    if (I.isParked(which)) {
        why = "it is already set aside";
        return false;
    }
    // What is joined to it goes with it. A thing of parts on pins -- a cart and
    // its two wheelsets, a mace and its head on a link -- goes in the bag as the
    // one thing it is, its pins still in it, and comes out the same (unpark). A
    // pin is kept between two names, and one whose thing is away is left as it
    // is rather than made again against nothing (rehangJoints) until the thing
    // is back. Exact bodies go as cell bodies do.
    const std::vector<std::size_t> group = I.jointedWith(which);
    const auto inGroup = [&](const std::string &part) {
        const auto at = I.index_of.find(part);
        return at != I.index_of.end() && std::find(group.begin(), group.end(), at->second) != group.end();
    };
    std::set<unsigned> own_pins;
    for (const Impl::SceneJoint &joint : I.joints)
        if (joint.attached && joint.rigid != 0 && inGroup(joint.a)) own_pins.insert(joint.rigid);
    // Breaking. A fracture being worked out holds a slot, and will destroy its
    // island and put pieces where it was: set aside from under that, a thing
    // would come back out of the bag and lie on the floor in pieces as well. The
    // same things collect and reviseMatter keep their hands off.
    const auto holds = [](const Pending &job, std::size_t k) {
        return job.which == k || job.anvil == k ||
               std::find(job.island_bodies.begin(), job.island_bodies.end(), k) != job.island_bodies.end();
    };
    const auto bladeBody = [&I](unsigned id) {
        for (const Impl::Blade &blade : I.blades)
            if (blade.id == id) return blade.body;
        return std::string();
    };
    // Why one part of it cannot go now, in words about that part; nothing when
    // it can.
    const auto refusal = [&](std::size_t k) -> std::string {
        const std::string &own = I.described[k].name;
        if (I.isParked(k)) return "it is already set aside";
        if (I.described[k].anchored) return "it is fixed in place: it is part of the room, not a thing to carry";
        if (!I.inWorld(k)) return "it is not in the world";
        for (const Impl::SceneJoint &joint : I.joints) {
            if (joint.a != own && joint.b != own) continue;
            const std::string &other = joint.a == own ? joint.b : joint.a;
            const std::string word = jointWord(joint.kind);
            // Parted, but still on record between two names: with one of them
            // away, it would be a joint to nothing.
            if (!joint.attached)
                return "the " + word + " that joined it to the " + other +
                       " has parted but is still on record: take the " + word + " away first";
            // What is not in the thing to be carried with it: a pulley's rope
            // runs over points fixed in the room, a drum's is wound so far, and
            // a motor keeps its command, its brake and its store with its pin.
            if (joint.kind == JoltWorld::JointKind::Pulley)
                return "its pulley runs over points fixed in the room: set aside, its rope would run over nothing";
            if (joint.kind == JoltWorld::JointKind::Drum)
                return "the rope on its drum is wound so far, and the bag cannot keep that yet";
            for (const Impl::Motor &motor : I.motors)
                if (motor.said.joint == joint.id)
                    return "a motor drives its " + word + ", and the bag cannot keep a motor and what controls it yet";
        }
        bool breaking = I.pending && holds(*I.pending, k);
        for (const auto &job : I.queued) breaking = breaking || holds(*job, k);
        breaking = breaking ||
                   std::find(I.held_for_fracture.begin(), I.held_for_fracture.end(), k) != I.held_for_fracture.end();
        if (breaking) return "it is breaking: what it breaks into is still being worked out";
        if (I.split_later.count(own) != 0) return "it has been cut through and is about to come apart";
        // Being cut, or cutting. An edge in matter is held there by a kerf
        // between the two, and one still lying in a kerf's mouth keeps their
        // ordinary contact suspended until it is clear: set aside, either is
        // half a cut with nothing to finish it.
        for (const Impl::Engagement &e : I.engaged) {
            if (e.target == own) return "it is being cut: the " + bladeBody(e.blade) + "'s edge is in it";
            if (bladeBody(e.blade) == own) return "its edge is in the " + e.target + ": draw it out of the cut first";
        }
        for (const auto &[blade, target] : I.exempt) {
            if (target == own) return "an edge is still in a cut in it: draw the " + bladeBody(blade) + " clear first";
            if (bladeBody(blade) == own)
                return "its edge is still in the cut it made in the " + target + ": draw it clear first";
        }
        // A tool whose point is in the ground: the ground's bite holds it there.
        if (I.tools.inGround(own)) return "its point is in the ground: pull it out first";
        // A gas that pushes on it, or that it holds in: set aside, the gas would
        // push on nothing, or have nothing round it.
        if (I.thermo)
            for (const thermo::GasRegion &region : I.thermo->state().regions) {
                if (!region.piston) continue;
                if (region.piston->body == own)
                    return "the " + region.name + " pushes on it: set aside, the gas would push on nothing";
                if (region.piston->container == own)
                    return "it holds the " + region.name + " in: set aside, the gas would have nothing round it";
            }
        // And anything else the rigid world holds it by that none of that
        // names: its own pins are the only holds it may go with.
        for (const unsigned hold : I.world->jointsOn(I.body_of[k]))
            if (own_pins.count(hold) == 0) return "something in the world is holding it";
        return {};
    };
    for (const std::size_t k : group) {
        const std::string reason = refusal(k);
        if (reason.empty()) continue;
        why = k == which ? reason : "the " + I.described[k].name + " joined to it cannot go with it: " + reason;
        return false;
    }
    double kg = 0.0;
    bool in_hand = false;
    for (const std::size_t k : group) {
        kg += I.world->mechanicalState(I.body_of[k]).mass_kg;
        in_hand = in_hand || I.holding == k;
    }
    if (I.environment && !in_hand &&
        I.carriedObjectsKg() + kg + I.environment->carriedKg() > I.environment->carryLimitKg()) {
        why = "carrying capacity includes held items, stored items and excavated ground";
        return false;
    }

    // Nothing has been touched until here. In the hand: let go first, as
    // letting go always is -- a stroke on it ends, cancelled.
    if (in_hand) release();
    for (const std::size_t k : group) {
        const std::string &own = I.described[k].name;
        // A run started early for a collision it was going to be in is not
        // wanted now: binned, as a guess always is. Only one that holds it --
        // binning waits for the worker, and a guess about something else is
        // still worth having.
        if (I.guessing && holds(*I.guessing, k)) dropGuess("guess-wasted");
        // Its points leave whatever ground they were resting on.
        if (!I.tools.empty()) I.tools.setAside(toolHost(), own);
        // Its edges are in nothing.
        for (Impl::Blade &blade : I.blades)
            if (blade.body == own) blade.cutting.clear();
    }
    // Its pins come out of the rigid world with it, as they stand: each is made
    // again when it is back, turned as far as it had turned.
    I.rememberJointAngles(*I.world);
    for (Impl::SceneJoint &joint : I.joints) {
        if (!joint.attached || joint.rigid == 0 || !inGroup(joint.a)) continue;
        if (I.world->hasJoint(joint.rigid)) I.world->removeJoint(joint.rigid);
        joint.rigid = 0;
    }
    std::vector<std::pair<std::size_t, Impl::ParkedRecord>> away;
    for (const std::size_t k : group) {
        const MatterBodyId id = I.body_of[k];
        away.push_back({k, Impl::ParkedRecord{I.world->snapshot(id), I.world->mechanicalState(id).mass_kg}});
    }
    for (std::size_t n = 0; n < away.size(); ++n) {
        const std::size_t k = away[n].first;
        const std::string &own = I.described[k].name;
        std::string refused;
        if (I.world->park(I.body_of[k], refused)) {
            I.parked.emplace(own, away[n].second);
            // What it holds -- its heat, what it is made of, its fuel -- stays
            // with it exactly: time stands still for it while it is away
            // (ThermoWorld::park), and it is still the network's, on its ledger.
            if (I.thermo && I.thermo->holds(own)) I.thermo->park(own);
            continue;
        }
        // Something the checks above do not see holds this part: what already
        // went comes back where it was, and its pins are made again.
        for (std::size_t m = 0; m < n; ++m) {
            const std::size_t back = away[m].first;
            std::string ignored;
            (void)I.world->unpark(I.body_of[back], away[m].second.pose, ignored);
            I.parked.erase(I.described[back].name);
            if (I.thermo && I.thermo->holds(I.described[back].name)) I.thermo->unpark(I.described[back].name);
        }
        rehangJoints();
        why = k == which ? refused : "the " + own + " joined to it cannot go with it: " + refused;
        return false;
    }
    // What rested on it falls, and what it rested on carries it no more. Jolt
    // wakes nothing when a body is taken out from under a sleeping one (see
    // applyPending), and the load survey is asked again on the next step.
    for (const auto &[k, record] : away) {
        const double reach = 0.5 * length(I.described[k].dimensions_m) + 0.05;
        for (std::size_t j = 0; j < I.described.size(); ++j) {
            if (j == k || I.described[j].anchored || !I.inWorld(j)) continue;
            const Vec3 there = I.world->snapshot(I.body_of[j]).center_of_mass_world_m;
            if (length(there - record.pose.center_of_mass_world_m) <= reach + 0.5 * length(I.described[j].dimensions_m))
                I.world->wake(I.body_of[j]);
        }
    }
    I.settleJointedContacts();
    I.survey_due = true;
    return true;
}

bool LiveWorld::unpark(const std::string &name, const Vec3 &at_world_m, const Quat &facing_world,
                       std::string &why) {
    Impl &I = *impl_;
    why.clear();
    const auto found = I.index_of.find(name);
    if (found == I.index_of.end()) {
        why = "there is nothing called that in the scene";
        return false;
    }
    const std::size_t which = found->second;
    if (!I.isParked(which)) {
        why = "it is not set aside: it is in the world already";
        return false;
    }
    const auto place = [](double v) { return std::isfinite(v) && std::abs(v) <= 1e5; };
    if (!place(at_world_m.x) || !place(at_world_m.y) || !place(at_world_m.z)) {
        why = "where to put it is not a place: three finite numbers, in metres";
        return false;
    }
    const double size = std::sqrt(facing_world.w * facing_world.w + facing_world.x * facing_world.x +
                                  facing_world.y * facing_world.y + facing_world.z * facing_world.z);
    if (!std::isfinite(size) || !(size > 1e-9)) {
        why = "its facing is not a turn: a quaternion with a size, w first";
        return false;
    }
    const Quat facing{facing_world.w / size, facing_world.x / size, facing_world.y / size, facing_world.z / size};
    // At rest, where it is asked to be, facing as poses() would say it faces:
    // that is its rigid pose with the turn its shape carries on top
    // (Impl::shapeTurn), so the rigid pose is the facing with that turn taken
    // off -- as aimHeld takes it off.
    RigidSnapshot pose{};
    pose.center_of_mass_world_m = at_world_m;
    pose.orientation_world = compose(facing, conjugateOf(I.shapeTurn(which)));
    // And everything that went into the bag with it on its pins, each part
    // where it stood against this one when they were put away.
    const std::vector<std::size_t> group = I.jointedWith(which);
    for (const std::size_t k : group)
        if (!I.isParked(k)) {
            why = "the " + I.described[k].name + " joined to it is in the world already, not set aside with it";
            return false;
        }
    const RigidSnapshot was = I.parked.at(name).pose;
    const Quat undo = conjugateOf(was.orientation_world);
    std::vector<std::pair<std::size_t, RigidSnapshot>> poses;
    for (const std::size_t k : group) {
        const RigidSnapshot &then = I.parked.at(I.described[k].name).pose;
        RigidSnapshot now{};
        now.center_of_mass_world_m =
            pose.center_of_mass_world_m +
            pose.orientation_world.rotate(undo.rotate(then.center_of_mass_world_m - was.center_of_mass_world_m));
        now.orientation_world = compose(pose.orientation_world, compose(undo, then.orientation_world));
        poses.push_back({k, now});
    }
    for (std::size_t n = 0; n < poses.size(); ++n) {
        if (I.world->unpark(I.body_of[poses[n].first], poses[n].second, why)) continue;
        // Nothing comes out unless all of it can: what already did goes back.
        for (std::size_t m = 0; m < n; ++m) {
            std::string ignored;
            (void)I.world->park(I.body_of[poses[m].first], ignored);
        }
        return false;
    }
    for (const auto &[k, now] : poses) {
        const std::string &own = I.described[k].name;
        I.parked.erase(own);
        if (I.thermo && I.thermo->holds(own)) I.thermo->unpark(own);
    }
    // Coupled again from where it is now, holding what it held as it was put
    // away; and told what it weighs, if that changed while it could not be told.
    if (I.thermo) {
        I.thermo->refresh(thermoShapes(), I.setup->ground_y);
        I.mirrorMasses();
    }
    // Its pins, made again where they are in its parts and turned as far as
    // they had turned (rehangJoints); a pin between exact parts keeps the two
    // from meeting each other (settleJointedContacts, at its end).
    if (group.size() > 1) rehangJoints();
    I.survey_due = true;
    return true;
}

bool LiveWorld::parked(const std::string &name) const { return impl_->parked.count(name) != 0; }

bool LiveWorld::anchored(const std::string &name) const {
    const auto found = impl_->index_of.find(name);
    return found != impl_->index_of.end() && found->second < impl_->described.size() &&
           impl_->described[found->second].anchored;
}

// ===========================================================================
// A world that is kept: the whole of it as it stands, and the scene opened
// again from that (docs/inventory-and-hands-design.md, "What a room keeps").
// ===========================================================================

std::vector<std::string> LiveWorld::notKept() {
    return {"legacy snapshots recover body heat; missing heaters are suspended and gas history restarts from the scene",
            "anything under way: a world is saved only between breaks, strokes of the hand, cuts and a point's "
            "time in the ground, so the last one saved before any of those is what comes back",
            "the solver's memory of its contacts: a thing that was moving carries on from where it was, but "
            "not step for step as it would have"};
}

std::vector<std::string> LiveWorld::notCarried() {
    return {"heaters and gas regions: as the room declares them, from the start",
            "anything under way: a world is carried only between breaks, strokes of the hand, cuts and a point's "
            "time in the ground, so the last one saved before any of those is what comes back",
            "the solver's memory of its contacts: a thing that was moving carries on from where it was, but "
            "not step for step as it would have"};
}

const LiveRestore &LiveWorld::restored() const { return impl_->restored; }

std::string LiveWorld::snapshot(std::string &why, const std::string &spec_digest) const {
    const Impl &I = *impl_;
    why.clear();
    const auto refuse = [&why](std::string reason) {
        why = std::move(reason);
        return std::string{};
    };
    // What a saved world cannot carry, and so waits for: each is over in well
    // under a second of the world's time, or as soon as the hand is done.
    if (I.pending || !I.queued.empty() || !I.held_for_fracture.empty())
        return refuse("a break is being worked out: the world is saved once it has come apart");
    if (!I.split_later.empty()) return refuse("something cut through is about to come apart");
    if (!I.engaged.empty() || !I.exempt.empty())
        return refuse("an edge is in a cut: the world is saved once it is clear");
    // Nor while an edge's ordinary contact with anything is suspended -- the
    // edge biting, or lying in the mouth of the cut it made (prepareCuts) --
    // whatever the lists above say: made again, the two would meet as ordinary
    // solids, one inside the other.
    for (const Impl::Blade &blade : I.blades) {
        const auto holder = I.index_of.find(blade.body);
        if (!blade.attached || holder == I.index_of.end() || !I.inWorld(holder->second)) continue;
        for (std::size_t j = 0; j < I.described.size(); ++j)
            if (j != holder->second && I.inWorld(j) &&
                I.world->pairContactOwner(I.body_of[holder->second], I.body_of[j]) == PairContactOwner::External)
                return refuse("the " + blade.body + "'s edge is in a cut in the " + I.described[j].name +
                              ": the world is saved once it is clear");
    }
    for (const LiveBodyPose &body : I.described)
        if (I.tools.inGround(body.name))
            return refuse("the " + body.name + "'s point is in the ground: the world is saved once it is out");
    if (I.stroke) return refuse("the hand is making a stroke: the world is saved once it is over");

    nlohmann::json doc;
    doc["format"] = kWorldFormat;
    doc["fingerprint"] = {{"nodes", I.fingerprint_nodes}, {"bonds", I.fingerprint_bonds}, {"hash", I.fingerprint_hash}};
    // And each authored part of it, and what lays every cell out, so that a
    // world carried into this scene once it has changed finds each thing's
    // cells again (LiveWorld::open with a carry).
    doc["lattice"] = I.lattice_settings;
    nlohmann::json parts = nlohmann::json::array();
    for (const PartPrint &part : I.part_prints)
        parts.push_back({{"bodies", part.bodies},
                         {"definition", part.definition},
                         {"heat", part.heat},
                         {"cells", part.cells},
                         {"anchored", part.anchored},
                         {"nodes", nlohmann::json::array({part.node_begin, part.node_end})},
                         {"bonds", nlohmann::json::array({part.bond_begin, part.bond_end})}});
    doc["parts"] = std::move(parts);
    doc["spec_digest"] = spec_digest;
    doc["t_s"] = savedNumber(I.time_s);
    doc["steps"] = I.steps_taken;
    doc["last_dt_s"] = savedNumber(I.last_dt_s);
    doc["foresee_horizon_s"] = savedNumber(I.foresee_horizon_s);
    doc["next"] = {{"body", I.next_body_id}, {"joint", I.next_joint}, {"blade", I.next_blade},
                   {"point", I.tools.nextId()}};

    // Every body: what it is, its cells and where they sit in its frame, and
    // where it is and how it moves -- or where it was put away.
    nlohmann::json bodies = nlohmann::json::array();
    for (std::size_t i = 0; i < I.described.size(); ++i) {
        const LiveBodyPose &d = I.described[i];
        const MatterBodyId id = I.body_of[i];
        const JoltWorld::BodySurface surface = I.world->surfaceOf(id);
        nlohmann::json b = {{"name", d.name},
                            {"material", d.material},
                            {"shape", d.shape},
                            {"dimensions_m", savedVec(d.dimensions_m)},
                            {"revision", d.revision},
                            {"color_rgba", d.color_rgba},
                            {"anchored", d.anchored},
                            {"fragment", d.fragment},
                            {"dent_m", savedNumber(d.dent_m)},
                            {"dent_at_m", savedVec(d.dent_at_m)},
                            {"body_id", id},
                            {"friction", savedNumber(surface.friction)},
                            {"restitution", savedNumber(surface.restitution)},
                            {"rolling_resistance", savedNumber(surface.rolling_resistance)}};
        if (const auto precise = I.precise_bodies.find(d.name); precise != I.precise_bodies.end()) {
            b["mechanical_model"] = "precise-rigid-v1";
            b["precise_rigid_definition"] = nlohmann::json::parse(precise->second.definition_json);
            // Away in the bag, it is not in the rigid world to be asked: what
            // it weighed as it was put away is its mass.
            const auto away = I.parked.find(d.name);
            b["precise_mass_kg"] = savedNumber(away != I.parked.end() ? away->second.mass_kg
                                                                     : I.world->mechanicalState(id).mass_kg);
            b["from"] = d.name;
        }
        // Which authored thing its cells came from, by name: a piece of a tool
        // is still of that tool, for whoever keeps a record of things.
        const std::vector<std::uint32_t> &nodes = I.nodes_of[i];
        if (!nodes.empty() && nodes.front() < I.setup->part_of_node.size()) {
            const std::uint32_t part = I.setup->part_of_node[nodes.front()];
            if (part < I.setup->part_bodies.size() && !I.setup->part_bodies[part].empty() &&
                I.setup->part_bodies[part].front() < I.request.bodies.size())
                b["from"] = I.request.bodies[I.setup->part_bodies[part].front()].name;
        }
        if (const auto tilt = I.tilt_of.find(d.name); tilt != I.tilt_of.end()) b["tilt_wxyz"] = savedQuat(tilt->second);
        std::vector<Vec3> offsets;
        offsets.reserve(nodes.size());
        for (const std::uint32_t node : nodes) offsets.push_back(I.cell_offset_m[node]);
        b["nodes_b64"] = packedArray(nodes);
        b["offsets_b64"] = packedVecs(offsets);
        if (const auto away = I.parked.find(d.name); away != I.parked.end()) {
            b["parked"] = {{"pose", savedRigid(away->second.pose)}, {"mass_kg", savedNumber(away->second.mass_kg)}};
        } else if (I.world->contains(id)) {
            b["pose"] = savedRigid(I.world->snapshot(id));
            b["awake"] = I.world->isAwake(id);
        } else {
            return refuse("the " + d.name + " is neither in the world nor set aside");
        }
        bodies.push_back(std::move(b));
    }
    doc["bodies"] = std::move(bodies);

    // What blades severed, in the scene's own matter, and each bond's
    // permanent set: sparse, since almost every bond is whole and unset.
    std::vector<std::uint32_t> dead;
    for (std::size_t k = 0; k < I.setup->matter.bonds.size(); ++k)
        if (!I.setup->matter.bonds[k].alive) dead.push_back(static_cast<std::uint32_t>(k));
    doc["dead_bonds_b64"] = packedArray(dead);
    std::vector<std::uint32_t> set_bonds;
    std::vector<double> extension, strain;
    for (std::size_t k = 0; k < I.plastic_extension_m.size(); ++k) {
        const double s = k < I.plastic_strain_m.size() ? I.plastic_strain_m[k] : 0.0;
        if (I.plastic_extension_m[k] == 0.0 && s == 0.0) continue;
        set_bonds.push_back(static_cast<std::uint32_t>(k));
        extension.push_back(I.plastic_extension_m[k]);
        strain.push_back(s);
    }
    doc["plastic"] = {{"bonds_b64", packedArray(set_bonds)},
                      {"extension_b64", packedArray(extension)},
                      {"strain_b64", packedArray(strain)}};

    // Joints, whole: what they are, in each body's frame, and -- for each one
    // holding -- what the constraint standing in for it reads now and the
    // travel it allows (a pin made again reads the same).
    nlohmann::json joints = nlohmann::json::array();
    for (const Impl::SceneJoint &j : I.joints) {
        nlohmann::json o = {{"id", j.id},
                            {"kind", savedKind(j.kind)},
                            {"a", j.a},
                            {"b", j.b},
                            {"point_local_a", savedVec(j.point_local_a)},
                            {"point_local_b", savedVec(j.point_local_b)},
                            {"axis_local_a", savedVec(j.axis_local_a)},
                            {"point_local_b_tie", savedVec(j.point_local_b_tie)},
                            {"stand_off_a", savedNumber(j.stand_off_a)},
                            {"stand_off_b", savedNumber(j.stand_off_b)},
                            {"lower", savedNumber(j.lower)},
                            {"upper", savedNumber(j.upper)},
                            {"friction", savedNumber(j.friction)},
                            {"breaks_at_n", savedNumber(j.breaks_at_n)},
                            {"over_a", savedVec(j.over_a)},
                            {"over_b", savedVec(j.over_b)},
                            {"ratio", savedNumber(j.ratio)},
                            {"holds_tension_n", savedNumber(j.holds_tension_n)},
                            {"holds_shear_n", savedNumber(j.holds_shear_n)},
                            {"comes_off_n", savedNumber(j.comes_off_n)},
                            {"rest_m", savedNumber(j.rest_m)},
                            {"stiffness_n_m", savedNumber(j.stiffness_n_m)},
                            {"damping_n_s_m", savedNumber(j.damping_n_s_m)},
                            {"at_when_hung", savedNumber(j.at_when_hung)},
                            {"attached", j.attached},
                            {"member_end", j.member_end},
                            {"declared_tension_n", savedNumber(j.declared_tension_n)},
                            {"declared_shear_n", savedNumber(j.declared_shear_n)},
                            {"declared_breaks_at_n", savedNumber(j.declared_breaks_at_n)},
                            {"declared_stiffness_n_m", savedNumber(j.declared_stiffness_n_m)},
                            {"declared_kept", j.declared_kept},
                            {"rated_tension_n", savedNumber(j.rated_tension_n)},
                            {"rated_shear_n", savedNumber(j.rated_shear_n)},
                            {"rated_breaks_at_n", savedNumber(j.rated_breaks_at_n)},
                            {"rated_stiffness_n_m", savedNumber(j.rated_stiffness_n_m)},
                            {"capacity_fraction", savedNumber(j.capacity_fraction)},
                            {"checked_fraction", savedNumber(j.checked_fraction)},
                            {"rechecks", j.rechecks},
                            {"parted_because", j.parted_because},
                            {"parted_load_n", savedNumber(j.parted_load_n)},
                            {"parted_capacity_n", savedNumber(j.parted_capacity_n)},
                            {"member_said", j.member_said},
                            {"radius_m", savedNumber(j.radius_m)},
                            {"winds", j.winds}};
        if (j.rigid != 0 && I.world->hasJoint(j.rigid)) {
            const JoltWorld::JointReport now = I.world->jointState(j.rigid);
            o["held"] = {{"at", savedNumber(now.at)}, {"lower", savedNumber(now.lower)},
                         {"upper", savedNumber(now.upper)}};
            // A drum's tally, which what is off it is worked out from: kept as
            // it is, it comes back to the last bit.
            if (j.kind == JoltWorld::JointKind::Drum)
                o["held"]["wound_m"] = savedNumber(I.world->drumState(j.rigid).wound_m);
        }
        joints.push_back(std::move(o));
    }
    doc["joints"] = std::move(joints);

    // Stores of energy and the motors on pins (docs/machine-world.md): what a
    // battery holds and has given, and each motor's command and account, so a
    // restart gives a machine back as it stood.
    nlohmann::json energy_stores = nlohmann::json::array();
    for (const LiveEnergyStore &s : I.energy_stores)
        energy_stores.push_back({{"id", s.id},
                                 {"name", s.name},
                                 {"body", s.body},
                                 {"capacity_j", savedNumber(s.capacity_j)},
                                 {"charge_j", savedNumber(s.charge_j)},
                                 {"voltage_v", savedNumber(s.voltage_v)},
                                 {"max_power_w", savedNumber(s.max_power_w)},
                                 {"given_j", savedNumber(s.given_j)},
                                 {"taken_j", savedNumber(s.taken_j)},
                                 {"short_j", savedNumber(s.short_j)}});
    doc["energy_stores"] = std::move(energy_stores);
    nlohmann::json motors = nlohmann::json::array();
    for (const Impl::Motor &m : I.motors)
        motors.push_back({{"id", m.said.id},
                          {"joint", m.said.joint},
                          {"store", m.said.store},
                          {"stall_torque_n_m", savedNumber(m.said.stall_torque_n_m)},
                          {"no_load_rad_s", savedNumber(m.said.no_load_rad_s)},
                          {"brake_torque_n_m", savedNumber(m.said.brake_torque_n_m)},
                          {"command", savedNumber(m.said.command)},
                          {"brake", m.said.brake},
                          {"state", m.said.state},
                          {"speed_rad_s", savedNumber(m.said.speed_rad_s)},
                          {"torque_n_m", savedNumber(m.said.torque_n_m)},
                          {"current_a", savedNumber(m.said.current_a)},
                          {"power_w", savedNumber(m.said.power_w)},
                          {"turned_rad", savedNumber(m.said.turned_rad)},
                          {"work_j", savedNumber(m.said.work_j)},
                          {"heat_j", savedNumber(m.said.heat_j)},
                          {"drawn_j", savedNumber(m.said.drawn_j)},
                          {"rotor_thrust_n_per_rad2", savedNumber(m.said.rotor_thrust_n_per_rad2)},
                          {"rotor_drag_n_m_per_rad2", savedNumber(m.said.rotor_drag_n_m_per_rad2)},
                          {"air_j", savedNumber(m.said.air_j)},
                          {"friction_heat_j", savedNumber(m.said.friction_heat_j)}});
    doc["motors"] = std::move(motors);
    doc["circuits"] = nlohmann::json::parse(circuits());
    // And each machine's controller: what it was told and by whom, the counts
    // it has applied, and a stall it stopped for.
    nlohmann::json controls = nlohmann::json::array();
    for (const Impl::Control &c : I.controls) {
        nlohmann::json seen = nlohmann::json::array();
        for (const auto &[sender, count] : c.seen) seen.push_back({sender, count});
        nlohmann::json sensors = nlohmann::json::array();
        for (const LiveSensor &sensor : c.said.sensors)
            sensors.push_back({{"kind", sensor.kind}, {"body", sensor.body},
                               {"at_local_m", savedVec(sensor.at_local_m)},
                               {"depth_m", savedNumber(sensor.depth_m)}, {"stops", sensor.stops}});
        controls.push_back({{"id", c.said.id},
                            {"sensors", std::move(sensors)},
                            {"name", c.said.name},
                            {"motor", c.said.motor},
                            {"rope", c.said.rope},
                            {"top_out_m", savedNumber(c.said.top_out_m)},
                            {"bottom_out_m", savedNumber(c.said.bottom_out_m)},
                            {"forward", c.said.forward},
                            {"power", c.said.power},
                            {"direction", c.said.direction},
                            {"setting", savedNumber(c.said.setting)},
                            {"sender", c.said.sender},
                            {"seq", c.said.seq},
                            {"seen", std::move(seen)},
                            {"tripped", c.tripped},
                            {"condition", c.said.condition}});
    }
    doc["controls"] = std::move(controls);
    // And each machine's program: what it was told and by whom, what it is
    // doing and how far into it, and the frame it reads its chassis in. Only a
    // world with one says anything of programs.
    if (!I.programs.empty()) {
        nlohmann::json programs = nlohmann::json::array();
        for (const Impl::Program &p : I.programs) {
            nlohmann::json seen = nlohmann::json::array();
            for (const auto &[sender, count] : p.seen) seen.push_back({sender, count});
            nlohmann::json sensors = nlohmann::json::array();
            for (const LiveSensor &sensor : p.said.sensors)
                sensors.push_back({{"kind", sensor.kind}, {"body", sensor.body},
                                   {"at_local_m", savedVec(sensor.at_local_m)},
                                   {"depth_m", savedNumber(sensor.depth_m)}, {"side", sensor.side}});
            programs.push_back({{"id", p.said.id},
                                {"name", p.said.name},
                                {"kind", p.said.kind},
                                {"left", p.said.left},
                                {"right", p.said.right},
                                {"body", p.said.body},
                                {"setting", savedNumber(p.said.setting)},
                                {"climb_deg", savedNumber(p.said.climb_deg)},
                                {"rotors", p.said.rotors},
                                {"rotor_local", [&] {
                                     nlohmann::json out = nlohmann::json::array();
                                     for (const Vec3 &r : p.rotor_local) out.push_back(savedVec(r));
                                     return out;
                                 }()},
                                {"spins", p.spins},
                                {"hover_m", savedNumber(p.said.hover_m)},
                                {"landed_height_m", savedNumber(p.landed_height_m)},
                                {"hover_i", savedNumber(p.hover_i)},
                                {"sensors", std::move(sensors)},
                                {"forward_local", savedVec(p.forward_local)},
                                {"left_local", savedVec(p.left_local)},
                                {"power", p.said.power},
                                {"sender", p.said.sender},
                                {"seq", p.said.seq},
                                {"seen", std::move(seen)},
                                {"doing", p.said.doing},
                                {"why", p.said.why},
                                {"doing_s", savedNumber(p.said.doing_s)},
                                {"turned_deg", savedNumber(p.said.turned_deg)},
                                {"turns", p.said.turns},
                                {"rest_below", savedNumber(p.said.rest_below)},
                                {"rest_until", savedNumber(p.said.rest_until)},
                                {"rests", p.said.rests},
                                {"asked", p.said.asked},
                                {"asked_why", p.said.asked_why},
                                {"asked_by", p.said.asked_by},
                                {"asked_for_s", savedNumber(p.said.asked_for_s)},
                                {"asked_s", savedNumber(p.said.asked_s)},
                                {"asked_toward_m", savedVec(p.said.asked_toward_m)},
                                {"store", p.said.store},
                                {"turn_sign", p.turn_sign},
                                {"turn_least_deg", savedNumber(p.turn_least_deg)},
                                {"then_turn", p.then_turn},
                                {"told", p.told},
                                {"interrupted", p.interrupted},
                                {"interruptions", p.interruptions}});
        }
        doc["programs"] = std::move(programs);
        doc["next_program"] = I.next_program;
    }
    // The room's sun, and each solar panel with its account. Only a world with
    // either says anything of them.
    if (I.sun.declared && I.sun.day_s > 0.0)
        doc["sun"] = {{"day_s", savedNumber(I.sun.day_s)},
                      {"noon_elevation_deg", savedNumber(I.sun.noon_elevation_deg)},
                      {"hour_at_start", savedNumber(I.sun.hour_at_start)},
                      {"irradiance_w_m2", savedNumber(I.sun.zenith_irradiance_w_m2)}};
    else if (I.sun.declared)
        doc["sun"] = {{"elevation_deg", savedNumber(I.sun.elevation_deg)},
                      {"azimuth_deg", savedNumber(I.sun.azimuth_deg)},
                      {"irradiance_w_m2", savedNumber(I.sun.irradiance_w_m2)}};
    if (!I.panels.empty()) {
        nlohmann::json panels = nlohmann::json::array();
        for (const LiveSolarPanel &panel : I.panels)
            panels.push_back({{"id", panel.id},
                              {"name", panel.name},
                              {"body", panel.body},
                              {"store", panel.store},
                              {"at_local_m", savedVec(panel.at_local_m)},
                              {"normal_local", savedVec(panel.normal_local)},
                              {"area_m2", savedNumber(panel.area_m2)},
                              {"efficiency", savedNumber(panel.efficiency)},
                              {"sunlight_j", savedNumber(panel.sunlight_j)},
                              {"collected_j", savedNumber(panel.collected_j)},
                              {"spilled_j", savedNumber(panel.spilled_j)},
                              {"heat_j", savedNumber(panel.heat_j)}});
        doc["solar_panels"] = std::move(panels);
        doc["next_panel"] = I.next_panel;
    }
    doc["next_energy_store"] = I.next_energy_store;
    doc["next_motor"] = I.next_motor;
    doc["next_control"] = I.next_control;

    nlohmann::json blades = nlohmann::json::array();
    for (const Impl::Blade &blade : I.blades)
        blades.push_back({{"id", blade.id},
                          {"body", blade.body},
                          {"heel_local", savedVec(blade.heel_local)},
                          {"tip_local", savedVec(blade.tip_local)},
                          {"facing_local", savedVec(blade.facing_local)},
                          {"grip_local", savedVec(blade.grip_local)},
                          {"thickness_m", savedNumber(blade.thickness)},
                          {"edge_radius_m", savedNumber(blade.edge_radius)},
                          {"bevel_deg", savedNumber(blade.bevel_deg)},
                          {"cut_area_m2", savedNumber(blade.cut_area)},
                          {"cut_work_j", savedNumber(blade.cut_work)},
                          {"attached", blade.attached},
                          {"body_id", blade.body_id},
                          {"frame_nodes_b64", packedArray(blade.frame_nodes)},
                          {"frame_offsets_b64", packedVecs(blade.frame_offsets)}});
    doc["blades"] = std::move(blades);

    nlohmann::json kerfs = nlohmann::json::object();
    for (const auto &[name, list] : I.kerfs) {
        nlohmann::json cut = nlohmann::json::array();
        for (const Impl::Kerf &kerf : list) {
            nlohmann::json swept = nlohmann::json::array();
            for (const auto &[strip, spans] : kerf.swept) {
                nlohmann::json each = nlohmann::json::array();
                for (const auto &span : spans)
                    each.push_back(nlohmann::json::array({savedNumber(span.first), savedNumber(span.second)}));
                swept.push_back(nlohmann::json::array({strip, std::move(each)}));
            }
            cut.push_back({{"blade", kerf.blade},
                           {"origin", savedVec(kerf.origin)},
                           {"u", savedVec(kerf.u)},
                           {"v", savedVec(kerf.v)},
                           {"w", savedVec(kerf.w)},
                           {"strip", savedNumber(kerf.strip)},
                           {"half_width", savedNumber(kerf.half_width)},
                           {"swept", std::move(swept)}});
        }
        kerfs[name] = std::move(cut);
    }
    doc["kerfs"] = std::move(kerfs);

    nlohmann::json points = nlohmann::json::array();
    for (const ToolTerrain::SavedPoint &p : I.tools.saved())
        points.push_back({{"id", p.id},
                          {"body", p.body},
                          {"tip_local", savedVec(p.tip_local)},
                          {"pointing_local", savedVec(p.pointing_local)},
                          {"grip_local", savedVec(p.grip_local)},
                          {"width_local", savedVec(p.width_local)},
                          {"width_m", savedNumber(p.shape.width_m)},
                          {"thickness_m", savedNumber(p.shape.thickness_m)},
                          {"angle_deg", savedNumber(p.shape.angle_deg)},
                          {"length_m", savedNumber(p.shape.length_m)},
                          {"body_id", p.body_id},
                          {"frame_nodes_b64", packedArray(p.frame_nodes)},
                          {"frame_offsets_b64", packedVecs(p.frame_offsets)},
                          {"attached", p.attached}});
    doc["tool_points"] = std::move(points);

    const bool holding = I.holding != static_cast<std::size_t>(-1) && I.holding < I.described.size();
    doc["hand"] = {{"holding", holding ? I.described[I.holding].name : std::string{}},
                   {"wielding", holding && I.wielding},
                   {"grip_local_m", savedVec(I.grip_local)},
                   {"held_at_m", savedVec(I.held_at)},
                   {"held_facing_wxyz", savedQuat(I.held_facing)},
                   {"strength_n", savedNumber(I.hand_strength_n)},
                   {"torque_n_m", savedNumber(I.hand_torque_n_m)},
                   {"mass_kg", savedNumber(I.hand_mass_kg)},
                   {"work_j", savedNumber(I.hand_work_j)}};
    // The water as it stands, for the scene's own "water": {"state": ...}.
    if (I.environment) {
        doc["ground"] = nlohmann::json::parse(I.environment->groundStateJson());
        const nlohmann::json water = nlohmann::json::parse(I.environment->stateJson(), nullptr, false);
        if (water.is_object() && water.contains("depth_b64")) doc["water"] = water;
    }
    // Reference geometry and its cached thermal strength belong to the same
    // physical state. Restoring only the shrunken collision box burns it twice.
    nlohmann::json geometry = nlohmann::json::object();
    for (std::size_t i = 0; i < I.described.size(); ++i) {
        const auto found = I.matter_of.find(I.described[i].name);
        if (found == I.matter_of.end()) continue;
        const auto &m = found->second;
        nlohmann::json entry;
        entry["applied_m"] = savedNumber(m.applied_m);
        entry["remaining_volume_m3"] = savedNumber(m.remaining_volume_m3);
        entry["bond_tension_min"] = savedNumber(m.bond_tension_min);
        entry["bond_tension_mean"] = savedNumber(m.bond_tension_mean);
        entry["bond_stiffness_mean"] = savedNumber(m.bond_stiffness_mean);
        entry["seen_consumed_m"] = savedNumber(m.seen_consumed_m);
        entry["reference_inferred"] = m.reference_inferred;
        entry["round"] = m.round;
        entry["revision"] = m.revision;
        entry["cells_burned"] = m.cells_burned;
        entry["seen_cells"] = m.seen_cells;
        entry["limits_heated"] = m.limits_heated;
        entry["box_m"] = savedVec(m.box_m);
        entry["centre_m"] = savedVec(m.centre_m);
        entry["turn"] = savedQuat(m.turn);
        entry["seen_surface"]["stiffness"] = savedNumber(m.seen_surface.stiffness);
        entry["seen_surface"]["tension"] = savedNumber(m.seen_surface.tension);
        entry["seen_surface"]["compression"] = savedNumber(m.seen_surface.compression);
        entry["seen_surface"]["shear"] = savedNumber(m.seen_surface.shear);
        entry["seen_core"]["stiffness"] = savedNumber(m.seen_core.stiffness);
        entry["seen_core"]["tension"] = savedNumber(m.seen_core.tension);
        entry["seen_core"]["compression"] = savedNumber(m.seen_core.compression);
        entry["seen_core"]["shear"] = savedNumber(m.seen_core.shear);
        entry["limits"]["minimum_removal_stretch"] = savedNumber(I.limits_of[i].minimum_removal_stretch);
        entry["limits"]["minimum_removal_energy_j"] = savedNumber(I.limits_of[i].minimum_removal_energy_j);
        entry["limits"]["yield_stretch"] = savedNumber(I.limits_of[i].yield_stretch);
        entry["limits"]["bar_wave_speed_m_s"] = savedNumber(I.limits_of[i].bar_wave_speed_m_s);
        entry["limits"]["acoustic_impedance_pa_s_m"] = savedNumber(I.limits_of[i].acoustic_impedance_pa_s_m);
        entry["limits"]["live_bonds"] = I.limits_of[i].live_bonds;
        entry["limits"]["cells"] = I.limits_of[i].cells;
        entry["impedance"] = savedNumber(I.impedance_of[i]);
        geometry[I.described[i].name] = std::move(entry);
    }
    doc["material_geometry"] = {{"schema", "banjo.material-geometry.v1"}, {"records", std::move(geometry)}};
    // What the thermal network holds for each body, for a world carried into
    // this scene once it has changed: the heat of each thing that comes back
    // comes back with it. Identical-scene restores also retain the complete network.
    if (I.thermo) {
        const thermo::ThermoState &state = I.thermo->state();
        nlohmann::json lumps = nlohmann::json::array();
        for (const thermo::Lump &lump : state.lumps) lumps.push_back(savedLump(lump, state));
        doc["heat"] = {{"substances", I.thermo->model().size()},
                       {"model", {{"id", I.thermo->model().id}, {"version", I.thermo->model().version}}},
                       {"lumps", std::move(lumps)},
                       {"network", savedThermoState(state)},
                       {"scene_settings", thermalSettings(I.request.thermo_scene_json)}};
    }
    // A snapshot's old descriptive not_kept list is not enough for a caller
    // that promises an atomic changed-scene carry: a heater scheduled but not
    // yet stepped has heater_w == 0 in its body's report. Expose whether state
    // omitted by the carry adapter ACTUALLY exists, without mutating it.
    std::size_t pending_heaters = 0;
    std::size_t gas_regions = 0;
    if (I.thermo) {
        const thermo::ThermoState &state = I.thermo->state();
        gas_regions = state.regions.size();
        for (const thermo::Heater &heater : state.heaters)
            if (heater.what.power_w != 0.0 &&
                heater.what.start_s + heater.what.seconds > state.time_s)
                ++pending_heaters;
    }
    doc["carry_readiness"] = {{"schema", "banjo.carry-readiness.v1"},
                              {"precise_rigid_version", 1},
                              {"thermal_network_version", 1},
                              {"pending_heaters", pending_heaters},
                              {"gas_regions", gas_regions}};
    doc["not_kept"] = notKept();
    return doc.dump();
}

std::unique_ptr<LiveWorld> LiveWorld::open(const TileImpactRequest &request, const std::string &snapshot) {
    const bool exact_required = !request.precise_rigid_scene_json.empty() || snapshot.find("precise-rigid-v1") != std::string::npos;
    Saved saved;
    try {
        saved.doc = nlohmann::json::parse(snapshot);
        if (!saved.doc.is_object() || saved.doc.value("format", std::string{}) != kWorldFormat)
            throw std::invalid_argument("it is not a saved world this engine reads");
    } catch (const std::exception &error) {
        if (exact_required) throw;
        std::unique_ptr<LiveWorld> live = openFrom(request, nullptr);
        LiveRestore said;
        said.tier = "none";
        said.why = std::string("the saved world could not be read: ") + error.what();
        said.not_kept = notKept();
        live->impl_->restored = std::move(said);
        return live;
    }
    std::string why;
    try {
        return openFrom(request, &saved);
    } catch (const SavedWorldMismatch &mismatch) {
        if (exact_required || saved.doc.contains("ground")) throw;
        why = mismatch.what();
    } catch (const std::exception &error) {
        if (exact_required || saved.doc.contains("ground")) throw;
        why = std::string("the saved world could not be put back: ") + error.what();
    }
    std::unique_ptr<LiveWorld> live = openFrom(request, nullptr);
    live->placeWhereLeft(saved, why);
    return live;
}

std::unique_ptr<LiveWorld> LiveWorld::open(const TileImpactRequest &request, const std::string &snapshot,
                                           const LiveCarry &carry) {
    const bool exact_required = !request.precise_rigid_scene_json.empty() || snapshot.find("precise-rigid-v1") != std::string::npos;
    Saved saved;
    try {
        saved.doc = nlohmann::json::parse(snapshot);
        if (!saved.doc.is_object() || saved.doc.value("format", std::string{}) != kWorldFormat)
            throw std::invalid_argument("it is not a saved world this engine reads");
    } catch (const std::exception &error) {
        if (exact_required) throw;
        std::unique_ptr<LiveWorld> live = openFrom(request, nullptr);
        LiveRestore said;
        said.tier = "none";
        said.why = std::string("the saved world could not be read: ") + error.what();
        said.not_kept = notCarried();
        live->impl_->restored = std::move(said);
        return live;
    }
    try {
        return openFrom(request, &saved, &carry);
    } catch (const std::exception &error) {
        if (exact_required || (carry.ground && saved.doc.contains("ground"))) throw;
        // Nothing half carried: the scene as it is, and why.
        std::unique_ptr<LiveWorld> live = openFrom(request, nullptr);
        LiveRestore said;
        said.tier = "none";
        said.why = std::string("the saved world could not be carried into this room: ") + error.what();
        said.not_kept = notCarried();
        live->impl_->restored = std::move(said);
        return live;
    }
}

LiveCarry LiveWorld::carryAll(const std::string &snapshot) {
    LiveCarry all;
    const nlohmann::json doc = nlohmann::json::parse(snapshot, nullptr, false);
    if (!doc.is_object()) return all;
    const auto ids = [&doc](const char *key, std::set<unsigned> &into) {
        if (!doc.contains(key) || !doc.at(key).is_array()) return;
        for (const nlohmann::json &entry : doc.at(key))
            if (entry.is_object() && entry.contains("id")) into.insert(entry.at("id").get<unsigned>());
    };
    ids("joints", all.joints);
    ids("energy_stores", all.energy_stores);
    ids("motors", all.motors);
    ids("controls", all.controls);
    ids("programs", all.programs);
    ids("solar_panels", all.solar_panels);
    ids("blades", all.blades);
    ids("tool_points", all.tool_points);
    return all;
}

void LiveWorld::placeWhereLeft(const Saved &saved, const std::string &why) {
    LiveRestore said;
    said.tier = "none";
    said.why = why;
    said.not_kept = notKept();
    bool read = true;
    try {
        if (saved.doc.contains("t_s")) said.saved_t_s = numberFrom(saved.doc.at("t_s"));
    } catch (const std::exception &) {
        read = false;
    }
    if (read) said.bodies = putBackWhereLeft(saved).size();
    if (said.bodies > 0) said.tier = "poses";
    impl_->restored = std::move(said);
}

std::vector<std::string> LiveWorld::putBackWhereLeft(const Saved &saved, const std::set<std::string> *only) {
    Impl &I = *impl_;
    std::vector<std::string> put;
    try {
        const nlohmann::json &doc = saved.doc;
        // What cannot be put back on its own: a thing on a joint, or carrying
        // an edge or a point, which the scene declares against where it was
        // authored.
        std::set<std::string> held_by_something;
        for (const nlohmann::json &j : doc.value("joints", nlohmann::json::array())) {
            held_by_something.insert(j.value("a", std::string{}));
            held_by_something.insert(j.value("b", std::string{}));
        }
        for (const nlohmann::json &b : doc.value("blades", nlohmann::json::array()))
            held_by_something.insert(b.value("body", std::string{}));
        for (const nlohmann::json &p : doc.value("tool_points", nlohmann::json::array()))
            held_by_something.insert(p.value("body", std::string{}));
        for (const nlohmann::json &b : doc.at("bodies")) {
            const std::string name = b.value("name", std::string{});
            if (name.empty() || held_by_something.count(name) != 0 || b.contains("parked") || !b.contains("pose"))
                continue;
            if (only != nullptr && only->count(name) == 0) continue;
            // Still whole and its authored self: not a piece, never dented or
            // reshaped, not scenery.
            if (b.value("fragment", false) || b.value("anchored", false) || b.value("revision", 0U) != 0) continue;
            if (b.contains("dent_m") && numberFrom(b.at("dent_m")) > 0.0) continue;
            const auto found = I.index_of.find(name);
            if (found == I.index_of.end()) continue;
            const std::size_t i = found->second;
            const LiveBodyPose &d = I.described[i];
            if (d.fragment || d.anchored || d.shape != b.value("shape", std::string{}) || !I.inWorld(i)) continue;
            if (b.contains("nodes_b64") && unpackedArray<std::uint32_t>(b, "nodes_b64").size() != I.nodes_of[i].size())
                continue;
            I.world->applyRigidState(I.body_of[i], rigidFrom(b.at("pose")));
            if (!b.value("awake", true)) I.world->sleep(I.body_of[i]);
            put.push_back(name);
        }
    } catch (const std::exception &) {
        // What could be put back was; the rest is where the scene has it.
    }
    return put;
}

} // namespace banjo::fastlattice
