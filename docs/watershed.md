# The watershed: ground and water beyond the valley (terrain and water, milestone 2)

**Status.** W1, locality, is implemented and measured -- see
[terrain and water](terrain-and-water.md#only-what-changes-is-looked-at-milestone-2-w1).
W2's first piece is implemented and measured: water crossing between regions
by level (connections), level-pool basins beyond the valley's source and
mouth, and the watershed room -- see [Measured](#measured-w2). Everything else
below is **design**: each part moves to the development status only with its
own tests, a 3D check in the playground and green CI.

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
| W2 | water crossing between regions by level; level-pool basins beyond the valley's source and mouth; the watershed room, the MCP's `beyond_the_edges` | built -- the rest of the region layer (declarations of whole regions, stored state, a JSON round trip) is next |
| W3 | the coarse river network | design |
| W4 | coarse-detailed coupling across connections, conservative | design |
| W5 | persistence, with the world snapshot (review item 3) | design |
| W6 | regional queries in the API, the MCP and the page; the chat asks for regions | design |
| W7 | the nine acceptance tests and the demonstration | design |

Out of scope for the milestone, by the owner's choice: sediment erosion, wet
soil, plants, weather, 3D splashes and wakes.

## Measured (W2)

**What was built.** A *connection* is part of a region's edge whose far side is
another region's water (`water::ShallowWater::addConnection`): each face there
gets the same Riemann flux as any face, against a column standing to the far
side's surface over the near column's own bed, so the same level on both sides
is exactly no flux. What crossed is counted once per substep and handed to the
far side with the opposite sign. A *basin* (`terrain::Environment::Basin`) is a
level pool -- level = bed + volume / area -- fed from beyond the world and
drained over an outlet weir to beyond it; a scene's `water.watershed`
declares basins and connections that take over a river's source or mouth by
name. Basins are stepped after accepted steps only, with exactly what crossed.
The watershed room declares the valley this way; `make_terrain`'s
`beyond_the_edges` does it for any valley or channel from its own report.

| test | measured |
|---|---|
| still water across a connection | the same level both sides: every surface and discharge unchanged to the bit over 100 strides, nothing crossed (`water_tests`) |
| either way by level | a far side 0.1 m higher sent 0.253 m3 in over 1 s; one 0.2 m lower took 0.415 m3 out; the water's ledger residual 0 m3 (`water_tests`) |
| a reservoir and a channel keep their water | a reservoir draining into a channel over a minute, 1.300 -> 1.205 m: their total 16 m3 before and after, to rounding (`water_tests`) |
| a dam fills the reservoir | two rivers the same to the bit until a dam goes into one; two minutes later the reservoir behind the dam stands at 1.378 m against 1.311 m without it, and 0.050 m3/s crosses against 0.111 (`water_tests`) |
| one account, and a reopen | the channel fed from a reservoir and pouring into a basin with an outlet: every cubic metre on one account to 1e-9 of what is held; reopened from its state, the basins and the channel's water the same to the bit; an earth bank across the channel makes the reservoir stand higher than without it, with less crossing (`environment_ffi_tests`) |
| the room in the runner | the watershed room opened through the live pipe: the reservoir feeds the river, the river pours into the basin, all the water unaccounted by less than a millilitre (`world_room_tests`) |
| the MCP | `make_terrain(beyond_the_edges)`: the reservoir sends water into the valley and the basin takes it, one account, `set_river` sets the reservoir's feed, and a basin kind is refused before the ground is touched (`banjo_mcp_tests`) |

**In the page** (port 8772, headless Chrome). The watershed room opened with
the water panel reading *29.08 m3 standing in the valley* and *the upstream
reservoir: 0.801 m, 240.2 m3, fed 0.35 m3/s, into the valley 0.27 m3/s -- the
downstream basin: 0.002 m, 361.0 m3, from the valley 0.35 m3/s*, and the two
sheets of water drawn 7 m out from the west and east edges at 0.8006 and
0.0016 m. Thirty seconds on the reservoir stood at 0.8061 m -- 2.20 m3 more,
the 0.35 m3/s it is fed less the 0.28 it sent -- and the basin at 0.0188 m,
taking 0.32 m3/s, not yet up to its 0.05 m outlet; all the water together
unaccounted by -1.1e-11 m3. The room kept 30.06 s of its clock in 30.00 s of
wall clock.

Then the room's chat was asked to *dam the river with stone blocks so the water
backs up behind them*. In 26 s it set nine concrete blocks, 0.32 x 0.48 x
0.48 m, across the river near x 0.62, and the room was opened again with them
-- the reservoir and the basin carried across as they stood: 242.6 m3 in the
reservoir before, going on from there rather than back to the 240.2 m3 it was
declared with. A minute later 0.221 m3/s was crossing from the reservoir,
against 0.285 before the dam, so it was filling faster (0.807 -> 0.824 m); the
basin downstream was taking 0.140 m3/s against 0.319, and had just reached its
outlet (0.052 m, 0.6 litres a second over the weir); all the water together
unaccounted by 3.9e-11 m3. The reservoir was filling before the dam too -- it
is fed 0.35 m3/s and started below the level that passes that -- so the dam's
own share is what the two rivers the same but for the dam measure: 67 mm.

**What W2 is not yet.** The basins are level pools: no coarse river network
(reaches, junctions) beyond them (W3). There is one detailed region; nobody
walks into a basin and finds it made detailed (W4, W5). The regions are the
scene's water block, not yet a region layer with its own stored state (the
rest of W2, and W5 with the world snapshot). A basin's level is held for a
water stride (1/60 s); a basin small enough to move by more than millimetres
in one stride is outside what this coupling covers.
