# Touch pickup gesture — October 6, 2026

## Observed client defect and shared repair

At source baseline main `9bf9f570`, a single 5-by-4 CSS pixel finger movement
turned the camera and marked a tap as a drag, suppressing pickup. Conversely,
a deliberate 16-pixel drag in two-pixel increments never became a drag, because
the old threshold compared each event only. The stage also lacked a cancellation
handler and did not distinguish the active pointer from another finger.
Three new client regressions fail on that baseline and pass after repair.

Touch now admits 12 CSS pixels of displacement from the original press before
looking begins. Taps retain the original press ray; deliberate cumulative drags
look without picking up. The active pointer owns its gesture. Other stage fingers
cannot replace, move or release it; cancellation stops use and clears the gesture
without pickup. The independent movement pad retains its own pointer handling.
Pointer release/cancellation decisions are included in the bounded local trace.
The shared path applies to all items, without Field pick name checks.

## Verification and boundaries

Windows, Python 3.13, Chrome touch emulation and unchanged Release native binaries
from `build/local-cell-tools/Release`. Three registered CTest suites pass in
55.12 seconds: 15 client cases, five World navigation/browser cases and 26 trace
cases. The native-body touch journey now includes 5-by-4 pixel finger movement
on both far and near pickup, checks the real reach refusal, retained whole-tool
native hand, reload and closed chat. Keyboard input still performs that journey's
walk away/back; this does not qualify simultaneous touch walking and pickup on
a physical phone. JavaScript syntax and source registration pass (305/305).

The owner reports a phone failure; their phone URL and deployed revision are
not yet established. GitHub main contains the preceding changes, but publication
does not establish that a phone deployment updated. The local port-18890 demo
was found stopped during this audit, with its last interaction log at
2026-10-06 20:41:43 UTC. Its saved rooms are preserved.

This is an input repair, not a change to native pickup reach or material laws.
Native grip loss during tool preparation remains open as recorded in
[gameplay diagnostics](gameplay-interaction-trace-checkpoint.md). Physical-phone
acceptance, native digging readiness/speed and the full regression suite remain
open. Exact publication is recorded in Git history.
