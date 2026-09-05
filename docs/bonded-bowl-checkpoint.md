# Actual bowl fracture: experimental bonded-cell model

**Rolling/fracture correction:** [Strength gate and computed replay](rolling-strength-checkpoint.md), source `aa3491f`, local only. Glass/oak/iron isolated rolling is damage-free over 0.3 s; strong glass impact still fractures progressively. The native eight-ball 1.25 s replay moves visibly and ends with four broken links but eight connected groups; contact attribution remains open. Calculate prepares a fresh trajectory, then Replay shows normal-speed motion. Coarse contact geometry, continuum calibration and the full platform remain unfinished. Earlier energy-only bowl notes below are historical.

September 5, 2026. Physics/integration `f55f996`, final UI guidance `a939df0`, local `codex/physics-foundation`, not main. The bowl now defaults to an experimental fracture mode; its rigid Jolt comparison remains selectable. This extends the application, while material realism and the full platform gates remain unfinished.

## What the user can do

Release the existing inventory-backed balls in the bowl. Glass can develop local bond failures, split into connected groups and continue interacting with the bowl and other matter. Surviving groups retain their internal positions, velocities, spin and bonds, so a detached piece can fail later. Oak and iron are elastic comparisons with failure unsupported. Pause, reset placement, switch surface/tilt, export the experiment or save an image. Reset/mode changes restore the same allocated objects as an authoring operation; they do not recover spent work or credit inventory.

The new mode runs slowly: the display advances a 1/2400-second requested interval per frame, subdivided into material steps. The earlier microscope is still a separate microscopic reference with a different integrator. Its trajectory is not replayed or mapped onto bowl impacts.

## Physical and numerical contract

Each 45 mm sphere is represented by 19 equal-mass quadrature cells on the center/face/edge sites of a cubic stencil. Spacing h is R/(sqrt(2)+0.45), about 24.1 mm. Each collision sphere has radius 0.45h. Total mass is the catalog density times the authored sphere volume. An isotropic finite-cell inertia remainder preserves the analytical sphere's initial rigid rotational inertia together with the node orbital contribution. The small contact spheres are proxies, not a claim that their union fills the authored sphere volume.

Face/diagonal central elastic links use stiffness E*A/L and area weight A=h*h/6. Current positive extension stores U=0.5*k*q*q. Only a brittle-model link whose own current U reaches Gc*A can fail. The removed energy is separated into fracture work and numerical overshoot; neighbor links are never broken automatically. A failed event trial recursively halves time if its overshoot exceeds 2% of that link's work. Previously disconnected cells continue using the same contact and elastic laws.

This is an explicitly selected **coarse energy-regularized law**. It does not enforce the catalog glass tensile-strength lower bound used by the earlier microscopic rupture adapter. At this spacing, its derived tensile threshold is about 5.7-6.8 MPa, below the catalog's 45 MPa; continuum modulus/Poisson response and fracture surfaces are also uncalibrated. This difference is intentional and disclosed, not a claimed calibration or a modification of the stricter reference solver. Do not interpret low-speed failure or the resulting fragment sizes as real glass predictions.

A single velocity-Verlet cell solver owns normal cell/cell and cell/bowl response, gravity, central elastic forces, finite-cell spin and friction. Jolt is not stepped in this mode. The bowl contact uses an analytic paraboloid with finite rim; the renderer still draws its triangular approximation. Linear normal compliance uses combined material modulus and proxy radius. Exact dissipative pair maps account separately for internal damping, contact damping and surface friction; common-point friction retains angular reactions. Spring/normal integration error remains a separate measured residual, not heat.

The timestep estimate combines the link stiffness/mass rows with a declared 24-contact-neighbor estimate and fraction 0.35; it is not a proof for arbitrary penetration or packing. Accepted outer intervals must keep cumulative energy error within 1% of max(abs(initial energy), 1e-6 J). Exceptions, excessive evaluations (65,536) or energy error roll back the entire requested interval, including candidate breaks, work and time, then pause the UI. Safe common free flight can advance analytically only before damage when internal motion is absent and distance bounds exclude contact. No elastic modes are suppressed after impact.

Rendering shows a smooth sphere before damage, then the actual surviving cell/link network. It creates no authored shard patterns, visual separation offsets or launch impulses. The collision proxies and rendered envelope/link tubes differ, so visual geometry and packing remain approximate. Refining this representation is a required next step.

## Verification

Windows/MSVC Release. The promoted bonded-bowl executable passes its complete new suite. The promoted existing bowl, microscope-preview and rupture-cascade suites pass (3/3, 1.95 s). The legacy bowl and new bonded-bowl suites pass (2/2, 45.69 s). No full platform suite, cross-platform graphics or general material calibration is claimed.

Eighteen closed-pair cases compare glass, oak and iron at initial per-body speeds 0.05, 0.5 and 2 m/s, with timestep fractions 0.35 and 0.175. Each experiment starts just before actual contact and advances 2 ms. All satisfy the 1% energy bound including named losses, linear/angular momentum checks and exact retained cell mass. Oak/iron have zero breaks. Final glass counts agree between the two timesteps:

| Per-body speed | Glass broken links | Final groups across two balls |
|---:|---:|---:|
| 0.05 m/s | 0 | 2 |
| 0.5 m/s | 68 | 10 |
| 2 m/s | 148 | 30 |

Each pair has 38 cells; even the strong fixture retains some connected groups. Event-history tests confirm time-separated failures and later failure within an already detached piece. Counts agreeing at two timesteps is not general trajectory/event-time convergence; high-speed fracture energy residual is not monotonic under halving.

Twelve short support cases compare all three materials on concrete and oak at 0 and 10 degrees. Initial pose/velocity are rotated with the fixture to avoid initial overlap. Support/gravity reaction ledgers close linear and angular momentum, friction does positive accounted work, and energy stays within the declared bound. A deliberately exhausted evaluation budget restores all positions, velocities, time, topology/event history and fracture work.

The actual six-ball bowl release reaches 0.6 s with 78 broken links and 24 connected groups, only glass failures, all cells above the level-bowl retention bound and unchanged inventory. Initial energy is 19.2604 J; the final numerical residual is 0.000442636 J. Reset restores intact allocated balls without changing stock. A longer developmental run reached 1.5 s and retained 155 broken links; this was diagnostic, not an additional full acceptance matrix.

Native input verified release and continued fragment motion, pause, switching rigid/experimental mode, unchanged eight-ball inventory, experiment export and image save. The saved eight-ball visual checkpoint at 0.63125 s has 183 failed links and 35 groups. Initial energy is 30.2479 J, fracture work 0.142175 J, event overshoot 0.000890720 J and residual 0.000978630 J. The PNG was opened and visually checked. The final guidance-only rebuild leaves the lab ready for a fresh release.

Exports contain the selected solver model, uncalibrated-strength flag, cells and their original object IDs, current component IDs, link states, event times, contact proxies, work/loss totals and support/gravity impulses. Stock persistence retains allocations; the experiment JSON is an inspection export, not a complete resumable trajectory/replay format.

## Next steps and retained gates

1. Replace the coarse proxy geometry with consistent occupied matter/contact/render surfaces; compare cell sizes, orientations and contact phases before interpreting fragment shapes.
2. Calibrate bulk response, cohesive/process-zone length and strength/Gc together. Keep the stricter microscopic law intact and explicitly version every approximation; preserve glass/oak/iron comparisons.
3. Optimize measured cost with validated local detail/sleep/coarsening while retaining internal state, work and repeated-fracture behavior. Do not soften materials to make the demo faster.
4. Expand oblique/ball-to-ball/fragment/rim/tilt tests, longer energy/reaction budgets, and state/event-time refinement evidence. Add wood grain/failure and iron plasticity only with their own laws/tests.
5. Connect supported outcomes and limitations to the crafting/LLM API and persistent material history. Fabrication energy, tool/level progression and all other retained mechanics still apply.

All 40 scorecard rows and all full-project gates remain active. The owner can now observe fracture in the actual bowl; the realistic, general-object physics platform is not complete.
