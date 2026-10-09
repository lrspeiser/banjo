# Ranked CUDA Newton starts — October 9, 2026

## Implemented experiment

The coupled CUDA solver scores three private starting guesses against the unchanged full physical equations. The proposed midpoint velocity fractions are 1, 0.1 and 0.01; the corresponding end-velocity guesses are 1, -0.8 and -0.98 times the previous velocity. These are nonlinear initial guesses, not assigned physical motion. Valid guesses are ranked by equation residual. A failed line search may try the next guess within the same total 24-iteration limit. The eight-probe search, equation tolerance, material/contact laws, work/P/L admission, rollback and runtime limits remain unchanged. Singular tangents and other invalid candidates still refuse.

The previous single-start solver remains selectable. Accepted microsteps record the actual strategy, scores, attempted fractions and converged fraction. Failure records also distinguish the Jacobian's base velocity from the last trial velocity. `/coupled` exposes both strategies and a Run 0.1 s control which renders only newly accepted CUDA states. This does not introduce cached motion, authored shards or an animation substituted for physics.

Base revision: `f21567fcdcd9c83a6c6ffad3cdcfd98acc7b9037`. Publication is the commit containing this note, reported by `/api/checkpoint`. Coupled source SHA: `a31a57e2f92a0e9ef727a4973737cc4c3a00c0573cae1d26e3a9d0c82c1b0412`. Windows / MSVC 19.44 / RTX 5090 / driver 610.88 / CUDA driver API 13.3 / CuPy 13.5.1 / NumPy 2.5.3. The CPU material-world executable and shared law headers are unchanged.

## Verification

- [Analytical root, recorded failure and material refinement](evidence/gpu-ranked-newton/refinement.json): a stiff two-body elastic oscillator matches the independently calculated implicit-midpoint root with both strategies. The exact previously recorded glass failure still refuses with the single start; ranked starts converge in six iterations, equation residual 2.199e-11 and energy residual 5.023e-17 J. Inputs/history remain private until acceptance.
- Eight matched material controls complete to 0.104167 physical s: glass, oak, iron and ice sheets, a 0.1 kg iron ball, 5 mm surface clearance, host timesteps 1/960 and 1/1920 s. All accepted microsteps pass existing work/P/L checks and the shared iteration bound. No separated site or yielded face is observed in these controls. Density and stiffness are material inputs; oak grain and calibrated bulk material realism are unsupported.
- [Current parallel/reference parity](evidence/gpu-ranked-newton/parity.json): exact 128-candidate, 480-local-Jacobian and four complete low-energy history comparisons, 162 fault-priority cases and failure isolation. [World controls](evidence/gpu-ranked-newton/controls.json) retain freefall, rollback and low-energy material checks.
- [Normal browser control and journal check](evidence/gpu-ranked-newton/browser.json): Set up the stronger glass control and Run 0.1 s complete 96 host ticks, with no failed response. Downloaded gateway records retain all accepted microstep starting strategies and work checks. Before/Live is also checked. Published revision/source verification is repeated after restart.
- Twelve distinct scoped CTests pass in `build/voxel-contact-audit` (290.91 s): coupled contact, rotation strain, voxel face spring, compliant step, GPU material laws, GPU material frames, GPU coupled world, GPU coupled pipeline, GPU coupled convergence, voxel gateway, voxel pipeline and voxel playback. This is not the entire historical suite. The new Python convergence test is registered in CMake. Source registration passes 345/345. CUDA full/local-Jacobian memcheck reports zero errors; racecheck reports zero errors/warnings.

Reproduce: configure the existing GPU-enabled `build/voxel-contact-audit`, then run `ctest --test-dir build/voxel-contact-audit -R banjo_gpu_coupled_convergence_tests --output-on-failure`. Its evidence is written to `build/voxel-contact-audit/gpu-coupled-convergence-evidence.json`. Use the configured GPU Python, not an interpreter without CuPy.

## Material accuracy and speed remain OPEN

These are completion and conservation checks, not trajectory qualification. Five common-time samples at the two host timesteps produce:

| Sheet | Wall seconds, 1/960 / 1/1920 | Maximum position difference | Maximum velocity difference |
|---|---:|---:|---:|
| Glass | 10.901 / 15.684 | 2.173 mm | 0.2954 m/s |
| Oak | 3.579 / 7.533 | 0.3695 mm | 0.1260 m/s |
| Iron | 14.033 / 12.227 | 0.1797 mm | 0.01909 m/s |
| Ice | 3.222 / 7.613 | 0.9106 mm | 0.1417 m/s |

Across these eight runs the maximum microstep momentum residual is 1.023e-11 N·s and angular residual 6.695e-14 N·m·s. Full per-run energy, support reactions, histories and coordinates are retained in the refinement evidence. The glass position difference is about 22% of a 10 mm cell. Calculation remains roughly 31–151 wall seconds per physical second in these individual measurements, excluding browser delivery. No near-realtime claim is made.

[Private prototype comparison](evidence/gpu-ranked-newton/prototype-comparison.json) preserves an additional warning: fixed-order and residual-ranked starting guesses both finish, but produce 31 versus zero separated ice sites. Those probes used explicit runtime method overrides; their baseline source hash alone does not identify the overridden algorithm. Script text/hashes and that distinction are retained. Neither prototype establishes a qualified fracture outcome. Conservation closure cannot establish correct root selection or temporal accuracy.

## Next work

1. Resolve contact event timing, nonlinear root selection and temporal error control using independent contact oracles and common-time material comparisons. Require accuracy before increasing impact scope or calling the result realistic.
2. Reduce measured dense Jacobian, ordered gathering and launch/synchronization cost with resident sparse work while retaining laws, audit gates and the CPU reference.
3. Qualify actual fracture connectivity and retained plastic deformation under matched impacts and unloading, then spatial refinement/adaptive cells and editable gameplay.
4. Friction/CCD, grain, bulk plasticity/tearing, thermal/fire/phase change, fluid/water-wheel/power and complete-world near realtime remain open. Earlier [model assumptions](gpu-coupled-checkpoint.md) remain in force. This is an experimental solver improvement, not completion of the platform.
