# Object authoring API and starter presets

This is the implemented `material-network-v2` interface, checked against source
`b15f860`. A program supplies geometry, material properties, initial state and
solver settings in JSON; `PlatformWorld` constructs and advances the world.
The engine derives mass, inertia, contact proxies, internal links and surfaces.
The Python helpers below author that same format. No LLM runs on a physics tick.

The presets are **current experimental lab settings**, not calibrated standards
for household doors, kitchen knives, fruit or engineering materials. The
[material showcase](material-showcase.md) records unresolved glass fracture,
cutting convergence and the absence of complete slice separation.

## 1. Calls a program can use today

The persistent, host-thread C++ API lives in
[`PlatformWorld.hpp`](../src/platform/PlatformWorld.hpp). Link `banjo_platform`.

| C++ call | Input | Result and use |
|---|---|---|
| `PlatformWorld::capabilitiesJson()` | None | JSON capabilities and backend-specific ABI requirements |
| `PlatformWorld::load(package_json)` | Complete initial-state JSON string | New owned world; parse/admission errors throw; an existing world is not modified |
| `world->fixedStep()` | None | The admitted timestep, seconds |
| `world->step(fixed_steps)` | Integer 1 through package `max_steps_per_call` | `{completed_steps, elapsed_s, wall_ms, error}`; elapsed time is cumulative |
| `world->renderInstances()` | None | Current rigid tools and physical cells, transforms, geometry and identities |
| `world->renderSkins()` | None | World-space blocky triangles for network objects, material, revision and provenance |
| `world->renderBonds()` | None | Endpoints, live/failed status, damage, plastic extension and cell IDs |
| `world->reportJson()` | None | Per-object mass, position, damage, components, events, performance and numerical limits |
| `world->packageJson()` | None | Original authoring package; it does not contain evolved damage or motion |
| `world->supportMesh()` | None | Ground triangles for the renderer |
| `world->fractureCount()` | None | Cumulative number of failed links |

Call these on the owning host thread. A runtime fault is sticky; stop using a
faulted world for gameplay. `step()` can complete only part of a requested batch;
inspect both `completed_steps` and `error`. A faulted step is not guaranteed to
roll back all intermediate state. Budget/argument errors may throw directly.
This API has no live `spawnObject`, deletion, impulse command, property edit,
joint builder, savegame restore, HTTP server or JavaScript/WASM binding yet.

It is also C++, reachable only from inside this tree. The live lane now has a C
face — one flat header, a shared library, CMake install and export rules, and a
Python binding — described in [building-on-banjo.md](building-on-banjo.md).
That is the surface to reach for when the caller is another program.
Loading a changed package starts another simulation, with fresh histories.

```cpp
#include "platform/PlatformWorld.hpp"
#include <stdexcept>

// packageJson is the complete JSON generated below.
auto world = banjo::PlatformWorld::load(packageJson);
auto receipt = world->step(8); // 1/60 second with a 1/480-second package.
if (!receipt.error.empty() || receipt.completed_steps != 8)
    throw std::runtime_error("Simulation stopped: " + receipt.error);

auto instances = world->renderInstances();
auto skins = world->renderSkins();
// Draw rigid instances, plus skins for network objects. Drawing every network
// instance and its skin together would duplicate the object's visual surface.
auto measurements = world->reportJson();
```

In a game loop, accumulate elapsed wall time, step only in fixed increments and
keep unfinished time as explicit backlog when the host's work budget is reached.
`max_steps_per_call` bounds a call's work count; it is not a frame deadline.
Do not call the CLI once per frame: a CLI invocation starts a new process/world.

## 2. Python authoring and CLI calls

[`banjo_authoring.py`](../examples/authoring/banjo_authoring.py) uses the standard
library only (Python 3.10+). Keep it beside
[`presets.json`](../examples/authoring/presets.json).

| Helper | Contract |
|---|---|
| `catalog()` | Read the five materials and twelve independent object templates |
| `make_material(preset, **overrides)` | Copy a material and change accepted property fields; use `id` to assign a new identity |
| `make_object(preset, object_id, **overrides)` | Produce an object declaration with a caller-supplied ID; overrides use exact engine JSON field names |
| `make_package(objects, materials=None, ...)` | Assemble the v2 envelope and required capabilities; omitted materials use all five catalog entries; omitted ground means no ground |
| `write_package(package, path)` | Write a new file; refuse overwrite and non-finite JSON numbers |
| `EngineCLI(executable).capabilities()` | Read the installed runtime's capabilities |
| `EngineCLI(...).validate(path)` | Construct and report initial state without stepping; performs actual engine admission, not physical validation |
| `EngineCLI(...).run(path, steps)` | Fresh world, 1–24,000 fixed steps, final JSON report |
| `EngineCLI(...).export_skin(path, steps, output)` | Fresh world, 0–24,000 steps; write derived triangles to a new file and return report |

The helpers do not replace engine validation. `EngineError` retains the JSON
error report and exit code. Timeout errors propagate; a timed-out stateless
process does not provide a resumable simulation. The Python functions are an
authoring/client convenience, not new C++ mutation methods.

```python
from banjo_authoring import EngineCLI, make_object, make_package, write_package

objects = []
for lane, (preset, x) in enumerate([
    ("glass_panel", -0.4), ("wood_panel", 0), ("iron_panel", 0.4)
]):
    objects.append(make_object(preset, 2*lane + 1, position_m=[x, 0.2, 0]))
    objects.append(make_object(
        "iron_ball", 2*lane + 2,
        position_m=[x + 0.015, 0.21, 0.2], velocity_m_s=[0, 0, -6]
    ))

package = make_package(objects, ground={
    "half_length_m": 2, "half_width_m": 2, "friction": 0.4
})
path = write_package(package, "work/my-panels.json")
engine = EngineCLI("build/win-joint-double/Release/banjo_platform_cli.exe")
initial = engine.validate(path)
result = engine.run(path, 1440)  # 3 seconds from the original initial state.
```

From the repository root, the executable example is:

```powershell
python examples/authoring/create_scene.py --engine build/win-joint-double/Release/banjo_platform_cli.exe --output work/panels.json --speed 6 --steps 1440
```

Any language able to write JSON and invoke a process can also use the CLI
directly, without the Python helper:

```text
banjo_platform_cli --capabilities
banjo_platform_cli --validate scene.json
banjo_platform_cli --run scene.json 1440
banjo_platform_cli --skin scene.json 72 skin.json
```

These commands return JSON on stdout and a nonzero exit code on failure.
`skin.json` must not exist. Exported meshes identify
`derived_render_data: true` and `simulation_snapshot: false`.

## 3. World settings: the package envelope

All distances are metres, time seconds, masses kilograms, forces newtons and
energy joules. The world uses +Y up; the usual gravity is `[0,-9.81,0]`.
The v2 header must be `package_version: 2`, `physics_abi: "banjo-network-2"`,
`backend: "material-network-v2"`, `units: "SI"`. The top-level v1 ABI in the
capabilities response is not the ABI to use for this backend; consult its
`backend_packages` entry.

| Field | Required / default | Meaning and admitted range |
|---|---|---|
| `name` | Required | Package label, at most 120 characters |
| `required_capabilities` | Required | At most 16 supported capability strings; unknown capabilities reject |
| `materials` | Required | 1–16 property declarations with unique string IDs |
| `objects` | Required | 1–32 object declarations with unique integer IDs |
| `fixed_dt_s` | Required; helper uses `1/480` | Fixed step in `[1/4800,1/240]` seconds; smaller steps cost more and change numerical response |
| `max_steps_per_call` | Required; helper `240` | Integer 1–240; C++ batch admission, not total run duration |
| `solver_iterations` | Optional, `24` | Integer 4–128; more constraint iterations do not replace temporal/spatial convergence |
| `temporal_policy` | Optional, `"diagnose"` | Diagnose reports unresolved spring frequencies; `"require-resolved"` rejects such a package |
| `contact_budget` | Optional, `{body_pairs:65536, constraints:32768}` | Integer resource capacities: pairs 128–262144, constraints 64–65536; pairs must be at least constraints |
| `gravity_m_s2` | Required; helper `[0,-9.81,0]` | Each component in `[-30,30]` |
| `ground` | Required, `null` for none | Otherwise `{half_length_m, half_width_m, friction}`; half extents 0.1–10 m, friction 0–2 |

Ground is the fixed plane at Y=0, backed by a 0.1 m thick support. Its contact
material is currently derived from the **first material entry**, with friction
overridden by `ground.friction`. There is no explicit ground material ID in this
ABI, so preserve catalog order for matched tests. No bowl field is accepted by
this backend; the older bowl-capable backends have separate schemas/laws.

Packages are at most 4 MiB. The world admits at most **1,024 physical bodies**,
counting every occupied network cell and each rigid object. The report lists a
20,000-link limit, but there is no separate link-count admission check: the
current nearest-neighbor construction and body cap already bound generated
links below it. These counts are not realtime guarantees.
The loader also checks an initial AABB envelope expanded by the actual Jolt
speculative-contact distance against both contact capacities. This is a
conservative initial-density check for the convex v2 bodies; it does not bound
future collisions or swept motion. A later capacity failure faults the world
and the failed tick is not accepted. Increasing capacity reserves resources;
it does not improve material accuracy or guarantee frame time.
`make_package(..., contact_budget={"body_pairs":65536, "constraints":32768})`
sets an explicit budget. The runtime report returns the effective capacities,
initial pair envelope, actual speculative distance and last/peak manifold and
point callback counts. `temporary_arena_bytes` reports the capacity-derived scratch reservation
(32 MiB plus per-constraint scratch; at most 256 MiB).
These are contact-listener observations, not exact
allocator occupancy or measured contact impulses. Optional estimated impact
events are disabled in v2; Jolt still owns and solves all contacts. See the
[contact and fracture checkpoint](contact-fracture-checkpoint.md).
The loader rejects unknown fields and invalid values; do not rely on duplicate
JSON keys being rejected in this mechanical parser—generate unique keys.
Unlike the v1 parser, v2 does not comprehensively reject initial overlaps or
below-ground placement; the authoring program must check initial placement.

The default timestep is the current demo setting, not a resolved-glass preset.
The frequency diagnostic excludes contact stiffness and does not certify
material accuracy. Keep its result alongside performance and damage metrics.

## 4. Object criteria

```json
{
  "id": 2,
  "name": "Iron projectile",
  "material": "iron",
  "shape": "sphere",
  "representation": "rigid",
  "dimensions_m": [0.08, 0.08, 0.08],
  "position_m": [0.015, 0.21, 0.20],
  "orientation_wxyz": [1, 0, 0, 0],
  "velocity_m_s": [0, 0, -6],
  "spin_rad_s": [0, 0, 0]
}
```

This is an object record inside `objects`, not a complete package. A material
record with ID `iron` must appear in that package's `materials` array.

| Field | Required / default | How to specify it |
|---|---|---|
| `id` | Required | Unique integer 1–1,000,000 within the world |
| `name` | Required | Label up to 100 characters; does not select physics |
| `material` | Required | Exact material string ID; properties, not spelling, determine response |
| `shape` | Required | `sphere`, `box`, `ellipsoid` or `wedge` |
| `representation` | Required | `rigid` for an indivisible rigid object; `network` for cells with internal deformation/damage |
| `dimensions_m` | Required | `[x,y,z]`, each 0.004–2 m. Full extents; spheres require three equal diameters, not radii |
| `position_m` | Required | Initial world position of the object COM, each component -10–10 m |
| `orientation_wxyz` | Required | Unit quaternion `[w,x,y,z]` taking object-local coordinates into world coordinates; identity `[1,0,0,0]` |
| `velocity_m_s` | Required | World linear velocity, each component -30–30 m/s |
| `spin_rad_s` | Required | World angular velocity, each component -100–100 rad/s |
| `resolution` | Required for network; forbidden for rigid | `[nx,ny,nz]`, integers 2–16, product at most 800, including unoccupied ellipsoid candidate cells |
| `pin_boundary` | Network-only optional, `false` | Pin occupied x/y perimeter cells to the world. True is a fully clamped panel, not a hinge or one fixed end |
| `grain_wxyz` | Network-only optional, identity | Rotation of the material's directional axes relative to object-local axes; each bond is transformed into this frame |

Both quaternion fields require components in [-1,1] and squared norm within
`1e-8` of one. Object orientation rotates the whole shape and material frame;
grain orientation rotates directional material properties within the shape.
The oak preset's strongest axis is local Y. Spin also contributes
`omega cross offset` to each cell's initial linear velocity.

| Shape | Available representations | Interpretation |
|---|---|---|
| `sphere` | Rigid only | Exact smooth collision sphere; density-derived solid-sphere mass/inertia; cannot fracture |
| `box` | Rigid or network | Rectangular solid or complete regular cell grid |
| `ellipsoid` | Network only | Keep cells whose centers lie inside the ellipsoid; equal extents make a sampled ball |
| `wedge` | Rigid only | Symmetric triangular prism; width X, height Y, extruded along Z; cutting tip faces local -Y |

The wedge extends from `-2*height/3` to `+height/3` along Y because its origin is
the COM, not its bounding-box midpoint. Rotate it to point toward the impact.
The +90-degree X quaternion `[0.7071067811865476,0.7071067811865476,0,0]`
turns its -Y tip toward -Z, as in the axe experiment. Sharpness is currently
specified through this geometry; there is no `cutting_power` or `sharpness`
scalar.

For a network, spacing is dimensions/resolution and each collision sphere has
radius `0.49 * min(spacing)`, which must be at least 0.001 m. Increasing
resolution can therefore violate both the body budget and collision minimum.
Thin panels have sparse spherical contacts even when the visible skin is solid.
There is no per-object custom collision mesh, explicit voxel occupancy or
sphere-cloud input in this public package yet.

Do not supply mass or inertia: they are derived. Rigid sphere mass is
`density * 4*pi*r^3/3`; a rigid box uses `density*x*y*z`; a wedge uses half the
box volume. Network mass is **occupied cell count times cell volume times
density**. Coarse ellipsoid sampling changes occupied volume, so read the
reported mass instead of assuming the analytical ellipsoid volume. Skin color
or mesh queries do not change mass, trajectories or damage.

## 5. Material criteria

Every record needs all required fields even when a rigid representation does
not exercise its internal failure law. All numeric values must be finite.
Arrays specify the three material axes, not three different materials.

| Field | Required / default | Meaning and admitted range |
|---|---|---|
| `id` | Required | Unique string, at most 80 characters |
| `density_kg_m3` | Required | 10–25,000; determines mass |
| `young_modulus_pa` | Required | Three values 100–1e12 Pa; directional axial stiffness |
| `tensile_strength_pa` | Required | Three values 1–1e10 Pa; tensile failure onset |
| `fracture_energy_j_m2` | Required | Three values 0.001–1e7 J/m²; separation-work parameter |
| `damping_ratio` | Required | 0–2; internal bond damping, not air drag or a bounce coefficient |
| `friction` | Required | 0–2; current contact adapter uses it for both static and dynamic friction |
| `fracture_enabled` | Required | Boolean; permits material-law bond failure in network objects |
| `failure_law` | Optional, `"cohesive"` | Cohesive gives progressive softening; brittle requires both tensile-strength and stored-energy thresholds |
| `yield_strength_pa` | Optional, `0` | 0–1e10 Pa; positive values enable the axial perfect-plastic demonstrator and require fracture disabled |
| `color_rgb` | Required | Integer 0–16777215 (`0xRRGGBB`); appearance only; JSON uses a decimal number |
| `provenance` | Required | Up to 500 characters describing assumptions/source/calibration limits |

Directional values are combined harmonically along each bond direction. The
engine derives stiffness `k=E*A/L`, strength force `T*A` and fracture work
`Gc*A`. A fracturing cohesive bond requires `2*Gc/T > T*L/E`; changing geometry
or material constants can invalidate this relationship and make admission fail.
The current central-force lattice is not a complete orthotropic continuum law.
Plasticity plus fracture is rejected; hardening, compression/shear failure
curves, rate dependence, flaws and layers are not accepted v2 fields.

There is no material-level restitution or rolling-resistance setting in this
schema. The current contact adapter uses the minimum directional modulus,
fixed Poisson ratio 0.25 and fixed contact-loss defaults. Its restitution field
is set to zero, but elastic contact/network response can still produce rebound;
that field is not a promise that an impact will settle without bouncing.

## 6. Existing material and item presets

These are the actual values from the latest v2 lab, intentionally preserved in
the helper catalog. Do not substitute the older scalar `MaterialCatalog.cpp`
entries: those belong to different backend paths and expose different fields.

| Material ID | Density kg/m³ | E along XYZ, GPa | Tensile XYZ, MPa | Gc XYZ, J/m² | Damping | Failure / yield |
|---|---:|---|---|---|---:|---|
| `glass` | 2500 | 70,70,70 | 45,45,45 | 8,8,8 | .025 | Brittle on; yield 0 |
| `oak` | 700 | .7,12,1 | 4,90,5 | 1500,20000,1500 | .15 | Cohesive on; yield 0 |
| `iron` | 7870 | 211,211,211 | 250,250,250 | 100000,100000,100000 | .04 | Fracture off; yield 0 |
| `soft-tissue` | 1000 | .00004,.00004,.00004 | .015,.015,.015 | 150,150,150 | .4 | Cohesive on; yield 0 |
| `ductile-demo` | 7870 | .004,.004,.004 | 3,3,3 | 10000,10000,10000 | .2 | Fracture off; yield .1 MPa |

All five use friction 0.4. RGB colors are glass `#71D8E1`, oak `#C89452`, iron
`#A7B7C6`, tissue `#E96C56` and the ductile demo `#929AD6`. File values for E and
strength are in **Pa**, not the scaled GPa/MPa units used to shorten this table.

| Object preset | Material | Shape / representation | Dimensions m | Resolution | Supports / use |
|---|---|---|---|---|---|
| `iron_ball` | Iron | Sphere / rigid | .08,.08,.08 | None | 2.10981 kg solid impactor; no internal fracture |
| `glass_panel` | Glass | Box / network | .24,.36,.04 | 6,9,2 | Fully clamped; glass failure remains unresolved |
| `wood_panel` | Oak | Box / network | .24,.36,.04 | 6,9,2 | Fully clamped; strongest grain axis Y |
| `iron_panel` | Iron | Box / network | .24,.36,.04 | 6,9,2 | Clamped nonfracturing comparison |
| `tomato_proxy` | Soft tissue | Ellipsoid / network | .18,.16,.16 | 7,6,6 | Free; 120 occupied cells, approximately 2.19429 kg |
| `knife` | Iron | Wedge / rigid | .025,.10,.14 | None | Tip toward -Y; approximately 1.37725 kg |
| `axe_head` | Iron | Wedge / rigid | .07,.14,.09 | None | Rotated tip toward -Z; approximately 3.47067 kg |
| `iron_cube` | Iron | Box / rigid | .09,.09,.09 | None | Free drop or impactor; 5.73723 kg |
| `ductile_coupon` | Ductile demo | Box / network | .24,.30,.05 | 8,10,2 | Clamped; deliberately soft plasticity demonstration |
| `glass_matter_ball` | Glass | Ellipsoid / network | .08,.08,.08 | 7,7,7 | Free sampled ball; new template, not calibrated fracture |
| `wood_matter_ball` | Oak | Ellipsoid / network | .08,.08,.08 | 7,7,7 | Same discretization for comparison |
| `iron_matter_ball` | Iron | Ellipsoid / network | .08,.08,.08 | 7,7,7 | Same discretization; fracture disabled |

The large tomato and heavy wedge tools are coarse **lab proxies**, not typical
produce or kitchen equipment. Preset creation initializes velocity/spin to zero;
the program chooses placement and launch speed. The showcase uses 2/6/12 m/s
balls, -4 m/s along Y for the knife, and -12 m/s along Z for the axe fixture.
All sphere/cell proxies and skins still need spatial and temporal qualification.

For a freely moving wooden board, copy `wood_panel` and set `pin_boundary=False`.
For an unbreakable glass prop, create a rigid sphere/box record with the glass
material. For damage-capable sampled balls, use equal-dimension network
ellipsoids. A material name alone does not switch representations or promise
shattering, slicing, heat resistance or realistic grain.

## 7. Appearance and results

`renderInstances()` exposes object, element and component IDs; current position,
orientation, velocities; primitive geometry; color; local wedge mesh and the
`deformable_cell` flag. Use `material_id` for v2 material identity; the legacy
`MaterialPreset` enum field is not the v2 material discriminator. Local rigid
mesh vertices require the instance transform.

`renderSkins()` returns material color and per-object topology revision.
Triangle positions are already in world coordinates. Each triangle records its
source cell, component and whether it belongs to a failed interface. Reuse
topology until revision changes, but update positions as matter moves. This is
a synchronous whole-object blocky skin; no input texture, UV, smooth mesh,
physical peel layer or arbitrary decorative-skin field is exposed yet.

In `reportJson().objects`, `damaged_links` includes broken links; current
softened-but-live count is `damaged_links - broken_links`. `components` and
`largest_component_cells` reveal whether anything actually separates. A failed
link is not a detached shard. Event endpoints use element IDs; do not assume
component IDs persist across a changing topology or across reloads. Network
aggregate spin may be null; use individual instance state where needed.

The top-level `damaged_links` counter has a transient failure-step inconsistency;
use per-object counts for stable client metrics. Bond rendering omits long
separated failed links, so the returned lines are not a complete event history.
Fracture events are cumulative and bounded; poll by a client cursor/index rather
than treating each report as new events. Full network events lack a causal
contact/attacker ID. `physical_response_validated` is false and
`energy_residual_j` is null; neither is a successful calibration/energy-closure
signal. Physics timings exclude rendering and package load.

## 8. Heat, stored energy, fire and ice: a separate current API

The implemented thermal contract is
[`loadWorldPackage`](../src/world/WorldPackage.hpp) plus
[`SparseThermalWorld`](../src/world/SparseThermalWorld.hpp), documented in the
[world language](world-physics-language.md). Its ABI is `banjo-thermal-world-1`.
It cannot be merged into the mechanical JSON above by adding temperature fields.

| Thermal call | Meaning |
|---|---|
| `loadWorldPackage(json)` | Build a validated thermal/phase/reaction world |
| `addMaterial(material)` / `addUniformChunk(address, material, temperature_k, liquid_fraction_at_melt)` | Define properties and uniform 16³ voxel storage |
| `activateInsulatedRegion(id, cells, fixed_step_s)` | Activate an explicit region, normally at .05 s steps |
| `addHeat(cell, requested_j, limit_j, expected_region_time_s)` | Apply capped external work at the acknowledged accepted time; stale/backlogged targets reject |
| `advance(elapsed_increment_s, budget)` | Add requested elapsed time and perform bounded work; receipt reports lag and exhausted budgets |
| `joinInsulatedRegions(first, second, expected_time_s)` | Atomic, face-adjacent, same-clock join; first ID survives |
| `activeCells()` / `reportJson()` | Temperature, liquid fraction, fuel/oxygen, accepted clocks and energy/lag metrics |

Thermal material criteria are density, `heat_capacity_j_kg_k`,
`conductivity_w_m_k`; optional finite `fuel_fraction`,
`oxygen_per_kg_solid`, reaction activation/rate/heat/oxygen requirements; or a
phase law with melting temperature, liquid heat capacity and latent heat.
Reaction plus phase change on the same material is currently rejected.

The existing [four-material phase example](../assets/world-v1/energy-phase.json)
uses 1 cm voxels, .05 s thermal steps, and an ice/water preset with density
1000 kg/m³, solid/liquid heat capacities 2100/4180 J/(kg K), melting point
273.15 K, latent heat 334000 J/kg and fixed conductivity 2.2 W/(m K).
It is an enthalpy demonstrator with fixed density/conductivity, not a flowing
water or expanding/freezing solid model. Its wood reaction also has explicit
finite fuel and oxygen. The separate runtime does not weaken moving wood with
heat, add melting to a colliding ice object, propagate smoke, or couple the
mechanical energy ledger yet.

## 9. Experimental damage integration

V2 mechanical packages and Python `make_package(..., damage_integration=...)`
now accept this optional policy. It adds the `adaptive-damage-integration`
capability; omitting the policy retains one constitutive update per step.

```json
"damage_integration": {
  "maximum_depth": 4,
  "maximum_damage_increment": 0.05,
  "maximum_plastic_strain_increment": 0.002,
  "maximum_brittle_opening_overshoot": 0.05,
  "on_limit": "reject"
}
```

Depth is an integer 0..8. Cohesive damage and brittle opening limits are
dimensionless, respectively 1e-6..1 and 1e-8..1. Plastic increment is
absolute plastic-extension change divided by original bond length, 1e-8..0.1.
Brittle overshoot is opening above the larger strength/work threshold divided
by that threshold. It uses post-plastic elastic opening. Fields default to
the values above, including strict `"reject"` when reaching a target must fault
the whole tick. `"report"` must be explicitly requested for diagnostics. Unknown fields,
invalid bounds and unknown limit policies reject at load.

The runtime tries the full step and bisects when an endpoint criterion is
exceeded. Smaller accepted steps apply changed spring state before continuing.
The maximum number of solver trials is `2^(maximum_depth+1)-1` per public tick,
up to 511. `reject` restores all motion, contact state, spring settings/removals,
history, events, work and time from the start of that tick. Earlier public
ticks remain accepted. `report` accepts at the depth limit and reports both
the number of limited steps and actual maximum accepted increments/overshoot.
Configured maxima are targets in this mode, not guaranteed achieved bounds.

The public clock is unchanged. This experimental algorithm snapshots the
whole admitted network; it is not automatic spatial refinement or a world
performance solution. Endpoint criteria miss peaks that occur and recede
inside a substep, and do not measure elastic/contact error. The full
mechanical energy residual remains unavailable. Use the
[comparative measurement script](../examples/authoring/measure_damage_integration.py)
and [checkpoint](additional-physics-checkpoint.md) before interpreting fracture
counts as material accuracy. `assets/damage-integration/` provides strict bounded studio trials alongside
the original controls. These trials stop at an unresolved limit; unrestricted
report-mode runs are generated by the measurement script for diagnosis only.

## 10. Platform operations still to add

The next shared API should support transactional live spawning/removal, forces
and impulses, assemblies and hinges, heterogeneous occupancy/layers, thermal
state attached to the same matter, state/history snapshots, and bounded
asynchronous jobs. It also needs explicit collision settings, complete reaction
and energy receipts, and stable publication/compatibility identities. These
belong to the retained [execution goals](execution-goals.md); they are not
accepted fields or callable methods in the current authoring format.

## Verification of this authoring kit

For generated-object physics checks and normal-speed native studio trials, use
the [visual/numerical validation workflow](generated-physics-validation.md).
It separates API acceptance, analytical motion, interactive performance and
the remaining material-realism gates.

The Python client passed 42 checks against the existing native CLI: all twelve
presets admitted and advanced eight steps with mass retained; the generated
three-material 12 m/s scene matched the existing fixture's discrete outcomes,
mass and velocities, with positions within 1e-12 m (one literal-versus-addition
roundoff difference was 5.55e-17 m); custom density doubled sphere mass; repeated
CLI runs restarted at initial state; skin/package overwrite and unsupported
field/law/timestep combinations rejected. These are API and smoke checks,
not additional material validation. Engine code and the 48-suite mechanical
checkpoint were unchanged by this documentation/client addition.
