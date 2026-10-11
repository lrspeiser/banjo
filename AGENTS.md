# Working on Banjo

Banjo is now one thing: the Rube Goldberg game (`/play`, its free build, and
the `/machine` sandbox) and the engine it runs on. The open world and the
physics labs were removed on 11 October 2026 (the last commit with them is
`880939eb`). Do not bring them back piecemeal.

## Read before changing the project

1. `README.md`: what the game is, how it fits together, how to build and run it.
2. `docs/machine-game.md`: every control, piece and level, with what was measured.
3. `docs/machine-physics-roadmap.md`: what the machines' physics does not do yet.
4. The source and tests you are changing.

Fetch the current `main` before integrating. Preserve concurrent changes. Do not
reset or force-push over other work.

## Owner-authorized publishing cadence

Push verified, coherent checkpoints to GitHub main regularly during development; do not accumulate long local-only runs. The owner authorized this on September 5, 2026. Fetch first, preserve concurrent changes, run checks appropriate to the outgoing scope, and use ordinary fast-forward pushes or the repository's required PR workflow. Never force-push main. Keep credentials and local build artifacts out of commits. Record the published revision and distinguish measured behavior from experimental or unfinished capabilities. A failed check must be fixed or explicitly resolved before publishing its affected code. This authorization covers repository updates, not separate production deployments or messages to other people.

Render deploys `main` automatically, so a push to main is a deploy of the game.
After one, check that the site serves the new commit (the page's header shows
it) and still plays.

## Physics requirements

What happens in a level is decided by the engine from materials, geometry, state and laws, never by a piece's name or a level's script. A declared property is not an implemented model.

Do not add precut shards, shatter animations, explosion impulses, arbitrary fragment launch velocities, or continual no-slip velocity assignments to make a level or a test pass. Initialize chosen spin explicitly; measure contact-point slip; let friction and torque determine later rolling/sliding. Keep internal damping separate from environmental drag and contact/rolling losses.

Use one authoritative response per contact and account for reactions/torques. Preserve material-derived mass and audit full momentum/energy transfers with external forces/work and numerical correction. Pairwise conservation tests and mass sums are not proof of full-pipeline conservation. Document model assumptions, calibration, units, validity and tolerances.

A level must be won by physics: every level's own solution has to reach its goal in nudged runs (`tests/machine_game_tests.py`), and a misplaced piece has to fail for a physical reason. Do not loosen a level's goal or a test's tolerance to make a change pass; explain any tolerance change.

## Page controls

Keep action buttons attached to the 3D view: Run it, Pause, Set up again, the piece controls and inspection. Secondary actions may use a clearly labelled disclosure beside the scene. Do not make players scroll through settings to find how to run a machine. Verify visible touch targets and unobstructed labels on desktop and phone portrait/landscape. This is an owner requirement from October 9, 2026.

## Verification and reporting

Material-dependent physics work must compare at least glass and oak (wood) under the same declared conditions, and keep iron in the regression set. Analytical point/spring oracles may remain material-neutral, but general material claims need the comparative scenarios. Record per-material results, timestep/resolution, conserved quantities and unsupported laws. Do not turn oak into a brittle preset or claim grain/plasticity by changing a display name.

Adding a source file is not finished until a CMake target compiles it. A `.cpp` that no target lists is built by nobody, so it never fails and its tests never run. Run the guard before claiming a source change is done, and again before publishing:

```sh
python scripts/check-source-registration.py
```

It reads every `CMakeLists.txt` and `.cmake` file, compares the target source lists against the sources on disk under `src/` and `tests/`, and exits non-zero on any file that no target builds. CI runs it as the `source-registration` job in `.github/workflows/ci.yml`. A file that is meant to stay out of the build goes in the `INTENTIONALLY_UNBUILT` allowlist at the top of the script with a reason. Do not silence the check by deleting the file's test.

Use a separate build directory. Typical commands:

```sh
cmake -S . -B build/agent-test -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/agent-test --parallel 4
ctest --test-dir build/agent-test --output-on-failure -LE "long|performance"
```

For behavioral changes, add regression tests and record conservation residuals and performance where relevant. For documentation-only work, validate links and changed-file scope; do not imply new physical validation. Keep `docs/machine-game.md` accurate when a control, piece or level changes, and say what was measured.

## Keep the local test site current

- Run the local server on port 18893 against the engine you verified:
  `python scripts/voxel-lab.py --native <build>/banjo_live_world_run[.exe]`.
  Check `/api/checkpoint`: `engine_sha256` must be the binary you tested and
  `restart_pending` must be false. An old process or a different executable is
  not delivery of a change.
- Play the change in a browser: the ordinary controls, what changed, and the
  layout on a phone when the page changed. Capture a screenshot for the update.
  Leave the test URL usable.
- Restarting the server ends the live levels on it; say so, and do not touch
  servers that are not yours.
- Never hide remaining failures behind a green build: say what passed, what is
  blocked and what is not done.
