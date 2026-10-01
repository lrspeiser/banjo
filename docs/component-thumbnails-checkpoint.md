# Component thumbnails — October 1, 2026

The owner replaced persistent exploded inspection with component thumbnails in
the World right panel. Ordinary selection keeps the item assembled and usable.
The panel opens a bounded, scrollable gallery with a picture, component name and
material. There are no displaced component meshes or faded assembled skins on
ordinary item selection. Existing click actions and Alt+click inspection remain.

Pictures use actual reported box/cylinder parts or current native lattice cells.
Attached joints define assembly membership (64 bodies maximum); pictures are
bounded to 256 components and 16,000 cells per cellular body. Authored boxes can
label cell groups only when every reported cell belongs and every named part
retains matter. Otherwise the actual remaining body cells are shown together.
Unavailable geometry is labeled, never replaced by invented geometry.

One offscreen renderer supplies component and mini Inventory pictures. Cached
pictures belong to the world session, body geometry/revision and component;
temporary preview meshes are disposed. The selected heading and gallery DOM are
retained through live panel updates so closing/collapsing does not race refreshes.
Explicit **Show native cells** and ground-layer inspection retain their brief
3.2-second pulse. Real dismantling and physical laws are unchanged.

## Verification

Windows, Python 3.13.5, Chrome, existing MSVC Release binaries in
`build/agent-paid-machine/Release`, based on published main `6db255b`.
No native source, solver, material law or tolerance changed.
The five focused browser regressions pass (goods/recovery 2/2 in 12.158 s,
Inventory 1/1 in 7.301 s, cell/ground navigation 2/2 in 10.494 s).
Browser shutdown can cancel an in-flight HTTP response; the final checks report
no JavaScript exceptions or database cleanup failure.

- `world_goods_tests.GoodsJourney.test_component_thumbnails_keep_rover_and_pick_assembled_without_native_changes`:
  actual Alt+click selection, all 14 native rover parts across five attached
  bodies, decoded thumbnail images, unchanged scene vertices/transforms/opacity,
  persistent gallery and refreshed components. The pick's haft/arm partition
  retains all 22 actual cells. Exact native time/bodies/machines remain unchanged.
- Rover recovery browser regression: actual acquisition, lift, live readings,
  reload and release. Compact Inventory regression: pickup/stow/equip/reload,
  unchanged local geometry/mass and retained item thumbnail.
- Navigation regressions: explicit native-cell edge buffers and timed skin
  restoration, mouse close, precise solar thumbnails, reduced-motion ground
  layers and Escape. Test maps are pinned; Chrome closes before SQL fixture
  removal to prevent polling deleted databases.
- Own live `8770` preview: existing ten-body world reopens; fresh generated
  22-cell pick shows two thumbnails, then actual E pickup reaches tool-ready with
  mini Inventory and no JS exceptions. Screenshots under ignored
  `build/resource-flow/component-thumbnails.png` and `compact-inventory-preview.png`
  were visually reviewed.
- Source registration: 287/287 C++ sources registered. Markdown links and
  whitespace pass. This is presentation/identity evidence, not physics validation.

The original fourteen-item player goal remains active: four verified, ten
partial. Item 6 now uses thumbnails in place of exploded inspection. Ordinary
finite workbench, full paid progression and damaged-tool use remain next.
