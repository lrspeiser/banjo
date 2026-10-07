# Solid patch boundaries and finite tool contact

October 6, 2026. Source base main `15273e3f`. This experimental CPU reference adds
explicit attachment to a stationary boundary and native tool contact across the
actual head width. It is a prerequisite for W08/W09, not the live terrain
replacement. The browser demo and its player worlds are unchanged.

## Implemented boundary contract

Serial-double Verlet now accepts explicitly clamped nodes: positive physical
mass, zero inverse mass, zero velocity and stationary previous position. Movable
nodes still require reciprocal mass. Invalid declarations are refused before
replacing uploaded state. Internal contacts remain unsupported in this reference.
Clamps with bond damping are refused because damping support reactions are not
qualified. Wrench regions and instantaneous finite-point transfers still require
movable nodes; direct tool/clamp contact is not silently treated as finite mass.

Clamped nodes stay at their declared positions through integration. No moving
velocity is overwritten and no rolling/no-slip motion is imposed. Prevented bond
impulses are recorded as support impulses/torques about the world origin, separate
from bond arithmetic roundoff. The support receives their negatives. Nodal loads
and gravity on clamps retain source impulses and cancelling support reactions,
with exactly zero kinetic work and unchanged load expiry. This is an **ideal
stationary external boundary**, not finite solved neighbouring terrain, support
stiffness calibration or a strength model.

`SolidMatterPatch` accepts source-node clamp declarations and includes boundary
impulses in its balance. Components report whether their surviving graph reaches
a boundary cell. Every cell retains source ID, mass, volume, position and velocity.
No debris is spawned here. This classification is intended to prevent attached
matter from being incorrectly handed off as free debris in the later adapter.

## Analytical and constituent checks

A 100 N/m spring with a clamped 2 kg cell and movable 3 kg cell matches the harmonic
solution, refining at second order at 100/200/400 steps over 0.5 s. Its offset
origin tests support torque. Force/gravity on two clamped cells cause zero motion
and work, with exact cancelling support accounts. Rejected reversible trials
restore reactions, state and clock. Moving clamps, inconsistent history, negative
inverse mass, damping and finite-point transfer to clamps are refused.
Review reproduced a norm-underflow defect with nonzero 1e-200 m/s clamp velocity.
Component-wise zero/history checks now refuse it without replacing prior state;
the regression also checks a 1e-200 m stationary-history mismatch. Boundary
declarations are capped before copying their source-node list.

Matched glass/oak/iron patches: 0.25 m cube, 50 mm cells, horizon 2, 25 bottom-face
clamps, origin (2, 0.6, -1) m, dt 100 ns, 512 steps; top central cell receives
(10,000, -20,000, 30,000) N. This is declared laboratory traction, not a hand-force
calibration. The existing isotropic elastic/strength reference is unchanged;
grain, plasticity in this wrapper, fatigue, soil and calibrated fracture energy
remain unsupported.

| Material | Mass kg | Source work J | Support impulse N s | Integration error J |
|---|---:|---:|---:|---:|
| Glass | 39.0625 | 0.330535 | 0.546924 | 0.00000890899 |
| Oak | 10.9375 | 1.76406 | 0.254934 | 0.0000148599 |
| Iron | 122.96875 | 0.107536 | 0.518565 | 0.00000269474 |

All retain one attached component with no failed bonds. Source/support/roundoff
momentum and angular residuals are below 5e-14 SI; energy residuals after measured
integration error are below 1.2e-13 J. Work differs through density/stiffness,
not material-name rules. A separate initially whole glass patch receives a 1 MN
upward traction on one top cell for 512 steps: 4,110.26 J supplied, 96 failed
bonds, two components correctly classified as one attached and one free, with all
125 cells retained. This high load is not a normal strike or calibrated crack work.

## Finite head/patch comparison

Existing `NativeFixedContact` couples a finite iron head/oak handle through their
actual native fixing to movable material nodes. Oak is laboratory-only; inorganic
gameplay remains unchanged. Actual Jolt shape queries choose contacts. No head-name
rule, prescribed fragment velocity, terrain collision exemption or invented work.

Twelve cases: 120 mm target cube, 27 cells at 40 mm, horizon 1, nine far-face clamps,
no gravity/damping, existing isotropic strength/plastic reference, initial source
assembly velocity 6 m/s. Head dimensions are (80 mm, width, 80 mm); handle is
(240, 40, 40) mm. Width is 40/120 mm with naturally different mass/inertia. Each
case runs 204.8 microseconds: 2,048 steps at 100 ns or 4,096 at 50 ns. Contact uses
16 mm nodal envelopes, **not exact cube faces**. Proxy/body pairs have one external
response owner; handle and directly clamped-node witnesses are checked, not omitted.

| Target | Head width mm | Contacted cells | Failed bonds | Integration error J at 100 ns | At 50 ns |
|---|---:|---:|---:|---:|---:|
| Glass | 40 | 3 | 13 | 0.000244252 | 0.0000607833 |
| Oak | 40 | 3 | 0 | 0.0000919263 | 0.0000240291 |
| Iron | 40 | 3 | 0 | 0.000659983 | 0.000165186 |
| Glass | 120 | 9 | 9 | 0.000558826 | 0.000138023 |
| Oak | 120 | 9 | 0 | 0.000219954 | 0.0000580845 |
| Iron | 120 | 9 | 0 | 0.00201330 | 0.000503794 |

Every case loads material and boundary. Wider geometry contacts more material.
Glass failures follow constitutive history; oak is not converted to a brittle
preset. Halving dt preserves these failure counts and reduces integration error
below 27% of the coarse value, retaining the existing refinement criterion. No
earlier tolerance is widened; this is not spatial/topology convergence evidence.

Declared trajectory attribution includes source/target kinetic/elastic energy,
contact loss, fixing reconciliation, removed stored bond energy, plastic work and
return error, native transfer error, boundary impulses, geometry couples and
measured native/target step errors. Boundary work is zero. Momentum/angular
attribution agrees within 1e-9 SI, energy within 1e-10 J. Paired rejected trials
generate real contact/support reactions, then restore both histories and clocks.

**Errors remain measured, not certified away:** accumulated native-step momentum
residual reaches 7.66e-6 N s, angular residual 4.50e-6 kg m²/s, and unallocated
mechanical energy before step-error attribution 0.002013 J. Native and target
step errors account for these quantities in this fixture; that is not complete
world conservation or permission to call numerical loss heat. The
[raw results](evidence/solid-boundary-contact-2026-10-06.txt) also retain earlier
free/held reference errors. [Structured evidence](evidence/solid-boundary-contact-2026-10-06.json)
records source hashes, rebuilt artifacts, cases and bounds.

New-case wall times are approximately 1,085–3,147 times simulated duration,
including queries and rollback checks. This reference is **too slow for gameplay**.
No realtime, two-uses-per-second, 10 ft shaft, GPU or cloud scaling claim. Profile
activation/contact/integration/handoff, then qualify faster stepping/reduction
against the unchanged material-law reference.

## Verification and remaining work

Windows x64, MSVC 19.44.35228, SDK 10.0.26100, Release, serial-double CPU,
`banjo-cpu-precise-v1`.

- Nine focused CTest suites pass: Verlet, solid patch, native lattice contact,
  external loads, fast lattice, plasticity, native tool use, ground work and hand
  stroke. Final strengthened native boundary/rollback tests also pass directly.
- Native runner/shared library rebuild; sixteen actual-native Rust-worker tests
  pass against these artifacts. Rust source is unchanged.
- Source registration remains 309/309 without exclusions.
- Strict `--require-repeat-yield` still exits 1 for four existing iron cases.
  They remain unchanged gameplay failures and mandatory migration gates.
- Full CI/regression, interactive input, physical phones, browser installation
  and subsystem retirement remain open.

Next activate actual terrain with neighbouring state/history and matching contact
ownership, then hand off only disconnected cells with their full physical state.
Ideal far clamps do not supply finite neighbouring-world response; nodal envelopes
cannot silently become exact cube surfaces. Soil/sand need supported laws rather
than substitution of a solid fracture experiment. Preserve the
[wide-head pit/strict repeat gates](native-pit-clearance-checkpoint.md), full
transfer accounts, refinement/obstruction tests and useful digging-speed tests
before browser migration. Full W00–W17 scope remains active.

## Reproduction

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_lattice_verlet_tests banjo_solid_matter_patch_tests banjo_native_lattice_contact_tests banjo_lattice_external_load_tests banjo_fast_lattice_tests banjo_lattice_plasticity_tests banjo_native_tool_use_tests banjo_ground_work_tests banjo_hand_stroke_tests banjo_live_world_run banjo_c --parallel 4
ctest --test-dir build/local-cell-tools -C Release --output-on-failure -R '^banjo_(lattice_verlet|solid_matter_patch|native_lattice_contact|lattice_external_load|fast_lattice|lattice_plasticity|native_tool_use|ground_work|hand_stroke)_tests$'
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/local-cell-tools/Release/banjo_live_world_run.exe).Path
$env:BANJO_RUNTIME_ENGINE=(Resolve-Path build/rust-runtime/debug/banjo-runtime.exe).Path
python tests/runtime_native_tests.py -v
build/local-cell-tools/Release/banjo_native_tool_use_tests.exe --require-repeat-yield
python scripts/check-source-registration.py
```
