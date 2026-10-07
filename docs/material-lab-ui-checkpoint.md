# First replacement UI stage: material response lab

**Current follow-up:** [Bounded fresh experiment commands](material-lab-live-checkpoint.md)
now extend this published baseline. This document retains the original replay-only
scope/evidence; the follow-up changes the disposable recording schema and lab
endpoint, without changing the retained World or material laws.

October 6, 2026. Source base main `886f475a`. The owner explicitly supports
small physical simulations and rebuilding the UI in stages. This checkpoint
adds a strict TypeScript experiment view and compiled CPU recording exporter.
The full rewrite remains active; the retained World demo on port 18890 is unchanged.

Implementation and evidence were published to GitHub main as
`55378ac49d13903ef1b1b882e3bfa0c84a7dd36b` on October 6. The evidence records
the tested workspace and actual binary/asset hashes before publication; its
base revision is provenance, not a claim that unmodified base main contains this UI.
This publication note adds no physical validation.

## What can be tried

Run [the launcher](../scripts/material-lab.py) and open
`http://127.0.0.1:18891/`. Select **Load & release** or **Pull apart**, compare all
three materials or focus one, play/pause the recorded response and scrub physical
time. Actual-size and explicitly labelled 100×/1000× displacement views make small
elastic motion inspectable. Work, broken bonds and free cells are the default
values; numerical/material details are in one closed disclosure.

The views show actual cell centres and surviving bonds, with free cells and
fixed supports distinguished. They do not invent fracture surfaces, fragment
velocities or an animation outcome. All samples come from the existing CPU
reference; replay does not advance a live world. Frames are selected exactly,
without interpolation across topology changes. No LLM is called on load/play.

This is a usable **recorded experiment viewer**, not a live edit/run interface,
physical handheld-tool experiment, new World client or calibrated material model.
The next UI stage must admit bounded live commands before claiming interactive
physics authoring. The [full audit](banjo-rewrite-audit.md) still governs migration
and retirement; the old client/controllers remain until their acceptance gates pass.

## Declared physical conditions

Six runs: glass/oak/iron × two interactions. Every run has a 250 mm cube,
50 mm cells, horizon 2, 125 positive-mass nodes, 1,261 initial bonds, 25 ideal
stationary bottom-face clamps, zero gravity/damping and initially zero motion.
The top-centre source cell receives the force below for 512 × 100 ns; the block
then continues unloaded for 128 steps. Twenty-one samples are recorded at 32-step
intervals over 64 µs. The positive-work ceiling is 50 kJ for the entire run, not
renewed each recorded chunk. Existing material-derived density/stiffness/strength,
seed 17, serial-double Verlet and `banjo-cpu-precise-v1` are retained.

- **Load & release:** (10,000, -20,000, 30,000) N.
- **Pull apart:** (0, 1,000,000, 0) N.

These are high laboratory traction inputs, not human/tool ratings. The wrapper
implements its existing isotropic elastic central-bond strength reference. It
does not implement grain, plastic flow, fatigue, calibrated crack work,
self-contact, settling or ground laws. Oak is laboratory-only; inorganic gameplay
policy remains unchanged. This export adds no material-law or tolerance change.

| Material | Mass kg | Load/release work J | Pull work J | Pull failed bonds | Pull free cells |
|---|---:|---:|---:|---:|---:|
| Glass | 39.0625 | 0.330535 | 4,110.255487 | 96 | 1 |
| Oak | 10.9375 | 1.764063 | 13,728.972518 | 56 | 1 |
| Iron | 122.96875 | 0.107536 | 197.689414 | 2 | 0 |

Gentler runs remain connected without failed bonds. Strong traction separates a
cell in glass/oak and leaves iron connected. Material inputs cause the differing
mass/motion/work; the exporter does not choose an outcome by name. The high-load
oak result is not a brittle preset or grain claim. Equal force/time does not supply
equal work. Source force/body energy is imposed externally; patch ledgers include
its work/impulse and ideal-support reactions, not a finite simulated source body.

[Evidence](evidence/material-lab/acceptance.json) records measured work, kinetic/
elastic energy, removed stored bond energy, integration error and residuals for
every material/input. Frame tests require energy closure within 1e-8 J and
linear/angular closure within 1e-8 SI **after measured integration/roundoff
attribution**. Numerical error remains reported, not erased or treated as heat;
this is not complete world conservation or material-realism certification.
Per-run wall cost includes stepping and sample capture/JSON assembly, excludes
final file encoding/startup, and is not a realtime/gameplay benchmark.
This captured run costs 135–165 ms per 64 µs experiment. Maximum energy closure
residual across the recorded frames is 1.34e-11 J; detailed per-material values
and separately retained numerical errors are in the evidence.

## Representation, identity and boundaries

The exporter stores immutable bond endpoints once per experiment and separate
alive/damage arrays per frame. This reduces the initial over-budget recording
to about 6.57 MB without changing any physical state. The viewer's 10 MB input
budget remains. This is packet compression, not air gaps, coarse material laws,
fracture caching or reuse of an outcome in a world.

The versioned client contract refuses incompatible schema/backend/input/time,
missing cells/topology, invalid/nonfinite units/state, duplicate experiments,
changed IDs and healed bond failures. It bounds sample and element counts before
drawing. A separate manifest records the actual exporter hash, workspace/source
hashes, revision and generated asset fingerprints. Checkout revision alone does
not establish that a binary was built from that checkout. Raw recordings/build
outputs stay ignored; the public evidence retains provenance and summaries.

The loopback-only read-only host serves six named assets and refuses directory
listing, other workspace paths, step APIs and POST. UTF-8 MIME types, no-store
and a same-origin content policy are explicit. It exposes no player saves,
credentials, mutation APIs or legacy game routes. It is not public-world auth,
network deployment or a physical-phone endpoint.

## Verification and current output

Windows x64, MSVC 19.44.35228, SDK 10.0.26100, Python 3.13.5, Node 22.18.0,
TypeScript 5.9.3; native Release.

- CMake builds `banjo_material_lab_record`; the four exporter/server checks use
  fresh actual CPU output rather than a canned physical trajectory.
- Three focused CTest entries pass: recording, solid patch and constituent transfer.
- Strict TypeScript compiles; three Node contract groups pass, including malformed
  clocks/inputs/cells, nonfinite data, topology and healed-failure negatives.
- CI adds a client compile/contract job; the native recording test is
  registered with CTest. This does not establish full CI or regression green.
- Source registration remains 311/311 under `src/` and `tests/`; the new tool's
  separate named CMake target also compiles. Static audit now includes `client/`.
- Actual in-app browser selects the strong pull, scrubs to 64 µs and displays
  glass/oak/iron results matching the export. Ordinary playback completes; an
  observer wait timed out before replay finished, and subsequent page state
  verified frame 20/Replay. No app exception remained.
- Desktop and 844×390 landscape / 390×844 portrait layouts show no horizontal
  overflow. Material selection and playback/scrubbing work; portrait scrolls.
  These are browser viewport checks, not physical-phone/touch acceptance.
- Final page console reports no errors/warnings. The initial recording-budget
  refusal and source-encoding defect were reproduced and fixed before publishing.

[Desktop comparison](evidence/material-lab/desktop-pull.jpg) and
[portrait view](evidence/material-lab/portrait-iron.jpg) retain visual evidence.
[Client instructions](../client/README.md) reproduce build, host and checks.

## Remaining stages

1. Bounded live experiment commands with solver/material/state identity, work
   budgets and accepted-time outcomes; compare custom declarations through the
   same compiler rather than scripted material-specific responses.
2. Finite-contact and release/settling/recontact views after their physical and
   clock/ownership boundaries qualify. Retain actual reactions and model refusals.
3. Shared World/Inventory/Build/Progress shell, deliberate chat and reusable
   desktop/touch intent adapters connected to the authenticated Rust world owner.
4. Durable world/private stock/product import, ordinary pickup/repeated use/
   collection/manufacture/restart and physical-phone journeys before retiring
   the retained host or controllers.

Four existing iron repeat failures, terrain activation, exact cell collision,
finite neighbours, supported soil/water/wear, full-world accounting, performance
and the 3.048 m excavation gate remain open. No active player world is reset.
