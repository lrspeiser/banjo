# Matching contact and friction to centered motion

October 8, 2026. **Implemented experimental time operator; full accuracy and
speed remain OPEN.** This continues [centered integration](centered-integration-checkpoint.md)
and [small rotations](centered-rotation-checkpoint.md). It supplies no metal
plasticity, automatic spatial refinement, custom authoring or player-world migration.

## Actual failure and correction

A normal-only midpoint boundary experiment still refused the iron-ball/glass-sheet
impact at 1.427934265 s. Its rejected step had normal midpoint work -0.000505926 J,
linear friction work -0.001052409 J and twist work +0.009284203 J. The positive
twist term dominated contact work +0.007725868 J. These are measured native
impulses and actual pre/post-solve velocities, not an inferred heat budget.
The journal and screenshot are preserved in
`build/voxel-midpoint-boundary-browser-refusal.jsonl` and
`build/voxel-midpoint-boundary-before-friction-fix.png`.

Centered pose motion uses `(v0+v1)/2`. The pinned contact and friction rows target
endpoint velocities. A spring can reverse endpoint motion during the coupled
solve, leaving endpoint friction doing positive work at the trajectory midpoint.
The opt-in `contact_law: "midpoint-unilateral"` now matches all three rows:

- Frozen-normal separation: `g1 = g0 + h*(vn0+vn1)/2`. For initially separated
  surfaces the row enforces `vn1 + vn0 + 2*g0/h >= 0`, with nonnegative impulse.
  Initial overlap gets no energy-injecting position projection.
- Tangential friction targets the midpoint relative velocity under the original
  Coulomb impulse disk. Its bias includes the initial point velocity, including
  each body's angular lever arm. Surface motion retains its native sign convention.
- Twist friction uses initial plus final relative spin under the existing native
  torque bound. No prescribed spin, launch velocity, velocity rescaling or extra
  contact response is applied.

This is a **hard-boundary numerical model**, not compliant indentation or a
calibrated material restitution/damping law. At zero gap it can reverse closing
velocity while retaining kinetic energy. The fixed normal/tangent geometry,
friction iteration convergence, finite rotations and native float precision remain
limits. Initial spin remains an explicitly chosen experiment input.

Source: build-local `cmake/JoltForceObservation.cmake`, `src/rigid/JoltWorld.*`,
`src/platform/VoxelImpactWorld.cpp`. Fetched Jolt sources and reference force/pose
expressions remain unchanged. All consumers share generated ContactSettings
headers. The midpoint choice requires centered pose integration before creating
bodies; mismatched declarations refuse. Ordinary browser selection visibly chooses
the matching interface solver. The new diagnostics separate normal/friction/twist
midpoint work and retain complementarity/velocity errors, including rejected trials.

## Controlled comparative regression

Windows x64, MSVC Release CPU, Jolt 5.6.0; global continuous-rotation option OFF.
Glass/oak/iron 0.1 m cubes retain catalog density 2500/700/7870 kg/m3 and material
mass 2.5/0.7/7.87 kg before float conversion. The contact oracles use zero gravity,
friction 0 for normal tests or 0.4 for coupled direction reversals; no rolling drag.
These are analytical interface experiments, not material stiffness/realism claims.

The 96 new normal-contact runs cover two CPU runners, all three materials,
free/free and anchored/free bodies, four gap fractions and h=1/960 or 1/3840 s.
Max measured nominal-gap error is 4.47035e-9 m, velocity error 2.30372e-5 m/s,
analytical energy error 9.0532e-5 J, impulse-account error 4.23722e-5 N s and
work-account error 6.35585e-5 J. New bounds derive from float contact-coordinate
precision divided by h and float accumulated momentum/work scale: gap bound
`8*epsilon_float*0.1 m`, velocity `2*gap_bound/h`, momentum
`32*epsilon_float*mass*(1+closing_speed)` in this SI fixture. Work and torque bounds
use the corresponding velocity/lever-arm scales. No earlier oracle or world energy
gate was relaxed. Rollback, reaction, actual torque and configuration refusal are tested.

The 24 added coupled controls/corrections use the same cube geometry, h=1/240 s,
zero gravity, 1 m/s normal approach, and either 1 rad/s twist or 1 m/s tangential
motion. All use declared analytical torsion 10,000 N m/rad; sliding additionally
uses 10,000,000 N/m tangential stiffness. Unused positive axes have stiffness 1
in their SI units. The endpoint controls retain positive coupled-energy changes:

| Material | Endpoint twist gain J | Matched twist change J | Endpoint sliding gain J | Matched sliding change J |
|---|---:|---:|---:|---:|
| Glass | 0.0196202 | 1.88e-15 | 0.0653572 | -0.0653555 |
| Oak | 0.00491799 | 1.39e-10 | 0.00533156 | -0.00533266 |
| Iron | 0.0151452 | -7.82e-10 | 0.579835 | -0.579834 |

Both runners agree. Corrected energy is checked within 4e-7 J for the coupled
part and 5e-6 J for the full fixture; original controls are explicitly expected
to retain their energy defect. All retained earlier face/force/contact/spin tests
pass. A passing isolated regression does not qualify the full impact world.

## Full-world comparison and remaining failure

All five diagnostic runs retain original cell IDs and masses, finite states,
unchanged depth-14/per-step and 0.1 J cumulative gates, and exact accepted state
on refusal. Conditions: 40 x 40 cm, 4 mm, 8 x 8 / 64-cell sheet; 32 cm support
gap; 1 kg constituent ball dropped 10 m; host h=1/960 s, 96 velocity iterations.
Glass/oak/iron/ice sheet masses 1.6/0.448/5.0368/0.58688 kg and moduli
70/12/211/9 GPa are retained. Oak is an elastic laboratory comparison without
grain/organic gameplay. Iron has no permanent yield/dents/tearing.

| Sheet / ball | Physical s | Wall s | Substeps | Sheet / ball pieces | Unclosed E J | Declared damping J | P residual N s | L residual N m s | Result |
|---|---:|---:|---:|---|---:|---:|---:|---:|---|
| glass / iron | 2.000000000 | 124.272 | 68311 | 23 / 1 | -46.297776 | 23.819813 | 0.002719886 | 0.018292384 | Complete, unqualified |
| oak / iron | 2.000000000 | 61.743 | 25715 | 1 / 1 | -42.845356 | 25.409467 | 0.002140905 | 0.000135754 | Complete, unqualified |
| iron / iron | 2.000000000 | 76.232 | 30086 | 1 / 1 | -64.249153 | 54.303110 | 0.002692408 | 0.000487876 | Complete, unqualified |
| ice / iron | 2.000000000 | 82.092 | 75292 | 64 / 1 | -18.353908 | 15.310608 | 0.003136325 | 0.030641505 | Complete, unqualified |
| glass / glass | 1.470365397 | 59.907 | 26503 | 15 / 20 | -44.273274 | 13.733975 | 0.003579822 | 0.000530448 | REFUSED |

The timing batch shares this Windows host with verification. No useful speedup
or realtime qualification is claimed; reference physics still takes about 39 s
for two simulated seconds. The original reference model is still the default.
Four-material prior-executable comparison matches every physical and work record
at 16-host-tick intervals through two seconds (profiler fields and contact model
qualification label excluded). That is regression preservation, not accuracy.

The corrected glass-ball now fractures into 20 components before refusing at
1.470365397 s. At the rejected h=6.357828776e-8 s, contact work is +0.068094581 J:
normal midpoint work +1.160154e-7 J, friction -0.001576525 J and twist
+0.069670994 J. Maximum normal velocity violation is only 6.194256e-8 m/s.
Matching row timing removed one reproducible source, but the completed iterative
coupled contact solve still permits positive twist work. This must be resolved;
these gains and geometry terms are not material heat. Merely increasing render
fps, suppressing spin or widening an energy gate would not resolve it.

Complete glass/iron also retains accumulated positive normal-work samples
0.008774052 J and max normal complementarity work error 0.003512260 J.
Full P/L residuals and finite-geometry work remain unresolved. Large losses must
be separated into declared spring damping, actual Coulomb transfers, hard-contact
approximation and unexplained numerical terms; arithmetic closure is not proof.

## Verification and next work

Compiled source registration: 331/331, no exclusions. Five focused CTests pass
(native face/work, actual gateway, bounded pipeline and playback). Full five-material
comparison and four-material prior-binary parity are separately recorded. The
preceding normal-only candidate's nine scoped tests pass reporting/refusal gates;
those results do not certify this final friction candidate or physical accuracy.
No full-repository, physical-phone, other-OS or cross-GPU validation is claimed.

Verified native SHA256:
`6f401bd9831596f45957885264e5b07ce6ba6df9b357e87eaddf13d8494c3c16`.
Build directory `build/voxel-contact-audit`; final native output
`build/voxel-midpoint-friction/Release/banjo_voxel_world_run.exe`.
Evidence: `build/voxel-midpoint-friction-{build,oracles,comparison,baseline}.log`,
`build/voxel-midpoint-friction-focused-ctest.log`, and
`build/voxel-midpoint-friction-browser-complete.png`. Current source revision and
live website promotion are pinned in the checkpoint manifest after publication.

Next: measure tangential/twist complementarity and convergence in the coupled
contact island, qualify compliant surface potential/damping and finite-geometry
work, then reduce global substeps/solve cost. Preserve the original glass-ball
refusal while testing iteration/timestep/spatial refinement and complete P/L/E.
Persistent metal history, adaptive cell mass/history transfer and validated custom
material/geometry authoring remain required. The five-part goal stays active.
