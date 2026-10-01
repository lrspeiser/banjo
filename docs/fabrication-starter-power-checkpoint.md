# Finite starter solar output — October 1, 2026

Published implementation: `2365ffe86bb321e90e293ddf195fabb870343316` on
GitHub main. Remote main was checked after the ordinary fast-forward push.
Own 8770 preview serves this Python implementation with unchanged native binaries.

## Implemented

Fresh generated yards declare a **10,000 W battery output rating** on their
existing solar array. Capacity, initial charge and voltage remain 20 MJ, 2 MJ
and 48 V. This is an authored starter hardware rating, chosen for the yard's
existing 5 kW furnace and other loads with charger margin. It is not derived
from battery geometry/material or certified electrical hardware.

The optional `max_power_w` property now survives Workshop chat, checked machine
records, the solar recipe and native installation export. Positive finite
numbers up to 1 MW are accepted; booleans, strings, invalid containers and
nonfinite/out-of-range values refuse. Omitted/zero ratings retain the native
unbounded authoring convention and cannot qualify for finite fabrication.
Older saved records without the field export their previous declaration.
Existing worlds are not regenerated or assigned a new rating.

The Lab regression now funds its replacement and saved-design Make from the
actual generated solar battery, without adding a fixture battery. It still
explicitly configures the fixture workbench at 500 W and 100 J/kg with no
initial process stock/energy. The default fresh world does **not** yet declare
that process. Ordinary Make, AI and supported machine manufacture need to
migrate together before the funded guard can be enabled by default.

World MCP is 1.18.0; platform MCP is 1.21.0. Native ABI remains 25. No native
law, material preset, solver tolerance, capacity or initial-energy change.

Sources: [starter generator](../tools/build_new_world.py),
[machine contract/export](../mcp/workshop_machines.py),
[solar recipe](../mcp/workshop_products.py),
[chat prompt/schema](../playground/workshop_chat.py),
[contract regression](../tests/workshop_tabs_tests.py) and
[native/browser journey](../tests/fabrication_remake_tests.py).

## Verification

Windows/MSVC Release, unchanged native runner/library. At 50 mm and
`dt=1/240 s`, the actual browser oak pick costs 1.925 kg / 192.5 J under the
authored shaping estimate. Reviewed material funding, accepted native charging,
lost acknowledgements/reload retries, owned Start/Run/Place, pickup/bag/equip
and actual digging pass using the generated 10 kW source. The original parked
pick and peer state remain unchanged. Saved-design paid Make also passes.

The latest actual stroke loosens **34.43438 kg** of sand/soil for **61.52121 J**
of native ground-work-v1 work (23.34244 J penetration, 38.17877 J breakout).
This browser-timed stroke differs from the earlier checkpoint; no controlled
performance/wear improvement is inferred. Native tool motion and accounting
are retained, without fatigue, damage-healing or strength certification.

Matched glass/oak/iron paid admission at 40 mm / `dt=1/240 s` remains covered:
2.56 / 0.7168 / 8.05888 kg consume 256 / 71.68 / 805.888 J. The actual 10 mm
oak cut-source test retains 104/12,876 broken bonds. Authored 100 J/kg is a
lumped shaping estimate, not calibrated glass cutting, grain or iron forming.

Checks:

- Fixed Fabrication QA: **59/59**, 61.461 s.
- Workshop tabs/rating and old-record compatibility: **10/10**, 1.314 s.
- API documentation parity: **12/12**, 0.186 s.
- Chat tool parity: **22/22**, 0.010 s.
- Native/Chrome day/night charging, shadows, lamp/unwire/dawn: **2/2**, 10.446 s.
- Generated rover/processor/personal collection/restart: **2/2**, 145.655 s.
  Two measured first deliveries: 40 kg by 52.2 s and 30.2 s; 12 kg mined ore
  and 9.6 kg collected copper each, conversion residual zero. These are two
  seed cases, not general route qualification or a controlled speed comparison.
- Source registration: **287/287**, no intentionally unbuilt files.

Fixed report: ignored
`build/resource-flow/starter-finite-power-20261001/report.json`, base
`3fe40f70998309453a404454974ba18bc7f5c26c` plus this dirty source scope.
Runner SHA-256:
`8d5ff68d5d32119932878bb860c8c3a3fbbc761dc5fba36f472ff5a94c167f97`.
Library SHA-256:
`b9d277d970cddbd20f2950f55f683cb4bcbf1dd8e63ede01743dfc444cc87ba1`.
No native rebuild was needed for this Python/API change.

The refreshed 8770 Chrome preview creates a fresh world with three stores,
one finite source, 16 stock sources and no pending transfers. Inventory, actual
field-pick take/stow, carried Lab review refusal for the undeclared process,
empty Lab and zero JavaScript exceptions pass. Preview:
`http://127.0.0.1:8770/world?world=050a5856768a484883a034d21995ab8c`.
The earlier persisted world retains its legacy source declaration.

## Remaining acceptance

Declare the ordinary workbench process and integrate supported player/AI/machine
builds without bypassing paid admission or disabling existing build paths.
Then verify an actual damaged carried tool through replacement and use in a
fresh ordinary world. Mixed interfaces, exact rigid forming, fatigue/joints,
physical transport and full-world conservation remain separate gates.
All fourteen player requirements remain active: **four verified, ten partial**.
