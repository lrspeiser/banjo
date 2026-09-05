# Saved assembly drafts

Local source `931be9f79b316320865483d43d5e1d29b1586387`, September 5, 2026; not pushed or merged. Full project goal remains active.

CreatorWorld save format 4 retains one validated two-box assembly declaration and its revision. Versions 1–3 migrate with no draft. Loading recompiles the declaration through the same bounded geometry/material/interface validator used by assessment and testing. Stored assessments, test results and LLM reviews are not persisted as current evidence.

The public commands are `remember_assembly` (assembly and expected_revision), `clear_assembly` (expected_revision), and `assess_saved_assembly`. Remembering an identical declaration is an idempotent no-op, including a retry carrying an older revision. A different declaration requires the current revision; clearing also requires the current revision. Revisions increase on actual changes and are bounded at one billion. Assessment reports draft_revision and recomputes current material shortages. These operations change in-memory state; callers must use the existing world save operation or CLI --save for persistence. This is not a new crash-durable or multiwriter transaction API.

Glass, oak and iron regression cases verify exact save/reload, unchanged lots/objects/time when remembering, identical retries, stale revision rejection, current readiness after collection, survival through ordinary object creation, v3 migration, invalid saved geometry rejection, and revisioned clear. Existing v1/v2 migration tests also pass. An initial test fixture used a sphere radius below the compiler minimum; correcting it to 0.03 m made the intended unrelated-object preservation check valid. No production bound or test tolerance was relaxed.

Separate CLI processes saved and reloaded each material's declaration, then collected the matching resource and reassessed. All three changed from insufficient to sufficient inventory while preserving declaration, revision, objects and elapsed simulation ticks. Creation remains explicitly unsupported in every assembly assessment.

Full Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass, 17.48 seconds. Environment: Windows 11, Core Ultra 9 285K, CMake 4.1.2, Jolt 5.6 and raylib 6. The owned starter was intentionally stopped for relinking and restarted successfully. No new native gameplay/UI verification or physics-law validation is claimed.

Next application work: expose this saved assembly in the crafting interface, allow deliberate revisions and regenerate test/review evidence for the selected revision. Live assembly creation still needs authoritative contact ownership and material/energy-aware transactions. Physical joining, realistic branch cutting, calibrated wood/iron response, spatial convergence and all other open gates remain unfinished. All 40 scorecard rows are retained.
