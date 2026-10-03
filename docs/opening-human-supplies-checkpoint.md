# Ordinary opening and simpler supplies — October 3, 2026

Verification base: `33c377e` plus this outgoing checkpoint, Windows,
Python 3.13, Node 22.18.0, existing MSVC Release binaries under
`build/agent-object-strike/Release`. Publication is recorded separately.
Native sources, binaries, laws and physics tolerances are unchanged. The
full [owner scope](readable-world-plan.md) remains active; R3 stays paused.

## Ordinary browser evidence

An isolated default generated world on port 8774 started with an empty human
inventory and zero wallet energy. All interaction used the in-app browser's
visible controls. No browser state writes, free grants, teleports or hidden API
calls made this journey. The native rover used the reflex decider; this is an
automated human-interface walkthrough, not a live-model autonomy claim.

1. Follow Get wood, walk to the finite oak pile from 18.5 m away, and collect
   25 kg into personal stock. The pile decreases by 25 kg.
2. Follow the personal pick recipe, fund its actual 1.925 kg oak / 192.5 J
   quote, start manufacture and collect the physical output into Inventory.
   Shared oak stays at 12.4 kg; personal oak becomes 23.075 kg.
3. Equip through number key 1. A complete host-process restart retains the
   paid tool, stock and private player identity.
4. Follow the surveyed dry-ground target and use J. The native stroke loosens
   about 1 litre of sand, reported in Inventory as 1.55 kg. Gathering by hand
   becomes Learned, and all three first-tool goals are Complete.
5. Study the selected held pick through its declared Study tool action. The
   native inspection is saved and guidance advances to a work surface.
6. Review Work table: 6.3616 kg oak, 636.16 J, minimum 1.27232 s. Prepare supplies
   takes personal wood. Its first energy attempt exposes a live-meter race;
   after the bounded transaction fix and restart, preparation completes from
   retained balances. Start make and Add to Inventory succeed. The owned table
   receives slot 2; private wood is 16.7134 kg, shared oak is still 12.4 kg.
7. Another full process restart retains the pick, table, sand and learned skill.
   Guidance points to equipping the existing table rather than funding a
   duplicate. Equip slot 2, then E places it through native world controls.

The screenshots are ignored artifacts under `build/opening-human-1003/`:
wood collection, paid pick readiness, the original stale-guidance defect,
first dig, completed first-tool checklist, compact supplies, funded table and
physical table Inventory. No screenshots or local save data are committed.

Read-only durable ledger inspection finds two installed paid jobs, zero Market
orders and zero deposits. Combined receiving is 8.2866 kg oak and 828.66 J.
The fabrication audit reports oak residual 0 kg, native transfer residual
−8.3844e−11 J, meter residual 3.2571e−11 J and work residual −1.1369e−13 J.
These are the existing stock/workpiece/station transfer boundary, not total
world conservation. Native glass/oak/iron funding comparisons below remain.

## Changes motivated by the journey

- Paid browser candidates carry a preview generation counter. Guidance's
  persisted selection omits it. Compare authored design fields, retaining exact
  ownership, prior-job and physical-input checks, so accepted work clears intent.
- Prepare supplies sequences the existing durable stock/goods/charger routes.
  It checks the whole available supply path before starting, uses private stock
  first and displays any shared-stock use. Manual controls remain in Supply
  details. Each click has at most 32 operations and five native charging seconds.
  Lost acknowledgements retain the exact pending request; they stop later work.
- Energy sources expose a prefixed binding hash for identity, body, capacity,
  voltage and power rating. The selected source's runtime charge counters may
  advance. Under the world lock, transfers still require current charge,
  station revision, actual elapsed native time and power shared with other loads.
  Exact before/after meters and the receiving receipt save together. Legacy
  full-meter hashes retain their strict stale-meter refusal. Only known pre-debit
  meter refusals get up to three refreshes; uncertain receiving failures do not.
- Selected products expose their declared native actions alongside component
  thumbnails. This makes Study available while the pick's main input digs and
  uses the same action contract for future authored items.
- A paid carried surface receives an equip/place recommendation. The existing
  native goal predicate credits an unparked held surface before placement;
  that premature goal award remains a limitation. The walkthrough still
  places the table through E. This checkpoint changes no goal predicate.

## Verification and boundaries

```powershell
# Set BANJO_LIVE_ENGINE/BANJO_LIBRARY/BANJO_BUILD_DIR to the Release directory.
python -m unittest discover -s tests -p fabrication_energy_tests.py -v
python -m unittest discover -s tests -p game_guidance_tests.py -v
ctest --test-dir build/agent-object-strike -C Release -R '^banjo_workshop_supply_tests$' --output-on-failure
node --experimental-default-type=module --check playground/workshop.js
node --experimental-default-type=module --check playground/world.js
python scripts/check-source-registration.py
git diff --check
```

Energy: nine checks pass, including actual meter advance, identity/rating
refusal, current depletion/shared power, exact debit, save failure, retry and
reopening. The existing matched glass/oak/iron products draw 1000 J each;
energy/work residuals remain at most 9.095e−13 J. No tolerance changes.
Guidance: eleven checks pass, including exact browser generation fields,
private selection, paid readiness, seven help screens and carried-surface
ownership/geometry boundaries. Six Node cases cover the shipped planner and
orchestrator with controlled transfers; those mocks do not qualify native
manufacture. CMake registers this suite. Source registration stays 297/297,
ten CMake files, zero exclusions. Captured browser JavaScript errors are zero.

An additional legacy surface journey fails at its free-authoring preview,
which is refused in funded worlds. A temporary conversion to actual gathered
wood and the paid API reaches its surface goal but fails the camp-stool
receiving trial with “no clear receiving point or ground in front,” including
a larger table. Those exploratory fixture changes were removed. The original
test remains intact and unqualified; it is not counted among the 26 passing
checks. No receiving/goal law or native source is published here. Investigate
that physical gate separately and preserve the test's intended functional
trial. The compact opening table is not certified as a camp-stool receiver.

The actual fresh browser next step remains blocked at processing/skill
guidance. Broader empty-input/source/processor coverage, live-model play and
custom LLM products are unfinished. Technical restart messages, raw action
results and duplicate template names still need presentation cleanup. This
does not qualify native avatars, water reactions, cargo inertia, night material
recognition, broader hauling routes or the owner-paused repair effort.
