# Revision-bound assembly tests in the workshop

Local source `22932be1b0b3f397fb83e39d3bbcf5f54163234a`, September 5, 2026; not pushed or merged. Full platform goal remains active.

The assembly screen now offers Review a physics test. Load test specification reads the workspace's assembly-test.json and displays initial relative kinetic energy, duration, required separated fraction, numerical energy budget, state tolerance and evaluation limit. Run on saved revision calls the existing bounded isolated test API on a background std::async task with copied declaration/settings. The renderer does not perform the simulation. There is one outstanding test per workshop; no cancellation was added, and process shutdown can wait for its bounded task.

Completed results show the measured pass/fail, separated versus required fraction, signed energy residual and accumulated absolute numerical error. Result validity requires both the saved revision and exact canonical declaration to match. Changing a draft hides the old result and export control behind an explicit stale-result message. Loading another specification clears the report. Budget/validation errors are reported as Test rejected, not as a measured physical failure. Returning to object authoring does not mutate the test; completion is collected when the assembly screen is next opened.

Export test evidence writes assembly-test-result.json with draft_revision plus the complete report, declaration, specification, bodies and site histories. This is an explicit snapshot; previously exported files are not automatically current after edits or failed runs. The UI never loads exported reports as current evidence. Reports and test settings are not added to world persistence. Passing means only that the requested separation criterion was met in the isolated fixture, not that the assembly is useful, realistic, manufacturable or safe. There is no live construction, gravity or external collision owner in this test.

## Native evidence

Oak revision 1 was tested through actual Load, Run and Export controls under both earlier declared experiment settings:

| Case | Outcome | Separated | Signed energy residual J | Accumulated absolute error J | Evaluations |
|---|---|---|---|---|---|
| Low input | failed | 0% versus 100% required | 2.4094155e-10 | 6.2066456e-8 | 2841 |
| High input | passed | 100% versus 100% required | -4.4650925e-9 | 7.9722086e-9 | 3397 |

Both exports were parsed and checked. An intentional joint-ID revision to revision 2 replaced the visible pass with the stale-result message. A new test with only three evaluations produced the explicit evaluation-budget-exhausted rejection without an export control. Saved lots, objects, authoring history and simulation ticks stayed identical to the pre-test world; only the intentional draft revision changed.

The workshop target builds on Windows MSVC 19.44 x64 Release; all 21 CTest suites pass in 17.83 seconds, retaining glass/oak/iron assembly and inventory regression coverage. Native test controls were exercised for oak this turn, not glass/iron. No physical model, criterion, solver bound or tolerance changed. UI loading uses ordinary JSON parsing for preview; the actual test API independently applies its strict bounded parser, including duplicate-key rejection. No concurrency-race or shutdown-latency claim follows from the native checks.

Next: connect real LLM review of regenerated evidence to the selected revision, then carry assembly declarations/testing into the first-person crafting table. Authoritative contact ownership, material/energy transactions, live assembly construction, realistic cutting and remaining gates stay open. All 40 mechanics/platform rows are retained. The test workshop and starter remain running.
