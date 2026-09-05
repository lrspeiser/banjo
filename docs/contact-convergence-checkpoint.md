# Contact-state convergence diagnostics and numerical controls

September 5, 2026. Local experimental checkpoint; full goal active.

Adaptive refinement-floor errors now retain two bounded per-body component records and the coarse/fine rigid snapshots. The component records separate normalized position, linear velocity, angular velocity and orientation discrepancy. This identifies what fails instead of reporting only one aggregate maximum. The snapshots use the existing SI motion representation. They are diagnostics, not accepted state or portable replay checkpoints.

The version-2 temporary assembly test accepts optional `body_pair_contact_cache` (boolean, default true) and `contact_iterations` with exactly `velocity` (2..256, default 10) and `position` (1..64, default 2). The velocity minimum preserves Jolt's documented requirement for friction iterations. Numerical settings appear in successful integration reports and refinement-floor diagnostics. The two host setters are allowed only before any bodies/supports are created and reject during reversible trials. Persistent application worlds keep their existing defaults; no migration or native promotion occurs here.

The cache switch controls Jolt's narrow-phase body-pair result cache. It does not disable surface contacts, friction, restitution or contact-impulse warm starting. Increasing iterations changes solver work, not material constants. These controls make the experiment reproducible; they are not a recommendation to disable caching globally or a complete solver fingerprint.

## Component evidence

At the default rotational fixture failures, angular velocity dominates the normalized state difference. Position discrepancies are approximately 6.94e-10, 1.46e-8 and 1.80e-8 of the 0.03 m reference length for glass/oak/iron. Orientation discrepancies are zero, about 1.28e-6 and zero respectively. The largest normalized angular-velocity discrepancies are 0.346641, 0.0726285 and 0.201627. Raw coarse/fine states show material changes in spin despite almost identical poses. This is not evidence that a position-only acceptance test would be sufficient.

## Same-fixture numerical comparison

All experiments preserve the three-material 0.1 s rotational fixture, initial state, law, work budget, 512 initial intervals, state tolerance 0.001 and minimum actual half step 1e-8 s. Only the listed numerical settings change. All twelve trials reject at the refinement floor.

| Velocity / position iterations | Pair cache | Glass discrepancy | Oak discrepancy | Iron discrepancy |
|---|---|---:|---:|---:|
| 10 / 2 | On | 0.346641 | 0.0726285 | 0.201627 |
| 10 / 2 | Off | 0.466102 | 0.210729 | 0.109017 |
| 80 / 8 | On | 0.346642 | 0.189926 | 0.571592 |
| 80 / 8 | Off | 0.466101 | 0.128224 | 0.285037 |

Failure times shift in some settings, so these values are not errors at identical terminal states. They show that the tested cache/iteration changes do not resolve the requested trajectory under its unchanged criteria. More iterations do not monotonically improve this result. This rules out treating cache disabling or the tested iteration increase as a sufficient fix; it does not prove the internal cause or rule out every solver configuration.

## Deferred investigation

Inspect the contact manifold/separation and impulse evolution around the failing interval, including friction/restitution branch choices and contact-event timing. Separate geometric precision and discontinuity effects from iterative convergence. Preserve work and state criteria; do not accept position agreement while discarding the angular discrepancy. The prior adaptive smooth successes and all rotational failures remain regression evidence.

Runtime-v3 save migration, other inertia adapters, persistent joints, physical crafting/cutting, native promotion and every remaining full-goal gate stay open.

Prior diagnostic changes passed all 28 promoted and 26 legacy suites (26.36 s / 20.05 s). The owner has now prioritized the crafting bowl lab; this contact investigation is paused, with all failures retained.

Source retained in local checkpoint `c717509` alongside the bowl runtime.
