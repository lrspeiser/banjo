# Material-column terrain comparison — October 3, 2026

Implemented/experimental on main base `04d39af`, Windows x64. This is an optional
25 cm terrain geometry comparison with matching native collision. It does not
qualify the complete readable-world/progression/physical-behavior goal. R3 remains
owner-paused. Publication revision is recorded below after verification.

## Behavior and architecture

**Menu → New game → Ground → Material cells · preview** generates a new world
with `terrain.surface: columns`. Smooth slopes remain the default; older worlds
without this declaration remain smooth. Existing user servers are unchanged.

Each actual layered column has a flat top and exposed vertical walls. Native Jolt
mesh patches and browser geometry follow the union of solid intervals, including
underground floors, roofs and openings. Material runs still drive face identity.
This is layered-column terrain, not independently simulated cubes or a new cubic
vertical resolution. Excavation, settling, water equations, density and material
laws retain their existing implementations. Collision consequences can change
because the contacted surface has changed.

Neighbor chunks rebuild when a wall changes at their seam. Saved geometry mode
survives continuation and subprocess reopening; mismatched declared/saved modes
are refused. Full terrain catchup preserves the existing mesh, water and explored
cells when mode/grid agree, and rebuilds for a mode change. The wire protocol
retains heights/runs rather than transmitting an expanded mesh.

The real paid-tool test caught `TerrainField::restore` reconstructing a smooth
candidate despite the declared column mode. The fix preserves the declaration
through the candidate restore. The exact staging-preservation guard is retained.

Sources: `TerrainField`, `Environment`, `JoltWorld`; `live_world_run`;
`material_appearance.js`, `world.js`; world generation/server/menu; native and
material-preview tests. No unregistered C++ source was added.

## Verification

Separate `build/agent-column-terrain`, Visual Studio 17 2022, MSVC 19.44.35228,
Release x64, CPU reference, `BANJO_BUILD_LAB=OFF`. Pinned existing dependency
sources are reused; build products are separate. Live engine, C API DLL,
platform CLI and all affected test targets compile. Source guard: **298/298**.

Ten registered suites pass **139 checks**: water 21, terrain 16, environment FFI
15, material presentation 12, native valley 23, hand stroke 9, material delivery
8, tool use 33, smooth layer journey 1, column layer journey 1 (65.33 s combined).
Commands:

```powershell
python scripts/check-source-registration.py
cmake --build build/agent-column-terrain --config Release --target banjo_valley_live_tests banjo_terrain_tests banjo_live_world_run banjo_c banjo_platform_cli banjo_water_tests banjo_hand_stroke_tests --parallel 4
ctest --test-dir build/agent-column-terrain -C Release --output-on-failure -R '^(banjo_valley_live_tests|banjo_terrain_tests|banjo_water_tests|banjo_hand_stroke_tests|banjo_environment_ffi_tests|banjo_terrain_material_tests|banjo_material_delivery_tests|banjo_tool_use_tests|banjo_material_layer_tests|banjo_column_material_layer_tests)$'
```

- Native flat-top and seam-wall rays: ≤2 µm. Actual valley adit breakout preserves
  floor/roof/opening and whole reopening; ray tolerance **0.1 mm**, below the
  1 mm packed-run precision. The initial new-test 0.5/2/10 µm tolerances were too
  narrow: flat ray error was about 0.7 µm, valley floor/roof errors about 2/10 µm.
  Jolt's `TriangleCodecIndexed8BitPackSOA4Flags` quantizes vertices using mesh
  bounds, including the deep column walls. No retained test tolerance changed.
  The original flat one-bed fixture cannot admit a tunnel; the revised test uses
  the generated valley's reserved beds and real adit face.
- Identical 120 mm glass/oak/iron cubes start 30 mm above the same column bed,
  dt=1/240 s. Density-derived expected masses: 4.32/1.2096/13.59936 kg. Initial
  gravity velocity agrees within 1e-6 m/s. At 1 s all have zero reported vertical
  velocity and clearance about 3.1e-7 m, within the retained 21 mm contact-slop
  bound. These are support checks, not calibrated material realism or measured
  full contact-energy/momentum conservation. Grain, plasticity and broader
  fracture certification remain unsupported by this experiment.
- Native terrain volume residuals remain within 1e-8 m³. Renderer signed union
  volume/ray tests preserve the void and actual material bands. These local
  ledgers/oracles do not establish full-pipeline conservation.
- Both actual journeys use finite wood → paid personal pick → native sand/soil
  extraction → private Store → peer geometry → full server/native restart.
  Column run: seed 7, 25 cm terrain, 50 mm manufacture, dt=1/240 s, 13 strokes,
  22.4279628734 kg sand and 3.8709449508 kg soil stored. Peer receives zero credit;
  ore reserve remains unchanged. Maximum mass delta/receipt residual is
  4.953502e-6 kg; existing receipt tolerance stays 5e-5 kg.

Ordinary Menu generation and full preview restart were exercised on isolated
port 8778. The rendered shore shows sand tiles, soil cuts and rock steps, with a
matching Sand target thumbnail. Screenshot:
`build/column-terrain-preview/material-cells.jpg`. No shader/JS errors observed;
existing shadow-map deprecation and the intentional server-stop fetch warning
remain. This is web view/input observation, not a raylib interactive-loop test.

## Preliminary cost and recommendation

One seed-7 bare valley, 156 × 125 cells, unchanged 25 cm spacing/physical extent:

| Measure | Smooth | Columns |
|---|---:|---:|
| Top triangles | 38,440 | 39,000 |
| Additional column wall/void triangles | Separate existing cuts | 113,872 |
| JSON material terrain packet | 620,650 bytes | 620,651 bytes |
| Native subprocess opening, one observation | 30.87 ms | 115.52 ms |

Column top/face helper traversal in Node took 49.4 ms cold and 42.5/20.9/16.3 ms
on subsequent passes. This excludes Three mesh creation/upload, rendering and
frame rate. It is not a cloud-cost benchmark. Current whole-map face rebuilding
is a concrete optimization target before default adoption; opening costs are
single observations, not distributions. The native realtime baseline in the
valley suite still uses smooth terrain and cannot qualify column performance.

Keep 25 cm for comparison. Halving spacing would add about 4× horizontal columns
at the same map extent, before measuring faces/contacts/water costs. Recognition
should be tested at day/night and walking distance before paying that cost.

## Next acceptance

1. Rebuild only changed/explored chunks; measure real browser frame/upload costs.
2. Compare material recognition and gathering at walking distance, dusk/night,
   across both generated terrain seeds, with human and model players.
3. Qualify rover hauling, native body traversal/contact and shoreline/water on
   steps before promoting the mode. Existing reported-pose player movement is
   still an approximation; native walking/swimming and physical cargo remain R5.
4. Continue the useful opening/supply audit and compact solar starter. Keep the
   shared next action/readiness path; remove remaining large restore diagnostics
   from ordinary chat into expandable details. The restarted preview still
   shows a verbose legacy save-boundary notice.

No complete progression, R4/R5, cross-GPU determinism, macOS or physical-world
material certification is claimed.
