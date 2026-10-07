# Material surface transfer checkpoint — October 6, 2026

## Scope and implementation

Experimental CPU reference, prepared against main `b49e51a5c4163484c2f8246e8779fe8533c3bcc8`. Publication is recorded below. [Exact source/executable hashes and per-material results](evidence/material-surface-contact-2026-10-06.json) pin the measurements. This extends the [occupied cuboid query](occupied-cell-contact-checkpoint.md); the retained spherical and centre-point fixtures remain regression tests.

The terrain audit found that `ToolTerrain` funds a centre-point bite while a wide native head meets neighbouring ground through ordinary collision. Removing the selected-column bound or widening the collision exemption would give those neighbours no corresponding material work/reaction. This checkpoint supplies the surface-to-material transfer needed before replacing that reduction. Gameplay terrain is not switched over.

`MaterialContactStencil` constructs a bounded affine translational support at a declared actual surface point. For actual node masses and positions, weights satisfy Σw=1 and Σw*x=surface. The mass-weighted covariance fit minimizes Σw²/m. Virtual surface velocity is Σw*v, inverse effective mass is Σw²/m; an impulse J gives each actual node Δv=w*J/m. These identities reproduce actual total force, surface torque and kinetic work. The virtual coordinate is never a second physical body or added mass. Actual material positions, strains, damage and plastic history continue through the existing constitutive backend.

The local region requires 4–64 finite movable translational nodes, radius 1 nm–100 m, surface within three region radii, |w|≤4 and a well-conditioned 3D covariance. Signed extrapolation permits a face outside the cell-centre convex hull; weights are quadrature coefficients, not negative granular masses. Planar/isolated/spinning supports refuse. The caller owns current connectivity and surface witness selection: this API does not discover a physical region or authorize transfer across broken bonds. A mutable stencil is recomputed/checked against current mass, geometry and velocity before use.

The serial-double backend admits 1–64 distinct node velocity candidates atomically, including stale-state, clamp, finite-arithmetic and cumulative-ledger checks. It counts one contact rather than one contact per constituent. Scalar contact delegates to the same checked implementation. `applyNativeFixedSurfaceTransfer` prepares the existing actual native fixed-source response, preflights all actual target candidates and their force/moment/work reproduction, then commits both between steps on one host thread. Both reactions share the native source-surface witness. No prescribed pose, fragment velocity, extra energy, smoothing animation, material-name switch or target history reset is supplied. Unsupported float/parallel backends refuse.

New double-reference reproduction bounds are explicit: 1e−10 dimensionless affine reproduction and 1e−10×(1+expected magnitude) SI target impulse/angular/work error. They do not relax any existing source or trajectory tolerance. Native float recoil is separately retained in the original roundoff receipts.

## Matched experiments

Windows x64 / MSVC Release, headless. Glass/oak/iron use the same 80 mm target cube, eight 40 mm cells, horizon 1 and full connected support. The source is an actual finite iron head (80 mm, width, 80 mm) with an oak laboratory handle (240, 40, 40 mm), an ideal native fixing and explicitly initialized velocity (6, 0.2, 0.1) m/s. Gravity and damping are zero; there is no clamp, hand controller or launch impulse. Each case lasts 3.2 µs, 32×100 ns or 64×50 ns. All target bonds remain alive throughout this deliberately short pre-fracture experiment. The target starts touching the source at x=40 mm.

Target masses from density are glass 1.28 kg, oak 0.3584 kg and iron 4.02944 kg. Catalog density/Young modulus are respectively 2,500 kg/m³ / 70 GPa, 700 kg/m³ / 12 GPa and 7,870 kg/m³ / 211 GPa. Their retained elastic stiffness, strength and supported plastic parameters drive the reference; oak is not changed into a brittle preset. These cases qualify transfer and early elastic response, not material realism, grain, fatigue or calibrated fracture. Oak remains laboratory-only; playable worlds stay inorganic.

| Material | Head width mm | Integration error J, 100/50 ns | Applied contacts, 100/50 ns |
|---|---:|---:|---:|
| Glass | 40 | 0.000244927191 / 6.12266037e-05 | 1 / 1 |
| Oak | 40 | 2.27511196e-05 / 5.68748086e-06 | 1 / 1 |
| Iron | 40 | 0.000396598329 / 9.91415191e-05 | 1 / 1 |
| Glass | 120 | 0.000253031792 / 6.47905775e-05 | 2 / 2 |
| Oak | 120 | 2.31637126e-05 / 5.96693389e-06 | 4 / 5 |
| Iron | 120 | 0.00054748433 / 0.000136859936 | 2 / 2 |

Halved-step integration error is below 0.27× the coarse result in each case and below the retained 0.1% of initial mechanical-energy cap. Contact counts are measured; different wide-oak counts do not establish converged manifold selection. Cell centres move with the material; envelope orientations remain aligned with reference axes. A continuum deforming face or independent cell spin is not implemented.

Actual full fixture totals retain native fixing/contact dissipation and numerical recoil, target constitutive plastic/removal/integration accounts and momentum roundoff. After those attributions, linear/angular residuals agree within 1e−9 SI and energy within 1e−10 J. Raw residuals before native-step attribution reach 4.57395e-08 N s linear and 9.88341e-08 kg m²/s angular; unallocated energy reaches 0.000547475 J. These are numerical measurements, not heat or a full-world conservation claim. Instant target reproduction errors reach only 3.55271e-15 J work, 1.77641e-15 N s and 3.10317e-17 kg m²/s.

Observed execution costs are 0.0044355–0.0090643 s per 3.2 µs trajectory, excluding its rollback probe: about 1386–2833 times simulated duration. The small fixture is not a gameplay performance test and is not fast enough for migration.

## Verification and remaining gates

Eight rebuilt CTest entries pass: surface transfer, retained native point and lattice contact, fixed assembly, external loads, Verlet, tool admission and native tool use. The new suite includes analytical affine mass/velocity/force/moment/work oracles, rotated/boosted and distant-origin supports, unequal masses, planar/spin/extent/staleness refusals, late-invalid/overflow/duplicate atomicity, unsupported backends, a rejected native roundoff budget and paired rollback. Seventeen actual-native Rust worker tests pass against the rebuilt runner. Source registration passes 314/314.

The strict repeated-digging test still exits 1 for the same four iron fixtures. No test is disabled or reclassified as a pass. The corrected build command supersedes an initial request for a nonexistent test-target name; two new test setup issues (overflow stimulus and unsupported float/parallel integrator setup) were corrected before the final eight-suite pass. Existing build warnings outside the changed sources remain visible. No complete regression, interactive/input, physical-phone, macOS or GPU claim follows from this headless reference. Demo World on 18890 and material lab on 18891 remain on their existing processes; no retained subsystem is deleted.

Next: graph-derived local support that survives fracture without spanning disconnected pieces; resolved surface/manifold and spatial refinement; finite neighbouring ground activation and exact history/native-collision handoff; settling/self-contact and supported soil/water laws; full actor/tool/ground/release accounting; measured faster execution and actual sustained excavation. Only then replace the old centre-bite path and retire its callers. Durable state, Rust/UI migration and W00–W17 remain active.
