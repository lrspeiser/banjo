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
  cannot know what the stroke would bump into on the way, and says so.
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

**Status:** engine implemented on `agent/interaction`; the page's use of it is
increment 1, below.

## 4. The components

A small vocabulary, combined per object:

| Component | What the hand does | Meter (measured) | Aiming guide | Status |
|---|---|---|---|---|
| carry | places it where it is put (no force) | where it is, what is under it | drop line and landing ring | exists |
| place | lowers it onto what is below with a stroke, then lets go | height above support | placement ghost and support | planned |
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

## 7. Pose help

A small rotatable demonstration of the **actual object**, fitted to its own
geometry, with ghost hands in three stages: **Hold → Prepare → Release**. Ghost
poses are instructional and drawn as such; the real object may lag or be
blocked. Shown briefly on first use, and on the help key afterwards.

**Status:** increment 4.

## 8. Status and plan

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
4. **Pose help**, and the remaining components.

Acceptance, from the owner: a new player can pick up a ball or a bow and use it
without asking the chat, and heavier balls and stiffer bows behave physically
differently.
