# Materials

Eight of them, and which one you choose decides almost everything. These are the
numbers the engine actually uses, and the behaviour measured out of it — not
handbook values quoted at you.

## What the engine is told

| | E (GPa) | density | tensile | compressive | shear | yield |
|---|---|---|---|---|---|---|
| iron | 211 | 7870 | 250 | 600 | 170 | **200** |
| aluminium (6061-T6) | 68.9 | 2700 | 310 | 250 | 207 | **276** |
| glass (soda lime) | 70 | 2500 | 45 | 1000 | 35 | — |
| alumina ceramic | 300 | 3900 | 300 | 2200 | 240 | — |
| oak | 12 | ~700 | 90 | 52 | 11 | **45** |
| rubber | ~0.01 | 1100 | 20 | 15 | 4 | **6** |
| ice | 9 | 917 | 1 | 5 | 1 | — |
| concrete | 30 | 2400 | 3 | 35 | 5 | — |

Strengths in MPa, density in kg/m³.

A **yield strength** is what makes denting possible: it is the stress at which
the material stops springing back. The four without one are brittle — they go
from elastic straight to broken, with no range in between where they deform and
stay in one piece.

Glass being **22× stronger in compression than tension** is why it shatters in
bending and crushes hard. Concrete's 3 MPa tensile is why it is so easy to break
and comes apart into so many pieces.

## What they actually do

A 100 mm ball of each, dropped onto a concrete floor:

| | bends above | breaks above | 5 / 10 / 20 / 40 / 80 m/s |
|---|---|---|---|
| iron | 14.2 | 35.6 | held · held · **dent** · broke · broke |
| aluminium | 26.4 | 47.8 | held · held · held · **dent** · broke |
| oak | 10.4 | 13.7 | held · held · held · **dent** · broke |
| rubber | 29.0 | 100.7 | never broke at any speed tried |
| glass | — | 8.7 | held · held · broke · broke · broke |
| ceramic | — | 264.8 | brittle, and very tough |
| concrete | — | 0.7 | brittle, and very weak |
| ice | — | 2.3 | brittle, and very weak |

Ductile materials bend and then break. Brittle ones are whole or in pieces.

### Bouncing

Same drop, measured as the fraction of the fall height it comes back:

| | off concrete |
|---|---|
| rubber | 32.6% |
| ice | 22.3% |
| glass | 17.5% |
| oak | 16.0% |
| aluminium | 15.9% |
| ceramic | 14.9% |
| iron | 14.5% |
| concrete | 13.8% |

That ordering is the catalogue's damping ratios showing through — rubber is the
least damped at 0.05, concrete the most at 0.30 — not a number anyone picked.

---

## Designing an experiment that shows something

### Use a span, not a slab

**What breaks a plate is having nothing under the middle of it.** The same plate
lying flat on the floor is supported everywhere and will not break however hard
you hit it. Bridge it between two piers.

### Reach for iron to do the hitting

A threshold depends on the *impedance* of the striker, not only its speed. The
same glass pane:

| striker | needs |
|---|---|
| iron ball | 4.5 m/s |
| glass marble | 6.8 m/s |
| aluminium ball | 6.7 m/s |

Iron's impedance is 4.07e7 against glass's own 1.32e7, so far more of the pulse
is transmitted into the target. Aluminium's is 1.36e7 — almost the same as glass
— so it is a poor hammer. **If you want to break something, hit it with iron.**

### Drop it from higher, not make it heavier

A fall of *h* metres arrives at `sqrt(2 × 9.81 × h)` m/s:

| fall | arrives at |
|---|---|
| 0.5 m | 3.1 m/s |
| 1.0 m | 4.4 m/s |
| 2.0 m | 6.3 m/s |
| 5.0 m | 9.9 m/s |
| 10 m | 14.0 m/s |

Mass does nothing at all. Measured, onto the same pane, from the same 1.0 m
fall:

| ball | mass | hit at | needs | result |
|---|---|---|---|---|
| 60 mm iron | 0.89 kg | 4.37 | 4.51 | held |
| 120 mm iron | 7.12 kg | 4.37 | 4.51 | held |
| 200 mm iron | 32.97 kg | 4.37 | 4.51 | held |
| 300 mm iron | **111.26 kg** | 4.37 | 4.51 | held |

### Thickness changes the outcome, not the bar

A 20 mm and an 80 mm glass plate are admitted at the same 4.5 m/s, because the
admission bound is about the transmitted pulse and does not depend on geometry.
What thickness changes is what the lattice then does:

| plate | same ball, same drop |
|---|---|
| 20 mm glass | shattered into 19 |
| 40 mm glass | held |

20 mm is also the thinnest anything can be at a 20 mm cell. **Real window glass
is 4–6 mm and is not reachable** without a finer grid, which costs about `h^-4`.

### Keep concrete and ice small

They break at 0.7 and 2.3 m/s and come apart into hundreds of pieces. A
600 × 200 mm concrete plate produced 291 fragments; an 80 mm one exceeded Jolt's
contact budget outright. Past 250 bodies fracture stops working altogether.

---

## A limit worth knowing

**The engine judges the blow, not the load.**

The admission bound is a stress-wave argument: it asks whether the transmitted
pulse carries enough strain to fail a bond. That is the right question for a
fast impact and the wrong one for a heavy weight sitting still.

Measured: **111 kg resting on a 600 mm span of 20 mm glass for six seconds
offered zero breaks.** The pane sagged 0.07 mm and held. In the world that pane
would be at or past failure under the load alone.

So: things break in Banjo by being *hit*, not by being *loaded*. There is no
bending or quasi-static failure path. If your experiment depends on something
sagging until it snaps, it will not, and that is the engine's limit rather than
your scene's.

---

## One number to check

Aluminium's compressive strength (250 MPa) is below its yield strength
(276 MPa), so in compression it would fail before it yields and denting is
unreachable for it in that direction. For 6061-T6 the compressive yield is
normally about equal to the tensile yield. This may be deliberate; it is the
kind of number worth a second look, and it would explain odd aluminium
behaviour.
