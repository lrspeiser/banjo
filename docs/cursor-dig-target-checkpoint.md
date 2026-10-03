# Clicked ground and dig readiness — October 3, 2026

Based on main `197f39c4`. The owner observed that selecting one ground square
dug somewhere else. Hover picking used the cursor projection, but actual tool
use cast along camera forward. The asynchronous tap scheduler also discarded
the original click direction. Sidebar focus cleared the cursor before Dig.

## Implemented

- World captures pointer-down coordinates before using the held tool. Tool
  actions share World's cursor projection, including zoom and locked-pointer
  centre aiming. Each explicit tap retains its ray through the bounded,
  sequential queue; moving the cursor before the pending stroke finishes cannot
  redirect that tap. Held repeats sample the current cursor ray. Stop/refusal
  discards queued targets. Sidebar Dig retains its displayed point and object.
- Native pick still finds the actual current surface along the captured ray;
  actual use checks the current observer and ordinary native reach/readiness.
  No client preview grants yield or changes tool work or terrain resistance.
- The existing ground-square outline is green only for fresh supported readiness,
  red for refusal and amber while checking/working. A missing tool is neutral.
  The same observation/cell/material/observer checks feed the sidebar. Distant
  visible targets retain their outline within the existing 40 m picking range.
  Old hover replies are rejected after a changed ray or observer; pointer movement
  immediately hides the old outline until the new pick arrives.

The outline identifies the intended target cell. Native tool geometry/contact
can affect neighboring cells; it is not a promise of one isolated voxel or a
guarantee of successful penetration. Generic authored tools share this path.
Native sources, binaries, physics laws, material tolerances and resolution are
unchanged. This fixes the targeting prerequisite for construction preparation;
the complete preparation planner and saved construction steps remain unfinished.

## Verification

Windows 11, Python 3.13, Node 22.18.0, VS17 x64 Release CPU native reference in
`build/agent-column-terrain`, Lab off. CMake reconfigured to register the new
client suite. Four registered suites pass, 51 checks, 23.74 s total:

- Terrain/material presentation: 16 checks, including fresh-ready green and
  changed cell/layer/observer rejection, refusal red and checking amber.
- Tool client: one regression exercises the actual tools module with controlled
  API/timers, off-centre rays, pending sequential taps, point-copying sidebar
  actions, current-ray held repeats and Stop. It does not simulate native contact.
- Tool host: 33 existing resolution/action/reach/working-point checks.
- Native layers: one ordinary gathering/private storage/peer/full process restart
  journey, unchanged 5e-5 kg receipt tolerance and 1/240 s native stepping.

```powershell
cmake -S . -B build/agent-column-terrain -DBANJO_BUILD_LAB=OFF
ctest --test-dir build/agent-column-terrain -C Release -R '^banjo_(tool_target_client|terrain_material|tool_use|material_layer)_tests$' --output-on-failure
python scripts/check-source-registration.py
```

Source registration passes 298/298, no omissions. Changed JS syntax and diff
whitespace pass. These are host/UI and existing native regressions, not new
constitutive, conservation, material-strength or cross-platform qualification.

The separate existing test world on 8779 used normal Find tool/E controls. An
off-centre click collected 1.51 kg sand and showed a green square. Sidebar Dig
collected another 1.43 kg. A too-close click refused at 1.0 m; a distant click
refused at 3.1 m, showed Move closer and a red square without changing the load.
The user's world and inventory were not touched. Local screenshot artifacts:
`build/construction-preview/dig-target-green.png` and `dig-target-red.png`.

Next: highlighted paid pad preparation and full saved construction steps, then
functional supports/mounting and learned skills. Wider terrain/night/usability
acceptance and the two-second model p95 remain open; separately paused R3 stays
paused. Implementation and verification are published on GitHub main as
`a68a082f`. Port 8779 serves the updated assets; existing browser pages need a
refresh to load them. The native backend/build is unchanged.
