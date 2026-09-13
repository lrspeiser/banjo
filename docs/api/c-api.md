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

`const char *banjo_version_string(void)` says which library it is in words, for
a log line. Never parse it: the number to compare is `banjo_abi_version()`.

Current ABI: **14**, which carries two additions made side by side and then
merged, numbered apart so that one number never meant two headers:

- **13** added blades -- `banjo_make_blade`, `banjo_blades`, `banjo_cuts`,
  `banjo_forget_cuts` -- and the bounded hand that swings them, `banjo_wield`,
  `banjo_aim_held`, `banjo_hand_strength` and `banjo_hand_torque`
  (see [Blades](#blades));
- **14** added heat, chemistry and gas -- `banjo_declare`, `banjo_heat`,
  `banjo_vent`, `banjo_bodies_heat`, `banjo_gas_regions`,
  `banjo_energy_ledger`, `banjo_thermo_report`, `banjo_thermo_model`.

A library at 14 has both. Nothing that was in 12 changed.

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

### What made the world wait

### `int banjo_delay_count(const banjo_world *world)`
### `int banjo_delays(const banjo_world *world, banjo_delay *out, int max)`
### `int banjo_forget_delays(banjo_world *world)`

Working a fracture out costs between a third of a second and a second, and
every way of making the run shorter changes the answer; what is left is to not
make anyone wait for it. Whether that is working is written down. Every time a
break was waited for, seen coming, guessed at or queued is a `banjo_delay`,
`{at_s, object, kind, lead_ms, cost_ms}`: the world time, the body, what
happened, and two numbers whose meaning depends on the kind. `cost_ms` is what
the run cost, never what it spent queued.

| `kind` | what happened | `lead_ms` | `cost_ms` |
|---|---|---|---|
| `blocked` | the caller asked and waited for the whole run | | the run |
| `foreseen` | a collision was spotted coming; with a cost, a run started early and then used | the warning; with a cost, how far out its predicted speed was, in per cent | the run |
| `guessing` | a run was started for a collision that has not happened yet | the speed it expects | |
| `guess-missed` | what turned up was not what was guessed | the speed expected | the speed that arrived |
| `guess-wasted` | a run started early and was thrown away | | |
| `queued` | a break arrived while another was being worked out, and was captured rather than waited for | | |
| `precomputed` | the answer was ready before it was asked for | how long it sat waiting for a worker | |
| `held` | the pair was pinned while the answer was worked out | | |

`banjo_delay_count` says how many there are. `banjo_delays` writes at most
`max` and returns how many it wrote; its strings stay good until the next
`banjo_delay_count` or `banjo_delays`, or until the world closes.
`banjo_forget_delays` starts a fresh record and returns `BANJO_OK`: call it once
you have read what you need.

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

## Carrying too much

There are two ways something breaks here, and this is the one the contact ledger
cannot see.

Every other break starts from a **blow** — a closing speed, an impedance, an
energy. A shelf with too much stacked on it is struck by nothing at all.
Measured: a plank bridging two piers with five iron crates on it reports **no
contacts whatsoever** once everything has settled, because the contact ledger is
a ledger of impacts. Load it until it should snap and nothing would ever ask.

So it is asked separately, from statics: what is resting on it, how far apart its
supports are, and what bending that puts in it.

```c
int count = banjo_overload_count(w);
if (count > 0) {
    banjo_overload *sagging = malloc(count * sizeof *sagging);
    int n = banjo_overloaded(w, sagging, count);
    /* sagging[i].name is also in banjo_breakable_name() */
}
```

### `int banjo_overload_count(const banjo_world *world)`
### `int banjo_overloaded(const banjo_world *world, banjo_overload *out, int max)`

```c
typedef struct {
    const char *name;
    double carrying_n;      /* stacked on it, not counting its own weight */
    double span_m;          /* how far apart the things holding it up are */
    double stress_pa;
    double strength_pa;
} banjo_overload;
```

For a simply supported span `L` of section `b × d`, under a central load `W` and
its own weight `w` per metre:

    stress = 3 W L / (2 b d²)  +  3 w L² / (4 b d²)

Like every bound in this engine, past `strength_pa` is **necessary and not
sufficient**: it says the lattice is worth running. The formula assumes the load
is in the middle and the ends are free to rotate — the worst case for both — so
it errs towards asking.

**The span is what decides it.** A beam supported along its whole length has no
span and cannot be bent, which is the honest reason a plate lying flat on the
floor will not break however much is piled on it. Measured: the same five crates
on the same plank, with a bench underneath, report nothing.

**`banjo_fracture` on one of these puts it into the lattice *with its load on
it*.** An island is normally built from the contact that caused the break, and a
sustained load has no contact — so an overloaded shelf went into the lattice on
its own, with nothing pressing on it, and came out whole however much was piled
on. With its crates: a stone shelf at 5.46 MPa against concrete's 3 came out in
**26 pieces**.

**`banjo_decline_break` matters more here than for a blow.** A load does not go
away by itself, so an undeclined shelf is offered on every survey for ever.

The survey runs at a stride — four times a second, not sixty — because load does
not change in a quarter of a second and the survey is O(bodies²).

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

### `int banjo_fix(banjo_world *world, const char *a, const char *b, const double at_m[3], const double axis[3], double holds_tension_n, double holds_shear_n)`

Two bodies held together as **one piece**: a peg, a bracket, a nail, a bolt, a
door catch, a locking bar, a rope anchor. All six degrees of freedom are held,
and whatever their relative pose is when the fixing is made is the pose they
keep — that is what "defined alignment" means here. It is defined by where they
are when the peg goes in, which is how a peg works.

```c
double at[3] = {0.0, 1.4, 0.2}, along[3] = {1.0, 0.0, 0.0};
int bar = banjo_fix(w, "jamb", "locking bar", at, along, 0.0, 0.0);
/* ... later ... */
banjo_unhinge(w, bar);          /* the latch is lifted */
```

**Two strengths, because they fail at different loads.** A peg pulled straight
out and a peg sheared sideways are not the same test. `axis` is the direction
the peg points: **tension is along it, shear is across it.** Either exceeded and
the fixing parts, reported once with `attached` 0, exactly like a rope. Measured
on a 618 N bracket hanging off a wall: `tension_now_n` of 6.5×10⁻¹⁷ and
`shear_now_n` of 617.586 — a hanging weight is *entirely* shear, and a fixing
with no tension strength at all holds it.

Zero means it never lets go on its own. That is a **weld**, and welds are a real
thing to want.

**Releasing it changes what the assembly is**, and that is the difference between
a latch and a very stiff hinge. Measured: the same shove on the same gate moved
it **1.66 degrees** with a bar across it and **18.76** without. Nothing about the
gate changed.

One practical caution. A bar fixed to both a jamb and a gate that is itself
hinged to that jamb is a **closed loop** of constraints, and an iterative solver
splits its error around one. A light bar restraining a heavy gate is the case
that shows: measured, a 5 kg oak bar on a 142 kg gate let it move as far as no
bar at all, and a 60 kg iron bar — a mass ratio of two rather than thirty — held
it. If a fixing seems soft, look at the mass ratio before looking at the
constraint.

### `int banjo_reeve(banjo_world *world, const char *a, const char *b, const double at_a_m[3], const double at_b_m[3], const double over_a_m[3], const double over_b_m[3], double ratio, double length_m)`

A rope from one thing, over two fixed points, to another — a **hoist**. Pull one
end down and the other comes up, because the rope's length cannot change.

```c
double at_grate[3] = {0.0, 1.04, 0.14}, at_weight[3] = {1.6, 2.16, 0.14};
double over_grate[3] = {0.0, 2.4, 0.14}, over_weight[3] = {1.6, 2.4, 0.14};
int winch = banjo_reeve(w, "grate", "counterweight",
                        at_grate, at_weight, over_grate, over_weight,
                        0.35, 0.0);
```

This is the **ideal** pulley: a relationship between cable lengths,

    |a - over_a|  +  ratio * |b - over_b|  <=  length

with no wheel (so no wheel inertia or bearing friction) and no rope wrapping (so
it cannot slip or come off its sheave). `banjo_tie` is the physical alternative —
a run of bodies draped over something, with real wrap and real friction, at a
body per segment. Both are here on purpose; reach for this when you want the
hoist to work, and for that when the rope itself is what is being watched.

**`ratio` multiplies `b`'s run, and the direction is the thing to get right.**
The constraint puts force `λ` on end `a` and `ratio × λ` on end `b`. So a
counterweight hung at `b` arrives at `a` **divided by the ratio**:

| you want | ratio |
|---|---|
| a light counterweight to balance a heavy load at `a` | **below 1** |
| a plain redirect, 1:1 | 1 |
| `b` to move further than `a`, for less force | above 1 |

Measured, and this cost an afternoon: at a ratio of 3, a 3.95 kN counterweight
showed a rope tension of **1.32 kN** — its own weight over three — and an 800 N
heave could not shift a 12.3 kN portcullis at all. At **0.35** the same
counterweight carries 11.29 kN, the grate sits down by 1.03 kN, and a person
finishes the lift. What a low ratio costs is distance: the grate rises 0.35 m
for every metre hauled.

Like a rope it pulls and does not push, so a counterweight resting on the floor
is not dragged anywhere when the other end is lifted. `length_m` of 0 means "as
it is rove".

### `int banjo_spring(banjo_world *world, const char *a, const char *b, const double at_a_m[3], const double at_b_m[3], double rest_m, double stiffness_n_m, double damping_n_s_m)`

An elastic element between two points: a **bow limb**, a spring, a bent plank —
anything that stores energy by being deformed and gives it back.

```c
double root[3] = {0.35, 2.1, 0.0}, tip[3] = {0.15, 2.4, 0.0};
int limb = banjo_spring(w, "riser", "upper tip", root, tip,
                        0.0,        /* rest: as it stands */
                        4000.0,     /* newtons per metre */
                        0.0);       /* the declared loss */
```

**This is a declared simplified model**, and which one matters:

    force  = stiffness * (length - rest)
    stored = stiffness * (length - rest)² / 2

Hooke's law with viscous damping. It has no mass of its own, no internal stress,
no yield, no hysteresis, and it does not care which way it bends. A real bow limb
has all of those.

**It is validated rather than asserted** — `tests/elastic_tests.cpp`:

| check | result |
|---|---|
| a known load against the extension | 100 / 200 / 400 N settled at 49.94 / 99.88 / 199.75 mm (Hooke: 50 / 100 / 200) |
| the work integral of a draw | 55.85 J against a claimed 55.60 |
| energy back as motion | **98.06%** |
| the declared loss | 400 N s/m turned 54.5 J of return into 14.2 |
| four times the stiffness | 1.85× the speed (model: 2) |
| eight times the mass | 2.70× slower (model: 2.83) |

Hooke's law is checked with a **known load against the measured extension**, not
force against extension — the latter would only restate the formula, because
`force_n` is computed *from* the extension.

**It pushes as well as pulls.** Leaned on with 300 N it squashed 149.8 mm and
pushed back with 299.6 N. A thing that only pulls is a rope: use `banjo_tie`.

`rest_m` of 0 means "as it stands". `damping_n_s_m` is the declared loss and
should be the only thing that takes energy out.

`banjo_joints` reports `rest_m`, `stiffness_n_m`, `damping_n_s_m`, `force_n` and
`stored_j` for one of these, and `at` is its current length.

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
**degrees** and `friction` in newton metres; a slider, a link and a pulley report
them in **metres** and newtons. Reading a slider's `0.8` as degrees gives a portcullis
fifty-seven times too tall.

A fixing holds every degree of freedom, so it has no `at`, `lower` or `upper` to
report; what it has instead is `tension_now_n` and `shear_now_n` against
`holds_tension_n` and `holds_shear_n`.

For a link, `at` is how far apart the two ends are, `upper` is the length it is
tied to, and `lower` is 0 — because nought-to-length is exactly what a rope is.
For a pulley, `at` is the whole run (one side plus the ratio times the other),
`upper` is the rope's length, and `ratio`, `over_a_m` and `over_b_m` describe
the machine. `tension_n` is meaningful for links and pulleys; `breaks_at_n` only
for links.

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

## Blades

A blade is an ordinary body with a declared **edge**. There is no cutting power
and nothing is destroyed on touch: what resists an edge is the target's own
fracture energy and hardness, applied in the solver, and the only way the world
changes is that bonds between cells are severed, each for the work it cost. The
model, and what it does not capture, is [../cutting-model.md](../cutting-model.md).

### `int banjo_make_blade(banjo_world *world, const char *body, const double heel_m[3], const double tip_m[3], const double facing[3], double thickness_m, double edge_radius_m, double bevel_deg, const double grip_m[3])`

Give a named body an edge. Everything is given where it is in the world now and
kept in the body's own frame from then on. Both ends of the edge must lie on the
body's matter, and the edge must face OUT of it, away from its matter: an edge
on a bar's far face declared facing back into the bar is refused. `facing` is
squared up against the edge, so roughly perpendicular is enough.
`edge_radius_m` is how sharp it is — 0.0002 is a working sword edge, 0.00005 a
keen one — and `bevel_deg` the included angle of the edge. Returns the blade's
id, above zero, or a negative status; `banjo_last_error` then says which rule
the edge broke.

(`make_blade` because C will not let a function and a struct share a name.)

### `int banjo_blade_count(const banjo_world *world)`
### `int banjo_blades(const banjo_world *world, banjo_blade *out, int max)`

```c
typedef struct {
    unsigned id;
    const char *body;
    const char *material;
    double heel_m[3], tip_m[3];   /* the edge, heel to tip, in the world now */
    double facing[3], flat[3];    /* the way it faces; the normal to its flats */
    double grip_m[3];
    double thickness_m, edge_radius_m, bevel_deg;
    double cut_area_m2;           /* everything it has cut */
    double cut_work_j;            /* and the work that cost, as the solver applied it */
    const char *cutting;          /* what the edge is in right now, "" for nothing */
    int attached;                 /* 0 once the body carrying it has gone */
} banjo_blade;
```

### `int banjo_cut_count(const banjo_world *world)`
### `int banjo_cuts(const banjo_world *world, banjo_cut *out, int max)`
### `int banjo_forget_cuts(banjo_world *world)`

Every meeting between an edge and something else, from first touch until they
part — **including the ones that cut nothing**, because "the flat hit it" is an
answer a host has to be able to give. `banjo_forget_cuts` drops the ones that
are over; open ones stay.

```c
typedef struct {
    const char *blade, *target, *kind;
    double at_s;
    double speed_m_s, into_m_s, along_m_s, across_m_s;  /* in the blade's axes */
    double resistance_j_m2;   /* R = G + H w for this edge in this material */
    double area_m2, work_j;   /* what it cut, and what that cost */
    int bonds;                /* severed */
    int links;                /* rope links severed */
    int separated, pieces;    /* the target came apart, into how many */
    int open;                 /* still in contact */
} banjo_cut;
```

`kind` is decided from geometry and motion, never from names: `edge`, `slice`
and `press` bit (mostly into the material, mostly along the edge, or slowly);
`glancing`, `flat` and `point` met it some other way and were ordinary
contacts; `blunt` means the target is at least as hard as the blade; `brittle`
that it has no yield point, and cracks under a blow rather than being cut.
`work_j` is always `area_m2` times `resistance_j_m2`.

### `int banjo_wield(banjo_world *world, const char *name, const double grip_m[3])`
### `int banjo_aim_held(banjo_world *world, const double orientation_wxyz[4])`
### `int banjo_hand_strength(banjo_world *world, double newtons)`
### `int banjo_hand_torque(banjo_world *world, double newton_metres)`

Take hold of a body the way a person holds a sword: at a point on it, with a
hand whose force and torque are **bounded** — 800 N and 60 N m unless told
otherwise. `banjo_move_held` then says where the grip should be and
`banjo_aim_held` which way the body should face; the hand pulls and turns
towards both with what it has, and what the body meets can slow it, turn it
aside or stop it. This is not `banjo_grab`, which carries a loose body exactly
where it is put — placement, an editor's move — and stays exactly that.

```c
double heel[3] = {0.29, 1.005, 1.885}, tip[3] = {-0.405, 1.005, 1.885};
double facing[3] = {0, 0, -1}, grip[3] = {0.35, 1.005, 1.9};
int id = banjo_make_blade(w, "sword", heel, tip, facing, 0.01, 0.0002, 30.0, grip);
banjo_wield(w, "sword", grip);
banjo_move_held(w, (double[3]){-0.9, 1.5, 1.9});   /* the hand pulls; the world answers */
for (int i = 0; i < 240; ++i) banjo_step(w, 1.0 / 240.0);
```

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

## Heat, chemistry and gas

A world can hold matter that reacts, heat that moves and gas that pushes. The
design, the models and what was measured are in
[thermochemistry.md](../thermochemistry.md); this is the interface.

**One energy convention.** Every substance has `u = u0 + cv T` per kilogram,
from 0 K. A body or a gas stores ONE internal energy and its temperature is
derived from it, never set. `chemical_j` and `thermal_j` below are the reference
and sensible parts of that one number -- two views, not two stores.

**Burning is a result.** An oak log burns because oak is dry wood, moisture and
ash (its material's composition) and it is hot enough with air around it.
Nothing has a burn time: `remaining_s` is the fuel left over the rate it is used
now, an estimate under current conditions.

### `int banjo_declare(banjo_world *world, const char *json)`

Declare into a running world. The same keys a scene's `thermo` block takes, plus
`contents` as a list:

```json
{"contents": [{"body": "log", "contents": {"dry wood": 1}, "temperature_k": 900}],
 "gas_regions": [{"name": "cylinder gas", "contents": {"argon": 1},
                  "piston": "piston", "height_m": 0.4, "balance": true}],
 "heaters": [{"target": "log", "power_w": 10000, "seconds": 60}]}
```

A heater declared here starts now. A key the network does not know is refused
**by name** (`BANJO_BAD_ARGUMENT`) -- a misspelt `tempreature_k` silently ignored
is a log at room temperature that somebody believes is alight.

### `int banjo_heat(banjo_world *world, const char *target, double power_w, double seconds)`

Heat a body or a gas region from now: external work, counted as `heater_in_j`.
Returns the heater's id. Whether it lights anything is the model's answer -- on
the demonstration model, 10 kW for a minute lights a lone oak log and 5 kW does
not, and two logs on a stone hearth need about 10 kW under each for 90 s.

### `int banjo_vent(banjo_world *world, const char *region, int open)`

Open or close a gas region's opening to the surroundings.

### `int banjo_body_heat_count(const banjo_world *world)`
### `int banjo_bodies_heat(const banjo_world *world, banjo_body_heat *out, int max)`

Every body the network holds: `temperature_k` (the surface -- what glows and
burns), `core_temperature_k`, `mass_kg`, `fuel_kg`, `heat_release_w`,
`fuel_use_kg_s`, `remaining_s` (`INFINITY` when nothing burns), `heater_w`,
`gained_w` (from other bodies), `lost_w` (to the surroundings), `reacting`,
`declared`. A body nothing has heated is not in the network and not listed.

### `int banjo_gas_region_count(const banjo_world *world)`
### `int banjo_gas_regions(const banjo_world *world, banjo_gas_region *out, int max)`

Every gas region: derived `temperature_k` and `pressure_pa`, `volume_m3`,
`mass_kg`, `moles`, the `piston` it pushes on, where its column starts
(`base_m`), which way it grows (`axis`), `area_m2`, `height_m`, `stroke_m`,
`force_n` (net of the surroundings' pressure), and the boundary work:
`work_to_bodies_j` and `work_to_atmosphere_j`.

**How the work is made to agree.** The force for a step is the pressure at its
start times the area, pushed onto the body inside the step's reversible trial;
after the step the gas is charged exactly that force times the displacement that
happened. What the gas pays and what the body receives are the same product. A
refused step takes the push, the fuel, the gas and the heat back with it.

### `int banjo_energy_ledger(const banjo_world *world, banjo_energy *out)`

```
stored_j - initial_j = heater_in_j - heat_to_surroundings_j + matter_in_j - matter_out_j
                     + joined_j - left_j - work_to_bodies_j - work_to_atmosphere_j
                     + numerical_j + residual_j
```

Every term but `residual_j` is added up where it happens, so `residual_j` is
rounding: 1.6e-11 J on a heated piston after 120 s, 8.7e-6 J on 1.8e8 J stored
for a burning hearth. `numerical_j` is energy the arithmetic had to add to keep
something physical -- reported, never hidden, and zero in every run so far.
`mechanical_j` is a separate view: the solver's own kinetic and gravitational
energy of every body.

### `const char *banjo_thermo_report(const banjo_world *world, int with_model)`
### `const char *banjo_thermo_model(void)`

All of the above as JSON; with `with_model`, every substance and reaction with
its **provenance** (`demonstration`, `reference-derived`, `experimentally
validated`), the compositions of the catalogue's materials, and what is not
modelled. `banjo_thermo_model` needs no world.

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
| `contents` | optional: what it contains, by mass fraction of its own mass -- `{"dry wood": 0.7, "moisture": 0.3}`. Left out, it is made of what its material is made of. |
| `temperature_k` | optional: how hot it starts. The surroundings' temperature (293.15 K) by default. |

Scene-level settings, read from the same document:

| field | meaning |
|---|---|
| `plasticity` | **off unless you ask.** Without it every bond springs back to its rest length, nothing can hold a shape it was pushed into, and nothing can dent. |
| `hardening_ratio` | how much a material stiffens as it yields. 0 is perfect plasticity. |
| `thermo` | heat, chemistry and gas that are not one body's: `gas_regions`, `heaters`, `ambient`. See [Heat, chemistry and gas](#heat-chemistry-and-gas). |

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
