# Creator workshop checkpoint

Tested source: `9cd9197bb99492b1a834622cd87d35302468c4dd`, local `codex/physics-foundation`. This is a working first application slice: collect a world material, obtain an LLM proposal through a manual file bridge, review the independently compiled quantity, build an intact rigid sphere, run it and save the inventory/object state. The automatic in-app model connection, modification/reclamation of existing objects, additional shapes, general materials and publishing remain open. No push or merge into main is included.

## What now shares one path

`CreatorWorld` owns inventory, recipe validation, compilation, creation and a Jolt world. `banjo_creator_cli`, `banjo_workshop` and the creator regression tests use it. Recipes declare schema version, geometry, material, physics, placement and initial motion using explicit SI field names. Solid-sphere volume is analytical: V = 4πr³/3, mass = catalog density × V and isotropic inertia = 2mr²/5. The intact sphere uses that mass in Jolt. This is not the sampled lattice approximation used by the detailed material laboratory.

The starter world contains uncollected 10 kg lots of glass, oak and iron. Picking up an existing lot retains its ID, material and provenance; the collection command cannot set a quantity. Preview checks inventory, supported geometry/law, placement and budgets without spending material. Creation prepares allocations and object state before insertion and commits both together after successful insertion. Replaying a request ID with the same recipe returns the existing object, even after it moves or is saved/reloaded; conflicting recipes reject. No automatic refund, replacement or reclamation is implemented.

The runtime is explicitly `rigid-v1`: intact spheres, catalog contact friction/restitution and existing rolling-resistance torque, a finite 16 × 6 m concrete support at 10 degrees, and gravity (0, −9.81, 0) m/s². It advances at 1/240 s. It has no deformation, fracture, wood grain, metal plasticity or assemblies. Jolt owns each rigid clock/contact; the slower conservative material reference is not called on these bodies. Creating initial motion is an authoring operation, not a simulation of manufacturing or of the work required to launch an object.

## Reproduce the application

Build the existing CMake project. `BANJO_BUILD_HEADLESS` enables the CLI, `BANJO_BUILD_LAB` enables the workshop, and runtime tests include the creator suite. The new structured-input dependency is nlohmann/json 3.12.0 pinned to `65ee68451d8eb2b5f3a30b410476ab83deb3289b`; see its [official CMake integration](https://json.nlohmann.me/integration/cmake/) and [release](https://github.com/nlohmann/json/releases/tag/v3.12.0).

Windows commands from the repository root after configuring the Release build:

```powershell
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
& ./build/win-integration/Release/banjo_workshop.exe --workspace ./build/my-workshop
```

The workshop defaults to `workshop-data` beside its executable if no workspace is supplied. Use a writable workspace and only one workshop process per saved world. Collect a material, choose material/radius/lane or obtain a proposal, inspect its cost, Build, then Run. Space pauses; Step advances one physics tick; right-drag orbits, wheel zooms, and F/Follow object tracks the last object. Save writes inventory, recipes and current motion together. Collection/creation and normal exit also save; motion is not saved every tick. Run changes simulation time; it is not a guaranteed wall-clock rate under load.

The headless three-material fixture and its idempotent replay use the same creator path:

```powershell
& ./build/win-integration/Release/banjo_creator_cli.exe --commands assets/creator/three-material-ramp.json --save build/creator-demo-world.json
& ./build/win-integration/Release/banjo_creator_cli.exe --load build/creator-demo-world.json --commands assets/creator/replay-three-material-ramp.json --save build/creator-demo-replayed-world.json
```

The first file collects, previews and creates glass/oak/iron spheres, advances 240 ticks, then inspects. The second replays all three creation IDs and inspects. Its saved world must equal the first saved world. These are declared fixtures, not LLM-generated evidence.

## The LLM boundary and observed exchange

Ask assistant writes `request-<request_id>.json` into the workspace, containing the prompt, inventory/world/capabilities, an example recipe and expected response filename. An external assistant reads it and writes `proposal-<request_id>.json` with exactly `request_id`, `explanation` and `recipe`. The workshop checks the pending ID, parses the bounded recipe, independently validates/compiles it and pauses for the user to review/build. It does not invoke a model endpoint itself. Cancelling ignores the pending response and spends nothing. Manual recipe edits do not constitute modifying/reclaiming a built object. A pending assistant response can replace an unbuilt manual draft; cancel the pending request before changing that draft.

Actual observed manual Codex exchange, separate from the fixtures:

- Prompt: “Use some of my wood to make a ball that rolls down this ramp.” Only the 10 kg oak lot had been collected.
- Codex read request `workshop-1788583693349389-2` and authored an oak sphere of radius 0.08 m, initially at rest, tangent −2 m and clearance 0.002 m. The response explained its intact-rigid limitation.
- The application accepted the proposal, independently derived a cost of **1.5012624093954423 kg**, and created body 1 on Build. Remaining oak was **8.498737590604557 kg**. Glass and iron remained uncollected, 10 kg each.
- Normal interactive Run produced visible rotation/translation with a measured **1.167 m/s speed and 0.002 m/s slip** at the observed 80.26 s world timestamp. The world clock had already advanced while waiting for authoring input; this is not an 80-second rolling trial. The object later left the finite ramp and was classified airborne. Pause, Save and normal close succeeded.
- Request, accepted proposal and the post-motion saved world are preserved in the evidence bundle. This was a real proposal authored by the current Codex model through a manual file handoff, not an automatic in-app model/API integration.

## Validation and comparative results

Windows 11 Pro build 26200, Intel Core Ultra 9 285K, RTX 5090 / NVIDIA 580.88, MSVC 19.44.35228 x64 Release, Windows SDK 10.0.26100, CMake 4.1.2, Jolt 5.6.0 and raylib 6.0/OpenGL 3.3. Full build passed; **all 14 CTest executables passed in 9.86 s**. This is local Windows evidence, not a new Linux/macOS or remote-CI claim.

New creator tests cover inventory/transaction rejection and replay, three-material free fall, three-material rolling, finite glass–oak/glass–iron collisions, persistence/input rejection and coexistence of multiple Jolt worlds. The CLI fixture passed all 11 commands; replay returned the same three IDs and unchanged saved world. No tolerance in the existing material tests was widened.

Identical radius 0.06 m and initial rest; each lot starts at 10 kg. Rolling uses the same 10-degree concrete ramp, 1/240 s steps, 1 s duration and separated lanes. Free fall uses a flat support with 1.5 m clearance, 0.2 s duration; the spheres have not reached the floor.

| Material | Derived mass (kg) | Remaining (kg) | Free-fall vertical velocity (m/s) | Ramp speed at 1 s (m/s) | Contact slip at 1 s (m/s) |
|---|---:|---:|---:|---:|---:|
| Glass | 2.261946711 | 7.738053289 | −1.962 | 1.11563 | 0.001573588 |
| Oak | 0.633345079 | 9.366654921 | −1.962 | 1.05547 | 0.001621150 |
| Iron | 7.120608245 | 2.879391755 | −1.962 | 1.10885 | 0.001552896 |

The [machine-readable creator comparison](evidence/creator-materials.csv) records the same three-material CLI fixture, compiled quantities and measured motion at 1 s.

Mass/inertia/inventory assertions use 1e−12 absolute tolerance; persisted allocation checks scale by max(1, mass). Jolt's float mass/geometry storage is not exact double-precision representation. Free-fall velocity tolerance is 1e−5 m/s, position is 0.005 m for fixed-step truncation, and cross-material position/velocity agreement is 1e−6. Rolling requires downhill speed >0.2 m/s, angular speed >0.5 rad/s and measured slip <0.02 m/s with Rolling classification. These contact coefficients differ by material, so speed differences are not an ideal density-only rolling law or calibrated substance behavior.

Finite collisions use identical 0.06 m geometry, zero gravity, initial velocities ±0.5 m/s and elevated placement for 0.8 s. Both bodies must react, linear momentum residual must be ≤2e−6 × combined mass, and kinetic energy must not exceed its initial value by >1e−6 J. This bounded two-body check does not close the full rolling/support energy ledger or validate all restitution regimes.

## State, input and runtime limits

Only schema 1 spheres and `rigid-v1` are supported. Radius is 0.025–0.5 m, placement must fit the finite surface with 0.002–3 m clearance, initial speed ≤5 m/s and spin ≤50 rad/s. Worlds have at most 64 objects, input documents 1 MiB and 24 nesting levels, and command batches 128 entries; a step command advances at most 2400 ticks. Unknown, missing, duplicate or invalid fields reject; commands do not execute arbitrary code or filesystem actions. Command failures are `ok:false` results while other commands in the same batch may succeed; the whole batch is not one transaction. Malformed documents or file errors exit the CLI with code 1; a valid batch containing individual rejections still exits 0, so inspect `ok`.

World format 1 saves inventory provenance/allocations, stable object/request IDs, accepted recipes, poses, velocities/spins and ticks. Load recomputes mass/inertia and rejects incompatible catalog/runtime signatures or inconsistent material ledgers. The signature is a compatibility guard for this version, not a complete cache key for arbitrary solver state. Same-directory pending-file replacement commits the serialized world together; existing pending saves are preserved for recovery. This is single-writer local persistence, not a signed/untrusted world-package or multiplayer authority protocol. Jolt sleep/contact warm-start caches are not stored, so continuation is not bit-exact and cross-platform determinism is not established. Schema migrations, deletion, inventory refunds, damage and assembly persistence remain open.

Preparing a loaded world exposed process-global Jolt factory/type ownership: initialization now lasts for the process so destroying one world cannot invalidate another. Rigid insertion rolls back on allocation failure before inventory/object publication.

Normal Windows input also exposed a GLFW active-window crash, missed by capture mode: exception 0xc0000005 at `_glfwPollEventsWin32 + 0xe1`. Disassembly and source inspection traced the dereference to the active HWND's `GLFW` property. Attached input queues can expose a window owned elsewhere; resolving only this GLFW instance's window list removes that pointer assumption. `cmake/GuardGlfwActiveWindow.cmake` applies the fix to a generated build copy, preserving shared dependency sources. Normal activation, collection, building, run/pause, save/close and subsequent default-path launch/follow were exercised successfully after the fix. Main's frame-control, busy-wait and MSVC runtime flags remain OFF. The original main viewer was left available.

## Next application checkpoint

1. Connect an automatic bounded assistant adapter to the existing request/proposal contract, with request cancellation, unavailable-capability explanations and retry/revision feedback. Keep model/provider choice outside the physics runtime.
2. Add a second geometry through this same compiler and inventory path, then compare sphere/box or cylinder using glass, oak and iron. Derive the correct mass, full inertia, placement and collision geometry; test rolling versus sliding/toppling.
3. Add safe revisions of existing objects, explicitly accounting for material reuse/waste and preserved history. Do not treat creating another object as a refunded replacement.
4. Continue the separate conservation/friction/activation and constitutive gates. Integrate detailed matter only with clear clock/contact ownership, measured work and usable cost. This small application slice does not repair the default detailed-material energy/fracture defects or complete the platform goal.

See the [creator contract](creator-loop.md), [30-mechanic/10-capability scorecard](mechanics-scorecard.md), [adaptive reference](adaptive-checkpoint.md), [default detailed-path defects](material-stage-checkpoint.md) and [full roadmap](roadmap.md).
