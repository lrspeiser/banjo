# Held strikes: native and CPU target rollback - October 2, 2026

## Implemented boundary

`fastlattice::runNativeFixedTargetTrial` wraps one trusted serial host callback
in both the native reversible trial and the serial-double CPU lattice trial.
False or an exception restores native state first and then target state. True
retains both. The callback owns the number of synchronized substeps and must
retain external controller/actor histories itself. This is not a portable save
format or the complete LiveWorld transaction.

The CPU snapshot deep-copies all working arrays: displacement/previous position,
velocity, damage, failure modes, plastic state, strain/adjacency/contact caches,
accumulated multipliers and schedules' working ranges. It also retains queued
force/wrench/gravity loads and remaining spans, source/contact work ledgers,
run/failure/capture counters, phase clocks, captures and first-failure receipts.
The restored array view is rebound to the restored storage. Upload and nested
trials reject; float, parallel and unavailable GPU backends reject before the
callback. Admission bounds the copied payload to 16 MiB, including captures and
source names. This is a copied-payload bound, not a total process-memory bound.

Native rollback now retains the exact constraint order/strong references,
joint/gear maps, stripped-gear receipts, last timestep, rope taut/slack distances,
rolling step inputs/cache flag and contact collector counters. Both ordinary
and spring trials restore that configuration before restoring native state.
This fixes the missing joint configuration and gear-removal boundary in the
previous recorder-only path. Existing native recorder/body/depth limits remain.

Fixed external contact is allowed inside the paired trial only. Ordinary native
trials retain their refusal of externally owned point mutation; paired trials
forbid nesting on both sides. Configuration/topology methods now guard body
mass/shape/damping, joint removal/friction/motors, kerf/ground-bite settings and
rolling laws. Dynamic forces and velocities remain recorded state. No material,
contact response, hand limit, force law or numerical tolerance changes.

Every abandoned native trial advances a separate plan generation. Prepared
contacts from that branch reject even if positions and the elapsed tick happen
to match the restored state. Failed restoration is an explicit discard-world
error, not permission to continue with a partly restored world.

## Verification experiment

The matched rollback fixtures retain the same 80 mm iron head, 240 x 40 x 40 mm
oak handle and declared ideal native fixing, 6 m/s initial speed, 120 mm target,
40 mm cells and 100 ns substeps. Catalog glass, oak and iron retain compiled
elastic/failure/plastic laws. Both clocks advance one warm-up step to establish
pending target load/capture state, then 2,048 paired steps (204.8 microseconds).
The shared bounded hand law queues one local root force/wrist torque each step;
its requested path is derived from the step index and recomputed on each retry.
A named target wrench lasts 20 steps total, including warm-up.

For each material and each XPBD/opt-in Verlet mode:

- Run the contact/hand/native/target batch and reject it after all substeps.
- Run it again, drain captures, clear queued target forces and throw a late error.
- Confirm exact restoration of observable arrays, native poses/velocities,
  history, counters, phase clocks, first-failure receipts and work accounts.
- Accept the retry and compare it with a separate never-rejected control.
- Require identical arrays, native motion, fixing load, finite-load expiry,
  contact work/counts and all captured displacement/damage/failure histories.
- Require actual glass bond failure and actual iron plastic work; oak remains
  a distinct non-brittle catalog comparison.

Measured accepted retries (same declared conditions):

| Mode | Target | Broken bonds | Plastic work (J) | Retry difference |
|---|---|---:|---:|---|
| XPBD | Glass | 16 | 0 | Exact |
| XPBD | Oak | 0 | 0 | Exact |
| XPBD | Iron | 0 | 1.41317623060 | Exact |
| Verlet | Glass | 15 | 0 | Exact |
| Verlet | Oak | 0 | 0 | Exact |
| Verlet | Iron | 0 | 2.28601628167 | Exact |

The comparison includes material-derived node mass and full native motion;
positions, velocities, histories, load/contact work and captures have zero
retry differences at their stored precision. Such replay does not certify
momentum/energy conservation of the accepted trajectory. Existing physical
phase balances and unclosed native/hand remainders remain separate.

Additional gates cover unsupported backends, 16 MiB payload refusal before any
callback, upload/nesting/configuration refusal, abandoned prepared plans and
continued use after refusal. Gear tests overload a real native coupling inside
both trial types, restore it and reproduce its strip time/motion. Loaded-rope
tests retain actual taut configuration and force readings after a tentative
slack step with a different timestep, including all three catalog materials.
Invalid/unrepresentable timestep inputs reject before state/metadata changes.

Exact replay is a rollback measurement on this Windows/MSVC build. It is not
cross-platform determinism, whole-world conservation, calibrated fracture or
finite fixing strength. The existing matched conservation/roundoff/refinement
measurements remain in the [hand checkpoint](held-strike-hand-checkpoint.md)
and [integrator checkpoint](held-strike-integrator-checkpoint.md); they are not
changed or reclassified by this transaction.

## Remaining integration

The ordinary browser Use action remains terrain-only. `playground/tools.js`
posts `world.groundAim` to `/api/world/tool/use`; `playground/tool_use.py`
resolves it through a terrain survey and ground working-point gesture. The
made object's name/contact witness is not passed through this action. The
paired trial is a compiled integration primitive used by tests, with no installed object-damage
route. Actual LiveWorld hand contexts, accepted scheduler state and other
external histories still require a complete coordinated boundary. Finite
interface failure, fragment/grip remapping, retained damaged-product history,
paid repair/replacement and restart remain under R3. Reference solver cost and
unclosed native/hand conservation remainders remain qualification limits.

## Build and publication

Environment: Windows, Visual Studio 2022 x64 Release, MSVC 19.44.35228.0,
MSBuild 17.14.51, CPU build, `BANJO_BUILD_LAB=OFF`, separate
`build/agent-paid-machine`. No interactive app route was installed or verified.
The in-use preview EXE/DLL are unchanged.

Verification: all 26 compiled affected ordinary suites passed in 68.70 seconds:
lattice Verlet, native lattice contact, fixed assembly contact, native point
contact, point rigid contact, pair impulse, contact ownership, conservative
contact, tetrahedron impulse, lattice external load, fast lattice, plasticity,
ground work, hand stroke, blade, fixing, LiveWorld, live determinism, gear,
reversible trial, spring trial, native contact capacity, rope, motor, circuit
and machine control. Registration passes 297/297 sources with zero exclusions;
changed links and `git diff --check` pass. The final build has no compiler warnings.

The ordinary regression command was:

```sh
ctest --test-dir build/agent-paid-machine -C Release --output-on-failure -LE long -R '^banjo_(lattice_verlet|native_lattice_contact|fixed_assembly_contact|native_point_contact|point_rigid_contact|pair_impulse|contact_ownership|conservative_contact|tetrahedron_contact_impulse|lattice_external_load|fast_lattice|lattice_plasticity|ground_work|hand_stroke|blade|fixing|live_world|live_determinism|gear|reversible_trial|spring_trial|native_contact_capacity|rope|motor|circuit|machine_control)_tests$'
python scripts/check-source-registration.py
``` Native capacity
checks also have an ordinary CTest entry, `banjo_native_contact_capacity_tests`,
which invokes `banjo_contact_capacity_tests --native-trials-only`. The original
six-case long suite remains registered unchanged in scope; tests print and flush
each case name before running it.

The first broad run included that already-labelled long capacity suite, whose
CMake note records about 2,039 seconds. It was interrupted after 623.19 seconds
without a result, after the other 25 suites passed. This does not qualify the
full material-network stress suite. Its two affected native observation and
trial/diagnostic cases passed separately. The publication gate uses `-LE long`
and includes the newly registered native capacity entry. No stress test or its
assertions was removed; the long network experiments remain a separate gate.

Published implementation and original verification record: `a80be5c3eeb516504240899824d9e394498ee666`
on GitHub main (ordinary fast-forward push). This documentation follow-up
records publication only; it introduces no additional physical validation.
