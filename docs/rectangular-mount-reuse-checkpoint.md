# Rectangular mount damage and paid reuse — October 2, 2026

Published code: `71fe9c39868e43c40c491991136f28223b2db650` on GitHub `main`.
The eight-suite/48-test evidence below covers that code revision; this line is
a subsequent documentation-only publication record.

## Implemented boundary

Newly reviewed filled rectangular mounts use their sampled face centroid,
dimensions and the existing weaker constituent tensile strength × face area
× declared join efficiency. The native fixing now reads Jolt's actual angular
constraint impulse divided by the accepted timestep. For unit section axes
`u`, `v = normal × u`, opening occurs when

```
equivalent_normal_force = |N| + 6 |Mu| / v_size + 6 |Mv| / u_size
equivalent_normal_force > declared_tensile_capacity
```

This is the rectangle's maximum absolute corner normal stress, expressed in
newtons so the existing history can retain its deciding load and capacity.
It includes both bending directions and axial load. The moment excludes the
attachment force's lever arm; adding that again would count it twice. Existing
shear failure remains independent. Opening removes the actual fixing and
wakes its endpoints; it supplies no launch impulse, fabricated pieces or
velocity assignment. Component mass and material/internal histories remain.

This is an **experimental abrupt interface model**, with symmetric normal
strength inferred from the declared tensile capacity. Independent compression,
torsion, fracture work, adhesive/fastener calibration, fatigue and wood grain
are unsupported. It does not install a brittle law inside oak or iron.
Nonrectangular sampled mounts retain force-only limits. Existing saved
fixings without sections retain their original behavior.

The C ABI adds `banjo_fix_section` without changing `banjo_joint` layout.
Python, line protocol, room validation and paid staging carry the section.
Invalid frames/dimensions refuse before creating a joint. Paid staging checks
the exact dimensions and rotated frame, and rejects their tampering. Workshop
model instructions explain that these values are compiled from actual faces,
that a thin mount/long lever requires testing, and that remake preserves the
original while making a separately paid result.

Worlds containing section history use `banjo.world.v2`; others remain v1.
The new reader accepts both, with complete restoration required for v2.
Older engines cannot report a whole v2 restore. Persistent funded/named rooms
already reject an incomplete native restore; they must be upgraded before
reopening such a world. Paid staging validates this format transition.

## Measured behavior

Windows, Visual Studio 2022 x64 Release, MSVC 19.44; CPU/native reference,
`BANJO_BUILD_LAB=OFF`, build directory `build/agent-object-strike`.

`tests/fixing_tests.cpp` uses the same 200 mm cube bracket and anchored wall
for glass, oak and iron, 50 mm cells, 1/240 s, normal gravity, 100/200 mm lever
arms, 200×100 mm declared rectangular sections. Actual masses are 20, 5.6,
62.96 kg. Settled bending moments agree with `mass × 9.81 × lever` within 2%:

| Material | 100 mm lever, N m | 200 mm lever, N m |
| --- | ---: | ---: |
| Glass | 19.6184 | 39.2367 |
| Oak | 5.49314 | 10.9863 |
| Iron | 61.7586 | 123.517 |

These tests use declared interface capacities to isolate the stress criterion;
they do not calibrate material strength. Both axes, unequal dimensions, finite
bending failure, unchanged mass, invalid-input refusal and history reopening
are checked. Native restart can initially under-report the 200 mm lever moment
by about 25%; it recovers after settling. This checkpoint does not claim exact
constraint warm-start replay or converged dynamic peak loads.

`NativeRemake.test_paid_made_target_strike_separates_and_paid_replacement_retains_damage`
uses a finite stocked/charged workbench fixture at 5 mm and 1/240 s. It pays for
an iron/oak pick and an iron/oak target with an 800×5×5 mm handle. Another native
actor supports the head using bounded ordinary holding/lifting. The target
retains an intact 5×5 mm sampled mount (2250 N normal, 275 N shear) before Use.
An ordinary private Inventory pickup and object Use then open this actual
mount **after contact**, at about 2.74 kN equivalent normal force.

The test stows the striking tool, picks up/stows the separated target handle,
reviews and funds a 30 mm section replacement, and verifies actual replacement
pickup/contact. It injects a placement-save failure, checks exact native,
inventory and funded-ledger rollback, retries and replays without another
result/debit. Original failed-joint history and the frozen damaged-source
binding survive whole native reopening. Local material/work/energy residuals
are zero; native fabrication-transfer roundoff is approximately 1.14e-13 J.
These process receipts do **not** close native strike momentum/energy accounts.

The earlier shorter paid-target probes still retain their mounts under contact.
This is a declared geometry/load-path difference, not a guarantee every hit
breaks something or a capacity reduced to force a desired outcome.

## Verification and remaining work

Eight affected native/ABI suites pass in 36.76 s; 48 host/native/HTTP/Chrome
tests pass in 51.994 s. Source registration is 297/297 with no exclusions.
No force/torque cap, contact response, timestep or existing physics tolerance
changed. The new interface criterion is an explicit model addition. The
earlier lift-only paid-source test now fails from bending normal stress at its
2250 N equivalent capacity, so its expected failure basis changed from the
old 275 N shear criterion; its replacement/recovery checks still pass.

```powershell
cmake --build build/agent-object-strike --config Release --target banjo_live_world_run banjo_c banjo_fixing_tests banjo_scene_joint_tests banjo_hand_stroke_tests banjo_joint_interface_tests banjo_thermal_mechanics_tests banjo_native_point_contact_tests banjo_native_lattice_contact_tests --parallel 4
ctest --test-dir build/agent-object-strike -C Release -R '^(banjo_fixing_tests|banjo_scene_joint_tests|banjo_hand_stroke_tests|banjo_joint_interface_tests|banjo_thermal_mechanics_tests|banjo_native_point_contact_tests|banjo_native_lattice_contact_tests|banjo_joint_binding_tests)$' --output-on-failure
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/agent-object-strike/Release/banjo_live_world_run.exe).Path
$env:BANJO_LIBRARY=(Resolve-Path build/agent-object-strike/Release/banjo.dll).Path
$env:BANJO_BUILD_DIR=(Resolve-Path build/agent-object-strike/Release).Path
$env:PYTHONPATH='tests'
$env:PYTHONIOENCODING='utf-8'
python -m unittest player_identity_tests tool_use_tests object_strike_tests quick_tool_tests.RapidPlayer workshop_fixed_assembly_tests fabrication_remake_tests.NativeRemake.test_paid_manufactured_mount_failure_retains_receipt_and_paid_replacement_works fabrication_remake_tests.NativeRemake.test_paid_made_target_strike_separates_and_paid_replacement_retains_damage -v
python scripts/check-source-registration.py
```

Set `BANJO_LIBRARY` before the CTest command as well when its binding test runs
outside the generated CTest environment. Logs/evidence under ignored `build/resource-flow/` include
`section-native-build.log`, `section-native-tests.log`, `section-host-tests.log`,
`paid-made-target-test.log`, `paid-made-target-replacement.json` and
`section-fixing-tests.log`.

R3 remains open: complete the fresh-map supply/paid damage/collection/reuse
journey with private peer ownership and a Python server restart, integrate held
source/target internal damage on a shared accepted clock, and implement genuine
repair/wear. This fixture does not replace those requirements. Existing preview
servers have not been restarted; no new interactive native window qualification.
