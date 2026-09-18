# Thin parts: buildability and explicit rigid motion

September 17, 2026 Pacific. Started at `b789faa6ecb37cd3a5eb41db8a6c29f9eed5ae31`; integrated and retested on
`b76502654f3bb5e85a7882362a27398f99667cc6` after the parallel visible-test repair
landed. Its drop/slide/load controls, automatic playback, stable mesh reuse and
measured thermal visualization are preserved. The UI filters tests by the selected
mechanical model; no rigid trial is advertised as a lattice fracture experiment.

## Delivered scope, not the whole architecture

A valid design no longer implies that its cell preview is buildable. Workshop now
reports subcell members, actual disappeared components, closed clearances between
supported opposing box faces, stored-cell cost, and independent scene/bridge
budgets while preserving the editable source. Failed or over-budget sampling is
reported as unavailable, not as an empty successful simulation or a coarser model.
The opening audit is **not** a general hole/topology proof: curved, rotated and
physical-skin openings still require a geometry-specific test.

The user can explicitly select **Precise rigid (no internal failure)** for the
whole candidate. Its exact boxes, density-derived mass, centre of mass and full
inertia tensor travel through a new `rigid-v1` compound package into the existing
native Jolt rigid engine. Boxes are not decoded into cubic material cells. The
isolated **Precise rigid motion** test drops/slides the selected product and
returns actual native poses for play/pause/scrubbing. No animation or substitute
reference product stands in for its geometry. Saving/reopening preserves the
source and the selected model, including an unbuildable source with a visible
physical-preview error.

**The precise-rigid Workshop-to-live-room path is NOT complete.** Live installation,
lattice/static-load trials and legacy materialization refuse rigid/mixed models;
they do not quietly convert them into snapped cells. Existing lattice authoring
installation remains available and its carry/rollback/persistence tests still run.
This checkpoint delivers buildability plus the exact-rigid compiler, persistence
and isolated native test path, not mixed physical representations in the live room.

## How to exercise it

Build `banjo_platform_cli` and `banjo_live_world_run` in the same build directory.
In Workshop's Build panel, choose **Precise rigid (no internal failure)** under
Mechanical representation and press **Apply mechanical model**. The Matter view
shows exact boxes and their mass; changing the comparison cell width does not
change their dimensions or mass. The Test panel selects **Precise rigid motion**.
Set drop height, horizontal speed and duration, then **Run test**. The result is
**measured**, never a strength/survival pass. Save the design and reopen it to retain
the explicit choice. Change back to lattice explicitly before requesting lattice
physics. An old native binary without the declared capability refuses the request.

## Current admission boundary

- One homogeneous material, 1–64 axis-aligned non-overlapping boxes, each dimension
  1–6000 mm; offsets about the compound COM bounded to 6 m. The fixed compound
  must be face-connected. Positive-volume overlaps are refused rather than
  double-counted; gaps and point/edge-only contacts need an actual joint model.
- Supported native density catalogs: glass, oak, iron and concrete. The same
  geometric rules apply to every material. Cosmetic skins do not affect physics;
  physical curves/round members and rotated subparts are refused, not replaced by
  bounding boxes. Explicit physical block edits are boxes.
- Internal faces are ideal fixed connections. **No internal bending, yielding,
  buckling, crushing, fracture or attachment-failure law is supplied.** A metal
  spring is not made flexible by its name. Unsupported models are rejected.
- The isolated fixture uses SI units, `dt = 1/240 s`, 0.1–5 s duration, drop height
  0–2 m, horizontal speed −2–2 m/s, finite ground and a bounded footprint. The native
  protocol independently checks geometry, object/primitive budgets and capabilities.
  Trace capture is bounded and records simulation states, not interpolated motion.
- Shared-grid budgets remain 50,000 preview cells, 16,000 scene cells and 240 joined
  boxes. Cheap dimension feedback is separate from actual occupancy compilation.
  Counts of unknown active deformation/fracture work remain unknown, not zero;
  the rigid model's zero deformation work is explicitly declared.

## Measured thin-table regression

The unmodified 1.2 m × 0.7 m table has a 5 mm top, four 15 mm square legs, and
0.76 m total height. Its volume is 0.0048795 m³. Cell compilation still produces
0 cells at 40 mm, 0 at 20 mm, 1,216 at 10 mm (top absent), and 37,224 at 5 mm
(over the native scene budget). Those failures are now visible rather than called
engine-ready. No grid algorithm, cell cap or fracture law was changed to hide them.

The explicit rigid artifact has **five collision boxes and zero stored lattice
cells** at every comparison resolution. The native engine confirms the component
count, initial dimensions/placement, material mass and independently computed
inertia. Native translational and rotational energy oracles exercise its actual
solver mass/inertia, rather than relying only on descriptive JSON.

| Material | Density (kg/m³) | Exact rigid mass (kg) | COM vertical change after 1 s, 0.2 m drop (m) |
| --- | ---: | ---: | ---: |
| Glass | 2500 | 12.19875 | −0.20001254 |
| Oak | 700 | 3.41565 | −0.20000209 |
| Iron | 7870 | 38.401665 | −0.20000099 |

The drop uses the same geometry, gravity, timestep and height for all three
materials. It demonstrates ordinary collision/motion, **not material survival**.
Contact dissipation and numerical corrections are inherited from rigid-v1; the
before/after mechanical energy is reported but is not a complete support-work
ledger or a conservation proof for collisions.

With gravity and ground disabled, initial horizontal speed 0.5 m/s, zero spin and
one second of motion, the energy residual was 0 J at report precision for all
three materials. A separate 1.5 rad/s principal-axis spin test checks actual
rotational inertia: relative energy drift after one second was 5.42e-5 (glass),
6.61e-5 (oak), 3.51e-5 (iron). The new rotation oracle uses 1e-4 relative energy and
angular-speed tolerances because Jolt's orientation/velocity state is float32;
it does not claim exact angular constancy from double-position support. No
pre-existing physics tolerance was relaxed. A sphere placed inside the leg-space
opening is admitted and remains there: the compound is not a filled outer box.
A separate 20 mm-radius iron sphere dropped onto the 5 mm tabletop settles with
its centre at 0.77999974 m (expected 0.78 m): the top exists in actual collision
geometry, not merely in the renderer.

## Verification

Linux CPU Release build, GCC 14, Python 3.13, Node 22; Jolt v5.6.0 and the repository's
pinned nlohmann/json. No macOS/Windows/GPU or world-scale throughput claim follows.

```sh
python scripts/check-source-registration.py
node --check playground/workshop.js
python tests/workshop_buildability_tests.py -v
python tests/workshop_rigid_tests.py -v
BANJO_PLATFORM_ENGINE=$PWD/build/thin-parts/banjo_platform_cli BANJO_RIGID_TESTS=required \
  python tests/workshop_rigid_engine_tests.py -v
./build/thin-parts/banjo_platform_tests
BANJO_LIVE_ENGINE=$PWD/build/thin-parts/banjo_live_world_run \
  python tests/workshop_install_engine_tests.py -v
BANJO_LIVE_ENGINE=$PWD/build/thin-parts/banjo_live_world_run \
  python tests/workshop_bench_engine_tests.py -v
```

Local checks passed: 8 buildability cases, 13 rigid source/API/persistence cases,
11 new native rigid cases, the existing native platform executable, all isolated
`workshop-fast` Python files, 15 existing native installation cases and 11 existing
native bench cases. Run Python files separately as CI does; legacy standalone
Workshop material defaults and engine-synchronized catalog imports must not be
mixed by an indiscriminate single-process discovery run.

`tests/workshop_browser_tests.py` adds an actual thin-table UI journey: visibility
of the missing top, explicit model selection with a selected leg, invariant mass
across comparison grids, native trace scrubbing, save and page-reload persistence.
The over-budget browser case now expects an explicit blocked buildability report,
not a thrown compiler exception. Browser execution is a separate publishing gate;
this environment's managed Chromium blocks page URLs, so its local launch is not
a browser pass. CI's Chrome must run the journey rather than silently skip it.

## Remaining acceptance gates

1. **Complete rigid live-room integration:** representation-aware native body
   records, picking/editing, contacts with lattice bodies, inventory/fabrication,
   staged world installation, exact state carry and restart/idempotency. Do not
   reuse a lattice snapshot as a rigid body's authoritative record.
2. **Add actual beam, sheet and cable solvers:** section/thickness properties,
   force/torque transfer, constitutive limits and independent analytical oracles.
   Merely assigning these names to rigid boxes would not implement them.
3. **Per-body cell sizes and localized detail:** body-specific contact/support
   settings, substepping, bounded active work, conservative rigid/detail transfer,
   damage/energy preservation and mixed-resolution interface convergence. A new
   resolution field alone is not sufficient.
4. General continuous opening/clearance verification and richer precise compound
   geometry without replacing functional holes/gear teeth with decorative surfaces.

The fine source remains authoritative throughout. Budget exhaustion cannot change
its mechanical model or certify an unperformed failure calculation.
