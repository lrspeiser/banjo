# Native ground matter checkpoint

## Scope and revision

Implemented and measured on Windows 11, MSVC 17.14 Release, CPU precise floating-point profile `banjo-cpu-precise-v1`, native Jolt contact, 2026-10-05. Development base: main `249f350daa959c842c795f5ffe4be1ce10c9205c`; this note describes the shared working-tree checkpoint before the integrating owner records its published revision. It does not describe an already deployed owner world.

The former hit-count cube promotions are removed. There are two admitted tool paths:

- Ordinary dry column-soil strokes retain `ground-work-v1` penetration/passive-earth resistance and measured solver contact work. Their actual terrain edits detach as connected native rigid components (`ground-work-v1-rigid-detachment`). A small pry never becomes a free whole cube.
- Explicit `work-cut-v2` spends a bounded, named external work budget against the actual selected material band. The host identifies its finite banked-energy assist source. Internal measured rock contact feeds the same accumulated work law without external retry-receipt allocation.

Both retain precise source matter and permit native motion, native contact, collection, saving and reopening. This is an admitted work-cut reduction. Constituent fracture, granular soil mechanics, grain-dependent wood fracture, rock constitutive fracture, and a closed full-system energy audit remain unsupported. [The SolidMatterPatch CPU reference](solid-matter-reference-checkpoint.md) is retained separately; its stiff substeps are not silently replaced by the gameplay timestep or claimed as this law.

## Source matter, work, and native bodies

`src/terrain/GroundExcavation.cpp` belongs to `banjo_environment`; `tests/ground_excavation_tests.cpp` belongs to the registered `banjo_ground_excavation_tests` target. Tool integration is in `ToolTerrain`, `LiveWorld`, and the native runner.

Exact clipped 5 cm cells preserve identity, source center, dimensions, material/run kind, density, volume and mass. Damage and temperature are null because this model does not resolve them. Source identities contain region, column, band, release generation and local sample coordinates; reuse of a geometric location does not reuse a released identity. Sparse per-column matter revisions invalidate accumulated work when that source is actually edited and preserve it when a neighbor changes.

The cells are provenance samples, not prebuilt shards. Adjacent removed slabs form one connected rigid compound. Disconnected components are found from actual removed geometry. Shapes use merged actual material slabs; mass, center of mass and inertia follow density and geometry. Initial linear and angular velocities are zero. Gravity and native contact determine subsequent motion. No fragment kick, cosmetic shard, prescribed settling animation, or continued velocity assignment is used. A chunk can remain supported in its original hole until its actual support is removed or it is collected.

Rock density is 2400 kg/m³. Its contact catalog identity is the existing **concrete surrogate**; fresh rock extraction still uses the declared 100 MPa ground hardness and unchanged 30 MJ/m³ specific work. Soil/sand density is 1600 kg/m³. Their released bodies use an explicitly reduced bulk rigid contact material (50 MPa contact modulus, static/dynamic friction 0.7/0.6, contact damping ratio 0.6). This is not a granular constitutive model.

Funded native operation:

```json
{"op":"strike-cell","at_m":[0,0.625,0],"work_j":1000,"work_source":"bank:actor:unique-request"}
```

The `ground_cut` receipt reports `requested_work_j`, `consumed_work_j` and alias `work_consumed_j`, source, supported/kind/why, required work, actual removed volumes, mass and body ID. Consumed work cannot exceed its submitted budget. Zero budget/source or failed admission gives zero consumption and no extraction. Partial work persists without removing matter. The same funded source and identical request returns its saved receipt; a different request with that source is refused. Funding is a host escrow boundary, not a claim of calibrated human muscular energy.

Hard material admission uses numeric point hardness and actual native point/fixed-handle connection. It checks the material beds crossed, reach, available material, compatible dry column geometry and source band. Oak's 35 MPa point cannot cut the 100 MPa fresh-rock target even with external funding. There is currently no standalone read-only `strike-cell-check` quote operation; host readiness must treat unsupported regimes as warnings and use authoritative native refusals. Material names alone are insufficient readiness evidence.

`ground-debris` returns full source cells and actual native poses. Ordinary wire states use compact cached body/slab metadata, source cell count and actual native pose. `collect-ground-debris` measures at most 3 m reach and native line of sight, ignoring only the collector's avatar and held fixed assembly. A successful packet returns those exact cells and the actual collection-time transform, removes its native body once and credits the selected carrier once. Storage is an explicit abstract boundary. The host must pair native withdrawal with its durable private inventory receipt.

## Measured experiments

### Funded same-geometry comparisons

All cases: dry flat 20×20 column terrain, 25 cm terrain cells, 5 cm matter samples, selected band volume 0.015625 m³, declared point geometry width/thickness 4 cm, 30° included angle, 15 cm point length, held 8×24×8 cm material body, 1 MJ explicit budget. The selected interior band retains its actual roof. Each successful release has one body and 125 exact cells. Timing is one local native cut call, including source-cell assembly and terrain collision rebuild; it is not browser latency or a sustained frame-rate benchmark.

| Point material | Ground | Removed mass | Consumed work | Cut wall time |
|---|---|---:|---:|---:|
| Glass | Rock | 37.5 kg | 468750 J | 1.869 ms |
| Glass | Soil | 25 kg | 574.733 J | 1.459 ms |
| Glass | Sand | 25 kg | 372.182 J | 2.669 ms |
| Oak | Rock | 0 kg (hardness refusal) | 0 J | unsupported |
| Oak | Soil | 25 kg | 574.733 J | 1.793 ms |
| Oak | Sand | 25 kg | 372.182 J | 1.756 ms |
| Iron | Rock | 37.5 kg | 468750 J | 1.524 ms |
| Iron | Soil | 25 kg | 574.733 J | 1.598 ms |
| Iron | Sand | 25 kg | 372.182 J | 1.581 ms |

Ground work sets funded cost; identical external supply therefore does not make different admitted point materials consume different energy. Their native tool masses/contact inputs differ: glass 2500 kg/m³, 70 GPa, 5.5 GPa hardness; oak 700 kg/m³, 12 GPa, 35 MPa hardness; iron 7870 kg/m³, 211 GPa, 1.5 GPa hardness. Catalog parameters are not proof that this extraction path implements their fracture/yield/grain laws.

Terrain volume residual printed 0 m³ in all admitted comparisons. Sample volume sum agrees to 1e-12 m³ and sample mass sum to 1e-9 kg; roof/neighbor/floor tests remain. These tests close geometry/mass bookkeeping, not momentum or full energy transfers. Work is accounted at its supplied boundary; no invented fracture heat or fragment kinetic-energy allocation closes the missing full-system ledger.

### Ordinary measured soil stroke and contact comparisons

With assist absent, the oak pick fixture swings, pries and withdraws against dry column soil. Native timestep is 1/240 s, tool lattice resolution 4 cm and terrain resolution 25 cm. Actual result: **0.00590749248424 m³ (9.452 kg), 100 clipped source cells, one connected native body, 26.3210801 J measured ground work, 2.77083333 s native elapsed time including settle steps**. Repeating with a neighboring ground aim gives the same result; aiming does not enlarge the wedge. Collection returns exactly those source cells. Terrain and collection volume residuals are 0 m³. Local stroke wall time, excluding fixture setup and collection, was **77.2773 ms**, and **71.8245 ms** for the neighboring-aim repeat. This includes native swing/pry/withdraw/settle calls; it is not host round-trip or browser latency.

Existing same-drop material regressions at 4 cm / 1/240 s retain differences without presetting outcomes:

| Material | Tool mass | Penetration | Measured ground work | Drop energy residual | Damping bound |
|---|---:|---:|---:|---:|---:|
| Glass | 1.600000 kg | 0.069447 m | 4.998111 J | -0.004325528 J | 0.008098328 J |
| Oak | 0.448000 kg | 0.033302 m | 1.241271 J | -0.000610494 J | 0.001395404 J |
| Iron | 5.036800 kg | 0.163013 m | 20.342134 J | -0.027121319 J | 0.058831232 J |

These drop residuals are bounded contact checks, not a full dig/collect ledger. Fixed mixed-head/oak-handle contact regressions also retain unclosed work-minus-mechanical-minus-ground values: glass -0.444883845 J, oak -0.289081497 J, iron -0.0448162138 J. Those residuals are explicitly unclosed and do not substantiate complete conservation.

In a native released-component experiment, the top piece remains supported until the actual lower piece is cut and collected. At 1/240 s, the upper piece falls 0.242868 m, then its vertical velocity settles to 0 m/s after the additional native steps. The collection packet retains its settled transform. The cut has no initial velocity.

## Persistence, bounds, and compatibility

Ground save schema v6 retains released bodies, all exact cells, current poses/velocities, cumulative source-work counter, target paid progress, sparse matter revisions and external request receipts. Whole live-world reopen is tested before collection; partial funded work survives reopening, and corrupt sample mass is refused. Legacy v1–v5 quantities retain their bulk ledger history without fabricating past constituent identities or fragment positions. Region state retains source revisions and the region regression verifies native pieces before collection.

Limits are explicit: 256 live components, 2000 provenance samples per component, 32 involved columns in an ordinary detachment, 1 MJ per external request, 4096 external funded request receipts, finite named sources, 5 cm-compatible column sizes up to 50 cm. External receipts require future durable archival when full; they are never silently dropped. Internal accepted contact work avoids this request cache and coalesces the same actual actuator identity in paid progress. A 4100-contact regression adds exactly 41 J to one source/target with no external receipts. These limits bound individual work and memory, not prove whole-world performance at all caps.

Wet excavation/debris-water momentum coupling, mixed loose-soil/sand sources, unsupported column resolutions, cross-region ordinary detachment, and disconnected funded bands are refused. The wet-channel fixture now requires authored entry plus funded dry cuts; it validates water quantity/roof behavior and does not claim a wet work-cut law. Static retained terrain roofs remain anchored geometry; stress-based support collapse is absent. Smooth terrain, authored dig/deposit and machine editing still use their existing bulk pathways; this checkpoint does not turn all terrain APIs into constitutive matter simulation.

A fast deep fresh-rock shaft is not validated: one 25 cm cube already costs 468750 J under the retained law. A few hundred joules in a bank cannot fund that cube. Changing display names, applying a free repeated strike, or lowering hardness to meet a timing goal would violate this checkpoint's work boundary.

## Verification commands

```powershell
cmake --build build/agent-column-terrain --config Release --target banjo_ground_excavation_tests banjo_ground_work_tests banjo_streamed_regions_tests banjo_terrain_tests banjo_live_world_run banjo_platform_cli banjo_c --parallel 4
ctest --test-dir build/agent-column-terrain -C Release --output-on-failure -R "^banjo_(ground_excavation|ground_work|streamed_regions|terrain)_tests$"
python scripts/check-source-registration.py
git diff --check
```

The four native suites passed after the final collection-transform relink and comment cleanup (11.24 s). Source guard: 304/304 registered, zero deliberately unbuilt. Checkpoint relative links and changed native scope whitespace checks pass. Output bundle: `build/pickaxe-preview/Release/banjo_live_world_run.exe`, `banjo_platform_cli.exe`, `banjo.dll`. Browser/host escrow, save/collect restart and raw fabrication evidence belong to the integrating agents' checkpoints. No macOS, Linux or cross-GPU claims follow from these Windows checks.

Final bundle SHA256: runner `44F74C1729E8C2BB01B9448A64C76C314E00500E3129CB821F1582D84D404026`; CLI `5A49E7F5D771756573ACD034BC0F6CB61A06E7F9312FA02DA0A6B8D1FB8C8817`; C API DLL `31B03BFE3FB28F0D2BB81659152534A916E127F75456F77D4952786E6EC3EC8C`.

### Resolved broader hand regression fixture

The integrating agent's broader gate found one hand rollback fixture failure: zero actual hand work. A fresh isolated build of the **unchanged** base `249f350daa959c842c795f5ffe4be1ce10c9205c` reproduced the identical 1/9 failure (`build/main249-check`, 0.33 s). Main's existing 1.8 m native shoulder reach had made its old avatar starts more than 2.23 m from their grips, so the authoritative reach gate correctly released the tools before the test could exercise work rollback.

Only fixture avatar starts were corrected to (-1,1,2)/(1,1,2), keeping each complete stroke within reach and preserving all rollback, retry, saved-state and nonzero-work assertions/tolerances. The current `banjo_hand_stroke_tests` now passes all nine tests (CTest 0.51 s). Actual retained glass/oak/iron work is 0.310001/0.0868004/0.674483 J for grip, 0.147805/0.082133/0.0794768 J for haul, and 0.384392/0.161199/0.694394 J for fixed tools. These agree with the earlier passing cached fixture. No hand law, native reach limit or production behavior was changed to obtain the pass.

### Remaining paid-target strike fixture gate

The broader host regression found a timing-sensitive preexisting expectation in `NativeRemake.test_paid_made_target_strike_separates_and_paid_replacement_retains_damage`. On the final immutable native bundle, the original ordinary one-strike fixture passed twice and returned genuine contact-only twice across four isolated runs. An exact `249f350d` native baseline was also built. With the same deterministic accepted input schedule, the baseline and final bundle produced identical physical values: 26.31679 J hand work, first contact 2.078096866607666 m/s and 0.02931336573609991 J, time 9.999999999999753 to 12.916666666666254 s, and contact-only. The one-strike mount-failure expectation depended on asynchronous host polling phase; it is not a qualified invariant or an excavation regression.

A bounded repeated-action diagnostic reached actual 2908.87048 N equivalent normal load against the unchanged 2250 N mount and separated it. However, the released thin shaft subsequently hit the floor at 26.240623 m/s and caused a native fracture offer/refused step. That diagnostic did not pass the complete paid-damage/reuse/reopen flow, and is not retained as acceptance evidence. Its exploratory deterministic-clock/repeated-action test edits were restored; the original test and every assertion remain. No strength, capacity, damping, impulse, fragment velocity or tolerance was changed to manufacture a pass. This host fixture remains an explicit unresolved baseline test gate. A robust declared experiment with a justified load margin, deterministic inputs and bounded unsupported-fracture handling is still required before claiming dependable one-action paid-target separation.

Next physical steps: extract a mutation-free native quote/admission plan, close contact/detachment/environment energy and reaction accounting, calibrate work-cut validity, add wet/granular laws and resolved constituent topology failure, and measure sustained performance at admitted caps. [Ground audit](ground-matter-audit.md) and [mechanics scorecard](mechanics-scorecard.md) retain the broader platform boundaries.
