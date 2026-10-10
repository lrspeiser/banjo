# The machine: a live chain-reaction world built from general parts

October 10, 2026. Open `/machine` on the lab server (local `http://127.0.0.1:18893/machine`; on Render, `/` now opens it after login).

## What you can do

The page shows one world with a chain reaction in it. Press **Start** and watch it run:

1. Water runs down a flume (a trench in level ground) and turns an oak paddle wheel.
2. The wheel's axle winds in a rope, which slides a gate bar out from in front of an iron marble.
3. The marble rolls down an oak ramp.
4. It knocks over eight oak dominoes.
5. The last domino presses down one end of a hinged oak lever.
6. Past 8 degrees the lever closes an electric switch. A 48 V battery drives about 56 A through a heating coil wound on an oak peg.
7. The coil heats the peg. Oak chars, burns and loses strength as it heats; about 13 s later the peg can no longer carry the iron weight hanging from it.
8. The weight falls about 1.1 m.
9. It lands on a glass plate on two supports, and the plate breaks.

In the engine's rehearsal of this machine the stations happen at 2.8, 3.4, 5.8, 6.7, 6.8, 6.8, 20.1, 20.5 and 20.5 s.

Every step is calculated by the engine while you watch. Nothing is animated or replayed. The stations are checked off only when the engine measures what each one names: a contact between two parts, a hinge past an angle, a switch closed, a fixing parted, a body broken.

You can also **build with words**. Type a request ("add a pendulum that swings into a tower of three oak blocks") and press **Build it**. A language model writes a new declaration of the machine using the same parts. The server checks it, runs it once in the engine to see whether the new stations really happen, and if not, sends the measured events back to the model for one revision. Then the page builds it and the engine calculates it live. **Undo** returns to the previous machine. Under **The machine as data** you can read and edit the whole declaration by hand.

## How it works

- `scripts/machine_world.py` defines the declaration (`banjo.machine.v1`): parts (box, sphere or cone; material, size, position, turn, fixed), joints (hinge, fix, tie, spring), batteries, circuits and torches. **Kits** are shorthand that expand into exactly those parts and joints: ramp (with an optional ball), domino row, lever, hanging weight (post, oak peg, weight), plate on supports, pendulum (frame, rope, ball; it can `aim_at` a part declared earlier) and block tower.
- Before anything runs, the server refuses a declaration that cannot be built honestly: a part below the ground, two loose parts overlapping, unknown materials, joints or circuits naming parts that do not exist, more than 120 parts or more than 120,000 engine cells. Sizes are snapped to whole engine cells (20 mm) and each snap is listed as a note.
- The engine is `banjo_live_world_run` (LiveWorld: Jolt rigid bodies, a bonded-cell lattice for breaking, a heat and combustion network, and DC circuits). The server steps it against the wall clock at a chosen speed (¼× to 4×), answers the breaking handshake, and streams only the bodies that changed. Broken pieces are drawn from their actual cells.
- `scripts/machine_chat.py` asks the model (OpenAI Responses API, `OPENAI_MODEL`, default gpt-5-mini) for a complete declaration. It gets the parts, kits and rules, the current declaration and a summary of where things already stand. The model writes only the declaration; it never writes motion or outcomes.

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
| Electric switch and coil | Kirchhoff/Ohm DC network with a finite battery; Joule heat into the peg | Calculated |
| Burning peg | Heat conduction, oak combustion with oxygen, strength falling with temperature | Experimental: not calibrated against measured oak burns |
| Glass plate | Bonded-cell fracture | Experimental: whether it breaks is computed; the number of pieces is not calibrated |
| Water wheel | Shallow-water flow; drag on each paddle with a declared drag coefficient (1.0) and skin friction (0.01) | Experimental: the coefficients are declared, not calibrated |
| Rope and gate | A rope wound on a drum (pulls, never pushes); a bar on a sliding joint | Calculated |

Breaking can take the engine longer than real time; the clock then shows how far world time is behind the wall clock.

## Verification

Windows Release build (`build/handoff-resume`), October 10, 2026:

- `banjo_circuit_tests`: all cases pass, including the new hinge-switch and body-heat case. The existing ledger table in `docs/machine-circuits.md` reproduces exactly.
- `tests/machine_world_tests.py` (15 tests, including the flume ground checks, the exact compound wheel and the water-first default chain): declaration checks and refusals, rotation identical to the engine's, kits, the default machine reaching all seven built stations in order in the engine, an aimed pendulum finding its target, live streaming of changes only, the circuit current equal to V/(R_source + R_switch + R_coil), heat handed over exactly, and the chat's refusal and rehearsal loops with a stand-in model.
- `tests/machine_view_test.mjs`: frame merging, temperature colours and camera focus.
- In an ordinary browser: the default machine ran through all seven built stations. A later request on the water-first machine ("In the free lane, add a rubber ball that rolls down a second ramp and knocks over a tower of four ice blocks") was built in one try; the rehearsal measured the hit at 1.42 s. An earlier typed request ("Add a pendulum: an iron ball hanging on a rope from a fixed beam, pulled back so it swings into a tower of three oak blocks") was built by gpt-5-mini in one try. The rehearsal measured the hit at 0.47 s, and the live run checked it off at 0.47 s.

An earlier request, made before the pendulum kit and its `aim_at` existed, produced a pendulum whose ball fell to the ground. The engine showed that honestly: the station stayed unchecked. That is why the kits, the layout summary and the measured-closest-approach feedback were added.

## Limits and next steps

- Water cannot be poured from above: the model has no vertical water velocity, so an overshot wheel or a filling bucket is not possible (handoff section 6). The wheel here is undershot, turned by flow under it.
- A flume runs along x only, and the water grid samples barriers at column centres, so a dam thinner than a cell (10 cm) does not hold water back.
- The coil's resistance does not follow the body's temperature, and it has no trip temperature yet.
- The glass plate's piece count and the oak burn are uncalibrated (handoff sections 4 and 6).
- Ramps run along x or z; a corner takes two ramps.
- The model's spatial reasoning is the weakest link. Kits with aiming and the engine rehearsal make the result reliable for simple requests; a complicated request may still need a second try or hand edits to the declaration.
- Render's free instance has a tenth of a CPU, so the hosted machine runs slower than real time while it breaks glass.
