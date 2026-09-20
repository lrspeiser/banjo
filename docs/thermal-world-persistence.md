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

Changing a scene remains a separate operation. New snapshots stamp global
thermal declarations as heat.scene_settings and expose
carry_readiness.thermal_network_version = 1. When every thermal body and piston
support carries unchanged and global declarations still match, the native carry
restores the operating network, including active heaters and gas, then refreshes
geometry. Changing a pressure or heater declaration cannot silently reuse the
previous network under this rule.

Atomic installation keeps existing parcels, temperature history, gas, heaters,
clock and all prior ledger history exact. Geometry-derived contacts, radiation
paths, ambient view fractions and exposed area can change when a new part is
placed nearby. Undeclared cold bodies activated by these paths join the thermal
network at their existing ambient state; their parcel mass and internal energy
must match the added joined_kg and joined_j ledger crossings. This expands the
thermal accounting boundary, not the world's physical material inventory.
Authoring remains externally supplied construction; funded manufacture has its
separate material account.

Only the sums of newly admitted parcel energy/mass allow floating-point rounding,
bounded by the parcel count and double precision. Altering old energy, heater
work, fuel, damage history or other ledger crossings still fails staging.
Explicitly declared new hot inventories require a separate transfer and are not
admitted by this rule. Older engines without the capability and declaration stamp
still refuse active thermal installation. Old snapshots without the stamp retain
the previous quiescent-only carry rule.

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

The full 30-capability objective remains open. Next: persistence of reference
geometry for thermally receded bodies, funded articulated assembly, and broader
fluid/contents persistence. The updated
engine is deployed to the main-world server on port 8793. [Deployment evidence](evidence/thermal-world-deployment.json)
records migration of the actual saves and an exact live save/reopen comparison.

Verification on Windows: 10 native room-carry cases, 18 native installation tests, seven startup-upgrade tests, 25 room-store tests and 11 API-documentation tests passed. All 275 C++ sources remain registered. No constitutive law changed; the full impact matrix was not rerun for this persistence checkpoint.

## Active thermal carry checkpoint

Ten native room-carry cases now include active vented gas and glass/oak/iron
heating during an unrelated addition, exact subsequent thermal continuation,
changed-pressure declaration invalidation and preservation of a moving piston's
pressure/work state. Twenty native installation tests include timed heaters,
live gas and refusal of older capability reports. Seven startup-upgrade tests
and twelve installation-boundary tests pass. No constitutive law changed.

The active-carry work is now included in the thermal-paths build deployed on
port 8793. [Current evidence](evidence/thermal-paths.json) records native additions,
API tests, comparative heat transfer and checks of the actual saved worlds.
Material-funded articulated assembly and the remaining capability gates are open.

The actual HTTP/MCP startup-upgrade test also carries an active heater and compares its thermal state exactly. All 44 mechanics cases pass on the final heat-path build. The 96-case material matrix passed against the fixed baseline on the preceding active-carry build; it does not qualify thermal geometry continuation.


## Geometry-reference limitation

Thermal parcels and the network are serialized, but the host's MatterRecord
reference dimensions and applied recession depth are not yet in disk snapshots.
A reference reconstructed from already-receded geometry can apply past recession
again on subsequent stepping. Immediate snapshot equality does not establish
correct geometric continuation. This is the next persistence defect to address;
do not interpret these tests as complete fire-damage or whole-world persistence
qualification.

## Heat-path verification

Ten native carry cases now also test cold glass/oak/iron additions in contact
with hot bodies: existing stored state remains exact, each new part receives
heat after stepping, and the enlarged thermal boundary closes to 1e-7 J and
1e-12 kg. Twenty-one atomic native installation tests include nearby radiative
admission and deliberate corruptions of old energy, heater history and admitted
energy. Seven startup and twelve boundary tests pass. The live server runs this
build, with saved 54-body main, 20-body yard and four-body fabrication probes
preserving all compared physical fields.


### Material reference geometry (source implementation, deployment pending)

New native snapshots include `material_geometry` with schema
`banjo.material-geometry.v1` and records keyed by body name. Each record retains
the thermal reference dimensions/frame, applied recession, geometry revision,
burned-cell count, remaining volume, bond summaries and cached material factors.
The associated fracture limits and acoustic impedance travel with those cache
flags so reopening cannot suppress a needed strength update against cold limits.

Identical-scene reopening and compatible body carry restore these records before
thermal shapes are built. The installation comparator requires every old record
to remain exact; additional records may only belong to newly installed bodies.
No HTTP/MCP signature changes are required: these fields travel in the existing
opaque native snapshot.

Verification: actual oak combustion, glass/iron controls, three repeated
save/reopen continuations, and a distant part addition pass in the 11-case
native room-carry suite. All 13 installation-boundary tests pass, including
rejection of changed recession, missing records and unknown body references.
This does not qualify legacy saves: their missing reference history remains the
next migration task. The running main world has not been restarted onto this
new build. No full-engine or constitutive-law qualification is claimed.
