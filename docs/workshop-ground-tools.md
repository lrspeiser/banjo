# Workshop ground-tool declarations — September 30, 2026

Code `7b4a062` follows the [mixed-scene admission checkpoint](lattice-tools-with-equipment.md). The broader player progression goal remains active.

## Implemented authoring contract

`parameters.ground_tool` is a bounded declaration shared by ordinary Workshop candidates, saved assembly recipes and the model's new `define_ground_tool` tool. It locates one ground point and grip on existing components. Component-local coordinates are relative to the component centre before its rotation, in metres. Rotating or moving that component transforms its point or grip with it. Changing its size may invalidate the declaration and requires another check.

```json
{
  "schema": "banjo.workshop-ground-tool.v1",
  "point": {
    "component": "arm",
    "tip_local_m": [0, 0, -0.15],
    "direction_local": [0, 0, -1],
    "width_m": 0.05,
    "thickness_m": 0.05,
    "angle_deg": 30,
    "length_m": 0.2
  },
  "grip": {
    "component": "haft",
    "position_local_m": [-0.35, 0, 0]
  }
}
```

This example belongs to an 800 × 50 × 50 mm haft and 50 × 50 × 300 mm arm meeting face to face. It is not a declaration for every possible tool. The same contract works for other supported fixed lattice solids: names do not select a special result.

Native installation translates the component frames into the actual grid placement, adds the point to the new joined body and binds the existing `swing-and-lever` controls. It preserves each older point exactly. New points are checked against their declared tip, grip, direction, section, identity, actual body and sampled matter. The native probe checks matter behind the tip, outward pointing and a grip on actual sampled cells. Corrupt or unsupported mechanisms cannot be accepted merely by naming them.

Ground tools require a homogeneous, connected fixed lattice solid in the current installer. Exact rigid and articulated tool points are refused. The native ground model owns depth, resistance, work and removal; this metadata cannot prescribe those outcomes. It provides no motor, strength guarantee, chemistry, grain or new constitutive law. A wedge's declared section remains an authored model input, not a measured manufacturing certification.

The existing finite fabrication quote accepts these fixed lattice solids and refuses an articulated point before charging work. A deliberate primary-use program remains required by that process. The test recipe has an explicit **Study tool** inspection program; actual digging comes from the installed ground-tool profile, not from inspecting it. Inspection has not yet been wired to personal study evidence.

## Instructions for item-authoring LLMs

1. Inspect the selected design and identify existing components, their dimensions and mechanical models. For a new item, create real connected geometry through the component API first.
2. Use `define_ground_tool` for a supported digging point. Name the point and grip components. Put the tip on the actual end, pointing out of its matter, and the grip on the handle. Supply SI widths, thickness, angle and point length. The model tool uses the existing bounded swing/lever defaults; persisted declarations may contain the separately checked `use` settings from the interaction-profile contract.
3. Check again after moving, resizing, replacing or removing those components. Do not silently keep a tip or grip that no longer belongs to matter. The frame declaration survives saved-recipe reopening, but that is not a functional pass.
4. Verify geometry/grid coherence and native point admission in staging, then perform a supported action on actual ground. Report what the engine measured, including refusal, wet/rock regimes, breakage or no removal. Never invent a successful dig or treat a name as a capability.
5. Save a design only when requested through the normal save flow. Making it uses the existing inventory/energy gates. Prototype admission or an authoring fixture does not credit a player's goals or journal.

## Verification and measured boundaries

Windows 11, Python 3.13.5, MSVC Release CPU runner from `f819e81`; this checkpoint changes Python authoring/staging and registers its tests in CTest, not native laws, dt or tolerances. Guard remains 286/286 native sources registered, no exclusions.

- `banjo_workshop_ground_tools_tests`: **5 tests pass**, 2.95 seconds in the recorded CTest run. Missing/invalid fields, nonfinite numbers, boolean dimensions, nonexistent components and off-component points/grips are refused. Rotated component frames and saved recipe roundtrip pass. The model's tool updates the actual editable candidate.
- Identical 50 mm-grid geometry occupies **22 cells / 0.00275 m³**. Native masses: glass **6.875 kg**, oak **1.925 kg**, iron **21.6425 kg**. Each installs beside exact iron equipment, preserves point/body records through a later table append and whole native restart, and rejects corrupt staged records. This compares compilation and state, not three-material swinging performance.
- One actual oak fixture uses the existing bounded hand and `tool_use.run` at `dt=1/240 s` on dry soil. Recorded closed supported event: `broke out`, soil volume **0.02413815505857741 m³**, displayed mass **38.62105 kg**, measured tool/ground work **96.628 J**. Unrounded removed volume minus the carried-volume increase is **0 m³**, checked at `1e-12 m³`.
- The displayed mass is rounded by the existing native runner's `tidy()` to five decimal places, so its separate comparison allows only that serialization's half-unit, `5e-6 kg`. The source-volume test remains unrounded. No existing conservation tolerance is widened.
- Hand/use phases follow native results with a host stepping thread, not a prescribed successful trajectory. Scheduling changes phase boundaries, so later runs may remove different positive quantities. This is neither a bitwise timing nor a realtime performance claim. No external hand/gravity/full-world energy closure is claimed from the removal ledger.
- Existing regression checks: native Workshop installation **39**, Workshop chat **38**, construction **23**, installation boundary **20** pass. Chat tests include intentional provider/wrap-up failures and do not make live provider calls. The previously recorded comparative native stake energy checks remain applicable.

```powershell
cmake -S . -B build/agent-progression
ctest --test-dir build/agent-progression -C Release -R '^banjo_workshop_ground_tools_tests$' --output-on-failure
python scripts/check-source-registration.py
```

The CTest job sets `BANJO_GROUND_TOOL_TESTS=required` and the built native runner, so a missing runner cannot silently skip the native case. The physical trial uses defined fixture stock and native calls, not a named-world AI playthrough or a browser journey. No cross-platform or cross-GPU behavior is inferred.

## Next acceptance gates

Place a reachable grid-appropriate tool in generated worlds using this same Workshop contract, add an explicitly versioned matching design, and implement attributed durable study/use receipts. Then run the Camp → tool → measured gathering → useful surface → supported process chain through ordinary authenticated player controls. Skills must resolve the actual available examples/actions; AI needs broader actions and separate live-provider play. These gates are not closed by this compiler checkpoint.
