# Native player pickup reach — October 6, 2026

## Reproduction and implementation

On the owner's saved demo world, clicking the Field pick did take the joined
tool up, then the next native step released it. The saved player's shoulder
was approximately 1.99 m from the actual handle grip, outside the engine's
existing 1.8 m arm boundary. Inventory acknowledged success without checking
that boundary. Previous click tests used a fixed fly camera and could not
detect this physical-player failure.

The shared Inventory world-to-hand path now checks the authenticated native
player's actual position and rotated shoulder offset against the actual
functional grip before committing the record or calling wield. An unreachable
grip returns “Move closer to pick this up” in the ordinary World action toast;
the hand and inventory are unchanged. This applies to every declared product
and joined assembly using this path, without switching on tool names.
The native arm limit, bounded hand forces, collisions and reaction laws remain
unchanged. There is no teleport, automatic avatar approach or reach exemption.

Screen rays refresh the camera transform before casting. Native eye following
and guided look changes can otherwise leave the transform from the previous
render while the press uses a newer origin.

## Regression coverage

The registered `banjo_world_navigation_tests` now includes desktop handle and
landscape touch head journeys using a live generated world and the default
native player. They walk away using actual keyboard input, assert the far
pickup is refused with a visible notice and empty native/UI hands, walk back,
click the rendered constituent, then assert the whole tool remains equipped
for two seconds and survives reload. No fly observer, paused simulation or
tool relocation is used for these new cases. Before the admission change, the
new far-pickup assertion failed because Inventory returned `ok: true`.

Evidence is generated under `build/resource-flow/native-body-pickup*.json`
and `.png`; the tests remain part of CTest, not an unregistered ad hoc source.
Environment: Windows, Python 3.13, Chrome desktop/touch emulation, unchanged
Release native binaries from `build/local-cell-tools/Release`. Source baseline
is main `43d18416`; publication is recorded in Git history.

Verified outgoing scope:

- Four registered CTest suites pass in 170.05 s: five World navigation cases,
  native walk, Workshop ground tools (retaining glass/oak/iron comparisons),
  and all four paid tool-family journeys.
- All 19 Inventory room cases pass against the same Release build with
  `BANJO_BUILD_DIR=build/local-cell-tools/Release`. An initial ad hoc run used
  the older default integration CLI and failed two unsupported-op checks;
  selecting the current build resolves those environment mismatches.
- JavaScript syntax, changed-file whitespace and source registration pass:
  305 of 305 C++ sources remain registered.

[Desktop native-hand observation](evidence/native-pickup/native-body-pickup.json)
and [touch native-hand observation](evidence/native-pickup/native-body-pickup-touch.json)
retain real actor/body/hand results without player credentials.

This checkpoint changes host admission and client picking, not material laws.
It does not qualify physical-phone behavior, crouching/reaching biomechanics,
the full regression suite, constitutive excavation, tool wear or fast digging.
The broader glass/oak/iron physics and conservation limitations remain those
recorded in the mechanics scorecard.

## Published demo verification

Implementation and scoped checks are on main `3a2d5d6f`. The port-18890 demo
was stopped with Ctrl+C, its saved rooms copied to
`C:/play/backups/native-pickup-3a2d5d6f`, updated to that revision and restarted
with unchanged native binaries. Through the owner's real in-app browser,
Menu → New game created `d36ec8d4d52d49be9906973033b000a5` (Fresh pickup test).
Clicking the visible pick equipped Field pick in the right hand, retained it
across later native steps and left chat closed. The previous world remains
available in the Menu. The hand screenshot is retained locally at
`build/resource-flow/fresh-world-pick-held.jpg`.
