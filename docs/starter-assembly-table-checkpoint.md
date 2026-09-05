# Remembered assemblies at the first-person crafting table

Local source `f2103728655fd49b1597dc412fef719bd25b080e`, September 5, 2026; not pushed or merged. Full goal remains active.

Starter save format 4 retains one canonical assembly declaration with its revision alongside existing player progress and remembered single-object designs. Versions 1–3 migrate with no invented assembly. Loading revalidates assembly geometry/material/law through the shared compiler; unknown or invalid saved data rejects. Revisions are nonnegative integers bounded at one billion; a present declaration requires a positive revision.

rememberAssemblyAndSave and clearAssemblyAndSave use the existing private-candidate save-before-publication path. An identical remembered declaration keeps its revision, including retries carrying an earlier expected revision; a changed declaration requires the current revision. Clearing also requires the current revision and increments only when a declaration existed. Every call still saves its candidate, so a save failure is not acknowledged as successful. This is single-writer local persistence, not shared-world conflict resolution or a general operation receipt protocol.

The crafting table now has Assembly Designs, with Import Design, Clear Design and current held/missing/loose material quantities. Import reads assembly.json in the starter workspace and validates before saving. A saved design remains available as inventory changes. The UI uses the actual starter assessment adapter, explicitly excludes attached branches/equipped tools from loose supply and states assembly construction and its level/stamina costs remain unsupported. Tests and LLM review are still available in the workshop only. The --layout assembly option opens this table view directly; capture mode can read the saved starter assembly without publishing changes.

## Verification

Glass, oak and iron regressions cover file save/reload, unchanged gameplay state when remembering, identical retries, rejected stale edits, valid replacement, invalid saved geometry, stale clear and save-after-clear. An existing pending file forces save failure; the live and prior durable design remain unchanged. Existing migration tests now cover v1, v2 and v3 into v4. Prior pickup/restoration/tool-debit/mixed-material checks continue with remembered assemblies present, verifying normal gameplay preserves the design.

In a fresh native starter, the table imported an oak declaration as revision 1 and displayed 0.0245 kg required/missing, zero held and 5.376 kg loose. The actual saved JSON was checked for format 4 and exact declaration equality. After normal close and a fresh process, the native table restored revision 1 and the same shortages. A capture of the saved table was generated successfully. Native clear, invalid imports, gathering-and-return, mixed-material layout and complete gameplay were not exercised this turn; their respective backend checks must not be mistaken for native verification.

Full Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass in 18.07 seconds. No physics law or tolerance changed. Environment remains Windows 11/Core Ultra 9 285K/RTX 5090/CMake 4.1.2/Jolt 5.6/raylib 6. The test starter remains open at its saved assembly table; the workshop is restored separately.

Next: integrate isolated assembly tests and real LLM review at this table using the starter's inventory context. Then support live construction with authoritative collision ownership, material and energy transactions. Realistic branch cutting, joining processes, calibrated material behavior, spatial convergence and all remaining platform gates stay open. All 40 scorecard rows are retained.
