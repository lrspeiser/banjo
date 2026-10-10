# The 10 m glass drop no longer stops at the impact

October 10, 2026. Coupled lab (`/coupled`), CPU solver.

## What was wrong

Drop the 0.1 kg iron ball from 10 m onto the 3 × 3 glass sheet and the lab used to stop at 1.425 s, the moment of impact, with "Coupled Newton line search did not reduce the equation residual". Nothing was ever shown breaking.

The saved inputs of the refused step tell why. Glass interfaces are stiff and short: each holds until it has opened 89 nanometres, then softens, and it is fully broken at 356 nm. While an interface softens, its force falls as it opens, by up to about 4 × 10⁹ N per metre. A 2.5 g glass cell's inertia over a step of h seconds resists like a spring of m/h². At the 4 µs steps the controller was trying, that inertia is only about 1.5 × 10⁸ N/m, a thirtieth of the softening. The step's equations then have no unique answer near where Newton starts. Newton stops at a point between "still holding" and "broken" where the error stops shrinking but is not zero. The saved trial shows exactly that: a residual stuck near 6 (the tolerance is 3 × 10⁻¹⁰), and two interfaces between cells 10 and 11 caught halfway through softening.

The controller's answer to a failed step was to halve it, up to ten times: 1/240 s ÷ 1024 = 4 µs. That is not short enough. The same saved step converges in 10 iterations at 0.5 µs, and fails at 1, 2 and 4 µs.

## What changed

Only the search for a step the solver can take. The equations, the material laws, the contact law and every admission check (energy, momentum, travel, turn and compression) are unchanged.

- **Deeper halving.** A host step may now be halved 16 times (to 64 ns at 1/240 s) instead of 10, and it may spend 512 trials instead of 128. The 30 s wall-clock limit per host step still applies.
- **A softening bound.** When a failed step carried interfaces that held at its start past their strength, the step's path takes them through their softening range. The controller works out how short the step must be for each cell's inertia to outweigh the softening of those interfaces: h ≤ √(m / Σ k_soft), with k_soft = area × strength ÷ (breaking opening − strength opening). It goes straight to the first halving under that bound instead of failing at every level in between. The bound is cautious: on the saved step it counts all 16 interfaces around the centre cell, gives 0.19 µs, and the step converges at 0.13 µs in 4 iterations, though it would already converge at 0.51 µs. A version that counted only the interfaces still softening at the failed trial's end gave 0.54 µs there, but took longer over the whole drop, because it fell back to plain halving more often.
- **A travel-informed split.** When a step fails only because something would move more than its travel limit (a quarter of the smallest part, 2 mm here) or turn more than a quarter radian, the controller skips straight to the halving where the measured motion fits, instead of failing at each level.

The first two make the impact possible. The last two make it affordable: the impact step went from 23 s of wall time (32 failed solves) to 16.7 s (9 failed solves).

## Measured

10 m, 0.1 kg iron ball, glass sheet, 1/240 s host step, CPU, this desktop:

- The run reaches 2.000 s. All 48 glass interfaces break.
- The fracture ledger is 0.0096 J, exactly 48 × fracture energy × interface area.
- The largest energy-balance error of any accepted step is 8 × 10⁻¹¹ J (each step's tolerance is about 10⁻⁷ J).
- 9,216 accepted substeps and about 3 minutes of wall time (184 s, while other work shared the computer). After the impact each host step takes about 0.9 s, because fragments flying at up to about 30 m/s may move only 2 mm per step.

The same 0.1 kg iron ball on the other materials, 2 s:

| Sheet | 10 m | 1 m |
|---|---|---|
| Glass | Completes; all 48 interfaces break | Stops at the impact (0.45 s): the impact step needs more than its 30 s of computing |
| Ice | Completes; all 48 break (0.0018 J) | Completes; all 48 break |
| Oak | Stops at the impact (1.43 s): over the 30 s limit | Stops at the impact (0.50 s): over the 30 s limit |
| Iron (plastic connectors) | Completes | Had not finished after 25 minutes while seven other drops shared the computer |

Before this change, the 10 m glass drop stopped at the impact (1.425 s), and the 10 m ice drop stopped just after it (1.4292 s, at the 128-trial limit). Oak's interfaces soften over 17 µm of opening where glass's soften over 0.27 µm, so oak keeps them softening, and needing sub-microsecond steps, for far longer.

`tests/cpu_glass_fracture_step_test.py` replays the saved refused step (`tests/data/coupled-glass-high-drop-step.json`). It checks that Newton stalls there with interfaces past their strength, that the softening bound picks a step between half the bound and the bound (0.13 µs; the bound is 0.19 µs), and that the step then converges and closes energy and momentum. It runs in half a second. With `--full` (registered as a `long` test) it runs the whole 2 s drop and checks that all interfaces break, the fracture ledger and the energy balance.

## Heat follows the sheet as it breaks

With heat switched on, the lab used to refuse a step as soon as any interface had begun to crack or yield, so no heated sheet could break. Heat now crosses each face between two cells only through the part of it that is still bonded: the conductance of a face is its intact conductance times the area-weighted mean of (1 − damage) over its four cohesive sites. A fully separated face carries none, because contact conductance across a gap is not modelled. Iron's plastic connectors yield without opening a gap, so their faces stay fully conducting. Moving heat between cells conserves the field's energy whatever the conductance, so the energy account is unchanged. A reopened scene takes each face's bonded fraction from its saved damage.

Measured on the 10 m glass drop with the centre cell heated at 2 W: every face had separated by 1.4292 s; from then on, the other eight cells' temperatures did not change in the last bit; the centre cell ended at 261.89 K; the combined account of motion, stored energy, fracture and heat closed to 3.8 × 10⁻¹⁰ J; the mechanics were identical to the unheated run (9,216 substeps); and the scene reopened exactly. `tests/thermal_matter_adapter_test.py` checks the face law directly: half-bonded faces carry exactly half the conductance, separated faces isolate a heated cell exactly, and two broken sites of four leave half a face bonded.

## Faster, the same to the bit

Each Newton iteration evaluates 120 finite-difference trials, one per unknown each way, in one call to the native library. They are independent: each reads the shared, prepared scene and writes only its own rows. They now run on up to 8 threads, so every output is the same to the bit, and `cpu_local_jacobian_tests`, which compares local and full trials byte for byte, still passes on Windows and under GCC. The batch for the saved glass step went from 16.5 ms to 5.0 ms. The heated 10 m glass drop went from 233 s to 136 s of wall time, with identical results (the same 9,216 substeps and the same residuals to the last digit).

It is not enough for the gentler impacts. From 1 m, glass now gets through 363 substeps of the impact step in its 30 s, against 163 before, and is still refused there. So is oak from 10 m, after 430. Those need a cheaper Jacobian, not more threads.

## Pick where it lands

The ball used to fall on the sheet's centre every time. The coupled lab now takes a drop spot (`spot_m`, x and z from the sheet's centre, within the 15 mm the sheet reaches each way; the page has **Spot · x mm** and **Spot · z mm** beside the drop height). `tests/cpu_drop_spot_test.py` lets a 1 mm drop go over two corner cells, an off-centre point and the centre, and checks from the solver's own contact sites that each first touches the cell beneath it; a spot off the sheet is refused. A ball that bounces lands again wherever the calculation takes it, so second hits need no extra setting.

## What this does not fix

- **The ball rebounds and glass flies.** The coupled lab's contact is elastic: it stores and returns energy and has no restitution law (see the conservative-reference checkpoint). So after breaking through, the ball bounces off the ground to about 5 m and the glass pieces are thrown 2–6 m up. That is what this model says. It is not what real glass and iron do.
- **Speed.** About 3 minutes of wall time for 2 s of world time is about 1% of real time. The impact step's 15–17 s is about half the 30 s limit, so a slower or busier computer refuses the same drop at the time limit. Render's hosted lab, with a tenth of a CPU, will. Oak and the 1 m glass drop already exceed it here. The cost is the solver's finite-difference Jacobian (about a thousand trial evaluations per step). That is the realtime work in section 7 of the handoff.
- **Crack pattern.** With nine cells and four interfaces per face, "all interfaces broke" is the whole crack pattern. It is not a calibrated fragment count.
