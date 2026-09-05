# Starter crafting designer checkpoint

Source: `29e46a23dddf38d2066cc6a6f43ee17a9fcf5291`, local `codex/physics-foundation`; not pushed or merged. September 5, 2026. Full platform goal remains active.

The first-person crafting table now connects to the existing real Codex designer. Requests contain actual inventory, level, XP, stamina and equipped tool. Supported custom designs are single solid spheres or boxes in glass, oak or iron. A missing level or resource preserves the requested recipe and shows requirements. Only an explicit Build action can debit material and gameplay stamina, award XP and create the rigid object.

The runtime independently validates schema, material, geometry, at-rest table placement, stock, level 2, stamina, capacity, output overlap and object limits. The custom gameplay cost is 10 + 1000 × volume in cubic metres; it is not fabrication work in joules. Custom object names cannot grant tool abilities. Successful retries replay their receipt without creating another object or spending again. Starter save version 2 preserves custom recipes and accepts version-1 progress through explicit migration.

## Verification

- Windows Release build passes. All 16 suites pass in 11.64 seconds. Later changes affect only the native prompt input and starting layout; these were rebuilt and inspected normally.
- Same 8 × 6 × 10 cm custom box test for glass, oak and iron: exact volume-based debit, stamina 10.48, level unlock, blocked-action atomicity, overlap rejection, retry, persisted recipe and bench contact.
- Five real provider trials pass. Glass: required 1.2 kg, held 5.12 kg. Oak: required 0.336 kg, held 3.584 kg. Iron: required 3.7776 kg, held 16.11776 kg. All three build and save. Empty level-1 iron request remains a proposal with 3.7776 kg missing. Functional saw with physical fracture energy returns clarification and creates nothing.
- Native empty-player request for an 8 cm oak sphere returns the correct diameter and approximately 0.188 kg requirement, with missing material/level and disabled Build. This caught and fixed paste handling for key taps released between frames.
- Automated designer capture passes and was visually inspected. An earlier absolute screenshot path failed in raylib despite process exit zero; the successful capture uses a relative path and the actual image was checked.

## Remaining work

Verify the full native walk, gather, level up, craft, cut, recover and custom-build loop, including cancel/retry. Built custom objects persist; unbuilt proposals and camera pose currently last only for the session. Long request/explanation layout, Unicode editing, and shared durable API transactions need further work. Proposal generation never reserves material. Physics continues while the table is open, and acceptance rechecks current placement and stock.

Stamina, XP, preset tool reductions and whole-branch release are game rules. No calibrated cutting, wood grain, bending/fracture progression, processing energy, physical raw-material reference state, functional assemblies or general tools are claimed. Detailed solver energy defects and all outstanding full-platform gates remain open.

## Reproduce

Build with `cmake --build build/win-integration --config Release --parallel 8`; run `ctest --test-dir build/win-integration -C Release --output-on-failure`. Run `build/win-integration/Release/banjo_starter_assistant_probe.exe NEW_DIRECTORY` for the five live trials using existing Codex sign-in. Start `banjo_starter.exe --workspace build/starter-play` for the game; `--layout designer` starts at the table without awarding resources or XP.

Environment: Windows 11 Pro 26200, MSVC 19.44 x64 Release, CMake 4.1.2, Core Ultra 9 285K, RTX 5090/NVIDIA 580.88, OpenGL 3.3, Jolt 5.6, raylib 6. Custom frame control, busy-wait loop and static MSVC runtime remain OFF.
