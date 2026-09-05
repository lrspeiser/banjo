# Physical property and capability coverage

**Energy and phase foundation (current):** All 44 regression suites pass. The [world checkpoint](world-foundation-checkpoint.md) now includes strict [SI language packages](world-physics-language.md), bounded thermal/reaction jobs, and ice/water enthalpy with latent heat. Repeated sparse-world tests separate stored volume from active cost and expose overload backlog. Glass/contact accuracy remains an open mechanical gate; smoke and full fluid flow are deferred. The [plan](world-runtime-plan.md) and all 40 scorecard requirements remain in force.

**Latest compiled-runtime checkpoint (experimental):** [Compiled runtime checkpoint](compiled-runtime-checkpoint.md) records the new `compiled-impact-v1` live backend: compiled mass/inertia and structural response factors, a 64-step local linear impact pulse on damaging contact, re-solves after failed bonds, seeded persistent variation, measured-loss-bounded fracture-work reclassification, and surviving components handed to rigid fragments without launch kicks. Smooth intact spheres use a coarse 19-sample fragment skin and boxes 27 samples. Native 3 s drop playback was verified live at 60 FPS; eight packages and the 128-object initial admission limit are covered, including the 96-object load fixture. This is not AVBD, full continuum validation, or a complete conservation/reaction ledger; oak and iron remain rigid-only (no grain, plasticity, or failure). All 36 regression suites passed; repeated performance measurements and the publication record are described in the linked checkpoint.

**Playback speed correction:** [Exact-scene playback](platform-playback-checkpoint.md) calculates reference trajectories once and replays at normal wall-clock speed, retaining four exact initial-package recordings within the process. Scratch-buffer reuse preserves the tested physical outputs; calculation still takes roughly 38 s for the tested 1.1 s drop. Live adaptive real-time physics remains unfinished.

**Offset and fracture-height drops:** [New comparative evidence](height-drop-checkpoint.md) retains centred controls, adds physically deflecting off-centre drops, and compares iron-on-glass with iron-on-oak from four heights. Glass progresses from intact to separated pieces in the reference model. Finite solid-ground contact, visible bond counts and zoom are implemented; real-glass calibration and near-real-time reference performance remain open.

**Object-on-object drop tests:** [Four new drop examples](drop-test-checkpoint.md) add spheres/cubes falling onto freely resting targets on finite concrete ground, each comparing glass/oak/iron. All 12 combinations pass motion/contact checks; all 21 example packages pass. This is rigid collision coverage, not fracture. Source `de8129f`; published with this checkpoint.

**Platform-first direction (current owner priority):** Banjo is a Unity-like, LLM-accessible physics authoring and publishing platform for game makers. Inventory, crafting and progression are the first customer application, not the engine roadmap. Preserve all physics and publishing requirements; require measured near-real-time execution alongside correctness. The bowl is the first extensible conformance and performance laboratory, not the product boundary. [Platform SDK checkpoint](platform-sdk-checkpoint.md) implements an inventory-independent runtime, 17 executable scene packages and headless/visual clients. Automatic physical LOD and full publishing remain open. Earlier customer-first priority notes below are historical and superseded.

**Rolling/fracture correction:** [Strength gate and computed replay](rolling-strength-checkpoint.md), source `aa3491f`, local only. Glass/oak/iron isolated rolling is damage-free over 0.3 s; strong glass impact still fractures progressively. The native eight-ball 1.25 s replay moves visibly and ends with four broken links but eight connected groups; contact attribution remains open. Calculate prepares a fresh trajectory, then Replay shows normal-speed motion. Coarse contact geometry, continuum calibration and the full platform remain unfinished. Earlier energy-only bowl notes below are historical.

**Fracture now runs in the bowl:** [Experimental bonded-cell checkpoint](bonded-bowl-checkpoint.md) connects crafted balls to local energy-driven failure, surviving internal networks and continued curved-support/multiple-body contact. Glass fractures during release; oak and iron retain elastic connections. Source `f55f996`, UI `a939df0`, local only. This is a slow, coarse 19-cell model with uncalibrated strength and contact geometry, not the completed realistic-fracture gate.

**Interactive fracture microscope:** [Visual checkpoint](fracture-microscope-checkpoint.md) connects accepted solver trajectories to the native bowl app, with glass/oak/iron comparison, four impact speeds, playback, scrubbing and event stepping. Source `413852a`, local only. Both affected suites pass in promoted and legacy builds. This is the eight-region connector reference; whole-ball fracture and live bowl fragment contact remain open.

**Local fracture cascades:** [Surviving-network propagation](rupture-cascade-checkpoint.md) now advances contact, local rupture and subsequent internal failure on one clock, with recursive time refinement and whole-interval rollback. An eight-region impact leaves a six-region core intact while a detached two-region piece breaks later. Four affected suites and the new legacy test pass. Local `334454d`; whole-ball/bowl integration remains open.


**Fracture component:** [Energy-accounted rupture](energy-rupture-checkpoint.md) now combines accepted elastic/contact motion with a transactional tensile break, explicit Gc-area work and a separate event-overshoot budget. Low/high glass impact cases and matched glass/oak/iron reference experiments pass; five affected suites pass, plus the new legacy test. Local `6b44c2f`. Whole-ball geometry, event convergence and live bowl fragment handoff remain unfinished; fracture is still disabled in the bowl.


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


**Starter support/release coverage:** [Willow Clearing](starter-checkpoint.md) tests glass/oak/iron fixed attachments, release without a launch impulse, gravity and crafted-sphere raw-volume collection. Its stamina costs, tool multipliers and whole-branch cut completion are game policies, not constitutive/energy validation. No calibrated wood grain, crack growth, tool efficiency or manufacturing law is added. Full physics gates remain open.

**Inventory assessment at `fca0cb3`:** [Three-material requirements tests and real provider trials](requirements-checkpoint.md) verify homogeneous volume/density cost, inventory versus uncollected stock, selected recovery and no implicit transmutation/reclamation. All 15 suites pass (11.73 s); no physical law or conservation tolerance changes. Fabrication energy, functional success and normal new-control input remain unverified/unsupported as detailed there.

The [selected-revision checkpoint](revision-checkpoint.md) at `14bb0b7` adds material-reuse/return and before/after mechanical records through actual created objects. Glass/oak/iron lifecycle and real provider cases pass; all 15 suites pass (11.71 s). These are explicit authoring discontinuities, not manufacturing, conservation or fracture-work validation. Energy accounting remains unsupported and the normal new-control check remains pending.

The [oriented box creator checkpoint](shape-checkpoint.md) adds full-dimension/orientation consumers, analytical homogeneous volume/inertia and actual solver tensors. Glass/oak/iron comparisons cover equal-volume sphere-versus-box ramp behavior, box free fall, asymmetric spin, finite shape collisions and persistence. Box top-support samples do not measure edge/side manifolds or support work; no constitutive/calibration/fracture claim changes. All 15 Windows suites pass; normal new-control verification remains pending.

The [automatic assistant at `ae82167`](assistant-checkpoint.md) adds structured request/reply validation and a Windows provider process boundary. Glass/oak/iron LLM recipes feed the existing compiler and produce measured rolling; an unsupported door produces no recipe. All 15 Windows CTest executables pass. No constitutive/contact law or physics tolerance changed; semantic LLM coverage remains a small sample.

The [creator checkpoint at `9cd9197`](creator-checkpoint.md) adds a shared runtime consumer for bounded SI recipes, exact solid-sphere volume, density-derived mass/inertia and inventory allocation. Headless and workshop objects share `CreatorWorld`. Glass/oak/iron creation, density-independent free fall, friction-generated rolling with measured slip, finite pair collisions and persistence checks pass; all 14 Windows CTest executables pass. This explicitly selected intact-rigid mode does not add calibrated material laws, deformation or fracture. The detailed-path defects below remain open.

The [adaptive reference at `8cf33bc`](adaptive-checkpoint.md) adds numerical accuracy controls consumed by `CompliantAdvance` and stricter equation-residual budgets consumed by `CompliantStep`. Every accepted trial retains the explicit normal spring/dashpot law; a swept finite-sphere guard rejects buried contact. Thirteen CTest executables pass; glass/oak/iron remain in the 12-run full-size comparison. These are numerical/geometry capabilities, not additional material laws or calibration. Default runtime consumers remain unchanged.

The [full-state trajectory checkpoint at `e5b883e`](trajectory-checkpoint.md) adds round-trip node position/velocity/spin/mass export and independently verified COM/kinetic summaries. Thirty glass/oak/iron runs at five rates provide 24 matched-time comparisons. Bulk motion is much more consistent than internal node velocity, so no new constitutive calibration or full-trajectory accuracy claim follows. The material/contact law and default runtime consumers are unchanged.

The [explicit normal-compliance reference at `58546cb`](compliance-checkpoint.md) consumes stiffness (N/m), compression-only damping (kg/s) and a declared compression validity bound. Seven analytical/ledger/rollback test groups and 27 glass/oak/iron probes account for stored contact energy, damping work and finite reactions. This is an uncalibrated per-contact law selected through `CompliantStep`/the probe; it adds no default-runtime consumer, internal viscoelastic memory, grain or plasticity. High-frequency lattice trajectory and spatial-resolution convergence remain open; the rigid e=0.3 failure is retained.

The [contact-root reference at `b31a8a5`](event-root-checkpoint.md) fixes interval-boundary/departure handling and records full-resolution glass/oak/iron impacts using short intervals. Prescribed frictionless restitution/work and rollback have analytical checks; sampled dissipative cases still reject after repeated impacts, and timestep accuracy is not established. This adds no grain, plasticity, fracture calibration or default runtime consumer. The [mechanics scorecard](mechanics-scorecard.md) records those limits and next steps.

The [coupled support reference at `1deb025`](coupled-support-checkpoint.md) adds full-glass floor convergence and external-reaction/work checks, including rotated support, separation and finite-footprint rejection. The timestep sweep still fails to establish converged rebound; its large impact-phase loss is numerical, not calibrated restitution. Default-runtime consumers in the matrix below are unchanged.

The [conservative reference at `1d29545`](conservative-reference-checkpoint.md) adds validated small elastic/contact bookkeeping cases. [Global Newton/GMRES at `dc7bcfb`](elastic-newton-checkpoint.md) adds analytical timestep refinement, local/global numerical agreement and accepted full-glass elastic probes at 2 ms and 1/240 s, with measured conservation drift and non-real-time cost. It is separate from the default lab and does not add calibrated friction, restitution, fracture, or new material families. The matrix below describes the default runtime at `d56611c` unless stated otherwise.

Local source checkpoint: `d56611c`, September 4, 2026. This matrix describes consumers and current evidence, not certified material data. Iron, aluminum, glass, ceramic, oak, rubber, ice and concrete presets are examples with incomplete provenance and calibration. Read the [stage checkpoint](material-stage-checkpoint.md) for current conservation defects and the [transfer checkpoint](transfer-accounting-checkpoint.md) for finite-cell accounting.

| Property / capability | Current consumer and evidence | Remaining boundary |
|---|---|---|
| Density, size and sampled volume | Lattice mass, target inertia, fragment properties; mass and spinning-transfer tests | Geometry/resolution convergence; arbitrary/composite material distributions |
| Initial velocity and spin | Rigid initialization, finite-cell activation and fragment momentum; three-resolution rotated-sphere transfer tests | Full active-stage conservation; subcell torque/torsion; general debris angular dynamics |
| Young modulus / Poisson ratio | Contact effective modulus, bond compliance and strain thresholds; compiler/contact/constitutive tests | Macroscopic elastic calibration, horizon weighting and resolution convergence |
| Tensile/compressive/shear strength | Local strain damage channels sampled at accepted substep endpoints; analytical regression excludes predictor-only damage; constitutive tests | Resolved strain-peak convergence, validated coupon failure envelopes, rate dependence, crack-path convergence |
| Fracture energy | Activation screening and compiled material parameter | Energy-consistent crack work is absent; removed spring energy is only a diagnostic |
| Static/dynamic friction | Contact compilation, sphere/material/support and rigid contact paths; sliding/rolling/pair-contact tests | Consistent full contact-load model and general contact geometry |
| Restitution / contact damping | Combined-contact response and damping/restitution conversion tests | Empirical material/speed dependence; complete scene dissipation budget |
| Rolling resistance | Runtime resisting torque; regression verifies torque instead of forced no-slip | Measured support loads, arbitrary geometry and full work accounting |
| Internal damping | Central radial pair damping; measured loss and vacuum-drag separation tests | Calibrated frequency/rate behavior; viscoelastic memory |
| Yield strength / hardness | Contact screening and classification | No working ductile plasticity, indentation, permanent strain or plastic-work model |
| Anisotropy / reference temperature | Declared material fields | No complete directional elasticity/failure, thermal state/evolution or thermal coupling |
| Seed / strength variation | Deterministic bond strength variation | Physical defect-distribution calibration and statistical convergence |
| Gravity / slope / support enable | Rigid/material/debris paths; free-flight gravity reference and runtime tests | Full support impulse/torque/work ledger, finite/curved/moving supports and general activation |
| Solid spheres / generated fragments | Procedural sphere lattice, smooth rigid sphere and convex fragment proxies | Hollow spheres, cylinders, boxes, ellipsoids, irregular/composite authored shapes and proxy-error validation |
| Object interfaces / laws | Strict SI creator schema and catalog capability validation for intact rigid spheres; manual AI proposals use the same compiler | Additional shapes, custom unit conversion/material laws, assemblies, hinges, fastener failure and automatic model adapter |

For every new property, add an explicit runtime consumer, units, a reference test, a stated validity domain and convergence evidence. A field, preset name, green unit test or visually plausible run alone is insufficient. Plasticity, viscoelasticity, anisotropy and thermal mechanics require distinct implemented laws and energy accounting before their names can describe supported behavior.
