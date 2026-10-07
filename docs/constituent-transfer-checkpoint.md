# Canonical constituent ownership transfer

October 6, 2026. Experimental CPU reference on source base main `cb1d3f71`.
This advances W08/W09 state transfer. It does not activate terrain or install the
replacement in the browser. The complete W00–W17 rewrite remains open.

## Representation and ownership

`partitionConstituents` prepares components from the **live bond graph** of a
canonical `LatticeState`. Node identity, reference/current/previous displacement,
velocity, physical mass, clamp mobility and represented volume are copied exactly.
Every internal bond retains compliance, rest vectors/lengths, all six thresholds,
damage, previous strain samples, failure mode and plastic extension/strain.
Dead crossing bonds retain those same values in a separate interface archive;
they are never recreated as live bonds. Original source maps compose through
subsequent transfers. Attached components remain distinguishable from free ones.

Components retain deformation rather than fitting all cell velocities to one
rigid body's motion. There are no fragment templates, launch velocities,
explosion impulses or material-name fracture branches. Reference coordinates are
not recentered: small displacement survives even at the million-metre test origin.
Topology adjacency/schedules are rebuilt and canonical histories are remapped
through the new schedule. Nodes are bounded to 1,024 and bonds to 65,536;
truncated/nonfinite histories, invalid maps/masses/clamps/thresholds and overflowing
mechanical totals are refused.

`SolidMatterPatch::transferToComponents` stages all replacement CPU backends
before retiring the original backend. The archived original refuses further
pulses and repeated transfer. New solvers inherit the absolute accepted step/time
and use inherited mechanical state as their accounting baseline. Earlier global
work/loss accounts remain in the single parent receipt; only later increments
belong to children. Bond arithmetic correction is explicitly exposed alongside
physical boundary reactions. This is in-process ownership, **not a durable world
transaction or native collision/body handoff**. Allocation failures leave the old
owner intact by construction; fault-injected allocation/crash recovery is not tested.

The pure partition preserves serial Verlet state. It is not a complete XPBD
multiplier, pending-load, contact-cache or solver-settings checkpoint. Callers
must supply the same admitted law/settings when resuming. The solid wrapper still
declares its existing elastic/strength law; the separate raw plastic experiment
passes its exact plastic settings. Existing LiveWorld/Refracture plastic sidecars
remain: this change does not claim they were universally losing plastic history.

## Matched ownership experiment

Windows x64, MSVC 19.44.35228, SDK 10.0.26100, Release, serial-double Verlet,
`banjo-cpu-precise-v1`. Glass/oak/iron have the same 0.25 m cube, 50 mm cells,
horizon 2, 125 nodes, 25 bottom-face clamps and origin (2, 0.6, -1) m. Density,
stiffness and strength come from their retained material inputs. Oak is a
laboratory comparison; active gameplay remains inorganic.

One top-centre cell receives (0, 1,000,000, 0) N for 512 steps at 100 ns, with a
50 kJ positive-work ceiling. This is declared high laboratory traction, **not a
human strike or calibrated excavation law**. Transfer occurs at step 512, then
each component continues unloaded for 128 steps against an unsplit control.

| Material | Mass kg | Supplied work J | Failed bonds at transfer | Components | Removed stored bond energy J |
|---|---:|---:|---:|---:|---:|
| Glass | 39.0625 | 4,110.255487 | 96 | 2 | 8.554048 |
| Oak | 10.9375 | 13,728.972518 | 56 | 2 | 261.273895 |
| Iron | 122.96875 | 197.689414 | 2 | 1 | 44.334814 |

All retain 0.015625 m³ and every source cell exactly once. Glass/oak have 22 dead
crossing interfaces archived; iron remains connected. High oak load can fail its
existing isotropic strength surface; this is not a brittle oak preset or grain model.
Equal force/time supplies different work because material-dependent motion differs.

The complete **patch** ledger combines the parent receipt with child increments,
including stationary support impulse/torque, source work/impulse, removed stored
bond energy, measured integration error and bond roundoff. Residual magnitudes:

| Material | Energy J | Linear momentum N s | Angular momentum kg m²/s | Maximum continuation velocity difference m/s |
|---|---:|---:|---:|---:|
| Glass | 3.63e-12 | 9.88e-14 | 2.37e-13 | 5.56e-17 |
| Oak | 6.90e-12 | 7.40e-13 | 1.67e-12 | 8.89e-16 |
| Iron | 3.67e-12 | 9.19e-13 | 2.02e-12 | 0 |

Position differences are below 7e-21 m. Tests require position 1e-10 m, velocity
1e-8 m/s, aggregate energy 1e-8 J, linear 1e-9 N s and angular 1e-8 kg m²/s.
These are new transfer oracle bounds; no earlier physics tolerance is widened.
Measured integration errors before transfer are 0.000230/0.003950/0.004655 J;
ledger attribution does not erase those errors or call them heat. The imposed
force source has no simulated finite body here, so this is not full-world conservation.

Observed transfer preparation/admission/retirement costs are about 0.48–0.59 ms
for these 125-cell cases in one run. This excludes force stepping and contact;
it establishes no world-scale or realtime capability. The preceding finite
contact reference remains orders of magnitude slower than realtime.

## Plastic history and finite-contact continuation

A separate 120 mm cube / 40 mm cells / horizon 1 / 27-node experiment uses the
same material-specific plastic/strength settings and distant origin
(1,000,000, 2, -1,000,000) m. Opposite corner forces ±(300,000, 300,000, 300,000) N
act for 512 × 100 ns; components continue unloaded for 128 steps. All three
produce three components. Iron acquires real plastic strain 2.57069328426e-6;
glass/oak retain zero plastic strain under their supported settings. Motion and
plastic continuation differences are zero in this run. Plasticity is not inferred
from display names, and this high-load fixture is not calibration.

The twelve [finite native contact cases](solid-boundary-contact-checkpoint.md)
also prepare canonical components after actual Jolt head contacts, at both
100/50 ns and 40/120 mm widths. Each then compares 128 target-only steps against
its original material backend. The source is paused after the coupled experiment;
this qualifies contacted target history, **not continued source/target collision
or live-world handoff**. Glass has two components and nine archived interfaces;
oak/iron remain connected. Maximum velocity difference is below 7e-21 m/s;
plastic history/failure agree. Existing native-step errors remain measured.

## Verification

- New source and regression compile in CMake; registration is **311/311**.
- Ten focused native CTest suites pass: constituent partition, solid patch,
  native lattice contact, Verlet, external loads, fast lattice, plasticity,
  native tool use, ground work and hand stroke.
- Sixteen actual-native Rust worker tests pass with the rebuilt runner.
- Runner and shared DLL rebuild successfully; they are not installed in `C:/play`.
- Strict `banjo_native_tool_use_tests --require-repeat-yield` still exits 1 with
  the original **four iron repeat failures**. Full regression and CI are not green.
- No normal interactive window, physical-phone, mobile/browser replacement,
  GPU or cross-platform behavior is newly qualified.

[Structured evidence](evidence/constituent-transfer-2026-10-06.json) retains source
and artifact hashes, commands, measured cases and open gates.
[Raw output](evidence/constituent-transfer-2026-10-06.txt) retains test results.

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_constituent_partition_tests banjo_solid_matter_patch_tests banjo_native_lattice_contact_tests --parallel 4
ctest --test-dir build/local-cell-tools -C Release --output-on-failure -R '^banjo_(constituent_partition|solid_matter_patch|native_lattice_contact|lattice_verlet|lattice_external_load|fast_lattice|lattice_plasticity|native_tool_use|ground_work|hand_stroke)_tests$'
python scripts/check-source-registration.py
```

## Next stages

The owner explicitly supports simple material simulations and a UI rebuilt in
stages. Build a small experiment view around real recorded/live solver state:
choose material and declared interaction, see cells/deformation/attachment, and
read work, damage and measured results. Keep magnification and replay time clearly
labelled; a rendered replay is not a new physical simulation. Include glass, oak
and iron comparisons and retain unsupported-law/refusal states. Use that view
to qualify force/release, finite contact and later settling/recontact before
exposing the replacement through World/Inventory/Build/Progress.

Continue finite-neighbour terrain activation, exact cell collision and paired
native clocks/contact ownership, settled deformable fragments and supported
soil/sand/wet laws. Then qualify private constituent collection/manufacture and
restart, sustained useful repeated digging and the 3.048 m excavation gate.
Performance, full-world accounting, authored-tool import, durable transactions,
the new UI, full regression and all retirement gates remain open. No old
controller, saved world or player data is removed by this checkpoint.
