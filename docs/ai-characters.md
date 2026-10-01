# Autonomous characters and watching

**Configured paid construction, October 1:** [AI job checkpoint](fabrication-ai-build-checkpoint.md)
adds reviewed Make, personal material funding, finite native solar charging,
work and owned placement. Pending jobs and exact writes survive pause/restart;
unsupported rigid machines refuse without unpaid authoring. Default workbench
and complete paid autonomous progression remain open.

**Actual generated-world audit:** [September 30 playthrough review](ai-player-playthrough-review.md) records 4/4 camp goals and 0/9 personal techniques, then failed assistant-guided continuation and rejoin. The run used the reference controller because no provider key was configured; it is not live-model quality evidence. The report includes sanitized receipts and prioritized acceptance gates.

Implemented September 30, 2026. **Menu → Characters** in a named game starts
a guest character. **Watch through its eyes** follows that guest's camera and
shows its action results, personal bag, energy, goal progress and tech journal.
**Return to my character** keeps the viewer's existing identity and viewpoint.
The creator can pause or resume their characters from Menu. Other guests may
watch, but cannot control them.

## Character state and authority

Each character is an ordinary world guest with its own private token, native
hand, visual pose, inventory, wallet, purchased stock and opening-goal evidence.
Its creator is recorded separately from the character. The private character
token stays on the server; watching never signs the viewer in as that character.
Player profiles and action history are saved with the room JSON/native snapshot.
Market and goal evidence remain in the world's Workshop SQLite database.

Named games now keep **one tech journal per guest**, including human guests, at
`<world room folder>/players/<player id>/journal.json`. Workshop skills, chat
knowledge, Market guidance and the world notebook read the authenticated guest's
journal. Closed native ground-work evidence is attributed by tool body and the
player's recorded strike window, rather than whoever next reads the world.
Machine batches without a witnessed-player attribution rule stay in the shared
archive even if a guest's step triggered the batch; stepping is not witnessing.
Background/unattributed research stays in the legacy shared journal; old shared
knowledge is preserved there and is not copied to every new guest. Standalone
rooms keep their previous shared journal. Guest identity is browser-local, not
an account with recovery. These files have the existing single-host persistence
and installation crash-consistency boundaries described in [opening goals](starter-goals.md).

Watching reads the existing native world and follows the saved eye position and
look direction. It does not step the world, issue a grip, modify a bag or move
the viewer's avatar. The world clock and active players continue running.
Watching may reconcile goal evidence and initialize a journal, like the existing
Goals/knowledge views; it grants no resources or technology.

## Controllers and prompt contract

**AI · OpenAI** uses the server's configured key and model through the existing
strict structured decider. No provider request is made unless someone starts
or resumes that mode. **Reference bot · no model calls** is explicitly labeled
and uses a deterministic policy for reproducible tests. It is available when
the server has no configured OpenAI key.

The model receives current goal requirements, personal inventory and tech tree,
Market quotes, native targets, compatible recipes with every material gap and
recent action results. A bounded server catalog offers compare/select recipe,
select target, move, acquire/equip, inspect, use-tool, build/pack, power-on,
watch/observe, bank/buy and explicit stop actions. Unknown choices are refused
before a game action. The normal authenticated APIs enforce reach, ownership,
payment, admission and evidence; the model cannot grant progress or supplies.

Each action has a unique request id, controller mode/model, confidence where
applicable, goal chain, result and bounded receipt. History retains 128 entries;
watching exposes the latest 20. Runs stop at completed declared chains, a
blocker, action failure or 64 decisions. At most four characters count toward
the existing 32-guest cap. Resume starts another budget. Restart pauses paid
model calls. Pause discards a model choice returning after the stop request;
an already executing transaction or physical stroke can finish and is recorded.

## Measured scope and next gates

[The expanded explorer checkpoint](ai-explorer-checkpoint.md) measures autonomous
reference play through Camp and Workshop on two generated maps: 8/8 goals,
2/10 personal techniques. Selection, recipe comparison, actual tool study and
use, funded Work table, nearby saved machine batch and isolated creator state
pass. Empty Market shelves stop the bot explicitly. Substituted-model native
integration and live-provider quality remain distinct; no configured local key
means **live OpenAI play has not been verified**.

New named games declare the same native-surveyed arrival for human and AI
players. Movement uses a bounded dry-column path search and ordinary reported
avatar poses, not physical walking, swimming or body-collision navigation.
Tool approach uses declared reach. Native placement guards still decide Make;
refused actions cannot publish an item. Goal completion does not prove the
rest of the tech tree is reachable: the controller currently stops there.

Next gates: live-provider seed/scarcity comparisons; supported replenishment
of machine intakes and play beyond declared chains; obstacle-aware navigation;
several active characters plus humans under load; accounts/recovery and
multi-instance world ownership. Market relevance and compact ownership/debit
labels remain open. See the checkpoint for save/capacity defects found by the
longer journey and their strict-guard repairs.

## Verification

With the existing native Release binaries built, on Windows:

```powershell
$env:BANJO_LIVE_ENGINE = (Resolve-Path build/integration/Release/banjo_live_world_run.exe).Path
python tests/ai_player_tests.py -v
python tests/starter_goals_tests.py -v
python tests/world_hub_tests.py -v
python tests/knowledge_tests.py -v
python scripts/check-source-registration.py
```

The seven AI tests run an isolated real HTTP server and native world. A substituted
structured model chooses 10 normal actions, completes all four goals, and keeps
the resulting stool in its own persisted bag. The human's wallet, bag and goals
remain separate. Tests cover private journal routing/restart, model pause,
foreign control refusal, invalid choices, the decision budget and strike/tool
attribution and unowned machine-batch isolation. The knowledge suite's test entry
point now follows all its classes, so direct execution also runs the previously
unreached learning and machine-batch cases. The browser starts the reference bot via Menu, follows its camera,
shows goal completion, sends no live/inventory writes while observing, and
returns to the same viewer identity. Screenshot: `build/ai-player/watching.png`.
CI requires Chrome for this flow.

Measured on Windows 11 / Python 3.13 with the existing MSVC native engine from
base main `014637f30c33966052b1410e17fde1ce08f93597` plus this source checkpoint.
These checks use a substituted model and the reference bot; they **do not
qualify live OpenAI planning quality** or arbitrary tech-tree progression.
No native solver or material law changed. No new conservation, strength,
seating, fracture or manufacturing validation is claimed.
