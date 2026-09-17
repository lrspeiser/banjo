# Workshop visual physics, matter and skins

Workshop keeps four representations separate:

- **Wire** — semantic design intent and component geometry.
- **Matter** — the canonical discrete cells compiled for detailed material physics.
- **Skin** — editable render geometry bound to a component; appearance-only skins add no physics.
- **Physics** — recorded states from an isolated engine trial, rendered back in the Workshop viewport.

The invariant is stronger than “they look similar”: **the Matter cells shown to the user are the Matter cells handed to detailed physics.** A skin may be prettier than the cells, but it may not imply physical geometry the solver did not receive.

## Canonical Matter v2

`mcp/workshop_visual.py` defines `banjo.workshop-matter.v2`. Matter is compiled directly on Banjo's shared engine grid:

```text
cell (i,j,k) center = ((i+0.5)h, (j+0.5)h, (k+0.5)h)
```

Each returned cell carries:

- integer `grid` coordinates;
- world `center_m` derived from those coordinates;
- `material`;
- primary `component` and all contributing `components`;
- `exposed` and exact `exposed_faces` (`+x`, `-x`, `+y`, `-y`, `+z`, `-z`).

The artifact also carries:

- `physics_hash` — cell coordinates + physical material, independent of UI filtering/component labels;
- `artifact_hash` — physical cells plus component identity;
- `surface_error_bound_m` — the half-cell-diagonal sampling bound;
- `engine_ready: true`.

`exterior_only` changes only which cells are sent to the renderer. It cannot change either hash or the authoritative `total_cells` set.

Cross-material overlap is refused. Two different materials claiming the same physical cell require an explicit interface law rather than silently allowing one material to win.

## Editable skins and curves

`banjo.product-skin.v1` remains separate from Matter. Current profiles are block, round and cubic-Bezier tube, with appearance controls (`roughness`, `metalness`, `color`).

A curve with `physical: false` changes only the skin; its Matter `physics_hash` must remain unchanged. With `physical: true`, the same parametric tube is sampled onto the shared cell grid and therefore changes the canonical physics hash when its occupied cells change.

Future skin operators should add sweep, lathe, extrusion/profile, fillet/chamfer and arbitrary Bezier/Catmull-Rom control points without creating product-specific geometry classes.

## Exact Matter -> engine bridge

The engine already has the needed physical generator: `generateVoxelLattice(VoxelRecipe)` consumes arbitrary occupied grid cells. The legacy scene JSON does not yet have a compact `shape: "voxels"` field, but joined grid-aligned boxes are already voxelised onto that same global grid and unioned before `generateVoxelLattice`.

`playground/workshop_sparse_trial.py` therefore uses a lossless compatibility bridge:

1. Take the exact `banjo.workshop-matter.v2` cell set.
2. Greedily decompose it into non-overlapping integer-grid rectangular runs.
3. Reconstruct the set from those boxes and require exact equality before starting the engine.
4. Encode each run as a grid-aligned box with one common `join` name derived from `physics_hash`.
5. Let the existing scene engine union those boxes and pass the resulting occupied cells to `generateVoxelLattice`.

This is **not a geometric approximation**. It is an exact encoding of the same cell set. If decomposition does not round-trip, the test refuses to run.

A future native sparse-body scene/API entry point is still desirable because it will be smaller and faster than the box encoding. It is no longer required to guarantee geometry identity.

The current exact fused static-load path intentionally supports one material. The existing join group has one material definition; fixed mixed-material assemblies need explicit per-material interface behavior before they can truthfully become one lattice.

## Physics playback

`playground/workshop_recording.py` defines `banjo.workshop-physics-run.v1`. It records authoritative isolated LiveWorld states without changing solver calls. Current visual playback includes cart rolling, kettle heating, powered machine operation and the product's declared static-load trial.

For the declared static-load trial, result metadata records the canonical Matter hashes, number of Matter cells, exact decomposition box count, and `matter_roundtrip_exact`. The test mass itself is quantized to whole lattice cells; requested and actual grid mass are both reported.

## Acceptance

The exact-Matter slice is correct when:

1. Matter mode displays cells from `banjo.workshop-matter.v2`, with integer grid identities.
2. Exterior-only display filtering leaves `physics_hash`, `artifact_hash` and `total_cells` unchanged.
3. Appearance-only skin edits leave the Matter physics hash unchanged.
4. Physical skin edits rebuild Matter and change the hash when occupancy changes.
5. The engine adapter reconstructs exactly the same occupied cell set before a test begins.
6. A static-load result names the same Matter `physics_hash` the viewport received.
7. No primitive/taper substitution is used for the product under exact-cell testing.
8. Mixed-material fused Matter is refused until explicit interface laws are available.
9. Physics playback remains an engine recording, never a scripted JavaScript animation.

## Remaining visual work

This slice closes the highest-priority geometry-identity seam. Still outstanding are richer CellSkin display modes, collision/relationship debug views, section clipping, broader generic tests, more skin operators, draggable 3D curve handles, smooth surfaces reconstructed from Matter, skin-to-matter error heatmaps and topology-aware reskinning after fracture/cutting.
