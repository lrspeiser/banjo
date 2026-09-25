# The Workshop: everything left to do

A survey, 2026-09-24, of what the bench is and what it would take to make it a
proper simulation of the world, where you can change a design, test it and save
it. Read with `docs/what-is-left.md`, which is the shorter working list.

Every item has a code reference, because most of what is wrong here is not
missing work -- it is work that was done and then buried, or wired to a name
that no longer matches.

## What the bench is today

Seven products (table, stool, bench, chair, shelf unit, cart, kettle), a 3D
view, a chat that can build part by part, and three buttons: Check it, Make it,
Back to the world. Underneath that there is far more: a part builder, a joint
editor, four compile views, a library, saved designs with versions, a test
catalogue, an install preview, a bill of materials and a rack.

**The Workshop is not short of capability. It is short of three things:**

- **Arrangement.** `workshop.js:1151` sweeps the entire right pane and the old
  left pane into one collapsed `<details>` called "Bench extras", whose summary
  is 0.74rem grey text. About fifty working controls live in there, including
  every way of saving, every way of testing, and every way of editing a part.
- **Memory.** There is no undo anywhere. Every earlier revision of a saved
  design is unrecoverable. No test result is ever stored. Nothing can be
  deleted.
- **Consequences.** Pass or fail reaches exactly one test with four criteria.
  Everything else answers `"not-declared"` or `"observed"`. Most of what the
  bench tells you is arithmetic over a wireframe, and it says so.

## 0. It already works and you cannot reach it

The cheapest work in the whole list.

- **0.1 Unbury the bench.** Take the fifty controls out of "Bench extras" and
  lay them out. (`workshop.js:1151-1156`)
- **0.2 A chat turn can die and lock the bench.** A 200 response without a
  `workshop_chat` key matches neither branch, so the "Working…" bubble stays for
  ever and the textarea stays disabled. **The only recovery is reloading the
  page.** (`world.html:69`)
- **0.3 Clicking a point to feel the force is dead at all five call sites.**
  `reprobe()` needs `force_probe` selected; the picker filters to
  `category == "simulation"` and `force_probe` is tagged `"analysis"`.
  (`workshop.js:650` against `workshop_bench.py:51`)
- **0.4 The only code that would ever draw a battery or a motor is
  unreachable**, by the same kind of mismatch: `machine_control` is tagged
  `subject: "reference-fixture"` and the picker requires `"selected-product"`.
  (`workshop.js:1576` against `workshop_bench.py:52`)
- **0.5 "run it" beside each declared test is a `<strong>`, not a button.**
  (`workshop.js:1026`)
- **0.6 The legend that explains the amber marks is hidden by CSS**, so the
  centre-of-mass dot and the support ring are unexplained.
  (`world.html:31` killed by `workshop.css:177`)
- **0.7 The server says what the model changed and nothing shows it.**
  `workshop_chat.py:959` returns `changed`; no renderer reads it. The design
  silently morphs. Same for Check it, which can redraw the whole design with no
  account of what moved. (`workshop.js:946-949`)
- **0.8 Editing the rack in one place does not refresh the other.**
  (`workshop.js:1857`)
- **0.9 `what_made` has no caller.** The round trip from a body in the world
  back to the bench that made it is built and unreachable from the UI.
  (`server.py:1335`)
- **0.10 Dead markup and dead CSS**: `.ws-workspace-tabs` is referenced twice
  and never created (`workshop.js:1726`, `:1740`); `#ws-active-situation` is
  written every render and permanently `display:none`; the Apart slider is
  positioned on top of the playback controls (`workshop.css:228`).

## 1. Change a design

- **1.1 No undo. None.** Not one step, not a history, not revert-to-saved. A
  chat turn, a Check-it redraw and a Thicker click are all permanent.
- **1.2 Every revision is written and none can be read.** The
  `workshop_library_versions` table keeps every payload
  (`workshop_library.py:78-86`, written `:258-260`) and **nothing ever reads
  it** -- there is no `load_version` and no `list_versions`. Meanwhile
  `workshop_store` overwrites `designs/<id>.json` in place, so `revision: 7`
  means "saved seven times" and one to six are gone.
  (`workshop_store.py:41-42`, `:124-126`)
- **1.3 You cannot type a dimension.** Every change to an existing part is a
  ±12% nudge. Exact millimetres are enterable only for a *new* part.
  (`workshop.js:1241`, `:2061-2068`)
- **1.4 `edit` has seven actions and none of them moves or rotates** --
  longer, shorter, thicker, thinner, wider, narrower, material. Repositioning
  is reachable only by hand-writing raw override fields.
  (`workshop_components_core.py:21`)
- **1.5 A part cannot be renamed, re-roled or re-familied.** The workaround,
  remove and re-add, drops every joint that held it.
  (`workshop_components_core.py:76-79`, `workshop_construction.py:783`)
- **1.6 Editing one part silently detaches it from the parameters.** Overrides
  are absolute, so a leg once shortened stops following `height_m` -- with no
  flag on the part and no note in the record.
  (`workshop_components_core.py:75-79`)
- **1.7 Joint inference latches shut on the first edit.** `adopted()` sets
  `joints_authored = True` once and thereafter *"nothing is inferred"*, so parts
  brought into contact by a later edit are never fastened, only listed as
  suggestions. (`workshop_construction.py:723`, `:865-883`)
- **1.8 Two parts may have at most one joint**, so a shaft bearing in two places
  on one housing cannot be said. (`workshop_construction.py:528-530`)
- **1.9 There is no "start from nothing" in the catalogue.** Seven products and
  no custom entry, so building part by part is only reachable through the chat.
  (`mcp/workshop.py:791-794`)

## 1a. Where to begin

**Done (2026-09-24).** The right pane has been wrong twice in one day. It was
one shut drawer called "Bench extras" holding about fifty working controls, and
nobody ever opened it. Un-burying it made six named sections, all open, and the
owner said: *"there are so many buttons and fields in the right nav of the
workshop I don't have a clue where to begin on it."*

Both are the same fault, and it was never that the controls were visible: there
was no ORDER OF WORK, so every control looked equally like the next thing to do.

The pane is four steps now and you see one: **Ask** what to make, **Change** it,
**Try** it, **Keep** it. The chat sits above them, because it is another way of
doing any of the four rather than a fifth step. Inside Change, the two things a
person reaches for are out and the other six are drawers with the names they
already had.

Measured, on opening the bench: **113 controls on screen before, 30 after** --
28 in Change and the chat's two. Nothing was deleted and nothing went behind an
unnamed lid; every drawer says what is in it.

The step names are what a person is doing; the keys under them are the modes
the workspace has always used (`start`, `build`, `test`, `details`), so the
viewport and the test scheduler go on hearing what they listened for. Picking a
part -- in the list or in the view -- takes you to Change, and picking a test
takes you to Try, so you are never left looking at the wrong pane.

## 2. Test it

**Done (2026-09-24).** There were three testing systems and they did not agree;
there is one now. `try_in_a_room` makes the design in a room with 400 mm of
soil under it, gravity and a sky, through `workshop_install` -- the world's own
installer -- and then does to it whatever you ask: a weight set on it, a drop,
a slide, a block thrown at it, in any combination. `declared_static_load`,
`drop_product`, `slide_product`, `impact_product` and `rigid_motion` are marked
retired and are offered to nobody.

What that fixed, and what came out of doing it:

- **2.1 The test room is the one test.** Done.
- **2.2 It can apply a load.** Done -- and the weight is a body, not a declared
  force: an iron cube of the mass asked for, let go a millimetre above it, that
  presses through real contact and can slide off.
- **2.3 It reads orientation.** Done: every body reports `turn_deg` from where
  it was put down, and past 45 degrees the answer is "it went over".
- **2.4 It reports fracture.** Done -- and doing it found a real error in the
  reading. The engine names what MIGHT give way in `breakable`; the failure run
  then says `held`, `dented` or `broke`. Counting every run as a break called a
  concrete table under 400 kg "broken" when it had held. `broke` now holds only
  the runs where the body came apart.
- **2.5 It has playback.** Done, at 30 frames a second, with each body drawn as
  the engine's own shape -- its cells where it is cells, its exact parts where
  it is exact, every piece as the cells the engine left it.
- **2.6 It verifies no geometry.** Still true. The install is taken on trust;
  the sparse trial's cell-by-cell check against the engine has no equivalent
  here.
- **2.7 Pass or fail** now reaches the one test, against three things it
  actually measures: how far it moved, how far it turned, and how many of it
  broke. Opt-in, and `not-declared` otherwise.
- **2.8 The `tip` trials every assembly declares are never run.** Still true.
  Both filters keep only `static_load`. (`mcp/workshop.py:744-745`,
  `workshop_statics.py:143-152`)
- **2.9 No test result is ever stored.** Still true.
- **2.10 The general physics-trial engine cannot be pointed at a design.**
  Still true.
- **2.11 There is no machine panel at the bench.** Still true.

And one thing that was not on the list, which doing this exposed:

- **2.12 Most archetypes cannot be MADE at all**, so they cannot be tested. A
  `cart` and a `kettle` are refused by the installation adapter ("only fixed
  structural solids ... articulated machines and containers need their own
  interfaces"); a `chair`, a `stool` and a `shelf-unit` come out of their own
  templates with "disconnected or missing physical components" and never
  compile. Only `table`, `bench` and things drawn part by part through the chat
  install. The old catalogue hid this by offering those kinds no test at all.

Two measured differences from the rigs this replaced, both of them the world
being the world:

- Glass dropped 4 m onto 400 mm of soil does not break. On the old rig's hard
  floor it did, at 8.85 m/s against a threshold of 8.70. Soil is softer than a
  plate, and soil is what it will stand on.
- The whole browser suite runs in 51 seconds instead of 337.

## 3. Save it

**Partly done (2026-09-24).** Undo, a readable history, delete and rename, and
test results kept against the exact shape they were measured on.

- **3.1 Nothing can be deleted.** Done for the three that matter: a saved
  design, a library component (with its versions and its tags) and a test
  preset. A price and a rack row still cannot be removed -- they are values
  with defaults, not things a person made.
- **3.2 Nothing can be renamed.** Done, for both a saved design and a library
  component, and renaming does NOT count as saving it again: the count of
  times a thing was saved holds, and no version row is minted. Duplicating is
  still not there.
- **3.2a Every version was written and none could be read.** Done.
  `workshop_library_versions` had been written on every save since the table
  was made, with no reader anywhere in the repo. There is one now
  (`list_versions`, `load_version`), and the library card says how many
  versions a thing has. The row keeps only the payload, so what a version was
  CALLED at the time is not recorded: renaming a thing renames its history.
- **3.2b No undo. None.** Done, in the page. Every edit went through `took()`
  and nothing kept the state before it, so a wrong material on all eight parts
  stayed wrong. There is an Undo, a Redo, and a list of what you did to get
  here -- worked out by comparing the two states rather than by every caller
  remembering to say, and grouped by what was done rather than by which part
  it was done to. It lives for the session; it is not written down.
- **3.2c No test result was ever stored.** Done. Every bench run is kept
  against the design's FINGERPRINT, which is the only thing in the Workshop
  that says two designs are the same geometry: edit a leg and the fingerprint
  moves, so yesterday's pass stops being claimed for today's shape. The result
  card says what this exact shape was told before. Fifty runs per design are
  kept.
- **3.3 Saved designs cannot be searched.** Everything, newest first, no filter.
  Tag search exists, but only for library components.
  (`workshop_store.py:146-166`)
- **3.4 Reopening a saved design gives no feedback**, so you cannot tell whether
  it worked. Measured by hand: the title still showed the old variant name.
- **3.5 A saved design is only as stable as the assembly code.** Geometry is
  regenerated on load rather than stored, so changing `_build_framed` silently
  changes every saved table. The fingerprint is recorded and never re-checked.
  (`workshop_store.py:6-11`, `:87`)
- **3.6 A design's declared tests are not saved** -- they are recomputed, so a
  load case changes whenever the assembly code does. (`mcp/workshop.py:1021`)
- **3.7 No export, no import, no sharing.** Every query is scoped to one owner
  and no function writes a portable file. (`workshop_library.py:37-38`)
- **3.8 Schema versions are checked for equality with no migration.** The first
  format change orphans every saved design; the SQLite schema has no
  `user_version` and no ALTER path. (`workshop_store.py:53-54`,
  `workshop_library.py:63-121`)

## 4. Close the loop to the world

- **4.1 Editing a design and making it again puts a SECOND thing in the room.**
  `commit` only appends, with a fresh uuid root every time. There is no
  uninstall, no replace, no update. (`workshop_install.py:711`, `:724`)
- **4.2 An installed body has no staleness signal.** The recipe stores no
  fingerprint and no revision, so nothing can tell whether the thing standing
  in the room still matches the design.
- **4.3 Provenance is dropped silently.** Receipts are a ring buffer of 64, so
  past that `what_made` starts failing for things that are still standing.
- **4.4 The bench and the world are two page loads.** `?workshop=1` loads
  `workshop.js` instead of `world.js` and CSS hides the world, so going to the
  bench and back loses where you were standing and what you were holding.
  Time "freezes" only because nothing is stepping the room.

## 5. A proper simulation of the world

What the world has that the bench does not know about at all.

- **5.1 One flat terrain.** The test room hard-codes flat ground, 400 mm of
  soil, no sand. The world has valleys, slopes, rock, a river bed and erosion.
  A cart cannot be tested on a slope.
- **5.2 No ground materials.** Only soil depth is settable -- no friction, no
  bearing capacity, no mud, ice or gravel. (Related: the world itself slides the
  same whatever the ground is made of.)
- **5.3 No water at all, and not even refused.** The bench never writes a
  `water` key while the world runs a full watershed. Buoyancy, rain and
  immersion are untestable.
- **5.4 Almost no heat.** The test room never asks for the thermal state. The
  sun charges a battery and heats nothing. The one thermal test targets a
  `kettle` kind that is not in the assembly list at all.
- **5.5 No person.** No hands, no reach, no grip, no lifting. A design must
  declare which part you take hold of and then nothing ever takes hold of it.
- **5.6 No wear.** Nothing ages, fatigues or loosens. The only mentions are
  three identical disclaimers.
- **5.7 Four other objects**, and no way to put a second design in the room or
  to test two things against each other.
- **5.8 No weather, no season, no long run.** A test is capped at 120 seconds.

## 6. What a design cannot say at all

The vocabulary itself. Each of these is a refusal with a message, not an
oversight.

- **6.1 No holes.** Geometry is purely additive; a bore is only a measured axis
  clip, so mass, volume, the bill of materials and the voxel compiler all treat
  a bored part as solid. (`workshop_construction.py:370-420`)
- **6.2 No fasteners, and joints are free.** A joint is bonded, pressed or a
  bearing. No screw, bolt, nail, dowel or bracket, and a joint has no mass and
  no cost -- forty parts with thirty-nine joints cost exactly what forty loose
  parts cost. (`workshop_construction.py:48`, `workshop_library.py:462`)
- **6.3 Nothing flexible.** No rope, cable, belt, spring, gear or slider.
  *"beam/sheet/cable solvers are not implemented"*. They exist as dead strings
  in a set nothing emits. (`workshop_rigid.py:36`, `workshop_force.py:25`)
- **6.4 A cylinder's curved side cannot take a joint**, so nothing can be
  fastened to the side of a wheel or a shaft.
  (`workshop_construction.py:184-186`)
- **6.5 Rotated parts are drawn but not rigid-compiled and not
  clearance-checked.** (`workshop_rigid.py:80`, `workshop_buildability.py:71`)
- **6.6 Mixed materials cannot be made.** Refused in three places -- and the
  stock cart is already mixed, because its axles are hard-coded iron, so a whole
  archetype cannot reach the world as one body. (`mcp/workshop.py:643`)

## What I would do, in order

1. **Unbury the bench and fix the dead wires** (all of group 0). About fifty
   working controls become reachable, the chat stops hanging, and clicking a
   part starts answering. Nothing new has to be built.
2. **One test, and make it the little world** (2.1-2.6). Add load, orientation,
   fracture and playback to the test room; fold drop, slide and strike into it;
   retire the rig with no ground. Then a bench answer means something about the
   world.
3. **Memory** (1.1, 1.2, 2.9, 3.1-3.3). Undo, a readable history, delete and
   rename, and test results stored against a revision so two revisions can be
   compared.
4. **Close the loop** (4.1-4.2). Making an edited design replaces the thing in
   the world instead of standing a second one beside it.
5. **A machine panel at the bench** (2.11), so a robot can be worked by hand
   where it is built.
6. Then the deeper simulation (group 5) and the vocabulary (group 6), which are
   each their own piece of work and should be chosen deliberately rather than
   swept up.
