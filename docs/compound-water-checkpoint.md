# Exact compound objects in native water — October 3, 2026

Implemented and measured on Windows 11 x64, MSVC 19.44.35228, CPU reference,
against main base `c22a226`. Implementation **`483d92b0762ebe222021bb19884ff5994b714a7c`**
is published on GitHub main. [Machine-readable evidence](evidence/compound-water-checkpoint.json)
records source/binary hashes and the six baseline/fixed cases. This advances the water portion of R5; it does not close
native player bodies, physical cargo or the broader active goal.

## Defect and correction

`LiveWorld::waterBodies()` previously treated exact rigid compounds as voxel
pieces. They have no lattice cells, so their fluid surfaces and displaced volume
were empty. The retained preview binary gives all three matched objects gravity
alone and no water-force report. Even oak sinks in that baseline.

The adapter now carries each body's actual local collision parts, measured union
volume, material-derived mass and native pose into `WaterCoupling`. A closed
fluid surface is compiled from boxes and cylinders. Convex subtraction removes
covered faces and overlapping volume; earlier parts own duplicate outward
faces, while touching internal interfaces disappear. The force still enters
the existing Jolt/environment path once. No pose, velocity, float flag or
material contact law is assigned to make an object rise.

The symmetric-union oracle also exposed a **0.218 N m spurious pressure moment**.
Mean hydrostatic pressure had been applied at the geometric face centroid.
Pressure is linear with depth, so its moment needs the pressure-weighted
centroid. Triangle barycentric second moments now integrate that moment over
the clipped polygon. Drag retains its declared relative-motion quadrature.

Raised compounds contribute only connected vertical solid spans to the shallow
water obstacle bed. A deck above a base leaves its gap open. Surface/obstacle
keys contain complete part shapes, dimensions, offsets and rotations without
rounding or pointer aliases. Changing coupling settings clears surfaces. These
are geometric caches: forces are recomputed from the current water and body
state; no simulation outcome is reused.

## Matched measurements

Both 400 × 200 × 200 mm boxes overlap by 200 mm along x. Their union is
600 × 200 × 200 mm, **0.024 m³**. Each material starts at rest with its native
mass center at `[0, 0.6, 0] m` in the same generated 64 × 48 basin, lake level
1 m. Rigid timestep **1/240 s**, lattice admission grid **40 mm**; the exact
parts remain independent of that grid. Fluid grid **250 mm**, environment water
stride **1/60 s** with its existing stable substeps; declared drag coefficients
Cd 1 / Cf 0.01. No applied hand work,
motor work or external horizontal drive is used.

| Material | Density kg/m³ | Native mass kg | Initial buoyancy N | Initial weight N | First native vy m/s | y after 2 s m |
|---|---:|---:|---:|---:|---:|---:|
| Glass | 2,500 | 60.00 | 235.44 | 588.60 | −0.024525 | 0.304490 |
| Oak | 700 | 16.80 | 235.44 | 164.808 | +0.0175179 | 0.937051 |
| Iron | 7,870 | 188.88 | 235.44 | 1,852.9128 | −0.0356812 | 0.303631 |

First-step velocity residuals against `(rho_water/rho_body − 1) g dt` are
−1.64509e−9 / +3.83598e−9 / −2.90938e−9 m/s respectively, within the declared
**1e−5 m/s** bound. Force and weight checks use **1e−5 N**. Water-volume residuals
after the matched run are at most **6.4e−14 m³**, against `1e−10 × volume`.
Source mass/inertia and the rigid solver are retained; stiffness is not used as
a buoyancy parameter. Glass's brittle law and oak's grain/plasticity are not
implemented by these exact rigid bodies.

The analytical union checks cover full/partial immersion, touching and duplicate
parts, cylinders rotated in their own frame, off-center buoyancy torque, a
submicron geometry edit, current-relative drag and open/closed/removed obstacles.
Equal union volume produces equal hydrostatic force for glass, oak and iron;
their densities change weight. Horizontal drag equals the sum of its returned
water reactions within **1e−9 N**. Symmetric pressure moment and off-center
moment use **1e−8 N m**, full-volume pressure uses **1e−8 N**. These tolerances
are new analytical checks; no existing regression tolerance is widened.

The direct native process comparison records zero water forces and vy
−0.04088 m/s for every baseline material. Its oak reaches the bed around
0.304 m. The fixed process reports one force per object and reproduces the
material-dependent outcomes above. Complete saved native JSON equals the JSON
obtained after terminating and reopening each process, for all six baseline/
fixed cases. No source pose reset or missing-body substitution is used.

Two seconds of fixed single-compound simulation plus line-protocol output take
**0.0655–0.0743 s** locally, versus **0.0251–0.0302 s** with the missing forces.
This is a small Windows fixture cost, not a scaling or frame-rate qualification.
The retained full-valley performance case runs 60 simulated seconds in
4.71074 s (0.07851× real time); its worst 470.16 ms step includes a fracture.

## Verification and preview

Separate headless build: `build/agent-native-water`, Visual Studio 17 2022,
`BANJO_BUILD_LAB=OFF`. Builds include `banjo_water_tests`, `banjo_live_world_run`,
`banjo_c`, `banjo_valley_live_tests` and `banjo_platform_cli`.

```powershell
python scripts/check-source-registration.py
cmake --build build/agent-native-water --config Release --target banjo_water_tests banjo_live_world_run banjo_c banjo_valley_live_tests banjo_platform_cli --parallel 4
ctest --test-dir build/agent-native-water -C Release -R '^banjo_(water_tests|valley_live_tests|environment_ffi_tests|precise_rigid_live_tests)$' --output-on-failure
```

All four registered suites pass: **21 water, 15 environment FFI, 15 live valley
and 36 exact-installation checks**, 22.34 s total. The registered sustained-hauling
suite also passes both methods in **272.89 s**, under its unchanged 300 s timeout:
three actual loads on each of two retained layouts, and five on the retained world
seed, with native paid processing and exact restart. That extends the existing R4
fixtures under this pressure correction; wider terrain/recovery gates remain open.
Registration: **298/298 sources,
10 CMake files, zero exclusions**. The first attempt to relink the retained
preview runner was refused by Windows because it was running. A later shared
intermediate-directory build conflicted; it was stopped and superseded by the
successful independent configure/build above. Its interrupted retained-core
intermediate was removed and the retained `banjo_core` target rebuilt successfully.
Running preview executables and libraries were not replaced.

The isolated authored comparison is at
`http://127.0.0.1:8775/world?world=1be55ed3c1a94723b494a8ef9ff72365`.
Normal browser menu/cursor/drag navigation shows the oak above the surface and
the dense objects submerged. Native clock/rendering continue. No browser console
errors; the existing Three.js shadow-map deprecation warning remains. Screenshot,
raw measurements, binary hashes, native snapshots and test logs stay under
ignored `build/agent-native-water/`. The fixture is authored test geometry,
not a paid player opening, AI playthrough, native avatar or cargo qualification.
Existing previews, including the owner's 8771, are unchanged.

## Physical boundaries and remaining acceptance

- Box union surfaces are polygon-clipped. Cylinders use 48–128 volume-matched
  facets, with maximum radial difference **0.143%** at 48 facets. Fluid surface
  union and the source's sampled curved-overlap mass integration may differ for
  intersecting cylinders. General curved/mixed-assembly convergence remains open.
- Local surface/current sampling, declared drag coefficients and obstacle sealing
  remain the existing approximations. Fine channels/gaps below the fluid grid,
  splash/waves and free-surface displacement are not newly resolved. A cylinder's
  obstacle span uses its actual analytic geometry rather than a bounding box.
- Horizontal drag reactions enter water once. Hydrostatic vertical reactions are
  carried by the untracked bed pressure in this shallow-water model. Force,
  torque and volume checks do **not** close full vertical momentum or total energy
  accounts. Drag is dissipative; numerical/bed work and full energy transfers still
  need broader R5 accounting. No general conservation or material realism claim.
- Human/AI motion remains reported camera/route-controller state. Native avatar
  creation, collision, locomotion, hand reactions and water response remain the
  next R5 integration. Hopper/player cargo still needs actual mass, inertia,
  geometry and supported receiving/unloading reactions. Processed constituent
  incorporation remains open.
- Wider R4 pit/shore/grade/obstacle and R1/R6 supply/model acceptance remain active.
  R3 repair/wear remains owner-paused.
