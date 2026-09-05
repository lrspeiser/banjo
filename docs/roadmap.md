# Banjo roadmap and acceptance gates

**Starter designer checkpoint:** [The real LLM crafting table](starter-designer-checkpoint.md) now proposes supported shapes from actual player stock/level/stamina, preserves shortages, and independently validates Build. Five real trials and all 16 suites pass; native request/paste and blocked proposal verified. Save v2 migrates v1 progress. Full native gameplay, durable common APIs, physical energy and realistic branch cutting remain open. Local source `29e46a2`; full goal active.


**First-person starter checkpoint:** `c10d379b6da72f7f07a283909d6dd577d4302084` adds [Willow Clearing](starter-checkpoint.md): body-free first-person view, click collection into raw voxel-equivalent stock, preset crafting with material/level/stamina requirements, XP, tool cost reductions and a cuttable fixed branch that falls under Jolt gravity. All 16 suites pass at its runtime foundation; the later input patch verifies native inventory/back/pause/resume and mouse look. Full native gameplay remains pending. Stamina/cutting are explicitly game approximations; realistic cutting, physical energy accounting and LLM integration into this new table remain required. The full platform goal stays active; local only.

**Inventory requirements checkpoint:** `fca0cb357d4dc4f154bb6efbb03efb9b69e8134f` now retains supported resource-short designs and reports collected, recoverable, uncollected and missing material through the shared compiler/API. [Evidence](requirements-checkpoint.md): seven real inventory/alternative cases plus five revision/unsupported-capability regressions pass; all 15 Windows suites pass (11.73 s). Automated capture passes; the normal workshop runs, but new-control input verification remains pending the native-helper error. Energy accounting remains unsupported, not zero-cost. Next: reliable API receipts/retries/durability, energy/tool contracts and bounded functional tests. Local only; all full-platform gates remain active.

Application progress at `14bb0b7`: [selected-object rebuild/reclaim](revision-checkpoint.md) now has shared API/UI source, five real provider trials, format-3 history and 15 passing Windows suites. Capture passes; normal control verification remains pending. Continue the [API reliability/test loop](api-platform-review.md) and [energy contract](energy-system.md) without treating this as completion of the physics gates.

This roadmap implements the [master plan](project-master-plan.md). See [development status](development-status.md) for pinned source/CI evidence. “Prototype implemented” does not mean physically validated. These are ordered engineering gates, not delivery dates. Later research can proceed in parallel, but should not conceal unfinished correctness work.

## Existing foundation

**Energy requirement:** carry [identified energy sources and tool/process work](energy-system.md) into the application transaction contract. Start by declaring the physical state of inventory and the energy boundary; test stores/work transfers and resource failure/retry semantics, then connect supported fabrication/interface laws. Current authoring is energy-unconstrained. The energy-system plan preserves Gate 1 conservation and Gate 2 fracture/calibration requirements; it does not replace them with a resource counter.

**Next functional API slice (revision update):** the [API/platform review](api-platform-review.md) proposes completing current rebuild/reclaim integration and reliable command/retry/durability contracts, then a bounded **build → test against measurable criteria → revise → reload** loop using today's primitives. Add physical actions/events and a simple assembly through that same boundary afterward. Current lifecycle backend work has focused tests only; assistant/UI integration remains incomplete. This application sequence runs alongside the ordered physics gates below and does not close them.

**Application slice to carry through the early gates:** [collected materials → LLM request → validated object → physical test → revision](creator-loop.md). Start with a visible inventory and one supported single-material object, preserving quantity/provenance and using the same specification/compiler as laboratory tests. The [first rigid-sphere workshop](creator-checkpoint.md) is now implemented with a manual Codex proposal bridge, shared CLI/compiler, inventory transactions and saved state. The [automatic Windows Codex adapter](assistant-checkpoint.md) now supplies proposals/clarifications with cancellation and independent validation. [Oriented solid boxes](shape-checkpoint.md) now have comparative creator/LLM evidence. Normal box-control verification, safe replacement/reclamation and further shapes remain next; do not defer all user-facing creation until Gate 8 or use a small creator demo to claim the open physics gates are complete.

**On main:** C++23/CMake/Jolt; procedural spheres; parameterized contact and brittle laws; rotation-invariant local strain with tension/compression/shear channels; target activation; generated components/meshes/collision proxies; Jolt fragments and overflow debris; raylib laboratory; material/surface/slope/gravity controls; analytical scenario cache; material-outcome serialization; tests and CI. Main also has interactive frame-control and MSVC build fixes.

**Not merged at audit:** PR #2's measured rolling/sliding, rolling-resistance torque, damping separation, sensor-deferred activation, two-way sphere/material impulses, synchronized microsteps, footprint checks and diagnostics. Its PR CI now passes, including graphical capture. Full physical validation does not.

## Gate 0 — integrate the development checkpoint safely

**Local checkpoint completed:** tested code `f29334d` on `codex/physics-foundation` reconciles main and PR #2 and passes Windows build, all seven CTest executables, headless handoff, capture and normal interactive controls. See [source, environment, quantitative results and remaining defects](windows-integration-checkpoint.md). This is not pushed or merged into main, and is not a new Linux/macOS or remote-CI claim. Gate 1 is the next active engineering gate.

Inspect main and PR #2, preserve concurrent edits and the explicit raylib/MSVC options, and reconcile on a development branch. Review new contact and rolling tests. Run headless tests, the screenshot path, and a normal interactive session; test launch-spin control, pause, reset, slope/gravity changes, and window input/timing. Record exact source and environment.

**Exit:** code is reviewable with no lost main fixes; normal input/frame presentation is verified; the CI result is tied to the tested commit; known physics defects remain documented. Documentation on main does not itself satisfy this gate.

## Gate 1 — conservation and physical bookkeeping

**Adaptive progress at `8cf33bc`:** bounded transactional temporal error control and grazing-contact subdivision now pass analytical/regression checks; all 13 CTest executables pass. [Twelve material runs](adaptive-checkpoint.md) retain glass/oak/iron and expose cost and full-node differences. Next, build the shared experiment workbench with explicit reference-law selection and one owner of each clock/contact. Preserve work/reaction audits through activation before adding friction and shape comparisons. Local error control is not global convergence or calibrated material behavior. Gate 1 stays open.

**Trajectory progress at `e5b883e`:** 30 glass/oak/iron runs at five timesteps now export and compare all nodes at common times. [The evidence](trajectory-checkpoint.md) separates shrinking bulk differences from unresolved internal motion; conservation remains bounded. Next, implement bounded temporal error control over node motion/elastic state, validate against those traces, and integrate one clock/contact owner per participant into the shared lab. Do not substitute the coupled step after the current Jolt advance and thereby advance the finite sphere twice.

**Explicit-compliance progress at `58546cb`:** a separately selected normal spring/compression-dashpot law accounts for stored interface energy and dissipated work in the global elastic solve. Plane/reduced-mass bounce and loaded equilibrium pass analytical checks; 27 glass/oak/iron probes pass per-step audits across three rates. [Measured evidence](compliance-checkpoint.md) still exposes unresolved lattice trajectory convergence. This does not repair or silently replace the rigid e=0.3 event law, and is not the default viewer solver. Next, establish matched trajectory errors and resolution-independent interface compilation, then integrate friction, contact ownership and activation/handoff.

**Contact-root progress at `b31a8a5`:** boundary remainders, departing contacts and stalled brackets have fixes and regression coverage. Full glass/oak/iron lattices finish a 2 ms elastic impact with 20- and 10-microsecond intervals; [refinement evidence](event-root-checkpoint.md) does not yet establish converged trajectories. Dissipative contacts still accumulate tiny impacts and reject. Next, implement sustained-contact integration with energy/work and temporal error control, then close runtime ownership/activation/handoff. Keep the [mechanics scorecard](mechanics-scorecard.md) current and retain the growing glass/oak/iron suite.

**Support progress at `1deb025`:** material/plane constraints now share the global elastic Newton solve. Full glass impact converges at 2 ms, with no widened conservation tolerances; all ten CTest executables pass. The [equal-duration timestep sweep](coupled-support-checkpoint.md) exposes 81.42 J of numerical normal loss for a half-step impact and unconverged rebound across finer steps. Next, resolve impact times with bounded transactional subdivision and an explicit normal-contact law before claiming reliable rebound or integrating this reference into the lab.

**Reference progress at `dc7bcfb`:** global Newton/GMRES now advances the full isolated glass lattice at 2 ms and 1/240 s with unchanged conservation budgets. All ten CTest executables pass, including new analytical timestep refinement and local/global trajectory agreement. A 1/60-second trial rejects and accepted runs remain slower than real time. See [exact source, tests, timing and accumulated drift](elastic-newton-checkpoint.md) and the [initial coupled reference](conservative-reference-checkpoint.md). Next, test stiff sampled contact/support convergence and normal-impact time accuracy, improve measured global linear cost, then integrate friction/restitution/damage and shared rigid ownership. The laboratory still runs the separate-correction path below; do not treat the new reference as a completed runtime repair.

**Local progress at `d56611c`:** finite-cell spin and actual Jolt/debris transfers are tested. Damage no longer records temporary predictor/solver strains; synthetic excitation is removed. Optional CSV stages distinguish prediction, constraints, contact, support, damping and damage. [Nine passing suites and full-run measurements](material-stage-checkpoint.md) expose 4.94 MJ of spring energy added by post-solve contact correction and 15.90 MJ by support correction in the supported run. Those corrections still lack physical work sources. Next, couple nonpenetration/contact with material response, align rigid/material temporal states, and close external reaction/work and numerical angular budgets. Do not declare this gate complete from the transfer tests or a telescoping diagnostic sum. [Property coverage](physics-coverage.md) distinguishes tested consumers from declarations.

Instrument rigid bodies, material nodes, constraints, supports and debris. Record external impulse/work and distinguish contact, rolling, damping, fracture/plastic, geometric-correction, and coarsening terms. Audit one owner per contact and consistent rigid/material clocks. Check finite-mass reactions, angular torque arms, frame invariance, and no attractive separating contacts.

Review rigid-to-lattice and lattice-to-fragment mass, COM and full inertia equivalence, including intrinsic cell spin. Do not infer whole-system correctness from pairwise tests or a zero mass error.

**Exit:** isolated and supported reference experiments bound momentum and energy residuals across activation, active contact and handoff. Numerical stabilization and intentional losses are measured and documented. Unexplained energy creation fails tests.

## Gate 2 — trustworthy material response and fracture

Create parameter/property coverage tests and provenance for presets. Calibrate elasticity and tension/compression/shear failure using coupons before tuning an impact spectacle. Tie irreversible fracture work to modeled crack area or another explicit energy-consistent law; audit horizon weights and double counting. Fix severe over-fragmentation without explosion pulses, pre-cut shards, or an imposed physical shard count.

Sweep voxel size, timestep, iterations, grid orientation, seed, density, speed and impact offset. Reference-model/data comparisons must state their validity domain. Add plasticity for metals, viscoelasticity for rubber and anisotropy for wood as separate tested capabilities, not labels applied to the brittle solver.

**Exit:** changing a supported characteristic produces the expected quantified response; canonical load/stiffness/failure/energy envelopes converge within specified tolerances; unsupported characteristics are surfaced honestly.

## Gate 3 — complete the ball test ground

Add controlled free-flight/drop, frictionless sliding, slide-to-roll, backspin/overspin, inclined slipping/rolling, off-center collisions, both-body activation, support-impact activation and repeated shard impacts. Add file-driven reproducible experiment configuration and per-run metrics. Retain material lineage and state after fragmentation.

**Exit:** real contact-point velocity determines measured rolling/slipping; frictionless tests do not self-spin; ideal reference tests do not acquire spurious density dependence; gravity/slope experiments and fragment landings remain consistent; input changes are reproducible without manual timing.

## Gate 4 — general contacts, supports, and geometry

Extend beyond a rigid sphere and material points: arbitrary supported rigid shapes, multiple active objects, material self-contact, finite support extent/thickness, curved/moving surfaces and continuous collision handling. Use actual support/contact loads where required rather than an `m*g` proximity shortcut. Improve concave fragment collision proxies without changing material mass.

**Exit:** objects fall off edges and land without invisible infinite planes, persistent interpenetration, or missing counterpart reactions; representative high-speed and mixed-representation scenes remain within declared numerical limits.

## Gate 5 — adaptive matter and measured real-time cost

Profile each stage and establish a reference machine and reproducible scenes. Add sparse bricks for larger objects, aggregate physical summaries, contact-centered activation, boundary coupling, error-driven expansion, persistent damage transfer, stable re-coarsening and sleeping. Add budget-aware debris policies with explicit fidelity limits. Port only measured bottlenecks to GPU, retaining a CPU reference.

**Exit:** many inactive objects stay cheap; impact cost follows the active region rather than total world volume; refinement does not change the material law or violate transfer accounting; frame/latency/memory percentiles and worst cases are measured. A target such as 60 Hz is not a completed benchmark until measured.

## Gate 6 — validated precomputation and speculation

Keep analytical projections distinct from simulated outcomes. Complete cache identity with material-content/geometry/state/solver hashes, both spins, contact frame, damage, gravity/support, time integration and numerical provenance. Harden serialization validation and cache invalidation. Add time-aligned outcome replay/resumption that does not jump a future terminal state into the current tick.

Then schedule multiple likely continuations before contact, prioritize by expected benefit, cancel stale branches, and select only after actual conditions are checked. Fall back to live/refined/explicit lower-fidelity physics outside the validated domain. Do not interpolate incompatible fracture topologies.

**Exit:** cached and live trajectories/ledgers agree within documented applicability bounds; changed state invalidates a result; misses never choose unrelated animation; end-to-end saved time exceeds speculation overhead on measured scenarios.

## Gate 7 — assemblies and editable laws

Implement material-backed interfaces and semantic hinges/fasteners/welds/adhesives. Build the door test: assembled wood/metal mass properties, constrained swing, local failure, anchor detachment, and post-failure motion. Introduce schema/unit checking, solver capability declarations and a small trusted law intermediate representation before a broad language grammar.

Add family-specific models and fields only with stated coupling, work and validation rules. Surface coatings, orientation, thermal/state dependence and fictional laws require explicit consumers and tests.

**Exit:** a creator changes matter/constraints/laws rather than authoring an outcome; invalid units/unsupported behaviors are rejected; interfaces fail based on their loads/materials; assemblies remain compatible with local activation and conservation bookkeeping.

## Gate 8 — creator language, APIs and AI workflow

Expose bounded authoring, queries, events, tests, diagnostics and serialization. Implement the LawScript-equivalent declarative front end, cost/capability checks and sandboxed high-level behaviors. AI produces inspectable source and tests, not uncontrolled per-voxel runtime loops or mandatory per-tick model calls. Keep trusted solver plugins separate from ordinary creator permissions.

**Exit:** a user/AI can generate, test, revise and reproduce a material experiment or assembly through the public API; code and memory limits are enforced; source is portable within a declared physics ABI.

## Gate 9 — engine and publishing V1

Add persistent procedural worlds and sparse damage state, versioned universe packages, dependency locks, capability compatibility, preview/validation, safe distribution and remix/version handling. Decide multiplayer authority/replication, resource budgets and correction policy explicitly; cross-platform bitwise determinism is not assumed. Hosting and commercial features require separate product decisions.

**Exit:** publish, load and modify a bounded world without losing material history or changing laws silently; untrusted packages respect permissions and resources; a published object declares its required physics capabilities. This is the publishing milestone, distinct from a good destruction demo.

## Keep the project on track

Every checkpoint should state: source commit/branch; implemented change; reproducible tests; quantitative result and tolerance; numerical/model limitations; measured performance; remaining work; and main-versus-experimental status. Update the status document and property coverage matrix when features move between categories. Do not call a gate complete merely because its types, menu items, or future enum values exist.
