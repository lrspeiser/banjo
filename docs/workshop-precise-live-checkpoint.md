# Precise rigid Workshop to live-world checkpoint

## Implemented boundary

Precise rigid prototypes can now be installed in the actual native live room,
not only the isolated Workshop bench. This is an **authoring sandbox** lane:
no inventory or fabrication energy is charged, and no strength certification is
implied. Each homogeneous face-connected box compound remains one Jolt body with
its exact dimensions, density-derived mass, centre of mass and full inertia.
It has zero lattice cells. Existing grid-based bodies remain grid-based.

The native and Python scene interfaces independently bound the new representation:
32 precise bodies / 256 collision boxes per room, 1–64 boxes per body, dimensions
1–6000 mm, COM-relative offsets within 6 m, initial positions within 190 m,
initial linear/angular speeds within 20 SI units, normalized orientation and
supported homogeneous glass/oak/iron/concrete material. Unknown fields, overlapping
boxes, separated parts, invalid numerical values and ambiguous geometry are refused.
The initial boxes are axis aligned in the body's own COM frame; the body itself
can rotate during native motion. These are shape/model limits, not a fracture law.

**The current mixed scene admits only anchored lattice scenery.** Dynamic
lattice/precise contact coupling would need to include the precise body's reactions
in the deformation/failure solve. It is not implemented and is refused, not silently
turned into nonbreaking lattice motion. Terrain, water, thermal declarations,
joints, machines, blades, tool points, bag storage and inventory-funded fabrication
are also outside this lane. Unsupported native mutation calls are rejected before
mutation. General MCP chat re-authoring of a precise room is blocked because its
legacy exporter cannot preserve this new representation; Workshop installation,
picking, carrying and native motion remain available. Beam/sheet/cable models and
localized fracture remain separate unfinished work.

## Actual end-to-end path

`precise_rigid_bodies` is a separate scene channel; it is never reconstructed from
cubic material cells. `PreciseRigidScene` is a registered, compiled native parser.
`LiveWorld` adds exact compounds to the same Jolt world as the anchored scenery.
The live protocol sends the native compound boxes, and the world renderer draws
one instanced, individually scaled box per collision part about the native COM.
A missing exact shape is an error, not permission to draw a filled bounding box.
The 5 mm tabletop and the opening between the legs are actual contact geometry.

Workshop retains its two-phase placement: explicit authoring consent, current
world preview, then commit. Rigid placement uses continuous X/Z coordinates and
a declared 2 mm initial floor clearance; it does not snap to the room grid. A
conservative AABB check may refuse some placements that could fit through holes.
An isolated staging process verifies exact geometry, native mass, initial pose and
preservation of existing world state before the persistent room save and process
swap. A failure keeps the original world and inventory unchanged. Preview tokens
bind world state, scene declaration and inventory; retry receipts persist across
restart. The comparison grid is not a rigid body's source of mass or collision.

Native snapshots retain the representation, canonical source definition, native
mass, identity, pose, velocity, spin, sleep and hand state. Adding another prototype
carries previous precise objects without resetting them. Source mismatch, malformed
state, removed precise geometry or unsupported mechanisms fail closed, rather than
falling back to a fresh world with lost objects. Jolt contact warm-start caches are
not persisted; exact state comparison does not claim bit-identical subsequent
contact impulses. Picking/carrying uses the existing externally driven hand model,
not a new energy-conserving manipulation law.

## Verification and numerical scope

`tests/precise_rigid_live_tests.py` covers source admission and the actual native
subprocess: three-material exact mass/shape installation, independent initial
mechanical-energy mass/inertia oracle, thin-top ray picking, clear leg space, a
small body landing on the tabletop, actual falling motion, moving/held-object
carry, full restart, persistent idempotent receipts, stale previews, collisions,
disk-failure rollback, old-binary refusal, malformed snapshot refusal and native
parser rejection independently of the Python validator. Native requirements do
not silently skip in CTest; the new suite is registered with the real engine path.

The live energy oracle is **initial-state only**: gravity potential plus independent
translational and rotational kinetic energy. It verifies the solver's effective
mass/inertia to 5e-6 relative tolerance, allowing Jolt float32 mass/inertia. It is
not a collision conservation proof. Drop and contact tests use dt = 1/240 s and
one second duration; no internal stiffness, yielding or fracture result is claimed.
The measured 20 mm iron cube rests at 0.77 m over the table's 0.76 m top (within
1 mm contact tolerance). The ray check uses a 10 micrometre top-height tolerance.

Measured live drop of the same table with 0.202 m initial floor clearance
(0.2 m lift plus the declared 2 mm placement clearance), dt=1/240 s, 240 steps:

| Material | Source mass (kg) | Native mass (kg) | COM vertical change (m) |
| --- | ---: | ---: | ---: |
| Glass | 12.198750 | 12.19874937 | -0.20200143 |
| Oak | 3.415650 | 3.41564983 | -0.20200203 |
| Iron | 38.401665 | 38.40166542 | -0.20200168 |

These are motion/contact checks under the declared no-internal-failure model,
not evidence that glass, wood and iron have identical strength.

The browser suite adds a real Workshop → preview → commit → live world → page
reload journey. It inspects the actual instanced mesh's five shapes and 5 mm top,
zero cell representation, unsnapped 3.123 m X position, native pick result and
persisted identity. It also keeps all earlier inspection and simulation journeys.
Runner outcomes and exact revision belong in the final verification record; a
successful compile alone is not a browser pass or whole-repository qualification.

## Reproduce

```sh
cmake -S . -B build/check -G Ninja -DCMAKE_BUILD_TYPE=Release -DBANJO_BUILD_LAB=OFF
cmake --build build/check --target banjo_live_world_run banjo_platform_cli --parallel 2
ctest --test-dir build/check -R banjo_precise_rigid_live_tests --output-on-failure
python scripts/check-source-registration.py
```

In Workshop choose Precise rigid under Mechanical representation. Open a fresh,
paused yard, acknowledge authoring creation, preview and install. Return to the
world to pick up or move the exact object. Its details explicitly say it has no
internal failure or thermal model. Use a separate lattice room for those mechanics.
