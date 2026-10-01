# Player experience work — September 30, 2026

The owner's twelve-point goal supersedes the earlier progression-only task.
This is the current acceptance list, not a claim that all features are done.

| Item | Acceptance | Status |
|---|---|---|
| 1. Action clarity | Recorded dig/delivery/process packets, filling rover inventory, visible output, nearby personal pickup; failure/restart/race checks | Native/browser checkpoint verified; general generated routing remains a separate gate. See [resource flow](resource-flow.md). |
| 2. Day/night | Moving sun/shadows; measured solar charge; dark night; lamp switches on and draws its battery | New games declare a 600 s day and battery-powered automatic camp lamp. Native accelerated 10 s cycle verifies solar accounting, night draw and dawn switching; visual night/shadow review remains. Existing explicit worlds retain their declared sun. |
| 3. Fresh start | Ordinary entry creates a new playable generated map with bootstrap equipment; samples remain in Debug | Chrome verifies two plain entries create different generated worlds. Explicit world/scene/QA links preserved. |
| 4. Resource discovery | Deposits have readable visual cues; selection shows actual substance, quantity, reachable gathering action | Ledger extraction rings/labels implemented and present in Chrome; ground selection shows actual reserve/grade/rover action. Full selection usability review pending. These are extraction areas, not native ore-cell composition. |
| 5. Gravity mode | Menu toggles exploration/gravity walking; ground support, falling, grounded jump and collision boundaries verified | Chrome verifies menu, falling, one grounded jump per press and fly altitude. Kinematic terrain controller: native physical avatar/body collision boundaries remain open. |
| 6. Component inspection | Selected item can expand real components, with names/materials and a return to assembled view | Precise compound parts have a presentation-only expansion; names/material labels, full multi-body assemblies and dedicated visual verification remain pending. No synthetic fracture parts. |
| 7. Recipe guidance | Select recipe → exact personal/shared shortages, acquisition routes, blocking skill/equipment | Expandable card materials/acquisition routes implemented; native connected tool readiness fixed without granting strength. Full shortage/route browser journey pending. |
| 8. Gathering loop | Reach/find/make tool, explain capacity/refusal, visible carried stock in World, explicit empty/store/use action | World load meter shows actual native carried mass/limit/materials; full load displays stopped digging and H emptying guidance. Chrome HUD check passes; complete tool/full/empty journey pending. |
| 9. Workshop chat | Typing, sending and draft selection work; chat focus cannot be stolen by world key bindings | Native Chrome ordinary typing, submission, head edit and subsequent whole-item edit pass. Local failure cleanup and replacement textarea retain selection/disabled state. |
| 10. Pick authoring | Whole pick appears in Lab; metal head modification has actual component geometry/material; Save and Make give actionable outcomes | Verified exact bootstrap source recovery includes head/handle. Explicit Recipe→Lab survives reload; head-only iron edit and Save pass. Supported oak Make debits stock and preserves existing machines. Mixed-material lattice joining remains unsupported: metal-head Make and visual shape improvement remain open. |
| 11. Durability/repair | Integrity derives from actual recorded damage; supported repair requires matching material/energy and native restored/admitted geometry | Pending. No invented physical health, strength or free restoration. |
| 12. Rover safety/recovery | Actual sensor readings visible; route/dig clearance avoids own support; ordinary recovery available with bounded forces/work | Pending native reproduction on multiple terrains. |

Priorities: preserve the verified transfer checkpoint, repair fresh entry and
Workshop/tool/capacity blockers, then connect the remaining ordinary-player
journeys with measured acceptance. Keep CPU/native simulation separate from
presentation, retain glass/oak/iron comparisons for physical changes, and publish
verified coherent checkpoints regularly.

## Verification checkpoint

Resource flow implementation is published as `9cc3ad1` on main. The next
player-entry/Workshop checkpoint is published as `6098387` on main and uses Python 3.13.5, Windows Chrome and the
existing MSVC Release native engines from `f819e81`, at 50 mm and native
`dt=1/240 s`. No C++ or constitutive law changed. The explicit 10 s lighting
experiment consumed 100 J over five seconds at 20 W; array charge agrees with
initial charge + native collected − delivered energy within `3e-5 J` after
protocol rounding. It does not qualify full-world conservation or new materials.

Focused checks: resource suite (including two-guest failure/restart/races),
Workshop fitting 47, chat 38, tools 7, solar 9, live session 12, and both CSP
world-address/current-file hash checks. Remaining acceptance is listed above;
the twelve-item goal remains active.
