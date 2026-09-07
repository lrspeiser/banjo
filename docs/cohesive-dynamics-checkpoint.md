# Parallel physics: coupled separation and visible accepted states

September 6, 2026; developed from main `69a3fc6`, Windows MSVC 19.44 Release, double Jolt. All nine workstreams, 40 retained mechanics and R01–R10 remain active. This checkpoint does not complete calibrated glass shattering, tomato slicing, unloaded metal dents, or world-scale realtime.

## Integrated implementation

`CohesiveDynamicPatch` advances tet-local nodes and irreversible facet history with one velocity-Verlet clock. Cached elastic/orthotropic tetrahedra supply bulk forces, and the cohesive assembly supplies interface forces and separation. Fixed-component reactions, external work, stored bulk/interface energy and fracture dissipation are reported. Invalid trials leave positions, velocities, history and time unchanged. J2 bulk is explicitly unsupported in this adapter.

`CohesiveSphereWorld` couples this state to the shared `SphereSurfaceContactStep` also used by the existing nonfracturing sphere/patch solver. It checks combined sphere/material momentum and raw energy before committing either participant. Exposed faces enter final contact constraints and penetration validation. Facet failure is detected at drift endpoints: event-time subdivision is still required for converged contact against newly exposed faces. Fragment self-contact and support/ground collision are absent.

`FractureComponentState` derives mass, momentum, angular momentum, inertia and best-fit rigid motion from actual separated material. Internal kinetic energy is retained and singular inertia is reported. It does not launch or animate fragments.

The optional pure `CorotatedTet` kernel passes rigid-rotation objectivity, potential-gradient, small-strain limit, force/moment and validity checks. It is not yet the bulk law in this coupled experiment; rotating cohesive frames, finite-rotation integration and continued contacts remain next dependencies.

## Actual sphere impact evidence

The reference is a **launched sphere into a fictional numerical material**, not a glass plate or gravity drop. Target: 80 × 20 × 80 mm, six tetrahedra, E = 1 MPa, density = 1000 kg/m³, Poisson ratio = 0.25. Sphere: radius 12 mm, density 7870 kg/m³. Interface: normal stiffness 1e9 Pa/m, tangent stiffness 2e8 Pa/m, strength 10 kPa, fracture energy 0.1 J/m². Both cases request 8 ms at 0.2 of the same stability limit; per-step raw energy gate 2e-4 J, no altered strain limit.

| Quantity | 0.03 m/s control | 1 m/s impact |
|---|---:|---:|
| Status | Complete | Solver limit: small displacement gradient |
| Accepted time | 8 ms | 6.192587 ms |
| Accepted steps / contacts | 849 / 261 | 657 / 435 |
| Fully separated facets / components | 0 / 1 | 6 / 6 |
| Newly exposed faces | 0 | 12 |
| Signed cumulative numerical energy residual | 2.18843e-7 J | 7.52983e-5 J |
| Sum of absolute numerical energy residuals | 3.82473e-7 J | 1.21404e-4 J |
| One contended diagnostic run | 14.7643 ms | 17.2702 ms |

These timings do not qualify realtime performance. The high case test requires and reports its actual stop; full-duration fracture acceptance is still open. Matched glass/oak/iron elastic controls also complete an actual-contact onset with an explicitly numerical, uncalibrated interface; they do not validate material fracture differences.

## Other parallel categories

**Fire:** the bounded native `banjo.thermal-experiment-request.v1` API advances explicit thermal cells, a finite heater, finite fuel/oxygen and reaction products. In a matched 3000 J heater / 0.1 s two-cell protocol, oak releases 7747.396 J of chemical heat; glass and iron release zero. All complete in 10 jobs / 60 cell operations, with zero remaining duration/backlog. Mass residuals are zero and the largest combined energy residual is 3.64e-12 J. This is a lumped reactive model; airflow, smoke, calibrated burning, mechanical coupling and arbitrary chat-authored thermal playback are unfinished.

**Metal:** the new post-yield regression preserves every J2 tensor/history, sphere state, motion, clock and ledger through a rejected step; 200 following steps match uninterrupted execution. The fictional J2 fixture reaches equivalent plastic strain 0.00180952 and tensor norm 0.00221017. A current endpoint displacement cannot prove a permanent dent: the matched elastic probe remains similarly displaced while vibrating. Full-state restart and unload/residual-equilibrium acceptance are next.

**Cutting:** the public native wedge/tomato network route is now tested against a blade-absent control and a refined timestep over the same 0.4 s. Control has no damaged/broken links or fracture work. Tool runs give 42/18 damaged/broken links and 0.4263 J at 1/480 s, versus 65/22 and 0.7163 J at 1/960 s. All retain 120 cells, 2.1943 kg and one connected core. The tool causes damage, but timestep sensitivity precludes converged cutting or full-slice claims. Resolved blade contact and a soft-tissue law remain required.

## Playground and verification

`python tools/archive_cohesive_reference.py build/cohesive-sphere-probe.json` creates a separately labeled native development archive. It does not call GPT, change the user's request or replace an earlier job. The existing 3D viewer renders accepted nodal positions, original plus newly exposed faces, component colors, per-component fracture evidence, 0.001× slow playback and scrubbing back to the intact state. GPT diagnostics retain signed/absolute residuals and fail incomplete-duration checks; no unsupported glass claim is inferred.

Native verification: **72/72 suites passed, 92.82 s**. **153 Python tests passed, one skipped** (154 discovered, 10.413 s). Browser evidence is recorded with the published output bundle. Normal browser playback, reset/scrubbing, initial/final component surfaces and explicit solver-stop/provenance messages were inspected. The original failed glass-drop archive remains unchanged.

Next integration order: finite-rotation bulk/cohesive objectivity and event subdivision; continued support/fragment contact; calibrated, refined glass/oak/iron impact comparisons; connect completed laws to general LLM authoring. Fire, metal persistence/unloading and blade/tissue work continue as independent bounded assignments. Do not mark a category complete because one worker's assignment finished.
