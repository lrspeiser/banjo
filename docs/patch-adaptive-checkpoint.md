# Adaptive distributed patch advances

Local source `e3f53bf6a737d1d79ac3aed3cb4e7b0d603a5faf`, September 5, 2026; not pushed or merged. Full goal remains active.

The single-site adaptive controller is now shared with `advanceCohesivePatchAdaptive`. A patch advance compares full-step and two-half-step body states and every site's opening/maximum-opening history. It accepts only complete candidates within the requested accumulated absolute energy-error budget. Rejected trials do not publish any body or history state. Previously damaged sites remain irreversible when a completed state is continued.

The shared controller preserves the preceding duration, tolerance, depth and evaluation limits: duration at most one second, state tolerance at most 0.1, positive energy budget, maximum 65536 evaluations and depth 24. Each patch evaluation visits up to 256 sites, so evaluation count alone is not a wall-time guarantee. Only typed timestep-screening failures trigger subdivision. Other invalid/unsupported states and exhausted work budgets reject. The local tolerance floor and strict global energy cap are unchanged from the [single-site controller](cohesive-adaptive-checkpoint.md).

State scaling uses total geometric patch area times Gc, mass and inertia. History disagreement is the maximum across corresponding fixed sites; no averaging hides a site's disagreement. The patch grid remains fixed during an advance. This does not implement spatial refinement, history interpolation or a rigorous global state-error estimate. Common law area is replaced by summed geometric site area for normalization and individual site area for constitutive responses.

## Comparative evidence

The tests use the preceding 64-site rectangular bending case at initial rotational energy 4*area*Gc, identical geometry for glass/oak/iron, and each material's established duration. Requested energy budgets are area*Gc times the tolerance below; state tolerance uses the same dimensionless value. Maximum evaluation count is 65536.

| Material | Tolerance | Evaluations | Accepted half steps | Accumulated absolute energy error, J | Final damage work, J |
|---|---:|---:|---:|---:|---:|
| Glass | 1e-4 | 169 | 78 | 3.91502e-9 | 9.83802e-5 |
| Glass | 1e-5 | 463 | 176 | 7.87715e-10 | 9.83785e-5 |
| Oak | 1e-4 | 181 | 82 | 4.39356e-7 | 0.0124255 |
| Oak | 1e-5 | 439 | 168 | 9.45119e-8 | 0.0124252 |
| Iron | 1e-4 | 193 | 86 | 4.91999e-5 | 1.67388 |
| Iron | 1e-5 | 475 | 180 | 5.70053e-6 | 1.67387 |

Both requested budgets pass for all materials; tighter controls reduce accumulated absolute energy error. Tests also compare final accounted energy to the requested budget plus 1e-12 J roundoff allowance, continue each tightly controlled damaged patch for half the original duration and verify every maximum-opening history is nondecreasing, and reject an advance limited to three evaluations. Fewer accepted steps than the fixed 2048-step case do not alone prove wall-time speedup; rejected trials and per-site cost remain part of the work.

Full Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass. Environment remains CMake 4.1.2/Core Ultra 9 285K. Reproduce with `banjo_cohesive_rigid_tests`. Existing single-site adaptive and fixed-grid tests remain passing after the shared-controller refactor. Logs are exported. The owned starter was intentionally stopped for relinking and restarted; no new native gameplay verification is claimed.

Temporal control now applies to the finite patch, but the nonmonotonic dynamic spatial comparisons remain unresolved. Both step estimates can miss sufficiently short events; this is not exact event localization. Next: compare spatial grids under common temporal budgets, improve sampling near damage fronts without healing history, and establish compression/contact ownership. Physical cutting, material calibration and all remaining goal gates stay open. All 40 scorecard rows are retained.
