# Selected projects and design-chat guidance

October 3, 2026. Published implementation: `79b3b41` on GitHub main.
Verification base: published `2312c77`, plus the host, authoring and UI changes.
Full owner scope remains active.

## Implemented

Selecting an owned carried item, recipe, saved design or library design in Lab
sets a private project focus. A bounded design proposal is retained in SQLite
within a 24 KiB authoring budget (the HTTP envelope retains its 32 KiB limit)
by world, authenticated player and scene. Navigation and server restart retain
the focus. Follow goals and Clear Lab remove that intent without changing
materials, wallet, skill evidence or saved designs. This record is neither a
stock reservation nor a manufacturing receipt. Saved/library navigation still
uses the existing catalog permissions; a supplied source label grants no item
access. Carried selection requires the authenticated player's hands or bag.

World, Workshop tabs, Market and AI Guide read the same focused resolver.
Readiness uses the exact paid manufacture quote, including station-funded
stock, physical energy and processed goods. Market estimates only remaining
purchases; it does not recommend buying stock already funded at the station.
An accepted owned running/paused/ready workpiece takes priority and shows its
actual candidate, rather than attaching its progress to an unrelated recipe.
New matching owned work reconciles the earlier project intent; choosing an
additional copy explicitly remains possible. Browser recovery of pending work
does not silently reselect that paid job as another unfunded project.

The bounded design assistant receives an authenticated current-candidate
snapshot and a read-only `inspect_game_guidance` tool. After editing it can
recheck the actual draft quote. A separate `draft_project` reading distinguishes
the isolated draft from a pending accepted workpiece. Model arguments cannot
supply balances, skill completion or stock. No-key funding/next-step questions
also read the resolver. Neither this tool nor project selection funds a build,
changes the physical original or awards evidence.

Named components and whole-design requests pass the UI's ambiguity check.
Live verification exposed an existing authoring bug: longer handles used the
local y dimension even when the handle's long axis was x. Handle/tool-head
length edits now follow their longest local dimension; thickness edits change
the other two dimensions. Existing anchored leg/post behavior is retained.
Centers are retained for handles/heads; arbitrary shortening can still lose
contact or invalidate a grip and must pass the ordinary admission/functional
test. This is geometry authoring, not a new material or contact law.

## Verification

Windows, Python 3.13.5, Node 22.18.0, existing MSVC Release engines in
`build/agent-object-strike/Release`. Native source, binary, dt, material law and
solver tolerances are unchanged. Exact occupied-geometry quotes are not
continuous wireframe BOM estimates; quote readings now carry product mass,
cell size and occupied-cell count when available. Chat instructions explain
the distinction and keep legacy library credits separate from game energy.

```powershell
# Set BANJO_LIVE_ENGINE/BANJO_LIBRARY/BANJO_BUILD_DIR to the Release directory.
python -m unittest discover -s tests -p game_guidance_tests.py -v
python -m unittest discover -s tests -p workshop_chat_tests.py -v
python -m unittest discover -s tests -p workshop_components_tests.py -v
python -m unittest discover -s tests -p workshop_component_api_tests.py -v
python -m unittest discover -s tests -p workshop_component_template_tests.py -v
python -m unittest discover -s tests -p world_goods_tests.py -k saved_withdrawal_recovers -v
node --experimental-default-type=module --check playground/workshop.js
node --experimental-default-type=module --check playground/player_guidance.js
node --experimental-default-type=module --check playground/world.js
python scripts/check-source-registration.py
git diff --check
```

- Ten guidance cases pass in 19.986 s. New cases cover private durable focus,
  actual quote changes, Market agreement, invalid/oversized/nonfinite inputs,
  source ownership, clear/restart, and current design-chat observations after a
  bounded model edit. The provider is mocked for those deterministic boundary
  checks; quote/state/native world operations are real.
  An oversized refusal fixture initially exceeded the HTTP envelope and could
  receive a Windows connection reset before its intended error response. The
  proposal budget now leaves room within that unchanged transport bound and
  the fixture exercises the authoring refusal through an ordinary 400 response.
- The finite wood and solar paid Make case still passes and reconciles focus
  when its matching job starts. A concurrently edited draft retains its own
  exact quote while guidance follows the accepted workpiece. Seven AI Guide
  screen snapshots agree; no wallet deposit is required. Reads do not fund or
  allocate new reviewed plans.
- 38 existing chat tests pass in 0.354 s, including current inline-script CSP
  hashing, bounded edits and refusal/retry behavior.
- Seven component tests pass in 0.019 s. The new same-geometry glass/oak/iron
  authoring case checks local axial/transverse dimensions and reproducible
  reopening, with no claim of comparative strength or physical realism.
- Seven component API cases pass in 0.626 s and three canonical template cases
  pass in 0.001 s. The API check exposed an existing standalone-catalog crash
  while settling a nonexistent room outbox. The no-room guard now permits
  ordinary catalog authoring. The real named-world saved withdrawal/SQL-failure/
  restart recovery case still passes in 10.998 s, retaining its injected failure
  logs and exactly-once credit checks.
- Python compile, Node syntax and source registration checks pass. Registration
  remains 297/297 with zero exclusions; no tolerance changed.

Actual in-app browser, isolated owned preview on port 8773: a carried pick
opens in Lab; explicit component-name editing reaches the design assistant.
The corrected live-provider edit lengthens the haft along x and returns
2.275 kg occupied oak / 227.5 J, matching the refreshed Market project. The
carried 1.925 kg original remains unchanged. Market distinguishes stock to
buy, wallet coverage and workbench energy still to fund. Private focus and
the original pick survive the full preview-server restart, and the Lab draft
restores from this browser. No provider reply is treated as manufacture,
functional use or skill evidence. Only the owned 8773 preview was restarted;
the user's 8771 process remains running.
Follow goals updates both Market guidance panels. Evidence is ignored under
`build/shared-guidance/market-selected.png`; captured browser JavaScript errors
are zero. Injected failure logs in headless tests are separate evidence.

## Remaining acceptance

Complete broader selected custom/machine and unavailable-source routes,
including recovery when a formerly carried source has moved out of its bag,
exhausted physical energy guidance and the full supported recipe supply audit.
Selected-project intent is durable; full unsaved Lab revision history remains
browser-local until explicitly saved. Design chat retains its existing bounded
request execution; the AI Guide provider-lock-release check does not qualify
all design-edit/test provider waits as allowing independent peer simulation.

Human opening, exposed-layer/gathering/reload/peer material agreement and
recognition/performance measurements remain open. Qualify broader model-driven
tech routes and LLM-created functional items through paid actions. Reproduce
and fix hauling failures, then native colliding avatars/water and physical
cargo under [R4/R5](player-experience-checklist.md#remaining-work).

The existing mixed-tool strike/reuse failure is retained in the
[earlier guidance checkpoint](shared-guidance-checkpoint.md#existing-failed-check-explicitly-separated).
Its test/tolerance is unchanged and its full physical gate remains unqualified;
the owner-paused R3 repair effort is not resumed. This checkpoint is progress,
not completion of the [full active scope](readable-world-plan.md).
