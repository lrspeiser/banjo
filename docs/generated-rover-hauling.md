# Generated rover hauling — October 1

Published implementation: `0806702c311d26b0fb7d61e42bfcc68f34da8eba` on
GitHub main. The port 8770 preview runs this checkpoint's Python sources with
the native engine/API baseline recorded below.

## Implemented

New generated worlds place their rover on the working approach toward the
nearest copper deposit, with declared initial heading and clear sampled ground/
water probes. Starter processors are placed before the solar farm and camp
light. Actual compiled part footprints reserve space around a working corridor;
processor service checks use the compiled root centre of mass and both real
stockpile regions. Placement checks dry rectangles instead of the larger square
around their diagonal. The terrain itself is unchanged. The placement graph
now filters at 11°, below the measured stock-rover 12° policy; it is not a
native traversal certificate.

Routine `go_to` reads current native bodies and terrain. Its local route has
0.5 m cells, a 6 m observation radius and at most 1,024 terrain queries per
plan. The assembled radius comes from actual transformed shape corners. It
checks occupied clearance, dry terrain, supported grade, and predicted forward
ground probes at each planned heading and turn. Turns are sampled at no more
than 22.5°; straight legs at 0.25 m. Rear probes retain native authority during
reversing. Only routine requests use this planner; direct human control keeps
its existing behavior.

Each issued waypoint uses the [native bounded approach](rover-waypoints.md)
with a 0.4 m radius. The routine waits for actual braking before replanning or
working, and checks actual position against the requested receiving/work region.
A blocked plan holds on real brakes, preserves load and retries after three
seconds. Exhausted drive retries hold the same step for recovery/resume; they
do not advance into digging at an unrelated place. There is no runtime body
position/velocity assignment or terrain flattening.

Ordinary world opening now supplies current native observations to the newly
created brains before their first clock step. A later page `poses` request is
not required to begin planning. Partial native replies keep the session's merged
static geometry, rather than deleting obstacles that did not move.

Automatic scoops recheck their actual proposed position with the native support
guard, moving the requested bite farther ahead in 0.1 m increments within the
existing 2 m arm reach. The scalar radius estimate alone did not certify a
rotated expanded rectangle. Refused digs still preserve the full snapshot;
accepted scoops still debit real work before changing terrain.

## Measured first delivery and pickup

Windows, MSVC Release native engine/API baseline
`18180a7ac98822980e3fa013f4d4da5d984721c1`, 50 mm scene cells,
native clock `dt=1/240 s`. The two ordinary generator choices use terrain seeds
0/1 and resource seeds 851269740/851269741. No provider calls, new grants or
forced movement are used. The declared starter intake contains 20 kg ore.

| Generator choice | First delivery by s | Delivered total kg | Mined copper ore kg | Collected copper kg | Conversion residual kg |
|---|---:|---:|---:|---:|---:|
| 0 | 68.2 | 40.000000 | 12.000000 | 9.600000 | 0 |
| 1 | 82.0 | 29.995942 | 8.998783 | 8.699635 | 0.000000221074 |

The test requires actual native digging, a positive rover dump activity into
the declared smelter intake, an emptied hopper, subsequent processing, nearby
personal output collection, exact SQL credit, complete routine restore and
retry without duplicate credit. A normal power-off after first delivery isolates
that load while the processor finishes. Copper is `(starter + mined ore) × 0.3`.
The conversion check allows `1e-6 kg` for the existing six-decimal ledger
quantization; actual pickup/SQL/restart receipts must match exactly. Inventory's
four-decimal display is checked separately. Neither the quantization residual
nor private receipt equality proves physical conservation.

The CMake-registered `banjo_generated_rover_tests` runs these two acceptance
cases independently of the browser/player presentation suite. Local evidence:
`build/resource-flow/generated-first-haul.json`,
`navigation-final-generated-gate.log`, `navigation-final-player-gates.log`,
`navigation-small-gates.log` and `navigation-final-seed.log` in that directory.
The source-registration guard remains 286/286 native sources.

Final affected gates: the two generated acceptance cases pass in 141.82 s;
all 15 browser/player cases pass in 104.72 s and all 50 rover-brain cases in
5.12 s. The 24 world-seed cases pass in 9.251 s; the room, Workshop-rover and
routine-language gates also pass. Earlier rotated-scoop failures were fixed
by checking the actual native bite position before excavation.

The refreshed port 8770 preview passes ordinary Chrome world entry, ten live
sensor readings, physical recovery and release with zero browser exceptions.
Measured recovery pull is 793.666 N and hand work 299.920 J. This preview check
qualifies those controls; the separate acceptance cases above measure hauling.

## Remaining boundary

Earlier exploratory 300 s runs with an initial pose refresh produce one delivery
on choice 0 and four on choice 1. Choice 0 then holds while returning toward
its excavated area. The heading/probe approximation does not capture the native
caster pivot, all braking drift, or all safe detours; local progress can run out.
Passing a first haul is not sustained hauling or general terrain qualification.

Next: inspect and fix the first map's return approach, require repeated actual
receiving receipts on both maps, and measure native turning clearance and planner
cost. Cargo is still a ledger load without added inertia or native container/
dump-truck tipping. Existing glass/oak/iron grade comparisons and unclosed native
mechanical-work boundaries are retained; no material, contact or friction law
changes here. Reacting avatars, physical damage/repair and the other outstanding
player-experience requirements remain open. The full fourteen-item goal stays active.
