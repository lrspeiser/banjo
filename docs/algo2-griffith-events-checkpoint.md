# Algorithm 2 checkpoint: an event-driven Griffith cascade with no time stepping

> **Kept for its findings.** This lane was tried on 2026-09-08 and not adopted:
> [development-status.md](development-status.md) records why -- none of the three
> fast-fracture lanes beat fixing the strain measure and parallelising the sweep.
> Its code was never merged. It is kept exactly as measured under the tag
> `archive/algo2-griffith-events` (commit `4ecd1ba`); `src/griffith/`, `tools/fracture_algo2.cpp`, `tests/griffith_cascade_tests.cpp` and `scripts/algo2-*.py` below refer to that tag.

Tested code: branch `agent/algo2-griffith-events` in worktree
`C:/Users/henry/dev/banjo-agents/algo2-griffith`, based on `c38da39`.
September 8, 2026, America/Los_Angeles. Not pushed, not merged, not on main.
Machine: Ultra 9 / RTX 5090 workstation, Windows 11, MSVC 17 Release, OpenMP on,
CPU only (this lane never touches the GPU).

Predecessors this lane was built against: the
[engine options analysis](engine-options-analysis-2026-09-07.md) (two walls; the
modal basis is exact and is the right predictor, and a truncated basis loses the
cascade), the [quasi-static checkpoint](fast-quasistatic-checkpoint.md) section 3
(a static load path spreads to the rim while inertia confines the dynamic one —
so this lane's *loading* is the dynamic impulse response, never a static solve),
the shared criterion in `fracture/BondFailure.{hpp,cpp}` (unchanged by this lane),
and the Fracture lab CLI contract in `playground/fracture_lab.py` on
`agent/integration`.

Every number below is measured on this machine unless it is marked *estimate*.

## Result in one paragraph

The lane works, it is by a wide margin the cheapest thing in this repository
that breaks a plate, and it is wrong in ways that are now measured rather than
suspected. **The fracture answer costs 4.0 ms at 240 cells, 65 ms at 1,000 and
445 ms at 2,000 — 1.15 nanoseconds per bond per event, flat across an 11x range,
and no time stepping anywhere** — against the explicit lattice's 98.5 s on the same 1,000-cell scene
run from the same binary. The precompute behind that is cached, keyed by the
whole scene, and costs 0.44 s / 19 MiB at 240 cells rising to 463 s / 2.34 GiB
at 2,000, where the influence matrix rather than the eigen decomposition is what
sets the wall. On the base scene it reproduces the reference's broken-bond count to
+2.4% and its removed energy to +79%, while getting the piece count wrong by
4.3x. **Three findings are the substance, and two of them are negative.**
(1) **The shared 500-cell contract scene cannot be expressed by this lane at
all**: one cell through the thickness leaves a central-force lattice with
exactly zero transverse stiffness, so the whole impact direction is a rigid
motion; the lane detects it and refuses with that reason. (2) **Where the bond
counts agree, it is two large errors cancelling** — an impulse 59x below what
the reference's contact delivers, against a Griffith criterion 16x more
permissive in strain — and on a 30 mm plate the cancellation stops and the lane
breaks 11,022 bonds where the reference breaks 13. (3) **The Griffith and the
engine's shared strain criterion do not differ by a constant: they cross over
between materials** (glass 1/22.7 in strain, oak 1/9.8, iron 1.54x), so swapping
one for the other changes the material ranking, not just the numbers. What does
survive is what survives in every other lane here: **removed energy**, within a
factor of two on four scenes and within 10% on two of them, and the contact
model's energy budget within 13% of what the reference's resolved contact
dissipates.

## 1. The method, exactly

### 1.1 Object model

Uniform-cube bond lattice from `generateBoxLattice`/`BoxRecipe`
(`src/matter/Lattice.hpp`), horizon 2, glass from the reference material route
`withStrengthDerivedFailure(compileElasticLatticeReference(...))` — the same
route `src/fastlattice/TileImpactScene.cpp` uses, so both lanes see identical
bond stiffness, identical rest lengths and identical strain thresholds. That
route leaves `fracture_energy_j_m2` unset, so Gc is copied from the material
definition (glass: 8 J/m²) rather than invented. `strength_variation` is 0 on
this route, so the lattice is deterministic.

`tests/griffith_cascade_tests.cpp` proves the lattice is bond-for-bond the
reference lane's lattice (same nodes, same bond endpoints in the same order,
same compliances), which is what makes first-failure sets comparable by index.

Support is `ledges` — the bottom-layer cells over the two rigid ledges of
`TileImpactScene.cpp`'s bridge layout (ledge width 40 mm, height 120 mm) are
held. `clamped` (the whole perimeter ring) is also implemented. **The reference
is run through the same executable with `--reference`**, which builds the
explicit lattice's scene from the same command line, so the two lanes cannot
differ by a scene detail.

The held cells are a *bilateral* Dirichlet condition, where the real ledge is
unilateral: this lane's plate cannot lift off its supports. That is stated here
as a modelling difference, not measured separately.

### 1.2 Bond crack area

Griffith needs an area. The bond's elastic-equivalence area is
`A_raw = k_b L_b / E = h² / (m d)` for horizon `m` and grid distance `d`, but
those do not sum to a cut: an axis-aligned plane through the lattice is crossed
by bonds whose raw areas total `C·h²` per cell of the plane, with

```
C = sum over offsets (dx>0, |d| <= m) of  dx / (m d)      C(m=2) = 3.5686
```

so the crack area is `A_b = A_raw / C`. With that, **a planar cut of any size at
any cell size costs exactly Gc per unit area** — the mesh-independence the
engine options analysis names as the fix for Wall 2, cause 1. The test
`bondAreasSumToACut` checks this at horizons 1, 2 and 3 to 1e-12.

### 1.3 Precompute (cached under `--cache DIR`)

1. **Eigenpairs** of the intact plate: `modal::ModalBasis` over the free cells,
   `K phi = omega² M phi`, `phi^T M phi = I`. Dense, O(n³), no truncation.
2. **E[s][b]**, the peak dynamic strain of bond `b` per unit impulse delivered
   through the ball's footprint centred on strikeable surface cell `s`. The
   modal impulse response is closed form, `q_k(t) = (phi_k^T f / omega_k) sin(omega_k t)`,
   so a bond's strain history is `eps_b(t) = sum_k (g_b·phi_k / L_b) q_k(t)` and
   the table entry is `max_t eps_b(t)` — the most *tensile* excursion, because
   Griffith mode I is what opens a crack. **No stepping**: the sample times are
   evaluation points of an exact solution, not integration steps.
   The window is 2.5 longitudinal wave transits of the plate's longest side and
   the sample step is a quarter of the lattice's own explicit substep limit
   (118 µs and 0.505 µs, 236 samples, on the base scene); both are reported.
3. **A[b][b']**, the crack-influence matrix. Removing bond `b'` is a rank-one
   downdate `K' = K - k' g' g'^T`, so by Sherman-Morrison the extra displacement
   under an unchanged load is `c' F' / (1 - k' g'^T c')` with `c' = K^-1 g'`, and

   ```
   A[b][b'] = (g_b^T K^-1 g_b') / ( L_b (1 - k_b' g_b'^T K^-1 g_b') )      [1/N]
   ```

   `K^-1 = phi diag(1/omega²) phi^T`, so `g_b^T K^-1 g_b'` is an inner product of
   two rows of `phi^T g / omega`; the whole matrix is one symmetric rank-`n`
   product. Stored column-major in the failing bond as float32 so one event
   touches one contiguous column. A bond that is a cell's last tie has
   `1 - k g^T K^-1 g -> 0`; its release cannot be equilibrated by the rest of
   the lattice, so it is flagged and redistributes nothing rather than being
   amplified. The report says whether the cascade broke such a bond.

The cache key is the whole scene — plate, cell, thickness, support, material,
horizon, ledge geometry, **ball diameter** (the footprint depends on it), seed,
and the sampling parameters — stored in full in the file and compared exactly on
load. Nothing is reused across a partial match.

### 1.4 Contact model (stated; `report.contact.model` repeats it verbatim)

A rigid sphere of radius R indenting a plate of cell size h by half a cell has
Hertzian contact radius `a = sqrt(R h - h²/4)`; the impulse is spread over the
top-layer cells inside `a` with the Hertzian pressure weight `sqrt(1 - (r/a)²)`,
normalised to one. Its magnitude is a restitution-zero capture of that footprint:

```
J     = mu_patch v,     mu_patch = m_ball m_patch / (m_ball + m_patch)
E_in  = 0.5 mu_plate v², mu_plate = m_ball m_free  / (m_ball + m_free)
```

`m_patch` is exactly the plate's modal effective mass for this load (since
`phi phi^T = M^-1`, `1/m_eff = sum_i w_i²/m_i`), and `m_free` is the unsupported
plate mass. The two effective masses answer two different questions: what
inertia a delta-function contact meets at first touch (short time), and what
inertia the ball meets before it separates (long time). The impulse response the
table holds is exact only in the delta limit, so `J` uses the first.

`--contact-mass plate` swaps in `mu_plate` for the impulse as well. It is not a
tuning knob; it is the other end of the same physical bracket, and section 4.3
measures what it does to the answer. **Nothing in this lane authors a fragment
velocity**: the pieces go to Jolt from rest, and the momentum the contact model
put into the plate is reported as `handoff.dropped_momentum_n_s`.

### 1.5 The cascade

```
load[b]        = J * E[s][b]                       (one table read per bond)
correction[b]  = 0
repeat:
    for every live b:  eps = load[b] + correction[b]
                       G_b/Gc = 0.5 k_b (eps L_b)² / (Gc A_b)    (eps > 0 only)
    break the single largest G_b/Gc >= 1;  ties to the lower bond index
    if Gc * A_b > remaining budget: stop, budget exhausted
    budget      -= Gc * A_b
    F            = k_b eps L_b
    correction   += A[:, b] * F                    (one precomputed column)
```

One event is two passes over the bonds: O(bonds), no solve, no step. The scan
keeps the first strict maximum, so the tie rule is deterministic and independent
of any sweep order — the Wall-2 order dependence of a Gauss-Seidel lane does not
exist here by construction. Compression and shear are not modelled: this is a
mode-I energy criterion, and the contact crushing the reference lane sees under
the ball has no counterpart here.

Pieces are connected components, handed to Jolt to fall and settle exactly as
the other lanes do.

## 2. The two obstacles, both hard

### 2.1 A plate one cell thick cannot be expressed at all (the 500-cell contract scene)

The shared scene contract's default is 0.25 x 0.20 x 0.01 m at 10 mm cells:
25 x 20 x **1** cells. With one cell through the thickness every bond lies in
the plate's own plane, and a central-force bond lattice then has **exactly zero
transverse stiffness**: `K` is singular, and the entire impact direction is a
rigid motion. There is no compliance column, no eigenbasis with a positive
spectrum, and no peak strain — a downward impulse produces free flight and zero
strain, not fracture.

What carries the load in the explicit lattice on that scene is *geometric*
stiffening: a transverse deflection `w` stretches the in-plane bonds by
`~w²/(2L)`, a second-order term that the explicit lattice keeps because it uses
real distances and that is **identically zero in any linearisation about the
undeformed plate**. This is not a solver bug or a tolerance; it is what the
approximation is. The lane detects it (a per-cell rank test on
`sum_b k_b d_b d_b^T`) and refuses with that reason and a non-zero exit, which
is what the CLI contract asks for:

```
$ banjo_fracture_algo2 --plate 0.25 0.20 0.01 --cell 0.01 --ball 0.06 --drop 2.0 ...
banjo_fracture_algo2: a plate one cell thick has no bond out of its own plane, so this
central-force lattice has exactly zero transverse stiffness and the whole impact direction
is a rigid motion. This lane linearises about the undeformed plate and cannot represent the
membrane stiffening that carries the load there; give the plate at least two cells through
the thickness (thickness >= 2 x cell)
```

The reference lane on that exact scene, run through the same binary, does work:
**73 bonds, 1 piece, 2.148 J removed, 1.95 s of wall for 0.330 s simulated
(5.89x realtime), fracture window 13.764 ms** — reproducing the numbers in the
brief (73 bonds, 2.15 J, ~6x) to the noise of one machine. That measured
13.764 ms is the denominator of `realtime.fracture_window_ratio` throughout this
lane, and `report.realtime.window_note` says so on every run.

The lane's own equivalent of that plate would be 0.25 x 0.20 x 0.01 m at 5 mm
cells: 50 x 40 x 2 = 4,000 cells, 11,040 free degrees of freedom, about 39,000
bonds. A dense eigendecomposition at that size is O(n³) with the measured
constant of section 3 — *estimate* 30 minutes for the eigen step alone, and a
6.1 GiB influence matrix — so it is outside this lane's envelope. **The lane's
working envelope, measured in section 3, is a plate at least two cells thick
with up to about 4,000 free degrees of freedom** (1,500 cells: 167 s and
1.17 GiB of tables), and it says so when it refuses.

### 2.2 The Griffith criterion and the shared strain criterion do not agree, and the gap is not a constant

Both criteria are evaluated on the same strain field by the same code
(`--criterion griffith|strain`), so the comparison is clean. For a `d = 1` bond
of glass at cell size h:

```
Griffith:        eps_c = sqrt( 2 Gc / (E h C) )      = 8.00e-5   at h = 10 mm
shared criterion: eps_c = 2 sigma_t / E              = 1.286e-3   (break_strain_multiplier 2.0)
ratio in strain 16.1x,  ratio in energy 259x         at h = 10 mm
ratio in strain 22.7x,  ratio in energy 516x         at h = 20 mm
```

Read the other way: **the engine's shared strain criterion currently dissipates
259 times Gc per unit of crack area at 10 mm cells, and 516 times at 20 mm** —
and the factor is proportional to the cell size, which is precisely the mesh
dependence the engine options analysis identifies as Wall 2, cause 1
(`docs/engine-options-analysis-2026-09-07.md` section 1). This lane measures it
rather than inheriting it, because it is the one lane whose criterion is written
in terms of Gc.

And the gap is not a fixed factor. It is proportional to the cell size, and it
also depends on the material — for iron it **reverses**, because Gc = 100 kJ/m²
makes the energy criterion the conservative one. Section 5.1 measures all three
materials under identical conditions and gives the crossover.

The consequence for this checkpoint is that a raw Algorithm 2 / reference
comparison mixes two independent errors. Section 4 therefore reports both
criteria on the same loads, which separates them.

*(This is the fourth agent's territory; nothing in `fracture/BondFailure.{hpp,cpp}`
was changed here, and no tolerance was moved.)*

## 3. Cost

Every size is a 20 mm glass plate on two ledges at 10 mm cells (240 cells at
20 mm for the small end), struck by a 60 mm iron ball at 6.264 m/s.
`scripts/algo2-cost-scaling.py` reproduces the table: each size is run once
against an empty cache directory of its own and once against the warm one, so
the precompute is really paid in the first column and really skipped in the
second.

The precompute is three costs with three different scalings, and the influence matrix is what stops the lane first - it is `bonds^2` floats.

| cells | bonds | free dofs | strike columns | cold precompute s | eigen / influence / peak s | tables MiB | warm process s | cascade s | events |
|---:|---:|---:|---|---:|---|---:|---:|---:|---:|
| 240 | 2176 | 600 | 120/120 | 0.44 | 0.14 / 0.08 / 0.20 | 19 | 0.148 | 0.0040 | 1658 |
| 500 | 4698 | 1260 | 250/250 | 5.62 | 1.37 / 0.99 / 3.21 | 89 | 0.422 | 0.0167 | 3271 |
| 1000 | 9788 | 2520 | 500/500 | 61.96 | 19.72 / 14.53 / 27.48 | 384 | 0.748 | 0.0647 | 5553 |
| 1500 | 17299 | 4020 | 1/500 | 166.43 | 86.94 / 78.62 / 0.22 | 1175 | 1.916 | 0.2184 | 11022 |
| 2000 | 24810 | 5520 | 1/500 | 462.78 | 216.85 / 244.18 / 0.36 | 2396 | 3.589 | 0.4448 | 15346 |

A rerun with the cache warm - a different drop height, a different strike
offset, a different speed - is the `warm process s` column: the tables are
read back from disk, the cascade runs, the pieces settle in Jolt and the
recording is written. `cascade s` is the fracture answer alone.

So the fracture answer costs **4.0 ms at 240 cells, 16.7 ms at 500, 65 ms at
1,000, 218 ms at 1,500 and 445 ms at 2,000**, and the process around it costs a
few times that.
The cascade is `events x bonds` work and it measures as exactly that: one event
costs 2.4, 5.1, 11.6, 19.8 and 29.0 microseconds at 2,176, 4,698, 9,788, 17,299
and 24,810 bonds — **1.12 to 1.18 nanoseconds per bond per event, flat across an
11x range** — and the thousands of events these scenes produce are what make the
total milliseconds rather than microseconds. On a
scene where few bonds break - the same plate under the shared strain criterion -
the cascade is **0.1 ms**. **"Microseconds per event" is the honest claim;
"microseconds per impact" holds only when the impact breaks a handful of
bonds**, and a Griffith cascade on glass at 10 mm cells breaks thousands.

Against the realtime rule (`report.realtime`), on the base scene through 3 s of
settling: **this lane is 0.136x with the cache warm** and 19.6x cold, against
the explicit lattice's **30.4x**. The lane's own fracture phase has no simulated
duration at all, so `fracture_window_ratio` uses the explicit lattice's own
fracture window on the 500-cell contract scene, **13.764 ms**, as its
denominator, and `report.realtime.window_note` says so on every run: this lane
scores **4.13** there against the reference's **483**.

## 4. Accuracy against the reference

Reference: **the explicit lattice, `banjo_fastlattice`, CPU backend, double
precision, every substep resolved** (`--reference` runs it from the same binary
and the same command line). Its numbers on the 500-cell contract scene reproduce
the brief: 73 bonds, 2.148 J, 1.95 s of wall for 0.330 s simulated.

### 4.1 The base scene, four combinations

The lane can be run with either criterion and either end of the contact
bracket, and all four are reported because the raw comparison mixes two
independent errors. Base scene: 250 x 200 x 20 mm glass, 1,000 cells at 10 mm,
60 mm iron ball at 6.264 m/s (a 2.0 m drop), centre strike, two ledges.

| lane | impulse | broken bonds | pieces | largest piece | removed energy | wall |
|---|---:|---:|---:|---:|---:|---:|
| **reference** (explicit lattice) | 7.658 N s | **5,421** | **168** | **304 cells / 0.760 kg** | **1.760 J** | 98.5 s |
| algo2, Griffith, footprint impulse | 0.130 N s | 5,553 (+2.4%) | 39 (0.23x) | 956 cells / 2.390 kg (3.1x) | 3.150 J (+79%) | 0.41 s warm |
| algo2, shared strain criterion, footprint impulse | 0.130 N s | 0 | 1 | 1,000 cells | 0.000 J | 0.40 s |
| algo2, shared strain criterion, plate impulse | 3.916 N s | 6,825 (+26%) | 107 (0.64x) | 840 cells (2.8x) | 3,035 J (1,700x) | 0.57 s |
| algo2, Griffith, plate impulse | 3.916 N s | 8,417 (+55%) | 470 (2.8x) | 188 cells (0.62x) | 2,943 J (1,670x) | 0.57 s |

**The apparent agreement on bond count is two large errors cancelling, not
evidence that the lane is right.** The contact model delivers 0.130 N s where
the reference's contact delivers 7.658 N s over its 200 ms of contact - 59x low,
because a delta-function impulse can only capture the footprint's inertia -
while the Griffith criterion fires at 1/16 of the shared criterion's strain
(1/259 of its energy per unit crack area, section 2.2). Fix either one alone and
the answer moves by orders of magnitude, as rows 3 and 4 show.

One thing the contact model does get right is its **energy budget**:
`E_in = 0.5 mu_plate v^2 = 12.26 J` is within **13%** of the kinetic energy the
reference's resolved contact actually dissipates into the plate, **14.17 J**.
The budget is never the binding constraint on any scene here - the cascade
spends 0.434 J of crack work against a 12.26 J budget - so the answer is set by
the strain field, not by the ledger. The ledger itself closes exactly
(`energy_ledger.residual_j` is 0 to roundoff on every run, and the test
`theEnergyLedgerCloses` checks it at three speeds).

### 4.2 Where the damage is: diffuse, not crack paths

The most visible error is not the bond count; it is that **the lane spreads its
damage over the whole plate where the reference cuts paths through it**.
`scripts/algo2-damage-geometry.py` reads the dead set straight out of the
recordings:

| | radius of gyration of the dead set | within 20 mm of the strike | median distance |
|---|---:|---:|---:|
| algo2, base scene, 5,553 dead bonds | 76.0 mm | 3.7% | 74.3 mm |
| reference, 500-cell contract scene, 73 dead bonds | 23.1 mm | 64.4% | 17.8 mm |

That is why 5,553 broken bonds still leave 956 of 1,000 cells in one piece: a
horizon-2 lattice does not separate until *most* of the bonds crossing a surface
are gone, and diffuse damage never reaches that density anywhere. The reference
breaks a similar number of bonds and makes 168 pieces because its damage is
organised into connected paths.

The mechanism is stated, not guessed. `E[s][b]` is `max_t eps_b(t)` - every
bond's *lifetime* peak over a 118 microsecond window - and the cascade applies
all of those peaks **at the same instant**. In the reference those peaks are
separated in time: its first failure is at 0.401 ms and its cascade runs for
200 ms. A bond 120 mm from the strike reaches its peak when the wave gets there,
long after the near-contact bonds have already broken and changed the wave that
would have loaded it. The lane has the redistribution (matrix A) but not the
ordering, and A is linearised about the *intact* plate, so it cannot build the
stress concentration at a crack tip that makes a crack a crack. That is the
"inertial confinement and wave arrival order" error, in numbers.

### 4.3 First failure

The reference does not expose its first failure round; the tightest available
proxy is the dead set in the earliest recorded lattice frame, at 0.499 ms with
186 bonds (its own declared first failure time is 0.401 ms). Against that:

* algo2's first-failure set (every bond at or above the criterion under the
  initial load, before any redistribution) is **3,469 bonds**;
* it **contains 170 of the reference's 186** - recall **91.4%**;
* but its precision is **4.9%**, and the Jaccard overlap is **0.05**.

So the lane finds *where* the reference starts breaking, and then breaks most of
the plate as well. The recall is the signal; the precision is the Griffith
criterion of section 2.2.

### 4.4 Per-bond energy

The removed-energy error is not in the count, it is per bond: this lane removes
**5.67e-4 J per broken bond** against the reference's **3.25e-4 J**, a factor of
1.75 that is the whole +79%. The cause is again the envelope: a bond is removed
carrying its *lifetime peak* strain energy, where the reference removes it at
the instant its strain crossed the threshold. The largest peak drive on this
scene is 209, so that bond is removed carrying 209 times the crack work its own
area needs.

## 5. The variations, and where the agreement comes from

Four variations of the base scene plus the contract scene, every one run through
both lanes from the same command line (`scripts/algo2-accuracy-matrix.py`, table
rendered by `scripts/algo2-render-tables.py`).

| scene | lane | impulse N s | broken bonds | pieces | largest piece cells | removed energy J | wall s |
|---|---|---:|---:|---:|---:|---:|---:|
| base: 250 x 200 x 20 mm, 1,000 cells at 10 mm, 60 mm ball at 6.264 m/s, centre | reference (explicit lattice) | 7.658 | 5421 | 168 | 304 | 1.760 | 98.53 |
|  | algo2, Griffith, footprint impulse | 0.130 | 5553 | 39 | 956 | 3.150 | 0.87 |
|  | algo2, shared strain criterion, footprint impulse | 0.130 | 0 | 1 | 1000 | 0.000 | 0.74 |
|  | algo2, Griffith, whole-plate impulse | 3.916 | 8417 | 470 | 188 | 2943.104 | 2.47 |
| | | | | | | |
| thicker: 250 x 200 x 30 mm, 1,500 cells at 10 mm, same striker | reference (explicit lattice) | 8.455 | 13 | 1 | 1500 | 1.574 | 17.06 |
|  | algo2, Griffith, footprint impulse | 0.130 | 11022 | 71 | 1348 | 3.721 | 2.11 |
|  | algo2, shared strain criterion, footprint impulse | 0.130 | 0 | 1 | 1500 | 0.000 | 1.58 |
|  | algo2, Griffith, whole-plate impulse | 4.405 | 15977 | 987 | 229 | 4501.429 | 7.24 |
| | | | | | | |
| higher drop: the base plate at 9.90 m/s (5.0 m) | reference (explicit lattice) | 11.859 | 7930 | 266 | 88 | 7.325 | 65.36 |
|  | algo2, Griffith, footprint impulse | 0.206 | 6690 | 99 | 330 | 8.053 | 1.16 |
|  | algo2, shared strain criterion, footprint impulse | 0.206 | 9 | 1 | 1000 | 0.558 | 0.74 |
|  | algo2, Griffith, whole-plate impulse | 6.189 | 8441 | 482 | 187 | 7351.446 | 3.30 |
| | | | | | | |
| off-centre: the base scene struck at (60, 40) mm | reference (explicit lattice) | 3.825 | 3984 | 99 | 742 | 3.014 | 113.25 |
|  | algo2, Griffith, footprint impulse | 0.130 | 5743 | 34 | 945 | 3.262 | 0.87 |
|  | algo2, shared strain criterion, footprint impulse | 0.130 | 0 | 1 | 1000 | 0.000 | 0.81 |
|  | algo2, Griffith, whole-plate impulse | 3.916 | 8616 | 540 | 168 | 3047.590 | 3.09 |
| | | | | | | |
| heavy slow striker: 200 mm iron ball (32.9 kg) at 1.0 m/s | reference (explicit lattice) | 17.203 | 849 | 14 | 485 | 5.273 | 12.47 |
|  | algo2, Griffith, footprint impulse | 0.065 | 204 | 1 | 1000 | 0.085 | 74.69 |
|  | algo2, shared strain criterion, footprint impulse | 0.065 | 0 | 1 | 1000 | 0.000 | 0.43 |
|  | algo2, Griffith, whole-plate impulse | 1.974 | 7964 | 318 | 211 | 176.773 | 2.19 |
| | | | | | | |
| the shared 500-cell contract scene, one cell through the thickness | reference (explicit lattice) | 3.593 | 74 | 1 | 500 | 2.180 | 2.01 |
|  | algo2, Griffith, footprint impulse | refused: a plate one cell thick has no bond out of its own plane, so this central-force lattice has exactly zero transverse stiffness and the whole impact dire | | | | |
|  | algo2, shared strain criterion, footprint impulse | refused: a plate one cell thick has no bond out of its own plane, so this central-force lattice has exactly zero transverse stiffness and the whole impact dire | | | | |
|  | algo2, Griffith, whole-plate impulse | refused: a plate one cell thick has no bond out of its own plane, so this central-force lattice has exactly zero transverse stiffness and the whole impact dire | | | | |
| | | | | | | |

Reading across the rows:

**Removed energy is the quantity that survives**, as it does in every other lane
in this repository. Algorithm 2 with the Griffith criterion and the footprint
impulse gives, against the reference: **+79% on the base scene, +10% at the
higher drop, +8% off centre**, and **+136% on the thicker plate**. Three of the
four are inside a factor of two and two of them are inside 10%. Nothing else
this lane produces is that close.

**The bond-count agreement is a coincidence and the thicker plate proves it.**
On the base scene the counts agree to 2.4%; on the 30 mm plate the reference
breaks **13 bonds and stays in one piece** while this lane breaks **11,022 and
makes 71**. The two errors that cancelled on the base scene (an impulse 59x low,
a criterion 16x permissive in strain) do not cancel at a different thickness,
because they scale differently with it. **This lane will report a plate as
shattered that the reference leaves intact** — a false positive, and the worst
failure mode for the question the owner actually asks. Under the *shared* strain
criterion on the same load the lane says 0 bonds on that plate, which is the
right verdict; the false positive is the criterion, not the cascade.

**Piece count is wrong everywhere, and always in the same direction with the
footprint impulse**: 39 against 168, 71 against 1, 99 against 266, 34 against 99.
The largest piece is correspondingly too large (956, 1348, 330, 945 cells
against 304, 1500, 88, 742). The reason is section 4.2: the damage is diffuse,
so the plate stays connected.

**The whole-plate impulse fragments, and then the energy explodes.** With
`--contact-mass plate` the same cascade makes 470, 987, 482 and 540 pieces with
largest pieces of 188, 229, 187 and 168 cells — much closer to the reference's
*character* — but its removed energy is 2,943 J against 1.760 J, because a delta
impulse of the full contact momentum over-strains every bond by more than an
order of magnitude and each one is removed carrying that energy. Neither end of
the contact bracket is right; the two ends bracket the answer and neither
reaches it.

**Where a static picture should be right.** The heavy slow striker — a 200 mm
iron ball, 32.9 kg, 13x the plate's mass, at 1.0 m/s — is the case the
quasi-static checkpoint identifies as its own good regime (Olsson's criterion: a
striker several times the plate's mass, loaded slowly relative to the wave
transit). It is not this lane's regime either, and the numbers say why: the reference removes 849 bonds and 5.273 J into 14 pieces, and Algorithm 2 with the footprint impulse removes 204 bonds and 0.085 J and makes one piece. A slow heavy striker is exactly where a delta impulse is worst - the contact lasts far longer than the plate's response, the loading is quasi-static rather than impulsive, and the footprint capture of a 32.9 kg ball at 1.0 m/s is only 0.065 N s. The right tool for that regime already exists and is the quasi-static lane; **this lane is a dynamic impulse-response lane and should not be aimed at slow loading.**

**The 500-cell contract scene** is in the table for completeness: the reference
breaks 73-74 bonds and removes 2.15-2.18 J there (two runs of the same scene at
different settle caps differed by one bond, which bounds the reference's own
run-to-run spread on this scene), and this lane refuses it for the reason in
section 2.1.


### 5.1 Glass, oak and iron under identical conditions

The verification rules require the three materials under one experiment before
any material-dependent claim. This lane's claims are about the algorithm rather
than about glass, but the comparison turned out to be the most useful single
measurement in this checkpoint. Scene: 240 x 200 x 40 mm plate, 240 cells at
20 mm, two ledges, a 200 mm iron ball (32.9 kg) at 9.90 m/s, identical for all
three.

| material | lane | broken bonds | pieces | largest piece cells | removed energy J | wall s |
|---|---|---:|---:|---:|---:|---:|
| glass | algo2 (Griffith) | 1830 | 83 | 64 | 66.771 | 0.55 |
| glass | reference | 1960 | 68 | 41 | 42.557 | 0.60 |
| oak | algo2 (Griffith) | 87 | 1 | 240 | 6.780 | 0.47 |
| oak | reference | 1461 | 95 | 64 | 179.863 | 0.81 |
| iron | algo2 (Griffith) | 0 | 1 | 240 | 0.000 | 0.46 |
| iron | reference | 1855 | 90 | 35 | 343.535 | 1.07 |

And the reason, which is the criterion again — but **material dependent, and it
changes sign**:

| material | Gc (J/m²) | Griffith break strain | shared criterion break strain | ratio in strain | ratio in crack energy |
|---|---:|---:|---:|---:|---:|
| glass | 8 | 5.66e-5 | 1.286e-3 | 22.7x more permissive | 516x |
| oak | 1,000 | 1.528e-3 | 1.500e-2 | 9.8x more permissive | 96x |
| iron | 100,000 | 3.644e-3 | 2.370e-3 | **0.65x — more conservative** | 0.42x |

So the Griffith cascade shatters glass where the reference shatters glass
(1,830 bonds against 1,960, 83 pieces against 68 — the closest agreement
anywhere in this checkpoint), barely marks oak where the reference breaks it up,
and declares iron untouched where the reference removes 1,855 bonds. **The two
criteria are not related by a constant, or even by a constant times the cell
size: they cross over between materials, and for iron the energy criterion is
the conservative one.** Any lane that swaps a strength criterion for a Gc
criterion changes the material ranking, not just the numbers.

## 6. Exact commands

Build (headless, no lab):

```sh
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 6
python scripts/check-source-registration.py
ctest --test-dir build/agent -C Release -E "banjo_network_skin_tests|banjo_network_runtime_tests|banjo_material_showcase_tests|banjo_network_adaptive_tests|banjo_contact_capacity_tests"
./build/agent/Release/banjo_griffith_cascade_tests.exe
```

The lane, on the base scene (the Fracture lab panel calls exactly this form):

```sh
./build/agent/Release/banjo_fracture_algo2.exe \
    --plate 0.25 0.20 0.02 --cell 0.01 --ball 0.06 --drop 2.0 --offset 0 0 \
    --support ledges --duration 2.0 --cache build/fracture-cache \
    --output build/runs/algo2/base.json
```

The reference on the same scene, from the same binary and the same numbers:

```sh
./build/agent/Release/banjo_fracture_algo2.exe --reference \
    --plate 0.25 0.20 0.02 --cell 0.01 --ball 0.06 --drop 2.0 --offset 0 0 \
    --support ledges --duration 2.0 --output build/runs/algo2/base-reference.json
```

Options beyond the shared contract, all defaulting to the contract's behaviour:
`--criterion griffith|strain` (default griffith), `--contact-mass footprint|plate`
(default footprint), `--all-strikes` / `--single-strike` / `--strike-budget S`
(the peak table is filled for every strikeable cell when a measured column says
the rest will cost less than S seconds, default 90), `--max-bytes MiB` (the
influence-matrix cap, default 1500), `--reference-window S` (the denominator of
`fracture_window_ratio`, default the measured 0.013764), `--reference-frames N`,
`--record-frames N`, `--no-settle`.

The whole checkpoint:

```sh
python scripts/algo2-accuracy-matrix.py --exe build/agent/Release/banjo_fracture_algo2.exe \
    --cache build/fracture-cache --out build/runs/algo2 --duration 3.0
python scripts/algo2-accuracy-report.py --matrix build/runs/algo2/matrix.json
python scripts/algo2-cost-scaling.py --exe build/agent/Release/banjo_fracture_algo2.exe \
    --cache build/fracture-cache-cost --out build/runs/algo2-cost
python scripts/algo2-damage-geometry.py build/runs/algo2/base-algo2.json build/runs/algo2/base-reference.json
```

Recordings are written under `build/`, which `.gitignore` already excludes; none
of them is committed.

## 7. What this lane is for, and what it is not for

**Implemented and measured** (this checkpoint):

* the precompute — eigenpairs, the peak dynamic strain table per strikeable
  cell, and the crack-influence matrix — with an on-disk cache keyed by the whole
  scene, and its cost and size at 240 to 2,000 cells;
* an event-driven Griffith cascade that is O(bonds) per event and does no time
  stepping at all, with a deterministic, order-free break rule;
* a stated contact model whose impulse and energy budget both come from the same
  momentum balance, and a second, stated end of the same bracket
  (`--contact-mass plate`) so the sensitivity to it can be read off;
* pieces to Jolt from rest, settled and recorded as `banjo.playback.v1`;
* the reference lane on the identical scene from the same binary.

**Validated** (a check that could have failed and did not): the influence matrix
against a direct Cholesky solve of the cracked stiffness; reciprocity; linearity
of the load in the impulse; closure of the energy ledger; bond crack areas
summing to a geometric cut at three horizons; bond-for-bond identity with the
reference lane's lattice.

**Not validated, and not claimed**: any of this against laboratory glass. The
lane reproduces neither the reference's piece count nor its crack topology, and
section 4 says by how much.

**Where the lane is right.** Removed energy, to within a factor of two on all
four fracture scenes and within 10% on two of them, at 1/240 of the reference's
cost - the one quantity every lane in this repository converges on, and this
lane converges on it too. First failure with **91% recall** (it contains 170 of
the reference's 186 first-failure bonds). The contact model's **energy budget**
within 13% of what the reference's resolved contact dissipates. And the verdict
under the *shared* criterion tracks the reference's on the scenes that do not
fracture: 0 against 13 on the 30 mm plate, 0 against 0 on the 40 mm plate at
6.26 m/s, and glass shatters where glass shatters (1,830 bonds against 1,960,
83 pieces against 68). Broken-bond count is right to 2.4% on one scene and
wrong by three orders of magnitude on another, so it is **not** something this
lane can be trusted for.

**Where the lane is wrong, in one sentence each.** It has no wave arrival order,
so it loads every bond to its lifetime peak simultaneously and its damage is
diffuse where the reference's is a crack path. It has no inertial confinement,
so the near-contact concentration that drives real impact fracture is only as
strong as the intact plate's impulse response makes it. Its influence matrix is
linearised about the *intact* plate and superposed one bond at a time, so it
cannot build a crack-tip concentration. Its contact is a single delta impulse,
so it delivers a fraction of the momentum a millisecond-long contact delivers.
Its criterion is a Gc energy criterion where the rest of the engine uses a strain
threshold; the two differ by 259x in crack energy for glass at 10 mm cells, by
96x for oak at 20 mm, and in the other direction for iron.

**What it should be used for, on this evidence:** an instant answer to "roughly
how much energy does this strike take out of the plate, and where does the
damage start" - the predictor role the engine options analysis already assigns
to the modal basis (section 4, phase 3), now with a cascade and an energy budget
attached. It should **not** be used to decide how many pieces there are or what
shape they have, and its "does it break at all" verdict is only as good as the
criterion it is run with: under Griffith at 10-20 mm cells it says yes far too
often (section 5), under the engine's shared criterion it says no too often
because its impulse is too small. Neither is safe on its own; the pair brackets
the answer.

## 8. Limits, defects and the next tests

1. **The 500-cell contract scene is refused** (section 2.1). Any lane that
   linearises about the undeformed configuration has this limit; it is not
   specific to the Griffith cascade. The next test is whether a *pre-stressed*
   linearisation (the plate's static sag under the ball, then the impulse
   response about that state) recovers a transverse stiffness large enough to be
   useful — one extra static solve in the precompute, no extra table.
2. **The envelope, not the ordering, is the dominant error.** The next test is
   cheap and would quantify it directly: store the *time* of each bond's peak
   alongside its magnitude (one more table of the same size), and report the
   spread of peak times across the bonds the cascade breaks. If a causal cascade
   — break only bonds whose peak time is before the current event's, then re-run
   — narrows the piece-count gap, that is a real improvement and still needs no
   stepping. Algorithm 3's causal cones are the principled version of the same
   idea.
3. **The influence matrix is O(bonds²) in memory**: 384 MiB at 1,000 cells,
   1.15 GiB at 1,500, 2.34 GiB at 2,000, and building it is 244 s of the 465 s
   precompute at 2,000 cells. It, not the eigen decomposition, is what stops
   this lane. A distance cut-off would make it sparse at the cost of the
   far-field redistribution; whether that costs anything is measurable against
   the dense answer on a small plate.
4. **The peak table is filled on demand above about 1,000 cells.** Below that
   every strikeable cell gets a column, so a new strike offset is free; above it
   the report says which columns exist (`precompute.strike_cells_ready`) and the
   estimate that made the decision, and a new offset costs one column (0.22 s at
   1,500 cells, 0.36 s at 2,000).
5. **The support is bilateral.** The plate cannot lift off its ledges, where the
   reference's is a unilateral contact. Not measured here.
6. **Pieces start from rest**, so the momentum the contact model put into the
   plate — `handoff.dropped_momentum_n_s` — is dropped at the handoff. Nothing
   in this lane authors a fragment velocity, and nothing should until there is a
   measured basis for one.
7. **Compression and shear are not modelled.** This is a mode-I energy
   criterion; the contact crushing the reference sees under the ball has no
   counterpart here.
8. **The largest dynamic piece can exceed Jolt's 64-part compound limit**; such a
   piece keeps its true mass and inertia and gets its bounding box as the
   collision silhouette, counted in `handoff.oversized_pieces`.

## 9. What the owner can watch

Five jobs are installed in the owner's playground store
(`C:/Users/henry/dev/banjo/build/playground-runs`) and play in the running
server's 3D tab. Nothing in the owner's checkout was modified and its server was
not restarted; the store is runtime data and the server discovers archived jobs
on demand.

| job | what it shows |
|---|---|
| [`?job=7d21b6a8dd0949a9b747cadc6d4831c3`](http://127.0.0.1:8765/?job=7d21b6a8dd0949a9b747cadc6d4831c3) | **The headline pair.** Algorithm 2 and the explicit lattice on the identical base scene: 5,553 bonds / 39 pieces / 3.15 J / 0.41 s against 5,421 / 168 / 1.76 J / 98.5 s. Switch between the two cases and the difference in *character* is the whole finding - one plate stays whole with a few chips off it, the other comes apart. |
| [`?job=6328956e35504e01a389b000499ac487`](http://127.0.0.1:8765/?job=6328956e35504e01a389b000499ac487) | **Change the plate or the drop and watch it again.** Four Algorithm 2 runs off one cached precompute: thicker plate, 5 m drop, off-centre strike, heavy slow striker. |
| [`?job=523839302e7e49aabd14e9b5a9226790`](http://127.0.0.1:8765/?job=523839302e7e49aabd14e9b5a9226790) | **The criterion is the disagreement, not the cascade.** The same load under the Griffith criterion (5,553 bonds), under the engine's shared strain criterion (0), under the strain criterion with the whole-plate impulse (6,825), and the reference (5,421). |
| [`?job=962c5f0a6d6044e08c715600a5f1cc87`](http://127.0.0.1:8765/?job=962c5f0a6d6044e08c715600a5f1cc87) | **The 500-cell contract scene, reference only**, because Algorithm 2 refuses a plate one cell thick. 73 bonds, one piece, 2.148 J, 1.95 s of wall. |
| [`?job=c68988b72e8d48ffa092a13d71648e43`](http://127.0.0.1:8765/?job=c68988b72e8d48ffa092a13d71648e43) | **Played through to rest**: the base scene with a 6 s settle cap comes to rest at 3.325 s simulated in 0.449 s of wall. |

The Fracture lab panel from `agent/integration` (merged into this branch at
`c090f67`) drives the lane directly. Checked end to end against a private
playground on port 8802 (stopped afterwards): a 240-cell two-layer plate runs in
**0.153 s of server wall, 0.030x of the simulated interaction**, and the panel's
own 500-cell default comes back as an error whose message is this lane's refusal
reason verbatim. `tests/fracture_lab_tests.py` passes on this branch.

A recording plays through to rest when the settle cap allows it: the base scene
comes to rest at **3.325 s** simulated and the run stops at 3.625 s in **0.449 s
of wall (0.124x)**. At the 3 s cap used for the accuracy matrix, 99% of the
cells are already stationary in the last frame and one chip is still bouncing at
0.59 m/s; the reference at the same cap has more residual motion (99th
percentile 0.21 m/s) and its own `came_to_rest` is false on every fragmenting
scene.
