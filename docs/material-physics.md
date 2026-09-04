# Material physics contract

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

`CompiledBrittleMaterial` converts continuum-scale stiffness and strength targets into resolution-aware bond compliance and damage thresholds. The calibration layer remains explicit because a simple bond lattice is not a complete constitutive model.

## What is first-principles today

The implementation currently preserves these relationships:

- mass comes from density times occupied volume
- center of mass and inertia come from the spatial mass distribution
- gravity is an acceleration, so ideal free-fall does not depend on density
- collision momentum depends on both masses
- contact deformation screening uses effective elastic modulus and reduced radius
- rolling/sliding classification follows slope, sphere inertia, and available friction
- brittle activation depends on energy, stress, strength, and fracture properties rather than names
- representation transitions preserve material mass and bulk momentum

## What remains model-dependent

No finite-resolution real-time solver can infer every material behavior from a short list of scalar constants. Banjo therefore treats each constitutive model as a named, versioned compiler target. The present brittle-bond model is a first solver family, not a claim that all matter is physically a spring lattice.

Planned additions include:

- strain-rate dependence
- tension/compression/shear damage separation
- plastic flow and work hardening
- anisotropic stiffness and fracture tensors
- temperature, moisture, phase, and fatigue state
- interfaces such as adhesive, weld, fastener, and loose contact
- uncertainty distributions and calibration provenance

The invariant is that creators author physical intent once while solver backends remain replaceable and testable.
