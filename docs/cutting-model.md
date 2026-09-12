# Blades, and cutting that changes what things are

This is the declared model behind `LiveWorld::blade()`, the physical grip
(`LiveWorld::wield()`), and everything a blade does to the matter it passes
through. It is written down before the code that implements it, and the
numbers at the end are measurements of that code, not of this page.

There is no `cutting_power` and nothing is destroyed on touch. A blade is an
ordinary body with a declared edge. What happens when the edge meets something
is decided by the geometry of the edge, the materials on both sides, how the
two are moving, and how hard they are pressed together -- and the only way the
world changes is that bonds between cells are severed, one at a time, each for
a stated amount of work.

## 1. What a blade is

A blade is declared ON a body that already exists, the same way a pin is: two
names in, a joint out. The body supplies the matter -- its cells, its material,
its mass, its inertia and its collision shape all come from the lattice exactly
as they do for every other body. The declaration adds only what the lattice
cannot resolve, all of it written down in the body's own frame so it travels
with the body wherever it is carried:

| property | meaning |
| --- | --- |
| `heel`, `tip` | the edge, a straight line from where it starts to the point |
| `facing` | which way the edge faces: perpendicular to the edge, in the blade's plane |
| `thickness_m` | the blade's thickness across its flats |
| `edge_radius_m` | how sharp it is: the radius of the edge. The edge's contact width is `w = 2 r` |
| `bevel_deg` | the included angle of the edge wedge |
| `grip` | where a hand holds it: the grip attachment |

From these the blade has three axes, all body-fixed: `t` along the edge (heel
to tip), `n` the facing, and `f = t x n` the normal to the flats. The region
of the body within the edge line is the EDGE; the faces normal to `f` are the
FLATS; the end of the edge line is the TIP.

Mass distribution is not declared, because it is not a property of the edge:
it is the matter. A sword whose pommel and grip are part of the same joined
body balances nearer the hand because that is where the extra cells are.

The blade's material bounds what it can cut. An edge can only deliver a
contact pressure up to its own indentation hardness `H_b`; a target at least as
hard (`H_t >= H_b`) flattens the edge instead of being cut, so it is not cut.

## 2. What resists the edge

The target's material supplies two catalogue numbers that every material in
this engine already declares: its fracture energy `G` (J/m^2) and its
indentation hardness `H` (Pa). Advancing an edge of engaged length `L` a
distance `d` through uncut material creates `L d` of new separated area and
costs

```
    W = R L d          R = G + H w          (w = 2 * edge_radius)
```

`G` is the energy of the new surface. `H w` is the work of crushing the strip
of material the edge's own width has to push aside -- the reason a dull edge
does not cut. A razor (`w` of microns) pays almost only `G`; a 1 mm dull edge
in oak pays 35 kJ/m^2 of crushing on top of 1 kJ/m^2 of fracture.

**The resistance is a plastic one, applied in the solver.** While an edge is
engaged, a constraint joins the blade and the target at the engaged part of
the edge, with the blade's own axes. Along `n` it is free, with a one-sided
force limit: a velocity motor driven to no relative motion, whose force may
push the edge back out and may never pull it in, bounded by `[0, R L]`. The
blade does not advance at all until it is pushed harder than the material
resists, and when it does advance the material resists with exactly the
limit. That is a `SixDOF` constraint's translation motor in Jolt's velocity
solver, which is what makes a slow press either cut or not cut, rather than
creep:

```
    push along n  <  R L     the edge rests on the material; nothing is cut
    push along n  >  R L     the edge advances, and the material takes R L
```

**Slicing.** Drawing an edge along its own length while pressing it in cuts
with less push, because the work is energy per unit AREA and the tangential
motion delivers it too. With the edge's in-plane velocity `(v_n, v_t)` and the
resistance taken along that velocity (frictionless flanks), the energy balance
`F . v = R L v_n` gives

```
    F_n = R L / (1 + xi^2)      F_t = R L xi / (1 + xi^2)      xi = v_t / v_n
```

-- the slice-push ratio. Pushing straight in (`xi = 0`) needs the full `R L`;
drawing the edge three times as fast as it sinks needs a tenth of it. The
limits along `n` (the one-sided motor) and `t` (a friction) are set from the
velocity at the start of each step, so the solver applies exactly this. The
ratio is regularised at `eps` = 20 mm/s, `F_n = R L (v_n^2 + eps^2) /
(v_n^2 + v_t^2 + eps^2)`, so that an edge at rest is held with all of `R L`.

**Withdrawal is free.** The resistance opposes the edge ADVANCING into
material. A blade drawn back out of its kerf is not resisted (the grip of the
kerf walls on the flanks is not modelled -- see section 9). It is free because
the motor's force is one-sided, not because anything decides which way the
edge is going. A first version used a two-sided friction and switched it off
for a retreating edge; a solver bounce of -20 mm/s then switched it off under
a pressing blade for one step, and the blade fell into the wood unresisted.

**The solver has to be able to deliver it.** The constraint is kept from step
to step while the engaged part of the edge stays within two cells of where it
was, so each step starts from the last step's impulse. A new one starts from
nothing, and an iterative solver passes an impulse through a light target held
between a heavy blade and its support at about the ratio of their masses per
iteration: after `N` iterations `(1 + m/M)^-N` of it has not been passed. So a
new kerf's first step gets `ceil(ln 100 / ln(1 + m/M))` iterations, which pass
all but 1% of it, up to 400; every later step gets 40. Measured: a 1.97 kg
blade resting on a 28 g batten sank 1.2 mm into it in the first steps with 40
iterations, and 0.014 mm with the 327 this gives.

**Fast strikes are not tunnels.** An edge crossing a thin rope at 10 m/s goes
through it in less than one 1/240 s step. The engaged length is therefore not
the length touching now but the area the edge's path will sweep through uncut
material this step, divided by its advance: `L_eff = A_swept / (v_n dt)`. A
rope 20 mm thick struck at 10 m/s is charged for 20 mm of it, not for the
42 mm the blade travels in the step. That is the rule for ANY edge moving into
material, not only a fast one: in the step an edge comes out of the far side,
what it touched at the start is more than its path crosses, and charged for
what it touched a 400 mm^2 rope was booked at 480 mm^2. Only an edge at rest is
held by the length it touches.

## 3. The work is measured, not assumed

The impulse the constraint actually applies in a step is known per axis, `J`,
and so is the relative velocity along that axis before and after the step.
The work the resistance did is its force times the distance the edge went
against it:

```
    W_step = J_n max(0, (v_n,before + v_n,after) / 2, v_n,after)
           + |J_t| max(|v_t,before + v_t,after| / 2, |v_t,after|)
```

For an edge LOSING speed the first term is `J (v_before + v_after) / 2`, which
is exactly the kinetic energy the impulse took out of the relative motion,
whatever the two masses -- and that is where the energy of an edge stopped
dead inside one step went, although the steel did not move. For an edge
GAINING speed, driven through by more than `R L`, a step moves it by its speed
at the END of the step, further than its mean; the resistance acted over that
distance, and did `J v_after` of work. (Charging the mean there let an edge
pushed through at 800 N run ahead of what it had paid for by half a step's
gain in speed, every step.) What this leaves unaccounted between the work and
the pair's change of energy is the step's own `M dv^2 / 2`, which is never
negative: no cut is paid for with energy that was not there.

That is the accounted-for mechanical work. The area it bought is
`A_step = W_step / R`, and the kerf is advanced by exactly that area along
each engaged part of the edge's path. So:

- no area is ever cut without its energy having left the blade and target, and
- no energy leaves through the cut without area being cut for it.

If the blade runs out of energy half way through a rope, half the rope's
section is marked cut and the rest is not. That is a partial cut, and it stays
one.

**A kerf is one cut in from the surface.** What a step marks starts at the
kerf's frontier under each part of the edge, or at the surface where nothing
has been cut yet, and runs forward from there -- never from wherever the edge
happens to be. An edge can be in matter ahead of the frontier (the first steps
of a press before it is held, a step the solver did not quite finish); that
matter is under the blade's own steel, found by walking back from the edge
through uncut matter the blade is in, and it is paid for with what the edge
sweeps next. Marking only from where a step's path met matter left a gap
behind it, and a kerf kept as one interval per strip then closed the gap for
nothing: an 800 N press through a batten separated it for 3.75 J of a 6 J
section.

Each part of the edge's path is laid into the strips it actually crosses,
piece by piece: an edge slicing along its own length crosses a strip every few
millimetres, and laid down as one rectangle at the middle of its path, a
12 m/s slice through a rope booked 88% of the rope's section and severed four
of its bonds. A part of the edge covers a sample's width of the kerf, several
strips, and its path goes into every strip in that width that has matter in
it -- and only those: a strip beyond the body's face has nothing to cut or to
pay for. **A strip holds every stretch the edge has swept through it**, not
one. An edge that turns or slides as it cuts -- which is what a swung edge
does -- crosses each strip's matter somewhere new; kept as one stretch grown
from its end, a strip refused a mark that did not touch it, the mark was
counted as cut anyway, and the strip never caught up. In the armoury a flick
across the oak panel left such strips every 12 mm along the kerf, and they
held the panel together. Stretches closer than an eighth of a cell -- the
resolution the path is followed at -- are one stretch; a wider gap is uncut
matter and stays uncut.

What a step buys is laid down as the same share of what the edge went through
in every strip, so the strips go in together, and what it did not buy is
still under the steel for the next step to find and pay for. The one
exception is **the step in which the edge comes out of the far side**: no
later step sweeps that matter again, so everything it went through in that
step is cut, and whatever the step's work did not cover is taken there and
then from the closing motion -- one equal and opposite impulse between blade
and target along the way the edge faced, sized to the declared cost and
audited by the solver, whose measured work is what is booked. Left standing,
that last stretch was a strip at the far edge of a panel holding its halves
together.

**An edge overpowered at rest.** An edge held still by something ELSE -- a
batten lying on the floor, pressed to it -- while the hand and gravity push it
in harder than `R L` has matter under its steel that cannot be what is holding
it. That matter is cut, at its declared cost `R` per square metre: the energy
is the push's, delivered in the step that stopped the blade and taken by the
other contact, and with nothing moving there is no impulse left to measure it
by. A push short of `R L` cuts nothing this way: the 181 N a 200 N hand has
left after holding the blade up rests on oak that resists with 300 N for as
long as it is held there.

## 4. How a cut changes connectivity

Matter here is cells joined by bonds, and a body is whatever set of cells its
live bonds hold together. Cutting is the removal of bonds, and nothing else.

Each body keeps its **kerfs**: for each separate cut, the plane the blade
passed through (in the body's own frame) and a map, in strips a quarter of a
cell wide, of the part of that plane the edge has swept through the body's
material -- every stretch of each strip it has been through. A bond is severed when it crosses a kerf's plane at a point the kerf
has swept. Severed bonds are written into the scene's matter, which is the
same record every later lattice run reads -- so a notch put into a plank is
still there when the plank is later loaded, dropped or broken.

- **A partial cut stays partial.** A kerf that stops short of the far side
  leaves the bonds beyond it alive: the body is still one body, with the same
  collision shape, carrying a kerf. It is drawn with the kerf showing.
- **Going back into an old kerf costs nothing**, because the material there is
  already cut: the resistance counts only uncut material ahead of the edge.
  And an edge can come back into its own slit from outside the body: the
  body's rigid shape knows nothing of the slit, so a path that runs into a
  kerf in the blade's own plane is a meeting like any other -- the rigid
  contact is suspended and the edge runs down the slit to where the last
  stroke stopped. (Met at the mouth, a second stroke along a partial cut was
  stopped there, and the cut could never be carried on.)
- **A rope is cut where its links are, too.** A rope is a run of bodies tied
  by links. A link whose line crosses a kerf at a swept point INSIDE the
  matter of one of its two bodies is severed with the bonds -- the fibres
  between two segments are cut with the segments. A bare link hanging in air
  (a rope made of one constraint, like the courtyard sign's) has no matter to
  cut, and a blade passes through it: build ropes that can be cut out of
  segments.

**Separation.** When the severed bonds leave a body's cells in more than one
connected group, the body is replaced by its pieces -- through the same
fragment builder a fracture uses:

- each piece's **mass** is the sum of its cells' masses, and its **inertia**
  is taken about its own centre of mass from those cells (with each cell's own
  `m h^2 / 6`);
- each piece's **velocity** is the velocity field the whole body had at those
  cells, `v + w x r`, so momentum is conserved exactly by the split;
- each piece **collides** as the convex hull of its own cells (or, where Jolt
  cannot build that hull, as its cells);
- every **joint** on the body follows the piece that holds its attachment
  point in its matter, and a joint whose matter has gone is reported detached.
  Each END follows its own point: a link is tied at two points, one either
  side of a join, and the end on the cut body is found where that end was
  tied, at the pose the body had when it came apart. Cut a segment through its
  middle and the tie above stays on the upper piece, the tie below on the
  lower. A load hanging on a rope whose segment was cut in two falls with the
  lower piece, because the link that held it is attached to that piece. (The
  first version looked for both ends at the one point a pin's ends share; a
  rope's are a cell apart, nothing was found within a cell, and the ties both
  sides of a cut segment came off -- seen in the room, and now checked.)

Pieces are named `<body> piece N`, like the pieces of anything else that comes
apart, and inherit the kerf that made them.

## 5. What distinguishes edge, flat, glance, press and slice

The categories are not separate code paths with different rules. There is one
contact law, above; these are the regimes it falls into, and the engine
reports which one each contact was so a host can say so.

When the blade's path is about to take it into a target's matter, the engine
finds where -- which face of which cell the edge crosses, and that face's
outward normal `N` -- and the relative velocity `a` of the edge there. An edge
that is already in the matter as the step starts is judged against its kerf's
frontier if it is lying at one, and otherwise against the surface NEAREST it:
a contact's slop lets a flat pressed with 800 N sink millimetres into oak, and
the edge along its side goes in with it, and that edge is lying along the
surface, not facing into it. (Judged as facing it, a pressed flat bit with its
side edge and cut the batten it lay on.) Then:

1. **The edge must be what meets the surface.** The edge can only bite if its
   facing points into the surface more steeply than its own bevel:
   `n . (-N) >= sin(bevel / 2)`. Shallower than that and the bevel lies on the
   surface and rides along it.
2. **The edge must be what leads.** In the blade's own frame the motion must
   be more edge-forward than sideways: `a . n > 0` and `a . n >= |a . f|`.
   Moving more across the blade than along its facing means the flat leads.
3. **It must be pressed in.** Either the edge is moving into the surface, or
   the hand and gravity are pushing it in.

| regime | how it is recognised | what the world does |
| --- | --- | --- |
| **flat** | rule 1 fails with the flat facing the surface, or rule 2 fails | an ordinary rigid contact: the flat pushes, bounces, skids. Nothing is cut |
| **glancing** | rule 1 fails with the edge nearest the surface (the bevel rides), or the edge bites but arrives at less than 15 degrees to the surface | the first skids like a flat; the second bites only as deep as its small inward motion lets it -- a nick |
| **edge** | bites, moving at 0.25 m/s or more, mostly edge-forward | cuts until the energy runs out: through, or partly |
| **slice** | bites, moving faster along the edge than into the material | cuts with the reduced push of section 2 |
| **press** | bites at under 0.25 m/s | cuts only while the push exceeds `R L`; stops dead when it does not |
| **point** | the tip meets a face head-on, moving along the blade | an ordinary rigid contact. Piercing is not modelled |

A cut does not need speed. A slow press cuts oak if the hand can push harder
than `R L`, and a fast strike does not cut if the edge meets the target flat.

**Brittle targets are not cut.** A material with no yield point in the
catalogue (glass, ceramic, ice, concrete) does not separate under an edge; it
cracks, and cracking under a blow is what the lattice fracture already does.
An edge meeting one of those is an ordinary contact, which the break
handshake can then judge like any other blow.

## 6. The kerf holds the blade

Once the edge is embedded (more than a millimetre into material), the same
constraint also stands in for the kerf's walls: the blade cannot move
sideways across its flats, and cannot twist in the kerf about its edge or its
facing. It CAN turn in its own plane, which is how an edge follows a curved
swing. So a blade stuck half way through a plank drags the plank if the hand
pulls it sideways, and levering it does not open the kerf. While a blade is
engaged, the rigid solver's ordinary contact between it and that target is
suspended -- the edge law replaces it -- and it is restored the moment the
blade is clear of that target's matter. The pieces a cut makes are in ordinary
contact with the blade from the moment they exist: their cut faces bear on its
flats. The cells the blade passed through stay with one piece, so a piece can
start out overlapping the steel by up to a cell; that is inside the contact's
penetration slop, and the solver keeps it from growing rather than throwing the
piece off. (Suspended until clear instead, a piece never was clear, slid into
the blade under the hand's push, and was cut a second time for nothing.)

## 7. The grip

`wield(name, grip)` takes hold of a body at a point on it and drives it with a
hand that has a bounded force and a bounded torque, and nothing else:

```
    M   = ( 1/m + [r]^T I^-1 [r] )^-1                   the grip's mass, by direction
    w'  = min(w, sqrt(strength / (50 mm * m)))
    F   = m g_up + M (w'^2 e - 2 z w' v_grip)           the second part capped at
                                                        strength - m g; |F| <= strength (800 N)
    tau = I (w^2 theta - 2 z w omega) - r x F           |tau| <= torque     (60 N m)
```

`e` is how far the grip is from where the hand wants it, `theta` how far the
body is turned from where the hand wants it turned, `r` the arm from the
centre of mass to the grip, `w` = 100 rad/s and `z` = 0.9. The force acts AT
the grip, so swinging a sword by its handle puts the swing into it the way a
hand does, and the wrist supplies what is left of the turn after the grip
force's own moment. The hand carries the body's weight (`m g_up`) so it does
not sag until an error pays for it -- and carries it FIRST: only what is left
of its strength after the weight goes to moving the body. Capped as one
vector instead, a hard swing spent the weight's share on the swing and the
sword dropped 100 mm on the way through, under the rope it was aimed at.

`M` is the grip's effective mass matrix. A force at the grip both moves the
body and turns it, so across the arm the grip is lighter than the body -- a
1.9 kg sword held 0.35 m from its middle is 0.6 kg across the grip -- and
along the arm it is the whole mass. Every direction answers at the same rate
`w'` with its own mass, so every direction stays inside what an explicit
240 Hz step can follow: `w'` is at most 100 rad/s, a tenth of a step per
radian. Sized for the whole mass instead, the damping across the arm came to
2.2 of a step's worth, past the 2 an explicit step can take; the sword rang at
the step rate, and a blade ringing in a kerf cuts what nobody pushed it to.
Along the arm the hand reaches full strength at 50 mm off, as the haul always
has. The wrist's gains are the held body's own inertia for the same reason,
because a thin blade's roll inertia is small enough that any fixed torque gain
would ring far above the step's Nyquist limit.

Nothing about this is a teleport. A swing is the hand pulling as hard as it can
towards where it wants the blade; the blade gets there as fast as 800 N and
60 N m can take it, and when the edge meets more than they can overcome, the
blade slows, turns aside or stops in the cut.

Editor repositioning is separate and stays what it was: `grab()` carries a
loose body exactly where it is put, and that is placement, not physics. A
host that wants a person to FIGHT with something uses `wield()`.

## 8. What a cut does to what a plank can hold

The load survey (`overloaded()`) asks each body what bending its supports and
its load put in it. A body carrying a kerf is also asked at the kerf: the
bonds still alive across the kerf plane are the ligament that is left, and its
depth and breadth give the section there. The bending moment is taken where
the kerf is. So a plank that held its load and is then half cut through at
mid-span is overloaded by the same statics that said it was fine -- a quarter
of the section modulus at the place the moment is largest -- and a host that
answers it runs the lattice on a plank whose severed bonds are already there.

## 9. What this does not capture

Said plainly, because every one of these would change an answer:

- **Wedging and flank friction.** The blade's thickness does not cost work:
  the kerf walls are taken as opening elastically and the flats as
  frictionless. A thick blade therefore cuts as easily as a thin one of the
  same edge, and pulling a stuck blade back out is free.
- **Edge wear.** An edge never dulls or chips, however much it cuts. Hardness
  only decides whether it can cut at all.
- **Anisotropy.** `G` and `H` are one number per material. Real oak cuts far
  more easily along the grain than across it; here it is the same both ways.
- **The kerf is one plane per cut, one cell wide in matter.** The engine's
  cells are 10-40 mm and a blade is thinner than that, so the bonds across the
  kerf's mid-plane are what is severed, and the cells the blade physically
  passes through stay with one side. Separation happens when the last bond
  across the plane goes, which can be up to half a cell before the edge has
  swept the whole section; the energy consumed by then is correspondingly
  short of `R` times the full section, by at most half a cell in the depth.
- **A partial kerf does not change the collision shape.** A notched plank
  still collides as its box; only its connectivity, its drawing and its load
  survey know about the notch.
- **The kerf holds rigidly.** Sideways and twisting motion of an embedded
  blade is locked, not resisted by a crushing strength, so a blade cannot be
  levered through the side of its own kerf.
- **Piercing.** A thrust with the point is an ordinary contact.
- **Brittle materials.** Not cut, as above -- cracked, by the lattice, when a
  blow is hard enough.
- **Anchored scenery** is the world, and is not cut.
- **Very light targets under heavy blades.** A new kerf's first step gets at
  most 400 iterations, which pass 99% of its impulse down to a target 87 times
  lighter than the blade. Lighter than that -- a 5 g sliver under a 2 kg blade
  -- and a resting blade can sink into it a little before the kerf holds.
- **Ropes are chains of rigid links between light bodies,** and an iterative
  solver does not hold the length of a chain whose load is hundreds of times
  heavier than its links: the armoury's first rope, 7.9 kg on 26 g segments,
  hung 0.6 m long with gaps between segments that a blade passed through
  without touching anything. Keep a rope's load within a few tens of its
  segments' mass.

## 10. Measured

From `tests/blade_tests.cpp`, which prints every number it checks, at 10 mm
cells and a 1/240 s step, on the real engine (Jolt and the lattice, nothing
stubbed). Every check is against the physics, not a number tuned until it
passed.

| check | measured |
| --- | --- |
| the work is the energy lost | an iron blade into a free oak block at 6 m/s, no gravity, nothing else touching: the pair lost 5.079 J of kinetic energy, the kerf's measured work was 5.075 J (0.08% apart), and that bought 1127.8 mm^2 at R = 4.5 kJ/m^2 -- 11.3 mm deep |
| a partial cut stays partial | the same block: 104 bonds severed, still 104 a second later, one body carrying one kerf |
| pieces have their own mass and momentum | a 9 m/s chop through a 280 g batten: pieces of 200 and 200 cells, 140 g each; momentum along the strike -4.2498 kg m/s before, -4.2495 after |
| an edge that has paid for a section gets through it | the sword's bar, 1.9 kg, flying level at 12.1 m/s (138 J) into the edge of a hung oak panel 400 mm across and 20 mm thick; at R = 15 kJ/m^2 the section costs 120 J: 120.0 J of cutting for 8003 mm^2 of its 8000, and the panel in two pieces |
| a press short of R L cuts nothing | a 2 kg blade in a hand of 200 N, which carries the blade's 19 N first and pushes with the 181 N left, onto 20 mm of oak that resists with R L = 300 N, for a second: no bond severed, the edge 0.014 mm into the surface |
| a press past R L cuts | the same blade, the same oak, an 800 N hand: through in two pieces for 4.65 J, 78% of R times the section -- separation comes when the last row of bonds goes, three quarters of the way |
| a slice cuts what a press cannot | the 200 N that could not press through, drawn along the edge: 24 bonds, two pieces |
| an edge strike parts a rope | 16 m/s edge-first through a hanging rubber rope: 24 bonds, the segment in two, the weight falls from 0.69 m to the floor; none of the rope's nine ties comes off -- the ones either side of the cut follow its two pieces |
| the flat does not | the same strike with the flat leading: nothing cut, reported as a flat, the weight still hanging |
| blunt and brittle | an iron edge pressed with 800 N onto iron ("blunt") and onto glass ("brittle"): nothing cut |
| a notch changes what a plank supports | an oak batten 2 m across its piers carrying 170 N holds at 44 MPa; a blade dropped 233 mm onto it beside the load (4.5 J) chops a 10.9 mm notch, 27 bonds, and the same load is now 122.8 MPa at the notch against oak's 90: overloaded |
| the hand is bounded | pulled towards a target a metre off, the blade accelerates at 406.574 m/s^2 at most against 800 N / 1.9675 kg = 406.607; driven edge-first at an anchored iron wall, the edge stops at the wall's face (2.7 mm of contact slop) |

The same claims are checked again through each way in: the C ABI and the
Python binding (`tests/blade_binding_tests.py`: an edge cuts a rope, the flat
does not, a wielded blade holds its height and turns 90 degrees to its aim,
bad edges are refused), the MCP server (`tests/banjo_mcp_tests.py`: an 800 N
press edge down goes through oak for 70-115% of the section's energy, flat
down it cuts nothing; an edge off its body is refused), and the room itself
(`tests/world_room_tests.py`: the armoury's statics; a swing through the rope
over the same pipe the browser uses, edge leading and flat leading; and
strokes across the panel with the page's own hand -- one flick at 7.3 m/s
parts it for 118.9 J of its 120, the upper piece still on both fixings and
the lower on the floor, and a slow stroke that stops 27 mm in, drawn back and
followed by a flick along the same cut, parts it too).
