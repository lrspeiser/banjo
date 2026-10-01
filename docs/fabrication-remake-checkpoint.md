# Selected-item Lab remake checkpoint — October 1, 2026

The subsequent [Lab funding-to-use checkpoint](fabrication-lab-funding-checkpoint.md)
adds reviewed stock/charger controls and actual output pickup, bag storage,
equipment and native digging in the explicitly configured fixture. It supersedes
those earlier next steps below. Ordinary starter capability and a damaged-tool
journey remain open; all fourteen gates retain four verified, ten partial.

## Implemented boundary

An authenticated player selects a current hands/bag item in Inventory and opens
the Lab. **Review remake** binds that actual source, native topology/kerfs and
condition to an exact frozen draft. It shows material mass, energy, minimum time,
station supplies and shortages as name/value rows. Review spends nothing.

For an explicitly configured and funded workbench, **Start remake** reserves new
material and starts finite work. Progress, paused-work Resume, native Run 1 s,
Place in World and a Collect in World link are available. Reload recovers the
accepted job; start/install retries retain their request IDs. Source changes,
expired plans, changed processes and unfunded starts refuse. Only the initiating
player may control or place a bound remake. Source tags and the frozen draft
hash are validated on load and retained in the installation receipt.

This creates a separate new product. The original remains with its recorded
damage; no native bond restoration, removal, refund or healing is performed.
Saved designs and an empty Lab have no carried-source remake panel. A normal
world without a process reports that absence instead of granting supplies.
Gathering actual raw goods remains available after process configuration.

Implementation: [source binding](../playground/fabrication_remake.py),
[room API](../playground/fabrication_room.py),
[Lab UI](../playground/workshop.js),
[job contract](../mcp/fabrication.py) and
[native/browser cases](../tests/fabrication_remake_tests.py).
See [API and persistence contract](fabrication.md#selected-item-remake--october-1).

## Measured cases

Windows/MSVC Release native runner/library, `dt=1/240 s`, matched 80 mm cubes at
40 mm cells, process stock `{}` and energy 0 J. Each independent world uses
actual rack stock and a declared 4000 J / 300 W native battery, a 250 W charger,
500 W process and authored 100 J/kg work estimate. Outputs are cold at 293.15 K.

| Material | Actual stock/output kg | Supplied J | Accepted charging s |
| --- | ---: | ---: | ---: |
| Glass | 1.28 | 128 | 1 |
| Oak | 0.3584 | 35.84 | 1 |
| Iron | 4.02944 | 402.944 | 2 |

Each workpiece completes after one further accepted native second. The complete
old parked native body remains identical during admission. Failed start saves,
exact request replay and whole reopen with the original request/session pass.
These are declared local process-accounting comparisons, not a manufacturing
calibration or full-world momentum/energy certificate.

A separate 100 mm oak / 10 mm cell experiment uses an actual 6 m/s iron cutting
edge under normal gravity, `dt=1/240 s`. Unsupported contact-fracture requests
are declined. The source records 104 broken of 12,876 bonds, connectivity
0.9919229574401989. Actual take-up/stow selects that damaged body. New 0.7 kg oak
and 70 J produce a separate native part with intact retained connectivity; the
original complete parked body and its condition are unchanged. Connectivity is
not strength, fatigue life or joint health.

The ordinary Chrome case collects 25 kg actual world oak, takes/stows the field
pick, reviews its exact recovered geometry, starts a 1.925 kg / 192.5 J remake,
pauses it, reloads, resumes, runs and places it. A peer is refused pause and
placement. The original parked pick is unchanged and a further 25 kg gathering
operation succeeds after configuration; personal stock is 48.075 kg. This fixture
explicitly declares a 2000 J / 300 W battery and the workbench estimate. It does
not prove a starter world already supplies those capabilities. Chrome records
zero JavaScript exceptions. The resulting output link is checked; the subsequent
physical collect/equip/use journey remains an acceptance gate.

## Verification and publication

The [fixed QA suite](../scripts/fabrication_qa.py) includes these four new cases,
alongside native funding, assembly, persistence, HTTP and MCP protocol coverage.
Final fixed suite: **57/57 pass in 42.811 s**, including paused-work browser
resume. QA manager launch/status/cancel: **2/2 pass in 43.962 s** against the
preceding 57-case checkpoint. API docs: **12/12 in 0.183 s**. Source registration:
**287/287**. Python compilation, JavaScript syntax and diff whitespace pass.
All **1,525** local document file references exist. No C++ source, native law,
ABI 25 or physics tolerance is changed.
MCP advertisement versions become world 1.16.0 / platform 1.19.0.

Evidence: ignored `build/resource-flow/lab-remake-resume-20261001/report.json`
records base `1845f46b23ba2fb12486de9a3b8c7bfdcd463b61` plus dirty source scope,
native runner SHA-256 `8d5ff68d5d32119932878bb860c8c3a3fbbc761dc5fba36f472ff5a94c167f97`
and library SHA-256 `b9d277d970cddbd20f2950f55f683cb4bcbf1dd8e63ede01743dfc444cc87ba1`.
The native binaries are unchanged. This is measured Windows evidence, not a
macOS/Linux or cross-GPU qualification.

Refreshed own preview 8770: fresh generated entry, native intact pick, three
actual store readings (zero finite-output sources), 16 stock sources, no pending
reservations and hidden empty reservation UI. Actual take-up/stow opens the
source-bound Lab; Review reports the undeclared process without offering Start.
Returning to an empty Lab hides Remake. Zero JavaScript exceptions.
Screenshots and JSON are under ignored `build/resource-flow/`.

The QA manager tests now wait up to 130 s, matching the existing 120 s worker
deadline plus bounded cleanup. Their former 45 s wait left only about 2.5 s
headroom for the expanded suite. Production timeout and success assertions are
unchanged; this adjustment avoids an observation deadline preceding the worker.

## Remaining acceptance

All fourteen player requirements remain active: four verified, ten partial.
Next supply an explicit finite starter energy/workbench capability, bring real
rack and charger funding into the reviewed Lab flow, and verify actual damaged
item → paid remake → collect → equip → use in ordinary generated worlds.
Fatigue, joint repair, mixed-material lattice interfaces, calibrated process
coefficients, physical stock transport and full conservation remain open.
Cold rack inventory is an explicitly declared reservoir approximation.

## Published checkpoint

Implementation **`217814f`** is on GitHub main. The ordinary fast-forward push
is verified against the remote main ref. Preview 8770 runs these sources with
the unchanged native runner/library. Its generated-world condition/Inventory/
carried-Lab/empty-Lab acceptance passes with zero JavaScript exceptions.

Preview: `http://127.0.0.1:8770/world?world=b94ebf64f8f94a92ad89a00879e81ed4`.
The field pick is in this player's bag; Inventory → Lab → Review remake reports
the world has no declared workbench. No fixture resources were granted there.
The configured/funded replacement journey is qualified by the isolated tests.

This publication note records the checkpoint; it adds no physical validation.
Next work remains ordinary finite capabilities and reviewed funding followed
by actual collection, equipment and use. Four verified, ten partial.
