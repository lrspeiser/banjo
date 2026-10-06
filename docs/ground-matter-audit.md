# Ground matter audit and replacement contract

October 5, 2026. Source baseline: GitHub main `db637b4a`, fetched before work; Windows x64. This is a source audit and a removal of cosmetic transfer motion, **not an implementation or qualification of physical excavation fragments**. The owner requires material voxels in ground, detached matter and crafted tools, with motion/failure decided by simulation. This supersedes the earlier suggestion to use an abstract stone-crafting shortcut. Earlier paused object damage/repair scope is not implicitly completed or resumed wholesale.

## Findings

| Stage | Present implementation | What it establishes / missing behavior |
| --- | --- | --- |
| Intact ground | `src/terrain/TerrainField.*`: per-column material runs, heights, voids and volume ledgers; `Environment.*` rebuilds native colliders and water beds | Actual editable solid boundaries and material quantities. Not an interacting solid/granular voxel lattice; height bands have no bond/damage field. |
| Ordinary cube strike | `src/fastlattice/ToolTerrain.cpp`, `ToolTerrain::strikeCell`: fixed 3 m/s and 26 J; top soil/sand removes one cell; wall material uses one/three/ten shares for soft/clay/rock | A native geometric extraction command with accounted mass. Neither contact-measured strike work nor constitutive fracture. It labels the result `ground-work-v1`, despite using a different shortcut. |
| Swing on cube ground | `ToolTerrain::meet`/breakout branches retain one/three/ten paid-cell shares | Disabling only the quick HTTP route is insufficient; the cube-specific law also exists inside the stroke path. |
| Other terrain strokes | `GroundWork.*`, `ToolTerrain.*`: reduced dry-soil bearing/passive-wedge response and declared rock-specific-energy model | Material/shape-dependent resistance and measured contact work, with unsupported regimes. Still exports aggregate volume; no physical fragment topology, grain contacts or debris pile. Not calibrated material realism. |
| Removal | `TerrainField::dig`, `chip`, `breakOut`; `Environment` carrier accounts | Terrain decreases; volume/mass moves into an account. No detached cell bodies, source voxel identities, inherited velocities or fracture surface state are emitted. |
| Automatic piles | `playground/world_goods.py::heap_excavation`: withdraw owned native volume into a host stockpile; choose dry positions behind/beside the player | Retained ownership, retry and quantity accounting. The material moves to a chosen receiver position without a simulated hauling path. No native grain collision or settling. |
| Pile display | `playground/world.js::goodsVisuals`: excavated cone from bulk density/repose constants, capped footprint; other stocks use capped decorative cube counts | Procedurally generated ledger pictures, not prerecorded video. The cone is not the settled geometry, and pictured cubes are not the constituent matter. Ground can be dug beneath these pictures; they have no native load/support response. |
| Transfer display | Former `goodsVisuals` flights: capped count from square root of kg, 1.15 s lerp plus sine arc/spin; former `showToolOutcome` DOM squares: capped count from kg and CSS trajectories | Entirely cosmetic motion, with no represented mass, collision, momentum or energy. Removed in this checkpoint across excavation, mining, processing and collection receipts. |
| Inventory | Native/host ground accounts, transfer packets and SQL supplies | Finite quantities and private transactions. Matter's shape, individual state and source identity are lost in bulk aggregation. Unlimited gameplay Inventory is an abstract storage policy, not demonstrated physical cargo. |
| Crafted tools | Workshop samples parts at the installation cell size; native fixed assemblies retain separate head/handle materials, masses and grip/point frames | Existing sampled geometry is useful. Crafting does not transfer the collected ground's exact constituent cells/damage into a tool. Some supported rigid shapes use another admitted adapter. Internal wear/failure and all mixed interfaces are not universally qualified. |
| Existing object fracture | `LiveWorld::fracture`, `FragmentLattice` and connected-component handoff | A reuse candidate for supported solids, with existing validity/performance boundaries. It is not an implemented granular-soil solver or ready terrain coupling. Do not present the old ball laboratory, limited-fragment fallback or complete mass sum as full-world physical qualification. |

### Quantitative contradiction in cube mode

A full 0.25 m cube is 0.015625 m3. At the terrain rock density 2400 kg/m3 it contains 37.5 kg. The repository's declared `rock-work-v1` specific energy is `0.3 * 100 MPa = 30 MJ/m3`, requiring **468,750 J** for that full cube. Ten shortcut strikes report **260 J**, a factor of approximately **1,803** lower. These are calculations from declared code inputs, not a calibrated claim about actual stone or a new physical experiment. Top/wall shortcuts also differ in how clay is classified. Tool material cannot justify a constant work assignment or an arbitrary hit-count threshold.

The prior ground/water tests prove selected geometry, volume receipts, ownership and reopening under those extraction commands. Glass/oak/iron yielding the same removed cube in these tests does not validate their material-dependent fracture behavior. A closed mass ledger does not close momentum, angular momentum or energy.

## Immediate checkpoint

Remove visual-only moving material cubes from both receipt renderers. Keep the existing target indicator, operation confirmation and quantity text as interface feedback. Keep static stock/pile pictures and existing durable accounts usable during replacement; they remain **ledger visuals**, not physical debris. No native law, tool rate, yield, pile placement, save format or material constant changes in this checkpoint. In particular, the one/three/ten shortcut and its falsely shared model identifier still require native replacement; removal of animation does not repair them.

Regression coverage executes the shipped renderer with excavation/mining/input/output/collection receipts and asserts that they cannot create moving fragment meshes or mutate stock. The browser processing-to-private-Inventory journey now checks actual stock changes and absence of fabricated flight meshes instead of requiring a cosmetic flight. Receipt rejection/contact tests and real material totals remain covered.

## Replacement, in dependency order

### 1. Authoritative matter and provenance

Represent terrain as sparse material bricks with a reproducible numerical cell size and stable source-cell/material IDs. The unactivated far field can remain compressed material runs; local activation must reproduce the same volume, layer interfaces, defects, history and support. The rendering and collider boundaries are caches of this matter, not independent source geometry. Resolve 25 cm terrain versus 40 mm object-cell incompatibility explicitly: partial cells carry their actual volume/inertia, or compatible hierarchy levels are chosen. No rounded extra volume, silent material change, or healed damage at refinement.

Ground, detached pieces, storage and made objects share the material/state contract. Voxel cells are numerical samples, not atoms; a soil voxel is not automatically a physical sand grain. Solid rock and granular/cohesive soil require distinct model capabilities, even when they share storage.

### 2. Actual tool work and failure

Retain cursor/touch targeting, fast input, generic point/grip declarations and native bounded hand control. Apply the commanded stroke through native forces/constraints; account for player actuator work and terrain reactions. Account for both tool and ground material/geometry. Use one response per contact. Remove fixed 26 J, fixed hit counts and the parallel cube-stroke shortcut only when the replacement reference is accepted; do not relabel them as real fracture in the meantime.

Solid connectivity changes through implemented constitutive damage/failure with available work and fracture area. Soil detachment/flow requires a declared cohesive/granular law and contact handling. Oak cannot become a brittle stone preset. Weak action can leave persistent local damage; material extraction is the actual disconnected matter, not an expected loot quantity. If a regime is unsupported, refuse it explicitly. Tool performance must emerge from its work, geometry and material limits; faster UI input must not supply unaccounted energy.

### 3. Detachment and physical piles

When connectivity/support fails, transfer the exact released cells into native connected components. Preserve mass, COM, inertia, linear/angular momentum, internal/elastic energy, damage and temperature. Derive initial motion from the pre-detachment state; never add random launch velocities, arbitrary explosion impulses, automatic subdivision into loose cubes, or a fragment-size distribution chosen for appearance. Mini cells may remain bonded as larger chunks until they actually fail.

Let native gravity, terrain/body/grain contacts, friction and water coupling decide where matter goes and settles. Piles form where those bodies settle; no `heap_excavation` receiver teleport or cone reconstruction. Unsupported cave roofs must be supported by the model or collapse, without a blanket cube-mode stability bypass. Preserve smooth unworked hills and exact activated cuts through one boundary representation. Wet cuts need a qualified law; shallow open-channel water is not a covered-tunnel or granular-entrainment solver.

### 4. Collection and crafting from that matter

Select reachable native material bodies/cells; perform one authenticated ownership transfer. Remove them from the physical world exactly once and retain provenance/state in private storage through retry/peer/restart. Unlimited Inventory can remain a clearly defined storage abstraction; it must not be claimed as infinite physical cargo or a shortcut for transporting material into nearby visible heaps. Old bulk lots stay recoverable with marked legacy provenance; never invent historical fragment positions or velocities for them.

Make a stone pick by a supported work/material transformation, conserving actual source volume/mass and recording removed waste and formation/joining work. Build parts from the shared matter cells and valid material interfaces, with a native grip and point. Primitive shaping, processing and joining need declared work sources/capabilities; asking the LLM to name stone or add a binding does not create a constitutive law. Raw ore is not processed metal. Save design is separate from making/altering the physical tool.

LLMs may propose unit-bearing shapes, materials, point/grip bindings, supported processes and tests. The compiler admits them against the current world's laws, quantities and resolution. They cannot author hit-count removal rules, synthetic fragment trajectories, arbitrary kernels, free work, guaranteed upgrades or per-use model calls. Routine new tools use the same tested physical path.

### 5. Renderer, persistence and bounded performance

Stream authoritative fragment IDs, occupied cell/material data, poses, damage and revisions; interpolation uses consecutive solver samples in physical time. No receipt-to-particle fabrication. Coalesce resting connected matter only when the representation preserves occupied volume, inertia, contacts, damage, recoverable energy and reopening behavior. Do not silently turn excess physical fragments into collisionless particles. When a measured resource limit is reached, retain/resume the operation with an explicit boundary instead of changing the material law.

Start with a CPU reference and a small active patch. Benchmark cell spacing, timestep, patch extent, active bodies/contacts, save/network cost and real browser frame time separately. A 25 cm cube contains 125 full 5 cm cells or 1,000 full 2.5 cm cells; these counts alone are not runtime estimates and do not imply that each cell must be a separate Jolt body. Reuse material palettes/rest templates; simulate moving disconnected components at the appropriate qualified detail. GPU work follows measured bottlenecks and reference agreement.

## Acceptance gates

1. **Matter transfer oracle:** exact clipped layer/cell volumes, density-derived mass, COM/inertia, ownership and conserved state across terrain -> detached components -> storage -> manufactured object/waste. No extra matter, double credit, or damage healing on refinement/restart.
2. **Constitutive cases:** same declared experiment for glass, oak and iron, plus actual stone and supported soil/sand. Record timestep/resolution, density/stiffness differences, initiation/damage/failure work and unsupported laws. Quiet contact must not fracture; stronger declared work changes damage through the law, not click count. Include more than one grid alignment/resolution and unchanged or justified tolerances.
3. **Full-system ledger:** tool, holder actuator, terrain/supports, fragments, gravity, water and numerical corrections. Record linear/angular momentum and energy including fracture/plastic/contact/damping losses and external work. A mass sum or pairwise impulse test alone cannot pass this gate.
4. **Physical outcomes:** detached fragments fall/collide/settle; a second strike acts on retained matter; material blocks/supports respond; reachable collection removes those same cells. Test supported dry/wet boundaries and terrain/region seams.
5. **Durability:** two players strike/collect independently; exact retries, partial work, dropped replies, rollback, reopen, legacy bulk lots and re-equipped made tools retain state without duplication.
6. **Player journey:** phone/desktop collect actual stone and wood -> request/preview a pick -> review actual missing material/work -> make -> Inventory -> equip -> ordinary use -> repeat -> restart. LLM-created variants must pass the same native admission/physics tests. Existing walking timing variability is separate and remains open.

**Next native milestone:** a small dry solid terrain patch using persistent material cells and measured tool work, connected-component detachment and native settling, with complete source accounting and glass/oak/iron/stone comparison. Granular soil and wet coupling require separate accepted model increments. Do not replace all current ground with an unvalidated prototype or claim stone crafting is complete after the presentation cleanup.

## Verification record

Windows x64, source baseline `db637b4a`, unchanged native demo executables from `C:/play/bin`. JavaScript syntax and Python compilation checks pass. All 300/300 native sources remain registered; no new native source was added. The terrain/render and tool-client suites pass 38 cases, including actual shipped receipt rendering with all five transfer kinds and no synthetic flight bodies. The ordinary Chrome processing/input/output -> private Inventory journey passes (1 case, 9.750 s), retaining actual balances, native receipts and no browser exceptions. The emulated-phone touch journey passes (1 case, 8.330 s). The ordinary E pickup/bag/dig journey passes on its final rerun (1 case, 16.426 s), but two earlier runs failed at starter-tool pickup before any dig. Published-baseline static assets passed twice (16.290/16.621 s); this does not establish the cause of the intermittent pickup failure. No test tolerance or pickup precondition was relaxed. That variability remains an open broader player gate. Expected aborted HTTP replies occur during phone page reload.

Local evidence: `build/ground-matter-audit/phone-player.log`, `current-player.log`, `current-diagnostic.log` and `baseline-player*.log`; browser images/reports in the existing ignored `build/resource-flow` and `build/player-regression` folders. Changed-link/syntax/scope checks and source registration passed before publication. Implementation/audit `fe6cb732` is on GitHub main. The existing port 18890 demo checkout was fast-forwarded to that revision; World responds HTTP 200 and served JavaScript contains neither receipt-flight bodies nor DOM material packets. Native binaries and saved rooms were retained. Native laws and binaries are unchanged; no new physical material qualification is claimed.
