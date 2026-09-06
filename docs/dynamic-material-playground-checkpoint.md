# Property-authored dynamic material playground

Status: experimental implementation of R08; no whole-platform acceptance claim. Built from main `88d88d3`. All nine earlier workstreams and 40 mechanics remain retained.

## Executable path

The playground accepts `dynamic_material_impact` with one to three explicit numeric material descriptors, a rectangular tetrahedral solid, a sphere, and declared duration/error/work limits. GPT selects supported isotropic elastic, orthotropic elastic or J2 plastic laws and their SI coefficients. It cannot generate arbitrary constitutive equations. Material display names do not select a behavior.

The Python contract validates the typed declaration, computes physical descriptor hashes and calls `banjo_dynamic_material_cli`. The native CLI independently validates input and uses the same material parser as the material-point executable. It runs the existing velocity-Verlet sphere/material solver with bounded adaptive advances and a clamped bottom. Sphere mass is density times volume. The original request, solver options, actual sphere/nodal states, plastic history indicators, work counters and numerical energy residuals are recorded.

Each material has cumulative work limits across its complete recording. A rejected chunk rolls back; the last accepted frames remain available with `solver_limit`. The server hashes inputs, executable and saved recording, saves compact evidence for GPT analysis, and restores playback from archived jobs. A terminal job means execution finished; each inner material status determines whether it completed the requested physical interval.

The 3D playground has a distinct dynamic-material mode. It displays actual nodal geometry and sphere centers, tetrahedral edges, undeformed references, X-ray and frame stepping. It uses recorded timestamps and no interpolation. Displacement magnification is disabled for this coupled view. Machine-scale timestamp differences from independent cases are coalesced within 1e-10 s; physical states are not altered. Materials that stop earlier freeze at their last accepted state, with a stopped label while other recordings continue. Playback is a computed recording, not realtime simulation.

## Boundaries

- One sphere and one homogeneous rectangular solid per independent material case; one to three cases.
- Brick dimensions x/y/z each 0.01..0.2 m. Y is thickness; bottom fully clamped. No thin-shell model.
- Mesh refinement 1 or 2 maps to 2r by r by 2r cells, each split into six tetrahedra.
- Sphere radius 0.002..0.03 m, density 1..30000 kg/m3, clearance 0..0.005 m, downward speed 0..0.2 m/s. Its initial footprint must fit the centered top face.
- Duration 0.001..0.1 s; sampled frames at 1 ms and the final requested endpoint. No material-specific timestep overrides.
- Declared energy budget 1e-9..1e-3 J per 0.1 s and 3..200000 native step calls per material. Each material also has 100 million reserved element visits, geometry queries and geometry iterations. Input 256 KiB; output 64 MiB; server subprocess timeout 75 s.
- Gravity 9.81 m/s2, friction 0.15, contact margin 1 micrometre and maximum penetration 10 micrometres are explicit fixed solver settings. The contact impulse uses no positive restitution coefficient; resolved material motion can release stored elastic energy.
- Finite strain, viscoelasticity, fracture, cutting, shared world persistence/repair, calibrated residual dents and realtime execution are unaccepted. Existing thermal/world modules are not coupled into this new route.

## Observed results

See [machine-readable results](dynamic-material-playground-results.json) for request identities, actual coefficients, summaries and test counts.

A first live GPT request authored extremely soft 1 Pa and 5 Pa materials. They reached small-strain/geometry validity limits after 13 and 16 ms. Those failures remain saved; no automatic material replacement or tolerance increase was applied. Unit guidance now explicitly explains MPa-to-Pa conversion. Model-authored coefficients still require review; schema admission alone does not establish physically appropriate values.

A second live GPT request preserved explicit SI values for two fictional materials with density 1000 kg/m3, E=1000000 Pa and nu=0.25. The J2 case additionally had yield stress 1200 Pa and hardening 20000 Pa. The 80 by 20 by 80 mm fixture used a 12 mm sphere at iron density, 0.5 mm clearance and offset (7,9) mm. Both completed 0.1 s. Accumulated absolute numerical-energy residuals were 3.866884 and 4.244440 microjoules against a 6 microjoule budget. The elastic case had zero plastic dissipation; the J2 case recorded 0.000116895 J. These are deliberately fictional compliant materials, not calibrated glass, wood, metal or rubber. Loaded plastic strain does not prove a permanent unloaded dent.

Matched retained catalog glass/oak/iron cases completed the 1 ms pre-contact control. At 20 ms requested duration, all three exhausted 200000 step calls at 10 ms, near estimated first contact. No accepted contact was claimed for those stopped recordings. This explicitly fails the current stiff-material responsiveness gate. Timings in this checkpoint were collected during other test activity and are diagnostic, not isolated performance qualification.

The browser was exercised from prompt submission through automatic 3D display, playback/frame stepping, X-ray, evidence retrieval, archival restoration and a live GPT evidence review. GPT correctly distinguished recorded elastic/J2 response from material calibration and permanent-dent acceptance.

A third GPT request created unseen Aster-37/Birch-91 properties with 1.2/0.8 MPa converted correctly to 1200000/800000 Pa, different densities, yield/hardening, geometry and sphere setup. Both completed 0.05 s with positive accepted contact counters and plastic dissipation only in the J2 case. A fourth request requiring fracture plus combustion in this same solver was blocked with no substitute run.

Verification: 62/62 native suites passed in 93.83 s. Python discovery ran 131 tests: 130 passed and one Windows directory-symlink privilege test skipped. Both JavaScript files passed syntax checks. Timings are single-run verification measurements.

## Next execution order

1. Reduce and qualify stiff/contact integration cost without weakening requested error budgets; retain glass/oak/iron and unseen-property comparisons.
2. Establish spatial convergence, contact telemetry and explicit expected-outcome checks, including stable unloading and residual geometry.
3. Add finite-strain recoverable materials and regularized fracture as separate tested laws; then shared compact persistence/repair and broader scene composition.
4. Qualify active-world load, latency percentiles and fallback policy before declaring a realtime release. Every R01..R10 acceptance remains open until its complete evidence exists.
