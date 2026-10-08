# Coupled sliding and twisting contact — October 8, 2026

## Implementation and scope

The native CPU lab now has an explicit `midpoint-block-friction` contact model.
The website calls it **Coupled friction · experimental** and selects the matching
centered interface/integration model. The material-restitution reference remains
the default. Existing geometry, constitutive laws, normal rows, impulse caps,
velocity limits and energy refusal bounds are retained.

At each frozen contact patch, the new block minimizes
`0.5 p^T K p + q^T p`, with `K = J M^-1 J^T`, over the existing tangent impulse
disk times the twisting impulse interval. The unknowns are
`p = (lambda_t1, lambda_t2, lambda_twist / L)` in N s; the gradient is
`(slip_t1, slip_t2, L * relative_spin)` in m/s. `L` is the maximum native
contact-patch radius (a dummy 1 m scale for the inactive one-point twist row).
Native inverse masses, world inertias, lever arms and motion types generate the
complete symmetric 3 by 3 matrix, including off-diagonal coupling.

The double CPU minimizer enumerates interior/lower/upper twisting active sets.
An interior twist is eliminated with a Schur complement; each resulting tangent
disk problem has a bounded multiplier bisection. Nonfinite/indefinite or
overflowing mass inputs refuse. No regularization, artificial damping, fragment
launch or prescribed velocity is introduced. The result is applied through the
existing native accumulated-impulse methods, once per contact block.

Pinned dependency sources are unchanged. `cmake/JoltFrictionBlock.cmake` generates
a shared build-local overlay with guarded native markers. `banjo_friction_block`
is a compiled library linked to both the core and Jolt; source registration is
333/333 with no exclusions.

This is a local friction block, not a simultaneous normal/island solve. Native
normal rows still execute afterward and other contacts/interfaces can change
the final slip. Full energy, momentum, spatial/timestep convergence and material
calibration remain open. Metals remain elastic; permanent dents and tearing,
adaptive cells and validated arbitrary authoring remain unfinished.

## Verification so far

Windows MSVC 2022 Release, precise CPU floating-point profile; headless native
tests and the ordinary 3D browser control loop. No cross-OS/GPU, phone, full-repo
or material realism qualification is claimed.

128 analytical disk/interval combinations cover sticking, sliding, saturated
twist and coupled mass matrices. Variational stationarity, feasible caps,
nonpositive free kinetic work, tangent-basis swapping and invalid inputs pass.
Native centered torsion/sliding controls are retained; the new mode additionally
runs them for glass, oak and iron in both inline and thread-pool execution.

A yawed 150 by 100 by 80 mm body on an offset 60 mm support patch tests actual
anisotropic tangent/twist coupling, with coefficient 0.4, no gravity, h=1/960 s
and 96 velocity iterations. Glass/oak/iron final variational gaps are respectively
4.0603e-8 / 1.13688e-8 / 1.27818e-7 J; friction work is
-1.72328 / -0.482519 / -5.42489 J. Both CPU runners reproduce these values.
The retained 5e-6 J controlled native bound is unchanged.

Six focused CTests pass in 7.74 s at the final publication check (initial 8.37 s): block minimizer, rigid work, native face/contact,
actual gateway, bounded pipeline and playback. The initial implementation reference glass/oak/iron/ice
physical/work fields match the previous published executable at every 16 host
ticks through 2 s (only profiler/timing and the separately checked contact-label
field excluded). No reference accuracy claim follows from parity.

All five final-build drops finish at 2 s. The previous glass-ball energy refusal
at 1.470365 s is absent in this declared experiment. The final measured physical/
work records match the initial implementation exactly, excluding profiler/timing.
This is a repaired benchmark failure, not general conservation or fracture accuracy.

Matched conditions: 400 by 400 by 4 mm sheet, 8 by 8 cells, 320 mm support gap,
1 kg ball dropped from 10 m, h=1/960 s host step with unchanged adaptive rejection,
96 velocity iterations. Sheet density/E: glass 2500 kg/m3 / 70 GPa; oak
700 / 12 GPa; iron 7870 / 211 GPa; ice 917 / 9 GPa. Sheet masses respectively
1.6 / 0.448 / 5.0368 / 0.58688 kg. Glass/ice permit brittle interface failure;
oak/iron retain their elastic-only laws. Ball geometry is the original 32-cell
cube approximation, not a new tetrahedral sphere.

| Sheet / ball | Wall s | Accepted substeps | Sheet / ball components | Max sliding / twist gap J | Legacy energy-ledger change J |
|---|---:|---:|---:|---:|---:|
| glass / iron | 167.99 | 90041 | 25 / 1 | 0.000185353 / 2.07684e-05 | -64.834357 |
| oak / iron | 71.06 | 25840 | 1 / 1 | 4.63064e-06 / 3.17306e-06 | -43.016985 |
| iron / iron | 114.33 | 29826 | 1 / 1 | 0.000249364 / 3.8833e-06 | -61.647994 |
| ice / iron | 118.35 | 72965 | 64 / 1 | 0.00013987 / 1.76711e-06 | -6.093648 |
| glass / glass | 176.79 | 96244 | 34 / 19 | 0.00935586 / 0.000336839 | -80.187843 |

Wall times include concurrent local verification jobs; this is no speed qualification
or isolated performance comparison. Substep counts are native measurements.
The 1 kg glass ball now separates into 19 components; its sheet has 34. Cracks
follow the cell interfaces; no resolution-independent shard distribution is claimed.

### Where the glass-ball energy goes

The common-phase kinetic ledger measures contact work -72.186657 J, spring work
-27.046630 J, numerical spin-limit work -0.198178 J, solver residual -0.000330 J,
gyroscopic kick +0.023606 J, other force work +0.045734 J and rotation drift
-0.016310 J. Gravity does +105.815770 J work; kinetic energy increases 6.437005 J
and gravitational potential falls 105.787504 J. The elastic/fracture/discarded-
elastic accounting increases 19.162656 J, giving the legacy ledger change
-80.187843 J. These signed arithmetic identities pass the retained 1e-7 J bound;
small closure is not a physical conservation pass.

Declared spring damping is 17.024567 J; the older spring-work residual is
+9.131000 J and geometry change +0.009571 J. Fracture work is 0.304299 J while
18.857865 J of surplus spring energy is discarded at interface removal. That
surplus is a numerical/model limitation, not fracture heat. Spin clipping occurs
31 times. Permanent metal plastic work is still unsupported.

Boundary diagnostics use pre-force/solver velocity averages and report normal
-11.130835 J, sliding -54.326652 J and twist -6.701736 J. The kinetic ledger uses
post-force/solver averages; their contact-operator difference is -0.027434 J.
The audit explicitly keeps these operators distinct rather than forcing their
sums equal. Contact normal complementarity error reaches 0.048818 J, final
sliding/twist gaps remain nonzero and some final impulse caps are exceeded after
later rows. Hard speculative contact loss, coupled normal/island convergence,
force/pose consistency, fracture overshoot and rotational corrections remain
accuracy work; these losses are not all classified as physical material heat.

Full glass-ball angular residual is (6.51265e-5, -4.84510e-5, -4.97622e-4) N m s;
linear residual is (1.79943e-6, -4.37061e-3, 4.78692e-6) N s. Their physical
admission and timestep/spatial refinement gates remain open.

## Lossless journal repair

Repeated full records exhausted the existing storage bound in the ordinary
glass-ball browser run. Archives now store exact structural replacements against
the previous record, then gzip them. IEEE signed zero and JSON value types are
retained; numeric deltas are not subtracted/rounded. Downloads reconstruct the
original NDJSON one row at a time. Manual/stream commands, every published state
and provenance remain available. The existing 32 MB compressed / 256 MB encoded
storage bounds remain; one prior record is retained in memory.

The regression streams 303 MB of repeated decoded history within the storage
bounds, verifies every record and exercises type changes, signed zero, removals
and array resizing. Native direct/stream parity and pause checks still pass.
The ordinary browser now completes the same glass-ball drop at 2 s, with
34 sheet / 19 ball components, 69 sheet / 45 ball broken interfaces and 96,244
accepted substeps. Its 1,661 downloaded records retain all 1,920 native host ticks;
final object/work/contact/boundary and nontiming diagnostics match the final CLI
run exactly. Download size is 99,376,847 decoded bytes; the stored archive is
about 26.92 MB compressed. No browser errors/warnings occurred.

Browser input verification also exposed a collapsed inspection drawer covering
Before/Live controls at 1280 by 720. The drawer now stays at the right; ordinary
mouse clicks are checked separately from the completed impact. Historical private
captures carry the source/build warning that was accurate at their load time;
the published public-lab capture reports its clean running checkpoint.

## Build and evidence

Implementation revision: `7371898757c47f6c02d6a9eb5389f156c4c382e9`; published to main with the checkpoint metadata. Final native SHA256:
`a99ebdde07748148f36537225457ba76087a59a894518fffe1ea86f3826ac2e1`.
Output: `build/voxel-coupled-friction-final/Release/banjo_voxel_world_run.exe`;
CMake tree `build/voxel-contact-audit`.

Initial implementation SHA256:
`40b2b2828b8ebdb2cc56b5dd893ec233cfae032797ba0f50b5a6dc035e195b85`.
The final build adds overflow-input refusal and stronger native/analytical tests;
bounded-world physical equations are unchanged. All five final-build comparisons are independently complete; final measured
physical/work records match the initial build with only timing/profiler excluded.

Evidence files: `build/voxel-coupled-friction-{build,oracle-detail,baseline,comparison,loss-verification,browser-verification}.log`
and `build/voxel-coupled-friction-final-{build,ctest,publish-ctest,comparison,server}.log`.
Browser artifacts: `build/voxel-coupled-friction-browser-{before,after}.png`,
`build/voxel-coupled-friction-browser-record.jsonl` and its final native snapshot.

Next: resolve normal/island convergence, force/pose work consistency and
fracture-energy overshoot, qualify timestep/spatial refinement, then reduce
measured active solve cost. The original five goals remain active.
