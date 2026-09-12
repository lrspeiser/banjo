#pragma once

#include "fastlattice/TileImpactScene.hpp"
#include "thermo/ThermoWorld.hpp"

#include <memory>
#include <set>
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
    // Whether this came OFF something, rather than being what it always was.
    //
    // A shape of "hull" is not the same question. A thing that bends takes a
    // permanent set and is rebuilt from where its matter ended up, which makes
    // it a hull too -- but it is still the same object, in a new shape, and
    // nobody expects to pocket it by walking past. A dented iron ball weighs
    // three and a half kilograms and had gone into somebody's pockets as
    // "debris" before this existed.
    bool fragment{};
    // The deepest permanent set this body carries, and where it is in the
    // body's own frame. Zero for anything that has never been dented.
    //
    // A dent is real and it is SMALL. An iron ball hammered into an anvil takes
    // a permanent set of about a fifth of a millimetre on a 120 mm ball -- so
    // the shape barely changes, and rebuilding it out of its cells to "show"
    // that threw away a smooth sphere in exchange for a 136-cube staircase that
    // displays no dent at all, because the cells had moved 90 micrometres.
    //
    // So the number travels instead. A host can draw the shape it was and mark
    // the spot, and say a true depth next to it.
    double dent_m{};
    Vec3 dent_at_m{};
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

// A pin two named things turn about, as the scene sees it.
//
// The engine's hinge is between two bodies. This is between two NAMES, which is
// a different thing and the reason this layer exists: bodies do not survive
// breaking. Everything in an island is destroyed and rebuilt when anything in
// it comes apart, so a hinge made against a body id is a hinge that lasts until
// the first hard knock -- and a constraint holding a body that no longer exists
// is not a bug that misbehaves, it is one that crashes.
//
// So a scene joint is remembered as: two names, and where the pin sits in each
// body's OWN frame. The body-local part is what makes it survive: the whole
// assembly can be picked up, carried, turned upside down, and the pin is still
// in the same place in the wood, because that is how it was written down.
struct LiveJoint {
    unsigned id{};
    // "hinge" -- a pin two things turn about.
    // "slider" -- a line two things move along.
    // "link"   -- one link of a rope or chain: it pulls, and it does not push.
    // "pulley" -- a rope rove over two fixed points: pull one end, the other
    //             comes up. The IDEAL pulley -- a cable-length relationship,
    //             not a wheel with a rope wrapped round it.
    // "fixing" -- two things held together as one: a peg, a bracket, a catch, a
    //             locking bar. It has a strength along its axis and another
    //             across it, and either one exceeded parts it.
    // "elastic"-- something that stores energy by being stretched or squashed: a
    //             bow limb, a spring, a bent plank. It pushes as well as pulls,
    //             which is what tells it from a rope.
    //
    // This is also the unit on the three numbers below, because a joint with
    // one degree of freedom has one number and the only question is what it is
    // measured in: radians and newton metres for a pin, metres and newtons for
    // a slide.
    std::string kind{"hinge"};
    std::string a, b;
    // Where it has got to, from where it was made.
    double at{};
    double lower{}, upper{};
    double friction{};
    // What a link or a pulley is carrying, in newtons. Zero for slack, and
    // zero for a pin or a slide, which have no tension in any useful sense.
    double tension_n{};
    // For a fixing: what it is carrying along its axis and across it, and what
    // it can take of each. A peg pulled straight out and a peg sheared sideways
    // fail at different loads, so they are two numbers and not one.
    double tension_n_now{}, shear_n_now{};
    double holds_tension_n{}, holds_shear_n{};
    // For an elastic: the declared linear model, and what it currently holds.
    //
    //     force_n  = stiffness_n_m * (at - rest_m)
    //     stored_j = stiffness_n_m * (at - rest_m)^2 / 2
    //
    // Both are the MODEL's numbers rather than something measured out of the
    // solver, because the model is what was declared -- and whether the solver
    // actually delivers them is the thing the tests check, by comparing the
    // work put in against the kinetic energy that comes out.
    double rest_m{}, stiffness_n_m{}, damping_n_s_m{};
    double force_n{}, stored_j{};
    // A pulley's mechanical advantage. One for everything else.
    double ratio{1.0};
    // Where a pulley's rope runs over, in world metres. Both zero for every
    // other kind, which has nothing of the sort.
    Vec3 over_a_m{}, over_b_m{};
    // What it takes to part a link. Zero means it never parts.
    double breaks_at_n{};
    // Where it is now, in the world, for a host that wants to draw it. For a
    // slide, the point is where the travel is measured FROM -- where the thing
    // was built -- not where it has got to.
    Vec3 point_world_m{};
    Vec3 axis_world{};
    // True while both ends are real and the pin is doing its job. A joint whose
    // wood was smashed away is reported once, gone, rather than silently
    // vanishing from the list -- a host that drew a gate wants to know the gate
    // came off its hinges.
    bool attached{true};
};

// A thing carrying more than it can hold up.
//
// This is the OTHER way something breaks here, and it exists because the first
// way cannot see it. Every other break in this engine starts from a blow: a
// closing speed, an impedance, an energy. A shelf with too much stacked on it
// is not struck by anything at all -- measured, a plank bridging two piers with
// an iron block sitting on it reports NO contacts whatsoever once everything
// has come to rest, because the contact ledger is a ledger of impacts. Load it
// until it should snap and nothing would ever ask.
//
// So this is asked separately, from statics rather than from dynamics: what is
// resting on it, how far apart the things holding it up are, and what bending
// that puts in it.
//
//     a simply supported beam, span L, section b x d
//     carrying a point load W in the middle and its own weight w per metre
//
//     stress  =  3 W L / (2 b d^2)  +  3 w L^2 / (4 b d^2)
//
// Like every other bound in this engine, `stress_pa` past `strength_pa` is
// NECESSARY AND NOT SUFFICIENT: it says the lattice is worth running, not that
// the thing is going to come apart. The beam formula assumes the load is in the
// middle and the ends are free to rotate, which is the worst case for both, so
// it errs towards asking.
struct LiveOverload {
    std::string name;
    // What is stacked on it, in newtons, not counting its own weight.
    double carrying_n{};
    // How far apart the things holding it up are. A beam held everywhere along
    // its length has no span and cannot be bent -- which is why a plate lying
    // flat on the floor will not break however hard it is loaded.
    double span_m{};
    // What that works out to, and what the material can take.
    double stress_pa{};
    double strength_pa{};
};

// A moment where the world was made to wait, or was saved from waiting.
//
// Working out a fracture costs between a third of a second and a second, and
// that is irreducible -- every way of making the run shorter was measured and
// every one of them changes the answer. So the only thing left is to not make
// anyone wait for it, and the only way to know whether that is working is to
// write down every time it happens.
// What a sweep picked up, added up by material rather than by shard: nobody
// wants forty entries called "glass plate 20mm piece 31", they want to know they
// now have four hundred grams of glass.
struct LiveCollected {
    std::string material;
    double kilograms{};
    std::size_t pieces{};
    std::size_t cells{};
    // Which bodies went, so a host can show them going rather than have them
    // blink out of existence between one frame and the next.
    std::vector<std::string> took;
};

struct LiveDelay {
    // When, in world time.
    double at_s{};
    // What it was about.
    std::string object;
    // "blocked"     the host asked and had to wait for the whole run
    // "foreseen"    a collision was spotted coming, with this much warning
    // "precomputed" the answer was ready before it was asked for
    // "held"        the pair was pinned while the answer was worked out
    const char *kind{"blocked"};
    // How much warning there was, for "foreseen": the time until contact.
    double lead_ms{};
    // What it cost, for "blocked" and "precomputed".
    double cost_ms{};
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
    // Every contact since the last forgetImpacts(), hardest first.
    //
    // Accumulated rather than per-step, because a host almost never steps once.
    // The playground asks for however many steps have gone by since the last
    // frame -- four, usually -- and a step only ever kept the contacts of the
    // step it just took, so three steps out of four were thrown away before
    // anyone could read them. Measured: a ball dropped on a pane reported four
    // contacts when stepped one at a time and NONE when stepped four at a time.
    // Everything that did not clear a threshold happened in silence.
    [[nodiscard]] std::vector<LiveImpact> impacts(double quiet_speed_m_s = 0.5) const;
    // Start a fresh batch. A host calls this when it has read what it needs,
    // which in practice is at the top of each batch of steps.
    void forgetImpacts();

    // What the last step hit hard enough to break, by name and once each.
    //
    // Includes anything carrying more than it can hold up -- see overloaded().
    // A host answers both the same way, because from the outside they are the
    // same question: this thing may come apart, do you want to know?
    [[nodiscard]] std::vector<std::string> breakable() const;

    // Everything carrying more than its material can take, as statics rather
    // than as impacts. See LiveOverload: this is the only way a shelf with too
    // much on it ever gets noticed, because nothing strikes it.
    //
    // Surveyed at a stride rather than every step -- load does not change in a
    // quarter of a second, and the survey is O(bodies^2) on axis-aligned boxes,
    // which is nothing for a room and not nothing at sixty times a second.
    [[nodiscard]] std::vector<LiveOverload> overloaded() const;

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

    // The same thing, without waiting for it.
    //
    // Working out a fracture costs a third of a second to a second, and that is
    // irreducible -- every way of making the run shorter changes the answer.
    // So the world does not stop for it: the run goes onto a worker, the pair
    // involved is pinned where it is, and everything else carries on. The room
    // keeps moving, the camera keeps moving, and half a second later the pieces
    // appear.
    //
    //     if (world.beginFracture(name)) {        // false: nothing to do
    //         while (!world.fractureReady()) world.step(dt);   // world runs on
    //         const std::size_t pieces = world.finishFracture();
    //     }
    //
    // Only one at a time. A second contact that needs the lattice while one is
    // pending has to wait, unless it shares no matter with the first -- which is
    // what `fracturePending` is for asking about.
    [[nodiscard]] bool beginFracture(const std::string &name, double window_s = 0.003);
    [[nodiscard]] bool fracturePending() const;
    [[nodiscard]] bool fractureReady() const;
    // What is being worked out, so a caller can tell whether a new contact
    // touches it.
    [[nodiscard]] std::string fractureSubject() const;
    std::size_t finishFracture();
    // What the last fracture() call turned out to be. The return value counts
    // pieces, which cannot tell "held exactly as it was" from "held, but bent
    // out of shape" -- both are one piece.
    [[nodiscard]] LiveOutcome lastOutcome() const;

    // Every moment the world waited, or was spared waiting, since the last
    // forgetDelays(). A host that never looks at this cannot tell a world that
    // is keeping up from one that is stalling twice a second.
    [[nodiscard]] std::vector<LiveDelay> delays() const;

    // Sweep up the loose pieces within `radius_m` of a point and say what they
    // were made of, added up by material.
    //
    // Only pieces: a "hull" is what something becomes when it breaks or bends,
    // so authored objects, anchored scenery and whatever is in a hand all stay
    // where they are. `largest_cells` is what counts as little -- a shard of
    // nine cells is debris, half a pane is not.
    //
    // This is also how a room that shatters stays inside the body budget, which
    // is what breaking depends on: sweeping the floor is the natural way to
    // keep the world small enough to keep working.
    [[nodiscard]] std::vector<LiveCollected> collect(const Vec3 &at, double radius_m,
                                                     std::size_t largest_cells = 64);
    void forgetDelays();
    // How far ahead to look for a collision that will need the lattice. Zero
    // turns the looking off. A ray per moving body is cheap -- 0.02 ms -- but
    // it is not free, so it is asked at a stride rather than every step.
    void foreseeCollisions(double horizon_s);
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
    // How hard the hand can pull on something that is attached to other things,
    // in newtons. Everything an archer can do to a bow is bounded by this.
    //
    // A loose body is CARRIED and this does not apply to it: it goes exactly
    // where the hand goes, which is what makes dragging feel like holding. A
    // body on a joint is HAULED instead, and hauling is a force -- see
    // carryOrHaul for why it cannot be anything else.
    void setHandStrength(double newtons);
    [[nodiscard]] double handStrength() const;
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

    // Hang one named thing off another on a pin.
    //
    // The pin is given where it is in the world, right now, and is kept in both
    // bodies' own frames from then on. Limits are in degrees because that is
    // how anybody describes a door -- "it opens ninety degrees" -- measured
    // from where it is standing when the pin goes in, so a door built shut
    // swings 0..90 and one built open swings -90..0.
    //
    // Returns 0 if either name is not there, or if they are the same thing.
    unsigned hinge(const std::string &a, const std::string &b,
                   const Vec3 &point_world_m, const Vec3 &axis_world,
                   double lower_deg = -180.0, double upper_deg = 180.0,
                   double friction_torque_n_m = 0.0);

    // Let one named thing slide along a line fixed in another.
    //
    // The same idea as a pin, one degree of freedom the other way round: the
    // two are locked in rotation and free to move along one axis. A portcullis
    // in its grooves, a sliding door, a bolt going across a door.
    //
    // And, like a pin, nothing is played. A portcullis that has been hauled up
    // and let go FALLS, because gravity is still acting on a body that is free
    // to move down its own axis -- which is the thing that makes a winch worth
    // having and a prop useless.
    //
    // Travel is metres either side of where it is built, so a grate built down
    // in its gateway has 0..2 of lift and one built up has -2..0 of drop.
    // `friction_n` is what it takes to start it moving: a heavy grate in dry
    // stone grooves does not run freely, and this is the difference between a
    // gate that stays where you leave it and one that drops the moment you stop
    // hauling.
    //
    // Returns 0 if either name is not there, or if they are the same thing.
    unsigned slide(const std::string &a, const std::string &b,
                   const Vec3 &point_world_m, const Vec3 &axis_world,
                   double lower_m = -1.0, double upper_m = 1.0,
                   double friction_n = 0.0);

    // Tie one named thing to another, so that they may be up to `length_m`
    // apart and no further.
    //
    // That one asymmetry is the whole of what makes a rope a rope: it pulls
    // and it does not push. Below the length the link does nothing at all, so
    // slack really is slack.
    //
    // A rope or a chain is made of these -- a run of small bodies, each tied
    // to the next -- rather than being a special kind of object. Which means it
    // hangs in a catenary because its own segments are heavy, drapes over what
    // it touches because its segments collide, and can be cut anywhere along
    // its length, because every link is separately real.
    //
    // `breaking_tension_n` is what it takes to part it, and zero means it never
    // parts. A link that parts is reported once with `attached` false, exactly
    // like a gate coming off its hinges, because a host that drew a rope has to
    // stop drawing it.
    //
    // `length_m` of zero means "as they stand": the distance between the two
    // points given, which is what you want when tying a rope that is already
    // laid out.
    unsigned tie(const std::string &a, const std::string &b,
                 const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                 double length_m = 0.0, double breaking_tension_n = 0.0);

    // Reeve a rope from one named thing, over two fixed points, to another.
    //
    // A hoist. Pull one end down and the other comes up.
    //
    // `ratio` applies to B'S RUN, and which end is not a detail: because b's
    // length is what gets multiplied, b moves 1/ratio as far as a does and feels
    // ratio times the cable tension. The advantage is on b's side --
    //
    //     hang the LOAD at b, and a counterweight of load/ratio balances it.
    //
    // At ratio 2 that is a block and tackle: half the weight holds the load and
    // the load rises half as far as the counterweight falls. With the load at
    // `a` you have the same machine backwards and need TWICE the weight, which
    // is a real thing to build and a surprising thing to build by accident.
    //
    // This is the IDEAL pulley, and the difference matters enough to say out
    // loud. What the engine holds is a relationship between lengths:
    //
    //     |a - over_a|  +  ratio * |b - over_b|  <=  length
    //
    // There is no wheel, so no wheel inertia and no bearing friction. There is
    // no wrap, so the rope cannot slip, cannot come off its sheave, and does
    // not rub. What you get is the mechanism working exactly.
    //
    // The physical alternative is already here and costs a body per segment: a
    // run of things tied with tie(), draped over something solid. That one has
    // real wrap, real friction and real slip. Reach for this when you want a
    // hoist that works; reach for that when the rope itself is what is being
    // watched.
    //
    // Like a rope it pulls and does not push -- slack on one side is just slack.
    // `length_m` of zero means "as it is rove": what the two runs add up to now.
    // Fix one named thing to another: a peg, a bracket, a nail, a door catch,
    // a locking bar, a rope anchor.
    //
    // All six degrees of freedom are held, so the two move as one piece, and
    // whatever their relative pose is right now is the pose they keep. That is
    // what "defined alignment" means here -- it is defined by where they are
    // when the peg goes in, which is how a peg works.
    //
    // Two strengths, because a peg pulled straight out and a peg sheared
    // sideways fail at different loads and it is rarely the same number.
    // `axis_world` is the direction the peg points: tension is along it, shear
    // is across it. Either exceeded and the fixing parts, reported once with
    // `attached` false, exactly like a rope.
    //
    // Zero means it never lets go on its own. That is a weld, and welds are a
    // real thing to want. Releasing it on purpose is unhinge(), which is what a
    // latch does -- and doing so changes what the assembly IS, which is the
    // whole point of a latch.
    // Put an elastic element between two named things: a bow limb, a spring, a
    // bent plank -- anything that stores energy by being deformed.
    //
    // A DECLARED SIMPLIFIED MODEL, and worth naming: an ideal linear spring.
    //
    //     force  = stiffness * (length - rest)
    //     stored = stiffness * (length - rest)^2 / 2
    //
    // Hooke's law with viscous damping. It has no mass of its own, no internal
    // stress, no yield, no hysteresis, and it does not care which way it bends;
    // a real bow limb has all of those. What it does have is the property
    // everything built on it depends on -- work in is energy stored, energy
    // stored is energy back, minus what the damping takes -- and that is
    // measured rather than asserted.
    //
    // It pushes as well as pulls. A thing that only pulls is a rope: use tie().
    //
    // `rest_m` of zero means "as it stands", which is what you want for
    // something built already relaxed. `damping_n_s_m` is the declared loss.
    unsigned spring(const std::string &a, const std::string &b,
                    const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                    double rest_m = 0.0, double stiffness_n_m = 1000.0,
                    double damping_n_s_m = 0.0);

    unsigned fix(const std::string &a, const std::string &b,
                 const Vec3 &point_world_m, const Vec3 &axis_world,
                 double holds_tension_n = 0.0, double holds_shear_n = 0.0);

    unsigned reeve(const std::string &a, const std::string &b,
                   const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                   const Vec3 &over_a_world_m, const Vec3 &over_b_world_m,
                   double ratio = 1.0, double length_m = 0.0);
    // Every pin in the scene, with where each has turned to.
    [[nodiscard]] std::vector<LiveJoint> joints() const;
    // How hard it is to move. A stiff hinge holds a door where it is left.
    void setJointFriction(unsigned joint, double friction_torque_n_m);
    // Take the pin out. What hung on it falls.
    void unhinge(unsigned joint);

    // ---- heat, chemistry and gas ----------------------------------------
    //
    // The thermochemical network this world runs (thermo/ThermoWorld.hpp), or
    // null when nothing in it has declared any. It steps with the world and
    // its state is part of the reversible step: a step that is taken back
    // takes back the fuel it burned, the gas it made and the heat it moved, or
    // the retry would burn them twice. Pressure boundaries push on bodies
    // inside the same trial and are charged exactly the work those pushes did.
    [[nodiscard]] const thermo::ThermoWorld *thermo() const;
    // Declare into the running world: {"contents": [{"body": ...}],
    // "gas_regions": [...], "heaters": [...]} -- a heater's start is from now.
    void declareThermo(const std::string &json);
    // Heat a body or a gas region from now, for `seconds`. Returns its id.
    unsigned heat(const std::string &target, double power_w, double seconds);
    void setVent(const std::string &region, bool open);
    // Bodies, regions and the ledger as JSON; with `with_model`, also every
    // substance and reaction with its provenance, and what is not modelled.
    [[nodiscard]] std::string thermoReport(bool with_model = false) const;

private:
    // Every body as the network sees it: where it is, how it is turned, what
    // it weighs and how much surface it has.
    [[nodiscard]] std::vector<thermo::BodyShape> thermoShapes() const;
    [[nodiscard]] double hullArea(std::size_t body) const;
    thermo::ThermoWorld &ensureThermo();
    // After an accepted step: the heat paths again at a stride, and the rigid
    // bodies told what they weigh now.
    void settleThermo();
    LiveWorld();
    // Reads the contacts of the step just taken and answers whether any of them
    // could break what it hit. Called inside a reversible trial, so it must not
    // change the world.
    [[nodiscard]] bool judgeStep();
    // Look ahead for a collision that will need the lattice, and write down how
    // much warning there is.
    void foresee();
    // The three phases of a fracture. Only `work` takes any time, and it is the
    // only one that touches nothing shared -- everything else reads and writes
    // the rigid world.
    struct Pending;
    // A collision that has not happened yet, described as it is expected to be.
    //
    // The lattice run costs about as long as a two-metre fall takes, and until
    // now it started when the two things touched -- so you dropped something,
    // it landed, and then it sat there for most of a second before it came
    // apart. The engine can see the collision coming hundreds of milliseconds
    // out. This is what it sees, in the form prepare() needs to start early.
    struct Foresight {
        std::size_t struck{};
        std::size_t striker{static_cast<std::size_t>(-1)};
        RigidSnapshot striker_state{};
        double arrival_speed_m_s{};
    };
    void prepare(const std::string &name, double window_s);
    [[nodiscard]] std::unique_ptr<Pending> prepared(const std::string &name, double window_s,
                                                    const Foresight *guess = nullptr);
    // Start the run for a collision that is still coming, from where the two
    // things are going to be rather than where they are.
    void guessAhead(const Foresight &guess, const std::string &name);
    // What would happen if the thing in the hand were let go right now. The
    // warning a fall gives can never be longer than the fall, and below about
    // three and a half metres that is shorter than the run -- but somebody
    // lining up a drop has already given us seconds of it.
    void guessWhatIsHeld(std::set<std::string> &still_coming);
    // Is the run already going for exactly this impact? Adopting it is what
    // turns most of a second of waiting into none.
    [[nodiscard]] bool adoptGuess(const std::string &name);
    void dropGuess(const char *why);
    // A break detected while another is being worked out. Captured here and
    // now -- this is the only moment that still has the closing speed in it --
    // so the world can take the step instead of stopping until the first run
    // finishes. See LiveWorld.cpp; it cost 756 ms of a stopped clock, twice, in
    // one cascade before this existed.
    void queueBreaks();
    void startNextQueued();
    // Follow every queued job's indices through a rearrangement of the body
    // table, given the names that were there before it. By NAME, because a body
    // that came through whole keeps its name and is re-appended at the end --
    // so counting erasures below an index gets it wrong by one and the next
    // apply destroys the body next door.
    void restackQueue(const std::vector<std::string> &before);
    void repin();
    // Work out what everything is carrying and whether it can hold it.
    void surveyLoads();
    // Where the hand puts what it is holding: carried if it is loose, hauled
    // along its joint if it is attached to something. See the definition; the
    // hand writes the world from two places and both have to agree.
    void carryOrHaul(double dt_s);
    // Part every link carrying more than it can take.
    //
    // Checked after the step rather than inside it, because a link's tension is
    // the impulse the solver just applied and that does not exist until the
    // step has run. One step of overload before it parts is 4 ms at a live
    // rate, which is not visible; a rope that never parts is.
    void partOverloadedLinks();
    // Put the pins back after the body table has been rearranged.
    //
    // Every body in an island is destroyed and rebuilt when anything in it
    // breaks, so the engine-level constraints are gone even for the bodies that
    // came through whole -- and the ones that did break have new names. This
    // finds each pin's wood again by NAME first and, failing that, by looking
    // for the piece the pin is actually inside, which is the physically honest
    // answer: the pin stays in whichever lump of door is still around it.
    void rehangJoints();
    // Which body, if any, holds this point in its matter. Used to follow a pin
    // into the piece it ended up in.
    [[nodiscard]] std::size_t bodyHolding(const Vec3 &point_world_m,
                                          const std::string &was_called) const;
    // Take bodies out of the world and out of every table parallel to it,
    // fixing up the hand and any fracture holding an index.
    void dropBodies(const std::vector<std::size_t> &which);
    static void work(Pending &job);
    std::size_t applyPending();
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace banjo::fastlattice
