# Plate bending: matter one cell thick

**Status: built, tested and measured; switched OFF in the world.** The term is
in the engine and `banjo_plate_bending_tests` pins what it computes, but
`TileImpactScene` sets its thickness to zero, so no room runs it. This note is
why it exists, what it fixes, and the thing that is not settled — which is the
reason it is off.

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
whole of "it breaks at 3 m and 7 m but not at 10", and it is still true in the
world today, because this term is off.

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

## What it does, with it switched on

One blow, the same plate and ball, glass at 20 mm cells lying on the floor:

| dropped | bonds broken | pieces |
|---|---:|---:|
| 5 m | 67 | 1 |
| 6 m | 79 | 2 |
| 7 m | 89 | 3 |
| 8 m | 103 | 4 |
| 10 m | 124 | 5 |
| 12 m | 143 | 6 |

Strictly more damage and strictly more pieces for a harder blow — the thing the
term was written for. Matter two and three cells thick is bit for bit what it
was, its neighbourhoods spanning three directions and measuring their own
bending (`banjo_plate_bending_tests`). A plate under its own weight breaks
nothing, in glass, oak and iron, at 1, 2 and 3 cells thick.

## Why it is off

**A plate that is already breaking is not bending, and the fit cannot tell.**
The curvature is a second derivative of the displacement field, so it amplifies
whatever noise is in that field; a lattice in the middle of shattering moves
its nodes every way at once, and a quadratic put through that returns a large
curvature which is not bending. That curvature breaks more bonds, which makes
the next fit worse.

Measured on the fracture lab's own default scene — a 10 mm glass plate bridged
between two piers, struck at 6.26 m/s, **eight pieces** on the reference:

| | pieces |
|---|---|
| bending off | 8 |
| bending on | 138, with pieces of pieces five levels deep |

and the two live lanes, which must describe the same world to within a tenth of
a millimetre, stopped agreeing on what was even in it
(`tests/live_lanes_agree_tests.py`, which passes on `main` in 14 s and failed
here).

Four ways of separating bending from shattering were written and measured, and
none of them did it:

| guard | the lanes test | the plate on the floor, 3–12 m |
|---|---|---|
| none | fails | monotone |
| fit explains ≥ 50% of the out-of-plane motion | fails | monotone |
| fit explains ≥ 90% | passes | 1, 16, 1, 2, 3, 4, 4, 5, 4, 3 pieces |
| ≥ 90%, and only where no bond has gone | fails | 1, –, 1, –, 1, –, –, 3, –, 2 |

The two scenes sit in the same band, so no threshold separates them, and
choosing one to thread between two tests would be fitting the constant to the
tests rather than to the physics.

## What it would take

The instability is a feedback loop inside one lattice run: strain → failure →
a worse neighbourhood → more strain. Breaking it needs something this shape
does not have — a curvature that cannot feed on its own output. Two directions
worth measuring, neither tried here: holding the curvature at what it was when
the blow arrived rather than re-fitting it every substep (which needs it stored
per node, and raises the question of what "when the blow arrived" means for a
run that starts before contact); or giving the lattice real rotational degrees
of freedom, which is a shell element and a different engine.

## What it does not claim, even switched on

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
