# Browser Test Hub — October 6, 2026

## Try the checkpoint

Open **http://127.0.0.1:18891/tests.html**. Click **Run checkpoint checks** (about 70–80 seconds on this Windows machine), or run an individual card. The controls disable during execution; the progress line names the current check. Expand a result to see its output and executable fingerprint. PASS, FAIL, unavailable and execution errors are distinct.

Click **Inspect contact response** after the contact recording arrives. Choose glass, oak or iron, 40/120 mm head width and 100/50 ns physical step. Play or scrub the exact samples. Compare the final narrow glass case: 100 ns produces 16 broken bonds and 1.44 kg detached; 50 ns produces 12 broken bonds and no detached component. This disagreement is an outstanding acceptance failure. The 100× option enlarges displacement only for inspection; dimensions stay unchanged. Playback does not interpolate or drive the solver.

**Material lab** opens the existing load/release and pull-apart experiment. Change load strength and click **Run experiment** for six fresh CPU runs. **Playable World** opens the retained game on port 18890. These are different test areas: the World has not been migrated to the new material-contact reference. No owner world is reset by lab tests.

Only loopback access is configured. This is not a public/mobile deployment; responsive browser viewport checks are not physical-phone acceptance.

## What the buttons cover

| Check | Coverage | Current result |
| --- | --- | --- |
| Surface transfer & live regions | Actual-node impulse/torque/work reproduction, live bonds, clamps, budgets, stale-state and rollback refusal; short comparative trajectories | PASS, bounded reference |
| Native / material coupling | Existing compiled coupled contact and constituent reference suite | PASS |
| Occupied cell contact geometry | Actual finite native shape witnesses, rotation, compound gaps, overflow and read-only queries | PASS |
| Material integration / external loads | Verlet, applied work, reactions and numerical accounts | PASS, two suites |
| Joined tool contacts | Fixed assembly reference contact suite | PASS |
| Tool families / readiness | Pick, shovel, hoe and unfamiliar geometry; actual native use/admission | PASS, two bounded suites |
| Sustained contact convergence + replay | 12 glass/oak/iron cases with actual evolving topology, paired trials and accounting | **FAIL: three convergence checks** |
| Repeated excavation | Retained strict same-column yield gate | **FAIL: four iron repeats** |
| Rust owner → actual native engine | 17 actual-engine worker tests including actor ownership, pickup, movement and tool use | PASS |
| Rust command / state contracts | 23 Rust tests | PASS |
| Source registration | Every source under src/tests is assigned a CMake target | PASS, 315/315; registration alone is not compilation |

This is the checkpoint regression selection, not the full repository suite. [Live-region evidence and unresolved physical assumptions](live-contact-region-checkpoint.md) remain authoritative. No law, strength, contact coefficient, numerical tolerance, prescribed spin or initial physical input changes here. Existing strict failures remain failures, rather than being reclassified as expected passes.

## Recording and execution boundaries

`banjo_material_surface_contact_tests --record FILE` captures the existing sustained experiment through read-only downloads and constituent partitions, after accepted steps. Twelve runs each record the initial state and 32 subsequent samples through 204.8 µs (2,048 × 100 ns or 4,096 × 50 ns). Samples include 27 cell identities, actual position/displacement/velocity/mass, clamp/component membership, actual bond aliveness/damage, integration error and the two native tool poses/orientations/velocities. The finite iron head and oak laboratory handle retain their catalog mass and native response; oak is not admitted to playable worlds.

The same invocation can require strict convergence and return exit 1 with a complete recording. A recording is not a passing certificate. Fatal/incomplete results are refused by the viewer. Recording and unrecorded executions are compared field-by-field for all 12 console evidence records, excluding wall time: their physical results are identical.

The viewer validates all twelve unique material/width/timestep combinations, bounds, initial/final clock, exact node/source identity, finite measurements, material mass, nine fixed supports, bond totals and source quaternion norms. It verifies the downloaded recording SHA256 against the actual native bytes. Lines depict surviving bonds; circles depict translational cell centres. Tool outlines use the actual native orientation. Cell spin, debris collision surfaces, self-contact, settling, soil and continuous world interaction remain unsupported in this experiment.

The local host accepts a fixed catalog ID, never browser-provided commands, paths or arguments. A shared execution semaphore prevents simultaneous material experiments/tests. Runs use fresh temporary directories, bounded subprocess time (60 seconds per check), bounded console tails and a 10 MB recording limit. No LLM call is made. The latest job can be polled/reconnected; a new job replaces it and restarting the host expires it. Result and recording routes accept only exact UUID keys. Existing origin/host restrictions and asset allowlisting remain.

Executables are fingerprinted before/after each test. The worker check also fingerprints both actual native and Rust engines. These fingerprints identify artifacts; checkout revision alone does not establish binary/source equivalence. Rust tests use the existing offline dependency cache. Missing builds, timeout, artifact changes and subprocess failure cannot become PASS.

## Reproduce on Windows

Use the existing separate build directory (MSVC Release, laboratory window disabled):

```powershell
cmake -S . -B build/local-cell-tools -DBANJO_BUILD_LAB=OFF
cmake --build build/local-cell-tools --config Release --parallel 4 --target banjo_material_lab_record banjo_material_surface_contact_tests banjo_native_lattice_contact_tests banjo_native_point_contact_tests banjo_lattice_verlet_tests banjo_lattice_external_load_tests banjo_fixed_assembly_contact_tests banjo_native_tool_use_tests banjo_tool_use_admission_tests banjo_live_world_run
cargo build --locked --manifest-path runtime/Cargo.toml --target-dir build/rust-runtime
node client/node_modules/typescript/lib/tsc.js -p client/tsconfig.json
python scripts/check-source-registration.py
python tests/lab_test_hub_tests.py build/local-cell-tools/Release -v
python tests/material_lab_recording_tests.py build/local-cell-tools/Release/banjo_material_lab_record.exe -v
node --test tests/material_lab_client_tests.mjs
python scripts/material-lab.py --native build/local-cell-tools/Release/banjo_material_lab_record.exe --port 18891
```

TypeScript dependencies must already be installed (`npm ci` in `client` on a fresh checkout). Rust/CMake dependencies likewise need the repository's normal initial setup. The server starts no World process and exposes no arbitrary shell endpoint. Build artifacts, live logs and screenshots stay under ignored `build/`.

## Verification and remaining work

Windows x64/MSVC Release headless solver and ordinary in-app browser UI. The browser executes all 13 catalog entries: eight bounded native suites + worker/Rust/registration pass, two strict gates fail. The new host suite passes three actual-engine groups, including three client contract tests on the actual returned recording, origin/path/identity/busy checks, timeout/missing-binary recovery and recording/unrecorded parity. Ten existing native lab/host tests and four existing client groups pass. TypeScript and source registration pass. Desktop, 390×844 portrait and 844×390 landscape are inspected; physical phone, macOS and cross-GPU determinism are unverified.

The native CI build now runs the new host/client recording checks immediately after compilation, before the broader CTest gate. The test requires the HTTP result to agree with the actual strict solver exit and recorded convergence count; it does not assume a particular platform's failure count or mark the strict gate passing. Linux CI execution is not yet verified locally.

Next: isolate sustained contact refinement defects without relaxing the gates; qualify repeated useful excavation and full actor/environment transfers; implement finite-cell/neighbour/debris response and durable state; migrate the shared Rust gateway/player UI in stages. W00–W17 is still active. This checkpoint makes the implemented references testable and does not declare the rewrite complete.

Prepared against main `18507c6f`; implementation `2ccb38fa` is published on GitHub main. The full publication revision and measured artifact/source hashes are recorded in [checkpoint evidence](evidence/test-hub-2026-10-06.json).
