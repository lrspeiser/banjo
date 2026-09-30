# Screen tests and native simulation verification

September 30, 2026. This audit covers every place the current app offers a
test, test result, or QA run for an object: Workshop Test and Build, Recipes,
the world's Bench replay, and Debug. It distinguishes a running native trial
from a calculation, an admission check, and a recording.

## Run the suite

From the repository root, with a configured `build/integration` CMake build and
Chrome installed:

```sh
python scripts/verify_screen_sim.py --mode smoke --build
python scripts/verify_screen_sim.py --mode full
```

Pass `--build-dir` for another configured build and `--chrome` if Chrome is not
at the default path. The runner builds the required native executables when
asked, requires all binaries and Chrome before starting, treats unexpected
skips as incomplete (the world browser's named break-room fixture skip is
allowed), runs browser tests against their own temporary rooms, and
writes each log plus `summary.json` under `build/screen-sim-verification/`.
Both modes also run `tests/workshop_navigation_tests.py`: an empty Lab,
explicit Inventory selection, shared right navigation and unchanged native
bag/hand records. Its fourth journey verifies categorized thumbnail cards,
all 16 offered design-starting blocks, preserved stock and saved-part copying.
These four browser/native checks are additional to the earlier full run
counts below; see the [Visual Inventory evidence](workshop-mode.md#visual-inventory-and-starting-a-design--september-30-2026).
`smoke` executes the real Workshop card contract, representative Workshop and
world browser journeys, a matched glass/oak/iron material triplet, and native
Mechanics and Tool QA. `full` executes the complete Workshop native suite, the
combined world and Workshop browser journeys (the world module imports the
Workshop suite), and the Material, Mechanics, Tool and
Fabrication QA contracts as well as the matched native material triplet. The
run does not use an API key or the player's saved room.

The Material QA catalog has 96 cases and Mechanics QA has 44. The full runner
checks their catalog and execution contracts and runs three matched native
Material cases and two bounded-lift Mechanics protocol cases (oak and iron);
it does not execute all
140 catalog cases. Their own `scripts/material_qa.py` and
`scripts/mechanics_qa.py` commands remain available for exhaustive sweeps.

**Measured full run:** Windows, Python 3.13, MSBuild 17.14 Release and headless
Chrome, September 30. `python scripts/verify_screen_sim.py --mode full --build`
passed all ten steps: native build; 2 product-card contract tests; 31 bench
tests; 35 native room tests; 103 combined world/Workshop browser tests (102
passed, one named break-room fixture skip); 14 Material QA contract tests;
three matched native Material cases; 14 Mechanics tests; 6 Tool QA tests; and
2 Fabrication QA tests. The 103 combined browser tests include 55 Workshop
tests, so the runner does not launch that suite a second time. Logs and
`summary.json` are under `build/screen-sim-verification/20260930-062322/`
(local build evidence, not committed). The run used main base `577dfaa` plus
this checkpoint's uncommitted source; the published commit is recorded in Git.

## What is on each screen

| Screen | Current control | Actual evidence | Boundary found |
| --- | --- | --- | --- |
| Workshop Test: table, stool, bench, breaker, custom | “Try it in a little world” with weight, drop, slide, strike, sun and optional limits | Native scratch-room installation and time stepping, with playback and measured displacement, turning and breaks | Four built-in defaults install. A custom source can still refuse at run time. There are 14 controls, ten outside Advanced. A run without declared limits is an observation, not a pass. |
| Workshop Test: cart | “Roll the cart” | Native articulation trial; chassis movement and axle turns | Uses a rolling collision proxy. It does not prove that the default cart installs in the main world. |
| Workshop Test: kettle | “Heat contained water” | Native thermal trial; water temperature and energy ledger | Contained thermal proxy; no sloshing or pouring. It does not prove world installation. |
| Workshop Test: chair, shelf-unit, rover, drone, processor, mine-lamp, solar-array, electric-furnace | No runnable default-product simulation | Their default source is refused by the current native little-world installer | The previous catalogue incorrectly offered the little-world card for rover, drone and processor; it hid the now installable stool and breaker. The catalogue and a native contract test now agree. |
| Workshop Build | Buildability, Check it, point-force/joint screen | Grid compilation and a static equivalent force calculation | These answer geometry or load-path questions; they do not run a dynamic impact or certify bending, fracture or joint life. “Check it” may redraw and must report the change. |
| Recipes | Grid-ready/draft label, stock and Make | Same source checked on Workshop and open-world grids; Make calls native placement preview | Grid-ready is not evidence that the declared function passed a trial. Placement can still fail at the chosen location. |
| World Bench | Select run, play, scrub and speed | Playback of a previously recorded run | It does not start a new experiment. The run's source and acceptance limits should stay visible with the replay. |
| Debug | Material QA (96 cases), Mechanics QA (44), Tool QA (6), Fabrication QA (fixed suite) | Server-side native QA reports, with case picker for the first three and one fixed Fabrication run | Material and Tool cases use reference fixtures, not the selected Workshop object. Fabrication runs its whole suite, which has no case picker. A passed reference case does not qualify every product. |

## Findings and proposed adjustments

1. **Keep the screen catalogue executable.** The new native contract runs each
   built-in source through the same little-world bench that the Test button
   uses. It fails if a card is offered for a refusing default or a newly
   installable default is hidden. The stool and breaker are now offered;
   rover, drone and processor defaults are withheld until their adapters or
   source designs are repaired. Custom designs still need a source-specific
   preflight before enabling Run.
2. **Reduce the first view to a scenario and its relevant inputs.** Offer
   “Stand”, “Set a weight”, “Drop”, “Slide”, and “Strike” as choices. Reveal
   `from_m` only for a weight, strike speed and height only for a strike, and
   time of day / program power only when the source uses them. Keep the current
   combined inputs under Advanced for complex experiments; the backend already
   supports composition.
3. **Keep result labels narrow.** Show “Measured” until the user declares
   limits, then “Passed”, “Failed”, or “Unsupported for this run”. Put the
   applied load beside the requested load, and keep “Grid ready”, “Trial
   passed”, and “Installed” as separate recipe states tied to the source
   fingerprint. This avoids turning a 40 mm geometry check into a strength
   claim or a reference cart trial into world-installation proof. In Tool QA,
   a valid run can pass its execution checks while the point stops at rock;
   show the actual effect beside that QA status instead of calling it a
   successful excavation.
4. **Make Debug easier to scan.** Add filters for material, thickness, speed
   and outcome to the 96-case Material QA picker. Offer one-click matched
   glass/oak/iron batches, because comparison is more informative than a
   single material case. The fixed Fabrication suite should expose its case
   names, estimated cost and last result before Run. Keep the current report
   link for detailed evidence. Extend the Mechanics protocol's bounded-lift
   pair with glass so that reference path also has a matched material triplet.
   The runner already avoids a duplicate full Workshop browser pass: the world
   browser test module includes those tests, and the runner checks that it did.
5. **Clarify replay and rock progress.** Call the world Bench “Recorded runs”
   where it lists results. Tool QA now uses the implemented `rock-work-v1`:
   in the matched 4.5 s trials, an iron point works into rock but no whole cell
   is removed. The native contact currently says `broke out` even with zero
   removed mass; the QA summary says “no whole cell removed”. Rename that
   native event when partial work is reported so the screen cannot imply a
   mined cell.

The present suite proves only the tested builds, scenes, configurations and
time windows. It does not certify material calibration, arbitrary custom
products, every terrain placement, or long-term durability.
