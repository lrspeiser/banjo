# Node-to-node contact in the explicit lattice phase

Branch `agent/lattice-self-contact`, worktree
`C:\Users\henry\dev\banjo-agents\self-contact`, base `af8af80`. Local only, not
on main. Windows 11 Pro, MSVC 19.44 (Visual Studio 17 2022, x64, Release),
CUDA 12.9 (nvcc via the Ninja generator; the Visual Studio generator on this
machine has no CUDA MSBuild integration), NVIDIA GeForce RTX 5090 (sm_120),
24 hardware threads. September 8, 2026.

**Headline.** Nothing stopped a cell from passing through another cell; on the
250 x 200 x 10 mm glass plate at 10 mm cells, struck by a 60 mm iron ball at
20 m/s on two ledges, the worst overlap between two cells that no live bond
joined was **8.06 mm out of a 10 mm cell** -- an all-but-complete pass-through.
With node contact it is **0.0118 mm**, the contact margin, a factor of 683
smaller. A stack of eight loose cells dropped 50 mm collapsed into a single
layer 10 mm high before; it now rests 79.96 mm high against a geometric 80.00 mm.
The lane still meets the owner's 1.1x rule and meets it on one scene where it
did not before. The CPU, parallel-CPU and CUDA backends are bit identical with
contact on, and the fracture answer is unchanged, bit for bit, in every window
where contact does not act.

`physical_response_validated` stays false. Nothing here calibrates glass.

---

## 1. The rule, and why

> **Contact resolves a pair if and only if no LIVE bond joins it.**

A bonded pair is already held by its bond. Adding a contact response to it would
apply two responses to one interaction, stiffen the material in compression and
change the elastic reference the failure criterion is calibrated against --
exactly the double-counting AGENTS.md forbids. A pair whose bond has **failed**
is held by nothing, and that is precisely the crack surface a fragment would
otherwise pass through, so contact must act there. A pair that was never bonded
(beyond the horizon) is likewise held by nothing.

The alternative rule -- contact only between pairs that were never bonded --
was rejected because it does not solve the problem it was asked to solve: the
two faces of a crack are the *failed nearest-neighbour bonds*, and under that
rule fragments would still interpenetrate along every crack.

The rule is enforced twice, deliberately: `nodeContactGather` never puts a
live-bonded pair in the list, and `nodeContactPair` re-checks the bond's
aliveness where the response is applied. The second check makes the invariant
local to the code a reader looks at, and costs one byte load.

### Geometry

A cell is a cube of side `cell`. For contact it is the **inscribed sphere**, of
radius `cell / 2` -- the same radius the support planes already use to hold a
cell centre half a cell above a surface (`SupportPlane::node_radius`). Two cells
therefore touch when their centres are exactly one cell apart, which is the
lattice spacing. Three consequences, all wanted:

- **Contact is inert at rest.** The nearest unbonded pair in an intact lattice
  is at grid distance `sqrt(5) = 2.236` cells (horizon 2 admits every offset
  with `dx^2+dy^2+dz^2 <= 4`), which is 2.236 cells against a contact distance
  of 1 cell. Nothing is pushed.
- **Contact cannot act before the first failure.** The pair list reaches
  `2*radius + skin = 1.25` cells; every pair inside that radius of an intact
  lattice is bonded, so the list is empty and the narrow phase costs nothing.
  Measured: the first failure time is identical to twelve significant figures
  with contact off and on, on every scene in section 4.
- **A freshly failed face bond is exactly at the contact threshold**, gap zero.
  That is the correct statement for two touching cubes, and it is why a scene
  in which bonds break and fragments provably *never* touch does not exist in
  this geometry unless the failures are all long bonds. Section 4.3 uses such a
  window as the control.

Pair coefficients are `combineContactMaterials(tile, tile)`; restitution uses the
same `restitution_speed_threshold` (0.5 m/s) rule as the striker.

### The response

`nodeContactPair` is `sphereContactNode` with the rigid ball replaced by a
second node of finite mass: one normal impulse with the same speculative /
restitution rule, then one Coulomb friction impulse, then one overlap
correction, all applied **equal and opposite** to the two nodes. Momentum is
conserved by construction, and the run reports the residual
(`lattice.node_contact.momentum_residual_n_s`) as the receipt: 1.1e-16 N s over
321,576 contacts on the crush scene, 3.4e-17 over 174,239 on the panel default.
The overlap correction is mass-weighted, so the pair's centre of mass does not
move.

---

## 2. Broad phase

A uniform spatial hash with a Verlet skin, four steps, in this order:

| Step | What | Where it runs |
|---|---|---|
| 1 | Each node's grid cell of side `2*radius + skin`, and the displacement the list is built at | per node, spread |
| 2 | Counting sort of the nodes into the hash buckets | one thread |
| 3 | Each node's own pair list: scan its 27 neighbouring cells, keep partners of higher index inside the cutoff that no live bond holds | per node, spread |
| 4 | The ascending list of nodes owning at least one pair | one thread |

The hash is a power-of-two table (`latticeContactBucketMask`: the smallest power
of two at least twice the node count) addressed by Teschner's three-prime hash,
so the domain is unbounded -- fragments that leave the tile need no bounding box.
A bucket can hold several grid cells, so the gather compares the stored grid
coordinates before accepting a node; that removes both duplicates and collision
noise.

**Determinism.** Steps 1 and 3 write only the node's own slots, and steps 2 and
4 walk the nodes in index order, so the pair list is the same on the serial CPU,
the parallel CPU and the GPU regardless of thread scheduling. Each node owns at
most `kMaxPairsPerNode = 24` slots (`pair_other`, `pair_bond`), so no prefix sum
is needed; overflow is counted and reported (`pair_overflow`, zero in every run
below).

**Rebuild cadence, justified by measurement, not chosen.** The list is rebuilt
when either

1. a bond failed in the previous substep -- the topology changed, so which pairs
   are unbonded changed -- or
2. any node has drifted more than `skin/2` since the build (two nodes each moving
   `skin/2` towards one another close exactly the skin).

The drift test is one serial scan per substep. With `skin = 0.25 * cell` and a
1 us substep, a node moving at 20 m/s covers 0.002 cell per substep, so drift
alone forces a rebuild about every 60 substeps. Measured on the crush scene:
**598 rebuilds in 41,726 substeps** (1.4%), of which 190 were failure rounds.
On the panel scene, 342 rebuilds in 39,976 substeps.

**Why the list, not the raw hash, is the per-substep object.** Because bonded
pairs are excluded at build time, an intact lattice lists *zero* pairs, and the
narrow phase walks an empty list. All of the broad-phase work is paid only at a
rebuild.

**Measured cost** (250 x 200 x 10 mm plate, 500 cells, 2,777 bonds, parallel CPU
backend, 16 threads, double):

| | broad (s) | narrow (s) | lattice phase (s) | share |
|---|---:|---:|---:|---:|
| crush, 20 m/s, `measure` | 0.0166 | 0.0081 | 0.792 | 3.1% |
| crush, 20 m/s, `on` | 0.0314 | 0.0383 | 1.695 | 4.1% |
| panel default, `measure` | 0.0349 | 0.0355 | 2.171 | 3.2% |
| panel default, `on` | 0.0249 | 0.0340 | 1.680 | 3.5% |

`measure` runs the identical broad and narrow phases on the identical trajectory
as `off`, so the `measure`-vs-`off` pair is the clean throughput number: the
substep goes from **38.53 to 40.32 us (+4.6%)** on the panel scene and from
**39.41 to 41.15 us (+4.4%)** on the crush scene. Bond-updates per second on the
panel scene: 72.07 M (`off`) -> 68.88 M (`measure`) -> 66.09 M (`on`); on the
crush scene 70.47 M -> 67.48 M -> 68.35 M. The lane's quoted 75.6 M is on a
different scene; on this one it starts at 72.1 M and the contact takes 4.4%.

The worst case for the narrow phase is a body with **no bonds at all**, where
every near pair is a contact pair every substep. On the 32-loose-cell pile the
broad and narrow phases are 0.139 s of a 0.354 s lattice phase (**39%**, 0.007 s
of it broad) at 13.9 contacts per substep, against 0.228 s with contact off.
That is the ceiling, and it is the price of a granular pile rather than a cracked
solid; it is also 41 rebuilds in 207,204 substeps, so the ceiling is the narrow
phase, not the hash.

---

## 3. Where it sits in the substep, and backend parity

Two new phases are appended to `phase_seconds`, so every existing key keeps its
index and its meaning:

    ... damping (9), contact_pass_2 (10), node_contact_broad (14),
        node_contact_narrow (15), end_sample_nodes (11), end_sample_bonds (12),
        sphere_exit (13)

Contact runs after the striker's second pass and before the end strain sample,
so a contact that pushes two cells apart loads the bonds still attached to them
and the criterion sees it in the same substep. That is the same position the
striker's own position corrections occupy.

The physics is in `src/fastlattice/LatticePhysics.hpp` as `BANJO_HD` element
functions, as everything else in the lane is, so all three backends execute the
same code. The split is:

| | serial CPU | parallel CPU | CUDA |
|---|---|---|---|
| broad steps 1, 3 | serial loop | `forEach` over the thread pool | one thread per node stride |
| broad steps 2, 4; staleness scan | one thread | one thread | leader thread |
| narrow phase | one thread | one thread | leader thread |

**The broad phase is identical across backends** -- there is no approximation
and no per-backend variant. The narrow phase is one thread's work everywhere,
for the same reason the striker pass is: the response of one pair changes the
state the next pair sees, so pair order is part of the physics, and a fixed
order (owner node ascending, then slot ascending) is what keeps the parallel
backend bit identical.

Measured (`tests/fast_lattice_tests.cpp`):

- serial vs parallel at 2, 4 and 8 threads, through a cascade of 166 broken bonds
  and 74,178 contacts: every node position and velocity equal, same broken set,
  same contact ledger.
- CPU vs CUDA on the same window, double and float, one block and four slabs:
  `max |du| = 0`, `max |dv| = 0`, contacts 74,178 / 74,178 (double, 1 block),
  75,853 / 75,853 (double, 4 slabs), 70,536 / 70,536 (float, 1 block),
  70,046 / 70,046 (float, 4 slabs).

`tests/fracture_algo3_tests.cpp`'s existing bit-identity suite passes unchanged,
and so do the four guarded invariants: a rigid motion strains nothing, the
one-cell sheet keeps the nonlocal criterion, the one-element criterion equals
`fracture/BondFailure.cpp` for glass, oak and iron, and the colour-order sweep is
`BrittleBondSolver` in a permuted order.

---

## 4. The three measurements

Every run below: `banjo_fast_lattice_run`, parallel CPU backend, double
precision, glass tile, iron ball, concrete ground, reference material route.
Exact commands in section 7.

### 4.1 Interpenetration, before and after

250 x 200 x 10 mm glass plate, 10 mm cells (500 cells, 2,777 bonds), on two
ledges 120 mm up, struck by a 60 mm iron ball at 20 m/s.

| | worst overlap between unbonded cells | as a fraction of a cell |
|---|---:|---:|
| **before** (`--node-contact measure`) | **8.0607 mm** | 81% |
| **after** (`--node-contact on`) | **0.0118 mm** | 0.12% |

The "before" number is taken by the same broad and narrow phases, with the
response switched off, on the same trajectory: `measure` reproduces `off` bit for
bit (identical broken bonds 561, failure rounds 178, pieces 70 and removed energy
4.13636620723 J), which the test
`measuring the overlap changes nothing the run reports` asserts.

0.0118 mm is the contact margin (10 um) plus one substep of closing. The maximum
possible overlap is 10 mm -- two cell centres coincident -- so 8.06 mm is an
all-but-complete pass-through.

The fracture answer on this scene does change where contact acts, which is the
point: 561 -> 600 broken bonds, 70 -> 73 pieces, 4.136 -> 4.251 J removed. The
fragments now push on each other instead of passing through, and that loads
bonds that used to see nothing.

### 4.2 A pile that holds

Eight layers of loose cells -- a 20 x 80 x 20 mm glass block at 10 mm cells,
2 x 8 x 2 = 32 cells, **every bond removed** (`--loose-cells`) -- released 50 mm
above the ground and stepped for 200 ms of lattice phase. This is a contact
scene, not a fracture one: nothing is precut to stand in for a fracture outcome,
the criterion never runs (a bondless node has no strain), and no fracture claim
is made from it. It exists so contact can be measured on its own.

Layer centre heights at the end of the lattice phase, in mm:

| | layer centres | top face | geometric top face |
|---|---|---:|---:|
| **contact off** | 5.0 (all 32 cells) | 10.00 mm | 80 mm |
| **contact on** | 5.00, 14.99, 24.98, 34.97, 44.96, 54.96, 64.96, 74.96 | **79.96 mm** | 80 mm |

Without contact the whole block collapses onto the ground plane: every cell ends
at the one height the ground projection puts it at, eight layers occupying one
layer's space. With contact the eight layers are resolved and the stack stands at
**99.95% of its geometric height**; the 43 um shortfall is 5.4 um per interface,
about half the 10 um contact margin, which is what the response is allowed to
leave. Worst overlap over the whole run: 10.001 um, i.e. the margin.

### 4.3 The fracture answer where contact should not act

Three controls, from the strictest outward.

**(a) A fracture window in which the broad phase lists no pair.** The 120 x 40 x
160 mm glass tile at 20 mm cells on the ground, struck at 12 m/s, breaks 32 bonds
in 3 rounds in a 4,000-substep window. Every one of them is a diagonal or
two-cell bond, whose ends are 28.3, 34.6 or 40 mm apart against a 25 mm list
radius, so the broad phase runs (4 rebuilds) and lists **0 pairs**. Contact on
against contact off:

| | broken | first failure step | rounds | removed energy | node positions |
|---|---:|---:|---:|---:|---|
| `--node-contact off` | 32 | 170 | 3 | 15.2417 J | -- |
| `--node-contact on` | 32 | 170 | 3 | 15.2417 J | **bit identical** |

Asserted by `the fracture answer is unchanged where contact does not act`.

**(b) `--node-contact off` is `af8af80`, bit for bit.** The `af8af80` binary and
this branch's binary with contact off, same commands, three scenes:

| scene | first failure (s) | rounds | broken | pieces | removed (J) |
|---|---:|---:|---:|---:|---:|
| crush 20 m/s, af8af80 | 0.000139401051148 | 178 | 561 | 70 | 4.13636620723 |
| crush 20 m/s, `off` | 0.000139401051148 | 178 | 561 | 70 | 4.13636620723 |
| panel default, af8af80 | 0.00065457884887 | 321 | 997 | 135 | 3.29236799695 |
| panel default, `off` | 0.00065457884887 | 321 | 997 | 135 | 3.29236799695 |
| 192-cell 8 m/s, af8af80 | 0.000617641896737 | 95 | 305 | 13 | 28.4233163895 |
| 192-cell 8 m/s, `off` | 0.000617641896737 | 95 | 305 | 13 | 28.4233163895 |

**(c) The answer is unchanged up to and including the first failure, always.**
Contact cannot act while the lattice is intact (section 1), and the measurement
agrees on every scene run for this checkpoint: `first_failure_s` is identical to
twelve significant figures with contact off and on, in every case. The at-rest
control -- the 500-cell plate held on its ledges under gravity for 40 ms with the
ball parked 1 m away -- breaks 0 bonds under the af8af80 binary, under `off` and
under `on`.

There is one more control worth naming because it is nearly free: a 60 x 50 x
10 mm tile struck at 3 m/s breaks exactly one bond and then fires **2,138 node
contacts** across that crack -- and the fracture answer (first failure
0.000799030662741 s, 1 round, 1 bond, 1 piece, 0.0304735950711 J removed) is
identical to af8af80's to twelve figures. Contact acted, and it changed nothing.

### 4.4 Glass, oak and iron under identical conditions

240 x 40 x 160 mm tile, 20 mm cells (192 cells), on two ledges, 40 mm iron ball
at 8 m/s, everything else equal; only the tile material changes.

| material | mode | broken | pieces | removed (J) | worst overlap (mm) | contacts | contact dissipation (J) | realtime |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| glass | `off` | 305 | 13 | 28.4233 | -- | 0 | 0 | 0.204x |
| | `measure` | 305 | 13 | 28.4233 | **14.01** | 0 | 0 | 0.193x |
| | `on` | 303 | 13 | 27.6595 | **0.011** | 67,803 | 3.61 | 1.031x |
| oak | `off` | 104 | 3 | 14.0100 | -- | 0 | 0 | 0.215x |
| | `measure` | 104 | 3 | 14.0100 | **15.06** | 0 | 0 | 0.221x |
| | `on` | 63 | 1 | 16.0337 | **0.139** | 25,528 | 84.71 | 0.319x |
| iron | `off` | 0 | 1 | 0 | -- | 0 | 0 | 1.031x |
| | `measure` | 0 | 1 | 0 | 0 | 0 | 0 | 1.070x |
| | `on` | 0 | 1 | 0 | 0 | 0 | 0 | 1.065x |

Three things are worth naming.

- The **before** overlap is the same order in glass and oak, 14.0 and 15.1 mm of
  a 20 mm cell: interpenetration was never a material property, it was the
  absence of a contact.
- The **after** overlap is not: oak keeps 0.139 mm where glass keeps 0.011 mm, a
  factor of twelve. Oak's substep is longer (a softer lattice has a higher
  explicit limit), so `-vn * dt` is larger and the speculative branch engages
  later in distance, and there are fewer substeps in which to correct what is
  left. That is a limit of the single-pass response, section 9 item 2, and it is
  measured here rather than asserted.
- **Iron does not fracture at 8 m/s**, so no pair is ever listed and all three
  columns are identical, which is the strictest form of the section 4.3 control.

Oak's 84.7 J of contact dissipation against a 67.5 J ball is not a violated
budget: it is kinetic energy removed summed over the run, and the bond solve puts
elastic energy back in between contacts. Section 6.

---

## 5. The cost

Same scenes, before and after, isolated runs.

| scene | | lattice wall (s) | substeps | us/substep | **realtime ratio** | 1.1x rule |
|---|---|---:|---:|---:|---:|---|
| 500-cell plate, panel default (6.264 m/s, 2 s settle) | `off` | 2.075 | 53,839 | 38.53 | **1.171x** | miss |
| | `measure` | 2.171 | 53,839 | 40.32 | 1.217x | miss |
| | `on` | 1.680 | 39,976 | 42.02 | **0.896x** | **meet** |
| 500-cell plate, crush (20 m/s, 6 s settle) | `off` | 0.759 | 19,255 | 39.41 | **0.151x** | meet |
| | `measure` | 0.792 | 19,255 | 41.15 | 0.157x | meet |
| | `on` | 1.695 | 41,726 | 40.63 | **0.307x** | meet |

Read it this way. **Per substep the change costs 4-6%** -- the `measure` rows,
which are the same trajectory as `off`. Everything else in the table is the
cascade being a different length, which is physics, not overhead: on the panel
default the fragments now push each other apart instead of sliding through, the
cascade quiets after 39,976 substeps instead of 53,839, and the scene the brief
records as missing the rule at 1.97x through the panel **meets it at 0.893x**.
On the crush scene the opposite happens -- fragments driven together by a 20 m/s
punch keep breaking bonds for longer, 41,726 substeps instead of 19,255 -- and
the ratio goes from 0.152x to 0.311x, still five times inside the budget.

The brief's other reference point, a 1 m pane at 256 cells, is in section 5.1.

Neither direction is a claim about which cascade is right. Both are the same
criterion at the same tolerances reading a strain field that now includes the
contact the lane was missing.

### 5.1 The 1 m pane

1.0 x 1.0 m glass pane, 62.5 mm cells, one layer (16 x 16 x 1 = 256 cells),
60 mm iron ball dropped 2 m (6.264 m/s), on two ledges, 2 s settle.

| | lattice wall (s) | substeps | us/substep | broad (s) | narrow (s) | realtime ratio | rule |
|---|---:|---:|---:|---:|---:|---:|---|
| `off` | 0.1211 | 3,168 | 38.21 | 0 | 0 | 0.411x | meet |
| `measure` | 0.1102 | 3,168 | 34.78 | 0.0009 | 0.0001 | 0.371x | meet |
| `on` | 0.1127 | 3,168 | 35.57 | 0.0008 | 0.0001 | 0.376x | meet |

At 62.5 mm cells the pane is a slab and a 60 mm ball at 6.264 m/s breaks nothing:
0 bonds, 1 piece, contact never lists a pair. So this row measures the **floor**
of the change -- one broad-phase build plus the per-substep staleness scan --
which is 0.9 ms of a 110 ms lattice phase, **0.8%**, or 0.25 us per substep for
256 nodes. The 10% spread between the three rows is run-to-run noise at this size
(the whole lattice phase is a tenth of a second); the ratio is unchanged.

I could not reproduce the brief's 0.18x on this scene; what I measured with the
parameters above is 0.41x before the change and 0.38x after, and the honest
statement is that the change does not move it.

---

## 6. Energy

`lattice.dissipated_kinetic_energy_j` reports the three separately. Node contact
is always accounted (the narrow phase is serial, so the sum is in pair order on
every backend). The striker's and the bond damping's are measured by
`--energy-audit`, which brackets those phases with a serial kinetic-energy
reduction; it is off by default because it is two extra passes over the nodes
per substep.

Crush scene, 20 m/s, contact on, `--energy-audit`:

| | reference route | catalog route (`--catalog`) |
|---|---:|---:|
| node contact | 5.2338 J | 6.0112 J |
| striker contact | 8.8558 J | 32.4793 J |
| bond damping | **0.000000 J** | 0.000001 J |
| removed by fracture | 4.2508 J | 4.1821 J |

Bond damping is exactly zero on the reference route because
`compiled.bond_damping` is zero there, so `damping_fraction` is zero and the
damping sweep never runs -- that is now measured rather than assumed. The catalog
BrittleBond route does run it, and removes 1e-6 J.

These are **kinetic energy removed, summed over the run**, not a closed budget:
the same node is in many pairs over many substeps and the bond solve puts elastic
energy back in between them, so the totals can and do exceed the striker's
initial 178 J on long runs. A full pipeline energy ledger is not claimed.

---

## 7. Exact commands

Build (no CUDA):

```sh
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 6
ctest --test-dir build/agent -C Release -E "banjo_network_skin_tests|banjo_network_runtime_tests|banjo_material_showcase_tests|banjo_network_adaptive_tests|banjo_contact_capacity_tests"
python scripts/check-source-registration.py
```

Build with CUDA. The Visual Studio generator cannot find a CUDA toolset on this
machine (the CUDA MSBuild integration is not installed into the VS BuildTools
instance), so the CUDA configuration uses Ninja from a developer prompt:

```bat
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
cmake -S . -B build/cuda -G Ninja -DCMAKE_BUILD_TYPE=Release -DBANJO_BUILD_LAB=OFF -DBANJO_BUILD_CUDA=ON
cmake --build build/cuda --parallel 6
build\cuda\banjo_fast_lattice_tests.exe
```

Scenes:

```sh
E=build/agent/Release/banjo_fast_lattice_run.exe

# 4.1 interpenetration, before and after (--node-contact measure | on | off)
$E --material glass --ball-material iron --tile 0.25 0.01 0.2 --cell 0.01 \
   --ball-radius 0.03 --speed 20 --offset 0 0 --layout bridge \
   --backend parallel --precision double --node-contact measure --report crush.json

# 4.2 the pile (contact off | on)
$E --material glass --ball-material iron --tile 0.02 0.08 0.02 --cell 0.01 \
   --loose-cells --layout flat --drop 0.05 --speed 0 --gap 1.0 --ball-radius 0.01 \
   --max-ms 200 --min-ms 200 --no-failure-ms 0 --quiet-ms 0 --settle-s 0.02 \
   --frames 60 --backend parallel --precision double --node-contact on --report pile.json

# 4.3a a fracture window with no near unbonded pair (contact off | on)
$E --material glass --ball-material iron --tile 0.12 0.04 0.16 --cell 0.02 \
   --ball-radius 0.03 --speed 12 --gap 0.0005 --layout flat --backend cpu --precision double \
   --max-ms 8 --min-ms 8 --no-failure-ms 0 --quiet-ms 0 --node-contact on --report window.json

# 4.3c the at-rest control
$E --material glass --ball-material iron --tile 0.25 0.01 0.2 --cell 0.01 --ball-radius 0.03 \
   --speed 0 --gap 1.0 --layout bridge --min-ms 40 --max-ms 40 --no-failure-ms 100 \
   --quiet-ms 100 --settle-s 0.2 --backend parallel --precision double --node-contact on

# 5 the panel default (what playground/fracture_lab.py drives)
$E --material glass --ball-material iron --tile 0.25 0.01 0.2 --cell 0.01 --ball-radius 0.03 \
   --speed 6.26424 --offset 0 0 --layout bridge --settle-s 2 \
   --backend parallel --precision double --node-contact on --report panel.json

# 6 the energy audit
$E ... --energy-audit
```

New flags, all with the previous behaviour as the fallback except
`--node-contact`, which defaults to `on`:

| flag | meaning |
|---|---|
| `--node-contact on\|measure\|off` | the contact. `off` is `af8af80` bit for bit; `measure` runs the broad and narrow phases and records the worst overlap without applying anything |
| `--node-contact-skin F` | Verlet skin = `F * cell` (default 0.25) |
| `--drop H` | start the tile `H` metres above its support |
| `--loose-cells` | remove every bond: a heap of separate cells, a contact scene |
| `--energy-audit` | measure the damping and striker dissipation as well |

**The default is `on`.** `playground/fracture_lab.py` passes no new flag and
keeps working; it now drives the contact, which is the point of the work. Its
default scene's answer changes accordingly (section 5), and `--node-contact off`
restores the old answer exactly if the owner wants the comparison.

---

## 8. Watchable

Registered in the owner's store (`C:\Users\henry\dev\banjo\build\playground-runs`,
server already running on port 8765; the playground loads a job directory on
first request, no restart needed). No file in the owner's checkout was modified
other than adding these run directories.

- **Interpenetration, before and after** --
  `http://127.0.0.1:8765/?job=72fae9eb461e4aff8d81b32e770f33b4`
  - case 1: `--node-contact measure`, the 500-cell glass plate struck at 20 m/s,
    worst overlap between unbonded cells 8.06 mm of a 10 mm cell;
  - case 2: `--node-contact on`, the same strike, worst overlap 0.0118 mm.
- **A pile that holds** --
  `http://127.0.0.1:8765/?job=cf5a9e542ce54e43b71cd247642b48ab`
  - case 1: without contact, 32 loose glass cells dropped 50 mm collapse into one
    10 mm layer;
  - case 2: with contact, the same drop rests in eight layers, 79.96 mm high.
- **The fracture answer, where contact cannot act and where it can** --
  `http://127.0.0.1:8765/?job=4fef7d414a844117af829c7607454ecc`
  - cases 1 and 2: the 96-cell tile at 12 m/s with contact off and on -- 32 bonds,
    15.2416566484 J removed, every node position bit identical;
  - cases 3 and 4: the Fracture lab default plate at 6.264 m/s with contact off
    and on -- 997 bonds / 135 pieces / 1.17x against 523 bonds / 55 pieces /
    0.90x.

Verified in a browser: job `72fae9eb...` opens on the 3D Playback tab with the
plate on its ledges and the ball above it, the case selector carries both cases,
and the frame scrubber steps through the strike into the scattered fragments
(frame 31/79 at t = 1.556 s). Job `cf5a9e54...` plays the same way.

---

## 9. What does not work, and limits

1. **The narrow phase is one thread.** It is faithful to the lane's existing
   choice for the striker pass and it is what makes the parallel backend bit
   identical, but on a body with no bonds it is 36% of the substep (section 2).
   A parallel narrow phase would need an order-preserving colouring of the pair
   graph, which is the same problem the bond sweep solves and has not been done
   here.
2. **The response is one Gauss-Seidel pass per substep, not a solve.** A cell
   squeezed between two others is resolved pair by pair in list order; there is
   no simultaneous solution and no stacking iteration count. It holds an
   eight-layer pile to 5 um per interface at a 1 us substep (section 4.2), and it
   leaves twelve times more residual overlap in oak than in glass on the same
   strike because oak's substep is longer (section 4.4). It has not been tested
   on a deep pile at a coarse substep, and it will sink further as `dt` grows.
3. **Contact acts between cell centres, not between cell faces.** The contact
   sphere is the cube's inscribed sphere, so two cells meeting corner to corner
   touch later than two cubes would, and a cell can sit in the gap between four
   others. That is the same approximation the support planes already make.
4. **No rotation.** Lattice cells have no orientation in this phase, so contact
   applies no torque and friction is a pure translational Coulomb impulse. The
   rigid handoff to Jolt is where cells acquire orientation.
5. **The fracture answer changes where contact acts**, in both directions
   (fewer bonds broken on the panel default, more on the crush). Nothing here
   says which is right; the criterion and its tolerances are untouched.
6. **`kMaxPairsPerNode = 24`** caps how many contacts one cell can own. It was
   never reached in any run here (`pair_overflow = 0` everywhere), but a
   sufficiently compacted heap could reach it; overflow is counted and reported
   rather than silently dropped, and the reported count is the signal to raise
   the cap.
7. **The energy audit is not a closed ledger** (section 6). It attributes
   kinetic energy removed per phase; it does not account elastic storage,
   gravity work or the support planes.
8. **`--loose-cells` is a contact scene, not a fracture one.** It must never be
   used to stand in for a fracture outcome; it exists so contact is testable
   without the criterion.
9. Not done: contact between lattice cells and the rigid ball's fragments after
   the handoff, self-contact during the rigid phase (Jolt does that), a
   broad-phase variant that keeps bonded pairs in the list so a rebuild is not
   needed on every failure round, and any change to the criterion or its
   tolerances.

---

## 10. Files

| Path | Change |
|---|---|
| `src/fastlattice/LatticePhysics.hpp` | `NodeContactSettings`, `NodeContactAccumulators`, `latticeContactBucketMask`, the four broad-phase element functions, `nodeContactStale`, `nodeContactPair`, `nodeContactPass`, `latticeKineticEnergy`; the pair-list arrays in `LatticeArrays` |
| `src/fastlattice/LatticeWorking.hpp` | allocation of the broad-phase arrays and the settings conversion |
| `src/fastlattice/FastLattice.{hpp,cpp}` | `kPhaseCount` 14 -> 16, the two phase names, `RunStatus::node_contact` and the audit fields |
| `src/fastlattice/CpuLatticeBackend.cpp` | the contact phases and the rebuild flag |
| `src/fastlattice/ParallelCpuLatticeBackend.cpp` | the same, with steps 1 and 3 spread over the pool |
| `src/fastlattice/CudaLatticeBackend.cu` | the same in the kernel, plus the device buffers and the status fields |
| `src/fastlattice/TileImpactScene.{hpp,cpp}` | `NodeContactMode`, `tile_drop_m`, `loose_cells`, `audit_energy`, the tile-tile contact material, the JSON |
| `tools/fast_lattice_run.cpp` | the five flags |
| `tests/fast_lattice_tests.cpp` | six suites (section 3 and section 4) |
