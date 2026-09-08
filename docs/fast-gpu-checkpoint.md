# Fast-GPU lane checkpoint: the CPU lattice physics on a colour-parallel schedule

Branch `agent/fast-gpu` (base `432fb88` = `f7c4dc3` with `agent/playground-rebuild`
merged), worktree `C:\Users\henry\dev\banjo-agents\fast-gpu`, local only, not
on main. Windows 11 Pro, MSVC 19.44 (Visual Studio 17 2022, x64, Release),
CUDA 12.9 (runtime 12090, driver 13000 / 580.88), NVIDIA GeForce RTX 5090
(sm_120, 170 SMs, 32 GB, of which 24 GB and about 8% utilisation belonged to
another process throughout these measurements), 24 hardware threads.
September 7, 2026.

**Headline.** The 1.1x rule is met on the headline scene and fails above it.
A 192-cell uniform-cube glass tile (0.24 x 0.04 x 0.16 m, 20 mm cells, 1,704
bonds) resting on two ledges, struck by a 4 cm iron ball at 8 m/s, fractures
into 3 pieces that fall and settle: 1.895 s of simulated time in 0.38 s of
wall time (0.20x) on the GPU, the whole thing recorded for the playground. The
same tile struck at 12 m/s (59 pieces) takes 0.57x. The rule holds for glass at
12 m/s up to 384 cells (0.71x), fails at 800 cells (1.50x) and fails by 7x at
every 1,536-cell (10 mm cell) glass scene, where the fracture cascade fills the
whole 200 ms lattice window at 142-155 us per substep. Oak and iron at 1,536
cells pass (0.76x, 0.59x) because their cascades end within 15-21 ms.

**What the GPU is and is not.** The CUDA backend executes `BrittleBondSolver`'s
physics and `fracture/BondFailure.cpp`'s criterion bit for bit: on the same
state it produces the same positions, velocities, damage, removed bonds and
removed energy as this lane's CPU backend (`max |du| = 0` through a fracture
cascade, double and float, one block and four slabs), and that CPU backend is
`BrittleBondSolver` in a permuted sweep order (`max |dx| = 4.0e-11 m` through a
646-bond cascade, identical first-failure set, pieces and energy). But the GPU
is **no faster than one CPU thread at the headline size**: 55 M bond-updates/s
on the GPU against 57-68 M for this lane's single-threaded CPU backend (and
19-21 M for `BrittleBondSolver` itself, 0.85 M for the network lane the brief
quotes). The GPU overtakes one core from 384 cells on (1.9x there, 2.5x at
800 cells, 3.3x at 1,536: it is what extends the rule from 192 to 384 cells)
and reaches 616 M bond-updates/s at 173k bonds, five times short of the ~3e9
the brief estimated.
The obstacle is structural: one Gauss-Seidel substep is a chain of 22-32
node-disjoint colour stages, each a barrier, so a substep costs 25-35 us on
one block and about 110 us of sweep alone with slabs, almost independently of
the bond count below 20k bonds, while the substep itself is 0.3-1.6 us of
simulated time.

Implemented and validated, experimental and unvalidated, and not working are
labelled separately below. `physical_response_validated` stays false; nothing
here calibrates glass, and the fracture outcome is not converged with respect
to sweep order, precision or cell size (section 8).

## 1. What exists on the branch

| Path | Role |
|---|---|
| `src/matter/BoxLattice.{hpp,cpp}` | Uniform-cube box lattice with `generateSphereLattice`'s bond rules (horizon, rest length, compliance over the horizon weight, per-bond strength variation), plus the slab split along z |
| `src/fastlattice/LatticeSchedule.{hpp,cpp}` | Greedy edge colouring (22-32 colours on these lattices) and slab decomposition: interior bonds, then boundary bonds of even and of odd slabs |
| `src/fastlattice/LatticePhysics.hpp` | Every element function, `__host__ __device__`: node strain, criterion, XPBD bond solve, damping, support projection and velocity response, sphere contact, exit rule |
| `src/fastlattice/FastLattice.{hpp,cpp}`, `LatticeWorking.hpp` | Canonical state in schedule order, precision-specific working copy, write-back into `ActiveMatter` |
| `src/fastlattice/CpuLatticeBackend.cpp` | The same phases on one thread: the fallback and the reference the kernel is proven equal to |
| `src/fastlattice/CudaLatticeBackend.cu` | One persistent cooperative kernel per launch (behind `BANJO_BUILD_CUDA`, default OFF); `CudaLatticeUnavailable.cpp` throws a clear error otherwise |
| `src/fastlattice/TileImpactScene.{hpp,cpp}` | The scene, the rigid handoff to Jolt, the `banjo.playback.v1` writer, the `BrittleBondSolver` comparison |
| `tools/fast_lattice_run.cpp` | Driver (`banjo_fast_lattice_run`) |
| `tests/fast_lattice_tests.cpp` | Seven suites (`banjo_fast_lattice_tests`), section 5 |
| `scripts/fast-gpu-sweep.py`, `scripts/fast-gpu-install-playback.py` | The measurement matrix (evidence under `docs/evidence/fast-gpu/`) and the playground job installer |

Most of this was written by the previous agent and left uncommitted and
unbuilt when it was cut off; this checkpoint built it, found and fixed four
defects (section 2.8), added the fracture-window equality tests, measured it
and committed it. The CMake guard `python scripts/check-source-registration.py`
passes: every source is built by a target.

## 2. Method

### 2.1 Scene

A box lattice of uniform cubic cells (aspect 1:1:1, never rounded: a tile
whose extent is not a whole number of cells is refused), every cell full, so
node masses are uniform. Material via the strength-derived elastic reference
shared by all presets (`withStrengthDerivedFailure(compileElasticLatticeReference(...))`),
horizon 2 cells (32 bonds at an interior node). Glass tile, iron ball, concrete
ground, contact coefficients from `combineContactMaterials`. Two layouts: `flat`
(tile on the ground; expressible by `BrittleBondSolver`, used for the
comparison) and `bridge` (tile resting on two ledges 0.12 m above the ground,
each ledge 2 x 0.04 m wide under the ends of the tile's long axis, so the
middle falls; the headline). The ball starts 2 mm above the tile top, moving
straight down.

The substep is `dt_factor` (0.5) times the lattice's own explicit limit
`2/omega_max` from `measureLatticeResolutionLimit`: 1.59 us at 20 mm cells,
0.67 us at 10 mm, 0.33 us at 5 mm for glass. One constraint iteration per
substep. The lattice phase ends when no bond has failed for 10 ms (after at
least 5 ms), when nothing has failed by 20 ms, or at 200 ms.

### 2.2 The physics is the CPU lane's, one element at a time

`LatticePhysics.hpp` re-expresses, statement by statement:

- `fracture/BondFailure.cpp`: the nonlocal Green-Lagrange node strain
  (weighted rest/current covariance over live neighbours, `1/|rest edge|^2`
  weights, three live neighbours and a non-degenerate rest covariance required),
  its resolution along the bond's rest axis, the bond's own stretch as the
  fallback, the linear damage ramp, tension-first tie break, removal at damage
  1, and the removed stored energy `0.5 * extension^2 / compliance`.
- `fracture/BrittleBondSolver.cpp`: the XPBD bond solve with per-substep
  `accumulated_lambda` reset, the support projection inside the constraint
  sweep with the approach-speed/restitution/Coulomb velocity response of
  engaged nodes, the velocity reconstruction from accepted positions, and the
  radial pair damping (zero on the reference route).
- `physics/SphereMaterialContact.cpp`: the sequential node-order impulse and
  position-correction pass against the rigid ball, twice per substep.

The substep order is the CPU's: start sample (only after a topology change;
otherwise the previous end sample is reused, which is what the CPU computes),
gravity kick, contact pass 1, approach speeds, prediction, sweep with support
projection, velocity update, damping, contact pass 2, support velocity, end
sample and failure. The one-element criterion is tested against
`BondFailure.cpp` on the same deformed, partly broken lattices for glass, oak
and iron (section 5).

### 2.3 Schedule

Bonds that share a node cannot be solved at the same time, so the bond graph is
edge-coloured greedily; one colour is a node-disjoint set solved in one
parallel stage. Across blocks the nodes are split into z-slabs at least one
horizon thick and a bond belongs to the slab of its lower node: every block
sweeps its interior bonds, then the even slabs sweep their boundary bonds,
then the odd slabs. Every bond is solved exactly once per iteration against
the latest positions: it is a Gauss-Seidel sweep in a permuted order, not a
Jacobi relaxation. The permutation is the only physics-level difference from
the CPU lane's index-order sweep, and it is measured (section 6.6).

### 2.4 CUDA backend

One persistent cooperative kernel advances up to `steps_per_launch` substeps
(10,000 by default, well under the display watchdog) with the host consulted
only between launches: the exit rule, the failure bookkeeping and the frame
capture all run on the device. Within a substep, colour stages are separated
by block barriers and the phases by `grid.sync()` (a `__syncthreads()` when the
grid is one block). A single-block run keeps positions, node strain, validity
and the bond constants in dynamic shared memory when they fit (62 KB at 192
cells). The sphere contact pass, which the CPU resolves sequentially in node
order because every impulse changes the ball the next node sees, is executed
by one thread over per-block candidate lists that a conservative parallel
prefilter compacted in node order (a node is a candidate if it could pass the
CPU's gap test for any ball velocity reachable within the step, plus a slack
of 5% of the ball radius; overflow of the 1,024-entry list is an error, never
a silent drop). Failure counters use atomics; the removed energy is an atomic
sum of identical addends (its summation order is the only thing that can differ
from the CPU, at 1e-16 relative).

**FMA contraction is off** (`BANJO_CUDA_FMAD`, default OFF, `-fmad=false`).
nvcc fuses `a*b+c` by default and MSVC (`/fp:precise`) never does; the fused
operation rounds once where the CPU rounds twice, and the discrete removal
decisions turn that last-bit difference into a different cascade within a few
hundred substeps (with FMA on: 1,562 vs 1,522 broken bonds on the 192-cell
scene, both in double). With it off the kernel reproduces the CPU backend bit
for bit; the cost is +4.5% on the float path (31.4 -> 32.8 us/substep) and
+5.5% in double.

### 2.5 Precision

`double` runs the CPU's arithmetic in its operation order on absolute
positions. `float` is the fast path: positions are carried as displacements
from the reference configuration and the strain is formed from `F - I`
directly, so the criterion keeps ~1e-7 relative precision where a naive float
port would lose it to cancellation; the rest-covariance degeneracy threshold is
relative in float (the CPU's absolute 1e-16 is below float rounding noise) and
the number of nodes on which the two rules would disagree is counted
(`degenerate_disagreements`: 1-13 recomputations per run here). The float path
reproduces the CPU float backend bit for bit; it does **not** reproduce the
double cascade (section 6.6).

### 2.6 Handoff and settling

At the end of the lattice phase the connected components of the live bond
graph (`findConnectedComponents`) become rigid fragments through the engine's
`buildFragmentRepresentations` and are stepped by `JoltWorld` at 240 Hz with
the ball and the ledges until every piece is below 0.01 m/s and 0.1 rad/s for
0.3 s, or 6 s have passed. Jolt's contact capacity is sized from the piece
count (the default 8,192 constraints overflowed at about 300 pieces; Jolt then
refuses the step rather than dropping contacts). The ball is not part of the
rest criterion: under Jolt's rolling resistance a ball that rolled off keeps
rolling. Pieces do not fracture again after the handoff (section 8).

### 2.7 Recording

`banjo.playback.v1`, mode `network`: cells as boxes, the ball, the ledges, a
ground support, per-frame cell poses with component ids, `fracture_count`, and
bond lines with live/damage state for lattice-phase frames. Frames are thinned
and bond lines dropped only to keep a recording inside the playground's 64 MiB
budget; thinning happens after the simulation and changes nothing computed.

### 2.8 What differs from the CPU lane, and four defects fixed here

1. **Sweep order** (section 2.3), measured in section 6.6.
2. **Finite support footprints.** `BrittleBondSolver` has one footprint; the
   bridge needs two ledges plus the ground. A ledge has an edge a node can
   fall past and then drift under; the CPU's unconditional projection would
   teleport such a node back up through its bonds (the previous agent measured
   kilojoules injected this way). On a finite footprint the projection
   therefore only stops what arrives from above (`reach = 8 * |approach| * dt +
   10 um`). The previous agent applied that cap to every plane and believed it
   inert on an infinite one; it is not: under a hard strike the sweep pushes a
   resting bottom node deeper than 10 um in one substep and the CPU projects
   it. **Fixed:** the cap is a per-plane property set only for finite
   footprints; on the ground the CPU rule applies unchanged, and the
   comparison of section 6.6 went from diverging before the first failure to
   agreeing through the cascade.
3. **FMA contraction** (section 2.4). **Fixed** by the build option.
4. **The comparison's first-failure set** was read from a 300-step capture
   stride, so it reported every bond dead by the next capture. **Fixed:** the
   lane is run through the reference's first failure step, its dead set read
   there, then continued.
5. **Recording budget.** Bond lines in every frame put a 1,536-cell recording
   far over 64 MiB. **Fixed:** frames are thinned to a byte budget and bond
   lines are written for lattice frames only.
6. **Jolt capacity** (section 2.6). **Fixed** by sizing.
7. The ball meets the ledges/ground during the lattice phase through the same
   restitution/friction rule a node uses (`sphereSupportContact`); the CPU
   material solver has no such rule (Jolt does it there). Both lanes use it in
   the comparison.

No threshold, tolerance or material law changed. The lane never chooses a
cheaper criterion: every bond is judged by the nonlocal strain at every
substep.

## 3. Papers used

- M. Macklin, M. Muller, N. Chentanez, *XPBD: Position-Based Simulation of
  Compliant Constrained Dynamics*, MIG 2016. The compliance form of the bond
  solve (`alpha = compliance / dt^2`, accumulated lambda) is the CPU lane's and
  is reproduced here unchanged.
- M. Macklin et al., *Small Steps in Physics Simulation*, SCA 2019. One
  Gauss-Seidel iteration per small substep: `dt_factor 0.5`, `iterations 1`.
  Used as the justification for not adding iterations when going parallel.
- M. Fratarcangeli, F. Pellacini, *Scalable Partitioning for Parallel Position
  Based Dynamics*, Computer Graphics Forum 34(2), 2015. The idea of graph
  colouring to run a Gauss-Seidel PBD sweep in node-disjoint parallel stages.
  Only the idea was taken; the slab decomposition and the persistent kernel
  are this lane's.

Not used: the peridynamics literature (Silling 2000; Silling & Askari 2005) and
GPU peridynamics implementations. The bond lattice, its criterion and its
solver are the engine's existing ones; nothing was taken from those papers.

## 4. Exact commands

```
# CPU-only build (CUDA backend absent, throws a clear error if asked for)
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 4 --target banjo_fast_lattice_tests banjo_fast_lattice_run
build\agent\Release\banjo_fast_lattice_tests.exe

# CUDA build (sm_120, -fmad=false unless -DBANJO_CUDA_FMAD=ON)
cmake -S . -B build/agent-cuda -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF -DBANJO_BUILD_CUDA=ON
cmake --build build/agent-cuda --config Release --parallel 4 --target banjo_fast_lattice_tests banjo_fast_lattice_run
build\agent-cuda\Release\banjo_fast_lattice_tests.exe

# Headline scene, GPU, with recording and report
build\agent-cuda\Release\banjo_fast_lattice_run.exe --layout bridge --ball-radius 0.04 --speed 8 --tile 0.24 0.04 0.16 --cell 0.02 --record out.playback.json --report out.json

# Same scene on the CPU backend in double (the reference-faithful cascade)
build\agent-cuda\Release\banjo_fast_lattice_run.exe --layout bridge --ball-radius 0.04 --speed 8 --tile 0.24 0.04 0.16 --cell 0.02 --backend cpu --precision double --record out.playback.json

# Comparison against BrittleBondSolver (flat layout), index order and schedule order
build\agent\Release\banjo_fast_lattice_run.exe --layout flat --ball-radius 0.04 --speed 12 --tile 0.24 0.04 0.16 --cell 0.02 --backend cpu --precision double --compare-only --compare-steps 15000 [--compare-permuted]

# The measurement matrix (docs/evidence/fast-gpu/*.json, summary.csv); --only merges rows
python scripts/fast-gpu-sweep.py --record bridge-192,bridge-192-v8,bridge-1536-v8-blocks8

# Register recordings as a playground job in the owner's store
python scripts/fast-gpu-install-playback.py docs/evidence/fast-gpu/bridge-192-v8.playback.json docs/evidence/fast-gpu/bridge-192.playback.json --runs C:/Users/henry/dev/banjo/build/playground-runs --name "..." --name "..."

python scripts/check-source-registration.py
```

The five suites the brief excludes (`banjo_network_skin_tests`,
`banjo_network_runtime_tests`, `banjo_material_showcase_tests`,
`banjo_network_adaptive_tests`, `banjo_contact_capacity_tests`) were not run.
The lane's own suite runs in 0.2 s (CPU build) and 2.4 s (CUDA build).

## 5. Equality evidence (validated)

`banjo_fast_lattice_tests`, all passing on both builds:

1. **Box lattice follows the sphere generator's bond rules**: 32 bonds at an
   interior node, rest length = grid distance, compliance = bond compliance x
   grid distance^2, the same per-offset compliance as a sphere lattice of the
   same material, uniform mass, non-integer cell counts refused.
2. **The schedule is a proper edge colouring over adjacent slabs**: no colour
   stage shares a node, every bond swept exactly once, every bond joins the
   same or adjacent slabs, owner is the lower slab (1 and 4 slabs, 22 colours,
   264 boundary bonds).
3. **The one-element criterion equals `fracture/BondFailure.cpp`** on affinely
   strained, noisy, 20%-dead lattices for glass, oak and iron: in double the
   resolved peaks, damage, removed set (84/84, 317/317, 84/84), failure modes
   and removed energy agree exactly (peak error 0, energy error <= 4e-16
   relative); in float the peak error is <= 5.3e-9, damage <= 5.1e-7, energy
   <= 4.2e-6 relative, with the same removed set and modes.
4. **The colour-order sweep names the same failing bonds as the index-order
   `BrittleBondSolver`** on the axis-aligned 3x3x3 lattice of
   `tests/implicit_fracture_tests.cpp` stretched past the break strain: 18 of
   54 bonds, the same 18, 3 components, for glass, oak and iron.
5. **The lane is `BrittleBondSolver`'s physics in a permuted sweep order**
   (flat 192-cell tile, 12 m/s, 4,000 substeps = 6.4 ms): against the
   reference sweeping the lane's order, first failure at step 219 with the
   same 28 bonds, 646/646 broken, 4/4 pieces, 110.719/110.719 J removed,
   `max |dx| = 4.0e-11 m`, `max |dv| = 1.1e-7 m/s`, 0 alive mismatches. Against
   the index-order reference the first failure step and set are identical and
   the cascade then differs (620 vs 646 broken, 107.782 vs 110.719 J): the
   Gauss-Seidel ordering effect.
6. **CPU and CUDA backends agree** without fracture (400 substeps): `max |du|
   = 0` in double and float, one block and four slabs with 37 substeps per
   launch (11 launches), same sphere state.
7. **CPU and CUDA backends agree bit for bit through a fracture cascade**
   (2,500 substeps, 32 bonds failing in 3 rounds from step 170): 0 alive
   mismatches, `max |du| = |dv| = |ddamage| = 0`, same failure history and
   removed energy (<= 2.3e-16 relative), in double and float, one block and
   four slabs, ten launches.

At scene level the sweep confirms it: GPU float and CPU float give the same
21,898 substeps, 1,534 broken bonds, 645 failure rounds, 59 pieces and
37.09 J on the 192-cell bridge; GPU double and CPU double the same 22,266,
1,522, 619, 58 and 37.10 J.

## 6. Measurements (experimental result, not validated physics)

All rows: `docs/evidence/fast-gpu/<name>.json` (full report incl. per-phase
seconds and contact accumulators) and `summary.csv`. Bridge layout, 4 cm iron
ball (2.11 kg), glass unless noted, 12 m/s unless noted, GPU float, 512 threads
per block. `us/step` is lattice wall time per substep, `M bu/s` bond-updates
per second (bonds x substeps / lattice wall). "rigid" is the Jolt settling
phase. Timings are repeatable to about +-1% (three repeats of the 192-cell
scene: 31.4/31.4/31.5 and 32.78/32.83/32.83 us/step); the GPU was shared with
another process throughout.

### 6.1 Headline

| scene | cells | bonds | dt | substeps | lattice sim | lattice wall | us/step | broken | pieces | largest | rigid sim / wall | at rest | total sim | total wall | ratio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bridge-192-v8 (8 m/s) | 192 | 1,704 | 1.59 us | 7,288 | 11.6 ms | 0.26 s | 35.3 | 286 | 3 | 96 cells, 1.92 kg | 1.88 s / 0.05 s | yes, 1.5 s | 1.895 s | 0.38 s | **0.199** |
| bridge-192 (12 m/s) | 192 | 1,704 | 1.59 us | 21,898 | 34.8 ms | 0.67 s | 30.7 | 1,534 | 59 | 66 cells, 1.32 kg | 1.36 s / 0.06 s | yes | 1.397 s | 0.80 s | **0.574** |
| same, CPU backend double | 192 | 1,704 | 1.59 us | 22,266 | 35.4 ms | 0.55 s | 24.8 | 1,522 | 58 | 0.82 kg | 1.51 s / 0.07 s | yes | 1.544 s | 0.63 s | **0.406** |
| same, GPU double | 192 | 1,704 | 1.59 us | 22,266 | 35.4 ms | 3.42 s | 153.4 | 1,522 | 58 | 0.82 kg | 1.51 s / 0.07 s | yes | 1.544 s | 3.57 s | **2.315** |

The total wall time includes setup, frame conversion (a connected-component
labelling per captured lattice frame, on the CPU) and the handoff; the
recording is written afterwards (0.05 s for the 192-cell scenes, 0.5 s for
1,536 cells) and is not in the ratio. The 8 m/s strike breaks the tile into a
large middle piece and two ends resting on the ledges; the 12 m/s strike
crushes it (90% of the bonds).

### 6.2 Scaling (glass, 12 m/s)

| scene | cells | bonds | blocks | colours | dt | substeps | lattice sim | lattice wall | us/step | M bu/s | broken | pieces | total sim | total wall | ratio | rule |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bridge-96 | 96 | 792 | 1 | 22 | 1.59 us | 8,897 | 14.1 ms | 0.23 s | 25.7 | 31 | 696 | 23 | 1.110 s | 0.35 s | 0.314 | met |
| bridge-192 | 192 | 1,704 | 1 | 23 | 1.59 us | 21,898 | 34.8 ms | 0.67 s | 30.7 | 55 | 1,534 | 59 | 1.397 s | 0.80 s | 0.574 | met |
| bridge-384 | 384 | 3,592 | 1 | 23 | 1.59 us | 77,867 | 123.6 ms | 4.05 s | 52.0 | 69 | 3,073 | 125 | 6.124 s | 4.34 s | 0.709 | met |
| bridge-800 | 800 | 7,768 | 1 | 23 | 1.59 us | 125,963 | 200 ms (cap) | 8.95 s | 71.1 | 109 | 6,810 | 232 | 6.200 s | 9.32 s | 1.503 | not met |
| bridge-1536 | 1,536 | 18,852 | 1 | 31 | 0.67 us | 298,553 | 200 ms (cap) | 46.3 s | 155.1 | 122 | 18,012 | 769 | 6.200 s | 49.2 s | 7.927 | not met |
| bridge-1536-blocks4 | 1,536 | 18,852 | 4 | 31 | 0.67 us | 298,553 | 200 ms (cap) | 44.9 s | 150.5 | 125 | 17,808 | 818 | 6.200 s | 46.0 s | 7.413 | not met |
| bridge-1536-blocks8 | 1,536 | 18,852 | 8 | 31 | 0.67 us | 298,553 | 200 ms (cap) | 42.5 s | 142.2 | 133 | 16,803 | 702 | 6.200 s | 43.7 s | 7.045 | not met |
| bridge-1536-v8-blocks8 (8 m/s) | 1,536 | 18,852 | 8 | 31 | 0.67 us | 298,553 | 200 ms (cap) | 43.2 s | 144.6 | 130 | 15,334 | 672 | 6.200 s | 45.2 s | 7.287 | not met |
| bridge-3072-blocks8 (30 ms window) | 3,072 | 38,596 | 8 | 31 | 0.67 us | 44,783 | 30 ms | 8.14 s | 181.7 | 212 | 11,762 | 294 | 6.030 s | 9.43 s | 1.563 | not met |
| bridge-6400-blocks8 (30 ms window) | 6,400 | 81,780 | 8 | 31 | 0.67 us | 44,783 | 30 ms | 11.12 s | 248.4 | 329 | 18,492 | 448 | 6.030 s | 12.47 s | 2.068 | not met |
| bridge-6400-blocks20 (30 ms window) | 6,400 | 81,780 | 20 | 31 | 0.67 us | 44,783 | 30 ms | 7.95 s | 177.5 | 461 | 9,312 | 223 | 6.030 s | 8.48 s | 1.406 | not met |
| bridge-12288-blocks16 (30 ms window) | 12,288 | 173,196 | 16 | 32 | 0.33 us | 90,267 | 30 ms | 25.4 s | 281.1 | 616 | 18,335 | 548 | 6.030 s | 28.0 s | 4.642 | not met |

Rows above 1,536 cells cap the lattice window at 30 ms because the verdict
is already settled by then; they measure cost per substep and throughput, not
the rule. Slab count is limited by the tile's thickness in z (slabs must be a
horizon thick), so 8 slabs at 16 layers, 20 at 40, 16 at 32.

Three things decide the rule, and the GPU's throughput is the least of them:

1. **How long the cascade lasts in simulated time.** The rule is
   `wall <= 1.1 x (lattice_sim + rigid_sim)` and the rigid phase is almost
   free (0.03-2.7 s of wall for 1-6 s of Jolt), so the lattice phase may cost
   up to roughly 1.1 x total simulated time. At 12 m/s the 384-cell tile's
   cascade quiets after 114 ms and passes; the 800-cell tile is still breaking
   at the 200 ms cap and fails; every 1,536-cell glass scene is still breaking
   at 200 ms (6,900-8,400 failure rounds) and fails by 7x. Oak (3,022 broken,
   quiet at 11 ms) and iron (839 broken, quiet at 5 ms) at 1,536 cells pass.
2. **The substep floor.** One block costs 25.7 us per substep at 96 cells and
   30.7 at 192: a chain of 22-23 colour stages plus twelve phase barriers,
   with the GPU under 1% utilised. Eight slabs cost 142-182 us per substep
   from 1,536 to 6,400 cells: the boundary sweeps (even, then odd slabs, each
   31 colour stages) are 70-78 us at every size, the interior sweep 36-41 us.
3. **The substep shrinks with the cell.** Halving the cell doubles the
   substeps per millisecond and multiplies the bonds by twelve.

### 6.3 Where the time goes (us per substep, from the kernel's own phase clock)

| scene | us/step | sweep interior | sweep boundary | node strain (end) | criterion (end) | contact pass 1 | contact pass 2 | kick+classify | velocity | support | sphere+exit | start sample | capture |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bridge-96 (1 block) | 25.7 | 10.7 | 2.0 | 1.0 | 1.9 | 4.7 | 5.2 | 1.4 | 0.7 | 0.8 | 0.8 | 0.2 | 0.5 |
| bridge-192 (1 block) | 30.7 | 12.5 | 2.2 | 5.8 | 5.6 | 2.2 | 2.2 | 1.9 | 0.9 | 0.8 | 1.0 | 0.7 | 0.4 |
| bridge-800 (1 block) | 71.1 | 26.4 | 2.2 | 12.2 | 28.7 | 1.6 | 2.1 | 3.6 | 2.2 | 1.8 | 1.1 | 1.3 | 0.5 |
| bridge-1536 (1 block) | 155.1 | 55.8 | 2.9 | 29.4 | 65.1 | 5.5 | 6.6 | 5.7 | 4.3 | 2.7 | 1.2 | 3.0 | 0.5 |
| bridge-1536-blocks8 | 142.2 | 35.9 | 70.0 | 21.9 | 12.0 | 6.9 | 8.9 | 2.8 | 3.1 | 2.3 | 1.9 | 1.1 | 0.6 |
| bridge-6400-blocks20 | 177.5 | 36.5 | 72.5 | 26.0 | 20.3 | 16.5 | 21.5 | 2.8 | 2.7 | 2.4 | 2.0 | 4.8 | 0.6 |
| bridge-12288-blocks16 | 281.1 | 40.8 | 77.5 | 59.7 | 47.7 | 37.6 | 45.4 | 4.5 | 4.2 | 3.7 | 2.0 | 7.1 | 0.6 |
| bridge-192 GPU double | 153.4 | 70.8 | 2.5 | 17.5 | 45.3 | 12.0 | 10.3 | 6.7 | 4.1 | 4.6 | 3.1 | 3.0 | 0.6 |
| bridge-192 CPU float | 29.9 | 7.7 | 0 | 5.6 | 9.8 | 0.1 | 0.1 | 1.3 | 0.7 | 3.5 | 0 | 1.0 | 0 |

The phase clock is the leading thread's, including its wait at the barrier
that ends the phase, so the columns sum to slightly more than the wall figure.
Reading it:

- **On one block** the per-thread serial work grows with the scene: at 1,536
  cells each of 512 threads walks 37 bonds in the criterion phase and 3 nodes
  with 32 neighbours each in the strain phase, both latency-bound chains
  (65 + 29 us). More blocks fix that (12 + 22 us with eight) but add the
  boundary sweeps.
- **The boundary sweep is a constant ~70 us**: two half-idle passes of 31
  colour stages over 29 bonds per stage per block, plus two grid syncs. That
  is a barrier chain, not work; it does not shrink with more blocks and does
  not grow with the scene.
- **The interior sweep is ~36-41 us with slabs** for the same reason (31
  stages of about 50 bonds per block): a colour stage costs about 1.1-1.3 us
  whether it holds 30 or 500 bonds.
- **The serial contact pass** (one thread, node order, exactly the CPU's
  loop) grows with the number of ball contacts: 4 us per substep at 192
  cells, 83 us at 12,288 cells (212,410 impulse contacts over 90,267
  substeps), a third of the substep there. The prefilter never overflowed and
  the ball's centre moved at most 7e-10 to 6e-8 m within one pass.
- **GPU double** is 5x float: 71 us in the interior sweep and 46 us in the
  criterion on one block (consumer FP64 rate, double-size shared memory).
- **Launch chunking:** 1 substep per launch costs 130 us per substep (114-146
  over three measurements: launch, event sync and status download per
  launch); 100 per launch 31.8, 1,000 per launch 30.8, 10,000 per launch
  30.7. Upload/download add 2.5 ms (192 cells) to 10 ms (1,536 cells) to a
  run.
- **More slabs help only once per-block work dominates:** 1,536 cells go from
  155 (1 block) to 142 us (8 slabs); 6,400 cells from 248 us (8 slabs) to
  178 us (20 slabs).
- **Labelling** (connected components) runs once at the handoff on the CPU
  (2 ms at 192 cells, 16 ms at 1,536) and once per captured lattice frame for
  the recording's component ids; it is not on the per-substep path, and the
  lattice phase never needs it (`nbr_alive` slots are cleared as bonds fail,
  so the strain sums see the new topology without a search).
- **Transfer** is negligible; the whole run is one to thirty kernel launches.

### 6.4 The CPU backend

This lane's CPU backend runs the same phases on one thread and is bit-equal to
the kernel. At 192 cells it does 29.9 us per substep in float (57 M
bond-updates/s) and 25.1 in double (68 M): the GPU float kernel (30.7) is not
faster. `BrittleBondSolver` on the same tile, in the comparison of section
6.6, does 18.6-21.5 M bond-updates/s in double; the backend's 1.4-3.6x over it
comes from the cached inverse rest covariance (recomputed only for nodes whose
neighbour set changed), the padded k-major neighbour lists and the absence of
per-step allocation, not from any change of arithmetic. The 0.85 M the brief
quotes for the network lane is a different solver (`material-network-v2`,
implicit, transactional). CPU scaling rows (`cpu-384-float`, `cpu-800-float`,
`cpu-1536-float`, `cpu-1536-double`, `cpu-3072-float`) are in `summary.csv`'s
companion JSON files; see section 6.8.

### 6.5 Materials under identical conditions (12 m/s, 4 cm iron ball, bridge)

| scene | dt | substeps | lattice sim | us/step | broken | rounds | pieces | largest | removed | ratio | rule |
|---|---|---|---|---|---|---|---|---|---|---|---|
| glass 192 | 1.59 us | 21,898 | 34.8 ms | 30.7 | 1,534 | 645 | 59 | 1.32 kg | 37.1 J | 0.574 | met |
| oak 192 | 2.03 us | 20,760 | 42.1 ms | 35.2 | 775 | 255 | 29 | 0.41 kg | 44.9 J | 0.156 | met |
| iron 192 | 1.62 us | 12,326 | 20.0 ms | 33.4 | 0 | 0 | 1 | 12.09 kg | 0 | 0.581 | met |
| glass 1536 (8 slabs) | 0.67 us | 298,553 | 200 ms (cap) | 142.2 | 16,803 | 7,484 | 702 | 0.48 kg | 53.9 J | 7.045 | not met |
| oak 1536 (8 slabs) | 0.86 us | 24,521 | 21.0 ms | 176.1 | 3,022 | 837 | 92 | 0.95 kg | 51.2 J | 0.759 | met |
| iron 1536 (8 slabs) | 0.68 us | 21,717 | 14.9 ms | 140.2 | 839 | 232 | 15 | 11.83 kg | 43.8 J | 0.585 | met |

The materials differ by their declared stiffness, density and strength-derived
failure strains, nothing else: the oak substep is longer (lower stiffness over
density), iron at 192 cells does not break at all and at 1,536 cells loses a
contact patch. No material realism is claimed; these are the same reference
route the other lanes compare, and the non-convergence with cell size (glass
192 vs 1,536 at 8 m/s: 3 vs 672 pieces) applies to all three.

### 6.6 Accuracy against the CPU lattice

Flat 192-cell tile (the layout `BrittleBondSolver` can express), 12 m/s,
15,000 substeps = 23.8 ms, both lanes driven by one protocol (ball kick,
material substep, ball drift, ball/support contact). `docs/evidence/fast-gpu/compare-flat192-v12-*.json`.

| reference sweep order | lane precision | first failure step (bonds) ref / lane | set difference | broken ref / lane | pieces | largest (cells) | removed energy (J) | max dx | max dv | alive mismatches |
|---|---|---|---|---|---|---|---|---|---|---|
| schedule order | double | 219 (28) / 219 (28) | 0 | 988 / 988 | 9 / 9 | 173 / 173 | 110.726426 / 110.726426 | 9.5e-9 m | 5.5e-6 m/s | 0 |
| index order | double | 219 (28) / 219 (28) | 0 | 768 / 988 | 9 / 9 | 155 / 173 | 107.787 / 110.726 | 5.0e-2 m | 3.9 m/s | 402 |
| schedule order | float | 219 (28) / 219 (28) | 0 | 988 / 1,060 | 9 / 20 | 173 / 144 | 110.726 / 110.787 | 2.5e-2 m | 1.4 m/s | 282 |
| index order | float | 219 (28) / 219 (28) | 0 | 768 / 1,060 | 9 / 20 | 155 / 144 | 107.787 / 110.787 | 5.8e-2 m | 2.9 m/s | 404 |

- **Double, same sweep order: the same cascade.** Identical first failure,
  broken-bond history at every 300-step sample, pieces, largest piece and
  removed energy to nine digits; positions to 9.5 nm after 23.8 ms. The GPU
  float backend, being bit-equal to the CPU float backend, inherits the float
  row; the GPU double backend inherits the double row.
- **The sweep order changes the cascade** (the Gauss-Seidel ordering effect
  the design accepts): the same first 28 bonds at the same step, then 768 vs
  988 broken bonds, largest piece 155 vs 173 cells, 107.8 vs 110.7 J. Both
  references are `BrittleBondSolver`; only the bond storage order differs.
- **Float changes the cascade too**, after the first ~1.5 ms: 1,060 broken
  and 20 pieces against 988 and 9. Float is the same physics to float
  rounding; the cascade amplifies that rounding.
- The removed-energy ledger agrees to rounding in every row where the cascade
  is the same, and stays within 3% across sweep orders and precisions.

### 6.7 FMA and precision cost

| 192-cell bridge, GPU | us/step | broken | pieces |
|---|---|---|---|
| float, FMA on (previous build) | 31.4 | 1,536 | 62 |
| float, FMA off (this build) | 32.8 | 1,533 | 59 |
| double, FMA on | 147.5 | 1,562 | 82 |
| double, FMA off | 155.6 | 1,522 | 58 |

With FMA on, neither precision reproduces its CPU counterpart (1,536 vs
1,533; 1,562 vs 1,522); with it off both are bit-equal (section 5). (The
FMA-off rows here are from the interim build with the reach cap on every
plane; the final-build values are in section 6.2.)

### 6.8 CPU backend against the GPU at scale

The same scenes on this lane's CPU backend, one thread, float, measured in
isolation (`docs/evidence/fast-gpu/cpu-*.json`; the GPU columns repeat
section 6.2). The outcomes are identical to the GPU float rows by
construction (bit-equal backends).

| scene | cells | bonds | CPU us/step | CPU M bu/s | CPU ratio | GPU us/step (blocks) | GPU M bu/s | GPU ratio | GPU / CPU speed |
|---|---|---|---|---|---|---|---|---|---|
| bridge-192 | 192 | 1,704 | 29.7 | 57 | 0.512 met | 30.7 (1) | 55 | 0.574 met | 0.97x |
| bridge-384 | 384 | 3,592 | 98.6 | 36 | 1.288 not met | 52.0 (1) | 69 | 0.709 met | 1.9x |
| bridge-800 | 800 | 7,768 | 174.3 | 45 | 3.588 not met | 71.1 (1) | 109 | 1.503 not met | 2.5x |
| bridge-1536 | 1,536 | 18,852 | 465.4 | 41 | 22.86 not met | 142.2 (8) | 133 | 7.045 not met | 3.3x |
| bridge-3072 (30 ms) | 3,072 | 38,596 | 2,666 | 14 | 19.93 not met | 181.7 (8) | 212 | 1.563 not met | 14.7x |
| bridge-1536, double (30 ms) | 1,536 | 18,852 | 937.3 | 20 | 7.19 not met | 153.4-class | | | |

On the CPU the per-substep cost is the work (25 us of sweep, 25 of strain and
35 of criterion at 384 cells; 47, 34 and 63 at 800; 120, 117 and 164 at
1,536), so it grows with the bond count from the start, and at 3,072 cells it
jumps 3-4x per bond (663, 733 and 1,047 us): the backend's data layout is the
kernel's (padded k-major neighbour lists strided by the node count, bond
arrays in schedule order), which coalesces on a GPU and spills a single
core's cache once the lattice passes ~20k bonds. On one GPU block the same
phases are latency chains that grow more slowly until the per-thread
iteration count bites (section 6.3). The GPU's advantage therefore grows with
the scene (1.0x, 1.9x, 2.5x, 3.3x, 15x) and is what carries the rule from 192
to 384 cells; above that neither backend meets it, for the reason in
section 6.2.

## 7. Verdict on the rule

- **Met**, on the real engine's lattice physics and rigid world, for the
  192-cell glass tile struck at 8 m/s (0.20x) and 12 m/s (0.57x), on the GPU
  in float and on the CPU backend in float (0.50x) and double (0.40x); for
  glass at 12 m/s up to 384 cells (0.71x); for oak and iron at 192 and 1,536
  cells.
- **Not met** for glass at 800 cells (1.50x) or at 1,536 cells and above at
  10 mm cells (4.6-7.9x), and not met in double on the GPU even at 192 cells
  (2.3x: the FP64 kernel is 5x slower than float and 6x slower than the CPU's
  double).
- **Throughput**: 55 M bond-updates/s at the headline size (64x the network
  lane's 0.85 M, 2.7x `BrittleBondSolver`, 1.0x this lane's own CPU thread),
  69-109 M at 384-800 cells (1.9-2.5x the CPU thread), 133 M at 1,536 cells
  (3.3x), 212 M at 3,072 (15x, the CPU having spilled its cache), 616 M at 173k bonds
  (five times short of the ~3e9 the brief estimated as needed for a
  whole-step-on-GPU plate, and that estimate assumed 190,440 substeps where
  this scene needs 7,288-21,898).
- **The single biggest obstacle** is the barrier chain of the Gauss-Seidel
  sweep: >= max-degree (22-32) node-disjoint colour stages per sweep, each a
  barrier, three sweeps per iteration with slabs. It puts a floor of ~30 us
  (one block) to ~110 us (slabs) under every substep of 0.3-1.6 us of simulated
  time, whatever the bond count. Jacobi relaxation would remove the chain but
  is different physics (different convergence per iteration) and was not done.

## 8. What does not work, and limits

1. **Scale.** Above ~400 cells at 12 m/s, and at every 10 mm-cell glass scene,
   the rule fails because the cascade outlasts the wall budget at the substep
   floor above. More blocks do not help below ~20k bonds (1 -> 8 slabs: 155
   -> 142 us) and the slab count is capped by the tile thickness.
2. **GPU double** is 5x slower than GPU float and 6x slower than CPU double.
   The only rule-meeting double run is the CPU backend's.
3. **Float is not the double cascade** (section 6.6). The GPU's rule-meeting
   runs are float; their cascade differs from the reference's after ~1.5 ms
   while agreeing on the first failure, the ledger to 0.1% and the piece count
   within a factor two.
4. **The fracture outcome is not converged** with respect to sweep order
   (768 vs 988 broken), precision (988 vs 1,060) or cell size (3 vs 672 pieces
   for the same 8 m/s strike at 20 vs 10 mm cells); the first failure step and
   set are robust to the first two. This is the same non-convergence the
   implicit lane and the convergence study reported for this criterion.
5. **The serial ball contact pass** is faithful to the CPU's node-order
   dependence and therefore single-threaded: a third of the substep at 12,288
   cells.
6. **Pieces do not fracture again** after the handoff, and pieces do not
   collide with each other during the lattice phase (bonds only), so a crushed
   tile's fragments interpenetrate until Jolt separates them; the 200 ms cap
   then hands over hundreds of overlapping pieces, which is why the large
   scenes do not come to rest within 6 s. The 8 m/s 192-cell scene has no such
   overlap.
7. **Jolt capacity** overflowed at ~300 pieces with the default 8,192
   constraints; sizing from the piece count fixed the 6,400-cell row but the
   world's ceiling is 65,536 constraints.
8. **The finite-footprint reach cap** (section 2.8) is an extension the CPU
   lane does not have; it is inert on infinite planes by construction now,
   and measured inert on the flat comparison.
9. **Recording**: frames are thinned to a 48 MiB budget (27 of 27 kept at 192
   cells, 123 at 1,536 cells with bond lines for 51 lattice frames); the
   bond lines are drawn only for lattice-phase frames.
10. The GPU was shared with another process (24 GB, ~8% utilisation) and the
    last six rows of the first full sweep were perturbed by this checkpoint's
    own concurrent CPU runs; those rows were re-measured in isolation.
11. Not done: multi-GPU, cluster barriers (sm_90+ distributed shared memory)
    for cheaper inter-slab sync, a parallel contact pass, Jacobi or
    red-black variants, and any change to the criterion or its tolerances.

## 9. Playground

Registered in the owner's store (`C:\Users\henry\dev\banjo\build\playground-runs`,
server on port 8765) with `scripts/fast-gpu-install-playback.py`; the
playground loads a job directory on first request, no restart needed:

- `http://127.0.0.1:8765/?job=08678486c9aa43949b5a0ec7b00fafb8`
  - case 1: GPU float, 192-cell glass tile on two ledges, 8 m/s, 3 pieces,
    0.20x realtime, 27 frames (12 lattice frames with bond lines, then the
    pieces falling and settling on the ground and ledges);
  - case 2: same tile at 12 m/s, 59 pieces, 0.57x.
- `http://127.0.0.1:8765/?job=34c2b8108580425fbaefbd407ddf0279`
  - case 1: GPU float, 8 slabs, the 1,536-cell (10 mm cells) tile at 8 m/s:
    672 pieces, 7.3x realtime, rule not met; 123 frames, bond lines for the
    51 lattice frames; the pieces have not settled when the 6 s limit ends;
  - case 2: the CPU backend in double on the 8 m/s headline (the
    reference-faithful cascade: 276 broken bonds, 4 pieces, 0.72x measured
    under load, 0.41x-class when isolated).

Verified in a browser: the job opens on the 3D tab, the frame scrubber steps
through the cascade (frame 7/27 shows the crack bands, 24/27 the three
separated pieces), the Bonds toggle draws the lattice-phase bond lines, and
the case selector switches between the two recordings.

## 10. Next steps

1. Cut the barrier chain without changing the physics: process each colour
   stage with one warp when a stage holds <= 32 bonds (a `__syncwarp` is an
   order of magnitude cheaper than a block barrier), and merge each slab's
   interior and boundary stages into one even/odd pass (62 stages and two grid
   syncs per sweep instead of 93 and three). Both are permutations of the same
   Gauss-Seidel sweep and must be re-proven with suites 5-7.
2. Parallelise the ball contact pass by node-order-preserving segmented
   scans, or prove the CPU's order dependence is below rounding for the
   candidate sets seen here (the ball's centre moves < 6e-8 m within a pass).
3. Quantify the ordering and precision sensitivity as a convergence study
   (many seeds and sweep permutations) rather than one pair.
4. Piece-piece contact in the lattice phase, or an earlier handoff of pieces
   that have separated, so a crushed tile does not hand over overlapping
   fragments.
5. Only then revisit the rule above 400 cells; at the present floor it cannot
   be met for a cascade that lasts longer than ~40 ms at 20 mm cells or ~15 ms
   at 10 mm.
