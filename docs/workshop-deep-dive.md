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

## 2. Test it

There are **three** testing systems and they do not agree.

| | ground? | mechanisms? | what it gives |
|---|---|---|---|
| `run_static_load` ("Run simulation") | no | **refused** | fracture, displacement, pass/fail |
| drop / slide / strike catalogue | a floor | table and bench only | playback, fracture |
| the test room (new today) | **real terrain + sun** | yes | position, speed, battery, program |

- **2.1 Make the test room the one test.** It is the only one with ground,
  gravity and a sky, and the only one that uses the real installer, so it is the
  only one that answers for the world. Everything below is what it still lacks.
- **2.2 It cannot apply a load.** A chair rated for 120 kg can be installed in
  it and not sat on. (`workshop_test_room.py:80-91`)
- **2.3 It does not read orientation**, only position and speed -- so **you
  cannot tell whether a thing fell over**, which is the one trial every piece of
  furniture declares. (`workshop_test_room.py:234-237`)
- **2.4 It reports no fracture.** It never reads `breakable`, so "it broke" and
  "it moved" are indistinguishable.
- **2.5 It has no playback.** Every other engine test wraps the session in
  `workshop_recording`; this one does not, so there is no timeline to scrub.
- **2.6 It verifies no geometry.** The sparse trial checks every cell against
  the engine; the test room takes the install on trust.
- **2.7 Pass or fail reaches one test with four criteria** -- displacement,
  rotation, fracture count, actual load -- and only on `declared_static_load`.
  (`workshop_acceptance.py:13-18`, `workshop_bench.py:104-105`)
- **2.8 The `tip` trials every assembly declares are never run.** Both filters
  keep only `static_load`. (`mcp/workshop.py:744-745`,
  `workshop_statics.py:143-152`)
- **2.9 No test result is ever stored.** You cannot ask "did this pass last
  time" or compare two revisions. The only durable trace of testing is a 1-5
  rating in `feedback.jsonl`.
- **2.10 The general physics-trial engine cannot be pointed at a design.**
  `mcp/physics_trial_tools.py` takes a hand-authored document and there is no
  design-to-trial adapter anywhere.
- **2.11 There is no machine panel at the bench.** The world has On/Off,
  Lower/Stop/Raise, a drive setting and four read-outs (`world.html:25`); the
  Workshop has nothing, so a robot cannot be worked by hand where it is built.

## 3. Save it

- **3.1 Nothing can be deleted** -- not a saved design, a library component, a
  test preset, a price or a rack row. Fourteen HTTP routes and not one removes
  anything. (`server.py:1282-1288`, `:1331-1336`)
- **3.2 Nothing can be renamed or duplicated** either.
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
