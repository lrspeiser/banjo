# Continuous affine motion and native contact envelopes

October 9, 2026. Based on main `8e3fac7a6fa777f227a2e58d84bf75eafde12a63`.
**Implemented conditional reference bounds and inspection. Reduced world
execution, strong impacts and complete-pipeline realtime remain OPEN.**

## Implementation and model boundary

[ModeBasis.envelope](../scripts/coupled_modes.py) encloses displacement and
velocity throughout an interval of up to two seconds for the prepared affine
equation M x'' = F0 - K x. Stable modes include interior trigonometric extrema;
complete cycles use their global amplitude without iterating through periods.
Zero modes include polynomial turning points. Negative modes include hyperbolic
turning points and retain the existing growth bound. All modes, preload and
initial velocity remain represented. Interval mapping deliberately loses mode
correlations; it can refuse a trajectory that would actually be safe.

Arithmetic has an explicit FP64 allowance and outward nextafter rounding.
Analytical and independent RK4 tests check coverage; this is not a formally
directed-rounding libm certificate or a bound on the nonlinear native trajectory.
An oscillator returning to its starting point after a full cycle still has a
nonzero travel envelope. Endpoint-only checking would miss that motion.

The compiled [native geometry ABI](../src/physics/CoupledCpuApi.cpp) reports all
current contact quadrature sites, including separated broadphase pairs. The
force law and diagnostic share the same Gauss surface lever construction.
Rows retain pair/site/sample-owner IDs, signed native gap, broad gap, sample
offset and lever length. Invalid capacities refuse before mutating output.

The contact envelope maps affine translation and local Cayley rotation vectors
to bounded point travel. Box signed-distance is 1-Lipschitz in local coordinates;
rotational chord travel is bounded by min(|theta|,2) times the lever/offset.
Each native site receives an interval and a separated/compressed/uncertain
classification. These signs are conditional on that affine geometry path.
Exact prepared body/history matching is required; stale or nonfinite requests
refuse. Primitive-pair envelopes are not silently inferred from surface sites.

**This does not qualify broad SAT feature switching, constitutive branches,
nonlinear trajectory error or actual reduced reaction/work transfers.** Nothing
advances the world or alters its native material/contact law, timestep limits,
work budget or ownership. Native accepted states and exact restart stay unchanged.
Affine energy is still only the reference equation's energy; no new full-world
mass, momentum, angular momentum or energy conservation proof is claimed.

## Comparative measurements

Same nine connected 10 mm cubes, two fixed iron supports, gravity, separated
0.1 kg iron sphere at 10 m and 1/240 s host clock. Loaded measurements follow
one accepted detailed tick. Density, stiffness, inertia and native histories
remain material-derived; oak still lacks grain and iron is not continuum J2.

| Material | Loaded envelope Windows ms | Loaded envelope WSL Linux ms | Native sites | Uncertain sites |
|---|---:|---:|---:|---:|
| glass | 2.070 | 4.866 | 2,808 | 116 |
| oak | 1.762 | 1.494 | 2,808 | 116 |
| iron | 1.736 | 1.518 | 2,808 | 116 |
| ice | 1.803 | 1.453 | 2,808 | 116 |

These are single diagnostic-call measurements, including native geometry and
classification, not isolated performance benchmarks or physical processing
rates. The interval is 4.167 ms. The glass Linux sample exceeds that interval;
even a faster diagnostic is not a running or realtime material simulation.
All cases classify 2,692 sites as separated throughout the reference interval;
none certifies sustained compression. The 116 uncertain sites span support
and neighbouring-cell pairs. This is possible branch change, not proof that
every site actually changes. Independent modal bounds can be conservative.

[Readable evidence](evidence/affine-contact-envelopes/summary.json) records exact
implementation/state identities, declarations, bounds and times. Complete
[Windows](evidence/affine-contact-envelopes/windows.json.bz2) and
[Linux](evidence/affine-contact-envelopes/linux.json.bz2) test receipts retain
all per-pair diagnostics and prior native-versus-affine error comparisons.

## Verification and user test

Windows MSVC 19.44 Release / Python 3.13 / NumPy 2.2.6 and WSL GCC 13.3 Release /
Python 3.12 / NumPy 1.26.4 compile the native API in separate build directories.
The registered preparation test passes analytical interior extrema, a 1 MHz
complete-cycle case, independent mixed-mode RK4, four-material geometry at 33
interior times, exact physical-state/next-step preservation, stale-history
refusal, independent plane/Gauss geometry and untouched invalid-output buffers.
The geometry samples check implementation coverage, not continuum validation.

Eight scoped suites pass: preparation, local Jacobian, CPU world, high drop,
gateway, CPU/CUDA parity, playback and coupled view. A parity process correctly
refused after a source edit during its run; rerunning against the final frozen
sources passes all four materials. No gate or tolerance was widened. Source
registration passes 346/346. This is not full repository or physical-phone QA.

In the same `/coupled` 3D lab, expand **Physics views**, press **Inspect vibration
basis** and inspect **Checked interval**, **Contact sites** and **Motion/contact
bounds**. Physical time stays unchanged and **Reduced motion: Not admitted**
remains explicit. Local browser execution shows 54 retained modes and 2,808
sites with 116 uncertain. The published Render image and public API/browser
must be verified separately before reporting this checkpoint as available there.

## Next acceptance

Resolve the uncertain unilateral support/neighbour contact events with tighter
correlated bounds or explicit piecewise branch continuation; qualify broad
geometry and constitutive switches. Bound native-versus-reference trajectory
error, retain actual vibration and audit all fixed reactions/work and full P/L/E
at handoff. Only then admit reduced advancement and measure complete scenes.
Do not freeze the sheet or ignore the uncertain contacts to make the clock fast.
Detailed ball response, fragment reactivation, articulated/flow/thermal/reaction
bindings, breakable grid floors and simultaneous balls remain unfinished.
