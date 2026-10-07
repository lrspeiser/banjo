# Rigid grain test world checkpoint — October 7, 2026

## Implemented scope

The default replacement browser sandbox now declares **200 loose rigid grains**, not a soil heightfield. Each grain is a 100 mm cube (0.001 m³ / 1 litre), with material-derived mass/inertia and native Jolt gravity, friction and collision. Two layers on a fixed concrete base have 120 mm horizontal spacing: the gaps are declared porosity, **not compression or alternating hidden air cells**. There is no cohesive parent solid, implied breaking threshold or precut fracture outcome. The base and stand are deliberately anchored external supports.

Glass and iron test blocks also use exact native collision primitives. The configured held tool retains its existing material-cell geometry, native fixing and declared grip/contact point. The player is an actual native body. There are no assigned impact velocities, tool poses, debris paths, cosmetic voxel particles, geometry deletion, raw-material credits or automatic fragment outcome reuse in this scenario. The legacy heightfield fixture remains explicit in the gateway for earlier regression coverage; this browser no longer renders or invokes its soil-only cut path.

A new actor-scoped physical-hit intention selects the actual first native ray target. It checks the actor eye, ray, range, actual held assembly, supported load, attached contact point and bounded arm reach. It does not branch on material/tool display names. The hand lifts clear, approaches, makes contact, pushes and recovers through the existing force/torque actuator and finite actor reactions. Separate measured straight segments avoid ambiguous nearest-point progress on a returning path. A blocked approach attempts physical recovery; it never grants removal. Native contact pairs are recorded before damage/anchored-body filtering, so hitting a fixed support can be reported without promising motion.

The browser ignores the actual native held-part set, targets the click/touch coordinate, previews native admission, and displays contact, selected-target displacement and signed net hand work. Green admits an **attempt**, not a successful cut. Preview retries after a busy observation and invalidates on holding/active-state changes. Exact native compound parts are rendered with their own transforms. The obsolete browser terrain/soil-cut display path was removed. No larger subsystem is retired.

Native exact-body admission increases from 32 to **256 bodies**, while the existing aggregate **256 collision-part cap** remains. A registered native regression admits 256 one-part declarations and refuses 257. The bounded browser fixture admits no arbitrary native operations, force settings, timestep, actor or geometry supplied by the client.

## Measured verification

Windows/MSVC Release native build in `build/local-cell-tools`; Rust debug owner in `build/rust-runtime`. Base main revision: `60c28ee8`; this document belongs to the following coherent checkpoint commit, whose exact revision is recorded in Git and the user report.

- Native SHA-256: `feb425b8b46b371b387f2ba26180afe5e050603c7016be0a39a49b93daefb9bd`.
- Rust executable SHA-256: `3a1a450e40ecdae7a01cc734b869d68849712cfac735a1f4ffb5e4f6eea6fbb0`.
- **26 Rust tests**: bounded typed preview, actor privacy, unsupported capability and existing command/clock/receipt behavior.
- **17 actual-native worker tests** pass in 25.827 s.
- **7 actual HTTP → Rust → native gateway groups** pass in 49.953 s, including four configured head-width families, three grain materials, fixed support, glass/iron blocks, independent custody and exact retry identity.
- Rebuilt `banjo_native_tool_use_tests` and `banjo_precise_rigid_parts_tests` pass (2.23 s combined). These are bounded suites; the stricter retained acceptance flags are not changed or waived.
- Source registration: **315/315**, zero exclusions. Python compile and browser JavaScript syntax checks pass.

Matched grain experiment: the same iron configured pick, 200 grains, 100 mm grain edge, 120 mm packing spacing, 1/240 s native timestep, same initial actor/tool/target conditions and actual force-controlled stroke. Host scheduling can shift admission by a few accepted ticks; this is not cross-platform determinism evidence.

| Grain material | Grain mass kg | Native cycle s | Selected target travel cm | Net hand work J | Mass residual kg |
|---|---:|---:|---:|---:|---:|
| Glass | 2.5 | 1.542 | 0.5005 | 23.346 | 0 |
| Oak, laboratory only | 0.7 | 1.521 | 0.6575 | 24.217 | 0 |
| Iron | 7.87 | 1.779 | 0.0352 | 21.592 | 0 |

All three record actual contact and retain every body. The native density differences are implemented; rigid grains do **not** demonstrate stiffness-dependent deformation, oak grain/plasticity or intrinsic fracture. The packing and material friction also affect displacement, so this table is not a pure density scaling oracle.

Four iron tool-head configurations record contact on the same concrete-grain target: pick 1.571 s, shovel 2.196 s, hoe 1.950 s and custom 1.737 s. Those names select declared widths; this verifies shared configured actuator/contact handling, not complete shovel/hoe constitutive functionality. Glass-block, iron-block and anchored-stand contacts are also positive. Stand displacement is exactly zero, as required for its declared support.

Local evidence: `build/material-lab/granular-gateway-tests.log`, `granular-worker-tests.log`; these are ignored build artifacts. The delivered loopback server is `http://127.0.0.1:18891/world.html` with refreshed browser assets and rebuilt native/owner binaries. Browser desktop pickup/strike displays native contact and measurements, with no console errors; landscape layout exposes movement/drop/zoom controls without menu overlap. Browser emulation is not a physical-phone qualification.

## Explicit remaining gates

This is an **experimental loose rigid aggregate laboratory**, not completed ground physics or solid excavation. Selected grain movement is small in the heavy packed cases. A completed controller/contact does not guarantee a useful hole; there is no extracted-volume claim. Contacts between the tool, player, grains, neighbouring objects and supports can disturb grains beyond the selected target. Browser runs show broader disturbance during actor/hand recovery. Locality, long-duration stable stance/recovery and useful excavation speed remain unqualified.

Mass/body retention is measured. **Full momentum/angular-momentum/energy closure is not qualified**: external gravity, native player/hand actuator work, static support reactions, contact losses and numerical corrections still need one complete pipeline ledger. Signed hand work is an observation, not that ledger or the energy received by the selected grain. No conservation tolerance is widened.

Cohesive solid ground, intrinsic glass/metal/tool fracture, finite material self/neighbor contact, conservative topology handoff, calibrated granular/soil laws, durable hit-completion receipts/state, production terrain scale and physical-phone/full-repository regression remain open. The [coupled manifold checkpoint](coupled-manifold-checkpoint.md) and original strict sustained-contact / four iron same-column repeat gates are retained and still unresolved. This scenario does not close them by replacing their experiments with rigid cubes.

Next: qualify physical targeting/clearance and bounded actor/hand recovery under long repeated use; close the full transfer ledger; then connect the converged conservative solid solver to native target activation and topology replacement. Calibrate cohesion/packing and prove excavation throughput before calling it a playable material-ground engine.

### Published follow-up

Core scope is published on main as `b3b8dd5d`. A subsequent ordinary-browser check caught New world discarding a click during an observation. The control now waits briefly for the active request, prevents duplicate starts and reports a timeout; a successful fresh world replaces the session and resets the native clock. This follow-up changes browser scheduling only. Native/worker/gateway physical evidence above remains the same; no physical gate is reclassified.


## Pickup and selection follow-up

User reproduction found a frozen scene labelled "World stopped" at native time 761.65 s. The last frame remained clickable-looking and `act()` silently returned after loss of session. The original stopped/expired cause cannot be reconstructed from old generic HTTP logs. A new world admitted clicking the head as well as the earlier tested handle. This was an application failure, not evidence of incorrect user input.

The replacement interface now retains the press's body/point through modest finger drift (16 px touch, 8 px mouse), assigns one pointer owner, and rejects deliberate orbit gestures. It highlights/tints all visible components linked by attached fixing topology, with a 10 px mouse / 18 px touch halo around a configured assembly's projected bounds. Foreground unanchored targets take precedence; native visibility/load/reach admission remains authoritative. Public joints/tool points are explicitly projected by Rust; other actors' custody/cargo are still private. This presentation does not authorize arbitrary topology or grant pickup through native obstacles.

A native physical-hit capability incorrectly required the selected custody body to equal the declared `grip_body`. Physical pickup can legitimately start on the head or another fixed member. Physical-hit admission now finds the attached point and connected declared grip in the actual fixed assembly, retaining ambiguity, strength, reach and action-in-progress refusals. Four configured families now acquire by head, confirm native custody, strike a grain, retain the whole tool and drop. The legacy terrain-use planning path still has stricter grip-root assumptions; it is not silently qualified by this change.

Equipped items appear in a highlighted hand slot. Their native bodies remain present and colliding, but the client hides them between actions and shows their actual poses as faint ghosts during the force-controlled stroke. The confusing player-cylinder drawing is removed; the native player and finite hand/player reactions remain. This is equipped physical custody, **not implemented Inventory parking/material transfer**. Native mass, pose and impact are not synthesized or teleported.

The rigid-grain fixture now starts with feet at [0, 0.022, 0.82] m on its declared fixed base beside the sample, instead of standing on the loose grains. This bounds the pickup experiment's footing and avoids driving initial balance into the sample before a strike. It does not solve general balance on loose ground or long repeated recovery. The old retained-soil comparison fixture is unchanged.

Expired, native-stopped and input-budget-exhausted worlds return bounded lifecycle codes. The client stops input, labels the frame frozen and keeps a persistent restart control. Closing an already expired disposable session is idempotent, so restart can create a fresh native world. The existing 90 s inactivity lease, two-world cap and 4,000 browser input-receipt cap remain. Generic refused requests still reveal no arbitrary exception text.

### Verification

Base main `415b24fd`; Windows/MSVC Release `build/local-cell-tools`, Rust debug `build/rust-runtime`. Native SHA-256 `d1334f075ab4b78a88c04ab3ad3bde89e297720b86e93a96d37ea5cfba2ce3f7`; owner SHA-256 `220c06eb2410ca5dbce44cfed81da7319de5f1a777fa536591c8b14b018fe266`.

- Ten actual HTTP/Rust/native gateway groups pass in 64.721 s, including head pickup followed by impact for all four declared widths, whole connected custody, expiry/idempotent-close recovery and input-limit refusal.
- Seventeen actual-native worker checks pass in 25.669 s; 26 Rust tests pass, retaining privacy/clock/receipt assertions.
- Rebuilt `banjo_pickup_admission_tests` and `banjo_native_tool_use_tests` pass. Registered `banjo_test_world_input_tests` passes four input/whole-topology groups. The CTest gateway timeout increases from 90 to 120 s and the Test Hub job budget from 60 to 120 s to admit the additional physical cycles and stance intervals; no physical acceptance tolerance changes.
- Matched configured picks, same native 1/240 s timestep / 20 mm tool resolution, same fixed footing and two-second stationary observation after grip confirmation:

| Material | Peak tilt rad | Peak horizontal drift m |
|---|---:|---:|
| Glass | 0.000106168 | 0.000403772 |
| Oak, laboratory only | 0.000097662 | 0.000213166 |
| Iron | 0.000158583 | 0.000395017 |

These are bounded balance observations, not constitutive law, grain/plasticity or full-system conservation qualification. The existing mass/body-retention tests continue to pass; full P/L/E closure is still open. No spring/contact/fracture law or conservation tolerance is changed.

Ordinary desktop browser verification: a click beside the narrow handle equips the pick, the next grain click records actual contact (0.3 cm target travel / 20.70 J signed hand work in one run), and the restart prompt recovers a stopped session. Native scheduling affects measurements; these are not deterministic cross-platform values. JS syntax/Python compile and 315/315 source registration pass. Local logs: `build/material-lab/pickup-recovery-gateway-tests.log` and `pickup-recovery-worker-tests.log`. The refreshed server is on 18891.

Remaining: intrinsic solid fracture/cohesive excavation, useful displacement and digging speed, full transfer ledger, repeated-hit locality/stability, general stance on loose ground, actual Inventory parking, retained-soil grip-root generalization, physical-phone acceptance, production-scale hosting and full repository regression. Original strict contact/four-repeat gates are unchanged and remain unresolved.


The head-pickup follow-up also executes **two consecutive native contacts for each of four configured families**. This registered group passes in 24.668 s with native sampled up-vector above cos(0.6), the existing controller's fallen-posture boundary, through each action/recovery. This is a bounded loose-grain paired-contact test, not the failing retained-soil four-repeat excavation gate. A second desktop journey picks the head, strikes a grain and reports actual contact (2.9 cm target travel, −15.11 J signed net hand work); negative net hand work is recovery/actuator exchange, not an inventory energy credit. Whole-object highlighting, slight-drift orbit cancellation, expanded handle acquisition and persistent stopped-session restart are visibly verified. Landscape emulation at CSS 844 × 390 keeps 48 × 45 px movement buttons clear of the top menu and footer; no physical phone is certified. Proof captures are ignored local files `build/material-lab/whole-tool-highlight-tested.jpg` and `equip-and-impact-tested.jpg`.
