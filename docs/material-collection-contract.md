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


## Excavated bulk transfer primitive (source work, September 20)

The native line protocol adds the internal operation
`{"op":"ground_withdraw","sand_m3":0.001,"soil_m3":0}`.
Both volume fields are required, finite and nonnegative; their sum must be
positive and neither may exceed the corresponding carried inventory. A refused
withdrawal changes nothing. A successful withdrawal reduces the carried account
and increases cumulative exported volume; it does not dig again, change bodies,
advance time or convert either substance into an engine solid preset.

The response includes `material_packet` with schema `banjo.bulk-material.v1`,
source `excavated_ground`, form `granular`, thermal_state `unmodeled`, and contents
entries containing substance, volume_m3 and mass_kg. Mass uses the native terrain
bulk densities. Sand and soil remain distinct substances. No object ID is a
source for this primitive. It cannot recover a crafted object or its recipe.
The thermal marker is deliberately not a 293.15 K default: terrain currently
has no transported temperature/enthalpy state. A later thermal process must
account for that missing model rather than silently claiming energy closure.

Ground snapshots become `banjo.ground-state.v2`, adding `exported` volumes.
Version 1 reads with zero exports. Version 2 requires the field and refuses
nonfinite/negative export totals or exported-plus-carried quantities exceeding
excavation. Exported rock is unsupported; existing rock cuts remain bodies.

This is an internal source-side transfer primitive, not yet a user-facing
stock deposit. A receiving store, idempotency receipt, source/destination audit,
and native-snapshot-plus-store durable transaction are still required before
HTTP/MCP/browser exposure. Calling it twice means two withdrawals; transport
retries must be handled by that transaction layer. It must not be used directly
against the running player world before a destination can be committed. The
currently deployed local world remains on the previous runtime.

Verification: 27 native installation cases pass; the strengthened mixed-material case then passes independently. It digs through 0.02 m of sand into soil on a 0.25 m grid, withdraws half of each substance, reopens the snapshot, rejects invalid requests without changing state, and withdraws the remaining halves. Native densities are 1600 kg/m3 for both declared bulk materials; substances remain separate. Existing bodies and non-ground snapshot fields stay unchanged. Seven corrupt-ground cases include an export exceeding excavation. The source-registration guard remains 275/275.

## Durable raw receiving deployed (September 20)

The receiving transaction described above is now implemented and deployed on local port 8793. `POST /api/world/fabrication/store_ground` and MCP `fabrication_store_ground` stage the native withdrawal, validate both accounts, and save source snapshot, raw lots and retry receipt together before replacing the live session. The reply returns the new session; an identical request ID is replayable using its original session after a restart. Failed saves leave the original live source untouched.

Raw lots retain substance, mass, volume, granular form and explicitly unmodeled thermal state. Sand remains sand and soil remains soil; neither enters the finished glass/oak/iron stock. Crafted-object pickup remains separate and retains the object. No proximity, container capacity, handling energy or raw-processing law is claimed. See the [fabrication contract](fabrication.md#stored-excavated-materials), [before screenshot](evidence/raw-material-before.png) and [after screenshot](evidence/raw-material-after.png).

## Raw retrieval and return to terrain (September 20)

`POST /api/world/fabrication/retrieve_ground` and MCP `fabrication_retrieve_ground` return selected remaining sand/soil from a named lot into native carrying. Native `ground_return` is an internal transaction primitive, not direct authoring supply. The adapter stages the native credit and lot debit, checks both accounts and saves the replacement world plus return receipt before swapping sessions. Read `raw_inventory` for current available quantities; original `raw_lots` retain provenance and `raw_returns` retain debits.

Ground-state v3 adds cumulative `returned` beside cumulative `exported`, so repeated storage cycles preserve history without counting matter twice. Existing v1/v2 saves migrate with zero returns. Capacity checks use the native ground carrying limit, currently distinct from bag/equipment mass. Existing carried-material deposit puts retrieved matter back into terrain. This does not create a physical storage container, processing law, handling-work cost or thermal state. The browser's mixed-lot mass selector preserves remaining proportions; API clients may select the two substances independently.

[Before](evidence/raw-retrieval-before.png), [after](evidence/raw-retrieval-after.png) and [saved-state evidence](evidence/raw-retrieval-deployment.json) show a 0.500 kg retrieval from the main-world lot and preservation through reopening.

## Shared carrying admission (September 20)

The preceding ground-only limit is superseded in terrain worlds by a budget including native held/stored body mass. Retrieving raw stock, digging and tool breakout cannot use capacity already occupied by crafted objects. Native grab/wield and park refuse additional load before mutation. Existing items keep identity and saved physical state; stow/equip does not duplicate mass. [Carrying contract](fabrication.md#shared-carrying-budget) documents reported quantities, float32 mass precision and unsupported cases.

## Internal heat while stored (September 20)

Stored native objects now continue their existing surface-to-core heat conduction over accepted world time. Parking still disconnects external heaters, ambient/floor/contact heat paths and reaction exchange. This is explicitly insulated, nonreacting storage; it does not model a physical bag, finite container air, contact between packed items or a safe way to store reactive material. Total internal energy and composition stay with the object. Single-temperature objects remain unchanged until an external connection is restored.

The same two-node conductance/capacity law used in the world runs while parked. Save/restore retains its temperatures and energy, and returning the object uses those evolved temperatures. The regression compares 400 K surfaces and 300 K cores against exponential equilibration for glass/oak/iron, checks energy and material closure, and checks exact continuation after restoring an intermediate state. Existing higher-temperature live inventory cases separately verify preserved material and total energy while stored. No external cooling or general chemical-storage claim is made.
