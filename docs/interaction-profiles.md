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
  "bindings": {"draw_part": "bowstring", "latch": "the nock fixing",
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
that cannot sit on the latch. Every object without a profile keeps the generic
**carry/place**, and every loose object a hand can lift gets **throw**.

**Status:** schema and validation are increments 2 and 3.

## 6. The crafting transaction

**Build the object → attach its profile → validate the references and what the
engine can do → trial the actions → return the object with its controls.** The
trial runs in a scratch world, never the live one: a bow is drawn with the
bounded hand and loosed, and what it stored and what the arrow left with are
returned as numbers. After any change — a part removed, a string cut — the
profile is revalidated, and an action whose parts are gone is withdrawn with the
reason.

**Status:** increment 3 (an MCP tool the chat uses to craft, and QA through the
chat).

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
3. **Crafting** — profiles through the MCP, the chat crafting a bow of a
   different stiffness, and QA through the chat.
4. **Pose help**, and the remaining components.

Acceptance, from the owner: a new player can pick up a ball or a bow and use it
without asking the chat, and heavier balls and stiffer bows behave physically
differently.
