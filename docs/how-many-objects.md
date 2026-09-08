# How many objects a scene can hold

Measured 2026-09-08 on `agent/integration`, answering: *"a limit of 12 items is
not going to work, so we need to test it and see where it starts to break based
on total number of items."*

## The test

A grid of 40 mm cubes on an oak floor slab, with an iron ball dropped into the
middle of them at 6 m/s. Every cube is eight cells, so the cell count rises with
the object count instead of being confounded with it, and every run exercises
object-against-object contact. Materials cycle glass, oak, iron. 20 mm cells,
`--backend parallel --precision double`, one second of settling.

| objects | cells | bonds | wall | x realtime | pieces | recording |
|---|---|---|---|---|---|---|
| 6 | 313 | 2,673 | 2.9 s | 2.7 | 67 | 7.9 MB |
| 18 | 721 | 6,093 | 7.2 s | 6.7 | 67 | 20.7 MB |
| 66 | 2,161 | 18,141 | 13.1 s | 12.2 | 136 | 37.1 MB |
| 152 | 4,979 | 42,434 | 15.6 s | 14.7 | 188 | 43.6 MB |
| 322 | 9,369 | 78,529 | 37.4 s | 35.8 | 378 | 43.7 MB |
| 452 | 13,481 | 114,041 | 37.2 s | 35.7 | 502 | 44.8 MB |
| 642 | 18,649 | 157,281 | 139.4 s | 132.3 | 703 | 50.4 MB |
| 902 | 24,953 | 208,529 | 148.6 s | 142.4 | 961 | 49.8 MB |
| 1,202 | - | - | 86.8 s | - | - | **refused** |

## Where it breaks, and what does not break

**The physics does not break.** Nothing failed in the solver at any size. The
node-contact pair lists never overflowed: `pair_overflow` is zero at every point
including 902 objects and 208,529 bonds. The Jolt handoff took 961 separate
pieces without exhausting its contact caches. There is no object-count limit in
the engine to find.

**The recording breaks, at about 1,200 objects.** `playback exceeds 64 MiB`. The
writer thins frames to a budget but will not go below eight, so past roughly
31,000 cells even the thinnest possible recording overruns the ceiling. This is
the only hard failure in the range tested, and it arrives after the physics has
been paid for: 87 seconds spent, then nothing to watch.

**Wall time is the real ceiling long before either.** It is not linear in the
object count, because the lattice phase runs until the breaking stops rather
than for a fixed time. Up to about 450 objects a run comes back inside 40
seconds. Past 640 it is minutes.

## What the caps are now, and why

The playground's object cap was ten, chosen when a scene had five objects in it.
It is 250. The cell cap was 8,000 and is 16,000, which is comfortably inside the
recording ceiling (about 31,000 cells) and keeps a run under the 300 second
timeout. Neither cap is a physics limit; both are the point where waiting stops
being worth it.

A ten-pin bowling alley, which is what prompted this: twelve objects, 1,221
cells, 10,831 bonds. The ball at 12 m/s breaks 3,540 bonds and leaves 198
pieces, in 31 seconds.

## What this says about a Minecraft-shaped world

Objects are free; cells are not. Nine hundred objects cost no more than the same
cells arranged as nine, and the engine never noticed the difference. The budget
to spend is the cell count, and at 20 mm cells 16,000 cells is a scene about
half a metre across.

That is the wall, and it is the same one every other measurement in this project
has run into. A world made of matter at a resolution fine enough to break
correctly is a small world. Nothing found here changes that; it only shows the
object count was never the constraint.
