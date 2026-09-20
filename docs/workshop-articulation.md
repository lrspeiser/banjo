# Workshop articulation compiler

Source checkpoint, September 20, 2026. This is an executable compiler and native regression, not a completed arbitrary-product installation path.

`playground/workshop_articulation.py:compile_design(design, overrides, cell_m=.04, root="assembly")` translates existing authored fixed/bearing joints into native cell bodies and hinge declarations. It returns `banjo.workshop-articulation.v1`, with source joints and measured interfaces, per-group occupied cells and mass, component-to-body identities, native bodies/joints, material totals and a physics hash independent of the runtime instance prefix.

Only explicitly fixed connections merge components. Bearing endpoints stay in different bodies. Each fixed group must be connected in the occupied-cell grid and homogeneous in material; different moving groups may use different materials. Every source component must retain cells. Each group's box decomposition must reproduce exactly its occupied cells. A bearing mount must touch occupied native cells on both sides. A fixed path that locks a bearing, open joints, orphan groups, missing cells and overlapping moving groups are refused. In particular, drawing a shaft inside a solid housing does not create a bore: the author must provide real clearance. Budgets are 16,000 occupied cells and the existing native box budget. The compiler accepts the explicitly selected lattice model; it does not convert precise rigid models.

Native bearings currently use ideal hinge constraints, with the native full-range settings and zero authored friction. This does not establish bearing load capacity, wear, backlash or a calibrated friction law. Fixed component labels and source joint methods remain in the artifact. Proposed method-specific weak-joint factors remain inactive.

## Native experiment

At 40 mm cells, an 80 x 80 x 400 mm arm meets an 80 mm support cube on a face. The source interface supplies the bearing axis and contact centre. The test anchors the support as its declared external boundary, then advances 24 steps at 1/240 s under native gravity. Nothing imposes arm rotation or velocity. Every native body's occupied cells and material are checked against its group descriptor before stepping.

| Material | Moving arm mass (kg) | Bearing-constrained drop (mm) | Drop with bearing removed (mm) | Pivot-radius error (mm) |
| --- | ---: | ---: | ---: | ---: |
| Glass | 6.4 | 32.77 | 51.06 | 0.03485 |
| Oak | 1.792 | 32.77 | 51.06 | 0.03485 |
| Iron | 20.1472 | 32.76 | 51.06 | 0.03286 |

The support remains fixed; the arm changes orientation, keeps mass within 1e-6 relative, and preserves its pivot radius within 0.5 mm. Removing the joint produces at least 10 mm more downward travel. Matched-material constrained displacement must agree within 1 mm. These checks prove compiled native constraint behavior, not realistic bearing strength, support-reaction closure or full energy qualification.

## QA and remaining integration

The existing **Run fabrication QA** button and HTTP/MCP QA functions now also run the five compiler cases and the native three-material bearing experiment, retaining their measurements. The current fixed suite has 33 cases. [Recorded local QA](evidence/articulation-stage-qa.json) includes source revision/dirty state and native binary hashes. CI already runs the containing installation test modules; the full modules report 19 admission/compiler and 32 native cases passing, with two QA-runner integration checks passing.

There is no new public installation or manufacture tool in this checkpoint. The current funded installer still correctly refuses articulated products. Staging now preserves multiple new body identities and constraints alongside old-world state. Next fund material by group, admit each group's thermal output, bind core-use programs and interaction points to the right body, then expose the funded assembly in the main world. Articulated bag storage and mixed-material fixed groups remain separate unsupported cases. The existing local main world is unchanged by these isolated experiments.

## Verified assembly staging and restart (September 20)

The shared native staging path now accepts an articulation artifact and checks every group independently against its occupied cells. The preservation verifier permits only the declared new hinges between the newly added bodies. Existing constraint state stays exact (with the existing four-float32-ULP allowance for derived hinge angle readouts). New IDs must follow the saved next-joint counter; no unrelated counter may change. Both world-space attachment points, the normalized axis, declared limits/friction, native solver limits and initial angle, attached state and absence of undeclared capacities are checked. Old body motion, heat parcels, material geometry, clocks, inventories and other existing state still use the existing exact preservation checks.

The new native case first runs a 350 K glass/oak/iron assembly for 0.1 s, then adds another two-body assembly with one bearing to a private staging world. The old live snapshot is unchanged. The combined snapshot reopens at whole-world tier, retains both constraints, and the new arm moves under gravity after restart (y = 0.96723/0.96723/0.96724 m after 0.1 s from 1 m). Nine corrupt-state variants per material reject changed axes, endpoints, attachment points, limits, friction, attached state, old-joint state, next-ID counters and solver limits. All 32 native installation cases and 19 admission/compiler cases pass; two HTTP/MCP QA-runner checks include the new three-material measurements.

This is staging/restoration infrastructure, not public assembly installation. Funding and thermal transfer still assume one output body, and the public preview adapter still rejects articulated products. Remaining work is to connect multi-body publication and receipts, group-aware thermal transfers, construction costs, and core-use/interaction routing before exposing funded assemblies in the main world. The staged test's anchored support is an explicit laboratory boundary; it does not certify a manufactured mount or bearing strength.
