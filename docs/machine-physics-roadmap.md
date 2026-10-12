# Physics for the machine: what there is, what to add

October 10, 2026. A list of the physics a Rube Goldberg machine on `/machine` should be able to use, so that a person (or the chat's language model) can build with it. For each: whether the engine (LiveWorld) already calculates it, whether the machine's declaration (`banjo.machine.v1`) lets you use it yet, and what is planned.

**In the machine now** means a person or the chat can put it in a machine today. **In the engine** means LiveWorld calculates it, but the machine cannot ask for it yet. **New physics** means it has to be built.

Nothing on the page is animated. Every position, cut, pressure and dent is the engine's own calculation, sent to the page as it happens; change a size or a material and the outcome changes because the physics does. Heavy moments (an impact or a cut solved cell by cell) can run slower than real time, and the page's clock says when.

## In the machine now

October 12 bulb update: **Light the bulb** teaches reducing a rated load to
fit the native supply current limit. Large/medium/small components declare
12/6/2.5 W at 12 V and 16/13/10 cm glass diameters. These are chosen component
ratings, not a glass-volume-to-power law. Wire labels distinguish measured
flow from the one shared source budget. Existing bulb presets are unchanged;
filament temperature-dependent resistance and realistic failure remain
unsupported. See [bulb measurements](sandbox-electrics-measured.md#bulb-sizing-and-shared-supply-limits-october-12).

October 12 battery update: selected wire length and cross section now compile
to copper resistance at 20 °C (`R = 0.0172 L/A`, metres and mm²). Native
circuit voltage drop and `I²R` heating determine brightness. Old saved wires
keep their 0.01 Ω resistance. The battery lesson uses a grounded source,
player-drawn positive/return leads, voltage choice and wire thickness.
Its resistive bulb works with reversed leads; signed motor current reverses
direction. Cable mass, spatial copper temperature, temperature-dependent
resistivity, insulation breakdown, ampacity and realistic filament failure
remain unsupported. See [the wire measurements](sandbox-electrics-measured.md#battery-voltage-and-copper-wire-resistance-october-12).

Latest October 12 update: the new Gear card creates one mounted compound wheel
with colliding rectangular teeth, rather than a paired ideal ratio constraint.
Tooth count and size set actual geometry and material-derived mass/inertia;
native contact forces transfer torque only when the teeth meet. A separate
finite battery and wired motor supply energy. The lesson and sandbox example
use three individual wheels, with a gap the player bridges. Legacy saved pairs
keep their original ideal joints. Glass/oak/iron comparisons at 1/480 and
1/960 s are in [contact gear measurements](sandbox-mechanics-measured.md#individual-contact-gears-october-12).
This is an experimental rectangular profile, not involute tooth calibration,
tooth stress/fracture, a meshing snap constraint or a full closed mechanical
energy/momentum audit. Contact/hinge receipts still leave aggregate losses and
fixed-support reactions unseparated; the document reports those limitations.

Later October 12 update: the spring, tackle and gear lessons now start with
the loads or wheels they act on, and the pour lesson starts with its wheel.
The spring builder can connect its existing native linear spring/slide joints
to a named moving load. A grounded fork cradle and pedestal support the waiting
loads. All authored levels show apparatus or a visual goal area at opening;
empty worlds remain supported for sandbox/engine use. This changes scene
declarations, not contact, spring, pulley, gear or motor laws. Marked height
guides do not collide or decide outcomes. See the
[waiting-load comparison](sandbox-mechanics-measured.md#waiting-load-spring-october-12).

October 12 update: independent fixed tanks now have a constant-area gravity
reservoir and an adjustable outlet. The native engine derives flow from
remaining head and opening, debits only accepted parcels, and reports source
energy and the external fixed support's impulse/moment. A visible water level
uses native remaining volume. Pour onto the paddles requires a separate tank
and wheel; Wheel in the river teaches moving paddles into the current. There
are now twenty-two selectable lesson families. Old metered sources remain
supported for saved designs and version-1 shares. This is a lumped fixed-store
model, not a tipping bucket, sloshing simulation or calibrated pipe/valve model.
See [the gravity outlet measurements](sandbox-water-launch-measured.md#independent-gravity-tanks-october-12).

Authored empty scenes can open, step and save without solid bodies, including
water-only flumes. An explicit empty body array selects an empty scene; an
undeclared legacy test request retains its original fixture. Missing/malformed
arrays are still refused. This removes the need for reference-marker boxes in
learning fields. Empty lattices use a finite 1/240 s idle scheduling default;
live callers choose their actual step and water keeps its own CFL limit. No
material, contact or water-force law changes accompany this loader update.

The river workbench and its easy lift lesson expose the existing shallow-water
current coupling: immersed paddle surfaces receive pressure/relative-flow drag
and torque, and the wheel winds a real drum rope. Current arrows use the native
velocity grid. The measured oak example lifts its gate; equal-geometry glass
and iron probes receive the same instantaneous water torque, but dense full
fixtures still stall under the existing wake/obstacle heuristics. This is not a
calibrated turbine model or a closed coupled energy audit. See
[river measurements](sandbox-water-launch-measured.md#river-current-wheel).

October 11 update: the sandbox exposes independent cards and twenty-one easy
challenges for the guide's cutting, optics, mechanical, electrical, water and
launch pieces. Explicit electrical terminal graphs support shared finite
supplies, manual/paddle switches, bulbs, coils and motors. Fixed metered water
supplies debit actual remaining volume and count receiver landings; source
valves and arm restraints are queued at engine boundaries. A counterweight
cradle launches through contact. These additions do not establish calibrated
fluid turbines, free liquid containment, spreading fire, gear teeth or a spring
catapult preset. See [mechanical measurements](sandbox-mechanics-measured.md),
[electrical measurements](sandbox-electrics-measured.md) and
[water/launch measurements](sandbox-water-launch-measured.md) for per-material
comparisons, full receipts where available and remaining coupled-pipeline limits.

Manual switches now expose a force-dragged physical rocker with hinge limits
and friction; measured angle controls the circuit. Saved starting poses reset
normally, and the former Toggle command is refused. The glass/oak/iron,
two-timestep comparison and the remaining native Pull receipt gap are recorded
in [manual rocker measurements](sandbox-electrics-measured.md#physical-manual-rocker-october-11-2026).
The ideal electrical contact still lacks internal metal-contact geometry,
pressure-dependent resistance, elastic bounce and a snap detent.

Solar collectors now expose their native center-ray obstruction, incidence
angle, instantaneous charging power and energy account before and during a
run. Both Catch the sun challenges require a player-drawn output-to-input
power lead, to the winch or the introductory lesson's receiving battery.
That lead routes collected energy to a finite receiving store; it is ideal,
with cable mass, resistance, voltage conversion and breakage unsupported.
The shade model still samples only the center, rather than partial lit area.
See [solar controls and limitations](machine-game.md#solar-feedback-and-explicit-power-leads).

| Physics | How a machine asks for it | Measured (tests/machine_physics_tests.py) |
|---|---|---|
| Rigid bodies: rolling, sliding, falling, toppling, friction, rolling resistance | parts, kits | Marble run, dominoes, falling weight in the default machine |
| Turning a whole kit any way | `"turned": {"yaw_deg", "pitch_deg", "roll_deg", "about_m", "clear_ground"}` on any kit: its parts, joints, gas, edges and lamps all turn about `about_m`; with `clear_ground` it is lifted to stand on the ground | A cannon turned 20 degrees fires 20 degrees off its line; a knife pendulum turned 30 degrees still cuts its rope (tests/machine_game_tests.py) |
| Hinges, fixings, ropes (ties), springs, slides, a rope wound on a drum | `joints` | Lever, rope and gate |
| Gears | a `gear` joint between two hinges, teeth on each | A motor turns a 12-tooth wheel 1189 degrees; the 24-tooth wheel turns back 594 |
| Pulleys (block and tackle) | a `pulley` joint with a ratio | 2:1: the counterweight falls 0.538 m, the load rises 0.269 m |
| Motors | a circuit's `motor` on a hinge: stall torque, no-load speed, throttle | Draws its battery down as it turns |
| The sun and solar panels | `sun`, `solar_panels` on a part, charging a battery | 0.25 m2 under a 50 degree sun: 191.5 W of sunlight, 38.3 W into the battery |
| Breaking (bonded cells) | brittle parts; any part hit hard enough | Glass plate |
| Dents | `"plasticity": true`, a `dented` station | An iron ball fired into an iron anvil at 20 m/s keeps a 0.1 mm dent |
| Cutting | a `knife_pendulum` kit (held out level and let go), or `blades` on any part; a `cut` station | The knife cuts a 20 mm oak rope edge-first at 3.7 m/s, 403 mm2 for 6.0 J, and the weight falls; turned flat it cuts nothing |
| DC circuits: battery, switch worked by a hinge, a coil that heats a part | `batteries`, `circuits` | Electric switch, burning rope |
| Heat, wood burning, strength falling with temperature | coils, torches | Burning rope |
| Steam | a `steam_engine` kit: a boiler, a cylinder, a piston; heat from a firebox or a coil | 10 kW lifts the piston 10 cm in 0.82 s (about 13 cm/s) |
| A powder charge (a stand-in for gunpowder) | a `cannon` kit; a primer at a time, or a coil on its charge | 2 g fires a 2.1 kg iron ball at 20.7 m/s, a 0.72 kg aluminium one at 31.6, a 0.19 kg oak one at 78; a 0.1 ohm coil on 24 V fires it 0.4 s after its switch closes |
| Water in a channel, buoyancy and drag; water poured from a spout | `ground` flume, `spouts`, the water wheel's `pour` | Pouring water onto the wheel |
| Light: a sun traced through glass and off mirrors (polished aluminium or iron), glass and ice that bend and focus it, lamps whose light is traced, light sensors and switches that follow them; light warms what absorbs it | `light` (sunlight boxes, `mirrors`, `lamps`, `photocells`), the `mirror` and `light_gate` kits, a circuit switch with `photocell`, `lit_w` and `shaded_w` stations | A 100 mm glass ball puts 0.72 W on a 4 mm sensor, twenty times the open sun, which closes a coil that burns a rope; a falling ball breaks a light gate's beam ([optics-checkpoint.md](optics-checkpoint.md); tests/machine_world_tests.py, class Light) |
| Light on a spot: a beam heats where it lands and takes oak (charred) and ice (melted) away there; lasers; lenses traced as spheres | the `laser` and `lens` kits, `light.lenses`, the `cut` station | A 4.5 kW laser off one mirror burns a 20 mm oak rope through at 2.05 s and the weight is in its bin at 2.3 s; a convex lens focuses a wider beam to a smaller spot and the rope goes sooner ([light-spots.md](light-spots.md); tests/machine_world_tests.py, class Light) |

What the measurements show, and what they do not:

- A thicker rope takes more cutting, in proportion to its section. The same knife at the same 3.7 m/s goes through 20 mm of oak for 6.0 J and comes out at 3.3 m/s; through 40 mm (four times the section) for 22.5 J and comes out at 0.9 m/s; and stops 55% of the way through 60 mm, having spent the 30 J its swing had.
- A knife pendulum starts held out level. A square part is built exactly to its faces; a plate tilted at another angle is built of a staircase of the world's cells, and an edge cannot be laid along it reliably.
- Dents are small at the engine's 20 mm cells: a permanent set spread over a cell reads shallower than a real dent would. They are reported in micrometres when they are.
- An iron ball hitting an anchored iron block at 17 m/s or more can break, at the engine's iron strength; real steel would not.
- The cannon's ball starts at the muzzle (one body cannot be inside another here) and is pushed as if from the breech over the barrel's length, then flies free.
- The boiler's water starts at its boiling point; heating cold water first is not modelled in the kit.

## In the engine, not yet in the machine

October 11 contact-holder update: **Give it power** and the new saved sandbox example expose the existing geometric native contact switch. Separate iron caps and holder pads close a finite battery/bulb circuit only while touching. Glass/oak/iron housing comparisons, two timesteps, electrical receipts and the limits of the mechanical audit are in [sandbox-electrics-measured.md](sandbox-electrics-measured.md#physical-battery-holder-october-11-2026). This is a fixed-resistance binary connector model. Pressure-dependent contact resistance, corrosion, arcing, connector elasticity and battery chemistry are still absent; rigid drop energy changes are not full coupled conservation proof.

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
2. Done on `agent/optics`: light, ray optics with mirrors and lenses, sunlight that heats what it lands on, and photocells ([optics-checkpoint.md](optics-checkpoint.md)). Done on `agent/light-spot`: light that heats the spot it lands on and cuts there, lasers, and lenses with curved faces ([light-spots.md](light-spots.md)).
3. Sensors for heat and touch, then magnetism.
4. Air drag, thermal expansion, freezing and condensation, sound.

Each addition is general (it works for any machine, not just the default one), is calculated live, and is checked by the engine before it is called done.

## Watching it

`scripts/film_machine.py` films a machine on the page itself, with a headless browser, so a test's result can be watched rather than only read:

```
python scripts/film_machine.py --spec my-machine.json --seconds 3 --speed 0.25 --view=0,0.2,2.2 --out build/films/my-machine.mp4
```

`--view` fixes the camera (azimuth and elevation in radians, distance in metres, and optionally the point looked at); `--focus` looks at one station.
