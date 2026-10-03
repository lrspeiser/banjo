# Exposed layers and peer terrain delivery — October 3, 2026

Verification base: `302c662` on GitHub main plus the outgoing host, viewer and
test changes. Native sources, material laws and MSVC Release binaries are
unchanged. Publication is recorded after the verified implementation commit.

## Problems and changes

The renderer identifies the top retained native run. The coarse contact
classification instead calls a sand film below 2 cm soil, while stripping
still removes that sand. Gathering candidates now use the actual top run,
including proportional loose sand/soil mixtures and possible underlying soil.
Rock/clay/ore above soil remains refused. Candidates promise no yield or
quantity and introduce no new harvesting capability.

Native dirty terrain rectangles are consumed by any reply, including tools
and the unattended clock. An observer could receive updated bodies but never
the excavation consumed by another caller. The host now invalidates one
bounded geometry snapshot from every current-session native reply. Each view
acknowledges a session/revision only after applying geometry. Missing or stale
acknowledgements receive current native terrain; unchanged acknowledgements
need no geometry. Session replacement invalidates the snapshot. The cache
excludes carried accounts; normal personalization adds only that caller's load.
Client acknowledgements cannot edit terrain or advance native time.

Capture takes the native Live/Session locks before the snapshot lock, matching
listener order. A forced concurrent-listener test checks that capture and a
native reply complete without deadlock. Matching-grid catchup reuses the
existing mesh, water and exploration visibility. Packed runs advance through
the packet once instead of rescanning earlier columns for every cell.

## Verification

Windows, Python 3.13, Node 22.18.0, native engine/library from
`build/agent-object-strike/Release`; generated terrain cells 25 cm, paid pick
cells 50 mm, native dt 1/240 s. No tolerance was loosened.

```powershell
cmake -S . -B build/agent-object-strike -DBANJO_BUILD_LAB=OFF
ctest --test-dir build/agent-object-strike -C Release -R '^banjo_(terrain_material|material_delivery|material_layer)_tests$' --output-on-failure
# BANJO_LIVE_ENGINE=.../Release/banjo_live_world_run.exe
# BANJO_LIBRARY=.../Release/banjo.dll
# BANJO_BUILD_DIR=.../Release
python tests/world_hub_tests.py NamedWorlds.test_generated_worlds_are_isolated_and_joinable NamedWorlds.test_each_guest_has_an_avatar_and_inventory NamedWorlds.test_solar_energy_market_is_personal_and_durable -v
python tests/private_ground_tests.py PrivateGround.test_authenticated_storage_recovery_ownership_failures_and_full_restart PrivateGround.test_independent_capacity_deposit_spoof_refusal_and_restart -v
python scripts/check-source-registration.py
git diff --check
```

- Three focused CTests pass: six Node material/viewer cases, five candidate
  boundaries, three delivery/acknowledgement/concurrency cases and one actual
  native layered journey (15 individual checks). Final CTest run: 18.63 s.
- The journey gathers finite wood, funds/manufactures a personal 22-cell,
  1.925 kg oak pick, equips it, then repeatedly uses the ordinary tool endpoint.
  Terrain seed 7, goods seed 851269742; other machine programs are explicitly
  switched off through their ordinary controls to isolate extraction. Each
  stroke checks actual private sand/soil deltas, receipt mass within the
  existing 5e-5 kg bound, and an independently authenticated peer's received
  top run and column height (packed float32 height within 1e-6 m of survey).
  It crosses the thin-film boundary, exposes soil, collects soil, Stores the
  load, and retains exact surveys, packed geometry and private lots through a
  complete server restart. The peer receives no material and ledger ore
  reserves remain unchanged.
- An observed browser-fixture run took 13 actual strokes. Stored sand was
  22.4279628734 kg and soil 3.39880234188 kg; maximum receipt/delta residual
  4.85193e-6 kg. Summed reported ground work was 119.92484 J, with first/last
  contact records at native 26.39167/36.85 s. These are local extraction work
  and receiving checks, not full-world momentum/energy conservation. Normal
  CTest timings and quantities vary with ordinary host stepping; the gates
  compare the actual receipts and native state, not fixed cosmetic outcomes.
- Three native named-world checks and two private-ground storage/recovery/
  capacity checks pass. Ten guidance checks passed against the outgoing host
  changes. The named-world Market regression was updated from the obsolete
  mandatory stool/purchase chapter to the current optional-purchase personal
  pick opening; banking, scarcity, private credit and exact restart assertions
  remain. This checkpoint adds no material constitutive law; existing matched
  glass/oak/iron qualification boundaries are unchanged.
- Actual in-app browser observation joins a third, empty player before the
  native fixture digs. Its view changes from tan sand to brown exposed soil
  without reload; ordinary aiming shows **Soil / Surface** and a soil thumbnail.
  The observer's load remains 0/80 kg and its skill remains unearned. Zero
  captured browser errors. The digging actor is an HTTP/native fixture, not a
  claimed complete human or live-model opening. Screenshots and reports are
  ignored under `build/material-readability/peer-before-sand.png`,
  `peer-after-soil.png`, `layer-acceptance.json` and `peer-frame-trace.jsonl`.
- The observer trace covers 59 overlapping reporting windows and 13,899
  reported frames; window p95 frame time is at most 17.6 ms, worst frame 42.7 ms,
  worst step round trip 590.1 ms. Reports are sampled rolling windows, not a
  unique-frame total or controlled throughput benchmark. Installed host:
  Intel Core Ultra 9 285K / RTX 5090 plus virtual display; actual browser GPU
  selection was not established. Day/night recognition and other hardware
  remain unqualified.
- Registration: 297/297 sources, 10 CMake files, zero exclusions. Python
  compilation, viewer syntax and changed-file whitespace checks pass.

## Test scope and retained failures

An overly broad named-world selection reached the legacy Chrome menu test;
it expected its named menu creation before the plain `/world` automatic entry
created `New world`. The same automatic-entry source and stale test are present
on verification base `302c662`; neither file's menu behavior changes here. This
legacy browser gate remains unqualified and is not counted as passing. Further
browser verification used the in-app browser. A broad private-ground CTest
also included legacy browser cases and was stopped; only the explicit native
cases above and the focused new CTests count toward this checkpoint.

Development test failures also exposed an old session after Store and an
independently running ore rover. The fixture now follows the returned session
and explicitly powers off those programs. Its peer assertion checks the
normal personalized response's own zero load, rather than incorrectly
rejecting the existence of a carried field. The original missing peer terrain
was a real implementation failure; native and ordinary-browser evidence now
exercise its repair.

## Remaining full scope

Current catchup sends one full native geometry packet, approximately 620,584–
620,592 JSON bytes in the observed journey, after edits. Existing trace reply
sizes measure native replies before this host attachment and undercount these
packets. Unchanged acknowledged frames avoid the geometry, and only one
snapshot is retained per world; this is not a many-player bandwidth/scaling
qualification. A bounded chunk/delta protocol needs measured load evidence
before a multiplayer scale claim.

Material recognition at night, finer/stepped render comparisons and broader
hardware acceptance remain open. Finish the fresh human wood → paid pick →
use journey and wider source/processor/empty-energy/custom-design/live-model
guidance acceptance. Additional R4 pits, shores, grades, obstacles and recovery
families remain beyond the two qualified rover maps. R5 still requires native
human/AI avatar contact, buoyancy/current/drag/reactions and cargo mass/inertia,
container geometry and physical transfers. R3 repair remains owner-paused.
The [full readable-world scope](readable-world-plan.md) stays active.
