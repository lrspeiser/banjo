# Mixed-tool draft preservation — October 1, 2026

## Implemented

Lab component edits retain the requested material. Check it, Recipes readiness,
physical buildability and the paid Make quote share a read-only fixed-lattice
material guard. A refusal identifies the components/materials and retains Save
as an available action. The visible Lab notice is a short name/value summary.

The automatic fitter no longer changes iron members to oak (or the reverse) to
pass a single-material compiler. It refuses before resizing or moving a mixed
fixed group. The ordinary mixed cart therefore reports its unsupported joints;
the dimensional/bearing/control regressions explicitly choose an all-oak fixture.
Exact rigid machine constituent allocation and separately moving bearing groups
retain their distinct supported paths. No automatic rigid conversion or invented
bearing is used to bypass a ground tool's fixed connection.

Workshop model instructions now require applying the requested edit, inspecting
and checking it, explaining the named joint blocker, and allowing the draft to
be saved. Material alternatives require an explicit user choice. Saving a design
is not evidence that it can be manufactured or used.

Sources: [material guard](../mcp/workshop_material_support.py),
[fitting](../playground/workshop_fitting.py),
[model tools/instructions](../playground/workshop_chat.py),
[buildability](../mcp/workshop_buildability.py),
[quote](../playground/fabrication_room.py) and
[Lab display](../playground/workshop.js).

## Verification

Actual Chrome, fresh generated seed 4 and its normal empty workbench: take/stow
the native Field pick, open it in Lab, click its head in the 3D view, type a local
chat material edit, Save, reload the saved draft, then press Make. The saved draft
retains `arm: iron` and `haft: oak`; Make returns the actual HTTP 400 joint reason.
The original complete parked native pick, rack, process energy, stock and jobs
remain unchanged. The visible geometry shows both constituents. There are no
browser JavaScript exceptions. This uses zero provider calls; it does not qualify
a live model's judgment.

Fixed fabrication QA: **69/69 pass in 108.618 s**, including the new browser case,
paid glass/oak/iron mass/work comparisons, funding, unchanged damage, output use,
private ownership, save failures, retries, restart and native machine use.
[Retained measured evidence](evidence/mixed-tool-draft-checkpoint.json) records
base `36093ba` plus dirty source hashes and unchanged native runner/library hashes.
The existing experiment conditions and tolerances are retained, including native
`dt=1/240 s`; no native solver, material, force, overlap, thermal law or ABI changes.
Local process accounts remain local accounts, not full-world conservation proof.

The fitting tests now require a mixed 12 mm iron pin to remain iron and 12 mm
when lattice fitting refuses; the separate exact-rigid test still admits that
geometry and material. The matched glass/oak/iron head diagnostic preserves source
and sampled material identity. These are admission tests, not physical joint tests.

Workshop fitting/chat/buildability/recipe regressions: **98/98 pass in 28.599 s**.
The older direct recipe authoring journey now explicitly selects its legacy
process fixture; normal finite-workbench funding is covered by the fabrication
lane. Python compilation, JavaScript syntax, source registration **287/287** and
changed-file whitespace checks pass. Windows browser teardown may emit an
existing connection-aborted trace; the test outcomes above are successful.

## Remaining work

R2 stays open: implement and qualify a native fixed metal/wood interface, its
constituent mass/inertia, applicable mechanical law and damage/state persistence,
then run paid modification → Save → Make → pickup → native use in normal worlds.
R1–R6 and the full fourteen player requests remain active. This checkpoint fixes
design substitution and makes its capability boundary reviewable; it does not
claim mixed-material tools now work in the World.
