# The machine: a live chain-reaction world built from general parts

October 10, 2026. Open `/machine` on the lab server (local `http://127.0.0.1:18893/machine`; on Render, `/` now opens it after login).

## What you can do

The page shows one world with a chain reaction in it. Press **Start** and watch it run:

1. A spout pours water onto the paddles of an oak wheel standing in a dry trench. The falling water turns the wheel, then runs off down the trench.
2. The wheel's axle winds in a rope, which slides a gate bar out from in front of an iron marble.
3. The marble rolls down an oak ramp.
4. It knocks over eight oak dominoes.
5. The last domino presses down one end of a hinged oak lever.
6. Past 8 degrees the lever closes an electric switch. A 48 V battery drives about 56 A through a heating coil wound on the rope the iron weight hangs from.
7. The coil sets the rope burning. The rope is an oak cord (there is no fibre material yet): it chars, burns and loses strength as it heats. About 14.5 s later it can no longer carry the weight. In the rehearsal the engine reports the rope "carrying 317 N against the 317 N it could still take (800 N cold)": surface 578 K, core 337 K, 3 mm of char, a 14 × 14 mm core of its 20 × 20 mm section still sound, and 40% of its tension strength left.
8. The weight falls about 1.1 m.
9. It lands on a glass plate on two supports, and the plate breaks.

In the engine's rehearsal of this machine the stations happen at 1.9, 2.4, 4.5, 5.4, 5.5, 5.5, 20.0, 20.5 and 20.5 s.

Every step is calculated by the engine while you watch. Nothing is animated or replayed. The stations are checked off only when the engine measures what each one names: a contact between two parts, a hinge past an angle, a switch closed, a fixing parted, a body broken.

You can also **build with words**. Type a request ("add a pendulum that swings into a tower of three oak blocks") and press **Build it**. A language model writes a new declaration of the machine using the same parts. The server checks it, runs it once in the engine to see whether the new stations really happen, and if not, sends the measured events back to the model for one revision. Then the page builds it and the engine calculates it live. **Undo** returns to the previous machine. Under **The machine as data** you can read and edit the whole declaration by hand.

## How it works

- `scripts/machine_world.py` defines the declaration (`banjo.machine.v1`): parts (box, sphere or cone; material, size, position, turn, fixed), joints (hinge, fix, tie, spring), batteries, circuits and torches. **Kits** are shorthand that expand into exactly those parts and joints: ramp (with an optional ball), domino row, lever, hanging weight (post, oak peg, weight), plate on supports, pendulum (frame, rope, ball; it can `aim_at` a part declared earlier) and block tower.
- Before anything runs, the server refuses a declaration that cannot be built honestly: a part below the ground, two loose parts overlapping, unknown materials, joints or circuits naming parts that do not exist, more than 120 parts or more than 120,000 engine cells. Sizes are snapped to whole engine cells (20 mm) and each snap is listed as a note.
- The engine is `banjo_live_world_run` (LiveWorld: Jolt rigid bodies, a bonded-cell lattice for breaking, a heat and combustion network, and DC circuits). The server steps it against the wall clock at a chosen speed (¼× to 4×), answers the breaking handshake, and streams only the bodies that changed. Broken pieces are drawn from their actual cells.
- `scripts/machine_chat.py` asks the model (OpenAI Responses API, `OPENAI_MODEL`, default gpt-5-mini) for a complete declaration. It gets the parts, kits and rules, the current declaration and a summary of where things already stand. The model writes only the declaration; it never writes motion or outcomes.

## Pouring water

The river in LiveWorld is depth-averaged: it has no water in the air, so on its own nothing could be poured onto a wheel. A **spout** now pours at a declared rate (`spouts` in the scene; the water-wheel kit's `pour` makes one above its paddles), and its water falls as parcels until it reaches the river (`src/water/FallingWater.cpp`):

- Each parcel is a 4 cm cube of water, 64 g. Between parcels the law is the weakly compressible SPH of the fluid-wheel experiment (a Wendland C2 kernel, sound speed reduced to 20 m/s), worked out in its own substeps of about a millisecond inside each engine step.
- Against bodies the contact neither rubs nor bounces: a parcel's speed into a surface goes, its speed along it stays, and the body receives the equal and opposite impulse. Those impulses are pushed into the engine's step as a force and a torque about each body's centre, inside the step's reversible trial, so a step taken back pours nothing. The surfaces come from the engine's own shapes (a new sphere query on the rigid world), asked once per parcel per step.
- Where a parcel's underside reaches the river's surface, or the dry ground, it joins that column: its volume as added water in the river's ledger, its horizontal momentum into the water.

Every parcel is the same volume, so the pour's ledger closes by counting: poured = landed + ran off + still in the air. Measured: 3 × 10⁻¹⁸ m³. Parcels are not rigid bodies in the engine, so they cost none of its pair budget and are never mistaken for the ground when a hit is judged.

`tests/valley_live_tests.cpp` "poured water turns a wheel the way it lands": 2 L/s poured 0.2 m to the right of the axle turns the wheel −20.2 rad in 6 s; poured to the left, +20.4 rad; poured past it, 0. The pour's ledger and the river's close together, and a spout with no ground to land on is refused. Three such runs, 15 s of world time, take 1.3 s of wall time.

Not modelled: surface tension, spray, water soaking in, a density correction at solid walls, and water standing inside a body as a liquid (water a bucket holds is parcels resting in it).

## Water in the shared world

LiveWorld's water is a depth-averaged shallow-water model on the terrain grid; it pushes on bodies with pressure and with drag from the relative flow on each surface patch, so it puts a torque on a hinged wheel. Two engine changes were needed to use it here:

- **A flume terrain kind** (`terrain.generate.kind = "flume"`, `src/terrain/TerrainGenerator.cpp`): level ground at y = 0, as the rest of the machine needs, with a straight rock trench along x at a declared z, width, depth and fall; a source on the west edge across the trench, a mouth on the east, and optionally still water standing in the trench up to a declared x. Every other machine part sits on its level banks.
- **A sleeping body now wakes on a change in water torque, not only force** (`Environment::wakeWhatTheWaterReached`). Before, a body asleep in the water woke only when the water's force on it changed by more than a twentieth of its weight. A wheel asleep on its pin in a dry trench felt about 11 N of drag when the water arrived, under the 13.5 N threshold, and never woke, although that drag put about 3.6 N·m on it. It now also wakes when the torque changes by the same twentieth of its weight acting at half its size. `tests/valley_live_tests.cpp` "a stream wakes and turns a wheel asleep in the flume" fails without this change (0 rad) and passes with it (12.8 rad in 12 s, water volume ledger closed to 1e-14 m³).

The wheel is one exact rigid body (a compound of a hub, an axle and paddles), and its rope is the engine's drum joint: a rope that winds onto a turning body and pulls its load. The gate bar sits on a sliding joint. None of these has any machine-specific code.

## Two new engine links

Two general links were missing between the circuit model and the rest of the world, so a switch could not be worked by anything in the world and a coil could not warm anything in it. Both are now in the engine, and both work for any body or hinge, not just this machine:

- **A switch that follows a hinge** (`follows_hinge: {joint, closed_at_or_above_deg | closed_at_or_below_deg}`). At the start of every step, the switch is set from the hinge's measured angle. A hand cannot also throw it.
- **A coil that heats a world body** (`heats_body` on a resistor). Its Joule heat for each step leaves the circuit's own lumped nodes and goes into that body's thermal parcel, as a heater on the heat network's clock. It is declared after the network's saved state, so a refused step takes it back. If the body has gone, the heat stays in the circuit's declared node, so it is never lost.

Measured in the default machine: the battery gave 25,238.6 J, of which 1,118.3 J heated its own internals and 24,120.27 J left through the coil; the heat network received exactly 24,120.27 J. `tests/circuit_tests.cpp` adds a test in which a bar swinging on a hinge closes its switch past -20°: the coil's 953.829 J out equals the 953.829 J into the peg, and it equals I²R times the time the switch was closed.

## How honest each station is

| Station | Engine law | Maturity |
|---|---|---|
| Marble run, dominoes, lever, falling weight | Jolt rigid bodies, contact friction, rolling resistance, hinge limits | Calculated |
| Electric switch and coil | Kirchhoff/Ohm DC network with a finite battery; Joule heat into the rope | Calculated |
| Burning rope | Heat conduction, oak combustion with oxygen, strength falling with temperature; the rope is an oak cord | Experimental: not calibrated against measured burns; no fibre (hemp) material yet |
| Glass plate | Bonded-cell fracture | Experimental: whether it breaks is computed; the number of pieces is not calibrated |
| Pouring water | Falling water as SPH parcels; contact that neither rubs nor bounces; the stream in the trench is shallow-water flow | Experimental: coarse parcels, reduced sound speed; not compared with a measured wheel |
| Rope and gate | A rope wound on a drum (pulls, never pushes); a bar on a sliding joint | Calculated |

Breaking can take the engine longer than real time; the clock then shows how far world time is behind the wall clock.

## Verification

Windows Release build (`build/handoff-resume`), October 10, 2026:

- `banjo_circuit_tests`: all cases pass, including the new hinge-switch and body-heat case. The existing ledger table in `docs/machine-circuits.md` reproduces exactly.
- `tests/machine_world_tests.py` (15 tests, including the flume ground checks, the exact compound wheel and the water-first default chain): declaration checks and refusals, rotation identical to the engine's, kits, the default machine reaching all seven built stations in order in the engine, an aimed pendulum finding its target, live streaming of changes only, the circuit current equal to V/(R_source + R_switch + R_coil), heat handed over exactly, and the chat's refusal and rehearsal loops with a stand-in model.
- `tests/machine_view_test.mjs`: frame merging, temperature colours and camera focus.
- In an ordinary browser: the default machine ran through all seven built stations. A later request on the water-first machine ("In the free lane, add a rubber ball that rolls down a second ramp and knocks over a tower of four ice blocks") was built in one try; the rehearsal measured the hit at 1.42 s. An earlier typed request ("Add a pendulum: an iron ball hanging on a rope from a fixed beam, pulled back so it swings into a tower of three oak blocks") was built by gpt-5-mini in one try. The rehearsal measured the hit at 0.47 s, and the live run checked it off at 0.47 s.

A request using the pour ("In the free lane, add a spout that pours water onto one end of a long oak lever on a pivot, so the water's weight tips the lever down and its other end knocks a small iron ball off a short post") was built by gpt-5-mini and is honest but unsuccessful. It took 4 attempts and two rehearsal revisions (123 s, 56k tokens). The engine measured the pour tipping the lever 11.6° onto its stop within 0.6 s. But the model put the water on the end away from the ball, so the end beside the ball rose, the ball never moved, and the page reported the new station as not happened. After this, each rehearsal-driven revision also gets the revised layout (every group's extents), and the model gets up to two revisions instead of one.

An earlier request, made before the pendulum kit and its `aim_at` existed, produced a pendulum whose ball fell to the ground. The engine showed that honestly: the station stayed unchecked. That is why the kits, the layout summary and the measured-closest-approach feedback were added.

## Limits and next steps

- Poured water is coarse: 4 cm parcels with a reduced sound speed, no surface tension or spray. A pour of a few litres a second looks like a stream of drops, not a smooth jet.
- A flume runs along x only, and the water grid samples barriers at column centres, so a dam thinner than a cell (10 cm) does not hold water back.
- The coil's resistance does not follow the body's temperature, and it has no trip temperature yet.
- The glass plate's piece count and the oak burn are uncalibrated (handoff sections 4 and 6).
- Ramps run along x or z; a corner takes two ramps.
- The model's spatial reasoning is the weakest link. Kits with aiming and the engine rehearsal make the result reliable for simple requests; a complicated request may still need a second try or hand edits to the declaration.
- Render's free instance has a tenth of a CPU, so the hosted machine runs slower than real time while it breaks glass.
