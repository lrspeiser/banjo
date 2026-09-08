# Why the glass plate does not shatter, measured

Recorded 2026-09-08 on `agent/integration`. Windows 11, MSVC 19.44, x64 Release,
Jolt v5.6.0. All runs: `banjo_fast_lattice_run`, CPU backend, glass tile on two
ledges struck by an iron ball, unless stated.

The question: the Fracture lab's default scene -- a 250 x 200 x 10 mm glass
plate, 500 cells, struck by a 60 mm iron ball dropped 2 m -- reports 73 broken
bonds and **one piece**. Real 10 mm glass hit with 17 J cracks right through
(the hand calculation puts the bending stress near 130 MPa against a 45 MPa
strength). Why does the engine keep it whole?

## 1. It is not an energy shortage

The ball carries 17.4 J. Cutting the plate clean across -- 0.20 x 0.010 m of new
surface at Gc ~ 8 J/m^2 -- costs **0.016 J**, one tenth of one percent of it.
Energy is never the constraint in any of the runs below.

## 2. At one cell through the thickness, cracks initiate and arrest

Default plate, 10 mm cells (25 x 20 x **1**), speed swept:

| impact | bonds broken | share | pieces | peak tensile stretch |
|---|---:|---:|---:|---:|
| 6.26 m/s (17 J) | 73 | 2.6% | 1 | 0.00137 |
| 12 m/s (64 J) | 400 | 14.4% | 1 | 0.00145 |
| 20 m/s (178 J) | 544 | 19.6% | 1 | 0.00148 |
| 40 m/s (712 J) | 678 | 24.4% | 9 (largest 488 of 500 cells) | 0.00210 |

Forty times the energy breaks nine times the bonds and still leaves 488 of 500
cells joined. The peak stretch barely moves: the lattice **diffuses damage**
around the impact instead of **propagating a crack**. Two causes, both
structural:

- **A single layer cannot bend.** There is no through-thickness gradient, so the
  tension on the underside -- the mechanism by which a struck pane actually
  breaks -- does not exist in the model. Only contact crushing is left. Note
  that "500 components" on a 250 x 200 x 10 mm plate *forces* 10 mm cells and
  therefore exactly this case.
- **No crack-tip concentration.** A tip's stress singularity cannot be resolved
  at 10 mm cells; the tip stress is averaged over one cell, so when a bond
  breaks the local strain relaxes and its neighbour sees no amplification. Real
  glass runs a crack at ~1,500 m/s because tip amplification grows with crack
  length. Here it does not exist. This is the missing length scale in the
  failure criterion (`docs/engine-options-analysis-2026-09-07.md`, Wall 2),
  seen from the propagation side.

Halving the thickness does not change the verdict, so this is not a strength
question. 250 x 200 x **5** mm at 5 mm cells (still one layer, 2,000 cells):
6.26 m/s breaks 799 bonds (6.9%) into **1 piece**; 12 m/s breaks 1,519 (13.1%)
into **2 pieces**, the second being a single cell. Real 5 mm glass hit with
64 J is destroyed.

Connectivity makes the arithmetic explicit: at horizon 2 a cell bonds to 12
in-plane neighbours, so about 5 bonds cross every cell-length of a cut and a cut
across the 20-cell width needs ~100 *contiguous* failures forming a closed
curve. Hundreds of scattered failures around the impact never close one.

## 3. Resolve the thickness and it does fail -- and over-fragments

Same 250 x 200 x 10 mm plate at 5 mm cells (50 x 40 x **2**, 4,000 cells),
6.26 m/s: **20,079 of 40,568 bonds broken (49.5%), 501 pieces**. On the small
60 x 50 x 10 mm tile the contrast is clean, same tile, same strike:

| cells through thickness | cells | bonds broken | pieces |
|---:|---:|---:|---:|
| 1 | 30 | 1 (0.8%) | 1 |
| 2 | 240 | 1,735 (79.7%) | 56 |
| 4 | 1,920 | 6,823 (28.7%) | 209 |

So the plate breaks as soon as it can bend, and then breaks far too much: 501
pieces from a 17 J strike on a 10 mm pane is pulverisation, not fracture. That
is the same missing length scale as in section 2, from the energy side: at half
the cell size a crack costs half the energy, so a finer lattice fragments more.
It is the defect the energy-scaled criterion work exists to fix.

The lattice is **stable at rest** at both resolutions -- the same 4,000-cell
two-layer plate, held on its ledges under gravity for 40 ms with the ball parked
1 m away, breaks **0 bonds** at a peak stretch of 0.0000; the one-layer control
breaks 0 at 0.00008, which is its own sag. The breakage above is caused by the
impact, not by an at-rest instability.

## 4. A separate defect: double precision fabricates strain at degenerate nodes

Discovered while measuring the above. The nonlocal node strain needs the inverse
of the node's rest covariance over its live neighbours. `inverseEpsilon`
(`src/fastlattice/LatticePhysics.hpp`) picks the degeneracy threshold:

- **double**: absolute, `|det| > 1e-16`, inherited from the shared criterion
  (`src/fracture/BondFailure.cpp:128`, `rest_covariance.inverse(1.0e-16)`).
- **float**: relative, `|det| > 1e-5 * (trace/3)^3`.

For a nearly coplanar neighbourhood -- a thin plate, or **any node that has lost
most of its neighbours to fracture** -- the determinant is tiny but larger than
1e-16, so the double path accepts the matrix and its inverse amplifies noise.
The code computes both rules, counts the disagreements in
`degenerate_disagreements`, and then ignores them.

Measured, same tile and strike, precision the only difference:

| run | peak tensile stretch | peak compressive strain | degenerate disagreements |
|---|---:|---:|---:|
| 1 layer, double | 0.0015 | 0.0010 | 0 |
| 2 layers, **double** | **2.2630** | **0.5000** | 9 |
| 2 layers, float | 0.0029 | 0.0132 | 10 |
| 4 layers, **double** | **127.5000** | **0.5000** | 26 |

A compressive strain of exactly 0.5000 is the Green-Lagrange value for a
deformation gradient collapsed to zero: `E = (F^T F - I)/2 = -I/2`. A tensile
stretch of 127 is 12,750% strain in glass. These are fabricated numbers, not
physics.

The same signature is already in the GPU lane's committed evidence and was not
noticed: `docs/evidence/fast-gpu/bridge-192-cpu-double.json` and
`bridge-192-gpu-double.json` both report stretch **4.0000**, compressive
**0.5000**, 8 disagreements, while the float runs of the same scene report
0.0046 / 0.0040 / 1. The checkpoint attributed the double/float difference to
speed alone.

**What this does and does not change.** On the tile above it did not drive the
outcome -- double broke 1,735 bonds into 56 pieces, float 1,789 into 42 -- so
the fragmentation in section 3 is not an artefact of it. But every
double-precision fracture result in this engine carries fabricated strain at
some nodes, the reported peak strains are meaningless wherever
`degenerate_disagreements > 0`, and the number of such nodes grows with damage,
which is exactly where the criterion is being read. Any convergence study run in
double is measuring this as well as the physics.

**The fix** is to use the relative rule in both precisions (or reject the node
when the two disagree) in `inverseEpsilon` and in `BondFailure.cpp`, and to fail
loudly rather than count silently. That is a criterion-level change and belongs
with the energy-scaled criterion work, before any convergence ladder is trusted.

## 5. What has to be true before a pane shatters correctly

1. A failure criterion with a length scale, so a crack costs the same energy at
   every resolution and can propagate rather than diffuse. In flight.
2. The node-validity rule fixed, so strains read near a crack are real. Section 4.
3. At least 3-4 cells through the thickness, so bending exists -- which for a
   10 mm pane means ~2.5 mm cells and ~32,000 cells, not 500. The "500
   components" figure and "shatters like glass" are in direct tension, and the
   resolution of that tension is the speed work, not a coarser model.

## Reproduce

```
build/integration/Release/banjo_fast_lattice_run.exe --material glass --ball-material iron \
  --tile 0.25 0.01 0.2 --cell 0.01 --ball-radius 0.03 --speed 6.26 --offset 0 0 \
  --layout bridge --settle-s 1 --backend cpu --precision double --record out.json
# speed sweep: --speed 6.26 | 12 | 20 | 40
# thickness ladder (small tile): --tile 0.06 0.01 0.05 --cell 0.01 | 0.005 | 0.0025
# precision comparison: --precision double | float on the 2-layer tile
# at-rest control: --speed 0 --gap 1.0 --min-ms 40 --max-ms 40 --no-failure-ms 100 --quiet-ms 100
```

Read `report.max_tensile_stretch`, `report.max_compressive_strain`,
`report.degenerate_disagreements`, `report.lattice.broken_bonds` and
`report.handoff.components`.
