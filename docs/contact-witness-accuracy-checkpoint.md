# Contact witness and work accuracy — October 7, 2026

## Scope

Baseline main `91897380c80ce45b7fec3be7eca4642017441f45`, Windows x64,
MSVC Release, pinned Jolt v5.6.0, double world positions. This continues
[small-rotation qualification](native-small-rotation-checkpoint.md) toward the
[free-form 3D physics objective](world-physics-action-plan.md).

This checkpoint adds measured diagnostics and regressions. It changes no
material/contact/integration law, tolerance, outcome key or demo. Sustained
contact/fracture acceptance is still failing; the running worlds are unchanged.

## Implemented diagnostics

`NativeContactAccuracyResult` now retains the actual full/two-half values,
absolute bound, scalar/vector kind and last attempted interval for its worst
comparison. Vector comparisons preserve three components rather than replacing
them with an unexplained norm. Target contact work, linear impulse and angular
impulse have distinct metric names and units. Comparison arithmetic and admission
bounds are unchanged. Glass/oak/iron regression cases reproduce the normalized
error from both scalar and vector receipts and verify refusal does not commit.

The retained `--controlled-manifold` experiment records:

- actual seed, gap, normal, surface witness and envelope centre;
- actual source centre/orientation before response;
- each contact's target work, native delivery correction and loss receipts;
- full and two-half intervals at 100 ns, 100 ps and 1 ps;
- a paired no-time-advance reapplication using identical witnesses;
- a paired 1 ps two-half trial with identical first-step witnesses, preserving
  native and material stepping while isolating the fresh geometry query.

All isolation trials roll back. Frozen witnesses are explicitly diagnostic:
they are not a valid geometry cache for moving production objects, and are never
used by the accepted controller or ordinary world actions. Partial/error traces
are labelled; native-only isolation and existing mass/P/L/E bounds remain.

## Matched evidence and cause

All six controlled failures select **target contact work**, not linear or angular
impulse. The experiment retains 40 mm cells, a 120 mm / 27-node target, nine
far-face clamps, 40/120 mm iron heads, the laboratory oak handle, initial velocity
(6, 0.2, 0.1) m/s and no gravity/damping. Target masses remain glass 4.32 kg,
oak 1.2096 kg and iron 13.59936 kg. Catalog density/stiffness remains glass
2500 kg/m³ / 70 GPa, oak 700 / 12 GPa, iron 7870 / 211 GPa. Oak remains a
comparison laboratory material without grain or organic gameplay.

The continuous-small-rotation build still stops at 5.4125 / 5.429898 / 6.075 µs
for narrow glass/oak/iron and 5.728125 / 6.110004 / 5.8875 µs for broad cases,
against 204.8 µs required. All have zero broken bonds. Narrow oak exhausts
100,000 accepted intervals; the other five exhaust accuracy refinement.

Broad oak's seed 12 surface witness changes from approximately
(0.04003534685, 0.00000084283, 0.00000047444) m to
(0.04003539528, -0.01999929650, -0.01999962575) m after a 0.5 ps half step.
That is **28.2844 mm along the face**, while other witnesses move about
picometres. The second contact transfers 0.105675894 J with a new native query.
With no stepping and identical geometry, its second projection transfers only
6.89147e-9 J. With identical native/material stepping but the first witnesses
retained, the second contact transfers 1.84562e-7 J. All other cases' fresh and
retained-witness 1 ps work agrees within 2.26e-10 J. This paired experiment
isolates the broad-oak jump from native stepping, without qualifying a retained
witness model for production.

This identifies a representative-witness/load-distribution discontinuity, not
a fracture or large physical displacement. It does not prove every native
witness must be continuous across genuine feature changes. The current native
query uses float local collision geometry and Jolt's default 1e-4 m GJK collision
tolerance; the search margin is 1e-5 m. Its single GJK/EPA representative point
can switch within a nearly parallel face and substantially change affine nodal
loading. Reducing dt does not qualify that reduction through this switch.

The other five 1 ps trials have at most 2.05e-12 m witness changes, but nonzero
second-contact work (2.10e-7 to 1.50e-6 J). Identical-geometry, zero-time
reapplication leaves additional work from zero to 2.43e-7 J, with explicit
native delivery corrections. Source float state, native joint stepping and
material time integration therefore remain separate numerical qualifications;
the trace does not assign all small errors to geometry or prove a complete cure.

## Verification and remaining work

Both legacy and continuous-small-rotation builds compile the affected target.
Three registered surface-contact, coupled-contact and manifold-oracle CTest
entries pass in each build, including the new scalar/vector/refusal regressions.
Final scoped CTest wall times are 16.77 s legacy and 16.85 s experimental.
Controlled attributed residual maxima remain 2.29e-14 N s,
2.08e-16 kg m²/s and 1.80e-12 J, within the retained 1e-9 SI / 1e-10 J bounds;
these numerical/support accounts are not proof of full-world conservation.
The explicit controlled experiment still returns 1 with six open gates, as
required. Source registration remains 315/315 across 31 CMake files. PR #2 is
merged at `138260d2`; its pinned conservative checkpoint was reread.

```powershell
cmake --build build/agent-point-separation --config Release --target banjo_material_surface_contact_tests --parallel 4
ctest --test-dir build/agent-point-separation -C Release -R 'banjo_(material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles)$' --output-on-failure
build/agent-point-separation/Release/banjo_material_surface_contact_tests.exe --controlled-manifold
cmake --build build/local-cell-tools --config Release --target banjo_material_surface_contact_tests --parallel 4
ctest --test-dir build/local-cell-tools -C Release -R 'banjo_(material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles)$' --output-on-failure
python scripts/check-source-registration.py
```

Large traces stay ignored under `build/material-lab/`; the final isolation log
is `contact-witness-fixed-step-final.log`. Published revision is recorded in Git
and the user report. This is not full regression, interactive/phone testing,
cross-platform qualification, material realism or successful live fracture.

Next: replace ambiguous single-point face loading with a bounded actual contact
patch representation, verify geometry/response convergence through the captured
near-parallel case, and resolve source delivery/constraint precision separately.
Preserve all existing law/work/conservation/refinement gates; do not freeze
witnesses, omit work comparisons or enlarge tolerances to claim acceptance.
Then qualify ordinary live strikes, persistent constituent fragments and useful
speed. Deformation/structures/mechanisms and fluids/heat/energy/pressure remain
part of the complete active objective.
