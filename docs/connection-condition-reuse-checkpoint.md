# Connection condition and paid replacement — October 2, 2026

## Implemented boundary

Native `condition` readings now include each selected part's assembly joints:
endpoints, kind, attachment state, declared capacities and retained failure
reason/load/capacity. They exclude poses and current reaction loads. Queries
change no physical state. Body bond/thermal fractions keep their existing
meaning: an intact handle and head can each read 100% internally while their
connection is separated. The shared World/Inventory/Lab panel shows
**Disconnected** without assigning a durability percentage to separation.

Lab replacement reviews include connection history in source/native hashes.
Failure after review refuses Start before spending; a new review retains the
failure in the accepted job's durable source record. Existing accepted jobs
remain replayable. Replacement creates a distinct paid product; it does not
heal, remove or refund the original.

Native parking now admits a failed fixing with no live constraint. Only the
currently connected group goes into the bag. The detached other end stays in
the world; the failed fixing remains in history across park, whole reopening
and unpark. Another player's bag stays inaccessible. Other unsupported parted
constraint kinds retain their refusal.

Shared tool readiness uses the actual native hand grip, including when it
differs from the authored grip or the working point is on another body. Point,
grip and body reads share one native instant. Distant pickup readiness uses a
bounded 2 m/s, 8 m/s² path with a 2 s native give-up horizon. The 35 mm point and
.98 direction gates, press/withdrawal paths, force/torque caps and material/contact
laws are unchanged. These are hand wishes, not imposed body poses or outcomes.

## Measurements and evidence

Windows x64 Release, Visual Studio 2022 / MSVC 19.44, CPU reference. Six
condition experiments reuse the [ordinary native strike fixture](object-strike-joints-checkpoint.md):
20 mm cells, 1/240 s, zero gravity, iron head/oak handle and identical 100 mm
glass/oak/iron targets. Failed target loads are 866.593666, 709.914379 and
875.610638 N against 200 N. Failed tool loads are 77.010033 N against 60 N in
all three comparisons. Target masses/density differences and prior work/energy
measurements remain in that checkpoint. The weak tool fails under acceleration
before target impact; this is not calibrated impact damage.

All constituent bond fractions remain 1 with zero broken bonds. One hundred
connection queries preserve an exact full snapshot; whole reopening preserves
failure records. Each tool-failure case parks/unparks the handle without moving
the detached head or restoring its working point, and refuses another player's
unpark. Existing cold three-body readings take 11.333 ms for 100 queries on this
run. No fatigue, abrasion, blunting, grain, plasticity, calibrated strength or
new constitutive law is added. Unclosed momentum/energy/reaction accounts remain
unclosed.

Authenticated HTTP tests at 20 mm and normal gravity repeat source failure,
review invalidation without spend, private carried condition, peer refusal and
server restart for glass/oak/iron targets. Actual Chrome Inventory displays
Disconnected without a meter. The object-Use browser can begin in sustained
contact after its carry clock reports the impact. Its gate now requires the
selected target's actual overload receipt above the unchanged 200 N capacity;
a fresh impact event is not a continuous reaction load. Native HTTP and the
paid replacement case still require fresh impact receipts. No physical tolerance
is relaxed.

The paid native test uses 40 mm, 1/240 s, normal gravity, a declared 60 N weak
source fixing and explicit finite test rack/battery supplies. It retains the
original 124.617111 N failure, spends 0.896 kg oak + 4.02944 kg iron and
492.544 J, and installs a 4.92544 kg mixed pick through the paid Make/placement
APIs. Ordinary Inventory pickup and shared object Use produce native target
contact and fixing separation. Signed hand work is separate from manufacturing
energy; no whole-pipeline conservation claim is made. Failed Start save restores
world/ledger; retry reserves once; whole reopening and accepted-request replay
retain source history and original failed fixing. This is replacement, not repair.

## Verification and publication

Separate build: `build/agent-object-strike`, `BANJO_BUILD_LAB=OFF`.
Seven rebuilt native suites pass in 66.16 s: LiveWorld, determinism, thermal
mechanics, hand stroke, ground work, body condition and fixing. Thirty-nine
host/browser controls checks pass in 39.035 s (tool use 29, body condition 2,
object strikes 3, quick tools 5). All ten native/Chrome fabrication remake
checks pass in 91.455 s, including paid mixed pickup/dig/restart, existing cut
source replacement and new failed-connection replacement/use. Source
registration remains 297/297. No full long capacity, native raylib window,
macOS/Linux or cross-GPU qualification is claimed.

Ignored evidence under `build/resource-flow/`: `connection-condition-build.log`,
`connection-condition-measurements.log`, `connection-condition-native-final.log`,
`connection-condition-controls-final.log`, `connection-remake-final.log`,
`connection-review-http.json` and `broken-replacement-native.json`.
Published implementation: `5621c171baa7859432ea4347c266bf62320e1a5a` on GitHub main,
based on `efaabbe3908cc114f9dc412470b4739f95f0b6c7`. The first push hit a
transport reset; a fetch and ordinary HTTP/1.1 fast-forward push succeeded.
The unchanged older preview runner/DLL/CLI hashes were rechecked; no preview
server was restarted or binary overwritten.

## Remaining R3 work

Host inventory still groups authored assemblies through failed joints. Item
identity, displayed parts/mass, bag root and ownership must reconcile to actual
separated groups; the native bag check does not close that host journey. The
new test's original source is an authored weak fixture, not a previously paid
manufactured product. Complete the fresh-world made-item damage → Lab review →
paid result → collection/equip/use journey with correct detached ownership,
peers, failure/retry and server restart. Integrate actual held source/target
internal damage and finite interface/clock/grip handling through the paired
boundary. Genuine repair and accumulated wear remain absent. R3 stays open;
existing preview servers are unchanged.
