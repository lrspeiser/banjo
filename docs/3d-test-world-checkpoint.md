# Interactive 3D test world — October 7, 2026

## Implemented checkpoint

Open `http://127.0.0.1:18891/world.html`. This is an isolated, small 3D sandbox,
not the retained saved game and not another node/bond replay. Its initial world
is 3.2 × 3.2 m, with native 100 mm soil columns, an actual rigid avatar, a metal
tool stand, a configured joined tool and glass/iron comparison blocks.

The browser sends bounded intentions to the loopback host. A separate Rust
owner steps the actual native engine at 4 × 1/240 s per accepted batch; browser
polls never supply time or physical poses. The view draws native body poses and
the actual column heights, including side walls after excavation. Pickup stays
pending until physical grip confirmation. Tool completion displays measured
removed volume or the native refusal. There are no cosmetic debris particles,
precut fragments, animation substitutes or amplified cuts.

The New world menu selects pick/shovel/hoe/custom head geometry and iron, glass
or laboratory-only oak; oak is not added to playable-world defaults. WASD/arrows
move, dragging orbits, scrolling or +/− zooms. On small/landscape screens,
direction buttons sit above the footer, separate from the menu. Pointer pickup
and use target the actual clicked screen geometry, including touch pointers.
Ground preview uses the same actor-eye ray construction as use. Green means
native admission plus clear entry observation, **not a guaranteed stroke**.

## Authority and limits

- Loopback only, exact local Origin/Host, 1–1024-byte JSON requests and fixed
  asset/action allowlists. No LLM calls, arbitrary native operations, paths,
  clocks, snapshot injection, client-selected actor or host privileges.
- Two isolated sandbox sessions maximum. Each has one server-assigned actor,
  an owned worker/native child, bounded replies/events/input receipts and a
  90-second inactivity timeout. Closing a scene expires only that test world;
  it never resets a saved game. Forced shutdown targets only its process tree.
- Native geometry-only terrain projection excludes carried accounts and other
  private fields. Trusted-host observation uses no mutation receipt, revision,
  sequence or physical step; a 5,000-read Rust test protects this.
- Movement/standing renews the existing 250 ms native intention lease. These
  are actual typed inputs and consume the current in-memory receipt budget.
  At 4,000 sandbox inputs (or earlier native capacity refusal), use New world.
  This is a bounded laboratory host, not durable/public multiplayer hosting.
- Tool geometries are declared fixtures through the same generic native
  joint/grip/tool-point path. Product import/LLM authoring is not implemented
  in this host. The renderer supports the fixture primitive shapes; unsupported
  native shapes stop rendering rather than silently becoming fictional boxes.

## Measured verification on Windows

Native MSVC Release artifact SHA-256:
`9d709d66fb186438fdaba4f5ce0c3c773ab88bbca87d2dbc745a6a9cc92c72c4`.
Native laws/binary are unchanged by this checkpoint. Rust is rebuilt through
the named CMake target. The running host reports the native and Rust executable
fingerprints; these do not prove native source/artifact equivalence. Implementation
is based on main `93ef465e5cbe735a8d1e26eee7f98d7134bc7f1d`; published revision
is recorded in the companion evidence update.

Checks performed:

- 24 Rust tests, including free private observation and receipt preservation.
- 17 existing actual-native worker tests, including the 12 original first-use
  material/tool cases; all pass.
- Five new actual-native HTTP/Rust tests: full terrain geometry/privacy, scoped
  inputs/origin/idempotency/budgets, independent worlds/avatars/hands/movement,
  pickup/drop, and measured tool closure with actual geometry updates. These
  tests qualify transport/presentation: a real refused stroke is reported as
  a refusal, not accepted as useful-digging qualification.
- The new CTest `banjo_test_world_gateway_tests` runs all five tests: pass.
- Ten existing material-lab host/exporter tests, three Test Hub host groups,
  four material client contract groups, TypeScript build and new JS syntax: pass.
- Source registration: 315/315 compiled sources registered, zero exclusions.
- Ordinary browser: desktop pickup confirmed, soil cut reported 0.25 L,
  landscape 844 × 390 pickup/use reported 0.38 L, and Drop emptied the hand.
  Native cuts were rendered from returned heights. Virtual viewport checks do
  not certify a physical phone. Portrait layout and final installed host are
  verified in the companion evidence.

The matched fixture checks retain all four families × glass/oak/iron and one
shared timestep/resolution. Pick head geometry is 120 × 80 × 40 mm; measured
mass is 0.96 kg glass, 0.2688 kg oak, 3.02208 kg iron. The ratios follow the
existing 2,500/700/7,870 kg/m³ densities. Wider heads scale with actual volume;
the iron shovel head is 7.05152 kg, exposing how heavy these thick reference
tools are. No new stiffness, grain, plasticity, fracture or realism claim follows
from those names or masses.

## Open physics gates — not completed by this UI

Soil still uses the retained native excavation/reduction law. The new conservative
material-contact solver is **not connected to terrain**. This scene makes current
carry/contact/ground response inspectable; it does not qualify full-pipeline P/L/E
conservation, debris geometry/spin/collision/settling, rock excavation, useful
10-foot-hole speed, sustained digging, realistic organic materials or the rewrite.
Displayed hand/contact work and loosened volume are existing native measurements;
full sandbox conservation residuals are not established.

An exploratory stand-fixture sweep produced cuts in glass/oak and some iron
cases, but also an iron shovel out-of-reach refusal and an iron pick still
pending at the short observation deadline. A tool allowed to fall onto the soil
before pickup can subsequently fail preparation. These remain controller/fixture
defects, not cosmetic-animation problems. The existing strict gates remain
visible: three material-contact convergence failures and four iron same-column
repeat failures. Do not generalize first-stroke demonstrations to every position,
idle duration, tool material or repeated excavation.

Next: qualify carry acquisition/preparation after arbitrary resting poses;
close the repeat/controller and conservative contact gates; connect authoritative
material topology, mass/work/reactions and settled debris to terrain; then expand
this same 3D shell into world/gameplay and complete mobile input journeys. See
the W00–W17 rewrite backlog; this checkpoint closes only the missing 3D inspection
surface and a local Rust/browser transport slice.

## Reproduce

```powershell
cmake -S . -B build/local-cell-tools -DBANJO_BUILD_RUST_RUNTIME=ON
cmake --build build/local-cell-tools --config Release --target banjo_rust_runtime --parallel 4
ctest --test-dir build/local-cell-tools -C Release -R '^banjo_test_world_gateway_tests$' --output-on-failure
& 'C:/Program Files/nodejs/node.exe' client/node_modules/typescript/lib/tsc.js -p client/tsconfig.json
python scripts/material-lab.py --native build/local-cell-tools/Release/banjo_material_lab_record.exe --port 18891
```

Stop your owned sandbox host before rebuilding its running Rust executable on
Windows. The observed initial rebuild refusal was a Windows executable-in-use
lock; after owned shutdown the same CMake build passes. All new Python tests
require actual native/Rust artifacts and fail if unavailable. The Test Hub now
includes the sandbox integration check; strict failures are retained.
