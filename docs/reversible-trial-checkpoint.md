# Reversible runtime contact trials

September 5, 2026. Local source `654c668`, not pushed or merged. Experimental host API; full platform goal active.

`JoltWorld::runReversibleTrial` creates an in-memory checkpoint before invoking a trusted C++ host callback. Returning true retains the result. Returning false restores the checkpoint. An exception also restores and then rethrows. The operation records Jolt's bodies, contacts, constraints and global state, including previous timestep and gravity, using the pinned `StateRecorderImpl`/`PhysicsSystem::SaveState` APIs. It additionally captures Banjo's tick counter and queued impact events; rollback restores events even if the callback drained them.

Configuration and topology must remain unchanged within a trial. Gravity changes, contact-owner changes, adding/removing bodies or supports, and pin/release operations reject before mutation. Normal stepping, motion/impulse operations, queries and draining events are supported. Existing constraints can evolve and be restored. Nested trials are supported: an outer rejection discards accepted inner work.

## Bounds and ownership

The entry bound is 256 registered bodies and at most 16 nested trials. Serialized checkpoints exceeding 16 MiB reject after capture; event queues exceeding 65536 entries reject before copying. This is not a hard allocator-wide memory ceiling. It is a host-thread, between-steps operation; the callback must keep the world alive and unmoved and must not access it concurrently. The callback is trusted host code, not a new facility for executing LLM-generated code.

The checkpoint does not own external application state or cohesive histories. A caller must keep trial histories/ledgers in a candidate and publish only accepted results. No save-file format, portable snapshot or arbitrary scene restoration is exposed. If the internal Jolt restore fails, the operation raises an error explicitly requiring that world to be discarded; it does not claim an atomic recovery from restore corruption.

## Comparative verification

Glass, oak and iron share a 0.1 m moving box and 1 by 0.1 by 1 m fixed support, with gravity, initial downward speed and initial spin. A rejected 40-step collision trial restores the initial motion; rerunning and accepting reproduces the same body snapshot and event count/timestamps/contact points/estimated impulses on this build. The fixture checks a support/rebound response distinct from ballistic free fall, rather than treating a speculative callback as sufficient.

A separate explicitly positioned resting fixture warms the contact cache before comparing rejected/replayed trajectories at a changed timestep. A world-fixed constraint receives the same replay check. Tests also cover topology-change exceptions after a step, accepted nested work discarded by an outer rejection, depth exhaustion followed by a valid new trial, and restoring a nonempty pre-existing event queue after a callback drains it. Contact counts for the initial trial are 1/1/2 for glass/oak/iron; their first event tick is 1 and can be speculative. Reported body snapshots and tested event fields replay exactly in this build, not as a cross-platform determinism guarantee.

## Next integration boundary

The failing rotational assembly stepper does not yet invoke this API. Next use it to compare full and half-step candidates while restoring interface histories and diagnostics alongside runtime state, then refine/reject based on the existing work/error budgets. Keep the failed oak/iron evidence until that complete trajectory passes its stated criteria. Runtime-v3 save migration, native promotion, other inertia adapters, persistent live joints, physical crafting/cutting and all remaining platform gates stay open.

## Build evidence

All test executables and the runtime cohesive probe rebuilt in both configurations. All 28 double-position suites pass in 25.76 s and all 26 legacy suites pass in 20.06 s. The new reversible-trial suite runs in 0.08/0.09 s respectively; that suite duration is not a per-trial performance guarantee. Windows 11 / MSVC 19.44 x64 Release / CMake 4.1.2 / Jolt 5.6. Unlike runtime cohesive assembly tests, this restore API is exercised in both precision configurations. Existing graphical applications were not relinked or restarted, and no new native interaction is claimed.
