# Algorithm 1: a precomputed impulse-response library with Woodbury crack updates

Tested code: branch `agent/algo1-impulse-woodbury` in worktree
`C:/Users/henry/dev/banjo-agents/algo1-impulse`, based on `c38da39` with
`agent/integration` (`b3ae5aa`) merged. September 8, 2026, America/Los_Angeles.
Not pushed, not on main. Windows 11 Pro build 26200, MSVC 19.44, VS 2022 x64
Release, `-DBANJO_BUILD_LAB=OFF`, Intel Core Ultra 9 285K. Six OpenMP threads
(`--threads 6`, the default); other agents shared the machine, and the same run
took up to 20x longer while they were busy, so every timing below was taken on a
quiet machine and the repeat spread is stated.

Predecessors: the [engine options analysis](engine-options-analysis-2026-09-07.md)
that asked for this lane, and the [modal-lane checkpoint](fast-modal-checkpoint.md)
whose measured obstacle -- an `O(n k^2)` eigenvector update per broken bond --
this lane exists to remove.

## Headline

**The eigenvector update is gone and the cost it caused is gone with it. What
replaces it as the obstacle is the object, not the algorithm.**

On the shared scene -- a 250 x 200 x 10 mm glass plate of 10 mm cells (500 cells,
2,777 bonds) on two ledges, struck by a 60 mm iron ball dropped 2.0 m -- the lane
computes impact, fracture, hand-off and 2.0 s of settling in **2.67-2.89 s of
wall after a precompute that is cached**, which is **1.33-1.44x** of the
simulated interaction against the reference lane's **6.19x**. The precompute is
**1.00 s cold** and **0.36 s warm**, for a 14.4 MB cache file keyed by the plate
and not by the strike -- change the drop height or the strike point and it is
reused untouched. A crack round costs `O(n k) + O(k^2)`: the 64 rounds and 276
broken bonds of the default scene spend **0.25 s** in Woodbury updates, where the
modal lane spent 77-92% of its window on basis updates.

**Both lanes start the crack in the same cells, and on the one plate where this
model is well posed they break the same bond first.** On the 20 mm plate (two
cells through the thickness, 1,000 cells, zero mechanism modes) the reference's
single first failure is bond 4725, cell (12,0,9) to cell (12,1,9); this lane's
first failure is bonds 4725 and 5234, the two through-thickness bonds under the
ball. On the 10 mm plate both lanes fail at the two cells the ball touches; the
reference takes the two diagonal bonds there and this lane takes the six
axis-aligned ones, so the *sets* are disjoint while the *place* is identical.

**And on the default scene the answer is wrong, for a reason the report states
and the object owns.** A plate one cell thick at horizon 2 has every bond in its
mid-plane, so the linearised stiffness `K` has no out-of-plane entries at all:
340 of the plate's 1,340 free degrees of freedom have exactly zero stiffness.
They are not rigid-body modes; they are mechanisms. The lane detects and reports
them (`library.mechanism_modes`), carries them as the free flight the linear
equation `M u'' + K u = f` actually prescribes, and the shared criterion then
reads the second-order stretch that free flight produces. The result is 276
broken bonds and 28 pieces where the reference breaks 73 and keeps the plate
whole. **Algorithm 1 as specified cannot answer the default scene, and no
engineering inside it will change that: a one-cell-thick plate resists a
transverse load only through membrane tension, which is second order in
displacement and outside a linear basis by construction.**

Three things are **implemented and measured**: the library and its cache, the
screen, and the Woodbury cascade. Four things are **exact**: the intact modal
field, the first failure read from it, the Woodbury identity, and the screen's
bound. One thing is a **hypothesis, tested and not supported by these runs**:
that a released bond may be treated quasi-statically while the impact loading
stays dynamic. Nothing here is **validated** against laboratory data.

## Method

### What is precomputed, once, per object

`src/algo1/ImpulseLibrary.{hpp,cpp}`. Keyed by plate size, cell size, horizon,
support and material -- never by the strike.

1. **Mass-normalised eigenpairs.** `K phi_i = w_i^2 M phi_i` with
   `phi^T M phi = I` over the free degrees of freedom, from the same dense
   Householder/implicit-QL solver the modal lane uses
   (`src/modal/SymmetricEigen.cpp`, unchanged). Every mode is an independent
   oscillator with a closed form, so the elastic wave is never integrated and
   the sampling interval has no stability limit.
2. **Bond-mode amplitudes** `a(b,i) = g_b . phi_i / L_b`: one dense
   (bonds x modes) block, "how much mode i strains bond b". `g_b` is the bond's
   linearised extension gradient, six non-zero entries; an end the support holds
   contributes nothing, exactly as a clamped node contributes stiffness to its
   free end only.
3. **Compliance columns** `c_b = K^+ g_b` for every bond, formed as
   `C = (Z / w^2) phi^T` with `Z(b,i) = L_b a(b,i)`, in one blocked product.
   These are the `S D` columns of the Woodbury identity.

**A degree of freedom that no live bond gives any stiffness is separated out
before the eigensolve.** Its eigenpair is known exactly (`w = 0`,
`phi = e_d / sqrt(m_d)`), and handing several hundred identical zero eigenvalues
to implicit QL does not work: its deflation test is relative to
`|d_m| + |d_m+1|`, which is zero there, and the solver throws
`symmetric QL did not converge` on the default scene at 1,340 dofs. Separating
them is exact, removes the failure, and shrinks the decomposition from 1,340 to
1,000 columns for the default plate. The count is `library.mechanism_modes`.

The cache stores `w^2` and `phi` only; the two blocks are rebuilt on load, which
for the default scene costs 0.35 s against a 0.68 s decomposition.

### What happens at impact

`src/algo1/CrackCascade.{hpp,cpp}`.

**Contact.** Two models, both named in the report. `--contact tracked` (the
default) resolves frictionless normal contact against the *intact* plate once
per substep: free cells inside the ball's contact sphere (radius `R + h/2`, the
convention the modal and fast-lattice lanes both use) take impulses along their
own outward sphere normals from a projected Gauss-Seidel solve, with each cell's
response along the normal computed over its *free* axes only. Between substeps
the modal state advances in closed form. Impulses are recorded as events and the
cascade replays them, so contact is solved once and the cascade is a second pass
over the same timeline. `--contact impulse` delivers the whole two-mass momentum
transfer as one impulse at `t = 0` over the footprint the ball covers at half a
cell of penetration -- the literal reading of the algorithm, kept so its error
can be measured.

**Screen.** One (bonds x modes) product bounds *everything the shared criterion
reads*, not only the axial strain:

- the bond's own stretch, from `|axial| <= A` and `|Delta u| <= W`:
  `|stretch| <= (A + W^2 / (2 (L - A))) / L`;
- the nonlocal Green-Lagrange strain the criterion actually uses, through the
  node's rest covariance: `grad u = (sum_b w_b du_b x dx_b) R^-1`, so
  `||grad u|| <= (sum_b |du_b| / |dx_b|) ||R^-1||_F`, and the Green-Lagrange
  measure adds half its square.

Both are driven by a bound on each modal amplitude: `sqrt(q^2 + (qdot/w)^2)` for
an elastic mode, `|q| + |qdot| t` for a zero-frequency one -- which is why a
mechanism makes the bound grow linearly in time while a well-posed plate's bound
is constant. On a coarse time grid the screen gives the earliest instant at
which any bond can reach a threshold, and samples before it are never taken.
`banjo_algo1_tests` checks the bound against 1,500 samples of a swept impact and
finds it reached exactly (ratio 1.000) and never crossed.

**Cascade.** At each sample the intact modal field `u0 = phi q(t)` plus the
Woodbury correction from the bonds released so far is written into the lattice
and handed to `fracture/BondFailure` unchanged:

```
u = u0 + S D (Kappa^-1 - D^T S D)^-1 D^T u0
```

`S D` are the precomputed compliance columns, `D^T u0` is the extension each
released bond would have carried, and the `k x k` inverse is extended by
*bordering* when a bond breaks: `O(k^2)` per bond, `O(k^2 + n k)` per sample, and
no eigenvector is ever touched. Pieces are `findConnectedComponents` and go to
Jolt for flight and settling through the hand-off the modal lane established.

### Three guards the measurements forced

Each was a measured runaway, and each is reported per run:

| guard | what it caught |
|---|---|
| the cell's contact response counts only its *free* axes | a cell the ledge holds in y cannot move that way; pretending it can let the penetration recovery inject impulse without limit whenever the ball's footprint reached the supported strip -- the off-centre strike then broke all 2,777 bonds and removed 5.07 MJ |
| the penetration recovery is capped at 2% of the impact speed | the constraint already holds the approach velocity at zero, so the residue is one substep of closing and does not grow; recovering it at `penetration/dt` put 8.3 N.s into two cells and 269 J of removed bond energy against a 17 J ball |
| a release whose correction moves any dof by more than 2 cm is rolled back out of the correction, and the released set is capped at 512 bonds | the quasi-static correction diverges as the released set approaches a mechanism: measured, before the guard, as a 1.2 m correction with every bond in the plate broken inside one sample at t = 3.32 ms |

A bond dropped from the correction still breaks in the lattice and still cuts the
connectivity; it stops contributing a released force. The counts are
`window.singular_releases`, `window.capped_releases` and `window.released_bonds`
(211 of 276 carried on the default scene).

## Exact, hypothesis, wrong

**Exact.**

- *The intact response.* The modal evolution has no time step. An independent
  velocity-Verlet on the engine's own nonlinear bond forces agrees with the
  closed form to 1.9e-6 of the peak displacement and stops improving under
  refinement (dt 2.0e-8 -> 2.5e-9 s moves it from 2.36e-6 to 1.91e-6 relative);
  halving the motion halves that residual, which identifies what is left as the
  lattice's geometric nonlinearity and not a linear-algebra error.
- *The first failure*, in the sense that it is read from that exact field by the
  unchanged shared criterion. Whether it is the *right* first failure is section 4.
- *The Woodbury identity.* The corrected static field equals a direct solve of
  the lattice with the same bonds removed to 7e-15 relative, for one released
  bond and for five.
- *The screen's bound*, for the intact field, on a plate with a full spectrum and
  on one whose out-of-plane response is a mechanism.

**Hypothesis, and what testing it showed.** *Each released bond may be treated
quasi-statically while the impact loading stays dynamic.* The quasi-static limit
drops the dynamic amplification of a suddenly released force (up to 2x for a step
release) and has no notion of the release wave taking time to reach another bond.
On the well-posed 1,000-cell plate this lane breaks 2 bonds where the reference
breaks 6,869: the released force is applied instantly and everywhere, but
statically, and a static field an order of magnitude below the dynamic one does
not drive a crack forward. The hypothesis is not supported by these runs. It is
also not cleanly separable on the 500-cell scenes, where the correction is 0.25 s
of a 2.87 s window and the outcome is set by free flight instead.

**Wrong, and why.**

- *A plate one cell thick.* `K` has 340 zero-stiffness dofs of 1,340. The lane
  runs and reports them, but its answer on the default scene is driven by
  unopposed out-of-plane free flight, not by elasticity. It should refuse this
  object rather than answer it; it does not yet.
- *The contact impulse on such a plate.* With no transverse restoring force the
  ball barely feels the plate: 0.68 N.s delivered against the reference's
  3.85 N.s on the default scene, 1.07 against 8.92 at the higher drop. On the
  two-cell-thick plate, where the model is well posed, the lane delivers
  7.14 N.s against the reference's 5.57 N.s -- 28% high, and the right order.
- *The rigid ball on two cells.* With an even cell count across the width the
  ball first touches exactly two cells; on a stiff plate it bounces off those two
  before any others enter the contact sphere (`contact.cells_touched = 2` on both
  the 1,000- and 2,000-cell plates). The reference spreads the same momentum over
  13,000 substeps of a deforming lattice.
- *The screen's bound is rigorous and loose.* It sums `|a(b,i)|` over thousands
  of modes with no cancellation, so it overstates the reachable strain by 54x on
  the 1,000-cell plate, 20x on the 2,000-cell one, and 5,700x on the default
  scene (where the mechanisms' linear-in-time term dominates). It therefore
  shortlists 45-100% of the bonds and its earliest-failure time is 0 on every
  scene here. It still answers "can anything break at all" in one product, and
  that answer is free; it does not yet cut the sampling.
- *Piece counts.* 28-33 against the reference's 1 on the 500-cell scenes, 1
  against 207 on the 1,000-cell one. Neither lane's piece count is converged (the
  engine's own analysis says so), but these are not near-misses.

## Cost

### Precompute, once per object

| plate | cells | bonds | free dofs | mechanisms | decompose | amplitudes | compliance | cold total | warm total | cache bytes | compliance block |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 250 x 200 x 10 mm | 500 | 2,777 | 1,340 | 340 | 0.68 s | 0.010 s | 0.34 s | **1.00 s** | **0.36 s** | 14,391,699 | 29.8 MB, stored |
| 250 x 200 x 20 mm | 1,000 | 9,788 | 2,840 | 0 | 25.8 s | 0.059 s | 5.42 s | **31.28 s** | **5.52 s** | 64,581,699 | 222 MB, stored |
| 250 x 200 x 40 mm | 2,000 | 24,810 | 5,840 | 0 | 233.0 s | 0.32 s | -- | **233.6 s** | -- | 272,961,699 | 1.16 GB, on demand |

The decomposition is the dense solver's `O(n^3)` and dominates cold; the
compliance block is `bonds x dofs x modes` and is memory-bound. Warm reuse skips
the decomposition and rebuilds both blocks, which is why the 1,000-cell warm
precompute is still 5.5 s. Above `--compliance-mb` (1 GB by default) the block is
not stored and columns are computed on demand -- which is what the 2,000-cell
plate does, and it costs nothing there because **the cascade only ever reads the
columns of bonds that actually break**, six entries at a time. Precomputing all
of them, as the algorithm specifies, is convenient but not necessary.

### Per rerun, after the precompute

Default scene, three consecutive runs on a quiet machine: window 2.640 / 2.709 /
2.668 s, compute 2.660 / 2.728 / 2.689 s, ratio 1.329 / 1.363 / 1.343. Under load
from other agents the same run took up to 51.9 s; that is contention, not
variance in the algorithm.

| scene | cells | contact | screen | field | criterion | Woodbury | handoff + settle | **compute wall** | simulated | ratio | window ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| default | 500 | 0.92 s | 0.032 s | 1.52 s | 0.37 s | 0.25 s | 0.022 s | **2.89 s** | 2.002 s | 1.44 | 478x |
| drop 5.0 m | 500 | 0.86 s | 0.031 s | 0.97 s | 0.26 s | 0.19 s | 0.020 s | **2.17 s** | 2.000 s | 1.09 | 479x |
| offset (60, 40) mm | 500 | 0.78 s | 0.028 s | 1.34 s | 0.35 s | 0.23 s | 0.017 s | **2.54 s** | 2.002 s | 1.27 | 420x |
| 20 mm thick | 1,000 | 0.28 s | 0.19 s | 2.12 s | 0.70 s | 0.010 s | 0.006 s | **3.32 s** | 2.002 s | 1.66 | 1,640x |
| 40 mm thick | 2,000 | 0.48 s | 0.95 s | 27.16 s | 5.00 s | 0.00 s | 0.009 s | **33.69 s** | 2.002 s | 16.8 | 5,613x |

`field` is `u = phi q` at every sample: a dense `n x m` product that reads the
whole basis -- 14 MB at 500 cells, 64 MB at 1,000, 273 MB at 2,000. At 2,000
cells it runs at 60 GB/s, which is this machine's DRAM bandwidth, so it is
memory-bound and it is the lane's cost floor. **The honest asymptotic statement
is that the modal field costs `O(n^2)` per sample where an explicit lattice costs
`O(n)` per substep.** The lane wins at 500 and 1,000 cells because it takes 6,000
samples against 13,626-198,000 substeps *and* because a dense product is two
orders of magnitude more efficient per operation than a Gauss-Seidel sweep; at
2,000 cells the `n^2` catches up and the rule is missed by 15x.

The 2,000-cell run also shows the screen's weakness at its clearest: nothing
breaks at all (peak stretch 3.76e-4 against a 1.29e-3 threshold), the screen
knows only that the bound is 19.6x the threshold, and the lane pays 33.7 s to
discover that nothing happens. A tight screen would have answered in 0.95 s.

## Accuracy against the reference

Reference: the explicit lattice, `fastlattice` CPU backend, double precision, run
from the same executable with `--reference` so both lanes are built from one set
of numbers. Same material route (`makeReferenceMaterial(Glass, 971)` ->
`compileElasticLatticeReference` -> `withStrengthDerivedFailure`), same lattice
generator rules, same bond order, same ledges, same criterion.

| scene | lane | first failure | broken | rounds | pieces | largest piece | removed J | contact N.s | wall | simulated | ratio |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| default | algo 1 | 0.456 ms, 6 bonds | 276 | 64 | 28 | 462 cells | 8.67 | 0.68 | 2.89 s | 2.002 s | 1.44 |
| default | reference | 0.655 ms, 2 bonds | 73 | 63 | 1 | 500 cells | 2.15 | 3.85 | 2.05 s | 0.330 s | 6.19 |
| drop 5.0 m | algo 1 | 0.288 ms, 2 bonds | 281 | 66 | 33 | 462 cells | 9.41 | 1.07 | 2.17 s | 2.000 s | 1.09 |
| drop 5.0 m | reference | 0.279 ms, 1 bond | 315 | 307 | 1 | 500 cells | 9.27 | 8.92 | 5.33 s | 0.505 s | 10.6 |
| offset (60, 40) mm | algo 1 | 0.456 ms, 6 bonds | 275 | 182 | 30 | 464 cells | 8.67 | 1.78 | 2.54 s | 2.002 s | 1.27 |
| offset (60, 40) mm | reference | 0.665 ms, 1 bond | 120 | 113 | 1 | 500 cells | 3.54 | 6.07 | 3.56 s | 0.370 s | 9.61 |
| 20 mm thick | algo 1 | 0.517 ms, 2 bonds | 2 | 1 | 1 | 1,000 cells | 0.042 | 7.14 | 3.32 s | 2.002 s | 1.66 |
| 20 mm thick | reference | 0.401 ms, 1 bond | 6,869 | 3,735 | 207 | 256 cells | 1.79 | 5.57 | 86.6 s | 2.200 s | 39.4 |
| 40 mm thick | algo 1 | none | 0 | 0 | 1 | 2,000 cells | 0.00 | 5.88 | 33.7 s | 2.002 s | 16.8 |

### The first-failure sets, cell by cell

The strike lands between cells (12,0,9) and (12,0,10) -- 25 cells across x puts a
cell on the axis, 20 across z straddles it, so the ball touches exactly two.

| scene | this lane | reference | shared |
|---|---|---|---:|
| default | bonds 1234, 1370, 1376, 1515, 1521, 1524: the six axis-aligned bonds out of (12,0,9) and (12,0,10) | bonds 1239, 1525: the two *diagonal* bonds at the same two cells | 0 of 6 |
| drop 5.0 m | 1234, 1524 | 1376 = (12,0,9)-(13,0,9), which is in this lane's default set | 0 of 2 |
| offset (60,40) mm | 1850, 1986, 1992, 2131, 2137, 2140 | 2137 | 1 of 6 |
| 20 mm thick | 4725 = (12,0,9)-(12,1,9) and 5234 = (12,0,10)-(12,1,10), the two through-thickness bonds under the ball | 4725 | 1 of 2 |

Set agreement is 0-50% by Jaccard and 100% by *place*: every first failure in
either lane, on every scene, is a bond at one of the two struck cells. On the
one plate where the linear model is well posed the reference's single first
failure is one of this lane's two. Which bond at those cells goes first is
decided by the difference between a strain field the linear basis produces and
one a 1.01 us Gauss-Seidel lattice produces, and the two disagree on whether the
diagonals or the axis bonds carry more.

### What agrees and what does not

- **First-failure time** agrees to 3% at the higher drop (0.288 vs 0.279 ms) and
  to 29% on the default scene (0.456 vs 0.655 ms); 0.517 vs 0.401 ms on the
  well-posed plate. The reference steps at 1.01 us and this lane samples the
  criterion at 1.00 us, so they are compared at the same resolution.
- **Removed energy** agrees to 1.5% at the higher drop (9.41 vs 9.27 J), the one
  place where the two lanes measure the same event. It is 4x apart on the default
  scene and 40x apart at 1,000 cells.
- **Broken bonds** agree to 11% at the higher drop and disagree by 3.8x, 2.3x and
  3,400x elsewhere.
- **Pieces** never agree.

The higher-drop row is the informative one: when the impact is violent enough
that the *in-plane* response dominates -- the part a linear basis on a
one-cell-thick plate can represent -- this lane lands on the reference's answer
for the two quantities the engine's convergence study says do converge (removed
energy, and broken-bond count within its spread). When the impact is gentle
enough that the plate's *bending* carries it, this lane has nothing to carry it
with.

### The two contact models, measured against each other

The same default scene, the same library, the two models the report names:

| contact model | impulse delivered | broken | pieces | removed J | window wall | ratio |
|---|---:|---:|---:|---:|---:|---:|
| `tracked` (per substep, intact plate) | 0.68 N.s | 276 | 28 | 8.67 | 2.87 s | 1.44 |
| `impulse` (one impulse at t = 0) | 3.26 N.s | 0 | 1 | 0.00 | 1.48 s | 0.91 |
| reference (explicit, per substep) | 3.85 N.s | 73 | 1 | 2.15 | -- | 6.19 |

The single-impulse model -- the literal reading of the algorithm -- gets the
*momentum* right to 15% of the reference and the *fracture* completely wrong: it
delivers everything at t = 0 into the footprint, which on a plate with no
transverse stiffness produces a uniform downward kick that strains nothing, and
nothing breaks. The tracked model gets the fracture qualitatively (a punched
hole) and the momentum 5.7x low, because a plate that cannot push back cannot
take momentum. Neither is right; they are wrong in opposite directions, and the
difference between them is a measure of how much of this scene is outside the
model.

## Materials

Glass, oak and iron on the 250 x 200 x 20 mm plate (the well-posed one), 10 mm
cells, ledges, 60 mm iron ball from 2.0 m, both lanes, identical in every other
respect:

| material | lane | first failure | broken | pieces | removed J | contact N.s | wall |
|---|---|---|---:|---:|---:|---:|---:|
| glass | algo 1 | 0.517 ms | 2 | 1 | 0.042 | 7.14 | 3.26 s |
| glass | reference | 0.401 ms | 6,869 | 207 | 1.79 | 5.57 | 88.4 s |
| oak | algo 1 | none | 0 | 1 | 0.00 | 6.93 | 8.72 s |
| oak | reference | 0.985 ms | 89 | 2 | 0.70 | -- | 6.91 s |
| iron | algo 1 | none | 0 | 1 | 0.00 | 7.16 | 8.41 s |
| iron | reference | none | 0 | 1 | 0.00 | -- | 15.6 s |

The lanes agree on iron: neither breaks it. **That agreement is not a material
result, and this lane cannot produce one for iron.** A linear modal basis cannot
represent plasticity at all: iron's response past yield is history-dependent and
irreversible, and a fixed eigenbasis of a linear elastic operator has neither.
Oak's grain and rate dependence are equally outside it, and the engine's own oak
is an isotropic strength-derived surface with no grain, so the oak row compares
two solvers of the same wrong model. What the rows do show is that the lane's
contact impulse is insensitive to the plate material (6.93-7.16 N.s across a 3x
range of stiffness), which is what a rigid ball bouncing off two cells should
look like and is another reading of the contact-patch problem.

## What to do next, in the order the measurements support

1. **Refuse a mechanism, or price it.** The lane should exit non-zero on a plate
   whose library has mechanism modes, with the reason it already computes, and
   the Fracture lab should say "use at least two cells through the thickness".
   The measurement justifying it is in this note; the change is ten lines.
2. **Halve the field cost.** `u = phi q` is memory-bound on a 14-273 MB basis. A
   single-precision copy of `phi` used only for the field evaluation halves the
   traffic; the displacement error is ~1e-12 m against bond extensions of ~1e-5 m,
   so the criterion cannot see it. Estimated: the default window from 2.7 s to
   1.8 s, the 2,000-cell one from 33.7 s to 19 s.
3. **Make the screen tight enough to cut sampling.** The absolute-value mode sum
   is 20-5,700x loose. Bounding `|q_i(t)|` per mode over a *short* interval and
   re-screening per interval, or grouping modes by frequency band and using the
   phase, would give a per-bond `headroom / rate` and therefore a sample interval
   that provably cannot miss a failure. That is what would make the 2,000-cell
   "nothing breaks" answer cost 1 s instead of 34 s.
4. **Test the quasi-static release properly** on a well-posed plate: compare one
   released bond's effect against the reference's own field a few microseconds
   later. The 2-bond result at 1,000 cells says the release under-drives the
   cascade; it does not say by how much, or whether a dynamic release closes the
   gap.
5. Only then, the contact patch. Two cells taking a ball's whole momentum is the
   weakest part of the impact model in both lanes.

## Verification

`python scripts/check-source-registration.py`: OK (207 sources, 207 registered).
`ctest -C Release` with the five long suites excluded by instruction: **87 of 87
passed in 81 s**, including the new `banjo_algo1_tests`. No existing test's
tolerance was changed, and no shared criterion, solver or reference lane was
modified: `fracture/BondFailure`, `modal/SymmetricEigen` and
`fastlattice/TileImpactScene` are untouched.

`banjo_algo1_tests` output:

```
  explicit lattice dt=2e-08   max |u_explicit - u_modal| = 4.58e-12  (relative 2.36e-06)
  explicit lattice dt=2.5e-09 max |u_explicit - u_modal| = 3.72e-12  (relative 1.91e-06)
  amplitude 0.5 m/s: relative residual 1.91e-06
  amplitude 0.125 m/s: relative residual 4.84e-07
[PASS] the intact modal field is what an explicit lattice converges to
  released 1 bonds: max |u_woodbury - u_direct| = 9.72e-24 on a field of 1.26e-09 (relative 7.69e-15)
  released 5 bonds: max |u_woodbury - u_direct| = 1.00e-23 on a field of 1.37e-09 (relative 7.30e-15)
[PASS] the Woodbury-corrected static field equals a direct solve with the bonds removed
  clamped 5x2x5, full spectrum: 1500 samples, tightest bond reached 0.192 of its bound
  ledges 7x1x5, out-of-plane mechanism: 1500 samples, tightest bond reached 1.000 of its bound
[PASS] the screen's bound is never violated by sampling
```

The Fracture lab panel was driven end to end on a private playground
(`python playground/server.py --port 8801 --engine build/agent/Release/banjo_platform_cli.exe
--runs build/playground-runs`, stopped afterwards): the panel offers this lane as
built, runs it on the default scene through the CLI contract in
`playground/fracture_lab.py` unchanged, and reports `500 cells in 2.958 s wall,
1.11x of the simulated interaction (limit 1.1x)` with 276 broken bonds, 28
components and a cached precompute -- the same numbers this note reports, through
the panel the owner will use.

### Reproduction

```powershell
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 6
ctest --test-dir build/agent -C Release -E "banjo_network_skin_tests|banjo_network_runtime_tests|banjo_material_showcase_tests|banjo_network_adaptive_tests|banjo_contact_capacity_tests"

$exe = "./build/agent/Release/banjo_fracture_algo1.exe"

# The default scene, this lane and the reference on identical geometry
& $exe --plate 0.25 0.20 0.01 --cell 0.01 --ball 0.06 --drop 2.0 --offset 0 0 `
       --support ledges --duration 2.0 --output build/runs/a1-default.json
& $exe --reference --plate 0.25 0.20 0.01 --cell 0.01 --ball 0.06 --drop 2.0 --offset 0 0 `
       --support ledges --duration 2.0 --output build/runs/ref-default.json

# Variations. The first two reuse the library; only the third rebuilds it.
& $exe --plate 0.25 0.20 0.01 --cell 0.01 --ball 0.06 --drop 5.0 --support ledges --duration 2.0 --output build/runs/a1-drop5.json
& $exe --plate 0.25 0.20 0.01 --cell 0.01 --ball 0.06 --drop 2.0 --offset 0.06 0.04 --support ledges --duration 2.0 --output build/runs/a1-offset.json
& $exe --plate 0.25 0.20 0.02 --cell 0.01 --ball 0.06 --drop 2.0 --support ledges --duration 2.0 --output build/runs/a1-thick.json
& $exe --plate 0.25 0.20 0.04 --cell 0.01 --ball 0.06 --drop 2.0 --support ledges --duration 2.0 --output build/runs/a1-2000.json   # 4.5 min, 233 s of it precompute

# The single-impulse contact model, and a cold precompute
& $exe --plate 0.25 0.20 0.01 --cell 0.01 --ball 0.06 --drop 2.0 --contact impulse --support ledges --duration 2.0
& $exe --plate 0.25 0.20 0.01 --cell 0.01 --ball 0.06 --drop 2.0 --support ledges --duration 2.0 --no-cache

# The clamped support (perimeter ring of cells held in every axis), for comparison
& $exe --plate 0.25 0.20 0.02 --cell 0.01 --ball 0.06 --drop 2.0 --support clamped --duration 2.0

# Watch any of them
python scripts/import-playback.py --runs C:/Users/henry/dev/banjo/build/playground-runs `
    --name "Algo 1" --name "Reference" build/runs/a1-default.json build/runs/ref-default.json
# or through the Fracture lab panel: python playground/server.py --runs build/playground-runs
```

The Fracture lab panel calls the same executable with the same contract
(`playground/fracture_lab.py`, lane `algo1`), so changing the plate or the drop
height in the browser reruns exactly these commands.

### Registered in the owner's playground store

`C:\Users\henry\dev\banjo\build\playground-runs`, served by the owner's running
playground on port 8765:

| job | cases |
|---|---|
| http://127.0.0.1:8765/?job=3c03fd6af1234a61890c248918056890 | the default scene, this lane and the reference |
| http://127.0.0.1:8765/?job=4e8e0a6c49654786b9cf8e5c38112719 | drop 5.0 m and the off-centre strike, both lanes |
| http://127.0.0.1:8765/?job=1de22e8b1fb34f35b9341573cecacf89 | the 20 mm plate (two cells thick), both lanes |

The first was opened in a browser and played through to frame 207/207 at
t = 2.0018 s: the ball punches a hole through the plate, the plate stays on its
ledges, and the fragments fall to the ground and stop.
