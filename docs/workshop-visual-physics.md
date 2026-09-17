# Workshop visual physics, matter and skins

This is the visual contract for Workshop. It keeps four representations separate:

- **Wire** — semantic design intent and component geometry.
- **Matter** — the actual discrete cells compiled for detailed material physics.
- **Skin** — editable render geometry bound to a component; appearance-only skins add no physics.
- **Physics** — recorded states from an isolated engine trial, rendered back in the Workshop viewport.

The rule is: **the picture may be prettier than the cells, but it may not pretend the cells are something they are not.** A skin change marked `physical` changes the matter compilation; an appearance-only change does not.

## Implemented slice

`mcp/workshop_visual.py` defines:

- `banjo.product-skin.v1`
- `banjo.workshop-matter.v1`
- block, round and cubic-Bezier tube skin profiles
- appearance controls (`roughness`, `metalness`, `color`)
- `physical` skin edits that are sampled onto the Workshop cell grid
- sparse physical-cell previews with component/material identity and an explicit surface error bound

`playground/workshop_recording.py` defines `banjo.workshop-physics-run.v1`. It transparently records isolated LiveWorld states without changing solver calls. Functional bench tests and the declared static-load trial can therefore return the same measured evidence plus a time-ordered body/joint recording.

`playground/workshop_api.py` decorates candidates with their skin document and accepts:

```json
{
  "skin_edit": {
    "part_name": "handle",
    "scope": "this",
    "skin": {
      "profile": "curve",
      "bend_m": 0.12,
      "physical": true,
      "roughness": 0.45
    }
  }
}
```

A visual plan request returns skin plus cells:

```json
{
  "kind": "cart",
  "design_id": "cart-g1-v1",
  "parameters": {},
  "component_overrides": {},
  "visual": {
    "cell_size_m": 0.04,
    "exterior_only": true
  }
}
```

The response's `matter.cells` are positioned in product space and carry `component`, `material`, `center_m` and whether the cell is exposed.

## Physics playback

The Workshop bench marks tests that have `visual_playback`. Current engine-backed recordings include:

- cart rolling
- kettle heating
- powered machine operation
- the product's own declared static-load trial for table/stool/bench/chair/shelf/cart designs

Playback is evidence from the isolated scratch world, not a JavaScript animation. The outside world does not advance.

## Curves

Curves exist at two independent levels.

### Curved skin

A `curve` skin is currently a cubic Bezier tube whose four local control points are derived from component height plus `bend_m`. The renderer may draw it smoothly at arbitrary visual tessellation.

### Curved matter

With `physical: true`, that same parametric tube is sampled onto the cell grid. Matter is therefore stair-stepped at coarse cell sizes and converges toward the curve as resolution increases. `surface_error_bound_m` reports the half-cell-diagonal sampling bound.

Future skin operators should add sweep, lathe, profile/extrusion, fillet/chamfer and arbitrary Bezier/Catmull-Rom control points without making product-specific geometry classes.

## Important current limitation

The new Matter view is an honest deterministic preview, but the current scratch-engine scene ABI still accepts the existing primitive/reduced body adapters rather than an externally supplied sparse cell list. Therefore a curved physical skin is voxelized for inspection now, while engine-backed Workshop trials still use their existing test adapters.

The next engine slice is a sparse compiled-body scene/API entry point carrying at least:

```text
cell_size
cell positions/indices
material/component identity
pose
optional stable cell ids
```

Once that exists, the same `banjo.workshop-matter.v1` compilation should feed both the visible Matter view and the detailed physics trial. Until then the UI must label the distinction rather than imply that a curved voxel preview has already been exercised by the engine.

## Acceptance

A Workshop build is correct when:

1. Matter mode visibly displays cells rather than translucent design primitives.
2. Skin mode can show a curved skin while Matter shows the cell approximation underneath it.
3. Appearance-only skin edits leave candidate mass/physics evidence unchanged.
4. Physical skin edits invalidate/rebuild Matter.
5. A visual-playback test supplies recorded engine frames and can be paused/scrubbed in Workshop.
6. Fracture/topology-changing recordings never keep drawing an intact skin across bodies that the engine has separated.
7. The UI reports cell resolution and the skin-to-matter error bound.
