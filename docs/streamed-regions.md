# The ground beyond the valley: regions streamed in as you walk

**Status, October 4 (branch `agent/stream-regions`).** The first working
increment of the owner's choice of 2026-10-04 -- *the map grows by streaming
new regions as the player nears the edge* -- is built and measured. It is the
ground half of [the watershed's](watershed.md) promotion idea: a region beyond
the valley becomes real ground when somebody comes near it. Water out there,
and putting a region away again, are the next increments (the end of this note).

## What a player sees

You walk (or fly, in God mode) toward the edge of the valley. When you are
within **10 m** of an edge, a new stretch of ground the size of the valley
(39 x 31 m) appears beyond it, already joined on. You walk straight across the
join without noticing it, and you can dig there like anywhere else. Keep going
and the next one appears. Leave the world and come back: everything you grew,
and every hole you dug in it, is still there.

## How a region is made

**One rule for all the ground outside the valley.** The height of the ground at
any point outside the valley is worked out from that point's world position and
the world's seed alone:

- *Hills*: the valley's own noise (the same noise its slopes are made of),
  plus a broader swell, taken at world coordinates -- so two regions side by
  side compute the same hills where they meet, and the floor keeps falling
  1.2 % eastward as the valley's does.
- *A blend band*: within 10 m of the valley, the ground is eased from the
  valley's own **generated** edge (before anyone dug it) into the hills. At the
  seam the region starts exactly where the valley stops; 10 m out it is all
  hills. The edge is also softened sideways the further out you go, so the
  river's channel and a strip of sand fade out instead of running on as a
  straight furrow.
- Soil is thinned on steep ground as the valley's is; near the valley the
  valley's own soil and sand are carried out. The rock has the valley's
  weathered mantle and its clay bed, continued from the valley's west edge.

Because the rule is one function of position, a region is the same whichever
order the regions were made in (checked to the bit), and a region never needs
its neighbour to exist.

**Tiling.** Regions sit on a lattice of valley-sized cells; the valley is
(0, 0). Their columns tile the valley's: region (1, 0) starts one 25 cm column
past the valley's last one, so every column in the world belongs to exactly
one region. A column at a region's edge finds its neighbour in the region
beside it, so the physics walls at a seam are exactly the walls one big map
would have had there.

**The river.** In this increment the river still leaves the valley at its
mouth as before; outside, its channel shows as a dry dip that fades away. The
design for later: the river crosses each region boundary at a **fixed crossing
point**, worked out from the seed and the boundary alone (like the hills), so a
region can carve its stretch of river from where it enters to where it leaves
without knowing its neighbours -- and the coarse river network
([watershed W3](watershed.md#measured-w3)) already carries water out there.

## When it becomes real ("detailed")

Before every step the engine looks where each player's body is, and where the
page's camera is. If that spot is on ground and within 10 m of a region that
does not exist yet, that region is made -- between steps, never inside one.
Its ground is made at once (about 17 ms); its colliders come in a few per
step, nearest to you first (3 ms a step), and are all there within about a
tenth of a second of game time, long before anyone 10 m away reaches them.

A region is real ground in every way the valley is: one collider per 31 x 31
chunk, digging and heaping, a swung pick (it went 124 mm into a region's soil
and, pried, broke 6 L out, carried and taken off the region's ledger), rock
broken out, banks slumping, the survey and the ground sensors. It has no water
of its own (see below). At most
48 regions, and at most 6 out from the valley each way.

The page draws each region as its own pieces -- one mesh for its column tops
and its cut faces in 32-column chunks -- so a region arriving redraws nothing
already drawn, and a dig out there redraws only the columns it changed.

## How it is saved

- The room's spec lists the regions grown so far (`terrain.regions`), beside
  its digs. A world reopened from its spec makes them again from the seed.
- The saved world keeps each region as **where it is, plus only the 31 x 31
  chunks that have been changed**. A region nobody has touched is 26 bytes; a
  region with a 2 m trench in it keeps one chunk, 124 KB. Everything else is
  made again from the seed.
- The world is saved as soon as it grows.

## What it costs (measured)

`tests/streamed_regions_tests.cpp`, Release, this machine, the walker world:

| | |
|---|---|
| making one region's ground | 16-20 ms |
| its colliders, all 20 chunks | 70-100 ms in all, given 3-5 ms a step over the next 23 steps (0.1 s of game time) |
| the step that grows it | 20-21 ms, once; no later step over 6.4 ms |
| a step with 0 / 1 / 4 / 9 regions | 0.142 / 0.142 / 0.143 / 0.158 ms: still ground costs nothing a step |
| opening a world with 0 / 1 / 4 / 9 regions | 0.09 / 0.18 / 0.44 / 0.92 s |
| saved world | +26 bytes a region untouched; +124 KB a changed chunk |
| the ground sent to a page whole | 636 KB valley, +553 KB a region (5.5 MB with 9) |
| memory | 4.4 MB a region (the engine's private memory 110 MB with none, 149 MB with 9) |

The whole-ground message is the cost that grows: today every change to the
ground sends a page that missed it the whole ground again, all regions
included.

## Not yet (the next increments)

1. **Water out there.** Regions are dry. Next: each region's own shallow water,
   joined to its neighbours' by the connections the watershed already has, and
   the river carved through fixed crossing points.
2. **Putting regions away.** Regions are never unloaded; next is demotion:
   far-away regions keep only their saved state and their colliders are
   removed, with the hysteresis the watershed design describes.
3. **Sending less.** A page should be sent only the regions that changed, not
   the whole ground.
4. **Slumping across a seam.** A bank at a seam settles on its own side only.
5. **Smooth and sharp-cut ground.** Only the 25 cm column ground grows: the
   smooth surface would leave a gap a cell wide at each seam. Those worlds
   refuse to stream and say why.
6. **The in-process engine lane** (`--live-inprocess`, off by default) loads
   regions but does not grow them.
