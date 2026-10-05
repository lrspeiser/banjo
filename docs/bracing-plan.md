# Bracing deep holes: the plan

The owner's call, 2026-10-04: dug walls on cube ground hold, the way cubes do in Minecraft, until there is physics for braces that keep a hole open. Then a hole can go 5 or 10 cubes deep between wooden or metal braces.

## What happens now

On cube ground (25 cm cells), nothing caves in. `TerrainField::relax` returns at once when the surface is columns, so a dug hole keeps its vertical walls however deep it goes. Smooth and sharp-cut ground still settle as before:
- sand stands at about 33 degrees;
- soil stands a vertical face up to about 0.6 m.

## What comes next

### 1. Caving in comes back on cube ground, by depth

A dug wall is judged by how many cubes of it stand unsupported:

| Ground | Stands unbraced |
|---|---|
| Sand | 1 cube (25 cm) |
| Soil | 2 cubes (50 cm); about its 0.6 m critical height |
| Clay and weathered rock | 4 cubes |
| Rock | Any depth |

Past that, the cubes at the top of the wall slide into the hole as loose soil, one cube at a time, using the ground's existing slump code (`TerrainField::relax`) with whole cubes instead of thin layers. Water in the ground lowers each limit.

### 2. Braces

A brace is a made thing, built in the Workshop like any recipe:
- **Wooden frame:** a square of four oak posts and boards, one cube deep.
- **Steel frame:** iron or steel, one cube deep, stronger and thinner.

It is placed in a hole with the build guide, like a foundation pad, and fastened to the wall it touches. A braced cube of wall counts as supported. So the wall stands to the brace's rating:

| Frames | Depth they hold |
|---|---|
| Wood | 5 cubes (1.25 m) |
| Steel | 10 cubes (2.5 m) |

Frames stack, one per cube of depth.

The brace is a real body with a real load. The wall's earth pressure (active pressure, about half the weight of the soil column times its depth) pushes on it. A brace that is too weak bends or breaks, and the wall above it then slides in. That uses the same fracture and fastening code as everything else that is built.

### 3. What it needs

- A per-column "supported" mark kept with the ground and saved, set by a fastened brace and cleared when the brace is removed.
- An earth-pressure load applied to fastened braces each step, only while the hole is open beside them.
- Recipes for the two frames and a construction skill, "Shoring", earned by bracing a hole that then stands for a minute.
- Tests:
  - an unbraced sand wall slides past one cube;
  - a braced one holds to its rating;
  - removing the brace lets the wall go;
  - a too-weak brace fails under the measured pressure.

### 4. Order

Caving in by depth first, behind a world setting that is off by default. Then the wooden frame, then steel. Caving in is switched on by default only once braces can be made, so the change never makes digging worse without the fix being available.
