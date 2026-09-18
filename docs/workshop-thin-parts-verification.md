# Thin-part checkpoint: verified execution

Tested source: `00c973ade20d3a4b0e1404c9f3c2a095d6369a54`. GitHub Actions run `35308400162` on Ubuntu 24.04.

All targeted gates passed: 224 source/API/persistence tests in 25 separate Python suites; 37 native-engine integration tests (11 precise-rigid, 15 existing installation, 11 existing bench); all 18 actual Chrome Workshop journeys; and the native platform executable's package, geometry, three-material motion, clone and budget checks. Node syntax and source registration passed. No browser test was skipped. Native binaries were restored from an exact CMake/native-source hash cache and executed again; the original binaries were built in run 35306891351.

The Chrome thin-table journey checks the 5 mm tabletop and 15 mm legs, zero-cell grid warning, explicit rigid selection, 3.416 kg oak mass independent of comparison grid, actual native motion and trace scrubbing, five collision shapes in one rigid body, and save/page-reload persistence. Screenshots were retained alongside the source, native and browser logs in the `thin-startup-verification` artifact for this run.

The browser gate caught and fixed a nested-heading editor insertion error before main promotion. Fixture creation uses the existing session-token helper. Post-reload diagnostics wait for the asynchronous audit, and the budget regression requires the explicit 50,000-cell message; physical assertions and access protections were not weakened.

These are targeted Linux CPU checks, not a completed whole-repository CTest, macOS/Windows/GPU, performance or fracture-validation claim. The precise-rigid path supports homogeneous, connected axis-aligned box compounds in the isolated Workshop test only. Precise-rigid live-room installation/state carry, beam/sheet/cable solvers, per-body voxel resolution and localized fracture remain unfinished. See `workshop-thin-parts-checkpoint.md` for admission limits, numerical evidence and reproduction commands.
