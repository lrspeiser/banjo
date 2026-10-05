# Cube targeting and saved-world repair — October 4, 2026

Source base: main `1676570a`; this note accompanies the outgoing main checkpoint.
Windows, Python 3.13, MSVC Release; native build and actual Chrome mouse input.
Runtime products: `build/pickaxe-preview/Release`.

## Findings and changes

The owner's actual port 18890 served a separate `C:/play` checkout at
`8542ee80`. Its existing world used smooth terrain, so it ran slow physical
strokes despite the newer column-world default. Updating another demo did not
update this one. The app also hid markers on walls, host/native strikes replaced
clicked height with column-top height, and the wire protocol omitted rock volume
and partial progress. Rock could leave while the UI reported zero progress or
no yield.

`tools/upgrade_cube_world.py --room <saved room.json> --build <Release>` explicitly
upgrades a stopped server's paired surface declarations and digest. It verifies
whole native restore and unchanged terrain, water, body, hand and energy state,
keeps original bytes in `.before-cube-digging`, and refuses mismatched/racing
saves. No map regeneration, inventory reset or resource grant.

Shared faces resolve 2 mm into solid along the sight line. Preview, green marker,
material identity and strike preserve clicked height. Native strikes use the
actual field, including streamed regions. Soft roofs retain source material in
runs around the clicked void. Flat/older bed storage grows within the existing
14-bed limit plus two surface layers. Rock receipts now carry volume, mass and
progress; collection feedback accepts rock.

## Measured evidence

- Source registration: all 300 sources registered, no exclusions.
- Native ground-work suite passes. Identical held glass/oak/iron experiments on
  soil, sand and rock walls remove exactly `0.25³ = 0.015625 m³`: 25 kg soil/sand,
  37.5 kg rock. Roof, floor and neighbor remain. Per-material volume residuals
  are zero within `1e-10 m³`; expanded bed state restores hole and ledger.
  Existing wet-channel comparison uses dt `1/240 s` and water/ground residuals
  below `1e-10 m³`. Immediate strikes themselves do not advance the clock.
- Terrain 17/17, the streamed-region held-pick test, 11 migration/protocol tests,
  39 host tool tests and 32 render/client tests pass. Wire tests compare
  glass/oak/iron: 10–90% progress, then one rock cube, owned by Alice.
- Five player journeys ran: walk, rover, Workshop and selection passed; dig
  passed in an isolated rerun after the previously observed view-relocation
  flake. Six east-facing clicks at 250 ms cadence answered in 40–70 ms, one use
  in flight. The dig gate now compares each receipt to its clicked point and
  unclicked columns. A fixed ray can meet a wall after a top cube leaves;
  requiring every later click to deepen the original column would reintroduce
  redirection. No timing tolerance changed.
- Actual owner Chrome world: green vertical marker, ten clicks showing 10–90%,
  then `Dug 37.5 kg · Rock → nearby pile`; clicking Collect added exactly
  37.5 kg rock to that player's Inventory. Local ignored screenshots:
  `build/construction-preview/cube-wall-green.png` and `cube-wall-excavated.png`.

## Boundaries and next checks

This is the existing fixed-work gameplay abstraction: 26 J and 3 m/s per
immediate strike; soil/sand one, clay three, hard rock ten. It does not qualify
physical swing energy, bending, fracture, grain, wet constitutive laws or global
momentum/energy conservation. Column walls keep their no-slump rule. Smooth/cut
physical strokes retain their cap rules. Partial chipping progress is not saved
across restart. Water is a surface solver, not flow under retained roofs. R3
remains paused.

Next: persistent partial mining, more sites/roof directions, the body/view
relocation flake, and the separate walking timing investigation. The owner world
and inventory were preserved; one cube was mined during verification.
