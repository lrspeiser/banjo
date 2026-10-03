# Readable world and useful progression — October 3, 2026

Latest implementation checkpoint: `3544fd2` on GitHub main. This publication record
does not close the full active scope.

The [Camp light/output checkpoint](camp-light-opening-checkpoint.md) continues
the ordinary opening through watched output collection, a paid useful battery
light, placement/use and full server restart without purchases. Initial charge
is paid; this qualifies one complete route and its private guidance, not all
catalog supply graphs, unaided night recognition or physical cargo receiving.

The [ordinary opening/supply checkpoint](opening-human-supplies-checkpoint.md)
now observes a fresh browser wood → paid pick → numbered equip → native sand
stroke → learned skill → paid work table journey, with full process restarts.
Prepare supplies hides the manual transfer sequence while preserving real
stock, battery charge and durable retry. Live source identity/rating binding
removes the clock race without relaxing current charge or shared power limits.
Wider processing/custom/live-model acceptance and all broader physical gates
remain active; a legacy tabletop receiving regression remains unqualified.

The [exposed-layer/peer checkpoint](exposed-layer-peer-checkpoint.md) qualifies
actual sand → soil excavation, private Store/full restart and an ordinary
observer's changing terrain/Soil thumbnail without reload. Independent
geometry acknowledgements repair changes consumed by tool/clock replies;
matching-grid catchup preserves the mesh and exploration state. Night
recognition, broader hardware/load acceptance and the full progression/
physics scope below remain open.

The [reachable-ground guidance checkpoint](reachable-ground-guidance-checkpoint.md)
removes the at-feet gathering recommendation and stale Inventory-action pose.
Current-source HTTP/native openings follow the same reachable ground target
as shared guidance for both owners on both terrains, then retain paid evidence
through restart. Ordinary browser gathering shows sand/skill/Inventory/Goals
agreement and reload. Complete fresh human acceptance remains open.

The subsequent [close-arrival/recovery checkpoint](rover-close-arrival-checkpoint.md)
resolves the retained ordered-port and packing-Q failures and preserves real
three-load hauling/restart on both generated maps. Broader R4 route families
and R5 native avatars/water/cargo remain open, alongside the material, supply
and human/model acceptance described below.

Owner scope: material readability; an opening useful product with a complete
supply path and no purchase-only requirement; one next action/readiness model
across all game screens and chat; reliable hauling, physical avatar water
response and cargo consequences. This is the full active work scope. The
presentation checkpoint below does not close the progression or physics gates.

## Material presentation checkpoint

Implemented in `playground/material_appearance.js`, `terrain_material.js`,
`world.js`, `game_menu.js` and the server's explicit static allowlist:

- One presentation catalog follows native `RunKind` order. Rock, soil, sand,
  clay and ore have different colors and patterns. Native ore names and
  material samples resolve through the same catalog. Manufactured material
  laws, collection permissions and quantities do not use this catalog.
- A nearest-column texture lookup replaces interpolated vertex colors on the
  existing outdoor triangles. Each column's material has a sharp boundary;
  patterned surfaces and restrained cell edges show the 25 cm sampling in
  a default generated world. Fine edge lines fade with screen derivatives.
- Changes and exploration repaint the texture from the actual retained runs
  and visibility record. Unexplored cells remain unknown. Texture disposal is
  paired with world replacement; changed geometry refreshes its bounds.
- The aimed cell has a thin local outline sampled on the actual triangular
  surface. It is hidden off-grid, beyond five metres, on unknown ground and
  while targeting objects or goods. No circles or world material labels return.
- Find tool now updates the retained camera heading rather than a quaternion
  overwritten on the next frame. Look/locate requests refresh native aim.
- Material preview refreshes with the native aim response and initializes
  after open. Repeated aim errors are recorded once per reason. Watching an
  AI character remains read-only and does not send ordinary pick requests.

This is material-colored terrain on the existing geometry, not cubic collision
steps. Terrain spacing, heights, collider triangles, native digging/work,
material laws and accounting are unchanged. Cut bands retain their actual
layer colors. No new ore harvesting or fracture capability is advertised.

### Verification

Windows, Node 22.18.0, Python 3.13, existing MSVC Release native binaries in
`build/agent-object-strike/Release`. Verification base: `430ab46` plus the
outgoing presentation changes; published revision is recorded in Git history.

Commands:

```powershell
cmake -S . -B build/agent-object-strike -DBANJO_BUILD_LAB=OFF
ctest --test-dir build/agent-object-strike -C Release -R '^banjo_terrain_material_tests$' --output-on-failure
# Set BANJO_LIVE_ENGINE/BANJO_LIBRARY/BANJO_BUILD_DIR to that Release directory.
python -m unittest discover -s tests -p material_preview_tests.py -k Candidates -v
node --experimental-default-type=module --check playground/world.js
python scripts/check-source-registration.py
git diff --check
```

The Node CTest runs five behavioral checks: primary color/pattern separation,
negative-coordinate/outer-axis boundaries, an analytical sloped target
perimeter, solid identification at exposed/void boundaries, and nearest-filter palette/visibility updates without mutating
input geometry. Four existing gathering-candidate checks pass: actual loose
layers, wet/absent/refused targets, thin sand exposing soil and custom tool
read-only inspection. The first Python invocation lacked its native engine
environment and failed import; rerunning with the declared environment passes.
No tolerance changed. Registration remains 297/297 with zero exclusions.

The in-app browser opens an isolated fresh generated world on port 8772. The
new shader compiles and renders with zero captured JavaScript/shader errors;
the existing shadow-filter deprecation warning remains. The World shows the
local sloped outline, Sand / Surface / Equip tool, and sand/clay/ore thumbnails.
Browser inspection does not grant material. Evidence screenshot is ignored
under `build/material-readability/terrain-target.jpg`.

These checks establish presentation and candidate boundaries. They do not
establish perceptual recognition rates, cross-GPU performance, a complete
multi-layer excavation playthrough or any new physical realism. Add actual
dig/reopen/peer evidence and frame measurements as the complete opening
journey is qualified.

## Remaining acceptance for the full owner scope

1. **Material readability:** sand/soil layers, private storage, peer geometry
   and full restart now pass the linked checkpoint. Extend recognition to
   day/night play and broader hardware/load conditions; compare finer/stepped
   presentation with measured geometry/collider agreement and cost.
2. **Opening progression:** the [personal tool checkpoint](opening-tool-checkpoint.md)
   replaces the required banking/oak-purchase/stool sequence for new players.
   Actual finite wood collection, paid 50 mm tool admission, ordinary pickup/use
   and restart pass for two players on two terrains; exhausted sources stay
   blocked. The reference AI completes this and the workshop chain on both.
   The linked ordinary browser opening now reaches the tool and work table.
   Qualify later human processing and broader supply coverage, including supported
   processing alternatives and LLM-created products; retain private evidence.
3. **Unified guidance:** one authenticated server result resolves readiness and
   the next supported action. The [shared guidance checkpoint](shared-guidance-checkpoint.md)
   now connects World, Inventory, Goals, Skills, Recipes, Market and AI Guide
   snapshots, using exact paid quote readiness for the recommended project and
   Lab review. Owned work takes priority and recovers its accepted design.
   [Selected-project/editing-chat focus](selected-project-guidance-checkpoint.md)
   now retains private intent and exact current-draft funding observations.
   Finish broader source/processor/
   empty-energy coverage; retain actual availability, ownership, skill evidence
   and native admission. A display name grants nothing.
4. **Broader physical behavior:** complete [R4/R5](player-experience-checklist.md#remaining-work).
   The retained close-arrival and packing-Q failures are resolved by the linked
   rover checkpoint. Expand pits, shores, grades, obstacles and recovery cases.
   Human and AI avatars need native ground/object/player contact and water
   buoyancy/current/drag with reactions. Cargo must contribute actual mass and
   inertia, including physical handling and retained private transfers.
   Compare declared glass/oak/iron experiments where material claims are made;
   report work, momentum/energy residuals, resolution and performance.

R1 and R6 remain open for supply coverage and broader human/model-driven
progression. R3's earlier paused repair scope is not resumed by this work.
