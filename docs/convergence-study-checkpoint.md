# Fracture convergence study: measured timestep and resolution behaviour

Measurement checkpoint, September 6, 2026. Local branch `agent/converge`, not main.

This checkpoint answers one question with data: **does the fracture simulation converge?**
It is a measurement, not a fix. No material constant, solver default, law or engine source
file was changed. The only new source is a measurement harness,
`examples/authoring/convergence_sweep.py`, which drives the existing
`banjo_platform_cli` over declared timestep, mesh and solver-iteration ladders.

**Answer: no.** No admissible configuration of the `material-network-v2` fracture pipeline
is temporally resolved, the discrete fracture answer does not stabilise anywhere in the
admissible parameter space, and the same lattice at rest in a vacuum manufactures up to
1.3e9 J of elastic energy from a zero-energy initial state. The rigid-body and rigid-contact
paths, by contrast, converge cleanly at first order.

---

## 1. Environment and reproduction

| Item | Value |
|---|---|
| Commit | `fbd81082c7ce6726285e93585717e4497f856df6` (`agent/converge`, worktree `banjo-agents/converge`) |
| Host | Windows 11 Pro 10.0.26200, Intel Core Ultra 9 285K, 24 logical processors |
| Compiler | MSVC 19.44.35228.0 (reported by the engine as `MSVC 1944`) |
| Generator | Visual Studio 17 2022, x64, `Release` |
| Jolt | v5.6.0, `DOUBLE_PRECISION=ON` (engine reports `position_bits: 64`) |
| Python | 3.13.5 |
| Backend under test | `material-network-v2`, package `banjo-network-2`, `package_version` 2 |

```powershell
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 4
ctest --test-dir build/agent -C Release --output-on-failure
```

Sweep commands, each into a new output directory, run from `examples/authoring`:

```powershell
python convergence_sweep.py --engine ../../build/agent/Release/banjo_platform_cli.exe `
    --output ../../build/converge/map    --studies map
python convergence_sweep.py --engine ../../build/agent/Release/banjo_platform_cli.exe `
    --output ../../build/converge/main   --studies A,B,ctrl
python convergence_sweep.py --engine ../../build/agent/Release/banjo_platform_cli.exe `
    --output ../../build/converge/depth  --studies D --d-elapsed-s 0.5 `
    --d-divisors 480,4800 --d-depths 0,1,2,3,4,5,6,7,8
python convergence_sweep.py --engine ../../build/agent/Release/banjo_platform_cli.exe `
    --output ../../build/converge/bounce --studies ctrl --ctrl-elapsed-s 0.3
```

Each output directory contains `runs.json`, `runs.csv`, `environment.json`, every generated
package under `packages/` and every raw engine report under `reports/`. Sections 7-10 below
were run as short scripts built on the same harness functions
(`single_panel_scene`, `make_package`); their exact parameters are stated inline.

Totals actually executed: 75 validate records, 120 + 54 + 42 stepped runs from the harness
plus 88 stepped runs from the section 7-10 probes. Harness wall time 204.4 s (main),
63.7 s (depth), 0.7 s (bounce), 1.3 s (map).

The tree at this commit builds fully in Release and **all 84 regression suites pass in
91.41 s** (`ctest --test-dir build/agent -C Release`). No engine source changed in this
checkpoint, so that result is a baseline, not new validation.

**Determinism check.** Repeating the same package three times in fresh processes reproduces
every reported field bit-for-bit, so all spreads below are timestep effects and not run-to-run
noise:

```
build/agent/Release/banjo_platform_cli.exe --run build/converge/main/packages/B_pinned_glass_8x12x3_dt960.json  480
build/agent/Release/banjo_platform_cli.exe --run build/converge/main/packages/B_pinned_glass_8x12x3_dt1920.json 960
```

| Repeat | dt = 1/960 s | dt = 1/1920 s |
|---|---|---|
| 1 | broken 0, E = 173.943511 J | broken 892, E = 189.823177 J |
| 2 | broken 0, E = 173.943511 J | broken 892, E = 189.823177 J |
| 3 | broken 0, E = 173.943511 J | broken 892, E = 189.823177 J |

---

## 2. What can actually be varied

Two hard limits define the entire admissible search space, both read from the source and
confirmed by rejection at the boundary.

- **Timestep.** `NetworkWorld.cpp:93` clamps `fixed_dt_s` to `[1/4800, 1/240]` s. Anything
  smaller is rejected with `network SI number outside bounds`. The smallest admissible fixed
  step is therefore **2.0833e-4 s**.
- **Mesh.** `banjo_authoring.validate_network_geometry` and `NetworkWorld.cpp:200` cap each
  `resolution` axis at 16 and the whole world at 1024 cells. The 0.24 x 0.36 x 0.04 m panel
  ladder used here is (nx, ny, nz) = (4,6,2), (6,9,2) [authored default], (8,12,3), (10,15,4),
  giving 49, 109, 289 and 601 cells and 236, 586, 1858 and 4208 links (cell counts include the
  single rigid striker body).
- **Substep.** `damage_integration.maximum_depth` is capped at 8, so recursive bisection can
  reach `dt/256`, but only inside ticks where damage, plasticity or brittle overshoot already
  moved (section 6).
- **Solver.** `solver_iterations` is bounded to `[4, 128]`, default 24.

The elapsed windows are 3.0 s (study A, matching the documented fixture), 0.5 s (studies B, D
and sections 8-10) and 0.3 s (bounce control). All fracture activity in the 12 m/s fixture
occurs between 0.0119 s and 0.083 s, so 0.5 s contains the whole fracture window; this was
checked against the 3.0 s runs, which report the same event set.

**`resolution` also changes the boundary condition.** `pin_boundary: true` pins the one-cell
in-plane ring (`NetworkWorld.cpp:205`), so the pinned fraction falls from 65% at (4,6,2) to
31% at (10,15,4). A pinned/unpinned control is reported in section 9.

---

## 3. The engine's own resolution bound: nothing admissible is resolved

`assessSpringResolution` (`src/physics/ResolutionBudget.cpp`) bounds the spring network's
maximum angular frequency by `omega^2 <= 2 max_i(sum_j k_ij / m_i)` and requires
`omega * dt <= 0.2 rad`. This is free to evaluate: `--validate` reports it without stepping.
Sweeping the full admissible (material, mesh, dt) space gives 72 records, **every one of which
reports `temporal_resolution.resolved: false`.**

Per-mesh frequency bound and required substeps (the substep count is `ceil(omega*dt/0.2)`):

| Material | Mesh | Cells | Links | Pinned | omega (rad/s) | Required max step (s) | Substeps at 1/240 | at 1/480 | at 1/4800 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| glass | 4x6x2 | 49 | 236 | 32 | 225 697.3 | 8.8614e-07 | 4 703 | 2 352 | 236 |
| glass | 6x9x2 | 109 | 586 | 52 | 301 959.2 | 6.6234e-07 | 6 291 | 3 146 | 315 |
| glass | 8x12x3 | 289 | 1 858 | 108 | 503 274.1 | 3.9740e-07 | 10 485 | 5 243 | 525 |
| glass | 10x15x4 | 601 | 4 208 | 184 | 642 246.1 | 3.1141e-07 | 13 381 | 6 691 | 670 |
| oak | 4x6x2 | — | — | — | *rejected* | *rejected* | — | — | — |
| oak | 6x9x2 | 109 | 586 | 52 | 121 211.7 | 1.6500e-06 | 2 526 | 1 263 | **127** |
| oak | 8x12x3 | 289 | 1 858 | 108 | 189 726.0 | 1.0542e-06 | 3 953 | 1 977 | 198 |
| oak | 10x15x4 | 601 | 4 208 | 184 | 243 371.3 | 8.2179e-07 | 5 071 | 2 536 | 254 |
| iron | 4x6x2 | 49 | 236 | 32 | 220 851.9 | 9.0558e-07 | 4 602 | 2 301 | 231 |
| iron | 6x9x2 | 109 | 586 | 52 | 295 476.7 | 6.7687e-07 | 6 156 | 3 078 | 308 |
| iron | 8x12x3 | 289 | 1 858 | 108 | 492 469.6 | 4.0612e-07 | 10 260 | 5 130 | 513 |
| iron | 10x15x4 | 601 | 4 208 | 184 | 628 458.1 | 3.1824e-07 | 13 093 | 6 547 | 655 |
| glass+oak+iron (documented 3-panel scene) | 6x9x2 | 327 | 1 758 | 156 | 301 959.2 | 6.6234e-07 | 6 291 | 3 146 | 315 |

Consequences that follow directly from the table:

1. The documented fixture at its authored step (1/480 s) is **3 146x coarser** than the step
   the engine's own criterion requires.
2. The **smallest admissible fixed step (1/4800 s) is still 315x coarser** than that
   requirement for the documented scene.
3. The single best cell anywhere in the admissible space — oak, coarsest admissible mesh,
   smallest admissible step — is **127x coarser** than required.
4. Refinement moves the target: halving the in-plane spacing roughly doubles `omega`
   (`k ~ h`, `m ~ h^3`), so a joint space-time refinement needs `dt ~ h`. Going from (6,9,2)
   to (10,15,4) raises the glass requirement from 6.62e-7 s to 3.11e-7 s.

**`temporal_policy: "require-resolved"` therefore rejects every fracture scene in the
repository.** Every scene in `examples/authoring/verify_physics.py` runs with the default
`"diagnose"`, which reports the violation and proceeds.

**Mesh coarsening has a material bound too.** Oak at (4,6,2) is rejected with
`network cohesive law requires df greater than d0`. The cohesive law needs
`2*Gc/sigma_t > sigma_t*L/E`, i.e. bond length `L < 2*E*Gc/sigma_t^2`. For oak's stiff grain
axis (E = 12 GPa, sigma_t = 90 MPa, Gc = 20 kJ/m^2) that is L < 59.3 mm, and the (4,6,2) mesh's
in-plane face diagonal is 84.9 mm. Glass and iron admit the same mesh because glass uses the
brittle law and iron has `fracture_enabled: false`. So oak has both an upper mesh bound (law
admissibility) and, with everything else, an unreachable lower timestep bound.

---

## 4. Study A: the documented three-panel fixture, 3.0 s

Fixture: `examples/authoring/verify_physics.py` `_panel_scene`, unchanged — glass, oak and iron
0.24 x 0.36 x 0.04 m panels at (6,9,2), each struck by a 0.08 m iron ball from z = 0.2 m.
327 cells, 1 758 links, 156 pinned, ground on, gravity on, `solver_iterations` 24, 3.0 s elapsed.
Broken-link counts are per panel.

| Speed | dt | Steps | glass | oak | iron | Damaged | Components | First event (s) | Last event (s) | E0 (J) | E final (J) | Unseparated dE (J) | Fracture work (J) | Max strain | Wall (ms) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 1/240 | 720 | 0 | 0 | 0 | 0 | 6 | — | — | 100.76 | 93.33 | −7.43 | 0.000 | 0.002 | 295 |
| 2 | 1/480 | 1 440 | 0 | 0 | 0 | 0 | 6 | — | — | 100.76 | 96.69 | −4.07 | 0.000 | 0.003 | 505 |
| 2 | 1/960 | 2 880 | 0 | 0 | 0 | 0 | 6 | — | — | 100.76 | 94.94 | −5.82 | 0.000 | 0.004 | 916 |
| 2 | 1/1920 | 5 760 | 0 | 0 | 0 | 0 | 6 | — | — | 100.76 | 95.59 | −5.17 | 0.000 | 0.006 | 1 841 |
| 2 | 1/3840 | 11 520 | 0 | 0 | 0 | 0 | 6 | — | — | 100.76 | 94.77 | −5.99 | 0.000 | 0.008 | 3 683 |
| 2 | 1/4800 | 14 400 | 0 | 0 | 0 | 0 | 6 | — | — | 100.76 | 93.70 | −7.06 | 0.000 | 0.010 | 4 834 |
| 6 | 1/240 | 720 | 0 | 0 | 0 | 1 | 6 | — | — | 202.03 | 123.70 | −78.27 | 0.027 | 0.008 | 393 |
| 6 | 1/480 | 1 440 | 0 | 0 | 0 | 2 | 6 | — | — | 202.03 | 173.58 | −28.41 | 0.015 | 0.009 | 691 |
| 6 | 1/960 | 2 880 | 0 | 0 | 0 | 10 | 6 | — | — | 202.03 | 154.32 | −47.29 | 0.424 | 0.014 | 1 022 |
| 6 | 1/1920 | 5 760 | 0 | 2 | 0 | 21 | 6 | 0.02500 | 0.02552 | 202.03 | 146.29 | −54.12 | 1.622 | 0.024 | 1 834 |
| 6 | 1/3840 | 11 520 | 1 | 4 | 0 | 19 | 6 | 0.02396 | 0.02474 | 202.03 | 125.76 | −73.95 | 2.212 | 0.026 | 3 631 |
| 6 | 1/4800 | 14 400 | 3 | 9 | 0 | 12 | 6 | 0.02396 | 0.02604 | 202.03 | 110.35 | −86.61 | 4.660 | 0.060 | 4 506 |
| 12 | 1/240 | 720 | 0 | 13 | 0 | 30 | 6 | 0.02917 | 0.39167 | 543.82 | 236.04 | −301.26 | 5.906 | 0.602 | 426 |
| 12 | 1/480 | 1 440 | 0 | 9 | 0 | 29 | 6 | 0.02083 | 0.04167 | 543.82 | 197.84 | −342.09 | 3.833 | 0.663 | 980 |
| 12 | 1/960 | 2 880 | 1 | 10 | 0 | 39 | 6 | 0.01458 | 0.01875 | 543.82 | 347.90 | −190.66 | 5.207 | 0.043 | 1 444 |
| 12 | 1/1920 | 5 760 | 4 | 26 | 0 | 59 | 6 | 0.01250 | 0.01719 | 543.82 | 296.71 | −232.56 | 13.960 | 0.079 | 1 961 |
| 12 | 1/3840 | 11 520 | 28 | 38 | 0 | 37 | 6 | 0.01198 | 0.01641 | 543.82 | 243.56 | −276.09 | 18.627 | 0.133 | 4 924 |
| 12 | 1/4800 | 14 400 | 46 | 40 | 0 | 27 | 6 | 0.01187 | 0.01625 | 543.82 | 192.74 | −322.55 | 19.460 | 0.118 | 7 275 |
| 20 | 1/240 | 720 | 1 | 2 | 0 | 23 | 6 | 0.03333 | 0.07917 | 1 353.99 | 440.55 | −910.70 | 1.668 | 0.061 | 368 |
| 20 | 1/480 | 1 440 | 0 | 7 | 0 | 49 | 6 | 0.01250 | 0.01667 | 1 353.99 | 634.06 | −714.75 | 4.933 | 0.113 | 683 |
| 20 | 1/960 | 2 880 | 1 | 44 | 0 | 77 | 6 | 0.00833 | 0.02500 | 1 353.99 | 479.89 | −854.84 | 19.128 | 0.092 | 1 280 |
| 20 | 1/1920 | 5 760 | 18 | 76 | 0 | 102 | 6 | 0.00729 | 0.04635 | 1 353.99 | 659.93 | −655.68 | 35.264 | 0.129 | 2 800 |
| 20 | 1/3840 | 11 520 | 203 | 95 | 0 | 83 | 6 | 0.00729 | 2.88750 | 1 353.99 | 234.40 | −1 019.27 | 56.580 | 0.151 | 7 638 |
| 20 | 1/4800 | 14 400 | 255 | 94 | 0 | 349* | 6 | 0.00708 | 2.61937 | 1 353.99 | 174.16 | −1 070.21 | 53.926 | 0.128 | 10 404 |

\* the 20 m/s 1/4800 row's world total is 349 broken and 67 damaged; the per-panel split is
glass 255 / oak 94 / iron 0.

Readings:

- **2 m/s converges only in the degenerate sense**: zero breaks at every step. Section 5 shows
  its continuous observable does not converge.
- **6, 12 and 20 m/s do not converge.** Glass goes 0 → 46 at 12 m/s and 1 → 255 at 20 m/s
  across the admissible range, still climbing at the finest admissible step. Oak goes 13 → 40
  and 2 → 94. Nothing plateaus.
- **A single halving is enough to change the answer by an order of magnitude.** At 20 m/s,
  glass goes from 18 to 203 broken links between 1/1920 s and 1/3840 s.
- **Iron is 0 everywhere because the model is off**, not because it converged: the catalog sets
  `iron.fracture_enabled: false`, so no iron bond can ever fail in this pipeline. The
  "glass 0 / oak 24 / iron 0" style rows in earlier checkpoints must not be read as an iron
  physics result.
- **The energy ledger does not converge either.** `unseparated_energy_change_j`
  (`E_mech + elastic + fracture + plastic + unreleased − E0`) at 20 m/s runs
  −910.7, −714.8, −854.8, −655.7, −1 019.3, −1 070.2 J against an initial 1 354.0 J: 48-79% of
  the initial mechanical energy is unattributed, and the fraction does not settle.
- **One quantity does converge: the first fracture event time.** At 12 m/s it runs 0.029167,
  0.020833, 0.014583, 0.012500, 0.011979, 0.011875 s. Successive halving differences are
  −8.333e-3, −6.250e-3, −2.083e-3, −5.208e-4 s, with ratios 1.33, 3.00, 4.00 — approaching the
  ratio 4 of a second-order sequence. Richardson extrapolation from the last halving pair gives
  0.011805 s, and the measured 1/4800 value is 0.011875 s. **Impact timing converges; the
  fracture count that follows it does not.**

---

## 5. Study B: mesh x timestep, single-material panels, 0.5 s

One panel plus one 12 m/s striker per scene, so the mesh can be refined past the 1024-cell world
budget. `solver_iterations` 24, `pin_boundary: true`. Broken links out of the link count in the
row header.

**Glass** (brittle law):

| Mesh | Cells | Links | 1/240 | 1/480 | 1/960 | 1/1920 | 1/3840 | 1/4800 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 4x6x2 | 49 | 236 | 0 | 0 | 0 | 1 | 8 | 14 |
| 6x9x2 | 109 | 586 | 0 | 0 | 1 | 4 | 28 | 48 |
| 8x12x3 | 289 | 1 858 | 1 | 0 | 0 | **892** | 1 070 | 835 |
| 10x15x4 | 601 | 4 208 | 66 | 9 | 1 | **2 362** | 2 577 | 2 512 |

**Oak** (cohesive law; the 4x6x2 mesh is rejected by the law itself):

| Mesh | Cells | Links | 1/240 | 1/480 | 1/960 | 1/1920 | 1/3840 | 1/4800 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 4x6x2 | — | — | reject | reject | reject | reject | reject | reject |
| 6x9x2 | 109 | 586 | 1 | 0 | 10 | 327 | 41 | 40 |
| 8x12x3 | 289 | 1 858 | 29 | 15 | 6 | 34 | 62 | 74 |
| 10x15x4 | 601 | 4 208 | 48 | 597 | 4 | 2 415 | 86 | 102 |

**Iron** (`fracture_enabled: false`): 0 at every mesh and every timestep, by construction.

Readings:

- **The worst single-halving change measured anywhere in this study**: glass at 8x12x3 goes from
  **0 broken links at dt = 1/960 s to 892 of 1 858 at dt = 1/1920 s** — an intact panel versus a
  panel with 48% of its network severed, from one halving of the timestep and nothing else.
  At 10x15x4 the same halving takes glass from 1 to 2 362 of 4 208.
- **The result is not even monotone.** Oak at 10x15x4 reads 48, 597, 4, 2 415, 86, 102 across
  the six steps — a 600-fold spread with sign changes in the trend.
- **Refining the mesh makes timestep convergence worse, not better.** The coarsest mesh's spread
  is 0 → 14; the finest mesh's is 1 → 2 577. This is the opposite of the expected behaviour and
  is explained in section 8.
- **Energy is created in the fracturing fine-mesh runs.** Glass 10x15x4 at 1/1920 s reports
  `mechanical_energy_j / initial_energy_j = 1.358` (+132.1 J unseparated); at 1/3840 s, 1.198;
  at 1/4800 s, 1.183.

**Cost.** Solver-only wall time per 1 000 steps at `solver_iterations` 24, single-threaded
process, no rendering: 49 cells 148-233 ms, 109 cells 311-363 ms, 289 cells 1 577-2 195 ms,
601 cells 3 195-4 566 ms. The most expensive study B cell (oak 10x15x4 at 1/4800 s, 0.5 s of
simulation) cost 12 855 ms, i.e. **25.7x slower than real time** for a single 0.36 m panel.

---

## 6. Study D: adaptive substep bisection, the only refinement left below 1/4800 s

`damage_integration` bisects a tick recursively when a damage, plastic-strain or brittle-opening
increment exceeds its target, down to `maximum_depth` levels (cap 8, so `dt/256`). Runs below use
deliberately tight targets (`maximum_damage_increment` 1e-6, `maximum_plastic_strain_increment`
1e-8, `maximum_brittle_opening_overshoot` 1e-8, `on_limit: "report"`) so that bisection fires
wherever any damage moves. Single panel at (6,9,2), 12 m/s striker, 0.5 s. Depth 0 reproduces the
non-adaptive baseline exactly.

| Material | dt | Depth | Smallest accepted step (s) | Broken | Comp. | E/E0 | Fracture work (J) | Wall (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| glass | 1/480 | 0-8 | 2.0833e-03 | 0 | 2 | 0.25 | 0.00 | 185-206 |
| glass | 1/4800 | 0 | 2.0833e-04 | 48 | 2 | 0.38 | 0.06 | 1 500 |
| glass | 1/4800 | 1 | 1.0417e-04 | 71 | 2 | 0.16 | 0.10 | 1 509 |
| glass | 1/4800 | 2 | 5.2083e-05 | 67 | 2 | 0.22 | 0.09 | 1 382 |
| glass | 1/4800 | 3 | 2.6042e-05 | 362 | 8 | 0.47 | 0.49 | 1 312 |
| glass | 1/4800 | 4 | 1.3021e-05 | 366 | 11 | 0.54 | 0.49 | 1 302 |
| glass | 1/4800 | 5 | 6.5104e-06 | 369 | 12 | 0.51 | 0.50 | 1 321 |
| glass | 1/4800 | 6 | 3.2552e-06 | 369 | 13 | 0.60 | 0.50 | 1 354 |
| glass | 1/4800 | 7 | 1.6276e-06 | 366 | 13 | 0.64 | 0.49 | 1 460 |
| glass | 1/4800 | 8 | 8.1380e-07 | 209 | 10 | 0.64 | 0.28 | 1 534 |
| oak | 1/480 | 0 | 2.0833e-03 | 0 | 2 | 1.01 | 0.68 | 197 |
| oak | 1/480 | 1 | 1.0417e-03 | 21 | 2 | 1.56 | 9.91 | 202 |
| oak | 1/480 | 2 | 5.2083e-04 | 405 | 13 | 4.48 | 245.58 | 242 |
| oak | 1/480 | 3 | 2.6042e-04 | 462 | 58 | **48.22** | 397.65 | 190 |
| oak | 1/480 | 4 | 1.3021e-04 | 439 | 52 | 44.11 | 379.37 | 226 |
| oak | 1/480 | 5 | 6.5104e-05 | 433 | 49 | 27.70 | 372.72 | 269 |
| oak | 1/480 | 6 | 3.2552e-05 | 446 | 57 | 30.15 | 391.33 | 342 |
| oak | 1/480 | 7 | 1.6276e-05 | 448 | 57 | 33.70 | 391.29 | 514 |
| oak | 1/480 | 8 | 8.1380e-06 | 423 | 45 | 4.89 | 371.51 | 661 |
| oak | 1/4800 | 0 | 2.0833e-04 | 40 | 2 | 0.32 | 18.78 | 1 489 |
| oak | 1/4800 | 1 | 1.0417e-04 | 40 | 2 | 0.21 | 27.64 | 1 640 |
| oak | 1/4800 | 2 | 5.2083e-05 | 44 | 2 | 0.25 | 26.19 | 1 693 |
| oak | 1/4800 | 3 | 2.6042e-05 | 80 | 2 | 0.09 | 45.64 | 1 594 |
| oak | 1/4800 | 4 | 1.3021e-05 | 83 | 2 | 0.10 | 46.64 | 1 907 |
| oak | 1/4800 | 5 | 6.5104e-06 | 85 | 2 | 0.11 | 49.17 | 2 168 |
| oak | 1/4800 | 6 | 3.2552e-06 | 87 | 2 | 0.12 | 52.93 | 3 382 |
| oak | 1/4800 | 7 | 1.6276e-06 | 86 | 2 | 0.11 | 51.82 | 5 130 |
| oak | 1/4800 | 8 | 8.1380e-07 | 89 | 2 | 0.12 | 53.00 | 10 782 |
| iron | 1/480, 1/4800 | 0-8 | = dt (never bisects) | 0 | 2 | 0.37 | 0.00 | 178-1 981 |

Readings:

- **The nearest thing to a converged fracture answer in the whole study**: oak at dt = 1/4800 s,
  depth >= 3, gives 80, 83, 85, 87, 86, 89 broken links across a 32x refinement of the substep —
  a **±5% band**. At depths 7 and 8 the accepted substep (1.63e-6 and 8.14e-7 s) is finally below
  oak's required 1.65e-6 s, and crossing that threshold changes the count by 3 links.
- **That plateau is not the answer, because it disagrees with the other timestep.** The same
  fixture at dt = 1/480 s with deep bisection plateaus at 423-462 broken links. Two plateaus,
  five times apart, from the same physics.
- **Bisection cannot find fracture a coarse step never starts.** Glass at 1/480 s reports
  `deepest_trial: 0` at every depth: no damage ever moves, so the controller never refines, and
  the answer stays 0 while dt = 1/4800 s gives 48-369. Iron likewise never bisects, because
  `fracture_enabled: false` means no damage state evolves.
- **Refinement manufactures energy.** Oak at dt = 1/480 s, depth 3 reports a final mechanical
  energy of **7 763.58 J from an initial 161.00 J — 48.2x**. Depths 4-7 sit between 27x and 44x.
  Substepping is a pure numerical control; it must not add energy. The bisection also never
  actually meets its criterion (`accepted_maximum_damage_increment` stays 1.0 against a 1e-6
  target, with `unresolved_substeps` up to 6 030), so the depth cap is always the binding limit.

---

## 7. Controls that do converge: rigid integration and rigid contact

Same engine, same package format, no material network.

**Free flight** (0.08 m ball, gravity only, 0.5 s; error against the exact parabola; identical
for glass, oak and iron):

| dt | Position error (m) | Ratio | Velocity error (m/s) | dE, glass (J) | Ratio |
|---:|---:|---:|---:|---:|---:|
| 1/240 | 1.022e-02 | — | 2.413e-06 | −6.718e-02 | — |
| 1/480 | 5.108e-03 | 2.00 | 3.664e-06 | −3.359e-02 | 2.00 |
| 1/960 | 2.563e-03 | 1.99 | 1.893e-05 | −1.684e-02 | 1.99 |
| 1/1920 | 1.270e-03 | 2.02 | 1.630e-05 | −8.358e-03 | 2.01 |
| 1/3840 | 6.263e-04 | 2.03 | 2.929e-05 | −4.136e-03 | 2.02 |
| 1/4800 | 4.967e-04 | 1.26 (dt ratio 1.25) | 4.789e-05 | −3.295e-03 | 1.26 |

Clean first order in both position and energy drift.

**Zero gravity transport**: position error 6.706e-08 m and energy change exactly 0.000e+00 J at
every timestep — identical to machine precision across the whole ladder.

**Rigid contact bounce** (ball dropped at 2 m/s onto the finite ground, 0.3 s, no network, nothing
that can fracture):

| dt | Final y (m) | Final vy (m/s) | E/E0 |
|---:|---:|---:|---:|
| 1/240 | 0.298547 | −0.411624 | 1.011 |
| 1/480 | 0.297750 | −0.391186 | 1.006 |
| 1/960 | 0.296494 | −0.401405 | 1.003 |
| 1/1920 | 0.296285 | −0.396307 | 1.001 |
| 1/3840 | 0.296183 | −0.393734 | 1.001 |
| 1/4800 | 0.296163 | −0.393214 | 1.001 |

Position converges to ~0.29616 m and the contact energy gain falls from 1.1% to 0.1%, halving with
dt. Identical for glass, oak and iron.

**Conclusion: the rigid integrator and the contact solver both converge.** The failure is in the
material spring network.

---

## 8. The at-rest reproducer: the network is unstable with no load at all

The decisive experiment. A single panel, **zero gravity, no ground, no contact, no striker, zero
initial velocity, zero initial elastic energy.** The exact solution is that nothing moves and every
reported energy stays 0 J forever. Run for 0.5 s.

| Material | Mesh | Pinned | dt | Mechanical E (J) | Elastic E (J) | \|p\| (kg m/s) | Max axial strain | Broken links |
|---|---|---|---:|---:|---:|---:|---:|---:|
| glass | 6x9x2 | no | 1/240 | 0.544 | 4.07e-03 | 5.1e-07 | 2.1e-05 | 0 |
| glass | 6x9x2 | no | 1/4800 | 5.537 | 6.58e-03 | 1.7e-05 | 1.66e-03 | **322** |
| glass | 6x9x2 | yes | 1/240 | 1.4e-12 | 9.9e-11 | 8.4e-07 | 1.9e-09 | 0 |
| glass | 6x9x2 | yes | 1/4800 | 0 | 1.67e-07 | 0 | 9.3e-08 | 0 |
| glass | 10x15x4 | no | 1/240 | 0.112 | 8.45e-04 | 1.0e-07 | 9.3e-06 | 0 |
| glass | 10x15x4 | no | 1/4800 | 11.194 | 6.35e-02 | 9.0e-06 | 2.28e-03 | **2 109** |
| glass | 10x15x4 | yes | 1/4800 | 11.202 | 4.03e-02 | 1.748 | 3.05e-03 | **2 477** |
| oak | 6x9x2 | no | 1/4800 | 0.875 | 1.09e-02 | 4.0e-06 | 0.132 | **219** |
| oak | 10x15x4 | no | 1/4800 | 20.050 | 0.365 | 2.4e-06 | 0.393 | **1 497** |
| iron | 6x9x2 | no | 1/240 | 9.195 | 8.69e-03 | 2.6e-06 | 1.6e-05 | 0 |
| iron | 6x9x2 | no | 1/4800 | 1.90e+04 | **7.09e+05** | 466.6 | 0.350 | 0 |
| iron | 10x15x4 | no | 1/240 | 2.676 | 6.34e-03 | 2.9e-07 | 1.7e-05 | 0 |
| iron | 10x15x4 | no | 1/4800 | 1.66e+06 | **1.28e+09** | 2 855 | **14.73** | 0 |
| iron | 10x15x4 | yes | 1/4800 | 5 028.45 | 1 605.9 | 369.3 | 1.43e-02 | 0 |

This is not discretisation error. It is a self-excited instability:

- **A glass panel sitting motionless in a vacuum shatters 2 109 of its 4 208 bonds** at
  dt = 1/4800 s. Oak breaks 1 497. At dt = 1/240 s the same panels break nothing.
- **Iron cannot fracture, so it just explodes**: 1.28e9 J of stored elastic energy and 1 473%
  axial strain from a 0 J initial state, with 2 855 kg m/s of momentum created from rest.
- **Refining the timestep makes it worse, monotonically.** This inverts the usual expectation and
  is the mechanism behind sections 4-6: the fine-timestep "fracture" in study B is largely this
  instability, not the fracture law responding to the impact.
- **Pinning masks it partially.** Pinned coarse meshes stay at 0 J; pinned fine meshes still break
  2 477 glass bonds and still gain 5 028 J of iron energy. So the authored `pin_boundary: true`
  hides the defect at the default mesh and hides nothing at the refined mesh.

**Threshold, measured on the cleanest case** (iron 10x15x4, `fracture_enabled: false`, pinned,
12 m/s impact fixture, 0.5 s, initial energy 209.617 J — no bond can break, so every number below
is pure elastic/contact behaviour):

| dt | dt·omega (rad) | Mechanical E (J) | E/E0 | Stored elastic E (J) | Unseparated dE (J) |
|---:|---:|---:|---:|---:|---:|
| 1/960 | 654.6 | 63.55 | 0.303 | 2.28 | −143.79 |
| 1/1088 | 577.6 | 89.49 | 0.427 | 2.98 | −117.14 |
| 1/1200 | 523.7 | 200.33 | 0.956 | 13.65 | +4.36 |
| 1/1344 | 467.6 | 94.73 | 0.452 | 20.36 | −94.53 |
| 1/1536 | 409.2 | 187.72 | 0.896 | 51.75 | +29.85 |
| 1/1728 | 363.7 | 287.73 | 1.373 | 80.05 | +158.16 |
| 1/1920 | 327.3 | 585.52 | 2.793 | 116.47 | +492.37 |
| 1/2400 | 261.9 | 1 375.02 | 6.560 | 184.47 | +1 349.86 |
| 1/3840 | 163.7 | 5 264.80 | 25.116 | 624.49 | +5 679.68 |
| 1/4800 | 130.9 | 11 903.38 | 56.786 | 1 176.28 | +12 870.05 |

Onset is between dt·omega ~578 and ~524; past it, stored elastic energy grows monotonically over
the whole remaining range, by a factor of 516 from 1/960 s to 1/4800 s.

---

## 9. Localising the defect: solver iterations, not the fracture law

If this were an elastic-wave sampling error it would depend on dt·omega only. It does not — it
depends strongly on `solver_iterations`, the Gauss-Seidel iteration count Jolt uses on the
distance-spring lattice. At-rest lattice, unpinned, zero gravity, no contact, dt = 1/4800 s, 0.5 s:

| Material | Mesh | 4 iters | 24 iters (default) | 64 iters | 128 iters (max) |
|---|---|---:|---:|---:|---:|
| glass | 6x9x2 | 413 broken, 17.08 J | 322 broken, 5.54 J | 44 broken, 0.62 J | **0 broken, 0 J** |
| glass | 10x15x4 | 3 239 broken, 61.61 J | 2 109 broken, 11.19 J | 1 865 broken, 4.44 J | 1 249 broken, 2.14 J |
| oak | 6x9x2 | 439 broken, 20.63 J | 219 broken, 0.87 J | **0 broken, 0 J** | **0 broken, 0 J** |
| oak | 10x15x4 | 3 240 broken, 176.71 J | 1 497 broken, 20.05 J | 778 broken, 6.23 J | **0 broken, 0 J** |
| iron | 6x9x2 | 3.16e5 J elastic | 7.09e5 J elastic | 395.9 J elastic, 0 J mech | **2.99e-07 J elastic, 0 J mech** |
| iron | 10x15x4 | 2.93e7 J elastic | 1.28e9 J elastic | 2.02e9 J elastic | 2.97e4 J elastic, 4.74e4 J mech |

(The 64- and 128-iteration iron 10x15x4 runs needed `contact_budget` raised to
`{body_pairs: 262144, constraints: 65536}`; at the default budget the exploded lattice exhausts
`contact-constraints-full`.)

So the at-rest instability is a **solver-convergence failure on a stiff, highly connected
constraint network** — each interior cell has up to 18 spring neighbours — and it is curable at
the authored mesh by raising `solver_iterations` from 24 to 128, and not curable at the finest
mesh even at the schema maximum. It is not caused by the fracture criterion: iron, which cannot
fracture, is the worst case.

**Does fixing the solver fix convergence?** No. Repeating the impact fixture (single panel
6x9x2, 12 m/s striker, 0.5 s) with `solver_iterations: 128`, where the at-rest instability is
gone:

| Material | 1/240 | 1/480 | 1/960 | 1/1920 | 1/3840 | 1/4800 |
|---|---:|---:|---:|---:|---:|---:|
| glass broken | 0 | 0 | 2 | 16 | 48 | 55 |
| oak broken | 0 | 1 | 14 | 21 | 33 | 36 |
| iron broken | 0 | 0 | 0 | 0 | 0 | 0 |
| glass E/E0 | 0.811 | 0.397 | 0.420 | 0.398 | 0.311 | 0.270 |
| oak E/E0 | 0.199 | 0.303 | 0.279 | 0.226 | 0.266 | 0.150 |
| iron E/E0 | 1.220 | 0.914 | 0.915 | 0.893 | 0.809 | 0.754 |
| glass first event (s) | — | — | 0.012500 | 0.011979 | 0.011979 | 0.011875 |
| wall (ms) | 120-147 | 226-285 | 506-603 | 1 107-1 158 | 2 120-2 348 | 2 599-3 150 |

At 128 iterations the erratic jumps and the energy creation are gone (every E/E0 <= 1.22, and the
sequences are monotone), but **the fracture count still rises monotonically over the entire
admissible timestep range with no plateau** — glass 0 → 55, oak 0 → 36 — because the range still
stops 315x short of the engine's own resolution requirement. The first-event time converges as
before.

---

## 10. Is there any configuration that converges?

| Fixture | Converges in dt? | Evidence |
|---|---|---|
| Rigid free flight, glass/oak/iron | **Yes**, first order | Section 7; error halves with dt, ratios 1.99-2.03 |
| Rigid zero-gravity transport | **Yes**, exactly | Section 7; identical at all six steps |
| Rigid contact bounce, glass/oak/iron | **Yes**, first order | Section 7; y → 0.29616 m, energy gain 1.1% → 0.1% |
| Panel impact **event time** | **Yes**, near second order | Section 4; halving ratios 1.33, 3.00, 4.00 → 0.011805 s |
| Panel impact at 2 m/s, **break count** | Degenerate only | Section 4; 0 breaks at every step, but the striker rebound speed runs 1.999, 1.927, 1.359, 0.711, 0.529, 0.436 m/s — a **4.6x change** with no plateau |
| Panel impact, **break count**, any material | **No** | Sections 4, 5, 9 |
| Panel impact, **components / fragment count** | **No** | Section 5; glass 10x15x4 gives 2, 2, 2, 5, 2, 4 |
| Panel impact, **energy ledger** | **No** | Sections 4, 5; unseparated dE is 48-79% of E0 and unsettled |
| At-rest lattice (should be trivially exact) | **No** | Section 8; up to 1.28e9 J from 0 J |
| Adaptive substep at dt = 1/4800 s, oak | **A local plateau only** | Section 6; 80-89 breaks over a 32x substep refinement, but 423-462 at dt = 1/480 s |

**There is no configuration in which the fracture answer converges.** The only apparently
converged fracture cell (2 m/s, zero breaks) is degenerate: its continuous observable, the
striker rebound speed, changes by 4.6x over the same timestep range. The only genuine refinement
plateau found anywhere (section 6) disagrees by 5x with the other timestep's plateau.

**Numerical non-convergence versus physics bug — both are present and they are separable:**

- **Bug (sections 8, 9).** The material spring network is unstable at rest with no load, and
  refinement makes it worse. It creates energy, momentum and fracture from an exactly zero state.
  This is a solver-iteration/constraint-stiffness convergence failure in the distance-spring
  lattice, demonstrable on iron, which cannot fracture. It is upstream of, and independent of,
  the fracture law. Raising `solver_iterations` to 128 removes it at the authored mesh.
- **Non-convergence (sections 3, 9).** Even with that bug suppressed at 128 iterations, the
  fracture count keeps rising monotonically as dt falls, because the admissible timestep range
  never reaches the engine's own `omega*dt <= 0.2` requirement. This one cannot be fixed by a
  setting: the requirement is 315x below the smallest step the package schema will accept.

---

## 11. Limitations of this study

- Windows/MSVC Release only; no macOS, Linux or cross-GPU claim.
- Only the `material-network-v2` backend was swept. The `bonded-reference-v2` bowl solver, the
  `compiled-impact-v1` path and the `banjo_headless` rolling-ball lattice were not measured here;
  `banjo_headless` exposes `--voxel-size` and `--target-speed` but no timestep option and is
  glass-only, so it cannot supply the glass/oak/iron timestep comparison this study needed.
- The mesh ladder keeps the authored 2:3 in-plane aspect but the panel is only 40 mm thick, and
  `resolution` axes must be >= 2, so cell aspect changes across the ladder (in-plane spacing
  60/40/30/24 mm; through-thickness 20/20/13.3/10 mm). Cells are never cubic and the ladder is not
  a uniform refinement in z.
- `pin_boundary: true` pins a one-cell ring, so the physically pinned width shrinks with
  refinement. Section 8 reports pinned and unpinned controls; the impact studies use the authored
  pinned fixture.
- Study A uses 3.0 s; studies B, D and sections 8-10 use 0.5 s and section 7's bounce uses 0.3 s.
  All fracture events in the 12 m/s fixture occur before 0.083 s, and the 3.0 s and 0.5 s runs
  report the same event set, so the shorter windows do not truncate fracture. The 20 m/s case has
  events out to 2.89 s and was only run at 3.0 s.
- Timings are single-process, solver-only, no rendering, no repetition beyond the three-run
  determinism check, and were measured with no other sweep running. They are not a frame budget.
- Break counts are observations of this discretisation and this law. No real-world glass, oak or
  iron ranking is implied, and iron's zero counts are a disabled model, not a prediction.
- No claim is made about *why* Jolt's spring lattice fails to converge at 24 iterations beyond the
  measured `solver_iterations` dependence; the internal constraint formulation was not audited.

---

## 12. Next gates

1. **Fix the at-rest instability first.** Add an at-rest regression suite — lattice, zero gravity,
   no contact, zero velocity, asserting `elastic_energy_j`, `mechanical_energy_j`,
   `linear_momentum_kg_m_s` and `broken_links` all stay at zero — across glass/oak/iron, both
   pinned and unpinned, at every admissible timestep and mesh. Section 8 gives the failing cases.
   No fracture result can be interpreted until this passes.
2. **Raise or justify the default `solver_iterations`.** 24 fails the at-rest test at 1/4800 s on
   every material; 128 passes it at (6,9,2) and still fails at (10,15,4). Either the default must
   move with a measured cost, or the network needs a solver that does not depend on iteration
   count this way.
3. **Close the timestep gap or bound the claim.** The schema floor of 1/4800 s is 315x above the
   engine's own requirement for the authored fixture. Either the network needs an internally
   substepped or implicit local solver that decouples the material clock from `fixed_dt_s`, or
   every fracture result must be labelled unresolved by a stated factor. The adaptive bisection
   (cap `dt/256`) is not sufficient: it only refines where damage already moved, so it cannot find
   fracture a coarse step never initiates.
4. **Publish the resolution factor with every fracture number.** `temporal_resolution.
   required_substeps` is already computed on every load and is free. Reporting it beside each
   break count would make the 3 146x gap visible at the point of use.
5. **Enable and test iron fracture, or stop reporting iron break counts.** `fracture_enabled:
   false` means the documented iron column carries no information.
6. **Document the cohesive mesh bound.** `L < 2*E*Gc/sigma_t^2` (59.3 mm for oak's stiff axis)
   should be reported at admission, not surfaced as `network cohesive law requires df greater
   than d0`.
7. **Add a continuous convergence metric to the acceptance gates.** Break counts are discrete and
   hide partial convergence; the striker rebound speed and the first-event time both behave
   better and one of them (event time) converges at near second order.

All 40 scorecard rows and every full-project gate remain open. Nothing in this checkpoint changes
engine behaviour.
