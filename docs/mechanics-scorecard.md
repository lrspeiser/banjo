# Banjo mechanics scorecard

Living scorecard for the general-object platform. Latest tested code is `8cf33bccf3c21eea69efaea192efa10e1be43198` on local `codex/physics-foundation`; GitHub main remains separate. The [adaptive checkpoint](adaptive-checkpoint.md) records 13 passing CTest executables, bounded local error control, a grazing-contact guard and 12 full-size glass/oak/iron runs with 15 matched comparisons. Local indicators do not certify global convergence, and the reference remains far from real time. The default viewer and fracture defects remain current. Update this document at every physics checkpoint, including failed and unsupported cases.

Status meanings: **Measured** = verified only within the stated reference bounds; **Defect** = evidence contradicts the required behavior; **Prototype** = implementation exists but the required validation is incomplete; **Planned** = required implementation is absent. A measured component does not make the full platform complete.

Application priority: the [first creator loop](creator-loop.md) is **planned**—collect materials, ask an LLM to make something from that inventory, validate and create a physical object, then test and revise it. Carry this small application slice through foundation work. The laboratory must exercise the same object/compiler path rather than becoming a separate product.

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
| M01 Matter-derived mass, volume, COM | Measured: sampled spheres, activation and fragment mass tests | Extend paired-material/resolution checks to hollow, non-spherical and heterogeneous objects |
| M02 Full inertia and finite-cell spin | Measured: spinning transfer tests include subcell inertia/spin | Extend to general shapes, anisotropic cells and debris dynamics |
| M03 Linear momentum and finite reactions | Measured: finite-pair analytical contact and transfer/reference reactions; full default path incomplete | Close the complete activation/contact/fracture/handoff ledger for every material |
| M04 Angular momentum and torque arms | Defect in default active path; bounded reference and transfer tests | Eliminate default-path drift; retain orbital and intrinsic angular momentum across every transfer |
| M05 Energy, external work and named losses | Defect in default corrections; reference raw and whole-interval contact/storage/damping work audits pass with residual-budget allocation | Integrate one audited clock/contact owner; preserve named physical losses and numerical residuals through activation/handoff |
| M06 Gravity, free flight and acceleration | Measured analytical free fall and compliant loaded equilibrium; glass/oak/iron gravity-loaded ledgers pass | Retain density-independent gravity, arbitrary directions and transfer accounting; establish lattice settling convergence |
| M07 Reversible elasticity | Measured spring/network references and glass/oak/iron full-lattice ledgers; uncalibrated response | Paired tension/compression/shear/bending coupons, load curves, horizon/resolution convergence |
| M08 Contact ownership and nonpenetration | Prototype: explicit compliant normal contacts, transactional interval publication and excess-compression/buried-sweep rejection; default path remains | Integrate ownership through activation and shared experiment declarations; compile area-aware interface laws |
| M09 Impact timing and rapid collisions | Measured bounded finite-sphere grazing regression and adaptive contact trials; 12 full-size material runs complete | Retain rejection/rollback bounds and fast-contact tests; generalize swept geometry and reduce measured cost |
| M10 Restitution and rebound | Defect in rigid e=0.3 sampled event law; separate compliant law passes analytical bounce and three-material work checks | Establish sampled rebound convergence and explicit law selection; retain rigid-law failure and calibrate interface/speed dependence |
| M11 Static/dynamic friction and slip | Measured limited pair/rolling tests; not in new conservative reference | Integrate friction with consistent loads, torque and work; retain glass/oak/iron comparisons |
| M12 Slide-to-roll, backspin and overspin | Measured limited rolling tests; default full energy ledger incomplete | Shared experiments with measured contact-point slip and analytical limits; no forced no-slip assignment |
| M13 Rolling resistance and settling | Prototype resisting torque and regression | Calibrate losses using actual support loads; verify settling and arbitrary shapes |
| M14 Internal damping versus external drag | Measured limited internal damping/drag separation; compliant contact damping has its own nonnegative work ledger | Calibrate internal rate/frequency response and contact losses separately; damping is not viscoelastic memory |
| M15 Strength, damage and crack initiation | Prototype: accepted-state strain sampling; no predictor-only damage | Paired material-specific failure coupons and resolution/timestep/defect sweeps |
| M16 Fracture energy and emergent topology | Defect: over-fragmentation; removed spring energy is not a fracture-work law | Energy-consistent crack work, crack-area accounting and convergence; no forced shard count |
| M17 Plasticity, yield and hardening | Planned; iron/aluminum parameters are not a plastic solver | Ductile return mapping, permanent strain and plastic-work coupons |
| M18 Viscoelasticity and rate dependence | Planned; damping is not rubber memory | Constitutive state/history and relaxation/creep/frequency tests |
| M19 Anisotropy, grain and layered response | Planned; oak anisotropy field lacks directional mechanics | Grain-oriented elasticity/failure, rotated coupons, fibers and laminations |
| M20 Flaws, porosity and statistical variation | Prototype seeded strength variation | Reproducible defect distributions, density/porosity coupling and statistical convergence |
| M21 Fragments, landing and repeated damage | Prototype rigid fragments/debris and transfer accounting | Preserve material history and lineage; repeated impact/refracture and explicit debris fidelity bounds |
| M22 Finite, inclined, curved and moving supports | Measured limited static/inclined plane cases; footprint crossing rejects | Real finite edges/thickness, moving/curved supports and their external work |
| M23 Both-body activation, multiple active objects and self-contact | Planned beyond limited one-active-target coupling | Shared ownership and synchronized state; multiple deformable bodies and self-contact |
| M24 Shape and mass-distribution effects | Prototype solid spheres/generated convex fragments | Hollow spheres, disks/cylinders, boxes, ellipsoids and irregular/composite geometry with actual inertia/contact |
| M25 Interfaces, adhesion, coatings and fasteners | Prototype explicit normal stiffness/damping interface; adhesion, coatings and fasteners planned | Compile area/resolution-aware interface laws; add welds/glue/coatings/fasteners with load transfer and work budgets |
| M26 Assemblies, hinges and constrained motion | Planned | Door/hinge example with material-derived inertia, anchor failure and post-failure motion |
| M27 Thermal, moisture and phase state | Planned; declarations are not thermal evolution | Unit-bearing state, heat/expansion/transport and explicit mechanical coupling tests |
| M28 Granular, fluid and further material families | Planned | Select and validate solver families; capability limits and consistent coupling to solids |
| M29 Frame, timestep, resolution and orientation invariance | Prototype: analytical adaptive refinement and 15 full-node comparisons; global trajectory/spatial convergence not established | Use explicit accuracy limits in the workbench; retain refinement evidence and add area-consistent resolution/orientation sweeps |
| M30 Determinism, reproducibility and experiment diagnostics | Prototype: node exports, matched binary/physical-state checks, adaptive error/trial diagnostics and all three materials retained | Shared portable experiment declarations and viewer/headless export; preserve rejection records and state identity through topology changes |

## Platform capabilities that must preserve those mechanics

| ID / capability | Status | Next required step |
|---|---|---|
| P01 Adaptive/local matter and physical LOD | Planned beyond whole-ball activation | Sparse local patches, boundary coupling, refinement/re-coarsening and damage preservation |
| P02 Sleeping, resource budgets and performance | Prototype bounded trials; latest concurrent full-size runs take 36.1947–392.419 solver seconds per 5 ms impact | Keep slow reference solves off the input/render loop; profile and optimize without changing laws or concealing internal modes |
| P03 Cache identity and reuse | Prototype serialization and scenario summaries | Full state/material/geometry/solver keys, invalidation and time-aligned validated reuse |
| P04 Speculative precomputation | Planned | Likelihood/error bounds, cancellation and measured net benefit with live fallback |
| P05 Units, extensible laws and capability checks | Design plus partial compiler validation; inventory-aware object compilation planned | Validate units, supported geometry/laws and material quantities; derive cost/mass/inertia from the same matter; reject unsupported LLM requests |
| P06 Human/AI creator APIs | Planned: first collected-materials → LLM request → inspectable specification → physical object → test/revise loop | Implement the narrow creator slice with shared human/LLM commands, independent validation, no invented resources and one supported object before expanding APIs |
| P07 Persistence and material history | Prototype outcome files; collected-material inventory and creation transactions planned | Persist inventory lots/provenance, accepted specifications, transaction/object IDs; prevent duplicate debit/creation; later preserve damage, assemblies and lineage |
| P08 Publishing, distribution and remixing | Planned | World/object manifests, physics ABI, dependencies, validation, preview, permissions and migration |
| P09 Multiplayer authority and compatibility | Undecided | Authority/snapshot/event model, stable IDs, version agreement and measured bandwidth/determinism |
| P10 Usable shared laboratory and visualization | Measured prior Windows build/input/capture; creator loop and audited reference integration still planned | Expose inventory, request/specification preview and physical create/test/revise flow; share glass/oak/iron experiments and keep accepted-state/budget feedback usable |

## Current order of work

1. Build the first inventory-backed creator path: collect a supported material, ask an LLM to make a simple object, inspect/validate its specification and cost, create it atomically, then test/revise it. Share this compiler/object path with glass/oak/iron headless/viewer experiments and preserve one clock/contact owner. Keep capability, accuracy, cost and rejection limits visible.
2. Integrate work-accounted friction and synchronized activation/handoff; test measured sliding, slide-to-roll and spin while preserving contact storage, dissipation and reaction ledgers.
3. Add hollow spheres, cylinders and boxes with real inertia/contact geometry. Validate area-aware interfaces and material-specific elastic/fracture/plastic/anisotropic coupons; retain the separate rigid e=0.3 failure and unresolved convergence evidence.
4. Continue local adaptive matter, assemblies, creator APIs and publishing in the full roadmap. The platform goal is not complete when balls work.

Evidence: [adaptive/12-run checkpoint](adaptive-checkpoint.md), [full-state/five-rate checkpoint](trajectory-checkpoint.md), [explicit compliance/27-case checkpoint](compliance-checkpoint.md), [contact-root/full-resolution checkpoint](event-root-checkpoint.md), [event/material comparison](event-material-checkpoint.md), [support/timestep checkpoint](coupled-support-checkpoint.md), [elastic reference](elastic-newton-checkpoint.md), [default-stage defects](material-stage-checkpoint.md), [transfer accounting](transfer-accounting-checkpoint.md), [property consumers](physics-coverage.md), [ordered roadmap](roadmap.md). The table records the scope of that evidence, including missing evidence, rather than inferring completion from passing suites.
