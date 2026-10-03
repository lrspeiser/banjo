# Generic tool HUD and deliberate target feedback — October 3, 2026

Based on main `9681fbd2`. The owner reported red targets near their feet,
distracting held meshes, tiny delayed collection packets and a crowded right
rail. This is a host/input/presentation checkpoint; native binaries, materials,
constitutive laws, resistance, conservation tolerances and resolution are unchanged.

## Implemented

- Default contact reach is 0.3–2 m, within the existing bounded authoring schema.
  The old 1.15 m minimum came from full swings and unnecessarily blocked close
  contact. Explicit authored bounds are retained; explicit legacy swing keeps
  1.15–2 m. Wet/unsupported ground, overload, disconnected points and distant
  targets still require native refusal. Fresh supported ground has a bright
  green filled surface marker; red means blocked and amber checking/working.
  The marker follows the sampled terrain boundary and is not an excavation promise.
- Left/right hand thumbnails sit at the lower screen edges. Hover or keyboard
  focus reveals Stow/Place/Lab. Bag slots and ordinary Inventory remain the
  authority. First-person tool meshes and their selected outline are hidden
  only for that render; native collision, peer meshes and physics are retained.
- Hover does not move or rotate a contact tool. After use, an actual native
  resting grip is retained and translated with player movement. The renderer
  cannot prescribe the physical tool pose. Native preparation/contact can still
  take longer for a newly equipped or obstructed tool than established taps.
- World navigation is a compact bottom bar. Details opens the optional right
  rail; `/` or Chat opens its chat view, Esc closes chat. The full Workshop tabs
  are unchanged. A short action toast keeps refusals/results visible in World.
- Target thumbnails/actions appear in a fixed upper-right card after 1.5 seconds of dwell.
  The October 3 placement repair keeps the cursor and targeted ground unobscured;
  opening the right rail offsets the card alongside it. Narrow screens bound its
  width and retain scrolling. No target, action, native law or hover-delay change.
  Changed target, >12 px drift, camera translation, cursor mode or leaving reset
  the dwell. Readiness refresh alone does not. Moving into a popover stops edge
  looking; moving out dismisses it. Current native checks remain authoritative.
- A short contact pulse requires a confirmed native contact. Closed positive
  sand/soil receipts create 16 px material packets over 1.25 seconds, with a
  brief measured mass label, toward the live load counter. Up to 12 packets per
  batch/48 at once are illustrative UI, not physical debris or mass-bearing
  fragments. Reduced motion omits flying packets. Inventory is never incremented
  by an animation, preview, LLM response or authored material display name.
- The authenticated player's active-use receipts are retained transiently, up to
  64 meetings, and included in that player's step responses. This lets closed
  collection animate before the final tool response even when the world clock
  consumed its native packet. The client deduplicates point/time identities;
  peers cannot retrieve another player's feedback. The buffer is removed when
  the use ends. Final responses also include closed meetings, so totals cover
  the attempt rather than only its last meeting. An open excavation can still
  render before its receipt closes; this is not predicted yield or delayed physics.
- The shared LLM authoring prompt describes these controls and bounded reach.
  New authored tools with admitted native working points use the same feedback;
  no tool-specific swing animation or extra LLM call is needed for digging.

## Verification

Upper-right placement repair: Windows browser verification in the separate
`bd899fb4d1aa4e029bb88b6ace0194ab` world shows Sand details clear of the cursor
and successful expansion of Nearby materials. The owner world is unchanged.
The two registered terrain/material and tool-client suites pass (28 checks),
JS syntax and whitespace checks pass, and source registration remains 298/298.
Screenshot: `build/construction-preview/target-details-top-right.png` (ignored).
This is layout verification only; no new physics qualification.

Windows 11, Python 3.13, Node 22.18, VS17 x64 MSVC 19.44 Release CPU reference,
existing `build/agent-column-terrain`, Lab off. Six registered focused suites:

- Terrain/material presentation: 19 checks including dwell reset, stale readiness,
  native-only particles, complete closed-meeting totals and existing column geometry.
- Real tool client: four checks for clicked/queued/held targets, idle/native-rest
  pose behavior, render restoration and streaming/final-response deduplication.
- Tool host: 35 checks, including private active-use feedback, close contact,
  preserved explicit/legacy limits and existing refused/unsupported paths.
- Four native paid-pick journeys: ordinary and 0.45 m contact on smooth and column
  terrain, real sand → soil, private Store, peer geometry/load isolation and complete
  restart. Existing 5e-5 kg receipt tolerance and 1/240 s native steps are unchanged.

```powershell
ctest --test-dir build/agent-column-terrain -C Release -R '^banjo_(tool_use|close_material_layer|material_layer|column_material_layer|terrain_material|tool_target_client)_tests$' --output-on-failure
python scripts/check-source-registration.py
```

Final suite totals/publication are recorded below. Source registration remains
298/298, no omissions. JS syntax, Python compile, changed-scope whitespace and
local documentation links are checked. No new material constitutive, full
pipeline conservation, native avatar/cargo or cross-platform claim is made.

The ordinary Cua browser uses a separate retained test world on 8779. It shows
hand icons, the bottom bar, green target/delayed popover and collection while the
popover still says Using tool. One measured collection adds 1.65 kg Soil, matching
54.2933 → 55.9442 kg total load. Slash opens the right AI/player audience selector;
Esc hides it. Day and night targets were observed. Screenshots are local ignored
artifacts in `build/construction-preview/tool-hud.png`, `tool-yield-hud.png` and `tool-chat-hud.png`.
The owner's world/draft was read for diagnosis and not changed by the test.

## Existing broader test failure and remaining work

The broader `banjo_goal_chains_tests` probe fails the composed camp/table journey:
it still calls `/api/world/workshop/preview` in a funded generated room, which the
unchanged fabrication request gate rejects with HTTP 400 (create/change designs
in Lab, then fund and make at the workbench). Replaying the exact published
`9681fbd2` test reproduces that failure. It is an existing stale journey fixture,
not a contact-reach or HUD regression. Attempts to migrate it also exposed the
fixture's one-second charging assumption and stale supported placement preview.
Those trial changes were removed; no failed fixture changes are published here.
A full updated paid-table/process journey remains a separate verification repair;
this checkpoint does not claim the full goal suite passes.

Full construction preparation, saved project steps, supports/mounting/earned
skills, wider custom-tool and unaided human usability remain unfinished. The
prior R3 scope remains separately paused. Test the hover delay, packet readability
and hand/card placement with the owner before expanding this HUD to more surfaces.

## Final focused results

All six registered suites pass, 62 checks, 80.57 s total. Registration passes
298/298 with no omissions. All 2,050 local documentation links resolve. JS syntax and Python compilation pass. The broader
goal-suite failure above is not included in this passing total.

## Published checkpoint

Implementation and verification were committed and pushed by ordinary fast-forward
to GitHub main as `dcd94baee43c1a08b85377c033b3fb3daf7b42cc`. The matching
8779 preview is running from this checkout; screenshots remain local build
artifacts and no credentials or local world saves were committed. This subsequent
publication note changes documentation only.
