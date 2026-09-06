# Banjo: project vision, physics contract, and complete development plan

**Thin-plate admission correction:** [The reported first-test failure](plate-admission-checkpoint.md) now has matching Python/native geometry preflight and a visible numerical error. An identical live prompt produces 42 actual 3D frames with an explicitly assumed 6 mm plate, then stops at 0.342 s with zero broken bonds in glass/oak/iron. Stable fracture remains open; this is a setup/UI correction, not new physics validation.

**Dynamic material playground:** [Property-authored coupled impacts](dynamic-material-playground-checkpoint.md) now execute explicit SI elastic/orthotropic/J2 descriptors through a bounded native API and render actual sphere and nodal states in the embedded 3D playground. Per-material contact/work/energy evidence and honest solver limits feed the GPT review. R08 is active; this is experimental computed playback, with spatial accuracy, unloaded dents, fracture, finite-strain rubber and realtime still open. All nine original workstreams and 40 mechanics are retained.

**General material rules execution:** [Ten implementation goals](rules-engine-execution-plan.md) are active. R01/R02 now have a property-based native material path and a bounded inertial tetrahedral foundation; coupled impact fracture, residual dents, finite-strain rubber, shared persistence and realtime qualification remain unfinished. All nine earlier workstreams and 40 mechanics remain retained.

**Composable experiment checkpoint:** [General experiment authoring](general-experiment-checkpoint.md) adds configurable comparative drops and freely composed initial scenes, typed GPT proposals, explicit fidelity and archived 3D results. Experimental6mm panels are admitted but fail the damage/refinement gate; no thin-shell, calibrated fracture or realtime claim is made. The [seven-stage execution plan](general-experiment-plan.md) retains all nine goals and40 requirements.

**Embedded 3D playground checkpoint:** [Chat-authored experiments and controls](embedded-playground-checkpoint.md) now connects GPT plans to native recordings and an in-page 3D viewer. Physical controls rerun the engine without another model call. All 58 native suites, 3 recorder tests and 49 mocked/control tests pass. This is bounded computed playback; integrated calibrated impact/deformation and realtime qualification remain open. All nine goals and 40 requirements are retained.

**Pressure API and assembled-solver checkpoint:** The [bounded pressure and stiffness implementation](continuum-pressure-performance-checkpoint.md) integrates partial-face loads and provides an optional same-law block-CSR solve. All 58 native suites pass (83.49 s); added pressure-state cases pass a subsequent focused rerun, and 33 mocked playground tests pass (2.164 s). Crossed mesh/load studies still fail the high-load spatial-accuracy gate; the finest iron mesh hits the explicit work cap. Kernel benchmark execution is smoke-tested, but repeated isolated performance qualification remains pending. All nine goals and 40 requirements remain retained.

**September 6 goal and playground checkpoint:** The [fully updated goal](project-goal-2026-09-06.md) groups all 40 retained requirements into nine workstreams. [New foundation evidence](playground-foundation-checkpoint.md) covers J2 permanent material state, bounded intrinsic variation, compact lossless numeric history, and a GPT-to-Banjo API playground. All 55 native suites and 29 mocked playground tests pass. Spatial dents, calibrated glass fracture, live-world persistence/repair and global realtime remain open.

**Additional physics checkpoint — September 6, 2026:** Opt-in cold-neighbor thermal activation now preserves stored energy, phase and reactive history while bounding active work. Mechanical damage trials support complete tick rollback, spring-configuration cache reset and explicit unresolved-limit diagnostics. All 52 regression suites pass; thermal storage scaling passes, while fracture convergence and full work closure remain open. See the [implementation, experiments and next gates](additional-physics-checkpoint.md).

**Material showcase:** [Iron-ball panel speeds and knife/tomato proxy](material-showcase.md) add genuine rigid spheres, matched glass/oak/iron clamped panels at 2/6/12 m/s, and explicit damage overlays. Wood has 0/0/11 broken links; glass has none at the authored step. All panels and the tomato retain a connected core containing all their cells. This demonstrates local damage, not validated glass shattering or a complete tomato slice. G02 is active; contact/time/space convergence and work closure remain open.

**Owner representation decision:** Voxel or sphere/particle matter may carry a separate appearance skin, with new surfaces generated from surviving matter and exposed interfaces after damage. The [skin contract](object-skin-contract.md) covers partial cracks, physical layers, material interiors, bounded remeshing and rendering/physics separation. Legacy blocky fragment surfaces exist; continuous live v2 skins remain planned. This is a documentation checkpoint, with no new physics-validation claim.

**Energy and phase foundation (current):** All 44 regression suites pass. The [world checkpoint](world-foundation-checkpoint.md) now includes strict [SI language packages](world-physics-language.md), bounded thermal/reaction jobs, and ice/water enthalpy with latent heat. Repeated sparse-world tests separate stored volume from active cost and expose overload backlog. Glass/contact accuracy remains an open mechanical gate; smoke and full fluid flow are deferred. The [plan](world-runtime-plan.md) and all 40 scorecard requirements remain in force.

**World foundation checkpoint:** The [runtime plan](world-runtime-plan.md) now prioritizes material-law correctness, sparse world storage, bounded active work, and named energy stores. The [initial implementation](world-foundation-checkpoint.md) adds thermal/reaction conservation, explicit backlog, a comparative visual lab, and mechanical temporal-resolution diagnostics. Four affected suites pass. Glass/contact correction remains open. Ice/water enthalpy and latent heat are next; smoke and full fluid dynamics are deferred by owner direction. All 40 retained mechanics/platform requirements remain in scope.

**Current checkpoint:** `61c5edc` is published on main; 39 suites pass. The [v2 evidence](network-runtime-checkpoint.md) adds local damage and permanent axial deformation while exposing unresolved cutting convergence, stiff-wave behavior and whole-world performance. These results advance the platform implementation without completing the physical-validation or publishing goals below.

**Platform-first direction (current owner priority):** Banjo is a Unity-like, LLM-accessible physics authoring and publishing platform for game makers. Inventory, crafting and progression are the first customer application, not the engine roadmap. Preserve all physics and publishing requirements; require measured near-real-time execution alongside correctness. The bowl is the first extensible conformance and performance laboratory, not the product boundary. [Platform SDK checkpoint](platform-sdk-checkpoint.md) implements an inventory-independent runtime, 17 executable scene packages and headless/visual clients. Automatic physical LOD and full publishing remain open. Earlier customer-first priority notes below are historical and superseded.

**Material-network v2 checkpoint (experimental):** [Network runtime checkpoint](network-runtime-checkpoint.md) adds the `material-network-v2` / `banjo-network-2` backend for property-driven boxes and ellipsoids represented by occupied cells, plus rigid convex wedge tools. Springs, contact and gravity advance on one physical clock; local cohesive damage and an axial perfect-plastic demonstrator change the active network state. Oak uses a directional axial lattice approximation, not a full grain continuum; the ductile demonstrator is not calibrated iron. Glass stiff-wave response remains under-resolved and unreliable, and the older v1 pulse backend remains selectable. The implementation is experimental: clamped panel boundaries are not door hinges, a damage front is not a complete carved chip, and local refinement, adaptive scheduling, and strain/contact/damping/energy closure remain immediate gates before any surrogate-learning work. No RL/neural training or world-scale realtime claim is made.

**Rolling/fracture correction:** [Strength gate and computed replay](rolling-strength-checkpoint.md), source `aa3491f`, local only. Glass/oak/iron isolated rolling is damage-free over 0.3 s; strong glass impact still fractures progressively. The native eight-ball 1.25 s replay moves visibly and ends with four broken links but eight connected groups; contact attribution remains open. Calculate prepares a fresh trajectory, then Replay shows normal-speed motion. Coarse contact geometry, continuum calibration and the full platform remain unfinished. Earlier energy-only bowl notes below are historical.

**Fracture now runs in the bowl:** [Experimental bonded-cell checkpoint](bonded-bowl-checkpoint.md) connects crafted balls to local energy-driven failure, surviving internal networks and continued curved-support/multiple-body contact. Glass fractures during release; oak and iron retain elastic connections. Source `f55f996`, UI `a939df0`, local only. This is a slow, coarse 19-cell model with uncalibrated strength and contact geometry, not the completed realistic-fracture gate.

**Interactive fracture microscope:** [Visual checkpoint](fracture-microscope-checkpoint.md) connects accepted solver trajectories to the native bowl app, with glass/oak/iron comparison, four impact speeds, playback, scrubbing and event stepping. Source `413852a`, local only. Both affected suites pass in promoted and legacy builds. This is the eight-region connector reference; whole-ball fracture and live bowl fragment contact remain open.

**Owner fracture-propagation requirement:** impact loads a local region, forces and waves propagate through connected matter, and later damage follows the evolved state. A first break must not shatter every connection. Preserve surviving cores and internal state in detached fragments so later failures can arise physically. Numerical recursion may refine time/space; it must not prescribe a destruction tree. See [cascade evidence and remaining integration](rupture-cascade-checkpoint.md).


**Immediate owner priority: craft-and-release bowl lab.** Complete inventory-backed glass/oak/iron ball crafting, placement/release in an adjustable concave bowl, rolling/collisions/rebound and physically driven fracture before moving to the next physics family. The [bowl checkpoint](bowl-checkpoint.md) records the new running rigid preview and the explicit unfinished fracture gate. Broader assembly contact research is paused, not discarded. Preserve every existing mechanic and platform gate.


**Owner first-person/LitRPG requirement:** build a small Minecraft-like starting world viewed through the player’s eyes, with no rendered body parts. Clicking world materials collects them into inventory; clicking the crafting table offers possible designs and exact shortages. Successful actions award experience and levels gate crafting/actions. Gathering and building consume energy; crafted tools should reduce later gathering effort. Branch cutting must eventually follow supported physical loads, material/tool response and failure, then collected matter becomes raw voxel materials with its substance/quantity preserved. Keep level/game rules distinct from physical laws, model conversion energy/state explicitly, and connect this world to the LLM creator. The [starter checkpoint](starter-checkpoint.md) implements a limited gameplay version; it does not discharge the realistic-physics or energy requirements.

**Owner inventory requirement:** collected resources belong in the user’s inventory. A natural-language creation request must explain what is possible with that inventory or precisely what else is needed. Preserve requested dimensions/material when short, distinguish held material from world pickups and selected recovery, and offer alternatives explicitly. Extend the requirements bill to energy sources, capable tools/processes and supported behavior as those models are implemented; missing capability is distinct from missing supplies. Queries must not spend resources. [Current implementation and acceptance evidence](requirements-checkpoint.md).

**Start here.** This is the durable project brief for a new developer or coding agent. It consolidates the project owner's goals and the architecture discussed while building the prototype. The ball laboratory is the proving ground, not the final product.

Read [development status](development-status.md) next for what actually exists, where it is committed, verification evidence, and known defects. Read the [roadmap](roadmap.md) for ordered work and acceptance gates. A design in this document is **not** an implementation claim. Current source and test evidence take precedence over older descriptions of completed work.

Owner's comparative-testing requirement: material-dependent experiments always include at least glass and oak (wood), retaining iron as the third reference and accumulating earlier substances as new ones are added. Use identical declared geometry, conditions and numerical settings unless an experiment explicitly controls mass or another variable. Report results and unsupported laws per substance. Maintain the [mechanics scorecard](mechanics-scorecard.md) with the status, evidence and next step for every retained mechanic and platform capability.

## 1. Product we are trying to build

Owner energy requirement, September 4, 2026 Pacific: [energy stores, fabrication work and bond/interface changes](energy-system.md) must become part of the same material-backed creator contract. Making, reshaping and breaking require identified work sources and accounted consequences; material recovery does not refund spent energy. Physical impacts supply their own energy, and formation versus separation must follow the implemented law. The current authoring sandbox has no energy cost or manufacturing model. Add source/process/power limits and a combined transaction ledger with glass/oak/iron acceptance tests; this extends the application requirements without closing the existing physics gates.

Owner application priority: users collect materials in a virtual world, ask an LLM to make an object from what they have, and use the resulting object under supported physics. Carry a small version of this experience through foundation work. The [first creator loop](creator-loop.md) specifies inventory, inspectable requests, material/capability validation, atomic creation, physical testing and revision. The [first rigid-sphere workshop](creator-checkpoint.md) now exercises collected inventory, manual Codex proposals, independently validated creation and saved state. The [automatic Windows assistant](assistant-checkpoint.md) now returns validated proposals or clarifications. [Oriented solid boxes](shape-checkpoint.md) now use that same creator/compiler path. Normal verification of the new controls and safe object revision/reclamation are the next application milestones; the complete authoring/publishing platform remains the objective.

Banjo is a publishing and creation platform for interactive worlds whose **materials and laws of physics are editable**. It combines Minecraft-like construction with a deeper material model and eventually an engine/platform alternative to authoring every interaction manually in a conventional game engine.

A creator should describe matter, geometry, assemblies, fields, and laws. The engine determines movement, contact, deformation, damage, and failure from those declarations. AI should be able to author the same inspectable language and use the same APIs as a person. It should not need to invent special-purpose engine code for every object.

The central examples are:

- Assemble wood into a door and metal into hinges and fasteners. Geometry and material distribution determine mass and inertia; the hinges constrain movement. A strike may crack the panel, pull an attachment out of the wood, or yield a hinge, depending on the physical model and properties.
- Roll an iron sphere into a glass sphere. A small contact need not break anything. Sufficient stress and available energy activate detailed material simulation, bonds fail, and newly disconnected pieces move and collide. Neither shard boundaries nor flight paths are supplied by an animation.
- Change material, surface properties, slope, or gravity. Rolling, slipping, rebound, fracture, and landing must change for the relevant physical reasons, not because an object has a particular name.
- Anticipate expensive interactions and compute several possible outcomes before contact. Reuse a result only when the actual state lies within its demonstrated applicability; otherwise refine or simulate live.

The long-term publishable unit is a versioned world or universe package, including laws, material definitions, procedural assets, behaviors, tests, dependencies, and permissions. Creators should also be able to publish reusable materials, law packs, machines, and generators.

## 2. What “first principles” means here

The target is physically grounded mechanics with explicit, testable constitutive laws—not an assertion that all real materials can be reconstructed from density and color, or that each voxel is an atom. Voxels and lattice points are numerical samples of matter. A spring/bond lattice is one replaceable numerical model, not a theory of all matter.

Mass distribution, forces, torques, momentum, energy, constraints, contact, and material response must have traceable meanings. Friction, damping, strength, flaws, plasticity, and fracture require constitutive assumptions and measured/calibrated inputs. A few scalar properties do not uniquely determine every behavior. A fitted parameter is acceptable when its purpose, units, provenance, valid domain, and uncertainty are visible.

The engine must distinguish:

1. **Authored intent:** unit-bearing physical quantities, geometry, state, and chosen law/model.
2. **Compilation:** conversion to a particular solver, discretization, timestep policy, and coefficients.
3. **Approximation:** homogenization, rigid treatment, collision proxies, reduced detail, or cached outcomes with stated limits.
4. **Validation:** tests and evidence that establish which behaviors the implementation reproduces.

The project must not claim realistic glass, ductile iron, viscoelastic rubber, or anisotropic wood merely because those names appear in a preset menu. Unsupported behavior should be reported or rejected, not silently simulated as an unrelated material.

## 3. Non-negotiable principles

- No pre-authored fracture chunks, shatter animation, explosion pulse, or arbitrary shard launch velocities in the authoritative physical path. An intact lattice and reproducible defect distribution may be generated in advance; failure topology must result from the interaction.
- No material-name conditionals such as `iron + glass => shatter`. Dispatching a declared constitutive model is legitimate; choosing an outcome by a display name is not.
- Matter, not a render mesh or a simplified collision hull, determines mass, center of mass, and inertia.
- Do not enforce rolling by continually assigning `omega = n cross v / r`. That equation can initialize a chosen experiment; contact friction and torque determine subsequent motion.
- Do not double-apply a collision impulse during a rigid/material transition. Separate internal damping from environmental drag, contact loss, and rolling loss.
- Account for external forces and constraints when checking momentum and energy. Gravity changes momentum; a fixed floor exchanges impulse with the simulated bodies. Those are not conservation violations, but they must appear in the ledger for the chosen system boundary.
- Physics detail and scheduling must not secretly change material strength. Rendering detail may change independently.
- Cache misses, budget exhaustion, and unsupported laws require explicit fallbacks. Never substitute an unrelated prerecorded outcome to hide a missed frame budget.
- State “implemented,” “experimental,” “validated within these bounds,” and “planned” separately. A green build is not a material validation certificate.

## 4. Matter representation and deferred physicalization

The key performance idea is **deferred physicalization**: retain a cheap representation until an interaction requires detail, then activate only the relevant material and return stable pieces to cheap representations.

The intended source of truth is:

```text
object = procedural geometry + spatial material field + sparse state changes
```

A box, sphere, constructive-solid-geometry expression, signed-distance field, or imported solid can define the initial occupied volume. A material field answers what exists at a location and its orientation, phase, or interface. Damage, removed volume, deformation history, temperature, moisture, and embedded foreign material are changes to that original description.

Do not allocate every possible voxel throughout a world or every dynamic array inside an intact object. Shared material IDs and palettes replace copies of every material coefficient in every cell. Dynamic state arrays are allocated where needed. Start with compact arrays for a small active ball; introduce sparse hashed bricks and a parent hierarchy for larger objects. Repeated undamaged templates can be shared with copy-on-write changes.

Movable volumes live in object-local coordinates and move using a rigid transform. Rotating a door must not resample it into a global grid every frame. World-space chunks remain appropriate for terrain. On fracture, pieces retain stable identities, provenance, material, damage, and ownership of their portion of the matter.

### Physical hierarchy

The proposed “Matter Pyramid” stores aggregate mass, center of mass, inertia, occupancy, bounds, material distribution, effective stiffness, damage, and estimated failure envelopes. A coarse query asks whether a region is safely rigid, clearly requires refinement, or is uncertain.

These bounds and effective properties are research/engineering work, not already solved. A coarse local estimate may miss stress transmitted through the rest of an assembly. Refinement rules must include boundary loads, supports, fasteners, stress propagation, and uncertainty, rather than only distance to a visual impact mark.

### Simulation modes

```text
procedural/asleep -> rigid -> articulated or active material patch
                                      |
                                      v
                            damage and component split
                                      |
                                      v
                         rigid fragments / declared debris
```

Later solver families may use continuum grids, particles, or material points for fluid-like or severely deforming matter. One authoring system need not mean one numerical solver for everything.

Whole-ball activation is intentional in the current prototype. Local patches, boundary coupling, adaptive growth, hysteresis against mode oscillation, and re-coarsening are still future work. Promotion and demotion must explicitly transfer state and preserve the accounted quantities within declared numerical tolerances.

## 5. Complete material and interaction contract

This table is the **target inventory**, not a list of fully functioning features. The status document separates live parameters from declared or future ones.

| Layer | Authored characteristics | Intended consequence |
|---|---|---|
| Geometry and mass | Occupancy, dimensions, density field, voids, shell thickness, layers | Mass, center of mass, full inertia tensor, contact shape |
| Elasticity | Young's modulus, Poisson ratio, shear/bulk response, anisotropic stiffness, orientation | Reversible deformation and stress transmission |
| Strength and plasticity | Tensile/compressive/shear strength, yield surface, hardening, rate dependence | Crack initiation versus permanent deformation, crushing, or yielding |
| Fracture | Fracture energy, mixed-mode failure, flaws, damage history, fatigue | Work required to create cracks, path and fragmentation behavior |
| Dissipation | Internal damping or viscosity, contact damping/restitution, rolling resistance | Named energy losses, rebound, settling, and stopping |
| Surface/interface | Static/dynamic friction, roughness, coating, lubrication, adhesion, welds, glue, fasteners | Stick/slip, transfer of loads, separation and interface failure |
| Structure | Grain, laminations, fibers, porosity, defect field, seeded variation | Direction-dependent response and heterogeneous failure |
| Thermal/state | Temperature, heat capacity, conductivity, thermal expansion, phase thresholds, moisture | State-dependent mechanics, heat transfer, phase changes |
| Appearance | Color, roughness, opacity, refractive properties, fracture-surface appearance | Rendering only unless an explicit physical coupling is declared |
| Provenance | Model/version, units, calibration data, valid range, uncertainty, seed | Reproducible and honest authoring, tests and caching |

Hardness and strength are not interchangeable. Bulk density is not an interface coefficient. Restitution is not uniquely determined by density or stiffness; deriving it from a damped-contact model introduces a particular approximation. Combining two friction coefficients by a simple rule is a policy, not a universal first-principles law. Keep such assumptions replaceable and visible.

The intended compiler validates dimensions, positivity and admissible ranges, chosen solver capabilities, resolution dependence, and unsupported characteristics. It produces immutable compiled laws plus mutable material state. Later temperature, electric, chemical, or fictional field laws should be added as explicit solver families and couplings, not as unused fields that appear to work.

### Resolution calibration

A fixed force-per-bond failure rule changes object strength when the number of bonds changes. Instead, derive/calibrate discrete stiffness and failure work from represented lengths, areas, volumes, neighborhoods, and fracture energy. Avoid counting the same crack area repeatedly across a long-range bond horizon.

Test convergence of mass, stiffness, initiation load, dissipated work, and broad fragmentation outcomes across resolution, timestep, iteration count, and grid orientation. Exact shard identity need not match across resolutions; outcome envelopes and conserved quantities should converge. Refinement must transfer prior damage and stored energy rather than heal or strengthen an object.

## 6. Balls as a controlled physics laboratory

The ball scene should become a collection of controllable experiments, not just a dramatic collision. Vary radius, shape/mass distribution, material, initial translation and spin, impact offset, support material, slope, gravity, and numerical resolution independently. A measured contact-point slip readout must distinguish rolling, sliding, spinning, resting, and airborne motion.

Reference relationships used as test oracles include:

```text
homogeneous solid sphere: m = density * (4/3) * pi * r^3
                         I = (2/5) * m * r^2
contact velocity:        v_contact = v_COM + omega cross r_contact - v_surface
no-slip incline:         a = g_parallel / (1 + I/(m*r^2))
```

The no-slip incline result assumes adequate static friction and no rolling loss or environmental drag. Same-shape homogeneous balls do not accelerate differently in ideal gravity merely because one is denser. Different inertia distributions, slipping, deformation, and dissipation can produce differences. Tests should catch a model that invents a density dependence where the reference predicts none.

An initially translating, non-spinning solid sphere on a level frictional surface is a useful slide-to-roll test. With kinetic friction, no rolling resistance or drag, and no other force along the plane, the final rolling speed is `5/7` of the initial speed. Frictionless sliding should not spontaneously turn into rolling. Backspin and overspin should evolve through contact, not through a velocity reset.

Required experiment families include free flight, rebound/drop, flat sliding, slide-to-roll, incline rolling/slipping, material-pair collision, off-center collision, brittle failure, repeated impact, floor-triggered damage, and fragment landing. Use run configurations and time-series diagnostics so observations can be reproduced without mouse timing.

## 7. Authoritative contact, damage, and fragment handoff

The intended interaction pipeline is:

1. Broad/narrow phase identifies a real or imminent contact and the relevant material/interface state.
2. A cheap conservative screen decides whether rigid response is sufficient or detailed material is needed. Hertz-like sphere screening is only an elastic approximation; it cannot dictate an exact crack outcome.
3. Exactly one solver owns the contact response. A rigid contact being activated must not also receive the old rigid collision impulse.
4. Activate the material at a well-defined time and transfer mass, position, orientation, linear/angular momentum, and internal state.
5. Couple the material to the rigid counterpart, supports, and neighboring material. Contact impulses have equal-and-opposite reactions and correct torque arms. Separating contacts must not attract.
6. Deformation and the constitutive failure rule change damage and connectivity. Available work constrains irreversible fracture and plastic work; arbitrary extra energy is forbidden.
7. Surviving connectivity defines pieces. Recompute mass properties from each piece's matter, generate visual surfaces and appropriate collision proxies, and transfer motion to rigid bodies when the approximation is admissible.
8. Continue gravity, contact, sliding, rolling, and sleeping. Pieces remain material-backed so later interactions can reactivate and fracture them again.

Synchronize the rigid and material clocks. Subcycling cannot advance one body twice, omit the counterpart's reaction, or apply a future fracture state at the current time. Positional penetration correction must be measured separately from physical impulse; numerical stabilization is not free energy.

The current developmental coupling is sphere-to-material-point contact. General shapes, material self-contact, multiple simultaneous active objects, compliant interface patches, and contact accuracy under rapid motion need further work. A point lattice without self-contact may interpenetrate after bond failure.

### Finite-cell angular momentum and energy

Mass points do not automatically carry the intrinsic rotation of finite volume elements. Including cube inertia in a fragment while omitting corresponding spin state can make rigid/material conversions inconsistent. Audit both orbital and intrinsic contributions instead of asserting conservation because a matrix inverse exists.

Rigidifying a deforming component can remove internal kinetic/elastic energy. Record that residual and make the coarsening criterion explicit. Likewise, lightweight debris preserves mass bookkeeping only if it continues to represent all material; that alone does not prove correct angular momentum, contacts, or energy.

## 8. Gravity, supports, and assemblies

Gravity is a world acceleration field independent of the support orientation. Every representation and predictor uses the same field and geometric frame. Test downward, reduced, sideways, reversed, and zero gravity. A tilted floor must not leave material nodes or debris colliding with a hidden horizontal plane.

A support surface has finite extent and thickness. Leaving its edge must permit a fall; proximity to an infinite mathematical plane is not sufficient evidence of support. Ultimately use actual contact geometry and normal reaction, including transient and dynamic loads, rather than assuming the normal force is always `m*g`.

Assemblies should use semantic joints backed by actual materials and interfaces. A hinge declaration supplies a revolute axis and intended degrees of freedom; attachment regions connect to wood/metal that can fail. Do not try to infer screw threads and bearing tolerances from a coarse game-scale voxel grid. The door's mass/inertia still comes from its material distribution, and a failed anchor changes the assembly constraints.

The door-and-hinge demonstration follows validated balls: swing under torque/gravity, bend or crack under load, detach an anchor when its backing matter fails, and preserve motion after separation. It is a test of structured objects, not permission to script their failure.

## 9. Forward projection, speculative work, and precomputation

There are three distinct levels:

**Analytical projection:** cheap estimates of masses, impact energy, elastic contact force/pressure, expected regime, incline motion, and operation counts. Useful for planning, not authoritative future motion. The current CSV tool is this level.

**Solver-generated outcomes:** results produced by the same physical model used live. Prototype serialization exists, but integration, complete keys, validation, and time-consistent reuse remain work.

**Speculative scheduling:** identify likely contacts before they happen, compute several candidate continuations using spare CPU/GPU time, and select/revalidate when the actual contact is known. This scheduler does not yet exist.

The scheduler should rank candidates using contact likelihood, lead time, uncertainty, expected solve cost, and saved latency. It may prebuild an intact lattice, collision data, or mesh allocations even when no fracture outcome can safely be cached. Cancel or invalidate candidates when forces, player inputs, geometry, materials, supports, or state change. Measure net benefit; speculation can cost more than it saves.

### Required cache identity and applicability

A future authoritative key must cover geometry and material-content hashes, constitutive and compiler versions, interface law, existing damage/plastic/thermal state, radius/mass distribution, relative position/orientation, contact location/normal, both linear and angular velocities, gravity and support/boundary conditions, neighboring interactions, resolution, horizon, timestep/substeps/iterations, integration/correction settings, seed, and backend/numerical provenance where it affects reproducibility.

The present preset-based quantized keys are not complete for arbitrary edits. Equal quantized values or matching node counts are not proof of physical equivalence. Prevent stale results when a preset's underlying properties change, a timestep changes, or a spinning ball matches a non-spinning scenario by translational speed alone.

Rigid transforms or velocity offsets may be factored out only when the full problem has the relevant symmetry. Rotating a contact without rotating the gravity, support, grain, or other boundaries is not generally equivalent. Surface-relative velocities matter when applying a boost.

Use exact validated matches first. Interpolation near crack initiation, phase changes, or different connectivity is unsafe without explicit error bounds; do not blend incompatible shard lists. Cache a trajectory/checkpoint sequence or a rigorously time-aligned transition, not a future terminal state teleported into a single frame. Resume live simulation for gravity and subsequent contacts. If an unforeseen third object enters, invalidate the relevant future.

## 10. Rendering is a replaceable view of matter

Voxels versus ray tracing is not a choice between competing equivalents: one concerns representation, the other image formation. A volume can be ray traced or meshed; a visually smooth sphere can contain a volumetric material model.

The prototype uses raylib as a practical window/input/render shell. Keep rendering outside the physics core. Current exposed voxel faces are useful for inspecting generated topology; they are not the desired final visual fidelity. Future meshes should show new interior fracture surfaces, material orientation, and coatings without inventing changes in mass.

The earlier production direction was SDL3, Dawn/WebGPU/WGSL compute, and Dear ImGui. These remain candidates, not dependencies to add before the physical model is measured. Sparse-brick editing, surface extraction, lighting, mesh simplification, and GPU buffers should be replaceable caches of matter. Far or unchanged objects can use cached meshes; active regions and volumes can use other render methods. Transparent/refraction-heavy glass comes after opaque geometry and physics are reliable.

## 11. Language, APIs, and AI authoring

The working language name is **LawScript**; the grammar and name are not final. Begin with a schema-validated, unit-aware intermediate representation rather than prematurely building a large general-purpose language.

Planned declaration categories are `material`, `shape`, `assembly`, `field`, `interaction`, `transition`, `behavior`, `policy`, and `test`. The compiler should recognize efficient computation patterns: local neighborhoods, sparse constraints, field solves, accelerated long-range interactions, and events. Authors should not write quadratic loops over every voxel.

The execution contract declares units, model capabilities, interaction range, conservation/external-work behavior, determinism scope, memory limits, active-element limits, and solver/timestep requirements. Fictional laws may intentionally add energy or violate familiar constraints, but only explicitly, observably, and within resource/safety limits.

Separate permission tiers: parameter editing; composition of trusted law primitives; reviewed expert solver plugins. Do not permit arbitrary AI-generated GPU kernels, unbounded loops, filesystem/network access, or unmanaged allocation in untrusted published worlds. A sandbox such as a constrained WebAssembly interface is a candidate for high-level behaviors, not a requirement for per-voxel arithmetic.

The desired AI workflow is:

```text
creator intent -> inspectable declarations + tests -> validation/compiler
               -> bounded simulation/measurement -> revision -> approval/publish
```

AI is an authoring tool, not a necessary participant in every physics tick. The creator should be able to inspect and reproduce the source without a model call. APIs should expose material/shape creation, assemblies, fields, simulation control, events, queries, diagnostics, serialization, resource budgets, and test execution. A material property change must produce an observable, testable change where its law predicts one.

## 12. Publishing, persistence, and multiplayer

The proposed universe package contains a manifest, source laws/materials/shapes/assemblies/behaviors/tests, runtime/physics ABI version, dependency lock, calibration/provenance, capability permissions, deterministic seeds, budgets, and optional compiled caches.

World persistence stores procedural recipes plus state changes, fragment lineage, assembly/interface state, and version metadata. It must reconstruct current matter, not just screenshots or surface meshes. Migration must be explicit when material/solver versions change.

Publishing needs validation, preview, packaging, distribution, remix/version rules, capability checks, and safe execution. A machine can declare that it needs rigid bodies, revolute joints, and anisotropic fracture before being imported into another world's law set. Marketplace economics, hosting architecture, and product policies remain undecided; they are not prerequisites for the ball solver.

Multiplayer requires an explicit authority model, reproducible inputs/events where feasible, stable IDs, snapshots/corrections, bandwidth budgets, and version agreement. Do not promise bitwise cross-platform GPU determinism without proof. An authoritative host/server with state correction is a possible design to evaluate. Persistence, multiplayer, and publishing services are not implemented in the present laboratory.

## 13. Engineering structure and library choices

The current stack is C++23/CMake, Jolt for rigid motion/collision, a custom CPU material solver, and raylib for visualization. Keep `banjo_core`, `banjo_runtime`, and viewer responsibilities separate.

The long-term module boundaries are matter storage/hierarchy; material/interface compilation; contact/synchronization; deformable/fracture backends; fragment/assembly lifecycle; prediction/cache/scheduling; geometry/render caches; authoring/compiler/sandbox; persistence/networking/publishing; and diagnostics/tests.

Earlier research considered OpenVDB for volume tooling, NanoVDB for appropriate GPU/static caches, Warp/Taichi for experiments, and peridynamic/FEM tools for reference comparisons. These are options, not installed runtime features. No library eliminates the need to validate constitutive laws, conserved transfers, mutation semantics, and real-time budgets. Do not change the toolchain solely to make the demo look more advanced.

## 14. Validation and performance gates

Maintain an automated truth table for each claimed property: compiler consumer, solver consumer, observable, test, tolerance, and reference/calibration source. Show unsupported or screening-only properties clearly in authoring tools.

Record a conservation ledger over well-defined boundaries: mass; COM; linear/angular momentum; translational/rotational/internal kinetic energy; recoverable strain energy; gravitational/external work; fracture/plastic work; contact/rolling/damping loss; coarsening/correction loss; and numerical residual. Pairwise impulse tests are necessary but do not establish whole-scene correctness.

Use deterministic seeds and ordering; record runtime, compiler/backend, timestep, iterations, material content and geometry with every experiment. Test rotated scenes, changed grid axes, changed density, impact-angle sweeps, high speeds/CCD, near-rest contacts, low gravity, and unsupported surfaces. Use separate tolerances for double-precision core and single-precision rigid integration. Do not widen a tolerance without recording the numerical reason and retaining a meaningful bound.

Profile rigid stepping, activation/allocation, contact, constraints, damage, connectivity, mass properties, hull construction, meshing, GPU upload, and cached-outcome verification separately. Track active nodes, bonds, fragment count, memory, latency percentiles, discarded work, cache hit rate and validity failures. A 60 Hz display target on a named reference machine is an engineering target, not a measured guarantee.

GPU migration follows a working CPU reference and measured bottlenecks. Parallel kernels must retain error/conservation tests. For larger scenes use physical LOD, sparse bricks, sleeping, bounded debris policies, asynchronous resource preparation, and validated speculation rather than silently changing the physical law.

## 15. Completion criteria and immediate direction

The next checkpoint is a trustworthy ball laboratory: measured rolling/sliding; conservative continuous sphere/material contact; fracture with explained work and stable resolution trends; material/surface/gravity/slope controls; repeatable tests; and clearly labeled approximations.

A useful engine V1 then adds arbitrary supported geometry, repeatable/repeated fracture, local activation/re-coarsening, material-backed assemblies, persistence, and a bounded unit-aware authoring API. A publishing-platform V1 additionally requires safe packaging, validation, distribution, versioning/remixing, and AI-generated declarations/tests. These are different completion levels; a successful ball demo does not complete the platform.

Follow the [roadmap](roadmap.md). First reconcile the experimental contact branch with current main, preserve concurrent build fixes, inspect the now-successful CI, audit full-system energy and angular momentum, and fix over-fragmentation through the model rather than visual shortcuts. Then widen material/geometry coverage, establish adaptive performance, integrate validated precomputation, and build authoring/publishing on that foundation.

## Source of this brief

The product requirements and architecture come from the project owner's Banjo conversation: editable in-world physics; procedural voxel matter; wood/metal door assemblies; emergent iron/glass ball fracture; physically driven material changes; gravity and tilted supports; proactive multiple-scenario computation; and AI-accessible language/APIs plus publishing. Repository evidence and exact branch/verification links are maintained in [development status](development-status.md). This brief preserves the intent without turning unimplemented proposals into claims of completion.
