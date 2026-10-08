# Coupled contact search checkpoint — October 7, 2026

## Scope and implementation

Experimental CPU reference on Windows x64 / MSVC Release, based on main
`d5afd64f`. Publication revision is recorded in Git and the user report.
This advances the contact prerequisite for ordinary held-tool fracture in the
[world physics plan](world-physics-action-plan.md). It does not install intrinsic
fracture in the running 3D sandbox or replace the default sequential contact path.

The previous shared-support solver refused a nine-contact glass state at
1.45336e-8 m/s against its retained 1e-10 m/s accuracy requirement. Isolated
numerical investigation found a convergent response under the same Coulomb law,
but the zero-start search stalled among nearly redundant contact modes.

`evaluateFixedSurfaceManifold` now uses a bounded normal complementarity solve
to initialize the full friction search. Tentative inactive contacts stay exactly
at zero while active friction equations converge; every omitted contact is then
checked against the full law and re-admitted if violated. The initializer
explicitly removes its blocking variable at the zero bound, preventing a
roundoff-induced sequence of zero-length steps. Singular/nonfinite/exhausted
initialization returns to the original zero starting guess. A final full-law
residual check also protects against exhausting the mode budget immediately
after a contact admission or static/dynamic switch.

This changes numerical search, not contact/material laws. Cholesky, QR damping
and starting guesses add no physical impulses or dissipation. The full contact
accuracy, kinetic-work, reaction and atomic prepare/commit bounds are unchanged.
No sequential fallback, precut shards, cached outcomes or prescribed launch
motion is introduced. The bounded search can still refuse unsupported states.

## Regression inputs and reproducibility

`tests/data/coupled-glass-contact-state.txt` stores actual pre-contact inputs
captured from the failing baseline: 18 translational nodes, nine surface
contacts, two finite native source members, one fixed link, striker index zero
and dt=100 ns. It contains no fracture outcome or accepted impulse.

Format: header counts/striker/dt; each node's current/previous position, velocity,
spin and mass; each contact's node indices, point, normal, gap, static/dynamic
friction, restitution, restitution threshold and margin; each source body's
COM, quaternion wxyz, linear/angular velocity, mass and world inertia tensor;
then each link's member indices and world attachment points. Units are SI:
m, s, kg, m/s, rad/s and kg m²; coefficients and quaternion are dimensionless.

The compiled regression reads these inputs and solves them live. It independently
checks complete node/source momentum, angular momentum with the measured fixing
geometry couple, and kinetic energy with contact/reconciliation loss. It also
checks exact input-contact reversal equality. The captured state now converges
with six active contacts and work residual -1.59e-15 J. The three-material
instantaneous elastic effective-mass and single-contact friction oracles remain.

## Matched sustained experiments

Retained conditions: 40 mm cells, 27-node 120 mm target, finite iron head and oak
laboratory handle starting at (6, 0.2, 0.1) m/s, the same boundary attachments,
100/50 ns timesteps and 204.8 µs accepted duration. The local contact union uses
14–18 actual nodes. Native stepping/roundoff, clamp work and constitutive
integration corrections remain separately attributed.

| Material | Head width | Broken bonds, 100/50 ns | Integration error, 100/50 ns (J) |
| --- | --- | --- | --- |
| Glass | 40 mm | 19 / 7 — strict topology gate fails | 4.0807e-4 / 8.6878e-5 |
| Oak | 40 mm | 0 / 0 | 1.4891e-5 / 3.8318e-6 |
| Iron | 40 mm | 0 / 0 | 6.7777e-4 / 1.3616e-4 |
| Glass | 120 mm | 13 / 13 — retained comparison passes | 6.3590e-4 / 1.6519e-4 |
| Oak | 120 mm | 0 / 0 | 1.7104e-3 / 4.4852e-4 |
| Iron | 120 mm | 0 / 0 | 1.2419e-3 / 3.1660e-4 |

All twelve coupled cases complete without a contact-search refusal. Maximum
absolute attributed residuals are 3.02e-13 N s, 7.76e-16 kg m²/s and 4.19e-12 J.
These are residuals **after measured external/numerical attribution**, not proof
of exact full-world conservation. The actual source/material masses and catalog
stiffness differences are retained; the instantaneous 8-cell target comparison
has glass/oak/iron masses 1.28 / 0.3584 / 4.02944 kg. Oak remains a laboratory
comparison with its existing laws, not a brittle glass preset or organic gameplay
admission. Grain, calibrated material realism, finite cell spin and contact with
finite neighbouring terrain are not added here.

Per-case observed wall time is 0.25–2.47 s for only 204.8 µs of simulated time,
far from realtime. These isolated timings exclude browser, transport and full
world costs; concurrent verification timings are not a performance benchmark.

## Verification and remaining gates

Six rebuilt CTest entries pass in 40.65 s: fixed assembly, native point, native
lattice, material surface, manifold oracles and the new coupled material surface
entry. The new CTest entry covers complete coupled search/accounting and fails
on solver refusal; it deliberately does not claim strict fracture refinement.
The retained `--require-live-contact-convergence` remains the acceptance gate.
315/315 source registration and changed-file whitespace checks pass.

The coupled strict command and its reversed-contact command both return failure
for **one remaining narrow glass topology comparison (19 versus 7 broken bonds)**.
The original default sequential strict command still fails three comparisons.
These failures are explicit unresolved acceptance, not relaxed tolerances. Four
previous iron gameplay-repeat failures are not addressed or requalified here.

```powershell
cmake --build build/local-cell-tools --config Release --target banjo_material_surface_contact_tests banjo_fixed_assembly_contact_tests banjo_native_point_contact_tests banjo_native_lattice_contact_tests --parallel 4
ctest --test-dir build/local-cell-tools -C Release -R 'banjo_(material_surface_contact_tests|material_coupled_surface_contact_tests|material_manifold_oracles|fixed_assembly_contact_tests|native_lattice_contact_tests|native_point_contact_tests)$' --output-on-failure
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --require-live-contact-convergence --coupled-manifold
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --require-live-contact-convergence --coupled-manifold --reverse-contact-order
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --require-live-contact-convergence
python scripts/check-source-registration.py
```

Ignored logs/recording are under `build/material-lab/manifold-*`; the fixture is
tracked independently. No full repository, normal interactive window, phone,
cross-platform or real-world material qualification is claimed. Neither local
server is restarted; saved worlds and the sandbox's installed native binary are
unchanged.

Next: resolve narrow-glass fracture event/time refinement, then connect the
qualified material pipeline to ordinary player contact, preserved fragments and
later strikes. Full free-form motion/contact/fracture/debris, deformation,
structures/tools/mechanisms and water/heat/energy/pressure remain active.
