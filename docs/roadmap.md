# Bootstrap roadmap

## Milestone 0 — committed here

- C++23/CMake project and CI
- Jolt 5.6.0 integration
- Headless iron-ball/glass-ball experiment
- Thread-safe, engine-neutral `ImpactEvent`
- Physical activation policy
- Procedural sphere lattice with no precut chunks
- XPBD-style brittle bond reference solver
- Connected-component fragment discovery
- Fragment mass and momentum reconstruction
- Initial material and scene declarations
- Core tests

## Milestone 1 — make the headless fracture robust

- Calibrate glass at 24³, 32³, and 48³ equivalent resolutions
- Track elastic, fracture, damping, and numerical energy separately
- Add compression/shear-sensitive damage rather than tensile stretch alone
- Remove both linear and angular momentum from the internal fracture pulse
- Add deterministic event sorting and replay files
- Add benchmark output for active nodes, bonds, broken bonds, and component count

## Milestone 2 — return fragments to Jolt

- Generate exposed voxel-face meshes
- Build a convex hull for each large connected component
- Approximate tiny components as particles or simple primitives
- Batch-create Jolt fragment bodies
- Use material-derived mass and inertia rather than collision-hull mass
- Verify combined fragment mass, linear momentum, and angular momentum

## Milestone 3 — visual laboratory

- SDL3 window and input
- Dawn/WebGPU rendering
- Instanced voxel and bond debug views
- Opaque/frosted glass first; transparent refractive shards later
- Dear ImGui controls for speed, material, resolution, gravity, and seed
- Contact, stress, damage, and component overlays

## Milestone 4 — two-way rigid/material coupling

- Make an activating contact sensor-like before rigid response
- Transfer the authoritative material reaction impulse back to Jolt
- Support continued iron-to-active-glass collision
- Collide active nodes against arbitrary rigid environment shapes
- Define synchronization and substepping rules

## Milestone 5 — local physicalization

- Activate a contact-centered material patch
- Couple patch boundaries to an aggregate rigid body
- Expand the patch when stress or damage approaches its edge
- Split only disconnected material into new bodies
- Re-coarsen stable regions

## Milestone 6 — authoring language

- JSON Schema for materials, objects, and scenes
- Unit-aware intermediate representation
- Static cost and capability declarations
- Trusted law primitives and solver selection
- AI-generated source plus required behavioral tests
- Versioned universe packages and deterministic dependency locks
