# Material-impact showcase

Experimental implemented checkpoint, September 5, 2026. The four packages in
`assets/material-showcase` are a compact, reproducible presentation sequence for
the `material-network-v2` backend. They use the same five material declarations
as `assets/runtime-v2/04-soft-tissue-offset-cut.json` without retuning strength,
fracture energy, damping, friction, or failure laws.

## Sequence and setup

The first three packages compare 2, 6, and 12 m/s strikes. Each contains three
parallel lanes: glass panel, oak panel, and an iron control panel. Every lane has
the same declared geometry, support, discretization, initial pose, and iron-ball
state apart from the controlled speed:

| Quantity | Declaration |
|---|---:|
| Panel dimensions | 0.24 x 0.36 x 0.04 m |
| Panel resolution | 6 x 9 x 2 cells |
| Panel cell spacing | 0.04 x 0.04 x 0.02 m |
| Panel centers | x = -0.40, 0, +0.40 m; y = 0.20 m; z = 0 |
| Ball diameter | 0.08 m |
| Ball start relative to panel center | (+0.015, +0.010, +0.200) m |
| Ball velocity | (0, 0, -2), (0, 0, -6), or (0, 0, -12) m/s |
| Step and solver iterations | 1/480 s; 24 iterations |

`pin_boundary: true` fixes the exterior x/y rows of each panel. These are
model-scale clamped door-panel proxies, not hinged doors: they do not swing,
transfer load through hinges, model a frame joint, or test fastener pull-out.
The identical 15 mm horizontal and 10 mm vertical offsets avoid a perfectly
symmetric center strike while preserving a matched comparison across materials
and speeds. The iron lane is a retained nonfracturing control.

The fourth package reuses the existing 0.18 x 0.16 x 0.16 m occupied-cell
soft-tissue ellipsoid and freely moving iron wedge at 4 m/s. Its names identify
the objects as a tomato and knife proxy for presentation, but the physical setup
remains the existing uncalibrated soft-tissue cutting experiment.

Load the directory in `banjo_network_lab`, or run one package headlessly for
three simulated seconds:

```powershell
build/win-joint-double/Release/banjo_network_lab.exe assets/material-showcase 01-clamped-panels-02mps.json --showcase
build/win-joint-double/Release/banjo_platform_cli.exe --run assets/material-showcase/01-clamped-panels-02mps.json 1440
```

Showcase mode starts at 0.25x inspection speed; its speed control cycles through
0.25x, 0.1x, and 1x. `K` cycles the skin, cells, structure, and the default
skin-plus-diagnostic-overlay views. In that overlay, red lines are actual failed
solver links and gold lines are softened links projected through the surface;
they are an x-ray diagnostic, not cracks added to the visible skin. Failed links
whose endpoints have separated beyond 1.5 times their rest length are omitted
from this overlay; the counts retain all historical failures. Right-drag
orbits the camera and the wheel zooms. Compare each material's reported broken
links, damaged links, connected components, largest retained component, first
damage, and first break. A zero-velocity derivative of the panel setup is the
unstruck gravity/rest control; it is generated only for probing and is
deliberately absent from the showcase directory.

## Interpretation limits

The panels are 40 mm thick with two 20 mm layers through thickness. Their cells
use spherical collision proxies with radius 0.49 times the smallest cell
spacing, so apparent ball/panel contact and visible cell surfaces are coarse.
This resolution is chosen to keep all three lanes interactive; it is not a
spatial-convergence result or a faithful window/door construction.

Glass and iron spring frequencies are far above this fixture's timestep. The
implicit solver remains bounded but attenuates short stress waves, so glass may
look too stiff or may fail less than expected at this resolution. Such an
outcome is a known under-resolution defect, not a physical claim that glass
outperforms oak. Oak is a directional axial lattice approximation without a
full grain, shear, or mixed-mode cutting law. The iron control has fracture
disabled and does not model yielding.

The tomato proxy has no skin, pulp pressure, seeds, fluid transport,
viscoelastic or rate response, and its material constants are not calibrated to
tomatoes. Its wedge contact can produce local cohesive-link failure, but a
damage front is not evidence of a clean macroscopic slice.

All fixtures advance cells, contacts, gravity, rigid tools, and constitutive
history on one clock. They contain no prebroken links, named-material outcome
dispatch, launch kicks, blade animation, or imposed post-contact motion.
`energy_residual_j` remains unavailable because contact/damping loss, support
work, and integration error are not yet closed. Record measurements as
experimental numerical observations with executable revision, timestep,
resolution, and simulated duration.

## Measured results

Headless measurements used a Release `banjo_platform_cli.exe` built from a
working tree based on `86541389a4ff867e36b4ec7bc0f74b4938e5af63`, after
rigid-sphere support was added. The executable SHA-256 was
`48b21eb119b4ecfe036bf35632ce37345d5d9e8fc0a0acc7c21c426fd2a75a83`.
The contact snapshot was at 0.15 s (72 steps); the final observation was at
3.0 s (1440 steps). Three final runs reproduced the same topology exactly.

| Fixture | Glass broken / damaged | Oak broken / damaged | Iron broken / damaged | 3 s physics time, three runs |
|---|---:|---:|---:|---:|
| Unstruck gravity/rest control | 0 / 0 | 0 / 0 | 0 / 0 | 444.75-456.66 ms |
| 2 m/s | 0 / 0 | 0 / 0 | 0 / 0 | 473.82-484.51 ms |
| 6 m/s | 0 / 0 | 0 / 2 | 0 / 0 | 572.19-577.21 ms |
| 12 m/s | 0 / 0 | 11 / 20 | 0 / 0 | 671.01-680.04 ms |

The 12 m/s oak panel first damaged at 0.016667 s and first broke at 0.01875 s.
Every panel retained one connected 108-cell component at 3 s, so the visible
claim is local internal link failure, not a hole or detached wooden piece. The
tomato proxy had 14 broken and 35 damaged links at both observation times,
first damage at 0.016667 s and first break at 0.03125 s; its 120 cells also
remained connected. Structural-bond display is needed to inspect these partial
internal failures through the nearly continuous cell skin.

Two scratch diagnostics were intentionally not promoted to showcase packages.
At 24 m/s and 1/480 s, oak reached 83 broken and 108 damaged links while
remaining one connected 108-cell component; glass and iron still had no damage. Repeating
the 12 m/s case at 1/960 s produced 1 broken/damaged glass link and 26 broken,
43 damaged oak links, versus 0/0 and 11/20 at 1/480 s. All panels remained
connected. This sensitivity, and glass changing from zero to one break under
timestep refinement, confirm that the fixture is not converged. Do not infer
calibrated real-material behavior from the apparent speed ordering.

## Verification and next gate

MSVC Release builds both the v1 and v2 viewers and the CLI. All 48 regression
suites have passing results: the full run passed 46, and the two new/extended
test suites passed on a focused rerun after their fixture construction and
incorrect settling assumption were corrected (7.40 s). The runtime laws were
not changed to satisfy these tests. The new checks cover sphere mass/inertia,
orientation, input rejection, free fall/contact, matched geometry and material
catalogs, low-speed and unstruck controls, local failures and retained mass/core.

Native Space release ran the 12 m/s comparison and the knife trial through three
simulated seconds at 0.25x with 60 FPS displayed and without the backlog pause.
Next-experiment, skin view and report export were checked in the normal input
loop; exported native reports retain their live timing and backlog. Offline
0.15 s images are separate, explicitly labeled captures. The final display adds
an oblique knife view, stable softened-link counts and physical-body labels.

G02 remains active. The next physical gate is resolved local contact/stress
transmission and knife separation under timestep, iteration and cell-size
refinement, with measured reactions and work. These fixtures do not establish
glass realism, clean slicing, full energy closure, automatic physics LOD, or
Minecraft-scale realtime performance.
