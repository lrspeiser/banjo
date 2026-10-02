# Held strikes: explicit CPU target integration — October 2, 2026

## Scope and publishing

This is an opt-in numerical reference checkpoint for R3. It improves the
[continuous target experiment](held-strike-target-checkpoint.md); ordinary
held-tool clicks against made objects are still unimplemented. R1 and R3–R6
remain open. The default XPBD path and running preview executables are unchanged.
Implementation revision will be recorded after verified publication on main.

## Numerical method and accounts

`StepSettings::bond_integrator = kBondVelocityVerlet` selects serial double CPU
velocity Verlet. The default is `kBondXpbd`. A live axial bond has recoverable
extension `e = length - rest_length - plastic_extension`, compliance `c` in m/N
and elastic energy `e²/(2c)` in joules. At each half kick its force on endpoint
a is `(e/c) * direction_ab` in newtons; endpoint b receives the opposite force.
All forces use the same current geometry before any velocity write. Between
the kicks, positions drift with the actual half-step velocities. Velocity is
not reconstructed from projected positions. No damage, shard or launch impulse
is assigned to create a result.

The existing compliance, node strain sampling, plastic return, damage thresholds,
bond removal and radial internal damping functions are retained. This is a
different explicit integrator, not a silent change to material laws or GPU/parallel
behavior. Float, parallel and CUDA uploads explicitly refuse the new mode.
The reference currently requires freely movable finite reciprocal masses and
no internal sphere, support-plane or node contacts; it accepts the previously
qualified external native point-contact bridge between actual substeps.

The local stability gate uses the mass-normalized Hessian bound
`omega_bound² = 2 max_i sum_edges[max(1, |e|/length)/(c * mass_i)]`.
It requires `dt * omega_bound < 2` before each spring kick. Collapsed bonds,
nonfinite inputs and excessive steps refuse. This is a conservative current-state
bound, not a global guarantee across future deformation. Whole-step rollback
on a later refusal remains required before world integration.

Finite forces/wrenches and gravity receive two half kicks per actual substep.
Only the final half consumes a load's finite span. Delivered work, impulse,
angular impulse and named-source elapsed time remain separate; gravity has its
own ledger. Actual summed internal kick momentum/angular changes are measured
as arithmetic errors, with no velocity correction. New mode energy auditing
is always enabled and phase names identify the selected integrator.

Two numerical effects are now distinguished:

- An isolated XPBD spring is backward Euler. With reduced mass mu and stiffness
  k, its exact numerical loss is `mu * delta_v²/2 + k * delta_q²/2`. The analytical
  test measures this identity rather than assigning it to physical damping.
- The existing explicit plastic return removes excess elastic energy above its
  declared plastic work. Its additional numerical loss is
  `(1 + hardening) * delta_plastic_extension²/(2c)`. This is measured separately
  in the new mode, not relabeled as heat or added plastic work. The remainder
  `delta(K+elastic) + physical_losses + plastic_return_numerical_loss - external_work`
  is the signed measured integration error. It changes no state.

## Matched actual native/target measurements

Conditions are retained: 6 m/s iron 80 mm head + oak 240×40×40 mm handle with
an ideal ordinary fixed seam; 120 mm glass/oak/iron targets, 27 cells at 40 mm,
seed 17, 100/50 ns steps and 204.8 microseconds elapsed. No gravity, internal
damping, supports or target node contacts. Initial combined energy is 77.36832 J.
Current native surfaces and per-leaf contact materials determine every witness.
The source and target advance on the same actual substep clock, preserving
target history, native recoil and explicit float-transfer accounts.

| Target | dt (ns) | Contacts | Broken bonds | Plastic work (J) | Contact loss (J) | Plastic-return numerical loss (J) | Signed integration error (J) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Glass | 100 | 2012 | 15 | 0 | 8.33260931609 | 0 | +0.000665196108 |
| Oak | 100 | 3732 | 0 | 0 | 5.20861995156 | 0 | +0.000130762373 |
| Iron | 100 | 1628 | 0 | 2.28794376385 | 19.5690413738 | 0.005376114733 | +0.001308871198 |
| Glass | 50 | 4013 | 16 | 0 | 8.25052303208 | 0 | +0.000166978438 |
| Oak | 50 | 7448 | 0 | 0 | 5.14182514887 | 0 | +0.000032833616 |
| Iron | 50 | 3237 | 0 | 2.28931292917 | 19.5382494076 | 0.002725489649 | +0.000327509498 |

Halving dt reduces the measured integration errors to 0.2510/0.2511/0.2502 of
their coarse values. The retained XPBD experiment's unallocated target losses
were -2.86799/-1.60146/-10.28027 J at 100 ns. This comparison does not erase
the separate plastic return loss or establish converged fracture topology.
Glass's 15 versus 16 failed bonds remain a timestep qualification boundary.
Oak remains intact under the same declared conditions; iron flows axially.
This is an isotropic axial reference: no wood grain, metal bending/plastic
continuum, rate law or calibrated fracture-energy claim.

New target-only accumulated linear/angular residuals are at most
8.88179e-14 N s / 2.43309e-15 kg m²/s. Raw combined residuals still reach
1.84018e-6 N s / 4.11058e-7 kg m²/s, from the measured native step errors.
Native float contact transfer, reconciliation and geometry-couple accounts
remain separate. Contact phase work residual is at most 4.09058e-14 J.
These phase and experiment measurements are not full-world conservation proof.

The audited new-mode loop took 0.269–0.278 s at 100 ns and 0.537–0.557 s at
50 ns for 204.8 microseconds of simulation (about 1311–2719 times simulated
time). It includes queries, native preparation, state downloads and per-phase
audits. This is not a real-time gameplay result or a measured production budget.

## Verification and next integration

Windows x64, Visual Studio 2022 Release, MSVC 19.44, separate CPU headless
`build/agent-paid-machine`, `BANJO_BUILD_LAB=OFF`. The new compiled analytical
target checks backward Euler loss, unequal-mass harmonic motion with second-order
phase/energy refinement, a 20 s central-force rotating spring, exact ballistic
gravity, finite force/coast and named-wrench expiry/work, plastic overshoot identity
and refusal preserving an existing uploaded state. Harmonic energy errors at
5/2.5/1.25 ms are 1.01913e-5/2.54759e-6/6.36883e-7 J. Rotating-spring angular
residual is 5.77316e-15 kg m²/s; energy change is 2.66454e-14 J.

The native/target suite retains both integration modes, all three materials,
history/capture/load expiry, immutable preparation and atomic contact refusals.
New mode requires target angular residual below 1e-9 kg m²/s, integration error
below 0.1% of initial energy and a fine/coarse error ratio below 0.27. These are
bounded reference gates; old tests and tolerances are retained. The fourteen
affected compiled suites pass in 16.35 s; source registration is 296/296 with no exclusions.
The CUDA guard is registered but not GPU-compiled or runtime-qualified here.
No new app/window interaction has been installed or claimed.

The retained 8770 preview answers HTTP 200. Its runner, DLL and CLI SHA-256
hashes still match the paid-Make checkpoint; these tests did not replace them.
Final build and regression logs are locally retained under
`build/resource-flow/verlet-final-build.log` and `verlet-final-regressions.log`.
The full matched measurement output is `verlet-native-results.log`; these
local build artifacts are ignored and not published.

Focused reproduction from the repository root:

```powershell
python scripts/check-source-registration.py
cmake -S . -B build/agent-paid-machine -DBANJO_BUILD_LAB=OFF
cmake --build build/agent-paid-machine --config Release --target banjo_lattice_verlet_tests banjo_native_lattice_contact_tests --parallel 4
ctest --test-dir build/agent-paid-machine -C Release -R '^banjo_(lattice_verlet|native_lattice_contact)_tests$' --output-on-failure
```

Next add bounded native hand work and finite fixing failure to this shared
accepted clock, close complete-step rollback and grip/history handling, then
route normal crosshair object strikes and verify actual damage → paid reuse →
private save/restart. Retain terrain/paid Make and multiplayer ownership checks.
