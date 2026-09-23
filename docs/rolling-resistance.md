# Rolling resistance

A real ball set down on a gentle sandy bank stays where it was put, and one
rolled across a hard floor slows and stops. Before this, nothing in the
playground did either: measured, a rubber ball set down dry on 2.1 degrees of
sand by the river rolled 0.5 m in 2 s and was in the river by 4 s, and a thrown
iron ball rolled out of the yard. The engine had a rolling-resistance torque,
but it acted only on a ball the rigid world had been told was a ball, on the
one flat support plane, with the normal force taken as `m g n`; every body in
the live world is built as a fragment and was never marked round, and the
valley's ground is a height field, not a plane. So nothing in the room was
ever resisted.

## The law

A round body rolling on something is resisted at each of its contacts by a
couple against its turning about the axes that lie in the contact plane:

    M = c N r

- `c` is the coefficient of rolling resistance for the pair: the **ball's own
  share plus the surface's**, because both are deformed at the contact.
- `N` is the normal force the solver put through that contact.
- `r` is the ball's radius.

A solid ball (`I = 2/5 m r^2`) rolling without slipping on the level:

    m a = -f,    I alpha = f r - c N r,    a = alpha r
    =>  a = 5/7 c g,  and it stops in  v0^2 / (2 a)

On a slope of angle `theta` the couple can stop the ball's rolling only while
`c N r >= m g r sin(theta)`, i.e. `tan(theta) <= c`: a ball set down on a
slope gentler than `atan(c)` stays, and on a steeper one it rolls at
`5/7 g (sin theta - c cos theta)`.

## What about a piece that is not round?

Nothing here acts on one, and after this it does not need to. The reasoning was
that "a broken piece is a hull whose rolling is its own shape's business: it has
to lift itself over each edge", and that is true -- but it was not happening,
for a reason that had nothing to do with rolling.

A piece was being made **six thousand times harder to turn than its own
matter**. Jolt diagonalises the inertia it is handed and substitutes a unit
sphere for anything below its epsilon, and a 20 mm chip is far below it: one
asking for 3.73e-7 kg m2 was made with 0.00224. So nothing could stop such a
piece turning, and it rolled on for ever. Measured on a chip set going at
0.49 m/s and 42 rad/s across concrete: **4.2 m in ten seconds**, keeping three
quarters of its speed. With its own inertia: **21 mm**, by climbing its own
corners exactly as the reasoning said it would.

Two other things were measured and rule themselves out:

- Rolling resistance for every body, not only round ones, does fire once the
  contacts are kept for it -- but oak on concrete is c = 0.002 + 0.001, which
  took 0.06 mJ a second off 1.3 mJ of motion. A ball's coefficient is not what
  stops a tumbling chip.
- A shape's own share of the coefficient -- `(1 - e^2) * rise / chord` from the
  lift over its corners -- does stop it, in about the same distance. With the
  inertia right it is not needed, so it is not in the engine.

## What the engine does (src/rigid/JoltWorld.cpp)

Before every step, for each round body that ended the last step touching
something:

- **N is the solver's own.** Jolt keeps, for warm starting, the total normal
  impulse its solver applied at every contact point in the last update, and
  the one public way to read it is the state recorder. After each step the
  world saves only the contact pairs a ball is in
  (`PhysicsSystem::SaveState(EStateRecorderState::Contacts)` with a filter) and
  reads each manifold's impulse out of Jolt 5.6's layout, which the reader must
  account for byte by byte. If it ever does not -- a Jolt upgrade changing the
  layout -- it says so once on stderr and falls back to each ball's own change
  of momentum over the step, less gravity and the pushes, along each contact
  normal: exact for a ball touching one thing, and blind to two things
  pressing it from opposite sides. That fallback is the only approximation of
  N, and `from_solver` in every report says which one was used.
- **What does not move is one support.** The floor, the ground and anchored
  scenery a ball touches are taken together, their normal the force-weighted
  mean and their limit the sum of `c N r`. If the ball is rolling (its surface
  at the contact moving under 5 cm/s, the line the contact callback already
  draws between static and dynamic friction) the couple stops the rolling
  angular momentum about the contact point that the step would otherwise
  leave -- the ball's own, and what gravity and any push add over the step;
  the contact's own forces act at that point and add none. If it can, it does,
  and the ball stays exactly where it is: that is a ball held on a slope. If it
  cannot, it takes off `c N r dt`. A sliding ball has its spin resisted, never
  reversed. Jolt's own friction then carries the couple into the ball's travel,
  which is what makes the level deceleration `5/7 c g`.
- **What moves under it** -- a plank, another ball -- gets the couple too:
  equal and opposite, against the two bodies' relative turning, never
  reversing it.
- **The energy it takes is declared.** The couple's work over a step is `M`
  times the mean rolling rate, which is what it takes out of the motion; it is
  added up by ball and in all (`JoltWorld::rollingLossJ`). Holding a ball
  still does no work. It is reported like the engine's other declared losses
  (the work a cut takes): `banjo_rolling_report`, the line protocol's
  `rolling` op and `thermo` ledger, the MCP's `run`.

Two things in the solver had to be dealt with for the law to come out, both
found by the tests below failing, not by inspection:

1. **Jolt's body-pair contact cache carries a rolling ball's contact point
   round with the ball.** While two bodies have moved less than 1 mm and turned
   less than 2 degrees since a contact was found, Jolt reuses it, and the point
   on the ball is kept in the ball's own frame -- so below about a quarter of a
   metre a second a 120 mm ball is pushed on at a point up to a millimetre
   behind the one it rests on. That couple drives it on: about 0.008 in
   coefficient, more than an iron ball's whole rolling resistance. Measured
   before the fix: a rubber ball rolled 8% past `v^2 / 2a` and an iron one never
   stopped. Now a rolling ball's contacts are found afresh every step
   (`BodyInterface::InvalidateContactCache` on the balls alone, which costs a
   sphere's narrow phase). It was always there; with nothing to resist a ball
   it had nothing to show against.
2. **Jolt's sleep rule froze a ball the law says rolls.** A body still for half
   a second under 3 cm/s is put to sleep, and a ball just over `atan(c)` on a
   ramp stopped 8 mm down it. A ball on a fixed support that the couple cannot
   hold now has its sleep timer reset; one it holds is at rest and sleeps by
   Jolt's own rule. Nothing is put to sleep, pinned or damped to make it stop.

And whole balls no longer carry Jolt's velocity damping (0.02 per second on
every fragment): with rolling resistance to stop them, that damping was a drag
of `0.02 v` on a rolling ball besides -- a quarter of a rubber ball's rolling
resistance at 1 m/s on the floor, and twice an iron ball's. Boxes and broken
pieces keep it, so nothing that slides or topples changed.

One consequence reaches fracture, and it is left showing rather than tuned
away. A ball dropped 6 m now arrives 0.4% faster (10.79 m/s against 10.75),
and in `tests/threshold_tests.py` the iron ball dropped exactly 6.00 m onto
the 20 mm glass plate now leaves it whole, where the build this was branched
from (main at 422d629) broke it into 54 pieces. Whether that plate breaks
turns on where in a step the ball arrives, without rolling resistance as well.
Dropped from each of 5.90, 5.93, 5.96, 5.99, 6.00, 6.02, 6.05 and 6.08 m, 422d629
breaks it at 3 of the 8 heights (0, 31, 0, 0, 54, 26, 0, 0 pieces) and this
branch at 7 (14, 77, 43, 3, 0, 74, 37, 4). That is the
queued fracture path's sensitivity to the capture phase, which does not depend
on rolling resistance; it is a separate defect, and the test stays as written.

## What is round

**Balls only**: a whole authored sphere (`FragmentPrimitive::Sphere`, not
anchored), and the rigid world's `addBall`. A ball dented by an impact keeps
its sphere -- dents in this engine are about a tenth of a millimetre -- and is
still resisted.

**Boxes do not roll**, and nothing is added to them: a toppling domino, a
rocking tower and a sliding block are exactly what they were.

**Broken pieces (hulls) are not resisted either, deliberately.** A hull has no
radius, and its rolling is its own shape's business: to roll it has to lift its
centre of mass over each edge and it loses energy at each face it lands on,
which the solver already computes. A couple `c N r` would need an `r` it does
not have and would damp its tumbling, which is exactly what must not change.
The one body this would miss is a ball rebuilt as a hull because its shape
changed by more than a quarter of a cell; the engine cannot currently dent
anything that far.

## The coefficients

Each material's and surface's own share, what the engine uses, where it comes
from and how uncertain it is. "Sourced" means an engineering table or a
measurement gives it (or bounds it) for that material; a **demonstration**
value means none was found, and it is carried over from a sourced one by the
elastic-hysteresis scaling of rolling resistance (Tabor 1955; Johnson 1985,
ch. 8): `c` grows with the material's loss fraction and with the contact
half-width `a / r`, and `a` goes as `(N r / E*)^(1/3)`, so for the same ball
and load `c` scales as (internal loss) x `E^(-1/3)`. The damping ratio each
material declares is taken as its loss.

| material / surface | own share `c` | basis | status | range |
|---|---|---|---|---|
| iron | 0.0005 | half of steel on steel: hardened steel ball bearings on steel 0.0010-0.0015 [1]; a railway wheel on its rail 0.0010-0.0024 [1][2] | sourced | 0.0002-0.0012 (rail "pure rolling" 0.0003-0.0004 [1] to the rail upper bound); cast-iron mine-car wheels reach 0.0065 a pair [1] |
| aluminum | 0.001 | iron's, scaled: 69 GPa against 211 (x1.45) and loss 0.02 against 0.015 (x1.33) | demonstration | 0.0005-0.002 |
| glass | 0.0005 | no table value for a glass ball; hard, elastic and smooth, taken as iron. A handbook figure for a 1/16 in steel ball on glass is 1.4e-5 [6] | demonstration | 1e-5-0.001 |
| ceramic (alumina) | 0.0003 | iron's, scaled: 300 GPa (x0.89) and loss 0.01 (x0.67) | demonstration | 0.0001-0.001 |
| oak | 0.002 | a smooth wooden track adds at most 0.001 under a bicycle tyre [2]; iron's scaled for 12 GPa and loss 0.04 gives 0.0035; taken between | demonstration | 0.001-0.004 |
| rubber | 0.010 | a rubber tyre on concrete 0.010-0.015 [1][2][3], nearly all of it the rubber's own hysteresis | sourced | 0.002-0.015: tyres flex far more than a solid ball, and a solid 120 mm ball under its own weight estimates nearer 0.002 by the hysteresis formula |
| ice | 0.002 | no measurement found; iron's scaled for 9 GPa (x2.9) and loss 0.025 (x1.7) | demonstration | 0.0005-0.005 |
| concrete | 0.001 | a bicycle tyre on concrete is 0.002 in all [2], so concrete's own share is at most that | sourced (bound) | 0.0005-0.002 |
| **the floor** of every room without terrain | 0.001 | it is concrete -- the room's ground material, drawn and described as flat concrete | as concrete | |
| rock (valley) | 0.001 | the engine's stone, concrete | as concrete | 0.001-0.02: a natural rock face is rougher than a floor (car tyres: 0.03 on large worn cobbles against 0.010-0.015 on concrete [2]), and that roughness is not modelled |
| soil (valley) | 0.06 | a car tyre on medium-hard soil 0.04-0.08 [2]; a 19th-century stagecoach on a dirt road 0.0385-0.073 [1][4] | sourced | 0.04-0.08 |
| sand (valley) | 0.30 | a car tyre on sand 0.30 [1][3], on loose sand 0.2-0.4 [2]; glass spheres of 5-32 g rolling on loose quartz sand 0.43-0.50 and steel spheres of 2-175 g 0.50-0.67, independent of speed below 1 m/s [5]; 12.7 mm spheres on 0.8 mm glass beads 0.2-0.45, rising with sinkage as 0.41 d/R + 0.32 [7] | sourced | 0.15-0.65: on loose sand it rises with a ball's density and falls with its size [5], which one number cannot say |

What pairs come to (`c` = the two shares added):

| pair | c | rests below | from 1 m/s on the level it stops in |
|---|---|---|---|
| rubber on the floor | 0.011 | 0.63 degrees | 6.5 m |
| iron on the floor | 0.0015 | 0.086 degrees | 48 m |
| rubber on sand | 0.310 | 17.2 degrees | 0.23 m |
| rubber on soil | 0.070 | 4.0 degrees | 1.0 m |
| rubber on rock | 0.011 | 0.63 degrees | 6.5 m |
| iron on sand | 0.3005 | 16.7 degrees | 0.24 m |

The additive rule and a single number per material are the owner's model, and
a simplification: in reality `c` depends on load, radius and speed (a caster
maker's own data give a forged-steel wheel `f = 0.019 in` under 1200 lb on an
8 in wheel, `c` = 0.005 [8]; tyres rise with speed), and on loose sand on how
far the ball sinks [5][7].

The values are in `src/material/MaterialCatalog.cpp` (with
`rollingResistanceSource`, the sourced / demonstration label) and
`src/terrain/TerrainField.cpp` (`GroundMaterial::rolling_resistance`, with its
own label). The ground's patches are one collider with one material, so the
world asks the terrain what is on top wherever a ball touches it
(`JoltWorld::setGroundRollingResistance`, set by `Environment::attach`): a
dig, a slump or a heap of sand changes it as it changes the ground.

## Measured (tests/rolling_resistance_tests.cpp)

All through the engine; tolerances were set before the runs and none was
widened.

| what | measured | the law | off |
|---|---|---|---|
| rubber on the floor, rigid world (analytic sphere), deceleration | 0.077019 m/s^2 | 5/7 c g = 0.077079 | -0.08% |
| the same, stopping distance from 0.9926 m/s | 6.3943 m | 6.3915 | +0.04% |
| rubber, live world, 10 mm cells (917 cells), deceleration | 0.076563 | 0.077079 | -0.67% |
| the same, stopping distance | 6.2833 m | 6.2447 | +0.62% |
| iron on the floor, rigid world, deceleration | 0.010468 | 0.010511 | -0.41% |
| the same, stopping distance from 0.3 m/s | 4.2721 m | 4.2523 | +0.47% |
| iron, live world, 10 mm cells, deceleration | 0.010324 | 0.010511 | -1.78% |
| the same, stopping distance | 4.2839 m | 4.2102 | +1.75% |
| control: rubber on the floor with every coefficient zero, 5 s | -6.8e-5 m/s^2 | 0 | keeps its speed |
| energy rolling resistance declared it took, rubber rolling to rest | 0.68703 J | the kinetic energy it lost, 0.68646 J | +0.08% |
| rubber on declared sand, height field, 2.1 degrees, 5 s | moved 8e-8 m | rests (tan < c) | |
| the same at 0.85 atan(c) = 14.6 degrees | moved 2.8e-5 m | rests | |
| the same at 1.15 atan(c) = 19.8 degrees, 3 s | rolled 1.43 m | rolls | |
| control: no resistance on either, height field, 2.1 degrees | rolled 1.17 m in 3 s | rolls | |
| exact plane of declared sand, 19.8 degrees, acceleration | 0.33066 m/s^2 | 5/7 g (sin - c cos) = 0.33068 | -0.01% |
| exact plane, no resistance, 2.1 degrees | 0.25676 m/s^2 | 5/7 g sin = 0.25677 | -0.00% |
| anchored concrete ramp in the live world, 0.85 atan(c) = 0.54 degrees, 5 s | moved 3.5e-9 m | rests | |
| the same ramp at 1.15 atan(c) = 0.72 degrees, 5 s | rolled 0.174 m | rolls | |
| a ball alone on the floor, N | 9.7635 N | m g = 9.7635 | 0.00% |
| a ball under a 63 kg iron plank, N from the floor | 318.58 N | (m + M/2) g = 318.58 | 0.00% |
| the same ball, N from the plank | 308.82 N | M g / 2 = 308.82 | 0.00% |
| what `m g n_y` would have said under the plank | 9.76 N | 318.58 | 97% short |
| valley, rubber ball set down on sand at [2.00, 4.25], 2.12 degrees, 10 s | at most 0.0001 m from where it was put, dry | rests (tan 0.037 < 0.310) | |
| valley, the same ball set down on a plane soil slope of 11.2 degrees | rolled 14.7 m in 10 s | rolls (tan 0.197 > 0.070) | |
| valley, 10 s with both balls | 0.24 s of computing | inside 1.1x realtime | 0.02x |

Two measurements that are NOT the 5/7 law, said rather than asserted:

- **At the room's own 40 mm cells** a 120 mm ball is a handful of cells whose
  own inertia is not `2/5 m r^2` (19 cells give 0.54 m r^2), and it slows at
  `c g / (1 + k)`: measured 5.7% (rubber) and 6.4% (iron) under `5/7 c g`. That
  is the law for the body the engine has, not a fault of the resistance.
- **Rolling down a steep height field** the ball is 10.6% slower than the law
  (19.8 degrees; the exact plane is -0.01%). The height field keeps its
  heights to a few tenths of a millimetre per block, and a ball rolling over
  those steps loses a little more. At the valley's gentle slopes it is under 2%.

## Where to see it

- **The playground.** In the valley (`/world?scene=valley`) a ball set down on
  the sandy bank stays; in the empty yard (`/world?scene=yard`) a ball rolled
  across the floor slows and
  stops where `v^2 / (2 * 5/7 c g)` says.
- **C API** (ABI 16): `banjo_materials()`, `banjo_rolling_report(world)`, and
  `rolling_resistance` in `banjo_survey`. See [api/c-api.md](api/c-api.md#rolling-resistance).
- **Python**: `banjo.materials()`, `World.rolling_report()`.
- **Line protocol** (`banjo_live_world_run`): `{"op":"materials"}`,
  `{"op":"rolling"}`, `rolling_resistance` in `survey`, `rolling_loss_j` in the
  `thermo` ledger.
- **MCP**: `list_materials` (every material's and surface's coefficient, marked
  sourced or demonstration), `survey` (the ground's, and which balls rest there),
  `run` (which balls are held still, which roll against it, what it took).
- **The chat**: the guide tells it a ball stops quickly on sand or soil and
  rolls a long way on stone or the floor, with the numbers.

## Not modelled

- `c` does not depend on speed, load or radius, and a pair is the sum of two
  single numbers.
- Sand and soil are a rigid height field: nothing sinks, nothing is ploughed,
  no rut is left. Rolling resistance stands in for all of that, as a number.
- Roughness of a natural rock face, wet sand, grass.
- Hulls and boxes: not resisted, by choice (above).
- Twist -- spinning about the contact normal -- is Jolt's own twist friction,
  not rolling resistance.
- A ball on something that moves is resisted against their relative turning,
  without the stop-the-step prediction a fixed support gets, so it can creep on
  a moving plank where it would rest on a fixed one.
- `N` falls back to each ball's change of momentum if Jolt's contact cache
  stops reading as Jolt 5.6 writes it; `from_solver` says when.

## References

1. Wikipedia, "Rolling resistance", table of rolling-resistance coefficients
   (accessed 2026-09-12), citing for its rows: Hibbeler, R. C., *Engineering
   Mechanics: Statics & Dynamics*, 11th ed., Pearson Prentice Hall, 2007,
   pp. 441-442 (hardened steel ball bearings); Hay, W. W., *Railroad
   Engineering*, and Astakhov, P. N. (railway wheels on rail, and "pure
   rolling"); Hersey (mine-car cast-iron wheels); Gillespie, T. D.,
   *Fundamentals of Vehicle Dynamics*, SAE, 1992, p. 117 (ordinary car tyres on
   concrete 0.010-0.015, on sand 0.30); Baker, I. O., *A Treatise on Roads and
   Pavements*, Wiley, 1914, Table 7 (stagecoach on a dirt road).
2. The Engineering ToolBox, "Rolling Resistance" (engineeringtoolbox.com,
   rolling-friction-resistance-d_1303): railroad steel wheels on steel rails
   0.001-0.002; bicycle tyre on a wooden track 0.001; bicycle tyre on concrete
   0.002; ordinary car tyres on concrete 0.01-0.015; car tyre on solid sand,
   loose worn gravel or medium-hard soil 0.04-0.08; car tyre on loose sand
   0.2-0.4.
3. Gillespie, T. D., *Fundamentals of Vehicle Dynamics*, SAE, 1992, p. 117.
4. Baker, I. O., *A Treatise on Roads and Pavements*, Wiley, 1914.
5. De Blasio, F. V. and Saeter, M.-B., "Rolling friction on a granular medium",
   *Physical Review E* 79, 022301 (2009), Tables II and III.
6. Sasaki, S., Namba, Y., Iwanari, T. and Kitano, Y., "Analysis of rotational
   motion based on rolling friction torque", arXiv:2111.06258 (2021), quoting
   a Mechanical Engineering Handbook for a 1/16 in steel ball on glass, iron,
   lead, copper and aluminium: 1.4e-5 to 1e-3.
7. Fukumoto et al., "Depth and slip ratio dependencies of friction for a sphere
   rolling on a granular slope", arXiv:2602.01652 (2026).
8. Lippert, D. and Spektor, J., "Rolling Resistance and Industrial Wheels",
   Hamilton Caster White Paper No. 11.
9. Tabor, D., "The mechanism of rolling friction. II. The elastic range",
   *Proceedings of the Royal Society A* 229, 198-220 (1955); Johnson, K. L.,
   *Contact Mechanics*, Cambridge University Press, 1985, ch. 8 -- the
   elastic-hysteresis scaling the demonstration values are carried by.
