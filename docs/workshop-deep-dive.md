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

## 1b. The bench is the chat now

**Done (2026-09-24), and it replaces 1a.** Three goes at the right-hand pane:

1. One shut drawer called "Bench extras" with about fifty working controls in
   it. Nobody opened it.
2. Un-buried into six named sections, all open: *"there are so many buttons and
   fields in the right nav of the workshop I don't have a clue where to begin
   on it."*
3. Arranged as four steps -- Ask, Change, Try, Keep: *"I don't really
   understand how to use the try or change or keep functions, it makes no
   sense. Since we can't make this work we should just leave it all up to the
   chat."*

So the bench is the chat down one side, the object, and **one bar** over it:
which product (a dropdown), Wire/Skin, the four points of view, Check it, Make
it, and the way back to the world. The page header, the panel under the object
that said "hold objects on a stable work surface", the row of view buttons
under it, and the Run simulation / Reset to setup dock are all gone from the
page.

Under the chat box there are things to ask for -- "Drop a 20 kg iron block on
it from 2 m and show me what happens" -- and each one is a real turn. When the
chat tries the thing out, the run is played **over the object**, with one
button back to the build.

**What a person can no longer reach.** The panels are still built and still
wired -- the page reads values out of them and the browser tests hold the bench
to them -- but they are not on the screen. Nothing was deleted.

Saving, opening and undo were the three that mattered, and the chat has them
now: `save_design`, `list_saved_designs`, `open_saved_design` and
`take_it_back`. Undo is the page's, because the page holds the session's
history; the tool returns the instruction and the page walks back through it.

Still only reachable by the page or the API:

- **The library**: reusing a saved component by name works
  (`reuse_library_component`), but browsing does not.
- **The rack**: `what_it_needs` reports what is short, but nothing can SET a
  rack row from the chat.
- **Saved test presets**, which have no home now the picker is off the bench.

## 1c. The model writes the room

**Done (2026-09-24).** The owner: *"why can't the llm write bits of code to run
tests? does it need to always be prebuilt?"*

It did. `try_it_in_a_room` had four settings -- a weight, a drop, a slide, a
thrown block -- and a question outside those four could not be asked at all.
"Roll a ball down a ramp into its leg" came out as a block thrown sideways,
because that was the nearest thing the vocabulary had.

It takes `add` now: up to twelve things the model writes into the room, each
one what somebody would say out loud -- what it is made of, how big, where,
which way up, how fast it is already going, and whether it is driven into the
ground. **Height is measured from the ground**, so 0 is resting on it; 400 mm
of soil is not a number anybody should have to know. Anything tilted becomes an
exact body, because a lattice body is a box on the cell grid and cannot be
turned.

It is DATA, not code. Every field is checked against a bound before the room
opens and a refusal says which thing and why -- "the ground is 16 m across, so
it has to stand within 7.5 m of the middle" -- so a scene the model got wrong
comes back as something it can fix rather than a crash. Nothing is executed.

Measured: a 180 mm iron ball let go at the top of a 20-degree oak ramp rolls
from x=-2.20 to x=-0.65 and falls from 1.15 m to 0.49 m in four seconds, and
the table it reaches moves 41 mm.

**Real code is a separate question.** A short Python script driving the room
step by step -- loops, conditions, measuring between steps -- is strictly more
powerful, and it is arbitrary code running on the server that holds the world
and the API key. It needs a separate process with no filesystem, no network and
a time and memory cap. That is its own piece of work and the owner has parked
it behind this one.

## 1d. Testing means finding the range, and saying what you are doing

**Done (2026-09-25).**

**Where the wait actually is.** Measured, not guessed: the physics of "drop
20 kg on the table from 2 m" takes **0.35 s**, and a six-second run takes 0.36 s.
Everything else in a turn is round trips to the model. Watched live, one turn
went: 5.4 s to look at the part, 10.3 s to check the room can carry it (a call
that itself takes 10 ms), 11.6 s to measure it, and about 20 s to answer. The
work is a rounding error; the thinking is the wait.

Three things follow.

- **Say what it is doing while it does it.** A turn is one POST that answers at
  the end, so the page hands in an id, the server writes each step as it
  happens, and the page reads it back about once a second and puts it under the
  working bubble -- in a person's words ("looking at the design", "trying it in
  a little world"), with how far into the turn each one was. The thinking
  between calls is said too, because that is where most of the wait is.
- **Best guess and go.** Asking before starting costs a wait as long as the
  work. The prompt now says to pick the sensible thing, DO it, say what was
  picked in one line, and THEN offer what else they might have meant --
  everything can be taken back. `ask_the_person` is for afterwards, or for a
  fork that genuinely cannot be picked.
- **`find_the_limit`.** One run only tells you whether the number you guessed
  was over or under. A sweep turns one thing up through five or six values and
  says where the answer changes -- holds here, cracks there -- and keeps the
  run where it changed to watch. Every row is a real run; nothing is
  interpolated. Four runs plus the one to watch take **1.6 s**.

  It says which way to look when the answer is outside the range, and that is
  the whole value of the sentence: glass struck at 10 m/s breaks at 5 kg, the
  least tried, so the limit is BELOW the range. "Past the end of what was
  tried" would send somebody looking in exactly the wrong direction.

**A weight of cells has to BE a whole number of cells.** A 1 kg iron cube is
50 mm, which is not a whole number of 40 mm cells, and the room refuses it.
Rounding each side is no good -- 50 mm down to 40 mm is half the mass. So a
weight is now the squarest stack of whole cells of about the right mass: 1 kg
is two cells, an 80 x 40 x 40 mm bar weighing 1.008 kg, and the run says what
it really weighs when that differs.

**Bubbles.** `#ws-chat-log` is a grid, and a grid row takes an equal share of
the box, so two short messages in a tall log were two tall bubbles of mostly
nothing. `align-content:start` and `align-self:start`.

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
- **2.11 There is no machine panel at the bench.** **Done (2026-09-25), and
  not as a panel.** The world has On/Off, a direction and a drive setting for
  every control on a machine; the bench had none of it, so a machine could be
  built here and never worked until it was out in the world. A wall of buttons
  is the thing the owner took off this page twice, so what it got instead is
  `do`: a list of {at_s, control, power, direction, setting} carried out while
  the run goes on. "Drive it forward for three seconds and then stop" is two
  orders at 0 s and two at 3 s, and you watch it happen over the object.

  It is the same `operate` the world's panel sends. Measured: the chat-built
  robot, told to drive at full setting, goes 137 mm in four seconds and stops
  dead when it is switched off -- and in a six-second run by hand it goes over,
  129 degrees from how it was put down, which is the sort of thing a bench is
  for finding out.

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
  **Done (2026-09-25).** `preview` takes `replace`: `true` for the most recent
  still-standing copy of this design, or an explicit list of bodies. The bench
  asks for it, so Make it after an edit puts the new one where the old one was.
  Funded fabrication does not: each run of a job is its own output and none of
  them replaces another, which is why this is asked for rather than assumed.

  What it took to make the append-only guard safe for removal, all of it
  measured against the engine rather than reasoned about:

  - A group of cells is **several names in the spec and one body in the
    engine** -- they are joined -- so what the spec drops and what the world
    loses are different sets, and the guard needs both.
  - The engine counts the **things** it let go of, not the bodies: five bodies
    installed as one group report as one.
  - A machine cannot be identified by name. The replacement declares a battery
    called "battery" too, so the name survives while the thing does not. Nor by
    body: a saved motor does not always say which body it is on, because the
    engine fills that in from the joints and the joints travel only when their
    set changes. What is checked instead is that every machine naming a body
    that is STAYING is still there, unchanged and in order, and that nothing
    which went named a staying body.
  - A pin, a saved gesture, a blade's cut, a tool point and an interaction
    point all go out with the body they are about; anything else still naming a
    removed body is a refusal with the key that named it. (`workshop_install.py:711`, `:724`)
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
