/* Banjo: a world of real matter, from C.
 *
 * This is the whole engine behind one flat header: no C++ in the interface, no
 * exceptions crossing it, no ownership of anything but an opaque handle. If a
 * language can call a C function it can drive a Banjo world -- Python through
 * ctypes, C# through P/Invoke, Rust through bindgen, a game engine through its
 * native plugin path.
 *
 * The shortest thing that works:
 *
 *     banjo_world *w = banjo_open(scene_json, 0.01);
 *     if (!w) { fprintf(stderr, "%s\n", banjo_last_error()); return 1; }
 *     for (int i = 0; i < 600; ++i) {
 *         banjo_advance(w, 1.0 / 120.0, 0.003);
 *         int n = banjo_body_count(w);
 *         banjo_body *b = malloc(n * sizeof *b);
 *         banjo_bodies(w, b, n);
 *         draw(b, n);
 *         free(b);
 *     }
 *     banjo_close(w);
 *
 * THE ONE THING THAT IS NOT LIKE OTHER PHYSICS ENGINES
 *
 * Breaking is a conversation, not a property. When a step would break
 * something, the step is TAKEN BACK and time does not move: the world is left
 * one step short of the impact, with the closing speed intact, because that is
 * the only state a fracture can start from. Handing the lattice a collision
 * Jolt has already resolved is handing it a ball that has already bounced, and
 * it breaks nothing however hard it was hit.
 *
 * So `banjo_step` can return BANJO_BREAK_PENDING, and the caller MUST answer --
 * by breaking each name in banjo_breakable_name, or by declining it with
 * banjo_decline_break. A caller that ignores it gets a world frozen at that
 * instant for ever, which is a real bug that has been hit more than once.
 *
 * `banjo_advance` does that whole conversation for you and is what most callers
 * want. Reach for `banjo_step` only when the decision about what may break is
 * yours to make.
 *
 * THREADS AND LIFETIMES
 *
 * A world belongs to the thread that opened it and is not internally locked.
 * Different worlds on different threads are fine. Every `const char *` returned
 * points into the world (or, for banjo_last_error, into thread-local storage)
 * and stays valid only until the next call on that world -- copy it if you want
 * to keep it. banjo_last_error is per-thread and is only meaningful straight
 * after a call that reported failure.
 */
#ifndef BANJO_H
#define BANJO_H

#include <stddef.h>

#if defined(_WIN32)
#  if defined(BANJO_BUILDING_SHARED)
#    define BANJO_API __declspec(dllexport)
#  elif defined(BANJO_SHARED)
#    define BANJO_API __declspec(dllimport)
#  else
#    define BANJO_API
#  endif
#else
#  if defined(BANJO_BUILDING_SHARED)
#    define BANJO_API __attribute__((visibility("default")))
#  else
#    define BANJO_API
#  endif
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* The ABI version. Bumped when the meaning or layout of anything here changes.
 * Check it once at startup against banjo_abi_version(): a header and a library
 * that disagree will not tell you so any other way. */
#define BANJO_ABI_VERSION 10

/* What a call reported. Anything below zero is a failure and leaves the world
 * unchanged; banjo_last_error() says what happened. */
typedef enum {
    BANJO_OK = 0,
    /* The step did not happen. Something in the world is one step short of
     * breaking, and until that is answered time cannot move. See the note at
     * the top of this file. */
    BANJO_BREAK_PENDING = 1,
    BANJO_ERROR = -1,
    /* A name that is not in the scene, a ray with no direction, a step with a
     * dt that is not positive: the caller's mistake, not the world's. */
    BANJO_BAD_ARGUMENT = -2
} banjo_status;

typedef enum {
    /* Drawn exactly as the box or sphere that was asked for. */
    BANJO_SHAPE_BOX = 0,
    BANJO_SHAPE_SPHERE = 1,
    /* A piece that broke off something. Its cells ARE its surface and no
     * primitive fits; `dimensions_m` is the bounding box of those cells, which
     * is enough to place a proxy but is not the real outline. */
    BANJO_SHAPE_HULL = 2
} banjo_shape;

typedef struct {
    /* Valid until the next call on this world. */
    const char *name;
    /* What it is made of, by its common name: "oak", "alumina ceramic". Valid
     * until the next call, like the name. A piece that broke off something
     * carries the material of what it broke off. */
    const char *material;
    double position_m[3];
    double orientation_wxyz[4];
    double velocity_m_s[3];
    double dimensions_m[3];
    int shape;    /* banjo_shape */
    /* Scenery: it is the world, not a prop. It does not move, cannot be picked
     * up, and is never judged for breaking. */
    int anchored;
    int held;
    unsigned rgba;
} banjo_body;

/* A pin two named things turn about.
 *
 * Two NAMES rather than two bodies, because bodies do not survive breaking:
 * everything in an island is destroyed and rebuilt when anything in it comes
 * apart. A pin whose wood is smashed follows the piece it ends up inside, so
 * `a` and `b` do change -- a gate hung on "post" can find itself hung on
 * "post piece 3" -- and `attached` goes to 0 when there is no wood left to hold
 * it, which is a gate coming off its hinges. */
typedef struct {
    unsigned id;
    /* BANJO_JOINT_HINGE or BANJO_JOINT_SLIDER. This is also the unit on the
     * four numbers below: a pin has turned so many degrees and grips in newton
     * metres, a slide has moved so many metres and grips in newtons. */
    int kind;
    const char *a;
    const char *b;
    /* Where it has got to, from where it was made: degrees, or metres. */
    double at;
    double lower;
    double upper;
    double friction;
    /* Where the pin is now and which way it runs, in world metres. Worked out
     * from the body it is in rather than remembered, so a gate carried across
     * the room reports its hinge where the gate is. */
    double at_m[3];
    double axis[3];
    int attached;
    /* For a link: what it is carrying, in newtons, and what it takes to part
     * it. Zero tension on a pin or a slide, which have no tension in any useful
     * sense; zero breaking strength means a link that never parts. */
    double tension_n;
    double breaks_at_n;
    /* For a pulley: its mechanical advantage, and the two fixed points its rope
     * runs over. 1 and zeroes for every other kind. */
    double ratio;
    double over_a_m[3];
    double over_b_m[3];
} banjo_joint;

/* A thing carrying more than it can hold up.
 *
 * This is the OTHER way something breaks here, and it exists because the first
 * way cannot see it. Every other break starts from a blow -- a closing speed, an
 * impedance, an energy. A shelf with too much stacked on it is struck by
 * nothing at all: measured, a plank bridging two piers with iron crates on it
 * reports NO contacts whatsoever once everything has settled, because the
 * contact ledger is a ledger of impacts.
 *
 * So this is asked separately, from statics: what is resting on it, how far
 * apart its supports are, and what bending that puts in it --
 *
 *     stress = 3 W L / (2 b d^2)  +  3 w L^2 / (4 b d^2)
 *
 * for a simply supported span L of section b x d under a central load W and its
 * own weight w per metre. Like every bound in this engine it is NECESSARY AND
 * NOT SUFFICIENT: past it, the lattice is worth running. */
typedef struct {
    const char *name;
    /* What is stacked on it, in newtons, not counting its own weight. */
    double carrying_n;
    /* How far apart the things holding it up are. A beam supported along its
     * whole length has no span and cannot be bent, which is the honest reason a
     * plate lying flat on the floor will not break however much is piled on. */
    double span_m;
    double stress_pa;
    double strength_pa;
} banjo_overload;

typedef struct {
    int hit;
    /* Empty when the ray stopped on something that is not one of the scene's
     * bodies -- the ground. "It hit the floor" and "it hit nothing" are
     * different answers and a pointer has to tell them apart. */
    const char *name;
    double distance_m;
    double point_m[3];
} banjo_pick;

typedef struct {
    const char *struck;
    const char *by;         /* "" when it was the ground */
    double closing_speed_m_s;
    /* The speed below which nothing CAN break. Above it a break is possible,
     * not certain -- the bound is deliberately generous, so clearing it is a
     * necessary condition and never a promise. Reading it as a promise reads
     * the derivation backwards. */
    double threshold_speed_m_s;
    /* What it would take to leave a MARK on it -- the speed below which nothing
     * can take a permanent set. Infinite for a brittle material, which has no
     * yield point and goes from elastic straight to broken.
     *
     * Almost always the lower of the two, and the gap between them is where
     * most real damage lives: iron yields in compression at 200 MPa and
     * crushes at 600. */
    double dent_speed_m_s;
    double energy_j;
    int would_break;
    int would_dent;
} banjo_impact;

/* What the lattice actually did. The two speeds above say what is POSSIBLE;
 * only running it says what happened. */
typedef enum {
    BANJO_NOTHING = 0,  /* asked about something that is not there */
    BANJO_HELD = 1,     /* it took the hit and is the shape it was */
    BANJO_DENTED = 2,   /* still one piece, and no longer the shape it was */
    BANJO_BROKE = 3     /* it came apart */
} banjo_outcome;

/* ---- opening and closing -------------------------------------------- */

typedef struct banjo_world banjo_world;

BANJO_API int banjo_abi_version(void);
/* Human-readable, for logs. Never parse it. */
BANJO_API const char *banjo_version_string(void);
/* Why the last call on this thread failed. "" if nothing has. */
BANJO_API const char *banjo_last_error(void);

/* A world from a scene, described as JSON:
 *
 *   {"bodies":[{"name":"pane","shape":"box","material":"glass",
 *               "dimensions_m":[0.3,0.04,0.3],"center_m":[0,0.02,0],
 *               "velocity_m_s":[0,0,0],"anchored":false}]}
 *
 * `material` is one of: iron, aluminum, glass, ceramic, oak, rubber, ice,
 * concrete. `cell_size_m` is how finely matter is divided, and it is the single
 * most expensive number here: halving it costs sixteen times as much, because
 * there are eight times as many cells and the timestep must halve with them.
 * 0.01 to 0.02 is the usual range.
 *
 * Returns NULL on failure; banjo_last_error() says why. */
BANJO_API banjo_world *banjo_open(const char *scene_json, double cell_size_m);
BANJO_API void banjo_close(banjo_world *world);

/* ---- time ------------------------------------------------------------ */

/* One step. Returns BANJO_OK, or BANJO_BREAK_PENDING if the step was taken back
 * because something is about to break -- read the note at the top of this file
 * before using this rather than banjo_advance. */
BANJO_API int banjo_step(banjo_world *world, double dt_s);

/* Step, and settle whatever wants to break along the way. `window_s` is how
 * long the lattice runs to work out a break; 0.003 is the usual answer and the
 * energy plateau normally stops it sooner.
 *
 * This is the call to reach for. It cannot leave a world wedged. */
BANJO_API int banjo_advance(banjo_world *world, double dt_s, double window_s);

BANJO_API double banjo_time(const banjo_world *world);

/* ---- what is about to break ----------------------------------------- */

BANJO_API int banjo_breakable_count(const banjo_world *world);
/* The i'th name, or NULL if i is out of range. */
BANJO_API const char *banjo_breakable_name(const banjo_world *world, int i);

/* Put this body back into the lattice and run it, at the impact that was caught.
 * Returns how many pieces it became: 1 means it held. Costs roughly a third of
 * a millisecond per cell, so it is worth telling the user it is happening. */
BANJO_API int banjo_fracture(banjo_world *world, const char *name, double window_s);

/* What the last fracture turned out to be, as a banjo_outcome. The piece count
 * it returns cannot tell "held exactly as it was" from "held, but bent out of
 * shape": both are one piece. */
BANJO_API int banjo_last_outcome(const banjo_world *world);

/* ---- working one out without waiting for it -------------------------- */

/* banjo_fracture above blocks for the whole run -- a third of a second to a
 * second -- and because the caller is the thing driving time, the whole world
 * stops with it. Everything else carries on being drawn, so what somebody sees
 * is the room freezing at the instant of an impact.
 *
 * These do the same work without anyone waiting for it:
 *
 *     if (banjo_begin_fracture(world, name, 0.0) == BANJO_OK) {
 *         while (!banjo_fracture_ready(world))
 *             banjo_step(world, dt);              // the world keeps running
 *         int pieces = banjo_finish_fracture(world);
 *     }
 *
 * The pair that is about to break is pinned where it is while the answer is
 * worked out -- letting it carry on means it bounces off something that is in
 * fact shattering, and has to be put back when the answer lands.
 *
 * A `window_s` of 0 means the default. */
BANJO_API int banjo_begin_fracture(banjo_world *world, const char *name, double window_s);

/* Whether something is being worked out right now. One at a time: a second
 * request waits for the first, so a host that asks while this is true gets
 * nothing back and should not ask. */
BANJO_API int banjo_fracture_pending(const banjo_world *world);

/* Whether the answer is in. Cheap, and safe to ask every step. */
BANJO_API int banjo_fracture_ready(const banjo_world *world);

/* What is being worked out, or "" if nothing is. */
BANJO_API const char *banjo_fracture_subject(const banjo_world *world);

/* Take the answer and apply it, waiting only if it is not ready. Returns the
 * piece count, exactly as banjo_fracture does -- 1 means it held. Calling it
 * when nothing is pending returns 0 and changes nothing. */
BANJO_API int banjo_finish_fracture(banjo_world *world);

/* Let this contact pass without breaking anything. Time can move again.
 * Answering is what matters, not which way you answer. */
BANJO_API int banjo_decline_break(banjo_world *world, const char *name);

/* ---- reading the world ---------------------------------------------- */

BANJO_API int banjo_body_count(const banjo_world *world);
/* Fills up to `max` bodies and returns how many were written, or a negative
 * banjo_status. Ask banjo_body_count first: a fracture changes the count. */
BANJO_API int banjo_bodies(const banjo_world *world, banjo_body *out, int max);

/* Contacts from the last step, hardest first. `quiet_speed_m_s` drops the
 * gentle ones -- two things leaning on each other are not an impact. */
BANJO_API int banjo_impact_count(const banjo_world *world, double quiet_speed_m_s);
BANJO_API int banjo_impacts(const banjo_world *world, double quiet_speed_m_s,
                            banjo_impact *out, int max);

/* ---- what made the world wait ---------------------------------------- */

/* Working out a fracture costs between a third of a second and a second, and
 * that is irreducible: every way of making the run shorter changes the answer.
 * So the only thing left is to not make anyone wait for it -- and the only way
 * to know whether that is working is to write down every time it happens. */
typedef struct {
    double at_s;             /* when, in world time */
    const char *object;
    /* "blocked"      the caller asked and waited for the whole run
     * "foreseen"     a collision was spotted coming (lead_ms is the warning);
     *                or, with a cost, a run started early and then used --
     *                lead_ms is then how far out its predicted speed was, as a
     *                percentage
     * "guessing"     a run was started for a collision that has not happened
     *                yet; lead_ms is the speed it expects
     * "guess-missed" what turned up was not what was guessed: lead_ms is the
     *                speed expected, cost_ms the speed that arrived
     * "guess-wasted" a run started early and was thrown away
     * "queued"       a break arrived while another was being worked out, and
     *                was captured rather than waited for
     * "precomputed"  the answer was ready before it was asked for; lead_ms is
     *                how long it sat waiting for a worker
     * "held"         the pair was pinned while the answer was worked out */
    const char *kind;
    double lead_ms;
    double cost_ms;          /* what the RUN cost, never what it spent queued */
} banjo_delay;

BANJO_API int banjo_delay_count(const banjo_world *world);
BANJO_API int banjo_delays(const banjo_world *world, banjo_delay *out, int max);
/* Start a fresh record. Call it when you have read what you need. */
BANJO_API int banjo_forget_delays(banjo_world *world);

/* Look this far ahead for a collision that will need the lattice, so there is a
 * chance to work it out before it arrives -- and the run is started there and
 * then, from where the two things are going to be, so that by the time they
 * touch the answer is already waiting.
 *
 * On by default at 2.5 s. 0 turns it off. Costs one ray per moving body, asked
 * at a stride, and a run that turns out to be for a collision that did not
 * happen is thrown away.
 *
 * The warning a fall gives can never be longer than the fall, so this cannot
 * cover a short drop on its own -- what is in the hand is looked at too, and the
 * run for a drop somebody is lining up starts before they let go. */
BANJO_API int banjo_foresee(banjo_world *world, double horizon_s);

/* ---- sweeping the floor ---------------------------------------------- */

/* One material's worth of what a sweep picked up, added up by material rather
 * than by shard: nobody
 * wants forty entries called "glass plate 20mm piece 31", they want to know
 * they now have four hundred grams of glass. */
typedef struct {
    /* Valid until the next call on this world. */
    const char *material;
    /* The matter that was actually there: a piece's cells are its volume, and
     * volume times the material's density is what has been carried away. */
    double kilograms;
    int pieces;
    int cells;
} banjo_lot;

/* Take the loose pieces within `radius_m` of a point out of the world.
 *
 * Only what came OFF something. Anchored scenery, whatever is in the hand, and
 * anything that is still the object it always was all stay where they are --
 * including a thing that has been DENTED, which is a BANJO_SHAPE_HULL like a
 * shard is, but is the same object in a new shape. (A dented iron ball weighs
 * three and a half kilograms and went into somebody's pockets as debris before
 * that distinction was drawn.) `largest_cells` is what counts as little (0 means a
 * sensible default): a shard of nine cells is debris, half a pane is not.
 *
 * This is also how a world that shatters stays inside the body budget, which is
 * what breaking depends on: the reversible step that a fracture needs cannot run
 * past a couple of thousand bodies, and a room fills up faster than that.
 *
 * The sweep HAPPENS on this call. It returns how many materials came back, and
 * the result is held until the next sweep -- read it with banjo_collected().
 * The body list has changed, so ask banjo_body_count() again. */
BANJO_API int banjo_collect(banjo_world *world, const double at_m[3], double radius_m,
                            int largest_cells);

/* Fills up to `max` lots from the last banjo_collect and returns how many were
 * written, or a negative banjo_status. */
BANJO_API int banjo_collected(const banjo_world *world, banjo_lot *out, int max);

/* How many things are carrying more than they can hold up. */
BANJO_API int banjo_overload_count(const banjo_world *world);
/* Fills up to `max` and returns how many were written, or a negative
 * banjo_status. The names belong to the world and stay good until the next call
 * that changes it.
 *
 * These names also appear in banjo_breakable_name(), because from the outside
 * they are the same question -- this thing may come apart, do you want to know.
 * banjo_fracture() on one puts it into the lattice WITH ITS LOAD on it, which is
 * what makes it actually fail: measured, a stone shelf at 5.46 MPa against
 * concrete's 3 came out in 26 pieces. banjo_decline_break() silences it, and
 * that matters more here than for a blow -- a load does not go away by itself,
 * so an undeclined shelf is offered on every survey for ever. */
BANJO_API int banjo_overloaded(const banjo_world *world, banjo_overload *out, int max);

/* ---- the hand -------------------------------------------------------- */

/* Take hold of something. It stops being moved by gravity and contacts and goes
 * exactly where it is put, while still pushing what it runs into. Anchored
 * scenery refuses. Returns BANJO_OK or BANJO_BAD_ARGUMENT. */
BANJO_API int banjo_grab(banjo_world *world, const char *name);
BANJO_API int banjo_move_held(banjo_world *world, const double to_m[3]);
/* Let go. It rejoins the simulation from rest, so it falls from where it was
 * left rather than carrying the hand's speed. */
BANJO_API int banjo_release(banjo_world *world);
/* What is in the hand, or "" if nothing is. */
BANJO_API const char *banjo_held(const banjo_world *world);

/* ---- pins ------------------------------------------------------------ */

/* Hang one named thing off another on a pin.
 *
 * The pin is given where it is in the world RIGHT NOW, and is kept in both
 * bodies' own frames from then on -- which is what makes a mechanism go on
 * working when the whole assembly is carried somewhere else or turned over.
 *
 * A door swings because a push off its centre line makes a torque about the
 * pin, and stops because it meets its travel limit or runs out of momentum.
 * Nothing plays an animation of a door opening.
 *
 * Limits are degrees either side of where it is hung: a `lower_deg` from -180
 * to 0 and an `upper_deg` from 0 to 180, so a door built shut swings 0..90 and
 * one built open swings -90..0. `friction_n_m` is what it takes to start it
 * turning -- a stiff old hinge holds a door where it is left, and zero swings
 * freely.
 *
 * Either end may be anchored scenery (a door on a wall is the ordinary case)
 * but not both, or there is nothing for the pin to move.
 *
 * Returns the joint's id, which is always above zero, or a negative
 * banjo_status. */
BANJO_API int banjo_hinge(banjo_world *world, const char *a, const char *b,
                          const double at_m[3], const double axis[3],
                          double lower_deg, double upper_deg,
                          double friction_n_m);

/* Let one named thing slide along a line fixed in another.
 *
 * The same idea as a pin, one degree of freedom the other way round: the two
 * are locked in rotation and free to move along one axis. A portcullis in its
 * grooves, a sliding door, a bolt going across a door.
 *
 * And, like a pin, nothing is played. A portcullis hauled up and let go FALLS,
 * because gravity is still acting on a body free to move down its own axis, and
 * it stops on whatever is under it at whatever height that thing happens to be.
 * Nothing in the engine knows what a portcullis is.
 *
 * Travel is metres either side of where it is built: `lower_m` of zero or less,
 * `upper_m` of zero or more. A grate built down in its gateway has 0..2 of lift.
 * `friction_n` is what it takes to start it moving, and it is the difference
 * between a gate that stays where you leave it and one that drops the moment
 * you stop hauling -- size it against the weight it has to hold, which for
 * 1.5 x 1.8 x 0.1 m of iron is 20.8 kN.
 *
 * Returns the joint's id, always above zero, or a negative banjo_status. */
BANJO_API int banjo_slide(banjo_world *world, const char *a, const char *b,
                          const double at_m[3], const double axis[3],
                          double lower_m, double upper_m, double friction_n);

enum { BANJO_JOINT_HINGE = 0, BANJO_JOINT_SLIDER = 1, BANJO_JOINT_LINK = 2,
       BANJO_JOINT_PULLEY = 3 };

/* Tie one named thing to another, so they may be up to `length_m` apart and no
 * further.
 *
 * That one asymmetry is the whole of what makes a rope a rope: it PULLS and it
 * does not PUSH. Below the length the link does nothing at all -- no force, no
 * damping, no quiet stiffness -- so slack really is slack. A distance
 * constraint with a minimum as well as a maximum is a rigid rod, and a rod
 * pushes.
 *
 * A rope or a chain is made of these: a run of small bodies, each tied to the
 * next. There is no rope object and no rope solver. Which means it hangs in a
 * catenary because its own segments are heavy (measured: six segments over a
 * 1 m gap with 1.4 m of rope sag 464 mm), drapes over what it touches because
 * its segments collide, and can be cut anywhere along its length -- with
 * banjo_unhinge -- because every link is separately real.
 *
 * `length_m` of 0 means "as they stand": the distance between the two points
 * given, which is what you want when tying a rope that is already laid out.
 *
 * `breaking_tension_n` is what it takes to part it, and 0 means it never parts.
 * A parted link reports `attached` as 0, the same as a gate off its hinges, and
 * what was hanging on it falls. Read what a link is carrying from `tension_n`
 * on banjo_joints -- measured against a 617.638 N weight, it reports 617.586.
 *
 * Returns the joint's id, always above zero, or a negative banjo_status. */
BANJO_API int banjo_tie(banjo_world *world, const char *a, const char *b,
                        const double at_a_m[3], const double at_b_m[3],
                        double length_m, double breaking_tension_n);

/* Reeve a rope from one named thing, over two fixed points, to another: a hoist.
 *
 * Pull one end down and the other comes up. This is the IDEAL pulley, and the
 * difference is worth stating: what the engine holds is a relationship between
 * lengths,
 *
 *     |a - over_a|  +  ratio * |b - over_b|  <=  length
 *
 * and nothing else. There is no wheel, so no wheel inertia and no bearing
 * friction. There is no wrap, so the rope cannot slip, cannot come off its
 * sheave, and does not rub. The physical alternative is banjo_tie: a run of
 * bodies tied together and draped over something solid, which has real wrap and
 * real friction and costs a body per segment. Reach for this when you want the
 * hoist to work; reach for that when the rope itself is what is being watched.
 *
 * `ratio` applies to B'S RUN, and which end is not a detail. Because b's length
 * is what gets multiplied, b moves 1/ratio as far as a does and feels ratio
 * times the cable tension, so the mechanical advantage is on b's side:
 *
 *     hang the LOAD at b, and a counterweight of load/ratio balances it.
 *
 * Measured at ratio 2: a 617.6 N load held by a 308.8 N counterweight, and
 * hauling the counterweight down 0.799541 m raised the load 0.39977 m. With the
 * load at `a` instead you have the same machine backwards and need TWICE the
 * weight -- a real thing to build, and a surprising one to build by accident.
 *
 * Like a rope it pulls and does not push: slack on one side is just slack, so a
 * counterweight resting on the floor is not dragged anywhere when the other end
 * is lifted (measured: it moved 1.5 nanometres).
 *
 * `length_m` of 0 means "as it is rove": what the two runs add up to now.
 *
 * Returns the joint's id, always above zero, or a negative banjo_status. */
BANJO_API int banjo_reeve(banjo_world *world, const char *a, const char *b,
                          const double at_a_m[3], const double at_b_m[3],
                          const double over_a_m[3], const double over_b_m[3],
                          double ratio, double length_m);

/* How many joints are in the world. */
BANJO_API int banjo_joint_count(const banjo_world *world);
/* Fills up to `max` pins and returns how many were written, or a negative
 * banjo_status. The strings belong to the world and stay good until the next
 * call that changes it. */
BANJO_API int banjo_joints(const banjo_world *world, banjo_joint *out, int max);
/* How hard it is to turn, in newton metres. */
/* Newton metres for a pin, newtons for a slide. */
BANJO_API int banjo_joint_friction(banjo_world *world, unsigned joint,
                                   double friction);
/* Take the pin out. What was hanging on it falls. */
BANJO_API int banjo_unhinge(banjo_world *world, unsigned joint);

/* ---- asking where things are ---------------------------------------- */

/* What a ray meets first, against the shapes the solver really collides. This
 * is "what is under the pointer", "can this see that", "is anything in the
 * way". Costs no step and changes nothing, so ask it as often as you like.
 * `max_m` of 0 means a sensible default. */
BANJO_API int banjo_pick_ray(const banjo_world *world, const double from_m[3],
                             const double direction[3], double max_m,
                             banjo_pick *out);

#ifdef __cplusplus
}
#endif

#endif /* BANJO_H */
