# Energy-scaled bond failure: derivation, convergence ladder, and what still does not converge

Branch `agent/criterion-energy-scaled`, from `c38da39`. Written 2026-09-08.
Machine: Windows 11, Ultra 9 / RTX 5090, CPU-only build (`-DBANJO_BUILD_LAB=OFF`,
no CUDA toolchain). Every number below is measured on this branch unless it is
marked *estimate* or cited to another checkpoint.

Status labels: **implemented** (code exists and a CMake target builds it),
**validated** (a test or a measurement with a known answer confirms it),
**experimental result** (measured, no independent answer to check it against),
**hypothesis** (stated, not measured).

---

## 0. Headline

1. **The criterion now has a length scale and it is exact.** A crack costs the
   material's own `fracture_energy_j_m2` per unit area at every cell size and
   horizon, to 1e-12 relative, measured on generated lattices. Before, the same
   glass tile was made of a material 795 times tougher than glass at 20 mm cells
   and 199 times tougher at 5 mm.
2. **On a well-posed fracture problem the answer converges.** The pre-cracked
   strip advances 25.0 / 42.5 / 47.5 mm at 10 / 5 / 2.5 mm cells (+70%, +12%),
   and Griffith's threshold is reproduced: the crack runs at G/Gc = 1.0 and not
   at 0.8.
3. **On the tile the answer does not converge, and the brief's gate is not met.**
   Piece count still grows 3-6x per level under the new law (6-15x under the
   old); largest piece and removed energy do not settle. One gate item improves:
   removed energy under timestep refinement, +0.55% against -9.8%.
4. **Why is now a number, not a mystery.** The pulverisation number
   `R = (v/c_L)/s_c` is 25-13 for glass and 1.2-0.6 for oak on this ladder.
   Where R > 1 the impact wave takes every bond it reaches past the threshold -
   93% of the 20 mm glass tile's bonds break - so the fragment size is the cell
   size and a piece count counts cells. Glass under this strike would need about
   31 um cells to be resolvable at all; that is the same bound as its 0.28 mm
   Irwin length, reached from the lattice side.
5. **The crack speed check passes.** 0.39 c_R against Freund's 0.375 estimate at
   G/Gc = 1.6 (4%), never super-Rayleigh, over 0.6 c_R only at G/Gc = 2.4 where
   the crack is branching.
6. **The old law is untouched.** Bit for bit, over 48 material/cell/horizon
   combinations and 40,632 generated bonds.

---

## 1. The problem, restated as a number

`docs/engine-options-analysis-2026-09-07.md` section 1, Wall 2: the same 8 m/s
strike on the same tile gives 3 pieces at 20 mm cells and 672 at 10 mm. The
diagnosis was that the bond failure criterion has no length scale, so the energy
needed to open a unit of crack area is proportional to the cell size.

That is now measured rather than asserted. Under the strain-threshold law, a
{100} crack plane through the glass tile costs

| cells | crack energy the old law charges | glass's declared `fracture_energy_j_m2` | ratio |
|---|---:|---:|---:|
| 20 mm | 6,364 J/m^2 | 8 J/m^2 | 795x |
| 10 mm | 3,182 J/m^2 | 8 J/m^2 | 398x |
| 5 mm | 1,591 J/m^2 | 8 J/m^2 | 199x |

(horizon 2; `banjo_criterion_energy_tests` test 4. At horizon 3 it is
27,000 / 13,500 / 6,750 J/m^2.) The tile is not made of glass at any of those
resolutions: at 20 mm it is made of something 795 times tougher than glass, and
halving the cells halves that toughness. Nothing about the answer can converge
while the material itself changes with the mesh.

---

## 2. Derivation (validated by `banjo_criterion_energy_tests`)

### 2.1 What this lattice's bonds actually are

`compileElasticLatticeReference` (`src/material/MaterialCompiler.cpp`) gives the
material a single bond compliance

    C0 = 1 / (E h^2 / (m h)) = m / (E h)

for cell size h, nominal modulus E and horizon m cells. `buildBonds`
(`src/matter/Lattice.cpp:152`) divides it by the horizon weight
`1 / max(1, |o|^2)` for a bond of integer grid offset o, so the bond's own
compliance, stiffness and rest length are

    c(o) = m |o|^2 / (E h)      k(o) = E h / (m |o|^2)      L(o) = |o| h

Bonds join every pair of nodes with `1 <= |o| <= m`, one bond per unordered pair.

**Fact 1 - the stored energy of a bond does not depend on its length.** At
stretch s the extension is `s L(o) = s |o| h`, so

    U(s) = 0.5 k(o) (s |o| h)^2 = 0.5 (E h / (m |o|^2)) s^2 |o|^2 h^2
         = E h^3 s^2 / (2 m)

with `|o|` gone. Every bond in the lattice, near neighbour or far, stores the
same energy at the same stretch. The whole derivation rests on this, and it is
measured directly on generated lattices (test 1: 4 distinct rest lengths at
horizon 2, 8 at horizon 3, all agreeing to 1e-13 relative).

**Fact 2 - the lattice is a cubic elastic solid whose constants follow.** Under
an affine strain e a bond along unit direction n extends by `L (n.e.n)`, so the
energy density is `(E / 2m) sum_half (n.e.n)^2` and

    C11 = E sum_half n_x^4 / m       C12 = C44 = E sum_half n_x^2 n_y^2 / m

(the Cauchy relation, as any central-force lattice must obey). Measured under
affine strain on a generated lattice, to 2e-5 relative (test 2):

| horizon | half offsets | bonds at an interior node | C11 / E | C12 = C44 / E | E_eff / E | nu_eff | Zener A |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2 | 16 | 32 | 1.7222 | 0.4722 | 1.5190 | 0.2152 | 0.7556 |
| 3 | 61 | 122 | 3.9314 | 1.4232 | 3.1748 | 0.2658 | 1.1348 |

Two consequences that are easy to get wrong: the lattice's Young modulus is
**not** the E it was fed (1.52x that at horizon 2, 3.17x at horizon 3), and the
lattice is **not** isotropic (Zener A = 1 would be isotropy). The wave speeds
and the Rayleigh speed in section 5 use these constants, not the nominal ones.

### 2.2 The crossing count

**Fact 3.** For a {100} lattice plane - the plane between two x layers - one node
column at fixed (y, z) contributes exactly `|o_x|` crossing bonds per half
offset o, and there are `1 / h^2` columns per unit area. So

    bonds crossing a unit area of a {100} plane = N_100 / h^2,
    with N_100 = sum_half |o_x|

`latticeHorizonGeometry` walks the same offsets `buildBonds` walks and sums
them: **N_100 = 11 at horizon 2, 70 at horizon 3.**

The same argument gives `sum_half |o.n| / h^2` for a plane of any normal n
(the lower endpoints of the crossing bonds fill a slab of thickness `|d.n|`
against the plane, and the node density is `1/h^3`), so the crack energy the
threshold buys depends on which lattice plane the crack runs on. That
anisotropy is smaller than one might fear, and it is a reason to prefer
horizon 3:

| horizon | N_100 | N_110 | N_111 | worst-case error in Gc |
|---|---:|---:|---:|---:|
| 2 | 11.000 | 11.314 (1.029x) | 12.124 (1.102x) | +10.2% |
| 3 | 70.000 | 69.297 (0.990x) | 69.282 (0.990x) | -1.0% |

*Implemented and derived, not separately measured*: the {100} case is the one
checked against a generated lattice (test 3b). A crack that runs on a {111}
plane at horizon 2 therefore costs 10% more than the material's Gc, and 1% less
at horizon 3.

### 2.3 The threshold

The criterion removes a bond outright at full damage. `fracture/BondFailure.hpp`
is explicit that a partially damaged bond is mechanically identical to an
undamaged one, so there is no softening: the bond leaves carrying all of its
stored energy. Opening one unit of {100} crack area therefore costs

    G_lattice = (N_100 / h^2) . U(s_end) = N_100 E h s_end^2 / (2 m)

Setting that equal to the material's `fracture_energy_j_m2` gives the law:

> **s_c = sqrt( 2 m Gc / (N_100 E h) )**

This is the direct analogue of Silling and Askari's bond-based critical stretch
`s0 = sqrt(5 Gc / (9 k delta))` (*A meshfree method based on the peridynamic
model of solid mechanics*, Computers & Structures 83, 2005), derived for **this**
lattice's compliance rule and horizon weighting rather than for their uniform
micromodulus, and it carries the same inverse-square-root scaling in the length
scale: at fixed horizon ratio, s_c is proportional to h^-1/2.
`energyScaledCriticalStretch` implements exactly this line.

### 2.4 The strength bound

s_c and the strength stretch `s_sigma = break_strain_multiplier . sigma_t / E`
describe the same material and disagree whenever the cell size is far from the
material's Irwin length `l_ch = E Gc / sigma_t^2`. The law takes the smaller:

    s_end   = min( s_c , s_sigma )
    s_start = s_end . (damage_strain_multiplier / break_strain_multiplier)

which is Bazant's crack-band rule (*Crack band theory for fracture of concrete*,
Materiaux et Constructions 16, 1983): where the element is larger than the
process zone the energy governs and the effective strength must fall; where it
is smaller the strength governs. Which one bites is decided by the material, not
by taste, and test 6 checks the reported `strength_bound_active` flag against
`min(s_c, s_sigma)` in every case:

| material | l_ch | s_c at 20 / 10 / 5 mm | s_sigma | governed by |
|---|---:|---|---:|---|
| glass | 0.28 mm | 4.56e-5 / 6.45e-5 / 9.12e-5 | 1.29e-3 | energy, everywhere |
| oak | 1.48 mm | 1.23e-3 / 1.74e-3 / 2.46e-3 | 1.50e-2 | energy, everywhere |
| iron | 338 mm | 2.94e-3 / 4.15e-3 / 5.87e-3 | 2.37e-3 | strength, everywhere |

The compressive and shear ramps are left exactly as `withStrengthDerivedFailure`
produced them. Gc is a mode-I crack energy and the catalogue carries no second
and third fracture energy to calibrate the other two modes against; this is a
stated limitation, not an oversight (section 8).

### 2.5 An independent check on the constant, not just the scaling

The derivation is never told about linear elastic fracture mechanics, so LEFM
can be asked whether its answer is sane. A crack of length a in a body of
modulus E' propagates at `sqrt(E' Gc / (pi a))`. Take a to be one cell, which is
what a lattice that resolves a crack in cells means, and compare with the stress
the criterion actually fails at, `E_eff s_c`. Both scale as h^-1/2, so their
ratio is a pure number:

    E_eff s_c / sqrt(E_eff Gc / (pi h)) = sqrt( (E_eff / E) . 2 pi m / N_100 )

which is **1.317 at horizon 2 and 0.925 at horizon 3**, for every material and
every cell size (test 7). The criterion fails a cell-sized ligament within a
third of where Griffith says it should. Nothing in the derivation was fitted to
make that come out; it is a consequence of the compliance rule and the crossing
count, and it is the strongest evidence that the constant - not just the
h^-1/2 scaling - is right.

### 2.6 What the law is not

It is not a cohesive-zone law. The engine's damage counter does not soften the
bond, so the traction-separation curve this implies is a rectangle ending in a
snap, not Bazant's linear softening ramp. Section 6 measures the consequence and
it is the most important caveat in this document: a snap criterion whose
threshold sits far below the material's strength produces **diffuse** damage
rather than a localised crack, because every bond the passing wave takes over
the threshold breaks at once. Softening is the fix and it needs a solver change
this branch does not make (section 8.3).

---

## 3. Selection, and the old law's bit-for-bit guarantee

`MaterialDefinition::failure_law` selects `BondFailureLaw::StrainThreshold` (the
default, unchanged) or `BondFailureLaw::EnergyScaled`. `withFailureLaw`
dispatches; `compileBrittleMaterial` and `TileImpactScene` route through it;
`banjo_fast_lattice_run` exposes `--failure-law strain-threshold|energy-scaled`;
an unknown name throws rather than silently defaulting.

**Validated.** `banjo_criterion_energy_tests` test 5 compares, for 8 presets x 3
cell sizes x 2 horizons (48 combinations), the six damage thresholds and the bond
compliance produced by `withFailureLaw` under the strain-threshold law against
`withStrengthDerivedFailure`, by `memcmp`; then the 40,632 `BondRest` structures
the box generator writes from them, byte for byte. All identical. The three
sibling fracture lanes see no change at all until they ask for the new law by
name.

---

## 4. Tests

`ctest --test-dir build/agent -C Release -R banjo_criterion_energy_tests`.

| # | what it checks | how |
|---|---|---|
| 1 | per-bond energy is length-independent | every bond of generated 8^3-cell lattices at 20/10/5 mm and horizon 2/3 stores E h^3 s^2 / 2m, to 1e-13 |
| 2 | the lattice's C11 and C44 are the derivation's | affine strain on a generated lattice, energy density over full-complement nodes, 2e-5 |
| 3a | **a single bond pair reproduces Gc** | a two-node lattice broken at the derived stretch releases Gc . h^2/N_100, its share of a unit crack face: 4 presets x 3 cells x 2 horizons, 1e-12 |
| 3b | **a unit crack face reproduces Gc at three resolutions** | every bond crossing the mid-plane of a generated block, summed over complete columns, over their area: glass and oak, 20/10/5 mm, horizons 2 and 3, 1e-12 |
| 4 | the scaling | s_c(h/2)/s_c(h) = sqrt(2) and G_lattice flat in h, both to 1e-13; the old law's G_lattice scales as h |
| 5 | **the old law is unchanged bit for bit** | 48 material/cell/horizon combinations and 40,632 generated bonds, `memcmp` |
| 6 | the strength bound bites where the Irwin length says | `strength_bound_active` against `min(s_c, s_sigma)` for iron, glass, oak |
| 7 | **the implied strength agrees with LEFM for a cell-sized flaw** | `E_eff s_c / sqrt(E_eff Gc / (pi h))` is 1.317 (horizon 2) and 0.925 (horizon 3), independent of material and cell size, to 1e-12 |
| 8 | names | `parseBondFailureLaw` round trips and refuses an unknown name |

The whole suite passes: **87 of 87 CTest suites**, 81 s, with the five the brief
excludes not run and no tolerance changed anywhere.
`python scripts/check-source-registration.py` reports 206 sources registered and
nothing unbuilt.

---

## 5. Physics check (a): the pre-cracked strip

**Implemented**: `tools/criterion_strip_probe.cpp` (`banjo_criterion_strip_probe`).

### 5.1 The scene, and why its answers are known in advance

A rectangular strip of uniform cubic cells is clamped along its top and bottom
faces (the outermost node layer of each is pinned by giving it zero mass, which
is how the XPBD solve expresses an infinite mass) and released from rest in
uniform tension along y. A slit of length a0 is cut on the mid-height plane by
removing every bond that crosses it left of a0. Nothing else acts: no gravity, no
contact, no damping, no prescribed motion after t = 0.

This is the classical constant-energy-release strip. The material ahead of the
tip carries strain energy density W over the full height H; the material behind
it has unloaded completely; so the energy release rate

    G = W H = E_eff e0^2 H / 2

does not depend on crack length. The strip starts in the uniaxial-**stress**
state the grips and the free side faces hold it in (e_yy = e0,
e_xx = e_zz = -nu e0, using the lattice's own nu), so it begins in equilibrium
instead of ringing. e0 is set from a requested G/Gc, and the probe refuses to run
when that strain would reach the removal stretch on its own, because then there
is no crack to measure, only a disintegrating bulk.

Crack area is measured in the criterion's own accounting - broken mid-plane bonds
times h^2/N_100, exactly the counting the threshold was derived from - so it does
not depend on guessing where a ragged front lies. The rectangle the tip swept is
reported next to it and their ratio says how straight the front is.

### 5.2 The Griffith threshold: does the crack run exactly when G > Gc?

*Validated.* Glass, 5 mm cells, horizon 2, 0.40 x 0.10 x 0.04 m strip (12,800
cells, 81,020 bonds), 0.10 m slit, 300 us window. Only the requested G/Gc
changes between rows; nothing else.

| G/Gc | loading strain | as a fraction of s_c | tip advance | new crack-plane bonds | crack runs? |
|---:|---:|---:|---:|---:|---|
| 0.6 | 3.005e-5 | 0.330 | 0 | 0 | **no** |
| 0.8 | 3.470e-5 | 0.381 | 0 | 0 | **no** |
| 1.0 | 3.879e-5 | 0.425 | 1 cell | 69 | marginal |
| 1.2 | 4.249e-5 | 0.466 | 3 cells | 206 | yes |
| 1.6 | 4.907e-5 | 0.538 | 8.5 cells | 674 | yes |
| 2.4 | 6.010e-5 | 0.659 | 59.5 cells (the whole strip) | 4,591 | yes |

**The threshold sits between G/Gc = 0.8 and 1.0.** Griffith's criterion is
reproduced by a lattice that was never told about it: the crack advances when
the energy the strip can release per unit of new crack area exceeds the
material's declared `fracture_energy_j_m2`, and stops when it does not. The
loading strain is only 0.33 to 0.66 of the removal stretch throughout, so the
bulk is nowhere near failing on its own; what fails is the crack tip.

### 5.3 Crack speed against the Rayleigh speed, and dissipation against Gc

*Experimental result*, with LEFM's steady-state estimate `v = c_R (1 - Gc/G)`
(Freund, *Dynamic Fracture Mechanics*, ch. 7) as the comparison. c_R is this
lattice's own Rayleigh speed from the constants of section 2.1 (3,313 m/s for
glass, 2,593 m/s for oak), not the nominal material's.

| run | cells | G/Gc | tip speed | v / c_R | LEFM v / c_R | dissipated per crack area | / Gc | off-plane : plane breaks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| glass, 5 mm | 12,800 | 1.6 | 1,297 m/s | **0.391** | 0.375 | 10.23 J/m^2 | 1.279 | 405 : 674 |
| glass, 5 mm | 12,800 | 2.4 | 2,307 m/s | **0.696** | 0.583 | 11.97 J/m^2 | 1.496 | 6,128 : 4,591 |
| glass, 2.5 mm | 102,400 | 1.6 | 1,070 m/s | **0.323** | 0.375 | 12.03 J/m^2 | 1.503 | 2,420 : 2,750 |
| oak, 5 mm | 12,800 | 1.6 | 332 m/s | **0.128** | 0.375 | 1,261 J/m^2 | 1.261 | 550 : 766 |

**Speed. The gate holds where the crack is a single crack.** No row is
super-Rayleigh, which a mode-I crack must not be. At G/Gc = 1.6 the tip runs at
0.32 to 0.39 c_R, comfortably under the 0.6 c_R branching bound, and the 5 mm
glass row matches Freund's estimate to **4%** - a much sharper agreement than
the gate asks for. At G/Gc = 2.4 the tip reaches 0.696 c_R, over the bound and
19% above the LEFM estimate; that row is also the one where off-plane breaks
outnumber crack-plane breaks 1.33 : 1, which is what branching looks like in a
lattice. So the criterion respects the Rayleigh limit, follows the speed against
driving-force relation to within 4-19%, and crosses 0.6 c_R only when the crack
stops being one crack.

Oak is the outlier: 0.128 c_R against an estimated 0.375. Oak's crack front is
slower than LEFM by a factor of three under the same relative driving force.
*Hypothesis, not measured*: oak's shear ramp is only twice its energy-scaled
tensile one (4.95e-3 against 2.46e-3, where glass's is 28x), so oak's crack tip
sheds part of its driving energy into shear failure off the plane instead of
advancing.

**And on this problem the answer converges.** The strip is a well-posed,
localised fracture problem - one crack, driven at a known energy release rate,
with no pulverisation anywhere - and it is the one place in this branch where an
outcome converges under cell refinement. The same strip, same loading, same
300 us window, only the cell size changing:

| cells | lattice | crack advance in 300 us | change | new crack-plane bonds |
|---|---:|---:|---:|---:|
| 10 mm | 1,600 cells, 4 thick | 25.0 mm | | 96 |
| 5 mm | 12,800 cells, 8 thick | 42.5 mm | +70% | 674 |
| 2.5 mm | 102,400 cells, 16 thick | 47.5 mm | **+12%** | 2,750 |

That is what convergence looks like, on the same criterion and the same solver
that will not converge on the tile in section 6. The difference is the problem,
not the law: here the fracture is localised and the fragment scale is many cells,
there it is not.

**Dissipation.** The criterion removes 1.26 to 1.50 Gc per unit of crack area,
where the area is counted by the crack-plane bonds it broke. The spread is not
calibration error, it is where one draws the crack: counting the off-plane
breaks into the area as well would put the same four rows at 0.65 to 0.80 Gc.
The honest statement is **Gc to within a factor of about 1.5, with the ambiguity
in the definition of the crack area rather than in the threshold**, against a
unit test (3b) that puts the ideal figure at exactly Gc to 1e-12. A crack in a
lattice is a band a few cells wide, not a surface.

### 5.4 The same strip under the old law

*Validated, and it is the clearest single demonstration of the defect.* Running
the identical strip at G/Gc = 1.6 under the strain-threshold law: the loading
strain is 3.8% of that law's removal stretch, and **nothing happens at all** -
0 bonds break, the tip does not move. The old law charges 1,591 J/m^2 per unit
crack area at 5 mm cells against glass's 8, so a strip loaded to 1.6x glass's
fracture energy is 199 times too weak to crack it.

Drive the old law at the same fraction of *its own* removal stretch instead
(G/Gc = 318.4, giving the identical 0.538 ratio) and its crack does run - and
what it costs is the whole point:

| law | driving G | tip speed | v / c_R | dissipated per crack area | as a multiple of glass's Gc |
|---|---:|---:|---:|---:|---:|
| energy-scaled | 12.8 J/m^2 | 1,297 m/s | 0.391 | 10.2 J/m^2 | **1.28** |
| strain-threshold | 2,547 J/m^2 | 242 m/s | 0.073 | 1,993 J/m^2 | **249** |

The old law's crack consumes 249 times the material's fracture energy for every
square metre it opens, and crawls at a fifth of the speed because it is dragging
that cost. 249 / 199 = 1.25 is the same discrete overshoot the energy-scaled law
shows at 1.28, so the two laws differ by exactly the factor the derivation says
they should and by nothing else.

### 5.5 The lane's own energy leak

XPBD damps the modes it cannot resolve; at `dt_factor 0.5` the fastest bond mode
has `omega dt = 1`. Measured on this very scene while the crack is still
standing still: **0.0059 to 0.0076% of the stored energy per microsecond**
(0.07%/us with no crack at all, in the sub-threshold rows). Over the whole
300 us run the ledger closes 22.4% low. That leak is why the *elastic energy
released* per unit area cannot be used as the check and the *dissipated* energy
is used instead: the criterion's own removal accounting is exact, while the
strip's potential-energy drop is contaminated by numerical damping. The leak is
a property of `BrittleBondSolver` and of the fast lattice lane that reproduces it
bit for bit, not of the criterion, and it is unchanged by the failure law
(0.06949% per us for both laws in the rows where nothing breaks).

**Horizon 3 on this strip is not a valid test at this geometry.** At horizon 3
the lattice's effective modulus is 3.17x the nominal E rather than 1.52x, while
s_c falls, so the bulk loading needed for G/Gc = 1.6 reaches 0.77 of the removal
stretch instead of 0.54 and the strip disintegrates at the grips (46,277
off-plane breaks against 760 on the plane). The requirement is
`(G/Gc) . N_100 h / ((E_eff/E) m H) < ~0.3`, which at horizon 3 needs a strip
twice as tall; that run was not made. The horizon is exercised at 2 and 3
throughout the unit tests and section 2 instead.

---

## 6. The convergence ladder

### 6.1 The scene and the protocol

The bridge tile of `docs/fast-gpu-checkpoint.md`: 0.24 x 0.04 x 0.16 m of
uniform cubic cells resting on two ledges, struck in the middle of its top face
by a 4 cm iron ball (2.11 kg) falling at 8 or 12 m/s from a 2 mm gap. Fast
lattice CPU backend, double precision, `dt_factor 0.5`, one constraint iteration,
horizon 2 unless stated. 20 mm cells is 192 cells and 1,704 bonds; 10 mm is
1,536 and 18,852; 5 mm is 12,288 and 173,196.

Two protocol choices matter and both were arrived at by getting them wrong first.

1. **The same exit rule at every level, not the same duration.** A window sized
   for the 20 mm cascade (which ends at 2.6 ms) closes while the 5 mm cascade is
   still breaking bonds, and comparing a finished cascade with a truncated one
   measures the window, not the criterion. Every row runs until the cascade has
   been quiet for 2 ms, or until 12 ms, whichever comes first. Each row reports
   which of the two ended it (`exit`) and when its last bond broke, so a capped
   row is visible rather than silently mixed in.
2. **The ladder rows do not settle.** The piece count and the largest piece are
   measured at the handoff, before Jolt is involved. Running the rigid phase
   costs wall time and, at 5 mm with the energy-scaled law, overflows the rigid
   world outright (section 6.4). The recordings in section 10 settle fully.

### 6.2 Glass at 8 m/s

*Experimental result.* `exit` is `quiet` if the cascade stopped on its own and
`capped` if it was still breaking bonds at 12 ms. `s_c` is the removal stretch;
`G_lattice` the crack energy the law charges per unit {100} area (glass's Gc is
8 J/m^2); `measured Gc` the energy actually removed per unit of crack area in
the criterion's own accounting; `R` the pulverisation number of section 8.2.

| cells | law | exit | window | s_c | G_lattice | broken | of all bonds | pieces | >=1% | largest | removed | measured Gc | R | first failure | depth | wall |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 mm | old | quiet | 4.56 ms | 1.286e-3 | 6,364 | 276 | 16.2% | 4 | 3 | 1.92 kg | 28.25 J | 2,815 | 0.90 | 0.618 ms | 30 mm | 0.27 s |
| 10 mm | old | quiet | 6.17 ms | 1.286e-3 | 3,182 | 2,775 | 14.7% | 36 | 5 | 1.77 kg | 26.25 J | 1,040 | 0.90 | 0.334 ms | 10 mm | 10.6 s |
| 5 mm | old | capped | 12.0 ms | 1.286e-3 | 1,591 | 9,410 | 5.4% | 257 | 1 | 3.71 kg | 31.57 J | 1,476 | 0.90 | 0.275 ms | 5 mm | 462 s |
| 20 mm | new | quiet | 4.57 ms | 4.558e-5 | **8** | 1,590 | 93.3% | 103 | 25 | 0.34 kg | 0.62 J | 10.7 | 25.3 | 0.505 ms | 18 mm | 0.10 s |
| 10 mm | new | capped | 12.0 ms | 6.447e-5 | **8** | 16,550 | 87.8% | 414 | 6 | 0.94 kg | 3.15 J | 21.0 | 17.9 | 0.319 ms | 10 mm | 7.7 s |
| 5 mm | new | capped | 12.0 ms | 9.117e-5 | **8** | 103,122 | 59.5% | 1,526 | 1 | 3.30 kg | 1.53 J | 6.5 | 12.6 | 0.267 ms | 5 mm | 407 s |

Level-to-level change:

| law | step | pieces | largest piece | removed energy | broken bonds |
|---|---|---:|---:|---:|---:|
| old | 20 -> 10 mm | +800% | -8% | -7% | +905% |
| old | 10 -> 5 mm | +614% | +110% | +20% | +239% |
| new | 20 -> 10 mm | +302% | +176% | +408% | +941% |
| new | 10 -> 5 mm | +269% | +251% | -51% | +523% |

**Neither law converges for glass at 8 m/s, and they fail for different
reasons.** The old law does not converge because the material changes with the
mesh: it charges 6,364 J/m^2 per unit crack area at 20 mm and 1,591 at 5 mm, so
each refinement makes the tile four times cheaper to break. The new law charges
8 J/m^2 at every level - the material is now the same at every resolution, which
is what the criterion was built to fix - and still does not converge, because
8 J/m^2 is glass's real fracture energy and a 2.11 kg ball at 8 m/s pulverises
glass. 93% of every bond in the 20 mm tile breaks, 88% at 10 mm, 60% at 5 mm.
The pulverisation number R runs 25 to 13 across the ladder, so the impact wave
takes essentially every bond it reaches past the threshold and the fragment size
sits at the cell size at every level. Piece count then counts cells, and no
criterion can make that converge (sections 8.2 and 8.4).

The crack pattern changes with resolution under both laws. The first failure is
always on the strike axis (the centroid of the first-failing set sits within
3e-15 mm of it at every level, i.e. on it), but its depth below the tile's top face moves
from 30 mm at 20 mm cells - the bottom node layer, which is bending tension on
the underside of the bridge - to 5 mm at 5 mm cells, immediately under the ball.
Refining the mesh resolves the contact stress concentration better than it
resolves the bending, and the failure mechanism swaps. That is a non-convergence
of the *first failure location*, which `docs/fast-gpu-checkpoint.md` had found
robust to sweep order and to precision. It is not robust to cell size, and the
new law does not change it.

### 6.3 Oak at 8 m/s

Oak's Gc is 1,000 J/m^2, 125 times glass's, so the same strike opens far less
crack area and R falls to 1.20 / 0.85 / 0.60 across the ladder - the regime
where the criterion should be able to localise.

*Experimental result.*

| cells | law | exit | window | s_c | G_lattice | broken | of all bonds | pieces | largest | removed | measured Gc | R | tensile / shear | wall |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 20 mm | old | quiet | 3.09 ms | 1.500e-2 | 148,500 | 104 | 6.1% | 3 | 1.053 kg | 14.01 J | 3,705 | 0.098 | 0 / 99 | 0.15 s |
| 10 mm | old | quiet | 5.34 ms | 1.500e-2 | 74,250 | 952 | 5.0% | 28 | 1.041 kg | 24.31 J | 2,808 | 0.098 | 8 / 889 | 7.3 s |
| 5 mm | old | quiet | 7.99 ms | 1.500e-2 | 37,125 | 9,656 | 5.6% | 417 | 1.026 kg | 32.87 J | 1,498 | 0.098 | 223 / 8,562 | 227 s |
| 20 mm | new | capped | 12.0 ms | 1.231e-3 | **1,000** | 1,302 | 76.4% | 24 | 0.549 kg | 8.18 J | 173 | 1.20 | 845 / 443 | 0.33 s |
| 10 mm | new | capped | 12.0 ms | 1.741e-3 | **1,000** | 11,315 | 60.0% | 155 | 0.939 kg | 9.15 J | 89 | 0.85 | 6,112 / 5,124 | 13.5 s |
| 5 mm | new | capped | 12.0 ms | 2.462e-3 | **1,000** | 36,046 | 20.8% | 1,021 | 0.924 kg | 25.01 J | 305 | 0.60 | 16,338 / 18,912 | 414 s |

| law | step | pieces | largest piece | removed energy | broken bonds |
|---|---|---:|---:|---:|---:|
| old | 20 -> 10 mm | +833% | -1% | +73% | +815% |
| old | 10 -> 5 mm | +1389% | -1% | +35% | +914% |
| new | 20 -> 10 mm | +546% | +71% | +12% | +769% |
| new | 10 -> 5 mm | +559% | -2% | +173% | +219% |

Oak does not converge either. One thing does improve and is worth recording:
under the old law oak fails almost entirely in **shear** (0 tensile against 99
shear at 20 mm; 223 against 8,562 at 5 mm), because oak's declared shear
strength is 11 MPa against a tensile strength of 90 MPa, so the shear ramp bites
first and the "crack" is a shear band. Under the energy-scaled law the mode-I
threshold drops below the shear one and tension becomes the leading mode (845
tensile against 443 shear at 20 mm). The new law puts oak's failure in the mode
a bending impact should produce; it does not make the piece count converge.

Oak's largest piece is the one quantity on the whole ladder that holds still:
1.053 / 1.041 / 1.026 kg under the old law, within 1.5% per level on a 1.0752 kg
tile. That is not a convergence result, though - it is the tile refusing to come
apart. 95-98% of the mass stays in one piece and the "pieces" are surface chips.
Under the new law it does not hold still (0.549 / 0.939 / 0.924 kg), and the
20 mm row is the odd one out because there the tile is the only case on the
ladder that actually breaks in half.

### 6.4 Glass at 12 m/s

*Experimental result.* The same tile and ball, struck at 12 m/s instead of 8.
The pulverisation number scales with the speed, so R rises to 37.9 / 26.8 / 19.0
under the new law and 1.34 under the old.

| cells | law | exit | window | broken | of all bonds | pieces | >=1% | largest | removed | measured Gc | R | first failure | depth | wall |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 mm | old | capped | 12.0 ms | 1,433 | 84.1% | 49 | 12 | 1.080 kg | 36.62 J | 703 | 1.34 | 0.362 ms | 30 mm | 0.29 s |
| 10 mm | old | capped | 12.0 ms | 7,832 | 41.5% | 223 | 4 | 2.718 kg | 61.52 J | 864 | 1.34 | 0.221 ms | 10 mm | 18.8 s |
| 5 mm | old | capped | 12.0 ms | 21,595 | 12.5% | 664 | 1 | 3.514 kg | 62.07 J | 1,265 | 1.34 | 0.183 ms | 5 mm | 442 s |
| 20 mm | new | quiet | 4.83 ms | 1,616 | 94.8% | 120 | 29 | 0.220 kg | 1.28 J | 21.7 | 37.9 | 0.337 ms | 20 mm | 0.07 s |
| 10 mm | new | capped | 12.0 ms | 15,548 | 82.5% | 436 | 4 | 1.193 kg | 5.18 J | 36.6 | 26.8 | 0.213 ms | 9 mm | 7.5 s |
| 5 mm | new | capped | 12.0 ms | 101,074 | 58.4% | 2,069 | 1 | 3.155 kg | 2.25 J | 9.8 | 19.0 | 0.178 ms | 5 mm | 409 s |

| law | step | pieces | largest piece | removed energy | broken bonds |
|---|---|---:|---:|---:|---:|
| old | 20 -> 10 mm | +355% | +152% | +68% | +447% |
| old | 10 -> 5 mm | +198% | +29% | **+1%** | +176% |
| new | 20 -> 10 mm | +263% | +442% | +306% | +862% |
| new | 10 -> 5 mm | +375% | -57% | -57% | +550% |

The one quantity anywhere on either ladder that looks like a limit is the old
law's removed energy at 12 m/s: 36.6 -> 61.5 -> 62.1 J, a 1% change over the
last refinement. It is not evidence for the old law. At 12 m/s the strike
saturates - 84% of the 20 mm tile's bonds break under a law that is 795 times
too tough - and the removed energy converges to "as much as the ball had",
which is a property of the ball and not of the criterion. The piece count on the
same rows still triples per level.

### 6.5 dt against dt/2, and the horizon

*Experimental result.* Oak, 10 mm cells, 8 m/s, `dt_factor 0.5` (0.856 us)
against `0.25` (0.428 us), same exit rule:

| law | substeps | broken | pieces | largest | removed | first failure |
|---|---:|---:|---:|---:|---:|---:|
| old, dt | 6,233 | 952 | 28 | 1.0409 kg | 24.306 J | 0.3502 ms |
| old, dt/2 | 11,565 | 907 | 29 | 1.0416 kg | 21.921 J | 0.3527 ms |
| change | | **-4.7%** | +3.6% | **+0.07%** | **-9.8%** | +0.7% |
| new, dt | 14,017 | 11,315 | 155 | 0.9394 kg | 9.1485 J | 0.3502 ms |
| new, dt/2 | 28,033 | 12,727 | 228 | 0.8666 kg | 9.1987 J | 0.3527 ms |
| change | | +12.5% | +47% | -7.8% | **+0.55%** | +0.7% |

One thing here is a clear win for the new law and it is on the brief's list:
**the removed energy is 18x less sensitive to the timestep** (+0.55% against
-9.8%). That is what an energy-calibrated threshold should buy. Halving the step
changes the old law's energy ledger by a tenth because the removal stretch has
nothing to do with energy, so what a bond happens to be carrying when it crosses
the threshold is set by how far the step overshot it. Under the new law that
overshoot is bounded by the calibration.

Piece count and largest piece go the other way (+47% and -7.8% against +3.6% and
+0.07%), for the same reason as section 6.3: oak under the new law is in a
diffuse-damage regime where the piece count is a count of cells.

**Horizon.** The horizon is a parameter of the derivation, of every unit test and
of the strip probe (2 and 3 throughout). On the tile ladder it is not: at 10 mm
cells the lane refuses horizon 3 with `lattice needs more than 64 bond colours`,
because a full horizon-3 neighbourhood has 122 incident bonds and the lane's edge
colouring caps at 64 colours. The 20 mm tile is only 2 cells thick, which
truncates the neighbourhood enough to fit, so horizon 3 is measured there only.
This is a lane limitation, not a criterion limitation.

### 6.6 Does the cascade ever stop?

Every energy-scaled row above ends `capped`, so the obvious question is whether
the cascade terminates at all. The 20 mm rows are cheap enough to answer it:

| row | 12 ms cap | 60 ms cap |
|---|---|---|
| glass, old | quiet at 4.56 ms, 276 bonds, 4 pieces, 28.252 J | identical |
| glass, new | quiet at 4.57 ms, 1,590 bonds, 103 pieces, 0.6207 J | identical |
| oak, old | quiet at 3.09 ms, 104 bonds, 3 pieces, 14.010 J | identical |
| oak, new | capped at 12 ms, 1,302 bonds, 24 pieces, 8.18309 J | **quiet at 20.5 ms**, 1,389 bonds, 30 pieces, 8.18382 J |

It does terminate; the energy-scaled law simply has a longer tail, because the
debris of an undamped lattice keeps ringing and a threshold far below the
material's strength keeps catching that ringing. Running oak's 20 mm row out to
its own quiet point costs +7% bonds and +25% pieces and moves the removed energy
by 1 part in 10,000. That is the bound quoted for the capped 10 and 5 mm rows;
running those to quiet is not affordable (5 mm at 12 ms already takes 7 minutes
of wall time).

The long tail is a lane property, not a criterion property. The reference route
sets `bond_damping = 0`, and the catalogue's declared damping is a rate of
0.015-0.04 per second, which over a 12 ms window is a factor of 5e-4, i.e.
nothing. Fragments also do not collide with each other during the lattice phase
(`docs/fast-gpu-checkpoint.md` section 8, item 6). So a fragment that has come
free rings for ever at whatever amplitude it separated with, and the criterion
keeps reading that ringing.

### 6.7 What the ladder shows: does the answer converge?

**The criterion converges. On a well-posed fracture problem the answer converges
too. On this tile it does not.** All three are measured, and they are different
claims about different things.

The middle one is section 5.3: the pre-cracked strip, driven at a known energy
release rate, gives a crack advance of 25.0 / 42.5 / 47.5 mm at 10 / 5 / 2.5 mm
cells - +70% then **+12%**. Same criterion, same solver, same lane. So what
follows is not "the law does not converge"; it is that this scene is not a
convergence test.

**What converges (validated).** The energy it costs to open a unit of crack area
is now the material's own `fracture_energy_j_m2` at every cell size and every
horizon, to 1e-12 relative, measured on lattices the production generator built
(tests 3a, 3b, 4). Before, the same tile was made of a material 795 times
tougher than glass at 20 mm cells and 199 times tougher at 5 mm - a different
material at each rung of the ladder. That is the length scale the criterion was
missing, and it is there now. The independent LEFM check (section 2.5) says the
constant is right and not merely self-consistent: the criterion breaks a
cell-sized ligament at 1.32x (horizon 2) or 0.92x (horizon 3) the Griffith
stress, for every material and every cell size.

**What improved but is not a limit.** Removed energy under timestep refinement:
+0.55% for dt against dt/2, where the old law moves -9.8% (section 6.4). That is
the one item on the brief's gate list that the new law measurably fixes.

**What still does not converge (experimental result).** Piece count, largest
piece and removed energy under *cell* refinement, for both laws and both
materials:

| | 20 -> 10 mm | 10 -> 5 mm | | 20 -> 10 mm | 10 -> 5 mm |
|---|---:|---:|---|---:|---:|
| **glass, pieces** | | | **oak, pieces** | | |
| old | +800% | +614% | old | +833% | +1389% |
| new | +302% | +269% | new | +546% | +559% |
| **largest piece** | | | | | |
| old | -8% | +110% | old | -1% | -1% |
| new | +176% | +251% | new | +71% | -2% |
| **removed energy** | | | | | |
| old | -7% | +20% | old | +73% | +35% |
| new | +408% | -51% | new | +12% | +173% |

The new law halves the piece-count divergence rate (roughly 3-6x per level
against 6-15x) and that is all. **The gate the brief sets - removed energy,
largest piece and piece count approaching a limit - is not met.**

**Why, and it is not the criterion's fault.** The pulverisation number
R = (v/c_L)/s_c (section 8.2) is 25 to 13 for glass over the ladder and 1.2 to
0.6 for oak. Where R exceeds 1, the strain the impact puts into the bulk exceeds
the stretch at which a bond leaves, so the wave breaks essentially every bond it
reaches: 93% of the 20 mm glass tile's bonds, 88% at 10 mm, 60% at 5 mm. The
fragment size is then the cell size at every level, the piece count is a count of
cells, and no failure criterion can make that converge. R falls as h^1/2, so
refinement does move towards localisation - glass would need about 31 um cells
(4.6e11 of them) and oak about 14 mm.

Oak sits at R ~ 1 and still does not localise, and that is the honest limit of
this branch: a threshold that snaps rather than softens gives no mechanism for a
damaged bond to shed load onto its neighbours, which is what makes damage
localise into a crack in the first place. Section 8.3 sets out what a softening
ramp would cost and what the energy-consistent condition on it is
(`s_0 s_f = s_c^2`, with the stretch derived here as the geometric mean).

**What the sibling lanes should take from this.** The law is worth adopting for
the energy ledger and its resolution independence, and it is a strictly better
input to any fast fracture algorithm than a threshold that changes the material
with the mesh. It does not by itself make a piece count reproducible, and no
lane should claim it does. The next change that would is softening, not speed.

---

## 7. Physics check (b): glass, oak and iron under the identical strike

### 7.1 Where iron's yield makes a brittle criterion inapplicable

Stated plainly, before any number: **neither failure law is a valid model of
iron, and the energy-scaled one is not more valid than the old one.**

`makeReferenceMaterial(Iron)` declares `yield_strength_pa = 200 MPa` on
E = 211 GPa, so iron yields at a strain of 9.5e-4. Both laws remove a bond well
past that: the strength-derived threshold is 2.37e-3 (2.5x the yield strain) and
the energy-scaled one is 2.94e-3 to 5.87e-3 over the ladder (3.1x to 6.2x). The
lattice has no plasticity, so every one of those strains is carried as recoverable
elastic energy that a real bar would have shed as plastic work. Three separate
things are wrong and none of them is fixed by calibrating Gc:

1. **There is no yield surface.** `MaterialModel::RigidOnly` with a brittle bond
   criterion has one path from elastic to gone. `src/material/Plasticity.cpp`
   exists in the engine but this lane does not use it.
2. **Iron's Gc is not a Griffith energy.** 100,000 J/m^2 is a ductile-tearing
   resistance dominated by plastic work in the process zone. Feeding it to a law
   derived for the elastic energy stored in bonds prices a crack correctly only
   if the crack is elastic-brittle, which this one is not.
3. **LEFM does not apply at this size at all.** Iron's Irwin length
   `E Gc / sigma_t^2` is 338 mm, more than the tile is long (240 mm). A specimen
   smaller than its own process zone is fully plastic, not cracked, and no
   critical-stretch law of any kind is the right model for it.

The law's own bookkeeping says the same thing without being told: for iron the
strength bound is active at every cell size on the ladder (section 2.4), which is
exactly the "the element is far smaller than the process zone" branch of the
crack-band rule. So under the energy-scaled law iron keeps the old law's
thresholds, and its rows below are, by construction, the old law's rows.

### 7.2 The three materials under one strike

*Experimental result.* Identical scene: the 0.24 x 0.04 x 0.16 m bridge tile,
20 mm cells, struck in the middle of its top face by the same 4 cm iron ball
(2.11 kg) at 8 m/s from the same 2 mm gap; fast lattice CPU backend in double,
`dt_factor 0.5`, horizon 2, same exit rule. Only the tile material changes.

| material | tile | law | removal stretch | governed by | crack energy charged | Gc declared | broken | pieces | largest | removed | R |
|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| glass | 3.840 kg | old | 1.286e-3 | strength | 6,364 J/m^2 | 8 | 276 | 4 | 1.920 kg | 28.25 J | 0.90 |
| glass | 3.840 kg | **new** | 4.558e-5 | **energy** | **8 J/m^2** | 8 | 1,590 | 103 | 0.340 kg | 0.62 J | 25.3 |
| oak | 1.075 kg | old | 1.500e-2 | strength | 148,500 J/m^2 | 1,000 | 104 | 3 | 1.053 kg | 14.01 J | 0.098 |
| oak | 1.075 kg | **new** | 1.231e-3 | **energy** | **1,000 J/m^2** | 1,000 | 1,302 | 24 | 0.549 kg | 8.18 J | 1.20 |
| iron | 12.088 kg | old | 2.370e-3 | strength | 65,166 J/m^2 | 100,000 | 0 | 1 | 12.088 kg | 0 J | 0.50 |
| iron | 12.088 kg | **new** | 2.370e-3 | **strength** | 65,166 J/m^2 | 100,000 | 0 | 1 | 12.088 kg | 0 J | 0.50 |

At 10 mm cells iron still breaks nothing under either law, and the two laws give
byte-identical thresholds for it.

Three things to read off this table.

1. **The two brittle materials now carry their declared fracture energy and did
   not before.** Glass was 795 times tougher than glass and oak 149 times
   tougher than oak; both are now exact, at this and at every other cell size.
2. **Iron is unchanged, by design and for the right reason.** Its removal
   stretch is identical under both laws to the last bit, because its Irwin
   length (338 mm) is far above the cell size and the crack-band rule hands the
   decision to the strength. Section 7.1 says why no critical-stretch law is a
   model of iron at all; the point here is that the new law does not pretend
   otherwise, and it does not make iron's rows worse.
3. **Where the strength bound is active, the crack energy is still mesh
   dependent.** Iron's charged crack energy is 65,166 J/m^2 at 20 mm and
   32,583 at 10 mm - proportional to h, exactly as the old law is, because the
   removal stretch is the old law's. The resolution independence this branch
   delivers holds only on the energy-governed branch. That is not a defect of
   the derivation: on the strength-governed branch the element is far smaller
   than the process zone and the energy release rate is not what decides
   failure. But it must not be read as "the new law makes everything
   resolution independent", because it does not.

The lane's other measured material differences are unchanged: oak's substep is
longer than glass's (lower stiffness over density) and iron's tile is 3.1x the
mass of glass's, so iron's rows are cheap and inert under both laws.

---

## 8. Limitations and what to do next

### 8.1 What this branch does not claim

1. **No material realism.** The law reproduces the *declared* `fracture_energy_j_m2`
   of the catalogue preset. Whether 8 J/m^2 is the right number for the glass
   the owner has in mind is a calibration question this branch does not touch,
   and no comparison against laboratory fracture data was made.
2. **Mode I only.** The compressive and shear damage ramps are still the
   strength-derived ones. A cell that fails in crushing or in shear does not
   charge a calibrated energy, so a scene dominated by those modes is no better
   off than before. The catalogue carries one fracture energy per material and
   there is nothing to calibrate mode II and mode III against.
3. **Calibrated on {100} planes.** The threshold makes a crack on a {100}
   lattice plane cost exactly Gc; a crack on a {110} or {111} plane costs a
   different amount because a different number of bonds crosses it. The spread
   is +2.9% and +10.2% at horizon 2 and -1.0% at horizon 3 (section 2.2), so the
   crack energy carries a lattice-orientation bias of up to a tenth at the
   horizon the lane ships with. That bias is computed from the offset sums, not
   measured on a running crack.
4. **No flaw statistics on the reference route.** `compileElasticLatticeReference`
   zeroes `strength_variation`, so every bond in the tile has the identical
   threshold. Real brittle solids localise partly because their surface flaws
   do not. The catalogue route (`--catalog`, glass only) carries the 12%
   variation and was not swept here.
5. **One solver.** Everything is measured on the fast lattice CPU backend in
   double and on `BrittleBondSolver`, which it reproduces bit for bit in the
   same sweep order. Nothing here was run on the CUDA backend, the modal lane
   or the quasi-static lane.

### 8.2 The snap criterion cannot localise where the energy governs

This is the finding that matters most and it is not a bug in the implementation.

Without softening, a bond is fully stiff up to its removal stretch and then
gone. Under a passing impact wave the material sees a strain of order `v / c_L`.
Whenever that exceeds the removal stretch **everywhere the wave reaches**, every
bond it touches breaks in the same few substeps: the damage is diffuse, the
fragment size falls to one cell, and no piece count can converge under
refinement. The dimensionless group is

    R = (v / c_L) / s_c,     R^2 = N_100 rho v^2 h / (2 Gc sum n_x^4)

which reads as the kinetic energy in a cell-deep layer of moving material over
the crack energy of that layer's area. It is computable before any run, and it
**falls** as h^1/2 under refinement, so refining always moves towards
localisation - just not fast enough to save a material whose R starts at 25.

### 8.3 What softening would and would not fix

A linear softening ramp (compliance scaled by `1/(1 - d)`) dissipates
`E h^3 s_0 s_f / (2 m)` per bond over a ramp from initiation s_0 to failure s_f,
so the energy-consistent condition becomes

    s_0 s_f = s_c^2

with s_c exactly the stretch this branch derives: the snap law is the special
case s_0 = s_f = s_c, and s_c is the geometric mean of any admissible ramp. Two
things follow.

- **Softening would not rescue the strength.** Putting s_0 at the material's
  true strength stretch s_sigma requires `s_f = s_c^2 / s_sigma`, which is
  *below* s_0 for both glass and oak at every cell size on the ladder
  (glass at 20 mm: s_f = 1.6e-6 against s_0 = 1.29e-3). That is the snap-back
  regime, where crack-band theory says the element is too large to carry both
  the strength and the energy and the strength must be reduced - which is what
  this law does.
- **Softening would still help localisation**, by shedding load from a damaged
  bond onto its neighbours, if the ramp is placed around s_c rather than at the
  strength (for instance s_0 = s_c / 2, s_f = 2 s_c). That is the recommended
  next step, and it is a solver change: `BondFailure.cpp`, `LatticePhysics.hpp`
  and the CUDA kernel all have to scale the bond compliance by `1/(1 - d)`, and
  the removed-energy ledger has to account for the work the ramp already did.
  It would end the sibling lanes' bit-for-bit reproduction of the current
  criterion, which is why it is not in this branch.

### 8.4 The cell size a material actually needs

Setting R = 1 gives the cell size at which a given strike stops pulverising a
given material:

    h* = 2 Gc sum n_x^4 / (N_100 rho v^2)

*Experimental result, from the constants in section 2.1 at horizon 2.* For the
4 cm iron ball at 8 m/s: glass needs about 31 um cells (the tile would be
4.6e11 cells, which is not a resolution any lane can reach), oak needs about
14 mm, and iron does not break at all. That is the honest bound on what this
engine can be asked for: a converged *piece count* for glass under a 2 kg
strike is out of reach at any cell size the engine can run, and the useful
question for glass is the converged *energy and crack area*, which the new law
does deliver. Glass's Irwin length `l_ch = E Gc / sigma_t^2` is 0.28 mm, so
this is the same bound classical fracture mechanics gives, arrived at from the
lattice side.

---

## 9. Exact commands

```sh
# Build (CPU only; the CUDA backend is absent and throws if asked for)
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 6

# The criterion's own tests
build/agent/Release/banjo_criterion_energy_tests.exe

# The whole suite, minus the five the brief excludes
ctest --test-dir build/agent -C Release -E "banjo_network_skin_tests|banjo_network_runtime_tests|banjo_material_showcase_tests|banjo_network_adaptive_tests|banjo_contact_capacity_tests"

python scripts/check-source-registration.py

# One ladder row by hand (this is what the runner below issues)
build/agent/Release/banjo_fast_lattice_run.exe --layout bridge --ball-radius 0.04     --speed 8 --tile 0.24 0.04 0.16 --cell 0.005 --horizon 2 --material glass     --backend cpu --precision double --dt-factor 0.5     --failure-law energy-scaled     --quiet-ms 2 --no-failure-ms 2 --min-ms 0 --max-ms 12 --settle-s 0     --report docs/evidence/criterion/glass-new-5mm-v8.json

# The ladder, its variations and the recordings, in the order they were run.
# Rows already on disk are reused; --force re-runs them. The 68 reports land in
# docs/evidence/criterion/; recordings sit beside them and are gitignored.
python scripts/criterion-ladder.py --stage ladder-v8 --stage ladder-oak-v8
python scripts/criterion-ladder.py --stage long-window --stage materials     --stage dt-half --stage horizon3
python scripts/criterion-ladder.py --stage strip --stage strip-griffith     --stage strip-materials --stage strip-old-matched     --stage window --stage horizon3-20mm --stage ladder-v12
python scripts/criterion-ladder.py --stage record

# `--stage horizon3` is the one that does not complete: at 10 mm cells the lane
# refuses horizon 3 with "lattice needs more than 64 bond colours". Use
# `--stage horizon3-20mm`, which is the part that runs (section 6.5).

# Any table in this document, from the reports on disk
python scripts/criterion-ladder.py --summarise glass-old-20mm-v8 glass-new-20mm-v8     --cols "name,law,cell_mm,cells,broken,pieces,largest_frac,removed_j,measured_gc,pulverisation"

# Physics check (a): the pre-cracked strip
build/agent/Release/banjo_criterion_strip_probe.exe --strip 0.4 0.1 0.04 --cell 0.005     --precrack 0.1 --energy-ratio 1.6 --window-us 300 --failure-law energy-scaled     --report docs/evidence/criterion/strip-glass-5mm.json

# Register the recordings in the owner's playground store (runtime data only;
# the server picks a new job directory up on the next request, no restart)
python scripts/fast-gpu-install-playback.py     docs/evidence/criterion/rec-glass-old-20mm-v8.playback.json     docs/evidence/criterion/rec-glass-new-20mm-v8.playback.json     --runs C:/Users/henry/dev/banjo/build/playground-runs     --title "..." --name "..." --name "..."
```

---

## 10. Playground

The ladder's runs are registered as jobs in the owner's playground store
(`C:/Users/henry/dev/banjo/build/playground-runs`, server on port 8765).
Nothing in the owner's checkout was modified and its server was not restarted;
the server discovers a new job directory on the next request. A separate test
playground was run on port 8804 against this worktree's own store and stopped
afterwards.

Two jobs, four cases each, the same 8 m/s strike with the two laws side by side.
Both were confirmed in a browser against the owner's server; the server picked
each job up on the next request with no restart.

- **`http://127.0.0.1:8765/?job=8cfdf34a144c43d88120c9460e224b1b`** - 20 mm
  cells, and every case **plays through to rest**:
  1. glass, strain-threshold: the crack costs 6,364 J/m^2, 795x glass's Gc.
     276 bonds, 4 pieces, 28.25 J removed, at rest at 0.41 s (25 frames).
  2. glass, energy-scaled: the crack costs 8 J/m^2, which is glass's Gc.
     1,590 bonds, 103 pieces, 0.62 J removed, at rest at 0.90 s (29 frames).
  3. oak, strain-threshold: 148,500 J/m^2, 149x oak's Gc. 104 bonds, 3 pieces,
     14.01 J, at rest at 1.08 s.
  4. oak, energy-scaled: 1,000 J/m^2, oak's Gc. 1,302 bonds, 24 pieces, 8.18 J,
     at rest at 1.80 s.
  Verified by opening case 1 and case 2 and pressing play: case 1 reaches frame
  25/25 at 0.712 s with three slabs and the ball resting on the ledges, case 2
  reaches 29/29 at 1.205 s with a hundred small pieces scattered and still.
- **`http://127.0.0.1:8765/?job=a95ce830c5e8444cb80d8c5577870d11`** - the same
  four runs at 10 mm cells, one rung finer. **None of these four comes to rest
  inside the 6 s settling limit**, under either law: at 10 mm the handoff gives
  Jolt 28 to 414 interpenetrating fragments and it spends the whole window
  separating them. That is the fast lattice lane's known limitation
  (`docs/fast-gpu-checkpoint.md` section 8, item 6: pieces do not collide during
  the lattice phase), not something this branch changed, and it is why the
  ladder rows in section 6 do not settle at all.

The 5 mm energy-scaled rows are not registered: the rigid world refuses their
handoff outright with `manifold-cache-full body-pair-cache-full
contact-constraints-full`, because the tile arrives as more than a thousand
pieces. That refusal is itself one of the measurements in section 6.2.

A separate test playground was run on port 8804 against this worktree's own
store (`build/playground-runs`, one job `d36706d924ba450a88c187f4355f3978`) to
rehearse the registration before touching the owner's, and stopped afterwards by
process id. The owner's checkout was not modified and its server was not
restarted.
