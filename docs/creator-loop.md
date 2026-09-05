# First creator loop: collected materials to a working object

Current extension: [oriented solid boxes](shape-checkpoint.md) now share the sphere inventory/compiler/LLM path. All three reference substances pass geometry/mass/inertia/dynamics checks; real model calls produce buildable blocks. Capture passes, while normal new-control verification remains pending. Safe revisions/reclaimed material remain next.

Owner direction, September 4, 2026: the application is a virtual world where a user asks an LLM to make something from materials they have collected, and the resulting object works through the system's physics. Keep a rudimentary version of this experience present during foundation work. This is an early product slice, not a claim that general creation or publishing is implemented.

## The first user experience

1. Collect a small quantity of a supported substance into a visible inventory. Start with a simple pickup action in a test world; mining, crafting animations and a full economy are unnecessary for this slice.
2. Ask, for example, “Use some of my wood to make a ball that rolls down this ramp.” The LLM reads available materials and supported capabilities and proposes an inspectable object specification. It can explain an affordable size or a missing capability. It cannot invent material or promise unsupported mechanics.
3. Preview shape, dimensions, material, required quantity and remaining inventory. Geometry and actual matter determine mass and inertia. The application validates units, capability support, resource cost, placement and numerical limits independently of the LLM.
4. Build the object. Commit the inventory debit and the created object together only after validation succeeds. Failed, cancelled or duplicated requests must not consume extra material or create extra objects.
5. Place and test the object in the world. The real simulation determines its motion and interactions. Show a small useful result—whether it rolls, slips, rebounds or fails under a supported law—and let the user ask for a revision.

Begin with a single-material sphere. Then extend the same request/specification path to a box or cylinder, followed by composite objects and assemblies when their physics is supported. The first sphere is a small supported case of a general object contract, not a special command that substitutes a scripted rolling animation.

The first usable execution path may use the existing tested rigid-body components for intact primitives, with that approximation declared and its supported motion rechecked through the creator flow. Do not make every creation wait for the very slow detailed-material reference or for calibrated fracture. Detailed deformation/damage remains an explicit experimental mode until its runtime ownership, work accounting and cost are ready; never switch laws silently to meet a frame budget. Early assembly, cutting and manufacturing can be bounded authoring operations with an inventory ledger, without pretending to simulate an unimplemented manufacturing process.

## Shared system boundaries

- **World inventory:** stable material/lot identity, quantity with units, provenance and the physical state relevant to supported laws. Collected oak remains oak. A material name is neither a capability guarantee nor authority to reinterpret it as brittle glass.
- **LLM adapter:** translates intent into the same bounded, versioned specification and commands available to a human editor. Keep provider/model choice outside the physics layer. Record the accepted specification so a saved creation can be reproduced without asking the LLM again. Fixtures can test this boundary deterministically, but a real LLM round trip is required before claiming the requested natural-language workflow works.
- **Object compiler:** validates supported geometry, spatial material assignments, initial state, interfaces and constraints; derives occupied matter, cost, mass and inertia; reports approximation/capability limits. Material allocation and the simulation's authoritative matter calculation must agree, with sampling approximations stated explicitly.
- **Creation transaction:** reserve/check inventory, validate/compile and place, then publish the object and debit together. Revisions account for the old object and remaining resources. Never silently refill inventory, reset material history or heal damage.
- **Simulation and feedback:** consume the compiled object under a declared solver with one owner per clock/contact. The headless experiment and viewer use the same object declaration. Slow reference work must not freeze user input; expose progress, accepted state and bounded failures.

The LLM chooses supported design inputs and can help interpret measured results. It does not choose collision outcomes, provide per-frame forces, mint resources or bypass physics/capability checks.

## First acceptance checks

- An end-to-end request uses collected inventory, creates one visible physical object, changes inventory by the derived amount, and leaves an inspectable reproducible specification.
- Insufficient material, unavailable geometry/laws, invalid units, failed compilation and cancelled/duplicate creation leave a consistent inventory/world state and give actionable feedback.
- A user can revise a dimension or request a supported alternate substance and see the cost and resulting physical behavior change for those inputs.
- The same creation path produces glass, oak and iron fixtures under declared comparable geometry/conditions. Retain all three as coverage expands. A fixture may provision the required inventory explicitly; production creation cannot fabricate it.
- Rolling is classified from contact-point slip and torque-driven motion. If the selected solver lacks friction/rolling support, the application must say so or limit the first demonstration to a supported behavior. It cannot label sliding or a scripted path as physical rolling.
- Save/reload the accepted specification, inventory transaction and object identity for this small slice. Full persistent damage, assemblies, economy, multiplayer and publishing remain later work.

## Near-term order

Keep the existing creator workshop as the application-facing path for subsequent work. Next finish normal box-control verification and add safe object revisions to the existing automatic assistant and inventory/specification/compiler boundaries. The first intact rigid rolling demonstration already uses Jolt friction/torque and measured slip; work-accounted friction and synchronized activation in the detailed reference remain separate engineering work. Keep the user-visible create/test/revise path in each subsequent material and shape milestone. Do not wait until every material family or Gate 8 is complete to exercise that path, and do not interpret it as permission to hide the open conservation, performance or fracture defects.

Previous sphere checkpoint: **automatic Windows Codex proposal/clarification prototype** at `ae82167`. The [assistant checkpoint](assistant-checkpoint.md) records real glass/oak/iron provider calls, an unsupported-door clarification, cancellation/retry and normal sphere UI creation. The manual bridge remains available. The [creator checkpoint](creator-checkpoint.md) records the original inventory/compiler/physical-object foundation. The current [shape checkpoint](shape-checkpoint.md) adds boxes through those boundaries, with normal verification of the new controls still pending. Modifications/refunds, further geometry and general publishing remain open. See the [mechanics/platform scorecard](mechanics-scorecard.md), [current reference evidence](adaptive-checkpoint.md), [project master plan](project-master-plan.md) and [roadmap](roadmap.md).
