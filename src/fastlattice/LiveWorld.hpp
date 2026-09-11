#pragma once

#include "fastlattice/TileImpactScene.hpp"

#include <memory>
#include <string>
#include <vector>

namespace banjo::fastlattice {

// Where one object is, under the name the request gave it.
struct LiveBodyPose {
    std::string name;
    // What it is made of, by its common name -- "oak", "alumina ceramic". A
    // host showing someone an object has to be able to say what it is, and
    // working it back from the name is guesswork the moment something breaks:
    // "glass plate piece 7" only looks like glass because of how it was named.
    std::string material;
    // "box" and "sphere" are the shape that was asked for and are drawn exactly.
    // "hull" is a piece that broke off something, whose cells are its real
    // surface -- there is no primitive for it and the host draws its cells.
    std::string shape{"hull"};
    Vec3 dimensions_m{};
    std::uint32_t color_rgba{};
    Vec3 position_m{};
    double orientation_wxyz[4]{1.0, 0.0, 0.0, 0.0};
    Vec3 velocity_m_s{};
    bool anchored{};
    bool held{};
    // Where this body's cells sit in its own frame. Only filled in when the
    // caller asks for geometry, because it does not change between steps and a
    // bowl has two thousand of them.
    //
    // A body authored as one box or sphere is drawn as that shape and needs
    // none of this. Everything else -- a join, whose union no primitive
    // describes, and a piece that broke off something, whose cells ARE its
    // surface -- has to be drawn as its cells or it is drawn as a lie: a
    // hollow bowl rendered from its bounding box is a solid block.
    std::vector<Vec3> cells_local_m;
};

// One contact from the step just taken, judged against what the struck object
// can actually take.
//
// The verdict is not a guess. `would_break` is the refracture admission test:
// two necessary conditions, stress and energy, derived in Refracture.hpp from
// the acoustic impedances of the two bodies and the smallest removal threshold
// any live bond in the struck one carries. A contact that fails either cannot
// break anything, and one that passes is a contact the lattice has to be run on
// to find out what it did.
// What a ray met, named the way the scene names things.
struct LivePick {
    bool hit{};
    // Empty when the ray stopped on something that is not one of the scene's
    // bodies -- the ground. "It hit the floor" and "it hit nothing" are
    // different answers and a pointer has to tell them apart.
    std::string name;
    double distance_m{};
    Vec3 point_world_m{};
};

struct LiveImpact {
    std::string struck;              // the object that took the hit
    std::string by;                  // what hit it, or "the ground"
    double closing_speed_m_s{};
    double threshold_speed_m_s{};    // what it would take to break `struck`
    // What it would take to leave a mark on it: the speed below which nothing
    // can take a permanent set. Infinite for a brittle material, which has no
    // yield point and goes from elastic straight to broken.
    //
    // Almost always the lower of the two, and the gap between them is where
    // real damage lives: iron yields in compression at 200 MPa and crushes at
    // 600, so most of what happens to an iron thing happens in between.
    double dent_speed_m_s{};
    double energy_j{};
    bool would_break{};
    bool would_dent{};
};

// What the lattice actually did when it was run. The bounds above say what is
// POSSIBLE; only running it says what happened.
enum class LiveOutcome : std::uint8_t {
    Nothing = 0,   // asked about something that is not there, or cannot be run
    Held = 1,      // it took the hit and is the shape it was
    Dented = 2,    // still one piece, and no longer the shape it was
    Broke = 3,     // it came apart
};

// A scene that keeps running instead of being run.
//
// runTileImpact is a batch: build, fracture, hand off, settle, write a
// recording, return. Everything it knows dies with the call, which is why the
// playground plays a film rather than a world -- to move something you have to
// edit the scene and run the whole thing again.
//
// This holds the rigid world open instead. A host steps it a frame at a time,
// reads where everything is, and can take hold of an object and move it. The
// rigid phase is already far faster than realtime (0.146 s of wall for 4.000 s
// of scene on a four-object ramp, 27x faster than it needs to be), so the
// limit here is not the physics.
//
// It starts intact and stays intact: no lattice phase runs, because nothing has
// been struck yet. A live world currently moves, collides and settles, and
// breaks nothing. Fracture on demand -- re-entering the lattice when a contact
// is hard enough to matter -- is the piece that is still missing, and the
// contact ledger is the trigger it will use.
class LiveWorld {
public:
    // Throws if the scene cannot be built, exactly as the batch lane would.
    [[nodiscard]] static std::unique_ptr<LiveWorld> open(const TileImpactRequest &request);
    ~LiveWorld();
    LiveWorld(const LiveWorld &) = delete;
    LiveWorld &operator=(const LiveWorld &) = delete;

    // Advance by one fixed step. A host calls this at whatever rate it draws.
    void step(double dt_s);
    [[nodiscard]] double time_s() const;
    [[nodiscard]] std::size_t bodies() const;

    // Every object, in the order they were authored.
    // `with_geometry` fills in cells_local_m for the bodies that need it. It is
    // static between steps, so a host asks for it when the set of bodies
    // changes and not on every frame.
    [[nodiscard]] std::vector<LiveBodyPose> poses(bool with_geometry = false) const;
    [[nodiscard]] double cellSize() const;

    // What happened in the step just taken. Cleared by the next step, so a host
    // reads it once per frame and narrates it. Contacts too gentle to be worth
    // mentioning are left out: `quiet_speed_m_s` is what counts as an arrival
    // rather than two things leaning on each other.
    [[nodiscard]] std::vector<LiveImpact> impacts(double quiet_speed_m_s = 0.5) const;

    // What the last step hit hard enough to break, by name and once each.
    [[nodiscard]] std::vector<std::string> breakable() const;

    // True when the last step was taken back because it would have broken
    // something. The world is one step short of that impact and the clock has
    // not moved, so a host that is drawing frames knows not to draw one, and
    // knows the next thing to do is decide whether to pay for the fracture.
    [[nodiscard]] bool steppedBack() const;

    // Put one object back into the lattice for `window_s` of simulated time and
    // replace it with whatever it became. Returns how many pieces it is now:
    // 1 means it took the hit and held.
    //
    // This is deliberately NOT automatic inside step(). A step costs about two
    // microseconds; this costs roughly the object's cell count times a third of
    // a millisecond, so a 500-cell object is about 165 ms and a 5,000-cell one
    // about 1.6 s. A host has to decide when to pay that -- on a worker, over a
    // held frame, or not at all -- and hiding it inside step() would take the
    // choice away and make a frame budget meaningless.
    //
    // The window is short because it can be: removed energy settles five to ten
    // times sooner than the piece count, and 3 ms covers it.
    std::size_t fracture(const std::string &name, double window_s = 0.003);
    // What the last fracture() call turned out to be. The return value counts
    // pieces, which cannot tell "held exactly as it was" from "held, but bent
    // out of shape" -- both are one piece.
    [[nodiscard]] LiveOutcome lastOutcome() const;
    // Let this contact pass. The world can move again without anything being
    // put back into the lattice.
    //
    // A step that would break something is taken back and time stops until the
    // host answers. Answering is what matters, not which way: a host that only
    // ever calls fracture has no way to say "not this one" and, if it says
    // nothing at all, the same contact is judged again on the next step and
    // taken back again, for ever.
    void declineBreak(const std::string &name);

    // Taking hold of something. A held body is pinned out of the simulation --
    // gravity and contacts stop moving it -- and goes exactly where it is put,
    // which is what makes dragging feel like holding rather than pushing.
    // Anchored scenery refuses to be picked up; it is the world, not a prop.
    [[nodiscard]] bool grab(const std::string &name);
    void moveHeld(const Vec3 &to_world_m);
    // Let go. The object rejoins the simulation from rest, so it falls from
    // where it was left rather than carrying the hand's speed.
    void release();
    [[nodiscard]] std::string held() const;
    // What is under a ray: the same question the solver answers, so a pointer
    // agrees with the physics instead of with a second copy of the shapes.
    // Costs no step; safe to ask every frame.
    [[nodiscard]] LivePick pick(const Vec3 &from_world_m,const Vec3 &direction,
                                double max_distance_m = 1000.0) const;

private:
    LiveWorld();
    // Reads the contacts of the step just taken and answers whether any of them
    // could break what it hit. Called inside a reversible trial, so it must not
    // change the world.
    [[nodiscard]] bool judgeStep();
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace banjo::fastlattice
