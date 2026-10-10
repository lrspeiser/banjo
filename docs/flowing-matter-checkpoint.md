# Flowing matter: bounded hydrostatic reference

October 10, 2026. **Implemented CPU reference and editable 3D page; general 3D fluid/solid coupling remains unimplemented.** Parent checkpoint records integration revision and ordinary browser evidence. This branch of work adds family 6 without pretending the eight families are fully coupled.

## What the user sees

At `/flow`, set initial left/right depths or paint arbitrary initial water heights, then calculate. Replay or scrub accepted states. Displayed water-column height equals the calculated depth; horizontal speed or hydrostatic bed pressure controls the color. The renderer never advances the fluid or substitutes prescribed waves. It replays the native solver's output in physical time. The fixed basin walls do not deform.

The law accepts arbitrary finite initial `[depth_m, discharge_x_m2_s, discharge_z_m2_s]` per column through `/api/flow-reference`. Initial height is not a precalculated dam outcome: every changed initial state is solved again. Density is a unit-bearing liquid property. A material name cannot select flow; unsupported `material: oak/glass/iron` declarations refuse.

## Equations and ownership

The native [reference](../src/flow/FlowReference.cpp) evolves the flat-bed Saint-Venant equations:

- `∂t h + ∂x qx + ∂z qz = 0`.
- `∂t qx + ∂x(qx²/h + gh²/2) + ∂z(qx qz/h) = 0`.
- `∂t qz + ∂x(qx qz/h) + ∂z(qz²/h + gh²/2) = 0`.

Each face has one Rusanov flux, applied oppositely to neighbors. Reflecting ghost states impose fixed-wall normal boundary conditions; actual boundary momentum flux supplies the external wall impulse and torque account. Static walls perform zero work. Gravity appears in the hydrostatic pressure and column potential energy, rather than a second vertical particle force. Positive depth is maintained by a declared CFL maximum 0.2; negative depth is refused, never clamped or secretly replenished. No physical viscosity or environmental drag is present.

The represented material is one conserved liquid volume, with one persistent instance-derived matter ID. Eulerian column IDs identify control volumes, **not persistent particles**: water crosses between them. Phase is explicitly liquid but no solid-to-liquid transfer is qualified. No mass is silently normalized. Definition hash includes the source identity and grid/density/gravity; instance ID is separate and stays unchanged through continuation. Each response carries SHA256 of the actual loaded native library and physics source. The native [API](../src/flow/FlowCpuApi.cpp) copies results out only after the complete bounded experiment passes. Failure leaves output buffers and accepted input unchanged.

## Persistent continuation and restart

`Reference::State` retains settings, current cells, original mass/P/L/energy reference, accepted time, solver step count, cumulative wall reactions and numerical terms. `Reference::restore` checks finite state, clock/step bounds and all reference balances before admission. This does not reinitialize the original energy or impulse accounts. The new bounded `banjo_flow_continue` API returns actual frames and continuation together; each output remains untouched if any frame fails. Legacy `banjo_flow_run` remains supported and uses the same calculation path.

Python `run(declaration, library=None, checkpoint=None)` emits a versioned, checksummed checkpoint with exact IEEE754 binary64 encoding. Continuing accepts only duration/frame-count overrides; grid, density, gravity and initial reference budgets cannot be edited. Original initial cells and stable instance/matter/control-volume IDs remain. Stale source/binary, changed original budgets or inconsistent counters/owner mapping refuse. Source or loaded library changes require server restart rather than claiming the new disk identity for old executable code. As with the existing laboratory checkpoint format, checksums and balance validation are corruption/consistency checks, not cryptographic proof of a unique earlier physical trajectory.

The 20,000-substep/eight-million-column-update work ceiling applies once to the **current transaction**, across all returned output intervals. Accepted cumulative physical solver counts survive restart and do not create a permanent lifetime execution cap. The law, CFL and every accepted physical update remain unchanged.

[Four continuation tests](../tests/flow_continuation_test.py) compare 61 frames through one second, reopen/continue for another 61 frames, and compare every frame/cell/account bit-for-bit with one 121-frame two-second native run. Original reference and cumulative wall/angular/numerical energy accounts match, with persistent IDs and input checkpoint unchanged. An additional reflected-wave experiment starts with valid 2 m depth and 1 m/s horizontal velocity, reaches 2.4085 m depth, and continues exactly like its one-shot reference. Evolving columns are not incorrectly subjected to the 2 m **initial authoring** limit; restore uses the mass-derived `2 × column count` maximum height and checks original total mass/energy/momentum. Native malformed restore and actual-loop whole-request budget failures leave frame, account and continuation output buffers untouched. These tests do not establish solid-to-flow, enthalpy advection or shared coupled-world ownership.

## Conservation and numerical terms

Accounts retain mass, horizontal momentum, angular momentum about the declared basin coordinate origin, kinetic plus gravitational energy, fixed-wall impulse/torque and residuals. Internal advective face transport can introduce discrete angular change because momentum is represented at cell centers; that term is derived from each internal flux and separately reported. It is not attributed to an external torque. Energy change from first-order Rusanov diffusion is separately reported as **numerical energy change**, never heat, friction or a calibrated material loss. Positive energy creation above `1e-10 × max(1 J, pre-step energy)` refuses. An energy receipt closes by tracking that numerical term; closure alone does not prove physical energy conservation.

The default release loses about 134.32 J out of 753.408 J over two seconds. This appreciable numerical diffusion is a limitation, not a realism claim. The independent spatial refinement check below demonstrates improvement but is not full convergence qualification. Reporting a numerical energy loss does not make a strongly dissipative scheme appropriate for fine waves or coupled machinery.

## Bounds and measured verification

Native settings: at most 4096 columns (`2..128` in each dimension), `dx 0.01..1 m`, density `1..20000 kg/m³`, gravity `0..20 m/s²`, initial depth `0..2 m`, initial and evolving speed at most `20 m/s`. Evolving depth may exceed the initial authoring limit after a pressure wave; continuation checks the retained original mass bound. A request advances at most five seconds, with at most 20,000 cumulative CFL substeps and eight million column-updates for the **whole transaction**, including every output interval. At most 241 render frames and 300,000 column-frames are returned. An exhausted bound refuses rather than changing the law or extrapolating. Actual-loop budget tests run a costly 128×32-column, 0.01 m setup until refusal and verify zero committed time/cell change plus unchanged native output buffers.

Windows MSVC 19.44, Release; Python 3.13.5. Separate build `build/flow-reference-agent`. CMake targets `banjo_flow_cpu` and `banjo_flow_reference_tests` compile both new source files; source registration passed 352/352 at verification. [Native tests](../tests/flow_reference_tests.cpp) pass:

- Still 0.2 m lake remains bit-identical in every depth and discharge for one second. Opposed wall reactions cancel within accumulated floating-point rounding (`1e-10 N·s`).
- Independent first-step wall impulse equals `ρ g h²/2 × face area × dt`, within `1e-12 N·s`.
- A finite release over initially dry bed produces moving water with nonnegative depth. Actual total mass, P and L balances include boundary fluxes and numerical angular transport.
- Asymmetric two-axis flow exercises the angular transport account.
- Matched liquid-density controls `700 / 917 / 1000 / 2500 / 7870 kg/m³` produce identical depth/discharge trajectories and density-scaled physical accounts. These controls do not simulate solid oak/glass/iron laws; those materials remain in the separate solid regression set.
- Ritter analytical dry-bed release: at 0.5 s, depth L2 error decreases from `0.0200582` (`dx=0.2 m`) to `0.0149957` (`dx=0.1 m`). First-order front diffusion remains visible.
- Invalid state and intervals refuse atomically. [Three Python API tests](../tests/flow_reference_api_test.py) pass arbitrary-field authoring, identity changes, no material-name law/fallback, strict bounds and untouched sentinel output on native refusal. [Semantic view tests](../tests/flow_view_test.mjs) verify actual depth/speed/pressure observation mapping, geometry, no future extrapolation, valid DOM controls and family navigation; root separately verifies ordinary browser operation.

Default 48×24 columns, `dx=0.1 m`, left third at `h=0.2 m`, rest dry, 1000 kg/m³, zero velocity:

| Quantity | Measured result |
|---|---:|
| Initial / retained mass | 768 kg |
| Two physical seconds, 121 frames | 240 CFL substeps |
| Native solve + native output writes | 0.00994 wall s |
| Python validation, native solve, receipt/checkpoint construction | 0.0751 wall s |
| Mass residual | −2.61e−12 kg |
| Horizontal momentum residual | 8.64e−12 N·s |
| Angular residual | 3.41e−12 N·m·s |
| Numerical mechanical energy change | −134.32 J |

Single measurements, not a network/browser or complete-world realtime qualification. Serialization, network, client construction and rendering cost must be measured in the integrated website. This small reference is markedly faster than physical time; that says nothing about the slow detailed-sheet impact solver.

Verified local flow DLL SHA256: `515daf26b0d47cc8488c0d4baedb346ca556818941d34f18fca23c8b844b284c`. Physics source SHA256: `5f69616e83e6eb10313e4157eda9e2406f471288d4c29017ac92ab86eac85828`. These identify the independent agent build; the parent must record the actual delivered checkpoint binaries separately.

## Remaining work

This is a **hydrostatic depth-averaged** model. It cannot demonstrate a vertical poured jet, overhang/free 3D surface, droplets, splashes, full incompressible pressure, turbulence, capillarity, viscosity, freezing/melting or calibrated fluid material behavior. Coupling to detailed solid contacts, articulated water wheels and thermal/chemical fields is absent and explicitly refused by this authoring scope. It does not displace the retained [existing shallow-water solver](../src/water/ShallowWater.hpp), which supports uneven bed/region exchange and has its own tests; this small independent reference supplies explicit P/L/E diagnostics on a restricted flat bed.

Next: refine the entropy/accuracy and delivery measurements, qualify depth-average exchanges with articulated boundary work, and separately implement a genuine 3D free-surface solver for the requested pour/wheel test. No stream trajectory or wheel motion may be prescribed to satisfy that gate.
