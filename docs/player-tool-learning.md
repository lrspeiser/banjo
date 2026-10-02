# Personal tool learning — September 30, 2026

Source `2ee3ab7` builds on [starter-tool access](generated-starter-tool.md) and [personal machine witnessing](player-learning-checkpoint.md). The broader player progression goal remains active.

**October 1 update:** [Live progress and achievement checkpoint](live-tool-skills-checkpoint.md) supersedes the separate Study prerequisite below. Historical September 30 results remain recorded. Ordinary successful saved digging now earns gathering directly.

## Player contract (current)

Take or equip a ground tool, aim at nearby dry soil/sand and use its swing/lever controls. **Gathering by hand** requires a passing saved native ground-use receipt. **Study tool** (or Inspect) remains optional: inspection records the held example without certifying its function. Merely navigating Skills, taking an item, watching from elsewhere or being the guest who advances the clock awards nothing.

The graph adds a versioned `field-pick@1` construction and the `using-ground-tools` technique. It retains the earlier 40 mm wooden-pick definition and accepts a demonstrated example of that design too. Geometry/material/point properties select a curated construction, not its display name. Other supported authored tools retain evidence under their own construction key; they are not silently promoted to the Field pick. The technique names no manufacturing process and does not enable unsupported wood shaping or change a material law. Workshop authoring remains ungated.

Study reads an actual whole native snapshot of the tool in the authenticated guest's hand. Its attached point must share that body's identity, nodes and offsets, and all authored sampled matter must remain present. The scene's occupancy calculation covers joins, rotations, shapes and subtraction; it does not assume every authored shape fills its bounding box. Study retains a digest of that native matter/point frame. This is example inspection, not strength, manufacturing or fracture certification.

Ground learning uses only closed supported native reports attributable to that guest's actual strike and tool, with the historical construction that was used. Raw source volumes are preserved without the former extra six-decimal rounding; other values retain the precision supplied by the native API. Displayed mass/work may already have native presentation rounding. No chat or player payload can submit a successful learning result.

## Save ordering

`player_evidence_pending` is a bounded outbox (1,024 receipts / 2 MB) saved beside the exact physical world and guest records. Each receipt retains its actor, world/session, native time, source and deterministically evaluated evidence. A later matching physical snapshot is required. The room store captures the durable receipt IDs from the exact serialized list; a receipt arriving during another save cannot be mistaken for a saved receipt.

Only then is the personal journal updated and the graph evaluated. Source-save failure leaves the older durable world and awards no new knowledge. Journal failure leaves the outbox for retry/restart. Event-derived IDs and the journal's existing atomic rollback/idempotence guard prevent duplicate evidence or technique awards. Tool-use replies visibly say **Journal update pending** when saving has not completed. This is bounded local persistence, not a distributed transaction or cryptographic proof against someone rewriting server files.

Installation/fabrication preserve the outbox; saves with pending physical history require whole restoration. Old saves without this optional field remain readable. Unsupported-ground notes still use the older diagnostic path and are not technique rewards.

## World-aware guidance

Skills and Market resolve actual available tools, ownership, bag locations and nearby native ground surveys. Another guest's carried tool is not offered as yours. A bagged tool links to Inventory; a world tool links to its selected World object. Each route displays its conditions, with one destination link per object. World shows the current tool’s saved condition counts and completion notice. The Gathering card says **Gather soil / sand** instead of implying it opens an unimplemented product.

Completed conditions no longer demand a replacement gift. Equivalent process machines are alternatives: one stocked machine can make a route ready even when another is empty. Input/nearby-ground availability remains a bounded readiness check. It does not prove avatar collision paths, occlusion, full machine power/thermal capacity, or the eventual outcome of a stroke.

## Measured acceptance

Windows 11 / Python 3.13.5 / MSVC 19.44 CPU Release runner from `f819e81`; Python implementation `2ee3ab7`. [Structured receipts](evidence/player-tool-learning/acceptance.json) retain the final scripted two-seed run. Only generator seed selection and deliberate save failures are fixtures. Inventory, tool geometry, native outcomes and rewards are not injected.

| Terrain / goods seed | Work, J | Sand removed, m³ | Soil removed, m³ | Personal result |
|---|---:|---:|---:|---|
| 7 / 851269742 | 58.42453 | 0.016307715822450396 | 0.00008225750851535533 | 2 evidence records; Gathering by hand |
| 4 / 1 | 60.73312 | 0.020205271718234143 | 0 | 2 evidence records; Gathering by hand |

Both use 50 mm scene cells and `dt=1/240 s`. Actual API take → stow → equip → study → use passes. Study alone earns no functional technique; source-save failure awards nothing; journal failure recovers from the saved outbox on a new server instance. A repeat study/save leaves two records and one technique. The other guest's journal remains empty. These are scripted authenticated player checks, with **zero provider calls**, not autonomous LLM play. Host scheduling changes settling and numerical yield; other passing runs differ and no bitwise timing promise is made.

The [Chrome Skills view](evidence/player-tool-learning/skills.png) and destination link pass without awarding knowledge for navigation or reporting browser exceptions. Test browsers/servers are isolated fixtures and shut down; existing user servers were not restarted.

Verification: knowledge 45; focused final two-seed journey 1; new Chrome guidance 1; actions 39; native installation 39; tool suite 7; room store 25; fabrication 27; Workshop tabs 9; Market 2, all pass. The existing full AI suite passed 12 tests in 196.249 s before the final occupancy/capacity/presentation refinements; the affected final tool/knowledge/Chrome checks were then rerun. Its pinned real-time rover returned two source receipts at 130.892 native / 132.867 wall seconds and retained a 3,600 J wallet through bank failure/retry/rejoin/restart. This proves source return consistency, not correct delivery at the intended yard or routing across arbitrary seeds. Source-registration remains 286/286, JS syntax and diff checks pass. No new constitutive or conservation tolerance was introduced; prior glass/oak/iron comparative installation/work evidence remains covered.

## Remaining gates

Connect Camp → tool study → measured gathering → useful work surface → supported process using ordinary receipt-backed goals. Expand the AI catalog to those actions and recipe comparisons. Test live provider and reference play separately across seeds/scarcity. Finish complete affordable Market recommendations and compact product/source labels. Rover routing/delivery is still unresolved. The current reference bot still stops at Camp; this checkpoint does not claim full tech-tree playability.
