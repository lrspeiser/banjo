# Visual screen consolidation — October 5, 2026

## Review and implemented changes

The old seven destinations separated possessions from purchases, browsing from editing, and objectives from the skills needed to perform them. Energy meters and navigation were repeated, empty storage sections occupied space, and the goal list gave future steps the same weight as the current task.

| Destination | What belongs here | Main action |
| --- | --- | --- |
| World | Explore, gather, place, operate machines | Use the selected item or target |
| Inventory | Hands/bag products, material thumbnails, energy and rates, supplies to buy | Equip/place/edit an item, collect energy, or buy missing supplies |
| Build | Recipes, saved designs, reusable blocks and the selected item's Lab | Select → customize/check → save or build |
| Progress | Current goal, chapter milestones, skills and unlocks | Follow the highlighted step to its actual game location |

These are combined work areas, not six renamed sub-tabs. Inventory displays purchases beside possessions. Build keeps the recipe catalog available beside the editor; the Lab stays empty until an item, recipe or design is explicitly selected. Progress keeps the goal and skill sections together. Existing `lab`, `recipes`, `market`, `skills`, and `goals` links still reach the corresponding hub, including material filters and selected designs/workpieces.

### Removed from the primary flow

- Three redundant main navigation destinations and duplicate Inventory-to-Market/Recipes buttons.
- A second wallet/next-action display, duplicate draft Save/Build buttons and the always-visible shared machine meter card.
- Empty carried-ground, stored-ground and processed-goods sections. Store/Retrieve, unassigned-load recovery and pending transfers remain visible when relevant.
- The all-chapters button wall, expanded future goal list and repeated goal-title/progression paragraphs.
- An always-open chat rail. Chat opens with `/`, the navigation button, or **Customize with AI** beside the selected item. Component thumbnails, draft status and the reviewed build stay with the Lab, outside chat.

Purchase history, pricing/debit detail, array/machine meters, complete goal checklists and design diagnostics are disclosures. These are useful inspection/recovery capabilities, rather than extra tasks for every player. Server-side admission, paid resource accounting and bounded LLM authoring remain in force.

## The guided path

The existing authenticated next-action decision appears once above every hub, with its destination and blocker. It does not manufacture progress or charge energy. Goal cards explain the current task and navigate to World, Inventory or Build; real actions still earn completion. Numbered milestones and completion colors summarize the chapter. The existing skill tree retains prerequisites, ready/learned states and actual equipment links, with visual skill icons.

LLM customization is an explicit action on the selected Lab item. Game questions remain available everywhere. Moving the guidance card does not add periodic model calls: ordinary refreshes read state/status, while advice remains explicit or tied to the existing bounded construction events.

Initialization respects a player's navigation request, including while a saved design loads. Purchases become interactive after the Inventory snapshot, energy summary and offers settle, so a late meter response cannot move the Buy button during a click. The shell exposes a ready marker for browser journeys, preventing tests from interacting with a partially initialized screen.

## Verification

Environment: Windows, Python 3.13, Node 22, installed Chrome; native executables from `build/pickaxe-preview/Release`. Base revision: `bfcc9f36`. This checkpoint changes host presentation and tests, with no native binaries or physics laws changed.

- `tests/workshop_navigation_tests.py`: all 17 journeys pass in 129.158 seconds, including two new consolidation regressions. Covers in-place purchase/wallet/private-stock updates and peer isolation; all four destinations; empty/explicit Lab selection; material filtering; saved drafts through World, Progress and reload; ordinary Make and refusals; solar ownership; meters without stepping/spending; skill/equipment links.
- Responsive regression runs the three hubs at 1440×900, 844×390 and 390×844, checks navigation/content width, a reachable next action and nonoverlapping goal/skill sections.
- Four affected `workshop_browser_tests.py` layout/input/tree journeys pass. Chat-based bench tests now explicitly open the optional chat panel.
- `LabRemake.test_mixed_pick_chat_edit_save_paid_make_pickup_dig_and_restart` passes with an actual pointer-driven chat edit, saved design, paid build, pickup, use and restart.
- `node tests/player_guidance_ui.mjs` passes stable refresh, stale-response, transient-state, dismissal and quiet-mode checks. Changed JavaScript syntax, diff checks and the source-registration guard pass (300/300 sources).

The carried-stool ownership fixture now declares seed 0 for its fixed installation site; it does not claim arbitrary-terrain placement. Native placement tolerances and ownership assertions are retained. The stock-race journey now asserts the combined Build destination while retaining the selected Lab geometry and verifying no spending after refusal.

Evidence is under ignored `build/construction-preview/screen-hubs-*.log` and browser screenshots, including phone layouts. No player records, tokens or keys are committed.

## Remaining acceptance

Have unfamiliar players complete the opening using this layout: recognize the next action, acquire supplies, select/edit a design, finish a paid build, place/use the product and recognize its skill unlock. Record time and wrong turns before claiming Minecraft/Civilization-level ease. Physical phone/touch gameplay, broader supply/recipe gaps, native cargo/actor qualification and the retained physics roadmap remain separate work.
