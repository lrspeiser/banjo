# Oriented box creator checkpoint

Latest tested code: `c10afc8afdcd38c670795e93548bd37932f3a70a`, after geometry implementation `d5d469dd1cdc3d839898176002e35466534a5b1a`, on local `codex/physics-foundation`. Changes are not pushed or merged. The shared creator/compiler, CLI, automatic Codex adapter and workshop now support homogeneous intact **solid boxes as well as spheres**. The full platform goal remains active.

All **15 Windows CTest executables pass in 9.91 s**. A six-object capture and headless comparison pass at the latest source. Four real provider trials at `d5d469d` produce glass/oak/iron blocks or an unsupported-door clarification. The final follow-up changes only missing-contact diagnostics and their test/UI wording. **Normal interactive testing of the new box controls remains pending** because the Windows Computer Use helper returned `foreground window did not report a process id` even after refreshing the returned window handle and trying the rebuilt window. The process itself was confirmed live; this is not evidence of an application crash or successful input verification.

## Shared geometry and authoring contract

`RigidPrimitive` represents occupied homogeneous matter. Spheres use radius; boxes use full object-local X/Y/Z lengths. Box volume is xyz and mass is density × volume. The local center of mass is the geometric center. Its inertia tensor is diagonal in the object frame: Ixx = m(y²+z²)/12, Iyy = m(x²+z²)/12, Izz = m(x²+y²)/12. Rotation produces the full world tensor R I Rᵀ, including off-diagonal terms. Tests independently check the analytical mass/diagonal values and the actual float mass/world inertia accepted by Jolt.

Schema-2 recipes include `placement.orientation_wxyz`, a unit quaternion in world coordinates. Box `dimensions_m` must each lie in 0.025–1 m; sphere radius remains 0.025–0.5 m. The strict tagged shape object rejects mixed sphere/box fields. Version 1 retains its original sphere-only fields; authored orientation and boxes require version 2. Both shapes share collected material allocation, the 64-object budget, initial speed ≤5 m/s, spin ≤50 rad/s, request replay identity and transactional creation.

Placement computes the oriented shape extent along each ramp axis and raises its lowest point by the requested clearance. The whole initial footprint must fit the 16 × 6 m support. Preview checks use sphere/sphere distance, exact sphere/oriented-box closest points and oriented-box separating axes with a stated 1 mm authoring clearance. Thin nearby boxes can fit without being replaced by enclosing spheres. These checks gate authoring; Jolt owns subsequent collisions.

Jolt receives a true box with zero convex rounding radius and the material-derived mass and full local inertia. Gyroscopic force is enabled for asymmetric free rotation; linear-cast motion quality is enabled for boxes. That setting alone is not broad rapid-contact validation. Existing catalog friction/restitution combination remains in use. Sphere rolling resistance is not applied to boxes. No material-name outcomes, forced rolling, manufactured launch impulses, deformation or fracture were added. A solid box is a rectangular block, not a hollow container.

The model uses the same schema and compiler. It receives full dimensions, orientation/support-frame guidance, collected inventory and capability limits. Build remains separate from a proposal. The native probe's explicit `--apply` option creates a validated design, runs one second and saves the resulting world. Deterministic tests make no model calls.

## What the comparisons establish

The [six-row comparison](evidence/shape-comparison.csv) holds **occupied volume and per-material mass fixed** between each sphere and box. Sphere radius is 0.04 m; box full dimensions are 0.08 × 0.06 × 0.05585053606381855 m. Each pair starts at rest on the same 10° concrete ramp with 2 mm clearance and zero spin. Boxes begin face-aligned with the ramp. The distinct lanes prevent inter-object contact. All use dt = 1/240 s for one second. Across substances, catalog coefficients and density differ; this is not a calibrated-material comparison.

| Material | Mass of each shape (kg) | Sphere speed at 1 s (m/s) | Box speed at 1 s (m/s) | Result |
|---|---:|---:|---:|---|
| glass | 0.670206433 | 1.118184546 | 0.000000000 | Sphere rolls; box rests on its face |
| oak | 0.187657801 | 1.057738043 | 0.000000000 | Sphere rolls; box rests on its face |
| iron | 2.109809850 | 1.111398211 | 0.000000000 | Sphere rolls; box rests on its face |

Each sphere has measured slip below 0.02 m/s; each box has at least three near-support vertices and moves less than 5 mm while settling. All three lot ledgers close to 1e−12 kg. This demonstrates a supported shape effect, not all tipping/sliding/contact regimes.

Additional creator tests retain all three materials and check unequal box dimensions, a 45° orientation with nonzero world inertia cross terms, density-independent free fall, rotated placement bounds, actual corner overlap, replay/error atomicity, box persistence and post-reload support. Off-center sphere/box and box/box collisions give reactions and box spin while bounding total linear/angular momentum residuals and preventing kinetic-energy growth in these isolated runs. The earlier different-material sphere collision tests remain.

For an asymmetric free box with initial angular velocity (2,3,4) rad/s, zero gravity, dt 1/240 s and duration 0.5 s, observed relative angular-momentum errors were **0.00388428, 0.00388725 and 0.00388794** for glass/oak/iron. Relative kinetic-energy errors were **0.000110977, 0.000112022 and 0.000113828**. Both are below the declared 0.005 bound. These measured Jolt integration errors are not exact conservation or a timestep-convergence proof. Existing physics tolerances were not relaxed.

## Real automatic block proposals

The three live prompts specify a solid 8 × 6 × 10 cm block, face-aligned with the same ramp, tangent −2 m, lane 0, 2 mm clearance and zero initial motion. All returned the correct dimensions, material, schema and quaternion. The compiler independently derived mass and inertia; after one second each block was resting with its material ledger intact.

| Request | Result | Compiled mass (kg) | Remaining collected mass (kg) | Observed request/probe time (s) |
|---|---|---:|---:|---:|
| glass block | Proposal; created; resting | 1.200000 | 8.800000 | 10.6684 |
| oak block | Proposal; created; resting | 0.336000 | 9.664000 | 11.3174 |
| iron block | Proposal; created; resting | 3.777600 | 6.222400 | 11.2950 |
| Hinged oak door | Clarification; no object | — | 10 | 7.3194 |

The door reply identifies unsupported hinges/assemblies and suggests a free solid panel as an alternative, but returns **null recipe** and creates nothing. Adding box geometry did not silently turn that door request into a working hinge. This is one negative semantic example, not a guarantee against every misleading prompt or model explanation.

[Provider results](evidence/shape-assistant.csv) include token counts and full-precision compiled inertia. The three positive requests ran concurrently; the door ran separately. Times include startup, provider response and the short physical probe, not a service latency percentile. Codex CLI 0.153.3 used the existing ChatGPT login and default model with user config ignored. The JSONL stream does not identify the model ID. As in the [assistant checkpoint](assistant-checkpoint.md), execution helpers are disabled; no tool executions appeared in these four traces. Raw requests, responses, events and accepted worlds are retained.

## Diagnostics and persistence boundaries

The box readout uses RMS tangential velocity v + ω×r at vertices within 3 mm of the finite ramp's top face. Near-zero translation/spin is resting; nonzero slip is sliding/slipping; supported rotation with low slip is reported as rotating on support. It never applies a sphere no-slip formula to boxes or writes a velocity. Missing top-support samples produce **no top-support sample** and null slip in JSON; the UI says **contact not measured**. Edge/side manifolds and arbitrary body/body contact diagnostics remain unmeasured. Missing samples must not be treated as proof of airborne motion. Full support impulse/work accounting remains open.

World format 2 pins `object_compiler=2` and `jolt-5.6/banjo-rigid-primitives-v2`. It stores shape/orientation recipes, inventory allocations, IDs and rigid states; compiled tensors are recalculated and checked against matter. A deliberate compatibility reader accepts only the exact known format-1 sphere signature and schema-1 recipes, then saves format 2. The actual previous glass UI world migrated with **only the version/signature fields changed**; all recipes, quantities, IDs, ticks and saved motion were identical. Changed material/runtime signatures still reject. This does not establish portable damage history, arbitrary migrations, warm-start cache restoration, bit-exact restart or multiplayer authority.

## Reproduction and current UI status

Windows 11 Pro 26200, MSVC 19.44.35228 x64 Release, CMake 4.1.2, SDK 10.0.26100, Jolt 5.6.0, raylib 6.0; Intel Core Ultra 9 285K and RTX 5090 / NVIDIA 580.88 / OpenGL 3.3. Frame-control, busy-wait and MSVC runtime fixes remain preserved. Build and tests:

```powershell
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
& ./build/win-integration/Release/banjo_creator_cli.exe --commands assets/creator/three-material-shapes.json --save build/shape-world.json
& ./build/win-integration/Release/banjo_workshop.exe --workspace build/shape-capture --capture build/shape.png --capture-layout shapes --frames 60
& ./scripts/run-assistant-check.ps1 -Shape box
```

The last command makes real authenticated model requests for glass/oak/iron and a door, using fresh output folders. The wrapper's new box branch was separately exercised with `-Cases oak`; that wrapper check is not the three-material physical comparison.

The final automated capture shows all six correctly rendered sphere/box objects and completes normally at one second. The workshop adds a shape selector, dimension-axis selector, 5 mm size controls and orientation presets (world-aligned, ramp-aligned, ramp +45°). Preview and rendering use the authored quaternion. The rebuilt normal process launched successfully and remains available, initially paused. **The new controls still need ordinary interactive verification**, including typing a box request, review/build, dimension/orientation editing, run/pause and save/reload. Earlier sphere UI verification does not cover those additions; capture is not a substitute.

Next: complete that UI check when native access works, then implement safe object replacement/reclamation with explicit material reuse/waste and preserved request identity. Continue cylinders/hollow shapes and wider sliding/tipping/edge-contact tests through this same path. The default activation/contact/fracture conservation defects, detailed-reference friction/work integration, calibration, assemblies and publishing gates remain open in the [scorecard](mechanics-scorecard.md) and [roadmap](roadmap.md).
