# Thin-plate request admission and playback checkpoint

September 6, 2026. Python/JavaScript integration correction over native checkpoint `b4b5c9e7f0b302aa39d19bcf414ff1b784674aa0`. No native material law, collision tolerance, damage budget or solver code changed. R08 remains active; all nine original workstreams, 40 mechanics and R01..R10 goals remain retained and uncompleted.

## Reported failure and correction

The exact user prompt was `drop an iron ball onto a thin glass plate`. Job `f4dc878d9c084365b4444ed557c46080` received a GPT proposal for a 240 by 360 by 4 mm network plate with resolution 6 by 9 by 2. Native validation rejected it before simulation: the collision radius is 0.49 times the smallest cell spacing, giving 0.98 mm, below the 1 mm minimum. The planner had incorrectly described the geometry as supported.

The public authoring API and drop/scene validators now check the same dimensional relation before native execution. Tests compare Python admission with actual native validation, including matched glass/oak/iron packages. A 4 mm, two-layer network and a 6 mm, three-layer network reject; 4.1 mm and 6 mm with two layers admit. Lateral over-resolution also rejects. Admission establishes neither thin-shell accuracy nor fracture validity. Rigid geometry is unaffected.

The GPT instructions explain the limit. When no numeric thickness is supplied, the planner explicitly assumes a 6 mm experimental panel with two layers. Explicit user dimensions must remain intact; inadmissible combinations must be declined. The original failed job is preserved. Its 3D page now displays the precise cause and dimensions. Editing a failed request preserves the prompt and report but starts fresh planning, avoiding rejection caused by the invalid previous plan.

## Actual repeated prompt

Live GPT job `96ff6a24a4a74a349f0efa6846af9125` used the identical original prompt. GPT chose a 240 by 360 by 6 mm plate, resolution 6 by 9 by 2, an 80 mm diameter iron ball, 0.5 m initial clearance and 1 second duration. Glass, oak and iron targets run together with matching geometry and impact conditions. The assumption is visible in the plan; the old 4 mm job was not resized or replaced.

Native recording has 42 sampled frames through 0.3416666666666667 s, with 164 of 480 requested outer steps accepted. The next tick rolled back with `damage integration limit exceeded; complete outer tick rolled back`. All three panels retained 108 cells in one connected component and zero broken or damaged links. There is no demonstrated shattering. Temporal resolution is unresolved and the full energy residual is unavailable. These are diagnostics of an incomplete model, not physical validation.

The native case took 0.774 s wall time; planning took 13.127 s, with 13.935 s total. These single-run timings are not realtime qualification. The browser automatically opened the actual recording, played all 42 frames and exposed the solver-stop reason. Play, frame inspection and component view were checked. No substitute animation was generated.

## Verification and next gate

Python discovery: 141 tests run, 140 passed, one Windows symlink-privilege skip, 13.628 s. This includes six geometry-admission tests and four live/archive failure-detail tests. JavaScript syntax passed. Native code is unchanged; the native CLI admission parity was rerun here, while the previous full native result remains 62/62 at `b4b5c9e`. Browser checks include the original archived error, prompt prefill, retry envelope with no invalid previous plan, and the actual live prompt-to-recording flow.

Next: resolve stiff-material contact cost and coupled fracture evolution under temporal/spatial convergence and energy accounting; demonstrate a complete accepted impact with glass/oak/iron controls. Removing this setup rejection does not satisfy R03, R06 or R09.
