# Light on a spot: lasers, burning glasses and lenses

October 10, 2026. Branch `agent/light-spot`. This follows
[optics-checkpoint.md](optics-checkpoint.md), which ended with "the next step: a model where a
small lit spot heats faster than the rest of the body".

## What changed, in a sentence

Light used to warm the whole of whatever it landed on, so a 4.5 kW beam on a 20 mm oak rope
warmed all of the rope and took more than 30 seconds to burn it. Now light heats the spot it
lands on, and a beam strong enough takes the matter there away, the way a real laser does: the
same beam parts the rope in about two and a half seconds.

## What you can do

In a machine (`/machine` and the levels on `/play`):

- A **`laser` kit**: a small fixed housing and a narrow beam leaving it. You say where the beam
  leaves (`at_m`), which way it goes (`aim`, or `aim_at` a part, or `aim_m` a point), what it
  draws from its battery (`watts`), how much of that comes out as light (`efficiency`), how wide
  the beam is a metre out (`beam_width_m`), and whether its light is visible or near infrared
  (`band`). Glass and ice let visible light through and soak up infrared within a few
  centimetres.
- A **`lens` kit**: a disc of glass (or ice) with two curved faces, held in a part shaped to fit
  it. You give its shape ("convex" to bring light to a focus, "concave" to spread it), the radius
  of its faces, how wide it is and how thick. You do not give its focal length: the engine works
  out where the lens brings light to a focus from its shape, by tracing the light through its
  two faces. A lens can also be declared on any clear part (`light.lenses`).
- **Light that cuts.** Where a beam lands on oak or ice with enough power on a small enough
  spot, it chars the oak through or melts the ice, one lattice cell at a time; a rope it cuts
  through parts, and what hung on it falls. The `cut` station (`{"cut": "weight rope"}`) is met
  when light (or a blade) has cut a part in two. Each cell taken is news in the machine's events
  ("the light charred 8.0 cm3 of weight rope away (3544 J, 442.98 J/cm3)").

Level 6 ("Bounce the beam") is solved by its own two mirrors in about 5 seconds now, 3 runs in 3,
where it took 20.3 seconds before.

## Why a spot heats faster than the body it is on

A beam on a small spot pours heat into a little matter. That matter can only pass the heat on
into the rest of the body as fast as the body conducts it, so it gets hot long before the body
does. Wood conducts heat poorly, so a few watts on a spot a few millimetres across are enough to
char it, while the same few watts spread over the whole rope would warm it by a fraction of a
degree.

The engine holds a body's heat as one lump (a surface layer over a core). So a lit spot is held
beside the lump, as a store of its own: the heat light has put into a cell of the body towards
taking that cell's matter away.

## How the engine works it out

**Where the light lands.** The ray tracer records each place a ray gives some of its power to a
body: where, which way the ray was going, and the size of the bundle of light the ray stands for
(a sun ray stands for one square of its grid; a lamp's ray for its share of the lamp's cone,
growing with the distance it has come). The live world puts each record in the lattice cell it
landed in. Light absorbed on its way through glass or ice is shared along the ray's path, part
by part, by Beer and Lambert's law, each band at its own rate.

**Spots.** Lit cells that touch, and are lit alike, are one spot: a beam across several cells is
one spot, and so is the sun on a board. A spot grows from its brightest cell; a cell lit less
than a quarter as brightly as that starts a spot of its own, so the focus of a lens is not
averaged away into the dim light around it. A spot's area is the spread of the points light
landed on, across the face it lit (a uniform disc of radius R has a mean square distance from its
middle of R²/2, so the area is 2π times that), and one ray's bundle more.

A focused beam lands as a bright middle in a dim halo. So the engine also looks for the spot's
**core**: the disc round its middle in which the light brings the most beyond what that disc would
lose (below). Where the core is less than the whole spot, the core is the spot and the halo only
warms the body.

**What a spot loses.** A spot taking matter away is held at the temperature that matter goes at.
From there it loses heat two ways:

    conducted into the body    4 k a (T_gone - T_body)        a disc of radius a held at a fixed
                                                               temperature on a large body
                                                               (Carslaw and Jaeger, 1959)
    from its face              h A (T_gone - T_air) + e s A (T_gone^4 - T_air^4)

with k the body's conductivity and e its emissivity (the thermochemistry's own numbers), h the
room's film coefficient and A the spot's area. What the light brings beyond that goes into the
cells under the spot. What it brings short of that only warms the body, exactly as all light did
before: the spot then settles where the light in equals what it loses, and the engine reports that
temperature.

The conducted loss goes into the body, so the rest of the rope is still warmed by what flows out
of the spot. For oak this is small: a spot 25 mm across loses about 7 W at oak's char line, so a
beam has to put more than about 7 W on it before it chars anything (about 12 kW/m², close to the
heat flux at which wood is measured to ignite).

**Where matter goes, and what it costs.** Nothing here is a number for light. Whether heat can
take a material away, and at what temperature, is the thermochemistry's:

| Material | Gone when | Taking it from 293 K to gone costs |
|---|---|---|
| Oak | it chars, at its law's char line, 573.15 K (EN 1995-1-2's 300 °C isotherm) | dry wood (0.88) and ash (0.02) heated to 573.15 K, its moisture (0.10) driven off as water vapour where free water boils: 633 kJ/kg, 443 MJ/m³ |
| Ice | it melts, at 273.15 K | 333.55 kJ/kg (its latent heat) from its melting point: 306 MJ/m³ |
| Glass, aluminium, iron, concrete, rubber, ceramic | never: the model has no melting point for them | only warmed |

The cost of a cell is worked out from what that cell actually holds and how hot it is, each time:
a cell in a rope that is already warm costs less.

**Taking a cell away.** When a cell's spot holds what taking the cell away costs, the cell leaves
the body. Every bond through the cell goes with it -- its own, and the longer bonds the lattice
runs past it -- and the body is rebuilt from the cells it has left, as pieces where they no longer
join (the same rebuilding as a body whose cells have burned away). The cell's matter leaves the
heat network carrying its own energy and what the light spent on it; melted ice is handed on as
meltwater, to the room's water. What the spot held beyond the cost is given back to the body as
heat. A spot no longer lit gives its heat to its body.

**The ledgers.** Light's ledger is unchanged: every watt sent is heated, warms nothing, reaches the
ground, escapes, is scattered, unfollowed, or is still going at the bounce limit. Of what is
heated, the part that went into spots is counted too. The heat network's ledger counts light
into spots as heat in, what spots hold as stored heat, and the matter they take as matter out,
carrying its energy. So, for any body: light absorbed = heat into the body + energy spent taking
its matter away + heat still held in its spots, to rounding.

## Lenses

A lens is a disc of a clear material with two spherical faces. In its own frame its axis is z, its
middle the origin, the front face's vertex at z = -t/2 and the back face's at z = +t/2, and its
rim a cylinder of radius a (its aperture). A face's radius is signed the lensmaker's way: positive
when the face's centre of curvature lies ahead of it along the axis. A lens bulging both ways has a
positive front radius and a negative back one; zero is a flat face.

The tracer meets a lens's faces exactly, as the spheres they are, and does to the light there what
it does at any glass surface: Fresnel's share reflected, Snell's law for the rest, total internal
reflection past the critical angle, and Beer and Lambert's absorption along the path inside. Where
the light comes to a focus is what all that makes of the lens's shape; it is never declared. The
engine also reports the focal length the lensmaker's equation gives for a thick lens,

    1/f = (n - 1) [1/R1 - 1/R2 + (n - 1) t / (n R1 R2)],    back focal distance = f (1 - (n - 1) t / (n R1)),

and the test checks that traced light focuses there. The part holding the lens still collides as
its own box; light meets only the lens.

## Measured

From `tests/light_spot_tests.cpp` and `tests/optics_tests.cpp` (Windows, Release, 20 mm cells,
1/240 s step):

| What | Measured |
|---|---|
| A lamp of 5 kW (4.5 kW of light, 0.3° half angle, 64 rays) off a polished aluminium mirror onto a 20 × 20 × 300 mm oak cord holding a 13.6 kg iron weight, 2.5 m from the lamp | The cord absorbs 1779 W, all in one spot of 488 mm² (3.6 MW/m²), held at 573.15 K; 1772 W of it takes oak away. The cell under it goes at 2.40 s and the weight falls at 2.47 s. The cell cost 3545 J for 8 cm³: 443.15 MJ/m³, against 443.29 by hand from the model for oak at 293.15 K (the cell had warmed a little) |
| The same, saved after 1 s with 1765 J held in the cord's spot | Opened again with the same 1765 J; both worlds' weights fall at the same moment |
| Half the beam, and a quarter | The cord parts 1.96 and 3.91 times later; the power taking oak away is 2.01 and 4.05 times less |
| A 10 W lamp on the same cord | It absorbs 3.6 W; its spot would lose 6.5 W held at the char line, so it settles at 459 K and nothing is taken in 20 s |
| The mirror under the 4.5 kW beam | It absorbs 360 W (8%); after 10 s the plate is at 294.5 K and its spot at 331 K. Aluminium melts at 933 K; nothing in the model takes it away anyway |
| A 20 mm glass pane in the 4.5 kW beam | It absorbs 735 W along the beam's way through it (Beer and Lambert: 742 W less its faces' reflection), and passes the rest to a target behind it. Never cut; its spot would be 3264 K (see the limits) |
| An ice cord in the beam | Infrared (100 per metre): it absorbs 3054 W within the cord and parts at 1.03 s, the melted cell costing ice's latent heat to the joule (333,550 J/kg). Visible (1.5 per metre): it absorbs 103 W and melts nothing in 4 s |
| A wider beam (0.6°, 256 rays) on the cord, without and with a convex glass lens 0.1 m before it (faces of radius 100 mm, 12 mm thick, 60 mm across) | Without: the cord catches 970 W on a spot of 1552 mm² and parts at 9.78 s. With: 1747 W on 13.7 mm², parted at 2.14 s |
| A 100 mm glass ball's focus on an oak board in full overhead sun | Its focus is a spot of its own: 0.22 W over 4.3 mm² (51 kW/m², a hundred times the open sun's), which would lose 0.30 W held at oak's char line. So it warms the oak there to 502 K and does not char it |
| A 2 kW filament heat lamp 25 cm from a 20 × 20 × 100 mm oak cord (optics tests) | The cord absorbs 786 W on one spot and parts at 5.2 s, by charring (it burned through in 16.3 s when heat was spread through the cord) |
| A mirror tipped 20° about x and turned 45° about y | Every ray off it within the precision of Jolt's float shapes of the law of reflection about the normal the engine reports |
| Convex and concave glass lenses, faces of radius 100 mm, 60 mm across, in an overhead sun | Convex, 12 mm thick: the lensmaker's equation puts the focus 93.0496 mm beyond the back vertex; 100 traced rays within 6.4 mm of the axis, their crossings run back to h = 0 (spherical aberration goes as h²), meet it at 93.0501 mm. Concave, 3 mm thick: -95.5460 by the equation, -95.5466 traced back (a virtual focus before the lens). A ray 27 mm out focuses at 80.6 mm and -81.6 mm: spherical aberration. The light ledger closes to 3e-13 W |

From `tests/machine_world_tests.py`: the laser machine (level 6's laser with one mirror) burns
its rope through at 2.05 s and the weight is in the bin at 2.3 s; without the mirror the beam goes
past and the weight hangs. With a beam twice as wide, the rope catches 1100 W over 1389 mm² and
is burned through at 6.92 s; a `lens` kit 0.1 m before it (the engine reports f = 96.9 mm, its
focus 93.2 mm beyond its back vertex) brings 1753 W onto 31.5 mm² and the rope goes at 2.03 s.
Level 6's own solution: the weight is in the bin at 4.85 to 5.25 s, 3 runs in 3.

## Limits

- **A cell is the smallest thing light can take away.** A beam narrower than a cell (20 mm here)
  chars or melts the whole cell, and pays the whole cell's cost. In life it would drill a hole the
  width of the beam, and a narrow static beam would not part a rope. The cost is never less than a
  real kerf's.
- **The spot settles at once.** The time a spot takes to warm to where its matter goes is not
  modelled. For a laser's spot that is a few microseconds; for a weak beam near the threshold, on
  wood, it can be minutes.
- **Heat does not spread sideways from a spot** into the cells round it, other than into the body's
  lump. Cells next to a spot are not pre-warmed.
- **A hole that does not cut a body in two** is not a hole to the light: a body's collision shape is
  the hull of its cells, so light landing on the hull over a hole is placed in the first cell
  further along the ray, or, if it finds none, warms the body. Through glass or ice, light is
  absorbed along the whole hull, hole included.
- **Glass and metals do not melt here.** The thermochemistry has no melting point for glass, iron
  or aluminium, so a beam can heat them past where they would really soften or melt and they stay.
  A 4.5 kW visible beam through a 20 mm pane would put its spot at about 3300 K; a real pane would
  crack or melt.
- **Anchored scenery is not cut.** Light warms it and reports its spot's temperature.
- **A laser is a point source** with a cone; it has no aperture of its own.
- **Lenses** are spheres meeting a cylinder: no aspheres, no coatings. The part holding a lens
  collides as its box. A broken lens is plain glass.

## Where the code is

- `src/optics/RayOptics.{hpp,cpp}`: where light was absorbed (`Absorption`), each ray's bundle
  (`Ray::section_m2`, `spread_sr`), and lenses (`Lens`, `meetLens`, the lensmaker's equation).
- `src/thermo/ThermoWorld.{hpp,cpp}`: spots (`SpotDeclaration`, `Spot`, `Removal`,
  `removalEnergyJ`, `takeAway`), their loss and temperature, the ledger's spot lines.
- `src/fastlattice/LiveWorld.{hpp,cpp}`: `placeLitSpots` (where light landed, spots, cores),
  `takeLitCells` (a cell goes), `lens`, the light scene's lens faces, saving.
- `tools/live_world_run.cpp`: the `lens` operation, and each reply's spots, cells taken and lenses.
- `scripts/machine_world.py`: the `laser` and `lens` kits, `light.lenses`, the light events.
- Tests: `tests/light_spot_tests.cpp` (`banjo_light_spot_tests`), `tests/optics_tests.cpp`
  (lenses, a tipped mirror, the heat lamp), `tests/machine_world_tests.py` (class `Light`).
