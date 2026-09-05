# LLM review of verified assembly evidence

Local source `b08d0d7fa5773edbfd20a91f314dbbca9ef74e3e`, September 5, 2026; not pushed or merged. Full goal active.

`CodexAssistant::assemblyReviewDocument` independently computes the current assembly assessment and isolated test, then packages both with the user's review request. It does not accept an arbitrary claimed pass/fail result as evidence. Context remains bounded to 256 KiB and prompt text to 500 bytes. Test/geometry/resource limits are inherited from the existing assembly APIs; preparing the document performs the bounded test synchronously.

The provider receives an explicit assembly-review override: explain the supplied result, separate inventory sufficiency from unsupported live creation, preserve materials/geometry/law/test criteria, and return clarification with recipe null. A passed separation test must not be described as proof of a useful or realistic joint. Embedded identifiers/provenance are data, not instructions. The existing local Codex provider keeps its no-tool, read-only, bounded-output process setup and five-minute timeout. The adapter additionally rejects any recipe returned in review mode, independent of prompt compliance.

The new `banjo_assembly_review_probe COMMANDS.json NEW_WORKSPACE` exercises this path against real provider calls. It uses the prior six declared low/high test cases across glass, oak and iron, regenerates assessment/test evidence, verifies unchanged serialized world state and requires null recipes. It is an evidence runner, not a new starter UI or public asynchronous review job.

## Real model evidence

All six real calls completed. The three low-input cases were correctly described as failed with 0% separation versus 100% required; the three high-input cases as passed with 100% separation. Every reply explicitly stated that live assembly creation remains unsupported and distinguished collected shortages from available uncollected stock. High-case replies also stated that test success does not prove usefulness or realism. Glass shortage was reported as 0.0875 kg and iron as 0.27545 kg when quantities were included, matching the two-box material bill. No call returned a recipe or changed world state.

The requests and structured responses are exported as an evidence archive without provider event/stderr logs. The text log contains the six explanations. These outputs were inspected for agreement with the supplied evidence; natural-language accuracy is observed for these cases, not guaranteed for arbitrary prompts. No assembly proposal generation, revision, actual build or fabrication is claimed.

A deterministic provider fixture also attempts to return a normal object recipe in review mode. The adapter rejects it, clears process ownership and preserves the world. This fixture verifies the boundary and is separate from the six real LLM calls. Full Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass. Environment remains CMake 4.1.2/Core Ultra 9 285K. The owned starter was intentionally stopped for relinking and restarted; no new native UI verification is claimed.

Next: expose saved assembly declarations/review evidence in the creator UI and support intentional revisions, then authoritative contact routing and durable material/energy-aware creation. This review-only adapter cannot build assemblies. Spatial convergence, physical joining/cutting, calibrated grain/plasticity and all remaining gates stay open. All 40 scorecard rows are retained.
