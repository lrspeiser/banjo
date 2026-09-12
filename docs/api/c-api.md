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

Current ABI: **8**.

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

## Working a break out without waiting for it

`banjo_fracture` above blocks for the whole run — a third of a second to a
second — and because **your loop is what drives time**, the whole world stops
with it. Everything else carries on being drawn, so what somebody watching sees
is the room freezing at the instant of an impact. For anything with a person in
front of it, use these instead.

```c
for (;;) {
    if (banjo_fracture_pending(w)) {
        if (banjo_fracture_ready(w)) {
            int pieces = banjo_finish_fracture(w);
            printf("%s came to %d pieces\n", name, pieces);
            continue;
        }
        banjo_step(w, dt);          /* the world keeps running */
        continue;
    }
    if (banjo_step(w, dt) != BANJO_BREAK_PENDING) continue;
    const char *name = banjo_breakable_name(w, 0);
    if (banjo_begin_fracture(w, name, 0.0) != BANJO_OK)
        banjo_decline_break(w, name);   /* nothing to run; answer it anyway */
}
```

### `int banjo_begin_fracture(banjo_world *world, const char *name, double window_s)`

Start the run and come straight back. `window_s` of 0 means the default.

The pair that is about to break is **pinned where it is** while the answer is
worked out. Letting it carry on means it bounces off something that is in fact
shattering and has to be put back when the answer lands — measured, an iron ball
arcs half a metre into the air and comes down again in the time the run takes,
which is a worse thing to watch than the wait it replaced.

Returns `BANJO_BAD_ARGUMENT` when there was nothing to run — anchored scenery, a
name that is not there, something in a hand. The contact was still answered, so
time can move; there is simply nothing to collect.

### `int banjo_fracture_pending(const banjo_world *world)`
### `int banjo_fracture_ready(const banjo_world *world)`
### `const char *banjo_fracture_subject(const banjo_world *world)`

Whether something is being worked out, whether the answer is in, and what it is
about. One at a time: a second request waits for the first, so do not ask while
`banjo_fracture_pending` is true. Both tests are cheap enough to ask every step.

### `int banjo_finish_fracture(banjo_world *world)`

Take the answer and apply it, waiting only if it is not ready. Returns the piece
count exactly as `banjo_fracture` does — 1 means it held — and
`banjo_last_outcome` tells held from dented. Calling it with nothing pending
returns 0 and changes nothing.

### The engine does most of this for you

`banjo_foresee` is on by default at 2.5 s. A collision seen coming has its run
**started there and then**, from where the two things are going to be, so that
by the time they touch the answer is usually already waiting. What is in the
hand is looked at too: the run for a drop somebody is lining up starts before
they let go, which matters because the warning a fall gives can never be longer
than the fall, and a short drop is shorter than the run.

Measured on a concrete pane, from the impact to the pieces: **856 ms** with none
of this, **147 ms** with foresight on a 4 m drop, **43 ms** with the hold guess
at any height. You still want `banjo_begin_fracture`, because a piece landing on
a piece is exactly what a ray cannot see coming.

---

## Sweeping the floor

A world that shatters fills with debris, and the reversible step a fracture
needs cannot run past a couple of thousand bodies. Past that the room keeps
running and **quietly stops being able to break anything** — measured, the same
iron ball onto the same 20 mm pane broke it into 71 pieces in a room of 58
bodies and left it whole in a room of 430. So sweeping is not tidying; it is how
the world stays able to do the thing it is for.

```c
double where[3] = {x, y, z};
int lots = banjo_collect(w, where, 1.2, 0);
if (lots > 0) {
    banjo_lot *haul = malloc((size_t)lots * sizeof *haul);
    int n = banjo_collected(w, haul, lots);
    for (int i = 0; i < n; ++i)
        printf("%.0f g of %s (%d pieces)\n",
               haul[i].kilograms * 1000.0, haul[i].material, haul[i].pieces);
    free(haul);
}
```

### `int banjo_collect(banjo_world *world, const double at_m[3], double radius_m, int largest_cells)`

Takes the loose pieces within `radius_m` of a point out of the world. The sweep
**happens on this call**; the result is held until the next one. Returns how
many materials came back. `largest_cells` of 0 means a sensible default: a shard
of nine cells is debris, half a pane is not.

Only what came **off** something. Anchored scenery, whatever is in the hand, and
anything that is still the object it always was all stay put — including a thing
that has been **dented**, which is a `BANJO_SHAPE_HULL` like a shard is, but is
the same object in a new shape. A dented iron ball weighs three and a half
kilograms and went into somebody's pockets as debris before that line was drawn.

The body list has changed afterwards, so ask `banjo_body_count` again.

### `int banjo_collected(const banjo_world *world, banjo_lot *out, int max)`

```c
typedef struct {
    const char *material;   /* valid until the next call on this world */
    double kilograms;
    int pieces;
    int cells;
} banjo_lot;
```

Added up by material rather than by shard, because that is the useful form:
nobody wants forty entries called `"glass plate 20mm piece 31"`, they want to
know they have 400 g of glass. The weight is the matter that was actually there
— a piece's cells are its volume, and volume times the material's density is
what has been carried away.

---

## Joints

A pin is what turns a scene into a mechanism. A door swings because a push off
its centre line makes a torque about its hinge, and stops because it meets its
travel limit or runs out of momentum. There is no "open the door" call, and
there is not going to be one: to open it, push something into it.

```c
double at[3]  = {0.0, 1.0, 0.12};      /* where the pin is, in the world */
double axis[3] = {0.0, 1.0, 0.0};      /* which way it runs: up, for a door */
int gate = banjo_hinge(w, "post", "gate", at, axis,
                       0.0, 100.0,     /* opens outward, up to 100 degrees */
                       12.0);          /* stiff enough to stay where it is put */
if (gate < 0) { /* banjo_last_error() says why */ }
```

### `int banjo_hinge(banjo_world *world, const char *a, const char *b, const double at_m[3], const double axis[3], double lower_deg, double upper_deg, double friction_n_m)`

Hangs `b` off `a`. Returns the joint's id, always above zero, or a negative
`banjo_status`.

The pin is given **where it is in the world right now**, and is kept in both
bodies' own frames from then on. That is what makes a mechanism go on working
when the whole assembly is carried across the room or turned upside down: the
pin is a fact about the two bodies, not about where they happened to be standing.

Limits are degrees **either side of where it is hung**: `lower_deg` from -180 to
0, `upper_deg` from 0 to 180. A door built shut swings `0 .. 90`; one built open
swings `-90 .. 0`. `friction_n_m` is what it takes to start it turning — zero
swings freely, and a stiff old hinge holds a door where it is left instead of
rocking back and forth.

Either end may be anchored scenery — a door on a wall is the ordinary case — but
not both, or there is nothing for the pin to move.

Two things about the geometry that cost an afternoon each:

- **Set the leaf clear of its own frame.** A door sharing space with its post is
  jammed against it, and jammed is exactly what a working hinge looks like from
  the outside: two degrees of swing and a long look at the constraint solver.
- **Hang it clear of the floor.** A door resting on the ground is held by
  friction with the ground and will not swing either.

### `int banjo_slide(banjo_world *world, const char *a, const char *b, const double at_m[3], const double axis[3], double lower_m, double upper_m, double friction_n)`

The same idea one degree of freedom the other way round: `b` is locked to `a` in
rotation and free to move along one line. A portcullis in its grooves, a sliding
door, a bolt going across a door.

```c
double at[3] = {0.0, 0.8, 0.2}, up[3] = {0.0, 1.0, 0.0};
int grooves = banjo_slide(w, "left jamb", "grate", at, up,
                          0.0, 1.5,      /* resting on the ground, 1.5 m of lift */
                          0.0);          /* and nothing holding it up there */
```

**A grate hauled up and let go falls.** Nothing in the library knows what a
portcullis is: it is a body free to move down its own axis with gravity still
acting on it, and it stops on whatever is under it, at whatever height that
thing happens to be. Push a barrel into the gateway and the grate comes to rest
on the barrel — measured, 600 mm barrel, 600 mm of clearance.

Travel is metres either side of where it is built: `lower_m` zero or less,
`upper_m` zero or more.

**Size `friction_n` against what it holds.** It is newtons, and the weight it
has to resist is real: 1.2 × 1.6 × 0.12 m of iron is 1,813 kg and 17.8 kN. A
groove gripping at 4 kN does not hold that, and from the outside it reads as
friction not working. Measured, hauled 1 m and let go: a free groove left it at
0.000 m, one gripping at twice the weight left it at 0.999 m.

A hand hauling something on a joint **pulls it**, rather than putting it where
the hand is. A carried body is placed exactly where the hand is every step,
which overrides everything it is attached to — measured, a portcullis with
800 mm of travel dragged two metres went 1.57 m up its own 0.8 m groove, with
the constraint reporting `upper = 0.8` the whole way. So anything on a joint is
pulled towards the hand along what the joint allows, and the mechanism decides
where it ends up.

### `int banjo_tie(banjo_world *world, const char *a, const char *b, const double at_a_m[3], const double at_b_m[3], double length_m, double breaking_tension_n)`

Two points that may be any distance apart **up to** a limit and no further. That
one asymmetry is the whole of what makes a rope a rope: it **pulls** and it does
**not push**. Below the length the link does nothing at all — no force, no
damping, no quiet stiffness — so slack really is slack. (A distance constraint
with a minimum as well as a maximum is a rigid rod, and a rod pushes.)

```c
double top[3] = {0.0, 3.9, 0.0}, bottom[3] = {0.0, 3.0, 0.0};
int rope = banjo_tie(w, "beam", "weight", top, bottom,
                     0.0,        /* 0 = as they stand */
                     2000.0);    /* and it parts above 2 kN */
```

**A rope is made of these, not of a rope object.** A chain is a run of small
bodies each tied to the next — which is why it hangs in a catenary (its own
segments are heavy), drapes over what it touches (its segments collide), and can
be cut anywhere along its length with `banjo_unhinge`. Measured on eight links
hanging from a beam, the tension down the chain was 632, 553, 474, 395, 316,
237, 158, 79 N — a staircase whose every step is one link's weight, because each
link carries everything below it.

`length_m` of 0 means "as they stand": the distance between the two points
given, which is what you want for a rope already laid out — and getting it wrong
by a millimetre is either a rope taut at rest or one that sags.

`breaking_tension_n` of 0 never parts. Anything else is a rope you can
overload: a parted link reports `attached` as 0, the same as a gate off its
hinges, and what was hanging on it falls. Read what a link is carrying from
`tension_n` — measured against a 617.638 N weight it reports 617.586 N, and 0 N
while the rope still has slack in it.

### `int banjo_joint_count(const banjo_world *world)`
### `int banjo_joints(const banjo_world *world, banjo_joint *out, int max)`

Fills up to `max` pins and returns how many were written. The strings belong to
the world and stay good until the next call that changes it.

```c
typedef struct {
    unsigned id;
    int kind;                  /* BANJO_JOINT_HINGE or BANJO_JOINT_SLIDER */
    const char *a;
    const char *b;
    double at;                 /* where it has got to, from where it was made */
    double lower, upper;
    double friction;
    double at_m[3];            /* where the joint is NOW */
    double axis[3];
    int attached;
} banjo_joint;
```

**`kind` is also the unit.** A hinge reports `at`, `lower` and `upper` in
**degrees** and `friction` in newton metres; a slider and a link report them in
**metres** and newtons. Reading a slider's `0.8` as degrees gives a portcullis
fifty-seven times too tall.

For a link, `at` is how far apart the two ends are, `upper` is the length it is
tied to, and `lower` is 0 — because nought-to-length is exactly what a rope is.
`tension_n` and `breaks_at_n` are meaningful only for links.

`at_m` is worked out from the body the pin is in rather than remembered, so a
gate carried across the room reports its hinge where the gate is.

**`a` and `b` change when things break, and `attached` can go to 0.** A joint is
between two NAMES rather than two bodies, because bodies do not survive breaking:
everything in an island is destroyed and rebuilt when anything in it comes apart.
So a pin whose wood is smashed follows the piece it ends up inside — a gate hung
on `"post"` can find itself hung on `"post piece 3"` — and when there is no piece
left around the pin, `attached` goes to 0 and what was hanging on it falls. That
is a gate coming off its hinges, it is reported rather than silently dropped, and
it is the one thing about a hinge a host cannot work out from the bodies alone.

### `int banjo_joint_friction(banjo_world *world, unsigned joint, double friction)`
### `int banjo_unhinge(banjo_world *world, unsigned joint)`

Newton metres for a pin, newtons for a slide. Taking the joint out drops
whatever it was holding up — both kinds; the name is historical.

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
