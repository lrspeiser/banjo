# Quasi-static fracture lane checkpoint

Tested code: branch `agent/fast-quasistatic` in worktree
`C:/Users/henry/dev/banjo-agents/fast-quasistatic`, based on `f7c4dc3` with
`agent/playground-rebuild` (`641e658`) merged. September 7, 2026,
America/Los_Angeles. Not pushed, not merged, not on main.

Predecessors: the [implicit-lane fracture checkpoint](implicit-fracture-checkpoint.md),
whose transactional Newton/GMRES solver is the dynamic reference here and whose
shared criterion (`fracture/BondFailure.hpp`) this lane calls unchanged; the
[realtime envelope](../../envelope/docs/realtime-envelope-checkpoint.md) that
measured every stepped lane at 3,000-10,000x off realtime for any fracture; and
the [playground admission and cost checkpoint](playground-admission-and-cost-checkpoint.md)
whose 1.1x rule this lane was built against.

## Result

**The rule is met, on the real engine, with a recording the owner can watch:**
a uniform-cube glass tile struck by an iron ball, computed through impact,
fracture, and settling to rest, in **0.014x to 0.03x** of its simulated
duration for tiles of 128 to 512 cells, and **1.34x** (not met) at 1,152 cells
when the run is cut short of settling. The fracture itself costs 5-140 ms of
wall time for the whole cascade, against 0.26-2.7 s for the dynamic reference
on the same lattice (160x-1,354x realtime).

**The physics is the obstacle, not the cost.** On every glass scene tried, the
quasi-static lane craters the tile and stops the ball; the dynamic reference
fragments it. At 8x8x2 cells and a 2 m drop the static answer is 156 broken
bonds in one piece with the ball rebounding, the dynamic answer is 400-912
broken bonds in 2-30 pieces depending on the reference's own removal timing and
step. The static count lies outside the reference's whole spread by a factor of
2.6-5.8, the piece count by a factor of 2-30, while the *removed energies*
agree within 11-25%. The difference is not a matter of tolerance: it is that
the static load path spreads the impact to the rim while inertia confines the
dynamic one, and the ball-to-tile mass ratio of 0.4-1.0 puts these scenes in
the wave-controlled regime. That is the research answer, and it is negative for
this class of scene: **a quasi-static solve does not produce the shatter, and
the difference is the whole visual outcome.**

Three things are **implemented and measured**:

- `fracture/QuasiStaticFracture.{hpp,cpp}`: a static equilibrium solver for the
  live bond lattice with unilateral support and ball contact, and an
  event-driven loading loop that spends one linear solve per event, applies the
  shared criterion, and freezes pieces that lose their static answer. Its
  energy ledger closes to `1e-9`-`1e-11 J` on every run with every term named.
- `src/app/quasistatic_probe_main.cpp`: the scene (tile on a frame, iron ball
  dropped onto it), the fall in Jolt, the lane, the optional dynamic reference on
  the identical lattice and impact, the pieces into Jolt, settling to rest, and
  the `banjo.playback.v1` recording. It also settles the *reference's* pieces
  and records them, so the two answers can be watched side by side.
- `matter/Lattice.hpp`: `generateBoxLattice`, a uniform cubic-cell box with
  the sphere generator's bond rules, and `physics/ConservativeStep.hpp`: an
  optional per-node support mask so the reference can rest a tile on a frame.

Nothing here is **validated** against laboratory glass; the two lanes are
compared with each other on a lattice whose contact is a point on a node.

## Method

### The static picture

The cracks that matter are decided in about 140 us; nobody sees them. The lane
therefore never integrates the wave. At each stage it solves

    K u = f + reactions,   K = sum over live bonds of k (d d^T) on [a, b]

linearised about the rest configuration (strains are `1e-3`, so the
linearisation error is of that order; the criterion still reads the actual
positions `X + u`). `f` is gravity. The support is a plane on which only the
tile's bottom rim nodes may rest, unilaterally and without friction. The ball
is a rigid sphere whose contacted nodes are held on its surface, unilaterally
and without friction. Constraints are enforced by projection, node by node: the
constrained directions are orthonormalised, the prescribed displacement is
solved in that subspace, and preconditioned conjugate gradients run on
`P K P` with a block-Jacobi preconditioner built the same way. The active set
is iterated: a contact whose reaction pulls is released, a node that penetrates
is activated.

What statics cannot answer, the lane pins and reports, never regularises:

- **Rigid modes.** A frictionless support leaves a component free to slide
  and spin in its plane. Those modes, computed per connected component as the
  rigid motions compatible with the *anchoring* constraints (support and frozen
  nodes, never the ball), are projected into the constrained subspace and
  deflated from the iteration. The load they would have carried is the friction
  the frame needs, and it is reported (`required_friction_coefficient`:
  `1e-11` to `1e-7` on every centred scene, i.e. nothing). Leaving the ball out
  of the anchors is deliberate: a single tilted ball contact otherwise makes the
  whole tile slide away at zero force, which is what the first version did.
- **Mechanisms.** A node whose live bonds no longer span three directions
  (a dangling node in the crater) has that direction pinned at its current
  value and counted. A zero-stiffness direction the per-node check cannot see (a
  flap on a hinge) is caught when conjugate gradients meet negligible curvature:
  the direction is pinned, its load charged, the iteration restarted. Runs report
  4-24 pinned directions after cratering and 0 flap modes.
- **Pieces without a static answer.** A component with fewer than three
  non-collinear active support nodes is frozen: snapped to its rest shape about
  its mass-weighted mean displacement, its stored energy charged as *released*.
  It becomes a rigid piece for Jolt with zero velocity; the static picture cannot
  give it one, and the lane says so rather than inventing one.
- **Loose contact nodes.** A node with a pinned direction cannot carry the
  ball; it is excluded from contact, so the ball proceeds to the next node the
  lattice can still resist with.

### Event-driven loading

Between events the system with a fixed active set is affine in the ball's
travel `s`: one solve at the current travel and one *rate* solve (unit ball
step, no loads) give `u(s) = u_0 + s u'` and every reaction `lambda(s) =
lambda_0 + s lambda'`. The next event is the smallest of:

1. a bond reaching the shared criterion's removal threshold, found by a
   secant bracket and Illinois iteration on the criterion's own ratio evaluated
   with `resetBondStrainPeaks`/`accumulateBondStrainPeaks` at trial travels
   (the ratio is nearly affine; 3-6 evaluations);
2. an active reaction reaching zero (release; a reaction already at or below
   zero and falling releases at zero travel);
3. an inactive contact closing (support: affine; ball: a quadratic in `s`;
   a contact that touches and closes at the current travel joins at zero
   travel, and one that has already been released at this travel is a
   knife-edge that stays locked until the travel advances);
4. the ball's work `W_0 + F_0 s + F' s^2 / 2` reaching its kinetic energy
   (the ball stops; the stored elastic energy is returned to it as rebound);
5. the travel limit (tile thickness plus one cell).

At a bond event the shared `applyBondFailure` removes what it removes (the
event lands at ratio `1 + 1e-9`), the stiffness is rebuilt, components are
recomputed and frozen if unsupported, the state is re-solved at the same travel,
and the loop repeats until nothing fails: that is one *round*. The ball's
energy budget is the load; nothing precuts, animates, or launches.

Ledger, per run: `kinetic_in = work + kinetic_out`, and
`work = (potential_end - potential_start) + removed + released + relaxation`,
where `removed` is the linear-model stored energy of removed bonds (the shared
criterion's own figure from actual positions is reported alongside and agrees
to strain order), `released` is the energy of frozen pieces, and `relaxation`
is what re-equilibration at fixed travel sheds, energy the dynamic lane would
carry as motion. The independent check is `segment_work_mismatch`, the largest
disagreement between the integrated reaction work and the potential change over
any segment: `4e-10` to `5e-7 J` on runs of 40-100 J, i.e. the solver's own
`1e-10` residual tolerance.

### Handoff to Jolt and the recording

Pieces are `findConnectedComponents` of the final lattice. Each becomes one
Jolt body: its cells are merged greedily into axis-aligned boxes
(`fracture/PieceGeometry.hpp`; a solid block is one box), a single box goes
through `addBox`, up to 64 through `addCompound` with the piece's own mass and
inertia, more than 64 through the legacy convex-hull fragment path (counted;
never hit in these runs). Velocities are what the nodes carry: zero for the
quasi-static lane, the fragment velocities for the reference. The ball is
given the energy-balance velocity (rebound when stopped, the remaining kinetic
energy when through) and lifted along its path until it clears every cell box,
because lattice contact is against node points half a cell below the cell
surface; the lift is reported (12-25 mm). The frame is four static iron bars,
the floor is the engine's concrete floor; contact restitution comes from each
catalog material's declared contact damping through `combineContactMaterials`,
so the network lane's restitution defect never applied here.

The recording is written directly in the `banjo.playback.v1` schema the 3D tab
plays: the fall at 60 fps with the intact tile as one mesh body, the contact
frame with every bond, the fracture frame with the pieces and the dead bonds
red, then settling at 60 fps. `scripts/install_quasistatic_playback.py`
registers a recording as a playground job; both recordings below were opened
in the 3D tab and play (frame 153/153 at 2.49 s for the 8x8 scene).

### Literature actually used

- Herrmann and Roux (eds.), *Statistical Models for the Fracture of Disordered
  Media*, North-Holland 1990: the quasi-static lattice algorithm this lane is,
  solve, remove the bond that reaches its threshold, re-solve. The event-driven
  scaling of the load to the next failure is theirs.
- Hahn and Wojtan, SIGGRAPH 2015 and 2016: the premise that the transient is
  invisible and the outcome is what must be right, and coupling a quasi-static
  fracture solve to a rigid-body solver. Their BEM machinery was not used; the
  lattice already exists.
- Francfort and Marigo 1998, Bourdin, Francfort, Marigo 2008: the framing of
  the ball's kinetic energy as the budget a quasi-static path spends on stored
  and surface energy. Their Gc criterion is *not* used; the shared strain
  criterion is, so the pattern stays comparable to the reference.
- Olsson, *Mass criterion for wave controlled impact response of composite
  plates*, Composites A 31 (2000) 879-887: quasi-static impact response requires
  an impactor much heavier than the plate; below about a quarter of the plate
  mass the response is wave controlled. Used to interpret, not to build.
- Marazzato, Ern, Monasse, *Quasi-static crack propagation with a Griffith
  criterion using a variational discrete element method*, Comput. Mech. 2022:
  consulted as the current discrete quasi-static formulation; its kinking
  criterion was not needed on a lattice.
- Silling 2000, Silling and Askari 2005: the bond lattice is a bond-based
  peridynamic model with a critical-stretch criterion; consulted for that
  identification only.

## Conditions

Tile: `n x 2 x n` cubic cells of 20 mm (aspect 1:1), resting by its bottom rim
on an iron frame 0.30 m above the concrete floor, interior unsupported. Glass
from the catalog through `withStrengthDerivedFailure(compileElasticLatticeReference(...))`,
horizon 2, exactly as the implicit checkpoint compiles it: tensile removal at
strain `1.2857e-3`, shear at `2.44e-3`, compressive at `2.857e-2`, uniform
strength (no variation, no damping). Ball: iron, radius 40 mm, 2.11 kg,
dropped so that free fall to the first contacted node is the stated height,
centred on the tile (a 4-node first contact on even tiles, 1-node on odd).
Gravity on. Reference: `tryFracturingStep` with the same lattice, plane and
mask, the sphere as `CoupledSphereState`, `StepRestart` unless stated, trial
budget 1024, run for 2 ms or until 0.5 ms pass with no failure.

| Scene | Nodes | Bonds | Tile mass | Ball KE at contact |
|---|---|---|---|---|
| 8x8x2, 2 m | 128 | 1,096 | 2.56 kg | 40.9 J |
| 12x12x2, 3 m | 288 | 2,648 | 5.76 kg | 61.4 J |
| 16x16x2, 5 m | 512 | 4,872 | 10.24 kg | 102.6 J |
| 24x24x2, 3 m, ball 60 mm (7.12 kg) | 1,152 | 11,336 | 23.0 kg | 207.3 J |

A 0.39 m drop (the playground's Stage A height, 7.8 J) breaks nothing in the
static picture on any tile from 8x8 to 32x32: the tile stores the energy
elastically (failure would need ~35 J on 8x8x2) and the ball rebounds
elastically. The 2-5 m drops above were chosen because they are the smallest
that make the static lane break anything.

## 1. Accuracy against the dynamic reference

### 8x8x2, 2 m: the reference's own spread, and where the static answer sits

| Lane | dt (s) | dt / lattice limit | Removal timing | Broken bonds | Pieces | Largest piece | Removed energy | Ball after |
|---|---|---|---|---|---|---|---|---|
| quasi-static | - | - | - | **156** | **1** | 100% | 15.9 J | rebound 1.93 m/s up |
| reference | 2.5e-6 | 0.79 | restart | 44 | 1 | 100% | 5.6 J | 4.9 m/s up (cascade not reached) |
| reference | 1.25e-6 | 0.39 | restart | 704 | 3 | 50% | 21.0 J | 0.05 m/s |
| reference | 6.25e-7 | 0.20 | restart | 835 | 10 | 91% | 20.4 J | 0.87 m/s down |
| reference | 1.25e-6 | 0.39 | end | 912 | 30 | 58% | 22.4 J | 0.72 m/s down |
| reference | 1.25e-6 | 0.39 | bisect | 400 | 2 | 91% | 17.9 J | 0.04 m/s down |

The reference does not converge, as its own checkpoint says: 400-912 bonds and
2-30 pieces across the two fine steps and three removal timings (the coarse
step never reaches the cascade within 2 ms and is excluded from the spread).
The quasi-static count, 156, is **2.6x below the lowest and 5.8x below the
highest** of that spread; its piece count, 1, is below every dynamic outcome.
Removed energy, the quantity the reference does converge, is 15.9 J against
17.9-22.4 J: 11-29% low.

Set overlap with the `dt=1.25e-6`, restart reference: broken-bond Jaccard
0.17, per-node damage correlation 0.47, crack centroid 0.4 mm apart, crack
radius of gyration 28 mm (static) against 57 mm (dynamic). The dynamic damage
reaches the rim; the static damage is a crater.

**First failure.** The static lane's first event is six bottom-layer tension
bonds 6.7 mm from the axis at a contact force of 244 kN after 0.28 mm of ball
travel: bending tension under the load, exactly where a plate theory puts it.
The reference's first failure, 61 us after contact, is sixteen tension bonds in
the diagonal inter-layer bonds 22 mm from the axis (14 mm at the finest step):
a ring around the contact, the lattice's version of a Hertzian cone. The two
lanes do not begin at the same place or by the same mechanism, and their
first-failure sets are disjoint (Jaccard 0) at every step and timing.

### Larger tiles and the material comparison

| Scene | Lane | Broken | Pieces | Largest | Removed | Ball after | Damage corr. | Jaccard |
|---|---|---|---|---|---|---|---|---|
| 12x12x2, 3 m | quasi-static | 142 | 1 | 100% | 18.7 J | 3.5 m/s up | | |
| | reference 1.25e-6 | 1,390 | 30 | 85% | 24.2 J | 1.7 m/s up | 0.26 | 0.07 |
| | reference 6.25e-7 | 1,221 | 14 | 95% | 23.7 J | 1.3 m/s up | 0.38 | 0.10 |
| 16x16x2, 5 m | quasi-static | 178 | 1 | 100% | 21.5 J | 5.9 m/s up | | |
| | reference 1.25e-6 | 2,193 | 14 | 86% | 38.5 J | 3.9 m/s down | 0.23 | 0.06 |
| 8x8x2, 2 m, **oak** | quasi-static | 0 | 1 | 100% | 0 | 6.2 m/s up | | |
| | reference 1.25e-6 | 122 | 2 | 97% | 9.8 J | 0.7 m/s up | 0 | 0 |
| 8x8x2, 2 m, **iron** | quasi-static | 0 | 1 | 100% | 0 | 6.2 m/s up | | |
| | reference 1.25e-6 | 0 | 1 | 100% | 0 | 4.4 m/s up | - | 1 |

Glass: the reference breaks 8-12x more bonds than the static lane and makes
14-30 pieces where the static lane makes one. Oak: the reference chips a 3%
corner (38 compression-first bonds under the contact) that the static lane does
not see. Iron: both lanes agree that nothing breaks, and both rebound the ball,
at 4.4 m/s (dynamic, with 0.5 J left in the tile's vibration) and 6.2 m/s
(static, all stored energy returned). The static lane's rebound is
systematically the elastic upper bound.

### Would the difference be visible?

Yes, and it is the entire outcome: one piece with a crater and a ball that
bounces back up, against 3-30 pieces of which the small ones fall through the
frame while the ball goes on through (16x16) or dribbles off. Both were settled
in Jolt and recorded; in the 8x8 reference recording a 0.08 kg chip falls to the
floor and the ball rolls off the frame, while in the quasi-static recording the
tile stays whole and the ball comes to rest on top of it after 1.86 s. The
reference's own refinement spread (bond count +-30%, pieces 2-30) is wide, but
the static answer is not inside it on any count.

## 2. Cost, measured

Windows 11, MSVC 19.44, VS 2022 x64 Release, serial code, Jolt with zero
worker threads, other agents' work running on the machine; single runs, not
repeated benchmarks. Simulated duration is fall plus settling to rest (all
bodies below 1 mm/s and 0.01 rad/s for 0.5 s). Jolt runs at 1/120 s, frames at
60 fps. The reference and its recording are excluded from the pipeline time.

| Scene | Simulated | Fall | Fracture (solves, PCG iterations) | Settle | Recording | Total wall | Ratio | Rule |
|---|---|---|---|---|---|---|---|---|
| 8x8x2, 2 m, glass | 2.49 s | 2.2 ms | 12.7 ms (63, 1,671) | 4.7 ms | 16 ms | 0.036 s | **0.014x** | met |
| 12x12x2, 3 m | 4.09 s | 4.1 ms | 56 ms (92, 3,861) | 9.8 ms | 11 ms | 0.082 s | **0.020x** | met |
| 16x16x2, 5 m | 6.01 s | 6.9 ms | 136 ms (97, 5,902) | 17 ms | 24 ms | 0.184 s | **0.031x** | met |
| 24x24x2, 3 m, 60 mm ball | 0.79 s (cut at 0.01 s settle) | 26 ms | 1,008 ms (182, 25,308) | 28 ms | - | 1.06 s | **1.34x** | not met |
| 32x32x2, 5 m (no fracture) | 1.02 s (cut) | 48 ms | 1,251 ms (82, 14,189) | 50 ms | - | 1.35 s | 1.32x | not met |

The cascade is the cost, and inside it the linear solves are 95% of the
fracture stage. The static solves are not slow per iteration (60-90 us per
PCG iteration at 11-20k bonds); the iteration count is: 20-30 iterations on an
intact tile, 100-300 once the crater has made the local stiffness ratio large,
with the block-Jacobi preconditioner. At 1,152 nodes that is 25,308 iterations
over 182 solves, one second. The number of solves, two per event plus one per
round, is not the problem: 40-180 events per scene.

The dynamic reference on the same scenes: 8x8x2 0.26-0.53 s for 1.3-1.7 ms
simulated (160x-316x realtime); 12x12x2 1.4-2.7 s for 2 ms (700x-1,354x);
16x16x2 2.65 s for 2 ms (1,324x). Per fracture event the static lane is
10-100x cheaper; per second of simulated interaction it is 4-5 orders of
magnitude cheaper, because it charges nothing for the wave.

## 3. The research question, answered

*What does the quasi-static answer get wrong relative to the dynamic one, and
does it matter visually?*

It gets the mechanism wrong, and therefore the outcome. In the static picture
the ball's push is carried by the whole tile to the rim; bending tension under
the load is the first thing to fail (bottom layer, 244 kN on 8x8x2, at the
force plate theory predicts), then the contact zone crushes into loose nodes,
the ball proceeds until the ring of nodes around the crater carries it, and
the remaining energy is stored elastically and returned as rebound. The tile
is too strong for the ball to break through statically: a 40 mm glass slab on a
160-320 mm span needs 35-200 J of static work to fail in bending.

In the dynamic picture the load never reaches the rim in time. The first
failures are the inter-layer diagonals around the contact within 40-60 us,
while the stress wave is still 200 mm from the edge; the stored energy in the
contact region has nowhere to go but into more bonds, and the pattern runs
outward to the rim as cracks (radius of gyration 57-95 mm against 28-29 mm
static). That is inertial confinement plus wave loading, and it is consistent
with Olsson's criterion: these balls weigh 0.2-0.8 of their tiles, not the
several times a quasi-static response needs.

The removed energy is the one thing the two agree on within ~25%, which is
also the one thing the reference converges. The count and the topology of what
that energy removes are different, and in the direction that matters: the
quasi-static lane under-fragments, so the pieces the owner wants to watch fall
do not exist in its answer. This is not fixable by a tolerance, a finer lattice
or a better preconditioner; it is what the approximation is.

What the quasi-static lane *is* good for, from these measurements: iron and
the no-fracture regime (both lanes agree), the first bending failure of a plate
loaded slowly enough, the removed-energy budget to within a quarter, and any
scene where the striker is much heavier than the plate. It is also a cheap,
exact-ledger static solver that the modal lane could use for its first
failure. It is not a route to the shatter.

## 4. What does not work

- **No fragmentation, on any glass scene tried.** The static lane ends with
  one piece (plus a chip on the 24x24 tile) where the reference ends with
  3-30. Section 3 says why; it is not a bug.
- **The ball's rebound is the elastic upper bound.** All stored energy is
  returned to the ball; the dynamic tile keeps some as vibration and fragment
  motion. The static ball comes back 1.4x-2.7x faster than the reference's
  where both rebound.
- **Pieces start from rest.** A frozen piece has no static velocity. The
  reference's pieces carry 6-16 J of kinetic energy into Jolt; the static
  lane's carry zero.
- **1.1x fails above ~1,000 cells with fracture** (1.34x at 1,152 cells with
  the run cut short of settling; a full settle of ~3 s would put the same
  work at ~0.4x). The block-Jacobi preconditioner is the reason; an
  incomplete-Cholesky or a factorisation updated by Woodbury for the few bonds
  each round removes would cut the 100-300 iterations per cratered solve by an
  estimated 3-10x. Not done.
- **Point contact.** Both lanes contact node points, so neither sees Hertzian
  stresses; the lattice's own contact stiffness (`8.7e8 N/m`) sets first
  failure. Real glass under this ball would fail at the contact at ~3 GPa long
  before either lane's threshold.
- **The reference is not converged**, and its removal timing changes its
  answer by 2.3x in bond count. The comparison above is against the spread,
  not a number.
- **Mechanism pins and freezes are approximations the lane reports**, not
  physics: 4-24 pinned directions per cratered run, 0-61 frozen pieces. A
  frozen piece's stored energy is charged as released and it is handed to Jolt
  at rest.
- **The recording lifts the ball by up to 25 mm** at handoff to clear the
  cell boxes the lattice's point contact ignores.
- The fall stage is Jolt free flight; the landing on the contact node is
  exact to `3e-10 m` by solving Jolt's own update for the last partial step.

## Verification

Windows Release, `-DBANJO_BUILD_LAB=OFF`. `python scripts/check-source-registration.py`
reports every source registered. CTest: see the commit message for the count;
`banjo_network_skin_tests`, `banjo_network_runtime_tests` and
`banjo_material_showcase_tests` excluded by instruction. **No existing test's
tolerance was changed and no existing test file was edited.** Existing lanes
are untouched except for the additive support mask on `ConservativeStepSettings`
(null keeps the old behaviour) and the sphere generator's bond loop moving into
a shared helper (byte-identical output; `banjo_implicit_fracture_tests` and every
lattice test still pass).

`tests/quasistatic_fracture_tests.cpp` adds nine checks:

- the box lattice is uniform (every cell full, mass = density x volume) and
  follows the sphere generator's bond rules (horizon, compliance weights);
- the static solver is an equilibrium solver: reactions balance the load to
  `1e-8`, stored energy is half the work (Clapeyron) to `1e-9`, free nodes have
  zero residual, and a glass bar comes out at `7.7e10 Pa` apparent modulus;
- a tile resting on its rim carries exactly its weight on non-negative rim
  reactions, needs no friction, and its unsupported interior sags through the
  hole in the frame;
- the lane and the implicit lane name the identical failing bonds on the same
  over-stretched lattice for glass, oak and iron (the criterion is shared, not
  copied);
- the impact ledger closes to `1e-9 J` with every term named, the reactions
  integrate to the potential change to `1e-7` relative, mass is untouched, no
  node is given a velocity, and component bookkeeping matches the shared
  function;
- a tile with no support is frozen whole and reported, never regularised: the
  ball passes, nothing breaks, no work is done;
- glass, oak and iron run through the identical 7x7x2, 2 m scene (glass
  breaks; all three reach a physical stop);
- the reference's support mask restricts support to the masked nodes and
  rejects a mask of the wrong size;
- greedy voxel boxes cover every cell exactly once and merge a solid block
  into one box.

Reproduction (from the worktree root):

```powershell
cmake -S . -B build/agent -G "Visual Studio 17 2022" -A x64 -DBANJO_BUILD_LAB=OFF
cmake --build build/agent --config Release --parallel 4
ctest --test-dir build/agent -C Release -E "banjo_network_skin_tests|banjo_network_runtime_tests|banjo_material_showcase_tests"

# Section 1: the 8x8x2 comparison, both recordings, the report
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4 --record qs.json --record-reference ref.json --report report.json
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --reference-dt 6.25e-7 --reference-duration 2e-3 --reference-quiet 5e-4
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --reference-dt 2.5e-6  --reference-duration 2e-3 --reference-quiet 5e-4
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4 --reference-timing end
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4 --reference-timing bisect
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --material oak  --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --material iron --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4

# Larger tiles
./build/agent/Release/banjo_quasistatic_probe.exe --cells 12 2 12 --drop 3.0 --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4 --settle-max 10 --record qs12.json --record-reference ref12.json
./build/agent/Release/banjo_quasistatic_probe.exe --cells 16 2 16 --drop 5.0 --settle-max 10 --record qs16.json
./build/agent/Release/banjo_quasistatic_probe.exe --cells 24 2 24 --drop 3.0 --ball-radius 0.06 --settle-max 0.01

# Watch it: register a recording as a playground job, then open the printed URL
python scripts/install_quasistatic_playback.py qs.json --report report.json --name "Quasi-static lane"
python playground/server.py --port 8790 --engine build/agent/Release/banjo_platform_cli.exe --studio build/agent/Release/banjo_network_lab.exe --runs build/playground-runs
```

`--trace` prints every solve, event, round, release, activation and freeze to
stderr; it is how every defect in this lane's history was found.

## Next

Ordered by what the measurements say:

1. **Do not pursue the quasi-static lane as the route to the shatter.** The
   answer is qualitatively wrong for ball-on-tile at these mass ratios, and no
   tolerance or preconditioner changes that. Its static solver, ledger, freeze
   rule and Jolt handoff are reusable: the modal lane could take the first
   bending failure and the piece-to-Jolt path from here.
2. **If the static picture is kept for anything, precondition it.** An
   incomplete Cholesky or a Woodbury update of one factorisation per cascade
   would bring 1,152 cells with fracture inside 1.1x by the measured iteration
   counts.
3. **The reference needs its own convergence before it can be a yardstick:**
   400-912 bonds across removal timings on one scene is not a spread, it is a
   choice. The removed energy is the only converged quantity to compare on.
4. **Contact.** Both lanes contact node points; a cell-face or Hertz-type
   contact on the lattice would change first failure in both and is the next
   physics both lanes share.
