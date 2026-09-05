# Assembly requirements from first-person inventory

Local source `b02bab931052deb0bea007722aa6ac92cfac9cd6`, September 5, 2026; not pushed or merged. Full project goal remains active.

CreatorWorld::assessAssemblyWithStockJson shares the existing assembly compiler and requirement calculation with a bounded host-provided stock view. The workshop wrapper supplies its existing lots. The new StarterWorld::assessAssemblyJson supplies actual first-person inventory and loose uncollected object mass, derived from geometry and catalog density. It does not construct a temporary workshop with fictitious ten-kilogram piles and does not introduce a second inventory authority.

Stock entries must have known material IDs, no duplicates, and finite nonnegative held/collectible masses at most 1e12 kg each; entries are bounded by catalog size. Missing materials imply zero supply. This host C++ interface is read-only evidence input, not a network command accepting client inventory claims or permission to create matter.

The starter excludes attached branches, collected objects and equipped tools from collectible supply. Loose objects can still require approaching, waiting for motion to settle and spending stamina before pickup. The report explicitly states those conditions. Current player level/stamina are included, but assembly level requirement and stamina cost remain null and creation_supported remains false. Missing implementation is not represented as a free action or an arbitrary unlock.

## Comparative evidence

Each case uses the same two-box assembly geometry: 0.02 m and 0.03 m cubes with the existing illustrative joint, with the material changed consistently. No new material calibration is claimed.

| Material | Required kg | Loose clearing supply kg | First pickup transferred kg |
|---|---|---|---|
| Glass | 0.0875 | 7.68 | 1.28 |
| Oak | 0.0245 | 5.376 | 0.896 |
| Iron | 0.27545 | 24.17664 | 4.02944 |

All start with zero held material. The loose-mass oracle uses six declared pickup volumes; the attached oak branch is excluded. Actual pickup makes each assembly material-sufficient and reduces loose supply by exactly the held increase, without making creation supported. Assessment itself preserves complete serialized state, including XP, stamina, resources and time. Save/reload returns identical requirements. Crafting the oak pry tool debits held stock but does not add the equipped tool to collectible mass. Mixed-material assemblies retain separate bills and cannot substitute held stock of another substance. Duplicate/negative stock rejects; an empty supplied stock view does not invent collectible material.

Full Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass in 17.75 seconds. Existing CreatorWorld tests verify the workshop assessment contract remains intact. Focused starter tests passed as well; the final suite additionally includes the independent six-pickup and mixed-material checks. Environment remains Windows 11/Core Ultra 9 285K/RTX 5090/CMake 4.1.2/Jolt 5.6/raylib 6. The owned starter and workshop were intentionally stopped for relinking and both restarted successfully. No UI controls changed or new native gameplay verification is claimed.

Next: persist an assembly declaration with the starter save and expose its requirements/test/review at the first-person crafting table using this adapter. The workshop's LLM adapter currently takes CreatorWorld; first-person review must use the starter assessment rather than recreating workshop stock. Live assembly construction, authoritative contact ownership, physical joining/cutting, material/energy transactions and all remaining gates stay open. All 40 scorecard rows are retained.
