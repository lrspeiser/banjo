# Chat playground, permanent material state and compact history

September 6, 2026. The [updated project goal](project-goal-2026-09-06.md)
organizes the complete platform into nine goals while preserving all 40
requirements. The [parallel ownership plan](parallel-physics-workstreams.md)
sets independent module boundaries and serial integration gates. No full goal
is complete.

## Implemented and verified reference modules

`material/Plasticity` supplies a small-strain isotropic J2 radial return with
linear hardening. Tensor stress follows total strain minus permanent plastic
strain. Unloading leaves permanent strain, and reloading uses the retained
yield surface. Hydrostatic loading does not cause J2 yield. Tests cover the
closed-form shear solution, hardening/free energy, dissipation, curved-path
subdivision, zero increment and invalid-state rejection. Glass/brittle and
wood/orthotropic declarations reject this law rather than being mislabeled.

Its 14-double state stores total strain, plastic strain, accumulated equivalent
plastic strain and dissipation density. Stress reconstructs from that state and
the material. The constitutive work partition is distinct from backward-Euler
stress-work quadrature and its algorithmic excess. This is **not a spatial
metal dent, contact solve, calibrated iron result or finite-strain model**.

`material/PropertyVariation` samples a bounded property using a versioned
integer algorithm, material seed and stable object/element/property/law IDs.
Order and display names do not change the sample. Positive/nonnegative domains
and finite bounds are checked. Golden results, replay, reorder/prefix stability
and a 100,000-seed distribution sanity test pass. This supplies intrinsic
heterogeneity, not numerical error control, correlated flaw fields, calibrated
fracture probabilities or an automatically integrated collision response.
Refinement must preserve physical flaw identity; arbitrary new cell IDs do not
provide that property by themselves.

## Compact numeric persistence and history

`persistence/NumericStateDelta` encodes only changed IEEE-754 bytes relative to
an immutable finite-double base. It is lossless, including signed zero and
subnormal values. Layout, object, base identity/content checksum, revision and
parent are checked. Explicit little-endian encoding, canonical indices, size
limits and CRC32 reject corrupt or incompatible payloads. CRC is an accidental
corruption check; the host must resolve/authenticate the declared base digest.

The sparse entry API takes the complete current overlay and works in proportion
to changed fields. Partial decoding scans the encoded changes and reconstructs
only the requested range. Dense encoding and full reconstruction still scale
with base size. The immutable base has a one-time validation/allocation cost.
History references the same base at every revision, avoiding a replay chain.
Revision/byte budgets and stale expected revisions reject before commit; there
is no silent history eviction. Original-state restoration is a candidate,
and appending it preserves the earlier revision.

Three serial Release runs, 100 timed samples per case after warmup, on this
Windows host produced:

| Base material points | Dense base bytes | Changed points | Delta bytes | Partial decode p95 |
|---:|---:|---:|---:|---:|
| 64 | 7,168 | 16 | 732 | 6.1 microseconds |
| 4,096 | 458,752 | 16 | 732 | 6.1–6.5 microseconds |
| 65,536 | 7,340,032 | 16 | 732 | 6.1–6.6 microseconds |

There are 64 changed scalar fields in this particular unloaded shear state.
An original-state revision takes 92 bytes; the two stored revisions take 824
bytes. Sparse encoding p95 was 6.9–8.6 microseconds, and validating/resuming the
16 material points was 4.4–5.7 microseconds. At 65,536 points, initial base
validation took 62.2–65.6 ms and full decoding took 1.72–2.00 ms. These costs are
reported separately, not hidden in the sparse path. Dense heavily damaged data
can grow; this fixture is not a compression guarantee for every object.

The saved J2 state and its next strain increment match uninterrupted execution
bit for bit in the same build. This verifies the numeric/material-point path.
Geometry, velocities, constraints/contact caches, thermal state, topology,
renderer rebuild, multiplayer and live-world sleep/wake are **not** implemented
by this codec. Gameplay repair must still account for material/energy,
consistent stress/topology and safe placement before using a restoration
candidate. A zero numeric delta is not a physically free repair.

## Chat-to-engine playground

The [local playground](../playground/README.md) uses server-side GPT Responses
with Structured Outputs and the ignored local `.env`. The
`banjo-playground-1` language compiles via the existing Python authoring API
into actual native packages. It admits template comparisons and bounded custom
preset objects, and also exposes the thermal, material-state and published
glass references with their separate scopes.

Strict host validation precedes every native execution. One active job,
bounded sweeps/cells/time, fixed executable routes, request deduplication,
loopback Host/Origin checks, a session token and static-file allowlisting bound
the local service. No model-generated executable code, shell or path is run.
The API key is never placed in the browser, prompt, package or logs. Generated
plans, packages and reports are retained in ignored `build/playground-runs`.

The studio opens the exact generated package through its directory/filename
interface; case discovery contains only packages. `--duration-s` aligns its
interactive duration with the headless fixed-step count. Native reports are
stored outside the scene directory. The studio is a fresh simulation of that
initial state, rather than a continuation of the finished headless process.

All generated damage-integration scenes use strict limit rejection. A strong
impact can halt when the solver cannot resolve damage; this does not certify
glass shattering. The [published 6 mm glass data](glass-drop-benchmark.md)
records first fracture under repeated increasing-height drops, and leaves
missing apparatus details explicit. It is reference data, not model validation.

## Verification and remaining gates

The complete MSVC 1944 Release build passed. All 55 native CTest suites passed
in 83.19 seconds. The 29 mocked Python language/HTTP/worker tests pass; they do
not spend API tokens or open native windows. JavaScript syntax validation
passes. The standalone state probe produced the three serial measurements
above. The previous main checkpoint `34ed3b4` also passed GitHub CI; outgoing CI
must be checked separately after publication.

An actual `gpt-5-mini` browser request generated iron-ball impacts on glass,
oak and iron at 2 and 6 m/s for one second. Planning took 4.433 seconds and
1,195 tokens; both native CLI cases completed 480 steps. Both visible studio
cases also stopped at 1.000 second and 480 steps. All reported physical fields
matched the CLI, excluding compiler metadata, load/step timing and skin/
presentation diagnostics. The 2 m/s studio trial had 50 active frames and
31.25 ms p95 frame time; this does not qualify the 60 Hz target.

The Language, Results and Project goal tabs were exercised without browser
errors. A further real chat revision changed an iron-cube drop from 25 to
50 cm and selected `rigid_drop`; the generated no-fracture package validated,
ran 480 steps and opened visibly. The first cube proposal selected plate_drop
despite a request for rigid controls and used incorrect calibration wording.
This is retained as a planner limitation: structured output is not semantic
proof. The prompt now describes the rigid route and supports explicitly, the
UI labels the plan as a proposal, and terminal chat/results use engine evidence
instead of repeating the planner's physical claims. Users can inspect and
revise the setup before treating it as their intended experiment.

Direct native admission and execution covered plate drops, rigid drops and
custom objects. This caught and fixed rigid-drop conversion retaining
network-only resolution, pin and grain fields. The knife/tomato proxy and
20 m/s thin-panel test hit strict damage limits with outer-tick rollback.
Those are diagnostic rejections, not completed cutting/fracture predictions.
Actual worker adapters also completed the material-state and six-frame thermal
references with real executables and an injected planner; published glass
remained reference-only/blocked with no native scene. A further real GPT
browser request completed the material-state reference and correctly disabled
the native scene button. These adapter checks are not performance benchmarks.
The native screenshot button now checks write success and places chat-run
images beside the job's live report, outside the scene-discovery directory.

Tests and references establish bounded slices, not completed G02 realism,
whole-object dents, game repair, full-world persistence or realtime mechanics.
Next integrate a resolved contact/continuum patch, use the persistent plastic
and flaw states there, implement a complete saved-object layout and repair
transaction, and measure that coupled path against physical experiments.
