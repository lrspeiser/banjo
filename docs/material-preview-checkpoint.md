# Material collection previews — October 1, 2026

Verified against main base `3c0e9d08e14ef3b016967b5d33c2f7c8dab40a32` with the outgoing changes present. [Machine-readable evidence](evidence/material-preview-checkpoint.json) records source/binary hashes and a native receipt. Publication revision is recorded below after the verified push. Broader progression remains four verified requirements and ten partial.

## Player flow

Ground deposit circles, floating material/reserve labels, the tool target circle and carry landing circle are removed. Ledger extraction areas remain available to rovers. Machine input hoppers, rover filling pictures and recorded transfer packets remain visible.

The right panel's **At crosshair** card shows material thumbnails and the collection method:

- Ground tools: possible native soil/sand; **J / click · Dig**. Thin sand can also show underlying soil as a candidate. No amount is promised. Wet ground, absent loosening motion, missing point and unsupported surfaces do not promise loose soil/sand. Full load and reach failures remain explicit.
- Ore extraction area: **Mining rover**, with **View source** opening a matching rover's controls. If no matching rover exists, the link opens an actual rover recipe from the current catalog. Hand tools never receive ledger ore from this preview.
- Intact object: its actual mesh thumbnail and **Whole item**; pickup, occupied hands, attachment, distance or fixed placement are distinguished. This does not promise constituent material drops.
- Output or loose stockpile: actual material quantities, **Collect** within 2 m, or **Walk closer**. Input hoppers are marked **Machine input**. The existing durable collector authorizes/debits the shared source and credits only the caller's personal Inventory. Walking output collection remains available.

**Nearby materials** shows up to three nearest source thumbnails, method and distance. **Look** changes camera direction only. It aims at a real stockpile packet, rather than empty space between cubes. Picking a packet is a UI ray clipped by the native visible hit distance; pictures add no native mass or collider. Detailed pinned ground layers are collapsed.

## Shared authoring and physical boundary

`mcp/resource_previews.py` derives read-only candidates from native survey layers and the declared ground-tool use/point. `playground/tool_use.py::resolve` returns `gather: {method, materials, state, label}`. Existing target/reach metadata, including the legacy `ring` status object, remains API compatible; it no longer draws a ground ring. Custom names and LLM-authored tools inherit the same preview. World authoring instructions and MCP interaction responses describe the current interface and prohibit fabricated drops/ore rewards.

Collection still comes from closed native ground-work receipts or the existing durable goods collector. Native rock-work-v1 remains available to suitably hard points; this soil/sand preview does not certify rock breakage or new raw ore collection. No solver, material, contact law, force bound, timestep, tolerance or progression award changes. No wood cutting law is added. The earlier matched glass/oak/iron [contact experiments](quick-tools-checkpoint.md) remain separate physical evidence.

## Verification

Windows, Python 3.13, MSVC 19.44 Release native CPU ABI 25, actual Chrome on ordinary pages. Native generated scenes retain 50 mm cells and dt=1/240 s. These are host/UI changes; existing runner and DLL are reused.

Expanded navigation checks exposed a mistaken interpretation of a routine's `of` field (step count, not material) and assumptions about named versus custom routines. Source navigation now joins declared dig steps/places with the current routine's sites. The native receipt fixture explicitly declares an ore zone and its rover route on known native sand; it changes no native material. Closing machine controls clears their input focus before returning to tool use. Initial failures were fixed before the final passing run.

- `python tests/material_preview_tests.py -v`: six checks, including actual whole-pick thumbnail/E pickup, native sand receipt within an explicitly declared test ore area, unchanged ore reserve, camera-only Look, rover source navigation, and output thumbnail Collect/private credit.
- `python tests/tool_use_tests.py -v`: 20 passed.
- `python tests/quick_tool_tests.py -v`: five passed, including real rapid input and retained glass/oak/iron native account comparisons.
- `python tests/world_goods_tests.py -v`: 15 passed, including automatic/manual output collection, races, failed acknowledgement, SQL failure/restart, two players, raw stock and browser input/output pictures.
- `python tests/ground_work_mcp_tests.py -v`: 24 passed; current MCP interaction instructions are covered.
- `python tests/api_docs_tests.py -v`: 12 passed.
- `python scripts/check-source-registration.py`: 287/287 registered; `git diff --check` passes.

Snapshots are in local `build/resource-flow/material-preview.png` and `material-output-preview.png`. Browser navigation/teardown can abort pending HTTP reads and print Windows socket-close tracebacks; no browser runtime exception occurred. These disconnect logs are not simulation failures. This checkpoint verifies agreement between preview categories and actual collection, not full-world conservation, calibrated fracture, cross-GPU determinism or the entire tech tree.

Next: qualify additional physically supported harvesting families and ore exposure/dismantling routes before advertising raw drops from those actions. Show their verified methods through the same preview, rather than defining loot by a display name.
