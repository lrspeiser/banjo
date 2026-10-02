# Paid mixed-material Make — October 2, 2026

## Status

Implemented and verified: normal Lab component edit → Save → reload → review
each material → fund Make → native output placement → World pickup/dig → private
bag → complete server restart → re-equip. **R2's supported iron-head/oak-handle
player journey is complete.** The five remaining goals are R1 and R3–R6 in the
[working list](player-experience-checklist.md#remaining-work).

Developed from published main `de9f4f8`. Native sources in this checkpoint
retain ABI 26 and require a rebuild for the assembly ray filter below.
Implementation publication is recorded in development status after the verified push.

This does not close raw supply routes, damaged-tool repair, physical avatars,
general rover reliability or live-provider progression. In particular, ordinary
held-tool strikes against built objects are still missing: click targets terrain,
and the fracture island does not integrate the continuing held striker. Exact
rigid parts have no internal fracture law. R3 must qualify actual damage and
paid reuse through ordinary controls, retaining the old item and its history.

## Shared compiler and payment

`banjo.workshop-fixed-assembly.v1` assigns occupied cells to separate constituent
bodies. Each keeps its material-derived mass and internal lattice model. Sampled
shared faces define finite ordinary native fixings; native constraints own those
interfaces. No material is replaced, no unoccupied gap is bridged, and no second
interface response is added to the same seam.

Each part must retain connected cells, the complete fixing graph must connect,
and each admitted mount must have a single planar face normal. Explicit authored
connections are honored. Missing/overlapping mounts, open connections, bearings
and mixed fixed groups inside articulated machines retain a named blocker.
Single-material lattice and exact machine paths retain their existing adapters.
Bridge budget feedback counts each constituent's actual separate boxes; it cannot
merge across a material seam to understate cost. A two-box collinear mixed fixture
is refused under a one-box budget despite its union fitting in one box.

Mount pull/shear limits use the existing weaker catalog material strength ×
sampled face area × existing declared method efficiency. This is an estimate;
adhesive/fastener quality, fatigue, bending and torsional failure are uncalibrated.
No new efficiency coefficients, material laws or native force limits are enabled.
The compact review shows connection count; numeric limits are collapsed.

An isolated native quote admits every constituent, fixing and working point
before payment. Actual retained cells, body material/mass, anchors, capacities
and head/handle binding must match the reviewed artifact. Start atomically
reserves each material and metered energy; placement verifies the same hash and
allocation, preserves original bodies/receipts, and admits each output's cold
thermal content through the existing local process account. Retry pays once.

The shared LLM instructions describe this contract, explain geometry blockers,
preserve requested materials and distinguish Save from Make and physical use.
They still refuse unsupported tool mechanics rather than inventing an effect.

## Handling and test corrections

Separate-head frame reads take point and actual handle pose at one native
instant, under the existing Live lock order. A stale pose cannot silently define
a different grip frame. First-use positioning moves the grip to safe clearance
before turning/lowering with the existing bounded hand. Established repeated
contacts keep their short path and cadence; native forces determine the result.

The separate HTTP QA run exposed an intermittent native ray obstruction:
`past_held` ignored the handle alone, so its separate head could hide the ground.
The native ray now filters the selected actor's complete active ordinary fixed
assembly. It still hits nearby terrain, other objects, other players' tools and
detached heads. Matched glass/oak/iron native tests verify those boundaries and
that the queries leave the snapshot unchanged. No ray marching, body motion,
contact response or material law is introduced by this fix. This does not
enable held-tool strikes against built objects.

The browser journey works beside the picked-up output. An earlier test teleported
the camera across the map while holding a physical 7.3 kg tool, creating a carry
transient unrelated to this acceptance flow. No body pose, speed, force limit or
fixing strength was reset to pass the corrected journey. It checks the actual
inventory assembly membership and re-equips after restart before checking the
live point, rather than expecting a parked point to be attached in the world.

The older solar-cart positive fixture failed the already-published mixed-group
guard. Its positive articulation test now explicitly declares homogeneous oak;
a separate negative test retains and refuses the catalog iron/oak design without
redrawing/recoloring it. This does not qualify mixed articulated lattice carts.

## Measurements and verification

Windows x64, Python 3.13, actual Chrome, rebuilt MSVC Release CPU native binaries.
Matched paid quotes/installation: 40 mm cells, native dt 1/240 s, identical
10 kg finite feed / 1000 J authored shaping input; unchanged process constants
and tolerances. These shaping constants are not calibrated manufacture.

| Head / oak handle | Product kg | Mechanical mass residual kg | Local process-energy residual J |
|---|---:|---:|---:|
| Glass | 2.176000 | −4.44e−16 | 2.842e−12 |
| Oak | 1.254400 | −2.22e−16 | 3.638e−12 |
| Iron | 4.925440 | −8.88e−16 | 1.819e−12 |

Glass/oak/iron densities remain 2500/700/7870 kg/m³; the handle stays oak.
Each native body retains its own thermal output and actual cells. Allocation,
debits, original state, failed placement/retry, full reopen and invalid native
binding before spending pass. These close local mass/energy accounts, not the
full mechanical/contact/damping conservation ledger.

The fresh-world browser run uses the ordinary initially empty 500 W workbench
and existing finite solar battery. **Explicit finite test stock** (20 kg oak +
20 kg iron) is collected through normal bounded private receipts, then funded
through actual UI controls. This qualifies R2 Make, not R1 natural supply.
The generated 50 mm iron/oak tool is 7.3025 kg. One measured native use removes
3.73808 kg sand/soil, reports 19.4674 J ground work, remains whole and credits
its owner. The old parked Field pick remains unchanged. Provider calls: zero.
This is an observed stroke, not a fixed per-click yield. The final targeted
browser case also waits for the saved design thumbnail to render after restart.

- Fixed fabrication QA: **77/77**, 128.559 s, including actual Chrome/restart.
- HTTP launch/MCP status/cancel and unchanged-live-room checks: **2/2**, 126.239 s.
- Affected rapid-tool/Workshop/install/handling checks: **131/131**, 45.986 s.
- Compiled native ground/query cases: **17/17**; four public binding/lanes/MCP
  suites pass in 19.00 s. Final constituent-budget/buildability cases: **17/17**.
- Final ordinary mixed Lab/World/restart/thumbnail case: **1/1**, 20.485 s.
- CMake registration: **287/287**; Python compile, JS syntax and diff checks pass.
- Screenshot inspected: `build/resource-flow/mixed-pick-paid-restart.png`.
- Ignored evidence: `build/resource-flow/paid-fixed-ray-20261001/report.json`,
  `paid-fixed-materials.json`, `paid-mixed-affected-ray.log`,
  `paid-fixed-manager-ray.log`, `paid-fixed-public-ray.log`,
  `paid-fixed-ground-native.log`, `paid-fixed-budget-final.log`,
  `paid-fixed-thumbnail-final.log`. The precommit report records `de9f4f8` and
  `source_dirty: true`; native sources/binary hashes correspond to this checkpoint.

The QA orchestration deadline increases from 120 to 180 seconds because the
expanded fixed suite first measured 127.384 seconds; cancellation and a finite timeout
remain. This changes no physics tolerance. The HTTP launch/MCP status/cancel
integration is checked separately and leaves the user's live room unchanged.

Refreshed own preview 8770 reopens the retained ten-body world and native tool
point with zero browser exceptions. The screenshot is inspected. A retained
rover reports no clearance around its footprint; that remains R4, not a passed
rover route. The legacy original's Inventory mass/source thumbnail remain
unavailable, while the new paid item's actual mass and saved design preview load.

Native runner SHA-256:
`073d7165bfc8b2c7cdcfec5ccf0a9ddcce92d76f25fc3b336a3a4aaed22a21c3`.
Native library SHA-256:
`eeec21de8b2d711384fc79a55b9c8c36cd26723887cac1ca5f5b016158389668`.

## Sources and next work

[Constituent compiler](../mcp/workshop_fixed_assembly.py),
[native installation](../playground/workshop_install.py),
[paid quote](../playground/fabrication_room.py),
[shared handling](../playground/tool_use.py),
[native ray filtering](../src/fastlattice/LiveWorld.cpp),
[native query regression](../tests/ground_work_tests.cpp),
[model instructions](../playground/workshop_chat.py),
[matched tests](../tests/workshop_fixed_assembly_tests.py),
[ordinary browser journey](../tests/fabrication_remake_tests.py),
[QA entrypoint](../scripts/fabrication_qa.py).

Continue R1 supply routes and R3 actual damage → reviewed replacement/repair →
pickup/use, preserving ownership, history and retry/restart. Keep R4–R6 and the
master platform/physics requirements intact. Arbitrary composite mounts,
calibrated joint failure, physical storage, full-world conservation and
macOS/cross-GPU behavior are not established by this checkpoint.
