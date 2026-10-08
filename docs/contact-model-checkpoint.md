# Contact-model comparison in the voxel world

October 8, 2026. Implemented **experimental alternative**, not an accuracy fix,
calibrated contact model, realtime solver or player-world migration. Default
material-restitution contact and its retained glass-ball refusal remain intact.

## Why this comparison exists

The reference combines finite-body elastic interfaces with instantaneous,
material-derived contact restitution. Its glass-ball run refuses a positive
energy increment near impact, even at the minimum timestep. This comparison
isolates instantaneous restitution as a factor: the alternative uses the same
native unilateral normal constraint with restitution zero, existing friction,
and unchanged material interfaces. Elastic recovery can come from deformation
of those interfaces. There is one native response per surface contact.

This is a distinct declared model, **not a correction that makes the reference
accurate**. In particular, an isolated rigid-cell collision is now inelastic.
The model has no compliant normal-contact indentation or Hertz response; it
cannot stand in for a converged deforming continuum. Large losses persist.
No lost work is renamed as calibrated material heat. Contacts with anchored
supports use the same declared model and retain reaction/torque observations.

The declaration is `contact_law: "resolved-deformation"`; default omission
means `"material-restitution"`. Unknown names/types refuse creation. The native
API accepts a bounded enum only before bodies or support history exist. Both
new and persisted contact callbacks use it. Impact metadata reports the
selected response, and the journal retains the declaration and source hash.
Material display names choose no new behavior. Bulk density, stiffness,
strength and damping, friction, geometry, solver iterations, fracture work and
energy gates are unchanged. No shards, launch velocities or motion are authored.

## Verification

The rebuilt native oracle suite has **62 scenarios** across inline and
thread-pool execution and retained interface laws. New equal-cube glass/oak/
iron contact checks compare analytical separating velocity, kinetic loss and
linear/angular momentum for both response models. For zero restitution,
two equal 0.1 m cubes at opposing 1 m/s velocities lose the initial normal
kinetic energy (2.5 / 0.7 / 7.87 J). The reference retains its catalog-derived
restitution (0.777139 / 0.459929 / 0.562774 respectively). Configuration after
body creation is rejected instead of changing existing contact history.

Three material-dependent density fixtures also exercise real contact followed
by elastic assembly recovery. Two 0.1 m cubes joined by a declared 1000 N/m,
zero-damping spring hit a fixed support at 1 m/s, without gravity or friction.
At dt 1/960 s for 400 steps, upper-body upward velocities reach 0.967838 /
0.940144 / 0.981744 m/s, and peak stored elastic energy reaches 1.20989 /
0.329054 / 3.86319 J. These are intentionally declared spring oracles, not the
catalog's calibrated stiffness. Maximum energy excess is zero in these runs;
the new oracle bounds native-float roundoff at 1e-5 J. No existing energy
gate or tolerance is relaxed. This proves interface recovery exists even
with inelastic surface constraints; it does not certify full impact physics.

Seven scoped CTests pass in **373.01 s**: work oracles, native interfaces,
six new contact-model experiments, eleven reference worlds plus retained
refusal, gateway, pipeline and playback. The six added recovery oracles were
subsequently rebuilt and run in the same suite; they pass. The default
glass/oak/iron/ice comparison against the published executable matches all
physical **and work** fields at 120 observations through two seconds.
Only runtime profiler fields and the new `qualification/contact_law` label
are excluded. No full-repository, phone, other-OS or cross-GPU claim.

## Matched world measurements

Windows x64/MSVC Release CPU, continuous-small-rotation OFF. Same conditions:
40 × 40 cm, 4 mm, 8 × 8 / 64-cell sheet, 32 cm support gap; 1 kg iron
constituent ball dropped 10 m; host dt 1/960 s, 96 velocity iterations.
All rows complete two physical seconds with every original cell ID/mass kept.

| Sheet | Wall s | Substeps | Sheet pieces | Spring work + elastic change J | Contact work J | Unclosed E J | P residual N·s | L residual N·m·s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Glass | 68.518 | 59,223 | 8 | -47.018777 | -33.531106 | -80.544058 | 0.00162850 | 0.00119699 |
| Oak | 7.270 | 6,106 | 1 | -19.698671 | -24.908354 | -44.677462 | 0.00010784 | 7.31104e-7 |
| Iron | 6.901 | 5,326 | 1 | -58.327328 | -25.339493 | -83.633500 | 0.00020352 | 7.28028e-6 |
| Ice | 25.761 | 32,016 | 64 | -41.507146 | -54.785847 | -96.327646 | 0.00181216 | 8.58409e-5 |

P/L values are norms of the actual accumulated full-world residuals after
active gravity/support reactions. They are **reported unresolved defects**,
not newly admitted conservation bounds. Algebraic work closure is not proof
of constitutive validity. The remaining signed work terms stay in the record.

Sheet masses remain 1.600 / 0.448 / 5.0368 / 0.58688 kg. Density is
2500 / 700 / 7870 / 917 kg/m³; Young's modulus is 70 / 12 / 211 / 9 GPa.
Common geometry and those inputs determine interface/mass differences. Oak
remains an elastic comparison, with no grain law or organic gameplay enablement.
Iron still has no persistent plastic dents/yield/tearing in this experiment.

The reference glass row costs 39.692 s in this checkpoint, with its prior
41,823 substeps, 12 pieces and -92.923298 J deficit. The new model is **slower**
for that pair. Comparison checks ran concurrently; no speedup is claimed.

### Glass constituent ball

With a 1 kg **glass** ball and the same glass sheet, the new contact model
completes instead of reaching the reference refusal. At dt 1/960 s it takes
17.443 wall s / 20,010 substeps, with 12 sheet pieces and 13 ball pieces.
Energy deficit remains **-96.462860 J**: spring work plus elastic change
contributes -14.292587 J and contact work -82.166038 J. P/L residual norms
are 0.00183685 N·s / 4.95898e-6 N·m·s. Completion does not validate that loss.

At dt 1/1920 s it takes 26.337 s / 31,560 substeps, with 11 sheet pieces and
18 ball pieces. Energy deficit remains -96.003110 J, P/L residual norms
0.00260042 N·s / 8.66141e-6 N·m·s. Different fragment counts and persistent
losses leave timestep/continuum convergence unqualified. Reference glass-ball
refusal stays exactly retained at 1.427663485 s, h 6.357828776e-8 s, depth 14;
no reference tolerance, impulse, gate or fracture threshold changes.

## Test website and next work

The actual 3D website adds **Contact response**. Instant bounce is the reference;
Unilateral is explicitly experimental. Glass balls are selectable in the latter
only. Switching back restores an admitted iron-ball setup. Changing a model
creates a fresh scene and journal, rather than mutating contact history.
Physics & record explains the inelastic boundary, large losses and unsupported
indentation; the build manifest distinguishes experimental completion from
blocked accuracy/speed. Rendering still consumes only native accepted poses.

The next accuracy work is a coupled material/contact integrator with a declared
normal-surface compliance and auditable elastic/dissipative state, preserving
support reactions, finite-cell spin and all energy/momentum accounts. It must
recover elastic energy without this large instantaneous/numerical loss, and
pass timestep/resolution comparisons rather than only completing a drop.
Reducing the global substep cost remains necessary. Persistent metal plasticity,
adaptive cell transfer and validated custom geometry/material authoring remain
required, with the full active goal intact.

Source registration is **331/331**, no exclusions. New Python experiments are
registered CTests; every affected C++ source/test is built by its CMake target.
Native SHA256:
`adfeda1cb18ec7b741b5160a730c9cbbf35fb34a5d69798ebc72201cd4b11560`.
Local evidence is retained in `build/voxel-unilateral-results.json`,
`build/voxel-unilateral-ctest.log`, `build/voxel-unilateral-baseline.log`
and `build/voxel-unilateral-recovery-oracles.log`. Artifacts stay out of Git.
The website manifest pins the verified source revision and executable hash.
