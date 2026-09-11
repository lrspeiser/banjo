# A world that keeps running

`runTileImpact` is a batch: build, fracture, hand off, settle, write a recording,
return. Everything it knows dies with the call. That is why the playground played
a film — to move something you edited the scene and ran the whole thing again.

`LiveWorld` holds the rigid world open instead: `step(dt)`, `poses()`, `grab()`,
`moveHeld()`, `release()`, `impacts()`, `breakable()`, `fracture()`.

It is **additive**, not a refactor. `runTileImpact` is 1,333 lines that fifteen
suites depend on, and every piece the live lane needed was already callable on its
own — `buildTileImpactSetup`, `findConnectedComponents`,
`buildFragmentRepresentations`, `JoltWorld`. So the two lanes share the machinery
and the batch path was not touched.

## What it costs

| | |
| --- | --- |
| one rigid step | **0.0019 ms** (a 60 Hz frame is 16.7 ms) |
| one break | **~0.33 ms per cell** — 334 ms for a 450-cell pane |
| server round trip | 0.9 ms |
| the whole loop, pane hidden and throttled to ~1 Hz | **1.16x realtime** |

The rigid phase has about 8,700x more headroom than a frame needs, which settles
the question the earlier measurements pointed at: **live is not limited by the
rigid physics.** It is limited by the transport, and then only barely.

A break is three orders of magnitude more expensive than a step, which is why
`fracture()` is deliberately **not** automatic inside `step()`. A host has to
choose when to pay it — on a worker, over a held frame, or not at all — and
hiding it inside `step()` would make a frame budget meaningless.

## Four things that had to be true at once

Each was wrong on its own first, and each looked like "the physics is broken".

**1. The island has to hold both bodies.** Entered alone, after the contact, a
body is a free-flying object with a uniform velocity and no stress anywhere in it.
It cannot break however hard it was hit — measured, as 171 ms of lattice that
produced one piece. Both bodies are cut from the same parent lattice, so the
island is simply the union of their cells.

**2. The step has to be taken back.** Jolt resolves a contact inside the step, so
by the time it is reported the energy has already gone into bouncing the two
apart. `step()` runs inside a reversible trial and **rejects** any step that would
break something, leaving the world one step short of the impact with the closing
speed intact. `steppedBack()` says so and the clock does not advance.

**3. Each cell keeps its own velocity.** `buildFragmentLattice` places every cell
with ONE rigid pose, because it was written for one fragment — position,
orientation *and* velocity. A two-body island arrived with the struck body's
velocity on both: the ball in exactly the right place at exactly the wrong speed,
closing speed zero, and 2,174 substeps later nothing broken.

**4. The window has to cover the step it replaces, and the calm exit must be off.**
The world is a rigid step short of contact, so a 3 ms window runs out while the
ball is still in the air; and the calm rule stops a run once nothing is near
failing, which is exactly the state a re-entry starts in.

## The threshold is a lower bound

`admitRefracture` is a **necessary** condition, from a deliberately generous spall
argument. Clearing it means a break is *possible*, not that one happens:

```
a 100 mm iron ball onto a 300 x 40 x 300 mm glass pane
  dropped 10.00 m: 13.9 m/s (threshold 4.51) -> 90 pieces
  dropped  1.50 m:  5.4 m/s (threshold 4.51) -> 1 piece, it holds
```

Both rows are asserted in `tests/live_world_tests.cpp`. A test that only checked
the hard case would let "admitted" be read as "breaks", which is the derivation
backwards — and several hours went into chasing a bug that was this misreading.

## A grab is a kinematic hold, not a constraint

`pinToWorld` makes a world-fixed constraint with `mAutoDetectPoint`, which anchors
wherever the body was when it was made and drags a moved body straight back. The
first attempt held a ball perfectly still at the position it was grabbed from,
ignoring every move. Re-asserting the pose after each step has no such memory, and
it leaves a dragged object able to push what it runs into, which a pinned one
would not.

## Reaching it from the playground

`banjo_live_world_run` holds one world open and speaks JSON over stdin and stdout,
a line at a time; `playground/live_session.py` owns that process for a session and
`/api/live/open` and `/api/live/act` expose it. One world at a time, because each
is a physics engine with the scene resident in it.

Two things the browser forced:

**The loop paces on elapsed time.** A fixed number of steps per tick ties the
scene's clock to the browser's timer, and a browser throttles a tab it is not
showing to about 1 Hz — the scene then crawled at a sixtieth of real time for a
reason that had nothing to do with the engine.

**A body with no primitive is drawn as its cells.** A join is a union that no box
or sphere describes; a piece that broke off something has cells that ARE its
surface. Drawing those from a bounding box rendered the hollow bowl as a solid
block. They are one instanced mesh carried by the body's own pose, so it stays one
pose a frame on the wire and one draw call on screen — and the cells travel only
when the set of bodies can have changed.

## Then the pause moved to the wire

Taking the fracture off the caller's thread fixed the engine and the room still
stuttered. The engine was not the thing left to blame: paced exactly as the
browser drives it -- thirty replies a second, fractures and all -- the slowest
tick was 34 ms and nothing blocked. What was left was the size of a reply.

Every reply carried every body. A room that has shattered holds two hundred and
fifty of them, and a step reply measured **259 KB**. Thirty times a second is
7.8 MB/s for the browser to fetch, parse and walk, to be told what it already
knew: of those two hundred and fifty bodies, four were moving. The rest were
lying still on the floor being re-sent a hundred and eighty times a minute.

That reads exactly like slow physics from the other side of the glass, which is
why it was worth chasing twice.

Two things fixed it, in this order:

**Numbers at the precision anyone can use.** Positions went out with seventeen
digits and are meaningful to about five. Rounding to 10 µm -- a two-thousandth of
the smallest cell the engine will build, and nothing anybody can see -- took
259 KB to 200 KB on its own.

**A step carries only what changed.** `{"op":"step","moved":true}` compares each
body against the last one sent under that name and leaves out the ones that are
identical. The reply then says `"partial":true`, gives `"count"` for the whole
world, and names in `"gone"` the bodies that really did disappear -- because the
host deletes whatever a reply leaves out, and "unchanged" and "gone" must not
look the same to it.

Measured in the browser, over 805 steps with a 77-piece shatter in the middle:

| | before | after |
|---|---|---|
| median reply | 259 KB | **0.2 KB** |
| worst reply | 259 KB | 42 KB |
| traffic at 30 Hz | 7.8 MB/s | **0.6 MB/s** |
| median round trip | — | 5.0 ms |
| 99th round trip | — | 9.5 ms |
| worst round trip | — | 14.6 ms |
| steps over 100 ms | — | **0** |

The room runs at 106% of real time with 243 bodies in it, inside the 110% gate.

Three things this had to get right, none of them obvious:

**A full reply to anyone resets the trimming.** One process can be drawing a room
and answering a chat window's questions at the same time. If a reply that went to
the chat window counted as "already sent", the room would be told a body was
unchanged on the strength of a reply it never saw, and would leave it standing in
the air. So a reply that goes out whole empties the cache behind it; the next
partial request is answered in full, marked `"partial":false` so the host
replaces what it has, and trimming resumes from there. It costs one big reply and
it cannot go stale.

**The session still hands callers the whole world.** Trimming is for the wire.
`live_session.Session.state` folds each partial reply into the last full picture,
so the tools, the tests and anything else asking what the world looks like get
all of it, exactly as before.

**The step that lands a fracture has to carry geometry.** A piece's cells *are*
its surface. When fracture was synchronous, the fracture's own reply carried
them. Not waiting means the pieces arrive on a *step* instead, and a step does
not normally carry shape -- so every shard was about to be drawn as a box around
itself, which is a lie about what broke.

## And then the clock stopped instead

Two pauses fixed and the room still lurched, and this one was invisible to every
measurement built so far: nothing blocked, no fracture took longer than before,
the wire was a fifth of a kilobyte. The log said `precomputed` every time, which
is the entry that means *nobody waited*.

What it did not say was that the world had stopped.

Reading the owner's own session back, lining the wall clock up against the world
clock, one pair of lines gave it away:

```
14:06:09,196 banjo: held concrete plate 20mm piece 1, 0 ms (t=16.83 s)
14:06:09,977 banjo: precomputed concrete plate 20mm piece 1, 756 ms (t=16.83 s)
```

781 ms of wall clock. **The world clock did not move at all.** And again later,
750 ms for 10 ms of world. The cascade came out at **40% of real time** with
every delay in the log reading "precomputed".

The cause is the handshake meeting itself coming the other way. A break the
world has not resolved is a step it will not take — that is deliberate, and it
is right, because Jolt resolves a contact inside the step and the rolled-back
state is the only one that still has the closing speed in it. The host is meant
to answer. But a host cannot answer while a run is going: asking for a second
fracture then gets nothing back, and the room knows it, so it does not ask.
Nobody could resolve the break and the world sat at one instant for as long as
the first run took.

So the engine stops waiting to be asked. A break detected while another is being
worked out is **captured where it is detected** — in the rolled-back step, from
exactly the state the host would have been handed — and queued. Preparing is a
copy of an island; it is the *run* that costs a third of a second. Capturing it
also records the name as heard, so the next step commits and the clock moves.

Three things this needed that were not obvious:

**A captured break must be accounted for even when its contact lapses.**
`held_through` is cleared for any body not in contact this step. A captured body
whose contact lapsed for one step and resumed was then treated as brand new: it
stopped the clock, and the capture skipped it because it was already queued, so
nothing cleared it and nothing could. Measured, that stalled the world **106
steps in a row** with the capture otherwise working perfectly.

**Applying a fracture renumbers the body table**, and a queued job's indices are
into that table. Everything above the erased island shifts down — the same fixup
`holding` already gets. A queued job whose island *shared* a body with the one
just applied is not fixable and is dropped: the thing it was going to break has
itself come apart, and its pieces are new and untried.

**A batch of steps must run through a captured break.** The batch stopped at the
first rolled-back step so the host could decide — but once the engine captures
it, the next step takes, and stopping there spent a whole round trip per break.
A cascade has dozens.

| | before | after |
|---|---|---|
| longest stall with a fracture pending | 45–106 steps | **0** |
| the owner's cascade | 40% of real time | — |
| the same cascade here | — | **99% of real time** |
| worst the world fell behind the wall clock | — | 0.11 s |
| median round trip, in the browser | — | 12.9 ms |

## A log that misattributes time is worse than none

While reading the above, the log claimed a fracture had taken **4,039 ms**, and
32,670 ms across the cascade. Neither was true. `cost_ms` ran from the moment a
job was *captured*, and a queued job is captured long before a worker takes it,
so the queue wait was being reported as compute. The real numbers were 532 ms
worst and 650 ms total.

That is worth more than a tidy-up: a log that misattributes time sends you to
optimise the wrong thing, and this one would have sent the next reader back into
the lattice solver, which was innocent. `cost_ms` is now the run alone and
`lead_ms` is the wait, and the server prints both:

```
banjo: precomputed concrete plate 20mm, 794 ms of run, 196 ms queued (t=20.72 s)
```

## The room fills up, so you sweep it

Breaking depends on the step being reversible. Before every step the engine
snapshots the physics world, takes the step, and rewinds if that step would break
something — because Jolt resolves a contact *inside* the step, and a fracture
handed an already-resolved contact is handed a ball that has already bounced.

That snapshot has a budget, and the budget is what the room runs out of. It was
256 bodies, which is two broken panes. Past it the step is taken straight and
the room quietly stops shattering — measured, the same iron ball onto the same
20 mm pane broke it into **71 pieces in a room of 58 bodies and left it whole in
a room of 430**. Nothing says so; the room just stops working.

The budget turned out to be far more conservative than it needed to be. Measured
across a room of shattered glass, one step with the trial on:

| bodies | one step | of a 33 ms frame |
|---|---|---|
| 58 | 0.6 ms | 2% |
| 250 | 3.3 ms | 10% |
| 600 | 3.1 ms | 9% |

Flat from 250 to 600, because a body that has settled is cheap to record. So the
ceiling is now **2,048**, which a room has to work to reach rather than reach by
breaking two panes. The same drop that left the pane whole at 430 bodies breaks
it into 75 at 468.

That moves the wall; it does not remove it. What removes it is picking the
pieces up.

### Walking over debris collects it

`{"op":"collect","at":[x,y,z],"radius_m":1.2}` takes the loose pieces near a
point out of the world and says what they were made of:

```json
{"ok": true, "collected": [
  {"material": "glass", "kg": 1.62, "pieces": 66, "cells": 81, "took": ["glass plate 20mm piece 1", "..."]}]}
```

Added up by material, because that is the useful form — nobody wants sixty-six
entries called "glass plate 20mm piece 31", they want to know they have 1.62 kg
of glass. The weight is the matter that was actually there: a piece's cells are
its volume, and volume times the material's density is what you carry away.

What it takes is deliberately narrow, and most of the tests are about what it
must **not** take. Only a *hull* — what something becomes when it breaks or
bends — so an authored bowl is not pocketed by walking past it. Never anchored
scenery, never what is in a hand, and never a body that an unfinished fracture
still holds an index to, which would either resurrect a body that is gone or
write a piece back onto somebody else's slot.

Three things this needed:

**`described` is not where a body is.** It carries the pose a body was *built*
with; `poses()` is what refreshes it from the world. Reading it in the sweep
found every piece sitting at the origin — a fixed 3.06 m from the plate they came
off — so a 3 m sweep collected nothing and a 50 m sweep collected the room. That
is a bug that reads exactly like a tuning problem.

**A sweep answers lean, like `pick`.** It is asked for whenever there is debris
underfoot, and carrying the world along with each answer would put back exactly
the cost that trimming the step reply took out. Every body that went is named in
`took`, which is all a host needs to remove.

**A lean reply is not the world.** `Session.state` was being replaced by whatever
came back, so a `collect` — or a `pick`, which had the same hole and nobody had
noticed — left this side of the wire with no bodies in it at all. A reply only
replaces the world if it describes one; a sweep instead applies its own `took`.

In the room, walking into the pieces shrinks them away over a quarter of a
second, adds them to a tally in the corner, and says so once the sweeping stops —
once, not once per step, or crossing a shattered pane would bury the chat.

## The clock was never the problem. The event was late.

Three pauses fixed — the run off the caller's thread, the wire trimmed, the
clock kept moving — and dropping something that breaks still lurched. Every
measurement said the room was fine: 99% of real time, median round trip 5 ms,
nothing over 100 ms, no stall longer than one tick.

They were all measuring the clock. Here is the measurement that was not:

> **856 ms between the impact and the pieces.**

You drop something, it lands, and then for most of a second *nothing happens* —
and then it shatters. The room is running perfectly the whole time. That is the
lag, and no amount of frame rate fixes it, because the frames were never the
problem.

### Start the run on the way down

The engine could already see it coming. `foresee()` casts a ray along each
moving body's path, works out how fast it will be going when it arrives
(`v² = u² + 2gh`, so a ball that is barely moving now is still judged on the
speed it will land at), and asks the same admission test the step asks. It
reports 485 ms of warning for a 1.5 m drop and 939 ms for 6 m.

And **it was switched off.** The horizon defaulted to zero, nothing in the
playground ever set it, and no caller ever turned it on. The foresight this
engine had was never once used.

So: turn it on, and when a collision is foreseen, start the lattice run *then* —
built from where the two things are going to be rather than where they are.
Nothing is pinned and nothing is told; the world carries on exactly as it would
have. If the collision turns up as expected the answer is already waiting.

| | before | after |
|---|---|---|
| impact → pieces, glass 20 mm | 856 ms | **127 ms** |
| impact → pieces, concrete 20 mm | 818 ms | **113 ms** |
| runs started early and used | — | 6 of 6 |
| how far out the predicted arrival speed was | — | **0.18%** |

0.18% is the number that makes this sound. The lattice is being handed a
collision that differs from the real one by a fifth of a per cent in closing
speed. A guess is only adopted if the same thing was struck, by the same thing,
arriving within 5% of the predicted speed — five, not fifteen, because the
energy goes as the square of it, so 5% of speed is 10% of energy and 15% would
be a third. Anything else is thrown away, which costs a worker thread and
nothing else.

### Four things this got wrong first

**One lattice run at a time.** A guess running beside a real fracture is two at
once, which nothing here was built for. The world deadlocked: the answers came
back wrong, the step was refused for ever, and the test that exists for exactly
that deadlock caught it. Every path that starts a run now settles the guess
first — adopting it if it fits, waiting for it and binning it if not.

**Adopting a guess is the body having its chance.** `prepare()` records that a
body has been tried, which is what lets the world step past something that
*held*. A guess deliberately does not — a prediction about a later collision
must not suppress a different impact in the meantime — so adoption has to record
it instead. Without that, a thing that held was never written down as having
held, and the world deadlocked a second way.

**A guess holds indices into the body table**, which every fracture and every
sweep renumbers. Unlike a queued job it is speculative, so it is thrown away
rather than carefully renumbered.

**Two tests now had nothing to test.** The one that proves the world keeps
running while a fracture runs, and the one that proves a second break does not
stop the clock, both need a run that happens *at contact* — which foresight
removes. They turn it off, deliberately, because that path still matters: a
piece landing on a piece is exactly what a ray does not see coming.

### And a piece that did not know what it was made of

Sweeping the floor reported **"2,833 g of "**. A body is filed under the part of
its first cell, and a piece made of pieces can span several; any component whose
dominant part was not the first cell of anything took an empty name and an empty
material. The room held things called `" piece 1 piece 1"` made of nothing.

Two wrong fixes before the right one: falling back to the struck body called
iron shards glass (4.3 kg of glass where there were 2.5), and falling back to the
material definition called them `soda_lime_glass` while every other body said
`glass` — two entries in the inventory for one substance. What each *part* is
made of, in the words the room uses, is now recorded once when the scene opens,
which is the only place both halves are in hand at the same time.

## The room writes down what it saw

Four lags now, and every one of them was invisible from the server's side. The
world clock stopped while the wall clock ran. The pieces of a broken pane turned
up most of a second after the impact. Both times every number available here said
the room was fine, because every number available here was measuring the clock.

Only the page can see its own frames. So it writes down what it did and posts it
to the server, which puts it in the log:

```
banjo room (somebody said it lagged): room: 104% of realtime  58 fps
  worst frame 34 ms  136 objects  glass plate 20mm broke into 79 87 ms after the
  impact  1 slow frames, worst 71 ms while a break is being worked out
```

Three numbers, because each has caught a lag the other two missed:

- **The two clocks.** How much of the scene's own time went by against how much
  real time did. A world that has stopped reads 0% while everything else looks
  perfect.
- **The worst frame.** What the eye actually sees, which no round-trip
  measurement reaches.
- **How late a break was** — the contact, and the moment the pieces appear. This
  is the one a person actually complains about, and nothing on this side can see
  it at all.

Individual slow frames are named with what the room was in the middle of, since
a slow frame while a break lands means something different from a slow frame
while walking. Every report is also appended to `room-frames.jsonl` under the
runs directory, so a session can be read back rather than described.

**Press L when it lags.** That marks the moment and sends the last few seconds
immediately, so there is a report in the log lining up with what was just seen.
Routine reports go out every four seconds and stay at debug level unless the
room was visibly behind; anything marked by hand is said out loud.

### Nothing drawn is not the same as slow

A browser throttles a tab it is not showing to about one frame a second. In the
numbers that reads as a catastrophic lag — *0.1 fps, worst frame 10,205 ms* —
and it is nothing of the kind. It cost this project two wrong diagnoses before
it was written down, so a report from a room that drew no frames says so on the
front of the line, ahead of any number it would otherwise mislead somebody with.

`document.hidden` is the obvious test for that and it is not enough: a pane can
be off screen in a way that stops the drawing without ever setting it. The
honest test is whether any frames were drawn at all.

### Two mistakes worth keeping

The report was handed `trace.breaks` and `trace.slow` **by reference** and then
emptied them a few lines later, before the request was serialised. Every report
went out with no slow frames and no breaks in it — which is precisely the half
worth reading, and it looked like a working feature that simply never had
anything to say.

And only the break being *asked about* was timed. A cascade queues most of them,
so the majority arrived with no time against them at all — and a queued break,
which waits for the one in front of it, is exactly the one whose timing matters.

## A fall is not long enough to hide a run behind

The first thing the frame trace was used for was a report from somebody playing
in the room, who pressed L:

```
banjo room (somebody said it lagged): room: 98% of realtime  60.1 fps
  worst frame 18.3 ms  134 objects  concrete plate 20mm broke into 75
  356 ms after the impact
```

Sixty frames a second, worst frame 18 ms, the clock keeping up — and the break
still 356 ms late. The trace answered in one line what had taken a day to find
the time before.

The cause is arithmetic. A concrete pane's run costs about 810 ms, and the
warning a fall gives can never be longer than the fall:

| dropped from | the fall itself | warning | impact → pieces |
|---|---|---|---|
| 0.6 m | 350 ms | 268 ms | 573 ms |
| 1.0 m | 452 ms | 375 ms | 462 ms |
| 2.0 m | 639 ms | 501 ms | 330 ms |
| 4.0 m | 903 ms | 702 ms | 147 ms |

Below about three and a half metres there is simply not enough air to work in,
and looking further ahead creates none: the object has not been let go yet.

### So start before it is let go

Somebody holding a ball over a pane has already given us all the warning anyone
could want — seconds of it — and nothing was being done with it. A ray straight
down from whatever is in the hand says what is underneath and how far; `v² = 2gh`
says how fast it would arrive. That is a collision description, and the run for
it can start while the person is still lining the drop up.

If they move, the guess is thrown away and made again — 2% of the arrival speed
is the bar for "still the same drop", so a wobbling hand does not restart it. If
they throw it instead of dropping it the speed will not match and it is refused.
Being wrong costs a worker thread.

| dropped from | before | after |
|---|---|---|
| 0.6 m | 573 ms | **43 ms** |
| 1.0 m | 462 ms | **49 ms** |
| 2.0 m | 330 ms | **53 ms** |
| 4.0 m | 147 ms | **45 ms** |

Flat, because the answer is ready before the thing is released. Watched in the
room: the log shows `guessing concrete plate 20mm` while it is still held, and
the room reports the pane breaking into 65 pieces **46 ms after the impact**.

### Two things it needed

**A guess must not be binned for one quiet pass.** A guess is dropped when the
collision it was made for stops being expected — and the instant somebody lets
go, the drop stops being a held one and has not yet become a falling one. The
guess was binned in that gap, after 816 ms of finished work, at the exact moment
it was about to pay. It now survives four passes of not being expected.

**The held body has to be allowed into the island.** A thing in a hand is
deliberately kept out of a fracture — it is being carried, not colliding — but a
guess that names it is describing what happens when it is let go, and its state
is overridden to the moment it lands. Without that the island was the pane
alone: a free-flying body with no stress in it, which breaks nothing.

### And the contact capacity had to follow the body cap

Raising the reversible-trial ceiling from 256 bodies to 2,048 left Jolt's
contact capacity sized from the scene's *opening* body count. A room that had
broken and been swept a few times reached 504 bodies and Jolt reported
`contact-constraints-full` — which does not slow anything down, it **drops
contacts** and says the step is not validated. Worse than any pause. The
capacity is now sized for what the world may grow to rather than what it opened
with, and the same room runs to over a thousand bodies.

## Every wait is written down

Anything the world waits on, or is spared waiting on, goes out in the reply's
`waits` array and into the server's log:

```
banjo: held glass plate 20mm, 0 ms (t=37.25 s)
banjo: precomputed glass plate 20mm, 815 ms (t=38.13 s)
banjo: precomputed glass plate 20mm piece 3, 6 ms (t=38.13 s)
```

Four kinds. `foreseen` is a collision seen coming, with how long the warning was.
`held` is a pair pinned while its answer is worked out. `precomputed` is an
answer that landed without the caller waiting -- the cost is what it *would* have
cost. `blocked` is the only one that means somebody waited, and the run above has
none.

This was missing when it mattered. The delays were recorded in `LiveWorld` and
handed to the C library, and the playground talks to neither -- it talks to the
line protocol. So the log existed and nothing that drives the room could read it,
which is the same as not having one.

## Nothing to press, and nothing to decline

The stage opens as a running world. There is no transport over it, because a
transport belongs to a recording: a frame to scrub to, a speed to play at, a
pause. None of those mean anything about a world that is still happening, and
leaving them on screen invites the reader to press something that cannot answer.
The one control left restarts the scene.

There is also no scene the lane refuses. It used to accept only a many-object
scene and tell anyone holding the other kind to go and pick a different one --
and the other kind was the default, so the first thing a new reader saw was a
refusal. But a plate and a ball is not a different kind of scene, it is the same
matter written down differently: `fracture_lab.as_objects` turns the plate into a
panel, the striker into a ball already moving at the speed the drop resolves to,
and ledges into two anchored piers. It then goes through `normalise_bodies`, the
same gate a typed scene goes through, so a translated scene cannot slip past a
bound a typed one is held to. What the reader gets is their scene, running.

## Three things a live world needs that a recording does not

**A body that has been still is not being simulated.** A rigid solver stops
stepping a body that has come to rest -- that is what keeps a scene of a hundred
settled pieces cheap -- and writing a pose does not bring it back, because
writing a pose is also how a sleeping body gets placed. A hold that only
re-asserts a pose therefore picks up a sleeping body, carries it, and lets go of
it still asleep: it hangs in the air. Measured: let go a metre up, still a metre
up two seconds later. So `grab`, the per-step hold and `release` all call
`JoltWorld::wake`, which activates the body and clears its sleep timer -- the
timer as well, or a body still resting against the same contacts is asleep again
within a step or two, before it has had a chance to start moving. This is only a
live-world problem. Nothing in a recording is picked up by hand.

**A body that has already broken is not breakable.** Its impacts are still on
record naming it, and a fracture deliberately clears it from the "already tried"
set because its pieces are new and untried. Without a check that the name still
answers to something, the same break was offered a second time, the host asked
again, got nothing back, and told the reader the object had held -- while its
pieces lay on the floor in front of them.

**The piece count has to be read before the pieces replace the body.** `fracture`
reports how many pieces the thing it was asked about became. That count was read
after the struck body had been erased from `nodes_of`, which indexed a vector
that had just been shortened past the index in hand. With the struck body first
the read landed on memory that happened to give the right answer and every test
passed. With a plate standing on two piers -- the arrangement the playground
actually opens with, where the plate is body 2 of 4 -- it read off the end: a
plate that had come apart into eight pieces was reported as having held, and the
panel said so in the chat. The test that pins it holds the reported count against
what the world is holding, in a scene where the struck body is neither first nor
last.
