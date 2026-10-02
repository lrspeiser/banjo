# Fast shared tool handling — October 1, 2026

Implementation verified on main's `953aef6` base, with changes present during testing. [Machine-readable evidence](evidence/quick-tools-checkpoint.json) records source and rebuilt engine/DLL hashes. Implementation **`df15b5955684066a3e8b28779af19bdb022247b6`** is published on GitHub main; pickup refinement **`6ebbf5053add2a098f74bdefb0071ad694c598c5`** is also published on main. Broader progression remains four verified requirements and ten partial.

## Player behavior

Ground tools use a short contact stroke by default: down, a small lateral working motion and withdrawal. Click or J uses the tool; hold repeats; right mouse stops repeat after the current native use. Explicit rapid taps enter a bounded three-tap queue. One request runs at a time. The requested cadence is 4 Hz; native completion, resistance and positioning determine the actual rate. There is no full revolution, mandatory wind-up or 700 ms repeat pause. Initial pickup carries the tool above terrain in its existing orientation. First Use performs safe alignment; pickup and idle positioning do not excavate (verified in Chrome). Initial positioning still moves the real bounded hand. A grounded horizontal tool is lifted, turned above terrain and lowered smoothly before its first contact.

Actual Chrome input measured **2.74 completed native uses/s**, nine uses during the held interval, **5/5 rapid taps**, at most one concurrent request and maximum native displayed rotation **5.26°** during established use. All held replies include closed native ground receipts. Right-click stops subsequent repeats. This is a Windows machine/terrain measurement, not a guaranteed rate for every mass or surface.

The native sight ray can filter the selected actor's own held body. This avoids a moving tool obscuring ground targeting or the former ray-marching workaround stepping through nearby terrain. Normal inspection still sees the held body; another player still sees it, and released bodies remain visible. Late ready-pose packets from the same actor cannot cancel a running tool stroke. Other actors continue to interact.

## Shared authoring contract

`mcp/interaction_profiles.py` owns `TOOL_USE_DEFAULTS`, validation and `TOOL_USE_SCHEMA`. World MCP recipes, interaction authoring and Workshop `define_ground_tool` expose that same schema. World and Lab model instructions describe short repeated use. `mcp/tool_gestures.py` supplies the same point-frame alignment and contact path to the live controller and native MCP trials. Saved profiles that omit the new fields inherit contact/4 Hz automatically. A tool's name does not select its motion or physics.

Authoring guidelines for the LLM:

- Declare the physical point and grip on admitted geometry. Omit `use` to inherit the standard controls.
- Use concise `label`/`past` feedback. `repeat: false` disables held repeat; `pry: false` omits lateral working motion and can loosen nothing.
- `cadence_hz` is a requested input rate within 1–8 Hz, never a yield or world-time multiplier. Native strokes must finish sequentially.
- Do not add spinning, a mandatory flourish, forced poses, resource grants, strength overrides, skill awards or a model call per press.
- `gesture: "swing"` retains the historical full-swing experiment only when explicitly requested. Angular swing/lever fields apply to that mode; bounded `swing.speed_m_s` drives both modes.
- Test real native work and report failures. Supported ground points do not imply calibrated axe cutting, farming, wet-soil or rock fracture laws.

## Native measurements and limits

Native hand, torque, ground resistance, material mass and learning persistence laws are unchanged. Contact targets are 60 mm clearance, 80 mm requested bite, 40 mm lateral travel, speed 4 m/s, requested acceleration 80 m/s² and 25 mm lead. These are bounded controller wishes; the body may lag or fail. No prescribed velocities, impulses, pose teleports or accelerated world time were added. A changed controller path changes work and yield; old swing measurements remain historical.

Matched glass/oak/iron experiments use the same joined 40 mm haft/arm, point, flat dry soil, dt=1/240 s and controller inputs. Actual native worlds are used for the ledger check, rather than the untouched originals of scratch trials:

| Material | Native tool mass | Point penetration | Ground work | Soil removed |
|---|---:|---:|---:|---:|
| Glass | 4.320 kg | 86.3 mm | 13.392 J | 0.0015119843 m³ |
| Oak | 1.2096 kg | 70.4 mm | 8.682 J | 0.0007632074 m³ |
| Iron | 13.59936 kg | 189.8 mm | 50.417 J | 0.0132831074 m³ |

Density-derived mass is retained (glass 2500, oak 700, iron 7870 kg/m³); different inertia changes the bounded hand's response. The catalog declares elastic moduli glass 70 GPa, oak 12 GPa and iron 211 GPa (iron > glass > oak); this ground-point experiment does not exercise or validate that stiffness ordering. These outcomes do not validate grain, plasticity or brittle fracture. Tools remain whole; the local removal-minus-carried-volume residual is **zero for each**, with unchanged native tool mass (1e-10 tolerance). The installed 50 mm oak tool additionally matches raw carried-volume change exactly and serialized mass within its existing 5e-6 kg rounding tolerance. No tolerance was relaxed. Ground work is reported, not a full-world momentum/energy conservation certificate. Calibration, wear, wet ground and fracture under a point remain unsupported.

## Verification and usable preview

Windows, Python 3.13, MSVC 19.44 Release, native CPU ABI 25 and actual Chrome E/J/right mouse input. Generated player scenes use 50 mm cells; comparative flat scenes use 40 mm. The native runner, shared library and live-world test target were rebuilt. A first build command named a nonexistent `banjo_shared` target; the correct `banjo_c` target was then built successfully. An initial installed-tool account failure exposed incidental contact during positioning and was fixed with safe lift/turn/lower handling before publication.

- Quick-tool suite **5/5**: shared authoring/migration, invalid overrides, overlapping-use refusal, matched material/native accounts and actual held/tapped/stopped browser flow. Registered in CI with required native engines and Chrome.
- Tool handling **20/20**, Workshop tool authoring/installation **7/7**, MCP ground work **24/24**, knowledge **48/48**, API documentation **12/12**.
- Native two-map personal inventory/use/save-failure/restart journey **1/1**; Chrome progress/achievement/fade/repeat/reload/Skills journey **1/1**. Skill credit still requires authentic durable personal native evidence.
- Native live-world CTest **1/1**, including own-held-ray, peer and released-body checks; source registration **287/287**, diff and changed-document links pass.
- Refreshed [local preview](http://127.0.0.1:8770/world) retains the earlier ten-body world and passes fresh empty paid-workbench, component thumbnails, E pickup, mini Inventory and contextual skill card with no JavaScript exceptions. This is a local preview, not a production deployment.

Next: qualify contact use on damaged paid tools and broader slopes/target changes, then extend native action contracts to additional supported tool families. The complete tech tree and all-world conservation gates remain open.
