# Native point surfaces and fixed-tool reaction — October 2, 2026

## Implemented boundary

`JoltWorld::pointShapeContacts` supplies the geometry for the previously
qualified [finite contact/native transfer](held-strike-contact-checkpoint.md).
It queries the actual native shape and current pose using a material point's
spherical contact envelope, returning signed gap, body-to-point normal, both
surface witnesses, native leaf ID/user data and the leaf's compiled material.
It handles sphere, rotated box, cylinder, compound and convex native shapes.
Compound voids remain empty. All reported native leaf contacts are retained;
the complete result refuses if its bounded capacity is exceeded.

The query is read-only and does not take contact ownership, apply an impulse,
alter mass/pose, wake a body or advance time. Tests now feed actual queried
surfaces into the native contact transfer. A separate matched fixed-tool
fixture measures head recoil, later native fixing reaction and handle loading.
No head/handle is merged, released or reset; loads at the handle remain local.

This is still an integration boundary. Its only callers are the native tests.
**The live hand/fracture worker and ordinary object-click tool path remain
unimplemented. R3 stays open**, alongside R1 and R4–R6. No C ABI, LLM tool,
browser flow or running preview binary changes are part of this checkpoint.

## Query contract and accuracy

Radius is 1 micrometre..100 m; search separation is 0..1 m; contact capacity
is 1..256. Nonfinite/invalid inputs, missing bodies or excessive relative range
refuse. Capacity overflow throws before a result is returned; no partial list
is offered as complete geometry. Native geometry itself can be approximate.

Radius is represented in native float precision. Search separation is rounded
outward to float. Both actual values are returned, including for an empty
query. World-position subtraction occurs before the local collision frame is
converted to float; relative distance above `sqrt(float_max)/8` refuses to
avoid overflow in native squared-distance arithmetic. The native body's
actual position is used even on a float-position build; the distant-origin
test below is qualified only on this Windows double-position build.

The unchanged native GJK/EPA collision and penetration tolerances apply.
Normals come from the native penetration axis, including edge/corner normals,
with the source-to-envelope sign. Positive gap is envelope separation;
negative gap is penetration. This query does not move either object to close
a gap or remove overlap. Coordinates and depths must be finite and the
normal resolvable; an unresolved result refuses.

Results are ordered by shape user data, native leaf ID, gap and normal.
Native leaf IDs are transient geometry witnesses, not stable saved design
identity. Compound leaf user data retain the authored part index; cell-shape
user data have their existing native meaning. Mixed compound materials are
resolved from the same compiled per-leaf records used by native contacts.
Missing declared mixed-leaf material refuses instead of substituting a name.
Requery after motion, reshape or rebuild; no outcome/geometry cache is added.

All native leaf witnesses are raw geometry candidates. This does not provide
contact manifold reduction, resolve overlapping internal compound faces or
integrate target spin/finite-cell surface traction. The subsequent response
must still own every relevant source/target contact exactly once. Taking over
a whole proxy pair and supplying one selected leaf would be incomplete.

## Verification environment and geometry

Windows x64 / VS 2022, MSVC 19.44.35228.0 (MSBuild 17.14.51), Release CPU,
`BANJO_BUILD_LAB=OFF`, `build/agent-paid-machine`; baseline `35c3cc7` plus the
implementation revision recorded below. Material catalog seed 17 is retained.

New cases in the registered native contact target verify:

- Glass/oak/iron spheres of radius 80 mm, with a 16 mm envelope and gaps
  -2/0/+3 mm. Signed gap, source/envelope witnesses and material records are
  compared with independent spherical geometry; gap bound 1e-6 m, normal and
  position bounds 2e-6. Queries preserve native motion and contact events.
- A 400×80×60 mm iron box rotated 45 degrees about Y, with envelope 16 mm
  and gaps -4/0/+2 mm. Native face/normal oracles use the same bounds. A point
  inside its enclosing world box but outside its actual thin shape returns no
  contact. Origin shift (1e8,-2e8,3e8) m retains local geometry within those
  bounds on this double-position build.
- Two 40 mm glass/iron compound boxes separated along X, with independently
  computed density-weighted centre and full intrinsic/parallel-axis inertia.
  The centre void returns no contact for a 10 mm envelope / 5 mm search.
  Left/right witnesses retain distinct material and leaf data. A 45 mm envelope
  touches both leaves; budget 2 returns both in repeatable order, budget 1
  refuses the entire query with unchanged source state.
- A native 80 mm diameter / 200 mm long oak cylinder, part turned 90 degrees
  about Z and body 30 degrees about Y. Side/cap gap bound 3e-5 m and normal
  bound 3e-4 reflect native rounded/GJK geometry; no earlier tolerance changed.
  A 100 mm glass tetrahedral convex hull uses independent simplex mass/inertia;
  its diagonal face matches those bounds and empty enclosing-box space stays
  empty. These are geometric qualification, not fracture calibration.
- Actual box surfaces drive the native finite contact response for all retained
  materials under the matched experiment below. Invalid input/budget/range
  and missing-body cases refuse. No new source file is left outside a target.

## Matched actual-surface contact

Each source box is 400×80×60 mm, rotated 30 degrees about Y, initial COM
(1,0.5,-0.5) m, velocity (-1,0.2,0.4) m/s and chosen spin (1,-2,0.3) rad/s.
The oak target point has mass 0.0448 kg from a 40 mm cell. Envelope radius
16 mm; declared gap -1 mm; point sits 10 mm off-centre on the source's +X
face. Its relative velocity is -2 m/s along the queried normal plus 0.5 m/s
along local Y. Contact horizon is `dt=1/240 s`; native gap is
-0.0009999955073 m. Contact coefficients come from the point and queried leaf.

| Source | Native mass kg | Normal impulse N s | Double-law contact loss J | Native numerical energy J | Linear error N s | Angular error kg m²/s |
|---|---:|---:|---:|---:|---:|---:|
| Glass | 4.80000011444 | 0.13319798943 | 0.0718145376706 | 1.93007374e-7 | 1.76542933e-7 | 8.06837677e-8 |
| Oak | 1.34399995898 | 0.126465544427 | 0.0730507284124 | 7.56624947e-8 | 7.47624005e-8 | 6.18595572e-8 |
| Iron | 15.1104008985 | 0.130886591604 | 0.0755039810986 | -6.24747001e-7 | 7.28313005e-7 | 6.47958600e-7 |

The existing explicit native budgets remain 1e-5 J, 1e-5 N s and
1e-5 kg m²/s, without numerical correction. Densities 2500/700/7870 kg/m³
drive source mass and inertia. Catalog moduli 70/12/211 GPa are retained but
no target stiffness/bond response is solved in this contact phase.

## Matched native fixing phase

80 mm cubic glass/oak/iron heads meet the same 240×40×40 mm oak handle at
a native fixing, attachment (-0.04,0,0) m, axis +X. Both start at 2 m/s along
X with explicitly zero spin. The same 40 mm oak point / 16 mm envelope
contacts each head's +X face at 10 mm Y offset and -1 mm gap.

The head receives the queried contact reaction first; the handle is unchanged
by that instantaneous kick. The existing native fixing then transmits reaction
in one `1/240 s` step. Strength fixtures are 5000 N axial/shear, below which
the measured case stays. The fixing owns the joined seam response; both
external target/source pairs are explicitly suppressed in Jolt.

Actual force (25,-7,3) N is applied only to the handle at local grip
(-0.08,0,0) m, with free torque (0,0.2,-0.1) N m. These are below the
existing 800 N / 60 N m hand limits but **not the live feedback controller**.
Gravity and damping are off. Root work uses mean actual grip velocity and
spin across this native step; force impulse/moment use the same world grip.

| Head | Head mass kg | Handle mass kg | Axial force N | Shear N | Root work J | Linear residual N s | Angular residual kg m²/s | Unallocated ΔK − root work J |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Glass | 1.28 | 0.268799991797 | 26.0576534 | 1.70269216 | 0.210940773 | 8.34614543e-8 | 1.29762973e-8 | -0.00553928576 |
| Oak | 0.35839997375 | 0.268799991797 | 26.1514717 | 2.33199683 | 0.211206095 | 1.84852997e-8 | 1.34825457e-8 | -0.0182189672 |
| Iron | 4.02943996741 | 0.268799991797 | 25.3834444 | 0.531761558 | 0.210686050 | 1.81269768e-7 | 6.02532688e-9 | -0.00150220985 |

The new phase momentum bounds are 1e-5 in the stated SI units. The energy
column remains unallocated; it may include native constraint reconciliation,
integration/position correction and work quadrature. It is not measured heat
or a closed whole-pipeline conservation result. This fixture does not advance
the deformable target, fracture the head, qualify strength/fatigue or use a
physical avatar reaction. The live assembly/time bridge remains necessary.

## Checks and next step

```powershell
cmake --build build/agent-paid-machine --config Release --target banjo_native_point_contact_tests banjo_pair_impulse_tests banjo_contact_ownership_tests banjo_ground_work_tests banjo_hand_stroke_tests --parallel 4
ctest --test-dir build/agent-paid-machine -C Release -R '^banjo_(native_point_contact|point_rigid_contact|pair_impulse|contact_ownership|conservative_contact|tetrahedron_contact_impulse|lattice_external_load|fast_lattice|lattice_plasticity|ground_work|hand_stroke)_tests$' --output-on-failure
python scripts/check-source-registration.py
git diff --check
```

All 11 affected CTest targets pass, 12.08 s total on this Windows run. The
expanded native contact target takes 0.04 s; this tiny-suite timing is not a
game-scale performance claim. Registration remains 291/291. One new test initially failed to
compile because one `auto` declaration mixed mechanical totals and pose types;
separate declarations resolve it. No physics tolerance was relaxed.

Next synchronize the CPU target step with actual native tool/hand/fixing
motion. Start with the CPU reference, retain measured contact loss, numerical
error, hand work and joint reactions on one accepted clock, and then integrate
that route into LiveWorld's pending fracture boundary and object-target clicks.
Keep target/striker history, source ownership and grip remapping through failed
saves, detached heads and restart. The full damaged-tool/paid-reuse acceptance
and five remaining player goals are retained.

Sources: [native query/transfer](../src/rigid/JoltWorld.cpp),
[unit-bearing API](../src/rigid/JoltWorld.hpp),
[registered native measurements](../tests/native_point_contact_tests.cpp).

## Publication

Pending final affected checks and ordinary fast-forward publication to main.
