# Fracture from a precomputed basis (the modal lane)

Tested code: branch `agent/fast-modal` in worktree `C:/Users/henry/dev/banjo-agents/fast-modal`, based on `f7c4dc3` with `agent/playground-rebuild` (`641e658`) merged. September 7, 2026, America/Los_Angeles. Not pushed, not on main. Windows 11 Pro build 26200, MSVC 19.44, VS 2022 x64 Release, `-DBANJO_BUILD_LAB=OFF`, Intel Core Ultra 9 285K (24 cores). Serial unless a thread count is stated; other agents' jobs shared the machine, so wall times carry a few percent of noise and are quoted with the conditions they were taken under.

Predecessors: the [implicit-lane fracture checkpoint](implicit-fracture-checkpoint.md) (the reference this lane is compared against), the [realtime envelope](../../envelope/docs/realtime-envelope-checkpoint.md) that put 1x realtime at 365 nodes for the implicit lane, and the owner's goal in [goal-realtime-fracture](goal-realtime-fracture.md).

## Headline

**The rule is met on the smallest honest scene, and it is met for a reason that does not scale.** A clamped 8x8x2 tile of 20 mm glass cells struck by a 20 mm iron ball at 16 m/s, computed from impact through the fracture cascade, hand-off of the pieces to Jolt and 8 s of falling and settling, runs at **0.14x** of realtime on this lane (1.12 s of compute for 8.0 s of interaction; 0.09x when the settle window is extended to 12 s) and **0.12x** on the implicit reference (0.76 s for 6.2 s, at rest from 5.9 s) (section 4.3). Both are inside the owner's 1.1x. The fracture window itself is 400-500x slower than realtime in both lanes; the rule is met because a 2 ms fracture window is a small part of a multi-second interaction and Jolt settles the pieces at 0.01x. At 12x12x2 (600 free degrees of freedom, 20 m/s, a 1,733-bond cascade) the same interaction through 8 s runs at **1.94x** on this lane (15.5 s of compute, 13.8 s of it basis updates) and fails the rule by 1.8x, while the implicit reference still meets it at **0.51x** (4.1 s) (section 4.3). The single biggest obstacle is the exact rank-one eigenvector update: it is exact to roundoff across the whole cascade, and it costs O(n·k²) per broken bond (0.9 ms per bond at 216 degrees of freedom, 8-9 ms at 600), so it dominates as soon as more than a few dozen bonds break on anything larger than the smallest tile.

Three things are **implemented and measured**:

- The basis is exact and stays exact. Built once from the lattice's own stiffness and mass, it satisfies `K phi = omega^2 M phi` to 1e-13 relative; after every round of a 39-round, 214-bond cascade the rank-one-updated basis still satisfies the reduced lattice to 4.5e-15, stays M-orthonormal to 1.1e-14 and matches a fresh decomposition's spectrum to 3.5e-15. Updating and recomputing produce the identical cascade, bond for bond and time for time. The energy ledger of the modal phase closes to 1e-13 J.
- The first crack is deterministic and shared. On every scene, speed and step tried, both lanes name the same first failing bonds at the same sample (Jaccard 1.0), and at 12 m/s on 8x8x2 both lanes converge under refinement to the identical outcome: four bonds, nothing else, no cascade.
- The cascade is reproduced only as well as the reference reproduces itself. Above the fracture threshold, broken-bond counts agree between lanes to 10-25% and within each lane's own 3-15% refinement spread; piece counts converge in neither lane; near the threshold the outcome is a knife-edge that a 2 µm, 1.5 m/s difference flips from 10 bonds to 1,671.

Two things are **negative results**, stated so they are not tried again:

- A truncated (low-rank) basis does not carry the cascade. Keeping 75% of the modes reproduces the first crack and then breaks 106 of the 922 bonds the exact basis breaks; 50% breaks 30.
- Any sampling coarser than about half the lattice's own fastest period produces a spurious cascade in *both* lanes: at 12 m/s the reference at dt = 1e-6 breaks 871 bonds into 25 pieces; at 5e-7 and 2.5e-7 it breaks 4. The modal lane does the same at 2e-6 and 1e-6. The elastic evolution of the modal lane has no step; its criterion sampling and its contact capture do, and those set its resolution requirement at the same place as the reference's.

Nothing here is **validated** against laboratory data, and the implicit checkpoint's caveats stand: no Gc calibration, no friction in the fracture window, no fragment-fragment contact until the hand-off, and the oak and iron thresholds are a strength-derived isotropic surface with no grain, plasticity or rate dependence.

## Method

### What the lane computes

`src/modal/ModalBasis.{hpp,cpp}` assembles the linearised stiffness of the live bonds about the reference configuration, restricted to the free nodes (clamped nodes are removed from the system; a bond to a clamped node contributes stiffness to its free end only), mass-scales it, and diagonalises it with a dense Householder/implicit-QL solver in `src/modal/SymmetricEigen.{hpp,cpp}`. The result is `phi` with `phi^T M phi = I` and one `omega^2` per column. Every mode is then an independent oscillator with a closed form, so `src/modal/ModalFracture.{hpp,cpp}` never integrates the elastic wave: it advances the modal amplitudes exactly over a sampling interval, evaluates the displacement field `u = phi q` at the sample, writes it into the `ActiveMatter` positions, and hands those positions to the unchanged shared criterion (`fracture/BondFailure`: `resetBondStrainPeaks`, `accumulateBondStrainPeaks`, `applyBondFailure`) at both interval ends, exactly as `physics/FractureStep` does. A failing interval is discarded, the failed bonds are removed at its start with `removeBondsAtCurrentState` (StepRestart semantics), and the interval is re-tried against the new topology until it carries no failure. Pieces are `findConnectedComponents`.

The ball is coupled by frictionless normal contact against the free nodes, resolved once per sampling interval: an impulse applied at the interval midpoint, sized with the basis's own impulse response over the remaining half interval (`G(δ) = Σ sin(ω δ)/ω · phi phi^T`), puts each penetrating node on the sphere surface at the interval end. The midpoint placement reproduces the reference's midpoint-rule contact, in which a captured node leaves with twice the closing speed (an elastic capture); an impulse at the interval start gives an inelastic capture and is kept as an option (`--contact-midpoint 0`). Nodes pushed into the sphere by other nodes' impulses are admitted in outer passes until no free node ends the interval inside the sphere; the lane audits every free node at every accepted interval end and reports violations (zero in every run below).

The contact sphere holds a node (a cell centre) at `R + h/2`, so the ball touches a cell face, not its centre. That convention is applied identically to both lanes. The ball's true radius is what is rendered.

### The basis update

Removing bond `b` subtracts `k_b g_b g_b^T` from the stiffness, a rank-one downdate. In the eigenbasis it is `Λ - k_b z z^T` with `z = phi^T g_b`, which needs only the six rows of `phi` the bond touches. `updateRankOne` in `SymmetricEigen.cpp` solves it the classical way: deflation of components that cannot change the decomposition at working precision (linear in `|z_i|`, as LAPACK's `dlaed2` does; a test on the diagonal term alone admits a `sqrt(eps)` backward error, measured as a 2.5e-8 residual before it was corrected) and of nearly equal eigenvalues (a rotation that also rotates the stored eigenvectors and every carried modal state), Bunch-Nielsen-Sorensen's secular equation for the eigenvalues with each root stored as an offset from the nearer interval end so it keeps full relative accuracy, Gu & Eisenstat's reformulation that recomputes the perturbation vector from the computed roots (Loewner's formula) so the eigenvectors are orthonormal to working precision, and one dense product `phi[:, retained] · V` of cost `2 n k²` for the `k` retained (non-deflated) modes. Modal states `q`, `q̇` and the modal gravity force are rotated by the same `V`, so the physical state is unchanged by the change of basis (the test checks this to 1e-18 m).

`k` is the number of modes with non-negligible amplitude on the bond's two nodes. While the tile is one piece that is nearly all of them; as it fragments, modes localise and `k` falls: on 8x8x2 the mean retained count per update falls from 195 of 216 in the first quarter of the cascade (2 pieces) to 47 in the last quarter (40 pieces); on 12x12x2 from 524 of 600 to 304 (10 to 54 pieces). Deflation is therefore real but it arrives late, after the expensive part of the cascade.

### Papers actually used

- J. R. Bunch, C. P. Nielsen, D. C. Sorensen, "Rank-one modification of the symmetric eigenproblem," Numer. Math. 31 (1978): the secular equation and interlacing used for the eigenvalues.
- M. Gu, S. C. Eisenstat, "A stable and efficient algorithm for the rank-one modification of the symmetric eigenproblem," SIAM J. Matrix Anal. Appl. 15(4) (1994): the Loewner reformulation used for the eigenvectors; the same paper notes the fast multipole method reduces the eigenvector product to O(n log n) per row, which this lane does not implement.
- N. Jakovčević Stor, I. Slapničar, J. L. Barlow, "Forward stable eigenvalue decomposition of rank-one modifications of diagonal matrices," Linear Algebra Appl. 487 (2015): consulted for the forward-stable formulation; not implemented.
- E. Glondu, M. Marchal, G. Dumont, "Real-time simulation of brittle fracture using modal analysis," IEEE TVCG 19(2) (2013): the closest prior art (modal response to an impact drives fracture initiation, propagation by a separate heuristic). This lane keeps the engine's own criterion instead of a heuristic and updates the basis through the cascade rather than stopping at initiation.
- S. Sellán, J. Luong, L. Mattos Da Silva, A. Ramakrishnan, Y. Yang, A. Jacobson, "Breaking Good: Fracture Modes for Realtime Destruction," ACM TOG 42(1) (2023): precomputed *fracture* modes from a sparsified eigenproblem, onto which an impact is projected with no runtime crack simulation. Read as the current state of the art for precomputation; not adopted, because the owner's constraint is that pieces must come from the shared strain criterion, not from a precomputed pattern.
- Pentland & Williams (1989), James & Pai "DyRT" (2002), Hauser, Shen & O'Brien (2003), Barbič & James (2005), Müller et al. (2001): the closed-form modal evolution and impulse response are theirs. Craig & Bampton (1968) component-mode synthesis was the planned fallback for per-region bases; it was not needed to answer the research question and was not built.

### What is on the branch

| Item | Where |
|---|---|
| Dense symmetric eigensolver and rank-one update | `src/modal/SymmetricEigen.{hpp,cpp}`, `src/modal/DenseMatrix.hpp` |
| Basis over free nodes, downdate, rebuild, projections | `src/modal/ModalBasis.{hpp,cpp}` |
| The lane: contact, sampling, criterion, cascade, ledger, frames | `src/modal/ModalFracture.{hpp,cpp}` |
| Uniform-cube box lattice sharing `generateSphereLattice`'s bond rules | `generateBoxLattice` in `src/matter/Lattice.{hpp,cpp}` |
| Tool: scene, either lane, Jolt hand-off, `banjo.playback.v1` recording, timings | `tools/modal_fracture_record.cpp` → `banjo_modal_fracture_record` |
| Comparison driver (ladders, sizes, materials, truncation, headline) | `scripts/modal-fracture-compare.py` |
| Import a recording as a playground job | `scripts/import-playback.py` |
| Tests | `tests/modal_eigen_tests.cpp`, `tests/modal_fracture_tests.cpp` |

`banjo_modal` is its own CMake library (OpenMP for the dense products, `/arch:AVX2` on MSVC) so neither flag leaks into `banjo_core`. `python scripts/check-source-registration.py` passes.

## Conditions

Scene: a box lattice of `W x D x T` cubic cells of 20 mm, horizon 2 (the sphere lattice's bond rules, so 16 bonds per interior node), centred at 0.3 m height, its perimeter ring of cells fixed in every layer ("clamped"). Node masses are uniform (0.02 kg for glass), so the 27:1 surface-mass artefact of the sampled sphere does not occur. An iron ball of radius 20 mm (0.264 kg) is placed on the tile's axis so that its nearest free node is 1 mm outside the contact radius and given the impact speed downward. Gravity is off during the fracture window (2 ms) in both lanes and on (9.81 m/s²) during settling; over 2 ms it would move the ball by 0.02 m/s and strain the tile by 1e-7. Materials are the reference catalog's glass, oak and iron through `compileElasticLatticeReference` + `withStrengthDerivedFailure`, thresholds as in the implicit checkpoint's table.

The reference lane is `tryFracturingStep` (StepRestart, unchanged budgets) with the ball as its `CoupledSphereState`. It has no clamp, so the fixed nodes are given 1e9 times their mass. That works, with a cost: the reference's momentum and penetration audits become sensitive, and on the 12x12x2 tile it rejects `dt = 1e-6` on its 72nd step with a residual penetration of 1.32e-10 m against its 1e-10 m tolerance; `dt ≤ 5e-7` completes. On 8x8x2 `dt = 1e-6` completes. Nothing in the reference was changed.

The box lattice's fastest mode has period 12.2 µs on 8x8x2 (uniform masses; the sampled sphere's 27:1 mass spread is what made its period 4.6 µs), so its explicit-integration limit is 3.9 µs and `5e-7` is eight times below it.

Reproduction commands are at the end.

## 1. The basis is exact, and stays exact through the cascade

`banjo_modal_eigen_tests`: random symmetric matrices to n = 150 have residual `|A v − λ v| / |λ|max < 1e-13` and orthonormality defect `< 1e-12`; a rank-one update or downdate matches a fresh decomposition of the explicitly modified matrix to 1e-11 relative in every eigenvalue, with residual `< 1e-12`; a two-node perturbation of a block-diagonal matrix deflates all but 3 of 48 modes; sixty sequential bond downdates of a 2-D spring chain end with orthogonality 1.1e-14, residual 3.2e-15 and eigenvalue error 3.1e-15.

`banjo_modal_fracture_tests` on the engine's lattice: the basis residual against `assembleScaledStiffness` is `< 1e-12` clamped and free, with 0 and 6 rigid modes respectively; the fastest mode is bounded by `measureLatticeResolutionLimit`'s estimate; three downdates equal a rebuild to 1e-10 relative and carry a modal state to the same displacement to 1e-18 m. On a 6x6x2 glass tile struck at 14 m/s with `check_basis` on, 39 rounds removed 214 bonds and after every round the updated basis had residual ≤ 4.5e-15, orthogonality ≤ 1.1e-14 and spectrum error ≤ 3.5e-15 against a fresh decomposition; the ledger residual was −1.4e-13 J. Update and recompute modes produced 28 identical rounds (194 bonds) at identical times.

**So the answer to the research question's first half is yes: an exact rank-one basis update holds accuracy across the cascade, to roundoff, with no drift over hundreds of updates.** The question that remains is cost, in section 4.

## 2. The closed form is what the reference converges to

`tests/modal_fracture_tests.cpp`, `closedFormAgreesWithTheImplicitReference`: the same 5x5x2 lattice, the same authored velocity field, 4 µs of free vibration. The reference's maximum displacement error against the closed form is 5.1e-10, 1.3e-10 and 3.4e-11 m at `dt` = 5e-7, 2.5e-7 and 1.25e-7 (peak displacement 1.94e-6 m): a factor 3.9 and 3.8 per halving, second-order convergence *toward* the modal solution. That reproduces in C++ the numpy result the brief cited (1.49% → 0.64% → 0.17%) on the engine's own lattice.

`sharedCriterionNamesTheSameBonds`: a uniformly strained 4x2x4 tile at 1.5x the break strain; the modal lane's criterion call and `tryFracturingStep` name the identical failing bonds for glass (40 of 216), oak (136) and iron (40).

## 3. Accuracy against the reference

### 3.1 First failure: identical everywhere

In every run below, both lanes name the same first failing bonds at the same sample. 8x8x2: 4 bonds at 1.07-1.08e-4 s for 12 m/s, at 9.35-9.40e-5 s for 14 m/s, 7.25-7.33e-5 s for 16 m/s, 5.80-5.85e-5 s for 20 m/s; 12x12x2: 6 bonds at 7.25-7.33e-5 s for 16 m/s. Stage D of the goal is met exactly.

### 3.2 At the threshold the outcome converges, and coarse sampling fabricates a cascade in both lanes

8x8x2, glass, 12 m/s, 2 ms window (`scripts/modal-fracture-compare.py ladder`):

| lane, step | first failure | rounds | broken | pieces | largest | removed J | window wall | vs finest reference: J(first) / J(final) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| implicit dt = 1e-6 | 1.070e-4 (12 bonds) | 52 | 871 | 25 | 86 | 9.78 | 0.44 s | 0.33 / 0.00 |
| implicit dt = 5e-7 | 1.070e-4 (4) | 1 | 4 | 1 | 128 | 0.019 | 1.10 s | 1.00 / 1.00 |
| implicit dt = 2.5e-7 | 1.080e-4 (4) | 1 | 4 | 1 | 128 | 0.012 | 2.04 s | 1.00 / 1.00 |
| modal δ = 2e-6 | 1.060e-4 (4) | 177 | 801 | 10 | 106 | 19.8 | 0.89 s | 1.00 / 0.00 |
| modal δ = 1e-6 | 1.060e-4 (4) | 78 | 337 | 5 | 124 | 8.92 | 0.58 s | 1.00 / 0.01 |
| modal δ = 5e-7 | 1.075e-4 (4) | 1 | 4 | 1 | 128 | 0.004 | 0.27 s | 1.00 / 1.00 |
| modal δ = 2.5e-7 | 1.080e-4 (4) | 1 | 4 | 1 | 128 | 0.011 | 0.51 s | 1.00 / 1.00 |

The converged answer at 12 m/s is "four bonds break and the tile holds", and both lanes reach it. The reference's own refinement spread at this speed is 871 bonds to 4; every cascade above `5e-7` is a discretisation artefact, on either lane. The modal lane's elastic evolution has no step, but its contact capture and its criterion sampling do, and at the same interval they make the same mistake the reference makes.

### 3.3 Above the threshold both lanes shatter; counts agree, pieces do not

8x8x2, glass, 2 ms window, both lanes at both fine steps:

| speed | step | modal: rounds / broken / pieces / largest | implicit: rounds / broken / pieces / largest | contact loss J modal / implicit | removed J modal / implicit |
|---:|---:|---|---|---|---|
| 14 | 5e-7 | 208 / 875 / 13 / 87 | 49 / 688 / 7 / 112 | 6.52 / 6.48 | 26.1 / 11.2 |
| 14 | 2.5e-7 | 84 / 852 / 16 / 96 | 95 / 746 / 12 / 86 | 4.94 / 4.94 | 46.7 / 10.3 |
| 16 | 5e-7 | 476 / 918 / 40 / 71 | 209 / 790 / 3 / 126 | 8.56 / 9.26 | 40.5 / 12.3 |
| 16 | 2.5e-7 | 168 / 790 / 14 / 93 | 91 / 687 / 7 / 88 | 8.65 / 8.70 | 25.1 / 13.4 |
| 20 | 5e-7 | 178 / 909 / 45 / 59 | 65 / 821 / 15 / 88 | 14.22 / 14.31 | 43.5 / 22.9 |
| 20 | 2.5e-7 | 189 / 944 / 51 / 56 | 133 / 859 / 16 / 93 | 12.48 / 12.49 | 44.1 / 22.4 |

Broken-bond counts differ between lanes by 10-27% at matched step and by 3-15% within each lane between steps; the reference's own spread is the yardstick and the lanes sit at or just outside it. The contact energy loss agrees to 1-8%, which says the two contact treatments do the same physics. Piece counts do not converge in either lane (the reference goes 3 → 7 at 16 m/s under halving; the modal lane 40 → 14), reproducing the implicit checkpoint's finding. Two lane differences are unexplained and recorded: the modal lane removes 2-4x more stored bond energy per cascade, and it breaks more of its bonds at nodes already down to four or fewer live neighbours (23-128 rounds versus 3-38).

That last number is the shared criterion's weakness, not the lane's: `calculateNodeStrains` inverts the rest covariance of a node's live neighbours, and once those neighbours are few or nearly coplanar the resolved strain is ill-conditioned. Removed bonds in both lanes carry recorded strains up to 2,100x their threshold in such rounds. Late cascades in both lanes are partly this artefact.

### 3.4 Near the threshold the outcome is a knife-edge

12x12x2, glass, 16 m/s: at `5e-7` the reference breaks 10 bonds (2 rounds) and the tile holds; the modal lane breaks 1,671 into 45 pieces. At `2.5e-7` both break the same 10 bonds in the same 2 rounds at the same times and the tile holds. State dumps just before the divergent round (8.45e-5 s) show the lanes agreeing to 2.2 µm in position and 1.4 m/s in velocity on peak node speeds of 8 m/s — the size of the contact-capture discretisation difference — and the criterion sitting at 1.01-1.05 of threshold. That difference decides between "6 bonds" and "18 bonds" at that sample, and the cascade follows from it. At 20 m/s on the same tile both lanes shatter: modal 1,733 bonds / 54 pieces / largest 195, reference 1,531 / 21 / 234 (13% apart in bonds; pieces again unconverged).

### 3.5 Materials under identical conditions

8x8x2, 16 m/s, `5e-7`, both lanes:

| material | tensile / shear / compressive break strain | modal peak strains (t / s / c) | implicit peak strains | outcome |
|---|---|---|---|---|
| glass | 1.29e-3 / 2.44e-3 / 2.86e-2 | reaches threshold | reaches threshold | shatters in both (918 vs 790 bonds) |
| oak | 1.50e-2 / 4.95e-3 / 8.67e-3 | 3.81e-3 / 3.97e-3 / 7.30e-3 | 3.78e-3 / 3.99e-3 / 7.35e-3 | no failure in either lane |
| iron | 2.37e-3 / 4.16e-3 / 5.69e-3 | 1.35e-3 / 1.17e-3 / 1.96e-3 | 1.24e-3 / 1.18e-3 / 1.97e-3 | no failure in either lane |

Where nothing breaks the two lanes' elastic peak strains agree to 1-8%, a direct check of the elastic response independent of fracture. Oak reaches 80% of its shear threshold and iron 57% of its tensile one at this speed. Neither is a material claim: the linear basis cannot represent oak's grain or iron's yield, and neither can the reference's isotropic central-force lattice, so the comparison is between two solvers of the same wrong model.

### 3.6 Truncation: a low-rank basis loses the cascade

8x8x2, 16 m/s, δ = 1e-6, keeping the lowest-frequency fraction of the modes (`--modes-fraction`):

| retained | first failure set | rounds | broken | pieces | J(first) / J(final) vs exact |
|---:|---:|---:|---:|---:|---:|
| 1.00 (216) | 8 bonds | 183 | 922 | 35 | 1.00 / 1.00 |
| 0.75 (162) | 12 | 13 | 106 | 1 | 0.67 / 0.11 |
| 0.50 (108) | 12 | 8 | 30 | 1 | 0.67 / 0.03 |
| 0.25 (54) | 4 | 5 | 28 | 1 | 0.00 / 0.03 |

The first crack survives moderate truncation; the cascade does not, because the strain field that the criterion reads after each removal lives in the high modes the truncation removed. A reduced basis in the sense of Barbič-James is not a route to this cascade; **the second half of the research answer is no.**

## 4. Cost

### 4.1 Per stage, fracture window

Modal lane, 2 ms window, `5e-7` sampling, OpenMP with 4 threads (the concurrent-campaign setting), dense cascade at 16 m/s:

| tile | free dofs | basis build | evolve | field u = phi q | contact | criterion | basis updates | bonds updated | per bond | window total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8x8x2 | 216 | 0.006 s | 0.005 | 0.057 | 0.045 | 0.076 | 0.806 s | 918 | 0.88 ms | 1.02 s |
| 12x12x2 (20 m/s, 2.5e-7) | 600 | 0.119 s | 0.033 | 0.342 | 0.345 | 0.535 | 16.19 s | 1,733 | 9.34 ms | 17.7 s |
| 12x12x2 (16 m/s, 2.5e-7, 10 bonds) | 600 | 0.121 s | 0.037 | 0.320 | 0.274 | 0.666 | 0.13 s | 10 | 13 ms | 1.58 s |

The update dominates whenever the cascade is dense, and it scales as `n k²` with `k ≈ n` until the body fragments. Sampling (field + criterion + contact) is 0.18 s per 4,000 samples at 216 dofs and 1.3 s at 600, roughly the `n²` of the field evaluation plus the bond count of the criterion. Where little breaks the modal lane is 3-5x cheaper than the reference (0.27 s vs 1.10 s at 12 m/s on 8x8x2; 1.58 s vs 4.86 s at 16 m/s on 12x12x2); where much breaks it is 1-4x more expensive (1.02 s vs 0.74 s on 8x8x2 at 16 m/s; 17.7 s vs 3.86 s on 12x12x2 at 20 m/s).

At 16x16x2 (1,176 free dofs, 24 m/s, `2.5e-7`, 6 threads) the modal window is **120 s** (basis build 1.45 s, 115.5 s of updates for 1,757 bonds in 390 rounds, 66 ms per bond), against **8.3 s** for the reference (1,966 bonds; the two lanes 11% apart in bonds, 50 versus 21 pieces). Sampling at that size is 2.9 s per 8,000 samples. The basis build is 0.006 s at 216 dofs, 0.12 s at 600 and 1.45 s at 1,176, consistent with the dense solver's n³.

### 4.2 Threads

OpenMP threads change only the dense products (the update and the field evaluation); the criterion and contact are serial. Same scenes, clean machine:

| tile, speed, step | threads | basis updates | field | criterion | window total |
|---|---:|---:|---:|---:|---:|
| 8x8x2, 16 m/s, 5e-7 (918 bonds) | 1 | 1.09 s | 0.057 | 0.077 | 1.31 s |
| 8x8x2, 16 m/s, 5e-7 | 24 | 0.74 s | 0.061 | 0.085 | 0.98 s |
| 12x12x2, 20 m/s, 2.5e-7 (1,733 bonds) | 1 | 33.7 s | 1.17 | 0.53 | 36.1 s |
| 12x12x2, 20 m/s, 2.5e-7 | 24 | 14.2 s | 0.19 | 0.62 | 15.6 s |

Threads buy 1.3x at 216 dofs and 2.4x at 600: each update is one product of a few hundred thousand to a few hundred million flops, too small to fill 24 cores. Single-threaded the update runs at 11 GFlop/s (AVX2), which is not far from what a serial dense product can do; the cost is in the algorithm's `n k²`, not in the kernel.

### 4.3 Impact through rest

8x8x2 glass, iron ball 16 m/s, `5e-7`, both lanes, Jolt (0 worker threads) at 1/240 s from the hand-off, default concrete floor, gravity on, rest defined as every dynamic body below 1 mm/s and 0.1 rad/s for 0.25 s. Modal lane with 24 threads; the machine was otherwise quiet. These are the figures of the verification re-run on the committed binaries; the previous run of the same binaries gave the identical bond sets, frames and piece counts with 1.131 s and 0.745 s of compute.

| lane | simulated | scene + basis | fracture window (2 ms) | hand-off | settle | compute wall | ratio | pieces handed to Jolt | at rest |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| modal | 8.002 s | 0.006 s | 0.993 s (476 rounds, 918 bonds) | 0.001 s | 0.125 s (1,920 steps) | **1.120 s** | **0.14** | 35 fragments (49 cells, 76 collision boxes), 5 clamped remnants (79 cells) | pieces yes; the ball is still rolling on the floor at 0.31 m/s at 8 s and 0.18 m/s at 12 s (0.092x), on the engine's default concrete surface with rolling resistance 0.015 |
| implicit | 6.173 s | 0 | 0.752 s (209 rounds, 790 bonds) | 0.001 s | 0.007 s (1,481 steps) | **0.760 s** | **0.12** | 1 fragment (1 cell); the rest stays clamped as two remnants (127 cells) with 790 internal bonds cut | yes, from 5.92 s (the ball bounces on the tile and stops) |

Both meet the owner's 1.1x, and the two recordings show the two outcomes section 3.3 measured: the modal cascade opens a hole and 35 pieces fall through it; the reference cuts 790 bonds but the tile stays clamped and the ball bounces on it. That difference is inside the reference's own unconverged spread for piece counts (3 to 7 pieces between its two finest steps at this speed), so neither recording can be called the right one. Writing the JSON takes 0.30 s (modal, 959 frames, 22.6 MB) and 0.19 s (implicit, 584 frames, 16.2 MB) on top of the compute wall.

Both recordings play in the playground's 3D tab (`scripts/import-playback.py`, then `python playground/server.py --runs build/playground-runs` and the printed URL); the modal one carries 476 cascade frames plus 60 Hz settling frames. They were also registered in the owner's job store (`--runs C:\Users\henry\dev\banjo\build\playground-runs`, job `65331afc7b2f47f791799e70ed699c97`) and checked in the owner's running playground at `http://127.0.0.1:8765/?job=65331afc7b2f47f791799e70ed699c97`: the server restores the job from disk, serves both playbacks, and the 3D playback tab plays the modal case from the strike through the hole opening to the pieces gone through it.

**Where the rule fails.** The same interaction on the 12x12x2 tile, 20 m/s, `2.5e-7`, both lanes, same settle settings, 8 s cap (neither lane's pieces are at rest by 8 s: the ball and a few fragments are still rolling in both):

| lane | simulated | scene + basis | fracture window (2 ms) | settle | compute wall | ratio | rule | pieces handed to Jolt | JSON |
|---|---:|---:|---|---:|---:|---:|---|---|---|
| modal | 8.002 s | 0.121 s | 15.30 s (685 rounds, 1,733 bonds; 13.84 s of basis updates, 8.0 ms per bond) | 0.200 s (1,920 steps) | **15.51 s** | **1.94** | failed by 1.8x | 52 fragments (92 cells, 110 boxes), 2 clamped remnants (196 cells) | 0.85 s, 60.7 MB, 1,168 frames |
| implicit | 8.002 s | 0 | 4.00 s (369 rounds, 1,531 bonds) | 0.064 s | **4.07 s** | **0.51** | met | 20 fragments (54 cells, 56 boxes), 1 clamped remnant (234 cells) | 0.62 s, 49.0 MB, 852 frames |

The rule is met on the 8x8x2 scene because 2 ms of fracture is followed by seconds of rigid motion that Jolt computes at 0.01-0.03x, and an 8 s interaction allows 8.8 s of wall. On 12x12x2 the modal window alone is 15.3 s, so the lane fails for any interaction shorter than 14 s and the pieces would have to keep moving that long for it to pass; the reference's 4.0 s window is inside the budget. (An earlier draft of this note said neither lane meets the rule once the window exceeds about 2.5 s; that was wrong, and the measurement above replaces it.) At 16x16x2 the modal window is 120 s against the reference's 8.3 s (section 4.1, window only, not run through rest), so the modal lane fails there by more than 13x and the reference sits at the edge of the budget; and the reference's step cannot be relaxed on larger tiles (section "Conditions"). These two recordings are registered in the owner's store as job `9afe5fe6e9624dfda6c21d1b51f263cb` (`http://127.0.0.1:8765/?job=9afe5fe6e9624dfda6c21d1b51f263cb`).

## 5. What does not work

- **The exact basis update is O(n·k²) per bond and dominates dense cascades.** On 8x8x2 it is 77-80% of the window; on 12x12x2, 90-92%. Deflation reduces `k` only after the body has fragmented. The known route below `O(n²)` per bond, the fast-multipole Cauchy product of Gu & Eisenstat, is not implemented.
- **Truncating the basis loses the cascade** (section 3.6).
- **The lane's resolution requirement is the same as the reference's**, set by contact capture and criterion sampling, not by the elastic wave. Above about half the fastest period both lanes fabricate cascades (section 3.2).
- **Fracture outcomes near the threshold are knife-edge** and are decided by discretisation-scale differences; piece counts converge in neither lane (sections 3.3, 3.4). This is the implicit checkpoint's non-convergence result, reproduced.
- **The shared criterion goes ill-conditioned at nodes with few live neighbours** and drives late-cascade breaks in both lanes (section 3.3).
- **The modal lane removes 2-4x more stored bond energy** than the reference at matched broken counts; not explained.
- **Fragment-fragment contact starts only at the hand-off.** During the 2 ms window detached pieces pass through each other, as in the reference.
- **The hand-off is to a rigid compound of merged cell boxes** (runs along x, then slabs along z; at most 64 parts per Jolt compound). A fragment needing more than 64 boxes stops the tool with a message. Fragment inertia and velocity come from `calculateFragmentMassProperties`; its coarsening loss is reported.
- **A microscopic tail interval was a bug.** Accumulated rounding could leave a final interval of 1e-19 s in which the impulse response is roundoff-sized and a roundoff-sized gap correction became a 44 N·s impulse (a node at 2,189 m/s, −71 kJ of "contact loss"). The lane now stops when the remaining window is below 1e-9 of the sampling interval, which is the reference's own guard. Every number in this note was taken after the fix.
- **The reference cannot be run at `dt ≥ 1e-6` on tiles larger than 8x8x2** with the heavy-clamp construction (its penetration audit fails by 32%), so its ladders start at `5e-7`.

## Verification

`python scripts/check-source-registration.py`: OK (194 sources, 194 registered). Two new suites, `banjo_modal_eigen_tests` and `banjo_modal_fracture_tests`, pass; the CTest sweep with the five long suites excluded by instruction (`banjo_network_skin_tests`, `banjo_network_runtime_tests`, `banjo_material_showcase_tests`, `banjo_network_adaptive_tests`, `banjo_contact_capacity_tests`, 18 min to 1 h each) is **84 of 84 passed in 88 s** (89 configured). An earlier sweep with only the first three excluded passed 84 of 85, the one failure being `banjo_contact_capacity_tests` at CTest's 1,500 s timeout, which is why it is on the list. No existing test's tolerance was changed and no existing test file was edited. The reference lane (`ConservativeStep`, `FractureStep`, `BondFailure`) is untouched.

The one wrong-premise check that was removed from a new test: an assertion that the linearised removal energy equals the engine's exact one to 2%. A node left with fewer than three live neighbours is judged on its own stretch only, so it can slide sideways by millimetres before its last bonds fail, and there the geometric term dominates (23% apart in the test scene). The ledger closes with the linear figure, which is what is asserted; both figures are reported.

### Reproduction

```powershell
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 4
ctest --test-dir build/agent -C Release -E "banjo_network_skin_tests|banjo_network_runtime_tests|banjo_material_showcase_tests|banjo_network_adaptive_tests|banjo_contact_capacity_tests"

# Headline (impact through rest, both lanes, playback written)
./build/agent/Release/banjo_modal_fracture_record.exe --lane modal    --cells 8x8x2 --speed 16 --window 0.002 --sample-dt 5e-7    --settle 1 --max-duration 8 --output build/runs/modal-8x8x2-16.json
./build/agent/Release/banjo_modal_fracture_record.exe --lane implicit --cells 8x8x2 --speed 16 --window 0.002 --reference-dt 5e-7 --settle 1 --max-duration 8 --output build/runs/implicit-8x8x2-16.json
python scripts/import-playback.py build/runs/modal-8x8x2-16.json build/runs/implicit-8x8x2-16.json --name "modal" --name "implicit"
python playground/server.py --runs build/playground-runs   # then open the printed URL, 3D playback tab
# ... or register them in an already-running playground's job store (runtime data, no source change):
python scripts/import-playback.py --runs C:/Users/henry/dev/banjo/build/playground-runs build/runs/modal-8x8x2-16.json build/runs/implicit-8x8x2-16.json --name "modal" --name "implicit"

# Where the rule fails (12x12x2 through 8 s, both lanes: 15.5 s and 4.1 s of compute, 61 MB and 49 MB of JSON)
./build/agent/Release/banjo_modal_fracture_record.exe --lane modal    --cells 12x12x2 --speed 20 --window 0.002 --sample-dt 2.5e-7    --settle 1 --max-duration 8 --output build/runs/modal-12x12x2-20.json
./build/agent/Release/banjo_modal_fracture_record.exe --lane implicit --cells 12x12x2 --speed 20 --window 0.002 --reference-dt 2.5e-7 --settle 1 --max-duration 8 --output build/runs/implicit-12x12x2-20.json

# Section 3.2 / 3.6 / 3.5
python scripts/modal-fracture-compare.py ladder     --cells 8x8x2 --speed 12 --reference-dts 1e-6,5e-7,2.5e-7 --sample-dts 2e-6,1e-6,5e-7,2.5e-7
python scripts/modal-fracture-compare.py truncation --cells 8x8x2 --speed 16 --fractions 1,0.75,0.5,0.25
python scripts/modal-fracture-compare.py materials  --cells 8x8x2 --speed 16

# Section 3.3 / 3.4 (any lane, size, speed, step; --settle 0 for the window alone)
./build/agent/Release/banjo_modal_fracture_record.exe --lane modal --cells 12x12x2 --speed 16 --window 0.002 --sample-dt 2.5e-7 --settle 0 --output out.json
./build/agent/Release/banjo_modal_fracture_record.exe --lane modal --cells 12x12x2 --speed 16 --window 8.45e-5 --sample-dt 5e-7 --settle 0 --dump-state state.json --output out.json

# Section 1 (basis exactness through a cascade) is the test; per-round figures for any scene:
./build/agent/Release/banjo_modal_fracture_record.exe --lane modal --cells 8x8x2 --speed 16 --window 0.002 --sample-dt 5e-7 --check-basis 1 --basis-mode update --settle 0 --output out.json
```

Every report carries the per-round bond lists, trigger ratios, live-neighbour counts, update wall times and retained-mode counts, the ledger, the contact audit and the stage timings; the `_summary` line the tool prints is enough for the tables above.

## Next

1. **Bring the update below `O(n²)` per bond or avoid it.** The fast-multipole Cauchy product (Gu & Eisenstat) makes the eigenvector update `O(n log n)` per row; alternatively, keep the basis factored (`phi_0 V_1 ... V_m`) and collapse it only when a sample is needed. Either is a week of numerical work with a clear success criterion: the 12x12x2 window under the reference's 4.0 s, which takes the 8 s interaction from 1.9x to about 0.5x.
2. **Decouple the contact substep from the criterion sample.** The contact capture, not the wave, sets the resolution now; resolving contact at `2.5e-7` while sampling the criterion at `2e-6` would cut the sampling cost 8x if the cascade proves insensitive to it. Section 3.2 says it may not be.
3. **Fix the criterion's degenerate-neighbour case** in `BondFailure` (a minimum-rank or minimum-count guard on the nonlocal strain) — it is shared, so the fix lands in both lanes at once, and it is the first thing standing between any lane and a converged piece count.
4. **Explain the 2-4x removed-energy difference** by dumping per-bond extension at removal in both lanes.
5. Only then: fragment-fragment contact inside the window, and a Gc-calibrated law.
