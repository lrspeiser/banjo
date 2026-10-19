# Physics on the wall

The wall is a placement surface inside the 3D world. It removes the depth
decision while building; it does not flatten trajectories or override gravity,
contacts, torque, electric current, heat or pressure during a run.

This catalogue separates the complete set of currently supported mechanism
families from physics that still needs a model. A mechanism being listed is
not a promise that its internal material structure has been resolved.

## Playable wall curriculum

There are 26 wall lessons and 64 challenges overall. The first ten remain in
their previous order. Sixteen further activities cover these connections:

| Activity | What the player changes | What decides the result |
|---|---|---|
| Drop into the cup | Marble position | Gravity and cup contact |
| Roll along the wall | Sloping track position | Rolling, sliding and rails |
| Center the funnel | Funnel position | Contact with two sloping faces |
| Bounce off a peg | Peg position | Impact geometry and material response |
| Tip the wall seesaw | Seesaw position | Contact torque about its axle |
| Turn a wall wheel | Wheel position | An off-centre marble impact |
| Connect the wall circuit | A return wire | A complete electrical loop |
| A marble lights the wall lamp | Marble position | Contact between real metal switch pads |
| Fill the wall receiver | Tank position and tap opening | Finite water, head-dependent flow and retained parcels |
| Water drives the wall wheel | Paddle position | Falling water transfers momentum to the rotor |
| Lift and release the marble | Marble in the low cradle | A wired motor, hinge, cradle contact and gravity unloading |
| Water lifts a marble | Tank position and opening | Paddles and cradle on one solid shaft; no electric drive |
| Water lights the lamp | Tank position and opening | Shaft work, DC generator, two massive wires and lamp resistance |
| Air pushes the marble | Air speed | Native drag from an explicitly external air supply |
| Steam raises the piston | Firebox heat | Boiling water, vapour pressure and piston work |
| Open the wall trapdoor | Free/braked hinge | Gravity overcomes bearing resistance |
| Release a wall pendulum | Release angle | Stored gravitational energy pushes a marble along a slide |
| Release the wall spring | Placement and relaxed length | A latch releases a spring-loaded plate against a separate marble |
| Reflect light up the wall | Mirror position and face angle | Native reflected rays reaching the sensor |
| Focus light on the wall | Lens position and curvature | Refraction through the actual lens faces |
| Connect the wall gears | Teeth, height and phase | Independent teeth make contact; a wired motor supplies work |
| Roll through a wall pipe | Pipe inlet position | A hollow sloping collision surface carries the marble |
| Limit current on the wall | Series resistance | Voltage drop, current and Joule heat |
| Store charge on the wall | Capacitance | Accepted-step RC charge and stored electrical energy |
| Catch sunlight on the wall | Panel tilt and an explicit charging cable | Incident sunlight, orientation, occlusion and cable loss |
| Two wall lamps in parallel | Two feed wires | Each lamp has its own path across the supply |

The trapdoor goal measures its hinge opening, rather than crediting a marble
that happens to bounce off the closed flap. Its cup demonstrates the released
path. The pendulum's target has a visible horizontal guide and a native slide;
the player must move it 15 cm. The boiler has a height marker before placement.
Spring release is a field action after Run, not an automatic preview action.

## Building blocks and combinations

The wall Sandbox has 31 mounted tools, alongside the ordinary 3D library.
Search or choose **Wall mounted** in Add a piece. The new tools are a water
marble lift, water-wheel generator, air nozzle, spring launcher, pendulum,
trapdoor, boiler/piston, mirror, lens, laser, solar panel, straight pipe,
pipe elbow and pipe reducer. Moving or turning a mounting wall transforms
the tools' declared anchors, sources and sockets too. Undo, saved versions
and the existing word builder use these same declarations.

| Physics family | Available construction and useful combinations | Boundary |
|---|---|---|
| Gravity, inertia, momentum | Drops, ramps, funnels, cups, marbles, blocks, weights | No assigned rolling speeds or teleported marbles |
| Contact and friction | Peg deflection, slides, rolling, bounces, jams, braked axles | Existing material/contact calibration, not every real surface finish |
| Levers and hinges | Seesaws, pendulums, doors, trapdoors, counterweights | Hinges and rigid brackets are ideal supports |
| Springs and latches | Wall spring, trampoline deck, spring-loaded pushers | Axial spring law, not resolved coil-wire stress/fatigue |
| Rotating storage | Passive paddle wheel, flywheel, geared machines | Bearing and environmental losses remain separate |
| Toothed transmission | Individual gears, powered wall gear, idlers | Rectangular teeth, not calibrated involute gears/backlash |
| Tension transmission | Rope, pulley, winch, counterweight, block and tackle | New massive pulley strands coexist with older ideal drum/tie recipes |
| Mechanical return | Motor cradle or water-driven cradle feeding an upper chute | One lift per reset; no continuous conveyor or endless recycling yet |
| Launch and chain reaction | Counterweight catapult, domino rows, falling doors | Existing ordinary tools; not additional authored wall lessons in this pack |
| DC circuits | Battery, physical switch, lamp, two-terminal copper wires | Rated lumped components; geometry alone does not create a circuit |
| Resistance | Series drops, parallel branches, wire cross-section and copper loss | No automatic conductor melting/insulation failure |
| Electrical storage | Capacitor charge/discharge, ESR and leakage | Nonpolar rated capacitor; no breakdown or dielectric field mechanics |
| Electric motors | Finite electrical power, torque, back EMF, load and direction | Rated actuator law, not resolved coils, magnets and commutator |
| Generation | Water wheel → shared shaft → DC generator → lamp/capacitor/load | No chemical battery charge controller or AC conversion |
| Solar conversion | Adjustable panel → explicit two-core charging cable → receiver | Centre-ray whole-panel shade approximation |
| Reflection/refraction | Wall laser, mirror, convex/concave lens and sensor | Geometric rays, not interference/diffraction |
| Optical heating and cutting | Existing laser/cord and lens-heating primitives | No new authored wall burning/cutting lesson in this pack |
| Joule heating | Wired heating coil, material target and release | Existing lumped winding/body coupling |
| Combustion and fracture | Existing oak cord, knife, fuel and thermal/cutting laws | Exact compound rotors have no fracture/thermal interiors |
| Heat and phase change | Firebox, preheated water boiler, vapour and piston | Lumped thermochemistry; not a resolved kettle with sloshing water |
| Gas pressure and work | Cylinder/piston; existing pressure-powered apparatus | Ideal/lumped region models, not spatial compressible CFD |
| Falling water | Finite reservoirs, opening, head, streams, containers, wheels | Equal-volume gravity parcels, not free-surface CFD |
| Open-channel flow | Existing river wheel and river machinery | Existing shallow-water/contact coupling; no new river solver |
| Plumbing | Wall straight/elbow/reducer pipes carry water or suitably sized balls | Gravity-fed hollow geometry; no sealed pressure/loss network |
| Air and wind | Adjustable supplied airflow, drag, pendulums and sails/doors | Prescribed external velocity region; no resolved fan or gust CFD |
| Structure and assembly | Grounded wall, brackets, scaffolding, joints and blueprints | Mount strength/bolts are ideal, not calibrated structural failure |
| Energy and objectives | Native readings, power/current, temperature, pressure, capture, displacement | Scoring's fabrication estimate is not a physical conservation ledger |

The ordinary tools in that table remain available beside the wall. Wall
placement adapters and dedicated lessons are not supplied for every ordinary
apparatus; in particular the catapult, domino, pulley and cutting activities
remain their existing 3D constructions. They are candidates for the next wall
teaching pack, not silently reclassified as newly shipped wall tools.

## Generator and lift details

The generator includes a passive paddle rotor, real axle and rear housing
with clearance around the rotating shaft. Its sockets extend above and to
the left of the swept paddles. The two native cables sag and collide; their
initial route must remain clear of the wheel throughout use.

Its existing reversible DC law has `k = 1.5 V/(rad/s) = 1.5 N·m/A` and
`R = 450 Ω`: generated EMF is `kω`, winding torque is `kI`, and winding heat
is `I²R`. There is no hidden charged supply. The native circuit requires a
reference port; this one has zero initial energy, stays disconnected and
contributes zero joules. The wall lesson uses a declared 12 V / 0.3 W
nonpolar indicator and a 0.05 W goal, rather than pretending it is a full-size
lamp. Reverse rotation reverses polarity. Connecting a chemical battery to
this island is refused until a charge-controller model exists. A rated
generator is not a resolved electromagnetic interior.

Both cradle lifts use the existing counterbalanced wheel and open pocket.
The water version adds paddles in a separate forward depth lane connected
by solid shaft geometry. One native hinge carries both; there is no separate
animation, speed assignment or scripted release. The source tank's rear
brackets extend back to the wall. After unloading, a physical travel stop
prevents the cradle entering its outlet track. Reset is required for another
lift. A continuous bucket elevator/chain return requires further machinery.

## Further physics: not built in this release

These need new qualified models before we can offer them as real mechanisms:

- A continuous bucket elevator, belt/chain conveyor, ratchet and escapement.
- A directly coupled generator add-on, battery charge controller, diodes,
  rectifier, AC alternator and transformer.
- Inductors, relays, solenoids, permanent magnets and resolved motor interiors.
- Semiconductor devices, logic gates and programmable controllers.
- Water pumps, sealed pressure plumbing, flow loss, siphons and hydraulic rams.
- Moving buckets with free-surface water, buoyancy, floating bodies and sloshing.
- Compressed-air tanks, valves, pneumatic piping and cylinders with leakage.
- A powered fan/blower, wind turbine model, lift/airfoil forces and spatial gusts.
- A fully assembled sunlight → wood fire → kettle → steam loop, with thermal
  contact, containment and fuel/air supply qualified together.
- Calibrated structural bolts, flexible beams, ropes breaking along their
  strands, insulation/conductor failure and material-specific fatigue.

See [the physics roadmap](machine-physics-roadmap.md) and
[specialist solver evaluation](physics-solvers.md). Adding wall placement
does not supply these missing laws.

## Qualification

The authored solutions run through the same native goal observers as other
levels, including two millimetre-scale nudges and deliberately incorrect
settings. No goal or physics tolerance of an existing level was relaxed.
The added negative cases include a closed tap, open generator return,
disconnected solar receiver, held spring latch, missed cradle, zero air,
zero firebox heat, a vertical pendulum and a braked trapdoor.

`tests/machine_game_tests.py` records generator work/heat/light and electrical,
thermal and coupling residuals at 1/240 s and 1/480 s. An open rotor still
loses bearing work; that is heat, not generation. A single final wheel speed
is not an energy oracle: discrete water contacts and cable interactions can
change its phase. Electrical loading is checked through opposing torque and
negative shaft work. These ledgers do not prove full water/rigid-body/global
momentum or energy conservation.

Glass, oak and iron marbles are compared under the same geometry and sources
at 20 mm cells and 1/240 s. A finite water lift can fail with the heavier iron
marble; that is recorded as a load/capture limit, not overridden to force a
win. The motor lift retains the three-material regression. See the opening
measurement record in [machine-game.md](machine-game.md) for final results.
