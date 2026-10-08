# Voxel spring loss and timing audit — October 8, 2026

## Scope

Experimental measurements and analytical verification. This does **not** close full-world conservation, repair the glass-ball refusal, implement plastic dents, or add adaptive spatial subdivision. The five-part accuracy/speed/plasticity/refinement/authoring objective remains active.

Base main: `5f34dc6adebed0017f4111669a94f2fe5a79f016`; publication revision is the commit containing this note. Windows x64, Visual Studio/MSBuild 17.14.51, Release, separate `build/voxel-accounting`, Jolt double positions. Normal qualification uses the existing default `BANJO_JOLT_CONTINUOUS_SMALL_ROTATION=OFF`. The live 18893 session remains on the prior published executable so ongoing user experiments are preserved. No new browser/phone/platform qualification is claimed.

Sources: [world](../src/platform/VoxelImpactWorld.cpp), [spring observations](../src/rigid/JoltWorld.cpp), [analytical tests](../tests/voxel_face_spring_tests.cpp), [comparative regression](../tests/voxel_world_test.py), [gateway regression](../tests/voxel_gateway_test.py).

## An observed numerical loss, separate from material damping

Pinned Jolt 5.6.0 `SpringPart.h` describes its implicit Euler implementation. For an isolated scalar spring, with endpoint relative speed v₁, stiffness K, damping C, interval h and extension q₁ = q₀ + hv₁, its total impulse obeys:

`λ = −h(Kq₁ + Cv₁)`

The discrete energy balance includes three different terms:

- Material damping: `h C v₁²`.
- Implicit elastic integration loss: `½ K h² v₁²`.
- Velocity update quadratic loss: `½ Σ mᵢ |vᵢ₁ − vᵢ₀|²`.

The latter two persist at C = 0. They are numerical losses, **not** material heat or fracture work. Small-angle isolated torsion has the corresponding inertia/angle balance. These analytical two-body oracles use a single mass/inertia reference and are material-neutral; they do not establish general substance behavior.

Six compiled energy checks cover zero/nonzero initial extension, zero/nonzero damping, and zero/damped torsion at h = 1/240 s. Maximum translation energy residual is 5.02e−9 J against 2e−8 J tolerance; maximum small-angle torsion residual is 8.48e−12 J against 2e−9 J tolerance. Linear/angular momentum checks retain 1e−7 SI limits. False native trials restore the actual spring extension and cached impulse exactly. A seventh observation check covers native nearest-orientation tie handling at exactly π. Tolerances are new oracle bounds, not relaxations of world admission.

## World diagnostics and limits

Face observations retain the actual solver frame, B anchor, native total translation/rotation impulses, and native nearest-orientation motor error. Before-step geometry and accepted endpoint velocities provide spring damping, implicit elastic loss, endpoint work, constitutive residual and geometry-change measurements. The geometry term compares **changes** in the reported physical-angle potential against the native linearized motor potential; it does not repeatedly count their absolute offset.

These terms are an audit decomposition, **not a closed world ledger**. The native motor uses 2 sin(angle/2); the reported elastic energy uses physical angle. Changing frames and finite rotations require further constitutive qualification. The velocity quadratic currently uses authored cell mass; native mass rounding, full rotational integration, actual contact restitution/friction work, support reaction/work and sleep/cap behavior still need attribution. Do not sum the displayed terms and label the remaining deficit physical dissipation.

Accepted intervals alone accumulate response diagnostics. Timing counters include attempted and rejected native trials. Counters distinguish sweep inspection, before-face observation, full trial, actual `world.step`, totals reading, and candidate-face observation. Full trial contains the latter three and state capture/rollback overhead; these are nested timing values and must not be summed as independent phases.

Native face transforms are read once per body per face instead of repeated BodyInterface calls. Candidate totals/faces are read once per trial and reused after acceptance. Native response laws, material catalog values, fracture admission, angular caps, positive energy limits and default iterations are unchanged. Native frame arithmetic can change last-bit geometry and later contact trajectories; this is not a bit-identical optimization claim.

An optional diagnostic declaration `solver_iterations` accepts integers 16–256, default 96. Unknown/nonintegral/boolean/string/out-of-range fields are refused. This enables measured solver comparisons rather than hidden material-specific tuning.

## Default-build common experiment

Same 400 × 4 × 400 mm, 64-cell sheet; 1 kg iron voxel ball; 10 m drop; default 96 iterations; 1/960 s host step; 2 actual physical seconds. The normal small-rotation option is OFF. Density/stiffness and supported laws remain those documented in the [previous checkpoint](voxel-impact-world-checkpoint.md). No calibration values or admission tolerances changed.

| Sheet | Sheet mass kg | Broken faces / pieces | Unclosed E J | Spring damping J | Implicit elastic diagnostic J | Linear quadratic diagnostic J | Native substeps | Wall s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Glass | 1.60000 | 40 / 12 | −92.92330 | 1.41169 | 48.75478 | 60.63647 | 41,823 | 41.15 |
| Oak | 0.44800 | 0 / 1 | −44.16689 | 5.42856 | 9.06141 | 12.46432 | 6,410 | 7.19 |
| Iron | 5.03680 | 0 / 1 | −82.82857 | 3.30970 | 50.45484 | 55.62004 | 5,224 | 6.11 |
| Ice | 0.58688 | 110 / 62 | −103.15185 | 1.66734 | 74.53264 | 78.35345 | 73,631 | 35.65 |

These accumulated terms are **not independently additive proof** of conservation: contact work and coupled rotation remain missing. Iron's measured spring constitutive-work residual is 9.60318 J, versus glass 0.11775 J, oak 0.80794 J and ice −0.01234 J. That discrepancy needs native solve/geometry investigation rather than being relabeled damping. No spin-cap samples occur; peak spins are 599.96 / 600.33 / 408.34 / 806.65 rad/s respectively.

Glass's actual `world.step` accounts for 33.69 s of the 39.10 s full native trial profile and 41.15 s measured protocol wall time. The profiling build does not establish a speed improvement over the prior default 37.8 s single run. Source inspection counters and observer reuse do not solve the dominant native stepping cost.

The native comparative regression passes in **193.16 s**: eleven completed scenarios plus the preserved glass-ball refusal. Exact original IDs/masses, analytical pre-contact freefall, finite accepted states, positive-energy bounds, no-ball/missed-ball controls, alternate ball materials and 144/256-cell sheets remain checked. Through-plane passage is now tested at an actual received state during the drop rather than requiring the ball to remain below the plane at the final snapshot after bouncing. This corrects a measurement criterion, not a physics tolerance.

Comparative measurement executable SHA256: `cb46fa193074a4ec783af59a2d8f1f938b4122a3680cb49bb6e29098f895c877`. After that run, the exactly-π native motor-error observation tie was corrected and explicitly tested; that field affects diagnostic work only, not accepted dynamics or fracture admission. Final rebuilt executable SHA256: `e46c7afabbaf117f6d0a94946a94fa0875817837be8d088062910494b6bc1660`.

Five final rebuilt CTest entries pass in **2.16 s**: analytical face springs (seven cases), reversible spring trials, scene joints, joint interfaces and ordinary gateway/session/persistence behavior. The gateway rejects malformed iteration declarations. Source registration passes **326/326**, no exclusions; changed checkpoint links and `git diff --check` pass. Logs and binaries remain local excluded build artifacts. The full repository regression and new interactive input tests are not claimed.

## Retained glass-ball gate and rejected shortcut

A separate continuous-small-rotation **ON** investigation, same 64-cell glass sheet, 1 kg glass ball, 10 m, 1/960 s host step:

| Velocity iterations | Actual elapsed s | Outcome |
|---|---:|---|
| 96 | 1.427661 | Energy refusal |
| 128 | 1.500000 | Completed this horizon only |
| 192 | 1.468496 | Energy refusal |
| 256 | 1.488774 | Energy refusal |

The isolated 128-iteration success is not convergence or a reliable repair. No default was raised and the glass-ball UI stays unavailable. At 96 iterations the existing ON option does not resolve the original failure. No measured spin-limit hits occur in that probe (peak 362 rad/s below the native 1000 rad/s cap), so attributing its deficit to the cap is unsupported.

For the ON default iron-ball/glass-sheet 2 s comparison, measured total wall time was 50.44 s versus 53.16 s before observer reuse (single exploratory runs). Native `world.step` dominates the trial profile. This is a modest matched-build observation, **not** improvement from the default OFF 37.8 s reference and not a repeated performance qualification.

## Next work

1. Capture actual native contact impulses and start-of-solve geometry; audit support wrenches and coupled rotational work. Preserve rollback and avoid treating sleeping cached impulses as newly applied responses.
2. Resolve finite-rotation potential/Jacobian consistency and the contact integration failure without increasing numerical admission tolerances.
3. Optimize the measured native stepping bottleneck with paired timestep/geometry/energy comparisons. The current global swept-point rule can let a distant spinning fragment constrain all bodies; contact-local stepping also needs material integration accuracy.
4. Add retained plastic strain, return mapping, yield/hardening and measured dissipation for metals, then conservative mixed-resolution interfaces and unit-bearing custom declarations.
