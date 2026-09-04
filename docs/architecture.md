# Banjo bootstrap architecture

## Goal of this repository

The bootstrap proves one complete state transition:

```text
Jolt rigid sphere
    -> measured impact event
    -> material activation decision
    -> procedural intact voxel/bond lattice
    -> locally driven brittle fracture
    -> connected material components
    -> derived fragment mass properties
    -> future Jolt rigid fragments
```

The source of truth is material, while rigid bodies, meshes, and collision hulls are disposable runtime representations.

## Runtime layers

### 1. Rigid world

Jolt Physics owns broad-phase collision, contact generation, rolling, gravity, and normal rigid-body response. Each body carries a Banjo `MatterBodyId` in Jolt user data. Jolt callbacks only copy immutable contact information into a queue because callbacks may execute concurrently while bodies are locked.

### 2. Impact translation

`ImpactEvent` is independent of Jolt. It records body IDs, contact point, manifold normal, closing speed, estimated normal impulse, and available normal kinetic energy. Material code therefore has no dependency on Jolt types.

### 3. Activation policy

The policy compares impact energy with a fracture-energy scale derived from the target material and projected object area. This is intentionally a policy, not a material-name lookup. An iron ball moving too slowly should not shatter glass, while another sufficiently energetic object may.

### 4. Procedural matter

`LatticeAsset` is the immutable intact representation of a sphere:

- sampled occupied material cells,
- represented volume and mass,
- object-local node positions,
- breakable neighbor bonds,
- compact adjacency,
- rest center of mass and inertia.

No fragments exist in the asset. A fragment is discovered only after broken bonds disconnect a set of nodes.

### 5. Active material solver

`BrittleBondSolver` creates mutable node positions, velocities, and bond state from the immutable lattice. The current solver is an XPBD-style distance-constraint reference implementation. It records peak tensile stretch before constraint correction and converts excessive stretch into progressive bond damage.

At activation, the Jolt post-collision linear and angular velocities are transferred to every node. A separate localized velocity pattern supplies internal fracture energy. Its mass-weighted translational component is removed so the pulse does not double-apply the collision's bulk impulse.

### 6. Fragment discovery

`findConnectedComponents` unions nodes linked by live bonds. This topology, not a stored fracture plane, defines the resulting pieces.

### 7. Fragment handoff

`calculateFragmentMassProperties` derives each component's mass, center of mass, linear velocity, inertia tensor, angular momentum, and angular velocity. A future `FragmentRigidBuilder` will create render surfaces and convex Jolt collision proxies while preserving these material-derived quantities.

## Frame ordering

The intended fixed-step order is:

```text
1. Capture pre-step rigid state if required.
2. Step Jolt.
3. Drain and deterministically sort impact events.
4. Evaluate activation outside Jolt callbacks.
5. Capture post-contact rigid state.
6. Remove activated rigid bodies at a safe synchronization point.
7. Initialize and step active material objects.
8. Analyze connectivity only when bonds changed.
9. Convert stable components to rigid fragments in a batch.
10. Update render caches and conservation metrics.
```

## Why the first activation resolves the whole ball

A 3D local patch coupled to a still-rigid remainder is the scalable design, but it adds boundary constraints, patch growth rules, two-way force transfer, and crack continuation across the patch boundary. The first prototype activates the complete glass sphere so fracture, topology, and conservation can be validated independently. Local activation is a later optimization, not a different object model.

## Determinism contract

A replay must record at least:

- fixed step and substep size,
- initial transforms and velocities,
- material definitions and compiler version,
- lattice resolution and neighbor horizon,
- seeded bond variation,
- impact-event ordering,
- solver iteration count,
- Jolt and Banjo runtime versions.

Cross-platform bitwise identity is not promised by the bootstrap. Stable topology and close conservation metrics on a pinned toolchain are the initial target.

## Long-term solver boundary

`BrittleBondSolver` is a first solver family, not the universal physics law. The same authored material layer should later compile to different runtime programs:

```text
Rigid-only
Brittle XPBD bonds
Peridynamic brittle fracture
Ductile/plastic solid
Granular material
Material-point or continuum solver
```

The language and package system should describe physical intent and permitted computational patterns, while solver plugins implement the numerical method.
