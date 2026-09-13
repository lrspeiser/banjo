# The watershed: ground and water beyond the valley (terrain and water, milestone 2)

**Status.** W1, locality, is implemented and measured -- see
[terrain and water](terrain-and-water.md#only-what-changes-is-looked-at-milestone-2-w1).
Everything below W1 is **design**: nothing of it is built yet, and each part
moves to the development status only with its own tests, a 3D check in the
playground and green CI.

The owner's demonstration, which the whole milestone is measured against:
*dam a river, walk downstream into another region, see the flow change there,
and come back to find the reservoir behind the dam has gone on filling --
without the whole world being simulated at full detail.*

## The shape of it

A layer of **regions** sits above what exists -- `TerrainField`,
`TerrainGenerator`, `ShallowWater` and `WaterCoupling` stay as they are. The
first world is three regions: an **upstream basin**, the existing **valley**,
and a **downstream basin**. Every region is in one of three representations:

| representation | what it holds | what it costs |
|---|---|---|
| stored | its declaration and its last state, on disk or in memory | nothing |
| coarse | a river network: reaches, junctions and basins, each a handful of numbers | a few operations per coarse step |
| detailed | the ground (`TerrainField`), the water (`ShallowWater`) and the bodies, as the valley is today | what W1 made local |

**One owner per quantity.** At any moment each cubic metre of water belongs to
exactly one representation of exactly one region. Water crossing between
regions is a flux over a connection, computed once and applied to both sides
with opposite signs.

## Regions

A region has:
- a stable id;
- bounds, a rectangle in world metres;
- its declaration: the ground's generator, seed and generator version (as
  `terrain.generate` is today), and its rivers;
- every edit made to its ground since;
- its connections;
- its water state;
- its own clock and water ledger;
- the objects in it, kept compact while it is not detailed.

## Connections

A connection joins a span of one region's edge to a span of a neighbour's edge:
the same length, facing each other. What crosses it is decided by the water
on both sides -- the head difference -- so it can run either way: a flood can
back up into the region upstream, and a connection under water on both sides
carries what the levels say, not a fixed discharge. A prescribed discharge
(today's river source) and a free outfall (today's mouth) remain only for
sources and sinks that really are outside the world: the upstream basin's own
inflow and the downstream basin's own outlet.

## The coarse river network

- **Basins** hold water by a stage-storage curve: level from volume, taken
  from the region's own ground (the lake-at-rest level for that volume), so
  a coarse basin and the same basin in detail agree on its level.
- **Reaches** carry discharge driven by the difference in level along them,
  with bed resistance (Manning, as the detailed solver uses) and a declared
  limit of the flow regime they cover.
- **Junctions** join reaches and conserve what passes.

The coarse model runs on its own clock and keeps its own ledger. It is where
an off-screen reservoir goes on filling.

## Coarse and detailed together

- A connection between a detailed region and a coarse one is, to the
  detailed solver, a boundary face with a ghost column on the far side: the
  coarse side's level and its velocity along the face. The face's flux is the
  same Riemann flux every other face gets, so still water against still water
  at the same level is exactly zero, as a lake at rest is today.
- The detailed side accumulates what crosses each connection over its
  substeps; the coarse side takes that accumulated volume and momentum at its
  own step, with the opposite sign. Computed once, applied twice, never
  estimated twice.
- Ponds that are not connected stay distinct: a connection carries water
  only where its faces are wet.

## Transitions

- **Promotion.** A coarse region is made detailed from its declaration and its
  edits, and its water is laid out so that the detailed volume equals the
  coarse storage exactly -- basins by level over their own ground, rivers by
  the coarse reach's depth and discharge.
- **Demotion.** The detailed volume becomes the coarse storage, and nothing
  is rounded away.
- Both happen for physical reasons -- where the person is going, what is
  moving -- with hysteresis: a region is promoted nearer than it is demoted,
  so walking along a boundary does not flicker it. The transition's own
  residual is measured and has to be roundoff.

## Locality and instrumentation

W1 made the detailed region's bookkeeping follow change. The milestone adds:
- incremental activation, with no whole-world reopen as the way to stream;
- regional queries and regional drawing;
- compact inactive objects.

What is reported: resident regions, allocated and active cells, reaches
advanced, cells scanned outside active regions, dirty obstacle cells, collider
rebuilds, awake bodies, simulated time against wall time, latency p50, p95,
p99 and worst, transition time, and memory.

## Acceptance

1. The existing valley regression, unchanged.
2. A reservoir that spans two regions.
3. A region evolving while nobody is in it.
4. Transitions that conserve water to roundoff.
5. A lake at rest stays at rest across a connection.
6. A flood crossing a boundary, against the same flood all in detail.
7. Scaling to 10, then 100, stored regions.
8. Persistence: saved and reopened, every region goes on from where it was.
9. A step taken back leaves every region, and every connection's ledger,
   as it was.

Every layer carries it: engine, C API, Python, line protocol and MCP, and the
playground, where the chat asks the engine for real region state rather than
reading coordinates written into its guide.

## Increments

| | what | status |
|---|---|---|
| W1 | locality: tiles, obstacle tops and the ground and water sent follow change | done, `cc5d912` |
| W2 | the region layer: declarations, connections, stored state, a JSON round trip | next |
| W3 | the coarse river network | design |
| W4 | coarse-detailed coupling across connections, conservative | design |
| W5 | persistence, with the world snapshot (review item 3) | design |
| W6 | regional queries in the API, the MCP and the page; the chat asks for regions | design |
| W7 | the nine acceptance tests and the demonstration | design |

Out of scope for the milestone, by the owner's choice: sediment erosion, wet
soil, plants, weather, 3D splashes and wakes.
