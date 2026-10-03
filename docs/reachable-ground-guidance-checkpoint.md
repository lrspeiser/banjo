# Reachable gathering guidance — October 3, 2026

Published implementation: `19c2110` on GitHub main.

Verification base: `9636cfa` on GitHub main plus the outgoing host changes.
This is a guidance and ordinary gathering checkpoint. Native sources, material
laws and MSVC Release binaries are unchanged.

## Observed problem and change

The ordinary opening recommended a dry column near the carried pick's centre,
then told the person to step back because it was inside the tool's minimum
reach. The inventory request also left the saved guidance pose at an earlier
material collection location until the next player heartbeat.

`learning_routes.py` now prefers surveyed columns in the held/stowed tool's
declared reach, ahead of the owner's latest reported pose. It uses the same
surface candidate contract as the crosshair: dry exposed soil/sand with a
loosening motion. Soil beneath rock/clay is insufficient. The bounded search
tries two reachable rings and one approach ring, eight directions each; its
worst case is 24 read-only native surveys per tool. World tools retain their
near-tool search and ownership restrictions. A candidate is not a path proof,
guaranteed yield or skill award.

Tool preview/use and Inventory requests now refresh that owner's reported pose
after checking the open room, using the existing finite/bounded pose validator.
This is still a reported camera pose, not a native avatar collision body.

## Verification

Windows, Python 3.13; native runner/library from
`build/agent-object-strike/Release`, manufactured cells 50 mm, native dt 1/240 s.
No physics tolerance changed.

- Three new route boundary checks cover player-relative/custom reach, wet/
  buried/off-grid rejection, the 24-query cap and an honest approach fallback.
  The full knowledge suite passes 52 checks.
- Ten game-guidance and four material-candidate checks pass.
- The reference explorer still completes both opening chapters on both maps:
  33/31 decisions, 40.4125/22.0125 native seconds, 109.917/72.837 wall seconds.
  Gathering and copper-smelting knowledge stays private; actual paid process
  accounts meet their existing 1e-7 residual gates and exact saved machine
  runtime/learning outboxes remain paired. No provider calls. This is two
  chapters/two learned techniques, not the full ten-technique catalog.
- The paid personal opening now follows the actual Goals column and asserts
  that `/api/world/guidance` offers `use-tool` at that same reachable column.
  Two players on each of terrains 7 and 4 collect finite wood, fund their own
  22-cell, 1.925 kg oak pick, use it successfully, and retain private stock,
  evidence and products through full server restart. No Market order, wallet
  deposit or provider call is required. The four digs loosen 3.7618–3.76621 kg;
  their reported ground work is 6.84925–6.87024 J. This is local excavation work,
  not a closed full-pipeline energy/momentum account.
- Actual in-app browser input in the existing isolated opening world on 8773
  collects 3.7 kg sand with the paid personal pick. World reports the measured
  dig, marks Gathering by hand learned, and displays the sand thumbnail/quantity.
  Inventory retains the same sand and quantity after reload; Goals shows the
  first tool chapter complete. Zero captured browser errors. This qualifies
  ordinary use and display/reload, not a fresh human wood-to-build journey.
  Evidence is ignored under `build/opening-tools/gathered-sand.png`,
  `gathered-inventory.png` and `first-chapter-complete.png`. That browser server
  still runs the prior host process; the new guidance is qualified by the
  current-source HTTP/native tests above.

Run with `BANJO_LIVE_ENGINE`, `BANJO_LIBRARY`, `BANJO_BUILD_DIR` pointing at that
Release directory:

```powershell
python -m unittest discover -s tests -p knowledge_tests.py -v
python -m unittest discover -s tests -p game_guidance_tests.py -v
python -m unittest discover -s tests -p material_preview_tests.py -k Candidates -v
python -m unittest discover -s tests -p goal_chains_tests.py -k test_personal_tool_opening_collects_builds_uses_and_restarts_for_two_players -v
python -m unittest discover -s tests -p ai_player_tests.py -k test_reference_explorer_completes_goal_chains_on_both_generated_terrains -v
python scripts/check-source-registration.py
git diff --check
```

Total: 68 checks pass, including the two composed native scenarios above.
Python compilation and changed-document local file links pass. Registration
remains 297/297 sources, ten CMake files, zero exclusions. No new C++ source
requires compilation; these host tests run the existing native binary.

## Remaining full scope

Material work still needs exposed-layer/peer consistency and day/night
recognition/frame measurements. Opening work still needs a complete fresh
human journey, broader recipe/source/processor coverage, and model-driven/LLM
product acceptance. Shared guidance still needs those unavailable-input cases
across screens/chat. Additional R4 routes and R5 native avatar water/cargo
consequences remain active. The owner-paused R3 strike/reuse defect remains
unqualified. The [realism review](world-realism-review.md) and
[full readable-world scope](readable-world-plan.md) retain these requirements.
