# Opening progression and independent glass learning

October 3, 2026. Implementation against main base `ebc2726`, Windows 11,
Python 3.13 and retained MSVC Release native binaries in
`build/agent-native-water/Release`. This checkpoint changes the progression
catalog and its regressions. Native laws, material properties, geometry,
manufacturing quotes, physics timestep and tolerances are unchanged.

## Implemented behavior

- The personal-tool chapter still requires finite wood, paid manufacture and
  actual successful use of the player's own admitted whole tool.
- The next chapter has two goals: Build a work surface, then Learn from a
  working machine. Study and Gather are removed from that chapter because the
  opening already demonstrates gathering. Optional inspection and the journal
  remain available; no new skill or item is granted by reading Goals.
- Glass melting technique revision 2 has no copper-smelting prerequisite.
  Its existing positive saved glass experiment remains required. Watching a
  copper process still does not teach glass. Wire and iron dependencies remain.
- Older chapter receipts stay in SQL, including retired Study/Gather records.
  Existing completed surface/batch receipts still count. Older glass evidence
  can earn glass on journal reconciliation once, without inventing copper
  knowledge. Private peer state and full restart remain separate.
- Built-in chapters, shared guidance, Skills and AI actions consume the same
  catalog. The Camp light remains the existing optional useful follow-up,
  with its paid oak/glass/copper/energy supply contract.
- Browsing a chapter before its prerequisite is complete shows Later chapter
  and does not label a second action Next step. The shared sidebar retains the
  active opening action; chapter links remain available for inspection.

## Verification

Tests run with BANJO_DECIDER=reflex and no live provider calls:

- Knowledge library: 53 checks pass, including independent glass earning,
  recovery of older evidence, exact reopening and no duplicate/peer award.
- Goal predicates and player boundaries: five checks pass in 29.901 s. This
  includes preserved retired/partial SQL records and full restart, plus paid
  wood/tool/native-use openings for two owners on each of two terrain seeds.
- Shared guidance: 11 checks pass in 20.422 s, including exact paid readiness,
  all seven chat screens, private projects and pending work.
- Registered native process guidance: three cases pass in 82.30 s, including
  actual stored sand to glass, native heat/work, owner skill, private output,
  paid Camp light manufacture/use and whole server restart without purchases.
- Reference AI: one two-terrain journey passes in 188.741 s. Seed 7 / goods
  851269742 completes in 112.939 s with 32 decisions; seed 4 / goods 1 in
  73.815 s with 30 decisions. Both earn gathering and copper processing,
  preserve private paid tool/table jobs and pass exact runtime/journal reopening
  accounts. Inspection is optional; the required actions retain paid building,
  collection, native tool use and actual watched batches. No live model ran.
- In-app browser on isolated port 8776 creates a normal fresh world, opens
  Goals and browses the shorter two-step second chapter. Later chapter wording
  agrees with the active Get wood sidebar action; both chapters remain 0
  complete. Screenshot is local `build/progression-branch-preview/goals.png`.
- Total: 73 automated checks pass. Source registration passes 298/298,
  ten CMake files, zero exclusions. Viewer syntax and whitespace checks pass.

[Compact results](evidence/opening-progression-simplification.json) record the
base revision, declared environment and real two-seed reference results.

Exact commands use `python -m unittest discover -s tests -p knowledge_tests.py
-v`, the equivalent discovery for `game_guidance_tests.py`,
`python tests/goal_chains_tests.py Predicates
PlayerJourney.test_retired_opening_checks_preserve_older_partial_progress_and_restart
PlayerJourney.test_personal_tool_opening_collects_builds_uses_and_restarts_for_two_players
-v`, and `ctest --test-dir build/agent-native-water -C Release -R
'^banjo_process_guidance_tests$' --output-on-failure`.
The AI command is `python tests/ai_player_tests.py
AutonomousGuests.test_reference_explorer_completes_goal_chains_on_both_generated_terrains
-v`. BANJO_LIVE_ENGINE, BANJO_LIBRARY and BANJO_BUILD_DIR point to the retained
Release directory above; BANJO_DECIDER=reflex and OPENAI_API_KEY is empty.

An initial direct invocation of `game_guidance_tests.py` ran no tests; the
reported eleven are from the corrected unittest discovery command. Initial
preview argument quoting introduced spaces in native paths; only that owned
failed preview was stopped and restarted with corrected paths. Ordinary world
creation and browser verification then pass. Existing 8771/8774/8775 servers
and native binaries were not replaced.

## Boundaries and next work

This removes two repeated tutorial checks and an unrelated knowledge gate;
it does not complete the larger supply audit or a first-time usability study.
The work surface still precedes processing in this chapter. Its retained
legacy tabletop receiving journey remains unqualified and is not counted as
passing here. Its native placement assertions are preserved. The legacy
browser-driver test is updated for the two goal links, but is not executed or
claimed as passing; browser verification uses the in-app browser.

Terrain recognition at night and stepped/finer terrain comparisons remain
open. Further human/model progression, depleted shared supplies, broader
hauling, native human/AI body contact and water response, physical cargo
mass/inertia/receiving and full conservation remain open. R3 repair stays
owner-paused. The complete four-part active objective is unchanged.
