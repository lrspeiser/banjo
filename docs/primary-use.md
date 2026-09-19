# Primary Use programs

Contextual placement and saved interaction points: [contract](placement-and-interaction-points.md).

September 19, 2026. MCP 1.5.0; native ABI 25 is unchanged.

Every finished product should have one purpose-specific **Use** program. Left
mouse or **J** uses the held product first, otherwise the product under the
crosshair. E retains pickup/put-down and the contextual menu. The first mouse
click with no held object captures the view; J also works without pointer lock.

The LLM writes bounded data during authoring. Pressing Use runs the saved
program against the current world, without an LLM request. Names, construction,
program, physical state and presentation are separate: opening Workshop does
not make a motor run or create energy.

## Room authoring and execution

Call `offer_actions` with `primary: true` on exactly one action:

```json
{
  "world_id": "WORLD",
  "name": "cart chassis",
  "actions": [{
    "label": "Push cart forward",
    "primary": true,
    "steps": [{"do": "push_forward", "distance_m": 0.4, "speed_m_s": 0.4}]
  }]
}
```

All existing checked action steps remain available, including `drive` on a
real motor, `turn` on a hinge and `slide` along a slider. The primary flag is
saved with the room and survives the authoring adapter's export/reopen. At most
nine programs per body and twelve steps per program; duplicate primary
declarations are refused atomically. For compatibility, the first offered
action becomes primary when none is marked. An object with no program has a
read-only Inspect fallback; this is not certification that its intended
machine function is implemented.

Four additional steps are available:

| Step | Preconditions | Bounds and effect |
| --- | --- | --- |
| `inspect` | Body exists | Read current body state; no physical act |
| `place` | This body is already held | Resolve nearby receiving points or ground, carry with the bounded hand, recheck actual arrival and release; [placement contract](placement-and-interaction-points.md) |
| `strike` | This body is already held | Hand travels along current look direction, then returns to its starting grip; distance 0.05–0.8 m (default 0.35), speed 0.1–5 m/s (default 3) |
| `push_forward` | Empty hand; body unanchored and within 3 m | Hand pushes along the person's horizontal facing, then releases; distance 0.05–1.5 m (default 0.4), speed 0.1–1.5 m/s (default 0.4) |

These are native bounded-hand strokes using existing contact physics, not
teleports or velocity assignments. The current executor uses the existing
800 N hand, 2 m/s² stroke acceleration and 0.05 m lead. Maximum requested
stroke speed is not a promise the object reaches it. Forward displacement
below 0.02 m reports refusal. Strike reports the stroke outcome rather than
claiming an unmeasured hit, break or successful manufacturing operation.
The held tool remains held after a strike. Actions cannot overlap on the hand.
Motor steps retain their battery, torque and brake limits. The hand supplies
external work; a hand-pushed cart is not self-powered.

HTTP execution reuses `POST /api/world/action`:

```json
{
  "session": "LIVE_SESSION",
  "object": "cart chassis",
  "primary": true,
  "person": {
    "standing_m": [0, 0, 2],
    "eyes_m": [0, 1.65, 2],
    "facing": [0, 0, -1],
    "look_direction": [0, 0, -1]
  }
}
```

The server selects the saved program. It does not accept a replacement
program in the Use request. Normal session and CSRF checks still apply.
Existing zero-based `action` indices and built-in selections remain supported.
Responses use `action`, `done`, `did`, `refused` and `holding`.
The browser continues advancing simulation during gestures.

MCP `use_action({world_id, name, primary: true})` selects the same primary.
Through room chat it uses the running browser world. In the standalone MCP
world, inspect and drive are available; hand programs are explicitly refused
because that tool does not own the browser person's hand. Existing explicit
action labels or one-based numbers still work.

## Workshop and ProductGraph

Workshop stores a portable program under `parameters.primary_use`:

```json
{
  "kind": "table",
  "parameters": {
    "primary_use": {
      "label": "Push forward",
      "steps": [{"do": "push_forward", "distance_m": 0.3, "speed_m_s": 0.4}]
    }
  }
}
```

The Workshop chat's `program_use` tool authors this declaration. The same
parameter is accepted by the published Workshop API/MCP candidate operations
and pure Workshop agent `change_parameters` operation. It survives rebuilding,
component edits and library serialization. ProductGraph and PhysicsContract
carry a `controls` entry with `kind: "primary-use"`, `binding: "primary"`,
`programmed` and `program`.

The portable Workshop subset is inspect, strike, push_forward and place,
referencing the product itself. Mixed held-strike/empty-hand-push programs,
unknown executable steps, non-finite numbers and out-of-range parameters are
rejected. Both lattice and precise-rigid installation map the program to the
installed root body. Old candidates without a declaration receive Inspect;
their graph says `programmed: false`. Room chat still refuses authoring edits
to precise-rigid rooms, as before.

A cart's declared Use does not add missing wheels, bearings or an engine.
Workshop's articulated installation limitations remain in force. Room-authored
machines can use the richer existing action DSL. General controllers,
arbitrary drivetrain installation, cancellation of multi-step programs,
damage qualification and full-world energy closure are not established by
this control feature.

## Evidence

`tests/actions_tests.py` covers saved primary selection, export/reopen,
validation, Workshop graph/contract/edit preservation, the LLM programming
tool, bounded forward requests, blocked/out-of-reach refusal, repeated strikes
without release, and overlapping-Use refusal. Its HTTP hand stand-in verifies
dispatch and outcomes, not a new constitutive law.

`tests/workshop_install_engine_tests.py` also exercises a saved program on an
installed body with real native stepping, and checks room-store round trip.
The existing material and installation regressions remain separate from this
source/control assessment.

Browser check: an isolated oak object on a pedestal was pushed using J; the
server reported 0.21 m forward displacement and stroke reached. The hint showed
Left mouse / J and the saved label. No console errors. The first oversized test
fixture was rejected by the scene cell cap and replaced with a validated smaller
fixture. The broad native/browser discovery run was stopped in favor of focused
native installation and connected-browser checks.
