# Device-status GPU linear solve — October 9, 2026

## Delivered implementation and boundary

The coupled 3D lab offers **Linear solve → Resident cuSOLVER · Windows** alongside the retained **CuPy reference** default. Both use FP64 pivoted LU and triangular solution of the same current Newton matrix. Material laws, contact law, ranked starts, ordered line search, physical gates and work bounds are unchanged. The CPU material world is unchanged.

`scripts/gpu_linear_solve.py` owns reusable factor, pivot, workspace, solution and device-status buffers for dimensions 1–192 on CUDA device 0 and one ordered stream. Input matrices/vectors remain unchanged. CUDA guards retain invalid input, singular factor, nonfinite factor and invalid/nonfinite solution status. A private identity/zero substitution only prevents unsafe triangular solution after a fault; that result is rejected, never admitted as a physical direction. There is no CPU numerical fallback in `enqueue`.

The installed CuPy 13.5.1 wrapper explicitly refuses cuSOLVER calls during stream capture. A separate, typed Windows x64 bridge calls the already-loaded NVIDIA library with its actual ABI; it does not modify CuPy's wrapper flags. The bridge checks cuSOLVER 11.7.5 and refuses other unverified versions. Actual CUDA command capture/replay is tested with changing inputs, singular input and recovery. It reuses executable commands, **not cached physical outcomes**. This is a prerequisite for resident nonlinear control, not its completion. The coupled caller still reads the combined status and controls Newton convergence/backtracking on the host.

NVIDIA documents the pivoted factorization, triangular solve and device error information in its [cuSOLVER reference](https://docs.nvidia.com/cuda/cusolver/index.html). Installed headers and runtime checks establish this checkpoint's narrower version/ABI scope; current online documentation alone does not prove capture on this installed runtime.

## Verification and measurements

Environment: Windows x64, RTX 5090, driver 610.88, CUDA toolkit 12.9, CuPy 13.5.1, NumPy 2.5.3, cuSOLVER 11.7.5. Base main revision: `f1f1f251b24ddead5bb94bb5d32960d59ed4bd9a`. Coupled source digest: `31105d759be71507d256aac805caf643c5cf21e9895669e3d122819e96a0b33d`. The source includes the new helper in both worker and website verification keys. Evidence is saved under [gpu-resident-linear](evidence/gpu-resident-linear/).

The CMake-registered `banjo_gpu_resident_linear_tests` checks 90 matrices: ten dimensions, dense/symmetric/scaled inputs and C/F/strided layouts. Results match `cp.linalg.solve` exactly; the maximum independent relative backward residual is 3.513e-16. Input/factor faults, alias/dtype/shape rejection, fault recovery and stream ownership are checked. Three actual CUDA graphs each process four fresh matrix/RHS inputs; singular replay and recovery retain their device statuses.

Eight paired material-world experiments retain glass/oak/iron/ice: a 0.01 kg iron ball at 1 mm clearance, dt 1/240 s for 0.041667 physical s, and a 0.1 kg iron ball at 5 mm clearance, dt 1/960 s for 0.104167 physical s. Backend order alternates each tick. Every accepted pose, velocity, material history, reaction, work and Newton record matches exactly; final resident arrays match byte for byte. The actual previously recorded glass line-search refusal also matches both paths after excluding backend/status metadata. Existing per-microstep P/L limits of 1e-9 and scale-dependent energy tolerance remain unchanged.

Single paired wall measurements are modest: low/strong glass 2.049/9.677 s versus 2.004/9.071 s; oak 1.103/3.455 versus 1.021/3.237; iron 5.181/13.997 versus 4.877/13.315; ice 0.522/3.129 versus 0.486/2.960. An earlier low-energy probe made oak/ice slightly slower. These are not statistical speed qualification and are nowhere near realtime. Reference remains default. Profiling of the preceding published source shows the matrix phase is only about 10–12% of wall time; scalar CPU waits remain substantial. Event/host timing intervals overlap and must not be added as independent costs.

Fifteen scoped CTests pass in 652.29 s; source registration is 345/345 with zero exclusions. CUDA memcheck reports zero errors and racecheck zero errors/warnings, executing matrix guards, fresh-input graph replay, the actual glass refusal and four material worlds. Maximum per-microstep residuals across the eight direct paired histories are P 1.023e-11 N·s, L 1.392e-13 N·m·s and energy 2.003e-13 J. The scoped CTest transcript, CUDA sanitizer results, registration and normal browser/journal evidence accompany this checkpoint. This is scoped verification, not the entire historical repository suite or cross-GPU/phone validation. Native matrix parity preserves the existing numerical trajectory; it does not establish that trajectory's material accuracy.

## Remaining work

Move nonlinear norms, decisions and local tangent work onto CUDA without accepting faulted directions or weakening whole-interval rollback. Reduce dense global work with verified local/sparse structure. Qualify connected material/contact temporal error and root selection: refined sheets still exceed bounded work, and previous timestep/root experiments changed trajectories and ice fracture outcomes. No new fracture/dent realism, oak grain, continuum iron plasticity/tearing, adaptive cells, thermal/fluid/fire/phase-change or power law is qualified here. Full-world near realtime remains OPEN.

For Jolt, CuPy, Newton/Warp, PhysX and other library roles, see the [GPU migration assessment](gpu-migration-plan.md). Jolt remains the CPU reference; there is no automatic Jolt-to-CuPy constitutive conversion.
