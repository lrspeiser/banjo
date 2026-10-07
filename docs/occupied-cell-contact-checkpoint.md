# Occupied cuboid contact: experimental rewrite checkpoint

October 6, 2026. Baseline main `5d15a10f`. This advances W08 contact geometry and its CPU reference, not terrain activation or a gameplay replacement. PR #2 is merged at its retained `138260d2` head; its checkpoint and remaining conservation/calibration requirements were reviewed. Current main's runtime and frame-control changes are preserved.

## Native query and response boundaries

`JoltWorld::materialShapeContacts` queries an occupied cuboid or sphere against the body's actual native shape. Cuboid faces/corners use their full declared lengths and unit orientation, with zero envelope edge rounding. Existing source-shape rounding remains unchanged. Dimensions, radius, orientation and separation returned by the query reflect the float geometry used by Jolt. The spherical `pointShapeContacts` delegates to the same search/collection/material path, avoiding a second collision implementation.

Queries retain every source-leaf witness within the admitted search distance, native compound leaf/material identity, signed gap and both surface points. Compound holes remain empty. The double world origin is subtracted before native local float geometry is evaluated. Overflow refuses the entire result rather than truncating contacts. Cuboid dimensions are bounded to 2 µm–200 m, sphere radius to 1 µm–100 m, separation to 0–1 m and witness count to 1–256. Unsupported cylinder envelopes, nonunit rotations and invalid sizes refuse. Native source cylinders/convexes still use Jolt's source geometry; this envelope API adds no new material law.

The finite-source experiment feeds these cuboid witnesses into the existing `NativeFixedContact`/serial-double Verlet coupling. An actual iron head and oak handle retain their native ideal fixing, finite mass/inertia and recoil. Both source members are queried; direct contact with an ideal clamped cell remains explicitly unsupported. Pair response has one external owner. Equal/opposite point transfers, fixing reactions, support impulses, contact loss, constitutive histories and native/target numerical changes remain audited. No fragment launch, fake impulse, prescribed target motion or material-name behavior is introduced.

**This remains a translational nodal contact reduction.** Cell centres own point mass; the law does not solve independent finite-cell spin or distribute surface tractions over a deforming continuum face. Cuboid geometry does not implement that missing law. Cell orientations stay at the declared reference axes in this fixture. Self-contact, finite neighbouring terrain, calibrated rock/soil/fracture/wear, collision-proxy handoff and settling remain open.

## Matched experiment and evidence

[Structured measurements and executable hashes](evidence/occupied-cell-contact-2026-10-06.json) record Windows x64 / MSVC 19.44.35228 Release / Python 3.13.5. No constitutive/contact coefficients or earlier numerical tolerances change. Glass/oak/iron retain material-derived density, stiffness, strength and supported plastic settings; oak remains laboratory-only.

All twelve new cases use a 120 mm target cube, 27 cells of 40 mm, horizon 1, nine stationary far-face clamps, no gravity/damping, and a finite source initially moving at 6 m/s. Head dimensions are (80 mm, width, 80 mm); the handle is (240, 40, 40) mm. Target origin is (0.1, 0, 0) m, so its occupied face begins at contact with the head rather than already inside it. This initial source velocity defines a laboratory impact, not a hand force or debris launch. Each case runs 204.8 µs: 2,048 × 100 ns or 4,096 × 50 ns.

| Target | Head mm | Initially contacted forward cells | Failed bonds, 100/50 ns | Integration error J, 100/50 ns |
|---|---:|---:|---:|---:|
| Glass | 40 | 3 | 13 / 13 | 0.000269423 / 0.0000671071 |
| Oak | 40 | 3 | 0 / 0 | 0.0000602209 / 0.0000156031 |
| Iron | 40 | 3 | 0 / 0 | 0.000794549 / 0.000201096 |
| Glass | 120 | 9 | 9 / 9 | 0.000652221 / 0.000162110 |
| Oak | 120 | 9 | 0 / 0 | 0.000168289 / 0.0000429853 |
| Iron | 120 | 9 | 0 / 0 | 0.00210901 / 0.000528729 |

Target masses are 4.32 / 1.2096 / 13.59936 kg; source mass/inertia naturally increase with head width. This differs from the retained spherical experiment: its target origin remains 0.095 m and its contact radius 16 mm. It is retained as a regression, not presented as identical occupied geometry. Preliminary cuboid reuse of that origin embedded the cube faces by 5 mm and produced 15/13 glass failures; that initial condition was rejected. New initially touching cases agree on failure count, but this does not establish spatial/topology convergence or realistic glass/oak fracture.

Full fixture trajectory attribution agrees within the retained 1e−9 SI momentum/angular and 1e−10 J energy bounds. Raw native-step errors remain visible: up to 6.04e−7 N s linear, 1.02e−6 kg m²/s angular and 0.00210869 J unallocated mechanical energy before numerical-step attribution. They are not heat or proof of full-world conservation. Every paired refused trial restores both solvers' motion, clock, damage, plastic history and support accounts. Post-contact partition/128-step continuation also retains exact cell/bond history and mass.

Observed wall costs are 0.240–0.696 s per 204.8 µs experiment, including the rollback probe: approximately 1,172–3,400 times simulated duration. This CPU reference is **not fast enough for gameplay**; no two-uses-per-second or 10 ft digging claim follows.

## Verification and next work

Four rebuilt native CTest entries pass: shape/contact witnesses, coupled native/lattice contact, tool admission and native tool use. Seventeen actual-native Rust worker tests pass against the rebuilt runner, including twelve positive first uses. Source registration passes 312/312. Native geometry checks cover face/corner contacts omitted by spherical envelopes, rotated source/cell pairs, native spheres, compound voids/leaf materials, distant origin, no mutation and whole-result overflow refusal.

The strict repeat-yield command still exits 1 for four iron fixtures. The browser World on 18890 and material UI on 18891 remain on their existing processes; no UI/input, physical-phone, macOS/GPU, full regression or gameplay migration qualification is claimed. No retained subsystem is deleted.

Next: qualify finite-volume surface response and supported anchored ground activation; retain exact constituent histories through native collision/settling; close full player/tool/ground/release accounts; profile and qualify a faster solver against this reference; then require useful repeated excavation and the actual player speed task. The full W00–W17 scope remains active.
