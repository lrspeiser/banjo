# Live material contact regions — October 6, 2026

## Scope and publication

Experimental CPU reference prepared against main `b58da692151edd649e8b829d94a516fd32a76ac7`. Implementation `6e52e6cf8a3106a04794898063541fe83d980ce9` is published on GitHub main; passing boundaries and failing strict gates are distinguished below. [Pinned source/executable hashes and all 36 comparative records](evidence/live-contact-region-2026-10-06.json) cover this checkpoint. It extends [surface traction transfer](material-surface-contact-checkpoint.md), while retaining the original declared-support and centre-point tests. Gameplay terrain is not migrated and neither demo process is replaced.

**Previous-turn classification: progress.** Main gained compiled surface-transfer code, comparative evidence and a verified publication. This turn adds actual live graph selection and exposes a sustained convergence defect; it does not relabel that defect as completed terrain physics.

## Shared implementation

`MaterialContactTopology` builds immutable schedule-order adjacency from canonical bond endpoints. Every selection reads current bond aliveness, actual node positions and mobility. The serial-double Verlet backend owns it; no downloaded/caller-provided topology snapshot is accepted by `applyNativeFixedLocalSurfaceTransfer`. Upload stages a fresh graph before publishing state; paired trials retain the immutable graph while restoring its live material state and clock. Other backends and larger reference graphs explicitly refuse this API; their existing non-contact paths remain available.

Selection starts at the actual contacted cell, uses deterministic breadth-first/node-ID order, and stays within declared physical radius and hop count. It excludes and does not traverse clamped nodes or broken bonds. It does not heal connectivity when disconnected pieces touch. Whole-selection node/edge budget overflow refuses rather than silently changing the effective contact mass. Bounds: 1,024 total nodes, 65,536 total bonds; 64 selected nodes, 1–64 hops, 1–65,536 edge visits; radius 1 nm–100 m. The experiments select at most three hops and 4,096 edge visits. A selected graph region may still be thin/isolated and refuse the affine surface law; no force, torque, spin or substitute mass is invented in that case.

Each actual surface hit selects fresh support immediately before the existing fixed-source/affine material transfer. Target positions, constitutive histories and absolute time continue unchanged by selection. The immutable adjacency is a structural index, not a cached physical outcome. The low-level declared-support API remains for explicit laboratories; the shared live wrapper removes that trust requirement for this path.

## Comparative experiments

Windows x64 / MSVC Release, headless. Glass/oak/iron retain catalog density/Young modulus 2,500 kg/m³ / 70 GPa, 700 kg/m³ / 12 GPa and 7,870 kg/m³ / 211 GPa, and the same compiled strength/plastic rules. Oak stays laboratory-only. No constitutive/contact coefficients or previous numerical tolerances change.

All cases use 40 mm material cells, horizon 1, finite iron source head (80 mm, width, 80 mm), oak laboratory handle (240, 40, 40 mm), ideal native fixing and explicitly initialized velocity (6, 0.2, 0.1) m/s with zero spin. Gravity/damping are zero. Native shape witnesses provide the common source/target reaction point; the source retains its actual finite mass, inertia, friction and recoil.

Twelve short live-region cases use the previous 80 mm/eight-cell free target, radius 80 mm, and 3.2 µs (32×100 ns or 64×50 ns). All retain eight connected nodes and all accounting/refinement bounds. Twelve original declared-support short cases remain passing regressions.

Twelve sustained cases use a 120 mm/27-cell target centred at (0.1,0,0) m, nine stationary far-face cells and separately audited ideal-support reactions. Target masses are glass 4.32 kg, oak 1.2096 kg and iron 13.59936 kg. Radius is 100 mm. Each runs 204.8 µs (2,048×100 ns or 4,096×50 ns), with a complete paired reversible trial per physical step. Only accepted-step receipts are published. Current supports contain 14–18 movable nodes. Every run reaches the declared duration; no unsupported-region stop occurs in these twelve cases. Thin/isolated refusal and exact rollback are separately tested with prescribed damaged initial states, not presented as simulated fracture results.

| Target | Head mm | Failed bonds, 100/50 ns | Components, 100/50 ns | Detached mass kg, 100/50 ns | Fine/coarse integration-error ratio |
|---|---:|---:|---:|---:|---:|
| Glass | 40 | 16 / 12 | 2 / 1 | 1.44 / 0 | 0.148992 |
| Oak | 40 | 0 / 0 | 1 / 1 | 0 / 0 | 0.032500 |
| Iron | 40 | 0 / 0 | 1 / 1 | 0 / 0 | 0.285144 |
| Glass | 120 | 10 / 10 | 2 / 2 | 1.44 / 1.44 | 0.282874 |
| Oak | 120 | 0 / 0 | 1 / 1 | 0 / 0 | 0.257077 |
| Iron | 120 | 0 / 0 | 1 / 1 | 0 / 0 | 0.240362 |

Glass develops actual failures under the existing compiled law; oak and iron remain whole in this experiment. The broad glass head detaches 1.44 kg at both timesteps, while the narrow head detaches 1.44 kg at 100 ns and none at 50 ns. That large release discrepancy is not gameplay-ready. Detached CPU components retain canonical histories; they have not been installed as native collision bodies or credited to Inventory. These cases do not validate realistic material fracture, grain, crushing, wear or long-time constitutive behavior. They demonstrate live selection through generated failures and retention of material mass/history, not finite neighbour terrain or cell-spin/settling.

Full sustained fixture attribution includes native fixing/contact losses and numerical recoil; target plastic, removal, ideal-boundary and bond/integration accounts. All agree within the retained 1e−9 SI linear/angular and 1e−10 J energy bounds. Maximum attributed errors are 2.9383e-13 N s, 7.78718e-16 kg m²/s and 1.25759e-12 J. Raw unallocated energy before numerical attribution reaches 0.00190209 J; it is not heat or proof of full-world conservation. Integration error stays below the retained 0.1% initial-mechanical-energy cap.

Measured sustained execution is 0.267113–1.11518 s per 204.8 µs, including per-step trials: approximately 1304–5445 times simulated duration. This remains unsuitable for gameplay and does not measure a player digging a 10 ft hole.

## Passing boundaries and failing acceptance

Eight rebuilt focused CTest entries pass across the recorded physics/tool commands: material surface, retained native point/lattice, fixed assembly, external loads, Verlet, tool admission and native tool use. Seventeen real-native Rust worker tests pass against the rebuilt runner. Source registration passes 315/315. New analytical/ownership tests cover exact BFS/hop/radius oracles, broken planes, touching separated pieces, clamps as traversal barriers, moved cells, unsupported covariance, late budget/endpoint/aliveness refusals, upload refresh and paired live-region rollback. An initial test compile error incorrectly reading body identity from `RigidSnapshot` was corrected to retain explicit body IDs before final verification. Changed production/test files add no new compiler warning; retained scene warnings remain visible.

**Sustained convergence is not qualified.** The strict command exits 1:

```powershell
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --require-live-contact-convergence
```

It exposes three open checks: narrow glass differs in its canonical broken-bond pattern (16 versus 12 failures, two versus one components); narrow iron and broad glass exceed the existing 0.27 halved-step integration-error ratio. The ordinary CTest verifies bounded selection, accounting and refusal behavior and reports these open gates; it does not claim the strict acceptance passed. No tolerance is widened, assertion suppressed or failing command counted as green. The scoped graph reference is publishable as experimental; terrain migration remains blocked by these physical qualifications.

The existing `banjo_native_tool_use_tests.exe --require-repeat-yield` also still exits 1 for the same four iron gameplay repeats. Neither strict gate is a full-regression pass. No interactive/input, physical-phone, macOS or GPU qualification is claimed. World on 18890 and material lab on 18891 retain their existing processes; no old subsystem is deleted.

## Next work

Diagnose the sustained discrepancy with controlled source-pose/geometry and contact-order comparisons. Native witness selection, sequential overlapping support impulses and native float microstep response are candidates, not proven causes. Qualify a consistent simultaneous contact/manifold reduction and timestep/spatial refinement against this CPU reference. Then handle unsupported thin/isolated components with actual admitted angular state and exact constitutive ownership, finite neighbours, self-contact/settling, and history-preserving collision handoff. Only after those gates should the physical patch replace `ToolTerrain` centre-bite work and its collision exemptions. Supported soil/water laws, full actor/tool/ground/release accounts, faster execution and actual sustained digging, durable state, Rust/UI migration and W00–W17 remain open.
