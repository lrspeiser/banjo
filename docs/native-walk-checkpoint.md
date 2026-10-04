# Native bodies that walk and swim — October 4, 2026

Branch `agent/opening`. Windows 11, MSVC Release, CPU reference. This builds
on the [native actor foundation](native-player-foundation-checkpoint.md): a
70 kg, 0.24 m × 1.7 m rigid cylinder per player, which until now could only be
pushed by a bounded external actuator.

**A player now starts as a body** (the owner's call, 2026-10-04). Menu →
Movement offers "God mode" (fly freely) and the old camera walk instead. If
the server will not give a body, the page walks as the camera and asks again
every 5 s, so the view never freezes. Browser tests that are about other
things keep the camera walk unless they set `BANJO_TEST_MOVEMENT`.

## What a native body does now

**It walks.** The host asks for a horizontal velocity and a facing (at most
6 m/s, held at most 0.5 s and renewed every frame). The engine's own
controller drives the body only while the ground under it holds it up, which a
ray from its middle checks.

- **Traction.** A horizontal force toward that velocity, capped at 0.6 of the
  normal force and 600 N. While the body is driven its contacts carry no
  friction, so this force is its grip. It does not add to the contact's own
  friction.
- **Slope.** Four short rays read the slope under it. On a frictionless
  contact the ground pushes the body downhill by m·g·tan(slope), so the
  controller adds that push into the hill, the way a person leans to stand on
  a hill. Past tan(slope) = 0.6 (31°) it cannot hold.
- **Balance.** A bounded balance torque (at most 400 N·m, about what ankles
  and hips give together) keeps it upright and turns it to its facing.
- **Reaction.** When it stands on a loose body, that body takes the equal and
  opposite push.
- **No ground.** In the air it gets no traction at all.
- **Accounts.** Walk work, impulse, angular impulse and support reaction are
  its own accounts. They survive a reopen; a held request does not.

**It swims.** Off the ground and in water half a metre up its body, a request
becomes a stroke:

- a horizontal force toward the asked velocity, at most 100 N (a swimmer's
  sustained push);
- no traction limit and no balance torque, since buoyancy holds it up;
- the stroke's reaction goes into the water column it swims in, on the steps
  that are kept.

**It is a little more than a person.** The owner asked for bodies that are
slightly superhuman, and each number says so beside it in the code:

- **Speed.** It walks at 2 m/s and runs (Shift) at 5 m/s.
- **Jump.** Space gives 4.4 m/s upward, about a metre, once per press and
  only from the ground. Its feet push the ground down by as much.
- **Getting up.** Knocked flat, it rights itself the next time it is asked to
  walk, with up to 700 N·m. Before this it stayed down for good, and in a
  river it was pinned to the bed.
- **Landing.** Its contact is damped (ratio 0.7), so it lands on its feet
  instead of bouncing.
- **Stepping up.** Any rise from 1 cm to 35 cm is a step its legs lift it
  onto, with up to 2,500 N (about 3.6 times its weight) and at up to 2 m/s.
  A 50 cm wall still stops it.

**Walking over 25 cm cells is smooth.** The player's report of a stuttering
walk had four causes, each fixed:

- **The server held walks up.** Every page asks for guidance every few
  seconds, which re-checked all 23 recipes: 1.6 s of work under the world
  lock that every walk waited behind. Recipe readiness is now remembered by
  the recipe's source, and guidance takes 0.18 s. A walk request also holds
  for 0.5 s, so the body keeps going through a slow reply.
- **It stepped up too late.** It looked only 15 cm ahead, met each riser
  before its feet were up, stopped and set off again. It now looks as far as
  it will travel in 0.3 s, takes the nearest step in that distance, and rises
  at the speed that would just carry it to the top, so it arrives level.
- **Steps read as hills.** The slope rays straddled the edges between cells
  and read a step as a hill to push into. That push helped one way and
  dragged the other. Now a rise on one side only is taken as a step, and the
  level top it stands on as flat.
- **Old bodies were left standing.** A body stayed where its player last
  was, long after they left. A player not seen for 12 s now takes their body
  out of the world (`player-remove`).

**People and robots drive the same body.** On the page, Menu → Movement →
Native body sends the keys and stick as a walk request about twelve times a
second, and the eye rides the body. The AI player, with `BANJO_NATIVE_BODIES=1`,
walks its route with the same requests instead of reporting poses. The server
derives the actor from the authenticated player and spawns the body once, at
that player's own last stance. A request may name neither another actor nor a
place to appear. The route is allowed in funded rooms.

## Measured

Engine tests at dt = 1/240 s:

| Case | Conditions | Result |
|---|---|---|
| Walk, seamless slab | 1.4 m/s asked for 3 s | Reaches 1.4 m/s in about 1.75 s; momentum residual 0.0002 N·s; work residual −0.04 J against kinetic energy |
| Walk, generated-style terrain | Same, over ground patches | 1.33 m/s averaged over 2 s; each patch seam costs speed (below) |
| Stop | 0 asked after walking | Under 0.05 m/s within 1.5 s |
| Traction | 6 m/s asked from rest | Gains no more than 0.6·g·t; traction fully used |
| In the air | Dropped from 3 m with 2 m/s asked | No horizontal speed, no walk work |
| 20° ramp | Standing, asked 0 | 0.09 mm in 3 s after settling; 1.4° lean |
| 40° ramp | Standing, asked 0 | Slides 5.4 m and goes over; tan 40° > 0.6 |
| Plank | Walking 1 m/s on a loose oak plank | Plank takes exactly the opposite impulse (60.69 N·s) |
| Reopen | Save and reopen mid-walk | Walk accounts restored; held request not |
| Swim | Basin lake, 0.8 m/s asked for 4 s | 1.6 m swum; stroke reaction equals the water's received stroke momentum to 1e-9 N·s |
| Get up | Knocked to 88° | Back to 0.02° |
| Jump | Standing, Space once | Rises 0.98 m; a second jump in the air does nothing; lands upright |
| Stairs | Four 25 cm steps at 2 m/s | 1.97 m/s through them (was 1.48 in jerks); rises 1.00 m |
| Uneven cells | Tiles 0–4 cm apart, 2 m/s each way | 1.85 and 1.80 m/s (was stuck both ways) |
| Trench | A 50 cm trench ending in two 25 cm steps | Climbs both out; a 50 cm wall stops it |

End to end, `tests/native_walk_tests.py` runs on a generated valley through the
real server. A joined player's body spawns where they stood, walks more than
1.5 m in 3 s at 1 m/s upright, stops, and stays put once the requests end. In
the browser, about 100 walk requests over 3 s were accepted and the view
followed the body with no page errors.

## Limits, said plainly

- **Seams.** The ground is height-field patches, each compressed to 2 mm.
  Where two meet there can be a millimetre lip, and crossing one costs a
  walker a little speed (about 5% over 2 s). The cylinder's base edge is
  rounded 3 cm so it rides over the lips rather than catching. Making every
  patch finer would change collision for the whole game, so it was not done
  here.
- **Swimming momentum.** Body and water momentum close only to about 17% while
  swimming. The water coupling's hydrostatic force on a moving body has no
  reaction on the water (`WaterCoupling.hpp`). The stroke itself is exact.
- **Not anatomical.** The balance torque and traction are declared control
  limits on a cylinder proxy, not muscles or footwear. There are no legs:
  stepping up is a lift its legs would give, not a stride.
- **Lips cost a little.** Over cells a few centimetres apart it keeps about
  92% of the asked speed, the same each way.
- **Cargo pulls back on the body.** What the hand pushes on a thing it holds,
  reversed at the grip, acts on the body, and a held load presses on its feet
  for traction and balance. A thing carried whole (a crate with a lid fixed to
  it) pulls back the same way, through its joints. In zero gravity and clear
  of the floor, body and load keep their momentum to 0.34% (one crate) and
  0.32% (crate and lid): the crates' declared 0.02/s velocity damping, which
  the body does not have. The earlier 4% was the floor: standing on it, the
  reaction at the grip tipped the body onto the rim of its foot and the floor
  took part of the push.
- **Bodies survive world edits.** An install rebuilds the room from its
  snapshot, and a restart reopens the saved world; the engine carries native
  players in both. The body is within 1 cm of where it stood after an install,
  walks on in the rebuilt room, and is back within 5 cm after a restart
  (`tests/native_walk_tests.py`).
- **Not yet done:** the hand's reach tied to the body, and AI robots on
  bodies by default.

## Verification

```powershell
cmake --build build/walk --config Release --target banjo_valley_live_tests banjo_live_world_run
build/walk/Release/banjo_valley_live_tests.exe        # 36/36
$env:BANJO_LIVE_ENGINE="build/walk/Release/banjo_live_world_run.exe"; python tests/native_walk_tests.py
```

The existing hand-stroke (9) and water (21) suites pass unchanged.
