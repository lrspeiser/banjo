# Consequences: what breaks, what gives, what is carried, and the person in the water

Branch `agent/world-consequences`, from `main` (`9c6e791`). Six things a person
testing the room and the Workshop reported as missing (2026-09-18): nothing ever
breaks; every product is one fused body; carried ground weighs nothing; water
is scenery; nothing fails under a load; heat does not change mechanics. What was
found under each, what changed, what was measured, and what is still not done.

Two of the six were wrong as reported, and are corrected here rather than built:

- "Only 7,648 of 19,500 water columns are computed, so 61% of the water is not
  solved." Only wet tiles and a one-tile ring are computed, on purpose
  ([terrain-and-water.md](terrain-and-water.md)): a dry column has no water in
  it. Nothing is unsolved.
- "Water is no force." On every BODY it already is: the engine presses on each
  body's own surface, oak floats with 70% of itself under and a log goes
  downstream at 0.76 m/s. It was no force on the PERSON, who is a point of view
  and not a body. That is what changed (section 4).

## 1. Nothing ever broke

**The ceiling.** The Workshop's drop topped out at 2 m, which lands at 6.3 m/s.
The engine says its glass table can first break at 8.70 m/s and its oak one at
13.75. Every run reported `fracture_events: 0` whatever was chosen, because no
control could reach the failure model that was already wired in
(`workshop_motion.run` has always answered `breakable` with `fracture`).

**And under the ceiling, an engine defect** that would have hidden most breaks
once it was raised. `LiveWorld::prepared` starts a fracture run from a lift clear
of the floor and refused outright when that lift was more than half a cell --
the guard against matter that is BURIED. A body landing fast is not buried: the
step taken back is the one in which the contact was reported, and at the room's
1/120 s a table at 10.8 m/s has moved 90 mm by then. Measured on the Workshop's
glass table, 40 mm cells:

| dropped | lands at | caught | before | now |
|---|---|---|---|---|
| 4 m | 8.8 m/s | 14 mm short of the floor | 40 pieces | 65 pieces |
| 6 m | 10.8 m/s | 25 mm inside it | `would_break`, "held", no run made | 161 pieces |
| 10 m | 14.0 m/s | deeper | "held" | 213 pieces |
| 16 m | 17.7 m/s | deeper | "held" | 226 pieces |

A harder landing held where a softer one broke. The depth the deepest cell can
owe to its own body's way in -- what that cell moves into the plane in one step
-- is no longer counted as burial. `banjo_live_world_tests`
`aHardLandingBreaksItWhateverThePhaseOfTheStep` drops a joined glass table at
12 m/s from six clearances a cell apart (caught 0 to 79 mm inside the floor);
four of the six were refused before, all six break now, and it fails on the old
engine at the first clearance.

**What the Workshop now offers** (`playground/workshop_motion.py`, `workshop.js`):

- The drop goes to 20 m. The declared time is still the time simulated (a short
  run is how free fall is checked in mid-air, and a test pins it), so a run that
  ended in the air says so and says how long would see it land; raising the drop
  in the page raises the time beside it, in plain sight.
- **Strike it with a weight**: an iron block of whole cells thrown at the thing
  where it stands, 0.5 to 200 kg at 0.5 to 30 m/s, at a height from its feet to
  its top. It is aimed at matter -- a table's middle is the air between its legs.
- What happened is said from the engine's own reading of the blow to the thing
  as designed: *Broke into 65 pieces at 0.90 s. Met the ground at 8.83 m/s.
  Against that, this can first break at 8.70 m/s and has no bending range.*
- Every piece is drawn as the cells the engine left it (a snapshot follows each
  step in which something was asked about), and the cells drawn at the end are
  counted against the cells compiled.
- The view goes with the matter, every body weighed by its cells: framing the
  whole journey made a table dropped 4 m a speck.

Measured through the page's own path, default table:

| | glass | oak | iron |
|---|---|---|---|
| drop 1 m | holds | holds | holds |
| drop 4 m | 65 pieces | holds | holds |
| drop 10 m | 213 pieces | 29 pieces (dents at 6 m) | holds |
| 4 kg at 8 m/s, 129 J | 6 pieces | shoved, whole | whole |
| 18 kg at 15 m/s, 2.0 kJ | 24 pieces | top sheared off all four legs | 10 pieces |

## 2. "Every product is one fused body"

It is, and it is the product contract's decision (`runtime_bodies: 1`), not
changed here. What it was taken to rule out is not ruled out: **a broken table
comes apart at its joints into its own parts.** By blow or by landing, in oak or
in glass, each 18-cell leg comes away as one 17-cell piece, parting one cell
below the top, and the cells at the end are the cells compiled
(`test_a_broken_table_comes_apart_at_its_joints_into_its_own_parts`).

**Not done, and proposed rather than built:** a joint is as strong as the wood
it joins. A glued or dowelled joint is perhaps a third to two thirds of it, a
weld nearly all. The mechanism exists -- `weakenBond` scales a bond's damage
thresholds and is how heat already weakens a section -- and the bonds to scale
are those whose two cells belong to different components. What is missing is
which component a cell came from surviving the scene's `join`, and what each
mating method's efficiency is. Both are ProductGraph and mating decisions, so
this is an issue to decide and not a second implementation.

## 3. Carried ground weighed nothing

Six presses of Dig here put 435 kg of sand and soil on the person, who crossed
the room at a run. The account of what is carried is the engine's, so the limit
is too:

- `TerrainField::dig` takes a budget: the same trench, every column to the one
  depth, as deep as takes out exactly what may come out and no deeper. The depth
  is found by halving over arithmetic identical to the report's, so what is
  found to fit is, to the last bit, what is said to have come out. It reports
  the depth it went; **made again at that depth the dig takes out the same**,
  which is what a room keeps (`server.remember_ground` now keeps it; kept as
  asked, the room opened again dug the whole pit and carried the lot).
- `Environment` holds the limit (infinite unless a host says: every world as it
  was, and a scene's own edits are never limited). A spade's dig and a pick's
  both go through `Environment::dig`, so both keep to it.
- The playground says 80 kg: what the person's 800 N hand holds against gravity
  (81.5 kg). Full, a dig is refused in words before the ground is touched --
  *You are carrying 80.0 kg of sand and soil, and 80.0 kg is all you can carry:
  heap some of it first* -- as a refusal, not a page error.
- It is in their legs: pace falls to two fifths at a full load (what is dug plus
  what is in the hand), and from half a load they cannot run. The bag says so.

Measured in headless Chrome (`WhatIsDugIsCarriedAndWeighs`): one press of Dig
here, which lifts about 100 kg, takes 80.0; carrying it, 0.96 m/s walking and
0.96 "running" against 2.40 and 5.59 with empty hands; a reload carries the
same to 1e-6 kg; heaped back, the legs are free.

## 4. The person in the water

The body is taken to hang 1.6 m below the eye, never below the ground. To the
knees they wade at four fifths of their pace; by 1.2 m they are swimming at
three tenths. Water deeper than their thighs takes them with it -- none of its
speed at 0.5 m, all of it by 1.2 m. A head under the surface looks it (the view
dims and goes blue) and the bag says *wading*, *swimming* or *under water*, how
much of them is under, and how fast the water carries them. Five metres over a
river is over it, not in it.

**Not done:** breath. There is no health in the room for running out of it to
cost, and inventing one is a game-design decision, not a physics one.

## 5. Nothing failed under a load

The engine has had sustained-load failure since the beam work: a survey asks,
from statics, what rests on a body, how far apart its supports are and what
bending that puts in it, and statics on the body's own lattice answers. It
looked for a beam held up by OTHER bodies. **A table is one body with nothing
under it but the ground**, so it was "falling, not carrying": through the
Workshop's load test, five tonnes of iron on a glass table was never asked
about. Had it been, its section would have been the whole body's box, legs and
all.

Both are now read from the body's own cells (`LiveWorld::surveyLoads`):

- Where it is: a box about the centre of mass is where a BOX is. A table's weight
  is nearly all in its top, so that box stood 0.3 m proud of it and nothing put
  on the table was found resting on it.
- What it is as a beam: its feet are the cells whose underside is on the ground
  beneath them; along each of its two level axes, in its own frame, the widest
  gap between two runs of feet is the clear span; the section is each column's
  run of cells down from the top in the middle of that gap, and its modulus is
  summed over those cells (b d^2 / 6 exactly, for a rectangle). Statics holds it
  up by those feet.

Pinned on the beam suite's own shelf made as one stone table: 5.74 MPa against
concrete's 3 over the 1 m between its feet, where the shelf on loose piers reads
5.46 (the difference is the weight of its own two ends); loaded further, statics
breaks it on 48 cells of its own feet; on a plinth as long as itself, nothing.

The Workshop's "Load the product" now says what became of it: *Held 400.1 kg, at
59% of what breaks it*, or *Gave way under 300.2 kg: in 3 pieces*, with the
bending, the span between its feet and what the material can take. Measured at
20 mm cells: a 2.0 x 0.5 m concrete table under 300 kg reads 11.9 MPa against
3.0 over 1.84 m, statics breaks it at 103% of the criterion, in 13 s; the default
concrete table holds 600 kg at 77%; oak is never asked about, which beam theory
agrees with (14 MPa against 52).

Two things it needed. Once a table has given, the question is answered: the old
loop answered every break the wreck then offered, each a lattice run over the
load's thousands of cells, with no budget, and one run was stopped at 37 minutes
of processor time. What is offered after the break is declined (the runner's new
`decline` op; `LiveWorld::declineBreak` was there and no host could reach it),
the wreck falls for 0.6 s as the pieces the break left, and a wall-clock budget
backs both. And every ceramic product was refused before it ran -- the catalogue
says "alumina ceramic" and a scene says "ceramic"
(`engine_materials.scene_name`).

**Honest limits.** A top one cell thick has no depth to bend through, and statics
says such a top holds far more than beam theory does; the page says to put two
cells through the part that carries the load. Creep and fatigue are not
modelled: a load is held or it is not, now.

## 6. Heat and mechanics

Not changed. What exists on `main` is more than was reported: heat, composition
and burning change what a body can carry by a declared law per material
(`thermo/ThermalMechanics.hpp`, oak EN 1995-1-2, iron EN 1993-1-2); a heated
section is offered as overloaded when the bending in it passes what is left; and
a fracture run weakens each bond by what heat has done to the cells at its ends
(`heatIsland`). **Melting, forging and phase change are not in the live world**
-- the status endpoint's own words: J2 plasticity, compact state and bounded
property variation are reference modules, not live-world capabilities. That is
a lane of its own, not an increment here.

## Verification

C++ (Release, this branch's own build): live_world 35, beam 10,
thermal_mechanics 11, thermal_geometry 6, blade 10, terrain 9, valley_live 10,
water 19, ground_work all checks.

Python: the fast Workshop lane; `workshop_bench_tests` 30;
`workshop_bench_engine_tests` 19 with `BANJO_LIVE_ENGINE` set and none skipped;
`workshop_browser_tests` 25 and the world journeys in headless Chrome.
