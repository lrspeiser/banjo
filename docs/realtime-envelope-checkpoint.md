# Realtime envelope checkpoint

Measurement-only checkpoint. **No solver behaviour, tolerance, acceptance budget
or material constant was changed.** The only new code is a measurement driver,
`scripts/realtime-envelope-sweep.py`, which runs the shipped probes with their
existing flags and records what they print.

Banjo's stated purpose is near-realtime visualisation of material interaction.
Until now nobody had measured where realtime is actually reachable. This note
draws that envelope for both solver lanes on one chart, with one definition of
realtime ratio.

## Provenance

| Item | Value |
|---|---|
| Worktree | `C:/Users/henry/dev/banjo-agents/envelope` |
| Branch | `agent/realtime-envelope` |
| Base commit | `1d2d89fe124076fed2fee84a3e38bfbd4b770237` |
| CPU | Intel Core Ultra 9 285K, 24 cores / 24 logical, 3.7 GHz max |
| RAM | 95.7 GiB |
| OS | Windows 11 Pro build 26200 |
| Compiler | MSVC 19.44.35228.0 (VS 2022 BuildTools 14.44.35207), x64 Release |
| CMake | 4.1.2 |
| Configure | `cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF` |
| Build | `cmake --build build/agent --config Release --parallel 4` |

Both solver lanes are serial CPU code; the 24 cores do not help a single step.
`ConservativeStep` contains no threading at all, and `NetworkWorld::Impl`
constructs its `JoltWorld` with `rigid(0, ...)`, i.e. **zero Jolt worker
threads** — jobs run on the calling thread ("small connected networks avoid
thread-pool wakeup overhead", `src/platform/NetworkWorld.cpp:48`). Neither
number below is a parallel result, and neither has been measured with threads on.
The machine was not otherwise idle-guaranteed: other agent work runs on it. Every
cell below is repeated, and spread is reported rather than a single sample.

## Definition of realtime ratio

For both lanes:

```
realtime ratio = solver wall seconds / simulated seconds
```

`1.0` is exactly realtime; below 1 is faster than realtime; 500 means 500 wall
seconds to advance one simulated second. Rendering, package loading, JSON
reporting and process start-up are excluded from both lanes.

The brief for this work cited an existing figure of "961x slower than realtime
on a 108-cell glass panel" for the explicit lane. **That number could not be
traced to any measurement in this repository** — no `docs/*.md`, asset or script
contains it — so it is neither reproduced nor contradicted here. The explicit
numbers below are new, with their definition stated in full.

For the implicit lane the probe prints its own per-step wall time, so the ratio
is the summed per-step wall time over the simulated duration. For the explicit
lane the CLI prints no per-step timing, so per-step cost is obtained by
**differencing two runs** of the same package at two step counts; process
start-up, package load and report serialization cancel exactly.

Per-step solver work is not constant over a run in either lane, and the two
drift in opposite directions. In the implicit lane cost *rises* over the first
second as internal elastic modes develop, then plateaus. In the explicit lane
cost *falls* about 8x once Jolt puts the network to sleep. A measurement that
does not fix the simulated window will therefore flatter whichever lane it
suits. **Every cell in this note is measured over a stated simulated window**:
0.2 s from rest for the implicit headline sweep, 4 s from rest for the sustained
check, and simulated time 0.1 s to 0.5 s — while the scene is still moving — for
every explicit figure.

## What each lane is

**Implicit lane.** `src/physics/ConservativeStep.{hpp,cpp}`, driven by
`banjo_solver_probe`. Newton iteration on the whole nodal velocity system with a
restarted GMRES linear solve (40-vector Krylov basis, per-node 3x3 block-Jacobi
preconditioner). Geometry is the fixed 0.25 m sphere lattice from
`generateSphereLattice({.25, h, 2, 3}, ...)`; the voxel size `h` is the only
knob on node count. Free flight, zero gravity, zero contact, no damage, no
friction, no damping. A step is accepted only if the Newton/Krylov solve
converges *and* the independent energy, momentum and penetration audits pass; a
rejected step leaves the state untouched and the probe exits 2.

**Explicit lane.** `src/platform/NetworkWorld.cpp` via `banjo_platform_cli`.
Jolt rigid cells joined by face and diagonal distance springs, stepped at a
fixed admitted timestep in `[1/4800, 1/240]` s. There is no acceptance test:
every step is taken. Its correctness limit is instead reported as
`temporal_resolution`, computed by `assessSpringResolution` from
`omega_max^2 <= 2 max_i(sum_j k_ij / m_i)` with a 0.2 rad phase limit. A step
larger than `maximum_step_s` is under-resolved; the engine says so and steps
anyway.

The two lanes therefore fail differently, and this is the single most important
thing to hold on to when reading one chart of both. **The implicit lane refuses
a step it cannot resolve. The explicit lane takes it and reports that it was
not resolved.** A realtime ratio from the explicit lane is only meaningful
alongside its `required_substeps` count.

## Harness agreement with the existing record

Before sweeping anything, all five measurements in
[`elastic-newton-checkpoint.md`](elastic-newton-checkpoint.md) were reproduced
on this build. The physics matches to the last printed digit; wall times differ
by a few percent, which is the machine noise this note is careful about.

| Case | Recorded | Reproduced here | Agreement |
|---|---|---|---|
| Local, 81 nodes, 2 ms | Rejected, residual `2.48858e-6 m/s`, 256/0, 94.74 ms | Rejected, residual `2.48858218417e-6`, 256/0, 96.41 ms | residual identical; wall +1.8% |
| Newton, 81 nodes, five 2 ms steps | Accepted, 3/62, 0.495–0.553 ms | Accepted, 3/62, 0.488–0.555 ms | identical iterations |
| Newton, 1,285 nodes, 100 x 2 ms | Accepted, 3–4 / 426–555, 49.87–69.02 ms, median 60.34, p95 66.83 | Accepted, 3–4 / 426–555, 48.26–69.65 ms, median 59.24, p95 67.16 | iterations identical; median −1.8% |
| Newton, 1,285 nodes, 120 x 1/240 s | Accepted, 4 / 296–979, 39.35–114.56 ms, median 54.22, p95 109.93 | Accepted, 4 / 296–979, 37.67–113.99 ms, median 52.15, p95 106.38 | iterations identical; median −3.8% |
| Newton, 1,285 nodes, 1/60 s | Rejected, residual `4.37003e-9`, 19 / 6,688, 894.03 ms | Rejected, residual `4.3700265637e-9`, 19 / 6,688, 889.43 ms | residual and iterations identical; wall −0.5% |

Conserved-quantity totals match exactly: for the 100 x 2 ms run,
delta-P `5.42298e-14`, delta-L `1.41010e-10`, delta-E `-5.27692e-10`; for the
120 x 1/240 s run, `3.57043e-14`, `2.43465e-8`, `-9.10937e-8`. **No
disagreement with the record was found.**

Commands, run from the worktree root:

```powershell
.\build\agent\Release\banjo_solver_probe.exe --solver local --voxel-size 0.12 --dt 0.002
.\build\agent\Release\banjo_solver_probe.exe --voxel-size 0.12 --dt 0.002 --steps 5
.\build\agent\Release\banjo_solver_probe.exe --voxel-size 0.04 --dt 0.002 --steps 100
.\build\agent\Release\banjo_solver_probe.exe --voxel-size 0.04 --dt 0.004166666666666667 --steps 120
.\build\agent\Release\banjo_solver_probe.exe --voxel-size 0.04 --dt 0.01666666666666667 --steps 5
```

## Materials

The three presets required by `AGENTS.md`, from `makeReferenceMaterial`:

| Preset | Density kg/m^3 | Young's modulus | Poisson | sqrt(E/rho) m/s |
|---|---:|---:|---:|---:|
| glass (soda lime) | 2500 | 70 GPa | 0.22 | 5292 |
| oak | 700 | 12 GPa | 0.35 | 4141 |
| iron | 7870 | 211 GPa | 0.29 | 5178 |

The explicit lane reads its material constants from the package instead; the
sweeps below use the values already shipped in
`assets/material-showcase/01-clamped-panels-02mps.json`, copied verbatim.

The implicit-lane reference compiles only density, modulus and Poisson ratio
into `bond_compliance`; strength, fracture energy and damping are explicitly
disabled in `compileElasticLatticeReference`. So across these three presets the
implicit lane sees one axis of variation: bond stiffness over nodal mass. Their
bar-wave speeds fall within 28% of each other, and the cost results below
reflect that.

## Implicit lane: realtime ratio over 0.2 s of simulated time

Every cell advances 0.2 s of simulated time from the same rigid initial state
(translation `(0.3,-0.1,0.2) m/s`, spin `(1,-2,3) rad/s`, radius 0.25 m sphere,
horizon 2, occupancy sampling 3, zero gravity/contact/damage). The number is
**solver wall seconds per simulated second**; `1.000` is exactly realtime.
`rejected` means at least one step failed the existing convergence or
energy/momentum/penetration audits, so the configuration does not run at any
speed and no time is reported for it. Two repeats per cell; the median across
repeats is shown, and the CSV carries the min and max as well. Raw per-step
data, spreads and iteration counts:
[`evidence/envelope-implicit-sustained.csv`](evidence/envelope-implicit-sustained.csv).

```powershell
python scripts/realtime-envelope-sweep.py sustained --sim 0.2 --repeats 2 --budget 300
```

### glass

| Voxel h (m) | Nodes | Bonds | dt=1/60 | dt=1/120 | dt=1/240 | dt=1/480 | dt=1/960 | Best |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.2 | 27 | 185 | 0.014 | 0.019 | 0.020 | 0.049 | 0.094 | 0.014 @ 1/60 |
| 0.12 | 81 | 773 | 0.059 | 0.102 | 0.137 | 0.285 | 0.461 | 0.059 @ 1/60 |
| 0.1 | 117 | 1181 | 0.152 | 0.187 | 0.223 | 0.457 | 1.036 | 0.152 @ 1/60 |
| 0.08 | 179 | 1957 | 0.179 | 0.309 | 0.387 | 0.818 | 1.133 | 0.179 @ 1/60 |
| 0.075 | 251 | 2881 | 0.405 | 0.529 | 0.628 | 1.271 | 2.816 | 0.405 @ 1/60 |
| 0.07 | 275 | 3193 | rejected | 0.587 | 0.725 | 1.538 | 3.152 | 0.587 @ 1/120 |
| 0.065 | 365 | 4321 | rejected | 0.827 | 1.027 | 2.103 | 4.796 | 0.827 @ 1/120 |
| 0.06 | 461 | 5665 | rejected | 1.469 | 1.642 | 2.960 | 6.729 | 1.469 @ 1/120 |
| 0.055 | 509 | 6277 | rejected | 1.825 | 1.769 | 3.683 | 6.938 | 1.769 @ 1/240 |
| 0.05 | 739 | 9477 | rejected | 4.822 | 3.865 | 7.489 | 11.2 | 3.865 @ 1/240 |
| 0.045 | 919 | 11973 | rejected | 7.838 | 6.991 | 12.9 | 18.9 | 6.991 @ 1/240 |
| 0.04 | 1285 | 17097 | rejected | rejected | 12.7 | 28.0 | 33.4 | 12.650 @ 1/240 |

### oak

| Voxel h (m) | Nodes | Bonds | dt=1/60 | dt=1/120 | dt=1/240 | dt=1/480 | dt=1/960 | Best |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.2 | 27 | 185 | 0.012 | 0.020 | 0.020 | 0.041 | 0.081 | 0.012 @ 1/60 |
| 0.12 | 81 | 773 | 0.061 | 0.104 | 0.133 | 0.298 | 0.389 | 0.061 @ 1/60 |
| 0.1 | 117 | 1181 | 0.099 | 0.200 | 0.232 | 0.450 | 1.005 | 0.099 @ 1/60 |
| 0.08 | 179 | 1957 | 0.178 | 0.308 | 0.370 | 0.889 | 0.926 | 0.178 @ 1/60 |
| 0.075 | 251 | 2881 | 0.279 | 0.491 | 0.633 | 1.274 | 2.945 | 0.279 @ 1/60 |
| 0.07 | 275 | 3193 | 0.405 | 0.582 | 0.686 | 1.551 | 3.278 | 0.405 @ 1/60 |
| 0.065 | 365 | 4321 | rejected | 0.807 | 1.002 | 2.177 | 4.863 | 0.807 @ 1/120 |
| 0.06 | 461 | 5665 | rejected | 1.141 | 1.443 | 2.934 | 6.949 | 1.141 @ 1/120 |
| 0.055 | 509 | 6277 | rejected | 1.747 | 1.681 | 3.516 | 6.929 | 1.681 @ 1/240 |
| 0.05 | 739 | 9477 | rejected | 4.368 | 3.719 | 5.902 | 11.1 | 3.719 @ 1/240 |
| 0.045 | 919 | 11973 | rejected | 6.915 | 7.370 | 11.3 | 15.3 | 6.915 @ 1/120 |
| 0.04 | 1285 | 17097 | rejected | 7.754 | 11.3 | 30.0 | 30.2 | 7.754 @ 1/120 |

### iron

| Voxel h (m) | Nodes | Bonds | dt=1/60 | dt=1/120 | dt=1/240 | dt=1/480 | dt=1/960 | Best |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.2 | 27 | 185 | 0.015 | 0.018 | 0.019 | 0.052 | 0.096 | 0.015 @ 1/60 |
| 0.12 | 81 | 773 | 0.059 | 0.103 | 0.133 | 0.306 | 0.462 | 0.059 @ 1/60 |
| 0.1 | 117 | 1181 | 0.151 | 0.188 | 0.222 | 0.490 | 0.972 | 0.151 @ 1/60 |
| 0.08 | 179 | 1957 | 0.183 | 0.294 | 0.369 | 0.808 | 1.133 | 0.183 @ 1/60 |
| 0.075 | 251 | 2881 | 0.390 | 0.492 | 0.632 | 1.252 | 2.762 | 0.390 @ 1/60 |
| 0.07 | 275 | 3193 | rejected | 0.567 | 0.694 | 1.495 | 3.202 | 0.567 @ 1/120 |
| 0.065 | 365 | 4321 | rejected | 0.809 | 1.006 | 2.063 | 4.701 | 0.809 @ 1/120 |
| 0.06 | 461 | 5665 | rejected | 1.458 | 1.578 | 2.948 | 6.412 | 1.458 @ 1/120 |
| 0.055 | 509 | 6277 | rejected | 1.754 | 1.704 | 3.554 | 6.888 | 1.704 @ 1/240 |
| 0.05 | 739 | 9477 | rejected | 4.744 | 3.908 | 7.623 | 11.2 | 3.908 @ 1/240 |
| 0.045 | 919 | 11973 | rejected | 8.272 | 7.403 | 12.5 | 18.7 | 7.403 @ 1/240 |
| 0.04 | 1285 | 17097 | rejected | rejected | 13.4 | 29.1 | 32.5 | 13.390 @ 1/240 |


### Sustained cost: the 0.2 s window is optimistic

Per-step cost rises during the first half-second of simulated time as internal
modes develop, then plateaus. To check that the 0.2 s headline is not measuring
only the cheap transient, the configurations near the 1x line were re-run for
**4 s of simulated time** (480 steps at 1/120 s), with the ratio reported for
each successive 0.5 s block:
[`evidence/envelope-implicit-duration.csv`](evidence/envelope-implicit-duration.csv).

```powershell
python scripts/realtime-envelope-sweep.py duration --budget 900
```

Glass at 365 nodes, dt = 1/120 s, block by block: 0.882, 1.017, 1.101, 1.101,
1.055, 1.055, 1.002, 0.998. The cost rises about 20% over the first second and
then **plateaus** — it does not keep climbing. Krylov iterations per step move
from 188–226 in the first block to 220–255 in the last. The same shape appears
at 461 and 1,285 nodes.

So the 0.2 s ratios above understate sustained cost by roughly 15–25%, and the
sustained numbers are the ones to quote.

### Where 1x sits for the implicit lane

Measured over 4 s of simulated time. The 365-node row was run twice and both
values are given, to show the machine's run-to-run spread; the other rows are
single 4 s runs. The 275-node row uses 1/120 s for all three materials so the
comparison is like for like, although oak also accepts 1/60 s at that size and
reaches about 0.41 there.

| Nodes / bonds | Voxel h | dt | glass | oak | iron |
|---:|---:|---:|---:|---:|---:|
| 179 / 1,957 | 0.08 m | 1/60 s | 0.184 | 0.184 | 0.183 |
| 251 / 2,881 | 0.075 m | 1/60 s | 0.409 | 0.284 | 0.395 |
| 275 / 3,193 | 0.07 m | 1/120 s | 0.581 | 0.589 | 0.586 |
| **365 / 4,321** | **0.065 m** | **1/120 s** | **0.997 and 1.026** | **0.816 and 0.857** | **1.005 and 1.034** |
| 461 / 5,665 | 0.06 m | 1/120 s | 1.653 | — | — |
| 1,285 / 17,097 | 0.04 m | 1/240 s | 14.53 | — | — |

**The 1x line for the implicit lane on this machine is 365 nodes and 4,321
bonds, at a 1/120 s step.** Glass lands at 0.997–1.026 and iron at 1.005–1.034
— on the line to within the ~3% run-to-run spread — and oak sits comfortably
under at 0.816–0.857. The next lattice up, 461 nodes, is 1.65x and cannot be
rescued by any timestep in the sweep — its best 0.2 s ratio across all five
timesteps is 1.14 (oak) to 1.47 (glass). The largest configuration measured
*comfortably* under 1x, with margin against machine noise, is 275 nodes at
0.58–0.59.

Cost per simulated second differs between the three materials by less than 3%
at matched node count and timestep. **Material choice is not a performance lever
in this lane.** Its one real effect is on which timesteps the solver will accept.

### The three cost drivers, measured

**1. Node count, at an exponent near 1.6.** Least-squares fit of
log(wall per simulated second) against log(nodes) at dt = 1/240 s over the
twelve lattices above:

| Material | Fitted exponent |
|---|---:|
| glass | N^1.615 |
| oak | N^1.595 |
| iron | N^1.631 |

Where that exponent comes from is visible in the probe's own counters. Krylov
iterations per step grow as **N^0.593** (glass, dt = 1/240 s: 49 iterations at
27 nodes, 110 at 365, 555 at 1,285), and each iteration costs O(bonds), with
bond count growing as **N^1.160** — 6.9 bonds per node at 27 nodes rising to
13.3 at 1,285. Those two exponents sum to 1.75 against a measured 1.615, so they
account for the direction and most of the magnitude but not all of it; the
residual is per-step work that does not scale with their product. **This is
still the single biggest cost driver: doubling the node count costs about three
times the wall time, not two.**

**2. A large timestep costs far more than it saves.** Going from dt = 1/60 s to
dt = 1/30 s halves the number of steps but multiplies the work in each one by
far more than two, because the Newton system becomes much harder. Measured on
the 179-node lattice (12 steps, 3 repeats, from
[`evidence/envelope-implicit-sweep.csv`](evidence/envelope-implicit-sweep.csv);
both steps were accepted in every case, so this is not a convergence failure):

| 179 nodes | dt = 1/60 s | dt = 1/30 s | Change |
|---|---:|---:|---|
| glass, Newton iterations per step | 5 | 52 | 10.4x |
| glass, Krylov iterations per step | 180–181 | 6,376–6,459 | 35x |
| glass, wall per step | 2.83 ms | 104.60 ms | **37x** |
| glass, realtime ratio | 0.170 | 3.138 | 18.5x worse |
| oak, Newton / Krylov per step | 5 / 177–180 | 15 / 1,267–1,285 | 3x / 7.1x |
| oak, wall per step | 2.82 ms | 20.27 ms | 7.2x |
| oak, realtime ratio | 0.169 | 0.608 | 3.6x worse |
| iron, Newton / Krylov per step | 5 / 180–181 | 51 / 6,239–6,321 | 10.2x / 35x |
| iron, wall per step | 2.81 ms | 103.81 ms | 37x |
| iron, realtime ratio | 0.169 | 3.114 | 18.5x worse |

This is also the one place where material identity matters, and it matters a
lot: oak's softer lattice needs 15 Newton iterations where glass and iron need
51–52, so doubling the step costs oak 7x and the stiff materials 37x.

So every configuration has an optimal timestep, and it is not the largest one
the solver will accept. Below the optimum the ratio rises again, because
per-step cost approaches a floor (residual assembly and preconditioner work)
while the step count keeps growing: glass at 27 nodes costs 0.014 at 1/60 s but
0.094 at 1/960 s, for identical physics. **For glass and iron the optimum in the
measured band is 1/60 s up to 251 nodes, 1/120 s from 275 to 461 nodes, and
1/240 s from 509 nodes up.** Oak's is shifted one notch coarser at both ends: it
still prefers 1/60 s at 275 nodes and returns to 1/120 s at 919 and 1,285,
because it accepts larger steps than the stiff materials.

**3. Timestep acceptance, which is what actually caps the big lattices.** See
the next section: the largest step the solver will accept shrinks as the lattice
grows, and it is that shrinking — not raw per-step cost — that keeps the
1,285-node glass lattice off 1/60 s. Its measured boundary is 7.046 ms, so the
coarsest step in the sweep it can use is 1/240 s: 4x more steps per simulated
second than 1/60 s would have needed, before any solver work is counted.

## Implicit lane: where it stops converging

The largest timestep each lattice accepts, found by geometric bisection between
1/3,840 s and 1/30 s (the 365-node row was bisected separately between 1/240 s
and 1/60 s, because it is the 1x lattice). The acceptance criterion is **all of
the first 8 steps accepted** from the rigid initial state; the bracket is closed to about 4% on a
log scale. `> 1/30 s` means the lattice accepted the top of the search range,
which was capped at one 30 Hz frame because no visualiser needs a coarser step.
Raw brackets and iteration counts:
[`evidence/envelope-timestep-boundary.csv`](evidence/envelope-timestep-boundary.csv).

```powershell
python scripts/realtime-envelope-sweep.py dtboundary --steps 8 --budget 300
```

| Voxel h | Nodes | glass | oak | iron |
|---:|---:|---:|---:|---:|
| 0.25 | 19 | > 1/30 s | > 1/30 s | > 1/30 s |
| 0.20 | 27 | > 1/30 s | > 1/30 s | > 1/30 s |
| 0.12 | 81 | > 1/30 s | > 1/30 s | > 1/30 s |
| 0.10 | 117 | 18.88 ms (53 Hz) | 23.70 ms (42 Hz) | 19.61 ms (51 Hz) |
| 0.08 | 179 | > 1/30 s | > 1/30 s | > 1/30 s |
| 0.065 | 365 | 12.31 ms (81 Hz) | 15.62 ms (64 Hz) | 12.31 ms (81 Hz) |
| 0.06 | 461 | 11.53 ms (87 Hz) | 13.94 ms (72 Hz) | 11.98 ms (83 Hz) |
| 0.05 | 739 | 8.845 ms (113 Hz) | 10.69 ms (94 Hz) | 9.187 ms (109 Hz) |
| 0.04 | 1,285 | 7.046 ms (142 Hz) | 9.541 ms (105 Hz) | 7.046 ms (142 Hz) |
| 0.035 | 1,863 | 6.054 ms (165 Hz) | 7.600 ms (132 Hz) | 6.054 ms (165 Hz) |
| 0.03 | 2,945 | 5.009 ms (200 Hz) | 6.288 ms (159 Hz) | 5.009 ms (200 Hz) |

Three things fall out of this table.

**The boundary shrinks roughly as N^-0.4.** From 461 to 2,945 nodes (6.4x) the
largest accepted glass step falls from 11.53 to 5.01 ms (2.3x). That is what
forces the big lattices onto small steps and multiplies their cost.

**It is not monotonic in node count, and the exception is reproducible.** The
117-node lattice (h = 0.10 m) rejects 1/30 s while both the coarser 81-node and
the finer 179-node lattices accept it — in all three materials, and in a
separate 12-step sweep as well (glass rejected at 117 nodes after 26 Newton
iterations, accepted at 81 and at 179). The bound is set by the worst-conditioned
node in that particular occupancy sampling, not by a smooth function of
resolution. **Refining a mesh can increase the step the solver accepts.** Anyone
tuning a scene should measure its own boundary rather than interpolating this
table.

**Oak accepts 21–35% larger steps than glass and iron.** At 1,285 nodes: oak
9.54 ms against 7.05 ms for both stiff materials. Glass and iron, meanwhile, are
identical to the printed digits at 1,285 nodes and above and within 4% at 461
and 739, despite iron's modulus being 3x glass's — because what sets the bound
is stiffness over nodal mass, and iron's density is 3.1x glass's, which nearly
cancels it.

This also answers the open question in the record. The 1/60 s rejection on the
full 1,285-node lattice is not a cliff at 1/60 s: the boundary for glass is
7.046 ms, i.e. **1/142 s**, with the first rejected step in the bracket at
7.318 ms. 1/240 s was accepted because it sits comfortably inside that.

## Explicit lane

Same definition of realtime ratio. Cost per step is obtained by differencing two
`banjo_platform_cli --run` invocations of the same package, over a **matched
simulated window of 0.1 s to 0.5 s** in every case. Panels are single clamped
0.24 x 0.36 x 0.04 m boxes with `pin_boundary`, no ground, and the material
constants copied verbatim from
`assets/material-showcase/01-clamped-panels-02mps.json`.

```powershell
python scripts/realtime-envelope-sweep.py explicit --repeats 3 --budget 600
python scripts/realtime-envelope-sweep.py explicit_dt --repeats 3 --budget 600
```

### Sleeping bodies make a naive measurement look 8x better than it is

At dt = 1/480 s, one 108-cell glass panel:

| Simulated window | Wall per step | Realtime ratio as run |
|---|---:|---:|
| 0.1 – 0.5 s (panel still ringing) | 0.3228 ms | 0.155 |
| 0.5 – 1.0 s | 0.0402 ms | 0.019 |
| 1.0 – 2.0 s | 0.0447 ms | 0.021 |

Jolt puts the cells to sleep once the clamped panel goes quiet, and per-step
cost drops about 8x. A measurement spanning steps 40–1,040 blends the two and
reports 0.1019 ms/step — a true number for *that* scene, and a misleading one
for an active scene. **Every explicit figure below uses the awake 0.1–0.5 s
window.** This matters when putting the two lanes on one chart: the
implicit-lane probe is in free flight with a spin and never goes quiet, so it
gets no equivalent discount.

### Per-step cost does not depend on the timestep

Glass, 108 cells, matched 0.1–0.5 s window, three repeats:

| dt | Wall per step | Spread | Ratio as run | `required_substeps` |
|---:|---:|---:|---:|---:|
| 1/240 s | 0.3043 ms | 0.019 | 0.073 | 6,291 |
| 1/480 s | 0.3228 ms | 0.031 | 0.155 | 3,146 |
| 1/960 s | 0.3333 ms | 0.015 | 0.320 | 1,573 |
| 1/1920 s | 0.3382 ms | 0.014 | 0.649 | 787 |
| 1/4800 s | 0.3327 ms | 0.010 | 1.597 | 315 |

Over a 20x range of timestep the per-step cost moves by 11%, about the size of
the spread. The lane's fixed 24 velocity iterations over a fixed constraint set
cost the same whatever `dt` is. **The realtime ratio in this lane is therefore
very close to proportional to 1/dt**, which is what makes the resolved-step
figure below a defensible extrapolation rather than a guess.

### Cell-count ladder, at the shipped 1/480 s step

Realtime ratio as run, awake window, three repeats:

| Cells | Links | glass | oak | iron |
|---:|---:|---:|---:|---:|
| 48 (4x6x2) | 236 | 0.078 | not admitted | 0.080 |
| 70 (5x7x2) | 363 | 0.110 | 0.121 | 0.111 |
| 108 (6x9x2) | 586 | 0.155 | 0.171 | 0.158 |
| 288 (8x12x3) | 1,858 | **0.904** | **0.868** | 1.119 |
| 600 (10x15x4) | 4,208 | 2.404 | 2.432 | 2.823 |
| 800 (10x16x5) | 5,812 | 4.373 | 4.304 | 4.224 |

**At the step it actually ships with, the explicit lane reaches 1x realtime at
about 288 cells** — 0.90 for glass, 0.87 for oak, 1.12 for iron. Cost scales as
roughly N^1.43 across this ladder (48 to 800 cells is 16.7x; cost is 55.9x).
Materials again differ by only a few percent.

Cells that could not be run are left empty rather than estimated. Oak at 48
cells is refused by the admission check (`network cohesive law requires df
greater than d0` — at that cell size oak's elastic opening exceeds its final
opening), and the 3x4x1 and 12x18x4 resolutions are outside the package limit
of 2..16 per axis (`src/platform/NetworkWorld.cpp:188`), which with the 800
candidate-cell and 1,024 world-cell budgets is what caps this lane's scene size.

### Shipped fixtures, for grounding

| Package | Cells | Links | Wall per step (blended, steps 40–1,040) | Ratio as run |
|---|---:|---:|---:|---:|
| `material-showcase/01-clamped-panels-02mps.json` | 327 | 1,758 | 0.3942 ms | 0.189 |
| `runtime-v2/03-axe-oak-panel.json` | 217 | 1,240 | 1.4068 ms | 0.675 |
| `runtime-v2/08-free-flight.json` | 108 | 504 | 0.3495 ms | 0.168 |

These use the blended window, because the shipped packages have their own
transient structure. They are included for continuity with
[`network-runtime-checkpoint.md`](network-runtime-checkpoint.md), not as
awake-scene numbers.

### The number that actually matters for the explicit lane

Every configuration above is stepped far above the lattice's own resolution
bound. `NetworkWorld` says so itself: `temporal_resolution.resolved` is `false`
in every single run, and `required_substeps` runs from 315 to 7,353. Using the
measured fact that per-step cost is independent of `dt`, the realtime ratio at
the **resolved** step is per-step cost divided by `maximum_step_s`:

| Package | Cells | `maximum_step_s` | Ratio as run at 1/480 s | Ratio at the resolved step |
|---|---:|---:|---:|---:|
| glass panel | 48 | 8.861e-7 s | 0.078 | **184x** |
| glass panel | 108 | 6.623e-7 s | 0.155 | **487x** |
| glass panel | 288 | 3.974e-7 s | 0.904 | **4,740x** |
| glass panel | 600 | 3.114e-7 s | 2.404 | **16,083x** |
| glass panel | 800 | 2.833e-7 s | 4.373 | **32,154x** |
| oak panel | 108 | 1.650e-6 s | 0.171 | **216x** |
| oak panel | 288 | 1.054e-6 s | 0.868 | **1,716x** |
| oak panel | 600 | 8.218e-7 s | 2.432 | **6,165x** |
| iron panel | 108 | 6.769e-7 s | 0.158 | **487x** |
| iron panel | 288 | 4.061e-7 s | 1.119 | **5,739x** |

The last column is arithmetic on two measured quantities: the measured per-step
cost, which is constant in `dt` across the 20x range tested, and the engine's
own reported `maximum_step_s`. It extrapolates past the smallest admitted step
(1/4800 s), and is stated as an extrapolation. It is also a slight *under*
estimate of cost, since the trend in the timestep table is marginally upward as
`dt` falls.

**The explicit lane does not reach 1x realtime at a resolved step at any size
measured.** The smallest panel in this sweep, 48 cells, is still 184x off, and
shrinking the scene barely helps: a 16.7x cut in cell count (800 to 48) buys
only 3.1x in `maximum_step_s`, because that bound is set by the stiffness and
mass of a *single cell*, not by how many there are.

## Both lanes on one chart

Realtime ratio against element count, with the same definition of realtime ratio
and a stated simulated window for each. Glass in both lanes.

| Elements | Implicit lane (nodes, best accepted dt, 4 s window) | Explicit lane as run (cells, 1/480 s, awake window) | Explicit lane at its resolved step |
|---:|---:|---:|---:|
| 48 | — | 0.078 | 184x |
| 108 | — | 0.155 | 487x |
| 179 | 0.184 (1/60 s) | — | — |
| 275 | 0.581 (1/120 s) | — | — |
| 288 | — | 0.904 | 4,740x |
| 365 | **0.997** (1/120 s) | — | — |
| 461 | 1.653 (1/120 s) | — | — |
| 600 | — | 2.404 | 16,083x |
| 800 | — | 4.373 | 32,154x |
| 1,285 | 14.53 (1/240 s) | — | — |

The comparison is between different geometries — a 0.25 m free-flying sphere
lattice against a clamped rectangular panel — so only the element count and the
ratio are being compared, not the scenes. The columns also differ in what they
guarantee. **Every implicit number in that column passed the energy, momentum
and penetration audits at every step. No explicit number did, because that lane
has no such audit and reports every one of these runs as temporally
unresolved.** The middle column is the cost of stepping the network at a step
315 to 7,353 times larger than its own lattice frequency allows; the right
column is what it would cost to stop doing that.

Read that way, the two lanes are not close. At 288–365 elements the implicit
lane is at 1x with its audits passing, and the explicit lane is at 0.9 as run
but 4,740x away from a step it can defend.

## Where 1x realtime sits: the answer

**Implicit lane (`ConservativeStep`, Newton + GMRES): 365 nodes and 4,321
bonds, at a 1/120 s step, sustained over 4 s of simulated time.** Glass 0.997
and 1.026 across two runs, iron 1.005 and 1.034, oak 0.816 and 0.857. With
margin for the machine's ~3% run-to-run spread, the defensible figure is
**about 275–365 nodes**. This is free flight with no contact, fracture, friction
or damping; adding any of those will move the line down.

**Explicit lane (`NetworkWorld` + Jolt): 288 cells and 1,858 links, at the
1/480 s step the fixtures ship with,** for an awake scene — glass 0.904, oak
0.868, iron 1.119. But that step is 5,243 times larger than the lattice's own
resolution bound. **At a step the engine would call resolved, this lane reaches
1x at no size measured**; the smallest panel in the sweep, 48 cells, is still
184x short, and cutting cells 16.7x buys only 3.1x in `maximum_step_s`.

## The single biggest cost driver

**Node count, at a measured exponent of about 1.6 in the implicit lane and 1.43
in the explicit one.** Both are superlinear, and in the implicit lane the reason
is visible in the solver's own counters: Krylov iterations per step grow as
N^0.59 while each iteration costs O(bonds). Doubling a scene costs about three
times the wall clock, not two.

The second driver, and the one that is easier to get wrong, is that **the
timestep has an optimum and it is not the largest one that converges.** Above
the optimum, Newton and Krylov work explodes — 37x more wall time per step for
2x more simulated time, on the 179-node glass lattice. Below it, per-step cost
hits a floor and the ratio climbs again. Choosing 1/30 s to "save work" on that
lattice costs 18x more wall clock than choosing 1/60 s.

## What would have to change for a visually useful scene

Stated as extrapolation from measured exponents, not as a promise.

A scene worth looking at is not 365 nodes. Take 10,000 nodes as a modest target
for one recognisable object. From the measured 1x point of 365 nodes and the
measured N^1.615 exponent, 10,000 nodes is `(10000/365)^1.6` = **about 200x**
more work per simulated second. That is the size of the gap. Nothing measured
here closes it, and no speedup is claimed. What the measurements do say about
where such a factor could come from:

- **Threading is entirely unexploited and is the only large, unmeasured
  headroom.** Both lanes run on one core of a 24-core machine; the explicit lane
  explicitly asks Jolt for zero workers. A perfect 24x would still leave a
  factor of 9 at 10,000 nodes, and neither lane has been measured with threads
  on, so even the 24x is unmeasured here.
- **The Krylov iteration count is the specific thing to attack.** It is measured
  at N^0.593 with the current per-node 3x3 block-Jacobi preconditioner, while
  bond count — the work in one iteration — is measured at N^1.160. A
  preconditioner that held the iteration count flat would leave the bond term,
  N^1.16, which at 10,000 nodes is a factor of **47 rather than 200**. This is a
  preconditioner question rather than a micro-optimisation one, and no such
  preconditioner has been tried here.
- **Timestep is nearly exhausted as a lever.** At the 365-node 1x lattice the
  best step is 1/120 s (8.33 ms) and the measured acceptance boundary is
  12.31 ms for glass and iron, 15.62 ms for oak — so at most 1.5x to 1.9x sits
  between the optimum and the wall, and the sweep shows that stepping closer to
  the wall costs more than it saves. The boundary itself shrinks as N^-0.4, so
  this lever gets worse with scale, not better.
- **Level of detail is untouched.** Every node in both lanes is active every
  step; `docs/mechanics-scorecard.md` P01 already records that there is no
  activation, demotion, refinement or re-coarsening. A scene that only solves
  the moving part is the one structural change that could beat the exponent
  rather than fight it, and nothing in this note measures it because nothing
  implements it.

For the explicit lane the arithmetic is different and worse. It is not 200x from
a target scene; it is 184x from realtime on the *smallest scene measured*,
purely because the step needed to resolve a stiff cell lattice is around
10^-6 s. Node-count reduction does not fix that: across the whole 48-to-800-cell
range measured, `maximum_step_s` moves by only 3.1x (8.861e-7 to 2.833e-7 s for
glass), because that bound is set by one cell's stiffness over its mass rather
than by how many cells there are. Substepping, implicit integration of the
springs, or a softer effective lattice would move it; none of them is measured
here. Oak is 2.5x better off than glass on this axis (1.650e-6 vs 6.623e-7 s at
108 cells) and still 216x short.

## Limitations of this note

- The implicit lane was measured in **free flight only**: no contact, support,
  friction, fracture, damage or damping, and zero gravity. The record's own
  caveat still stands. Contact and fracture will add cost and can only move the
  1x line down.
- The explicit panels are **clamped and unloaded** — no ball, no tool, no
  fracture. The shipped fixtures with impacts are reported separately and only
  in blended-window form.
- Geometry differs between the lanes (sphere vs panel), so the joint chart
  compares element counts, not scenes.
- The timestep acceptance boundary is measured with an **8-step criterion** from
  the rigid initial state. A step accepted for 8 steps is not guaranteed for
  480; the 4 s duration runs confirm the 1/120 s and 1/240 s cases used in the
  headline, but the bisected boundaries themselves were not re-verified at that
  length.
- Timings were taken on a shared machine. Where a run was repeated the spread is
  reported; the largest observed run-to-run spread on a repeated cell is about
  3%, and the explicit lane's 800-cell rows have spreads up to 3 ms.
- The resolved-step column for the explicit lane extrapolates past the smallest
  admitted timestep. The extrapolation rests on a measured constant (per-step
  cost flat to 11% over a 20x `dt` range), and is labelled everywhere it appears.
- No cell in any table is estimated. Cells that could not be run are empty and
  their reason is stated.

## Reproducing everything

```powershell
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 4
python scripts/realtime-envelope-sweep.py nodes
python scripts/realtime-envelope-sweep.py implicit --steps 12 --repeats 3 --budget 180
python scripts/realtime-envelope-sweep.py sustained --sim 0.2 --repeats 2 --budget 300
python scripts/realtime-envelope-sweep.py dtboundary --steps 8 --budget 300
python scripts/realtime-envelope-sweep.py explicit --repeats 3 --budget 600
python scripts/realtime-envelope-sweep.py explicit_dt --repeats 3 --budget 600
python scripts/realtime-envelope-sweep.py duration --budget 900
```

The 365-node boundary rows were bisected with a targeted variant of the same
`--steps 8` acceptance test, between 1/240 s and 1/60 s, and appended to
`envelope-timestep-boundary.csv`:

```powershell
python -c "import subprocess
PROBE='build/agent/Release/banjo_solver_probe.exe'
def ok(m,h,dt,n=8): return subprocess.run([PROBE,'--material',m,'--voxel-size',repr(h),'--dt',repr(dt),'--steps',str(n)],capture_output=True).returncode==0
for m in ['glass','oak','iron']:
    lo,hi=1/240.0,1/60.0
    for _ in range(7):
        mid=(lo*hi)**0.5
        lo,hi=(mid,hi) if ok(m,0.065,mid) else (lo,mid)
    print(m,lo,hi)"
```

Evidence written by those commands:

| File | Contents |
|---|---|
| [`evidence/envelope-lattice-sizes.csv`](evidence/envelope-lattice-sizes.csv) | voxel size to node/bond count |
| [`evidence/envelope-implicit-sweep.csv`](evidence/envelope-implicit-sweep.csv) | fixed 12-step scan, 3 materials x 10 voxel sizes x 7 timesteps, with 1/30 s and 2 ms columns |
| [`evidence/envelope-implicit-sustained.csv`](evidence/envelope-implicit-sustained.csv) | headline 0.2 s equal-simulated-time sweep |
| [`evidence/envelope-implicit-duration.csv`](evidence/envelope-implicit-duration.csv) | 4 s runs in 0.5 s blocks |
| [`evidence/envelope-timestep-boundary.csv`](evidence/envelope-timestep-boundary.csv) | bisected largest accepted timestep |
| [`evidence/envelope-explicit-sweep.csv`](evidence/envelope-explicit-sweep.csv) | explicit cell ladder and shipped fixtures, blended window |
| [`evidence/envelope-explicit-timestep.csv`](evidence/envelope-explicit-timestep.csv) | explicit matched-window timestep, sleep and cell-count data |

The sweep driver takes no flag that alters solver tolerances, acceptance budgets
or material constants; it only varies material preset, voxel size, timestep,
step count and package resolution, all of which are existing inputs.

## Next measurements

1. Repeat the implicit envelope with the support plane and contact enabled
   (`--case floor`), which is the first thing that will move the 1x line.
2. Measure both lanes with threads enabled — the only large unmeasured headroom.
3. Measure the Krylov iteration count against preconditioner choice, since
   N^0.59 is the exponent that sets the whole cost law.
4. Re-verify the bisected timestep boundaries over 4 s rather than 8 steps.
5. Investigate the 117-node lattice: a reproducible, material-independent
   convergence hole between two lattices that both accept 1/30 s is worth a
   diagnosis, not just a footnote.
