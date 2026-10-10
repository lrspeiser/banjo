# Persistent fields, continuing water and controls beside 3D

October 9, 2026. Physics implementation published on main `5619cb0991e5170a377287eeb26378966a9dddfe`. Implemented bounded CPU references from main `8cb64e4e980cd133379b4adaafed3026eb370ffa`. This checkpoint does not complete the eight-family platform or strong-impact gate.

## What the user can test

- `/coupled`: enable **Retain heat on moving matter**, select a ball heater in watts, and run **Drop & rebound** beside the scene. **Temperature** shows the actual accepted field on that same moving matter; **Contact forces** shows measured contact points instead. Inspection, save/reopen and diagnostic actions are in **Inspect / save / tests** beside the scene.
- `/flow`: calculate spreading water, then **Continue flow** beside the basin. It advances the same water from its accepted checkpoint, rather than starting the initial field again. The physical clock and wall/numerical accounts remain cumulative. Painting/reset/input mutations are locked during requests. A refused result retains the last accepted view and checkpoint.
- `/mechanisms`: **Calculate & play**, before/play/after, gravity swing, wake and support removal are attached to the 3D panel. The Calculate button still submits the actual settings form.
- `/thermal-fields`: heat, step, stop, setup, ice/reaction tests and save/reopen are beside the cell view. They remain disabled until a native session exists.

The representation, CUDA contact and material-loading workbenches also use the same adjacent action dock. Their numerical laws and existing handlers are unchanged. Thermal-page navigation now closes only its owned session so browsing experiments does not exhaust the eight-session bound.

The [demonstration contract](physics-lab-demonstration-contract.md) now requires this placement for every new physical experiment. Desktop and phone portrait/landscape are acceptance surfaces. Settings may be separate; the action that runs the scene must not be hidden after a long settings form.

## Shared accepted state

`ThermalMatterAdapter` binds finite thermal cells to the actual registry's persistent matter IDs, exact material geometry/density-derived masses and canonical mechanical body IDs. The native ID rebind copies each complete field record without averaging. Internal uint64 comparison tokens never replace persistent string IDs in browser/checkpoint receipts.

The optional CPU field adapter advances after each privately accepted mechanical substep, before publication. Each replay sample carries its own field timestamp and actual endpoint position. Clock, ID or pose mismatches make inspection unavailable rather than fabricating heat from force or color. A complete-request failure restores native bodies, interface history, registry, clock, representation ownership and fields together. Save/reopen preserves the exact accepted continuation, original law/configuration, source and native identity.

The combined energy receipt counts native mechanical energy, stored contact/material energy, dissipative and numerical accounts once; retained thermal energy is separate; explicit heater work is external. In this bounded model the two systems exchange **no** energy with one another. Mechanical mass, stiffness and response are temperature-independent. Conduction uses the original authored face graph. Reactions on moving matter, damage/plastic topology transfers, contact heating, expansion, weakening and solid-to-flow transitions are refused or unimplemented. An initially liquid state cannot be installed as unchanged rigid ice.

Water now has a sealed exact-f64 checkpoint, persistent provenance/control-volume IDs, original budget and cumulative wall/angular/numerical accounts. Continuation uses the same native conservative flux/CFL law and immutable physical declaration. Reflected evolved depth may exceed the initial authoring limit; restore validates it against conserved available volume rather than erroneously applying the initial 2 m limit. This remains depth-averaged horizontal flow, not a 3D jet, wheel or solid-phase transfer.

## Verification

Windows 11, MSVC Release, native DLLs in `build/voxel-contact-audit/Release`; Python/NumPy CPU reference. Source registration: **354/354**. Both new C++ implementation/test files are registered and compiled. Twenty-one scoped CTests pass (fourteen field/native/view/API tests plus six existing registry/CPU world/modes/gateway/parity/session tests and one action-placement suite); this is not a full repository regression run. The final HTTP test exercises actual authenticated workers for all four retained solid materials, exact field save/reopen, and same-water continuation. See [thermal transfer evidence](thermal-fields-checkpoint.md) and [flow continuation evidence](flowing-matter-checkpoint.md) for native and adapter assumptions.

Matched experiment: 0.1 kg ball, 10 m initial gap, gravity 9.81 m/s², host step 1/240 s, contact phase bound 0.0625 rad, partitioned rigid flight, CPU local Jacobian, initial temperature 260 K, 2 W heater, two accepted seconds. Heated/unheated native bodies and edges are exactly equal for every accepted batch; each completes contact and rebound. The heater oracle is `T = 260 + 2*t/(0.1*cp)`.

| Material | Temperature at 2 s, K | Independent combined energy residual, J |
|---|---:|---:|
| Glass | 260.0476190476 | 7.13e-10 |
| Oak | 260.0235294118 | -8.15e-10 |
| Iron | 260.0888888889 | 2.27e-10 |
| Ice | 260.0190476190 | -5.46e-10 |

Different specific heats produce different temperature rises. These cases do not validate temperature-dependent strength, oak grain or continuum plasticity. Paired heated/unheated backend measurements are about 0.56–0.57 wall seconds/material including reopen in the agent run; they exclude HTTP, rendering and constructor cost. No general realtime claim follows. Tests independently calculate the combined account and inject a late post-heat publication failure and unsupported melting; both restore the full interval.

Flow split continuation is bitwise equal to an uninterrupted run, including original momentum/energy accounts. The actual 48×24-column browser test continues 2 to 4 s with 768 kg water and about -3.52e-12 kg mass residual. Native calculation measured about 0.01 wall s per two physical seconds locally; this is not end-to-end mobile delivery qualification.

Ordinary in-app browser checks show actual 3D water, mechanism wake and heat fields with actions beside them. At 390×844 all main action targets are in the viewport; landscape 844×390 also checks their bounds. The moving heated iron ball completes 2 s, rebounds at 8.39 m/s and reads 264.444 K with a 100 W heater. Force glyphs and temperature inspection are mutually exclusive to prevent overlapping quantity labels. Screenshots are local ignored evidence under `build/physics-families-qa/controls-*.jpg`.

## Next gates

1. Close actual strong glass/oak/iron/ice sheet impacts, ball internal deformation and conservative fragment field transport. Do not substitute prerecorded fractures.
2. Reduced execution must use the current native material law. Current mode preparation retains all 54 modes but has 116 uncertain contact sites and central tangents averaging open/closed contact. Native relative gap gradients and correlated bounds are now implemented in the [next checkpoint](correlated-contact-bounds-checkpoint.md); branch/event control, consistent endpoint reconstruction, nonlinear error and full reaction/work audit are still required. The older modal lattice uses another law and cannot be substituted unchanged.
3. Add general articulated-world contacts, conservative phase/flow mapping, enthalpy transport and true 3D pouring/wheel forces.
4. Add calibrated thermal expansion/weakening and reactive moving matter with full species/mass/energy accounts.
5. Measure complete HTTP/browser delivery on hosted phone hardware before qualifying realtime.
