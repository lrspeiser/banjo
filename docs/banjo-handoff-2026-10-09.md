# Banjo implementation and remaining work handoff

Snapshot date: October 9, 2026, Pacific time. Code baseline: **`9173124ed5724871d86c610bd349de05765fb138` on GitHub main**. Work on the physics objective is paused at the owner's request. This handoff adds documentation; it does not resume implementation or validate additional physics.

Banjo has working, bounded 3D physics experiments, shared CPU/CUDA material equations, exact scene continuation, occupied-matter mapping references, and substantial diagnostic and regression coverage. **A reliable strong sheet smash, general deformable ball, admitted reduced continuation, all eight coupled representation families, and complete realtime gameplay remain unfinished.** Passing short controls, preparation tests or rollback tests must not be reported as closing those gates.

## Reading order

1. This handoff for the resume sequence and current boundaries.
2. [Project master plan](project-master-plan.md) for product intent and physical invariants.
3. [Development status](development-status.md), [roadmap](roadmap.md), and [mechanics scorecard](mechanics-scorecard.md) for subsystem history and evidence.
4. [Object representation design](object-representation-design.md) for the active architecture.
5. [Latest material branch checkpoint](material-branch-checkpoint.md), [contact branch checkpoint](contact-branch-checkpoint.md), and [correlated contact bounds](correlated-contact-bounds-checkpoint.md) before editing reduced mechanics.
6. [Codebase rewrite audit](banjo-rewrite-audit.md) before revisiting the older game, removing code, or changing host languages.

The older documents contain chronological notes, sometimes followed by earlier baseline tables. Use revision-specific checkpoints and the current source to resolve conflicts. The complete checkpoint index at the end preserves access to earlier work without treating every historical feature as integrated into the replacement lab.

## Product requirements to retain

- People and LLMs author inspectable, unit-bearing geometry, materials, assemblies and supported interactions through the same bounded compiler/API.
- The engine computes movement, contact, deformation, damage and failure from geometry, state and implemented laws. Material names and display colors do not select outcomes.
- Matter can use large homogeneous regions and finer elements at thin features, interfaces and contact. Coarse storage does not insert alternating air gaps. Numerical elements are samples of matter, not literal molecules.
- A persistent object can change numerical representation while retaining its occupied matter, mass/inertia, motion, history, fields and identity.
- Every physical system must have an editable, calculated 3D demonstration. Before, during and after show accepted states; logs explain what actually happened and why a calculation refused.
- Run, Stop, Reset, replay and relevant inspection actions stay next to the 3D scene on desktop and phone portrait/landscape. Render speed and calculation speed are separate measurements.
- Tools must use general pickup, hand, targeting and action contracts. A new shovel, hoe or unfamiliar LLM-created tool must not require a special animation or instrument-specific engine patch.
- Longer-term gameplay includes accessible gathering/crafting, energy storage and income, construction, grounded chat/voice, autonomous players, independent inventories and shared/private worlds. The replacement lab has not reintegrated that entire game.

## Repository and operational state

| Item | State at handoff |
|---|---|
| Main | Local HEAD and origin/main both `9173124e`; clean working tree before this documentation change |
| Latest code commit | Conditional native material branches and retained support maps |
| Previous code checkpoints | `100e26f5` contact curvature; `839b59a8` correlated contact bounds; `1e3fa250` adjacent controls; `5619cb09` retained thermal matter/continued water |
| Preserved local experiment | `stash@{0}`: `On main: Preserve unfinished common-force-phase accounting for later integration` |
| Active physics objective | Paused; incomplete. Creating this file does not authorize restarting it |
| Public test destination | [Render coupled lab](https://banjo-f1sv.onrender.com/coupled) |
| Last verified hosted physics revision in the session | `100e26f52f29f06975729c6725b749f9d80c36e0`; new `9173124e` deployment was not verified before stopping |
| Local lab | `http://127.0.0.1:18893/coupled`; existing process is stale and needs a deliberate restart before testing latest code |

At handoff the local read-only `/api/checkpoint` reports website revision `9173124e`, server startup revision `100e26f5`, and `restart_pending: true`. It also reports matching disk CPU source/native identities. A matching disk source hash does **not** prove an already-running worker loaded the new DLL. The primary server was started with the older `build/contact-branches` CPU library. Do not tell the owner that refreshing their browser alone activates the new native API.

Keep the stash intact until its contents have been inspected against main and their failed/unfinished boundaries resolved. A stash is local recovery state, not published functionality. Older PR/branch status notes are historical; fetch and inspect actual current PR state before any integration, especially conservative-contact PR #2. Preserve main's raylib frame-control and MSVC runtime fixes. Never force-push or reset concurrent work.

## Architecture that is present

The replacement website is served by [scripts/voxel-lab.py](../scripts/voxel-lab.py). The browser renders observations; it does not own simulation time or invent failure topology.

```text
Bounded declaration or saved accepted state
    -> canonical object registry and world state
    -> explicit CPU or CUDA adapter
    -> shared native material/contact/flight equations
    -> bounded nonlinear solve and physical admission checks
    -> atomic state/history/field commit or complete rollback
    -> accepted snapshots, exact journal and diagnostic receipts
    -> independent 3D rendering and replay
```

### Source map

| Responsibility | Entry points |
|---|---|
| Build and CI | [CMakeLists.txt](../CMakeLists.txt), [.github/workflows/ci.yml](../.github/workflows/ci.yml), [source registration guard](../scripts/check-source-registration.py) |
| HTTP, sessions, auth, routes, journal and checkpoint identity | [voxel-lab.py](../scripts/voxel-lab.py), [access_gate.py](../playground/access_gate.py), [cpu-build-receipt.py](../scripts/cpu-build-receipt.py) |
| Canonical arrays, transactions and accounts | [coupled_world.py](../scripts/coupled_world.py), [object_registry.py](../scripts/object_registry.py) |
| Bounded Newton controller | [coupled_solver.py](../scripts/coupled_solver.py) |
| CPU/CUDA adapters | [cpu_coupled_world.py](../scripts/cpu_coupled_world.py), [gpu_coupled_world.py](../scripts/gpu_coupled_world.py), [CoupledCpuApi.cpp](../src/physics/CoupledCpuApi.cpp) |
| Shared material/contact and flight kernels | [CoupledGpuKernel.hpp](../src/physics/CoupledGpuKernel.hpp), [CoupledFlightKernel.hpp](../src/physics/CoupledFlightKernel.hpp), [FiniteFrameKernel.hpp](../src/physics/FiniteFrameKernel.hpp), [CohesiveInterfaceKernel.hpp](../src/physics/CohesiveInterfaceKernel.hpp), [ConnectorModeKernel.hpp](../src/material/ConnectorModeKernel.hpp) |
| Representation scheduling and preparation | [coupled_representations.py](../scripts/coupled_representations.py), [coupled_modes.py](../scripts/coupled_modes.py), [material_modes.py](../scripts/material_modes.py) |
| Occupied-ball compiler and reference mappings | [solid_representation.py](../scripts/solid_representation.py), [RigidComponent.hpp](../src/rigid/RigidComponent.hpp) |
| Mechanism reference | [mechanisms.py](../scripts/mechanisms.py), [MechanismCpuApi.cpp](../src/physics/MechanismCpuApi.cpp) |
| Flow reference | [flowing_matter.py](../scripts/flowing_matter.py), [FlowReference.cpp](../src/flow/FlowReference.cpp), [FlowCpuApi.cpp](../src/flow/FlowCpuApi.cpp) |
| Thermal fields and matter transfer | [thermal_fields.py](../scripts/thermal_fields.py), [thermal_matter_adapter.py](../scripts/thermal_matter_adapter.py), [ThermalKernel.cpp](../src/thermal/ThermalKernel.cpp), [ThermalMatterTransfer.cpp](../src/thermal/ThermalMatterTransfer.cpp) |
| 3D view and scene controls | [coupled.js](../client/voxel-lab/coupled.js), [coupled-view.mjs](../client/voxel-lab/coupled-view.mjs), [scene-actions.css](../client/voxel-lab/scene-actions.css), [scene-session.mjs](../client/voxel-lab/scene-session.mjs) |
| Declared material data and visible checkpoint | [material-laws.json](../client/voxel-lab/material-laws.json), [checkpoint.json](../client/voxel-lab/checkpoint.json) |
| Production image | [Dockerfile](../Dockerfile) |

The C++ CPU target compiles the same physical trial kernels used by CUDA. NumPy and CuPy are explicit adapters, not automatic fallback choices. The current bounded coupled factory supports 32 bodies, 128 interfaces and 384 private candidates; it is not an unlimited world solver. Current-source save identities include implementation details and refuse incompatible builds/backends. No bitwise cross-platform or cross-GPU determinism claim is established.

Jolt remains important in retained native/game/reference paths. The replacement coupled solver is custom material/contact work, not simply Jolt with a GPU switch. Optional Newton/Warp and PhysX GPU experiments are separate rigid references. A Rust rewrite alone would not remove stiff material clocks, dense derivative work or host/device synchronization.

## Completed work and its boundaries

### Canonical definitions and accepted continuation

Installed object definitions have versioned geometry/material/law identities; instances have stable object and matter IDs. Multiple instances can share a definition while retaining separate state. Exact accepted native arrays/history can be exported and restored on a compatible implementation, with atomic rollback on failure. Tests cover mass/inertia, malformed state, incompatible provenance, changed inputs and next-step continuation. This is bounded scene restart, not a durable multiplayer world service or general saved outcome cache. See [object registry checkpoint](object-registry-checkpoint.md).

### Rigid flight and ordinary drop control

Eligible isolated spheres can advance separately from material islands under the shared gravity/rotation law, with swept eligibility bounds and retained accounts. The useful 10 m ball/fixed-plane control completes contact and rebound. Both CPU and CUDA references have scoped four-material controls and timestep/contact-phase comparisons. The sphere in `/coupled` is a rigid primitive without an internal fracture discretization. A primitive rebound is not evidence that either the ball or floor can crack or dent. See [GPU representations](gpu-representation-checkpoint.md) and [hosted CPU lab](cpu-hosted-lab-checkpoint.md).

### Occupied geometry and rigid to detail mapping reference

`/representations` compiles an adaptive union of occupied cubes, retaining stable cells/interfaces and material-derived volume, mass, COM and full inertia. Coarse interiors and finer boundaries remain actual occupied matter. Collapse/expansion preserves current local geometry, velocity/spin and retained history; incompatible internal motion, disconnected matter or bad geometry refuse. The reference performs isolated gravity flight and stops above the ground. Its adaptive interface solver bindings are not installed, so it cannot calculate internal forces or an impact. See [solid representation checkpoint](solid-representation-checkpoint.md).

### Shared material response and coupled solver

The shared kernels implement bounded cohesive and connector histories, finite-frame reactions, compliant contact and their trial/work accounts. Controlled material loading at `/materials` shows actual damage or plastic rest where supported. CPU/CUDA trials have comparative parity checks. This does not establish calibrated continuum metal dents, oak grain, cutting, tearing, fatigue or arbitrary finite-strain behavior. Connected-sheet motion is experimental and full high-drop fracture remains blocked. See [GPU material laws](gpu-material-laws-checkpoint.md), [finite-frame delivery](gpu-material-frames-checkpoint.md) and [coupled world](gpu-coupled-checkpoint.md).

### Solver performance improvements and diagnostics

Published steps include ordered parallel contributions, actual Jacobian reuse within a private batch, ranked Newton starts, full-step-first line-search batching, explicit normal-contact phase refinement, resident observation buffers, optional native cuSOLVER matrix work, and omission of guaranteed-zero ledger work in reference order. Tests retain original refusal priority, histories and physical gates. The full nonlinear controller still incurs host/device work and is not qualified as resident realtime simulation. Earlier local numerical force optimization was withdrawn after slower/refusing results; retain its archived failure evidence. See [performance audit](drop-performance-audit.md), [realtime release gate](realtime-release-gate.md), and the GPU checkpoint index below.

### Contact geometry and physical inspection

Rounded-boundary repairs preserve tiny exterior gaps in local coordinates. Native read-only contact queries, relative differentials and correlated all-mode bounds retain shared motion, exact-frequency cancellation and finite Cayley rotations. The bounds narrowed uncertainty in matched loaded fixtures but left all 116 ambiguous contact sites. The 3D contact overlay marks actual native sample/target locations and measured contact forces, including historical peak locations. It is not an internal stress, damage or temperature heat map. CUDA spatial receipts remain a separate unimplemented capability. See [contact boundary](contact-boundary-checkpoint.md) and [correlated bounds](correlated-contact-bounds-checkpoint.md).

### Mode and branch preparation through the latest commit

All 54 material-island modes are retained; negative, uncertain and zero modes are not discarded. The original central-difference affine model remains a diagnostic reference. Native material-only reads separate constitutive response from contact curvature. Opening/closing contact candidates include compressed geometric preload curvature, forces/torques and fixed-body rows.

The latest `9173124e` adds native compensated attachment coordinates/Jacobians and explicit elastic opening/compression material candidates. Cohesive shear remains active in compression; connector rest history is retained. Exact-symmetric potential stiffness is assembled directly rather than repaired by averaging numerical columns. Full reaction maps, body state and attachment history are retained for private candidates. The initial sheet can prepare four material/contact branch combinations. Damage/yield/history/energy inconsistencies and unqualified rotation-log preload refuse. **No candidate advances the world and `execution_admitted` remains false.** See [material branches](material-branch-checkpoint.md), [contact branches](contact-branch-checkpoint.md), and [initial mode preparation](native-mode-preparation-checkpoint.md).

### Mechanisms and limited equilibrium sleep

`/mechanisms` calculates a rigid hinged bar with density/inertia-derived motion, gravity, applied torque/load, measured support reactions and energy accounts. An exactly eligible equilibrium can sleep, wake on a delayed load and fall after support removal. This is an ideal pin and restricted reference, not general 3D joint graphs, moving supports, attachment fracture or safe sleep for an oscillating/prestressed material sheet. See [mechanisms](mechanisms-checkpoint.md).

### Water flow and retained continuation

`/flow` solves a conservative depth-averaged flat-bed water reference with native flux/CFL updates and explicit mass, momentum, angular and numerical energy accounts. Continue flow uses the same sealed accepted checkpoint and cumulative budgets; split continuation matches uninterrupted calculation bitwise in the tested fixture. The columns are Eulerian volumes, not persistent water particles. Vertical jets, droplets, full 3D surfaces, viscosity/turbulence and a water wheel are not implemented here. See [flowing matter](flowing-matter-checkpoint.md).

### Thermal and chemical fields

`/thermal-fields` calculates conduction, an ice latent-heat reference, and bounded fuel/oxygen/product reactions at fixed geometry. Optional heat in the CPU coupled lab stays on persistent moving matter with shared timestamps, exact reopen and whole-request rollback. Temperature is calculated, not inferred from contact colors. In this bounded adapter heater work changes thermal energy while mechanical mass/stiffness remain temperature-independent; there is no mechanical-to-thermal exchange. Damaged topology transport, phase-to-flow, reaction transport on moving matter, thermal expansion, softening and contact heating remain unfinished. See [thermal fields](thermal-fields-checkpoint.md) and [persistent fields](persistent-fields-and-lab-controls-checkpoint.md).

### Web operations and usability

The lab has protected same-origin sessions, bounded requests, explicit unavailable-backend refusal, exact journals, session-expiry recovery and image/source receipts. Docker now builds the CPU coupled and mechanism/flow/field libraries and starts the lab rather than the older playground. Stop/Reset and before/contact/after controls sit beside the view, with camera framing and phone layout checks. Heat actions are disabled before a native session exists. A physics refusal keeps the last accepted state; an expired session is a different error and does not silently replay the interrupted action. Source push, successful image build and verified hosted physical behavior are separate milestones.

## Status of the eight representation families

| Family | Usable foundation | Missing for general shared-world use |
|---|---|---|
| Equilibrium and sleeping | Exact-equilibrium mechanism reference | Prestressed/deforming assembly eligibility, error budgets, general wake propagation and retained fields |
| Rigid body | Primitive drop, isolated flight, occupied aggregate mapping reference | Qualified detailed activation/contact and damaged fragment return/reactivation |
| Articulated assembly | Ideal pinned bar with support release | General joints/contacts, movable supports, attachment matter/failure, registry transfers |
| Reduced deformable solid | All-mode inspection, correlated contact bounds, conditional elastic branch preparation | Admitted path/events, nonlinear error, finite endpoint/history transfer and full reaction/work audit |
| Detailed solid | Experimental connected finite-cell/material solve, controlled cohesive/plastic histories | Reliable strong impacts, internally deformable ball, refinement/calibration, adaptive contact and fragments |
| Flowing matter | Conservative depth-averaged water with exact continuation | True 3D pouring, solid/phase mapping, articulated boundary work and water wheel |
| Thermal field | Fixed-geometry reference and retained moving-matter heat | Damage/fragment transport, thermal mechanics, contact exchange, phase flow |
| Chemical and reaction field | Closed local fuel/oxygen/products reference | Species transport, oxygen access, moving/deforming matter coupling, calibrated propagation |

These are partial foundations across eight families, not eight completed world systems.

## Historical game work and reintegration backlog

The older application includes checkpoints for multiplayer/player persistence, inventory and quick slots, pickup/carry, hand-target input, excavation and shoreline behavior, raw storage/crafting, recipe/design editing, tool admission/use/wear, skill/goal evidence, energy/solar/market, rover recovery, machines, construction guidance, AI explorers, chat and voice. Their individual implemented scope and failures are recorded in the checkpoint index and rewrite audit. They are not automatically part of the replacement `/coupled` lab.

Preserve these product requirements when reintegrating:

| Area | Required resumed experience and acceptance |
|---|---|
| Pickup and tool use | Click/touch the whole item, visibly equip it, act at the selected surface with a clear reachable/usable target. Verify arbitrary supported tool definitions and phone coordinates; avoid flying held-tool visuals and instrument-specific routes |
| Terrain and resources | Smooth natural hills with sharp excavation cuts, obvious exposed material, physical detached matter, water-aware holes/channels and collectable material. Measure a practical 10 ft excavation loop; do not inherit a canned pile animation as physics |
| Build and inventory | Raw material/products/energy in inventory; building blocks/saved designs in a simple build/lab path. Thumbnail-driven make/equip/store/retrieve with specific shortages/skills and atomic material/energy/history transfer |
| Guidance and skills | Explain steps where the action belongs; earn skill evidence from actual use and show clear unlocks. Chat/advice is explicit or event-based, not periodic LLM polling while walking |
| Chat and voice | One grounded interface across screens, access to actual state/tools, deliberate changes and press-to-talk with menu audio preference |
| Machines and rovers | Minimal status plus commands; actual progress, input/output/storage, stuck detection/recovery and separate ownership |
| Energy and progression | Solar/other income and persistent stored energy, clear balance/rates, justified market prices and a tested achievable progression path |
| Construction | Shared components/attachments for house/castle/airport scale, guided placement and supported stress tests. Earthquake, meteor, fire and other buttons require implemented laws |
| Multiplayer and publishing | Independent avatars/inventories/tech trees, simultaneous distant interactions, shared/private worlds, server authority, versioned persistence and bounded deployment |

The earlier inorganic-only game policy and later oak comparison requirements have different scopes: keep organic game availability deliberate while retaining oak as a mandatory physics regression material. Do not delete oak coverage because wood gameplay is deferred.

## Measured results to retain

| Evidence and scope | Result | Interpretation |
|---|---|---|
| Latest material preparation, Windows, four native materials | Coordinate derivative error <= 5.79e-11; attachment curvature discrepancy <= 8.86e-10; one-sided force errors <= 7.08e-11 for glass/oak/ice and 8.64e-12 for iron | Private analytical/constitutive preparation; not a transfer, runtime or conservation certification |
| `9173124e` scoped Windows verification | Five CTests pass in 23.09 s; protected CPU HTTP gateway passes; 354/354 sources registered | No full repository CI, latest Linux, ordinary browser or Render validation claim |
| Previous contact branch checkpoint | Eight Windows suites, independent Linux branch/modes checks, protected HTTP and local/hosted 3D inspection | Evidence for `100e26f5`, not an automatic validation of later material code |
| Last hosted ordinary 10 m rigid control, previous revision | 2 physical s in about 3.634 wall s including HTTP; upward speed 8.394349 m/s; energy residual about 1.03e-10 J | Useful actual rebound control, still below end-to-end realtime in that run; no sheet fracture |
| Earlier 16 CPU primitive controls | Glass/oak/iron/ice, 240/960 Hz host clock, two contact phases; fine-phase position error <0.4 micrometres and speed error <0.01 m/s | Independent compliance/gravity controls under declared assumptions |
| Historical connected glass GPU attempt | 1.425 physical s / about 42.27 wall s and Newton refusal | Strong impact and realtime gate fail; later source/request sizes have separate receipts |
| Retained heated/unheated matched controls | Same accepted mechanical state across four materials; combined energy residual magnitude below 8.2e-10 J | Bounded uncoupled heater/thermal-plus-mechanical accounting; no thermal weakening |
| Adaptive occupied ball reference | 32 / 224 / 1,168 cells at boundary levels 2 / 3 / 4; fine-level volume error +1.461%, one-axis inertia error +3.124% | Geometry approximation is explicit; finer is not automatically admissible or monotonically better |

Receipts: [latest material data](evidence/material-branches/verification.json), [contact preparation](evidence/contact-branches/verification.json), [family integration](evidence/physics-families/integration.json), [occupied geometry](evidence/solid-representation/reference.json), [CPU hosted controls](cpu-hosted-lab-checkpoint.md). Do not compare timing rows from different sources, host request sizes or scopes as a measured optimization.

## Remaining work in execution order

### First verify the published checkpoint

On explicit resumption, rebuild the latest CPU library and restart the local server with that library. Verify image/source/native identities and actual branch inspection on local and hosted pages. Exercise ordinary window/browser input, not just automated receipts. Keep Linux and current deployment verification open until measured. Finish this small verification checkpoint before more physics changes.

### Qualify conditional reduced continuation

The immediate physics task is to turn preparation into an admitted native-consistent path. Qualify mixed per-attachment opening/compression and contact opening/closing events, feature changes, interior extrema, elastic validity and nonlinear error. Handle finite endpoint poses and physical angular velocity; do not interpret a potential Hessian as the timestep Newton Jacobian. Rotation-log preload needs qualified curvature before it is admitted. Cohesive maximum opening can change during an interior excursion even if final damage is unchanged.

Retain full support forces/torques and integrate external work, momentum and angular momentum at a common origin. Audit kinetic, elastic, contact, dissipative and numerical energy without double counting. Transfer native body/interface/history state atomically; failed preparation, endpoint reconstruction or publication restores the complete interval. Compare common-time motion and history to always-detailed glass/oak/iron/ice controls under refinement. Until these gates pass, keep `execution_admitted: false` and the detailed solver authoritative.

**Owner test when finished:** the sheet can flex/vibrate during a 10 m fall using an explicitly qualified representation, with no arbitrary freezing; support removal or a new load wakes detail before it becomes invalid. Inspect mode, clock, active work and actual transfer residuals beside the 3D scene.

### Complete strong contact and damage

Retain and repair the current high-drop refusal with its actual inputs/candidate history. Complete freely chosen impacts on supported sheets and compare timestep/resolution, loading/unloading, second hits and support motion. Add qualified detailed ball matter so the striker can deform or break too. Constitutive calibration and separate laws are required for realistic oak grain, continuum metal denting/tearing and thin-edge cutting; connector yielding is not all of these.

**Owner test when finished:** choose material, mass, height and impact location; see actual glass separation or qualified permanent metal deformation and subsequent collisions. A failed setup explains its unsupported law or calculated refusal rather than appearing to do nothing.

### Scale contact work and representation transfer

Bind adaptive occupied elements/interfaces to qualified laws; the medium/fine ball currently exceeds the small coupled factory capacities. Introduce local analytical/block derivatives and appropriate sparse solving, retaining the dense reference until equivalence and accuracy gates pass. Preserve histories, geometry, nonrigid energy and finite-cell spin through coarse/fine mapping and damaged-fragment reactivation. Include remote support/load transmission. Never heal damage or normalize away geometry error.

**Owner test when finished:** a thin edge stays resolved beside a large block; a damaged fragment responds to a later impact with its retained state. Unchanged distant terrain does not increase active impact work proportionally.

### Complete fields and general assemblies

Extend mechanism joints/supports/contact into the registry with shared clocks/reactions. Map heat/species through damage and fragments, then implement qualified expansion/weakening, phase/mass changes and conservative solid-to-flow transfer. Add species/reactant transport for reaction propagation. Introduce a genuine 3D free-surface flow model for vertical pouring and fluid/solid/hinge work exchange.

**Owner test when finished:** pour calculated water onto a wheel and see torque/output work bounded by supplied water energy; heat and damage the same object, save/reopen it and continue its retained fields. No prescribed stream or wheel motion.

### Meet complete realtime and delivery gates

Move the bounded nonlinear control, norms, fault choice, history commit, work/P/L audits and rollback onto CUDA after CPU reference qualification. Reuse buffers/graphs with actual changed input and invalidation; matrix-only graph tests do not complete this. Publish compact accepted snapshots independently from the audit journal, with bounded ordering/backpressure. Keep render interpolation compatible with topology and accepted physical time.

The current small-scene release goal is a **completed two-physical-second drop in at most two wall seconds**, including impact and declared delivery scope. Measure repeated warm/cold and tail behavior, archive failure work, report frame age and input latency. The proposed accepted-checkpoint control target is below 100 ms, not a measured guarantee. Keep slow/refused cases visible. A fast rigid flight or GPU kernel does not satisfy this gate.

### Rebuild the user creation and game loop

Use the same immutable definition, mutable state and compiler for unfamiliar LLM-created objects. Add inspectable plan revisions, supported-law reporting, inventory/energy-backed creation and safe world placement; then reconnect progression, construction, machines and multiplayer. Keep proactive LLM work driven by explicit advice requests or meaningful events and use fast configured models for suitable authoring tasks. The model must never invent constitutive outcomes or run on every physics tick.

**Owner test when finished:** gather materials, ask for a new supported tool or assembly, inspect/edit/make it, equip/place it and physically test it through the same pipeline. No special recipe-name engine route; unsupported capability is clear before manufacturing.

## Resume build and test procedures

Use a separate build directory. The following are procedures for resumption, not claims that this documentation change reran the physics suites.

```powershell
git fetch origin
git status --short
git log -8 --oneline
git stash list
python scripts/check-source-registration.py
cmake -S . -B build/handoff-resume -DBANJO_BUILD_LAB=OFF
cmake --build build/handoff-resume --config Release --target banjo_coupled_cpu banjo_voxel_world_run banjo_mechanisms_cpu banjo_flow_cpu banjo_thermal_fields --parallel 4
ctest --test-dir build/handoff-resume -C Release -R 'banjo_(material_branch|contact_branch|contact_observation|cpu_coupled_modes|coupled_view)_tests' --output-on-failure
python tests/cpu_coupled_gateway_test.py --library build/handoff-resume/Release/banjo_coupled_cpu.dll --native build/handoff-resume/Release/banjo_voxel_world_run.exe
```

Those targets do not build every registered test executable. For broader verification, build the appropriate test targets or the complete configured build before running the expanded CTest profile. GPU parity tests require the pinned working CUDA Python/runtime and configured dependencies. Re-run only checks needed by the changed scope; complete material claims need glass and oak, retain iron and ice. Record exact revision, binary/source identities, geometry, units, timestep, resolution, law versions, supported domain and tolerances.

Important suite families include CPU world/parity/high-drop, object registry, contact observations/branches, material branches, mode preparation, occupied geometry, thermal transfer/adapter/coupled heat, mechanisms, flow continuation/API, protected HTTP, session/playback and actual view/action-layout tests. Broader historical runtime lint/test-hub failures were recorded as open; they were not resolved by the five latest scoped suites. See [hosted CPU checkpoint](cpu-hosted-lab-checkpoint.md) for their historical boundary and reproduce before claiming a full green CI.

### Start a fresh local test server after resumption

First identify the process listening on 18893 and its full command line. Stop only the owned Banjo server and its owned workers. Do not reuse an old PID from a helper file, kill unrelated Python processes or start a competing server on the same port.

```powershell
$env:BANJO_MECHANISMS_LIBRARY=(Resolve-Path 'build/handoff-resume/Release/banjo_mechanisms_cpu.dll').Path
$env:BANJO_FLOW_LIBRARY=(Resolve-Path 'build/handoff-resume/Release/banjo_flow_cpu.dll').Path
$env:BANJO_THERMAL_FIELDS_LIBRARY=(Resolve-Path 'build/handoff-resume/Release/banjo_thermal_fields.dll').Path
python scripts/voxel-lab.py --native build/handoff-resume/Release/banjo_voxel_world_run.exe --cpu-library build/handoff-resume/Release/banjo_coupled_cpu.dll --port 18893
```

The command runs in the foreground for deliberate local testing. If launching a background helper, use `Start-Process -WindowStyle Hidden` and separate ignored stdout/stderr logs. Add `--gpu-python build/gpu-runtime/Scripts/python.exe` only if that local runtime exists and is intended for the test. Ninja/Linux builds use different binary locations and `.so` names; do not copy the Windows DLL path into a Linux deployment.

Read `/api/checkpoint` and compare startup/source/native identity. Run an actual CPU operation so stale-worker/API mismatches cannot hide behind static metadata. A source edit invalidates resident code; restart rather than silently mixing versions. Keep passwords/API keys in ignored local or host secrets; never print or commit them.

### Owner test itinerary

| Page and action | Expected current experience | Boundary to report |
|---|---|---|
| `/coupled`: Fall & rebound, then Drop & rebound, Full drop, contact inspection | Actual 10 m rigid flight/contact/rebound, accepted time and before/contact/after | No internal ball/floor fracture; whole pipeline may be slower than realtime |
| `/coupled`: Save scene, Open scene, continue | Exact accepted state/history on a compatible build | New source/backend/build may refuse an older save; migration is not automatic |
| `/coupled`: Inspect vibration basis | 3D sheet stays at the same time; material/contact candidates and support-map status appear beside it | Reduced motion remains not admitted; unsupported loaded states may refuse qualification |
| `/coupled`: retain heat, heater and Temperature | Calculated temperature remains on the moving accepted matter | No thermal weakening, contact heat, fragment transport or flowing melt |
| `/representations`: Compile & calculate, Inspect interior, Expand into elements | Actual occupied cube union and conservative isolated flight/mapping | Stops before impact; adaptive material/contact solver is absent |
| `/mechanisms`: Calculate & play, equilibrium wake and support release | Calculated pinned-bar motion, reactions and free fall after release | Restricted ideal pin, not general assemblies or joint fracture |
| `/flow`: calculate, then Continue flow | Same native water field continues with cumulative accounts | Depth-averaged flat-bed columns, not 3D pour/wheel |
| `/thermal-fields`: conduction, ice, fuel/oxygen and save/reopen | Calculated temperatures, latent fraction and local species/products | Fixed geometry/restricted reservoirs; no general fire propagation |
| Phone portrait and landscape | Relevant action dock and whole scene are usable without scrolling away from action | Latest material UI change still requires ordinary current-revision browser verification |

For each itinerary, retain actual before/impact/after screenshots and their time, backend, revision and receipt. Screen comparison should validate geometry/time/field colors against calculated samples, including refusals and unchanged last-accepted state. A picture alone is not a fracture/conservation test.

## Retirement and duplication rules

Use the [rewrite audit deletion ledger](banjo-rewrite-audit.md) for concrete candidates. Keep CPU analytical/constitutive oracles, native laws/history, exact failure records, source guard and independent rendering. Move dense numerical derivatives and full-JSON-per-tick paths to reference/diagnostic roles only after replacements cover their accepted and refused behavior. Consolidate routes and state owners through a versioned contract; do not delete whole directories because a newer demo exists.

Retire any old outcome pulse, special-case pickup/targeting route or scripted material animation only after identifying its callers and covering the replacement end-to-end. Preserve normal input-loop and MSVC fixes. A new `.cpp` or test is not complete until a CMake target compiles it. Deliberate exclusions require the guard's documented allowlist, not deletion of the failing test.

## Publishing and handoff discipline

Fetch before integration; preserve concurrent changes; publish coherent verified checkpoints with ordinary main pushes or the required PR workflow. Never force-push. Main publishing is owner-authorized; it is not separate authorization to send messages or perform a production deployment outside the existing workflow. Record exact outgoing and hosted revisions, measured behavior, failing gates and next user test. Do not call the full platform complete because an intermediate build or reference passes.

This documentation checkpoint validates links, scope and source registration only. It introduces no new physical validation. On resumption, begin with the published-checkpoint verification and conditional reduced-path tasks above, rather than rebuilding another unrelated demonstration.

## Complete checkpoint index

The index below includes every top-level `docs/*checkpoint.md` file present in the `9173124e` working tree, including the latest material checkpoint. Titles locate the original implementation/evidence; inclusion does not assert current integration, qualification or deployment. Supplementary canonical plans, audits and designs are linked in the sections above.

| Checkpoint | Recorded subject |
|---|---|
| [3d-test-world-checkpoint.md](3d-test-world-checkpoint.md) | Interactive 3D test world — October 7, 2026 |
| [adaptive-checkpoint.md](adaptive-checkpoint.md) | Adaptive compliant reference and next laboratory milestone |
| [adaptive-material-contact-checkpoint.md](adaptive-material-contact-checkpoint.md) | Error-controlled material contact |
| [adaptive-runtime-checkpoint.md](adaptive-runtime-checkpoint.md) | Adaptive runtime assembly trials |
| [additional-physics-checkpoint.md](additional-physics-checkpoint.md) | Bounded thermal activation and experimental damage trials |
| [affine-contact-envelope-checkpoint.md](affine-contact-envelope-checkpoint.md) | Continuous affine motion and native contact envelopes |
| [ai-explorer-checkpoint.md](ai-explorer-checkpoint.md) | AI explorer checkpoint — September 30, 2026 |
| [ai-processing-recovery-checkpoint.md](ai-processing-recovery-checkpoint.md) | Shared processing and exhausted-input recovery — October 3, 2026 |
| [algo1-impulse-woodbury-checkpoint.md](algo1-impulse-woodbury-checkpoint.md) | Algorithm 1: a precomputed impulse-response library with Woodbury crack updates |
| [algo2-griffith-events-checkpoint.md](algo2-griffith-events-checkpoint.md) | Algorithm 2 checkpoint: an event-driven Griffith cascade with no time stepping |
| [algo3-propagator-cones-checkpoint.md](algo3-propagator-cones-checkpoint.md) | Algorithm 3 checkpoint: precomputed propagators, causal cones, and what the engine actually allows |
| [assembly-assessment-checkpoint.md](assembly-assessment-checkpoint.md) | Read-only assembly assessment API |
| [assembly-draft-checkpoint.md](assembly-draft-checkpoint.md) | Saved assembly drafts |
| [assembly-review-checkpoint.md](assembly-review-checkpoint.md) | LLM review of verified assembly evidence |
| [assembly-review-ui-checkpoint.md](assembly-review-ui-checkpoint.md) | LLM assembly review in the workshop |
| [assembly-spin-checkpoint.md](assembly-spin-checkpoint.md) | Rotational assembly loading and small-box inertia correction |
| [assembly-test-checkpoint.md](assembly-test-checkpoint.md) | Bounded isolated assembly test API |
| [assembly-test-ui-checkpoint.md](assembly-test-ui-checkpoint.md) | Revision-bound assembly tests in the workshop |
| [assembly-ui-checkpoint.md](assembly-ui-checkpoint.md) | Assembly designs in the workshop |
| [assembly-work-checkpoint.md](assembly-work-checkpoint.md) | Assembly collision-step work localization |
| [assistant-checkpoint.md](assistant-checkpoint.md) | Automatic creator assistant checkpoint |
| [automatic-excavation-piles-checkpoint.md](automatic-excavation-piles-checkpoint.md) | Automatic excavation piles — October 3, 2026 |
| [bending-oracle-checkpoint.md](bending-oracle-checkpoint.md) | Exact prescribed-bending integration oracle |
| [blunt-control-substep-checkpoint.md](blunt-control-substep-checkpoint.md) | Blunt-control assertion under the stability clock |
| [bonded-bowl-checkpoint.md](bonded-bowl-checkpoint.md) | Actual bowl fracture: experimental bonded-cell model |
| [bowl-checkpoint.md](bowl-checkpoint.md) | Craft-and-release bowl lab |
| [box-face-checkpoint.md](box-face-checkpoint.md) | Material-backed box-face attachments |
| [build-lab-chat-checkpoint.md](build-lab-chat-checkpoint.md) | Build selection and shared typed chat |
| [building-sledgehammer-checkpoint.md](building-sledgehammer-checkpoint.md) | Built wall, sledgehammer, and 160k-cell experiment |
| [camp-light-opening-checkpoint.md](camp-light-opening-checkpoint.md) | Collected output to a useful Camp light |
| [canonical-machine-use-checkpoint.md](canonical-machine-use-checkpoint.md) | Canonical machine Make and Use |
| [centered-integration-checkpoint.md](centered-integration-checkpoint.md) | Centered elastic integration in the voxel laboratory |
| [centered-rotation-checkpoint.md](centered-rotation-checkpoint.md) | Continuous rotation in the centered voxel integrator |
| [chat-object-transport-checkpoint.md](chat-object-transport-checkpoint.md) | Room-chat object-result transport |
| [cohesive-adaptive-checkpoint.md](cohesive-adaptive-checkpoint.md) | Adaptive rigid cohesive advances |
| [cohesive-asymmetric-checkpoint.md](cohesive-asymmetric-checkpoint.md) | Asymmetric cohesive rigid verification |
| [cohesive-compression-checkpoint.md](cohesive-compression-checkpoint.md) | Reversible interface compression |
| [cohesive-dynamics-checkpoint.md](cohesive-dynamics-checkpoint.md) | Parallel physics: coupled separation and visible accepted states |
| [cohesive-interface-checkpoint.md](cohesive-interface-checkpoint.md) | Work-accounted opening-interface reference |
| [cohesive-orbit-checkpoint.md](cohesive-orbit-checkpoint.md) | Analytical circular-motion checkpoint |
| [cohesive-pair-checkpoint.md](cohesive-pair-checkpoint.md) | Finite-mass cohesive dynamics reference |
| [cohesive-patch-checkpoint.md](cohesive-patch-checkpoint.md) | Finite rectangular cohesive patch reference |
| [cohesive-rigid-checkpoint.md](cohesive-rigid-checkpoint.md) | Coupled rigid cohesive dynamics checkpoint |
| [cohesive-spatial-checkpoint.md](cohesive-spatial-checkpoint.md) | Three-dimensional central cohesive reference |
| [column-rendering-checkpoint.md](column-rendering-checkpoint.md) | Sparse terrain rendering and character joining — October 3, 2026 |
| [column-terrain-checkpoint.md](column-terrain-checkpoint.md) | Material-column terrain comparison — October 3, 2026 |
| [combined-bending-checkpoint.md](combined-bending-checkpoint.md) | Simultaneous compression and tensile damage |
| [common-phase-work-checkpoint.md](common-phase-work-checkpoint.md) | Realtime pipeline: actual native work phases |
| [compiled-load-checkpoint.md](compiled-load-checkpoint.md) | Loaded compiled box-face joints |
| [compiled-runtime-checkpoint.md](compiled-runtime-checkpoint.md) | Live compiled material runtime v1 |
| [compliance-checkpoint.md](compliance-checkpoint.md) | Explicit normal compliance and sustained-contact reference |
| [component-thumbnails-checkpoint.md](component-thumbnails-checkpoint.md) | Component thumbnails — October 1, 2026 |
| [compound-water-checkpoint.md](compound-water-checkpoint.md) | Exact compound objects in native water — October 3, 2026 |
| [connection-condition-reuse-checkpoint.md](connection-condition-reuse-checkpoint.md) | Connection condition and paid replacement — October 2, 2026 |
| [connector-plasticity-checkpoint.md](connector-plasticity-checkpoint.md) | Persistent connector plasticity checkpoint |
| [conservative-reference-checkpoint.md](conservative-reference-checkpoint.md) | Coupled conservative reference solver |
| [constituent-transfer-checkpoint.md](constituent-transfer-checkpoint.md) | Canonical constituent ownership transfer |
| [construction-guidance-checkpoint.md](construction-guidance-checkpoint.md) | Construction requirements, starter foundations and proactive guidance |
| [construction-guide-usability-checkpoint.md](construction-guide-usability-checkpoint.md) | Stable advice, explicit help and carried lamp recovery |
| [construction-placement-checkpoint.md](construction-placement-checkpoint.md) | Inventory placement and saved construction intent |
| [contact-boundary-checkpoint.md](contact-boundary-checkpoint.md) | Rounded contact boundary repair |
| [contact-branch-checkpoint.md](contact-branch-checkpoint.md) | Separate native contact preparation |
| [contact-checkpoint.md](contact-checkpoint.md) | Conservative material contact: development checkpoint |
| [contact-convergence-checkpoint.md](contact-convergence-checkpoint.md) | Contact-state convergence diagnostics and numerical controls |
| [contact-fracture-checkpoint.md](contact-fracture-checkpoint.md) | Contact capacity and spring reaction checkpoint |
| [contact-model-checkpoint.md](contact-model-checkpoint.md) | Contact-model comparison in the voxel world |
| [contact-ownership-checkpoint.md](contact-ownership-checkpoint.md) | Explicit runtime contact ownership |
| [contact-phase-checkpoint.md](contact-phase-checkpoint.md) | Contact phase and source precision — October 7, 2026 |
| [contact-precision-checkpoint.md](contact-precision-checkpoint.md) | Contact retains small physical displacements |
| [contact-stationarity-checkpoint.md](contact-stationarity-checkpoint.md) | Final contact slip and twisting disagreement |
| [contact-time-refinement-checkpoint.md](contact-time-refinement-checkpoint.md) | Contact time refinement — October 7, 2026 |
| [contact-witness-accuracy-checkpoint.md](contact-witness-accuracy-checkpoint.md) | Contact witness and work accuracy — October 7, 2026 |
| [continuum-pressure-checkpoint.md](continuum-pressure-checkpoint.md) | Spatial pressure and springback reference |
| [continuum-pressure-performance-checkpoint.md](continuum-pressure-performance-checkpoint.md) | Bounded pressure loading and an assembled continuum solve |
| [controlled-contact-checkpoint.md](controlled-contact-checkpoint.md) | Controlled coupled contact — October 7, 2026 |
| [convergence-study-checkpoint.md](convergence-study-checkpoint.md) | Fracture convergence study: measured timestep and resolution behaviour |
| [correlated-contact-bounds-checkpoint.md](correlated-contact-bounds-checkpoint.md) | Correlated native contact bounds |
| [coupled-contact-checkpoint.md](coupled-contact-checkpoint.md) | Coupled contact reference checkpoint |
| [coupled-contact-search-checkpoint.md](coupled-contact-search-checkpoint.md) | Coupled contact search checkpoint — October 7, 2026 |
| [coupled-friction-block-checkpoint.md](coupled-friction-block-checkpoint.md) | Coupled sliding and twisting contact — October 8, 2026 |
| [coupled-manifold-checkpoint.md](coupled-manifold-checkpoint.md) | Coupled material manifold checkpoint — October 7, 2026 |
| [coupled-support-checkpoint.md](coupled-support-checkpoint.md) | Coupled support and impact-timing checkpoint |
| [cpu-hosted-lab-checkpoint.md](cpu-hosted-lab-checkpoint.md) | Explicit CPU physics lab for Render |
| [cpu-local-jacobian-checkpoint.md](cpu-local-jacobian-checkpoint.md) | Bounded CPU local Jacobians |
| [creator-checkpoint.md](creator-checkpoint.md) | Creator workshop checkpoint |
| [criterion-energy-scaled-checkpoint.md](criterion-energy-scaled-checkpoint.md) | Energy-scaled bond failure: derivation, convergence ladder, and what still does not converge |
| [cube-targeting-checkpoint.md](cube-targeting-checkpoint.md) | Cube targeting and saved-world repair — October 4, 2026 |
| [cursor-dig-target-checkpoint.md](cursor-dig-target-checkpoint.md) | Clicked ground and dig readiness — October 3, 2026 |
| [daylight-player-checkpoint.md](daylight-player-checkpoint.md) | Player day/night checkpoint — October 1, 2026 |
| [detached-flight-checkpoint.md](detached-flight-checkpoint.md) | Detached native cell flight — experimental stepping |
| [double-application-checkpoint.md](double-application-checkpoint.md) | Double-position application promotion |
| [double-geometry-contact-checkpoint.md](double-geometry-contact-checkpoint.md) | CPU pose geometry and paired contact accuracy — October 7, 2026 |
| [double-rigid-source-checkpoint.md](double-rigid-source-checkpoint.md) | Double CPU rigid source — October 7, 2026 |
| [drop-test-checkpoint.md](drop-test-checkpoint.md) | Object-on-object drop checkpoint |
| [drop-view-checkpoint.md](drop-view-checkpoint.md) | High-drop visibility and controls — October 9, 2026 |
| [dynamic-material-playground-checkpoint.md](dynamic-material-playground-checkpoint.md) | Property-authored dynamic material playground |
| [elastic-newton-checkpoint.md](elastic-newton-checkpoint.md) | Global elastic solve checkpoint |
| [embedded-playground-checkpoint.md](embedded-playground-checkpoint.md) | Chat-authored experiments and embedded 3D controls |
| [endpoint-contact-checkpoint.md](endpoint-contact-checkpoint.md) | Coupled endpoint friction with material bounce — October 8, 2026 |
| [energy-rupture-checkpoint.md](energy-rupture-checkpoint.md) | Energy-accounted rupture: collision-driven reference |
| [event-material-checkpoint.md](event-material-checkpoint.md) | Event contact and comparative-material checkpoint |
| [event-root-checkpoint.md](event-root-checkpoint.md) | Contact root recovery and full-resolution stepping |
| [execution-checkpoint.md](execution-checkpoint.md) | Execution checkpoint — September 5, 2026 |
| [experiment-review-checkpoint.md](experiment-review-checkpoint.md) | Experiment logging and review checkpoint — September 6, 2026 |
| [exposed-layer-peer-checkpoint.md](exposed-layer-peer-checkpoint.md) | Exposed layers and peer terrain delivery — October 3, 2026 |
| [fabrication-ai-build-checkpoint.md](fabrication-ai-build-checkpoint.md) | AI construction through paid jobs — October 1, 2026 |
| [fabrication-assembly-goods-checkpoint.md](fabrication-assembly-goods-checkpoint.md) | Processed supplies in paid machine construction |
| [fabrication-energy-checkpoint.md](fabrication-energy-checkpoint.md) | Native energy funding for fabrication — October 1, 2026 |
| [fabrication-lab-funding-checkpoint.md](fabrication-lab-funding-checkpoint.md) | Lab funding and replacement use — October 1, 2026 |
| [fabrication-machine-checkpoint.md](fabrication-machine-checkpoint.md) | Paid exact rigid machines — October 1, 2026 |
| [fabrication-paid-design-checkpoint.md](fabrication-paid-design-checkpoint.md) | Reviewed paid designs — October 1, 2026 |
| [fabrication-remake-checkpoint.md](fabrication-remake-checkpoint.md) | Selected-item Lab remake checkpoint — October 1, 2026 |
| [fabrication-starter-power-checkpoint.md](fabrication-starter-power-checkpoint.md) | Finite starter solar output — October 1, 2026 |
| [fabrication-stock-checkpoint.md](fabrication-stock-checkpoint.md) | Player material funding for fabrication — October 1, 2026 |
| [fast-gpu-checkpoint.md](fast-gpu-checkpoint.md) | Fast-GPU lane checkpoint: the CPU lattice physics on a colour-parallel schedule |
| [fast-modal-checkpoint.md](fast-modal-checkpoint.md) | Fracture from a precomputed basis (the modal lane) |
| [fast-quasistatic-checkpoint.md](fast-quasistatic-checkpoint.md) | Quasi-static fracture lane checkpoint |
| [finite-rotation-parallel-checkpoint.md](finite-rotation-parallel-checkpoint.md) | Parallel physics: rotation, tearing, metal state and thermal playback |
| [flowing-matter-checkpoint.md](flowing-matter-checkpoint.md) | Flowing matter: bounded hydrostatic reference |
| [force-boundary-contact-checkpoint.md](force-boundary-contact-checkpoint.md) | Contact at Verlet force boundaries — October 7, 2026 |
| [force-contact-work-checkpoint.md](force-contact-work-checkpoint.md) | Force/contact phase work audit — October 7, 2026 |
| [fracture-microscope-checkpoint.md](fracture-microscope-checkpoint.md) | Interactive fracture microscope |
| [fresh-made-strike-checkpoint.md](fresh-made-strike-checkpoint.md) | Fresh-world made-item contact and persistence checkpoint |
| [fresh-workbench-checkpoint.md](fresh-workbench-checkpoint.md) | Ordinary fresh-world workbench |
| [friction-fastpath-checkpoint.md](friction-fastpath-checkpoint.md) | Contact performance trial and retained regression checks |
| [functional-test-checkpoint.md](functional-test-checkpoint.md) | Bounded physical tests for creator recipes |
| [gameplay-interaction-trace-checkpoint.md](gameplay-interaction-trace-checkpoint.md) | Gameplay interaction diagnostics — October 6, 2026 |
| [gathering-supply-checkpoint.md](gathering-supply-checkpoint.md) | Gathering and recursive supply checkpoint — October 1, 2026 |
| [general-experiment-checkpoint.md](general-experiment-checkpoint.md) | General experiment authoring checkpoint |
| [glass-swing-world-checkpoint.md](glass-swing-world-checkpoint.md) | Intact slab and native swing checkpoint — October 7, 2026 |
| [gpu-active-graph-checkpoint.md](gpu-active-graph-checkpoint.md) | Ordered active work and final-update convergence |
| [gpu-contact-checkpoint.md](gpu-contact-checkpoint.md) | Resident GPU contact yard — October 8, 2026 |
| [gpu-contact-timing-checkpoint.md](gpu-contact-timing-checkpoint.md) | GPU normal-contact timing — October 9, 2026 |
| [gpu-coupled-checkpoint.md](gpu-coupled-checkpoint.md) | Coupled GPU finite cells — October 9, 2026 |
| [gpu-line-search-checkpoint.md](gpu-line-search-checkpoint.md) | GPU Newton probe scheduling — October 9, 2026 |
| [gpu-material-frames-checkpoint.md](gpu-material-frames-checkpoint.md) | GPU finite-frame material force bridge |
| [gpu-material-laws-checkpoint.md](gpu-material-laws-checkpoint.md) | Shared material laws on CUDA — October 9, 2026 |
| [gpu-newton-diagnostics-checkpoint.md](gpu-newton-diagnostics-checkpoint.md) | CUDA fault collection and Newton failure evidence — October 9, 2026 |
| [gpu-parallel-checkpoint.md](gpu-parallel-checkpoint.md) | Parallel coupled CUDA pipeline — October 9, 2026 |
| [gpu-phase-profile-checkpoint.md](gpu-phase-profile-checkpoint.md) | GPU phase measurement, October 9 |
| [gpu-ranked-newton-checkpoint.md](gpu-ranked-newton-checkpoint.md) | Ranked CUDA Newton starts — October 9, 2026 |
| [gpu-representation-checkpoint.md](gpu-representation-checkpoint.md) | GPU representation adapter: isolated flight and an awake material island |
| [gpu-resident-linear-checkpoint.md](gpu-resident-linear-checkpoint.md) | Device-status GPU linear solve — October 9, 2026 |
| [height-drop-checkpoint.md](height-drop-checkpoint.md) | Off-centre drops and iron-on-glass height comparison |
| [held-strike-actor-checkpoint.md](held-strike-actor-checkpoint.md) | Held strikes: actual player hand rollback — October 2, 2026 |
| [held-strike-contact-checkpoint.md](held-strike-contact-checkpoint.md) | Finite rigid contact and native reaction transfer — October 2, 2026 |
| [held-strike-fixed-contact-checkpoint.md](held-strike-fixed-contact-checkpoint.md) | Constrained fixed-assembly point contact — October 2, 2026 |
| [held-strike-hand-checkpoint.md](held-strike-hand-checkpoint.md) | Held strikes: shared native grip and target clock — October 2, 2026 |
| [held-strike-integrator-checkpoint.md](held-strike-integrator-checkpoint.md) | Held strikes: explicit CPU target integration — October 2, 2026 |
| [held-strike-load-checkpoint.md](held-strike-load-checkpoint.md) | Finite lattice loads — October 2, 2026 |
| [held-strike-rollback-checkpoint.md](held-strike-rollback-checkpoint.md) | Held strikes: native and CPU target rollback - October 2, 2026 |
| [held-strike-shape-checkpoint.md](held-strike-shape-checkpoint.md) | Native point surfaces and fixed-tool reaction — October 2, 2026 |
| [held-strike-target-checkpoint.md](held-strike-target-checkpoint.md) | Native fixed-source / continuous CPU target — October 2, 2026 |
| [held-strike-wrench-checkpoint.md](held-strike-wrench-checkpoint.md) | Force, wrist torque and named source accounts — October 2, 2026 |
| [impact-diagnostics-checkpoint.md](impact-diagnostics-checkpoint.md) | Live world impact diagnostics — October 8, 2026 |
| [impact-inspector-checkpoint.md](impact-inspector-checkpoint.md) | Measured impact-load inspection |
| [implicit-fracture-checkpoint.md](implicit-fracture-checkpoint.md) | Fracture in the implicit solver |
| [inorganic-game-policy-checkpoint.md](inorganic-game-policy-checkpoint.md) | Playable inorganic material policy — October 5, 2026 |
| [inorganic-generated-world-checkpoint.md](inorganic-generated-world-checkpoint.md) | Inorganic generated opening — October 5, 2026 |
| [inorganic-player-catalog-checkpoint.md](inorganic-player-catalog-checkpoint.md) | Inorganic player catalog and paid tool checkpoint |
| [interaction-history-checkpoint.md](interaction-history-checkpoint.md) | Retained interaction history: rewrite checkpoint |
| [inventory-rendering-checkpoint.md](inventory-rendering-checkpoint.md) | Stable world geometry and compact Inventory |
| [lattice-plasticity-checkpoint.md](lattice-plasticity-checkpoint.md) | Plastic flow in the explicit lattice |
| [lattice-self-contact-checkpoint.md](lattice-self-contact-checkpoint.md) | Node-to-node contact in the explicit lattice phase |
| [live-contact-region-checkpoint.md](live-contact-region-checkpoint.md) | Live material contact regions — October 6, 2026 |
| [live-tool-skills-checkpoint.md](live-tool-skills-checkpoint.md) | Live tool skill progress — October 1, 2026 |
| [local-cell-tools-checkpoint.md](local-cell-tools-checkpoint.md) | Recipe identity and thin metal tools — October 6, 2026 |
| [manifold-law-admission-checkpoint.md](manifold-law-admission-checkpoint.md) | Manifold law admission — October 7, 2026 |
| [material-branch-checkpoint.md](material-branch-checkpoint.md) | Conditional native material branches |
| [material-build-energy-checkpoint.md](material-build-energy-checkpoint.md) | Exact energy receipts and material-to-build acceptance — October 2, 2026 |
| [material-build-storage-checkpoint.md](material-build-storage-checkpoint.md) | Material-to-build storage checkpoint — October 2, 2026 |
| [material-input-delivery-checkpoint.md](material-input-delivery-checkpoint.md) | Personal material delivery to machine inputs — October 2, 2026 |
| [material-lab-live-checkpoint.md](material-lab-live-checkpoint.md) | Material lab: bounded fresh experiments |
| [material-lab-ui-checkpoint.md](material-lab-ui-checkpoint.md) | First replacement UI stage: material response lab |
| [material-preview-checkpoint.md](material-preview-checkpoint.md) | Material collection previews — October 1, 2026 |
| [material-stage-checkpoint.md](material-stage-checkpoint.md) | Accepted-state damage and active-stage accounting |
| [material-surface-contact-checkpoint.md](material-surface-contact-checkpoint.md) | Material surface transfer checkpoint — October 6, 2026 |
| [material-target-readiness-checkpoint.md](material-target-readiness-checkpoint.md) | Material target and tool readiness — October 3, 2026 |
| [mechanisms-checkpoint.md](mechanisms-checkpoint.md) | Articulated motion and exact equilibrium reference |
| [midpoint-contact-friction-checkpoint.md](midpoint-contact-friction-checkpoint.md) | Matching contact and friction to centered motion |
| [mixed-tool-draft-checkpoint.md](mixed-tool-draft-checkpoint.md) | Mixed-tool draft preservation — October 1, 2026 |
| [mixed-tool-native-checkpoint.md](mixed-tool-native-checkpoint.md) | Fixed head and handle checkpoint — October 1, 2026 |
| [mobile-digging-checkpoint.md](mobile-digging-checkpoint.md) | Phone digging and opened pits — October 5, 2026 |
| [mobile-hud-checkpoint.md](mobile-hud-checkpoint.md) | Mobile controls and deliberate panels — October 6, 2026 |
| [mobile-lab-checkpoint.md](mobile-lab-checkpoint.md) | Phone-visible physics lab |
| [native-execution-checkpoint.md](native-execution-checkpoint.md) | Native execution comparison — October 8, 2026 |
| [native-face-contact-checkpoint.md](native-face-contact-checkpoint.md) | Native face contact checkpoint — October 7, 2026 |
| [native-ground-matter-checkpoint.md](native-ground-matter-checkpoint.md) | Native ground matter checkpoint |
| [native-mode-preparation-checkpoint.md](native-mode-preparation-checkpoint.md) | Native vibration representation preparation |
| [native-pickup-reach-checkpoint.md](native-pickup-reach-checkpoint.md) | Native player pickup reach — October 6, 2026 |
| [native-pit-clearance-checkpoint.md](native-pit-clearance-checkpoint.md) | Tool width and narrow pit clearance |
| [native-player-foundation-checkpoint.md](native-player-foundation-checkpoint.md) | Native actor body foundation — October 3, 2026 |
| [native-small-rotation-checkpoint.md](native-small-rotation-checkpoint.md) | Native small rotations — October 7, 2026 |
| [native-stage-performance-checkpoint.md](native-stage-performance-checkpoint.md) | Native execution stages and exact snapshot storage |
| [native-tool-entry-checkpoint.md](native-tool-entry-checkpoint.md) | Whole-tool entry observation: experimental rewrite checkpoint |
| [native-walk-checkpoint.md](native-walk-checkpoint.md) | Native bodies that walk and swim — October 4, 2026 |
| [navigation-water-checkpoint.md](navigation-water-checkpoint.md) | Walking, water and cursor controls — October 1, 2026 |
| [network-at-rest-stability-checkpoint.md](network-at-rest-stability-checkpoint.md) | Network lane at-rest stability checkpoint |
| [network-runtime-checkpoint.md](network-runtime-checkpoint.md) | Local material runtime v2 |
| [normal-contact-delivery-checkpoint.md](normal-contact-delivery-checkpoint.md) | Normal contact experiment and interrupted native delivery |
| [normal-contact-energy-checkpoint.md](normal-contact-energy-checkpoint.md) | Normal constraint reactions and impact energy |
| [object-registry-checkpoint.md](object-registry-checkpoint.md) | Object registry and a useful high-drop control |
| [object-strike-joints-checkpoint.md](object-strike-joints-checkpoint.md) | Object strikes and native connections — October 2, 2026 |
| [occupied-cell-contact-checkpoint.md](occupied-cell-contact-checkpoint.md) | Occupied cuboid contact: experimental rewrite checkpoint |
| [opening-human-supplies-checkpoint.md](opening-human-supplies-checkpoint.md) | Ordinary opening and simpler supplies — October 3, 2026 |
| [opening-progression-simplification-checkpoint.md](opening-progression-simplification-checkpoint.md) | Opening progression and independent glass learning |
| [opening-readability-checkpoint.md](opening-readability-checkpoint.md) | Opening, readability and recipe audit — October 3, 2026 |
| [opening-tool-checkpoint.md](opening-tool-checkpoint.md) | Useful first tool — October 3, 2026 |
| [paid-mixed-tool-checkpoint.md](paid-mixed-tool-checkpoint.md) | Paid mixed-material Make — October 2, 2026 |
| [pair-impulse-checkpoint.md](pair-impulse-checkpoint.md) | Audited impulses between live rigid bodies |
| [parallel-physics-checkpoint.md](parallel-physics-checkpoint.md) | First resumed parallel physics checkpoint |
| [patch-adaptive-checkpoint.md](patch-adaptive-checkpoint.md) | Adaptive distributed patch advances |
| [patch-refinement-checkpoint.md](patch-refinement-checkpoint.md) | Integrated patch refinement: convergence remains open |
| [persistent-fields-and-lab-controls-checkpoint.md](persistent-fields-and-lab-controls-checkpoint.md) | Persistent fields, continuing water and controls beside 3D |
| [physical-ground-gameplay-checkpoint.md](physical-ground-gameplay-checkpoint.md) | Physical ground and raw tool flow — October 5, 2026 |
| [physics-families-integration-checkpoint.md](physics-families-integration-checkpoint.md) | Physics families: parallel references and spatial inspection |
| [physx-gpu-checkpoint.md](physx-gpu-checkpoint.md) | PhysX GPU contact comparison — October 8, 2026 |
| [plate-admission-checkpoint.md](plate-admission-checkpoint.md) | Thin-plate request admission and playback checkpoint |
| [platform-playback-checkpoint.md](platform-playback-checkpoint.md) | Normal-speed platform playback and scratch-buffer checkpoint |
| [platform-sdk-checkpoint.md](platform-sdk-checkpoint.md) | Platform SDK and example laboratory checkpoint |
| [player-learning-checkpoint.md](player-learning-checkpoint.md) | Personal machine learning checkpoint — September 30, 2026 |
| [player-persistence-checkpoint.md](player-persistence-checkpoint.md) | Player persistence checkpoint — September 30, 2026 |
| [playground-admission-and-cost-checkpoint.md](playground-admission-and-cost-checkpoint.md) | Playground admission and cost checkpoint |
| [playground-foundation-checkpoint.md](playground-foundation-checkpoint.md) | Chat playground, permanent material state and compact history |
| [precision-conversion-checkpoint.md](precision-conversion-checkpoint.md) | Explicit 32-to-64-bit position conversion |
| [precision-identity-checkpoint.md](precision-identity-checkpoint.md) | Saved runtime position precision |
| [private-ground-checkpoint.md](private-ground-checkpoint.md) | Private carrying accounts — October 1, 2026 |
| [processing-guidance-checkpoint.md](processing-guidance-checkpoint.md) | Processing guidance and live recipe evidence |
| [quick-tools-checkpoint.md](quick-tools-checkpoint.md) | Fast shared tool handling — October 1, 2026 |
| [raw-crafting-readiness-checkpoint.md](raw-crafting-readiness-checkpoint.md) | Gathered constituent input and paid tool forming — October 5, 2026 |
| [raw-storage-inventory-checkpoint.md](raw-storage-inventory-checkpoint.md) | Inventory raw storage and unassigned recovery — October 2, 2026 |
| [reachable-ground-guidance-checkpoint.md](reachable-ground-guidance-checkpoint.md) | Reachable gathering guidance — October 3, 2026 |
| [realtime-envelope-checkpoint.md](realtime-envelope-checkpoint.md) | Realtime envelope checkpoint |
| [realtime-pipeline-checkpoint.md](realtime-pipeline-checkpoint.md) | Near realtime pipeline — October 8, 2026 |
| [realtime-solver-checkpoint.md](realtime-solver-checkpoint.md) | Realtime pipeline: observable delivery and finite-rotation experiment |
| [recipe-supply-checkpoint.md](recipe-supply-checkpoint.md) | Recipe supply checkpoint — October 1, 2026 |
| [rectangular-mount-reuse-checkpoint.md](rectangular-mount-reuse-checkpoint.md) | Rectangular mount damage and paid reuse — October 2, 2026 |
| [refracture-after-handoff-checkpoint.md](refracture-after-handoff-checkpoint.md) | Breaking a piece that has already broken |
| [remembered-design-checkpoint.md](remembered-design-checkpoint.md) | Remembered starter designs |
| [requirements-checkpoint.md](requirements-checkpoint.md) | Collected inventory and creation requirements |
| [resident-observation-checkpoint.md](resident-observation-checkpoint.md) | Resident GPU observations, October 9 |
| [reversible-trial-checkpoint.md](reversible-trial-checkpoint.md) | Reversible runtime contact trials |
| [revision-checkpoint.md](revision-checkpoint.md) | Selected-object rebuild and reclamation checkpoint |
| [rigid-attachment-checkpoint.md](rigid-attachment-checkpoint.md) | Rigid attachment impulse checkpoint |
| [rigid-component-checkpoint.md](rigid-component-checkpoint.md) | Rigid component transfer and initial free flight |
| [rigid-contact-restitution-checkpoint.md](rigid-contact-restitution-checkpoint.md) | Rigid contact restitution checkpoint |
| [rigid-grain-world-checkpoint.md](rigid-grain-world-checkpoint.md) | Rigid grain test world checkpoint — October 7, 2026 |
| [rolling-strength-checkpoint.md](rolling-strength-checkpoint.md) | Rolling strength and computed replay checkpoint |
| [rover-close-arrival-checkpoint.md](rover-close-arrival-checkpoint.md) | Rover close arrival and visible recovery feedback |
| [rover-recovery-brake-checkpoint.md](rover-recovery-brake-checkpoint.md) | Retained rover brakes after recovery and power cycles |
| [rover-stuck-recognition-checkpoint.md](rover-stuck-recognition-checkpoint.md) | Rover recovery recognition |
| [rules-engine-foundation-checkpoint.md](rules-engine-foundation-checkpoint.md) | General rules engine: first implementation checkpoint |
| [runtime-assembly-checkpoint.md](runtime-assembly-checkpoint.md) | Declared assemblies tested in a temporary Jolt world |
| [runtime-carry-checkpoint.md](runtime-carry-checkpoint.md) | Native actor-relative carry: experimental rewrite checkpoint |
| [runtime-cohesive-checkpoint.md](runtime-cohesive-checkpoint.md) | Runtime cohesive motion: position precision gate |
| [runtime-pickup-checkpoint.md](runtime-pickup-checkpoint.md) | Native admission and confirmed Rust pickup |
| [runtime-rewrite-checkpoint.md](runtime-rewrite-checkpoint.md) | Runtime rewrite: first implementation checkpoint |
| [runtime-tool-admission-checkpoint.md](runtime-tool-admission-checkpoint.md) | Native tool-target admission: experimental rewrite checkpoint |
| [runtime-tool-use-checkpoint.md](runtime-tool-use-checkpoint.md) | Native tool use: experimental controller checkpoint |
| [runtime-tool-use-protocol-checkpoint.md](runtime-tool-use-protocol-checkpoint.md) | Rust tool use commands and retained native results |
| [runtime-worker-checkpoint.md](runtime-worker-checkpoint.md) | Rust world worker: native-backed experimental checkpoint |
| [rupture-cascade-checkpoint.md](rupture-cascade-checkpoint.md) | Local fracture propagation and surviving fragments |
| [sand-glass-build-checkpoint.md](sand-glass-build-checkpoint.md) | Gathered sand to glass and a usable lamp — October 2, 2026 |
| [screen-consolidation-checkpoint.md](screen-consolidation-checkpoint.md) | Visual screen consolidation — October 5, 2026 |
| [selected-project-guidance-checkpoint.md](selected-project-guidance-checkpoint.md) | Selected projects and design-chat guidance |
| [session-recovery-checkpoint.md](session-recovery-checkpoint.md) | Lab session recovery — October 9, 2026 |
| [shape-checkpoint.md](shape-checkpoint.md) | Oriented box creator checkpoint |
| [shared-drop-world-checkpoint.md](shared-drop-world-checkpoint.md) | Shared native drop world — October 8, 2026 |
| [shared-guidance-checkpoint.md](shared-guidance-checkpoint.md) | Shared player guidance and paid build readiness |
| [sharp-excavation-checkpoint.md](sharp-excavation-checkpoint.md) | Smooth hills with sharp excavation — October 3, 2026 |
| [sheet-feedback-checkpoint.md](sheet-feedback-checkpoint.md) | Sheet selection and damage visibility — October 8, 2026 |
| [sheet-impact-checkpoint.md](sheet-impact-checkpoint.md) | Thin-sheet impact checkpoint — October 8, 2026 |
| [shoreline-channel-checkpoint.md](shoreline-channel-checkpoint.md) | Shoreline drawing and cube channels — October 4, 2026 |
| [skills-guidance-checkpoint.md](skills-guidance-checkpoint.md) | Skills guidance checkpoint — October 1, 2026 |
| [solar-bank-checkpoint.md](solar-bank-checkpoint.md) | Automatic solar banking checkpoint — October 2, 2026 |
| [solid-boundary-contact-checkpoint.md](solid-boundary-contact-checkpoint.md) | Solid patch boundaries and finite tool contact |
| [solid-matter-reference-checkpoint.md](solid-matter-reference-checkpoint.md) | Constituent solid reference — October 5, 2026 |
| [solid-representation-checkpoint.md](solid-representation-checkpoint.md) | Occupied ball compiler and conservative transfer reference |
| [starter-assembly-review-checkpoint.md](starter-assembly-review-checkpoint.md) | First-person assembly evidence review |
| [starter-assembly-stock-checkpoint.md](starter-assembly-stock-checkpoint.md) | Assembly requirements from first-person inventory |
| [starter-assembly-table-checkpoint.md](starter-assembly-table-checkpoint.md) | Remembered assemblies at the first-person crafting table |
| [starter-assembly-test-checkpoint.md](starter-assembly-test-checkpoint.md) | Physics tests at the first-person assembly table |
| [starter-checkpoint.md](starter-checkpoint.md) | Willow Clearing: first-person starter game |
| [starter-designer-checkpoint.md](starter-designer-checkpoint.md) | Starter crafting designer checkpoint |
| [starter-transactions-checkpoint.md](starter-transactions-checkpoint.md) | Starter saved-action checkpoint |
| [tension-contact-checkpoint.md](tension-contact-checkpoint.md) | Tensile interfaces with retained Jolt surface contact |
| [tension-patch-checkpoint.md](tension-patch-checkpoint.md) | Atomic tensile patch impulses |
| [test-hub-checkpoint.md](test-hub-checkpoint.md) | Browser Test Hub — October 6, 2026 |
| [test-website-checkpoint.md](test-website-checkpoint.md) | Test website delivery — October 8, 2026 |
| [tetrahedron-contact-checkpoint.md](tetrahedron-contact-checkpoint.md) | Tetrahedron contact checkpoint |
| [thermal-fields-checkpoint.md](thermal-fields-checkpoint.md) | Native thermal and closed reaction fields |
| [tool-authoring-contract-checkpoint.md](tool-authoring-contract-checkpoint.md) | General tool authoring — October 6, 2026 |
| [tool-autosave-checkpoint.md](tool-autosave-checkpoint.md) | Quiet tool autosave retries — October 1, 2026 |
| [tool-family-checkpoint.md](tool-family-checkpoint.md) | Ground tool families — October 6, 2026 |
| [tool-grip-recovery-checkpoint.md](tool-grip-recovery-checkpoint.md) | Tool grip recovery — October 5, 2026 |
| [tool-hud-checkpoint.md](tool-hud-checkpoint.md) | Generic tool HUD and deliberate target feedback — October 3, 2026 |
| [touch-pickup-gesture-checkpoint.md](touch-pickup-gesture-checkpoint.md) | Touch pickup gesture — October 6, 2026 |
| [trajectory-checkpoint.md](trajectory-checkpoint.md) | Full-state timestep comparison across glass, oak and iron |
| [transfer-accounting-checkpoint.md](transfer-accounting-checkpoint.md) | Finite-cell spin and representation-transfer checkpoint |
| [ui-chat-verification-checkpoint.md](ui-chat-verification-checkpoint.md) | Lab, shared chat and guidance verification |
| [variable-contact-step-checkpoint.md](variable-contact-step-checkpoint.md) | Reversible variable contact steps — October 7, 2026 |
| [voice-shared-chat-checkpoint.md](voice-shared-chat-checkpoint.md) | Voice through the selected chat |
| [voxel-contact-audit-checkpoint.md](voxel-contact-audit-checkpoint.md) | Voxel contact impulse audit — October 8, 2026 |
| [voxel-impact-world-checkpoint.md](voxel-impact-world-checkpoint.md) | Voxel impact world checkpoint — October 8, 2026 |
| [voxel-motion-cost-checkpoint.md](voxel-motion-cost-checkpoint.md) | Global stepping cost and coherent body observations |
| [voxel-spring-loss-checkpoint.md](voxel-spring-loss-checkpoint.md) | Voxel spring loss and timing audit — October 8, 2026 |
| [voxel-unloading-checkpoint.md](voxel-unloading-checkpoint.md) | Native unloading and retained metal deformation |
| [water-wheel-comparison-checkpoint.md](water-wheel-comparison-checkpoint.md) | Water-wheel and before/after comparisons — October 8, 2026 |
| [windows-integration-checkpoint.md](windows-integration-checkpoint.md) | Windows contact integration checkpoint |
| [workshop-acceptance-checkpoint.md](workshop-acceptance-checkpoint.md) | Explicit Workshop load-test limits |
| [workshop-consistency-checkpoint.md](workshop-consistency-checkpoint.md) | Workshop consistency checkpoint — September 17, 2026 Pacific |
| [workshop-inspection-merge-checkpoint.md](workshop-inspection-merge-checkpoint.md) | Workshop inspection integration (PR #16) |
| [workshop-install-checkpoint.md](workshop-install-checkpoint.md) | Workshop prototype installation checkpoint |
| [workshop-precise-live-checkpoint.md](workshop-precise-live-checkpoint.md) | Precise rigid Workshop to live-world checkpoint |
| [workshop-thin-parts-checkpoint.md](workshop-thin-parts-checkpoint.md) | Thin parts: buildability and explicit rigid motion |
| [workshop-visible-tests-checkpoint.md](workshop-visible-tests-checkpoint.md) | Workshop tests that visibly simulate |
| [workshop-workspace-checkpoint.md](workshop-workspace-checkpoint.md) | Visible Workshop workspace and component inspection |
| [world-chat-checkpoint.md](world-chat-checkpoint.md) | World chat — October 2, 2026 |
| [world-consequences-checkpoint.md](world-consequences-checkpoint.md) | Consequences: what breaks, what gives, what is carried, and the person in the water |
| [world-foundation-checkpoint.md](world-foundation-checkpoint.md) | Sparse-world and thermal foundation |
| [world-pickup-chat-checkpoint.md](world-pickup-chat-checkpoint.md) | Whole-tool pickup and deliberate World chat — October 6, 2026 |
