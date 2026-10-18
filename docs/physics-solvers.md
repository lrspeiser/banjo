# Specialist solvers and device fidelity

## October 18: electronics and fluid library evaluation

**Recommendation:** extend the existing ngspice integration for electronics;
prototype **SPlisHSPlasH/DFSPH** for contained/poured water and
**OWA-EPANET** for filled pipe networks. Keep the shallow-water river solver.
Use Xyce and OpenFOAM as independent reference tools before considering them
as runtime backends. These rankings are engineering judgments from Banjo's
source and the primary sources linked below, not measured speed/accuracy wins.
No new dependency or physical capability is delivered by this evaluation.

Source baseline: Banjo `18705bdc6dfaae0538df46cbe8ba99e7c622373f`.
Library documentation/source reviewed October 18, 2026. Existing measurements
later in this document retain their original dates and build identities.

### What Banjo actually runs

* `BANJO_USE_NGSPICE` defaults on in [CMake](../CMakeLists.txt).
  [SpiceNetwork](../src/machines/SpiceNetwork.cpp) generates resistors/series
  voltage sources and requests fresh operating points. It does **not** run
  ngspice's transient integrator. [Circuit](../src/machines/Circuit.cpp) owns
  backward-Euler capacitor state, electrical/thermal ledgers and accepted
  motor work. The adapter currently limits networks to 128 nodes, serializes
  calls and sets ngspice to one thread. New semiconductors/inductors need new
  branch laws, state and energy accounting, not another link flag.
* [FallingWater](../src/water/FallingWater.hpp) uses weakly compressible SPH
  parcels: 40 mm spacing, 64 g per parcel, reduced 20 m/s sound speed and a
  2,000 parcel bound. It lacks boundary density correction and surface tension;
  stored water does not have a resolved sloshing reservoir. Existing pipes are
  collision geometry/gravity routes, not a sealed pressure network.
* [ShallowWater](../src/water/ShallowWater.hpp) solves depth-averaged
  Saint-Venant mass/momentum equations with wet/dry boundaries and substeps.
  That remains appropriate for shallow rivers; it cannot resolve an overturned
  bucket or vertical pipe flow.
* Jolt owns solid contact/joints. It supplies neither circuit equations nor
  fluid pressure. Its mechanical wire bodies and terminal retention remain
  separate from the electrical network.

### Electronics shortlist

| Library/tool | Capability and licence | Fit for Banjo / decision |
|---|---|---|
| **ngspice — first choice, already integrated** | Embedded C shared API, transient/AC analysis and nonlinear SPICE device models. Predominantly modified BSD, with component exceptions and separately licensed runtime dependencies. [API](https://ngspice.sourceforge.io/shared.html), [manual](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf), [licensing](https://ngspice.sourceforge.io/faq.html). | Lowest integration cost. Extend the adapter for inductors, diodes/LEDs, transistor switching and calibrated solar/battery/bulb models. First prove transient synchronization and reversible state. A DC solve alone cannot produce inductive kickback or transistor switching dynamics. |
| **Xyce — independent reference / reserve backend** | Sandia C++ SPICE-compatible solver; DC, transient, AC and large parallel networks. GPL-3.0; Trilinos and other dependencies add build work. [Project/source](https://github.com/Xyce/Xyce), [build guide](https://xyce.sandia.gov/documentation-tutorials/building-guide/). | Useful independent implementation for checking selected netlists. Banjo's small circuits do not establish a benefit from MPI or million-device capacity. Higher integration cost than using the backend already present. Check model compatibility instead of assuming identical SPICE syntax/results. |
| **CircuitJS — teaching reference** | Interactive browser circuit simulator, Java/GWT, GPL-2.0-or-later. [Source/licence](https://github.com/sharpie7/circuitjs1). | Useful examples of readable current/voltage feedback. Replacing the native coupled solver with it would create another state owner and require a major port/bridge. Do not copy a visualization and treat it as electrical validation. |
| **Qucs-S — authoring/debugging tool** | Qt schematic interface to ngspice, Xyce and other backends; GPL-2.0 repository. [Supported kernels](https://github.com/ra3xdh/qucs_s). | Helpful for engineers preparing reference circuits. It is an interface to solvers, not a new physical model to embed in the game. |
| **Elmer FEM — later device calibration** | Meshed electromagnetics, heat and other PDE models; GPL-2.0-or-later with module/dependency terms. [Capabilities](https://github.com/ElmerCSC/elmerfem), [licence](https://github.com/ElmerCSC/elmerfem/blob/devel/LICENSE.md). | Candidate for offline motor/coil field and thermal studies. SPICE does not derive winding geometry, magnetic saturation or commutation from a rendered motor. First qualify a field model; any reduced runtime model needs a declared geometry/material range. No per-frame FEM integration is proposed. |

For ordinary low-frequency learning circuits, lumped network physics is the
right initial abstraction. Geometry supplies wire length/area/material and
actual contact topology; the solver supplies voltages/currents. Realistic
device interiors still require physical parameters, calibrated component laws
and mechanical/thermal coupling. Adding ngspice's larger model library does
not automatically supply those interiors.

### Fluids shortlist

| Library | Capability / hardware / licence | Fit for Banjo / decision |
|---|---|---|
| **SPlisHSPlasH — first 3D liquid prototype** | C++ SPH library with DFSPH/IISPH and other pressure methods, viscosity, surface tension and rigid-fluid coupling. CPU/OpenMP; optional GPU neighbour search is not a wholly GPU fluid solver. Core MIT, dependencies have separate terms. [Project](https://github.com/InteractiveComputerGraphics/SPlisHSPlasH), [licence](https://github.com/InteractiveComputerGraphics/SPlisHSPlasH/blob/master/LICENSE). | Best initial fit for buckets, pouring, sloshing, receivers and water wheels on the current CPU service. Its [rigid body interface](https://github.com/InteractiveComputerGraphics/SPlisHSPlasH/blob/master/SPlisHSPlasH/RigidBodyObject.h) exposes state, forces and torques, making a Jolt adapter plausible, not already available. Custom boundary/coupling and rollback work are substantial. Benchmark before choosing DFSPH over the current solver. |
| **SPHinXsys — strongest broader multiphysics alternative** | C++ particle/mesh framework for fluid, elastic solids, heat and multibody coupling. CPU dependencies include TBB; core Apache-2.0. [Source/licence](https://github.com/Xiangyu-Hu/SPHinXsys), [fluid/solid coupling](https://www.sphinxsys.org/html/theory.html), [installation](https://www.sphinxsys.org/html/installation.html). | Worth a second CPU prototype if solid-fluid/thermal coupling is the priority. Its documented rigid integration uses Simbody, not Jolt; a Banjo adapter still needs qualification. The installation guide warns about Simbody/VS2022 compatibility, so verify a pinned revision with our compiler. Prefer the smaller contained-water experiment first; there is no measured speed or accuracy ranking between these libraries here. |
| **OWA-EPANET — first plumbing prototype** | C toolkit for hydraulic pipe networks: tanks, reservoirs, pumps, valves, diameters and losses. MIT community implementation. [Toolkit](https://github.com/OpenWaterAnalytics/EPANET), [licence](https://github.com/OpenWaterAnalytics/EPANET/blob/dev/LICENSE), [EPA scope/manuals](https://www.epa.gov/water-research/epanet). | Good candidate for filled, quasi-steady pressure networks. EPANET assumes full pipes; it does not resolve a moving liquid front, water hammer, air locks, splashes, steam or a marble inside a pipe. Use Darcy-Weisbach for initial comparisons. Partially filled pipes stay in a free-surface domain; do not silently label them pressurized. |
| **DualSPHysics — engineering SPH reference** | C++ SPH for free-surface engineering flows; CPU/OpenMP or CUDA GPU. LGPL-2.1 core. [Source/build](https://github.com/DualSPHysics/DualSPHysics), [hardware/licence FAQ](https://dual.sphysics.org/faq/). | Strong comparison candidate for dam-break loads, moving boundaries and wheel forces. Its case/preprocessing workflow needs more adaptation to interactive edits than the first-choice library. Check terms for every packaged preprocessing/postprocessing tool separately. CPU execution is supported; performance on our server is unmeasured. |
| **Chrono::FSI SPH — GPU research lane** | SPH and solid coupling within Chrono; BSD-3-Clause core. The FSI SPH module requires CUDA/NVIDIA hardware. [Requirements](https://api.projectchrono.org/10.0.0/module_fsi_installation.html), [licence](https://github.com/projectchrono/chrono/blob/main/LICENSE). | Attractive if later evaluating Chrono solids/FEA with fluids. Not the first runtime choice for the existing CPU-only service. Connecting it to Jolt needs explicit force/state coupling and must not give both engines ownership of the same rigid dynamics. |
| **OpenFOAM Foundation — offline reference** | Finite-volume CFD, free surfaces, heat and thermodynamics; CPU/parallel; GPLv3. [Project](https://openfoam.org/), [licence](https://openfoam.org/licence/enforcing-gpl/). | Best initial independent grid-based reference for a few carefully meshed pipe/jet/wheel cases. Setup, remeshing and interactive coupling make it a high-cost gameplay backend. Neither its name nor higher resolution guarantees accuracy without convergence and boundary-condition checks. |
| **Basilisk — adaptive reference / river research** | Adaptive Cartesian finite-volume framework with Navier-Stokes, two-phase interfaces and shallow-water solvers; GPLv3. [Solvers](https://basilisk.fr/src/README), [licence](https://basilisk.fr/src/COPYING). | Useful for dam-break, wet/dry and free-surface reference cases. Its Basilisk-C toolchain and external moving-solid integration make it a larger embedding task. No reason yet to replace Banjo's functioning river solver wholesale. |

The SPlisHSPlasH [changelog](https://github.com/InteractiveComputerGraphics/SPlisHSPlasH/blob/master/Changelog.txt)
and build sources show maintained methods and portability work, but old wheel
support advertised in a README is not proof of a current Python/ARM build.
Use a pinned C++ source revision for experiments. Xyce, DualSPHysics, Chrono
and EPANET also have public source/build documentation; project size or
reported solver speed is not a Banjo benchmark.

FluidX3D was also screened. Its current
[licence](https://github.com/ProjectPhysX/FluidX3D/blob/master/LICENSE.md)
restricts commercial use, so it is excluded from the proposed unrestricted
open-source dependency set. Publicly readable source alone is insufficient.

Steam remains a separate thermodynamic problem. [CoolProp](https://coolprop.org/)
is a property-law candidate for water/steam state and transport; it does not
solve a kettle, valve or pressure-driven piston. Neither the proposed EPANET
lane nor an incompressible SPH test should claim boiling or combustion.

### Integration boundaries and hosting constraints

The documented Render service has one CPU and 2 GB; `/test` shares that host
and has tighter process/memory limits ([deployment](deploy.md)). A GPU-only
solver is not deployable there. Extra OpenMP threads cannot create extra CPU
capacity. First benchmark at one thread with no GUI, render/export tools or
per-step file output; measure cold start, peak RSS and p50/p95/p99 step time.
Then measure two competing sessions and production/test contention on an
equivalent isolated environment before a small hosted smoke test. Do not run
a heavy benchmark against live players.

SPlisHSPlasH's [top-level build](https://github.com/InteractiveComputerGraphics/SPlisHSPlasH/blob/master/CMakeLists.txt)
and [CMake options](https://github.com/InteractiveComputerGraphics/SPlisHSPlasH/blob/master/CMake/Common.cmake)
support library-only builds, OpenMP and precision choices. Its build also
sets global paths/flags, including `/fp:fast` on MSVC; use an isolated external
build and audit the generated compile commands. Do not inherit fast-math or
host-specific AVX assumptions into Banjo. Compare double precision for
qualification with any proposed faster build, retaining measured errors.
Audit the selected transitive libraries and preserve required notices; a
permissive top-level licence is not a licence inventory for the binaries.
GPL/LGPL redistribution considerations also matter for future native apps.

One clock and one authoritative accepted state are required:

1. Mechanical state supplies wet geometry/velocities and electrical contacts.
   A fluid adapter returns force **and torque**; Jolt applies solid motion and
   contact. Do not additionally integrate the same solid with the library's
   PBD/Chrono world. Do not also apply the old water force for that domain.
2. Prototype `trial(dt, boundary_state)` / `accept()` / `discard()` semantics.
   Fluid pressure warmstarts, particle/emitter history and SPICE transient
   history must roll back with rejected steps; copying positions alone is
   insufficient. Current stateless ngspice trials deliberately avoid this issue.
3. First compare native ngspice transient results in a standalone circuit
   process. Only then choose reversible companion models versus a persistent,
   synchronized transient session. Preserve charge/flux across contact changes;
   never restart a capacitor at zero after editing a wire. Keep models/netlists
   server-generated and bounded.
4. Exchange liquid across pipe/SPH/river boundaries transactionally: debit and
   credit mass, momentum and energy exactly once, including pressure/shaft
   work and support reactions. Initial tests keep domains separate. A pressure
   network's flow rate cannot be imposed on SPH without debiting source head
   and accounting for outlet momentum/work.
5. Keep the existing backend selectable in experiment builds. Solver failures
   are visible errors, not an unnoticed runtime switch. Cache results only
   against all geometry, parameters, state, solver revision and numerical settings.

### First experiments and acceptance evidence

The following are **proposed new experiments**, not tests already added or
passing. Use separate CMake-registered opt-in targets/builds, pinned source
and dependency hashes, and machine-readable receipts. No baseline goal or
existing tolerance changes are part of this proposal.

| Order | Experiment | Independent check / recorded evidence |
|---|---|---|
| E1 | ngspice transient RC and series/parallel networks, then RL and RLC | Exact exponential response and damped oscillator frequency/decay; half timesteps at 1/240, 1/480, 1/960 s, with finer electrical substeps as the shortest time constant requires. Record KCL, voltage error, charge/flux continuity, source work, storage, Joule heat and numerical loss. A fixed mechanical step is not an adequate electrical step for every component. |
| E2 | Diode + resistor, LED, transistor switching, inductor flyback | Check the declared device equations/parameters first, then selected equivalent Xyce netlists. Agreement between simulators is a cross-check, not an experiment validating the physical component. Include open/reversed leads, short/current limit, switch timing, rollback and save/reload. |
| E3 | Motor electrical/shaft/thermal coupling and solar I-V | Independent motor equations with winding resistance/inductance and back EMF; electrical input equals storage + heat + actual mechanical work within a declared convergent residual. Measured device curves are needed before material/device-fidelity claims. Re-run Turn the axle, Give it power and existing RC/electrical regressions. |
| F1 | SPlisHSPlasH sealed still tank, draining tank and tilted bucket | Hydrostatic pressure and no unaccounted leakage; analytic discharge only for its applicable nozzle regime/coefficient; receiving mass and COM motion. Compare 40/20/10 mm spacing and successive timestep/CFL refinements on the same physical geometry. Cost rises roughly eightfold in particle count when 3D spacing halves, before extra solver work. |
| F2 | Paddle/water wheel and free floating body coupled to Jolt | Account for inlet/outlet momentum, torque, gravity, support impulse, head work, body energy and dissipation. Run matched geometry with glass, oak and iron using declared densities, inertia and wet boundary laws. Compare material-dependent motion, not just housing names. Add missed-paddle and closed-source controls. |
| F3 | EPANET single pipe, parallel branches, throttled valve and tank | Laminar Poiseuille and declared Darcy-Weisbach/head-loss references in their valid regimes; continuity at junctions, pump/head power and tank inventory. Halve time steps for tank evolution. Reject full-pipe assumptions when a branch empties; water hammer and moving air fronts remain unsupported. |
| F4 | Dam break / jet force independent reference | Compare converged arrival time, water height and integrated force against an independently meshed OpenFOAM case and available experimental data with provenance. DualSPHysics is a second SPH comparison if the first candidate fails boundaries or cost. Do not tune a library to one puzzle's success flag. |

Before integration, assign fixture-specific numerical bounds from analytical
or experimental uncertainty and the existing Banjo baseline, then freeze
them. Require a convergence trend and full coupled ledgers with declared
external work/reactions, rather than claiming a mass sum proves energy or
momentum closure. Record dissipation/stabilization separately from physical
heat; do not warm a body with unexplained solver corrections. Where no
independent measurement exists, label the result numerical verification.

Suggested performance qualification target, **not an achieved measurement**:
one small coupled fixture should simulate 10 s in at most 10 s of CPU wall
time on a declared one-thread reference machine, fit the documented test
limits with room for the engine, and have no unbounded solve or memory growth.
Report tail latency and loading/playback separately; a smooth replay does not
make computation faster. If 20 mm particles miss the cost budget, report that
and limit the qualified domain/scene instead of increasing compressibility or
loosening winning conditions unnoticed. Any local CUDA experiment must use
the owner's shared GPU queue with declared VRAM/runtime estimates.

The first runtime checkpoint should expose only a qualified contained-water
example on `/test`, retaining ordinary controls, undo/reset/save and physical
wrong-placement checks. A later checkpoint adds filled plumbing, then richer
electronics as their models pass. New shared-library runtime dependencies
need the base-image provisioning described in [deploy.md](deploy.md); a test
archive alone cannot install an absent OS library. Production promotion waits
for review of the measured test revision.

### Verification of this evaluation

This section is a source/documentation review and an implementation plan.
No SPlisHSPlasH, EPANET, Xyce, Chrono, OpenFOAM or Elmer integration was built
or benchmarked in this checkpoint. Existing historical measurements below
are not evidence for a candidate's performance or device accuracy.

The existing `banjo_circuit_tests`, `banjo_spice_network_tests` and
`banjo_water_tests` targets were built through CMake in `build/feedback-test`
(Windows/MSVC Release) and rerun: **3/3 pass, 3.56 s combined CTest wall time**.
This is a baseline regression run, not an isolated performance comparison.
No laws, device parameters, tolerances, level goals or runtime sources changed.
The source-registration guard passes for 274/274 sources in 41 CMake files.

October 16 follow-up: [mechanical motor cables](mechanical-cables.md) now use
Jolt's native rigid contacts and articulated six-axis constraints. No additional
physics dependency was introduced. Chrono remains a candidate for more detailed
wire/rope constitutive laws; motor magnetics and other unimplemented device
interiors below remain unchanged. The original October 13 audit follows.

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
| Flexible cables/bending/mounts | Native articulated Jolt motor/electrical cables since October 16; other connectors and bounded lattice/cohesive models retain their declared limits | **Chrono FEA candidate** for richer constitutive laws, with SOFA another deformable option. Compare stiffness, buckling, bending/torsion, contact, retention and work/reaction transfers. One authoritative contact owner is required. [Chrono](https://projectchrono.org/), [SOFA](https://www.sofa-framework.org/). |
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
