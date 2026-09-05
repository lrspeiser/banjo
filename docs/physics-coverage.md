# Physical property and capability coverage

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
