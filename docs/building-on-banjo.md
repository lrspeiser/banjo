# Building on Banjo

The engine is a C library. One header, one shared object, an opaque handle.
Anything that can call a C function can drive a world.

```c
#include "banjo/banjo.h"

banjo_world *w = banjo_open(scene_json, 0.01);
for (int i = 0; i < 600; ++i) banjo_advance(w, 1.0 / 120.0, 0.003);
banjo_close(w);
```

```bash
cmake --install build --prefix /somewhere
cc drop.c -I/somewhere/include -L/somewhere/lib -lbanjo -o drop
```

or, in someone else's CMake tree:

```cmake
find_package(Banjo REQUIRED)
target_link_libraries(my_app PRIVATE Banjo::banjo_c)
```

Two consumers are in the repository and both run in the test suite:
[`examples/drop.c`](../examples/drop.c), which is C and would stop compiling if
the header ever needed a C++ compiler, and
[`bindings/python/banjo.py`](../bindings/python/banjo.py), which is ctypes and
proves the point the C face exists to make.

## The one thing that is not like other physics engines

**Breaking is a conversation, not a property.**

When a step would break something, the step is *taken back* and time does not
move. The world is left one step short of the impact with the closing speed
intact, because that is the only state a fracture can start from: handing the
lattice a collision the rigid solver has already resolved is handing it a ball
that has already bounced, and it breaks nothing however hard it was hit —
measured, as 171 ms of lattice that produced one piece.

So `banjo_step` can return `BANJO_BREAK_PENDING`, and the caller has to answer:
`banjo_fracture` on each name from `banjo_breakable_name`, or
`banjo_decline_break`. A caller that ignores it gets a world frozen at that
instant for ever. That is not hypothetical — it has been hit more than once from
inside this repository.

`banjo_advance` holds the whole conversation for you and cannot leave a world
wedged. Reach for `banjo_step` only when the decision about what may break is
genuinely yours — a playground that wants to *tell* the reader what broke and
how hard it was hit has to be the one deciding.

## The threshold is necessary, never sufficient

Every impact reports `threshold_speed_m_s`: the speed below which nothing *can*
break. Above it a break is possible, not certain. The bound comes from a
deliberately generous spall argument, so clearing it is a necessary condition,
and a program that treats it as a promise is reading the derivation backwards.

The measured pair, on a 0.3 × 0.04 × 0.3 m glass pane with a 0.1 m iron ball:

| drop | arrives at | threshold | result |
|---|---|---|---|
| 0.06 m | 0.9 m/s | 4.5 m/s | under the bound, holds |
| 1.5 m | 5.4 m/s | 4.5 m/s | **over the bound, still holds** |
| 10 m | 13.9 m/s | 4.5 m/s | 78 pieces |

Support matters as much as speed. The same pane lying flat on a concrete floor
takes 8.7 m/s and holds; what breaks glass is a thin plate with a span under it.

## What it costs

`cell_size_m` is the most expensive number in the scene. Halving it costs
sixteen times as much: eight times the cells, and the timestep has to halve with
them because the internal step is bounded by the speed of sound in the material
(glass forces 0.55 µs). 0.01 to 0.02 m is the usual range.

Stepping is cheap — microseconds. Putting matter back into the lattice to break
it costs about a third of a millisecond per cell, so a fracture is worth
announcing rather than hiding inside a frame that then takes half a second.

`banjo_pick_ray` costs no step and changes nothing: 0.02 ms per call measured
through the line protocol, so ask it on every mouse move.

## What is not built in

Honest list, so nobody discovers these by hitting them:

- **No joints.** A distance spring and a world pin exist inside the C++ layer;
  the C face exposes neither. No hinge, slider, motor or ragdoll.
- **No spawning or deleting at runtime.** A world is opened from a scene and
  that is the set of bodies it has, except for the pieces a fracture makes.
- **No save and resume.** There is no way to snapshot a running world and start
  it again from there.
- **Materials are a closed set of eight**: iron, aluminum, glass, ceramic, oak,
  rubber, ice, concrete. A program cannot supply its own.
- **No character controller, vehicles, soft body or cloth.**
- **One world per thread, not internally locked.** Different worlds on different
  threads are fine; one world from two threads is not.
- **Caps**: 250 bodies for the reversible-trial path that makes fracture
  possible (Jolt's trial caps at 256), and roughly 16,000 cells in the lattice
  lane. Past 250 bodies the step is taken straight and **fracture stops
  working** — impacts are still reported, but they describe a collision that has
  already been resolved.

`PlatformWorld` is a separate, older C++ surface for authored packages and is
documented in [object-authoring-api.md](object-authoring-api.md). It is not
reachable from C and has its own, longer list of gaps.
