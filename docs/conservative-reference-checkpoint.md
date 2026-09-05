# Coupled conservative reference solver

Tested code: **`1d29545035b50a32f5596274dfc9c10cded848bc`**, September 4, 2026, America/Los_Angeles. Local branch `codex/physics-foundation`, worktree `C:/Users/henry/dev/banjo-integration`. Original main remains `3a38d7d`; this work is not pushed or merged. The Windows Release toolchain and dependencies are unchanged from the preceding checkpoints: MSVC 19.44, Windows 11 build 26200, Jolt v5.6.0, raylib 6.0.

## Result and boundary

`tryConservativeStep` is a new CPU reference for elastic material plus an optional finite-mass sphere and static support. Bond forces and normal-contact impulses determine the same midpoint position update. It does not push nodes out of overlap after solving elasticity. Accepted steps must meet constitutive, energy, momentum and contact-gap tolerances; a rejected solve preserves every input node and sphere state.

**It is not yet the interactive lab's solver.** The default experiment still uses the implementation at `d56611c` with the correction-energy defects documented in the stage checkpoint. The new reference lacks friction, prescribed restitution, damage evolution and Jolt activation/handoff integration. Its convergence and cost at practical glass timesteps are inadequate. Gate 1 remains open.

## Method and explicit contracts

For a bond with rest length `L`, compliance `c` and endpoint separation vectors `q0`, `q1`, its stored energy is `U=(|q|-L)^2/(2*c)`. The impulse on its second endpoint over step `h` is:

`J = -h/(2*c) * (|q0|+|q1|-2*L)/(|q0|+|q1|) * (q0+q1)`.

This discrete-gradient impulse has work `-ΔU` under the midpoint position update. It is central about the midpoint separation, so the pair's angular reaction balances. The implementation solves each nonlinear bond locally and iterates the coupled network, recomputing the final constitutive residual independently. The approach is related to the energy/momentum methods analyzed for central-force systems by [Gonzalez and Simo](https://web.ma.utexas.edu/users/og/PUBLICATIONS/paper_Stab.pdf); Banjo's network/contact solver and evidence are its own implementation, not validation supplied by that paper.

The sphere and material start at the same time and advance together. Normal contact is enforced through nonnegative impulses in the coupled solve. Finite-step normal constraints may remove energy; `normal_contact_loss_j` records that numerical loss. **This is not a calibrated restitution law** and collision timing can affect the loss. A successful ledger does not establish correct rebound across timesteps. Gravity is integrated at the midpoint; support impulse and torque are included in the selected system boundary. Intrinsic cell spin is retained, and isotropic sphere spin advances its orientation.

Initially overlapping contact states are rejected beyond tolerance. Swept paths through the sphere are rejected even if their endpoints lie outside it. A step crossing a finite support footprint boundary is rejected for subdivision or a future general-contact handler. The reference has no automatic subdivision yet. Positive finite masses and compliant live bonds are required; arbitrary fixed-node constraints, self-contact, multiple rigid shapes and moving supports are not implemented here.

Default acceptance settings:

- At most 256 nonlinear sweeps and `1e-9 m/s` constitutive velocity residual.
- Energy residual below `1e-9` times the larger of 1 J and the initial elastic plus relevant kinetic energy. Isolated bodies use kinetic energy relative to their common COM; a stationary support uses its preferred frame. The arbitrary potential-energy zero does not set this budget.
- Linear/angular momentum residuals below `1e-9` of their declared reference scales, with a unit SI floor and explicit gravity/support reactions.
- Contact penetration below `1e-10 m`.

These are declared numerical acceptance settings, not material accuracy or universal coordinate-scale guarantees. Large steps can converge to an inaccurate trajectory; physical timestep convergence remains necessary. `balance_measured=false` distinguishes failure before the balance audit from a measured zero residual.

## Tests at the source checkpoint

Windows Release builds successfully, and all **ten** CTest executables pass (4.74 s for the full run). The new executable contains nine checks:

1. A radial spring matches the independent scalar midpoint solution at four timesteps, with displacement/velocity error below `1e-12` in SI units.
2. A rotating spring retains energy and angular momentum over 100 steps, including a spatial offset, boost and intrinsic cell spin.
3. A non-collinear, unequal-mass tetrahedral spring network retains momentum/energy over 20 steps.
4. An elastic floor impact balances kinetic/strain/gravity energy and external linear/angular reactions while enforcing the contact gap.
5. A finite sphere supplies strain energy to an elastic target while both advance on the same clock; total COM motion, momentum and energy balance are checked.
6. Insufficient iteration budget and a sphere-crossing trajectory are rejected without mutation.
7. Off-center contact remains consistent under rotation, translation and a velocity boost; sphere orientation advances.
8. A sampled 81-node elastic lattice passes ten steps. This fixture deliberately uses a softer modulus and is not glass calibration.
9. A deliberately loose iteration stopping rule cannot bypass the independent energy audit; the unresolved network is rejected unchanged.

Multi-step/frame comparisons use absolute momentum/energy tolerances of `1e-8` in their SI units; the sampled network uses `1e-7`. Existing lab, material, contact and transfer tests still pass. There is no new remote-CI or Linux/macOS claim. The normal lab was rebuilt and reopened; its unchanged visual path does not demonstrate the new reference kernel.

## Actual-glass convergence and cost probes

`banjo_solver_probe` generates the ordinary glass-preset lattice with horizon 2, initial translation `(0.3,-0.1,0.2) m/s`, spin `(1,-2,3) rad/s`, and no gravity/contact/damage. Unlike the softer unit fixture, this uses the preset's stiffness. It records acceptance, iterations, residual and wall time. Failed probes exit 2 and leave the trial state intact; an empty energy-residual field means the balance stage was not reached.

| Lattice / step | Measured outcome |
|---|---|
| 81 nodes, 773 bonds; `h=0.002 s`, 256 sweeps | Rejected; residual `2.48858e-6 m/s`; 94 ms |
| Same; 2,048 sweeps | Rejected; residual `1.07344e-6 m/s`; 743 ms |
| Same; `h=0.00002 s`, five steps | Accepted in 12–15 sweeps; 3.29–4.53 ms per step |
| 1,285 nodes, 17,097 bonds; `h=0.00002 s` | Rejected after 256 sweeps; residual `8.06542e-9 m/s`; 1,580 ms |
| Same full lattice; `h=0.000002 s`, five steps | Accepted in 5–6 sweeps; 18.86–32.12 ms per step |

The accepted full-lattice sequence measured total delta-P `3.18e-14 N·s`, delta-L `1.92e-14 kg·m²/s` and displayed delta-E `0 J` at printed precision. Only 10 microseconds of physical time were advanced. This proves neither long-time stability nor a real-time runtime. Timings are serial wall observations on the existing Windows machine with other applications present, not an isolated benchmark. The many scalar-root evaluations and slow network iteration are concrete optimization targets; do not widen tolerances or remove the rejection checks to claim speed.

Reproduction:

```powershell
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
./build/win-integration/Release/banjo_solver_probe.exe --voxel-size 0.12 --dt 0.002 --iterations 256
./build/win-integration/Release/banjo_solver_probe.exe --voxel-size 0.04 --dt 0.000002 --steps 5
```

The first probe is expected to reject at this checkpoint. Next, improve the nonlinear solve/preconditioning and root-evaluation cost while retaining the reference tests; establish step-size convergence and normal-impact timing/restitution. Then integrate friction, damage, activation and shared rigid/material ownership into the lab, with rollback and explicit resource limits. Only after that work can the reference replace the known-defective default path and support a Gate 1 completion claim.
