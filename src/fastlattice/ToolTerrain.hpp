#pragma once

// Tools that work the ground: the tool-terrain process (docs/ground-work.md).
//
// A pick swung into soil is not a dig with a pick-shaped name. Its point goes
// into the ground as far as its own momentum and the hand's push drive it
// against what the soil resists with, and a pry breaks out as much ground as
// the soil gives -- and only then is the terrain changed, through the ground's
// own dig, so what came loose is carried like anything else dug.
//
// This holds the points declared on bodies and each point's meeting with the
// ground, and runs in the two halves of a step the cutting model runs in
// (LiveWorld::step). Before it: a point about to go in, or already in, gets
// its bite (JoltWorld::addGroundBite) set from ground-work-v1 at the depth it
// has reached, the ground's contact with the point is left to the bite, and
// the rest of the tool keeps meeting the ground as the surface it is. After
// it: what the bite took is read back as work, and a point that has come out
// takes the ground it broke out with it.
//
// It never decides anything the solver does. It sets what the ground resists
// with; the solver decides whether the tool overcomes it.
#include "fastlattice/LiveWorld.hpp"
#include "terrain/GroundWork.hpp"

#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace banjo {
class JoltWorld;
struct MaterialDefinition;
}

namespace banjo::fastlattice {

// What the process needs from the world it is part of: handed over at each
// call, and kept by none of them.
struct ToolTerrainHost {
    JoltWorld *world{};
    terrain::Environment *environment{};   // null: no ground, only the flat floor
    double floor_y{};                      // that floor, where there is no ground
    double cell_m{};
    double time_s{};
    std::function<std::optional<MatterBodyId>(const std::string &)> id_of;
    // A body's cells: node number, and its centre in the body's own frame.
    std::function<std::vector<std::pair<std::uint32_t, Vec3>>(const std::string &)> cells_of;
    std::function<const MaterialDefinition *(const std::string &)> material_of;
    std::function<std::string(const std::string &)> material_name_of;
    std::function<double(const std::string &)> dent_of;
    std::function<bool(const std::string &)> anchored;
    // A body set aside (LiveWorld::park): out of the world, and not gone. Its
    // points are left as they are while it is away -- not finished, not
    // detached -- and work again when it comes back.
    std::function<bool(const std::string &)> parked;
};

class ToolTerrain {
public:
    // Declare a point on a body (LiveWorld::toolPoint). 0 and the reason when
    // it cannot be one.
    unsigned declare(const ToolTerrainHost &host, const std::string &body, const Vec3 &tip_world_m,
                     const Vec3 &pointing_world, const terrain::ToolPointShape &shape,
                     const Vec3 &grip_world_m, std::string &why);
    [[nodiscard]] std::vector<LiveToolPoint> points(const ToolTerrainHost &host) const;
    // Before the step's reversible trial, and outside it: bites made, set and
    // taken away, and the ground's contact with a point suspended or restored.
    void prepare(const ToolTerrainHost &host, double dt_s);
    // After a step the world accepted: the work the bites did, and a point
    // that has come out takes out what it broke loose.
    void settle(const ToolTerrainHost &host, double dt_s);
    [[nodiscard]] const std::vector<LiveGroundWork> &reports() const { return log_; }
    // Drop the meetings that are over; the open ones stay.
    void forget();
    // Whether a point on this body is in the ground, held there by its bite.
    [[nodiscard]] bool inGround(const std::string &body) const;
    // A body about to be set aside (LiveWorld::park) leaves the ground it was
    // on: a meeting held open while its point stayed on that ground is over,
    // and is closed now, while the tool is still here to be looked at.
    void setAside(const ToolTerrainHost &host, const std::string &body);
    // The motion of a bounded tool action (LiveStrike), for the hand to make.
    [[nodiscard]] std::optional<LiveStroke> plan(const ToolTerrainHost &host, const LiveStrike &strike,
                                                 const std::string &held, const Vec3 &grip_local,
                                                 std::string &why) const;
    [[nodiscard]] bool empty() const { return points_.empty(); }

    // A point as a saved world keeps it (LiveWorld::snapshot): what it is and
    // where it sits in its body's own frame. Not what only a meeting with the
    // ground has -- a world is not saved while a point is in the ground -- and
    // not whether its body has been made to collide as its cells yet, which a
    // body made again has not: the next step does that, as it does for a new
    // point.
    struct SavedPoint {
        unsigned id{};
        std::string body;
        Vec3 tip_local{}, pointing_local{}, grip_local{}, width_local{};
        terrain::ToolPointShape shape;
        MatterBodyId body_id{kInvalidMatterBodyId};
        std::vector<std::uint32_t> frame_nodes;
        std::vector<Vec3> frame_offsets;
        bool attached{true};
    };
    [[nodiscard]] std::vector<SavedPoint> saved() const;
    [[nodiscard]] unsigned nextId() const { return next_; }
    // Replaces every point with these, and the next id with `next`. Its log of
    // meetings starts empty.
    void restore(const std::vector<SavedPoint> &points, unsigned next);

private:
    static constexpr std::size_t kNone = static_cast<std::size_t>(-1);
    struct Point {
        unsigned id{};
        std::string body;
        // In the body's own frame, about its centre of mass.
        Vec3 tip_local{}, pointing_local{}, grip_local{}, width_local{};
        terrain::ToolPointShape shape;
        // The rigid body that frame belongs to, and the body's cells as they
        // sat in it: a body that comes through a fracture whole is put back in
        // a new frame, and the point follows its own matter into it.
        MatterBodyId body_id{kInvalidMatterBodyId};
        std::vector<std::uint32_t> frame_nodes;
        std::vector<Vec3> frame_offsets;
        bool shaped{};
        bool attached{true};
        // In the ground: the bite, where the point went in and along what.
        unsigned joint{};
        Vec3 entry{}, axis{}, across_x{}, across_z{};
        std::size_t column{};
        double deepest{}, sideways{};
        Vec3 pry{};          // the sideways motion in the ground, added up
        bool broke_out{};
        bool at_rock{};
        std::string ground;  // the layer the tip is in
        // As the step began, for what the step did.
        Vec3 tip_before{};
        double vn_before{}, vx_before{}, vz_before{};
        std::size_t report{kNone};
        // A meeting that is not a bite -- stopped, glanced, not supported --
        // held open while the point stays on that ground.
        std::size_t note{kNone};
        std::string note_kind;
    };
    std::vector<Point> points_;
    std::vector<LiveGroundWork> log_;
    unsigned next_{1};

    void follow(const ToolTerrainHost &host, Point &p, MatterBodyId now);
    void shape(const ToolTerrainHost &host, Point &p, MatterBodyId id);
    void meet(const ToolTerrainHost &host, Point &p, MatterBodyId id, const RigidSnapshot &s,
              const Vec3 &tip, const Vec3 &a, const Vec3 &v, double dt_s);
    void holdIn(const ToolTerrainHost &host, Point &p, MatterBodyId id, const Vec3 &tip, const Vec3 &v,
                double dt_s);
    void suspend(const ToolTerrainHost &host, const Point &p, MatterBodyId id, const Vec3 &v, double dt_s);
    void finish(const ToolTerrainHost &host, Point &p, bool tool_here);
    void note(const ToolTerrainHost &host, Point &p, const std::string &kind, const std::string &ground,
              const std::string &why, bool supported, const Vec3 &at, double closing);
    void closeNote(const ToolTerrainHost &host, Point &p);
    void condition(const ToolTerrainHost &host, LiveGroundWork &r, const Point &p) const;
    // What the ground resists the point with over this step, going in and
    // sideways: from ground-work-v1 at the depth it is at, and -- going in --
    // averaged over the depth it can reach this step.
    struct Resistance {
        double into{}, x{}, z{};
    };
    [[nodiscard]] Resistance resistance(const Point &p, const terrain::GroundMaterial &ground,
                                        double depth_m, double closing_m_s, double dt_s) const;
    [[nodiscard]] double leadingWidth(const Point &p) const;
    [[nodiscard]] double loosened(const ToolTerrainHost &host, const Point &p) const;
};

} // namespace banjo::fastlattice
