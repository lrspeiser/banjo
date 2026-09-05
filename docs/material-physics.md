# Material physics contract

> Scope note (September 4, 2026 audit): this is a focused design/model document, not a complete implementation-status ledger. Read the [master plan](project-master-plan.md) and [development status](development-status.md) first. Main's audited code is `62cf812`; conservative-contact work in PR #2 is not merged.

Banjo separates **authored physical characteristics** from the numerical model that executes them. A material name is descriptive only; no collision rule is allowed to ask whether a material is called `iron`, `glass`, or `rubber`.

## Authored characteristics

The current material contract stores the first set of quantities needed by the ball laboratory:

- density
- Young's modulus and Poisson ratio
- yield, tensile, compressive, and shear strength
- hardness
- fracture energy
- internal damping
- static and dynamic friction
- rolling-resistance coefficient
- contact damping
- anisotropy ratio
- reference temperature
- solver calibration and deterministic strength variation

These values are reference-state inputs, not universal constants. Real materials vary with temperature, manufacturing process, strain rate, flaws, moisture, grain direction, and surface finish. The catalog presets are intentionally labeled reference materials and are calibration starting points rather than certified engineering data.

## Compilation layers

```text
MaterialDefinition
    |-- compileContactMaterial()  -> CompiledContactMaterial
    |-- compileBrittleMaterial()  -> CompiledBrittleMaterial
    `-- future compilers          -> ductile, granular, thermal, fluid, etc.
```

`CompiledContactMaterial` resolves legacy friction fields, validates elastic inputs, and can derive a restitution coefficient from a damped-contact model. Two contact materials are combined using:

- geometric-mean static and dynamic friction
- additive rolling resistance
- compliance-weighted contact damping
- effective Hertz contact modulus
- damping-derived pair restitution

`CompiledBrittleMaterial` converts continuum-scale stiffness and strength targets into resolution-aware bond compliance and tension, compression, and shear damage thresholds. The local solver reconstructs a deformation gradient from each node's live neighborhood and evaluates Green-Lagrange principal strain. That makes the strain measure insensitive to rigid rotation and lets the three strength channels fail differently. The calibration layer remains explicit because a simple bond lattice is not a complete constitutive model.

## Contact activation

Whole-object fracture energy alone is not enough to decide whether detailed matter must be activated. A concentrated contact can exceed a brittle material's local strength while carrying less energy than would be needed to create a crack across the object's full projected area.

The activation policy therefore combines:

- available normal impact energy
- material fracture energy and object scale
- reduced mass and radius
- pair effective elastic modulus
- Hertz peak contact pressure
- a subsurface tensile/shear screening stress
- tensile and compressive strength
- an explicit minimum energy floor that rejects tiny numerical contacts

Hertz theory is used as a fast elastic screening model. It does not encode surface flaws, cone-crack statistics, plastic indentation, rate dependence, or complex geometry. Once the screening threshold is crossed, the detailed material solver—not the Hertz predictor—determines the evolving damage topology.

## Physically grounded relationships and current limits

The implementation currently preserves these relationships:

- mass comes from density times occupied volume
- center of mass and inertia come from the spatial mass distribution
- gravity is an acceleration, so ideal free-fall does not depend on density
- collision momentum depends on both masses
- contact deformation screening uses effective elastic modulus and reduced radius
- analytical rolling/sliding classification uses slope, sphere inertia, and available friction; measured runtime slip diagnostics are in the unmerged contact branch
- brittle activation depends on energy, stress, strength, and fracture properties rather than names
- brittle damage distinguishes tension, compression, and shear in a rotation-invariant local strain measure
- representation transitions reconstruct material mass and bulk motion; mass-accounting tests exist, while complete angular-momentum/energy correctness is still under review

## What remains model-dependent

No finite-resolution real-time solver can infer every material behavior from a short list of scalar constants. Banjo therefore treats each constitutive model as a named, versioned compiler target. The present brittle-bond model is a first solver family, not a claim that all matter is physically a spring lattice.

Planned additions include:

- strain-rate dependence
- plastic flow and work hardening
- anisotropic stiffness and fracture tensors
- temperature, moisture, phase, and fatigue state
- interfaces such as adhesive, weld, fastener, and loose contact
- uncertainty distributions and calibration provenance

The invariant is that creators author physical intent once while solver backends remain replaceable and testable.
