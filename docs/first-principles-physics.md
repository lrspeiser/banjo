# First-principles physics contract

> Scope note (September 4, 2026 audit): this is a focused design/model document, not a complete implementation-status ledger. Read the [master plan](project-master-plan.md) and [development status](development-status.md) first. Main's audited code is `62cf812`; conservative-contact work in PR #2 is not merged.

Banjo's goal is not to attach a bespoke behavior script to every named material. The runtime takes measurable material, geometry, contact, field, and state properties and compiles them into the cheapest solver representation that can answer the current interaction.

This document defines the contract used by the rolling-ball laboratory and the direction for later objects.

## 1. Authored quantities versus solver coefficients

Creators author quantities with units and physical meaning. Examples include:

- density (kg/m^3)
- Young's modulus (Pa)
- Poisson ratio
- tensile, compressive, and shear strength (Pa)
- fracture energy (J/m^2)
- coefficient of static and dynamic friction
- coefficient of restitution
- rolling-resistance coefficient
- explicitly modeled environmental drag, separate from internal material and contact damping
- thermal expansion, conductivity, heat capacity, melting point, and ignition state (future solver families)
- anisotropy axes, grain direction, layers, porosity, and defect distributions

A material compiler converts those quantities into resolution- and solver-specific coefficients. A creator should not directly choose an XPBD compliance, lattice bond threshold, Jolt mass override, or GPU workgroup size.

The split is intentional:

```text
measurable material + geometry + state
                  |
                  v
       unit-checked material compiler
                  |
                  v
 rigid/contact law | brittle law | ductile law | granular law | fluid law
```

Changing density must change mass and inertia. Changing friction must change tangential contact response. Changing restitution must change recoverable normal impulse. Changing stiffness and strength must change deformation and failure without a material-name conditional.

## 2. Ball test equations

A solid spherical body of radius `r` and density `rho` begins with:

```text
volume = 4/3 pi r^3
mass = density * volume
inertia about each principal axis = 2/5 mass r^2
```

For a sphere rolling without slipping down a plane inclined by angle `theta`, the ideal center-of-mass acceleration is:

```text
a = g sin(theta) / (1 + I/(m r^2))
```

For a solid sphere this becomes `5/7 g sin(theta)`. The actual runtime may depart from that value because authored rolling resistance, slipping, damping, deformation, and contact compliance are real energy-loss channels. The laboratory uses the ideal equation as a reference rather than forcing every ball to follow it.

For a general contact, the desired effective-mass calculation includes translational mass and rotational inertia at each torque arm. Main's sphere impact-energy screen uses the reduced translational mass; do not mistake that special-case screen for a validated general-contact solver. Contact laws combine surface coefficients and impose impulse limits. Activation uses energy/stress/material screening, not names such as `iron` or `glass`.

## 3. One support-plane model

The same support plane must be used by every representation:

- rigid balls in Jolt
- active material nodes
- newly generated rigid fragments
- lightweight debris
- the visual floor
- scenario projection

The plane is represented by a normalized outward normal `n` and a signed offset `d`:

```text
signed_distance(x) = dot(n, x) - d
```

A sphere is initially placed one radius along `n`. A material node or debris particle penetrates when its signed distance is below its support radius. Contact projection, friction, and restitution are applied in the plane's normal/tangent basis rather than assuming world `+Y`.

Gravity is an independent vector field. Tilting the plane and rotating gravity are therefore distinct experiments. After fracture, every component continues to receive the same field acceleration and collides with the same plane.

## 4. Material interactions

Bulk material and surface interaction are separate declarations. The initial compiler uses deterministic combination rules for two contacting surfaces and keeps the resulting contact law in the impact event. This lets the fracture layer know the impulse, effective restitution, friction, and energy that the rigid solver actually used.

Interfaces will later support coatings, lubrication, adhesion, welding, fasteners, and temperature-dependent contact. Those belong to an interface law and should not silently mutate bulk density or tensile strength.

## 5. Resolution independence

A voxel or lattice bond is a numerical sample, not a physical atom. Material strength may not be defined as a fixed force per bond because changing resolution changes the number of bonds crossing an area.

The intended compiler must scale stiffness, represented mass, failure work, and neighborhood weights from physical length, area, volume, and fracture energy. Some stiffness/mass/threshold compilation exists, but fracture-work accounting and resolution convergence are unfinished. Every material backend must publish canonical tests at several resolutions:

- static mass and inertia
- rolling acceleration and stopping distance
- coefficient-of-restitution drop test
- sliding-friction test
- tensile, compression, and shear coupons
- beam bending
- impact and fracture classification

Exact crack geometry can vary with resolution and seeded defects, but broad outcomes and accounted energy should converge.

## 6. Forward projection and cached outcomes

Banjo may project several plausible continuations before contact. A projection key contains quantized physical state rather than object names:

```text
geometry/material version hashes
relative position and orientation
linear and angular velocity
contact normal and location
material state and damage
support plane and gravity
solver version, resolution, and deterministic seed
```

The current ball laboratory generates a deterministic grid of analytical scenario summaries and stores it in a projection cache. MaterialOutcome serialization APIs also exist, but automatic authoritative outcome reuse is not integrated. The following are target rules for a future validated runtime cache, not current playback behavior:

1. Use an exact cached state when available.
2. Interpolate only within a validated tile whose neighboring outcomes have compatible topology and bounded error.
3. Keep multiple branches when small uncertainty changes the outcome class.
4. Select or refine a branch when the real contact manifold becomes known.
5. Fall back to live simulation whenever the request is outside the validated domain, conservation residuals exceed tolerance, or the topology is ambiguous.

The future authoritative cache must store solver results, not an unrelated prerecorded animation: material state/connectivity, motion, accounted work and provenance with applicability checks and consistent elapsed time. Gravity and subsequent collisions must remain live. The current CSV contains analytical summaries only; the current outcome format does not yet satisfy the full state/key/energy contract.

## 7. Conservation ledger

Every representation transition must eventually record the following ledger; current diagnostics do not yet cover every term:

```text
mass
center of mass
linear momentum
angular momentum
kinetic energy
recoverable elastic energy
fracture work
plastic work
contact and rolling losses
damping loss
potential-energy change
numerical residual
```

For an isolated closed system, mass and total momentum are invariants unless an authored law explicitly declares otherwise. For bodies acted on by gravity, supports, boundaries, or actuators, include the corresponding external impulse, torque and work. Transfers must not introduce unexplained changes. Energy may move into named irreversible channels; unexplained energy creation is a failed test.

## 8. Current model boundaries

The present brittle-ball implementation is a physically parameterized reference solver, not a certified continuum-mechanics package. It removes material-name outcome rules, derives aggregate mass from density, uses strength/fracture-energy screening inputs, supports gravity vectors and inclined support planes, and creates fragments from broken connectivity. Mass bookkeeping and selected momentum/contact tests exist; whole-pipeline momentum/energy consistency, finite-cell angular state and fracture-work calibration still require an audit.

Still required for stronger physical fidelity:

- calibrated tensile, shear, and compression damage surfaces
- strain-rate and temperature dependence
- ductile plasticity for metals
- viscoelasticity for rubber and polymers
- anisotropy and grain for wood and composites
- authoritative two-way contact while material is active
- local physicalization instead of whole-object activation
- uncertainty bounds and validated interpolation for cached outcomes
- measured benchmark datasets for parameter fitting

No higher-level language or AI authoring layer should bypass this contract. It must generate unit-bearing declarations, compiler inputs, and behavioral tests that the runtime can inspect and reject when invalid or too expensive.
