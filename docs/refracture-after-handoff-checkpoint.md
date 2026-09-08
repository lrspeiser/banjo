# Breaking a piece that has already broken

Branch `agent/refracture-after-handoff`, worktree
`C:\Users\henry\dev\banjo-agents\refracture`, base `078ae24`. Local only, not on
main. Windows 11 Pro, MSVC 19.44 (Visual Studio 17 2022, x64, Release; the CUDA
configuration through Ninja + nvcc, CUDA 12.9), NVIDIA GeForce RTX 5090
(sm_120), 24 hardware threads. September 8, 2026.

**Headline.** The rigid handoff was a one-way street: after it, a fragment could
not fracture at any speed (`docs/fast-gpu-checkpoint.md` section 8, limit 6). It
now can. On the panel's 500-cell glass plate, broken by a 60 mm iron ball at
6.264 m/s into **523 broken bonds and 55 pieces**, a second 100 mm iron ball
dropped on the debris at 8 m/s **did nothing at all before** — 0 bonds, 55
pieces — and now **breaks 507 more bonds and turns one 209-cell piece into 77**,
ending at 131 pieces. The damage grows with the second strike:

| second strike | 4 m/s | 6 m/s | 8 m/s | 12 m/s | 16 m/s | 20 m/s |
|---|---:|---:|---:|---:|---:|---:|
| bonds broken, before | 0 | 0 | 0 | 0 | 0 | 0 |
| **bonds broken, now** | **0** | **585** | **507** | **722** | **860** | **948** |
| energy removed (J) | 0 | 5.14 | 28.11 | 29.44 | 43.66 | 54.73 |
| pieces at rest | 55 | 137 | 131 | 169 | 182 | 205 |
| realtime | 0.70x | 0.96x | 0.98x | 0.95x | 0.94x | 0.93x |

4 m/s is not a tuned floor: the trigger's own bound for glass struck by iron is
**4.506 m/s**, the measured closing speed at 4 m/s is 3.97, and nothing is
admitted. The bound is `s_min * c * (z_o + z_f) / (2 z_o)` and comes from the
material — 8.70 m/s for glass on concrete, 13.75 for oak, 35.60 for iron
(section 1).

**Off by default.** `--refracture off` is the default and runs not one line of
this: every panel scenario reproduces the `078ae24` binary on **100 of 100
measurement keys, on all 8 scenes** (section 6). Turning it on costs **4.0%**
on the 500-cell plate and **16.9%** on the 1 m pane when nothing is admitted,
and the 1.1x rule holds through every scene above.

**Backend parity holds.** Serial CPU, parallel CPU and CUDA agree on **124 of
124 measurement keys** through a re-entry, the re-fracture event included down
to the removed energy's last bit (74.74992354716711 J).

`physical_response_validated` stays false. Nothing here calibrates glass; the
criterion, its thresholds, the contact rule and the solver are the ones the lane
already had, and this checkpoint changes none of them.

---

## 1. The trigger, and its derivation

A rigid fragment carries its material and its geometry; a contact hands us a
closing speed and a reduced mass. Two **necessary** conditions follow for "some
bond inside this fragment could reach its removal threshold during this
contact". A contact that fails either cannot break anything and is rejected
without building anything at all.

### 1.1 The stress bound

In the acoustic limit — the first microseconds of a contact, before any boundary
reflects — two bodies meeting at closing speed `v` along the contact normal
reach a common interface velocity, and the interface carries

```
sigma = v * z_o * z_f / (z_o + z_f),      z = rho * c,   c = sqrt(E / rho)
```

with `z` the acoustic impedance of each side (`o` = the other body, `f` = the
fragment). The pulse entering the fragment therefore carries the uniaxial strain

```
eps_0 = sigma / E_f = v * [z_o / (z_o + z_f)] / c_f.
```

A plane wave is a state of uniaxial *strain*, so a bond aligned with the
propagation direction is stretched by `eps_0` and every other orientation by
less: `eps_0` bounds the axial stretch the incident pulse can produce. The pulse
then reflects. At a traction-free surface a compressive pulse returns as a
tensile pulse of the same magnitude, and where the incident and reflected pulses
superpose the magnitude reaches at most `2 eps_0` — the classical spall bound.
No other linear-elastic mechanism inside a free fragment amplifies one pulse
further within one contact, so

```
eps_max <= 2 v [z_o / (z_o + z_f)] / c_f.
```

The lattice removes a bond when its resolved stretch reaches that bond's own
removal threshold (`LatticePhysics.hpp bondEndSampleAndFailure`, reading the
`threshold` array `fracture/BondFailure.cpp` fills). Taking `s_min`, the
**smallest** removal threshold over the fragment's *live* bonds and over the
three modes — so a fragment that has already lost bonds, and one whose seeded
strength variation left a weak bond, are judged on what they actually hold —
gives the admission test

```
v >= v* = s_min * c_f * (z_o + z_f) / (2 z_o).
```

Erring towards admission is the correct direction: the trigger never decides
that a fragment breaks, only whether the fragment is worth asking the lattice
about, and the lattice — the same criterion, at every substep — decides the
rest. That is why the free-surface factor 2 is kept.

### 1.2 The energy bound

Removing a bond costs at least the energy that bond stores at its removal
stretch, `0.5 (s_end L)^2 / compliance`, which is exactly what `storedBondEnergy`
reports when the bond goes. The contact cannot deposit more than the kinetic
energy available in the pair's centre-of-mass frame along the normal,
`0.5 mu v^2` with `mu` the reduced mass (Jolt's
`ImpactEvent::available_normal_energy_j`; ignoring the rotational part of the
effective mass makes it an upper bound). So

```
0.5 mu v^2 >= U_min = min over live bonds of 0.5 (s_end L)^2 / compliance
```

is necessary as well. It is what rejects a chip: a light fragment can arrive at
any speed and still not carry one bond's worth of energy. Both `s_min` and
`U_min` take the *smallest* of the three modes per bond, which makes both bounds
as permissive as the data allows — the safe direction for an admission test. For
tensile removal `U_min` is exact; for a shear or compressive removal the axial
energy at that stretch is an over-estimate of what the bond itself must hold,
and taking the smaller threshold keeps the test on the admitting side.

### 1.3 What it costs, and what it rejects

`FragmentFractureLimits` (`s_min`, `U_min`, `c`, `z`, the live-bond count) is
computed **once per fragment**, when the fragment is created. A contact then
costs four multiplies, two divisions and two compares — no allocation, no
lattice, no state.

On the headline scene (500-cell plate, second strike at 8 m/s, 3 s of rigid
time):

| | count | share |
|---|---:|---:|
| contacts the trigger saw | 88,963 | 100% |
| rejected: fragment has no live bond | 58,060 | 65.3% |
| refused: partner is another fragment (section 4) | 23,908 | 26.9% |
| rejected: below the stress bound | 6,994 | 7.9% |
| rejected: below the energy bound | 0 | 0% |
| **admitted, a lattice built** | **1** | **0.0011%** |

One contact in 89 thousand built anything.

### 1.4 The bound for the three materials

Measured by `banjo_refracture_tests` from the compiled materials themselves
(20 mm cells, horizon 2, strain-threshold law):

| fragment | `s_min` | `c` (m/s) | `v*` against iron | `v*` against concrete |
|---|---:|---:|---:|---:|
| glass | 1.2857e-3 | 5291.5 | **4.506 m/s** | **8.705 m/s** |
| oak | 4.95e-3 | 4140.4 | **10.976 m/s** | **13.748 m/s** |
| iron | 2.3697e-3 | 5177.9 | **12.270 m/s** | **35.598 m/s** |

Glass's threshold is low because its removal stretch is low (45 MPa over
70 GPa, doubled by the catalogue's break multiplier). Iron's is high against
concrete because concrete's impedance is a third of iron's, so only a third of
the interface velocity is transmitted.

---

## 2. The return path

`src/fastlattice/Refracture.{hpp,cpp}` `buildFragmentLattice`. A fragment goes
back into the lattice with everything it learned the first time.

**What is carried.** The cells of that fragment, sorted by their parent index so
the sub-lattice never depends on the order a component search produced; every
parent bond with both ends inside it, **dead ones included**, so a broken bond
stays broken and stays reportable in the parent's numbering; each bond's
`damage`, `failure_mode` and strain peaks; and each bond's **permanent (plastic)
extension and accumulated plastic flow**, which `ActiveBondState` has nowhere to
put and which the scene therefore keeps in the asset's own bond order. The
suite asserts every one of these bit for bit
(`theReturnPathCarriesTheState`).

**The pose becomes the initial state.** Cell positions are
`com + R * offset`, where the offsets were taken from the *deformed* lattice at
the handoff, so a piece that was bent when it was handed over comes back bent.
Velocities are `v + omega x r`. The cell's own spin is set to `omega` and
carried through the window untouched — the lattice applies no nodal torque, so
it is a constant — and that is what makes the round trip conserve angular
momentum and kinetic energy exactly (section 5).

**The reference frame is a rigid placement.** The reference configuration is the
**original rest lattice**, rigidly rotated and translated onto the fragment's
pose: `reference_i = com + R * Q * (rest_i - rest_centroid)`, where `Q` is the
rotation closest to the correlation between the rest shape and the frozen shape
(the quaternion iteration of Muller, Bender, Chentanez and Macklin, MIG 2016).
A rigid motion of the reference frame changes no rest length, no threshold and
no strain — the nonlocal Green-Lagrange measure is frame indifferent — and the
suite checks that the stored elastic energy and every bond's current length are
what they were before. What it buys is conditioning: `LatticePhysics.hpp
bondVector` forms a bond in the float path as an exact rest edge plus a
displacement difference, and without `Q` the displacement field carries the
whole rotation a piece accumulated while it was breaking. Measured on the
headline fragment: **89.8 mm without `Q`, 10.1 mm with it**, on a 250 mm plate
with 10 mm cells. A polar decomposition will not do this job: a plate one cell
thick has every rest position in one plane, the correlation matrix is rank
deficient, and its polar factor is undefined.

**The island.** The re-entering fragment is simulated with the same support
planes the first phase used and, when the contact partner was a striker, with
that striker as the lattice's sphere. Nothing else in the world is in the
lattice. The striker is removed from Jolt for the duration and put back where
the lattice left it.

**Rolling the step back.** Jolt has already resolved a collision by the time it
reports the contact, so acting on the post-step state hands the lattice a ball
that has already bounced. Measured before this was fixed: the second strike's
damage *fell* as its speed rose (max closing speed on a bonded piece 4.21 m/s at
an 8 m/s strike, 3.26 at 16, 2.70 at 20). The admitted step is therefore taken
inside `JoltWorld::runReversibleTrial`, which returns false and restores the
bodies, contacts, constraints, tick and queued impacts; the lattice then replays
that step. With it, the measured closing speeds are 5.95 / 7.94 / 11.91 / 15.87 /
19.84 m/s for second strikes of 6 / 8 / 12 / 16 / 20 m/s.

The trial is entered only when it could matter: a pre-gate compares twice the
fastest body in the world against the lowest `v*` any live-bonded piece holds,
which is the trigger's own bound and can only skip steps in which no admission
was possible. On the headline scene 715 of 720 rigid steps were trial steps (a
ball is in the air for most of it) and exactly 1 was rolled back; on the
1 m pane with nothing admitted, 223 of 247.

**The window.** A window runs in whole rigid steps so the two clocks stay
together: the lattice runs `round(rigid_dt / dt)` substeps (4,125 at 10 mm glass
cells), then the rigid world — with the island removed — takes one step, then a
frame is recorded. It ends after `--refracture-window` steps (default 6) or
after `--refracture-quiet` steps (default 2) in which no bond failed. The clock
residual between the two is the rounding of the substep count: **1.3e-6 s over a
25 ms window**, reported per event.

---

## 3. The budget, and refusals

Caps, all reported and all refusable:

| flag | default | meaning |
|---|---:|---|
| `--refracture-events N` | 8 | re-entries admitted in one run |
| `--refracture-steps N` | 600,000 | total re-entry substeps |
| `--refracture-window N` | 6 | rigid steps one window may occupy |
| `--refracture-quiet N` | 2 | rigid steps with no failure that end a window |
| `--refracture-max-cells N` | 4,000 | largest fragment that may re-enter |

Every refusal is counted under `refracture.refused` and every rejection under
`refracture.rejected`, so a re-entry that does not happen is a number:

- `budget_events`, `budget_steps`, `too_many_cells` — the caps above;
- `unsupported_partner` — the partner is another fragment, which the lattice
  phase cannot express (it has bonds and one striker, not piece-piece
  collision). 23,908 on the headline scene, 1,025 on the landing scene;
- `support_penetration` — the rigid solver had sunk the piece more than half a
  cell into the floor (section 4);
- `no_rollback` — the world holds more bodies than `runReversibleTrial` can
  record (250; the cap is Jolt's 256).

`rejected.max_closing_speed_m_s` and `rejected.max_margin` report the hardest
contact the trigger ever saw on a fragment that still has bonds and how close it
came to the bound, so a run that breaks nothing says *why*. The landing scene's
oak case reports `max_margin 0.774`: it was never close.

The suite asserts a refusal is visible: with `--refracture-events 0` the same
scene admits 3 contacts, refuses 3 for want of budget, breaks 0 bonds and leaves
no event behind.

---

## 4. The two places matter is moved, and why

The rigid representation and the lattice do not agree about where a body's
surface is, and where they disagree the conversion has to choose. Both
disagreements were found the same way: by running the identical strike as a
FIRST lattice phase and comparing.

### 4.1 The piece is lifted out of its supports

On an infinite plane the lattice's support projection is unconditional
(`fast-gpu` section 2.8 keeps the CPU rule there deliberately), so a cell centre
that starts below the floor is teleported back up **through its bonds** — the
mechanism that injected kilojoules before the finite-footprint rule existed. A
finite footprint (a ledge) caps the projection's reach at
`8 |approach| dt + 10 um`, which protects a node at REST but stops protecting it
as soon as the approach speed rises — which is exactly what a second strike
does.

Measured, before this was handled: a settled fragment entered 2.53 mm into the
ground of a 10 mm cell and its window removed **2,922 J** of bond energy from a
15 J scene; an intact iron plate resting on ledges, struck at 20 m/s, removed
**361 kJ** from a 422 J scene, where the same plate struck at 20 m/s in the
first phase breaks no bond at all.

The conversion therefore measures the penetration against **every upward-facing
support plane, footprints respected**, and lifts the island by it before
building the lattice.

### 4.2 The striker is backed off until it just touches

Jolt's collision proxy for a fragment is the convex hull of at most 192 sampled
cell corners (`FragmentBuildSettings::maximum_collision_points`), and that hull
sits INSIDE the true box of cells. So the rigid solver lets a striker reach a
depth the lattice's node-sphere contact would never have allowed, and lets a
piece sink into the floor further than its cells do. Measured on an intact iron
plate: the ball is **1.36 mm** inside when the contact is reported, and the
plate lying flat is **5.5 mm** into the ground.

Handing that overlap to the contact pass is a position correction of millimetres
in one substep. The striker is therefore backed off along the contact normal,
iteratively, until it just touches.

### 4.3 What that costs, and what it is not

Both are **rigid translations**: no momentum, no kinetic energy and no internal
state changes. The lift changes gravitational potential by `m g dz`; the back-off
costs the striker the microseconds it takes to close the gap again. Both are
bounded at half a cell and **refused** beyond
(`refused.support_penetration`, `refused.striker_overlap`), and both are
reported per event as `entry_support_penetration_m` and
`entry_striker_backoff_m`. **No fragment is given a velocity, an impulse or a
spin anywhere in this lane**; these two are the only position changes.

With them, the same intact iron plate struck at 20 m/s removes **177 J** instead
of 17.9 kJ and the window ledger no longer creates energy. It still breaks 232
bonds where the first phase at the same speed and place breaks 11, and 81
against 0 for a mid-span strike: a piece re-entered from Jolt rests where the
rigid solver left it — tilted by a fraction of a cell, bearing on one edge of a
ledge rather than flat along it — and that is a different bending problem from
the one the first phase constructs. The energy scale is right and the outcome is
sensitive to the resting pose; section 10 keeps that as an open limit.

## 5. The conservation ledger

Three ledgers, all reported per event under `refracture.events[].ledger`.

### 5.1 Entry: rigid -> lattice

The lattice built from the rigid pose, against the same cell set read back
through the engine's own `calculateFragmentMassProperties` — a different code
path, which inverts the inertia tensor to recover `omega` from `L`.

| | headline event | suite fixture (oak, spinning pose) |
|---|---:|---:|
| `entry_momentum_residual` | **0** kg m/s | **0** kg m/s |
| `entry_angular_residual` | 6.6e-22 kg m2/s | 1.8e-15 kg m2/s |
| `entry_energy_residual` | -2.1e-25 J | -1.8e-15 J |

The conversion is exact to rounding because the node velocity field *is* the
rigid field and the cell spin is carried: `coarsening_kinetic_loss_j` at entry
is zero.

### 5.2 Exit: lattice -> rigid

The lattice's momentum, angular momentum about the island origin and kinetic
energy against the sum over the pieces it becomes.

| | headline event |
|---|---:|
| `exit_momentum_residual` | 6.4e-16 kg m/s |
| `exit_angular_residual` | 3.7e-17 kg m2/s |
| `exit_coarsening_loss_j` | 0.0696 J (named, not hidden) |
| `exit_energy_residual` after naming it | -5.8e-16 J |

The kinetic energy the pieces cannot carry is exactly the coarsening loss — the
non-rigid part of the motion the rigid representation drops — and the elastic
energy still stored in the bonds (`elastic_out_j`, 0.024 J here) is likewise
reported rather than absorbed.

### 5.3 The window

`window_external_impulse_n_s` is what is left of the momentum balance after
gravity; `window_unaccounted_work_j` is what is left of the energy balance after
gravity, the removed bond energy, the plastic work and the measured striker and
node-contact dissipation.

With **nothing external acting** — a fragment struck in flight, no support
engaged — both must vanish, and they do:

| landing scene, airborne event at 4.60 m/s | |
|---|---:|
| `window_external_impulse_n_s` | **3.4e-11** N s |
| `window_unaccounted_work_j` | **1.4e-6** J |
| `exit_momentum_residual_kg_m_s` | 3.5e-18 kg m/s |
| `exit_energy_residual_j` | **0** J |

and the suite asserts the same thing directly: a 4,000-substep window with no
gravity, no support and a 30 m/s striker breaks 318 bonds and drifts
**5.1e-12 kg m/s** on 26.7 kg m/s of momentum.

With a **support engaged**, the residual is the support's contribution, and it
is large. On the headline event (a piece resting on a ledge, struck at 8 m/s by
a 4.12 kg ball carrying 131.8 J):

| | J |
|---|---:|
| removed bond energy | 28.11 |
| striker contact dissipation | 71.48 |
| node-to-node contact dissipation | 68.25 |
| plastic work | 0.00 |
| `window_unaccounted_work_j` | **-46.37** |
| `window_external_impulse_n_s` | 38.48 N s |

The sign says 46 J entered the island. That is the support planes: their impulse
(the ledges and the ground taking the ball's 33 N s), their velocity response,
and — dominantly — the unconditional position projection on the infinite ground
plane, which is a known energy source in this lane and which this checkpoint is
not allowed to change. It is 35% of the strike energy and it is the largest
single limitation here. The lane has never measured a whole-phase energy ledger
before, so this number is new, not a regression.

---

## 6. The first strike is unchanged

`078ae24` was extracted with `git archive` into a separate tree and built; both
binaries were run on the same commands and **every measurement key** compared
(wall clock, throughput and per-phase timers excluded, since they are not
physics).

| scene | keys | differing | what it is |
|---|---:|---:|---|
| 1 m glass pane, 20 m/s | 100 | **0** | 357 bonds, 42 pieces |
| 1 m oak pane, energy-scaled law | 100 | **0** | 268 bonds, 25 pieces |
| 500-cell glass plate, 6.264 m/s | 100 | **0** | 523 bonds, 55 pieces |
| the same plate at 20 m/s | 100 | **0** | 600 bonds, 73 pieces |
| the same plate struck off centre | 100 | **0** | 202 bonds, 23 pieces |
| iron plate, plastic flow on | 100 | **0** | 2,450 bonds, 113 pieces |
| oak plate on the ground | 100 | **0** | 0 bonds, 1 piece |
| 192-cell tile, 8 m/s | 100 | **0** | 303 bonds, 13 pieces |

Those keys include `first_failure_s` to twelve figures, the removed energy,
every contact accumulator, every peak strain and the plastic block.

Inside the suite the stronger claim is asserted rather than measured by hand:
running a scene with `--refracture on` that *admits nothing* must change
nothing. 11,043 compared values — every measurement a re-entry could touch, plus
the position of every cell in every recorded frame and the ball's — are
identical, with 1,744 contacts tested and none admitted.

---

## 7. The scenes

### 7.1 Hit it twice

500-cell glass plate (250 x 200 x 10 mm, 10 mm cells, 2,777 bonds) on two
ledges, struck by a 60 mm iron ball at 6.264 m/s (a 2 m drop). It breaks into 55
pieces, the largest 230 cells. Once the pieces are at rest a **100 mm iron ball
(4.12 kg)** is placed directly above the highest cell 90 mm off the strike axis
and dropped at 8 m/s. It is placed and dropped exactly as the first ball is: no
fragment is moved, no velocity is authored, no impulse is applied.

| | before (`--refracture off`) | now (`--refracture on`) |
|---|---:|---:|
| first strike: bonds / pieces | 523 / 55 | 523 / 55 |
| second strike: contacts tested | 0 | 88,963 |
| second strike: admitted | 0 | 1 |
| second strike: closing speed | — | 7.94 m/s (bound 4.51) |
| **second strike: bonds broken** | **0** | **507** |
| the struck piece | 209 cells, intact | **77 pieces** |
| pieces at rest | 55 | **131** |
| energy removed by the second strike | 0 J | 28.11 J |
| realtime | 0.66x | 0.98-1.04x |

### 7.2 Hit it again harder

The table in the headline. The bond count is monotone from 8 m/s upward and the
removed energy and the piece count are monotone throughout; the 6 -> 8 m/s step
inverts the bond count (585 -> 507) while the removed energy rises 5.5-fold
(5.14 -> 28.11 J), which is the same non-convergence of the fragment count the
lane already reports (`fast-gpu` section 8 item 4): a harder strike drives more
of the damage into fewer, more energetic removals near the contact instead of a
wider low-energy crack field. The claim this table supports is that damage grows
with the strike, measured on energy and on pieces; it is not a convergence
result.

### 7.3 A fragment that lands on a corner

192-cell tile (240 x 40 x 160 mm, 20 mm cells) on ledges **5.5 m** above the
ground, struck by a 80 mm iron ball at 12 m/s. The fragments fall 5.5 m and land
at **10.39 m/s**. Glass, oak and iron under identical geometry, drop, striker
and law:

| | glass | oak | iron |
|---|---:|---:|---:|
| first strike: bonds / pieces | 1,120 / 74 | 212 / 7 | 0 / 1 |
| landing speed | 10.39 m/s | 10.39 m/s | 10.39 m/s |
| **`v*` on concrete** | **8.70 m/s** | **13.75 m/s** | **35.60 m/s** |
| hardest contact on a bonded piece | 11.72 m/s | 10.65 m/s | 2.09 m/s |
| `max_margin` (1.0 is the line) | **1.35** | **0.77** | **0.06** |
| re-entries admitted | 9 (1 refused, budget) | 0 | 0 |
| bonds broken on landing | **13** | 0 | 0 |
| pieces at end | 80 | 7 | 1 |

The reason is stated by the trigger and not by a preference: glass's removal
stretch is 1.29e-3 where oak's is 4.95e-3, so at the same landing speed glass is
over its bound by 35% and oak is 23% under it. Iron never fractured in the first
strike, so it had no fragment to land.

The per-event detail shows the trigger doing its job in both directions. Of the
eight windows that ran, six broke nothing (a 2-4 cell corner landing at
9.4-11.3 m/s: admitted because a bond *could* reach its threshold, refused by the
lattice because none did) and one, an 8-cell piece landing at 11.43 m/s, broke
13 bonds and came apart into 7. One event has partner `striker` at 4.60 m/s —
0.09 m/s over the bound — and broke nothing.

### 7.4 Glass, oak and iron struck twice under identical conditions

The 192-cell tile on ledges, struck by an 80 mm iron ball at 12 m/s, then struck
again at 20 m/s by an 80 mm iron ball 80 mm off the axis, once the pieces are at
rest. Same geometry, same striker, same law, same strain-threshold thresholds:

| | glass | oak | iron |
|---|---:|---:|---:|
| first strike: bonds / pieces | 1,132 / 78 | 212 / 7 | 0 / 1 |
| `v*` against iron | 4.51 m/s | 10.98 m/s | 12.27 m/s |
| hardest contact on a bonded piece | 17.29 m/s | 21.49 m/s | 20.57 m/s |
| `max_margin` | 3.84 | 1.76 | 1.68 |
| re-entries admitted | 2 | 1 | 1 |
| **second strike: bonds broken** | **219** | **403** | **0** |
| energy removed | 13.71 J | 36.53 J | 0 J |
| pieces at end | 78 -> **104** | 7 -> **32** | 1 -> **1** |
| realtime, off / on | 0.70x / 0.72x | 0.15x / 0.45x | 0.55x / 0.60x |

All three are admitted; only two break. Iron's second strike is admitted at a
margin of 1.68 and the lattice removes no bond — the trigger asks and the
criterion answers, which is the division of labour the whole design rests on.
Oak breaks more on the second strike than on the first because the first strike
at 12 m/s barely reaches its threshold while the second arrives at twice the
speed on a piece that is now free to move.

### 7.5 Cost

| scene | `--refracture` | simulated | wall | realtime | rule |
|---|---|---:|---:|---:|---|
| 500-cell plate, no second strike | off | 2.040 s | 1.888 s | **0.925x** | met |
| 500-cell plate, no second strike | on | 2.040 s | 1.963 s | **0.962x** | met |
| 1 m glass pane, 20 m/s | off | 1.055 s | 0.185 s | **0.176x** | met |
| 1 m glass pane, 20 m/s | on | 1.055 s | 0.217 s | **0.205x** | met |

Turning re-fracture on with nothing admitted costs **4.0%** on the plate
(30,333 trigger evaluations and all 480 rigid steps reversible) and **16.9%** on
the pane (8,334 evaluations, 223 of its 247 rigid steps reversible). The cost is
the reversible trial's state save, not the trigger; the pane pays more because
its rigid phase is short and its 42 bodies make the save relatively dearer.

With a re-entry, one window of 24,750 substeps on a 209-cell fragment costs
**0.685 s of wall time** and 25.0 ms of simulated time. The whole 3 s scene runs
at **0.92-1.04x** over repeats against 0.65-0.68x without it, so a triggered
re-entry adds about 0.3x of the simulated duration and the 1.1x rule holds on
every row of section 7.2 and on every repeat of 7.1. The landing scene, with 8
windows on 2-8 cell fragments, runs at 0.58x.

---

## 8. Backend parity and determinism

The same second-strike scene (192-cell tile, second ball at 14 m/s) on all three
backends of the CUDA build, every measurement key compared with wall clock
excluded:

| | keys | differing |
|---|---:|---:|
| serial CPU vs parallel CPU, float | 124 | **0** |
| serial CPU vs **CUDA**, float | 124 | **0** |
| serial CPU vs parallel CPU, double | 124 | **0** |

The re-fracture event is identical down to its last bit on all three: 1
re-entry, 605 broken bonds, 56 pieces out, 74.74992354716711 J removed, and the
ledger residuals byte for byte. The suite asserts the same thing on a whole
scene, comparing 15,683 values including every cell position in every frame.

**Re-entry order does not depend on thread completion order.** Jolt's impact
collector is filled from its worker threads under a mutex, so the order events
arrive in is a scheduling order. Every decision is therefore taken on a total
order over the contacts themselves — body ids, then the contact point, then the
closing speed, then the normal — and among admitted candidates the one with the
largest margin wins, ties broken by that same order. The fragment's cells are
sorted by parent index before the sub-lattice is built, so the colouring, the
sweep order and the arithmetic do not depend on how a component search happened
to enumerate them.

---

## 9. The suite

`banjo_refracture_tests`, seven suites, 8.2 s (CPU build), all passing on the
Visual Studio build and on the Ninja + CUDA build:

1. **The trigger is its derivation.** `v*` equals
   `s_min c (z_o + z_f) / (2 z_o)` to 1e-12 relative for glass, oak and iron
   against iron and against concrete; just above it admits and just below it
   rejects; the peak-stretch estimate is linear in the closing speed; `s_min` is
   the compiled material's own smallest removal threshold; one bond's energy
   admits and a hair less refuses; a one-cell fragment is refused at a million
   metres a second.
2. **The return path carries the state.** Broken bonds, damage, failure mode,
   permanent extension and accumulated plastic flow come back exactly; rest
   lengths, compliances and thresholds are untouched; every bond's current
   length and the fragment's stored elastic energy are what they were; the
   displacement field is the deformation and not the pose.
3. **The round trip conserves.** Mass, linear momentum, angular momentum (cell
   spin included) and kinetic energy across rigid -> lattice; and out again,
   with the kinetic energy the pieces do not carry equal to the coarsening loss.
4. **A free window conserves momentum.** 318 bonds broken, 5.1e-12 kg m/s of
   drift on 26.7 kg m/s.
5. **Turning it on changes nothing it does not touch.** 11,043 values identical.
6. **Serial and parallel agree bit for bit through a re-entry.** 15,683 values.
7. **A refused re-entry is counted rather than silent.**

`ctest` on the whole repository (the five suites the brief excludes were not
run): **90 of 90 passing, 96.6 s**. `python scripts/check-source-registration.py`
passes.

---

## 10. What does not work, and limits

1. **Fragment-fragment contacts are refused, not simulated.** The lattice phase
   has bonds and one striker; it has no piece-piece collision (the lane's own
   limit 6, second half). 27% of the contacts on the headline scene are refused
   for this reason, and the energy chain through debris is therefore broken: a
   ball that hits a loose cell which then hits a bonded piece transfers nothing
   that can break the piece. It is counted, not hidden.
2. **The support planes' work is not measured, and it is large.** Section 5.3:
   46 J on a 132 J strike, dominated by the unconditional position projection on
   an infinite plane. The window ledger closes to 1.4e-6 J only when no support
   engages. Measuring it needs an accumulator inside the support projection,
   which is the contact rule this brief forbids changing.
3. **The island approximation.** While a fragment is in the lattice the rest of
   the world steps without it, and its own contacts with other pieces during the
   window are not seen. The window is 6 rigid steps at most (25 ms).
4. **A striker found more than half a cell inside a piece is refused**
   (`refused.striker_overlap`). The rollback undoes one rigid step, but in a
   debris field the striker's first contacts are with bondless chips, which the
   trigger rejects and the world steps through; by the time a bonded piece
   reports a contact the striker can be deeper than one step's travel. Measured
   on the panel's plate with a 1 s wait before the second strike: 1 refusal and
   no re-entry, where the same scene struck 0.4 s earlier admits and breaks 507
   bonds. The rigid step (1/240 s) is 33 mm of travel at 8 m/s; catching every
   first contact needs a finer rigid step near a fast striker, which would
   change the existing lane.
5. **One re-entry per rigid step**, chosen by margin. A scene in which two
   fragments are struck hard in the same 4.17 ms takes two steps to answer both.
6. **`runReversibleTrial` caps the world at 256 bodies**, so a scene with more
   than ~250 pieces refuses every re-entry (`refused.no_rollback`). The 1 m
   pane's 190-piece pulverisation is inside it; a 672-piece scene is not.
7. **The trigger's factor 2** is the free-surface superposition bound. It is a
   bound, not a calibration, and it makes the lane ask the lattice about
   contacts at half the speed a single-pulse estimate would. Measured on the
   headline scene the price is 1 extra window; on a scene full of near-threshold
   landings it would be more.
8. **The two entry corrections** (section 4) are position changes. Both are
   bounded by half a cell, refused beyond and reported per event, and neither
   changes momentum or kinetic energy — but they are changes of state at a
   representation boundary and should be read as such. They exist because
   Jolt's fragment proxy is a decimated convex hull; a proxy that matched the
   cell box would remove the need for both.
9. **A re-entered piece is not in the state the first phase would have built.**
   It rests where the rigid solver left it, which is tilted by a fraction of a
   cell and bearing on one edge of a support rather than flat along it. On an
   intact iron plate struck at 20 m/s that is worth 232 broken bonds against the
   first phase's 11 over a ledge edge, and 81 against 0 at mid-span, at a sane
   energy scale (177 J and 36 J removed from a 422 J strike). The outcome of a
   re-entry is therefore sensitive to the resting pose, and no convergence study
   of that sensitivity has been done. A material claim made from a re-entry
   should be read as a comparison between materials under the same treatment,
   not as an absolute.
10. **The fragment count is still not converged** (`fast-gpu` section 8 item 4);
   section 7.2's 6 -> 8 m/s inversion is that same non-convergence.
11. **Nothing is calibrated.** The 4.506 m/s bound for glass on iron follows from
   the catalogue's 45 MPa and 70 GPa through the untouched strain-threshold law;
   it is not a measured glass property.
12. Not done: piece-piece re-entry, an island that carries more than one
    fragment, a re-entry triggered by anything other than a Jolt contact, and
    any change to the criterion, the contact rule or the thresholds.

---

## 11. Exact commands

```sh
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 6
build\agent\Release\banjo_refracture_tests.exe
ctest --test-dir build/agent -C Release -E "banjo_network_skin_tests|banjo_network_runtime_tests|banjo_material_showcase_tests|banjo_network_adaptive_tests|banjo_contact_capacity_tests"
python scripts/check-source-registration.py
```

CUDA, through Ninja from a developer prompt (the Visual Studio generator on this
machine has no CUDA toolset):

```bat
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
cmake -S . -B build/cuda -G Ninja -DCMAKE_BUILD_TYPE=Release -DBANJO_BUILD_LAB=OFF -DBANJO_BUILD_CUDA=ON
cmake --build build/cuda --parallel 6
build\cuda\banjo_refracture_tests.exe
```

Every scene in section 7, and the `078ae24` comparison of section 6:

```sh
python scripts/refracture-scenes.py --group all
# or one group at a time: unchanged | twice | harder | landing | materials | cost
```

The headline scene by hand:

```sh
E=build/agent/Release/banjo_fast_lattice_run.exe

# 7.1, before and after (--refracture off | on)
$E --material glass --ball-material iron --tile 0.25 0.01 0.2 --cell 0.01 \
   --ball-radius 0.03 --speed 6.26424 --layout bridge --settle-s 1.5 \
   --backend parallel --precision double --cpu-threads 8 \
   --refracture on --second-ball 0.05 --second-material iron --second-speed 8 \
   --second-offset 0.09 0 --second-at rest --second-wait 0.6 \
   --record twice.playback.json --report twice.json

# 7.3, glass | oak | iron under identical conditions
$E --material glass --ball-material iron --tile 0.24 0.04 0.16 --cell 0.02 \
   --ball-radius 0.04 --speed 12 --layout bridge --ledge-height 5.5 --settle-s 2.5 \
   --backend parallel --precision double --cpu-threads 8 --refracture on \
   --report landing-glass.json

# 7.4, glass | oak | iron struck twice under identical conditions
$E --material glass --ball-material iron --tile 0.24 0.04 0.16 --cell 0.02    --ball-radius 0.04 --speed 12 --layout bridge --settle-s 1.0    --backend parallel --precision double --cpu-threads 8 --refracture on    --second-ball 0.04 --second-material iron --second-speed 20    --second-offset 0.08 0 --second-at rest --second-wait 0.35 --report materials-glass.json

# 8, backend parity (--backend cpu | parallel | gpu)
build/cuda/banjo_fast_lattice_run.exe --material glass --ball-material iron \
   --tile 0.24 0.04 0.16 --cell 0.02 --ball-radius 0.04 --speed 8 --layout bridge \
   --settle-s 0.5 --backend gpu --precision float --refracture on \
   --second-ball 0.04 --second-speed 14 --second-offset 0.08 0 \
   --second-at rest --second-wait 0.35 --rigid-frames 12 --report parity-gpu.json

# register recordings in the owner's store
python scripts/import-playback.py --runs C:/Users/henry/dev/banjo/build/playground-runs \
   --title "..." --name "..." --name "..." a.playback.json b.playback.json
```

New flags, all with the previous behaviour as the default:

| flag | meaning |
|---|---|
| `--refracture on\|off` | let a struck fragment re-enter the lattice. **Default off**: the lane before this existed, bit for bit |
| `--refracture-events N` | re-entries allowed in one run (default 8) |
| `--refracture-steps N` | total re-entry substeps allowed (default 600,000) |
| `--refracture-window N` | longest window, in rigid steps (default 6) |
| `--refracture-quiet N` | rigid steps with no failure that end a window (default 2; 0 runs the whole window) |
| `--refracture-max-cells N` | refuse a fragment larger than this (default 4,000) |
| `--refracture-trace` | print every contact above 5 m/s to stderr. Observation only |
| `--second-ball R --second-speed V` | a second striker of radius R dropped on the debris at V |
| `--second-material NAME --second-offset X Z --second-gap G` | its material, axis and clearance |
| `--second-at rest\|SECONDS` | when it appears (default: when the pieces are at rest) |
| `--second-wait S` | give up waiting for rest after S seconds (default 1) |
| `--cpu-threads N` | parallel backend worker threads (0: calibrate to the machine's load). The backend is bit identical at every thread count, so this fixes only the speed |

`playground/fracture_lab.py` gains those fields, all defaulting to off/zero, and
emits no new flag unless asked: the default command line is byte for byte the one this
lane has always run. Five fields were added — `refracture`, `second_speed_m_s`, `second_ball_m`,
`second_offset_m` and `second_wait_s` — and three scenarios (`glass-twice`,
`glass-twice-before`, `glass-twice-harder`), which reproduce section 7.1's
numbers exactly (523 / 55, then 0 against 507, and 948 at 20 m/s).

---

## 12. Watchable

Registered in the owner's store (`C:\Users\henry\dev\banjo\build\playground-runs`,
server already on port 8765; the playground loads a job directory on first
request, no restart needed). No file in the owner's checkout was modified other
than adding these run directories.

- **Hit it twice, before and after** —
  `http://127.0.0.1:8765/?job=5e7e65bc411946e088d4670bf26331ef`
  - case 1: `--refracture off`, the second ball at 8 m/s bounces off the debris:
    523 bonds, 55 pieces, unchanged from the first strike;
  - case 2: `--refracture on`, the same strike: 507 more bonds, the 209-cell
    piece becomes 77, 131 pieces at the end.
- **Hit it again harder** —
  `http://127.0.0.1:8765/?job=4eb312c7fdf0461ab5f3395090824430`
  - case 1: the second strike at 8 m/s (507 bonds, 28.1 J removed);
  - case 2: the same at 20 m/s (948 bonds, 54.7 J, 151 pieces out of one).
- **A fragment landing on a corner: glass, oak and iron** —
  `http://127.0.0.1:8765/?job=0e670799282f4e4b8b85c49494a8e8f5`
  - case 1: glass, 8 windows on landing, 13 bonds broken;
  - case 2: oak, the same drop, margin 0.77, nothing admitted;
  - case 3: iron, which does not break in the first strike either.
- **Struck twice: glass, oak and iron under identical conditions** —
  `http://127.0.0.1:8765/?job=00349d930e354e1a9ee759fd1b14f136`
  - case 1: glass, 1,132 bonds then 219 more, 78 -> 104 pieces;
  - case 2: oak, 212 then 403, 7 -> 32 pieces;
  - case 3: iron, admitted at margin 1.68 and still 0 bonds, 1 piece.

Verified in a browser: job `5e7e65bc...` opens on the 3D Playback tab, the case
selector switches between the before and after recordings, and the frame
scrubber steps through 91 frames of the second case (frame 56/91 at t = 1.58 s,
frame 73/91 at t = 2.29 s) with the cells and the ball drawn.

---

## 13. Files

| Path | Change |
|---|---|
| `src/fastlattice/Refracture.{hpp,cpp}` | **New.** The trigger and its derivation, the per-fragment limits, the sub-lattice builder with the closest-rotation reference frame, and the mechanical ledgers |
| `src/fastlattice/TileImpactScene.hpp` | `refracture` and its budget, the second striker, `RefractureReport` / `RefractureEventReport`, `pieces_at_end`, `broken_bonds_total` |
| `src/fastlattice/TileImpactScene.cpp` | The rigid phase as pieces rather than a fixed fragment list; the deterministic contact order; the pre-gate, the reversible step and the window; the entry lift; the second striker; the ledgers and their JSON |
| `tools/fast_lattice_run.cpp` | The twelve flags of section 11 |
| `tests/refracture_tests.cpp` | **New.** Seven suites (section 9) |
| `scripts/refracture-scenes.py` | **New.** Every scene and the `078ae24` comparison; evidence under `docs/evidence/refracture/` |
| `playground/fracture_lab.py` | The four pass-through fields and three scenarios; the default command line unchanged |
| `CMakeLists.txt` | `Refracture.cpp` in `banjo_fastlattice`, `banjo_refracture_tests` |
| `.gitignore` | The lane's recordings (8-14 MiB each), as the fast-gpu and criterion lanes do |
