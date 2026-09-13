# Ground work: tools that dig

A pick is a body with a point. What the ground does about the point is the
engine's, decided in the solver from the ground's own materials and the point's
shape -- never from what the tool is called, and never from anything a player
knows. This is the physics layer of [knowledge and progression](knowledge-and-progression.md)
(its increment 1): knowledge decides which plans a player can understand and
reproduce, resources and equipment what they can make, and **physics what the
finished object can do**. Everything here is the third.

## What happens

A **tool point** is declared on a body, as an edge is: where its tip is, the way
it goes in, how wide and thick it is, how sharply it comes to its tip and how
much of the tool is point (`LiveWorld::toolPoint`). From then on that body
collides as its cells, so a pick's crook is open.

When the point meets the terrain point first, the engine (src/fastlattice/
ToolTerrain.cpp) puts a one-sided constraint on it for that step -- the **ground
bite**: along the point's axis the ground can push back with at most the
model's resistance for how deep the point is going; across it, with at most the
passive resistance of the soil in front of it. The contact between the point's
own cells and the ground is suspended while the bite holds, so the ground's
push on the point is the bite's and nothing else. The work is measured from the
solver's own impulses, the way a cut's is. How deep the point goes is what the
solver makes of that resistance against the tool's momentum and the hand.

Pried sideways further than a tenth of its depth, the point **breaks the ground
out**: a wedge of soil comes loose in front of it. When the point comes out of
the ground, what came loose leaves through the ground's own dig
(`Environment::dig`), so it is carried exactly as anything dug is, the ground's
ledger keeps it, and the report says where the dig was made -- as a dig edit
would say it -- so a room keeps it: the ground opened again from its edits has
the same hole, to the bit, and carries the same.

Ground the model does not cover is said, not guessed:

| the point meets | the answer |
|---|---|
| soil, sand, loose soil, dry | goes in; a pry breaks it out (`in the ground`, `broke out`, `pulled out`) |
| rock, with a point no harder than the rock | `stopped`: the rock stops it and nothing comes loose |
| rock, with a point harder than the rock | `not supported`: breaking rock out under a point has no law here |
| ground under more than 5 mm of water | `not supported`: there is no wet-soil law |
| the room's concrete floor | `glanced`/`stopped`: an ordinary contact |
| the ground side-on | `glanced`: an ordinary contact |

The tool's own condition -- whole, dented, broken -- is the engine's material
response to what the bite and the contacts put through it, reported with every
meeting.

## The model: ground-work-v1 (declared)

A **declared** model, from closed forms in the soil-mechanics literature and the
terrain's own ground materials. It has not been calibrated against a real pick
in real soil. Every number below is the model's, and says so wherever it is
reported; the work, impulse and peak force next to it are measured.

- **Going in** -- Terzaghi's bearing capacity of a strip, on the point's face:
  q(d) = c N_c + γ d N_q + ½ γ t(d) N_γ, with Prandtl's
  N_q = e^(π tan φ) tan²(45° + φ/2) and N_c = (N_q − 1) cot φ, and Vesić's
  N_γ = 2 (N_q + 1) tan φ. The resistance is F(d) = q(d) · w · t(d), where the
  point is w wide and t(d) = min(T, 2 mm + 2 d tan(θ/2)) thick at depth d for a
  wedge of included angle θ and full thickness T. Per step the bite resists with
  the mean of F over the step's predicted travel, [W(reach) − W(depth)] / (reach
  − depth), so the work it takes is the model's work to the millimetre.
- **Being pried** -- Rankine's passive pressure on the face in front of the
  point: P(d) = (½ γ d² K_p + 2 c d √K_p)(b + d), with K_p = tan²(45° + φ/2) and
  b the width of the face that leads.
- **Breaking out** -- once the point has gone sideways 0.1 d, the wedge in front
  of it comes loose: V = (b + d)(½ d L_f + d (s − d/10)), L_f = d tan(45° + φ/2),
  for sideways travel s. It goes out as one even layer over the ground's
  columns the wedge reached, along the way the point was pried.
- **Rock** -- as hard as the engine's stone, the concrete preset's 100 MPa. Oak
  is 35 MPa, iron 1.5 GPa.
- **The ground** -- the terrain's own materials: soil ρ 1600 kg/m³, φ 30°, c
  2 kPa; sand ρ 1600 kg/m³, φ 32°, c 0; loose soil is soil with no cohesion.

At φ 30°: N_q 18.401, N_c 30.140, N_γ 22.402, K_p 3. For the pick's point (40 mm
wide and thick, 30°, 200 mm long) in soil: F(100 mm) 153.9 N, P(200 mm) 558.6 N,
and the wedge a 200 mm-deep pry breaks out is 8.31 L.

`src/terrain/GroundWork.hpp` is the model, `kGroundWorkModel` its version,
reported with every meeting.

## Every way in

| | declare a point on a body | a bounded tool action | what the ground did |
|---|---|---|---|
| C++ | `LiveWorld::toolPoint` | `LiveWorld::strike` | `LiveWorld::groundWork` |
| C API | `banjo_make_tool_point` | `banjo_strike` | `banjo_ground_works` |
| Python | `World.tool_point` | `World.strike` | `World.ground_work` |
| line protocol | `{"op":"tool_point"}` | `{"op":"strike"}` | `{"op":"ground_work"}`, and every step reply that has news |
| MCP | `tool_point` | `strike` | `ground_work`, and `interaction`'s trial for `swing-and-lever` |
| page | the pick's profile (`swing-and-lever`) | click to swing at the ground under the crosshair; right-click levers it out | the line under the controls, the conversation, and the Carried list |

A **strike** is a bounded tool action: the engine's hand -- 800 N and a 60 N m
wrist -- makes it at the step's own rate. A swing raises the tool back over the
shoulder and brings it round so the point meets the target along its own axis;
how fast it arrives is the hand's strength against the tool's mass. A lever
turns a point that is in the ground about where it went in, then draws it up.
No speed and no depth is ever given.

## Measured

`tests/ground_work_tests.cpp` (the engine), `tests/ground_work_binding_tests.py`
(the C API through Python) and `tests/ground_work_mcp_tests.py` (the MCP, and the
playground's room), all in the real engine, stepped at 1/240 s:

- **A 0.448 kg stake dropped point first from 1 m into soil**: arrived at
  4.35 m/s, went 62.3 mm in. The bite measured 4.640 J; the stake lost 4.603 J
  from the step the bite first acted in, and the semi-implicit integrator's own
  term m g dt v/2 is 0.040 J, leaving 0.003 J against a damping bound of
  0.006 J. The model's depth for 4.640 J is 70.7 mm: the solver's is short of it
  by less than one step's travel (18.1 mm). Drawn straight out: `pulled out`,
  nothing loosened, the carried account unchanged.
- **The oak pick (1.21 kg) swung from a fixed shoulder**: into soil at 9.34 m/s,
  124.0 mm in, 16.51 J, peak 165 N; the same swing twice is the same meeting to
  the bit. Onto rock: `stopped`, nothing loosened, with the reason. An iron
  stake onto rock: `not supported`, with the reason.
- **Levered**: the point went 192.6 mm sideways at 125 mm deep, 11.94 J of the
  work prying, and broke out 5.96 L (9.54 kg) of soil. The carried account grew
  by exactly what the dig took (to 10⁻¹² m³); the ground's ledger closes (to
  10⁻⁹ m³). Opened again from the dig as the report gives it, the ground's
  heights are identical and the carried amount is the same.
- **Through the MCP, in the clearing room**, the pick built as the chat is told
  to build it (lying on the soil) and tried by `interaction`: into soil at
  9.17 m/s, 120.3 mm in, 15.85 J; levered and drawn out, it broke out 5.61 L
  (8.97 kg); onto the rock at 8.22 m/s, `stopped`. 6.6 s of world in 0.17 s of
  computing. The same trial under two names is the same to the last digit:
  nothing a profile says reaches the physics.

## Not here yet

- No fracture of rock under a point (mining), and no wet soil.
- No wear: a point is as sharp after a thousand blows as after one. Its dents
  and breaks are the lattice's.
- The breakout goes out as an even layer over whole ground columns (0.1 m in
  the clearing), which is coarser than the wedge.
- Rankine without wall friction, and no rate effects: the model's resistance
  does not depend on how fast the point goes in.
- Nothing here is calibrated: the model is declared, with its sources above.
