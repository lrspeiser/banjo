# Fresh-world made-item contact and persistence checkpoint

October 2, 2026. This checkpoint tests the normal generated world through public HTTP actions. It does not complete R3's damage/reuse acceptance.

## Scope

`LabRemake.test_fresh_market_paid_pick_contacts_peer_product_and_server_restart_keeps_both` in [the fabrication tests](../tests/fabrication_remake_tests.py) starts a generated 50 mm world with its empty workbench. It banks actual solar-store energy, purchases finite Market lots into the player's private rack, funds measured material/energy requirements, waits for accepted native charging/processing time and places two paid products. It does not insert stock, alter the map, weaken a fixing, change the grid or grant free energy.

The products are a 2.5 m × 50 mm × 50 mm oak beam with a 100 mm iron head (12.245 kg), and a 500 mm oak-handled pick with a 200 mm iron arm (4.81 kg). These are deliberately declared experiment geometries. A second authenticated player takes the beam by its head through Inventory and raises it with the existing bounded native hand. The first player takes the paid pick, aims from a surveyed ground height and uses the ordinary object-strike endpoint.

The test requires native contact, completed use and an attached working point. It checks separate Inventory ownership, stows the striking product, saves the world and stops/restarts the Python HTTP server and native sessions. It verifies the manufactured fixing records, player-hand records, private inventory records, Market balance and funded fabrication ledger after reopening. It also uses the existing whole-world preservation checker, including its existing 1e-6 rad hinge-angle tolerance. The rover's recomputed native hinge angle is not bit-exact across reopening; this tolerance is unchanged. No other tolerance is relaxed.

Named worlds grant public simulation steps against a shared wall-time budget. The driver requests up to 60 substeps at dt=1/240 s; the server still grants only the elapsed budget. Sending tight batches does not fast-forward this world. The peer must finish its actual lift before the strike or checkpoint is attempted.

## Measured boundary

The native contact probes with the starter pick and the paid mixed pick leave these normal-grid mounts intact. Contact does not imply destruction. This test qualifies the paid contact/private-peer/server-restart path; it does **not** qualify separated-part collection or replacement after a fresh-world strike. The earlier [paid 5 mm separation/replacement test](rectangular-mount-reuse-checkpoint.md) remains a distinct, controlled fixture result.

The final paid-pick run reports one native contact at 1.80168 m/s, 3.36237 J diagnostic impact energy and 79.818 J signed hand work across preparation/use. It reports no parted joints. These readings are not a closed momentum/energy audit. The funded process reports material residuals of zero for oak/iron, energy residual -2.28262e-12 J and native transfer residual -3.41061e-13 J.

The sampled oak/iron contact here has a 0.0025 m² area, 225,000 N declared normal capacity and 27,500 N declared shear capacity. Its square 50 mm section has a pure single-axis bending limit of 1,875 N m in the experimental rectangular normal-stress model. The earlier square 5 mm oak/iron mount has 2,250 N normal capacity and a 1.875 N m bending limit. With the same declared strength and efficiency, area scales as cell size squared and the square-section bending limit as cell size cubed: these particular one-cell mounts differ by factors of 100 and 1,000 respectively. This is a property of the compiled joint model, not a calibrated wood, adhesive or fastener claim.

The mounts have different physical dimensions. Refining the grid for an unchanged 50 mm physical mount does not itself reduce its strength by these factors. The coarse grid constrains the smallest represented geometry; it does not justify silently changing original dimensions or declaring the same object weaker.

The [shared Workshop instructions](../playground/workshop_chat.py) now require lifting/striking tests at the installation world's cell size. They prohibit using a finer Lab result as installation qualification, silently enlarging thin components, changing the world grid or activating proposed joint-efficiency reductions to make a strike pass. Contact, separation and unsupported internal damage must be reported separately.

Internal held-strike damage, genuine repair, fatigue/wear, grain, calibrated interface failure and full strike momentum/energy closure remain unsupported or unfinished. Local fabrication audit residuals qualify the funded process only. No native law, strength, hand force/torque limit, timestep or resolution is changed here.

## Verification

The fresh-world test passes in 45.282 s. The existing paid 5 mm strike/replacement test and three native HTTP/Chrome object-strike checks also pass in the focused run; its then-failing new assertion was fixed and the fresh-world test rerun successfully. The original assertion incorrectly required bit-exact restoration of the rover's recomputed hinge angle. It now uses the existing whole-world preservation gate and additionally requires exact equality for the manufactured fixing histories; no tolerance was added or widened.

Runtime under test: native implementation `71fe9c39868e43c40c491991136f28223b2db650`, Windows x64 MSVC 19.44 Release, `build/agent-object-strike/Release`; source-registration guard remains 297/297. The existing preview servers and binaries are unchanged by this test/prompt checkpoint.

With `BANJO_LIVE_ENGINE`, `BANJO_LIBRARY`, `BANJO_BUILD_DIR` pointing to this separate build and `PYTHONPATH=tests`, the new check is:

```text
python -m unittest fabrication_remake_tests.LabRemake.test_fresh_market_paid_pick_contacts_peer_product_and_server_restart_keeps_both -v
```

Ignored local evidence is `build/resource-flow/fresh-paid-peer-strike-restart.json`. It contains the receipts, actual strike and local process audit, not a full conservation certification.

## Next acceptance work

Keep the whole R3 objective: made-item damage or separation, private collection, reviewed funded replacement/repair, original/history retention and restart. The next implementation must resolve the normal-world held source/target damage boundary with actual geometry/material/contact/hand reactions. Do not weaken capacities or use a click-count durability decrement to turn this contact qualification into a destruction test.
