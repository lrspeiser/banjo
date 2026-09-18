# Precise-rigid live-world verification

## Published source and executed gates

Tested source: `48dd87d9fa7259f14ac0c2a5180175cfe1432ece`.
Tested tree: `8acad8de10b3f484e467fc47afdb0d8b71358077`.
GitHub Actions run: `35312523607`, job `105497300960`, Ubuntu 24.04.
Run: https://github.com/lrspeiser/banjo/actions/runs/35312523607

All targeted gates passed. The runner compiled the actual Release native engines and live-world tests, then executed:

- 224 source/API/persistence tests across 25 separate Python suites.
- 18 new precise-live tests through registered CTest `banjo_precise_rigid_live_tests`: five admission cases and thirteen native subprocess cases. The engine path was required; absence is a failure, not a silent skip.
- 37 retained native integration tests: 11 isolated precise-rigid, 15 existing lattice installation, and 11 existing Workshop bench tests.
- All 21 actual Chrome Workshop journeys, including the new Workshop-to-live-world installation and reload journey. No browser tests skipped.
- The C++ `banjo_live_world_tests` executable and native platform package/geometry/three-material/clone/budget checks.
- JavaScript syntax checks for Workshop and the live world, and source registration (272 compiled source files accounted for).

This is 300 passing Python tests across the targeted CI gates, plus the C++ executable checks; do not count the 18-test CTest wrapper a second time. The native live-world CTest took 37.89 s on this runner; this is a test-suite runtime, not a world-scale performance benchmark.

The `precise-live-verification` artifact contains `VERIFIED.txt` and `commit.txt` naming the tested source above, source.tar.gz, build/source/native/browser logs, and actual Chrome screenshots. `screenshots/thin-rigid-live-world.png` shows the installed table in the live room, not a generated rendering.

Additional local HTTP/room/access/inventory regression checks ran ten separate suites: 148 passed and one native drop-builder check skipped because that legacy test searches fixed build paths rather than this checkpoint's build directory. Those additional checks are not included in the 300 CI total. The native platform and precise-live gates above used explicitly configured, built executables and passed.

## What the end-to-end test establishes

The browser creates a table with a 5 mm top and 15 mm square legs, explicitly selects the precise-rigid model, consents to authoring installation, previews, confirms, and enters the actual live world. It checks five native collision/render shapes, zero lattice cells, the actual 5 mm mesh thickness, unsnapped X placement at 3.123 m, approximately 3.41565 kg oak mass, native picking, and persisted body identity after a page reload.

Native checks additionally cover glass/oak/iron under the same geometry and experiment, effective mass and inertia using an independent initial-energy oracle, a small object landing on the thin top, an open leg space, actual motion, rotating and held-object state carry, native process restart, idempotent receipts, stale previews, collision refusal, disk-failure rollback, and fail-closed malformed-state/unsupported-operation handling. The physical assertions were not replaced by visual plausibility or a canned trajectory.

See [workshop-precise-live-checkpoint.md](workshop-precise-live-checkpoint.md) for units, tolerances, numerical results and reproduction commands.

## Merge audit

Previous thin-part and visible-simulation work was already on main at `8d9ea502f81b229acd1b60b19b2946dfc513010c`.
The previously outstanding inspection PR #16 was reconciled without reverting those newer changes and integrated into main through `c373ef9e5c9a83b33a6712e4f34028d6232fab07`. Its head `a347cdfec13642e639fd3db43b715d5010a798f2` is part of the actual merged ancestry. Its obsolete feature-branch-targeted PR card was closed with this integration recorded; the card's separate `merged` flag is not the evidence of main's ancestry.
All 20 inspection-era Chrome journeys passed in run `35311121292`; they remain included in the new 21-test browser gate.
A subsequent repository search found no open pull requests. Temporary verification workflows and encoded staging payloads remain on the tooling branch; they are not product code to merge into main.

## Explicit remaining scope

This delivers a bounded authoring Workshop-to-world path, not every part of the proposed architecture. Precise compounds are homogeneous, connected local axis-aligned boxes and can move/rotate as native rigid bodies. The room admits anchored lattice scenery and other admitted precise compounds, not dynamic lattice deformation/fracture coupling. Installation does not consume inventory or fabrication energy. The model has no internal deformation, thermal response or attachment-failure law.

Next acceptance gates remain: authoritative dynamic lattice/precise force and torque coupling; supported joints and attachment behavior; representation-aware inventory, fabrication and general editing; actual beam/sheet/cable solvers; and per-body resolution/localized detailed fracture. Unsupported operations are explicitly refused rather than silently changing the mechanical model.

These targeted Linux CPU checks do not claim full-repository CTest completion, Windows/macOS/GPU qualification, collision energy conservation, material strength calibration, or a production deployment.
