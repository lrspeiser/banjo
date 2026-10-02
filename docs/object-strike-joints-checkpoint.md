# Object strikes and native connections — October 2, 2026

## Implemented boundary

Ordinary tool Use accepts a named object under the current native sight line.
The server recasts the ray with the actor's attached tool excluded, checks the
actual hit and declared reach, and requires a connected native working point.
Client coordinates cannot grant an object hit. Full bags do not prevent
nongathering strikes. The page also queries the current sight line at click
time, so a stale preview does not choose the previous view.

The shared profile supplies speed, cadence, reach and repeat behavior. The
handler requests a native ready position/wrist, a 140 mm bounded press and a
60 mm withdrawal. At the default 4 Hz each stroke has a 125 ms give-up horizon,
80 m/s² requested acceleration and 25 mm lead. Readiness can refuse after two
wall-clock seconds. These are hand wishes: native contact determines motion,
work and finite fixing failure. Signed hand work and bounded native receipts
are retained. A disconnected point prevents withdrawal/repeat and refuses the
next use. No stock, skill, scripted damage, shards or launch impulse is granted.

Held source/target groups explicitly decline the old incomplete single-target
fracture island. Native contact and finite fixing failure stay active. Unheld
supported fracture retains its existing route. Held internal fracture is
**not integrated** with the paired native/CPU boundary. The shared LLM authoring
schema states this limit, and does not promise wear, per-hit damage or drops.

The compiled grip law accepts separate movement/wrist rates. Free bodies keep
100/100 rad/s. Fixed groups keep stable 20/20 idle feedback; bounded strokes
use 100 rad/s movement and 20 rad/s wrist feedback. Slow movement stalled short
heavy-tool strokes; fast idle position jumps destabilized the browser fixture.
The corrected policy passes the checks below. The coupled stroke reference
uses the same compiled 100/20 law. Caps remain 800 N / 60 N m. Constituent
geometry, mass, fixings, material laws and test tolerances are unchanged.

Reopening a carried assembled tool follows the native hand's `grip` mode.
A head/handle fixing no longer incorrectly selects haul controls. This is a
presentation correction; native ownership and constraints remain authoritative.

## Native measurements

Windows x64 Release, MSVC 19.44 / Visual Studio 2022, CPU Parallel, seed 971,
20 mm cells, zero gravity, 1/240 s steps. A 100 mm iron sphere head at
(.08, 1.5, 0) m connects to a 40×240×40 mm oak handle at (0, 1.38, 0) m.
Grip: (0, 1.3, 0) m. A 100 mm target cube at (.24, 1.5, 0) m connects to an
anchored 80 mm iron block at (.4, 1.5, 0) m. Source parts do not overlap.
Fixings are declared constraints; no connector area or glue calibration is
claimed. All bodies start at rest. After one second of unchanged-grip readiness,
the native press and connected withdrawal run; measurement ends after .5 s.

For target failure, its tension/shear capacities are 200 N and the source fixing
is ideal. For tool failure, source capacities are 60 N and the target fixing is
ideal. Ideal zero-capacity fixings are fixtures, not strength certifications.

| Failed connection | Target material | Target mass kg | Failure load N | Signed hand work J | Final mechanical energy J | Δmechanical − hand work J |
|---|---|---:|---:|---:|---:|---:|
| Target, 200 N | Glass | 2.5 | 866.594 | 1.86224 | .0174185 | −1.84482 |
| Target, 200 N | Oak | .7 | 709.914 | 1.82613 | .0391681 | −1.78696 |
| Target, 200 N | Iron | 7.87 | 875.611 | 1.86723 | .0175737 | −1.84966 |
| Tool, 60 N | Glass | 2.5 | 77.01 | 2.26047 | .00780754 | −2.25266 |
| Tool, 60 N | Oak | .7 | 77.01 | 2.22638 | .0123525 | −2.21402 |
| Tool, 60 N | Iron | 7.87 | 77.01 | 2.26023 | .00487279 | −2.25536 |

Initial mechanical energy is zero. Target contact occurs at .108333 s and its
connection fails at .129167 s. The weak **tool connection fails under hand
acceleration at .008333 s, before the freed head meets the target at .1 s**.
This proves failure during handling, not calibrated impact failure. Subsequent
head motion comes from native dynamics. The player retains the handle; the
working point disconnects; target mass and the remaining ideal fixing stay
intact. Whole reopening preserves failure and the named player's grip state.

The energy remainder is **unclosed**. These cases do not separate all native
damping, contact/fixing loss, numerical correction or anchored support work and
reactions. No full momentum/angular-momentum/energy closure, heat allocation,
wear, material realism or joint calibration is claimed. Density differences
remain; oak is not a brittle glass preset. No grain, fatigue, abrasion or
edge-blunting law is added.

A separate center-gripped iron sphere follows a bounded .8 m stroke at 4 m/s,
80 m/s² into each free target material under the same dt/cell/gravity. All
three make native contact. Glass reaches material admission and explicitly
declines its incomplete held island without stepping back or queuing fracture.
Oak and iron do not reach admission in this trial. This qualifies routing,
not held material fracture.

## Host and browser evidence

`tests/tool_use_tests.py`: 28 host tests pass, including native ray admission,
stale/occluded/malformed/far/near refusal, full bags, signed receipts, native
receipt-dependent repeat, detached-point refusal, vertical ready frames and
busy/listener cleanup. Stand-ins qualify controls only.

`tests/object_strike_tests.py`: two tests pass against the new native runner.
Authored 20 mm fixtures use gravity (0, −9.81, 0) m/s². Normal Inventory Take Up
and HTTP Use separate target fixings for glass/oak/iron, ignore client contact
coordinates and retain saved/reopened joint/player-hand records. Actual headless
Chrome reopens the carried mixed tool, selects the target through the native
ray and presses J; native impact and separation receipts arrive, with its
handle still held. This is not a paid manufacture/repair journey or avatar proof.

All five `tests/quick_tool_tests.py` cases pass: real Chrome held uses, five
rapid taps, stop/Esc, private excavated stock restart and failed-save retry.
The completion wait includes the whole action mode because the click-time ray
query precedes the observed Use request. An earlier wait counted the last tap
before its request started. The stale-view/no-yield failure is addressed by
the current click-time ray. Native physics tolerances were not relaxed.

## Verification and publication

Separate build: `build/agent-object-strike`, Visual Studio 2022 x64 Release,
`BANJO_BUILD_LAB=OFF`. Fifteen affected native suites pass in 100.91 s: hand
stroke, LiveWorld, determinism, ground work, blade, fixing, rope, motor,
circuit, machine control, thermo live, thermal mechanics, thermal geometry,
blade thermo and native lattice contact. The subsequently extended admission
fixture passes the rebuilt fixing suite. Registration: 297/297.
No full long material-network capacity, raylib window, macOS/Linux or cross-GPU
qualification is claimed. Chrome tests exercise actual browser key input.

Ignored local evidence: `build/resource-flow/object-strike-fixing-results.log`,
`object-strike-final-results.log`, `object-strike-host-results.log`,
`object-strike-http-results.log`, `object-strike-http.json`,
`object-strike-browser.json`, `object-strike-quick-final-results.log` and
`build/player-learning/quick-tool-browser.json`.

Publication: verified worktree based on `a0afab4f757f16cd99a99195b1a2c79c6cfeccf7`;
the published implementation revision is recorded after the ordinary push.
Running preview executables were not overwritten. Existing preview servers
have not been restarted onto this native build.

## Still required for R3

Couple actual held source/target internal damage, finite-interface reactions,
accepted clocks and grip remapping through the paired boundary. Qualify an
owned damaged source through Lab, reviewed finite material/energy/work,
collection/equip/use, failed saves/retries, another player and server restart.
Keep funded replacement distinct from genuine supported repair. Complete joint
condition/ownership handling for detached product parts. Ordinary use still
has no wear accumulation; R3 remains open.
