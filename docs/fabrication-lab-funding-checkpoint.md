# Lab funding and replacement use — October 1, 2026

Published implementation: `7a4ce90` on GitHub main. Final unchanged-source
remake rerun: **4/4 pass in 21.383 s**. Own preview on port 8770 serves this
checkpoint at `http://127.0.0.1:8770/world`; its existing generated world remains
unconfigured. The fixture's extra battery/process declarations are not silently
applied to players' worlds.

## Implemented player flow

The carried-item Lab's reviewed Remake panel now contains **Fund workbench**:

- Exact missing material, with separate **Your stock** and **Shared stock**
  actions. Partial available balances can be transferred without silently
  spending from the other pool. **Find material supplies** opens Recipes with
  that material filter and its existing acquisition guidance.
- An explicit battery selector with actual charge, source rating, connected
  charger power and ready-to-transfer joules. **Connect battery**, **Charge for
  1 s** and **Add energy** use accepted native time and the existing bounded
  paired battery/process transfer. Only the currently needed, available amount
  is requested. No economic wallet supplies physical energy.
- Exact pending stock/connection/energy request bodies retained in session
  storage. Uncertain receiving saves or acknowledgements show retry controls;
  Start remains disabled until confirmation. Reload retries the original ID.
  A known stale source/revision refusal requires current supplies. Waiting is
  explicitly elapsed native time, not an idempotent monetary transfer.

Charging refreshes retain the reviewed design rather than allocating another
bounded server plan on every second. Explicit review renews the plan; Start
still validates the actual source and process. Navigation stays above the
scrollable funding panel. Small viewports may require scrolling to its controls.

The design/source plan remains read-only. Funding credits shared workbench
supplies; starting reserves stock, and actual work consumes buffered energy.
The original remains in inventory with its damage. No energy/material process
parameters are invented by the UI. A world without a declared process or finite
source still reports missing capability. Existing [source-binding rules](fabrication-remake-checkpoint.md)
and [funding contracts](fabrication.md) remain authoritative.

## Blocker found by actual use

Returning from the Lab to use the new pick stopped the World: the funded-room
guard denied ordinary `tool_points`/`ground_work` diagnostics and `collect`.
The guard now admits these operations. Native collection already admits actual
fragments only, preserving authored whole hull products, held bodies and active
fracture participants. Direct draw, store authoring and close remain refused;
this change does not unlock free installation, fracture authoring or reset.

The World Q hint now says **put it in your bag** for an owned whole product or
explicit tool/profile. A hull shape alone was wrongly described as debris.
This is a caption correction; the actual bag transaction was already correct.

Sources: [Lab UI](../playground/workshop.js), [World hint](../playground/world.js),
[funded-room guard](../playground/server.py) and
[native/browser acceptance](../tests/fabrication_remake_tests.py).

## Native and browser evidence

The fixture generates a real world, gathers 25 kg actual oak, takes/stows the
field pick, and explicitly declares an empty 500 W / 100 J/kg approximate
workbench and a 2000 J / 300 W native battery. These remain fixture declarations;
the ordinary generator does not yet provide this capability.

Chrome uses the Lab buttons to transfer exactly **1.925 kg oak** from the
personal rack, select/connect the native source at **300 W**, wait one accepted
second and transfer **192.5 J**. Shared stock is unchanged. Independently losing
the stock and energy acknowledgements after real commits, reloading and retrying
leaves exactly one receiving packet and one source debit for each operation.

After Start, peer pause and preview are refused for the actual ownership reason
with the current session. Owner pause → reload → Resume → Run → Place passes.
A native collection attempt with a large cell budget collects nothing from the
new whole hull. Chrome follows **Collect in World**, locates it, presses E to
take it, Q to stow it, equips it again through its bag slot, and uses J for an
actual native stroke. The new tool's own identity is recorded in the result.
The test places the observer near the output using surveyed ground; it proves
ordinary pickup/bag/equip/stroke controls, not a physical-avatar walking route.

One recorded 50 mm cell / `dt=1/240 s` oak run loosens **24.64177 kg sand** with
**46.62703 J** ground-work-v1 work: 9.7923 J penetration and 36.83474 J breakout.
It stays whole. This is one supported native stroke, not a wear/fatigue or
manufacturing calibration. The original complete parked pick remains identical.
The peer receives neither the product nor the sand. Further actual raw collection
continues after configuring the workbench, leaving **48.075 kg personal oak**.
Chrome records zero JavaScript exceptions; screenshots show the held output,
filled native load meter and original/new bag slots.

Matched glass/oak/iron paid admission, real 104/12,876-bond oak cut retention,
native stock/energy/restart and installation comparisons remain in the fixed
fabrication lane. There is no C++ source, native law, ABI 25 or tolerance change.
MCP versions remain world 1.16.0 / platform 1.19.0; these are existing API controls.

## Verification and remaining work

Fixed suite: **57/57 pass in 55.530 s**, including both lost-response retries and
the actual replacement use. Ignored evidence:
`build/resource-flow/lab-funding-use-20261001/report.json`, base `5733733` plus
dirty source scope, unchanged native runner/library hashes recorded there.
QA-manager launch/status/cancel: **2/2 pass in 56.551 s**, including the corrected
bag caption. The final focused remake lane passes **4/4 in 21.238 s**, including
the plan-cache charging regression and latest layout. Workshop tabs **9/9** and
API documentation **12/12** pass. Python compilation, JavaScript syntax and the
source-registration guard (**287/287**) pass; local documentation links resolve.

All fourteen player requirements remain active: **four verified, ten partial**.
Next declare ordinary finite starter source/workbench capabilities, connect the
ordinary Make routes, and verify a damaged carried tool through replacement
and use in a fresh generated world. Mixed-material interfaces, native fatigue,
joint repair, physical avatar/cargo transport and full conservation remain open.
The current shape/work estimate and cold inventory reservoir remain explicit
approximations; replacing a body does not restore the original's bonds.
