# Rolling strength and computed replay checkpoint

Source `aa3491f`, local branch `codex/physics-foundation`; not merged or pushed to main. This supersedes the energy-only bowl behavior described in the earlier bonded-bowl checkpoint.

## Implemented correction

Each brittle link must now meet both catalog tensile strength and fracture work Gc times its declared area. The previous coarse energy-only law could fail at roughly 6 MPa despite the glass catalog specifying 45 MPa. The new link energy threshold is max(Gc*A, (strength*A)^2/(2*k)). At rupture, Gc*A is consumed; remaining threshold elastic energy becomes local relative kinetic energy through equal/opposite central impulses. This is an explicit instantaneous elastic-relaxation idealization, not calibrated continuum fracture. Event overshoot remains a separate numerical loss with the same 2% of fracture-work refinement limit. The cumulative energy budget remains 1%; no tolerance was relaxed.

Local contact, surviving bonds and subsequent failures continue on the same simulation clock. Fragments are connected components of retained cells. Oak and iron remain elastic with failure unsupported. No material-name shatter switch or exemption for bowl contact was added.

The native lab now calculates a fresh 1.25-second trajectory in a background worker, then offers Replay at normal wall-clock speed. Initial state, material, geometry, topology and ledger are copied exactly. Playback selects recorded states at 120 Hz without interpolating topology. Editing setup discards the recording; cancellation discards unfinished work. This is one experiment owned by the lab, not reusable cross-experiment caching. Preparation remains CPU slow; this does not make the solver real-time. The impact trial explicitly launches the first two crafted balls toward each other at 10 m/s each and includes the added initial kinetic energy in the ledger.

## Comparative evidence

Windows MSVC Release, promoted double-position build: all four affected suites pass, 44.72 s, including the added crafted impact and recording tests. Earlier final-runtime legacy build passes both bowl suites, 41.43 s. The later test-only crafted-impact addition was run in the promoted build. No cross-platform or full-platform validation is claimed.

All isolated rolling trials use the same 45 mm ball radius and bowl setup, advance 0.3 s in outer intervals of 1/2400 s, with the initialized material-dependent stable internal step.

| Material | Center displacement (m) | Peak object spin (rad/s) | Broken links |
| --- | ---: | ---: | ---: |
| Glass | 0.195009 | 10.9282 | 0 |
| Oak | 0.195834 | 10.4671 | 0 |
| Iron | 0.195615 | 10.8441 | 0 |

These checks establish translation and rotation without damage over this interval, not no-slip rolling or long-duration calibration. The six-ball gravity release runs 0.6 s: zero broken links, six groups, initial energy 19.2604 J and residual -2.95548e-6 J.

Closed pair tests compare all three materials at 0.05, 2 and 10 m/s per body, for 2 ms, using wave-step fractions 0.35 and 0.175. Glass remains intact at the two lower speeds. At 10 m/s, glass loses 148 links and retains 30 connected components among 38 cells; failures occur over time and include later internal failure inside a detached piece. Oak/iron do not fracture. Glass high-speed residuals are -0.00716887 J and +0.00141802 J against 95.4259 J initial energy. All cases preserve mass and closed linear/angular momentum within 1e-10; energy errors remain below 1%. Twelve support cases cover glass/oak/iron, concrete/oak surfaces and 0/10-degree tilt, with reaction and named-loss checks. A separately run three-crafted-ball impact produces 31 broken links after 0.01 s. Recording completion, wall-clock advancement, restart and cancellation pass.

## Native verification

Opened the actual bowl window with the user's eight crafted balls and stock retained. Calculate completed; Replay advanced the displayed time from 0 to 1.25 s and visibly changed ball positions. Export experiment and Save lab image were exercised. The final state has four broken links in object 7 around 0.68282–0.68291 s but still eight connected groups: no separated balls. The recording is left available through Replay.

Do not describe the entire eight-ball release as damage-free. The current report lacks contact-to-fracture attribution; its legacy ball_contact_callbacks field is not a bonded-solver collision counter. We cannot establish from this export whether these four breaks were driven by another ball or coarse support contact. The earlier release image is historical evidence of the superseded model.

## Remaining gates and next steps

1. Record contact identities, normal approach speed/impulse, local stress and fracture timing to distinguish ball impacts from support loading. Add longer isolated rolling and matched multi-ball regressions through the full 1.25-second replay.
2. Replace or refine the coarse 19-cell spherical contact proxies and test geometry/resolution convergence; smooth rendered spheres currently hide a bumpy physical surface.
3. Calibrate strength, fracture work, crack progression and fragment geometry with comparative coupons, defects and timestep/resolution sweeps. The local 45 MPa gate alone does not establish macroscopic tensile strength.
4. Profile computation and recording memory, preserve numerical budgets and exact experiment identity, then improve latency.
5. Keep the complete application goal: first-person collection into voxel-equivalent inventory, material/energy/tool/level requirements, LLM designs and shortages, functional crafted objects, API contracts and durability. Preserve every mechanic and platform scorecard row. The bowl remains the immediate laboratory; this checkpoint does not complete the general platform.