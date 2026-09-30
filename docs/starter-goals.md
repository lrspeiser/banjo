# Opening goals and agent playthroughs

## Checklist and actions in their own screens — September 30, 2026

Goals is now a guide and progress view. It does not bank energy, buy stock, make a source or take an item. The current step expands a short numbered checklist; later steps keep their instructions folded. Each incomplete step names its destination and offers navigation only. Completion still comes from the existing authenticated Market ledger, native build receipt and saved guest bag/hand evidence.

The human route is World → Goals → Market (bank energy and buy oak) → Recipes (Make Camp stool) → World (point at the stool and use Q for the bag or E to pick it up) → Goals. Visiting a destination never performs the action. The goal's Market route highlights oak and labels the existing bank control as 500 J; ordinary Market visits retain the 100 J control. Guided Market reads progress after transactions and offers Recipes when supplies are collected. Guided Recipes highlights Camp stool. The carry link uses the existing native-body focus/inspector route; it does not teleport the player or collect the body. A missing stool links back to Recipes for recovery.

The Goals browser regression now follows real navigation, pointer clicks on normal Market/Recipes controls, and the regular World Q binding. It checks that the initial navigation leaves balance and goal evidence unchanged, then verifies all four achievements and completion after reload. This replaces the former test of direct task buttons on Goals. Existing two-player/restart, wrong receipt/geometry, unsaved inventory and autonomous-character tests remain applicable because server predicates and storage are unchanged. Screenshots of guidance, the native bag and completion were inspected on Windows with Chrome and the existing Visual Studio Release engine, on source based on main `030de96`. No native law, timestep, resolution, persistence schema, goal reward or technique unlock changes.

Checkpoint verification: 4 opening-goal tests, 7 AI-character tests, 6 navigation/Inventory/Recipes tests and 55 Workshop browser tests pass (72 checks). The initial concurrent browser run had one cart-component removal timeout; that case passed in isolation and the complete 55-case rerun passed in 113.4 s. Its intermittent cause was not established, and no Lab control or tolerance was changed to hide it. JavaScript syntax, Python compilation, documentation links and all 286 C++ source registrations pass. The broader physics suite and a paid live model were not rerun. The published main revision is recorded by this section's Git commit and task handoff.

**Character controller follow-up:** [Autonomous characters](ai-characters.md) now exposes a bounded OpenAI controller and a separately labeled reference bot in Menu, with personal state and camera watching. The action chain here remains unchanged and still awards no new technique.

Implemented September 30, 2026. Chain `first-camp-v1` is a small, Minecraft-inspired
gather → build → carry loop in **named generated games**. It starts with the
solar economy already present in those maps. It is not a survival or mining
campaign and does not award technology knowledge.

## The first objective: make your first camp

| Goal | Required server evidence | Normal action |
| --- | --- | --- |
| Collect your first energy | At least 500 J of settled personal solar deposits | Bank from the shared array |
| Gather building supplies | Six paid oak orders, totaling 3 kg | Buy current quoted oak lots |
| Build your first camp item | Personal installed receipt with the admitted physical hash and resource debit | Preview and commit Camp stool |
| Pack for the next adventure | That builder's stool in their saved bag or hand | Inventory take |

The Goals link in the world and Goals tab in Workshop show the next incomplete
goal, progress, instructions and destination. Perform banking/buying in Market,
Make in Recipes, and carrying in the World. There is no client completion flag.
`POST /api/workshop/goals` accepts only `{}` and authenticates the guest.

The curated **Camp stool** is also in Recipes. It has a 240 × 240 mm square
top, 240 mm height, 40 mm top and straight legs, and explicit rigid mechanics.
Its five connected boxes weigh **2.5088 kg of oak**. Construction consumes
personal material first, leaving **0.4912 kg** from six bought lots, while the
shared rack remains available to other players. A fresh shelf prices the six
lots at 120, 122, 123, 125, 126 and 128 J: **744 J total**. Two 500 J deposits
cover that route. Scarcity can raise costs; bank more in Market when needed,
and its purchase control uses the latest quote. A sold-out shelf awaits the existing
trader's replenishment (one lot per 120 simulated seconds).

The starter array is shared and initially charged. Banking that charge is
metered; this goal is not proof that all deposited energy was generated since
joining. No tutorial reward creates currency, stock or physical energy.

## Evidence and persistence

`playground/starter_goals.py` derives progress from the existing Market ledger,
installed native receipts and authenticated inventory. Completed evidence is
remembered per guest and chain in `starter_goal_progress`, in that world's
Workshop SQLite database. Deposits and orders count cumulatively, so spending
energy or using wood does not erase achievements. Completion is sticky;
spending, losing or unpacking the stool does not erase demonstrated progress.

A recipe name or client-chosen ID cannot certify a build. The receipt must
identify the authenticated builder, successful resource charging, and the
exact material/geometry hash compiled from the curated recipe. Bag evidence
must also be present in the saved room's guest inventory. Reading Goals
reconciles evidence; successful install/inventory actions also reconcile it.
If this secondary write fails, the game logs it and a later Goals read retries
without misreporting the committed physical action as a failure.

Installation now saves guest profiles, bags and paired pending bank claims
with the replacement native snapshot. Failed installation refunds each
original material/goods rack owner by adding the precise debits back; it does
not overwrite a concurrent purchase. The existing room JSON and SQLite stock
writes remain separate commits, so process termination between stock debit
and room publication is still a crash-consistency gap. A durable installation
outbox is a separate next gate; this checkpoint does not claim distributed
transactions or multiple server instances owning a world.

## How an AI should propose and test the next goal

Use this authoring instruction with the current recipe contract and supported
action catalog:

> Propose one short player goal chain using only implemented actions. Name
> the initial world, player prerequisites, quantities with units, resource
> acquisition routes, supported recipe and native interaction. Each step
> needs a server-owned evidence predicate, prerequisites, a useful outcome,
> a bounded action/time budget and a recovery route. Give short numbered
> instructions for a step that needs multiple actions, and name the normal
> game screen/control where each action belongs. Goals should explain and
> navigate; it must not execute the task or award completion from a button.
> Test human journeys through those normal controls as well as bounded agent
> API actions. Visiting a goal or destination must spend nothing. Check that resources and
> tools are reachable without requiring the outcome they enable. Preserve
> the declared material, dimensions and mechanical model. Names, client
> assertions, narrative text and a plausible plan are never success evidence.
> Run the proposed route in a newly generated isolated world through the same
> APIs or browser controls a player uses. Inspect actual refusals, prices,
> material debits, native admission, inventory and saved state. Do not seed
> extra stock, edit saves, call unrestricted authoring APIs, alter physics,
> bypass payment or mark completion yourself. If a prerequisite or action is
> unsupported, report the blocked step and propose the smallest implemented
> alternative. Label suggested, implemented and demonstrated goals separately.
> Repeat with another guest and after a restart before claiming personal
> progression. Functional physics claims need their own stated experiment;
> successfully installing a recipe proves neither strength nor manufacturing.

Suggested next goals, **not implemented or certified**: make a useful work
surface; operate a solar-powered process; obtain a working gathering tool;
gather material with that tool; build shelter. The existing knowledge graph
assumes a found wooden pick in `progression/start.json`; generated named games
do not yet supply that item. Do not use that graph assumption as proof that a
mining tutorial is achievable. Sitting, hunger, night survival and shelter
protection are also not modeled by this chain.

## Run the checks

From the repository root in PowerShell, with the native binaries already built:

```powershell
$env:BANJO_LIVE_ENGINE = (Resolve-Path build/integration/Release/banjo_live_world_run.exe).Path
python tests/starter_goals_tests.py -v
python scripts/check-starter-goals.py --worlds 3
python scripts/check-source-registration.py
```

The suite covers visible browser controls and reload, two personal playthroughs,
native solar debits, paid supplies, unchanged shared stock, saved profiles and
bags immediately after build, process restart, wrong-geometry refusal for goal
credit, client completion refusal, and unsaved inventory evidence. CI requires
Chrome for the browser test. The standalone runner refuses absent engines,
creates isolated temporary maps and writes a report to
`build/starter-goals/playthrough.json`; it never modifies the user's world.

This runner is a bounded evidence-driven reference planner, **not an LLM**.
Its reusable action loop is a baseline against which an LLM playtester can be
compared. The AI developer also verified the browser flow. Neither is a claim
that arbitrary AI-invented goals have been certified.

Measured on Windows 11 / Python 3.13 / native MSVC build: three standalone
generated-map playthroughs completed in about 5–7 seconds each, using both
terrain seeds 4 and 7. Four goal tests, four world-hub tests, two native
installation failure/inventory tests, and 44 Market/Workshop unit tests passed.
The source-registration guard reported 286/286 registered sources. The report
records the Git revision and whether it includes uncommitted changes. No
solver or constitutive law changed; no new bending, fracture, seating or
manufacturing-energy validation is claimed.
