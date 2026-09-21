# Workshop Mode: what to build next

`docs/workshop-mode.md` states the intent and the six increments. This file is the
ordered work list against the code that actually landed (main `ece2419`), with the
reason each step comes where it does and what "done" looks like in 3D.

## The keystone problem

**There are two workshops.**

- `mcp/workshop.py` — a tested Python model of designs, components, variants,
  materialization and feedback. It is imported by nothing but its own test and
  its demo. No MCP tool, no server route, no `docs/api/mcp.md` row.
- The inline module in `playground/world.html` — a second, independent
  implementation in JavaScript, with its own component layout, its own variant
  sweep, its own materializer and its own feedback record. This is the one a
  person actually sees.

They share the string `banjo.workshop.v1` and nothing else. They already
disagree: the Python `variants()` never rebuilds geometry, so every Python
candidate materializes identically, while the page's candidates differ; the
page drops `rotation_deg` at materialization, the Python keeps it.

Every item below — the library, the chat, materials, trials, machines — would
otherwise have to be written twice and kept in step by hand. So stage 1 is one
model, and it comes before the features.

## Stage 0 — make the measurements true  — DONE

The workshop's whole purpose is comparing candidates. Three defects make the
comparison wrong, and they are cheap to fix.

- **The splay is inverted.** Legs rotate about their own centres with
  `rotation.z = -sx * splay`, which sends the feet *in* and the tops *out*.
  Measured on "Splayed · wide" (10°): feet span 0.972 m, leg tops span 1.232 m
  past a 1.20 m top. The candidate offered as the wide, sturdy one has the
  narrowest base of the six.
- **The cheap check measures the wrong points.** It reports the leg *centre*
  inset as "support footprint" whatever the splay: 1.10 × 0.60 m for a candidate
  whose real base is 0.97 × 0.53 m, and calls it "inside the top" when the tops
  overhang.
- **Materialization erases the differences.** It drops `rotation_deg` and taper,
  and `_snap` at the 40 mm cell sends 45, 48, 50 and 58 mm all to 40 mm. Six
  visibly different candidates become two distinct plans; three are identical.

Done when: a splayed candidate's feet are demonstrably outside its top, the
reported footprint is measured from the feet, and no two candidates that look
different materialize the same without saying so.

## Stage 1 — one workshop model  — DONE

`mcp/workshop.py` becomes the only place designs exist.

- A new `playground/workshop_api.py` exposes it over `/api/workshop/*`.
- The page keeps the three.js renderer and the controls and loses every line of
  design logic: it asks the server for candidates and draws `wireframe()`.
- The workshop's CSS and JS move out of `world.html` into `/workshop.css` and
  `/workshop.js`, served under `'self'`. The inline bootstrap shrinks to the two
  lines that choose between the world driver and the workshop, and the CSP
  special case shrinks with it.

Done when: deleting the JS design code changes nothing a person can see, and one
change to a component family shows up in the page and in a Python test at once.

## Stage 2 — a component library that composes  — DONE

Today there is one family (`leg`) and two hardcoded assemblies whose corner
arithmetic is written out twice. Components should attach to each other.

- The primitive is a **strut**: a member spanning two points, which derives its
  own length, centre and rotation. Legs, stretchers, posts, beams and braces are
  all struts; tops, panels and shelves are boxes.
- Families declare their parameters with units and bounds, and the **anchors**
  they offer: a leg offers `foot` and `head`; a top offers its four underside
  corners; a stretcher spans two anchors.
- Assemblies compose by anchor, not by repeated corner maths: `table`, `stool`,
  `chair`, `bench`, `shelf-unit`, `cart`.

Done when: a new family is added without touching any assembly, and an assembly
is added without touching any family.

## Stage 3 — a library you can browse, and designs that persist  — PART DONE

- A **Library** pane: families, their parameters and bounds, what each attaches
  to, and a thumbnail of each.
- Designs are saved to a durable store with their lineage, so a candidate can be
  reopened, forked and compared next week. Feedback moves out of `localStorage`
  into the same store, which is what makes it evidence rather than a note on one
  browser.

Done when: a design made today is reopened tomorrow, on another browser, with
its lineage and its feedback.

## Stage 4 — the workshop chat (increment 3)

The agent API from `docs/workshop-mode.md`, over the library above:
`open_workshop`, `list_component_families`, `instantiate_component`,
`compose_design`, `fork_variants`, `inspect_candidate`, `measure_candidate`,
`record_feedback`, `materialize_candidate`, `save_design`, `close_workshop`.

The live-world authoring tools are **not** in this set. Exploring a candidate
must not be able to touch the room.

Done when: "show me six leg styles", "I like #3 but lower", "try those legs on a
chair" and "which two are hardest to tip?" all work in the page, and none of
them changes the live world.

## Stage 5 — materials and mass  — PART DONE

The workshop names `oak` and means nothing by it. The page's centre-of-mass dot
is drawn at a fixed fraction of the height.

- Materials come from Banjo's catalogue with real density.
- Every part gets mass; the design gets total mass and a real centre of mass.
- The cheap checks become real statics: is the centre of mass inside the support
  polygon, what is the tip angle about each edge, what load does each leg carry.

Done when: swapping oak for iron changes the mass, the centre of mass and the
tip margin, and the numbers are arithmetic anyone can check by hand.

Density, mass, the real centre of mass, the support polygon and the tip angle
have landed, and so has the per-leg load (`mcp/workshop_statics.py`, e9d9acb).
A material the engine has a preset for weighs what the engine's catalogue says:
`mcp/workshop.py` reads it from `mcp/engine_materials.py`, whose parity test
pins it to `MaterialCatalog.cpp`. Until September 21 the table kept its own oak
(750 kg/m³) and rubber (1200) wherever nothing had synchronised it, so one
design had two masses. What is left: pine and steel, which the engine has no
preset for, still weigh what the table says.

## Stage 6 — scratch physical trials (increment 4)

Compile the chosen candidate plus a floor into a scratch `LiveWorld` and run the
trials the design already declares: static load, tip about each axis. Nothing
else in the world is compiled.

Done when: "specified but not claimed by this cheap check" is replaced by a
measured result, and the trial is watchable.

## Stage 7 — process and heat

What it takes to *make* the thing: cutting, joining, and the heat a join needs.
This is the input the commit's "fabrication energy/process validation" is
waiting for, and it is where Banjo's thermo belongs in the workshop.

## Stage 8 — machines on the bench

`axle`, `wheel`, `drum`, `motor` families, driven by the existing `LiveControl`
and its Operate panel. Design a cart or a hoist in the workshop, test it under
power in a scratch world, then install it.

## Stage 9 — transactional return (increment 5)

Revalidate against the *current* world revision, debit inventory, validate
placement against the owner's rule (nothing below the ground, nothing
overlapping, nothing of theirs moved), and apply as one atomic edit.

## Stage 10 — the learned library (increment 6)

Promote a proven subassembly into a reusable family through an explicit review
step, so the library fills with what worked rather than with every experiment.

## Order, and why

0 and 1 are foundations: 0 because the workshop currently measures the wrong
thing, 1 because everything after it would otherwise be built twice. 2 and 3
make the thing worth browsing. 4 is the payoff the design document is really
about. 5 and 6 turn its claims into measurements. 7-10 connect it back to the
world.


## What has landed so far

Stages 0, 1 and 2, and the first half of 3.

- **The geometry is right.** A member is now a `strut` between two points, so a
  splayed leg is described by where its foot and head actually are. Splaying 10
  degrees widens a table's base from 1.16 to 1.36 m and its tip angle from 24.6
  to 33.0 degrees; before the fix it narrowed the base to 0.97 m.
- **The support polygon is measured where the design touches the ground**, from
  the cut foot faces, and a standing panel contributes its whole rectangle -- so
  a shelf unit is no longer reported as balanced on a line.
- **Materialization keeps rotation and reports its snapping.** Every plan now
  carries a `fingerprint`, so candidates that arrive as the same object once
  snapped to the cell grid say so in the bench, instead of being offered as six
  choices that make two things.
- **`variants()` rebuilds.** Forking on a parameter an assembly does not have is
  refused rather than silently recorded.
- **One model.** `mcp/workshop.py` is the only place designs exist.
  `playground/workshop_api.py` serves it at `/api/workshop/*`, and
  `playground/workshop.js` is a renderer that decides no geometry. The page's
  private copy of the design model is gone.
- **Eleven families and six assemblies**: leg, surface, apron, stretcher, beam,
  post, brace, panel, axle, wheel, handle; table, stool, bench, chair,
  shelf-unit, cart. Assemblies compose by anchor, so the cart's axles hang from
  posts and its handle stands on arms without any assembly doing a family's
  arithmetic.
- **Mass and balance are real.** Every part has a density-derived mass, the
  bench draws the balance point where the model puts it and rings the support
  polygon on the floor, and swapping oak for iron changes both.
- **The library is browsable** in the left pane, with every family's parameters
  and bounds, and **feedback is kept on the bench** rather than in one browser's
  `localStorage`.
- **The workshop's CSS and JS are served files.** `world.html` fell from 22,486
  to about 9,400 bytes and carries only the two-line bootstrap that chooses
  between the world driver and the bench.

Suites: `tests/workshop_tests.py` 25, `tests/workshop_api_tests.py` 15, both in
CI. Not yet done: saved designs and their lineage (the rest of stage 3), and
stages 4 to 10.
