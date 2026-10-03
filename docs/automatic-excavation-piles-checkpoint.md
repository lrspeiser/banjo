# Automatic excavation piles — October 3, 2026

Implemented on main base `69ae9f5c`, Windows x64. Named sandbox/new-game worlds
use the same flow for existing and LLM-authored ground tools:

**Dig → nearby material pile → click → personal Inventory.**

Published implementation: `5af65746e756cb1fbdd2965a8b2aefcd01ff68c7`
on GitHub main, October 3, 2026. Verification below applies to that revision.

## Interaction and source contract

- A completed ordinary native tool action exports actual actor-owned sand,
  soil or broken rock into separate material piles. Earlier owned carried
  ground is recovered at the next reachable dig site. No inventory grant,
  predicted yield, new tool animation, native constitutive change or model
  request is introduced. Every transfer uses `ground_withdraw` and retains
  its native volume/density/mass packet in `ground_transfers`.
- Reuse a nearby pile of the same material. For a new pile, inspect dry
  candidate positions 1.1–2.2 m around the selected site, starting sideways
  from the player's approach. Avoid other stockpile centers. If no candidate
  is admitted, retain the material in the actor's native account and explain
  that moving a few steps allows another placement search. No material is
  discarded when placement fails.
- Piles use the existing shared goods ledger and bounded voxel pictures.
  Confirmed export events animate ground-to-pile packets. The pictures have
  no solver mass, collision, calibrated volume, repose or physical hauling;
  they do not replace the native terrain or its soil/sand settling law.
- Click a pile, including while holding a tool. The actual click ray checks
  native occlusion; collection rechecks 2 m horizontal reach and standing
  height. Pile clicks take priority over tool strokes. A nearby Collect button
  and delayed material popover provide the same ordinary receiving action.
  Machine outputs retain their existing proximity auto-collection; excavation
  piles collect deliberately.
- A click requests the entire available pile, rather than 25 kg installments.
  Collection uses the existing paired world claim/SQL credit outbox. Shared
  piles compete for current stock; the resulting Inventory credit is private.
  Retry, SQL recovery and whole reopening retain the original receiver.
- Personal raw Inventory is an aggregated storage ledger with no gameplay
  weight limit. Sand/soil/rock appear under raw materials, with thumbnails and
  amounts; the World meter no longer implies an 80 kg raw-storage ceiling.
  Native hand/carry/load limits still apply to actual held tools, machines,
  earlier carried stock and existing Store/Retrieve recovery controls.
- Shared processing guidance recognizes available excavation piles and offers
  Collect before loading a machine. AI Guide receives the pile facts and
  these rules. Custom tools use the existing shared extraction/profile/API
  path; prompts cannot promise unsupported native extraction laws.

Source history is compacted by receiving pile and material, retaining cumulative
native quantities. Rows retain the existing 100 m³ volume bound; large totals
split into additional rows. This does not erase source quantities. Technical
sanity/history limits remain: goods quantities at most 1e9 kg, 2048 collection
outbox claims and 4096 transfer rows. These are not inventory slots or a weight
progression mechanic. Long-lived receipt archival and full end-to-end resource
accounting remain separate scaling work; this checkpoint does not claim
mathematically infinite storage or complete manufacturing conservation.

## Verification

Windows 11, Python 3.13, Node 22; existing MSVC Release native products from
`a14248d5` in `build/sharp-cuts-final/Release`. Native C++ and material laws are
unchanged. No new general physical or glass/oak/iron constitutive claim is made;
their retained support comparison is documented in
[sharp excavation](sharp-excavation-checkpoint.md).

**95 focused checks pass:**

- Five native collection/recovery tests: more than 80 kg of actual older
  actor-owned excavation, separate receiving piles, empty actor ground load,
  compacted receipts, uncollected pile reopening, whole-pile collection,
  failed-save/no-credit, identical retry, SQL failure/restart and two-collector
  competition without duplicate credit. Personal API quantities retain their
  existing 5e-5 kg display/receipt comparison bound; no tolerance changes.
- Nine receiving/save tests include 300 source packets compacted into one
  exact 3 m³ soil total, supported native rock density/form, corrupt packet
  refusal and unchanged atomic save boundaries. Native export/receiving
  volume comparisons retain 1e-10 m³ absolute / 1e-12 relative tolerances.
- Three paid native layer journeys, smooth/columns/cuts: actual pick work
  exposes sand then soil; piles receive the measured output and collect into
  private stock without filling the hand; peers share geometry and receive
  no personal credit; native/Python reopening preserves both. Ore reserves
  are not credited or consumed by soil/sand pick work.
- 35 existing tool controls, 23 terrain rendering checks and five shipped
  client control checks pass. Pile click tests cover an equipped tool, exact
  click ray, occlusion, distance refusal and input-hopper priority.
- Four AI processing regressions pass, including retained writes and the
  ordinary two-surface exhausted-input recovery (236.36 s suite).
- Eleven game-guidance checks pass through unittest discovery (25.72 s).
  The file has no standalone runner; merely executing it is not a test run.

Registered final pile/receiving/three-surface rerun: 96.23 s. Source-registration
guard: 298/298 sources, ten CMake files, no intentional exclusions. Python
compilation, JavaScript syntax and diff whitespace checks pass. The existing
broader goal fixture failure remains the separate boundary described in
[tool HUD checkpoint](tool-hud-checkpoint.md#existing-broader-test-failure-and-remaining-work).

```powershell
python scripts/check-source-registration.py
ctest --test-dir build/agent-column-terrain -C Release --output-on-failure -R '^(banjo_excavation_piles_tests|banjo_ground_transfers_tests|banjo_tool_use_tests|banjo_tool_target_client_tests|banjo_cut_material_layer_tests|banjo_material_layer_tests|banjo_column_material_layer_tests|banjo_terrain_material_tests|banjo_ai_processing_tests)$'
# With BANJO_LIVE_ENGINE/BANJO_LIBRARY pointing at the same native products:
python -m unittest discover -s tests -p game_guidance_tests.py -v
```

## Browser observation and remaining work

Isolated comparison world `bd899fb4d1aa4e029bb88b6ace0194ab` on port 8779;
the owner's original world and Lab draft are retained. The paused comparison
character used its actual owned pick through ordinary authenticated requests.
The first placement search left soil carried in a crowded site. The final
wider search exports that 52.6 kg plus new output and reports **zero carried
ground**, with separate sand/soil piles. Browser rendering shows those shared
piles and the new raw-storage labels; isolated reported camera positioning
is a viewing fixture, not evidence of native avatar traversal. Screenshots
and local saves are ignored build artifacts.
Ordinary authenticated pile collection then puts 1.41 kg sand and 53.96 kg
soil in the isolated human player's private Inventory. Browser inspection
confirms both raw-material thumbnails and amounts. Screenshot:
`build/construction-preview/collected-material-inventory.png`. This pickup
was through the receiving API; browser direct-click reach/occlusion behavior
is covered separately by the shipped-handler test, not claimed as a manually
completed human walking journey.

Remaining acceptance: unaided human digging/pickup on both map families,
crowded/wet-edge fallback recognition, night readability and long-lived receipt
archival. Native physical pile bodies/cargo, actual erosion, full pipeline
momentum/energy closure and broader construction/R4/R5 remain unfinished. R3
remains owner-paused.
