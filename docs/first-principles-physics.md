# First-principles physics contract

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
- linear and rotational damping
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

For a normal collision, the rigid broad phase estimates effective mass from both translational masses and rotational inertia at the contact point. The contact law then combines surface coefficients and computes normal and tangential impulse limits. Fracture activation is based on available local energy and the target's fracture-energy scale, not names such as `iron` or `glass`.

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

The compiler scales stiffness, represented mass, failure work, and neighborhood weights from physical length, area, volume, and fracture energy. Every material backend must publish canonical tests at several resolutions:

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

The current ball laboratory can generate a deterministic grid of candidate collision outcomes and store it in a scenario cache. Runtime lookup follows these rules:

1. Use an exact cached state when available.
2. Interpolate only within a validated tile whose neighboring outcomes have compatible topology and bounded error.
3. Keep multiple branches when small uncertainty changes the outcome class.
4. Select or refine a branch when the real contact manifold becomes known.
5. Fall back to live simulation whenever the request is outside the validated domain, conservation residuals exceed tolerance, or the topology is ambiguous.

A cache stores solver results, not a prerecorded animation. Cached fracture state consists of material damage/connectivity, fragment transforms and velocities, energy accounting, and provenance. Gravity and subsequent collisions continue to be simulated after a cached transition is instantiated.

## 7. Conservation ledger

Every representation transition records:

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

Mass, linear momentum, and angular momentum are hard invariants unless an authored world law explicitly declares otherwise. Energy may move into irreversible channels, but unexplained energy creation is a failed test.

## 8. Current model boundaries

The present brittle-ball implementation is a physically parameterized reference solver, not a certified continuum-mechanics package. It already removes material-name rules, derives aggregate mass from density, derives fracture thresholds from strength/fracture-energy inputs, preserves momentum through representation changes, supports arbitrary gravity and inclined support planes, and creates fragments from broken connectivity.

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
