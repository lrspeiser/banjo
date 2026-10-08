# Coupled material manifold checkpoint — October 7, 2026

**Follow-up:** [Contact-search repair and current evidence](coupled-contact-search-checkpoint.md)
supersede the broad-glass solver refusal below. All twelve coupled sustained
cases now complete; narrow-glass topology refinement remains open. This earlier
checkpoint records the original experiment and its failed acceptance.

## Scope

Experimental CPU reference, not terrain migration or completed gameplay physics.
Base main: `4ba2696dc2c3a9dca155cea2cc897e17a738d3be`. Windows x64, MSVC Release,
`build/local-cell-tools`. No renderer or running sandbox physics is changed here.

Controlled reversal of the retained sustained contact enumeration changed narrow
glass from 16/12 failed bonds (100/50 ns) to 15/9, and broad glass from 10/10 to
9/10. The experiment conditions, laws and retained acceptance bounds were unchanged.
This demonstrates order sensitivity in the sequential shared-support reduction;
it does not isolate every source of timestep error.

## Implemented experimental alternative

`evaluateFixedSurfaceManifold` builds the full shared material/source inverse
contact-mass matrix. Affine supports use actual current nodes, and one finite
native fixed tree supplies mass and inertia. Restitution targets are frozen at
pre-impact admission. Contacts are sorted for reproducibility, but sorting alone
is not the solver: bounded block iteration and a safeguarded QR/Newton residual
solve must converge before any result is returned. Static capacity is tried
first; sliding blocks then use the declared dynamic coefficient. Damping is a
search parameter, not physical drag or energy loss.

All accepted candidates audit aggregate kinetic work, finite source/target
reactions and actual fixing geometry couples. Native immutable prepare/commit
checks owner, tick, trial epoch, shape, mass, fixing anchors, velocity limits and
float-roundoff budgets. The lattice wrapper preflights its current graph union,
all node velocities and force/moment reproduction before either write. A whole
manifold counts one atomic target transfer. Unsupported or unconverged cases
refuse; there is no sequential fallback, fabricated motion or copied fracture.

## Verified boundaries

Matched glass/oak/iron instantaneous tests have identical geometry and initial
source velocity (6, 0.2, 0.1) m/s. The eight target cells are 40 mm; target masses
are 1.28 / 0.3584 / 4.02944 kg. A native iron head and oak laboratory handle use
the retained actual fixed-source construction. Two symmetric normal contacts
with prescribed restitution 1 and no friction deliver 2.95228059132 /
0.850503031189 / 8.57589099237 N s total. Independent effective-mass oracles,
full momentum/torque, and kinetic-work tests pass. Maximum work residual is
7.33e-15 J. These instantaneous oracles do not exercise stiffness or fracture.

Single-contact sticking/sliding parity, input-order equality, invalid endpoints
and masses, paired rollback, cross-world and stale-tick refusals also pass.
Five rebuilt CTest entries pass: fixed assembly, native point, native lattice,
material surface and the new registered manifold oracle entry (28.96 s total).
No complete repository, interactive, phone or cross-platform qualification.

## Failed acceptance remains visible

The original strict sustained test remains the default. The alternative is an
explicit `--coupled-manifold` experiment, never an automatic gameplay replacement.
At 204.8 microseconds and the unchanged 100/50 ns comparison, narrow iron's
integration ratio improves to about 0.201 (under the retained 0.27 bound), but
narrow glass still changes topology (19/7 failed bonds). Broad glass refuses at
a nine-contact state: residual 1.45336e-8 m/s exceeds the alternative's declared
1e-10 m/s contact accuracy. Refusal rolls back the paired trial. Neither strict
sustained convergence nor repeated iron excavation is closed by this checkpoint.
The existing absolute accounting and refinement gates are not widened.

Commands:

```powershell
ctest --test-dir build/local-cell-tools -C Release -R 'banjo_(material_surface_contact_tests|material_manifold_oracles|fixed_assembly_contact_tests|native_lattice_contact_tests|native_point_contact_tests)$' --output-on-failure
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --require-live-contact-convergence
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --require-live-contact-convergence --reverse-contact-order
build/local-cell-tools/Release/banjo_material_surface_contact_tests.exe --require-live-contact-convergence --coupled-manifold
python scripts/check-source-registration.py
```

Next: resolve redundant contact modes and event/time/geometry refinement, then
finite neighbouring ground, history-preserving handoff, cell spin, self-contact,
settling and supported soil laws. The owner now requests a fully physical,
all-target interactive world. Rigid loose-grain contact can be tested separately
from intrinsic solid fracture, but must not be presented as calibrated soil,
converged solid fracture or completion of the terrain rewrite.
