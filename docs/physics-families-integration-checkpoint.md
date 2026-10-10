# Physics families: parallel references and spatial inspection

October 9, 2026. Implementation checkpoint; full eight-family coupling, strong sheet impact and complete-world realtime remain open.

## What the user can test

- `/mechanisms`: change density, bar dimensions, initial angle/spin, gravity, forces or torque. Watch the calculated bar swing; apply a load to exact equilibrium or remove its support without resetting motion. Inspect real support reactions, work and energy residuals.
- `/flow`: set or paint initial water depths. Calculate spreading and wall reflection, replay accepted physical time, and inspect speed, hydrostatic pressure or depth. Columns are Eulerian control volumes, not persistent water particles.
- `/thermal-fields`: choose glass, oak, iron or ice; choose a heater cell and power. Watch native temperature diffusion. Ice phase and finite fuel/oxygen presets show measured latent fraction and species consumption/products at fixed geometry.
- `/coupled`: Contact forces marks the native contact quadrature locations on both participating surfaces. Peak locations retain the measured historical positions. Original material colors remain visible. These are per-substep contact contributions in newtons, not internal stress, temperature, pressure area or damage.

The [demonstration contract](physics-lab-demonstration-contract.md) applies to subsequent systems. Per-family assumptions, independent oracles and limits are in [mechanisms](mechanisms-checkpoint.md), [flow](flowing-matter-checkpoint.md) and [fields](thermal-fields-checkpoint.md).

## Spatial inspection implementation

The native CPU adapter replays the same accepted trial material/contact contributions in reference order, using the same geometry and contact law. It publishes midpoint sample positions, closest target surface positions, pair forces/torques and contact energies. Reconstructed totals must match the accepted solver, contact counts and energies before the step commits. Inspection cannot mutate authoritative matter or material history.

The browser draws small inspection markers at those locations. Marker size is chosen for visibility. Peak markers represent past contact positions even if the object has subsequently moved. The CUDA adapter has no spatial receipt yet and explicitly reports unavailable data; it does not call a substitute CPU law. Internal stresses and thermal response to impact are not inferred from this display.

## Integration and verification

All new native sources have CMake targets. Docker builds and copies the three reference libraries. The authenticated same-origin server explicitly refuses unavailable backends, bounds declarations and work, and keeps thermal sessions isolated with exact checkpoint export/restore. The generic two-second collision scheduler is refused for thermal fields; their page uses bounded manual advance.

Peer review found and corrected cumulative flow work limits, inconsistent direct-ABI mechanism inertia and thermal checkpoint clocks/counters. Regression tests exercise these refusals and unchanged outputs. Native/Python comparisons retain glass, oak, iron and ice. Flow density comparisons use explicit liquid properties and do not imply a molten-solid law.

The first integration was published as `494facbbe104f3ec139a99b20cc6e1ede8223cc8` on GitHub main. A subsequent HTTP guard checkpoint returns native mechanism convergence/work refusals as explicit HTTP 422 `physics_refused` receipts, retaining the reason and publishing no partial trajectory. The regression drives an actual high-load native refusal; it does not mock one. Both Windows and WSL gateway checks pass with that guard.

Verification details, exact final source/binary identities and scoped test results are in [the integration receipt](evidence/physics-families/integration.json): 17 Windows CTests and 9 WSL CTests pass; five affected API/field/view suites and the Linux thermal oracle were rerun after presentation changes. Source registration passes 352/352. The first Linux gateway attempt lacked its required native executable; building that actual CMake target resolved it before the final run. No tolerance was widened.

Ordinary browser checks show the mechanism swinging, waking after 0.5 s and falling after pin removal; water release/replay; conduction, ice latent fraction and a heater-localized reaction; and native paired contact locations. Phone checks at 390 × 844 show real material cells and the basin. Narrow views now frame the geometry, and explicit mechanism/water calculations return to the 3D view rather than playing offscreen. Whole-motion framing preserves visible free fall; body-following is an optional camera action.

No full repository regression or complete-world realtime claim is made. New measurements are CPU references, separate from the retained CUDA contact solver. The integration receipt identifies a tested source tree based on `c79bcb84`; the publishing commit contains it and is recorded in Git. Hosted revision and image verification remain separate from local source/binary receipts.

## Remaining acceptance

Hosted verification on `ae9db7eaf60a577804dd27a99f6b4b1bf0ceb22b` confirmed the published CPU image/source identity, all three native field libraries, mechanism wake/work, conservative evolving water, localized heater-driven reaction with exact reopen, and the 10 m primitive rebound with paired native contact samples. This does not qualify strong sheet fracture. A subsequent presentation guard disables heat advance/export before a native session exists, including the initial HTML loading window. Its Node regression executes the actual readiness function against loading, ready, busy and running states; physics laws and tolerances are unchanged.

1. Reliable completed strong glass/oak/iron/ice impacts with converged damage and full work/reaction accounts.
2. Detailed ball/fragment transfers with persistent occupied matter and constitutive history.
3. Qualified reduced deformation and general articulated/contact graphs.
4. Conservative fluid/mechanical/thermal/species coupling; true 3D pour and water-wheel test.
5. Calibrated material laws and actual end-to-end realtime delivery measurements.
