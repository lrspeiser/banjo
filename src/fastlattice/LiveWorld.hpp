#pragma once

#include "fastlattice/TileImpactScene.hpp"

#include <memory>
#include <string>
#include <vector>

namespace banjo::fastlattice {

// Where one object is, under the name the request gave it.
struct LiveBodyPose {
    std::string name;
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
struct LiveImpact {
    std::string struck;              // the object that took the hit
    std::string by;                  // what hit it, or "the ground"
    double closing_speed_m_s{};
    double threshold_speed_m_s{};    // what it would take to break `struck`
    double energy_j{};
    bool would_break{};
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
    [[nodiscard]] std::vector<LiveBodyPose> poses() const;

    // What happened in the step just taken. Cleared by the next step, so a host
    // reads it once per frame and narrates it. Contacts too gentle to be worth
    // mentioning are left out: `quiet_speed_m_s` is what counts as an arrival
    // rather than two things leaning on each other.
    [[nodiscard]] std::vector<LiveImpact> impacts(double quiet_speed_m_s = 0.5) const;

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

private:
    LiveWorld();
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace banjo::fastlattice
