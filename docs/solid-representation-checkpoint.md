# Occupied ball compiler and conservative transfer reference

October 9, 2026. **Implemented CPU geometry and rigid/detail mapping reference. Internal material forces, GPU detailed-ball contact/fracture and whole-world realtime remain OPEN.** Source parent main `efc84f9c982219e40b151fece44d00dbac82cd14`. This checkpoint does not add a second impact solver or claim another complete representation family.

## What the owner can see

At `/coupled?representations=1`, the default experiment is explicitly **Rigid ball drop**: a rigid sphere falling onto a prescribed plane and rebounding. Neither object can fracture or dent in this control. Before / Contact / After report actual accepted observations. Full drop now includes the ground when no sheet exists; the previous camera excluded the plane and gave another ball close-up, making motion hard to interpret. Detailed solver results are collapsed. Before, Inspect ball contact and After select actual accepted states.

At `/representations`, **Compile & calculate** creates a material-backed adaptive cube ball, calculates isolated uniform-gravity flight, then restores detailed element poses/velocities at the same ending time. Scrub the calculated time; **Rigid owner** hides the element grid while retaining the exact occupied cube union; **Expand into elements** shows the final retained elements. **Inspect interior** clips the view to expose larger interior and finer boundary elements. Nothing explodes or receives invented launch velocity. This workbench stops at 20 cm conservative ground clearance and **does not calculate an impact, cracks or dents**.

The requested sphere is an authoring input. The compiled cube union is a separate explicit approximation; it does not silently replace the GPU lab's exact sphere or change its law. Existing default GPU motion, tolerances and native executable are unchanged.

## Implementation

- [`solid_representation.py`](../scripts/solid_representation.py) compiles a bounded, versioned installed recipe. Octree cells wholly inside the sphere remain coarse; boundary cells refine to the requested level and use center occupancy. Cells have stable matter IDs; independently created instances have separate persistent UUIDs retained through every mapping. A finest-grid compiler index finds actual shared-face areas across unequal cells and preserves empty space. Interfaces have stable IDs and requested installed law names; **solver bindings are null** because adaptive face laws/contact are not yet admitted.
- Installed material coefficients and units are retained. Density times actual occupied volume supplies mass; no renormalization hides missing/excess volume. Exact cube intrinsic inertia and the full parallel-axis tensor account for occupied matter. The geometric boundary-distance bound is half the finest cube diagonal. Refinement errors are measured, not assumed monotone.
- One mechanical owner exists at a time. Detailed state retains current cell geometry, orientation, spin, velocity, interface connectivity/history and field metadata. Collapse derives the aggregate COM/full inertia/velocity/spin and preserves current local poses, including edits; expansion does not regenerate the original intact recipe. Field metadata is retained but has no thermal/reaction evolution.
- The mapping measures central angular momentum directly rather than subtracting large orbital terms. Relative kinetic energy is a positive sum of residual cell translation/spin energy, avoiding cancellation between total energies. More than `1e-10 J` relative kinetic or elastic energy refuses rigid continuation. Disconnected cells refuse a single owner. Mapping audits permit at most `1e-9 J`, `1e-9 N s` and `1e-9 N m s` roundoff; inertia consistency uses a `2e-12` relative tensor norm. These are new reference transfer bounds, **not changed contact/material admission tolerances**.
- The CPU reference evaluates exact uniform-gravity translation and torque-free isotropic spin. Anisotropic nonzero spin refuses until an Euler integrator is qualified. The workbench's complete interval has a conservative enclosing radius for all occupied cubes and spin orientations; COM descends only until the radius remains 20 cm above the horizontal boundary. There is no sampled collision response. Each displayed pose is evaluated at its declared physical time; no renderer-owned extrapolation or cached fracture is used.
- A bounded same-origin `/api/representation` endpoint admits only installed material/radius/resolution/height/spin/frame settings. No arbitrary code, foreign definitions or client-supplied physics states are executed. Only one compiler request runs concurrently, requests are bounded to 4096 bytes, and oversize geometry refuses without silently coarsening. The source hash is pinned at import and edited sources require restart. The endpoint creates no GPU/native world session and cannot alter the existing impact scene.

## Measured evidence

[`reference.json`](evidence/solid-representation/reference.json), exact reference source SHA256 `c5cb7217587c44b27758029c6c990e659c6c6eda04b55d82f8fcab567463e5f2`. Windows x64, Python 3.13, NumPy 2.2.6 CPU. Independent formulas check volume, full cube/parallel-axis inertia, actual shared faces and gravity work/impulse/torque about a common origin. No GPU/material-realism/cross-platform claim.

For the same 0.05 m requested sphere:

| Boundary level | Occupied elements | Interfaces | Volume error | Inertia error about one symmetry axis |
|---|---:|---:|---:|---:|
| 2 | 32 | 60 | -4.507% | -0.528% |
| 3 | 224 | 552 | +4.445% | +9.730% |
| 4 | 1,168 | 3,204 | +1.461% | +3.124% |

Level 4 contains three cube sizes; level 5 exceeds the 4096-element compiler bound and refuses. The coarse inertia happens to be closer than the medium case. This is why declared geometric/error budgets are necessary before using an approximation as an exact sphere replacement. The analytical volume oracle uses compensated summation; the existing reference-order registry sum agrees within `2e-13` relative FP64 accumulated-roundoff tolerance. No lost volume is accepted.

Glass/oak/iron/ice use the same geometry, 10 m initial clearance, gravity 9.81 m/s², spin `[0,3,0] rad/s`, and 12 output intervals through 1.41349 physical seconds. This is an analytical flight law, not an internal-force timestep. Density 2500/700/7870/917 kg/m³ gives masses 1.3671875/0.3828125/4.30390625/0.501484375 kg. Declared Young's moduli 70/12/211/9 GPa are stored but **do not affect this rigid flight**; no stiffness/grain/plasticity comparison is claimed.

The four CPU requests take about 0.15–0.17 wall seconds each including compilation, mappings and output generation, excluding HTTP/render delivery. Energy residuals are at most `5.69e-14 J`, momentum residual norm at most `5.76e-13 N s`, and angular residual norm below `2e-16 N m s` in the recorded drop cases. Separate translated/rotated/spinning transfer fixtures retain histories/metadata and account gravity torque; their largest recorded flight energy residual is `1.14e-13 J`. These are **geometry/transfer/free-flight measurements**, not realtime contact qualification.

Six affected CTests passed: new registered solid representation, existing gateway, pipeline, playback, session and coupled view. The final solid-reference suite passed again after private constant-law frame generation was introduced. The source registration guard retains 345/345 compiled C++ sources; this checkpoint adds no C++ source. HTTP tests exercise the actual server endpoint and refusal behavior. The actual in-app browser verified medium glass and fine iron 3D geometry/interior views, final expansion and error readouts. It also ran the ordinary GPU 10 m drop to 2 s: accepted contact at 1.4278541 s and upward velocity 8.394 m/s, then used the contact close-up. Final publication verification must confirm the same routes on the restarted main server.

## Remaining work

1. Bind this occupied-matter compiler to admitted detailed solid/contact laws, including adaptive face quadrature and full inertia. The current CUDA factory limit of 32 bodies/128 interfaces cannot accept the medium ball; declaring interfaces does not solve them.
2. Transfer one canonical object to/from an actual rigid GPU owner at a common clock. Keep exact occupied collision geometry, all internal histories and work; qualify activation before collision, rollback, save/reopen and later damaged-fragment reactivation.
3. Complete and refine actual glass/oak/iron/ice impacts under matched conditions. Retain the connected-glass work-budget refusal. Show measured cracks/deformation/fragments where laws support them and compare before/during/after.
4. Qualify reduced deformation, articulated/sleeping mechanics and field/flow transfers. Full pipeline speed still includes collision calculation, delivery, rendering and responsive controls. The eight-family objective remains active.
