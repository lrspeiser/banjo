# Development status and handoff

**World foundation checkpoint:** The [runtime plan](world-runtime-plan.md) now prioritizes material-law correctness, sparse world storage, bounded active work, and named energy stores. The [initial implementation](world-foundation-checkpoint.md) adds thermal/reaction conservation, explicit backlog, a comparative visual lab, and mechanical temporal-resolution diagnostics. Four affected suites pass. Glass/contact correction remains open. Ice/water enthalpy and latent heat are next; smoke and full fluid dynamics are deferred by owner direction. All 40 retained mechanics/platform requirements remain in scope.

**Published v2 verification:** Source `61c5edc` is on GitHub main. All 39 suites pass. The [final evidence](network-runtime-checkpoint.md#repeated-performance-and-refinement-evidence) supersedes provisional timings below: 24 three-second trials have identical outcomes at fixed settings; the soft-cut timestep/grid sweeps are not converged. The single-cut example meets the measured physics-time budget on this CPU, while the four-material comparison exceeds realtime. Material realism, energy closure and automatic physical LOD remain unfinished.

**Material-network v2 (experimental):** [Network runtime checkpoint](network-runtime-checkpoint.md) records the current `material-network-v2` backend with ABI `banjo-network-2`, bounded to 1024 cells, 20,000 links and 32 objects. It is property-driven across material IDs and shape declarations: occupied-cell boxes/ellipsoids and rigid convex wedges run springs, contact and gravity together, with irreversible local cohesive damage and an axial perfect-plastic demonstrator. Oak is a directional axial lattice approximation rather than a full grain continuum; the ductile demonstrator is not calibrated iron. Eight current fixtures cover glass, oak, iron and soft tissue. Earlier provisional measurements were about 0.53 CPU seconds for 1 second of a 121-cell tissue case and 1.18 CPU seconds for 1 second of a 328-cell four-material case; the checkpoint supersedes exact timing once recorded. Glass stiff-wave behavior remains under-resolved/unreliable; v1's pulse backend remains selectable. Clamped panel boundaries do not implement door hinges or complete carved chips. Local surface refinement, adaptive localized runtime, and strain/contact/damping/energy closure remain required. No RL/neural training or global realtime claim is made.

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


**Saved-action checkpoint:** [Starter save-before-publication](starter-transactions-checkpoint.md) prevents failed saves from spending live resources or granting XP/tools. Glass/oak/iron failure/reload/retry tests and all 16 suites pass; native failed and successful wooden-tool crafting verified. Single-writer local scope; recovery UI, common durable APIs and physical energy remain open. Source `659cc54`, local only.


**Starter designer checkpoint:** [The real LLM crafting table](starter-designer-checkpoint.md) now proposes supported shapes from actual player stock/level/stamina, preserves shortages, and independently validates Build. Five real trials and all 16 suites pass; native request/paste and blocked proposal verified. Save v2 migrates v1 progress. Full native gameplay, durable common APIs, physical energy and realistic branch cutting remain open. Local source `29e46a2`; full goal active.


**First-person starter checkpoint:** `c10d379b6da72f7f07a283909d6dd577d4302084` adds [Willow Clearing](starter-checkpoint.md): body-free first-person view, click collection into raw voxel-equivalent stock, preset crafting with material/level/stamina requirements, XP, tool cost reductions and a cuttable fixed branch that falls under Jolt gravity. All 16 suites pass at its runtime foundation; the later input patch verifies native inventory/back/pause/resume and mouse look. Full native gameplay remains pending. Stamina/cutting are explicitly game approximations; realistic cutting, physical energy accounting and LLM integration into this new table remain required. The full platform goal stays active; local only.

**Inventory requirements checkpoint:** `fca0cb357d4dc4f154bb6efbb03efb9b69e8134f` now retains supported resource-short designs and reports collected, recoverable, uncollected and missing material through the shared compiler/API. [Evidence](requirements-checkpoint.md): seven real inventory/alternative cases plus five revision/unsupported-capability regressions pass; all 15 Windows suites pass (11.73 s). Automated capture passes; the normal workshop runs, but new-control input verification remains pending the native-helper error. Energy accounting remains unsupported, not zero-cost. Next: reliable API receipts/retries/durability, energy/tool contracts and bounded functional tests. Local only; all full-platform gates remain active.

**Current revision checkpoint:** `14bb0b760f43ee500576a8624a5205a78365e4f4` adds material-accounted selected-object rebuild/reclaim, stable revisions and format-3 history. [Evidence](revision-checkpoint.md): all 15 Windows suites pass (11.71 s), all three real material-reuse requests succeed, reclaimed-object replay preserves stock, and unsupported door/energy requests apply nothing. Automated capture passes and the new normal app is running; native control verification remains pending the repeated helper error. Energy accounting is explicitly unsupported. Next: reliable API command/receipt/durability semantics, inventory energy reference states and bounded functional tests. Local only; the full goal remains active.

**Energy-system direction:** the [energy design](energy-system.md) specifies source stores, tool/process work, combined material/energy transactions and physically consistent making/breaking/recovery. It remains design, with no creator energy-cost implementation. Capability discovery now explicitly reports this limitation; the real 10-joule request returned a no-build clarification. See the revision checkpoint above for current code verification.

**API/platform review, September 4, 2026 Pacific:** [The functional API review](api-platform-review.md) maps 12 application areas to the retained platform scorecard and defines the next build/test/revise milestone. At that review, lifecycle work was uncommitted with focused creator tests, assistant edit-context changes were unbuilt/untested and workshop rebuild/reclaim controls were unconnected. This was a documentation review, not a new full-suite, interactive, remote or physics-validation claim. Finish that lifecycle and consistent command/durability semantics, then expose bounded functional tests and measured feedback through the same API.

**Current shape checkpoint:** `c10afc8afdcd38c670795e93548bd37932f3a70a` extends the shared creator/compiler to oriented solid boxes, full inertia, actual box collisions, version-2 persistence and automatic block proposals. [Evidence](shape-checkpoint.md): 15 Windows suites pass (9.91 s), equal-volume glass/oak/iron sphere-versus-box comparisons, three real block requests and a no-build hinged-door clarification. Final capture passes; normal box-control input verification remains pending because native inspection returned `foreground window did not report a process id`. Next: finish that input check and safe material-accounted revisions/reclamation. Full physics/platform gates remain open; local only.

**Previous automatic-assistant checkpoint:** `ae821677da0e430695417a753921e105273321cc` connects the Windows workshop to background Codex structured proposals and clarifications. [Four real provider trials](assistant-checkpoint.md) cover glass/oak/iron creation and an unsupported door; all 15 Windows CTest executables pass (9.99 s). Normal UI cancellation/retry, typed requests, build/run/save and keyboard input were checked. Only independently validated Build actions spend inventory. Next: a second geometry through the same creator path and safe revisions/material reuse. Detailed-material physics and general publishing remain open. Local only, not pushed or merged.

**Previous creator checkpoint:** `9cd9197bb99492b1a834622cd87d35302468c4dd` adds the [material workshop](creator-checkpoint.md), a shared bounded recipe/compiler/CLI, world pickup inventory, transactional sphere creation and versioned local persistence. A real manual Codex file exchange produced a visible 16 cm oak ball from collected material; automatic in-app model calls and edits/refunds of existing objects remain open. Glass/oak/iron creation, free fall, measured rolling and finite pair collisions pass; all 14 Windows CTest executables pass (9.86 s). Normal interactive controls and capture were checked, including a generated-copy GLFW active-window guard and safe multi-world Jolt lifetime. Next: automatic assistant connection and another geometry through this same creator path, alongside the open detailed-material physics gates. Local only; no push/merge and no full-platform completion.

**Previous adaptive checkpoint:** `8cf33bccf3c21eea69efaea192efa10e1be43198` adds bounded transactional accuracy control, residual-budget allocation and a buried grazing-contact guard. All 13 Windows CTest executables pass (10.23 s). [Twelve full-size glass/oak/iron runs](adaptive-checkpoint.md), recorded at controller source `a7acccfe60cfa3a77159aa831079c67c55380c7f`, complete with closed work/reaction ledgers and 15 matched full-node comparisons. Local error indicators do not prove global convergence; the reference remains far from real time. Next: the [first collected-materials creator loop](creator-loop.md), using an LLM request, inspectable specification, validated inventory debit and a visible physical object. Carry this planned application slice through the shared workbench, one clock/contact owner, work-accounted friction and shape comparisons. Default viewer energy/fracture defects remain. All changes are local and Gate 1 remains open.

**Previous trajectory checkpoint:** `e5b883e6d5d47dc85a5e1ea42c671d94a83cee99` adds complete node-state export and matched-time comparison. All 30 glass/oak/iron impact runs complete across five timesteps; all 12 CTest executables pass (8.60 s). [Measured differences](trajectory-checkpoint.md) show that bulk rebound can hide unresolved internal motion: finest-pair damped node-velocity RMS differences remain 0.0339, 0.0603 and 0.0124 m/s for glass, oak and iron. Full trajectory accuracy remains open, with a bounded state-error controller next. This probe/analysis update changes no solver law or default viewer behavior. Changes are local, not pushed or merged; Gate 1 remains open.

**Previous compliant-contact checkpoint:** `58546cbbcd3696db409124b9f353c231db0ae0e4` adds an explicitly selected normal-interface spring and compression-only dashpot in a coupled, transactional reference. All 12 Windows CTest executables pass (9.04 s), and all 27 full-resolution glass/oak/iron runs complete across undamped impact, damped impact and gravity-loaded contact at three timesteps. [The law, analytical checks and measured limits](compliance-checkpoint.md) distinguish closed work/reaction ledgers from unresolved sampled trajectory convergence. The constant-restitution e=0.3 failure remains; the default viewer solver and its energy defects are unchanged. Maintain the [mechanics scorecard](mechanics-scorecard.md). Gate 1 remains open; this checkpoint is local and not pushed or merged.

**Previous contact-root checkpoint:** `b31a8a5cf51d09dc725fe1448c9eb27254aeb2ea` fixes tiny interval remainders, stalled root brackets and departing-contact classification. All 11 Windows CTest executables pass (6.57 s). Full glass/oak/iron lattices finish the same 2 ms elastic impact using 20- and 10-microsecond intervals; [refinement results and limits](event-root-checkpoint.md) separate conservation from temporal accuracy. Dissipative sampled impacts still reject after repeated tiny impacts, and cost remains far above real time. Maintain the [mechanics scorecard](mechanics-scorecard.md) and growing material set. The default viewer solver is unchanged; Gate 1 remains open.

**Current support checkpoint:** `1deb025dad8eb56754250de1fabba94984217080` globally couples material/plane support with the conservative elastic solve. All ten Windows CTest executables pass, and the full glass floor impact now converges at 2 ms. [Support evidence and timestep sweep](coupled-support-checkpoint.md) expose large impact-phase-dependent numerical loss and unconverged rebound despite closed per-step ledgers. Resolve impact times and the normal-contact law next. This remains a local reference, not the default interactive solver; Gate 1 is open.

**New reference checkpoint:** `dc7bcfb6b9d9392bdf19e82e0baa48e53e0b16cc` adds global Newton/GMRES elasticity to the coupled conservative CPU reference. All ten Windows CTest executables pass. [Global solve results and limits](elastic-newton-checkpoint.md) show accepted full-glass steps at 2 ms and 1/240 s with unchanged conservation budgets; 1/60 s rejects, and accepted runs remain slower than real time. The [initial reference checkpoint](conservative-reference-checkpoint.md) records the original method and local-sweep limitations. This reference is not yet wired into the lab; the default-path checkpoint below and its defects remain current. Gate 1 is open; all changes remain local.

**Default lab checkpoint:** tested code `d56611cd582a1e51e4169ef10e62aa5773eec75b` on `codex/physics-foundation` evaluates damage at accepted states instead of temporary predictor/solver iterates, removes the obsolete synthetic pulse, and adds optional active-stage momentum/energy CSV measurements. Windows Release, all nine then-existing CTest executables, supported/isolated runs, capture and normal input were verified. See [stage evidence and unresolved correction energy](material-stage-checkpoint.md), the [previous transfer audit](transfer-accounting-checkpoint.md), and [property coverage](physics-coverage.md). Gate 1 remains open: separate contact/floor corrections inject substantial spring energy and angular momentum still drifts. This work is local, not pushed or merged into GitHub main. The earlier integration evidence and audit below remain historical snapshots.

**Audit date:** September 4, 2026, America/Los_Angeles. Associated late-day GitHub events are dated September 5 in UTC. This is a pinned snapshot, not a promise that branch heads never change.

Read [project-master-plan.md](project-master-plan.md) for the complete product/architecture intent and [roadmap.md](roadmap.md) for the next work. This documentation checkpoint does not merge experimental code.

## 1. Where the code is

| Location | Audited commit | State |
|---|---|---|
| `main` code baseline | [`62cf812`](https://github.com/lrspeiser/banjo/commit/62cf8129a2ee08c9237eb5c42dac26680d186633) | Material laboratory plus subsequent interactive-window/MSVC build fixes |
| `feature/material-physics-lab` | [`a969178`](https://github.com/lrspeiser/banjo/commit/a969178e2d57555e211f49732e94269f26127712) | [PR #1](https://github.com/lrspeiser/banjo/pull/1) merged via `d944ba7`; no need to treat it as still unmerged |
| `feature/conservative-material-contact` | [`138260d`](https://github.com/lrspeiser/banjo/commit/138260d2f3d2e30a112f28034731db6052ae1720) | [PR #2](https://github.com/lrspeiser/banjo/pull/2) open and draft at audit; contact-driven fracture is not on main |

The documentation commit containing this file is layered on the main baseline above. Distinguish publishing a description of branch work on main from merging that branch's implementation.

**Important integration issue:** main advanced independently after the contact branch started. Preserve the main CMake fixes for `SUPPORT_CUSTOM_FRAME_CONTROL=OFF`, `SUPPORT_BUSY_WAIT_LOOP=OFF`, and `USE_STATIC_MSVC_RUNTIME_LIBRARY=OFF`. Do not replace main wholesale with the branch tree. The main fix explains that deterministic screenshot capture masked a normal interactive frame-presentation/input/timing bug; screenshot success alone is insufficient interactive verification.

## 2. What has been built, in order

### Bootstrap and first visual laboratory

The initial C++23/CMake implementation integrated Jolt, a procedural solid-sphere lattice with partial-cell volume sampling, engine-neutral impact events, energy-based activation, an XPBD-style brittle-bond solver, connected-component discovery, and fragment mass-property calculations. The first program was headless, which is why it built but showed no scene.

The next iteration added raylib visualization, a shared `RollingBallExperiment`, exposed-face meshes, convex collision proxies, batched Jolt fragment insertion, bounded full-rigid fragment counts, and lightweight debris. The renderer observes simulation state rather than owning a separate animation. Headless/visual CI and core tests were added. The earlier visual baseline was `ed0cfb5`.

### Material laboratory, now in main

PR #1 added material/contact definitions and presets, contact combination policies, elastic sphere-impact screening, rotation-invariant local strain evaluation with tensile/compressive/shear failure channels, support-plane/slope handling, full gravity vectors, material controls, analytical scenario projection/CSV caching, outcome serialization APIs, and additional tests. It did not finish constitutive validation or general two-way contact.

The main build fix `62cf812` addresses interactive raylib frame control and MSVC runtime linkage. Its commit message reports Windows and Ubuntu testing by its author. That report is distinct from the Linux Actions result and was not independently reproduced during this documentation audit.

### Conservative contact development, not yet in main

PR #2 replaces the runtime's synthetic fracture excitation with sphere/material contact impulses, defers activating Jolt contacts using sensor-like settings, and synchronizes finite-mass rigid reaction with material microsteps. It introduces measured slip classification, selectable launch spin, rolling-resistance torque instead of forced no-slip reassignment, separation of internal damping from rigid-body vacuum drag, support-footprint checks, and contact dissipation/impulse diagnostics.

The branch also contains an offline source-bundle workflow used to reproduce development with pinned dependency sources. That is a development aid, not part of the world-publishing system.

Read the [pinned contact checkpoint](https://github.com/lrspeiser/banjo/blob/138260d2f3d2e30a112f28034731db6052ae1720/docs/contact-checkpoint.md) and its source/tests before integration. The checkpoint's statement that graphical CI still needed checking was true when written; the CI evidence below supersedes that status only.

## 3. Implementation versus validation

| Capability | Main baseline | Contact branch / remaining boundary |
|---|---|---|
| Density-derived mass, COM, inertia | Implemented for the prototype's sampled matter and rigid spheres | Exact rotational consistency at representation transfers, including finite-cell spin, still needs an audit |
| Rolling and sliding | Initial no-slip launch; material contact friction; approximate rolling loss | Branch measures actual slip and replaces velocity reassignment with torque; no complete contact-load model |
| Material presets | Iron, aluminum, glass, ceramic, oak, rubber, ice, concrete | Preset names are not certified models; rigid materials do not thereby dent, creep, or split |
| Stiffness/strength response | Contact screening and approximate brittle constitutive channels | Resolution, strain-rate, and fracture-work calibration incomplete |
| Yield/hardness/anisotropy/temperature fields | Some used for screening or declared as metadata | Do not interpret declarations as working ductile plasticity, full anisotropic wood, or thermal mechanics |
| Gravity and slope | Shared frame/vector across ball experiment, support-plane material/debris handling and projections | Arbitrary geometry and robust finite support/contact need work |
| Original fracture handoff | Rigid collision followed by internal excitation | Branch disables that runtime pulse and adds actual sphere/material response |
| Two-way active material contact | Not implemented in main | Experimental sphere/point coupling in branch; not arbitrary-shape or material/material contact |
| Fragment creation | Connectivity -> mesh -> convex proxy -> Jolt, with overflow debris | Mass-accounting tests pass; full energy/angular-momentum correctness and realistic shard distribution are not established |
| Damage from floor/striker/repeated shards | Not general in the experiment | Future work; the demo principally activates the selected target in a ball/ball impact |
| Analytical scenario cache | Implemented; 960-scenario generator | Planner summaries do not execute adaptive scheduling or cached fracture playback |
| Material outcome capture/load/apply | Prototype library and tests | No automatic runtime reuse; state identity, frame applicability and time alignment incomplete |
| Physical LOD, sparse large worlds | Design only | Whole-object ball activation currently; no adaptive local patch hierarchy |
| Runtime material-file editing | General material JSON examples remain design | Local creator schema validates SI fields for intact spheres and catalog material IDs; custom constitutive material loading remains open |
| Door/hinge assemblies, LawScript, AI authoring | Design only on main | Local manual Codex proposal â†’ validated creator recipe works; automatic model connection, assemblies and LawScript remain open |
| Universe publishing, persistence, multiplayer | Design only on main | Local creator inventory/recipe/rigid-state persistence exists; world packages, history, publishing and multiplayer remain open |

Contact combination rules, damping-derived restitution, Hertz screening, point contacts, XPBD iterations, geometric correction and lightweight debris are model choices. They must be visible in tests and documentation, not labeled exact consequences of a handful of material constants.

## 4. Verification evidence

### Main lineage

[Material checkpoint CI run 33931822102](https://github.com/lrspeiser/banjo/actions/runs/33931822102) passed for `acd3aa3`: build, tests, analytical scenario generation, headless fracture/fragment handoff, and graphical capture. The later PR #1 head/merge and main build fixes must not be confused with that exact tested commit.

Main's CMake defines six CTest executables when runtime targets are enabled: `banjo_tests`, `banjo_material_tests`, `banjo_contact_tests`, `banjo_constitutive_tests`, `banjo_outcome_tests`, and `banjo_runtime_tests`. Executable count is not individual assertion count.

### Contact checkpoint

The pinned branch notes record seven passing local Linux CTest executables, including 12 runtime checks and seven conservative-contact checks, plus a passing headless experiment. A slide-to-roll test launched at 2 m/s measured 1.42857 m/s after settling. A frictionless test records a 6.53e-6 m/s surface-speed spin drift and a declared 1e-5 m/s tolerance rather than claiming exact zero numerical drift.

**Now verified:** [PR #2 CI run 33934550424](https://github.com/lrspeiser/banjo/actions/runs/33934550424), associated with `138260d`, completed successfully. Job `101219808357` passed compilation, core/material-law tests, scenario generation, headless handoff, graphical capture and artifact upload. This is a PR-triggered Linux workflow; do not treat it as independent macOS/Windows verification or proof of normal interactive input behavior on the unmerged branch.

The recorded default branch experiment had 1,285 nodes, 17,097 initial bonds, 17,076 broken bonds, 1,264 components, 64 Jolt fragments and 1,200 lightweight debris particles. Accounted target mass was 163.6089 kg. **This almost-complete breakup is a known model defect/over-fragmentation result, not validated glass behavior.** The large mass follows the 0.25 m radius solid sphere experiment, not a small household marble.

No new physics executable was built for this documentation-only audit. Historical measurements remain attributed to the exact checkpoint/report. Green tests and complete mass bookkeeping do not prove conservation across the whole nonlinear pipeline.

## 5. Current code map

| Area | Entry points |
|---|---|
| Build/targets | `CMakeLists.txt`, `CMakePresets.json`, `.github/workflows/ci.yml` |
| Authoring examples | `assets/materials/`, `assets/scenes/` (examples, not a complete live loader) |
| Material definitions/compilation | `src/material/Material.hpp`, `MaterialCatalog.cpp`, `MaterialCompiler.cpp` |
| Matter and geometric frames | `src/matter/Lattice.*`, `src/core/Math.hpp`, `Plane.hpp` |
| Contact screening | `src/physics/ContactMechanics.*`, `src/fracture/ActivationPolicy.*` |
| Rigid integration | `src/rigid/JoltWorld.*` |
| State machine | `src/sim/RollingBallExperiment.*` |
| Deformation/fracture | `src/fracture/ActiveMatter.hpp`, `BrittleBondSolver.*`, `ConnectedComponents.*` |
| Fragment transfer | `src/fracture/FragmentGeometry.*`, `FragmentMassProperties.*` |
| Predictions/outcome serialization | `src/prediction/`, `src/precompute/MaterialOutcome.*` |
| Viewer and tools | `src/viewer/main.cpp`, `src/viewer/workshop.cpp`, `src/app/creator_main.cpp`, `headless_main.cpp`, `precompute_main.cpp` |
| Creator contract, compilation and state | `src/creator/CreatorWorld.*`, `assets/creator/`, `tests/creator_world_tests.cpp` |
| Verification | `tests/`; inspect branch additions for conservative contact and rolling diagnostics |

## 6. Build and exercise the appropriate version

For main, use a separate working tree/build directory and keep local changes safe:

```sh
git fetch origin
git switch main
git pull --ff-only
cmake -S . -B build/main-test -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/main-test --parallel 4
ctest --test-dir build/main-test --output-on-failure
./build/main-test/banjo_lab
```

For contact development, switch to `feature/conservative-material-contact` and build into `build/contact-test`. Reconcile current main before relying on a standalone interactive build. Do not reset or force-push over other work. On a headless machine add `-DBANJO_BUILD_LAB=OFF` and run the `banjo_headless` executable. Linux graphical builds need the window/OpenGL development packages specified in CI; macOS/Windows setup and generator paths may differ.

Main viewer controls: `M` striker, `T` target, `S` support material; `[`/`]` slope; Up/Down striker speed; `G` gravity magnitude, `V` direction; `1`/`2`/`3` voxel detail; Space pause, `N` step, `R` reset; `B` bonds, `W` wireframe; right drag orbit, wheel zoom. The contact branch additionally exposes `L` initial-spin modes and measured motion readouts. Verify the branch's current control implementation rather than relying on an old screenshot.

```sh
./build/main-test/banjo_headless
./build/main-test/banjo_precompute build/main-test/ball-scenarios.csv
./build/main-test/banjo_lab --cache build/main-test/ball-scenarios.csv
```

The CSV contains analytical summaries, not precomputed fracture animations or an automatic real-time acceleration system.

## 7. Known issues and next handoff

Highest priority: reconcile/verify the contact branch; measure full-system momentum and energy with external-work accounting; remove artificial fracture energy from the authoritative path; calibrate over-fragmentation; and audit activation/handoff inertia, finite-cell spin, geometric correction, and damping.

Then widen to drop/floor activation, both objects and repeated shards, genuine material-specific laws, arbitrary surfaces and self-contact, deterministic parameter files, resolution/timestep tests, local physicalization, and measured performance. Automatic reuse of material outcomes is blocked on complete keys, physical applicability checks, and time-consistent integration. Language, assemblies, persistence and publishing follow the acceptance gates in the roadmap.

### Suggested coding-agent task

> Read `AGENTS.md`, `docs/project-master-plan.md`, `docs/development-status.md`, and `docs/roadmap.md`. Inspect current main and PR #2 rather than assuming historical branch heads. Reconcile the experimental contact implementation without losing main's raylib/MSVC fixes. Verify a normal interactive run as well as CI capture. Audit conservation through contact, fracture, and handoff; fix over-fragmentation through explicit constitutive/fracture-work modeling. Do not add synthetic impulses, precut chunks, forced rolling, or unvalidated cache playback. Keep the ball laboratory reproducible and update implementation status and verification evidence with each checkpoint.
