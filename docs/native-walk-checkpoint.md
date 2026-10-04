# Native bodies that walk and swim — October 4, 2026

Branch `agent/opening`. Windows 11, MSVC Release, CPU reference. This builds
on the [native actor foundation](native-player-foundation-checkpoint.md): a
70 kg, 0.24 m × 1.7 m rigid cylinder per player, which until now could only be
pushed by a bounded external actuator. It is experimental. The camera
controller is still the default; a native body is chosen in Menu → Movement.

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
  limits on a cylinder proxy, not muscles or footwear. There is no stepping
  up: a step taller than the rounded edge stops it. There are no legs.
- **Cargo pulls back on the body.** What the hand pushes on a thing it holds,
  reversed at the grip, acts on the body, and a held load presses on its feet
  for traction and balance. In zero gravity with nothing to stand on, body and
  crate together keep their momentum to within about 4%; where the 4% goes is
  not yet found (the test prints it). A thing carried whole, rather than
  held in the hand, does not yet push back.
- **Bodies survive world edits.** An install rebuilds the room from its
  snapshot, and a restart reopens the saved world; the engine carries native
  players in both. The body is within 1 cm of where it stood after an install,
  walks on in the rebuilt room, and is back within 5 cm after a restart
  (`tests/native_walk_tests.py`).
- **Not yet done:** the hand and camera tied fully to the body. The camera
  controller remains the default.

## Verification

```powershell
cmake --build build/walk --config Release --target banjo_valley_live_tests banjo_live_world_run
build/walk/Release/banjo_valley_live_tests.exe        # 30/30
$env:BANJO_LIVE_ENGINE="build/walk/Release/banjo_live_world_run.exe"; python tests/native_walk_tests.py
```

The existing hand-stroke (9) and water (21) suites pass unchanged.
