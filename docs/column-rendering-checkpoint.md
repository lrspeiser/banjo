# Sparse terrain rendering and character joining — October 3, 2026

Implementation checkpoint on Windows x64, based on published GitHub main
`bbcd23369c523eb715a739e74849cf97999cd133`. Published implementation:
**`edf82515d9b154ed111f1d1277af6f7c32877717`**, on GitHub main.
The optional material-column terrain remains experimental; smooth remains the
default. R3 remains owner-paused. The broader readability, useful opening,
shared guidance and R4/R5 physical acceptance remain active.

## Changes

Column wall, floor and roof meshes now belong to 32-column render chunks.
Geometry edits invalidate their own chunks and the immediate neighbor halo;
exploration changes invalidate only the owning chunks. Distant meshes are
retained and replaced geometry is disposed. These render chunks are independent
of native collider ownership and change neither cell spacing nor physical laws.
The existing 25 cm tops, material bands and underground openings are preserved.

Unchanged full terrain catchup no longer reconstructs all faces or repaints
the material palette. Exploration compares actual cell visibility, including
equal-count masks with different positions. Top position/color buffers declare
changed ranges. Column tops keep their constant flat normals. The material
texture still uploads through its existing whole-texture update path; this
checkpoint does not measure or claim isolated GPU upload savings.

Bounded browser traces now record terrain construction, CPU render submission,
draw calls, triangles and geometry count. CPU render time includes submission
and any synchronous uploads; it is not GPU elapsed time.

Starting a reference character through the ordinary Menu exposed **The player
could not be saved**. A watched page advances fabrication time between periodic
native world checkpoints. Adding a character previously saved a new profile
beside the older native snapshot, failing the existing paired-time guard.
Character creation now checkpoints first and retains the exclusive world lease
and state lock through profile creation/save. A refused checkpoint leaves no
guest or worker. Persistence validation and stock/energy guards are retained.

The actual watched run subsequently reached its 64-decision budget repeatedly
refreshing an energy transfer: sunlight changed the battery meter after the AI
read it. AI connection/funding now uses the existing identity/rating binding
already supported by the receiver, with a legacy meter-hash fallback. The
receiver still checks current charge, shared power and revision under its world
lock. Pending request arguments remain exact through lost replies and restart.

Sources: `playground/material_appearance.js`, `playground/world.js`,
`playground/ai_player.py`; material and AI regression tests; CMake registration.
No C++ source or native constitutive implementation changed.

## Measured rendering costs

Exact published `bbcd233` renderer versus this renderer, same generated seed-7
19,500-column / 25 cm native packet, shipped Three mesh construction in Node,
eight serial samples per case on this Windows host:

| Measurement | Published whole mesh | Render chunks |
|---|---:|---:|
| Wall/void triangles | 113,872 | 113,872 |
| Full construction | 56.30–95.07 ms | 59.01–95.62 ms |
| One-cell edit construction | 51.10–78.43 ms | 3.01–4.04 ms |
| Chunks reconstructed for that edit | Whole map | 1 of 20 |

The local edit is at column (78,62). Edits at seams additionally rebuild their
affected neighbors. These samples exclude native simulation, WebGL and GPU
work. Initial/full construction did not improve. This is one packet/host with
small serial samples, not a cloud price or cross-device benchmark. Raw local
measurements are retained in ignored `build/column-terrain-preview/` files.

In the actual isolated port-8778 browser, observed watched idle four-second
windows near 60 fps have frame median 16.7 ms, p95 around 16.8–17.3 ms and
CPU render median 0.2–0.4 ms. Startup/reload windows still contain roughly
80–110 ms frames, including 35.7–52.0 ms worst CPU render submissions and
41.7–51.5 ms full chunk construction. Changing camera/frustum changes draw
counts and rendered triangles. These observations establish current costs;
they are not a controlled before/after FPS comparison or GPU-time measurement.

## Verification

Separate `build/agent-column-terrain`, Visual Studio 17 2022,
MSVC 19.44.35228, Release x64, CPU reference, `BANJO_BUILD_LAB=OFF`.
Native products retain the previously verified material-column implementation.
Source registration: 298/298, ten CMake files, zero deliberate omissions.

- Material presentation: 15 checks pass. Full/chunk face records match exactly
  across material, height and void seams; the actual chunk renderer preserves
  distant meshes, disposes replaced geometry and exposes the new seam wall.
  Equal-count exploration relocation and unchanged catchup are tested against
  the shipped functions. Smooth catchup remains covered.
- Smooth/column native material journeys: both pass through the real paid pick,
  sand-to-soil exposure, private Store, independent peer and full server restart.
  Three registered suites pass 17 checks in 37.79 s. No new mass tolerance.
- AI joining: two focused checks pass, exercising both surface modes. The
  uncheckpointed join reproduces the paired-time failure and rolls back;
  ordinary AI creation then saves matching native/fabrication times. A refused
  checkpoint creates neither a guest nor a worker.
- The dedicated `banjo_ai_column_opening_tests` CTest target registers those
  joining checks, advancing-meter/lost-write recovery and the two-map reference
  opening, without launching legacy browser automation. Its registration is
  confirmed; the four methods were executed directly with the same native paths.
- Both column-map reference openings pass in 189.55 s combined. Seed 7 / goods
  seed 851269742: 32 decisions, 111.84 s wall, 40.26 s native. Seed 4 / goods
  seed 1: 30 decisions, 75.17 s wall, 22.21 s native. Both complete the two
  declared chains, learn Gathering by hand and Smelting copper, keep the human's
  journal empty, install two paid personal products and load exact machine
  runtime/ledgers. Local fabrication energy residuals are below 5e-13 J,
  native transfer residual below 8.4e-11 J and oak residual zero. These are
  bounded receiving-ledger checks, not full physical-world conservation. The
  route test preceded the final binding change; the real watched recovery and
  advancing-meter test below exercise that corrected funding path.
- Advancing native source counters before connection/funding, lost stock/
  energy/start/commit acknowledgements, interrupted preview and full Python
  server restarts: the paid AI pick test passes in 13.00 s. It preserves private
  ownership, unchanged peer/shared stock and one installed product. Two existing
  native energy guard checks also pass: current insufficient charge, exhausted
  shared power and altered identity/rating refuse without debit; exact retry
  does not duplicate credit. No increased AI decision budget or weaker guard.
- JavaScript syntax and Python compilation checks pass. CMake reconfiguration
  confirms the dedicated test is registered.

Commands:

```powershell
python scripts/check-source-registration.py
node --experimental-default-type=module --check playground/world.js
cmake -S . -B build/agent-column-terrain -DBANJO_BUILD_LAB=OFF
ctest --test-dir build/agent-column-terrain -C Release --output-on-failure -R '^(banjo_terrain_material_tests|banjo_material_layer_tests|banjo_column_material_layer_tests)$'
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/agent-column-terrain/Release/banjo_live_world_run.exe).Path
$env:BANJO_LIBRARY=(Resolve-Path build/agent-column-terrain/Release/banjo.dll).Path
python tests/ai_player_tests.py AutonomousGuests.test_character_join_checkpoints_advancing_world_before_profile_save AutonomousGuests.test_character_join_refuses_unsaved_world_without_creating_guest -v
python tests/ai_player_tests.py AutonomousGuests.test_reference_explorer_completes_goal_chains_on_both_column_terrains -v
python tests/ai_player_tests.py AutonomousGuests.test_ai_paid_make_uses_own_collected_stock_solar_and_recovers_lost_writes_on_restart -v
python tests/fabrication_energy_tests.py NativeEnergy.test_live_store_binding_preserves_current_limits_exact_debit_and_retry NativeEnergy.test_other_consumers_share_source_power_and_reconnect_cannot_reuse_time -v
```

## Ordinary browser play and remaining gates

The matched isolated preview is
`http://127.0.0.1:8778/world?world=0cc7621ee0de49f9948239e3ee81b960`.
Only that preview was restarted to load the fixes; the owner's port 8771
server and world were untouched. Through Menu → Start character, the reference
explorer joins successfully and the normal watch camera shows collected wood,
a paid equipped pick, actual sand/soil gathering and its private Gathering by
hand achievement. No model calls, free products or manually awarded evidence.
Screenshots are retained under the ignored preview directory.

After the funding fix, a full preview restart and Menu → Resume retain the same
character, its pick and pending build. The work table installs, completing the
first goal of chapter two in eight further decisions. The character then stops
honestly at an exhausted `electric-furnace` copper-ore intake. This long-running
world is not the fresh-map fixture. Supply recovery and a meaningful next action
at that blocker remain required; the UI currently concatenates many unavailable
process prerequisites. Do not describe this watched journey as fully complete.
Reloading Watch before the native world is open also requires Menu → Resume /
opening the world first; improved spectator restore remains an interaction gap.

The observed night view is too dark to read the material distinctions reliably.
Repeated build/refresh phases dominated the visible character history before
the funding correction; compact phase/progress presentation still needs review.
A reference controller completing a route does not prove unaided human or model
recognition. Reported-pose AI walking is still not a native contact-driven avatar.

Next gates:

1. Material recognition at walking distance and at dusk/night on both generated
   maps, including a fresh human route and actual model decisions.
2. Compact solar collector with reviewed geometry, rating and a complete supply
   path; exhausted-input recovery, broader project/input readiness audit and
   useful next rewards.
3. Native avatar traversal and shoreline/water response, plus stepped rover
   hauling and physical cargo consequences before promoting columns to default.
4. Optimize opening/full catchup and texture/upload costs only against measured
   remaining bottlenecks. Do not infer GPU or multiplayer capacity from idle FPS.

Existing glass/oak/iron and native contact/water limitations are unchanged; no
new material realism, full momentum/energy closure, macOS or cross-GPU claim.
