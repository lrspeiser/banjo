# Native rover grades — October 1

Published implementation: `8d3bc1f68239f0539ba43d54c452b4671fdd1cc8` on
GitHub main. Native runner/platform CLI and native regression target were
rebuilt from these sources in `build/agent-progression` (MSVC Release).
The preview on `http://127.0.0.1:8770/world` was restarted with this build.

## Implementation

New generated stock rovers declare a 12° autonomous climb limit instead of 8°.
This applies to the room builder's unloaded 43.5471 kg oak-wheel assembly with
its existing motors. The editable Workshop rover has additional battery/hopper
geometry and selectable dimensions/materials: its conservative 8° declaration
is retained until that assembly is separately measured. Existing saved programs
keep their explicit limits. No contact, material, motor or friction law changed.

Ground probes now compare the actual interpolated height at their world point
with a terrain reference under the chassis. That reference uses half-cell
central height differences in x/z. Chassis pitch alone no longer invents a
ground step. This remains top-height-field sensing, not a physical ranging
device or underground/overhang detector. Tight curvature can still warn before
the body reaches its declared pitch limit. No body velocity is assigned.

Source: `src/fastlattice/LiveWorld.cpp`, `tools/build_rover_room.py`, and the
CMake-registered `tests/rover_roam_tests.cpp`. The latter accepts an optional
scenario-name substring for focused experiments; no match fails. CTest still
runs every case without a filter.

## Measured native experiments

Windows, MSVC Release, CPU reference/parallel backend, 50 mm scene grid,
`dt=1/240 s`. Two 20 N m stall-torque motors, 60 rpm no-load speed, 40 N m
brakes, 100 kJ initial battery at 24 V. Gravity and actual shape contacts are
retained. Each ramp case starts at rest, settles for two seconds, then drives
for six seconds on an anchored 3 × 0.1 × 20 m concrete box. Only the two rear
wheel materials change; the iron stubs/caster, oak deck and glass panel remain.
Compiled density determines mass: oak 43.5471 kg, glass 60.8935 kg,
iron 112.644 kg. Density/friction differences are implemented; no grain,
bending, wheel deformation, fracture or plasticity is established here.

The measured slip uses native `v + omega × lever` at the analytical cylinder
support point, projected along the ramp. Samples are once per second and are
admitted only within 10 mm of the plane; these are sampled maxima, not bounds
over every timestep. There are 12 rear-wheel contact samples except oak at 20°,
which has ten and rolls off the finite ramp. Negative distance is downhill.

| Rear wheels | Grade ° | Uphill m | Sampled slip m/s | Motor work J | Motor heat J | Unclosed work − Δmechanical J |
|---|---:|---:|---:|---:|---:|---:|
| Glass | 0 | 5.708 | 0.0000211 | 43.58 | 39.02 | 5.38 |
| Glass | 5 | 4.515 | 0.0000245 | 263.15 | 117.41 | 4.20 |
| Glass | 8 | 3.803 | 0.0000128 | 336.65 | 221.62 | 3.50 |
| Glass | 12 | 2.863 | 0.0000124 | 367.76 | 425.37 | 2.58 |
| Glass | 16 | 1.936 | 0.0000062 | 324.96 | 699.52 | 1.74 |
| Glass | 20 | −0.962 | 0.407 | 222.44 | 1011.83 | 418.33 |
| Oak | 0 | 5.785 | 0.0000324 | 34.53 | 22.27 | 9.41 |
| Oak | 5 | 4.903 | 0.0000636 | 211.09 | 62.84 | 10.38 |
| Oak | 8 | 4.371 | 0.0000612 | 286.09 | 117.31 | 11.68 |
| Oak | 12 | 3.645 | 0.0000596 | 350.50 | 224.01 | 16.35 |
| Oak | 16 | 2.763 | 0.156 | 375.12 | 367.96 | 42.83 |
| Oak | 20 | −10.591 | 2.850 | 341.86 | 390.34 | 1507.83 |
| Iron | 0 | 5.378 | 0.0000162 | 85.85 | 79.05 | 9.18 |
| Iron | 5 | 3.293 | 0.0000080 | 351.42 | 334.37 | 5.55 |
| Iron | 8 | 2.049 | 0.0000048 | 329.56 | 667.00 | 3.41 |
| Iron | 12 | 0.404 | 0.0000004 | 93.92 | 1313.19 | 0.67 |
| Iron | 16 | −0.215 | 0.0000591 | −57.80 | 485.52 | 7.61 |
| Iron | 20 | −0.611 | 0.0000007 | −163.55 | 660.18 | 67.57 |

Battery debit minus actual motor draw is below `1e-7 J` in all cases
(largest measured absolute value about `7.03e-10 J`). Actual torque respects
the existing DC envelope `abs(stall * (command - previous_speed/no_load))`,
or the separate brake bound, within `1e-4 N m` for float joint impulses
(largest measured excess `3.29e-6 N m`). The initial experiment incorrectly
treated stall torque as a hard current limit; that assertion was replaced by
the implemented torque-speed envelope. Back-driven motors can exceed stall
torque and brakes can reach 40 N m. No solver tolerance was changed.

The final column is deliberately unclosed. Contact/brake/drag losses and
numerical corrections are not fully allocated, and anchored ground reactions
are not integrated into a total-system momentum ledger. Battery accounting
and measured point slip do not prove full-pipeline energy/momentum conservation.

## Autonomous controller and terrain

- On a 10° ramp, the old 8° program turns away; the 12° program climbs
  4.01205 m in six seconds with maximum body pitch 9.99856°. On a 16° ramp,
  the 12° program reports the slope refusal. Turning can leave the finite
  ramp; these cases do not certify safe descent or all boundaries.
- On a dry generated basin with 250 mm terrain samples, starting at z = 9 m,
  the old limit reaches 1.28087 m uphill before its 8.00977° pitch refusal.
  The 12° limit reaches 3.34079 m in six seconds, maximum pitch 9.22311°,
  without a ground warning. Maximum ground discrepancies are respectively
  0.0705338 / 0.0844636 m.
- A sharper basin with 125 mm samples, starting at z = 2 m, retains a
  0.152183 m ground warning and no uphill progress for either declaration.
  Increasing the pitch setting does not disable support sensing.
- An initially tilted 20° rover above flat native terrain reads zero ground
  discrepancy. Cutting a real 0.5 m depression beneath that same probe then
  reads 0.5 m. Declared initial pose is used; runtime bodies are never moved
  to produce the result. Existing dry-hole, bounded recovery, water, solar,
  commands, saves and stuck-recovery cases remain in the suite.

The 12° setting is a useful unloaded stock-rover policy, not a general grade
certificate for different materials, payloads, rough terrain or physical soil.
Ledger hopper contents still contribute no native inertia.

## Generated delivery failures and next work

A separate ordinary native-world-clock run from source `5ab072f` measured both
supported generated maps for 300 simulated seconds, without grants, provider
calls or forced movement. Map seed 4's rover never collected a load; map seed 7
collected 40 kg, including 12 kg copper ore, but made no delivery. Both had
zero trips. These are measured route failures, not passing delivery tests.
Ignored raw logs/records are under `build/resource-flow/generated-routes.log`
and `routes-0.json` / `routes-1.json`.

Next inspect actual route/obstacle and intake arrival behavior, replay both
maps with this checkpoint, and require positive source-attributed intake
receipts followed by processing/output collection. The generator's declared
0.35 rise/run flood-fill limit is still more permissive than the measured
stock rover policy; it must be reconciled with real route planning and the
assembly footprint. Keep physical cargo/tipping, reacting avatars, full
conservation and material/energy-funded repair as separate unfinished gates.

## Verification

The final native suite passes 19 cases, including all 18 material/grade
experiments. Three affected CTest suites (room, brain, Workshop rover) pass
in 11.22 s. Source registration remains 286/286 with no exclusions.
Fifteen resource/player/browser checks pass in 104.936 s. The rebuilt preview
on port 8770 passes ordinary Chrome fresh-world selection,
live ground/water readings, recovery/lift/release and zero browser exceptions:
794.61 N pull, 544.19 J measured hand work. Raw checks/logs are ignored build
artifacts; [the acceptance checklist](player-experience-checklist.md) retains
the open requirements rather than declaring the full goal complete.
