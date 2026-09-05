# Declared assemblies tested in a temporary Jolt world

Local source `c7aa5d9`, September 5, 2026; not pushed or merged. Full platform goal active.

Assembly declarations now accept the explicit `tension_with_jolt_surfaces` contact policy. It requires zero cohesive compression; nonzero compression rejects before a draft is accepted. The existing `cohesive_patch_only` policy retains its original isolated reference behavior. Assessment reports the selected policy and still reports live creation unsupported. Both policies can be remembered and round-tripped without changing their meaning.

The existing public `test_assembly` command now dispatches the new policy to test version 2, `jolt-tensile-patch-separation-v1`. This constructs a temporary two-box Jolt world from compiled face geometry and material-derived mass/inertia. It uses each site's compiled area, local attachment and reference distance. Both bodies start with separating normal velocity and zero total COM velocity; there is no gravity. Symmetric half-kicks surround one Jolt drift per step, and accepted site histories move together. Jolt retains its surface contacts. Any exception discards the temporary trial, without modifying the caller's world, inventory, draft or clock.

## Contract and limits

Version 2 requires exactly these specification fields: `test_version: 2`, `relative_kinetic_energy_j`, `duration_s`, `steps`, `energy_error_budget_j`, `transfer_roundoff_budget_j`, and `minimum_separated_area_fraction`. Initial requested energy is positive and at most 10000 J; duration is positive and at most 1 second; steps are 1..4096. Geometry remains bounded to the existing two-box, at most 256-site compiler. Initial relative speed is bounded to 100 m/s and runtime limits can reject a trajectory. Double positions are required; legacy builds may assess/save the declaration but reject its runtime test.

The integration budget is positive and at most 1 percent of input energy; the per-kick transfer-roundoff budget is nonnegative and cannot exceed it. The report includes the requested and actual duration (the latter uses float-representable Jolt steps), runtime signature, final bodies/site histories, energy and momentum measurements, and separate pass predicates for separation fraction and maximum integration-energy error. Version 1 specifications cannot silently select this solver, and version 2 cannot select the old policy.

The energy report separates the full KE+stored+damage change, signed transfer roundoff, Jolt-stage KE change and maximum remaining integration residual. Jolt-stage change includes numerical effects and is not automatically heat. Contact-event counts can include speculative events. Passing is limited to the requested separation and integration criteria; momentum is diagnostic, not a new general conservation certificate. This is fixed-step testing, not an adaptive whole-world rollback engine.

## Comparative evidence

Glass, oak and iron use the same 0.02/0.03 m box geometry, 0.001 m face gap, 0.01 by 0.012 m patch and 4 by 4 sites. Catalog density, strength and Gc set illustrative laws with K=2*S*S/Gc. Initial separating energy is 6*A*Gc; duration is 8*df/relative_speed. These catalog-based examples are not calibrated material joints or a wood-grain/plasticity model.

| Material | 512-step maximum integration error J | 1024-step error J | Final damage work J |
|---|---:|---:|---:|
| Glass | 1.291873e-7 | 5.481736e-8 | 0.00096 |
| Oak | 1.614796e-5 | 6.851816e-6 | 0.12 |
| Iron | 0.001614823 | 0.000685191 | 12 |

All finest cases separate completely, retain A*Gc within 1e-12 relative tolerance and satisfy the specified 1e-4*A*Gc integration budget. Coarse errors are larger; two resolutions do not prove convergence order or spatial convergence. Reordering the parts array preserves body results through referenced IDs. Tight budgets cannot pass, oversized step counts reject, duplicate compression rejects and policy persistence round-trips. Real CLI command files for all three materials pass, with before/after saved caller worlds JSON-identical.

Rebuilt affected creator, starter, assistant and precision-conversion tests pass in both configurations: four suites in 4.83 s (double) and four in 4.17 s (legacy). The legacy path tests rejection of unsupported runtime precision; it does not validate this fixture's dynamics. Windows 11 / MSVC 19.44 x64 Release / Jolt 5.6. The promoted creator CLI was rebuilt and exercised. Existing graphical applications were not restarted; no new native interaction or LLM request is claimed.

## Next application boundary

The creator can now assess, save and physically test this declared policy through its public API. Live resource-backed creation, persistent runtime joints, adaptive multi-pair stepping, supports/third-body interactions and a complete energy source/process ledger remain open. Next validate asymmetric patch trajectories and define persistent joint state before enabling a craft transaction. The first-person collection, XP, stamina, tools and eventually realistic branch cutting remain the application target. Default fracture defects, calibration, publishing and all other goal gates remain open.
