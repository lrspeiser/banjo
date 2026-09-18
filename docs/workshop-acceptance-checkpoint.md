# Explicit Workshop load-test limits

Base: main `971261cd81d967fe928f10d796bf5370ddd062c9`.
Scope: goals 5 (useful measured tests), 7 (reusable evidence), and 2/10
(trustworthy controls and regression protection). No native material law changed.

## Implemented

Static-load tests accept explicit endpoint displacement, rotation, fracture-event
and minimum actual grid-load limits. The browser's limits are opt-in. API/MCP
clients can supply the same limits inside the existing test config, and saved
presets retain them. The same evaluator is used by direct Python trials and the
shared browser/MCP bench. Design-declared limits can be tightened, not weakened.

Missing or nonfinite measurements cannot pass. Native geometry verification,
surviving tested bodies and completed simulation time are prerequisites. Each
verdict includes its checks and exact Matter hash/resolution/load/time basis.
Changing test controls clears old results and invalidates pending responses.
Late optional history loads preserve current controls and pending tests rather
than resetting them; a deliberately delayed-response browser case covers this.
Evidence import now supports unjudged static observations and deep-copies nested
state, retaining source design, subject and native-geometry metadata.

## Verified locally

Linux, Python 3.13, Node 22, GCC Release, banjo-cpu-precise-v1. The focused gate
passed 22 Python suites (183 tests) and seven native tests. The new native case
compares glass, oak and iron tables at 40 mm over 0.2 s; enabling limits leaves
every measured physics field unchanged. Deliberately excessive minimum-load
requirements fail. Thirteen new pure tests cover invalid bounds, missing data,
early stops, lost bodies, optional controls, presets, immutable evidence and
absence of fabricated validated ranges. JavaScript syntax and source-registration
checks pass. No tolerance was relaxed.

The container browser is administratively blocked from localhost. Eight required
Chrome cases, including three new limit-control/stale-response cases, run on the
GitHub Actions checkpoint before publication. Local browser verification is not
claimed.

## Limits

These are endpoint measurements of the exact compiled test, not peak deformation,
creep, material calibration, mixed-material certification, or proof of behavior
across a load range. The first adapter handles exact-Matter static loads only.
Other benches remain observations. Workshop installation and generic functional
certification remain separate roadmap work.

## Published verification

The required GitHub Actions gate passed the fast, native-engine and all eight Chrome browser tests.
Run: https://github.com/lrspeiser/banjo/actions/runs/35295490627
