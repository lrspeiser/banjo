# Heat and strength

Temperature, composition and what has burned now change what a body can carry,
and the failures that follow are the engine's own: a joint parts when the load
the solver measures passes what is left of it, and a beam is offered as
overloaded when the bending in it passes what its section can still take. There
is no "fire destroys object" rule, no burn timer and no universal "hot means
weak" multiplier: each material has its own declared law, with its sources, and
a material with no law is not changed at all.

Branch `agent/thermal-mechanics`. Engine: `src/thermo/ThermalMechanics.{hpp,cpp}`
(the laws and the section), `src/thermo/ThermoWorld.*` (the irreversible history
each body carries), and the coupling in `src/fastlattice/LiveWorld.cpp`.

This closes the gap `docs/thermochemistry.md` stated -- "temperature does not
yet change any mechanical property or cause failure" -- for increment 1 of the
owner's specification (A and C). What burned is taken out of the **load-bearing
section and the mass**; taking it out of the collision shape, the drawn shape,
the centre of mass and the inertia is increment 2 (B), and thermal expansion is
later still (D). Both are listed under *Not done* at the end.

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
* **Bending** (the load survey): each ring's share of the section modulus,
  b d^2 / 6, times its tension factor -- the survey's criterion is the tension
  side, so it follows the tension curve. The compression side softens faster
  (0.25 against 0.65 at 100 degC) and its yielding is not modelled.
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
| what burned away | stays -- the inventory is used up |
| concrete | keeps what its hottest caused |
| iron cooled from past 600 degC | let recover, flagged outside what is modelled |

The history that decides it -- each zone's hottest temperature and each body's
starting inventory -- is part of the thermal state. A refused step takes it back,
a copy is a save and assigning it back is a restore, and breaking or cutting a
body shares it out: every piece has used the same share of its load-bearing
matter as the body had and is as hot at its hottest.

## How failure is decided

Nothing new decides a failure. The two paths the engine already had are fed the
new numbers, and heat changing them is itself a reason to ask again.

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

A joint with no member is exactly what it was declared, whatever heats it.

**Beams.** The load survey (`LiveOverload`) multiplies the material's strength
by the section's bending factor, so a heated plank is offered as overloaded when
the bending it already carried passes what its heated section can take -- and a
body whose section has moved by more than 0.2% is surveyed on the next step,
not at the next 60-step stride. `LiveOverload.capacity_fraction` and `why` say
so.

**A known gap:** the lattice a fracture is worked out in still uses every
material's room-temperature bonds. A heated beam the survey offers as overloaded
is broken, if the host asks, with cold bonds -- so it can come out "held". The
attachment path has no such gap: a joint parts in the rigid world on the
measured load.

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

## The rigid solver, and what a joint is rated for

Two things found building the acceptance assembly, both about the rigid world
rather than the law:

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

## The acceptance scene

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
| a heated plank bridging two piers under 212 kg | offered as overloaded 190.7 s into 8 kW at 33.09 MPa against 33.09 MPa, with 36.8% of its section left -- the law's number to the digit |

## Watching it

Start the playground against this branch's build and choose *An empty yard*:

    python -u playground/server.py --port 8776 \
        --engine <checkout>/build/thermal/Release/banjo_platform_cli.exe \
        --studio <checkout>/build/thermal/Release/banjo_network_lab.exe

and ask the chat:

> Hang an iron gate on an oak peg in an oak gatepost, with the peg rated to hold
> 800 N, and put a 2 kW torch on the peg until it gives way. Build an identical
> one beside it that nobody heats.

The chat builds it with the MCP's own tools (`add_object`, `fix` with `member`,
`heat`). In the room the peg tints, then darkens as its layer chars; the Heat
panel shows its strength falling and the attachment's load against what it can
still take; about 50 s in the gate gives way, the chat's log says why in the
numbers that decided it, and the gate falls through the rigid world. The cold
twin hangs where it was.

## Where it is reachable

| layer | what |
|---|---|
| engine | `thermo::lawFor`, `evaluateSection`, `ThermoWorld::matter`, `LiveWorld::setJointMember / materialStates / mechanicsReport`; `LiveJoint.member / rated_* / capacity_fraction / rechecks / parted_because / parted_load_n / parted_capacity_n`; `LiveOverload.capacity_fraction / why` |
| C API (ABI 16) | `banjo_joint_member`, `banjo_body_mechanics_count`, `banjo_bodies_mechanics`, `banjo_mechanics_report`; new fields at the end of `banjo_joint`, `banjo_overload`, `banjo_energy` |
| Python | `World.joint_member / body_mechanics / mechanics_report`; `member=` on `fix`, `tie`, `spring` |
| line protocol | `member` on `fix`, `tie`, `spring`; ops `member` and `mechanics`; a trimmed `mechanics` block on every reply that describes the world |
| live wrappers | `playground/live_session.py` and `playground/live_inprocess.py` both carry `member`, `mechanics` and the block |
| MCP | `member` on `fix`, `tie`, `spring`; `strength` in `thermal_state` and `run`; `run` reports what gave way and why; `joints` says what each is made of; `list_substances` lists the laws |
| playground | char drawn darker by the share of the section that is char or gone; the Heat panel's strength and attachment rows; a fixing that gives way says why |

## Tests

| file | what |
|---|---|
| `tests/thermal_mechanics_tests.cpp` | 11: the laws against their sources; the cold control; the heated twin; a different load; a sleeping assembly re-checked; cooling; a refused step; splits and restores; iron in the same fire; a softening spring's energy; a heated beam in the load survey |
| `tests/thermo_ffi_tests.py` | the same through the C library |
| `tests/banjo_mcp_tests.py` | the same through the MCP |
| `tests/live_lanes_agree_tests.py` | both live lanes carry the same `mechanics` |
| `tests/qa_cases.py` | `burning-peg`: built by the chat, checked in the real engine |

## Not done

* **Increment 2 (B):** what burned leaves the load-bearing section and the mass,
  not yet the collision shape, the drawn shape (char is a tint), the centre of
  mass or the inertia. A log burning down still occupies its full box.
* **The lattice** a fracture is run in uses room-temperature bonds (see above).
* **Thermal expansion** (D) is not modelled.
* A fixing is checked against the force it carries, along its axis and across
  it -- not against a bending moment at its face.
* The section is at most three rings; there is no temperature field inside a
  body.
