# Banjo

Banjo is an experimental **matter-first runtime for editable-physics worlds**. Ordinary objects remain inexpensive rigid bodies until an interaction requires material detail. The object can then become an active voxel-and-bond simulation, fracture according to its material law, and return to inexpensive rigid fragments.

The current visual proof performs this complete transition:

```text
iron rigid sphere
        ↓ Jolt contact and measured impact energy
glass rigid sphere
        ↓ material activation
intact procedural voxel/bond lattice
        ↓ XPBD-style deformation and emergent bond failure
connected voxel components
        ↓ exposed-face meshing and convex proxy generation
Jolt rigid glass fragments + lightweight debris
```

There are no precut chunks and no shatter animation. The pieces are the connected components that remain after the material bonds fail.

## Build and watch it

Requirements:

- CMake 3.25 or newer
- Ninja or another CMake generator
- A C++23 compiler: GCC 12+, Clang 16+, or Visual Studio 2022+
- Git
- Normal desktop OpenGL/window-system development libraries

On macOS, the usual setup is:

```bash
brew install cmake ninja
```

Then:

```bash
git clone https://github.com/lrspeiser/banjo.git
cd banjo
cmake --preset dev
cmake --build --preset dev
./build/dev/banjo_lab
```

CMake fetches pinned copies of Jolt Physics `v5.6.0` and raylib `6.0`. The first build therefore compiles those dependencies as well as Banjo.

### Controls

| Control | Action |
|---|---|
| `R` | Reset the experiment |
| `Space` | Pause or resume |
| `N` | Advance one fixed physics step while paused |
| `B` | Show a sampled bond view |
| `W` | Toggle wireframe overlays |
| `Up` / `Down` | Increase or decrease iron-ball speed, then reset |
| `1`, `2`, `3` | Select coarse, normal, or fine voxel detail, then reset |
| `G` | Cycle gravity direction, then reset |
| Right mouse drag | Orbit the camera |
| Mouse wheel | Zoom |

The visual lab deliberately slows simulation to make the representation change visible. The overlay reports impact energy, active nodes, broken bonds, connected components, rigid fragments, debris, and handoff mass error.

## Automated headless proof

```bash
./build/dev/banjo_headless
ctest --preset dev
```

`banjo_headless` runs the same state machine as the viewer, waits for fracture, generates fragment meshes and convex proxies, batch-inserts the rigid pieces into Jolt, advances them for another second, and fails if mass is lost or a generated rigid body is missing.

To build only the dependency-free material core and tests:

```bash
cmake --preset core
cmake --build --preset core
ctest --preset core
```

## What is implemented

- Procedural solid-sphere material sampling with partial boundary-cell volume
- Resolution-compiled brittle material parameters
- Horizon bond lattice with deterministic material variation
- Thread-safe Jolt contact translation into engine-neutral impact events
- Energy-based activation rather than material-name interaction tables
- Rigid-to-material transfer of position, linear velocity, and angular velocity
- Contact-localized internal pulse with both net linear and angular momentum removed
- XPBD-style brittle bond deformation and progressive damage
- Connected-component discovery from surviving bonds
- Exposed voxel-face surface generation with internal faces removed
- Sampled convex collision proxies for large and small components
- Material-derived fragment mass, center of mass, inertia, and velocities
- Batched fragment creation in Jolt using supplied mass and inertia
- Lightweight debris fallback for components beyond the rigid-body budget
- Interactive 3D viewer and deterministic CI screenshot capture

## Current boundaries

This is still a physics laboratory, not yet the publishing platform:

- During the active-material phase, the iron ball is no longer coupled to the glass voxels after the initial rigid collision. Authoritative two-way rigid/material contact is the next major solver milestone.
- Active voxels currently collide only with a floor plane. Arbitrary Jolt-shape collision comes with two-way coupling.
- The fracture model is visually useful but not yet calibrated across multiple resolutions against laboratory glass data.
- Surface meshes are block-style exposed voxel faces. Smoothing and crack-surface material treatment are future rendering work.
- raylib is a quick visual shell. The simulation and fragment geometry layers do not depend on raylib, preserving the planned path to a production SDL3/Dawn/WebGPU renderer.
- The JSON files are authoring contracts; schema validation and runtime loading are not implemented yet.

See [`docs/architecture.md`](docs/architecture.md) for the data flow and [`docs/roadmap.md`](docs/roadmap.md) for the next milestones.
