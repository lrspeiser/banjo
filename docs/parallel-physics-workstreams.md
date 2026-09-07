# Parallel physics implementation

Owner steering, September 6, 2026: keep independent physics categories moving concurrently. Glass shattering is the first visual delivery priority. This plan retains all nine original workstreams, 40 mechanics and R01–R10.

Four workers are available in this session: three implementation agents and the primary integrator. Routine bounded implementation/testing uses the existing lower-model agents. An agent finishing its assignment frees a worker; that does not complete its physics category.

| Lane | Owner | Latest accepted assignment | Evidence | Next connected milestone |
|---|---|---|---|---|
| Glass fracture and integration | Primary | Objective corotated dynamics and energy-preserving fracture rejection | Rotation/energy tests; typed compressed-interface stop; full coupled rollback | Conservative compression-to-fragment-contact handoff and event timing |
| Metal deformation | `surface_contact_geometry` | Complete state restart and zero-load J2/elastic coupon | 300-step bitwise continuation; plastic residual at force equilibrium, elastic recovery | Coupled sphere dent unloading, compact binary persistence |
| Cutting | `sphere_patch_acceptance` | Mixed-mode tearing and finite segment/triangle geometry | Rotated/confined-shear coupons; exact Gc-area; bounded closest features | Continuous blade contact, tissue dynamics and convergence |
| Fire and thermal reactions | `dynamic_patch` | General GPT thermal route, archive and 3D | Actual reactive/inert jobs; finite reactants, full ledgers, inspected cell playback | Thermal/mechanical coupling and broader material acceptance |

This is a checkpoint of completed independent batches, not a live worker-status feed. Three subagents ran these lanes in parallel with primary integration. Worker completion is distinct from feature acceptance. Next bounded tasks refill available slots after review. See [current results and open limits](finite-rotation-parallel-checkpoint.md).

## Shared contract and merge order

Agents own separate files; the integrator owns shared build registration, API composition, diagnostics, goal/scorecard updates and publishing. No agent changes another lane's files without coordination. Bounded functions report rejected work instead of publishing partial state.

1. Review law, topology and thermal APIs with units, state identity and supported domain explicit.
2. Compile and run each lane's analytical and regression tests; inspect energy, mass, support work and limits.
3. Combine changes and run the native and Python regression suites. Preserve existing concurrent work and push ordinary verified checkpoints to main.
4. Integrate the accepted fracture state with the coupled solver. Topology alone never breaks material; only solved local forces and the fracture law can advance separation.
5. Update collision geometry from actual exposed surfaces; continue sphere, support and fragment contacts. Preserve fragment mass, momentum and irreversible history.
6. Run the full iron-ball/glass sequence with glass/oak/iron controls, then expose the accepted recording in 3D with timeline, component inspection and evidence. Do not call a partial crack, solver stop or animation a completed shatter.

## Gates that remain open

The original coupled tetrahedral solver retains small-strain elastic/J2 response. A separate cohesive adapter now advances tet-local topology and elastic bulk under actual sphere contact, with an explicit optional corotated isotropic bulk/interface path. Finite-rotation coupons pass, but compressed-fracture contact handoff and coupled J2 support remain unfinished. Large fragment rotations, fragment self-contact, calibrated fracture and realtime cost remain separate implementation/acceptance gates. The older cell-lattice glass run stops at its damage limit and has zero broken links in the latest reported job (`8b113b80050e441686561e685f3b72a0`).

Fire currently uses a lumped thermal/reactive approximation with finite local oxygen; smoke, airflow and full fluids remain deferred. Topology for separation is a dependency for cutting, not a knife/tomato simulation. No completion date or whole-platform acceptance is implied by running several agents.

Keep this assignment table and `execution-goals.json` current at each merged checkpoint. Completed assignments move to the next bounded dependency instead of leaving the remaining physics categories silently idle.

---

## Retained workstream contracts

The following original contract remains in force. The assignment table above sets the current execution order; older baseline descriptions below are historical.

# Parallel physics workstreams and shared acceptance contract

This is an integration plan for the next physics work. It keeps the current
experimental boundaries visible while allowing contact/dynamics, fracture,
plasticity, thermal state, runtime/rendering, and validation work to proceed in
parallel. It does not promote the current network runtime to a validated
continuum model or claim full real-time execution. The current status and the
40-row requirement set remain authoritative in
[development-status.md](development-status.md), [mechanics-scorecard.md](mechanics-scorecard.md),
and [roadmap.md](roadmap.md).

## Baseline that the work must preserve

The public runtime currently separates several state owners:

- [JoltWorld](../src/rigid/JoltWorld.hpp) owns rigid poses, velocities,
  contacts, constraints, contact diagnostics, and reversible rigid trials.
  `step` uses seconds; positions are metres, linear velocity is metres per
  second, angular velocity is radians per second, mass is kilograms, impulse is
  newton-seconds, and energy/work is joules. `runReversibleTrial` and
  `runSpringTrial` restore the Jolt state, constraints, ticks, events, and
  contact diagnostics on rejection; caller-owned constitutive history is not
  implicitly covered by the rigid transaction.
- [NetworkWorld](../src/platform/NetworkWorld.hpp) is the experimental
  single-clock cell-network adapter. Its package declares SI units, a fixed
  timestep, material and object data, optional contact and damage budgets, and
  a bounded object/cell/link set. It owns network bond history, damage,
  plastic extension, fracture/plastic work, connectivity, and network reports;
  Jolt remains the contact and spring execution owner. A network `step` must
  use its admitted fixed timestep.
- [NetworkMaterial](../src/material/NetworkMaterial.hpp) is a directional
  axial lattice approximation. Density is kg/m3; modulus and strength are Pa;
  fracture energy is J/m2; damping, friction, yield strength, and hardening are
  explicit fields. `NetworkBondHistory` owns plastic extension, maximum opening,
  damage, fracture/plastic dissipation, and unreleased energy. These fields do
  not by themselves establish grain, calibrated iron plasticity, or a continuum
  law.
- [SparseThermalWorld](../src/world/SparseThermalWorld.hpp) owns sparse thermal
  cells, region clocks, phase state, fuel/oxygen/product reservoirs, frontier
  admission, and bounded thermal jobs. Temperature is K, heat capacity is
  J/(kg K), conductivity is W/(m K), thermal energy and heater work are J, and
  region time is s. Deferred frontier faces are an insulated approximation;
  thermal state is not silently coupled into mechanics.
- [PlatformWorld](../src/platform/PlatformWorld.hpp) exposes the host-thread
  load/step/query/report boundary. `PlatformInstance`, `PlatformBondLine`, and
  `PlatformSkin` are views. `renderInstances`, `renderBonds`, and
  `renderSkins` must not mutate physics. `CellSkin` carries stable cell and
  component IDs plus a topology revision; it is a derived blocky render cache,
  not an authority for mass, contact, or fracture.

The current measured evidence is bounded fixture evidence. Existing network
scenes, material showcase scenes, thermal tests, and contact-capacity tests are
useful regression controls. They do not prove glass realism, global
convergence, a complete energy ledger, or world-scale real-time performance.
Every new claim must state whether it is a design, implementation, experiment,
or validation result.

## Workstreams

Each workstream may develop independently behind the contract below. A branch
must keep its commits small and leave the shared integration branch buildable
after each merge.

### Contact and dynamics

Own rigid contact, motion integration, contact ownership, support geometry,
solver resource admission, and coupling of a rigid body to an active local
model. Work against [JoltWorld.hpp](../src/rigid/JoltWorld.hpp),
[RigidPrimitive.hpp](../src/core/RigidPrimitive.hpp), and the existing contact
and reversible-trial tests.

The workstream must preserve one authoritative response per contact, equal and
opposite reactions with correct torque arms, finite support extents, and an
explicit distinction between physical impulse, positional correction, contact
damping, rolling loss, and numerical residual. Contact capacity is a resource
contract, not a physics tuning knob: report the configured body-pair and
constraint budgets, initial pair upper bound, manifold/point peaks, and any
rejected admission. Do not solve capacity failures by lowering resolution or
silently dropping contacts.

Initial gates:

1. Free-flight, gravity, torque, contact, friction/slip, and finite-support
   analytical controls pass at two timesteps and for glass/oak/iron matched
   rigid cases where material behavior is being compared.
2. Low and high explicit contact capacities either produce identical physical
   output when both admit the same case or reject before mutation with a clear
   resource error.
3. A rejected reversible trial restores poses, velocities, springs, events,
   ticks, diagnostics, and all caller state included in the transaction.
4. Contact refinement reports penetration/contact distance and reaction/work
   residuals; it may not relax a tolerance merely to make a scene pass.

The existing `banjo_contact_tests`, `banjo_runtime_tests`,
`banjo_contact_ownership_tests`, `banjo_pair_impulse_tests`,
`banjo_contact_capacity_tests`, `banjo_reversible_trial_tests`, and
`banjo_spring_trial_tests` are the first regression set. The measured glass
ball drop benchmark is the shared integration fixture, with oak and iron at the
same geometry, speed, gravity, support, timestep, and solver settings.

### Brittle and cohesive fracture

Own damage initiation, cohesive/brittle laws, bond history, topology changes,
fracture work, component lineage, and fragment handoff. Consume contact and
motion through a narrow event/impulse interface; do not duplicate a rigid
contact impulse. Use [NetworkMaterial.hpp](../src/material/NetworkMaterial.hpp),
[ImpactEvent.hpp](../src/fracture/ImpactEvent.hpp),
[CellSkin.hpp](../src/fracture/CellSkin.hpp), and existing rupture/energy tests.

The fracture interface receives a timestamped contact or strain increment,
relative velocity and normal/tangent data, material law version, current
history, and an explicit available-work budget. It returns a proposed history
update, damage/connectivity changes, fracture work, unreleased or residual
energy, and events. Acceptance is transactional: an outer tick must either
publish all accepted state, or restore bond history, connectivity, work,
events, skin revision, and coupled rigid state. A `Gc` value in J/m2 requires
an explicitly declared crack-area rule in m2; strength, opening overshoot, and
numerical correction are separate terms.

Gates:

1. Matched glass/oak/iron coupons and impact scenes report initiation time,
   live/broken bonds, connected components, crack-area/work terms, mass, linear
   and angular momentum, and residuals.
2. Timestep, spatial resolution, solver-iteration, orientation, and seeded
   defect sweeps report outcome envelopes. Break-count changes are evidence of
   unresolved convergence, not a reason to tune a threshold until counts agree.
3. Strict limit rejection restores the complete physical state. Report mode
   exposes accepted maxima and unresolved limits, and does not imply that
   unobserved intra-substep peaks were resolved.
4. Detached pieces continue to carry matter, material history, stable lineage,
   mass properties, and later contact capability. No pre-cut shards, launch
   kicks, or render-only cracks may create the result.

Run `banjo_network_material_tests`, `banjo_network_runtime_tests`,
`banjo_network_adaptive_tests`, `banjo_network_skin_tests`,
`banjo_energy_rupture_tests`, `banjo_rupture_cascade_tests`,
`banjo_bonded_bowl_tests`, and `banjo_material_showcase_tests` at each
integration checkpoint. Current network fracture remains experimental and is
not a real-material validation.

### Plastic deformation and cutting

Own the standalone constitutive module first, then its bounded adapter into
network bonds and tool/contact loading. The initial target is small-strain J2
return mapping with explicit yield, flow direction, hardening state, plastic
work, and a documented valid range. The module must be testable without Jolt or
rendering. A future adapter may consume a local strain increment and return
updated stress/internal variables, plastic work, and a consistent tangent;
neither the adapter nor a knife tool may directly assign a visual displacement.

State ownership is explicit: elastic strain/stress and plastic strain/history
belong to the constitutive material point; bond topology and fracture history
remain with the fracture owner; rigid pose/contact remains with Jolt. Cutting
must provide measured tool geometry, relative velocity, contact work, and
support reactions. Any material removal or separation must be paid for in the
work ledger and must preserve remaining mass and inertia.

Gates:

1. Uniaxial tension/compression, shear, unloading, cyclic loading, and
   timestep-refinement tests match an analytical return-mapping oracle within
   stated tolerances.
2. Plastic work is nonnegative for the selected convention, stored/recoverable
   energy is separated from dissipation, and rejected trials restore all
   internal variables.
3. A knife/tomato or tool coupon is compared at multiple speeds and resolutions
   with glass/oak/iron controls where those materials are applicable. Report
   separation, mass, work, contact, and unresolved peaks; do not claim a
   completed slice from a visual cut.
4. The current axial perfect-plastic demonstrator remains labeled as an
   uncalibrated demonstrator, not iron plasticity, until these gates pass.

Start with `banjo_constitutive_tests`, `banjo_network_material_tests`,
`banjo_network_adaptive_tests`, and the generated knife/tomato fixture. Keep
the plasticity module independent of the thermal and render branches until its
unit and state contract is stable.

### Thermal, phase, and chemistry

Own [ThermalKernel.hpp](../src/thermal/ThermalKernel.hpp),
[EnthalpyLaw.hpp](../src/thermal/EnthalpyLaw.hpp), and
[SparseThermalWorld.hpp](../src/world/SparseThermalWorld.hpp). The thermal
branch may add phase, reaction, moisture, and boundary/frontier behavior, but
must not add unused fields to a mechanical material and must not weaken
mechanics by display name. A future coupling adapter must declare exactly which
thermal state changes a mechanical law, its units, lag/error policy, and work or
heat transfer term.

Every thermal operation is keyed to an accepted region time. Mass reservoirs
(fuel, oxygen, inert, products), sensible/latent energy, and external heater
work remain separately visible. Frontier admission is bounded by probes, cells,
pending candidates, jobs, operations, and wall budget; deferred faces retain
their documented insulated approximation. Cross-clock exchange, radiation,
flow, moisture transport, and thermal weakening remain planned until they have
their own contracts and tests.

Gates:

1. Heat exchange, phase transition, reaction, and insulated-boundary tests
   conserve the declared closed-system quantities at matched elapsed time.
2. Stale time, backlog, limit, and failed join commands reject before mutation.
3. Cold-neighbor activation and demotion preserve mass, phase/history, and
   energy within a stated boundary/error budget.
4. Mechanical coupling is tested as a separate mixed-world experiment and
   cannot silently count the same energy as both heat and mechanical work.

Use `banjo_thermal_kernel_tests`, `banjo_enthalpy_law_tests`,
`banjo_sparse_world_tests`, `banjo_world_package_tests`,
`banjo_thermal_frontier_tests`, and `banjo_thermal_region_join_tests` before
any mechanics coupling is merged.

### Sparse runtime, API, rendering, and validation

Own the package/capability boundary, bounded scheduling, reports, render views,
and the compact object-state persistence contract below. Runtime work must
remain independent of rendering, file access, model calls, and network calls on
the physics tick path. A package is initial authoring state; a persisted state
is a versioned physical snapshot with explicit compatibility and error budget.

The view contract is derived and disposable: stable object/element/component
IDs, `CellSkinTopology.revision`, and material IDs bind a render cache to an
accepted physical revision. A skin query can rebuild or evaluate a cache but
cannot advance time, alter bonds, alter mass, or alter a pose. Record render
rebuild time, visible cell/face/triangle counts, and latency when testing
visibility activation.

The package/API branch owns schema versions, capability manifests, units,
admission errors, receipts, report field names, and compatibility checks. It
must not hide unsupported laws behind a valid-looking field. Use the existing
`banjo_platform_tests`, `banjo_cell_skin_tests`, `banjo_compiled_object_tests`,
`banjo_compiled_runtime_tests`, `banjo_platform_tests`, and authoring/API
checks as controls.

#### Compact object persistence contract

The first persistence slice should use a sparse base-plus-delta record rather
than a screenshot or a replay-only recipe:

1. **Identity and base:** package/object ID, stable cell/element/component IDs,
   base geometry/occupancy, material-law IDs and versions, units/ABI, compiler
   and solver fingerprints, deterministic seed, and a state revision/hash.
2. **Physical delta:** per active region or changed cell, plastic strain and
   stress/internal constitutive history, damage and bond connectivity/history,
   phase/thermal/chemical reservoirs when present, residual pose/orientation,
   linear and angular velocity, and named stored/work/energy terms. Include
   dents and permanent deformation as physical state; do not encode them only
   in a mesh delta.
3. **Derived data:** render topology, mesh, visibility, broadphase, and contact
   caches are optional and disposable. They carry the source revision/hash and
   are rebuilt when absent or stale; they are never authoritative.
4. **Activation:** decode only a bounded requested region, validate ABI,
   geometry/material/history hashes and finite ranges, restore state directly,
   and then rebuild derived render/contact caches. Activation must not replay
   the entire history to reconstruct a saved state.
5. **Quantization:** exact values are preferred. If compact encoding quantizes
   values, record precision and a per-field error budget; reject a budget that
   cannot contain the resulting mass, momentum, stress, plastic-work, damage,
   or energy error. Never silently drop history or energy.

The editor/history layer should add a bounded immutable original base plus
base-relative revision/checkpoint deltas. The original base is never evicted;
recent revisions have explicit byte/count caps and random access does not
require replaying collisions. A stale edit command rejects against the current
revision/hash. An editor repair is a new transactional revision that restores
geometry and material state/connectivity together, records provenance and any
external energy/material cost, and may reject overlap, support, mass, or other
validity failures before publication. This is an editor rollback/repair
facility, distinct from gameplay repair. Keep provenance and revision metadata
bounded; do not create an unbounded per-collision log. The first implementation
may remain lossless and narrow, covering base-relative numeric state and exact
restore preview; it must not be described as a complete gameplay dent/repair
system.

Required persistence gates are compact-byte and decode tests, reactivation of a
bounded region, render rebuild latency under a named budget, and comparison of
the next impact against uninterrupted execution at the same precision. Repeated
unload/load cycles must not heal damage, drift pose/velocity, duplicate work, or
change stable IDs. History gates additionally cover immutable-base retention,
random-access checkpoint restore without collision replay, stale-command
rejection, bounded revision eviction, and a repair transaction that either
publishes a new revision with its external cost or leaves the prior revision
unchanged. A current package/report API is not evidence that this persisted
physical state exists; implementation and validation remain planned.

## Shared acceptance contract

All workstreams use the following boundary unless a versioned exception is
reviewed into the package schema.

| Contract item | Required rule |
| --- | --- |
| Units | SI: m, s, kg, rad, N, Pa, J, W, K. Dimensionless coefficients state their law and range. Temperature is absolute K; angular quantities use radians. |
| Frames | Positions and velocities are world-space unless a field says local/object-space. Geometry dimensions are full lengths; object-local axes are transformed by the authored unit quaternion `orientation_wxyz`. Quaternion order is w,x,y,z and it must be finite and unit length. Grain orientation is a separate unit quaternion. |
| Time | One authoritative fixed clock per coupled mechanical scene. A substep/refinement may not advance one body twice or publish a future failure at the current time. Every result reports fixed dt, elapsed time, accepted/rejected substeps, and unresolved limits. |
| State ownership | Jolt owns rigid pose/contact/constraint state; the constitutive owner owns stress/strain/internal variables; the fracture owner owns bond history/connectivity/lineage; thermal owns phase/chemical reservoirs and region clocks; renderer owns only derived caches. Cross-owner writes use an explicit transaction or returned update. |
| Contact | Exactly one response owner per contact pair. Reactions include torque arms. Positional correction, damping, friction, rolling resistance, external work, and numerical residual are separate ledger terms. |
| Irreversible work | Fracture/plastic/chemical changes require an explicit available-work source and named dissipation. `Gc` work uses declared area and is not inferred from a display mesh. No arbitrary impulses or fragment launches. |
| Transactions | Rejection restores every state mutated by the trial, including histories, springs, topology, events, diagnostics, clocks, and cached solver configuration. A report must identify discarded work/substeps and the rejection reason. |
| Determinism | Record package hash, law/compiler/backend versions, seed, geometry/material content, dt, substeps, iterations, resource budgets, and precision. Require repeat equality or state the measured tolerance and platform scope. |
| Errors and capabilities | Unknown fields, invalid units/ranges, unsupported law combinations, stale timestamps, resource admission failure, and incompatible snapshots reject before mutation with a stable machine-readable category and human message. |
| Observability | Reports include per-material outcomes, mass/COM/inertia, momentum, angular momentum, recoverable and dissipated energy, external work, residuals, topology/lineage, active counts, allocations, latency percentiles, and discarded work where relevant. |
| Rendering | Render and persistence caches bind to physical revision/hash, rebuild from accepted state, and cannot mutate or advance the solver. Visibility activation is bounded and measured separately from physics. |

Material-dependent claims always compare glass, oak, and iron under the same
declared experiment. Material-neutral analytical oracles may stand alone, but a
law claim must state calibration, valid range, resolution, timestep, defect
seed, and unsupported behavior. Report failures as failures; do not widen
tolerances or change a material name to make a comparison pass.

## Merge sequence and ownership

The shared integration steward owns the package/schema version, cross-owner
interfaces, benchmark fixture, report vocabulary, and final merge. Each branch
owner owns implementation and focused tests within one workstream; no branch
may edit another owner’s state model by reaching through a private class.

1. Freeze this contract and add only pure interface/test scaffolding. Land the
   standalone plasticity oracle and thermal/material unit tests first because
   they have no Jolt or render dependency.
2. Land contact/dynamics resource and rollback changes with the glass-ball
   drop benchmark plus matched oak and iron cases. Confirm current network
   admission and contact diagnostics before enabling another constitutive law.
3. Land fracture changes against the returned contact/strain event interface,
   then run the three-material fracture, topology, skin, and work-ledger gates.
4. Land plasticity-to-network/cutting integration only after its standalone
   state and work contract passes. Run knife/tool cases with refinement and
   preserve unresolved-peak diagnostics.
5. Land thermal/phase/chemistry coupling through a versioned adapter after
   isolated thermal conservation and frontier gates pass. Do not make thermal
   fields mandatory for existing mechanical packages.
6. Land persistence, render-cache rebuild, and visibility activation against
   the accepted physical snapshot. Verify next-impact equivalence, repeated
   savings, bounded decode, and no render mutation.
7. The steward runs the full CTest set, generated/native benchmark suite, and
   interactive smoke checks serially. Publish a checkpoint that lists exact
   commit, build, machine, timings, pass/fail gates, and remaining defects.

Each merge is a small coherent commit: one contract or implementation change,
its focused tests, and its measured report. Do not merge a green build as a
realism certificate. The measured glass-ball drop is the common smoke test;
fracture convergence, complete mechanical/thermal work closure, automatic
physical LOD, durable live mutation, and full realtime behavior remain open
until their stated gates pass.

## Scorecard preservation map

No scorecard row is removed or reclassified by this plan. The parallel split
provides an owner and a next gate for every retained row:

| Workstream | Retained rows |
| --- | --- |
| Contact/dynamics | M01–M14, M22–M26 |
| Brittle/cohesive fracture | M15, M16, M20, M21, M24, M25, M26 |
| Plasticity/cutting | M05, M15, M17–M20, M24–M26, M29 |
| Thermal/phase/chemistry | M05, M27, M28, M29 |
| Runtime/API/render/persistence/validation | M01–M06, M09, M16, M21, M23–M30, P01–P10 |

The overlaps are intentional: the rows describe cross-cutting acceptance
properties, while ownership describes who may change a state and who supplies
the evidence. Existing goals stay active or queued according to the current
status documents; this plan does not mark any goal complete.
