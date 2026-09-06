# World runtime plan

Status: planning target, 2026-09-05. This plan starts the fundamental runtime work; it does not claim that the current material-network implementation is a completed mechanics fix or that any proposed thermal behavior is implemented until measured.

Banjo must support a Minecraft-scale world in which most matter is cold, rigid, and cheap while a small region can become hot, deformable, fractured, or chemically active. The authoritative state remains occupancy, material identity, geometry, orientation/tensor state, mechanical state, thermal state, and history. Rendering, cached outcomes, and learned surrogates never become the source of truth.

The first customer loop remains the ax, tree, door, and tomato bowl. The ax must load a local wood law and tool contact; the tree must yield, cut, or fracture from declared matter; the door must retain panel, boundary, and future hinge state; the tomato must use a soft-tissue law and local damage. A panel clamped at its boundary is a test coupon, not a door hinge, and a torn region is not a complete carved chip until geometry and mass transfer are resolved.

Energy is intrinsic to the world-physics language, not a rendering effect or a force label. The language is declarative, unit-bearing, versioned by a law ABI, and advanced by simulation clocks owned by the runtime; an LLM may author declarations but never ticks physics. Each state carries named stores for chemical, sensible, latent, elastic, kinetic, and gravitational-reference energy where applicable, plus explicit transfers between them and to external work. Force is a momentum/work interaction, never an energy store, so “falling force” is not a material property. Wood may release declared chemical energy into heat and retained products under its thermochemical law; stone falling converts gravitational-reference energy into kinetic, contact, and deformation work under explicit transfers.

## Current implementation boundary

The [additional physics checkpoint](additional-physics-checkpoint.md) implements opt-in bounded cold-neighbor activation with state/energy transfer accounting, conservative same-clock conduction and reported backlog. Deferred faces remain insulated approximations without a global error bound; cross-clock exchange, demotion and mechanics coupling remain open. Mechanical endpoint damage refinement and whole-tick rollback are experimental, not a continuum/contact accuracy solution. The foundation paragraph below records the earlier slice.

The `material-network-v2` / `banjo-network-2` runtime is an experimental comparator. It has occupied-cell boxes/ellipsoids, rigid convex wedges, Jolt distance springs, gravity, contact, directional axial cohesive damage, and a perfect-plastic demonstrator. It is useful for controlled regression and API work, but stiff-wave and cutting convergence are not established. It must not be the mandatory first stage before a continuum solver, and it does not establish calibrated glass, wood, iron, tissue, or global realtime behavior.

The [first implementation](world-foundation-checkpoint.md) adds `SparseThermalWorld`, `ThermalKernel`, `EnthalpyLaw` and the [strict SI world language](world-physics-language.md), while keeping mechanical outcomes unchanged. The slice is deliberately narrow: fixed-capacity/conductivity regions, finite fuel/oxygen lumped reaction, enthalpy with latent heat, bounded jobs, explicit lag, and no cross-region or cold-region flux, mechanics coupling, fluid flow, or automatic activation. One thermal region may span multiple storage chunks, but it is still a single insulated solve. It is a thermal foundation, not a full fire system or a mechanics certification. Mechanical temporal admission now exposes/rejects under-resolved spring dynamics; it does not fix the contact/continuum model.

## Authoritative state and law families

The owner accepts voxel or sphere/particle samples wrapped in a separate visual skin. Follow the [object skin contract](object-skin-contract.md): render surfaces derive from accepted matter and interfaces, remain attached during deformation, and expose new interiors on partial cuts and fragmentation. Rigid motion reuses a skin; topology changes update affected patches with bounded work. Appearance-only skins add no physical properties. Physical layers such as tomato peel require declared matter/laws. Compact inactive storage remains valid; this decision does not require an active rigid body per cell or replace the pending continuum/contact correction.

Every occupied chunk/cell or active particle carries stable identity, mass/volume, material ID, position and velocity, orientation, inertia/tensor state, temperature or enthalpy, phase/fuel/oxygen/products, damage/plastic history, provenance, and named energy stores `{chemical, sensible, latent, elastic, kinetic, gravitational_reference}`. Transfers are explicit and auditable: reaction, heat, phase change, contact/work, plasticity, fracture, gravity, and external boundaries may move energy between stores or across the system boundary. Water keeps one material identity while its phase state changes between ice and liquid; an ID swap may not create or destroy energy. Aggregate cold chunks additionally carry COM, full inertia, thermal totals, material bounds, contact envelope, and a conservative error budget.

Material dispatch selects a family-specific law from declared properties and units:

- brittle glass: tensile/shear damage and fracture work with a converged process scale;
- anisotropic wood: orthotropic elasticity, grain frame, direction-dependent failure and later plastic/crushing laws;
- metal: J2 or another explicitly selected elastoplastic law with yield, hardening, rate, and thermal coupling;
- soft tissue: finite-strain viscoelastic/plastic cells or particles with cohesive/debonding interfaces;
- thermochemical matter: enthalpy, phase/fuel/oxygen/product state, heat transport and reaction law; water identity persists across ice/liquid transitions, with latent energy represented explicitly. Wood chemical/fuel state is distinct from stone's gravitational-reference and mechanical energy.

Density, hardness, strength, and a display name do not choose outcomes. No law may make strength depend on cell count, geometry name, or solver LOD without an explicit resolution conversion and test.

## Sparse world and execution policy

Use sparse uniform chunks for occupancy and field storage, active islands for mechanics/thermal work, and field-specific clocks. Cold chunks remain rigid aggregates until a declared wake predicate fires: contact impulse/stress bound, damage proximity, thermal gradient, phase threshold, player inspection, or tool interaction. The wake record names the cause and estimated error.

Promotion and demotion are transactional. A promotion must transfer mass, COM, full angular momentum, kinetic energy, recoverable internal energy, thermal enthalpy, damage/plastic history, and boundary reactions. A demotion is permitted only after residual, contact, and gradient bounds pass; it stores the aggregate state and unresolved-error budget. Rigid and local solvers have one contact owner per pair. No second collision impulse, shadow predictor, fabricated fragment launch, or silent state reset is allowed.

Scheduling uses a soft deadline and an explicit backlog. The target is 60 FPS / 16.67 ms frame time, with a provisional 4 ms CPU physics scheduling budget and measured p95/p99 costs under declared loads. These are targets, not guarantees. If work exceeds budget, the runtime preserves the last accepted state, reports lag and active-set age, and refines or catches up according to policy; it never substitutes an unrelated cache or learned prediction. GPU layouts and persistent buffers are later optimizations measured against the CPU reference, not a changed material law.

The first scale test compares approximately 1 million and 16 million stored voxels while holding active-cell count fixed, then grows the active-cell count at fixed chunk size. Acceptance reports payload storage (allocator overhead separately), p50/p95/p99 physics time, backlog, and numerical residuals for both cases. Wake churn and full process-memory benchmarks join this matrix once automatic activation exists.

## Solver selection and contact

There is no mandatory rigid → axial-lattice → continuum chain. For each active island, benchmark the declared law and geometry against:

- CPIC/MLS-MPM for cutting, displacement discontinuities, large deformation, and two-way rigid coupling;
- VBD/AVBD or another implicit variational solver for stiff deformable contact and large mass ratios;
- the CPU axial network only as an experimental comparator where its convergence envelope is demonstrated.

The selected local solver must expose forces/reactions, work, damage, plastic work, thermal coupling, and error indicators. The rigid solver remains the authoritative owner of rigid-rigid contact and must exchange equal-and-opposite impulses with the local solver. Cutting and fracture require spatial and temporal convergence of force, newly created area, dissipated work, topology envelope, and surrounding momentum/energy; a visually plausible crack is insufficient.

## Thermal foundation and progression

Phase 1 implements exact two-lump conduction for an insulated pair. With harmonic conductivity \(k_h\), shared face area \(A\), separation \(d\), and heat capacities \(C_a,C_b\), define \(G=k_h A/d\):

```text
Q_to_a = (T_b - T_a) / (1/C_a + 1/C_b)
          * (1 - exp(-G * (1/C_a + 1/C_b) * dt))
H_a += Q_to_a; H_b -= Q_to_a
T_a = H_a / C_a; T_b = H_b / C_b
```

The kernel owns finite heat capacity/conductivity, validates finite SI inputs, applies equal-and-opposite heat transfer, and reports residual/lag. `SparseThermalWorld` owns chunk scheduling and bounded jobs; `ThermalKernel` owns the pure pair update. The first slice also applies a finite lumped fuel/oxygen reaction inside an insulated region, retaining products and chemical+sensible energy, and enthalpy/latent-heat phase transitions with water/ice priority. In a single phase interval, temperature follows the capacity relation above; across a transition, enthalpy inversion holds the transition temperature while latent energy changes, conserving total heat. It keeps fixed material properties and has no cross-region or cold-region flux, mechanics coupling, fluid flow, or automatic activation.

Phase 2 adds cross-chunk flux and a thermal frontier with conservative accumulation. Phase 3 adds moisture, pyrolysis, radiation, and thermal weakening only as separate validated laws. Airflow, smoke, and full fluid transport remain deferred; there is no fluid-flow requirement for the initial thermal runtime. A finite lumped fuel/oxygen reaction must conserve fuel mass and chemical+sensible energy into retained products; it is not a Navier–Stokes fire model. Burning cannot be a visual flag or unexplained mechanical impulse.

Thermal subcycling is allowed only when fine-step interface fluxes are accumulated once and applied with equal-and-opposite signs at the coarse boundary. The pair formula above is exact for one isolated two-lump exchange; a network solve uses symmetric operator splitting and must report splitting error. Thermal lag, reaction backlog, and unprocessed frontier age are first-class report fields.

## Learning and caches

Offline learned surrogates or analytical caches may be used only after a solver has a measured applicability envelope. Keys must include complete physical state, material/law version, geometry/occupancy, solver configuration, resolution, elapsed time, and thermal/chemical history. Invalidation must cover every key field and topology/history change. A miss, uncertainty, or budget violation falls back to the authoritative CPU/local solver. No RL or neural training is part of the initial runtime.

## Acceptance gates

1. **State and boundary gate:** free flight, rigid aggregate promotion, local demotion, contact ownership, and two-body reaction tests close mass, COM, momentum, angular momentum, named energy stores, explicit transfers, and thermal enthalpy within declared tolerances. Force/reaction values are not counted as stored energy.
2. **Temporal-policy gate:** every active island reports solver clock, field clocks, backlog, age, p95/p99 cost, and residual. Soft-deadline behavior preserves the last accepted state and never hides lag.
3. **Spectral/stiffness gate:** timestep and iteration refinement bound wave/contact response for each law; stiff glass and tool contact cannot pass solely on visual output.
4. **Continuum/cut gate:** CPIC/MPM or VBD/AVBD candidates are compared with the CPU reference on force, work, crack/cut area, topology envelope, and convergence under mesh/particle refinement.
5. **Thermal gate:** two-lump conduction has an analytical oracle; multirate fluxes conserve heat; finite fuel/oxygen reaction closes mass and chemical/sensible energy; water/ice phase transitions close enthalpy and latent heat without changing material identity; no thermal claim proceeds to fire/weakening without these checks.
6. **Scale gate:** fixed-active-count and increased-active-count sparse-world runs meet declared memory and p95/p99 budgets or report bounded backlog; no world-scale realtime claim is inferred from a small fixture.
7. **Customer gate:** the ax/tree, door/panel, and tomato bowl retain material identity and history through local interaction. Unsupported hinges, chips, grain, tissue, chemistry, or tool processes reject or report explicitly.

## Current failure table

| Area | Current boundary or failure | Required next evidence |
|---|---|---|
| Axial network | Stiff-wave and cutting convergence are unresolved; it is not a universal active tier | Compare against refined continuum/cutting cases and keep it as an experimental comparator |
| Glass | Stiff response is under-resolved and unreliable | Spectral/timestep/resolution convergence with contact and work closure |
| Oak | Directional axial approximation is not a grain continuum | Orthotropic grain-frame coupons, rotated failure, plastic/crushing law |
| Metal | Ductile demonstrator is not calibrated iron and has no complete J2/rate/thermal law | Calibrated elastoplastic coupons and thermal weakening tests |
| Tissue | Local cohesive tearing is not full cell, fluid, or biological behavior | Finite-strain tissue law, cut convergence, pressure/moisture validation |
| Thermal | Initial/next slice is insulated two-lump enthalpy conduction with finite reaction and water/ice latent heat; no cross-region/cold flux, mechanics coupling, or fluid flow | Cross-chunk conservative flux/frontier, then moisture/pyrolysis/radiation/weakening; airflow, smoke, and full fluid transport remain deferred |
| Geometry | Clamped panels and torn networks do not implement hinges or complete chips | Surface refinement, mass removal, hinge/contact ownership, topology and conservation tests |
| Scheduling | No automatic localized activation/re-coarsening or universal realtime guarantee | Sparse active islands, field clocks, bounded backlog, scale and p95/p99 evidence |

The plan preserves the existing 40 mechanic/platform requirements. Each phase must add evidence and retain prior controls; a faster path is acceptable only when it is numerically equivalent within the declared envelope.
