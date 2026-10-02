# Quiet tool autosave retries — October 1, 2026

Verified on base main `11ab00ceb87de42afb6f6015a2513448140ca69e` with outgoing source changes present. [Machine-readable evidence](evidence/tool-autosave-checkpoint.json) records source/binary hashes and actual save transitions. Implementation **`910e6ab20329ba2d608498188a8cba2001228181`** is published on GitHub main; the refreshed local preview is http://127.0.0.1:8770/world.

## Cause and change

`LiveWorld::snapshot` deliberately refuses incomplete tool strokes, embedded points/edges and fracture transitions. `keep_world` previously labelled every such refusal **failed**, causing the shared “World not saved” banner during normal tool use.

Known native transient guards now produce **pending** and retain the last complete disk checkpoint. Page stepping retries after 0.5 simulation seconds, even when the five-second periodic save is not yet due. The existing tool-completion save and unattended-clock saves remain. No blocking save wait or tool animation is added. Pending refusals log at debug level. Unknown refusals, engine/transport problems and disk errors still report **failed**. A pending attempt cannot clear an earlier genuine failure; only a successful paired checkpoint does.

World state, room accounts, receiving stock and learning outboxes retain their existing atomic boundary. Pending work is not yet durable; an abrupt stop before a safe checkpoint can lose progress since the last save. A point/edge left embedded continues to wait until it is withdrawn. Paid operations still require successful saving. No snapshot restriction, material/contact law, conservation gate, timestep or tolerance is weakened.

## Verification

Windows, Python 3.13, MSVC 19.44 Release CPU ABI 25, actual Chrome; generated 50 mm world, native dt=1/240 s. Existing compiled runner/DLL reused.

- `python tests/room_store_tests.py -q`: **28 pass**. Known guard classification, retained prior checkpoint, throttled early retry, unknown refusal and disk failure/recovery.
- `python tests/quick_tool_tests.py -q` with required Chrome and explicit native runner/DLL: **5 pass**. A real snapshot during a real stroke becomes pending; ordinary E/J hold, rapid taps and stop show zero save warnings. Held use measures **2.37 completions/s**, maximum rotation **4.04°**. Injected disk failure displays the real warning and a successful checkpoint clears it. All nonzero per-actor native excavated stock and tool-point declarations survive server restart. Matched glass/oak/iron native contact regression remains included.
- `python tests/ai_player_tests.py AutonomousGuests.test_generated_starter_tool_can_be_taken_re_equipped_and_used_through_player_routes -q`: **1 pass**, both generated terrains. Failed physical save does not award skills; journal failure retains the durable outbox and recovers on restart without duplicate evidence or peer awards.
- `python tests/world_goods_tests.py -q`: **15 pass**, retained private source/credit, retries, restart and machine/input/output flows. Windows browser shutdown can still log the previously recorded `WinError 10053` connection-close trace.
- Refreshed preview `http://127.0.0.1:8770/world`: legacy reopen and fresh funded workbench, native pickup, compact Inventory and skill card pass with zero JavaScript exceptions.
- `python scripts/check-source-registration.py`: **287/287** registered; `git diff --check` passes.

This verifies host persistence handling and retained existing native behavior. Broader player progression remains the [six remaining goals](player-experience-checklist.md#remaining-work).
