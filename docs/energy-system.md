# Energy for making, using and breaking objects

**Owner inventory requirement:** collected resources belong in the user’s inventory. A natural-language creation request must explain what is possible with that inventory or precisely what else is needed. Preserve requested dimensions/material when short, distinguish held material from world pickups and selected recovery, and offer alternatives explicitly. Extend the requirements bill to energy sources, capable tools/processes and supported behavior as those models are implemented; missing capability is distinct from missing supplies. Queries must not spend resources. [Current implementation and acceptance evidence](requirements-checkpoint.md).

Owner direction, September 4, 2026 Pacific: creation and destruction should require energy because material transformations and the bonds/interfaces involved have energetic consequences. This document proposes the world/API contract. It does not introduce calibrated fabrication, chemical, thermal or fracture laws, and no energy cost is implemented in the current creator runtime.

The application becomes **collected materials + available energy + a capable tool/process → an inspectable construction plan → a working physical object**. The LLM can plan within those resources; it cannot assign a convenient energy cost, mint energy or choose the resulting fracture.

## Physical meaning

Separating bonded atoms requires energy; forming stable bonds releases energy. A complete reaction includes both, so its net energy change depends on the initial and final states. Macroscopic manufacture also involves positioning and processing material; a lower-energy final state does not imply a usable fabrication route exists. Gas-phase bond-energy tables are not ready-made cutting costs for bulk glass, wood or iron. [OpenStax, Chemistry 2e, section 7.5](https://openstax.org/books/chemistry-2e/pages/7-5-strengths-of-ionic-and-covalent-bonds).

Energy must be accounted for as changes of stored state and transfers of work/heat across a declared boundary. The underlying conservation requirement follows the first law; our choice of reservoirs, tools and API fields below is a Banjo design proposal. [OpenStax, University Physics, section 3.3](https://openstax.org/books/university-physics-volume-2/pages/3-3-first-law-of-thermodynamics).

For structural failure, a continuum traction/separation law can define fracture work through its integrated response, expressed per unit interface area. This is an appropriate model family to investigate for Gate 2; it is not proof that Banjo's current deleted-spring diagnostics implement it. Effective fracture energy can include multiple unresolved processes, so those processes must not also be charged separately without a consistent decomposition. [Abaqus documentation, Contact Cohesive Behavior](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEITNRefMap/simaitn-c-cohesivebehavior.htm).

## Proposed world contract

| Element | Required behavior |
|---|---|
| Energy source/store | Stable identity, energy in joules, capacity, maximum input/output power in watts, revision and provenance. Start with a workbench energy store; add batteries, fuel, generators and other sources through explicit conversion laws. A displayed fuel mass is not an implemented combustion model. |
| Tool and process | Supported operations, input/output material and state, required work, power/duration limits, efficiency and heat/output paths, model version and validity. Cutting, joining and forming are different processes. Unsupported transformations fail capability checks. |
| Material and interface | Geometry, existing damage/state, direction and the implemented constitutive/interface parameters determine supported response. Do not use a display-name price table as a physical law. Manufacturing cost cannot be inferred from density alone. |
| Plan and preview | Material allocations, energy source, energy/work estimate and bounds, tool/process identity, expected state changes, waste/recovery, duration, assumptions and unsupported parts. Separate net energy change from peak power/process feasibility. |
| Acceptance | Validate current object, material and energy-store revisions; reserve/check all required resources and publish their changes with the object and a durable operation receipt. Insufficient energy or a stale source cannot leave a half-created object or a partial debit. |
| Execution | A bounded process can deliver work over time. Once physical work is performed, cancellation must retain spent energy and actual material state; only unused reservations are released. An unstarted or failed atomic authoring transaction can roll back fully. |
| Evidence | Record before/after stores and material/mechanical state, work transfers, named irreversible processes, heat or unresolved internal-energy destination, external sources/sinks, numerical residual and model versions. Preserve these on reload and distinguish them from gameplay currency. |

For a chosen complete boundary, require `energy_before + energy_in = energy_after + energy_out + numerical_residual`. The residual is reported and bounded by justified tests; it must not be silently added to a battery or relabeled as heat to close an unexplained discrepancy.

Stored quantities can include mechanical, elastic, chemical/interfacial and thermal energy only where their models exist. A mechanical-only approximation may instead track irreversible work into an explicitly unresolved internal-energy sink; this is not a temperature simulation. Fracture work, surface energy, plastic work and resulting heat must not count the same transfer twice. Energy released by a process can recharge a store only through a supported capture/conversion path with its losses and capacity checked. Generic waste heat is not automatically interchangeable with stored electrical energy.

## Creation, breakage and reclamation

- **Build or reshape:** charge the implemented fabrication process, including changes to position and initial motion. Existing collected material already contains its structure; do not charge the energy of making every original chemical bond again. If a simplified or fictional workbench process is used first, label it and version its parameters explicitly; it does not establish real wood/glass/iron manufacturing costs.
- **Break through physical interaction:** energy comes from the striker, a stretched spring, falling mass, powered tool or another modeled source. The solver partitions it into remaining motion, recoverable deformation, fracture/plastic work and other supported losses. No second generic destruction fee is added to the same impact. Existing stored energy can cause failure even when the workbench store is empty.
- **Reclaim or disassemble:** return only the material/state actually recovered under the declared process. Recovered mass does not refund the energy spent producing it. Irreversible damage remains; remaking useful stock or repairing an interface requires its own supported process. Disassembly may release stored energy, with a defined destination and hazard/limit handling rather than an automatic energy credit.
- **Bond or join:** changing connectivity must use an implemented interface/process model with state and history. Neither creating a numerical spring nor deleting it is, by itself, a calibrated chemical or fracture-energy calculation. Resolution changes cannot change cost simply by changing the number of simulated bonds.

The current `intact-return-100pct-v1` rebuild/reclaim implementation is an authoring sandbox operation. It records mechanical discontinuities, resets replacement motion and returns intact lots, but supplies no energy source or manufacturing law. Preserve that explicit limitation; it cannot serve as the final energy-constrained application. Do not hide an unpaid transformation under a renamed energy-aware command.

A further prerequisite is the **physical reference state of inventory**. Today's lots hold mass/provenance, not location, motion or thermal state. Energy-accounted pickup, placement and reclamation need a declared stock/workbench reference state and the relevant external support reactions. Charging only the created object's potential-energy increase would omit the source material's original energy. A coarse inventory reservoir is acceptable if its boundary and state are explicit.

## API additions

Extend capability discovery with energy stores, process/tool versions and supported transfers. Add queries for stores and process estimates; bind a construction plan to source-store and object revisions; report `insufficient_energy`, `power_limit`, `unsupported_process`, `stale_plan` and accounted execution status. Names are proposed contracts, not implemented error codes.

The human editor and LLM must use the same preview/accept/run APIs. A request such as “Make this from my wood using the workbench's remaining charge” should expose both the material and energy bill. A bounded assistant may propose a smaller design, a different supported process, another source, or ask for more resources. It must preserve the requested function or explain why it cannot meet it. Trial simulations use isolated snapshots and cannot consume or recharge the live world's inventory/stores.

## Implementation order and acceptance

1. Retain the current mechanical audits and explicit authoring limitation. Establish the inventory reference state, energy-store/transfer schema and process-capability contract alongside lifecycle transaction work. Do not assign invented physical cost numbers merely to enable a debit counter.
2. Implement a bounded workbench process with named inputs/outputs, measured or explicitly declared approximation, energy/power checks, one-owner execution and transactional receipts. Test analytical positioning/spin/work transfers before claiming bond-aware manufacture.
3. Connect real mechanical work to energy-consistent interface fracture and supported forming/joining laws. Preserve the existing Gate 1 correction-energy defects and Gate 2 calibration/convergence work; an energy inventory does not solve either.
4. Expand to energy generation, storage/conversion, thermal state and additional processes through tested laws. Carry this through useful mechanisms and publishing capabilities.

Required evidence includes no double debit on retries/reload; stale-store and insufficient-energy rollback; cancellation before versus after work; capacity and power limits; material-and-energy conservation for pickup/build/rebuild/reclaim; lift/lower and spin-up/braking references; fracture-work/area accounting; and build/break/rebuild cycles that cannot generate net usable energy without an identified source. Reference-state changes and numerical refinement must not create energy credits.

Retain **glass, oak and iron** under common geometry, loading, interfaces and numerics, reporting each separately. Add intentionally process-specific comparisons as supported models grow. Glass fracture, directional wood splitting and iron plastic work require their own validation; the current rigid and elastic approximations do not provide those laws. Track this work under M05, M16, M17, M25, M27 and P05–P07 of the existing scorecard, without dropping any previous requirement.
