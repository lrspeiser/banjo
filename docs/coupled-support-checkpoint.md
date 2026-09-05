# Coupled support and impact-timing checkpoint

Tested code: **`1deb025dad8eb56754250de1fabba94984217080`**, September 4, 2026, America/Los_Angeles. Local branch `codex/physics-foundation`, worktree `C:/Users/henry/dev/banjo-integration`; not pushed or merged. Original main remains `3a38d7d`.

## Result and boundary

Unilateral material/plane support now joins the global elastic Newton system. The previous alternating elastic/support iteration failed the 81-node glass impact at 2 ms after 256 updates. The coupled method finishes that first impact in three updates and the full 1,285-node impact in four. No energy, momentum, velocity or gap tolerance was widened.

The endpoint contact law is unchanged. Its measured impact-phase loss and unconverged rebound prevent claiming a reliable glass collision model. The reference lacks calibrated restitution, friction, damage, automatic impact-time subdivision and Jolt activation/handoff integration. It remains separate from the default `d56611c` lab path with its correction-energy defects. Gate 1 is open; outcome/cache versions are unchanged because the reference is not used by the lab or its cache.

## Method and authority

The [elastic Newton method](elastic-newton-checkpoint.md) retains the discrete-gradient bond law and midpoint motion. Let `R` be a node's momentum-equation residual in velocity units, including gravity and other contacts but excluding support. With plane normal `n`, initial gap `g0`, timestep `h` and velocities `v0`, `v1`, set `z = v1.n + v0.n + 2*g0/h`. Endpoint gap is `h*z/2`. A unilateral reaction satisfies `R.n = lambda/m >= 0`, `z >= 0`, `lambda*z = 0`.

The residual uses tangential momentum and `min(R.n,z)` in the normal direction. Active constraints replace the normal Jacobian row with the gap equation; the block preconditioner follows the same replacement. This active-set/semismooth Newton treatment is related in method to [Hintermüller, Ito and Kunisch](https://epubs.siam.org/doi/10.1137/S1052623401383558). Their paper is an algorithmic reference, not validation of Banjo's nonconvex network or collision law.

Recover support impulses from the solved momentum equations and enter them into the external impulse, angular impulse and work ledgers. Do not apply another velocity impulse or position edit. Separating nodes have no attractive reaction. Nodes outside the finite support footprint remain free; footprint crossings reject transactionally, without invented edge geometry. Finite-sphere contacts still use the outer impulse iteration. This change globally couples material elasticity and its plane constraints, not every contact type.

`global_support_solve=false` retains the alternating implementation. The probe adds `--case free|floor`, `--support-solver coupled|split`, `--gap` (meters, nonnegative), and `--speed` (m/s, positive). Floor translation is `(0.3,-speed,0.2) m/s`, with no spin or gravity. Gap is from the lowest material node, not an ideal smooth sphere surface. Output includes normal loss, support impulse and penetration; final balances subtract accumulated external reactions/work. Rejection exits 2 and leaves unavailable balance columns blank.

## Verification

Windows Release builds successfully. All **ten CTest executables pass in 5.17 s**. The conservative suite now has seventeen checks, retaining the previous twelve and adding:

- Coupled/alternating support agreement and invariance under generic rotation, translation, rotated gravity and tangential boost; position, velocity, impulse and loss comparisons within `1e-8` in SI units.
- No attractive support, free motion outside a finite footprint, supported contact inside, and transactional rejection of footprint crossing.
- An analytical point/plane impact-phase sweep verifies that numerical normal loss is explicit.
- Five full-glass 2 ms floor steps with accumulated momentum, angular momentum and energy balances below `1e-8` in SI units; penetration below `1e-10 m`.
- A finite sphere between incoming elastic matter and support, checking single-counted reactions and mechanical balances within `1e-8`.

The lab is rebuilt and reopened after relinking; its unchanged visual path does not exercise the reference. No new remote-CI, Linux/macOS or cross-platform determinism claim is made.

## Serial probes

Actual glass, radius 0.25 m, horizon 2, occupancy sampling 3, gap 0.001 m, downward speed 1 m/s, no gravity/spin/damage. Coarse: 81 nodes/773 bonds, voxel size 0.12 m. Full: 1,285 nodes/17,097 bonds, voxel size 0.04 m. All successful rows advance **10 ms of physical time**.

| Solve / lattice / timestep | Outcome | Total wall time |
|---|---|---|
| Alternating support, coarse, 2 ms | First trial rejects: 256 outer/5,320 linear iterations; residual `0.002413 m/s` | 38.93 ms; no state advanced |
| Coupled support, coarse, 2 ms | Five steps accept; first impact 3 outer/44 linear iterations | 2.57 ms |
| Coupled support, full, 2 ms | Five steps accept; first impact 4 outer/161 linear iterations | 199.19 ms |
| Coupled support, full, 1 ms | Ten steps accept | 493.62 ms |
| Coupled support, full, 0.2 ms | Fifty steps accept | 2,078.60 ms |
| Coupled support, full, 0.02 ms | Five hundred steps accept | 4,579.03 ms |
| Coupled support, full, 0.01 ms | One thousand steps accept | 6,583.09 ms |

Full-lattice runs remain slower than real time. These are serial observations with other applications and the baseline viewer present, not isolated benchmarks. Environment: Intel Core Ultra 9 285K, Windows 11 Pro build 26200, VS 2022 x64 Release/MSVC 19.44.35228, SDK 10.0.26100, CMake 4.1.2, cached Jolt v5.6.0 and raylib 6.0. Reference physics is CPU code.

## Impact timing remains unresolved

For a free point mass approaching the plane at speed `u`, starting at gap `alpha*h*u` with `0 <= alpha < 1`, the endpoint constraint gives `v1.n = u*(1-2*alpha)` and removes `2*m*u²*alpha*(1-alpha)` of kinetic energy. At zero gap it is lossless; at half-step impact it can remove all incoming normal kinetic energy. That numerical loss is not a material restitution coefficient.

The glass sweep exposes phase sensitivity and unresolved elastic dynamics:

| Full-lattice timestep | Normal loss | COM vertical speed after 10 ms | Accumulated energy balance residual |
|---|---|---|---|
| 2 ms | 81.4178 J | +0.01409 m/s | `+7.60e-12 J` |
| 1 ms | `1.47e-11 J` | +0.96274 m/s | `-1.26e-10 J` |
| 0.2 ms | `9.06e-11 J` | +0.69629 m/s | `-1.12e-9 J` |
| 0.02 ms | `1.50e-12 J` | +0.96749 m/s | `+3.18e-12 J` |
| 0.01 ms | `2.77e-4 J` | +0.95876 m/s | `-2.24e-8 J` |

Accepted steps meet the original constitutive threshold. Maximum observed penetration is `8.33e-17 m`. The 1,000-step run accumulates momentum residuals of `2.12e-8 N s` and `3.97e-11 kg m²/s`. Per-step bookkeeping does not prove converged rebound or long-time accuracy. The finest two COM results differ by about 0.009 m/s and the sequence is non-monotonic; no convergence or calibration claim follows. Fracture is disabled in these probes.

Reproduce from the integration worktree:

```powershell
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
./build/win-integration/Release/banjo_solver_probe.exe --case floor --support-solver split --voxel-size 0.12 --dt 0.002
./build/win-integration/Release/banjo_solver_probe.exe --case floor --voxel-size 0.04 --dt 0.002 --steps 5
./build/win-integration/Release/banjo_solver_probe.exe --case floor --voxel-size 0.04 --dt 0.001 --steps 10
./build/win-integration/Release/banjo_solver_probe.exe --case floor --voxel-size 0.04 --dt 0.0002 --steps 50
./build/win-integration/Release/banjo_solver_probe.exe --case floor --voxel-size 0.04 --dt 0.00002 --steps 500
./build/win-integration/Release/banjo_solver_probe.exe --case floor --voxel-size 0.04 --dt 0.00001 --steps 1000
```

The alternating coarse case should reject. Next, resolve impact times and separate the chosen normal-contact law from numerical loss using bounded, transactional subdivision. Validate phase/timestep convergence before claiming reliable rebound. Then address sphere/material timing, friction, damage and synchronized rigid/material ownership before integrating into the lab.
