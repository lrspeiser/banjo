# Selected-object rebuild and reclamation checkpoint

Code and all five real provider trials: **`14bb0b760f43ee500576a8624a5205a78365e4f4`**, local branch `codex/physics-foundation`. Not pushed or merged into main. Review date September 4, 2026 Pacific / September 5 UTC. The later documentation commit also tightens the reproducible runner's placement/orientation/rest checks; the saved provider outputs were checked against those conditions without making another model call.

## What works

The shared creator API, CLI and workshop now support selecting an existing object, previewing a replacement with its recoverable material, rebuilding that identity, and reclaiming its material. Rebuild preserves the object ID and original creation-request identity, advances its authoring revision, and records before/after recipes, states, allocations and actual solver mechanical totals. History retains removed-object receipts. New IDs are never reused within a saved world.

The preview distinguishes **reused material, additional free stock and returned material** by original lot. Changing substance returns the old substance to its lot and draws the new substance from a collected lot. The chosen object's geometry is excluded from its own placement test; other objects remain obstacles. Missing/stale target revisions fail. Replay checks include the original operation, target/revision and recipe; replay after reclamation neither resurrects an object nor changes inventory a second time.

The assistant receives a selected object ID/revision and the free stock plus that object's recoverable matter, counted once. It proposes only a replacement recipe. The application independently recompiles and checks it before applying it. Manual and automatic workshop proposals use the same context builder. The real provider remains the existing Windows Codex CLI adapter with saved login, structured responses and disabled tools. Its actual default model identifier is not reported in the captured events; no specific model is claimed.

World format 3 adds operation history, object revisions, the monotonic ID counter and the explicit `intact-return-100pct-v1` authoring policy. Known format-1/2 worlds import as identified baseline records; unknown earlier histories are not invented. The loader checks history ordering/identity, allocations, active definitions and mechanical-record consistency. No exact continuation of solver contact/sleep caches is promised.

## Authoring and energy boundary

Rebuild/reclaim are **intact authoring operations**, not physical manufacture or fracture. A replacement takes its recipe's placement and initial motion, which can reset a moving object to rest. Before/after mechanical quantities expose that discontinuity; they do not supply a work source or prove conservation. Full material return is a declared sandbox policy, not damage-aware salvage.

The workshop visibly says energy is not modeled. The API now explicitly advertises energy-limited fabrication, manufacturing and damage repair as unsupported. A real request constrained to a 10-joule fabrication budget returned a clarification and applied nothing. The [energy-system requirement](energy-system.md) remains open: inventory reference states, source stores, process work, power/capacity, atomic material/energy receipts and calibrated interface/constitutive laws are still needed.

Publication builds a private complete rigid world and swaps it into place only after body construction, inventory checks, history and saved-document limits succeed. This preserves failed-operation state, but reconstructs contact warm-start and sleep caches for the world. Unrelated object definitions and snapshots and the simulation clock are preserved in the tested cases; future trajectories are not claimed bit-identical. Success is still an in-memory publication followed by a separate save; crash-durable acknowledgement remains an API task.

## Three-material evidence

Each separate trial begins with one collected 10 kg lot, a 9.9 kg sphere, 0.1 kg free stock and 120 ticks of physical motion. The model is asked to rebuild the selected sphere into a solid 8 × 6 × 10 cm block at rest, aligned with the 10-degree concrete ramp. The replacement therefore requires target-material recovery for all three substances. Placement, dimensions, material, orientation and initial motion are checked. The accepted block runs for a further 240 ticks and is resting in each saved inspection.

| Substance | New/reused mass, kg | Returned from old object, kg | Free stock after rebuild, kg | Old kinetic energy, J | New initial kinetic energy, J | Provider time, s |
|---|---:|---:|---:|---:|---:|---:|
| Glass | 1.2000 | 8.7000 | 8.8000 | 2.175423 | 0 | 10.290 |
| Oak | 0.3360 | 9.5640 | 9.6640 | 1.940709 | 0 | 10.291 |
| Iron | 3.7776 | 6.1224 | 6.2224 | 2.166164 | 0 | 10.755 |

Old spheres have equal mass and therefore different radii. This intentionally stresses resource reuse; it is not a same-geometry rolling comparison. The new blocks have identical dimensions/initial conditions, with density-derived mass differences. The earlier [equal-volume sphere/box experiments](shape-checkpoint.md) remain the common-condition shape baseline.

All three accepted worlds retain one object with ID 1, revision 2, and a rebuild receipt at tick 120. Reclaiming it returns the stock to 10 kg. Replaying the earlier rebuild, reclaim and creation requests leaves no active object, exactly three history records and the same tick 360. The source world file remains unchanged by the probe.

Two additional real requests deliberately remain unsupported: a functioning hinged door (7.598 s), and energy-accounted construction within 10 J (6.804 s). Both return `clarification` with a null recipe and no applied-world output. The door response identifies both missing hinge mechanics and uncollected metal; collecting metal alone would not enable a hinge. These five specific prompts do not constitute broad semantic/model reliability evaluation.

## Verification and reproducibility

- Windows Release full build succeeds; **all 15 CTest executables pass in 11.71 s**. The creator suite includes glass/oak/iron rebuild/reclaim, cross-substance ledger checks, untouched-object snapshots, stale/replay rejection, known-world migrations, history tampering and budget rollback. Assistant tests cover selected recovery context and stale/missing/reclaimed targets alongside existing proposal, cancellation and process-boundary checks.
- A 256-operation create/reclaim sequence completes in **1.08248 s** inside the creator test and serializes to **608,769 bytes**. This is one bounded local microbenchmark, not a percentile/service throughput guarantee. Limits remain 64 active objects, 256 authoring records and 1 MiB saved worlds. Exhaustion rejects another operation before publication.
- Actual float-solver mechanical records are checked against serialized analytical mass/state within `2e-6 × max(1, |expected component|)`. This is a loader consistency tolerance, not a conservation claim or a fabrication-energy tolerance. Inventory/compiled mass checks retain their `1e-12` scaled tolerance. Existing physics tolerances were not widened.
- Automated revision capture succeeds with normal process exit. It shows completed glass/oak rebuilds and an iron replacement preview; it is a seeded fixture, not a screenshot of mouse-driven LLM creation.
- The new normal workshop is launched with a saved six-object fixture and confirmed live. **Normal new-control verification remains pending.** Native inspection returned `foreground window did not report a process id`; refreshing the returned window and activating/retrying produced the same error. No click/keyboard verification is claimed from capture or from a live process alone. The old owned workshop was intentionally stopped for the rebuild; the separate original-main laboratory was left untouched.

Reference environment: Windows 11 Pro 26200, Intel Core Ultra 9 285K, RTX 5090 / NVIDIA 580.88, OpenGL 3.3, VS 2022 MSVC x64 Release, CMake 4.1.2, Jolt 5.6.0 and raylib 6.0. Main's `SUPPORT_CUSTOM_FRAME_CONTROL=OFF`, `SUPPORT_BUSY_WAIT_LOOP=OFF` and `USE_STATIC_MSVC_RUNTIME_LIBRARY=OFF` remain in the build cache. No Linux/macOS, cross-GPU determinism or remote-CI claim is added.

From the development checkout, use:

```powershell
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
python scripts/run-revision-check.py --out build/revision-check-new
build/win-integration/Release/banjo_workshop.exe --workspace build/revision-preview --capture build/revision-preview.png --capture-layout revisions --frames 5
```

The real-provider runner requires an existing Codex login and refuses to reuse its output directory. It records prompts, commands, request/response/event files, elapsed times, accepted worlds, reclamation/replay results and source hashes. `--cases glass oak iron door energy` is the default; subsets are available for a focused rerun. The API also exposes `preview_rebuild`, `rebuild` and `reclaim`, with `object_id` and `expected_revision`; mutations additionally take `request_id`, and rebuild takes a recipe.

## Next work

Finish normal-control verification when the native helper can inspect the window, while continuing available platform work. The [API review](api-platform-review.md) identifies the next reliability gaps: a versioned command/result contract, machine-readable errors, request receipts for every retryable mutation, explicit ordered-partial batch semantics and durable acknowledgement/recovery. Then expose bounded functional tests and measured assistant feedback. Establish the energy inventory/reference-state and process contracts alongside this work, without adding invented physical costs.

Full detailed-material conservation, fracture-work/calibration, work-accounted friction, local activation, additional shapes/assemblies and publishing remain open. This checkpoint does not repair the default viewer's correction energy or make the slow conservative reference real-time. The [40-row scorecard](mechanics-scorecard.md) and full project goal remain active.
