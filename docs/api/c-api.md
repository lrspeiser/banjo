# The C API

One header, one shared library, an opaque handle. No C++ in the interface, no
exceptions crossing it, nothing to free but the world.

```c
#include "banjo/banjo.h"
```

Check the ABI once at startup. A header and a library that disagree will not
tell you any other way:

```c
if (banjo_abi_version() != BANJO_ABI_VERSION) { /* mismatch */ }
```

Current ABI: **3**.

---

## Threads and lifetimes

A world belongs to the thread that opened it and is **not internally locked**.
Different worlds on different threads are fine; one world from two threads is
not.

Every `const char *` returned points into the world (or, for
`banjo_last_error`, into thread-local storage) and stays valid **only until the
next call on that world**. Copy it if you want to keep it.

`banjo_last_error` is per-thread and only meaningful straight after a call that
reported failure.

---

## Opening and closing

### `banjo_world *banjo_open(const char *scene_json, double cell_size_m)`

Returns `NULL` on failure; `banjo_last_error()` says why. See
[the scene format](#the-scene-format) below.

### `void banjo_close(banjo_world *world)`

Closing twice is not an error; closing `NULL` is not an error.

---

## Time

### `int banjo_step(banjo_world *world, double dt_s)`

One step. Returns:

| | |
|---|---|
| `BANJO_OK` (0) | time advanced |
| `BANJO_BREAK_PENDING` (1) | **the step did not happen.** Something is one step short of giving way. Answer it or nothing will ever move again. |
| `BANJO_BAD_ARGUMENT` (-2) | `dt_s` was not positive, or there is no world |
| `BANJO_ERROR` (-1) | the engine failed; `banjo_last_error()` says how |

### `int banjo_advance(banjo_world *world, double dt_s, double window_s)`

Step, and settle whatever wants to break along the way. **This is the call to
reach for.** It cannot leave a world wedged.

`window_s` is how long the lattice runs to work out a break; `0.003` is the
usual answer and the energy plateau normally stops it sooner.

### `double banjo_time(const banjo_world *world)`

Seconds of world time since it opened. A step that was taken back does not
advance it.

---

## The break conversation

Only needed if you use `banjo_step` rather than `banjo_advance`.

```c
while (banjo_step(w, dt) == BANJO_BREAK_PENDING) {
    int n = banjo_breakable_count(w);
    for (int i = 0; i < n; ++i) {
        const char *name = banjo_breakable_name(w, i);
        int pieces = banjo_fracture(w, name, 0.003);
        if (banjo_last_outcome(w) == BANJO_BROKE)
            printf("%s broke into %d pieces\n", name, pieces);
        else if (banjo_last_outcome(w) == BANJO_DENTED)
            printf("%s held together and changed shape\n", name);
    }
}
```

### `int banjo_breakable_count(const banjo_world *world)`
### `const char *banjo_breakable_name(const banjo_world *world, int i)`

What the lattice has something to say about. Call `banjo_breakable_count` first;
it is what refreshes the list. `banjo_breakable_name` returns `NULL` for an
index out of range.

The name is a hangover from when breaking was the only thing the lattice was
ever run for. What it means is "this one needs the lattice", and a dent is one
of the things it can say.

### `int banjo_fracture(banjo_world *world, const char *name, double window_s)`

Put this body back into the lattice and run it at the impact that was caught.
Returns **how many pieces it became**; 1 means it held together.

Costs roughly a third of a millisecond per cell, so it is worth telling the user
it is happening.

### `int banjo_decline_break(banjo_world *world, const char *name)`

Let this contact pass without breaking anything. Time can move again.
**Answering is what matters, not which way you answer.** Use this when your
program is about something other than breaking — a bounce measurement, say.

### `int banjo_last_outcome(const banjo_world *world)`

What the last `banjo_fracture` turned out to be:

| | |
|---|---|
| `BANJO_NOTHING` (0) | asked about something that is not there |
| `BANJO_HELD` (1) | it took the hit and is the shape it was |
| `BANJO_DENTED` (2) | still one piece, and no longer the shape it was |
| `BANJO_BROKE` (3) | it came apart |

The piece count alone cannot tell "held exactly as it was" from "held, but bent
out of shape" — both are one piece — which is why this exists.

---

## Reading the world

### `int banjo_body_count(const banjo_world *world)`
### `int banjo_bodies(const banjo_world *world, banjo_body *out, int max)`

Fills up to `max` and returns how many were written. **Ask the count first: a
fracture changes it.**

```c
typedef struct {
    const char *name;        /* valid until the next call on this world */
    const char *material;    /* "oak", "alumina ceramic", ... */
    double position_m[3];
    double orientation_wxyz[4];
    double velocity_m_s[3];
    double dimensions_m[3];
    int shape;               /* BANJO_SHAPE_BOX / _SPHERE / _HULL */
    int anchored;            /* scenery: does not move, cannot be picked up */
    int held;
    unsigned rgba;
} banjo_body;
```

`BANJO_SHAPE_HULL` means a piece that broke or bent. Its cells **are** its
surface and no primitive fits; `dimensions_m` is then the bounding box of those
cells, which is enough to place a proxy but is not the real outline.

A body that came through a collision whole keeps the shape it was authored as —
a ball that cracked a pane is still a sphere.

### `int banjo_impact_count(const banjo_world *world, double quiet_speed_m_s)`
### `int banjo_impacts(const banjo_world *world, double quiet, banjo_impact *out, int max)`

Contacts since the last batch of stepping began, hardest first. `quiet` drops
the gentle ones — two things leaning on each other are not an impact.

```c
typedef struct {
    const char *struck;
    const char *by;                /* "" when it was the ground */
    double closing_speed_m_s;
    double threshold_speed_m_s;    /* below this, nothing CAN break */
    double dent_speed_m_s;         /* below this, nothing CAN take a set.
                                      Infinite for a brittle material. */
    double energy_j;
    int would_break;
    int would_dent;
} banjo_impact;
```

Impacts **accumulate across a batch** and the hardest of each pair survives.
That matters: a host almost never steps once, and keeping only the last step's
contacts meant three in four were thrown away before anyone could read them.

---

## The hand

### `int banjo_grab(banjo_world *world, const char *name)`

Take hold of something. It stops being moved by gravity and contacts and goes
exactly where it is put, while still pushing what it runs into. Anchored scenery
refuses. Returns `BANJO_BAD_ARGUMENT` with a reason if it cannot be picked up.

### `int banjo_move_held(banjo_world *world, const double to_m[3])`
### `int banjo_release(banjo_world *world)`
### `const char *banjo_held(const banjo_world *world)`

Letting go hands it back to gravity **from rest** — it falls from where it was
left rather than carrying the hand's speed.

---

## Asking where things are

### `int banjo_pick_ray(const banjo_world *world, const double from_m[3], const double direction[3], double max_m, banjo_pick *out)`

What a ray meets first, against the shapes the solver really collides.

```c
typedef struct {
    int hit;
    const char *name;     /* "" when it stopped on the floor */
    double distance_m;    /* metres along the ray */
    double point_m[3];
} banjo_pick;
```

An empty name with `hit` true is **the ground**: something stopped the ray, but
not one of the scene's bodies. "It hit the floor" and "it hit nothing" are
different answers and anything pointing at the world has to tell them apart.

`max_m` of 0 means a sensible default. Costs no step and changes nothing —
measured at 0.02 ms per call — so this is how you ask "what is under the
pointer", "can this see that", "is anything in the way".

```c
banjo_pick under;
banjo_pick_ray(w, (double[3]){0, 6, 0}, (double[3]){0, -1, 0}, 0, &under);
if (under.hit && under.name[0])
    printf("%s, %.2f m down\n", under.name, under.distance_m);
```

---

## The scene format

A JSON object. `bodies` is required; everything else has a default.

```json
{
  "plasticity": true,
  "bodies": [
    {
      "name": "pane",
      "shape": "box",
      "material": "glass",
      "dimensions_m": [0.6, 0.02, 0.2],
      "center_m": [0, 0.41, 0],
      "velocity_m_s": [0, 0, 0],
      "anchored": false
    }
  ]
}
```

| field | meaning |
|---|---|
| `name` | how everything else refers to it. Must be unique. |
| `shape` | `"box"` or `"sphere"`. A sphere uses `dimensions_m[0]` as its diameter. |
| `material` | one of `iron`, `aluminum`, `glass`, `ceramic`, `oak`, `rubber`, `ice`, `concrete` |
| `dimensions_m` | width, height, depth. **Each side must be a whole number of cells.** |
| `center_m` | its centre. y is up, the floor is y = 0, so a thing resting on the floor has its centre at half its own height. |
| `velocity_m_s` | what it is already doing at t = 0 |
| `anchored` | scenery: it does not move, cannot be picked up, and is never judged for breaking |
| `rotation_deg` | optional, for a tilted body |

Scene-level settings, read from the same document:

| field | meaning |
|---|---|
| `plasticity` | **off unless you ask.** Without it every bond springs back to its rest length, nothing can hold a shape it was pushed into, and nothing can dent. |
| `hardening_ratio` | how much a material stiffens as it yields. 0 is perfect plasticity. |

Two mistakes worth naming because everyone makes them:

- **A side that is not a whole number of cells is refused.** At a 0.02 m cell,
  0.3 m is fine and 0.05 m is not.
- **Putting something at y = 0 buries half of it.** The centre is the middle.

---

## Errors

Anything below zero is a failure and leaves the world unchanged.
`banjo_last_error()` returns a sentence, not a code.

```c
banjo_world *w = banjo_open(scene, 0.02);
if (!w) { fprintf(stderr, "%s\n", banjo_last_error()); return 1; }
```

`BANJO_BAD_ARGUMENT` is the caller's mistake — a name that is not in the scene,
a ray with no direction, a step with a dt that is not positive. `BANJO_ERROR` is
the engine's.

---

## Caps

| | |
|---|---|
| 250 bodies | past this the reversible trial stops being used, and **fracture stops working**. Impacts are still reported, but they describe collisions that have already been resolved. |
| ~16,000 cells | the lattice lane's budget for a whole scene |
| one world per thread | not internally locked |

The 250-body cap is the one that bites: a single concrete plate can come apart
into ninety pieces, so a scene that starts at sixty bodies can cross it in two
good hits. Watch `banjo_body_count` and say something before it goes quiet.
