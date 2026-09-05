# Explicit normal compliance and sustained-contact reference

Tested code: `58546cbbcd3696db409124b9f353c231db0ae0e4`, local `codex/physics-foundation`, September 4, 2026 (logs September 5 UTC). All 12 Windows CTest executables pass, including seven new compliant-contact test groups. All 27 full-resolution glass/oak/iron probes complete. This is an explicitly selected, uncalibrated normal-interface model. The constant-restitution event model remains available and its three sampled `e=0.3` cases still reject. The default viewer still uses its earlier separate-correction solver; Gate 1 remains open.

## Law and accounting

`NormalComplianceLaw` requires stiffness `k > 0` in N/m and compression-only damping `c >= 0` in kg/s. With signed gap `g` and compression `delta=max(0,-g)`, recoverable interface energy is `U=k*delta^2/2`. The continuous normal force is `k*delta+c*max(delta_dot,0)` during compression/contact. Unloading returns the stored elastic energy without dashpot force. This particular law was selected as a testable capability; it is not a calibrated glass, wood or iron contact law, a conversion from restitution, or a repair to the rigid `e=0.3` law.

For a step with gap increment `dg`, the elastic impulse is `J_elastic=-dt*(U1-U0)/dg`, evaluated with stable piecewise expressions and the derivative limit when needed. With `s=min(g,0)`, damping impulse is `J_damping=-c*min(s1-s0,0)`. Its nonnegative work loss is `D=-J_damping*dg/dt`. Thus `U1-U0+(J_elastic+J_damping)*dg/dt+D=0`. Endpoint contact transitions receive this discrete work treatment; no root event or instantaneous restitution impulse is also applied. The damping quadrature follows the discrete gap path, so temporal refinement still matters.

`CompliantStep` puts elastic bonds and normal contacts into one global Newton/GMRES solve. Nodes and the optional finite sphere advance with the same midpoint clock. Static-plane reactions act along its normal. For node/sphere separation `q`, the discrete radial direction is `(q0+q1)/(|q0|+|q1|)`, which closes gap work and gives equal/opposite impulses with midpoint angular balance. Isotropic sphere spin is unchanged by these central forces. There is no friction, damage, plasticity or velocity snapping in this reference.

Each proposed step independently measures whole-system energy, linear momentum and angular momentum, including gravity work, support reactions, stored contact energy and contact damping. Input state is published only on success. The previous per-step velocity tolerance (1e-9 m/s), energy and momentum budgets (relative 1e-9 with SI floor 1) are not widened. Isolated energy scaling excludes bulk COM kinetic energy; a fixed support uses total kinetic energy. Gravity potential offsets cannot inflate the energy tolerance.

A new finite-mass analytical test exposed an insufficient stopping rule: at step 265 a velocity residual of 9.88e-10 m/s still produced 2.47e-9 kg m/s momentum drift. The solver now also checks mass-weighted residual momentum, angular momentum and work before stopping Newton, using half the corresponding audit budget to leave roundoff room. The independent final audit still decides acceptance; there is no after-the-fact momentum or energy projection.

Modeled compression has a separate, required positive validity bound. It is not recorded as unresolved rigid penetration or accepted by increasing the rigid contact tolerance. Initial/end compression and the swept finite-sphere chord must respect that bound; a chord through a sphere rejects. Finite-plane footprint transitions reject for a future edge/general-geometry handler. Failed convergence, geometry, compression or balance leaves caller state untouched.

## Independent analytical checks

For one point hitting a plane, let `omega=sqrt(k/m)` and `zeta=c/(2*sqrt(k*m))`. Compression ends at `t_peak=acos(zeta)/(omega*sqrt(1-zeta^2))` below critical damping, `1/omega` at critical damping, and `acosh(zeta)/(omega*sqrt(zeta^2-1))` above it. Undamped unloading then takes `pi/(2*omega)`. The predicted rebound ratio is `exp(-zeta*omega*t_peak)`. Tests use this continuous solution, rather than a second copy of the discrete implementation.

- Plane bounce covers damping ratios 0, 0.25, 0.8, 1 and 2, with `m=2 kg`, `k=2000 N/m`, incoming normal speed 1 m/s and duration 0.25 s. Refining 1 ms to 0.25 ms reduces combined velocity/position error by more than the required factor two in every case (observed roughly 16–18). Fine-rate speed and position errors stay below 2e-4 m/s and 1e-4 m. Independent accumulated energy and reaction checks use 1e-8 absolute bounds.
- A 1 kg point hits a freely reacting 2 kg sphere; the same oracle uses reduced mass 2/3 kg. Both final velocities, contact duration, positions and damping work pass at 0.2 ms for 0.1 s.
- Under 9.81 m/s² gravity, a critically damped 2 kg point approaches the exact loaded equilibrium at 9.81 mm compression without snapping velocity to rest. At 0.5 s, measured vertical velocity is -6.66e-7 m/s. The 0.0962361 J damping loss and 0.0962357 J stored contact energy close the gravity-work ledger. Starting exactly at equilibrium gives the expected 1.962 N s support impulse over 0.1 s.
- Scalar work checks span free, entering, compressed, unloading and leaving branches. Analytical Jacobians agree with finite differences. An oblique finite-pair experiment and its rotated/translated/boosted copy preserve trajectory and momentum/energy within 1e-8. Compression/footprint rollback and invalid parameters are checked.
- Full glass/oak/iron lattices run with damping on and off in the test suite. These use the same elastic approximation, never brittle failure selected by a substance label.

## Full material comparison

Every probe uses radius 0.25 m, spacing 0.04 m, horizon 2, occupancy sampling 3, 1,285 nodes and 17,097 bonds. Only catalog density and elastic stiffness differ between glass, oak and iron. The interface has **the same per-contact `k=1e8 N/m`**, damping `c=0` or `10000 kg/s`, and explicit maximum compression 0.005 m. These coefficients are chosen numerical experiment parameters, not measured substance data. Per-contact stiffness is not yet compiled from area or a resolution-independent interface law.

| Catalog input | Glass | Oak (wood) | Iron |
|---|---:|---:|---:|
| Density (kg/m³) | 2500 | 700 | 7870 |
| Young modulus (GPa) | 70 | 12 | 211 |
| Declared Poisson ratio | 0.22 | 0.35 | 0.29 |

These are the repository's preset inputs, not newly sourced/calibrated material measurements. At fixed sampled volume, iron carries more mass and incoming kinetic energy than glass, and oak less. Changing both density and stiffness changes contact duration and internal modes; the rebound differences cannot be attributed to a substance name or one coefficient alone. The central-bond approximation does not independently reproduce each declared Poisson ratio.

Impact cases start at `(0.3,-1,0.2) m/s`, zero spin, with a plane 1 mm below the lowest node, no gravity, friction or damage; all run for 5 ms. Loaded cases start touching the plane at `(0.3,0,0.2) m/s`, use downward gravity 9.81 m/s² and damping 10000 kg/s, and run for 20 ms. Tangential translation remains frictionless. All cases use 50, 25 and 12.5 microsecond intervals. [The 27-case evidence table](evidence/compliance-matrix.csv) preserves commands, per-run totals, compression, iteration work and observed timing.

Final COM vertical velocity, in m/s:

| Material / case | 50 microseconds | 25 microseconds | 12.5 microseconds |
|---|---:|---:|---:|
| Glass, undamped impact | 0.999862733 | 0.999816663 | 0.999768530 |
| Oak, undamped impact | 0.996273702 | 0.995336367 | 0.993567500 |
| Iron, undamped impact | 0.999984923 | 0.999953152 | 0.999986233 |
| Glass, damped impact | 0.784401840 | 0.782812092 | 0.783298926 |
| Oak, damped impact | 0.778346728 | 0.775059174 | 0.772439666 |
| Iron, damped impact | 0.855918057 | 0.855625335 | 0.855674217 |
| Glass, loaded | 1.84961e-6 | 1.31569e-6 | 1.26592e-6 |
| Oak, loaded | 3.16275e-7 | -1.42595e-7 | 5.53659e-8 |
| Iron, loaded | 2.46989e-4 | 2.34886e-4 | 2.31962e-4 |

At the finest interval, damped impacts lose 31.345586 J (glass), 8.798866 J (oak), and 68.823636 J (iron); all have zero remaining contact energy at 5 ms. Loaded cases retain 0.000514135 J, 0.0000404590 J and 0.004318139 J of interface energy respectively. Iron still has appreciable residual motion at 20 ms; these are finite-duration loaded-contact measurements, not proof that every lattice has reached static equilibrium. Maximum observed compression across the matrix is 0.450359 mm, below the declared 5 mm validity bound.

Every interval passes its unchanged energy/momentum budget. Across complete runs, the largest absolute residuals are **1.16e-8 J**, **4.07e-8 kg m/s** and **1.67e-10 kg m²/s**. Normal numerical loss and instantaneous impact loss are zero; compliant damping is reported separately. Accumulated run drift is distinct from the per-step acceptance tolerance.

These results do **not** establish converged lattice trajectories. Oak's undamped rebound changes more in the second refinement than the first. Damped-work increments shrink, but this does not establish a universal order or resolve all motion/internal-mode error. The analytical low-dimensional oracle passes while high-frequency sampled-material response still needs finer timesteps, matched trajectories and resolution/orientation sweeps. Material calibration, Poisson response, wood grain and iron plasticity remain absent.

Observed solver wall time is 1.11–2.56 s per 5 ms impact and 4.58–11.06 s per 20 ms loaded run on this machine. These are single development observations, not performance distributions, and remain far from real time. A brief rigid-reference regression ran during the last fine batch. Comparing this timing directly with rigid event contact would compare different physical laws; it is not evidence of an equivalent-model speedup.

## Reproduction and source

```powershell
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
./scripts/run-compliance-matrix.ps1
# Optional independent fine-only batch:
./scripts/run-compliance-matrix.ps1 -FineOnly -OutputDirectory build/compliance-fine
```

The probe exposes `--step-mode compliant --normal-stiffness 100000000 --normal-damping 10000 --max-compression 0.005`; `--gravity` and a zero `--speed` permit loaded cases. Compliance parameters outside that mode and restitution outside event mode reject instead of silently changing laws. The older reference script was adjusted to pass restitution only for events. Its rerun records the same 15 accepted / three repeated-impact rejections in the [rigid regression evidence](evidence/compliance-rigid-regression.csv).

The recorded probes ran against the working source subsequently committed as `58546cb`. The matrix retains the then-current HEAD and dirty flag as well as the final tested-code commit; they are not mislabeled clean-HEAD runs. The first 18 cases and subsequent nine fine cases were separate batches; the committed script defaults to all 27. Build and CTest logs are retained with the exported evidence.

Windows x64 Release build passes with no compiler warnings/errors in the captured log. All **12 CTest executables pass in 9.04 s**. Environment: Windows 11 Pro 26200, Intel Core Ultra 9 285K, VS2022/MSVC 19.44.35228, SDK 10.0.26100, CMake 4.1.2, cached Jolt 5.6/raylib 6. Main's custom-frame-control, busy-wait and static-MSVC-runtime flags remain OFF. The rebuilt normal viewer renders and reset input works; that checks the unchanged default runtime, not use of this new contact reference. No new remote-CI, Linux/macOS, cross-GPU or material-realism claim is made.

## Next work

1. Establish matched trajectory/internal-energy error for glass, oak and iron over further timestep refinement. Define the valid compression regime and compile interface stiffness/damping against contact area before any resolution comparison claims the same physical law.
2. Preserve the rigid `e=0.3` failure and explicitly decide which contact law each experiment requests. A compliant model is an added choice; no automatic fallback or silent restitution change is allowed.
3. Integrate consistent frictional loads, torque and work, then synchronized rigid/material ownership, activation and handoff into the shared laboratory. The default contact/support energy injection remains a defect until that path is repaired and retested.
4. Continue constitutive/fracture coupons and the shape, adaptive-matter, assembly, authoring and publishing gates. Maintain all 30 mechanics and 10 platform capabilities in the [scorecard](mechanics-scorecard.md).
