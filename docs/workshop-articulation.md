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

The existing **Run fabrication QA** button and HTTP/MCP QA functions now also run the five compiler cases and the native three-material bearing experiment, retaining their measurements. The current fixed suite has 32 cases. [Recorded local QA](evidence/articulation-qa.json) includes source revision/dirty state and native binary hashes. CI already runs the containing installation test modules; the full modules report 19 admission/compiler and 31 native cases passing, with two QA-runner integration checks passing.

There is no new public installation or manufacture tool in this checkpoint. The current funded installer still correctly refuses articulated products. Next connect the compiler to staging: preserve multiple new body identities and constraints alongside old-world state, fund material by group, admit each group's thermal output, bind core-use programs and interaction points to the right body, then save/reopen the assembly and expose it in the main world. Articulated bag storage and mixed-material fixed groups remain separate unsupported cases. The existing local main world is unchanged by these isolated experiments.
