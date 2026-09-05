# Banjo mechanics scorecard

Energy requirement: [making, breaking and recovering material](energy-system.md) now explicitly requires identified energy sources, process/power limits and combined material/energy accounting. This is design; the creator still has no energy-cost model. The selected-revision path now passes all 15 suites and real glass/oak/iron provider trials; workshop build/capture pass, while normal control verification remains pending. The earlier API review below remains a historical snapshot.

API review, September 4, 2026 Pacific: [12 functional API areas and acceptance checks](api-platform-review.md) expand the detail behind P05–P10 without replacing any retained mechanic. Uncommitted rebuild/reclaim and world-format-3 history pass the focused creator tests; assistant/UI integration is incomplete. The next application milestone is reliable API-driven build/test/revise with measurable task criteria. This review adds no new physics or full-suite validation.

Living scorecard for the general-object platform. Latest tested code is `14bb0b760f43ee500576a8624a5205a78365e4f4` on local `codex/physics-foundation`; GitHub main remains separate. The [revision checkpoint](revision-checkpoint.md) records material-accounted rebuild/reclaim, format-3 history, 15 passing suites and five real provider cases. The earlier [shape checkpoint](shape-checkpoint.md) records 15 passing Windows suites, actual oriented-box tensors/collisions, equal-volume glass/oak/iron comparisons, saved-world migration and real block proposals. New controls have capture evidence but await normal interactive verification. The [previous assistant checkpoint](assistant-checkpoint.md) records sphere UI creation/cancellation/retry. The [creator checkpoint](creator-checkpoint.md) supplies the shared inventory/compiler/persistence foundation. The earlier [adaptive checkpoint](adaptive-checkpoint.md) records bounded local error control, a grazing-contact guard and 12 full-size glass/oak/iron runs with 15 matched comparisons. Local indicators do not certify global convergence, and the reference remains far from real time. The default viewer and fracture defects remain current. Update this document at every physics checkpoint, including failed and unsupported cases.

Status meanings: **Measured** = verified only within the stated reference bounds; **Defect** = evidence contradicts the required behavior; **Prototype** = implementation exists but the required validation is incomplete; **Planned** = required implementation is absent. A measured component does not make the full platform complete.

Application priority: the [creator loop](creator-loop.md) now supports selected-object rebuild/reclaim and saved operation history through the shared compiler. Real glass/oak/iron requests and unsupported door/energy clarifications pass. Normal control verification remains pending; next standardize API retries/durability, establish energy reference states and add measurable functional tests.

## Comparative-material rule

Always run material-dependent experiments with **glass and oak**, retaining **iron** as the third reference case and expanding the set as substances are added. Keep geometry, initial motion, gravity/support, resolution, timestep and solver settings identical for comparisons unless a declared experiment intentionally holds mass or inertia fixed. Report every material separately. Keep material-neutral analytical oracles alongside the comparisons. A preset name, color or a successful build is not material realism.

| Substance | What current code represents | Current limitation / next evidence |
|---|---|---|
| Glass | Catalog density/modulus; brittle prototype; conservative elastic reference | Three-material contact ledgers pass, but sampled timestep accuracy, calibration and fracture work remain unvalidated |
| Oak (wood) | Catalog density/modulus; rigid lab material; explicit elastic approximation in comparative work | Grain, directional strength and moisture effects absent; implement anisotropic coupons before claiming wood mechanics |
| Iron | Catalog density/modulus; rigid lab material; explicit elastic approximation in comparative work | Yield/plastic flow/hardening absent; retain as third numerical case, then add ductile coupons |
| Aluminum, ceramic, rubber, ice, concrete | Existing catalog/contact declarations with differing coverage | Add each to shared regression scenarios; rubber memory, concrete crushing and other named behavior need their own laws/tests |

An elastic approximation uses the same declared bond law for each material's density/stiffness. It must not silently enable brittle fracture for oak or iron. The current central-bond reference does not independently calibrate Poisson response, anisotropy, plasticity or damping.

## Mechanics and retained invariants

| ID / mechanic | Status and evidence | Next required step |
|---|---|---|
| M01 Matter-derived mass, volume, COM | Measured sampled/transfer tests and exact homogeneous sphere/box compiler; glass/oak/iron inventory ledgers | Hollow and heterogeneous objects with material-derived occupied matter and COM |
| M02 Full inertia and finite-cell spin | Measured finite-cell transfer spin plus authored unequal boxes with full local/world tensors, including solver off-diagonal inertia | Heterogeneous/concave mass tensors and broader torque-free convergence; current box H drift ~0.39% over 0.5 s |
| M03 Linear momentum and finite reactions | Measured: finite-pair/transfer/reference reactions plus created glass–oak and glass–iron collisions; full default path incomplete | Close complete activation/contact/fracture/handoff ledger for every material |
| M04 Angular momentum and torque arms | Default active-path defect remains; finite shape collisions and box free-spin tested with explicit drift bound; reference/transfer tests retained | Eliminate default-path drift; refine asymmetric rotation and retain orbital/intrinsic angular momentum across transfers |
| M05 Energy, external work and named losses | Defect in default corrections; reference contact/storage/damping audits pass. Creator energy source/process accounting is now explicitly required, still design | Close activation/handoff ledgers; define inventory reference states and combined energy/material transactions; no unexplained credits or loss refunds |
| M06 Gravity, free flight and acceleration | Measured analytical free fall, loaded equilibrium and glass/oak/iron created-object free fall at matched geometry | Retain density-independent gravity and arbitrary directions; establish lattice settling convergence |
| M07 Reversible elasticity | Measured spring/network references and glass/oak/iron full-lattice ledgers; uncalibrated response | Paired tension/compression/shear/bending coupons, load curves, horizon/resolution convergence |
| M08 Contact ownership and nonpenetration | Prototype: explicit compliant normal contacts, transactional interval publication and excess-compression/buried-sweep rejection; default path remains | Integrate ownership through activation and shared experiment declarations; compile area-aware interface laws |
| M09 Impact timing and rapid collisions | Measured bounded finite-sphere grazing regression and adaptive contact trials; 12 full-size material runs complete | Retain rejection/rollback bounds and fast-contact tests; generalize swept geometry and reduce measured cost |
| M10 Restitution and rebound | Defect in rigid e=0.3 sampled event law; separate compliant law passes analytical bounce and three-material work checks | Establish sampled rebound convergence and explicit law selection; retain rigid-law failure and calibrate interface/speed dependence |
| M11 Static/dynamic friction and slip | Measured limited pair tests and glass/oak/iron creator ramp motion; no friction in new conservative reference | Integrate consistent loads, torque and work in detailed reference; retain comparative creator cases |
| M12 Slide-to-roll, backspin and overspin | Measured limited spin tests; three created materials roll from rest with slip <0.002 m/s at 1 s | Extend creator experiments to backspin/overspin and ideal references; close full rolling energy ledger |
| M13 Rolling resistance and settling | Prototype resisting torque and regression | Calibrate losses using actual support loads; verify settling and arbitrary shapes |
| M14 Internal damping versus external drag | Measured limited internal damping/drag separation; compliant contact damping has its own nonnegative work ledger | Calibrate internal rate/frequency response and contact losses separately; damping is not viscoelastic memory |
| M15 Strength, damage and crack initiation | Prototype: accepted-state strain sampling; no predictor-only damage | Paired material-specific failure coupons and resolution/timestep/defect sweeps |
| M16 Fracture energy and emergent topology | Defect: over-fragmentation; removed spring energy is not a fracture-work law | Energy-consistent crack/interface work and area convergence; no numerical-bond-count costs, duplicate impact fees or forced shard count |
| M17 Plasticity, yield and hardening | Planned; iron/aluminum parameters are not a plastic solver | Ductile return mapping, permanent strain and plastic-work coupons |
| M18 Viscoelasticity and rate dependence | Planned; damping is not rubber memory | Constitutive state/history and relaxation/creep/frequency tests |
| M19 Anisotropy, grain and layered response | Planned; oak anisotropy field lacks directional mechanics | Grain-oriented elasticity/failure, rotated coupons, fibers and laminations |
| M20 Flaws, porosity and statistical variation | Prototype seeded strength variation | Reproducible defect distributions, density/porosity coupling and statistical convergence |
| M21 Fragments, landing and repeated damage | Prototype rigid fragments/debris and transfer accounting | Preserve material history and lineage; repeated impact/refracture and explicit debris fidelity bounds |
| M22 Finite, inclined, curved and moving supports | Measured limited static/inclined plane cases; workshop uses finite Jolt ramp and observed edge departure | Quantify edge/corner contact and support work; add moving/curved supports |
| M23 Both-body activation, multiple active objects and self-contact | Planned beyond limited one-active-target coupling | Shared ownership and synchronized state; multiple deformable bodies and self-contact |
| M24 Shape and mass-distribution effects | Measured bounded equal-volume sphere/box ramp comparison for glass/oak/iron; true oriented box contact/inertia, free fall and off-center collisions | Cylinders/hollow/ellipsoidal/composite shapes; sliding/tipping/edge regimes and wider convergence |
| M25 Interfaces, adhesion, coatings and fasteners | Prototype explicit normal stiffness/damping interface; adhesion, coatings and fasteners planned | Compile area/resolution-aware interface laws; add welds/glue/coatings/fasteners with load transfer and work budgets |
| M26 Assemblies, hinges and constrained motion | Planned | Door/hinge example with material-derived inertia, anchor failure and post-failure motion |
| M27 Thermal, moisture and phase state | Planned; declarations are not thermal evolution | Unit-bearing state, heat/expansion/transport and explicit mechanical coupling tests |
| M28 Granular, fluid and further material families | Planned | Select and validate solver families; capability limits and consistent coupling to solids |
| M29 Frame, timestep, resolution and orientation invariance | Prototype: analytical adaptive refinement and 15 full-node comparisons; global trajectory/spatial convergence not established | Use explicit accuracy limits in the workbench; retain refinement evidence and add area-consistent resolution/orientation sweeps |
| M30 Determinism, reproducibility and experiment diagnostics | Prototype: full-node reference exports plus shared creator JSON fixtures, stable IDs and accepted-recipe/state persistence | Extend portable experiment/metric export to more geometries and topology; no bit-exact Jolt reload or cross-platform claim |

## Platform capabilities that must preserve those mechanics

| ID / capability | Status | Next required step |
|---|---|---|
| P01 Adaptive/local matter and physical LOD | Planned beyond whole-ball activation | Sparse local patches, boundary coupling, refinement/re-coarsening and damage preservation |
| P02 Sleeping, resource budgets and performance | Prototype bounded trials; latest concurrent full-size runs take 36.1947–392.419 solver seconds per 5 ms impact | Keep slow reference solves off the input/render loop; profile and optimize without changing laws or concealing internal modes |
| P03 Cache identity and reuse | Prototype serialization and scenario summaries | Full state/material/geometry/solver keys, invalidation and time-aligned validated reuse |
| P04 Speculative precomputation | Planned | Likelihood/error bounds, cancellation and measured net benefit with live fallback |
| P05 Units, extensible laws and capability checks | Prototype strict SI sphere/box schema and material-derived tensors. Energy stores/processes remain design | Versioned energy/work/power and tool capability declarations alongside material fields, geometry and laws; preserve unsupported behavior |
| P06 Human/AI creator APIs | Prototype create/rebuild/reclaim with real glass/oak/iron recovery requests and door/energy clarifications; all 15 suites pass | Normal revision-control verification; versioned commands/errors/receipts, consistent retry/durability semantics and bounded functional tests |
| P07 Persistence and material history | Prototype format-3 recipes/state/revisions, persistent receipts and removed-object history; known-v1/2 baseline migration and stale/replay/ledger checks pass | Crash-durable acknowledgement; energy-store/stock reference states and history; reusable packages and damage/assembly lineage |
| P08 Publishing, distribution and remixing | Planned | World/object manifests, physics ABI, dependencies, validation, preview, permissions and migration |
| P09 Multiplayer authority and compatibility | Undecided | Authority/snapshot/event model, stable IDs, version agreement and measured bandwidth/determinism |
| P10 Usable shared laboratory and visualization | Previous sphere UI verified; new revision controls build and capture successfully, but normal inspection still fails in the native helper | Verify selected edit/next/rebuild/reclaim and keyboard flow normally; preserve explicit energy limitation; then functional-test feedback |

## Current order of work

1. Finish normal revision-control verification while standardizing API command/error/receipt/retry/durability semantics. Establish inventory energy reference states and bounded functional tests. Preserve shared glass/oak/iron fixtures, one clock/contact owner and visible capability/budget limits.
2. Integrate work-accounted friction and synchronized activation/handoff; test measured sliding, slide-to-roll and spin while preserving contact storage, dissipation and reaction ledgers.
3. Extend the sphere/box path to hollow spheres and cylinders with real inertia/contact geometry. Validate area-aware interfaces and material-specific elastic/fracture/plastic/anisotropic coupons; retain the separate rigid e=0.3 failure and unresolved convergence evidence.
4. Continue local adaptive matter, assemblies, creator APIs and publishing in the full roadmap. The platform goal is not complete when balls work.

Evidence: [shape checkpoint](shape-checkpoint.md), [automatic assistant checkpoint](assistant-checkpoint.md), [creator workshop checkpoint](creator-checkpoint.md), [adaptive/12-run checkpoint](adaptive-checkpoint.md), [full-state/five-rate checkpoint](trajectory-checkpoint.md), [explicit compliance/27-case checkpoint](compliance-checkpoint.md), [contact-root/full-resolution checkpoint](event-root-checkpoint.md), [event/material comparison](event-material-checkpoint.md), [support/timestep checkpoint](coupled-support-checkpoint.md), [elastic reference](elastic-newton-checkpoint.md), [default-stage defects](material-stage-checkpoint.md), [transfer accounting](transfer-accounting-checkpoint.md), [property consumers](physics-coverage.md), [ordered roadmap](roadmap.md). The table records the scope of that evidence, including missing evidence, rather than inferring completion from passing suites.
