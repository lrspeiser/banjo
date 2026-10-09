# GPU representation adapter: isolated flight and an awake material island

October 9, 2026. **Implemented experimental first adapter. Full representation architecture, material impact accuracy and whole-world realtime remain OPEN.** Source parent main `5b08796e9dc52adb3204c33e9e170e6ffb4e9d8d`. This implements part of the [object representation design](object-representation-design.md), addressing a cost measured in the [drop audit](drop-performance-audit.md).

## What you can test

Open `/coupled?representations=1`. **Object representations → Independent rigid flight** selects the new adapter; **Whole coupled solve** remains the reference/default. Set **Experiment → Ball / ground**, mass **0.01 kg**, height **10 m**, then use **Follow ball** and **Run 0.1 s** or **Run to ball contact**. Accepted states show the rigid sphere's actual gravity-driven motion. The Ball representation and switch count reflect accepted ownership changes. The backend advertises up to 16 flight steps per request only when a swept bound proves separation from fixed surroundings for that entire interval; otherwise delivery requests one host tick. Every microstep remains in the exact experiment log. Stop prevents subsequent requests after the in-flight bounded request.

Choose **Connected sheet**, the same iron ball/mass/height, and glass/oak/iron/ice to retain the material comparisons. The sheet remains awake under gravity and its supports. This is still slow; the 10 m glass case retains its convergence refusal. No internal ball fracture, calibrated bulk dents, grain, flowing matter, thermal/reaction coupling, automatic sleep or reduced elastic modes are added here.

## Implementation and validity

- [`FlightPartition`](../scripts/gpu_representations.py) derives a private island cache from the canonical world arrays. It accepts one unattached dynamic isotropic sphere; attached spheres, multiple candidate spheres, unknown shapes and rotating dynamic planes remain coupled. It depends on the existing bounded finite-cell world, not arbitrary world authoring.
- A CUDA bound encloses the sphere's whole constant-gravity path using a chord plus `|g| h² / 8` curvature allowance. Other boxes use enclosing spheres for all orientations; dynamic island centers use the unchanged accepted travel envelope. Fixed planes use their actual normal. A 1e-10 m activation margin encloses FP64 geometric roundoff. This selects calculation ownership and never supplies an impact response.
- The isolated CUDA integrator uses the same midpoint translation and isotropic-spin Cayley update as the reference. The island continues its nonlinear material/support solve. If its motion exceeds the envelope, the trial subdivides/refuses before acceptance. No sheet is frozen, gravity skipped or dissipation invented.
- Positive separation allows sphere travel to exceed the unrelated 2 mm island guard; that guard remains in force for every island member. Near an uncertain/contact interval the complete coupled evaluator owns response. No contact impulse is applied twice. Angular, compression, P/L/energy and work budgets remain unchanged.
- Material histories, endpoint IDs and poses/velocities are retained in canonical arrays. Cache-local endpoint indices are derived maps. Ownership changes use identity state mappings: there is no topology conversion or measured rigid-to-deformable transfer in this adapter. The corresponding accepted substep contains the actual full P/L/energy account. The ball is a rigid primitive in both modes.
- World publication is transactional as well as stepping: errors while publishing a snapshot restore host clocks, accounts and representation history, in addition to GPU arrays. Work already attempted remains observable as a rejected candidate.
- The evidence fingerprint is pinned to the loaded implementation. A long experiment cannot silently label old code with a newly edited disk hash; new scenes refuse a mixed-version worker. The website checks its requested source against the worker's actual source.
- The eight-family catalog identifies the design target. General versioned object authoring/serialization, active/dormant field mappings, thermal/chemical/flowing solvers and cross-family transfer are unfinished.

## Comparative scope and tests

Windows x64, NVIDIA GeForce RTX 5090, CuPy 13.5.1 / NumPy 2.5.3, FP64 CUDA with `--fmad=false`; MSVC Release CPU oracle. Separate build `build/voxel-contact-audit`, outputs `build/voxel-endpoint-final/Release`. PR #2 remains merged at `29254bd0a0f8287ac6470f5c1d5af5fad32d6161`; its contact laws are unchanged.

The high-speed diagnostic starts a 0.01 kg iron sphere 10 m above the sheet with **14 m/s initial downward velocity**, at host dt **1/240 s**. It is one host interval, not a replay of the entire drop. All sheets use the same nine 10 mm cubes and two 8 mm wide fixed supports. Density/Young's modulus are glass 2500 kg/m³ / 70 GPa, oak 700 / 12, iron 7870 / 211 and ice 917 / 9. Sheet dynamic masses are 0.0225 / 0.0063 / 0.07083 / 0.008253 kg, plus the same 0.01 kg ball. Oak remains an isotropic interface experiment; iron uses six-mode connector plasticity, not continuum J2.

| Sheet | Reference accepted microsteps | Partitioned accepted microsteps | Meaning |
|---|---:|---:|---|
| Glass | 32 | 2 | Ball moves independently; sheet still responds |
| Oak | 32 | 1 | Same declared geometry/loads |
| Iron | 32 | 2 | Existing plastic history retained |
| Ice | 32 | 1 | Prior material coverage retained |

See [final adapter controls](evidence/gpu-representations/controls.json) for signed residuals, common-time sheet differences and timings. Maximum common-time position differences in this one-interval comparison are below 1e-9 m; this is not impact/refinement qualification. All interval P/L residual norms stay within the unchanged 1e-9 N·s / N·m·s gates and energy within the existing scale-dependent gate.

Further tests cover four material-density freefall/spin oracles, live support sag, exact low-energy reference contact states/history, an intervening sheet despite clear flight endpoints, rotated-plane refusal, canonical nonmutation during proposal, whole-interval island failure, post-step snapshot-publication failure, unknown policies and mixed-version refusal. Near-contact batch hints revert to one; Node tests verify duration, the 16-step delivery bound, Stop and expired-session cancellation. Source registration is 345/345; the new Python regression is explicitly a CMake/CTest entry and executes the CUDA kernels.

[Reference CPU/CUDA controls](evidence/gpu-representations/reference-controls.json) and [parallel/serial parity](evidence/gpu-representations/pipeline-parity.json) retain 12 shared trial comparisons, 128 GPU candidate comparisons, 480 localized Jacobian trials, four complete low-energy histories and 162 fault-priority cases. Those reports use loaded source `3d76d94...`; the final adapter/delivery report uses `2ec72186...`. The intervening changes add conservative delivery hints and snapshot metadata, not contact/material arithmetic. Final affected adapter/delivery tests are rerun after that change. This is scoped verification, not the full repository, physical-phone or cross-GPU suite.

## Performance: distinguish the paths

[Backend measurements](evidence/gpu-representations/backend-performance.json), loaded source `3d76d94...`, include complete Python `advance` calls and accepted snapshot production, excluding HTTP/browser:

| Case | Accepted physical s | Wall s | Result |
|---|---:|---:|---|
| Glass rigid sphere / fixed plane, collision-free prefix | 1.3333 | 0.4558 | 2.93× physical/wall |
| Oak rigid sphere / fixed plane, collision-free prefix | 1.3333 | 0.3921 | 3.40× |
| Iron rigid sphere / fixed plane, collision-free prefix | 1.3333 | 0.3806 | 3.50× |
| Ice rigid sphere / fixed plane, collision-free prefix | 1.3333 | 0.4285 | 3.11× |
| Iron ball / connected glass sheet, 10 m full attempt | 1.4250 | 42.2685 | Newton limit; rejected interval restored |

The glass attempt is roughly 30× slower than wall time, despite removing the old flight subdivision cost. It has no accepted impact. The remaining material solve runs throughout flight and the strong-contact nonlinear failure remains. This fails the whole-world realtime and impact-completion gates.

[Final HTTP measurement](evidence/gpu-representations/http-performance.json), loaded source `2ec72186...`, uses 20 bounded requests of 16 steps for the iron sphere/fixed-plane collision-free prefix: **1.3333 physical s / 1.2615 wall s = 1.057×**, maximum request **84.1 ms**. It includes the worker, JSON, exact replay journal and localhost HTTP; excludes browser rendering. Another GPU regression was running, so these single-run timings are diagnostics, not a throughput/tail-latency qualification. Near contact and material-sheet performance are not established by this prefix.

## Next work and open acceptance

1. Replace whole-island dense numerical Jacobian work with local derivative blocks and resident sparse solving; independently check derivatives and retain accepted work/history gates.
2. Add a qualified reduced elastic continuation for small deformation. Retain vibrational energy and evolving prestress; freeze neither a loaded sheet nor unexplained motion. Promote under error bounds, changing support/load or damage.
3. Repair actual strong-contact convergence and compare common-time response under timestep/spatial refinement across glass/oak/iron/ice. Completion and conservation alone do not certify accurate response.
4. Add compatible detailed sphere geometry, adaptive regions and damaged-fragment reactivation with actual mass/inertia/history transfer receipts. Then extend the registry and coupled thermal/phase/chemical/flowing families from the design.
5. Measure the full physics → journal → delivery → browser pipeline over sustained impacts and multiple objects. Preserve responsive Stop and accepted-state rendering. Require ≥1 physical second per wall second with headroom before claiming gameplay readiness.

The active objective remains incomplete. This adapter is a usable experimental checkpoint, not completion of the eight-family system.
