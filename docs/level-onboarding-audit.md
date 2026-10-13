# Level onboarding audit — October 13, 2026

All 34 authored challenges were assessed before their order changed. The table gives estimated newcomer planning/placement/retry time, measured native execution time and blind solver outcomes. No humans were recruited or timed. Native execution seconds and simulated goal seconds are separate from player completion time.

Three LLM assessors received disjoint packets with no parent conversation history. Packets included the public brief, tray, goal and exact starting geometry; they excluded hints, reference solutions, wrong placements and reference manual inputs. Each model chose its own placements and forces, with up to two feedback-based retries. Geometry assistance bypasses visual recognition and precise dragging, so successful probes are an optimistic discoverability check. Failed trials expose ambiguity, not proof of broken physics. One assessor per level is not a statistical usability study.

The initial runner inherited archived construction defaults when a proposal omitted version metadata. Those runs were excluded; the retained current runs fill defaults exactly as a fresh UI piece does. Original packets/proposals remain in the ignored local `build/onboarding-audit` directory. The [machine-readable audit](level-onboarding-audit.json) records hashes, observations and per-attempt receipts without publishing answer placements. [The runner](../scripts/audit-level-onboarding.py) can export fresh blind packets and execute separately supplied proposals.

## Results and new order

25/34 initial proposals won; 32/34 won within the three-proposal allowance. **Catch the sun** (winch) and **Turn the big wheel** were unresolved. Gear proposals failed overlap checks; solar proposals failed orientation/aiming. Other retries involved reflected-angle signs, a missed knife sweep, chute/source overlap, water routing and an invalid field-force input. The authored solutions are checked separately by the game regression suite; the blind solvers never receive them.

Order combines operation count, prerequisite concepts, 3D placement burden, feedback clarity and the blind outcomes. Time ranges overlap; this is a teaching sequence, not a strict sort by interval midpoint. The one-wire and one-resistor lessons are deliberately early despite old category names. Wiring, single-reflection and river-wheel lessons precede their multi-step follow-ups. IDs, existing progress, physics goals, deadlines and energy scoring are retained.

| New # | Level | Est. newcomer minutes | Blind proposals | Outcome | Native wall seconds, all proposals |
|---|---|---|---|---|---|
| 1 | Tip the lever | 2–4 | 1 | Won | 0.038 |
| 2 | Turn the axle | 1–3 | 1 | Won | 0.077 |
| 3 | Light the bulb | 2–5 | 1 | Won | 0.076 |
| 4 | Finish the loop | 1–3 | 1 | Won | 0.072 |
| 5 | Fill the receiver | 2–5 | 1 | Won | 0.310 |
| 6 | Wheel in the river | 2–5 | 1 | Won | 0.284 |
| 7 | Spring lifts the load | 2–5 | 1 | Won | 0.036 |
| 8 | Mind the gap | 2–5 | 1 | Won | 0.226 |
| 9 | Limit the voltage drop | 1–4 | 1 | Won | 0.052 |
| 10 | Close the switch | 2–5 | 1 | Won | 0.092 |
| 11 | Pour onto the paddles | 2–6 | 1 | Won | 0.178 |
| 12 | Marble turns on a light | 2–6 | 1 | Won | 0.090 |
| 13 | Raise the crate | 3–7 | 1 | Won | 0.103 |
| 14 | Up she goes | 3–7 | 1 | Won | 0.130 |
| 15 | Find the focus | 3–9 | 1 | Won | 0.028 |
| 16 | Cut the cord | 3–8 | 1 | Won | 0.090 |
| 17 | Bounce to the target | 3–8 | 2 | Won | 0.107 |
| 18 | Give it power | 3–8 | 1 | Won | 0.052 |
| 19 | Gentle first launch | 3–8 | 1 | Won | 0.217 |
| 20 | River-powered lift | 3–7 | 1 | Won | 0.344 |
| 21 | Series or parallel? | 4–9 | 1 | Won | 0.054 |
| 22 | Store the charge | 4–10 | 1 | Won | 0.082 |
| 23 | Heat to release | 4–10 | 1 | Won | 0.773 |
| 24 | Water opens a gate | 4–10 | 1 | Won | 0.366 |
| 25 | Charge in the sun | 4–10 | 2 | Won | 0.594 |
| 26 | Cut it down | 4–10 | 2 | Won | 0.379 |
| 27 | Chain reaction | 5–12 | 1 | Won | 0.330 |
| 28 | Sun-powered lift | 5–12 | 2 | Won | 0.528 |
| 29 | Divert the water | 5–12 | 3 | Won | 0.914 |
| 30 | Lift with less | 6–15 | 1 | Won | 0.213 |
| 31 | Knock it off | 6–15 | 2 | Won | 0.256 |
| 32 | Bounce the beam | 8–18 | 2 | Won | 1.179 |
| 33 | Catch the sun | 8–20 | 3 | Unresolved | 1.831 |
| 34 | Turn the big wheel | 8–20 | 3 | Unresolved | 0.191 |

## Simplification

The main Adjustment menu prioritizes the task’s relevant parameters. Opening Precision controls restores every adjustment; Sandbox retains its complete ordinary menu. The introductory weight puts position and height before material/mounting. River wheel placement starts with across-river position, gear lessons prioritize size/position/height/tooth alignment, and optics prioritize face/beam adjustments. These change presentation only; no default solving placement, auto-aim, force, target or threshold is introduced.

All solar lessons now show the existing camera-relative Sun direction marker; it points toward the declared sun and never rotates the panel. The collector normal and live preview still show what the native model measures. The battery-charging lesson is renamed **Charge in the sun**, distinguishing it from the full **Catch the sun** winch puzzle. Cards show estimated minutes with a tooltip identifying their proxy basis; the simulation deadline remains a separate game condition.

Harder follow-up work remains: broader real-player sampling, a visual-only blinded cohort, drag/recognition timing, clearer gear clearance/phase diagnostics and calibration of the solar angle convention. This audit does not add new physical validation, resolve cable mechanics or validate conservation beyond the existing engine tests.

## Verification

61 game/engine tests passed in 98.131 s, including every authored solution and its nudged runs, misplaced-piece failures, unchanged energy pars and complete blind-packet coverage. Four browser regressions passed in 61.526 s: all 34 levels at 1280×860, 390×844 and 844×390 (102 openings), the new order/time labels/primary controls, solar shade and actual cable delivery, and the native gear lesson. Visible Run/Reset touch targets remain at least 44 px and attached to the scene. Median local page-to-ready time was 0.222 s, maximum 0.534 s; those 102 measurements are recorded in the JSON receipt and are not player solve times.

The first sweep reported Chrome net::ERR_NO_BUFFER_SPACE on a module fetch. A fresh owned browser/profile per viewport bounded the fixture accumulation and passed the same unchanged waits. A subsequent fixture-handle cleanup error was corrected before the passing four-test run. Both client geometry/gallery CTests and all 269 C++ source registrations passed. JavaScript syntax and changed-file checks passed. No C++ engine source, force, material law, timestep, goal deadline or conservation tolerance changed; the tested Windows engine hash is in the JSON receipt.

The final introductory-weight profile was checked again in the three-size
ordering/control browser regression (5.465 s), plus tray/blind-export checks.
Manual phone play used the blind assessor's placement and achieved three stars
in the new first level. Desktop and phone screenshots remain in ignored
`build/onboarding-audit`; public deployment verification follows publication.
