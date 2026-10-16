# Level and Sandbox release audit — October 16, 2026

All 34 authored level solutions passed three native runs (reference plus two
1.5 mm perturbations). Wired levels additionally passed three runs after one
second of native setup gravity. Empty setups fail or are refused because the
goal's piece is absent; each supplied wrong setup fails, with manual activation
omitted when that is the lesson. No goal, deadline or tolerance was weakened.
All five curated Sandbox examples also passed their measured demonstrations.

This is an automated solvability and interface audit, **not a timed novice
study**. The simulation seconds below are how long the physical machine takes
after starting. The novice estimates are explicitly historical October 13
interface review/solution-blind LLM estimates, not new human measurements.
The older blind probes reached 32/34 within three attempts; Catch the sun and
Turn the big wheel were unresolved. See [that assessment](level-onboarding-audit.md).
The release audit knows the authored solutions; it does not call those blind.

## What changed during this audit

* All existing visible electrical wire families now have native mass, contact,
  bending and overload pullout. Solar charging cords include both copper cores
  and resistive loss. Cords fall during setup before Try It!, without consuming
  puzzle time or stored electricity.
* Factory fitting keeps separate seats and strain reliefs at shared sockets,
  reserves future plug corridors, and avoids already fitted cords. Extra stock
  is actual coiled material. The native engine subsequently owns its motion.
* Press-deck wiring attaches at the conductive pivot; opposite heater jaws
  carry the two polarities. Panel charging cords leave the rear face.
* Knock it off and Chain reaction declare 32 V supplies to accommodate real
  wire loss. Their powder, targets and deadlines are unchanged.
* The old +30 cm marble-switch negative case could now catch the bouncing
  marble. Its replacement is a clear lateral miss; the goal is unchanged.
* Cable picking/deletion uses the actual native shape, including charging
  cords. Removing a prepared mirror also removes its optical reference.
* Picking a solid case no longer deletes a nearby wire through its touch
  padding. Older battery holders move wire jacks to the front of the pads,
  away from the falling pack's landing face. Glass/oak/iron housing checks at
  240/480 Hz all powered the lamp; electrical residuals were below 4.4e-12 J.
* The solar lift bench uses declared 200 N locking connectors on its four
  prepared load leads. At 2000 Hz the earlier 50 N return pulled out during
  floor impact. The stronger connectors retain the same native pullout law,
  goal and tolerances; the separate panel cord remains rated 50 N. See the
  [qualification and timestep limits](mechanical-cables.md#remaining-limits).
* Sandbox shows five combined examples instead of the long component-demo
  list. Saved designs remain first and all placeable components remain usable.

## Problems to consider next

| Priority | Area | Finding and suggested next improvement |
|---|---|---|
| High | Catch the sun | Historically the hardest blind placement task: move out of shade, aim the panel and wire it. Preserve the visible beam/shadow and rear socket; consider a more generous starting camera and a single suggested next action. Current native solutions and shadow/disconnection negatives pass. |
| High | Turn the big wheel | Coplanar height, radius and tooth spacing must agree. The green alignment guides and visible size choices help, but this still needs novice testing of a drag-to-mesh interaction. Passing reference runs do not establish ease for beginners. |
| High | Optical power sources | The prepared optical lamps/laser still draw from a declared store without an external physical feeder. Give those their own visible, electrically gated supply cords before claiming every power connection is physically wired. |
| Medium | Heat to release | The correct setup takes about 8.6 simulation seconds to burn the cord. Keep the temperature/charring feedback prominent; time the complete interaction with new players before reducing the wait through physical apparatus changes. |
| Medium | Cable clutter and fitting | Five-metre stock can make large service coils. Dense scenes and conservative compound bounds can still refuse a valid real-world route. Offer a clearly measured cut-to-length tool or an explicit routing waypoint, rather than silently changing copper length. |
| Medium | Impact and connector calibration | Inextensible rods can produce timestep-sensitive impact peaks at their plugs. The solar bench now uses declared locking connectors; qualify axial compliance and real connector geometry before making hardware-strength claims. |
| Medium | Water-driven mechanisms | Water opens a gate varies noticeably under the small initial perturbations. Check novice placement margins and source-opening feedback; retain actual paddle contact and the original goal. |
| Medium | Pulley/drum ropes | These still use ideal endpoint constraints rather than distributed colliding ropes. Do not describe the wire migration as replacement of every thin mechanical connection. |
| Medium | Device internals | Motor torque/back-EMF, regulated solar charging, ideal spring laws and some switch laws remain lumped models. Wire insulation damage, conductor heating/failure and strand deformation are not implemented. See [the model limits](mechanical-cables.md). |
| Medium | Performance | Heat/fracture and crowded cable scenes need hosted CPU measurements. The local example wall times below include construction/observation; they are not Render latency or a controlled hosting benchmark. |
| Low | Example breadth | Five examples cover mechanical chains, water, solar/electric power, storage and optical heating. They do not yet demonstrate every individual library part, such as wind, doors, trampolines or the catapult. Improve the five combined machines rather than adding more single-part gallery cards. |

## Per-level results

| Level | Native goal time (s), 3 runs | Solution | After setup gravity | Historical novice estimate |
|---|---|---|---|---|
| Tip the lever | 0.233–0.233 | 3/3 | — | 2–4 min |
| Spring lifts the load | 0.100–0.100 | 3/3 | — | 2–5 min |
| Mind the gap | 1.900–1.917 | 3/3 | — | 2–5 min |
| Raise the crate | 0.733–0.733 | 3/3 | — | 3–7 min |
| Find the focus | 0.017–0.017 | 3/3 | — | 3–9 min |
| Cut the cord | 0.683–0.683 | 3/3 | — | 3–8 min |
| Bounce to the target | 0.017–0.017 | 3/3 | — | 3–8 min |
| Gentle first launch | 1.083–1.100 | 3/3 | — | 3–8 min |
| Cut it down | 0.683–0.683 | 3/3 | — | 4–10 min |
| Lift with less | 3.700–3.750 | 3/3 | — | 6–15 min |
| Bounce the beam | 4.867–5.433 | 3/3 | — | 8–18 min |
| Turn the big wheel | 1.633–1.750 | 3/3 | 3/3 | 8–20 min |
| Turn the axle | 0.583–0.817 | 3/3 | 3/3 | 1–3 min |
| Light the bulb | 0.583–0.583 | 3/3 | 3/3 | 2–5 min |
| Finish the loop | 0.583–0.583 | 3/3 | 3/3 | 1–3 min |
| Limit the voltage drop | 0.583–0.583 | 3/3 | 3/3 | 1–4 min |
| Close the switch | 0.700–0.700 | 3/3 | 3/3 | 2–5 min |
| Marble turns on a light | 0.467–0.467 | 3/3 | 3/3 | 2–6 min |
| Give it power | 0.583–0.583 | 3/3 | 3/3 | 3–8 min |
| Series or parallel? | 0.583–0.583 | 3/3 | 3/3 | 4–9 min |
| Store the charge | 1.867–1.867 | 3/3 | 3/3 | 4–10 min |
| Charge in the sun | 0.467–0.467 | 3/3 | 3/3 | 4–10 min |
| Sun-powered lift | 0.550–0.583 | 3/3 | 3/3 | 5–12 min |
| Catch the sun | 2.417–2.500 | 3/3 | 3/3 | 8–20 min |
| Fill the receiver | 3.483–3.483 | 3/3 | — | 2–5 min |
| Wheel in the river | 3.883–4.100 | 3/3 | — | 2–5 min |
| Pour onto the paddles | 1.400–1.867 | 3/3 | — | 2–6 min |
| River-powered lift | 4.033–4.267 | 3/3 | — | 3–7 min |
| Water opens a gate | 2.733–4.417 | 3/3 | — | 4–10 min |
| Divert the water | 4.567–4.567 | 3/3 | — | 5–12 min |
| Up she goes | 3.350–3.367 | 3/3 | — | 3–7 min |
| Heat to release | 8.617–8.617 | 3/3 | 3/3 | 4–10 min |
| Chain reaction | 1.567–1.596 | 3/3 | 3/3 | 5–12 min |
| Knock it off | 0.804–0.875 | 3/3 | 3/3 | 6–15 min |

## Five Sandbox demonstrations

* **Sun powers the flag** — flag rises 0.1500 m. Automated wall time 5.580 s.
* **Chain reaction** — 9/9 stations; last at 21.779 s. Automated wall time 20.070 s.
* **River powers a lift** — river gate rises 0.1068 m. Automated wall time 0.539 s.
* **Charge and release** — storage retains 4.5762 J. Automated wall time 3.700 s.
* **Light, heat and gravity** — 1/1 stations; last at 5.433 s. Automated wall time 0.550 s.

## Reproduction and evidence

Run `python scripts/audit-level-release.py --engine <verified-engine> --out <directory>`.
It records the engine SHA-256, every positive/negative result and the five
example observations. `--examples-only` and `--level` support focused reruns.
The committed [JSON receipt](level-release-audit-2026-10-16.json) records this
run. Large native journals and screenshots remain in ignored `build/` folders.

The native cable target compares glass, oak and iron at 240/480 Hz with 8/4/2 cm
rods (18 sag/contact scenarios), falling loads and full-system reaction/work
receipts. Momentum and energy acceptance bounds are unchanged; this is a
finite-resolution qualification, not a continuum/material calibration claim.
The source-registration guard covers all 273 C++ sources.

The catalogue browser sweep opens all 34 levels at desktop, portrait and
landscape sizes. Focused browser checks also cover live setup gravity, wire
thickness, shared-terminal rewiring/deletion, solar connections, heater leads,
the five-card gallery and saved historical designs. Final CI and the exact
hosted test revision must pass before production promotion; publishing state
is verified separately and is not inferred from these local results.
