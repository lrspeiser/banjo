# Built wall, sledgehammer, and 160k-cell experiment

September 19, 2026. Native Release engine from main `365f43a`, ABI 25,
Windows. Source/control experiment, not a material calibration or full-engine
qualification. The executable material and joint laws were not changed.

## What was built and used

`scripts/test_building_sledgehammer.py` authors the scene through the existing
world MCP handlers, exports their saved declarations, then opens that scene in
the native live engine. The transcript and complete room spec are saved with
the run. It creates eight concrete masonry bricks, two 440 × 800 × 20 mm glass
panes, an 800 × 1280 × 40 mm oak door, two iron hinge mounts, an oak frame,
and a sledgehammer. Concrete is a declared brick substitute: the catalog does
not contain calibrated fired clay or mortar.

The hammer has a **0.7168 kg oak handle and a separate 8.05888 kg iron head**,
joined with a fixing. Joining their cells into one body would homogenize
their material in the current room-authoring lane. The head fixing has declared
10 kN tension/shear limits; pane retainers use 2.5 kN, and brick joints use
1.5 kN. These are experiment inputs, not measured fastener or mortar strengths.
Frame and hinge mounts are anchored, so this is a supported wall test, not
a freestanding building-collapse qualification. Hinge bearing strength is not
established by this run.

Every object has saved interaction points. The handle has an explicit grip
and saved primary `strike`; the door has a saved `turn` and release program.
The program moves the existing bounded hand: no imposed body velocities,
scripted breaks, fracture impulses, or edited damage states are used.

The original hinge mount touched the door edge. Moving the mount clear and
using the door's physical arc program fixed the assembly. The saved action
reported **71° of opening**, both hinges remained attached, and pressing J
in the normal browser produced the same opening. The page rendered the wall
and hammer with no browser console errors.

## Impact results and open failures

The standard saved Strike program requests 5 m/s but has the existing
2 m/s² acceleration limit. Initial head contacts reached only approximately
1.1–1.3 m/s. Both glass panes remained whole. Contact against concrete exceeded
its model threshold and entered detailed fracture analysis.

The final whole-assembly run records three completed `broke` outcomes and
122 bodies at 36.325 simulated seconds. After an additional 15-second wall-time
drain allowance, another break was still being calculated: **the damaged
snapshot was refused**. A preceding 90-second drain also failed to settle the
cascade. Dropping/repositioning the assembled hammer and secondary collisions
are included in this run, so these are not all isolated, direct hammer blows.
The intact saved world, event log, intermediate states and final report are
retained; the failed save is not presented as a successful persistence test.

A separate matched comparison holds the handle nearer the head and requests an
8 m/s, 60 m/s² native stroke, still with the unchanged bounded hand. This is
a diagnostic input, **not a change to normal Use**:

| Panel material | Peak head closing speed | Reported contact energy | Result |
|---|---:|---:|---|
| Glass | 5.019 m/s | 69.630 J | Threshold triggered analysis; detailed result was one intact piece (`held`) |
| Oak | 5.038 m/s | 38.804 J | Intact, no recorded dent |
| Iron | 5.010 m/s | 88.279 J | Intact; panel and hammer head each report a 0.05514 mm dent |

This does **not** establish realistic glass shattering. The disagreement between
the coarse trigger and the detailed result needs investigation. The contact
energy is the engine's reported impact quantity, not a complete energy ledger.
Reported dynamic mass is unchanged across these comparison runs (139.00288,
113.65888 and 214.61248 kg respectively); anchored scenery reports zero dynamic
mass. That check does not establish whole-world energy conservation.

## 160k budget measurement

`scripts/benchmark_building_cells.py` raises the admission cap to 160,000
**inside its own process only**. Production world and Workshop caps remain
16,000. The large case uses 10 mm cells and extra, separate anchored stock
blocks to fill the admission budget; it does not make one enormous deforming
body. Values below are single local observations, not performance guarantees.

| Measurement | Small wall | Large scene |
|---|---:|---:|
| Admission count | 15,868 | 160,000 |
| Native saved node count | 12,952 | 157,648 |
| Cell spacing | 20 mm | 10 mm |
| Validation after optimization | 0.042 s | 0.329 s |
| Open, including validation | 0.114 s | 1.414 s |
| 0.5 s ordinary simulation, 240 Hz | 0.032 s | 0.042 s |
| Peak native working set | 74.1 MiB | 1,038.6 MiB |
| Strong glass stroke and analysis | 0.420 s | 5.369 s |

The existing Python admission count can conservatively exceed native occupancy
when a cell centre lies exactly on an unrotated box boundary. The optimization
preserves that behavior; the table distinguishes the two counts. Correcting
that pre-existing boundary mismatch remains separate work.

Before optimization the small wall took 4.46 seconds to validate, and the
105,968-admission-cell / 103,616-native-cell wall took 35.96 seconds. The
validator previously scanned a circumscribed cube even around a thin pane or
long post. Unrotated boxes now use their exact per-axis bounding box, retaining
the same centre-inside test. Rotated boxes and other shapes keep their prior
path. All 120 seeded translated/boundary comparisons matched the old function
cell for cell, and the native geometry tests cover the new aligned-box path.

The higher scene budget is feasible for ordinary motion on this machine.
It is not a reason to permit unlimited simultaneous detailed fracture:
the larger pane's analysis took seconds, and the concrete cascade failed to
reach a saveable state. Recommended next work is a configurable scene cap,
separate active fracture budgets and queue limits, robust refinement handoff,
and glass-response investigation.

## Reproduction and verification

From the repository root, with a Release engine and adjacent `banjo.dll`:

```powershell
python scripts/test_building_sledgehammer.py --engine build/circuits/placement-qa/banjo_live_world_run.exe --out build/assembly-impact-final
python scripts/benchmark_building_cells.py --engine build/circuits/placement-qa/banjo_live_world_run.exe --spec build/assembly-impact-final/spec.json --out build/assembly-cell-bench/small --impact --grip-y .84
python scripts/benchmark_building_cells.py --engine build/circuits/placement-qa/banjo_live_world_run.exe --spec build/assembly-impact-final/spec.json --cell .01 --fill-to-cap --out build/assembly-cell-bench/large --impact --grip-y .84
```

The benchmark's process-memory measurement uses Windows APIs. Run the matching
oak and iron cases with `--material oak` and `--material iron`. Local raw
artifacts live under `build/assembly-impact-final` and
`build/assembly-cell-bench`; the compact measurements are in
[evidence](evidence/building-sledgehammer-summary.json).

Verification: all 56 world-room tests pass with the native DLL and live engine;
the fracture-lab validation/commands/summary checks pass. The menu test was
updated to the already-shipped Expedition default. The aligned native-cell
fixture uses a 120 mm thickness on the 20 mm grid to avoid the separately
documented boundary-count mismatch; rotated fixtures are unchanged.
