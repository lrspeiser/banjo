# Algorithm 3 checkpoint: precomputed propagators, causal cones, and what the engine actually allows

Branch `agent/algo3-propagator-cones`, worktree
`C:\Users\henry\dev\banjo-agents\algo3-propagator`, local only, not on main.
Windows 11 Pro, MSVC 19.44 (Visual Studio 17 2022, x64, Release), 24 hardware
threads, NVIDIA GeForce RTX 5090 (driver 580.88) with CUDA 12.9.
September 8, 2026.

**Headline.** The lane is **exact** and **3.8x faster** than plain explicit
stepping on the Fracture lab's default plate: 500 cells in **0.55 s** of wall
time against the reference's 2.07 s (the report's own paired comparison, which
times both lanes back to back inside one run, says 3.63x), with `max |du| = 0`,
`max |dv| = 0`, identical damage, an identical broken-bond set and an identical
first-failure set and step. At 2,000 cells it is **7.2x** faster. But **none of that speed
comes from a propagator**, because the two premises Algorithm 3 rests on are
both false for this engine, and both were measured rather than assumed:

1. **One substep is not a linear map on x = (u, v).** With the plate on its
   ledges the best possible matrix gets one substep wrong by 99% to 1,860% of
   the answer, at every amplitude from 1e-9 m up. The support velocity response
   branches at zero normal speed and a resting plate sits exactly on that
   switch, so the map is not even differentiable there. Remove the supports and
   the map is smooth but still nonlinear: the error of the best matrix is
   `0.88 x (amplitude / cell size)`, which is 8.8e-5 at a 1 um displacement --
   eleven orders above rounding. The XPBD constraint `|x_b - x_a| - rest` is the
   source.
2. **The causal cone is the whole plate after ten substeps.** One node's
   displacement reaches **7.81 cells in one substep** and every one of the 500
   cells within ten, because a Gauss-Seidel sweep chains bond corrections
   through its 23 colour stages *inside* one substep, each stage carrying up to
   the 2-cell horizon. The lattice's fastest mode carries 0.159 cells per
   substep, so the exact numerical support spreads **49x faster** than any wave
   argument allows. There is no "outside the cone" at m = 50, let alone 1,000.

So the lane refuses to jump, at runtime, with the reason in its report, and
gets its speed from an exact multithreaded backend instead. Section 7 says what
would have to change for the propagator to become usable.

`physical_response_validated` stays false. Nothing here calibrates glass; the
lane reproduces the engine's answer exactly, it does not make that answer right.
The default scene's one-cell thickness is itself a degenerate case for the
criterion -- see `docs/why-the-plate-does-not-shatter.md`, which is the failure
criterion lane's finding, not this one's.

## 1. What exists on the branch

| Path | Role |
|---|---|
| `src/fastlattice/Propagator.{hpp,cpp}` | `SubstepMap` (one substep as a map on `x = (u, v)`, run by the engine's own backend), `buildPropagator` (dense P by applying it to every basis state), `propagatorPower` (repeated squaring of the affine map), `probeLinearity` / `checkPropagator` (is it affine at all?), `measureCone` (how far a perturbation reaches), the binary cache and `measureGemmSeconds` |
| `src/fastlattice/ParallelCpuLatticeBackend.cpp` | `makeParallelCpuLatticeBackend`: `CpuLatticeBackend`'s phases on a spin pool, bit identical to it |
| `tools/fracture_algo3.cpp` | `banjo_fracture_algo3`: the Fracture lab CLI contract, plus `--probe`, `--cone`, `--bench`, `--precompute` |
| `tests/fracture_algo3_tests.cpp` | `banjo_fracture_algo3_tests`, six suites (section 6) |
| `src/fastlattice/TileImpactScene.{hpp,cpp}` | `BackendKind::CpuParallel` and a `report_json` override for `writePlayback`, so the lane reuses the existing scene, Jolt handoff and recording writer |

Nothing in `LatticePhysics.hpp`, `fracture/BondFailure.{hpp,cpp}` or the
`BrittleBondSolver` route changed. No threshold, tolerance or material law
changed. The two edits inherited from the previous attempt (ADL lookup for
`sqrt`/`isfinite`, `sizeof(Real) >= 8`) are inert for `float` and `double` and
were kept so a differentiable `Real` can be substituted for the probe.

## 2. Method

### 2.1 The map is probed, never rederived

`SubstepMap::apply(x, y)` writes `x` into a pristine `LatticeState`, uploads it
to the engine's own `CpuLatticeBackend`, runs exactly one substep with the ball
contact disabled and the topology frozen, and reads `(u, v)` back. The map
depends on nothing but `x`: the gravity kick rewrites `u_prev`, the single
constraint iteration resets `accumulated_lambda`, `engaged` is cleared and
`approach` recorded inside the step, and everything `download()` writes is
restored from the pristine copy before each call. Test 1 asserts that its output
is bit for bit what a fresh backend produces, so the thing being measured is the
integrator that exists.

### 2.2 Affineness is a measurement, not an assumption

`probeLinearity` draws random displacement increments `a` and `b` of a given
amplitude and compares `g(a + b)` against `g(a) + g(b)`, where
`g(d) = f(x0 + d) - f(x0)`. That is the definition of affine. The displacement
and velocity blocks are reported apart because a substep carries `u` into `v`
through a factor `1/dt = 1e6`, so a single norm over both would say nothing
about the positions.

### 2.3 The cone is measured by its exact support

`measureCone` perturbs one node by 1e-9 m and steps two trajectories, counting a
node as touched when **any component of its (u, v) differs at all**. Not "differs
by more than a tolerance": exactness demands the strict support, because a
one-ulp difference in a strain sample flips a threshold comparison and from
there a whole cascade (the fast-GPU lane measured exactly that, section 2.4 of
`docs/fast-gpu-checkpoint.md`).

### 2.4 The runtime gate

Every non-reference run opens with nine substeps of `probeLinearity` at the
amplitude the scene reaches (1e-6 m by default) against a 1e-9 relative
tolerance. If the residual is above it, no matrix of any precision reproduces a
substep, so the lane sets `jumps.refused`, puts the measured residual and the
reason in the report, builds no matrix, and advances the plate by exact
explicit stepping. The gate costs 5-23 ms. It is not a fallback that hides a
failure; it is the lane declining to be wrong and saying why.

### 2.5 The exact parallel backend

`ParallelCpuLatticeBackend` is `CpuLatticeBackend` phase for phase with the
independent phases spread over a spin pool. Three rules keep it bit identical:

- **Colour stages are spread within a stage, never across stages.** The bonds of
  one colour share no node, so a stage's bonds read and write disjoint entries
  and may run in any order; the stage *order* is untouched, which is what keeps
  it the same Gauss-Seidel sweep. Splitting by slabs instead would change the
  sweep order and therefore the cascade, so it is not done.
- **The sphere contact pass stays serial.** Every node's impulse changes the ball
  the next node sees; node order is physics. The candidate lists are built by a
  serial scan of the per-node flags, which is the order the serial backend
  pushes them in.
- **Reductions are order-independent or replayed in index order.** The strain
  peaks combine by `max`, which is exact and commutative. The removed energy is
  summed by a serial pass over the bonds that broke, in bond index order, which
  is the order the serial backend adds them in; the thread slices are contiguous
  and ascending, so concatenating them in thread order *is* bond index order.

Two performance defects were found and fixed on the way, both measured:

- **False sharing on the per-thread strain peaks.** Every bond updated
  `peaks_[thread]`, and the peaks were packed back to back, so all sixteen
  threads wrote one cache line 2,777 times per substep. The speedup sat at
  **1.08x** until they were padded to a cache line each; it went to 1.75x
  immediately, and to 3.89x once the colour stages were spread too.
- **Oversubscription.** An empty pool dispatch costs 0.17-1.00 us from two to
  sixteen threads but **5.10 us at twenty-four**, where the calling thread
  competes with a spinning worker for its core. The default thread count is
  therefore capped at sixteen (3.89x), not taken from the machine (1.33x).

A spin pool is also sensitive to other load: one measurement taken immediately
after a parallel `cmake --build` read 92 s where two clean runs of the same
scene read 18.3 s and 19.8 s. Timings below were taken with the machine
otherwise idle.

## 3. The default scene

Glass plate 0.25 x 0.20 x 0.010 m at 10 mm cells: 25 x 20 x 1 = **500 cells**,
2,777 bonds, horizon 2. Substep 1.0102 us (0.5 x the lattice's own explicit
limit, 2.0203 us). Iron ball 60 mm diameter dropped 2.0 m (6.2642 m/s), two
rigid ledges, glass and iron from the catalog's strength-derived elastic
reference route. This is the Fracture lab's default, and the reference outcome
matches the brief's: **73 broken bonds, 2.1478 J removed**.

Where the reference's 1.95 s of lattice wall goes (its own phase clock,
`banjo_fast_lattice_run`, CPU double, one thread):

| phase | seconds | share |
|---|---:|---:|
| end sample + failure criterion, per bond | 1.018 | 52% |
| constraint sweep (XPBD), per bond | 0.692 | 35% |
| support projection, per node | 0.129 | 6.6% |
| gravity kick + contact classify | 0.052 | 2.7% |
| velocity update | 0.033 | 1.7% |
| node strain | 0.017 | 0.9% |
| sphere contact passes 1 and 2 | 0.007 | 0.3% |

The criterion and the sweep are 87% of it, and both are per-element phases that
parallelise without reordering anything. That is where the lane's speed comes
from.

## 4. The two refutations, measured

### 4.1 The substep is not an affine map

500-cell plate, double, displacement increments, `banjo_fracture_algo3 --probe`.
`additivity_rel` is `||g(a+b) - g(a) - g(b)||` over the worse of the two blocks,
divided by that block's image. Affine means "at rounding".

Plate at rest (t = 0), **with the ledges** -- the scene as it runs:

| amplitude | additivity_rel | homogeneity_rel | error of the best matrix P |
|---|---:|---:|---:|
| 1e-12 m | 1.02e-5 | 1.11e-5 | -- |
| 1e-10 m | **0.986** | 0.182 | -- |
| 1e-8 m | **1.94** | 2.00 | -- |
| 1e-6 m | **0.981** | 1.87e-4 | **1.86** |
| 1e-4 m | 9.89e-2 | 0.193 | **1.86** |

The residual does not shrink as the amplitude shrinks, which is the signature of
a kink rather than a curve. `applySupportVelocity` branches on
`normal_speed > target` and on `normal_speed < 0`, and the friction branch on
`speed <= static_friction * normal_delta`; a plate resting on a ledge sits at
`normal_speed = 0`, so any perturbation, however small, flips the branch for
some node. Inside the fracture window (step 4,000, `max |u| = 18.9 mm`,
73 bonds already gone) the matrix error is **0.97 to 16.4**.

Same plate, **support planes removed**, which isolates the bond solve:

| amplitude | additivity_rel | error of the best matrix P |
|---|---:|---:|
| 1e-12 m | 1.02e-5 (floor) | -- |
| 1e-10 m | 1.10e-7 | -- |
| 1e-8 m | 1.25e-6 | -- |
| 1e-6 m | 1.25e-4 | 8.78e-5 |
| 1e-4 m | 1.24e-2 | 8.68e-3 |

Now the residual scales one decade per decade of amplitude: a smooth quadratic,
exactly what `|x_b - x_a| - rest` and `delta / |delta|` produce. The best matrix
is wrong by `0.878 x (amplitude / 10 mm)`. The 1e-12 row is not nonlinearity: the
absolute residual there is 5.39e-18 m and it is *the same absolute value* at
1e-10, so it is the rounding floor of the double path's absolute-position
arithmetic (about 0.4 ulp of a 0.1 m coordinate), not a curvature.

**Conclusion.** A matrix propagator on this engine is wrong by 1e-4 relative at
best (bond solve only, micron amplitudes) and by 100% or more as actually
configured. The brief's tolerance was "~1e-12 relative". Nothing about
precision, cache size or the number of powers changes this: it is a property of
the map, not of the representation.

### 4.2 The causal cone is the whole plate

`banjo_fracture_algo3 --cone`. Cell 10 mm; the lattice's fastest mode has period
6.347 us, i.e. 1,575.6 m/s, i.e. **0.159 cells per substep**. A node counts as
touched when any component of its state differs at all.

Plate at rest:

| substeps | touched cells | share | reach (cells) | reach a wave allows |
|---:|---:|---:|---:|---:|
| 1 | 87 | 17.4% | **7.81** | 0.16 |
| 2 | 285 | 57.0% | 11.66 | 0.32 |
| 3 | 418 | 83.6% | 13.89 | 0.48 |
| 5 | 496 | 99.2% | 15.62 | 0.79 |
| 10 | **500** | **100%** | 15.62 (the plate's half-diagonal) | 1.59 |

Just after the first failure (step 700) the picture is the same: 5.39 cells in
one substep, 100% of the plate by ten.

**Conclusion.** The brief's rule -- "in m substeps a change can travel at most
the lattice's wave distance" -- is false for a Gauss-Seidel sweep, by a factor
of 49 in one substep. Information does not travel by the physical wave inside a
substep; it travels along the sweep, through 23 colour stages of 2-cell horizon.
For the causal-cone patch to save anything, the cone would have to be smaller
than the plate at m = 50; it is larger than the plate at m = 10. On a bigger
plate the cone would still swallow 46 cells of radius per substep, so the jump
length would have to fall below one substep to leave an outside.

## 5. Cost

### 5.1 Precompute, if it could be used (500 cells, n = 3,000)

`banjo_fracture_algo3 --precompute --cache build/fracture-cache`, sixteen
threads. Built and cached anyway, so the cost question has a measured answer.

| step | wall | bytes | note |
|---|---:|---:|---|
| P from the engine | **1.00 s** | 72.0 MB | 3,001 substeps, one per basis state plus the offset |
| P^50 from P | 5.00 s | 72.0 MB | 4.76 s of it in the multiplies |
| P^200 from P^50 | 2.75 s | 72.0 MB | |
| P^1000 from P^200 | 2.93 s | 72.0 MB | |
| **total, cold** | **11.7 s** | **288 MB** | 275 MiB on disk under `build/fracture-cache/` |
| total, warm | 0.30 s | 288 MB | all four loaded from the cache |

Raising each power from P separately would take about 30 multiplies; chaining
them (50 from P, 200 from 50, 1000 from 200) takes 12.

One dense 3,000 x 3,000 multiply, sixteen threads: **1.09 s in double**
(52 GFLOP/s) and **0.92 s in float**; float halves the storage to 36 MB per
power. Float would not rescue exactness -- section 4.1's error is 1e-4 to 1e0,
nine to thirteen orders above the float/double gap.

At 2,000 cells the state is n = 12,000, so a power is 1.15 GB in double and one
multiply is 3.5e12 flops, about 67 s at the measured rate; the four matrices
would be 4.6 GB and about 13 minutes. Not run: the gate refuses them at 500
cells for a reason that does not improve with size.

### 5.2 Per-rerun wall (the number the Fracture lab shows)

All rows: `banjo_fracture_algo3`, glass, 60 mm iron ball, two ledges, CPU
double, sixteen threads, machine idle. "Reference" is the same lane with
`--reference`: plain explicit stepping, one thread, the same lattice.

| scene | cells | bonds | substeps | lattice wall | **total wall** | simulated | ratio | window ratio | broken | pieces | removed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **default** 250x200x10 mm, 2 m drop | 500 | 2,777 | 13,626 | 0.54 s | **0.55 s** | 0.330 s | 1.65 | 38.9 | 73 | 1 | 2.148 J |
| *reference, same scene* | 500 | 2,777 | 13,626 | 2.06 s | *2.07 s* | 0.330 s | 6.27 | 149.9 | 73 | 1 | 2.148 J |
| thicker plate 250x200x**20** mm | 1,000 | 9,788 | 251,926 | 17.59 s | 18.10 s | 2.200 s | 8.23 | 88.0 | 6,869 | **207** | 1.786 J |
| higher drop, 4 m (8.86 m/s) | 500 | 2,777 | 45,447 | 1.88 s | 1.89 s | 0.771 s | 2.46 | 40.9 | 289 | 1 | 8.480 J |
| off-centre strike, 60/40 mm | 500 | 2,777 | 23,954 | 0.97 s | 0.97 s | 0.370 s | 2.63 | 39.9 | 120 | 1 | 3.539 J |
| **2,000 cells** 500x400x10 mm | 2,000 | 11,552 | 14,507 | 1.21 s | 1.23 s | 0.331 s | 3.70 | 82.9 | 119 | 1 | 3.539 J |

The 1.1x realtime rule is **not met** on any of these: the default plate is at
1.65x against a 1.1 limit, and the reference is at 6.27x. The lane closes most
but not all of that gap. The fracture window alone falls from 149.9x realtime to
38.9x.

(The off-centre and 2,000-cell rows both remove 3.5386 J from 120 and 119 bonds.
That is a coincidence of two similar contact-crush regions, not a shared code
path: the totals differ at the seventh figure and the per-bond energies differ by
0.8%.)

### 5.3 Where the speedup comes from, and where it stops

Lattice phase of the default scene, `banjo_fracture_algo3 --bench`:

| threads | wall | speedup | exact? |
|---:|---:|---:|---|
| 1 (serial) | 2.012 s | 1.00 | reference |
| 4 | 0.845 s | 2.38 | `max\|du\| = 0`, identical broken set |
| 8 | 0.595 s | 3.38 | same |
| 12 | 0.547 s | 3.68 | same |
| **16** | **0.517 s** | **3.89** | same |
| 24 | 1.512 s | 1.33 | same |

Empty pool dispatch: 0.17 us (2 threads), 0.31 (4), 0.59 (8), 0.83 (12),
1.00 (16), **5.10 (24)**. The 24-thread collapse is the calling thread sharing a
core with a spinner, not a correctness or a barrier-count problem.

The speedup rises with the scene because the parallel phases dominate more:
3.6x at 500 cells, 5.4x at 1,000, **7.2x at 2,000**. The ceiling is Amdahl on
the serial sphere contact pass plus the colour-stage count: 23 stages per
substep at about 120 bonds each means a stage carries ~0.14 us of work per
thread against a ~1 us dispatch, so the stages are spread at a thin margin and a
finer colour graph would help more than more threads.

### 5.4 GPU

Built and measured. NVIDIA GeForce RTX 5090, driver 580.88, CUDA 12.9. The
CUDA backend is the fast-GPU lane's, unchanged by this work; the propagator's
multiplies would be a cuBLAS call, and the gate refuses them before any is
issued, so what is measured is the lattice itself on the default scene.

| lane | substeps | lattice wall | us/substep | broken | removed | exact? |
|---|---:|---:|---:|---:|---:|---|
| plain explicit stepping, CPU double, 1 thread | 13,626 | 2.06 s | 151.4 | 73 | 2.1478 J | reference |
| **this lane, CPU double, 16 threads** | 13,626 | **0.54 s** | **39.6** | 73 | 2.1478 J | **yes, `max\|du\| = 0`** |
| CUDA, double | 13,626 | 2.72 s | 199.4 | 73 | 2.1478 J | yes (same cascade) |
| CUDA, float | 13,568 | 0.535 s | 39.5 | **77** | **2.2720 J** | **no** |

The only GPU mode that reproduces the reference cascade is double, and it is
**5.0x slower than this lane** and 1.3x slower than one CPU thread: a substep is
a chain of 23 colour stages separated by grid-wide barriers, and 500 cells does
not fill an RTX 5090 -- the same structural limit `docs/fast-gpu-checkpoint.md`
section 6.2 reports. The float path matches this lane's wall time to within 1%
but breaks 77 bonds instead of 73 and removes 4.4% more energy, which is the
known float/double cascade divergence (fast-GPU checkpoint section 2.5), so it
is not available to an exact lane. **The GPU does not help Algorithm 3 at this
size.**

## 6. Tests

`banjo_fracture_algo3_tests`, 0.4 s, all passing:

1. **`SubstepMap` is the engine's own substep, bit for bit** -- the probe measures
   the integrator that exists.
2. **The substep is not an affine map**: the supported residual is above 1e-3 at
   both 1e-6 m and 1e-9 m; the unsupported residual scales with the amplitude
   (a tenfold amplitude gives 3x-30x the residual, measured 10x); and the best
   matrix's one-substep error sits at the nonlinear floor, above 1e-6 and below
   1e-2. This pins section 4.1 as a regression test: if a future engine makes the
   substep affine, this test fails and the lane can be reopened.
3. **`P^m` equals m applications of P** to 1e-9 relative -- the repeated squaring
   is correct; what it is applied to is not linear.
4. **The causal cone** reaches more than ten times the fastest mode's distance in
   one substep and covers the whole plate within ten.
5. **The parallel backend is bit identical through a fracture cascade** (203
   bonds, 6,000 substeps): identical positions, velocities, damage, broken set,
   removed energy, failure rounds and first-failure step at 2, 4 and 8 threads.
6. **The cache round-trips** and refuses to hand out another scene's matrix.

Full suite: 87 of 87 pass (`ctest -C Release`, excluding the five suites the
brief excludes). `python scripts/check-source-registration.py` passes.

## 7. What would make Algorithm 3 work

Both refutations are about the *discretisation*, not about the idea, and both
have a named fix that this lane did not take because it would change the
engine's answer:

- **For linearity:** a propagator needs a linear integrator. Replacing the XPBD
  distance projection with a linearised spring (`C = r_hat . (u_b - u_a)`,
  direction fixed at the rest configuration) and the support response with a
  fixed active set makes the substep exactly affine, and then P is exact by
  construction. That is a different material law, and small-strain only; it
  would have to be proposed and validated as such, not slipped in under an
  optimisation.
- **For the cone:** a propagator needs a local stencil. Jacobi relaxation instead
  of Gauss-Seidel bounds one substep's reach at the 2-cell horizon, which would
  make a cone at m = 5 meaningful on a plate this size -- at the cost of a
  different (and slower-converging) sweep, again a physics change.
- **Failing both,** the honest use of a propagator here is as a *preconditioner
  or predictor* inside an iterative exact scheme, not as a substitute for
  stepping. That trades this lane's guarantee (exact) for a bound, and needs a
  residual test per jump whose cost is a full m-substep evaluation, which is
  what the jump was meant to avoid.

## 8. Exact commands

```sh
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 6
ctest --test-dir build/agent -C Release -E "banjo_network_skin_tests|banjo_network_runtime_tests|banjo_material_showcase_tests|banjo_network_adaptive_tests|banjo_contact_capacity_tests"
python scripts/check-source-registration.py

# CUDA build. The toolset must be named explicitly: the CMake on PATH here is
# the pip-installed one, which does not find the CUDA MSBuild integration by
# itself and fails with "No CUDA toolset found".
cmake -S . -B build/agent-cuda -G "Visual Studio 17 2022" -A x64   -T cuda="C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.9"   -DBANJO_BUILD_LAB=OFF -DBANJO_BUILD_CUDA=ON
cmake --build build/agent-cuda --config Release --parallel 6

# The same scene on the GPU (section 5.4)
build/agent-cuda/Release/banjo_fast_lattice_run.exe --material glass --ball-material iron   --tile 0.25 0.01 0.20 --cell 0.01 --ball-radius 0.03 --speed 6.264184 --layout bridge   --settle-s 2.0 --backend gpu --precision double --report gpu.json

# The default scene (the Fracture lab panel calls exactly this shape)
build/agent/Release/banjo_fracture_algo3.exe --plate 0.25 0.20 0.01 --cell 0.01 \
  --ball 0.06 --drop 2.0 --offset 0 0 --support ledges --duration 2.0 \
  --cache build/fracture-cache --output out.playback.json

# Plain explicit stepping instead
build/agent/Release/banjo_fracture_algo3.exe --plate 0.25 0.20 0.01 --cell 0.01 \
  --ball 0.06 --drop 2.0 --support ledges --duration 2.0 --reference \
  --cache build/fracture-cache --output ref.playback.json

# The two refutations
build/agent/Release/banjo_fracture_algo3.exe --probe --probe-steps 4000 --probe-samples 3
build/agent/Release/banjo_fracture_algo3.exe --cone --probe-steps 0

# Precompute cost, and the thread sweep
build/agent/Release/banjo_fracture_algo3.exe --precompute --cache build/fracture-cache
build/agent/Release/banjo_fracture_algo3.exe --bench

# Register recordings as playground jobs in the owner's store
python scripts/import-playback.py --runs C:/Users/henry/dev/banjo/build/playground-runs \
  --title "..." --name "..." out.playback.json
```

`--support clamped` is refused with a one-line reason and a non-zero exit: the
scene builder expresses the two-ledge bridge and the flat ground, and pinning
edge cells would need an inverse-mass path the lattice does not have. The
Fracture lab's default is `ledges`.

## 9. Owner playground jobs

Registered in `C:\Users\henry\dev\banjo\build\playground-runs` (runtime data;
the owner's checkout source and server were not touched). Recordings are kept
out of git.

| job | cases | URL |
|---|---|---|
| Algorithm 3, four scenes | default, thicker plate, higher drop, off-centre strike | http://127.0.0.1:8765/?job=c1afb90d517e46b2ace55f04496d927d |
| Algorithm 3 against plain stepping | reference (2.07 s), Algorithm 3 (0.55 s), same lattice | http://127.0.0.1:8765/?job=b8673d5344744dad8f88c25b7e7f3878 |
| Cost row, 2,000 cells | 500x400x10 mm, 11,552 bonds, 1.23 s | http://127.0.0.1:8765/?job=1e51f8bd9ae24ead8182ee8ad9b9ec40 |

Confirmed in a browser: the comparison job's reference case plays to its last
frame at 0.330431 s and comes to rest, and the Algorithm 3 case plays to the
same last frame at the same time -- which is the exactness result, watchable.

## 10. Status

**Implemented and validated**

- `SubstepMap`, `buildPropagator`, `propagatorPower`, the scene-keyed binary
  cache, `probeLinearity`, `checkPropagator`, `measureCone`. Tested.
- The refutations of sections 4.1 and 4.2, on the default scene, with regression
  tests.
- `ParallelCpuLatticeBackend`: bit identical to the serial backend through a
  fracture cascade at 2, 4, 8, 12, 16 and 24 threads, on four scenes and in the
  test suite.
- The lane CLI, its report contract, the recording, and the exactness comparison.

**Implemented, not validated as physics**

- Nothing in this lane claims a physical outcome. It reproduces
  `CpuLatticeBackend` exactly; whether that backend is right about glass is the
  criterion lane's question.

**Not done**

- The propagator jump, the causal-cone patch and the bisection are **not
  implemented as a runtime path**, because sections 4.1 and 4.2 show they cannot
  be exact here. The machinery to build and cache the powers exists and is
  measured; the gate refuses to use it.
- `--support clamped` is refused rather than implemented.
- The realtime rule (1.1x) is still not met: 1.65x on the default scene.

**Next**

- The colour count is the parallel ceiling: 23 stages per substep at ~120 bonds
  each. A coarser colouring (fewer, larger stages) would raise the speedup
  without touching the sweep semantics, since only the *stage order* is physics.
- The exactness comparison is capped at 20,000 substeps on long cascades so the
  Fracture lab's 60 s budget holds; the thicker-plate row's full 251,926-substep
  window has been compared only over its first 20,000. Comparing the whole window
  there takes about 100 s and has not been run to completion.
