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
 * that disagree will not tell you so any other way.
 *
 * 13 added blades: an edge on a body, the bounded hand that swings it, and
 * what it cut (banjo_make_blade, banjo_blades, banjo_cuts, banjo_forget_cuts,
 * banjo_wield, banjo_aim_held, banjo_hand_strength, banjo_hand_torque).
 * 14 added heat, chemistry and gas. The two were made on separate branches
 * and numbered apart so that, merged, one number means one header: a library
 * at 14 carries both. Nothing that was in 12 changed.
 *
 * 15 added terrain and water: a ground of rock, soil and sand held as a height
 * field, rivers and ponds as columns of water on it, digging, heaping and
 * cutting, and bodies that float, drift and dam (banjo_terrain_info,
 * banjo_water_info, banjo_dig, banjo_deposit, banjo_cut_block, banjo_set_discharge,
 * banjo_terrain_heights, banjo_water_surface, banjo_environment_report,
 * banjo_environment_state, banjo_survey, banjo_awake_bodies). Nothing that was
 * in 14 changed.
 *
 * 16 made heat change what things can carry (docs/thermal-mechanics.md): a
 * declared law per material, a joint that names the body it is made of
 * (banjo_joint_member), what heat has done to each body
 * (banjo_body_mechanics_count, banjo_bodies_mechanics, banjo_mechanics_report),
 * and new fields at the END of banjo_joint, banjo_overload and banjo_energy.
 * Those three structs grew, so a caller built against 15 must be rebuilt;
 * every field that was there keeps its place and its meaning. */
#define BANJO_ABI_VERSION 16

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
    /* For a fixing: what it is carrying along its axis and across it, and what
     * it can take of each. A peg pulled straight out and a peg sheared sideways
     * fail at different loads, so these are two numbers and not one. Zero for
     * every other kind. */
    double tension_now_n;
    double shear_now_n;
    double holds_tension_n;
    double holds_shear_n;
    /* For an elastic: the declared linear model, and what it currently holds.
     *     force_n  = stiffness_n_m * (at - rest_m)
     *     stored_j = stiffness_n_m * (at - rest_m)^2 / 2
     * Zero for every other kind. */
    double rest_m;
    double stiffness_n_m;
    double damping_n_s_m;
    double force_n;
    double stored_j;
    /* ---- ABI 16: heat and strength (docs/thermal-mechanics.md) ----------
     * Which of the two things the joint is MADE of -- the peg of a fixing, the
     * rope segment a link is tied through, a spring's limb -- set with
     * banjo_joint_member. "" when nothing was named: the joint is then exactly
     * the numbers it was declared with, and heat changes nothing about it.
     * With a member, holds_tension_n, holds_shear_n, breaks_at_n and
     * stiffness_n_m above are what it has NOW, and these are what it had cold. */
    const char *member;
    double rated_tension_n;
    double rated_shear_n;
    double rated_breaks_at_n;
    double rated_stiffness_n_m;
    /* The share of that it still has: 1 cold. For a fixing, the lower of its
     * two. */
    double capacity_fraction;
    /* How many times heat changing the member made the joint be asked again
     * whether it holds, with both ends woken so the solver measured the load. */
    unsigned rechecks;
    /* Why it let go, once it has, and the two numbers that decided it: the
     * load the solver measured in that step and what the joint could still take.
     * "" and zeros while it holds, and for a joint taken out on purpose. */
    const char *parted_because;
    double parted_load_n;
    double parted_capacity_n;
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
    /* ABI 16. What its section can still take against the same beam cold: 1
     * for anything heat has not touched. strength_pa is already the material's
     * strength times this. And why, in words. */
    double capacity_fraction;
    const char *why;
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
       BANJO_JOINT_PULLEY = 3, BANJO_JOINT_FIXING = 4, BANJO_JOINT_ELASTIC = 5 };

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

/* Fix one named thing to another: a peg, a bracket, a nail, a bolt, a door
 * catch, a locking bar, a rope anchor.
 *
 * All six degrees of freedom are held, so the two move as one piece, and
 * whatever their relative pose is when the fixing is made is the pose they keep.
 * That is what "defined alignment" means here -- it is defined by where they are
 * when the peg goes in, which is how a peg works.
 *
 * TWO strengths, because a peg pulled straight out and a peg sheared sideways
 * fail at different loads and it is rarely the same number. `axis` is the
 * direction the peg points: tension is along it, shear is across it. Either
 * exceeded and it parts, reported once with `attached` 0, exactly like a rope.
 * Measured on a bracket hanging off a wall: 6.5e-17 N of tension and 617.586 N
 * of shear, because a hanging weight is entirely shear.
 *
 * Zero means it never lets go on its own -- that is a weld, and welds are a real
 * thing to want. Releasing it on purpose is banjo_unhinge, which is what a latch
 * does, and doing so changes what the assembly IS: measured, the same shove on
 * the same gate moved it 1.66 degrees with a bar across it and 18.76 without.
 *
 * Returns the joint's id, always above zero, or a negative banjo_status. */
BANJO_API int banjo_fix(banjo_world *world, const char *a, const char *b,
                        const double at_m[3], const double axis[3],
                        double holds_tension_n, double holds_shear_n);

/* Put an elastic element between two named things: a bow limb, a spring, a bent
 * plank -- anything that stores energy by being deformed and gives it back.
 *
 * This is a DECLARED SIMPLIFIED MODEL, and which one matters, so here it is. An
 * ideal linear spring:
 *
 *     force  = stiffness * (length - rest)
 *     stored = stiffness * (length - rest)^2 / 2
 *
 * Hooke's law with viscous damping. It has no mass of its own, no internal
 * stress, no yield, no hysteresis, and it does not care which way it bends; a
 * real bow limb has all of those.
 *
 * It is VALIDATED rather than asserted -- tests/elastic_tests.cpp integrates the
 * work actually done drawing it and compares that against the energy the model
 * claims, then fires it and measures what comes back. Measured: 99.94 N where
 * Hooke says 100; a work integral of 62.68 J against a claimed 62.43; and
 * 95.86% of that back as kinetic energy with no damping declared. Four times
 * the stiffness multiplied the speed by 1.963 where the model says 2, and eight
 * times the mass divided it by 2.730 where the model says 2.83.
 *
 * It PUSHES as well as pulls -- squashed below its rest length it shoves back.
 * A thing that only pulls is a rope: use banjo_tie.
 *
 * `rest_m` of 0 means "as it stands". `damping_n_s_m` is the declared loss and
 * is the only thing that should take energy out: measured, 400 N s/m turned
 * 59.85 J of return into 16.07.
 *
 * Returns the joint's id, always above zero, or a negative banjo_status. */
BANJO_API int banjo_spring(banjo_world *world, const char *a, const char *b,
                           const double at_a_m[3], const double at_b_m[3],
                           double rest_m, double stiffness_n_m,
                           double damping_n_s_m);

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

/* ---- blades ---------------------------------------------------------- */

/* An edge on a body, and what it has done. docs/cutting-model.md is the whole
 * declared model; the short of it is this.
 *
 * A blade is declared ON a body that already exists. The body supplies the
 * matter -- its material, its mass, and where that mass is -- and the
 * declaration adds what cells cannot resolve: the edge (a straight line, heel
 * to tip), the way it faces, how thick and how sharp it is, and where a hand
 * holds it. There is no cutting power and nothing is destroyed on touch.
 *
 * What resists an edge is the target's own catalogue numbers, its fracture
 * energy G and its hardness H. Advancing an edge of engaged length L a distance
 * d through uncut matter costs R L d, with R = G + H * 2 * edge_radius. The
 * resistance is applied in the solver as friction, so a slow press cuts only
 * while it pushes harder than R L, and the work a cut takes is measured from the
 * solver's own impulses rather than assumed.
 *
 * What gets cut is bonds. A partial cut leaves the body one body, carrying a
 * kerf; a cut through replaces it with pieces that have their own mass, inertia
 * and momentum and keep whatever joints they hold -- a rope cut through drops
 * what hung on it because the link that held it is on the lower piece. */
typedef struct {
    unsigned id;
    const char *body;       /* the body carrying the edge */
    const char *material;
    /* Where it is now, in world metres: the edge heel to tip, the way it
     * faces, the normal to its flats, and the grip. */
    double heel_m[3];
    double tip_m[3];
    double facing[3];
    double flat[3];
    double grip_m[3];
    double thickness_m;
    double edge_radius_m;
    double bevel_deg;
    /* Everything it has cut, and the work that cost as the solver applied it. */
    double cut_area_m2;
    double cut_work_j;
    /* What the edge is in right now, "" for nothing. */
    const char *cutting;
    /* 0 once the body carrying it has gone. */
    int attached;
} banjo_blade;

/* One meeting between an edge and something else, from first touch until they
 * part. Every one is reported, including those that cut nothing, because "the
 * flat of the blade hit it" is an answer a host has to be able to give.
 *
 * `kind` is decided from geometry and motion, never from names:
 *   "edge", "slice", "press"     the edge bit; moving mostly into the material,
 *                                mostly along its own length, or slowly
 *   "glancing", "flat", "point"  it met the surface some other way and was an
 *                                ordinary rigid contact
 *   "blunt"                      the target is as hard as the blade, or harder
 *   "brittle"                    the target has no yield point: it cracks under
 *                                a blow, and is not cut */
typedef struct {
    const char *blade;
    const char *target;
    const char *kind;
    double at_s;
    /* The relative motion of the edge at first contact, in the blade's axes. */
    double speed_m_s;
    double into_m_s;
    double along_m_s;
    double across_m_s;
    /* R = G + H w for this edge in this material, J/m^2 (newtons per metre of
     * engaged edge). */
    double resistance_j_m2;
    double area_m2;
    double work_j;
    int bonds;          /* severed */
    int links;          /* rope links severed */
    int separated;      /* the target came apart */
    int pieces;         /* into how many, when it did */
    int open;           /* still in contact */
} banjo_cut;

/* Give a named body an edge. Everything is given where it is in the world RIGHT
 * NOW and kept in the body's own frame from then on. Both ends of the edge must
 * lie on the body's matter; `facing` is squared up against the edge, so roughly
 * perpendicular is enough. `edge_radius_m` is how sharp it is -- 0.0002 is a
 * working sword edge, 0.00005 a keen one -- and `bevel_deg` the included angle
 * of the edge wedge.
 *
 * Returns the blade's id, always above zero, or a negative banjo_status. */
/* (Named make_blade because C will not let a function and a struct share a
 * name, and banjo_blade is the struct.) */
BANJO_API int banjo_make_blade(banjo_world *world, const char *body,
                               const double heel_m[3], const double tip_m[3],
                               const double facing[3], double thickness_m,
                               double edge_radius_m, double bevel_deg,
                               const double grip_m[3]);
BANJO_API int banjo_blade_count(const banjo_world *world);
/* Fills up to `max` and returns how many were written, or a negative status.
 * The strings stay good until the next call on this world. */
BANJO_API int banjo_blades(const banjo_world *world, banjo_blade *out, int max);
/* Every edge contact since the last banjo_forget_cuts, in the order they
 * began. Open ones are still going and keep changing. */
BANJO_API int banjo_cut_count(const banjo_world *world);
BANJO_API int banjo_cuts(const banjo_world *world, banjo_cut *out, int max);
/* Drop the ones that are over. Open contacts stay. */
BANJO_API int banjo_forget_cuts(banjo_world *world);

/* ---- the grip -------------------------------------------------------- */

/* Take hold of a body the way a person holds a sword: at a point on it, with a
 * hand whose force and torque are BOUNDED. banjo_move_held then says where the
 * grip should be, and banjo_aim_held which way the body should face; the hand
 * pulls and turns towards both with what it has -- 800 N and 60 N m unless told
 * otherwise -- and what the body meets can slow it, turn it aside or stop it.
 *
 * This is not banjo_grab. banjo_grab carries a loose body exactly where it is
 * put, which is placement -- an editor's move -- and stays exactly that.
 * Returns BANJO_OK or BANJO_BAD_ARGUMENT. */
BANJO_API int banjo_wield(banjo_world *world, const char *name, const double grip_m[3]);
/* Which way the wielded body should face, as a quaternion, w first. */
BANJO_API int banjo_aim_held(banjo_world *world, const double orientation_wxyz[4]);
/* How hard the hand can pull, in newtons, and turn, in newton metres. */
BANJO_API int banjo_hand_strength(banjo_world *world, double newtons);
BANJO_API int banjo_hand_torque(banjo_world *world, double newton_metres);

/* ---- asking where things are ---------------------------------------- */

/* What a ray meets first, against the shapes the solver really collides. This
 * is "what is under the pointer", "can this see that", "is anything in the
 * way". Costs no step and changes nothing, so ask it as often as you like.
 * `max_m` of 0 means a sensible default. */
BANJO_API int banjo_pick_ray(const banjo_world *world, const double from_m[3],
                             const double direction[3], double max_m,
                             banjo_pick *out);

/* ---- heat, chemistry and gas ------------------------------------------ */

/* A world can hold matter that reacts, heat that moves, and gas that pushes.
 *
 * ONE ENERGY CONVENTION. Every substance has an internal energy per kilogram of
 * u = u0 + cv * T, measured from 0 K: a reference part u0 and a sensible part.
 * A body or a gas stores ONE internal energy, and its temperature is derived
 * from it -- never assigned. "Chemical" and "thermal" below are the reference
 * and the sensible parts of that one number, not two stores added together: a
 * reaction heats what it happens in because its products' reference energies
 * are lower, and nothing adds a separate heat of reaction on top.
 *
 * WHAT CONTAINS WHAT. A body is made of what its material is made of -- an oak
 * log is dry wood, moisture and ash by default, which is what lets it burn --
 * and a scene may say otherwise on the body ("contents": {"dry wood": 0.7,
 * "moisture": 0.3}). A gas region is a volume of gas that can push on a body:
 * a cylinder under a piston. Burning is a RESULT. Nothing has a burn time; a
 * log lasts as long as its fuel does at the rate the model burns it, and
 * banjo_body_heat.remaining_s is that estimate under current conditions.
 *
 * DECLARED, NOT VALIDATED. The wood model is a declared simplified model with
 * demonstration parameters. banjo_thermo_report(world, 1) says where every
 * number came from and what is not modelled.
 *
 * Declared in a scene (see banjo_open):
 *
 *   {"bodies": [{"name": "log", "material": "oak", ...,
 *                "contents": {"dry wood": 0.8, "moisture": 0.18, "ash": 0.02},
 *                "temperature_k": 293.15}],
 *    "thermo": {"gas_regions": [{"name": "cylinder gas", "contents": {"argon": 1},
 *                                "piston": "piston", "height_m": 0.4,
 *                                "balance": true}],
 *               "heaters": [{"target": "log", "power_w": 10000, "seconds": 60}]}}
 *
 * or into a running world with banjo_declare. */

/* What one body holds and how hot it is. */
typedef struct {
    /* Valid until the next call on this world. */
    const char *name;
    const char *material;
    /* The surface: what glows, radiates, burns and touches. */
    double temperature_k;
    /* The rest of it. The same as the surface for a body that conducts well
     * enough to be one temperature throughout. */
    double core_temperature_k;
    double mass_kg;
    /* What is left that a heat-releasing reaction can consume. */
    double fuel_kg;
    /* How fast reactions are releasing heat now, at their quoted heating value. */
    double heat_release_w;
    double fuel_use_kg_s;
    /* Fuel over the rate it is being used now: what it would last if nothing
     * about it changed. INFINITY when nothing is burning. */
    double remaining_s;
    double heater_w;
    /* From other bodies, by contact and radiation; and to the surroundings. */
    double gained_w;
    double lost_w;
    int reacting;
    /* Its contents were declared, rather than taken from its material. */
    int declared;
} banjo_body_heat;

/* A volume of gas, and the body it pushes on if it has one. */
typedef struct {
    const char *name;
    /* "" for a region with nothing to push on. */
    const char *piston;
    double temperature_k;
    double pressure_pa;
    double volume_m3;
    double mass_kg;
    double moles;
    /* Where the column starts, which way it grows, and its cross-section:
     * enough to draw it. Its top is base + axis * height_m. */
    double base_m[3];
    double axis[3];
    double area_m2;
    double height_m;
    /* How far the piston has moved since the region was declared. */
    double stroke_m;
    /* Net force on the piston: the gas's pressure less the surroundings'. */
    double force_n;
    /* Boundary work: delivered to bodies (net of the atmosphere), and done
     * pushing the atmosphere back. Negative when bodies pushed on the gas. */
    double work_to_bodies_j;
    double work_to_atmosphere_j;
    double heater_w;
    double wall_loss_w;
    int vent_open;
} banjo_gas_region;

/* The ledger: where the energy is, and everything that crossed the boundary.
 *
 *     stored_j - initial_j = heater_in_j - heat_to_surroundings_j
 *                          + matter_in_j - matter_out_j + joined_j - left_j
 *                          - work_to_bodies_j - work_to_atmosphere_j
 *                          + numerical_j + residual_j
 *
 * Every term but the last is added up where it happens, so residual_j measures
 * the arithmetic and nothing else. */
typedef struct {
    double chemical_j;
    double thermal_j;
    double stored_j;
    double mass_kg;
    double initial_j;
    double heater_in_j;
    double heat_to_surroundings_j;
    double matter_in_j;
    double matter_in_kg;
    double matter_out_j;
    double matter_out_kg;
    /* Bodies drawn into the network by heat reaching them, and bodies that
     * left the world (swept up) with what they held. */
    double joined_j;
    double left_j;
    double work_to_bodies_j;
    double work_to_atmosphere_j;
    /* Energy the arithmetic had to add to keep something physical. Reported,
     * never hidden; zero in every run so far. */
    double numerical_j;
    double residual_j;
    double mass_residual_kg;
    /* A separate view: the kinetic and gravitational energy of every body, from
     * the solver's own masses. Boundary work is the link between the two. */
    double mechanical_j;
    /* ABI 16. Energy the mechanical side handed the network as heat: the
     * elastic energy a spring stopped holding when its member softened at a
     * fixed stretch (negative when one stiffened again and took it back). A
     * crossing, so it is in the balance at the top of this struct's comment as
     * a term added to the right-hand side. */
    double mechanical_in_j;
} banjo_energy;

/* Declare into a running world:
 *     {"contents": [{"body": "log", "contents": {"dry wood": 1}}],
 *      "gas_regions": [...], "heaters": [...]}
 * A heater declared here starts now. BANJO_BAD_ARGUMENT, with the reason, for
 * anything the network refuses -- a key it does not know is refused by name. */
BANJO_API int banjo_declare(banjo_world *world, const char *json);

/* Heat a body or a gas region at `power_w` from now, for `seconds`: external
 * work, counted in the ledger as heater_in_j. Enough of it lights a log and
 * less does not. Returns the heater's id, above zero, or a negative status. */
BANJO_API int banjo_heat(banjo_world *world, const char *target, double power_w,
                         double seconds);

/* Open or close a gas region's opening to the surroundings. */
BANJO_API int banjo_vent(banjo_world *world, const char *region, int open);

BANJO_API int banjo_body_heat_count(const banjo_world *world);
/* Every body the network holds. Fills up to `max`, returns how many. */
BANJO_API int banjo_bodies_heat(const banjo_world *world, banjo_body_heat *out, int max);
BANJO_API int banjo_gas_region_count(const banjo_world *world);
BANJO_API int banjo_gas_regions(const banjo_world *world, banjo_gas_region *out, int max);
BANJO_API int banjo_energy_ledger(const banjo_world *world, banjo_energy *out);

/* Everything above as JSON; with `with_model` nonzero, also every substance and
 * reaction with where its numbers came from, and what is not modelled. Valid
 * until the next call on this world. */
BANJO_API const char *banjo_thermo_report(const banjo_world *world, int with_model);
/* The substances, reactions and material compositions a world starts with, as
 * JSON, without needing a world. Valid until the next call on this thread. */
BANJO_API const char *banjo_thermo_model(void);

/* ---- heat and strength (ABI 16) ------------------------------------------ */

/* Temperature, composition and what has burned change what a body can carry,
 * by a DECLARED LAW PER MATERIAL -- never "hot means weak": oak by EN 1995-1-2's
 * softwood curves (shear 0.40 of cold at 100 degC, nothing at 300 degC, char
 * from there on), iron by EN 1993-1-2's carbon-steel curves (no loss of yield
 * below 400 degC), concrete by EN 1992-1-2 (and it does not recover). Glass,
 * aluminium, alumina ceramic, rubber and ice have no law and are not changed.
 * banjo_mechanics_report(world, 1) says where every number came from and what
 * is not modelled; docs/thermal-mechanics.md is the whole model.
 *
 * A section is at most three rings, because a body is one surface layer over
 * one core in the thermal network: what burned away (gone), the surface layer
 * (at its temperature; char once it has passed 300 degC) and the core. What
 * does not come back when it cools -- char, what burned, what pyrolysis took --
 * is decided by the hottest each zone has been.
 *
 * Failure is the engine's two existing paths, fed the new numbers: a joint made
 * of a member parts when the load the solver measures passes what the member's
 * law leaves it (banjo_joint.parted_because says so), and a beam is offered as
 * overloaded when the bending in it passes what its section can still take.
 * Heat changing either makes it be asked again at once, with the bodies woken,
 * even while nothing is moving. */
typedef struct {
    const char *name;
    const char *material;
    /* The law, and where its numbers come from. "" for a material with none. */
    const char *law;
    const char *provenance;
    /* Whether the thermal network holds it at all: nothing has heated a body
     * it does not, and every factor is 1. */
    int tracked;
    double surface_k;
    double core_k;
    /* The hottest each zone has been. */
    double peak_surface_k;
    double peak_core_k;
    /* How much of its load-bearing matter is left, and its load-bearing share
     * when it was declared against its material's own (dry wood in oak). */
    double remaining_fraction;
    double composition_factor;
    double dimensions_m[3];
    /* The section across its longest axis: as built, how far burning has
     * eaten in from every face, the char under that, the surface layer's
     * depth, and what is still sound. */
    double section_m[2];
    double consumed_m;
    double char_m;
    double layer_m;
    double sound_section_m[2];
    /* Against the same section cold: 1 is as it was. */
    double stiffness;
    double tension;
    double compression;
    double shear;
    double bending;
    /* What it would keep if it cooled now. */
    double tension_if_cooled;
    double shear_if_cooled;
    double bending_if_cooled;
    /* 0 when its state is outside what the law supports (banjo_mechanics_report
     * says why): the answer is still given, and said to be outside. */
    int supported;
} banjo_body_mechanics;

/* Say which of a joint's two bodies it is made of: its strength (a fixing, a
 * link) or its stiffness (an elastic) follows that body's law from now on. A
 * declared strength of zero becomes the member's own section times its
 * material's strength -- so with a member, zero is no longer a weld. "" goes
 * back to the declared numbers. BANJO_BAD_ARGUMENT for a pin, a slide or a
 * pulley, which have no strength to lose here, and for a name that is not one
 * of the joint's two ends. A spring's stiffness changing stretched changes the
 * energy it holds; that difference is handed to the thermal ledger as heat
 * (banjo_energy.mechanical_in_j), never made or lost. */
BANJO_API int banjo_joint_member(banjo_world *world, unsigned joint, const char *member);

/* Every body the thermal network holds, and every body a joint is made of. */
BANJO_API int banjo_body_mechanics_count(const banjo_world *world);
BANJO_API int banjo_bodies_mechanics(const banjo_world *world, banjo_body_mechanics *out, int max);

/* All of it as JSON: the bodies, every joint made of a member with what it
 * carries against what it can take, and with `with_laws` nonzero the laws,
 * their sources and what is not modelled. Valid until the next call on this
 * world. */
BANJO_API const char *banjo_mechanics_report(const banjo_world *world, int with_laws);

/* ---- terrain and water (ABI 15) ---------------------------------------- */

/* Physics decides what changes; nothing re-simulates what has not.
 *
 * THE GROUND is columns of rock, soil and sand held still as a height field --
 * a static collider in chunks of 31 x 31 cells -- until something changes it.
 * A spade (banjo_dig) takes material out; the columns it touched and their
 * neighbours are asked whether they still stand (Mohr-Coulomb: sand slumps to
 * its angle of repose, firm soil holds a spade-deep wall, rock never slumps),
 * whatever fails flows down at the speed a granular layer of that thickness
 * can, and only the chunks that changed get new colliders. Whatever those
 * chunks were holding up is woken to find out whether it still is: dig under
 * a boulder and it falls.
 *
 * THE WATER is a shallow-water solver on the same grid: a column of water per
 * cell, its surface and its sideways velocity, conserving mass and momentum,
 * well balanced (a lake at rest stays exactly at rest), wet and dry, on its own
 * clock inside its stability limit. A river comes in at one edge and leaves at
 * another. Bodies are pressed on by the water over their own surface --
 * buoyancy is the pressure on the underside, from density and displaced
 * volume, so oak floats 70% under and iron sinks -- and dragged by it
 * relative to their motion; the drag goes back into the water. Something that
 * sinks and rests on the bed is, to the water, part of the bed: a row of
 * blocks is a dam.
 *
 * DECLARED in a scene (see banjo_open):
 *
 *   "terrain": {"generate": "valley",
 *               "edits": [{"dig": {"from_m": [x, z], "to_m": [x, z],
 *                                  "width_m": 1, "depth_m": 0.5}},
 *                         {"deposit": {"at_m": [x, z], "radius_m": 1,
 *                                      "sand_m3": 0.5, "soil_m3": 0}},
 *                         {"cut": {"at_m": [x, z], "cells": [4, 4],
 *                                  "height_m": 0.4}}]},
 *   "water": {"discharge_m3_s": 0.35, "state": <banjo_environment_state()>}
 *
 * "generate" is "valley" (made once by drainage and erosion and cached on
 * disk under BANJO_TERRAIN_CACHE), "basin", "channel" or "flat", or an object
 * {"kind": ..., ...} with its parameters. Edits are applied in order when the
 * world opens, and whatever they unsettle has come to rest by the time it
 * does. A world with none of this is unchanged and pays nothing for it. */

typedef struct {
    int nx, nz;                 /* points; point (i, j) is at origin + (i, j) * cell */
    double cell_m;
    double origin_m[2];         /* x and z of point (0, 0) */
    int chunks_x, chunks_z;     /* colliders */
    double lowest_m, highest_m;
    double floor_m;             /* the rock goes down to here; nothing is dug below it */
    double rock_m3, soil_m3, sand_m3;
    /* What has crossed the ground's boundary since it was made: dug out, cut
     * out as blocks, heaped up. Slumping moves matter between columns and is
     * counted apart. residual_m3 is now - (initial - dug - cut + deposited),
     * summed over the kinds: rounding and nothing else. */
    double dug_m3, cut_m3, deposited_m3, slumped_m3;
    double residual_m3;
    int unsettled_columns;      /* still being asked whether they stand */
    int chunks_rebuilt;         /* colliders rebuilt since the world opened */
    double rebuild_ms_worst;
} banjo_terrain;

typedef struct {
    double time_s;
    double volume_m3, wet_area_m2;
    int cells, wet_cells;
    int active_cells;           /* computed in the last substep: only water costs */
    double inflow_m3_s, outflow_m3_s;
    /* volume - initial = inflow - outflow + numerical + residual */
    double initial_m3, inflow_m3, outflow_m3, numerical_m3, residual_m3;
    double substeps;
    double last_substep_s;      /* within the stability limit, always */
    double wave_speed_m_s;
    int bodies_in_water;
    double water_ms_worst, coupling_ms_worst, step_ms_worst;
} banjo_water;

/* What a dig or a heap moved, and what it cost the world. */
typedef struct {
    double sand_m3, soil_m3, mass_kg;
    int columns;
    int chunks_rebuilt;
    double rebuild_ms;
    int bodies_woken;           /* what the changed ground was holding up */
} banjo_dug;

/* A block cut out of bare rock: a box of the same footprint and volume as the
 * rock that left, at the rock's own density. */
typedef struct {
    double center_m[3];
    double size_m[3];
    double volume_m3;
    double mass_kg;
} banjo_block;

/* BANJO_BAD_ARGUMENT, with a reason, for a world whose scene declares no
 * terrain. */
BANJO_API int banjo_terrain_info(const banjo_world *world, banjo_terrain *out);
BANJO_API int banjo_water_info(const banjo_world *world, banjo_water *out);

/* Dig a trench from `from_m` to `to_m` (x, z; the same point for a pit),
 * `width_m` wide, `depth_m` below the ground as it stands. Loose material
 * first, then soil; a spade stops on rock. What came out is the caller's --
 * carry it, heap it somewhere with banjo_deposit -- and the ledger says so.
 * Water over the dug ground keeps its volume: digging makes none. */
BANJO_API int banjo_dig(banjo_world *world, const double from_m[2], const double to_m[2],
                        double width_m, double depth_m, banjo_dug *out);
/* Heap sand and soil up around a point; it settles to the slope it can hold. */
BANJO_API int banjo_deposit(banjo_world *world, const double at_m[2], double radius_m,
                            double sand_m3, double soil_m3, banjo_dug *out);
/* Cut a block `height_m` tall (rounded to whole cells) out of bare rock,
 * `cells_x` by `cells_z` columns centred on `at_m`. The cut is a flat plane
 * that height below the rock's mean top there, so exactly the block's volume
 * leaves the ground. The ground loses it NOW; a body cannot join a running
 * world, so the caller adds the block as a body in the scene it opens next --
 * with {"cut": {"at_m", "cells", "height_m"}} in that scene's "edits" -- and
 * the two together are exactly the rock there was. Every side of a body is a
 * whole number of cells, so a footprint that is not is refused with the size
 * that would do (with 0.25 m columns and 0.04 m cells, 4 columns: 1 m).
 * BANJO_BAD_ARGUMENT, with the reason, also where there is soil over the rock
 * or the rock is too uneven for a block that shallow. */
BANJO_API int banjo_cut_block(banjo_world *world, const double at_m[2], int cells_x, int cells_z,
                              double height_m, banjo_block *out);
/* A river's discharge from now, by the name the scene or the valley gave it. */
BANJO_API int banjo_set_discharge(banjo_world *world, const char *river, double discharge_m3_s);

/* The ground's heights, nx * nz floats, row by row (j outer). Returns how many
 * were written. */
BANJO_API int banjo_terrain_heights(const banjo_world *world, float *out, int max);
/* The water's surface, nx * nz doubles, NaN where a column is dry. */
BANJO_API int banjo_water_surface(const banjo_world *world, double *out, int max);

/* Everything about the ground and the water as JSON; `full` nonzero adds the
 * model's parameters, where they came from, and what is not modelled. */
BANJO_API const char *banjo_environment_report(const banjo_world *world, int full);
/* The water as it stands, as JSON, for "water": {"state": ...} in the scene a
 * world is opened again from: the same water, over whatever ground that
 * scene's edits leave. */
BANJO_API const char *banjo_environment_state(const banjo_world *world);
/* Ground and water at a point: height, what it is made of, slope, depth,
 * surface and flow. JSON. */
BANJO_API const char *banjo_survey(const banjo_world *world, double x_m, double z_m);
/* How many bodies the rigid solver is stepping right now. A body at rest is
 * asleep and costs nothing; this is how to see that digging one corner did
 * not wake the valley. */
BANJO_API int banjo_awake_bodies(const banjo_world *world);

#ifdef __cplusplus
}
#endif

#endif /* BANJO_H */
