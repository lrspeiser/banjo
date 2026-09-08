# One cell through the thickness is not a plate

Measured 2026-09-08 on `agent/integration`, in answer to: *"it just seems like
glass would not bend and stay bent."*

## The question

The lab's glass plate visibly bowed under a strike and sprang back. The
intuition was that glass does not do that. The intuition is right, and the
measurement says why.

## What was measured

A 250 x 200 x 10 mm glass plate on two ledges, struck at the centre by a 60 mm
iron ball at 0.5 m/s. Same strike four ways, changing only the cell size, so
the only variable is how many cells lie through the 10 mm thickness. Twenty
milliseconds of lattice phase in every case, `--backend parallel --precision
double`.

The yardstick is simply-supported beam theory under a central load, where the
surface strain at a mid-span deflection `d` is `e = 6 d t / L^2`.

| layers | cells | deflection | strain read | beam theory | under-read | rank-deficient nodes |
|---|---|---|---|---|---|---|
| 1 | 500 | 4.419 mm | 259 ustrain | 4242 ustrain | 16.4x | 500 of 1092 |
| 2 | 4,000 | 0.885 mm | 249 ustrain | 849 ustrain | 3.4x | 0 |
| 4 | 32,000 | 0.674 mm | 350 ustrain | 647 ustrain | 1.9x | 0 |

Glass fails at 1286 ustrain in this configuration, so at one layer the plate
deflects far enough to have broken four times over and reads a fifth of the
strain needed to break once.

## Why

Bending strain varies linearly through the thickness: tension on one face,
compression on the other, zero at the mid-plane. One layer of nodes sits on the
mid-plane and nowhere else. It therefore has

- no bending strain to feed the failure criterion, and
- no lever arm to resist with, which is the 4.42 mm rather than 0.67 mm.

The node-strain read is also rank-deficient at one layer: every one of the 500
nodes has a coplanar neighbourhood, so the rest-covariance has no third
eigenvalue and the strain is only defined in the plane. The plane-stress
projection added earlier keeps that honest -- it reports in-plane strain
correctly and reports nothing out of plane -- but there is no out-of-plane
strain to report in the first place.

## The residual factor of two, and a dead end

Four layers still reads 1.9x low. That is the nonlocal horizon: with a horizon
of two cells a surface node averages its strain over half the thickness, and
averaging a linear profile that changes sign halves the peak.

Shrinking the horizon to one cell does not fix it, it destroys the material.
At two layers, horizon 1:

| | bonds | rank-deficient | deflection | under-read | pieces |
|---|---|---|---|---|---|
| horizon 2 | 40,568 | 0 | 0.885 mm | 3.4x | 1 |
| horizon 1 | 9,820 | 1,366 | 8.147 mm | 761x | 407 |

A nearest-neighbour lattice has a quarter of the bonds, is rank-deficient
again, is nine times floppier, and shatters into 407 pieces under a strike that
leaves the horizon-2 plate whole. Horizon 2 stays.

## What it costs

This is the reason one layer was ever used. Same 20 ms of simulated time:

| layers | cells | bonds | lattice wall | x realtime |
|---|---|---|---|---|
| 1 | 500 | 2,777 | 0.92 s | 46x |
| 2 | 4,000 | 40,568 | 14.9 s | 743x |
| 4 | 32,000 | 417,180 | 385.4 s | 19,270x |

Eight times the cells per doubling, fifteen times the bonds, and the substep
halves with the cell size. Four layers is 420x the work of one.

## What was done about it

Nothing was made slower by default. The lab now states the cost of the choice
where the choice is made: the cell badge turns amber at one layer and the note
says the plate will flex about 6.6x too far and read bending strain about 16x
low, with the cell size that fixes it. `thickness_cells` is in the run summary,
so a saved run carries the caveat with it.

## What is still open

A one-layer plate could be given bending stiffness without more cells, by a
hinge term on collinear node triples -- the standard bending spring of shell and
cloth models. That would recover the stiffness at roughly the cost of the
existing bond solve rather than 420x it. It is an engine change, not a lab
setting, and it has not been built.

Every headline result so far -- the shatter patterns, the 500-cell plate at
0.99x realtime, the perforation speeds -- was measured on a one-layer plate.
Those are impact-dominated and dominated by tension near the strike rather than
by bending, so they are not invalidated by this. Anything that turns on how far
a plate bends before it breaks is.
