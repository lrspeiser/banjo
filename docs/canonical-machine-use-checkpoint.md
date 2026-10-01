# Canonical machine Make and Use

October 1, 2026. Windows main, based on `2db3260333157f8b14f390ff657060cc1130239a`.
Verification ran with the implementation changes uncommitted. Implementation
`51648f9` is published on GitHub main. Refreshed own 8770 preview reopens the
existing 10-body world and passes fresh entry, two component thumbnails, native
22-cell pick pickup and mini Inventory with no JavaScript exceptions.

## Implemented

Canonical rover, drone, processor and electric-furnace designs now carry a
purpose-specific Start program. Mine-lamp has Switch light on; the passive solar
array has Inspect power. The bounded `machine_power` action operates the existing
native program or lamp, with an explicit boolean on/off value. It supplies no
energy, materials, prescribed motion or production result.

Admission requires exactly one declared device. Use checks the current attached
assembly, native visibility and 3 m reach. Existing rover recovery-grip refusal
and native energy/input/heat limits remain. An unwired lamp stays dark. Failed
saves report uncertainty and request the same on/off command. Sender identity
includes the native session, so saved command sequences cannot block a new
session after its monotonic clock resets. Standalone C API worlds explicitly
refuse the primitive because they lack its portable controller binding.

Bare canonical requests retain template machine/construction declarations
through candidate, quote and Save adapters. Explicit override documents remain
authoritative, including an empty document that removes machinery. Constructed
machines still refuse generic size variants; parts must be edited directly.
Workshop chat validates a device before applying its new program and explains
these requirements to the LLM. Existing explicitly saved programs remain intact.

The browser acceptance found a preexisting controller-validation crash when a
new rover followed a stationary processor. The validator now handles programs
without wheels while retaining duplicate wheel-owner refusal in either order.

World MCP is 1.21.0, platform MCP 1.24.0; native ABI remains 25.
The missing processed-funding rows are also added to the API tables.

## Verification

[Retained native/browser evidence](evidence/canonical-machine-use-checkpoint.json).

- Fixed Fabrication QA: **68/68**, 101.914 s. Native installation/use, damage
  retention, rollback, whole restart, stock/energy accounting and actual Chrome
  funding remain covered, including the retained glass/oak/iron comparisons.
- Actual Chrome Recipes → saved canonical rover → Lab funding → work → native
  placement → World J Use passes. Supplies come from an explicitly authored
  fixture heap collected through three normal, bounded 25 kg pickup calls.
  Energy comes from the generated native solar battery. No JavaScript exceptions;
  the capture was visually inspected and includes component thumbnails.
- Rover quote: glass 4 kg, oak 37.807790509 kg, iron 11.731241381 kg, separately
  copper 0.5 kg and wire 2.3 kg. Authored shaping work 5353.903189008 J plus
  separately funded 1000 J initial battery charge. Native Use starts the program
  and increases the battery's actual given-energy counter. Local material,
  processed-goods, work and energy residuals are zero in the browser case;
  source-transfer residual is 1.457e-10 J.
- Native rover/lamp admission: distant Use changes no machine state; explicit
  start/stop and lost-save on/off retry pass. Mine-lamp switches on but remains
  unlit without wiring. Whole reopen and the final focused clock-reset test pass.
  Cumulative local energy residual is at most 2.729e-12 J in this pair.
- Actions **40/40**, Workshop chat **38/38**, API **16/16**, rover declarations
  **7/7**, public API docs **12/12**, components **6/6**, fitting **47/47**.
- Configured paid AI checks **4/4**, 26.071 s: own supplies/energy, restart and
  pending-write recovery remain covered. Full fresh-world acquisition is open.
- Source registration **287/287**, no exclusions. No C++ source, solver, material
  law, timestep or tolerance changes. Existing Windows MSVC Release native
  binaries in `build/agent-paid-machine/Release` were used; native fixture stepping
  remains dt=1/240 s and scenery 40 mm.

```powershell
$env:BANJO_LIVE_ENGINE=(Resolve-Path build/agent-paid-machine/Release/banjo_live_world_run.exe).Path
$env:BANJO_LIBRARY=(Resolve-Path build/agent-paid-machine/Release/banjo.dll).Path
$env:BANJO_BUILD_DIR=(Resolve-Path build/agent-paid-machine/Release).Path
$env:BANJO_BROWSER_TESTS='required'
python scripts/fabrication_qa.py --engine build/agent-paid-machine/Release/banjo_live_world_run.exe --out build/resource-flow/canonical-machine-use-20261001
python tests/fabrication_tests.py NativeFabrication.test_canonical_machine_paid_admission_primary_switch_native_motion_and_restart
python tests/actions_tests.py
python tests/workshop_chat_tests.py
python tests/workshop_api_tests.py
python tests/rover_room_tests.py TheRoomDeclaresIt
python tests/api_docs_tests.py
python tests/workshop_components_tests.py
python tests/workshop_fitting_tests.py
python tests/ai_player_tests.py -k paid -v
python scripts/check-source-registration.py
```

## Boundary and next gate

The finite process and collected supplies are explicitly configured fixtures.
This does not establish fresh-world autonomous supply acquisition or a default
workbench. The other canonical machine Start programs are declared/compiled;
this checkpoint's paid operational journeys measure rover and lamp. General
drone flight, furnace yield, physical constituent incorporation and calibrated
forming require their own acceptance. Unsupported recipes still refuse.

Next declare the ordinary zero-supply workbench, migrate the normal player/AI
guards, and verify complete fresh-world paid progression and actually damaged
tool replacement/equip/use. No healing, strength or full-world conservation
certificate is added. All fourteen player requirements remain active:
**four verified, ten partial**.
