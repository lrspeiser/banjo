# Banjo world physics actions and implementation plan

October 7, 2026. Source baseline on main: `f413326a8f56420e269ae08386e1c3b360fc6367`. This is an implementation proposal, not new physical validation. It covers the retained inorganic game world, its editable tools and machines, and the transfers between terrain, loose matter, inventory and manufactured products. Coal, water and ice are included. Organic gameplay remains excluded; oak stays in the comparative laboratory. Full smoke transport, biological mechanics and general fluid dynamics remain outside the current product scope.

The first deliverable must be ordinary pickup and a physical swing that actually damages a bonded glass target. Collision-only success cannot complete that milestone. The existing fracture implementation is retained and tested while its missing world coupling is completed.

## Free form live simulation requirement

Owner clarification, October 7: the player must choose actions freely and see reactions computed from the current world. This requirement applies to every A01–A48 capability as it becomes supported. A scenario supplies editable starting conditions; it cannot prescribe the player's targets, sequence, impact time, failed bonds, shards or final state.

- The sandbox stays live after loading. Players can move, select any reachable supported object or surface, acquire a whole tool, place or reposition objects, change the arrangement and use supported actions in any order. Contact is queried against actual current geometry, including fresh fragments and newly excavated surfaces.
- One shared interaction interface exposes context-appropriate actions and bounded force/work controls. The same physics handles the same action on any admitted geometry/material/state; a scene name, object ID or recipe name cannot choose a response. New authored tools require supported grip, working geometry, actuation and capability declarations, then enter that interface.
- A strike calculates motion/contact, damage and topology from the actual tool, actor, target, support and accepted histories. Subsequent strikes start from the state the previous interaction left. Players can interrupt, drop, change target, remove a support, hit a fragment or return later; the engine must preserve physical continuity.
- Rendering follows accepted simulated states. There is no predetermined reaction playback, fixed shard layout, cosmetic cut, assigned launch motion or hidden input script in the playable mode. Automatic cached simulation-outcome reuse is disabled for this acceptance mode. Compiled geometry, material parameters and solver setup may be reused as inputs; they do not contain the reaction.
- Sandbox authoring can insert or edit declared matter as an explicit external state change with provenance and accounting. Ordinary gameplay manufacturing still consumes resources/work. Creation mode must not silently become a free physical-work source during an action.
- In unsupported regimes, the interface names the missing law or numerical limit. That refusal is an unfinished capability, never a substitute reaction. The live sim must meet the interaction performance gates; a delayed recording cannot qualify as free form play.

**Manual acceptance:** start a fresh live world; pick an arbitrary reachable point; vary angle/strength and target support; repeat on the actual changed object; interact with the resulting matter; then save/reload and continue. Repeat with an edited arrangement and an unfamiliar authored tool. The player can perform these steps independently without an agent preparing the exact click or initiating a hidden experiment. Automated tests use varied positions, orientations, action order, materials and prior damage through the same public commands, and compare physical invariants and supported response trends. Their fixtures are reproducible starting states, not precomputed outcomes.

## Present boundary

- [The rewrite audit](banjo-rewrite-audit.md) recommends one Rust world owner around the existing C++/Jolt engine, with renderer-independent simulations and one command protocol.
- [Held contact integration](held-strike-hand-checkpoint.md) already connects a native tool and shared hand controller to a deformable target reference. It does not include the normal player's complete interaction, finite surrounding world and general fracture handoff.
- [Coupled manifold experiments](coupled-manifold-checkpoint.md) still have glass convergence/refusal failures. They must not be promoted by relaxing their acceptance bounds.
- [The current swing sandbox](glass-swing-world-checkpoint.md) has actual rotating native motion but rigid targets. It deliberately does not run internal fracture.
- Water, thermal, material, structural and energy code have measured subsets. The mechanics scorecard remains the authority for those specific boundaries; the list below specifies the intended end-to-end behavior.

## Actions and their required physical reactions

Each row is a contract for the final integrated world. Existing source code is a starting point, not evidence that the whole row already works. Stage references identify where it is implemented and qualified.

### Motion and contact

| ID | Action | Required reaction | Stage |
| --- | --- | --- | --- |
| A01 | Release or drop an object | Gravity changes its momentum; it lands, bounces or settles according to contact and material state | 1, 2 |
| A02 | Push or pull | Both bodies receive opposite forces; actual mass, inertia, support and friction determine motion | 1, 4 |
| A03 | Twist or strike off centre | Torque produces rotation with the actual inertia tensor and counterpart reaction | 1, 4 |
| A04 | Slide over a surface | Measured slip drives static/sliding friction, resistance and separately accounted losses | 4 |
| A05 | Roll or spin | Contact friction couples translation and rotation; declared rolling resistance slows motion | 4 |
| A06 | Tip, stack or balance | Real supports and centre of mass determine stability; changing support wakes affected bodies | 2, 5 |
| A07 | Collide at speed | Swept contact prevents tunnelling; native/material contact receives one authoritative response | 1, 4 |
| A08 | Walk, climb a step or jump | Bounded actuators push against actual support; slopes, obstacles, footing and carried load matter | 4 |
| A09 | Pick up, carry, equip or drop | Whole connected ownership is acquired; bounded grip and reach apply; unsupported loads refuse or release | 1, 4 |
| A10 | Carry cargo on a rover or platform | Cargo changes mass, COM and inertia and loads its restraints; it can shift or fall when unsecured | 4, 8 |

### Solids, tools and terrain

| ID | Action | Required reaction | Stage |
| --- | --- | --- | --- |
| A11 | Stretch, compress, bend, shear or twist a solid | Material and cross-section determine deformation, stored elastic energy and recoil | 5 |
| A12 | Buckle a thin post or panel | Geometry, imperfections, loading and boundary conditions determine instability | 5 |
| A13 | Strike glass, ceramic or rock | Local stresses/damage and declared fracture work produce emergent cracks and components | 1, 2, 5 |
| A14 | Strike or form metal | Elastic response becomes permanent plastic deformation when the implemented yield law is exceeded | 5, 10 |
| A15 | Crush concrete or mineral material | Supported compressive damage law creates compacted/broken matter; tensile fracture is distinct | 5 |
| A16 | Strike an already damaged fragment | Existing damage/history continues; contact and further failure are solved without healing or double response | 2 |
| A17 | Dig soil, sand or rock | Contact, delivered work and supported material law release actual source constituents, leaving an exact hole | 3 |
| A18 | Shovel or hoe loose material | Tool surface and resistance move/shear the grains; a scoop transports matter through contact or supported containment | 3, 6 |
| A19 | Excavate under a bank or structure | Ground loses support; remaining banks slump and structures settle or collapse as appropriate | 3, 5 |
| A20 | Heap, compact or collect debris | Released matter settles and can be transferred once; placement/compaction consumes actual matter and work | 2, 3, 10 |
| A21 | Cut, saw, drill or grind | Edge/contact geometry and delivered work remove constituents; offcuts, chips, friction and wear are retained | 6 |
| A22 | Pierce, embed and withdraw | Resistance sets penetration depth; local material holds the tip; extraction and subsequent failure retain reactions | 6 |
| A23 | Use a tool repeatedly | Supported wear/fatigue laws evolve its edge, section or damage; its working capacity changes and it can break | 6 |

### Assemblies and machines

| ID | Action | Required reaction | Stage |
| --- | --- | --- | --- |
| A24 | Fasten, weld, bond or repair parts | A paid process creates a finite material interface; repairing adds/replaces matter instead of erasing history | 5, 10 |
| A25 | Load a hinge, slider, bearing or fastening | Constraint reactions carry force and moment; finite capacity/slip/opening and failure persist | 5, 8 |
| A26 | Build a wall, pillar, bridge or foundation | Loads propagate through contacts and material interfaces; removing supports produces physical failure | 5 |
| A27 | Stretch a spring or tension a metal cable | Stored energy and tension follow implemented laws; attached bodies receive equal reactions | 5, 8 |
| A28 | Draw and release a spring launcher | Delivered work stores elastic energy; release gives projectile energy and recoil; the spring/string can fail | 6, 8 |
| A29 | Run a wheel, gear, pulley, belt or winch | Torque and motion transfer through constraints/contact with declared slip, losses, loads and limits | 8 |
| A30 | Start, stall, brake or overload a motor/rover | Finite power, torque, traction, cargo and obstacles determine acceleration, heat, stall and recovery | 4, 8 |

### Water, temperature and energy

| ID | Action | Required reaction | Stage |
| --- | --- | --- | --- |
| A31 | Dig a channel, breach or build a dam | Actual bed/boundary changes drive water flow and hydrostatic loads without creating/removing water | 7 |
| A32 | Put a player or object in water | Displacement produces buoyancy; relative motion produces drag and matching fluid reactions | 7 |
| A33 | Fill, carry, pour, spill or break a container | Finite liquid mass, temperature and COM transfer among vessel, ground and water region | 7 |
| A34 | Wet, scour or erode ground | Supported pore-pressure/cohesion and transport laws change stability and carry sediment downstream | 7 |
| A35 | Heat or cool matter | Actual power and thermal paths evolve temperature/enthalpy; capacities/conductivity depend on declared state | 9 |
| A36 | Heat a constrained part | Thermal expansion creates strain/reaction; temperature changes the implemented strength/yield laws | 9 |
| A37 | Melt, freeze, boil, condense or solidify | Latent heat, phase mass and volume are conserved; geometry/collision and loads change with phase | 9, 11 |
| A38 | Shine sunlight on a panel | Incident irradiance, exposed area, shadow and declared conversion give finite output and heat/loss accounts | 8, 9 |
| A39 | Charge/discharge a store or power a load | Finite energy/current/power/capacity and losses govern operation; energy is debited once | 8 |
| A40 | Burn coal or run a supported chemical process | Finite reactants become products/residue with declared reaction energy and heat; oxygen can limit it | 11 |
| A41 | Heat/compress a gas or open a valve | Finite gas mass/state creates pressure on enclosing surfaces and flow/work with counterpart loads | 11 |
| A42 | Drive a turbine, piston or pressure vessel | Fluid/gas pressure performs mechanical work, with exhaust, losses and possible enclosure failure | 8, 11 |

### Transfers and coupled continuity

| ID | Action | Required reaction | Stage |
| --- | --- | --- | --- |
| A43 | Manufacture from raw material | A supported process consumes actual lots and delivered work/heat, producing a persistent workpiece, product and residues | 10 |
| A44 | Collect, store, retrieve or trade physical matter | Exact ownership, composition, damage and relevant thermal state transfer once; no duplicate world bodies or receipts | 2, 10, 12 |
| A45 | Edit a live product | A declared physical process or explicit authoring operation changes geometry/state atomically; production matter/work is not free | 10, 12 |
| A46 | Save, reload or change resolution | Same matter/history, constraints, supported state and elapsed time continue without healing or added energy | 2, 12 |
| A47 | Two players affect the same object | One world owner orders both actions and reactions; ownership and collection cannot duplicate material | 12 |
| A48 | A broken support releases a hot, powered or wet assembly | Mechanical, fluid, thermal and energy connections update together; unsupported matter cannot hang or keep supplying power | 2, 12 |

Sound and contact effects can initially be presentation derived from measured events. A later acoustic model would need explicit propagation, energy and material support; playing an impact sound does not establish that model. Light for solar uses a declared irradiance/visibility approximation. This plan does not promise electromagnetic field simulation or a complete optical solver.

## One authoritative physical pipeline

Keep C++/Jolt for qualified rigid motion and constraints, the existing CPU material references for deformable response, and Rust for time, commands, ownership and persistence. Rewriting the solvers into Rust is not a prerequisite for fixing their integration.

1. **Matter state:** stable constituent IDs; reference geometry and occupied volume; material/law version; mass, COM and inertia; accepted pose/velocity; damage/plastic state; temperature/enthalpy/composition where supported; bonds/interfaces and provenance. Multiple cell sizes represent solid occupied regions, never alternating artificial air gaps.
2. **Intent:** mouse, touch, AI, chat and machines submit the same bounded commands. Tool configuration describes grip, working geometry, action family, actuators and required laws. The native state establishes actual contact and work. No material name or tool name branch may grant an outcome.
3. **Scheduling:** the Rust owner advances one accepted world clock. Fine material steps and coarse native steps use explicit boundary exchange, work/reaction accounts and error controls. A fine solve must not silently advance its target ahead of the world. Trial rejection rolls back the entire coupled island.
4. **Contact authority:** rigid-only pairs use Jolt; an activated deformable patch uses the selected coupled solve, with the overlapping Jolt response suppressed by an explicit ownership protocol. Never apply both impulses. Include held assembly, actor reaction, joints, neighbours and fixed-support reactions.
5. **Commit:** update histories, components, mass properties, collision shape, native constraints, renderer revision and ownership in one accepted transition. Fragment geometry comes from failed connected matter. No predetermined shards or arbitrary fragment velocities.
6. **Observation:** publish actual positions, geometry, contact/damage/transfer events and concise action results. The renderer cannot cut holes, award resources or move fragments independently.
7. **Capability registry:** each law/action declares supported materials, geometry, resolution, state and numerical limits. Unsupported cases give a specific refusal and enter the backlog; they do not fall back to cosmetic success.

Inventory stays convenient and has no gameplay bag-capacity chore. It is a declared storage boundary: receiving retains the exact matter state and records the receiving reservoir's support/work/energy exchange. Retrieval cannot teleport stored kinetic energy into a launched product or erase heat/damage. The chosen storage and thermal evolution policy must be explicit and tested; unobserved matter cannot simply disappear.

## Ordered implementation stages

Every stage ends with a small verified main checkpoint, a selectable 3D scenario, headless tests and an updated mechanics scorecard. Proposed numeric targets below are product gates, not measured current behavior.

### Stage 0 Establish the coverage and acceptance contract

- Turn A01–A48 into machine-readable cases with capability, production command, expected reaction, model limits, source and test target.
- Name the single authoritative solver for each contact/state regime. Record current bypasses and unclosed ledgers; keep the strict convergence and four iron-repeat failures visible.
- Declare numerical tolerances before evaluating candidates: absolute SI bounds plus scale-aware relative bounds, timestep/mesh/contact refinement and calibration applicability. Native float error is separately measured; analytical double tolerances must not be copied indiscriminately.

**Exit:** each supported claim resolves to a production path and executable test. There is no badge backed only by a material name, menu or standalone recording.

### Stage 1 Connect ordinary pickup and swing to existing glass fracture

- Build a bonded glass pane scenario with the ordinary native actor, configurable iron tool and actual fixed assembly; expose its constituent/bond state rather than `precise-rigid-v1` target geometry.
- Complete the shared hand/source/target/contact trial, including the finite actor reaction and support accounts. Resolve the retained contact-mode/convergence defects before committing damage.
- Use bounded contact-local activation and preserve the same accepted clock. Withdraw and retain grip after actual impact; support acquisition by either handle or head.

**Exit:** normal mouse and touch pickup/swing create measured glass damage and disconnected components where the declared physical experiment predicts failure. Below-threshold and no-contact controls remain intact. Matched glass/oak/iron experiments preserve distinct supported laws. Full source/target/support work and P/L/E ledgers are reported and meet predeclared bounds. The browser and headless run use the same solver. Contact confirmation alone fails this gate.

### Stage 2 Preserve fragments, secondary contact and custody

- Use existing constituent transfer, component state, mass-property and refracture code for atomic topology replacement. Preserve histories and remap grip, joints and embedded/contact references.
- Add fragment-to-fragment, fragment-to-source and fragment-to-ground contact, self-contact and finite neighbouring response; keep secondary failure and settling on the world clock.
- Collect a connected released group once; preserve it through storage, retrieval and restart. Retire neither old topology code nor tests until replacement parity is demonstrated.

**Exit:** break → fall → collide → break again → collect → reload retains constituent identity and measured accounts. A removed support wakes everything it supported. Ten repeated cycles and a two-player collection race pass. No sleeping debris floats above a vanished support.

### Stage 3 Make physical excavation useful

- Represent inactive ground as compressed homogeneous occupied bricks with sparse holes/history. Refine the active contact/support region; tools retain geometry-driven fine resolution. Unresolved boundary stresses expand the island rather than using an infinite hidden floor.
- Connect rock fracture and separately supported dry granular soil/sand to released constituent bodies, holes, debris and collection. Preserve sharp excavation cuts on smooth untouched hills with one collider/render surface.
- Implement granular settling, banking/slumping and actual heap/compaction transfer. Profile preparation, material solve, contact, topology, meshing, network and save separately.

**Exit:** at least two productive dry soil/sand actions per second after preparation, p95 complete-response latency at most 400 ms, target feedback within 100 ms on the declared reference desktop. A measured 1 × 1 × 3 m shaft takes at most five minutes with the intended obtainable tool and finite power; report soil and rock separately. These retained [digging targets](adaptive-ground-speed-plan.md) cannot be met by free work, fixed hit counts, deleting material or accelerating global time. If finite power is inadequate, add a obtainable powered tool or revise the opening supply, then rerun. Coarse/fine seams and all four strict iron repeat cases must pass before the old excavation route is retired.

### Stage 4 Qualify contact, movement and physical cargo

- Consolidate swept arbitrary-shape contact, concave fragment proxies, friction, rolling and finite support handling. Use actual slip and loads; keep internal damping distinct from air/rolling/contact loss.
- Complete native player footing, bounded locomotion, stance with held loads, jump/step/slope behavior and multiple actor reactions. Replace host position corrections only after ordinary journeys pass.
- Couple rover wheels/traction, braking and stored cargo mass/inertia/restraints to native state. Detect stuck motion using requested versus measured travel/contact, not the controller's desired state.

**Exit:** drop/bounce, slide/roll/backspin, off-centre hit, edge tipping and high-speed tunnelling tests pass; no spontaneous spin without friction. Ordinary actor and loaded rover navigate declared dry/wet routes, stop and recover without position/velocity assignment. Removing a platform drops its cargo.

### Stage 5 Add structures and the missing material laws

- Qualify the existing elastic/J2/cohesive references for bulk materials and add beam/rod/shell reductions for thin geometry, with explicit compatibility and transfer between reductions and solid cells.
- Add finite interfaces for welds, fastenings, hinges and masonry: tension, shear, bending, torsion, opening and compression are distinct. Implement concrete/mineral crushing and supported ceramic brittle response.
- Extend the material matrix: iron/aluminium elasticity and yielding; glass/ceramic brittle failure; concrete crushing/tension; dry sand/soil granular response; rubber-like inorganic alternatives only if admitted by material policy and their actual viscoelastic law. Names alone grant none of these.

**Exit:** tensile/compression coupons, three-point bending, torsion, buckling, unloading/dent, joint lever-arm and dry/mortared wall tests compare analytic/reference results under mesh/time/orientation refinement. A metal post supports a platform and fails under a measured overload. Every new substance expands the regression set; glass/oak/iron remain matched comparisons, with oak unsupported laws plainly marked.

### Stage 6 Make generic tool actions and wear work

- Define one declarative tool interaction schema for impact, scrape, scoop, cut, drill, penetrate and grasp. Geometry sets contact and leverage; actuation supplies finite work; required law support is checked at build/import.
- Add edge resistance, chips, side friction, wedging, embedding and withdrawal against supported material laws. No-hit/refusal, obstruction, cancellation and recovery use the same state machine.
- Implement separate supported laws for abrasion/blunting and fatigue. Preserve tool damage and update functional geometry. Repair requires paid replacement/interface formation; it cannot reset history for free.

**Exit:** authored pick, shovel, hoe, chisel, drill and an unfamiliar tool succeed through the same command path; renaming them changes no response. Sharp/blunt and thin/thick fixtures differ for physical reasons. A damaged tool changes effectiveness and eventually fails under its declared experiment; unsupported wear cannot be advertised as working.

### Stage 7 Connect water, channels and containers

- Reuse shallow-water, river and compound buoyancy code with current terrain boundaries and conservative detailed/coarse exchange. Report rigid-body fluid reactions and fixed bed/external boundary accounts.
- Add actual finite liquid inventories, free-surface/COM approximation, moving container loads, pouring/spilling/leaking and container-break transfer. Connect native actor water response and bounded propulsion.
- Add supported wet soil/pore-pressure weakening, erosion and sediment transport on the same mass accounts. Use declared validity limits for depth-averaged water; contained flow may require a different bounded solver.

**Exit:** a clicked channel fills from a connected finite lake; a dam changes levels and bears pressure; no stale surface remains over a removed bed. Float/sink/current tests, bucket → carry → pour → break, equal-level no-flow and closed-basin mass/energy accounts pass. A player enters water rather than walking on an invisible plane.

### Stage 8 Connect mechanical power and the energy system

- Qualify springs, cables, pulleys, gears, bearings, wheel motors and brakes with physical torque/speed/load limits, backlash/slip where supported and separate loss accounts.
- Connect actual battery/solar/motor/generator/store balances and port power limits. Use an initial lumped circuit approximation with declared voltage/current/resistance behavior; electrical failure/heat need consumers and tests.
- Add an inorganic spring launcher and projectile with actual stored energy/recoil; reuse Stage 6 penetration. Connect water-wheel/turbine work through water reactions, not a timer.

**Exit:** loaded mechanisms exchange finite work, stall without free motion and overload their supported parts. Solar input minus loads/losses/storage reconciles; energy currency banks only real unspent eligible output once. Empty sources cannot drive a drill, charge another bank or launch a projectile.

### Stage 9 Connect heat, strength and solid phase changes

- Reuse thermal/enthalpy kernels with spatially bounded fields, conduction, supported convection/radiation and adaptive boundary error estimates.
- Bind thermal state to expansion, mass/geometry/inertia and implemented temperature-dependent strength. Heat and damage fields must drive both simulation and renderer; no separate weakened copy.
- Implement finite latent-heat melt/freeze/solidification transfers for water/ice and supported processed inorganic materials. Glass softening is a declared temperature-dependent law, not an arbitrary melt switch.

**Exit:** hot/cold loaded coupons differ under the same load; a constrained metal bar expands and loads its supports. Ice melting/freezing keeps phase mass and enthalpy. Cooling and restart retain fields/history. Destroyed thermal connections stop transmitting heat.

### Stage 10 Connect manufacturing, editing and repair

- Compile process definitions for shaping, casting, drilling, welding, mineral/glass processing and repair into finite inputs, equipment, progress laws, operating conditions and work/heat/output accounts.
- Keep source-design editing separate from live physical modification. Manufacturing consumes exact private lots and retains offcuts, rejected material and partially completed workpieces.
- Make Inventory, Build, AI/chat and machine controllers use the same quote/start/cancel/inspect/collect commands with durable deduplicated receipts.

**Exit:** gather → store → make a metal/inorganic tool → equip → use → damage → repair → restart works without material substitution. Zero work produces zero progress; half power changes time consistently; cancellation retains spent work; retry never spends or credits twice. The manufactured object contains its declared constituent geometry and laws.

### Stage 11 Connect finite chemistry and pressure

- Implement only declared inorganic/coal process reactions, finite reactants/products and heat; couple oxygen supply and heat removal to gas regions without claiming resolved smoke.
- Add bounded gas compartments, equations of state and regime-limited valves/flows, with actual pressure loads and compression/expansion work. Couple changing enclosure volumes and rupture to mechanical geometry.
- Add supported boiling/condensation/vapour inventory and pressure-driven pistons/turbines; no unlimited steam/fuel/source workaround.

**Exit:** closed reactor/vessel retains mass and energy, oxygen or fuel exhaustion stops heat production, heating produces measured pressure/work, valve flow conserves inventory, and rupture transfers gas/liquid/fragment state once. Open external reservoirs are counted explicitly. Full smoke/weather/turbulent CFD stays outside this scope.

### Stage 12 Qualify shared worlds, adaptation and authored products

- Save material, thermal/fluid state, connections, phase, workpieces, energy and ownership atomically with command receipts and solver provenance. Retain authoritative multiplayer order and stable identities through fragment replacement.
- Add LLM-generated source validation and automatic physical tests against capability requirements. The model can propose geometry/laws from the supported registry and bounded actions; it cannot create unsupported physics or set a test's success.
- Profile/optimize the shared pipeline; introduce sleep, local adaptation and demotion only with boundary/transfer tests. Optimize measured bottlenecks, retain CPU reference parity, and declare lower-fidelity limits before admitting them.

**Exit:** all A01–A48 pass their specified production-path cases, paired interactions and restart/ownership gates. Two players can operate independently and collide/collaborate in one world; separate worlds are isolated. A newly generated unnamed tool passes build → pickup → use → damage → save tests. A verified quiet world plus two active players meets its predeclared frame, action, memory and network budgets; overload reports a fidelity/budget limit rather than fabricating the reaction.

## Tests that make a stage complete

Each case has six layers:

1. Analytical/constitutive oracle with units, supported range and law parameters.
2. Matched glass/oak/iron comparison where the material law is exercised; add rock/soil/water/new substances as relevant, preserving earlier cases.
3. Full pipeline mass, momentum, angular momentum and energy balances with actor/source/support work, gravity, fluid/thermal crossings, named losses and numerical residuals. An unchanged mass sum alone cannot pass this layer.
4. Time, mesh, orientation and contact-order refinement; compare damage onset, failed area/work, deformation and macroscopic fragments under predeclared tolerances. Exact shard counts need not match arbitrary meshes, but fragmentation cannot remain unbounded/unconverged.
5. Ordinary native worker/API/browser interaction, desktop and real touch input, ownership/cancellation/failure/retry/restart. Automated browser landscape testing does not establish physical-phone acceptance.
6. Sustained gameplay and performance: repeated use, neighbouring effects, simultaneous users and collecting/building from the actual output. No scripted direct-force shortcut substitutes for a player journey.

Add a single visible starting-world selector containing glass strike, metal bend, digging pit, support collapse, tool workshop, channel/dam, bucket, powered rover, heat/ice and pressure vessel. Each supplies an editable real 3D starting world and immediately permits free form live interaction under the contract above. It displays only held item, target readiness and the last measured result by default. Optional inspection shows actual damage/constituents and accounts. Screenshots/video derive from accepted native geometry and time. Keep headless replay and diagnostics available separately from the playable live mode; they cannot satisfy any stage's free form acceptance.

Before publishing source changes, register every new C++ source/test in CMake and run `python scripts/check-source-registration.py`, rebuild the affected targets, execute their tests and the production-path regression, and perform ordinary interactive verification. Update status/roadmap/scorecard with exact revision, measurements and remaining limits. Do not report full regression when only selected suites ran.

## Consolidation and deletion rules

Refactor `LiveWorld.cpp` behind separate contact authority, material-island scheduling, hand/tool, topology-transfer and world-state boundaries, each owning one accepted state. Keep a narrow compatibility facade while callers migrate. Move command ordering/persistence to the Rust owner; do not retain a second Python clock or browser action scheduler.

Retire these only after the named replacement gate passes:

| Candidate | Replacement gate |
| --- | --- |
| Collision-only sandbox as the default fracture demonstration | Stage 1 ordinary glass fracture; retain rigid collision scene as a labelled control |
| Height/work cuts presented as general solid fracture | Stage 3 physical excavation, strict repeats, save migration and speed |
| Cosmetic pickup/debris/resource trajectories | Stage 2 actual constituent motion and receiving |
| Product-name tool branches and duplicate host/browser controllers | Stages 4 and 6 generic native controller parity |
| Analytical design screens presented as full structural validation | Stage 5 live structural coupons and placement/load journey |
| Duplicate resource/energy balances across UI/host/native | Stages 8 and 10 authoritative transfers and durable receiving |
| Parallel terrain render/collision shapes and stale target caches | Stages 3 and 7 shared geometry revision and water boundary tests |
| Legacy saves, command facades and private helpers | Stage 12 migration fixtures, actual caller/reference audit and rollback plan |

Keep independent fracture/contact/material experiments and their tests: they provide oracles and expose defects that the game must resolve. No deletion quota and no blanket removal of thousands of lines. A replacement is complete when the old production route has no callers, existing saves migrate, the new route passes behavior tests, and its remaining approximations are explicit.

## First three main checkpoints

1. Coverage manifest and one editable live held-tool/glass starting world, exposing the real failed integration gate without a rigid substitute and permitting arbitrary supported targets/actions.
2. Coupled accepted hand/actor/target contact and fracture commit, with matched material, no-contact, low-energy, rollback and conservation/refinement tests.
3. Fragment contact/custody/restart plus repeated normal swings, then the measured physical excavation milestone.

These checkpoints come before additional catalog content, progression screens or another physics demonstration that bypasses the engine needed by the world.
