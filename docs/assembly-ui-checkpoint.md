# Assembly designs in the workshop

Local source `acf41d13ca256d602b38fb6ca2532534e06d13bf`, September 5, 2026. Not pushed or merged; full goal remains active.

The Material Workshop now has an Assembly designs screen. It displays the saved declaration's two parts, dimensions, density-derived masses, joint area/gap, complete separation work and exact inventory requirements. Held, collectible and missing-after-collection quantities remain distinct. Even when materials are ready, the screen explicitly says live assembly construction is unsupported. Separation work is not presented as fabrication cost.

Choose Assembly designs from the workshop header, or launch with `--view assembly`. Import design reads `assembly.json` from that workshop's workspace; dropping one design file is also implemented. The declaration must pass the shared bounded assembly compiler. A valid replacement uses the saved draft revision. Clear saved design preserves inventory. Collect buttons use the same world lots as the ordinary workshop. Simulation is paused while reviewing; Back to workshop and Escape return to object authoring. F12 writes an assembly image in the workspace.

Imports, clears and collection operate on a private deserialized candidate, save it, then publish it to the in-memory world. A validation/save exception leaves the current candidate unpublished. This is local single-writer UI handling using the existing world save, not a new shared durability protocol. Other workshop actions retain their existing semantics. No assembly physics law, test specification or provider prompt changed.

## Verification

A fresh native Windows workshop was opened on a test workspace. Importing oak created revision 1 and displayed 0.024500 kg required/missing. Clicking Collect Oak displayed 10 kg held, zero shortage and Materials ready. An oversized joint-face import was rejected; the complete saved world was checked unchanged. A valid joint-ID revision produced revision 2. Back to workshop and the header's Assembly designs navigation worked. After normal close and a fresh process launch, revision 2 and the collected inventory were observed in the native screen. F12 successfully exported evidence.

Glass and iron assembly capture layouts were separately generated and visually inspected: required masses 0.087500 and 0.275450 kg, respectively; zero held and 10 kg collectible. Their world files remained unchanged. All three screens retain unsupported construction and fabrication messaging. These are UI/material-bill checks, not new constitutive validation. Native dropping and clearing, injected save failure, mixed-material layout and complete first-person gameplay were not exercised this turn.

The workshop target builds with Windows MSVC 19.44 x64 Release. All 21 CTest suites pass in 18.08 seconds. Environment remains Windows 11/Core Ultra 9 285K/RTX 5090, CMake 4.1.2, Jolt 5.6, raylib 6. One initial restarted-window capture showed the underlying starter; reselecting and foregrounding the verified workshop window recovered a correct observation. No input was sent to that unrelated image. The starter and original laboratory remain running; the reviewed workshop is also open.

Next: connect selected-revision assembly tests and real LLM evidence review to this interface, then carry the same declaration contract into the first-person crafting table. Live construction still requires contact ownership and accounted material/energy transactions. Realistic branch cutting, physical joining, material calibration, spatial convergence and all remaining platform gates stay open. All 40 mechanics/platform rows remain in the scorecard.
