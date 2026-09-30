# Autonomous characters and watching

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

The model receives this character's current goal evidence, inventory, tech tree,
wallet, current oak quote/stock and recent actions. The server offers only
applicable actions: bank measured energy, buy one quoted oak lot, preview/commit
the curated Camp stool, put that stool in the character's bag, or stop for a
blocker. Prompt instructions require the model to use current evidence, never
claim completion, teach itself, alter physics or invent stock. An unsupported
choice is refused before a game action. The normal authenticated HTTP game APIs
enforce payment, admission, resource debit and carrying; the model's assertion
is never a completion predicate.

Each selected action has a unique decision/request id, controller mode, model
and confidence where applicable, duration, goal, result and bounded receipt.
The saved history retains 64 entries; watching exposes the latest 12. Provider
failures stop with an error rather than granting progress. This is a bounded
game controller, not arbitrary model-generated executable code.

Runs stop when the four opening goals finish, the planner reports a blocker,
an action fails, or **24 decisions** are reached. At most four characters belong
to a world and they count toward its existing 32-guest cap. Resume starts a new
decision budget. Restart pauses active characters; it never silently restarts
paid model calls. Pause discards a model choice that returns after the stop
request; an already executing game transaction may finish and is recorded.

## Measured scope and next gates

The implemented action catalog covers [first camp](starter-goals.md), not an
open-ended survival agent. Its short scripted camp route queries native terrain
and reports positions using the same visual avatar model as people. It is not
collision-aware navigation, a physical walking body, swimming or an exploration
planner. Placement can be blocked by another player or character. It reports
that refusal instead of bypassing occupied geometry. The opening loop does not
earn a new technique; the independent journal is a foundation for later goals
with real learning evidence. The found-pick graph assumption still does not
provide a mining tool in generated games.

Next gates: supply a real gathering tool; add an evidence-backed learning goal
and a machine-batch witness rule;
offer terrain/obstacle-aware movement and alternate camp locations; compare
actual provider playthroughs across seeds and scarcity states; measure several
active characters and humans together; add accounts/recovery, a character
retirement policy and multi-instance world ownership.

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
