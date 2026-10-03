# Retained rover brakes after recovery and power cycles

October 3, 2026. Host controller checkpoint against GitHub main `d8eb072`,
Windows / Python 3.13 / existing MSVC Release engines under
`build/agent-object-strike/Release`. No C++, native binaries, material law,
traction, terrain resolution, grip strength or solver tolerance changes.
**Published:** implementation/tests `ae8c46f` are on GitHub main. No separate
production deployment was performed; the owner's port 8771 preview is unchanged.

## Defect and change

Native power-off clears its movement request, including a routine's indefinite
waiting/braking request. The persisted host frame can still contain an issued
blocked route or a retreat stop. After power-on, native reflexes can drive while
the host waits for actual speed to fall before replanning. A saved refusal is
not an active brake.

Those two waiting states now reassert the native waiting request when it is
absent. They then observe actual speed/turning before replanning. Current step,
load, route refusal, explicit retry latch and recovery ownership are retained.
No velocity, orientation or position is assigned. A moving rover does not gain
permission to dig, dump or report arrival from this repair.

## Controlled retained-shore experiment

The ordinary test world on port 8774 has a retained rover at
`[10.95418, 0.47354, 1.08015] m`, after three deliveries, with a fourth 40 kg load
(12 kg copper ore and measured native sand/soil). Its center survey reports
0.265579 m water depth and approximately 0.597543 m/s water speed. Refusing a
new dry route there is correct. The source of the original shore entry is
still unqualified: a fresh unedited world with its same terrain/resource seed
does not reproduce it within the declared 440 simulated seconds.

An isolated frozen copy of the actual saved world is restored for both variants.
An authenticated analytical observer acquires the ordinary 800 N / 60 N m
recovery grip, lifts, pulls to surveyed dry ground at `[9.2, 4.3] m`, lowers,
releases and turns the program on. Native simulation uses 50 mm scene matter
and `dt = 1/240 s`. Both runs preserve the 40 kg load and have identical recovery
force/motion histories; peak force is 788.242 N and final signed external hand
work is 742.775 J. This is a headless declared observer, not a browser walk or
a native reacting avatar.

| Controller | Result after normal release/power-on |
| --- | --- |
| Published `d8eb072` | No fourth delivery in 20 s; rover moves to `[4.87483, 1.04945, 0.00449] m` without an active request |
| This change | Actual fourth delivery at 3.6 s; total delivered becomes 160 kg and hopper is empty |

Full server restart preserves each final routine exactly, including the fixed
receiving result. No ore grant, pose reset, added impulse, fake traction or
changed material law passes the experiment. Per-tick automatic disk snapshots
are disabled in this experiment; native ground/receiving transactions keep
their normal paired saves, and the final checkpoint is explicitly saved and
reopened. It is not a measurement of production autosave cost.

Local ignored source copy and evidence: `build/shore-recovery-frozen/`,
`build/shore-recovery-probe.py`, `build/resource-flow/shore-recovery-baseline.json`
and `shore-recovery-fixed.json`. The frozen private diagnostic world is not
published. Registered tests exercise the native lost-request state separately.
An earlier exploratory script left SQLite backup connections open and failed
Windows temporary-directory cleanup; explicit close resolves that fixture
error. No application persistence or test tolerance was weakened.

## Regression evidence

- `banjo_rover_brain_tests` retains the complete registered suite and adds
  blocked/latching power-cycle, restored retreat-stop and actual native brake
  cases. The native case declares retained controller history in a dry room;
  it does not fabricate a mined load or claim that room has the shore above.
- `banjo_generated_rover_repeat_tests` retains the previous three loads on each
  of two layouts. A new same-seed case requires five actual 40 kg deliveries
  within 440 s, each containing 12 kg native-collected copper ore, actual
  processing output, and exact whole-server routine/goods restart. It preserves
  the existing receiving APIs and uses explicit milestone snapshots.
- Source registration remains 297/297 sources in ten CMake files with no
  exclusions. Python compilation, whitespace and local documentation links
  are checked before publishing. Final suite results are recorded below.

Final Windows results:

| Registered CTest command (`-C Release --output-on-failure`) | Result |
| --- | --- |
| `-R '^banjo_rover_brain_tests$'` | 60 methods pass; 9.83 s suite wall time |
| `-R '^banjo_generated_rover_repeat_tests$'` | Both methods pass; 257.82 s, unchanged 300 s timeout |

The new five-load case delivers at 52.2, 145.0, 202.6, 300.4 and 387.0 simulated
seconds. The existing two-layout case keeps its three deliveries per layout
and exact restart assertions. These tests use the actual native engine; the
legacy browser module they import is not invoked. No full browser recovery,
new material law, cross-platform or production-load qualification is implied.

## Limits and remaining work

The rover's existing oak/glass/iron assembly and its native mass are unchanged;
the 40 kg hopper remains a goods account without native payload inertia. Hand
work is external work, not an avatar energy budget or full momentum/energy
closure. This host controller change adds no material-dependent physical claim;
the [matched wheel/grade boundaries](rover-grades.md) remain unchanged.

The lost-brake recovery defect closes. Broader R4 pit/shore/grade/obstacle
families, original shore-entry diagnosis and ordinary human recovery remain
open. R5 still requires native avatar contact/water reactions and physical
cargo mass, inertia and receiving. Material recognition, wider supply graphs
and live-model progression remain active. R3 remains owner-paused.
