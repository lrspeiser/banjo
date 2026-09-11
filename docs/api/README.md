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

## Four things to know before you build anything

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

### 2. A threshold is necessary, never sufficient

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

### 3. What is doing the hitting matters as much as how fast

The threshold depends on the *impedance* of the striker. The same glass pane
needs **4.5 m/s** from an iron ball and **6.7 m/s** from an aluminium one,
because aluminium is springier and transmits less of the blow.

**Mass does not enter into it.** A 111 kg iron ball and a 0.9 kg one arriving at
the same speed are judged identically, and both held. See
[materials.md](materials.md) for why, and for the limit this implies.

### 4. Cell size is the expensive number

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

---

## Where the pieces live

| | |
|---|---|
| `include/banjo/banjo.h` | the public C header, and the only file you include |
| `bindings/python/banjo.py` | the Python binding, ctypes, no build step |
| `mcp/banjo_mcp.py` | the MCP server |
| `examples/drop.c` | a complete C program, run by the test suite |
| `src/` | the engine. You do not need to read it to use this. |
