# Processing guidance and live recipe evidence

October 3, 2026. Implementation/test checkpoint against main `efeed41` on
Windows, Python 3.13, existing MSVC Release native executables in
`build/agent-object-strike/Release`. Native binaries, material laws, terrain
resolution and completion predicates are unchanged.

## Implemented

- Processing goals choose a compatible curated process from current private
  supplies and actual hopper input. Owned stored ground counts; another
  player's lots and older unassigned lots do not become personal supplies.
- Inventory loading, machine recipe views and shared guidance use the same
  current input facts. The existing authenticated guidance reaches World,
  Workshop screens and AI Guide observations. Transfers still recheck their
  normal distance, ownership, native and paired-save gates.
- Recommendations identify storing, selecting, loading, powering and watching.
  A positive known ore source gets a human-facing destination rather than an
  agent's stop instruction. This does not add a new gathering mechanism.
- Machine observation follows the actual live routine recipe, preserving the
  declaration key and existing saved-batch outbox/replay boundaries.
- World offers Power / Watch batch beside recipe selection. Recipe drafts
  survive live rerenders within the same session/current-recipe binding;
  refresh results from replaced sessions are ignored. Next action remains
  visible when a selected object's details hide the normal target panel.
- The goal guide links to World and explains the real steps. Selecting or
  watching alone grants neither a batch nor mastery.

## Automated evidence

- `python -m unittest discover -s tests -p game_guidance_tests.py -v`:
  11/11 pass, 21.407 s. Private supply/funding and seven chat screen snapshots
  retain the shared recommendation contract. Provider responses are mocked.
- `ctest --test-dir build/agent-object-strike -C Release -R
  '^banjo_process_guidance_tests$' --output-on-failure`: 1/1 registered suite
  passes in 42.91 s. It runs two native host cases, not the legacy browser
  driver imported elsewhere in that test module.
- The actual native sand fixture yields 5.95 kg glass from 7 kg sand, debits
  native heat/work, records one owned watched batch and collects the output.
  Exact replay/full restart retain the selected recipe, output and evidence;
  a peer receives no private credit. Native watched poses are refreshed by
  ordinary step messages during the longer heating sequence, retaining the
  existing observation freshness limits.
- An analytical read-only 0.5 kg input preview catches `convert` consuming a
  copied dictionary. It preserves source facts and changes no material or
  completion evidence. Private/current-input/Market facts agree.
- Two additional existing native copper witness/skill-shortage cases pass,
  retaining outbox failure/restart behavior. No prerequisite was removed.
- Source registration: 297/297 sources in ten CMake files, no exclusions.

## Ordinary browser evidence

The isolated server on port 8774 continues the fresh ordinary opening in
[the prior walkthrough](opening-human-supplies-checkpoint.md). The owner's
port 8771 was not changed. No grants, teleports, hidden browser state writes,
Market purchases or wallet deposits were used in this continuation.

The player walks near the furnace, turns it off, selects Melt Glass, stores
1.554498 kg gathered sand through Inventory, loads that owned lot into the
intake, turns the furnace on and watches while nearby/facing it. Native heat
and work produce 1.3213233 kg glass (UI: 1.32 kg), with declared processing
work approximately 1244 J plus separately debited heating. The second chapter
then shows all four goals complete. A full test-server restart retains that
chapter, the actual process selection and output. Screenshot artifacts are
local and ignored under `build/opening-human-1003/`.

This run exposed and repaired the recipe dropdown resetting to copper during
live updates. It also exposes unfinished usability: night rendering is nearly
black, nearby-material suggestions show only the closest sources, and the
completed observation goal recommends Skills before output collection.
Ordinary UI output collection was not qualified in this continuation; the
native fixture above qualifies private collection/replay/restart separately.
No first-time human timing or recognition study is claimed.

## Boundaries and next work

This is host/UI guidance and recipe-ledger processing, not chemistry,
constitutive or whole-world conservation validation. Existing glass/oak/iron
mechanical qualification boundaries are unchanged. The measured native glass
fixture has no new material law and cannot certify strength or realistic
manufacturing. `melting-glass` still requires `smelting-copper`; a saved glass
observation can finish the generic chapter without claiming that mastery.

Broader catalog supply graphs, depleted/shared/power contention, full provider
waiting and actual model-driven autonomous process selection remain open.
The reference AI action executor does not yet execute every new human guidance
verb. Night recognition, stepped/finer matched terrain comparisons, broader
R4 hauling and R5 native avatars/water/cargo remain active. The legacy tabletop
receiving trial remains unqualified; R3 repair stays owner-paused.

This checkpoint is a coherent slice of the full active owner scope, not its
completion. See [the realism review](world-realism-review.md) for the ordered
product recommendations and separate usability/physics acceptance gates.
