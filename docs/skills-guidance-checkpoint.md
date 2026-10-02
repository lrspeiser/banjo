# Skills guidance checkpoint — October 1, 2026

## Player-facing correction

Gathering by hand is earned through **one** accepted tool-use route. A successful Field pick dig does not also require the One-piece wooden pick. Previously the page printed every alternative under "How it was earned" and placed an unrelated global manufacturing blocker immediately below it.

Direct Skills entry loads the saved native World before resolving tools and equipment; an unopened session no longer looks like missing equipment.

Skills now shows **Learned ✓ · No further action needed**, with only completed routes in the history. An unlearned skill with an available route shows that route's actual instructions and World/Inventory destination. Ground-tool instructions use the shared primary control label. Tree cards distinguish learned, ready, earlier-skill prerequisites and unavailable-here states. Raw evidence counts and global design/manufacturing reasons remain in a closed **Design diagnostics** section.

The world resolver no longer treats a missing alternative as a whole-skill blocker when another route is available or the skill is already known. If a required example is absent and its declared manufacturing processes are unsupported, guidance explicitly says making that example is not available yet and collecting supplies will not unlock it. This does not enable the shaping process or award knowledge. Learned machine skills retain navigation to actual equipment.

## Verification

[Recorded evidence](evidence/skills-guidance-checkpoint.json): 63 affected knowledge, Skills/Market API, Workshop and actual Chrome tests pass in 29.723 s on Windows/Python 3.13.5. The browser journeys perform real native Field pick pickup/use, earned progress, achievement fade, repeated use and reload; personal evidence and peer isolation remain unchanged. They also retain an actual native copper batch and machine navigation. No browser exceptions. The source-registration guard passes 287/287.

Screenshots are ignored local artifacts: `build/player-learning/live-skills-complete.png`, `build/player-learning/tool-skills.png`, `build/workshop-navigation/world-aware-skills.png` and the two refreshed 8770 preview pictures listed in the evidence. The earlier navigation test now opens the current Menu's World diagnostics instead of removed Room/Notes tabs.

Verification base: `7f7492249c6fed532b00e24fe472bcf0a844bf5a`, with the scoped host/presentation changes above. Existing MSVC Release CPU runner/library are unchanged and their hashes are recorded. Native dt=1/240 s and generated 50 mm scenes are retained. This checkpoint changes no native physics, material law, tolerance, learning award, manufacturing admission or conservation claim. Retain prior glass/oak/iron evidence and limitations. R1–R6, especially broader supported progression under R6, remain open.
