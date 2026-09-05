# Assembly collision-step work localization

Local source `4844fb2`, September 5, 2026; not pushed or merged. Full goal active.

Version-2 runtime assembly reports now include total cohesive opening work, total applied impulse work and at most eight `largest_error_steps`, ranked by absolute change in the integration residual. Each retained step records tick/time, step and cumulative error, both work terms, Jolt-stage energy change, transfer roundoff, new contact-event count, endpoint slack crossings and the minimum/maximum endpoint opening across sites. This is bounded diagnostic output; it does not alter impulses, state integration, material constants, tolerances or pass predicates.

The independent work ledger checks that total mechanical-energy change minus Jolt-stage change and transfer roundoff equals cohesive opening work plus impulse work. Per-step diagnostics satisfy the same balance. Tests cover glass/oak/iron, the eight-row bound and valid tick range, with retained failed rotational trials and immutable caller state.

## Evidence at 2048 steps

These are the corrected-inertia off-center rotational fixtures from the [spin checkpoint](assembly-spin-checkpoint.md), using the same geometry, laws, velocities and budgets.

| Material | Largest error tick | Time s | Step integration error J | Jolt-stage KE change J | Endpoint slack crossings |
|---|---:|---:|---:|---:|---:|
| Glass | 1447 | 0.0706543 | -3.30811e-10 | 3.76191e-16 | 0 |
| Oak | 81 | 0.00395508 | 8.78963e-5 | -0.00843376 | 0 |
| Iron | 27 | 0.00131836 | 0.03965196 | -0.72358380 | 0 |

The largest oak step contributes approximately 78 percent of its maximum cumulative integration error; the largest iron step contributes approximately 70 percent. On that iron step, cohesive opening work is +0.01919317 J and impulse work is +0.02045880 J. Their sum is the positive 0.03965196 J integration discrepancy. This is separate from the large Jolt-stage energy loss; subtracting that loss does not close the kick/opening work balance.

The dominant oak/iron discrepancies coincide with substantial Jolt-stage energy changes and no endpoint tension/slack sign crossings. No *new* contact event occurs on those steps: the event stream alone cannot locate sustained solver response, and endpoint signs cannot exclude an interior crossing. The evidence points to collision-step splitting as the next investigation target rather than a material-name issue or the largest observed slack crossing. It does not prove a complete causal model of Jolt's internal contact processing. Glass remains within budget with much smaller, nonmonotonic error.

## Next solver action

Introduce a complete temporary-world checkpoint/restore boundary before retrying contact steps at smaller durations. Body transforms alone are insufficient: contact caches, solver state, emitted events and interface histories must be restored consistently. Compare a full step with accepted half steps, retain explicit work/error accounting, and reject exhausted budgets without publishing partial state. Do not compensate by artificial energy subtraction, altered material stiffness or wider tolerances. Persistent live assemblies and physical crafting remain downstream of this evidence.

Affected creator, starter, assistant and precision-conversion executables rebuilt in both configurations. All four affected suites pass in 5.91 s for double positions and 4.21 s for legacy positions. Legacy runtime assembly tests remain unsupported and reject. Windows 11 / MSVC 19.44 x64 Release / Jolt 5.6. The creator CLI was rebuilt and generated the three diagnostic reports. No new native interaction or save migration was performed. Runtime-v3 migration, other inertia adapters, default fracture defects, realistic cutting and every other full-goal requirement remain open.
