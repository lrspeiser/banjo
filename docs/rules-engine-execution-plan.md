# General material rules engine: execution goals

Status: active implementation; no universal material/behavior or realtime completion claim. This plan extends, and does not replace, all nine existing workstreams and 40 mechanics. Smoke and full fluid dynamics remain deferred. LLMs compose supported laws; genuinely new physics laws require implementation and tests.

The three requested demonstrations remain unaccepted: thin glass reaches the damage limit, impact-driven J2 history now exists but permanent unloaded dents are unqualified, and finite-strain rubber is missing. Generated names and scenes do not satisfy behavior acceptance.

**Thin-plate admission correction:** [The reported first-test failure](plate-admission-checkpoint.md) now has matching Python/native geometry preflight and a visible numerical error. An identical live prompt produces 42 actual 3D frames with an explicitly assumed 6 mm plate, then stops at 0.342 s with zero broken bonds in glass/oak/iron. Stable fracture remains open; this is a setup/UI correction, not new physics validation.

## R01: Property-based material contracts

Status: active.

Implementation: Validate SI density and elastic/orthotropic/J2 parameters, units, state layout and supported combinations. Physical identity excludes display names.

Acceptance: Unseen names and numeric parameter sets execute the same native material law; invalid values and unsupported models fail explicitly.

## R02: Shared inertial deformable state

Status: active.

Implementation: Reuse tetrahedral geometry and constitutive state for nodal mass, velocity, internal force and irreversible history. Transactional steps and explicit stability/work limits.

Acceptance: Translation/free-fall oracles, support reactions, rollback, elastic refinement and persistent plastic history pass without name-based branches.

## R03: Coupled dynamic contact

Status: active.

Implementation: Surface triangle/shape contact, consistent equal-and-opposite reactions, friction, continuous collision handling and coupled material updates.

Acceptance: Sphere on deformable patches: no tunneling; contact impulse, external work, stored energy and numerical losses balance under timestep/mesh refinement.

## R04: Recoverable flexible materials

Status: planned.

Implementation: Finite-strain elasticity for large rubber-like deformation, then explicit viscoelastic internal state and relaxation. Small-strain elasticity alone is not rubber.

Acceptance: Ball deforms target, releases stored energy and rebounds; shape recovery, frequency dependence and refinement compared against references; no restitution-only substitute.

## R05: Permanent impact deformation

Status: active; impact-driven J2 history exists, residual-dent acceptance remains open.

Implementation: Connect J2 history to contact-driven spatial motion, unloading and rendered residual geometry.

Acceptance: Impact leaves a measured residual dent, low-energy control recovers; glass/oak/iron comparisons plus new alloys; persistent reload reproduces geometry and subsequent response.

## R06: Stable progressive fracture

Status: planned.

Implementation: Resolve localized stress/energy release with length-scale-aware fracture, transactional topology changes and connected fragments. Include thin-plate/shell representation where needed.

Acceptance: Thin glass impact completes and propagates cracks from loading; fracture energy, fragment mass and momentum audited; timestep/mesh refinement; wood does not become glass by naming.

## R07: Compact state and repair

Status: planned.

Implementation: Serialize only supported canonical deformation, damage, plastic/thermal history and topology deltas; render skins from physical state; budget history and reference repair.

Acceptance: Reload damaged objects exactly within declared tolerance, contact immediately, repair explicitly with resource/energy accounting and bounded state size.

## R08: LLM authoring and experiment contracts

Status: active; property-authored sphere/brick experiments now connect to native dynamics and embedded 3D.

Implementation: LLM emits validated unit-bearing materials, geometries, initial/boundary conditions, supported law compositions, controls and machine-checkable expectations.

Acceptance: Fresh randomized requests generate unseen parameter sets through the public API and render actual native trajectories; unsupported requirements never silently substitute.

## R09: Realtime execution and compiled behaviors

Status: active; accepted evaluation reuse is implemented, world-scale qualification remains open.

Implementation: Profile active islands, sleeping regions, compiled law kernels, conservative LOD and state-keyed offline models with applicability/invalidation checks. Keep LLM out of per-frame execution.

Acceptance: Publish hardware, active interaction counts, p50/p95/p99 cost, memory and overload policy; target 60 Hz total frame with physics budget <=4 ms on declared reference hardware, qualify before promising.

## R10: Cross-material release gate

Status: planned.

Implementation: Run a held-out matrix of known/novel materials, shapes, speeds, thicknesses, temperature/state and histories; preserve energy/phase/fire and other existing goals.

Acceptance: Required shatter/dent/flex cases plus unseen supported compositions pass without engine edits per material. Evidence includes source/material hashes, direct contact and energy telemetry, refinement and LLM assessment separated from facts.

## Execution and reporting

R01/R02 can proceed in parallel. R03 depends on R02; R04/R05 depend on R03; R06 requires a stable coupled path and its own discretization evidence. R07/R08 integrate accepted capabilities incrementally. R09 measures each stage before optimizing, and R10 gates release. Routine bounded work uses lower-model agents, with integration and numerical review retained by the primary agent. Push verified checkpoints to main. Never relax physics limits merely to obtain the requested appearance.

Each goal records implemented scope separately from acceptance passed, with measurements and next steps. Physics comparison always retains glass, oak and iron, expanding the suite as materials are added. Quasistatic pressure is not a substitute for impact; small-strain elasticity is not a complete rubber model.

## Foundation checkpoint

R01 now has a property-only SI descriptor for three existing small-strain laws, a native JSON constitutive-path executable and a Python client. Display IDs/names cannot select a physical outcome. The native executable validates the declared coefficients independently, preserves plastic history along the requested path and returns stress and energy evidence. Material-point tests do not demonstrate spatial behavior.

R02 adds a separate dynamic tetrahedral adapter reusing the existing patch geometry and constitutive history. Its explicit reference integrator is intended to establish a checked baseline. A cached elastic stiffness/mass bound limits timestep; stiff thin structures may require very small steps. This foundation was extended by the coupled-contact checkpoint below; implicit/multirate integration and spatial accuracy still require implementation and comparison before realtime claims. No new drop, dent or rubber capability is exposed to the playground by this checkpoint.

The previous failed thin-glass recording and unsupported dent/rubber requests remain valid evidence of missing capabilities. Do not relabel this foundation as completion of those requests.

## Coupled-contact checkpoint

[Native sphere/mesh coupling](coupled-contact-checkpoint.md) now implements swept contact timing, moving material geometry, friction/spin, support reactions and atomic state commit. The full-duration elastic/J2 drop probe records actual mesh motion and constitutive history. It contains no material-name branches or prescribed rebound. Material contact, numerical energy and mesh refinement remain active acceptance gates. R04 finite-strain rubber and R06 fracture are still planned; no new browser capability is exposed by this checkpoint.

## Adaptive dynamics checkpoint

[Error-controlled contact](adaptive-material-contact-checkpoint.md) implements full-interval rollback, comparison of full/two-half trials, bounded consumable contact-error reserves, optional velocity Verlet with final contact-velocity constraints, and cached accepted material evaluations. Two complete 0.1 s elastic/J2 recordings pass a 3 microjoule accumulated absolute numerical-energy budget. The finer-mesh recordings exhaust the same work ceiling; R03 spatial accuracy and R09 realtime gates remain open. The next work is qualified spatial response and measured stiff-region integration cost, followed by unloaded dent/state retention and playground integration.

## Dynamic material playground checkpoint

[Property-authored impact experiments](dynamic-material-playground-checkpoint.md) connect explicit SI material descriptors to the native sphere/brick solver and actual nodal/sphere recordings. The LLM chooses supported laws and numeric properties, while the server and native CLI independently validate bounded input. The browser renders accepted physical states, shows solver stops, and provides generated playback/inspection controls. New materials require data changes within existing laws; new physics laws still require implementation. R08 is active, while arbitrary scenes, expected-outcome validation, R04 finite-strain recovery, R05 permanent unloaded dents, R06 stable fracture, R07 shared persistence and R09 realtime qualification remain open.
