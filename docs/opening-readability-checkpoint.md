# Opening, readability and recipe audit — October 3, 2026

Branch `agent/opening`, based on main `68bad3ca`. Windows 11, MSVC Release,
Intel Core Ultra 9 285K, RTX 5090, Chrome headless. This checkpoint works
through the first items of the owner's October 3 list. It does not finish
that list; what is left is at the end.

## What a player sees now

**Recipes reads as one list of things to make.** The screen has four groups:
*Useful now* (you can make it), *Next projects* (you are short of supplies),
*Construction*, and *Experimental designs* (the shape cannot be made yet, such
as the catalog chair, shelf unit, cart and kettle). A disabled Make no longer
sits next to the starter recipes. Each starter shows one recommended version;
the catalog version it stands in for (Field Pick, Stool, Table, the yard Solar
Array, the Mine Lamp) is under *Other versions* on that card. A link that
names one of those versions opens it.

**One status in one set of words.** Each card says *Ready to make*,
*Ready · uses shared stock*, *Needs supplies* or *Design needs changes*. The
second one fixes the mismatch the realism review found: the field pick said
"Materials 100%" while the guide said "Get wood for your tool", because Make
counted shared stock and the goal wanted your own wood. Stock is labelled
*Yours* and *Shared* everywhere it appears (Recipes, Inventory tiles, Market,
the World storage rows), instead of a mix of Personal, Stored and Shared.

**Badges say what a thing can do.** *Can do* badges are read from the
design's own machine declaration and use: Light (5 W lamp), Battery (Wh),
Solar power, Motor, Heat, Drives, Flies, Digs, Hauls, Processes, Gathers,
Seat, Surface, Storage, Wheels, Foundation. A part that looks like a panel or
lamp with nothing declared behind it gets a *Shape only* badge. The generic
"Carry / Place" pair is gone. Badges remain declarations; making and using
the thing is the test.

**A small solar panel before the yard array.** *Camp solar panel* is a
one-panel version of the solar array: 0.6 × 0.4 m of glass at 20% (about 48 W
in full sun), a 50 Wh battery rated at 60 W, starting empty. Geometry, area,
capacity and rating are all reduced together, so it asks for 1.8 kg of copper
and 0.12 kg of wire, not the array's 200 kg. It is the same solar law and banks
its surplus the same way. Test:
`fabrication_remake_tests ... test_camp_solar_panel_is_a_paid_starter_that_charges_and_banks`
makes it through the paid workbench and checks that it gains charge in sun,
and never more than the sunlight on 0.24 m² for that time.

**Night can be read.** At night the World was close to black: only the
river's sparkle and a lamp showed. A dim, cool moonlight now fades in as the
sun sets, and the night sky's light is about a quarter of the day's. Sand,
soil, the cut banks and the water stay distinct; the camp lamp still visibly
lights its area. This is presentation only: panels charge from the engine's
sun as before. The light's guide no longer says *Switch light on* once the
light is on.

**More than one player can find wood.** A click collects a whole pile (the
owner's rule from the automatic-excavation-piles checkpoint), so a world's
single 200 kg oak heap went entirely to the first player, and the second was
sent to the Market. The same finite timber is now laid as up to four piles.
The first is placed as before; the rest are placed last, nearest the start,
so a seeded map's veins and machine yards do not move. Across 40 seeds per
valley, playability, seams, deposits and machine yards are unchanged from
main; terrain 7 gets 2–4 timber piles on 36 of 40 maps, and terrain 4 gets 2–4
on 28 of 40 (the rest keep one).

**Things set down by the workbench stay standing, or the spot is refused.**
Two fixes, both in the precise-rigid install preview:

1. A product is now turned square to the plane it rests on (three ground
   samples under its footprint, none above, lowest under its centre of mass)
   and seated 2 mm clear of it. Before, it was set exactly upright on the
   highest ground point under it.
2. The preview then lets it stand for 2 s in the private staged copy of the
   world. If it tips more than 10°, the spot is refused: "It would not stand
   here: it tipped N degrees in its first 2 s. Choose flatter ground."

Measured on the valley: a paid work table on an 8° patch fell on its side in
1.2 s, squared or not. A camp stool on a 7.5° patch tipped 26°. On flat
patches both stood (0.0–0.6° of change). The engine decides; nothing here
estimates stability. The AI player now tries 24 spots (three distances in
eight directions) instead of 6.

## Ground: smooth, 25 cm cells and 12.5 cm cells

A new game can now choose **Material cells · 12.5 cm · preview**. It is the
same valley at the same 39 × 31 m extent with twice the cells each way. New
worlds can also be replayed exactly from given seeds
(`POST /api/worlds {"seeds": {"terrain": 4|7, "goods": n}}`), so the three
ground types can be compared on one map.

`tools/terrain_compare.py` measures all three on terrain 4, goods seed
851269742, in headless Chrome at 1280 × 800:

| | Smooth | 25 cm cells | 12.5 cm cells |
|---|---|---|---|
| Native step, bare valley (ms per 1/120 s) | 0.21 | 0.19 | 0.70 |
| Valley generation, uncached (s) | — | — | 9.8 |
| Page ready (s) | 2.4 | 2.5 | 3.4 |
| Triangles drawn | 120 k | 213 k | 721 k |
| Draw calls | 38 | 56 | 98 |
| JS heap (MB) | 16 | 45 | 104 |
| Downloaded (MB) | 10.3 | 10.1 | 14.3 |
| Frame time p95 (ms, RTX 5090) | 16.8 | 16.8 | 16.8 |
| Saved world (MB) | 3.6 | 3.6 | 13.6 |
| Page ground vs native survey, 200 points, max (µm) | 0.20 | 0.23 | 0.24 |

On this machine all three hold the 60 Hz frame cap, so frame time does not
separate them. The costs that do are triangles (6× smooth), heap (7×), save
size (3.8×) and step time (3.4×) for 12.5 cm. The page and the engine agree
on the ground to a fraction of a micrometre in every mode. Day screenshots:
both cell sizes read as distinct materials with visible layered banks, and
12.5 cm looks smoother at the cost above. Screenshots are written to
`build/terrain-compare/` (ignored).

This measures. It does not show that people can name the materials; that is
the human test still to run. Smooth remains the default.

## Can every recipe really be made

`playground/recipe_audit.py` asks five questions of every recipe in the
book, including saved and AI-made designs:

- **shape:** it compiles as drawn;
- **supply:** every material has a non-Market source in this world, and every
  process on the way is reachable;
- **power:** each of those processes runs on a machine with a charged battery
  or a panel;
- **use:** it declares something it does;
- **recovery:** a run-out source has another.

It reads the same source routes the Recipes screen shows.

The audit's first run found that Recipes said *no source of glass except the
Market* on both valleys, although the opening has players melt sand into
glass. Recipes only counted machines already running a recipe, while the
furnace can be switched to Melt Glass. Machines that can run a recipe now
count, and the card says *Select Melt Glass on it · supply its hopper · turn
on*.

`tests/recipe_audit_tests.py` now holds every starter (Personal field pick,
Camp stool, Work table, Camp light, Camp solar panel) to all five questions on
both valleys, and they pass. The full book is written to
`build/recipe-audit/terrain-<n>.json`. Catalog recipes that still fail:

- **shape:** the chair, shelf unit and kettle have parts thinner than the
  40 mm Workshop cell that are redrawn away from what they join; the cart
  needs a native adapter for mixed materials on an articulated axle. All four
  are under *Experimental designs*.
- **recovery:** the electric furnace's alumina ceramic and the foundation pad's
  concrete each have one finite source and no Market lot.

## Two known failures

**Strike and reuse** (`test_failed_connection_paid_mixed_replacement_retains_original_and_works`)
failed 4 times in 5 on main; it is not R3 work. Three causes were found:

- The tool turned toward its ready pose beside the target and swept the head
  through it, so the strike was spent before it began.
- It waited a wall-clock 2 s for the tool to settle while the world is stepped
  separately, so a loaded machine ran out of time.
- It pressed while the tool was still moving.

The tool now turns at a 0.3 m standoff behind the ready pose, waits there
until it points along the strike line, comes straight in, waits in *world*
time, and presses from rest. A slow press that shears the target's fixing
below the impact-event speed is counted as a strike. The test now passes
8 of 8 runs under load. No law, tolerance or engine behaviour changed.

**The composed camp/table journey** (`goal_chains_tests`) had gone stale on
main in several places: it used the retired free preview, it assumed 25 kg
collects, and it assumed one second of charging. It now:

- collects its own wood;
- makes the table through the paid workbench, waiting as long as the energy
  needs at the connected power;
- picks a spot the table will stand on;
- retries an expired placement preview as the page does.

The last red step was the stool going onto the light table: carried in at the
whole path's 0.8 m/s, it landed hard enough to shove the table, and every
put-down was refused with "the destination moved". A put-down now does its
last 4 cm at 0.12 m/s or less, as a hand sets a thing down. The composed
journey passes on both valleys, and so does the two-player personal-tool
journey in the same file.

## Main's test suites are red

Found while baselining. Each failure was reproduced on untouched main
`68bad3ca` with the same engine build, so none comes from this branch:

- `workshop_navigation_tests.py`: 8 of 15 fail;
- `workshop_browser_tests.py`: 15 failures and 1 error out of 56;
- `workshop_install_engine_tests ... test_physical_curve_and_requested_position_use_whole_grid_translation`;
- `starter_goals_tests ... test_browser_completes_goals_in_market_recipes_and_world`.

Repair of the two browser files is in progress on separate branches.

## Since then, on the same branch

**The opening has a light and a sun goal.** Chapter two keeps only *Learn from
a working machine*; the work table stays in Recipes as something you may make.
A new chapter, *Light and power your camp*, asks for:

- your own light, lit from its own battery: the engine has counted energy its
  lamp drew;
- your own solar panel, charged by sunlight: its battery has received energy.

Both are judged from the saved world and never awarded. Guidance offers the
Camp light and the Camp solar panel when each is next.

**Ore is delivered by mining it.** When a batch is short of an ore that lies in
a seam, and the rover already knows that seam and the furnace intake, guidance
offers the plain order a person could type: "dig at vein and dump it at smelter
intake". It then waits while the ore is delivered. The AI player carries out
both steps. `tests/rover_order_tests.py` checks that ore arrives in the intake
from the seam, by the rover's own dig and dump.

**The rover on harder ground.** `tests/rover_route_tests.py` gives it ordinary
orders on both valleys: a trench across its haul, a second haul, a call to the
river's edge, a call up the steepest slope, then "go on". It must end upright,
out of water and with a reason, and go back to its rounds. Four defects it
found are fixed:

- "come here" drove straight down a bank into 0.23 m of river;
- the solar farm's open deck counted as a solid box and trapped a rover
  parked beside it;
- a rover inside a part's margin could not start any route;
- "go on" kept its spent retries.

A blocked route now says what blocks it. On terrain 7 it delivers round the
trench; on terrain 4 the trench honestly blocks it. The "mound" scenario never
heaps a mound, because the dig's spoil goes to a pile, so it is a second haul
over trenched ground.

**Main's red suites are repaired.** These were failing on untouched main and
now pass on this branch:

- `workshop_navigation_tests` (15/15);
- `workshop_browser_tests` (56/56);
- `world_room_tests`, `api_docs_tests`, `market_tests`, `goods_tests` and
  `gathering_journey_tests`;
- `world_goods_tests`, `private_ground_tests`, `quick_tool_tests`,
  `material_preview_tests` and `world_navigation_tests`.

Real bugs found along the way and fixed:

- soil dug just before a terrain rewrite was lost on server restart;
- a heavy tool's first stroke started while its head still sagged, and
  loosened nothing;
- Menu → Controls opened a panel inside a folded rail;
- physical skin edits always failed;
- the chat box could not be reached on a 720 px window;
- links without a world dropped `?technique=`;
- a mine rover on 8.15° ground could not leave its vein;
- the picked-machine panel, rebuilt every 150 ms, swallowed clicks.

**Native bodies walk and swim** (experimental):
[native-walk checkpoint](native-walk-checkpoint.md).

**The new-player playtest is ready to run, not run:**
[protocol](human-playtest-protocol.md) and `tools/playtest_report.py`.

## 2026-10-04: the AI players finish the whole opening

Both explorers, the reference one and the model-driven one, now finish every
chapter on both terrains, the light and the sun included (70 to 75
decisions). They do it as a person would. They make a recipe that declares a
lamp or a panel, whatever it is called. They switch the light on through its
own use. Then they let the world run until the lamp has drawn from its
battery, or the sun has charged the panel's.

Running it found four real problems:

- **The sun goal could never complete.** It read `given_j`, which is what a
  battery gives *out*. What a battery takes in from its panels is `taken_j`.
- **The Camp solar panel had 10 mm of glass.** That is 6 kg for 0.24 m², and
  a new player had to buy 24 lots of it. The solar array has a new
  `panel_thickness_m` parameter (default unchanged at 10 mm). The camp panel
  uses 4 mm, like module glass: 2.4 kg.
- **Buying was one 0.25 kg lot per decision, and banking 500 J.** One
  decision now buys every lot a gap needs, and banks enough for them first.
  Each is still an ordinary priced purchase or 500 J deposit.
- **The ground tool's turn waited 2 s of wall time.** On a busy machine it
  refused. It now waits world time, like the other waits.

The AI's decision cap goes from 64 to 128, because the opening is now four
chapters with three paid builds. A native player's body is now tested to
survive an install, which rebuilds the room, and a restart.

Construction progress is in the
[construction checkpoint](construction-guidance-checkpoint.md): ground
preparation, saved steps with links, fastening, the first construction skill
and the two-second guide.

## Verification

```powershell
$R="build/rel/Release"
$env:BANJO_LIVE_ENGINE="$R/banjo_live_world_run.exe"; $env:BANJO_PLATFORM_ENGINE="$R/banjo_platform_cli.exe"; $env:BANJO_LIBRARY="$R/banjo.dll"
python tests/recipe_audit_tests.py
python -m unittest tests.fabrication_remake_tests -k camp_solar
python -m unittest tests.fabrication_remake_tests -k test_failed_connection_paid_mixed   # 8 of 8
python tests/workshop_install_engine_tests.py -k seated
python -m unittest tests.world_seed_tests tests.goal_chains_tests
python tools/terrain_compare.py --build $R --out build/terrain-compare
python scripts/check-source-registration.py
```

## Still to do on the owner's list

- Human recognition of materials by day and night on the three ground types
  (needs people; the playtest protocol covers it).
- Catalog shapes still missing: chair, shelf unit, kettle and cart; single
  sources for ceramic and concrete.
- Construction: supports beyond the pad (posts, beams, braces), raising low
  ground by heaping, and bounded customisation proposals.
- The playtest with 8–12 new players. R3 stays paused.
