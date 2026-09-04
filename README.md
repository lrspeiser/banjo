# Banjo

Banjo is an experimental **matter-first runtime for editable-physics worlds**. Ordinary objects remain inexpensive rigid bodies until an interaction requires material detail. At that point, the affected object can become an active voxel-and-bond simulation, fracture according to its material law, and later return to a collection of inexpensive rigid fragments.

The first proof is deliberately narrow:

1. Jolt Physics rolls an iron ball into a glass ball.
2. The contact listener measures the actual collision rather than checking `iron + glass` by name.
3. An energy-based policy decides whether the glass needs material simulation.
4. The glass rigid body is replaced by an intact procedural sphere lattice.
5. A contact-localized internal pulse drives an XPBD-style brittle-bond solver.
6. Broken-bond connectivity determines the pieces; no fracture animation or precut chunks are stored.
7. Fragment mass properties can be derived from the resulting material nodes for handoff back to Jolt.

This repository starts with a **headless CPU reference implementation**. A renderer, interactive controls, convex fragment generation, and GPU kernels come after the transition and conservation rules are testable.

## Build

Requirements:

- CMake 3.24 or newer
- Ninja or another CMake generator
- A C++23 compiler (GCC 12+, Clang 16+, or Visual Studio 2022+)
- Git, because CMake fetches the pinned Jolt dependency

```bash
cmake --preset dev
cmake --build --preset dev
ctest --preset dev
./build/dev/banjo_lab
```

Jolt Physics is pinned to `v5.6.0`. Its optional graphics/compute backends are disabled for this reference build, so the prototype does not require Vulkan, DirectX, Metal shader tooling, or CUDA.

To build only the dependency-free core and tests:

```bash
cmake -S . -B build/core -G Ninja \
  -DCMAKE_BUILD_TYPE=Debug \
  -DBANJO_BUILD_LAB=OFF \
  -DBANJO_BUILD_TESTS=ON
cmake --build build/core
ctest --test-dir build/core --output-on-failure
```

## Current boundaries

The current lab proves the **rigid-to-material activation path** and the material data structures. It is not yet a game engine:

- The material solver currently collides with a floor plane, not arbitrary Jolt shapes.
- After glass activation, the iron ball is not yet two-way coupled to active voxels.
- Connected components and fragment mass properties are implemented, but convex collision hull creation and reinsertion into Jolt are the next milestone.
- The JSON files are authoring contracts; a schema-validated loader is not added yet.
- Material constants are plausible starting values, not certified engineering models.

## Source layout

```text
src/core       Small dependency-free math and IDs
src/material   Authored material model and resolution compiler
src/matter     Procedural sphere lattice and adjacency
src/fracture   Activation, XPBD bonds, connectivity, fragment properties
src/rigid      Jolt adapter and thread-safe impact capture
src/app        Headless rolling-ball experiment
assets         Initial material and scene declarations
docs           Architecture and milestone plan
tests          Conservation and topology checks
```

## Design rules

- Do not pre-author fracture pieces.
- Do not simulate every voxel while an object is behaving rigidly.
- Do not hardcode material-name interaction tables.
- Preserve mass and bulk momentum at every representation transition.
- Keep authored physical intent separate from solver-specific coefficients.
- Make resolution, random seeds, solver iterations, and runtime versions explicit.

The working architecture is documented in [`docs/architecture.md`](docs/architecture.md), and the next implementation steps are in [`docs/roadmap.md`](docs/roadmap.md).
