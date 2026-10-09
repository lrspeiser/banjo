# Coupled GPU finite cells â€” October 9, 2026

## Implemented and measured

The separate `/coupled` 3D page runs a resident FP64 CuPy implicit body/material/contact solve. The existing CPU material world and published native binary are preserved. No Jolt or PhysX solver writes these bodies; the shared trial equations own their reactions. Jolt has no automatic conversion to CuPy. Library scope and primary references remain in [GPU migration](gpu-migration-plan.md).

Nine connected 10 mm cubes form a 30 Ã— 30 Ã— 10 mm slab on two fixed iron supports. A density-derived sphere drops on it. Each cube has six dynamic degrees of freedom, material-derived mass and isotropic inertia. Glass, oak and ice have 48 mixed-mode cohesive quadrature sites (12 shared faces, four sites per face); iron has 12 six-mode perfect-plastic connectors. This is a small assembly reference, not the original large thin-sheet experiment or an admitted general material engine.

[Machine-readable evidence](evidence/gpu-coupled/results.json) records source SHA, material conditions, measured work and runtime. Windows 11 / MSVC 19.44 / RTX 5090 / CUDA driver API 13.3 / CuPy 13.5.1 / NumPy 2.5.3. Repository base `6a599afa9ed612714af04c9966f4a70a5282ece0` plus this checkpoint. The publication commit is the commit containing this note; runtime `/api/checkpoint` reports its exact revision. No macOS, physical-phone or cross-GPU validation is inferred.

Same conditions: iron ball 0.01 kg, 1 mm initial surface clearance, host dt = 1/240 s, ten host ticks = 0.0416667 physical s. Adaptive private steps are bounded; every accepted physical step passes its own gates. Ball trajectories differ from unimpeded gravity after contact. None of these low-energy drops fracture or yield; this is NOT evidence of impact fragmentation or denting.

| Material | Wall seconds | Final full energy residual Â· J | Maximum step energy residual Â· J | Separated sites / yielded faces |
|---|---:|---:|---:|---:|
| glass | 39.484 | -1.668e-14 | 1.670e-14 | 0 / 0 |
| oak | 27.667 | 2.073e-16 | 1.912e-16 | 0 / 0 |
| iron | 58.213 | -4.313e-15 | 4.325e-15 | 0 / 0 |
| ice | 28.663 | 2.802e-16 | 2.795e-16 | 0 / 0 |

These timings are individual measured verification runs, not a stable throughput benchmark. They are dramatically slower than realtime. GPU use alone has not solved the performance problem.

## Shared equations and model assumptions

`CoupledGpuKernel.hpp` is compiled by an actual CMake CPU oracle target and embedded without FMA in CuPy NVRTC. CUDA batches the finite-difference Newton candidates; one thread evaluates a whole candidate with race-free body gathering. This bounds the reference at 32 bodies / 128 interfaces. Dense finite-difference Newton and serial per-candidate traversal are deliberate correctness scaffolding, not the final high-throughput architecture. A 16 KiB CUDA call-stack capacity is explicitly set: the default 1 KiB caused an illegal-address failure during development. There is no CPU execution fallback.

Translation uses implicit midpoint. Orientation uses a unit Cayley midpoint increment and isotropic world inertia. Interface coordinates use reference displacements and incremental rotations so micron-scale strains do not subtract rounded absolute positions. Rotation remains away from the SO(3) pi branch.

Integrated constitutive loading work comes from existing shared cohesive/connector laws. Midpoint forces/torques are corrected by a discrete-gradient projection in the internal pair space, orthogonal to rigid translation and rotation. Its declared length scale weights angular versus translation increments. The correction preserves pair linear and angular momentum and makes pair work equal to the constitutive work. It is a numerical integration differential, not a post-step velocity assignment, artificial damping, launch impulse or changed material potential. Consistency under finite rotation and full timestep/resolution convergence still require qualification.

Glass/oak/ice use the existing effective-opening potential shape `sqrt(<normal>+Â² + 0.5 Ã— tangentÂ²)` with four face Gauss sites. The ratio 0.5 and reference attachment frame are explicit common experiment inputs. This finite attachment adapter is not an exact port of the triangular corotated facet geometry. Oak retains catalog density/stiffness/strength/fracture energy but has no grain, wood plasticity or calibrated bulk failure. This comparison does not reintroduce wood into gameplay. Iron retains perfect-plastic connector history and separately accounts its numerical return excess; it is not bulk J2 plasticity, hardening or tearing.

Contact is one authoritative frictionless compliant response per pair, summed across declared surface samples. Its linear normal stiffness is `2/(1/Ea + 1/Eb) Ã— min(characteristic length)`; it is not Hertz calibration. Sphere/plane/sphere-box gaps are geometric; boxes use four interior Gauss points per face with signed distance to the other shape. Normal stiffness is divided by four for box/plane and eight for two-sided box/box quadrature. SAT/distance rejects endpoint-disjoint pairs. This replaces the nonsmooth extreme-corner support spring exposed by the first Newton trial. Edge-only overlap may evade quadrature; contact branch changes and full impact accuracy remain open. The interval travel limit is a conservative guard, not certified continuous collision detection.

## Admission, recordings and verification

Newton solves energy-weighted endpoint velocities entirely on CUDA, with a strict 1e-10 Ã— max(1, velocity norm) equation tolerance. Initial 1e-7 sqrt(J) finite differences crossed microscopic damage/compression ranges and produced an inappropriate secant Jacobian. A 1e-12 scaled perturbation resolves the tested FP64 local branch. Neither material stiffness nor energy tolerances were relaxed. Derivative-scale/refinement qualification outside these controls remains required.

Each physical step accounts for kinetic, gravitational, material and contact stored energy, physical constitutive dissipation and numerical return excess. Support impulse/torque and gravity are external reactions. Energy gate: 1e-10 J + 1e-8 Ã— max(abs(initial total stored/mechanical energy), 1e-3 J). Linear and angular residual norms must be <= 1e-9 NÂ·s / NÂ·mÂ·s. Compression <= 20% of minimum shape scale, travel <= 25%, angular increment <= 0.25 rad. Private subdivision never changes laws. A requested interval rolls back completely on refusal; reset is then required. A poisoned CUDA context reports that GPU rollback is unconfirmed while the prior accepted host snapshot remains intact.

Every accepted microstep records actual poses, velocities, material histories, work, support reactions and residuals. The website draws only accepted geometry; Before/Live uses the actual initial/accepted states. Its camera redraw remains independent while CUDA solves. No precut shards, cached fracture trajectories or fake animation is used.

- Compiled CPU test: 424 contact geometries, all 12 independent pose derivatives, torque/force reactions; 1000 randomized pair work/P/L corrections.
- GPU test: 12 nontrivial whole-scene CPU/CUDA trials compare every pose, force, residual, material state and ledger; measured scaled difference is zero in these inputs.
- Four matched low-energy coupled drops and four analytical freefall material controls pass; conservation is checked at every microstep.
- A deliberate failure after one private accepted step restores the entire two-tick interval, including material histories, not just its last step.
- Existing checked constitutive ports, finite-frame gradients/PhysX delivery, normal compliance and native face/rotation tests remain required regression gates.

## Remaining work and next actual experiment

1. Profile CUDA candidate kernels, dense linear solve, host synchronization and adaptive refusal drivers independently. Move derivatives/body gather into sparse parallel resident kernels; preserve exact reference results before claiming speed.
2. Qualify implicit contact/manifold consistency, finite rotations and timestep/geometry resolution with sustained contacts and off-axis impacts. Replace surface-sample edge gaps with a qualified manifold/CCD path.
3. Run higher-energy same-condition glass/oak/iron/ice impacts, unloading and later collisions. Demonstrate actual broken connectivity and permanent geometry only when full work/P/L and refinement pass. Low-energy contacts are not those demonstrations.
4. Generalize connected islands, topology lifecycle and adaptive cell geometry; keep the reference and bounded declarative inputs.
5. Thermal/fire, fluid momentum/water wheel, phase changes, power and gameplay/authoring remain unimplemented or unqualified in this backend. The full near-realtime material objective is active.

Final verification: ten distinct scoped CTests pass (coupled contact, rotation, native face spring, compliance, GPU laws/frames/coupled, gateway/pipeline/playback); 345/345 source registration; CUDA memcheck smoke reports zero errors. The normal browser UI completed ten steps and its downloaded journal retained all 37 microsteps. Before/Live and camera orbit remain available. GPU CTest timings while this browser verification was active are not standalone performance qualification.
