# Remembered starter designs

Local source `8bde4da` on `codex/physics-foundation`, September 5, 2026. Persistence and native verification foundation: `94ca5abb05658408b7e91fdb8439b7db48825820`. Not pushed or merged; full goal remains active.

The crafting table now retains its most recent completed design or clarification in the same world save as player resources. A player can ask for an object, close the game while short of supplies, gather later and build the exact retained recipe without another model call. Follow-up requests include that recipe and its previous explanation, rather than an unrelated default. The original explanation is labeled as an original note; current material, level, stamina and placement checks determine readiness and are recomputed. Build still revalidates independently and saves before publishing resource changes.

Save version 3 stores bounded request identity, prompt, explanation and optional recipe. Versions 1 and 2 migrate with no invented design. Loading validates supported recipe geometry and at-rest table placement without requiring the current inventory or level to be sufficient. Malformed or unsupported saved declarations fail. Saving a new design uses the existing saved-action boundary and grants no XP, material, stamina, object or tool. A save failure retains the previous saved world and design.

## Evidence

Windows Release build passes. All 16 suites pass in 12.16 seconds at the persistence foundation; the subsequent context-only change was rebuilt and passed the focused starter suite. Glass, oak and iron each cover an exact 8 by 6 by 10 cm box saved while unaffordable, reload, gathering to readiness, preserved recipe and failed replacement-save atomicity. Clarification reload, unexpected fields, unsupported motion, known save migrations and follow-up context are tested.

Native verification made one real request: “Make an oak ball exactly 8 cm in diameter.” The returned 0.04 m radius oak sphere saved with zero resources spent, level 1 and the expected approximately 0.188 kg shortage. The game was closed normally and reopened on the same test workspace. The prompt, recipe, original note, current shortage and disabled Build were restored. Only one assistant request directory exists; reopening did not call the model. Raw request/response and saved-state evidence are exported. No new full native gather-to-custom-build claim is made.

## Limits and next steps

Only the most recent completed design or clarification is retained. Draft typing and running jobs do not survive closing. A failed or canceled new request keeps the earlier persisted design, but restoring that earlier design within the current session still needs a control; restarting restores it. General blueprint libraries, explicit revisions/history, player pose, interrupted-save recovery UI and common world/API identity remain open. Long text and Unicode editing still need improvement. No new fracture, physical manufacturing energy, tool law or publishing capability is claimed. Continue the complete goal and all 40 mechanics/platform rows.

Environment remains Windows 11 Pro 26200, MSVC 19.44 x64 Release, CMake 4.1.2, Core Ultra 9 285K, RTX 5090/NVIDIA 580.88, OpenGL 3.3, Jolt 5.6 and raylib 6. Reproduce with the standard Release build and CTest commands; `banjo_starter.exe --workspace DIRECTORY --layout designer` opens the table on that saved world.
