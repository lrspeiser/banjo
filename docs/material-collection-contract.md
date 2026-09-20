# Material collection and preserved objects

Owner direction, September 20, 2026. This is the required contract for the
remaining collection, carrying, construction and salvage work, not a claim that
all of those workflows are already implemented.

Collection must distinguish two representations:

- **Object instance:** identity, construction, geometry, component connections,
  primary Use program, damage, temperature/energy, contents and operating state.
  Taking a crafted object moves that instance. It does not grant its bill of
  materials, repair it, refill it or rebuild it from a pristine design.
- **Material stock:** measured quantity, substance/composition, temperature or
  enthalpy, phase and supported processing state. Raw means an unprocessed
  resource (wood, ore, sand), not automatic separation into chemical elements.

Origin (generated, manufactured or recovered) is provenance, not a conversion
rule. A generated log, stone or useful component can still be picked up intact.
A generated loose-resource deposit can declare a harvest operation that yields
raw stock. The action and source representation determine the result.

## Required operations

**Pickup / put down** transfers custody and placement of an object instance.
Physical carrying limits and placement checks still apply. Unsupported compound
or active-state storage must refuse explicitly rather than silently simplify it.

**Harvest** removes a measured amount from a resource source and produces the
specified raw stock or debris, retaining mass/composition and transported energy.
The source cannot be harvested twice through retries or concurrent requests.

**Disassemble / salvage / process** explicitly transforms an object or material.
It consumes declared work and time when required, retains work in progress,
and produces actual remaining components, usable stock and waste. A material
recipe is not permission to erase damage or turn an assembly into pristine stock.

## Current boundary and acceptance

Inventory currently identifies existing native bodies and uses park/unpark for
supported single-piece objects. General articulated storage and complete active
contents behavior still require qualification. Terrain digging retains native
sand/soil quantities. Fabrication recovery moves only already-accounted cold
homogeneous offcuts within its material bins; it cannot consume an object ID or
an unfinished workpiece. Ground-to-station transfer remains unimplemented.

Before completing these workflows, QA must compare intact and damaged crafted
items before/after pickup, storage, restart and placement; retain compound joints,
energy, temperature and contents; test generated objects versus loose deposits;
and verify harvest/salvage accounting, failed saves, retries and shared spending.
The browser and LLM API must expose the same explicit operation and result type.

## Stored-state regression, September 20

The native inventory suite now compares glass, oak and iron boxes heated from
900 K for 10 s (1/240 s native steps), then stored, saved, reopened, held in
storage for 0.5 s and returned. It compares retained heat parcels, fuel/history,
material reference geometry and native body fields. Placement changes pose and
the exposed area from five to six faces; zero instantaneous thermal rates while
parked are expected, rather than erased stored energy. No calibrated damage or
general compound-storage claim follows from these cases.

A refused stow previously released the native hand before the storage preflight,
leaving the inventory claiming the dropped object. The room now lets native park
perform its preflight before release and updates saved facing only after success.
A refusal regression retains the actual hand and complete inventory record.
All 11 native inventory-room tests pass. These cases already run in CI through
`tests/inventory_room_tests.py`. Frozen thermal evolution in the bag remains an
explicit limitation; physical container heat exchange and articulated storage
are still required.
