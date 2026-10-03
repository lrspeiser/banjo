# Material-to-build wrap — October 2, 2026

The owner requested stopping at the current checkpoint and checking it into
main. Implementation `210dc93b188db1b404d981f677750d9c6e9a5a0f` and publication
record `35ac5ce` were already on GitHub main. A fresh fetch confirmed local
main and origin/main agree, with a clean working tree before this documentation
update. R1 is paused at this handoff, not complete; R3 remains paused.

## Verified checkpoint

[Personal machine-input delivery](material-input-delivery-checkpoint.md)
records the passing HTTP/native/Chrome checks, failure/retry/private-stock
coverage and complete fresh-world rover → personal ore delivery → processing
→ private copper → paid saved lamp → Use → server restart journey.
[Exact energy meters](material-build-energy-checkpoint.md) retain the solar
banking and battery save fix. These are bounded verified routes, not completion
of all raw sources or physical processing laws. Preview servers are unchanged.

The wrap reran source registration: 297/297 sources registered, no exclusions.
This handoff changes documentation only; no new simulation behavior was tested.

## Next item: personal raw-material storage

Before adding Inventory Store/Retrieve controls, resolve the ownership gaps
found in source inspection:

- The fabrication HTTP dispatch does not bind the authenticated player with
  `Live.as_actor`, while `transfer_ground` reads the session actor to choose
  the carried-ground account.
- Raw lots and return receipts retain material quantities but no player-owner
  binding. Add authorization for retrieval and request replay; preserve legacy
  unassigned provenance rather than guessing an original owner.
- `Live.as_actor` restores only its original session. Ground transfers replace
  that session, so actor lifetime must remain correct through replacement.

These are source-audit findings, not a newly executed exploit or ownership
qualification. Add actual two-player HTTP storage/retrieval, refused peer
replay, failed-save/retry and full-restart checks before publishing their fix.
Then expose compact material thumbnails, quantities and Store/Retrieve controls
in Inventory, with explicit recovery of old unassigned loads.

R1 also retains supported ground-to-usable-stock routes, exhausted-input
guidance and the broader built-in/saved-design supply audit. The current
[remaining goals](player-experience-checklist.md#remaining-work) remain R1 and
R3–R6; R2's supported paid mixed-tool route is complete.
