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
