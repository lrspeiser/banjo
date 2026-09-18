# Workshop tests that visibly simulate

Base: main `b789faa6ecb37cd3a5eb41db8a6c29f9eed5ae31`.
This addresses the owner's report that the Test tab did not do anything.
No native solver, material law, or physics tolerance is changed.

## User-facing behavior

Test offers only implemented simulations of the selected product. The runtime
contract report, analytical point-force probe, and unrelated reference hoist are
removed from this tab. Specialist API operations remain available for existing
clients; their presence in the API is not a claim that they animate the product.
The inexpensive design checks live in Details rather than Test.

- Table and bench: drop onto the floor, slide with a declared starting speed,
  or apply a chosen load (blank load uses the design's existing load case).
- Cart: run its existing axle/bearing rolling experiment.
- Kettle: run its existing contained-water heating experiment.
- Other product types: show an explicit unavailable message and disable Run.
  In particular, the current default chair, stool, and shelf do not have a
  sufficiently reliable grid-resolved experiment to advertise here.

Run simulation calculates the isolated experiment and then automatically shows
its computed motion. The viewport frames the experiment's full trajectory. Pause,
scrub, reset, and replay operate on the returned numerical states; replay from
the end restarts at the beginning. Heating displays at 30x by default, with an
explicit display-speed control and intermediate measured temperatures. The
thermal colors map measured 20-100 C to blue-red; they are not a fluid simulation.

A visible running/error/result status replaces the old result. A response without
advancing simulation states is a failure, never a successful report-only run.
Changing controls or products still invalidates late responses. Frame updates
reuse meshes and update poses instead of rebuilding the voxel meshes and the
entire editor DOM at each sample. Topology/revision changes rebuild affected
meshes; simplified collision shapes remain explicitly identified.

## New native experiments and limits

Drop/slide compiles the selected single-material structural solid to exact
canonical Matter. The native body is checked against every compiled cell and
material before time advances. Drop declares an initial grid-aligned height and
zero speed; slide declares an initial +X velocity, not a sustained force. Gravity,
contact, and the existing failure solver produce subsequent motion. The outside
room is not opened, reset, or advanced. Native sessions close after the trial.

Missing components, disconnected geometry, mixed materials, unsupported roles,
and excessive cell/box budgets fail with an explanation; no smaller or simpler
product is silently substituted. Static-load tests also reject vanished parts.
Cart/kettle reject physical-skin edits their legacy fixture adapters cannot
honor. Their existing approximations remain: spherical wheel collision proxies,
and a contained thermal water proxy with grid-quantized mass, not sloshing or
pouring. New flexible sheets, smaller physical parts, and arbitrary articulated
experiments are separate work.

These are preset experiments calculated before display, not continuous remote
interactive sessions. A stationary load result can correctly mean the object
held in the current model; the display now says so. Fracture evaluations are not
proof that a crack occurred, and a completed run is not a strength certificate.
The single-material voxel/grid limitations are not removed by this checkpoint.

## Verification

The focused gate runs the existing fast Workshop suites, native bench and
installation tests, and required browser regressions. New cases check the visible
catalog, exact shapes, explicit initial conditions, invalid inputs, missing parts,
changed load mass, default table/bench motion, and intermediate measured heat.
A free-fall check compares glass/oak/iron under the same 0.4 m drop, 0.15 s duration,
and 1/120 s stepping, allowing 8 mm finite-step displacement error relative to
0.5*g*t^2. This is not a fracture calibration or conservation audit.

Browser checks require automatic timeline advancement, changed object poses AND
changed viewport pixels, stable mesh allocation while topology is unchanged,
replay from the end, changing measured temperature, unsupported-product handling,
and visible failure when the server returns no simulation. The previous
installation, state-invalidation and saved-design browser checks remain included.

Local Linux native execution uses the unchanged runtime built from this base
by GitHub Actions. Managed local Chromium refused localhost with
`ERR_BLOCKED_BY_ADMINISTRATOR`; local browser success is not claimed. Publication
requires all Chrome regressions in the isolated GitHub Actions runner.

## Published verification

The required gate passed 203 fast Workshop tests, 11 native bench tests,
15 native installation tests and all 15 Chrome browser regressions. Source
registration and JavaScript syntax checks passed. This is not a full CTest,
material calibration or cross-platform qualification.
Run: https://github.com/lrspeiser/banjo/actions/runs/35304716399


## Viewport-controls follow-up

Visual review of the first gate's screenshots found that Run and the current
measurements were below the fold in the parameter sidebar. The actual Run,
Pause/Replay, timeline, elapsed time, measured temperature, and failure messages
now live in a dock on the viewport. It follows the Test tab; there are no duplicate
controls or handlers. Mechanical results default to explicitly labelled 0.25x
slow display so short impacts are easier to inspect; heating remains 30x.
A 1280x720 browser regression uses real DevTools mouse input, checks button hit
testing and screen bounds before running, and requires an onscreen readout after
completion. Programmatic click success alone no longer qualifies this flow.

Viewport follow-up verification: all 203 fast checks, 11 native bench tests,
15 native installation tests and 17 required Chrome browser tests passed.
The added cases check a real onscreen mouse click at 1280x720 and delayed
history loading while curve settings are edited. Optional history no longer
redraws and erases unsubmitted editor values.
Run: https://github.com/lrspeiser/banjo/actions/runs/35305664505
