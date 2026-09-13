# Interaction profiles

Every object someone can use carries an **interaction profile**: a validated
description of how to hold it, operate it, aim it and explain it to the person
using it. The chat authors the profile alongside the physical construction; the
game implements the controls through a small set of reusable interaction types.

The principle is that **simple inputs drive accurate physical actions**. Nobody
should have to work every constraint of a bow by hand to shoot it — and nothing
the controls do may decide what the physics decides. A throw is a bounded hand
moving; how fast the ball leaves is the world's answer. A draw is a bounded hand
pulling; how far the string comes back is the bow's answer.

This document is the design and the record of what is built. The status of each
part is stated where it is described, and summarised at the end.

---

## 1. What a control may and may not do

- **No speeds are given.** Nothing sets a body's velocity at release. A throw is
  the hand's force over the hand's stroke; a loose is the limbs' stored energy
  going into the string and the arrow.
- **The hand is bounded.** 800 N of pull, 60 N m of wrist, and a moving mass of
  its own (2 kg, a demonstration value: a hand, forearm and part of an upper arm
  as felt at the hand). The strength has to move the hand as well as the thing,
  which is why a light ball leaves faster than a heavy one even when neither is
  too heavy to hold.
- **Work is measured, not inferred.** The engine counts the hand's force times
  the grip's motion on every kept step. A meter that says "you put 12 J into it"
  is reading that number.
- **Meters bind to measured quantities.** Draw is where the string actually is;
  energy is what this bow's own limbs hold; speed is what the body left with.
- **Previews never touch the live world**, are bounded in time, say what they
  leave out, and refresh when what they depend on changes.
- **An obstructed object is not forced through the world.** The hand pulls with
  what it has; a wall stops a throw the way it stops anything else.

## 2. One control language

Profiles name **semantic actions**, never keys. The page maps them through one
bindings table, and the contextual help is generated from that table — so the
help always shows the player's keys, and the chat never invents a keyboard
scheme for an object.

| Action | Default binding | Ball | Bow |
|---|---|---|---|
| Interact | E, or a click with an empty hand | Take hold / put down | Take up the bow (the string, arrow nocked) |
| Move view | mouse, drag, arrow keys | Throw direction | Where to shoot |
| Hold primary | left mouse held | Wind up — longer is a harder throw | Draw the string |
| Release primary | left mouse released | Throw | Loose |
| Secondary | right mouse | Lower the arm (cancel) | Let the string down |
| More actions | Tab | Place, drop | Take the arrow off, release a latch |
| Advanced | Alt + Interact | Grab exactly the part under the crosshair | Grab the bowstring itself |
| Turn, tip | Z X; T G; C V | A loose thing: turn it about the vertical; tip it away or back; tip it sideways (section 7) | — |
| Upright | U | Stand it on its longest side | — |
| Reach | mouse wheel | Hold it further out or nearer | — |
| Talk | / | Open the room's chat, which is told what you hold and look at | the same |

E used to move the view up; up is Space (as it was already) and down is Q. Only
the actions available **in the current state** are shown: an unloaded bow offers
loading, a bow whose string is cut says why it cannot be drawn.

## 3. The engine underneath

Two things a person does with their hands cannot be done a frame at a time from
outside: a throw is over in a tenth of a second — three frames at thirty a
second, so a host moving the hand would let its frame rate decide the throw —
and a draw is decided by how hard a hand can pull against what resists it. So
the engine makes the **stroke** itself, at the step's own rate. The C API is in
[api/c-api.md](api/c-api.md#the-hands-own-motions); the same operations are on
the Python binding, the line protocol and both live sessions.

- **`stroke`** — where the hand *wants* the grip travels along a path, at up to a
  requested speed and acceleration, and never faster than the strength can move
  the hand and the thing together. It is never more than 50 mm ahead of the
  grip: a hand is on the thing it holds. The hand damps motion relative to its
  own speed along the path. With `let_go`, the hand opens on the step the
  **grip** reaches the end. It ends `reached`, `let go`, `blocked` (the grip has
  stopped while the hand pulls with everything it has — for a bow, that is the
  draw), `gave up` or `cancelled`. It needs a hand that pulls: a wielded body,
  or a hauled one on a joint. A carried body is placement and is refused.
- **`hand`** — what the hand holds and how (`carry`, `haul`, `grip`), where it
  wants the grip, the force it applied, the **work** it has done since taking
  hold, the stroke's progress, and — once a stroke opens the hand — what it let
  go of, how fast that was going, and the work done on it by then.
- **`preview_stroke`** — the held body alone, with its own mass and inertia,
  pulled along the path by the same hand law a step uses, then its flight. It
  is always a preview of a *throw*: the hand opens as the grip reaches the end,
  whatever the request says about `let_go`, because a hand that keeps hold has
  no flight to show. (The line protocol once took `let_go` from the request,
  with `stroke`'s default of false, and so previewed a hand slowing to arrive
  at the end. The room drew its aim from that: a ball the arc said would leave
  at 4.7 m/s left at 14.7.) It cannot know what the stroke would bump into on
  the way, and says so.
- **`preview_flight`** — stepped the way the solver steps a free body: gravity,
  then the body's own damping (every live body carries 0.02 a second on its
  speed and spin), then the move, at the world's own step. Checked every 1/60 s
  against the solver's own shapes along the line of the centre. Exact ballistics
  came down 84 mm beyond a real throw over 11.5 m, which is why it is not that.

**Measured** (`tests/hand_stroke_tests.cpp`, the real engine), one full-effort
stroke — 0.8 m, the hand's top speed 20 m/s — given to three balls:

| Ball | Mass | Left the hand at | Hand's work / energy the ball gained |
|---|---|---|---|
| rubber, 70 mm | 0.28 kg | 20.8 m/s | 60.8 J / 60.8 J |
| iron, 100 mm | 3.53 kg | 15.0 m/s | 397.1 J / 396.5 J |
| iron, 200 mm | 34.8 kg | 4.3 m/s | 328.8 J / 327.1 J |

The heaviest left under the 4.6 m/s that what is left of 800 N after holding it
up could give it over 0.8 m. The lightest left a little faster than the hand's
own top speed — 20.8 against 20 — because the grip gives back what it took up
as the ball caught up with it. The stroke preview's release speed matched each
throw to five figures, and the flight preview came down within 1.3 mm of the
real ball over 11.5 m. Hauling a block against a spring, the draw stopped at
199.98 mm on 4000 N/m and 99.99 mm on 8000 N/m, where 800 N balances them at 200
and 100.

**The aim arc is the throw** (playground/world.js). The page draws its arc from
`preview_stroke` of exactly the stroke it would throw — `throwStroke` lets go at
its end — and when the button comes up it throws the stroke the arc on screen
was drawn from, not one made afresh: a preview is a fifth of a second old by
then, and the engine starts the stroke from wherever the thing is when it is
thrown. Measured on the page in the bench room, with the room's own requests and
replies recorded: held steady at a full wind-up, a 0.25 kg iron marble, a
3.27 kg rubber ball (twice), a 5.6 kg oak block and an 8.6 kg iron ball each
left the hand at exactly the previewed velocity, and each centre line came down
within 10 mm of the ring. Each first touched the floor its own size short of the
ring (70 to 240 mm), because the ring marks where the centre line meets the
ground. Let go halfway through the wind-up, the rubber ball came down 0.10 m
along and 0.13 m across from the ring; with the view turned 12 degrees 60 ms
before letting go, 0.40 m short and 0.13 m across. A throw made afresh came
down 1.19 m past the ring and 2.25 m to the side of it, respectively. What a
thing does once it is down is the floor's business: on the bench room's floor
the balls went on rolling for 60 to 117 m and the block slid 7 m.

**Status:** engine implemented on `agent/interaction`; the page's use of it is
increment 1, below.

## 4. The components

A small vocabulary, combined per object:

| Component | What the hand does | Meter (measured) | Aiming guide | Status |
|---|---|---|---|---|
| carry | places it where it is put (no force), beside the view | where it is, what is under it | drop line and landing ring | exists; held beside the view since section 7 |
| place | lowers it onto what is below with a stroke that arrives, then lets go | height above support | drop line and landing ring; placement ghost later | section 7 |
| turn | the wrist turns it towards what the keys ask, with at most 60 N m | how it stands | — | section 7 |
| throw | winds up, then strokes forward and lets go at the end | wind-up reached; after: speed left with, work done | preview arc and first impact | increment 1 |
| draw-and-release | hauls the draw point back; lets go to loose | draw reached; energy in this bow's own limbs; pull | aim line and predicted arrow flight (approximate) | increment 2 |
| swing | a bounded grip swung by the view | edge speed | swept volume | exists as blades; profile later |
| rotate, slide, activate | haul a hinge, a slider, a latch | angle, travel, state | rotation arc | later |

## 5. The profile

A profile is data, stored with the scene the way blades are, validated where it
is written, and carried to the page with the room.

```json
{
  "object": "courtyard bow",
  "parts": ["bow grip upper", "bow grip lower", "upper limb tip", "lower limb tip",
            "bowstring", "arrow"],
  "templates": ["draw-and-release"],
  "grips": {"draw": {"part": "bowstring", "at_mm": [0, 0, 0]}},
  "bindings": {"draw_part": "bowstring", "nock": "the one-way fixing the arrow sits on",
               "limbs": ["the upper limb", "the lower limb"],
               "projectile": "arrow", "draw_axis": [1, 0, 0], "max_draw_mm": 500},
  "preconditions": ["string attached", "arrow on the string"],
  "aim": "arrow flight",
  "feedback": ["draw_mm", "stored_j", "pull_n"],
  "help_poses": ["hold", "prepare", "release"]
}
```

Grip anchors are in the part's own coordinates, so they follow the part.
Bindings name joints and parts; validation refuses a profile that names a part
or joint that is not there, a template the engine cannot do, or a projectile
that is not what its nock lets go of. Every object without a profile keeps the
generic **carry/place**, and every loose object a hand can lift gets **throw**.

**Status:** increment 2, the bow, below. The courtyard's bow carries a
`draw-and-release` profile, stored as `interactions` in the room and checked
where the room is written. The checks are:

- its parts are in the room;
- the draw part is one of them;
- the limbs are real elastics;
- the nock is a real ONE-WAY fixing (`comes_off_n`), whose axis lets the
  projectile off down the shot.

A profile that names something that isn't there, or tries to state a speed, is
refused.

Since increment 3 those rules are one set, `mcp/interaction_profiles.py`, and
the room and the MCP's `interaction` tool both hold a profile to it. A room the
chat changes is written back with its profiles. It used to be written back
without them, so the first thing the chat changed anywhere in the courtyard --
a crate by the gate -- left the bow with no controls, and the page offered to
carry its string about like a stick. A change that takes away something a
profile names withdraws that profile at the call that made the change, and the
answer says which and why; the room is not refused the change.

### The bow, measured

A nock is one-way, and the engine now has one. The string pushes the arrow as
hard as it has to, and holds it back with no more than the nock's grip. The
arrow leaves at the step where keeping it on would take more than that grip,
and nothing in the page lets it go. The page's earlier approach was to release a
two-way fixing "at brace", but the page ticks thirty times a second. By the time
it looked, a string doing 8.6 m/s was 290 mm past brace and on its way back, and
the arrow went with it: it never got further than x = −1.30.

In the page, headless Chrome against the live engine, the controls are: E on
the string takes up the bow; hold the left mouse to draw; let go to shoot.

| | Measured |
|---|---|
| draw, 2 s of left mouse | 436 mm; 42.2 J in the limbs; the hand pulling 214 N; the meter read off the engine |
| loose | the page opens the hand and does nothing else; "arrow came off bowstring" |
| the shot | the page said 8.6 m/s, 58% of what the limbs held -- the fastest it saw, the arrow and the string together; it left the string at 8.30, 55% (section 6); flew 1.6 m down the range and bounced off the gate |
| again, no arrow | "No arrow on the string"; drawn to 430 mm and let down with the right mouse |
| clock | 2.28 s of room time over 2.25 s of wall clock |

Through the same live pipe (`tests/world_room_tests.py`):

- drawn 147 mm, the limbs held 2.3 J, and the arrow came off 65 mm past brace
  at 1.89 m/s;
- drawn 291 mm, they held 15.6 J, and it came off 97 mm past brace at 5.24 m/s.

While drawn, the nock carried 1 to 7 N of its 20.

Three things in the engine were found wanting on the way, and each was fixed in
the engine rather than in the page:

- **The one-way fixing.** `banjo_fix_one_way`, and `comes_off_n` on every
  fixing API (see [api/c-api.md](api/c-api.md)).
- **A stroke that keeps hold now arrives at its end.** It slows at the rate it
  sped up. One that stopped dead at the end of a draw left the string ringing
  from −0.38 to +0.24 to −1.57 m/s within nine steps.
- **A taut rope stays taut.** Jolt's distance limit only engages when a rope is
  at or beyond its length as the step starts. A rope pulled tight sits right on
  that line, so being nudged a hair inside it made the rope do nothing for a
  whole step. Measured: a string rope carrying 110.7 N read 0 for one step, and
  the 45 g limb tip it held against a 307 N limb spring left at 6.8 m/s, every
  few dozen steps, with nobody touching anything. The arrow used to be welded to
  the string, and its mass hid this.

In the engine, a 4 kN/m and an 8 kN/m bow drawn 200 mm with the same hand
shoot the same arrow at 1.69 and 2.61 m/s. A 4.2 kg arrow leaves the 4 kN/m
bow at 1.94 m/s, against 3.28 m/s for a 1.05 kg one, and carries more momentum.
In the page there is one bow so far. A second stiffness is the crafting
transaction's job (section 6).

## 6. The crafting transaction

**Build the object → attach its profile → validate the references and what the
engine can do → trial the actions → return the object with its controls.** The
trial runs in a scratch world, never the live one: a bow is drawn with the
bounded hand and loosed, and what it stored and what the arrow left with are
returned as numbers. After any change — a part removed, a string cut — the
profile is revalidated, and an action whose parts are gone is withdrawn with the
reason.

**Status:** increment 3, measured below.

The MCP's `interaction` tool is the transaction: build the thing with the other
tools, then say how it is used ([api/mcp.md](api/mcp.md#things-a-person-uses)).
It is held to what is BUILT -- the calls that made the joints, not what the
world is doing, so a nock an arrow has just come off in a run is still the bow's
nock -- and then tried in a scratch world opened from what was built, holding
the object and whatever is joined to it. There the engine's own 800 N hand draws
the draw part back along the draw, at the draw's speed, until the limbs balance
it or it reaches `max_m`; holds it a quarter of a second; and lets go. What comes
back is what was drawn, the pull, what the limbs held and what the projectile
left with at the step the nock let it go, with `sound: false`, and why, when the
engine did not follow the shot.

### The trial, measured

The chat's guide carries a bow as a recipe -- the courtyard's geometry at the
origin: 6 kN/m limbs on 45 g tips, a 672 g oak arrow on a 20 N nock -- built and
tried through the MCP's own tools. The same hand on other limbs and to other
draws:

| | drawn | pull | limbs held | the arrow left | share |
|---|---|---|---|---|---|
| 3 kN/m, asked for 0.45 m | 443 mm | 107 N | 21.8 J | 5.58 m/s | 48% |
| 4.5 kN/m | 440 mm | 160 N | 32.2 J | 7.11 m/s | 53% |
| 6 kN/m, the courtyard's | 436 mm | 214 N | 42.2 J | 8.30 m/s | 55% |
| 8 kN/m | 432 mm | 285 N | 54.9 J | 9.67 m/s | 57% |
| 12 kN/m | 423 mm | 423 N | 78.6 J | 11.87 m/s | 60% |
| 20 kN/m | 406 mm | 686 N | 119.1 J | 15.48 m/s | 68% |
| 6 kN/m, asked for 0.20 m | 195 mm | 77 N | 5.2 J | 2.10 m/s | 28% |
| 6 kN/m, 0.30 m | 291 mm | 140 N | 15.6 J | 4.72 m/s | 48% |
| 6 kN/m, 0.40 m | 387 mm | 197 N | 32.0 J | 7.20 m/s | 54% |

A trial takes 0.05 to 0.08 s to compute.

The page used to say the courtyard bow's arrow left at 8.6 m/s. That was the
fastest it saw: the arrow and the string ran together at 8.59 m/s, and over the
two steps the arrow slid off the nock, its 20 N grip took 0.29 m/s back. The page
now reports the arrow's speed along the shot at its first report after the arrow
is clear of the string.

The trial found the engine wanting a fourth time. Before it, the arrow was
stopped dead on the string on 13 of these 19 draws and stiffnesses -- 5.58 m/s to
−2.54 in one step, still nocked, with nothing touching it -- and it was not the
bow. Jolt sweeps a fast body as its shape shrunk by its convex radius; every
moving box here had none, so one lying on something -- the arrow on its rest --
started its sweep already touching it, and the sweep reported a hit along the
way it was going. Every moving box and hull now has round edges, 2 mm or a tenth
of its thinnest half if that is less, inside its authored size. Anything sliding
fast over what it rested on was stopped the same way: a box thrown along a plank
went from 7 m/s to −4.6 in one step, and now slides on, losing 0.021 m/s a step,
which is friction.

In the page, headless Chrome against the live engine, the chat was asked for
two things in the courtyard and the bows were then used the way a person uses
them -- E on the string, hold the left mouse, let go:

| | Measured in the page |
|---|---|
| a change elsewhere | "Put a small oak crate on the floor a metre in front of me": done, the room reopened, and the courtyard's bow kept its controls |
| the courtyard's bow, drawn 1 s | 352 mm; loosed, "The arrow left at 7.6 m/s — the limbs held 34.7 J and 56% of it went into the arrow" |
| crafting | "Build me a second bow beside the courtyard bow, just like it but with stiffer limbs, 8 kN/m": `duplicate` of its 8 parts with the springs at 8 kN/m, 0.8 m across its line of fire, in 28 s; the chat gave the trial -- 0.432 m, 285 N, 54.9 J, 9.68 m/s |
| the stiff bow, drawn 2 s | 432 mm by 285 N, 54.9 J; the arrow left at 9.7 m/s, 57%, and flew 9.3 m down the courtyard |
| the courtyard's bow, drawn 2 s | 436 mm by 214 N, 42.2 J; the arrow left at 8.3 m/s, 55%, into the gate |
| clock | 2.77 s of room time over 2.77 s of wall clock, shooting the stiff bow |

The first time it was asked, before `duplicate` existed, the chat built the
copy from the recipe by hand, got the offsets wrong and stopped halfway with its
parts overlapping ([api/mcp.md](api/mcp.md#things-a-person-uses)).

### The meter, read off the step

The meter's draw is where the string is in each step's reply. Its joules were
the limbs' `stored_j` from the list of joints, and a step carries that list only
when the SET of joints changes, so the page asked for it at most four times a
second while a bow was held. The joules trailed the millimetres by up to 250 ms,
which is 100 mm at the page's 0.4 m/s, and a loose took its joules from the
same stale read. Now each elastic's reading (`metres`, `force_n`, `stored_j`)
comes with every step reply it changed in, trimmed the way the bodies are
(`describe()` in `tools/live_world_run.cpp`). The page folds it into its joints
before the meter or a loose reads them. Nothing on the page works out a joule.

In the page, headless Chrome against the live engine, the courtyard's bow was
drawn at 0.4 m/s. The meter's joules, against the MCP `interaction` trial's at
the same draw:

| drawn | the trial | the meter, before | the meter, after |
|---|---|---|---|
| 291 mm | 15.63 J | 4.98 J | 15.62 J |
| 339 mm | 23.10 J | 16.36 J | 23.10 J |
| 387 mm | 32.01 J | 16.36 J | 31.96 J |
| 436 mm | 42.17 J | 33.71 J | 42.14 J |

- **Every frame, after:** in two draws, every frame from 280 to 440 mm was
  within 0.4% of the trial's curve.
- **Loosed at full draw:** "The arrow left at 8.3 m/s — the limbs held 42.2 J
  and 55% of it went into the arrow". The trial's share is 55.1%.
- **Loosed mid-draw, before:** let go once the meter passed 350 mm, the string
  was 357 mm back. The loose said the limbs held 12.5 J (the trial's curve
  there: 26.3 J) and that 113% of it went into the arrow.
- **Loosed mid-draw, after:** 26.58 J at 359 mm, the same to the last digit as
  the engine's own reply to the release, and 54%.
- **The string taken by itself (Alt+E) and hauled back:** its panel line said
  "Drawing bowstring — N mm back, … J in the limbs" on 115 of 115 frames, within
  1.4% of the trial's curve from 250 mm on. Before, it said so on 16 of 115,
  and "Holding bowstring." between its polls.

| clock and wire, draw and shot | before | after |
|---|---|---|
| room clock over wall clock | 0.991, 1.005 | 1.002, 1.003, 0.989 |
| frames a second | 59.8 | 60.0 |
| `joints` requests while drawing | 1.4 to 1.8 a second, 5.4 KB each | none |
| step reply while drawing, median | about 2.3 KB | about 2.4 KB |

On the runner's own pipe a step at brace is the same 192 bytes either way: a
bow at rest sends no readings. `tests/live_wire_tests.py` draws the bow through
the pipe and holds the room's folded readings to the engine's `joints` answer
after every step.

## 7. Holding, turning and setting down

The owner, 2026-09-13: a thing taken up could cover the whole view, and there
was no way to change how it was held -- "I have a pillar and I want to make it
stand up". Both of the options the owner named are built: the hand turns what
it holds, from the keys, and "/" asks the room to.

**Where it is held.** Beside the view, never in front of it: low and to the
right, 27 degrees off the line of sight, at a distance that grows with the
thing. A ball is held where a ball always was, 0.56 m out; a 0.8 m pillar 1.08 m
out -- 2.6 times its bounding radius, which stops it 4 degrees short of the
crosshair. The mouse wheel takes it further or nearer, 0.4 to 3 m, and the hand
takes as long to get it there as its strength says. While it covers the middle
of the view anyway -- a big crate brought in close -- it is *drawn* see-through:
its material is swapped for the one frame it is drawn in, and the body in the
world is the same body. While something is held the help sits to the left of
the crosshair; at the bottom of the view it was covering what was held, and a
pillar held lying down could not be seen at all.

**Turning it.** Z X turn it about the vertical, T G tip it away or back, C V tip
it sideways, and U stands it upright: its longest side vertical, by the smallest
turn from how it is. The keys never turn the thing. They turn what the hand
*wants* -- kept relative to the way the person faces, so a thing held across the
view stays across it as they turn round -- and the hand asks the engine for that
through `hand_q`, the wish its grip law turns towards with at most the wrist's
60 N m: the same law that aims a sword. A loose thing a hand can hold up (under
73 kg) is held by that grip; a heavier one is carried, which is placement, and
cannot be turned by the hand -- a turn key says so, and offers the room.

The pace of the wish is the one thing the page decides, and it is decided from
the engine's numbers. The wrist is bounded, so a wish it cannot follow is an
overshoot. Measured on the live engine: a 49 kg concrete pillar asked to stand up
all at once swung 74 degrees past upright; asked at 1.2 to 3 rad/s, easing in over
the last part, it stood up with no overshoot at all. A 74 kg pillar 1.2 m long --
four times the inertia -- stood up at 1.2 rad/s, overshot by 14 degrees at 1.8
and fell over at 3. So the page asks at sqrt(0.2 x 60 N m / the thing's largest
moment of inertia), at most 2.5 rad/s, easing into the end over 0.3 s
(`interaction.js`, turnPace).

**Setting it down.** E lowers it with the hand's own stroke straight onto what is
under it -- the drop line and its ring say where -- and the stroke now
*arrives*: it slows as it comes to where the thing rests and keeps hold, and the
page lets go once the engine says the stroke has reached its end. It used to let
go on the way down, at 0.8 m/s, which drops a pillar onto its end. How far a
thing reaches below its middle is worked out from how it is turned; it was half
its own height whichever way up it was, so a pillar held on end was lowered as if
it were still lying down. A carried thing, being placed, is placed lower and lower
onto what is under it and let go of there, rather than dropped from wherever it
was carried.

**Asking the room.** "/" opens the room's chat from anywhere but a text box. What
is sent carries what the person holds (`holding`), what they are looking at,
where they stand and which way they face, and the chat's guide says "this" is
what they hold, or else what they look at. The MCP's new `turn_object`
([api/mcp.md](api/mcp.md#turning-a-thing)) stands a thing upright, or lays it
down, at a point: an edit that the engine holds to what the world would do with
it. Nothing may share its space, what is under it has to be under its middle
and flat, and the world is run until it is still -- from a third of a degree off,
so that a balance only an exact run could keep is found out -- and it has to be
standing as it was put.

**Measured in the page** (headless Chrome over CDP, the keys sent as keys, my
server on port 8776, the room built by its own chat):

| | Measured |
|---|---|
| "Put a stone pillar lying on the ground in front of me" | a concrete pillar 0.16 x 0.16 x 0.8 m, 49.2 kg, lying on the floor in front, in 12 s |
| E, then Z held 0.5 s | taken by the grip, held 1.08 m out; turned 44 degrees about the vertical |
| U | its long side 0.19 degrees from vertical, in the hand |
| E | set down, at rest 1.0 s later, 0.19 degrees from vertical |
| "/", then "Turn this vertical and set it in front of me", looking at it lying down | `turn_object`, answered in 8 s: at rest 1.00 m straight ahead of the camera, 0.00 degrees from vertical |
| clock | the page's own frame reports, 99-101% of wall clock throughout |

Through the live pipe (`tests/world_room_tests.py`, TheHandTurnsWhatItHolds): the
pillar was held upright at 0.18 degrees with no overshoot, and set down and let
go at 0.00 degrees, sliding nothing. Asked all at once it overshoots by more than
20 degrees, which is the wrist being bounded.

**Status:** built. Not yet: a placement ghost (where it will stand, drawn before
it is put down); turning a thing too heavy to hold up, which a person does by
walking one end up; anything on a joint, which turns the way its joints let it.

## 8. Pose help

A small rotatable demonstration of the **actual object**, fitted to its own
geometry, with ghost hands in three stages: **Hold → Prepare → Release**. Ghost
poses are instructional and drawn as such; the real object may lag or be
blocked. Shown briefly on first use, and on the help key afterwards.

**Status:** increment 4.

## 9. Status and plan

1. **The throw** — the engine's stroke, hand work, hand mass and previews
   across every API; the page's input state machine, contextual help, wind-up
   meter and preview arc; every loose, liftable object throwable.
2. **The bow** — draw-and-release on the courtyard bow through the same state
   machine: take up the bow from any of its parts, draw by holding primary, a
   meter that reads this bow's own limbs, let down, and the states an unloaded
   or broken bow is in.
3. **Crafting** — profiles through the MCP (`interaction`, with its trial),
   profiles kept through the chat's changes and withdrawn with the reason, the
   chat crafting a bow of a different stiffness -- `duplicate` of the
   courtyard's, its springs at 8 kN/m -- and QA through the chat in the page
   (section 6). Measured.
4. **Holding, turning and setting down** — what is held is held beside the
   view, further or nearer on the wheel, and drawn see-through only while it
   covers the middle; the hand's wrist turns it from the keys, at a pace worked
   out from its own inertia; U stands it upright; it is set down by a stroke
   that arrives before the hand lets go; "/" opens the chat, which is told what
   is held, and the MCP's `turn_object` stands a thing up at a point (section
   7). Measured.
5. **Pose help**, a placement ghost, and the remaining components.
6. **A tool that digs** — swing-and-lever, on `agent/progression`: a tool with
   a point ([ground work](ground-work.md)) is taken up by any of its parts, by
   the grip its point was given with, and held ready, point down. A click
   swings it -- the engine plans and makes the stroke, raised back over the
   shoulder and round it so the point meets the ground under the crosshair
   along its own axis -- and the ground decides how far it goes in. With the
   point in, the secondary button levers it about where it went in and draws it
   out, and what the pry breaks out is carried. The profile names its `parts`
   and its `tool`, never a speed or a depth; the MCP's `interaction` tries it in
   a scratch world, into soil, levered, and onto rock (`picks.js`). Measured.

Acceptance, from the owner: a new player can pick up a ball or a bow and use it
without asking the chat, and heavier balls and stiffer bows behave physically
differently.
