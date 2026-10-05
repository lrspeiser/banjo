# Rover recovery recognition

October 5, 2026. Host/controller/UI repair against GitHub main `756ebb6e`,
Windows, Python 3.13, existing MSVC Release bundle `build/pickaxe-preview/Release`.
No native binaries, material laws, traction, grip limits or solver tolerances change.
Implementation and verification are published together; the task result records
the outgoing main revision. The owner's localhost port 18890 runs this checkpoint.

## Failure and repair

The owner's retained column world had nine deliveries (349.99 kg), a roughly
30 kg hopper, and three native escape attempts. Its `moving round` interruption
kept trying other mining stands and hid the exhausted native escape. Chat read
the latest movement request instead of the retained routine failure.

The host now observes native `stuck` immediately, before an asynchronous model
answer can overwrite it. A bounded recovery record retains location, time
and native reason. Routine retries and pending model actions hold; status, senses
and chat expose the recovery requirement. Explicit "unstuck" questions use the
record without a model call. Continue/closing chat cannot clear it. Explicit
reverse/steering remains available through existing native actuators.

Recovery clears only after measured displacement over 2 m, translation at most
0.05 m/s, turning at most 3 degrees/s, and release of the chassis grip. A declared
terrain world also requires a reported dry center (water depth at most 3 mm)
and slope within its declared climb limit. This is a center check, not a whole
assembly stability certificate; ordinary route checks still govern the next leg.
Earlier runtime v1 snapshots without recovery remain readable. Malformed recovery
records are rejected before assigning runtime state.

Inspection includes a direct controls/chat button and short recovery steps. Job
and hopper persist. A physically trapped rover still needs a successful motor
maneuver or the existing bounded grip; asking a model is not proof it escaped.
Battery depletion can separately prevent powered travel.

## Measurements

An isolated copy of the actual owner's saved world reproduced and latched native
failure at 5.2 simulated seconds. Ten further seconds produced no new mining or
delivery and preserved exact hopper quantities and the job. A full server restart
restored recovery/runtime exactly. Private rooms/database remain local only.

In that copy, an authenticated analytical observer used the normal 800 N / 60 N m
recovery grip, lifted, pulled and lowered onto surveyed dry ground. Native stepping
was `dt=1/240 s`. The rover moved from approximately `[7.8644,1.0422,2.8516] m`
to `[11.8402,0.9908,2.8392] m`; recovery cleared and the retained job resumed.
Peak sampled pull was 799.951 N; signed external hand work was 474.757 J.
Exact hopper mass 29.99833691271461 kg and its material contents were preserved.
No position assignment, impulse, terrain edit or inventory grant was used.
This is a controlled headless observer, not a measured browser walk/recovery or
full-pipeline conservation audit. It does not change the owner's actual rover pose.

## Verification

- `python tests/rover_brain_tests.py -q`: 66 pass, including actual native chat,
  immediate failure observation, obsolete pending decision rejection, persistence,
  legacy restore, corrupt restore and dry/wet/steep/held/moving clearance cases.
- `python tests/routine_language_tests.py -q`: 8 pass.
- `python tests/rover_order_tests.py -q`: 1 native order journey passes.
- `python tests/generated_rover_repeat_tests.py -q`: 2 pass in 109.2 s, including
  five actual 40 kg deliveries, processing and exact whole-server restart.
  The first run failed an exact 12 kg assertion at `12.000000000000002`.
  That receipt assertion now allows `1e-12 kg` binary-float summation error;
  the 200 kg total, five receipts and exact saved/restored records remain checked.
  No physical or implementation tolerance was changed.
- Python compilation, JavaScript syntax, whitespace and source registration pass:
  300/300 native sources registered in 15 CMake files, no exclusions.
- Owner's ordinary in-app browser: the retained rover shows "Stuck · Needs
  recovery", its 30 kg hopper (9 kg ore / 21 kg sand and soil), recovery steps
  and an honest stuck chat reply. Player 2's held pick and 37.5 kg rock inventory
  remain present. No browser recovery movement is claimed; the battery also
  reports roughly 3% charge with solar replenishment.

The scripted HTTP 529 and existing socket ResourceWarning in the brain test fixture
are not live provider failures. Tests use scripted or disabled models.
Remaining: qualify prevention of mined-pit trapping, retained-world self-recovery
and a complete ordinary browser approach/grip/release journey. General navigation
and physics scope is not closed by this recognition repair.
