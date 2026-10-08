# Shared native drop world — October 8, 2026

## Implementation stage, not physical qualification

This checkpoint connects the existing `PlatformWorld` / `NetworkWorld` native
pipeline to a live 3D drop scene. It does not replace the independent serial
double sheet reference, rewrite its failed affine contact stencil, complete the
Rust player-world migration or qualify a continuum material model.

`drop.html` → bounded `/api/drop` intentions → persistent
`banjo_drop_world_run --serve` → one `PlatformWorld` → native Jolt motion,
contact and axial material networks → timestamped actual instances → WebGL.
The ordinary World and sheet reference link to this scene. It is a connected
3D test world, not an installed change to the saved gameplay world.

Both ball and sheet can remain deformable cell networks. Every cell, both
posts and the floor share one native clock and contact owner. Connected bonds
carry the existing axial constitutive response; detached bodies remain in Jolt
with gravity/contact. There are no precut fragments, scripted launch velocities,
position corrections or prerecorded outcomes. The rigid baseline uses the same
world owner with four intact bodies and no internal material response.

## Declared experiment

- Sheet: 240 × 80 × 240 mm; 6 × 2 × 6 = 72 represented material cells.
- Ball: 32 occupied cells of a 4 × 4 × 4 ellipsoid grid. Diameter follows
  requested mass / catalog density / occupied-volume fraction 0.5. The rigid
  baseline uses a sphere and its true sphere volume instead.
- Ball mass: 0.1–5 kg; initial surface clearance: 0–10 m; x offset ±80 mm.
- Initial downward speed: 0–15 m/s, explicitly declared. The UI offers 0 and
  14 m/s. Contact + 14 m/s is a shortened initial-value impact experiment,
  **not a simulation of the preceding 10 m fall**.
- Gravity: −9.81 m/s²; native solver: 96 velocity / 4 position iterations.
- Deformable host interval: 1/4800 s, further divided onto the unchanged
  0.2-radian network stability clock. Rigid baseline: 1/240 s.
- Two free iron posts: 60 × 500 × 300 mm. Their native contacts carry the
  specimen; they can move/tip. Their internal fracture is unsupported.
- Bounded position admission expands from ±10 to ±30 m to admit actual
  10 m surface clearance above the raised specimen.

Visible spheres are the actual cell collision proxies. Their radii are 0.49
times the smallest represented cell spacing. Represented material volume
determines mass/inertia; **the gaps are real limitations of this proxy model**,
not air compression. No smooth skin hides a different collision shape here.

Catalog properties map to an experimental isotropic axial network. Glass,
ceramic, ice and concrete use the existing brittle branch. Materials with
yield use axial plasticity without fracture: this engine rejects combining
plasticity and fracture. Oak remains a laboratory comparison, with no grain
claim; rubber has no hyperelastic law. Different display names do not supply
missing laws.

## Sampled trajectories and rendering

Each accepted **host tick** produces position, quaternion, linear/angular
velocity, material, object/element/component IDs and collision geometry for
every body. A batch contains up to four timestamped frames plus its final
material/contact/performance report. The final frame equals the final native
state. Internal stability substeps are not individually exported; these are
sampled trajectories, not a complete microstep trace.

The renderer draws the latest actual state, independently of the simulation's
wall time. It does not invent intermediate motion. Logs retain declarations,
all delivered frames, actual receipts and executable SHA256 in
`build/drop-world-logs`. Download exports the browser's observed receipt history.
Native solving currently uses one worker configuration; simultaneous object
interaction does not imply parallel CPU/GPU material solving or real-time speed.

The gateway shares session limits, subprocess lifetime, request validation and
receipt persistence with the original sheet manager. Eight sessions maximum,
180 s inactivity, 12,000 host ticks/world, 15 s/request deadline. UI pause waits
for the active bounded batch. A refused material update pauses the UI and stays
visible. Integration success is never promoted to `release_ready:true`.
Closing an expired session is idempotent, so Prepare/reset also recovers after
server restart or inactivity expiry; advancing an expired session stays refused.

## Measured Windows evidence

MSVC Release / Windows 10.0.26200; native binary SHA256
`32dafc5d89841bdbff73bf4c439dd5ac46f0fcf8b918846f10db0e95bd7de39f`.
Clean-impact regression checks every initial ball/sheet cell pair for nonpenetration.
An early unpublished setup placed the ball 20 mm too low; those fracture results
and screenshot are superseded by the corrected run below.

Detailed [native measurements](evidence/material-lab/shared-drop-results-20261008.json).
Four registered scoped CTest entries pass in 27.52 s, including native drop
integration, existing sheet gateway, network material and spring oracles.
Source registration: 323/323. TypeScript build, JavaScript syntax, Python compile
and HTTP test catalog admission checks pass. The named drop check also runs
through the HTTP gateway and returns a complete result with the native binary
fingerprint (one integration test, 27.703 s). Browser verification caught an
undefined suffix variable in this new runner entry; it was corrected and this
end-to-end regression added before publishing. These are scoped checks, not full
regression, material qualification or physical-phone acceptance.

Same 1 kg iron ball / 14 m/s contact / centre / gravity / 4 host ticks =
0.833333 ms, with density-dependent ball volume unchanged:

| Sheet | Mass kg | Pair frequency rad/s | Sheet bonds broken | Sheet plastic work J | Ball plastic work J | Unseparated energy change J | Wall s |
|---|---:|---:|---:|---:|---:|---:|---:|
| Glass | 11.520 | 76376 | 44 | 0 | 46.5046 | −30.9586 | 4.104 |
| Oak | 3.2256 | 59761 | 0 | 5.5818 | 11.4060 | −47.5800 | 4.295 |
| Iron | 36.26496 | 74737 | 0 | 0 | 57.3937 | −28.8346 | 4.156 |

Three matched gravity-only controls (initial speed zero) retain zero broken
bonds and plastic work below 1e−6 J. Their unseparated energy changes span
−5.02e−7 to −5.70e−8 J. A separate iron-sheet/glass-ball impact breaks **124
ball bonds into seven components**, retaining all 106 bodies and their masses, in 2.378 s wall.
This confirms the source ball participates in the axial model; it is not a
calibrated glass-ball breakage or energy-conservation result.

The complete 10 m **rigid baseline** reaches sheet contact, changes the ball's
free-fall velocity, preserves mass and advances to 1.6 s in 0.255 s native wall.
Its unseparated energy change is −46.9646 J. Contact/support/internal damping
and numerical work are not fully separated in this network path; therefore
`energy_residual_j` stays null. The table's signed energy changes are **not
conservation residuals or certified physical losses**. Full linear/angular
momentum transfers with gravity/support/contact remain unaudited here.

The former 1/240 s deformable trial needed 13,830 substeps, exceeded the 8,192
budget and took 43.42 s for four ticks. The admitted 1/4800 s experiment fits
the budget (692 substeps for the iron ball case). This change restores the
stability bound; it is not a speedup or contact/wave accuracy proof. A complete
10 m deformable fall remains too slow for interactive use.

## Next integrated stages and gates

1. Profile the native cell/contact/constraint hot loop. Qualify CPU reference
   optimizations against actual state/history/conservation and wall time before
   considering parallel CPU/GPU solving. Keep short live impacts usable.
2. Replace gapped cell proxies and uncoupled intrinsic spin with a finite-volume
   connector/contact representation that preserves reactions and torques after
   fracture. Test grazing/edge/fragment/post/floor contacts in this same scene.
3. Separate gravity/support/contact/internal damping/plastic/fracture/numerical
   accounts; close full E/P/L transfer tolerances. Refine time and cell resolution.
4. Verify visible unloading dents, through-openings and debris settling with
   glass/oak/iron under identical declared conditions; keep unsupported laws
   refused. A broken-bond count alone is not a visible crack or hole.
5. Qualify a usable complete deformable 10 m drop, then import the same runtime
   through the Rust player-world owner. Retire older paths only after parity.

[Actual browser observation](evidence/material-lab/shared-drop-glass-ball-20261008.png)
shows the corrected glass-ball experiment. Browser UI, native API and saved
receipts agree; the normal interactive drag/orbit, reset, one-batch and pause
controls were exercised.

Physical qualification and the complete free-form world objective remain open.
