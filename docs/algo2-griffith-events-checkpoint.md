# Algorithm 2 checkpoint: an event-driven Griffith cascade with no time stepping

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

The lane works, it is the cheapest of the three by a wide margin, and it is
wrong in a specific and measurable way. On a 1,000-cell glass plate struck by a
60 mm iron ball at 6.26 m/s it reproduces the explicit lattice's broken-bond
count to **+2.4%** (5,553 against 5,421) and its **removed energy to +79%**
(3.15 J against 1.76 J), while getting the **piece count wrong by 4.3x**
(39 against 168) and the **largest piece wrong by 3.1x** (956 cells against 304).
A warm rerun — change the drop height, change the strike offset — costs
**0.40 s of wall**, of which **60 ms is the cascade itself** and 0.27 s is
reading the cached tables back from disk; the reference costs **102 s** on the
same scene. The precompute is **58 s and 384 MiB** for that plate and is cached.
Two hard obstacles were found and both are reported rather than papered over:
**a plate one cell thick — the shared 500-cell contract scene — cannot be
expressed by this lane at all**, and **the Griffith criterion and the engine's
shared strain criterion disagree by a factor of 516 in crack energy at 10 mm
cells**, which is the single largest source of disagreement with the reference.

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
cells (50 x 40 x 2 = 4,000 cells, 11,040 free degrees of freedom). A dense
eigendecomposition at that size is O(n³) with the measured constant of section 3
— *estimate* 25 minutes for the eigen step alone and a 5.5 GiB influence matrix
— so it is outside this lane's envelope. **The lane's working envelope is a
plate at least two cells thick with at most about 3,000 free degrees of
freedom**, and it says so when it refuses.

### 2.2 The Griffith criterion and the shared strain criterion disagree by 516x in energy

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

The consequence for this checkpoint is that a raw Algorithm 2 / reference
comparison mixes two independent errors. Section 4 therefore reports both
criteria on the same loads, which separates them.

*(This is the fourth agent's territory; nothing in `fracture/BondFailure.{hpp,cpp}`
was changed here, and no tolerance was moved.)*

## 3. Cost

Measured on the base scene (a 250 x 200 x 20 mm glass plate on two ledges,
25 x 20 x 2 = 1,000 cells at 10 mm, 9,788 bonds, 840 free cells = 2,520 modes,
500 strikeable surface cells), and on a 240-cell scene for the small end.
`scripts/algo2-cost-scaling.py` reproduces the table; each size is run once with
an empty cache and once with the warm one.

The precompute is three costs with three different scalings:

| stage | scaling | 240 cells | 1,000 cells |
|---|---|---:|---:|
| eigenpairs of the intact plate | O(n^3) in free dofs | 0.14 s | 17.7 s |
| crack-influence matrix A | O(bonds^2 x modes) | 0.09 s | 14.1 s |
| peak-response table E, every strike cell | O(bonds x modes x samples x strikes) | 0.20 s (120 cells) | 26.3 s (500 cells) |
| cache write | bytes | 0.02 s | 0.22 s |
| **total, cold** | | **0.44 s** | **58.4 s** |
| **tables on disk** | bonds^2 x 4 B + strikes x bonds x 4 B | **20.0 MiB** | **384 MiB** |

A rerun with the cache warm - a different drop height, a different strike
offset, a different speed - costs:

| | 240 cells | 1,000 cells |
|---|---:|---:|
| read the tables back from disk | 0.014 s | 0.272 s |
| **the cascade itself** | **0.0039 s** | **0.057 s** |
| components, Jolt handoff, 3 s of settling, recording | 0.041 s | 0.077 s |
| **whole process, warm** | **0.059 s** | **0.407 s** |

So the fracture answer costs **57 ms at 1,000 cells** and the process around it
costs several times that. The cascade is `events x bonds` work: one event is two
passes over the bond list, about **10 microseconds at 1,000 cells**, and the
5,553 events of this scene are what make it 57 ms. On a scene where few bonds
break - the same plate under the shared strain criterion - the cascade is
**0.1 ms**. "Microseconds per event" is the honest claim; "microseconds per
impact" holds only when the impact breaks a handful of bonds.

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
| algo2, Griffith, plate impulse | 3.916 N s | refused: makes more pieces than Jolt's contact budget allows | | | | |

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
