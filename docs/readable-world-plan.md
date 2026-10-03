# Readable world and useful progression — October 3, 2026

Published implementation: `59f4efe` on GitHub main. This publication record
does not close the full active scope.

The [reachable-ground guidance checkpoint](reachable-ground-guidance-checkpoint.md)
removes the at-feet gathering recommendation and stale Inventory-action pose.
Current-source HTTP/native openings follow the same reachable ground target
as shared guidance for both owners on both terrains, then retain paid evidence
through restart. Ordinary browser gathering shows sand/skill/Inventory/Goals
agreement and reload. Exposed-layer/peer and complete fresh human acceptance
remain open.

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

1. **Material readability:** qualify exposed layers and stock/crosshair/Inventory
   consistency through actual gathering and reload. Check day/night readability
   and performance on declared hardware; retain geometry/collider agreement.
2. **Opening progression:** the [personal tool checkpoint](opening-tool-checkpoint.md)
   replaces the required banking/oak-purchase/stool sequence for new players.
   Actual finite wood collection, paid 50 mm tool admission, ordinary pickup/use
   and restart pass for two players on two terrains; exhausted sources stay
   blocked. The reference AI completes this and the workshop chain on both.
   Qualify the human journey and broader supply coverage, including supported
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
   Reproduce and fix the existing rover failures before expanding terrain cases.
   Human and AI avatars need native ground/object/player contact and water
   buoyancy/current/drag with reactions. Cargo must contribute actual mass and
   inertia, including physical handling and retained private transfers.
   Compare declared glass/oak/iron experiments where material claims are made;
   report work, momentum/energy residuals, resolution and performance.

R1 and R6 remain open for supply coverage and broader human/model-driven
progression. R3's earlier paused repair scope is not resumed by this work.
