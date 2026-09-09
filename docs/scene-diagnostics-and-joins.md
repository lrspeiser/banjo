# Why a scene detonates, and how to join two objects into one

Measured 2026-09-08 on `agent/integration`, from: *"the ball doesn't roll, the
entire floor and everything just blows up"*, and *"how do we have the physics
engine understand when we overlap two cells and provide that as an error to the
llm so it can fix it... make sure that our ability to debug issues are as
powerful as our ability to build physics items."*

## What was actually wrong

Nothing in the physics. The scene the model built put every pin and the ball at
ground level, but the lane also occupied 0 to 20 mm, so thirteen of the ninety-one
object pairs began exactly one cell inside each other. Node contact then has to
undo a full cell of interpenetration across hundreds of node pairs on the first
substep, and the scene detonates. Objects do not settle before a run; they start
exactly where they are put.

## The report

`fracture_lab.check_scene` returns every fault at once, in the terms the scene
was written in, because whoever is fixing them pays for each round trip. On the
scene above: 13 errors and 2 warnings.

| code | severity | what it catches |
|---|---|---|
| `below_ground` | error | an object whose centre is less than half its height up |
| `overlap` | error | two objects sharing space, reported in cells and in mm of depth, with the height to raise one to |
| `joined_overlap` | info | the same overlap where both carry the same join name, which is deliberate |
| `unsupported` | warning | an object at rest with nothing under it, so it starts by falling |
| `one_cell_thick` | warning | no bending stiffness at all (docs/one-cell-is-not-a-plate.md) |
| `late_strike` | warning | a striker that arrives after the 20 ms window in which anything can break |

Errors stop the run. Warnings do not: they are things worth knowing about a
legitimate scene.

## Joining, which is overlap done on purpose

Two bodies with the same `join` name are voxelised onto the one shared cell grid
and unioned. A cell both shapes claim is built once, and bonds are generated
across the whole union by the same neighbour rule every other lattice uses, so
they come out as one object rather than two touching ones. That is a handle on a
blade, a leg on a table, a spout on a jug.

The same knife, with and without the join:

| | cells | bonds | pieces |
|---|---|---|---|
| joined | 542 | 6,317 | 2, the knife and the block |
| not joined | 552 | 6,388 | 20, the blade and handle blow apart |

Ten cells were claimed by both shapes and built once. `generateVoxelLattice` in
`src/matter/Lattice.cpp` is the new generator; it takes an arbitrary set of
occupied cells, which is also the route to shapes no box or sphere can make.

A join takes one material, the first body's. Per-bond stiffness and strength
come from the material at generation time, and blending two across a seam is not
built, so a wooden handle on an iron blade is iron.

## Friction, gravity and rolling

Three questions, one scene, objects far enough apart that none touches another.

**Gravity acts continuously on everything, and it is right.** A cube released in
mid air fell 216.1 mm in the 150 ms after the handoff. Free fall over that
interval, starting from the speed it already had, predicts 213 mm. That is 1.4%.

**Friction acts and brings things to rest.** A cube pushed along the ground at
3 m/s travelled 850 mm and stopped, which is a deceleration of about 5.3 m/s²,
or a coefficient near 0.54 against the ground.

**Nothing turns sliding into rolling.** The same push given to a ball moved it
557 mm and turned it 0.0 degrees, in both phases. Friction slows a body and
applies no torque to it. This is why the ball did not roll, and it is not a bug
in the contact model so much as a missing input: a body had only a linear
velocity to start with.

`SceneBody` now carries `spin_rad_s`, applied per node as `v + w x r`, and
`"roll": true` on a sphere derives the spin that rolls without slipping at the
speed already given. The same ball:

| | travelled | turned |
|---|---|---|
| sliding | 557 mm | 0.0 degrees |
| rolling | 1,524 mm | continuously |

## Unchanged

The single-tile lane: 167 physics fields compared before and after, none differ.
Fast-lattice, refracture and plasticity suites, 30 tests, all pass.
