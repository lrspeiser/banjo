# Exact energy receipts and material-to-build acceptance — October 2, 2026

Published implementation: `fa84f146ee8d5ed24b389ae92ec8bcb2029c9055` on GitHub main.
The separate runner was rebuilt from these source changes; preview servers
were not restarted.

## Implemented

The native runner now reports energy-store declarations and counters at their
actual double precision in both draw replies and ordinary machine readings.
Previously `tidy` rounded them to 0.00001 J. A real 0.000006 J draw could report
0.00001 J given, exceeding the complete saved meter by 0.000004 J. Market's
unchanged 0.000001 J receipt bound correctly refused that mismatched save.

No energy law, debit, credit, reserve policy, numerical tolerance, machine
behavior or snapshot format changes. Geometry and other display rounding stay
unchanged. This supersedes the unresolved cause in the
[previous handoff](material-build-handoff.md).

## Verification

Windows / MSVC Release CPU; rebuilt `banjo_live_world_run` through CMake in
`build/agent-object-strike`. Native library and physical solver sources retain
the preceding storage build. Source registration: 297/297, no exclusions.

- The new native regression failed before the fix: charge 3999.999994 J was
  reported as 3999.99999 J. It now checks draw/poses against complete snapshots
  exactly after 0.000006, 500 and 99.123456789 J withdrawals.
- A real fresh-world HTTP test banks after a fractional native draw, injects a
  disk-full save failure, retries the same request twice, checks private peer
  balance, restarts the whole Python server and checks exact native meters and
  one wallet credit. No credit is issued before the durable checkpoint.
- Those two regressions and seven Market tests pass: 9 checks in 4.491 s.
- The complete stock suite and existing personal solar-Market/server-restart
  test pass: 13 checks in 15.562 s. Existing glass/oak/iron paid-stock evidence
  retains zero material residuals and energy residual magnitude below 1e-12 J.
- Existing native ground-work/terrain suites pass in 4.08 s. These are regression
  checks, not new constitutive or full-world conservation qualification.

Ignored logs: `build/resource-flow/r1-meter-build.log`, `r1-meter-check.log`
and `r1-meter-stock-regression.log`.

## Fresh-world material-to-build journey

The restored draft acceptance now passes in **141.119 s**. Generated seed
851269740 starts with an empty paid workbench. The native rover actually mines
and delivers copper ore; the declared processor consumes the starter hopper
and mined load. The player collects the measured copper output nearby into
private Inventory; a second player receives none.

The player saves/reloads a full-size battery-powered mine lamp and funds its
0.5 kg assembly-copper requirement from the collected output, replaying that
transfer without another debit. Glass/iron come from finite personal Market
purchases paid with native solar energy. The original iron shelf is smaller
than the design requirement, so the test advances real accepted world time for
restocking rather than shrinking the design or giving it extra stock.

Actual 500 W native supply funds the quoted process work and battery charge.
The test completes native Make, placement/replay and ordinary World Use. The
light turns on and its battery pays for operation. A complete Python-server
stop/start retains the fabrication ledger, remaining private copper, peer stock,
wallet/offers/orders, saved design and exact native battery state. Collection
and funding retries after restart do not duplicate or spend another copy.

Measured: 20 kg starter ore + 12 kg mined ore produce 9.6 kg declared copper;
0.5 kg funds the lamp and 9.1 kg remains private. Stock is 4.32 kg glass and
12.68644 kg iron; restock waits total 350 accepted world seconds. Native funding
is 2200.644 J, including 500 J installed battery charge. After two seconds of
10 W light operation the battery retains 479.9999999999909 J and has given
20.00000000000002 J. Fabrication material/copper ledger residuals are zero,
energy residual is 2.84217e-13 J and native transfer/meter residual magnitudes
are below 9e-11 J. World cells stay 50 mm, native dt=1/240 s, observer clock
ticks are 0.2 s. These are existing ledger/native meters, not complete mechanical
or thermal conservation accounts.

Evidence: `build/resource-flow/material-build-lamp.log` and the ignored
`material-build-lamp.json` measurement record. This is an HTTP/native acceptance
route with surveyed player positions, not a browser/physical-avatar playthrough.
Copper conversion and incorporation use the existing declared goods ledger;
they do not certify chemical yield, full-pipeline conservation or constituent
mechanics. No solar energy, trader stock or geometry is injected to pass.

Run with `BANJO_LIVE_ENGINE`, `BANJO_LIBRARY` and `BANJO_BUILD_DIR` pointing to
the separate Release runner/library directory, and `PYTHONPATH=tests`:

```powershell
python -m unittest fabrication_remake_tests.LabRemake.test_fresh_mined_processed_personal_copper_funds_saved_lamp_use_and_server_restart -v
python -m unittest fabrication_remake_tests.LabRemake.test_fractional_native_meter_bank_failed_save_retry_peer_and_server_restart fabrication_stock_tests market_tests -v
```

## Remaining R1 work

Player-to-machine input delivery, ground-to-usable-stock paths, exhausted-input
guidance, legacy unassigned-load recovery and player-facing raw storage remain
unfinished. Supported processed assembly supplies are ledger quantities;
incorporating their native constituent mass/thermal/mechanical state remains
R5. R3 remains paused. Existing preview processes are unchanged; this checkpoint
does not claim browser or normal interactive native-window verification.
