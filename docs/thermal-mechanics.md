# Heat and strength

Temperature, composition and what has burned change what a body can carry, and
the failures that follow are the engine's own: a joint parts when the load the
solver measures passes what is left of it, and a beam gives way when its own
heated lattice, loaded as it stands, reaches its failure criterion. There is no
"fire destroys object" rule, no burn timer and no universal "hot means weak"
multiplier: each material has its own declared law, with its sources, and a
material with no law is not changed at all.

**One material state.** What heat has done to a body is one field, and
everything that asks what the body can carry or where it is reads that field:
the load survey and the joints (the section), a fracture run (the lattice's
bonds and masses), the collision shape and the drawn shape, the mass, the centre
of mass and the inertia, and the attachments made on it. A burning beam is drawn
and collides smaller, weighs less, is exactly as weak in its lattice as the
survey says, and once a section has burned away it stops holding what rested on
it and stops being in the way.

Increment 1 -- properties and failure, parts A and C of the owner's
specification -- came with `agent/thermal-mechanics` (ABI 16). Increment 2 --
what burned leaves the shape, part B -- and the heated lattice are on
`agent/heat-geometry` (ABI 19). Thermal expansion (D) is later. What is not done
is listed at the end.

Engine: `src/thermo/ThermalMechanics.{hpp,cpp}` (the laws, the material field,
the section), `src/thermo/ThermoWorld.*` (the irreversible history each body
carries), `src/fracture/SustainedLoad.{hpp,cpp}` (statics under a load),
`src/rigid/JoltWorld.*` (`reshapePrimitive`), and the coupling in
`src/fastlattice/LiveWorld.cpp`.

## One material state

### Design

A body's thermal state -- from `ThermoWorld::matter`: how much of its
load-bearing substance is gone, its surface layer and its core, their
temperatures and the hottest each has been, their masses -- is laid over the
body's **reference box** (as authored, or as a piece's cells were when it broke
off) as `thermo::MaterialField`. Depth is measured in from the faces (radially
for a sphere):

    depth from the faces      what is there
    0 .. consumed_m           burned away: nothing
    .. + layer_m              the surface layer, at its factors; char once its hottest passed 300 degC
    beyond                    the core, at its factors

Each zone carries its factors now and if it cooled now (stiffness, tension,
compression, shear). Everything reads that field and nothing reads anything
else:

| what | how it reads the field |
|---|---|
| the section: the load survey, joints made of the body, the reports | integrated over a cross-section: at most three rings |
| a lattice run: an impact, or statics | each cell's overlap with the three zones gives its factors by the rule of mixtures; a bond is two half-cells in series (its stiffness the harmonic mean of its ends'), as strong as its weaker end; a cell weighs the matter left spread evenly over the volume left, normalised to the network's mass |
| the collision shape | a box or a sphere: the reference less the burned depth on every face, re-cut every 0.2 mm; a piece (a hull): the cells it has left |
| the drawn shape | the same, redrawn whenever the body's `revision` moves |
| the mass | the network's, mirrored to the rigid body whenever it has moved by 1e-3 of itself |
| centre of mass and inertia | the box that is left, with the matter spread evenly in it; a box recedes evenly, so its centre of mass stays at its centre |
| attachments | a joint made at a point lets go once more than half a cell (10 mm at 20 mm cells) has burned away from under that point |
| the impact bar | the heated bonds' removal thresholds and impedance, refreshed whenever the field moves |

**The heated bond: one law, applied once.** A lattice bond's thresholds are
strains, and the force a bond fails at is its stiffness times its strain. A bond
whose factors are f_E (modulus), f_t, f_c and f_s (strengths) gets

    compliance               / f_E
    tension thresholds       x f_t / f_E
    compression thresholds   x f_c / f_E
    shear thresholds         x f_s / f_E

so the force it fails at moves by exactly f_t (or f_c, or f_s), once. A bond
with f_E at or below 1e-6, or with no strength left, is dead: it is not in the
lattice at all.

**Never twice.** The survey multiplies the cold strength by the section's
factor; the lattice multiplies cold bonds by their cells' factors and never by
the section's as well; a joint multiplies its cold capacity by the section's
factor. The section is taken across the reference box with the burned depth
inside it -- taken across the burned box as well, what burned away would come
out twice. The field's numbers are worked out once per body per refresh and
shared by all of them.

### Implementation

`thermo::materialField`, `cellShare` (for a box, the exact separable overlap of
the cell with each zone, over the cell's cold overlap with the box; for a
sphere, 4 x 4 x 4 samples), `cellFactors`, `cellMassKg`, `bondFactors`,
`massProperties` and `remainingBox`; `evaluateSection` reads the same field. In
`LiveWorld`: `heatedCellsOf` and `heatIsland` put the field into a lattice run;
`reviseMatter`, every eighth accepted step, cuts the shape again, takes away
cells, lets go of joints and burns away what has nothing left;
`refreshHeatedBonds` keeps the impact bar on the heated bonds; `materialStates`
reports it.

### Validated

- **The field is one state** (`tests/thermal_geometry_tests.cpp`). A 400 x 60 x
  100 mm oak box with 12% of its dry wood burned -- 2.129 mm from every face --
  and a charred 3 mm layer at 700 K over a 400 K core: its cells add up to
  exactly what the field says is left (2112 of 2400 cm3, to 1e-9 m3), which is
  12% gone to 1e-6; the section's tension factor is the field integrated cell by
  cell over a cross-section (0.418668 both, to 1e-9); the mass properties hold
  all of the network's matter and the inertia of the box that is left.
- **At every snapshot of the owner's heated beam** (`checkOneState`): the rigid
  body weighs what the network says is left, to the 1e-3 it is mirrored at; its
  box is the reference less twice the burned depth, to 0.4 mm -- twice the
  0.2 mm it is re-cut at; its inertia is that box's with that mass, to 1%; and
  the mean of its bonds' tension factors is within 0.05 of the section's.
- **The impact bar follows the heated bonds.** Glass has no law: 4.506 m/s
  heated and cold. Iron at 412 K: 12.397 m/s against 12.270 cold, x1.0103 --
  EN 1993-1-2 leaves its strength whole there and its modulus at 0.961, so a
  bond takes a little more energy to break, and the acoustic bound through the
  heated bond gives x1.0100. Oak dried at 3 kW for 15 minutes and cooled for 10:
  7.65 m/s against its cold twin's 10.98.

## Sustained loads: statics

### Design

The load survey asks beam theory whether a body carries more than its section
can take. That is the question worth asking, not the answer. A body the survey
offers **under a sustained load** -- nothing is striking it -- is answered by
**statics on its own heated lattice**:

- supported by the cells of its bottom layer over each thing it rests on,
  unilaterally: a support that would have to pull is let go (an active set);
- loaded by gravity on its heated cells' masses and by the weight of each body
  resting on it, shared over its top cells under that body;
- solved (conjugate gradients, rigid modes deflated); the shared criterion
  (`fracture/BondFailure`) is evaluated on every bond and the bonds at damage 1
  are removed; and again at the same load until nothing more fails (**held** --
  or **broke**, if pieces came off on the way), it breaks through between its
  supports (**broke**: statics stops there, because what its pieces do next is
  motion, which the rigid world answers; a chip that comes off without parting
  the supports is solved on without), or a solve does not converge (**said so**,
  and nothing is broken on it).

A body statics leaves whole -- it held, or a solve could not say -- is not asked
again until its section falls or its load rises by more than 1%: asked again
unchanged, it would get the same answer at the same cost. The answer, and how
near its bonds came, is reported (`LiveStatics`, the MCP's `under_load`, the
Heat panel).

While statics works its answer out, the body is left as it is. A body something
struck is held still until its answer comes, so that its pieces are put where it
broke; a body at rest under its load has nothing to spring back from, and holding
it -- its velocity zeroed and it woken after every step -- only upset the contact
that carries the load. Found in the owner's room, where a host does not wait for
an answer: each held answer left the 258 kg block about a millimetre deeper in
the beam it rested on (4.1 mm to 9.3 mm over eight), and then the block fell
through a beam that had not broken (`the owner's room, answers not waited for`).
And an answer lasts as long as its load: once nothing rests on the body, statics'
answer and its throttle go (`an answer goes with its load`); a body that broke
keeps its last answer.

It replaced a dynamic lattice run started from contact, which a sustained load
does not have. Traced, what broke an overloaded shelf in that run was its
crate's resting cells -- sunk millimetres into it by the rigid solver's contact
allowance -- being pushed out, not the load.

### Measured

Statics against Euler-Bernoulli beam theory with the catalogue's modulus and
tensile strength: a 60 x 60 mm oak beam on a 1.2 m span, 1 kN at midspan
(`statics against beam theory`):

| cells deep | cells | midspan deflection (beam theory) | its bonds reach the criterion at (beam theory at 90 MPa) | cost |
|---|---:|---|---|---:|
| 3 | 540 | 2.53 mm (2.64) | 20.32 kN (10.98) | 3.5 ms |
| 4 | 1,280 | 2.30 mm (2.67) | 19.88 kN (10.94) | 13.1 ms |
| 6 | 4,320 | 2.12 mm (2.71) | 19.31 kN (10.89) | 64.7 ms |

- The lattice is 4-22% stiffer than beam theory with the catalogue's modulus,
  and more so as it is refined: its elastic constants are its own
  ([criterion checkpoint](criterion-energy-scaled-checkpoint.md) measures its
  C11). Measured here, not tuned.
- **It carries about 1.8 times what beam theory at the declared strength says.**
  It removes a bond at the damage end threshold, which is the catalogue's break
  multiplier (2) times the strain the strength gives; and a lattice n cells deep
  has its outer cells at (n - 1)/n of the half-depth. So there is a band where a
  body is offered and holds -- and statics says how near its bonds came.
- The shelf (`tests/beam_tests.cpp`, and the same through the C library in
  `tests/joint_binding_tests.py`): a 1.4 m concrete shelf 100 mm deep -- two
  50 mm cells -- under five 300 mm iron crates, 10.4 kN, 5.46 MPa by beam theory
  against 3: offered, and statics holds it at 46.9% of the criterion. Under five
  450 mm crates, 35.2 kN, 17.8 MPa: statics reaches 140.8% and it breaks --
  2,519 bonds in three rounds, 70 pieces, 12 ms. (A fourth solve, on the pieces,
  used to follow it and spend 840 ms running out of iterations; statics now stops
  where a body breaks through between its supports.)

## Both sides of the section

The survey's strength is the weaker side of the section: the lesser of the
tension strength times the tension-side bending factor (`bending`) and the
compression strength times the compression-side one (`bending_compression`).
For oak that is 52 MPa in compression against 90 in tension, and heated, the
compression side goes first -- 0.25 of it at 100 degC against 0.65.
`capacity_fraction` is against the cold governing strength. The heated plank of
`tests/thermal_mechanics_tests.cpp` is now offered 58.8 s into 8 kW, at 33.08 MPa
against 33.0, on its compression side (63.5% of it left).

## What burns leaves the shape

### Design and implementation

- **A box or a sphere** is cut again (`JoltWorld::reshapePrimitive`) every 0.2 mm
  of burning: the reference less the burned depth on every face, with the
  field's mass and inertia and its centre of mass at the box's centre. What rests
  on it comes down with its top, and it comes down onto what it stands on, by
  exactly what came off each face and without being woken (`planRecession`).
  Woken at every cut and left to settle, the room's 258 kg block on its 80 mm
  beam -- sunk a few millimetres into it, which Jolt allows up to 20 mm -- rolled
  a little further each time it was awake: 0.14 degrees before the first cut,
  1.9 after eight, 9.4 after eighteen, 28 mm to one side, and then off a beam
  that had not broken. A stack with a joint in it, or anything standing on
  something else as well, is left to the solver and woken as before.
- **A piece** is its cells. A cell with less than 2% of its matter left is taken
  away and the piece is rebuilt from the cells it has left (`reformFromCells`):
  it keeps its name while they still join, comes apart into pieces when they do
  not, and its joints are carried into its new frame. So a piece's outline
  recedes a whole cell at a time, while its mass and inertia follow the network
  continuously.
- **A body with nothing left** -- no cells, or no volume -- burns away: it leaves
  the world, its residue leaves the thermal network through the ledger
  (`left_kg`), whatever was fixed to it lets go and says why, and what it held
  up falls.
- **A joint** made at a point lets go once more than half a cell has burned away
  from under that point.

### Measured

- **A burning slat** (`what burns leaves the shape`): an 840 x 40 x 200 mm oak
  slat, two cells thick, bridging two concrete piers, a 60 mm iron cube resting
  on it and an iron weight hanging under it on a fixing; 8 kW. The fixing let go
  1,801.8 s in with 10.0 mm burned from under it, and said so. The cube settled
  38.93 mm with 19.60 mm burned from every face -- twice that is 39.20 mm: the
  slat's top comes down by what burned from it, and the slat by what burned from
  its underside, onto its piers. The slat burned away 3,354.1 s in, 98.5% of its
  load-bearing matter gone, and its 0.1575 kg of residue left the ledger once; a
  second later the cube was at y = 0.090 m, through where the slat had been. The
  ledger's residual: 1.4e-4 J on 1.8e7 J stored. 3,354 s of world in 13.4 s.
- **A piece rebuilt** (`a piece is rebuilt from the cells it has left`): a join
  of two oak boxes, a hull of 248 cells, under 8 kW. 1,664 s in, its first 4
  cells had gone and it had been rebuilt; it weighed 0.6451 kg against the
  network's 0.6447.
- **A heated 60 x 60 mm oak beam** with no load, 8 kW (`measure: a heated beam`):
  bending 56.1% at 151 s, when it was first cut again; 0% at 466 s, when its core
  passed 300 degC (574 K) and the whole section was char. It burned back
  0.42 mm/min (0.25 mm at 151 s, 4.81 mm at 796 s). 1,201 s of world in 3.0 s.

**Found and fixed on the way:** a body that left the network -- burned away, or
broken into pieces -- stayed among the shapes the host had last given until the
next refresh, so the coupling pass straight after brought it back as a fresh
lump at room temperature whenever a hot neighbour touched it: its matter joined a
second time, it drew heat from its neighbours, and it left a second time at the
refresh. The slat's 0.158 kg of residue left the ledger as 0.315 kg.
`ThermoWorld::remove` and `split` now forget the shape
(`tests/thermochemistry_tests.cpp`, "what leaves does not come back").

## Burning

The thermal network burns dry wood at the rate the air can bring oxygen to its
surface -- about 4.7 g/m2 s -- straight to carbon dioxide and steam. There is no
char substance: char is a mechanical state, a zone whose hottest passed
300 degC. For oak the rate is about 0.43 mm a minute from every face, so a 60 mm
beam loses its strength to heat long before it burns away, and a 40 mm slat
takes most of an hour to burn through.

## The owner's acceptance: two loaded beams

Two identical assemblies 3 m apart, each an oak beam 1.4 m x 60 mm x 100 mm --
three 20 mm cells deep, the least a lattice can bend -- on two concrete piers
1.04 m clear, under a 300 mm iron cube (212 kg); beside each, a 120 mm iron ball
(7 kg) on a pedestal for a second blow. A declared heater goes into one beam.
Followed through heating, the survey's question, statics' answer, the pieces,
cooling and a second blow -- the same ball dropped 1.5 m onto what is left of
each, 5.27 m/s. Nothing in the test sets a time, a temperature or a strength at
which anything happens. `banjo_thermal_geometry_long_tests`, labelled long, runs
it with the heater powers and the room's own build: 63 s on this build.

### Which heater lights it

What a heater does to the loaded beam in 900 s, and what is left 600 s after it
stops (`measure: heater powers`):

| heater | surface at most | burned | bending at least (compression side) | offered | statics | 600 s later: bending (compression side); kept when cold |
|---|---|---|---|---|---|---|
| 2 kW | 413 K | no, only dried | 75.4% (52.1%) | no | | 86.0% (70.0%); 100% |
| 3 kW | 465 K | no, only dried | 64.6% (34.9%) | no | | 79.2% (55.4%); 100% |
| 4 kW | 512 K | yes, 41 W released | 55.0% (21.1%) | no | | 67.3% (39.0%); 92.0% |
| 5 kW | 558 K | yes, 206 W | 46.9% (18.1%) | 877.5 s in | held, its bonds at 25.7% | 52.9% (22.2%); 82.5% |
| 6 kW | 625 K | yes, 1,347 W | 38.9% (15.0%) | 682.0 s in | held, 31.0% | 44.6% (17.2%); 78.8% |

### Oak, 8 kW for 12 minutes, then 6 minutes without it

| | heated | cold twin |
|---|---|---|
| as built | 1400 x 60 x 100 mm, 5.880 kg, inertia 0.0067 / 0.9653 / 0.9622 kg m2 | the same |
| 61 s | surface 424 K; its moisture gone: 5.787 kg; bending 88.6% | |
| offered, 336.5 s | 9.151 MPa by beam theory against the 9.148 its compression side had left (17.6% of 52 MPa). Surface 1029 K, core 374 K; bending 48.4%, tension 52.3%, compression 20.1%; its bonds' tension factor 0.502 on average, 0.347 at the weakest; 0.77 mm burned, 3.0 mm char; 1398.8 x 58.8 x 98.8 mm, 5.549 kg, inertia 0.0061 / 0.9092 / 0.9063 | never offered |
| statics | held on every ask, the first with its bonds at 25.0% of the criterion, until 658.75 s, when they reached 100.08%: broke, 4,719 bonds, 20 pieces, 221 ms | |
| last whole, 660 s | surface 1044 K, core 514 K; bending 12.1%, compression side 5.3%; 2.83 mm burned; 1394.4 x 54.4 x 94.4 mm, 4.926 kg, inertia 0.0049 / 0.8018 / 0.7994 | |
| the pieces | the halves and the 212 kg cube fell: 20 bodies by the end of heating (720 s), the largest 2.35 kg | |
| 6 minutes without the heater | still burning, so nothing cooled: the largest piece's surface 975 K and core 716 K at 1,081 s, 8.7 mm burned, 2.02 kg (see *Not done*) | 295 K -- it sees a little of the fire -- and bending 99.6% |
| second blow, 5.27 m/s | on a piece charred through: no bond left to break, so its bar is infinite and the blow broke nothing | its bar 10.92 m/s: held |
| cost | 1,080 s of world in 17.3 s, 62 times faster than real time; 137 lattice runs, 6.1 s in all, the costliest 221 ms (the break) | |

Statics was asked 135 times in all, about the beam and later about its pieces.
What the pieces do after the break is chaotic: builds in which the cube was woken
to settle at every re-cut ended heating with 136 and 158 bodies, and one of their
lattice runs took 7.9 s (a half-beam struck by the falling cube, the cube's
3,375 cells in the run).

### Oak, 3 kW for 15 minutes, then 10 minutes without it

| | heated | cold twin |
|---|---|---|
| end of heating, 900 s | surface 465 K, core 357 K; bending 64.6%, tension 66.5%, compression 36.3%; its bonds 0.655 on average, 0.580 at the weakest; no char, nothing burned; 5.787 kg, its moisture gone | 293 K, 100% |
| offered | never: its load needs 17.6% and its compression side kept 34.9% at the least | never |
| cooled, 1,500 s | surface 313 K, core 348 K; bending 79.2%, compression 53.7%; its bonds 0.774 on average, 0.760 at the weakest; it would keep 100% cold | |
| second blow, 5.27 m/s | its bar 7.65 m/s: held | its bar 10.98 m/s: held |
| cost | 1,500 s of world in 7.0 s | |

### Glass, oak and iron under the same 8 kW

| | glass | oak | iron |
|---|---|---|---|
| law | none | EN 1995-1-2 softwood curves | EN 1993-1-2 carbon steel |
| end of heating, 720 s | surface 540 K, core 446 K; 100% | broke at 658.75 s | 445 K; 100% of its strength |
| offered | never | 336.5 s | never |
| second blow: heated / cold bar | 4.506 / 4.506 m/s; neither broke | charred piece, infinite / 10.92 m/s | 12.397 / 12.270 m/s; neither broke |
| cost | 1,080 s in 4.5 s | 1,080 s in 17.3 s | 1,080 s in 4.4 s |

### The room's own build, answered as the room answers

The playground's yard has 40 mm cells, so the owner's beam is built 80 x 80 mm
-- two cells deep -- and the 300 mm block is a 320 mm, 258 kg cube. And the room
does not wait for an answer: it starts a fracture, steps on in batches of four
and collects the answer when it is ready (`the owner's room, answers not waited
for`, in the long suite). Measured: statics was asked 105 times; while the beam
was whole the block, which rested 0.69 mm into it, was never more than 1.49 mm
into it and never more than 0.19 degrees from level; statics broke the beam
760.2 s into 8 kW with its bonds at 106.6% of the criterion -- 108 bonds, 7
pieces -- and the block came down 442 mm (763 s of world in 2.4 s). Run again
with the rest of the long suite: 107 answers, the block within 1.49 mm and 0.22
degrees, and statics broke it 764.9 s in at 107.0%, 286 bonds, 8 pieces. An
answer lands on the step after the worker has it, so which step varies.

Before, this scene failed twice, in the page and then in this test: a body
waiting on statics was held, and its block sank through it; and then the beam's
re-cuts woke the block each time and it rolled off (*Sustained loads*, *What
burns leaves the shape*). In neither case had the beam broken.

And once the beam had broken, the block could hang in the air. Built by the
QA recipe `heated-beam` (`tests/qa_cases.py`, the same assemblies set down
through the MCP) and stepped ten seconds at a time, statics broke the beam
746.3 to 747.2 s into 8 kW at 100.3 to 101.4% of the criterion in six runs out
of six. In one, a cell came off first (54 bonds, 2 pieces), what was left was
asked under the same load 0.1 s later and broke at 417% -- the beam is two
cells deep, and a notch one cell deep leaves a quarter of its section modulus
-- and the block came down 437 mm. In the other five (4, 5, 5, 5 and 56
pieces) the block stayed where it had rested, 12 mm down, which is what the
re-cuts had taken off the beam's top, with none of the beam under it: in the
56-piece run the pieces were on the floor and the block 0.43 m above them,
still there at 1,020 s. It had slept on the beam through the re-cuts, and
Jolt wakes nothing when a body is taken out from under a sleeping one; the
pieces put in its place did not wake it either. What stood on or against a
body that comes apart is now woken (`LiveWorld::applyPending`), and in six
runs since the block came down 0.38 to 0.48 m.

Woken, the block does what a 212 kg block does to charred wood, and that found
three more faults, all in how a lattice run hands bodies back. Measured on the
owner's two beams at 20 mm cells: statics broke the heated oak into 20 pieces,
the block fell onto them, and the two halves, down to about a 2 m/s bar,
were crushed into 305 and 327 pieces (31 bodies to 664 in 0.25 s of world).

- A body that is only in a run to deliver the blow -- admitted neither to break
  nor to dent -- was handed back with its cells where the run had left them.
  The block was in several runs in 30 ms, its cells by then 0.13 m from where
  its box touched a piece, and it came out of the next at 188 m/s, then 500.
  It now comes out as it went in but for how it moved: its cells in their rigid
  layout, no permanent set, its name and its shape kept.
- A whole box that goes through a run came back square to the world, its cells
  keeping the tilt. It keeps its turn.
- An applied run never marked the bonds between the pieces it made as broken in
  the scene's matter, so a later run with two of those pieces in it took the
  bonds in alive, stretched across whatever gap had opened: two pieces 79 mm
  apart went in at 5 m/s and came out one body at 97.5 m/s. A bond between two
  bodies now starts broken, and a held body gets back only bonds inside itself.
  `tests/threshold_tests.py` had relied on this without knowing: every bond it
  saw put back in its six drops (16 between two pieces of the plate, 2 inside a
  piece one of those pulled on) came from these stale bonds. None is now, and
  its last check says so.

What is left is not the lattice. After the crush the world holds some 660
burning bodies, and it ran 29.25 s of world in 331 s of wall -- 11.3 times
slower than real time -- with only 40 lattice runs in all: the cost is in the
step, not in fracture. So the long suite's owner's two beams does not finish:
2,400 s after all three fixes it had not. See *Not done*.

## The laws

A law says, per material, a reduction factor against temperature for the
modulus and for each strength a failure can be decided by, what does not come
back when the material cools, where the curves are supported, and where every
number came from. `banjo_mechanics_report(world, 1)` / the MCP's
`list_substances` print all of it.

### Oak -- EN 1995-1-2 Annex B (softwood curves), reference-derived

| factor against 20 degC | 20 degC | 100 degC | 300 degC |
|---|---|---|---|
| tension (Figure B.2) | 1 | 0.65 | 0 |
| compression (Figure B.2) | 1 | 0.25 | 0 |
| shear (Figure B.2) | 1 | 0.40 | 0 |
| modulus, tension (Figure B.3) | 1 | 0.50 | 0 |

Straight lines between. The char line is the 300 degC isotherm (3.4.2): a zone
whose hottest has passed 300 degC is char and carries nothing, for good.

* **These are the standard's SOFTWOOD curves.** EN 1995-1-2 gives none for
  hardwood; using them for oak is an assumption, not a validation.
* What stays after cooling from between 200 and 300 degC is a **demonstration**
  value: nothing lost for good below 200 degC (where pyrolysis begins), falling
  linearly to nothing at 300.
* Composition: the load-bearing constituent is the thermal model's *dry wood*,
  0.88 of oak by mass. A body declared with less carries less in proportion (a
  **demonstration** rule of mixtures, never more than the catalogue's oak); what
  burns of it is taken out of the section.
* Not modelled: any direction but along the grain; moisture's own effect beyond
  what the curves contain; creep under load at temperature beyond what they
  contain; the little strength real char keeps.

### Iron -- EN 1993-1-2 Table 3.1 (carbon steel), reference-derived

| degC | 20 | 200 | 400 | 500 | 600 | 700 | 800 | 1000 | 1200 |
|---|---|---|---|---|---|---|---|---|---|
| every strength, k_y | 1 | 1 | 1 | 0.78 | 0.47 | 0.23 | 0.11 | 0.04 | 0 |
| modulus, k_E | 1 | 0.9 | 0.7 | 0.6 | 0.31 | 0.13 | 0.09 | 0.045 | 0 |

* Carbon steel's curves stand in for the catalogue's iron; wrought and cast iron
  are not covered by the standard.
* It recovers fully on cooling. That is what structural steel does from below
  about 600 degC; cooled from hotter, what it keeps depends on the steel and is
  **outside what is modelled** -- the answer is still given, and every report
  says `supported: false` with the reason.

### Concrete -- EN 1992-1-2, reference-derived

Compression from Table 3.1 (siliceous aggregate: 0.95 at 200 degC, 0.75 at 400,
0.45 at 600, 0.15 at 800, 0 at 1200); tension from 3.2.2.2 (1 to 100 degC,
falling to 0 at 600); shear follows tension, declared. **It does not recover**:
the hottest it has been governs. Its modulus, spalling and the further loss that
comes with cooling are not modelled.

### No law

Glass, aluminium, alumina ceramic, rubber and ice have no law. Heat does not
change what they can carry, and the reports say so rather than implying it was
checked.

## The section

The thermal network holds a body as one lump, or -- when it conducts too poorly
to be one temperature -- as a 3 mm surface layer over a core. So a section across
the direction a body carries load is at most three rings, each carrying its
share at its own factor:

    what burned away   gone
    the surface layer  at the surface's temperature; char once its hottest passed 300 degC
    the core           at the core's temperature

* **What burned** is worked out from the load-bearing inventory: the share of
  the dry wood the body started with that is gone, turned into a depth by
  letting every face of the body's box recede alike -- a **declared
  approximation**. Only that goes: moisture drying leaves the section alone.
* **Axial and shear** capacity: each ring's area times its factor, over the
  whole section's area.
* **Bending**: each ring's share of the section modulus, b d^2 / 6, times its
  tension factor (`bending`) and, separately, its compression factor
  (`bending_compression`). The survey takes the weaker side.
* **What it would keep if it cooled now** is the same sum with each ring at the
  reference temperature and its hottest where it is: what burned, the char and
  any lasting loss stay.

That is the resolution the thermal model has, and the answer says so: a thick
beam's char front creeping inwards is **not** resolved inside the core -- the
core goes from sound to weak as its one temperature rises. It is a fair picture
for a slender member (a 40 mm peg is 28% layer) and a poor one for a 300 mm beam.

## What is reversible and what is not

| | on cooling |
|---|---|
| the reduction a temperature causes (oak below 200 degC, iron below 600 degC) | comes back |
| oak between 200 and 300 degC | keeps the lasting loss its hottest caused (demonstration) |
| char (oak past 300 degC) | stays |
| what burned away | stays -- the inventory is used up, and the shape with it |
| concrete | keeps what its hottest caused |
| iron cooled from past 600 degC | let recover, flagged outside what is modelled |

The history that decides it -- each zone's hottest temperature and each body's
starting inventory -- is part of the thermal state. A refused step takes it back,
a copy is a save and assigning it back is a restore, and breaking or cutting a
body shares it out: every piece has used the same share of its load-bearing
matter as the body had and is as hot at its hottest.

## How failure is decided

Nothing new decides a failure. The paths the engine already had are fed the
heated numbers, and heat changing them is itself a reason to ask again.

**Joints made of a member.** A fixing, a tie or a spring can say which of its
two ends it is MADE of -- the peg, the rope segment, the limb
(`banjo_joint_member`, `member` on the MCP's `fix` / `tie` / `spring`). Cold, it
holds what was declared; where a declared strength was zero it holds the
member's own section times its material's strength (shear across a peg, tension
along it) -- so with a member, zero is no longer a weld. Every accepted step:

* its strength now is the cold one times the member's section factor, across
  the joint's load direction (a fixing's axis; the line between a tie's or a
  spring's two ends);
* `partOverloadedLinks` compares that with the load the solver measured in the
  step -- exactly as it always did for a rope or a peg -- and parts it if the load
  is past it, saying why: *sheared across its axis: carrying 318 N against the
  318 N it could still take (800 N cold) -- heated peg: surface 1072 K, core 352
  K; 0.1 mm burned away and 3.0 mm char; 34 x 34 mm of its 40 x 40 mm section
  still sound; 40% of its shear ... left*;
* **the re-check while nothing moves**: whenever the member's factor has moved
  by more than 0.2% of what the joint could take cold, both ends are woken, so
  the next step's solve MEASURES the load rather than remembering it from before
  the change, and the load survey is asked for at once. A gate asleep on its peg
  carries its weight all the same; a body told it weighs less as it burns is not
  woken by being told.

A joint with no member is exactly what it was declared, whatever heats it. And a
joint lets go of matter that has burned away from under it (*What burns leaves
the shape*).

**Beams.** The load survey (`LiveOverload`) takes the weaker side of the heated
section, so a heated beam is offered as overloaded when the bending it already
carried passes what either side of its section can take -- and a body whose
section has moved by more than 0.2% is surveyed on the next step, not at the next
60-step stride. `LiveOverload.capacity_fraction` and `why` say so, and statics on
its own heated lattice answers whether it breaks (*Sustained loads*). A body
struck is broken, if the lattice says so, in a lattice that carries its heated
state (*One material state*).

## Energy

A fixing is a rigid constraint and stores nothing, and the lattice a fracture is
run in starts unstressed, so neither holds elastic energy for a change of
property to create or destroy. An **elastic** made of a member does: its
stiffness follows the member's modulus, and at the stretch it has when that
changes the energy it holds changes by half the change in stiffness times the
stretch squared. That difference is handed to the thermal network as heat into
the member (`Ledger::mechanical_in_j`, `banjo_energy.mechanical_in_j`) -- a
crossing in the ledger like any other, so nothing is made or lost. Measured
(`tests/thermal_mechanics_tests.cpp`): an iron hook heated to 918 K took a
spring from 20,000 to 4,578 N/m (the law's 0.2289); the 32 kg weight settled
53.68 mm lower (Hooke: 53.25 mm); 8.17 J was handed to the ledger against the
8.42 J a quasi-static softening would release; the ledger's residual stayed at
5.7e-7 J.

Statics is quasi-static: it finds where the bonds fail at a load, and the pieces
it makes start at rest. The elastic energy its removed bonds held is not handed
to any ledger.

## The rigid solver, and what a joint is rated for

Two things found building the peg's acceptance assembly, both about the rigid
world rather than the law:

* **A light peg carrying a heavy gate sagged.** An iterative solver passes an
  impulse through a light body held between a heavy one and its support at
  about the ratio of their masses per iteration. With Jolt's default ten, a
  180 g peg carrying a 32 kg gate drooped 13 degrees, and the load its fixing
  read was the weight times the cosine of that. A fixing that makes exactly that
  arrangement -- a light moving body held by something that does not move and
  carrying something heavier, in whichever order the two fixings were made --
  now gives its island enough iterations to pass all but 1% of the heavy body's
  impulse, up to Jolt's limit (255: the override is 8 bits); the arithmetic the
  kerf already used. The same peg now holds its gate to within 1 mm and reads
  317.49 N of the 317.88 N it carries. Only that arrangement: a first version
  raised the count for any fixing between unlike masses, which reached a bow's
  nock (a light nocking point between its string and a heavier arrow) and
  changed what the bow threw, because the bow's limbs are soft springs whose
  behaviour depends on the iteration count (`tests/bow_tests.cpp` caught it).
* **A scene starts with every load suddenly applied**, and a suddenly applied
  load reaches up to twice its weight while a joint takes it up: measured, 1.33
  times the gate's weight on the first steps. A joint rated less than about
  twice what it holds can give way in the first moment. Rate it with margin, as a
  real one would be; the chat's guide and the MCP say so.

## The first acceptance scene: a heated peg

An anchored oak gatepost; a 40 x 40 mm oak peg, 160 mm long, standing 5 mm off
its face; a 32 kg iron gate welded 5 mm under the peg's outer half. The peg's
fixing is rated 800 N and made of the peg. An identical assembly stands 3 m
away. A declared 2 kW heater goes into the first peg. (Jointed bodies stand 5 mm
clear because the solver still makes contacts between two bodies a joint holds,
and a gate pressed into its own peg fights the weld that holds it.)

Measured in `tests/thermal_mechanics_tests.cpp`, all in a live world, at 42x
faster than real time:

| | |
|---|---|
| cold control, 20 s after taking up its load | the gate moved 0 mm; the fixing carries 317.49 N of the 317.88 N hung on it; holds 800 of 800 N; no re-checks |
| heated twin | the peg's surface chars within about 20 s; the fixing held exactly what the law left it on every one of 11,233 steps (0 N difference); it gave way **46.8 s** in, carrying 317.887 N against the 317.843 N left of 800 N -- surface 1072 K, core 352 K, 3.0 mm char, 0.1 mm burned away, 40% of its shear left -- and the gate fell to the ground |
| the cold twin beside it | 293.16 K (it sees a little of the fire), holds 799.98 of 800 N; its gate did not move |
| a different load | 2 kW each: the 316 N gate fell at 46.8 s, the 158 N gate at 73.1 s |
| an unloaded peg, heated the same | at 1187 K -- hotter than the loaded one, which its gate was cooling -- it still holds 156 N for its own 1.76 N |
| asleep when the heat began | 0 bodies awake; 295 re-checks woke it; it gave way at 52.8 s on the measured load |
| an iron peg in the same fire | at 394 K when the oak one gave way, holding 800 of 800 N |
| cooling | iron heated to 807 K lost to 67% (EN 1993-1-2 at 534 degC) and came back to 100%; oak whose surface reached 647 K kept 59% when cold -- no more than the 72% the law predicted while hot, because its core went on heating after the prediction -- and none of what burned |

Measured in headless Chrome, on the QA recipe's build (run 20260913-013619) and
on the chat's own (run 20260913-022827, gpt-5-mini): 0.9989 and 0.9992 of real
time at 60 frames a second from the start until 12 s after the gate had come to
rest; the fixing gave way about 47 s in, carrying 318 N against the 318 N it
could still take, and the cold twin held.

## Watching it

Start the playground against this branch's build and choose *An empty yard*:

    python -u playground/server.py --port 8774 \
        --engine <checkout>/build/heat/Release/banjo_platform_cli.exe \
        --studio <checkout>/build/heat/Release/banjo_network_lab.exe

and ask the chat:

> Lay an oak beam 1.4 m long, 60 mm by 100 mm, across two concrete piers and
> put a 300 mm iron block in the middle of it. Build an identical one 3 m away,
> and put an 8 kW heater on the first beam for 15 minutes.

The chat builds it with the MCP's own tools (`add_object`, `heat`). The yard's
cells are 40 mm, so what it builds is the room's own scene above: an 80 x 80 mm
beam under a 320 mm, 258 kg block. In the room the heated beam tints, then burns,
and is drawn smaller every 0.2 mm; the Heat panel shows its size now, its mass,
its strength falling, and -- once the survey asks, about seven minutes in --
statics' answer under its load and how near its bonds came. About twelve and a
half minutes in, statics says its bonds have reached the criterion and it gives
way under the block. The cold twin carries its block throughout.

Measured in the real page, in headless Chrome over the DevTools protocol, on this
branch's final build, merged with main at `2ef95e2`: the request above was typed
into the room's own chat, which built both assemblies in one turn (57 s). The
room then ran at 0.9999 of real time -- 781.76 s of world in 781.8 s, the worst
minute 0.997, 60 frames a second, no page errors -- through the break and the
20 s after it. The heated beam was drawn smaller 17 times, from 1400 x 80 x 80 mm
to 1393.2 x 73.2 x 73.2 mm. Statics was first asked 431.1 s in, its bonds at
24.2% of the criterion, and asked again as the section fell, holding on every
ask up to 97.7% at 756.1 s; at 759.8 s they reached 100.8% -- broke, 64 bonds, 4
pieces -- and the block came down between the piers onto the burning pieces,
which the ground broke further (39 objects in the room after). The cold twin
carried its block throughout. An earlier run of this branch, before a body that
comes apart woke what stood on it, happened to break so that the block came
down, the halves folding under it; through the QA recipe, five runs of six of
that build did not. Before the two fixes in *Sustained loads* and *What burns
leaves the shape*, the same run ended with the block on the floor under a beam
that had not broken, and the Heat panel saying "under its load: holds".

## What it keeps

Everything the one material state remembers is in owned structures, so that a
save can carry it (none of it is serialised yet):

- the thermal state, `thermo::ThermoState`: every lump's parcels, the hottest
  each zone has been, its starting inventory and layer depth -- already copied
  and restored for a refused step;
- `LiveWorld::MatterRecord`, one per body by name (`Impl::matter_of`): the
  reference box, where it sits in the body and how it is turned, whether it is
  round, the burned depth the shape was last cut at, the revision, the cells
  burned, the remaining volume, what the bonds keep, and the field last seen;
- the cells each body has left (`Impl::nodes_of`) and each body's `revision`;
- statics' last answer per body (`Impl::sustained_answers`) and the load and
  section it held at (`Impl::statics_held`);
- what burned away, when, its residue and why (`Impl::burned_away`).

What the last survey found resting on what (`Impl::sustained_by`) is worked out
again by every survey and need not be kept.

## Where it is reachable

| layer | what |
|---|---|
| engine | `thermo::lawFor`, `evaluateSection`, `materialField`, `cellShare`, `cellFactors`, `bondFactors`, `massProperties`; `ThermoWorld::matter`; `solveSustainedLoad`; `JoltWorld::reshapePrimitive`; `LiveWorld::setJointMember / materialStates / statics / burnedAway / mechanicsReport`; `LiveMaterialState.reference_m / remaining_m / mass_kg / inertia_kg_m2 / cells / cells_burned / bond_tension_* / revision`; `LiveBodyPose.revision`; `LiveJoint.member / rated_* / capacity_fraction / rechecks / parted_because / parted_load_n / parted_capacity_n`; `LiveOverload.capacity_fraction / why` |
| C API (ABI 19) | `banjo_joint_member`, `banjo_body_mechanics_count`, `banjo_bodies_mechanics`, `banjo_mechanics_report` (with `statics` and `burned_away`); `banjo_body.revision`; at the end of `banjo_body_mechanics`: `bending_compression`, `bending_compression_if_cooled`, `reference_m`, `remaining_m`, `remaining_volume_m3`, `mass_kg`, `inertia_kg_m2`, `cells`, `cells_burned`, `bond_tension_min / mean`, `bond_stiffness_mean`, `revision` |
| Python | `World.joint_member / body_mechanics / mechanics_report`; `member=` on `fix`, `tie`, `spring`; `Body.revision` and the new `BodyMechanics` fields |
| line protocol | `member` on `fix`, `tie`, `spring`; ops `member` and `mechanics`; `revision` on every body; a piece's cells in the room's stream whenever burning has changed them; the `mechanics` block with the size now, the mass, the cells, what the bonds keep, `statics` and `burned_away` |
| live wrappers | `playground/live_session.py` and `playground/live_inprocess.py` carry the same block |
| MCP | `member` on `fix`, `tie`, `spring`; `strength` in `thermal_state` and `run`, with `now_mm`, `as_built_mm`, `mass_kg`, `cells`, `cells_burned_away`, `lattice_tension_left_pct`, `under_load` and `burned_away`; `run` reports what gave way and why; `joints` says what each is made of; `list_substances` lists the laws |
| playground | char drawn darker by the share of the section that is char or gone; a body drawn again from what is left of it whenever its revision moves; the Heat panel's size now, mass, cells gone, statics' answer and what burned away, and its attachment rows; a fixing that gives way says why |

## Tests

| file | what |
|---|---|
| `tests/thermal_geometry_tests.cpp` | `banjo_thermal_geometry_tests`, on every push: the field is one state; statics against beam theory; a heated beam over time; what burns leaves the shape; a piece rebuilt from the cells it has left; an answer goes with its load. `banjo_thermal_geometry_long_tests`, labelled long and run by `.github/workflows/long-physics.yml`: the owner's two beams in glass, oak (8 and 3 kW) and iron, the heated oak's block coming down when statics breaks its beam; the heater powers; the owner's room, answers not waited for |
| `tests/thermal_mechanics_tests.cpp` | 11: the laws against their sources; the cold control; the heated twin; a different load; a sleeping assembly re-checked; cooling; a refused step; splits and restores; iron in the same fire; a softening spring's energy; a heated beam in the load survey, against oak's governing 52 MPa |
| `tests/beam_tests.cpp`, `tests/joint_binding_tests.py` | the shelf on both sides of statics' line, in C++ and through the C library |
| `tests/thermochemistry_tests.cpp` | what leaves the network does not come back |
| `tests/thermo_ffi_tests.py`, `tests/banjo_mcp_tests.py`, `tests/live_lanes_agree_tests.py` | the same through the C library, the MCP and both live lanes, at ABI 19 |
| `tests/qa_cases.py` | `burning-peg` and `heated-beam`: built by the chat or by the recipe, checked in the real engine. `heated-beam` follows the load onto whatever of the beam it stands on -- statics says "broke" whenever pieces come off, which is not always the span giving way -- until it comes down or the time is up |

## Not done

* **Hundreds of burning pieces are slower than real time.** At 20 mm cells the
  owner's heated oak, crushed by its block, becomes some 660 burning bodies,
  and the world then runs 11.3 times slower than real time (29.25 s in 331 s),
  the cost in the step rather than in its 40 lattice runs. The long suite's
  owner's two beams does not finish (2,400 s after the fixes above); where the
  step spends it has not been measured. The room's own build, at 40 mm, breaks
  into far fewer pieces.
* **A body that cracked and stayed whole heals on its next run.** An applied
  run never writes the bonds it broke back into the scene's matter; a run now
  starts with every bond between two bodies broken, but a crack inside one body
  is whole again the next time that body is run.
* **A body charred through keeps its shape.** EN 1995-1-2 gives char no strength
  and no stiffness, so a body charred all the way through has no live bond: its
  impact bar is infinite and statics cannot say where it gives ("char through").
  It keeps its shape and holds what rests on it until it burns away, although its
  section reads 0%: the unloaded 60 mm beam read 0% from 466 s and still spanned
  its piers at 1,201 s. The lattice's literal answer is that it comes apart into
  its cells -- one rigid body and one thermal lump per cell, which the network's
  pairwise coupling could not carry at the room's pace; the alternative is to
  give char a small residual strength. That choice is the owner's.
* **A fire does not go out.** Dry wood burns at the rate oxygen reaches it for as
  long as it is hot, and burning keeps it hot: there is no extinction criterion,
  so the heated beam's pieces burned on after the heater stopped and did not
  cool.
* **Every face recedes alike.** A beam on its piers burns from its underside as
  fast as from its top. The heat input already leaves out the faces in contact;
  the geometry does not.
* **The band between the survey and the lattice.** A beam is offered at the
  declared strength and breaks in the lattice at about 1.8 times it (*Sustained
  loads*): the declared strengths and the lattice's break multiplier are two
  numbers for one thing. Not tuned here.
* **Statics removes every bond past the criterion at once.** Near the criterion
  that is a crack growing round by round. At many times over -- a piece nearly
  charred through with something resting on it, asked about at 10.5 times its
  criterion in an earlier build of the owner's scene -- it is most of its bonds, and the piece comes
  apart in chunks of a few cells instead of cracking through. Removing the worst
  first, one event at a time, would crack it through; not done.
* **A lattice run with a heavy striker can be slow.** In one build of the
  owner's scene a falling half-beam struck by the 212 kg cube took 7.9 s of
  lattice, the cube's 3,375 cells being in the run. In the room it is worked out
  while the world goes on, and its answer arrives that much later.
* **A heavy statics solve can run out of iterations**; it says "did not
  converge", and the body is not broken on it.
* **A piece's outline recedes a whole cell at a time**; its mass and inertia
  follow the network continuously.
* **Thermal expansion** (D) is not modelled; nor any direction but along the
  grain.
* A fixing is checked against the force it carries, along its axis and across
  it -- not against a bending moment at its face.
* The section is at most three rings; there is no temperature field inside a
  body.
