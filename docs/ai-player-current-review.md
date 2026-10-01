# AI player review — September 30, 2026

## Result

The character completed **8/8 Camp and Workshop goals** and learned **2/10
techniques: Gathering by hand and Smelting copper**. It has its own Field pick,
packed Camp stool and 256 J. The introduction now connects building to actual
personal learning. Further progression is still interrupted by equipment and
material-delivery gaps.

[Watch the character in its world](http://127.0.0.1:8769/world?world=a49789cfd53d4f998ea38dea43ef6c6f&watch=569e64a5cb8e46a281c4b946bfc7bd5a).
The local review server must be running. The reference controller is complete;
I subsequently moved this same character to inspect the wire-making route.

Review and native power-command correction are published to GitHub **main** as
`8b551165cfe2d84e72d07eafed728970ceac2d70`. Final Chrome verification reopened
the saved character on that backend with the watched-hand name display follow-up.
It retains 35 decisions, both techniques and its named stool, with no runtime
exception. [Watch capture](evidence/ai-explorer/watching-current.png) and
[verification receipt](evidence/ai-explorer/published-check.json) record that
boundary. The watched hand now displays its inventory label even though the
viewer has no local held object.

## How I played

I created a separate generated world and player, with the normal unattended
clock enabled and no free supplies, equipment or outcome grants. The app's
**reference controller** made 35 decisions in 92.408 s. No provider key is
configured locally, so **zero live LLM calls** were made. Reference policy,
assistant-guided continuation and live-model planning are different evidence.

The character banked solar energy, bought oak, made and packed its stool,
acquired and studied the actual Field pick, gathered native dry ground,
compared recipes, funded a useful Work table and personally watched smelting.
Native receipts, stock debits and its private journal determine success.
The [original explorer receipt and restart check](ai-explorer-checkpoint.md)
retain their exact source revisions and restore limitations.

I also reran the reference journey on two fresh generated maps after the
[product guidance changes](product-labels.md), published as `ef89a07` on main:

| Terrain seed | Goals | Techniques | Decisions | Wall time |
|---|---:|---:|---:|---:|
| 7 | 8/8 | 2/10 | 34 | 60.086 s |
| 4 | 8/8 | 2/10 | 35 | 62.370 s |

These fixtures disable the unattended clock and step through ordinary player
APIs under the shared wall-time budget. They are action acceptance checks,
not realtime throughput measurements or proof of the whole tech tree.

## Attempt to continue

After restarting the review server on published `ef89a07`, I used the same
character's ordinary player APIs to approach the actual mill, turn it on and
explicitly watch it. The server accepted the power command and observation.
After **11.560 s wall time**, including approach and observation, the character
still knew the same two techniques. The observed interval advanced native time
from **2265.445833 to 2270.445833 s**. Its **mill intake lacks copper**.

[Sanitized continuation receipt](evidence/ai-explorer/continuation-review.json)
records the actual target, watch acknowledgement, missing inputs, personal
possessions and unchanged journal. I found no implemented ordinary action that
transfers purchased/carried stock into that machine intake. Buying copper into
Workshop stock alone would not establish a fed machine or a wire-drawing batch.
I did not edit the stockpile or grant the technique to continue.

The reference controller stops when its declared goal chains are complete.
That alone cannot establish a gameplay blocker. The following separate Skills
audit resolves all remaining routes against this particular world:

| Technique | Current obstacle |
|---|---|
| Drawing wire | Mill exists; intake needs copper |
| Rough-shaping wood | Required One-piece wooden pick example is absent |
| Burning lime | Lime kiln absent |
| Firing ceramic | Clay kiln absent |
| Melting glass | Glass furnace absent |
| Mixing concrete | Concrete mixer absent; Burning lime prerequisite |
| Smelting iron | Iron smelter absent |
| Smelting aluminium | Aluminium cell absent; Drawing wire prerequisite |

Missing-equipment routes were audited, not manufactured or mechanically tested.
The current Recipes catalog offers 17 named templates, including a processor
and electric furnace; a generic template name does not establish the exact
recipe, inputs and observation evidence those techniques require. This review
does not prove that every possible authored route is impossible.

## What feels good

- Solar → purchases → a visible product gives the player an understandable start.
- Tool study and measured gathering make learning feel connected to actions.
- Watching a real batch earns personal knowledge; another player gets no free
  progress from being in the world.
- Names, source pictures, readable masses and Personal/Shared quantities make
  possession easier to understand. Native ids and exact mass stay in Details.
- Two guests' packed products survive another build and restart unchanged.

## What needs to improve next

1. **Make wire the next playable loop.** Let the player obtain copper, deliver
   an explicit quantity to the mill intake, start it and observe a saved batch.
   Expose the debit, receiving receipt and remaining input on the machine panel.
2. **Keep the AI playing after checklists.** Select the next supported reachable
   technique, equipment or construction task from the current catalog. Stop
   with a specific missing action/resource, not merely “all goals complete.”
3. **Connect missing equipment to real build plans.** Skills should offer the
   actual recipe, required supplies and supported use, or clearly mark the
   route unavailable. A declaration or purpose string cannot grant capability.
4. **Fix machine delivery and clock ownership.** The generated rover still has
   unqualified delivery routes. AI page requests suppress some background
   advancement; the continuation's 5 native s in its observation interval is
   further evidence that wall time and sim time are not aligned during play.
5. **Qualify a live LLM separately.** Repeat seeds and shortages with provider
   calls, recording decisions, refusals, latency and token cost. Fake/reference
   integration success is not a live-model result.

The continuation also exposed a real AI power-command bug: the controller
passed a machine name where the native interface requires a numeric program id.
The correction resolves the
current native program immediately before acting and uses a request-specific
sender with integer count 1 instead of an epoch-based count. A native powered-off-machine test verifies on, saved power,
no skill award and refusal of a missing target; five controller-boundary checks
also pass. The continuation above used the correct ordinary command explicitly,
before that controller correction was published.

Windows 11, Python 3.13.5, MSVC Release CPU runner `f819e81`, 50 mm cells,
`1/240 s` step. No solver or material law changed. Reported avatar paths are not
physical collision navigation; machine goods receipts are not chemistry,
strength or full-world conservation certification. Existing glass/oak/iron
comparative evidence remains unchanged.
