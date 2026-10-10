# Articulated motion and exact equilibrium reference

October 10, 2026. **Implemented bounded CPU reference; shared-world mechanisms remain unfinished.**
Prepared from main `c79bcb847cc4d618191af160036f23f6e1cebfc1`; the outgoing integration revision must be recorded by the publishing checkpoint. This document does not claim that all representation families or their couplings are complete.

## What the user can test

The actual 3D `/mechanisms` laboratory contains one occupied rectangular rigid bar on an ideal fixed-axis pin. Edit its length, width, thickness, density, initial angle/spin, gravity, constant world-direction tip force, applied torque and event times. Calculate and inspect Before, accepted physical frames and After. Playback selects computed native states and never extrapolates or supplies a prescribed angle. The visible reference grid has no collider. Removing the support lets the same body translate and spin freely; it does not hit the visual grid.

- **Gravity swing:** a displaced bar swings through its actual joint coordinate without damping or angle assignments.
- **Sleep → push:** an exactly stationary, supported stable equilibrium keeps its complete state. At the declared load time, the applied force wakes it and produces measured motion.
- **Remove support:** support removal transfers its current COM position/velocity and intrinsic spin to free rigid motion. No velocity or energy is reset. A moving-body release has independent regression coverage.

The arrows show measured pin reaction impulse divided by the native timestep, with normalized display length. Their direction comes from the accepted response. They are neither resolved stress nor temperature. Geometry is one actual rigid occupied box; the visible outline does not imply hidden fracture voxels.

## Native mechanics and accounts

[`MechanismCpuApi.cpp`](../src/physics/MechanismCpuApi.cpp) compiles as `banjo_mechanisms_cpu` and exports a bounded FP64, renderer-independent ABI. [`mechanisms.py`](../scripts/mechanisms.py) validates SI declarations, records stable `mechanism-bar` and `mechanism-bar:occupied-box` identities within the experiment, and supplies accepted poses, velocities, mode transitions and receipts. This is an initial-scene reference adapter, not a durable installed-object registry or the current coupled-sheet solver.

Mass is `density × length × width × thickness`. COM inertia about the hinge axis is `m(length² + width²)/12`; pin inertia includes the exact parallel-axis term `m(length/2)²`. Glass/oak/iron/ice defaults select density only. They do not add rigidity calibration, grain, fracture, ice melting or metal plasticity.

For a supported bar, a discrete-gradient integrator solves the nonlinear pendulum equation. Gravity and constant world tip forces use the angle-integrated torque, including the zero-angle limit; applied torque contributes its measured work. A contractive interval bound refuses unresolved large force/timestep combinations. This conserves the modeled energy while admitting second-order temporal error; energy conservation alone does not prove the trajectory.

The support reaction is the bar's measured linear-momentum change minus gravity/applied-force impulse. Angular impulse accounts include the same joint response and the fixed pin's lever arm about the common world origin. The fixed pin performs zero work. Support removal retains COM and angular motion, then evolves free translation and rotation under the actual external force/torque. All steps audit modeled energy, linear momentum and angular momentum with external work and support reactions. Failed native steps leave output buffers unchanged; the stateless request publishes no partial trajectory on refusal.

**Sleep admission is deliberately exact:** zero angle, zero angular velocity, fixed support, no transverse force or drive torque, and a stable or neutral equilibrium. The omitted-motion bound is exactly zero for this declared model. An arbitrarily small nonzero vibration remains awake. No settling law or damping is fabricated to create sleep. Heating, changing material histories and deformable-support wake propagation are not connected.

## Verification and measured boundaries

Windows 11, MSVC 19.44 Release, Python 3.13.5. Native SHA256:
`09301102570e6d69e527e332343b87c24d72018dafcb17b5afdfb1909e7fbdbd`.
Read-only runtime source receipt: `6fee5dc86e34f7a550aa647fb580d2719b061d5e1388fa5ec7663fef9a8551cd`.

[`windows.json`](evidence/mechanisms/windows.json) records the same 1 m × 0.12 m × 0.05 m, 35° initial angle, gravity 9.81 m/s², 1/480 s timestep, two-second experiment for all retained materials:

| Density label | Mass kg | Whole-run energy residual J | Max angular residual N m s |
|---|---:|---:|---:|
| Glass | 15.000 | 2.84e-14 | 9.01e-15 |
| Oak | 4.200 | 7.11e-15 | 2.88e-15 |
| Iron | 47.220 | 5.68e-14 | 2.76e-14 |
| Ice | 5.502 | 7.11e-15 | 3.93e-15 |

The mass-independent gravity trajectory agrees across these density controls. Applied torque changes the trajectory with actual inertia. Native + Python calculation of each two-second control takes approximately 3–5 ms locally, excluding HTTP, serialization and rendering. This is not evidence of whole-platform realtime or Render performance.

Independent tests cover constant-torque rotation, small-angle analytical pendulum motion (2.25e-10 rad discrepancy at the declared tiny amplitude/timestep), radial load producing no rotation, exact equilibrium, delayed-force wake, stationary and moving support removal, invalid fields and native output-buffer preservation. Common-time errors against 1/1920 s for a 70° pendulum at 1/120, 1/240 and 1/480 s are respectively 2.715e-4, 6.709e-5 and 1.598e-5 rad, approximately fourfold improvement per halved step. Release energy residual magnitude stays below 3e-11 J in these controls.

[`mechanisms_test.py`](../tests/mechanisms_test.py) exercises the compiled library; [`mechanisms_view_test.mjs`](../tests/mechanisms_view_test.mjs) rejects incoherent mass/geometry, changed matter identity, missing 3D trajectories, unqualified sleeping motion and physical-time extrapolation. Ordinary browser, source registration and integrated server identity verification are completed by the publishing checkpoint; their results must not be inferred from these unit tests.

## Remaining work

General multi-body joint graphs; movable supports; deformable attachment matter and stress-triggered promotion; joint breakage; qualified contact/friction; state persistence through the shared object registry; full inertia/arbitrary 3D axes; thermal/reaction fields while mechanics sleep; fluid-to-wheel reaction/work exchange; exact shared-time coupling with the current material solver; GPU implementation and full delivery/render performance. Reattaching a moving free body is refused because it needs an implemented impact law.

The ideal pin is an explicit physical assumption, not a modeled metal post. An outcome is solved from parameters and accepted state rather than selected from a material-name animation. This first functioning reference advances families 1 and 3; it does not complete their general platform requirements.
