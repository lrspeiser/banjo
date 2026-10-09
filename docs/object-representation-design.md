# One object, multiple physical representations

**Implementation update:** [Initial GPU flight/material-island adapter](gpu-representation-checkpoint.md) is experimental. The complete representation registry, detailed sphere transfers, reduced modes and coupled fields below remain open.

October 9, 2026. **Proposed architecture; no new solver or speed improvement implemented in this checkpoint.** Source reviewed at main `3ebe792060df2bd42585e183616e2361bda6a917`. This expands [deferred physicalization](project-master-plan.md#4-matter-representation-and-deferred-physicalization) into an explicit storage and switching contract, and addresses the [measured 10 m drop bottleneck](drop-performance-audit.md).

## Decision

Store one physical object and maintain the representations needed for its current activity. Start with **eight representation families**. An object may use several simultaneously: a rigid falling ball can conduct heat; a bending beam can burn; a damaged fragment can fly and cool. Extend the registry when a new implemented law needs a different solver representation.

The engine chooses representations from geometry, physical state, applicable laws and measured approximation error. It must be able to explain that choice. A display name such as glass or iron does not select a canned outcome.

## The eight families

| Family | Stored/runtime data | When it is useful | What the user sees |
|---|---|---|---|
| 1. Equilibrium/sleeping | Occupied geometry, support relationships, retained internal state and wake conditions | A mechanically stable object whose omitted motion is within an explicit error budget | Buildings and settled pieces remain in place; moving a support or adding a load wakes affected regions |
| 2. Rigid body | Exact represented mass, center of mass, full inertia, transform, linear/angular velocity and collision shape | Flight, translation, spin and contacts proven to need negligible deformation | A ball falls and spins promptly; later rolling/sliding follows friction and torque |
| 3. Articulated assembly | Rigid regions, joint coordinates, attachment matter, constraints and reaction accounts | Hinged doors, wheels, connected mechanisms | A door swings or a wheel turns; stressed attachments can promote to detailed mechanics |
| 4. Reduced deformable solid | Deformed rest geometry, validated deformation modes and their positions/velocities, constitutive history | Small elastic bending/vibration where retained modes meet the error bound | A beam flexes without solving every possible material element; large/localized loads activate detail |
| 5. Detailed solid | Active finite material elements, interfaces, deformation/spin state, damage, plastic history and local contact graph | Impacts, crushing, cracks, permanent deformation and fine cutting | Actual cracks, changed shape and separated matter, where the implemented law and resolution support them |
| 6. Flowing matter | Conservative particle/grid/volume state, density, velocity, stress/pressure and phase information | Liquids, qualified granular flow or extreme deformation beyond the solid representation's validity | Water flows; sufficiently heated matter can flow once a phase-change model is implemented |
| 7. Thermal field | Enthalpy/temperature distribution, conductivity, heat capacity, surface exchange and phase fractions | Heating, cooling, conduction, thermal expansion and phase changes | Heat spreads through the same object; qualified temperature-dependent mechanics changes its response |
| 8. Chemical/reaction field | Species masses, reaction progress, reactant transport and accounted chemical energy | Combustion, oxidation and other implemented reactions | Available fuel and oxygen determine consumption and heat; noncombustible material has no combustion response |

Families 1–6 describe mechanical evolution; one mechanical solver owns each material region at a time. Families 7–8 are coupled fields and can remain active while mechanical detail changes. Sleeping suspends eligible mechanics, not ongoing heat or reactions. Supported combinations require an explicit coupling implementation, not just declared properties.

Rigid free flight and rigid contact share family 2, with different integration/contact work. A disconnected fragment reuses families 1–6; it does not need a ninth material model. A solid sphere can use an exact sphere for rigid collision and an occupied-volume discretization for detailed response. Collision shapes and visible surfaces must describe the same occupied matter within declared geometric error.

Electrical, magnetic, acoustic and other future fields can register further representations once implemented. Do not allocate an unused copy of each object for every possible future law.

## What is stored once

### Immutable definition, shareable across instances

- Definition ID/version and content hash; units and reference frame.
- Initial occupied geometry in local coordinates: solids, voids, shells, layers and fine features.
- Spatial material distribution, orientation and interfaces, with implemented law IDs/versions and calibrated coefficients.
- Semantic assembly connections and attachment regions; intended tool/interaction capabilities.
- Representation recipes: how to build an intact hierarchy, collision shape, material discretization, reduced basis or field grid. These are numerical structures, not predetermined cracks or shards.

### Mutable authoritative instance

- Object and stable matter IDs, ownership/provenance, accepted physical time and active region-to-solver mapping.
- Current motion/deformation, connectivity, removed volume, plastic rest, damage and fracture surfaces.
- Retained elastic/vibrational modes where present, temperatures/enthalpy, species masses and phase fractions.
- Pending forces, joint/interface state, external impulse/work crossings and solver continuation state needed for restart.
- Representation transitions and their measured errors, refusal reasons and conservation receipts.

Fields can live in sparse arrays with a defined mapping to matter. The authoritative state is the accepted union of those owned fields, rather than an always-allocated finest-grid copy. Intact identical objects share templates; edits use instance-specific changes. Save/load retains every active or dormant history required for subsequent evolution.

### Derived caches

Mass properties, hierarchy summaries, spatial bounds, collision acceleration structures, meshes and dormant detail buffers are derived from the definition plus current state. Cache keys include geometry/material/history revision, law/compiler/solver version, resolution and relevant boundary conditions. A dent, cut, crack, phase change or edit invalidates affected summaries and surfaces. Render quality can change independently of physical resolution.

## Shape and resolution

Allow blocks, tetrahedra, shell elements and other supported numerical shapes through the representation compiler. Their choice follows geometry and solver validity. An icosahedral visible ball is not automatically a calibrated deformable solid.

Keep a sphere's actual occupied volume, density-derived mass and inertia consistent across modes. A cell approximation must meet geometric/mass/inertia budgets before promotion; normalize neither density nor mass silently to hide a poor discretization. Refine until admissible or report the limitation. Empty gaps stay empty and thin sheets stay thin. Coarse storage never means alternating material and air cubes.

Use large homogeneous regions where safe and finer regions at interfaces, thin edges, cracks or contact. Damage is persistent when a region coarsens. Refinement must preserve fracture work and constitutive history instead of healing or strengthening the material. A spatial hierarchy must account for load transmission and supports beyond the immediate contact patch.

## How the engine switches

1. **Predict an interaction.** Swept geometry and force/heat/reaction bounds identify the earliest interval where the current representation may become invalid. Use position, relative translation/spin, current damage, imposed loads, material laws, boundaries and uncertainty. Heat can require detail without any collision.
2. **Select the affected region and its coupled neighbors.** Start with whole-object activation where local boundary coupling is not qualified. Include both colliding objects and relevant supports. A low-energy contact can stay rigid only inside a demonstrated applicability envelope; uncertain cases activate detail.
3. **Prepare privately.** Allocate/build compatible representations before the event where possible. Advance no accepted time and apply no response while preparing. Changed state invalidates speculative work.
4. **Transfer at one accepted time.** Capture the old owner, map occupied matter and persistent fields, rebuild mass/inertia and rebind contacts/joints. Initialize rigid-motion detail with `v_i = V + omega × (x_i - COM)` plus any retained nonrigid state. Include finite-element intrinsic spin/inertia. The mapping must preserve deformation, plasticity and damage, not reset to the original intact recipe.
5. **Audit and commit atomically.** Check mass/species, occupied geometry, linear/angular momentum about a common origin, kinetic/elastic/thermal/chemical energy, external work and boundary reactions against explicit scope-specific budgets. Refuse or refine if the transfer fails. Keep one contact response owner and prevent duplicate gravity, impulses or time advancement. Rollback includes topology, fields, clocks and pending commands.
6. **Continue actual physics.** Neighboring solver clocks exchange time-aligned reactions and work. Strong coupling can require one solve or iterations; thermal expansion, changing stiffness and reaction/phase mass changes cannot be applied as unrelated visual effects.
7. **Reduce only when admissible.** Use separate activation/deactivation thresholds and minimum residence criteria. Cheap rigid continuation is admitted only if omitted deformation and its future evolution stay within bounds. Retain a qualified reduced mode or stay detailed if appreciable elastic/vibrational energy remains. Record physical dissipation through its law; never label unexplained numerical loss as heat.

Conservation alone does not establish accurate switching. Compare common-time trajectories, stresses, damage and contact timing against an always-detailed reference under timestep/spatial refinement. Wake and reactivation tests must include a second impact after damage, changing supports, heat-driven stress and edits.

If a detailed representation or coupling is unavailable, reject the unsupported setup or explicitly pause with a reason. Budget exhaustion must not substitute an animation, unrelated cached outcome or silent law change.

## Ball example in the 3D world

1. Create a ball with supported geometry/material laws. Show one smooth or inspection-grid surface; retain its intact material recipe and instance state.
2. During eligible flight, integrate one rigid owner on the GPU, using the same gravity as the rest of the world. A fine distant support must not set this ball's flight timestep.
3. Before reaching the sheet, activate the required mechanical detail in both ball and sheet. Preserve the sheet's prestress/support loading and the ball's spin/temperature/history. Only the qualified detailed contact path applies the impact response.
4. Let contact and constitutive laws decide elastic rebound, deformation, damage and connectivity. Both objects can respond. The display never assumes that a named material must shatter or dent.
5. Extract actual connected components. Settle/coast eligible pieces as material-backed rigid owners; keep deforming pieces detailed or reduced. On later collision, restore their current damaged geometry and history.
6. If heated meanwhile, the thermal field continues through flight, impact and splitting. Each new component receives its actual material/enthalpy. Melting requires implemented latent heat and solid-to-flow transfer; burning requires reactants, chemical energy and accounted products.

The viewer should offer an optional inspector with **mode, active element count, physical time, transition reason and transfer residuals**. An inspection overlay exposes actual matter/discretization without changing collision behavior. Before/Impact/After show accepted states. No extra tool animation is required to make a contact occur.

## LLM authoring contract

The LLM authors one unit-bearing object definition: occupied geometry, material regions, assemblies, tool capabilities and requested supported interactions. The compiler reports which representations/laws are available, geometric and resolution limits, estimated active cost and required validation. It generates compatible representations and their mappings; the runtime decides when they activate.

For example, a user can request a hollow metal ball with a ceramic coating or a thin metal shovel edge. The compiler must preserve the cavity/coating/edge through mass, collision and detailed mechanics. Unsupported ceramic fracture or cutting laws are reported explicitly. The LLM cannot supply a named-material shatter preset, predetermined fragments, arbitrary launch velocities or untrusted GPU code to satisfy the request.

## Existing foundation and missing work

[RigidComponent](../src/rigid/RigidComponent.hpp) and its [implementation](../src/rigid/RigidComponent.cpp) provide an experimental CPU aggregate/detail adapter. [Tests](../tests/rigid_component_tests.cpp) cover material-derived mass, inertia, occupied gaps, original IDs, retained native rest, refusal and repeated transfers. [Measured checkpoint](rigid-component-checkpoint.md) explains the exact scope: the lab automatically reduces only the initial unloaded ball, restores before loading/contact, and stays detailed afterward. Full comparative accuracy/speed remains open.

That adapter is not used by the current `/coupled` CuPy path. The coupled ball is currently a rigid primitive without an internal fracture discretization. Initial-flight transfer is reusable design/code evidence, not proof that a GPU ball can already deform, fragment and re-enter detail. Existing CPU thermal/reaction experiments elsewhere in the repository do not establish these proposed GPU couplings either.

## Implementation sequence and visible acceptance

| Order | Deliverable | What the user can test and what must pass |
|---|---|---|
| 1 | Versioned definition/instance/representation registry and transactional mappings; retain the CPU reference | Inspect an object, save/reopen it, and see unchanged geometry, mass, motion and history. Unknown laws, stale caches, partial transfers and failed allocation refuse without changing the scene. Add analytical mass/inertia and transfer oracles. |
| 2 | GPU rigid flight with swept activation and separate material-island scheduling | Drop from 10 m; see prompt actual flight, mode change before contact and no tunneling. Compare analytical freefall and common-time detailed motion. Stationary prestressed sheets still solve when needed; distant small objects do not globally subdivide flight. This removes a measured source of cost but does not fix the current impact convergence failure by itself. |
| 3 | Qualified detailed ball/sheet contact, local material solve and constitutive response | Hit freely chosen positions on supported sheets. Compare glass, oak and iron under identical declared conditions; retain ice coverage. Display actual cracks/deformation only where qualified. Measure complete work/reactions, P/L/E, temporal/spatial convergence, unsupported laws and the previously refused 10 m case. Calibrated oak grain and continuum metal dents remain separate laws. |
| 4 | Adaptive material regions, reduced modes and fragment reactivation | Hit a previously damaged piece again, move a support and strike a fine edge. Show damage retained and new response computed. Test coarse/fine boundary loads, strain/vibration retention, double counting, failed transfer rollback and restart. |
| 5 | Thermal and phase coupling, then chemical/transport coupling | Heat a supported object and watch measured temperature and qualified expansion/softening. For melting/burning, show mass/species/enthalpy/latent/chemical work accounts and products; unsupported laws stay labeled. Test heating during impact and after fragment splitting. |
| 6 | Qualified flowing matter and large assemblies, with compact accepted render snapshots | Pour water onto an articulated wheel, or stress a constructed building; motion and reactions come from the shared pipeline. Measure full simulation/delivery/render time and responsive controls. Keep slow/refused cases visible. Require the proposed complete-pipeline realtime and interaction gates from the performance audit before claiming gameplay readiness. |

Every implementation checkpoint updates the actual 3D test website and records backend, revision, physical settings, per-material results and remaining failures. New source files must compile in registered CMake targets. Do not retire existing regression/reference paths until their replacements cover their behavior and failed-case evidence.

## Verification of this design checkpoint

Documentation only. Validate local links, changed-file scope and the source-registration guard before publication. No physical tests, new GPU timings, runtime switches, thermal/chemical/fluid capabilities or repaired impact convergence are claimed by this document.
