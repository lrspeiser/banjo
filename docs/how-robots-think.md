# How robots think

A plan, 2026-09-24. Nothing here is built yet except what the "Where we are"
section says is built. It answers one question the owner asked: how can a
language model give machines behaviour in the world without making the world
slow?

## The measurement that settles the question

A room with one thinking robot, on flat ground, going to a stool and sitting
down (`/world?scene=tests-sit`):

| what is in the room | wall time for 10 s of world | of realtime | a step |
|---|---|---|---|
| the robot, no program declared at all | 0.29 s | 34.0x | 122 us |
| the program declared, turned off | 0.29 s | 35.1x | 119 us |
| the program running | 0.29 s | 34.2x | 122 us |

The three are the same number. **The thinking costs nothing that can be
measured.** Adding robots:

| robots, all going to their own stool | bodies | of realtime | a step |
|---|---|---|---|
| 1 | 7 | 33.1x | 126 us |
| 2 | 13 | 26.7x | 156 us |
| 4 | 25 | 20.1x | 207 us |

All four sat down. Each robot after the first costs about 27 us a step, and that
is the price of its six bodies and five pins -- the physics -- not of its
thinking. The realtime gate wants 1.1x, which leaves about 3,800 us a step to
spend, so on this evidence the processor would carry something like a hundred
robots of this shape.

It will not get the chance: `precise_rigid.MAX_BODIES` is 32, so a room holds
five robots of this shape and nothing else. **The ceiling on how many machines
can think in a room is the body cap, not the thinking.**

So the problem is not "make the AI fast". It is **keep it this way**.

## Three rules

1. **Two clocks, never crossed.** The engine decides before every step, 240
   times a second. A language model answers in seconds and costs money every
   time. A model must never be inside the step loop -- not once, not for one
   robot, not "only when something interesting happens". A model's job is to
   WRITE the behaviour; the behaviour runs.

2. **A behaviour may only tell motors what to try.** It reads what its machine
   measures and writes what its controllers are told. It cannot move a body, set
   a pose or put a thing anywhere. Whether the machine arrives, what it hits on
   the way, and what happens when it leans on something are the world's answer.
   That is already true of the two behaviours there are.

3. **What a behaviour costs is measured and refused, not hoped for.** The same
   discipline the workshop's gate already applies: the cheapest network panel
   priced at 124x realtime and was refused, and said so. A behaviour that will
   not fit in the budget is refused before it runs, with the number.

## Where we are

Two behaviours exist, both written in C++ inside `LiveWorld` and both chosen by
a `kind` on a machine's program (docs/machine-world.md):

- **"roam"**: go forward; turn away from water a sensor sees; back off and turn
  where the wheels make no progress; turn downhill off ground too steep; rest
  when the battery is low and go on when the sun has charged it.
- **"sit"**: go to a thing you are told the place of, and hold a pose when you
  get there.

Both are state machines. Between them they use about a dozen readings and issue
one kind of command. Neither needed a loop, a list, or arithmetic beyond
comparing two numbers. That is the evidence for what comes next.

## What a behaviour should be made of

Four ways it could go, and why the third one is wrong for now:

**a. Hard-coded in C++, as today.** Fast, safe, and a person can read it. But
only a programmer can add one, and it takes a rebuild: the model cannot write
one while somebody is playing.

**b. Declared as data, run by the engine.** The same state machine, written down
as states, conditions over named readings, and the commands each state issues.
A model writes this kind of thing well. It cannot crash the engine, cannot loop
forever and costs a handful of comparisons. It saves and is carried like a
program is now, and the panel can show it in plain English. What it cannot do is
anything the vocabulary does not have a word for.

**c. A small sandboxed machine** -- a stack VM or an expression language with an
instruction budget a step. More it can say; still bounded; more to build, and
harder for a person to read.

**d. A scripting language embedded in the engine** (Lua, Wren, a JS engine).
The most a model could say, and the most familiar to it. But an interpreter
running for every robot every step costs real time, sandboxing and repeatability
are work, and a saved world has to save the interpreter's state too.

**The recommendation is (b), with (c) held back as an escape hatch and only if
(b) provably runs out.** Building (d) first would buy expressiveness that nothing
has needed yet and spend a budget we have just measured as free.

## What a behaviour may read and say

This is the real design work, and it should be grown from what the two
behaviours already use rather than invented.

**What it reads** -- every one of these is already measured every step:

- of itself: how fast it is going across the ground, the slope it faces and the
  slope across it, how long it has been doing what it is doing, how far it has
  turned in it, and its battery's share of full.
- of a thing it has been told about: how far away it is across the ground and
  which way that is off its nose.
- of each of its controllers: the shaft's turns a minute, whether it stopped for
  want of progress, and what stands in its way in words.
- of each of its sensors: what it reads, whether it sees what it was fitted to
  see, and which side of the machine it is on.
- of the room: whether the sun is up, and the hour.

**What it says** -- and this is the whole list:

- to one of its controllers: on or off, a direction (-1, 0, 1) and a drive
  setting from 0 to 1.

**What a state is**: a name, a sentence saying why it is in that state, the
commands it issues while it is, and a list of "when THIS, go to THAT, because
'...'".

**The first proof is to write "roam" and "sit" in that form and check the engine
tests still pass with the same numbers.** If a declared behaviour cannot
reproduce them, the vocabulary is wrong, and that is worth knowing on the first
day rather than after a model has been wired to it.

## Where the model sits

Three places, all of them outside the step loop.

**1. Writing.** The chat writes a behaviour from what the person asked for --
"make it go to the stool and sit down" -- against the vocabulary above. This is
the existing `set_program` tool grown up: it names a kind today, it would write
states tomorrow.

**2. Proving.** Nothing is installed until it has been run. A behaviour comes
with a **trial**: a room to run it in, where everything starts, and what must be
true at the end -- "within 0.7 m of the stool's middle, the end of its torso
resting on the seat, the stool moved less than 150 mm". That is exactly what
`tools/build_sit_room.py` does by hand today, and exactly the shape the Workshop
bench already has: check it, make it, install it. A behaviour that fails its
trial is reported with what went wrong, not installed.

**3. Repairing.** A stuck machine already says why in plain English -- "it could
not come round where it stood", "its wheels made no progress", "its battery is
low and its panel is in the shade of the ground". That sentence, with the trial,
is most of a good prompt. The person clicks "ask it to fix this"; the model edits
the behaviour; the trial runs again.

**What this costs to run.** A call happens when a person asks for one. Never on
a timer, never per robot, never per step. A behaviour written once goes in the
library: the fiftieth machine that roams costs nothing at all.

## The order to build it in

1. **Declared behaviours, with "roam" and "sit" re-expressed as data.** Proof:
   `banjo_rover_roam_tests` and `rover_room_tests` pass unchanged, and the cost a
   step is still lost in the noise -- measured, not assumed.
2. **A behaviour's trial.** A behaviour carries the room, the start and the end
   conditions that prove it. `tests-sit` becomes the first one.
3. **The chat writes one.** `write_behaviour` and `try_behaviour` beside the
   tools it has; the chat authors something new -- follow the person, fetch a
   thing and bring it back -- and it passes its trial before it is offered.
4. **A library and a price.** Behaviours are saved, shared between machines, and
   costed: a room that would miss the gate is refused with the number.
5. **Only then, and only if something real cannot be said in the declared form,
   the escape hatch.**

## Decisions for the owner

- **D1. What does a person see when they ask for a behaviour?**
  - The chat writes it and shows its trial running -- the robot doing the thing
    in a scratch room -- before it is installed. *Recommended: nothing reaches
    the world until it has been watched doing the thing.*
  - It goes straight in and you watch it in the room you are standing in.

- **D2. Who may edit a behaviour by hand?**
  - A panel that lists its states in plain English and lets the person change
    the numbers in them. *Recommended: the numbers are where the tuning is, and
    changing one should not need a model.*
  - The chat only.

- **D3. Does a stuck machine ask for help by itself?**
  - No. It says why it is stuck and waits to be asked. *Recommended: no timer,
    no surprise spend.*
  - It may ask once, and then waits.

- **D4. The body cap.** A room holds 32 exact bodies, so five robots of this
  shape. The processor would carry many more. Raising the cap is a separate
  piece of work, and worth doing before "a small ecosystem" of machines is
  attempted (docs/machine-world.md, "After the hoist").
