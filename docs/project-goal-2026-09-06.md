# Banjo project goal and execution contract — September 6, 2026

**Embedded 3D playground checkpoint:** [Chat-authored experiments and controls](embedded-playground-checkpoint.md) now connects GPT plans to native recordings and an in-page 3D viewer. Physical controls rerun the engine without another model call. All 58 native suites, 3 recorder tests and 49 mocked/control tests pass. This is bounded computed playback; integrated calibrated impact/deformation and realtime qualification remain open. All nine goals and 40 requirements are retained.

**Pressure API and assembled-solver checkpoint:** The [bounded pressure and stiffness implementation](continuum-pressure-performance-checkpoint.md) integrates partial-face loads and provides an optional same-law block-CSR solve. All 58 native suites pass (83.49 s); added pressure-state cases pass a subsequent focused rerun, and 33 mocked playground tests pass (2.164 s). Crossed mesh/load studies still fail the high-load spatial-accuracy gate; the finest iron mesh hits the explicit work cap. Kernel benchmark execution is smoke-tested, but repeated isolated performance qualification remains pending. All nine goals and 40 requirements remain retained.

## Product outcome

Banjo is an editable-physics world authoring and publishing platform. A creator
should be able to describe matter, geometry, assemblies, fields, laws and a
test through an inspectable, unit-bearing language; validate that declaration;
run it through bounded physics APIs; play and inspect it in the native
application; preserve its history; and eventually publish or remix the same
versioned package. Chat is an authoring surface over those contracts. It never
becomes the physics clock or a route around validation.

The customer path remains a small first-person, Minecraft-like loop: gather
real quantities of material, ask for an object, see exact shortages and
unsupported capabilities, spend declared material and process energy
transactionally, test the resulting object, revise it without duplicating
matter, and retain the result in a recoverable world. The ax/tree, door/panel,
and tomato/bowl cases are conformance tests for that platform. Balls and
coupons are validation laboratories rather than the product boundary.

Physical outcomes must follow declared geometry, material state and
constitutive laws. Banjo must not choose fracture, dents, rolling or thermal
behavior by display name; prescribe shards or launch velocities; hide missed
deadlines with unrelated cached outcomes; count force as stored energy; or
silently reset damage, plastic, phase, reaction or player history. Rendering
derives from accepted matter and topology and cannot mutate them.

The authoritative object must retain physical volume beneath its appearance:
voxel cells, particles or volumetric elements with explicit material state and
load transfer. A smooth skin is derived presentation. Current voxel-style
networks and the new solid-tetrahedron pressure reference are separate
implementations of that principle; replay may display computed states, but
authored surface animation cannot substitute for physical deformation or damage.

No full goal below is complete. G01, G02, G03, G04, G05, G07, G08 and G09 are
active at different foundation stages. G06 remains queued. “Active” means work
and bounded evidence exist or are underway; it does not mean validated material
behavior, product readiness or a promised completion date.

## Authoritative scope

The [project master plan](project-master-plan.md) remains the durable product
contract, and the 40 rows in [mechanics-scorecard.md](mechanics-scorecard.md)
remain the authoritative requirement inventory. This document groups every
row without replacing its evidence, limitations or next step. The
[development status](development-status.md) and [roadmap](roadmap.md) continue
to carry current evidence and ordering details.

| Scope | Retained IDs | Goal-level acceptance |
|---|---|---|
| Matter, inertia, momentum and energy | M01–M05 | Occupied matter determines mass, COM and full inertia; finite reactions preserve linear/angular momentum; named stores and transfers close for the declared boundary |
| Gravity, elasticity, contact and loss | M06–M14 | Free flight, reversible response, one contact owner, rapid impact, rebound, friction, rolling and distinct damping/loss laws pass analytical and matched-material checks |
| Damage and constitutive behavior | M15–M20 | Fracture, plasticity, viscoelasticity, anisotropy and intrinsic variation use explicit law families, persistent history, work/dissipation and calibration envelopes |
| Fragments, geometry and assemblies | M21–M26 | Emergent pieces retain state and lineage; finite supports, multiple bodies, shape effects, interfaces, fasteners and hinges preserve reactions and history |
| Thermal and further material families | M27–M28 | Heat, phase, reaction and later fluid/granular laws have separate state, conservation and coupling gates; deferred flow is reported |
| Numerical validity and reproducibility | M29–M30 | Time, space, iteration, orientation and seed studies bound applicability; exports identify exact state, configuration and unresolved error |
| Sparse execution and reuse | P01–P04 | Active work is localized and budgeted; sleeping/backlog are explicit; caches and speculation use complete keys, invalidation and authoritative fallback |
| Language, creator API and history | P05–P07 | SI/version/capability validation, human/AI APIs and lossless persistent history share one contract and reject incompatible state |
| Publishing, authority and usable laboratory | P08–P10 | Packages carry dependencies, permissions and migration; multiplayer authority is explicit; native and headless laboratories expose the same accepted physics |

General acceptance always includes identical-condition glass and oak controls
and retains iron as the third reference when a claim depends on material.
Material-neutral analytical tests may stay neutral. New substances expand the
matrix. A passing build establishes regression behavior only; physical claims
also require calibration, convergence, conservation and stated uncertainty.

The preceding integrated foundation checkpoint is a Windows MSVC 19.44 Release
build with all 55 CTest suites passing in 83.19 seconds. Focused J2,
deterministic-variation and numeric-delta tests pass, and 29 mocked playground
HTTP tests pass in 2.140 seconds. These results establish bounded regression
and reference behavior for those slices. They do not complete any goal. See
[the playground foundation checkpoint](playground-foundation-checkpoint.md).

The next [spatial pressure checkpoint](continuum-pressure-checkpoint.md)
connects those laws to a force-balanced tetrahedral mesh, residual plastic
shape, full spatial state round-trip and a chat-selectable computed native
sequence. Low-load glass/oak/iron controls recover; high-load iron response is
strongly mesh-dependent and oak can reach declared validity limits. This
extends the foundation without completing the material, persistence or
real-time goals.

## Goals and dependencies

### G01 — Live cell-derived object skins

**Status:** active. Derive renderer-independent blocky surfaces from accepted
cells, interfaces, topology and history, then qualify bounded local updates and
smooth/deforming surfaces separately.

Acceptance requires partial cracks and repeated fragmentation to expose the
correct interiors while stable IDs, material, motion, phase, damage and lineage
remain unchanged by rendering. Surface/contact error, patch backlog, memory,
uploads and p95/p99 cost must be measured. G01 depends on stable state identity
and feeds G02 contact geometry, G06 publication and G09 inspection.

### G02 — Converged material/contact response and cutting

**Status:** active. Establish declared, separately validated laws for brittle
glass, orthotropic wood, ductile metal and soft tissue, coupled to one
authoritative contact response and complete reaction/work ledgers.

The current axial network and endpoint refinement are diagnostics with known
time/contact/energy failures. The integrated small-strain isotropic J2
material-point reference uses radial return, linear hardening, permanent strain
and explicit nonnegative dissipation; its focused analytical, rejection and
reload-continuation tests pass. The new small-strain spatial patch assembles
stress forces on a connected mesh and solves applied pressure and support
equilibrium. J2 plastic history leaves a residual shape after unloading;
glass uses isotropic elasticity and oak fixed-axis orthotropic elasticity.
The 100 MPa controls recover on three meshes, but 800 MPa iron residual
displacement changes from 34.4 to 162.2 to 348.4 micrometres on successively
refined meshes. This is not a converged or calibrated dent, contact solver or
finite-strain model. High-load elastic survival is not a strength prediction.

Acceptance requires time, iteration, spatial and contact refinement for force,
impulse, work, topology, momentum and energy; calibrated yield/hardening for
metal; grain-frame coupons for wood; brittle/manufacturing state for glass; and
finite-strain cohesive evidence for tissue. Dents and cuts must emerge from
resolved geometry and load transfer, not visual displacement.

### G03 — Conservative thermal frontier

**Status:** active. Preserve thermal/phase/reaction state while activating,
coupling and eventually cooling sparse thermal regions under bounded clocks.

The implemented opt-in cold-neighbor slice preserves promotion mass and energy,
but deferred faces remain insulated approximations and its instantaneous flux
values are not global heat-error bounds. Complete acceptance requires bounded
boundary error, time/space/frontier refinement, conservative demotion,
cross-clock transfer and separately validated mechanical coupling. Smoke,
airflow, pressure/advection and full fluid dynamics remain deferred.

### G04 — Unified state, energy and bounded authoring API

**Status:** active at the limited language/chat API foundation; full
mechanical/thermal unification remains open. Define the authoritative,
unit-bearing, versioned schema for matter, geometry, laws, state/history,
energy stores, commands, receipts, capability errors and bounded jobs.

Prototype acceptance requires the chat and programmatic clients to use the
same load/validate/step/query/export operations as native tools. Commands have
stable identities, validate finite SI values and budgets, and reject stale,
unsupported or incompatible combinations before mutation. The LLM authors
declarations and tests but never advances physics itself. Complete acceptance
requires every promotion, contact, fracture, plastic, thermal, reaction,
external-work and snapshot transition to share one nonduplicated ledger.

### G05 — Measured sparse-world execution

**Status:** active. Keep cold/rigid matter compact, schedule only admitted
active islands and fields, and optimize measured kernels without changing laws.

Acceptance reports payload and allocator cost separately, p50/p95/p99,
active-set age, backlog, lag, residual, wake churn and rejected stale work over
fixed-stored/fixed-active and growing-active matrices. Existing thermal scaling
does not establish mechanical world-scale real time. Mixed mechanical,
thermal, persistence and chat-driven loads must meet declared budgets or retain
the last accepted state and report delay.

The engineering target is a 60 Hz, 16.67-millisecond full frame on named
hardware, measured across 1M- and 16M-stored-voxel worlds with 256, 1,024,
4,096 and 16,384 active cells plus growing-contact and wake-churn cases. This is
a target and benchmark matrix, not measured performance or a promise.

### G06 — Snapshot publishing and customer conformance

**Status:** queued. Turn accepted worlds and objects into recoverable,
compatible, publishable units with manifests, dependencies, permissions,
migrations, previews and an explicit authority/event model.

G06 consumes the state contract from G04/G07, accepted physics from G01–G03,
measured scheduling from G05, deterministic variation from G08 and the
customer-facing path from G09. Save/recover/replay/publish/import/rollback must
preserve trajectories, topology, lineage, ledgers and player/object history.
The ax/tree, door/panel and tomato/bowl paths must report unsupported hinges,
chips, grain, tissue, chemistry and tools until those capabilities pass.

### G07 — Compact persistence, history and repair

**Status:** active foundation with a verified numeric material-point slice.
Store a compact immutable base description plus sparse, versioned state deltas
so a world can render quickly while asleep and resume without rebuilding or
healing its physical history.

The integrated lossless IEEE-754 numeric base/delta codec preserves the fixed
14-double J2 state: total strain tensor, plastic strain tensor, equivalent
plastic strain and cumulative dissipation. Stable
object/material/law IDs, topology revision, phase/reaction state, damage,
plasticity, motion, clocks, provenance, variation seed and solver fingerprint
belong in the eventual snapshot contract.

In three serial runs with 100 timed samples per case, changing 16 J2 points
(64 scalars) produced a 732-byte delta against 64-, 4,096- and 65,536-point
bases of 7,168, 458,752 and 7,340,032 bytes. The measured original restore was
92 bytes and retained history was 824 bytes. Partial 16-point decode p95 was
6.1–6.6 microseconds, sparse encode p95 was 6.9–8.6 microseconds, and
validate-plus-resume-next-material-increment p95 was 4.4–5.7 microseconds.
One-time full-base validation ranged from 0.057 to 65.57 milliseconds; full
65,536-point decode ranged from 1.717 to 2.0013 milliseconds. Same-bit
round-trip, exact next-increment continuation and retention of an old revision
pass. This evidence covers numeric material-point state only. It does not cover
geometry, a world dent, rendering, a save game, crash repair or full-world
reactivation.

Separately, the spatial pressure reference now round-trips complete nodal
displacements, material history, applied loads, work ledgers and revision in
JSON against the same immutable mesh/law/constraints. The next-load result
agrees with uninterrupted execution, including consistent limit rejection.
This full patch JSON has not been integrated with the compact codec and does
not yet authenticate a mesh/law fingerprint or resume a dynamic contact world.

Acceptance requires:

1. Exact encode/decode and next-increment continuation for finite supported
   numeric state, including signed zero policy and explicit nonfinite rejection.
2. Crash-atomic checkpoints or journals with base fingerprints, schema/law
   versions, checksums, writer identity and monotonically ordered revisions.
3. Corrupt, stale, partial or incompatible deltas reject without mutating the
   last accepted state; repair selects a verified prefix and reports discarded
   records rather than inventing state.
4. Save/reload preserves damage, topology, plastic strain/dissipation,
   temperature/phase, reaction reservoirs, variation identity, motion, clocks,
   inventory and player history; no reset, healing or duplicate work.
5. Compact/asleep render and query cost is measured separately from
   reactivation and active simulation cost.
6. Efficient gameplay repair is a bounded transaction that consumes explicit
   material and energy receipts, restores declared stress, geometry and
   topology, chooses collision-safe placement, preserves the old revision for
   audit/rollback, and reports its work and delay.

### G08 — Intrinsic property variation and uncertainty

**Status:** active foundation with the reference sampler verified. Represent
bounded intrinsic heterogeneity through a deterministic, versioned field keyed
by persisted seed and stable object/element/property IDs. Samples are fixed for
the lifetime of that physical material point and independent of visit order,
tick, thread, reload and display name.

The versioned bounded-uniform sampler passes its portable golden-value,
reordered-access and 100,000-seed bounds tests. It changes no force, mass or
energy by itself and is not yet wired into contact or damage.
Its bounds and distribution are law inputs requiring provenance. Intrinsic
heterogeneity is distinct from evolving stochastic physical state, which must
be persisted; calibration uncertainty, which requires parameter ensembles; and
numerical error, which requires refinement.

Acceptance requires exact same-key replay, algorithm/law version rejection,
range and finite-value validation, stable prefix/order behavior, portable
golden values, distribution sanity, compact reconstruction from seed/bounds,
and ensemble convergence. Glass/oak/iron controls use property IDs and declared
law families rather than names. No distribution is a calibrated glass flaw
model until it matches physical population data without tuning numerical
resolution or contact behavior.

### G09 — Chat-to-language/API/native playground

**Status:** active foundation with the basic native request-to-visible-studio
gate verified. Build a GPT chat playground where a user can request a scene or
test, inspect and edit the generated Banjo declaration, validate capabilities
and inventory, run bounded physics through the public API, and open the
accepted result in the native laboratory.

The `continuum_pressure_reference` authoring route selects a fixed spatial
pressure/load-unload experiment. It runs the native quasistatic solver, exposes
glass/oak/iron statuses and opens the computed node sequence in the continuum
lab. The viewer has play/pause/reset/frame controls and labeled displacement
magnification. It is distinct from the network studio's fresh impact run;
failed material cases retain their last accepted shapes and remain marked.

The backend owns model calls and secrets. Local credentials live only in an
ignored .env; a checked-in example may contain variable names and placeholders
but no key. Keys, raw authorization headers and unrelated environment values
must not reach the browser, package, report, prompt transcript or logs. The
frontend receives structured proposals, validation errors, job receipts and
approved result data.

All 29 mocked HTTP tests pass in 2.140 seconds. Live job
`ff0c7d0f1eaa4c4a9f50f8ef7d486202` used an actual `gpt-5-mini` call through
the ignored local `.env` to request an iron ball against glass, oak and iron at
2 and 6 m/s for one second. It used 1,195 tokens, with 4.433 seconds of planning
and 6.537 seconds total. Both headless cases and both native cases completed
480 steps/one second, and the visible studio opened. All physical report fields
matched between headless and native results; compiler/loader metadata,
`load_wall_ms`, performance, skin and presentation fields are deliberately
outside that physical comparison. Actual-native validation caught forbidden
network fields in `rigid_drop`; they were removed before the passing run. The
2 m/s native run produced 50 active
frames with 31.25 ms p95 full-frame time. That measurement does not qualify the
60 Hz target. The basic request → GPT → validate → headless → visible studio →
one-second gate passes; edit, follow-up, save/reload, cancellation, inventory,
unsupported-capability and repair paths remain open.

Acceptance requires:

1. Mocked API tests for proposal, clarification, invalid schema, unsupported
   law, shortages, retry/idempotency, cancellation, timeout and budget paths;
   tests must run without a real key.
2. An opt-in live API test reads its key from .env, uses bounded cost/output,
   records model/config provenance without secrets, and validates the returned
   declaration independently before any world mutation.
3. Chat, CLI and native clients produce the same accepted package and physical
   result from the same declaration. Prompt wording cannot bypass versions,
   units, capability checks, inventory, energy or scheduler bounds.
4. Native end-to-end use covers request, inspect, edit, validate, run,
   pause/resume, save/reload and visible unsupported/error states.
5. Generated tests can call only the bounded public test API; arbitrary model
   code is not admitted to the physics tick.

## Physical reference and calibration policy

The first external fracture reference is the published 6 mm fully tempered
soda-lime-glass pane staircase experiment documented in
[glass-drop-benchmark.md](glass-drop-benchmark.md) and
assets/benchmarks/glass-drop-reference.json: a reported 4.11 kg steel ball,
0.10 m starting height and 0.10 m increases on the same pane until first
observed fracture. The 35-specimen 6 mm series reports mean terminal height
0.76 m and sample standard deviation about 0.24 m.

This evidence is first observed fracture after accumulated staircase history.
It does not establish complete shattering, crack/fragment distributions,
contact force, impulse or timing. The projectile diameter/grade, roller span
and rubber layer are unresolved; a 100 mm sphere is an inferred sensitivity,
not a measured apparatus dimension. Banjo must reproduce the protocol history,
retain raw terminal heights, bracket missing apparatus inputs, run at least 35
independent physical-property realizations, and compare the distribution rather
than tune one deterministic threshold to 0.76 or 0.80 m. Fresh-pane one-drop
cases are useful controls but are not the published probability experiment.

## Ordered execution and integration policy

1. Retain the verified Plasticity, PropertyVariation and NumericStateDelta
   reference behavior while integrating them into higher-level systems. Do not
   claim dents, calibrated scatter or persistence completion from these slices.
2. Finalize G07’s common state IDs, scalar ordering, fingerprints, journal and
   repair semantics. Connect compact asleep rendering and bounded reactivation.
3. Advance G04’s shared language and command/receipt API and extend G09’s
   passing mocked backend/frontend flow across the supported declaration set.
4. Retain independent validation, secret isolation and bounded-job checks for
   live `.env`-backed calls, then extend the verified basic native path through
   edit/follow-up, unsupported cases, cancellation, inventory, save/reload and
   repair tests.
5. Extend the integrated small-strain continuum path with crossed load/mesh
   refinement, pressure-profile and element-orientation controls, and a
   locking-resistant formulation comparison. Predeclare convergence bounds
   for displacement, yielded volume/dissipation, reactions and work before
   dynamic contact, calibrated dents or property-variation integration. Keep
   brittle glass and orthotropic wood on their own laws.
6. Run the physical glass staircase and identical-condition oak/iron controls,
   followed by time/space/contact/seed/calibration sweeps and complete ledgers.
7. Continue G01/G03/G05 surface, thermal-boundary and mixed-load work, then
   admit G06 publishing/customer conformance only from accepted state.

Bounded independent agents may own disjoint files and routine test fixtures.
Routine documentation and mechanical fixtures use a smaller model; bounded
numerical work uses the designated workhorse model; the parent owns architecture,
shared-file integration, review, serial builds and final verification. Merge
small coherent checkpoints, fetch first, preserve concurrent work, run the
relevant and full regression checks, and publish verified checkpoints to main
regularly through ordinary non-force workflow. Never commit secrets, .env
contents, generated credentials or local build artifacts.
