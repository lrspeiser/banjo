# Generated starter tool — September 30, 2026

Implementation `0fa2b9a` follows the [Workshop ground-tool contract](workshop-ground-tools.md). This is a usable-tool checkpoint; the larger progression goal remains active.

## Implementation

New named worlds get one oak Field pick near arrival. It is an explicit bootstrap gift, not a learning reward. Its source is the `field-pick` Workshop assembly, also available in Recipes. Default geometry is an 800 × 50 × 50 mm haft and 50 × 50 × 300 mm arm, face-connected, sampled at 50 mm into 22 cells / 0.00275 m³ / 1.925 kg. The builder and ordinary installation share `fixed_lattice_plan`; placement uses measured terrain under the whole footprint, then ordinary native admission checks the point and connected matter.

The generic component-frame declaration supplies grip/use anchors. Inventory takes and re-equips any authored object using its declared grip rather than its centre. Explicitly authored interaction anchors still take precedence. No forced launch velocity, manufactured fracture, timestep or material law changes were introduced.

Existing saved worlds and the older shipped `new-game.json` are not retroactively given a tool. The named New Game generator uses the new builder. A private world already saved with failed receipts remains refused; this change does not rewrite it.

## Measured Windows player route

Python 3.13.5, Windows 11, MSVC 19.44 CPU Release runner built from `f819e81`; source under test `0fa2b9a`. `AutonomousGuests.test_generated_starter_tool_can_be_taken_re_equipped_and_used_through_player_routes` creates two generated named worlds. Only seed selection is pinned. It uses authenticated ordinary take-up, stow, equip, survey and tool-use requests; the ordinary clock advances the native hand. No resources, snapshots, ground outcome or evidence are injected. This is scripted acceptance, not autonomous model play.

| Terrain / goods seed | Initial tool centre, m | Measured work, J | Sand removed, m³ | Soil removed, m³ |
|---|---|---:|---:|---:|
| 7 / 851269742 | (0.95227, 0.825, −0.72273) | 58.42453 | 0.016307715822450396 | 0.00008225750851535533 |
| 4 / 1 | (1.25227, 0.825, 0.42727) | 60.73312 | 0.020205271691574784 | 0 |

Both closed supported ground records contain positive work/removal. The other guest gets no evidence. Reopening the page rejoins the same session with its point unchanged. A separate native check opens both generated scenes, takes their actual grip and verifies whole-snapshot restart preserves point/body state exactly. Reported player positions are client poses, not physical avatar bodies or a collision/path proof. Host scheduling changes hand settle boundaries and numerical yield; these are recorded runs, not bitwise timing promises.

Seven tool checks also retain glass/oak/iron installation and material-derived mass comparisons (6.875 / 1.925 / 21.6425 kg), corruption refusals, state preservation and the existing flat-ground oak physical test. No iron/glass swing performance is inferred from their mass/admission checks. The raw ground-volume account residual remains zero in that oak fixture; ground work remains declared, uncalibrated and limited to supported dry soil/sand. This is not full-world conservation or strength/fracture certification.

## Verification and remaining work

- Workshop tool suite: 7 pass, including both generated native scenes and restart.
- Focused generated authenticated player test: 1 pass, both seeds, zero provider calls.
- Existing native Workshop installation: 39 pass.
- World-seed suite: 24 pass; its resource/rover reachability proof is still a graph claim.
- Workshop screens: 2 pass; assemblies: 25 pass; Inventory: 16 pass; placement context: 16 pass with native engine (an earlier no-engine run skipped six and was rerun).
- Source-registration guard: 286/286; `git diff --check` passes.

Still required: explicit personal study receipts, durably ordered tool evidence, a technique earned by use, the connected work-surface/process goals, broader AI actions and Market guidance. The reference character still stops at Camp; live provider play is unverified without a configured key. Rover routing/delivery across seeds remains a separate defect. No existing user server was restarted and no deployment was performed.
