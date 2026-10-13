# Electronics components and advanced activities

October 12, 2026. Banjo's electronics expansion should let players place,
connect and adjust components in the same 3D scene as marbles, water wheels
and mechanical loads. Wiring decides topology; the engine decides voltages,
currents, temperatures and motion. Series and parallel are connections the
player builds, rather than special pieces or a mode that changes the rules.

The first implementation milestone is resistors, capacitor charging and
discharging, and series/parallel activities. Later milestones add magnetic
actuators, semiconductors, sensing, power conversion and control circuits.
**The first pack ships standalone resistors, nonpolar capacitors and three
advanced activities; other proposed entries are not shipped components.**
It covers the practical families useful to this game, rather
than every commercial electronic part or a full semiconductor fabrication model.

## What the engine supports today

| Capability | Current status and boundary |
| --- | --- |
| Finite batteries | Placeable voltage, initial charge and shared power limit. A network has one supply. Battery cells in series/parallel and regenerative charging are not supported by the terminal-graph compiler. |
| Explicit wiring | Two terminals per lead; crossings never connect. Selected copper length and area determine resistance at 20 °C. Mechanical cable mass, tensile failure, insulation failure and spatial wire heat are absent. |
| Resistive networks | Native nodal solver handles series/parallel resistive branches. Standalone resistor cards expose rated resistance and A/B terminals. |
| Bulbs | Rated resistive loads; native power is split into heat and optical emission. Brightness follows delivered power. Filament warm-up, temperature-dependent filament resistance and realistic failure are absent. |
| Switches | Paddle leaf/pad conduction follows native iron-body contact. Manual rockers still follow measured hinge angle. Contact resistance is lumped; pressure, oxidation and arcing are absent. |
| Motors | DC torque/back-EMF coupling and mechanical reaction are present. Winding inductance, a calibrated generator and battery regeneration are absent. |
| Heating coils | Circuit Joule heat can enter an actual world body. A generic heater is not yet a calibrated electromagnet. |
| Solar panels | Sun incidence and center-ray shadowing charge a finite store. Their charging leads are ideal, without voltage conversion or resistance. |
| Fuse and temperature laws | Native Circuit has an I²t fuse and positive linear temperature-dependent resistance/tripping. These have no independent Sandbox cards. They do not establish spatial conductor melting or realistic burn/explosion geometry. |
| Capacitors and inductors | Nonpolar capacitors have signed charge, stored energy, ESR and explicit leakage in native Circuit. Inductors still require a magnetic-flux state/model. |
| Diodes and transistors | Native Circuit rejects these branch kinds. New nonlinear device laws and convergence handling are required. |

These statuses come from [Circuit](../src/machines/Circuit.hpp),
[its solver and snapshot implementation](../src/machines/Circuit.cpp),
[the piece compiler](../scripts/sandbox_electrics.py), and the
[existing measurements](sandbox-electrics-measured.md). Existing features
retain their documented limits during the expansion.

## How players place and connect electronics

Every component has a solid housing, supported mounting and visible terminals.
Click the first terminal and then the second to draw a lead. Drag a component
to reposition it while keeping its saved connections. Move a real connector or
contact apart to break a physical connection; moving an explicitly wired
housing does not silently disconnect a wire. A junction exists only where
terminals are connected or a declared conductive contact physically closes.

Nonpolar resistors and film capacitors use A/B terminals. Batteries and
polarized components use +/−. Diodes and LEDs show anode/cathode; transistors
show their three actual pin roles. MOSFETs use gate/drain/source; relays have
separate coil and contact pins. A chassis or earth mark is not a magical
return path: the circuit needs an actual conductor. Ground symbols identify
references; earth conduction needs its own supported model.

The scene shows current only on branches that carry it. Supply voltage can be
available beside an open switch while both series leads carry zero steady
current. Current arrows use conventional-current direction; their display
speed is not electron speed. Voltage, current, charge, temperature and ratings
are available through compact meters and Inspect. Rehearsals stay visibly
separate from the live circuit.

Use the existing full-screen piece library, grid snapping and View/Move controls.
Run/Pause/Reset and the selected piece's adjustments stay with the scene.
On phones, Controls, Level/Design and Help remain separate tabs. Inspect opens
a close-up or cutaway; it does not move native bodies, rewrite contact state,
or leave a win card covering the mechanism. No new permanent panel over the
scene is needed.

## Component catalogue

**Available** means a player can place it now. **Engine foundation** means a
relevant native law exists, but the described card or complete model needs
work. **New model** requires new physics. **Assembly** combines separately
modeled parts; its case name must never determine its output.

### Power and connections

| Piece | Player adjustments and 3D behavior | Physics required | Starting status |
| --- | --- | --- | --- |
| Battery or rechargeable cell | Place a case with two metal terminals; choose a declared cell rating and initial charge. | Finite energy, internal resistance, current/voltage limits and thermal losses. State-of-charge voltage curves and charge acceptance are later extensions. | Available, simplified |
| Battery holder and pack | Place individual cells in physical terminal holders; draw series or parallel links. | Per-cell sources, charge accounting and balancing currents. Different cells must not acquire the same charge merely because they share a case. | Holder available; multi-source pack new model |
| Bench DC supply | Select output voltage and current limit; connect real output terminals. | Explicit external energy/work source, output impedance and regulation loss. It is not a finite battery with infinite hidden charge. | Engine foundation |
| Solar module | Aim and shade a panel; connect a rated controller to the load. | Existing optical collection plus a voltage/current curve, controller losses and battery charging limits. Partial-area shade is a separate improvement. | Available, simplified |
| Generator or dynamo | Couple a shaft to a river wheel, crank or falling weight. | Back-EMF, winding resistance/inductance, reaction torque and electrical extraction bounded by shaft work. No free output at rest. | New generator coupling |
| AC source | Place a declared alternator or explicitly externally powered source; choose frequency/amplitude. | Time-dependent voltage, RMS readings, signed power and energy provenance. | New model |
| Wire, jumper and junction terminal | Draw leads; choose conductor, cross section, length/slack and insulation. | Resistivity versus material/temperature, Joule heat and voltage drop; later physical cable mass, stretch, rupture and insulation failure. | Copper resistance available; extensions needed |
| Plug, socket and terminal block | Fit conducting pins into separate insulated sockets; unplug on the field. | Actual conducting contacts, supported geometry and contact resistance. Pin crossings or nearby plastic must not connect. | Contact foundation |
| Breadboard | Drop parts into labeled holes and bridge the power rails deliberately. | Explicit internal copper buses and terminal graph. Separate rails stay separate until wired. | New assembly/interface |
| Circuit board and solder joint | Route tracks and attach component pins to pads. | Track resistance, explicit junctions and joint geometry; later thermal soldering/reflow, joint failure and shorts. An artistic line is not a conducting trace. | New assembly/interface |

### Resistance and stored energy

| Piece | Player adjustments and 3D behavior | Physics required | Starting status |
| --- | --- | --- | --- |
| Fixed resistor | Place a labeled two-lead body; choose resistance. Tolerance and rated dissipation are later controls. | V=IR and I²R heat. A rated packaged resistor uses declared electrical values; a bare resistive bar needs resistivity, length and area. Do not derive a rating from case diameter. | Available rated card; no bulk resistive bar |
| Rheostat | Move a real wiper along a two-terminal resistive track. | Resistance from contact position and actual conductive path; wiper contact and heat losses. | New component on resistive foundation |
| Potentiometer | Connect both track ends and the movable wiper. | Two resistive segments sharing the wiper; the connected load changes the output voltage. | New three-terminal component |
| Nonpolar film/ceramic capacitor | Place two A/B leads; choose capacitance, ESR and leakage. Voltage-rating controls and internal construction inspection are later additions. | Charge state, I=C dV/dt, stored energy ½CV², series resistance and leakage. A rated core is a bounded starting model, not every real capacitor effect. | Available RC card; no breakdown or geometric plate model |
| Electrolytic capacitor | Place a polarized can with a clear negative stripe and +/− pins. | Transient storage plus rated polarity, leakage, ESR and a calibrated reverse/overvoltage damage law before failure activities ship. Wrong wiring must affect the device law, not trigger a canned explosion. | New model after nonpolar capacitor |
| Supercapacitor or capacitor bank | Place a rated module or connect individual cells visibly. | Per-cell charge/voltage limits, ESR, leakage, finite stored energy and balancing. A bank is an explicit assembly; its energy cannot exceed the sum of its cells. | New model/assembly |
| Adjustable plate capacitor | Change plate area, gap and declared dielectric in setup. | Fixed parallel-plate C≈εA/d in a stated geometry range. Moving charged plates during Run also requires electrostatic forces and mechanical-work accounting. | Later electromechanical model |
| Inductor | Place an insulated winding; change turns, winding resistance and a calibrated core preset. | Flux/current state, V=L dI/dt, ½LI² storage and winding losses. Saturation and hysteresis require additional measured laws. | New transient magnetic model |
| Transformer | Place two insulated windings on a core; choose turns ratio and load. | Mutual inductance, leakage, winding loss, magnetizing current and energy balance. A DC input cannot magically produce continuous transformer output. | New coupled magnetic model |

Capacitor charge and energy behavior follows the component principles in
[Analog Devices' capacitor lab notes](https://wiki.analog.com/university/courses/electronics/electronics-lab-capacitors).
ESR and leakage are distinct paths in the
[Analog Devices capacitor equivalent model](https://ez.analog.com/adiacademy/university-program/a/studentzone-articles/SA1023/grounding-and-decoupling-learn-basics-now-and-save-yourself-much-grief-later-part-3-decoupling-continued).
These references define model requirements, not a calibration of a Banjo part.

### Switching and protection

| Piece | Player adjustments and 3D behavior | Physics required | Starting status |
| --- | --- | --- | --- |
| Knife/manual contact switch | Drag a blade into two visible metal contacts. Choose travel and supported contact material. | Real contact closure, reaction forces and contact resistance. Replace the existing manual hinge-threshold abstraction only after its physical successor passes nudged runs. | Existing rocker; contact upgrade needed |
| Pushbutton and limit switch | Press a plunger with a marble, lever or moving load. | Spring/plunger/contact mechanics, return force and electrical closure. | Mechanical/contact foundation |
| Changeover switch | Move one conducting blade between two separate output contacts. | Common/NO/NC graph with actual contact geometry; break-before-make unless the modeled geometry deliberately overlaps. | New assembly |
| Relay | Power the coil; watch an armature connect an independent load circuit. | Magnetic force from winding current, air gap and iron core; spring return and native contacts. Coil power alone must not run the output load. | New magnetic/mechanical coupling |
| Latching relay | Set/reset separate coils or a supported magnetic/mechanical latch. | Stored mechanical/magnetic state and real contacts, with explicit set/reset work. | New model/assembly |
| Reed switch | Bring a magnet near two springy ferromagnetic blades. | Magnetic field, elastic blade forces, contact closure and hysteresis. | New magnetic model |
| Fuse | Place a replaceable conducting fuse cartridge. Choose a calibrated current-time characteristic. | Native I²t foundation; a thermal melt/failure model is needed before claiming real filament melting or fragments. Failed state persists in saved live snapshots. | Engine foundation; new card |
| Thermal breaker | Heat a current-carrying mechanism until it opens; cool/reset where the model permits. | Temperature-dependent mechanics/contact trip, heat capacity and environmental losses. A threshold macro model must be labeled as such. | Partial thermal foundation |
| Reverse-polarity protection | Build a diode or MOSFET protection path. | Actual semiconductor I–V behavior, forward loss, leakage and supported breakdown behavior. | New model/assembly |

### Semiconductors and control

| Piece | Player adjustments and 3D behavior | Physics required | Starting status |
| --- | --- | --- | --- |
| Rectifier/Schottky diode | Connect marked anode/cathode; select a calibrated part curve. | Nonlinear I–V, temperature, forward loss and leakage; rated reverse breakdown only within a validated model. | New nonlinear solver/device |
| LED | Place a visible emitting die with marked pins; select color and rated current. | Nonlinear diode law and measured optical power/efficiency. Brightness depends on current; reverse leads do not behave like the existing nonpolar bulb. | New model |
| Zener/TVS diode | Put a clamp across the protected input with correct orientation. | Reverse-breakdown I–V, heat, dynamic resistance and energy limits. | New model |
| BJT transistor | Connect base/collector/emitter; a small signal controls a separately powered load. | Coupled junction currents, gain/saturation and thermal loss; later capacitances. Base current is not an unlimited energy source. | New model |
| MOSFET | Connect gate/drain/source and its separate load supply. | Gate charge/capacitance, channel I–V/RDS(on), body diode and dissipation. A gate threshold alone does not mean the device is fully on. | New model |
| Comparator | Wire signal, reference, supply and output pins; choose hysteresis. | Powered macro model with input/common-mode limits, output drive/saturation and delay. An unpowered comparator must not output a powered signal. | Later calibrated macro model |
| Operational amplifier | Connect both inputs, supply rails and feedback components. | Bounded gain/bandwidth, slew rate, input range, output current/rail limits and supply energy. An ideal math operation is not the finished component. | Later calibrated macro model |
| Timer/oscillator | Assemble RC timing plus a comparator/driver, or place an inspectable timer module. | Timing derived from circuit state and thresholds; finite supply, discharge path and output loading. No level countdown fires the module. | Assembly after RC/comparators |
| Logic gates and Schmitt inputs | Wire AND/OR/NOT/XOR inputs, power and outputs. | Datasheet-based voltage thresholds, hysteresis, loading, drive limits, delays and energy use. This is a powered macro model, not a transistor-process simulation. | Later macro models |
| Latch, flip-flop and counter | Wire set/reset/clock/data pins; retain state only under the specified supply conditions. | State derived from input transitions and powered logic behavior; preserve runtime state in snapshots. | Assembly after logic |
| Microcontroller module | Place a powered board and connect explicit I/O pins. Program bounded behaviors later. | Declared instruction/clock model, voltage thresholds, output drive limits and real sensor/actuator interfaces. Its code must not create energy or override native outcomes. | Later bounded digital model |

### Sensors and outputs

| Piece | Player adjustments and 3D behavior | Physics required | Starting status |
| --- | --- | --- | --- |
| Incandescent lamp | Select a rated lamp; adjust geometry only through a declared component family. | Existing resistive optical output; later filament temperature/resistance, thermal inertia and supported failure. | Available, simplified |
| DC motor | Connect polarity and attach an axle to a mechanical load. | Existing torque/back-EMF/reaction model; later inductance and supported regenerative operation. Stall draw and heat are not the same as shaft output. | Available, simplified |
| Solenoid/electromagnet | Place a coil around a sliding iron armature; connect power. | Field/force versus current and gap, inductance, winding heat, magnetic energy and reciprocal mechanical/electrical work. | New model |
| Heater | Put a rated heating element in thermal contact with a container or gas fixture. | Existing Joule-heat transfer; element thermal state, temperature-dependent resistance and electrical isolation need extension. | Available coil; extensions needed |
| Photodiode/phototransistor | Aim a sensor at a native light beam; wire its signal into a powered amplifier/driver. | Photocurrent from absorbed radiant power and response curve, plus dark current, loading and capacitance. | Native light sensing; electrical device new |
| Light-dependent resistor | Place a sensor in light or shadow and wire a divider. | Resistance versus native absorbed light with a calibrated response time. | New constitutive law |
| Thermistor | Attach to a heated object and wire its measurement loop. | Calibrated R(T), self-heating and thermal contact. A positive linear coefficient does not implement an NTC thermistor. | Partial thermal foundation |
| Hall sensor | Move a magnet near a powered three-pin sensor. | Magnetic field sensing, response limits and supply/output loading. | New magnetic/sensor model |
| Piezo transducer | Strike or bend an element, or drive it electrically to vibrate. | Reciprocal electromechanical coupling, capacitance, damping and energy transfer. It is not a switch that conjures voltage on impact. | New model |
| Speaker/buzzer | Drive a coil/diaphragm or piezo element. Choose resonance and damping presets. | Electrical/mechanical power, diaphragm motion and bounded sound output. Audible tones reflect that response. | New model |

### Measurement and power assemblies

| Piece | Player adjustments and 3D behavior | Physics required | Starting status |
| --- | --- | --- | --- |
| Voltmeter | Place two probes across nodes; optionally clip onto metal terminals. | Node-voltage difference and a declared input resistance, so connecting the meter can load a sensitive circuit. | Readouts available; placeable model new |
| Ammeter | Insert a low-resistance shunt in series. | Actual shunt current, voltage drop, heating and instrument fuse. Across a supply it creates a short, not a harmless reading. | Readouts available; placeable model new |
| Ohmmeter/continuity tester | Connect probes to an unpowered circuit. | Explicit internal test source, measured response and unsupported-live-circuit handling. Conductive contact differs from mere proximity. | New assembly |
| Oscilloscope | Attach channel/return probes and inspect voltage/current over time. | Native samples, known input loading, timebase and sufficient resolution. Interpolation must not invent missed transients. | New instrument/interface |
| Bridge rectifier | Place/wire four diodes in a visible bridge. | The constituent nonlinear diode laws, reverse half-cycle behavior and losses. | Assembly after diodes/AC |
| RC filter and smoothing bank | Place separate resistors/capacitors; feed a changing signal or rectified source. | Native transient state and frequency response; load and ESR change ripple/delay. | Assembly after RC |
| H-bridge | Wire switches/MOSFETs around a motor; reverse direction. | Four controlled conducting paths, body/flyback diodes, winding current and possible shoot-through. | Assembly after magnetic/nonlinear devices |
| Buck/boost regulator | Assemble an inductor, switch, diode and capacitor with a powered controller. | Switching transients, stored magnetic/electric energy, regulation and losses. Higher voltage trades current/efficiency, not free power. | Assembly after RLC/semiconductors |
| Charge controller | Place between a generator/solar module and storage. | Explicit conversion/charging limits, source/load curves, losses and battery acceptance. | New assembly |

Inductive switching/protection activities need a real energy path when current
is interrupted. TI's
[high-side switch loss-of-battery report](https://www.ti.com/lit/pdf/slvaes9)
is a reference for decay and clamp models; a spark graphic or forced relay
motion is not a substitute for that model.

## Series and parallel activities

Use **series**, rather than serial, for these circuits. The player's wires
establish the relationship:

| Circuit | What the solver must reproduce | What the player sees |
| --- | --- | --- |
| Series resistors | Same current, voltage shared; equivalent R is the sum. | Each branch's current meter agrees; each resistor has a different voltage drop when its value differs. |
| Parallel resistors | Same node-pair voltage, current split; conductances add. | Separate branch currents and a shared total battery draw. |
| Series lamps | Voltage and power determined by both loads and source resistance/limits. | Changing either load can change both brightnesses; disconnecting either breaks the path. |
| Parallel lamps | Each has its own complete branch; source limits remain shared. | Disconnect one branch and the other still works, subject to the real source budget. |
| Parallel capacitors | Common voltage; stored charge and capacitance add. | Longer hold-up from greater stored energy, with each capacitor's ESR/leakage accounted for. |
| Series capacitors | Equivalent capacitance follows reciprocal addition; individual voltage/initial charge still matters. | Each capacitor has its own voltage/charge meter. Unequal values/leakage do not guarantee equal voltage sharing. |
| Series battery cells | Cell voltages add under a complete validated multi-source model. | Per-cell discharge and possible weak-cell limits. Not part of the current one-source compiler. |
| Parallel battery cells | Currents depend on each cell's voltage and resistance. | Mismatched cells can circulate current; they do not simply gain a shared capacity label. |

Resistor/capacitor/inductor combinations and their ideal relationships are
covered in [TI's passive-component training](https://www.ti.com/video/6119033637001).
The table describes required circuit behavior; real parasitics and validity
limits remain component-specific.

## Twenty advanced activities

Players may choose any offered activity. Cards show how many tasks complete it,
using the existing task-count system. Each starts with visible apparatus, a
load or a receiver, rather than an empty field with an unexplained win message.
The numerical goals below are design criteria to calibrate, not measured levels.

| Activity | Waiting apparatus and player work | Physical completion and failure |
| --- | --- | --- |
| 1. Share the voltage | Source, two resistor sockets and meter; place/wire two resistors in series. | Reach a target divider voltage under the connected load; wrong values/return fail. |
| 2. Split the current | Two branch loads; wire them in parallel. | Both loads meet measured power while the shared source remains within its rating. |
| 3. Keep the other lamp on | Two independent lamps and a physical branch switch. | Opening one branch leaves the other supplied; a mistaken shared series lead extinguishes both. |
| 4. Turn the dimmer | Lamp and a real wiper track; build a divider or rheostat. | Set delivered lamp power in a target band. Loading and resistor heat still count. |
| 5. Charge before the marble arrives | Visible capacitor meter and a falling/rolling trigger. | Reach a required capacitor voltage before actual trigger contact, by choosing R/C. No timer grants charge. |
| 6. Keep the light on after disconnect | Source switch, lamp and storage terminals. | After source contact opens, stored capacitor energy supplies the load for a declared interval. An undersized capacitor droops too soon. |
| 7. Two stores last longer | Two capacitor sockets and a known load. | Wire parallel storage and meet hold-up time; wrong topology or missing return fails. |
| 8. Share the capacitor voltage | Two individually metered capacitor cells. | Build series storage without exceeding either rating; unequal sharing must be visible. |
| 9. Smooth the flashing supply | Pulsed source and visible output meter/load. | R/C values keep measured ripple below a threshold without starving the load. |
| 10. Point the LED correctly | LED socket, resistor and supply. | Correct diode orientation and resistor give rated current/light; reverse orientation is not an ordinary bulb. |
| 11. Protect the little light | Higher-voltage source and a rated LED. | Limit current with actual resistance. Unmodeled explosion behavior cannot decide success. |
| 12. Power through either input direction | Reversible generator leads and a DC load. | Build a four-diode bridge so the output retains the required polarity, including real forward losses. |
| 13. A small signal controls a motor | Low-power sensor, transistor and separate motor supply. | Sensor drive switches the load through a BJT/MOSFET; the sensor does not provide shaft energy. |
| 14. Pull the latch with a coil | Mounted iron plunger, spring and visible latch. | Coil field force overcomes the load; insufficient current/gap alignment fails mechanically. |
| 15. Open the relay safely | Inductive relay and separate contact-powered lamp. | Provide a diode/clamp path; measured turn-off voltage stays within supported component ratings. |
| 16. Harvest the river's work | River wheel/shaft, generator and storage. | Native shaft work charges storage and drives a load; extracting electrical energy slows/reacts on the wheel. |
| 17. Raise voltage without extra energy | Source, regulator parts and a higher-voltage load. | Build a converter that meets voltage/current; input power and losses cover output and storage changes. |
| 18. Let temperature start the fan | Heated container, thermistor, comparator and fan motor. | The measured temperature changes the circuit enough to start the motor; cooling reduces the signal. |
| 19. Wait for both marbles | Two real contact sensors, powered logic and a release mechanism. | Both independent inputs must reach supported logic levels before release. Missing power/one input fails. |
| 20. Build the complete machine | Generator, storage, sensing, controller and actuator. | Harvest energy, detect an event and operate a mechanical load within measured energy/time limits. Each stage has inspectable meters. |

Useful Sandbox examples are a resistor comparison bench, a two-lamp wiring
board, an RC charge/discharge bench, a metered capacitor bank, a transistor
motor driver, an inspectable relay, a river-generator charging bench, a
temperature-controlled fan, and a combined event-controlled machine. Each
example should include a working setup plus an obvious physical control to
change, with Run/Pause and inspection available beside the scene.

## Physics and implementation milestones

### First milestone with resistors and capacitors

Add a placeable resistor card on the existing native resistor branch, then
extend Circuit with persistent capacitor charge/voltage. A capacitor connects
two nodes, stores energy, supports signed current and can supply loads when
the external supply is disconnected. ESR and leakage are explicit element
paths, rather than unexplained decay. The existing one-source restriction
must not prevent a charged capacitor from driving an isolated load network.

Start with declared, rated nonpolar components in a supported voltage range.
Polarized reverse-bias and breakdown activities wait for calibrated failure
laws. Capacitance, resistance and ratings are shown on the actual piece; cases
can be enlarged for interaction, but their visual scale must not invent energy.

For linear RC validation, compare charging/discharging against the exponential
solution with τ=RC. Compare series/parallel equivalent values independently.
Use a method with an explicit numerical-energy account: source energy must
equal changes in electrical storage, physical heat, optical/shaft export and
separately reported numerical dissipation/residual. Solving a trial must not
mutate charge; only an accepted native step commits it.

The first delivered activities are **Limit the voltage drop**, **Series or
parallel?** and **Store the charge**; the larger activities 1–8 above remain
planned. Resistor/capacitor cards, meters, native runtime snapshots and Sandbox
examples accompany this first pack. New/reset designs start capacitors
uncharged: charging them requires source work. Saved designs preserve ratings
and wiring, while native engine snapshots also preserve instantaneous charge.
First confirm the source/load graph supports source disconnect,
floating islands and finite-source limits correctly. Do not replace a
capacitor with a temporary battery of fixed voltage.

### Second milestone with diodes and transistors

Add a bounded nonlinear solve with convergence/error diagnostics and independent
I–V references. Ship diode/LED cards before rectifiers or transistor drivers.
Calibrate device curves, temperature behavior and supported voltage/current
limits from chosen datasheets. Prove that gates/base signals control source
energy rather than supplying it. Deliver activities 10–13.

### Third milestone with magnetic and thermal components

Add inductor flux/current, magnetic stored energy and reciprocal mechanical
coupling before relays, solenoids and generators. Keep friction, winding heat,
environmental losses and numerical correction separate. Add diode/clamp paths
before inductive turn-off challenges; add calibrated thermal/resistive sensors.
Deliver activities 14–16 and 18.

### Fourth milestone with alternating sources and power conversion

Add multi-source networks, AC waveforms, coupled windings and waveform meters.
Then expose transformers, rectification, smoothing, H-bridges and switching
conversion as actual assemblies. Time resolution must resolve switching;
slow-motion viewing must not change physical time constants. Deliver activities
9, 12 and 17 once their dependencies pass.

### Fifth milestone with powered logic and complete machines

Implement supported comparator/op-amp/logic macro models with real power pins,
load limits and timing. Logic behavior remains distinct from transistor-process
physics. Assemble timers, latches and counters from those models; add a bounded
microcontroller later. Deliver activities 19–20 and combined Sandbox examples.

## Materials and release checks

Keep a component's electrical material separate from its housing. A copper
conductor in an oak case can conduct; the oak must not become conductive by
renaming it. Insulation, dielectric and magnetic-core properties need their
own measured models. Unknown materials do not silently inherit copper or iron.
Bulk conductor R=ρL/A is different from microscopic contact resistance.

Fixed packaged components may use datasheet-based equivalent circuits with
declared validity. Inspection can show their construction, but it must not
claim the geometry is computing capacitance or junction physics unless it is.
For moving charged/magnetic parts, account for reciprocal forces, reactions
and storage changes. No programmed launch impulses, forced angles, unexplained
charge or explosion animation may make a level pass.

Before shipping a component or activity:

1. Compile every source into a CMake target and pass source registration.
2. Verify analytic RC/RL and series/parallel references, nonlinear device curves
   where applicable, KCL/KVL and all energy accounts, including disconnected
   supplies, shorts, dead sources and finite final joules.
3. Compare multiple timesteps/resolutions; report actual errors and numerical
   dissipation without relabeling them as physical heat.
4. Compare identical apparatus with glass, oak and iron housings/supports where
   material affects mechanics/heat. Keep conducting materials and electrical
   values explicit; material-neutral circuit oracles are separately identified.
5. Verify every activity's solution in nominal and nudged native runs. Wrong
   wiring, misplaced actuators and insufficient energy must fail physically.
   Preserve old share recipes and do not loosen goals/tolerances to pass.
6. Check placement, wiring, inspection, current display, Run/Pause/Reset and
   save/restore on desktop and phone portrait/landscape.
7. Publish verified checkpoints, update Recent Changes and the measured report,
   verify the local engine hash/revision, then play the deployed revision.

Only independently verified entries move from proposed to available. Detailed
semiconductor fabrication, electromagnetic radiation/RF, mains installation,
electrochemical battery chemistry and a spatial explosion/fracture model are
outside these initial milestones.
