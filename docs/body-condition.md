# Native item condition — October 1, 2026

Publication revision is recorded after the verified checkpoint is pushed.
This is a partial implementation of item 11 in the
[fourteen-item acceptance list](player-experience-checklist.md).
Four items are verified and ten are partial. Repair and fatigue remain open.

Native runner, C library, platform CLI and new/affected native test targets were
rebuilt in `build/agent-progression` with MSVC Release from this checkpoint's
implementation sources. The refreshed port 8770 preview passes actual Chrome
fresh entry, native pick condition and exact-rigid unmodeled inspection with
zero script exceptions. [Verified preview](http://127.0.0.1:8770/world?world=cf9366a6262c439fb84a7fbdfadcc891).

## Implemented and measured

World selection, carried Inventory products and an explicitly selected carried
Lab item show a native **Condition** meter. Saved designs and an empty Lab have
no physical meter. World selection reads at most once per second; carried
Workshop readings refresh every five seconds. Details show native broken bonds,
current thermal section factors and dents separately. The Lab reading describes
the carried source; editing a candidate does not heal that source.

The diagnostic uses retained native `ActiveBondState` damage, not hits or uses:
`connections_fraction = 1 - sum(alive ? damage : 1) / retained_bond_count`.
For a tracked material with a supported thermal law it also reads the minimum
of tension, compression, shear and both bending section factors. The meter is
the minimum of the available connection and thermal readings. It is an index,
not a strength certificate or predicted service life. Dents are reported in mm,
not converted to arbitrary damage points.

Actual separation reports **Broken**. An admitted but unfinished native fracture
reports **Checking damage** with no numeric fraction. Missing bodies report
**Not reported**; exact rigid bodies without internal damage laws report
**Not modeled**. A merged head/handle's native `source_parts` cover the authored
component names; other missing components remain unavailable. Unknown parts in
a multipart item prevent a fabricated whole-item percentage.

Windows / MSVC Release / Python 3.13 / Chrome, unchanged laws and tolerances:

- Four CMake-registered native cases pass. All three materials start at 100%
  retained connectivity. Repeated inspections preserve the full native snapshot.
  One hundred three-body reads, including JSON parsing, take 11.621 ms in the
  final fixture run (about 0.116 ms/read); this is not a general scene/frame budget.
- Matched 100 mm targets, 10 mm cells, `dt=1/240 s`, a 6 m/s iron blade with
  0.05 mm edge radius: oak loses 104 of 12,876 bonds, retains 99.1923%
  connectivity and records 5.07526 J of cutting work. It stays cut after
  drifting, whole-world reopen and bag parking. Glass and iron acquire no
  unsupported blade cut (0 J); this cutting-only comparison declines contact
  fracture as the existing blade oracle does.
  Declared densities are glass/oak/iron 2,500 / 700 / 7,870 kg/m³;
  the same target volume represents 2.5 / 0.7 / 7.87 kg respectively.
- Matched 80 mm cubes, 20 mm cells, no gravity, 2 kW for 10 s: oak's minimum
  current section factor is 0.836458; iron retains 1. Glass has no supported
  thermal strength law and returns null. These are the existing native section
  readings, not a new heat or damage law.
- A real 3 m glass-pane impact reports unresolved through the native worker,
  then Broken after actual topology commit. No fragment animation supplies
  the result.
- The new authenticated HTTP/private Inventory/Chrome suite passes two cases:
  query leaves the native snapshot unchanged; malformed/oversized/UTF-8 names
  refuse; another player's carried list stays empty; bag readings survive a
  complete server restart. Chrome verifies World measured/unmodeled states,
  Inventory, carried Lab and empty Lab with zero script exceptions.
- Native condition, existing thermal-mechanics and blade CTest targets pass
  together in 20.21 s. Nine Workshop-tab and two private-carrying cases pass.
  Twelve API documentation checks pass; the final new HTTP/browser run is 7.958 s.
  Source registration is 287/287. Logs and reviewed screenshot are ignored
  `build/resource-flow/condition-*` artifacts.

## Boundaries and next acceptance

Ordinary tool use does not yet accumulate fatigue or blunt an edge. Not every
dent implies lost load capacity. Connectivity describes retained matter, so
removing damaged cells can change its denominator; it is not a monotonic lifetime
health variable. Thermal softening can recover on cooling according to the
existing law, while char, consumption and severed bonds retain their actual
history. Joint damage is not aggregated into this body index. Exact rigid
equipment has no internal damage model. Queries add no work, impulse, mass or
energy; neither these tests nor the existing blade/thermal checks prove full
pipeline conservation or material realism.

Next implement a supported repair process with matching material and energy
receipts, native geometry/topology admission, retained old revision, collision
checks, and atomic save/failure/retry/restart behavior. A repair must identify
whether it replaces a component, remakes a part, or restores a supported
constitutive state, and account for removed matter, work and delay. It must not
reset severed bonds or history for free. Then exercise actual damage → carried
Lab → paid repair → native use through the ordinary browser, including
glass/oak/iron limitations. Item 11 and the full fourteen-item goal remain open.

## Bounded native and HTTP read

`LiveWorld::conditionJson(names)` is exposed through the native runner and
Python live-session adapter. Authenticated `POST /api/live/act` accepts:

```json
{"session":"current-live-session","op":"condition","names":["field pick"]}
```

Use the current world and player headers as for other named-world calls. Actor
identity comes from the token. Supply 1–64 unique nonempty names of at most
160 UTF-8 bytes each. The reply's `condition` contains schema
`banjo.body-condition.v1`, native `time_s`, `bodies`, the index `basis`, and
`fatigue_supported:false` / `repair_supported:false`. Each row includes `name`,
`state`, nullable `fraction`, `bonds`, `broken_bonds`, `damaged_bonds`, nullable
`connections_fraction` / `thermal_fraction`; existing bodies add material,
mechanical model, source parts, parked/fragment flags, dent mm and thermal law.
One bond traversal serves each batch. No new C ABI or MCP tool is claimed.
