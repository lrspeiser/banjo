# Working on Banjo

## Read before changing the project

1. `docs/project-master-plan.md`: complete product intent and architecture.
2. `docs/development-status.md`: implemented/experimental/planned status, source refs and verification evidence.
3. `docs/roadmap.md`: ordered work and acceptance criteria.
4. `docs/mechanics-scorecard.md`: every retained mechanic, measured boundary and next step.
5. The relevant source/tests and, for conservative contact work, PR #2 and its pinned checkpoint note.

These docs are a snapshot. Fetch current branch/PR state before integration. The contact-development branch is not automatically main. Preserve concurrent changes, especially main's raylib frame-control/busy-wait and MSVC runtime fixes. Do not reset or force-push over other work.

## Owner-authorized publishing cadence

Push verified, coherent checkpoints to GitHub main regularly during development; do not accumulate long local-only runs. The owner authorized this on September 5, 2026. Fetch first, preserve concurrent changes, run checks appropriate to the outgoing scope, and use ordinary fast-forward pushes or the repository's required PR workflow. Never force-push main. Keep credentials and local build artifacts out of commits. Record the published revision and distinguish measured behavior from experimental or unfinished capabilities. A failed check must be fixed or explicitly resolved before publishing its affected code. This authorization covers repository updates, not separate production deployments or messages to other people.

## Physics requirements

Banjo is an editable-physics publishing platform; the balls are a validation laboratory. Material/geometry/state/law inputs drive behavior, not material display names. A declared property is not an implemented constitutive model.

Do not add precut shards, shatter animations, explosion impulses, arbitrary fragment launch velocities, or continual no-slip velocity assignments to make tests look better. Initialize chosen spin explicitly; measure contact-point slip; let friction and torque determine later rolling/sliding. Keep internal damping separate from environmental drag and contact/rolling losses.

Use one authoritative response per contact and account for reactions/torques. Preserve material-derived mass and audit full momentum/energy transfers with external forces/work and numerical correction. Pairwise conservation tests and mass sums are not proof of full-pipeline conservation. Document model assumptions, calibration, units, validity and tolerances.

Analytical projections are not cached fracture simulations. Automatic outcome reuse requires complete physical-state/material/solver keys, applicability/invalidation checks and consistent elapsed time. Do not blend incompatible topology or silently use an unrelated cache entry.

Keep simulation independent of rendering. Start with the CPU reference; optimize measured bottlenecks without changing the material law unnoticed. Support unit-bearing declarative authoring and bounded APIs rather than untrusted arbitrary GPU code.

## Verification and reporting

Material-dependent physics work must compare at least glass and oak (wood) under the same declared experiment conditions. Retain iron in the growing regression set now that it is part of the catalog and comparison work; adding a substance must expand coverage rather than replace earlier cases. Analytical point/spring oracles may remain material-neutral, but general material claims need the comparative scenarios. Record per-material results, timestep/resolution, conserved quantities, expected density/stiffness differences, and unsupported laws. Do not turn oak into a brittle preset or claim grain/plasticity by changing a display name. Maintain `docs/mechanics-scorecard.md` with evidence, limitations and concrete next steps at every physics checkpoint.

Use a separate build directory. Typical commands:

```sh
cmake -S . -B build/agent-test -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/agent-test --parallel 4
ctest --test-dir build/agent-test --output-on-failure
./build/agent-test/banjo_headless
./build/agent-test/banjo_lab
```

For headless work configure with `-DBANJO_BUILD_LAB=OFF`. Record environment and exact commit. Test the normal interactive window/input loop as well as automated capture. Do not claim macOS/Windows, cross-GPU determinism, or material realism from Linux tests alone.

For behavioral changes, add analytical/constitutive/regression tests and record conservation residuals and performance where relevant. Explain any tolerance change. For documentation-only work, validate links and changed-file scope; do not imply new physical validation.

Keep `docs/development-status.md` and `docs/roadmap.md` accurate. Label design, implementation, experimental result and validated behavior separately. State where changes are committed and whether they are on main. Leave a usable checkpoint with remaining defects and next tests rather than claiming the entire platform is complete.
