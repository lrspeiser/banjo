# Rover close arrival and visible recovery feedback

October 3, 2026. Published implementation: `7dcdcfe` on GitHub main.
Verification base: published `2170449`, plus this host/UI checkpoint.
The full material, opening, guidance and physical-behavior scope
remains active. No native source, binary, material law or solver tolerance was
changed.

## Reproduced defects and implementation

The retained ordered-port test failed on the verification base: no completion
message in its unchanged 60 simulated seconds. Observed native motion approached
the smelter intake, stopped outside the accepted region and repeatedly turned
and replanned. The nearest observed chassis reading was 1.296682 m from the
mouth. A grid endpoint up to 0.25 m outside the receiving region was marked
final, while the native waypoint ask could stop 0.4 m before that endpoint.
The transit obstacle allowance also excluded the close receiving region.

For a close destination with an outer radius at most 1 m and no inner exclusion,
the bounded planner now tapers its additional transit allowance as it reaches
that region. It retains the actual occupied assembly radius, surveyed terrain,
grade/probe checks, native collision and hazard guards. A final leg is extended
to a surveyed point inside the receiving region with a 0.1 m native arrival
request. An unsafe extension does not report final arrival. No body is moved by
the planner. Other working rings and larger receiving regions retain their
existing requests. The 0.25 m routine acceptance allowance and all test time
limits remain unchanged.

The ordered-port journey now completes at 25.5 simulated seconds, with the
observed chassis 0.904 m from the mouth and its brakes settled. The order report,
return to routine, person-near watch, drone order/cancellation and stationary
machine refusal all pass.

The packing-Q failure was also reproduced through ordinary controls in an
isolated in-app-browser world. Clicking Take hold to recover entered Cursor
mode; Q silently returned. Switching to Explore made the existing recovery
guard answer. Moreover, selecting an item hid the look-at card containing the
last-action message. The keyboard now permits packing an already held item in
Cursor mode through the same guarded Inventory action as Stow. Text fields,
browser shortcuts, repeat keys, movement and empty-hand targeting retain their
guards. Last-action feedback is a shared visible status above the selected
component card. Recovery refuses packing in both modes without releasing it.

## Verification

Windows, Python 3.13.5, Node 22.18.0, existing MSVC Release engines in
`build/agent-object-strike/Release`. Native steps are 1/240 s. The mine fixture
uses its declared 50 mm grid; generated repeat maps retain their declared
terrain and machine sampling. These are controller, ownership and UI checks,
not new material realism or full conservation qualification.

Set `BANJO_LIVE_ENGINE` to `banjo_live_world_run.exe` and `BANJO_LIBRARY` to
`banjo.dll` in that Release directory, then:

| Check | Result |
|---|---|
| `routine_language_tests.py` | 8 pass, 1.535 s; ordered-port 60 s bound retained |
| `rover_brain_tests.py` | 57 pass, 9.465 s; includes stopping room, solid exclusion, dry probes, load/restart |
| `ports_tests.py` | 23 pass, 3.362 s; native docking at 17.3 s and actual ore transfer at 19.3 s |
| `quick_tool_tests.py -k KeyboardInventory` | 1 pass, 0.055 s; shipped listener with input/mode state |
| `world_goods_tests.py -k test_rover_recovery_is_nearby` | 1 pass, 4.282 s; both seeds, bounded native lift/work, peer/save failures/retry/reopen/release |
| `generated_rover_repeat_tests.py` | 1 pass, 222.456 s; three positive deliveries on each of two maps and exact routine reopening |

Total: 91 passing checks. No check was removed or tolerance relaxed. The existing
automated browser recovery case additionally requires a visible refusal and
asserts Cursor mode after acquisition; its full legacy browser harness was not
executed in this session. Browser acceptance used the supported computer-use
API: declared isolated observer arrival beside the actual native assembly,
normal acquisition, Q in Cursor/Explore, retained hold after reload and visible
release. The release leaves power off; browser error capture is empty. No
browser script repositioned the observer or native bodies. Native lift/work
evidence comes from the two-seed headless test, not a claimed browser lift.

Repeat hauling retained these measurements:

| Generated choice | Delivery times, simulated s | Delivered kg | Copper ore kg | Plans | Maximum surveys | Median / maximum plan wall s |
|---|---|---|---|---|---|---|
| 0 | 52.2, 145.0, 202.6 | 120 | 36 | 27 | 4092 | 0.308 / 0.496 |
| 1 | 30.2, 127.4, 220.8 | 120 | 36 | 13 | 1745 | 0.067 / 0.367 |

Both restore the exact routine/load receipts after full server restart; neither
needed a checked retreat in this run. Observation remains bounded to 6 m and
4096 surveys. No inventory, material supply or pose reset was used to pass.
Ignored evidence: `build/resource-flow/port-order-trace.json`,
`generated-repeat-hauling.json` and `recovery-cursor-refusal.png` in that folder.
Source registration, Python compilation, JavaScript syntax, changed-document
links and Git whitespace checks pass before publication.

## Physical boundary and next checks

The existing [glass/oak/iron wheel-grade comparison](rover-grades.md), native
motor torque-speed law, reactions and battery/work limitations remain in force.
The generated rover retains its declared oak/glass/iron assembly; this change
does not establish general material-dependent routing. Cargo remains a goods
account without native load inertia. Port transfer remains a ledger operation,
not physical chute flow. Recovery remains an external bounded grip with a
camera observer, not a native avatar reaction. Full mechanical work/momentum
closure, fatigue, calibrated breakage, avatar contact/water and physical cargo
are unqualified.

R4 still needs additional declared pits, shorelines, grades and obstacle
families, explicit unreachable-destination recovery and sustained processing.
Material/exposed-layer/peer/performance acceptance, broader useful supply
routes, human/model progression and R5 native avatars/water/cargo remain active.
R3 repair remains owner-paused; its existing strike/reuse defect is retained.
