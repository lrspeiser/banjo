# Banjo roadmap

## Milestone 0 — material bootstrap ✅

- C++23/CMake project and CI
- Jolt 5.6.0 integration
- Engine-neutral impact events
- Energy-based material activation
- Procedural sphere lattice with no precut chunks
- XPBD-style brittle bond reference solver
- Connected-component fragment discovery
- Fragment mass and momentum reconstruction

## Milestone 1 — observable and safer fracture ◐

Completed in the current iteration:

- Remove both linear and angular momentum from the internal fracture pulse
- Deterministically sort contact events
- Report kinetic energy, estimated elastic energy, maximum stretch, and maximum node speed
- Expose active nodes, bonds, damage, and component counts to a shared simulation controller

Still required:

- Calibrate glass at coarse, normal, and fine resolutions
- Track fracture energy, damping loss, and numerical error separately
- Add compression- and shear-sensitive failure rather than tensile stretch alone
- Record portable deterministic replay packages

## Milestone 2 — return fragments to Jolt ✅ prototype

- Generate exposed voxel-face meshes while removing internal faces
- Sample component surfaces into convex collision proxies
- Convert a bounded set of components into Jolt bodies
- Convert overflow/tiny components into lightweight debris
- Batch-create Jolt fragment bodies
- Supply material-derived mass and inertia instead of collision-hull mass
- Verify complete component mass accounting in tests and the headless run

Next quality work:

- Better convex decomposition for strongly concave fragments
- Sleeping and debris retirement policies
- Smoothed visual surfaces independent of collision proxies
- More explicit system angular-momentum error reporting at handoff

## Milestone 3 — visual laboratory ✅ bootstrap

The current visual laboratory uses raylib 6.0 as a deliberately lightweight shell:

- Resizable 3D window and camera controls
- Rigid iron and glass spheres
- Instanced-style active voxel view
- Optional live/broken bond overlay
- Generated fragment mesh rendering after Jolt handoff
- Opaque/frosted glass presentation
- Runtime speed, resolution, gravity, pause, step, reset, and wireframe controls
- Deterministic offscreen CI screenshot capture

Production renderer work remains:

- SDL3 application shell
- Dawn/WebGPU rendering and compute
- GPU buffers for active voxels and bonds
- Dear ImGui material and solver panels
- Stress, contact, and energy overlays
- Transparent/refractive glass after opaque geometry is stable

## Milestone 4 — authoritative two-way rigid/material coupling

- Turn an activating Jolt contact into sensor-like contact before rigid response
- Let the material solver distribute the authoritative contact impulse
- Return equal-and-opposite reaction impulse to the rigid body
- Keep iron colliding with glass during active fracture
- Collide active nodes against arbitrary rigid environment shapes
- Define synchronization and substepping rules

## Milestone 5 — local physicalization

- Activate a contact-centered material patch instead of the whole object
- Couple patch boundaries to an aggregate rigid body
- Expand the patch when stress or damage approaches its edge
- Split only disconnected matter into new bodies
- Re-coarsen stable regions

## Milestone 6 — material validation

- Beam, tension, compression, shear, impact, and fracture calibration scenes
- Resolution-invariant outcome envelopes
- Reference comparison against peridynamic or finite-element solvers
- Material versioning and uncertainty ranges

## Milestone 7 — authoring language and publishing

- JSON Schema for materials, objects, scenes, and tests
- Unit-aware intermediate representation
- Static cost and capability declarations
- Trusted law primitives and solver selection
- AI-generated source plus required behavioral tests
- Versioned universe packages and deterministic dependency locks
