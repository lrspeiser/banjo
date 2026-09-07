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

## Limits that stay stated throughout

- Uniform cells cap face:thickness at 16:1 (12:1 through the authoring routes).
  A windowpane is not expressible; tiles and blocks are.
- Piece counts are not converged on either lane; removed energy and largest
  piece mass are. The visual confirmations compare patterns, not integers.
- Admission is not calibration. Nothing here is compared to laboratory glass.
