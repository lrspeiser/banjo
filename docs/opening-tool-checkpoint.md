# Useful first tool — October 3, 2026

## Implemented checkpoint

New players now start with **collect wood → make a personal field pick →
gather with it**. Each step sends them to its ordinary game screen. Navigation
and checklist buttons award nothing. The previous solar banking, mandatory
six Market lots and stool sequence is retained as an optional earlier chapter;
players who already completed it can continue to the existing workshop chain.

The default pick uses the existing oak field-pick geometry: 800 mm haft,
300 mm arm and 50 mm section. At the default 50 mm installation grid the
actual paid build admits 22 occupied cells, consumes **1.925 kg oak** and
requires **192.5 J** of authored shaping work. It declares gathering dry soil
or sand and studying construction. The recipe card now shows these uses.
It is not a hard-rock mining tool or a calibrated strength/wear certificate.

Supply guidance locates a real loose wood pile and shows its available mass.
Collected stock belongs to the collecting player. Existing stock and optional
Market purchases also work. Building uses the existing funded workbench and
native battery energy; currency banking is no longer an opening requirement.
An exhausted loose source falls back to existing stock or Market, and exhausted
Market shelves produce a wait/blocker. No checklist or AI action creates wood.

Completion checks authenticated stock, saved paid native build admission,
the actual installed ground-tool profile and positive ordinary-use evidence
with the builder's own tool. A name, recipe annotation, another player's tool
or receipt, zero-yield contact and a failed whole-tool check cannot qualify.
Consumed supplies and completed achievements stay recorded across restart.

The reference AI and model action catalog can approach and collect actual
piles. They resolve goal tools independently of whether their associated skill
is already known. This avoids rebuilding a tool simply because the earlier
use already earned Gathering by hand. Machine observation now uses twenty
half-second intervals plus API time, checking pause throughout and returning
early when the active goal changes. It still uses ordinary native steps;
machine temperatures and successful outcomes are not supplied by the planner.

## Verification

Windows, Python 3.13, Node 22.18.0 and existing MSVC Release native binaries in
`build/agent-object-strike/Release`. Source base `fd733c6`; the implementation
revision is recorded in Git history and the publication note below this file's
linked status entries. Native source, material laws and solver tolerances are
unchanged.

Set `BANJO_LIVE_ENGINE`, `BANJO_LIBRARY` and `BANJO_BUILD_DIR` to that Release
directory before Python HTTP/native tests. Focused commands:

```powershell
python -m unittest discover -s tests -p goal_chains_tests.py -k Predicates -v
python -m unittest discover -s tests -p goal_chains_tests.py -k test_personal_tool_opening -v
python -m unittest discover -s tests -p goal_chains_tests.py -k test_empty_loose_wood -v
python -m unittest discover -s tests -p ai_player_tests.py -k ControllerBoundaries -v
python -m unittest discover -s tests -p ai_player_tests.py -k test_skill_and_market_guidance -v
python -m unittest discover -s tests -p ai_player_tests.py -k test_reference_explorer_completes -v
python -m unittest discover -s tests -p ai_player_tests.py -k test_reference_explorer_reports_empty -v
python -m unittest discover -s tests -p ai_player_tests.py -k test_model_selected_actions_complete_real_goals -v
python -m unittest discover -s tests -p starter_goals_tests.py -k test_two_players_complete -v
python -m unittest discover -s tests -p starter_goals_tests.py -k test_wrong_geometry -v
python -m unittest discover -s tests -p starter_goals_tests.py -k test_unsaved_inventory -v
python -m unittest discover -s tests -p product_labels_tests.py -v
python -m unittest discover -s tests -p workshop_tabs_tests.py -k TheTabs -v
node --experimental-default-type=module --check playground/workshop.js
python scripts/check-source-registration.py
git diff --check
```

### Measured outcomes

- Two authenticated players on each of terrain seeds 7 and 4 collect 25 kg
  from the actual finite loose pile, build, take up and use separate paid tools,
  then stow them. The source loses 50 kg total; each private stock retains
  23.075 kg after manufacture. There are zero Market orders or wallet deposits.
  Full server restart retains both products, personal progress and evidence.
- At 1/240 s and 50 mm cells, the four ordinary-use results remove
  0.0023513–0.0023521 m³ dry soil, reporting 3.76214–3.76342 kg and
  6.84962–6.85094 J native work. These are existing digging measurements,
  not a new deformation law or full pipeline conservation claim.
- Exhausted loose wood and Market fixtures remain blocked without awards.
  Negative predicate cases and nine controller boundary cases pass.
- The reference explorer completes the new opening plus the existing
  study/gather/worktable/working-machine chain on both generated terrains:

  | Terrain / goods seed | Decisions | Wall time | Native elapsed | Earned techniques |
  | --- | ---: | ---: | ---: | --- |
  | 7 / 851269742 | 33 | 110.455 s | 40.4625 s | Gathering by hand, Smelting copper |
  | 4 / 1 | 31 | 71.813 s | 22.0625 s | Gathering by hand, Smelting copper |

  Both runs use two paid jobs (tool and worktable), collected personal oak and
  actual solar-generated battery energy, with no shared rack debit. Existing
  fabrication material/energy residual checks remain below 1e-7 kg/J in their
  documented station boundary. This is not whole-world conservation.
- The earlier two-player stool chapter still passes through earned energy and
  restart. Wrong geometry/foreign receipts and unsaved bag progress remain
  refused. Six product-label and six tab contract checks pass.
- The mocked-model action-selection journey passes in 76.996 seconds, retains
  the made tool in its own hands/bag and keeps its private tech tree through
  full server restart. It tests the model execution boundary, not live model
  reasoning. Across the focused commands above, 33 test cases pass; source
  registration remains 297/297 with zero exclusions.

The explorer test's wall deadline changes from 120 to 300 seconds because
ordinary machine heating can continue after the previous deadline. Native
time, work and thermal predicates are unchanged. Earlier probes exposed a
tool-location/planner loop and excessive decisions during unchanged heating;
the fixes above address those causes. The completed reference run took
184.195 seconds for both terrain cases combined. No actual LLM provider call
is implied by a deterministic reference or mocked-provider test.

Browser verification on an isolated preview at port 8773 shows the three-step
opening, the actual wood-pile link, highlighted personal pick recipe, declared
Gather/Study uses and Lab funding review at 1.93 kg oak / 192.5 J. There are
zero captured JavaScript errors. The existing legacy-browser and Market-browser
harness assertions were updated for the new default chapter; those harnesses
were not executed in this checkpoint. Actual UI verification used the in-app
browser. Evidence is ignored under
`build/opening-tools/`; it is not a shipped
asset. Restarting the preview while already in Lab requires opening World
before making again; direct post-restart Lab reopening remains a usability gap.

## Remaining scope

This proves the finite opening supply/build/use/restart path, not the entire
tech tree or smooth human play. Native headless player tests report actual
ground heights at declared poses; they do not qualify physical avatar walking.
Wood collection is currently loose-pile collection, not chopping trees.

The [readable-world plan](readable-world-plan.md#remaining-acceptance-for-the-full-owner-scope)
remains active: complete gathering/layer/thumbnail/reload presentation acceptance,
unify readiness and next-action guidance across every screen and chat, and
finish reliable hauling, physical avatar water response and cargo consequences.
World still offers a later skill suggestion while Goals recommends the opening
tool; private stock and shared workbench stock also need clearer common guidance.
R1's broader supply coverage and R6's human/model-driven progression remain open.
R3's paused repair scope is unchanged.
