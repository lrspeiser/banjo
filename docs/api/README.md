# The Banjo API

Banjo simulates matter. An object is not a shape with a "breakable" flag on it:
it is cells joined by bonds, the bonds carry tension and compression, they yield
and they fail, and what happens to a thing is worked out rather than looked up.
Drop a glass ball and an iron one from the same height onto the same floor and
they do different things, because they are made of different stuff.

This is the documentation for using that from your own program.

- **[c-api.md](c-api.md)** — the C library: every function, the scene format,
  and the one thing about this engine that surprises people.
- **[materials.md](materials.md)** — the eight materials, what each actually
  does, and the measured numbers you need to design an experiment that shows
  something.
- **[mcp.md](mcp.md)** — the MCP server, so Claude or ChatGPT can run
  experiments instead of guessing at them.
- **[../cutting-model.md](../cutting-model.md)** — blades: an edge declared on a
  body, a hand with bounded force and torque to swing it, and the contact law
  that decides what an edge does to what it meets and what that costs.
- **[../building-on-banjo.md](../building-on-banjo.md)** — a shorter
  orientation, and the honest list of what is not built in.

---

## Install

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
cmake --install build --prefix /where/you/want/it
```

That gives you `include/banjo/banjo.h`, a shared library, and a CMake package.

From another project:

```cmake
find_package(Banjo REQUIRED)
target_link_libraries(my_app PRIVATE Banjo::banjo_c)
```

Or by hand:

```bash
cc drop.c -I/where/you/want/it/include -L/where/you/want/it/lib -lbanjo -o drop
```

---

## The shortest thing that works

```c
#include "banjo/banjo.h"
#include <stdio.h>

int main(void) {
    banjo_world *w = banjo_open(
        "{\"bodies\":["
        " {\"name\":\"pane\",\"shape\":\"box\",\"material\":\"glass\","
        "  \"dimensions_m\":[0.3,0.02,0.3],\"center_m\":[0,0.01,0]},"
        " {\"name\":\"ball\",\"shape\":\"sphere\",\"material\":\"iron\","
        "  \"dimensions_m\":[0.1,0.1,0.1],\"center_m\":[0,3.0,0]}]}",
        0.02);
    if (!w) { fprintf(stderr, "%s\n", banjo_last_error()); return 1; }

    for (int i = 0; i < 600; ++i) banjo_advance(w, 1.0 / 120.0, 0.003);

    printf("%d bodies now\n", banjo_body_count(w));   /* more than two, if it broke */
    banjo_close(w);
    return 0;
}
```

The same in Python, with no build step at all:

```python
import sys; sys.path.insert(0, "banjo/bindings/python")
from banjo import World

scene = {"bodies": [
    {"name": "pane", "shape": "box", "material": "glass",
     "dimensions_m": [0.3, 0.02, 0.3], "center_m": [0, 0.01, 0]},
    {"name": "ball", "shape": "sphere", "material": "iron",
     "dimensions_m": [0.1, 0.1, 0.1], "center_m": [0, 3.0, 0]}]}

with World(scene, cell_size_m=0.02) as world:
    for _ in range(600):
        world.advance(1 / 120)
    for body in world.bodies():
        print(body.name, body.material, body.position_m)
```

Two complete, runnable examples live in the repository and both run in the test
suite, so they cannot go stale:
[`examples/drop.c`](../../examples/drop.c) and
[`tests/banjo_ffi_tests.py`](../../tests/banjo_ffi_tests.py).

---

## Seven things to know before you build anything

### 1. Breaking is a conversation, not a property

This is the one that catches people.

When a step would break something, **the step is taken back and time does not
move**. The world is left one step short of the impact with the closing speed
intact, because that is the only state a fracture can start from — handing the
lattice a collision the rigid solver has already resolved is handing it a ball
that has already bounced, and it breaks nothing however hard it was hit.

So `banjo_step` can return `BANJO_BREAK_PENDING`, and you have to answer:
`banjo_fracture` on each name from `banjo_breakable_name`, or
`banjo_decline_break`. **A caller that ignores it gets a world frozen at that
instant for ever.**

`banjo_advance` holds the whole conversation for you and cannot leave a world
wedged. Reach for `banjo_step` only when the decision about what may break is
genuinely yours — a program that wants to *tell* the user what broke and how
hard it was hit has to be the one deciding.

**If a person is watching, do not use either of them to break something.** Both
block for the whole run — a third of a second to a second — and because your
loop is what drives time, the world stops with it. `banjo_begin_fracture` starts
the run and comes straight back; you keep stepping and collect it with
`banjo_finish_fracture` when `banjo_fracture_ready` says so. Most of the time
the answer is already waiting, because the engine starts the run when it sees
the collision coming — and, for a drop somebody is lining up, before they even
let go.

### 2. A world that shatters fills up, and a full world stops breaking

Fracture needs a step it can take back, and that cannot run past a couple of
thousand bodies. Past it the room keeps running perfectly and **quietly stops
being able to break anything** — the same iron ball onto the same 20 mm pane
broke it into 71 pieces in a room of 58 bodies and left it whole in a room of
430, with nothing anywhere saying why.

`banjo_collect` sweeps the loose pieces near a point out of the world and says
what they were made of, by material and by weight. That is where raw materials
come from if you are building something with them, and it is also the thing that
keeps the world able to work.

### 3. A threshold is necessary, never sufficient

Every impact reports `threshold_speed_m_s` (the speed below which nothing *can*
break) and `dent_speed_m_s` (below which nothing can take a permanent set).
Above them a break or a dent is **possible, not certain**. The bounds come from
a deliberately generous argument, so clearing one is a necessary condition, and
a program that treats it as a promise is reading the derivation backwards.

Measured, on a 0.3 × 0.04 × 0.3 m glass pane with a 0.1 m iron ball:

| drop | arrives at | threshold | what happened |
|---|---|---|---|
| 0.06 m | 0.9 m/s | 4.5 m/s | under the bound, held |
| 1.5 m | 5.4 m/s | 4.5 m/s | **over the bound, still held** |
| 10 m | 13.9 m/s | 4.5 m/s | 78 pieces |

Only running the lattice says what actually happens.

### 4. What is doing the hitting matters as much as how fast

The threshold depends on the *impedance* of the striker. The same glass pane
needs **4.5 m/s** from an iron ball and **6.7 m/s** from an aluminium one,
because aluminium is springier and transmits less of the blow.

**Mass does not enter into it.** A 111 kg iron ball and a 0.9 kg one arriving at
the same speed are judged identically, and both held. See
[materials.md](materials.md) for why, and for the limit this implies.

### 5. Cell size is the expensive number

`cell_size_m` is how finely matter is divided, and it costs about `h^-4`:
halving it gives eight times the cells, and the timestep has to halve with them
because the internal step is bounded by the speed of sound in the material
(glass forces 0.55 µs). 0.01 to 0.02 m is the usual range.

It is also the floor on how thin anything can be — one cell. Real window glass
is 4–6 mm and is not reachable at a 20 mm grid.

Stepping is cheap: microseconds. Putting matter back into the lattice to break
it costs about a third of a millisecond per cell, so a fracture is worth
announcing rather than hiding inside a frame that then takes half a second.
`banjo_pick_ray` costs nothing at all — 0.02 ms measured — so ask it as often as
you like.

### 6. A mechanism is a joint, not an animation

`banjo_hinge` hangs one named thing off another on a pin, and that is the whole
of how a door, a gate, a hatch, a lever or a drawbridge works here. There is no
"open the door" call. A door opens because you push something into it off its
centre line and the pin turns that into a torque; it stops because it meets its
travel limit, meets its frame, or runs out of momentum.

```c
double at[3] = {0.0, 1.0, 0.12}, up[3] = {0.0, 1.0, 0.0};
int gate = banjo_hinge(w, "post", "gate", at, up, 0.0, 100.0, 12.0);
```

`banjo_slide` is the same idea one degree of freedom the other way round: two
bodies locked in rotation and free to move along one line, which is a
portcullis, a sliding door or a locking bolt.

```c
double at[3] = {0.0, 0.8, 0.2}, up[3] = {0.0, 1.0, 0.0};
int grooves = banjo_slide(w, "left jamb", "grate", at, up, 0.0, 1.5, 0.0);
```

**A grate hauled up and let go falls**, and stops on whatever is under it at
whatever height that thing happens to be. If it should stay up, give the groove
friction — and size it against the weight, which for 1.2 × 1.6 × 0.12 m of iron
is 17.8 kN. A groove gripping at 4 kN holds a quarter of a portcullis.

Both are given where they are in the world right now and kept in both bodies'
own frames, so the mechanism goes on working if the assembly is carried
somewhere else or turned over. `banjo_joints` reports a `kind`, and **the kind
is the unit**: degrees and newton metres for a pin, metres and newtons for a
slide.

**A pin holds two names, and names change when things break.** Bodies do not
survive breaking — everything in an island is destroyed and rebuilt when
anything in it comes apart — so a pin whose wood is smashed follows the piece it
ends up inside, and `banjo_joints` will start reporting `"post piece 3"` where it
used to say `"post"`. When there is no piece left around the pin, `attached` goes
to 0 and what hung on it falls. Read that flag: it is the only way to find out a
gate has come off its hinges.

`banjo_tie` is the third: two points that may be up to a length apart and no
further. It **pulls and does not push**, and below its length it does nothing at
all, so slack is really slack.

A rope or a chain is made of these rather than being a rope object — a run of
small bodies, each tied to the next. That is why it hangs in a catenary (its own
segments are heavy), drapes over what it touches (its segments collide), and can
be cut anywhere along its length. Measured on eight links: tensions of 632, 553,
474, 395, 316, 237, 158, 79 N down the chain, a staircase whose every step is
one link's weight. Give a tie `breaking_tension_n` and it can be overloaded;
read `tension_n` to see what it is carrying.

`banjo_reeve` is the fourth: a rope from one thing, over two fixed points, to
another — a hoist. Pull one end down and the other comes up, because the rope's
length cannot change.

```c
int winch = banjo_reeve(w, "grate", "counterweight",
                        at_grate, at_weight, over_grate, over_weight,
                        1.0, 0.0);   /* ratio 1, length as rove */
```

This is the **ideal** pulley: a relationship between cable lengths, with no
wheel (so no wheel inertia or bearing friction) and no rope wrapping (so it
cannot slip or come off). `banjo_tie` is the physical alternative — a run of
bodies draped over something, with real wrap and real friction, at a body per
segment. Both are here on purpose.

**`ratio` applies to `b`'s run, and which end is not a detail.** `b` moves
1/ratio as far as `a` and feels ratio times the tension, so the advantage is on
`b`'s side: hang the **load at `b`** and a counterweight of load/ratio balances
it. Measured at ratio 2 — a 617.6 N load held by a 308.8 N counterweight, and
hauling that counterweight down 0.799541 m raised the load 0.39977 m. Put the
load at `a` and you need *twice* the weight, which is the same machine
backwards.

Measured in the courtyard, a winch driving a portcullis in its grooves: at rest
the rope carries 3,953 N (the counterweight's own weight, exactly), hauling it
down 1 m raises the grate 1.005 m, and letting go settles it back.

`banjo_fix` is the fifth and last: two bodies held as **one piece** — a peg, a
bracket, a catch, a locking bar. Two strengths, because a peg pulled straight out
and a peg sheared sideways fail at different loads: tension along the axis, shear
across it. Zero is a weld.

Releasing one with `banjo_unhinge` **changes what the assembly is**, and that is
the whole difference between a latch and a very stiff hinge. Measured: the same
shove on the same gate moved it 1.66° barred and 18.76° unbarred.

`banjo_spring` is the sixth: an elastic element that stores energy by being
deformed — a bow limb, a spring, a bent plank. A **declared** linear model,
`force = stiffness × extension`, validated against the work actually done
drawing it (98.06% of the stored energy comes back as motion). It pushes as well
as pulls, which is what tells it from a rope.

Together those six are enough to build a **bow** with no bow code anywhere: a
hinge at each limb root, an elastic forward of it, links for the string, and a
fixing for the nock that you `banjo_unhinge` to loose. The arrow's speed is not
chosen — it comes out of the energy in the limbs and the mass of what is nocked,
so changing the bow, the draw or the arrow changes the shot.

Two pieces of geometry that each cost an afternoon: set the leaf **clear of its
own frame** (a door sharing space with its post is jammed against it, and jammed
looks exactly like a broken hinge), and hang it **clear of the floor** (a door
resting on the ground is held by the ground).

### 7. Breaking has a second door, and it is not impacts

`banjo_step` and the contact ledger only ever see **blows**. A shelf with too
much stacked on it is struck by nothing: measured, a plank under five iron
crates reports *no contacts at all* once it has settled.

`banjo_overloaded` asks the other question, from statics — what is resting on
it, how far apart its supports are, and the bending that puts in it. Those names
also appear in `banjo_breakable_name`, because from the outside they are the same
question: this may come apart, do you want to know.

The **span** is what decides it. A beam supported along its whole length cannot
be bent, which is why a plate lying flat on the floor will not break however much
is piled on. And `banjo_fracture` on an overloaded body puts it into the lattice
*with its load on it* — a stone shelf at 5.46 MPa against concrete's 3 came out
in 26 pieces.

Pick materials with this in mind. Oak takes 90 MPa in tension and concrete takes
3, so a stone shelf is a thing you can overload by hand and an oak one of the
same size wants eighteen tonnes.

---

## Where the pieces live

| | |
|---|---|
| `include/banjo/banjo.h` | the public C header, and the only file you include |
| `bindings/python/banjo.py` | the Python binding, ctypes, no build step |
| `mcp/banjo_mcp.py` | the MCP server |
| `examples/drop.c` | a complete C program, run by the test suite |
| `src/` | the engine. You do not need to read it to use this. |
