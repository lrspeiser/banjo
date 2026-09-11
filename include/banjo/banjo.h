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
#define BANJO_ABI_VERSION 1

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
    double energy_j;
    int would_break;
} banjo_impact;

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
