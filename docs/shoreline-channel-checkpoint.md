# Shoreline drawing and cube channels — October 4, 2026

## Integration

Fast-forwarded main from `68bad3ca` to `ba0bad48` (109 commits). The checkout
had no uncommitted tracked changes. Retained the new column-world default,
native player walking, streamed regions, bottom-left navigation, bottom-right
inventory, and fast cube strikes. The separate Claude demo on port 18890 was
left running. The updated local demo uses port 8779 and its existing room store.

## Implemented

- Water is drawn on reported wet cell footprints above their own bed. The
  old renderer extended a river's level into dry neighbors and stretched
  triangles between them; excavation could expose that fabricated sheet.
  One-cell channels now have two water triangles per wet cell. Dry and unseen
  cells have none. Replaced buffers are disposed and level interpolation
  retains each cell's identity when the wet footprint changes.
- Column-world contact readiness matches the existing native `strike-cell`
  operation, which admits wet ground and rock. The server selects this from
  the saved terrain mode and still checks the owned tool point and reach.
  Material candidates use the native cell depth, so a click crossing thin
  sand into soil shows both materials. Receipts remain authoritative.
- Smooth and sharp-cut worlds keep their existing physical stroke/pry path
  and its wet-ground refusal. No constitutive laws, water solver, terrain
  collision model, or native tool response were changed.

## Measured verification

Windows, MSVC 19.44 Release, CPU reference/parallel backend, Python 3.13 and
Node 22.18. Native products were rebuilt from `ba0bad48`; changed host/render
code and the additional compiled regression are committed with this note.
Build configuration: `build/agent-column-terrain`, Lab off; runtime products:
`build/shoreline-preview/Release`.

`ground_work_tests.cpp::cubeStrikesOpenAWetChannel` uses a real held pick,
private actor accounts and saved native water state. For each of glass, oak
and iron, under identical conditions: 20×20 grid, 0.25 m cells, 0.75 m soil,
0.1 m water in the first cell, five successive strikes and two seconds of
stepping at 1/240 s. Each removed 125 kg / 0.078125 m³ of soil; Bob received
none. The neighboring bank remained unchanged and dry. Water reached the
last cut cell; final volume was 0.00625 m³, water residual
`3.98986399475e-17 m³`, ground residual `0 m³` (tolerance `1e-10 m³`).

This measures the existing fixed-work cube gameplay abstraction. It does
**not** qualify tool-material differences, wet-soil strength, erosion, or
full momentum/work/energy closure. Equal cube removal across these tools
is intentional here; density and stiffness still differ in the separately
retained physical-stroke regression.

Passing checks:

- 25 terrain/render JavaScript checks, including narrow channels, wet/dry
  topology changes, empty geometry, material bands and target feedback.
- 37 host tool-use checks, including wet columns versus smooth refusal and
  cell-depth-dependent layer candidates.
- Registered water, valley-live, ground-work, ground-work binding/MCP,
  terrain-material, tool-use and smooth/cut/column material-layer targets.
  The column layer check initially caught the missing soil candidate; it
  passes after the correction, including private storage, peers and restart.
- Source registration: all 300 sources registered; no exclusions.
- Ordinary browser on a separate new column world: Find tool → E → click
  ground produced 25 kg Sand in a nearby pile and Gathering by hand. The
  shoreline rendered with no browser errors. Screenshot:
  `build/construction-preview/shoreline-checkpoint.png` (local, ignored).

## Player gate still open

The five browser journeys were run. Rover, paid Workshop and point/click
passed. Dig initially failed at test relocation (view did not follow body);
the focused rerun passed. Walk failed acceleration timing (A: 0.602 s,
D: 0.455 s versus 0.4 s). An isolated archive of unchanged `ba0bad48` passed
dig but also failed walk stopping (A: 0.596 s versus 0.5 s). No timing
tolerances or locomotion code were changed. These failures are explicitly
retained as an existing player gate, not a claim that all gameplay passes.
Reports are in `build/player-regression/` and the isolated baseline's
`build/player-regression/`. Initial full run took 102 s; each focused
dig/walk comparison took about 47 s.

## Remaining

1. Stabilize the body/view relocation and walking acceleration/stop gate on a
   quiet machine; reproduce and measure before changing controller or limits.
2. Human playtest of digging a connected river outlet; the channel-flow
   qualification above is native, not a complete manual outlet journey.
3. Water in streamed regions, river crossing connections and unloading remain
   separate work. Current cell-based water can show level/grid seams; this
   repair removes fabricated dry water, not all cell sampling artifacts.
4. Wet physical stroke/pry, caving/bracing, calibrated wet laws and erosion
   remain unsupported or planned. R3 remains paused.
