# G10: Interactions at realtime, watched in 3D

Owner's rule, adopted as a hard gate: **no job may take more than 1.1x the
simulated duration of the whole interaction, including settling to rest.** The
playground refuses anything projected over that before it runs.

Owner's standard, adopted as the definition of done: **a stage is not done until
it can be loaded into the Banjo playground, run on the real engine, and watched
in 3D.** Measurements, validations and scratch experiments do not count.

Each stage below names the scene, the visual confirmation, and the realtime gate.
Stages are cumulative; none is skipped.

## Stage A -- the rule is enforced, and the simplest interaction is watchable

Scene: a rigid iron ball dropped onto a rigid glass plate lying on the ground.
It bounces, rolls, and comes to rest.

Visual confirmation: in the 3D playback tab, the ball falls, strikes, bounces,
and is at rest by the end of the recording. Nothing passes through anything.

Realtime gate: wall time <= 1.1x simulated time, reported on the case card.
Any request projected over 1.1x is refused before running, with the projected
ratio and the nearest change that would pass.

What this proves: the pipeline from authored package to 3D playback works at
realtime for rigid bodies, and the rule is real.

Evidence, 2026-09-07: job `bcfc001ce3fd4ac998af5858d882e3c0` (`http://127.0.0.1:8765/?job=bcfc001ce3fd4ac998af5858d882e3c0`). 0.053 s wall
for 3.0 s simulated, 0.018x. Iron ball, 0.39 m drop: 7 bounces, first rebound
0.523x the drop height (e = 0.723, model 0.715), at rest on the plate from 1.35 s,
0.000 mm of movement in the final 0.25 s, 0.00 mm penetration, plate displacement
and tilt 0. The viewer's own scene graph places the ball at (0, 0.45, 0) at frame
0 and (0, 0.06, 0) -- plate top plus radius -- at 1.35 s and 3.0 s. The realtime
gate refused a 200-cell tile at 11,154x before any job existed. Status: ready for
the owner to watch; not marked done until watched. Reaching this exposed that
every contact in the network lane had restitution 1.0; see
docs/rigid-contact-restitution-checkpoint.md.

## Stage B -- a glass tile flexes under the ball, elastically, at realtime

Scene: the same ball onto an edge-clamped uniform-cube glass tile that bends
but does not break (fracture disabled), on the implicit Newton/GMRES lane, up
to 365 nodes.

Visual confirmation: the tile visibly deflects under the ball and springs back;
the deflection is largest at the strike point and zero at the clamped edges.

Realtime gate: <= 1.1x. The implicit lane measured 1.00-1.03x at 365 nodes and
1/120 s, so this is reachable with the existing solver once its output reaches
the 3D viewer, which it does not today.

What this proves: the fast lane is wired to the playground.

## Stage C -- the same flex from a basis computed once, faster

Scene: identical to B, but the elastic response is evaluated from the object's
eigenbasis, computed in the engine when the object is created, instead of by
stepping.

Visual confirmation: side-by-side or toggled playback of B and C is visually
identical; a difference view shows nothing. The case card shows the wall time
of each.

Realtime gate: C is measurably faster than B and stays under 1.1x.

What this proves: the precomputed-basis mechanism exists in the engine and is
exact for the intact body, which the scratch experiment showed but the engine
did not have.

## Stage D -- the first crack, from the basis

Scene: as C, with the failure criterion enabled, stopping at the first set of
bonds to fail.

Visual confirmation: the first crack set appears at the strike point in 3D, and
it is the same set the stepped solver produces on the same scene, shown side by
side.

Realtime gate: <= 1.1x for the run up to first failure.

What this proves: strain from the basis feeds the same failure criterion both
lanes already share.

## Stage E -- the full shatter, from basis updates (the research gate)

Scene: as D, continuing through the cascade. After each round of failures the
basis is updated for the changed topology rather than recomputed.

Visual confirmation: the tile shatters into separate pieces in 3D, and on a
small tile the piece pattern matches the stepped solver's within the spread the
stepped solver itself shows under refinement.

Realtime gate: <= 1.1x for impact through end of fracture.

What this proves: the cascade -- measured at 61 rounds -- can be carried by
basis updates. This is the stage that may fail. If low-rank updates lose
accuracy across the cascade, the honest outcome is to report where they lose it
and stop, not to widen a tolerance.

## Stage F -- pieces fall and come to rest

Scene: as E, run through to rest. Fragments contact each other and the ground.

Visual confirmation: pieces separate, fall, collide, and stop. Nothing
interpenetrates. The recording ends with everything at rest.

Realtime gate: <= 1.1x for the entire interaction, impact through rest. This is
the owner's rule in full.

## Stage G -- the owner changes the request and the result changes correctly

Scene: the Builder varies thickness, cube size, impact speed and material.

Visual confirmation: thicker tiles crack less; faster balls break more; oak and
iron respond differently from glass; every change is visible in 3D and every
run passes the realtime gate or is refused before it starts.

What this proves: the physics is authorable and the answers track the inputs.

## Evidence from the three parallel lanes, 2026-09-07

Three agents built fracture three different ways in their own worktrees. Two
delivered recordings that load in this playground; the primary verified each
job below through `/api/jobs` (full playback frames) and on its case card
(Realtime row, and the fracture-window row where the lane reports one). The
owner has watched none of them yet, so nothing below is marked done.

**Modal basis** (`agent/fast-modal`, `c73ce15`, `docs/fast-modal-checkpoint.md`).
Rule met on the smallest honest scene and not on the next size up. Clamped
8x8x2 glass tile (128 cells, 20 mm), 20 mm iron ball at 16 m/s, impact through
fracture, hand-off to Jolt and settling: 1.120 s wall for 8.002 s simulated,
**0.14x**, 35 fragments through the hole
(`http://127.0.0.1:8765/?job=65331afc7b2f47f791799e70ed699c97`, case 1; case 2
is the implicit reference on the same scene at 0.12x). It passes because the
2 ms fracture window -- itself **497x** slower than realtime -- sits inside
8 s of rigid settling that Jolt computes at 0.01-0.03x. On 12x12x2 at 20 m/s
the exact rank-one eigenvector update (O(n k^2) per broken bond) takes 13.8 s
of a 15.3 s window and the interaction runs at **1.94x**, rule failed
(`http://127.0.0.1:8765/?job=9afe5fe6e9624dfda6c21d1b51f263cb`). Truncating the
basis loses the cascade, so the obstacle is a sub-O(n^2) update, not tuning.
First-failure set identical to the reference on every scene tested.

**Quasi-static** (`agent/fast-quasistatic`, `c272499`,
`docs/fast-quasistatic-checkpoint.md`). Rule met through to rest up to
2,048 cells: 32x32x2 tile, 80 mm ball from 3 m, 3.000 s wall for 8.095 s,
**0.37x**, tile plus nine chips
(`http://127.0.0.1:8765/?job=5b132ccb059c468ea9ec41e0a4f9ff1d`); 24x24x2 at
0.125x (`?job=62a1c74327624f658b9e0920c939d63d`); 8x8x2 at 0.010x
(`?job=73f331b1b4e34d8aa88578b3bdfcafbc`, with the dynamic reference at 0.050x
in `?job=a74cf2a71c8749e0a685eab6f82ac3fb`). Fails at 3,200 cells (1.56x),
cost about N^2.3. The caveat is the physics: the quasi-static answer craters
the tile and stops the ball where the dynamic reference shatters it (8x8x2:
156 bonds and one piece against 400-912 bonds and 2-30 pieces; first-failure
sets disjoint; only removed energy agrees, within 11-29%). It meets the rule
without reproducing the dynamic outcome.

**GPU lattice** (`agent/fast-gpu`, `7d07996`, `docs/fast-gpu-checkpoint.md`).
The CPU lane's physics and the shared criterion, bit for bit, on a
colour-parallel schedule with a CUDA backend (`BANJO_BUILD_CUDA`, default off;
equality proven against the CPU backend and against `BrittleBondSolver`).
Rule met with the fracture window itself resolved: a 192-cell glass tile
(20 mm cells, 1,704 bonds) on two ledges, 4 cm iron ball at 8 m/s, 7,288
substeps at 1.59 us through fracture, hand-off and settling, 0.377 s wall for
1.895 s, **0.20x**, 3 pieces
(`http://127.0.0.1:8765/?job=08678486c9aa43949b5a0ec7b00fafb8`; case 2 is the
same tile at 12 m/s, 59 pieces, 0.57x). Holds to 384 cells (0.71x), fails at
800 (1.50x) and by about 7x at 1,536 cells of glass, where the cascade fills
the whole 200 ms lattice window; oak and iron at 1,536 cells pass (0.76x,
0.59x) because their cascades end within 15-21 ms
(`?job=34c2b8108580425fbaefbd407ddf0279`). The GPU is no faster than one CPU
thread at 192 cells (55 M bond-updates/s against 57-68 M) and reaches 616 M at
173k bonds, five times short of the ~3e9 estimated: one substep is a chain of
22-32 barrier-separated colour stages costing 25-35 us regardless of bond
count, while it advances 0.3-1.6 us of simulated time. This is the only lane
where the window is computed rather than amortised and the rule still holds;
its outcome is not converged with respect to sweep order, precision or cell
size.

What this does to the stages: D, E and F have recordings (modal on 8x8x2;
quasi-static to 2,048 cells; GPU lattice on 192-384 cells with the window
resolved) and are ready for the owner to watch. B and C have
no elastic-only recording of their own, though the modal checkpoint shows the
basis exact through the cascade. G is untouched: both lanes are command-line
tools with recording importers, not Builder routes, and the Builder still
drives only the network lane.

## Limits that stay stated throughout

- Uniform cells cap face:thickness at 16:1 (12:1 through the authoring routes).
  A windowpane is not expressible; tiles and blocks are.
- Piece counts are not converged on either lane; removed energy and largest
  piece mass are. The visual confirmations compare patterns, not integers.
- Admission is not calibration. Nothing here is compared to laboratory glass.
