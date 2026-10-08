# Live world impact diagnostics — October 8, 2026

## Implemented interface and transport

The browser glass slab **does not fracture**. It is one native rigid body. The
separate CPU material/contact experiments have not been connected to this world.
Earlier successful browser tests verified pickup and collision, not breakage.

`scripts/test-world.py` now records a correlated strike intention, native admission
preview, actual command outcome, sampled native swing observations and completed
report. Full projected snapshots surround an admitted strike. Player commands,
asynchronous pickup completions, native transport failures and interrupted strokes
also have archive entries. The native preview is eligibility, not a simulated
forecast or a guarantee of contact. The trace does not record every solver substep.

Append-only JSONL lives in `build/world-impact-logs/<world-id>.jsonl`, separately
from disposable worker files, and survives closing a sandbox. Session capabilities
and credentials are excluded. History retains all attempts within the existing
4,000-input session budget; downloads use bounded pages rather than the eight-event
display queue. Each archive is capped at 128 MiB. A cap or write failure produces an
explicit warning; it does not fabricate evidence or change the physics response.
There is no automatic cross-session browser history restore. Saved local archives
remain available after session expiry or a server restart.

The deliberate **Impact report** button opens a scrollable report with requested
and resolved points, admission versus confirmed contact, target/obstruction, head
contact speed, peak tip speed, rotation, target travel, signed hand work, duration
and observed body/mass changes. Previous strikes and session download are available.
Unavailable fracture prediction, broken bonds, contact impulse and whole-system
energy accounting are labelled unavailable or unqualified, not reported as zero.
Hand work is actuator work, not measured energy deposited in the glass.

## Measured verification

[Machine-readable evidence](evidence/material-lab/impact-diagnostics-results-20261008.json)
records binary fingerprints and actual matched/native/browser results. Base checkout
was `0589bf43b485a68af941ee9fa96938f3712a38fe`. The outgoing revision is recorded
by the containing Git commit and publication report. Windows, MSVC Release native
worker, Python 3.13 and the local Rust worker were used. No native law/binary was
changed or rebuilt for this diagnostics checkpoint. Separate unpublished CPU
integration edits are outside this checkpoint.

Matched experiment: iron pick, 1.2 × 0.1 × 1.2 m intact target, requested point
(0.3, 0.12, 0.3) m, native timestep 1/240 s. Tools initially use 20 mm cells;
targets are exact rigid primitives without a fracture-cell resolution. All glass,
oak and iron cases confirmed head contact, kept target/body identities and retained
observed total body mass. Expected catalog density gives approximately 360 kg glass,
100.8 kg oak and 1,133.28 kg iron slabs. No stiffness, grain, plasticity, cracks or
fracture realism is established by these collisions. Oak remains laboratory only.

- Registered gateway CTest: 13 groups passed, 93.22 s. Covers all four tool families,
  handle/head pickup, actual rigid/grain hits, retries, refusal, world isolation,
  report/native equality, persistence, history beyond eight events and archive errors.
- Registered input CTest: five groups passed; final direct run also passed all five.
- Actual-native Rust gateway regression: 17 groups passed, 26.66 s.
- Material recorder/host regression: ten groups passed, 12.82 s.
- Final matched diagnostic subset: two groups passed, including all three materials
  and 35 refused attempts with paged history and explicit archive/write failures.
- Source registration: 322/322; no intentionally unbuilt sources.
- Ordinary desktop browser: handle click confirmed grip; glass slab click confirmed
  1.620 m/s contact, 0.000 cm displayed travel and zero new bodies. The downloaded
  JSONL records match the corresponding prefix of the persistent archive. The
  browser download event observer timed out, but the actual downloaded file was
  found and its parsed records verified against the archive.
- 844 × 390 browser viewport: report and movement pad rectangles do not overlap;
  report closes, scrolls and leaves ordinary controls usable. This is not a physical
  phone qualification. Local screenshots are in `build/status-tests/impact-report-*`.

Mass sums and report equality are transport/observation checks. Full momentum,
angular momentum, external/support work, dissipation and energy conservation remain
unqualified here. The full regression suite was not run. Logging adds no physical
reaction or simulated crack, and does not reconstruct prior unlogged impacts.

## Still required

Finish the coupled force/contact accounting and sustained accuracy gates, then
connect the qualified material solver and physical constituent handoff to the live
world. Add actual bond/topology, contact impulse, reaction and energy records when
their production paths exist. The six sustained fracture gates, useful digging,
ordinary live fracture/debris and the full free-form world objective remain open.
