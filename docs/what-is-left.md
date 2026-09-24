# What is left

The working list. `docs/roadmap.md` is the history -- what was done and what was
measured; this is what has not been done yet. Keep it current: when something
lands, move it up and say what was measured; when something is found to be
missing, put it in.

Last touched 2026-09-24, branch `agent/fracture-truth` (pushed, not merged).

## Ready to try

These work and are watchable. `python playground/server.py --port <p> --engine
<build>/banjo_platform_cli.exe`, then:

- **A robot goes to a stool and sits on it** -- `/world?scene=tests-sit`. Look
  at the robot, E for its panel, On. 12.5 s, stops 0.51 m from the stool's
  middle and 3.4 degrees off square, its torso resting 24 mm above the seat.
- **Which end of a motor turns** -- `/world?scene=tests-motor`. Three
  turntables, each a block on a free pin above a pedestal with a second block
  and a motor above it, so BOTH ends are free and the only thing deciding is how
  hard each is to turn. E on one, On. Measured: 287.8x the turn to the light end
  where its moment is 285.3x smaller; 4.7x where it is 4.8x; and two of the same
  going -356.15 and +356.15 degrees. The middle one is the point -- its top is
  the HEAVIER of the two and still the one that comes round.
- **What a break costs** -- `/world?scene=tests-break`. Drop the ball on the
  plank; every break reports what it cost.
- **A rover that roams by itself** -- `/world?scene=tests-rover`, and the same
  rover on solar (`tests-solar`) and through a night (`tests-day`).
- **The Workshop** -- `/world?workshop=1`. Ask the chat for something, Check it,
  Make it, Back to the world. The rack at the bottom holds the stock a design
  spends; a design short of stock is refused until the rack has it.
- **A thing the Workshop made, opened on the bench again** -- make something,
  then ask the world which design made it: it hands back the recipe, and the
  bench loads it.

## The two places

The owner, 2026-09-24: "I don't want 10 different places. I want the main world
and a workshop/lab where time freezes and you can craft items and test them and
so forth. Remove all other code paths and consolidate everything in these two."

Today there are **7 pages and 22 scenes**. `/` is the fracture lab (where a
bowling scene of 12 bare bodies ran and nothing moved), `/world` is the world,
`/explore`, `/qa`, `/mechanics-qa`, `/tool-qa` and `/fabrication` are five more.
Of the scenes, `world.html` offers two on its menu and the other twenty are
reachable only by typing a URL.

The target is two:

- **The world** -- `/world`. One place you walk around in.
- **The Workshop** -- `/world?workshop=1`. Time frozen. Craft a thing, finalize
  it, test it in a little room that behaves exactly as the world does, and take
  it out to the world.

**The Workshop is already a mode of the world page** (`world.html:28`, body
class `workshop-mode`), so two places is structurally most of the way there. The
work is what the Workshop cannot yet do, then the deleting.

### What the Workshop cannot do yet, in the order to fix it

1. **Finalize a thing so its small parts survive.** The lattice paths cannot
   carry a part thinner than two cells -- 80 mm at the bench's 40 mm grid, 100 mm
   in a 50 mm room. The exact path has a floor of **1 mm**
   (`mcp/workshop_rigid.py:19`), and the rover in the world proves it: 12 mm
   caster cheeks and a 12 mm pin, live, at a 50 mm cell size
   (`tools/build_rover_room.py:167`).

   The compiler that does this properly already exists and **nothing in the
   server can reach it**: `playground/rigid_assembly.py:94` makes an exact
   compound per fixed group with real hinge pins, each part its own material and
   its own rotation. The one the Workshop *can* reach, `compile_rigid`, demands
   a single material, axis-aligned parts and no mechanisms -- useless for a
   machine. Its only callers today are `tools/build_cart_room.py` and a test.

   **Done.** `rigid_assembly` is wired in: a design whose parts are all declared
   rigid, and which has something that turns, is compiled to exact bodies on
   real pins and installed that way. Measured: a 12 mm iron pin is drawn 80 mm
   as cells, and 12 mm finalized -- in a body of oak, which the one-compound
   compiler cannot do at all. Two things had to give way for it: the exact
   compiler only knew shaft-in-bore bearings, where the bench can only draw a
   butt joint, so it now takes a contact face's normal as the axis the way the
   construction library already does; and staging had to learn that a finalized
   machine has no cells to check against the grid.

   **What is NOT done:** a finalized machine stands still and stable, but under
   motor load it eventually throws itself across the room. Every bearing the
   bench can draw is between two parts that TOUCH -- that is the bench's rule
   for fastening -- and as exact bodies those faces are in contact while the
   pin drives them. Nothing in the engine stops two bodies joined by a pin from
   colliding with each other (no group filter in `src/rigid/JoltWorld.cpp`),
   which is fine for the rover, whose parts were drawn with clearance by hand,
   and is not fine for anything the bench draws. This is the same root as the
   swivel that would not turn.

2. **Test it in a little room, not a rig.** **Done**
   (`playground/workshop_test_room.py`). A test room is a room of the same shape
   a world room is: flat ground of real soil, gravity, and a sky with the sun
   somewhere in it or below it. Testing a thing is **installing** it through
   `workshop_install`, the same call the world makes -- same compiler, same
   seating on the ground, same battery, motors and program. There is no second
   physics and no second way of making a thing.

   Measured, on one design made both ways: **the bench took in 431.1 J and the
   world took in 431.1 J.** At noon its panel gives 43.08 W; at eleven at night
   the sun is 60 degrees below the horizon, the panel gives 0.00 W and the
   battery does not move by a millionth of a joule. It stands on ground 400 mm
   up and drifts 4 mm in five seconds.

   Reachable three ways: `workshop_test_room.try_it`, `try_in_a_room` on the
   plan route, and `try_it_in_a_room` as a chat tool, so the model can answer
   "does it work?" by running it rather than by looking at its shape. Trying
   costs nothing -- the room keeps a scratch rack of its own, because being
   refused a test for want of stock is backwards. Making it in the WORLD still
   spends the world's rack.

3. **Put other things in the test room.** **Done.** A small catalogue -- a
   stool, a plank, an iron ball, a concrete post -- placed by name and a
   position, by the person or by the model. Measured: a stool in the room
   changes nothing about the machine (431 J either way).

### Then the deleting

Pages to go, with what has to move first:

| goes | first |
|---|---|
| `/` + `app.js`, `style.css`, `scene.js`, `/api/fracture*` | `tests/playground_tests.py:740` asserts they serve. **`playground/fracture_lab.py` STAYS** -- despite the name it is the spec admission gate for the world and the Workshop both, with 45 importers. Only the panel is the lab. It wants an honest name. |
| `/explore` | nothing links to it; only an uncI'd test uses it |
| `/qa`, `/mechanics-qa`, `/tool-qa` | the **pages** only. `material_qa.py` is the shared run manager for all three plus fabrication and physics trials; `mechanics_qa.binary()` is imported by two others. CI runs their headless twins under `scripts/`, and `node --check` on two of their .js files. |
| `/fabrication` | `fabrication_room.py` is a **world** capability (finite stock, gated at `server.py:1234`). The Workshop already has the rack; fold it in. |

Scenes to go: `explore`, `armoury`, `watershed`, `clearing`, `courtyard`, and
the duplicate keys `yard` and `valley` (same builders as `fabrication` and
`expedition`; `workshop.js:105` links to `yard` and must move first).

The `tests-*` scenes are the proofs, and six of them are driven by
`world_page_journey_tests.py` in CI. **They should become saved setups in the
Workshop's test room rather than places you visit** -- which is exactly what a
test room with items in it is. Nothing is lost and the proofs keep running.

Capabilities that live ONLY in something being removed, and where they go:

- the **energy-scaled failure law** runs in one room only (`tests-break`). It is
  the honest one; it should be a bench setting.
- **finite-stock fabrication** transactions -> the Workshop's rack.
- the **30-capability table** -> the Workshop, or dropped.
- **tool-qa's recorded product-use trials** and **mechanics-qa's fixture-vs-user
  separation** -> the Workshop's test room is the natural home for both.

## The Workshop

A deep survey of the bench is in [workshop-deep-dive.md](workshop-deep-dive.md):
about sixty items, grouped by whether they block changing a design, testing it
or saving it. The short of it: the Workshop is not short of capability, it is
short of arrangement, memory and consequences. Some fifty working controls sit
inside one collapsed panel; there is no undo and no readable history; no test
result is ever stored; and pass-or-fail reaches exactly one test with four
criteria.

## Next

1. **Every object should say what you do with it, and show you before it does
   it.** The owner, watching a bowling scene where nothing moved: does the ball
   have a primary action of "Roll"? Does clicking it and pressing the action key
   show a ghost of where it is going before you let go? The parts exist and do
   not meet:
   - The chat has `define_interaction_points` (grip, use, surface, container, in
     design-local metres) and `program_use` (one labelled action on Left mouse /
     J). Interaction points are gated -- a design that leaves one unbound is
     refused. A primary use is NOT gated: `core_use.DEFAULT` is
     `{"label": "Inspect"}`, so anything the model does not program becomes a
     thing you can only look at, silently.
   - The verbs are four: `inspect`, `strike`, `push_forward`, `place`. There is
     no roll, throw, pull, lift or turn. A bowling ball's best available action
     is `push_forward`, capped at 1.5 m/s over 1.5 m. "Roll it down the lane"
     cannot be said.
   - The previews are real, and are wired to gestures rather than to declared
     actions. A held thing's ghost (green fits, amber tips, red will not) shows
     where it comes to rest when PLACING. The aim arc is an engine prediction,
     not a drawn parabola -- the page calls `preview_flight` with the actual
     stroke and draws what comes back, including what it hits -- but only when
     THROWING or drawing a bow. An object whose declared action is "Roll" gets
     neither.

   What to build: one vocabulary of bounded physical gestures the model
   designates per object; a preview for every one of them, out of the same
   `preview_flight` machinery, driven by the declared action rather than by
   which of two gestures the page happens to be in; and a concept check that
   says "it says what you do with it" the way the bench already says "it says
   which part you take hold of". Keep the rule that is already right: a use is a
   bounded gesture the hand performs, never a prescribed body velocity. This is
   the same shape as a behaviour (docs/how-robots-think.md) -- a named action,
   bounded steps, written by the model, previewed before it commits, proved by a
   trial -- and should be one mechanism, not two.

2. **The chat-built robot cannot turn.** Nine tool calls build it, the bench
   takes it as drawn, it compiles into six bodies on five pins and the Workshop
   installs it as a machine -- but on the ground it drives and will not come
   round, so it never reaches the stool. The hand-built one does. First thing to
   test: the bench only fastens parts that TOUCH, so a butt-jointed swivel sits
   face to face with the deck it hangs from and the two faces rub, where the
   hand-built caster hangs from a pin with clearance. The compiler already
   speaks of "explicit clearance".

3. **Ask the model to design it.** The nine calls above are the ones a model
   could make, and they are written by hand. Nothing has yet asked the chat for
   a robot and watched what it draws.

4. **Behaviours written down as data, not code** (docs/how-robots-think.md).
   Start by re-expressing "roam" and "sit" in that form and checking the engine
   tests pass with the same numbers. If they cannot be expressed, the vocabulary
   is wrong, and that is worth knowing on the first day.

5. **A behaviour's trial**: the room, the start, and what must be true at the
   end. `tools/build_sit_room.py` already does this by hand; make it the shape.

6. **The chat writes a behaviour**, and it passes its trial before it is
   offered.

7. **A library and a price for behaviours**: shared between machines, and a room
   that would miss the realtime gate refused with the number.

## Waiting on the owner

From docs/how-robots-think.md:

- **D1.** When a person asks for a behaviour, does the chat show its trial
  running before it is installed, or does it go straight into the room?
  *Recommended: show the trial.*
- **D2.** May a person edit a behaviour by hand, in a panel that lists its
  states in plain English? *Recommended: yes, the numbers at least.*
- **D3.** Does a stuck machine ask for help by itself? *Recommended: no. It says
  why and waits.*
- **D4.** The body cap: a room holds 32 exact bodies, so five robots of this
  shape, where the processor would carry many more. Raise it before a small
  ecosystem of machines is attempted.

## Known gaps, in the order they will bite

- **A room holds 32 exact bodies.** Measured: one thinking robot runs at 33x
  realtime, four at 20x, about 27 us a step for each one added -- the cost of
  its bodies, not its thinking. The cap, not the processor, is the ceiling.
- **The ground slides the same whatever it is made of.** Terrain rolling
  resistance varies by ground material; terrain sliding friction is one material
  for the whole patch, so ice and sand slide alike.
- **A break spends about 41 J/m2 where oak charges 1,000.** The failure law
  reports the cost honestly and the energy that goes into it does not match it
  yet (docs/what-a-break-costs.md).
- **check_validity dead-ends on a vertical pin.** Drawing a caster the natural
  way -- a pin through the deck -- can never compile at any cell size, and the
  bench refuses it with "nothing here answers" rather than saying that a butt
  joint under a flat face is how a swivel is drawn.
- **A machine with a program owns its wheels.** An off program still tells them
  every step, so a person cannot drive a programmed machine by hand. Deliberate,
  but it should be said in the panel rather than discovered.
- **A lab scene and a world object are different things.** The bowling job
  (`?job=e72b...`) went through the fracture lab: 12 bare bodies, 13,872 cells at
  30 mm, "nothing is moving", 2.99x of realtime against the 1.1x limit. A lab
  scene has no interaction points by construction -- it is for measuring what
  breaks. Nothing says so when you build one expecting to play with it.
- **The rover journey flakes.** One CI red that passed on a re-run and was shown
  not to be the change under it.
- **`agent/fracture-truth` is not merged.** Five commits: the bench round trip,
  the sit program, the tests-sit room, the plan, and the chat-built robot.
