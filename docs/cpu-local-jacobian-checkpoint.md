# Bounded CPU local Jacobians

October 9, 2026. Execution optimization of the existing equations, based on main
`7fdd7ad7e709097aa0b13ef32c1d2c910cf1c42e`. Strong impact, full-world realtime
and the eight representation families remain unfinished.

## Implementation

A fresh private baseline is built within each native derivative request. A
single-body velocity perturbation recomputes that body's prepared pose, incident
material interfaces and incident shape pairs. Unchanged rows reuse their exact
private contributions under the same bodies, geometry, histories, laws, dt and
gravity. All rows gather in the original reference order. There is no subtraction
from cached total forces, cross-time outcome reuse or accepted-state mutation.
The shared material/contact kernels, Newton limits and physical gates are
unchanged. Full native trial evaluation remains available as reference.

The additional C ABI is bounded to 32 bodies, 128 interfaces and 384 candidates,
with at most 48 sites per shape pair. Row storage is private to the request;
allocation failure refuses rather than crossing the ABI with an exception.
Every undeclared second-body change, including signed zero, refuses before
output is touched. Allocation-failure injection is not claimed by these tests.

Two measured boundary defects in the draft were repaired before publication:
an early rotation refusal must leave the caller's unwritten history suffix
unchanged, and signed-zero prescribed mass must retain the reference signs in
gravity components. Tests retain both witnesses with nonzero-prefilled buffers.

`local-jacobian` is a CPU pipeline choice. The 3D lab selects it on initial CPU
setup and retains Full CPU reference in Solver settings. Declaration, exact
restart and the shared nonlinear controller understand both choices. Identity
continues to include source, native binary and NumPy version; old incompatible
saved scenes are explicitly refused. No CUDA/native fallback is introduced.

## Measurements and verification

Windows: MSVC 19.44 Release, Python 3.13/NumPy 2.2.6. Linux: GCC 13.3 Release,
WSL Ubuntu 24.04, Python 3.12/NumPy 1.26.4. Separate audited CMake targets compile
the native API. Seven warmed measurements per candidate batch are medians;
accepted ten-tick comparisons alternate local/full execution. These are local
measurements, not Render or general-world realtime qualification.

Matched 13-body, nine-cell sheet controls use material-derived mass/stiffness,
a 10 g iron sphere, 1 mm clearance, 240 Hz host steps and the reference contact
clock. The 120-candidate private derivative batch is measured at 960 Hz.

| Material | Windows full/local batch ms | Linux full/local batch ms | Windows full/local ten ticks s |
|---|---:|---:|---:|
| glass | 70.76 / 15.20 | 41.18 / 8.84 | 10.04 / 2.42 |
| oak | 70.15 / 14.80 | 43.16 / 8.45 | 15.65 / 3.86 |
| iron | 69.46 / 14.75 | 40.92 / 8.20 | 15.06 / 3.65 |
| ice | 71.31 / 15.43 | 41.64 / 8.60 | 6.88 / 1.67 |

Ten ticks are only 0.04167 physical seconds. The roughly fourfold improvement
still leaves these material calculations far slower than realtime.

Windows and Linux each pass 2,400 matched candidates across glass/oak/iron/ice,
including large finite trials and original fault codes 1/2, exact accepted
histories/work/reactions and exact restart/next-step parity. Tests retain maximum
body/candidate/interface requests, the empty graph, signed-zero and prefilled
failure buffers, and refusal without output mutation. The actual difficult glass
root matches the full reference's result and updates within each platform;
Windows/Linux are not claimed bitwise identical.

Ten scoped Windows/CUDA CTests pass: local CPU Jacobians, CPU world/high-drop/
gateway/CUDA parity, coupled view, retained GPU world/representations/high-drop
and registry. Source registration passes 346/346. This is not a complete repository
CI run, macOS test, physical-phone test or cross-GPU determinism claim. Normal 3D
browser tests complete 10 m fall/rebound using both CPU choices and retain replay.

Evidence: [Windows](evidence/cpu-local-jacobian/windows.json),
[Linux](evidence/cpu-local-jacobian/linux.json), and
[complete strong-refusal records](evidence/cpu-local-jacobian/strong-refusals.json.bz2).
Each report identifies its installed source/binary through the implementation
hash and records per-material conditions, density-derived mass/stiffness and
momentum/energy diagnostics. Comparable low-energy accounts are byte-identical
to the full reference; that is numerical parity, not material calibration.

## Strong impacts and remaining work

The same 0.1 kg iron ball / 10 m clearance / 240 Hz / 0.0625 rad contact-phase
sheet attempt still hits the unchanged interval trial/time budget before impact:
glass/oak/ice retain 0.004167 physical s and iron 0.008333 s. No accepted fracture
is observed. The archived refusals preserve the actual last accepted state and
rejected trials. These refined-contact setups are not equivalent to earlier
reference-clock 10 m attempts; their early support-contact failure remains a
separate unresolved case. Do not advertise this optimization as a smash fix.

Next: resolve actual support/contact continuation and strong-impact convergence,
compare completed material trajectories under temporal/spatial refinement, then
bind occupied ball matter and damaged-fragment histories to qualified contact.
Equilibrium/reduced modes must retain prestress and vibration; articulated,
thermal/reaction and flowing-matter bindings remain required. Oak grain,
continuum metal plasticity and arbitrary geometry remain unsupported here.

The same public 3D test website must be checked after publication. A main push
alone does not prove the current image is live or that browser/API controls pass.
