# Platform SDK and example laboratory checkpoint

Source: `ecffdf5`, local `codex/physics-foundation`; not pushed or merged to main.

## Product and architecture

The engine/publishing platform is the product. Games call the same validated runtime used by the laboratory. The LLM authors inspectable declarations and tests; it is not in the physics tick. Inventory, crafting, energy availability and progression exercise engine APIs as a first customer and must not be dependencies of the physics runtime.

Implemented dependency boundary: `banjo_platform` links the rigid runtime and `banjo_material_lab`, with no CreatorWorld, inventory, model API or raylib dependency. The existing crafting bowl uses the same extracted bowl geometry/material library. The new visual client alone links raylib.

The first package contract supports an explicit choice of `rigid-v1` (spheres and oriented boxes) or `bonded-reference-v2` (coarse spheres and experimental glass fracture), optional finite bowl, gravity, glass/oak/iron/concrete, initial pose/velocity/spin and declared capabilities. All declarations are validated before a solver is allocated. Unknown fields, incompatible ABI, unsupported capabilities/shapes, non-SI units, duplicate IDs, invalid quaternion/spin, initial object overlap and object/call limits reject. This is a bounded initial-scene package, not full arbitrary-world publishing or a persisted damaged-world checkpoint.

## Game-facing C++ API

Link target `banjo_platform`; include `platform/PlatformWorld.hpp`.

```cpp
auto world = banjo::PlatformWorld::load(package_json);
auto result = world->step(1); // one package-defined fixed step
if (!result.error.empty()) {
    // Stop this instance and inspect diagnostics; reload to recover.
}
auto instances = world->renderInstances();
auto report = world->reportJson();
```

The host owns scheduling and threading; calls on one instance must not overlap. Independent objects return stable package IDs, geometry and world pose/velocity. Reference rendering returns actual cells and current component identifiers; component numbers are snapshot connectivity labels, not persistent fragment lineage. Rendering does not determine physics. `packageJson()` returns the initial authoring package, not the current simulation state.

A failed reference advance rolls back that interval. A failed rigid update may have partially changed internal state; the report sets state_valid false, faults the world and prevents further stepping. The host must discard/reload it, not treat the last successful tick count as an accepted current physical state. There is no rigid-world transactional rollback claim at this API boundary.

Byte limit: 4 MiB. Rigid limit: 4096 bodies; reference limit: 12 bodies/228 cells. Calls allow 1–240 steps with a package-selected lower ceiling. Rigid timestep range: 1/4800–1/60 s; reference additionally caps at 5 ms. These are admission/work-count bounds, not hard wall-clock deadlines or a certified untrusted-code sandbox. Near-contact placement is accepted; support penetration screening, complete dependency/content locks and scene-level conditioning remain future work.

Reports include authoring inputs, ABI, position precision, mass, motion, backend limits, reference fracture/energy diagnostics and step timing. The CLI adds compiler and package-load timing. P50/P95 retain the last 4096 samples in bounded storage; total/max cover the whole run. Step timing includes event draining, excludes package loading, rendering, report generation and OS scheduling outside the measured call.

## Tools and examples

```powershell
build/win-joint-double/Release/banjo_platform_cli.exe --capabilities
build/win-joint-double/Release/banjo_platform_cli.exe --validate assets/platform/01-bowl-three-materials.json
build/win-joint-double/Release/banjo_platform_cli.exe --run assets/platform/01-bowl-three-materials.json 240
build/win-joint-double/Release/banjo_platform_lab.exe assets/platform
python scripts/platform_matrix.py --exe build/win-joint-double/Release/banjo_platform_cli.exe
```

CLI stdout is structured JSON; errors are nonzero exits. The visual client supports Run/Pause, package reset, next/previous example, report and image export. Reference stepping runs on a worker with the last completed render state retained, so the window remains responsive while simulation may advance slowly. No reference replay is advertised as live real-time physics.

| Packaged examples | Coverage established in this checkpoint |
| --- | --- |
| 01–06: bowl, drop/rebound, spin, tilted oak bowl, boxes/spheres, free flight | Three-material executable smoke coverage; analytical free-flight check; no full bounce/friction/shape calibration claim |
| 07–12: glass/oak/iron at 2 and 10 m/s per body | 10 ms reference advances; glass gentle intact, glass strong 148 broken links; oak/iron retain bonds because their failure laws are unsupported |
| 13–15: isolated rolling | 0.3 s, all three translate/rotate without fracture; full reference energy budget checked |
| 16–17: 100/1000 moving rigid bodies | 50/500 independent colliding pairs across three materials; callbacks required; performance load fixtures, not dense fracture or calibrated contact proofs |

## Measured results

Windows 11, Intel Core Ultra 9 285K (24 cores/logical processors), MSVC Release, double-position build. Final 17-case matrix passes. This is an initial single-run benchmark with other desktop applications present, not a statistically characterized performance guarantee.

For 1000 moving rigid bodies, 240 steps advance 1 simulated second, produce 500 contact callbacks, and consume 39.7961 ms total measured step time (25.13 simulated seconds per solver wall second). P95 is 0.441 ms per 1/240 s step, max 2.715 ms, package load 8.6521 ms. Rendering and reporting are excluded. The earlier run was 46.103 ms; retain this variability. Callbacks are not one-to-one certified physical impacts and may be speculative.

Detailed reference cases remain below real time. They are deliberately separate from rigid scale claims. No new automatic activation/coarsening algorithm or GPU acceleration was implemented in this checkpoint.

Regression: three affected suites pass (bowl, bonded bowl, platform), 41.69 s. Final platform-only test rerun passes after additional spin validation and timing storage changes; all 17 examples rerun successfully. The older crafting application and inventory allocations are preserved. Native Run/Pause shows advancing physics and 60 displayed FPS in the small rigid scene; this is a spot observation, not a frame-time percentile benchmark. Native Reset, Next example and structured report export also verified. Existing/native and new package clients are separate windows.

## Next implementation milestones

1. Contact-to-damage evidence: IDs, approach velocities, local load/stress and time-aligned fracture records; distinguish support artifacts from ball impacts.
2. Physics activation: conservative screening plus uncertainty; one contact owner; accounted rigid-to-local-material transfer; propagation-aware patch expansion; damage-preserving return to rigid fragments.
3. Broaden the same package conformance matrix: frictionless sliding, measured slip/backspin/overspin, off-center impact, moving/finite supports, repeated damage and fragment landing, shapes/composites, material coupons, hinges and fastener failure. Do not claim a law from a menu or example filename.
4. Runtime scale: spatial/independent-group scheduling, sleeping, sparse local storage, shared compiled geometry/material data, admission limits and declared overload behavior. Measure end-to-end frame-time percentiles, active cells, fragments, memory and activation spikes at 100/1000+ bodies.
5. Publishing: full dependency/content identity, portable compiled packages, live-state persistence/migration, rendering adapters, script/LLM bindings, trusted law plugins, sandboxed behaviors, distribution/remix and multiplayer authority. Preserve all 40 mechanics/platform scorecard rows; no original gate is removed.

The platform is not finished. This is an executable SDK boundary and a measured conformance laboratory on which the near-real-time material runtime can be built.
