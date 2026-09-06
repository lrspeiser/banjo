# Generated objects: visual and numerical validation

**Latest follow-up:** The [contact and reaction checkpoint](contact-fracture-checkpoint.md) removes the recorded 537-cell capacity fault and corrects spring reaction direction. Its new measurements supersede the historical outcomes below; dense networks and fracture convergence remain open.

The authoring API is exercised through executable declarations, the native
`banjo_network_lab`, and independent analytical controls. Passing package
validation does not certify material realism. This checkpoint does not change
material constants, contact response, or fracture laws.

## Reproduce

From the repository root, with the Release binaries built:

```powershell
python examples/authoring/verify_physics.py --engine build/win-joint-double/Release/banjo_platform_cli.exe --output build/generated-physics-new
build/win-joint-double/Release/banjo_network_lab.exe build/generated-physics-new/scenes panels_12mps.json --studio --live-report build/live-trial.json
```

The output directory must be new. The script generates scenes from
`banjo_authoring.py` and `presets.json`, with report files kept outside the
scene directory. The studio reads those same generated packages. Release runs
three simulated seconds; reset restores the authored initial state. Next and
Previous choose a generated scene. Skin, cell, and bond views expose the same
accepted state. The time button provides slow motion for inspection, but
performance measurements must use a fresh reset at 1x.

`--studio` starts at 1x, frames the authored scene, displays object response and
frame/backlog measurements, and retains the normal interactive event loop.
`--live-report` exports once on completion, overload or a runtime fault; its parent directory
must exist. A failed write is reported in the window and the Export button
retries the same path. Reusing the path replaces the previous report.

## Measurement boundaries

- Native live `presentation.trial` reports active frame p50/p95/p99/max, frames
  over 20 ms, CPU work p95, active wall time, peak simulation backlog, overload
  pauses, and mixed-speed/manual-step flags. Paused and idle frames are excluded.
- Full active frame time includes physics, report queries, rendering submission
  and frame pacing. Work time stops before `EndDrawing`, excluding its swap and
  pacing work. Neither measures hardware input-to-photon latency or GPU time.
- Scene preparation is timed separately; the engine also reports its own load
  and step costs. Skin-query timings include idle queries and are not a complete
  rendering budget.
- The loop preserves backlog, caps catch-up at 24 steps per frame, and pauses
  above 250 ms lag. An overload must not be presented as a realtime pass.
- `--capture` is an offline fixed-step illustration. Its exported report says
  so explicitly; it cannot be used to claim interactive speed.
- Headless timings exclude rendering. Small scenes on this workstation do not
  establish a Minecraft-scale world budget.

## Acceptance gates

1. All twelve catalog objects must be constructed by code and admitted. Mass
   must agree with the authored density/volume or initial accepted cell mass.
2. Glass, oak and iron rigid free flight must match the analytical solution
   within documented integration and floating-point bounds. Without contact or
   external forces, velocity, momentum and kinetic energy must be retained.
3. Matched panel impacts at 2, 6 and 12 m/s, knife/tomato, mixed network-ball
   drops and support controls must complete or explicitly expose overload.
4. Identical package/timestep runs must repeat their physical outcomes, and
   native/headless accepted states must agree at the same elapsed time.
5. Material fracture must converge under time, iteration, contact and spatial
   refinement before it is called realistic. Halving the timestep is an initial
   diagnostic, not a complete convergence study or experimental calibration.

The glass stress-transmission and tomato-separation defects remain G02 work.
M01-M30 and P01-P10 remain retained in the scorecard. The next performance gate
is a declared active-body/contact/load matrix with bounded physical detail;
the current network still keeps every cell active.

## Measured checkpoint (2026-09-06)

Windows Release, MSVC 1944, Core Ultra 9 285K, RTX 5090; fixed step 1/480 s,
24 solver iterations, skin plus diagnostic overlay. The comparison panels
contain 327 physical bodies and the knife/tomato contains 121. These remain
model-scale clamped panels and a soft-tissue proxy, not calibrated doors/fruit.

All twelve generated catalog templates admitted and completed eight steps
with unchanged total object mass. For glass/oak/iron rigid balls, 0.5 s free
flight had 5.1082 mm continuous-position error (the expected first-order
fixed-step integration error) and 3.67e-6 m/s velocity error. Zero-gravity
translation error was below 6.71e-8 m; reported momentum and kinetic energy
were unchanged. Three initially supported rigid balls remained at 0.04 m
center height to within 3.9e-9 m, with zero final velocity after 3 s.

The three panel speeds and knife/tomato each repeated their discrete outcomes
across three headless trials. Five completed native trials matched every
reported physical field of fresh headless runs at the same tick; compiler
metadata, performance and skin-query/cache counters were excluded. This
comparison does not expose every internal cell history; separate skin-isolation
regressions cover physical mutation.

Initial native 1x results (one completed 3 s trial per row):

| Scene | Bodies | Active wall s | Frame p95 ms | Peak backlog ms |
|---|---:|---:|---:|---:|
| Supported glass/oak/iron | 3 | 3.000 | 16.855 | 0.252 |
| Panels, 2 m/s | 327 | 3.001 | 16.928 | 2.046 |
| Panels, 6 m/s | 327 | 3.005 | 17.006 | 1.888 |
| Panels, 12 m/s | 327 | 3.003 | 17.105 | 1.954 |
| Knife/tomato | 121 | 3.012 | 17.040 | 2.070 |

No measured active frame exceeded 20 ms and none of these five trials
overloaded. Scene preparation was 1.96-8.83 ms. These are CPU frame readings
from the normal window loop, not offline screenshots or end-to-end input latency.

After finalizing floor-aware framing and preserving unconsumed time on a
failed step, the 12 m/s native trial was repeated: 3.002 s active wall,
16.983 ms frame p95, 1.661 ms peak backlog, and the same reported physics as
the headless run. The final build passes all 48 existing C++ regression suites
in 82.80 s. The new exploratory runtime failure below remains a separate failed
gate, not a passing regression result.

### Failed gates retained

**Fracture realism fails refinement.** At 2/6/12 m/s, glass has 0/0/0 broken
bonds and oak 0/0/11; iron has none. At 12 m/s, halving dt to 1/960 changes
glass 0 to 1 and oak 11 to 26. Knife/tomato changes 14 to 25 broken bonds.
All panels and the tomato retain their entire cell count in one connected
component. These are not converged glass shattering or a separated tomato slice.
Mass retention and repeatability do not validate fracture or energy closure.

**The 537-cell network-ball drop fails execution.** Three 179-cell balls
admit, then exhaust the contact-constraint buffer on the first update
(`ContactConstraintsFull`, flags=4), before any tick is accepted. Jolt is
configured for 8192 bodies, 16384 body pairs and 8192 contact constraints;
the network's 1024-body budget is not a guarantee that contact demand fits.
The default speculative contact distance is 0.02 m, larger than these cells'
approximately 0.0056 m radii; its contribution requires a measured policy
study. The failure is present before gravity can accumulate or a later impact
can occur. Do not interpret the partially mutated faulted state as accepted
physics. No capacities or material constants were increased to hide this case.

The verification command returns nonzero for this recorded runtime failure,
while separately reporting passed analytical/admission gates. Its realism
status remains explicitly not passed. Diagnostic messages now identify the
actual exhausted resource, and native fault reports preserve this evidence.

Next: budget/specify contact generation and reject or schedule unsupported
dense scenes before committing a tick; measure active contact/cell load growth;
then converge stress transmission and cutting with time/contact/space/work
checks. Whole-world realtime and calibrated material response remain open.
