# When to stop the fracture window

The lattice phase is the whole cost of this engine. The rigid phase after it
already runs 11-46x faster than realtime; the fracture window runs 41-649x
*slower*. So the only question that matters for the realtime gate is: when has
the window produced everything it is going to produce?

It had been stopping on the piece count going quiet. That was the wrong quantity.

## The piece count does not converge

Fragment count moves under every knob that should not change the answer:

| varied | one value | the other |
| --- | --- | --- |
| cell size | 90 pieces | 556 pieces |
| time step (implicit lane) | never converges | |
| sweep order | 768 bonds | 988 bonds |
| precision | 988 bonds | 1060 bonds |

A number that does not converge in cell size, time step, sweep order or precision
cannot be a stopping criterion, and cannot be used to falsify a speedup either.

## The removed energy does converge

Measured on a 250 x 200 x 20 mm glass plate against the same run taken to 1,058
wave transits (one transit across the plate is 47.2 us):

| transits | window | lattice wall | bonds | pieces | removed energy |
| --- | --- | --- | --- | --- | --- |
| 106 | 5 ms | 0.66 s | 1,466 | 59 | 2.484 J |
| 212 | 10 ms | 1.28 s | 1,841 | 84 | 2.498 J |
| 1,058 | 50 ms | 6.15 s | 2,086 | 95 | 2.504 J |

Energy is within 0.8% by 106 transits while the piece count is still 38% short.
Energy settles five to ten times earlier than the count, and it is the one
quantity every lane in this repository agrees on.

## The rule

`latticeExitReason` gained reason 4: after at least one failure and `min_steps`
in total, stop once the removed bond energy has grown by less than
`energy_flat_fraction` (default 0.001) of its running total for `energy_flat_steps`.
`--energy-flat-ms` sets the window; 0 disables it and the lane is what it was.

It never outranks the quiet rule, and it cannot fire on a scene that has broken
nothing — a plate that only bends is left entirely alone, bit for bit.

## Choosing the window

Too short and it stops inside a lull. On the panel's default scene:

| plate | window | energy kept | pieces | wall clock |
| --- | --- | --- | --- | --- |
| 250x200x10 | none | 100% | 51/51 | 1.23x realtime — over the gate |
| 250x200x10 | 2 ms | 82.40% | 14/51 | 0.28x |
| 250x200x10 | 3 ms | 99.76% | 33/51 | 0.48x |
| 250x200x20 | none | 100% | 77/77 | 1.95x realtime — over the gate |
| 250x200x20 | 2 ms | 98.27% | 62/77 | 0.56x |
| 250x200x20 | 3 ms | 99.98% | 75/77 | 0.94x |

2 ms is enough for the two-cell plate and not for the one-cell one, which is the
degenerate case in every other respect too (see one-cell-is-not-a-plate.md).
**3 ms clears 99.7% at both thicknesses and puts both inside the 1.1x gate,
which neither of them met before.** It is the default.

Pieces stay short of the full count on purpose: the ones still missing at 3 ms
are separations that release no measurable energy.

## The late burst is falling, not fracture

On a 400 x 200 x 20 mm plate at 18 m/s the rule appears to lose 4%, and the loss
does not shrink as the window grows from 1.5 to 3 ms. Walking the clock cap out
shows why — 96% of the energy is gone by 2 ms (26 transits), then **exactly zero
for the next 18 ms** while 88 more bonds separate at no measurable energy, and
then a second burst at 20-40 ms.

A 20 ms silence is 240 transits, some 400x longer than any acoustic timescale in
the plate. Taking the support away identifies it:

| layout | 2 ms | 50 ms | late burst |
| --- | --- | --- | --- |
| bridge, 60 mm ledges | 8.4700 J | 8.8763 J | +0.406 J (+4.58%) |
| bridge, 160 mm ledges | 9.3042 J | 9.8048 J | +0.501 J (+5.11%) |
| flat on the ground | 62.3990 J | 62.3997 J | +0.001 J (+0.00%) |

Remove the ability to fall and the burst vanishes. It is fragments landing, which
is the rigid phase's job, and secondary fracture on landing belongs to the
refracture lane. Keeping the lattice phase running 20 ms to catch a landing pays
lattice prices for rigid-body work.

## What it is worth

Across five fracturing scenes (150-400 mm plates, glass and oak, 6-18 m/s) the
lattice phase costs 7-16x less wall clock. On the panel's own default the whole
run went from 1.20x realtime (over the gate) to 0.471x, keeping 99.76% of the
energy, 416 bonds and 33 pieces, and coming to rest — as the panel reports itself.

## The other exit: scenes that were never going to break

Most scenes never fracture -- a ball rolling down a ramp, a stack standing there --
and they were paying the full no-failure window to establish it. Measured on a
four-object ski ramp of 9,056 cells:

| | wall clock | simulated | share of compute |
| --- | --- | --- | --- |
| lattice | 11.46 s | 20 ms | **91%** |
| rigid | 0.15 s | 4.000 s | 1% |

573x realtime, 91% of the run's compute for 0.5% of the watched time, and zero
bonds broken -- the worst-stressed bond never passed a tenth of its failure strain.

Exit reason 5 watches `L.damage`, which is already computed for the failure test
and is normalised by each bond's own six thresholds, so one number compares across
materials. It fires when nothing has broken, the worst bond is under
`calm_damage_margin` (0.5) of the way to failing, and it has not climbed for
`calm_steps`. `--calm-ms` sets the window; 0 disables it.

| calm_ms | lattice wall | whole run |
| --- | --- | --- |
| off | 11.47 s | 3.12x realtime -- over the gate |
| 0.5 | 0.49 s | 0.39x |
| **1.0** | **0.59 s** | **0.40x** |
| 2.0 | 1.21 s | 0.55x |
| 4.0 | 3.66 s | 1.18x -- over again |

1 ms is the default: about two and a half wave transits of the largest body there,
so "flat" means something. The safety is the margin rather than the window --
anything actually being loaded keeps `last_damage_gain_step` advancing and the run
continues. Checked against the plate-and-ball scenes that do break, at both
thicknesses: same bonds, same pieces, same energy to four decimals.

## What this exposed, and did not cause

With the rule off, those scenes break nothing either. A many-object scene can only
fracture during the lattice window, which runs at t = 0; a ball that has to travel
arrives during the rigid phase, and Jolt does not fracture. The lane that would
re-enter the lattice on a rigid contact -- refracture -- is built for the
single-tile scene: `piece_reach_m` is `0.5 * length(tile_dimensions_m)`, which is
zero when there is no tile, and a contact between two lattice pieces is explicitly
`refused_unsupported`. In a many-object scene every contact is piece-versus-piece.

So the bowling ball has never broken the pins, and the ski ramp reports 0 bonds
broken, for a reason that has nothing to do with the geometry or the request:
**the engine cannot yet fracture anything that is not already in contact at t = 0
in a multi-object scene.** That is the next thing to build.
