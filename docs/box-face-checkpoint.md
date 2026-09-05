# Material-backed box-face attachments

Local source `a81532149ac46c108332916d235c48285a1ee26d`, September 5, 2026; not pushed or merged. Full goal remains active.

`makeBoxFaceCohesivePatch` constructs at-rest rigid bodies from box dimensions, density, world centers and orientations, then compiles corresponding rectangles on two actual box faces. Mass is density*volume and principal inertia follows the solid-box formula. The face normal axis/sign, in-face offsets and width/height locate each rectangle. Its corners must lie within the box face; its width/height determine physical interface area. The transformed face positions determine the initial gap. No caller-supplied mass or inertia can override these derived values.

Face tangent axes follow cyclic coordinate axes. Faces must oppose across a positive normal gap and have corresponding widths/heights and world tangent bases. Body dimensions/density and rectangle sizes must be finite positive, offsets finite, face axis 0..2, and quaternions valid. In-face containment tolerance is 1e-12 times the relevant box dimension; corresponding sizes use 1e-12 relative tolerance. Existing rectangular-constructor basis/alignment checks and 256-site limit remain. Unsupported orientation mappings or zero-gap interfaces reject; no automatic face projection, snapping or patch clipping occurs.

The gap has no assigned matter or mass. This remains a declared compliant interface across a positive separation, not a solid adhesive-layer model or automatic contact detector. Box declarations are C++ data, not yet creator JSON/API recipes. Existing raw patch APIs remain available for isolated experiments. This constructor does not register collision ownership or prevent a caller from adding another contact response; that integration requirement remains open.

## Verification

Glass, oak and iron each exercise x, y and z faces with both boxes rotated 0.4 rad around z. Body A is a 0.02 m cube, B a 0.03 m cube; density comes from each catalog material. Their centers are separated by a rotated 0.026 m axis vector, yielding a 0.001 m gap. Patch width/height are 0.01/0.012 m with offsets (0.002,-0.001) m and 16 sites. The total area must equal 0.00012 m2 within 1e-16 m2, each gap 0.001 m within 1e-14 m, masses density times their respective volumes within 1e-12 kg, and A's inertia within 1e-14 kg m2. Oversized rectangles and nonopposing faces reject for every material and axis.

These nine geometric cases pass, alongside all existing dynamics tests. They verify compilation, not a new loading trajectory of the compiled pair. Full Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass. Environment remains CMake 4.1.2/Core Ultra 9 285K. Reproduce with `banjo_cohesive_rigid_tests`; logs are exported. The owned starter was intentionally stopped for relinking and restarted. No new native gameplay verification is claimed.

Next: run compiled pairs through declared load cases, bind interface/contact ownership and expose an inspectable bounded assembly contract to the creator. Spatial convergence, finite surface contact, grain/plasticity, realistic cutting and all other goal gates remain open. All 40 scorecard rows are retained.
