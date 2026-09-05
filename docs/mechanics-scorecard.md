# Banjo mechanics scorecard

Living scorecard for the general-object platform. Latest tested code is `e5b883e6d5d47dc85a5e1ea42c671d94a83cee99` on local `codex/physics-foundation`; GitHub main remains separate. The [trajectory checkpoint](trajectory-checkpoint.md) records 30 glass/oak/iron impacts at five timesteps and 24 full-node comparisons at common physical times. Bulk rebound is much more consistent than internal motion; full trajectory accuracy remains open. The [explicit compliant law](compliance-checkpoint.md) and [rigid e=0.3 failure](event-root-checkpoint.md) remain distinct. Update this document at every physics checkpoint, including failed and unsupported cases.

Status meanings: **Measured** = verified only within the stated reference bounds; **Defect** = evidence contradicts the required behavior; **Prototype** = implementation exists but the required validation is incomplete; **Planned** = required implementation is absent. A measured component does not make the full platform complete.

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
| M05 Energy, external work and named losses | Defect: default corrections inject strain energy; explicit compliant reference accounts for stored contact energy and damping | Integrate the audited solver; retain separate physical contact/plastic/fracture work and numerical residuals |
| M06 Gravity, free flight and acceleration | Measured analytical free fall and compliant loaded equilibrium; glass/oak/iron gravity-loaded ledgers pass | Retain density-independent gravity, arbitrary directions and transfer accounting; establish lattice settling convergence |
| M07 Reversible elasticity | Measured spring/network references and glass/oak/iron full-lattice ledgers; uncalibrated response | Paired tension/compression/shear/bending coupons, load curves, horizon/resolution convergence |
| M08 Contact ownership and nonpenetration | Prototype: explicit compliant normal contacts share one elastic solve and reject excess compression; default correction path remains | Integrate ownership through activation; calibrate interface compliance and generalize geometry |
| M09 Impact timing and rapid collisions | Prototype: boundary/departure oracles pass; all three full lattices finish at 20 and 10 microseconds; large intervals remain unvalidated | Resolve dense contact cost and temporal error with bounded rollback; preserve all three materials |
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
| M29 Frame, timestep, resolution and orientation invariance | Defect: full-node velocity differences remain substantial at the finest sampled pair despite stable bulk rebound; five-rate refinement measured | Bound temporal error over node motion and elastic state; preserve analytical/frame tests and add area-consistent resolution/orientation sweeps |
| M30 Determinism, reproducibility and experiment diagnostics | Prototype: all-node export, executable/configuration checks, independent COM/kinetic verification and 24 common-time comparisons across 30 runs | Portable experiment declarations, rejection/error records and state identity through topology changes; no cross-platform determinism claim |

## Platform capabilities that must preserve those mechanics

| ID / capability | Status | Next required step |
|---|---|---|
| P01 Adaptive/local matter and physical LOD | Planned beyond whole-ball activation | Sparse local patches, boundary coupling, refinement/re-coarsening and damage preservation |
| P02 Sleeping, resource budgets and performance | Prototype limits; five-rate compliant probes take 2.40–33.49 solver seconds per 5 ms impact | Profile accuracy-controlled coupled solves and distributions; optimize without hiding internal modes or changing laws |
| P03 Cache identity and reuse | Prototype serialization and scenario summaries | Full state/material/geometry/solver keys, invalidation and time-aligned validated reuse |
| P04 Speculative precomputation | Planned | Likelihood/error bounds, cancellation and measured net benefit with live fallback |
| P05 Units, extensible laws and capability checks | Design plus partial compiler validation | Unit-aware schema/IR, explicit unsupported-law errors and trusted solver plugins |
| P06 Human/AI creator APIs | Planned | Inspectable declarations, bounded simulation/query/test APIs and sandboxed behavior |
| P07 Persistence and material history | Prototype outcome files | Versioned recipes, damage/plastic/thermal history, fragments and assembly lineage |
| P08 Publishing, distribution and remixing | Planned | World/object manifests, physics ABI, dependencies, validation, preview, permissions and migration |
| P09 Multiplayer authority and compatibility | Undecided | Authority/snapshot/event model, stable IDs, version agreement and measured bandwidth/determinism |
| P10 Usable shared laboratory and visualization | Measured Windows build/input/capture; experimental runtime | Wire the audited solver into shared headless/viewer experiments with readable per-material diagnostics |

## Current order of work

1. Implement bounded temporal error control for full node motion and elastic state, verified against the five-rate glass/oak/iron trajectories. Compile interface response against area before resolution claims; retain the separate rigid e=0.3 failure.
2. Integrate friction and synchronized activation/handoff into the shared lab without losing contact storage, dissipation or reaction ledgers.
3. Validate elastic/fracture coupons and substance-specific laws; expand shapes and repeatable material comparisons.
4. Continue the adaptive-object, assembly, authoring and publishing gates in the full roadmap. The platform goal is not complete when balls work.

Evidence: [full-state/five-rate checkpoint](trajectory-checkpoint.md), [explicit compliance/27-case checkpoint](compliance-checkpoint.md), [contact-root/full-resolution checkpoint](event-root-checkpoint.md), [event/material comparison](event-material-checkpoint.md), [support/timestep checkpoint](coupled-support-checkpoint.md), [elastic reference](elastic-newton-checkpoint.md), [default-stage defects](material-stage-checkpoint.md), [transfer accounting](transfer-accounting-checkpoint.md), [property consumers](physics-coverage.md), [ordered roadmap](roadmap.md). The table records the scope of that evidence, including missing evidence, rather than inferring completion from passing suites.
