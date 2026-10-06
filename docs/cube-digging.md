# Digging on cube ground

**October 5 audit:** The cube path below is a gameplay extraction approximation, not constitutive voxel fracture. Its fixed 26 J and one/three/ten-click counts are not contact-measured work. Host piles and static cone pictures are aggregate ledger representations. Cosmetic material-flight cubes have been removed. See [ground matter audit and replacement contract](ground-matter-audit.md) for the physical source/fragment/tool requirements and outstanding native rewrite.

October 4 follow-up: [owner demo, clicked faces and saved-world upgrade](cube-targeting-checkpoint.md).

The owner's calls of 2026-10-04: digging should feel like Minecraft ("an entire cube goes away pretty fast so you can see your progress"), clicks must keep up ("not queue up way behind me"), and dug walls hold until braces exist. This note says how that works now.

## What a player sees

New worlds are 25 cm cubes (the "Material cells · 25 cm" ground). With a digging tool such as the field pick in hand:

- **One click takes one cube.** Soil or sand: the whole cube you point at comes out at once, 25 kg of it. Clay takes 3 clicks and rock 10. The message says how far through the cube you are ("Rock: 40% broken through").
- **Clicks keep up.** A click is answered in tens of milliseconds. While one click is being handled, the next one waits, and a newer one replaces it. It aims where you are looking when it runs. Clicks never pile up behind you.
- **The clicked cube leaves.** A top click deepens that column; a wall click removes its visible vertical band and can retain a roof. Dug walls hold. Caving in comes back once braces can be built: [bracing-plan.md](bracing-plan.md).
- **Reach.** Any cube from 0.25 m to 4 m in front of you.
- **Piles.** What you dig goes to a pile beside or behind you, never within 1 m of a hole you have dug recently. It is drawn at its real size: a cone of loose earth at its natural slope, growing taller once it is 0.6 m across. With an empty hand, click a pile to collect it into your inventory. With a pick in hand, a click digs, even past a pile.
- **The square under the cursor** turns green when the spot can be dug. It is judged by the cell and its height, and it tolerates the sway of your body's eye (25 cm).

## How it works

- **One engine call per click.** On cube ground the outcome of a swing is decided in advance, so `tool_use._strike_cell` sends the engine one `strike-cell` command. Before this, each click physically lifted, turned and lowered the pick, waited for it to settle, then swung it: 0.5 to 3 s a click. `strike-cell` is not part of `/api/live/act`, so a page cannot get round the reach checks.
- **`ToolTerrain::strikeCell`** (src/fastlattice/ToolTerrain.cpp) finds the column under the aimed point:
  - Soil, sand or loose soil: it digs that column one cell deep, through `Environment::dig`, and the cube is carried at its real mass.
  - Rock or clay: it pays a third (clay) or a tenth (rock) of the cell through `Environment::chip`, which takes the cell out once it is paid for.
  - Either way it writes a closed ground record, the same as a swung tool's. So piles, receipts and learning ("Gathering by hand") follow unchanged.
  - A shared face resolves 2 mm into the solid column along the sight line. Wall clicks preserve height; previews and markers agree. Soft face cuts retain material-bearing roof runs around their void.
- **Walls hold.** `TerrainField::relax` returns at once on cube ground, so nothing slumps.
- **Saves.** A swing asks for a save, which happens at the next page step, at most every 2 s. A save the engine had to put off, because a stroke was under way, is retried within 0.5 s. The engine part of a save now takes about 36 ms (was 180 ms), because the 2.9 MB of ground in the snapshot is passed through as text rather than parsed and written out again.
- **Smooth and sharp-cut ground** keep the physical swing: there the point's depth, the pry and the breakout model still decide what comes loose ([ground-work.md](ground-work.md)).

## Tests

- `tests/ground_work_tests.cpp`:
  - a swing takes a whole cube out of cube ground;
  - a swing takes out the cube aimed at.
- `tests/material_preview_tests.py`: digging through sand to soil on cube ground, with piles and what another player sees.
- `tests/player_regression_tests.py`, the dig journey: real clicks on a real page. It checks replies within 400 ms, the first full top cube, receipt against each later clicked point, unclicked columns unchanged, at most one use in flight, piles clear of the digger, and the player stays put. Native wall tests separately qualify full cubes, material ledgers, roofs and saved holes. See [player-regression.md](player-regression.md).
