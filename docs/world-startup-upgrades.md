# Starting equipment in saved worlds

Fresh main worlds include the battery hoist on the east terrace. Existing main
worlds receive it on opening or rejoining only when an append-only installation
can preserve the running state. The browser describes where it is and how to use
it. The Room tab has a Controls button for each controller, using the same
engine commands as the panel opened by aiming at its machinery. This is initial world equipment supplied by the world author: its material
and 5000 J battery are explicitly external supplies, not player manufacture.

## One transaction for the browser and MCP

`POST /api/world/open` with `{"scene":"world"}` opens or rejoins the world.
`world_open_saved` in both MCP servers calls that same endpoint through
`BANJO_PLAYGROUND_URL`. Its optional `scene` defaults to `world`; another
scene switches the local server's active room. It does not request `fresh` or
`again`. The response returns the current session and `world_upgrades`:

| Status | Meaning |
| --- | --- |
| `present` | The equipment already existed; recorded without changing it. |
| `installed` | New equipment was staged, verified and atomically saved. |
| `already_applied` | Durable receipt exists; no equipment or energy is added. |
| `pending` | Installation was refused; `reason` explains what needs resolving. |

Receipts contain the package ID, package hash, simulation time, title, usage
help and source-of-material/energy statement. They live beside the native
snapshot in the same room file. Renaming, dismantling, moving or depleting
equipment after its receipt never causes another supply on reload.

The trusted [upgrade catalog](../progression/world-upgrades.json) declares
self-contained bodies, joints, stores, motors and actions. It is not a public
arbitrary-code input. Later additions use new package IDs. A partially occupied
name set is refused; user objects are never overwritten. Existing complete
equipment is adopted as it stands, including user changes.

## Preservation checks

Opening has exclusive world access; nested installation by that thread keeps
the same exclusion. A separate native process stages the proposed scene.
Every existing serialized body, topology, damage/plastic field, joint,
battery, motor, controller and water state must survive unchanged. The comparison
also checks unknown future global fields. Only documented new components and
their identifier increments may appear. Existing thermal lumps are compared;
this does not establish complete thermal-network persistence.

Changed-scene carry explicitly supplies the snapshot's water state to the new
scene, preserving flow, volume, time and ledger values. Placement checks use
the existing bodies' current collision envelopes. A failed stage or failed
atomic save closes the staged process and leaves the original process and room
unchanged. The live process is swapped only after the durable write succeeds.

A native rope restore defect found by these comparisons is corrected: the last
taut/slack solver setting is restored without taking a simulation step. The next
step still computes rope behavior using the existing physical law. This does
not preserve Jolt's full contact/warm-start cache or promise bitwise continuation.

## Remaining boundaries

Active heaters, gas regions, pending fracture/cutting work, incompatible cell
resolution, name conflicts and overlapping player builds can leave additions
pending. In particular, declared thermal schedules may be recreated by the
underlying carry path: the staged-state check refuses that outcome rather than
restarting the schedule silently. Complete heater/gas persistence remains work.
The ordinary room restore path has its own reported thermal limitations; this
upgrade does not remove them.

The hoist's support is anchored. Load-rated mount reactions, funded articulated
construction and the other broad capability requirements remain open. This
checkpoint does not mark another of the 30 capabilities complete.

## Verification

The native upgrade suite exercises a running terrain/water world, lifting and
battery depletion after installation, repeated opening, durable receipts after
restart, active-heater refusal, partial equipment, blocked placement, failed
saves and actual HTTP/MCP adapter requests. The native rope suite checks both
whole restore and changed-scene carry, then verifies continued support.

Run `BANJO_LIVE_ENGINE=<runner> python tests/world_upgrades_tests.py -v`.
CI runs this suite alongside machine, mechanics and material regressions.

[Checkpoint measurements and local replay IDs](evidence/world-startup-upgrades.json) record the 44 mechanics and 96 material-impact runs, saved-room checks and browser operation.
