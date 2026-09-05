# Collected inventory and creation requirements

Tested runtime and real provider source: `fca0cb357d4dc4f154bb6efbb03efb9b69e8134f` on local `codex/physics-foundation`. The initial implementation was `7822435fddb03bdfbe4e94a8e653943bf0bf4c9c`; the final prompt correction is included in the tested source. These changes are local, not pushed or merged. GitHub was not refreshed for this checkpoint. The complete [project goal](project-master-plan.md), physics gates and [40-row scorecard](mechanics-scorecard.md) remain active.

## User experience and implemented behavior

Collected resources enter inventory. A user can request a supported object and receive its design, what it needs, what is held, and what else must be collected. An unaffordable design retains the requested substance and dimensions. Only an explicit alternative request or a genuinely open choice permits a different design. A missing law/tool is a capability problem: more inventory cannot enable an unsupported hinge or energy-limited fabrication.

The compiler independently derives occupied volume, mass and inertia. `CreatorWorld::assess` and the JSON `assess` / `assess_rebuild` commands report collected inventory, same-substance recoverable selected-object material, matching uncollected lots and the remaining shortfall. Assessment does not collect, reserve, debit, create, reset motion or advance time. Build/rebuild revalidates current state through the same assessment path.

The workshop displays the retained design as a wire preview and shows required, held, recoverable and missing mass. Build stays disabled while resource/placement/budget checks fail; an unsupported assistant clarification also disables Build until the request/design changes. Collection is an explicit action. The initial implementation collects a whole fixed lot once; it does not implement partial pickup, mining, drops, arbitrary new sources, trading or multiple actors.

The assistant sees compiler-checked requirements for the current draft and selected recovery context. It returns an inspectable recipe or a capability clarification. The returned recipe is assessed again; the assistant's prose does not authorize resource allocation. The headless probe saves an assessment even for a resource-short proposal, and `--apply` cannot build it. Unsupported/invalid drafts can still be sent for explanation, while stale/missing edit targets remain rejected.

## Requirements API

Existing recipe versions and bounds remain unchanged. Example commands, using a supported SI recipe:

```json
{"type":"assess","recipe":{"schema_version":2,"name":"Iron block","shape":{"type":"box","dimensions_m":[0.08,0.06,0.1]},"material":"iron","physics":"rigid-v1","placement":{"tangent_m":2,"bitangent_m":0,"clearance_m":0.002,"orientation_wxyz":[1,0,0,0]},"motion":{"linear_velocity_m_s":[0,0,0],"angular_velocity_rad_s":[0,0,0]}}}
```

For replacement use `type: assess_rebuild` plus `object_id`, `expected_revision` and `recipe`. Recovery only credits the explicitly selected object's original material. A new creation never scavenges another object. A cross-material replacement must obtain its new substance from collected stock.

The successful query result contains `assessment_version: 1`, `status` (`buildable`, `needs_resources`, `blocked`), `buildable_with_inventory`, `buildable_after_collection`, `compiled`, `issues`, and `material_requirements`. Each requirement gives `material`, `required_mass_kg`, `inventory_mass_kg`, `recoverable_mass_kg`, `collectible_mass_kg`, `missing_mass_kg` and `missing_after_collection_kg`. In a rebuild, the buildable flag includes the displayed selected-object recovery. `compiled.allocations` is only populated when the entire assessment is buildable; it is not a reservation.

Known valid-design blockers have codes/fields: `insufficient_material`, `placement_overlap`, `object_limit`, `history_limit`. Multiple independent blockers can appear together. A successful `assess` query can report an unbuildable design; callers must inspect its result, not just outer `ok`. Unsupported recipes, invalid units/ranges and stale targets still use the existing command error boundary; a general versioned error schema remains open.

`buildable_after_collection` means matching lots currently present would cover the material shortfall and no other current blocker was found. It neither performs pickup nor guarantees future placement. `fabrication_energy_j: null` explicitly means no implemented fabrication energy law; it is not zero work. All buildable claims are within the intact-authoring sandbox and do not prove functional performance.

## Evidence

The same new solid block (8 × 6 × 10 cm) is requested for all three substances. Each shortage case starts with an existing 9.9 kg sphere and 0.1 kg free stock; sphere radii intentionally vary with density. The new block's dimensions are held fixed and it starts at rest, world-aligned at tangent 2 m, lane 0 m with 2 mm clearance. This is a material-requirement comparison, not a matched-radius sphere experiment.

| Substance | Required kg | In inventory kg | Additional kg |
|---|---:|---:|---:|
| Glass | 1.2 | 0.1 | 1.1 |
| Oak | 0.336 | 0.1 | 0.236 |
| Iron | 3.7776 | 0.1 | 3.6776 |

Seven final real Codex calls pass: three shortages retain the exact requested recipe and build nothing; three uncollected-lot cases report no held material, then explicit collection permits the exact returned recipe to build; an explicit iron-to-oak alternative uses oak while retaining the original iron sphere. Repeated collect/create calls in the three collection sequences do not duplicate mass or objects. All source world files remain unchanged by the provider; the probe checks in-memory nonmutation when no object is accepted. Timings span 8.308–10.679 seconds. See [per-case figures and explanations](evidence/requirements-assistant.csv).

Five further real provider regression cases pass on the same source: glass/oak/iron selected rebuild/reclaim/replay, unsupported hinged door and fabrication constrained to 10 J. The door and energy requests return null recipes and no applied world. The new material proposals and prior revision cases retain the default Codex provider/configured login; no model override, coding subagent, tool execution or model-authored world mutation is used. This is a small observed sample, not a guarantee that all future language requests are interpreted correctly.

One preliminary call at `7822435` returned a malformed/oversized explanation and a null recipe for a supported shortage. The strict parser rejected it without applying a world. The final prompt explicitly requires a recipe for stock-only shortages and brief explanations. Preserve the failed exchange in the evidence; the validator limit was not widened. Provider streams also report unavailable Code Mode with its host disabled; the final structured replies still complete without tool calls.

All 15 Windows CTest executables pass in 11.73 s. New regressions cover three-material independent volume/density requirements; collected/uncollected accounting; repeat collection; insufficient total world stock; selected recovery and no transmutation; concurrent placement/stock blockers; history exhaustion; read-only request/assessment; stale target and unsupported-law rejection; and unchanged moving-world state. Existing dynamics, tensors, rollback, persistence and replay tests remain in the full run. No constitutive/contact law or physics tolerance changed.

Windows 11 Pro 26200, Core Ultra 9 285K, RTX 5090 / NVIDIA 580.88 / OpenGL 3.3; MSVC 19.44 x64 Release, CMake 4.1.2, Jolt 5.6, raylib 6.0. `SUPPORT_CUSTOM_FRAME_CONTROL`, `SUPPORT_BUSY_WAIT_LOOP`, and `USE_STATIC_MSVC_RUNTIME_LIBRARY` remain OFF.

Reproduce from the repo:

```text
cmake --build build/win-integration --config Release --parallel 8
ctest --test-dir build/win-integration -C Release --output-on-failure
python scripts/run-requirements-check.py --out build/fresh-requirements-evidence
python scripts/run-revision-check.py --out build/fresh-revision-regression
build/win-integration/Release/banjo_workshop.exe --workspace build/fresh-requirements-capture --capture build/fresh-requirements.png --capture-layout requirements --frames 30
```

The scripts require unused output folders and a configured Codex login. Raw evidence is in `build/requirements-assistant-final`, `build/requirements-revision-regression` and the preserved failed `build/requirements-assistant`. Logs: `build/requirements-final-build.log`, `build/requirements-final-ctest.log`, `build/requirements-final-capture.log`. The capture exits 0 and was inspected: all three inventory entries, retained iron block, material shortfall and disabled Build are legible.

A fresh normal workshop is running from `build/requirements-ready` (owned exec session 98011, returned window 2754672), initially paused with uncollected resources. Native state inspection and one refreshed/activated retry both fail with `foreground window did not report a process id`; no mouse/keyboard action was issued. Normal input verification remains pending. The prior owned session 96638 was intentionally stopped to relink, preserving its workspace; Ctrl+C exit 1 is not normal-exit evidence. The separate main laboratory was left untouched.

## Next application work and retained limitations

1. Standardize versioned command/result/error/receipt contracts, world identity/revision, retry semantics and durable acknowledgement. Assessment is a current read-only view; it is not a durable quote or reservation. Existing ordered batch partial success and step retry limitations remain.
2. Add explicit energy-store and inventory reference states, tool/process capability and work/power limits, then combined material/energy/object transactions. Unknown cost remains unknown. More stock must never bypass a missing process.
3. Add bounded isolated physical tests with measurable success criteria and assistant feedback, then a simple supported assembly through the same interface. A recipe that compiles may fail its intended job.
4. Verify new controls through normal input when native inspection works. Persist pending proposals if they must survive restart; currently accepted worlds and provider exchanges are saved, but the live UI draft is not a saved-world entity.

Further geometry, multi-material composition, general construction/mining, calibrated wood/metal/fracture behavior, energy-paid manufacturing, network service/SDK, publishing and multiplayer remain open. Keep glass, oak and iron in every expanding material-dependent regression set and retain the full physics gates.
