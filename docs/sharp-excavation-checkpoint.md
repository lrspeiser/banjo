# Smooth hills with sharp excavation — October 3, 2026

Implemented experimental comparison on main base `416e8676`, Windows x64.
Select **Menu → New game → Ground → Smooth hills · sharp cuts · preview**.
Existing saved smooth/column worlds keep their declared geometry. This is a new
native and browser terrain mode (`terrain.surface: cuts`), not a cosmetic pit.
Migration of an existing populated world remains a separate acceptance gate.

## Representation

The generated triangular landscape supplies an immutable float32 baseline.
Within each 25 cm column, the top is that original sloping surface plus the
column's actual height change. An edit is not interpolated into its neighbors.
Cell-boundary walls join different displacements; exposed walls show actual
material runs. Tops retain smooth hillside lighting, while walls have separate
normals. Thin outlines show actual upper/lower rims and upright edges for
steps of at least 5 mm, without drawing triangle diagonals or participating in
picking/collision. Native collision, height queries, placement sampling, target markers
and drawing use the same displacement and original diagonal split.

The entire column footprint is retained, including half a cell beyond the
outer sample centers. Baseline interpolation clamps there. Each interior cell
uses eight triangles and each wall uses two segments so crossings of original
triangle planes remain exact. Edit/exploration invalidation uses existing
32-cell render chunks and native neighbor-chunk invalidation. Native collider
updates retain their existing scheduling; this does not qualify instantaneous
per-frame collision synchronization.

Ground continuation saves and checks the generated baseline. A different mode
or corrupted baseline refuses restoration. Ordinary smooth/column v5 saves
without the new optional baseline key still restore. Heights, material volumes,
tool work, densities, strengths, water equations and settling rules are unchanged.
Loose sand can still physically slump into a cut; cohesive soil and rock follow
their retained limits. No arbitrary depth multiplier or erosion timer is added.
Slow weathering/erosion is a design proposal and must transport actual material
with a receiving ledger before it can reshape a pit.

Sources: `TerrainField`, `Environment`, `live_world_run`; `cut_surface.js`,
`material_appearance.js`, `world.js`; native world generation, schema and Menu.
No new C++ file or constitutive law. Source guard: 298/298, ten CMake files,
zero deliberate exclusions.

## Verification and boundaries

CPU Release, Visual Studio 17 2022 / MSVC 19.44, Windows 11 x64,
`BANJO_BUILD_LAB=OFF`. Separate `build/agent-column-terrain` configuration, with
runtime products in `build/sharp-cuts-final/Release` to preserve running older
preview binaries. Native live engine, DLL, CLI and affected tests compile.

- Analytical sloping-field test: unchanged hill, cell-local 200 mm cut,
  unaffected neighbor, negative half-cell ownership and exact continuation.
  Field material residual bound is 1e-10 m³.
- Native rays: original valley slopes, cut tops, complete boundary-cell
  footprint and vertical walls agree within **0.1 mm**, the retained column
  valley ray bound below 1 mm run packing. A seam edit removes the old wall;
  whole reopening preserves the replacement wall exactly. Corrupt baseline
  refuses. Native material residual bound is 1e-8 m³. No retained tolerance
  changes.
- Same 120 mm glass/oak/iron cubes, same flat bed with an actual 200 mm cut,
  30 mm initial clearance, dt=1/240 s, one second. Density-derived expected
  masses are 4.32 / 1.2096 / 13.59936 kg. First gravity velocity agrees within
  1e-6 m/s; reported final vertical velocity is zero for all three. Measured
  bottom clearance is about −9.52e-8 m for each, within the retained 21 mm
  support bound. Column support comparison is retained. This is support
  evidence, not friction calibration or full reaction/work/momentum closure;
  grain, plasticity, fracture resolution and material realism remain unqualified.
- Browser geometry tests cover untouched smooth planes, sharp depth,
  unchanged neighbors, complete top area, material bands, selected-floor
  marker, matching full/chunk records and signed removal volume within
  1e-8 m³. The shipped Three chunk renderer has native-wall-equivalent ray
  distance, retains distant meshes and disposes changed seam geometry.
- Paid native pick → sand/soil exposure → private Store → peer geometry →
  complete Python/native restart passes in all three modes. The cuts journey
  uses 45 cm horizontal contact distance. Existing 5e-5 kg receipt tolerance
  remains. No grant, predicted yield or replacement inventory transfer.
- Nine focused registered suites pass, 112 checks (83.15 s for the combined
  final native run, followed by the final 23-check render rerun in 0.33 s). Water, terrain, environment FFI, native valley, hand stroke and
  the three native material journeys are included. This does not qualify the
  entire repository: the existing goal fixture failure described in
  [tool HUD checkpoint](tool-hud-checkpoint.md#existing-broader-test-failure-and-remaining-work)
  remains separate.

```powershell
python scripts/check-source-registration.py
cmake -S . -B build/agent-column-terrain -DBANJO_BUILD_LAB=OFF -DCMAKE_RUNTIME_OUTPUT_DIRECTORY=C:/Users/henry/Documents/ChatGPT/Banjo/build/sharp-cuts-final
cmake --build build/agent-column-terrain --config Release --target banjo_valley_live_tests banjo_terrain_tests banjo_live_world_run banjo_c banjo_platform_cli banjo_water_tests banjo_hand_stroke_tests --parallel 4
ctest --test-dir build/agent-column-terrain -C Release --output-on-failure -R '^(banjo_terrain_tests|banjo_valley_live_tests|banjo_terrain_material_tests|banjo_cut_material_layer_tests|banjo_water_tests|banjo_hand_stroke_tests|banjo_environment_ffi_tests|banjo_material_layer_tests|banjo_column_material_layer_tests)$'
```

## Play observation and cost

Isolated ordinary Menu world on port 8779:
`http://127.0.0.1:8779/world?world=bd899fb4d1aa4e029bb88b6ace0194ab`.
Reference character `Digging comparison` collects finite wood, pays for its
personal pick, equips and gathers, earning Gathering by hand. It is paused
after 20 decisions with a pending paid table; this is not a full-tree result.
Twenty-two additional normal authenticated tool-use requests with that owned
pick deepen the inspected point from 0.884960 to 0.731694 m. Closed per-use
receipts report roughly 1.34–1.51 kg. The inspection camera is repositioned for
viewing; it is the existing reported-pose camera, not physical avatar traversal.
The owner's original world, inventory and Lab draft are not migrated.

One 156×125 packet / 25 cm cells adds 78,000 raw baseline bytes to full terrain
catchup (base64 expands that payload); local patches retain their old wire form.
Top triangles are 156,000 against 38,440 in legacy smooth terrain. The final shipped renderer
constructs the actual Three meshes in **181.02–221.42 ms full /
9.47–11.06 ms for one changed chunk**, five serial samples on the restored native
packet, Node on this host. Full construction has 470,430 triangle vertices across
20 chunks, including 156,000 top triangles; rim line vertices are separate.
These are CPU mesh construction, not WebGL/GPU elapsed time, cloud cost or
multiplayer capacity. Initial loading is a concrete remaining optimization;
this mode is not promoted to default.

The matched preview was fully restarted onto the final native products. The
existing spectator cold-start gap still requires the world to be opened before
Watch can reconnect; this checkpoint does not repair it. Daylight and night
rendering were observed, but the unlit night view remains difficult to read.
Screenshot: `build/construction-preview/sharp-excavation.png`. No screenshot,
local saves, build products or credentials are included in Git.

## Next acceptance

1. Owner comparison of the cut rim, repeated progress and material recognition;
   fresh human play on both generated maps at day/night.
2. Review a reversible existing-world migration with original save backup,
   candidate whole-restore admission, private receipts and active peer recovery.
3. Qualify underground openings, shoreline/water, supports/removal, stepped
   hauling and native avatar/cargo traversal before broader adoption. R3 remains
   owner-paused and wider construction/R4/R5 acceptance remains unfinished.
4. Optimize full mesh creation/upload against measured costs; erosion needs
   a separate material-transport model and tests.
