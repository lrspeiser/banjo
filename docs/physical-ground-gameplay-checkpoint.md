# Physical ground and raw tool flow — October 5, 2026

This integrates the bounded dry-column excavation replacement, private raw
material collection and paid tool forming with the current Build/chat UI.
It supersedes the fixed-hit cube lane described in the historical October 4
notes. It is an experimental work-cut reduction with native rigid motion,
not a qualified constitutive fracture or granular-soil model.

## Player flow

1. Hold a connected ground tool. Click a dry ground face; ordinary hand contact
   remains the default. Green means the reachable loose-ground action is ready.
   Rock shows an amber work/material warning; the native material gate decides
   whether the actual point can cut it. Wet physical excavation refuses.
2. Removed matter retains exact small source cells. The renderer follows native
   component geometry and poses. Click the loose component within reach to
   collect it into private raw Inventory. There is no assigned launch path or
   receipt-to-pile animation in this lane.
3. Select collected Rock in Inventory, choose **Stone field pick** in Build,
   inspect/edit the draft and **Review Make**. The plan shows the remaining
   wood, raw rock, station and energy requirements. Opening a source never
   manufactures an item. Paid Make rechecks and reserves the exact input.
4. Take/equip the finished item from Inventory. Its constituent-derived native
   quote, fixed head/handle and connected working point survive storage/reopen.

**Menu → Energy assist** is optional and defaults Off. It redeems finite banked
energy as declared external cutting work, up to 500 kJ per request. It does not
simulate an electrical connection to a hand tool. The SQL escrow reserves before
native execution, saves the native receipt before settlement and refunds unused
work. Unknown replies retain the stable request and reserve for retry. Wallet
charges round up to integer joules; `wallet_rounding_j` records that difference.
This does not override the native point hardness/attachment/reach gates.

## Authoritative state and recovery

- Native ground state v6 persists cut source revisions, accumulated work,
  exact clipped 5 cm cells, material, density, mass, source centers and current
  native component state. Earlier ground versions retain their bulk ledgers;
  loading one does not invent historical cells or trajectories.
- Normal step replies contain compact native slabs/poses. New components request
  full source-cell metadata once; no frame or hover requests a model.
- Collection clones the whole native state, checks authenticated stored reach
  and native occlusion, withdraws the exact paired quantities, adds a private
  cell lot and saves both sides together before replacing the live session.
  Exact retries return the existing owned receipt, including a lost reply with
  the original session ID. Other players cannot replay or spend private lots.
- Confirmed collected IDs ignore late pose/metadata replies. Native IDs persist
  through whole session restoration; refresh/new game creates a new renderer.
- Raw forming retains source allocations and a source-to-product/offcut mapping.
  Ground auditing includes currently physical loose volume so it does not
  incorrectly label released but uncollected matter as untracked.
- The player route allowlist includes only the two new bounded material routes,
  alongside existing player actions. It does not enable arbitrary native edits.

## Verification

Environment: Windows, Python 3.13, MSVC Release, CPU/Jolt reference at dt 1/240 s.
Build cache: `build/agent-column-terrain`, Lab disabled, separate from the owner
demo. Native outputs include the runner, platform CLI and C ABI DLL. Every C++
source is registered with CMake; `scripts/check-source-registration.py` checks
304/304 sources.

The [native checkpoint](native-ground-matter-checkpoint.md) records same-condition glass/oak/iron scenarios, precise
source volumes, clipped geometry, real falling/settling, corrupt-state refusal,
saved partial work and internal contact source aggregation. The raw crafting
[checkpoint](raw-crafting-readiness-checkpoint.md) records twelve native input/
forming/recovery tests and the nine escrow/route tests. The host/UI
[checkpoint](ui-chat-verification-checkpoint.md) records Build/chat/voice flows.
These fixtures supply a cutter, finite wood and energy explicitly; they do not
prove an unaided new player's opening supply path.

Ordinary dry-column oak tool experiment: 26.321 J of measured ground work removes
0.00590749 m³ (9.452 kg) as 100 exact cells in one connected native component.
The swing/pry/withdraw/settle fixture takes 2.771 simulated seconds at 1/240 s
and 77.3 ms native wall time, excluding setup and collection. This is not a
browser round-trip timing or a deep excavation benchmark. The same Stone pick
source passes the actual paid builder/readiness at both 40 mm and 50 mm room
grids; their sampled products are 8.4992 kg and 12.8 kg respectively. Source
dimensions are unchanged and actual occupied matter determines each paid cost.

Measured escrow experiment: a 600 kJ private external reservoir reserves 500 kJ,
cuts a 25 cm rock cell using 468,750 J, refunds 31,250 J and ends at 131,250 J.
The actual component is 37.5 kg, 0.015625 m³, with no carried/exported duplicate
and zero untracked-volume residual. Failed-save recovery/replay/reopen executes
one native strike in total. This is a volume/work-source check, not a complete
world momentum/energy audit.

Final scoped checks also pass eight retained goods browser journeys together
(63.788 s), the actual native collection/Build browser journey (8.853 s), four
Build/chat browser cases, 48 fitting and eight fixed-assembly cases. The registered
terrain palette, voice client/controller and physical-matter renderer tests pass
4/4 in 0.71 s. Native live-world, carry and water suites pass; the nine hand
stroke cases pass after an existing out-of-reach fixture was corrected without
changing its work assertions or the material laws.

The broader host sweep ran 91 entries in 598.116 s: 87 passed, two private-ground
fixtures needed the v6 assertion/cache invalidation corrections, one paid-target
strike exposed clock sensitivity, and one entry was an orchestration ImportError
for a nonexistent module. The two corrected private cases pass separately in
5.245 s; the actual process-guidance cases are registered from PrivateGround.
The registered process-guidance CTest gate also passes separately in 48.63 s.
The initial sweep is not reported as a clean all-suite run. The paid-target
experiment produces identical physical output on unchanged `249f350d` and the
final native bundle under the same deterministic solver ticks: 26.31679 J hand
work and a 2.0780968666 m/s first impact, with contact only. The original threaded
one-hit fixture alternated between separation and contact only. Its test and
all assertions remain unchanged; it is an unresolved baseline test gate, not a
passing destruction qualification or a new excavation regression. A second-hit
diagnostic is excluded because later floor contact requested unsupported
fracture handling. Exact details are in the native checkpoint.

## Remaining acceptance gates

- Constitutive terrain detachment, calibrated natural-stone fracture, oak grain,
  iron plasticity, granular flow and a complete external/contact/thermal energy
  and momentum ledger remain unqualified. Soft clods are connected rigid cut
  components. Crafted forming uses the existing declared cold-stock process;
  retained source history is not state-preserving constitutive deformation.
- Smooth-ground and machine extraction retain their existing bounded bulk
  lanes. Wet/mixed unsupported hand strokes, cross-region wedges, covered-tunnel
  water and erosion/caving are not promoted by this checkpoint.
- The rock specific-work law remains 30 MJ/m³. An oak point cannot mine rock;
  a concrete-surrogate stone point is not claimed to be harder than that same
  rock. An affordable harder point and finite power progression still need
  fresh-player acceptance. Fast solver cuts do not prove the 10 ft gameplay gate.
- Read-only native cutting quotes need factoring before rock previews can turn
  green based on exact point/work admission rather than an amber warning.
- Native live-component and external retry-history limits are bounded. Long
  session history archival and large excavation performance remain open.
- Actual human/mobile/audio play, the ordinary opening after changed collection,
  and the complete earlier construction/economy backlog are not declared done.
  Separately paused R3 work remains paused.
- The preexisting one-hit paid target strike fixture still depends on host
  scheduling. A deterministic, supported contact/failure experiment must replace
  that assumption before treating the complete test suite as a clean gate.

## Publication and owner demo

Implementation checkpoint **`2d9f626b6581911461211600c1951a582ada7b26`** is
published on GitHub main. The owner demo at `http://localhost:18890` was gracefully
stopped through its supported SIGBREAK save/shutdown handler, fast-forwarded from
`249f350d` to that checkpoint, and restarted hidden with the tested runner/CLI/DLL
hashes recorded in the native checkpoint. `/api/status` reports engine ready and
the existing model credential configured; no credential or build/private state
is committed.

All 153 private room files match the post-shutdown backup byte for byte before
restart. Private rooms, prior binaries and existing configuration have local
backups under `C:/play/build/physical-ground-20261005`. Subsequent world-clock
steps are normal live changes. The existing player/world reopens with its 225 kg
legacy Rock, 37.5 kg Copper and prior stock intact; no materials were collected,
spent or granted as an owner-demo fixture.

The owner's existing browser tab was reloaded and left at
`http://localhost:18890/world?world=8b5044e9fa524b46b8d887a22ec353af`.
The visible World/Inventory/Build/Progress bar, microphone control, compact
Inventory thumbnails and native collection instructions are verified. No browser
console errors appeared; Three.js emits an existing shadow-map deprecation
warning. Screenshot: ignored `build/workshop-navigation/owner-demo-published.jpg`.
The new physical module is served with the same content hash as the installed
source. This deployment does not qualify the unresolved gates listed above.
