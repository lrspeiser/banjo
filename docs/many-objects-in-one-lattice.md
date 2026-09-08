# Many objects in one lattice

Built 2026-09-08 on `agent/integration`, answering: *"the next step should allow
us to have more in the sim where I can pick up an object and drop it on another
and there are many different objects and shapes."*

## What was in the way

A scene was one box tile struck by a `SphereState`: a centre, a velocity, a
radius, a mass and an inertia. Six numbers. The striker could not deform, dent,
break or carry a material. A world in which only the thing being hit is made of
matter is not a world, and this had already been raised once as a defect.

## What it turned out to cost

Nothing in the solver. The fast lattice never asks what material it is stepping.
Node mass is per node; compliance and all six damage thresholds are per bond.
Node-to-node contact acts on any pair that no live bond joins, which is exactly
the condition between two separate objects, and the pair carries no bond record
at all when the nodes belong to different objects. The `loose_cells` mode had
already proved the case: it deletes every bond and lets contact alone hold a
heap of independent cells apart.

So many objects in one lattice is concatenation. `src/matter/LatticeMerge.cpp`
places each part's nodes about its own centre, shifts its bond endpoints,
rebuilds the adjacency, and carries a per-node mass from that part's own
density. No bond crosses a part, so the parts stay separate objects; contact is
what lets them meet.

## What had to follow

- **One clock.** The substep is the smallest bound any body asks for, measured
  per body against its own material. A stiff light object sets it for everyone.
- **One schedule.** Slab decomposition reads a box's z layers and a merged
  lattice has no single version of those, so it takes the one-block schedule.
  The bond colouring is where the parallelism is and that is unchanged.
- **One cell size.** The contact radius and the support offset are single
  numbers for the whole lattice, so every body in a scene shares the cell size.
- **A recorder that can tell objects apart.** Cells used to be written with one
  material name and one colour. They now carry the object they were generated
  in.

## The single-tile lane is untouched

`TileImpactRequest::bodies` empty means the scene the lane has always run. The
default 500-cell glass plate was compared field by field before and after: 167
physics fields, none differing. Fast-lattice, refracture and plasticity suites,
30 tests, all pass.

## Measured

Three scenes in the playground, all at 20 mm cells, all under three seconds:

| scene | objects | cells | bonds broken | pieces | wall | realtime |
|---|---|---|---|---|---|---|
| ball on a glass shelf between two iron piers | 5 | 342 | 255 | 45 | 2.7 s | 3.0x |
| tower of oak and glass struck from above | 5 | 385 | 1,796 | 138 | 2.2 s | 2.4x |
| ball rolled sideways into three glass pins | 5 | 633 | 884 | 81 | 3.9 s | 3.2x |

The pins are knocked flat and slide 1.2 m; the tower scatters, its three blocks
ending 220 to 500 mm from where they started while the iron base moves 2 mm.

## The trap this surfaced

Only the lattice phase can break anything, and it ends about 20 ms after the
last failure. A striker that starts 130 mm above what it hits arrives at 43 ms,
by which time the scene is rigid pieces in Jolt: it can knock things over but
nothing can crack however hard it lands. Every one of the first three scenes had
this, and all three read "0 bonds broken" while looking perfectly lively.

The panel now measures the gap along the direction of travel and says so before
the run: how far the object has to go, when it will arrive, and that it will
push things over rather than break them. The presets start their striker just
clear of what it hits, the same way the plate lane starts its ball 2 mm above
the plate.

## Known limits

- Bond damping and the plastic yield law are single numbers in `StepSettings`,
  so they come from the first body rather than each body's own material.
- Object-against-object contact uses one set of friction and restitution
  coefficients, not a pairwise table, so glass-on-oak and glass-on-glass are
  treated alike.
- Static scenery in the lattice phase is capped at two support planes with four
  footprints. A many-object scene therefore uses the ground plane only and makes
  its piers and floors out of matter, which is the better answer anyway.
- Resolution costs what it always did. The same shelf at 10 mm cells is two
  cells through its thickness and shatters properly at 4 m/s into 73 pieces, but
  it is 2,699 cells and 42 seconds of wall against 2.7. See
  docs/one-cell-is-not-a-plate.md.
