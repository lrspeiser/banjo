# Physics for the machine: what there is, what to add

October 10, 2026. A list of the physics a Rube Goldberg machine on `/machine` should be able to use, so that a person (or the chat's language model) can build with it. For each: whether the engine (LiveWorld) already calculates it, whether the machine's declaration (`banjo.machine.v1`) lets you use it yet, and what is planned.

**In the machine now** means a person or the chat can put it in a machine today. **In the engine** means LiveWorld calculates it, but the machine cannot ask for it yet. **New physics** means it has to be built.

Nothing on the page is animated. Every position, cut, pressure and dent is the engine's own calculation, sent to the page as it happens; change a size or a material and the outcome changes because the physics does. Heavy moments (an impact or a cut solved cell by cell) can run slower than real time, and the page's clock says when.

## In the machine now

| Physics | How a machine asks for it | Measured (tests/machine_physics_tests.py) |
|---|---|---|
| Rigid bodies: rolling, sliding, falling, toppling, friction, rolling resistance | parts, kits | Marble run, dominoes, falling weight in the default machine |
| Hinges, fixings, ropes (ties), springs, slides, a rope wound on a drum | `joints` | Lever, rope and gate |
| Gears | a `gear` joint between two hinges, teeth on each | A motor turns a 12-tooth wheel 1189 degrees; the 24-tooth wheel turns back 594 |
| Pulleys (block and tackle) | a `pulley` joint with a ratio | 2:1: the counterweight falls 0.538 m, the load rises 0.269 m |
| Motors | a circuit's `motor` on a hinge: stall torque, no-load speed, throttle | Draws its battery down as it turns |
| The sun and solar panels | `sun`, `solar_panels` on a part, charging a battery | 0.25 m2 under a 50 degree sun: 191.5 W of sunlight, 38.3 W into the battery |
| Breaking (bonded cells) | brittle parts; any part hit hard enough | Glass plate |
| Dents | `"plasticity": true`, a `dented` station | An iron ball fired into an iron anvil at 20 m/s keeps a 0.1 mm dent |
| Cutting | a `knife_pendulum` kit (pulled back by `pull_back_deg`, 90 held out level, and let go), or `blades` on any part; a `cut` station | The knife cuts a 20 mm oak rope edge-first at 3.7 m/s, 403 mm2 for 6.0 J, and the weight falls; pulled back 60 degrees it passes at 2.7 m/s and cuts it edge-first for 494 mm2 and 7.4 J wherever it stands; turned flat it cuts nothing |
| DC circuits: battery, switch worked by a hinge, a coil that heats a part | `batteries`, `circuits` | Electric switch, burning rope |
| Heat, wood burning, strength falling with temperature | coils, torches | Burning rope |
| Steam | a `steam_engine` kit: a boiler, a cylinder, a piston; heat from a firebox or a coil | 10 kW lifts the piston 10 cm in 0.82 s (about 13 cm/s) |
| A powder charge (a stand-in for gunpowder) | a `cannon` kit; a primer at a time, or a coil on its charge | 2 g fires a 2.1 kg iron ball at 20.7 m/s, a 0.72 kg aluminium one at 31.6, a 0.19 kg oak one at 78; a 0.1 ohm coil on 24 V fires it 0.4 s after its switch closes |
| Water in a channel, buoyancy and drag; water poured from a spout | `ground` flume, `spouts`, the water wheel's `pour` | Pouring water onto the wheel |
| Light: a sun traced through glass and off mirrors (polished aluminium or iron), glass and ice that bend and focus it, lamps whose light is traced, light sensors and switches that follow them; light warms what absorbs it | `light` (sunlight boxes, `mirrors`, `lamps`, `photocells`), the `mirror` and `light_gate` kits, a circuit switch with `photocell`, `lit_w` and `shaded_w` stations | A 100 mm glass ball puts 0.72 W on a 4 mm sensor, twenty times the open sun, which closes a coil that burns a rope; a falling ball breaks a light gate's beam ([optics-checkpoint.md](optics-checkpoint.md); tests/machine_world_tests.py, class Light) |

What the measurements show, and what they do not:

- A thicker rope takes more cutting, in proportion to its section. The same knife at the same 3.7 m/s goes through 20 mm of oak for 6.0 J and comes out at 3.3 m/s; through 40 mm (four times the section) for 22.5 J and comes out at 0.9 m/s; and stops 55% of the way through 60 mm, having spent the 30 J its swing had.
- A knife pendulum can start pulled back at any angle from 10 to 90 degrees. A tilted box is built in its own frame, to its faces as a square one is, so an edge laid along a tilted plate's face is on its matter wherever it stands. (Before, a tilted plate was a staircase of the world's cells: the same 60-degree knife was refused its edge with the rope's post at x 0.513 or 0.527, and where it was taken the cut came to 442-514 mm2 by place.)
- Dents are small at the engine's 20 mm cells: a permanent set spread over a cell reads shallower than a real dent would. They are reported in micrometres when they are.
- An iron ball hitting an anchored iron block at 17 m/s or more can break, at the engine's iron strength; real steel would not.
- The cannon's ball starts at the muzzle (one body cannot be inside another here) and is pushed as if from the breech over the barrel's length, then flies free.
- The boiler's water starts at its boiling point; heating cold water first is not modelled in the kit.

## In the engine, not yet in the machine

| Physics | What the engine does | Planned use |
|---|---|---|
| Rocket thrust | A region with a nozzle pushes its vessel (thrust 2·Cd·A·Δp) | A rocket cart along a rail |
| Lamps | A lamp on a battery gives so many lumens; its light is traced (a machine's lamp is in `light`, or the `light_gate` kit) | A lamp that comes on when a switch closes |
| Fuses | A fuse branch that melts at its I²t | A fuse that blows and opens a circuit |

## New physics

| Physics | What it needs | Planned use |
|---|---|---|
| Light: what is still missing | Light scattered off rough surfaces and the sky's light; a spot heated more than the rest of its body (so focused sunlight could set wood alight); light pushing on what it reaches | A burning glass that lights the rope itself |
| Sensors for heat and touch | A thermostat (closes above a temperature) and a pressure plate (closes under a load), each a circuit switch, measured by the engine | A pan of water that boils trips a switch; a ball landing on a plate rings a bell |
| Magnetism | Force between magnets and iron; an electromagnet driven by the circuit's current | An electromagnet that lets go of an iron ball when its circuit opens |
| Air drag and wind | A drag force on each surface from the air's relative velocity | A sail cart; a feather that falls slowly |
| Thermal expansion | Size changing with temperature | A bimetal strip that bends as it heats |
| Freezing and condensation | Water freezing; steam condensing on a cold surface | Ice that forms and holds a part |
| Sound | Pressure waves; the engine has none | A bell's ring |

## Order of work

1. Done: gears, pulleys, motors, the sun and solar panels, dents, cutting, steam, the cannon. Next of what the engine has: rockets, fuses.
2. Done on `agent/optics`: light, ray optics with mirrors and lenses, sunlight that heats what it lands on, and photocells ([optics-checkpoint.md](optics-checkpoint.md)).
3. Sensors for heat and touch, then magnetism.
4. Air drag, thermal expansion, freezing and condensation, sound.

Each addition is general (it works for any machine, not just the default one), is calculated live, and is checked by the engine before it is called done.

## Watching it

`scripts/film_machine.py` films a machine on the page itself, with a headless browser, so a test's result can be watched rather than only read:

```
python scripts/film_machine.py --spec my-machine.json --seconds 3 --speed 0.25 --view=0,0.2,2.2 --out build/films/my-machine.mp4
```

`--view` fixes the camera (azimuth and elevation in radians, distance in metres, and optionally the point looked at); `--focus` looks at one station.
