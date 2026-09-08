# Plastic flow in the explicit lattice

Branch `agent/lattice-plasticity`, worktree
`C:\Users\henry\dev\banjo-agents\plasticity`, base `b778517`. Local only, not on
main. Windows 11 Pro, MSVC 19.44 (Visual Studio 17 2022, x64, Release), CUDA
12.9 (nvcc via the Ninja generator; the Visual Studio generator on this machine
has no CUDA MSBuild integration), NVIDIA GeForce RTX 5090 (sm_120), 24 hardware
threads. September 8, 2026.

**Headline.** The lattice's bond had no yield: an iron plate struck by an iron
ball behaved as a spring and gave the energy back. It now carries a **permanent
extension** derived from the declared yield strength, by the same return mapping
`material/NetworkMaterial.cpp` already used — bit for bit, checked against it.
On the 250 x 200 x 10 mm iron plate at 5 mm cells (two cells through the
thickness) the permanent dent at the strike point grows with the strike:

| strike | 4 m/s | 4.5 m/s | 5 m/s | 5.5 m/s | 6 m/s | 6.264 m/s |
|---|---:|---:|---:|---:|---:|---:|
| **permanent dent** | 0.000 mm | 0.000 mm | **0.004 mm** | **0.027 mm** | **0.067 mm** | punched through |
| plastic work | 0.0022 J | 0.035 J | 0.162 J | 0.653 J | 1.49 J | 2.78 J |
| bonds holding a permanent extension | 4 | 22 | 49 | 133 | 242 | 216 |
| broken bonds (of 40,568) | 0 | 0 | 0 | 8 | 26 | 1,507 |
| pieces | 1 | 1 | 1 | 1 | **1** | 64 |

and the elastic control on the same strikes relaxes back to **-0.003 to
-0.004 mm**, i.e. flat: the plate that flowed did not.

**Nothing changes for anything that declares no yield strength.** The plastic law
is off by default and, even switched on, a material whose `yield_strength_pa` is
zero compiles to `yield_stretch = 0` and every expression reduces to the elastic
one. Measured against the `b778517` binary on seven scenes — glass, oak and iron,
both failure laws, float and double, serial and parallel — **all 73 measurement
keys identical**, and glass is identical again with the law switched on.

Oak is the exception the brief did not expect, and it is a declared property, not
a display name: **the catalogue declares `yield_strength_pa = 45 MPa` for oak**
(`src/material/MaterialCatalog.cpp:129`). With the law off oak is `b778517` bit
for bit; with the law on oak flows. Section 7.

`physical_response_validated` stays false. Nothing here calibrates iron. Iron's
yield is the catalogue's 200 MPa and its failure surface is the catalogue's
250 MPa tensile strength through the untouched strain-threshold law, which
removes a bond at 2.37e-3 of stretch against a yield stretch of 9.48e-4 — a
**ductility ratio of 2.5**, where real structural steel is nearer 150. That
number is the single biggest limit on everything below, and section 3.3 measures
what it does.

---

## 1. The constitutive law, and how it maps to the network lane's

### 1.1 What the network lane does

`material/NetworkMaterial.cpp` `advanceNetworkBond`, lines 106-117:

```cpp
double elastic_extension = total_extension_m - result.history.plastic_extension_m;
if (parameters.yield_force_n > 0.0) {
    const double yield_extension = parameters.yield_force_n / parameters.stiffness_n_m;
    const double magnitude = std::abs(elastic_extension);
    if (magnitude > yield_extension) {
        const double increment = magnitude - yield_extension;
        result.history.plastic_extension_m += std::copysign(increment, elastic_extension);
        result.plastic_increment_j = parameters.yield_force_n * increment;
        result.history.plastic_dissipation_j += result.plastic_increment_j;
        elastic_extension = std::copysign(yield_extension, elastic_extension);
    }
}
```

with `yield_force_n = yield_strength_pa * area_m2` and
`stiffness_n_m = E * area / L`, so the yield extension is
`yield_strength_pa * L / E`.

### 1.2 What the lattice does

`src/fastlattice/LatticePhysics.hpp`, `bondPlasticReturn`, per bond, once per
substep:

```
e   = |x_b - x_a| - rest_length - p            elastic extension
e_y = yield_stretch * rest_length + H * kappa  yield extension
if |e| > e_y:
    d      = (|e| - e_y) / (1 + H)
    p     += sign(e) * d                       permanent, signed
    kappa += d                                 accumulated flow, monotone
    W_p   += (e_y + (e_y + H d)) / 2 * d / c   dissipated, never stored
```

and the XPBD constraint in `bondSolve` becomes
`C = |x_b - x_a| - (rest_length + p)`: the bond pulls towards the rest length it
has **now**, so unloading returns it to the new rest length, not the original
one. `storedBondEnergy` measures `e`, not the total extension, so plastic work
never appears as stored elastic energy — which is also what the removed energy of
a fracture reports.

`yield_stretch` and `H` are compiled once, in
`MaterialCompiler.cpp` `withPlasticFlow`:

```
yield_stretch = yield_strength_pa / young_modulus_pa
H             = hardening_ratio          (declared; 0 for every catalogue preset)
```

For iron: `yield_stretch = 200e6 / 211e9 = 9.4787e-4`.

### 1.3 The three departures, and why

**(a) A yield stretch, not a yield force.** The network lane stores
`yield_force_n` and divides by the bond stiffness. This lattice's bond stiffness
is not `E A / L` — it is the peridynamic family weight `E h / (m |o|^2)`
(`compileElasticLatticeReference`), so a bond's "area" is a fiction and dividing
a stress by that stiffness would give every bond of the family a *different*
yield strain, growing as the square root of the bond length. Storing the quotient
`sigma_y / E` instead gives every bond the same yield strain, which is the
currency the failure surface above it is already stated in
(`damage_end_stretch`), so yield and failure are directly comparable numbers. On
a bond whose stiffness *is* `E A / L` the two forms are identical:
`yield_stretch * L * (E A / L) = sigma_y A`. The test in section 2.1 drives both
implementations down the same path and they agree bit for bit.

**(b) Hardening is carried through.** `NetworkMaterial` declares
`hardening_ratio` and then `validateNetworkMaterial` requires it to be *exactly*
zero, so nothing in that lane has ever exercised it. The lattice implements
linear isotropic hardening — `e_y` grows by `H` per unit accumulated flow, the
return mapping divides the excess by `1 + H`, and the work is the mean flow force
over the increment — and with `H = 0` every line reduces to the network lane's,
including the work, which is then `yield_force * increment` exactly. No catalogue
material declares hardening; `MaterialDefinition::hardening_ratio` defaults to 0
and `--hardening R` overrides it for a run that wants to exercise it.

**(c) Plasticity and fracture coexist.** `validateNetworkMaterial` throws on
`yield_strength_pa > 0 && fracture_enabled` — "network v2 does not combine
plasticity and fracture". The lattice must combine them, because the scene it is
judged on is a plate that dents *and can tear*. The rule chosen is the one that
changes nothing: **the failure surface still reads the bond's TOTAL deformation**,
exactly as it did. Plasticity adds no failure law and moves no threshold. The
consequence is that flow spends part of the same stretch budget the criterion
measures — this lattice's ductile matter ruptures at a total strain — and with
iron's catalogue numbers that budget is only 2.5x the yield stretch. Section 3.3.

### 1.4 Where it runs in the substep

Inside `bondEndSampleAndFailure`, before the peaks and the removal rule, which is
the order `advanceNetworkBond` uses. That is phase 12, the end-of-substep bond
phase, already per-bond and already spread across threads on every backend; a
bond's mapping reads and writes only its own slots, so no scheduling changes.

**Once per substep, not once per constraint iteration.** The flow in a substep
therefore does not depend on how many iterations the solve takes. The price is
that within a substep a bond can carry more than its yield force — the solve sees
the plastic extension the substep started with — and the overshoot is bounded by
how far the load can move in one substep. That is the usual explicit-integration
statement; the elastic extension is at most the yield extension at every substep
*boundary*, which section 2.3 asserts on every bond of a chain. Section 2.3 also
measures what the overshoot costs: 17% more flow than the quasi-static answer at
the lane's own substep in the worst (perfectly plastic, localising) case, falling
to 2.8% per halving of the substep in the ledger scene.

---

## 2. The coupon: known answers

`tests/lattice_plasticity_tests.cpp`, all figures from its own output.

### 2.1 The return mapping IS the network lane's

One bond, iron at a 10 mm cell, driven down a 191-point path that loads past
yield, unloads through zero, pushes past yield in compression and comes back —
119 of the 191 points flow.

| | permanent extension | plastic work |
|---|---:|---:|
| lattice `bondPlasticReturn` | -9.47867e-06 m | 1.45213 J |
| `advanceNetworkBond`'s block, transcribed | max difference **0 m** | max difference **0 J** |
| `advanceNetworkBond` itself, through `directionalNetworkParameters` | max difference **0 m** | max difference 2.8e-17 J |

The transcribed block is the exact claim (same algebra, same rounding). The real
`advanceNetworkBond` forms its yield extension as `(sigma_y A) / (E A / L)` and
so rounds differently by construction; it still lands on the same permanent
extension to the last bit and on the same work to 2.8e-17 J of 1.45 J.

### 2.2 One spring, exactly

Two cells at horizon 1 — one bond between two kinematic grips, so the extension
is prescribed exactly — pulled to `yield + 0.6 * (ductile window)` and released.

| | H = 0 | H = 0.05 |
|---|---:|---:|
| yield force | 20,000 N | 20,000 N |
| flow force at the top (law) | 20,000 N (20,000) | 20,857.1 N (20,857.1) |
| elastic slope, loading (law) | 2.11e9 N/m (2.11e9) | 2.11e9 N/m (2.11e9) |
| elastic slope, unloading | 2.11e9 N/m | 2.11e9 N/m |
| permanent set at zero force (law) | 8.53081 um (8.53081) | 8.12458 um (8.12458) |
| permanent bond extension | 8.53081 um | 8.12458 um |
| plastic work (law) | 0.170616 J (0.170616) | 0.165973 J (0.165973) |
| force back at zero grip displacement | **-18,000 N** | -17,142.9 N |

The path is elastic, then the flow force (flat with `H = 0`, raised by hardening
with `H = 0.05`), then an elastic unload on the *same* slope, crossing zero force
at exactly the permanent set the law prescribes. Driven back to zero grip
displacement the bond **pushes**: it is a spring about its new rest length, which
is the whole point.

The closed form for hardening is checked separately and is path independent: one
step and a thousand land on `(D - e_y) / (1 + H)` to 1.6e-19 m for H = 0, 0.02
and 0.1.

### 2.3 A chain, and what a chain can state

Sixteen cells at horizon 1 = fifteen identical springs in series.

| | H = 0 | H = 0.05 |
|---|---:|---:|
| permanent set at zero force | 6.64905 um | 101.564 um |
| sum of the bonds' permanent extensions | 6.64811 um | 101.562 um |
| quasi-static closed form | 5.6872 um (**+16.9%**) | 101.557 um (**+0.005%**) |
| springs that flowed | **2 of 15** | **15 of 15** |
| worst \|elastic\| / yield extension at the end | 0.047 | 0.690 |
| unloading slope (series stiffness) | 1.40549e8 N/m (1.40667e8) | 1.40549e8 N/m |

Two findings worth naming.

**Perfect plasticity localises.** With `H = 0` the tangent modulus is zero, so
nothing shares the next increment out and the flow collapses into two of the
fifteen springs. The *total* permanent set is still the law's; where it goes is
indeterminate, and that is a property of the constitutive law, not of this
implementation. Hardening removes the indeterminacy and every spring flows.

**The once-a-substep mapping flows a little too far.** The localised chain ends
16.9% above the quasi-static answer, because a bond that overshoots the yield
surface inside a substep is returned to it and that flow is permanent. The
hardened chain, where flow spreads and no bond is far past yield in any one
substep, is within 0.005%. The invariant that holds in both is the one asserted:
**no bond is left outside its yield surface at a substep boundary**, and the
chain unloads to the sum of its bonds' permanent extensions on the series elastic
slope.

---

## 3. The plate: does iron dent, and keep the dent

### 3.1 The measurement, and why it needs a probe

The reference material route compiles **no bond damping**
(`compileElasticLatticeReference` sets `bond_damping = 0`; the self-contact
checkpoint measured the consequence as 0.000000 J of damping dissipation). A
struck plate that does not break therefore rings for the whole lattice phase and
never settles, so no frame is a deflection. Averaging over frames is not enough
either: at 10 mm cells the plate's slowest mode has a period comparable with the
whole 40 ms window.

The permanent set is a property of the **state**, so it is read from the state:
`--relax-steps N` runs the *same solver* on the configuration the lattice phase
ended in with the striker removed, gravity zero, the support planes gone, node
contact off and a strong radial bond damping, until the plate stops moving. What
is left is the shape the material holds with nothing loading it. It is reported,
never recorded as a frame and never fed to the rigid handoff — a measurement of
the state, not part of the simulated history — and the run reports its own
convergence receipts (`relax_kinetic_j`, `relax_elastic_energy_j`,
`relax_broken_bonds`).

Heights are taken against each node's own reference height and referred to the
mean of the plate's two end columns, so a rigid drift of the now-free plate
cancels. **The control is the same probe on the elastic run**: with the law off
every bond returns to its original rest length and the plate must relax flat.

### 3.2 The dent, at 5 mm cells

250 x 200 x 10 mm iron plate, **5 mm cells** (50 x 40 x 2 = 4,000 cells, 40,568
bonds), on two ledges 120 mm up, struck by a 60 mm iron ball, 8 ms of lattice
phase, then 120,000 relaxation substeps at damping 1.0.

| strike | law | broken | pieces | plastic work | bonds flowed | deepest permanent stretch | **permanent dent** | deepest dip | relax KE / U |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| 4 m/s | off | 0 | 1 | 0 | 0 | 0 | -0.0027 mm | 0.016 mm | 3e-5 / 4e-5 J |
| 4 m/s | on | 0 | 1 | 0.0022 J | 4 | 8.3e-05 | -0.0026 mm | 0.016 mm | 3e-5 / 8e-5 J |
| 4.5 m/s | on | 0 | 1 | 0.0347 J | 22 | 3.7e-04 | -0.0017 mm | 0.014 mm | 6e-5 / 2e-3 J |
| 5 m/s | off | 0 | 1 | 0 | 0 | 0 | -0.0039 mm | 0.013 mm | 8e-5 / 9e-5 J |
| 5 m/s | on | 0 | 1 | 0.1617 J | 49 | 9.9e-04 | **0.0041 mm** | 0.021 mm | 8e-5 / 9e-3 J |
| 5.5 m/s | on | 8 | 1 | 0.6534 J | 133 | 1.45e-03 | **0.0270 mm** | 0.031 mm | 2e-4 / 5e-2 J |
| 6 m/s | off | 0 | 1 | 0 | 0 | 0 | -0.0044 mm | 0.011 mm | 1e-4 / 1e-4 J |
| 6 m/s | on | 26 | 1 | 1.4926 J | 242 | 2.20e-03 | **0.0670 mm** | 0.067 mm | 2e-4 / 1.1e-1 J |
| 6.264 m/s | on | 1,507 | 64 | 2.7844 J | 216 | 4.81e-03 | punched through | | |

Read it this way.

- **The dent grows with the strike**, 0.004 -> 0.027 -> 0.067 mm over 5 to 6 m/s,
  while the plastic work grows 0.16 -> 0.65 -> 1.49 J and the bonds carrying a
  permanent extension grow 49 -> 133 -> 242.
- **The elastic control relaxes flat.** Every `off` row lands within 0.004 mm of
  zero — that is the probe's noise floor on this scene — against 0.067 mm for the
  6 m/s plastic run, a factor of 15. The deepest dip anywhere on the plate tells
  the same story: 0.011-0.016 mm for the controls, 0.067 mm for the dent.
- **The plate is still one piece** at every speed up to and including 6 m/s
  (`pieces = 1`), having broken 26 of 40,568 bonds at 6 m/s.
- **The relaxation converged**: residual kinetic energy 1e-4 to 2e-4 J on a plate
  that was struck with 13-16 J, and `relax_broken_bonds = 0` everywhere in this
  table, so the probe changed no material state. The residual *elastic* energy
  rises with the dent (9e-5 J elastic control, 0.11 J at 6 m/s) because a dented
  plate holds residual stress; kinetic over elastic is 0.002 there, so it is a
  standing self-stress and not motion the probe failed to remove.
- **Below 4.5 m/s the plate does not dent measurably**: 4 bonds flow, 0.0022 J,
  and the dent is inside the noise floor. The plate is stiff.

### 3.3 The limit: iron's ductile window here is 2.5x, so it dents and then tears

At 6.264 m/s — the panel default, a 2 m drop — the same plate at 5 mm cells is
**punched through**: 1,507 bonds, 64 pieces. The reason is not the plastic law,
it is the failure surface it lives under.

| | stretch | as a multiple of yield |
|---|---:|---:|
| iron yields (`sigma_y / E` = 200 MPa / 211 GPa) | 9.4787e-4 | 1.0 |
| damage starts (`tensile / E`) | 1.1848e-3 | 1.25 |
| the bond is removed (`2 * tensile / E`) | 2.3697e-3 | **2.5** |

Real structural steel elongates 15-25% before it fails, roughly 150 times its
yield strain. This lattice's iron gets a factor of 2.5, because the catalogue's
`break_strain_multiplier` of 2 applied to a tensile strength is a *brittle*
failure strain. So the plastic zone is thin, the dent is small, and past 6 m/s
the flow spends the rest of the budget and the bonds go.

The energy-scaled failure law does not help and was not touched: for iron at
10 mm cells its removal stretch is 2.9e-3, above the strength stretch, so the
strength bound is active and both laws remove an iron bond at the same 2.37e-3.

**Neither failure law was changed, and neither should be to fix this.** What
would fix it is a declared ductile failure strain for metals — a separate
property, a separate decision, and not this change.

### 3.4 The brief's own plate, at 10 mm cells, cannot answer the question

At **10 mm cells** the 10 mm plate is exactly **one cell thick**, and a
one-cell-thick central-force lattice has every bond in one plane. Bending such a
sheet shortens a bond only at second order in the curvature
(`chord = arc * (1 - k^2 l^2 / 24)`), so **cylindrical bending is a
zero-energy mechanism of this lattice**: the plate has essentially no bending
stiffness and holds whatever bend it is left with, plastic or not.

Measured, on that plate struck at 6.264 m/s:

| | strike-point deflection, loaded | after 40,000 relaxation substeps | residual elastic energy |
|---|---:|---:|---:|
| law off (elastic) | 12.65 mm | **2.94 mm** | 0.011 J |
| law on | 22.80 mm | -6.25 mm | 0.037 J |

The elastic plate keeps 2.94 mm of "permanent" shape with no plasticity anywhere,
and its residual elastic energy of 0.011 J is the size the second-order estimate
gives for a bend of that depth (`strain = -k^2 l^2 / 24` over the plate gives
0.026 J at 9 mm) — the shape is nearly isometric, so it costs almost nothing to
hold. **A dent cannot be separated from an
elastic bend on this discretisation**, and no dent depth is claimed from it.

What that plate *does* show, and it is real: with the law on it breaks 15 bonds
where the elastic plate breaks 0, dissipates **3.21 J** of plastic work over 57
bonds, and the ball is still driving the plate down at 40 ms where the elastic
plate has already thrown it back. That is the recording in section 8, job A.

Refining the cell to 5 mm resolves the thickness with two cells, gives the plate
real bending stiffness, and is the only change between section 3.4 and section
3.2. The physical scene is the brief's.

---

## 4. The energy ledger

Plastic work is reported beside the dissipations the lane already separates, in
`lattice.dissipated_kinetic_energy_j`:

```json
"dissipated_kinetic_energy_j": {
  "audited": true, "node_contact": ..., "striker_contact": ...,
  "bond_damping": ..., "plastic_work": ..., "fracture": ...
}
```

and `lattice.energy` reports the elastic energy the bonds still store
(`latticeStateElasticEnergy`, which measures the elastic extension only, so
plastic work is never in it), the lattice's kinetic energy and the striker's
initial kinetic energy.

### 4.1 A scene where it closes

A free bar — 24 cells at horizon 1, no gravity, no supports, no striker, no bond
damping, no contact — given a uniform stretching velocity of 4.53 J, run for
16 us. The only places that energy can go are the elastic store, the plastic
work, the fracture energy and the motion.

| substep | kinetic | elastic | plastic | fracture | **residual** |
|---|---:|---:|---:|---:|---:|
| **elastic control** (no declared yield), 3.41e-7 s | 1.0625 | 3.4257 | **0** | 0 | 0.0370 J (**0.82%**) |
| 6.83e-7 s (23 substeps) | 1.5801 | 1.5821 | 1.5447 | 0 | -0.1817 J (4.01%) |
| 3.41e-7 s (46) | 1.4430 | 1.6354 | 1.4086 | 0 | 0.0383 J (0.85%) |
| 1.71e-7 s (93) | 1.3990 | 1.6092 | 1.4671 | 0 | 0.0500 J (1.10%) |
| 8.54e-8 s (187) | 1.3901 | 1.5954 | 1.5074 | 0 | 0.0323 J (**0.71%**) |

**The control is the claim.** The same bar with a material that declares no yield
strength — no plastic work at all, none of this change running — leaves a
residual of 0.82%, the same size as the plastic runs'. What is left over is the
solve's own error, not the ledger's. XPBD is implicit-Euler-like and loses energy
on a mode with `omega * dt` near one; that loss belongs to the lane and predates
this work. (It is not small in general: the same free bar run for sixty periods
at the lane's own substep loses **all** of its energy to it.)

The residual **changes sign** between the coarsest and the finest substep,
because two errors of opposite sign meet there: the integrator's dissipation, and
the once-a-substep return mapping flowing a little too far when the substep is
long. Neither exceeds 4% over a 16-fold range of substeps and the plastic work
converges, moving 2.8% on the last halving.

### 4.2 What is not claimed

The plate scenes report an **attribution**, not a closed budget: plastic work,
fracture energy, node contact, striker contact and bond damping are each reported
separately and correctly, but gravity work and the support planes' dissipation
are not measured, and the contact figures are kinetic energy removed summed over
a run rather than a budget (the self-contact checkpoint, section 6, says the same
of its own). The closed ledger above is the closed scene's.

---

## 5. Backend parity

The physics is one `BANJO_HD` element function in
`src/fastlattice/LatticePhysics.hpp`, so all three backends execute the same
code. The per-bond state (`plastic_extension`, `plastic_strain`) is written only
by the bond that owns it, in a phase every backend already spreads over bonds, so
nothing about the scheduling changes.

Measured through a scene that yields (`tests/lattice_plasticity_tests.cpp`, iron,
120 x 40 x 160 mm at 20 mm cells, struck at 20 m/s, 1,500 substeps, 66.5 J of
plastic work over 65 bonds with 9 broken):

| against the serial CPU | positions | velocities | damage | plastic extension | plastic strain | broken | plastic work |
|---|---|---|---|---|---|---|---|
| parallel x2, x4, x8 | **0** | **0** | **0** | **0** | **0** | 9 / 9 | rel. 2.1e-16 |
| CUDA double, 1 block | **0** | **0** | **0** | **0** | **0** | 9 / 9 | rel. 2.1e-16 |
| CUDA double, 4 slabs | **0** | **0** | **0** | **0** | **0** | 9 / 9 | rel. 6.3e-16 |
| CUDA float, 1 block | **0** | **0** | **0** | **0** | **0** | 9 / 9 | **0** |
| CUDA float, 4 slabs | **0** | **0** | **0** | **0** | **0** | 9 / 9 | **0** |

Every element of state is bit identical. The one number that is not is the
**scalar total** of the plastic work, because the parallel backend sums it in
per-thread partials and the CUDA backend with `atomicAdd` — exactly as both
already do for the removed fracture energy, and to the same 1e-12 tolerance the
existing suite uses for it. The addends are identical bond for bond.

`build/cuda/banjo_fast_lattice_tests.exe` also passes unchanged and reproduces
the self-contact checkpoint's numbers exactly (74,178 / 74,178 contacts, 166
bonds, `max |du| = 0`).

---

## 6. Nothing changed, measured against the `b778517` binary

`b778517` was extracted with `git archive` and built into a separate tree; both
binaries were run on the same commands and every measurement key compared.

| scene | common keys | differing |
|---|---:|---:|
| glass crush, 500-cell plate, 20 m/s | 73 | **0** |
| glass panel default, 6.264 m/s, 2 s settle | 73 | **0** |
| glass 192-cell tile, 8 m/s | 73 | **0** |
| oak 192-cell tile, 8 m/s | 73 | **0** |
| iron 192-cell tile, 8 m/s | 73 | **0** |
| glass, **energy-scaled** failure law, 12 m/s | 73 | **0** |
| glass, **float**, serial CPU, flat layout, 12 m/s | 73 | **0** |

Those keys include `first_failure_s` to twelve figures, broken bonds, pieces,
removed energy, every contact accumulator and every peak strain. Both failure
laws are selectable and untouched; `--failure-law energy-scaled` reproduces
itself exactly.

Inside the suite, the same claim is asserted rather than measured by hand:
glass declares no yield strength, so running it with the plastic law **switched
on** must change nothing — 32 broken bonds either way, positions, velocities,
damage, plastic extension and plastic strain all bit identical, plastic work
exactly 0.

---

## 7. Glass, oak and iron under identical conditions

250 x 200 x 10 mm plate, 5 mm cells, 60 mm iron ball at 5 m/s on two ledges,
8 ms of lattice phase, everything else equal; only the tile material changes.

| material | law | broken (of 40,568) | pieces | removed energy | plastic work | bonds flowed | permanent dent |
|---|---|---:|---:|---:|---:|---:|---:|
| glass | off | 7,197 | 396 | 1.4010 J | 0 | 0 | (shattered) |
| glass | **on** | **7,197** | **396** | **1.4010 J** | **0** | **0** | (shattered) |
| oak | off | 563 | 30 | 1.9071 J | 0 | 0 | (broken up) |
| oak | **on** | 834 | 45 | 1.2837 J | **2.3701 J** | 375 | (broken up) |
| iron | off | 0 | 1 | 0 | 0 | 0 | -0.0039 mm |
| iron | **on** | 0 | 1 | 0 | **0.1617 J** | 49 | **+0.0041 mm** |

- **Glass is identical** with the law on and off, every digit. Glass declares no
  yield strength, so `yield_stretch` compiles to zero and not one line of the
  plastic law runs. This is the "yield absent, bit for bit" claim measured on a
  real scene rather than a unit test.
- **Oak changes**, because **the catalogue declares a yield strength for oak**:
  45 MPa against a 12 GPa modulus, a yield stretch of 3.75e-3 under a removal
  stretch of 0.015 — a ductile window of 4, wider than iron's. With the law on
  oak dissipates 2.37 J of plastic work over 375 bonds, breaks more bonds (834
  against 563) and removes less energy by fracture. The brief expected oak to
  declare no yield; it does. This is a declared property driving behaviour, which
  is what AGENTS.md asks for, and it is emphatically **not** a claim that this
  lattice models wood: oak's real behaviour is anisotropic and its "yield" is not
  metal plasticity. With the law off — the default — oak is `b778517` bit for
  bit.
- **Iron is the only one of the three that survives** this strike as one piece,
  and it is the only one whose permanent shape can be read: the elastic run
  relaxes to -0.0039 mm and the plastic run to +0.0041 mm.

---

## 8. The cost

Best of five runs per row on an otherwise idle machine, parallel CPU backend,
double precision, same commands, against the `b778517` binary.

| scene | | substeps | lattice wall | us/substep | M bond-updates/s | realtime | broken | plastic work |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| panel default, 500-cell glass plate, 6.264 m/s, 2 s settle | `b778517` | 39,976 | 1.610 s | 40.27 | 68.96 | 0.860x | 523 | - |
| | law off | 39,976 | 1.593 s | 39.85 | 69.68 | 0.851x | 523 | 0 |
| | law **on** | 39,976 | 1.622 s | **40.57** | 68.46 | 0.865x | 523 | 0 |
| 1 m glass pane, 256 cells, 62.5 mm, 2 s settle | `b778517` | 3,168 | 0.107 s | 33.80 | 40.77 | 0.360x | 0 | - |
| | law off | 3,168 | 0.105 s | 33.28 | 41.41 | 0.354x | 0 | 0 |
| | law **on** | 3,168 | 0.105 s | **33.13** | 41.59 | 0.354x | 0 | 0 |
| 1 m oak pane, **energy-scaled** law, 6 s settle | `b778517` | 2,479 | 0.085 s | 34.10 | - | 0.291x | 0 | - |
| | law off | 2,479 | 0.084 s | 33.86 | - | 0.288x | 0 | 0 |
| | law **on** | 2,479 | 0.084 s | **34.01** | - | 0.290x | 0 | 0 |
| iron plate, 10 mm cells, 6.264 m/s, 2 s settle | `b778517` | 19,374 | 0.787 s | 40.62 | 68.36 | 2.430x | 0 | - |
| | law off | 19,374 | 0.784 s | 40.49 | 68.59 | 2.421x | 0 | 0 |
| | law **on** | 11,102 | 0.475 s | **42.75** | 64.97 | **1.537x** | 15 | 3.21 J |
| iron plate, 5 mm cells, 4,000 cells, 5 m/s, fixed 8 ms window | `b778517` | 19,722 | 5.284 s | 267.94 | 151.41 | - | 0 | - |
| | law off | 19,722 | 5.291 s | 268.27 | 151.22 | - | 0 | 0 |
| | law **on** | 19,722 | 5.684 s | **288.23** | 140.75 | - | 0 | 0.16 J |

**Per substep**, which is the clean overhead number because the trajectory is
identical:

| scene | law off / `b778517` | law **on** / law off |
|---|---:|---:|
| panel default (glass, no declared yield) | 0.990 | **1.018** |
| 1 m glass pane (no declared yield) | 0.985 | **0.996** |
| 1 m oak pane, energy-scaled (yield declared, never reached) | 0.993 | **1.004** |
| iron plate, 10 mm cells (yielding) | 0.997 | **1.056** |
| iron plate, 5 mm cells (yielding) | 1.001 | **1.074** |

So: **nothing measurable where the law does not run** — the four rows without
flow scatter between 0.996 and 1.018, which is this machine's run-to-run noise on
a 33-40 us substep — and **5.6% to 7.4% where it does**. Both are well inside the
owner's 1.1x rule as an overhead. The branch that skips the whole law is one
comparison of a scalar against zero, and the plastic state costs one extra `Real`
load in `bondSolve` whether or not it is used.

Two honest notes on the realtime column.

**The two figures the brief quotes are not what this machine produces.**
`docs/development-status.md` records 0.993x for the Fracture lab default and
0.145x for the 1 m oak pane under the energy-scaled law; running the `b778517`
binary here with those commands I measure **0.860x** and **0.291x**. The
self-contact checkpoint records the same kind of disagreement on the pane (0.41x
measured against 0.18x quoted). I have not chased it; the like-for-like columns
above are all measured in one sitting with one binary pair.

**The iron plate misses the 1.1x rule before this change and misses it by less
after.** Iron breaks nothing, so the lattice phase runs the full 20 ms
`no_failure_ms` deadline and the rigid phase then settles a single body: 2.430x
at `b778517`. With the plastic law on a bond does break, the cascade-quiet exit
fires at 11,102 substeps instead of 19,374, and the ratio falls to **1.537x**.
That is physics changing the length of the phase, not overhead, and the rule is
still missed.

The relaxation probe is quoted separately because it is a measurement, not part
of the simulation: 120,000 substeps of the 4,000-cell plate cost about 35 s of
wall time. `--relax-steps` defaults to 0 and nothing runs.

---

## 9. Watchable

Registered in the owner's store (`C:\Users\henry\dev\banjo\build\playground-runs`,
server already running on port 8765; the playground loads a job directory on
first request, no restart needed). No file in the owner's checkout was modified
other than adding these three run directories. No test playground of my own was
needed on port 8806, because the owner's server picked the jobs up on a plain GET.

- **Iron under the same strike, plastic law off and on** --
  `http://127.0.0.1:8765/?job=9a449f704c1248639fdcc1a4fc897796`
  - case 1: `--plasticity off`, the 500-cell iron plate at 6.264 m/s: 0 bonds
    broken, 0 J of plastic work, the ball thrown back;
  - case 2: `--plasticity on`, the same strike: 15 bonds broken, **3.21 J** of
    plastic work over 57 bonds, the ball still driving the plate down at 40 ms.
  - This is the 10 mm-cell plate of section 3.4, so it is the *behaviour* that is
    watchable, not a dent depth.
- **The dent grows with the strike** --
  `http://127.0.0.1:8765/?job=c9dfd02765b748deab67115812274716`
  - the 4,000-cell plate at 5 mm cells struck at 4, 5, 5.5 and 6 m/s with the law
    on: 0.0022 / 0.162 / 0.653 / 1.493 J of plastic work, permanent dents of
    0.000 / 0.004 / 0.027 / **0.067 mm**, one piece in all four.
- **Glass, oak and iron under identical conditions, law on** --
  `http://127.0.0.1:8765/?job=b59f75a596f04dba9c05c2f1dc9b4c84`
  - glass (declares no yield): 7,197 bonds, 396 pieces, 0 J -- identical to the
    law off; oak (declares 45 MPa): 834 bonds, 45 pieces, 2.37 J over 375 bonds;
    iron (declares 200 MPa): 0 bonds broken, one piece, 0.162 J over 49 bonds.

Verified in a browser: job `9a449f70...` opens on the 3D Playback tab with the
plate on its ledges and the ball above it, the case selector carries both cases,
and **both play through to the last frame** (`Sampled frame 52 / 52`, 0.411 s for
case 1 and 0.394 s for case 2). Job `c9dfd027...` opens the same way with its four
cases.

---

## 10. What does not work, and limits

1. **Iron's ductile window is 2.5x its yield strain** (section 3.3), so the dent
   is small — 0.067 mm on a 10 mm plate — and past 6 m/s the plate tears rather
   than dishing. That is the catalogue's `break_strain_multiplier * tensile / E`
   meeting a metal, not a property of the plastic law. Fixing it needs a declared
   ductile failure strain, which is a separate decision.
2. **A one-cell-thick plate cannot show a dent at all** (section 3.4): cylindrical
   bending is a zero-energy mechanism of a single-layer central-force lattice, so
   the elastic control keeps 2.94 mm of shape. Any dent claim needs at least two
   cells through the thickness.
3. **The unloaded shape needs a relaxation probe** because the reference material
   route compiles no bond damping. The probe is honest about itself (it reports
   its own residual kinetic and elastic energy and whether it broke anything) but
   it is an extra 120,000 substeps, and on a scene where the probe *does* break
   bonds its number should not be trusted.
4. **The return mapping runs once per substep** and flows a little too far when
   the substep is long: 17% above the quasi-static answer in the worst measured
   case (a perfectly plastic chain, where flow localises), 0.005% when hardening
   spreads it, 2.8% per halving in the ledger scene. A mapping inside the
   constraint iteration would fix it and would make the flow depend on the
   iteration count instead.
5. **Perfect plasticity localises** and this implementation does not regularise
   it. With `H = 0` a chain of identical springs puts all its flow in two of
   fifteen. Physically correct, numerically mesh dependent; hardening is the
   available answer and no catalogue material declares any.
6. **The failure surface reads total deformation**, so flow spends the same
   budget the criterion measures. That is a deliberate choice (section 1.3c) and
   it means a ductile material's fracture answer changes when the law is on --
   oak goes from 563 to 834 broken bonds. Nothing here says which is right.
7. **Plasticity is axial only.** A bond carries a permanent *extension*; there is
   no deviatoric flow rule, no pressure dependence, no volumetric/deviatoric
   split, and therefore no plastic incompressibility. It is exactly the network
   lane's model, on a bond family.
8. **No rate dependence, no Bauschinger effect beyond the kinematic one the
   signed permanent extension gives, no temperature, no anisotropy.** Isotropic
   hardening only, and no catalogue material declares any.
9. **The plate ledger is an attribution, not a closed budget** (section 4.2).
10. **`--plasticity` defaults to off.** That is deliberate — it keeps
    `playground/fracture_lab.py` and every recorded result exactly as they were —
    but it does mean iron is still a spring unless the flag is passed. Whether the
    default should flip is the owner's call, and the reason it is not flipped here
    is oak: flipping it changes oak's fracture answer, which the brief asked to
    keep.

---

## 11. Exact commands

Build (no CUDA):

```sh
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 6
ctest --test-dir build/agent -C Release -E "banjo_network_skin_tests|banjo_network_runtime_tests|banjo_material_showcase_tests|banjo_network_adaptive_tests|banjo_contact_capacity_tests"
python scripts/check-source-registration.py
```

**89 tests run and all 89 pass, in 91 s** (94 configured, the five hour-scale
suites excluded by instruction), including the new
`banjo_lattice_plasticity_tests`. No tolerance was changed.

Build with CUDA (Ninja + nvcc from a developer prompt, as the self-contact
checkpoint records):

```bat
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
cmake -S . -B build/cuda -G Ninja -DCMAKE_BUILD_TYPE=Release -DBANJO_BUILD_LAB=OFF -DBANJO_BUILD_CUDA=ON
cmake --build build/cuda --parallel 6
build\cuda\banjo_lattice_plasticity_tests.exe
build\cuda\banjo_fast_lattice_tests.exe
```

Scenes:

```sh
E=build/agent/Release/banjo_fast_lattice_run.exe

# 3.2 the dent, at 5 mm cells (speed 4, 4.5, 5, 5.5, 6, 6.26424; --plasticity off for the control)
$E --material iron --ball-material iron --tile 0.25 0.01 0.2 --cell 0.005 \
   --ball-radius 0.03 --speed 5 --layout bridge --backend parallel --precision double \
   --plasticity on --max-ms 8 --min-ms 8 --no-failure-ms 0 --quiet-ms 0 --settle-s 0.02 \
   --frames 6 --relax-steps 120000 --relax-damping 1.0 --report dent.json

# 3.4 the brief's plate, at 10 mm cells (the diagnosis, not a dent)
$E --material iron --ball-material iron --tile 0.25 0.01 0.2 --cell 0.01 \
   --ball-radius 0.03 --speed 6.26424 --layout bridge --backend parallel --precision double \
   --plasticity on --max-ms 40 --min-ms 40 --no-failure-ms 0 --quiet-ms 0 --settle-s 0.5 \
   --frames 36 --rigid-frames 18 --relax-steps 40000 --relax-damping 1.0 --record iron.json

# 7 glass, oak and iron under identical conditions (--material glass|oak|iron)
$E --material iron --ball-material iron --tile 0.25 0.01 0.2 --cell 0.005 \
   --ball-radius 0.03 --speed 5 --layout bridge --backend parallel --precision double \
   --plasticity on --max-ms 8 --min-ms 8 --no-failure-ms 0 --quiet-ms 0 --settle-s 0.02 \
   --frames 6 --relax-steps 120000 --relax-damping 1.0

# 8 the cost, and 6 the comparison against the b778517 binary
$E --material glass --ball-material iron --tile 0.25 0.01 0.2 --cell 0.01 --ball-radius 0.03 \
   --speed 6.26424 --offset 0 0 --layout bridge --settle-s 2 \
   --backend parallel --precision double --plasticity on
```

New flags, all with the previous behaviour as the default:

| flag | meaning |
|---|---|
| `--plasticity on\|off` | axial plastic flow from the declared yield strength. **Default off**: the elastic-plus-damage lane, bit for bit, whatever the material declares |
| `--hardening R` | linear isotropic hardening, tangent modulus over the Young modulus. Default: what the material declares, which is 0 for every catalogue preset |
| `--relax-steps N` | after the lattice phase, relax the plate with the striker, gravity and the supports removed for N substeps and report the shape it holds unloaded. A measurement, not a recorded frame. Default 0 |
| `--relax-damping F` | radial bond damping of that probe (default 0.5; 1.0 is what section 3.2 uses) |

`playground/fracture_lab.py` passes none of them and is unaffected.

---

## 12. Files

| Path | Change |
|---|---|
| `src/material/Material.hpp` | `MaterialDefinition::hardening_ratio`; `CompiledBrittleMaterial::yield_stretch`, `plastic_hardening_ratio` |
| `src/material/MaterialCompiler.{hpp,cpp}` | `withPlasticFlow`, which is the only place the declared yield strength becomes a lattice number. Neither failure law touched |
| `src/fastlattice/LatticePhysics.hpp` | `bondElasticExtension`, `bondPlasticReturn`, `latticeElasticEnergy`; the plastic rest length in `bondSolve` and `storedBondEnergy`; the plastic arrays and the two settings scalars; `FailureOutcome::plastic_increment_j` / `plastic_stretch` |
| `src/fastlattice/LatticeWorking.hpp` | allocation, conversion and round-trip of the plastic state |
| `src/fastlattice/FastLattice.{hpp,cpp}` | `LatticeState::plastic_extension` / `plastic_strain`, `RunStatus::plastic_work_j` / `max_plastic_stretch`, `latticeStateElasticEnergy`, `latticeStateKineticEnergy` |
| `src/fastlattice/CpuLatticeBackend.cpp` | accumulate the plastic work and the peak permanent stretch |
| `src/fastlattice/ParallelCpuLatticeBackend.cpp` | the same, per thread |
| `src/fastlattice/CudaLatticeBackend.cu` | the same, with the device buffers and the atomic sum |
| `src/fastlattice/TileImpactScene.{hpp,cpp}` | `plasticity`, `hardening_ratio`, `relax_steps`, `relax_damping_fraction`; the unloaded-shape probe; the plasticity, energy and deformation measurements and their JSON |
| `tools/fast_lattice_run.cpp` | the four flags |
| `tests/lattice_plasticity_tests.cpp` | six suites (sections 2, 4, 5, 6) |
| `CMakeLists.txt` | the new test target |
