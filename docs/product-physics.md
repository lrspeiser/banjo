# Product physics: detail in Workshop, behavior in the live world

A Banjo product is not a named archetype such as a table, kettle, cart,
guillotine or merry-go-round. It is a **physical product graph**. Named products
are examples made from the same components, interfaces and relationships.

The design goal is intentionally asymmetric:

- **Workshop preserves design detail and may spend computation** to test a
  product at high fidelity.
- **The live world preserves behavior and real-time interaction**, reducing or
  deferring detail that does not affect the current interaction.

The rule is:

> Simulate every degree of freedom that affects behavior, not every piece of
> geometry that was used to design it.

And the safety rule is:

> Workshop evidence is what permits a reduction. Outside the evidence envelope,
> refine the simulation or say the reduced model does not cover the event.

## ProductGraph

`mcp/product_graph.py` defines `banjo.product-graph.v1`.

A graph has:

- **components** — stable ids, role/family/material, source geometry, mass
  properties, physics tags, capabilities and interfaces;
- **interfaces** — surfaces, ends, shafts and future electrical, fluid, thermal
  and control ports, with points/axes/normals in product-local coordinates;
- **relationships** — contact, support, fixed, hinge, slider, bearing, rope,
  pulley, drum, spring, gear, rack, contains, thermal contact, electrical,
  control and flow;
- **energy** — stores, motors, heaters and future sources/transmissions;
- **controls** — the intentions exposed by a machine and the actuator/control
  graph they drive;
- **contents** — matter held by containers or regions;
- **tests/evidence** — scenarios, measured results and validated ranges;
- **manufacturing** — eventually the stock/process/tool/energy graph needed to
  make it.

Workshop's current wire parts adapt into this graph through
`mcp/workshop_graph.py`. Geometry-derived touching is deliberately
`physical-contact`, never `fixed`: touching parts may be bearings, wheels,
sliders or merely resting against one another.

## Deterministic composition

`mcp/product_mating.py` solves interface-to-interface placement. The user or
agent chooses *which* interfaces should meet and what relationship they mean;
code computes the rigid transform.

A language model therefore says things like:

- attach this leg end to that mounting surface;
- put this wheel hub on that shaft as a bearing;
- hinge this door edge to this frame axis;

It does not invent XYZ coordinates.

The first mating operation moves one unconnected component. Moving a linked
subassembly is deliberately refused until grouped graph transforms are
first-class, rather than silently tearing an existing mechanism apart.

## Physics tags and the library

The personal SQLite Workshop library indexes items by semantic namespace:

- `physics`: beam, plate, rotor, shaft, rolling_contact, heater, container, ...
- `interface`: surface, shaft, fluid, electrical, ...
- `relationship`: fixed, bearing, hinge, slider, ...
- `capability`: rotates, rolls, supports_load, powered, ...
- `test`: static_load, impact, heat, stall, ...
- `role` and `family`.

This is intentionally orthogonal to names. A search for a shaft/bearing product
should find a cart wheel module and a rotating ride hub for the same physical
reason.

Saved component recipes also carry their ports, physics tags and capabilities,
so those semantics survive export/import rather than existing only in the DB.

## PhysicsContract

`mcp/product_contract.py` compiles a detailed graph to
`banjo.physics-contract.v1`, the representation intended for a live world.

### What may be reduced

Only components linked by an explicitly declared `fixed` relationship may be
collapsed automatically into one rigid runtime body.

A geometry-derived contact is only a **candidate** reduction and says
`requires_validation: true`.

Decorative geometry may eventually be visual-only. Detailed collision meshes
may become semantic proxies such as a plate, beam, shaft, rotor or blade.

### What must survive reduction

The contract preserves or accounts for:

- total mass;
- centre of mass;
- inertia;
- important collision zones;
- declared degrees of freedom and mechanism relationships;
- load paths;
- energy stores/actuators and controls;
- contents semantics;
- structural/failure modes;
- source component ids, so an event can refine back into detailed parts.

Numeric failure limits are never invented by the compiler. They come from
material laws or test evidence.

### Physics levels of detail

A product can effectively have several simultaneous LODs:

0. **visual** — detail that currently affects appearance only;
1. **collision** — cheap semantic collision zones;
2. **mechanism** — rigid bodies and exact important DOFs;
3. **reduced structure** — plates/beams/load paths/attachments responding to
   forces without a full lattice every frame;
4. **local fine physics** — lattice/fracture/thermal or other expensive detail
   only where an event requires it.

The LOD is per behavior, not one global quality switch. A complex machine may
run its shaft and bearing at mechanism fidelity while a single overloaded mount
is being refined at fine structural fidelity.

## Example: boulder on a table

The live collision need not lattice-simulate every table cell every frame.

A contract can say:

- the tabletop is a plate collision/load zone;
- four leg mounts accept its reactions;
- each leg is a beam/load-path member;
- the whole product has tested mass, COM, stiffness/failure evidence over a
  stated range.

A boulder impact is first resolved against the tabletop zone. The reduced model
computes the local plate response and reactions at the leg mounts. If the event
approaches a recorded failure mode or exceeds the validated impact range, only
that zone/attachment is promoted to fine physics. The result then updates the
coarse product state (for example, one mount broken and a leg detached).

## Arbitrary machines

No compiler branch should say `if product == "guillotine"` or
`if product == "merry-go-round"`.

A guillotine is generically:

- structural frame components;
- a blade/cutter component;
- a slider relationship;
- optional rope/counterweight/latch/control relationships.

A rotating ride is generically:

- foundation and shaft;
- a platform rotor;
- bearing relationship;
- optional motor/gear/energy/control graph;
- distributed payload components.

The same compiler sees the slider or bearing, collision zones, mass properties,
load paths and control graph and emits the runtime contract.

## Refinement triggers

The runtime contract asks for more fidelity when:

- an interaction leaves a validated Workshop range;
- reduced stress/load approaches a failure threshold;
- a collision cannot be represented by the current semantic zone;
- temperature leaves the tested/material range;
- a requested DOF or contents behavior is unsupported;
- the player explicitly asks to inspect/test it at higher fidelity.

Refinement is local whenever possible.

## Current boundary

The generic graph, first runtime contract, semantic library tags and deterministic
single-component mating are foundations. Workshop's kettle and hoist are test
fixtures for existing heat/machine systems, not product types in this
architecture.

Still to build on this contract:

- move/mate whole subassemblies;
- edit relationships directly in the Workshop UI;
- import asset-compiler/CAD geometry and exact mass/collision properties;
- attach engine test evidence and validated ranges to library versions;
- reduced structural response curves/surfaces from Workshop trials;
- adaptive live-world refinement and state handoff after a local break;
- world placement/inventory/process/energy transaction;
- manufacturing/process graph and cost beyond raw materials;
- free-liquid mechanics when Banjo has a supported liquid model.
