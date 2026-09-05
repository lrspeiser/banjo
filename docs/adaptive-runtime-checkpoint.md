# Adaptive runtime assembly trials

Local sources `57102de` and `7229159`, September 5, 2026; not pushed or merged. Full goal active.

Version-2 Jolt assembly tests accept optional `adaptive` controls: `maximum_evaluations` (3..65536), `state_error_tolerance` (positive, at most 0.1), and `minimum_step_s` (positive, no greater than the initial half step). The original `steps` count defines initial intervals. Each interval is tried once as a full step, rolled back, then tried as two half steps. Only accepted fine results survive. Rejected runtime trials restore contacts/constraints and events through the reversible-trial API; the controller separately restores all interface histories, time, diagnostics and work accumulators. Evaluation costs and rejection counts never rewind.

The state metric compares body positions normalized by the largest declared dimension across both parts, relative linear/angular velocities with a 1 SI-unit floor, quaternion component distance modulo sign, and site opening/max-opening differences normalized by the separation opening. The requested tolerance controls a local full-versus-fine discrepancy, not a proven global state-error bound. Contact cache values are restored but are not directly included in this error norm.

Energy acceptance uses the remaining global budget for the sum of absolute accepted step-work residuals. It does not allow cancellation between positive and negative step errors. The budget is unchanged from the caller's specification. This avoids requiring float-scale work noise to fit a time-proportional allowance that approaches zero, but it can spend too much budget early and reject a later interval. Rejected trials do not debit the accepted error ledger. No impulse, stiffness or physical energy correction is introduced.

Recursion is bounded to 20 refinements; evaluation and minimum actual half-step limits reject exhausted trajectories. Steps must be exactly float-representable with finite float reciprocals. On any failure, the temporary world is discarded and the public command returns an error without a partial result or changes to the caller's world/inventory. The report records actual elapsed time, evaluated and accepted step counts, rejection count and accumulated absolute work error. Fixed-step mode remains available unchanged apart from added diagnostics and timestep validation.

## Smooth separation evidence

The original glass/oak/iron aligned separation fixtures use 64 initial intervals, state tolerance 1e-5 and minimum step 1e-14 s. Every material rejects/refines 21 intervals, performs 318 evaluated steps and accepts 170 steps. Complete separation work remains A*Gc within 1e-12 relative tolerance. Total mechanical-energy change is also checked independently against twice the declared error budget, rather than relying only on subtraction of Jolt-stage changes.

| Material | Accepted absolute work error J | Original global budget J |
|---|---:|---:|
| Glass | 9.586955e-8 | 9.6e-8 |
| Oak | 1.198390e-5 | 1.2e-5 |
| Iron | 0.001198395 | 0.0012 |

These are successful bounded refinement cases, not a replacement for the failing rotational/contact requirement. The comparative fixed-step regressions remain.

## Rotational contact limit retained

The original 0.1 s off-center spin fixtures use 512 initial intervals, state tolerance 0.001, minimum step 1e-8 s and their unchanged energy budgets. All three reach the refinement floor and return errors. At the last attempted coarse interval of 2.384186e-8 s, the local state discrepancies are:

| Material | Failure time s | State discrepancy | Remaining work allowance J |
|---|---:|---:|---:|
| Glass | 0.09012683 | 0.346641 | 8.614215e-7 |
| Oak | 0.01044848 | 0.0726285 | 6.984468e-5 |
| Iron | 0.01230102 | 0.201627 | 0.00689016 |

At these points the measured candidate work error fits the remaining allowance; the state comparison is the blocker. The final accepted half-step floor is respected rather than silently bypassed. A fixed-step energy pass for glass therefore does not establish the stricter local state comparison. Investigate contact-solver iterations, correction/warm-start behavior and the specific disagreeing state components before asserting that further timestep refinement alone solves this. The current evidence does not establish the internal cause.

## Verification and next work

All four affected creator, starter, assistant and precision-conversion suites pass after rebuilding both configurations: 6.41 s double and 4.14 s legacy. After the final timestep guard, creator tests were rebuilt/rerun and pass in 4.54/2.32 s. Legacy builds reject the double-position runtime fixture. The final double creator CLI was rebuilt; six command/result pairs retain three smooth successes and three rotational failures. Windows 11 / MSVC 19.44 x64 Release / Jolt 5.6. No new native interaction, save migration, real LLM call or live assembly creation is claimed.

Next resolve the contact-state convergence limit while preserving global work bounds and rollback. Runtime-v3 migration and graphical promotion remain open, as do other inertia adapters, persistent material-backed assemblies, physical fabrication/cutting and all other original goal gates.
