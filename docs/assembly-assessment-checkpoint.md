# Read-only assembly assessment API

Local source `daecb00584e64528fb0da5239a2215a504424c5a`, September 5, 2026; not pushed or merged. Full goal remains active.

The public creator command `assess_assembly` accepts a strict version-1 two-box declaration and returns compiled body/joint quantities, material requirements and explicit capability limits. It does not create objects, simulate the assembly, spend/reserve inventory or advance time. Inventory readiness and capability readiness are separate: `materials_sufficient` may become true while `creation_supported` remains false. The creator inspection response advertises this operation.

## Contract

Command fields are exactly `type` and `assembly`. Assembly fields are `schema_version`, `parts` and `joint`. Exactly two parts are required, with distinct IDs, material ID, dimensions_m, center_m and orientation_wxyz. Tested material IDs are glass, oak and iron. Density/mass/inertia overrides are rejected. Dimensions must be 0.001–1 m and center coordinates within +/-10 m. Box-face compilation applies its stricter quaternion/geometry validation.

Joint fields are id, part_a, part_b, face_a, face_b, cells_per_axis, law and contact_owner. Part references must name the two distinct declared bodies. Faces use normal_axis, positive, u_offset_m, v_offset_m, width_m and height_m; the compiler validates rectangles on opposing faces. Grid limit is 16 cells per axis/256 sites; positive rest gap must be at most 0.1 m. The only accepted contact policy is `cohesive_patch_only`, an isolated-reference declaration, not a claim that live Jolt contact routing has been implemented.

Law fields are model (`central-cohesive-v1`), stiffness_pa_per_m, strength_pa, fracture_energy_j_m2, compression_stiffness_pa_per_m and provenance. The caller supplies explicit coefficients; material names do not choose failure outcomes. Constitutive validation applies, with assessment caps 1e22 Pa/m stiffness, 1e12 Pa strength and 1e12 J/m2 Gc. Provenance is required text, not independently verified calibration. Documents retain the existing 1 MiB/24-level limits, duplicate-key rejection, exact-field checking and bounded command batch behavior.

Response includes the unchanged declaration, compiled part masses/principal inertias, joint area/gap/site count and complete tensile-separation work. Material requirements aggregate both bodies by material and distinguish required, held, uncollected collectible, missing-from-inventory and missing-after-collection mass. Selected-object recovery is not offered by this contract. Joining energy/process/tool costs remain unsupported; fracture work is explicitly not fabrication cost. Materials are checked against the workshop inventory, not the starter game's separate saved inventory.

## Verification

Tests assess two cubes for glass/oak/iron before and after collecting each material. Required mass is density*(0.02³+0.03³), interface area 0.00012 m2. Full serialized state is identical across each assessment. Invalid contact policy, duplicate part reference, density override and out-of-face rectangle reject through the public command with no state change. Sufficient inventory still returns creation_supported=false.

A 21-command CLI run contains six assessments plus collection and inspection. Every command succeeds; before/after inspection responses are identical around each assessment. Before collecting, each material is insufficient; afterward it is sufficient. Live assembly creation remains unsupported in every report. Exported commands and JSON responses make the contract directly reproducible with `banjo_creator_cli --commands COMMANDS.json`.

Full Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass in 17.60 seconds. Environment remains CMake 4.1.2/Core Ultra 9 285K. The owned starter was intentionally stopped for relinking and restarted. No new native UI or real LLM assembly round trip is claimed. This API adds inspection and requirements, not assembly creation, persistence, a new physics test fixture or production collision ownership.

Next: expose a bounded isolated assembly test using these same declarations, then integrate authoritative contact routing and durable creation/resource transactions. Starter LLM/UI support, mixed-material interface calibration, shear/friction, spatial convergence, physical joining/cutting and remaining goal gates stay open. All 40 scorecard rows are retained.
