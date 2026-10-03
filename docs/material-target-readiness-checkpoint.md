# Material target and tool readiness — October 3, 2026

Implemented on main base `63e41bd7284e7a1e649e62793465d9023fed89a7`,
Windows x64. This checkpoint improves material/action feedback and its freshness.
It does not change native terrain geometry, resolution, material laws or tool
strength. The complete readable-world/progression/physical-behavior goal remains
active; R3 remains owner-paused.

Implementation **`13de170d8b90429d053da23b6bb6ece02437b290`** is published
on GitHub main. The matched local 8777 preview serves this implementation;
the older user preview processes have not been restarted.

## Changed behavior

- World places **Target**, the next action, the committed action result and held
  tool skill ahead of conversation. Keyboard/help rows and the full native action
  report remain available through closed disclosure controls.
- Target separates the actual exposed surface from possible tool yields. It shows
  material thumbnails, Tool / Yield and one current action. A ledger deposit still
  identifies its supported mining-rover route; it does not become pickaxe ore.
- The host derives compact feedback from the same tool resolution used by actual
  actions. Built-in and authored tool profiles share the path. Full load, missing
  working point, unsupported gathering, missing tool and reach refusals have
  explicit actions. Native contact admission remains separate from supported
  gathering yield; previews cannot grant material, money or skill evidence.
- Client observations are bound to the exact terrain column or object, current
  exposed layer/column geometry, sight point and observer pose. Crossing a cell
  boundary, changing layers or moving more than 3 cm invalidates the displayed
  readiness. Requests refresh at most every 200 ms while moving and every 1.5 s
  when stationary. In-flight stale answers are discarded. Actual use still checks
  the native sight line and readiness again.
- Successful collection presents the positive measured mass from a closed native
  receipt. It never derives that mass from preview candidates or guessed density.
  The original engine description remains under **Action details**.

These are host/presentation changes. The client observation metadata is not an
authorization credential, physical state or source receipt.

## Verification

Separate existing build: `build/agent-native-avatar`, Visual Studio 17 2022,
MSVC 19.44.35228, Release, CPU reference, `BANJO_BUILD_LAB=OFF`.
`banjo_platform_cli` was compiled for the fresh preview; the existing native live
engine contains the published actor foundation `8d417b89bd4f40d675243757ec39af34d2e84bc7`.
No C++ source or native law changed here.

```powershell
python scripts/check-source-registration.py
node --check playground/world.js
node --check playground/tools.js
ctest --test-dir build/agent-native-avatar -C Release --output-on-failure -R '^(banjo_tool_use_tests|banjo_terrain_material_tests|banjo_material_delivery_tests|banjo_material_layer_tests)$'
git diff --check
```

Four registered suites pass **51 checks**: nine material presentation cases,
eight candidate/delivery cases, 33 tool-use cases and one real native
HTTP/private-storage/peer/full-process-restart journey. Source registration is
298/298, with no exclusions. Tool-use cases use stand-ins to exercise the host
contract; they are not new physical qualification.

The native integration strips a real sand layer to soil and checks that preview
materials match the currently exposed run. Closed native yields agree with the
private Inventory deltas under the unchanged 5e-5 kg tolerance. The peer has no
private load but sees matching shared terrain. Store and complete server/native
process reopening retain ownership, layer geometry and balances. No tolerance
or physics assertion was relaxed.

## Ordinary browser observation

A fresh isolated provider-disabled server on 8777 created world
`afa3ec3ff70c47ed87f5ff9641a8dfee` through the ordinary UI. Its wrapper explicitly
disables model configuration before creating the playground; setting an empty
environment key alone would fall back to the repository's local configuration.
Existing preview servers and their worlds were left running.

The browser picked up the existing starter Field pick, aimed at dry exposed sand
and used the normal Target action. This does not qualify making a personal tool
or finishing the opening progression.

| Observation | Actual result |
|---|---|
| No tool | Sand surface, no promised yield, Equip tool |
| In range | Sand/Soil possible-yield thumbnails and native Dig action |
| First ordinary dig | Native 2.12474 kg sand; UI 2.12 kg; gathering skill Learned |
| Reload, then another ordinary dig | Native 18.43902 kg sand; concise UI 18.44 kg; personal sand balance displayed 20.56 kg |
| Expanded action report | Original native volume, depth, speed, work and force report retained |
| Distant source | At native-reported 10.5 m, Move closer with no Dig button; limestone deposit shown separately as Mining rover |
| JavaScript error log | Empty at the end of the observed flow |

Actual screenshots are local ignored artifacts in
`build/material-target-preview/{ready,collected,out-of-reach}.jpg`; hashes and
the focused CTest log hash are recorded in the
[evidence file](evidence/material-target-readiness-checkpoint.json).
Browser reload retention and the independent complete-process-restart test are
different observations. Dig mass/speed values above are receipts, not a tool
strength calibration, performance benchmark or full conservation audit.

## Remaining acceptance

- Compare current surfaced terrain with stepped material cells using matching
  native collision geometry. Smaller columns and improved night recognition
  remain unmeasured proposals; this checkpoint adds no voxel-resolution claim.
- Finish useful opening/supply coverage, compact solar entry and fresh human/model
  completion. The observed starter pick is not evidence for that full journey.
- Audit readiness and next actions across every tab/chat; this tool target slice
  does not close the entire unified-guidance acceptance.
- Native walking/swimming and authenticated human/AI binding, physical cargo,
  wider hauling families and complete work/momentum/energy accounting remain open.
- Older already-running Python previews need a matching backend restart to serve
  the new feedback field. The isolated 8777 preview has the matched host/assets;
  no claim is made that the user's older 8771 process was upgraded.
