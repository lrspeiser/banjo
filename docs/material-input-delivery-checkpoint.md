# Personal material delivery to machine inputs — October 2, 2026

## Implemented

Select a processing machine in World, stand within 2 m of its input hopper and
choose **Load from Inventory**. The right panel shows accepted material
thumbnails, personal quantities and **Load 5 kg** (or the available smaller
amount). Input piles also show this panel. Stationary controller selection now
matches its declared body even when the native program has no `parts` list.

The input contract is derived from the machine's current declared recipe,
including supported authored/saved machines with the same routine. It accepts
only that authenticated player's material/product rack stock. Shared stock,
other players' balances, unsupported inputs and distant/airborne delivery are
refused. Bounds are 1 microgram to 25 kg per request, whole micrograms, at most
2048 delivery reservations/receipts per scene. The existing goods ledger uses
six-decimal kilogram quantities.

SQL commits a source debit and reservation before changing the hopper. The
hopper and receiving receipt then save together with the complete native world
and machine runtime. Settlement marks the reservation applied only after this
checkpoint. Receipt identity includes scene, request id, owner, pile and exact
goods. Save failure retains the reservation/live receiving receipt; retry
cannot debit or load another copy. A receiving exception restores the old
hopper while retaining the source reservation.

Inventory shows reserved input materials as thumbnail/quantity cards with
**Finish delivery** and **Return to Inventory**. Return checks both live and
durable receiving receipts, so a successful save with a lost acknowledgement
cannot refund delivered goods. An unapplied reservation survives restart and
can retry near its input or return exactly once. Fabrication saves and native
installation preserve delivery receipts and their durability markers.
The UI offers Return only for unreceived reservations; pending receiving saves
offer Finish. The server independently checks durable receipts on every return.

The short delivery transaction holds its world's exclusive lease/state lock;
ordinary simulation/input requests retain their existing locks. Receipt
settlement uses one SQL transaction for the saved batch. No native material
law, solver setting or physical conservation tolerance changes.

## Bounded HTTP contract

Authenticated requests use the current world session:

```json
{"session":"current-session","action":"view","pile":"smelter intake"}
```

`POST /api/world/goods/deliver` view returns recipe-accepted `inputs` with exact
personal `mass_kg`, plus that player's `pending` reservations. Delivery uses:

```json
{"session":"current-session","pile":"smelter intake","substance":"copper ore","mass_kg":5,"request_id":"unique-delivery-id","person":{"eyes_m":[0,1.62,0],"facing":[0,0,-1]}}
```

Use the actual surveyed player position, not the example coordinates. Reuse
the same request id and quantity on retry. `action: "release"` requires the
reservation's request id and refuses once any receiving receipt exists.
`/api/workshop/inventory` includes `delivery_reservations` for recovery.
LLM-authored machines must declare a supported recipe/routine and actual input
and output stockpiles; a material name alone supplies no processing law or stock.

## Verification

Windows / MSVC Release CPU runner from `fa84f14`, native library from the
preceding storage build, separate `build/agent-object-strike/Release`. Host/UI
changes only. Source registration 297/297; Python compilation and both changed
JavaScript syntax checks pass.

- Three actual HTTP/native/Chrome input checks pass in 20.472 s. A finite
  generated 20 kg starter-ore pile is collected privately, 5 kg is delivered,
  existing processing produces 1.5 kg copper, and collection/restart retain
  15 kg ore plus 1.5 kg copper for the player and zero for the peer. Tests cover
  inappropriate inputs, quantity/reach refusal, disk failure, retry, mutation
  followed by exception, reserved-source restart/return, and lost save ack.
- Chrome clicks the real loading controls, reads the material thumbnail and
  remaining 15 kg, then returns an unreceived reservation through Inventory.
  No browser runtime exception. Screenshot:
  `build/resource-flow/personal-input-delivery.png`.
- The full fresh-world rover → ore → personal input delivery → processing →
  private copper → saved lamp → paid Make/Use → full server restart passes in
  141.534 s. Delivery retries after processing/restart add no new input.
- Nineteen related tab/library and output-collection/SQL-failure/private-stock
  regressions pass in 35.275 s. Logs are `r1-input-final.log`,
  `r1-input-regression.log` and `material-build-lamp.log` under
  `build/resource-flow/`. Browser closure may log an aborted outstanding HTTP
  response; that is separate from the checked browser runtime and transfer state.

This qualifies declared ledger processing and its player transfer/persistence
route. Hopper/cargo mass, collision, heat transport, chemical yield and native
processed constituent incorporation remain unmodeled or separately bounded
under R5. Manual withdrawal of a stocked input uses the existing explicit
collection API; automatic collection still protects inputs. No new player
pickaxe ore-extraction method is advertised. Preview servers are unchanged.

## Remaining R1

Finish player-facing raw storage, supported ground-to-usable-stock routes,
exhausted-input guidance and legacy unassigned-load recovery, then audit the
complete built-in/saved-design supply loop. R1 remains active; R3 is paused.
