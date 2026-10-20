# Pinball workshop

October 19, 2026. **Sandbox → Pinball** creates an independent saved design.
The five existing showcase machines remain. The Pinball category in the piece
library contains eight reusable tools; the starter is assembled from them.
Build edits the setup, Run advances the native machine, and Reset reloads its
original setup. Saved versions, Undo and run-only course sharing use the normal
Sandbox paths. **Levels → Build a Pinball Machine** opens its ten-step
construction project; see the teaching sequence below.

## Flipper, drain and marble placement correction — October 19

New tables replace the solid 3.39 kg aluminum paddle with a 1.258 kg assembly:
a closed 3 mm box section, shaft and below-deck return crank. Its actual
material volumes determine mass and inertia. The bearing has a shaft opening
and an explicit fixing to a grounded mounting; the deck's shaft openings are
44 mm wide. Motor terminals face outward and leads clear the crank's sweep.
The return-spring anchor is below the deck, where a ball cannot lodge against
it. Drain guides join the outer rail or shooter-lane wall and slope toward the
open centre drain. The shooter path remains open.

The contact button's initial metal gap is now 7.5 mm instead of 57.5 mm.
In a paired-button trial at 1/480 s, physical contacts close within 40 ms and
both paddles reach at least 50° within 160 ms for three press/release cycles;
they return within the existing 4° tolerance after release. The previous
solid-paddle apparatus took about 281 ms to reach its stop. The battery is
not current-limited in this comparison: capacitors would not correct the
mechanical delay. Capacitors remain available elsewhere in the catalogue.
The stock actuator is still a lumped DC motor, not a resolved solenoid.

The ordinary Marble tool keeps its exact sphere. The general Sandbox
**Above / Below** controls choose between clear physical supports: choose
Below to reach the playfield from the glass. No Pinball-specific placement rule
or cover exclusion is used. Legacy `presentation.placement_inside` is ignored;
the cover remains unchanged in the compiled physical world. An explicit
At height placement is still respected. Native glass/oak/iron comparisons
check deck contact for a ball placed inside and glass contact for a ball placed
above. A visible edge outline makes the transparent cover easier to recognize.

Hardware changes apply to newly created tables; saved user geometry is kept.
Create another table with Sandbox → Pinball to use the new mechanism. Ordinary
Marble surface-layer controls work in both old and new Pinball designs.

The response and drain trials keep the existing 1e-8 J electrical residual
limit and report shaft-coupling residual separately. They do not establish
full-system mechanical/thermal conservation. Drain comparisons use identical
40 mm glass, oak and iron spheres at both 1/480 and 1/960 s behind either
paddle. A miss must physically leave through the drain, rather than stick or
be teleported back to the shooter. Automatic ball return remains unfinished.

On one CPU, three identical 3 s launcher/flipper trials take 2.930–2.952 s
of local compute. This is near real time locally, not a hosted-server guarantee.
An experimental exact electrical-trial cache changed the median by only 0.3%
and was not retained. It produced identical final pose hashes in that comparison.
No timestep, physics law, contact tolerance or update cadence was reduced.

Verification: all 16 native Pinball checks pass in 172.098 s, including six
inside/above-cover cases and twelve behind-paddle drains. Contact closes in
31.25 ms and both paddles reach 50° in 125 ms in all three cycles. At the end
of those cycles, the accumulated electrical residual is 4.65e-11 J and the
separate shaft-coupling residual is 0.63594 J on 239.12581 J of source work.
The latter is a measured numerical residual, not physical heat. All 73 tray
and free-build tests and 46 host tests pass in 59.940 and 9.534 s. Two browser
cases passed in 22.875 s before the contextual layer replacement, each at desktop
1280×860, portrait 390×844 and landscape 844×390; they covered Marble placement, Undo, independent held inputs,
spring launch, Pause, Reset and saved identity. Source registration remains
274/274. No new native force law was introduced.

October 19 side-lane correction: the guide opposite the shooter lane now
joins the outer rail upstream of the flipper (0.72 m at 55 degrees), directing
an edge-running ball into the paddle's reach. It extends into the fixed side
rail so its exposed end cannot wedge the ball against that rail, and ends
above the powered paddle's sweep. The shooter lane stays clear. New Pinball
designs use the corrected guide; saved bases remain unchanged. No ball
position, speed or contact impulse is assigned.

The return assembly is still missing. A complete replay loop needs a retained
drain trough, a repeatable elevator or powered ejector with a physical guide,
and a feed into the spring launcher's waiting position. A powered version
also needs a real held/contact switch, both supply leads and a finite energy
source. The existing one-pass wall cradle stops after a half-turn; it cannot
serve as a cycling ball return unchanged. Future qualification must recover
the same ball and launch it again over several cycles, with an empty-supply
negative control. Reset currently restores the initial setup instead.

## Play and controls

The prepared controls now use the shared [object-action framework](object-actions.md).
Keep them as supplied to play, or change their label, shortcut, force and screen
location under **Design → Object actions · advanced**. The ready-made flipper
controls now sit on the physical caps, and the shooter control follows the
launcher nearby. Custom bindings and the word builder use the same
catalogue tool. Building such inputs can be taught in an advanced lesson later;
no new training lesson is shipped here.

Choose Run. Hold **Pull launcher · release to shoot**, then release it.
Hold **Left flipper** or **Right flipper** to operate the physical buttons.
Left/Right arrow keys and Space provide the same held inputs. The physical
button caps and launcher can also be held in the 3D scene. Touch supports
separate simultaneous fingers. Release, pointer cancellation, lost capture,
window blur and Pause let go; the server expires an unrenewed force after one
second. Text inputs retain their ordinary keyboard behavior.

The opening camera faces the player end of the table from above, with the
named left paddle on screen left. Controls follow their handles as the camera
moves. Run gives the table more screen space and hides setup wiring labels;
Build restores them for inspection. The glass guard remains a physical collider
even though its transparent surface allows selecting the mechanisms beneath it.

## Components and their laws

| Tool | Construction and adjustments | Physical role |
| --- | --- | --- |
| Pinball playfield | 1.5 × 2.6 m oak deck at 5°, rails, drain, four legs, a clear guard and two bearing apertures; width and length | Gravity and contact carry the ball downhill. The drain is an opening, not a trigger teleport. |
| Smooth pinball | 40 mm iron sphere; diameter and glass/oak/iron material | Exact homogeneous sphere, density-derived mass, analytical spherical inertia, native friction and impact. It starts with zero imposed spin and velocity. |
| Pinball spring launcher | One rigid aluminum rod/nose in a slide, 400 N/m axial spring, 0.28 m draw and a retaining throat; spring stiffness | A bounded 120 N operator force draws the rod. Release removes that force; the spring pushes the ball through contact. No launch impulse is inserted. |
| Powered pinball flipper | Hollow aluminum paddle, shaft and below-deck crank on a fixed bearing, native hinge stops, coupled DC actuator and axial return spring; left/right, length, stall torque and return stiffness | Circuit current supplies torque, with back EMF and reaction on the bearing. Opening the switch removes power and the spring returns the paddle. |
| Spring-return button | Hinged aluminum contact cap, fixed iron output pad and compression return spring | Operator force closes actual metal contact. The flexible input attaches at the pivot so it does not have to follow a sliding cap. |
| Rubber pinball bumper | Passive spherical rubber fixture; radius | Contact can return existing impact energy. It has no hidden powered kick. |
| Pinball guide rail | Solid mounted rail; length and heading | The launch turn and inlane guides deflect the ball through contact and keep the flipper sweep clear. |
| Hanging pinball target | Aluminum plate on a bearing and a fixed iron support | A hit swings it; gravity returns it. Native contact stations observe hits. |

The starter includes a finite 24 V, 10 kJ supply with a 1 kW limit, two parallel
button/actuator loops and six 2.5 mm² copper leads. Each external terminal and
return path is explicit. Cables have the existing native mass, bending, gravity,
collision and terminal pullout. Their declared 200 N locking terminations and
below-deck service routes are part of the apparatus. Leads leave the bearing's
outer face, clear of the rotating return crank; shafts pass through actual deck holes.
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

Named contact events enter the player log only for explicitly watched
`touches` stations. Fragment-to-fragment observations must not evict the
ordinary impact events used by older machines. The archived Chain reaction
regression confirms all nine stages, including the falling weight hitting
glass at 21.779 s, after this reporting correction.

## Qualification — October 19

For the side-guide comparison, a ball begins at rest at table coordinates
x = -0.72 m, z = 0.35 m on the unchanged 5-degree oak surface. Glass, oak and
iron at both 1/480 and 1/960 s make native guide contact and cross z = -0.70 m
at x = -0.139 to -0.152 m after 2.50 s, within flipper reach. Six otherwise
identical old-guide controls cross at x = -0.720 m after 1.90 s, outside its
reach. The positive cases must keep moving rather
than wedge at the guide end. This is a routing comparison, not a full
mechanical energy or momentum conservation audit. The source and contact
laws are unchanged; the fixture uses gravity, without player force or
electrical source work. Its largest electrical residual is 1.65e-23 J.
Full paddle travel and spring return remain required. All seven native checks
pass on Windows in 98.821 s and Linux in 93.980 s, including the 12 side-lane
cases. The desktop, phone portrait and phone landscape live-control browser
check passes in 26.482 s. The supervisor's eight cohosting/recovery checks
also pass after integrating the production recovery release.

The original six native Pinball checks cover compilation of all eight tools, bounded
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

The clean full-game rerun passes all 120 checks in 629.137 s after the
contact-reporting correction. The Pinball test runner resolves its native
executable path before launching from a temporary directory; the Linux
package gate caught the relative-path portability error before publication.

## Ten-step construction project — October 19, 2026

The `pinball-01` through `pinball-10` lessons form a separate chapter after
the introductory physics chapters. The chooser also has a **Build a Pinball
Machine** card that resumes its first unfinished step. All lessons remain
available individually. Each has a GO introduction, an overhead table view,
scene controls limited to its task, a visible catcher, target or measured
goal, and ordinary native Run controls. These are subsystem construction
lessons: bearing/paddle/spring and launcher internals are assembled kits,
not a screw-by-screw manufacturing editor.

A win records that lesson's actual setup in the anonymous synced profile.
It creates or advances **My Pinball project** in Sandbox, with a labelled
saved version for each completed step. Guides, spring settings, button
position, paddle length and bumper adjustments are retained in the table.
Practice catchers are excluded. Later lessons use authored practice rigs;
they do not silently import arbitrary Sandbox edits into scored puzzles.
Players can open the cumulative project from the result, edit it using
normal Sandbox tools and share a run-only course. Replaying an earlier step
does not replace an already more advanced project.

| Lesson | Player builds or changes | Observable goal |
| --- | --- | --- |
| 1. Let gravity play | Place a smooth ball on the angled deck | Roll through a marked lane into a catcher. |
| 2. Keep it on the table | Add solid rails and a clear guard | Reach the catcher without leaving the surface. |
| 3. Build the spring launch | Add a guide, rod and spring | Hold, release and reach an upper marker through contact. |
| 4. Guide the return | Place a launch turn and inlane rail | Route a ball from the launch lane toward a paddle tip. |
| 5. Make a returning paddle | Add a bearing, paddle and return spring | Operate it by hand and observe its return; no electricity yet. |
| 6. Close a real contact | Add a momentary button, supply and indicator | Hold the button to light the lamp; release opens the circuit. |
| 7. Power the first flipper | Add the missing return lead to a prepared contact/actuator loop | Hit the ball into the visible green region during Run. |
| 8. Two independent flippers | Add a second parallel loop | Operate either paddle without powering the other. |
| 9. Add bumpers and targets | Position passive bumpers and hanging targets | Hit a target, with no hidden energy source in the bumper. |
| 10. Your own table | Load the accumulated table, then edit/share it in Sandbox | Reach the upper marker and then drain through the open bottom; Reset reloads. |

The indicator must first receive power and then go dark on release. The
paddle must first pass 40 degrees and then return within four degrees.
The parallel lesson checks each paddle raised while the other rests, in
sequence, and then the second return. Ordered station prerequisites only
observe engine measurements; they do not assign positions, velocities,
contact states or power. Reference tests schedule the same bounded held
actions used by the HTTP live controls in simulated time. They are never
supplied to a player's preview or Run.

The final layout includes a solid two-sided return gutter below its front
edge. It catches either front lane and slopes toward a central opening;
it does not teleport or elevate the ball. The short optional right inlane
guide is left out of this beginner layout because its junction can form a
resting pocket. Final qualification uses actual repeated flipper presses,
then releases them, rather than treating the table as an automatic machine.
The authored goal remains the upper marker followed by the original central
drain region within 25 seconds. The three reference/nudged trials reach it at
6.317, 6.600 and 8.967 seconds on Linux after closing the upper launch-turn
notch. Its rail now joins the outer wall (0.76 m rather than 0.60 m); a
marble can no longer lodge between its endpoint and that wall. These are reference play sequences, not measured human
completion times.

Training mountings explicitly fix stationary fixtures to the grounded table
frame. They are ideal rigid mounts, not resolved screws, brackets or stress
models. Moving paddle, button, rod and ball bodies remain dynamic. Guides
sit above the deck rather than penetrating it. The lesson's diamond-shaped
rubber deflector is a fixed voxel block; the workshop's older round bumpers
remain available separately. Springs, DC motors and cable models retain
the qualifications and limits above; no new native material law is added.

The native rolling check now prevents displacement-based sleep on a jointed
support while measured load and the existing material rolling threshold
predict continued motion. It does not assign velocity or apply another
contact response. On the same jointed oak deck at 0.2 degrees and 1/480 s,
glass and iron move 0.033818 m in three seconds; oak moves 0.000073 m and
remains below its rolling threshold. The reported rolling losses are
0.0000690 J, 0.0002172 J and 0.0000000293 J respectively; masses stay
unchanged. The existing rolling level, energy, ground slope, ramp, normal
force and valley checks pass, as do rigid component transfer and step-work
checks. This does not certify full Pinball momentum/energy conservation.
The separate circuit ledger remains checked to 1e-8 J; shaft coupling and
operator work retain their separate accounts.

Advanced extensions should teach RC-driven pulse timing, energy-limited
solenoids and a physical ball elevator only after those mechanisms have their
own engine qualification. The existing one-pass wall cradle is not an endless
pinball ball-return mechanism.
