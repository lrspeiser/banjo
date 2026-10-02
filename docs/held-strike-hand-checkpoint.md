# Held strikes: shared native grip and target clock — October 2, 2026

## Implemented boundary

The existing LiveWorld grip law and fixed-group feedback now live in compiled
`physics/GripPull.cpp`. LiveWorld's actual wield and stroke preview call that
shared law. Its arithmetic, 800 N / 60 N m default bounds, gravity compensation,
grip effective mass, root feedback and 20/100 rad/s group/single-body settings
are retained. No source pose, velocity, material law or force limit is changed
to manufacture a result. Compilation includes the new source in `banjo_core`.

The [continuous contact reference](held-strike-integrator-checkpoint.md) now
also runs with this hand controller. It reads both actual native constituents,
sizes feedback by their combined mass and parallel-axis inertia, and evaluates
velocity/spin at the gripped root. After the instantaneous contacts at time t_n,
one local force and wrist torque are queued on that root. The real native fixed
constraint transmits this load during the native step. The target advances one
Verlet substep on the same declared clock; its history is never reuploaded.

The reference records signed external hand work and resultant linear/angular
impulse, actual native-step remainders, target integration error, contact losses,
fixed-contact joint impulses and later cached native fixing loads separately.
Hand work uses the existing trapezoidal grip-velocity and spin rule. The opposite
external impulse/work belongs to the prescribed hand source; no physical avatar
or arm body is introduced here. Source-step remainder is not assigned to heat,
material damping or a correction impulse.

This is an integration reference, not an installed ordinary object-strike route.
The normal LiveWorld object/hand/fracture scheduler still needs accepted-clock
rollback and finite fixing failure. App/preview binaries are unchanged. R1 and
R3–R6 remain open. Implementation `9b09d6a85be2de2ef2ef0ef21275922d14edda75`
is published on GitHub main.

## Declared matched experiment

Retain the previous source: 80 mm iron head + 240×40×40 mm oak handle with an
ideal native fixed seam and zero damping/gravity. Source velocity is explicitly
initialized to 6 m/s; this experiment does not model its preceding acceleration
or the ordinary player's complete stroke. The grip is 80 mm behind the handle
COM and the prescribed hand continues along +x at 6 m/s with identity facing.
The controller operates at 20 rad/s with the existing force/torque caps.

All three targets are 120 mm cubes, 27 cells at 40 mm, seed 17 and their existing
catalog-derived axial elastic/strength/plastic rules. Both systems advance
204.8 microseconds: 2048 steps at 100 ns or 4096 at 50 ns. Native shape queries,
per-leaf contact materials and checked source/target transfers are retained.
An untouched XPBD control and the unforced Verlet comparisons remain in the suite.

| Target | dt (ns) | Contacts | Broken bonds | Hand work (J) | Max grip force (N) | Max wrist torque (N m) | Target integration error (J) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Glass | 100 | 2029 | 15 | +0.225822274 | 688.171324 | 0.243192642 | +0.000658202621 |
| Oak | 100 | 3738 | 0 | +0.246649838 | 330.449922 | 0.028692170 | +0.000130318349 |
| Iron | 100 | 1640 | 0 | -0.039663588 | 800 | 0.945720472 | +0.001303191015 |
| Glass | 50 | 4047 | 15 | +0.225583364 | 688.606537 | 0.243192579 | +0.000166749901 |
| Oak | 50 | 7459 | 0 | +0.246785873 | 330.798388 | 0.028703397 | +0.000032721985 |
| Iron | 50 | 3263 | 0 | -0.039790624 | 800 | 0.945726455 | +0.000326090856 |

The hand absorbs work during iron recoil rather than always adding energy.
An initial positive-work assertion was incorrect and was replaced by the signed
work/nonzero bounded-hand check; no velocity or constitutive response changed.
Target-only accumulated linear/angular residuals are at most
9.59306e-14 N s / 4.00209e-15 kg m²/s. Halving dt reduces target integration
error to 0.2533/0.2511/0.2502 of its coarse value. Iron retains 2.28603/2.28739 J
plastic work and 0.00536516/0.00272104 J explicit plastic-return numerical loss.
Glass's equal broken counts in these two cases do not establish topology or
resolution convergence. Oak remains intact; no grain or brittle-oak claim.

## Native precision and joint limits

| Target | dt (ns) | Native delta K minus hand work (J) | Combined P remainder (N s) | Combined L remainder (kg m²/s) |
|---|---:|---:|---:|---:|
| Glass | 100 | -0.000274163183 | 0.000137049962 | 7.34916e-7 |
| Oak | 100 | +0.001222404394 | 0.000298427944 | 3.82344e-8 |
| Iron | 100 | +0.000040945763 | 0.000088884292 | 2.97033e-6 |
| Glass | 50 | -0.000060212160 | 0.000112049610 | 1.00581e-6 |
| Oak | 50 | +0.001042136169 | 0.000250629904 | 3.05790e-8 |
| Iron | 50 | +0.000027869040 | 0.000097102301 | 2.82255e-6 |

These remain unclosed source-step/combined qualification boundaries. At this dt,
some force increments approach native float velocity precision. Native constraint
integration and hand work quadrature also need distinct accounts before attributing
the whole source remainder to rounding. A phase attribution identity is not full
conservation evidence, and timestep refinement does not eliminate the native drift.

The new forced-source cases use the already declared per-transfer SI budgets:
1e-5 J, 1e-5 N s and 1e-5 kg m²/s per source step. Measured maxima are
5.38440e-6 J / 1.06890e-6 N s / 2.03472e-8 kg m²/s. The old unforced native
gates (1e-6 N s / 1e-7 kg m²/s) and target/contact gates are unchanged.
The initial held oak case exceeded the unforced 1e-6 N s gate; it is not used
as an overall conservation certificate after adopting the explicitly bounded
forced experiment. Cumulative drift is retained in the table above.

Largest contact joint impulse is 0.277499/0.072436/0.663398 N s for glass/oak/iron.
Cached native fixing tension peaks are 645.251/310.009/749.989 N at 100 ns, with
shear peaks 1.25352/0.09435/6.29162 N. The contact receipts do not update the
native cache. The seam is explicitly ideal in this experiment; dividing the
instantaneous contact impulse by dt is not a calibrated strength/failure law.
Do not infer a joint stayed within its finite strength from cached native loads
that omit those impulses. Finite interface failure remains an R3 requirement.

The audited held loop took 0.272–0.286 s at 100 ns and 0.539–0.558 s at 50 ns
for 204.8 microseconds of physical time: roughly 1328–2721 times simulated time.
It includes queries, preparation, downloads and audit measurements. No real-time
player, general material realism, full-world conservation or GPU claim is made.

## Verification and remaining integration

Windows x64, VS 2022 Release/MSVC 19.44, separate CPU headless
`build/agent-paid-machine`, `BANJO_BUILD_LAB=OFF`. The hand suite adds analytical
effective mass, centre force, force/wrist bounds, quaternion-sign/frame behavior,
unliftable load and actual-root versus aggregate-feedback oracles. Native/target
tests retain the twelve controls and add the six held experiments. Source
registration is 297/297 with no exclusions. All eighteen affected compiled suites
pass in 61.35 s, including actual LiveWorld/repeatability, two-player ground
ownership/restart, throw, digging, blade and fixing regressions. Existing source warnings remain; the new
shared grip and contact-test compilation has no new warnings. Build artifacts
are ignored. Logs are locally retained under `build/resource-flow/` as
`held-hand-regression-build.log`, `held-hand-regressions.log` and
`held-hand-results.log`.

The retained 8770 preview answers HTTP 200; runner, DLL and CLI SHA-256 hashes
still match the paid-Make checkpoint. New controller/contact behavior is measured
in the compiled reference and native regression suites; no new window or browser
object-strike interaction is installed or claimed.

Focused reproduction from the repository root:

```powershell
python scripts/check-source-registration.py
cmake -S . -B build/agent-paid-machine -DBANJO_BUILD_LAB=OFF
cmake --build build/agent-paid-machine --config Release --target banjo_native_lattice_contact_tests banjo_hand_stroke_tests banjo_ground_work_tests --parallel 4
ctest --test-dir build/agent-paid-machine -C Release -R '^banjo_(native_lattice_contact|hand_stroke|ground_work)_tests$' --output-on-failure
```

Next implement complete source/target/hand rollback on one accepted step, finite
interface load/failure and grip/history mapping, then connect ordinary crosshair
object use and qualify damage → reviewed paid reuse → private restart. Broader
supplies, rover terrain, physical avatar/cargo and live LLM progression remain.
