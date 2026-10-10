# Light: mirrors, lenses, heat and light sensors

October 10, 2026. Branch `agent/optics`. This is the second item of the plan in
[machine-physics-roadmap.md](machine-physics-roadmap.md): ray optics with mirrors and
lenses, light that heats what it lands on, and light sensors that work a switch.

## What you can do

In a machine (`/machine`, schema `banjo.machine.v1`) you can now:

- Put a **sun** in the sky: how high it stands, which way it lies, and how strongly it shines
  (a clear day gives 1000 W on each square metre square to its beam).
- Let **sunlight** fall on chosen parts. You name the parts, or give boxes, that the light
  should reach (lenses, mirrors, sensors, targets), and how far apart the traced rays are.
- Make a metal part (aluminium or iron) a **mirror**. The `mirror` kit turns a polished plate
  so that the sun's light from its middle goes to a target you name.
- Hang **lamps** on a battery, shining into a cone. The `light_gate` kit puts a lamp's beam
  across a gap onto a light sensor.
- Put a **light sensor** (a photocell) on a part. It reads the power of the light reaching its
  face, in watts.
- Make a circuit's **switch follow a sensor**: closed while the sensor reads at least so many
  watts, or at most so many (closed while a beam is broken).
- Use two new **station rules**: `lit_w` (a sensor read at least so many watts) and `shaded_w`
  (it read more, then that or less).

The page draws a few of the rays the engine last traced (those a mirror or a lens turned
first), each as bright as the power the engine measured on it, and each sensor as a small disc
that lights up when light reaches it. Checked in a browser: the glass-ball machine below ran
on the page through all four stations, with the rays bending through the ball to its focus.

An example the tests rehearse: a glass ball rolls along two rails to a stop. There the
overhead sun, focused through the ball, lands on a sensor 8 mm across under the rails. The
sensor reads 0.72 W, against 0.036 W from the open sun, and closes a switch. A battery then
drives a heating coil on a rope, the rope burns through, and a weight falls.

## How the engine calculates light

The engine follows rays of light. Each ray starts at the sun or a lamp and carries power, in
watts. Where it meets a surface, the surface's laws share its power out, and the parts are
followed on until they are absorbed, scattered or leave the scene.

- **Where rays meet things.** The engine asks the rigid-body solver (Jolt) where a ray meets a
  body, using the same shapes the bodies collide with: a ball is a true sphere, a box a true
  box, a broken piece the hull of its cells. It also asks for the surface's normal at that
  point.
- **Sunlight** comes as parallel rays on a square grid across the sun's beam, `spacing_m`
  apart. Only the rays that pass through one of the declared boxes are traced, so the cost
  goes where the light matters. Each ray carries the irradiance times one grid square. A ray
  is traced once, however many boxes it crosses. Before a sun ray enters the scene the engine
  looks back toward the sun from where it starts, so a hill beyond the scene can shade it.
- **A lamp's light** comes from the lamp's middle as rays spread evenly over a cone's solid
  angle (up to all directions). Its power is the lamp's lumens divided by the lumens that a
  watt of its light carries: about 300 for white LED light, about 17 for a filament's light.
  The lamp's own part does not block its light.
- **Mirrors.** A polished metal surface reflects its polished reflectance of the light by the
  law of reflection (angle out equals angle in) and absorbs the rest.
- **Glass and ice** are smooth and transparent. At each surface, Fresnel's equations split the
  light into a reflected part and a transmitted part (for unpolarised light). Snell's law bends
  the transmitted part. Past the critical angle, light inside cannot get out and all of it is
  reflected (total internal reflection). Inside, the light is absorbed as it goes, by Beer and
  Lambert's law. The stronger part of each split continues as the ray. The weaker part is also
  followed if it carries at least 2% of the ray's starting power; otherwise it is counted as
  "unfollowed".
- **Everything else** is a rough surface. It absorbs its share of the light and scatters the
  rest in all directions. Scattered light is counted, not followed.
- **Two bands.** Each ray carries two powers: visible light (with the small ultraviolet part)
  and near infrared. They travel together (one refractive index, no dispersion), but glass and
  ice absorb them at different rates. Window glass passes most visible light and absorbs most
  infrared; a single number for both would make a thick glass ball nearly opaque. Sunlight is
  46% visible.
- **Heat.** Whatever a body absorbs heats it. The power goes into the body in the heat network
  (the same network that burns oak and melts ice) as a heater for each step, until the next
  trace. The heater is declared after the network's state is saved for the step, so a step the
  engine takes back also takes the heat back. An exact rigid body (a compound part) has no heat
  model; light it absorbs is counted as "warms nothing".
- **Sensors.** A light sensor is a flat round face on a part. It reads every ray that lands on
  its part within the face's radius of its middle, coming from in front, before the surface
  does anything to the ray.
- **Switches.** A circuit's switch that follows a sensor is set from the sensor's last reading
  at the start of every step, before the circuit is solved, as a switch that follows a hinge
  is. A hand cannot work it.
- **When.** The engine traces light every 4 steps by default (every 1/60 s at the machine's
  1/240 s step), and at once when light is declared, a lamp is switched or changes brightness
  by more than 1%, or a body appears or goes (a break). A world with no light declared never
  traces and is not slowed.

### One ledger

Every watt of light ends up in one place:

```
sent = heated + warms nothing + ground + escaped + scattered + unfollowed + bounce limit + residual
```

"Heated" is absorbed by bodies the heat network holds. "Ground" is absorbed by the ground.
"Escaped" left the scene. "Bounce limit" was still going after 16 surfaces. The residual is
rounding: about 1e-12 W in every test. The ledger is kept in watts (the last trace) and in
joules (every step since light was declared), and a saved world keeps it.

## What each material does to light

Declared in one place, `src/optics/OpticalProperties.cpp`, with sources.

| Material | Behaviour | Numbers | Source |
|---|---|---|---|
| Glass (soda-lime float) | Transparent | n = 1.526; absorbs 9 per metre (visible), 72 per metre (infrared) | n from Duffie and Beckman, *Solar Engineering of Thermal Processes*, Table 5.1.1. Absorption from Pilkington Optifloat Clear: 0.87 light and 0.72 solar transmittance (taken as its 6 mm sheet), less its two faces' reflection |
| Ice | Transparent | n = 1.31; absorbs 1.5 per metre (visible), 100 per metre (infrared) | Visible: clear end of the 0.6 to 16 per metre Grenfell and Maykut (1977) measured at 500 nm. Infrared: from Warren and Brandt (2008), 22 per metre at 1.03 µm and thousands beyond 1.4 µm |
| Aluminium | Polishable | Polished reflects 0.92 (visible), 0.93 (infrared); rough absorbs 0.30 | Polished: normal-incidence reflectance from Rakić's optical constants (1995). Rough: Engineering ToolBox |
| Iron | Polishable | Polished reflects 0.51 (visible), 0.62 (infrared); rough absorbs 0.65 | Polished: from Johnson and Christy's optical constants (1974). Rough: galvanised iron (Engineering ToolBox 0.64, IES 0.65); no figure found for bare iron |
| Oak | Rough | Absorbs 0.5 | Wood measured 0.31 to 0.57 outdoors (Kim et al.); higher for dense, dark wood |
| Concrete (and the ground) | Rough | Absorbs 0.60 | Engineering ToolBox; RESNET |
| Ceramic (alumina) | Rough | Absorbs 0.50 | Porcelain (Engineering ToolBox); no figure found for alumina |
| Rubber | Rough | Absorbs 0.65 | Soft grey rubber (Engineering ToolBox) |

A rough surface uses one absorptance for both bands, because no figures by band were found.

## Measurements

From `tests/optics_tests.cpp` (Windows, Release, cell 20 mm, step 1/240 s):

| What | Measured |
|---|---|
| A polished aluminium plate tilted 20°, sun 50° up | The reflected ray is within 4.5e-6° of where the law of reflection puts it, and keeps 0.925 of the power (0.92 visible and 0.93 infrared, by share). The error is the precision of the plate's normal in Jolt's single-precision shape |
| A glass slab 100 mm thick, sun 40° from its normal | The ray inside obeys Snell's law to 4e-16. It leaves exactly parallel to how it came in, shifted sideways 28.701 mm (Snell's law gives 28.70086 mm; the engine is within 3 nm). The power out matches Fresnel and Beer-Lambert to 1.2e-7 |
| Total internal reflection | A ray meets the side of a glass block 65.1° from its normal (critical angle 40.9°). All of it turns back, by the law of reflection; it loses only what the glass absorbs on the way |
| A 100 mm glass ball in an overhead 1000 W/m² sun | 150 times the open sun on a spot 1 mm in radius, 67.5 mm below the ball's centre: 0.472 W. The same grid of rays traced by hand through a perfect sphere gives the same 0.472 W. The glass itself absorbs 5.65 W of the 7.85 W on it; by hand, 1.35 W comes out the far side |
| A 0.3 m oak board square to the sun | It absorbs 45 W, half of the 90 W on it. In 1 s the heat network took 45 J and the light gave 45 J |
| An exact (compound) oak board beside it | It absorbs 45 W, counted as warming nothing; the heat network is not handed it |
| A 2 kW filament heat lamp on an oak cord 20 × 20 × 100 mm holding 32 kg, 25 cm away | 1765 W of light; the cord absorbs 786 W, burns, and parts at 16.3 s |
| A lamp's beam on a sensor, and a ball that falls into the beam | The beam closes the switch on the second step. The ball reaches the beam at 0.350 s and the switch opens at 0.358 s, two steps later, and stays open while the ball sits there |
| A saved world | Its lights, sensors, polish and accounts come back, and it goes on exactly as the unsaved one |
| A world with no light | Two seconds of a ramp, a marble and a block are bitwise identical with and without light declared (a sensor, and a lamp's light with the lamp off). 0.0939 ms a step without, 0.0945 ms with |

From `tests/machine_world_tests.py`:

- The glass-ball machine above: the sensor first reads more than 0.3 W at 1.93 s, when the ball
  arrives. The switch closes at 1.98 s, the rope parts at 16.5 s and the weight lands at 16.8 s.
  Without the ball, the same sun on the same sensor reads at most 0.036 W and the switch never
  closes.
- A ball dropped through a light gate's beam darkens its sensor 0.36 s after it is released (it
  falls 0.65 m), and the alarm switch that follows the sensor closes.
- Mirror kits aimed at an oak target 1.5 m away, with the sun behind the target: one 0.2 m mirror
  adds 16.2 W absorbed on it (expected 15.8 W: the sunlight on the mirror, times its 0.925
  reflectance, times the oak's 0.5) and three add 48.1 W (expected 47.7 W). The difference is
  the ray grid's sampling of the mirrors' edges (10 mm).
- Light goes on through the pieces of a glass pane broken by a falling iron ball, and the ledger
  still closes to rounding.

The default machine, which declares no light, gives byte-identical replies for 25 s of world
time on the engine before and after this change.

## Why sunlight through a glass ball does not set the rope alight

In life, a burning glass sets wood alight by heating a spot a few millimetres across, very
quickly. In the engine, heat is held per body (a surface layer and a core). The light a body
absorbs is spread over its whole surface layer at once. So concentration does not help heating
here: only the total power absorbed does.

A 100 mm glass ball passes about 1.35 W of sunlight (worked by hand with the engine's laws;
the engine's focus matches that calculation exactly). To make an oak cord 100 mm long part
under 32 kg, the heat network needs about 400 W put into it: measured with a plain heater, it
parted after 31.6 s, while 200 W brought it to 480 K in 60 s without parting it. A 300 mm cord
needed 800 W (45.7 s). No glass ball of any size passes enough: a bigger ball absorbs more of
its own light, and the most any passes, by the same hand calculation, is about 2.5 W, at about
250 mm.

So the machine above uses the focused light the way the engine can honestly use it: to make a
small sensor read twenty times what the open sun gives, which closes a switch. The coil then
burns the rope. A heat lamp of 2 kW does burn a cord directly (above).

## Cost

Each trace casts a few rays per traced ray: one looking back toward the sun, one to find each
surface (and a second, shorter one to place a hit found far away precisely), and one inside a
transparent body to find where the ray leaves.

| Scene | Rays | Ray casts | Time per trace | Per step (trace every 4 steps) |
|---|---|---|---|---|
| Heat lamp on a cord | 256 | 258 | 0.06–0.07 ms | 0.02 ms |
| Glass-ball machine (rails, ball, sensor) | 2,116 | 9,759 | 2.1–2.2 ms | 0.55 ms |
| Ball-lens test (1.5 mm grid) | 7,272 | 35,196 | 7–9 ms | 2 ms |

Sunlight is limited to 8,192 rays and a lamp to 4,096; the machine's rehearsal of the glass-ball
machine took 4.3 s of computation for 20 s of world time. Each reply of a world with light
carries its ledger, sources, sensors and cost. The rays' paths (48 by default, in millimetres)
come with the `optics` and `light_trace` operations, or a step asked with `"light_paths": true`.

## The engine's operations

`tools/live_world_run.cpp`:

| Operation | What it does |
|---|---|
| `sunlight` `{name, apertures: [{center_m, size_m}], spacing_m}` | The sun's light through those boxes (or round every body). One per world |
| `lamp_light` `{name, lamp, axis, half_angle_deg, rays, radiant_efficacy_lm_w, visible_share}` | A lamp's light into a cone |
| `light_remove` `{light}` | Takes a light away |
| `polish` `{body, polished}` | A mirror finish on a metal part, or off it |
| `photocell` `{name, body, at_m, normal, area_m2}` | A light sensor on a part |
| `light_tracing` `{trace_every_steps, bounce_limit, follow_share, drawn}` | How light is traced |
| `light_trace`, `optics` | Trace now (or not), and answer with the full report and paths |

A circuit branch may carry `follows_light: {sensor, closed_at_or_above_w | closed_at_or_below_w}`.

## Limits

- **Geometric optics only.** No diffraction or interference. No polarisation: each Fresnel split
  treats the light as unpolarised, though real reflected light is partly polarised. No
  dispersion: one refractive index for all colours. Two absorption bands, not a spectrum.
- **Scattered light is not followed.** A rough surface's scattered share leaves the trace.
  There is no light bounced off walls and no light from the sky, only the sun's direct beam.
- **Heat is held per body.** A focused spot warms a body's whole surface layer, not the spot
  (see above). Light carries no momentum: it pushes nothing.
- **Sampling.** Light is a grid of rays. A sensor smaller than a few grid squares reads in
  steps of one ray's power, and a beam narrower than the grid can fall between rays.
- **Mirrors** reflect the same share at every angle; real metals reflect more at grazing angles.
  Only aluminium and iron take a polish. Glass and ice surfaces are always smooth.
- **Transparent bodies.** A body inside a transparent body is not seen by light travelling
  inside it, and two transparent bodies touching are treated as separated by air. A ray that
  enters a broken piece across a sharp edge and finds itself already outside goes on through
  the air (the trace counts these).
- **Lamps** are points. Their light's lumens per watt and visible share are declared, not worked
  out from a spectrum.
- **The sun** is traced from just beyond everything in the scene. A sun so low that the starting
  points are inside a hill is not handled.
- **Rooms** cannot yet declare light in their scene file; it is declared by operations, as the
  machine does. A saved world keeps its light, but light is not carried into a changed room.

## Where the code is

- `src/optics/OpticalProperties.{hpp,cpp}`: what each material does to light, with sources.
- `src/optics/RayOptics.{hpp,cpp}`: the laws and the tracer, with its ledger. It knows nothing
  of the world; the host answers where rays meet surfaces.
- `src/rigid/JoltWorld.{hpp,cpp}`: `castRayToSurface` and `castRayOutOf`, rays with the
  surface normal.
- `src/fastlattice/LiveWorld.{hpp,cpp}`: lights, sensors, polish, the trace's place in the
  step, heat into the network, switches, save and restore.
- `src/machines/Circuit.{hpp,cpp}`: `follows_light`.
- `scripts/machine_world.py`, section "light": the machine's declaration, the `mirror` and
  `light_gate` kits, the station rules. `client/voxel-lab/machine.js` and `machine-view.mjs`
  draw the rays and sensors.
- Tests: `tests/optics_tests.cpp` (`banjo_optics_tests`), `tests/machine_world_tests.py`
  (class `Light`), `tests/machine_view_test.mjs`.

## Verification

Windows, MSVC Release, `banjo-cpu-precise-v1`. Passed: `banjo_optics_tests`,
`banjo_live_world_tests`, `banjo_valley_live_tests`, `banjo_circuit_tests`,
`banjo_solar_panel_tests`, `banjo_sun_day_tests`, `banjo_thermo_live_tests`,
`banjo_machine_control_tests`, `tests/machine_world_tests.py` (all 23), and
`tests/machine_view_test.mjs`. The source-registration check and the floating-point audit pass.
The page was run in a browser on a local server (port 18951). Not checked: Linux.

## A fix on the way: the machine's turns

A mirror kit turns its plate about two axes, and the first one aimed sunlight the wrong way.
`machine_world.rotation()`, which the declaration's checks (overlap, the ground, a compound's
pieces) use, turned a part about x first, then y, then z. The engine turns a body about z first
(TileImpactScene's rotation quaternion, which the engine also reports back as the body's
orientation); x first is the order of the helper that undoes a turn. The two agree for a turn
about one axis, which is all the existing kits use, and not for a turn about two: a plank
turned [30, 0, 45] had its face pointing 10 degrees away from where the checks thought. It now
builds the engine's turn, and a test compares it with the orientation the engine reports.
