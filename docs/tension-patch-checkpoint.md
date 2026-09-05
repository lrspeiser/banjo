# Atomic tensile patch impulses

Experimental runtime foundation, September 5, 2026. Local source `b948acc85607ab82a483240ca3c8ab42bbff1999`; not pushed or merged. Full project goal active.

`applyCohesiveTensionPatchKick` accepts 1..256 caller-compiled body-local attachment sites, with individual reference lengths, areas and histories. It reuses `CohesivePatchSite`. The common law area is ignored in favor of each site's area. All sites are evaluated from one pair of poses. Their impulses and torques are accumulated, then both complete velocity candidates are checked for finite representation, Jolt speed limits and the supplied transfer-roundoff budget before either body is changed. Updated constitutive histories are returned only with an accepted transfer. The single-site API delegates to this operation.

The pure `applyAttachmentImpulses` computes total impulse, each body's total torque, and midpoint point work using the shared before/after velocities. This includes cross-site work terms that would be missed by adding independently solved single-site energy changes. Full world inertia tensors and the net couple remain in the audit. Jolt surface ownership, double positions, zero cohesive compression and no deferred activation are still required. The bodies remain awake while the external scheduler calls this operation.

## Measured boundary

Tests retain glass, oak and iron at the same declared geometry and conditions. The pure reference checks analytical net impulse/torque, rotated full-tensor covariance, reversed site order, four-way same-point impulse subdivision, work closure and angular accounting. The runtime fixture uses two 0.1 m cubes separated by 0.122 m, reference length 0.12 m and total area 0.001 m2, distributed 25/75 percent over two asymmetric local sites. Declared compliant onset/failure openings remain 0.005/0.02 m, using catalog density and Gc; these are not calibrated bulk material joints. One 0.001 s kick produces the analytical net translation and nonzero spin. Reversed site order and four-way same-point area subdivision agree within 1e-7 in tested velocities.

An invalid final site, empty/oversized patch and invalid/insufficient budget reject without changing either body's velocity or caller histories. Existing single-site failed-bond collisions, coupled tension/contact trajectories, opening accuracy and generic pair impulse tests remain regression coverage.

| Material | Signed patch transfer energy error J | Momentum error | Angular error |
|---|---:|---:|---:|
| Glass | -1.59181e-15 | 0 | 0 |
| Oak | -9.23228e-11 | 0 | 0 |
| Iron | -4.72069e-9 | 0 | 0 |

Zeros are measured values for this symmetric body-pair fixture, not exact-conservation guarantees. Same-point subdivision checks area/impulse accumulation; it does not establish spatial quadrature convergence. Pure frame-covariance coverage does not establish arbitrary-orientation live trajectories.

## Application and remaining work

This is one between-step pair update, not whole-world transactional stepping, multi-pair rollback or thread-safe concurrent mutation. The caller remains responsible for valid face geometry, area provenance, history persistence, timestep choice, full force/work integration and releasing sleeping responsibility. No creator/starter code invokes it yet. Existing assembly declarations with compression and `cohesive_patch_only` are not silently reinterpreted.

Next add an explicit compatible assembly contact policy, synchronized patch integration and immutable candidate histories across a complete step. Verify asymmetric finite-area trajectories with spin and third-body contact before enabling material/energy-backed live crafting. The first-person inventory, XP/levels, stamina and tool loop remains the application target; realistic branch cutting, physical process energy, calibrated wood grain/plasticity and the remaining platform gates are open.

## Build verification

All test executables and the runtime cohesive probe were rebuilt in the promoted double-position configuration. All 27 suites pass in 23.99 seconds. Windows 11 / MSVC 19.44 x64 Release / CMake 4.1.2 / Jolt 5.6. The already-running graphical applications were not relinked or restarted in this checkpoint; this operation has no application caller yet. No new native gameplay validation is claimed.

The retained single-position test executables/probe were also rebuilt; all 25 legacy suites pass in 19.83 seconds. In that configuration the tensile runtime API is unsupported and its test verifies rejection rather than running the double-position physics fixtures.
