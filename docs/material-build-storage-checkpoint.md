# Material-to-build storage checkpoint — October 2, 2026

## Implemented

R1's broken-rock receiving gap is fixed. Native withdrawal already produced
`rubble`/`mixed` packets, but the fabrication receiver accepted only `granular`
and the native snapshot loader refused every nonzero rock export.

- HTTP/MCP `store_ground` and `retrieve_ground` accept optional `rock_m3`,
  default zero. Legacy sand/soil request shapes and retry hashes remain valid.
- Raw lots retain substance, volume, native mass, provenance, granular/rubble/
  mixed form and explicitly unmodeled thermal state. Rock does not become iron.
- Checks/diagnostics use existing native densities: sand/soil 1600 kg/m3,
  broken rock 2400 kg/m3. `ground_audit` now includes a rock row.
- Native v4/v5 reopening checks rock exports minus returns plus aggregate carried
  rock against the existing excavation/cut bound. Excess returns and unbacked
  exports refuse; earlier ground versions still refuse rock exports.
- Staging saves source, raw destination and retry receipt together. Failed saves
  retain the live source and receiving ledger exactly.

No contact, strength, excavation-work, power, capacity policy or thermal law is
changed. This is storage-account/restore work. Crafted-object pickup and
finished-stock funding are unchanged; no physical container is implemented.

## Verification

Windows / MSVC Release CPU, separate `build/agent-object-strike`. Native runner,
C library, ground-work and terrain targets rebuilt through CMake. Registration:
297/297, no exclusions. All **67** fabrication, ground-transfer, stock and API
documentation checks pass in **40.883 s**. Two native ground-work/terrain CTests
pass in **4.61 s**, retaining existing glass/oak/iron cases and their limitations.

The model test checks mixed storage, partial rock return, 2400 kg/m3 mass,
remaining stock, corrupt mass/form and overdraw. MCP tests keep legacy arguments
and reject negative, boolean and excessive rock quantities.

The native test reuses the existing 1.5 kW breaker experiment: 250 mm terrain
cells, `dt=1/240 s`, existing 30 MJ/m3 rock-work declaration and 37.5 kg actual
broken rock credited to Alice while Bob/the clock step. That fixture explicitly
raises its allowance to 100 kg because its 47 kg tool plus one 37.5 kg cell
exceeds normal 80 kg. It releases the tool and restores 80 kg before storage.
This does **not** qualify fresh-world breaker acquisition or normal-capacity
mining. No tool is weakened or rock supplied by editing a carried account.

Storage refuses Bob's empty account, rolls back disk failure, commits/replays
once, rejects excess native exports/returns, reopens whole, returns Alice's rock
and reopens again with exact retained ground accounts. Finished stock and
process energy stay unchanged. Matching volume/mass accounts are not a
whole-world mechanical/thermal conservation certificate.

```powershell
python scripts/check-source-registration.py
cmake --build build/agent-object-strike --config Release --target banjo_live_world_run banjo_c banjo_ground_work_tests banjo_terrain_tests --parallel 4
ctest --test-dir build/agent-object-strike -C Release -R '^(banjo_ground_work_tests|banjo_terrain_tests)$' --output-on-failure
python -m unittest fabrication_tests ground_transfers_tests fabrication_stock_tests api_docs_tests -v
```

Python uses `BANJO_LIVE_ENGINE`/`BANJO_LIBRARY` pointing to the rebuilt Release
runner/DLL, `BANJO_BUILD_DIR` to that Release directory and `PYTHONPATH=tests`.
Ignored logs: `build/resource-flow/r1-rock-build.log` and
`build/resource-flow/r1-storage-regression.log`. The API check also found the
earlier `banjo_fix_section` missing from C API documentation; its existing
experimental contract is now documented, with no fixing changes.

## Remaining work

R1 stays open: ordinary fresh-world raw collection → machine input → processing
→ private output → funded built-in/saved design → use → restart, unassigned-load
recovery, raw-to-usable-stock paths and exhausted-input/player storage guidance.
Raw storage makes no finished material and closes none of those routes. No
preview restart, browser/UI or native interactive-window verification is claimed
here. R3 remains paused.
