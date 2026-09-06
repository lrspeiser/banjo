# Normal constraint reactions and impact energy

September 6, 2026; implementation over `ac324fa58a2f276feae4b053a1f942657bde6fef`. R03 and R09 remain active. All nine original workstreams, 40 mechanics and R01..R10 acceptance goals are retained. This corrects normal-contact energy accounting in the coupled tetrahedral route; it does not implement glass fracture or make the older network plate route accurate.

## Cause and implementation

The matched catalog glass case advanced to 10 ms in 13,680 calls, then exhausted 200,000 calls attempting the next 0.1 ms. Failure telemetry revealed 248,156 tentative contacts and a minimum accepted half-step of 7.8 ps. Its 3 nJ contact reserve was saturated. The whole final interval rolled back, so the committed recording correctly reported zero contacts. This was not evidence that no contact was ever computed.

Each velocity-Verlet force half-kick can temporarily push a resting contact into a forbidden normal velocity. The constraint impulse removes that stage kinetic energy. The old ledger classified every removal as irreversible collision dissipation. For a motionless ball supported against gravity this invented positive impact heat, despite zero displacement, external work and change in physical energy. Refinement then chased this false dissipation through tiny timesteps.

The same contact impulses and geometry still execute. The ledger now distinguishes a resting normal constraint reaction from an incoming impact. A drift-stage event at time zero uses the actual pre-kick relative normal velocity to identify rest, with the existing 1e-10 m/s contact-velocity threshold. A swept arrival or a genuine incoming velocity retains its inelastic impact dissipation. Endpoint Verlet normal projections are reactions: the drift already handled geometric arrivals, and the final force kick changes velocity without advancing geometry. Friction dissipation is unchanged.

`normal_constraint_projection_loss_j` records removed stage kinetic energy separately. It is a numerical diagnostic, not heat or a new energy reservoir. The raw physical balance `Delta(K + U) + impact/friction dissipation + plastic dissipation - external work` remains subject to both absolute accepted-half-step and endpoint budgets. No acceptance tolerance, material parameter, impulse, restitution coefficient or work limit was increased. Fixed-step trajectories are unaffected by this ledger classification; adaptive trajectories can change because the error estimator now measures the corrected quantity.

The native API, saved playback summary and compact GPT evidence expose the separate quantities. A stopped advance also reports tentative duration, error/reserve consumption and contacts, explicitly separate from committed state. Old recordings remain unchanged and preserve their source/binary hashes.

## Verification and measured progress

Analytical controls now require a resting supported sphere to remain motionless, balance its gravitational impulse, generate zero physical dissipation and close its raw energy ledger. Incoming normal impacts under both Euler and Verlet must still dissipate exactly the lost incoming kinetic energy. The other contact, friction, rollback, material and full-impact regressions remain active.

The original matched glass/oak/iron 10.1 ms request now completes under the unchanged 200,000-call and 6 microjoule-per-0.1-second limits:

| Catalog material | Calls | Committed contact impulses | Absolute energy residual |
|---|---:|---:|---:|
| Glass | 19,554 | 6,621 | 5.820 nJ |
| Oak | 5,565 | 142 | 4.225 nJ |
| Iron | 17,355 | 1,645 | 9.992 nJ |

These are computed first-contact states, not calibrated material response or a full drop qualification. Impulse counts include the repeated constraint solve and are not counts of separate physical collisions.

Previously GPT-authored fictional cases were rerun with identical numeric requests:

| Material and duration | Previous calls | Corrected calls | Corrected absolute energy residual |
|---|---:|---:|---:|
| Cedar-X elastic, 0.1 s | 68,394 | 7,830 | 2.773 microjoules |
| Copper-Y J2, 0.1 s | 46,809 | 4,665 | 2.406 microjoules |
| Aster-37 elastic, 0.05 s | 27,750 | 4,230 | 1.103 microjoules |
| Birch-91 J2, 0.05 s | 11,838 | 1,944 | 0.988 microjoules |

All four completed their full requested duration within the same error/work bounds, reducing calls by 6.1 to 10.0 times. They are deliberately compliant fictional materials; their labels do not select engine behavior. J2 history remains loaded/vibrating state, not an accepted permanent unloaded dent. Single-run wall times are diagnostic, not realtime qualification.

A fresh live GPT request authored Larch-Q elastic and Ember-R J2 with explicit SI properties. Job `bfe9916afdb64760aac815489cf29777` completed both 0.1 s cases and automatically displayed 101 sampled frames in the embedded 3D playground. The prompt, generated plan, native recording and separate energy evidence are saved.

Full Windows MSVC Release build passed. All 62 native suites passed in 89.78 s; the adaptive suite now has 11 cases. Python discovery ran 142 tests: 141 passed and one Windows symlink-privilege check skipped, in 6.871 s. Browser verification covered live chat, automatic computed 3D, slow playback, component/reference controls and native evidence. These results do not imply cross-platform or spatial-convergence qualification.

## Failed gates and next work

At 20 ms requested with 1 ms recording intervals and the same 200,000-call bound, glass commits through 11 ms, oak completes 20 ms, and iron commits through 10 ms. At 100 ms all three still hit the work bound. Failed intervals roll back. Glass's later exhausted interval has no contact impulses: high-frequency material motion and the explicit accuracy cost remain after the contact accounting correction. Stable fracture, finite-strain rubber, unloading, compact world persistence and realtime acceptance remain open.

Next audit sustained sticking-friction force-kick projections separately from true sliding loss; test separating contacts that reverse inside a timestep; then qualify an energy-accounted stiff integration/multirate strategy under time/space refinement. Do not loosen tolerances or add material-name outcomes to make longer recordings pass. The original full thin-glass shatter gate remains unmet.
