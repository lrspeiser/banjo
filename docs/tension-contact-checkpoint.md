# Tensile interfaces with retained Jolt surface contact

Local source `0b01533dc8151da07742ddb341f1b09486e8631f`, September 5, 2026; not pushed or merged. Full platform goal active.

`JoltWorld::applyCohesiveTensionKick` derives a central tensile impulse from a declared cohesive law, body-local attachment points, current world transforms, positive reference distance and prior interface history. It returns the updated constitutive increment and the existing measured pair-transfer audit. It requires double positions and ordinary Jolt ownership for the body pair. Nonzero compression stiffness rejects, as do bodies configured to defer contacts into material activation. The external whole-pair contact path remains available separately; its ownership requirement has not been weakened.

This separates a central tensile connector from Jolt's normal/frictional surface responses. Jolt retains contacts on the entire pair, rather than disabling them for a small interface. The caller owns valid attachment geometry, the declared area/law, history persistence, temporal integration and overall work/error budgets. The implemented connector uses Euclidean attachment distance; attachment separation at or below 1e-6 times the reference distance rejects. It is not a face-normal contact law or a complete finite-area assembly solver. Unpinned unrestricted dynamic bodies are required. Static reactions, caller-owned multi-kick rollback and application creation remain unsupported here.

## Sleeping and event evidence

The first contact fixture revealed a false success condition: the slow glass pair went to sleep at center separation about 0.1118 m, before its 0.1 m boxes touched. Its kinetic energy disappeared in the Jolt stage, and a speculative contact event alone did not establish actual contact. The corrected operation activates both bodies and resets sleep timers while the external solver continues issuing kicks, including slack/failed sites. The scheduler must stop those calls when normal sleeping can resume; this is not a general sleep-energy solution or performance policy.

The contact regression now requires minimum center separation between 0.098 and 0.1005 m, as well as an event and a response. Jolt can emit speculative contact events at positive gaps even in the separate opening probe, so event count is never treated as proof of a collision impulse.

## Glass/oak/iron verification

The prior 48-case high-stiffness opening/refinement/location probe now also runs with `--jolt-surfaces`. All 12 finest elastic/separation criteria pass with Jolt surface ownership retained, at 0 and 10 m for glass/oak/iron. This retains the independent elastic oscillator and post-separation energy/speed oracles. The previous externally owned probe remains as a separate test and its historical single-position failures remain recorded.

A failed-bond fixture compares an ordinary Jolt collision with the same collision receiving zero tensile kicks from fully failed history. For all three substances, positions agree within 1e-7 m and velocities within 1e-6 m/s through 40 steps of 1/240 s. Damage work remains A*Gc and force remains zero, with no compression refund or healing. Invalid compression, contact ownership and duration reject without body mutation; the glass material-activation deferral case also rejects. Single-position builds reject the new operation.

A second fixture includes positive tensile loading and actual subsequent surface contact in one trajectory. It uses equal 0.1 m cubes, center attachment points, reference distance 0.12 m, initial distance 0.122 m, area 0.001 m2, no gravity and zero initial velocity. Interface parameters declare 0.005/0.02 m onset/failure openings: S=2*Gc/0.02 and K=S/0.005, using catalog Gc and density. These intentionally compliant interface examples are independent of bulk tensile strength; they do not calibrate real material joints. Duration is 24/omega with omega=sqrt(2*A*K/m), at 1024 and 2048 steps.

The ledger separately measures Jolt-stage kinetic-energy change, audited transfer error, and the remaining coupled-integration error in KE+stored+damage energy. Jolt-stage change includes solver effects and is not automatically classified as physical heat. Whole-trajectory energy stays below 1.001 times initial energy; the remaining integration error is below 0.001 times initial energy and improves under refinement. Momentum residual is measured as zero in these symmetric fixtures.

| Material | Fine minimum center distance m | Fine Jolt-stage energy change J | Fine maximum integration error J | Fine error / initial energy |
|---|---:|---:|---:|---:|
| Glass | 0.100000 | -0.000319991 | 1.09857e-8 | 3.43303e-5 |
| Oak | 0.100000 | -0.0399989 | 1.37351e-6 | 3.43377e-5 |
| Iron | 0.100009 | -2.73306 | 1.37323e-4 | 3.43307e-5 |

Fine errors are approximately one quarter of the corresponding coarse errors. This is two-resolution evidence for these fixtures, not proof of global convergence order, general contact accuracy or spatial convergence.

Both complete Release builds pass: promoted double-position graphical build 27 suites in 23.17 s, legacy single-position build 25 suites in 19.41 s. New coupled-contact suite is 0.81 s in the double build. Windows 11 / MSVC 19.44 x64 / CMake 4.1.2 / Jolt 5.6 / raylib 6. Double positions remain ON in the promoted build; frame control, busy wait and static MSVC runtime remain OFF. Starter and workshop were closed normally for relinking and restarted in their converted workspaces. No new native joint interaction is claimed.

## Next integration boundary

No creator/starter path invokes the new tensile operation yet. Existing assembly declarations and isolated finite-patch compression tests are not silently reinterpreted as tension-only live joints. Next expose an explicit compatible interface/contact policy, assemble finite-area sites, synchronize kicks/drift and histories, and bound partial-step failures. Test asymmetric geometry, spin, third-body contact, surface overlap and reactions before claiming general live assemblies. Physical fabrication sources, realistic branch cutting, material calibration, default fracture defects and all other goal gates remain open; all 40 scorecard rows are retained.
