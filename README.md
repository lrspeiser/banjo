# Banjo

**A Rube Goldberg game where the physics decides what happens.**

Each level is a small machine you cannot change, a goal, and a tray of pieces.
You add pieces, press **Run it**, and the engine works out what every part
does. A ball rolls on the true surface of a plank. A knife cuts an oak rope part
way, or right through. A cannon fires when a circuit closes and the current
heats a coil in its powder. A laser chars a cord until it parts. A solar panel
gives as much power as it catches from the sun, so how it faces matters. Nothing
in a level is scripted: the game only checks whether the goal happened.

**Play it:** <https://banjo-f1sv.onrender.com/play>. It is open to anyone, with
no login.

Banjo is early, built in the open, and has no licence yet. It is developed on
Windows, built and tested on Linux in CI, and not tested on macOS.

## What there is

**Eight chain-reaction levels, twenty-three piece lessons and three advanced electronics activities.**
Every card shows its task count and stars; Level details reveals energy records.
The game shares Controls / Level (or Design) / Help tabs on desktop and phone,
with Run/Pause/Reset kept beside the 3D view. **Recent Changes** in the top
navigation opens dated player-friendly update notes over the current screen;
closing it keeps the level or design. Each published checkpoint updates these
notes in `client/voxel-lab/machine.html`, as required by `AGENTS.md`.
Optical levels keep an engine-traced light path visible while editing. Lenses
have a clear rim and a larger drag marker; focusing a lens or mirror keeps
its source and receiver in view, and **Whole machine** restores the overview.
Cables show measured power/current and moving flow dots while editing or
running. Draw wires by clicking their actual connection rings in the 3D scene.
A dashed guide follows the pointer between clicks; endpoint dropdowns remain
optional precision controls. Solar cables accept either click order.
Small object labels show a bulb's rating or power goal, and an estimated
starting power/torque for simple motor lifts. Complex loads retain
a variable-demand label rather than a guessed threshold.
The lessons introduce cutting, optics, springs, gearing, wiring, water,
heating and catapults one step at a time. **New challenge** offers tested
physical variations with repeatable seed links and a recent-challenges list.
Every authored level opens with a visible object or goal area. The spring
and tackle act on waiting loads, the gear lesson starts with wheels to power,
and the pour lesson starts with a wheel waiting for a separate tank. Water-only
lessons mark their collection channel or river current before a piece is added.
**Fill the receiver** has a waiting box: collect 3 L within 5 seconds by
increasing the source's initially slow tap. The meter counts retained water
and shows the live time remaining.
The one-mirror lesson **Bounce to the target** comes immediately before
**Bounce the beam**. The eight original chain-reaction challenges, with their
current menu numbers, are:

| Level | What makes it work |
|---|---|
| 1. Mind the gap | a plank, cut to length, for a ball to roll across |
| 2. Cut it down | a knife on a pendulum that cuts a rope |
| 3. Knock it off | aim a cannon, draw both firing leads, then drag its physical trigger |
| 4. Up she goes | a steam engine whose piston rises |
| 5. Chain reaction | a ball presses the seesaw's visible contact switch; the wired battery heats the cannon's igniter (Inspect switch shows the contacts) |
| 7. Bounce the beam | two mirrors that bounce a laser round a wall onto a cord |
| 8. Catch the sun | move a solar panel out of a broad wall's shadow, aim at the low sun and draw its power cable to the winch |
| 9. Lift with less | a counterweight on a block and tackle |

A win is scored by energy: what it takes to make your pieces (from their mass
and material) plus what the machine used while it ran. Win on par or less for
three stars.

**Sandbox** (`/machine`) combines the former Free build and machine sandbox.
It opens **Your designs / Examples** gallery tabs with setup previews and **Add New Design**.
New designs open immediately; rename them in the editor’s Design tab.
Each design has a table with no goal and every piece in
the tray: 39 cards including knives, mirrors, lenses, solar panels, tackle,
springs, gears, weights, motors, batteries, switches, bulbs, wires, water
wheels, finite water tanks, heating coils and counterweight catapults.
Gears are individual toothed wheels: choose their size, align their axles and
mesh their teeth. A separate wired battery/motor supplies power. **Turn the big
wheel** teaches bridging a gap between a powered gear and a larger target;
the **Fast wheel slow wheel** example uses the same contact-driven apparatus.
Older saved gear pairs retain their original ideal coupling.
There are 31 editable prebuilt designs, including a battery holder, a river workbench and a
river-powered gate lift. The river's current pushes submerged wheel paddles;
connect the wheel's drum rope to a load to lift it.
**Wheel in the river** teaches moving a wheel into that current. Tanks and
wheels are separate pieces: open a tank's tap, aim its outlet at the paddles,
and watch its native remaining water and flow decrease as it drains. These
are fixed gravity reservoirs; free tipping/sloshing buckets remain future work.
Straight pipes, elbows and reducers have hollow colliding walls for water and
marbles, adjustable bores, downhill slopes and removable mounting scaffolding.
Elbows can turn across the ground or bend a falling stream toward a horizontal
outlet. Separate scaffolding platforms hold loose objects by contact. Try
**Water through pipes**, **Marble through a pipe** and **Support a loose board**.
These are gravity routes, not sealed pressure plumbing; see the
[measurements and boundaries](docs/sandbox-water-launch-measured.md#hollow-pipes-and-scaffolding-october-12).
Pieces snap
together, can be joined with glue, a pin, a string or a spring, and a build can be shared
as a link. **Add a piece** opens a full-screen library with large thumbnails,
search and categories; choosing a piece returns to the scene to place it.
The ground grid has 5 cm squares and stronger 50 cm lines. **Snap to grid**
gently aligns a drag near a line; turn it off or hold Alt to bypass the grid.
Precision controls and movement arrows keep their smaller steps, and saved
positions are never rounded when reopening a design.
You can also ask the chat to build something in words. No player name or login
is needed: a private return URL selects your anonymous save, and a cookie
remembers it. Progress, designs and saved versions sync to the server so the
same link restores them on another device. **Save version** keeps a checkpoint
you can restore. The public service needs the persistent disk described in
[the deployment guide](docs/deploy.md); its save status warns while storage is
temporary. The engine readings and base declaration are available beside
the scene. Old `/play?level=free` links and previously kept builds still work.

Manual switches have physical hinged rockers. Drag their scene handle to open
or close the circuit; the measured hinge angle determines the contact state.
The saved starting pose returns with **Set up again**.

The marble-operated paddle now carries an iron contact leaf beside a separate
iron output pad. Native body contact closes its branch; an open gap, missing
return or empty battery carries no current. **Inspect contacts** in Readings
and wiring zooms in. Wire highlights require measured current, and electrical
previews start paused until **Play preview** or scrubbing is requested. Manual
rockers still use their measured hinge angle; pressure-dependent contact
resistance, oxidation, arcing and realistic filament failure remain future work.

**The chat** gives a hint on a level, places the tray's pieces for you (for one
star at most), or builds what you describe in the Sandbox. It uses OpenAI's
`gpt-5-mini`. It never sees a level's solution.

[docs/machine-game.md](docs/machine-game.md) says how every control and piece
works, what was measured, and how to add a level.
The [physics roadmap](docs/machine-physics-roadmap.md) records the experimental
models and remaining limits; the measured sandbox reports distinguish working
controls from full physical validation. The [electronics catalogue](docs/electronics-expansion.md)
lists placeable component families, proposed activities and implementation stages.
Standalone resistor and nonpolar capacitor cards are available now; capacitor
charge, ESR heat, leakage and stored energy use native RC physics. Three advanced
activities teach resistance, series/parallel lamp wiring and capacitor storage.
The larger semiconductor, magnetic and control-device catalogue remains planned.

## How it works

1. **The page** (`client/voxel-lab/machine.html` and `machine.js`, drawn with
   three.js) shows the world and sends what you do to the server.
2. **The server** (`scripts/voxel-lab.py`) holds each player's live world. It
   builds a level with `scripts/machine_game.py`, which turns pieces and knobs
   into a machine declaration, and runs it with `scripts/machine_world.py`,
   which starts the engine and speaks to it one JSON line at a time. The chat
   is `scripts/machine_chat.py`. `scripts/anonymous_profiles.py` stores anonymous
   progress and design setups in SQLite, independently of live engine sessions.
3. **The engine** (`banjo_live_world_run`, from `tools/live_world_run.cpp` and
   `src/`) is C++. Solid bodies, joints and contact use
   [Jolt Physics](https://github.com/jrouwe/JoltPhysics) 5.6. Anything that can
   break, bend or be cut is also a lattice of 2 cm cells held by bonds
   (`src/fastlattice`), so a break is wherever the bonds give way. Heat and fire
   (`src/thermo`), light (`src/optics`), electric circuits
   (`src/machines/Circuit.cpp`), water and gas pressure are worked out by the
   same engine on every step.

The rules the engine keeps: an outcome comes from the materials, shapes and
forces, never from a name or a canned animation. Nothing floats: every fixed
part stands on the ground or on something that does. The path shown before a
run is the engine rehearsing the same machine, not a guess.
The build preview also shows traced laser rays, falling water and wet channel
surfaces, and signed current through wires. **Flow preview** can be paused or
scrubbed without running the live machine or changing a saved design.

## Run it yourself

You need:

- **CMake 3.25 or later and a C++23 compiler**: Visual Studio 2022 on Windows,
  or GCC 12+ or Clang 16+ on Linux.
- **Python 3.** The server uses only its standard library.
- **Git and a network connection** the first time you configure. CMake
  downloads Jolt Physics and nlohmann/json.
- **An OpenAI API key, only for the chat.** Put `OPENAI_API_KEY=...` in a `.env`
  file at the repository root. Everything else works without one.
- **Chrome and Node.js, only for the tests of the page.**

Build the engine on Windows:

```powershell
cmake -S . -B build/release -G "Visual Studio 17 2022" -A x64
cmake --build build/release --config Release --parallel 8 --target banjo_live_world_run
```

Or on Linux, as the container does:

```bash
cmake -S . -B build/linux -G Ninja -DCMAKE_BUILD_TYPE=Release -DBANJO_BUILD_TESTS=OFF
cmake --build build/linux --parallel 2 --target banjo_live_world_run
```

Start the server with the engine you built, then open
<http://127.0.0.1:18893/play>:

```powershell
python scripts/voxel-lab.py --native build/release/Release/banjo_live_world_run.exe
```

On your own computer it needs no password. To listen on another address, set
`BANJO_PASSWORD` first; the server refuses to without one, unless it is the
public game (`--site game --public`, as deployed).

## Tests

Build everything (leave out `--target`), then run the tests that CI runs:

```powershell
ctest --test-dir build/release -C Release --output-on-failure -LE "long|performance"
python scripts/check-source-registration.py
```

The engine's own tests are C++. The game's are Python:
`tests/machine_world_tests.py`, `tests/machine_physics_tests.py` and
`tests/machine_game_tests.py` run machines and every level's solution in the
engine, and `tests/machine_game_browser_tests.py` plays the page in Chrome.
`check-source-registration.py` fails if a source file under `src/` or `tests/`
is not built by any target.

## Hosting

The game runs on Render from this repository's `main` branch, built from the
`Dockerfile`. [docs/deploy.md](docs/deploy.md) has the settings and how to check
an image before deploying.

## What was taken out

On 11 October 2026 the open world (the valley, the rovers, the workshop and the
bench) and the physics labs were removed so that work could go into the game.
Only the game and the engine it runs on are left. Everything removed is still
in the history: `git checkout 880939eb` is the last commit that had it.

## Documentation

- [docs/machine-game.md](docs/machine-game.md): the game, its levels, free build and the chat.
- [docs/machine-world-checkpoint.md](docs/machine-world-checkpoint.md): the machine declaration and the parts it is built from.
- [docs/machine-physics-roadmap.md](docs/machine-physics-roadmap.md): what the machines' physics does not do yet.
- [docs/cutting-model.md](docs/cutting-model.md): how a blade cuts, and a rope cut part way.
- [docs/light-spots.md](docs/light-spots.md) and [docs/optics-checkpoint.md](docs/optics-checkpoint.md): light, lenses, mirrors and what light heats.
- [docs/floating-point-model.md](docs/floating-point-model.md): why the build pins one way of doing arithmetic.
- [docs/deploy.md](docs/deploy.md): hosting.
