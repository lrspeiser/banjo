# Persistent connector plasticity checkpoint

October 8, 2026. Implemented experimental CPU integration, not full metal admission. All five active goals remain open. The source revision and tested executable hash are recorded in the publishing follow-up and `client/voxel-lab/checkpoint.json`.

## What the user can test

In the [3D lab](http://127.0.0.1:18893/), choose Iron, Sheet response **Yielding · experimental**, Coupled friction, 5 kg and 1 m. Drop the ball; use Before/Live to compare real native poses. The result reports yielded connections; Physics & record separates physical yield work from numerical return loss. Reset starts a new experiment. The reference response remains default. Unsupported brittle/grain declarations cannot select this model. No replacement velocity, pose, shader dent or shatter animation is used.

The browser experiment completed 2 s with 64 connected sheet cells, 32 ball cells and 11 anchored support/floor cells. It retained 24 yielded sheet connections, 31.576116 J plastic work and 1.443777 J endpoint projection excess. Its final unexplained energy ledger was -16.461741 J (see saved native result for full precision), so completion is not physical accuracy admission. At 0.8 s sheet cell centers ranged from 0.496887 to 0.515965 m, compared with initial 0.502 m; this is small deformation, not a promised dramatic crater. The ball remains on the sheet: a full unload/removal test is still required.

## Implemented law, units and assumptions

[`ConnectorPlasticity.hpp`](../src/material/ConnectorPlasticity.hpp) and [implementation](../src/material/ConnectorPlasticity.cpp) implement six independent elastic-perfect-plastic connector modes. Translation coordinates are metres; log rotation coordinates are radians. Conjugate loads are N and N m. Parameters come from declared modulus, Poisson ratio, yield stress and connector section geometry. Material display names do not determine response. Admission requires positive finite coefficients, isotropy, zero hardening and a non-brittle declaration; iron/aluminum qualify in the catalog, oak grain and glass do not.

Stiffness is EA/L, GA/L, polar-area torsion G(Iy+Iz)/L and EI/L bending. Axial/bending yield uses first-fibre yield stress; shear uses yield/sqrt(3); polar torsion is an approximation. These independent bounds are a box yield surface, **not continuum J2** or calibrated sheet plasticity. No hardening, grain, ductile tearing or damage regularization is implemented by this change. The separate existing J2 point oracle is retained; it is not silently claimed as integrated here.

At a fixed candidate endpoint, each over-yield mode updates plastic rest by delta-p. Physical yield work is Fy*abs(delta-p); numerical endpoint projection excess is k*delta-p^2/2. Stored elastic energy uses q minus plastic rest. The released energy identity includes both terms. Projection follows the actual elastic native solve; the current native impulse is not capped inside the iteration. Overshoot and full trajectory convergence therefore require further qualification. The numerical term is not material heat.

## Native integration and atomic acceptance

Log-face constraints retain translation/rotation rest in native SaveState/RestoreState. Updating rest changes later native forces and resets warm-start values; it assigns neither poses nor velocities. Candidate updates occur inside the existing reversible trial. Constitutive host history and both ledgers promote only after acceptance. Refusal/exception restores native rest and motion; accepted child history followed by parent refusal is covered. The unchanged energy gate includes yield work and projection excess, preventing plastic projection from hiding candidate energy creation. Reaction and source work are sampled before projection and retained separately.

Snapshots contain per-connector rest, accumulated flow, yield counts and both work histories. This supports inspection and exact journal playback; it is **not yet a supported restart/save-resume API**. Reset reconstructs the original declaration. Default declarations omit new fields, and all four default two-second physical/work comparisons match the previous executable exactly at 16-tick outputs.

## Measured comparisons

Same supported geometry and loading: 0.4 m square, 4 mm thick, 8 by 8 cells; 32 ball cells; 5 kg iron ball from 1 m; 32 cm support gap; centered faces, coupled friction, 96 velocity iterations. Values below are at 0.6 s; plastic tests continue another 16 steps to check retained/monotone history. Gravity is -9.81 m/s². Glass/oak/iron densities are 2500/700/7870 kg/m³ and moduli 70/12/211 GPa, so sheet mass/stiffness differences are expected. Oak remains an elastic comparison, with grain failure unsupported.

| Sheet | Plastic | dt (s) | Accepted substeps | Yield work (J) | Numerical return (J) | Unclosed energy (J) | Wall (s) |
|---|---|---|---:|---:|---:|---:|---:|
| glass | False | 1/960 | 11881 | 0.000000 | 0.000000 | -28.736993 | 26.70 |
| oak | False | 1/960 | 6972 | 0.000000 | 0.000000 | -13.483153 | 20.68 |
| iron | False | 1/960 | 7008 | 0.000000 | 0.000000 | -15.256687 | 24.72 |
| iron | True | 1/960 | 6462 | 31.576116 | 1.443777 | -11.590529 | 25.89 |
| iron | True | 1/1920 | 6342 | 31.408889 | 1.481346 | -12.111049 | 23.70 |

Runtime overlaps browser/other verification, so these are not isolated speed benchmarks. Iron physical plastic work differs by about 0.53% between nominal timesteps. Projection excess instead rises by about 2.6%; global adaptive subdivision and coupled contact change the accepted path. This is **not a convergence pass**. Under prescribed CPU loading, halving increments reduces endpoint projection excess while preserving final rest and physical yield work. Whole-impact energy/contact/spatial refinement remains open. No tolerances were relaxed.

## Verification and evidence

- 336/336 C++ sources registered, no intentional omissions; all new sources compile with MSVC Release, precise CPU floating-point policy, Windows SDK 10.0.26100. Separate output: `build/voxel-plastic-face/Release`.
- Nine rebuilt scoped CTests pass in 8.97 s: connector plasticity, native face springs, state recorder, rigid work, reversible trials, friction block, gateway, pipeline, playback. The new analytical test covers six modes, unloading/reversal, positive yield work, projection identity/refinement, invalid/unsupported laws and exact native rollback in both inline/thread-pool runners.
- The registered `banjo_voxel_plasticity_tests` script is invoked directly for five complete comparative/refined scenes: finite motion, conserved mass, actual yielding, retained history and ledger sums. Passing these checks does not certify full continuum behavior or full conservation.
- Four complete default two-second comparisons pass exact physical/work parity against the compact-recorder build: glass, oak, iron, ice. Only wall profiler fields are excluded.
- Ordinary browser setup/drop reaches 2 s; Before/Live and native work/history inspection pass, with no console errors. Desktop setup is bounded and scrollable. Landscape 844 by 390 controls are checked separately; physical phone and other platforms are not claimed.
- Earlier compact-recorder five coupled comparisons also finished: glass/iron, oak/iron, iron/iron, ice/iron and glass/glass all match their profiling baseline exactly at every 16 host ticks. The glass-ball ledger still loses about 80.188 J; storage parity is not accuracy admission.

Local evidence: `build/voxel-plastic-face-final-ctest.log`, `build/voxel-plastic-face-regression.log`, `build/voxel-plastic-face-regression-results.json`, `build/voxel-plastic-face-default-parity.log`, `build/voxel-plastic-face-browser-result.json`, `build/voxel-plastic-face-browser-before.png`, `build/voxel-plastic-face-browser-after.png`, `build/voxel-compact-record-coupled.log`. Initial native test fixtures failed because centered integration was not enabled, collision mode was continuous, and anchor strain was assumed exactly zero. Fixtures now use the supported centered/discrete mode and captured initial strain; the final tests pass without changing physics tolerances.

## Remaining work

Integrate yield response within the shared native iteration and qualify combined loading, contact transfers, timestep and spatial refinement. Add controlled unload/removal and supported save/reload of material history, then ductile damage/tearing with measured fracture work. Resolve unexplained glass/contact losses and reduce globally refined native update cost. Adaptive spatial cells and general unit-bearing authoring/revisions remain required. The lab now exposes the first actual permanent-rest mechanism, not completion of the platform.

Commands:

```text
cmake -S . -B build/voxel-contact-audit -DCMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE=C:/Users/henry/Documents/ChatGPT/Banjo/build/voxel-plastic-face/Release
cmake --build build/voxel-contact-audit --config Release --target banjo_connector_plasticity_tests banjo_voxel_world_run banjo_voxel_face_spring_tests banjo_state_recorder_tests banjo_rigid_step_work_tests banjo_reversible_trial_tests banjo_contact_friction_block_tests --parallel 4
ctest --test-dir build/voxel-contact-audit -C Release -R "banjo_(connector_plasticity|voxel_face_spring|state_recorder|rigid_step_work|reversible_trial|contact_friction_block|voxel_gateway|voxel_pipeline|voxel_playback)_tests" --output-on-failure
python tests/voxel_plasticity_test.py build/voxel-plastic-face/Release/banjo_voxel_world_run.exe --results build/voxel-plastic-face-regression-results.json
python tests/voxel_execution_test.py build/voxel-plastic-face/Release/banjo_voxel_world_run.exe build/voxel-compact-record/Release/banjo_voxel_world_run.exe --strict-inline-baseline --alternate-request-order
python scripts/check-source-registration.py
node --check client/voxel-lab/world.js
```

## Published source

Source and tests published to GitHub main as `eda7a89c70d7fde09269db22713abff567d76ba5`. Tested native SHA-256: `c091c4615afac39c86ba034c4dc363ccf27b33b095f10d16826b49a91ad114de`. The publishing follow-up updates the website checkpoint and restarts the local server. All five goals remain open; this is a coherent experimental stage.
