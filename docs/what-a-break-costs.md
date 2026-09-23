# What a break costs

Breaking a thing should cost what breaking it costs in life. A crack of one
square metre in oak takes about a thousand joules, in glass about eight. This
records what Banjo charges instead, measured in the world's own lane, and what a
break actually takes away.

Nothing here is calibrated against a laboratory. These are the engine's own
numbers, and the point of writing them down is that two of the three are wrong.

## The two laws

A break in the world is the lattice removing bonds. Which bonds go is decided by
one of two rules (`src/material/Material.hpp`):

- **strain-threshold**, which every room runs today: a bond goes when it is
  stretched past a fixed fraction of its length, set from the material's
  strength divided by its stiffness.
- **energy-scaled**, which until now only the fracture lab could ask for: the
  removal stretch is worked back from the material's own fracture energy, the
  cell size and the horizon, so that removing the bonds that cross a square
  metre of lattice plane costs the material's fracture energy
  ([the derivation](criterion-energy-scaled-checkpoint.md)).

A room can now name either: `"failure_law": "energy-scaled"` in the room, which
the engine reads (`readSceneSettings`) and applies to every material in it. A
room that says nothing runs the strain-threshold law, as before.

## What the charge is

`N_100 / h^2` bonds cross a unit area of a lattice plane, where `h` is the cell
size and `N_100` is a property of the horizon, so one removed bond stands for
`h^2 / N_100` of new crack. Each bond holds `E h^3 s^2 / 2m` at stretch `s`.
Charging every bond that crosses a square metre at the stretch it is removed at
gives

    charge = N_100 E h s^2 / 2m   joules per square metre of crack.

That is `law_energy_j_m2` below: what the law in force charges before anything
has broken. `LiveWorld::crackCost` works it out for any body in a room, and
every break reports it beside what the break actually took.

## Measured

`tools/break_cost.py`, in the world's own lane: a 60 mm iron ball at 30 m/s onto
the middle of a 150 x 60 x 150 mm plate lying on the ground, at three cell sizes
under both laws. Plasticity off. The same strike every time.

| Material | Cells | Law | Charge for a crack (J/m2) | The material's own (J/m2) | Pieces | Bonds (pulled/crushed/sheared) | Energy out (J) | Crack (mm2) | Measured (J/m2) |
|---|---:|---|---:|---:|---:|---|---:|---:|---:|
| glass | 20 mm | strain-threshold | 6,364 | 8 | 1 | 268 (102/0/166) | 227.48 | 9,750 | 23,342 |
| glass | 20 mm | energy-scaled | 8 | 8 | 170 | 1926 (1827/0/99) | 65.28 | 70,040 | 932 |
| glass | 10 mm | strain-threshold | 3,182 | 8 | 22 | 3948 (1237/5/2706) | 588.96 | 35,890 | 16,410 |
| glass | 10 mm | energy-scaled | 8 | 8 | 1099 | 17080 (15620/0/1460) | 43.81 | 155,270 | 282 |
| glass | 5 mm | strain-threshold | 1,591 | 8 | 726 | 31814 (13426/11/18377) | 319.90 | 72,300 | 4,424 |
| glass | 5 mm | energy-scaled | 8 | 8 | 6531 | 145284 (125210/323/19751) | 719.55 | 330,190 | 2,179 |
| oak | 20 mm | strain-threshold | 148,500 | 1,000 | 1 | 68 (0/20/48) | 14.92 | 2,470 | 6,034 |
| oak | 20 mm | energy-scaled | 1,000 | 1,000 | 1 | 314 (196/12/106) | 22.31 | 11,420 | 1,954 |
| oak | 10 mm | strain-threshold | 74,250 | 1,000 | 123 | 3758 (97/400/3261) | 79.81 | 34,160 | 2,336 |
| oak | 10 mm | energy-scaled | 1,000 | 1,000 | 486 | 13473 (7442/351/5680) | 85.85 | 122,480 | 701 |
| oak | 5 mm | strain-threshold | 37,125 | 1,000 | 645 | 13398 (400/2018/10980) | 37.97 | 30,450 | 1,247 |
| oak | 5 mm | energy-scaled | 1,000 | 1,000 | 978 | 29118 (13794/1447/13877) | 38.72 | 66,180 | 585 |

"Pieces 1" is a plate that stayed in one piece while losing bonds inside itself:
cracked, not broken apart.

## What it says

**1. The law every room runs has no length in it.** Halve the cells and the
charge halves: glass 6,364, 3,182, 1,591 J/m2 at 20, 10 and 5 mm cells, against
the 8 J/m2 glass actually takes; oak 148,500, 74,250, 37,125 against its 1,000.
The charge is a property of the grid, not of the material. That is why the same
strike leaves the glass plate in one piece at 20 mm cells and in 726 at 5 mm:
the finer the cells, the cheaper breaking gets.

**2. The energy-scaled law charges the material's own, at every cell size.**
Glass 8 J/m2 and oak 1,000 J/m2 at 20, 10 and 5 mm, to the last digit. This is
the first thing that has to be true before any calibration means anything, and
the world can now ask for it.

**3. What actually leaves is still not what is charged, in either direction.**
Under the energy law glass's breaks took 932, 282 and 2,179 J/m2 of crack where
8 was charged, and oak's took 1,954, 701 and 585 where 1,000 was charged. Two
reasons, both in the table:

- A bond is removed at whatever stretch it has reached, not at the stretch the
  charge is set for. There is no softening before the snap
  (`src/fracture/BondFailure.hpp`), so a bond pulled far past its threshold
  inside one substep carries all of that energy away with it.
- Much of the damage is not a tensile crack at all. Under the strain law at
  5 mm, 18,377 of glass's 31,814 removed bonds were sheared and only 13,426
  were pulled apart; oak at 5 mm lost 10,980 in shear against 400 in tension.
  Shear and crushing thresholds come from strength, and no fracture energy sets
  them under either law.

How far out it is follows how violent the strike is. The same glass pane on
piers, hit by an iron ball under the energy law:

| Hit | Pieces | Bonds | Energy out | Measured | Charged |
|---|---:|---:|---:|---:|---:|
| 1.7 m/s | 11 | 1,399 | 0.12 J | 2.3 J/m2 | 8 |
| 2.6 m/s | 33 | 1,582 | 0.19 J | 3.2 J/m2 | 8 |
| 6.9 m/s | 206 | 2,818 | 1.12 J | 11.0 J/m2 | 8 |
| 30 m/s (on the ground) | 170 | 1,926 | 65.28 J | 932 J/m2 | 8 |

A gentle break takes less than the charge, a violent one far more. Neither is
the material's number, and a calibration fitted at one speed would be wrong at
every other.

**4. The law decides what it takes to break a thing, not only what it costs.**
The same oak plank on the same piers, struck by the same ball: under the
energy-scaled law it is admitted for breaking above 3.1 m/s, and under the
strain-threshold law above 11.0 m/s (2.7 and 11.0 before the crack bound in
point 6 below; the stress bound is still the harder of the two under the strain
law). The admission bound is a stress-wave
argument built on the smallest strain at which a bond is removed
(`src/fastlattice/Refracture.hpp`), and the two laws set that strain differently
-- so which law a room runs changes whether a blow breaks anything at all. A
200 mm iron ball dropped 1.5 m carries about 500 J into a 40 mm plank spanning
320 mm; that it snaps is the believable answer, and it is the energy law that
gives it.

**5. The same report catches the engine making energy.** In the glass room a
piece that had already fallen was struck again and the break reported 349.40 kJ
removed -- from a ball whose whole fall carried about a joule. That is the
at-rest energy gain the [convergence study](convergence-study-checkpoint.md)
records (up to 1.28e9 J from a lattice at rest), now visible in the world
rather than in a sweep, because every break says what it cost.

**6. A thing's bar for breaking now depends on how big it is.** Before a
break can cost anything it has to be allowed, and the trigger that allows it
asked two questions (`src/fastlattice/Refracture.hpp`): can the stress wave the
contact sends into the piece reach the strain at which some bond is removed, and
is the contact carrying at least one bond's worth of energy. Neither question
has a size in it. Every piece of oak in the world therefore had the same bar --
2.7 m/s struck by that iron ball -- whether it was the whole plank or a chip
off one, which is why a room full of debris went on breaking as it landed.

Coming apart is not removing one bond, though. It is opening a crack across the
piece, and the material says what that costs: its fracture energy Gc, in joules
per square metre of new crack. The cheapest way to separate a piece is across
its thinnest part, so a contact that cannot pay

    Gc x (the thinnest slice of cells through the piece)

cannot break it, whatever else is true. That is Griffith's statement of the same
idea as the one-bond bound, taken against the whole crack instead of one bond of
it, and it is now the third thing the trigger asks. Measured by
`banjo_refracture_tests` from oak's own catalogue number, 1,000 J/m2, at 20 mm
cells, landing on something much stiffer so the piece's own mass is what the
pair has:

| oak cube | thinnest slice | a crack costs | its mass | so it needs |
|---|---:|---:|---:|---:|
| 40 mm | 16 cm2 | 1.6 J | 0.045 kg | **8.5 m/s** |
| 60 mm | 36 cm2 | 3.6 J | 0.151 kg | **6.9 m/s** |
| 80 mm | 64 cm2 | 6.4 J | 0.358 kg | **6.0 m/s** |
| 120 mm | 144 cm2 | 14.4 J | 1.210 kg | **4.9 m/s** |

Small things are harder to break, which is the everyday fact the old trigger did
not have: the crack a piece has to open shrinks as the square of its size while
what it carries shrinks as the cube. In `tests-break` the plank's bar went from
2.7 to 3.1 m/s, one of the seven pieces it broke into asks 3.4 m/s, and a piece
of that piece asks 8.5 m/s -- the ground hit it at 11.5 m/s and it held.

What the bound is not: it is necessary, not sufficient -- the lattice still
decides, and a piece above its bar often holds. It is a lower bound on the crack
as well, because the thinnest slice is the cheapest cut there could be, so
chipping a cell off a corner is still admitted. It uses the material's declared
Gc, not the charge the room's law makes for a crack: under the strain-threshold
law that charge is 148,500 J/m2 for oak at these cells, a property of the grid,
and gating admission on it would stop the world breaking anything at all. And a
material that declares no fracture energy is not bounded by it.

What it did not change: all 96 cases of the material ladder
(`docs/evidence/material-qa-baseline.json`) stay inside their bands; the break
room's own break is the same 7 pieces, 419 bonds, 4.47 J over 152 cm2; and a
100 mm ball of all eight materials dropped on concrete is quoted the same bars
to the last digit as before ([materials](api/materials.md)), because a ball that
size carries far more than its own crack costs.
What it did not fix either: the plank piece that the 33 kg ball drives into the
ground at 10.2 m/s still comes apart into 83 pieces. That contact can pay for
its crack nine times over, so the trigger is right to admit it; 83 pieces from
one landing is the run's own over-fragmentation, and it belongs to item 2 below.

## What this does not show

- Nothing about real glass or real oak. The materials' own numbers in the table
  are catalogue values with no citation behind them
  (`src/material/MaterialCatalog.cpp`), which is its own piece of work.
- The piece counts still do not converge: glass goes 170, 1,099, 6,531 pieces
  under the energy law as the cells shrink. That is a separate, documented
  defect ([convergence study](convergence-study-checkpoint.md)).
- The measured column divides the energy that left by the area of **all** the
  removed bonds, sheared and crushed ones included. It is the cost of the
  damage, not of a mode-I crack alone.
- Cost of the runs: the 5 mm rows took 26 to 40 seconds of wall clock for about
  a fifth of a second of world.

## The order this sets

1. A law with a length in it, reachable from a room. **Done**: a room can ask
   for `energy-scaled`, and the charge is then the material's own.
2. Close the gap between the charge and what leaves: soften the bond before it
   goes, or remove it at its threshold rather than past it, and give shear and
   crushing an energy of their own.
3. Flaw statistics, so that a plate has a strength that scatters as real panes
   do, instead of one number.
4. Only then, the laboratory comparison: the drop-tower series already filed in
   [`assets/benchmarks/glass-drop-reference.json`](../assets/benchmarks/glass-drop-reference.json)
   ([notes](glass-drop-benchmark.md)), whose status is still `not_run`. Those
   panes are toughened; the engine has no toughening, so the honest comparison
   needs that too, or an annealed series.

## Watching one

`/world?scene=tests-break` is an oak plank bridged between two iron piers with
a 200 mm iron ball a metre and a half above it. Nothing to do: the ball lands at
5.2 m/s, above the 3.1 m/s the plank can take, and the room says

> ball hit plank at 5.2 m/s (it bends above 8.3 m/s, breaks above 3.1 m/s). It
> broke into 7 pieces. It cost 4.47 J over 152 cm2 of new crack: 294 J/m2,
> where oak itself takes 1,000 J/m2 and this room charges 1,000 (energy-scaled).

It is the only room that runs the energy-scaled law. Every other room says the
same sentence with the strain-threshold charge in it, which is where the 148,500
and the 6,364 above will show up.

Oak rather than glass, because glass is admitted for breaking at 0.2 m/s here:
its pieces break again as they fall and land, and the cascade buries the number
the room is for. Glass declares 8 J/m2, so the crack bound barely moves it; oak
declares 1,000 and iron 100,000, and those are the materials it changes.

## Running it again

    BANJO_LIVE_ENGINE=build/.../banjo_live_world_run.exe python tools/break_cost.py

`--material`, `--cell-mm` and `--json PATH` narrow it or keep the runs.
`tests/break_cost_tests.cpp` pins the charges and the arithmetic: the energy
law's charge is the material's own at two cell sizes, the strain law's halves
with the cells, and a break's crack area is the bonds' own share of a lattice
plane.
