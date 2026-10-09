# Detached native cell flight — experimental stepping

October 8, 2026. Source parent `aef24471e38f527a998ed833cb99409f9182ec96`. Implemented optional scheduling, not near realtime or calibrated material admission. Source/tests and the website are published to GitHub main as `ec246f9f70a4fab41e841af902fd0c151a1f291f`; this following documentation revision records that checkpoint. The material-law baseline is unchanged.

## What you can test

In the 3D lab select **Motion → Detached flight · experimental** and drop a 1 kg iron ball from 10 m onto a 4 mm ice sheet. Original occupied cells fracture through their native connections. A disconnected cell that is far from all other geometry may stop driving the global thickness timestep. **Free shards** reports the current count. Physics & record lists the distinct flown cells and those that subsequently collided again. Before/Live retain actual native geometry. No cell is replaced, destroyed, assigned a launch velocity or animated along an invented trajectory. Reference remains default.

## Implementation and bounded applicability

[`VoxelImpactWorld`](../src/platform/VoxelImpactWorld.cpp) accepts the bounded boolean `local_rigid_flight`, default false. Only dynamic cells with **zero live interfaces**, no object actuators and no collapsed ball proxy qualify. Connected elastic/plastic material retains the original surface-speed/thickness rule. There is no coarsening transfer: the same native cell, source mass, inertia, pose and spin continue in Jolt, with the same gravity, damping, contact law, speed limits and whole-scene energy refusal gates. This is not independent local-island integration.

The predicted empty-space test encloses each dynamic box in its circumscribed sphere for arbitrary rotation. Anchored boxes retain exact oriented bounds. Center travel is conservatively expanded by start velocity and gravity. A 20 mm margin includes the native speculative envelope. Since another connected body's acceleration is not known in advance, the actual candidate COM segment and arbitrary-rotation envelope are checked again **inside the reversible trial**. An overlapping candidate envelope or observed contact on an exempt cell rejects the entire unpublished trial and retries with the original motion limit. The native per-update pose integration supplies a straight COM segment; this helper does not certify arbitrary curved trajectories, multi-step paths or other engines. External force commands conservatively disable the exemption. Reconnecting or supporting arbitrary authored components is still future work.

The compiled [`BoxSweep`](../src/physics/BoxSweep.hpp) center-path helper supplies this geometric envelope. Analytical tests cover rotating corners, anchored thin floors, opposing moving paths and invalid inputs. Candidate-path rollback is implemented; none of the standard full-drop fixtures triggered it, so fixture completion does not exercise that fallback branch. The existing reversible-trial native regression covers whole-world rollback separately.

## Same-condition material runs

Iron ball, 1 kg, 10 m; 0.4 m square / 4 mm sheet, 8×8 cells, 32 cm support gap; nominal dt 1/960 s; two physical seconds. Densities glass/oak/iron/ice 2500/700/7870/917 kg/m³, stiffnesses 70/12/211/9 GPa. Total dynamic masses 2.600/1.448/6.0368/1.58688 kg. Oak remains elastic, without grain; reference iron has no ductile tearing. No material name selects a bespoke flight/fracture rule.

| Sheet | Wall s | Accepted steps | Pieces / broken faces | Distinct flown / later contacted | Unclosed energy J |
|---|---:|---:|---:|---:|---:|
| Glass | 37.502 | 41,823 | 12 / 40 | 4 / 4 | -92.923298 |
| Oak | 7.426 | 6,410 | 1 / 0 | 0 / 0 | -44.166886 |
| Iron | 6.213 | 5,224 | 1 / 0 | 0 / 0 | -82.828571 |
| Ice | 26.981 | 48,977 | 61 / 109 | 37 / 25 | -103.338971 |

The reference has 41,823 / 6,410 / 5,224 / 73,631 steps. Glass/oak/iron's experimental end state/work is unchanged in these runs; glass's flown cells did not exceed the original motion bound. Ice changes from 62 pieces/110 failed faces to 61/109, with 48,977 steps. Its maximum exempt surface travel is 0.567 mm versus the old 0.200 mm limit. Twenty-five previously flown cells later participate in native contact. The measured reduction in steps is useful evidence, but changed topology and unresolved losses prevent accuracy or universal speed admission. Realtime is still far away. These final scoped-test timings are from sequential calculation with no concurrent build. They are not paired against reference mode, so a speed ratio is not admitted.

Signed residuals and full output remain in ignored `build/voxel-flight/scoped-final-results.json`. Large energy deficits are unexplained/numerical terms, not thermal energy. Material refinement, finite-spin free-flight accuracy and full conservation are unfinished.

## Verification and environment

Windows x64, Intel Core Ultra 9 285K, MSVC Release / precise CPU, Windows SDK 10.0.26100; separate tree `build/voxel-contact-audit`, outputs `build/voxel-flight/Release`. Lab/CUDA/Rust OFF. No full repository, phone, macOS or cross-GPU claim.

- Four low-drop controls compare every physical/work field at every output against the all-cell mode. No exemption is admitted in those controls; parity is exact.
- Four complete high-drop experiments retain all 107 original visible/native cells and source masses; ice exercises the changed timestep and actual later contacts.
- Compiled center-path oracle samples 16,800 rotating corners, plus the prior 16,800 supplied-travel corner tests.
- The compiled CTest registration includes a **full** high-drop lifecycle test; a short no-flight smoke test alone is insufficient.

Final **17/17 scoped CTests pass in 125.22 s**, including the full high-drop lifecycle (97.59 s including low-drop controls), existing native transfer, connector plasticity, shared work, capacity, rollback, gateway, delivery and playback checks. Source registration is **342/342**, no exclusions. Native SHA-256 `79a0ff1372639e4768100a799bb4ec49e58208b2106618bb90881574004e27b0`. Four complete **default-mode prior-binary comparisons** through two seconds retain every physical/work field at every 16-host-tick output against `83da8b8838c5ec80197b0bb9594ba8cfaf8892befb9baa080931c4d12fd2c272`. Profiling alone is excluded; request order alternates. Glass costs 35.447 versus 35.459 s; ice 38.100 versus 37.846 s. This proves default preservation, not experimental accuracy. The normal 3D browser Drop completes at two physical seconds with **61 pieces, 109 broken faces, 48,977 steps and 25 current free cells**, matching the native fixture. Before/Live restores original/accepted geometry. The browser's complete delivery readout is about **0.05× realtime** with 60 renderer fps; native-only timings do not prove delivery speed. Private screenshots: `build/voxel-flight/browser-before.png` and `browser-after.png`. Refined outcomes follow below.

## Refinement failure retained, not relaxed

The 1/1920 s high-drop glass experiment refuses at **1.428032016754 s** with zero admitted flight intervals. The previous published executable and the new flight-enabled executable retain **exactly the same physical/work state at every output and the identical rejected candidate**: energy 96.774807 → 96.782160 J, contact work +0.00734944 J, depth 14 / candidate dt 3.17891e-8 s. The invalid candidate is rolled back, never rendered. The failed refined run is explicitly resolved as a reproduced pre-existing contact-solver defect; it is **not** a passing refinement/accuracy check and no limit is relaxed. Private source evidence: `build/voxel-flight/prior-refined-refusal-parity.json`.

At the same 1/1920 s timestep, oak and iron complete with 7,598/6,724 steps, no failed faces and zero admitted flight intervals. Ice reference and flight both complete with **75,015 steps, 64 pieces/112 faces and -74.925100 J unclosed energy**. Its exempt surface travel stays below the old motion bound, so there is no step saving; checking the gate adds cost (44.70 versus 48.69 wall seconds in this diagnostic pair). The original-timestep ice has a -103.338971 J deficit and different topology. This fails a convergence claim; the experiment remains optional and accuracy/realtime remain blocked. Eight reference/flight refined outcomes are retained in `build/voxel-flight/refinement-comparison.json`; the glass durations are shorter because they refuse, and cannot be used as speed comparisons.

The finer timestep does not establish convergence. Connected contact/interface work must be solved consistently before this laboratory can be admitted as realistic or near realtime. The optional flight path's lifecycle test passing does not close that gate.

## Remaining work

1. Preserve loaded connected components and their elastic/plastic modes while allowing unrelated rigid flight its own timestep; this singleton gate does not solve the connected glass driver.
2. Couple material interfaces and contact at local islands, and account for all external work/torque. Retain the original energy gates.
3. Qualify timestep/spatial refinement and finite-spin free flight across glass, oak, iron and ice; resolve large energy deficits and topology sensitivity.
4. Recover multi-cell rigid continuation, later-impact reactivation, adaptive occupied cells and sustained ≥1 physical second per wall second.
5. Extend the same pipeline to qualified heat, fluids, burning and power with free-form 3D demonstrations and unit-bearing authoring.

## Reproduce this checkpoint

```text
python scripts/check-source-registration.py
cmake --build build/voxel-contact-audit --config Release --target banjo_voxel_world_run banjo_box_sweep_tests --parallel 4
python tests/voxel_rigid_flight_test.py build/voxel-flight/Release/banjo_voxel_world_run.exe --full
python tests/voxel_execution_test.py build/voxel-flight/Release/banjo_voxel_world_run.exe build/voxel-hybrid/Release/banjo_voxel_world_run.exe --strict-inline-baseline --alternate-request-order
python scripts/voxel-lab.py --native build/voxel-flight/Release/banjo_voxel_world_run.exe --port 18924
```

The optional `--dt 0.0005208333333333333` full test currently **fails** at the reproduced glass contact gate; it is retained as an open negative refinement result, not a passing test.
