# Live tool skill progress — October 1, 2026

Status: implemented and verified on Windows against source base `3dd8f074282096ae872a0e6823eac41ea30e2a13` with the outgoing edits. Implementation `a9ba0e3cfa158417f1919e0f69ecb3801d5964d0` is published on GitHub main. The following presentation refinement shortens refused target labels; it changes no learning condition. [Retained measurements](evidence/live-tool-skills-checkpoint.json).

## Player flow

Take/equip the pick and aim at nearby dry soil or sand. The right panel shows **Gathering by hand**, the action to do, and **0 / 1**. A stroke shows **Digging…**. A closed supported native dig that removes material with the tool still whole earns the technique after its source and personal journal are saved. The separate Study action is optional for this skill. It still records an authentic inspection when deliberately performed.

Completion shows **1 / 1**, **Learned ✓**, and **New Achievement: Gathering by hand** over the world. Named product unlocks appear when the catalog declares them. The notice stays five seconds and fades over 0.4 seconds; simultaneous awards are queued. Repeat strokes and reloads do not repeat the award. Skills links to the exact learned technique in the same world and player account.

The current tool's construction selects relevant routes and their actual saved condition counts. Completed skill stays visible during its notice, then another applicable skill is shown if the catalog has one. The starter Field pick currently has one tracked skill; its card says **No further skills for this tool yet**. Unmatched authored designs say that no skill is tracked. Selection never awards knowledge; unsuccessful or unsupported use never fills a skill meter. Animation indicates work in progress and does not invent intermediate completion percentages.

Tool-use responses now refresh the visible notebook immediately, including a reply arriving after the tool was put down. Target guidance refreshes the contextual card separately. Save failures retain the existing personal outbox and show pending status; journal loading reevaluates earlier persisted successful results so a player who previously dug without studying can receive the missing skill. Evidence is not copied between players.

## Verification

Windows / Python 3.13 / MSVC 19.44 Release CPU binaries / ordinary Chrome E and J input. Native engine and DLL are unchanged from the fresh-workbench checkpoint. Native dt = 1/240 s; generated scene cell = 50 mm.

- Knowledge **48/48**: direct successful dig, failed/unsupported/broken/zero-yield refusal, real route condition counts, prerequisite order, alternate construction isolation and a following skill fixture.
- Tool handling **20/20**, controller boundaries **9/9**, API documentation **12/12**.
- Actual native two-map player journey **1/1**, 8.448 s: take/stow/equip/use, whole-tool positive material removal, deliberate source/journal save failures, restart recovery, no peer award and no duplicate replay. Terrain 4 earns gathering without any preceding study; terrain 7 retains the explicit study/save-failure case. No provider calls.
- Actual Chrome journey **1/1**, final 16.399 s: empty journal, E pickup, J stroke, animated work state at 0/1, native success, achievement, 1/1, fade, repeated dig, reload and exact Skills link. Native sand removal 29.34719 kg, ground work 53.13456 J in the retained run. Browser and native scheduling change settling/yield; these numbers are measurements rather than golden tolerances. No JavaScript exceptions.
- Existing Chrome Skills navigation **1/1**, 4.217 s; world-aware Skills/Market guidance **1/1**, 1.437 s. Navigation grants nothing.
- Default First Camp suite **4/4**, 53.985 s; paid construction and separate player inventory remain valid.
- Source-registration **287/287** and changed-file/diff checks pass. Browser fixture closure can log aborted in-flight HTTP writes; these do not indicate an application exception or a failed assertion.

The refreshed local preview at **http://127.0.0.1:8770/world** passes legacy-world reopen (10 bodies), fresh funded workbench with zero stock/energy, unchanged 22-cell pick, native E pickup, component thumbnails and the 0/1 contextual skill card. Its positioning state is the short **Step back** label. No JavaScript exceptions. Existing worlds/players are preserved; other local servers are untouched.

## Limits / next work

This changes host progression and presentation. It adds no native physics law, free resources, manufacturing process or tool strength. It does not certify global momentum/energy conservation, grain, plasticity or fracture realism; no conservation tolerance is changed. Existing glass/oak/iron physical comparisons remain the prior published evidence, not new measurements of this UI work.

Only existing catalog routes can advance; the starter pick has no second gathering skill yet. Later tools/processes and generated-design progression need additional supported routes and player acceptance. The fourteen-item player experience goal stays **four verified, ten partial**. Broader paid progression and damaged-tool replacement/use remain open.
