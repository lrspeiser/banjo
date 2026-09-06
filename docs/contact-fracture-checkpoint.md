# Contact capacity and spring reaction checkpoint

This checkpoint follows main `2d086fd` on 2026-09-06. It corrects a contact-resource failure and a rotating-spring reaction bug. It does not complete the realistic-fracture or world-scale execution gates.

## Implementation

- V2 now reserves 65,536 body pairs and 32,768 contact constraints by default. Optional `contact_budget` makes these resource limits explicit; legacy Jolt callers retain 16,384/8,192 defaults. Unknown, malformed and out-of-range budgets reject.
- Temporary scratch is reserved before stepping: 32 MiB plus the declared constraint count times this Jolt build's maximum constraint size plus 64 bytes for associated scratch/alignment. A 256 MiB arena cap rejects larger layouts before world creation. This is the temporary arena limit, not total process memory.
- A bounded initial AABB sweep, expanded by Jolt's actual speculative distance, rejects initial convex-body density outside the declared budgets before the first step. This is not a future/swept-contact guarantee. Runtime exhaustion still faults and rejects the affected tick.
- Reports expose effective budgets, the initial pair envelope, actual speculative distance, and last/peak contact-listener manifold/point counts. These counts include speculative contacts; they are not exact allocator occupancy or solved impulses. Rejected reversible trials restore the observable diagnostics.
- V2 no longer estimates and queues optional impact events that it immediately discarded. Friction/restitution settings and Jolt contact solving remain active. Legacy observation behavior remains enabled by default; deferred material contacts retain required activation observations.
- Spring damping reconstruction now uses the constraint direction at the start of the Jolt step, matching the solver's reaction axis. Projecting onto the rotated end-of-step direction incorrectly mixed transverse velocity into axial stress. Material constants, failure thresholds and constitutive laws were not retuned.

Full Windows Release build succeeds; all **49 regression suites pass** together in 81.11 s, including capacity invariance across matched glass/oak/iron panels, observation-independent collision response, budget rejection, and reversible diagnostic replay.

## Independent reaction regression

A material-neutral freely rotating 2×2×2 network produces first-step maximum axial strain 0.0857493 before the correction and 5.08e-8 afterward. A separate two-body transverse-motion oracle checks zero first-step axial spring impulse and zero reconstructed elastic opening. Existing collinear damped-oscillator convergence remains covered. This validates the reaction-direction correction, not a full continuum model.

## Capacity and performance evidence

Windows Release/MSVC 1944, Core Ultra 9 285K, same Jolt settings and one solver thread. `measure_contact_load.py` generates glass/oak/iron sphere-cell objects in ground-drop and zero-gravity/no-ground controls, with 114, 486 and 537 occupied cells. Each duration (0.05 and 0.5 s) has three fresh-process repetitions. A preserved capacity-only executable separates resource/reporting changes from the spring-axis correction.

At the preserved baseline, both 537-cell cases fail with `ContactConstraintsFull` on the first update. The capacity-only version completes every matrix case. Its initial three-ball envelope is 17,157 pairs and the first step observes 12,495 speculative manifolds, exceeding the old 8,192 constraint allowance. The speculative distance is approximately 20 mm while each 7³ ball cell radius is about 5.6 mm; internal speculative neighborhoods dominate this load. This checkpoint does not silently reduce that numerical distance or suppress cell contacts.

For every previously successful matrix run, all pre-existing physical report fields are identical across the baseline and capacity-only executable; only load/step timing changes. At 486 cells, 0.5 s ground-drop median throughput improves from 0.394× to 0.465× real time. Capacity-only 537-cell ground throughput is 0.232×. These are solver-only measurements, exclude rendering, and do not establish a frame budget.

## Generated material scenes after both fixes

All 12 catalog presets admit and take eight steps with retained mass. Analytical glass/oak/iron free flight, zero-gravity momentum/energy and rigid support controls pass. Every generated dynamic scene completes; each repeated scene retains the same discrete outcome at fixed settings. The unchanged three-second fixtures report:

| Scene | Broken bonds at 1/480 s | Median solver wall time for 3 s | Median step p95 |
|---|---|---:|---:|
| Panels, 2 m/s | Glass 0 / oak 0 / iron 0 | 486 ms | 0.941 ms |
| Panels, 6 m/s | Glass 0 / oak 0 / iron 0 | 568 ms | 0.897 ms |
| Panels, 12 m/s | Glass 0 / oak 24 / iron 0 | 701 ms | 0.950 ms |
| Knife/tomato proxy | Tissue 18 | 1,318 ms | 1.222 ms |
| Three 7³ matter balls, 537 cells | Glass 0 / oak 0 / iron 0 | 14,610 ms | 12.532 ms |

All panels and the tomato remain connected. No detached glass shards or complete tomato slice is demonstrated. No material-ranking realism is inferred from these counts. The 537-cell simulation is about 0.21× real time even without rendering.

Halving the step changes the 12 m/s panel result to glass 1 / oak 29 / iron 0 and tomato to 22 broken bonds. Tomato's maximum reaction/geometric-extension discrepancy changes from the old 28.37 mm to 2.62 mm at 1/480 s (1.02 mm at 1/960 s). The coarse panel discrepancy grows from 19.20 to 31.33 mm after its trajectory changes; at 1/960 s it is 4.55 mm. Therefore the axis fix does not pass fracture convergence. Mechanical energy changes remain unseparated numerical/contact/work observations, not a closed conservation ledger.

## Visual verification boundary

The updated native studio launches. In this session Windows automation twice failed with `foreground window did not report a process id`, so ordinary live clicking and frame/backlog timing could not be reverified. No new live-frame or input-latency claim is made. Offline raylib captures of the final panels, tomato and dense-ball scenes were inspected; they expose the same physical results and the new contact-counter row. The capture mode and any FPS label are not realtime throughput evidence. The final temporary-arena change preserves every reported physical field of the six generated scenes against the preceding measured executable; only timing/resource metadata differ. The full 49-suite result predates only a viewer spacing adjustment and measurement-script argument/status hardening; both were verified separately afterward.

## Next gates

1. **G02:** localize bond threshold crossings within the timestep with complete state/history rollback and work accounting. Currently old stiffness carries the full crossing-step impulse and damage is applied afterward; stiff-wave peaks and contact/spatial resolution remain unresolved. Compare time, iteration and contact/space refinement across glass/oak/iron and tissue without strength tuning.
2. **G05:** measure explicit contact-distance refinement and implement bounded active detail/rigid condensation with conservative transfers, wake criteria and accuracy gates. Every cell is still a dynamic body. Larger contact buffers alone do not make dense worlds realtime.
3. **G01/G04/G06:** retain surface fidelity, shared versioned histories and transactional publishing requirements. No goal or retained mechanic is removed or marked complete by this checkpoint.

## Reproduce

```powershell
cmake --build build/win-joint-double --config Release --parallel 4
ctest --test-dir build/win-joint-double -C Release --output-on-failure
python examples/authoring/verify_physics.py --engine build/win-joint-double/Release/banjo_platform_cli.exe --output build/generated-new
python examples/authoring/measure_contact_load.py --engine build/win-joint-double/Release/banjo_platform_cli.exe --output build/contact-new --repeats 3
build/win-joint-double/Release/banjo_network_lab.exe build/generated-new/scenes panels_12mps.json --studio --live-report build/native-trial.json
```

Output directories must be new. Live timing uses the ordinary native input/render loop at 1×; offline captures are not responsiveness evidence. Raw generated packages, reports, offline captures and the live-verification limitation are preserved with the user-facing checkpoint deliverable.
