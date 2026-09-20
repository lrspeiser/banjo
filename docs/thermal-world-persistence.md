# Thermal state across world restarts

New native world snapshots include heat.network with schema
banjo.thermal-state.v1. Reopening the identical scene restores the thermal
clock, heater IDs and schedules, finite gas parcels, vents, piston boundaries,
heat paths and cumulative energy/material ledger. Existing heat.lumps retain
surface/core contents, energy, peak temperatures, fuel history and parked state.
Restoration does not advance time or replay elapsed heater work.

The same behavior is used by the existing native snapshot/open operations,
HTTP POST /api/world/open and MCP world_open_saved. No additional command,
MCP tool or ABI change is required. A native binary containing this change is
required; updating Python or JavaScript alone does not enable it.

## Compatibility and editing

Old snapshots without heat.network migrate the body parcels they actually
saved: surface/core mass and energy, fuel, initial composition, peak temperature,
and parked state. The energy/material ledger begins a new accounting period at
that imported state; it does not claim to recover past work or losses.

Missing clocks, gas state and heater histories cannot be reconstructed. Gas
retains the legacy scene initialization, and heaters without saved schedules are
suspended instead of replaying work. New heater commands remain available.
The not_kept report explicitly identifies this boundary. This is partial
legacy migration, not lossless recovery of information older saves omitted.

Changing a scene remains a separate operation. An edit that carries every old
thermal lump, introduces no new thermal lump, and has no gas or heater schedules
can retain its network history and recompute geometric heat paths. Atomic
installation compares the resulting network and refuses any changed existing
state. General edits involving active heaters or gas are still refused by that
installation adapter. Do not remove those checks based on whole-world restore
support.

Malformed network schemas, substance counts, references and path indices do not
qualify for a whole restore. Existing world-open fallback reporting applies;
callers must inspect restored.tier and restored.why.

## Regression evidence and limits

banjo_room_carry_tests includes a matched glass/oak/iron thermal restart with a
finite vented argon chamber, a scene heater and a dynamically created heater.
After 0.2 seconds it compares the entire serialized thermal state, then compares
another second of uninterrupted and restarted evolution exactly. Heater expiry
is included. Energy residual must be below 1e-7 J and material residual below
1e-12 kg. It also checks malformed indices, legacy parcel/history preservation, suspension of missing heater schedules and ledger closure after migration.

A separate moving-piston test preserves gas pressure state, boundary displacement
and accumulated mechanical work exactly at restart, then verifies the continuing
thermal ledger. Contact solver warm-start memory is still absent; exact moving
mechanical trajectories after restart are not claimed. These are persistence
regressions of the existing thermal laws, not new material calibration or
qualification of pipes, pouring, boiling, or every thermodynamic cycle.

The full 30-capability objective remains open. Next: state-preserving edits of
active thermal machines and broader fluid/contents persistence. The updated
engine is deployed to the main-world server on port 8793. [Deployment evidence](evidence/thermal-world-deployment.json)
records migration of the actual saves and an exact live save/reopen comparison.

Verification on Windows: 10 native room-carry cases, 18 native installation tests, seven startup-upgrade tests, 25 room-store tests and 11 API-documentation tests passed. All 275 C++ sources remain registered. No constitutive law changed; the full impact matrix was not rerun for this persistence checkpoint.
