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

## Rolling, resolved

Torque was never the missing piece. What stopped a ball rolling was its
collision shape. A fragment becomes a convex hull of its cell corners, so a
100 mm ball at 20 mm cells is a five-facet lump with a flat bottom, and a
flat-bottomed lump sliding on a plane does not roll. That is right for the shape
it actually was.

A fragment now carries the primitive it was authored as, set wherever a
component is exactly one whole un-joined body. Only while whole: the moment it
loses a cell it is a broken piece and the hull is its real surface. A joined
group keeps the hull, because its shape is a union no primitive describes.

That exposed a worse bug underneath. `generateSphereLattice` samples partial
occupancy, so rim cells hold a fraction of a cell's mass with sparse degenerate
neighbourhoods. They read fabricated strain and fail on the first substep.

| 100 mm iron at rest, 10 mm cells | bonds broken | peak stretch | rank-deficient reads |
|---|---|---|---|
| as a cube | 0 of 12,876 | 0.00000 | 0 |
| as a sphere | 5,791 of 9,477 | 0.0219 | 1,263 |

Critical stretch is 0.0024, so the sphere was reading nine times over it, at
rest, with its first failure at 0.000 ms. Every ball in every scene at that
resolution had been tearing itself apart, and most of its broken-bond count was
its own. Spheres in a scene now take the whole-cell voxel path, which is the
uniform-mass property the box generator has always had and warns about in its
own comment. The staircase that leaves costs nothing now that a whole body
collides as its authored shape.

| 100 mm iron ball | before | after |
|---|---|---|
| resting | 5,791 bonds broken | 0 |
| 5 cells across | 0.0 deg, 544 mm | 152.7 deg, 2,679 mm |
| 10 cells across | 24.4 deg, 2,302 mm | 168.1 deg, 2,629 mm |

The two resolutions now agree to 2%. They did not before.

## Tested in the playground

Asked for in words: an oak lane with ten glass pins in a triangle and an iron
ball rolled into them. The first attempt was refused, because the model buried
the pins in the lane again; the refusal named the objects, the 9.0 cells of
shared space and the height to raise them to, and went back into the
conversation. One correcting turn later it planned a scene that passed.

The run: 12 objects, 3,576 cells, 5.2 seconds. The ball rolls the whole length
of the lane, turning continuously, and seven pins are down at 0.37 s and all ten
by 0.62 s. No bonds broke, which is what bowling is.
