# Banjo roadmap and acceptance gates

**Normal contact energy correction:** [Support reactions and real impacts](normal-contact-energy-checkpoint.md) now have separate energy accounting in the coupled tetrahedral solver. Glass/oak/iron complete the previously failing 10.1 ms onset under the same limits; four full fictional-material runs use 6.1–10.0 times fewer calls. The raw energy gate remains strict. Longer stiff runs, stable fracture and realtime remain open; next audit sticking friction and stiff integration cost.

**Thin-plate admission correction:** [The reported first-test failure](plate-admission-checkpoint.md) now has matching Python/native geometry preflight and a visible numerical error. An identical live prompt produces 42 actual 3D frames with an explicitly assumed 6 mm plate, then stops at 0.342 s with zero broken bonds in glass/oak/iron. Stable fracture remains open; this is a setup/UI correction, not new physics validation.

**Dynamic material playground:** [Property-authored coupled impacts](dynamic-material-playground-checkpoint.md) now execute explicit SI elastic/orthotropic/J2 descriptors through a bounded native API and render actual sphere and nodal states in the embedded 3D playground. Per-material contact/work/energy evidence and honest solver limits feed the GPT review. R08 is active; this is experimental computed playback, with spatial accuracy, unloaded dents, fracture, finite-strain rubber and realtime still open. All nine original workstreams and 40 mechanics are retained.

**Adaptive material contact:** [Error-controlled advances](adaptive-material-contact-checkpoint.md) add transactional error/work budgets, optional velocity Verlet with final contact-velocity constraints, and cached constitutive state. Two full elastic/J2 reference drops pass a 3 microjoule accumulated numerical-energy budget; finer meshes exhaust the work cap. Spatial accuracy, unloaded dents, calibrated failure, playground integration and realtime remain open. All nine prior workstreams and 40 mechanics remain retained.

**Coupled contact checkpoint:** [Sphere/mesh dynamics](coupled-contact-checkpoint.md) now connects moving tetrahedral material state, swept sphere contact, friction and plastic history with explicit energy/momentum diagnostics. R03 and impact-driven J2 integration are active; temporal/spatial accuracy, unloaded dents, fracture, rubber and playground integration remain open. All nine earlier workstreams and 40 mechanics remain retained.

**General material rules execution:** [Ten implementation goals](rules-engine-execution-plan.md) are active. R01/R02 now have a property-based native material path and a bounded inertial tetrahedral foundation; coupled impact fracture, residual dents, finite-strain rubber, shared persistence and realtime qualification remain unfinished. All nine earlier workstreams and 40 mechanics remain retained.

**Experiment evidence checkpoint:** [Logging, GPT review and corrected drop duration](experiment-review-checkpoint.md) adds auditable saved evidence and on-demand analysis. Actual three-material rebound is recorded; solver contact-force telemetry and calibrated material response remain open. All nine goals and 40 mechanics are retained.

**Composable experiment checkpoint:** [General experiment authoring](general-experiment-checkpoint.md) adds configurable comparative drops and freely composed initial scenes, typed GPT proposals, explicit fidelity and archived 3D results. Experimental6mm panels are admitted but fail the damage/refinement gate; no thin-shell, calibrated fracture or realtime claim is made. The [seven-stage execution plan](general-experiment-plan.md) retains all nine goals and40 requirements.

**Embedded 3D playground checkpoint:** [Chat-authored experiments and controls](embedded-playground-checkpoint.md) now connects GPT plans to native recordings and an in-page 3D viewer. Physical controls rerun the engine without another model call. All 58 native suites, 3 recorder tests and 49 mocked/control tests pass. This is bounded computed playback; integrated calibrated impact/deformation and realtime qualification remain open. All nine goals and 40 requirements are retained.

**Pressure API and assembled-solver checkpoint:** The [bounded pressure and stiffness implementation](continuum-pressure-performance-checkpoint.md) integrates partial-face loads and provides an optional same-law block-CSR solve. All 58 native suites pass (83.49 s); added pressure-state cases pass a subsequent focused rerun, and 33 mocked playground tests pass (2.164 s). Crossed mesh/load studies still fail the high-load spatial-accuracy gate; the finest iron mesh hits the explicit work cap. Kernel benchmark execution is smoke-tested, but repeated isolated performance qualification remains pending. All nine goals and 40 requirements remain retained.

**Spatial pressure checkpoint:** The [connected continuum reference](continuum-pressure-checkpoint.md) solves isotropic glass, orthotropic oak and J2 iron under the same pressure footprint. It adds residual plastic geometry, full spatial state round-trip and a chat-to-computed-native-sequence route. Low-load controls recover, but high-load iron is not spatially converged and oak reaches declared validity limits. Dynamic contact, calibration, compact world state and real-time qualification remain open.

**September 6 goal and playground checkpoint:** The [fully updated goal](project-goal-2026-09-06.md) groups all 40 retained requirements into nine workstreams. [New foundation evidence](playground-foundation-checkpoint.md) covers J2 permanent material state, bounded intrinsic variation, compact lossless numeric history, and a GPT-to-Banjo API playground. All 55 native suites and 29 mocked playground tests pass. Spatial dents, calibrated glass fracture, live-world persistence/repair and global realtime remain open.

**Additional physics checkpoint — September 6, 2026:** Opt-in cold-neighbor thermal activation now preserves stored energy, phase and reactive history while bounding active work. Mechanical damage trials support complete tick rollback, spring-configuration cache reset and explicit unresolved-limit diagnostics. All 52 regression suites pass; thermal storage scaling passes, while fracture convergence and full work closure remain open. See the [implementation, experiments and next gates](additional-physics-checkpoint.md).

**Next G02/G05 gates:** The contact-capacity failure and rotating-spring stress reconstruction are corrected. Endpoint damage trials and complete rollback now exist. Next add an embedded state/work estimator for missed peaks, qualify contact-distance/space refinement and bounded active detail with conservative rigid-to-local transfers. Do not treat larger buffers or lower cell counts as a validated world-scale solution. See the [checkpoint and evidence](contact-fracture-checkpoint.md).

**Generated-object gate:** Use the [API-generated scene suite and normal-speed studio](generated-physics-validation.md) to separate analytical motion, API admission, repeated outcomes, visual responsiveness and material realism. Next resolve glass stress transmission and knife separation under contact/time/space refinement, and extend measured active-load budgets before increasing material or world-scale claims.

**Authoring API checkpoint:** [Field reference and starter client](object-authoring-api.md) now document the implemented package/load/step/query/export path and distinguish it from planned live spawning, forces, assemblies and coupled thermal state. The next platform gate remains transactional mutation and shared state/history, not a new client wrapper.

**Material showcase:** [Iron-ball panel speeds and knife/tomato proxy](material-showcase.md) add genuine rigid spheres, matched glass/oak/iron clamped panels at 2/6/12 m/s, and explicit damage overlays. Wood has 0/0/11 broken links; glass has none at the authored step. All panels and the tomato retain a connected core containing all their cells. This demonstrates local damage, not validated glass shattering or a complete tomato slice. G02 is active; contact/time/space convergence and work closure remain open.

**Current executed checkpoint:** See [execution-checkpoint.md](execution-checkpoint.md) for the live blocky `CellSkin` default and measured same-law phase evidence. The older 44-suite result is historical; 47/47 suites now pass (83.33 s). No gate below is complete from this slice alone.

**Owner representation decision:** Voxel or sphere/particle matter may carry a separate appearance skin, with new surfaces generated from surviving matter and exposed interfaces after damage. The [skin contract](object-skin-contract.md) covers partial cracks, physical layers, material interiors, bounded remeshing and rendering/physics separation. Legacy blocky fragment surfaces exist; the earlier statement that continuous live v2 skins remained planned is historical and is superseded by the executed blocky v1 slice. Smooth/deforming skins, skin/contact convergence, and finite-strain calibration remain open.

**Execution status:** G01 blocky live skins are exercised with stable IDs, failed-face exposure, accepted-break topology caching, no physical mutation, and two focused tests. G05 preserves backward-Euler behavior across five affine intervals and 432 oracle cases, with a measured 4.37–4.77x pair speedup. G03 explicit atomic same-clock joining passes focused tests; automatic frontier coupling remains open. Smoke and full fluid remain deferred.

**Historical 44-suite baseline:** All 44 regression suites passed for that baseline. The [world checkpoint](world-foundation-checkpoint.md) includes strict [SI language packages](world-physics-language.md), bounded thermal/reaction jobs, and ice/water enthalpy with latent heat. Repeated sparse-world tests separate stored volume from active cost and expose overload backlog. Glass/contact accuracy remains an open mechanical gate; smoke and full fluid flow are deferred. The [plan](world-runtime-plan.md) and all 40 scorecard requirements remain in force.

**World foundation checkpoint:** The [runtime plan](world-runtime-plan.md) now prioritizes material-law correctness, sparse world storage, bounded active work, and named energy stores. The [initial implementation](world-foundation-checkpoint.md) adds thermal/reaction conservation, explicit backlog, a comparative visual lab, and mechanical temporal-resolution diagnostics. Four affected suites pass. Glass/contact correction remains open. Ice/water enthalpy and latent heat are next; smoke and full fluid dynamics are deferred by owner direction. All 40 retained mechanics/platform requirements remain in scope.

**Next acceptance gate after v2:** Source `61c5edc` is published on main with 39 passing suites. [Refinement evidence](network-runtime-checkpoint.md#repeated-performance-and-refinement-evidence) shows local-cut topology is not converged and stiff impact response is unresolved. Prioritize resolved contact surfaces, coupled deformation/work validation and bounded local activation before expanding surrogate training or claiming realistic cutting. Preserve the eight current examples and all prior bowl/platform tests.

**Material-network v2 (experimental):** [Network runtime checkpoint](network-runtime-checkpoint.md) documents the current `material-network-v2` / `banjo-network-2` path: property-driven occupied-cell boxes/ellipsoids, rigid convex wedge tools, and a single-clock Jolt spring/contact/gravity runtime with irreversible local cohesive damage. Directional oak response is an axial lattice approximation, while the axial perfect-plastic demonstrator is not calibrated iron. The eight-fixture glass/oak/iron/soft-tissue set and provisional CPU timings are evidence for bounded experiments only. Glass stiff-wave response remains under-resolved, v1's pulse backend stays selectable, and the 1024-cell/20,000-link/32-object limits are explicit. Before a learned surrogate is considered, require local surface refinement, adaptive localized execution, and closure of strain, contact, damping and energy ledgers. No RL/neural training or global realtime claim is in scope.

**Latest compiled-runtime checkpoint (experimental):** [Compiled runtime checkpoint](compiled-runtime-checkpoint.md) records the new `compiled-impact-v1` live backend: compiled mass/inertia and structural response factors, a 64-step local linear impact pulse on damaging contact, re-solves after failed bonds, seeded persistent variation, measured-loss-bounded fracture-work reclassification, and surviving components handed to rigid fragments without launch kicks. Smooth intact spheres use a coarse 19-sample fragment skin and boxes 27 samples. Native 3 s drop playback was verified live at 60 FPS; eight packages and the 128-object initial admission limit are covered, including the 96-object load fixture. This is not AVBD, full continuum validation, or a complete conservation/reaction ledger; oak and iron remain rigid-only (no grain, plasticity, or failure). All 36 regression suites passed; repeated performance measurements and the publication record are described in the linked checkpoint.

**Playback speed correction:** [Exact-scene playback](platform-playback-checkpoint.md) calculates reference trajectories once and replays at normal wall-clock speed, retaining four exact initial-package recordings within the process. Scratch-buffer reuse preserves the tested physical outputs; calculation still takes roughly 38 s for the tested 1.1 s drop. Live adaptive real-time physics remains unfinished.

**Offset and fracture-height drops:** [New comparative evidence](height-drop-checkpoint.md) retains centred controls, adds physically deflecting off-centre drops, and compares iron-on-glass with iron-on-oak from four heights. Glass progresses from intact to separated pieces in the reference model. Finite solid-ground contact, visible bond counts and zoom are implemented; real-glass calibration and near-real-time reference performance remain open.

**Object-on-object drop tests:** [Four new drop examples](drop-test-checkpoint.md) add spheres/cubes falling onto freely resting targets on finite concrete ground, each comparing glass/oak/iron. All 12 combinations pass motion/contact checks; all 21 example packages pass. This is rigid collision coverage, not fracture. Source `de8129f`; published with this checkpoint.

**Main publication checkpoint — September 5, 2026:** This checkpoint brings the accumulated physics, application and platform work through `60173e6` onto main. Full Windows MSVC Release build passes; all 34 tests pass in 69.08 s. Outgoing history was checked for API-key patterns with no matches. The owner now authorizes regular verified main updates (see AGENTS.md). Earlier “local only” notes describe historical checkpoint publication status; they do not indicate that code included here is absent from this main checkpoint. Experimental physics limitations and all unfinished platform gates remain in force. GitHub CI is a separate check and must be reported from its actual result.

**Platform-first direction (current owner priority):** Banjo is a Unity-like, LLM-accessible physics authoring and publishing platform for game makers. Inventory, crafting and progression are the first customer application, not the engine roadmap. Preserve all physics and publishing requirements; require measured near-real-time execution alongside correctness. The bowl is the first extensible conformance and performance laboratory, not the product boundary. [Platform SDK checkpoint](platform-sdk-checkpoint.md) implements an inventory-independent runtime, 17 executable scene packages and headless/visual clients. Automatic physical LOD and full publishing remain open. Earlier customer-first priority notes below are historical and superseded.

**Rolling/fracture correction:** [Strength gate and computed replay](rolling-strength-checkpoint.md), source `aa3491f`, local only. Glass/oak/iron isolated rolling is damage-free over 0.3 s; strong glass impact still fractures progressively. The native eight-ball 1.25 s replay moves visibly and ends with four broken links but eight connected groups; contact attribution remains open. Calculate prepares a fresh trajectory, then Replay shows normal-speed motion. Coarse contact geometry, continuum calibration and the full platform remain unfinished. Earlier energy-only bowl notes below are historical.

**Fracture now runs in the bowl:** [Experimental bonded-cell checkpoint](bonded-bowl-checkpoint.md) connects crafted balls to local energy-driven failure, surviving internal networks and continued curved-support/multiple-body contact. Glass fractures during release; oak and iron retain elastic connections. Source `f55f996`, UI `a939df0`, local only. This is a slow, coarse 19-cell model with uncalibrated strength and contact geometry, not the completed realistic-fracture gate.

**Interactive fracture microscope:** [Visual checkpoint](fracture-microscope-checkpoint.md) connects accepted solver trajectories to the native bowl app, with glass/oak/iron comparison, four impact speeds, playback, scrubbing and event stepping. Source `413852a`, local only. Both affected suites pass in promoted and legacy builds. This is the eight-region connector reference; whole-ball fracture and live bowl fragment contact remain open.

**Local fracture cascades:** [Surviving-network propagation](rupture-cascade-checkpoint.md) now advances contact, local rupture and subsequent internal failure on one clock, with recursive time refinement and whole-interval rollback. An eight-region impact leaves a six-region core intact while a detached two-region piece breaks later. Four affected suites and the new legacy test pass. Local `334454d`; whole-ball/bowl integration remains open.


**Fracture component:** [Energy-accounted rupture](energy-rupture-checkpoint.md) now combines accepted elastic/contact motion with a transactional tensile break, explicit Gc-area work and a separate event-overshoot budget. Low/high glass impact cases and matched glass/oak/iron reference experiments pass; five affected suites pass, plus the new legacy test. Local `6b44c2f`. Whole-ball geometry, event convergence and live bowl fragment handoff remain unfinished; fracture is still disabled in the bowl.


**Immediate owner priority: craft-and-release bowl lab.** Complete inventory-backed glass/oak/iron ball crafting, placement/release in an adjustable concave bowl, rolling/collisions/rebound and physically driven fracture before moving to the next physics family. The [bowl checkpoint](bowl-checkpoint.md) records the new running rigid preview and the explicit unfinished fracture gate. Broader assembly contact research is paused, not discarded. Preserve every existing mechanic and platform gate.


**Adaptive runtime trials:** [Full/half-step comparison with complete rollback](adaptive-runtime-checkpoint.md) accepts bounded smooth separation for glass/oak/iron using 318 evaluations and unchanged global work budgets. All rotational fixtures still reject at the state-refinement floor. Four affected suites pass in both builds; contact-state convergence remains next. Local `57102de`/`7229159`; full goal active.

**Reversible contact trials:** [Complete runtime state restoration](reversible-trial-checkpoint.md) covers Jolt contacts/constraints/global state plus Banjo ticks/events, with configuration guards and nested rollback. Glass/oak/iron replay tests pass in both configurations; all 28 current and 26 legacy suites pass. Adaptive assembly integration remains next. Local `654c668`; full goal active.

**Collision-step error localized:** [Bounded assembly work ledgers](assembly-work-checkpoint.md) place about 78/70 percent of the maximum oak/iron integration error in single steps with strong Jolt responses. Physics and tolerances are unchanged; all four affected suites pass in both configurations. Next restore/refine complete temporary contact steps. Local `4844fb2`; full goal active.

**Rotational loading and inertia correction:** [Off-center assembly trials](assembly-spin-checkpoint.md) found and corrected small-box fallback inertia, with independent glass/oak/iron tensor/energy checks. Oak/iron integration failures remain explicit. All 27 current and 25 legacy suites pass. Runtime identity changed; existing graphical saves need explicit migration before promotion. Local `e86cb8e`; full goal active.

**Declared runtime assemblies:** [Explicit contact policy and public Jolt tests](runtime-assembly-checkpoint.md) compile face sites and run bounded temporary trajectories with per-site histories and energy diagnostics. Glass/oak/iron CLI trials and all four affected suites pass in both configurations. Live material-backed assembly creation remains open. Local `c7aa5d9`; full goal active.

**Atomic tensile patches:** [One audited update for 1..256 sites](tension-patch-checkpoint.md) preserves individual area/history, shared torque/work and Jolt surfaces. Glass/oak/iron ordering, subdivision and rejection tests pass; all 27 promoted suites pass. Whole-step integration and live crafting remain next. Local `b948acc`; full goal active.

**Tension with surface contact:** [Runtime tensile kicks](tension-contact-checkpoint.md) retain Jolt collisions, reject duplicate compression/activation ownership, and keep externally advanced bodies awake. Glass/oak/iron opening, failed-bond collision and coupled contact fixtures pass; 27 promoted and 25 legacy suites pass. Finite-area/application integration remains open. Local `0b01533`; full goal active.

**Double-position application:** [Converted graphical workspaces](double-application-checkpoint.md) now run the promoted configuration. Native inventory/three-material requirements, assembly test/export and save/restart checks pass; all 25 suites pass. New builds default to double positions; explicit legacy builds remain. Local `d96ca7e`; full goal active.

**Explicit precision conversion:** [Source-preserving review packages](precision-conversion-checkpoint.md) validate v5 32-to-64 upgrades for creator and starter worlds. Real workspace-copy normalization/conversion/reload and overwrite rejection pass; 24 default and 25 double-position suites pass. Application promotion remains next. Local `3bd8b74`; full goal active.

**Saved precision identity:** [World/starter v5](precision-identity-checkpoint.md) records compiled position precision and rejects cross-precision loads. Four-way real CLI checks, glass/oak/iron persistence, 23 default and 24 double-position suites pass. Explicit conversion and application promotion remain next. Local `7887177`; full goal active.

**Runtime joint precision evidence:** [Cohesive forces through live drift](runtime-cohesive-checkpoint.md) expose 11/12 finest accuracy failures in the current single-position build. A separate double-position build passes all 24 suites and all 12 checks. Precision identity/save compatibility must precede application integration. Local `f5d2226`; full goal active.

**Audited live impulses:** [Pair transfer accounting](pair-impulse-checkpoint.md) now preflights float/speed limits and measures work, momentum and noncentral couples for glass/oak/iron. All 23 suites pass. Joint-law integration, surface response and physical source accounting remain open. Local `2fa2fe2`; full goal active.

**Runtime contact ownership:** [Explicit body-pair routing](contact-ownership-checkpoint.md) suppresses duplicate Jolt responses, invalidates cached contacts and cleans up reused IDs. Glass/oak/iron routing/free-flight tests and all 22 suites pass. External joint/surface response and live assembly creation remain open. Local `5e7aa4e`; full goal active.

**First-person assembly review:** [Table LLM review](starter-assembly-review-checkpoint.md) regenerates physics and actual player-stock evidence, with context invalidation. Real native oak reply/revision checks and three-material backend review checks pass; 21 suites pass. Live assembly contact and resource accounting remain open. Local `1a251cc`; full goal active.

**First-person assembly testing:** [Table test controls](starter-assembly-test-checkpoint.md) run isolated physics in the background and export exact-revision evidence. Native oak run/export/stale checks and 21 suites pass. Table LLM review and live construction remain open. Local `6a5fae9`; full goal active.

**First-person assembly table:** [Remembered assembly designs](starter-assembly-table-checkpoint.md) persist in starter v4 with v1–3 migration and save-before-publish revisions. Native oak import/restart verified; three-material persistence checks and 21 suites pass. Table tests/LLM review and live creation remain open. Local `f210372`; full goal active.

**First-person assembly stock:** [Shared assessment adapter](starter-assembly-stock-checkpoint.md) uses real starter inventory and loose objects, excluding attached branches/tools. Three-material pickup, restoration, tool debit and mixed-material checks pass; full build and 21 suites pass. Starter assembly persistence/table controls remain next. Local `b02bab9`; full goal active.

**Assembly LLM review controls:** [Regenerated evidence review](assembly-review-ui-checkpoint.md) runs from current tests, invalidates world/spec changes and supports cancellation. Real native oak explanation, inventory invalidation and cancellation verified; 21 suites pass. First-person integration and live construction remain open. Local `c06ee32`; full goal active.

**Assembly test controls:** [Revision-bound background tests](assembly-test-ui-checkpoint.md) expose settings, measured outcomes and evidence export. Native oak pass/fail, stale-revision and budget-error paths verified; all 21 suites pass with glass/oak/iron coverage. LLM review controls and first-person integration remain open. Local `22932be`; full goal active.

**Assembly workshop UI:** [Saved-design review](assembly-ui-checkpoint.md) shows parts, joint quantities and current inventory shortages; native oak import/collection/revision/restart and glass/iron layouts verified. All 21 suites pass. Testing/review controls, first-person integration and live construction remain open. Local `acf41d1`; full goal active.

**Saved assembly drafts:** [Revisioned declarations](assembly-draft-checkpoint.md) survive CreatorWorld save v4, migrate v1–3 and reassess current stock. Glass/oak/iron CLI restart checks and all 21 suites pass. UI, live construction and physical energy remain open. Local `931be9f`; full goal active.

**Real LLM assembly review:** [Verified assessment/test evidence](assembly-review-checkpoint.md) reaches the provider through a review-only boundary. Six glass/oak/iron replies correctly distinguish outcomes, stock and unsupported creation; recipe injection rejects; 21 suites pass. UI/build integration remains open. Local `b08d0d7`; full goal active.

**Assembly test API:** [Bounded isolated separation tests](assembly-test-checkpoint.md) share assessment compilation and return measured pass/fail with body/site/energy evidence. Three-material CLI checks preserve live state; 21 suites pass. Live assembly creation and LLM/UI integration remain open. Local `9ddcc4e`; full goal active.

**Assembly assessment API:** [Read-only two-box declarations](assembly-assessment-checkpoint.md) report derived quantities, aggregated inventory shortages and explicit unsupported live creation. Six three-material CLI assessments preserve state; 21 suites pass. Local `daecb00`; full goal active.

**Compiled-joint loading:** [Box-face compilation through separation](compiled-load-checkpoint.md) passes nine material/axis cases with geometry-derived fracture work and bounded energy error; 21 suites pass. Creator assembly/contact ownership remains next. Local `3c5d007`; full goal active.

**Box-face attachments:** [Material-backed geometry compiler](box-face-checkpoint.md) derives mass/inertia and validates interface rectangles on opposing box faces. Nine material/axis cases and 21 suites pass. Creator API/contact ownership and spatial convergence remain open. Local `a815321`; full goal active.

**Combined joint loading:** [Compression with tensile damage](combined-bending-checkpoint.md) passes three-material bending and whole-system momentum/energy checks; 21 suites pass. Idealized joint only: geometry/contact ownership and spatial convergence remain open. Local `08267f8`; full goal active.

**Interface compression:** [Optional reversible compression](cohesive-compression-checkpoint.md) supports patch closure/rebound after tensile failure without healing. Glass/oak/iron and 21 suites pass. General surface contact, calibrated crushing and cutting remain open. Local `ef7e2c4`; full goal active.

**Adaptive finite patches:** [Shared error control](patch-adaptive-checkpoint.md) bounds distributed-patch energy error and preserves per-site history through retry/continuation. Glass/oak/iron and 21 suites pass. Spatial convergence and compression/contact remain open. Local `e3f53bf`; full goal active.

**Independent bending oracle:** [Exact force/moment/damage integrals](bending-oracle-checkpoint.md) bound prescribed-opening quadrature errors across glass/oak/iron; 21 suites pass. Dynamic damage-front convergence remains unproven. Local `610da9c`; full goal active.

**Patch convergence limit:** [Area-integrated comparisons](patch-refinement-checkpoint.md) cover 36 three-material cases. Fine-grid differences are bounded, but damage-work differences are nonmonotonic in five of nine comparisons; spatial convergence remains open. All 21 suites pass only the stated bounded checks. Local `716c27d`; full goal active.

**Finite cohesive area:** [Rectangular patch reference](cohesive-patch-checkpoint.md) distributes geometric area and independent damage over shared rotating bodies. All 27 glass/oak/iron bending cases and 21 suites pass. Spatial convergence, compression/contact and starter integration remain open. Local `9b1229f`; full goal active.

**Adaptive cohesive advances:** [Bounded error control](cohesive-adaptive-checkpoint.md) refines coupled motion using state disagreement and accumulated absolute energy error; glass/oak/iron and 21 suites pass. Budget exhaustion rejects without a partial candidate. Physical interfaces and exact event resolution remain open. Local `47ae5c6`; full goal active.

**Asymmetric cohesive verification:** [Unequal-body trajectories](cohesive-asymmetric-checkpoint.md) pass whole-trajectory momentum and energy/velocity refinement checks for glass/oak/iron; 21 suites pass. Physical attachment geometry, event resolution and cutting remain open. Local `c56988a`; full goal active.

**Coupled rigid cohesion:** [Moving and rotating attachments](cohesive-rigid-checkpoint.md) now drive damage and separation in a bounded reference. Glass/oak/iron refinement and 21 suites pass; numerical energy error is reported explicitly. Asymmetric coupling, physical surfaces and realistic cutting remain open. Local `ae7c495`; full goal active.

**Rigid attachment transfer:** [Off-center impulses and spin](rigid-attachment-checkpoint.md) now account for full-tensor rotation, impulse work and applied couples; three-material tests and 20 suites pass. Coupling to evolving cohesive motion and realistic cutting remains open. Local `6992342`; full goal active.

**Elastic turning accuracy:** [Circular-orbit oracle](cohesive-orbit-checkpoint.md) shows second-order timestep convergence for glass/oak/iron; all 19 suites pass. Damage-path convergence and extended-body attachments remain open. Local `faa78bb`; full goal active.

**Spatial cohesive reference:** [Three-dimensional central motion](cohesive-spatial-checkpoint.md) passes glass/oak/iron reduction tests and a turning orbital-momentum/energy check; all 19 suites pass. Extended rigid-body rotation, actual attachments, cutting and default fracture defects remain open. Local `ab8bcd3`; full goal active.

**Finite cohesive pair:** [Motion-driven interface separation](cohesive-pair-checkpoint.md) now transfers equal/opposite impulses and accounts for kinetic, stored and damage energy in a collinear two-mass reference. Three-material sub/supercritical trajectories and 18 suites pass. Geometry/rotation/contact coupling and default fracture defects remain open. Local `2e9b061`; full goal active.


**Cohesive-interface reference:** [Normal opening with accounted work](cohesive-interface-checkpoint.md) now consumes explicit strength, stiffness, Gc and area with irreversible history. Three-material coupons and 17 suites pass. Separate reference only: dynamic/lattice coupling, realistic cutting and default correction-energy defects remain open. Local `5360f03`; full goal active.


**Functional-test checkpoint:** [Isolated recipe tests](functional-test-checkpoint.md) measure travel/contact/slip on a declared incline without spending live resources. Three-material sphere/box comparisons, nine CLI cases, native saved-oak testing and all 16 suites pass. This is one bounded rigid fixture, not general functional or fracture certification. Local `cf73e5e`; full goal active.


**Remembered-design checkpoint:** [Saved starter proposals](remembered-design-checkpoint.md) retain exact recipes across closing/reopening and update readiness after gathering. Three-material tests and 16 suites pass; one real native oak request survived restart without another model call. Save v3 migrates v1/v2. Local `8bde4da`; full goal remains active.


**Saved-action checkpoint:** [Starter save-before-publication](starter-transactions-checkpoint.md) prevents failed saves from spending live resources or granting XP/tools. Glass/oak/iron failure/reload/retry tests and all 16 suites pass; native failed and successful wooden-tool crafting verified. Single-writer local scope; recovery UI, common durable APIs and physical energy remain open. Source `659cc54`, local only.


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
