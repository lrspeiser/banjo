# Personal goal chains

## Implemented contract

The Goals screen now has two checklists: **Make your first camp** and **Put your camp to work**. Links take the player to Market, Recipes, Skills or World. No checklist control performs a physical action or supplies completion evidence.

The second checklist records tool study, positive measured ground removal plus Gathering by hand, a funded native work surface, and a personally witnessed supported machine batch. Completion is retained per player and chain in the existing SQLite goal ledger. Source receipts come from the durable personal journal or from the saved room containing the installation receipt, exact geometry and native snapshot. Another player's receipts, another world's results, unsupported notes and watch registration alone do not qualify.

[The bounded catalog](../progression/goals.json) composes server implemented predicates. Definitions reject unknown operations, measurements and techniques, missing/cyclic prerequisites and duplicate steps. `after` orders chapters and reports whether the prior checklist is complete; it does not forbid playing or earning receipts out of order. `chain: active` selects the next incomplete checklist. The empty request retains the existing Camp API.

| Predicate | Required source | Boundary |
|---|---|---|
| `personal-test` | This world's acting guest's saved `study-example` or `loosens-soil` journal result | Optional positive removed volume and known technique; inspection alone is not functional success |
| `funded-box-surface` | This guest's resource-charged, native-verified precise rigid installation in the saved room | An upright body with a receiving point on an actual unrotated box top; declared receiving area must fit the face and meet the configured area |
| `personal-batch` | This world's saved supported machine batch with the guest's observer attribution | Positive output and a curated implemented batch test; recipe-ledger evidence is not simulated chemistry |

The surface predicate currently excludes lattice, curved and tipped surfaces. It checks geometry and admission, not structural strength. A client name, design id or oversized surface annotation cannot substitute for a physical face. Once credited, later packing or dismantling does not erase the demonstrated build.

**Work table** is an ordinary editable oak bench recipe with a 0.48 × 0.32 m top. It uses the existing material debit, exact rigid compiler, clearance and state-preservation gates. Make installs it in World. Its next supported use is Place; it does not manufacture parts or unlock unsupported wood shaping. Shared supplies can fund a build after personal supplies are used.

## Instructions for authoring future checklists

Use these instructions when an LLM proposes a new chain for review:

> Compose only the predicates admitted by `goal_chains.definitions`. Give each step a short title, one receipt target, a normal game destination and concise player instructions. Refer to implemented measured actions and actual world equipment. Use Skills' world resolver for tool/machine locations and missing prerequisites. Never supply completion, stock, energy, test results or new physical laws. A work surface must qualify from native geometry, not its label. An unavailable action needs an implemented evaluator and native player-route test before it can become a goal. Test a proposed chain with normal authenticated player actions on generated seeds and shortages. Report reference-policy, scripted-player and live-provider results separately.

There is no client/LLM endpoint for installing arbitrary goal definitions in this checkpoint. Catalog changes remain reviewed repository changes. The future AI action catalog must consume these checklists and world state; the existing autonomous Camp controller still stops after Camp.

## Verification

Tests run on Windows 11 / Python 3.13.5 / MSVC Release CPU runner built from `f819e81`, with 50 mm world cells and unchanged native `dt = 1/240 s`. Test fixtures advance the normal world clock faster than wall time while waiting for physical actions. They pin map selection only and use ordinary authenticated Market, build, inventory, study, tool, placement and watch APIs. They do not grant inventory, alter outcomes or invoke a provider.

The new CTest target and CI command run `tests/goal_chains_tests.py`: two complete generated-world journeys, personal isolation/restart, rejection of unsupported declarations and false surface annotations, and a Chrome chapter/guide/recipe navigation check. The first seed uses the advertised Work table; the second changes its id and dimensions to verify general geometry qualification. Both place the carried Camp stool on the admitted surface through the native placement resolver and normal Put down control.

Final source revision and measured receipts are recorded with the [acceptance evidence](evidence/goal-chains/acceptance.json). Browser output is [the checklist](evidence/goal-chains/checklist.png). The existing opening-goals suite, Workshop tabs suite, source registration guard, Python compilation, JavaScript syntax and changed-file checks are also retained.

No material law, tolerance or solver changed. This checkpoint adds no new full-world conservation, chemistry, strength or cross-GPU claim; earlier glass/oak/iron comparative physics remains bounded by its existing evidence.

## Remaining gates

- Broader autonomous selection, walking, tool use, recipe comparison and batch observation; live-provider play is still unverified.
- Exhausted bootstrap intakes need a playable replenishment route. The fresh-world runs qualify available inputs, not indefinite or late-join progression.
- Avatar poses remain client reports; these tests do not prove collision-aware navigation or physical line of sight.
- Rover navigation/delivery failures, complete Market gap/cost ranking and compact product/debit labels remain open.
