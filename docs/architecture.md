# Banjo runtime architecture

**Automatic creator assistant at `ae82167`:** `CodexAssistant` accepts immutable world/design context and returns a proposal or clarification; it cannot mutate `CreatorWorld`. `ChildProcess` owns the background Windows process tree, bounded polling, streams and cancellation. The workshop validates returned recipes against current inventory/placement before enabling Build. [Source, live-call evidence and limits](assistant-checkpoint.md) distinguish this provider adapter from the shared physics/compiler and future untrusted-world sandbox.

**Creator application at `9cd9197`:** `CreatorWorld` is the shared single-thread owner of inventory, bounded SI recipes, analytical solid-sphere compilation, creation transactions, persistence and one Jolt runtime. The CLI, workshop and glass/oak/iron tests share it. A manual request/proposal file bridge accepts model-authored input only after independent validation and user preview; it makes no automatic model call. Process-global Jolt registration now supports concurrent world lifetimes. [Contract, quantitative evidence and limits](creator-checkpoint.md) keep this intact-rigid mode separate from the detailed reference and existing activation path; neither deformation nor fracture is silently enabled.

**Adaptive reference at `8cf33bc`:** `CompliantAdvance` privately compares one interval with two actual half steps, controls node/sphere motion, live-bond strain and damping-work differences, and publishes only after the whole requested interval passes its work/reaction audit. Equation-residual budgets prevent excessive accumulation across tiny substeps while independent state-audit tolerances remain unchanged. [Evidence and integration plan](adaptive-checkpoint.md) keep one clock/contact owner per participant; the current Jolt-first active phase cannot directly call this sphere-advancing reference. The viewer still uses the older runtime path.

**Trajectory measurement at `e5b883e`:** the probe exports all node states at explicit accepted physical times; Python analysis checks identities, masses, source binary and configuration before comparing every node. [Five-rate evidence](trajectory-checkpoint.md) motivates temporal error control over both bulk and internal state. Runtime integration must give one solver ownership of each participant's clock: the current Jolt-first active phase cannot directly call a reference that also advances the sphere. This checkpoint changes diagnostics, not simulation ownership.

**Explicit compliance reference at `58546cb`:** `NormalCompliance` defines recoverable normal-interface energy and compression-only damping. `CompliantStep` couples it to elastic bonds, a finite sphere and a static plane using the existing global Newton/GMRES machinery. Mass-weighted residual work/momentum inform stopping; independent state-based work/reaction audits and compression/geometry bounds control transactional publication. The caller explicitly chooses this law; there is no fallback from rigid event restitution. [Analytical and three-material evidence](compliance-checkpoint.md) records the limitations. This is not wired into `RollingBallExperiment`.

**Current contact reference at `b31a8a5`:** `ConservativeAdvance` brackets new contacts through unpublished masked trials, applies `NormalImpact` at arrivals, and audits the entire interval before publishing. Root search now requires arrival, guarantees bracket reduction, retries failed solves without fabricated gap signs, and attempts a tiny final remainder without dropping time. Full-resolution glass/oak/iron impacts advance using short intervals; sustained dissipative contact and temporal accuracy remain unresolved. See [method and evidence](event-root-checkpoint.md) and the [mechanics scorecard](mechanics-scorecard.md). This is not wired into `RollingBallExperiment`.

**Support update at `1deb025`:** material/plane unilateral constraints join the global elastic Newton system through complementarity rows. Recover support reactions from the solved momentum equations; do not apply a second impulse or position edit. Finite-sphere contacts still use the outer impulse iteration. The reference remains separate from the lab, with impact timing unresolved. See [method, evidence and limitations](coupled-support-checkpoint.md).

**Coupled reference at `dc7bcfb`:** `physics/ConservativeStep` advances elastic matter and optional finite-sphere/support normal contacts in one midpoint solve, with independent balance/gap checks and transactional failure. `physics/ElasticNewton` adds global Newton/GMRES elasticity; the original local solve remains selectable. `banjo_solver_probe` measures actual-glass convergence, linear work and timing. It is not part of `RollingBallExperiment` yet; stiff sampled contact convergence, normal-impact timing, runtime cost, friction/restitution and damage integration remain work. See [current global-solve evidence](elastic-newton-checkpoint.md) and the [initial coupled formulation](conservative-reference-checkpoint.md).

**Latest solver update at `d56611c`:** damage samples accepted substep endpoints, never predictor positions or constraint iterates. Synthetic excitation has been removed, and nonzero legacy pulse settings are rejected. Outcome solver model 5 invalidates older damage behavior. Optional stage diagnostics identify substantial stored-energy injection from post-solve contact/floor correction; this and angular drift remain unresolved. See [active-stage evidence](material-stage-checkpoint.md). Historical pulse descriptions below do not describe this branch.

**Local integration update:** `codex/physics-foundation` at tested code `f29334d` now contains PR #2's sphere/material coupling plus main's build fixes. In this branch activating contacts defer the Jolt response, the runtime pulse is disabled, and material impulses update the finite-mass striker between microsteps. The rigid-first pulse description below documents the historical main baseline, not this branch's authoritative path. See [Windows integration evidence and conservation gaps](windows-integration-checkpoint.md).

**Transfer update at `68c4908`:** active cells retain intrinsic isotropic spin with inertia `m*h*h/6`; target rigid inertia comes from its sampled lattice. Fragment angular momentum includes orbital and cell-spin terms, and overflow debris keeps the component inertia. `MechanicalAccounting` measures mass, COM, world-origin angular momentum, kinetic energy, live-bond spring energy and gravity potential. Runtime transfer audits read actual inserted Jolt/debris states and report discarded internal kinetic/elastic energy. Outcome format 2 / solver model 4 includes cell spin and rejects format 1. This preserves transfer bookkeeping; active-cell spin has no torsional coupling and debris uses a fixed-inertia spin reservoir. The full-step solver budget remains incomplete. See [measured results and limitations](transfer-accounting-checkpoint.md).

> Scope note (September 4, 2026 audit): this is a focused design/model document, not a complete implementation-status ledger. Read the [master plan](project-master-plan.md) and [development status](development-status.md) first. Main's audited code is `62cf812`; conservative-contact work in PR #2 is not merged.

## Current executable pipeline

```text
RollingBallExperiment
├── JoltWorld
│   ├── floor and rigid spheres
│   ├── multithreaded contact listener
│   └── generated rigid fragment bodies
├── ActivationPolicy
├── procedural LatticeAsset
├── BrittleBondSolver
├── connected-component analysis
├── FragmentGeometry builder
└── lightweight debris integrator
```

`RollingBallExperiment` is shared by the windowed viewer and the automated headless executable. Rendering therefore does not own or duplicate simulation state.

## Representation state machine

```text
Rigid
  Jolt owns one smooth sphere and its collision shape.
    ↓ measured impact exceeds the material threshold
Active material
  The glass sphere becomes material nodes plus breakable bonds.
    ↓ the fracture becomes stable or reaches its simulation budget
Fragmenting
  Surviving-bond connectivity defines components; exposed voxel faces,
  collision samples, and material mass properties are generated.
    ↓ batch insertion
Rigid fragments
  Jolt owns a bounded set of convex fragment bodies. Remaining tiny
  components use a lower-cost debris representation.
```

The immutable `LatticeAsset` contains no fragment definitions. Every bond begins intact. Pieces exist only after runtime damage disconnects the bond graph.

## Impact capture

Jolt contact callbacks may run concurrently while bodies are locked. `ImpactCollector` therefore performs no world mutation. It copies contact position, normal, relative velocity, estimated impulse, reduced-mass impact energy, body IDs, and fixed tick into a protected queue.

After `PhysicsSystem::Update` returns, the experiment drains and deterministically sorts those engine-neutral `ImpactEvent` values. Only then may it remove the rigid glass body and activate material simulation.

## Rigid-to-material handoff

The current prototype uses a rigid-first handoff:

1. Jolt resolves the original iron/glass collision.
2. Banjo captures the glass sphere's post-contact center of mass, orientation, linear velocity, and angular velocity.
3. Every material node receives the corresponding rigid velocity:
   `linear velocity + angular velocity × node offset`.
4. A localized internal velocity field is placed near the contact.
5. Its mass-weighted translation and best-fit rigid rotation are projected out.
6. The residual deformation mode is scaled to a bounded fraction of measured impact energy.

This projects out the added bulk impulse, but it does not establish a closed collision-energy budget. It is a provisional main-baseline mechanism, not the desired authoritative physics path. PR #2 disables the runtime synthetic pulse and instead couples material points to a finite-mass sphere. Its integration and full conservation audit remain open.

## Active material

`BrittleBondSolver` is a CPU reference implementation:

- gravity predicts node positions,
- XPBD distance constraints resist bond extension,
- a simple plane constraint handles the floor,
- local rotation-invariant strain and tension/compression/shear thresholds accumulate damage,
- failed bonds are removed from subsequent solves,
- velocities are reconstructed from corrected positions.

The solver reports broken bonds, maximum tensile stretch, kinetic energy, estimated elastic energy, and maximum node speed. These measurements are debugging signals, not yet a complete thermodynamic energy ledger.

## Fragment discovery and geometry

A disjoint-set pass joins every node pair that still has a live bond. Each resulting connected component becomes an independent material piece.

For each component:

1. Sum node mass and momentum.
2. Compute center of mass, full inertia tensor, angular momentum, and angular velocity.
3. Emit a quad wherever a voxel face has no same-component grid neighbor.
4. Remove internal faces automatically.
5. Select directional extrema and distributed surface samples for a convex proxy.
6. Preserve the full block-style surface mesh separately from the collision proxy.

This is generated geometry, not a selected animation or precut Voronoi asset.

## Material-to-rigid handoff

The largest bounded set of components is inserted into Jolt in one batch. Each body uses:

- a generated convex hull,
- a center-of-mass-adjusted collision shape,
- the material component's mass,
- the material component's full inertia tensor,
- derived linear and angular velocity,
- continuous collision detection for small fast pieces.

Collision hull density is not allowed to overwrite material-derived mass properties. Components outside the rigid-body budget remain represented as lightweight debris, and their mass is still included in accounting.

## Renderer boundary

The viewer consumes only public experiment state:

- rigid snapshots,
- active node and bond arrays,
- generated fragment surface meshes,
- lightweight debris positions,
- diagnostics.

raylib is currently used to make the transition visible quickly. It is not referenced by `banjo_core`, `banjo_runtime`, the solver, or fragment geometry. A future Dawn/WebGPU renderer can consume the same data without changing the physical state machine.

## Known correctness boundary

The initial collision is still rigid-authoritative. Once the glass body is removed, the iron sphere is not coupled to active material. PR #2 implements the first sphere/material version of sensor-deferred activation and equal-and-opposite reaction. It remains unmerged and does not yet cover arbitrary shapes, self-contact, or full-pipeline validation. Read development-status.md before deciding whether a capability is on main.
