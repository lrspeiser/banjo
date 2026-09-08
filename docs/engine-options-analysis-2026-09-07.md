# Engine options analysis: what has been tried, what is a dead end, and how to reach a solution

Written 2026-09-07 evening, after three parallel fracture lanes ran one round
each on the RTX 5090 / Ultra 9 machine. Every number below is measured on this
engine unless it is marked *estimate*. Sources: `docs/fast-modal-checkpoint.md`,
`docs/fast-quasistatic-checkpoint.md`, `docs/fast-gpu-checkpoint.md`,
`docs/realtime-envelope-checkpoint.md`, `docs/convergence-study-checkpoint.md`,
`docs/implicit-fracture-checkpoint.md`, `docs/blunt-control-substep-checkpoint.md`.

## 0. The requirement, as numbers

The engine must show material interactions in 3D at no more than 1.1x the
simulated duration of the whole interaction, through to rest, on uniform
bonded cells whose behaviour comes from declared physics, and it must give
the *right* answer when the owner changes the request (thickness, speed,
material, strike point). Glass shattering is one case; cutting, pressing,
bending, tearing soft tissue and ductile iron are in the same brief and in the
existing test suites.

For an impact on glass, the physics sets the scale of the problem:

| quantity | value | source |
|---|---:|---|
| longitudinal wave speed in glass | 5,292 m/s | material constants |
| stable substep at 20 / 10 / 5 mm cells | 1.59 / 0.67 / 0.33 us | fast-gpu checkpoint, section 6.2 |
| substeps per millisecond of cascade at 20 / 10 / 5 mm | 630 / 1,500 / 3,000 | from the line above |
| bonds per cell (horizon 2) | 9-14 | 1,704 / 192 ... 173,196 / 12,288 |
| crack crossing a 240 mm plate | about 140 us (0.84% of a 60 fps frame) | modal analysis, 2026-09-07 |
| the cascade on a 193-cell plate | 61 distinct break times, 127 bonds, in ~2 ms | modal analysis |
| what the owner's rule allows for a 2 ms window inside a 2 s interaction | 2.2 s of wall | the rule as written |

So the fracture event itself is sub-frame. The rule does not ask for the
window to be computed in its own 2 ms; it asks for the whole interaction to be
computed in 1.1x its length. That is achievable in principle, and it is why two
of the three lanes met the rule on small scenes: the settling is cheap and the
window is short.

## 1. Two walls, not one

Everything measured in two days comes down to two independent obstacles. The
second is the one nobody was working on.

### Wall 1: cost. Fracture reads a strain field that only exists by resolving the wave.

Every lane that gets the dynamic answer right pays `cells x bonds-per-cell x
substeps`, and substeps scale as `cascade duration x wave speed / cell size`.
Measured per lane:

| lane | throughput | where 1.1x holds (glass, through rest) | where it fails |
|---|---:|---|---|
| network (Jolt bodies + distance springs, what the playground runs) | 0.85 M bond-solves/s, one thread | rigid bodies only | any fracture: 3,000-10,000x over |
| implicit Newton/GMRES (`ConservativeStep`) | serial | <= 365 nodes with no fracture (1.00-1.03x); with fracture at coarse steps, 0.12x at 128 cells, 0.51x at 288 | converged-fracture regime: 8,384x |
| modal basis (exact eigenbasis, rank-one updates) | n k^2 per broken bond | 8x8x2 (128 cells): 0.14x, only because a 2 ms window that is itself 497x slower than realtime sits inside 8 s of settling | 12x12x2: 1.94x; 16x16x2: the window alone is 120 s |
| quasi-static (static solves, no wave) | PCG, ~N^2.3 | <= 2,048 cells: 0.37x | 3,200 cells: 1.56x, and the answer is wrong (see Wall 2) |
| fast lattice on GPU (colour-parallel Gauss-Seidel) | 55 M bond-updates/s at 192 cells, 616 M at 173k bonds | 192 cells: 0.20x (8 m/s) / 0.57x (12 m/s); 384 cells: 0.71x; oak and iron at 1,536 cells | 800 cells: 1.50x; 1,536 cells of glass: 7x; substep floor 25-110 us from 22-32 barrier stages per sweep |

The GPU lane is the only one where the window itself is computed at its
resolved step and the rule still holds. Its ceiling is not the GPU; it is the
schedule (section 3E).

### Wall 2: convergence. The fracture answer changes with things that are not physics.

The same strike, same criterion, same material:

| what changed | result changed | source |
|---|---|---|
| cell size 20 mm -> 10 mm | 3 pieces -> 672 pieces | fast-gpu section 8 |
| Gauss-Seidel sweep order (index vs schedule) | 768 vs 988 bonds broken; same first 28 | fast-gpu section 6.6 |
| float vs double | cascade diverges after ~1.5 ms; 988 vs 1,060 bonds | fast-gpu section 6.6 |
| substep count 5 -> 901 -> 2,271 -> 4,699 (blunt tool on soft tissue) | peak strain 0.317 -> 0.394 -> 0.530 -> 0.537, intact -> damaged | blunt-control checkpoint |
| lane (modal vs implicit, same scene, same first failure) | counts agree, pieces do not | fast-modal section 3.3 |
| network lane time step and resolution | fragment counts swing +-9%; removed energy converges to 0.07%; largest piece converges | convergence study |
| dynamic vs quasi-static | 400-912 bonds and 2-30 pieces vs 156 bonds and 1 piece; disjoint first-failure sets | fast-quasistatic section 3 |

Removed energy, first-failure set and largest-piece mass converge. Piece
count and piece shape do not, in any lane. Two causes are identified and both
are in the model, not in any solver:

1. **The failure criterion has no length scale.** A bond fails at a strain
   threshold (`tensile_strength / E` times calibration multipliers,
   `MaterialCompiler.cpp:70-89`). The material's `fracture_energy_j_m2` is
   carried but does not set the threshold. The energy dissipated to open a
   unit of crack area is therefore proportional to the cell size: halve the
   cells and cracks cost half as much, so the 10 mm lattice pulverises where
   the 20 mm lattice makes three pieces. This is the classic mesh dependence of
   local strain-softening damage (Bazant's crack-band argument; Silling and
   Askari's critical stretch `s0 = sqrt(5 Gc / (9 k delta))` for bond lattices)
   and it is fixed by making the bond threshold a function of `Gc`, the
   horizon and the cell size, so that a crack of a given area releases the same
   energy at every resolution.
2. **The reference physics is defined by a solver, not by a model.** The CPU
   lattice (`BrittleBondSolver`) and the network lane are sequential-impulse
   (Gauss-Seidel) solvers; their answer depends on the sweep order, and
   fracture amplifies that dependence into different piece sets. The GPU lane
   was required to reproduce that solver bit for bit, which is why it inherited
   a 22-32-stage barrier chain (Wall 1) *and* the order dependence (Wall 2).
   An explicit, order-independent integrator (velocity-Verlet / Jacobi force
   accumulation, which is what peridynamics codes use) has one barrier per
   substep and no ordering in its answer.

A horizon of 2 cells (`neighbor_horizon_cells{2}`) is also below what
peridynamic convergence studies use (m = 3-4); with an energy-scaled threshold
that becomes a tunable of the convergence study rather than a guess.

**Consequence.** A faster non-convergent engine is not a solution. The owner's
sentence "I'm going to modify my requests and expect it to be correct" cannot
be met by any lane whose answer depends on the cell size the Builder happened
to choose. Wall 2 has to come down first, and it is cheaper than Wall 1: it is
a change to one criterion and one integrator on a lane that already exists.

## 2. The options, one by one

### A. Network lane (Jolt rigid bodies + distance springs), `NetworkWorld`

What it is: every cell a Jolt body, every bond a distance constraint, damage
reconstructed from the constraint's applied impulse (`-impulse/dt`). Single
thread, zero Jolt workers by design.

Verdict: **dead end as a material solver.** 0.85 M bond-solves/s; 3,000-10,000x
off realtime for any fracture; its reconstruction is a measurement of the
solver's residual as much as of the material (the at-rest tearing of
2026-09-06 and the stability clock that fixed it are symptoms); its blunt
control fails under resolution. Keep it for what it is good at: rigid bodies,
contact, resting, and the playground's authoring and admission layer. Do not
spend another hour making it faster.

### B. Implicit Newton/GMRES lane, `ConservativeStep` + `FractureStep`

What it is: transactional implicit elastic solver with fracture at interval
starts; the most careful ledger in the repository.

Verdict: **dead end for realtime fracture** (accuracy-bound to the wave:
8,384x in the converged regime), **keep as the reference.** It is the yardstick
every other lane was measured against, and the only lane whose refinement
spread is documented. It becomes more valuable, not less, once Wall 2 is
addressed, because convergence claims need a converged reference.

### C. Modal basis (precomputed eigenbasis + rank-one updates), `src/modal`

What it is: the owner's "knowledge embedded in the object" idea in its exact
form. The basis is computed once at creation and reproduces the intact body's
strain field exactly (the stepped solver converges toward it: 1.49% -> 0.64%
-> 0.17%). First failure is identical to the reference on every scene tested.

Verdict: **dead end for the cascade; keep as the predictor.** Each broken bond
costs an O(n k^2) eigen-update (0.9 ms at 216 dofs, 9 ms at 600, 66 ms at
1,176); truncating the basis to make that cheap loses the cascade (keeping 75%
of modes: 106 bonds and 1 piece instead of 922 and 35), because the strain
field the criterion reads after each removal lives in exactly the high modes
truncation removes. A crack is local and high-frequency; a global basis is
the wrong representation for it. What the basis *is* right for: instant
pre-fracture response, an exact and instant answer to "will this strike break
it, and where does the first crack start", and the elastic response of intact
pieces after fracture (Craig-Bampton substructuring). That is the role it
should have in the final engine (section 4, phase 3).

### D. Quasi-static crack propagation, `banjo_quasistatic_probe`

What it is: no wave; static solves, shared criterion, propagation rounds,
pieces to Jolt. Fast (0.37x through rest at 2,048 cells).

Verdict: **dead end for impact fracture; the right tool for slow loading.** It
craters where dynamics shatters, because in the static picture the load
reaches the rim and bending fails first, while in the dynamic picture the
inter-layer diagonals around the contact fail within 40-60 us before the wave
has gone 200 mm; the striker is 0.2-0.8 of the tile's mass, far from the
quasi-static regime. Its own author's list of what it is good for is exactly
the rest of the owner's brief: a knife entering a tomato, a tool pressing on
wood, a tissue tearing, a plate loaded slowly, iron that does not fracture.
Those are quasi-static processes in reality too. Keep it, aim it there, and
never present its glass answer as the shatter.

### E. GPU lattice, colour-parallel Gauss-Seidel, `src/fastlattice`

What it is: the CPU lattice's physics and the shared criterion executed bit
for bit on the GPU, CUDA backend behind an option, equality proven.

Verdict: **the substrate is right; the schedule and the criterion are the dead
ends.** Three measured facts decide it. (i) The sweep is a chain of 22-32
node-disjoint colour stages, each a barrier, so a substep costs 25-35 us on one
block and ~110 us with slabs regardless of bond count below 20k; the GPU is
level with one CPU core at 192 cells and only reaches 616 M bond-updates/s at
173k bonds. (ii) Its answer depends on sweep order and precision (Wall 2). (iii)
At 10 mm cells it pulverises (Wall 2, cause 1). None of these is a property of
"lattice on GPU"; all three are properties of reproducing a sequential-impulse
solver. The fix is to stop reproducing it: an explicit Verlet/Jacobi lattice
is one kernel per substep (force gather + integrate), embarrassingly parallel,
order-independent, and the standard form of every GPU peridynamics code. Its
cost is bandwidth: *estimate* 60-100 bytes per bond-update, so a 5090
(1.8 TB/s) tops out near 2-3e10 bond-updates/s, 30-50x the measured 616 M.
The contact pass (currently serial, a third of the substep at 12,288 cells)
becomes a per-node signed-distance test against the tool. The infrastructure
built this week (scene, recording, equality tests, handoff, playground import)
carries over unchanged.

### F. Not tried, and whether they should be

- **Phase-field fracture** (Bourdin-Francfort-Marigo; Miehe; Ambati). The one
  approach with a proof of convergence to Griffith fracture, and the natural
  fix for Wall 2. Its cost is that the regularisation length `l` must be
  resolved by the mesh (h < l/2), and for glass `l` is millimetres: a 240 mm
  plate needs ~10^5-10^6 cells before it is right. *Estimate*: 100-1,000x the
  cell count of the lattice for the same scene. Worth having as a **validation
  reference on small scenes**, not as the realtime engine. The energy-scaled
  bond threshold (section 1) is the cheap cousin that gets the same
  mesh-independence for crack energy.
- **Material point method with damage** (CD-MPM, Wolper et al. 2019; AnisoMPM
  2020; GPU MPM at 10^6 particles in milliseconds per step, Gao 2018, Wang
  2020). GPU-native, fragmentation and contact come free, handles soft tissue,
  cutting and large deformation that a bond lattice cannot. Same CFL cost as
  the lattice (dt ~ h/c). Verdict: **the strongest candidate if the engine
  must be one substrate for glass, tissue, wood and cutting**; a larger
  rewrite than fixing the lattice, and its fracture criterion has the same
  length-scale requirement. Evaluate on the tomato-cut and tissue suites once
  the lattice is convergent, not before.
- **FEM / XFEM / cohesive zones.** Accurate, mesh-following cracks or heavy
  enrichment; not realtime at these sizes; the implicit lane already covers
  the "careful reference" role.
- **Precut Voronoi shards, authored patterns, explosion impulses.** Forbidden
  by AGENTS.md and by the owner: they are not physics and cannot track a
  changed request. Dead end by rule.
- **A new language ("write our own, like Rust").** The bottleneck is not the
  language. The GPU lane's kernel is CUDA C++; the gap between 616 M and the
  bandwidth bound is the algorithm's barrier chain, and the wrong-answer
  problem is the criterion. No language change touches either.
- **Multi-GPU, cluster barriers, warp-level colour stages** (fast-gpu next
  steps 1-2). These make the Gauss-Seidel sweep cheaper by constant factors
  while keeping its order dependence. Skip them; the Jacobi form removes the
  chain entirely.

## 3. What a solution can and cannot be

The window will never be computed inside its own duration for large glass:
that is Wall 1 at the bandwidth bound. *Estimate*, explicit Jacobi lattice at
2e10 bond-updates/s:

| scene | cells | bonds | window | substeps | bond-updates | wall for the window | inside a 2 s interaction |
|---|---:|---:|---:|---:|---:|---:|---|
| 240 x 160 x 40 mm tile, 20 mm | 192 | 1,700 | 2 ms | 1,260 | 2e6 | 0.1 ms + launch overhead | met |
| same tile, 10 mm | 1,536 | 19,000 | 2 ms | 3,000 | 6e7 | 3 ms | met |
| 240 x 360 x 6 mm pane, 3 mm cells | 19,200 | 250,000 | 2 ms | 5,000 | 1.2e9 | 60 ms | met |
| 1 m x 1 m x 6 mm pane, 3 mm cells | 220,000 | 3,000,000 | 3 ms | 7,500 | 2.3e10 | 1.1 s | met (0.6x) |
| 1 m x 1 m x 6 mm pane, 2 mm cells | 750,000 | 1e7 | 3 ms | 11,000 | 1.2e11 | 6 s | not met without localisation |

The last row is where localisation (phase 3) is required: cracks occupy a
small fraction of a pane, and cells farther than a few horizons from any
damaged bond and outside the wave front do not need the lattice at all. The
first four rows say that a correct, order-independent GPU lattice meets the
owner's rule for every tile the Builder can currently express and for
window-sized panes, with the window itself at 1-30x realtime rather than
3,000x. That is the realistic shape of "solved": realtime for the whole
interaction, honest about the window, convergent under refinement.

## 4. The route

Two efforts should run in parallel from the start, each iterated until its gate
passes, with the reference lane and the playground as the judges. Neither is
research; both are engineering on code that exists.

**Phase 1 - make the answer converge (Wall 2).** On `src/fastlattice`:
replace the strain-threshold failure with an energy-consistent threshold
derived from `fracture_energy_j_m2`, the horizon and the cell size (Silling &
Askari critical stretch, or crack-band scaling of the damage ramp), keep
`tensile_strength` as the initiation bound; replace the Gauss-Seidel sweep with
explicit velocity-Verlet / Jacobi force accumulation; raise the horizon to 3
and make it part of the study. Gate: on the 240 x 160 x 40 tile at 8 and
12 m/s, piece count, largest piece and removed energy agree within the
reference's own spread across 20 / 10 / 5 mm cells and across dt and dt/2;
sweep order is not a variable any more by construction; crack speed on a
pre-cracked strip stays below 0.6 c_R; the Hertzian cone under a ball on a
thick block appears. Glass, oak and iron under the same conditions, every time.
Cost of a wrong turn here is measured in hours, not days: the equality suite
and the reference lane already exist.

**Phase 2 - make it fast (Wall 1).** Same lane, one kernel per substep on the
GPU, persistent kernel or CUDA graph so a 3,000-substep window is one launch,
contact as a per-node SDF test, pieces handed to Jolt as today. Gate: the
1,536-cell 10 mm tile through rest inside 1.1x; 250k bonds at >= 1e10
bond-updates/s; the fracture-window ratio shown on the case card next to the
total. Both phases land in the playground through the existing importer, so
every gate is something the owner watches, not a number in a log.

**Phase 3 - localise and precompute.** The modal basis as the predictor:
compute it at object creation (it is instant at these sizes), evaluate an
impact in closed form to decide whether and where the object breaks, and run
the lattice only in a region grown from the first-failure set (cells within a
few horizons of any damaged bond, plus the wave front); everything outside
stays rigid or modal. After the cascade, pieces become rigid bodies with a
Craig-Bampton basis each. This is the owner's "embedded knowledge per object"
in the form the measurements support, and it is what makes the last row of the
table above reachable. Gate: the 1 m pane at 2 mm cells through rest inside
1.1x.

**Phase 4 - the rest of the brief.** The quasi-static lane for slow loading
(cutting, pressing, bending, tearing); an MPM evaluation on the tomato and
tissue suites if the lattice cannot carry large deformation; the blunt-control
fixture rebuilt so it cannot topple, and the runtime suite green, before `main`
moves.

**Phase 5 - the playground.** The Builder drives the fast lattice, not the
network lane; every card shows the total ratio and the window ratio; over
budget is refused before it starts, as now.

## 5. What to stop

- Making the network lane faster or more careful; it stays the rigid substrate.
- Basis updates through cascades; the modal lane is a predictor and a
  post-fracture representation.
- Quasi-static glass shatter demonstrations.
- Constant-factor work on the Gauss-Seidel sweep (warp stages, cluster
  barriers, multi-GPU).
- Any comparison of piece counts between lanes or resolutions until Phase 1's
  gate passes; until then only removed energy, first failure and largest piece
  are evidence.
- Any change to a tolerance to pass a gate.

## 6. What this week actually established

Three lanes were run in parallel, one round each, and each returned a precise
result: the modal basis is exact and cannot carry the cascade; the quasi-static
picture is fast and is the wrong mechanism for impact; the GPU lattice meets
the rule to 384 cells with the window resolved and is held back by its own
schedule and criterion. None was iterated after its first round; that was the
gap between what was asked ("until we find one that can run quickly enough")
and what was done. The measurements are what make the route above concrete:
the walls are named, the fixes are on code that exists, and each phase has a
gate the owner can watch.
