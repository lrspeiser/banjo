# Starter saved-action checkpoint

Source `659cc54f25b98f6acb909e18c6887fd84f2bc015`, local `codex/physics-foundation`, September 5, 2026. Not pushed or merged. Full platform goal remains active.

Previously the starter UI changed resources, XP, tools or branch state before attempting to save. A save error therefore looked like a failed action while leaving its costs and effects live. Gathering/cutting, preset crafting and custom crafting now execute on a candidate world, save that candidate and its receipt, then publish the live world and success message. Failed writes or publication preserve the previous live state. Windows saves create pending files exclusively, flush file contents with FlushFileBuffers, close and replace the destination with write-through requested. Existing pending evidence is never truncated or automatically promoted.

## Evidence

Windows Release build passes. All 16 suites pass in 11.92 seconds; the final warning-only local-variable rename was rebuilt and the focused starter suite passed again. Comparative glass/oak/iron tests cover blocked pickup, blocked preset/custom crafting, unchanged published save, unchanged live material/stamina/XP/receipts, preserved pending data, successful save/reload/retry, and failure after writing the candidate but before publishing it. Retrying saved requests after reload neither charges resources nor creates objects twice.

A native test used a separate fixture containing four collected oak resources: 3.584 kg oak, 68 stamina, 20 XP. An intentionally blocked save made a wooden-tool craft fail without changing those values or equipping the tool. Removing only that known test obstruction and clicking again produced 3.248 kg oak, 56 stamina, 30 XP, an equipped pry tool and gathering cost 5.6 stamina. The published JSON contains that state and the craft receipt. This verifies the actual UI route, not just the embedded calls. Automated crafting capture also exits successfully; see exported image and logs.

## Contract limits and next steps

This is a single-writer local host boundary, not a distributed transaction protocol or proof against every power-loss/filesystem failure. No power-cut or process-kill matrix was performed. POSIX saves still use the older stream/rename path and were not verified here. Calls to the original in-memory operations remain available to tests/authoring hosts and do not promise persistence. Continuous physics and resting are checkpointed periodically, not durably acknowledged per tick. Saving reconstructs rigid bodies, so contact/sleep caches are not persistent solver state.

After an interrupted save, an existing pending file deliberately blocks subsequent saves until inspected; recovery UI, operation-status discovery, stable world identity, exclusive lifetime writer ownership and common API envelopes are still needed. Do not automatically discard or apply pending data. Unbuilt designs and player pose still need persistence. Full native walking/gathering/cutting/custom-build progression, physical energy accounting and realistic branch cutting remain open. No physics law changed in this checkpoint.

Reproduce with `cmake --build build/win-integration --config Release --parallel 8` and `ctest --test-dir build/win-integration -C Release --output-on-failure`. Environment remains Windows 11 Pro 26200, MSVC 19.44 x64 Release, CMake 4.1.2, Core Ultra 9 285K, RTX 5090/NVIDIA 580.88, OpenGL 3.3, Jolt 5.6 and raylib 6. Required frame-control/busy-wait/static-runtime fixes remain preserved.
