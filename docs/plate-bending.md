# Plate bending: matter one cell thick

**Status: built, measured, and OFF — on the realtime rule.** It was on for one
commit (4c193d5, 28 September) and is off again in the one after. It fixes the
reported fault from 6 m up and does not fix it below that. What stopped it is not
the physics but the bill: a one-cell glass tabletop comes apart into ~185 pieces,
and the Workshop's own drop test for a glass table then takes **15.0 s of wall
clock for 1.7 s of world time — 8.8× realtime**, where the same test is 0.08 s
with the term off. Design rule 2 is 1.1×, and the bench's own 30 s guard refuses
the run outright on CI's slower hardware: three tests in
`tests/workshop_bench_engine_tests.py` failed on main at 4c193d5 with
"The simulation exceeded its work budget". **The cost is not the curvature fit —
it is simulating the pieces** — so it cannot be optimised away at the fit. This
note is the measurement both ways, so the decision can be made on numbers: it
needs either a cheaper way to carry a shattered sheet, or a decision that a
product test may cost that much.

The other half of this work, the world repeating itself, is ON and unaffected —
it has no cost and it is what made the published ladders reproducible.

## What a plane can measure

The failure criterion is nonlocal: the strain at a node is fitted from how its
neighbours have moved, not from one bond's stretch. The fit needs the
neighbours to span three directions, and it says so —
`symmetricPseudoInverse3` reports the rank of the rest covariance, and
`nodeStrain` projects the strain into the plane when that rank is 2.

For a sheet one cell thick every node's neighbourhood is coplanar, so the rank
is 2 at every one of them. The engine already knew and already said so in the
source:

> a sheet one cell thick has every node at rank 2, and reporting zero here used
> to be the only sign that the nonlocal criterion had quietly become a local
> stretch test

Truncating the direction through the sheet is the right thing to do with the
data: `F d = d` along it is the plane-stress statement, and a single layer of
nodes supports no other claim. The projection is not optional either — leaving
the out-of-plane cross terms in is not rotation invariant, and a sheet that
merely flexed read as shear, at 436 bonds broken under gravity alone.

But **hitting a plate loads it in bending**, and membrane strain is blind to
bending. So the criterion saw almost nothing.

Measured, a 300 × 300 mm plate at 20 mm cells struck by a 100 mm iron ball
dropped on it where it lay on the floor:

| plate | 3 m | 5 m | 7 m | 10 m |
|---|---|---|---|---|
| 20 mm, one cell thick | 40 bonds | 68 | 82 | 115 |
| 40 mm, two cells thick | 902 bonds | 988 | 1,053 | 1,569 |

Ten to twenty times less damage for the same blow, and none of it ever
separated the plate. What the piece count actually reported was whether one
20 mm cell had happened to lose its last bond: a 0.02 kg chip off 4.5 kg at
3 m and at 7 m, five cells at 12 m, and nothing at 4, 5, 8 or 10. That is the
whole of "it breaks at 3 m and 7 m but not at 10".

## The curvature is in the same data

A plate's bending is not lost — it is in how far each neighbour has moved *out*
of the plane, which is exactly what the truncation throws away. Recovering it
takes two weighted fits over the same neighbours the strain is built from
(`plateBendingStrain`, `src/fastlattice/LatticePhysics.hpp`):

1. **The tilt.** The best linear fit of the out-of-plane displacement against
   the rest offset, `a = R⁺ Σ w (d·n) r`, using the live pseudo-inverse the
   strain itself uses. A rigid rotation moves every neighbour out of the plane
   by an amount *exactly* linear in its offset, so this stage absorbs all of it
   and leaves nothing behind. That is what makes the curvature invariant under
   rigid motion — the property the in-plane projection exists to protect.
2. **The curvature.** What the tilt does not explain, fitted as
   `w = ½ rᵀ K r` over the three independent components of `K`. The normal
   matrix is symmetric 3 × 3, so the same eigen-decomposition serves, with a
   floor of a thousandth of its largest eigenvalue rather than the billionth
   the rest covariance uses: this matrix's entries go as the *fourth* power of
   an offset, and the shared floor will invert a direction the neighbours have
   barely sampled.

A plate of thickness `h` strains its outermost fibre by `(h/2) K`, and `h` here
is the cell size. The fibre taken is the one in **tension**, `|K|` rather than
`K`: which face the stored normal points out of is arbitrary, and a signed term
would make the answer depend on it.

**And a material that yields stops at its yield.** This term feeds the failure
criterion; it does not feed the bonds' own plastic return, which is axial. Past
first yield a real section does not go on straining its surface elastically —
it yields there, and the extra curvature becomes permanent rotation, which is a
dent and not a crack. So the fibre strain is capped at the material's yield
stretch, which is zero for every material that declares no yield strength.
Measured on a curvature far past yield: 0.0012 of strain where the uncapped
term wanted 0.04, while a bow under the yield is reported whole.

Whether a node is in a sheet at all is asked of the **rest** neighbourhood —
every bond it was built with, alive or not. The live set cannot tell a sheet
from a solid node that fracture has stripped down to a plane, and they are not
the same thing: judging by the live set alone moved the 40 mm plate from 13
pieces to 26, because nodes that had lost bonds began to be read as sheets
halfway through the cascade.

## What it does

The bug, reproduced: a 300 x 300 mm glass plate one cell thick at 20 mm cells,
lying on the ground with nothing under it but the ground, and a 100 mm iron ball
(4.5 kg) dropped on it. `scripts/plate-ladder.py` is this table, so anyone can
run it; the left column is the same script against a build with the term off.

| dropped | bending off | bending on |
|---|---|---|
| 3 m | 2 pieces | whole |
| 4 m | whole | 16 pieces |
| 5 m | whole | whole |
| 6 m | whole | 2 pieces |
| 7 m | 2 pieces | 3 pieces |
| 8 m | whole | 4 pieces |
| 9 m | whole | 4 pieces |
| 10 m | whole | 5 pieces |
| 11 m | whole | 4 pieces |
| 12 m | 2 pieces | 3 pieces |

The left column IS the reported fault, exactly: it breaks at 3 m and at 7 m and
not at 10 m, and "breaks" means a 0.02 kg chip off 4.5 kg — the biggest piece
is 4.48 kg every time. Nothing about it is a threshold; the plate never comes
apart at any height, and which heights chip is which heights happened to take
one cell's last bond.

**From 6 m up the right column is what the term was written for:** the plate
comes apart at every height, and 6 -> 10 m gives 2, 3, 4, 4, 5 pieces, more for
a harder blow. **Below 6 m it is still not right,** and that is worth saying
plainly rather than averaging away:

- **3 m and 5 m leave the plate whole.** The blow is under the bar and nothing
  breaks, which is a defensible answer — but 4 m between them is not whole, so
  the sequence is not ordered by the blow.
- **4 m gives 16 pieces,** the most of any height. It is not one blow: watched
  against the clock, the ball first turns round at t = 0.892 s with the plate
  still in one piece, and the plate comes apart at t = 1.700 s as the ball falls
  back onto it. From 5 m up the ball goes through or rebounds clear instead. So
  a drop height is not a dose, and a piece count from a bouncing ball is a count
  for the whole aftermath.
- **11 m and 12 m give 4 and 3** where 10 m gives 5. Measured, repeated, and not
  explained — see below.

Two controls, the same script — `--thickness-cells 2` and `--spanned`:

| dropped | 3 m | 4 m | 5 m | 6 m | 7 m | 8 m | 9 m | 10 m | 11 m | 12 m |
|---|---|---|---|---|---|---|---|---|---|---|
| two cells thick, off | 13 | 142 | 47 | 24 | 35 | 47 | 30 | 48 | 64 | 58 |
| two cells thick, on | 13 | 142 | **53** | 24 | 35 | 47 | 30 | 48 | 64 | 58 |
| one cell, spanned, off | 44 | 83 | 31 | 62 | 25 | 82 | 24 | 96 | 31 | 209 |
| one cell, spanned, on | 33 | 166 | 34 | 194 | 173 | 175 | 195 | 196 | 184 | 142 |

**Two cells thick is untouched, with one cell of the ladder moved** — 5 m, 47
to 53 pieces. That is not the term reading a solid body: it is that a cascade
makes pieces, a piece of a two-cell plate can be one cell thick, and a piece one
cell thick is exactly what this is for. The body as built never reads bending at
any node, which is what `banjo_plate_bending_tests` checks directly; what
changes is what its fragments can do. The same explains the one material that
moved on the README's ladder: ice, which comes apart into dozens, at 5 m/s
(30 -> 41 pieces) and 40 m/s (12 -> 32). Nothing else in those forty cases
moved.

**A plate bridged on piers is where this costs the most.** Its span was never
blind — in-plane tension across it is something a coplanar neighbourhood can
always see, which is why the off column already breaks it into tens of pieces --
and with bending on it goes to near-total disintegration: 194 of the plate's 225
cells at 6 m, 196 at 10 m. That is not obviously wrong for 4.5 kg of iron at
11 m/s onto a 20 mm sheet of glass bridging 260 mm, and both columns are equally
unordered in the blow, so neither is carrying information above about 6 m. It is
a real change in what the world does, and anyone quoting a spanned piece count
from before 27 September should re-measure it.

**A glass table's top now shatters when the table is dropped, and that was a
decision.** The Workshop's table is a 540-cell top on four 18-cell legs, and the
top is one cell thick — so this term applies to it. The product guarantee is that
a break parts the JOINTS and each leg comes away whole, and that still holds:
four whole legs, every cell accounted for. What no longer holds is the top coming
away as one piece. Measured with the term on, dropped: 0.5 m breaks nothing at
all, and 1, 1.5 and 2 m leave a biggest piece of 88, 43 and 329 cells of 540. So
there is no height that gives the old answer — the case could not be re-tuned,
only re-decided. Oak is untouched (516 of 540 after 10 m, and a 20 kg striker at
15 m/s parts the joints without taking the top). The owner's call was that 20 mm
annealed glass does shatter and the test should say so, so
`test_a_broken_table_comes_apart_at_its_joints_into_its_own_parts` now asserts
the joints guarantee for every material and the shattered top for glass — which
makes it the thing that would catch this term being switched off again: with it
off, that top survives with 496 of 540 cells.

**It costs about twice the time in a fracture run, and that is not free here.**
The engine's own deadline check (`banjo_live_world_tests --deadline`) times the
run a foreseen fracture starts on the way down and compares it with the warning
it had. Measured on this machine, 24 hardware threads, the lattice on 16:

| case | warning | run, term off | run, term on |
|---|---|---|---|
| 1.5 m, cold | 485 ms | 354 ms (margin +131) | — |
| 6.0 m | 939 ms | 355 ms (margin +584) | 782 ms (margin +156) |
| 1.5 m, warm | 485 ms | 360 ms (margin +125) | 878 ms (**margin −393**) |

So a run takes 2.2 to 2.4 times as long, and in the 1.5 m case it no longer
finishes inside its window: foresight misses. That is a second weighted fit and
an eigen-decomposition per node per substep, plus the extra work of actually
breaking more. Rule 2 of the design rules is "real time, or refused", and this
does not change what the gate refuses — the gate prices a job before it starts —
but it moves every fracture closer to it, and a scene that used to fit may now
be refused. Worth knowing before blaming that on something else.

(That deadline test fails either way, on a different and older complaint —
"something still blocked at the moment of contact" — which is not this term:
with it off, all three margins are positive and the test still fails.)

A plate under its own weight still breaks nothing, in glass, oak and iron, at 1,
2 and 3 cells thick.

**Every number here repeats.** Each ladder was run at least twice and gave the
same answer to the piece, and the forty-case materials ladder was run five times
identically, which it did NOT do before the contact order went in (the next
section). Numbers published before 27 September were taken without it and will
not all match.

## The thing that nearly sank it, which was a different bug

Turned on, this term first made the fracture lab's own default scene — a 10 mm
glass plate on piers at 6.26 m/s, eight pieces on the reference — come apart
into 138, with pieces of pieces five levels deep, and the live world's two
lanes stopped agreeing on what was even in the room about a third of the time
(`tests/live_lanes_agree_tests.py`).

That was **not** this term. It was that the world could not repeat itself.
Jolt's contact collector is filled from its worker threads under a mutex, so
contacts arrived in thread-completion order, and `judgeStep` keeps the hardest
contact on a struck body as the partner for the island a fracture would build —
so when two contacts were equally hard, whichever thread finished last decided
the break. Measured: the same held ball let go from 1.4 m came to rest as 376
bodies, then 380, then 376 again, one process, one binary, one input.

Plate bending did not cause that; it revealed it, by moving that scene close
enough to a threshold that a different partner meant a different answer. With
the contacts in a total order of their own (`ImpactEvent.hpp`
`hardestContactFirst`, and `banjo_live_determinism_tests` to keep it), the lab
scene is 352 bodies four runs running, both lanes agree, and the lanes suite is
green eight times out of eight.

Four guards were written while that was being chased, on the theory that the
fit had to be stopped from reading a shattering neighbourhood as a bend. One of
them is still in the code — a curvature is read only where the quadratic
explains nine tenths of the out-of-plane motion — and it is worth being exact
about its status: **with the contact order fixed, taking it out changes nothing
that has been measured.** The height curve is identical, the lab scene is 352
either way, the lanes pass either way. It stays as a bound on what the fit may
claim, not because it is carrying anything.

## Still unexplained

Above 10 m the piece count falls — 5 at 10 m, 4 at 11, 3 at 12 — and it
repeats, so it is not noise. The guard is not the reason either: removing it
does not move those numbers. A blow that violent is doing something else to the
plate and it has not been run down. Two directions worth measuring if it
matters, neither tried here: holding the curvature at what it was when the blow
arrived rather than re-fitting it every substep (which needs it stored per node,
and raises the question of what "when the blow arrived" means for a run that
starts before contact); or giving the lattice real rotational degrees of
freedom, which is a shell element and a different engine.

## What it does not claim

- **The bond is at the mid-plane and the strain is the surface's.** A plate
  cracks from its outermost fibre and the crack runs through, so failing the
  mid-plane bond when the surface fibre fails is the right proxy for a brittle
  material. For a ductile one the yield cap stops it there, which is the
  first-order elastic–plastic picture and not the whole of one: the plastic
  hinge and the reserve between yield and rupture are not modelled.
- **Tension, not compression.** Oak, aluminium and rubber are weaker in
  compression than in tension, so for those three this reports the stronger
  face.
- **A cell is still the thinnest thing there is.** This makes a one-cell sheet
  answer a blow; it does not make the sheet thinner.
- **Nothing here is calibrated** against laboratory plate-impact data, as
  nothing else in the fracture model is.

## A hole it turned up, which IS fixed

A run in which **nobody** was admitted to break left every body in its island
holding the cells the run had left them with. The `!may_break.empty()` guard
had already been taken off the bond put-back for exactly this reason; it was
still on the cell put-back, and an empty set is the one case it has to cover —
it is the only way the set ends up empty.

Measured on a 20 mm iron plate on piers, struck well under iron's bar: its
cells came back where a run had left them, and it entered the next run holding
12 MJ of stretch, then 890 GJ, at a bond stretch of 2,144 — and came apart into
every one of its 225 cells. With the guard gone it holds, three runs alike. The
put-back now covers every body whose bonds were put back, and skips one that
took a permanent set, because a dent is the answer and laying its cells back
out would throw the shape away.

That fix is independent of plate bending and is on in the world.
