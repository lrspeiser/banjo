# Compiled runtime design (v1 direction)

**Status: architectural direction with an experimental v1 slice implemented.**
This document records the intended compiled object and response contract.
The [live checkpoint](compiled-runtime-checkpoint.md) identifies the implemented
subset and measured boundaries. The broader contract below, including full
reaction/energy accounting and adaptive spatial refinement, remains unfinished.
The cited research motivates the direction; those methods are not integrated.

## Scope

V1 is a bounded runtime slice for supported rigid objects and selectively
activated local material/fracture regions. It is not the entire Banjo engine,
publishing platform, or a promise of real-time fracture for arbitrary geometry.
The first conformance set remains identical declared experiments for glass,
oak (wood), and iron. Unsupported constitutive laws must be reported or
rejected; a display name must never select an outcome.

The implementation order is:

1. A schema-validated, unit-bearing declarative authoring API and compiler.
2. An inspectable compiled object/response representation consumed by the
   existing CPU reference runtime.
3. Local progressive activation and fracture with persistent state and seeded
   flaws.
4. Learned local calculations only after measured local baselines and a safe
   fallback path exist.
5. A broader language (the planned LawScript direction) only after the
   declarative API/compiler is stable.

## Compiled object

The compiler converts source intent into immutable laws plus mutable runtime
state. A compiled object should contain, at minimum:

```text
CompiledObject {
  schema/physics ABI and compiler/backend versions
  geometry/occupancy and local coordinate frame
  material field, interfaces, orientation and provenance
  mass distribution, total mass, center of mass, full inertia tensor
  constitutive capabilities and parameters (units, ranges, validity)
  resolution/horizon and discretization calibration
  initial pose, linear/angular velocity, temperature/state where supported
  deterministic seed and persistent flaw/defect distribution
  activation policy, resource limits and unsupported-capability diagnostics
}
```

Mass, center of mass, and inertia are derived from occupied matter and its
material distribution. They are not inferred from a render mesh, display name,
or a radius-one fallback. Compiled laws are immutable for a run; mutable state
holds pose, velocities, deformation, stored recoverable energy, damage,
connectivity, flaw history, and fragment lineage.

The response contract is structured data, not an animation or a name-based
answer:

```text
StepResponse {
  accepted time interval and solver status
  bodies/fragments with stable IDs, provenance and mass properties
  pose, linear/angular momentum and contact/interface reactions
  deformation, damage/connectivity and newly activated local regions
  energy ledger: kinetic, recoverable, external work, fracture/plastic work,
    named losses, correction work and numerical residual
  events (contact, activation, bond failure, separation, refusal/fallback)
  diagnostics: tolerances, budgets, seed, backend and applicability bounds
}
```

One authoritative contact owner must produce equal-and-opposite reactions and
correct torque arms. Activation must transfer mass properties, pose,
linear/angular momentum, and internal state exactly once. The response must
make unsupported laws, budget exhaustion, cache misses, and rejected steps
observable. Energy cannot be created by a correction or by an arbitrary launch.

## Selective local progressive fracture

Keep an intact object cheap until an interaction crosses a declared activation
criterion. Activate a spatial neighborhood around the actual load/contact,
couple its boundary to the coarse representation, and advance both on one
authoritative clock. Refine or grow the neighborhood when the evolved state
requires it; do not precompute a destruction tree.

Fracture is progressive: local stresses, waves, deformation, available work,
and constitutive history update damage and connectivity. A first failed link
must leave surviving networks and cores. Connected components define pieces;
each detached piece retains material, damage, flaw state, stable identity, and
stored energy. Later impacts may activate and fracture that piece again.

Flaws are generated from a deterministic seed and persisted as part of the
compiled object/state identity. They may vary local strength or structure when
the selected law supports that behavior, but they do not prescribe shards,
failure order, or launch velocities. Replays and cache keys include the seed,
flaw content, geometry, material state, solver settings, contact state, and
time integration settings.

## Research-informed boundaries

These papers motivate the boundaries, not implementation claims:

- [Breaking Good (SIGGRAPH Asia 2022)](https://www.dgp.toronto.edu/projects/breaking-good/)
  demonstrates precomputed fracture modes and impact-dependent patterns, but
  explicitly avoids online crack propagation. Banjo may use such modes as an
  offline analysis or proposal; they cannot be the authoritative progressive
  fracture result.
- [Augmented Vertex Block Descent (SIGGRAPH 2025)](https://graphics.cs.utah.edu/research/projects/avbd/Augmented_VBD-SIGGRAPH25.pdf)
  provides a stable, fast constraint solver and plausible breaks in rigid
  block attachments. Its rigid-block results do not establish detailed local
  material fracture for Banjo.
- [Fast Nodal Hessian Computation for Peridynamic Fracture (May 2026)](https://onlinelibrary.wiley.com/doi/full/10.1111/cgf.70503)
  motivates efficient local implicit/peridynamic calculations and solver
  primitives. It does not supply Banjo's calibrated material laws or runtime
  integration.
- [IFENN (2025)](https://arxiv.org/abs/2505.19566) motivates a later learned
  local calculation: it learns spatial coupling near a phase-field process
  zone while retaining an FEM equilibrium solve. Banjo must validate a learned
  result against a reference and fall back when outside its domain.
- [Differentiate the Solver, Not the Equation (August 2026 preprint)](https://arxiv.org/abs/2608.08559)
  motivates differentiating the executed local solver for offline training.
  It does not justify inserting an unvalidated model into the authoritative
  runtime.

## Supported-model policy and evidence

V1 supports only explicitly implemented and tested models. A material catalog
entry is not proof of brittleness, plasticity, anisotropy, grain, or thermal
behavior. Comparative tests must run glass, oak, and iron under the same
declared geometry, state, timestep, and solver settings, reporting conserved
quantities, expected density/stiffness differences, and unsupported laws.

The [live compiled-runtime checkpoint](compiled-runtime-checkpoint.md) records
implementation files, supported models, eight glass/oak/iron experiments,
progressive failure and handoff evidence, seed tests, measured timings,
resource limits, native controls and remaining defects. The exported evidence
manifest records the published source revision. No learned surrogate or
physical-state outcome cache has been integrated.

Suggested scorecard follow-up rows: P01 local adaptive matter/physical LOD,
P03 cache identity and reuse, P05 units/laws/capability checks, P06 human/AI
creator APIs, M01 mass/COM, M02 inertia, M05 energy/work, M15 strength/damage,
M16 fracture topology/work, M20 seeded flaws, and M21 fragments/repeated damage.
