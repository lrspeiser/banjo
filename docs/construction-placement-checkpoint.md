# Inventory placement and saved construction intent

October 3, 2026. Based on published main `f14c346`, following the
[foundation and guidance checkpoint](construction-guidance-checkpoint.md).
Verified implementation published to GitHub main as
`de19d60c` (October 3, 2026). Publication evidence includes the 47 focused
checks, source registration and 1,267 valid local documentation targets.
The full 14-item construction goal remains active and unfinished.

## Implemented

- Physical Hands/bag Inventory thumbnails offer **Place → World**. A saved
  design must first become a physical item through ordinary paid manufacture.
- The World shows one selected-item card: Hold, Choose supported spot, Place,
  Check settling and access. Its current action precedes the optional AI tip.
  These four placement steps do not implement the complete preparation,
  supports, platform, mounting, access and operation project sequence.
- [Construction projects](../playground/construction_projects.py) persist
  private world/player/scene selection and checked site in SQLite. Versioned
  writes retain up to 64 exact request receipts. Stale revisions, reused IDs
  with changed intent and another player's carried item are refused. Retrying
  an accepted intent after movement or restart returns its original receipt.
- Find supported spot checks at most nine nearby candidates through the
  existing native placement preview. Candidates must fit, have at least three
  supported corners and avoid the preview's tipping warning. The existing
  three-metre hand reach remains authoritative. **Another location** must
  choose a different spot, at least 0.2 m away, or report no new site.
- The ghost includes the checked object's actual joined parts. A footprint
  and short **Place here** label remain visible at night and while using the
  sidebar. Looking elsewhere does not silently change a saved site.
- Confirmation rechecks current ownership, held body, reach and native
  placement. It uses the existing bounded native hand operation. A failed
  explicit target keeps the item held instead of silently dropping it elsewhere.
  No scene pose assignment, free resource grant or new native law is added.
- Ordinary successful placement saves the world. Reload resumes the project;
  observed placement explicitly leaves settling, access and operation checks
  outstanding. Inspect opens the existing component thumbnails.
- [Shared guidance](../playground/player_guidance.py) and AI observations
  expose the same selected physical project. Proactive Luna advice receives
  its current status, steps, installation declarations and blocker. Market
  does not mistake a placement project for a purchase/manufacturing quote.

## Verification

Windows 11, Python 3.13, VS 17 x64/MSVC 19.44.35228; existing Release native
build `build/agent-column-terrain`, Lab disabled. Native sources, binaries and
material/contact/water laws are unchanged. Tests use ordinary native stepping
at dt 1/240 s. No new constitutive or conservation qualification is claimed.

| Check | Result |
| --- | --- |
| New construction project suite | 4 pass, final direct run 11.656 s |
| Registered `banjo_construction_project_tests` | 4 pass, 11.27 s before final held-body identity refinement; final direct suite retested that refinement |
| Proactive, shared guidance and AI controller boundaries | 27 pass, 34.268 s |
| Existing placement context suite, direct | 16 pass, 3.780 s |
| Source registration | 298/298 sources, 10 CMake files, zero omissions |
| Changed JavaScript ES module syntax and diff whitespace | Pass |

The 47 unique focused checks include bounded read-only suggestions, another
site, peer privacy, exact intent replay/restart, shared human/AI observation,
reach invalidation, failed-target retention and actual camp-light placement
on fresh smooth and column worlds. Native body tables and saved project
state survive full Python/native restart. Test fixtures supply an existing
starter light and initial surveyed player pose; this is not a paid gathering
or unaided opening benchmark. The AI observes construction state but its
controller does not yet execute the complete construction sequence.

The isolated ordinary browser on port 8779 verifies picking up the camp light,
Inventory thumbnail → Place → World, night ghost/footprint, Another location,
Place here, reload and Inspect placed item. The light leaves Hands/bag and
appears in the world; inspection shows its iron foot, iron bracket and glass
globe. The actual Luna milestone tip asks to check settling, access and
operation. Cursor mode preserves the selected preview. This is agent-operated
UI evidence, not the required unaided human usability gate.

Local ignored artifacts: `build/construction/placement-journey.json` and
`build/construction-preview/placed-light.png`. No credentials or private
authentication tokens are committed. The preview still reports an unrelated
rover dry-route refusal; this checkpoint does not close broader R4 hauling.

## Boundaries and next checkpoint

Native fit/support preview is not soil bearing, concrete curing, strength,
bending, grain/plasticity or attachment-failure certification. The existing
glass/oak/iron/concrete foundation comparison retains its measured limits;
no material law or tolerance is changed here. Advanced clearance, ports and
skills remain declarations pending construction-planner enforcement.

Intent writes have exact receipts. Physical placement currently recovers an
uncertain reply by checking the actual native hand/project; complete shared
world mutation receipts, terrain/resource conflict and depletion coverage
remain required. Observed release is not proof of settled operability.

Next implement ordinary paid ground preparation and the complete saved
construction step sequence, then functional supports/mounting and earned
skills, then broader bounded customization. Repeated-failure AI events,
routine-edit routing/escalation, wider site qualification and unaided
human/model journeys remain open. The previous six-call Luna p95 of 2.81 s
still exceeds the two-second target. R3 remains separately paused.
