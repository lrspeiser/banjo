# Placement and interaction points

September 19, 2026. MCP **1.5.0**; native ABI **25** is unchanged.

A held loose object shows a translucent destination before placement. Nearby
valid receiving points attract it; otherwise it rests on reachable ground one
metre in front of the person. E and the contextual drop/put-down action commit
the preview. Green means supported, amber warns about limited support or a tall
thing on a slope it may fall over on, and red means blocked. Esc dismisses the preview and keeps hold. Primary Use retains
the product's saved function; a product programmed with `place` commits the
same destination.

The resolver considers receiving points in front, within three metres of the
eyes, and within 1.25 horizontal metres of the ground fallback (or on the
aimed body). It prefers aimed receivers, then distance and stable identifiers.
It checks at most eight candidates. Capacity, upright receptacles, native
collision geometry and support all matter. Occupied or undersized receiving
areas do not become free inventory slots.

## Authoring

World MCP and world chat expose `define_interaction_points`:

```json
{
  "world_id": "WORLD",
  "name": "cart",
  "points": [{
    "id": "cargo",
    "label": "Cargo bed",
    "kind": "container",
    "position_m": [0, 0.2, 0],
    "size_m": [0.7, 0.6, 1.0],
    "yaw_deg": 0,
    "max_mass_kg": 30
  }]
}
```

Positions are body-local metres from the **centre of mass**. A receiving
position is the centre of its supporting floor, not the centre of empty space.
`size_m` is usable width, height above the floor, and depth in body axes;
`yaw_deg` aligns the item relative to those axes. `max_mass_kg` is an optional
admission limit, not a strength rating. Kinds are `grip`, `use`, `surface`
and `container`. IDs are unique, 1–60 characters (`ground` is reserved); labels are 1–80 characters;
there are at most 32 points including the required grip/use defaults.
Coordinates and dimensions are finite and bounded to 100 m; receiving sizes
must be positive, yaw is −360 to 360 degrees, mass is 0.001 to 1,000,000 kg.
Unknown fields and invalid declarations are refused before replacement.

Omit `points` to read. Supply a list to replace the object's declarations.
Grip and use defaults are added when omitted. They are semantic anchors;
specialized blade/bow/pick grip physics retain their existing profiles.
Receiving declarations do not create collision surfaces, cavities, powered
motion, joints, or container contents.

Workshop uses `parameters.interaction_points` with the same point schema,
but positions are in the **design coordinate frame**. Its LLM also has
`define_interaction_points({points})`. Template decks, tops and seats derive
receiving points from their geometry. Authors must update custom coordinates
when changing geometry. ProductGraph and PhysicsContract carry these in an
`interaction-points` control record; installation converts to the actual
installed centre of mass. Both precise rigid and lattice adapters preserve
them. Saved rooms carry `interaction_points: [{body, points}]`; legacy objects
gain grip/use defaults.

## Preview API and execution

`POST /api/world/placement` is read-only and requires the current session:

```json
{
  "session": "LIVE_SESSION",
  "name": "crate",
  "person": {
    "standing_m": [0, 0, 2],
    "eyes_m": [0, 1.62, 2],
    "facing": [0, 0, -1]
  },
  "yaw_deg": 0
}
```

The answer includes `fits`, `why`, `at_m`, `facing`, `on`, `onto`,
`supported_corners`, `tipping_used`, `may_fall_over`, `label`, and
`target: {body, id, on, yaw_deg}` when a destination exists. `tipping_used` is
how far the slope under a thing taller than it is wide goes towards tipping it
over (1 is where it would; 0 when it is not asked); past 0.5 `may_fall_over` is
true and the preview is amber, past 1 it is refused. `at_m` and `facing` set the
thing down square to what its underside would rest on -- the plane through the
highest ground around its middle, under its whole footprint -- up to 45
degrees of it, its middle over the point: set down upright on a slope, a tall
thing swings onto it and over. The engine's `place_check` takes `square: false` to keep it
upright, which is how each part of a thing of several parts is asked. The hand
lets go only when the thing is that square and still, to within a share of
its tipping angle that shrinks as the slope uses more of it. No destination
returns `fits:false` with a reason.
Optional `expected` accepts the prior `target` and checks that same destination.
It never silently substitutes another receiver on confirmation.

A saved primary program can use `{"label":"Place gently","steps":[{"do":"place"}]}`.
This requires the product already held. `POST /api/world/action` accepts the
optional `placement_target` from its preview; the saved Place step uses the
same resolver. Without one, it resolves the current destination. As with other
hand programs, the host must keep advancing the world while execution runs.
The standalone world MCP can author this program; its `use_action` still
reports that hand programs run in the live playground, rather than pretending
to execute them in a separate world.

The UI and saved Place executor lift, carry and lower using the existing
bounded native hand. Collision can stop the movement. The receiver is checked
again before movement and release; a shift greater than 3 cm or rotation
greater than 2 degrees invalidates confirmation. Actual arrival and orientation
are checked before release. Obstruction, excessive weight or a moved target
leaves the object held. The hand supplies external work, as with other hand
actions. This is a local placement check, not a global path planner.

## Boundaries and verification

This adds interaction metadata and physical placement coordination, not
general fluid containers or articulated-cart installation. Existing specialized
tool controls and explicit legacy `carry_to`/`put_down` programs retain their
handling; new contextual placement programs should use `place`. Expedition
resource accounting remains on its separate gameplay panel.

Tests cover validation, Workshop graph/contract mapping, local-frame rotation,
capacity, obstruction, stale targets, ground fallback, native support geometry,
and a saved Place program moving an actual native body. This checkpoint is
adapter/control verification, not a fresh full-engine qualification.

Verified on Windows with the Release native engine (ABI 25): 13 contextual
placement tests, 18 native installation tests, 18 precise-rigid live tests,
the native placement target (including self-excluded support rays), 36 action
tests, 68 world MCP tests, 17 chat/MCP parity tests and 9 API-doc tests passed.
Workshop discovery ran 296 tests: 252 passed and 44 environment-gated cases
skipped; native installation was run separately. All 275 C++ sources are registered.

Browser verification showed the green ghost inside a compound cargo bed before
input. J, E and the inventory Put down button each placed and released the
9.68 kg oak parcel into the same destination, with no console errors. Native
installation anchors were compared against full-precision saved COM poses,
not the rounded UI pose values. Precise-rigid admission now permits validated
core gestures; heat, mechanisms and the richer action DSL remain excluded.
