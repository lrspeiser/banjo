# Banjo

**A physics engine where things are made of something.**

An object here is not a shape with a "breakable" flag on it: it is cells joined
by bonds, the bonds carry tension and compression, they yield and they fail, and
what happens to a thing is worked out rather than looked up. Drop a glass ball
and an iron one from the same height onto the same floor and they do different
things, because they are made of different stuff.

```c
#include "banjo/banjo.h"

banjo_world *w = banjo_open(scene_json, 0.02);
for (int i = 0; i < 600; ++i) banjo_advance(w, 1.0 / 120.0, 0.003);
printf("%d bodies now
", banjo_body_count(w));
banjo_close(w);
```

## Using it

- **[docs/api/](docs/api/README.md)** — start here. Install, quickstart in C and
  Python, and the four things to know before you build anything.
- **[docs/api/c-api.md](docs/api/c-api.md)** — every function, the scene format,
  the caps.
- **[docs/api/materials.md](docs/api/materials.md)** — the eight materials, what
  each actually does, and how to design an experiment that shows something.
- **[docs/api/mcp.md](docs/api/mcp.md)** — the MCP server, so Claude or ChatGPT
  can run experiments instead of guessing at them.
- **[docs/building-on-banjo.md](docs/building-on-banjo.md)** — a shorter
  orientation, and the honest list of what is not built in.

## Seeing it

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build --config Release
python playground/server.py --port 8765
```

`http://127.0.0.1:8765/world` is a room you stand in: W A S D to walk, click to
pick things up, and a chat panel that can rearrange the room for you. Sixteen
plates of every material at two thicknesses to drop things on.

`http://127.0.0.1:8765` is the older bench: describe an experiment, watch it run,
read the report.

## The one thing that surprises people

**Breaking is a conversation, not a property.** When a step would break
something, the step is *taken back* and time does not move until you answer —
because handing the lattice a collision that has already been resolved is
handing it a ball that has already bounced, and it breaks nothing however hard
it was hit. `banjo_advance` holds that conversation for you.

---

## Project history

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

## Project brief and development handoff

**Start with [the complete project master plan](docs/project-master-plan.md).** It covers the editable-physics publishing platform, procedural matter and adaptive simulation, material/interface laws, the ball and door test grounds, speculative precomputation, the creator language/APIs, AI authoring, and publishing.

[Development status](docs/development-status.md) records what is implemented, what remains experimental, exact commits/PRs, tests, known defects, and build instructions. [The roadmap](docs/roadmap.md) turns the remaining work into ordered acceptance gates. Coding agents should also read [AGENTS.md](AGENTS.md).

The [mechanics scorecard](docs/mechanics-scorecard.md) tracks every retained mechanic and platform capability with evidence and next steps. Material-dependent testing retains **glass, oak (wood), and iron** in a growing set. The [material workshop](docs/creator-checkpoint.md) collects inventory, validates designs, builds physical rigid spheres and saves recipes/state. Its CLI, viewer and comparative tests share the compiler. The [automatic Windows assistant](docs/assistant-checkpoint.md) returns structured proposals or clarifications through an authenticated Codex CLI; all 15 Windows test suites pass. [Oriented solid boxes](docs/shape-checkpoint.md) now share the creator path, with equal-volume glass/oak/iron comparisons and real LLM block proposals; 15 suites pass. New box controls await normal interactive verification. Safe revisions and material reclamation are next.

The earlier [adaptive checkpoint](docs/adaptive-checkpoint.md) records bounded reference accuracy control, a grazing-contact guard and 12 full-size glass/oak/iron runs with matched node trajectories. Global convergence, calibrated interfaces and default-runtime integration remain open; observed costs are far from real time. The earlier rigid restitution failure remains documented.

The local `codex/physics-foundation` branch integrates main and PR #2's contact-driven fracture/rolling diagnostics. [Stage-accounting evidence](docs/material-stage-checkpoint.md) records tested code `d56611c`, nine passing CTest executables, headless/capture results and normal input verification. Damage uses accepted states, finite-cell spin survives transfers, and optional diagnostics expose numerical energy changes. This checkpoint is not pushed or merged into GitHub main; PR #2's earlier Linux CI belongs to its own head. This remains a physically parameterized prototype with known over-fragmentation and conservation defects.

## Try the material workshop

After building, run `banjo_workshop --workspace build/my-workshop` (Windows Release executable: `build/win-integration/Release/banjo_workshop.exe`). Collect a material, review a sphere design and its cost, Build, then Run. With an authenticated Codex CLI on PATH, Ask assistant automatically requests a design in the background. Use `--assistant-exe` for an explicit executable path or `--assistant manual` for the earlier file bridge. The [assistant checkpoint](docs/assistant-checkpoint.md) documents controls, live checks and limits. [The creator guide](docs/creator-checkpoint.md) includes the file contract, saved-world behavior, supported limits and three-material CLI fixtures.

## Build and watch it

An experimental [conservative coupled reference](docs/conservative-reference-checkpoint.md) is available through `banjo_solver_probe`. Its [global Newton/GMRES solve](docs/elastic-newton-checkpoint.md) now advances the full isolated glass lattice at 2 ms and 1/240 s with strict conservation checks. Larger steps, runtime cost and contact/material integration remain unresolved. The default viewer still has the conservation defects described above.

The [coupled plane-support update](docs/coupled-support-checkpoint.md) also converges for full-glass floor impacts. Its timestep sweep exposes numerical impact-phase loss and unconverged rebound, so this reference is not yet a reliable material collision model or the viewer's solver.

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

To export per-tick mechanical diagnostics and enable optional active-stage sampling, run `banjo_headless --audit-csv run.csv`. Add `--isolated --target-speed 1` for a zero-gravity, unsupported run with a moving/spinning target; `--voxel-size` selects cell size in meters. On Windows with the Visual Studio generator, executables are under the build directory's `Release` folder. See the [stage checkpoint](docs/material-stage-checkpoint.md) for commands, tolerances and interpretation: successful handoff does not establish full-system conservation.

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
| `M` / `T` / `S` | Cycle striker / target / support material, then reset |
| `[` / `]` | Change support slope, then reset |
| `G` / `V` | Cycle gravity magnitude / direction, then reset |
| `L` | Cycle rolling spin, zero spin, backspin and overspin, then reset |
| Right mouse drag | Orbit the camera |
| Mouse wheel | Zoom |

The motion panel measures actual contact-point slip. The time/tick readout makes pause, single-step and reset observable. Short key taps are consumed from the event queue even when press/release occur between frames.

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

### Source registration check

A source file that no CMake target lists is never compiled, so it never fails and its tests never run. This guard catches that before it reaches a build:

```bash
python scripts/check-source-registration.py
```

It compares the sources on disk under `src/` and `tests/` against the `add_library`, `add_executable` and `target_sources` argument lists in every `CMakeLists.txt` and `.cmake` file, and exits non-zero on any file that no target builds. It needs no compiler, no configured build directory and no third-party packages. CI runs the same command as the `source-registration` job in `.github/workflows/ci.yml`.

Sources that are deliberately committed without being built are listed in the `INTENTIONALLY_UNBUILT` allowlist at the top of the script, each with a reason citing the `docs/` note that justifies it. The script prints that list on every run, and fails if an entry becomes stale or its file is added to a target, so an intentional exclusion stays visible rather than silently permanent.

## What is implemented

- Procedural solid-sphere material sampling with partial boundary-cell volume
- Resolution-compiled brittle material parameters
- Horizon bond lattice with deterministic material variation
- Thread-safe Jolt contact translation into engine-neutral impact events
- Energy-based activation rather than material-name interaction tables
- Rigid-to-material transfer of position, linear velocity, and angular velocity
- Sensor-deferred activation and experimental two-way sphere/material contact; the runtime synthetic pulse is disabled
- XPBD-style brittle bond deformation and progressive damage, including local tension/compression/shear screening
- Connected-component discovery from surviving bonds
- Exposed voxel-face surface generation with internal faces removed
- Sampled convex collision proxies for large and small components
- Material-derived fragment mass, center of mass, inertia, and velocities
- Batched fragment creation in Jolt using supplied mass and inertia
- Lightweight debris fallback for components beyond the rigid-body budget
- Interactive 3D viewer and deterministic CI screenshot capture
- Material/surface selection, tilted support planes and independent gravity vectors
- Analytical scenario projection/CSV caching and prototype material-outcome serialization (not automatic fracture playback)

## Current boundaries

This is still a physics laboratory, not yet the publishing platform:

- Active material exchanges impulses with the finite-mass striker through an experimental sphere/point contact solver. Finite-cell spin is retained, but full-system conservation and fracture-work accounting remain incomplete. Numerical correction changes angular momentum; removed spring energy is not validated fracture work.
- Active voxels use a support-plane approximation with footprint checks. Arbitrary Jolt-shape collision, self-contact and robust support-load detection remain work.
- The fracture model is visually useful but not yet calibrated across multiple resolutions against laboratory glass data.
- Surface meshes are block-style exposed voxel faces. Smoothing and crack-surface material treatment are future rendering work.
- raylib is a quick visual shell. The simulation and fragment geometry layers do not depend on raylib, preserving the planned path to a production SDL3/Dawn/WebGPU renderer.
- General material/scene JSON examples remain authoring contracts. The separate creator schema has strict validation and loading for intact sphere recipes, inventory and rigid state; arbitrary geometry/laws and full world packages are not implemented.

See the [master plan](docs/project-master-plan.md), [development status](docs/development-status.md), [runtime architecture](docs/architecture.md), and [acceptance-gated roadmap](docs/roadmap.md). Historical prototype descriptions are not evidence that every planned behavior is implemented.
