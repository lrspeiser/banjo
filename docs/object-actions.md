# Object actions

October 19, 2026. Sandbox makers and the word builder now share `object_action`,
a saved catalogue binding to a real moving hinged/sliding handle. It gives the
player a held button and an optional keyboard shortcut. This is an operator
input, not a programmable script or an automatic event system. Ordinary levels
do not expose its editor. Pinball comes with its launcher and two flipper
buttons configured; teaching how to build bindings belongs in a later advanced
lesson. That lesson is not part of this checkpoint.

## Create, edit and place a button

Open **Design → Object actions · advanced**. Edit an existing action or choose
**Add object action** and select a moving handle. Alternatively, select an
eligible Sandbox object and choose **Actions** beside Move and Turn. Set:

- A player-facing label of 1–60 characters.
- An optional shortcut: arrows, Space, A/D/W/S/E/Q. Shortcuts must be distinct.
- Push direction in the handle's initial local axes and force from 1 to 120 N.
- **Auto**, **Beside object**, or **Bottom bar** for its screen location.

Auto uses the fixed bottom row for Pinball and an edge callout for other
machines. Beside object always uses the edge callout with a thin leader to the
moving handle; the layout avoids apparatus and other controls where space
permits. Bottom bar stays fixed while the camera moves. More than three docked
actions use pages, with two per page on narrow screens and three on desktop.
Run enables the held inputs; Build hides them. Pause, blur, release and pointer
cancellation let go. An abandoned input also expires on the server after one
second. Scene handles and shortcuts operate the same input regardless of where
its button appears.

Save action is an ordinary Undo/Redo edit. Reset retains the edited setup;
saved designs, versions and run-only course copies retain the binding. A custom
binding on a prepared handle replaces its ready-made action. **Restore ready-made
action** removes that override; other bindings offer **Remove custom action**.
Deleting a placed handle also removes its dependent binding. Assembly references
renumber when copied, while force stays in the handle's initial axes. A copied
action with an already-used shortcut becomes an on-screen button, with a notice;
edit Object actions to give it another key. One binding per handle, twelve
effective bindings per machine; invalid targets, labels, keys, locations and
forces are refused by the shared compiler.

## Physical meaning

The button supplies a bounded external hand force at the body's centre of mass.
The saved adapter's vector is rotated from the handle's initial axes into the
world during compilation. It remains a fixed world direction during the run;
it is not a force that follows the body's later rotation. The existing native
pull-work receipt records operator work. No angle, velocity, contact state or
motor output is assigned by the action.

A powered flipper still needs a physical switch, both electrical paths, a
finite supply and a coupled motor. Pushing a hinged body at its centre is not
a general torque actuator; a handle offset from its hinge is needed to turn
it. Springs, joints and DC actuators retain their existing lumped/ideal models.
This does not add internal actuators, resolved muscle/solenoid physics, arbitrary
automation, latch programming or a new constitutive law.

## Word builder

The existing structured add/edit operations accept `object_action`. The builder
receives eligible handles and current bindings in `environment.action_targets`.
It supplies `part`, `label`, `key`, `location` (`auto`, `object`, `dock`) and
`push_x_n`, `push_y_n`, `push_z_n`. Added-tool aliases resolve through the same
reference system as wires: a `pinball_button` with ID `press` exposes
`press button`. Human edits and word proposals use the same composition and
compiler checks. API replies list manual inputs separately. Ordinary builder
rehearsals do **not** press these inputs, and must not be presented as proof
that an interactive sequence succeeded. A mocked structured-model fixture
qualifies the catalogue contract, not arbitrary live-model reliability.

## Qualification

At 20 mm cells and 1/480 s, identical glass, oak and iron push handles drive the
same aluminum contact cap with a 30 N downward action: settle 0.3 s, hold 0.5 s,
release 0.7 s. Insulating handles do not become conducting contacts. The powered
flipper reaches 55.215°, 55.371° and 55.371°, then returns to −0.290°, −0.085°
and −0.085°. Source work is 131.218, 142.368 and 109.330 J; recorded operator
work is 2.859, 2.903 and 1.347 J. The electrical residual is at most 1.67e-11 J;
separate shaft-coupling residuals are 0.0341–0.0351 J. These are subsystem
receipts, not a full mechanical/thermal conservation proof.

With an empty supply, the same iron handle closes the contact but the flipper
stays within 0.002° of rest. An upward action leaves the contact open and the
flipper at rest. All three material positives and both physical negatives run
on Windows and Linux. Existing Pinball tests retain the two-timestep launcher,
flipper, contact, expiry and side-guide comparisons.

HTTP regressions cover the shared validation and staging path. Ordinary browser
tests at 1280×860, 390×844 and 844×390 create/edit a binding, save/reload it,
Undo/Redo, switch edge/dock location, operate its real wired button by keyboard,
restore the prepared action and confirm that ordinary lessons hide the editor.
The edge button must be inside the scene, near an edge, at least 44 px in each
dimension, with its leader visible. The independent starter test retains
simultaneous touch, scene input, launch/release, Pause, Reset and saved versions.

Local checkpoint: all 12 native Pinball/action checks pass on Windows in
140.617 s; the Linux 12-check run passes in 104.186 s, followed by the five
action checks after adding screen-location metadata (7.442 s). HTTP passes
46 checks in 9.704 s. The editor/starter/batch browser run passes three cases
in 37.603 s; complete physical-catalogue controls and library navigation pass
two cases in 85.460 s. The 121-check game run passed 119 cases, including all
64 solutions and their nudges, but two tray fixtures treated the new logical
binding as an unconnected solid. Those fixtures now exclude logical bindings,
whose handle/force validation is covered above. All 73 Tray/FreeBuild cases
pass after that correction in 61.036 s. No goal or physics tolerance changed.
