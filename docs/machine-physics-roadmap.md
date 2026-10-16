# Physics for the machine: what there is, what to add

October 10, 2026. A list of the physics a Rube Goldberg machine on `/machine` should be able to use, so that a person (or the chat's language model) can build with it. For each: whether the engine (LiveWorld) already calculates it, whether the machine's declaration (`banjo.machine.v1`) lets you use it yet, and what is planned.

**In the machine now** means a person or the chat can put it in a machine today. **In the engine** means LiveWorld calculates it, but the machine cannot ask for it yet. **New physics** means it has to be built.

Runtime body positions, cuts, pressure and dents come from the engine's declared
models; guides, current markers and tap illustrations are visual annotations.
Some device laws remain lumped or ideal, and the coupling/calibration limits
below matter. Heavy impacts or cuts can run slower than real time; the page's
clock says when.

October 16: visible graph wires, solar charging cords and legacy circuit
leads now use native Jolt rods, mass, contact and passive bending/twist.
Their actual stock length sets resistance; terminal overload disconnects the
electrical path. Cords settle during setup without advancing puzzle time or
electrical consumption. This supersedes the old drawing-only limitation for
these visible electrical families. Ties and pulley/drum ropes, implicit
optical-source feeders, detailed motor interiors, strand fracture, insulation
and conductor thermal failure remain work to do. See the
[cable qualification](mechanical-cables.md) for model limits and measurements.

October 14 connection audit: `syncRopes` and `updateRopes` in
[`machine.js`](../client/voxel-lab/machine.js) still draw ties, pulley runs and
drum ropes as lines. Their native constraints calculate endpoint forces and
reactions; they do not provide a rope's distributed mass, solid collision
surface, bending, wrap friction or material failure along its length. Spring
coils now have a visible tube, but their native law remains an ideal axial
spring. Historical state before the October 16 migration: older `circuits` drawings
could fall back to a line; newer power
and electrical cables use tubes and clear-solid routing, but only their
electrical connection/resistance is simulated. These cables have no mechanical
mass, bending/contact response or retention model. Changing a line to a tube
would not resolve those missing laws. This audit adds no new cable physics.
Actual knife/heat-cut cords already have material cells and are a separate
model from these ideal joints. Optical rays, paths, alignment guides and label
leaders are annotations and should remain lines.

The required physical replacement is an articulated or deformable connection
with declared conductor/fibre and insulation properties, geometry-derived
mass, collision/endpoint reactions, tensile and bending response, and
connectivity changes on detachment. Pulley/drum versions additionally need
contact with the wheel/drum and a measured wrap/slip law. Qualification must
include full transfers and timestep/mass-ratio convergence, not just a thicker
rendering or a constraint passing a pairwise force test. These replacements
remain unfinished.

## In the machine now

October 13 specialist-solver update: new builds use ngspice for circuit operating
points, including existing backward-Euler RC companions and motor back EMFs.
Charge, heat and reversible mechanical coupling remain engine-owned. This
adds no semiconductor, magnetic field, filament, flexible cable or detailed
device-interior model. Jolt still owns rigid contacts; it never solved water
or electricity. The [solver audit](physics-solvers.md) records measurements,
candidate libraries and concrete missing internal components.

October 13 placement assistance: working-point guides and local board/track
seating derive from compiled geometry and declared optical, blade and terminal
records. Snap edits only proposed placement coordinates, with overlap/support
checks; no simulated force, trajectory, spin or success is assigned. The
knife's lowest hinge-circle point is a kinematic reach annotation, not proof
that it swings there or cuts. Slender structural members expose finite spans
for guide crossings and local transverse knife-plane capture; their shape
and joint records select them, without consulting piece names or solutions.
This adds no blade/rope constitutive law or dynamic cutting constraint.
Green means 3D geometric alignment, not a
clear ray or successful energy transfer. See [editor measurements](machine-game.md).

October 13 heater attachment: new **Heat to release** and **Burn the cord**
use a hollow four-box iron clip with native fixed mounts to a scene-selected
box target and explicit player-drawn supply/return leads. Current, Joule power
and target temperature come from the engine. Unattached heaters heat their
own bar; missing mount declarations cannot designate remote thermal targets.
The fixed mount and winding's thermal coupling are ideal lumped models:
contact-dependent thermal conductance, a resolved winding, insulation and
mechanical attachment failure remain unimplemented. Precise compounds are
excluded from this thermal attachment. See [measurements](machine-game.md#advanced-electronics).

October 13 switch audit: the current **Marble turns on a light** lesson and
example use a broad counterbalanced press deck, open frame, colliding curbs
and actual iron leaf/pad contact. Inspection and current markers expose that
native contact rather than inferring conduction from downward motion. Manual
rockers still use their measured hinge threshold: a prototype metal-pad
retrofit failed to hold or reach contact consistently for glass/oak/iron and
is not published. Circuit voltage/current/RC/thermal laws remain lumped rated
component models; metal shape alone does not create a conducting network.

Cable drawings now clear conservative bounds of visible native solids and
retain sharp route corners in flow previews. This is a rendering correction,
not mechanical cable support or collision. Native slender cable geometry,
material-derived mass, bending/tension, friction/contact reactions, connector
retention and full force/work accounting are still needed before a body can
teeter on a cable or strain it. No collision-triggered cable removal or fake
teeter animation was added. See [the audit and measurements](sandbox-electrics-measured.md#broad-press-deck-and-electrical-audit-october-13).

October 12 editor/routing update: prepared Sandbox kits and hinged assemblies
can be moved or removed, with their dependent declarations updated. Gear
controls show radial size and tangential tooth-alignment guides. The motor's
terminals now sit on the fixed housing's rear face, so the axle lesson's drawn
floor leads clear its rotor. Cables still have an electrical graph/resistance
model and a drawing route, not mass, collision, tension, flexible insulation,
connector retention or mechanical tear/disconnection. Native contact turns
gears during a run. A fitting ghost does not apply forces to its neighbours:
contact-driven seating while dragging still needs a hand/kinematic placement
model and external-work/reaction accounting. Neither behaviour is represented
by a decorative animation. These remain explicit engineering work.

October 12 plumbing update: straight hollow pipes, elbows, reducers and
grounded scaffolding are placeable. Native rigid contact moves marbles; native
falling-water contact routes finite gravity-fed parcels through the same
walls. Inside radius changes actual clearance. Removing pipe mounts lets the
body fall; a separate platform supports a loose board by contact. Same-density
box compounds now integrate mass/centroid/inertia from their clipped union
boundary, avoiding overlap sampling limits for thin rotated walls. Mixed-density
and cylinder unions retain bounded sampling. Worlds containing only precise
bodies can open, step and save without an artificial lattice marker. This does
not add sealed hydraulic networks, calibrated pipe loss/pressure, fluid/ball
drag inside pipes or structural failure of ideal anchored frames. See
[pipe measurements](sandbox-water-launch-measured.md#hollow-pipes-and-scaffolding-october-12).

October 12 solar feedback correction: proposed panel positions now receive
native ready-state sunlight/occlusion samples without stepping or charging
the live machine. The meter and obstruction guide clear their old results
while the new position is measured, then report a marked Preview. The sampled
center is visible on the panel. This corrects observation/display; it changes
no solar, collision, material or energy law. Center-ray shade remains a
whole-collector approximation rather than partial-area integration. See
[solar controls](machine-game.md#clear-solar-shadows-and-required-delivery-cables).

October 12 electronics expansion: independent rated resistors and nonpolar
capacitors can be placed and wired in 3D. Native Circuit now uses accepted-step
RC charge state, explicit ESR/leakage and separate stored-energy/numerical-loss
ledgers. Three advanced activities teach series voltage drop, parallel lamp
wiring and storage. Open supply switches and exhausted batteries do not prevent
a connected charged capacitor from discharging into a load. The component's
capacitance/resistance is a declared rating; case geometry sets housing mass,
not dielectric microphysics. There is no breakdown, polarized failure,
electrostatic moving-plate force or magnetic flux law. See the
[expansion catalogue](electronics-expansion.md) and
[RC measurements](sandbox-electrics-measured.md#native-rc-components-and-advanced-activities-october-12).

October 12 routing update: **Divert the water** and a Sandbox example use a
separate mounted chute and fixed collector. Native falling-parcel contact
and gravity route the flow; the goal observes current parcel volume inside
a declared container region, retained for half a second. Millimetre-exported
positions and unrounded per-source volume ledgers supply the observation.
No native water law changed. These are fixed vessels with parcels resting
on the floor, not calibrated free-surface bucket containment, sloshing or
movable liquid vessels. Chutes admit positive 5â€“35Â° slopes; perfectly flat
pooled chutes are outside the offered domain after an instability in the
existing weakly-compressible parcel model. Invalid colliding placements are
refused. See [routing measurements](sandbox-water-launch-measured.md#divert-water-into-a-fixed-container-october-12).

October 12 bulb update: **Light the bulb** teaches reducing a rated load to
fit the native supply current limit. Large/medium/small components declare
12/6/2.5 W at 12 V and 16/13/10 cm glass diameters. These are chosen component
ratings, not a glass-volume-to-power law. Wire labels distinguish measured
flow from the one shared source budget. Existing bulb presets are unchanged;
filament temperature-dependent resistance and realistic failure remain
unsupported. See [bulb measurements](sandbox-electrics-measured.md#bulb-sizing-and-shared-supply-limits-october-12).

October 12 battery update: selected wire length and cross section now compile
to copper resistance at 20 Â°C (`R = 0.0172 L/A`, metres and mmÂ²). Native
circuit voltage drop and `IÂ²R` heating determine brightness. Old saved wires
keep their 0.01 Î© resistance. The battery lesson uses a grounded source,
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

October 13 spring update supersedes the direct attachment in the current
lesson and newly added Sandbox springs: an ideal native axial Hooke spring
acts on a separate iron push plate, a slide guides its travel, and a removable
fix constraint represents the latch. The user removes that constraint; no
launch velocity or scripted lift is applied. The waiting load has no spring
or slide attachment, so native plate/load contacts transfer force. A coil
mesh follows the measured attachment poses; its turns are a depiction,
not resolved elastic wire, self-contact, fatigue or calibrated coil material.
The red latch marker represents the restraint state, not a simulated pin
withdrawal or latch material model. See the
[contact spring comparison](sandbox-mechanics-measured.md#latched-contact-spring-october-13).
Old saved springs and v1/v2 challenge IDs retain their original construction.

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
fluid turbines, free liquid containment, spreading fire or a spring
catapult preset. See [mechanical measurements](sandbox-mechanics-measured.md),
[electrical measurements](sandbox-electrics-measured.md) and
[water/launch measurements](sandbox-water-launch-measured.md) for per-material
comparisons, full receipts where available and remaining coupled-pipeline limits.

Manual switches now expose a force-dragged physical rocker with hinge limits
and friction; measured angle controls the circuit. Saved starting poses reset
normally, and the former Toggle command is refused. The glass/oak/iron,
two-timestep comparison and the remaining native Pull receipt gap are recorded
in [manual rocker measurements](sandbox-electrics-measured.md#physical-manual-rocker-october-11-2026).
Manual rockers still use their measured hinge threshold. Paddle switches now
carry an iron leaf that must touch a separate supported iron output pad;
native body contact determines that branch. Their interface is still a lumped
0.001 ohm resistance, with no metal/pressure-dependent contact law, oxidation,
arcing, elastic contact bounce or snap detent. Wire displays require current;
electrical rehearsals start paused, with native switch poses included on explicit
playback. See [contact measurements](sandbox-electrics-measured.md#current-driven-display-and-paddle-metal-contact-october-12).

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
| Gears | New pieces use separate toothed bodies and contact torque; saved paired gears retain their ideal `gear` joint | Contact-gear measurements at 1/240 through 1/960 s are in [sandbox-mechanics-measured.md](sandbox-mechanics-measured.md#individual-contact-gears-october-12); the historical ideal pair turns 1189 / âˆ’594 degrees |
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
| Rocket thrust | A region with a nozzle pushes its vessel (thrust 2Â·CdÂ·AÂ·Î”p) | A rocket cart along a rail |
| Fuses | A fuse branch that melts at its IÂ²t | A fuse that blows and opens a circuit |

## New physics

| Physics | What it needs | Planned use |
|---|---|---|
| Light: what is still missing | Light scattered off rough surfaces and the sky's light; a spot heated more than the rest of its body (so focused sunlight could set wood alight); light pushing on what it reaches | A burning glass that lights the rope itself |
| Additional sensor pieces | The sandbox already has manual/paddle switches and the cannon's geometric contact trigger. A selectable thermostat and general pressure-plate piece still need controls and coupled verification | A pan of water that boils trips a switch; a ball landing on a plate rings a bell |
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
## October 13 mechanism expansion

The [new contact/spring pack and mechanism catalogue](mechanism-expansion.md)
adds doors, trapdoors, pendulums, a guided spring trampoline, flywheels,
independent blocks and prescribed open-air drag. It does not close the
remaining cable/contact, flexible membrane, fluid pressure, magnetic or
phase-change gaps. Air drag uses explicit external work and atmosphere
reaction; shielding, lift and powered fans are still unsupported.
