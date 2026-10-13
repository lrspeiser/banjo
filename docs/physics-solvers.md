# Specialist solvers and device fidelity

October 13, 2026. Implementation audit: a physical equation can be real while
its material model, boundary conditions or geometry remain simplified. This
checkpoint does not make every device interior accurate.

## Delivered electrical backend

Jolt solves rigid bodies/contact, never Banjo's circuits, water, heat or optics.
Those have separate native modules coupled through LiveWorld. New default
builds use **ngspice** for every circuit operating-point trial. Circuit translates
resistances, switch state, motor back EMF and capacitor backward-Euler companions
into a generated SPICE network. Returned voltages and Ohm's law determine
current; the engine accounts for finite source energy, heat, shaft work, light,
capacitor storage and numerical loss. No level name, piece name or success flag
enters that network. Missing dependencies fail configuration, and failed solves
report errors rather than fabricated readings or a runtime fallback.

This replaces the numerical solver within the existing **bounded DC/RC domain**.
It does not add AC, inductors, diodes, transistors, switching converters,
electromagnetic fields or resolved device interiors. The expected answers for
the existing linear components are the same as before; linking a specialist
does not improve a component's constitutive law automatically. ngspice provides
the foundation for future nonlinear models, subject to energy/coupling tests.
Its [shared-library API](https://ngspice.sourceforge.io/shared.html) supports
embedded analysis; the [manual](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf)
describes many capabilities Banjo does not yet expose.

The engine owns accepted capacitor charge, temperature and fuse state. Each
ngspice call is a fresh operating point, with no mutable transient history;
rejected mechanical trials cannot consume energy. One zero reference per
conducting island is a gauge choice, not leakage across an open wire. Calls
are synchronous and serialized inside a process; players already use separate
engine processes. Callbacks stay off protocol stdout and old plots are destroyed.
Circuit receipts identify backend, package-header version and numerical method.
A restored receipt describes provenance; it cannot choose or load a backend.

Long-run follow-up: generated circuits are explicitly removed with `remcirc`,
and the shared API's command control structures are cleared between trials.
Destroying result plots alone does not release those allocations. One active
definition can remain until the next solve; definitions/history do not accumulate.

## Other domains reviewed

These choices combine source inspection with primary project documentation.
**Candidate** means researched, not integrated or benchmarked against Banjo.

| Domain | Current model | Decision and qualification needed |
|---|---|---|
| Rigid mechanics/contact | Jolt plus Banjo material/contact lanes | Keep Jolt. No measured comparison here proves another rigid solver better. Any replacement needs reactions, friction/rolling slip, momentum and full energy comparisons. [Jolt](https://github.com/jrouwe/JoltPhysics) is a rigid-body/collision library. |
| Electricity | Lumped DC/RC, finite regulated source, motor back EMF, switches | **ngspice integrated by default**. Keep explicit charge/thermal/numerical/shaft accounting. Nonlinear device interiors still require models and calibration. |
| Rivers | Depth-averaged Saint-Venant finite-volume grid | Retain this appropriate shallow-flow model. It cannot represent overhead flow, overturning waves or sloshing vessels; 3D SPH is not necessarily better for every river cell. |
| Pouring/buckets/3D liquid | Weakly compressible SPH parcels with surface contact | **SPlisHSPlasH candidate**: incompressible pressure solvers, viscosity, surface tension and fluid-solid coupling. Benchmark containment, hydrostatics, pressure/flow, wheel torque, two-way reactions and cost. Its own rigid/PBD coupling cannot duplicate Jolt contact. [Methods and library](https://github.com/InteractiveComputerGraphics/SPlisHSPlasH). |
| Steam/property laws | Constant-property thermochemical parcels and pressure coupling | **CoolProp candidate** for water/steam equations of state and transport. Match reference energies, phase equilibrium, inlet/outlet enthalpy and moving-volume work first. A property library does not solve a boiler or piston. [CoolProp](https://coolprop.org/). |
| Fire/reacting gases | Declared oxygen-limited reactions and heat/matter accounting | **Cantera candidate** for chemistry/transport and reacting systems. Oak moisture, pyrolysis, char and flame transport still need defensible mechanisms and calibration. A library is not experimental validation. [Cantera](https://cantera.org/). |
| Flexible cables/bending/mounts | Ideal connectors and bounded lattice/cohesive models; electrical cables have no flexible mechanical body | **Chrono FEA candidate**, with SOFA another deformable option. Compare stiffness, buckling, bending/torsion, contact, retention and work/reaction transfers. One authoritative contact owner is required. [Chrono](https://projectchrono.org/), [SOFA](https://www.sofa-framework.org/). |
| Fracture/plasticity | Banjo material/lattice/cohesive lanes | Retain until replacements pass material-comparative fracture/contact/conservation tests. Generic engines do not supply calibrated oak grain, ductile copper or glass failure automatically. |
| Light/solar | Geometrical rays, declared optical properties and local heat; center-sampled solar shade | Retain macroscopic ray optics. Partial-area irradiance and photovoltaic conversion/device laws need implementation. Diffraction, interference and polarization are unsupported. |

## Required device interiors: not yet implemented

Internal behavior must come from connected physical components and declared
laws, with justified parameters and geometry. These are qualification targets,
not features enabled by this checkpoint:

* **Wire:** conductive core/insulation, material/length/area/temperature resistance,
  mass, bending/tension/contact and terminal retention. Electrical topology
  changes only through actual connections or physical failure. Melting,
  shorting and dielectric breakdown need validated laws; a drawing route is
  not a mechanical cable.
* **Switch:** conducting contacts and insulating housing, with geometry/pressure
  determining continuity/resistance. Current paddles use body contact plus fixed
  resistance; manual rockers still use measured hinge thresholds. Oxidation,
  arcing and calibrated contact bounce are missing.
* **Bulb:** a filament with material resistance versus temperature, heat capacity,
  conduction, radiation/spectrum and physical failure. Present bulbs remain
  rated resistors with fixed emitted-light fractions; envelope size does not
  derive filament demand. No scripted explosion should replace failure physics.
* **Motor/generator:** windings, rotor/stator, terminals, magnetic flux,
  inductance, commutation, losses and housing reaction. Current motors use a
  declared torque-speed line and lumped back EMF; magnetic interiors are unresolved.
* **Battery/solar cell:** calibrated voltage/current/state/temperature equivalent
  models with conserved energy. Current batteries are finite ideal stores and
  regulators; solar uses a fixed conversion fraction and ideal charging lead.
  Chemistry, photovoltaic I-V curves, partial shade, bypass diodes and converter
  losses remain absent.
* **Capacitor/inductor/semiconductor:** calibrated dielectric/ESR/leakage/breakdown,
  magnetic storage/saturation and junction/thermal models. Present capacitors
  use rated C/ESR/leakage; inductors and semiconductors are unimplemented.
  Housing dimensions are not dielectric or magnetic microphysics.
* **Reservoir/pipe/pump/valve:** wet geometry, volume, pressure, head, viscous flow,
  work and reactions. Handles and impellers must mechanically control openings
  and flow. Current fixed tank taps declare opening; hollow pipes are gravity
  routes, not sealed plumbing.
* **Heater/kettle/piston:** validated thermal connections, shared water/steam state,
  pressure-dependent phases, leakage/valves, volume work and reactions. Current
  heater clips have ideal fixed mounts and lumped thermal coupling, not resolved
  windings or pressure-dependent heat transfer.

Accuracy means a justified model over a declared range, timestep/resolution
convergence and comparison to measurements. Rendered electrons or atom-by-atom
matter are not a prerequisite or proof of accurate engineering simulation.

## Reproducible build

Linux/Render installs `libngspice0-dev` at build time and `libngspice0` at runtime.
Ubuntu 24.04 uses **42+ds-3build1**, tested locally in WSL. Windows uses official
**ngspice 47** DLL/header/import-library archives, with published SHA-256 values
pinned in `scripts/setup-ngspice-windows.py`. The companion executable archive
supplies two audio DLLs omitted from the shared-library archive.

```powershell
python -m venv build/ngspice-setup
build/ngspice-setup/Scripts/python.exe -m pip install py7zr==1.0.0
build/ngspice-setup/Scripts/python.exe scripts/setup-ngspice-windows.py
# Pass the printed NGSPICE paths to cmake -S . -B build/your-test-build.
```

CMake stages required DLLs beside native executables. No downloaded binaries,
archives or credentials are committed. `BANJO_USE_NGSPICE=OFF` is an explicit
legacy linear comparison build, never a runtime fallback/default deployment.

## Measurements

* Independent electrical oracles cover parallel/current-limited loads, a balanced
  Wheatstone bridge, winding back EMF/polarity, isolated capacitor discharge
  with storage/heat/numerical balance, empty/open nodes, invalid inputs and four
  concurrent callers (400 repeated solves). Windows 47: **0.0410 s**; Linux 42:
  **0.0425 s**. These are solver tests, not full game-frame benchmarks.
* Existing native circuit/coupling suite passes on Windows in **2.565 s**.
  RC voltage errors at 0.01/0.005/0.0025 s decrease to
  0.0217629/0.010904/0.00545763 V; numerical losses decrease to
  0.030524/0.0153117/0.00766831 J. Electrical residuals are
  4.23e-14/8.64e-14/2.71e-14 J. Numerical loss never warms a body.
* Existing motor tests at 120/240/480 Hz retain whole-system residuals
  **-0.119786/-0.0598687/-0.0299583 J**, with coupling residuals
  **0.239571/0.119706/0.0598431 J**. These converge but are not zero.
  The solver replacement is not complete mechanical energy closure.
* All **61 game checks** and **39 electrical checks** pass with ngspice,
  preserving authored/nudged wins and physical wrong/open controls. The legacy
  engine passes the 61 game checks too. Runs overlapped other validation:
  ngspice game 123.543 s, legacy game 99.977 s, electrics 99.387 s. These are
  **not** isolated comparative performance benchmarks.
* Equal electrical ratings in glass/oak/iron capacitor housings yield the same
  0.09719398 J remaining after 7.95 s, 8 J source draw, electrical residual
  -4.19e-12 J and thermal residual 6.63e-8 J. Housing material is not a
  dielectric-material comparison. The heater-target glass/oak/iron cases at
  1/240 and 1/480 s retain material-dependent temperatures with the same supplied
  heat. Existing detailed [electrical measurements](sandbox-electrics-measured.md)
  state the model limits; current receipts are under ignored
  `build/physics-solvers/electrics-spice.log`.

Initial Windows DLL loading failed because `sndfile.dll`/`samplerate.dll` were
missing from the official shared archive. These are now required/staged.
Windows tar also reported unreadable names in the companion archive; the
corrected setup uses py7zr and extracts only named ABI/runtime files. Corrected
setup and electrical checks pass. Initial failed runs are not counted as passes.

No material property, mechanical step, goal, deadline, solution, conservation
tolerance, water law or optical law changed.

Final qualification: Linux builds the engine and both C++ test targets through
CMake. Its four registered circuit/oracle/game/electrics targets pass in
328.27 s (game 184.55 s, electrics 138.84 s). Windows additionally passes 32
LiveWorld checks in 22.184 s and four ordinary-control Chrome checks: capacitor
charge/reset, battery voltage and wire thickness, physical firing contacts,
and Recent Changes. The electrical browser group passes in 47.978 s; the
four-size updates dialog check passes in 8.035 s. Desktop 1280x860, portrait
390x844 and landscape 844x390 preserve visible Run/Reset and measured readings.
Manual local play completes Finish the loop with three stars, 0.250 A and
2.99 W lamp power. Screenshots are in ignored `build/physics-solvers/`.

Verified Windows engine SHA-256:
`906ca958c0a9c0e15da13a003ef9ca92ac754c9563458545c0cb58e96752d49c`.
Verified Linux engine SHA-256:
`3d8cf9eb16185b8cd28fc847cc51fced49b5a9b4c64c029da658ac8e85b61da1`.
The local 18893 server uses that Windows executable, with matching checkpoint
hash and no restart pending. Both new C++ files are registered and compiled;
the source-registration guard covers 271/271. Local documentation links,
Python syntax and changed-file whitespace checks pass. Broader GitHub CI and
Render's separately compiled production executable are separate verification.

## Long-run retention regression

After publishing the first solver checkpoint, a lifecycle review of the
ngspice manual identified retained circuit/command lists. A new regression
warms 1,000 trials, then measures 6,000 additional three-node trials. It
failed against the first integration: Windows private-memory growth was
**145,940,480 bytes**. The explicit circuit/history cleanup above fixes that
retention. The same test now measures **479,232 bytes** on Windows (private
memory) and **0 bytes** on Linux (resident memory). A fixed 8 MiB allowance
after warmup permits bounded allocator/cache growth; electrical voltage,
KCL and energy tolerances are unchanged. This measures solver retention, not
all world geometry/fluid memory. The test also initially hit Windows' obsolete
`near` macro; its compile error was fixed before recording the failing baseline.

Final cleanup engine hashes supersede the first checkpoint identities above:
Windows `997b02d2b9f4594dbb575eeca38c17777a7ce6ec74e8832f97d265f8974464a9`;
Linux `d74c67470be8bc7464e306ca0f216e8b088f1d60c313d7cc0a1e09880d9f7095`.
The Windows C++ oracle/circuit targets pass in 2.45 s, including the longer
memory run. Its full game and electrical suites pass again: 61 checks in
129.043 s and 39 in 102.336 s. The four browser checks pass together in
54.639 s on desktop and both phone orientations. Linux's complete four-target
circuit/oracle/game/electrics rerun passes in 321.60 s. No physics or UI wait
tolerance changed for the cleanup. The 18893 server is switched to the final
Windows executable, and its checkpoint hash/restart state are checked.
