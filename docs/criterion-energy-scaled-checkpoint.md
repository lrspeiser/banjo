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

### 2.5 What the law is not

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
| 7 | names | `parseBondFailureLaw` round trips and refuses an unknown name |

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

### 5.2 Results

*Filled in below.*

### 5.3 The lane's own energy leak

XPBD damps the modes it cannot resolve; at `dt_factor 0.5` the fastest bond mode
has `omega dt = 1`. The probe measures the resulting leak on this very scene
while the crack is still standing still, so the energy check is stated against
that number rather than on top of it. It is a property of `BrittleBondSolver` and
of the fast lattice lane that reproduces it bit for bit, not of the criterion.

---

## 6. The convergence ladder

*Filled in below.*

---

## 7. Physics check (b): glass, oak and iron under the identical strike

*Filled in below.*

---

## 8. Limitations and what to do next

*Filled in below.*

---

## 9. Exact commands

*Filled in below.*

---

## 10. Playground

*Filled in below.*
