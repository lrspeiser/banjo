# Physics for the machine: what there is, what to add

October 10, 2026. A list of the physics a Rube Goldberg machine on `/machine` should be able to use, so that a person (or the chat's language model) can build with it. For each: whether the engine (LiveWorld) already calculates it, whether the machine's declaration (`banjo.machine.v1`) lets you use it yet, and what is planned.

**In the machine now** means a person or the chat can put it in a machine today. **In the engine** means LiveWorld calculates it, but the machine cannot ask for it yet. **New physics** means it has to be built.

## In the machine now

| Physics | Station today |
|---|---|
| Rigid bodies: rolling, sliding, falling, toppling, friction, rolling resistance | Marble run, dominoes, falling weight |
| Hinges, fixings, ropes (ties), springs, slides, a rope wound on a drum | Lever, rope and gate |
| Breaking (bonded cells) | Glass plate |
| DC circuits: battery, switch worked by a hinge, a coil that heats a body | Electric switch |
| Heat, wood burning, strength falling with temperature | Burning rope |
| Water in a channel, buoyancy and drag; water poured from a spout | Pouring water onto the wheel |
| Light: a sun, mirrors (polished aluminium or iron), glass and ice that bend and focus it, lamps, light sensors and switches that follow them; light warms what absorbs it ([optics-checkpoint.md](optics-checkpoint.md)) | A glass ball focuses sunlight on a sensor whose switch starts a coil; a ball breaking a light gate's beam |

## In the engine, not yet in the machine

| Physics | What the engine does | Planned use |
|---|---|---|
| Steam | Water in a heated body boils at 373 K; the steam fills a closed gas region; its pressure pushes a piston on a slide. Ideal gas, constant heat capacity | A boiler on a coil drives a piston that pushes the next thing |
| Gunpowder-like charge | A "propellant" (2.8 MJ/kg, 56% of it becomes gas, carries its own oxygen) ignites above 450 K in a closed region; the gas drives a ball out of a barrel. Not a model of real gunpowder | A cannon fired by a hot coil, its ball knocking something over |
| Rocket thrust | A region with a nozzle pushes its vessel (thrust 2·Cd·A·Δp) | A rocket cart along a rail |
| Dents | With plasticity on, iron, aluminium, oak and rubber bonds yield and stay stretched: the engine reports the dent's depth and where it is. Iron tears above about 6 m/s | A weight dents an iron plate instead of breaking it |
| Gears, pulleys | Gear pairs (teeth ratio, stripping torque); reeved ropes with a ratio | A gear train, a block and tackle |
| Motors | A motor on a hinge, from a battery, with stall torque and no-load speed | A motor-driven winch or conveyor |
| The sun and solar panels | The sun's direction and irradiance (air mass), shadows on panels, power into a battery | A panel in sunlight charges the battery that drives a motor |
| Lamps | A lamp on a battery gives so many lumens; its light is now traced (a lamp's beam in a machine is the `light_gate` kit) | A lamp that comes on when a switch closes |
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

1. Use what the engine has: steam piston, cannon, dents, gears and pulleys, motors, sun and solar panels, lamps, fuses. Each becomes a kit or part the chat can use, with a station in the engine's rehearsal and a test.
2. Light: ray optics with mirrors and lenses, sunlight that heats what it lands on, and photocells. Built on `agent/optics` ([optics-checkpoint.md](optics-checkpoint.md)).
3. Sensors for heat and touch, then magnetism.
4. Air drag, thermal expansion, freezing and condensation, sound.

Each addition is general (it works for any machine, not just the default one), is calculated live, and is checked by the engine before it is called done.
