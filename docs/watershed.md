# The watershed: ground and water beyond the valley (terrain and water, milestone 2)

**Status.** W1, locality, is implemented and measured -- see
[terrain and water](terrain-and-water.md#only-what-changes-is-looked-at-milestone-2-w1).
W2's first piece -- water crossing between regions by level -- and W3, the
coarse river network beyond the valley's source and mouth, are implemented and
measured, and the watershed room shows them -- see [Measured (W2)](#measured-w2)
and [Measured (W3)](#measured-w3). Everything else below is **design**: each
part moves to the development status only with its own tests, a 3D check in the
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

As built (W3, `water::RiverNetwork`):

- **Basins** hold water by a stage-storage curve: level from volume -- a
  flat-bottomed pool, a declared table, or the region's own ground
  (`StageStorage::fromGround`: what a lake at rest at a level holds over the
  cells it reaches from its seed, across saddles lower than the level), so a
  coarse basin and the same basin in detail agree on its level.
- **Reaches** are channels of declared width with a straight bed, cut into
  cells. Each face's discharge is driven by the fall of the surface across it
  against the bed's Manning friction -- the same law, and by default the same
  n, as the detailed water's -- in the local inertial form of Bates, Horritt &
  Fewtrell (2010). That form leaves out the advection of momentum, so it covers
  slow, deep, subcritical flow: a face inside a reach that would pass Froude 1
  is held there and counted, the declared limit of the regime it covers, and a
  reach's end falling freely into a node below it passes the critical
  discharge, as the detailed water's mouths do.
- **Junctions** join reaches and conserve what passes. Basins and junctions
  are the network's nodes, each with its own feed from beyond the world and
  outlet weir to it where declared.

The network runs on its own clock -- `advance` takes exactly the time asked, in
as many substeps as its stability limit needs -- and keeps its own ledger. It
is where an off-screen reservoir goes on filling.

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
| W3 | the coarse river network | built -- reaches, junctions and basins beyond the valley's source and mouth, in the watershed room and the MCP's `beyond_the_edges` |
| W4 | coarse-detailed coupling across connections, conservative; promotion and demotion | the coupling is built with W2 and W3; transitions are design |
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
far side with the opposite sign. A *basin* is a level pool -- level = bed +
volume / area -- fed from beyond the world and drained over an outlet weir to
beyond it; a scene's `water.watershed` declares basins and connections that
take over a river's source or mouth by name. Basins are stepped after accepted
steps only, with exactly what crossed. (Since W3 a basin is a node of the river
network, and a scene declaring basins this way reads as it did.)

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

**What W2 is not yet.** There is one detailed region; nobody walks into a basin
and finds it made detailed (W4, W5). The regions are the scene's water block,
not yet a region layer with its own stored state (the rest of W2, and W5 with
the world snapshot). A basin's level is held for a water stride (1/60 s); a
basin small enough to move by more than millimetres in one stride is outside
what this coupling covers.

## Measured (W3)

**What was built.** `water::RiverNetwork` (`src/water/RiverNetwork.hpp`): nodes
-- basins and junctions, each a stage-storage curve with an optional feed and
outlet weir -- and reaches between two nodes, or between a node and the
valley's edge. A reach's end at the edge is a connection: the valley's faces
there see the reach's end cell -- its level, and the speed its water moves
across -- and that cell takes exactly what crossed, once, with the opposite
sign. The network is stepped over each water stride after the step is
accepted. Still water is exact because the state is the level and a node's
level is worked out again only when its volume changes; mass is exact because
every face's discharge leaves one cell and enters the next, and a cell or node
asked for more than it holds gives what it holds, shared over the faces it is
losing water through. A scene declares it in `water.watershed` -- `basins`,
`junctions`, and `reaches` whose ends are nodes or `{"connection": a source or
mouth}` ([the C API](api/c-api.md)); the report's `watershed` block and the
state's `network` carry every node and every reach cell for cell.

| test | measured |
|---|---|
| still water | basins, a junction, reaches and a channel running up from the lake onto dry ground, all at one level: every level and discharge unchanged to the bit over an hour of 2 s steps and a minute of 1/60 s strides (`river_network_tests`) |
| a closed network rings down | a reservoir set 0.6 m above the rest: 4,913 m3 kept to 5e-11 m3, the reservoir averaging the one level that holds it all, 1.08316 m, over the sixth hour, and its energy above that level -- the most in each hour -- 608 kJ at the start, then 64, 20, 10, 6 and 4 J: rubbed away by the bed alone, whose friction weakens as the square of the speed |
| Manning's law | a 2 km reach fed 0.6 m3/s settles to Manning's normal depth, 0.2521 m, to 2e-7 over its middle third and passes the discharge to 1e-10; its middle runs at Froude 0.38, and it falls freely into the pool below it at critical depth, 0.1319 m |
| either way | two ponds 5 cm apart: 0.86 m3/s down the cut between them, and 0.17 m3/s back up it once the lower is raised 5 cm above the upper |
| a junction | two springs of 0.3 and 0.1 m3/s: 0.4 m3/s into the confluence and out of it, 0.4 down the river below, 0.397 over the lake's outlet |
| a flood front | a dry reach wetting from a reservoir: the front 5, 9, 11, 14, 16, 18, 20 and 20 cells down it at 30 s intervals, no cell below its bed, nothing put back |
| a basin's own ground | the stage-storage of ground with two hollows holds what the detailed water holds there as a lake at rest, to 1e-9 at every level, and waits at the saddle, 0.315 m, while 29.6 m3 fill the hollow beyond |
| a torrent | a 1-in-10 chute passing 1 m3/s is held to Froude 1, and the holds are counted |
| carried | a network's state taken and given back goes on to the bit |
| coupled | a detailed channel between two reaches: 0.82 m3/s into it and out of it after five minutes, and the reservoir, the reaches, the channel and the basin on one account to 2.4e-11 m3, what crossed in both ledgers with opposite signs |
| through the C API | the channel fed down a reach from a reservoir and pouring down another into a lake: one account to 1e-9 of what is held, and a world opened again from the state with every reach cell for cell and every basin where it was (`environment_ffi_tests`) |
| the room in the runner | the watershed room through the live pipe: the network drawn as declared, the river coming down into the valley and on down the reach below, the brook into the confluence, all of it unaccounted by less than a millilitre (`world_room_tests`) |
| the MCP | `make_terrain(beyond_the_edges)` stands the same network for a valley from its own report; `water_state` says what each river carries; `set_river` feeds the reservoir and, by its name, the spring (`banjo_mcp_tests`) |

Found on the way: de Almeida et al.'s blend of a face's discharge with its
neighbours', meant to damp oscillation from cell to cell, is not safe where a
reach runs from deep water into shallow -- it moves discharge towards the
shallow end, where a cubic metre a second carries more energy. With a face's
own value standing in for a dry neighbour it pumped a seiche in a reach running
up from the lake onto dry ground: 235 J standing in it, its shore cell rising
and falling 6.6 cm every 80 s, never dying down. The energy above the rest
level, hour by hour and part by part, found it. The network runs Bates et al.'s
scheme as it is; the blend remains a setting, in its proper form -- a dry face
lends its nothing, as a wall does, and the blend is a rate, not a share of each
substep, so a host stepping the network a sixtieth of a second at a time does
not damp it a hundred times harder.

**In the page** (port 8772, headless Chrome, a server started fresh). The
watershed room -- now *A valley within a river network* -- opened with the water
panel naming the reservoir (0.850 m, fed 0.35 m3/s), the spring, the lake
(-0.248 m) and the confluence, and what each river carries where it starts, in
its middle and where it ends; every basin's sheet and every reach's cells were
drawn at exactly the levels the engine reported (the largest difference 0.0 m).
Thirty seconds on, 0.455 m3/s was coming down the reach into the valley and
0.369 leaving down the reach below, the brook bringing 0.13 and 0.42 going on
to the lake; the reservoir was falling, 0.850 -> 0.843 m -- it started above
the level that passes its own 0.35 m3/s -- and the lake rising, -0.248 ->
-0.233 m; all the water unaccounted by 8.4e-12 m3. The room kept 29.92 s of its
clock in 30.00 s of wall clock.

Then the room's chat was asked to *dam the river with stone blocks so the water
backs up behind them*, and in 38 s set nine concrete blocks across it at
x 0.64. A minute later 0.248 m3/s was coming down into the valley against
0.453 before -- the reservoir, fed 0.35, now giving 0.25, so filling again --
0.203 was leaving down the reach below against 0.374, and 0.369 going on to the
lake against 0.436; all the water unaccounted by 4.0e-11 m3.

**What W3 is not yet.** The regions beyond the edges hold only the network: no
ground is drawn there, and nobody walks out along a reach and finds it made
detailed (W4). A reach is a straight-bedded channel of one width, with no
floodplain beside it. The network is part of the scene's water block, not yet
regions with their own stored state (the rest of W2, and W5).
