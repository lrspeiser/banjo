# Pinball workshop

October 19, 2026. **Sandbox → Pinball** creates an independent saved design.
The five existing showcase machines remain. The Pinball category in the piece
library contains eight reusable tools; the starter is assembled from them.
Build edits the setup, Run advances the native machine, and Reset reloads its
original setup. Saved versions, Undo and run-only course sharing use the normal
Sandbox paths. This pack does not add training levels yet.

## Play and controls

Choose Run. Hold **Pull launcher · release to shoot**, then release it.
Hold **Left flipper** or **Right flipper** to operate the physical buttons.
Left/Right arrow keys and Space provide the same held inputs. The physical
button caps and launcher can also be held in the 3D scene. Touch supports
separate simultaneous fingers. Release, pointer cancellation, lost capture,
window blur and Pause let go; the server expires an unrenewed force after one
second. Text inputs retain their ordinary keyboard behavior.

The opening camera faces the player end of the table from above, with the
named left paddle on screen left. Controls stay in one row along the scene's
lower edge. Run gives the table more screen space and hides setup wiring labels;
Build restores them for inspection. The glass guard remains a physical collider
even though its transparent surface allows selecting the mechanisms beneath it.

## Components and their laws

| Tool | Construction and adjustments | Physical role |
| --- | --- | --- |
| Pinball playfield | 1.5 × 2.6 m oak deck at 5°, rails, drain, four legs, a clear guard and two bearing apertures; width and length | Gravity and contact carry the ball downhill. The drain is an opening, not a trigger teleport. |
| Smooth pinball | 40 mm iron sphere; diameter and glass/oak/iron material | Exact homogeneous sphere, density-derived mass, analytical spherical inertia, native friction and impact. It starts with zero imposed spin and velocity. |
| Pinball spring launcher | One rigid aluminum rod/nose in a slide, 400 N/m axial spring, 0.28 m draw and a retaining throat; spring stiffness | A bounded 120 N operator force draws the rod. Release removes that force; the spring pushes the ball through contact. No launch impulse is inserted. |
| Powered pinball flipper | Aluminum paddle on a grounded bearing, native hinge stops, coupled DC actuator and axial return spring; left/right, length, stall torque and return stiffness | Circuit current supplies torque, with back EMF and reaction on the bearing. Opening the switch removes power and the spring returns the paddle. |
| Spring-return button | Hinged aluminum contact cap, fixed iron output pad and compression return spring | Operator force closes actual metal contact. The flexible input attaches at the pivot so it does not have to follow a sliding cap. |
| Rubber pinball bumper | Passive spherical rubber fixture; radius | Contact can return existing impact energy. It has no hidden powered kick. |
| Pinball guide rail | Solid mounted rail; length and heading | The launch turn and inlane guides deflect the ball through contact and keep the flipper sweep clear. |
| Hanging pinball target | Aluminum plate on a bearing and a fixed iron support | A hit swings it; gravity returns it. Native contact stations observe hits. |

The starter includes a finite 24 V, 10 kJ supply with a 1 kW limit, two parallel
button/actuator loops and six 2.5 mm² copper leads. Each external terminal and
return path is explicit. Cables have the existing native mass, bending, gravity,
collision and terminal pullout. Their declared 200 N locking terminations and
below-deck service routes are part of the apparatus. Leads pass through actual
bearing holes; the rotating paddles do not sweep through their connectors.
The cable collision rods are 80 mm long in this starter.

## Numerical scope and limits

Pinball requests a 1/480 s physics step because its small parts and fast spring
contact need finer resolution than the default 1/240 s. Network frames remain
at the ordinary update cadence: each frame batches more native steps. The
machine format accepts 1/240, 1/480, 1/960 and 1/1920 s; existing levels retain
their 1/240 s default. Qualification also runs Pinball at 1/960 s. Different
materials and contact timesteps can produce different later bounce sequences;
these observations are not a calibrated commercial pinball model.

The new exact-sphere declaration exposes Jolt's existing sphere primitive; it
does not introduce a new force law. Single-sphere mass is rho × 4πr³/3 and
inertia is 2mr²/5, tested for glass, oak and iron. Exact rigid bodies, including
the ball, glass guard and paddle, do not have resolved fracture or thermal
interiors. Bearings and mountings are ideal joints. The actuator is the existing
reversible lumped DC motor law, not a resolved solenoid, armature, winding,
contact arc or insulation model. Axial springs are force elements, not resolved
coil-wire stress. Native cable and general contact limitations still apply.

Worlds containing exact spheres select the existing feature-scaled native
contact settings using the smallest sphere diameter. For the 40 mm stock ball,
penetration slop is 0.4 mm; Baumgarte position projection remains disabled.
Worlds without exact spheres keep their previous settings. A single exact
sphere also uses the existing material rolling-loss law, with torque and
reaction accounting; no no-slip velocity is assigned.

There are no invented trajectories or on-contact bumper impulses. A future
powered bumper must have a finite supply, a contact sensor, a physical moving
ring/rod and a return spring. Repeated commercial scoring, drop-target banks,
multiball storage, automatic ball return, solenoid internals and tilt detection
are not implemented by this starter. A lost ball is reloaded with Reset.

Electrical source, heat, shaft work and numerical coupling residuals are
recorded separately from the operator's native pull-work receipt and spring
energy. A circuit residual is not a full-system mechanical conservation proof;
the current contact/constraint dissipation is not a complete thermal ledger.
The qualification must not be described as that proof.

## Qualification — October 19

The six native Pinball checks cover compilation of all eight tools, bounded
controls, actual switch contact, powered motion and spring return, zero-charge
negative controls, launcher/material comparisons, ball/flipper contact and
abandoned-input expiry. Ordinary browser play covers 1280×860, 390×844 and
844×390, including independent flippers, simultaneous touch, keyboard input,
holding the physical button, launch/release, Pause, Reset and saved identity.

At 1/480 and 1/960 s with identical initial geometry, glass, oak and iron all
receive spring work through contact. The launcher stores about 16.17 J after
a 0.5 s hold; the operator-work receipt is about 34 J, which also includes
losses and work elsewhere in the pull cycle. Later bounce sequences differ
with material and timestep. This is a reach/contact qualification, not a
trajectory-convergence or full-energy certification.

The charged flipper reaches its native 55° stop and returns within 4° after
release; the zero-charge control stays within 3°. A separate near-paddle
fixture observes native ball contact and more than 15 cm of up-table travel;
the same unpowered apparatus travels less than 3 cm. Electrical accounting is
checked within 1e-8 J. Electrical/shaft coupling residuals are recorded
separately and are not hidden in that electrical tolerance.

The final fixture moves the ball 0.391 m when powered and 0 m with an empty
supply. Its electrical residual is 1.97e-11 J and shaft-coupling residual is
0.0254 J on 170.414 J of source work. The iron launch reaches 2.404/2.272 m
up-table travel at the two timesteps. The six checks complete in 60.868 s;
the three-viewport browser case completes in 12.619 s. Its short live runs
advance 2.97/2.15/2.17 simulated seconds using 2.62/1.83/1.84 s of native
compute, with no recorded scheduling backlog. This is a local measurement,
not a guarantee for all phones or the hosted CPU. The native rigid/contact,
rolling-loss and precise-shape regression targets also pass.

## Training sequence after the workshop is qualified

Each lesson should expose only its essential controls, start with a visible
target, include an introductory GO overlay, and qualify its own solution in
three nudged runs with a physical negative control. Keep the completed parts
between lessons in a saved Pinball blueprint; introduce depth only after the
player understands the two-axis surface.

| Lesson | Player builds or changes | Observable goal |
| --- | --- | --- |
| 1. Let gravity play | Place a smooth ball on the angled deck | Roll through a marked lane into a catcher. |
| 2. Keep it on the table | Add solid rails and a clear guard | Reach the catcher without leaving the surface. |
| 3. Build the spring launch | Add a guide, rod and spring | Hold, release and reach an upper marker through contact. |
| 4. Guide the return | Place a launch turn and inlane rail | Route a ball from the launch lane toward a paddle tip. |
| 5. Make a returning paddle | Add a bearing, paddle and return spring | Operate it by hand and observe its return; no electricity yet. |
| 6. Close a real contact | Add a momentary button, supply and indicator | Hold the button to light the lamp; release opens the circuit. |
| 7. Power the first flipper | Wire the contact and actuator with both leads | Hit an approaching ball into a visible target during Run. |
| 8. Two independent flippers | Add a second parallel loop | Operate either paddle without powering the other. |
| 9. Add bumpers and targets | Position passive bumpers and hanging targets | Hit a target, with no hidden energy source in the bumper. |
| 10. Your own table | Assemble and save a complete layout | Qualify a launch, a controlled return and a drain; share a run-only copy. |

Advanced extensions should teach RC-driven pulse timing, energy-limited
solenoids and a physical ball elevator only after those mechanisms have their
own engine qualification. The existing one-pass wall cradle is not an endless
pinball ball-return mechanism.
