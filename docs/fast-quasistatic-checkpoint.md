# Quasi-static fracture lane checkpoint

Tested code: branch `agent/fast-quasistatic` in worktree
`C:/Users/henry/dev/banjo-agents/fast-quasistatic`, based on `f7c4dc3` with
`agent/playground-rebuild` (`641e658`) merged. September 7, 2026,
America/Los_Angeles. Not pushed, not merged, not on main.

Predecessors: the [implicit-lane fracture checkpoint](implicit-fracture-checkpoint.md),
whose transactional Newton/GMRES solver is the dynamic reference here and whose
shared criterion (`fracture/BondFailure.hpp`) this lane calls unchanged; the
realtime envelope checkpoint (`docs/realtime-envelope-checkpoint.md` on
branch `agent/realtime-envelope`, not on this branch) that measured every
stepped lane at 3,000-10,000x off realtime for any fracture; and
the [playground admission and cost checkpoint](playground-admission-and-cost-checkpoint.md)
whose 1.1x rule this lane was built against.

## Result

**The rule is met, on the real engine, with recordings the owner can watch:**
a uniform-cube glass tile struck by an iron ball, computed through impact,
fracture, and settling to rest, in **0.010x to 0.37x** of its simulated
duration for tiles of 128 to 2,048 cells. It **fails at 3,200 cells (1.56x)**
and at 4,608 cells (9.5x, where the lane's own active-set iteration also fails
to converge). The fracture itself costs 13 ms to 2.8 s of wall time for the
whole cascade on the tiles that meet the rule, against 0.16-2.9 s for the
dynamic reference on the 128-512-cell lattices where it was run (166x-1,468x
realtime). Four recordings are installed as jobs in the owner's playground;
their ids and what each shows are under Verification.

**The physics is the obstacle, not the cost.** On every glass scene tried, the
quasi-static lane craters the tile and stops the ball; the dynamic reference
fragments it. At 8x8x2 cells and a 2 m drop the static answer is 156 broken
bonds in one piece with the ball rebounding, the dynamic answer is 400-912
broken bonds in 2-30 pieces depending on the reference's own removal timing and
step. The static count lies outside the reference's whole spread by a factor of
2.6-5.8, the piece count by a factor of 2-30, while the *removed energies*
agree within 11-29%. The difference is not a matter of tolerance: it is that
the static load path spreads the impact to the rim while inertia confines the
dynamic one, and the ball-to-tile mass ratio of 0.4-1.0 puts these scenes in
the wave-controlled regime. That is the research answer, and it is negative for
this class of scene: **a quasi-static solve does not produce the shatter, and
the difference is the whole visual outcome.** At 1,152-3,200 cells with heavier
balls the static lane does make 2-26 pieces, but every piece except the tile
itself is a 20-160 g crater chip (0.05-0.35% of the tile) frozen loose with no
velocity: a crater, not a shatter.

The dynamic reference is not the far side of the rule at these sizes either.
Stopped 0.5 ms after its last failure and handed to Jolt exactly as the static
pieces are, its whole pipeline is 0.05x at 128 cells (0.33 s of wall for 6.6 s
simulated) and 0.15x at 288 cells (1.6 s for 10.8 s); its recordings are cut at
the settle cap because its ball rolls off the frame and Jolt gives it no rolling
resistance. The static lane is 13-27x cheaper per cascade at 128-512 cells;
what separates the two lanes there is the answer, not the rule.

Three things are **implemented and measured**:

- `fracture/QuasiStaticFracture.{hpp,cpp}`: a static equilibrium solver for the
  live bond lattice with unilateral support and ball contact, and an
  event-driven loading loop that spends one linear solve per event, applies the
  shared criterion, and freezes pieces that lose their static answer. Its
  energy ledger closes to `4e-11`-`1e-5 J`, at most `2e-8` of the ball's work,
  on every completed run with every term named; an aborted run's ledger does
  not close and is reported as such.
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
  `1e-11` to `4e-7` on every centred scene, i.e. nothing). Leaving the ball out
  of the anchors is deliberate: a single tilted ball contact otherwise makes the
  whole tile slide away at zero force, which is what the first version did.
- **Mechanisms.** A node whose live bonds no longer span three directions
  (a dangling node in the crater) has that direction pinned at its current
  value and counted. A zero-stiffness direction the per-node check cannot see (a
  flap on a hinge) is caught when conjugate gradients meet negligible curvature:
  the direction is pinned, its load charged, the iteration restarted. Runs report
  4-96 pinned directions after cratering and 0-1 flap modes (one at 3,200
  cells; four in the aborted 4,608-cell run).
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
criterion's own figure from actual positions is reported alongside; it agrees
to 0.6-3% on the 40 mm-ball scenes, whose craters are shallower than a cell,
and exceeds the linear figure by 1.4x, 3.7x and 5.8x on the 60, 80 and 90
mm-ball scenes, whose craters are deeper than a cell and outside the
linearisation, see section 4), `released` is the energy of frozen pieces, and
`relaxation` is what re-equilibration at fixed travel sheds, energy the dynamic
lane would carry as motion. The independent check is `segment_work_mismatch`,
the largest disagreement between the integrated reaction work and the potential
change over any segment: `5e-9` to `5e-7 J` on runs of 40-100 J and `5e-8` to
`9e-4 J` on runs of 200-700 J (`1e-10` to `2e-6` of the work), the solver's
`1e-10` residual tolerance amplified by the cratered lattice's conditioning.

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
surface; the lift is reported (12-42 mm). The frame is four static iron bars,
the floor is the engine's concrete floor; contact restitution comes from each
catalog material's declared contact damping through `combineContactMaterials`,
so the network lane's restitution defect never applied here.

The recording is written directly in the `banjo.playback.v1` schema the 3D tab
plays: the fall at 60 fps with the intact tile as one mesh body, the contact
frame with every bond, the fracture frame with the pieces and the dead bonds
red, then settling at 60 fps. `scripts/install_quasistatic_playback.py`
registers a recording as a job in any playground job store (`--runs`). The four
recordings listed under Verification were installed in the owner's store,
opened in the owner's playground (`127.0.0.1:8765`, the `?job=` URL lands on
the 3D tab), and play to their last frame (153/153 at 2.49 s for the 8x8
scene, 649/649 at 10.78 s for 24x24, 488/488 at 8.09 s for 32x32, 401/401 at
6.64 s for the reference) with no console errors.

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
| 32x32x2, 5 m (no fracture) | 2,048 | 20,488 | 40.96 kg | 102.6 J |
| 32x32x2, 3 m, ball 80 mm (16.88 kg) | 2,048 | 20,488 | 40.96 kg | 491.5 J |
| 40x40x2, 3 m, ball 90 mm (24.03 kg) | 3,200 | 32,328 | 64.0 kg | 699.8 J |
| 48x48x2, 4 m, ball 100 mm (32.97 kg) | 4,608 | 46,856 | 92.2 kg | 1,281.7 J |

A 0.39 m drop (the playground's Stage A height, 7.8 J) breaks nothing in the
static picture on any tile from 8x8 to 32x32: the tile stores the energy
elastically (failure would need ~35 J on 8x8x2) and the ball rebounds
elastically. The 2-5 m drops above were chosen because they are the smallest
that make the static lane break anything, and the heavier balls on the larger
tiles for the same reason: the 40 mm ball breaks nothing statically on a 32x32
tile even from 5 m.

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

On the tiles too large for the reference to be run (its 2 ms would cost tens
of seconds from 1,152 cells up), the static lane alone: 24x24 with the 60 mm
ball breaks 350 bonds into the tile plus one 80 g chip and rebounds the ball at
5.3 m/s; 32x32 with the 80 mm ball breaks 398 bonds into the tile plus nine
20-80 g chips and rebounds it at 6.3 m/s; 40x40 with the 90 mm ball breaks
1,392 bonds into the tile plus 25 chips of 60-160 g and the ball goes through
with 308 J of its 700 J left, the first static scene where the crater reaches
the bottom layer under the ball. Every chip is crater debris frozen without
velocity; the largest piece is 98.4-99.7% of the tile on all three.

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
floor and the ball rolls off the frame and keeps rolling (0.12 m/s when the 6 s
cap cuts the recording; Jolt gives it no rolling resistance), while in the
quasi-static recording the tile stays whole and the ball comes to rest on top of
it after 1.86 s. The
reference's own refinement spread (bond count +-30%, pieces 2-30) is wide, but
the static answer is not inside it on any count.

## 2. Cost, measured

Windows 11, MSVC 19.44, VS 2022 x64 Release, serial code, Jolt with zero
worker threads, other agents' servers idle on the machine; single runs, not
repeated benchmarks. Simulated duration is fall plus settling to rest (all
bodies below 1 mm/s and 0.01 rad/s for 0.5 s), or the 10 s settle cap where
that criterion never fires (section 4 says why). Jolt runs at 1/120 s, frames
at 60 fps. The reference and its recording are excluded from the pipeline time.

| Scene | Simulated (to rest) | Fall | Fracture (solves, PCG iterations) | Settle | Recording | Total wall | Ratio | Rule |
|---|---|---|---|---|---|---|---|---|
| 8x8x2, 2 m, glass | 2.49 s | 2.2 ms | 12.8 ms (63, 1,671) | 4.8 ms | 5.5 ms | 0.025 s | **0.010x** | met |
| 12x12x2, 3 m | 4.09 s | 4.2 ms | 57 ms (92, 3,861) | 10.6 ms | 15 ms | 0.087 s | **0.021x** | met |
| 16x16x2, 5 m | 6.01 s | 6.6 ms | 139 ms (97, 5,902) | 17 ms | 21 ms | 0.183 s | **0.030x** | met |
| 24x24x2, 3 m, 60 mm ball | 10.78 s (cap; every translation at rest by 6.76 s) | 16 ms | 1,235 ms (220, 28,313) | 38 ms | 58 ms | 1.35 s | **0.125x** (0.20x against 6.76 s) | met |
| 32x32x2, 5 m (no fracture) | 9.01 s | 28 ms | 1,285 ms (82, 14,189) | 57 ms | - | 1.37 s | **0.15x** | met |
| 32x32x2, 3 m, 80 mm ball | 8.09 s | 28 ms | 2,805 ms (193, 36,936) | 77 ms | 90 ms | 3.00 s | **0.37x** | met |
| 40x40x2, 3 m, 90 mm ball | 10.78 s (cap; ball rolls off, 0.055 m/s at 10 s) | 45 ms | 16,545 ms (525, 139,016) | 190 ms | - | 16.8 s | **1.56x** | not met |
| 48x48x2, 4 m, 100 mm ball | 10.90 s (cap) | 61 ms | 103,464 ms (759, 642,295; active set failed) | 174 ms | - | 103.7 s | **9.5x** | not met, not converged |

The cascade is the cost, and inside it the linear solves are 92-99% of the
fracture stage (the criterion evaluations are the rest). Three factors
multiply. The cost per PCG iteration is proportional to the live bond count:
5.6 us at 1.1k bonds, 39 us at 11k, 70 us at 20k, 110 us at 32k, 159 us at
47k, i.e. 3.4-5 us per thousand bonds. The iterations per solve grow with the
tile and with the crater under the block-Jacobi preconditioner: 27 at 128
cells, then 42, 61, 129, 191, 265 at 3,200 cells and 846 in the failing
4,608-cell run (an intact tile takes 20-30; a cratered one 100-300 and more,
because the crater's loose and pinned nodes make the local stiffness ratio
large). And the solves per run grow with the events, two per event plus one
per round: 63 solves at 128 cells, 220 at 1,152, 525 at 3,200. The product
grows as roughly the 2.3rd power of the cell count (12.8 ms at 128 cells to
16.5 s at 3,200) while the interaction it buys stays at 2.5-11 s, so the ratio
crosses 1.1 between 2,048 and 3,200 cells at these impact energies. Fall,
settle and recording are 0.01-0.3 s on every tile and never the problem.

The dynamic reference on the same scenes: 8x8x2 0.16-0.65 s for 0.6-1.7 ms
simulated (166x-408x realtime); 12x12x2 1.5-2.6 s for 2 ms (760x-1,291x);
16x16x2 2.9 s for 2 ms (1,468x). Per cascade the static lane is 13-27x cheaper
at these sizes; per second of fracture-lane simulated time it is 4-5 orders of
magnitude cheaper, because it charges nothing for the wave. The reference then
hands its pieces to Jolt exactly as the static lane does, and that whole
pipeline is itself 0.05x at 128 cells and 0.15x at 288 cells (see Result).

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
do not exist in its answer; the chips it does make from 1,152 cells up are
crater debris of 20-160 g, and the tile stays 98-99.7% whole. This is not
fixable by a tolerance, a finer lattice or a better preconditioner; it is what
the approximation is.

What the quasi-static lane *is* good for, from these measurements: iron and
the no-fracture regime (both lanes agree), the first bending failure of a plate
loaded slowly enough, the removed-energy budget to within a quarter, and any
scene where the striker is much heavier than the plate. It is also a cheap,
exact-ledger static solver that the modal lane could use for its first
failure. It is not a route to the shatter.

## 4. What does not work

- **No fragmentation, on any glass scene tried.** The static lane ends with
  one piece at 128-512 cells where the reference ends with 3-30, and with the
  tile plus 1-25 crater chips of 20-160 g at 1,152-3,200 cells. Section 3 says
  why; it is not a bug.
- **The ball's rebound is the elastic upper bound.** All stored energy is
  returned to the ball; the dynamic tile keeps some as vibration and fragment
  motion. The static ball comes back 1.4x-2.7x faster than the reference's
  where both rebound.
- **Pieces start from rest.** A frozen piece has no static velocity. The
  reference's pieces carry 6-16 J of kinetic energy into Jolt; the static
  lane's carry zero.
- **1.1x fails at 3,200 cells and above with fracture** (1.56x at 3,200
  cells, 9.5x at 4,608), computed through to rest; it holds to 2,048 cells
  (0.37x). Section 2 gives the three factors. The block-Jacobi preconditioner
  is the one that can be changed: an incomplete Cholesky or a factorisation
  updated by Woodbury for the few bonds each round removes would cut the
  130-850 iterations per cratered solve by an estimated 3-10x, which by the
  measured counts brings 3,200 cells inside the rule and 4,608 not. Not done.
- **The active-set iteration does not converge at 4,608 cells.** With the
  100 mm ball, after 88 events and 41 rounds (600 bonds removed), four
  mirror-symmetric ball contacts (nodes 2182, 2185, 2470, 2473) are released
  because they pull 0.435 N against a 31 kN contact force, re-activated as
  knife-edge contacts because without them they penetrate, released again, and
  so on until the 500-iteration budget stops the lane with `active_set_failed`
  103 s in (`--trace` shows the cycle verbatim). The ledger of the aborted run
  does not close (31.5 J open) and is reported so. The knife-edge threshold
  that decides this (`strong_pull`, `1e-6` of the force scale) was not
  widened, because that is the tolerance change the rules forbid; the fix is a
  contact algorithm with a convergence argument (Next).
- **The linearisation fails in a crater deeper than a cell.** The solve is
  linear about the rest configuration; the shared criterion reads actual
  positions. With the 40 mm ball the crater is 13 mm deep (0.65 cells) and the
  two removed-energy figures agree to 0.6-3%. With the 60-90 mm balls the
  travel is 15-34 mm, the crater nodes move more than a cell, and the
  criterion's figure is 1.4x (24x24), 3.7x (32x32) and 5.8x (40x40) the linear
  one: the transverse displacement of the crater's bonds stretches them
  geometrically in a way the linear model cannot see. The ledger still closes
  because it is the linear model's ledger; the removed energy it states is then
  not the lattice's. A corotational or Newton re-linearisation per round would
  fix it; not done.
- **"To rest" is a cap, not an event, whenever the ball leaves the frame.**
  Jolt gives the sphere no rolling resistance and no twist friction on the
  floor, so a ball that rolls off keeps rolling (the reference's, at 0.12 m/s
  when the 6 s cap cuts it; the 40x40 ball at 0.055 m/s at 10 s) or spins in
  place (the 24x24 ball, at 2.25 rad/s with `9e-7 m/s` of translation), and the
  1 mm/s / 0.01 rad/s rest criterion never fires. Those runs are cut at the
  settle cap and the cap is the simulated duration in the table; the ratio
  against the last translation (6.76 s at 24x24) is given alongside and
  changes no verdict.
- **Point contact.** Both lanes contact node points, so neither sees Hertzian
  stresses; the lattice's own contact stiffness (`8.7e8 N/m`) sets first
  failure. Real glass under this ball would fail at the contact at ~3 GPa long
  before either lane's threshold.
- **The reference is not converged**, and its removal timing changes its
  answer by 2.3x in bond count. The comparison above is against the spread,
  not a number.
- **Mechanism pins and freezes are approximations the lane reports**, not
  physics: 4-96 pinned directions per cratered run, 0-25 frozen pieces. A
  frozen piece's stored energy is charged as released and it is handed to Jolt
  at rest.
- **The recording lifts the ball by up to 42 mm** at handoff to clear the
  cell boxes the lattice's point contact ignores.
- The fall stage is Jolt free flight; the landing on the contact node is
  exact to `3e-10 m` by solving Jolt's own update for the last partial step.

## Verification

Windows Release, `-DBANJO_BUILD_LAB=OFF`, MSVC 19.44.
`python scripts/check-source-registration.py` reports every source registered
(193 files). CTest: **83 of the 88 registered suites run and pass** (94 s);
the five excluded by instruction, `banjo_network_skin_tests`,
`banjo_network_runtime_tests`, `banjo_material_showcase_tests`,
`banjo_network_adaptive_tests` and `banjo_contact_capacity_tests`, take 18
minutes to an hour each and none touches this lane (the previous session ran
the first four to a pass and the fifth timed out at 1,500 s). Every number in
this document was re-measured from a rebuild of the committed sources after
the last source edit; the previous session's 24x24 figures (182 solves,
1.34x with the settle cut at 0.01 s) predate that edit and are superseded.
**No existing test's tolerance was changed and no existing test file was
edited.** Existing lanes
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
ctest --test-dir build/agent -C Release -E "banjo_network_skin_tests|banjo_network_runtime_tests|banjo_material_showcase_tests|banjo_network_adaptive_tests|banjo_contact_capacity_tests"

# Section 1: the 8x8x2 comparison, both recordings, the report
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4 --record qs.json --record-reference ref.json --report report.json
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --reference-dt 6.25e-7 --reference-duration 2e-3 --reference-quiet 5e-4
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --reference-dt 2.5e-6  --reference-duration 2e-3 --reference-quiet 5e-4
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4 --reference-timing end
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4 --reference-timing bisect
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --material oak  --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8 --drop 2.0 --settle-max 0.01 --material iron --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4

# Larger tiles with the reference
./build/agent/Release/banjo_quasistatic_probe.exe --cells 12 2 12 --drop 3.0 --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4 --settle-max 10 --record qs12.json --record-reference ref12.json --report report12.json
./build/agent/Release/banjo_quasistatic_probe.exe --cells 12 2 12 --drop 3.0 --settle-max 0.01 --reference-dt 6.25e-7 --reference-duration 2e-3 --reference-quiet 5e-4
./build/agent/Release/banjo_quasistatic_probe.exe --cells 16 2 16 --drop 5.0 --settle-max 0.01 --reference-dt 1.25e-6 --reference-duration 2e-3 --reference-quiet 5e-4

# Section 2: the cost table, every scene through to rest (or the 10 s settle cap)
./build/agent/Release/banjo_quasistatic_probe.exe --cells 8 2 8   --drop 2.0 --record qs8.json --report rep8.json
./build/agent/Release/banjo_quasistatic_probe.exe --cells 12 2 12 --drop 3.0 --settle-max 10 --record qs12.json --report rep12.json
./build/agent/Release/banjo_quasistatic_probe.exe --cells 16 2 16 --drop 5.0 --settle-max 10 --record qs16.json --report rep16.json
./build/agent/Release/banjo_quasistatic_probe.exe --cells 24 2 24 --drop 3.0 --ball-radius 0.06 --settle-max 10 --record qs24.json --report rep24.json
./build/agent/Release/banjo_quasistatic_probe.exe --cells 32 2 32 --drop 5.0 --settle-max 10
./build/agent/Release/banjo_quasistatic_probe.exe --cells 32 2 32 --drop 3.0 --ball-radius 0.08 --settle-max 10 --record qs32.json --report rep32.json
./build/agent/Release/banjo_quasistatic_probe.exe --cells 40 2 40 --drop 3.0 --ball-radius 0.09 --settle-max 10 --report rep40.json
./build/agent/Release/banjo_quasistatic_probe.exe --cells 48 2 48 --drop 4.0 --ball-radius 0.10 --settle-max 10 --report rep48.json   # exits 2: active_set_failed
./build/agent/Release/banjo_quasistatic_probe.exe --cells 48 2 48 --drop 4.0 --ball-radius 0.10 --settle-max 0.01 --trace 2> trace48.txt   # the chattering contacts, verbatim

# Watch it: register a recording as a job in the owner's playground store
# (the server at 127.0.0.1:8765 runs from C:/Users/henry/dev/banjo and reads that
# store lazily, so no restart is needed), then open the printed URL.
python scripts/install_quasistatic_playback.py qs8.json  --report rep8.json  --runs C:/Users/henry/dev/banjo/build/playground-runs --name "Quasi-static lane: 8x8x2 glass tile (128 cells), iron ball 40 mm from 2 m, to rest"
python scripts/install_quasistatic_playback.py ref.json  --report report.json --runs C:/Users/henry/dev/banjo/build/playground-runs --name "Dynamic implicit reference (dt 1.25e-6 s, restart): same 8x8x2 scene, its own pieces settled in Jolt"
python scripts/install_quasistatic_playback.py qs24.json --report rep24.json --runs C:/Users/henry/dev/banjo/build/playground-runs --name "Quasi-static lane: 24x24x2 glass tile (1,152 cells), iron ball 60 mm from 3 m, to rest"
python scripts/install_quasistatic_playback.py qs32.json --report rep32.json --runs C:/Users/henry/dev/banjo/build/playground-runs --name "Quasi-static lane: 32x32x2 glass tile (2,048 cells), iron ball 80 mm from 3 m, 10 pieces, to rest"
# Or serve this worktree's own store on another port:
python playground/server.py --port 8790 --engine build/agent/Release/banjo_platform_cli.exe --studio build/agent/Release/banjo_network_lab.exe --runs build/playground-runs
```

The jobs installed in the owner's store on September 7, 2026, each opened in
the owner's playground and played to its last frame with no console errors:

| URL | Scene | Cells | Simulated | Wall | Ratio | What it shows |
|---|---|---|---|---|---|---|
| `http://127.0.0.1:8765/?job=73f331b1b4e34d8aa88578b3bdfcafbc` | quasi-static, 8x8x2 glass, 40 mm ball from 2 m | 128 | 2.49 s | 0.025 s | 0.010x | 156 bonds fail (red), the tile stays one piece, the ball rebounds and comes to rest on it |
| `http://127.0.0.1:8765/?job=a74cf2a71c8749e0a685eab6f82ac3fb` | dynamic reference, same scene, dt 1.25e-6 s | 128 | 6.64 s (cap) | 0.33 s | 0.050x | 704 bonds fail, 3 pieces, an 80 g chip falls through the frame, the ball rolls off and keeps rolling |
| `http://127.0.0.1:8765/?job=62a1c74327624f658b9e0920c939d63d` | quasi-static, 24x24x2 glass, 60 mm ball from 3 m | 1,152 | 10.78 s (cap; at rest by 6.76 s) | 1.35 s | 0.125x | 350 bonds fail, one 80 g chip, the ball rebounds 1.4 m, falls off the frame and spins in place on the floor |
| `http://127.0.0.1:8765/?job=5b132ccb059c468ea9ec41e0a4f9ff1d` | quasi-static, 32x32x2 glass, 80 mm ball from 3 m | 2,048 | 8.09 s | 3.00 s | 0.37x | 398 bonds fail, the tile plus nine 20-80 g chips, the ball rebounds at 6.3 m/s and ends on the floor |

`--trace` prints every solve, event, round, release, activation and freeze to
stderr; it is how every defect in this lane's history was found.

## Next

Ordered by what the measurements say:

1. **Do not pursue the quasi-static lane as the route to the shatter.** The
   answer is qualitatively wrong for ball-on-tile at these mass ratios, and no
   tolerance or preconditioner changes that. Its static solver, ledger, freeze
   rule and Jolt handoff are reusable: the modal lane could take the first
   bending failure and the piece-to-Jolt path from here.
2. **If the static picture is kept for anything, precondition it and give it
   a convergent contact solve.** An incomplete Cholesky or a Woodbury update
   of one factorisation per cascade would bring 3,200 cells with fracture
   inside 1.1x by the measured iteration counts (16.5 s of solves cut 3-10x
   against a 10.8 s interaction); 4,608 cells also needs the active-set
   chatter fixed, by a semi-smooth Newton or projected contact solve rather
   than by a wider knife-edge threshold, and a corotational re-linearisation
   per round so that a crater deeper than a cell is inside the model.
3. **The reference needs its own convergence before it can be a yardstick:**
   400-912 bonds across removal timings on one scene is not a spread, it is a
   choice. The removed energy is the only converged quantity to compare on.
4. **Contact.** Both lanes contact node points; a cell-face or Hertz-type
   contact on the lattice would change first failure in both and is the next
   physics both lanes share.
5. **Rolling and twist friction in Jolt**, or a rest criterion that ignores a
   sphere's spin about its contact normal, so that "to rest" is an event
   rather than a cap whenever the ball leaves the frame.
