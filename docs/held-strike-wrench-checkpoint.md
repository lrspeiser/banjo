# Force, wrist torque and named source accounts — October 2, 2026

## Implemented boundary

This extends the [finite force input](held-strike-load-checkpoint.md) with CPU
`setExternalWrenches`: named, disjoint sets of schedule node indices, a world
point in metres, force in newtons, free torque in newton metres, and a finite
shared substep span. Both CPU backends recompute the nodal loads from current
geometry before every kick. Each source retains requested/delivered linear and
angular impulse, signed work and loaded elapsed time. Source labels identify
accounts; they are not player authorization.

This is a distributed load model. It does not implement local finger traction,
6DOF fixings, native hand feedback, an avatar reaction or held-object fracture.
The source reaction remains the caller's obligation: use the negative delivered
impulse/moment, not the requested values. Separate source ledgers make those
accounts available; they do not physically apply a reaction or persist it to a
player. The C ABI, LLM tools, normal tool clicks and running 8770 preview are
unchanged. **R3 object destruction and damaged-tool reuse remain open.**

## Mapping, assumptions and refusal

For selected masses `m_i`, total `M`, centroid `c`, offsets `r_i`, point `p`,
force `F` and free torque `T`, the moment about the centroid is
`tau = T + (p-c) cross F`. The point-mass inertia is
`I = sum m_i (|r_i|² identity - r_i r_i^T)`. Solve `I alpha = tau` on its
sampled directions, then apply `f_i = (m_i/M) F + m_i (alpha cross r_i)`.
Thus the resultant is `F` and its world moment is `p cross F + T`.
No node position, bond state, speed reset or material law is assigned.

The point/force/free torque are fixed in world coordinates for the declared
span. This is not a moving or feedback-controlled hand; the native caller must
update its input on the accepted simulation clock. Selection defines the load
region. It is not automatically the entire fixed tool or all of its components.

Tensor scaling and existing symmetric eigendecomposition avoid a dimensional
determinant threshold. Eigenvalues at or below `1e-10` of the largest are
treated as unsampled/ill-conditioned. Unresolved torque above
`1024*epsilon_double*|tau|` refuses. Resultant/moment checks use `1e-10` of
their absolute constituent sums. These are new mapping/conditioning bounds,
not changes to constitutive/contact tolerances. Geometry is recomputed each
step; a later rank loss refuses before velocity or ledger publication.

Duplicate/missing source labels, duplicate/out-of-range nodes, overlapping
regions, zero-span nonempty input, nonfinite/unrepresentable fields and active
loads on immovable nodes refuse. Invalid replacement preserves the previous
load. Sources/nodes have canonical ordering. Zero wrenches are inactive; cancel
preserves accumulated receipts and upload clears them. Input replacement can
change modes between anonymous per-node forces and named wrenches; anonymous
work has no named source receipt. Aggregate timing counts loaded substeps once,
while each simultaneous source has its own elapsed span; do not sum their
elapsed times as world time. Ledger/work overflow preflights all sources and
the aggregate before any velocity is written. CUDA refuses nonempty inputs.

## Matched analytical measurements

Windows x64 / VS 2022, MSVC 19.44.35228.0 (MSBuild 17.14.51), Release CPU, `BANJO_BUILD_LAB=OFF`,
`build/agent-paid-machine`, baseline `bb4dd42` plus the revision recorded below.
Retained glass/oak/iron densities are 2500/700/7870 kg/m³ and moduli
70/12/211 GPa. The existing bonded-load cases remain retained; no law or
calibration changed. The new rigid oracle has **free translational point nodes**:
120 mm cube, 27 cells at 40 mm, no gravity/support/damping/contact, four
constraint iterations, one `dt=1e-7 s` kick. Origin (2, 0.6, -1) m;
point offset (0.02, -0.03, 0.04) m; force (20, -10, 5) N;
free torque (0.5, -0.75, 1.25) N m. Point inertia is `M*(4/3)*h²` per axis.

| Material | Mass kg | Point inertia kg m² | Work J | Double work residual J | Float work residual J |
|---|---:|---:|---:|---:|---:|
| Glass | 4.32 | 0.009216 | 2.3912218e-12 | -3.23117e-27 | -3.48927e-20 |
| Oak | 1.2096 | 0.00258048 | 8.5400778e-12 | 3.23117e-27 | -2.89376e-19 |
| Iron | 13.59936 | 0.029011968 | 7.5960031e-13 | -2.01948e-28 | 3.93980e-20 |

Analytical work is `0.5*dt²*(|F|²/M + |tau|²/I)`. Bounds are 1e-20 J in
double and 1e-6 relative in float; momentum 1e-16/1e-11 N s and angular
four times those. Maximum final-minus-delivered angular residual is
8.47033e-22 kg m²/s double and 1.97028e-13 float. This is point inertia:
finite voxel self-spin/inertia is absent. It is not native rigid-body equivalence.

A separate oak free-node run starts with translation (3,-2,1) m/s and chosen
spin (0,30,0) rad/s, without continual spin assignment. Two disjoint sources
act for 64 of 128 substeps at the same dt. Reordered sources/nodes and both
CPU backends produce identical states. Each source's requested and delivered
moment retains its fixed world-wrench value despite the changing geometry;
source impulse/moment/work sums agree with the aggregate. Final momentum
residual is 5.32454e-14 N s and angular residual 1.16371e-13 kg m²/s
(bounds 1e-10). Sample wall time 0.0003217 s for this tiny run, not a
game-scale performance claim. A 125-node, 200 mm free cube exercises actual
parallel node phases above their 64-node dispatch threshold for all three
materials and both precisions, with 16 loaded / 64 total substeps and exact
CPU parity. Origin shifts (1e6,-2e6,3e6) m and 90° coordinate rotations
retain physical loads and the world-origin angular translation rule.

Rank tests admit a representable transverse torque on collinear point nodes
and refuse axial twist. An analytical later rank invalidation verifies atomic
refusal; it is not a physical collapse experiment. Source-ledger overflow,
invalid replacement, expiry, cancellation, upload and zero-wrench identity
are tested. Localized bonded energy residuals remain the unclosed values
reported in the prior checkpoint. No whole-pipeline conservation, realistic
fracture, wood grain, physical hand or multiplayer gameplay claim is added.

## Verification and next integration

```powershell
cmake --build build/agent-paid-machine --config Release --target banjo_lattice_external_load_tests banjo_fast_lattice_tests banjo_lattice_plasticity_tests --parallel 4
ctest --test-dir build/agent-paid-machine -C Release -R '^banjo_(lattice_external_load|fast_lattice|lattice_plasticity)_tests$' --output-on-failure
python scripts/check-source-registration.py
git diff --check
```

All 15 named load cases pass, including seven new wrench/source cases. Existing
lattice/plasticity suites pass: 3/3 CTest targets, 8.69 s on the final rerun. Registration 288/288.
Only previously present alignment/shadow/getenv warnings appear. PR #2 was
checked live: merged, head `138260d2f3d2e30a112f28034731db6052ae1720`;
its contact checkpoint remains a historical experimental qualification.

Next preserve the actual native striker inertia, finite fixings and source
reactions while coupling contact into the target material. A collinear handle
cannot gain finite-cell axial spin by relabeling point inertia, and spreading
the root grip load over all fixed constituents would bypass the fixing's load
path. Retain native rigid striker dynamics and couple its one contact response,
or explicitly implement/audit the missing angular degrees before conversion.
Then synchronize hand/controller and fracture elapsed time, remap surviving
grips after damage, expose object targets and qualify the full paid reuse flow.
No item is removed from the five remaining player goals by this checkpoint.

## Publication

Implementation `0ebba84cf15ab1c73fbd84eabdefed455faace19` is published on GitHub
main. The recorded tests were built from those exact implementation sources;
the following publication record changes documentation only. Preview 8770 was
confirmed HTTP 200 with unchanged R2 runner/DLL hashes. This is not a deployment
of held-tool object destruction.
