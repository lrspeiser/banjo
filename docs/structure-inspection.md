# Selected structure and voxel resolution

## Interaction contract — September 30, 2026

Clicking an object pins its analysis and actual component thumbnails in the right
rail, keeping its assembled skin in the world. [Thumbnail acceptance](component-thumbnails-checkpoint.md)
replaces the earlier persistent exploded view. **Show native cells** explicitly
starts a 3.2-second skin/cell pulse; Escape, closing or changing selection removes it.
**Alt+click** inspects without primary Use, pickup or dropping a carried item.
Ordinary clicks retain their existing game actions; a tool's ordinary click
still uses the tool. Reduced-motion users receive a static, temporary reveal.

The analysis uses short name/value fields: material, reported mass, structure,
cell/part count, cell width and attached connections. Existing battery pictures,
machine status and available action keys remain. Anchored bodies whose native
pose reports zero mass say **Fixed · not reported**, rather than suggesting they
contain no material. Rigid assemblies say **No cell fracture**. Cellular bodies
say **Tool dependent**, not a promise that every tool can break every material.
There is no new dismantle command or fracture law.

### Authoritative geometry

- Cellular bodies use native cell centres, not a grid reconstructed from the
  skin or bounding box. Hull cells already received in pose packets are retained
  across pose-only updates. Intact boxes use the new read-only `structure` query.
- Precise rigid assemblies show thumbnails of their actual box/cylinder parts; they are
  never presented as fracture voxels. Authored finishes remain the normal view.
- Ground remains a layered height field. Its reveal is one actual native column,
  drawn at reported depth and width through the surface. The right-hand core log
  retains its explicitly broken scale for readability. Ore presence, depth and
  combined thickness are reported; no resource mass or reserve is guessed.

Native `LiveWorld::structureJson` reports name, geometry revision, cell width,
cell count, completeness and centres in the body's reported facing frame. It
rejects absent/parked bodies. Above 16,000 cells it returns the count with
`complete: false` and no cell array; the UI refuses a partial structural picture.
This is a selected-body query rather than adding intact-body cell arrays to every
world update. Python validates the name and session and existing named-world
authentication applies. Funded rooms and Expedition allow the read-only query.
The optional in-process lane has no structure-query binding yet and reports it
unavailable; it must not invent replacement cells.

There is one inspection request in flight. Cached results belong to the current
body entry/revision; replies from previous selections or replacements are ignored.
Removal, pending/new geometry and ground-layer changes invalidate the overlay.
Overlay line buffers and temporary materials are disposed after the
pulse. Skin swaps occur only inside rendering and are restored in `finally`,
including when a held-item transparency effect is also active. Selection does
not step the simulation, change collision geometry, spend energy or alter stock.

## Cost of halving cell width

Assume the same solid volume and physical dimensions, with width `h` becoming
`h/2`. This differs from reducing the number of cells by half.

| Quantity | Approximate scaling | Boundary |
| --- | --- | --- |
| Occupied 3D cells and per-cell state | 8× | Boundary sampling can differ for thin/curved features. Not all application memory. |
| Unmerged exposed surface faces | 4× | Greedy merging, skins and parts affect actual draw work. |
| Active cell solver work at the same step | About 8× | Depends on law, contacts, bonds, parallelism and active regions. |
| Active cell work if stable timestep must also halve | About 16× | Conditional estimate, not a measured Banjo throughput result. |
| Independently halved height-field spacing | 4× columns | Terrain spacing is separate from body cell width. |

Intact movement uses rigid bodies, and cell mechanics become active for specific
work such as fracture. Therefore these ratios do **not** imply eight times the
whole game's frame time, hosting bill or Render instance size. A deployment cost
estimate needs representative active-fracture/thermal workloads, concurrency,
memory, network and wall-time measurements. The current scene-cell admission
budget also matters: an approximately 2,000-cell solid could consume 16,000 cells
after refinement. Finer body cells do not automatically improve terrain silhouettes
or pixel aliasing. No production grid, timestep, admission limit or material law
is changed by this checkpoint.

### Measured geometry comparison

Windows 11, MSVC 19.44, Release CPU parallel reference, the same axis-aligned
`0.32 × 0.16 × 0.08 m` box, zero simulation steps:

| Material | 40 mm cells | 20 mm cells | Mass at either width |
| --- | ---: | ---: | ---: |
| Glass | 64 | 512 | 10.24 kg |
| Oak | 64 | 512 | 2.8672 kg |
| Iron | 64 | 512 | 32.2355 kg |

Each count increases exactly eightfold. Native mass remains within `1e-10 kg`;
this tolerance is for the unchanged grid-aligned mass calculation, not a new
physical conservation gate. No elapsed fracture time, strength, bending, grain,
plasticity, cross-GPU determinism or refined-law accuracy was measured.

## Verification and remaining gates

Sources: `playground/world.js`, `world.css`, `live_session.py`, `server.py`,
`src/fastlattice/LiveWorld.*`, `tools/live_world_run.cpp`.

`tests/live_world_tests.cpp --structure` checks native glass/oak/iron under the
same 20 mm, 30-degree turned-plank conditions (2,490 cells per material), unchanged
serialized physical snapshots before/after inspection, facing-frame bounds,
parked-body refusal, refinement counts/mass and the over-budget empty-array rule.
There is no time advancement and no conservation transfer to certify.

The new Windows Chrome/native journeys in `tests/workshop_navigation_tests.py`
check the actual GPU line vertices against native centres and twelve orthogonal
cube edges without triangle diagonals, skin restoration,
body-transform following, replay/close, switching to precise parts, native layer
dimensions, Alt+click, Escape, reduced motion and unchanged native time/machines/
bodies/ground during inspection. The AI watch browser journey also permits this
read-only query while retaining control/input restrictions and unchanged native
state. Screenshots are under ignored
`build/workshop-navigation/world-*-reveal.png`.

Build: separate `build/agent-xray`, `BANJO_BUILD_LAB=OFF`, Release targets
`banjo_live_world_run`, `banjo_platform_cli`, `banjo_live_world_tests`; existing
running app binaries were kept open. Verification logs remain under ignored
`build/xray-*.log`. Existing native source-registration and floating-point audits
remain required. Published revision is recorded in Git history and the handoff.

Results: all 35 existing native live-world checks pass, together with the new
structure checks included in that target; 10 screen-navigation, eight world
pointer/selection and one AI-watch Chrome journeys pass. Both reveal journeys
were rerun after replacing triangle wireframes with cube/part edges. Source
registration reports all 286 C++ sources registered. JavaScript/Python syntax,
changed Markdown links and whitespace checks pass. An early empty-Lab test read
the placeholder before its asynchronous invalid-source route cleanup; it now
waits for cleanup. The fade assertion now waits for the fade plateau rather than
sampling mid-ramp. Neither change alters a physical tolerance. Existing aborted
HTTP response logs during test reloads remain browser request cancellations.

Next gates: wire the optional in-process inspector; benchmark large selected-body
reveals on low-end GPUs; measure realistic multi-player fracture/refinement costs;
offer tool-specific cutting/dismantling guidance from validated capabilities
before naming a particular tool as effective. Running older backends require a
restart onto this checkpoint to serve the new intact-body query; the browser
reports unavailable when the endpoint is unsupported.
