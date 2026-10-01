# Generated return hauling — October 1

## Implemented

The [first-haul checkpoint](generated-rover-hauling.md) could stop on its
excavated return approach. A saved native replay found a valid outward loop,
but the 1,024-query local search exhausted its observations first. The search
now permits at most 4,096 terrain queries, retaining its 6 m horizon, 0.5 m
cells, actual occupied geometry and native ground/water checks. A route with
heading states can revisit its origin; smoothing now excludes destinations
inside the native arrival radius so that it cannot erase a required loop by
asking the rover to stop where it already stands.

Actual motion beyond the 0.65 m allowance around an issued segment requests
native braking and replans after settling. It does not continue the stale
command for a minute. A blocked request waits for actual speed at most
0.05 m/s and yaw rate at most 3 degrees/s before issuing a new route.

When a forward route fails, a rover with two clear rear ground probes can
request a short retreat. The planner samples a full metre of dry footprint
and rear-probe clearance at 0.25 m intervals; the command requests only 0.5 m,
leaving braking room. Actual travelled distance, a rear hazard, a 15 degree
heading change or command expiry ends reversing. Real brakes settle it before
the same destination is replanned. Three unsuccessful retreats exhaust the
existing retry allowance and hold for recovery/resume. Step, load and stopping
phase survive reopen. There is no blind reverse when rear probes are absent.

The native controller now holds an autonomous requested reverse when a rear
ground/water probe trips. Explicit human orders retain their existing override.
This closes a gap where a timed routine reverse bypassed that native guard.
Motion remains motor/contact/brake driven; no body pose or velocity is assigned.

Named mining prefers the far side of its working and falls back to near-side
fresh ground when needed. Candidate bites pass the actual native support guard
before selection; it no longer retries one refused high point indefinitely.
The existing 30 mm freshness policy, arm reach, excavation depth and work
debit remain. Ring-based freshness is still a terrain approximation, not a
soil stability or complete excavation-history certificate.

## Measured acceptance

Windows, MSVC Release, Python 3.13.5, Chrome, 50 mm scene cells and native
`dt=1/240 s`. Ordinary starts use the same generator choices 0/1 and resource
seeds 851269740/851269741 as the earlier checkpoint. No page `poses` request,
provider calls, new resource grants or forced movement are needed.

| Generator choice | Actual receiving times s | Delivered total kg | Mined ore kg | Plans | Maximum queries | Median / maximum plan s |
|---|---|---:|---:|---:|---:|---|
| 0 | 52.2, 145.0, 202.6 | 120 | 36 | 27 | 4,092 | 0.2481 / 0.3798 |
| 1 | 30.2, 127.4, 220.8 | 120 | 36 | 13 | 1,745 | 0.0580 / 0.3367 |

The independent CMake-registered `banjo_generated_rover_repeat_tests` requires
three positive native dump receipts into the declared intake on each map,
delivered-mass agreement, an empty hopper and exact complete routine restore.
It passes in 227.14 s. These runs need no planned retreat before their third
load; retreat safety has separate analytical and native coverage. The replay
that exposed the old limit costs 0.0842 / 0.1743 s at 1,024 / 2,048 queries and
finds its loop with 2,808 queries in 0.2333 s. These are local CPU/IPC timings,
not a multi-world realtime scaling claim.

The first-load acceptance still verifies processing, nearby private pickup,
exact SQL credit and retry/restart without duplication. Both maps now produce
9.6 kg copper from 20 kg starter ore plus 12 kg mined ore, with zero measured
conversion residual. Earlier arrivals left cold batches heating beyond the old
80 s post-delivery test window (9.0 / 7.5 kg completed at that point). Native
replay confirms the remaining real heating/conversion; the test allows 160 s.
The 0.3 yield, six-decimal ledger tolerance and exact credit checks are unchanged.

Final affected gates:

- Two first-haul/layout cases: 151.48 s.
- Fifteen browser/player cases: 106.03 s.
- Fifty-five rover-brain cases: 9.17 s in the final focused rerun.
- Native rover suite: 21 cases, including the retained 18 glass/oak/iron
  material/grade scenarios within its ramp case.
- Machine/API documentation gates pass; all 286 native sources remain registered.
- Refreshed 8770 preview: ordinary entry, ten sensors, physical recovery/release,
  793.368 N measured pull, 296.136 J hand work and zero browser exceptions.

The native reverse case moves 0.198143 m on clear ground, brakes at a real rear
drop with less than 0.01 m travel and retains explicit human control. Actual
measurements and ignored local evidence are in `build/resource-flow/`:
`generated-repeat-hauling.json`, `generated-first-haul.json`,
`return-repeat-final-gate.log`, `return-final-verified-gates.log`,
`return-native-final.log`, `return-native-reverse-final.log` and
`return-budget-replay.log`; the final brain rerun is `return-brain-final.log`.

## Remaining scope

Three loads on two maps qualify this bounded journey. They do not prove
indefinite mining, arbitrary terrain, every turning/caster drift, or scaling
many simultaneous planners. More route families and cheaper bounded observation
remain work. General rover recovery still uses the measured external grip.

Cargo remains a durable ledger without added native inertia or a container/
tipping law. No material, friction, contact or fracture law changes here.
Retained glass/oak/iron mass, slip, battery residuals and unclosed mechanical
work are documented in [rover grades](rover-grades.md); this checkpoint adds no
full conservation or material realism claim. Native avatars, damage/repair and
the remaining player-experience journeys keep the fourteen-item goal active.
