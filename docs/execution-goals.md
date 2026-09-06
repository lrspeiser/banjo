# Execution goals

**Contact and reaction slice:** G02 now has the corrected pre-step reaction axis and a transverse oracle. G05 now has explicit contact budgets, initial-density admission, callback metrics and a 114/486/537-cell comparative matrix. Full G02/G05 gates remain active; no overall goal is complete. See the [checkpoint and evidence](contact-fracture-checkpoint.md).

**Generated-scene verification:** [API-to-studio validation](generated-physics-validation.md) exercises G02 and G05 with analytical controls, repeated material comparisons and normal-speed frame/backlog measurements. It adds evidence to the existing goals without marking any full goal complete.

**Executed checkpoint:** [Implementation, 47-suite validation and measured limits](execution-checkpoint.md). Completed slices: blocky live skins and partial-cut lips, conservative same-clock thermal joining, faster phase kernel and comparative world-budget measurements. Full G01/G03/G05 gates remain active; G02 now has the [material showcase](material-showcase.md) and is active; G04/G06 remain queued.

Status: durable execution list, recorded against main `816cfaf` on 2026-09-05. The 44-suite baseline passes, but physics is unfinished. This list is an execution contract, not a completion claim; no goal has an invented completion date or speed target.

The authoritative retained requirements are the 40 rows in [`docs/mechanics-scorecard.md`](mechanics-scorecard.md): M01–M30 and P01–P10. The goals below group that retained scope without deleting, weakening, or replacing any scorecard requirement.

## 1. G01 — Live cell-derived object skins

**Status:** active. **Owner:** parent agent. **Objective:** derive a renderer-independent skin from accepted live matter, connectivity, interfaces, and history. Ship blocky v1 surfaces first, including partial cracks and fragment skins, while preserving physical state. Smooth and deforming refinements are separately qualified work.

**Dependencies:** object-skin contract; stable cell/component and interface identities; accepted connectivity and damage revisions; material coordinates; local patch queues and stale-job rejection; the existing cell/bond debug view; no dependency on a visual destruction pattern.

**Acceptance:**

- **Prototype gate:** blocky exposed-face surfaces attach to accepted live connectivity; joined cells hide shared interiors; a failed interface exposes both sides even when the body remains connected; partial cracks and repeated fracture update local patches; surviving fragments retain IDs, material, damage, phase/temperature, motion, and lineage; no reskin reset, fabricated impulse, or matter/energy change; stale topology jobs are rejected.
- **Complete gate:** glass, oak, iron, and soft-tissue/layered cases pass the contract under the same declared shape/drop/cut conditions; cavities, heterogeneous exposed interiors, repeated fracture, rigid motion, deformation, contact-proxy error, seam quality, and material coordinates are measured; visual detail changes leave trajectories and ledgers unchanged; many-break runs report surface p95/p99, memory/upload cost, fallback use, and mesh backlog separately from physics. Smooth/deforming skin work is complete only after its own geometry/contact convergence evidence; blocky v1 does not imply it.

**Next action/evidence:** the blocky skin, partial-cut lips, live view and renderer-independent export are implemented and tested in the execution checkpoint. Next add local patch jobs, material coordinates/layers and a measured contact/surface error envelope. Keep the scorecard’s M21, M24 and P10 limitations explicit; this slice does not complete the full surface gate.

## 2. G02 — Converged material/contact response and cutting

**Status:** active, not complete. **Objective:** converge glass, oak, and iron contact/material response and soft-tissue cutting from declared laws. Do not use strength hacks, display names, cell-count-dependent strength, prescribed fragment launches, or unexplained impulses. Assess continuum candidates and require force, work, time, and space gates.

**Dependencies:** authoritative contact ownership; material-derived mass/inertia; constitutive state/history; explicit fracture and plastic work; local solver selection (CPIC/MLS-MPM, VBD/AVBD, or a justified alternative); G01 surface evidence for exposed geometry; comparative glass/oak/iron fixtures; soft-tissue law and cut interface.

**Acceptance:**

- **Prototype gate:** a declared material law runs for glass, oak, iron, and soft tissue with explicit unsupported behavior; equal-and-opposite reactions, contact work, damage/fracture work, and material history are observable; cutting changes accepted matter/topology and produces no prescribed debris motion; the current axial/network path remains labeled experimental.
- **Complete gate:** refinement in timestep, iterations, spatial resolution, and contact geometry bounds force, reaction, newly created area, dissipated work, topology envelope, momentum, angular momentum, and named energy residuals for glass/oak/iron under matched experiments; oak has directional/orthotropic evidence rather than a brittle preset; iron has calibrated plastic/yield evidence; soft-tissue cutting has finite-strain/cohesive evidence; mass-ratio, asymmetric, support, and third-body cases pass declared tolerances. A visually plausible crack alone never passes.

**Next action/evidence:** define paired glass/oak/iron coupons and a soft-tissue cut fixture, then compare the candidate local solvers with the CPU reference across time and space refinement. Record per-material results, units, timestep/resolution, tolerances, residuals, and unsupported laws in the scorecard. No strength adjustment is accepted solely to make a fixture pass.

**Current G02 evidence:** [The material showcase](material-showcase.md) measures matched panel impacts and the existing tomato proxy with unchanged material laws. No panel or tomato fragment separates; timestep sensitivity and absent glass fracture remain failed physical gates. Next compare contact reactions, work and topology under time/iteration/space refinement.

## 3. G03 — Conservative thermal frontier

**Status:** active, not complete. **Objective:** extend the thermal foundation to cross-region flux, cold-neighbor/frontier activation, and conservative coupling while preserving phase, fuel, oxygen, products, latent heat, and lag accounting.

**Dependencies:** current `SparseThermalWorld`/`ThermalKernel` foundation; exact two-lump oracle; bounded jobs and field clocks; authoritative state/energy contract from G04; sparse chunk boundaries and wake predicates; explicit equal-and-opposite interface accumulation.

**Acceptance:**

- **Prototype gate:** cross-chunk/cross-region conduction uses conservative accumulated interface flux; thermal-frontier activation names its cause and error bound; cold storage remains compact and un-simulated until a declared wake; phase identity and latent energy remain explicit; backlog, frontier age, lag, and residual are reported.
- **Complete gate:** matched timestep/space refinements close heat, enthalpy, latent, fuel/oxygen mass, chemical+sensible energy, and interface flux residuals; activation and demotion are bounded and transactional; thermal-to-mechanical coupling is separately validated through G04/G02; no fire, weakening, or reaction claim exceeds its measured law envelope.

**Deferred boundary:** smoke, airflow, pressure/advection, and full fluid dynamics are deferred. They are not required for this goal’s initial thermal frontier and cannot be implied by a heat/reaction demo.

**Next action/evidence:** explicit same-clock neighboring-region joins now pass comparative, phase/history and rejection tests. Next add cold-neighbor activation, boundary error accounting, bounded wake/demotion and cross-clock interface work. The explicit join does not pass the automatic frontier gate.

## 4. G04 — Unified state/energy and bounded authoring API

**Status:** queued, not complete. **Objective:** make mechanical and thermal state one authoritative, versioned, unit-bearing runtime language with explicit named energy stores and bounded creator/job APIs.

**Dependencies:** world physics language; material/law/capability manifests; G02 constitutive/contact ledgers; G03 thermal stores and clocks; stable IDs/history; snapshots and command receipts; API validation and rejection semantics.

**Acceptance:**

- **Prototype gate:** packages validate finite SI inputs, versions, capabilities, IDs, budgets, and unsupported combinations; state exposes chemical, sensible, latent, elastic, kinetic, and gravitational-reference stores where applicable; force is an interaction, not an energy store; bounded jobs report admission, progress, lag, cancellation, and rejection; an LLM may author declarations but never ticks physics.
- **Complete gate:** promotion/demotion, contact, fracture, plasticity, reaction, phase change, external work, and snapshot/retry paths preserve mass, COM, full angular momentum, material/history state, and explicit transfer ledgers within declared tolerances; mechanical and thermal transitions cannot double-count or silently reclassify work; API commands are durable, idempotent or explicitly retryable, capability-checked, and connected to customer authoring flows.

**Next action/evidence:** consolidate the mechanical and thermal ledgers into one versioned transition schema, then exercise bounded load/step/query/export/retry fixtures and rejected inputs. Preserve unsupported laws as explicit capability errors.

## 5. G05 — Measured world-load performance

**Status:** active. **Owner:** execution support; a Sol agent is optimizing the phase kernel under this goal. **Objective:** measure and reduce active-world cost through kernel and sparse-active optimization without changing laws, while keeping cold storage compact and out of full simulation.

**Dependencies:** G03 field clocks/frontier and G04 state/ledger reporting; measured CPU reference; sparse chunks and active islands; bounded job scheduler; benchmark fixtures; stale-job rejection; p95/p99 instrumentation. Routine docs and test fixtures run on Luna; bounded numerical work runs on Sol; complex integration stays with the parent.

**Acceptance:**

- **Prototype gate:** benchmark payload storage separately from allocator overhead; report p50/p95/p99 physics time, active count, backlog, active-set age, residuals, lag, and memory for fixed stored volume/fixed active count and growing active count; optimize only measured kernels; rejected or superseded jobs cannot publish; cold storage is not fully simulated.
- **Complete gate:** declared scale/load matrices meet the repository’s measured budgets or report bounded backlog and preserved last accepted state; results include at least approximately 1M and 16M stored voxels with fixed active count, then increasing active count, plus wake churn once activation exists; numerical outputs and conservation residuals match the CPU reference within declared tolerances; no world-scale realtime claim is made from a small fixture, and no speed is invented.

**Next action/evidence:** the phase kernel and repeated thermal/phase load matrix are measured in the checkpoint, including the 64-versus-128 job allowance with the same wall/work budget. Next measure wake churn, stale-result handling and mixed mechanical loads; qualify their error, active-set age and p95/p99 together. Keep optimization separate from law changes.

## 6. G06 — Snapshot, publishing, and customer conformance

**Status:** queued, not complete. **Objective:** make accepted worlds and objects recoverable, publishable, compatible, and testable through the ax/tree, door/panel, and tomato-bowl customer loop.

**Dependencies:** G01 accepted topology/lineage; G02 material history; G03 thermal history; G04 versioned state/API; G05 bounded jobs and measured load; stable IDs, manifests, permissions, migration, and authority/event model.

**Acceptance:**

- **Prototype gate:** snapshots include authoritative geometry/occupancy, material/law versions, state/history, energy/thermal stores, IDs, provenance, solver/config fingerprints, and capability errors; publication is crash-atomic and validates dependencies; incompatible versions reject rather than silently migrate; customer fixtures expose unsupported hinges, chips, grain, tissue, chemistry, or tools explicitly.
- **Complete gate:** save/recover/replay/publish/import/rollback preserve accepted trajectories, topology, lineage, ledgers, and player/object history under declared compatibility rules; manifests support validation, preview, permissions, migration, and measured authority/bandwidth/determinism behavior; ax/tree, door/panel, and tomato bowl pass material/history/customer conformance with live interaction evidence.

**Next action/evidence:** define the snapshot manifest and compatibility matrix, then run crash/restart, migration rejection, publish/import, and customer-loop fixtures. Tie each result back to P03, P06–P10 and the relevant M rows without claiming product completion from a demo.

## Retained requirements and gate policy

The 40 retained requirements remain authoritative by reference:

`M01 M02 M03 M04 M05 M06 M07 M08 M09 M10 M11 M12 M13 M14 M15 M16 M17 M18 M19 M20 M21 M22 M23 M24 M25 M26 M27 M28 M29 M30 P01 P02 P03 P04 P05 P06 P07 P08 P09 P10`

The scorecard’s evidence/status and limitations apply to every goal. “Prototype” means an instrumented, bounded implementation or experiment with explicit limitations. “Complete” means the goal’s acceptance evidence, comparative material coverage, conservation/work checks, temporal and spatial/refinement checks, and relevant customer/scale checks are all recorded; passing the 44-suite baseline alone is insufficient. Smoke and full fluid remain deferred as stated in G03. No goal is complete; G01, G02, G03 and G05 are active, and G04/G06 are queued. Dependencies describe shared interfaces and final acceptance; independent prototype slices may proceed together.
