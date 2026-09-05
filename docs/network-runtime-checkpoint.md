# Local material runtime v2

Experimental checkpoint, September 5, 2026. This adds the `material-network-v2`
backend alongside the retained rigid, bonded-reference and compiled-impact
backends. Its purpose is to support **local deformation, tearing and permanent
indentation**, while keeping the rest of an object physically connected. It is
not a validated tomato, wood-cutting or general game-world simulator.

The introducing commit contains this note. The exported evidence manifest
records the exact published revision. The broader project goal remains open.

## Implemented platform pieces

- `NetworkMaterial` defines SI density, directional axial stiffness/strength/
  fracture work, damping, friction, and a selected cohesive or brittle law.
  A separate perfect-plastic axial law carries permanent rest-length changes.
  Properties select behavior; changing a material ID does not change physics.
- `NetworkWorld` compiles occupied box/ellipsoid grids into physical Jolt cells
  and face/diagonal distance springs. The cells, contacts, tool and springs all
  advance every physical step. Damage and plastic histories persist between
  contacts. Failed links are removed; connected components emerge from the
  surviving graph. There is no fixed 64-step damage window in this backend.
- Tools may be rigid boxes or convex triangular-prism wedges. Wedge mass, COM
  and full inertia come from its volume and material density. Motion and recoil
  follow physical contact and gravity, with no prescribed blade trajectory,
  fragment template, breakup animation or launch kick.
- `pin_boundary` clamps the exterior x/y cell rows of a panel to the world.
  This is an explicit support condition, not a door hinge or hand-held axe.
- `PlatformWorld` retains `load`, bounded `step`, `renderInstances`,
  `renderBonds`, `reportJson` and `packageJson`, independent of inventory,
  crafting, rendering or an LLM. V2 render instances expose property-defined
  material IDs, color, element/component lineage and convex tool triangles;
  visible bond lines include damage and plastic extension.
- `banjo_network_lab` runs eight initial-state packages. Release/pause, reset,
  next/previous, quarter-speed inspection, frame stepping, structure view,
  report export and screenshot capture work through the same API as headless
  clients. Green links are intact, amber softened and red broken.

## Constitutive and numerical scope

An occupied grid cell has mass `density * dx * dy * dz` and box-cell inertia.
The sphere collision proxy has radius `0.49 * min(dx,dy,dz)`. Ellipsoid volume
is the occupied-voxel sum, not the analytical ellipsoid volume. Every cell
remains physical after damage. Rigid component re-coarsening is not implemented.

For a link, `k = E_direction * area / length`, `strength = sigma_direction *
area`, and `fracture_work = Gc_direction * area`. The current area is
`cell_volume^(2/3)/6`; directional values use harmonic squared-direction
weights in the material reference frame. This is a declared axial lattice,
not a calibrated orthotropic continuum with independent shear/Poisson response.

The cohesive law has elastic opening `d0 = strength/k` and final opening
`df = 2*fracture_work/strength`; incompatible `df <= d0` packages reject. Its
secant stiffness follows linear softening. Maximum opening and dissipated work
are irreversible. Closing a partly damaged bond uses compression stiffness;
fully failed links stay removed and cell contact handles subsequent closure.
The force-opening integral equals the declared separation work in coupon tests.

The brittle law requires both tensile strength and available elastic energy.
Excess elastic energy removed at brittle failure is explicitly reported as
`unreleased_fracture_energy_j`; it is not injected as a velocity kick or
silently called heat. Perfect plasticity changes rest length and records
yield-force times plastic extension. Combined plasticity/fracture and hardening
are rejected until their coupled work law is implemented.

After each Jolt step the material update reconstructs an averaged elastic
opening from the actual spring impulse, with the axial damping term separated.
This avoids interpreting a stiff solver's positional residual as enormous
elastic strain. A two-mass spring test checks the signed impulse, damping
separation and backward-Euler response; refinement from 1/240 to 1/960 s reduces
its maximum scaled position/velocity error from 0.0006712 to 0.0001717 m.
This isolated coupon does not certify a multi-contact cutting trajectory.

**Stiff-wave response is unresolved.** Glass/iron cell frequencies are far above
what the demo timestep resolves. Implicit integration keeps motion bounded but
attenuates the short stress peaks needed for reliable brittle fracture. The
cube diagnostic can break oak while leaving glass intact. That is a model
failure boundary, not a claim about real material ordering. Reports expose
`step_times_pair_frequency`, reaction/geometric opening discrepancy, and
`physical_response_validated: false`. The frequency number is an isolated-pair
indicator, not a complete network eigenfrequency or universal error bound.

`energy_residual_j` remains **null**. Reports separate stored spring energy,
constitutive fracture work, plastic work and unresolved brittle release, but
contact/damping loss, support work and integration error are not yet closed.
`unseparated_energy_change_j` is their remaining combined change, not heat and
not proof of conservation. World-level work accuracy needs further validation.

## Examples and measured boundaries

All fixtures use a 1/480 s step and 24 velocity iterations. Names such as oak,
iron and soft tissue identify experimental parameter sets. The soft material
has no skin, pulp pressure, fluid transport or biological validation. Oak's
coarse cohesive parameters are not calibrated cutting data. `ductile-demo`
uses a deliberately compliant test modulus; it is distinct from physical iron.

| Package | What it demonstrates | Boundary |
|---|---|---|
| 01 sharp, four materials | Same iron wedge strikes glass/oak/iron/soft tissue; local tissue damage retains a connected core | Not a realistic ranking of all four materials |
| 02 blunt, four materials | Equal-mass/equal-volume iron blocks, same initial COM and velocity, provide a no-tear tissue control | Wedge/block inertia and lowest contact height differ; contact histories are not identical |
| 03 axe/panel | Freely moving 12 m/s iron wedge causes localized link damage in a clamped oak panel | No detached carved chip or door-hinge response established |
| 04 offset soft cut | A 4 m/s downward blade tears some links; gravity/contact continue moving the blade and retained tissue | No complete slice or fine cut surface established |
| 05 three cube drops | Continuous coupled drop diagnostic, retaining glass/oak/iron | Glass failure prediction is under-resolved and unvalidated |
| 06 supported rest | All four materials settle without material damage | Contact gaps/settling are discretization effects |
| 07 ductile indentation | A punch produces positive plastic work and permanent axial extension without fracture | Uncalibrated perfect-plastic test material; no hardening |
| 08 free flight | Four materials translate without damage or spurious internal work | No forces or contact; necessary control, not a full conservation proof |

At **one simulated second**, the sharp comparison produces 36 broken tissue
links and 44 total damaged links with all 81 cells still connected; the blunt
control produces zero. The standalone soft cut has 14 broken links, 35 total
damaged links and all 120 cells in its core. The panel has one broken/eight
damaged links and retains its 216-cell core. The ductile coupon records about
0.6082 J of plastic work and zero broken links. The cube diagnostic has zero
glass failures, 75 oak failures with a 26-cell largest core, and zero iron
failures. Supported-rest and free-flight controls have zero damage in all four
materials. These are numerical observations, not material validation.

Initial one-second physics measurements on Windows/MSVC Release, Jolt double
positions/float velocities, Intel Core Ultra 9 285K: about 0.53 s CPU for the
121-body standalone soft case and 1.18 s CPU for the 328-body four-material
comparison. Physics times exclude rendering, loading and JSON reports. Thus
the four-material comparison already exceeds real-time CPU budget. The lab
offers explicit inspection speed and pauses if live backlog exceeds 0.25 s;
it does not disguise prerecorded motion as a faster live solver.

The evidence export contains repeated three-second trials and timestep/grid
sweeps. Different resolutions change occupied volume and the contact proxy,
so those sweeps are diagnostics, not fixed-mass continuum convergence tests.
Do not treat matching regression counts as proof of convergence. Thousands
of simultaneous interactions and a whole-world frame budget remain open.

## API admission and running

The existing backend capability lists remain queryable. `backend_packages`
advertises v2's separate `package_version: 2`, `physics_abi: banjo-network-2`.
The package must specify `backend: material-network-v2`, `units: SI`, materials,
objects, gravity, ground (or null), fixed timestep and call budget. Required
capabilities are a caller's negotiated subset, not an inferred full manifest.
Unknown fields/laws/capabilities and incompatible geometry reject.

Admission limits: 4 MiB JSON, 16 materials, 32 objects, 1024 total physical
bodies, at most 800 candidate cells per object, 20,000 links, 240 steps per
call, and timestep 1/4800 through 1/240 s. These are resource bounds, not
wall-clock guarantees. `packageJson()` exports **initial authoring state**,
not a live-state save; no state migration is implied. Direct `NetworkWorld`
stepping must use the admitted timestep. See the eight JSON files for all
shape/material/property field names and explicit provenance.

```cpp
auto world = banjo::PlatformWorld::load(package_text);
auto step = world->step();
if (!step.error.empty()) { /* stop and surface the fault */ }
auto instances = world->renderInstances();
auto visible_links = world->renderBonds();
auto report = world->reportJson();
```

```powershell
cmake --build build/win-joint-double --config Release --target banjo_network_lab banjo_platform_cli
build/win-joint-double/Release/banjo_network_lab.exe assets/runtime-v2 04-soft-tissue-offset-cut.json
build/win-joint-double/Release/banjo_platform_cli.exe --run assets/runtime-v2/01-sharp-four-materials.json 480
python scripts/benchmark_network_v2.py --exe build/win-joint-double/Release/banjo_platform_cli.exe --out build/network-v2-evidence --seconds 3 --repeat 3 --sweep
```

All **39 CTest suites passed** in 79.12 s after rebuilding the test targets,
including the earlier bowl, crafting, assistant, creator and platform suites.
Three new suites cover the directional/cohesive/plastic laws, physical spring
oracle/convergence/lifetime, and live comparative controls, local damage,
material-ID invariance and invalid packages. Native inspection covers release,
continued gravity motion, reset, structure, speed and stepping. Full-suite and
repeated-run records accompany the published evidence.

## Next gates

1. **Resolved local surfaces and work.** Add contact-aware surface refinement,
   richer shear/bending connectors and a complete force/work ledger. Validate
   partial notches, detached chips and loaded/unloaded permanent indentation
   with orientation, mesh and timestep sweeps. Keep the failing glass diagnostic.
2. **Local simulation within a rigid world.** Activate only a bounded affected
   region, account for reactions into the surviving object, and transfer damage,
   momentum and energy when refining/re-coarsening. Establish measured budgets
   before claiming real-time whole-world execution.
3. **Additional physical laws.** Validate wood grain/mixed-mode cutting, layered
   skin/soft contents, hinges/fasteners, pressure and rate response using distinct
   material contracts. Preserve glass/oak/iron controls with every addition.
4. **Learn from the validated solver.** Build supervised local-response data with
   geometry, material, contact, support and persistent-state inputs. Add confidence
   checks and physical fallback before reuse. No exhaustive combination catalog,
   reinforcement-learning training or neural runtime was introduced here.
