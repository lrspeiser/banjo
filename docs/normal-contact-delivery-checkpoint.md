# Normal contact experiment and interrupted native delivery

October 8, 2026. The native normal patch experiment is withdrawn. The CPU analytical primitive is compiled and retained for future solver work. Interrupted native delivery now preserves the last delivered scene and an exact failure record. No physics speed improvement is admitted at this checkpoint.

## Why the glass drop appears slow

The current glass reference requires 41,823 accepted native substeps for two physical seconds. The measured native stage fixture spends about 73% of its 38.238 wall seconds inside Jolt update; see [the stage measurements](native-stage-performance-checkpoint.md). This is calculation latency. Rendering a smooth frame does not advance physical time.

[`VoxelImpactWorld.cpp`](../src/platform/VoxelImpactWorld.cpp) halves the whole interval when the ball's lowest conservative bound is below 0.65 m and the largest cell surface-speed bound times the interval exceeds 5% of sheet thickness. The speed bound includes rotation. A 4 mm sheet therefore sets a 0.2 mm motion bound for the entire scene. Reducing this global work requires a qualified local contact and elastic solve with accounted transfers; simply increasing the timestep does not establish accuracy.

## Withdrawn normal patch experiment

The attempted native option jointly solved up to four frozen unilateral normal rows, followed by the existing sliding/twisting block. This still separated normal, friction and elastic constraints. Analytical tests and controlled native oracles passed, but complete material experiments did not establish a useful improvement.

Matched experiment: 0.4 m square sheet, 4 mm thick, 8 by 8 sheet cells, 32 cm support gap; 1 kg iron ball from 0.1 m; centered interfaces, 96 velocity iterations, nominal 1/960 s host step; observe 0.3 physical seconds. Density and stiffness remain catalog-derived: glass 2500 kg/m³ and 70 GPa, oak 700 kg/m³ and 12 GPa, iron 7870 kg/m³ and 211 GPa. Oak remains an elastic comparison without grain or plasticity. These measurements are experimental numerical responses, not calibrated material behavior.

| Sheet | Patch / existing wall s | Patch / existing substeps | Patch / existing unclosed energy J | Patch / existing linear residual norm N s | Patch / existing angular residual norm N m s |
|---|---:|---:|---:|---:|---:|
| Glass | 14.39 / 12.62 | 4498 / 4778 | -0.521850 / -0.578754 | 4.51e-5 / 8.60e-5 | 1.06e-6 / 8.33e-7 |
| Oak | 13.13 / 12.03 | 4054 / 4063 | -0.218634 / -0.207509 | 5.07e-5 / 5.38e-5 | 1.89e-6 / 1.11e-6 |
| Iron | 18.08 / 12.69 | 4383 / 4636 | -0.863955 / -0.874052 | 3.47e-5 / 3.75e-5 | 7.71e-6 / 9.77e-6 |

Dynamic mass is retained at 2.600 / 1.448 / 6.0368 kg respectively. Glass has one sheet component in the patch trial versus two in the existing solve; neither outcome is accepted as a calibrated fracture prediction. The ice trial exceeded its private harness's 60 s request bound, with the last delivered state at 0.166667 physical seconds and 1994 substeps. The 10 m glass patch trial also exceeded that bound near first impact. The reason for those unanswered requests remains unresolved; a delivery deadline is not an energy gate or proof of a particular native failure.

An early prototype changed the unchanged reference trajectory at 1.433333 s. Isolating its dispatch restored exact four-material reference parity, but did not resolve the performance failures. The entire native option, overlay and website selector were withdrawn. Failed source and results remain in ignored local `build/voxel-normal-prototype-source/` and `build/voxel-normal-separated-low-comparison*.json`; they are not an admitted alternative physics mode.

## Retained analytical CPU reference

[`ContactNormalBlock`](../src/physics/ContactNormalBlock.hpp) minimizes ½ λᵀKλ + qᵀλ subject to λ ≥ 0 for at most four rows, with K in 1/kg, q in m/s and λ in N s. It enumerates bounded principal faces, uses a pseudoinverse for rank-deficient patches and refuses unqualified inputs/solutions. No diagonal stiffness is added. Roundoff bounds scale with double precision and input magnitude; no native physical tolerance is changed.

The registered target exercises 480 known KKT, kinetic-work and reversed-order cases at ranks 1, 3 and 4, plus singular, separating, small-dimension, indefinite and unbounded controls. This is material-neutral analytical validation. **The primitive is not called by the current native contact solver.** It does not qualify the withdrawn integration or solve full-world conservation.

## Interrupted response behavior

The existing 25 s response deadline remains. [`voxel-lab.py`](../scripts/voxel-lab.py) now stops only the session's owned native process and retains the exact last delivered state. It persists completed unpublished replay commands before a separate unanswered-request record, including reason, elapsed wall time, last delivered physical time and `candidate_available: false`. No pose is inferred from missing output. Late output cannot replace the retained scene.

The session remains inspectable through Before, Live, frames and record download. Further dynamics controls are disabled until Reset; Reset starts a new native process. Process stop and invalid delivery receive the same inspection boundary. Wall time controls transport termination only; it never selects forces, material laws or native acceptance.

Transport regression uses real native scenes and deliberately withholds output with a short private test deadline. Manual, streaming and EOF cases retain exact poses, archive the unfinished request once, exclude it from accepted replay steps and leave a second world usable. Four-material 96-tick scheduling parity and delayed Pause tests remain. Ordinary browser Step → interruption → Before → Live retains 16 accepted substeps at 0.017 s and the explicit failure; Reset restores usable controls. This injected delivery test is not a physics experiment.

## Verification and next work

Windows x64, MSVC Release, precise CPU floating point, SDK 10.0.26100. Source parent: `3e98346ddc10291a131c09ff4bfbe4393608c872`. Separate CMake tree `build/voxel-contact-audit`, output `build/voxel-delivery-reference/Release`. Eleven scoped CTests pass in 16.17 s. Source registration: 338/338, no exclusions. Changed targets compile; this is scoped verification, not the full repository suite, physical-phone acceptance or cross-GPU determinism.

Rebuilt native SHA-256: `d0cf707f69ebef5e64077acc10eec4c6764c65f193217a3c4dd272bd3af6e68a`. Native material/solver source remains the prior `bbb00f2ccada0179dd48d53eef9115089f6dcd9f` physics. Four complete default two-second glass/oak/iron/ice comparisons preserve every physical/work field at each 16-tick output against the published unloading binary; only wall profiling is excluded. Glass costs 37.17 versus 36.42 s; ice 41.34 versus 41.13 s. No speed gain is claimed. Local CTest evidence is in `build/voxel-contact-audit/Testing/Temporary/LastTest.log`; browser recovery capture is `build/voxel-delivery-fault-retained.png`.

```text
cmake -S . -B build/voxel-contact-audit -DCMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE=C:/Users/henry/Documents/ChatGPT/Banjo/build/voxel-delivery-reference/Release
cmake --build build/voxel-contact-audit --config Release --target banjo_voxel_world_run banjo_contact_normal_block_tests --parallel 4
ctest --test-dir build/voxel-contact-audit -C Release --output-on-failure -R "banjo_(contact_normal_block|contact_friction_block|connector_plasticity|voxel_face_spring|state_recorder|rigid_step_work|reversible_trial|rolling_resistance|voxel_gateway|voxel_pipeline|voxel_playback)_tests"
python scripts/check-source-registration.py
node --check client/voxel-lab/world.js
python tests/voxel_execution_test.py build/voxel-delivery-reference/Release/banjo_voxel_world_run.exe build/voxel-unload/Release/banjo_voxel_world_run.exe --strict-inline-baseline
```

The owner has expanded the active objective to near realtime material interactions with Minecraft-like 3D demonstrations, including fracture, dents, bounce, heat, burning and power. Accuracy and bounded active calculation remain prerequisites. The next speed experiment must measure the bodies/contacts driving global refinement and couple local normal, friction and elastic work; a normal patch alone is insufficient. Adaptive spatial cells, permanent deformation qualification and authoring remain required. Thermal, chemical and power models must each be implemented and verified before their demonstrations claim those behaviors.

GPU acceleration is optional in the proposed architecture. Keep the CPU reference and benchmark complete scenes, transfer costs and accuracy before requiring accelerated execution. [Jolt's architecture](https://jrouwe.github.io/JoltPhysics/) describes CPU job/island work; [NVIDIA's performance guide](https://nvidia-omniverse.github.io/PhysX/ovphysx/latest/guides/performance.html) also notes that small scenes may favor CPU and larger batches may favor GPU. These references guide architecture, not a Banjo speed guarantee. A future GPU server could serve phone/browser clients without requiring a dedicated client GPU; this is planned, not implemented.
