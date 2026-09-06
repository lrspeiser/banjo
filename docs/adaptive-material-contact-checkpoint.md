# Error-controlled material contact

The native sphere/mesh reference now supports bounded adaptive advances, optional velocity Verlet with a final contact-velocity constraint, and reuse of accepted constitutive evaluations. Two full 0.1 s impacts complete within a 3 microjoule absolute numerical-energy budget and a 200,000-step-call limit. This is progress on R02/R03 and the measured work behind R09. Spatial convergence, realistic fracture/dents/rubber and realtime qualification remain open. No new browser capability is exposed by this checkpoint.

## Shared state and work

`DynamicPatch` caches its immutable accepted material evaluation. Force evaluation and reporting reuse that evaluation; only the new candidate displacement requires another constitutive pass. A private checkpoint copies canonical displacement, velocity, material history, time and ledger state, and shares the immutable evaluation. Reference geometry and stiffness caches remain in place. Accepted cache allocation occurs before commit; failed trials restore state and cache together. This is internal trusted rollback, not a public persistence/import contract.

The default symplectic-Euler method remains available. Optional velocity Verlet applies an old-force half kick, the existing swept contact/drift stage, and a new-force half kick. A final velocity-constraint pass applies the same passive barycentric contact/friction impulse to any touching surface still closing after that last kick. It includes sphere spin, support reactions and measured contact loss, and does not move positions. Contact events identify this final stage separately. Event and geometry limits cover both stages.

The final contact constraint matters: an unconstrained final half kick had left touching surfaces with an inward velocity and prevented tight adaptive impact acceptance. Merely selecting a second-order free-flight method was insufficient. Harmonic/free-flight tests cover the integrator separately from contact.

## Accuracy contract

`SpherePatchWorld::advance(duration_s, load, options, sphere_force, sphere_gravity)` accepts constant loads over a bounded interval of at most one second. It compares one full trial with two actual half steps and commits the half-step path. No extrapolation, visual interpolation or outcome selection affects physics.

The comparison measures maximum nodal/sphere position difference, velocity difference including sphere spin surface speed, total/plastic strain differences, energy partition disagreement and the sum of absolute half-step energy residuals. Limits are supplied in metres, metres per second, dimensionless strain, joules and a reference duration. The requested interval receives `duration/reference_duration` of each limit.

Smooth work receives a duration-based share; nonsmooth contact can draw from a consumable reserve within the same original budget. Defaults reserve half of each interval allowance, with at most 1/32 of the whole allowance available to one contact segment. Actual error above a segment's smooth share consumes reserve and cannot be reused. This allows impulse events to refine against a finite absolute allowance. Giving every discontinuous event only a time-proportional allowance can fail to converge even as the timestep shrinks. No total tolerance is increased by the reserve.

All accepted indicators are accumulated and checked against the original interval limits. The controller independently checks the total absolute numerical energy residual and an endpoint energy/work identity. These are discrete error indicators and ledgers, not a rigorous bound on the unknown exact physical solution. They cannot establish spatial accuracy or calibrated material properties.

Every trial, including rejected/coarse trials, consumes the step-call, reserved constitutive-element and geometry budgets. A failed advance restores the entire requested interval, including tentative accepted segments, plastic state, cached forces, sphere, time and contact settings. Reports distinguish committed advancement from tentative work and retain the last failure. The square-root step controller avoids repeated large grow/shrink cycles; clipping to a recording boundary does not force the next interval to restart with an unnecessarily tiny step.

## Experiment and results

The new `banjo_sphere_patch_adaptive_probe` reuses the declared experiment from the [coupled-contact checkpoint](coupled-contact-checkpoint.md): a 12 mm radius iron-density sphere, 0.5 mm clearance, gravity on both participants, and an 80 by 20 by 80 mm supported target. The targets are fictional linear-elastic and J2 coefficient sets with density 1000 kg/m3, Young's modulus 1 MPa and Poisson ratio 0.25; J2 yield is 1.2 kPa and hardening is 20 kPa. They are not calibrated rubber or metal.

The recorder makes 100 advances of 1 ms and retains actual mesh/sphere states. Across the complete recording the step-call ceiling is 200,000 per material. Error allowances per 0.1 s are: position 0.1 mm, velocity 1 m/s, strain 0.1, energy-partition disagreement 0.1 mJ, and the declared absolute energy-residual budget. Constitutive strain/gradient validity remains a separate guard.

| Mesh | Energy budget over 0.1 s | Elastic completed / absolute residual / calls | J2 completed / absolute residual / calls |
|---|---|---|---|
| 18 nodes / 24 tetrahedra | 6 microjoules | 0.1 s / 3.867 microjoules / 68,394 | 0.1 s / 4.244 microjoules / 46,809 |
| 18 nodes / 24 tetrahedra | 3 microjoules | 0.1 s / 2.035 microjoules / 140,850 | 0.1 s / 2.221 microjoules / 99,294 |
| 75 nodes / 192 tetrahedra | 6 microjoules | Stops at 0.031 s: work budget | Stops at 0.053 s: work budget |

At the tighter coarse-mesh setting, sampled peak upward speed is 0.057987 m/s for elastic and 0.043355 m/s for J2. The J2 run retains 0.0001171 J of plastic dissipation; the elastic run has none. Active final contacts have normal relative velocity at roundoff. Sampled output peaks are not high-frequency maxima, and loaded/vibrating final deformation is not an unloaded residual dent.

The first-order adaptive recording had exhausted the same 200,000-call ceiling at 0.029 s for elastic and 0.076 s for J2 at the 3 microjoule setting. Those failure records remain alongside intermediate second-order failures. The final controller and velocity constraint complete both coarse-mesh cases without increasing that accuracy/work budget.

The 3 microjoule runs take seconds for 0.1 simulated seconds. Finer meshes exhaust the work cap, and their response differs. No realtime or mesh-convergence claim is made. One matched fixed-step check preserves both recorded trajectories exactly after caching; the source now performs one candidate constitutive pass per step instead of three repeated evaluations. One-shot wall times are not isolated benchmark qualification.

## Reproduction and next gate

Build `banjo_sphere_patch_adaptive_probe`. Run `banjo_sphere_patch_adaptive_probe evidence.json 0.000003 1 verlet`; use `euler` for the first-order reference, change the energy budget explicitly, and use mesh refinement 2 or 3 for harder spatial cases. Output includes numeric material/error inputs, mesh, actual accepted frames, work counts, committed duration and failure diagnostics. A failed 1 ms chunk retains the preceding accepted frame and does not publish tentative geometry.

Next qualify spatial/contact response under the same accumulated error contract, reduce measured contact/constitutive work, and evaluate an integration strategy suitable for stiff active regions. Unloaded impact dents and full state export/reload follow accepted dynamics. Finite-strain rubber, progressive fracture, thermal-mechanical coupling, LLM scene contracts, 3D playback integration and world-scale scheduling remain in the original goal list. All nine prior workstreams and 40 mechanics are retained.

## Verification

Windows MSVC 19.44 Release, double positions: full build passes and all 62 native suites pass in 93.08 s. Eight adaptive cases include complete elastic/J2 recordings, exact free flight, stricter-budget refinement, late interval rollback, retained plastic history, cached-force continuation and glass/oak/iron controls under both integrators. Eight dynamic cases include velocity-Verlet gravity and whole-interval oscillator refinement. The 8 Python descriptor and 4 native material-path tests pass. The final default-method fixed-step frame arrays exactly match both previous material recordings. No browser source changed, and the new path is not yet integrated there.

The [machine-readable results](adaptive-material-contact-results.json) include the final coarse recordings, finer-mesh work failures and preserved intermediate failures. Original nine goal records and all 40 unique mechanics were checked as retained. Changed-file credential and whitespace checks pass.
