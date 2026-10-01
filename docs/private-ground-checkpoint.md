# Private carrying accounts — October 1, 2026

Published implementation: `7c6c4ae` on GitHub main. Native runner, C library,
platform CLI and ground-work test were rebuilt from these implementation sources
in `build/agent-progression` (MSVC Release). This extends
[gathering and supply](gathering-supply-checkpoint.md), within the complete
[fourteen-item goal](player-experience-checklist.md). Four items remain verified,
nine partial and durability/repair pending.

## Implemented

- Native ground state v5 stores named sand/soil/rock accounts in `carriers`.
  Shared terrain, excavation, deposition and export/return ledgers remain one
  world. The empty actor retains the earlier anonymous load in `carried`.
  v1–v4 saves migrate without assigning that load to a joining player.
- Native selection follows the authenticated player's hand. Each actor's own
  parked native mass and gripped body's mass consume their allowance. Named
  parked owners persist; another actor's unpark refuses before changing state.
- A hand-tool bite captures its holder when it begins. Breakout credits that
  holder even while another player or the unattended clock advances the solver.
  Powered breakers use the current holder's budget and receiving account.
- Routine scoops, deposits and receipted exports/returns select a server-owned
  `machine:<program name>` account. A full requesting player cannot block a
  rover's independent hopper. Native transfers still require host receipts.
- HTTP derives the actor from the token, ignoring a supplied actor. Named
  players cannot call raw `ground_withdraw`/`ground_return` through live HTTP;
  storage and machines pair those operations with their receiving records.
- World replies and Inventory show the requesting player's load, capacity and
  pictured substances. Inventory offers **Heap → World**; H heaps sand/soil in
  World. Earlier anonymous stock appears separately as **World load · unassigned**.
  It is preserved and visible, without an invented owner.
- Funded fabrication stages its selected actor's stock, preserves every other
  account, and commits native debit, receiving lot and retry receipt together.
  Whole-world bulk diagnostics use aggregate carried stock, rather than whichever
  actor last requested a view.

## Measured native ownership and mass

Windows 11, MSVC Release CPU reference, Python 3.13.5 and installed Chrome.
Native tool cases use 40 mm matter cells and `dt=1/240 s`; matched experiments
keep the same geometry, terrain and 80 kg allowance for glass, oak and iron.

| Tool material | Parked native mass | Alice's excavated load | Bob's excavated load | Terrain residual |
|---|---:|---:|---:|---:|
| Glass | 4.320000 kg | 75.680000 kg | 80.000000 kg | 1.24345e-13 m³ |
| Oak | 1.209600 kg | 78.790400 kg | 80.000000 kg | 1.29674e-13 m³ |
| Iron | 13.599360 kg | 66.400640 kg | 80.000000 kg | 1.08358e-13 m³ |

Whole reopen retains each load and parked owner. Alice's heap leaves Bob's
load unchanged. A cloned ground account exceeding the excavation is refused;
Bob's attempted unpark leaves the full saved snapshot unchanged.

A real oak strike/pry/pull, stepped by Bob and the clock, releases 9.542 kg
to Alice with 27.720 J reported ground work and terrain residual 3.55271e-15 m³.
The other accounts receive zero. This is one measured stroke, not a fixed yield.

The existing matched drop oracle remains: glass/oak/iron energy residuals
are −0.004325528 / −0.000610494 / −0.027121319 J, inside the declared integration
correction and damping bounds of 0.008098328 / 0.001395404 / 0.058831232 J.
Trajectory differences between exact-equipment and mixed-scene runs are zero.
These bounded experiments do not close whole-world momentum/energy transfers.

The authored 1.5 kW breaker uses 0.25 m terrain cells and native `dt=1/240 s`.
Its 47.023252 kg held mass leaves only 32.976748 kg at normal capacity, so a
37.5 kg rock cell correctly refuses despite Bob's empty account. A separately
declared 100 kg test allowance permits completion to Alice; Bob and the clock
receive zero rock. Production allowance remains 80 kg. The existing 30 MJ/m³
rock-work and battery checks retain their 2% fixture tolerance, unchanged.

## API, storage and browser acceptance

- Two authenticated players each reach 80 kg. A forged actor cannot redirect
  Bob's dig to Alice. An actual rover scoop inside Alice's full request context
  still reaches its hopper and leaves both personal loads at 80 kg.
- Unattended stepping and a complete server stop/start preserve both loads and
  tokens. Alice heaps her stock; Bob retains 80 kg. Forged deposit and unfunded
  raw return refuse. Aggregate sand/soil ledger checks use unchanged 1e-9 m³
  comparison precision and include receipted machine exports.
- Chrome joins separately, sees zero while Alice carries 80 kg, then sees its
  own 80 kg/full indicator. Inventory shows its own pictured substances and
  separately displays a 20 kg anonymous fixture load; energy cards finish loading.
  No JavaScript exceptions. Reviewed screenshot is ignored
  `build/resource-flow/private-ground-inventory.png`.
- Private fabrication storage tests failed-save rollback, successful storage,
  retry, funded return and whole reopen while retaining Bob and anonymous stock.
  Existing v1/v2 migration, actual terrain/corruption and glass/oak/iron staging
  checks remain in the regression suite.

Final CMake acceptance: native ground work (11 cases), recipe guidance (3),
ordinary gathering (1), private ground (2) and mine loop (5) all pass in 61.31 s.
The final Inventory screenshot/text refinement's private suite passes separately.
Native installation passes 39 cases in 18.314 s; fabrication passes 28 in
16.644 s. Affected world goods (15) and rover brain (55) suites pass in
108.96 / 9.22 s. C terrain/tool/MCP boundary suites pass, retaining the public
anonymous ABI. Inventory (17), tool-use (20) and Workshop tabs (9) pass.
Native runner, C library, platform CLI and native test target are rebuilt.
The source registration guard reports 286/286 registered native sources.

The restarted port 8770 preview passes a fresh-world Chrome entry and actual
recipe supply route with zero JavaScript exceptions. Preview world:
`http://127.0.0.1:8770/world?world=d8e145c1ec9644e3b2f53ad00e0b0e0a`.
Changed-document local links validate (973 checked); syntax and changed-file
checks pass. These results are Windows/Chrome measurements, without cross-GPU
or other-platform claims.

## Remaining acceptance

- A player workflow to recover earlier anonymous loads is still needed. No
  owner is inferred from who happens to join first. Older parked records also
  retain unknown native ownership until explicitly brought back and stowed.
- Broken-rock carrying is accounted, but ordinary H heaping and receipted raw
  storage support sand/soil. Broken-rock storage and usable recipe stock remain.
- The general Workshop recipe economy still uses its recorded material/goods
  racks. Native ground cards do not silently become funded build stock.
  Process/output-to-build and broader saved-design journeys remain gates.
- Native carried/parked stock is an allowance ledger, without bag/hopper inertia,
  spilling or reacting avatar bodies. Held jointed extras are included in the
  Inventory display; native acquisition still budgets its gripped body.
- Unheld standalone breakers retain the anonymous world account. Broader
  machine ownership/permissions and arbitrary external native clients retain
  separate boundaries; this is not a whole-platform security certificate.
- No contact, material, friction, ground-work, energy law or physics tolerance
  changed. Repair, mixed-material pick joining, general rover routes and all
  other listed player-experience boundaries stay within the active goal.
