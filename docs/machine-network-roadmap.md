# Stateful machines: the remaining implementation program

The machine boundary is a set of physical connections and persistent state.
Detailed construction, ordinary operation and optional detailed analysis are
three views of one product. Opening Workshop must preserve charge, temperature,
contents, phase and damage. Exposed geometry still collides with the world.
Replacing internal geometry by equations never authorizes prescribed output
speed, arbitrary power or erased reaction loads.

This program extends ProductGraph and PhysicsContract. The first executable
increment is documented in [machine circuits](machine-circuits.md). The owner's
September 19 request ended during milestone 1; the later milestone grouping
below is an implementation proposal, not a reconstruction of missing text.

## Physical interface contract

| Connection | Shared quantities and accounting |
|---|---|
| Electrical | terminal voltage, signed current; power is their product |
| Rotating shaft | angle, angular velocity, torque, housing reaction |
| Translational | position, velocity, force, support reaction |
| Thermal | temperature, signed heat rate in watts |
| Fluid | pressure, mass flow, composition and transported enthalpy |
| Material | substance, amount, temperature, phase, processing state |
| Control/sensing | bounded commands and measurements; never implicit physical power |

Connections enforce shared equations: equal potentials where appropriate,
balanced flows, constitutive laws and consistent time. A component cannot set
both effort and flow regardless of the load. Every conversion names its source,
limit and loss destination. A defined boundary audits change in stored energy
against net incoming energy and external work, with independently reported
numerical residuals. Material balances and mount reactions have corresponding
audits. No local zero residual substitutes for a coupled-world audit.

## Four systems and their acceptance experiments

1. **Electrical, mechanical and thermal operation.** Battery, switch, fuse,
   motor, ideal gearbox and real world load. Shared weak-supply interaction;
   finite current and heating at stall; open-wire behavior; exhaustion; fuse
   failure; component temperatures; restart continuity. The first native
   increment exists. Remaining gates include stronger time coupling, generalized
   Workshop editing/carry, shared thermal-world ports, multi-source circuits and
   calibrated ratings. Do not call all electrical machinery complete.
2. **Contained matter and pressure-driven machinery.** Tanks, pipes, valves,
   pump and cylinder, coupled to inventories, pressure, mass and enthalpy.
   Restricting a passage changes the rest of the network; a blocked cylinder
   increases pressure; relief and leaking seals account for discharged matter
   and energy; pressure-rated walls fail under real loads. Couple the existing
   latent-heat foundation to live vessels before claiming pouring/casting.
3. **Generation and thermal cycles.** Waterwheel/generator/battery/motor,
   followed by a complete heat-engine or heat-pump loop. Include charging
   acceptance, converter losses, heat rejection and finite cooling/environmental
   limits. Check thermodynamic directionality and the second law as well as
   joules. Environmental inputs have declared available power.
4. **Autonomous manufacture with lifetime.** Sensor/controller-driven processing
   consumes stock, energy and time; interrupted work retains partially processed
   matter, waste and heat. Add declared fatigue/wear/creep/corrosion history after
   operating loops work. Detailed analysis can refine a local failure without
   repairing or replacing the rest of the product.

## Capability register (all fifteen retained)

| Area | Existing foundation / next executable extension |
|---|---|
| 1. Circuits | First bounded native shared DC/thermal network; multi-source, RLC and electronics still open |
| 2. Storage/generation/conversion | Finite stores exist; reversible charging, SOC voltage, acceptance and conversion laws next |
| 3. Electromechanical/magnetic | DC motor and reaction torques; declared solenoids, linear actuators and holding-force laws next |
| 4. Transmission | Pins, ropes, drums and first ideal motor gear ratio; general shafts, gears, clutches, belts, rack/screw and losses next |
| 5. Flexible structure/connections | Existing deformation/failure lanes; dependable beam/shaft/plate/shell models, bending/torsion and bearing ratings next |
| 6. Internal thermal networks | First arbitrary lumped circuit thermal nodes/links; coupling to existing thermochemical parcels and coolants next |
| 7. Expansion/material changes | Some thermal weakening/recession exists; rods, clearances, layered strips and thermal stress next |
| 8. Phase/vessels | Sparse enthalpy/latent heat exists; live inventories, support, density, pouring, boiling and condensation next |
| 9. Liquid/gas networks | Shallow water and 0-D gas exist; connected pressure/flow/mass/composition/energy equations next |
| 10. Hydraulics/pneumatics | Heated piston exists; pumps, cylinders, accumulators, seals, relief, choked flow and wall loading next |
| 11. Thermodynamic cycles | Heat/chemistry and piston work exist; reusable connected cycles and second-law constraints next |
| 12. Manufacture/processing | Finite reactions and energy convention exist; bounded physical transformation and persistent work in progress next |
| 13. Sensors/controllers | Engine-rate hoist controller exists; typed generic measurements/signals and bounded logic next |
| 14. Environment/harvesting | Water, terrain and prescribed thermal ambient exist; finite air zones, airflow/drag and solar exposure next |
| 15. Lifetime | Some irreversible thermal damage exists; declared load-history fatigue/wear/creep/corrosion next |

Use analytical/reference oracles, conservation audits, step refinement and
real installed-world scenarios for each capability. Material-dependent claims
retain matched glass/oak/iron comparisons. Parameter changes alone do not
establish a missing constitutive law. Optics, acoustics, resolved EM fields,
turbulence and elaborate chemistry follow a concrete machine need.
