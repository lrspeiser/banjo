# Workshop inspection integration (PR #16)

Reconciles `agent/workshop-matter-debug` at `a347cdf` with main `8d9ea50`.
The merge retains the thin-part compiler, representation selection, buildability,
measured native simulation/playback, viewport controls and current-state installation.
It does not restore the old Workshop implementation from the diverged branch.

## Behavior

- Solid CellSkin is exposed-face topology from the full canonical Matter artifact,
  with its physics/artifact hashes. Exterior-only display cannot change that topology.
- Collision and Relations are explicitly **design-contract inspection**, not native
  contact geometry or a load/strength test. Physical-skin edits invalidate that old
  contract; those views report unavailable instead of reinstating obsolete primitives.
  Canonical Matter and CellSkin remain available for the physically edited design.
- X/Y/Z section clipping changes rendering only. It does not remove mass, cut matter,
  or invalidate an otherwise unchanged physical artifact. Precise-rigid Matter keeps
  its exact collision boxes instead of being replaced by CellSkin from a comparison grid.
- The older PR's Y-face winding is corrected. Current native playback reuses meshes
  rather than rebuilding simulation geometry each animation frame.

## Verification boundary

The 25 standalone Workshop source/API suites, JavaScript syntax check and source
registration are required. The Chrome suite includes actual control journeys for
CellSkin, contract labels, display-only clipping, physically edited geometry, and
all earlier thin-rigid/persistence/simulation cases. Runner results are recorded
separately before main promotion. This is an inspection/UI integration, not new
constitutive or fracture validation.
