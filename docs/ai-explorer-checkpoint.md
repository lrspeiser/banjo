# AI explorer checkpoint — September 30, 2026

**Latest review:** [Opening chains and actual post-checklist attempt](ai-player-current-review.md)
retains 8/8 goals and 2/10 techniques, then checks the wire mill through the same
character's normal controls. Its missing copper intake blocks the next observed
batch; other missing-equipment routes are audited separately. Zero provider calls.

Implementation published to GitHub **main** as
`c4f48e21e39d1e296d7568fe7eb8fa0169cb6756`. The persistent run below used
the outgoing working tree before its final reader-lock fix; the restart check
used the published implementation.

## Play experience and recommendations

The opening loop works: collect solar energy, buy supplies, make a stool and
put it in your own bag. The next loop gives those supplies a purpose: find and
study a tool, gather material, build a work surface and watch copper being
smelted. The character keeps its own possessions and learning; watching it does
not give the human player its techniques.

The experience currently ends too early. Finishing the checklists stops the
controller at two techniques, even though the catalog lists ten. That is a
controller boundary, not evidence that the other eight are impossible. The
next playtest should choose the next reachable technique after each checklist
and keep going until an actual missing capability or resource prevents play.

Priorities from this run:

1. **Keep progressing after the introduction.** Show the next technique, its
   prerequisites, the equipment to use and the next supported action.
2. **Make purchasing a complete plan.** Show every missing material, estimated
   total energy cost and whether the next useful capability is affordable.
3. **Make possession and progress readable.** Use product names, compact
   quantities and personal/shared labels. Keep ids and action diagnostics in
   an expandable history.
4. **Repair machine delivery and timing.** The generated rover can fail to
   reach an intake; AI page steps also slow the world clock. Neither should
   silently leave the player waiting for a supply chain.
5. **Run a live LLM comparison.** This playtest uses the reference AI policy.
   It establishes supported gameplay actions, not language-model planning
   quality or cost.

## Measured result

The reference character completes **8/8 goals across Camp and Workshop** and
earns **2/10 personal techniques**: Gathering by hand and Copper smelting.
The ten techniques are the current catalog, not the older review's nine.
Completion stops at the end of the declared goal chains; it does not establish
that the other eight techniques are achievable or that the whole game is done.

[Sanitized seed receipts](evidence/ai-explorer/reference-seeds.json) and
[Chrome watch capture](evidence/ai-explorer/watching.png) accompany this result.

Two generated maps, ordinary authenticated player APIs, no stock or outcome
grants, Windows 11 / Python 3.13.5 / MSVC Release CPU runner `f819e81`:

| Terrain / goods seed | Decisions | Wall time | Native time at completion | Removed ground | Tool work |
|---|---:|---:|---:|---:|---:|
| 7 / 851269742 | 34 | 59.724 s | 16.754167 s | 0.007445339042138977 m³ | 32.90428 J |
| 4 / 1 | 35 | 61.245 s | 17.204167 s | 0.008021469915623260 m³ | 27.62231 J |

Each builds and packs its paid Camp stool, takes and studies the actual Field
pick, uses it on native dry ground, compares compatible recipes, installs a
resource-funded Work table with 0.1536 m² top surface, approaches the actual
smelter and explicitly watches its saved batch. The batch consumes 5 kg copper
ore, produces 1.5 kg copper and draws 10,000 J. The human creator earns no
technique from the character's actions. Exact runtime and empty learning
outboxes load unchanged from the saved source checkpoint.

These automated fixtures disable the unattended world clock; the character
advances ordinary page steps under the normal shared wall-time budget.
Planning and request time are included in wall time. This is autonomous action
acceptance, **not a realtime simulation throughput measurement**. Existing
P0 realtime rover checks remain a separate acceptance gate. Native time step
is unchanged (`1/240 s`), as are 50 mm scene cells and material/ground laws.
These numbers are individual measured runs, not bitwise determinism claims.

## General controller contract

`playground/ai_actions.py` builds a bounded action catalog from current goal
requirements, personal inventory, world-resolved Skills, native target poses,
actual Market quotes and all compatible recipe gaps. Goal ids and item names
do not select a hardcoded tutorial command. A renamed tool or different
compatible box surface follows the same capability path.

Actions: bank, buy, compare/select recipes, select a target, move, take/equip,
inspect, use a held ground tool, preview/Make, pack, power on a program,
register observation, observe and stop with explicit blockers. The normal
player APIs enforce reach, ownership, payment, grid/placement admission and
physical/economic receipts. A planner's response grants no progress.

The model sees the current offered action ids, labels, arguments and recent
results. Its planning view omits renderer meshes, the complete terrain and raw
scene specification; physical admission stays on the server. Prompt instructions require current targets and quotes, recipe-gap
comparison, supported actions, personal observation and evidence-based
progress. It cannot invent stock, physical laws, outcomes or skills. Unknown
choices are refused before a game action. Reference policy and provider
integration use the same catalog, with distinct mode/model history fields.

Runs stop at complete declared chains, an action failure, an explicit blocker
or 64 decisions. History retains 128 entries; the public watch summary exposes
20. Pause discards a returning model choice; an already-started physical stroke
finishes and records its real result. Restart pauses active characters.

Movement preflights native surveyed columns, tries a direct approach then a
bounded dry-column A* search (1200 columns, 64 m maximum path). Ground-tool
approach uses the tool profile's actual reach. This is the existing reported
avatar pose model, **not physical avatar motion or body-collision navigation**.
New named-world manifests declare their generated arrival point, and both the
browser and AI use its native surveyed floor. Reload preserves existing poses;
legacy manifests retain their original camera view.

## Failures found and repaired

- **Hopper capacity:** rounded scoop mass and volume could disagree, so an exact
  transfer overfilled the hopper and prevented all later saves. Capacity now
  bounds the same native-density volumes that are withdrawn; excess is returned
  before receipt publication. The strict capacity/mass/receiving guards remain.
  An analytical regression checks 30.016 kg offered to a 30 kg hopper: exactly
  30 kg received, remainder returned, total volume residual below `1e-15 m³`,
  and exact runtime accepted on restore.
- **Save boundary:** native replies could update source receipts between the
  snapshot and disk write. `Live.checkpoint` holds both native response locks
  through snapshot, source-account capture and atomic publication. It is never
  held while waiting for a stroke. A concurrent test verifies the boundary.
- **Stale fallback:** a ground edit or inventory change could try a room-only
  save against the last physical snapshot while a stroke was underway. Live
  operations now retain the visible refusal and retry a complete checkpoint.
  No future receipt is filtered out and no invariant/tolerance is relaxed.
- **Arrival/reach assumptions:** terrain's scenic camera could be disconnected
  from the generated starting terrace; a fixed approach distance could be too
  near for the declared swing. Explicit shared arrival and actual tool reach
  replace those assumptions. Dry-route failures remain explicit blockers.

- **Windows goal readers:** the persistent playthrough exposed one transient
  `Access is denied` during atomic replacement. Goal evidence readers now use
  `RoomStore.read_record` under the writer's lock, so an open reader cannot deny
  replacement. A concurrent reader/writer regression proves serialization.

## Persistent review

[Actual fresh-world receipts](evidence/ai-explorer/persistent-review.json): terrain
4 / goods 21454332, reference controller, normal unattended clock enabled,
35 decisions in 92.408 s; 8/8 goals and 2/10 techniques, 256 J bot wallet, 0 J
creator wallet. The source was the outgoing explorer working tree on `de6b90f`,
before the final goal-reader serialization fix; this run exposed that final
Windows sharing defect. No provider calls, inventory or outcome grants.

[Watch the character](http://127.0.0.1:8769/world?world=a49789cfd53d4f998ea38dea43ef6c6f&watch=569e64a5cb8e46a281c4b946bfc7bd5a).
This link requires the local review server. Native time reached 55.4125 s during
that wall interval: the current AI page-step cadence suppresses some unattended
clock time. Do not describe this as realtime autonomous throughput. Unifying
AI/page/background step ownership is a remaining timing gate.

[Server restart check](evidence/ai-explorer/restart-check.json) with the published
code restores the native world at 485.1375 s using the engine's `whole` tier.
The character retains its completed status, 35 decisions, two techniques,
256 J, held Field pick and packed stool. The ground-transfer ledger is
unchanged. The unattended clock saved again between baseline capture and
shutdown, so this check does not assert equality to that earlier native
snapshot. The engine's reported restore limitations remain in the receipt.

## Verification and remaining gates

`tests/ai_player_tests.py` is now registered as `banjo_ai_player_tests` in CTest
with a 900 s limit and the actual native runner. The full native/Chrome suite
passed 17 tests with zero skips in 427.38 s; after final provider-view and reader
changes, five controller-boundary checks, eight receiving/save checks, the
substituted-model native journey (64.432 s) and goal-chain CTest (42.94 s) pass.
The full-suite separate realtime rover case measured 134.196 native s / 136.105
wall s, two receiving receipts and 3700 J settled wallet, with failed-save,
duplicate, reload and restart gates intact. Source registration is 286/286;
Python compile, JavaScript syntax, diff whitespace and relative doc links pass.

Reference play across both
seeds, separate substituted-model integration, unsupported choices, pause,
personal journals, restart, realtime rover receiving/banking and Chrome watch
flows are distinct checks. Empty-shelf fixtures on both seeds remove trader
oak only: the character banks once then stops with the actual shortage; it
earns no skill or further goal. They are explicit scarcity fixtures, not
ordinary player purchases or a test of restocking policy.

**Live provider: not verified.** No OpenAI key is configured locally. A
substituted structured model tests the real game integration but is not evidence
of live-model planning quality, latency, token cost or seed/scarcity robustness.

Follow-up: [complete Market guidance](market-guidance.md) is now implemented
and verified in `d7571fb` on main. It supplies all gaps, stock budgets, goal
matching and folded personal/shared debit details. The playthrough measurements
above remain results from the earlier explorer checkpoint.

Follow-up: [product/resource labels](product-labels.md) now provide recorded
names, pictures, quantities, debit sources and implemented next uses across
Inventory/Recipes/World. Native multi-guest staging/restart and Chrome pass;
the original persistent-run measurements above remain unchanged.

Remaining work: live-provider comparisons; continued play beyond the declared
chains; replenishing exhausted machine intakes through supported player actions;
obstacle-aware physical navigation; generated rover delivery
failures. No full-world conservation, material strength or physical chemistry
claim is added. Prior glass/oak/iron comparative gates remain unchanged.
