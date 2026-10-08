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

Six focused CTests pass in 8.37 s: block minimizer, rigid work, native face/contact,
actual gateway, bounded pipeline and playback. The reference glass/oak/iron/ice
physical/work fields match the previous published executable at every 16 host
ticks through 2 s (only profiler/timing and the separately checked contact-label
field excluded). No reference accuracy claim follows from parity.

Full final-build drops are still being measured. The initial implementation
build completes all four iron-ball sheet cases; the browser glass-ball case passes
the previous 1.470365 s energy refusal but stops at 1.972 s on an archive limit.
That is a delivery failure, not a physics gate result or a completed drop.

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
The complete ordinary-browser drop with this repair is being verified.

## Build and evidence

Implementation revision: local verification in progress; publication recorded
after the checked source commit. Final native SHA256:
`a99ebdde07748148f36537225457ba76087a59a894518fffe1ea86f3826ac2e1`.
Output: `build/voxel-coupled-friction-final/Release/banjo_voxel_world_run.exe`;
CMake tree `build/voxel-contact-audit`.

Initial implementation SHA256:
`40b2b2828b8ebdb2cc56b5dd893ec233cfae032797ba0f50b5a6dc035e195b85`.
The final build adds overflow-input refusal and stronger native/analytical tests;
bounded-world physical equations are unchanged. Its independent comparisons are
in progress; no completed initial experiment is represented as final-build proof.

Evidence files: `build/voxel-coupled-friction-{build,oracle-detail,baseline,comparison}.log`
and `build/voxel-coupled-friction-final-{build,ctest,comparison,server}.log`.

Next: finish the final-build material/browser experiments, quantify full signed
energy/momentum and remaining normal/island errors, then reduce measured solve
cost. The original five goals remain active.
