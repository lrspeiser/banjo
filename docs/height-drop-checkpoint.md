# Off-centre drops and iron-on-glass height comparison

## Implemented

A new rigid package retains the earlier centred drop as a control and starts the falling glass/oak/iron spheres 15 mm to one side. No lateral velocity, random kick or post-collision correction is imposed. Contact geometry supplies the oblique normal response and friction/torque evolve through the rigid solver. Perfectly symmetric smooth-sphere drops can legitimately remain on their centre line. Surface roughness, non-sphericity and manufacturing defects are further physical inputs, not implemented by the offset fixture.

Four new reference packages drop iron onto glass and onto oak side by side, from centre heights 0.15, 0.5, 1.5 and 3 m. Every sphere has radius 45 mm; each target starts at centre height 45 mm on concrete, and each iron sphere starts 4 mm off the target centre line, with zero velocity/spin. Gravity supplies impact energy. Oak and iron are retained as comparison materials with their failure laws explicitly unsupported.

The reference solver now contacts a finite axis-aligned solid ground box, using the existing compliant contact, friction, damping and reaction/energy accounting. Both top and side/bottom contacts follow box closest-point geometry. This does not change the fracture threshold, impose a fragment count or convert the floor into an infinite plane. The platform admits this support through its finite-ground capability. Reference admission now explicitly matches the existing solver's nine-ball/45-mm-radius limit, correcting the previous overly broad declaration.

The visual client displays broken-bond count, accepts mouse-wheel zoom, and batches reference work up to 24 ticks while respecting each package's call limit. It displays actual completed physical states. It is still slower than real time and does not claim that rendering FPS measures simulation speed.

## Results and bounds

Windows MSVC Release, double-position build. After one second in the rigid offset test:

| Material | Centred upper sphere x (m) | +15 mm initial offset: final x (m) |
| --- | ---: | ---: |
| Glass | 0 | 0.249504 |
| Oak | 0 | 0.204733 |
| Iron | 0 | 0.218180 |

Negative offsets produce the mirrored negative values. All nine material/offset cases pass. The difference follows geometry and material contact response, not a synthetic random deflection.

At 1.1 simulated seconds in the four-body reference drop:

| Upper centre height (m) | Glass bonds broken | Total connected groups | Energy residual (J) |
| --- | ---: | ---: | ---: |
| 0.15 | 0 | 4 | -0.0000368805 |
| 0.5 | 53 | 9 | 0.00437775 |
| 1.5 | 74 | 18 | 0.00172034 |
| 3 | 71 | 15 | 0.00193838 |

Only glass object 1 loses bonds. Both iron spheres and the oak target remain connected; this is not evidence of implemented wood fracture or metal plasticity. The common final clock time gives different durations after first impact. Counts are not monotonic with height and are not a calibrated real-glass shattering curve. Contact geometry is a coarse 19-cell approximation, and strength at individual links is not macroscopic fracture calibration.

The original four reference runs each took roughly 35–40 seconds of process wall time for 1.1 simulated seconds on the desktop. Performance remains an open platform requirement.

The two affected suites pass in 41.52 s. They include three-material flat-support settling without damage, reaction/momentum and energy checks, free fall beyond the finite ground edge, and mirrored offset tests. The final API suite is rerun after exposing the fracture count. All 26 packaged examples pass the final matrix. The example matrix also checks that only the glass target can fracture in these height fixtures and that its energy residual stays within the existing 1% budget.

Native verification shows the iron-on-glass drop progressing to 53 broken bonds and separated glass cells while the wood stays connected. Zoom and pause work. The saved image shows the observed result, not an authored shatter animation.

## Run and next work

Examples 22–26 in the Platform Test Laboratory are the offset comparison followed by the four heights. Next/Previous selects a height. Run starts the drop; Reset restores initial conditions; mouse wheel zooms. The height displayed in the package name is the upper sphere's starting centre height above the floor, not the free clearance above its target.

Next: attribute fracture events to time-aligned local contact loads; compare equal post-impact windows; refine geometry and defect distributions; calibrate strength/fracture work and convergence; retain mirrored/no-offset controls. Improve the runtime through accounted local activation and coarsening, not relaxed strength or hidden replay. All original platform mechanics remain required.
