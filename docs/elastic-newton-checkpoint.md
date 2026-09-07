# Global elastic solve checkpoint

Later checkpoint: [coupled support and impact-timing evidence at `1deb025`](coupled-support-checkpoint.md). The wall times and the 1/60 s rejection recorded below were independently reproduced, and the timestep acceptance boundary located, in the [realtime envelope checkpoint](realtime-envelope-checkpoint.md): the boundary for the full 1,285-node glass lattice is 7.046 ms (1/142 s), not a cliff at 1/60 s. The free-elastic measurements below remain historical evidence; the support solver and probe now have additional capabilities.

Tested code: **`dc7bcfb6b9d9392bdf19e82e0baa48e53e0b16cc`**, September 4, 2026, America/Los_Angeles. Local branch `codex/physics-foundation`, worktree `C:/Users/henry/dev/banjo-integration`. Main remains `3a38d7d`; this work has not been pushed or merged.

## Result and scope

The conservative CPU reference now solves the whole elastic network with Newton iteration and a preconditioned GMRES linear solve. The full 1,285-node glass-preset lattice accepts 2 ms steps and 1/240-second steps in the isolated translation/spin probe. The old per-bond sweep failed even the 81-node glass case at 2 ms. Energy, momentum and penetration acceptance budgets have not been widened, and failed trials still leave the input state untouched.

This improves numerical convergence, not the material model. The default interactive experiment still uses the separate-correction implementation at `d56611c`, including its documented unphysical correction energy. The reference still lacks friction, prescribed restitution, damage evolution, automatic step subdivision and shared Jolt activation/handoff. Gate 1 remains open. No outcome/cache version changes: the new reference is not part of cached lab simulations.

## Method

The [previous reference](conservative-reference-checkpoint.md) defines the discrete-gradient spring impulse, midpoint position update and independent ledgers. Those equations are retained. Newton solves the nodal velocity equations with current contact/support impulses held fixed; the existing normal-contact iterations then update those impulses. Both parts must converge before the independent ledgers can accept a step.

For starting bond separation `q0` and relative midpoint displacement `d`, compute the length increment as `dot(d, 2*q0+d)/(|q0|+|q0+d|)`. This avoids subtracting almost equal endpoint lengths when stiff materials develop tiny strains. The elastic residual uses these relative coordinates. Its analytical tangent supplies a matrix-vector product assembled from bond blocks; no dense global matrix is stored.

The tangent is generally nonsymmetric. The linear method uses restarted GMRES with a 40-vector Krylov basis, per-node 3-by-3 block-Jacobi preconditioning, two passes of modified Gram-Schmidt and Givens rotations. The algorithmic reference is the [Netlib Templates description of GMRES](https://www.netlib.org/linalg/old_html_templates/subsection2.6.3.4.html). Banjo's code and physics acceptance tests are its own implementation.

Each Newton update permits at most 400 linear iterations by default. A relative linear residual of `1e-5` controls the search direction only. A backtracking line search requires a smaller nonlinear residual or attainment of the final velocity tolerance. The outer limit remains 256 updates. Acceptance still requires `1e-9 m/s` constitutive residual, the original relative energy/momentum budgets and `1e-10 m` penetration limit. The global residual measures each node's complete momentum equation in velocity units; the retained local solver measures consistency of each stored bond impulse, also in velocity units. These residual metrics should not be treated as identical, despite sharing a numerical threshold. Neither can bypass the independent mechanical audits.

`ConservativeStepSettings::global_elastic_solve=false` retains the local method for numerical comparisons. `maximum_linear_iterations` bounds one global update; `ConservativeStepResult::linear_iterations` reports the total Krylov work across the trial. The probe exposes `--solver newton|local` and `--linear-iterations` alongside its existing size, timestep and outer-iteration options. Failed probes exit 2; a blank energy-residual field means the mechanical balance was not reached.

## Verification

Windows Release builds successfully. All **ten CTest executables pass in 5.05 s**. The conservative suite now has twelve checks, retaining the nine previous analytical/contact/frame/rejection cases and adding:

- Agreement of the local and global elastic trajectories for an unequal-mass, non-collinear network over 20 steps, within `1e-8 m` and `1e-8 m/s`.
- Second-order trajectory convergence against the independent harmonic solution for two unit masses joined by a 100 N/m spring, over 0.2 s. The position errors at 20, 10 and 5 ms are `4.99849e-4`, `1.26373e-4` and `3.16823e-5 m`; velocity errors are `2.36206e-3`, `5.83370e-4` and `1.45381e-4 m/s`. Each refinement must reduce both errors by a factor between 3.8 and 4.2.
- The actual glass preset at 1,285 nodes/17,097 bonds, five 2 ms steps, with accumulated momentum/energy differences below `1e-8` in their SI units. This case also checks that insufficient Newton/Krylov budget rejects without changing positions or velocities. No wall-time threshold is baked into the test.

These tests do not establish glass calibration or accurate high-frequency vibration at millisecond steps. The radial convergence result applies to its stated reference, not every mode of the glass lattice. There is no new Linux/macOS, remote-CI or cross-platform determinism claim.

## Serial glass probes

All probes use the actual glass preset, radius 0.25 m, horizon 2, occupancy sampling 3, translation `(0.3,-0.1,0.2) m/s`, spin `(1,-2,3) rad/s`, and zero gravity/contact/damage. The coarse voxel size is 0.12 m; the full size is 0.04 m. Normal-impact convergence on a stiff sampled target remains to be measured separately.

| Case | Result | Outer / total linear iterations per step | Observed wall time per step |
|---|---|---|---|
| Local, 81 nodes/773 bonds, 2 ms | Rejected; residual `2.48858e-6 m/s` | 256 / 0 | 94.74 ms |
| Newton, same coarse case, five 2 ms steps | All accepted | 3 / 62 | 0.495–0.553 ms |
| Newton, full lattice, 100 steps at 2 ms | All accepted; 0.2 s simulated | 3–4 / 426–555 | 49.87–69.02 ms; median 60.34, p95 66.83 ms |
| Newton, full lattice, 120 steps at 1/240 s | All accepted; 0.5 s simulated | 4 / 296–979 | 39.35–114.56 ms; median 54.22, p95 109.93 ms |
| Newton, full lattice, 1/60 s | First step rejected; residual `4.37003e-9 m/s`; no state advanced | 19 / 6,688 | 894.03 ms |

Over the accepted 100-step 2 ms sequence, total delta-P is `5.42e-14 N s`, delta-L is `1.41e-10 kg m²/s`, and delta-E is `-5.28e-10 J`. Over the 120-step 1/240-second sequence, the corresponding values are `3.57e-14`, `2.43e-8` and `-9.11e-8`. The latter's accumulated angular/energy drift illustrates why per-step acceptance alone is not a long-time accuracy guarantee. Maximum per-step velocity residuals are `9.82e-11` and `9.72e-10 m/s`, respectively.

The 2 ms sequence takes 6.00 s of wall time to advance 0.2 s; the 1/240-second sequence takes 7.19 s to advance 0.5 s. These are **not real-time results**. Measurements were serial with other applications and the original baseline viewer present, not an isolated benchmark. Machine: Intel Core Ultra 9 285K, Windows 11 Pro build 26200, MSVC 19.44.35228, Windows SDK 10.0.26100, CMake 4.1.2, VS 2022 x64 Release; cached Jolt v5.6.0 and raylib 6.0. The reference is CPU code. The integration viewer is reopened after relinking; this unchanged visual path does not demonstrate the new reference.

Reproduction from the integration worktree:

```powershell
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
./build/win-integration/Release/banjo_solver_probe.exe --solver local --voxel-size 0.12 --dt 0.002
./build/win-integration/Release/banjo_solver_probe.exe --voxel-size 0.12 --dt 0.002 --steps 5
./build/win-integration/Release/banjo_solver_probe.exe --voxel-size 0.04 --dt 0.002 --steps 100
./build/win-integration/Release/banjo_solver_probe.exe --voxel-size 0.04 --dt 0.004166666666666667 --steps 120
./build/win-integration/Release/banjo_solver_probe.exe --voxel-size 0.04 --dt 0.01666666666666667 --steps 5
```

The local and 1/60-second cases intentionally report rejection at this checkpoint. Next, measure and improve stiff sampled contact/support convergence and normal-impact timing, with explicit rollback/subdivision. Profile the global linear work without weakening audits; add friction/restitution/damage and synchronized rigid/material ownership before replacing the defective default lab path. Preserve timestep/material calibration as separate acceptance work.
