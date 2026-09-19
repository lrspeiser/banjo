# Products made of parts: build them, break them, keep them fast

Written 2026-09-18, from the owner's three decisions of that day. It says what
a product is from the Workshop to the world, what is built, what each claim
rests on, and what is not done. [product-physics.md](product-physics.md) is the
earlier statement of the same aim ("detail in Workshop, behavior in the live
world"); this is how it is being carried out.

## The owner's decisions

1. **A product breaks in the world in two stages.** "A multi-component product
   can receive a blow and we can start by checking if the shearing forces can
   break it into sub components. Then as a sub-component we can decide if the
   hit to just that one part is enough to deform, shatter, melt it. This still
   requires fast analysis but this is my preferred approach."
2. **Build part by part** in the Workshop, not only tune a ready-made template.
3. **Once made, a product is one part in the main world.** It must be taken
   into the Workshop to break it into sub-components or recapture its raw
   materials.

Decisions 1 and 3 do not conflict. 3 is about handling and identity: one item
in the bag and in the hand, no taking apart by hand in the world. 1 is the
physics exception: a violent enough blow may still separate it.

## Why the pieces are as they are

Measured on the default cart (14 parts), with the Workshop's own model:

| cell size | cells | what happens |
|---|---:|---|
| 40 mm (most rooms) | 698 | both axles and all four bearing mounts vanish |
| 20 mm | 6,440 | everything resolves; 40% of a room's 16,000 cells |
| 10 mm | 50,408 | over the 50,000 preview cap, 3x a room |
| 5 mm | 405,088 | |

The deck is 53% of those cells and the wheels 39%; the parts where fine detail
matters (axles, mounts, handle) are 8%. Integration of intact cells is nearly
free and one break costs about 309 ms ([what-is-not-done.md](what-is-not-done.md)
section 4), so uniformly smaller voxels are not the way to a detailed product.
What a rolling cart needs in the world is its few rigid bodies and its joints;
what a breaking cart needs is detail in the one place that is breaking. That is
decision 1, and it is also what the engine already does for a single body.

## What the engine already has, and the two stages map onto it

Verified in the source on main `9c6e791`; line numbers drift, names do not.

**Stage A, a joint giving way, exists for a fixing.** `JoltWorld::JointKind::Fixing`
holds two bodies with separate `holds_tension_n` and `holds_shear_n`.
`LiveWorld::partOverloadedLinks` (after every step) reads the solver's own
constraint impulse over that step, divides by the step, resolves it along and
across the fixing's axis, and removes the constraint when either exceeds its
bound, reporting `parted_because` ("sheared across its axis", "pulled out along
its axis") with the load and the capacity. Both ends are woken; nothing is
pushed, so momentum is kept by construction. `LiveWorld::setJointMember` already
rates a fixing from a member's own section and the material catalogue
(`tensile_strength_pa * area`, `shear_strength_pa * area`) and re-rates it as
heat weakens the member (`tests/thermal_mechanics_tests.cpp`,
`theHeatedTwinWeakensByItsLawAndFails`).

Gaps: a fixing has **no bending capacity** (`GetTotalLambdaRotation` is never
read, so a long lever prying a joint is not caught); a **hinge has no strength**
and cannot break from load; and the force is the impulse of one step over that
step, which is the engine's accepted model for a sustained load and depends on
the step for a sharp blow.

**Stage B, the one struck part, exists for a lattice body.** `admitRefracture`
(`src/fastlattice/Refracture.cpp`) is "the whole trigger: no allocation, no
lattice, four multiplies": from the closing speed, the two bodies' acoustic
impedances, the bar wave speed and the body's weakest bond it bounds the peak
stretch, and gives `would_break` and `would_dent` with the speeds at which each
begins. Only an admitted body gets the lattice run. It is a necessary condition,
never a prediction ("the trigger never decides that a fragment breaks"). Heat
moves the bar: oak, iron and concrete soften by the Eurocode curves and oak
chars at 300 C (`src/thermo/ThermalMechanics.cpp`).

Gaps: a **precise-rigid body is skipped** by `judgeStep` (it has no lattice to
run); **nothing melts** in the live engine (`EnthalpyLaw` exists only in the
separate sparse thermal world; no catalogue material has a melting point); and
a thin part cannot be given a lattice at a room's cell size at all, which needs
a cell size per body.

So the product layer is what was missing, not the break machinery:

| needed | state |
|---|---|
| a design whose parts and joints are data a person can change | **built** (below) |
| what a declared joint can carry, from declared things only | **built** |
| a fast answer to "which joint goes first" while designing | **built**, as a screen |
| a joint weaker than the material it joins, in the engine | **built** (below), on the bench and in a live room |
| the same product in the world: few bodies, real joints, one item | not built |
| a joint's bending, and a bearing's load, checked by the engine | not built |
| the struck part refined on demand when it is a thin precise part | not built |
| taking a world product back into the Workshop to take apart or reclaim | not built |

## Built: a design is parts and joints a person can change

`mcp/workshop_construction.py`. An assembly such as `cart` was Python code; a
person could tune its numbers and edit one part. Three things are now data:
parts put in, template parts taken off, and joints. They travel inside
`component_overrides` under `"@construction"`, because every one of the dozen
places that rebuild a design, and every saved record, already carries the
overrides; nothing downstream learned a new field.

- **Placing.** A new part lands square on the face that was clicked, keeps the
  orientation of the part it lands on unless the face it attaches by forces a
  turn, grows out of the face, settles on its middle or flush to its edge, and
  can be twisted about the face or sunk into it (a tenon, a shaft in a bore).
- **Contact is measured, never stored.** Two square faces meet over the overlap
  polygon, with its area and second moments. A **raked** member (a splayed leg
  under a top, the cart's handle arms) is cut to sit flat, so its end bears
  over its section divided by the cosine of the rake. A **shaft** is measured
  by how much of its axis lies inside the other part.
- **A template's joints are adopted, then nothing is inferred.** The cart gives
  6 bonded, 6 pressed and 4 bearings, and reduces to the same 3 runtime bodies
  and 4 mechanisms as before. An edit that pulls two parts apart leaves their
  joint **open** and kept, so moving the part back closes it.
- **From nothing.** `kind: "custom"` starts from one part on the floor.
- The page's Build tab: choose a family or a saved component, press Place, click
  a face, see the part there see-through with what it would meet, turn it or
  sink it, add it; take the selected part off; joints listed and drawn on the
  object. Saved designs and My Library reopen as built.

## Built: what a joint can carry

`mcp/product_joints.py`. Only from things declared elsewhere: the measured
contact, and the engine catalogue's strengths of the **weaker** of the two
materials (`mcp/engine_materials.MECHANICS`, pinned preset by preset to
`src/material/MaterialCatalog.cpp` by a test that reads the C++).

| joint | carries |
|---|---|
| bonded, flat | tension `st A`, compression `sc A`, shear `tau A`, bending `st I/c` about each axis of the patch, torsion `tau J/r` |
| pressed shaft | across: the lesser of the bore crushing `sc d L` and the shaft shearing `tau pi d^2/4`; along `tau pi d L`; twisting that times `d/2`; prying `sc d L^2/6` |
| bearing | the same across and prying; free to turn; **its hold along its axis is not rated** |

This is the engine's own rule for a fixing made of a member, extended to
bending, prying and torsion. It assumes a bond as strong as the weaker material
over the whole contact, stress uniform under direct load and linear under
bending. Not modelled, and said in every answer: grain direction at the
interface, an adhesive or fastener weaker or stronger than the parts, stress
concentration, fatigue. `engine_fixing` in each answer is the pair of numbers a
native fixing takes.

## Built: which joint a push breaks first (stage A, on the bench)

`mcp/product_breakscreen.py`; in the page, **Push on it** in the Build tab.

Parts are rigid; each joint is an elastic interface whose stiffness comes from
its contact and its two materials (a rigid-body-spring model, Kawai 1978). The
loads are the push, gravity, what the floor does, and the inertia of whatever
the product is free to do: the six motions of the whole and the spin of each
body that turns on a single line of bearings ("inertia relief"). The set is
then in equilibrium and one linear solve gives what every joint transmits. For
a tree of joints the stiffnesses cancel out and the answer is free-body
statics; they only share a load between joints that carry it side by side.

**The floor pushes and never pulls.** At every foot: reaction >= 0, upward
acceleration >= 0, and one of the two is zero, with the product taken as one
rigid thing starting from rest. So it may stand, tip onto an edge or a corner,
or be lifted clear, and the answer says which and at what force it stops
staying put. The floor's grip keeps the middle of the bearing feet from sliding
and the product from turning on the spot, up to the friction on what presses
there; past that it slides. Standing still this is exactly the statics
`mcp/workshop_statics.py` already does. The floor is asked again at every force
when looking for the first joint to give, because a product that stands under a
light push may tip under a heavier one, and that changes what its joints carry.

It reports each joint's share of its strength and what it would be (pulled
apart, crushed, sheared, pried out), the force along the same line at which the
first joint goes, and what the product would come apart into.

**It is a screen and says so.** Static-equivalent: a blow shorter than the
structure's own period can load a joint up to about twice what a steady push
does, or much less. So below half of a joint's strength is `holds`, half to one
is `uncertain`, one is `gives way`. The parts are unbreakable here. It is a
calculation, so the page offers it in Build and not in Test, which shows
simulations only.

Seventeen cases worked out by hand, in glass, oak and iron
(`tests/product_breakscreen_tests.py`), none read back from the code:

- a push through the centre of mass of a free pair is shared by mass, and
  weight loads nothing in free fall;
- a push across one end sets it spinning, and the joint carries the shear of that;
- standing, each joint of a column carries the weight above it plus the load;
- a sideways push the floor holds bends a post's foot by force times height;
- what gives first is the far fibre reaching the strength: **oak crushes before
  it tears (52 against 90 MPa); glass and iron tear first**;
- a table shares a central load equally between four legs;
- the cart's four bearings carry its chassis and the push when standing, and in
  mid-air only the share of the push that accelerates the two wheelsets;
- a push past the floor's grip slides it, at the friction on its weight;
- **a block pushed over pivots on its far edge as a rigid body does**: about
  that edge `I = m (w^2 + h^2) / 3` and the torque is `F h - m g w/2`; its
  centre's acceleration, the reaction `m (g + a_y)` on the two far corners and
  the grip `m a_x - F` all come out, and it starts to tip at `F = m g w / 2h`;
- pushed up harder than its weight it leaves the floor and accelerates at
  `F/m - g`.

On the default cart, each answered in 0.1 to 0.35 s of pure Python:

| push | what it says |
|---|---|
| 3 kN down on the handle | tips onto its back wheels past about 221 N (the handle overhangs the back axle); the handle arms' small raked feet on the deck's edge go first, crushed, at about 560 N, and it comes apart into the chassis and the handle with its two arms |
| 1.5 kN on the deck | stands; every joint below 4%; the wheel hubs on their axles would go first, near 46 kN |
| 2 kN sideways on a wheel | slides past about 211 N; the bearings carry 30% of their strength and would go first near 6.6 kN |

The first is a finding about the template -- someone leaning their weight on
that handle -- and the kind this is for.

## Built: a joint is weaker than the wood it joins, in the engine

[Issue #20](https://github.com/lrspeiser/banjo/issues/20). A Workshop product
compiles to ONE fused lattice, so a bond between a leg's cell and the top's was
an ordinary oak bond: a broken table already came apart at its joints, but every
joint was as strong as the wood. A glued or dowelled joint is a fraction of it;
a weld is nearly all.

Three things were missing, and none of them was the mechanism.

**What each way of making a joint keeps** (`mcp/joint_efficiency.py`), declared
the way `src/thermo/ThermalMechanics.cpp` declares the heat curves: every number
carries its source and what it does not cover, and a demonstration value says so
in the answer rather than in a comment.

**None of these numbers is in force.** The owner's call, 2026-09-19: leave
every joint at the material's own strength for now, ship the mechanism inert,
and set the figures deliberately later, because a number below 1 is a
declaration about real joints and is theirs to make rather than something that
arrives with an implementation. So the column below is what each source would
support, recorded as `proposed` beside a law that currently keeps the material
whole. A law that keeps everything is not declared to a scene at all, so no
product breaks differently than it did, and putting the figures in force is an
edit to one table.

| joint | proposed tension | proposed shear | compression | where from |
|---|---:|---:|---:|---|
| bonded, side grain, or a weld | 1.0 (nothing pending) | 1.0 | 1.0 | a properly made side-grain glue joint fails in the wood beside the bond line, not in it (Wood Handbook FPL-GTR-190 ch. 10); a full-penetration weld with matching filler develops the base metal (AWS D1.1, EN 1993-1-8) |
| bonded, end grain butted on | 0.25 | 0.25 | 1.0 | an end-grain butt joint cannot be made to hold more than about a quarter of a comparable side-grain one -- the open cells drink the adhesive (same chapter). It is why scarf and finger joints exist. The quarter is the source's figure for TENSION; the same share for shear is an assumption |
| pressed fit | 0.15 | 0.15 | 1.0 | **demonstration.** A press fit holds by friction, and the interference, finish and moduli it follows from are declared nowhere in a design, so no number can be derived. A design that turns on it should declare its interference |
| a bearing | -- | -- | -- | not a bond at all. What holds a wheel on its axle -- a pin, a washer, a nut -- is not in the design, so neither weakening it nor welding it would be that. Left as the material's own, and said |

**Compression is 1.0 in every law, and that is physics, not a default.** Two
parts pushed together bear on each other: an end-grain joint that holds a
quarter of the wood in tension carries all of its compression, because there the
glue line is not what is carrying.

Which law a joint gets is read from the design, not chosen: the grain runs along
a part's longest side (which is how timber is cut, and why a strut is a strut),
so a face looking along that side is end grain. A material has a grain only if
the catalogue says so -- `anisotropy_ratio` above 1, which is oak and nothing
else. The same shapes in iron are a weld and keep everything. A part with no
single longest side, a cube or a disc, is taken to show end grain, because for a
strength answer that is the safe way to be wrong.

**Which part a cell came from, surviving the join.** A product's cells were
decomposed as one heap of boxes, so the engine could not tell an interface bond
from an interior one. They are now decomposed component by component
(`decompose_by_part`), every box carries `part`, and the union is unchanged
because the components partition the cells. A cell two parts both claim is the
first's -- the rule by which the lattice already builds it once.

**The bond law, in one place.** `weakenBond` moved from an anonymous namespace
in `LiveWorld.cpp` to `matter/Lattice.hpp`, beside the bond it acts on, with
`BondFactors` as its input. Heat and joints are now the same function: heat
supplies factors per zone, per fracture run; a joint supplies them once, at
asset build, so a product carries its joints from the moment it exists and a
blow, a landing, the admission bound and the fracture run all read the same
bonds. Nothing else changed.

**Measured with the end-grain quarter put in force**, to show that the
mechanism does what it says -- not how anything behaves today, because today
every law is whole and the left-hand column is what happens. Default oak table,
20 mm cells, dropped on its top:

| drop | as it is today (every law whole) | were the quarter in force |
|---|---|---|
| 1 m | holds | holds |
| 2 m | holds | **two legs off** |
| 4 m | holds | **all four legs off** |
| 6 m | holds | all four legs off |
| 10 m | 63 pieces, none leg-sized | 111 pieces, and the four legs still come off whole |

With the quarter in force the bar a blow has to pass falls from **13.75 to
3.44 m/s**, which is that quarter exactly -- the measurement that says the
mechanism reaches the engine, waiting on a number. Carved, the table survives to 10 m and then shatters
*through the wood* -- not one piece is leg-sized. Glued, it loses legs at 2 m, a
fifth of the energy, and loses them **as legs**: at the joint, which is where it
already parted. A separate two-part probe (a slab on a post) holds to 4.5 m
carved and parts in two at 4.5 m glued.

**In a live room, too.** A product installed in the yard used to arrive as one
heap of cells with no labels on them, so every joint in it was solid wood. Its
cells now carry their component through the install, and its joints go into the
room's spec as an `interfaces` block, namespaced by the body root -- two tables
of the same design standing in one room are two objects, and a joint in one is
not a joint in the other.

A **template installed as it comes still declares no joints.** Its parts are
labelled, but nothing in a bare template says how it was put together, and
inventing that would be asserting a construction nobody chose. Joints arrive
once a design's own are (`workshop_construction.adopted`), which is what
building it part by part makes.

The hard part was not the install but **the chat's hands.** A room is written
back field by field after every edit (`room_world.export_spec`), and anything
that pass does not carry is silently gone; joints were not carried. Worse, the
engine refuses a scene whose declared joint names a part that is gone or crosses
no bond -- right where someone wrote that joint by hand, and fatal here: moving
or removing a jointed part would have been refused, and a room that had been
saved with one could have stopped opening at all. So a joint that no longer
stands is dropped where the world is rebuilt (`banjo_mcp._rebuild`), before the
engine sees it, and said with the rest of what an edit lost -- the same
discipline that already drops a bow's controls, a blade, a tool's point and a
motor when what they name goes.

Standing means the two parts still meet across a face
(`fracture_lab.standing_interfaces`). The engine's bonds reach further, as far
as its neighbour horizon -- across a diagonal, or a cell of air -- so this rule
deliberately keeps **less** than the engine would honour and can never leave
behind a joint the engine will refuse. It can drop one the engine would still
reach across, which is why an install refuses a joint whose parts do not meet
rather than quietly shipping one a later edit would lose.

**No room's digest moves.** A room's saved world is only reopened into a spec
with the same digest, and the digest is taken from the spec as the room holds
it, never from what the validator returns -- checked across both changes, and
now pinned (`room_store_tests`, `TheSpecAWorldIsSavedFrom`).

**What this does not reach.** The load survey (`surveyLoads`, which is what
warns that a shelf is overloaded) reads per-body material strengths and not
bonds, so a weak joint does not show up there. Precise-rigid bodies have no
bonds to weaken. Mixed materials are still refused upstream. And a product in
the world is still many bodies rather than one item, which is the next step.

## Not built, in the order it should be

1. **The product in the world as few bodies and real joints, handled as one
   item.** The contract's runtime bodies (the cart's three) as precise-rigid
   compounds, its bearings as native hinges, its breakable joints as native
   fixings rated by `engine_fixing`. It needs: the one guard that refuses every
   joint in a room with a precise body (`LiveWorld::requireLatticeRoom`, 13
   call sites; the joint functions themselves already find precise bodies);
   parts that are not axis-aligned boxes (`addCompound` already takes spheres,
   and `RotatedTranslatedShape` is in use for other things); part names and the
   design id kept on the body so it reopens in the Workshop; and the inventory
   taking a jointed product as one thing (`playground/inventory.py` refuses
   anything jointed today, and a precise body is not an inventory item at all).
   Done when a built cart placed in the yard rolls when pushed, is picked up
   and put in the bag as one thing, and the room runs at realtime.
2. **The engine checking what the bench checks.** Read a fixing's rotational
   impulse for a bending capacity; give a hinge a radial capacity. With
   glass/oak/iron tests, as `fixing_tests.cpp` has for tension and shear. Then
   the bench screen can be checked against the engine on the same product, which
   is the evidence that would let its uncertain band be narrowed.
3. **Coming apart in the world.** A fixed group is one compound today, so a
   joint inside it has no constraint to measure. Either keep breakable joints
   as fixings between bodies (more bodies, no new physics) or split a compound
   on the screen's answer; `CompiledRuntime::split` is the pattern (each piece
   inherits `v + w x r` and the same spin, conservation measured, new before
   old). The pieces are the sub-components, by name.
4. **Stage B for a thin precise part.** Refine the one struck part to a lattice
   when `admitRefracture`'s bound is passed. It needs a cell size per body.
5. **Into the Workshop and back.** Carry a world product in, open it as its
   parts, take it apart or reclaim its materials. It needs the material and
   energy ledger that installation still lacks.
6. **Melting.** No material has a melting point and no live body a phase. The
   enthalpy law exists apart from the live world. Softening by heat exists for
   three materials and already re-rates a fixing.
